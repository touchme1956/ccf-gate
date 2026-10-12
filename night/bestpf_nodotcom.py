#!/usr/bin/env python3
"""night/bestpf_nodotcom.py — 「ドットコム・バブルのような下落はこの先は考えにくい」と置いたら答えはどう変わるか（2026-10-12）

読むだけ。門・採点・配分には触れない。ユーザーの問い「そもそもドットコムバブルのような下落は今後考えにくいと想定するなら？」への感度
（事前登録 out/bestpf_prereg.json の外＝仮定を置いた場合の計算。主の答えは out/bestpf_eval.json のまま）。

置き方: bestpf_eval と同じ物差し（5つの世界・π・20年の積立の内部収益率の表・同じ制約と同じ選び方）で、
  ① 世界 A1（直近26年の実績 2000-09〜）を、崩れの後の 2002-11〜2026-09 の実績に替える（★谷から始まるので上に偏る）
  ② 感度: 反発の年も外して 2004-01〜2026-09
  ③ ぶれと相関（確率の σ と B・C・D の分散の上乗せ）も、同じ窓（崩れを含まない）から取る＝2008・2020・2022 の下落は入る
  A2・B・C・D の各本の年率と π は変えない（B は100年の業種の歴史・C・D は2026年の予想で、ドットコムの崩れに直接は依らない）。
追加: 2022年型の半導体の下落（2021-12〜2022-09 の実際の値）を積立の16年目に置いた20年の内部収益率（2000年型の代わり）。
出力: out/bestpf_nodotcom.json
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

OUT = os.path.join(BASE, 'out', 'bestpf_nodotcom.json')
WORLDS = E.WORLDS
WINDOWS = {'base_2000-09': (200009, 202609), 'no_dotcom_2002-11': (200211, 202609), 'no_dotcom_rebound_2004-01': (200401, 202609)}
NAMED = {
    '今の形 NDX58.8/SMH23.5/ITA17.6': {'QQQM': 50, 'SMH': 20, 'ITA': 15},
    '事前登録の答え SMH60/インド20/ITA10/XLE10': {'SMH': 60, 'EPI_LONG': 20, 'ITA': 10, 'XLE': 10},
    '勧めた形 NDX20/SMH50/ITA20/XLE10': {'QQQM': 20, 'SMH': 50, 'ITA': 20, 'XLE': 10},
    'NDX40/SMH60': {'QQQM': 40, 'SMH': 60},
    'NDX50/SMH50': {'QQQM': 50, 'SMH': 50},
    'XLK40/SMH60': {'XLK': 40, 'SMH': 60},
    'S&P500（VOO）': {'VOO': 100},
    'NASDAQ100（QQQM）': {'QQQM': 100},
    '半導体（SMH）100': {'SMH': 100},
}
CRASH22 = (202112, 202209)


def main():
    res = X.rank_result()
    rows, chains = res['rows'], res['chains']
    assets = [c for c in rows if c != 'GLDM' and all(m in chains.get(c, {}) for m in R.months(*R.A1))]
    n = len(assets)
    k2 = R.months(*R.A2)
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    S2 = np.cov(np.log1p(G2), bias=True) * 12
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    Dmap, _, _ = E.load_D(rows, assets)
    pi_main, pi_sens, _ = E.load_pi()
    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi_main.items()}
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets]); gD = np.array([Dmap[c] for c in assets])
    tabs = P.dca_tables(20, [0.0, 0.05, 0.10, 0.15], log=False)
    sim = E.simulate_tables()
    vi = assets.index('VOO')
    out = {}
    for wname, (a, b) in WINDOWS.items():
        k1 = R.months(a, b)
        G1 = np.array([[chains[c][m] for m in k1] for c in assets])
        S1 = np.cov(np.log1p(G1), bias=True) * 12
        s1 = np.diag(S1).copy()
        A1_single = {c: float(np.expm1(np.log1p(G1[i]).sum() * 12 / len(k1)) + adj[i]) for i, c in enumerate(assets)}
        vol_single = {c: float(G1[i].std() * math.sqrt(12)) for i, c in enumerate(assets)}

        def wv_of(dot, a1g, a2g, q):
            bonus = 0.5 * (dot(s1) - q)
            return dict(A1=a1g + dot(adj), A2=a2g + dot(adj), B=np.expm1(dot(np.log1p(gB)) + bonus),
                        C=np.expm1(dot(np.log1p(gC)) + bonus), D=np.expm1(dot(np.log1p(gD)) + bonus))

        def probs(wv, sig, pi):
            o = {k: np.zeros_like(sig) for k in ('P15', 'P10', 'P5', 'P0')}
            for w in WORLDS:
                if pi.get(w, 0) <= 0:
                    continue
                m = np.log1p(np.clip(wv[w], -0.095, 0.56))
                o['P15'] += pi[w] * P.interp(tabs[0.15], m, sig); o['P10'] += pi[w] * P.interp(tabs[0.10], m, sig)
                o['P5'] += pi[w] * (1 - P.interp(tabs[0.05], m, sig)); o['P0'] += pi[w] * (1 - P.interp(tabs[0.0], m, sig))
            tot = sum(pi[w] for w in WORLDS if pi.get(w, 0) > 0)
            o = {k: v / tot for k, v in o.items()}
            live = [w for w in WORLDS if pi.get(w, 0) > 0]
            o['worst'] = np.min(np.vstack([wv[w] for w in live]), axis=0)
            o['mean_pi'] = sum(pi[w] * wv[w] for w in live) / tot
            return o

        print(f'== {wname} 組み合わせ', flush=True)
        g = E.build_grid(G1, G2, S1, S2, n)
        Wint = g['Wint']
        gdot = lambda x: E.wdot(Wint, x)   # noqa: E731
        wv = wv_of(gdot, g['a1g'], g['a2g'], g['q1'])
        sig = np.sqrt(g['q1'])
        e = np.zeros(n); e[vi] = 1.0
        vdot = lambda x: np.array([float(e @ x)])   # noqa: E731
        va1 = np.array([float(CB.path_stats(G1[vi][None, :], len(k1))[0][0])]); va2 = np.array([float(np.expm1(np.log1p(G2[vi]).sum() * 12 / len(k2)))])
        vwv = wv_of(vdot, va1, va2, np.array([S1[vi, vi]]))
        ent = {}
        for pname, pi in (('main', pi_main), ('noA2', noA2)):
            pr = probs(wv, sig, pi)
            pv = probs(vwv, np.array([math.sqrt(S1[vi, vi])]), pi)
            feas = pr['worst'] >= float(pv['worst'][0]) - 1e-12
            key = np.where(feas, pr['P15'], -1.0)
            near = np.where(feas & (pr['P15'] >= float(key.max()) - E.TIE))[0]
            i = int(near[np.lexsort((g['vol'][near], pr['P5'][near]))[0]])
            top = np.argsort(-key)[:1000]
            ent[pname] = dict(pick={assets[j]: int(Wint[i, j]) * 10 for j in range(n) if Wint[i, j]},
                              P15π=round(100 * float(pr['P15'][i]), 1), P10π=round(100 * float(pr['P10'][i]), 1),
                              P5π=round(100 * float(pr['P5'][i]), 1), P0π=round(100 * float(pr['P0'][i]), 1),
                              年率π=round(100 * float(pr['mean_pi'][i]), 2), 最悪の世界=round(100 * float(pr['worst'][i]), 2),
                              ぶれ=round(100 * float(g['vol'][i]), 1), 最大下落=round(100 * float(g['mdd'][i]), 1),
                              上位1000に入る割合={assets[j]: round(100 * float((Wint[top, j] > 0).mean()), 1) for j in range(n) if (Wint[top, j] > 0).mean() >= 0.05},
                              上位1000の平均の比={assets[j]: round(10 * float(Wint[top, j].mean()), 1) for j in range(n) if Wint[top, j].mean() >= 0.5})
            print(f"  {pname}: 1位 {ent[pname]['pick']} P15π {ent[pname]['P15π']} P5 {ent[pname]['P5π']} 最悪 {ent[pname]['最悪の世界']} 下落 {ent[pname]['最大下落']} 平均の比 {ent[pname]['上位1000の平均の比']}", flush=True)
        # 名前のある案
        named = {}
        for nm, wd in NAMED.items():
            tot = sum(wd.values())
            w = np.array([wd.get(c, 0) / tot for c in assets])
            Rp1 = w @ G1
            ps = CB.path_stats(Rp1[None, :], len(k1))
            q = float(w @ S1 @ w)
            d1 = lambda x, w=w: np.array([float(w @ x)])   # noqa: E731
            wvn = wv_of(d1, np.array([float(ps[0][0])]), np.array([float(np.expm1(np.log1p(w @ G2).sum() * 12 / len(k2)))]), np.array([q]))
            r = {}
            for pname, pi in (('main', pi_main), ('noA2', noA2)):
                pr = probs(wvn, np.array([math.sqrt(q)]), pi)
                r[pname] = dict(P15π=round(100 * float(pr['P15'][0]), 1), P10π=round(100 * float(pr['P10'][0]), 1), P5π=round(100 * float(pr['P5'][0]), 1),
                                P0π=round(100 * float(pr['P0'][0]), 1), 最悪の世界=round(100 * float(pr['worst'][0]), 2), 年率π=round(100 * float(pr['mean_pi'][0]), 2))
            r['世界ごと'] = {k: round(100 * float(v[0]), 2) for k, v in wvn.items()}
            r['ぶれ'] = round(100 * float(ps[1][0]), 1); r['最大下落（この窓）'] = round(100 * float(ps[2][0]), 1)
            r['IRR'] = E.irr_quantiles(sim, {k: math.log1p(float(v[0])) for k, v in wvn.items()}, math.sqrt(q), pi_main)
            # 2022年型の下落を16年目に（世界 B の伸びで組み直す積立）
            mB = math.log1p(float(wvn['B'][0])) / 12
            rets = [math.expm1(mB)] * 240
            cr = [float(w @ np.array([chains[c][m] for c in assets])) for m in R.months(*CRASH22)]
            for t, x in enumerate(cr):
                rets[180 + t] = x
            Wt = 0.0
            for x in rets:
                Wt = (Wt + 1) * (1 + x)
            r['2022年型の下落が16年目のIRR'] = round(100 * float(np.interp(Wt, sim['K'], sim['r_grid'])), 2)
            r['2022年型の下落の累計'] = round(100 * (float(np.prod([1 + x for x in cr])) - 1), 1)
            named[nm] = r
            print(f"  {nm[:34]:<34} P15π {r['main']['P15π']:5.1f}（A2抜き {r['noA2']['P15π']:4.1f}） P5 {r['main']['P5π']:4.1f} P0 {r['main']['P0π']:4.1f} 最悪 {r['main']['最悪の世界']:5.2f} A1 {r['世界ごと']['A1']:6.2f} ぶれ {r['ぶれ']:4.1f} 下落 {r['最大下落（この窓）']:6.1f} IRR中央 {r['IRR']['50%点']} 22年型16年目 {r['2022年型の下落が16年目のIRR']}", flush=True)
        out[wname] = dict(window=f'{a}〜{b}', months=len(k1), grid=ent, named=named,
                          single={c: dict(A1=round(100 * A1_single[c], 2), ぶれ=round(100 * vol_single[c], 1)) for c in assets})
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_nodotcom.py', posthoc=True,
               question='ドットコム・バブルのような下落はこの先は考えにくいと置いたら（ユーザーの問い）',
               how='A1 の窓と、ぶれ・相関の窓を崩れの後へ替える。A2・B・C・D の各本の年率と π は変えない。選び方は bestpf_eval と同じ',
               warn=['2002-11 から始めると谷から始まるので A1 は上に偏る（2004-01 からの版も並べる）',
                     'ドットコム級の崩れを外しても、2008・2020・2022 の下落はぶれに入っている',
                     '事前登録の外の感度（仮定を置いた計算）。主の答えは out/bestpf_eval.json'],
               pi_main=pi_main, results=out)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
