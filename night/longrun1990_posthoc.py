#!/usr/bin/env python3
"""night/longrun1990_posthoc.py — 1990年〜今の長い検証（longrun1990）の【事後の確かめ】（事前登録の外・判定に使わない）

結果（out/longrun1990.json）を見たあとで足した。L-a1（ROIC に近い量の高い側）が市場を上回ったので、
  1) 収益性の別の物差し（JKP ope_be・gp_at・cop_at・ni_be・op_at・French の OP）でも同じか
  2) 前に記録した『質は2007年以降 S&P500 型の市場に勝っていない』（longonly_test の事後）と食い違うのは、
     重み付け（上限つき vw_cap と上限なし vw）の違いか
を同じ道具（night/longrun1990.py の stats・tails・french_universe・jkp_terciles・jkp_side）で測る。
出力: out/longrun1990_posthoc.json
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as C  # noqa: E402
import longrun1990 as L  # noqa: E402

OUT = os.path.join(L.BASE, 'out', 'longrun1990_posthoc.json')


def row(rS, rB, rf=None):
    out = {k: L.stats(rS, rB, a, z) for k, (a, z) in L.PERIODS.items()}
    out['tail'] = L.tails(rS, rB, rf)
    return out


def main():
    rf = C.ff_factors()['rf']
    mk = {w: {C._ym(x['date']): float(x['ret']) for x in C.jkp_rows('usa', 'mkt', 'factor', w) if x['ret'] not in ('', 'NA', 'na')}
          for w in ('vw', 'vw_cap')}
    res = {'note': '事前登録の外。結果を見たあとで足した確かめで、判定（out/longrun1990.json）は変えない。',
           'profitability_other_measures': {}, 'weighting_reconciliation': {}}
    # 1) 収益性の別の物差し
    for key in ('ebit_bev', 'ope_be', 'gp_at', 'cop_at', 'ni_be', 'op_at'):
        r, _ = L.jkp_terciles(key, 'vw')
        hi, lo, c, dr = L.jkp_side(key, r)
        res['profitability_other_measures'][f'JKP {key} 高い側（vw）'] = row(r[hi], mk['vw'], rf)
        res['profitability_other_measures'][f'JKP {key} 低い側（vw）'] = row(r[lo], mk['vw'], rf)
    fp = L.french_parts('Portfolios_Formed_on_OP')
    for w in ('vw', 'ew'):
        uni, _ = L.french_universe(fp, ['Lo 30', 'Med 40', 'Hi 30'], w)
        res['profitability_other_measures'][f'French OP Hi 30（{w}）'] = row(fp[w]['Hi 30'], uni)
        res['profitability_other_measures'][f'French OP Lo 30（{w}）'] = row(fp[w]['Lo 30'], uni)
    # 2) 上限つき・上限なしの重み付け
    for key in ('ebit_bev', 'qmj'):
        for w in ('vw', 'vw_cap'):
            r, _ = L.jkp_terciles(key, w)
            hi, lo, c, dr = L.jkp_side(key, r)
            for bw in ('vw', 'vw_cap'):
                res['weighting_reconciliation'][f'JKP {key} 高い側 {w} 対 市場 {bw}'] = {
                    k: L.stats(r[hi], mk[bw], a, z) for k, (a, z) in L.PERIODS.items()}
    res['weighting_reconciliation']['市場 vw_cap 対 市場 vw'] = {k: L.stats(mk['vw_cap'], mk['vw'], a, z) for k, (a, z) in L.PERIODS.items()}
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/longrun1990_posthoc.py', 'prereg_commit': '4dc44296', **res}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for sec in ('profitability_other_measures', 'weighting_reconciliation'):
        print('==', sec)
        for k, v in out[sec].items():
            print(f"{k:40} " + ' | '.join(f"{p} {v[p].get('mean_ann_pct'):+6.2f}(t{v[p].get('t'):+5.2f})" for p in ('P0', 'H1', 'H2', 'E13'))
                  + (f" | win13 {v['tail']['win13_share']}" if 'tail' in v else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
