#!/usr/bin/env python3
"""night/bestpf_final.py — 事前登録の答えと、反論役の指摘を受けて実務に直した案を、同じ物差しと追加の点検で並べる（2026-10-12）

読むだけ。門・採点・配分（portfolio.json）には触れない。
★この道具の案は「事後」（最終の採点 out/bestpf_eval.json の結果と反論役4人の指摘を見た後）。選択の規則は事前登録のまま
  （答えは out/bestpf_eval.json の final_with_panel）。ここで並べるのは、その答えを実務で組むときの直し方の材料。

物差し（bestpf_eval と同じ）: A1・A2・B・C・D の5つの世界・重み π（R8）・20年の毎月の積立の内部収益率の表（etf_p15）。
追加の点検（反論役の指摘から）:
  noA2      … A2（直近15年の実績を延ばす世界）を外す
  stack     … R8 の重ね（A2=0・割安さ型に79%）の重み
  K4full    … 半導体の基礎率（過去10年1位の業種の次の10年 −4.0%/年）を薄めずに B・C・D へ
  yen20     … 20年で20%の円高（全部の世界から −ln(1.2)/20＝−0.91%/年）
  vol_only  … 全部の本に同じ年率（S&P500 の世界ごとの値）を与えた P15π＝ぶれと分散だけで出る分
  late_crash… 世界 B の伸びで毎月組み直す積立の16〜18年目に、2000-09〜2002-10 の実際の毎月の値（全部の本）を置いた20年の内部収益率
  vehicle   … 器の費用: NASDAQ100 を iFreeNEXT（QQQM より年0.345pt 高い）・インドを楽天・インド株Nifty50（EPI より年0.532pt 安い〔中身は違う〕）
出力: out/bestpf_final.json
"""
import datetime, json, math, os, sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R      # noqa: E402
import etf_forward_combo as CB    # noqa: E402
import etf_p15 as P               # noqa: E402
import bestpf_eval as E           # noqa: E402
import bestpf_ext as X            # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_final.json')
WORLDS = E.WORLDS
IFREE_EXTRA = 0.00495 - 0.0015
NIFTY_SAVE = 0.0084 - 0.00308
YEN20 = -math.log(1.2) / 20

CANDS = {
    '事前登録の答え SMH60/インド20/ITA10/XLE10': {'SMH': 60, 'EPI_LONG': 20, 'ITA': 10, 'XLE': 10},
    '同点の幅 インドなし SMH60/ITA30/XLE10': {'SMH': 60, 'ITA': 30, 'XLE': 10},
    'インドなし SMH60/ITA20/XLE20': {'SMH': 60, 'ITA': 20, 'XLE': 20},
    '前回の確率最大 SMH60/ITA40': {'SMH': 60, 'ITA': 40},
    '実務（反論役）NDX20/SMH45/インド15/ITA10/XLE10': {'QQQM': 20, 'SMH': 45, 'EPI_LONG': 15, 'ITA': 10, 'XLE': 10},
    '実務・インドなし NDX20/SMH50/ITA20/XLE10': {'QQQM': 20, 'SMH': 50, 'ITA': 20, 'XLE': 10},
    '実務・インドなし NDX20/SMH45/ITA20/XLE15': {'QQQM': 20, 'SMH': 45, 'ITA': 20, 'XLE': 15},
    '実務・インドなし NDX20/SMH50/ITA15/XLE15': {'QQQM': 20, 'SMH': 50, 'ITA': 15, 'XLE': 15},
    '実務・ITA が NISA 不可なら NDX20/SMH50/VBR15/XLE15': {'QQQM': 20, 'SMH': 50, 'VBR': 15, 'XLE': 15},
    '実務・守り NDX20/SMH40/ITA20/XLE20': {'QQQM': 20, 'SMH': 40, 'ITA': 20, 'XLE': 20},
    '今の形 NDX58.8/SMH23.5/ITA17.6': {'QQQM': 50, 'SMH': 20, 'ITA': 15},
    'S&P500（VOO）': {'VOO': 100},
    'NASDAQ100（QQQM）': {'QQQM': 100},
    '全世界株（VT）': {'VT': 100},
}
VEHICLE = {'QQQM': -IFREE_EXTRA, 'EPI_LONG': +NIFTY_SAVE}


def main():
    res = X.rank_result()
    rows, chains = res['rows'], res['chains']
    k1, k2 = R.months(*R.A1), R.months(*R.A2)
    assets = sorted({a for w in CANDS.values() for a in w} | {'VOO'})
    G1 = np.array([[chains[c][m] for m in k1] for c in assets])
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    S1 = np.cov(np.log1p(G1), bias=True) * 12
    s1 = np.diag(S1).copy()
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    Dmap, _, _ = E.load_D(rows, assets)
    pi_main, pi_sens, _ = E.load_pi()
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets]); gD = np.array([Dmap[c] for c in assets])
    chips = {}
    for c in assets:
        if c == 'VOO':
            chips[c] = CB.CHIPS_MKT
        elif (R.C.get(c) or {}).get('us'):
            chips[c] = float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    k4 = np.array([(-CB.CHIPS_GAP * chips[c] + rest * (1 - chips[c])) if c in chips else 0.0 for c in assets])   # 薄めない（÷2 しない）
    veh = np.array([VEHICLE.get(c, 0.0) for c in assets])
    tabs = P.dca_tables(20, [0.0, 0.05, 0.10, 0.15], log=False)
    sim = E.simulate_tables()
    vi = assets.index('VOO')

    def worlds(w, mode='main'):
        Rp1, Rp2 = w @ G1, w @ G2
        a1 = float(CB.path_stats(Rp1[None, :], len(k1))[0][0]); a2 = float(np.expm1(np.log1p(Rp2).sum() * 12 / len(k2)))
        q = float(w @ S1 @ w)
        bonus = 0.5 * (float(w @ s1) - q)
        b, c, d = gB, gC, gD
        if mode == 'K4full':
            b, c, d = gB + k4, gC + k4, gD + k4
        extra = float(w @ veh) if mode == 'vehicle' else 0.0
        out = dict(A1=a1 + float(w @ adj) + extra, A2=a2 + float(w @ adj) + extra,
                   B=math.expm1(float(w @ np.log1p(b)) + bonus) + extra, C=math.expm1(float(w @ np.log1p(c)) + bonus) + extra,
                   D=math.expm1(float(w @ np.log1p(d)) + bonus) + extra)
        if mode == 'yen20':
            out = {k: math.expm1(math.log1p(v) + YEN20) for k, v in out.items()}
        return out, math.sqrt(q), bonus

    def prob(wv, sig, pi, tau):
        t = tabs[tau]
        p = 0.0
        for k in WORLDS:
            if pi.get(k, 0) > 0:
                v = float(P.interp(t, np.array([math.log1p(wv[k])]), np.array([sig]))[0])
                p += pi[k] * (v if tau >= 0.10 else 1 - v)
        return p / sum(pi[k] for k in WORLDS if pi.get(k, 0) > 0)

    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi_main.items()}
    voo_w = np.zeros(len(assets)); voo_w[vi] = 1.0
    voo_main = worlds(voo_w)[0]

    def late_crash(w):
        """世界 B の伸びで組み直す積立の 16〜18年目に、2000-09〜2002-10 の実際の値を置く（全部の本）"""
        crash = [m for m in k1 if m <= 200210]
        mB = math.log1p(worlds(w)[0]['B']) / 12
        T = 240
        rets = [math.expm1(mB)] * T
        cr = [float(w @ np.array([chains[c][m] for c in assets])) for m in crash]
        for i, r in enumerate(cr):
            rets[180 + i] = r
        W = 0.0
        for r in rets:
            W = (W + 1) * (1 + r)
        K = sim['K']; rg = sim['r_grid']
        return float(np.interp(W, K, rg)), round(100 * (np.prod([1 + r for r in cr]) - 1), 1)

    out = {}
    for nm, wd in CANDS.items():
        tot = sum(wd.values())
        w = np.array([wd.get(c, 0) / tot for c in assets])
        wv, sig, bonus = worlds(w)
        g = CB.path_stats((w @ G1)[None, :], len(k1))
        r = dict(weights={k: round(100 * v / tot, 1) for k, v in wd.items()},
                 P15π=round(100 * prob(wv, sig, pi_main, 0.15), 1), P10π=round(100 * prob(wv, sig, pi_main, 0.10), 1),
                 P5π=round(100 * prob(wv, sig, pi_main, 0.05), 1), P0π=round(100 * prob(wv, sig, pi_main, 0.0), 1),
                 世界ごと={k: round(100 * v, 2) for k, v in wv.items()}, 最悪の世界=round(100 * min(wv.values()), 2),
                 π加重の年率=round(100 * sum(pi_main[k] * wv[k] for k in WORLDS), 2),
                 ぶれ=round(100 * float(g[1][0]), 1), 最大下落=round(100 * float(g[2][0]), 1), 分散の上乗せ=round(100 * bonus, 2),
                 IRR=E.irr_quantiles(sim, {k: math.log1p(v) for k, v in wv.items()}, sig, pi_main))
        r['P15_noA2'] = round(100 * prob(wv, sig, noA2, 0.15), 1)
        if 'stack' in pi_sens:
            r['P15_stack'] = round(100 * prob(wv, sig, pi_sens['stack'], 0.15), 1)
        wk, sk, _ = worlds(w, 'K4full')
        r['P15_K4full'] = round(100 * prob(wk, sk, pi_main, 0.15), 1); r['最悪_K4full'] = round(100 * min(wk.values()), 2)
        wy, sy, _ = worlds(w, 'yen20')
        r['P15_yen20'] = round(100 * prob(wy, sy, pi_main, 0.15), 1); r['P5_yen20'] = round(100 * prob(wy, sy, pi_main, 0.05), 1)
        wvh, svh, _ = worlds(w, 'vehicle')
        r['P15_vehicle'] = round(100 * prob(wvh, svh, pi_main, 0.15), 1)
        r['P15_vol_only'] = round(100 * prob(voo_main, sig, pi_main, 0.15), 1)
        lc, crash_cum = late_crash(w)
        r['崩れが16〜18年目のIRR'] = round(100 * lc, 2); r['崩れの期間の累計'] = crash_cum
        hs = P.hist_success(w[None, :], G1, adj, len(k1), tau=0.15)
        r['過去の転がる20年で15%以上'] = round(100 * float(hs[240][0]), 1)
        out[nm] = r
        print(f"{nm[:40]:<40} P15π {r['P15π']:5.1f} [A2抜き {r['P15_noA2']:4.1f} 重ね {r.get('P15_stack', 0):4.1f} K4全部 {r['P15_K4full']:4.1f}(最悪{r['最悪_K4full']}) 円高20% {r['P15_yen20']:4.1f} 器 {r['P15_vehicle']:4.1f} ぶれだけ {r['P15_vol_only']:4.1f}] "
              f"P10 {r['P10π']:4.1f} P5 {r['P5π']:4.1f} P0 {r['P0π']:4.1f} 最悪 {r['最悪の世界']:5.2f} 下落 {r['最大下落']:6.1f} 崩れ後半 {r['崩れが16〜18年目のIRR']:5.2f} 過去20年 {r['過去の転がる20年で15%以上']:5.1f} IRR中央 {r['IRR']['50%点']}")
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_final.py', posthoc=True,
               note='事後の比較（最終の採点と反論役の指摘を見た後）。選択の規則と答えは out/bestpf_eval.json の final_with_panel。',
               pi_main=pi_main, voo_worst=round(100 * min(voo_main.values()), 2), candidates=out)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
