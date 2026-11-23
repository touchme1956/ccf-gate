#!/usr/bin/env python3
"""night/beat_ret_posthoc.py — beat_ret_check の事後の診断（判定に使わない・結果を見たあとに足した）

beat_ret_check（事前に固定した決まり）の答えは「R を13の物差しすべてで超える形は無い」だった。
ここでは、どの物差しが止めているかだけを数える（同じ6本の範囲＝A 芯あり 5,196通り・D1 芯なし 53,130通り）:
  ① 物差しを1つだけ外したら超える形が何通り出るか（13通り）と、実績の2つ（⑩⑪）・集中の2つ（⑫⑬）を組で外した場合
  ② それぞれの最良（選び方は beat_ret_check と同じ＝期待の年率 → P15π → 最大下落 → 名前）と、外した物差しでの R との差
  ③ D1 で「実績の2つを外すと超える形」の NASDAQ100 の比ごとの最良
  ④ ②③の最良の形に、beat_ret_check の最終の確かめ（F1 感度5本・F2 基礎率の感度6本・F3 円）を R と比べて当てる
物差し・R・評価の関数は beat_ret_check と同じもの（best15_check.Fast・best15r_check.FastBR・Cent・five_mix_ndx_check.realized・
lookthrough.explode の線形）を使い、R の13の値が out/beat_ret_check.json と一致することを確かめてから数える。
使い方: python3 night/beat_ret_posthoc.py → out/beat_ret_posthoc.json
"""
import contextlib, io, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'beat_ret_posthoc.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import beat_ret_check as T  # noqa: E402

SIX, RF, K, STEP = T.SIX, T.RF, T.K, T.STEP
EPS, GAIN, TIE = T.EPS, T.GAIN, T.TIE
YJA, YSIGN, YSCALE, YDEC = T.YJA, T.YSIGN, T.YSCALE, T.YDEC


def log(*a):
    print('[beat_ret_posthoc]', *a, file=sys.stderr, flush=True)


def main():
    t0 = time.time()
    import lookthrough as L
    import unx_assets as U
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = list(BR.POOL)
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    a0 = BR.adj_vector(vec, st, BR.RATES['主（20年の値）'], P)[0]
    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    sv, nv = np.zeros(6), np.zeros(6)
    for j, c in enumerate(SIX):
        look, unk = L.explode({c: 1e6}, prof)
        sv[j] = sum(v for t, v in look.items() if t in L.SEMI) / 1e6
        nv[j] = look.get('NVDA', 0.0) / 1e6
    _, seats, _ = U.castle_copy()
    seats = list(seats)
    per = T.CASTLE_PCT / len(seats)
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')
    ix = [P.index(c) for c in SIX]

    def ymat(G):
        A = np.zeros((len(G), len(P)))
        A[:, ix] = G
        Y = np.full((len(G), 13), np.nan)
        for s in range(0, len(G), 20000):
            W = A[s:s + 20000]
            e, b, c, z = fast.eval(W), fbr.eval(W, a0), cent.eval(W), realized(W, fast)
            sl = slice(s, s + 20000)
            Y[sl, 0], Y[sl, 1], Y[sl, 2], Y[sl, 3], Y[sl, 4] = e['mean_pi'], e['P15'], -e['P5'], e['mdd'], e['worst']
            Y[sl, 5], Y[sl, 6] = b['mean_pi'], -b['P5']
            Y[sl, 7], Y[sl, 8], Y[sl, 9], Y[sl, 10] = c['c30med'], c['c30min'], z['med'], e['past20']
            bad = ~(e['ok'] & b['ok'] & c['ok'])
            Y[sl][bad] = np.nan
        Wn = G * STEP
        Y[:, 11] = -(c_semi + K * (Wn @ sv))
        Y[:, 12] = -(c_nvda + K * (Wn @ nv))
        return Y

    GR = np.array([[RF.get(c, 0) // STEP for c in SIX]], dtype=np.int16)
    yR = ymat(GR)[0]
    ref = json.load(open(os.path.join(BASE, 'out', 'beat_ret_check.json')))['R']['物差し13']
    mine = {YJA[i]: T.r(yR[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}
    if mine != ref:
        raise SystemExit(f'R の物差しが beat_ret_check と違う: {mine} 対 {ref}')
    log('R の13の物差しが beat_ret_check と一致 ✓')

    def names(G, i):
        return T.nm({c: int(v) * STEP for c, v in zip(SIX, G[i]) if v})

    def okey(G, Y, i):
        return (-round(float(Y[i, 0]) / TIE), -float(Y[i, 1]), -float(Y[i, 3]), names(G, i))

    def row(G, Y, i):
        f = {c: int(v) * STEP for c, v in zip(SIX, G[i]) if v}
        return dict(名前=T.nm(f), 全体の比=T.whole(f),
                    物差し={YJA[k]: T.r(Y[i, k] * YSIGN[k] * YSCALE[k], YDEC[k]) for k in range(13)},
                    R_との差={YJA[k]: T.r((Y[i, k] - yR[k]) * YSCALE[k] * YSIGN[k], max(YDEC[k], 2) + 1) for k in range(13)},
                    下回る物差し=[YJA[k] for k in range(13) if not (Y[i, k] >= yR[k] - EPS)])

    def study(G, label):
        Y = ymat(G)
        with np.errstate(invalid='ignore'):
            ge = Y >= yR[None, :] - EPS
            gt = Y > yR[None, :] + GAIN
        valid = ~np.isnan(Y).any(axis=1)
        out = dict(形=int(len(G)), 測れた形=int(valid.sum()), 全部で超える=int((valid & ge.all(axis=1) & gt.any(axis=1)).sum()))
        drops = {YJA[k]: [k] for k in range(13)}
        drops['⑩⑪（実績の2つ）'] = [9, 10]
        drops['⑫⑬（集中の2つ）'] = [11, 12]
        drops['⑩⑪⑫⑬（実績と集中）'] = [9, 10, 11, 12]
        res_ = {}
        keep_real = None
        for nm_, ks in drops.items():
            cols = [k for k in range(13) if k not in ks]
            m = valid & ge[:, cols].all(axis=1) & gt[:, cols].any(axis=1)
            idx = sorted([int(i) for i in np.where(m)[0]], key=lambda i: okey(G, Y, i))
            res_[nm_] = dict(超える形の数=len(idx), 最良=(row(G, Y, idx[0]) if idx else None))
            if nm_ == '⑩⑪（実績の2つ）':
                keep_real = (m, idx)
        out['物差しを外したら'] = res_
        by = {}
        if keep_real:
            m, idx = keep_real
            for u in range(0, 21):
                sel = [i for i in idx if G[i, 0] == u]
                if sel:
                    by[f'NASDAQ100 {u * STEP}'] = dict(形の数=len(sel), 最良=row(G, Y, sel[0]))
        out['実績の2つを外したときのNASDAQ100の比ごとの最良'] = by
        # R より期待の年率が高く集中が増えない形が、どの物差しで落ちるか
        with np.errstate(invalid='ignore'):
            base = valid & (Y[:, 0] > yR[0] + GAIN) & ge[:, 11] & ge[:, 12]
        out['期待の年率がRより高く集中が増えない形'] = dict(
            数=int(base.sum()), 物差しごとに下回る形の数={YJA[k]: int((base & ~ge[:, k]).sum()) for k in range(13)})
        log(label, out['形'], '全部で超える', out['全部で超える'], {k: v['超える形の数'] for k, v in res_.items()})
        return out

    GA = T.grid_of(0, True)
    GD = T.grid_of(0, False)
    sa, sd = study(GA, 'A'), study(GD, 'D1')

    # ④ 対抗の形の確かめ（beat_ret_check の F1〜F3 と同じ・R と比べる）
    import upside_check as UC
    import bestpf_check as BC
    import ndx_swap_check as N
    cand = {}
    x = sd['物差しを外したら']['⑩実績の年率の中央']['最良']
    if x:
        cand['⑩だけを外した最良'] = x['名前']
    for k, v in sd['実績の2つを外したときのNASDAQ100の比ごとの最良'].items():
        cand[f'実績を外した最良・{k}'] = v['最良']['名前']
    x = sd['物差しを外したら']['⑫⑬（集中の2つ）']['最良']
    if x:
        cand['集中を外した最良'] = x['名前']
    inv = {v: k for k, v in T.JA.items()}

    def parse(name):
        f = {}
        for part in name.split(' / '):
            a, b = part.rsplit(' ', 1)
            f[inv.get(a, a)] = float(b)
        return f
    forms = {}
    for lab, name in cand.items():
        forms.setdefault(name, parse(name))
    Fm = {'R': RF, **forms}
    assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
    ch_jpy, _ = U.jpy_chains(chains)
    adj = {k: BR.adj_vector(vec, st, rt, P)[0] for k, rt in BR.RATES.items()}
    with contextlib.redirect_stdout(io.StringIO()):
        k4, _ = N.chips_adj(rows, assets)
        vt = N.variants(Fm, rows, chains, k4)[UC.W_CRASH]
        tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets), windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    Wf = np.array([[f.get(c, 0) for c in P] for f in Fm.values()], dtype=np.float64)
    vres = {'主': fbr.eval(Wf, a0), '10年の値': fbr.eval(Wf, adj['10年の値']),
            '1位の業種を強く': fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
            '主の半分': fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': fbr.eval(Wf, a0, nobonus=True),
            '共分散をA2の窓から': fbr.eval(Wf, a0, cov2=True)}
    chk = {}
    for j, name in enumerate(Fm):
        if name == 'R':
            continue
        d1 = {N.VARS_JA[v]: round(100 * (vt[name][v]['mean_pi'] - vt['R'][v]['mean_pi']), 3) for v in N.VARS}
        d2 = {v: dict(平均=round(100 * float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]), 3),
                      五パーセント未満=round(100 * float(vres[v]['P5'][j] - vres[v]['P5'][0]), 2)) for v in vres}
        dj = 100 * (tj[name]['_raw']['mean_pi'] - tj['R']['_raw']['mean_pi'])
        dm = 100 * (tj[name]['_raw']['mdd'] - tj['R']['_raw']['mdd'])
        chk[name] = dict(呼び名=[lab for lab, nm_ in cand.items() if nm_ == name],
                         F1=all(v >= 0 for v in d1.values()), 感度5本のRとの差=d1,
                         F2=all(x_['平均'] >= 0 and x_['五パーセント未満'] <= 0 for x_ in d2.values()), 基礎率の感度6本のRとの差=d2,
                         F3=bool(dj >= 0 and dm >= 0), 円のRとの差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2)),
                         世界ごとの年率のRとの差={w: round(100 * (tj[name]['_raw']['worlds'][w] - tj['R']['_raw']['worlds'][w]), 2) for w in tj['R']['_raw']['worlds']}
                         if 'worlds' in tj['R']['_raw'] else None)
    with contextlib.redirect_stdout(io.StringIO()):
        tu = U.measure(Fm, rows, chains, mega=U.mega_map(rows, assets))[UC.W_CRASH]
    for name in chk:
        chk[name]['世界ごとの年率_ドル'] = tu[name]['世界ごとの年率']
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/beat_ret_posthoc.py',
               kind='事後の診断（beat_ret_check の結果を見たあとに足した・判定に使わない）',
               R=dict(名前=T.nm(RF), 物差し13=mine, 世界ごとの年率_ドル=tu['R']['世界ごとの年率']),
               A_芯あり_同じ6本=sa, D1_芯なし_同じ6本=sd, 対抗の形の確かめ=chk,
               secs=None)
    out['secs'] = round(time.time() - t0)
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('→', OUT, f'{out["secs"]}s')


if __name__ == '__main__':
    main()
