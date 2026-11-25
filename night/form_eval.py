#!/usr/bin/env python3
"""night/form_eval.py — 名指しした形を同じ13の物差しで比べる（汎用・読むだけ・配分は変えない）

「この形は？」「A より B のほうがよいのでは？」に、毎回同じ物差し・同じ判定で答えるための道具。
門・採点・配分（portfolio.json）・注文書には触れない。
使い方: python3 night/form_eval.py out/form_eval_<key>_spec.json → out/form_eval_<key>.json（約30秒）
★形・比べる相手・読み方は spec（JSON）に書き、**回す前に spec をコミットする**（結果を見てから形や読み方を変えない）。
spec の欄:
  key・date・question（ユーザーの問いの原文）・reading（問いの読み方）・seen（回す前に知っていた数字）・
  forms｛名前: ｛本: ETF 側の比｝｝（合計は100でなくてよい＝正規化する・個別株10%は別）・
  pairs［［案の名前, 相手の名前］…］（案を相手と比べて判定する）・recommend（判定から勧めへのつなぎ方）
  今の形（main）と R（枝の案）は自動で足す（回帰の検査に使う・名前は固定）。
使える本: NASDAQ100（QQQM）・SMH・ITA・XLV・FBT・VBR と、100年の写しのある XLU・XLP・XLE・XLF・XLI・XLY・VUG・VTV・IJR・XLK・VOO。
  金・国債は方針（2026-11-04）で入れない。
物差しと判定（ndx45_smh25_check＝3497a7e と同じ・相手は pairs の2つ目）:
  13の物差し: 元の物差し ①期待の年率 ②年15%以上の確率 P15π ③年5%未満の確率 ④最大下落 ⑤最悪の世界の年率／業種の基礎率（主）⑥平均 ⑦5%未満／
    100年の代用 ⑧30年の積立の市場との比の中央 ⑨同・最悪（V1＝NASDAQ100 の入れ替えを数えた写し・V0＝数えない写し）／
    実績（2000-09〜の転がる20年の毎月の積立）⑩年率の中央 ⑪年15%以上の窓の割合／
    集中（資産全体＝ETF 側×0.9＋個別株10%・席5社×2%）⑫半導体の連鎖（下限）⑬NVDA
  J1 「相手を超える」＝13の物差し（⑧⑨は V1）のどれでも相手を下回らず（向きをそろえた生の値で 相手 − 1e-12 以上）、1つ以上で上回る（＋1e-9 超）
  F1 感度5本（主・A2〔直近15年〕を外す・半導体の基礎率・分散の上乗せなし・共分散をA2の窓から）のすべてで 期待の年率 ≥ 相手
  F2 業種の基礎率の感度6本すべてで 平均 ≥ 相手 ∧ 5%未満 ≤ 相手
  F3 円の枠（崩れあり）で 期待の年率 ≥ 相手 ∧ 最大下落 ≥ 相手
  判定（上から順に）: (a) J1 → 「相手より良い」／(b) F1・F2・F3 をすべて通る → 「相手とほぼ同じか少し良い」／
    (c) F1 は通るが F2 か F3 が通らない → 「リターン寄りの入れ替え（好みの差）」／(d) F1 が通らない → 「上乗せは前提しだい」
併せて出す（判定に使わない）: 年15%以上の確率を3通りで（元・直近15年の世界を外す・未来の3つの世界だけ）と基礎率の物差しの P15／
  年20%以上・元本割れ・ぶれ・分位・世界ごとの年率と相手との差／小型バリューの上乗せが消えたら（five_mix の S2 と同じ置き方）／
  中身の集中（線形・中身がそろう形は lookthrough.py でも）
一本ごとの値動き（説明用・判定に使わない）: 使った本の世界ごとの年率・ぶれ・最大下落・相関・期間ごとの年率・暦年
回帰の検査（どれかが外れれば止める）: (a) 今の形・R の13の物差し（V0・V1）が out/ndx_recon_check.json と一致
  (b) すべての形で Fast と感度の主が measure と 1e-9 以内・実績の割合が past20 と一致 (c) 線形の集中が lookthrough.py と一致（中身がそろう形）
⚠ 限界: 5%前後の入れ替えの差は雑音に近い（判定は 1e-9 の差でも上回る・下回るに数える）／未来の世界は予想・分散の上乗せは仮定／
  実績は一つの時代（テックと半導体が勝った26年）／100年の代用の窓は1966年以降・写しは業種の代わり／中身は 2026-08〜10 の写し／
  税と NISA の枠・1株単位の買い方・今の保有からの移り変わりは物差しに入らない／個別株10%は集中にだけ数える
"""
import contextlib, io, json, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
REFJ = os.path.join(BASE, 'out', 'ndx_recon_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import beat_ret_check as BT  # noqa: E402
import ndx_recon_check as NR  # noqa: E402

SIX, OTH, RF, NOWF = NR.SIX, NR.OTH, NR.RF, NR.NOWF
CASTLE_PCT, K = NR.CASTLE_PCT, NR.K
EPS, GAIN = NR.EPS, NR.GAIN
YJA, YSIGN, YSCALE, YDEC = NR.YJA, NR.YSIGN, NR.YSCALE, NR.YDEC
nm, r = NR.nm, NR.r
K_NOW, K_R = '今の形（main）', 'R（枝の案）'
VERS = ('V0', 'V1')
ALLOWED = SIX + OTH
BANNED = {'GDX', 'GDXJ', 'GLD', 'GLDM', 'IAU', 'TLT', 'EDV', 'TIP'}


def log(*a):
    print('[form_eval]', *a, file=sys.stderr, flush=True)


def main(spec_path):
    t0 = time.time()
    spec = json.load(open(spec_path))
    key = spec['key']
    out_path = os.path.join(BASE, 'out', f'form_eval_{key}.json')
    forms = {K_NOW: dict(NOWF), K_R: dict(RF)}
    for k, f in spec['forms'].items():
        f = {('QQQM' if c in ('NASDAQ100', 'IFREE-NDX', 'QQQ') else c): float(v) for c, v in f.items() if v}
        bad = [c for c in f if c not in ALLOWED or c in BANNED]
        if bad:
            raise SystemExit(f'使えない本: {k} {bad}')
        tot = sum(f.values())
        if tot <= 0 or min(f.values()) < 0:
            raise SystemExit(f'比がおかしい: {k} {f}')
        f = {c: 100 * v / tot for c, v in f.items()}          # 合計100にそろえる
        if k in (K_NOW, K_R) and not BT.same(f, forms[k]):
            raise SystemExit(f'{k} は固定の名前（spec の形が正本と違う）')
        forms[k] = f
    pairs = [tuple(p) for p in spec['pairs']]
    for a, b in pairs:
        if a not in forms or b not in forms:
            raise SystemExit(f'pairs の名前が forms に無い: {a} / {b}')
    # spec の main_ref: 自動で足す『今の形（main）』（NOWF）と照らす版。既定は origin/main。
    # main の配分が NOWF より新しくなった日は、NOWF が main だった時点の版を書いて回す（今の main は forms に名前をつけて足す）。
    ref_main = spec.get('main_ref', 'origin/main')
    live = json.loads(subprocess.run(['git', 'show', f'{ref_main}:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    brt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    stale = {}
    for k, t, f in [(K_NOW, live, NOWF), (K_R, brt, RF)]:
        w, cp = BT.etf_side(t)
        if not BT.same(w, f) or cp != CASTLE_PCT:
            stale[k] = dict(正本=w, 個別株=cp)
    if K_NOW in stale:
        raise SystemExit(f'今の形が origin/main の portfolio.json と違う（beat_ret_check の NOWF を直す）: {stale}')

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
    used = sorted({c for f in forms.values() for c in f})
    for c in used:
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

    def W_of(fl):
        return np.array([[f.get(c, 0) for c in P] for f in fl], dtype=np.float64)

    # ── 中身（半導体・NVDA）の割合（ndx_recon_check と同じ出どころ） ──
    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    prof_old = prof.get('etfs') or {}
    pn = json.load(open(os.path.join(BASE, 'out', 'etf_forward_profiles.json'))).get('etfs') or {}
    pn = {**pn, **U.R.EXTRA_PROFILES}
    av = U.X.av_profiles()
    share = {}
    for c in used:
        look, unk = L.explode({c: 1e6}, prof)
        if sum(unk.values()) / 1e6 < 0.5:
            share[c] = dict(semi=sum(v for t, v in look.items() if t in L.SEMI) / 1e6, unk=sum(unk.values()) / 1e6,
                            nvda=look.get('NVDA', 0.0) / 1e6, look=True)
            continue
        if c == 'VOO':
            share[c] = dict(semi=sum(SPC.VOO_SEMI.values()) / 100, unk=0.0, nvda=SPC.VOO_SEMI['NVDA'] / 100, look=False)
            continue
        if c in U.X.SECTOR_NEW and c in av:
            h = [(x[0], x[1]) for x in U.X.holdings_for_R(c, av[c]) if x and x[0] and x[0] != 'n/a']
        else:
            h = U.R.holdings_of(c, prof_old, pn)
        if not h:
            raise SystemExit(f'中身が取れない本: {c}')
        cov = sum(w for _, w in h)
        share[c] = dict(semi=sum(w for t, w in h if t.upper() in L.SEMI), unk=max(0.0, 1.0 - cov),
                        nvda=sum(w for t, w in h if t.upper() == 'NVDA'), look=False)

    def sarr(k):
        return np.array([share[c][k] if c in share else np.nan for c in P])
    sv, uv, nv = sarr('semi'), sarr('unk'), sarr('nvda')
    _, seats, _ = U.castle_copy()
    seats = list(seats)
    per = CASTLE_PCT / len(seats)
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')

    def conc_arr(A):
        Wn = 100 * A / A.sum(axis=1, keepdims=True)
        usedm = Wn > 0
        if (usedm & np.isnan(sv)[None, :]).any():
            raise SystemExit('中身の無い本を含む形がある')
        lo = c_semi + K * np.where(usedm, Wn * sv[None, :], 0.0).sum(axis=1)
        un = K * np.where(usedm, Wn * uv[None, :], 0.0).sum(axis=1)
        nd = c_nvda + K * np.where(usedm, Wn * nv[None, :], 0.0).sum(axis=1)
        return lo, un, nd

    N.CASTLE_ARG = ','.join(f'{s}={per:g}' for s in seats)
    for c in ALLOWED:
        N.NET_ARG[c] = c

    def look_whole(f):
        tot = sum(f.values())
        lk = N.lookthrough({c: 100 * v / tot * K for c, v in f.items() if v})
        m = re.match(r'([\d.]+)〜([\d.]+)%', lk.get('半導体の連鎖（下限〜上限）', ''))
        return lk, (float(m.group(1)) if m else None), (float(m.group(2)) if m else None)

    def ydict(y):
        return {YJA[i]: r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}

    ve_names = list(BR.VARS)

    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()

    # ── 測る ──
    keys = list(forms)
    ix = {k: j for j, k in enumerate(keys)}
    Wd = W_of(forms.values())
    e, b = fast.eval(Wd), fbr.eval(Wd, a0)
    rz = realized(Wd, fast)
    lo, un, nd = conc_arr(Wd)
    Y0 = np.full((len(keys), 13), np.nan)
    Y0[:, 0], Y0[:, 1], Y0[:, 2], Y0[:, 3], Y0[:, 4], Y0[:, 10] = e['mean_pi'], e['P15'], -e['P5'], e['mdd'], e['worst'], e['past20']
    Y0[:, 5], Y0[:, 6], Y0[:, 9], Y0[:, 11], Y0[:, 12] = b['mean_pi'], -b['P5'], rz['med'], -lo, -nd
    YD = {}
    for v in VERS:
        Z = Y0.copy()
        cc = cts[v].eval(Wd)
        Z[:, 7], Z[:, 8] = np.where(cc['ok'], cc['c30med'], np.nan), np.where(cc['ok'], cc['c30min'], np.nan)
        Z[~(e['ok'] & b['ok'])] = np.nan
        YD[v] = Z
    if any(np.isnan(YD[v]).any() for v in VERS):
        raise SystemExit(f'測れない形がある: {[k for j, k in enumerate(keys) if np.isnan(YD["V1"][j]).any()]}')
    Vd = {v: ve(Wd, v) for v in ve_names}
    assets = sorted(set(used) | {'VOO'})
    mega = U.mega_map(rows, assets)
    ch_jpy, _ = U.jpy_chains(chains)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(dict(forms), rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(dict(forms), rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vtd = N.variants(dict(forms), rows, chains, k4)[UC.W_CRASH]
    _, sim = U.tables()
    pi, _, _ = E.load_pi()
    log('測った', len(keys), '形', f'{time.time() - t0:.0f}s')

    # ── 一本ごとの値動き（説明用・判定に使わない。2026-11-23 に最初の結果を見たあとで足した＝事後） ──
    import math
    import etf_forward_combo as CB
    Rk = U.R
    A1_0, A2_0, END = 200009, 201110, 202609
    if len(Rk.months(A1_0, END)) != fast.T1 or len(Rk.months(A2_0, END)) != fast.T2:
        raise SystemExit('窓の月数が Fast と違う（一本ごとの値動きの窓を直す）')
    Cr = np.corrcoef(np.log1p(fast.G1[[P.index(c) for c in used]]))

    def geo1(c, m0, m1):
        ks = Rk.months(m0, m1)
        return float(np.expm1(np.log1p(np.array([chains[c][m] for m in ks])).sum() * 12 / len(ks)))
    PER = [(A1_0, 200605, '2000-09〜2006-05'), (200606, 201109, '2006-06〜2011-09'), (A2_0, 201507, '2011-10〜2015-07'),
           (201508, END, '2015-08〜2026-09'), (202110, END, '直近5年（2021-10〜2026-09）'), (201610, END, '直近10年（2016-10〜2026-09）'),
           (A2_0, END, '直近15年（2011-10〜2026-09）'), (A1_0, END, '直近26年（2000-09〜2026-09）')]
    single = {}
    for a_, c in enumerate(used):
        i = P.index(c)
        ps = CB.path_stats(fast.G1[i][None, :], fast.T1)
        single[c] = dict(
            世界ごとの年率=dict(A1=r(100 * rows[c]['A1']), A2=r(100 * (float(np.expm1(np.log1p(fast.G2[i]).sum() * 12 / fast.T2)) + float(fast.adj[i]))),
                         B=r(100 * rows[c]['B']), C=r(100 * rows[c]['C']), D=r(100 * float(np.expm1(fast.lD[i])))),
            ぶれ=r(100 * math.sqrt(fast.S1[i, i]), 1), 最大下落=r(100 * float(ps[2][0]), 1),
            相関={d: round(float(Cr[a_, b_]), 2) for b_, d in enumerate(used) if d != c},
            期間ごとの年率={lab: r(100 * geo1(c, m0, m1)) for m0, m1, lab in PER},
            暦年={str(y): r(100 * float(np.prod([1 + chains[c][m] for m in Rk.months(y * 100 + 1, y * 100 + 12)]) - 1), 1) for y in range(2001, 2026)},
            代わりの系列はこの月の前まで=rows[c].get('proxy_until'))

    # ── 小型バリューの上乗せなし（S2） ──
    sv_off = None
    if 'VBR' in P and 'VOO' in P:
        iv, ivoo = P.index('VBR'), P.index('VOO')
        bx = 0.5 * float(rows['VBR']['B_X'])
        lB0, lC0, lD0 = fast.lB.copy(), fast.lC.copy(), fast.lD.copy()
        gB0, gC0, gD0 = fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy()
        try:
            fast.lB[iv] = np.log1p(np.expm1(lB0[iv]) - bx)
            fast.lC[iv], fast.lD[iv] = lC0[ivoo], lD0[ivoo]
            e2 = fast.eval(Wd)
            fbr.gB[iv] -= bx
            fbr.gC[iv], fbr.gD[iv] = fbr.gC[ivoo], fbr.gD[ivoo]
            b2 = fbr.eval(Wd, a0)
        finally:
            fast.lB, fast.lC, fast.lD = lB0, lC0, lD0
            fbr.gB, fbr.gC, fbr.gD = gB0, gC0, gD0
        if float(np.max(np.abs(fast.eval(Wd)['P15'] - e['P15']))) > 1e-12:
            raise SystemExit('上乗せを戻したあとの値が元と違う')
        sv_off = dict(e=e2, b=b2, 引いた上乗せ=round(100 * bx, 2))

    # ── 回帰の検査 ──
    reg = {}
    got = {k: {v: ydict(YD[v][ix[k]]) for v in VERS} for k in (K_NOW, K_R)}
    want = {K_NOW: ref['今の形']['物差し13'], K_R: {v: ref['R']['物差し13'][v] for v in VERS}}
    ok_a = all(got[k][v] == want[k][v] for k in got for v in VERS)
    for k in keys:
        raw = tab[k]['_raw']
        j = ix[k]
        reg[k] = dict(P15=abs(float(e['P15'][j]) - raw['P15']), 平均=abs(float(e['mean_pi'][j]) - raw['mean_pi']),
                      最大下落=abs(float(e['mdd'][j]) - raw['mdd']), 感度の主=abs(vtd[k]['main']['mean_pi'] - raw['mean_pi']),
                      実績の割合と_past20=abs(float(rz['share'][j]) - float(e['past20'][j])))
    ok_b = all(v < 1e-9 for x in reg.values() for v in x.values())
    lkchk = {}
    for k in keys:
        f = forms[k]
        if not all(share[c]['look'] for c in f):
            lkchk[k] = dict(一致=None, 理由='lookthrough に中身の無い本を含む（線形だけ）')
            continue
        lk, l0, h0 = look_whole(f)
        j = ix[k]
        lkchk[k] = dict(線形=dict(下限=round(float(lo[j]), 3), 上限=round(float(lo[j] + un[j]), 3), NVDA=round(float(nd[j]), 4)),
                        lookthrough=dict(下限=l0, 上限=h0, NVDA=lk.get('NVDA（資産全体）'), 最大の1銘柄=lk.get('最大の1銘柄')),
                        一致=bool(l0 is not None and abs(lo[j] - l0) < 0.051 and abs(lo[j] + un[j] - h0) < 0.051
                                and abs(nd[j] - lk['NVDA（資産全体）']) < 0.0051))
    ok_c = all(x['一致'] is not False for x in lkchk.values())
    if not (ok_a and ok_b and ok_c):
        raise SystemExit(f'回帰の検査が通らない: a={ok_a} {got} b={ok_b} {reg} c={lkchk}')
    log('回帰の検査 (a)(b)(c) ✓')

    # ── 形ごとの詳しい物差し ──
    def detail(k):
        j = ix[k]
        t = tab[k]
        q, pr_ = UC.upside(sim, t['_raw'], pi)
        tot = sum(forms[k].values())
        d = dict(
            形=nm(forms[k]), ETF側の比={BT.JA.get(c, c): round(100 * v / tot, 2) for c, v in forms[k].items()},
            資産全体の比={**{BT.JA.get(c, c): round(100 * v / tot * K, 2) for c, v in forms[k].items()}, '個別株': CASTLE_PCT},
            物差し13={v: ydict(YD[v][j]) for v in VERS},
            十五パーセント以上の確率=dict(元=r(100 * e['P15'][j]), 直近15年の世界を外す=r(100 * e['P15_noA2'][j]), 未来の3つの世界だけ=r(100 * e['P15_fwd'][j]),
                                基礎率の物差し=r(100 * b['P15'][j])),
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), 五パーセント未満=t['P5π（5%未満）'], 元本割れ=t['P0π（元本割れ）'],
                   最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'], 世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q),
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * b['mean_pi'][j]), P15π=r(100 * b['P15'][j]), 五パーセント未満=r(100 * b['P5'][j])),
            実績=dict(年15パーセント以上の割合=r(100 * rz['share'][j], 1), 年率の中央=r(100 * rz['med'][j]), 最悪=r(100 * rz['worst'][j])),
            集中=dict(半導体の連鎖_下限=round(float(lo[j]), 2), 半導体の連鎖_上限=round(float(lo[j] + un[j]), 2), NVDA=round(float(nd[j]), 2),
                    lookthrough=lkchk[k].get('lookthrough')))
        if sv_off:
            d['小型バリューの上乗せなし'] = dict(期待の年率=[r(100 * e['mean_pi'][j]), r(100 * sv_off['e']['mean_pi'][j])],
                                     P15π=[r(100 * e['P15'][j]), r(100 * sv_off['e']['P15'][j])],
                                     五パーセント未満=[r(100 * e['P5'][j]), r(100 * sv_off['e']['P5'][j])],
                                     基礎率の平均=[r(100 * b['mean_pi'][j]), r(100 * sv_off['b']['mean_pi'][j])], 読み方='［上乗せあり, なし］')
        return d

    # ── 対ごとの判定 ──
    def judge(a, bname):
        j, jb = ix[a], ix[bname]
        vs = {}
        for v in VERS:
            y, y0 = YD[v][j], YD[v][jb]
            ge, gt = y >= y0 - EPS, y > y0 + GAIN
            shown = [(r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]), r(y0[i] * YSIGN[i] * YSCALE[i], YDEC[i])) for i in range(13)]
            vs[v] = dict(相手を超える=bool(ge.all() and gt.any()),
                         下回る物差し_生の値=[YJA[i] for i in range(13) if not ge[i]], 上回る物差し_生の値=[YJA[i] for i in range(13) if gt[i]],
                         表示の桁で=dict(上回る=[YJA[i] for i in range(13) if gt[i] and shown[i][0] != shown[i][1]],
                                    同じ=[YJA[i] for i in range(13) if shown[i][0] == shown[i][1]],
                                    下回る=[YJA[i] for i in range(13) if not ge[i] and shown[i][0] != shown[i][1]]),
                         相手との差={YJA[i]: r((y[i] - y0[i]) * YSCALE[i] * YSIGN[i], max(YDEC[i], 2) + 1) for i in range(13)})
        d1 = {N.VARS_JA[v]: round(100 * (vtd[a][v]['mean_pi'] - vtd[bname][v]['mean_pi']), 3) for v in N.VARS}
        f1 = all(vtd[a][v]['mean_pi'] >= vtd[bname][v]['mean_pi'] - EPS for v in N.VARS)
        d2 = {v: dict(平均=round(100 * float(Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][jb]), 3),
                      五パーセント未満=round(100 * float(Vd[v]['P5'][j] - Vd[v]['P5'][jb]), 2)) for v in ve_names}
        f2 = all(Vd[v]['mean_pi'][j] >= Vd[v]['mean_pi'][jb] - EPS and Vd[v]['P5'][j] <= Vd[v]['P5'][jb] + EPS for v in ve_names)
        dj = 100 * (tj[a]['_raw']['mean_pi'] - tj[bname]['_raw']['mean_pi'])
        dm = 100 * (tj[a]['_raw']['mdd'] - tj[bname]['_raw']['mdd'])
        f3 = bool(dj >= -1e-10 and dm >= -1e-10)
        if vs['V1']['相手を超える']:
            verdict = '(a) 相手より良い'
        elif f1 and f2 and f3:
            verdict = '(b) 相手とほぼ同じか少し良い'
        elif f1:
            verdict = '(c) リターン寄りの入れ替え（好みの差）'
        else:
            verdict = '(d) 上乗せは前提しだい'
        wa, wb = tab[a]['世界ごとの年率'], tab[bname]['世界ごとの年率']
        return dict(案=a, 相手=bname, 判定=verdict, 相手を超える_V1=vs['V1']['相手を超える'], 相手を超える_V0=vs['V0']['相手を超える'],
                    F1=bool(f1), F2=bool(f2), F3=f3, 比べ=vs, 感度5本の相手との差=d1, 基礎率の感度6本の相手との差=d2,
                    円の相手との差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2)),
                    世界ごとの年率の相手との差={w: round(wa[w] - wb[w], 2) for w in wa},
                    十五パーセント以上の確率の相手との差=dict(元=r(100 * (e['P15'][j] - e['P15'][jb])), 直近15年の世界を外す=r(100 * (e['P15_noA2'][j] - e['P15_noA2'][jb])),
                                              未来の3つの世界だけ=r(100 * (e['P15_fwd'][j] - e['P15_fwd'][jb])), 基礎率の物差し=r(100 * (b['P15'][j] - b['P15'][jb]))))

    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/form_eval.py', spec=os.path.relpath(spec_path, BASE),
        kind='参考（測って比べるだけ・形と比べる相手と読み方は spec に固定し回す前にコミット）',
        question=spec.get('question'), 読み方=spec.get('reading'), 勧めへのつなぎ方=spec.get('recommend'),
        Rの正本とのずれ=stale.get(K_R), 対ごとの判定=[judge(a, bn) for a, bn in pairs],
        形ごと={k: detail(k) for k in keys}, 世界の重み=pi,
        一本ごとの値動き_説明用=dict(注='判定に使わない。年率は配当込み・ETF の費用の後・NISA で戻らない配当の税の前（世界ごとの年率は物差しに入る値）。相関は直近26年の毎月の値動き', 本=single),
        一本ごとの中身={c: dict(半導体=round(100 * share[c]['semi'], 2), NVDA=round(100 * share[c]['nvda'], 2), 未取得=round(100 * share[c]['unk'], 2)) for c in used},
        regression=dict(差=reg, 中身の検算=lkchk, 通過=True), 席=dict(社=seats, 一社=per, 半導体=c_semi), secs=round(time.time() - t0, 1))
    with open(out_path, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('書いた', out_path, f'{time.time() - t0:.0f}s')
    for p_ in out['対ごとの判定']:
        print(json.dumps({k: p_[k] for k in ('案', '相手', '判定', 'F1', 'F2', 'F3')}, ensure_ascii=False))
        print('   上回る', p_['比べ']['V1']['表示の桁で']['上回る'])
        print('   下回る', p_['比べ']['V1']['表示の桁で']['下回る'])


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('使い方: python3 night/form_eval.py out/form_eval_<key>_spec.json')
    main(sys.argv[1])
