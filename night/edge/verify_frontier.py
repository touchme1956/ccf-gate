#!/usr/bin/env python3
"""night/edge/verify_frontier.py — 第10回の検証（判定は変えない）: frontier（フロンティアの国の等加重）の上乗せはどこから来たか

  (1) 国ごとの寄与（2001年以降・算術の超過を国の等分で分けたもの）
  (2) 為替の作り物が疑われる国を外す: ジンバブエ（2007-08年のハイパーインフレ期・公定為替で米ドルへ換算）、ベネズエラ（為替統制・公定為替）
  (3) 月次リターンを ±50% で切った版、国の中央値で等加重の代わりにした版
  (4) 実在の器 FM（iShares MSCI Frontier and Select EM・2012〜）と、JKP frontier 地域の時価加重（凍結しなかった変種）
  出力: out/edge/verify_frontier.json
"""
import os, sys, json, statistics as S, datetime
os.environ['EDGE_PHASE'] = 'holdout'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h  # noqa: E402
import fam_frontier as F  # noqa: E402


def build(data, rf, mkt, drop=(), clip=None, agg='mean'):
    ret = {}
    for m in sorted(set().union(*[set(r) for r, n in data.values()])):
        if m not in mkt or m not in rf:
            continue
        p = h.add_months(m, -1)
        xs = [data[c][0][m] for c, (r, n) in data.items() if c not in drop and n.get(p, 0) >= F.MIN_N and m in r]
        if not xs:
            continue
        if clip:
            xs = [max(-clip, min(clip, x)) for x in xs]
        ret[m] = (S.mean(xs) if agg == 'mean' else S.median(xs)) + rf[m] - F.FEE / 12
    return ret


def main():
    mkt, rf = h.us_market()
    cs = F.frontier_countries()
    data = {c: F.country_mkt(c) for c in cs}
    nm = len([m for m in mkt if m >= h.HOLD_START])
    contrib = {}
    for m in sorted(mkt):
        if m < h.HOLD_START:
            continue
        p = h.add_months(m, -1)
        hold = [c for c, (r, n) in data.items() if n.get(p, 0) >= F.MIN_N and m in r]
        for c in hold:
            contrib[c] = contrib.get(c, 0) + (data[c][0][m] + rf[m] - mkt[m]) / len(hold)
    contrib = {c: round(v / nm * 1200, 2) for c, v in sorted(contrib.items(), key=lambda z: -z[1])}
    cases = {
        '凍結した規則（全フロンティアの国）': {},
        'ジンバブエを外す': {'drop': ('zwe',)},
        'ジンバブエとベネズエラを外す': {'drop': ('zwe', 'ven')},
        '月次を±50%で切る': {'clip': 0.5},
        '国の中央値': {'agg': 'median'},
    }
    out = {}
    for k, kw in cases.items():
        r = build(data, rf, mkt, **kw)
        st = h.stats(r, mkt, rf, a=h.HOLD_START)
        sel = h.stats(r, mkt, rf, b=h.SEL_END)
        out[k] = {'holdout': st, 'selection': sel}
        print(k, '検定', st['excess'], 't', st['t'], 'NW', st['t_nw'], '10年窓', st['roll10_win'], '| 選定', sel['excess'], sel['t'])
    reg = {w: {m: v + rf[m] - F.FEE / 12 for m, v in h.jkp('frontier', 'mkt', 'factor', w).items() if m in rf} for w in ('vw', 'ew')}
    for w, r in reg.items():
        st = h.stats(r, mkt, rf, a=h.HOLD_START)
        out[f'JKP frontier 地域の市場 {w}（凍結しなかった変種）'] = {'holdout': st}
        print('地域', w, st['excess'], st['t'])
    fm, spy, vwo = (h.px_to_ret(h.yahoo(s, 2010)) for s in ('FM', 'SPY', 'VWO'))
    for nmb, b in (('SPY', spy), ('VWO', vwo)):
        st = h.stats(fm, b, rf)
        out[f'FM（実在のETF）vs {nmb}'] = {'holdout': st, 'note': None if st else 'Yahoo に FM の系列が無い（上場廃止の可能性。Invesco の FRN も同じく無い）'}
        print('FM vs', nmb, st and (st['from'], st['to'], st['cagr'], st['bench_cagr'], st['excess'], st['t']))
    json.dump({'about': '第10回の検証（判定は変えない）: frontier の上乗せの出どころ', 'generated': datetime.date.today().isoformat(),
               'contribution_by_country_since2001_arith_pct': contrib, 'cases': out},
              open(os.path.join(h.BASE, 'out', 'edge', 'verify_frontier.json'), 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
