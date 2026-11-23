#!/usr/bin/env python3
"""night/ndx_recon_check.py — NASDAQ100 の入れ替えを数えた100年の物差しで最適な形を探す（2026-11-22・参考の測り）

ユーザー「100年の物差しが NASDAQ100 に不利なら入れ替えを考慮した最適解をあなたの分析でだして」
読み方（固定）: 100年の代用（1966年以降に始めた30年の毎月の積立の市場との比・起点1966〜1996の31窓）で、NASDAQ100 の写しは
  「French のテック3業種65%＋市場35%」＝今日の業種の傾きを60年ずっと固定したもの（銘柄と業種の入れ替えを数えない）。
  本物の NASDAQ の記録（総合指数 1971-02〜・NASDAQ100 1985-11〜）は入れ替えを含む。写しを本物の記録に替え、同じ13の物差しで
  枝の案（R）と比べ、下に決めた選び方で最適な形を出す。
この道具は門・採点・配分（portfolio.json）・注文書に触れない（測って選ぶだけ。配分に入れるのは別の手順）。
★写しの作り方・形の範囲・条件・目標・選び方・確かめ・読み方の決まりはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの: beat_ret_check・beat_ret_posthoc の数字（R の13の物差し・R を超える形0本・実績の年率の中央だけ譲った最良
  NASDAQ100 10 / SMH 40 / ITA 25 / FBT 25 ほか）／five_mix_ndx の感度（1985-11 から本物につなぐと30年の中央が NASDAQ100 だけ 0.98→1.61・
  SMH 1.00・ITA 1.44・XLV 1.38・VBR 2.28）／build_chain('NDX') のつなぎ目の点検（^NDX の価格は今の写しより年+1.56pt）／
  データが取れるかの確かめ（FRED NASDAQCOM 1971-02〜・French の配当なしの 2x3・値の単位）。
  総合指数を使った新しい写しの数字と、新しい写しで測った形の数字は見ていない。

NASDAQ100 の100年の写し（版・他の本の写しは変えない＝SMH は Chips・ITA は Aero+Guns・FBT は Drugs ほか＝業種の ETF は業種を固定して正しい）:
  V0 数えない（今の写し）: French のテック3業種（時価総額加重）65%＋市場35%
  V1 数える（主）＝本物の NASDAQ の記録を使えるだけ使う:
     1985-11〜       本物の NASDAQ100（bestfund_data.build_chain('NDX')＝QQQ〔経費を足し戻す〕← ^NDX の価格＋配当の置き値）
     1971-03〜1985-10 NASDAQ 総合指数（FRED NASDAQCOM の月末値＝価格）＋配当の見積もり
        配当の見積もり＝総合指数の月次の価格リターンを French の 2x3 の6本の「配当なし」のリターンに回帰（重み≥0・合計1・最小二乗・
        この区間の176か月）し、その重みで6本の（配当込み−配当なし）を毎月足す
     1966-01〜1971-02 French の大型成長（6_Portfolios_2x3 の BIG LoBM・毎年6月に入れ替え・時価総額加重）＝NASDAQ が無い期間の仕組みの写し
  V1p 下限: V1 の総合指数の区間を価格だけ（配当を足さない）
  V1b 前の感度: 1985-11〜 だけ本物・それより前は V0（five_mix_ndx と同じ）
  V2 控えめ（NASDAQ の記録を使わない）: 全期間を French の大型成長（BIG LoBM）＝入れ替えのある大型成長株の規則だけ

形の範囲: 6本（QQQM・SMH・ITA・XLV・FBT・VBR）・5%刻み・合計100（ETF 側・個別株10%は外）・各本は0か5%以上
  縛りなし＝全部（53,130通り）／核あり＝NASDAQ100 が最大の1本 ∧ 40%以上60%以下（ret_seek・balance・beat_ret と同じ）
基準 R＝枝の案（ETF 側 NASDAQ100 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5）。枝の portfolio.json と照合・今の形は origin/main と照合（違えば止まる）。
物差し（beat_ret_check と同じ13・⑧⑨だけ版ごとの写しで測る）:
  ①期待の年率 ②年15%以上の確率 ③年5%未満の確率 ④最大下落 ⑤最悪の世界の年率 ⑥基礎率の平均 ⑦基礎率の5%未満
  ⑧100年の30年の中央 ⑨100年の30年の最悪 ⑩実績の年率の中央 ⑪実績の年15%以上の割合 ⑫半導体の連鎖（下限・資産全体）⑬NVDA（資産全体）
条件（R を下回らない・6つ）: ①期待の年率 ≥ R ／守り5つ＝④最大下落 ≥ R・⑦基礎率の5%未満 ≤ R・⑨100年の最悪 ≥ R・⑫半導体 ≤ R・⑬NVDA ≤ R
目標（4つの証拠・five_mix_ndx と同じ4つ）: g1 ②年15%以上の確率（これからの見込み）・g2 ⑥基礎率の平均（勝ち業種は続かない）・
  g3 ⑧100年の30年の中央（長い記録）・g4 ⑩実績の年率の中央（過去26年）
選び方: 条件を通った形の中で 取り逃がし＝(最良−その形)÷(最良−最悪) を目標ごとに出し、4つの最大が最小の形。
  小数3桁に丸めて同じなら 取り逃がしの合計 → ①期待の年率 → 最大下落が浅い → 名前の順
最終の確かめ（beat_ret_check と同じ・R と比べる・選び方の順に上位30・最初に通った形が答え）:
  F1 感度5本（主・A2を外す・半導体の基礎率・分散の上乗せなし・共分散をA2の窓から）すべてで期待の年率 ≥ R
  F2 基礎率の感度6本すべてで 平均 ≥ R ∧ 5%未満 ≤ R／F3 円の枠で期待の年率 ≥ R ∧ 最大下落 ≥ R
  上位30がすべて落ちたら「確かめを通る形は無い」とし、選び方の1位と落ちた確かめを名指しする
答え＝V1・縛りなし の答え（主）。V1・核あり の答えを並べる。
読み方の決まり（結果を見る前に固定）:
  ・入れ替えを数えた効き目＝同じ選び方の V0 の答えと V1 の答えの違い（NASDAQ100 の比と形）
  ・V1 の答えが V1p・V1b・V2 の版でも条件を通り、その版の選び方の1位との取り逃がしの最大の差が0.05以内なら「写しの作り方に頼らない」。
    外れる版があれば名指しする
  ・V2（NASDAQ の記録を使わない）の答えが V0 の答えと同じ NASDAQ100 の比なら「効き目は NASDAQ の本物の記録（1971〜2026年の一つの時代）から来る」と書く
併せて出す（判定に使わない）:
  (a) 写しの確かめ: 本物の区間の相関と年率（本物の NASDAQ100 対 V0・大型成長・市場／総合指数 対 V0・大型成長・市場）・配当の見積もりの重みと年率・
      NASDAQ100 だけの30年の中央・最悪・市場に勝った窓の数（版ごと）
  (b) 13の物差しすべてで R を超える形の数（版ごと・縛りなし／核あり）と期待の年率の上位
  (c) 条件①（期待の年率 ≥ R）を外した同じ選び方の1位（版ごと・確かめなし）
  (d) NASDAQ100 の比ごとの最良（V0・V1・条件を通った形の中で選び方の順の1位・確かめなし）
  (e) 条件の基準を今の形（main）にした同じ選び方の1位（V0・V1・確かめなし）
  (f) 他の11本を1本足した形（V1・条件を通った形の取り逃がしを6本の範囲の最良・最悪で測り、6本の1位より0.01以上小さい形があれば名指し）
  (g) 詳しい物差し: 答え（V1 縛りなし・核あり）・V0 の答え・R・今の形・前の最良（NASDAQ100 10 / SMH 40 / ITA 25 / FBT 25）・バランス案
回帰の検査: (1) Fast が measure と 1e-9 以内（R・今の形）(2) 実績の割合が past20 と一致 (3) V0 の R の13の物差しが out/beat_ret_check.json と一致
  (4) V0 で R を超える形が縛りなし・核ありとも0本・期待の年率が R 以上の形の数が beat_ret と同じ（9,384・71）(5) 写しを替えない CentP が Cent と一致
  (6) V1b の NASDAQ100 だけの30年の中央・最悪が five_mix_ndx の記録（1.609・0.989）と一致 (7) 集中の線形が lookthrough.py と一致（R・今の形）。外れれば止める
⚠ 限界: 本物の NASDAQ の記録は1971〜2026年の一つの時代（後半はテックが勝った時代）＝入れ替えの効き目と時代の運を分けられない／
  総合指数は金融と小型株を含む（NASDAQ100 は金融を除く上位100社）・配当は見積もり／1971年より前は NASDAQ が無く大型成長で代える／
  100年の写しは他の本（防衛・医薬品）にも後知恵がある（勝った業種を後から選んでいる）がそこは変えていない／
  条件・4つの目標を等しく扱うこと・R を基準にすることは私が決めた／未来の世界は予想・分散の上乗せは仮定／実績は一つの時代／
  中身は 2026-09〜10 の写し／物差しは ETF 側だけ（個別株は外）／形どうしの差の多くは雑音に近い／税と NISA の枠は物差しに入らない
使い方: python3 night/ndx_recon_check.py → out/ndx_recon_check.json（約5〜10分）
"""
import contextlib, io, json, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx_recon_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import beat_ret_check as BT  # noqa: E402

SIX, OTH, RF, NOWF, BALF = BT.SIX, BT.OTH, BT.RF, BT.NOWF, BT.BALF
CASTLE_PCT, STEP, UNITS, K = BT.CASTLE_PCT, BT.STEP, BT.UNITS, BT.K
NDX_LO, NDX_HI = BT.NDX_LO, BT.NDX_HI
EPS, GAIN, TIE = BT.EPS, BT.GAIN, BT.TIE
YJA, YSIGN, YSCALE, YDEC = BT.YJA, BT.YSIGN, BT.YSCALE, BT.YDEC
nm, whole, r = BT.nm, BT.whole, BT.r
OLDF = {'QQQM': 10, 'SMH': 40, 'ITA': 25, 'FBT': 25}
VERS = ['V0', 'V1', 'V1p', 'V1b', 'V2']
VJA = {'V0': '数えない（今の写し＝テック3業種65%＋市場35%）',
       'V1': '数える（主）＝本物の NASDAQ100（1985-11〜）← 総合指数＋配当の見積もり（1971-03〜）← 大型成長（〜1971-02）',
       'V1p': '下限＝V1 の総合指数の区間を価格だけ', 'V1b': '前の感度＝1985-11〜 だけ本物・前は V0',
       'V2': '控えめ＝全期間を French の大型成長（NASDAQ の記録を使わない）'}
COND = [0, 3, 6, 8, 11, 12]          # ①④⑦⑨⑫⑬
DEF5 = [3, 6, 8, 11, 12]
GOALS = [1, 5, 7, 9]                 # ②⑥⑧⑩
GJA = {1: 'g1 年15%以上の確率', 5: 'g2 基礎率の平均', 7: 'g3 100年の30年の中央', 9: 'g4 実績の年率の中央'}
SDEC, NFIN, NTOP, NEAR, HELP = 3, 30, 10, 0.05, 0.01
CH1, CH2 = 40000, 20000
K_R, K_NOW, K_OLD, K_BAL = 'R（枝の案）', '今の形（main）', '前の最良（実績の年率の中央だけ譲った形）', 'バランス案'
SHOWN = BT.SHOWN
COLS6 = ['SMALL LoBM', 'ME1 BM2', 'SMALL HiBM', 'BIG LoBM', 'ME2 BM2', 'BIG HiBM']
SEG_C = (197103, 198510)             # 総合指数の区間
REAL_FROM, COPY_FROM = 198511, 196601


def log(*a):
    print('[ndx_recon]', *a, file=sys.stderr, flush=True)


def prev_m(m):
    return (m // 100 - 1) * 100 + 12 if m % 100 == 1 else m - 1


def simplex_ls(X, y):
    """min |Xw − y|²（w ≥ 0・Σw = 1）。使う列の組を全部試す（組ごとに等式つきの最小二乗）＝大域の最小"""
    n, k = X.shape
    best = None
    for mask in range(1, 1 << k):
        cols = [j for j in range(k) if mask >> j & 1]
        Xs = X[:, cols]
        A = np.zeros((len(cols) + 1, len(cols) + 1))
        A[:-1, :-1] = 2 * Xs.T @ Xs
        A[:-1, -1] = 1
        A[-1, :-1] = 1
        b = np.concatenate([2 * Xs.T @ y, [1.0]])
        try:
            w = np.linalg.solve(A, b)[:-1]
        except np.linalg.LinAlgError:
            continue
        if (w < -1e-12).any():
            continue
        sse = float(((Xs @ w - y) ** 2).sum())
        if best is None or sse < best[0] - 1e-15:
            full = np.zeros(k)
            full[cols] = np.maximum(w, 0.0)
            best = (sse, full)
    if best is None:
        raise SystemExit('配当の見積もりの回帰が解けない')
    return best[1], best[0]


def geo(s, ms):
    v = 1.0
    for m in ms:
        v *= 1 + s[m]
    return v ** (12 / len(ms)) - 1


def corr(a, b, ms):
    return float(np.corrcoef([a[m] for m in ms], [b[m] for m in ms])[0, 1])


def build_copies(C):
    """NASDAQ100 の写しの版 → ({版: {月: リターン}}, 確かめの表)"""
    import bestfund_data as D
    import gaps_common as G
    import mw_common as M
    q0, mkt = C['parts']['QQQM'], C['mkt']
    ndx, segs, chk = D.build_chain('NDX')
    real = [s for s in segs if s['kind'] in ('actual', 'index') and s.get('months')]
    if min(s['frm'] for s in real) != REAL_FROM:
        raise SystemExit(f'本物の NASDAQ100 の始まりが {REAL_FROM} でない: {segs}')
    lv = G.fred('NASDAQCOM')
    six = M.french_series('6_Portfolios_2x3', want='Average Value Weighted Returns')
    sx = M.french_series('6_Portfolios_2x3_Wout_Div', want='Average Value Weighted Returns')
    allm = [m for m in sorted(q0) if m >= COPY_FROM]
    seg = [m for m in allm if SEG_C[0] <= m <= SEG_C[1]]
    miss = [m for m in seg if m not in lv or prev_m(m) not in lv or any(m not in six[c] or m not in sx[c] for c in COLS6)]
    if miss or len(seg) != 176:
        raise SystemExit(f'総合指数の区間に欠けた月がある: {miss[:5]} n={len(seg)}')
    px = {m: lv[m] / lv[prev_m(m)] - 1 for m in seg}
    X = np.array([[sx[c][m] for c in COLS6] for m in seg])
    y = np.array([px[m] for m in seg])
    w, sse = simplex_ls(X, y)
    div = {m: float(sum(w[j] * (six[c][m] - sx[c][m]) for j, c in enumerate(COLS6))) for m in seg}
    big = six['BIG LoBM']
    for m in allm:
        if m not in big or (m >= REAL_FROM and m not in ndx):
            raise SystemExit(f'写しの材料に {m} が無い')

    def make(v):
        q = dict(q0)
        for m in allm:
            if v in ('V1', 'V1p'):
                q[m] = ndx[m] if m >= REAL_FROM else ((px[m] + (div[m] if v == 'V1' else 0.0)) if m >= SEG_C[0] else big[m])
            elif v == 'V1b':
                q[m] = ndx[m] if m >= REAL_FROM else q0[m]
            elif v == 'V2':
                q[m] = big[m]
        return q
    qs = {v: make(v) for v in VERS}
    comp_tr = {m: px[m] + div[m] for m in seg}
    ms_r = [m for m in allm if m >= REAL_FROM]
    ms_e = [m for m in allm if m < SEG_C[0]]
    fit = X @ w
    chkd = dict(
        本物のNASDAQ100のつなぎ=segs, つなぎ目の点検=chk,
        配当の見積もり=dict(重み={c: round(float(x), 3) for c, x in zip(COLS6, w)}, 回帰の相関=round(float(np.corrcoef(fit, y)[0, 1]), 3),
                     足した配当の年率=round(100 * 12 * float(np.mean(list(div.values()))), 2),
                     六本の配当の年率={c: round(100 * 12 * float(np.mean([six[c][m] - sx[c][m] for m in seg])), 2) for c in COLS6}),
        総合指数の区間_1971_03から1985_10=dict(
            月数=len(seg),
            年率=dict(総合指数の価格=round(100 * geo(px, seg), 2), 総合指数と配当の見積もり=round(100 * geo(comp_tr, seg), 2),
                    今の写し_V0=round(100 * geo(q0, seg), 2), 大型成長=round(100 * geo(big, seg), 2), 市場=round(100 * geo(mkt, seg), 2)),
            総合指数の価格との相関=dict(今の写し_V0=round(corr(px, q0, seg), 3), 大型成長=round(corr(px, big, seg), 3), 市場=round(corr(px, mkt, seg), 3))),
        本物の区間_1985_11から=dict(
            月数=len(ms_r), 終わり=ms_r[-1],
            年率=dict(本物のNASDAQ100=round(100 * geo(ndx, ms_r), 2), 今の写し_V0=round(100 * geo(q0, ms_r), 2),
                    大型成長=round(100 * geo(big, ms_r), 2), 市場=round(100 * geo(mkt, ms_r), 2)),
            本物との相関=dict(今の写し_V0=round(corr(ndx, q0, ms_r), 3), 大型成長=round(corr(ndx, big, ms_r), 3), 市場=round(corr(ndx, mkt, ms_r), 3))),
        大型成長の区間_1966_01から1971_02=dict(
            月数=len(ms_e), 年率=dict(大型成長=round(100 * geo(big, ms_e), 2), 今の写し_V0=round(100 * geo(q0, ms_e), 2), 市場=round(100 * geo(mkt, ms_e), 2))),
        全期間_1966_01から=dict(年率={**{v: round(100 * geo(qs[v], allm), 2) for v in VERS}, '市場': round(100 * geo(mkt, allm), 2)}, 終わり=allm[-1]))
    return qs, chkd


def main():
    t0 = time.time()
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
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = list(BR.POOL)
    for c in SIX + OTH:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
    C = B.century_extend(U)
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

    # ── NASDAQ100 の写しの版 ──
    qs, copy_chk = build_copies(C)
    cts = {v: BCc.CentP(U, P, {**C['parts'], 'QQQM': qs[v]}) for v in VERS}
    log('写し', json.dumps({k: copy_chk[k] for k in ('配当の見積もり', '全期間_1966_01から')}, ensure_ascii=False))

    def cent_windows(ct, f):
        W = W_of([f])
        W = W / W.sum(axis=1, keepdims=True)
        S = W @ ct.Pm
        return [(y + 1, float(ct._dca(S, a, b)[0] / mk)) for (y, a, b), mk in zip(ct.win, ct.mk)]

    # ── 中身（半導体・NVDA）の割合（beat_ret_check と同じ出所） ──
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
            share[c] = None
            continue
        cov = sum(w for _, w in h)
        share[c] = dict(semi=sum(w for t, w in h if t.upper() in L.SEMI), unk=max(0.0, 1.0 - cov),
                        nvda=sum(w for t, w in h if t.upper() == 'NVDA'), look=False)

    def sarr(key):
        return np.array([(share[c][key] if share.get(c) else np.nan) if c in SIX + OTH else np.nan for c in P])
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
        bad = (used & np.isnan(sv)[None, :]).any(axis=1)
        lo[bad] = np.nan
        un[bad] = np.nan
        nd[bad] = np.nan
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
    def ybase(A, slow_idx=None):
        """13の物差し（向きをそろえて高いほど良い）のうち⑧⑨以外。slow_idx＝⑩を測る行（None なら全部）"""
        n = len(A)
        Y = np.full((n, 13), np.nan)
        ok = np.zeros(n, bool)
        for s in range(0, n, CH1):
            W = A[s:s + CH1]
            e = fast.eval(W)
            b = fbr.eval(W, a0)
            Y[s:s + CH1, 0], Y[s:s + CH1, 1], Y[s:s + CH1, 2] = e['mean_pi'], e['P15'], -e['P5']
            Y[s:s + CH1, 3], Y[s:s + CH1, 4], Y[s:s + CH1, 10] = e['mdd'], e['worst'], e['past20']
            Y[s:s + CH1, 5], Y[s:s + CH1, 6] = b['mean_pi'], -b['P5']
            ok[s:s + CH1] = e['ok'] & b['ok']
        lo, un, nd = conc_arr(A)
        Y[:, 11], Y[:, 12] = -lo, -nd
        idx = np.arange(n) if slow_idx is None else slow_idx
        for s in range(0, len(idx), CH2):
            ii = idx[s:s + CH2]
            Y[ii, 9] = realized(A[ii], fast)['med']
        return Y, ok, un

    def cfill(Y, ok, A, v, idx=None):
        """⑧⑨を版 v の写しで埋めた写しを返す"""
        Z = Y.copy()
        idx = np.arange(len(A)) if idx is None else idx
        for s in range(0, len(idx), CH2):
            ii = idx[s:s + CH2]
            cc = cts[v].eval(A[ii])
            Z[ii, 7] = np.where(cc['ok'], cc['c30med'], np.nan)
            Z[ii, 8] = np.where(cc['ok'], cc['c30min'], np.nan)
        Z[~ok] = np.nan
        return Z

    def ydict(y):
        return {YJA[i]: r(y[i] * YSIGN[i] * YSCALE[i], YDEC[i]) for i in range(13)}

    # ── 参照の形と回帰の検査 ──
    REF = {K_R: RF, K_NOW: NOWF, K_OLD: OLDF, K_BAL: BALF}
    Wr = W_of(REF.values())
    er = fast.eval(Wr)
    with contextlib.redirect_stdout(io.StringIO()):
        tab0 = U.measure({K_R: RF, K_NOW: NOWF}, rows, chains, mega=U.mega_map(rows, sorted(set(RF) | set(NOWF) | {'VOO'})))[UC.W_CRASH]
    reg = {}
    for j, k in enumerate([K_R, K_NOW]):
        raw = tab0[k]['_raw']
        reg[k] = dict(P15=abs(float(er['P15'][j]) - raw['P15']), 平均=abs(float(er['mean_pi'][j]) - raw['mean_pi']),
                      最大下落=abs(float(er['mdd'][j]) - raw['mdd']))
    rz0 = realized(Wr, fast)
    reg['実績の割合と_past20'] = float(np.max(np.abs(rz0['share'] - er['past20'])))
    shown = {k: dict(平均=tab0[k]['π加重の平均の年率'], P15π=tab0[k]['P15π']) for k in (K_R, K_NOW)}
    ok1 = all(v < 1e-9 for k in (K_R, K_NOW) for v in reg[k].values()) and reg['実績の割合と_past20'] < 1e-9 and \
        all(abs(shown[k]['平均'] - SHOWN[k][0]) < 0.051 and abs(shown[k]['P15π'] - SHOWN[k][1]) < 0.15 for k in (K_R, K_NOW))
    rng = np.random.default_rng(5)
    Wt = rng.integers(0, 9, size=(40, len(P))).astype(np.float64)
    Wt[Wt.sum(axis=1) == 0, 0] = 1
    c1, c2 = cent.eval(Wt), cts['V0'].eval(Wt)
    with np.errstate(invalid='ignore'):
        d_cent = float(np.nanmax(np.abs(c1['c30med'] - c2['c30med']))) + float(np.nanmax(np.abs(c1['c30min'] - c2['c30min'])))
    reg['写しを替えないCentPとCentの差'] = d_cent
    Yr0, okr, unr = ybase(Wr)
    YR = {v: cfill(Yr0, okr, Wr, v) for v in VERS}
    old = json.load(open(os.path.join(BASE, 'out', 'beat_ret_check.json')))
    r13 = ydict(YR['V0'][0])
    reg['V0のRの13の物差し'] = r13
    ok3 = r13 == old['R']['物差し13']
    one = {v: cts[v].eval(W_of([{'QQQM': 1}])) for v in VERS}
    ndx_only = {}
    for v in VERS:
        xs = cent_windows(cts[v], {'QQQM': 1})
        ndx_only[v] = dict(三十年の中央=r(one[v]['c30med'][0], 3), 三十年の最悪=r(one[v]['c30min'][0], 3),
                           市場に勝った窓=f'{sum(x > 1 for _, x in xs)}/{len(xs)}', 最悪の起点=min(xs, key=lambda t: t[1])[0],
                           起点ごと={str(y): round(x, 3) for y, x in xs})
    ok6 = abs(float(one['V1b']['c30med'][0]) - 1.609) < 0.0015 and abs(float(one['V1b']['c30min'][0]) - 0.989) < 0.0015
    lkchk = {}
    for k in (K_R, K_NOW):
        lk, lo, hi = look_whole(REF[k])
        a, u, d = conc_arr(W_of([REF[k]]))
        lkchk[k] = dict(線形=dict(下限=round(float(a[0]), 3), 上限=round(float(a[0] + u[0]), 3), NVDA=round(float(d[0]), 4)),
                        lookthrough=dict(下限=lo, 上限=hi, NVDA=(lk or {}).get('NVDA（資産全体）')),
                        一致=bool(lk and lo is not None and abs(a[0] - lo) < 0.051 and abs(a[0] + u[0] - hi) < 0.051
                                and abs(d[0] - lk['NVDA（資産全体）']) < 0.0051))
    ok7 = all(x['一致'] for x in lkchk.values())
    if not (ok1 and d_cent < 1e-12 and ok3 and ok6 and ok7):
        raise SystemExit(f'回帰の検査が通らない: ok1={ok1} cent={d_cent} R13={ok3} {r13} V1b={ok6} {ndx_only["V1b"]} look={lkchk}')
    log('回帰の検査(1)(2)(3)(5)(6)(7) ✓')
    log('NASDAQ100 だけ', json.dumps({v: {k: x for k, x in d.items() if k != '起点ごと'} for v, d in ndx_only.items()}, ensure_ascii=False))

    # ── 6本の形 ──
    G0 = BT.grid_of(0, False)
    ix6 = [P.index(c) for c in SIX]
    A0 = np.zeros((len(G0), len(P)), dtype=np.float64)
    A0[:, ix6] = G0
    forms = [{c: int(x) * STEP for c, x in zip(SIX, row) if x} for row in G0]
    names = [nm(f) for f in forms]
    core = (G0[:, 0] >= NDX_LO) & (G0[:, 0] <= NDX_HI) & (G0[:, 1:] <= G0[:, [0]]).all(axis=1)
    free = np.ones(len(G0), bool)
    Yb, okb, unb = ybase(A0)
    log('6本の形', len(G0), '核あり', int(core.sum()), f'{time.time() - t0:.0f}s')
    YV = {v: cfill(Yb, okb, A0, v) for v in VERS}
    log('版ごとの100年', f'{time.time() - t0:.0f}s')

    def select(Y, yref, mask, cond, nm_list, best=None, worst=None):
        with np.errstate(invalid='ignore'):
            meas = ~np.isnan(Y).any(axis=1)
            ok = meas & (Y[:, cond] >= yref[cond][None, :] - EPS).all(axis=1) & mask
        idx = np.where(ok)[0]
        if not len(idx):
            return None
        if best is None:
            best, worst = Y[idx][:, GOALS].max(axis=0), Y[idx][:, GOALS].min(axis=0)
        span = np.where(best - worst > EPS, best - worst, np.inf)
        with np.errstate(invalid='ignore'):
            RG = (best[None, :] - Y[:, GOALS]) / span[None, :]
        mx, sm = RG.max(axis=1), RG.sum(axis=1)
        order = sorted([int(i) for i in idx], key=lambda i: (round(float(mx[i]), SDEC), round(float(sm[i]), 9), -round(float(Y[i, 0]) / TIE),
                                                             -float(Y[i, 3]), nm_list[i]))
        return dict(idx=idx, best=best, worst=worst, RG=RG, mx=mx, sm=sm, order=order, meas=meas)

    def brief(i, Y, yref, S=None, frm=None, nml=None, un=None, ref='R'):
        frm, nml, un = frm or forms, nml or names, unb if un is None else un
        y = Y[i]
        out = dict(名前=nml[i], 形=frm[i], 全体の比=whole(frm[i]), 物差し=ydict(y),
                   **{f'{ref}_との差': {YJA[k]: r((y[k] - yref[k]) * YSCALE[k] * YSIGN[k], max(YDEC[k], 2) + 1) for k in range(13)}},
                   下回る物差し=[YJA[k] for k in range(13) if not (y[k] >= yref[k] - EPS)], 半導体の未取得=r(float(un[i]), 2))
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
        """F1〜F3（R と比べる）。形の名前ごとに1回だけ測る"""
        todo = [f for f in fl if nm(f) not in FC]
        for s in range(0, len(todo), 10):
            part = todo[s:s + 10]
            Fm = {K_R: RF, **{'@' + nm(f): f for f in part}}
            assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
            with contextlib.redirect_stdout(io.StringIO()):
                k4, _ = N.chips_adj(rows, assets)
                vt = N.variants(Fm, rows, chains, k4)[UC.W_CRASH]
                tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets), windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
            Wf = W_of(Fm.values())
            vres = {v: ve(Wf, v) for v in ve_names}
            for j, f in enumerate(part, start=1):
                k = '@' + nm(f)
                d1 = {N.VARS_JA[v]: round(100 * (vt[k][v]['mean_pi'] - vt[K_R][v]['mean_pi']), 3) for v in N.VARS}
                f1 = all(vt[k][v]['mean_pi'] >= vt[K_R][v]['mean_pi'] - EPS for v in N.VARS)
                d2 = {v: dict(平均=round(100 * float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]), 3),
                              五パーセント未満=round(100 * float(vres[v]['P5'][j] - vres[v]['P5'][0]), 2)) for v in ve_names}
                f2 = all(vres[v]['mean_pi'][j] >= vres[v]['mean_pi'][0] - EPS and vres[v]['P5'][j] <= vres[v]['P5'][0] + EPS for v in ve_names)
                dj = 100 * (tj[k]['_raw']['mean_pi'] - tj[K_R]['_raw']['mean_pi'])
                dm = 100 * (tj[k]['_raw']['mdd'] - tj[K_R]['_raw']['mdd'])
                f3 = bool(dj >= -1e-10 and dm >= -1e-10)
                FC[nm(f)] = dict(F1=bool(f1), F2=bool(f2), F3=f3, 合否=bool(f1 and f2 and f3), 感度5本のRとの差=d1,
                                 基礎率の感度6本のRとの差=d2, 円のRとの差=dict(期待の年率=round(dj, 3), 最大下落=round(dm, 2)))

    def decide(S, Y, yref):
        """選び方の順に上位 NFIN を確かめ、最初に通った形を答えに"""
        if S is None:
            return dict(条件を通った形=0, 答え='条件を通る形は無い')
        top = S['order'][:NFIN]
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
        out = dict(条件を通った形=int(len(S['idx'])),
                   目標の最良と最悪={GJA[g]: dict(最良=r(S['best'][j] * YSCALE[g], YDEC[g]), 最悪=r(S['worst'][j] * YSCALE[g], YDEC[g])) for j, g in enumerate(GOALS)},
                   選び方の1位=dict(**brief(first, Y, yref, S), 確かめ=FC[names[first]]),
                   上位=[dict(**brief(i, Y, yref, S), 確かめ=(dict(F1=FC[names[i]]['F1'], F2=FC[names[i]]['F2'], F3=FC[names[i]]['F3'])
                                                        if names[i] in FC else None)) for i in S['order'][:NTOP]],
                   最終の確かめ=seen, Rの取り逃がし=None)
        out['答え'] = dict(**brief(ans, Y, yref, S), 確かめ=FC[names[ans]]) if ans is not None else '確かめを通る形は無い'
        out['_ans'], out['_first'] = ans, first
        return out

    ir = names.index(nm(RF))
    answers = {'縛りなし': {}, '核あり': {}}
    SEL = {}
    for v in VERS:
        Y, yR = YV[v], YR[v][0]
        if np.isnan(yR).any():
            raise SystemExit(f'R の物差しが測れない（{v}）')
        if float(np.nanmax(np.abs(Y[ir] - yR))) > 1e-9:
            raise SystemExit(f'形の表の R が参照の R と違う（{v}）')
        for lab, mask in (('縛りなし', free), ('核あり', core)):
            S = select(Y, yR, mask, COND, names)
            SEL[(v, lab)] = S
            d = decide(S, Y, yR)
            if S is not None:
                d['Rの取り逃がし'] = dict(最大=round(float(S['mx'][ir]), 4), 目標ごと={GJA[g]: round(float(S['RG'][ir, j]), 3) for j, g in enumerate(GOALS)})
            answers[lab][v] = d
            a_ = d.get('答え')
            log(v, lab, '条件を通った', d.get('条件を通った形'), '1位', (names[d['_first']] if '_first' in d else None),
                '答え', (a_['名前'] if isinstance(a_, dict) else a_), f'{time.time() - t0:.0f}s')

    # ── (b) 13の物差しすべてで R を超える形 ──
    dom_out, reg4 = {}, {}
    for v in VERS:
        Y, yR = YV[v], YR[v][0]
        with np.errstate(invalid='ignore'):
            ge = Y >= yR[None, :] - EPS
            gt = Y > yR[None, :] + GAIN
            dom = ge.all(axis=1) & gt.any(axis=1)
            himean = Y[:, 0] >= yR[0] - EPS
        dom_out[v] = {}
        for lab, mask in (('縛りなし', free), ('核あり', core)):
            idx = [int(i) for i in np.where(dom & mask)[0]]
            idx.sort(key=lambda i: (-round(float(Y[i, 0]) / TIE), -float(Y[i, 1]), -float(Y[i, 3]), names[i]))
            dom_out[v][lab] = dict(超える形の数=len(idx), 上位=[brief(i, Y, yR) for i in idx[:5]])
        if v == 'V0':
            reg4 = dict(縛りなしで超える=dom_out[v]['縛りなし']['超える形の数'], 核ありで超える=dom_out[v]['核あり']['超える形の数'],
                        期待の年率がR以上_縛りなし=int((himean & free).sum()), 期待の年率がR以上_核あり=int((himean & core).sum()))
    cnt = old['範囲ごとの数']
    ok4 = (reg4['縛りなしで超える'] == 0 and reg4['核ありで超える'] == 0
           and reg4['期待の年率がR以上_縛りなし'] == cnt['D1 芯なし・同じ6本']['期待の年率がR以上']
           and reg4['期待の年率がR以上_核あり'] == cnt['A 芯あり・同じ6本']['期待の年率がR以上'])
    reg['V0の超える形と数'] = reg4
    if not ok4:
        raise SystemExit(f'回帰の検査(4)が通らない: {reg4}')
    log('回帰の検査(4) ✓', json.dumps({v: {k: x['超える形の数'] for k, x in d.items()} for v, d in dom_out.items()}, ensure_ascii=False))

    # ── (c) 条件①を外す／(e) 基準を今の形に／(d) NASDAQ100 の比ごと ──
    no1, vs_now, by_ndx = {}, {}, {}
    for v in VERS:
        Y, yR, yN = YV[v], YR[v][0], YR[v][1]
        no1[v] = {}
        for lab, mask in (('縛りなし', free), ('核あり', core)):
            S = select(Y, yR, mask, DEF5, names)
            no1[v][lab] = dict(条件を通った形=int(len(S['idx'])), 上位3=[brief(i, Y, yR, S) for i in S['order'][:3]]) if S else dict(条件を通った形=0)
        if v in ('V0', 'V1'):
            vs_now[v] = {}
            for lab, mask in (('縛りなし', free), ('核あり', core)):
                S = select(Y, yN, mask, COND, names)
                vs_now[v][lab] = dict(条件を通った形=int(len(S['idx'])), 上位3=[brief(i, Y, yN, S, ref='今') for i in S['order'][:3]]) if S else dict(条件を通った形=0)
            S = SEL[(v, '縛りなし')]
            by_ndx[v] = {}
            if S is not None:
                pos = {i: k for k, i in enumerate(S['order'])}
                for u in range(0, UNITS + 1):
                    ii = [i for i in S['order'] if G0[i, 0] == u]
                    by_ndx[v][f'NASDAQ100 {u * STEP}'] = dict(条件を通った形=len(ii), **({'最良': brief(ii[0], Y, yR, S), '全体の順位': pos[ii[0]] + 1} if ii else {}))

    # ── 読み方の決まり ──
    def ans_of(lab, v):
        d = answers[lab][v]
        return d.get('_ans') if d.get('_ans') is not None else None

    def ndx_of(i):
        return None if i is None else int(G0[i, 0]) * STEP
    reading = {}
    for lab in ('縛りなし', '核あり'):
        a0_, a1_, a2_ = ans_of(lab, 'V0'), ans_of(lab, 'V1'), ans_of(lab, 'V2')
        f0, f1 = answers[lab]['V0'].get('_first'), answers[lab]['V1'].get('_first')
        rd = dict(V0の答え=(names[a0_] if a0_ is not None else None), V1の答え=(names[a1_] if a1_ is not None else None),
                  V2の答え=(names[a2_] if a2_ is not None else None),
                  NASDAQ100の比_V0からV1=f'{ndx_of(a0_)} → {ndx_of(a1_)}',
                  選び方の1位_確かめ前=dict(V0=(names[f0] if f0 is not None else None), V1=(names[f1] if f1 is not None else None),
                                     NASDAQ100の比=f'{ndx_of(f0)} → {ndx_of(f1)}'))
        tgt = a1_ if a1_ is not None else f1
        rob = {}
        if tgt is not None:
            for v in ('V1p', 'V1b', 'V2'):
                S = SEL[(v, lab)]
                if S is None or tgt not in set(int(i) for i in S['idx']):
                    y, yR = YV[v][tgt], YR[v][0]
                    rob[v] = dict(条件を通る=False, 外れた条件=[YJA[k] for k in COND if not (y[k] >= yR[k] - EPS)])
                else:
                    gap = float(S['mx'][tgt] - S['mx'][S['order'][0]])
                    rob[v] = dict(条件を通る=True, その版の1位との差=round(gap, 4), その版の1位=names[S['order'][0]], 幅の中=bool(gap <= NEAR + 1e-12))
            rd['V1の答えを他の版で測る'] = rob
            rd['写しの作り方に頼らない'] = bool(all(x.get('幅の中') for x in rob.values()))
            rd['外れた版'] = [v for v, x in rob.items() if not x.get('幅の中')]
        if a0_ is not None and a2_ is not None:
            rd['V2の答えのNASDAQ100の比がV0と同じ'] = bool(ndx_of(a0_) == ndx_of(a2_))
        reading[lab] = rd

    # ── (f) 他の11本を1本足す（V1・6本の範囲の最良と最悪で測る） ──
    extra = {}
    S1 = SEL[('V1', '縛りなし')]
    if S1 is not None:
        yR = YR['V1'][0]
        bar = float(S1['mx'][S1['order'][0]])
        G1 = BT.grid_of(1, False)
        cheap = [c for c in COND if c != 8]
        for x in OTH:
            cols = SIX + [x]
            A = np.zeros((len(G1), len(P)), dtype=np.float64)
            A[:, [P.index(c) for c in cols]] = G1
            Yx, okx, unx = ybase(A, slow_idx=np.array([], dtype=int))
            with np.errstate(invalid='ignore'):
                pre = okx & (Yx[:, cheap] >= yR[cheap][None, :] - EPS).all(axis=1)
            idx = np.where(pre)[0]
            for s in range(0, len(idx), CH2):
                ii = idx[s:s + CH2]
                Yx[ii, 9] = realized(A[ii], fast)['med']
            Yx = cfill(Yx, okx, A, 'V1', idx)
            fr = [{c: int(q) * STEP for c, q in zip(cols, row) if q} for row in G1[idx]] if len(idx) else []
            sub = Yx[idx]
            nml = [nm(f) for f in fr]
            S = select(sub, yR, np.ones(len(idx), bool), COND, nml, best=S1['best'], worst=S1['worst']) if len(idx) else None
            if S is None:
                extra[x] = dict(形=len(G1), 条件を通った形=0)
            else:
                i = S['order'][0]
                extra[x] = dict(形=len(G1), 条件を通った形=int(len(S['idx'])), 最良=brief(i, sub, yR, S, frm=fr, nml=nml, un=unx[idx]),
                                六本の1位より小さい幅=round(bar - float(S['mx'][i]), 4), 足す価値=bool(float(S['mx'][i]) < bar - HELP))
            del A, Yx
            log('他の本', x, json.dumps({k: (z if not isinstance(z, dict) else z.get('名前')) for k, z in extra[x].items()}, ensure_ascii=False),
                f'{time.time() - t0:.0f}s')
        extra['_6本の1位の取り逃がしの最大'] = round(bar, 4)

    # ── (g) 詳しい物差し ──
    DET, alias = {K_R: RF}, {}

    def add(label, i):
        if i is None:
            return
        same_as = next((k for k, f in DET.items() if nm(f) == names[i]), None)
        if same_as is None:
            DET[label] = forms[i]
        else:
            alias[label] = same_as
    add('答え（V1・縛りなし）', ans_of('縛りなし', 'V1'))
    add('選び方の1位（V1・縛りなし・確かめ前）', answers['縛りなし']['V1'].get('_first'))
    add('答え（V1・核あり）', ans_of('核あり', 'V1'))
    add('選び方の1位（V1・核あり・確かめ前）', answers['核あり']['V1'].get('_first'))
    add('答え（V0・縛りなし）', ans_of('縛りなし', 'V0'))
    add('選び方の1位（V0・縛りなし・確かめ前）', answers['縛りなし']['V0'].get('_first'))
    add('答え（V2・縛りなし）', ans_of('縛りなし', 'V2'))
    for k, f in REF.items():
        if nm(f) not in {nm(g) for g in DET.values()}:
            DET[k] = f
    Wd = W_of(DET.values())
    Yd0, okd, und = ybase(Wd)
    YD = {v: cfill(Yd0, okd, Wd, v) for v in VERS}
    bd, rzd = fbr.eval(Wd, a0), realized(Wd, fast)
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
    jr = list(DET).index(K_R)
    detail = {}
    for j, k in enumerate(DET):
        t = tab[k]
        q, pr_ = UC.upside(sim, t['_raw'], pi)
        lk, lo, hi = look_whole(DET[k])
        a, u, d = conc_arr(Wd[j:j + 1])
        detail[k] = dict(
            形=DET[k], 名前=nm(DET[k]), 全体の比=whole(DET[k]),
            物差し13={v: ydict(YD[v][j]) for v in ('V0', 'V1')},
            R_との差_V1={YJA[i]: r((YD['V1'][j, i] - YD['V1'][jr, i]) * YSCALE[i] * YSIGN[i], max(YDEC[i], 2) + 1) for i in range(13)},
            百年_版ごと={v: dict(三十年の中央=r(YD[v][j, 7], 3), 三十年の最悪=r(YD[v][j, 8], 3)) for v in VERS},
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), 五パーセント未満=t['P5π（5%未満）'],
                   元本割れ=t['P0π（元本割れ）'], 最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'], 世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q),
            感度5本のRとの差={N.VARS_JA[v]: round(100 * (vtd[k][v]['mean_pi'] - vtd[K_R][v]['mean_pi']), 3) for v in N.VARS},
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * bd['mean_pi'][j]), P15π=r(100 * bd['P15'][j]), 五パーセント未満=r(100 * bd['P5'][j]),
                     感度6本のRとの差={v: r(100 * (Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][jr]), 3) for v in ve_names}),
            実績=dict(年15パーセント以上の割合=r(100 * rzd['share'][j], 1), 年率の中央=r(100 * rzd['med'][j]), 最悪=r(100 * rzd['worst'][j])),
            集中=dict(半導体の連鎖_下限=round(float(a[0]), 2), 半導体の連鎖_上限=round(float(a[0] + u[0]), 2), NVDA=round(float(d[0]), 2),
                    lookthrough=(dict(半導体の連鎖=lk.get('半導体の連鎖（下限〜上限）'), NVDA=lk.get('NVDA（資産全体）'), 最大の1銘柄=lk.get('最大の1銘柄')) if lk else None)),
            百年の起点ごと_V1={str(y): round(x, 3) for y, x in cent_windows(cts['V1'], DET[k])})

    for lab in answers:
        for v in answers[lab]:
            answers[lab][v].pop('_ans', None)
            answers[lab][v].pop('_first', None)
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/ndx_recon_check.py',
        kind='参考（測って選ぶだけ・写しの作り方・範囲・条件・目標・選び方・確かめ・読み方は道具の頭に固定し回す前にコミット）',
        question='100年の物差しが NASDAQ100 に不利なら入れ替えを考慮した最適解をあなたの分析でだして',
        版=VJA, 写しの確かめ=copy_chk, NASDAQ100だけ_版ごと=ndx_only,
        R=dict(形=RF, 名前=nm(RF), 全体の比=whole(RF), 物差し13={v: ydict(YR[v][0]) for v in VERS}),
        今の形=dict(形=NOWF, 名前=nm(NOWF), 物差し13={v: ydict(YR[v][1]) for v in ('V0', 'V1')}),
        決まり=dict(条件=[YJA[k] for k in COND], 目標=[GJA[g] for g in GOALS], 上位を確かめる数=NFIN, 版の間の幅=NEAR),
        答え=answers, 読み方=reading,
        併せて=dict(b_13の物差しすべてでRを超える形=dom_out, c_期待の年率の条件を外す=no1, d_NASDAQ100の比ごと=by_ndx, e_基準を今の形に=vs_now, f_他の本を1本足す=extra),
        詳しい物差し=detail, 詳しい物差しの同じ形=alias, regression=dict(差=reg, 表示=shown, 中身の検算=lkchk, 通過=True),
        席=dict(社=seats, 一社=per, 半導体=c_semi), secs=round(time.time() - t0, 1))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('書いた', OUT, f'{time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
