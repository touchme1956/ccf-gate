#!/usr/bin/env python3
"""night/five_mix_ndx_check.py — NASDAQ100 を芯にして5本で組み直す（five_mix の続き・2026-11-01・参考・配分は変えない）

ユーザー「待って歴史検証でNASDAQ100が最も良かったETFなのになぜそれがベースにならない？」
five_mix（night/five_mix_check.py・1aa75206）の答え NASDAQ100 5 / SMH 25 / ITA 25 / XLV 5 / VBR 40 は、3つの目標
（元の物差しの P15π・業種の基礎率の物差しの平均・100年の代用）の取り逃がしで選んだ。どれにも「実際の積立の実績」が入っていない。
この道具は、どの物差しで NASDAQ100 が負けたかを1本ずつ並べ、実績を目標に足して NASDAQ100 を芯にした形で組み直す。
門・採点・配分（portfolio.json）・注文書には触れない。
★測るもの・形・条件・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする
  （five_mix の答えと比ごとの最良の数字は見たあと＝この道具の選び方はそれを知った上で決めた）。

① 1本ずつ（5本それぞれ100%・参考のS&P500〔VOO〕も）: 元の物差し（P15π・平均・5%未満・最大下落・世界 A1/A2/B/C/D）／
   基礎率の物差し（P15π・平均・5%未満）／100年の代用（30年の積立の比 中央・最悪）／
   実績（2000-09〜2026-09 の20年の毎月の積立〔元の物差しの A1 と同じ系列・費用込み・ドル〕: 年15%以上の割合・年率の中央・最悪）
② 100年の写しの感度（参考・選び方に使わない）: NASDAQ100 の写しの 1985-11 以降を本物（^NDX の価格＋配当の置き値 → QQQ・
   bestfund_data.build_chain('NDX')・費用の前）につないだ場合の30年の積立の比（1985-10 までは今と同じ French のテック3業種65%＋市場35%）
③ 組み直し
   形: 5本すべて5%以上・5%刻み・合計100%・NASDAQ100 が最大の1本（他のどの本以上）∧ 30%以上60%以下＝「芯」
   守りの条件: five_mix と同じ4つ（基礎率の物差しの5%未満 ≤ 今・最大下落 ≥ 今・100年の代用の30年の最悪 ≥ 今・
     勝ち業種の中身の比重の合計 ≤ 今）
   目標（4つ）: five_mix の g1〜g3 ＋ g4＝実績の20年の毎月の積立の年率の中央（上の①と同じ）
   選び方: five_mix と同じ＝条件を通った芯の形の中で目標ごとに 取り逃がし＝(最良−その形)÷(最良−最悪)・4つの最大を最小に。
     小数3桁に丸めて同じなら 取り逃がしの合計 → g4 → g1 → 最大下落が浅い → 名前の順
   最終の確かめ: five_mix と同じ F1（基礎率の感度6本すべてで 平均 ≥ 今 ∧ 5%未満 ≤ 今）・F2（円の最大下落 ≥ 今）・
     F3（小型バリューの上乗せなし S2 で基礎率の5%未満 ≤ 今）。上位30を順に・最初に通った形を答えに
   併せて出す（判定に使わない）: 同じ芯の形の中で g4 を入れない3つの目標の答え（＝芯の縛りだけの効果）／NASDAQ100 の比ごとの最良
     （4つの目標）／答えと参考（今・five_mix の答え・5本を等分・NASDAQ100 50/VBR 50・NASDAQ100 だけ）の詳しい物差し
⚠ 限界: 実績は 2000-09〜2026-09 の一つの時代（窓の終わりは全部 2020〜2026・重なる窓は独立でない）・目標を4つ等しく扱うのは私が決めた・
  芯の縛り（30〜60%・最大の1本）も私が決めた・100年の写しの感度は本物の NASDAQ100 が勝った時代を写しに足す（後知恵の向きがある）・
  税・NISA の枠は物差しに入らない
使い方: python3 night/five_mix_ndx_check.py → out/five_mix_ndx_check.json
"""
import contextlib, io, itertools, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'five_mix_ndx_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_check import FIVE, JA, name5, r  # noqa: E402

UNITS, STEP = 20, 5
NDX_LO, NDX_HI = 6, 12                       # 30〜60%
SDEC, NFIN, EPS, TW = 3, 30, 1e-12, 240
GOALS = ['g1', 'g2', 'g3', 'g4']
GOAL_JA = {'g1': '元の物差しの P15π', 'g2': '基礎率の物差しの平均', 'g3': '100年の代用の30年の中央',
           'g4': '実績の20年の積立の年率の中央（2000-09〜）'}
SINGLE = ['QQQM', 'SMH', 'ITA', 'XLV', 'VBR', 'VOO']
REFS = {'今': dict(B.NOW),
        'five_mix の答え': {'QQQM': 5, 'SMH': 25, 'ITA': 25, 'XLV': 5, 'VBR': 40},
        '5本を等分': {c: 20 for c in FIVE},
        'NASDAQ100 50/VBR 50': {'QQQM': 50, 'VBR': 50},
        'NASDAQ100 だけ': {'QQQM': 100}}


def log(*a):
    print('[five_mix_ndx]', *a, flush=True)


def forms_core():
    out = []
    for v in itertools.product(range(1, NDX_HI + 1), repeat=len(FIVE)):
        if sum(v) != UNITS:
            continue
        n = v[FIVE.index('QQQM')]
        if n < NDX_LO or n > NDX_HI or any(x > n for x in v):
            continue
        out.append(v)
    return np.array(out, dtype=np.int8)


def realized(W, fast, tau=0.15):
    """実績の転がる20年の毎月の積立（etf_p15.hist_success と同じ式）→ 年15%以上の割合・年率の中央・最悪"""
    Wn = W / W.sum(axis=1, keepdims=True)
    rr = Wn @ fast.G1 + (Wn @ fast.adj)[:, None] / 12.0
    Lc = np.cumsum(np.log1p(rr), axis=1)
    prev = np.hstack([np.zeros((len(Wn), 1)), Lc[:, :-1]])
    Pp0 = np.hstack([np.zeros((len(Wn), 1)), np.cumsum(np.exp(-prev), axis=1)])
    nwin = fast.T1 - TW + 1
    a = np.arange(nwin); b = a + TW - 1
    Wend = np.exp(Lc[:, b]) * (Pp0[:, b + 1] - Pp0[:, a])
    k = np.arange(1, TW + 1) / 12.0
    K15 = float(np.sum((1 + tau) ** k))

    def irr(v):
        lo, hi = np.full(v.shape, -0.6), np.full(v.shape, 1.5)
        for _ in range(80):
            mid = (lo + hi) / 2
            f = ((1 + mid)[..., None] ** k).sum(axis=-1)
            lo, hi = np.where(f < v, mid, lo), np.where(f < v, hi, mid)
        return (lo + hi) / 2
    return dict(share=(Wend >= K15).mean(axis=1), med=irr(np.median(Wend, axis=1)), worst=irr(Wend.min(axis=1)), nwin=int(nwin))


def main():
    t0 = time.time()
    B.check_now()
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import etf_forward_combo as CB
    import ndx_swap_check as N
    import bestfund_data as D
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = BR.POOL
    for c in set(FIVE) | {'VOO'}:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
    C = B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, vchk = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']

    # ── 100年の写しの感度: NASDAQ100 の 1985-11 以降を本物へ ──
    ndx, ndx_segs, _ = D.build_chain('NDX')
    parts_alt = dict(C['parts'])
    q = dict(C['parts']['QQQM'])
    for m in list(q):
        if m >= 198511:
            if m not in ndx:
                raise SystemExit(f'本物の NASDAQ100 に {m} が無い')
            q[m] = ndx[m]
    parts_alt['QQQM'] = q
    cent_alt = BCc.CentP(U, P, parts_alt)
    cent_chk = BCc.CentP(U, P, dict(C['parts']))

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    # ── 自己検問 ──
    rng = np.random.default_rng(3)
    Wr = rng.integers(0, 9, size=(40, len(P))).astype(np.float64)
    Wr[Wr.sum(axis=1) == 0, 0] = 1
    er = fast.eval(Wr)
    rz = realized(Wr, fast)
    d_share = float(np.max(np.abs(rz['share'] - er['past20'])))
    c1, c2 = cent.eval(Wr), cent_chk.eval(Wr)
    with np.errstate(invalid='ignore'):
        d_cent = float(np.nanmax(np.abs(c1['c30med'] - c2['c30med'])))
    sc = dict(実績の年15パーセント以上の割合が_Fast_の_past20_と一致=d_share, 写しを替えないCentPがCentと一致=d_cent,
              中身の業種が_rows_と一致={c: bool(vchk[c]) for c in FIVE if c in vchk})
    sc['一致'] = bool(d_share < 1e-12 and d_cent < 1e-12 and all(sc['中身の業種が_rows_と一致'].values()))
    log('自己検問', json.dumps(sc, ensure_ascii=False))
    if not sc['一致']:
        raise SystemExit('自己検問が通らない')

    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/five_mix_ndx_check.py', kind='参考（配分は変えない・測るもの・形・選び方は道具の頭に固定）',
               question='歴史検証で NASDAQ100 が最も良かったのに、なぜ five_mix でベースにならないか／NASDAQ100 を芯にして組み直す',
               selfcheck=sc, 本物のNASDAQ100のつなぎ=ndx_segs)

    # ── ① 1本ずつ ──
    Ws = W_of([{c: 100} for c in SINGLE])
    es, bs, cs, cas, rs = fast.eval(Ws), fbr.eval(Ws, a0), cent.eval(Ws), cent_alt.eval(Ws), realized(Ws, fast)
    with contextlib.redirect_stdout(io.StringIO()):
        tab1 = U.measure({c: {c: 100} for c in SINGLE}, rows, chains, mega=U.mega_map(rows, sorted(set(SINGLE))),
                         windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    one = {}
    for j, c in enumerate(SINGLE):
        o = tab1[c]
        one[JA.get(c, 'S&P500' if c == 'VOO' else c)] = dict(
            元の物差し=dict(P15π=r(es['P15'][j]), 平均=r(es['mean_pi'][j]), 五パーセント未満=r(es['P5'][j]), 最大下落=r(es['mdd'][j], 1),
                         ぶれ=r(es['vol'][j], 1), 世界=o['世界ごとの年率']),
            基礎率の物差し=dict(P15π=r(bs['P15'][j]), 平均=r(bs['mean_pi'][j]), 五パーセント未満=r(bs['P5'][j]),
                            世界=dict(B=r(bs['B'][j]), C=r(bs['C'][j]), D=r(bs['D'][j]))),
            百年=dict(三十年の中央=round(float(cs['c30med'][j]), 3), 三十年の最悪=round(float(cs['c30min'][j]), 3),
                    感度_1985年11月から本物のNASDAQ100=dict(三十年の中央=round(float(cas['c30med'][j]), 3), 三十年の最悪=round(float(cas['c30min'][j]), 3))),
            実績=dict(年15パーセント以上の割合=r(rs['share'][j], 1), 年率の中央=r(rs['med'][j]), 最悪=r(rs['worst'][j]), 窓=rs['nwin']))
        log('1本', c, json.dumps(one[JA.get(c, 'S&P500' if c == 'VOO' else c)], ensure_ascii=False)[:400])
    out['①1本ずつ'] = one

    # ── ③ 組み直し ──
    F5 = forms_core()
    ix = [P.index(c) for c in FIVE]
    A = np.zeros((len(F5), len(P)), dtype=np.float64)
    A[:, ix] = F5
    names = [name5({c: int(v) * STEP for c, v in zip(FIVE, row)}) for row in F5]
    W0 = W_of([B.NOW])
    e, b, c, rz = fast.eval(A), fbr.eval(A, a0), cent.eval(A), realized(A, fast)
    e0, b0, c0, rz0 = fast.eval(W0), fbr.eval(W0, a0), cent.eval(W0), realized(W0, fast)
    An = A / A.sum(axis=1, keepdims=True)
    winsum = (An @ IND).sum(axis=1)
    now = dict(g1=float(e0['P15'][0]), g2=float(b0['mean_pi'][0]), g3=float(c0['c30med'][0]), g4=float(rz0['med'][0]),
               P5b=float(b0['P5'][0]), mdd=float(e0['mdd'][0]), c30min=float(c0['c30min'][0]), win=float(((W0 / W0.sum()) @ IND).sum()))
    G = dict(g1=e['P15'], g2=b['mean_pi'], g3=c['c30med'], g4=rz['med'])
    okall = e['ok'] & b['ok'] & c['ok']
    with np.errstate(invalid='ignore'):
        gate = {'①基礎率の5%未満': b['P5'] <= now['P5b'] + EPS, '②最大下落': e['mdd'] >= now['mdd'] - EPS,
                '③100年の最悪': c['c30min'] >= now['c30min'] - EPS, '④勝ち業種の中身の比重の合計': winsum <= now['win'] + 1e-9}
    feas = okall.copy()
    for v in gate.values():
        feas &= v
    ii = np.where(feas)[0]
    log('芯の形', len(A), '測れた', int(okall.sum()), '条件ごと', {k: int((v & okall).sum()) for k, v in gate.items()}, '全部通った', len(ii))
    out.update(芯の形の数=len(A), 守りの条件を全部通った形=int(len(ii)),
               今=dict(形=dict(B.NOW), **{GOAL_JA[g]: (round(now[g], 3) if g == 'g3' else r(now[g])) for g in GOALS}))
    if not len(ii):
        out['答え'] = None
        json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        log('条件を通った芯の形が無い')
        return

    def regrets(goals):
        best = {g: float(np.max(G[g][ii])) for g in goals}
        worst = {g: float(np.min(G[g][ii])) for g in goals}
        reg = {g: (best[g] - G[g]) / (best[g] - worst[g]) if best[g] - worst[g] > EPS else np.zeros(len(A)) for g in goals}
        return best, worst, reg, np.maximum.reduce([reg[g] for g in goals]), sum(reg[g] for g in goals)

    best, worst, reg, R, Rs = regrets(GOALS)
    _, _, reg3, R3, Rs3 = regrets(['g1', 'g2', 'g3'])

    def order(idx, R_, Rs_):
        return sorted(list(idx), key=lambda i: (round(float(R_[i]), SDEC), round(float(Rs_[i]), 9), -float(G['g4'][i]),
                                                -float(G['g1'][i]), -float(e['mdd'][i]), names[i]))

    def brief(i, reg_=reg, R_=R):
        return dict(名前=names[i], 形={x: int(F5[i][j]) * STEP for j, x in enumerate(FIVE)},
                    取り逃がしの最大=round(float(R_[i]), 4), 取り逃がし={g: round(float(reg_[g][i]), 3) for g in reg_},
                    元のP15π=r(e['P15'][i]), 元の平均=r(e['mean_pi'][i]), 元の5パーセント未満=r(e['P5'][i]),
                    基礎率の平均=r(b['mean_pi'][i]), 基礎率の5パーセント未満=r(b['P5'][i]), 最大下落=r(e['mdd'][i], 1),
                    百年の中央=round(float(c['c30med'][i]), 3), 百年の最悪=round(float(c['c30min'][i]), 3),
                    実績の年率の中央=r(rz['med'][i]), 実績の年15パーセント以上の割合=r(rz['share'][i], 1), 実績の最悪=r(rz['worst'][i]),
                    勝ち業種の中身の比重の合計=r(winsum[i], 1))

    # 最終の確かめ（five_mix と同じ）
    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    ch_jpy, _ = U.jpy_chains(chains)
    Gj = np.array([[ch_jpy[x][m] for m in U.R.months(*BC.WINDOWS[UC.W_CRASH])] for x in P])
    _, _, mdd_j0 = CB.path_stats((W0 / W0.sum()) @ Gj, Gj.shape[1])
    iv, ivoo = P.index('VBR'), P.index('VOO')

    def s2(Wf):
        gB0, gC0, gD0 = fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy()
        try:
            fbr.gB[iv] -= 0.5 * float(rows['VBR']['B_X'])
            fbr.gC[iv], fbr.gD[iv] = fbr.gC[ivoo], fbr.gD[ivoo]
            return fbr.eval(Wf, a0)
        finally:
            fbr.gB, fbr.gC, fbr.gD = gB0, gC0, gD0
    S0 = s2(W0)

    def checks(idx, reg_=reg, R_=R):
        Wt = A[idx]
        vres = {v: (ve(Wt, v), ve(W0, v)) for v in BR.VARS}
        _, _, mdd_j = CB.path_stats((Wt / Wt.sum(axis=1, keepdims=True)) @ Gj, Gj.shape[1])
        Ss = s2(Wt)
        rows_out = []
        for j, i in enumerate(idx):
            ok1 = all(vres[v][0]['mean_pi'][j] >= vres[v][1]['mean_pi'][0] - EPS and vres[v][0]['P5'][j] <= vres[v][1]['P5'][0] + EPS for v in BR.VARS)
            ok2 = bool(mdd_j[j] >= mdd_j0[0] - EPS)
            ok3 = bool(Ss['P5'][j] <= S0['P5'][0] + EPS)
            rows_out.append(dict(**brief(i, reg_, R_), F1=bool(ok1), F2円の最大下落=ok2, F3小型バリューの上乗せなしの5パーセント未満=ok3,
                                 合否=bool(ok1 and ok2 and ok3), 円の最大下落=r(mdd_j[j], 1),
                                 感度ごとの今との差={v: dict(平均=r(vres[v][0]['mean_pi'][j] - vres[v][1]['mean_pi'][0], 3),
                                                         五パーセント未満=r(vres[v][0]['P5'][j] - vres[v][1]['P5'][0]),
                                                         P15=r(vres[v][0]['P15'][j] - vres[v][1]['P15'][0])) for v in BR.VARS},
                                 小型バリューの上乗せなし_S2=dict(P15π=r(Ss['P15'][j]), 平均=r(Ss['mean_pi'][j]), 五パーセント未満=r(Ss['P5'][j]),
                                                          今との差_平均=r(Ss['mean_pi'][j] - S0['mean_pi'][0], 3),
                                                          今との差_五パーセント未満=r(Ss['P5'][j] - S0['P5'][0]))))
        return rows_out

    top = order(ii, R, Rs)[:NFIN]
    finals = checks(top)
    ans = next((x for x in finals if x['合否']), None)
    top3 = order(ii, R3, Rs3)[:NFIN]
    finals3 = checks(top3, reg3, R3)
    ans3 = next((x for x in finals3 if x['合否']), None)
    log('答え（4つの目標）', ans['名前'] if ans else None, '／参考 3つの目標', ans3['名前'] if ans3 else None)
    out.update(最良と最悪={GOAL_JA[g]: dict(最良=(round(best[g], 3) if g == 'g3' else r(best[g])),
                                        最悪=(round(worst[g], 3) if g == 'g3' else r(worst[g]))) for g in GOALS},
               最終の確かめ=finals, 答え=ans, 参考_実績を入れない3つの目標の答え=ans3, 今の円の最大下落=r(mdd_j0[0], 1))
    fr = []
    jn = FIVE.index('QQQM')
    for u in range(NDX_LO, NDX_HI + 1):
        sel = ii[F5[ii, jn] == u]
        if not len(sel):
            fr.append(dict(比=u * STEP, 守りの条件を通った形=0))
            continue
        fr.append(dict(比=u * STEP, 守りの条件を通った形=int(len(sel)), **checks([order(sel, R, Rs)[0]])[0]))
    out['NASDAQ100の比ごとの最良'] = fr

    # ── 答えと参考の詳しい物差し ──
    show = dict(REFS)
    if ans:
        show = {'答え（芯・4つの目標）': dict(ans['形']), **show}
    if ans3 and (not ans or ans3['名前'] != ans['名前']):
        show['参考 芯・3つの目標'] = dict(ans3['形'])
    Wd = W_of(show.values())
    ed, bd, cd, cad, rd = fast.eval(Wd), fbr.eval(Wd, a0), cent.eval(Wd), cent_alt.eval(Wd), realized(Wd, fast)
    Vd = {v: ve(Wd, v) for v in BR.VARS}
    Sd = s2(Wd)
    Wdn = Wd / Wd.sum(axis=1, keepdims=True)
    assets = sorted({a for f in show.values() for a in f} | {'VOO'})
    with contextlib.redirect_stdout(io.StringIO()):
        mega = U.mega_map(rows, assets)
        tab0 = U.measure(show, rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(show, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vt = N.variants(show, rows, chains, k4)[UC.W_CRASH]
    j0 = list(show).index('今')
    det = {}
    for j, (nm, f) in enumerate(show.items()):
        o = tab0[nm]
        det[nm] = dict(
            形=f, 名前=name5(f),
            元の物差し=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 五パーセント未満=o['P5π（5%未満）'], 最悪の世界=o['最悪の世界'],
                         最大下落=o['最大下落'], ぶれ=o['ぶれ'], 世界=o['世界ごとの年率'], 過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上']),
            元の物差しの感度ごとの今との差={N.VARS_JA[v]: dict(P15=r(vt[nm][v]['P15'] - vt['今'][v]['P15']),
                                                     平均=r(vt[nm][v]['mean_pi'] - vt['今'][v]['mean_pi'], 3)) for v in N.VARS},
            基礎率の物差し=dict(P15π=r(bd['P15'][j]), 平均=r(bd['mean_pi'][j]), 五パーセント未満=r(bd['P5'][j])),
            基礎率の感度ごとの今との差={v: dict(平均=r(Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][j0], 3),
                                        五パーセント未満=r(Vd[v]['P5'][j] - Vd[v]['P5'][j0])) for v in BR.VARS},
            小型バリューの上乗せなし_S2=dict(P15π=r(Sd['P15'][j]), 平均=r(Sd['mean_pi'][j]), 五パーセント未満=r(Sd['P5'][j])),
            百年=dict(三十年の中央=round(float(cd['c30med'][j]), 3), 三十年の最悪=round(float(cd['c30min'][j]), 3),
                    感度_1985年11月から本物のNASDAQ100=dict(三十年の中央=round(float(cad['c30med'][j]), 3), 三十年の最悪=round(float(cad['c30min'][j]), 3))),
            実績=dict(年15パーセント以上の割合=r(rd['share'][j], 1), 年率の中央=r(rd['med'][j]), 最悪=r(rd['worst'][j])),
            円の枠={k: tj[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最大下落', '過去の転がる20年で15%以上')},
            勝ち業種の中身の比重の合計=r(float((Wdn[j] @ IND).sum()), 1),
            中身の集中=B.lookthrough(f))
        log(nm, json.dumps({k: det[nm][k] for k in ('元の物差し', '基礎率の物差し', '実績')}, ensure_ascii=False)[:500])
    out['詳しい物差し'] = det
    out['secs'] = round(time.time() - t0)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('→', OUT, out['secs'], 's')


if __name__ == '__main__':
    main()
