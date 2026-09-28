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


if __name__ == '__main__':
    if '--la' in sys.argv:
        D = directions()
        sp = {'chars': list(CHARS), 'w': 'vw_cap', 'sides': {c: D[c]['side'] for c in CHARS}}
        print(lookahead_test(sp))
    else:
        main(freeze='--freeze' in sys.argv)
