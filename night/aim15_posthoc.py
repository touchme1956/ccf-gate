#!/usr/bin/env python3
"""night/aim15_posthoc.py — aim15_check の事後の診断（2026-11-23・判定に使わない）

aim15_check の結果（決まりの答え＝NASDAQ100 25 / SMH 35 / FBT 15 / VBR 25・P15π の並びの1位＝NASDAQ100 25 / SMH 35 / ITA 20 / FBT 20 は
F2〔業種の基礎率〕だけ通らない・答えは実績の側〔⑩⑪〕が今より下がる）を見たあとで足した読み解き。
★結果を見たあとの追加なので、登録した決まりの答えは変えない。
  H1 答え・並びの1位・今の形・R の「15%以上の確率」を3通りで: 元（P15π）／直近15年の世界を外す／未来の3つの世界だけ、と基礎率の物差し・実績
  H2 小型バリューの上乗せが消えたら（five_mix の S2 と同じ置き方: B の世界の VBR から100年の上乗せ B_X×0.5 を引き、C・D の VBR を VOO と同じに）
     元の物差しと基礎率の物差しの 期待の年率・P15π・5%未満
  H3 条件を足す: G1〜G3 ＋ 実績を今より下げない（⑩年率の中央・⑪年15%以上の窓 ≥ 今）＋ F2（基礎率の感度6本）をすべての形に当てる。
     通る形の数・P15π の順の上位と F1・F3。通る形が無ければ、F2 と実績のどちらを外すと何が1位になるかを並べる
  H4 相棒の入れ替えの線: NASDAQ100 25 / SMH 35 / FBT 15 を固定し、残り25を ITA x・VBR 25−x に分けた6通り（x=0〜25）
  H5 （H1〜H4 を見たあとに足した）並びの1位と、H4 の線の中ほど＝NASDAQ100 25 / SMH 35 / ITA 15 / FBT 15 / VBR 10 の詳しい物差し
     （答えの詳しい物差しは aim15_check.json にある）。H1・H2 にもこの中ほどの形を並べる
使い方: python3 night/aim15_posthoc.py → out/aim15_posthoc.json（約1分）
"""
import json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'aim15_posthoc.json')

import aim15_check as A15  # noqa: E402

ANS = {'QQQM': 25, 'SMH': 35, 'FBT': 15, 'VBR': 25}
TOP = {'QQQM': 25, 'SMH': 35, 'ITA': 20, 'FBT': 20}
MID = {'QQQM': 25, 'SMH': 35, 'ITA': 15, 'FBT': 15, 'VBR': 10}


def log(*a):
    print('[aim15_post]', *a, file=sys.stderr, flush=True)


def main():
    t0 = time.time()
    c = A15.main(write=False)
    main_js = json.load(open(A15.OUT))
    fast, fbr, a0, ve, ve_names = c['fast'], c['fbr'], c['a0'], c['ve'], c['ve_names']
    W_of, rows, P, realized = c['W_of'], c['rows'], c['P'], A15.realized
    Y, YA, names, forms, G = c['Y'], c['YA'], c['names'], c['forms'], c['G']
    Aw, yN, yR, meas = c['A'], c['yN'], c['yR'], c['meas']
    base, g2, g3, order, fcheck, FC, brief = c['base'], c['g2'], c['g3'], c['order'], c['fcheck'], c['FC'], c['brief']
    NOWF, RF, nm, r, EPS = A15.NOWF, A15.RF, A15.nm, A15.r, A15.EPS
    if main_js['主']['答え']['名前'] != nm(ANS) or main_js['主']['並びの1位']['名前'] != nm(TOP):
        raise SystemExit('aim15_check.json の答え・1位がこの診断の前提と違う')

    F4 = {'今の形（main）': NOWF, 'R（枝の案）': RF, '答え（決まり）': ANS, '並びの1位（F2 を通らない）': TOP,
          '中ほど（ITA 15 / FBT 15 / VBR 10）': MID}
    W4 = W_of(F4.values())

    # ── H1 ──
    e, b, rz = fast.eval(W4), fbr.eval(W4, a0), realized(W4, fast)
    h1 = {k: dict(形=nm(f), P15π=r(100 * e['P15'][j]), 直近15年を外したP15=r(100 * e['P15_noA2'][j]), 未来の3つの世界だけのP15=r(100 * e['P15_fwd'][j]),
                  基礎率のP15=r(100 * b['P15'][j]), 基礎率の平均=r(100 * b['mean_pi'][j]), 基礎率の5パーセント未満=r(100 * b['P5'][j]),
                  実績の年15パーセント以上の窓=r(100 * rz['share'][j], 1), 実績の年率の中央=r(100 * rz['med'][j]))
          for j, (k, f) in enumerate(F4.items())}

    # ── H2 小型バリューの上乗せなし ──
    iv, ivoo = P.index('VBR'), P.index('VOO')
    bx = 0.5 * float(rows['VBR']['B_X'])
    lB0, lC0, lD0 = fast.lB.copy(), fast.lC.copy(), fast.lD.copy()
    gB0, gC0, gD0 = fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy()
    try:
        fast.lB[iv] = np.log1p(np.expm1(lB0[iv]) - bx)
        fast.lC[iv], fast.lD[iv] = lC0[ivoo], lD0[ivoo]
        e2 = fast.eval(W4)
        fbr.gB[iv] -= bx
        fbr.gC[iv], fbr.gD[iv] = fbr.gC[ivoo], fbr.gD[ivoo]
        b2 = fbr.eval(W4, a0)
    finally:
        fast.lB, fast.lC, fast.lD = lB0, lC0, lD0
        fbr.gB, fbr.gC, fbr.gD = gB0, gC0, gD0
    chk = fast.eval(W4)
    if float(np.max(np.abs(chk['P15'] - e['P15']))) > 1e-12:
        raise SystemExit('上乗せを戻したあとの値が元と違う')
    h2 = dict(引いた上乗せ_Bの世界=round(100 * bx, 2),
              形ごと={k: dict(元_期待の年率=[r(100 * e['mean_pi'][j]), r(100 * e2['mean_pi'][j])], 元_P15π=[r(100 * e['P15'][j]), r(100 * e2['P15'][j])],
                          元_5パーセント未満=[r(100 * e['P5'][j]), r(100 * e2['P5'][j])],
                          基礎率_平均=[r(100 * b['mean_pi'][j]), r(100 * b2['mean_pi'][j])], 基礎率_P15=[r(100 * b['P15'][j]), r(100 * b2['P15'][j])],
                          基礎率_5パーセント未満=[r(100 * b['P5'][j]), r(100 * b2['P5'][j])]) for j, k in enumerate(F4)},
              読み方='各欄は［上乗せあり, 上乗せなし］')

    # ── H3 条件を足す ──
    Wn = W_of([NOWF])
    vN = {v: ve(Wn, v) for v in ve_names}
    f2 = np.ones(len(Aw), bool)
    for v in ve_names:
        x = ve(Aw, v)
        with np.errstate(invalid='ignore'):
            f2 &= (x['mean_pi'] >= vN[v]['mean_pi'][0] - EPS) & (x['P5'] <= vN[v]['P5'][0] + EPS)
    with np.errstate(invalid='ignore'):
        real = (Y[:, 9] >= yN[9] - EPS) & (Y[:, 10] >= yN[10] - EPS)
    core = base & g2 & g3

    def top_of(mask, n=5, check=True):
        od = order(mask)
        if check and od:
            fcheck(od[:n])
        return dict(通る形=len(od), 上位=[brief(i) for i in od[:n]])
    h3 = dict(G1からG3を通る形=int((core & meas).sum()), うちF2を通る形=int((core & f2 & meas).sum()), うち実績を今より下げない形=int((core & real & meas).sum()),
              全部を通る形=top_of(core & f2 & real), F2を外して実績を守る=top_of(core & real), 実績を外してF2を守る=top_of(core & f2))
    # 自己検問: F2 の一括の判定が fcheck の判定と一致（確かめた形だけ）
    bad = [names[i] for i in range(len(names)) if names[i] in FC and bool(f2[i]) != bool(FC[names[i]]['F2'])]
    if bad:
        raise SystemExit(f'F2 の一括の判定が fcheck と違う: {bad[:5]}')

    # ── H4 相棒の入れ替えの線 ──
    h4 = []
    idx = {n: i for i, n in enumerate(names)}
    for x in range(0, 30, 5):
        f = {k: v for k, v in {'QQQM': 25, 'SMH': 35, 'ITA': x, 'FBT': 15, 'VBR': 25 - x}.items() if v}
        i = idx[nm(f)]
        fcheck([i])
        fc = FC[names[i]]
        h4.append(dict(形=names[i], P15π=r(Y[i, 1] * 100, 2), 期待の年率=r(Y[i, 0] * 100, 2), 年5パーセント未満=r(-Y[i, 2] * 100, 2), 最大下落=r(Y[i, 3] * 100, 1),
                       基礎率の平均=r(Y[i, 5] * 100, 2), 基礎率の5パーセント未満=r(-Y[i, 6] * 100, 2), 百年の中央_V1=r(Y[i, 7], 3), 百年の中央_V0=r(YA['V0'][i, 7], 3),
                       実績の年率の中央=r(Y[i, 9] * 100, 2), 実績の年15パーセント以上の窓=r(Y[i, 10] * 100, 1), F1=fc['F1'], F2=fc['F2'], F3=fc['F3'],
                       実績を今より下げない=bool(real[i])))

    # ── H5 詳しい物差し（並びの1位・中ほど） ──
    U, UC, BC, N = c['U'], c['UC'], c['BC'], c['N']
    chains, ch_jpy, sim, pi = c['chains'], c['ch_jpy'], c['sim'], c['pi']
    conc_arr, look_whole, ymat, ydict, YJA, YSCALE, YSIGN, YDEC = c['conc_arr'], c['look_whole'], c['ymat'], c['ydict'], A15.YJA, A15.YSCALE, A15.YSIGN, A15.YDEC
    D5 = {'今の形（main）': NOWF, '並びの1位': TOP, '中ほど': MID}
    k5 = list(D5)
    W5 = W_of(D5.values())
    Y5, e5, b5, rz5, _ = ymat(W5)
    V5 = {v: ve(W5, v) for v in ve_names}
    assets = sorted({a for f in D5.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(dict(D5), rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(dict(D5), rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vt = N.variants(dict(D5), rows, chains, k4)[UC.W_CRASH]
    h5 = {}
    for j, k in enumerate(k5):
        t = tab[k]
        raw = t['_raw']
        if abs(float(e5['P15'][j]) - raw['P15']) > 1e-9 or abs(float(e5['mean_pi'][j]) - raw['mean_pi']) > 1e-9:
            raise SystemExit(f'Fast と measure が合わない: {k}')
        q, pr_ = UC.upside(sim, raw, pi)
        a, u, dd = conc_arr(W5[j:j + 1])
        lk, lo, hi = look_whole(D5[k])
        if lo is None or abs(a[0] - lo) > 0.051 or abs(dd[0] - lk['NVDA（資産全体）']) > 0.0051:
            raise SystemExit(f'線形の集中が lookthrough と合わない: {k} {a[0]} {lo}')
        y1, y0 = Y5['V1'][j], Y5['V1'][0]
        h5[k] = dict(
            形=nm(D5[k]), 全体の比=A15.whole(D5[k]), 物差し13={v: ydict(Y5[v][j]) for v in ('V0', 'V1')},
            今との差={YJA[i]: r((y1[i] - y0[i]) * YSCALE[i] * YSIGN[i], max(YDEC[i], 2) + 1) for i in range(13)},
            今を下回る物差し=[YJA[i] for i in range(13) if not (y1[i] >= y0[i] - EPS)],
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), 五パーセント未満=t['P5π（5%未満）'], 元本割れ=t['P0π（元本割れ）'],
                   最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'], 世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q),
            世界ごとの年率の今との差={w: round(t['世界ごとの年率'][w] - tab[k5[0]]['世界ごとの年率'][w], 2) for w in t['世界ごとの年率']},
            感度5本の今との差={N.VARS_JA[v]: round(100 * (vt[k][v]['mean_pi'] - vt[k5[0]][v]['mean_pi']), 3) for v in N.VARS},
            基礎率の感度6本の今との差={v: dict(平均=r(100 * (V5[v]['mean_pi'][j] - V5[v]['mean_pi'][0]), 3), 五パーセント未満=r(100 * (V5[v]['P5'][j] - V5[v]['P5'][0]), 2)) for v in ve_names},
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * b5['mean_pi'][j]), P15π=r(100 * b5['P15'][j]), 五パーセント未満=r(100 * b5['P5'][j])),
            実績=dict(年15パーセント以上の割合=r(100 * rz5['share'][j], 1), 年率の中央=r(100 * rz5['med'][j]), 最悪=r(100 * rz5['worst'][j])),
            集中=dict(半導体の連鎖_下限=round(float(a[0]), 2), 半導体の連鎖_上限=round(float(a[0] + u[0]), 2), NVDA=round(float(dd[0]), 2), lookthrough=lk.get('最大の1銘柄')))

    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/aim15_posthoc.py', kind='事後の診断（判定に使わない・aim15_check の答えは変えない）',
               H1_15パーセント以上の確率を3通りで=h1, H2_小型バリューの上乗せが消えたら=h2, H3_条件を足す=h3, H4_相棒の入れ替えの線=h4, H5_詳しい物差し=h5,
               secs=round(time.time() - t0, 1))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('書いた', OUT, f'{time.time() - t0:.0f}s')
    print(json.dumps(h1, ensure_ascii=False, indent=1))
    print(json.dumps(h2, ensure_ascii=False, indent=1))
    print(json.dumps({k: (v if not isinstance(v, dict) else dict(通る形=v['通る形'], 上位=[(x['名前'], x['物差し']['②年15%以上の確率'], x['物差し']['⑪実績の年15%以上の割合'],
                                                                                 (x.get('確かめ') or {}).get('F1'), (x.get('確かめ') or {}).get('F2'), (x.get('確かめ') or {}).get('F3'))
                                                                                for x in v['上位']])) for k, v in h3.items()}, ensure_ascii=False, indent=1))
    for x in h4:
        print(x)


if __name__ == '__main__':
    main()
