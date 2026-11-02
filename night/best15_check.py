#!/usr/bin/env python3
"""night/best15_check.py — 年率15%を狙いつつ最も優れた形を、新しい投資先も含めて探す（best15・2026-11-01・参考・配分は変えない）

ユーザーの問い「歴史検証でデータと未来予測を活用してリターン15%を狙いつつ最も優れたポートフォリオ組むならどうするか
新しい投資先も検討したうえで案をだして」。門・採点・配分（portfolio.json）・注文書には触れない。
★候補・物差し・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする（`--selfcheck` は速い評価が
  標準の物差しと一致するかだけを出し、探索の結果は出さない）。

今（正本 portfolio.json の ETF 側・個別株0%）: NASDAQ100（iFreeNEXT＝物差しでは QQQM）50 / SMH 20 / ITA 20 / XLV 10（読み込んで確かめる）

候補（33本）: 今の4本＋FBT＋ out/etf_add_prereg.json の機械1の候補のうち主の窓（2000-09〜）に系列がそろう28本
  （楽天の海外ETF一覧か東証で買える・unx の行がある本）
  GDX 金鉱株・SLV 銀・GLDM 金・XLU 公益・XLP 生活必需品・XLE エネルギー・XLF 金融・XLI 資本財・XLY 一般消費財・XLK テック・
  VUG 大型グロース・VTV 大型バリュー・VBR 小型バリュー・IJR 小型・VOO S&P500・MOAT 堀・
  VT 全世界・VEA 先進国（除く米国）・VWO 新興国・PXF 先進国バリュー・DEM 新興国高配当・EPI_LONG インド（器は EPI）・EWY 韓国・
  EDV 超長期国債・TLT 長期国債・TIP 物価連動国債・TOPIX 日本株・UST_HEDGED_2621 円ヘッジ米国債
  外す: RSP・VIG・VYM（主の窓に系列がそろわない＝etf_add と同じ）・SHLD（2023-09 以前は ITA の写し・代理の門を通らない）・
        SHLD_EU（感度の行）・MTUM・QUAL・VNQ（楽天に無い）・GRID（主の窓にそろわない）・EPI（EPI_LONG で測る）・
        MF_REF・GOLDPLUS_REF（紙の上）・YEN_CASH（ETF でない）
形: ETF 側100%（個別株0%＝今の正本のまま）・5%刻み・7本まで・1本40%まで

物差し（主）: night/unx_assets.measure の USD・崩れあり（2000-09〜2026-09）の式を行列で写した速い評価
  （`--selfcheck`＝無作為の形で measure と century_monthly に 1e-9 以内で一致することを確かめてから使う）
  5つの世界: A1 直近26年・A2 直近15年（歴史）／B 100年の平均（UBS＋French）・C JPM 2026 の予想・D アナリストの予想（未来）
  π（out/bestpf_calibration.json）: A1 .2167・A2 .1539・B .31・C .1597・D .1597＝未来の世界に 63%
  P15π＝20年の毎月の積立の内部収益率が年15%以上になる確率
100年の代用: unx_assets.century_monthly（30年の積立 起点1965〜1995・市場との比）。写しは unx の部品
  （QQQM・SMH・ITA・VOO・XLV・FBT・GDX・XLU）＋この道具の中だけで足す写し: XLP・XLE・XLF・XLI・XLY＝French 49 の業種の時価加重
  （century_cand と同じ）・VBR＝SMALL HiBM（同じ）・XLK＝French のテック3業種（Hardw・Softw・Chips）の時価加重・VUG＝BIG LoBM・
  VTV＝BIG HiBM・IJR＝SMALL の3つ（LoBM・ME1 BM2・HiBM）の平均。
  写しの無い本（金・銀・債券・国・MOAT ほか）を含む形は100年を測れない

道（3つ）:
  T1 主「15%の確率を上げ、ほかのどの物差しでも今を下回らない」:
     ① π加重の平均の年率 ≥ 今 ② 最悪の世界 ≥ 今 ③ P5π（年5%未満）≤ 今 ④ 最大下落 ≥ 今（同じか浅い）
     ⑤ P15π（A2を外す）≥ 今 ⑥ P15π（未来の世界 B・C・D だけ）≥ 今 ⑦ 過去の転がる20年で15%以上 ≥ 今
     ⑧ 100年の代用 30年の積立の比の中央値 ≥ 今 ∧ 最悪 ≥ 今（測れない形は T1 に入れない）
  T2「15%を厚く狙う（守りの③④⑦⑧は問わない）」: ①②⑤⑥ だけ
  T3「天井」: 形の縛りだけ（参考）
  各道で P15π が最大の形（0.05pt 単位に丸めて同じなら π加重の平均が大きいほう → 最大下落が浅いほう → 名前の順）
探索:
  第0段（参考）＝核4本だけの総当たり（新しい本を足さずに比を変えるだけの最良・第1段の各行に「核だけの最良との差」）
  第1段＝核4本（QQQM・SMH・ITA・XLV）＋候補1本の総当たり（候補は5%以上・核は0%も可）→ 候補ごとの T1・T2 の最良の P15π
  第2段＝核4本＋第1段の T1 の上位3本＋T2 の上位3本（今の P15π を上回った候補だけ・重複は1本・最大10本）の総当たり（7本まで）
最終の確かめ（各道の第2段の上位30の形を P15π の順に・最初に通った形を答えにする）:
  F1 感度5本（主・A2を外す・半導体の基礎率・分散の上乗せなし・共分散を A2 の窓から＝ndx_swap_check.variants）すべてで P15π ≥ 今
     （T1 はさらに π加重の平均 ≥ 今 も5本すべてで）
  F2（T1 だけ）円・崩れあり の枠（unx_assets.measure・円の系列）で π加重の平均 ≥ 今 ∧ 最大下落 ≥ 今
  通る形が無ければ「今のまま」
併せて出す（判定に使わない）: 候補33本の第1段の表・T1 で⑧を問わない形（100年を測れない本を含む形）の最良・中身の集中
  （night/lookthrough.py・城0%）・積立20年の内部収益率の分位・崩れ2000型の位置・ドットコム級なしの枠・参考の形
  （SMH60/ITA40・前日の案 NDX50/SMH20/ITA15/XLV10/VBR5・NASDAQ100 だけ・S&P500 だけ）・
  物差しの外の候補（out/etf_add_check.json の機械2＝SIL・COPX・EWT・QTEC・FDN・FXL・BBH・GLIN・EPHE）
⚠ 限界: 歴史の世界は2000年以降のテックの時代・100年の写しは後から勝ちが分かった業種を含む・B・C・D の分散の上乗せは仮定
  （感度「分散の上乗せなし」で確かめる）・未来の世界も予想であって結果ではない・費用は物差しに入るが税は入らない・
  1本40%・7本の縛りと5%刻みは私が決めた。第1段の絞り込みは1本ずつの効き目で選ぶ＝2本で初めて効く組は第2段で拾えない場合がある。

使い方: python3 night/best15_check.py --selfcheck   （速い評価と measure・century_monthly の一致だけ）
        python3 night/best15_check.py               → out/best15_check.json
"""
import itertools, json, math, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'best15_check.json')

NOW = {'QQQM': 50, 'SMH': 20, 'ITA': 20, 'XLV': 10}
CORE = ['QQQM', 'SMH', 'ITA', 'XLV']
EXCL = {'SHLD', 'SHLD_EU', 'MTUM', 'QUAL', 'VNQ', 'GRID', 'EPI', 'MF_REF', 'GOLDPLUS_REF', 'YEN_CASH'}
SHORT = {'RSP', 'VIG', 'VYM'}                  # 主の窓（2000-09〜）に系列がそろわない（etf_add と同じく外す）
UNITS, STEP, KMAX, CAP = 20, 5, 7, 8          # 5%刻み・7本まで・1本40%まで
TIE = 0.0005                                   # 0.05pt
NTOP1, NFIN = 3, 30
REFS = {'SMH60/ITA40（15%を最も効率よく）': {'SMH': 60, 'ITA': 40},
        '前日の案 NDX50/SMH20/ITA15/XLV10/VBR5': {'QQQM': 50, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 5},
        'NASDAQ100 だけ': {'QQQM': 100}, 'S&P500 だけ': {'VOO': 100}}
CENT_IND = {'XLP': ['Smoke', 'Soda', 'Food', 'Beer', 'Hshld'], 'XLE': ['Oil'], 'XLF': ['Banks', 'Insur', 'Fin'],
            'XLI': ['ElcEq', 'Mach', 'Trans', 'Cnstr', 'BldMt', 'Ships'],
            'XLY': ['Rtail', 'Meals', 'Autos', 'Clths', 'Fun', 'Toys', 'Books']}
LOOK_NAME = {'EPI_LONG': 'EPI'}               # lookthrough に渡す器の名前
M2_ONLY = ['SIL', 'COPX', 'EWT', 'QTEC', 'FDN', 'FXL', 'BBH', 'GLIN', 'EPHE']


def log(*a):
    print(*a, flush=True)


def check_now():
    t = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    w = {('QQQM' if k == 'IFREE-NDX' else k): v for k, v in t['ami_weights'].items() if v}
    c = t.get('shiro_castle_pct')
    if w != NOW or float(c or 0) != 0:
        raise SystemExit(f'今の形が正本と違う: {w}・個別株 {c}（この道具の NOW を直してから回す）')


def pool_list():
    P = json.load(open(os.path.join(BASE, 'out', 'etf_add_prereg.json')))['machine_1_main']
    cands = P[next(k for k in P if k.startswith('候補'))]
    out = list(CORE) + ['FBT'] + [c for c in cands if c not in CORE and c != 'FBT' and c not in SHORT]
    assert not (set(out) & EXCL), set(out) & EXCL
    assert len(out) == len(set(out)) == 33, len(out)
    return out


# ───────────────────────── 速い評価（measure と同じ式・行列で）─────────────────────────
class Fast:
    def __init__(self, U, rows, chains, pool):
        import etf_p15 as P
        import bestpf_eval as E
        import bestpf_check as BC
        import upside_check as UC
        R = U.R
        self.P, self.E, self.pool = P, E, list(pool)
        a, b = BC.WINDOWS[UC.W_CRASH]
        k1, k2 = R.months(a, b), R.months(*R.A2)
        self.T1, self.T2 = len(k1), len(k2)
        self.G1 = np.array([[chains[c][m] for m in k1] for c in pool])
        self.G2 = np.array([[chains[c][m] for m in k2] for c in pool])
        self.adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in pool])
        Dmap, _, _ = E.load_D(rows, pool)
        for c in pool:
            if 'D_override' in rows[c]:
                Dmap[c] = rows[c]['D_override']
        S1 = np.cov(np.log1p(self.G1), bias=True) * 12
        self.S1, self.s1 = S1, np.diag(S1).copy()
        self.lB = np.log1p(np.array([rows[c]['B'] for c in pool]))
        self.lC = np.log1p(np.array([rows[c]['C'] for c in pool]))
        self.lD = np.log1p(np.array([Dmap[c] for c in pool]))
        pi, _, _ = E.load_pi()
        self.pi = pi
        self.noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi.items()}
        self.fwd = {k: (0.0 if k in ('A1', 'A2') else v) for k, v in pi.items()}
        self.tabs, _ = U.tables()

    def eval(self, W):
        import etf_forward_combo as CB
        P, E = self.P, self.E
        W = np.asarray(W, dtype=np.float64)
        W = W / W.sum(axis=1, keepdims=True)
        R1 = W @ self.G1
        geo, vol, mdd = CB.path_stats(R1, self.T1)
        wadj = W @ self.adj
        a2 = np.expm1(np.log1p(W @ self.G2).sum(axis=1) * 12 / self.T2)
        q = np.einsum('ij,jk,ik->i', W, self.S1, W)
        bonus = 0.5 * (W @ self.s1 - q)
        sig = np.sqrt(q)
        wv = {'A1': geo + wadj, 'A2': a2 + wadj, 'B': np.expm1(W @ self.lB + bonus),
              'C': np.expm1(W @ self.lC + bonus), 'D': np.expm1(W @ self.lD + bonus)}
        ok = (sig >= P.S0) & (sig <= P.S1_)
        for k in E.WORLDS:
            m = np.log1p(wv[k])
            ok &= (m >= P.M0) & (m <= P.M1)
        n = len(W)

        def pr(tau, p):
            tot = np.zeros(n); den = 0.0
            for k in E.WORLDS:
                if p.get(k, 0) <= 0:
                    continue
                v = np.full(n, np.nan)
                if ok.any():
                    v[ok] = P.interp(self.tabs[tau], np.log1p(wv[k][ok]), sig[ok])
                tot += p[k] * (v if tau >= 0.10 else 1 - v)
                den += p[k]
            return tot / den
        out = dict(ok=ok, P15=pr(0.15, self.pi), P15_noA2=pr(0.15, self.noA2), P15_fwd=pr(0.15, self.fwd),
                   P5=pr(0.05, self.pi), worst=np.minimum.reduce([wv[k] for k in E.WORLDS]),
                   mean_pi=sum(self.pi[k] * wv[k] for k in E.WORLDS) / sum(self.pi.values()), vol=vol, mdd=mdd, sig=sig)
        out['past20'] = P.hist_success(W, self.G1, self.adj, self.T1, months_list=(240,), tau=0.15)[240]
        for k in ('P15', 'P15_noA2', 'P15_fwd', 'P5'):
            out[k] = np.where(ok, out[k], np.nan)
        return out


# ───────────────────────── 100年の代用（century_monthly と同じ式・行列で）─────────────────────────
def century_extend(U):
    """century_cand・tsumitate_cand と同じ作法で、この道具の中だけ写しを足す（unx の部品は変えない）"""
    import mw_common as M
    import gaps_common as G
    from avuv_check import french_small_hibm
    C = U.century_parts()
    F = C['F']
    cols, ret, capm, me, be, share, mkt = F.load()
    allm = sorted(C['mkt'])
    for x, inds in CENT_IND.items():
        C['parts'][x] = F.capw(ret, capm, inds, allm) if len(inds) > 1 else ret[inds[0]]
    C['parts']['VBR'] = french_small_hibm(M, 0.0)
    six = M.french_series('6_Portfolios_2x3', want='Average Value Weighted Returns')
    C['parts']['VUG'] = dict(six['BIG LoBM'])
    C['parts']['VTV'] = dict(six['BIG HiBM'])
    sm = [six['SMALL LoBM'], six['ME1 BM2'], six['SMALL HiBM']]
    C['parts']['IJR'] = {m: sum(s[m] for s in sm) / 3 for m in sm[0] if all(m in s for s in sm)}
    C['parts']['XLK'] = G.french_tech()
    for x in list(CENT_IND) + ['VBR', 'VUG', 'VTV', 'IJR', 'XLK']:
        U.MONTHLY_OK.add(x)
    return C


class Cent:
    def __init__(self, U, pool):
        C = U.century_parts()
        F, parts, mkt, endm = C['F'], C['parts'], C['mkt'], C['endm']
        wins = [(y, F.months((y + 1) * 100 + 1, 360)) for y in range(1965, 1996)]
        wins = [(y, w) for y, w in wins if w[-1] <= endm]          # century_monthly と同じ窓（終わりが endm を超える窓は外す）
        hi = max(w[-1] for _, w in wins)
        ms = [m for m in sorted(mkt) if 196601 <= m <= hi]
        self.pool = list(pool)
        self.has = np.array([c in U.MONTHLY_OK and c in parts for c in pool])
        Pm = np.zeros((len(pool), len(ms)))
        for i, c in enumerate(pool):
            if self.has[i]:
                miss = [m for m in ms if m not in parts[c]]
                if miss:
                    raise SystemExit(f'100年の写し {c} に欠けた月がある（{miss[:3]}…）＝行列の写しが使えない')
                Pm[i] = [parts[c][m] for m in ms]
        self.Pm = Pm
        idx = {m: i for i, m in enumerate(ms)}
        assert all(len(w) == idx[w[-1]] - idx[w[0]] + 1 for _, w in wins)
        self.win = [(y, idx[w[0]], idx[w[-1]]) for y, w in wins]
        mk = np.array([mkt[m] for m in ms])
        self.mk = np.array([self._dca(mk[None, :], a, b)[0] for _, a, b in self.win])

    @staticmethod
    def _dca(S, a, b):
        """v=(v+1)(1+r) を a〜b の月で → v/n（future30.dca_mult と同じ）"""
        L = np.log1p(S[:, a:b + 1])
        c = np.cumsum(L, axis=1)
        prev = np.hstack([np.zeros((len(S), 1)), c[:, :-1]])
        v = np.exp(c[:, -1]) * np.exp(-prev).sum(axis=1)
        return v / (b - a + 1)

    def eval(self, W):
        W = np.asarray(W, dtype=np.float64)
        W = W / W.sum(axis=1, keepdims=True)
        okc = ~((W[:, ~self.has] > 0).any(axis=1)) if (~self.has).any() else np.ones(len(W), bool)
        S = W @ self.Pm
        X = np.stack([self._dca(S, a, b) / mk for (_, a, b), mk in zip(self.win, self.mk)], axis=1)
        med = np.where(okc, np.median(X, axis=1), np.nan)
        mn = np.where(okc, X.min(axis=1), np.nan)
        return dict(ok=okc, c30med=med, c30min=mn)


# ───────────────────────── 形の列挙 ─────────────────────────
def comps_pos(total, k, cap):
    """total を k 個の正の整数（各 cap 以下）に分ける全部 → (N, k)"""
    out = []
    for c in itertools.combinations(range(1, total), k - 1):
        p = (0,) + c + (total,)
        v = [p[i + 1] - p[i] for i in range(k)]
        if max(v) <= cap:
            out.append(v)
    return np.array(out, dtype=np.int8).reshape(-1, k)


def all_forms(n, kmax, cap, must=None):
    """n 本の中の全部の形（単位の和 UNITS・7本まで・1本 cap まで）。must＝必ず入れる列（第1段の候補）"""
    blocks = []
    for k in range(1, kmax + 1):
        cp = comps_pos(UNITS, k, cap)
        if not len(cp):
            continue
        for sub in itertools.combinations(range(n), k):
            if must is not None and must not in sub:
                continue
            B = np.zeros((len(cp), n), dtype=np.int8)
            B[:, list(sub)] = cp
            blocks.append(B)
    return np.vstack(blocks)


def name_of(row, assets):
    return '/'.join(f'{a}{int(v) * STEP}' for a, v in sorted(zip(assets, row), key=lambda t: (-t[1], t[0])) if v > 0)


# ───────────────────────── 道の判定 ─────────────────────────
def gates(e, ce, now, track):
    g = {}
    eps = 1e-12
    g['①平均'] = e['mean_pi'] >= now['mean_pi'] - eps
    g['②最悪の世界'] = e['worst'] >= now['worst'] - eps
    g['⑤A2を外す'] = e['P15_noA2'] >= now['P15_noA2'] - eps
    g['⑥未来の世界だけ'] = e['P15_fwd'] >= now['P15_fwd'] - eps
    if track == 'T1':
        g['③5%未満'] = e['P5'] <= now['P5'] + eps
        g['④最大下落'] = e['mdd'] >= now['mdd'] - eps
        g['⑦過去の20年'] = e['past20'] >= now['past20'] - eps
        if ce is not None:
            g['⑧100年'] = ce['ok'] & (ce['c30med'] >= now['c30med'] - eps) & (ce['c30min'] >= now['c30min'] - eps)
    return g


def feasible(g, ok):
    f = ok.copy()
    for v in g.values():
        f &= v
    return f


def order(idx, e, A=None, pool=None, k=5000):
    """P15π の降順（0.05pt 単位に丸めて同じなら 平均→最大下落→名前）。先に P15π の上位 k だけに絞る（同点の幅より十分広い）"""
    idx = np.asarray(idx)
    if len(idx) > k:
        idx = idx[np.argsort(-e['P15'][idx], kind='stable')[:k]]
    nm = (lambda i: name_of(A[i], pool)) if A is not None else (lambda i: '')
    return sorted(idx.tolist(), key=lambda i: (-round(e['P15'][i] / TIE), -e['mean_pi'][i], -e['mdd'][i], nm(i)))


def run_forms(fast, cent, A, now, chunk=20000, need_cent=True):
    """A: (N, n) の単位の形 → 評価の配列（century は T1 の①〜⑦を通った形だけ）"""
    keys = ('ok', 'P15', 'P15_noA2', 'P15_fwd', 'P5', 'worst', 'mean_pi', 'vol', 'mdd', 'sig', 'past20')
    E = {k: np.empty(len(A), dtype=bool if k == 'ok' else np.float64) for k in keys}
    E['c30med'] = np.full(len(A), np.nan); E['c30min'] = np.full(len(A), np.nan); E['cok'] = np.zeros(len(A), bool)
    for s in range(0, len(A), chunk):
        W = A[s:s + chunk].astype(np.float64)
        e = fast.eval(W)
        for k in keys:
            E[k][s:s + chunk] = e[k]
        if need_cent:
            g = gates(e, None, now, 'T1')
            pre = feasible(g, e['ok'])
            if pre.any():
                ce = cent.eval(W[pre])
                ii = np.arange(s, min(s + chunk, len(A)))[pre]
                E['c30med'][ii] = ce['c30med']; E['c30min'][ii] = ce['c30min']; E['cok'][ii] = ce['ok']
    return E


def masks(E, now):
    ce = dict(ok=E['cok'], c30med=E['c30med'], c30min=E['c30min'])
    with np.errstate(invalid='ignore'):
        t1 = feasible(gates(E, ce, now, 'T1'), E['ok'])
        t1x = feasible(gates(E, None, now, 'T1'), E['ok'])          # ⑧を問わない（参考）
        t2 = feasible(gates(E, None, now, 'T2'), E['ok'])
    return dict(T1=t1, T1x=t1x, T2=t2, T3=E['ok'].copy())


# ───────────────────────── 自己検問 ─────────────────────────
def selfcheck(U, rows, chains, pool, fast, cent, n=150, seed=11):
    import bestpf_check as BC
    import upside_check as UC
    rng = np.random.default_rng(seed)
    F = {'今': dict(NOW)}
    cpool = [j for j in range(len(pool)) if cent.has[j]]          # 100年の写しがある本だけの形も混ぜる（century の確かめを厚く）
    for i in range(n):
        src = cpool if i % 3 == 2 else list(range(len(pool)))
        k = int(rng.integers(3, min(KMAX, len(src)) + 1))
        sub = rng.choice(src, size=k, replace=False)
        cp = comps_pos(UNITS, k, CAP)
        if not len(cp):
            continue
        row = cp[int(rng.integers(len(cp)))]
        F[f'r{i}'] = {pool[j]: int(v) * STEP for j, v in zip(sub, row)}
    mega = U.mega_map(rows, sorted(set(pool) | {'VOO'}))
    tab = U.measure(F, rows, chains, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    W = np.array([[F[nm].get(c, 0) for c in pool] for nm in F], dtype=np.float64)
    e = fast.eval(W)
    ce = cent.eval(W)
    worst = {}
    nc = 0
    for i, nm in enumerate(F):
        r = tab[nm]['_raw']
        for k, kk in (('P15', 'P15'), ('P15_noA2', 'P15_noA2'), ('P5', 'P5'), ('worst', 'worst'), ('mean_pi', 'mean_pi'),
                      ('mdd', 'mdd'), ('vol', 'vol'), ('sig', 'sig')):
            d = abs(float(e[k][i]) - float(r[kk]))
            worst[k] = max(worst.get(k, 0.0), d)
        d = abs(100 * float(e['past20'][i]) - tab[nm]['過去の転がる20年で15%以上'])
        worst['past20（表示は小数1桁）'] = max(worst.get('past20（表示は小数1桁）', 0.0), d)
        cm = U.century_monthly(F[nm])
        if cm is not None:
            c30 = cm['30年の積立（起点1965〜1995）']
            xs = sorted(c30['_v'].values())
            worst['c30med'] = max(worst.get('c30med', 0.0), abs(float(ce['c30med'][i]) - c30['_med']))
            worst['c30min'] = max(worst.get('c30min', 0.0), abs(float(ce['c30min'][i]) - xs[0]))
            nc += 1
        elif ce['ok'][i]:
            worst['century の測れる・測れないの食い違い'] = worst.get('century の測れる・測れないの食い違い', 0) + 1
    ok = all(v < 1e-9 for k, v in worst.items() if not k.startswith('past20') and not k.startswith('century')) \
        and worst.get('past20（表示は小数1桁）', 0) <= 0.05 + 1e-9 and 'century の測れる・測れないの食い違い' not in worst \
        and nc >= 30
    return {'形': len(F), '100年を測れた形': nc, '最大の差': worst, '一致': ok}


# ───────────────────────── 最終の確かめ ─────────────────────────
def lookthrough(form):
    net = ','.join(f'{LOOK_NAME.get(k, k)}={v:g}' for k, v in form.items() if v > 0)
    p = subprocess.run([sys.executable, os.path.join(BASE, 'night', 'lookthrough.py'), '--what-if', '--castle', 'MSFT=0', '--net', net],
                       capture_output=True, text=True, timeout=600, cwd=BASE)
    m = re.search(r'★指定 \S+（網 [\d.]+%）\s+(\S+) ([\d.]+)%\s+([\d.]+)〜\s*([\d.]+)%\s+(\d+)件\s+([\d.]+)%\s+NVDA\s+([\d.]+)%', p.stdout)
    if not m:
        return dict(読めず=True, 末尾=p.stdout[-300:])
    return {'最大の1銘柄': f'{m.group(1)} {m.group(2)}%', '半導体の連鎖（下限〜上限）': f'{m.group(3)}〜{m.group(4)}%',
            'NVDA（資産全体）': float(m.group(7)), '未取得': f'{m.group(6)}%'}


def final_check(U, N, rows, chains, ch_jpy, forms, track, now_name='今'):
    import bestpf_check as BC
    import upside_check as UC
    F = {now_name: dict(NOW), **forms}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    tab = U.measure(F, rows, chains, mega=mega)
    k4, _ = N.chips_adj(rows, assets)
    vt = N.variants(F, rows, chains, k4)[UC.W_CRASH]
    tj = U.measure(F, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    res = {}
    for nm in forms:
        f1 = {N.VARS_JA[v]: dict(P15=vt[nm][v]['P15'] >= vt[now_name][v]['P15'] - 1e-12,
                                 平均=vt[nm][v]['mean_pi'] >= vt[now_name][v]['mean_pi'] - 1e-12) for v in N.VARS}
        ok1 = all(x['P15'] for x in f1.values()) and (track != 'T1' or all(x['平均'] for x in f1.values()))
        rj, nj = tj[nm]['_raw'], tj[now_name]['_raw']
        ok2 = (rj['mean_pi'] >= nj['mean_pi'] - 1e-12 and rj['mdd'] >= nj['mdd'] - 1e-12) if track == 'T1' else None
        res[nm] = dict(F1=f1, F1の合否=ok1, F2の合否=ok2,
                       感度ごとの差={N.VARS_JA[v]: dict(P15=round(100 * (vt[nm][v]['P15'] - vt[now_name][v]['P15']), 2),
                                               平均=round(100 * (vt[nm][v]['mean_pi'] - vt[now_name][v]['mean_pi']), 3)) for v in N.VARS},
                       円の枠={k: tj[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最大下落')})
    return res, tab, tj


def show(t, cw=None):
    keys = ('ETF側の比', 'P15π', 'P15π（A2を外す）', 'P10π', 'P5π（5%未満）', 'P0π（元本割れ）', '世界ごとの年率', '最悪の世界',
            'π加重の平均の年率', 'ぶれ', '最大下落', '積立20年の内部収益率', '崩れ2000型_1〜3年目', '崩れ2000型_16〜18年目',
            '下落2022型_16年目', '過去の転がる20年で15%以上')
    d = {k: t[k] for k in keys if k in t}
    if cw is not None:
        d['100年の代用（30年の積立・市場との比）'] = cw
    return d


def main():
    t0 = time.time()
    check_now()
    import unx_assets as U
    import ndx_swap_check as N
    import upside_check as UC
    import bestpf_check as BC
    res = U.build()
    rows, chains = res['rows'], res['chains']
    pool = pool_list()
    miss = [c for c in pool if c not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    century_extend(U)
    fast, cent = Fast(U, rows, chains, pool), Cent(U, pool)
    sc = selfcheck(U, rows, chains, pool, fast, cent)
    log('自己検問', json.dumps(sc, ensure_ascii=False, default=str))
    if not sc['一致']:
        raise SystemExit('速い評価が measure・century_monthly と一致しない')
    if '--selfcheck' in sys.argv:
        return
    n = len(pool)
    W0 = np.array([[NOW.get(c, 0) for c in pool]], dtype=np.float64)
    e0, c0 = fast.eval(W0), cent.eval(W0)
    now = {k: float(v[0]) for k, v in {**e0, **c0}.items() if k not in ('ok',)}
    log('今', {k: round(v, 4) for k, v in now.items()})

    # ── 第0段（参考）: 核4本だけの最良＝新しい本を足さずに比を変えるだけの形 ──
    idx_core = [pool.index(c) for c in CORE]
    A4 = all_forms(4, 4, CAP)
    A = np.zeros((len(A4), n), dtype=np.int8)
    A[:, idx_core] = A4
    E = run_forms(fast, cent, A, now)
    mk = masks(E, now)
    st0 = {}
    for tr in ('T1', 'T2', 'T3'):
        ii = np.where(mk[tr])[0]
        if len(ii):
            b = order(ii, E, A, pool)[0]
            st0[tr] = dict(最良の形=name_of(A[b], pool), P15π=round(100 * E['P15'][b], 2), 今との差=round(100 * (E['P15'][b] - now['P15']), 2),
                           平均=round(100 * E['mean_pi'][b], 2), 最大下落=round(100 * E['mdd'][b], 1), 過去の20年=round(100 * E['past20'][b], 1))
        else:
            st0[tr] = None
    log('第0段（核4本だけ）', json.dumps(st0, ensure_ascii=False))

    # ── 第1段 ──
    st1 = {}
    for x in pool:
        if x in CORE:
            continue
        sub = idx_core + [pool.index(x)]
        A5 = all_forms(5, 5, CAP, must=4)
        A = np.zeros((len(A5), n), dtype=np.int8)
        A[:, sub] = A5
        E = run_forms(fast, cent, A, now)
        mk = masks(E, now)
        row = dict(形の数=len(A))
        for tr in ('T1', 'T2'):
            ii = np.where(mk[tr])[0]
            if len(ii):
                b = order(ii, E, A, pool)[0]
                row[tr] = dict(最良の形=name_of(A[b], pool), P15π=round(100 * E['P15'][b], 2),
                               今との差=round(100 * (E['P15'][b] - now['P15']), 2), 平均=round(100 * E['mean_pi'][b], 2),
                               最大下落=round(100 * E['mdd'][b], 1), 過去の20年=round(100 * E['past20'][b], 1))
            else:
                row[tr] = None
        row['100年の写し'] = bool(cent.has[pool.index(x)])
        for tr in ('T1', 'T2'):                                      # 核4本だけの最良との差＝その本を足して初めて得た分（参考）
            if row[tr] and st0.get(tr):
                row[tr]['核だけの最良との差'] = round(row[tr]['P15π'] - st0[tr]['P15π'], 2)
        st1[x] = row
        log('第1段', x, json.dumps({k: row[k] for k in ('T1', 'T2')}, ensure_ascii=False))

    def top(tr):
        c = [(x, r[tr]['今との差']) for x, r in st1.items() if r[tr] and r[tr]['今との差'] > 0]
        return [x for x, _ in sorted(c, key=lambda t: (-t[1], t[0]))[:NTOP1]]
    pick1, pick2 = top('T1'), top('T2')
    assets2 = list(CORE) + [x for x in pick1 + pick2 if x not in CORE]
    assets2 = list(dict.fromkeys(assets2))
    log('第2段の本', assets2)

    # ── 第2段 ──
    A2s = all_forms(len(assets2), KMAX, CAP)
    A = np.zeros((len(A2s), n), dtype=np.int8)
    A[:, [pool.index(c) for c in assets2]] = A2s
    log('第2段の形', len(A))
    E = run_forms(fast, cent, A, now)
    mk = masks(E, now)
    cnt = {tr: int(m.sum()) for tr, m in mk.items()}
    log('通った形の数', cnt)

    # ── 最終の確かめ ──
    ch_jpy, _ = U.jpy_chains(chains)
    picks, finals, pick_forms = {}, {}, {}
    for tr in ('T1', 'T2', 'T3'):
        ii = np.where(mk[tr])[0]
        lst = order(ii, E, A, pool)[:NFIN] if len(ii) else []
        forms = {name_of(A[i], pool): {pool[j]: int(A[i][j]) * STEP for j in range(n) if A[i][j] > 0} for i in lst}
        if tr == 'T3':
            finals[tr] = dict(上位=[dict(名前=k, P15π=round(100 * E['P15'][i], 2), 平均=round(100 * E['mean_pi'][i], 2),
                                     最大下落=round(100 * E['mdd'][i], 1)) for k, i in zip(forms, lst)][:10])
            picks[tr] = next(iter(forms), None)
            if picks[tr]:
                pick_forms[tr] = forms[picks[tr]]
            continue
        fc, tab, tj = final_check(U, N, rows, chains, ch_jpy, forms, tr) if forms else ({}, {}, {})
        ans = next((k for k in forms if fc[k]['F1の合否'] and (tr != 'T1' or fc[k]['F2の合否'])), None)
        picks[tr] = ans or '今のまま'
        if ans:
            pick_forms[tr] = forms[ans]
        finals[tr] = dict(上位=[dict(名前=k, P15π=round(100 * E['P15'][i], 2), 平均=round(100 * E['mean_pi'][i], 2),
                                 最大下落=round(100 * E['mdd'][i], 1), F1=fc[k]['F1の合否'], F2=fc[k]['F2の合否'])
                             for k, i in zip(forms, lst)], 確かめ={k: fc[k] for k in list(forms)[:10]})
        log(tr, '答え', picks[tr])

    # T1 で⑧を問わない（100年を測れない本を含む形）の最良（参考）
    ii = np.where(mk['T1x'] & ~mk['T1'])[0]
    t1x = None
    if len(ii):
        b = order(ii, E, A, pool)[0]
        t1x = dict(名前=name_of(A[b], pool), P15π=round(100 * E['P15'][b], 2), 平均=round(100 * E['mean_pi'][b], 2),
                   最大下落=round(100 * E['mdd'][b], 1), 過去の20年=round(100 * E['past20'][b], 1),
                   **{'100年': ('測れない' if not E['cok'][b] else dict(中央=round(E['c30med'][b], 3), 最悪=round(E['c30min'][b], 3)))})

    # ── 答えの形の詳しい物差し ──
    show_forms = {'今': dict(NOW)}
    for tr in ('T1', 'T2', 'T3'):
        if tr in pick_forms:
            show_forms[f'{tr}の答え'] = pick_forms[tr]
    show_forms.update(REFS)
    assets = sorted({a for f in show_forms.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    tab = U.measure(show_forms, rows, chains, mega=mega)
    detail = {}
    for nm, f in show_forms.items():
        cm = U.century_monthly(f)
        cw = None if cm is None else U.strip_century(cm)
        detail[nm] = dict(形=f, 主=show(tab[UC.W_CRASH][nm], cw), ドットコム級なし=show(tab[UC.W_DC][nm]), 中身の集中=lookthrough(f))
    tjs = U.measure(show_forms, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    for nm in show_forms:
        detail[nm]['円の枠'] = {k: tjs[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最大下落', '過去の転がる20年で15%以上')}

    # 物差しの外の候補（機械2）
    m2 = None
    try:
        j = json.load(open(os.path.join(BASE, 'out', 'etf_add_check.json')))
        m2r = j['machine2']
        m2 = dict(比べた今=m2r.get('今'), 物差し='etfcand の4つの世界（NASDAQ100 から5%を回す・この道具の物差しとは別）',
                  結果={k: dict(まとめ=v.get('まとめ'), 主=v.get('主'), 主の差=v.get('感度', {}).get('main', {}).get('Δ'))
                        for k, v in m2r['results'].items() if k in M2_ONLY})
    except Exception as x:  # noqa
        m2 = f'読めず: {x}'

    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15_check.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='歴史検証でデータと未来予測を活用してリターン15%を狙いつつ最も優れたポートフォリオ（新しい投資先も検討）',
               pi=fast.pi, pool=pool, now=NOW, now_raw=now, selfcheck=sc, stage0=st0, stage1=st1, stage2=dict(本=assets2, 形の数=int(len(A)), 通った形の数=cnt),
               picks=picks, finals=finals, T1で100年を問わない最良=t1x, detail=detail, 物差しの外の候補=m2, secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('完了', doc['secs'], '秒', picks)


if __name__ == '__main__':
    main()
