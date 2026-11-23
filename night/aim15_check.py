#!/usr/bin/env python3
"""night/aim15_check.py — 年15%以上を狙うなら私が選ぶ形（2026-11-23・参考・配分は変えない）

ユーザー「あなたが今までの全てでなにを選ぶか教えて。リターン15％以上を狙うなら。」
読み方（固定）: 「狙う」＝20年の毎月の積立の内部収益率が年15%以上になる確率（P15π・元の物差し②）を最大にする。
  ただし私が15%を狙うときでも手放さないものを条件にする（下の G1〜G3）。門・採点・配分（portfolio.json）・注文書には触れない。
★範囲・条件・選び方・確かめはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの（この選び方を決める前に知っていた数字）:
    1本ずつの P15π（SMH 35.3・NASDAQ100 23.8・FBT 22.0・ITA 20.6・VBR 17.0・XLV 8.7＝ndx_recon_posthoc）／
    今の形 26.75・案 45/25/10/10/10 27.65・枝の案 R 28.51／NASDAQ100 の下限つきの答え（別の選び方＝4つの目標の取り逃がし）
    20/35/5/30/10 29.48・25/30/10/30/5 28.71・30/30/10/25/5 28.70・35/30/15/15/5 28.57（ndx_recon_posthoc）／
    11-09 の案B 20/35/15〔ITA〕/20〔FBT〕/10 29.4／best15c の SMH 40 / FBT 35 / ITA 20 / NASDAQ100 5 30.5。
    ＝P15π はほぼ SMH の量で決まる（5増やすごとに約 +0.8〜0.9pt）と知ったうえで決めた選び方である。
  見ていないもの: 下の範囲を P15π の順に並べた結果・条件を通る形の数・確かめの合否。

範囲（ETF 側・合計100・5%刻み・個別株10%は別）: 6本（NASDAQ100＝QQQM・SMH・ITA・XLV・FBT・VBR）。
  NASDAQ100 以外は1本40%まで（best15 と同じ上限）。金・国債は方針（2026-11-04）で入れない。
条件（G＝15%を狙っても手放さないもの。向きをそろえた生の値で、相手 − 1e-12 以上を「下回らない」とする）:
  G1 届く形: NASDAQ100 ≥ 25%。理由（物差しの外の算数・この道具が repo の保有と入金の計画から出して併記する）:
     NASDAQ100 の区分（XLK・QQQM＝売らない）は今 ETF 側の約79%・今月の入金140万円のあと約36%。2027-01 から自動の積立
     （iDeCo・こどもNISA＝月3.5万円）が NASDAQ100 を買い続けるので、注文書が1円も入れなくても 30% まで約5か月・25% まで約1年半・
     20% までは6年以上かかる（値段は横ばい）。2年以内に届かない目標は、測った形を何年も持てない＝数字が絵になるので外す。
  G2 下の側を今より悪くしない: ③年5%未満の確率 ≤ 今の形（main）∧ ④最大下落 ≥ 今の形。
  G3 集中は枝の案まで: ⑫半導体の連鎖（下限）≤ R ∧ ⑬NVDA ≤ R（R＝ETF 側 40 / 30 / 15 / 10 / 5・資産全体 40.26%・9.06%）。
選び方: G1〜G3 を通った形を ②P15π の高い順に（0.1pt に丸めて同じなら ①期待の年率の高い順 → ④最大下落の浅い順 → 名前の順）。
最終の確かめ（相手は今の形・上から30まで・最初にすべて通った形が答え）:
  F1 感度5本（主・A2〔直近15年〕を外す・半導体の基礎率・分散の上乗せなし・共分散をA2の窓から）のすべてで 期待の年率 ≥ 今
  F2 業種の基礎率の感度6本すべてで 平均 ≥ 今 ∧ 5%未満 ≤ 今
  F3 円の枠（崩れあり）で 期待の年率 ≥ 今 ∧ 最大下落 ≥ 今
  30までにすべて通る形が無ければ、F1 と F3 を通る最初の形を答えにして F2 を通らないと明記する。それも無ければ並びの1位を答えにして
  通らない確かめを明記する。条件を通る形が1つも無ければ「15%を狙って今より良くなる形は無い（今のまま）」とする。
併せて出す（参考・答えを決めるのに使わない・各1位と確かめ）:
  (a) NASDAQ100 ≥ 30%  (b) NASDAQ100 ≥ 20%  (c) FBT ≤ 20%（バイオを厚くしない場合）  (d) G3（集中）を外す
  (e) G2（下の側）を外す  (f) G2 も G3 も外す＝この範囲の P15π の天井（NASDAQ100 ≥ 25%）
  SMH の比ごとの最良（G1・G2 だけ・P15π の順）と、その半導体の連鎖・NVDA／答え・今の形・R の詳しい物差し／
  答えと今の形・R の13の物差しの勝ち負け／届くまでの月数の算数
物差しは beat_ret_check・ndx_recon_check・ndx45_smh25_check と同じ13（best15 の Fast・best15r の FastBR・100年の代用は
  NASDAQ100 の入れ替えを数える V1 と数えない V0・five_mix_ndx の realized・lookthrough.explode の線形の集中）。
回帰の検査（どれかが外れれば止める）: (a) 今の形・R の13の物差し（V0・V1）が out/ndx_recon_check.json と一致
  (b) 答えと今の形で Fast と感度の主が measure と 1e-9 以内 (c) 実績の割合が past20 と一致
  (d) 線形の集中が lookthrough.py（資産全体で渡す）と一致（答え・今の形）
⚠ 限界: P15π は4つ〜5つの世界の重み付きで、15%以上の大半は「直近15年・26年の実績が続く世界」から来る＝狙うこと自体がその賭け／
  どの形でも真ん中は10〜11%で、15%以上は3回に1回に届かない／形どうしの差は雑音に近い（1pt 未満の差に意味は薄い）／
  未来の世界は予想・分散の上乗せは仮定／FBT の未来の年率は医薬品の業種の写し／実績は一つの時代／中身は 2026-08〜10 の写し／
  税と NISA の枠（成長投資枠は約12年で埋まる）・1株単位の買い方は物差しに入らない／G1 の算数は値段が横ばいの仮定
使い方: python3 night/aim15_check.py → out/aim15_check.json（約1分）
"""
import contextlib, io, json, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'aim15_check.json')
REFJ = os.path.join(BASE, 'out', 'ndx_recon_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import beat_ret_check as BT  # noqa: E402
import ndx_recon_check as NR  # noqa: E402

SIX, RF, NOWF = NR.SIX, NR.RF, NR.NOWF
CASTLE_PCT, K, STEP = NR.CASTLE_PCT, NR.K, NR.STEP
EPS = NR.EPS
YJA, YSIGN, YSCALE, YDEC = NR.YJA, NR.YSIGN, NR.YSCALE, NR.YDEC
nm, whole, r = NR.nm, NR.whole, NR.r
K_NOW, K_R, K_ANS = '今の形（main）', 'R（枝の案）', '答え'
VERS = ('V0', 'V1')
FLOOR, SAT_CAP, NFIN, NTOP = 25, 40, 30, 10
P15_TIE, MEAN_TIE = 1e-3, 1e-4
IX_NDX, IX_SMH, IX_FBT = SIX.index('QQQM'), SIX.index('SMH'), SIX.index('FBT')


def log(*a):
    print('[aim15]', *a, file=sys.stderr, flush=True)


def reach():
    """G1 の算数: 注文書が NASDAQ100 に1円も入れないとき、NASDAQ100 の区分が ETF 側の x% まで下がる月数（値段は横ばい）"""
    st = json.load(open(os.path.join(BASE, 'state.json')))['data']
    J = lambda x: json.loads(x) if isinstance(x, str) else x  # noqa: E731
    pf_ = J(st['pf:portfolio'])
    pos = pf_['positions'] if isinstance(pf_, dict) else pf_
    d = json.load(open(os.path.join(BASE, 'out', 'dashboard.json')))
    fx = float(d['fx']['USDJPY'])
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    same = set(['IFREE-NDX']) | set((tg.get('ami_same_index') or {}).get('IFREE-NDX', [])) | set((tg.get('ami_same_bucket') or {}).get('IFREE-NDX', []))
    ndx = etf = castle = 0.0
    miss = []
    for p in pos:
        q = (d['quotes'].get(p['t']) or {}).get('px')
        if not q or not p.get('sh'):
            miss.append(p['t'])
            continue
        v = float(p['sh']) * float(q) * (1.0 if p.get('ccy') == 'JPY' else fx)
        if p.get('sleeve') == 'castle':
            castle += v
        else:
            etf += v
            if p['t'] in same:
                ndx += v
    first = float(J(st.get('pf:monthly_total')) or 0)
    plan = float((tg.get('nisa') or {}).get('monthly_total_jpy') or 0)
    auto = sum(float(m.get('jpy') or 0) for m in (tg.get('ideco') or {}).get('members', [])) + \
        sum(float(m.get('jpy') or 0) for m in (tg.get('kodomo_nisa') or {}).get('members', []))
    start = (tg.get('ideco') or {}).get('start') or (tg.get('kodomo_nisa') or {}).get('start')
    out = dict(今=dict(ETF側=round(etf), NASDAQ100の区分=round(ndx), 個別株=round(castle), NASDAQ100のETF側の比=round(100 * ndx / etf, 1)),
               今月の入金=first, 毎月の入金の計画=plan, 自動でNASDAQ100に入る円=auto, 自動の積立の開始=start, 価格の無い行=miss,
               前提='値段は横ばい・個別株は目標を超えているので新しいお金は全部 ETF 側・注文書は NASDAQ100 に入れない（自動の積立だけが入る）')
    if not (etf > 0 and plan > 0):
        out['届くまでの月数'] = '測れない'
        return out
    today = time.strftime('%Y-%m')
    y, m = int(today[:4]), int(today[5:7])
    e, n, month, hit = etf + first, ndx, 0, {}
    path = {0: round(100 * n / e, 1)}
    targets = [35, 30, 25, 20]
    for t in targets:
        if 100 * n / e <= t:
            hit[t] = 0
    while month < 240 and len(hit) < len(targets):
        month += 1
        m += 1
        if m > 12:
            y, m = y + 1, 1
        a = auto if (start and f'{y:04d}-{m:02d}' >= start) else 0.0
        e += plan
        n += a
        if month in (1, 6, 12, 24):
            path[month] = round(100 * n / e, 1)
        for t in targets:
            if t not in hit and 100 * n / e <= t:
                hit[t] = month
    out['今月の入金のあと・その後の月ごとのNASDAQ100の比'] = path
    out['届くまでの月数'] = {f'{t}%': (hit.get(t) if t in hit else '20年のうちに届かない') for t in targets}
    out['長い目の下限'] = round(100 * auto / plan, 1)
    return out


def main(write=True):
    t0 = time.time()
    live = json.loads(subprocess.run(['git', 'show', 'origin/main:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    brt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    for k, t, f in [(K_NOW, live, NOWF), (K_R, brt, RF)]:
        w, cp = BT.etf_side(t)
        if not BT.same(w, f) or cp != CASTLE_PCT:
            raise SystemExit(f'{k} が正本と違う: {w} 個別株 {cp}')
    rc = reach()
    log('届くまで', json.dumps(rc.get('届くまでの月数'), ensure_ascii=False))

    import lookthrough as L
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import bestpf_eval as E
    import ndx_swap_check as N
    ref = json.load(open(REFJ))
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
    cts = {v: BCc.CentP(U, P, {**C['parts'], 'QQQM': qs[v]}) for v in VERS}

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    share = {}
    for c in SIX:
        look, unk = L.explode({c: 1e6}, prof)
        if sum(unk.values()) / 1e6 >= 0.5:
            raise SystemExit(f'中身が読めない本: {c}')
        share[c] = dict(semi=sum(v for t, v in look.items() if t in L.SEMI) / 1e6, unk=sum(unk.values()) / 1e6, nvda=look.get('NVDA', 0.0) / 1e6)

    def sarr(key):
        return np.array([share[c][key] if c in share else np.nan for c in P])
    sv, uv, nv = sarr('semi'), sarr('unk'), sarr('nvda')
    _, seats, _ = U.castle_copy()
    seats = list(seats)
    per = CASTLE_PCT / len(seats)
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')

    def conc_arr(A):
        Wn = 100 * A / A.sum(axis=1, keepdims=True)
        used = Wn > 0
        if (used & np.isnan(sv)[None, :]).any():
            raise SystemExit('中身の無い本を含む形がある')
        lo = c_semi + K * np.where(used, Wn * sv[None, :], 0.0).sum(axis=1)
        un = K * np.where(used, Wn * uv[None, :], 0.0).sum(axis=1)
        nd = c_nvda + K * np.where(used, Wn * nv[None, :], 0.0).sum(axis=1)
        return lo, un, nd

    N.CASTLE_ARG = ','.join(f'{s}={per:g}' for s in seats)
    for c in SIX:
        N.NET_ARG[c] = c

    def look_whole(f):
        lk = N.lookthrough({c: v * K for c, v in f.items() if v})
        m = re.match(r'([\d.]+)〜([\d.]+)%', lk.get('半導体の連鎖（下限〜上限）', ''))
        return lk, (float(m.group(1)) if m else None), (float(m.group(2)) if m else None)

    def ymat(A):
        Y = np.full((len(A), 13), np.nan)
        e, b = fast.eval(A), fbr.eval(A, a0)
        Y[:, 0], Y[:, 1], Y[:, 2], Y[:, 3], Y[:, 4], Y[:, 10] = e['mean_pi'], e['P15'], -e['P5'], e['mdd'], e['worst'], e['past20']
        Y[:, 5], Y[:, 6] = b['mean_pi'], -b['P5']
        lo, un, nd = conc_arr(A)
        Y[:, 11], Y[:, 12] = -lo, -nd
        rz = realized(A, fast)
        Y[:, 9] = rz['med']
        out = {}
        for v in VERS:
            Z = Y.copy()
            cc = BCc.cent_chunked(cts[v], A)
            Z[:, 7], Z[:, 8] = np.where(cc['ok'], cc['c30med'], np.nan), np.where(cc['ok'], cc['c30min'], np.nan)
            Z[~(e['ok'] & b['ok'])] = np.nan
            out[v] = Z
        return out, e, b, rz, un

    def ydict(y):
        return {YJA[i]: r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}

    ve_names = list(BR.VARS)

    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()

    # ── 参照の形と回帰の検査 (a) ──
    Wref = W_of([NOWF, RF])
    YRf, eR, bR, rzR, _ = ymat(Wref)
    yN, yR = YRf['V1'][0], YRf['V1'][1]
    got = {K_NOW: {v: ydict(YRf[v][0]) for v in VERS}, K_R: {v: ydict(YRf[v][1]) for v in VERS}}
    want = {K_NOW: ref['今の形']['物差し13'], K_R: {v: ref['R']['物差し13'][v] for v in VERS}}
    if not all(got[k][v] == want[k][v] for k in got for v in VERS):
        raise SystemExit(f'回帰の検査(a)が通らない: {got}')
    log('回帰の検査 (a) ✓')

    # ── 範囲 ──
    G0 = BT.grid_of(0, False)
    sat = np.delete(G0, IX_NDX, axis=1)
    inrange = (G0[:, IX_NDX] * STEP >= 20) & (sat * STEP <= SAT_CAP).all(axis=1)
    G = G0[inrange]
    A = np.zeros((len(G), len(P)), dtype=np.float64)
    A[:, [P.index(c) for c in SIX]] = G
    forms = [{c: int(x) * STEP for c, x in zip(SIX, row) if x} for row in G]
    names = [nm(f) for f in forms]
    YA, eA, bA, rzA, unA = ymat(A)
    Y = YA['V1']
    meas = ~np.isnan(Y).any(axis=1)
    ndxp, smhp, fbtp = G[:, IX_NDX] * STEP, G[:, IX_SMH] * STEP, G[:, IX_FBT] * STEP
    log('範囲', len(G), '形・測れた', int(meas.sum()), f'{time.time() - t0:.0f}s')

    g2 = (Y[:, 2] >= yN[2] - EPS) & (Y[:, 3] >= yN[3] - EPS)
    g3 = (Y[:, 11] >= yR[11] - EPS) & (Y[:, 12] >= yR[12] - EPS)

    def order(mask):
        idx = [int(i) for i in np.where(mask & meas)[0]]
        idx.sort(key=lambda i: (-round(float(Y[i, 1]) / P15_TIE), -round(float(Y[i, 0]) / MEAN_TIE), -float(Y[i, 3]), names[i]))
        return idx

    ch_jpy, _ = U.jpy_chains(chains)
    FC = {}

    def fcheck(il):
        todo = [i for i in il if names[i] not in FC]
        for s in range(0, len(todo), 10):
            part = todo[s:s + 10]
            Fm = {K_NOW: NOWF, **{'@' + names[i]: forms[i] for i in part}}
            assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
            with contextlib.redirect_stdout(io.StringIO()):
                k4, _ = N.chips_adj(rows, assets)
                vt = N.variants(Fm, rows, chains, k4)[UC.W_CRASH]
                tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets), windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
            Wf = W_of(Fm.values())
            vres = {v: ve(Wf, v) for v in ve_names}
            for j, i in enumerate(part, start=1):
                k = '@' + names[i]
                d1 = {N.VARS_JA[v]: round(100 * (vt[k][v]['mean_pi'] - vt[K_NOW][v]['mean_pi']), 3) for v in N.VARS}
                f1 = all(vt[k][v]['mean_pi'] >= vt[K_NOW][v]['mean_pi'] - EPS for v in N.VARS)
                d2 = {v: dict(平均=round(100 * float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]), 3),
                              五パーセント未満=round(100 * float(vres[v]['P5'][j] - vres[v]['P5'][0]), 2)) for v in ve_names}
                f2 = all(vres[v]['mean_pi'][j] >= vres[v]['mean_pi'][0] - EPS and vres[v]['P5'][j] <= vres[v]['P5'][0] + EPS for v in ve_names)
                dj = 100 * (tj[k]['_raw']['mean_pi'] - tj[K_NOW]['_raw']['mean_pi'])
                dm = 100 * (tj[k]['_raw']['mdd'] - tj[K_NOW]['_raw']['mdd'])
                f3 = bool(dj >= -1e-10 and dm >= -1e-10)
                FC[names[i]] = dict(F1=bool(f1), F2=bool(f2), F3=f3, 合否=bool(f1 and f2 and f3), 感度5本の今との差=d1,
                                    基礎率の感度6本の今との差=d2, 円の今との差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2)))

    def brief(i, with_fc=True):
        y = Y[i]
        out = dict(名前=names[i], 形=forms[i], 全体の比=whole(forms[i]), 物差し=ydict(y),
                   百年_V0=dict(三十年の中央=r(YA['V0'][i, 7], 3), 三十年の最悪=r(YA['V0'][i, 8], 3)),
                   今との差={YJA[k]: r((y[k] - yN[k]) * YSCALE[k] * YSIGN[k], max(YDEC[k], 2) + 1) for k in range(13)},
                   Rとの差={YJA[k]: r((y[k] - yR[k]) * YSCALE[k] * YSIGN[k], max(YDEC[k], 2) + 1) for k in range(13)},
                   今を下回る物差し=[YJA[k] for k in range(13) if not (y[k] >= yN[k] - EPS)],
                   Rを下回る物差し=[YJA[k] for k in range(13) if not (y[k] >= yR[k] - EPS)], 半導体の未取得=r(float(unA[i]), 2))
        if with_fc and names[i] in FC:
            out['確かめ'] = FC[names[i]]
        return out

    def decide(mask, label):
        od = order(mask)
        if not od:
            return dict(条件を通った形=0, 答え='条件を通る形は無い'), None
        top = od[:NFIN]
        ans = how = None
        for s in range(0, len(top), 10):
            fcheck(top[s:s + 10])
            for i in top[s:s + 10]:
                if FC[names[i]]['合否']:
                    ans, how = i, 'F1〜F3 をすべて通った最初の形'
                    break
            if ans is not None:
                break
        if ans is None:
            for i in top:
                if FC[names[i]]['F1'] and FC[names[i]]['F3']:
                    ans, how = i, 'F1 と F3 を通る最初の形（F2 を通らない）'
                    break
        if ans is None:
            ans, how = top[0], '並びの1位（確かめを通らない）'
        return dict(条件を通った形=len(od), 答えの決まり方=how, 答え=brief(ans), 並びの1位=brief(top[0]),
                    上位=[brief(i) for i in od[:NTOP]],
                    確かめた形=[dict(名前=names[i], P15π=r(Y[i, 1] * 100, 2), F1=FC[names[i]]['F1'], F2=FC[names[i]]['F2'], F3=FC[names[i]]['F3'])
                           for i in top if names[i] in FC]), ans

    base = ndxp >= FLOOR
    main_res, ans = decide(base & g2 & g3, '主')
    log('主', main_res.get('条件を通った形'), (main_res['答え']['名前'] if isinstance(main_res.get('答え'), dict) else main_res.get('答え')),
        main_res.get('答えの決まり方'), f'{time.time() - t0:.0f}s')

    def first_of(mask):
        od = order(mask)
        if not od:
            return dict(条件を通った形=0)
        fcheck(od[:1])
        return dict(条件を通った形=len(od), 並びの1位=brief(od[0]))
    refs = {'(a) NASDAQ100 30%以上': first_of((ndxp >= 30) & g2 & g3),
            '(b) NASDAQ100 20%以上': first_of((ndxp >= 20) & g2 & g3),
            '(c) FBT 20%まで': first_of(base & g2 & g3 & (fbtp <= 20)),
            '(d) 集中の条件 G3 を外す': first_of(base & g2),
            '(e) 下の側の条件 G2 を外す': first_of(base & g3),
            '(f) G2 も G3 も外す（この範囲の天井）': first_of(base)}
    by_smh = {}
    for s in sorted(set(int(x) for x in smhp)):
        od = order(base & g2 & (smhp == s))
        if od:
            i = od[0]
            by_smh[f'SMH {s}'] = dict(形=names[i], P15π=r(Y[i, 1] * 100, 2), 期待の年率=r(Y[i, 0] * 100, 2), 年5パーセント未満=r(-Y[i, 2] * 100, 2),
                                      最大下落=r(Y[i, 3] * 100, 1), 半導体の連鎖=r(-Y[i, 11], 2), NVDA=r(-Y[i, 12], 2), G3を通る=bool(g3[i]), 数=len(od))
        else:
            by_smh[f'SMH {s}'] = dict(数=0)

    # ── 詳しい物差し（答え・今の形・R） ──
    DET = {K_NOW: NOWF, K_R: RF}
    if ans is not None and names[ans] not in (nm(NOWF), nm(RF)):
        DET[K_ANS] = forms[ans]
    keys = list(DET)
    Wd = W_of(DET.values())
    YDd, ed, bd, rzd, und = ymat(Wd)
    Vd = {v: ve(Wd, v) for v in ve_names}
    assets = sorted({a for f in DET.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(dict(DET), rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(dict(DET), rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vtd = N.variants(dict(DET), rows, chains, k4)[UC.W_CRASH]
    _, sim = U.tables()
    pi, _, _ = E.load_pi()
    reg, lkchk, detail = {}, {}, {}
    for j, k in enumerate(keys):
        t = tab[k]
        raw = t['_raw']
        if k in (K_NOW, K_ANS):
            reg[k] = dict(P15=abs(float(ed['P15'][j]) - raw['P15']), 平均=abs(float(ed['mean_pi'][j]) - raw['mean_pi']),
                          最大下落=abs(float(ed['mdd'][j]) - raw['mdd']), 感度の主=abs(vtd[k]['main']['mean_pi'] - raw['mean_pi']),
                          実績の割合と_past20=abs(float(rzd['share'][j]) - float(ed['past20'][j])))
            lk, lo, hi = look_whole(DET[k])
            a, u, d = conc_arr(Wd[j:j + 1])
            lkchk[k] = dict(線形=dict(下限=round(float(a[0]), 3), 上限=round(float(a[0] + u[0]), 3), NVDA=round(float(d[0]), 4)),
                            lookthrough=dict(下限=lo, 上限=hi, NVDA=lk.get('NVDA（資産全体）'), 最大の1銘柄=lk.get('最大の1銘柄')),
                            一致=bool(lo is not None and abs(a[0] - lo) < 0.051 and abs(a[0] + u[0] - hi) < 0.051
                                    and abs(d[0] - lk['NVDA（資産全体）']) < 0.0051))
        q, pr_ = UC.upside(sim, raw, pi)
        a, u, d = conc_arr(Wd[j:j + 1])
        detail[k] = dict(
            形=DET[k], 名前=nm(DET[k]), 全体の比=whole(DET[k]), 物差し13={v: ydict(YDd[v][j]) for v in VERS},
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), 五パーセント未満=t['P5π（5%未満）'],
                   元本割れ=t['P0π（元本割れ）'], 最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'], 世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q),
            世界ごとの年率の今との差={w: round(t['世界ごとの年率'][w] - tab[K_NOW]['世界ごとの年率'][w], 2) for w in t['世界ごとの年率']},
            感度5本の今との差={N.VARS_JA[v]: round(100 * (vtd[k][v]['mean_pi'] - vtd[K_NOW][v]['mean_pi']), 3) for v in N.VARS},
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * bd['mean_pi'][j]), P15π=r(100 * bd['P15'][j]), 五パーセント未満=r(100 * bd['P5'][j]),
                     感度6本の今との差={v: r(100 * (Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][0]), 3) for v in ve_names}),
            実績=dict(年15パーセント以上の割合=r(100 * rzd['share'][j], 1), 年率の中央=r(100 * rzd['med'][j]), 最悪=r(100 * rzd['worst'][j])),
            集中=dict(半導体の連鎖_下限=round(float(a[0]), 2), 半導体の連鎖_上限=round(float(a[0] + u[0]), 2), NVDA=round(float(d[0]), 2)))
    ok_b = all(v < 1e-9 for x in reg.values() for v in x.values())
    ok_d = all(x['一致'] for x in lkchk.values())
    if not (ok_b and ok_d):
        raise SystemExit(f'回帰の検査(b)(c)(d)が通らない: {reg} {lkchk}')
    log('回帰の検査 (b)(c)(d) ✓')

    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/aim15_check.py',
        kind='参考（測って選ぶだけ・範囲・条件・選び方・確かめは道具の頭に固定し回す前にコミット）',
        question='あなたが今までの全てでなにを選ぶか教えて。リターン15％以上を狙うなら。',
        決まり=dict(目的='②年15%以上の確率 P15π を最大に', G1=f'NASDAQ100 ≥ {FLOOR}%', G2='③年5%未満 ≤ 今 ∧ ④最大下落 ≥ 今',
                 G3='⑫半導体の連鎖 ≤ R ∧ ⑬NVDA ≤ R', 上限=f'NASDAQ100 以外は1本{SAT_CAP}%まで', 確かめ='F1〜F3（相手は今の形）・上から30'),
        G1の算数=rc, 範囲=dict(形=int(len(G)), 測れた形=int(meas.sum())),
        今の形=dict(形=NOWF, 名前=nm(NOWF), 物差し13=got[K_NOW]), R=dict(形=RF, 名前=nm(RF), 物差し13=got[K_R]),
        主=main_res, 参考=refs, SMHの比ごとの最良_G1とG2だけ=by_smh, 詳しい物差し=detail, 世界の重み=pi,
        regression=dict(差=reg, 中身の検算=lkchk, 通過=True), 席=dict(社=seats, 一社=per, 半導体=c_semi), secs=round(time.time() - t0, 1))
    if write:
        with open(OUT, 'w') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        log('書いた', OUT, f'{time.time() - t0:.0f}s')
        a_ = main_res.get('答え')
        print(json.dumps(dict(条件を通った形=main_res.get('条件を通った形'), 決まり方=main_res.get('答えの決まり方'),
                              答え=(a_['名前'] if isinstance(a_, dict) else a_), 物差し=(a_['物差し'] if isinstance(a_, dict) else None)),
                         ensure_ascii=False, indent=1))
    return locals()   # 事後の診断（night/aim15_posthoc.py）が同じ部品を使うため。計算と出力は変えない


if __name__ == '__main__':
    main()
