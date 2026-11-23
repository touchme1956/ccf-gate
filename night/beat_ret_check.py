#!/usr/bin/env python3
"""night/beat_ret_check.py — 枝の案（NASDAQ100 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5）を超える最高の形はあるか（2026-11-22・参考の測り）

ユーザー「NASDAQ100 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5これを超える最高のポートフォリオは？」
読み方（固定）:
  「超える」＝下の13の物差しのどれでもこの形（R）を下回らず、少なくとも1つで上回る（＝何も悪くせずに良くなる）。
  「最高」＝超える形の中で、期待の年率（元の物差しの π加重の平均）が最大の形。
この道具は門・採点・配分（portfolio.json）・注文書に触れない（測って選ぶだけ。配分に入れるのは別の手順）。
★物差し・範囲・選び方・確かめはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの: ret_seek_check（R・目的の上位10〔SMH 35 の形〕）と balance_check（SMH の比ごとの最良・バランス案）の数字、
  11月初めの best15・best15c（NASDAQ100 を芯にしない形＝SMH 40 / FBT 35 / ITA 20 / XLK 5 などが物差しで上だった）。
  ここで並べる13の物差しを R と突き合わせた結果（どの形が全部で下回らないか）は見ていない。

R（ETF 側・個別株10%は別）: QQQM 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5。枝の portfolio.json と照合・違えば止まる。
13の物差し（すべて ETF 側で測る・集中だけ資産全体）:
  元の物差し: ①期待の年率 ②年15%以上の確率 P15π ③年5%未満の確率（低いほど良い）④最大下落（浅いほど良い）⑤最悪の世界の年率
  業種の基礎率の物差し（主）: ⑥平均 ⑦5%未満（低いほど良い）
  100年の代用: ⑧30年の積立の市場との比の中央 ⑨同・最悪
  実績（2000-09〜の転がる20年の毎月の積立）: ⑩年率の中央 ⑪年15%以上の窓の割合
  集中（資産全体＝ETF 側×0.9＋個別株10%・席5社×2%）: ⑫半導体の連鎖（下限・低いほど良い）⑬NVDA（低いほど良い）
  「下回らない」＝生の値で R − 1e-12 以上（向きをそろえて）。「上回る」＝どれか1つで R ＋ 1e-9 を超える。
範囲（5%刻み・合計100・7本まで）:
  本: R の族の6本（QQQM・SMH・ITA・XLV・FBT・VBR）＋100年の写しのある物差しの本 11本（XLU・XLP・XLE・XLF・XLI・XLY・VUG・VTV・IJR・XLK・VOO）。
      金鉱株 GDX は方針（2026-11-04・金と国債は候補にしない）で外す。
  A 芯あり・同じ6本: NASDAQ100 が最大の1本（他のどの本以上）∧ 40〜60%（ret_seek_check と同じ5,196通り）
  B 芯あり・6本＋ほかの本を1本（その本は5%以上・11通りの本ごと）
  C 芯あり・6本＋B で「超える形」に入った本を同時に（2本以上が5%以上・多ければ B の最良の順に3本まで）。B に無ければ回さない
  D1 芯なし・同じ6本（NASDAQ100 0〜100%・最大でなくてよい）／D2 芯なし・6本＋ほかの本を1本／
  D3 芯なし・6本＋D2 で「超える形」に入った本を2本（D2 の最良の順に2本・どちらも5%以上）。D2 に2本無ければ回さない
  E（参考）⑫⑬（集中）を外した11の物差しで「超える」形（芯あり＝A〜C の中／芯なし＝D の中）
選び方: 超える形の中で ①期待の年率が最大。小数2桁（%）に丸めて同じなら ②P15π が高い → ④最大下落が浅い → 名前の順
最終の確かめ（選び方の順に上から30まで・最初に通った形がその範囲の答え・どれも通らなければ「確かめを通る形は無い」）:
  F1 感度5本（主・A2〔直近15年〕を外す・半導体の基礎率・分散の上乗せなし・共分散をA2の窓から）のすべてで 期待の年率 ≥ R
  F2 業種の基礎率の感度6本すべてで 平均 ≥ R ∧ 5%未満 ≤ R
  F3 円の枠（崩れあり）で 期待の年率 ≥ R ∧ 最大下落 ≥ R
芯あり（A〜C）に超える形が無いとき: 「芯を保つ限り超える形は無い」とし、併せて
  近い形＝期待の年率 ≥ R ∧ 半導体 ≤ R の形の中で、下回った物差しの下回り方（A の形の最大と最小の幅で割る）の最大が最小の形
  （同じなら期待の年率が高い形）と、その形が下回る物差しを名指しする
併せて出す（判定に使わない）: 範囲ごとの数（形・期待の年率が R 以上・うち半導体が R 以下・超える形）／超える形の上位15／
  芯なしの NASDAQ100 の比ごとの最良（超える形の中で）／詳しい物差し（R・各範囲の答え・近い形・今の形〔main〕・バランス案・私の案）
半導体の中身の出どころ: out/etf_profiles.json（lookthrough.py と同じ）→ 無い本は物差しの保有（out/etf_forward_profiles.json・
  業種の SPDR は bestpf_ext の写し）→ VOO は sp500_compare の定数。⑫は下限（分かった保有だけ）で比べ、未取得の分は別に出す
  （VTV・IJR は保有の上位だけ＝未取得が15〜25%ある）。どこからも取れない本を含む形は ⑫⑬ を測れない（超える形にしない）
回帰の検査: (a) Fast が measure と 1e-9 以内（R・今の形）(b) 感度の主が measure と 1e-9 以内 (c) 実績の割合が past20 と一致
  (d) 表示の値が ret_seek・balance_check と一致（期待の年率 R 11.08・今 10.83 を ±0.051・P15π 28.5・26.75 を ±0.15）
  (e) 線形の半導体の連鎖・NVDA が lookthrough.py（資産全体で渡す）と一致（R・今の形・バランス案・XLK 入りの形・半導体 ±0.051・NVDA ±0.0051）
  (f) A の形が ret_seek_check.grid() と同じ集合。どれかが外れれば止める
⚠ 限界: 13の物差しを等しく「下回らない」と置いたのは私が決めた（物差しどうしは重なる）／未来の世界は予想・分散の上乗せは仮定／
  実績は一つの時代（テックと半導体が勝った26年）／100年の写しの NASDAQ100 は業種を固定した代わり（年1回の入れ替えを数えない＝NASDAQ100 に不利な向き）／
  芯なしの形は物差しの外の事情（つみたて投資枠で買えるのは NASDAQ100 の投資信託・こどもNISA と iDeCo が自動で NASDAQ100 を買う）を数えない／
  中身は 2026-08〜10 の写し／形どうしの差の多くは雑音に近い（1e-9 の差でも「上回る」に数える）／税と NISA の枠は物差しに入らない
使い方: python3 night/beat_ret_check.py → out/beat_ret_check.json
"""
import contextlib, functools, io, json, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'beat_ret_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import ret_seek_check as RS  # noqa: E402

SIX = list(RS.SIX)
OTH = ['XLU', 'XLP', 'XLE', 'XLF', 'XLI', 'XLY', 'VUG', 'VTV', 'IJR', 'XLK', 'VOO']
JA = {'QQQM': 'NASDAQ100'}
RF = {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'FBT': 10, 'VBR': 5}
NOWF = {'QQQM': 45, 'SMH': 20, 'ITA': 10, 'FBT': 15, 'VBR': 10}
BALF = {'QQQM': 40, 'SMH': 15, 'FBT': 20, 'VBR': 25}
BASEF = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
XTF = {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'FBT': 10, 'XLK': 10}
CASTLE_PCT, STEP, UNITS, KMAX = 10, 5, 20, 7
K = (100 - CASTLE_PCT) / 100
NDX_LO, NDX_HI = 8, 12
EPS, GAIN, TIE, NFIN, NTOP = 1e-12, 1e-9, 1e-4, 30, 15
CH1, CH2 = 40000, 20000
K_R, K_NOW, K_BAL, K_BASE = 'R（枝の案）', '今の形（main）', 'バランス案', '私の案（11-22 の前）'
YJA = ['①期待の年率', '②年15%以上の確率', '③年5%未満の確率', '④最大下落', '⑤最悪の世界の年率', '⑥基礎率の平均', '⑦基礎率の5%未満',
       '⑧100年の30年の中央', '⑨100年の30年の最悪', '⑩実績の年率の中央', '⑪実績の年15%以上の割合', '⑫半導体の連鎖（下限）', '⑬NVDA']
YSIGN = np.array([1, 1, -1, 1, 1, 1, -1, 1, 1, 1, 1, -1, -1], dtype=np.float64)
YSCALE = np.array([100, 100, 100, 100, 100, 100, 100, 1, 1, 100, 100, 1, 1], dtype=np.float64)
YDEC = [2, 2, 2, 1, 2, 2, 2, 3, 3, 2, 1, 2, 2]
CHEAP, SLOW, CONC = [0, 1, 2, 3, 4, 5, 6, 10], [7, 8, 9], [11, 12]
NOCONC = CHEAP + SLOW
SHOWN = {K_R: (11.08, 28.5), K_NOW: (10.83, 26.75)}


def log(*a):
    print('[beat_ret]', *a, file=sys.stderr, flush=True)


def nm(f):
    return ' / '.join(f'{JA.get(c, c)} {f[c]:g}' for c in SIX + OTH if f.get(c))


def whole(f):
    return {**{JA.get(c, c): round(f[c] * K, 2) for c in SIX + OTH if f.get(c)}, '個別株': CASTLE_PCT}


def r(x, d=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), d)


@functools.lru_cache(maxsize=None)
def comps(total, parts):
    """total を parts 個の非負整数に分ける全通り"""
    if parts == 1:
        return np.array([[total]], dtype=np.int16)
    out = []
    for first in range(total + 1):
        rest = comps(total - first, parts - 1)
        out.append(np.hstack([np.full((len(rest), 1), first, dtype=np.int16), rest]))
    return np.vstack(out)


def grid_of(n_extra, core, min_extra=None):
    """6本＋n_extra 本。core なら列0（NASDAQ100）が 8〜12 かつ他のどの本以上。追加の本は min_extra 本以上が1単位以上・7本まで"""
    G = comps(UNITS, 6 + n_extra)
    m = (G > 0).sum(axis=1) <= KMAX
    if core:
        m &= (G[:, 0] >= NDX_LO) & (G[:, 0] <= NDX_HI) & (G[:, 1:] <= G[:, [0]]).all(axis=1)
    if n_extra:
        need = n_extra if min_extra is None else min_extra
        m &= (G[:, 6:] > 0).sum(axis=1) >= need
    return G[m]


def etf_side(tgt):
    w = {('QQQM' if k == 'IFREE-NDX' else k): float(v) for k, v in tgt['ami_weights'].items() if v}
    tot = sum(w.values())
    return {k: 100 * v / tot for k, v in w.items()}, float(tgt.get('shiro_castle_pct') or 0)


def same(w, f):
    return all(abs(w.get(k, 0) - f.get(k, 0)) < 1e-6 for k in set(w) | set(f))


def main():
    t0 = time.time()
    live = json.loads(subprocess.run(['git', 'show', 'origin/main:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    brt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    for k, t, f in [(K_NOW, live, NOWF), (K_R, brt, RF)]:
        w, cp = etf_side(t)
        if not same(w, f) or cp != CASTLE_PCT:
            raise SystemExit(f'{k} が正本と違う: {w} 個別株 {cp}')

    import lookthrough as L
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import bestpf_eval as E
    import etf_forward_combo as CB
    import ndx_swap_check as N
    import sp500_compare as SPC
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = list(BR.POOL)
    for c in SIX + OTH:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    adj = {k: BR.adj_vector(vec, st, rt, P)[0] for k, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    if not all(cent.has[P.index(c)] for c in SIX + OTH):
        raise SystemExit('100年の写しが無い本がある')

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    # ── 中身（半導体・NVDA）の割合 ──
    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    prof_old = prof.get('etfs') or {}
    pn = json.load(open(os.path.join(BASE, 'out', 'etf_forward_profiles.json'))).get('etfs') or {}
    pn = {**pn, **U.R.EXTRA_PROFILES}
    av = U.X.av_profiles()
    share = {}
    for c in SIX + OTH:
        look, unk = L.explode({c: 1e6}, prof)
        if sum(unk.values()) / 1e6 < 0.5:
            share[c] = dict(semi=sum(v for t, v in look.items() if t in L.SEMI) / 1e6, unk=sum(unk.values()) / 1e6,
                            nvda=look.get('NVDA', 0.0) / 1e6, src='out/etf_profiles.json（lookthrough.py と同じ）', look=True)
            continue
        if c == 'VOO':
            share[c] = dict(semi=sum(SPC.VOO_SEMI.values()) / 100, unk=0.0, nvda=SPC.VOO_SEMI['NVDA'] / 100,
                            src=f'sp500_compare の定数（{SPC.VOO_ASOF}・SEMI に入る社だけ写した）', look=False)
            continue
        if c in U.X.SECTOR_NEW and c in av:
            h = [(x[0], x[1]) for x in U.X.holdings_for_R(c, av[c]) if x and x[0] and x[0] != 'n/a']
            src = 'bestpf_ext の写し（Alpha Vantage）'
        else:
            h = U.R.holdings_of(c, prof_old, pn)
            src = 'out/etf_forward_profiles.json'
        if not h:
            share[c] = None
            continue
        cov = sum(w for _, w in h)
        share[c] = dict(semi=sum(w for t, w in h if t.upper() in L.SEMI), unk=max(0.0, 1.0 - cov),
                        nvda=sum(w for t, w in h if t.upper() == 'NVDA'), src=src, look=False)
    sv = np.array([(share[c]['semi'] if c in share and share[c] else np.nan) if c in SIX + OTH else np.nan for c in P])
    uv = np.array([(share[c]['unk'] if c in share and share[c] else np.nan) if c in SIX + OTH else np.nan for c in P])
    nv = np.array([(share[c]['nvda'] if c in share and share[c] else np.nan) if c in SIX + OTH else np.nan for c in P])
    _, seats, _ = U.castle_copy()
    seats = list(seats)
    per = CASTLE_PCT / len(seats)
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')

    def conc_arr(A):
        """A: 形（単位は何でも・行ごとに正規化）→ 半導体の下限・未取得・NVDA（資産全体の%）"""
        Wn = 100 * A / A.sum(axis=1, keepdims=True)
        used = Wn > 0
        with np.errstate(invalid='ignore'):
            lo = c_semi + K * np.where(used, Wn * sv[None, :], 0.0).sum(axis=1)
            un = K * np.where(used, Wn * uv[None, :], 0.0).sum(axis=1)
            nd = c_nvda + K * np.where(used, Wn * nv[None, :], 0.0).sum(axis=1)
        bad = (used & np.isnan(sv)[None, :]).any(axis=1)
        lo[bad] = np.nan; un[bad] = np.nan; nd[bad] = np.nan
        return lo, un, nd

    N.CASTLE_ARG = ','.join(f'{s}={per:g}' for s in seats)
    for c in SIX + OTH:
        N.NET_ARG[c] = c

    def look_whole(f):
        if not all(share.get(c) and share[c]['look'] for c in f if f[c]):
            return None, None, None
        lk = N.lookthrough({c: v * K for c, v in f.items() if v})
        m = re.match(r'([\d.]+)〜([\d.]+)%', lk.get('半導体の連鎖（下限〜上限）', ''))
        return lk, (float(m.group(1)) if m else None), (float(m.group(2)) if m else None)

    # ── 評価 ──
    def ev_cheap(A):
        n = len(A)
        o = {k: np.empty(n) for k in ('mean_pi', 'P15', 'P5', 'mdd', 'worst', 'past20', 'bmean', 'bP5')}
        ok = np.zeros(n, bool)
        for s in range(0, n, CH1):
            W = A[s:s + CH1]
            e = fast.eval(W)
            b = fbr.eval(W, a0)
            for k in ('mean_pi', 'P15', 'P5', 'mdd', 'worst', 'past20'):
                o[k][s:s + CH1] = e[k]
            o['bmean'][s:s + CH1] = b['mean_pi']
            o['bP5'][s:s + CH1] = b['P5']
            ok[s:s + CH1] = e['ok'] & b['ok']
        o['ok'] = ok
        return o

    def ev_slow(A, idx):
        n = len(A)
        cm, cn, rm = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
        for s in range(0, len(idx), CH2):
            ii = idx[s:s + CH2]
            W = A[ii]
            cc = cent.eval(W)
            z = realized(W, fast)
            cm[ii] = np.where(cc['ok'], cc['c30med'], np.nan)
            cn[ii] = np.where(cc['ok'], cc['c30min'], np.nan)
            rm[ii] = z['med']
        return cm, cn, rm

    def ymat(A, need=None):
        """13の物差し（向きをそろえて高いほど良い）。need＝遅い物差しを測る行（None なら全部）"""
        ch = ev_cheap(A)
        lo, un, nd = conc_arr(A)
        Y = np.full((len(A), 13), np.nan)
        Y[:, 0], Y[:, 1], Y[:, 2], Y[:, 3], Y[:, 4] = ch['mean_pi'], ch['P15'], -ch['P5'], ch['mdd'], ch['worst']
        Y[:, 5], Y[:, 6], Y[:, 10] = ch['bmean'], -ch['bP5'], ch['past20']
        Y[:, 11], Y[:, 12] = -lo, -nd
        Y[~ch['ok']] = np.nan
        idx = np.arange(len(A)) if need is None else np.where(need(Y))[0]
        cm, cn, rm = ev_slow(A, idx)
        Y[:, 7], Y[:, 8], Y[:, 9] = cm, cn, rm
        Y[~ch['ok']] = np.nan
        return Y, un

    # ── 参照の形と回帰の検査 ──
    REF = {K_R: RF, K_NOW: NOWF}
    Wr = W_of(REF.values())
    er = fast.eval(Wr)
    assets0 = sorted({a for f in REF.values() for a in f} | {'VOO'})
    with contextlib.redirect_stdout(io.StringIO()):
        tab0 = U.measure(dict(REF), rows, chains, mega=U.mega_map(rows, assets0))[UC.W_CRASH]
        k40, _ = N.chips_adj(rows, assets0)
        vt0 = N.variants(dict(REF), rows, chains, k40)[UC.W_CRASH]
    reg = {}
    for j, k in enumerate(REF):
        raw = tab0[k]['_raw']
        reg[k] = dict(P15=abs(float(er['P15'][j]) - raw['P15']), 平均=abs(float(er['mean_pi'][j]) - raw['mean_pi']),
                      最大下落=abs(float(er['mdd'][j]) - raw['mdd']), 感度の主の平均=abs(vt0[k]['main']['mean_pi'] - raw['mean_pi']))
    rz0 = realized(Wr, fast)
    reg['実績の割合と_past20'] = float(np.max(np.abs(rz0['share'] - er['past20'])))
    shown = {k: dict(平均=tab0[k]['π加重の平均の年率'], P15π=tab0[k]['P15π']) for k in REF}
    ok_num = all(v < 1e-9 for k in REF for v in reg[k].values()) and reg['実績の割合と_past20'] < 1e-9
    ok_shown = all(abs(shown[k]['平均'] - SHOWN[k][0]) < 0.051 and abs(shown[k]['P15π'] - SHOWN[k][1]) < 0.15 for k in REF)
    lkchk = {}
    for k, f in {K_R: RF, K_NOW: NOWF, K_BAL: BALF, 'XLK 入りの形': XTF}.items():
        lk, lo, hi = look_whole(f)
        a, u, d = conc_arr(W_of([f]))
        lkchk[k] = dict(線形=dict(下限=round(float(a[0]), 3), 上限=round(float(a[0] + u[0]), 3), NVDA=round(float(d[0]), 4)),
                        lookthrough=dict(下限=lo, 上限=hi, NVDA=(lk or {}).get('NVDA（資産全体）')),
                        一致=bool(lk and lo is not None and abs(a[0] - lo) < 0.051 and abs(a[0] + u[0] - hi) < 0.051
                                and abs(d[0] - lk['NVDA（資産全体）']) < 0.0051))
    GA = grid_of(0, True)
    ok_grid = {tuple(int(x) for x in row) for row in GA} == {tuple(int(x) for x in row) for row in RS.grid()}
    if not (ok_num and ok_shown and all(v['一致'] for v in lkchk.values()) and ok_grid):
        raise SystemExit(f'回帰の検査が通らない: {reg} {shown} {lkchk} grid={ok_grid}')
    log('回帰の検査 ✓', shown)

    yR, uR = ymat(Wr[:1])
    yR = yR[0]
    if np.isnan(yR).any():
        raise SystemExit(f'R の物差しが測れない: {yR}')

    def ydict(y):
        return {YJA[i]: r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}

    def need_pre(Y):
        with np.errstate(invalid='ignore'):
            return (Y[:, CHEAP] >= yR[CHEAP] - EPS).all(axis=1)

    def need_near(Y):
        with np.errstate(invalid='ignore'):
            return need_pre(Y) | ((Y[:, 0] >= yR[0] - EPS) & (Y[:, 11] >= yR[11] - EPS))

    def fo(T, i):
        return {c: int(v) * STEP for c, v in zip(T['cols'], T['G'][i]) if v}

    def na(T, i):
        return nm(fo(T, i))

    def tier(G, cols, label, need):
        A = np.zeros((len(G), len(P)), dtype=np.float64)
        A[:, [P.index(c) for c in cols]] = G
        Y, un = ymat(A, need)
        del A
        with np.errstate(invalid='ignore'):
            ge = Y >= yR[None, :] - EPS
            gt = Y > yR[None, :] + GAIN
            dom = ge.all(axis=1) & gt.any(axis=1)
            domE = ge[:, NOCONC].all(axis=1) & gt[:, NOCONC].any(axis=1)
            hi_mean = Y[:, 0] >= yR[0] - EPS
            hi_mean_semi = hi_mean & (Y[:, 11] >= yR[11] - EPS)
        log(label, '形', len(G), '期待の年率が R 以上', int(hi_mean.sum()), 'うち半導体が R 以下', int(hi_mean_semi.sum()),
            '超える', int(dom.sum()), '集中を外して超える', int(domE.sum()))
        return dict(label=label, G=G, cols=cols, Y=Y, un=un, dom=dom, domE=domE,
                    counts=dict(形=len(G), 期待の年率がR以上=int(hi_mean.sum()), うち半導体がR以下=int(hi_mean_semi.sum()),
                                超える=int(dom.sum()), 集中を外して超える=int(domE.sum())), hi_mean_semi=hi_mean_semi)

    def okey(T, i):
        Y = T['Y']
        return (-round(float(Y[i, 0]) / TIE), -float(Y[i, 1]), -float(Y[i, 3]), na(T, i))

    def order(T, idx):
        return sorted([int(i) for i in idx], key=lambda i: okey(T, i))

    def brief(T, i):
        y = T['Y'][i]
        d = {YJA[k]: r((y[k] - yR[k]) * YSCALE[k] * YSIGN[k], max(YDEC[k], 2) + 1) for k in range(13)}
        worse = [YJA[k] for k in range(13) if not (y[k] >= yR[k] - EPS)]
        return dict(名前=na(T, i), 形=fo(T, i), 全体の比=whole(fo(T, i)), 範囲=T['label'], 物差し=ydict(y), R_との差=d,
                    下回る物差し=worse, 半導体の未取得=r(float(T['un'][i]), 2))

    ve_names = list(BR.VARS)

    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    ch_jpy, _ = U.jpy_chains(chains)

    def final(cands):
        """cands: [(T, i)] を選び方の順に。F1〜F3 を当て、最初に通った形と確かめた一覧を返す"""
        seen = []
        for s in range(0, min(len(cands), NFIN), 10):
            part = cands[s:s + 10]
            Fm = {K_R: RF, **{na(T, i): fo(T, i) for T, i in part}}
            assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
            with contextlib.redirect_stdout(io.StringIO()):
                k4, _ = N.chips_adj(rows, assets)
                vt = N.variants(Fm, rows, chains, k4)[UC.W_CRASH]
                tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets),
                               windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
            Wf = W_of(Fm.values())
            vres = {v: ve(Wf, v) for v in ve_names}
            for j, (T, i) in enumerate(part, start=1):
                k = na(T, i)
                d1 = {N.VARS_JA[v]: round(100 * (vt[k][v]['mean_pi'] - vt[K_R][v]['mean_pi']), 3) for v in N.VARS}
                f1 = all(vt[k][v]['mean_pi'] >= vt[K_R][v]['mean_pi'] - EPS for v in N.VARS)
                d2 = {v: dict(平均=round(100 * float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]), 3),
                              五パーセント未満=round(100 * float(vres[v]['P5'][j] - vres[v]['P5'][0]), 2)) for v in ve_names}
                f2 = all(vres[v]['mean_pi'][j] >= vres[v]['mean_pi'][0] - EPS and vres[v]['P5'][j] <= vres[v]['P5'][0] + EPS
                         for v in ve_names)
                dj = 100 * (tj[k]['_raw']['mean_pi'] - tj[K_R]['_raw']['mean_pi'])
                dm = 100 * (tj[k]['_raw']['mdd'] - tj[K_R]['_raw']['mdd'])
                f3 = bool(dj >= -1e-10 and dm >= -1e-10)
                seen.append(dict(**brief(T, i), F1=bool(f1), F2=bool(f2), F3=f3, 合否=bool(f1 and f2 and f3), 感度5本のRとの差=d1,
                                 基礎率の感度6本のRとの差=d2, 円のRとの差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2))))
                if f1 and f2 and f3:
                    return seen[-1], seen
        return None, seen

    def pick(tiers, key='dom', extra=None):
        """範囲（複数の tier）をまとめて選び方の順に → 最終の確かめ"""
        cands = []
        for T in tiers:
            m = T[key] if extra is None else (T[key] & extra(T))
            cands += [(T, i) for i in np.where(m)[0]]
        cands = [(T, int(i)) for T, i in cands]
        cands.sort(key=lambda p: okey(*p))
        ans, seen = final(cands)
        if not cands:
            verdict = '超える形は無い'
        else:
            verdict = ans if ans else '確かめを通る形は無い'
        return dict(超える形の数=len(cands), 上位=[brief(T, i) for T, i in cands[:NTOP]], 答え=verdict,
                    最終の確かめ=[dict(名前=x['名前'], 期待の年率=x['物差し'][YJA[0]], F1=x['F1'], F2=x['F2'], F3=x['F3'], 合否=x['合否']) for x in seen],
                    最終の確かめの詳細=seen[-1:] if ans else seen[:3])

    def helpful(tiers):
        best = {}
        for T in tiers:
            x = T['cols'][6]
            idx = np.where(T['dom'])[0]
            if len(idx):
                i = order(T, idx)[0]
                best[x] = (round(float(T['Y'][i, 0]) / TIE), float(T['Y'][i, 1]))
        return [x for x, _ in sorted(best.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))]

    # ── A〜C（芯あり） ──
    TA = tier(GA, SIX, 'A 芯あり・同じ6本', None)
    GB = grid_of(1, True)
    TB = [tier(GB, SIX + [x], f'B 芯あり・6本＋{x}', need_near) for x in OTH]
    hb = helpful(TB)
    TC = []
    if len(hb) >= 2:
        hs = hb[:3]
        TC = [tier(grid_of(len(hs), True, min_extra=2), SIX + hs, f'C 芯あり・6本＋{"・".join(hs)}', need_near)]
    core = [TA] + TB + TC
    # ── D（芯なし） ──
    TD1 = tier(grid_of(0, False), SIX, 'D1 芯なし・同じ6本', need_pre)
    GD2 = grid_of(1, False)
    TD2 = [tier(GD2, SIX + [x], f'D2 芯なし・6本＋{x}', need_pre) for x in OTH]
    hd = helpful(TD2)
    TD3 = []
    if len(hd) >= 2:
        TD3 = [tier(grid_of(2, False), SIX + hd[:2], f'D3 芯なし・6本＋{hd[0]}・{hd[1]}', need_pre)]
    free = [TD1] + TD2 + TD3

    res_core = pick(core)
    res_free = pick(free)
    res_core_E = pick(core, key='domE')
    res_free_E = pick(free, key='domE')
    jn = 0
    by_ndx = {}
    for u in range(0, UNITS + 1):
        cands = []
        for T in free:
            cands += [(T, i) for i in np.where(T['dom'] & (T['G'][:, jn] == u))[0]]
        if not cands:
            by_ndx[f'NASDAQ100 {u * STEP}'] = dict(超える形の数=0)
            continue
        cands = [(T, int(i)) for T, i in cands]
        cands.sort(key=lambda p: okey(*p))
        T, i = cands[0]
        by_ndx[f'NASDAQ100 {u * STEP}'] = dict(超える形の数=len(cands), 最良=brief(T, i))
    floors = {}
    for fl in (20, 30):
        floors[f'NASDAQ100 {fl}%以上'] = pick(free, extra=lambda T, fl=fl: T['G'][:, jn] * STEP >= fl)

    # ── 芯ありに超える形が無いとき: 近い形 ──
    near = None
    span = np.nanmax(TA['Y'], axis=0) - np.nanmin(TA['Y'], axis=0)
    cands = []
    for T in core:
        Y = T['Y']
        with np.errstate(invalid='ignore'):
            m = T['hi_mean_semi'] & ~np.isnan(Y).any(axis=1)
            sh = np.maximum(0.0, (yR[None, :] - Y)) / span[None, :]
        mx = sh.max(axis=1)
        for i in np.where(m)[0]:
            if na(T, i) == nm(RF):
                continue
            cands.append((round(float(mx[i]), 6), -round(float(Y[i, 0]) / TIE), na(T, i), T, int(i)))
    cands.sort(key=lambda t: t[:3])
    if cands:
        near = [dict(**brief(T, i), 下回り方の最大=mx_) for mx_, _, _, T, i in cands[:5]]
    top_mean = []
    cm = []
    for T in core:
        cm += [(T, int(i)) for i in np.where(T['hi_mean_semi'])[0] if na(T, int(i)) != nm(RF)]
    cm.sort(key=lambda p: okey(*p))
    top_mean = [brief(T, i) for T, i in cm[:10]]

    # ── 詳しい物差し ──
    DET = {K_R: RF}

    def add(label, x):
        if isinstance(x, dict) and x.get('形') and nm(x['形']) not in {nm(f) for f in DET.values()}:
            DET[label] = x['形']
    add('芯ありの答え', res_core['答え'])
    add('芯なしの答え', res_free['答え'])
    for k, v in floors.items():
        add(f'芯なし・{k}の答え', v['答え'])
    add('集中を外した芯ありの答え', res_core_E['答え'])
    add('集中を外した芯なしの答え', res_free_E['答え'])
    if near:
        add('芯ありで近い形', near[0])
    for k, f in [(K_NOW, NOWF), (K_BAL, BALF), (K_BASE, BASEF)]:
        DET[k] = f
    Wd = W_of(DET.values())
    Yd, und = ymat(Wd)
    ed, bd, cd, rzd = fast.eval(Wd), fbr.eval(Wd, a0), cent.eval(Wd), realized(Wd, fast)
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
    detail = {}
    for j, k in enumerate(DET):
        t = tab[k]
        q, pr_ = UC.upside(sim, t['_raw'], pi)
        lk, lo, hi = look_whole(DET[k])
        a, u, d = conc_arr(Wd[j:j + 1])
        detail[k] = dict(
            形=DET[k], 名前=nm(DET[k]), 全体の比=whole(DET[k]), 物差し13=ydict(Yd[j]),
            R_との差={YJA[i]: r((Yd[j, i] - yR[i]) * YSCALE[i] * YSIGN[i], max(YDEC[i], 2) + 1) for i in range(13)},
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), 五パーセント未満=t['P5π（5%未満）'],
                   元本割れ=t['P0π（元本割れ）'], 最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'],
                   世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q),
            感度5本のRとの差={N.VARS_JA[v]: round(100 * (vtd[k][v]['mean_pi'] - vtd[K_R][v]['mean_pi']), 3) for v in N.VARS},
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * bd['mean_pi'][j]), P15π=r(100 * bd['P15'][j]), 五パーセント未満=r(100 * bd['P5'][j]),
                     感度6本のRとの差={v: r(100 * (Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][0]), 3) for v in ve_names}),
            百年=dict(三十年の中央=r(cd['c30med'][j], 3), 三十年の最悪=r(cd['c30min'][j], 3)),
            実績=dict(年15パーセント以上の割合=r(100 * rzd['share'][j], 1), 年率の中央=r(100 * rzd['med'][j]), 最悪=r(100 * rzd['worst'][j])),
            集中=dict(半導体の連鎖_下限=round(float(a[0]), 2), 半導体の連鎖_上限=round(float(a[0] + u[0]), 2), NVDA=round(float(d[0]), 2),
                    lookthrough=(dict(半導体の連鎖=lk.get('半導体の連鎖（下限〜上限）'), NVDA=lk.get('NVDA（資産全体）'), 最大の1銘柄=lk.get('最大の1銘柄'))
                                 if lk else '中身が out/etf_profiles.json に無い本を含む＝線形の値だけ'),
                    城=f'{N.CASTLE_ARG}（席{len(seats)}社×{per:g}%）'))

    sp = json.load(open(os.path.join(BASE, 'out', 'sp500_compare.json')))['results']['中身の集中']['S&P500（VOO）']
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/beat_ret_check.py',
        kind='参考（測って選ぶだけ・物差し・範囲・選び方は道具の頭に固定し回す前にコミット）',
        question='NASDAQ100 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5これを超える最高のポートフォリオは？',
        reading='超える＝13の物差しのどれでも R を下回らず1つ以上で上回る／最高＝その中で期待の年率が最大',
        R=dict(形=RF, 名前=nm(RF), 全体の比=whole(RF), 物差し13=ydict(yR)),
        regression=dict(差=reg, 表示=shown, 中身の検算=lkchk, Aの形がret_seekと同じ=ok_grid, 通過=True),
        中身の割合={c: ({kk: (round(100 * vv, 3) if kk in ('semi', 'unk', 'nvda') else vv) for kk, vv in share[c].items()} if share[c] else '取れない')
                 for c in SIX + OTH},
        席=dict(社=seats, 一社=per, 半導体=c_semi),
        範囲ごとの数={T['label']: T['counts'] for T in core + free},
        Bで超える形に入った本=hb, D2で超える形に入った本=hd,
        芯あり=res_core, 芯なし=res_free, 芯なしでNASDAQ100の下限つき=floors, 芯なしのNASDAQ100の比ごとの最良=by_ndx,
        参考_集中を外した芯あり=res_core_E, 参考_集中を外した芯なし=res_free_E,
        芯ありで近い形=near, 芯ありで期待の年率がR以上かつ半導体がR以下の上位10=top_mean,
        詳しい物差し=detail,
        参考_SP500=dict(半導体の連鎖=sp.get('半導体の連鎖（lookthrough と同じ SEMI）'), NVDA=sp.get('NVDA'), 出所=sp.get('出所')),
        caveats=['13の物差しを等しく「下回らない」と置いたのは私が決めた（物差しどうしは重なる）', '未来の世界は予想・分散の上乗せは仮定',
                 '実績は一つの時代（テックと半導体が勝った26年）', '100年の写しの NASDAQ100 は業種を固定した代わり（NASDAQ100 に不利な向き）',
                 '芯なしの形は、つみたて投資枠・こどもNISA・iDeCo が NASDAQ100 を買う事情を数えない', '中身は 2026-08〜10 の写し',
                 '形どうしの差の多くは雑音に近い', '税と NISA の枠は物差しに入らない'],
        secs=round(time.time() - t0))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    log('→', OUT, '芯あり', res_core['答え'] if isinstance(res_core['答え'], str) else res_core['答え']['名前'],
        '／芯なし', res_free['答え'] if isinstance(res_free['答え'], str) else res_free['答え']['名前'], f'{out["secs"]}s')


if __name__ == '__main__':
    main()
