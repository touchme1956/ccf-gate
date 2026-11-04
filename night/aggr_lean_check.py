#!/usr/bin/env python3
"""night/aggr_lean_check.py — 今の配分を「少し攻め」にした形を同じ物差しで並べる（2026-11-04・参考・配分は変えない）

ユーザー「私のポートフォリオを少し攻めに変えると?」。門・採点・配分（portfolio.json）・注文書には触れない。
★形と選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。

今（portfolio.json と照合）: NASDAQ100 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15（個別株0）
「少し攻め」＝守りの本（ITA・XLV・VBR）から伸びの本（NASDAQ100・SMH）へ、資産の5〜10%を移す（ret_lean_check の「気味」と同じ幅）:
  A VBR 5→SMH         40/25/15/10/10      B VBR 5→NASDAQ100   45/20/15/10/10
  C VBR 10→SMH        40/30/15/10/5       D VBR 10→NDX5・SMH5 45/25/15/10/5
  E ITA 5→SMH         40/25/10/10/15      F XLV 5→SMH         40/25/15/5/15
  G ITA5・VBR5→SMH    40/30/10/10/10      H 11-02 の前の形     50/20/20/10/0（参考）
測るもの（ndx40_form_check と同じ関数）: 元の物差し（P15π・平均・5%未満・最悪の世界・最大下落・ぶれ）／業種の基礎率の物差し
  （平均・5%未満・感度6本の今との差）／100年の代用（30年の積立の比 中央・最悪）／実績（2000-09〜の転がる20年の積立: 年15%以上の割合・年率の中央）／
  円の最大下落／中身の集中（lookthrough の NVDA・半導体の連鎖）
私の答えの選び方（結果を見る前に固定）:
  攻めの目的＝期待値を上げること。A〜G のうち (1) 元の平均が今より上 かつ (2) 基礎率の平均が感度6本すべてで今以上 かつ
  (3) 最大下落の深まりが3pt以内 の形の中で、元の平均の上がり幅が最大の形（同点〔0.01pt〕なら最大下落が浅いほう）。
  どれも通らなければ「今のまま」。
⚠ 限界: 未来の世界は予想・分散の上乗せは仮定・実績は一つの時代・100年の写しの NASDAQ100 は業種を固定した代わり・5%の差は雑音に近い
使い方: python3 night/aggr_lean_check.py → out/aggr_lean_check.json（約30秒）
"""
import contextlib, io, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'aggr_lean_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_check import name5, r  # noqa: E402
from five_mix_ndx_check import realized, EPS  # noqa: E402

NOW = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
def F(n, s, i, x, v):
    return {k: w for k, w in zip(('QQQM', 'SMH', 'ITA', 'XLV', 'VBR'), (n, s, i, x, v)) if w}
FORMS = {'今': dict(NOW),
         'A VBR5→SMH': F(40, 25, 15, 10, 10), 'B VBR5→NASDAQ100': F(45, 20, 15, 10, 10),
         'C VBR10→SMH': F(40, 30, 15, 10, 5), 'D VBR10→NDX5・SMH5': F(45, 25, 15, 10, 5),
         'E ITA5→SMH': F(40, 25, 10, 10, 15), 'F XLV5→SMH': F(40, 25, 15, 5, 15),
         'G ITA5・VBR5→SMH': F(40, 30, 10, 10, 10), 'H 11-02の前（参考）': F(50, 20, 20, 10, 0)}
CANDS = [k for k in FORMS if k[0] in 'ABCDEFG']


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def main():
    t0 = time.time()
    t = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    w = {('QQQM' if k == 'IFREE-NDX' else k): v for k, v in t['ami_weights'].items() if v}
    if w != NOW or float(t.get('shiro_castle_pct') or 0) != 0:
        raise SystemExit(f'今の形が正本と違う: {w}')
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import etf_forward_combo as CB
    import ndx_swap_check as N
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = BR.POOL
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    vec, _ = BR.industry_vectors(U, rows)
    st = BR.industry_state()
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    keys = list(FORMS)
    W = np.array([[FORMS[k].get(c, 0) for c in P] for k in keys], dtype=np.float64)
    e, b, c, rz = fast.eval(W), fbr.eval(W, a0), cent.eval(W), realized(W, fast)
    # 自己検問: 今の元の物差しが measure と一致
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure({'今': dict(NOW)}, rows, chains)
    m0 = tab[UC.W_CRASH]['今']
    sc = dict(P15=(r(e['P15'][0]), m0['P15π']), 平均=(r(e['mean_pi'][0]), m0['π加重の平均の年率']), 最大下落=(r(e['mdd'][0], 1), m0['最大下落']))
    if not all(abs(float(x) - float(y)) < 0.051 for x, y in sc.values()):
        raise SystemExit(f'自己検問が通らない {sc}')
    vres = {}
    for v in BR.VARS:
        f = {'主': lambda: fbr.eval(W, a0), '10年の値': lambda: fbr.eval(W, adj['10年の値']),
             '1位の業種を強く': lambda: fbr.eval(W, adj['1位の業種を強く（10年の値・Chips −4.0）']),
             '主の半分': lambda: fbr.eval(W, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(W, a0, nobonus=True),
             '共分散をA2の窓から': lambda: fbr.eval(W, a0, cov2=True)}[v]
        vres[v] = f()
    ch_jpy, _ = U.jpy_chains(chains)
    Gj = np.array([[ch_jpy[x][m] for m in U.R.months(*BC.WINDOWS[UC.W_CRASH])] for x in P])
    _, _, mdd_j = CB.path_stats((W / W.sum(axis=1, keepdims=True)) @ Gj, Gj.shape[1])
    N.NET_ARG['VBR'] = 'VBR'
    N.CASTLE_ARG = 'CW=0.0001'
    summ = {}
    for j, k in enumerate(keys):
        try:
            lk = N.lookthrough(FORMS[k])
        except Exception as ex:   # 参考だけ
            lk = dict(読めず=str(ex)[:200])
        summ[k] = dict(
            形=FORMS[k], 名前=name5(FORMS[k]),
            元=dict(P15π=r(e['P15'][j]), 平均=r(e['mean_pi'][j], 2), 五パーセント未満=r(e['P5'][j]), 最大下落=r(e['mdd'][j], 1), ぶれ=r(e['vol'][j], 1)),
            基礎率=dict(P15π=r(b['P15'][j]), 平均=r(b['mean_pi'][j], 2), 五パーセント未満=r(b['P5'][j]),
                     感度ごとの今との差={v: r(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0], 3) for v in BR.VARS}),
            百年=dict(三十年の中央=round(float(c['c30med'][j]), 3), 三十年の最悪=round(float(c['c30min'][j]), 3)),
            実績=dict(年15パーセント以上の割合=r(rz['share'][j], 1), 年率の中央=r(rz['med'][j], 2)),
            円の最大下落=r(mdd_j[j], 1),
            集中=dict(NVDA=lk.get('NVDA（資産全体）'), 半導体の連鎖=lk.get('半導体の連鎖（下限〜上限）')))
    ok = []
    for k in CANDS:
        j = keys.index(k)
        c1 = e['mean_pi'][j] > e['mean_pi'][0] + EPS
        c2 = all(vres[v]['mean_pi'][j] >= vres[v]['mean_pi'][0] - EPS for v in BR.VARS)
        c3 = e['mdd'][j] >= e['mdd'][0] - 3.0
        summ[k]['選び方'] = dict(元の平均が上=bool(c1), 基礎率の平均が感度6本すべてで今以上=bool(c2), 最大下落の深まり3pt以内=bool(c3))
        if c1 and c2 and c3:
            ok.append((-round(float(e['mean_pi'][j] - e['mean_pi'][0]), 2), -float(e['mdd'][j]), k))
    ans = sorted(ok)[0][2] if ok else '今のまま'
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/aggr_lean_check.py', kind='参考（配分は変えない・形と選び方は道具の頭に固定）',
               question='私のポートフォリオを少し攻めに変えると?', selfcheck=sc, 答え=ans, 形ごとの物差し=summ, secs=round(time.time() - t0))
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    for k in keys:
        s = summ[k]
        log(f"{k:<18} 元P15 {s['元']['P15π']:5} 平均 {s['元']['平均']:6} P5 {s['元']['五パーセント未満']:5} 下落 {s['元']['最大下落']:6} 円 {s['円の最大下落']:6} "
            f"基礎 {s['基礎率']['平均']:6} 百年 {s['百年']['三十年の中央']} {s['百年']['三十年の最悪']} 実績 {s['実績']['年15パーセント以上の割合']} {s['実績']['年率の中央']} "
            f"NVDA {s['集中']['NVDA']} 連鎖 {s['集中']['半導体の連鎖']} 感度 {list(s['基礎率']['感度ごとの今との差'].values())}")
    log('答え', ans, f'{time.time() - t0:.0f}秒')


if __name__ == '__main__':
    main()
