#!/usr/bin/env python3
"""night/edge/verify_r10_vehicles.py — 第10回の検証（判定は変えない）: 実在の器を設定来で比べる（事前登録 out/edge_prereg_r10.json の verification_plan）

  カバードコール・プット売り（XYLD・QYLD・JEPI・RYLD・PUTW）、フロンティア（FM）、株以外（GLD・IAU・GSG・DBC・VNQ・TLT）を
  Yahoo の月次 adjclose（分配込み・経費込み）で、同じ月の SPY（と比べる意味のある相手 QQQ・IWM・VWO）と比べる。
  出力: out/edge/verify_r10_vehicles.json
"""
import os, sys, json, datetime
os.environ['EDGE_PHASE'] = 'holdout'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h  # noqa: E402

PAIRS = {
    'XYLD': ['SPY'], 'QYLD': ['QQQ', 'SPY'], 'JEPI': ['SPY'], 'RYLD': ['IWM', 'SPY'], 'PUTW': ['SPY'],
    'FM': ['SPY', 'VWO'],
    'GLD': ['SPY'], 'IAU': ['SPY'], 'GSG': ['SPY'], 'DBC': ['SPY'], 'VNQ': ['SPY'], 'TLT': ['SPY'],
}


def main():
    lineup = json.load(open(os.path.join(h.BASE, 'out', 'broker_lineup.json')))['etfs']
    _, rf = h.us_market()
    rets = {s: h.px_to_ret(h.yahoo(s, 1990)) for s in set(PAIRS) | {b for v in PAIRS.values() for b in v}}
    out = {}
    for s, bs in PAIRS.items():
        row = {'rakuten': s in lineup, 'from': min(rets[s]) if rets[s] else None, 'vs': {}}
        for b in bs:
            st = h.stats(rets[s], rets[b], rf)
            row['vs'][b] = st and {k: st[k] for k in ('from', 'to', 'years', 'cagr', 'bench_cagr', 'excess', 't', 'vol', 'bench_vol', 'maxdd', 'bench_maxdd', 'roll10_win')}
        out[s] = row
        for b, st in row['vs'].items():
            if st:
                print(f"{s:5} 楽天{'○' if row['rakuten'] else '×'} vs {b:4} {st['from']}〜{st['to']} {st['cagr']}% vs {st['bench_cagr']}% 差 {st['excess']} t{st['t']} ぶれ {st['vol']}/{st['bench_vol']} 最大下落 {st['maxdd']}/{st['bench_maxdd']}")
    json.dump({'about': '第10回の検証（判定は変えない）: 実在の器を設定来で。Yahoo の adjclose（分配込み・経費込み）・税の前',
               'generated': datetime.date.today().isoformat(), 'rows': out}, open(os.path.join(h.BASE, 'out', 'edge', 'verify_r10_vehicles.json'), 'w'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
