#!/usr/bin/env python3
"""night/ndx_recon_posthoc.py — ndx_recon_check の事後の診断（2026-11-22・判定に使わない）

ndx_recon_check の結果（答え＝V1・縛りなし NASDAQ100 5 / SMH 40 / ITA 15 / FBT 20 / VBR 20・核ありは R だけ・13の物差しで R を超える形0本）を
見たあとで足した読み解き。★結果を見たあとの追加なので、登録した決まりの答えは変えない。
  P1 1本ずつ（6本と S&P500）の13の物差し（⑧⑨は V0 と V1）＝NASDAQ100 を抑えているのはどの物差しか
  P2 NASDAQ100 の下限つき（ETF 側の20・25・30・35%以上）で、登録した選び方（条件6つ・4つの目標・F1〜F3）をそのまま当てた答え（V1）
     下限の理由: 自動の積立（iDeCo・こどもNISA）が NASDAQ100 を買う＝入金に占める割合より下へは、売らない限り長い目でも下がらない
  P3 期待の年率の条件①を外した1位（V1・縛りなし／核あり）の F1〜F3（参考）と13の物差し
  P4 前の最良（NASDAQ100 10 / SMH 40 / ITA 25 / FBT 25）と R の勝ち負けの数（V0 と V1）
  P5 実行の算数: portfolio.json の入金の計画から、自動の積立が NASDAQ100 に入れる割合（資産全体・ETF 側）
使い方: python3 night/ndx_recon_posthoc.py → out/ndx_recon_posthoc.json（約1分）
"""
import contextlib, io, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx_recon_posthoc.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import beat_ret_check as BT  # noqa: E402
import ndx_recon_check as NR  # noqa: E402

SIX, RF, NOWF = NR.SIX, NR.RF, NR.NOWF
STEP, K, CASTLE_PCT = NR.STEP, NR.K, NR.CASTLE_PCT
EPS, TIE = NR.EPS, NR.TIE
YJA, YSIGN, YSCALE, YDEC = NR.YJA, NR.YSIGN, NR.YSCALE, NR.YDEC
COND, DEF5, GOALS, GJA = NR.COND, NR.DEF5, NR.GOALS, NR.GJA
nm, whole, r = NR.nm, NR.whole, NR.r
FLOORS = [20, 25, 30, 35]


def log(*a):
    print('[ndx_recon_post]', *a, file=sys.stderr, flush=True)


def main():
    t0 = time.time()
    import lookthrough as L
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import ndx_swap_check as N
    main_js = json.load(open(os.path.join(BASE, 'out', 'ndx_recon_check.json')))
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = list(BR.POOL)
    C = B.century_extend(U)
    fast = B.Fast(U, rows, chains, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    adj = {k: BR.adj_vector(vec, st, rt, P)[0] for k, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    qs, _ = NR.build_copies(C)
    cts = {v: BCc.CentP(U, P, {**C['parts'], 'QQQM': qs[v]}) for v in ('V0', 'V1')}

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    sh = {}
    for c in SIX:
        look, unk = L.explode({c: 1e6}, prof)
        sh[c] = (sum(v for t, v in look.items() if t in L.SEMI) / 1e6, look.get('NVDA', 0.0) / 1e6)
    import sp500_compare as SPC
    sh['VOO'] = (sum(SPC.VOO_SEMI.values()) / 100, SPC.VOO_SEMI['NVDA'] / 100)
    sv = np.array([sh[c][0] if c in sh else np.nan for c in P])
    nv = np.array([sh[c][1] if c in sh else np.nan for c in P])
    _, seats, _ = U.castle_copy()
    seats = list(seats)
    per = CASTLE_PCT / len(seats)
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')

    def ymat(A, v):
        Y = np.full((len(A), 13), np.nan)
        e, b = fast.eval(A), fbr.eval(A, a0)
        Y[:, 0], Y[:, 1], Y[:, 2], Y[:, 3], Y[:, 4], Y[:, 10] = e['mean_pi'], e['P15'], -e['P5'], e['mdd'], e['worst'], e['past20']
        Y[:, 5], Y[:, 6] = b['mean_pi'], -b['P5']
        Wn = 100 * A / A.sum(axis=1, keepdims=True)
        used = Wn > 0
        with np.errstate(invalid='ignore'):
            Y[:, 11] = -(c_semi + K * np.where(used, Wn * sv[None, :], 0.0).sum(axis=1))
            Y[:, 12] = -(c_nvda + K * np.where(used, Wn * nv[None, :], 0.0).sum(axis=1))
        Y[:, 9] = realized(A, fast)['med']
        cc = BCc.cent_chunked(cts[v], A)
        Y[:, 7], Y[:, 8] = np.where(cc['ok'], cc['c30med'], np.nan), np.where(cc['ok'], cc['c30min'], np.nan)
        Y[~(e['ok'] & b['ok'])] = np.nan
        return Y

    def ydict(y):
        return {YJA[i]: r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}

    # 自己検問: R の13の物差し（V0・V1）が ndx_recon_check.json と一致
    yR = {v: ymat(W_of([RF]), v)[0] for v in ('V0', 'V1')}
    for v in ('V0', 'V1'):
        if ydict(yR[v]) != main_js['R']['物差し13'][v]:
            raise SystemExit(f'R の物差しが ndx_recon_check.json と違う（{v}）: {ydict(yR[v])}')
    log('自己検問 ✓')

    # ── P1 1本ずつ ──
    singles = {}
    for c in SIX + ['VOO']:
        W = W_of([{c: 1}])
        singles[BT.JA.get(c, c) if c != 'VOO' else 'S&P500（VOO）'] = dict(
            V1=ydict(ymat(W, 'V1')[0]), 百年_V0=dict(三十年の中央=r(ymat(W, 'V0')[0, 7], 3), 三十年の最悪=r(ymat(W, 'V0')[0, 8], 3)))

    # ── 6本の形（V1） ──
    G0 = BT.grid_of(0, False)
    A0 = np.zeros((len(G0), len(P)), dtype=np.float64)
    A0[:, [P.index(c) for c in SIX]] = G0
    forms = [{c: int(x) * STEP for c, x in zip(SIX, row) if x} for row in G0]
    names = [nm(f) for f in forms]
    Y = ymat(A0, 'V1')
    y1 = yR['V1']
    core = (G0[:, 0] >= NR.NDX_LO) & (G0[:, 0] <= NR.NDX_HI) & (G0[:, 1:] <= G0[:, [0]]).all(axis=1)
    log('6本の形', len(G0), f'{time.time() - t0:.0f}s')

    def select(mask, cond):
        with np.errstate(invalid='ignore'):
            ok = ~np.isnan(Y).any(axis=1) & (Y[:, cond] >= y1[cond][None, :] - EPS).all(axis=1) & mask
        idx = np.where(ok)[0]
        if not len(idx):
            return None
        best, worst = Y[idx][:, GOALS].max(axis=0), Y[idx][:, GOALS].min(axis=0)
        span = np.where(best - worst > EPS, best - worst, np.inf)
        with np.errstate(invalid='ignore'):
            RG = (best[None, :] - Y[:, GOALS]) / span[None, :]
        mx, sm = RG.max(axis=1), RG.sum(axis=1)
        order = sorted([int(i) for i in idx], key=lambda i: (round(float(mx[i]), NR.SDEC), round(float(sm[i]), 9), -round(float(Y[i, 0]) / TIE),
                                                             -float(Y[i, 3]), names[i]))
        return dict(idx=idx, RG=RG, mx=mx, order=order, best=best, worst=worst)

    def brief(i, S=None):
        y = Y[i]
        out = dict(名前=names[i], 形=forms[i], 全体の比=whole(forms[i]), 物差し=ydict(y),
                   R_との差={YJA[k]: r((y[k] - y1[k]) * YSCALE[k] * YSIGN[k], max(YDEC[k], 2) + 1) for k in range(13)},
                   R_を下回る物差し=[YJA[k] for k in range(13) if not (y[k] >= y1[k] - EPS)],
                   R_を上回る物差し=[YJA[k] for k in range(13) if y[k] > y1[k] + NR.GAIN])
        if S is not None:
            out.update(取り逃がしの最大=round(float(S['mx'][i]), 4), 取り逃がし={GJA[g]: round(float(S['RG'][i, j]), 3) for j, g in enumerate(GOALS)})
        return out

    ve_names = list(BR.VARS)

    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    ch_jpy, _ = U.jpy_chains(chains)
    FC = {}

    def fcheck(fl):
        todo = [f for f in fl if nm(f) not in FC]
        for s in range(0, len(todo), 10):
            part = todo[s:s + 10]
            Fm = {NR.K_R: RF, **{'@' + nm(f): f for f in part}}
            assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
            with contextlib.redirect_stdout(io.StringIO()):
                k4, _ = N.chips_adj(rows, assets)
                vt = N.variants(Fm, rows, chains, k4)[UC.W_CRASH]
                tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets), windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
            Wf = W_of(Fm.values())
            vres = {v: ve(Wf, v) for v in ve_names}
            for j, f in enumerate(part, start=1):
                k = '@' + nm(f)
                d1 = {N.VARS_JA[v]: round(100 * (vt[k][v]['mean_pi'] - vt[NR.K_R][v]['mean_pi']), 3) for v in N.VARS}
                f1 = all(vt[k][v]['mean_pi'] >= vt[NR.K_R][v]['mean_pi'] - EPS for v in N.VARS)
                d2 = {v: dict(平均=round(100 * float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]), 3),
                              五パーセント未満=round(100 * float(vres[v]['P5'][j] - vres[v]['P5'][0]), 2)) for v in ve_names}
                f2 = all(vres[v]['mean_pi'][j] >= vres[v]['mean_pi'][0] - EPS and vres[v]['P5'][j] <= vres[v]['P5'][0] + EPS for v in ve_names)
                dj = 100 * (tj[k]['_raw']['mean_pi'] - tj[NR.K_R]['_raw']['mean_pi'])
                dm = 100 * (tj[k]['_raw']['mdd'] - tj[NR.K_R]['_raw']['mdd'])
                f3 = bool(dj >= -1e-10 and dm >= -1e-10)
                FC[nm(f)] = dict(F1=bool(f1), F2=bool(f2), F3=f3, 合否=bool(f1 and f2 and f3), 感度5本のRとの差=d1, 基礎率の感度6本のRとの差=d2,
                                 円のRとの差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2)),
                                 円=dict(期待の年率=round(100 * tj[k]['_raw']['mean_pi'], 2), 最大下落=round(100 * tj[k]['_raw']['mdd'], 1)))

    # ── P2 NASDAQ100 の下限つき（登録した選び方） ──
    S_all = select(np.ones(len(G0), bool), COND)
    floors = {}
    for fl in FLOORS:
        S = select(G0[:, 0] * STEP >= fl, COND)
        if S is None:
            floors[f'NASDAQ100 {fl}%以上'] = dict(条件を通った形=0)
            continue
        top = S['order'][:NR.NFIN]
        ans, seen = None, []
        for s in range(0, len(top), 10):
            part = top[s:s + 10]
            fcheck([forms[i] for i in part])
            for i in part:
                fc = FC[names[i]]
                seen.append(dict(名前=names[i], 取り逃がしの最大=round(float(S['mx'][i]), 4), F1=fc['F1'], F2=fc['F2'], F3=fc['F3'], 合否=fc['合否']))
                if fc['合否'] and ans is None:
                    ans = i
            if ans is not None:
                break
        first = S['order'][0]
        floors[f'NASDAQ100 {fl}%以上'] = dict(
            条件を通った形=int(len(S['idx'])),
            選び方の1位=dict(**brief(first, S), 確かめ=FC[names[first]], 縛りなしの範囲で測った取り逃がしの最大=round(float(S_all['mx'][first]), 4)),
            答え=(dict(**brief(ans, S), 確かめ=FC[names[ans]], 縛りなしの範囲で測った取り逃がしの最大=round(float(S_all['mx'][ans]), 4))
                 if ans is not None else '確かめを通る形は無い'),
            上位5=[dict(名前=names[i], 取り逃がしの最大=round(float(S['mx'][i]), 4), 物差し=ydict(Y[i])) for i in S['order'][:5]], 最終の確かめ=seen)
        log(fl, '以上', floors[f'NASDAQ100 {fl}%以上']['選び方の1位']['名前'], '答え',
            (names[ans] if ans is not None else None), f'{time.time() - t0:.0f}s')

    # ── P3 条件①を外した1位（V1） ──
    no1 = {}
    for lab, mask in (('縛りなし', np.ones(len(G0), bool)), ('核あり', core)):
        S = select(mask, DEF5)
        top = S['order'][:3]
        fcheck([forms[i] for i in top])
        no1[lab] = dict(条件を通った形=int(len(S['idx'])), 上位3=[dict(**brief(i, S), 確かめ=FC[names[i]]) for i in top])

    # ── P4 前の最良と R の勝ち負け ──
    OLD = NR.OLDF
    p4 = {}
    for v in ('V0', 'V1'):
        yo, yr_ = ymat(W_of([OLD]), v)[0], yR[v]
        p4[v] = dict(前の最良=ydict(yo), R=ydict(yr_), 前の最良が上=[YJA[k] for k in range(13) if yo[k] > yr_[k] + NR.GAIN],
                     R_が上=[YJA[k] for k in range(13) if yr_[k] > yo[k] + NR.GAIN])

    # ── P5 実行の算数 ──
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    total = float((tg.get('nisa') or {}).get('monthly_total_jpy') or 0)
    ide = sum(float(m.get('jpy') or 0) for m in ((tg.get('ideco') or {}).get('members') or []))
    kod = sum(float(m.get('jpy') or 0) for m in ((tg.get('kodomo_nisa') or {}).get('members') or []))
    auto = ide + kod
    p5 = dict(入金の計画_月=total, iDeCo_月=ide, こどもNISA_月=kod, 自動でNASDAQ100に入る割合=(round(100 * auto / total, 1) if total else None),
              ETF側に直した割合=(round(100 * auto / total / K, 1) if total else None),
              iDeCoの本=(tg.get('ideco') or {}).get('fund'), こどもNISAの本=(tg.get('kodomo_nisa') or {}).get('fund'),
              読み方='売らない限り、資産全体に占める NASDAQ100 の比は長い目でこの割合より下がらない（今の保有が目標より多い間は、目標が低いほど下がるのに年数がかかる）')

    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/ndx_recon_posthoc.py', kind='事後の診断（結果を見たあとの追加・登録した決まりの答えは変えない）',
               P1_1本ずつ=singles, P2_NASDAQ100の下限つき=floors, P3_期待の年率の条件を外した1位=no1, P4_前の最良とRの勝ち負け=p4, P5_実行の算数=p5,
               secs=round(time.time() - t0, 1))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('書いた', OUT, f'{time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
