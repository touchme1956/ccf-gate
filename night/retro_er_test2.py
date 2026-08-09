#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_er_test2.py — **2018年の入口で E[r] を計算していたら、勝者を上位に並べられたか**（2026-08-09新設）

発端（ユーザーの問い「過去リターンを出した銘柄たちはどうだったの？」）——
`night/irr85_er.py` が今日の14社を期待値で並べた直後に、**その並べ方自体を歴史で答え合わせする**。

作り方（同じ物差しを2018年へ当てる）:
  E[r] = shy + g + 倍率の重力(20年)
   ・per  = out/retro_per_2018_all.json（分割補正済み・当時の板の値）
   ・shy  = payout5 ÷ per ×100（payout5 = Σ(配当+自社株買い)÷Σ純利益 の5年）
     ⚠株式発行を引いていない**総額ベース**なので、実際の純還元よりやや過大に出る
   ・g    = min(max(cagr5,0),20)。**2018年の在庫に roicg が無いので全社「実証CAGRを信じる枝」**
     ＝門X本体の再投資式への分岐は再現できない（**甘い側の仮定**であることを明記して読む）
   ・fairPER = clamp(8+g,16,30) ／ mult = ((min(per,fair)/per)^(1/20)−1)×100

**結果（2026-08-09の実測）**:
  ・母集団598社: E[r]五分位の実現中央値は **6.8 / 7.6 / 6.9 / 7.3 / 7.7%** ＝**単調でない**。
    P(15%+) は 0.24 / 0.19 / 0.18 / 0.23 / 0.19（全体0.21）で**リフト無し**。**相関 r = −0.004**
  ・irr=85 の19社: E[r]上位半分の 15%+ は **0.67**、下位半分は **0.70** ＝**下位のほうが高い**
  ・個別では **WST が E[r] 最下位(−5.5%・PER127・倍率7.96x)で実現+15.7%の継続組**、
    **CW が下から2番目(+1.9%)で実現+24.5%**。逆に **IPGP(+20.2%)→−6.6%**、**OLED(+18.2%)→−0.6%**
  ⇒ **E[r] は「期待値」の記述としては正しいが、順位付けの道具としては歴史で働かなかった。**
    v9.9.98 が E[r] を合否から外した根拠（価格の線は質の中で選別力を持たない）と同じ結論に、
    **E[r]という合成量そのもの**で到達した5例目

使い方: python3 night/retro_er_test2.py [--json]
"""
import json, statistics as st, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]


def build():
    F2 = {r['ticker']: r for r in json.load(open('out/retro_features2_2018.json', encoding='utf-8'))['rows']}
    PE = {r['ticker']: r for r in json.load(open('out/retro_per_2018_all.json', encoding='utf-8'))['rows']}
    R = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    firms = set(json.load(open('out/retro_irr85_deep.json', encoding='utf-8'))['firms85'])
    Q = []
    for t, p in PE.items():
        f, r = F2.get(t), R.get(t)
        if not f or not r or not p.get('per') or p['per'] <= 0:
            continue
        po, cg = f.get('payout5'), f.get('cagr5')
        if po is None or cg is None:
            continue
        per = p['per']; shy = po / per * 100; g = min(max(cg * 100, 0), 20)
        fair = max(16, min(30, 8 + g)); mult = ((min(per, fair) / per) ** (1 / 20) - 1) * 100
        Q.append(dict(t=t, per=per, shy=shy, g=g, mult=mult, er=shy + g + mult,
                      x=per / fair, ret=r['tr_cagr'], irr85=t in firms))
    return Q, firms


def main():
    Q, firms = build()
    Q.sort(key=lambda z: -z['er'])
    n = len(Q)
    print(f'■ 2018年の入口で E[r] を計算していたら、勝者を上位に並べられたか（{n}社）')
    print('  ※2018年の在庫に roicg が無いので**全社「実証CAGRを信じる枝」**＝甘い側の仮定\n')
    print(f"  {'帯':<16}{'n':>5}{'E[r]中央値':>11}{'実現中央値':>11}{'15%+':>8}{'恒久毀損':>9}")
    k = n // 5
    for i, lab in enumerate(['Q1 E[r]最高', 'Q2', 'Q3', 'Q4', 'Q5 E[r]最低']):
        g = Q[i * k:(i + 1) * k] if i < 4 else Q[4 * k:]
        v = [x['ret'] for x in g]
        print(f"  {lab:<14}{len(v):>5}{st.median([x['er'] for x in g]):>10.1f}%{st.median(v)*100:>10.1f}%"
              f"{sum(1 for x in v if x >= .15)/len(v):>8.2f}{sum(1 for x in v if x <= -.15)/len(v):>9.2f}")
    v = [x['ret'] for x in Q]
    print(f"  {'全体':<14}{n:>5}{st.median([x['er'] for x in Q]):>10.1f}%{st.median(v)*100:>10.1f}%"
          f"{sum(1 for x in v if x >= .15)/len(v):>8.2f}{sum(1 for x in v if x <= -.15)/len(v):>9.2f}")
    xs = [x['er'] for x in Q]; ys = [x['ret'] for x in Q]
    mx, my = st.mean(xs), st.mean(ys)
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / n / (st.pstdev(xs) * st.pstdev(ys))
    print(f"\n  相関係数 r = {r:+.3f}")

    G = [x for x in Q if x['irr85']]
    print(f"\n■ irr=85 の {len(G)}社を E[r] の高い順に（**当時の入口の値**）")
    print(f"  {'':<6}{'2018 PER':>9}{'倍率':>7}{'shy':>7}{'g':>7}{'重力':>7}{'E[r]':>8}{'実現8.1年':>11}")
    for x in G:
        print(f"  {x['t']:<6}{x['per']:>9.1f}{x['x']:>6.2f}x{x['shy']:>6.2f}%{x['g']:>6.1f}%"
              f"{x['mult']:>6.1f}%{x['er']:>7.1f}%{x['ret']*100:>10.1f}%"
              + ('  ←継続' if x['ret'] >= .15 else ''))
    m = len(G) // 2
    print(f"\n  E[r]上位半分 {m}社: 実現中央値 {st.median([x['ret'] for x in G[:m]])*100:.1f}% / "
          f"15%+ {sum(1 for x in G[:m] if x['ret']>=.15)}/{m}")
    print(f"  E[r]下位半分 {len(G)-m}社: 実現中央値 {st.median([x['ret'] for x in G[m:]])*100:.1f}% / "
          f"15%+ {sum(1 for x in G[m:] if x['ret']>=.15)}/{len(G)-m}  ← **下位のほうが高い**")
    print('\n■ 読み方')
    print('  ・E[r] は「今の株価でこの前提なら年何%」という**記述**としては正しい。')
    print('    だが**順位付けの道具としては歴史で働かなかった**——母集団で相関ほぼ0・irr=85群では逆。')
    print('  ・v9.9.98 が E[r] を合否から外した根拠（価格の線は質の中で選別力を持たない）と')
    print('    同じ結論に、**E[r]という合成量そのもの**で到達した。価格の線の無力の5例目。')
    print('  ・⚠限界: roicg の分岐が再現できず全社を甘い枝で計算／shy は総額ベースで過大／')
    print('    窓は 2018→2026 の一つ／PER が取れた598社に限る（生存バイアス）')
    if AS_JSON:
        json.dump({'generated': '2026-08-09', 'n': n, 'corr': r, 'rows': Q},
                  open('out/retro_er_test2.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n→ out/retro_er_test2.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
