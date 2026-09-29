#!/usr/bin/env python3
"""night/edge/fam_valtime.py — 系統 valtime：割高さ（CAPE・配当利回り・超過CAPE利回り）で株の比率を 0.5〜1.5 の間で変える

事前登録 out/edge_prereg.json の round1_families.valtime（予想: 弱い）。読むだけ・門の採点に不使用。
データはすべて harness（h.shiller / h.us_market）経由で読む＝選定の段（EDGE_PHASE=select）では 2000-12 で切れている。

■ 規則（月次・前月末までのデータだけで決める）
  株の比率 w_m = 1 ± slope × (その時点までの百分位 − 0.5)、0.5〜1.5 に切る
    ・割高さの指標が高い（CAPE が高い）ほど株を減らす／利回り（配当利回り・超過CAPE利回り）が高いほど株を増やす
    ・w < 1 の残りは 10年債（GS10 から作る月次リターン）か 短期金利
    ・w > 1 の分は 借りる：短期金利＋0.4%/年、さらにレバレッジ型の経費 0.9%/年（事前登録の費用。保守側）
  相手＝株100%（同じ Shiller の配当込み S&P：(P_m + D_m/12)/P_{m−1} − 1）。費用＝回転1あたり 0.1%

■ 先読みを避けるための遅れ（結果を見る前に決めた・変種ではない）
  ・E・D は 15か月遅らせて使う：1926年以前は年次の値を月へ直線補間しており（年の値は12月に置かれる）、
    1月の値にもその年の12月の値が混ざる＝公表は翌年の初め。15か月あれば最悪の場合も既知
  ・GS10 は 1953-03 以前は1月の値の直線補間（翌年1月の値が混ざる）→ 信号には 12か月前の値を使う。1953-04 以降は月平均の実測＝その月末に既知
  ・CPI は1か月遅らせる（その月の CPI は翌月に公表）
  ・P は月平均の株価＝その月末に既知
"""
import sys, os, math, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'valtime',
    'name': '割高さで株の比率を変える（CAPE・配当利回り・超過CAPE利回りの百分位で 0.5〜1.5 倍）',
    'implement': ('楽天証券で、株は米国株全体・S&P500 の ETF（VTI/VOO）か投資信託（eMAXIS Slim 米国株式〔S&P500〕＝NISA可）、'
                  '残りは米国中期国債 ETF（IEF 等）か 円/米ドルの MMF・預金。1倍を超える分は 米国株信用取引 か 2倍型 ETF（SSO）で持つ'
                  '＝NISA 不可・課税口座。信号は月1回（CAPE は Shiller のサイトで毎月更新）で、比率の動きは遅いので実際の売買は年に数回')
}

ELAG = 15            # E・D を使う遅れ（か月）
CPILAG = 1           # CPI の遅れ
GS_INTERP_END = 195303   # これ以前の GS10 は年1回の値の直線補間
GSLAG_OLD = 12
SPREAD = 0.004       # 借入の上乗せ（年）
LEVFEE = 0.009       # 1倍を超える分の経費（年）
COST = 0.001         # 回転1あたり
START = 189101       # すべての変種で同じ始まり（信号がそろう後）

DEFAULT = {'signal': 'cape_pct', 'slope': 1.0, 'resid': 'bond', 'lo': 0.5, 'hi': 1.5, 'minhist': 60, 'window': 0, 'start': START,
           'equity': 'french_splice'}
# equity: 'french_splice'＝1926-07 以降は Ken French の米国市場（月末から月末・配当込み＝事前登録の『米国の規則』の相手・VTI に近い）、
#         それ以前は Shiller の配当込み S&P（月平均の株価）。'shiller'＝全期間 Shiller。相手はどちらでも『規則の株の脚そのもの』
#         （結果を見る前に french_splice に決めた。理由: Shiller の月平均の株価のリターンは前月の後半の値動きを含み〔Working 効果〕、
#          月末に売買する人は取れない。1926年以降は取れるリターンで比べる）


# ───────────────────────── 素材 ─────────────────────────
def _series(rows):
    """月→値（欠測は直前の値を引き継ぐ。P の欠測はそこで系列を止める）"""
    ms, P, D, E, CPI, GS = [], {}, {}, {}, {}, {}
    last = {}
    for r in sorted(rows, key=lambda x: x['m']):
        if r['P'] is None:
            break
        m = r['m']
        if ms and m != h.add_months(ms[-1], 1):
            break
        ms.append(m)
        P[m] = r['P']
        for k, dst in (('D', D), ('E', E), ('CPI', CPI), ('GS10', GS)):
            v = r[k]
            if v is not None:
                last[k] = v
            dst[m] = last.get(k)
    return ms, P, D, E, CPI, GS


def _gs_known(GS, s):
    """月末 s に分かっている 10年債利回り（%）"""
    if s <= GS_INTERP_END:
        return GS.get(h.add_months(s, -GSLAG_OLD))
    return GS.get(s)


def _cape(P, E, CPI, s):
    """月末 s に分かる CAPE：P_s を CPI_{s−1} で実質化 ÷ E の実質の10年平均（E は ELAG 遅らせる）"""
    c = CPI.get(h.add_months(s, -CPILAG))
    if c is None or P.get(s) is None:
        return None
    vals = []
    for k in range(ELAG, ELAG + 120):
        mk = h.add_months(s, -k)
        e, ck = E.get(mk), CPI.get(mk)
        if e is None or ck is None or ck <= 0:
            return None
        vals.append(e / ck)
    avg = sum(vals) / len(vals)
    return (P[s] / c) / avg if avg > 0 else None


def raw_signal(name, ms, P, D, E, CPI, GS):
    """{s: 値}（s＝月末。その月末に分かるデータだけ）。向き: 大きいほど『株に有利』に揃える"""
    out = {}
    for s in ms:
        if name.startswith('cape'):
            c = _cape(P, E, CPI, s)
            if c:
                out[s] = -math.log(c)                     # 割安ほど大きい
        elif name.startswith('ecy'):
            c = _cape(P, E, CPI, s)
            g = _gs_known(GS, s)
            c1, c0 = CPI.get(h.add_months(s, -CPILAG)), CPI.get(h.add_months(s, -CPILAG - 120))
            if c and g is not None and c1 and c0:
                infl = (c1 / c0) ** (1 / 10) - 1
                out[s] = 1 / c - (g / 100 - infl)
        elif name.startswith('dp'):
            d = D.get(h.add_months(s, -ELAG))
            if d is not None and d > 0 and P.get(s):
                out[s] = math.log(d / P[s])
        else:
            raise ValueError(name)
    return out


def pct_signal(raw, minhist=60, window=0):
    """{s: 百分位}（その時点までの値の中で、s の値以下の割合。window>0 なら直近 window か月だけ）"""
    ks = sorted(raw)
    out, srt = {}, []
    for i, s in enumerate(ks):
        x = raw[s]
        if window:
            hist = sorted(raw[k] for k in ks[max(0, i - window + 1):i + 1])
            n = len(hist)
            p = bisect.bisect_right(hist, x) / n
        else:
            bisect.insort(srt, x)
            n = len(srt)
            p = bisect.bisect_right(srt, x) / n
        if n >= minhist:
            out[s] = p
    return out


def weights(spec, rows):
    """{m: 株の比率}（m＝持つ月。m−1 月末までのデータだけ）。信号が無い月は 1（相手と同じ）"""
    sp = dict(DEFAULT, **spec)
    ms, P, D, E, CPI, GS = _series(rows)
    raw = raw_signal(sp['signal'], ms, P, D, E, CPI, GS)
    pc = pct_signal(raw, sp['minhist'], sp['window'])
    w = {}
    for s in ms:
        m = h.add_months(s, 1)
        p = pc.get(s)
        x = 1.0 if p is None else 1 + sp['slope'] * (p - 0.5)
        w[m] = min(sp['hi'], max(sp['lo'], x))
    return w


# ───────────────────────── 月次リターン ─────────────────────────
def bond_ret(y0, y1, n=10.0):
    """10年の額面債（年1回の利払い・利回り y0 で買う）を1か月持って利回り y1 で売る"""
    y0, y1 = y0 / 100, y1 / 100
    nn = n - 1 / 12
    if y1 <= 0:
        return y0 / 12
    price = (y0 / y1) * (1 - (1 + y1) ** (-nn)) + (1 + y1) ** (-nn)
    return price - 1 + y0 / 12


def run(spec, rows=None, market=None):
    """rows・market は先読みの検査のためだけに差し替えられる（統括の evaluate.py は run(spec) で呼ぶ＝harness から読む）"""
    sp = dict(DEFAULT, **spec)
    rows = h.shiller() if rows is None else rows
    ms, P, D, E, CPI, GS = _series(rows)
    fmk, frf = h.us_market() if market is None else market
    w = weights(sp, rows)
    ret, bench, rf, tov, wt = {}, {}, {}, {}, {}
    prev_w = prev_rs = prev_r = None
    last_rf = None
    for a, m in zip(ms, ms[1:]):
        if m < sp['start']:
            continue
        if sp['equity'] == 'french_splice' and m >= 192607:
            if m not in fmk:
                break                                   # French が切れたらそこで止める（Shiller と混ぜない）
            rs = fmk[m]
        else:
            rs = (P[m] + (D[m] or 0) / 12) / P[a] - 1
        g0, g1 = GS.get(a), GS.get(m)
        rb = bond_ret(g0, g1) if g0 is not None and g1 is not None else 0.0
        if m in frf:
            f = frf[m]; last_rf = f
        elif m < 192607:
            f = (g0 or 0) / 1200
        else:
            f = last_rf if last_rf is not None else (g0 or 0) / 1200
        x = w.get(m, 1.0)
        ro = rb if sp['resid'] == 'bond' else f
        if x <= 1:
            r = x * rs + (1 - x) * ro
        else:
            r = x * rs - (x - 1) * (f + (SPREAD + LEVFEE) / 12)
        if prev_w is None:
            tv = abs(x - 1.0)
        else:
            drift = prev_w * (1 + prev_rs) / (1 + prev_r) if (1 + prev_r) > 0 else prev_w
            tv = abs(x - drift)
        ret[m], bench[m], rf[m], tov[m], wt[m] = r, rs, f, tv, x
        prev_w, prev_rs, prev_r = x, rs, r
    return {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': tov, 'cost': COST, 'markets': {}, 'weight': wt}


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec=None, cuts=(189512, 190712, 192112, 192906, 193712, 195112, 196512, 197312, 198212, 199412, 200005)):
    """(1) データを c 月末で切って作った比率が、全データで作った比率と m ≤ c+1 のすべてで一致する
    (2) c+1 月以降のデータを乱しても m ≤ c+1 の比率が変わらない
    (3) 比率 w_m を使うリターンは m 月のリターン（run の中で w.get(m) を m の rs に掛けている）"""
    import random
    specs = [spec] if spec else [dict(signal=s, window=wd) for s in ('cape_pct', 'ecy_pct', 'dp_pct') for wd in (0, 240)]
    rows = h.shiller()
    bad = []
    for sp in specs:
        full = weights(sp, rows)
        for c in cuts:
            tr = [r for r in rows if r['m'] <= c]
            wt = weights(sp, tr)
            for m, x in wt.items():
                if m <= h.add_months(c, 1) and abs(full.get(m, 1.0) - x) > 1e-12:
                    bad.append(('truncate', sp, c, m, x, full.get(m)))
            rnd = random.Random(c)
            pert = [dict(r) if r['m'] <= c else {**r, 'P': r['P'] * rnd.uniform(0.3, 3), 'E': (r['E'] or 1) * rnd.uniform(0.3, 3),
                                                  'D': (r['D'] or 1) * rnd.uniform(0.3, 3), 'CPI': r['CPI'] * rnd.uniform(0.5, 2),
                                                  'GS10': r['GS10'] * rnd.uniform(0.5, 2)} for r in rows]
            wp = weights(sp, pert)
            for m in full:
                if m <= h.add_months(c, 1) and abs(full[m] - wp.get(m, 1.0)) > 1e-12:
                    bad.append(('perturb', sp, c, m, full[m], wp.get(m)))
            # 未来を乱したら c+2 以降のどこかは変わる（検査が空回りしていないこと）
            if not any(abs(full[m] - wp.get(m, 1.0)) > 1e-9 for m in full if m > h.add_months(c, 1)):
                bad.append(('insensitive', sp, c))
    # (4) run の水準：c+1 月以降の Shiller と French を乱しても、m ≤ c のリターン・相手・回転は変わらない
    mk, rf = h.us_market()
    for sp in specs:
        for resid in ('bond', 'cash'):
            s2 = dict(sp, resid=resid, slope=2.0)
            base = run(s2, rows, (mk, rf))
            for c in cuts:
                rnd = random.Random(c + 7)
                pr = [dict(r) if r['m'] <= c else {**r, 'P': r['P'] * rnd.uniform(0.3, 3), 'E': (r['E'] or 1) * rnd.uniform(0.3, 3),
                                                    'D': (r['D'] or 1) * rnd.uniform(0.3, 3), 'CPI': r['CPI'] * rnd.uniform(0.5, 2),
                                                    'GS10': r['GS10'] * rnd.uniform(0.5, 2)} for r in rows]
                pm = ({m: (v if m <= c else v * rnd.uniform(-3, 3)) for m, v in mk.items()},
                      {m: (v if m <= c else v * rnd.uniform(0, 3)) for m, v in rf.items()})
                x = run(s2, pr, pm)
                for k in ('ret', 'bench', 'turnover', 'weight'):
                    for m, v in base[k].items():
                        if m <= c and abs(v - x[k].get(m, 9e9)) > 1e-12:
                            bad.append(('run', k, s2, c, m)); break
                # 比率は c+1 月まで変わらない（c 月末までのデータで決まる）
                m1 = h.add_months(c, 1)
                if m1 in base['weight'] and abs(base['weight'][m1] - x['weight'].get(m1, 9e9)) > 1e-12:
                    bad.append(('run-weight-next', s2, c))
    return bad


if __name__ == '__main__':
    b = lookahead_test()
    print('先読みの検査:', 'OK' if not b else b[:10])
