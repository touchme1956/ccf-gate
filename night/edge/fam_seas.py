#!/usr/bin/env python3
"""night/edge/fam_seas.py — 系統 seas（第6回）: 同じ暦の月の過去のリターン（季節性）の良い側の買いだけ vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.seas（線・費用・相手・期間は out/edge_prereg.json と同じ）。

  素材: JKP（Jensen・Kelly・Pedersen）米国の三分位ポートフォリオ（買いだけ）。特徴は4本——
    seas_1_1an    1年前の同じ暦の月のリターン（月 t の組なら t−11 の月＝来月と同じ暦の月）          Heston & Sadka 2008
    seas_2_5an    2〜5年前の同じ暦の月のリターンの平均                                                同上
    seas_6_10an   6〜10年前の同じ暦の月のリターンの平均                                               同上
    seas_11_15an  11〜15年前の同じ暦の月のリターンの平均                                              同上
  良い側 = 予言の向き（Heston-Sadka: 同じ暦の月に高かった株はその月にまた高い＝値の大きい '3.0' 側の予想）。
    JKP の因子は direction ×（'3.0' − '1.0'）なので、選定期間（〜2000-12）の米国データで 因子 と '3.0'−'1.0' の
    相関の符号から決め、三分位の平均の並び（1.0 < 2.0 < 3.0 か）でも確かめる（directions()）。spec に定数で凍結する。
  合成 = 良い側の脚を等分（毎月もとの比へ戻す）。**その月に使う脚がすべてそろい、どの脚も銘柄数が下限以上の月だけ**を返す。

  ⚠ JKP の ret は米国の短期金利（T-bill）を引いた**米ドルの超過**（fam_payout.py で確かめ済み:
    JKP mkt(vw) + French RF − French 市場 = 平均 0.0000/月）。総リターン = ret + RF。
  先読み: JKP の行の date は**リターンの月**で、組は前の月末（m−1 月末）の特徴で作る。seas_1_1an の最初の行が
    1927-01（CRSP のリターンは 1926-01 から＝1年前の同じ月が初めて存在する月）であることがこれと整合する
    （同じ月のリターンを信号に使っていれば 1926-01 から行があるはず）。銘柄数 n も組んだ時点の数。
    この規則はデータから何も推定しない（側と重みは凍結した spec の定数）ので、月 m のリターンは JKP の月 m の値・
    月 m の n・月 m の RF だけで決まる。lookahead_test() が切り詰め・ずらし・毒で確かめる。

  相手: French 米国市場（上限なしの時価加重・配当込み）。費用: 回転1あたり 0.25%・回転 600%/年（暦の月で入れ替える信号の置き値・
  事前登録 r6）＋等分の組は毎月の戻し。
  再現: JKP 先進国22か国（米国を除く）に同じ特徴・同じ側・同じ重み付けを当てる。国の相手は JKP mkt(vw) + 米国 RF（米ドル）。
  社数: 米国は三分位の銘柄数が 50 社以上の月だけ。再現の国は 20 社以上。

使い方: python3 night/edge/fam_seas.py            → 方向の確認と変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_seas.py --la       → 先読みの検査だけ
        python3 night/edge/fam_seas.py --freeze   → 選んで凍結（out/edge/spec_seas.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, json, math, random, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'seas',
    'name': '季節性（同じ暦の月の過去のリターンが高い側の三分位・Heston & Sadka 2008）',
    'implement': ('楽天証券の米国株（成長投資枠＝NISA で買える個別株・レバレッジではない）で、毎月末に米国上場の大型・中型株を'
                  '「来月と同じ暦の月の、過去数年のリターンの平均」で並べ、上位3分の1（数百社）を時価加重（1社の重みに上限＝JKP の vw_cap）'
                  'または上限なしの時価加重で持ち、毎月入れ替える。暦の月ごとに中身が大きく変わる（回転 600%/年と置いた）ので、'
                  '個人が手で回すには重い＝実際には時価総額の大きい順に数十社へ絞る近似になり、NISA の年間枠（成長投資枠 240万円）と'
                  '売買の手数料（楽天の米国株は約定代金の0.495%・上限22ドル）が効く。この信号で組む ETF は無い'
                  '（季節性の ETF は月替わり・11〜4月など市場全体の暦を使うもので、銘柄の季節性ではない）'),
}

COST = 0.0025            # 片道の回転1あたり（個別株の組・事前登録 costs）
TURN_ANN = 6.0           # 回転 600%/年（暦の月で入れ替える信号 seas_* の置き値・事前登録 r6）
CHARS = ['seas_1_1an', 'seas_2_5an', 'seas_6_10an', 'seas_11_15an']
MIN_N = 50               # 米国: 三分位の銘柄数がこれ未満の月は使わない（事前登録 r6）
MIN_N_REPL = 20          # 再現の国
DEV = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
       'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']           # 事前登録 r6 の先進国22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _load(region, ch, w):
    """→ {三分位: ({m: 超過}, {m: 銘柄数})}。h.jkp は n を返さないので、同じキャッシュを h.cached で読み h.guard を通す"""
    key = (region, ch, w)
    if key in _MEMO:
        return _MEMO[key]
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    r, n = {}, {}
    try:
        z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            try:
                m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
                r.setdefault(x['pf'], {})[m] = float(x['ret'])
                n.setdefault(x['pf'], {})[m] = int(float(x['n']))
            except (TypeError, ValueError, KeyError):
                continue
    except Exception:
        r, n = {}, {}
    _MEMO[key] = {s: (h.guard(r[s]), h.guard(n.get(s, {}))) for s in r}
    return _MEMO[key]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """→ (総リターン {m}, 片道の回転 {m})。spec: {'chars': [...], 'sides': {ch: '1.0'|'3.0'}, 'w': 'vw_cap'|'vw'}
    月 m に持つかどうかは、月 m の行（m−1 月末に組まれた三分位）の銘柄数 n だけで決まる。等分の組は毎月もとの比へ戻す"""
    L = []
    for c in spec['chars']:
        d = _load(region, c, spec['w'])
        s = spec['sides'][c]
        if s not in d:
            return {}, {}
        L.append(d[s])
    months = sorted(set.intersection(*[set(x[0]) for x in L]))
    k = len(L)
    tw = 1.0 / k
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(x[1].get(m, 0) < min_n for x in L):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(p - tw) for p in prev)
        ret[m] = sum(x[0][m] for x in L) / k + rf[m]
        tv[m] = TURN_ANN / 12 + reb
        g = [tw * (1 + x[0][m] + rf[m]) for x in L]
        tot = sum(g)
        prev = [v / tot for v in g] if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}

    def one(c):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')          # その国の市場（上限なしの時価加重・米ドルの超過）
        except Exception:
            return c, None
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t = build(spec, c, rf, spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        if len(r) < 24 or not bench:
            return c, None
        return c, {'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}
    with ThreadPoolExecutor(8) as ex:
        for c, x in ex.map(one, spec.get('replicate', [])):
            if x:
                out['markets'][c] = x
    return out


# ───────────────────────── 選定（〜2000-12） ─────────────────────────
def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def directions():
    """良い側を選定期間の米国データで決める: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号。
    実物の確認として三分位の平均（超過・%/月）の並びも出す（向きの判定には使わない＝記録だけ）"""
    out = {}
    for c in CHARS:
        d = _load('usa', c, 'vw_cap')
        p1, p3 = d['1.0'][0], d['3.0'][0]
        f = h.jkp('usa', c, 'factor', 'vw_cap')
        ms = sorted(set(f) & set(p1) & set(p3))
        r = _corr([f[m] for m in ms], [p3[m] - p1[m] for m in ms])
        means = {}
        for w in ('vw_cap', 'vw'):
            dw = _load('usa', c, w)
            means[w] = {s: round(S.mean(dw[s][0][m] for m in ms if m in dw[s][0]) * 100, 3) for s in ('1.0', '2.0', '3.0')}
        out[c] = {'side': '3.0' if r > 0 else '1.0', 'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms),
                  'from': ms[0], 'mean_excess_pct_per_month': means}
    return out


def variants(sides):
    """成績を見る前に固定した14本（scratchpad plan_seas.md）。数字や月を振らない＝経済的な筋の違うものだけ"""
    V = []
    for w in ('vw_cap', 'vw'):
        for c in CHARS:
            V.append((f'{c}|{w}', {'chars': [c], 'w': w}))
        V.append((f'all4|{w}', {'chars': list(CHARS), 'w': w}))
        # 1年前の同じ月（t−11）は 12−1 の勢いの窓の中に入る → それを外した「勢いと重ならない季節性」だけ
        V.append((f'long3(2_5+6_10+11_15)|{w}', {'chars': ['seas_2_5an', 'seas_6_10an', 'seas_11_15an'], 'w': w}))
        # 近いラグ（履歴が短い銘柄でも信号がそろう）
        V.append((f'near2(1_1+2_5)|{w}', {'chars': ['seas_1_1an', 'seas_2_5an'], 'w': w}))
    for _, s in V:
        s['sides'] = {c: sides[c] for c in s['chars']}
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    return round(bt, 2), round((my - bt * mx) * 1200, 2)


SUBS = (('〜1962', None, 196212), ('1963-1985', 196301, 198512), ('1986-2000', 198601, 200012))


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    D = directions()
    sides = {c: D[c]['side'] for c in CHARS}
    rows = []
    for name, sp in variants(sides):
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        st0 = h.stats(r, mk, rf, b=h.SEL_END)                     # 費用の前（参考）
        sub = {}
        for lab, a, b in SUBS:
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        stc = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'spec': sp, 'stats': st, 'gross_excess': st0['excess'] if st0 else None, 'sub': sub,
                     'beta': bt, 'alpha_capm': al, 'ex_vs_jkp_capped_mkt': stc['excess'] if stc else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
    return D, rows


def lookahead_test(spec):
    """(1) 切り詰め: JKP の脚（リターン・銘柄数）と RF を月 X で切って作り直しても、X までの規則のリターン・回転が完全一致
       (2) ずらし: X より後の脚の値を1か月ずらして壊しても、X までは不変（後ろは変わる＝検査が空回りしていない）
       (3) 毒: X より後の脚のリターン・銘柄数・RF を乱数に置き換えても X までは不変
       (4) 月合わせ: 月 m の総リターン = 脚の月 m の超過の等分 + 月 m の RF（1脚の規則で差の最大を測る）
       (5) 側（信号）は spec の定数で、データから再推定しない"""
    mk, rf = h.us_market()
    full, tvf = build(spec, 'usa', rf, MIN_N)
    saved = {k: v for k, v in _MEMO.items()}
    keys = [('usa', c, spec['w']) for c in spec['chars']]
    res = {}
    cuts = [195012, 197012, 198512, 199512, 199912]
    ok1 = ok2 = ok3 = True
    rng = random.Random(20260928)
    try:
        for X in cuts:
            # (1) 切り詰め
            for k in keys:
                _MEMO[k] = {s: ({m: v for m, v in r.items() if m <= X}, {m: v for m, v in n.items() if m <= X})
                            for s, (r, n) in saved[k].items()}
            rfX = {m: v for m, v in rf.items() if m <= X}
            part, tvp = build(spec, 'usa', rfX, MIN_N)
            ok1 &= set(part) == {m for m in full if m <= X}
            ok1 &= all(abs(part[m] - full[m]) < 1e-15 and abs(tvp[m] - tvf[m]) < 1e-15 for m in part)
            # (2) ずらし
            for k in keys:
                _MEMO[k] = {s: ({m: (v if m <= X else r.get(h.add_months(m, -1), v)) for m, v in r.items()},
                                {m: (v if m <= X else n.get(h.add_months(m, -1), v)) for m, v in n.items()})
                            for s, (r, n) in saved[k].items()}
            part, tvp = build(spec, 'usa', rf, MIN_N)
            ok2 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(tvp[m] - tvf[m]) < 1e-15 for m in full if m <= X)
            ok2 &= any(abs(part.get(m, 9) - full[m]) > 1e-12 for m in full if m > X)
            # (3) 毒
            for k in keys:
                _MEMO[k] = {s: ({m: (v if m <= X else rng.uniform(-0.5, 0.5)) for m, v in r.items()},
                                {m: (v if m <= X else rng.randint(0, 3000)) for m, v in n.items()})
                            for s, (r, n) in saved[k].items()}
            rfP = {m: (v if m <= X else rng.uniform(0, 0.02)) for m, v in rf.items()}
            part, tvp = build(spec, 'usa', rfP, MIN_N)
            ok3 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(tvp[m] - tvf[m]) < 1e-15 for m in full if m <= X)
            ok3 &= any(abs(part.get(m, 9) - full[m]) > 1e-12 for m in full if m > X)
    finally:
        for k in keys:
            _MEMO[k] = saved[k]
    res['truncate'] = ok1
    res['shift_future'] = ok2
    res['poison_future'] = ok3
    # (4) 月合わせ
    L = [_load('usa', c, spec['w'])[spec['sides'][c]][0] for c in spec['chars']]
    d = max(abs(full[m] - rf[m] - sum(x[m] for x in L) / len(L)) for m in full)
    res['month_align_maxdiff'] = d
    res['sides_constant'] = bool(spec.get('sides'))
    # 信号の時点: seas_1_1an の最初の行が 1927-01（CRSP のリターン 1926-01 の1年後）か
    first = {c: min(_load('usa', c, 'vw_cap')['3.0'][0]) for c in CHARS}
    res['first_row'] = first
    res['first_row_ok'] = first['seas_1_1an'] >= 192701
    res['ok'] = ok1 and ok2 and ok3 and d < 1e-12 and res['sides_constant'] and res['first_row_ok']
    return res


def _fmt(r):
    st = r['stats']
    return (f"{r['name']:30s} {st['from']}〜 ex {st['excess']:+6.2f} (前 {r['gross_excess']:+6.2f}) t {st['t']:5.2f} NW {st['t_nw']:5.2f} "
            f"vol {st['vol']:5.1f}/{st['bench_vol']:5.1f} dd {st['maxdd']:6.1f}/{st['bench_maxdd']:6.1f} β {r['beta']} α {r['alpha_capm']:+} "
            f"対capmkt {r['ex_vs_jkp_capped_mkt']:+} 回転 {r['turnover_yr']} 10年窓 {st['roll10_win']} 部分 {r['sub']}")


def main(freeze=False):
    D, rows = select()
    print('directions', json.dumps(D, ensure_ascii=False))
    for r in rows:
        print(_fmt(r))
    if not freeze:
        return D, rows
    ok = [r for r in rows if r['stats'] and r['stats']['excess'] >= 1.0]
    if ok:
        best = max(ok, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間＝各変種のデータの始まり〜2000-12・費用後の超過 +1%/年以上の中で t が最大）'
    else:
        best = max(rows, key=lambda r: r['stats']['t'])
        how = ('どの変種も費用後 +1%/年 に届かなかった。いちばん筋の良い一つとして、費用後の t が最大の変種を選んだ'
               '（事前登録の線には届いていない＝ホールドアウトで確かな勝ちになる見込みは低い）')
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': list(DEV), 'turn_ann': TURN_ANN,
                 'side_note': "'3.0' = 特徴の値が大きい側＝同じ暦の月の過去のリターンが高い三分位"})
    la = lookahead_test(spec)
    assert la['ok'], la
    out = run(spec)
    st = h.stats(out['ret'], out['bench'], out['rf'], b=h.SEL_END, turnover=out['turnover'], cost=out['cost'])
    mkt_sel = {}
    for c, x in out['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('先読み:', la)
    print('他の市場（選定期間・参考）:', mkt_sel)
    return best, spec, st, la, mkt_sel, D, rows, how, out


LOOKAHEAD = ('lookahead_test() で確かめた（選んだ規則と4本の等分の両方・食い違い0）: '
             '(1) 切り詰め: JKP の脚（リターンと銘柄数）と RF を 1950-12/1970-12/1985-12/1995-12/1999-12 で切って作り直しても、'
             '切った月までの規則のリターンと回転が完全一致（持つ月の集合も同じ）。'
             '(2) ずらし: 切った月より後の脚の値と銘柄数を1か月ずらして壊しても、それより前は不変（後ろは変わる＝検査が空回りしていない）。'
             '(3) 毒: 切った月より後の脚のリターン・銘柄数・RF を乱数に置き換えても、それより前は不変（後ろは変わる）。'
             '(4) 月合わせ: 月 m の総リターン = 脚の月 m の超過の等分 + 月 m の RF（差の最大 1e-16 未満）。'
             '(5) 側（信号）は spec の定数で、データから再推定しない。'
             '(6) 信号の時点: JKP の行の date はリターンの月で、組は前の月末の特徴。最初の行が seas_1_1an 1927-01・seas_2_5an 1931-01・'
             'seas_6_10an 1936-01・seas_11_15an 1941-01＝どれも「いちばん古いラグが CRSP の最初のリターン 1926-01 にちょうど届く月」で、'
             '信号が月 m の12か月以上前のリターンだけで作られていることと整合する（同じ月のリターンを使っていれば行はもっと早く始まる）。'
             '銘柄数 n も組んだ時点（m−1 月末）の数で、持つかどうかの判定（50社以上）に使う')


def mom_alpha(ret, tv, mk, rf, b=None):
    """市場＋勢い（French の Mom）で回帰した費用後のα（%/年）と t・勢いへの感応度（参考）"""
    import numpy as np
    d = h.french('F-F_Momentum_Factor')
    t0 = next(iter(d))
    umd = d[t0][next(iter(d[t0]))]
    ms = [m for m in sorted(ret) if m in umd and m in mk and m > 9999 and (b is None or m <= b)]
    X = np.array([[1.0, mk[m] - rf[m], umd[m] / 100] for m in ms])
    y = np.array([ret[m] - tv[m] * COST - rf[m] for m in ms])
    c = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ c
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * e.var(ddof=3))
    return {'alpha_after_cost_pct_yr': round(float(c[0]) * 1200, 2), 't': round(float(c[0] / se[0]), 2),
            'beta_mkt': round(float(c[1]), 2), 'umd_loading': round(float(c[2]), 3), 'from': ms[0], 'to': ms[-1]}


def freeze():
    best, spec, st, la, mkt_sel, D, rows, how, out = main(freeze=True)
    mk, rf = h.us_market()
    la_all4 = lookahead_test({'chars': list(CHARS), 'w': spec['w'], 'sides': {c: D[c]['side'] for c in CHARS}})
    assert la_all4['ok'], la_all4
    ma = mom_alpha(out['ret'], out['turnover'], mk, rf, b=h.SEL_END)
    reb = round((best['turnover_yr'] - TURN_ANN) * 100, 1)
    capshare = round((st['excess'] - best['ex_vs_jkp_capped_mkt']) / st['excess'] * 100) if st['excess'] else None
    # 回転の置き値の感度（参考・選定期間。事前登録の置き値 600%/年は変えない）
    r, tv = build(spec, 'usa', rf, MIN_N)
    sens = {}
    for ta in (8.0, 10.0):
        t2 = {m: ta / 12 + (tv[m] - TURN_ANN / 12) for m in tv}
        s2 = h.stats(r, mk, rf, b=h.SEL_END, turnover=t2, cost=COST)
        sens[f'{int(ta * 100)}%/年'] = {'excess': s2['excess'], 't': s2['t']}
    sub = best['sub']
    others = {x['name']: x for x in rows}
    a4, l3, s1 = others['all4|vw_cap'], others['long3(2_5+6_10+11_15)|vw_cap'], others['seas_1_1an|vw_cap']
    vwv = others['near2(1_1+2_5)|vw']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    rationale = (
        '【規則】米国上場株を毎月末に JKP の seas_1_1an（1年前の、来月と同じ暦の月のリターン）と seas_2_5an（2〜5年前の同じ暦の月の平均）で'
        'それぞれ三分位に分け、両方の上の三分位（\'3.0\'＝同じ暦の月に高かった側）を上限つきの時価加重（JKP vw_cap）で持ち、二つの組を等分して毎月戻す。'
        '【なぜ】Heston & Sadka 2008（JFE・データ 1965-2002）: ある株の月 t のリターンは、12・24・36…か月前（同じ暦の月）のリターンと正に相関し、'
        'この関係は20年先のラグまで続き、ほかの月のラグでは続かない＝勢い（12−1）や反転とは別の現象。'
        '経済的な筋: 決算発表・配当・税（1月効果）・機関の決まった月の資金の出入りなど、会社ごとに暦で繰り返す事情が、同じ月に同じ向きの需要や'
        'リスクの上乗せを作る（Heston-Sadka は規模・業種・配当・決算発表の月では説明しきれないと報告）。近いラグ（1年と2〜5年）は銘柄の履歴が5年あればそろうので'
        '被覆が広い。⚠ 1年前の同じ月（t−11）は 12−1 の勢いの窓の中にあるが、市場＋勢い（French の Mom）で回帰すると'
        f'勢いへの感応度は {ma["umd_loading"]:+}、費用後のαは {ma["alpha_after_cost_pct_yr"]:+}%/年（t {ma["t"]}）残る＝勢いの言い換えではない。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後（回転 600%/年×0.25%＝年1.5%を引いた後）の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年（費用前 {best["gross_excess"]:+}）、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα（費用前）{best["alpha_capm"]:+}%/年。'
        f'JKP の上限つき市場（vw_cap）に対しては {best["ex_vs_jkp_capped_mkt"]:+}%/年＝超過の約{capshare}%は上限つきの重み（中型寄り）の分。'
        f'部分期間: 〜1962 {sub["〜1962"]["excess"]:+}%/年（t {sub["〜1962"]["t"]}）・1963-1985 {sub["1963-1985"]["excess"]:+}（t {sub["1963-1985"]["t"]}）・'
        f'1986-2000 {sub["1986-2000"]["excess"]:+}（t {sub["1986-2000"]["t"]}）＝効きは時代とともに小さくなっている。'
        f'回転の置き値の感度（参考）: 800%/年なら {sens["800%/年"]["excess"]:+}（t {sens["800%/年"]["t"]}）・1000%/年なら {sens["1000%/年"]["excess"]:+}（t {sens["1000%/年"]["t"]}）'
        '——暦の月ごとに信号が別の月のリターンになるので実際の回転は置き値より重いかもしれない。'
        f'【選び方】{how}。14変種のうち線（+1%/年）を越えたのは {sum(1 for x in rows if x["stats"]["excess"] >= 1.0)} 本。'
        f'次点は 4本の等分・vw_cap（{a4["stats"]["excess"]:+}・t {a4["stats"]["t"]}・1941〜）、長いラグ3本・vw_cap（{l3["stats"]["excess"]:+}・t {l3["stats"]["t"]}）。'
        f'単独で t が最大の seas_1_1an・vw_cap（{s1["stats"]["excess"]:+}・t {s1["stats"]["t"]}）は 1986-2000 が {s1["sub"]["1986-2000"]["excess"]:+}。'
        f'同じ組の上限なし（vw）は {vwv["stats"]["excess"]:+}（t {vwv["stats"]["t"]}）＝巨大株まで入れると弱い。'
        '良い側は選定期間の米国データで確かめた（因子と 3.0−1.0 の相関 +1.000・三分位の平均が4本とも 1.0<2.0<3.0 の順）。'
        f'【他の市場（選定期間・参考）】JKP の先進国のうち選定期間に20社以上の月が24か月以上ある {len(mkt_sel)} か国で、超過が正は {pos}。'
        '国のデータは 1987〜1991 年ごろからで短く、選定期間の国の比較はほぼ雑音。'
        '【予想】事前登録 r6 の予想どおり、回転が重いので費用後は弱い側。選定期間の t は大きいが 1986 年以降に縮んでおり、公表（2008）後のホールドアウトで '
        '+1%/年・t≥2 を満たすかは疑わしい。'
    )
    tbl = [{'name': x['name'], 'from': x['stats']['from'], 'excess': x['stats']['excess'], 't': x['stats']['t'],
            't_nw': x['stats']['t_nw'], 'gross_excess': x['gross_excess'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm_gross': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    extra = {
        'implement': FAMILY['implement'],
        'family_name': FAMILY['name'],
        'lookahead_test': LOOKAHEAD,
        'lookahead_result': {'selected': la, 'all4': la_all4},
        'directions': D,
        'variants_table': tbl,
        'variants_plan': '成績を見る前に固定した14本（単独4本×重み2・4本の等分×2・長いラグ3本×2・近いラグ2本×2）。scratchpad の plan_seas.md',
        'turnover_sensitivity_selection': sens,
        'momentum_adjusted_alpha_selection': dict(ma, note='French の Mkt-RF と Mom で回帰（選定期間・参考）'),
        'markets': list(DEV),
        'markets_selection_period': mkt_sel,
        'markets_note': '国は JKP の3文字（run() の markets のキーと同じ）。相手はその国の JKP mkt(vw)+米国 RF（米ドル）。'
                        '脚の三分位がどちらも20社以上の月だけ・24か月未満の国は run() が落とす（選定期間では9か国が落ちる。ホールドアウトでは全期間を読むので増える）',
        'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重・配当込み）',
        'cost_note': '片道の回転1あたり 0.25%。回転は脚ごとに 600%/年（事前登録 r6 の seas_* の置き値）＋二つの組を毎月等分へ戻す売買（選んだ規則で実測 約' + str(reb) + '%/年）',
    }
    doc = h.save_spec('seas', spec, rationale, len(rows), st, extra)
    print('FROZEN', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    if '--save' in sys.argv:
        freeze()
    elif '--la' in sys.argv:
        D = directions()
        sp = {'chars': list(CHARS), 'w': 'vw_cap', 'sides': {c: D[c]['side'] for c in CHARS}}
        print(lookahead_test(sp))
    else:
        main(freeze='--freeze' in sys.argv)
