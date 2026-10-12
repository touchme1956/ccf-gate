#!/usr/bin/env python3
"""night/bestpf_smh_timing.py — 「SMH は暴落のタイミングなどが難しいのでは？」に、SMH の量ごとの得と損を同じ物差しで並べる（2026-10-12）

読むだけ。門・採点・配分には触れない。事前登録の外（ユーザーの問いへの感度）。物差しは bestpf_eval と同じ
（5つの世界・π・20年の毎月の積立の内部収益率の表）。窓は2つ: 崩れあり（A1 2000-09〜）／ドットコム級なし（A1 と共分散 2002-11〜）。

並べるもの（SMH の量 0〜60%）:
  族1 NDX＋SMH            … NASDAQ100（QQQM＝iFreeNEXT と同じ指数）と SMH だけ
  族2 NDX20＋SMH＋ITA:XLE（2:1） … 前回勧めた形の延長
  P15π・P5π（5%未満）・P0π（元本割れ）・最大下落（A1 の窓）
  崩れの置き場所: 世界 B の伸びで毎月組み直す20年の積立に、実際の下落の月々を置く
     2000年型（2000-09〜2002-10・26か月）を 1〜3年目／16〜18年目、2022年型（2021-12〜2022-09）を 1年目／16年目
  過去の実際の並び（2000-09〜2026-09）で転がる20年の積立が15%以上だった割合
  滑り台（16年目から SMH を半分にする）: 1〜15年目は族2 の SMH50、16〜20年目は SMH25（減らした分は VOO）。
     確率は「前半と後半で別の正規分布」の近似（16年目に一度だけ組み直す＝NISA の中で売って買い直す前提・年の枠の上限は数えていない）
出力: out/bestpf_smh_timing.json
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

OUT = os.path.join(BASE, 'out', 'bestpf_smh_timing.json')
WORLDS = E.WORLDS
WINDOWS = {'崩れあり 2000-09〜': (200009, 202609), 'ドットコム級なし 2002-11〜': (200211, 202609)}
CRASH00 = (200009, 200210)
CRASH22 = (202112, 202209)
SHARES = [0, 10, 20, 30, 40, 50, 60]


def fam1(s):
    return {'QQQM': 100 - s, 'SMH': s} if s < 100 else {'SMH': 100}


def fam2(s):
    rest = 80 - s
    return {'QQQM': 20, 'SMH': s, 'ITA': rest * 2 / 3, 'XLE': rest / 3}


def main():
    res = X.rank_result()
    rows, chains = res['rows'], res['chains']
    assets = ['QQQM', 'SMH', 'ITA', 'XLE', 'VOO']
    k2 = R.months(*R.A2)
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    Dmap, _, _ = E.load_D(rows, assets)
    pi, _, _ = E.load_pi()
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets]); gD = np.array([Dmap[c] for c in assets])
    tabs = P.dca_tables(20, [0.0, 0.05, 0.15], log=False)
    sim = E.simulate_tables()
    T = 240
    rng = np.random.default_rng(20261012)
    Z = rng.standard_normal((40000, T))
    Kg, rg = sim['K'], sim['r_grid']
    K15 = float(np.sum(1.15 ** (np.arange(1, T + 1) / 12.0)))
    K05 = float(np.sum(1.05 ** (np.arange(1, T + 1) / 12.0)))
    out = {}
    for wname, (a, b) in WINDOWS.items():
        k1 = R.months(a, b)
        G1 = np.array([[chains[c][m] for m in k1] for c in assets])
        S1 = np.cov(np.log1p(G1), bias=True) * 12
        s1 = np.diag(S1).copy()

        def worlds(w):
            Rp1, Rp2 = w @ G1, w @ G2
            a1 = float(CB.path_stats(Rp1[None, :], len(k1))[0][0]); a2 = float(np.expm1(np.log1p(Rp2).sum() * 12 / len(k2)))
            q = float(w @ S1 @ w); bonus = 0.5 * (float(w @ s1) - q)
            return dict(A1=a1 + float(w @ adj), A2=a2 + float(w @ adj), B=math.expm1(float(w @ np.log1p(gB)) + bonus),
                        C=math.expm1(float(w @ np.log1p(gC)) + bonus), D=math.expm1(float(w @ np.log1p(gD)) + bonus)), math.sqrt(q)

        def pr(wv, sig, tau):
            p = 0.0
            for k in WORLDS:
                v = float(P.interp(tabs[tau], np.array([math.log1p(wv[k])]), np.array([sig]))[0])
                p += pi[k] * (v if tau >= 0.15 else 1 - v)
            return p

        def placed(w, mB, crash, at):
            rets = [math.expm1(mB)] * T
            cr = [float(w @ np.array([chains[c][m] for c in assets])) for m in R.months(*crash)]
            for t, x in enumerate(cr):
                rets[at + t] = x
            Wt = 0.0
            for x in rets:
                Wt = (Wt + 1) * (1 + x)
            return float(np.interp(Wt, Kg, rg))

        def row(wd):
            tot = sum(wd.values())
            w = np.array([wd.get(c, 0) / tot for c in assets])
            wv, sig = worlds(w)
            mdd = float(CB.path_stats((w @ G1)[None, :], len(k1))[2][0])
            mB = math.log1p(wv['B']) / 12
            hs = P.hist_success(w[None, :], G1, adj, len(k1), tau=0.15)
            flat = float(np.interp(sum((1 + math.expm1(mB)) ** (T - t) for t in range(T)), Kg, rg))
            return {'weights': {k: round(v, 1) for k, v in wd.items() if v}, 'P15π': round(100 * pr(wv, sig, 0.15), 1),
                    'P5π': round(100 * pr(wv, sig, 0.05), 1), 'P0π': round(100 * pr(wv, sig, 0.0), 1), '最大下落': round(100 * mdd, 1),
                    '崩れ2000型_1〜3年目': round(100 * placed(w, mB, CRASH00, 0), 2), '崩れ2000型_16〜18年目': round(100 * placed(w, mB, CRASH00, 180), 2),
                    '下落2022型_1年目': round(100 * placed(w, mB, CRASH22, 0), 2), '下落2022型_16年目': round(100 * placed(w, mB, CRASH22, 180), 2),
                    '崩れなしの世界B': round(100 * flat, 2), '過去の転がる20年で15以上': round(100 * float(hs[240][0]), 1), '_wv': wv, '_sig': sig}

        tab = {'族1 NDX＋SMH': {}, '族2 NDX20＋SMH＋ITA/XLE': {}}
        for s in SHARES:
            tab['族1 NDX＋SMH'][s] = row(fam1(s))
            tab['族2 NDX20＋SMH＋ITA/XLE'][s] = row(fam2(s))
        # 滑り台: 族2 SMH50 → 16年目から SMH25（減らした分は VOO）
        A = tab['族2 NDX20＋SMH＋ITA/XLE'][50]
        Bw = {'QQQM': 20, 'SMH': 25, 'ITA': 20, 'XLE': 10, 'VOO': 25}
        Bt = row(Bw)
        p15 = p05 = 0.0
        for k in WORLDS:
            mA, sA = math.log1p(A['_wv'][k]) / 12, A['_sig'] / math.sqrt(12)
            mB_, sB = math.log1p(Bt['_wv'][k]) / 12, Bt['_sig'] / math.sqrt(12)
            L = np.where(np.arange(T) < 180, mA, mB_)[None, :] + Z * np.where(np.arange(T) < 180, sA, sB)[None, :]
            G = np.exp(np.flip(np.cumsum(np.flip(L, axis=1), axis=1), axis=1))
            Wt = G.sum(axis=1)
            p15 += pi[k] * float((Wt >= K15).mean()); p05 += pi[k] * float((Wt < K05).mean())
        # 崩れを16〜18年目に置いた滑り台（崩れは減らした後の形に当たる）
        wA = np.array([A['weights'].get(c, 0) / 100 for c in assets]); wB = np.array([Bw.get(c, 0) / 100 for c in assets])
        mBA = math.log1p(A['_wv']['B']) / 12
        rets = [math.expm1(mBA)] * T
        cr = [float(wB @ np.array([chains[c][m] for c in assets])) for m in R.months(*CRASH00)]
        for t, x in enumerate(cr):
            rets[180 + t] = x
        Wt = 0.0
        for x in rets:
            Wt = (Wt + 1) * (1 + x)
        glide = {'前半': A['weights'], '後半': Bw, 'P15π': round(100 * p15, 1), 'P5π': round(100 * p05, 1),
                 '崩れ2000型_16〜18年目': round(100 * float(np.interp(Wt, Kg, rg)), 2),
                 'note': '16年目に一度だけ組み直す（NISA の中で売って買い直す前提・年の枠の上限は数えていない）。確率は前半と後半で別の正規分布の近似'}
        for f in tab.values():
            for v in f.values():
                v.pop('_wv'); v.pop('_sig')
        out[wname] = dict(table=tab, glide=glide)
        print('==', wname)
        for fn, f in tab.items():
            for s, v in f.items():
                print(f"  {fn[:10]} SMH{s:>3}: P15π {v['P15π']:5.1f} P5 {v['P5π']:5.1f} P0 {v['P0π']:4.1f} 下落 {v['最大下落']:6.1f} | 崩れ00 前 {v['崩れ2000型_1〜3年目']:5.2f} 後 {v['崩れ2000型_16〜18年目']:5.2f} | 下落22 前 {v['下落2022型_1年目']:5.2f} 後 {v['下落2022型_16年目']:5.2f} | 崩れなし {v['崩れなしの世界B']:5.2f} | 過去20年 {v['過去の転がる20年で15以上']:5.1f}")
        print('  滑り台', glide)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_smh_timing.py', posthoc=True,
               question='SMH は暴落のタイミングなどが難しいのでは？（ユーザーの問い）', pi=pi, results=out,
               warn=['崩れの置き場所の計算は、世界 B の伸びの上に実際の下落の月々を置いた決まった道（確率ではない）',
                     '滑り台は NISA の中で売って買い直す前提。成長投資枠の年240万円（1人）の上限では一度に移せない場合がある'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
