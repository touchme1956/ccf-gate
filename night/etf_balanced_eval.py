#!/usr/bin/env python3
"""night/etf_balanced_eval.py — 「15%を目指しつつバランスのよいポートフォリオなら？」の私の案を、同じ物差しで測る（2026-10-10）

読むだけ。門・採点・配分には触れない。候補7つと選び方は計算の前に会話で固定した（repo への事前登録のコミットはしていない＝判断の問いへの答えで、仮説の検定ではない）。
物差しは night/etf_forward_combo.py（4つの世界の年率・ぶれ・最大下落・分散の上乗せ）と night/etf_p15.py（20年の積立の内部収益率の確率・過去の転がる窓）をそのまま使う。
候補は合計の比（個別株15%を除いた ETF 側を正規化して測る）。
  選び方: 私の案は、15%以上の確率が今−3pt 以上 ∧ 最悪の世界が今より上 ∧ 5%未満の確率が今より下 なら勧める。満たさなければ予備、それも満たさなければ最小の変更。
出力: out/etf_balanced_eval.json
"""
import os
import sys, json, math
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import numpy as np
import etf_p15 as P
import mw_common as M
CB = P.CB
ctx = CB.build(max_k=1)
C = CB.CANDS
G1, adj, T1 = ctx['G1'], ctx['adj'], ctx['T1']
base_of, worlds = ctx['base_of'], ctx['worlds']
k1 = CB.R.months(*CB.R.A1)
def etf_side(total):
    """合計の比（個別株15%を除いた ETF 側）→ ETF 側の中の比"""
    s = sum(total.values()); return {k: v / s for k, v in total.items()}
CANDS = {
  '今': {'QQQM': 50, 'XLK': 15, 'SMH': 20},
  '最小の変更（その他をITA）': {'QQQM': 50, 'ITA': 15, 'SMH': 20},
  '私の案（バランス）': {'QQQM': 30, 'SMH': 20, 'ITA': 10, 'XLE': 10, 'VBR': 10, 'GLDM': 5},
  '予備（やや攻め）': {'QQQM': 30, 'SMH': 25, 'ITA': 15, 'XLE': 10, 'GLDM': 5},
  '参考 効率の点 SMH50/ITA40/金10': {'SMH': 50, 'ITA': 40, 'GLDM': 10},
  '参考 確率最大 SMH60/ITA40': {'SMH': 60, 'ITA': 40},
  '参考 S&P500': {'VOO': 100},
}
W = np.vstack([[etf_side(t).get(c, 0.0) for c in C] for t in CANDS.values()])
bs = base_of(W)
wv = worlds(W, bs, 'main')
sig = np.sqrt(bs['q1'])
tabs = P.dca_tables(20, [0.0, 0.05, 0.10, 0.15], log=False)
names = ['A1', 'A2', 'B', 'C']
per15 = {n: P.interp(tabs[0.15], np.log1p(wv[n]), sig) for n in names}
p15 = np.mean([per15[n] for n in names], axis=0)
p10 = np.mean([P.interp(tabs[0.10], np.log1p(wv[n]), sig) for n in names], axis=0)
p5 = 1 - np.mean([P.interp(tabs[0.05], np.log1p(wv[n]), sig) for n in names], axis=0)
p0 = 1 - np.mean([P.interp(tabs[0.0], np.log1p(wv[n]), sig) for n in names], axis=0)
hs = P.hist_success(W, G1, adj, T1)
# 暴落の局面・円の最大下落と水没
fx = M.yahoo('JPY=X')
eps = {'ITバブル崩壊': (200009, 200212), 'リーマン': (200707, 200906), 'コロナ': (202001, 202006), '利上げ2022': (202201, 202212)}
def dd(rs):
    v = pk = 1.0; m = 0.0; under = longest = 0
    for r in rs:
        v *= 1 + r
        if v >= pk: pk = v; under = 0
        else: under += 1; longest = max(longest, under)
        m = min(m, v / pk - 1)
    return m, longest / 12
rows = []
for i, (nm, t) in enumerate(CANDS.items()):
    w = W[i]
    r_usd = {k: float(w @ G1[:, j]) for j, k in enumerate(k1)}
    epi = {e: round(100 * dd([r_usd[k] for k in CB.R.months(a, b)])[0], 1) for e, (a, b) in eps.items()}
    yen = [(1 + r_usd[k]) * (1 + fx[k]) - 1 for k in k1]
    ydd, yund = dd(yen)
    tech = sum(t.get(k, 0) for k in ('QQQM', 'XLK', 'SMH')) / sum(t.values())
    rows.append(dict(name=nm, total_pct=t, etf_side={k: round(100 * v, 1) for k, v in etf_side(t).items()},
        tech_share_etf=round(100 * tech, 1),
        A1=round(100 * wv['A1'][i], 2), A2=round(100 * wv['A2'][i], 2), B=round(100 * wv['B'][i], 2), C=round(100 * wv['C'][i], 2),
        mean=round(100 * wv['mean'][i], 2), worst=round(100 * wv['worst'][i], 2), vol=round(100 * bs['vol'][i], 1), mdd=round(100 * bs['mdd'][i], 1),
        bonus=round(100 * wv['bonus'][i], 2), P15=round(100 * p15[i], 1), P15_per={n: round(float(100 * per15[n][i]), 1) for n in names},
        P10=round(100 * p10[i], 1), P5=round(100 * p5[i], 1), P0=round(100 * p0[i], 1),
        hist20=round(100 * hs[240][i], 1), hist15=round(100 * hs[180][i], 1), episodes=epi, yen_mdd=round(100 * ydd, 1), yen_underwater_y=round(yund, 1)))
for r in rows:
    print(f"{r['name'][:24]:<24} ETF側{r['etf_side']} テック{r['tech_share_etf']}% | 平均{r['mean']:5.2f} 最悪{r['worst']:5.2f} [A1 {r['A1']} A2 {r['A2']} B {r['B']} C {r['C']}] ぶれ{r['vol']} 下落{r['mdd']} 上乗せ{r['bonus']}")
    print(f"   15%以上{r['P15']}%（{r['P15_per']}）10%以上{r['P10']}% 5%未満{r['P5']}% 元本割れ{r['P0']}% | 過去20年{r['hist20']}% 15年{r['hist15']}% | 局面{r['episodes']} | 円 下落{r['yen_mdd']}% 水没{r['yen_underwater_y']}年")
now, mine, alt = rows[0], rows[2], rows[3]
def ok(c): return bool(c['P15'] >= now['P15'] - 3 and c['worst'] > now['worst'] and c['P5'] < now['P5'])
print('私の案が条件を満たす:', ok(mine), ' 予備が条件を満たす:', ok(alt))
json.dump(dict(generated=__import__('datetime').date.today().isoformat(), tool='night/etf_balanced_eval.py', rows=rows, rule='私の案: P15 ≥ 今−3pt ∧ 最悪 > 今 ∧ 5%未満 < 今 なら勧める。満たさなければ予備、それも満たさなければ最小の変更', mine_ok=bool(ok(mine)), alt_ok=bool(ok(alt))),
          open(os.path.join(BASE, 'out', 'etf_balanced_eval.json'), 'w'), ensure_ascii=False, indent=1)
