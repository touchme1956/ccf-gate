#!/usr/bin/env python3
"""night/best15r_posthoc.py — best15r の事後の診断（判定に使わない・2026-11-01・参考・配分は変えない）

best15r（out/best15r_check.json）は決まりどおりなら「今のまま」だった（第2段の上位30はどれも、感度「分散の上乗せなし」で
15%以上の確率が今を下回った）。答えを見た後に、次の形を同じ物差し（best15r_check の FastBR・基礎率・条件 T1r・感度6本）で並べる:
  今／決まりの上位1位／第2段で感度6本をすべて通った形／厳しい形（どの業種も市場の比重＋15pt まで）の答え／
  GDX を入れない形の中の s の最良／FBT を25%までにした形の中の s の最良／S&P500 だけ
  （どれも第2段の同じ形の中から・条件 T1r と⑨を通る形）
出すもの: この物差しの値・感度6本それぞれの今との差（15%以上・平均・5%未満・最大下落）・「平均が感度6本すべてで今以上か」・
  元の物差し（A1・A2 を含む unx_assets.measure）・100年の代用・勝ち業種の中身の比重・最大の業種・中身の集中
使い方: python3 night/best15r_posthoc.py → out/best15r_posthoc.json
"""
import contextlib, io, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'best15r_posthoc.json')
FIXED = {'決まりの上位1位 FBT40/ITA20/SMH20/GDX15/XLV5': {'FBT': 40, 'ITA': 20, 'SMH': 20, 'GDX': 15, 'XLV': 5},
         '感度6本をすべて通った形 FBT40/QQQM25/XLV20/SMH15': {'FBT': 40, 'QQQM': 25, 'XLV': 20, 'SMH': 15},
         '厳しい形の答え ITA35/FBT25/GDX20/QQQM10/SMH10': {'ITA': 35, 'FBT': 25, 'GDX': 20, 'QQQM': 10, 'SMH': 10},
         'S&P500 だけ': {'VOO': 100}}


def main():
    t0 = time.time()
    import best15_check as B
    import best15c_check as BCc
    import best15r_check as BR
    import unx_assets as U
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    B.century_extend(U)
    P = BR.POOL
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    inds = sorted(st['mkt'])
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    INDall = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in inds] for c in P])
    cap = np.array([st['mkt'][k] for k in win])
    adj = {nm: BR.adj_vector(vec, st, r, P)[0] for nm, r in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    W0 = np.array([[B.NOW.get(c, 0) for c in P]], dtype=np.float64)
    e0, c0 = fbr.eval(W0, a0), cent.eval(W0)
    now = {k: float(np.asarray(v)[0]) for k, v in e0.items() if k != 'ok'}
    now.update(c30med=float(c0['c30med'][0]), c30min=float(c0['c30min'][0]))
    main_doc = json.load(open(os.path.join(BASE, 'out', 'best15r_check.json')))
    assets2 = main_doc['stage2']['本']
    A2s = B.all_forms(len(assets2), B.KMAX, B.CAP)
    A2 = np.zeros((len(A2s), len(P)), dtype=np.int8)
    A2[:, [P.index(c) for c in assets2]] = A2s
    E2 = BR.run(fbr, cent, A2, now, a0, IND, cap)
    f2, _ = BR.feas(E2, now)
    mx2 = BCc.maxima(E2, f2, E2['c30med'])
    s2, _, _ = BCc.score(E2, now, mx2, E2['c30med'], now['c30med'])
    ii = np.where(f2)[0]
    gi, fi = P.index('GDX'), P.index('FBT')
    forms = {'今': dict(B.NOW)}
    forms.update({k: v for k, v in FIXED.items() if not k.startswith('S&P')})
    for lab, mask in (('GDX を入れない形の中の s の最良', A2[ii, gi] == 0), ('FBT を25%までにした形の中の s の最良', A2[ii, fi] * B.STEP <= 25)):
        jj = ii[mask]
        if len(jj):
            b = BCc.order_s(jj, E2, s2, A2)[0]
            forms[f'{lab} {BR.name_of(A2[b])}'] = BR.form_of(A2[b])
    forms['S&P500 だけ'] = FIXED['S&P500 だけ']
    W = np.array([[f.get(c, 0) for c in P] for f in forms.values()], dtype=np.float64)
    Wn = W / W.sum(axis=1, keepdims=True)

    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    V = {v: (ve(W, v), ve(W0, v)) for v in BR.VARS}
    cs = cent.eval(W)
    E = fbr.eval(W, a0)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(forms, rows, chains, mega=U.mega_map(rows, sorted({a for f in forms.values() for a in f} | {'VOO'})))
    import upside_check as UC
    out = {}
    for j, (nm, f) in enumerate(forms.items()):
        diffs = {v: dict(P15=round(100 * float(V[v][0]['P15'][j] - V[v][1]['P15'][0]), 2),
                         平均=round(100 * float(V[v][0]['mean_pi'][j] - V[v][1]['mean_pi'][0]), 3),
                         五パーセント未満=round(100 * float(V[v][0]['P5'][j] - V[v][1]['P5'][0]), 2)) for v in BR.VARS}
        o = tab[UC.W_CRASH][nm]
        cm = U.century_monthly(f)
        out[nm] = dict(形=f,
                       この物差し=dict(P15π=round(100 * float(E['P15'][j]), 2), 平均=round(100 * float(E['mean_pi'][j]), 2),
                                    最悪の世界=round(100 * float(E['worst'][j]), 2), 五パーセント未満=round(100 * float(E['P5'][j]), 2),
                                    最大下落=round(100 * float(E['mdd'][j]), 1), ぶれ=round(100 * float(E['vol'][j]), 1),
                                    百年の中央=round(float(cs['c30med'][j]), 3), 百年の最悪=round(float(cs['c30min'][j]), 3)),
                       感度ごとの今との差=diffs,
                       平均が感度6本すべてで今以上=all(x['平均'] >= 0 for x in diffs.values()),
                       十五パーセント以上が感度6本すべてで今以上=all(x['P15'] >= 0 for x in diffs.values()),
                       五パーセント未満が感度6本すべてで今以下=all(x['五パーセント未満'] <= 0 for x in diffs.values()),
                       元の物差し_A1A2を含む=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 世界=o['世界ごとの年率'],
                                           過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上'], 積立20年の内部収益率=o['積立20年の内部収益率']),
                       百年=(None if cm is None else U.strip_century(cm)),
                       勝ち業種の中身の比重={k: round(100 * float(Wn[j] @ IND[:, i]), 1) for i, k in enumerate(win)},
                       最大の業種=max(((k, round(100 * float(Wn[j] @ INDall[:, i]), 1)) for i, k in enumerate(inds)), key=lambda t: t[1]),
                       中身の集中=B.lookthrough(f))
        print(nm, json.dumps({k: out[nm][k] for k in ('この物差し', '平均が感度6本すべてで今以上', '十五パーセント以上が感度6本すべてで今以上')}, ensure_ascii=False))
    json.dump(dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15r_posthoc.py', kind='事後の診断（判定に使わない）',
                   stage2_本=assets2, 条件を通った形=int(f2.sum()), forms=out, secs=round(time.time() - t0)),
              open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
