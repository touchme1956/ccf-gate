#!/usr/bin/env python3
"""night/ndx45_smh25_check.py — 案「NASDAQ100 45 / SMH 25 / ITA 10 / FBT 10 / VBR 10」を今の形・枝の案・バランス案と同じ物差しで評価する（2026-11-23・参考・配分は変えない）

ユーザー「NASDAQ100 45 / SMH 25 / ITA 10 / FBT 10 / VBR 10 について評価して」
読み方（固定）: 5つの数字は合計100＝ETF 側の比で、個別株10%はそのまま（資産全体 NASDAQ100 40.5 / SMH 22.5 / ITA 9 / FBT 9 / VBR 9 / 個別株 10）。
  案は今の形（main の ETF 側 45 / 20 / 10 / 15 / 10）から **FBT の5を SMH へ**移した形＝今の形と枝の案 R（40 / 30 / 15 / 10 / 5）の間。
この道具は門・採点・配分（portfolio.json）・注文書に触れない（測るだけ）。
★測るもの・比べる相手・判定の決まりはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの: 今の形・R・バランス案の13の物差しと詳しい物差し（out/ndx_recon_check.json）／SMH の比ごとの最良（balance_check）／
    基準を今の形にした探し直しの上位3（どれも SMH 20）／ret_lean_check の「半導体を増やすほど物差しは上と言う」／
    best15_fbt_why（FBT で15%以上の確率が上がる分の約3分の2はぶれ）。
  見ていないもの: 案そのものの数字と、下の「同じ5の別の使い方」6通りの数字。

形（ETF 側・個別株10%は別）:
  今の形（main）  QQQM 45 / SMH 20 / ITA 10 / FBT 15 / VBR 10（origin/main の portfolio.json と照合・違えば止まる）
  案（ユーザー）  QQQM 45 / SMH 25 / ITA 10 / FBT 10 / VBR 10
  R（枝の案）     QQQM 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5（枝の portfolio.json と照合・違えば止まる）
  バランス案      QQQM 40 / SMH 15 / FBT 20 / VBR 25
  同じ5の別の使い方（参考・判定に使わない）:
    SMH を25にする出す元を替える3通り（今の形から NASDAQ100・ITA・VBR の5を SMH へ。FBT から＝案）
    FBT を10にする行き先を替える3通り（今の形の FBT の5を NASDAQ100・ITA・VBR へ。SMH へ＝案）
測るもの（beat_ret_check・ndx_recon_check と同じ関数・同じ値）:
  13の物差し: 元の物差し ①期待の年率 ②年15%以上の確率 P15π ③年5%未満の確率 ④最大下落 ⑤最悪の世界の年率／
    業種の基礎率の物差し（主）⑥平均 ⑦5%未満／100年の代用 ⑧30年の積立の市場との比の中央 ⑨同・最悪
    （V1＝NASDAQ100 の入れ替えを数えた写し・V0＝数えない写しの両方）／
    実績（2000-09〜の転がる20年の毎月の積立）⑩年率の中央 ⑪年15%以上の窓の割合／
    集中（資産全体＝ETF 側×0.9＋個別株10%・席5社×2%）⑫半導体の連鎖（下限）⑬NVDA
  詳しい物差し: 年20%以上の確率・元本割れ・ぶれ・世界ごとの年率・内部収益率の分位・円の枠・基礎率の感度6本・感度5本・実績の最悪・
    中身の集中（線形と lookthrough.py の両方）
判定の決まり（比べる相手は今の形・結果を見る前に固定）:
  J1 「今を超える」＝13の物差し（⑧⑨は V1。V0 でも同じか併記）のどれでも今を下回らず（向きをそろえた生の値で 今 − 1e-12 以上）、
     少なくとも1つで上回る（今 ＋ 1e-9 超）。
  確かめ3つ（ndx_recon_check の F1〜F3 と同じ式・相手を今の形に）:
     F1 感度5本（主・A2〔直近15年〕を外す・半導体の基礎率・分散の上乗せなし・共分散をA2の窓から）のすべてで 期待の年率 ≥ 今
     F2 業種の基礎率の感度6本すべてで 平均 ≥ 今 ∧ 5%未満 ≤ 今
     F3 円の枠（崩れあり）で 期待の年率 ≥ 今 ∧ 最大下落 ≥ 今
  判定（上から順に当てる）:
     (a) J1 を満たす → 「今より良い」
     (b) J1 は満たさないが F1・F2・F3 をすべて通る → 「今とほぼ同じか少し良い」（下回る物差しを名指しする）
     (c) F1 は通るが F2 か F3 が通らない → 「リターン寄りの入れ替え（好みの差）」＝期待の年率は前提を変えても上がるが、
         業種の基礎率か円の守りでは下がる
     (d) F1 が通らない → 「上乗せは前提しだい」＝期待の年率が上がるのは一部の前提だけ
  私の勧めへのつなぎ方（固定）: (a)(b) なら案を勧める。(c)(d) なら 2026-11-23 の総合の答え（main の形のまま）を変えない
     ——(c) は「リターンを優先するなら筋が通る中間の形」、(d) は「上がる根拠が弱い」と添える。
併せて出す（判定に使わない）:
  今から R への道のりの何割か＝各物差しで（案 − 今）÷（R − 今）（R と今の差が表示の桁で0の物差しは出さない）／
  上乗せの出どころ＝世界ごとの年率の差（A1 直近26年・A2 直近15年・B 100年の平均・C JPM・D アナリスト）と世界の重み π／
  13の物差しごとの 上回る・同じ・下回る（「同じ」＝表示の桁に丸めて同じ値）／同じ5の別の使い方6通りの13の物差しと今との差／
  集中の目安（ETF 側を NASDAQ100 だけにした形の半導体の連鎖・S&P500）
回帰の検査（どれかが外れれば止める）:
  (a) Fast が measure と 1e-9 以内（今の形・案）(b) 感度の主が measure と 1e-9 以内 (c) 実績の割合が past20 と一致
  (d) 今の形・R・バランス案の13の物差し（V0・V1）と今の形・R の詳しい物差し（元・基礎率・実績・集中）が out/ndx_recon_check.json と一致
  (e) 線形の半導体の連鎖・NVDA が lookthrough.py（資産全体で渡す）と一致（今の形・案・半導体 ±0.051・NVDA ±0.0051）
⚠ 限界: 5%の入れ替えの差は雑音に近い（1e-9 の差でも「上回る」に数える）／未来の世界は予想・分散の上乗せは仮定／
  実績は一つの時代（テックと半導体が勝った26年）／100年の代用の窓は1966年以降・FBT の写しは医薬品の業種／
  中身は 2026-08〜10 の写し／税と NISA の枠・1株単位の買い方は物差しに入らない／個別株10%は集中にだけ数える（席5社×2%）
使い方: python3 night/ndx45_smh25_check.py → out/ndx45_smh25_check.json（約1分）
"""
import contextlib, io, json, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx45_smh25_check.json')
REFJ = os.path.join(BASE, 'out', 'ndx_recon_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import beat_ret_check as BT  # noqa: E402
import ndx_recon_check as NR  # noqa: E402

SIX, RF, NOWF, BALF = NR.SIX, NR.RF, NR.NOWF, NR.BALF
PLAN = {'QQQM': 45, 'SMH': 25, 'ITA': 10, 'FBT': 10, 'VBR': 10}
CASTLE_PCT, K = NR.CASTLE_PCT, NR.K
EPS, GAIN = NR.EPS, NR.GAIN
YJA, YSIGN, YSCALE, YDEC = NR.YJA, NR.YSIGN, NR.YSCALE, NR.YDEC
nm, whole, r = NR.nm, NR.whole, NR.r
K_NOW, K_PLAN, K_R, K_BAL = '今の形（main）', '案（ユーザー）', 'R（枝の案）', 'バランス案'
VERS = ('V0', 'V1')
JA = {'QQQM': 'NASDAQ100'}


def log(*a):
    print('[ndx45_smh25]', *a, file=sys.stderr, flush=True)


def move(f, a, b, x=5):
    g = dict(f)
    g[a] = g.get(a, 0) - x
    g[b] = g.get(b, 0) + x
    if min(g.values()) < 0:
        raise SystemExit(f'負の比になった: {g}')
    return {k: v for k, v in g.items() if v}


ALT = {}
for _s in ('QQQM', 'ITA', 'VBR'):
    ALT[f'SMH 25・出す元 {JA.get(_s, _s)}'] = move(NOWF, _s, 'SMH')
for _d in ('QQQM', 'ITA', 'VBR'):
    ALT[f'FBT 10・行き先 {JA.get(_d, _d)}'] = move(NOWF, 'FBT', _d)


def main():
    t0 = time.time()
    if move(NOWF, 'FBT', 'SMH') != PLAN:
        raise SystemExit('案が「今の形の FBT の5を SMH へ」と違う')
    live = json.loads(subprocess.run(['git', 'show', 'origin/main:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    brt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    for k, t, f in [(K_NOW, live, NOWF), (K_R, brt, RF)]:
        w, cp = BT.etf_side(t)
        if not BT.same(w, f) or cp != CASTLE_PCT:
            raise SystemExit(f'{k} が正本と違う: {w} 個別株 {cp}')

    import lookthrough as L
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import bestpf_eval as E
    import ndx_swap_check as N
    import sp500_compare as SPC
    ref = json.load(open(REFJ))
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = list(BR.POOL)
    for c in SIX:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
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

    # ── 中身（半導体・NVDA）の割合（ndx_recon_check と同じ出所・6本はどれも lookthrough の中身がある） ──
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
        with np.errstate(invalid='ignore'):
            lo = c_semi + K * np.where(used, Wn * sv[None, :], 0.0).sum(axis=1)
            un = K * np.where(used, Wn * uv[None, :], 0.0).sum(axis=1)
            nd = c_nvda + K * np.where(used, Wn * nv[None, :], 0.0).sum(axis=1)
        if (used & np.isnan(sv)[None, :]).any():
            raise SystemExit('中身の無い本を含む形がある')
        return lo, un, nd

    N.CASTLE_ARG = ','.join(f'{s}={per:g}' for s in seats)
    for c in SIX:
        N.NET_ARG[c] = c

    def look_whole(f):
        lk = N.lookthrough({c: v * K for c, v in f.items() if v})
        m = re.match(r'([\d.]+)〜([\d.]+)%', lk.get('半導体の連鎖（下限〜上限）', ''))
        return lk, (float(m.group(1)) if m else None), (float(m.group(2)) if m else None)

    def ymat(A):
        """13の物差し（向きをそろえて高いほど良い）。⑧⑨は版ごと"""
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
            cc = cts[v].eval(A)
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

    # ── 測る ──
    FORMS = {K_NOW: NOWF, K_PLAN: PLAN, K_R: RF, K_BAL: BALF, **ALT}
    keys = list(FORMS)
    jn, jp, jr = keys.index(K_NOW), keys.index(K_PLAN), keys.index(K_R)
    Wd = W_of(FORMS.values())
    YD, ed, bd, rzd, und = ymat(Wd)
    if any(np.isnan(YD[v]).any() for v in VERS):
        raise SystemExit('測れない形がある')
    Vd = {v: ve(Wd, v) for v in ve_names}
    assets = sorted({a for f in FORMS.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    ch_jpy, _ = U.jpy_chains(chains)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(dict(FORMS), rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(dict(FORMS), rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vtd = N.variants(dict(FORMS), rows, chains, k4)[UC.W_CRASH]
    _, sim = U.tables()
    pi, _, _ = E.load_pi()
    log('測った', len(keys), '形', f'{time.time() - t0:.0f}s')

    # ── 回帰の検査 ──
    reg = {}
    for k, j in ((K_NOW, jn), (K_PLAN, jp)):
        raw = tab[k]['_raw']
        reg[k] = dict(P15=abs(float(ed['P15'][j]) - raw['P15']), 平均=abs(float(ed['mean_pi'][j]) - raw['mean_pi']),
                      最大下落=abs(float(ed['mdd'][j]) - raw['mdd']),
                      感度の主=abs(vtd[k]['main']['mean_pi'] - raw['mean_pi']))
    reg['実績の割合と_past20'] = float(np.max(np.abs(rzd['share'] - ed['past20'])))
    ok_a = all(v < 1e-9 for k in (K_NOW, K_PLAN) for v in reg[k].values()) and reg['実績の割合と_past20'] < 1e-9
    y13 = {k: {v: ydict(YD[v][keys.index(k)]) for v in VERS} for k in (K_NOW, K_R, K_BAL)}
    want = {K_NOW: ref['今の形']['物差し13'], K_R: {v: ref['R']['物差し13'][v] for v in VERS},
            K_BAL: ref['詳しい物差し'][K_BAL]['物差し13']}
    ok_d = all(y13[k][v] == want[k][v] for k in y13 for v in VERS)

    def det_core(k, j):
        t = tab[k]
        a, u, d = conc_arr(Wd[j:j + 1])
        return dict(元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], 五パーセント未満=t['P5π（5%未満）'], 元本割れ=t['P0π（元本割れ）'],
                           最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'], 世界ごとの年率=t['世界ごとの年率']),
                    円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
                    基礎率=dict(平均=r(100 * bd['mean_pi'][j]), P15π=r(100 * bd['P15'][j]), 五パーセント未満=r(100 * bd['P5'][j])),
                    実績=dict(年15パーセント以上の割合=r(100 * rzd['share'][j], 1), 年率の中央=r(100 * rzd['med'][j]), 最悪=r(100 * rzd['worst'][j])),
                    集中=dict(半導体の連鎖_下限=round(float(a[0]), 2), 半導体の連鎖_上限=round(float(a[0] + u[0]), 2), NVDA=round(float(d[0]), 2)))
    bad = []
    for k in (K_NOW, K_R):
        mine, old = det_core(k, keys.index(k)), ref['詳しい物差し'][k]
        for sec, d in mine.items():
            for kk, v in d.items():
                if old[sec].get(kk) != v:
                    bad.append(f'{k}.{sec}.{kk}: {v} ≠ {old[sec].get(kk)}')
    lkchk = {}
    for k in (K_NOW, K_PLAN):
        lk, lo, hi = look_whole(FORMS[k])
        a, u, d = conc_arr(W_of([FORMS[k]]))
        lkchk[k] = dict(線形=dict(下限=round(float(a[0]), 3), 上限=round(float(a[0] + u[0]), 3), NVDA=round(float(d[0]), 4)),
                        lookthrough=dict(下限=lo, 上限=hi, NVDA=lk.get('NVDA（資産全体）'), 最大の1銘柄=lk.get('最大の1銘柄')),
                        一致=bool(lo is not None and abs(a[0] - lo) < 0.051 and abs(a[0] + u[0] - hi) < 0.051
                                and abs(d[0] - lk['NVDA（資産全体）']) < 0.0051))
    ok_e = all(x['一致'] for x in lkchk.values())
    if not (ok_a and ok_d and not bad and ok_e):
        raise SystemExit(f'回帰の検査が通らない: a={ok_a} {reg} d={ok_d} {y13} 詳しい={bad} e={lkchk}')
    log('回帰の検査 (a)〜(e) ✓')

    # ── 判定（相手は今の形） ──
    def versus(j, v):
        y, y0 = YD[v][j], YD[v][jn]
        ge, gt = y >= y0 - EPS, y > y0 + GAIN
        shown = [(r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]), r(y0[i] * YSIGN[i] * YSCALE[i], YDEC[i])) for i in range(13)]
        up = [YJA[i] for i in range(13) if gt[i] and shown[i][0] != shown[i][1]]
        dn = [YJA[i] for i in range(13) if not ge[i] and shown[i][0] != shown[i][1]]
        eq = [YJA[i] for i in range(13) if shown[i][0] == shown[i][1]]
        return dict(今を超える=bool(ge.all() and gt.any()), 下回る物差し_生の値=[YJA[i] for i in range(13) if not ge[i]],
                    上回る物差し_生の値=[YJA[i] for i in range(13) if gt[i]], 表示の桁で=dict(上回る=up, 同じ=eq, 下回る=dn),
                    今との差={YJA[i]: r((y[i] - y0[i]) * YSCALE[i] * YSIGN[i], max(YDEC[i], 2) + 1) for i in range(13)})

    def checks(k, j):
        d1 = {N.VARS_JA[v]: round(100 * (vtd[k][v]['mean_pi'] - vtd[K_NOW][v]['mean_pi']), 3) for v in N.VARS}
        f1 = all(vtd[k][v]['mean_pi'] >= vtd[K_NOW][v]['mean_pi'] - EPS for v in N.VARS)
        d2 = {v: dict(平均=round(100 * float(Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][jn]), 3),
                      五パーセント未満=round(100 * float(Vd[v]['P5'][j] - Vd[v]['P5'][jn]), 2)) for v in ve_names}
        f2 = all(Vd[v]['mean_pi'][j] >= Vd[v]['mean_pi'][jn] - EPS and Vd[v]['P5'][j] <= Vd[v]['P5'][jn] + EPS for v in ve_names)
        dj = 100 * (tj[k]['_raw']['mean_pi'] - tj[K_NOW]['_raw']['mean_pi'])
        dm = 100 * (tj[k]['_raw']['mdd'] - tj[K_NOW]['_raw']['mdd'])
        f3 = bool(dj >= -1e-10 and dm >= -1e-10)
        return dict(F1=bool(f1), F2=bool(f2), F3=f3, 感度5本の今との差=d1, 基礎率の感度6本の今との差=d2,
                    円の今との差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2)))

    def verdict(vs, fc):
        if vs['V1']['今を超える']:
            return '(a) 今より良い'
        if fc['F1'] and fc['F2'] and fc['F3']:
            return '(b) 今とほぼ同じか少し良い'
        if fc['F1']:
            return '(c) リターン寄りの入れ替え（好みの差）'
        return '(d) 上乗せは前提しだい'

    def detail(k, j):
        t = tab[k]
        q, pr_ = UC.upside(sim, t['_raw'], pi)
        d = det_core(k, j)
        d['元'].update(P20_道の束=pr_.get('P20（道の束）'), 内部収益率の分位=q)
        vs = {v: versus(j, v) for v in VERS}
        fc = checks(k, j)
        out = dict(形=FORMS[k], 名前=nm(FORMS[k]), 全体の比=whole(FORMS[k]), 物差し13={v: ydict(YD[v][j]) for v in VERS}, **d)
        if j != jn:
            out.update(今と比べる=vs, 確かめ=fc, 判定=verdict(vs, fc),
                       世界ごとの年率の今との差={w: round(t['世界ごとの年率'][w] - tab[K_NOW]['世界ごとの年率'][w], 2) for w in t['世界ごとの年率']})
        return out

    det = {k: detail(k, j) for j, k in enumerate(keys)}
    for k in (K_NOW, K_PLAN):
        det[k]['集中']['lookthrough'] = lkchk[k]['lookthrough']

    # 今から R への道のりの何割か
    path = {}
    for v in VERS:
        yp, y0, yR = YD[v][jp], YD[v][jn], YD[v][jr]
        path[v] = {}
        for i in range(13):
            a, b = r(y0[i] * YSIGN[i] * YSCALE[i], YDEC[i]), r(yR[i] * YSIGN[i] * YSCALE[i], YDEC[i])
            path[v][YJA[i]] = None if a == b else round(float((yp[i] - y0[i]) / (yR[i] - y0[i])), 2)

    # 集中の目安
    a1, u1, d1 = conc_arr(W_of([{'QQQM': 100}]))
    lines = dict(ETF側をNASDAQ100だけにした形=dict(半導体の連鎖=round(float(a1[0]), 2), NVDA=round(float(d1[0]), 2)),
                 SP500_VOO=dict(半導体の連鎖=round(sum(SPC.VOO_SEMI.values()), 2), NVDA=round(SPC.VOO_SEMI['NVDA'], 2)),
                 一本ごとの中身={c: dict(半導体=round(100 * share[c]['semi'], 2), NVDA=round(100 * share[c]['nvda'], 2)) for c in SIX})

    pj = det[K_PLAN]
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/ndx45_smh25_check.py',
        kind='参考（測って評価するだけ・比べる相手と判定の決まりは道具の頭に固定し回す前にコミット）',
        question='NASDAQ100 45 / SMH 25 / ITA 10 / FBT 10 / VBR 10 について評価して',
        読み方='ETF 側の比（合計100）・個別株10%はそのまま＝今の形（main）から FBT の5を SMH へ',
        案=dict(形=PLAN, 名前=nm(PLAN), 全体の比=whole(PLAN)),
        判定=dict(相手=K_NOW, 結果=pj['判定'], 今を超える_V1=pj['今と比べる']['V1']['今を超える'], 今を超える_V0=pj['今と比べる']['V0']['今を超える'],
                F1=pj['確かめ']['F1'], F2=pj['確かめ']['F2'], F3=pj['確かめ']['F3'],
                上回る=pj['今と比べる']['V1']['表示の桁で']['上回る'], 同じ=pj['今と比べる']['V1']['表示の桁で']['同じ'],
                下回る=pj['今と比べる']['V1']['表示の桁で']['下回る']),
        今からRへの道のりの何割か=path, 世界の重み=pi, 集中の目安=lines,
        詳しい物差し={k: det[k] for k in (K_NOW, K_PLAN, K_R, K_BAL)},
        同じ5の別の使い方={k: det[k] for k in ALT},
        regression=dict(差=reg, 中身の検算=lkchk, 通過=True),
        席=dict(社=seats, 一社=per, 半導体=c_semi), secs=round(time.time() - t0, 1))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('書いた', OUT, f'{time.time() - t0:.0f}s')
    print(json.dumps(out['判定'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
