#!/usr/bin/env python3
"""night/ndx40_opt_check.py — XLV・XLP・XLU を直したデータで、NASDAQ100 40%以上の最適な形を探す（2026-11-25・参考・配分は変えない）

ユーザー「データを置き換えて最適解をだして」（同日に XLV・XLP・XLU の 1999-01〜2002-06 の壊れた終値を直した＝night/sector_spdr_fix.py・書庫:22245）。
読み方（固定）: 「最適解」＝ 2026-11-23 にユーザーの条件「NASDAQ は40%は欲しい」で答えた選び方（書庫:22007・form_eval ndx40）を、
  ①直したデータで ②今の main（40/25/15/10/10・ユーザーが同日マージした形）を相手に ③直した3本（XLV・XLP・XLU）も候補に入れて
  もう一度当てた答え。11-23 の範囲は XLV・XLP・XLU を含まなかった＝直しはその答えに効かないので、候補に足さないと「置き換え」が意味を持たない。
★範囲・条件・選び方・確かめはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの（この選び方を決める前に知っていた数字）: 今の main（直したデータ）期待の年率 10.98・年15%以上 27.56・年5%未満 18.27・
    最大下落 −66.0（円 −61.1）・基礎率の平均 8.45・100年の最悪 1.427（:22220）／11-23 の答え 40/25/10/10/15 は 年15%以上 27.53・
    年5%未満 18.29・最大下落 −65.9（円 −61.1）・基礎率の平均 8.51・100年の最悪 1.471（:22007・今の main より年5%未満が 0.02 悪い）／
    今の main に XLV・XLP・XLU を5%足す・NASDAQ100 や VBR から回す形はどれも (d)（:22154・:22245 の測り直し）／
    1本ずつでは XLP の 2000年からの年率 8.35%・XLV 7.78%・XLU 6.80%（直した後）。
  見ていないもの: 下の範囲を並べた結果・条件を通る形の数・答え。
範囲（ETF 側・合計100・5%刻み・個別株の写し10%は集中の物差しにだけ入る＝form_eval と同じ）:
  NASDAQ100（QQQM）40〜50／SMH 15〜35／ITA 5〜20／FBT 5〜20／VBR 0〜20（ここまで 11-23 と同じ・NASDAQ100 だけ 45・50 も許す）
  ＋ XLV 0〜20／XLP 0〜20／XLU 0〜20（直した3本）。金・国債は方針（2026-11-04）で入れない。
条件（11-23 と同じ5つ・向きをそろえた生の値で 相手 − 1e-12 以上を「悪くならない」とする）: 今の main と比べ
  ③年5%未満の確率 ≤ ・④最大下落（ドル・崩れあり）≥ ・最大下落（円・崩れあり）≥ ・⑥業種の基礎率の平均 ≥ ・
  ⑨100年の代用の30年の最悪（NASDAQ100 の入れ替えを数える V1）≥。
選び方: 条件を通った形のうち ②年15%以上の確率（元）が最も高い形（0.001pt に丸めて同じなら ①期待の年率 → ④最大下落の浅い順 → 名前の順）。
  今の main 自身は5つとも等しいので必ず通る＝「通る形が無い」は起きない（答えが今の main なら「今のまま」）。
併せて出す（答えを決めるのに使わない）: 上位10／XLV・XLP・XLU それぞれを5%以上含む形の最良と数／条件を外したときの年15%以上の天井／
  11-23 の範囲（NASDAQ100 40・3本なし）だけで同じ選び方を今の main に当てた答え／
  同じ道具を CCF_SPDR_FIX=off（直す前のデータ）で回した答え（--out で別のファイル。答えはこのファイルの直したデータの方）。
  答えは別に form_eval で今の main と11-23 の答えに当てて (a)〜(d) を出す（設定は回す前にコミット）。
回帰の検査（どれかが外れれば止める）:
  (a) 11-23 の今の形（45/20/10/15/10）と R の13の物差し（V0・V1）が out/ndx_recon_check.json と一致（3本を含まない＝直しで動かない）
  (b) 今の main の13の物差しと円の値が out/form_eval_ndx45_xlv5_spdrfix.json と一致（表示の桁で）
  (c) 11-23 の答え 40/25/10/10/15 の13の物差しと円の値が out/form_eval_ndx40.json と一致（表示の桁で）
  (d) 円の最大下落の速い計算（Fast を円の系列で）が measure（円）と 1e-9 以内（今の main・11-23 の答え・範囲の先頭の3形）
使い方: python3 night/ndx40_opt_check.py [--out FILE] → out/ndx40_opt_check.json（約1分）
"""
import contextlib, io, itertools, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx40_opt_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import ndx_recon_check as NR  # noqa: E402

FUNDS = ['QQQM', 'SMH', 'ITA', 'FBT', 'VBR', 'XLV', 'XLP', 'XLU']
NEW3 = ['XLV', 'XLP', 'XLU']
RANGE = {'QQQM': (40, 50), 'SMH': (15, 35), 'ITA': (5, 20), 'FBT': (5, 20), 'VBR': (0, 20), 'XLV': (0, 20), 'XLP': (0, 20), 'XLU': (0, 20)}
STEP, EPS, P15_TIE, MEAN_TIE = 5, 1e-12, 1e-3, 1e-4
MAIN = {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'FBT': 10, 'VBR': 10}       # 今の main（ETF 側）
OLD_ANS = {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'FBT': 10, 'VBR': 15}    # 11-23 の答え
K_MAIN, K_OLD = '今の main 40/25/15/10/10', '11-23 の答え 40/25/10/10/15'
YJA, YSIGN, YSCALE, YDEC = NR.YJA, NR.YSIGN, NR.YSCALE, NR.YDEC
VERS = ('V0', 'V1')
r = NR.r


def log(*a):
    print('[ndx40_opt]', *a, file=sys.stderr, flush=True)


def name(f):
    ja = {'QQQM': 'NASDAQ100'}
    return ' / '.join(f'{ja.get(c, c)} {f[c]}' for c in FUNDS if f.get(c))


def grid():
    lo = {c: RANGE[c][0] // STEP for c in FUNDS}
    hi = {c: RANGE[c][1] // STEP for c in FUNDS}
    tot = 100 // STEP
    out = []
    for combo in itertools.product(*[range(lo[c], hi[c] + 1) for c in FUNDS[:-1]]):
        rest = tot - sum(combo)
        if lo[FUNDS[-1]] <= rest <= hi[FUNDS[-1]]:
            out.append(dict(zip(FUNDS, [x * STEP for x in combo] + [rest * STEP])))
    return out


def main(out_path=OUT):
    t0 = time.time()
    import lookthrough as L
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = list(BR.POOL)
    if any(c not in P for c in FUNDS):
        raise SystemExit(f'物差しに無い本: {[c for c in FUNDS if c not in P]}')
    C = B.century_extend(U)
    fast = B.Fast(U, rows, chains, P)
    ch_jpy, _ = U.jpy_chains(chains)
    fastJ = B.Fast(U, rows, ch_jpy, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    a0 = BR.adj_vector(vec, st, BR.RATES['主（20年の値）'], P)[0]
    qs, _ = NR.build_copies(C)
    cts = {v: BCc.CentP(U, P, {**C['parts'], 'QQQM': qs[v]}) for v in VERS}

    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    share = {}
    for c in sorted(set(FUNDS) | set(NR.SIX)):
        look, unk = L.explode({c: 1e6}, prof)
        if sum(unk.values()) / 1e6 >= 0.5:
            raise SystemExit(f'中身が読めない本: {c}')
        share[c] = dict(semi=sum(v for t, v in look.items() if t in L.SEMI) / 1e6, nvda=look.get('NVDA', 0.0) / 1e6)
    _, seats, _ = U.castle_copy()
    per = NR.CASTLE_PCT / len(list(seats))
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    def conc(A):
        Wn = 100 * A / A.sum(axis=1, keepdims=True)
        sv = np.array([share[c]['semi'] if c in share else 0.0 for c in P])
        nv = np.array([share[c]['nvda'] if c in share else 0.0 for c in P])
        bad = (Wn > 0) & np.array([c not in share for c in P])[None, :]
        if bad.any():
            raise SystemExit('中身の無い本を含む形がある')
        return c_semi + NR.K * (Wn * sv[None, :]).sum(axis=1), c_nvda + NR.K * (Wn * nv[None, :]).sum(axis=1)

    def ymat(A):
        """13の物差し（form_eval と同じ並び・向きをそろえた生の値）＋円の最大下落"""
        Y = np.full((len(A), 13), np.nan)
        e, b, ej = fast.eval(A), fbr.eval(A, a0), fastJ.eval(A)
        Y[:, 0], Y[:, 1], Y[:, 2], Y[:, 3], Y[:, 4], Y[:, 10] = e['mean_pi'], e['P15'], -e['P5'], e['mdd'], e['worst'], e['past20']
        Y[:, 5], Y[:, 6] = b['mean_pi'], -b['P5']
        lo, nd = conc(A)
        Y[:, 11], Y[:, 12] = -lo, -nd
        Y[:, 9] = realized(A, fast)['med']
        out = {}
        for v in VERS:
            Z = Y.copy()
            cc = BCc.cent_chunked(cts[v], A)
            Z[:, 7], Z[:, 8] = np.where(cc['ok'], cc['c30med'], np.nan), np.where(cc['ok'], cc['c30min'], np.nan)
            Z[~(e['ok'] & b['ok'])] = np.nan
            out[v] = Z
        return out, ej['mdd'], e

    def ydict(y):
        return {YJA[i]: r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}

    # ── 回帰の検査 ──
    ref = json.load(open(os.path.join(BASE, 'out', 'ndx_recon_check.json')))
    Ya, _, _ = ymat(W_of([NR.NOWF, NR.RF]))
    got = {v: [ydict(Ya[v][0]), ydict(Ya[v][1])] for v in VERS}
    want = {v: [ref['今の形']['物差し13'][v], ref['R']['物差し13'][v]] for v in VERS}
    if not all(got[v] == want[v] for v in VERS):
        raise SystemExit(f'回帰の検査(a)が通らない: {got} 対 {want}')
    log('回帰の検査 (a) ✓')
    fe_now = json.load(open(os.path.join(BASE, 'out', 'form_eval_ndx45_xlv5_spdrfix.json')))['形ごと'][K_MAIN]
    fe_old = json.load(open(os.path.join(BASE, 'out', 'form_eval_ndx40.json')))['形ごと']
    k_old = [k for k, v in fe_old.items() if v.get('ETF側の比') and {c: round(x) for c, x in v['ETF側の比'].items() if x} ==
             {('NASDAQ100' if c == 'QQQM' else c): x for c, x in OLD_ANS.items()}]
    if len(k_old) != 1:
        raise SystemExit(f'11-23 の答えが out/form_eval_ndx40.json に1つで見つからない: {k_old}')
    fe_old = fe_old[k_old[0]]
    Yb, mJb, _ = ymat(W_of([MAIN, OLD_ANS]))
    for j, (lab, fe) in enumerate([('(b) 今の main', fe_now), ('(c) 11-23 の答え', fe_old)]):
        for v in VERS:
            if ydict(Yb[v][j]) != fe['物差し13'][v]:
                raise SystemExit(f'回帰の検査{lab} {v} が通らない: {ydict(Yb[v][j])} 対 {fe["物差し13"][v]}')
        if r(100 * mJb[j], 1) != fe['円']['最大下落']:
            raise SystemExit(f'回帰の検査{lab} 円の最大下落が通らない: {r(100 * mJb[j], 1)} 対 {fe["円"]["最大下落"]}')
    log('回帰の検査 (b)(c) ✓')

    G = grid()
    A = W_of(G)
    names = [name(f) for f in G]
    YD, mJ, eA = ymat(A)
    Y = YD['V1']
    meas = ~np.isnan(Y).any(axis=1) & ~np.isnan(mJ)
    log('範囲', len(G), '形・測れた', int(meas.sum()), f'{time.time() - t0:.0f}s')

    # (d) 円の最大下落の速い計算と measure（円）
    Fm = {K_MAIN: MAIN, K_OLD: OLD_ANS, **{f'@{i}': {c: v for c, v in G[i].items() if v} for i in range(3)}}
    assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
    with contextlib.redirect_stdout(io.StringIO()):
        tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets), windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    Wd = W_of(Fm.values())
    _, mJd, _ = ymat(Wd)
    for j, k in enumerate(Fm):
        if abs(float(mJd[j]) - float(tj[k]['_raw']['mdd'])) > 1e-9:
            raise SystemExit(f'回帰の検査(d) 円の最大下落 {k}: {mJd[j]} 対 {tj[k]["_raw"]["mdd"]}')
    log('回帰の検査 (d) ✓')

    if name(MAIN) not in names:
        raise SystemExit('今の main が範囲に無い')
    iM = names.index(name(MAIN))
    yM, mJM = Y[iM], mJ[iM]
    cond = (Y[:, 2] >= yM[2] - EPS) & (Y[:, 3] >= yM[3] - EPS) & (mJ >= mJM - EPS) & (Y[:, 5] >= yM[5] - EPS) & (Y[:, 8] >= yM[8] - EPS)

    def order(mask):
        idx = [int(i) for i in np.where(mask & meas)[0]]
        idx.sort(key=lambda i: (-round(float(Y[i, 1]) / P15_TIE), -round(float(Y[i, 0]) / MEAN_TIE), -float(Y[i, 3]), names[i]))
        return idx

    def row(i):
        return dict(形=names[i], ETF側の比={('NASDAQ100' if c == 'QQQM' else c): G[i][c] for c in FUNDS if G[i][c]},
                    物差し13={v: ydict(YD[v][i]) for v in VERS}, 円の最大下落=r(100 * mJ[i], 1),
                    今のmainとの差={YJA[k]: r((Y[i, k] - yM[k]) * YSIGN[k] * YSCALE[k], YDEC[k] + 1) for k in range(13)})

    ok_idx = order(cond)
    ans = ok_idx[0]
    old_space = np.array([(g['QQQM'] == 40 and all(g[c] == 0 for c in NEW3)) for g in G])
    old_idx = order(cond & old_space)
    incl = {}
    for c in NEW3:
        m = np.array([g[c] >= 5 for g in G])
        oi = order(cond & m)
        incl[c] = dict(条件を通った形の数=len(oi), 最良=(row(oi[0]) if oi else None),
                       最良の順位=(ok_idx.index(oi[0]) + 1 if oi else None))
    ceil = order(np.ones(len(G), dtype=bool))
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/ndx40_opt_check.py',
        kind='参考（範囲・条件・選び方はこの道具の頭に固定し回す前にコミット・配分は変えない）',
        data=('直す前（CCF_SPDR_FIX=off）' if os.environ.get('CCF_SPDR_FIX') == 'off' else '直したデータ（night/sector_spdr_fix.py）'),
        範囲=dict(本=FUNDS, 刻み=STEP, 上下限={('NASDAQ100' if c == 'QQQM' else c): RANGE[c] for c in FUNDS}, 形の数=len(G), 測れた=int(meas.sum())),
        条件を通った形の数=len(ok_idx), 今のmain=row(iM), 答え=row(ans), 答えは今のmainか=(ans == iM),
        上位10=[row(i) for i in ok_idx[:10]], 直した3本を含む形=incl,
        十一月二十三日の範囲だけの答え=(row(old_idx[0]) if old_idx else None),
        条件を外した天井=row(ceil[0]), secs=round(time.time() - t0, 1))
    with open(out_path, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('書いた', out_path, f'{time.time() - t0:.0f}s')
    print(json.dumps(dict(形の数=len(G), 通った=len(ok_idx), 答え=names[ans], 今のmainか=(ans == iM),
                          十一月二十三日の範囲だけ=(names[old_idx[0]] if old_idx else None),
                          三本ごと={c: (incl[c]['条件を通った形の数'], incl[c]['最良']['形'] if incl[c]['最良'] else None, incl[c]['最良の順位']) for c in NEW3},
                          天井=names[ceil[0]]), ensure_ascii=False))


if __name__ == '__main__':
    args = sys.argv[1:]
    out_path = OUT
    if args[:1] == ['--out'] and len(args) == 2:
        out_path = os.path.abspath(args[1])
    elif args:
        raise SystemExit('使い方: python3 night/ndx40_opt_check.py [--out FILE]')
    main(out_path)
