#!/usr/bin/env python3
"""night/future30_options.py — 30年の構造の案を、これまでの判断と同じ物差しで並べる（2026-10-11・future30 の続き）

読むだけ。門・採点・配分には触れない。future30（事前登録 out/future30_prereg.json aa6405d）の結果を受けた
『判断の材料』で、仮説の検定ではない（事前登録の外＝事後）。案と勧め方は計算の前にこのファイルに固定してコミットする。

案（合計の比・個別株15%は castle_rule が決めるので固定。ETF 側85%の中で『更新する芯』を全世界株式 VT に置く）:
  O0 今                 … QQQM 50 / SMH 20 / ITA 15
  O1 芯10（SMH から）   … QQQM 50 / SMH 10 / ITA 15 / VT 10
  O2 芯15（ITA の席を） … QQQM 50 / SMH 20 / VT 15
  O3 芯30               … ETF 側の30%を VT に・残りは今の比のまま（QQQM 35 / SMH 14 / ITA 10.5 / VT 25.5）
  O4 芯50               … 同じく50%（QQQM 25 / SMH 10 / ITA 7.5 / VT 42.5）
  参考 O3S             … O3 の VT を S&P500（VOO）に
  参考 市場だけ         … VT 85
物差し:
  ① 4つの世界（etf_forward_combo の A1 直近26年・A2 直近15年・B 100年の平均・C JPM）の年率の平均と最悪・ぶれ・最大下落
  ② etf_p15 の20年の毎月の積立の内部収益率が 15%以上／10%以上／5%未満／元本割れ の確率・過去の転がる窓で15%以上だった割合
  ③ future30 の Q3b と同じ100年の代用（NASDAQ100＝テック65%＋市場35%・SMH＝Chips・ITA＝Aero＋Guns・VT と VOO と個別株＝米国の市場）で
     30年の積立（起点1965〜1995）と20年の積立（起点1965〜2005）の市場との比の中央値・下位10%点・最悪
     ⚠ 100年の代用には米国外が無い（VT の米国外の分も米国の市場で代える）＝国の分散の効きは③に出ない
勧め方（計算の前に固定）:
  条件＝ 15%以上の確率 ≥ 今−3pt ∧ 最悪の世界 > 今 ∧ 5%未満 < 今（etf_balanced_eval と同じ）。
  O1〜O4 のうち条件を満たす案があれば、その中で芯が最も大きい案（30年の更新力を最も足せる案）を勧める。無ければ『今のまま』。
  採否はユーザーが決める（この道具は portfolio.json を書かない）
出力: out/future30_options.json
"""
import datetime, json, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import numpy as np                 # noqa: E402
import etf_p15 as P                # noqa: E402
import mw_common as M              # noqa: E402
import gaps_common as G            # noqa: E402
import future30 as F               # noqa: E402

OPTS = {
    'O0 今': {'QQQM': 50, 'SMH': 20, 'ITA': 15},
    'O1 芯10（SMH から）': {'QQQM': 50, 'SMH': 10, 'ITA': 15, 'VT': 10},
    'O2 芯15（ITA の席を）': {'QQQM': 50, 'SMH': 20, 'VT': 15},
    'O3 芯30': {'QQQM': 35, 'SMH': 14, 'ITA': 10.5, 'VT': 25.5},
    'O4 芯50': {'QQQM': 25, 'SMH': 10, 'ITA': 7.5, 'VT': 42.5},
    '参考 O3S（芯30を S&P500 で）': {'QQQM': 35, 'SMH': 14, 'ITA': 10.5, 'VOO': 25.5},
    '参考 市場だけ（VT）': {'VT': 85},
}
CORE = {'O1 芯10（SMH から）': 10, 'O2 芯15（ITA の席を）': 15, 'O3 芯30': 25.5, 'O4 芯50': 42.5}


def forward():
    CB = P.CB
    ctx = CB.build(max_k=1)
    C = CB.CANDS
    G1, adj, T1, base_of, worlds = ctx['G1'], ctx['adj'], ctx['T1'], ctx['base_of'], ctx['worlds']
    k1 = CB.R.months(*CB.R.A1)
    side = lambda t: {k: v / sum(t.values()) for k, v in t.items()}
    W = np.vstack([[side(t).get(c, 0.0) for c in C] for t in OPTS.values()])
    bs = base_of(W)
    wv = worlds(W, bs, 'main')
    sig = np.sqrt(bs['q1'])
    tabs = P.dca_tables(20, [0.0, 0.05, 0.10, 0.15], log=False)
    names = ['A1', 'A2', 'B', 'C']
    pr = lambda th: np.mean([P.interp(tabs[th], np.log1p(wv[n]), sig) for n in names], axis=0)
    p15, p10, p5, p0 = pr(0.15), pr(0.10), 1 - pr(0.05), 1 - pr(0.0)
    hs = P.hist_success(W, G1, adj, T1)
    fx = M.yahoo('JPY=X')
    eps = {'ITバブル崩壊': (200009, 200212), 'リーマン': (200707, 200906), 'コロナ': (202001, 202006), '利上げ2022': (202201, 202212)}

    def dd(rs):
        v = pk = 1.0
        m, under, longest = 0.0, 0, 0
        for r in rs:
            v *= 1 + r
            if v >= pk:
                pk, under = v, 0
            else:
                under += 1
                longest = max(longest, under)
            m = min(m, v / pk - 1)
        return m, longest / 12
    rows = {}
    for i, (nm, t) in enumerate(OPTS.items()):
        r_usd = {k: float(W[i] @ G1[:, j]) for j, k in enumerate(k1)}
        yen = [(1 + r_usd[k]) * (1 + fx[k]) - 1 for k in k1]
        ydd, yund = dd(yen)
        rows[nm] = dict(
            合計の比=t, ETF側の中の比={k: round(100 * v, 1) for k, v in side(t).items()},
            年率_A1=round(100 * wv['A1'][i], 2), 年率_A2=round(100 * wv['A2'][i], 2), 年率_B=round(100 * wv['B'][i], 2), 年率_C=round(100 * wv['C'][i], 2),
            年率_4つの平均=round(100 * wv['mean'][i], 2), 年率_最悪の世界=round(100 * wv['worst'][i], 2),
            ぶれ=round(100 * bs['vol'][i], 1), 最大下落=round(100 * bs['mdd'][i], 1),
            確率_15以上=round(100 * p15[i], 1), 確率_10以上=round(100 * p10[i], 1), 確率_5未満=round(100 * p5[i], 1), 確率_元本割れ=round(100 * p0[i], 1),
            過去の転がる20年で15以上=round(100 * hs[240][i], 1),
            暴落の局面の下落={e: round(100 * dd([r_usd[k] for k in P.CB.R.months(a, b)])[0], 1) for e, (a, b) in eps.items()},
            円の最大下落=round(100 * ydd, 1), 円で高値を下回った最長年=round(yund, 1))
    return rows


def century():
    cols, ret, capm, me, be, share, mkt = F.load()
    endm = max(mkt)
    tech = G.french_tech()
    allm = sorted(mkt)
    ndx = F.mix([(0.65, tech), (0.35, mkt)], allm)
    dfn = F.capw(ret, capm, ['Aero', 'Guns'], allm)
    parts = {'QQQM': ndx, 'SMH': ret['Chips'], 'ITA': dfn, 'VT': mkt, 'VOO': mkt}
    res = {}
    for nm, t in OPTS.items():
        tot = dict(t)
        tot['個別株'] = 15
        s = F.mix([(w / 100, parts.get(k, mkt)) for k, w in tot.items()], allm)
        d = {}
        for n, lab, starts in ((360, '30年の積立（起点1965〜1995）', range(1965, 1996)), (240, '20年の積立（起点1965〜2005）', range(1965, 2006))):
            v = []
            for y in starts:
                ms = F.months((y + 1) * 100 + 1, n)
                if ms[-1] > endm:
                    continue
                a, b = F.dca_mult(s, ms), F.dca_mult(mkt, ms)
                if a and b:
                    v.append(a / b)
            v.sort()
            q = lambda p: v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]
            d[lab] = {'窓': len(v), '中央値': round(S.median(v), 3), '下位10%点': round(q(0.10), 3), '最悪': round(v[0], 3),
                      '市場に勝った割合': round(sum(x > 1 for x in v) / len(v), 2)}
        res[nm] = d
    return res


def main():
    fw = forward()
    cn = century()
    now = fw['O0 今']
    ok = {nm: bool(fw[nm]['確率_15以上'] >= now['確率_15以上'] - 3 and fw[nm]['年率_最悪の世界'] > now['年率_最悪の世界']
                   and fw[nm]['確率_5未満'] < now['確率_5未満']) for nm in CORE}
    cand = [nm for nm in CORE if ok[nm]]
    rec = max(cand, key=lambda k: CORE[k]) if cand else 'O0 今（今のまま）'
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/future30_options.py',
           '位置づけ': '判断の材料（事後・仮説の検定ではない）。案と勧め方は計算の前にこのファイルに固定',
           '勧め方': '条件＝15%以上の確率 ≥ 今−3pt ∧ 最悪の世界 > 今 ∧ 5%未満 < 今。満たす案のうち芯が最も大きい案。無ければ今のまま',
           '条件を満たすか': ok, '勧める案（決まりどおり）': rec,
           '物差し①②_4つの世界と積立の確率（ETF 側・個別株15%は除く）': fw,
           '物差し③_100年の代用（個別株15%は米国の市場で代える・米国外は無い）': cn}
    with open(os.path.join(BASE, 'out', 'future30_options.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for nm in OPTS:
        r = fw[nm]
        c30 = cn[nm]['30年の積立（起点1965〜1995）']
        c20 = cn[nm]['20年の積立（起点1965〜2005）']
        print(f"{nm:<26} 平均{r['年率_4つの平均']:5.2f} 最悪{r['年率_最悪の世界']:5.2f} ぶれ{r['ぶれ']} 下落{r['最大下落']} | 15%以上{r['確率_15以上']} 5%未満{r['確率_5未満']} 元本割れ{r['確率_元本割れ']} | "
              f"100年30年 {c30['中央値']}/{c30['下位10%点']}/{c30['最悪']} 20年 {c20['中央値']}/{c20['下位10%点']}/{c20['最悪']}")
    print('条件', ok, '→ 勧める案', rec)


if __name__ == '__main__':
    main()
