#!/usr/bin/env python3
"""night/gaps_cost.py — 歴史検証の穴⑤: 費用と税を引いても配分の順位は変わらないか（読むだけ・判定に不使用）

事前登録: out/gaps7_prereg.json の Q5_cost_tax（9c28f6c・測る前に固定）
  ETF の adjclose は経費率を引いた後なので、器の差だけを足し引きする:
    iFreeNEXT NASDAQ100 0.495% ＝ QQQ(0.20%) − 0.295%/年 ／ QQQM 0.15% ＝ QQQ + 0.05% ／ SMH はそのまま
    S&P500（eMAXIS Slim 米国株式 0.0814%）＝ SPY(0.0945%) + 0.013%
  配当利回り QQQ 0.7%・SMH 1.0%・SPY 1.8%。米国の源泉10%はどの口座でも取り戻さない。
  課税口座は配当に毎年20.315%（源泉後の額に）、売却益は最後に全部売ったとして20.315%。
  NISA は今の制度（つみたて120万・成長240万・生涯1800万〔成長は1200万まで〕）を過去の窓にも当てた仮定。
  ETF 側だけを計算する（毎月の入金の8割＝10万→8万・17万→13.6万・30万→24万）。円建て（ドル円は各月末）。
出力: out/gaps_cost.json
"""
import json, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from gaps_common import fred, add_months
from gaps_yen import monthly_returns

OUT = os.path.join(BASE, 'out', 'gaps_cost.json')
TAX = 0.20315
WHT = 0.10
YLD = {'NDX': 0.007, 'SMH': 0.010, 'SPX': 0.018}
# 器: (元の系列, 年あたりの経費の差, 配当の系列, NISA の枠)
VEH = {'iFreeNEXT': ('QQQ', -0.00295, 'NDX', 'tsumitate'),
       'QQQM': ('QQQ', +0.0005, 'NDX', 'growth'),
       'SMH': ('SMH', 0.0, 'SMH', 'growth'),
       'Slim_SP500': ('SPY', +0.00013, 'SPX', 'tsumitate')}
MIXES = {
    '今の配分（iFreeNEXT75/SMH25・NISA→課税）': {'iFreeNEXT': .75, 'SMH': .25},
    'iFreeNEXTのみ': {'iFreeNEXT': 1.0},
    'S&P500のみ（eMAXIS Slim）': {'Slim_SP500': 1.0},
    '★事後: 同じ75/25で NASDAQ100 を つみたて枠=iFreeNEXT・成長枠と課税=QQQM': {'NDX_best': .75, 'SMH': .25},
    '★事後: QQQM75/SMH25（成長枠→課税・つみたて枠は使わない）': {'QQQM': .75, 'SMH': .25},
}


# 事後の追加（事前登録の外）: NASDAQ100 を口座ごとに安い器で持つ——つみたて枠は iFreeNEXT（QQQM は入らない）、
#   成長枠と課税口座は QQQM。枠の順番は つみたて→成長→課税
ROUTE = {'NDX_best': [('tsumitate', 'iFreeNEXT'), ('growth', 'QQQM'), ('tax', 'QQQM')]}
SRC_OF = {'NDX_best': 'QQQ'}


def simulate(ret, fx, start, n, monthly_yen, mix, use_nisa=True, force_taxable=()):
    """→ (費用も税も引かない倍率, 費用と税を引いた倍率, NISAにある割合)。金額は円"""
    TS_Y, GR_Y, LIFE, GR_LIFE = 1_200_000, 2_400_000, 18_000_000, 12_000_000
    acct = {}          # (器, 口座) -> [評価額, 簿価]
    gross = {k: 0.0 for k in mix}
    life = gr_life = 0.0
    used = {}
    for i in range(n):
        m = add_months(start, i)
        y = m // 100
        if y not in used:
            used[y] = {'tsumitate': 0.0, 'growth': 0.0}
        p = add_months(m, -1)
        fxr = fx[m] / fx[p]
        for v, w in mix.items():
            c = monthly_yen * w
            gross[v] += c
            if v in ROUTE:
                route = ROUTE[v]
            else:
                slot = VEH[v][3]
                route = ([('tsumitate', v), ('growth', v)] if slot == 'tsumitate' else [('growth', v)]) + [('tax', v)]
            rem = c
            for s, veh in route:
                if s == 'tax':
                    break
                if not use_nisa or v in force_taxable:
                    break
                cap = (TS_Y if s == 'tsumitate' else GR_Y) - used[y][s]
                room = min(cap, LIFE - life, (GR_LIFE - gr_life) if s == 'growth' else 1e18)
                put = max(0.0, min(rem, room))
                if put > 0:
                    a = acct.setdefault((veh, 'nisa'), [0.0, 0.0])
                    a[0] += put; a[1] += put
                    used[y][s] += put; life += put
                    if s == 'growth':
                        gr_life += put
                    rem -= put
            if rem > 0:
                veh = route[-1][1]
                a = acct.setdefault((veh, 'tax'), [0.0, 0.0])
                a[0] += rem; a[1] += rem
        # 1か月のリターン
        for v in mix:
            src = SRC_OF.get(v) or VEH[v][0]
            gross[v] *= (1 + ret[src][m]) * fxr        # 費用の差も税も引かない（元の系列そのまま・円）
        for (veh, kind), a in acct.items():
            src, fee, dv, slot = VEH[veh]
            r = (1 + ret[src][m]) * fxr - 1
            y_ = YLD[dv] / 12
            if kind == 'nisa':
                a[0] *= 1 + r + fee / 12 - y_ * WHT
            else:
                a[0] *= 1 + r + fee / 12 - y_ * (WHT + (1 - WHT) * TAX)
                a[1] += a[0] * y_ * (1 - WHT) * (1 - TAX)      # 税引後の配当の再投資は簿価に入る
    invested = monthly_yen * n
    g = sum(gross.values())
    net_total = 0.0
    for (v, kind), (val, basis) in acct.items():
        net_total += val if kind == 'nisa' else val - TAX * max(0.0, val - basis)
    nisa_share = sum(val for (v, kind), (val, b) in acct.items() if kind == 'nisa') / max(1e-9, sum(val for (val, b) in acct.values()))
    return g / invested, net_total / invested, nisa_share


def main():
    fx = fred('DEXJPUS')
    ret = {k: monthly_returns(k) for k in ('QQQ', 'SMH', 'SPY')}
    ms = sorted(set.intersection(*[set(v) for v in ret.values()]))
    last = max(m for m in ms if m < int(time.strftime('%Y%m')))
    ms = [m for m in ms if m <= last and m in fx and add_months(m, -1) in fx]
    out = {}
    n = 240
    starts = [s for s in ms if add_months(s, n - 1) <= last]
    for amt in (100_000, 170_000, 300_000):
        etf = amt * 0.8
        res = {}
        for nm, mix in MIXES.items():
            gs, ns, sh = [], [], []
            for s in starts:
                g, nt, share = simulate(ret, fx, s, n, etf, mix)
                gs.append(g); ns.append(nt); sh.append(share)
            gs_, ns_ = sorted(gs), sorted(ns)
            res[nm] = {'引く前 中央/最悪': [round(gs_[len(gs_) // 2], 3), round(gs_[0], 3)],
                       '費用と税を引いた後 中央/最悪': [round(ns_[len(ns_) // 2], 3), round(ns_[0], 3)],
                       '費用と税が取った割合（中央の窓）': round(1 - S.median(n_ / g_ for n_, g_ in zip(ns, gs)), 3),
                       'NISAにある割合（最終額・中央）': round(S.median(sh), 3)}
        # (c) NASDAQ100 の器: iFreeNEXT を NISA vs QQQM を全部課税口座
        alt = []
        for s in starts:
            _, a1, _ = simulate(ret, fx, s, n, etf * .75, {'iFreeNEXT': 1.0})
            _, a2, _ = simulate(ret, fx, s, n, etf * .75, {'QQQM': 1.0}, force_taxable=('QQQM',))
            _, a3, _ = simulate(ret, fx, s, n, etf * .75, {'QQQM': 1.0})
            alt.append((a1, a2, a3))
        res['NASDAQ100の器（ETF側の75%ぶん）'] = {
            'iFreeNEXT(NISA→課税) ÷ QQQM(全部課税)': round(S.median(a / b for a, b, c in alt), 3),
            'iFreeNEXT(NISA→課税) ÷ QQQM(成長枠→課税)': round(S.median(a / c for a, b, c in alt), 3)}
        mixk, spk = '今の配分（iFreeNEXT75/SMH25・NISA→課税）', 'S&P500のみ（eMAXIS Slim）'
        a, b = res[mixk]['費用と税を引いた後 中央/最悪'], res[spk]['費用と税を引いた後 中央/最悪']
        res['判定'] = '支持（順位は変わらない）' if a[0] >= b[0] and a[1] >= b[1] else '順位が変わる'
        out[f'月{amt // 10000}万（ETF側{etf / 10000:g}万）'] = res
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_cost.py', 'prereg': 'out/gaps7_prereg.json Q5_cost_tax（9c28f6c）',
           '窓': f'20年・{len(starts)}窓（{starts[0]}〜{starts[-1]}開始）・円建て', '結果': out,
           '注': 'NISA は今の制度を過去の窓に当てた仮定。売却益の税は20年の最後に全部売ったとして計算（売らなければ先送りされる）。配当利回りは固定の置き値'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for k, v in out.items():
        print('==', k, v['判定'])
        for nm, x in v.items():
            if nm != '判定':
                print('  ', nm, x)


if __name__ == '__main__':
    main()
