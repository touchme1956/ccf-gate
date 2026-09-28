#!/usr/bin/env python3
"""night/mw_mvo_wf.py — 角度 mvo_wf: 過去のデータだけで組む『最適化』（walk-forward）で、JKP の買いだけの良い側の三分位
（約153本）＋市場そのものを材料に、純粋な時価加重の市場に勝てるか（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」。
事前登録 out/mw_mvo_wf_prereg.json（規則・窓・縮小推定・費用・C5 の単位・Holm の族）を**測る前に**コミットしてから回す。
線は out/mw_prereg.json（C1〜C8）を night/mw_common.grade でそのまま当てる。線は結果を見て動かさない。

  python3 night/mw_mvo_wf.py             → out/mw_mvo_wf.json（全系列は out/_mw_cache/mw_mvo_wf_series.json）
  python3 night/mw_mvo_wf.py --selftest  → 先読みなし・二次計画の解・リスク均等・TE の予算を検算するだけ（戦略と市場の比較はしない）

約束（mw_common と同じ）: 月次リターンは小数・キーは yyyymm。欠測は0と読まない（ルール7）。
JKP の三分位は超過（米国T-bill を引いた値）＝French の Mkt-RF と超過どうしで比べる。総リターンは＋French RF。
"""
import sys, os, json, math, subprocess, statistics as S, time, random
for _v in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')   # 4つの子で BLAS の糸が取り合うと桁違いに遅くなる（2026-09-28 実測）
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
OUT = 'mw_mvo_wf.json'
SERIES_CACHE = os.path.join(M.CACHE, 'mw_mvo_wf_series.json')
PRE_FILES = ['mw_mvo_wf_prereg.json']
REGIONS = ['usa', 'world_ex_us', 'developed', 'emerging', 'jpn']
NMIN = 10          # 三分位の銘柄数がこれ未満の月は欠測
MINC_START = 100   # 始まりに要る材料（三分位）の数
MINC_AFTER = 30    # 始まった後、これ未満なら市場100%
WIN = 120          # 推定窓（か月）
CAP = 0.20         # 三分位1本の上限（市場は1.0）
JKP_END = 202512
COST_SWITCH = 0.003
MKT_TURN, MKT_COST = 5.0, 0.001
TE_BUDGET = {'TE2': 0.02, 'TE4': 0.04}
TR, HS, RS, PP = M.TRAIN_END, M.HOLD_START, M.RECENT_START, 201001
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


def cal(a, z):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= z:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ───────────────────────── 共通の表 ─────────────────────────
AV = json.load(open(os.path.join(BASE, 'out', '_mw_cache', 'jkp_availability.json')))
CHARS = [k for k in AV['portfolios']['usa'] if k != 'all_factors']
_FUS = json.load(open(os.path.join(BASE, 'out', 'mw_factor_us_prereg.json')))['families']['a_jkp_tercile_vw']['list']
TURN = {x['key']: (float(x['turnover_pct']), float(x['cost_per_100pct'])) for x in _FUS}
DIRECTION = {}
for _k in CHARS:
    _d = {x['direction'] for x in M.jkp_rows('usa', _k, 'factor', 'vw')}
    assert len(_d) == 1, (_k, _d)
    DIRECTION[_k] = int(float(_d.pop()))


def within_cost(k, side):
    """三分位の中の入れ替え（年%）と片道100%あたりの費用。market_equity の小型側（第1）だけ 0.60%"""
    tp, c = TURN[k]
    if k == 'market_equity':
        c = 0.006 if side == 1 else 0.003
    return tp / 100.0, c


# ───────────────────────── データ ─────────────────────────
class Region:
    def __init__(self, region, P1=None, P3=None, mkt=None, rf=None, cal_=None, chars=None):
        self.region = region
        if P1 is None:
            ch = [k for k in CHARS if k in AV['portfolios'].get(region, [])]
            d1, d3 = {}, {}
            for k in ch:
                for x in M.jkp_rows(region, k, 'portfolios', 'vw'):
                    if x['ret'] in ('', 'NA', 'na') or x['pf'] not in ('1.0', '3.0'):
                        continue
                    n = x.get('n')
                    if n not in (None, '', 'NA', 'na') and float(n) < NMIN:
                        continue
                    (d1 if x['pf'] == '1.0' else d3).setdefault(k, {})[M._ym(x['date'])] = float(x['ret'])
            ff = M.ff_factors()
            mk = dict(ff['mktrf']) if region == 'usa' else M.jkp_mkt(region, 'vw')
            allm = [m for dd in (d1, d3) for s in dd.values() for m in s] + list(mk)
            self.cal = cal(min(allm), JKP_END)
            T = len(self.cal)
            idx = {m: i for i, m in enumerate(self.cal)}
            self.chars = ch
            self.P1 = np.full((T, len(ch)), np.nan)
            self.P3 = np.full((T, len(ch)), np.nan)
            for j, k in enumerate(ch):
                for m, v in d1.get(k, {}).items():
                    if m in idx:
                        self.P1[idx[m], j] = v
                for m, v in d3.get(k, {}).items():
                    if m in idx:
                        self.P3[idx[m], j] = v
            self.mkt = np.array([mk.get(m, np.nan) for m in self.cal])
            self.rf = np.array([ff['rf'].get(m, np.nan) for m in self.cal])
        else:
            self.P1, self.P3, self.mkt, self.rf, self.cal, self.chars = P1, P3, mkt, rf, cal_, chars
        self._prep()

    def _prep(self):
        T, K = self.P1.shape
        self.T, self.K = T, K
        self.dir = np.array([DIRECTION[k] for k in self.chars], dtype=float)
        V1, V3 = np.isfinite(self.P1), np.isfinite(self.P3)
        VB = V1 & V3
        F = np.where(VB, self.dir * (np.nan_to_num(self.P3) - np.nan_to_num(self.P1)), 0.0)
        z = np.zeros((1, K))
        self.cumF = np.vstack([z, np.cumsum(F, 0)])        # cumF[i+1] = 0..i の和
        self.cumNF = np.vstack([z, np.cumsum(VB, 0)])
        self.cumV1 = np.vstack([z, np.cumsum(V1, 0)])
        self.cumV3 = np.vstack([z, np.cumsum(V3, 0)])
        self.cumP1 = np.vstack([z, np.cumsum(np.nan_to_num(self.P1), 0)])
        self.cumP3 = np.vstack([z, np.cumsum(np.nan_to_num(self.P3), 0)])
        VM = np.isfinite(self.mkt)
        self.cumVM = np.concatenate([[0], np.cumsum(VM)])
        self.cumM = np.concatenate([[0], np.cumsum(np.nan_to_num(self.mkt))])
        self.V1, self.V3, self.VM = V1, V3, VM
        # 最初の組み入れの日（12月）
        self.i0 = None
        for i in range(WIN - 1, T - 1):
            if self.cal[i] % 100 != 12:
                continue
            if self.cumVM[i + 1] - self.cumVM[i + 1 - WIN] < WIN or not VM[i + 1]:
                continue
            ks, _ = self.eligible(i)
            if len(ks) >= MINC_START:
                self.i0 = i
                break
        self.origin = self.i0 - (WIN - 1) if self.i0 is not None else None

    def sides(self, i):
        """月末 i の良い側（True=第3）。t までの符号つき因子の平均の符号（0 は向きの側）"""
        n = self.cumNF[i + 1]
        mean = np.where(n > 0, self.cumF[i + 1] / np.maximum(n, 1), 0.0)
        dir_side3 = self.dir > 0
        s3 = np.where(mean >= 0, dir_side3, ~dir_side3)
        return s3, n

    def eligible(self, i):
        """月末 i に材料になれる特性の列番号と側（True=第3）"""
        s3, n = self.sides(i)
        lo = i + 1 - WIN
        if lo < 0 or i + 1 >= self.T:
            return np.array([], dtype=int), s3
        full1 = (self.cumV1[i + 1] - self.cumV1[lo]) == WIN
        full3 = (self.cumV3[i + 1] - self.cumV3[lo]) == WIN
        nx1, nx3 = self.V1[i + 1], self.V3[i + 1]
        ok = (n >= WIN) & np.where(s3, full3 & nx3, full1 & nx1)
        return np.where(ok)[0], s3


# ───────────────────────── 推定 ─────────────────────────
def lw_cc(X):
    """Ledoit-Wolf（2004）定相関の目標への縮小（covCor.m と同じ式）。X は T×N の生のリターン"""
    T, N = X.shape
    Xc = X - X.mean(0)
    Sm = Xc.T @ Xc / T
    var = np.diag(Sm).copy()
    sd = np.sqrt(var)
    R = Sm / np.outer(sd, sd)
    rbar = (R.sum() - N) / (N * (N - 1))
    Fm = rbar * np.outer(sd, sd)
    np.fill_diagonal(Fm, var)
    Y = Xc ** 2
    phiMat = Y.T @ Y / T - Sm ** 2
    phi = phiMat.sum()
    theta = (Xc ** 3).T @ Xc / T - var[:, None] * Sm
    np.fill_diagonal(theta, 0.0)
    rho = np.trace(phiMat) + rbar * ((1.0 / sd)[:, None] * sd[None, :] * theta).sum()
    gamma = ((Sm - Fm) ** 2).sum()
    kappa = (phi - rho) / gamma
    delta = max(0.0, min(1.0, kappa / T))
    return delta * Fm + (1 - delta) * Sm, delta


def js_shrink(mu, Sig, T):
    """James-Stein（正の部分）で横断面の総平均へ"""
    N = len(mu)
    mbar = mu.mean()
    dv = mu - mbar
    d = float(dv @ np.linalg.solve(Sig, dv))
    phi = 1.0 if d <= 0 else min(1.0, max(0.0, (N - 3) / (T * d)))
    return mbar + (1 - phi) * dv, phi


# ───────────────────────── 二次計画 ─────────────────────────
def proj_box_budget(v, lo, up):
    """{Σw=1, lo≤w≤up} への射影（τ の二分法）"""
    a, b = float(np.min(v - up)), float(np.max(v - lo))
    for _ in range(200):
        t = 0.5 * (a + b)
        s = np.clip(v - t, lo, up).sum()
        if s > 1:
            a = t
        else:
            b = t
        if b - a < 1e-16:
            break
    return np.clip(v - 0.5 * (a + b), lo, up)


def qp_fista(Q, c, lo, up, w0=None, iters=20000, tol=1e-12):
    """min ½w'Qw − c'w s.t. Σw=1, lo≤w≤up を射影勾配（FISTA・再起動つき）で。検算と予備の解法"""
    n = len(c)
    Lc = float(np.linalg.eigvalsh(Q)[-1]) * 1.0001
    x = proj_box_budget(np.full(n, 1.0 / n) if w0 is None else w0, lo, up)
    y, tk = x.copy(), 1.0
    fold = 0.5 * x @ Q @ x - c @ x
    for it in range(iters):
        g = Q @ y - c
        xn = proj_box_budget(y - g / Lc, lo, up)
        tn = (1 + math.sqrt(1 + 4 * tk * tk)) / 2
        y = xn + ((tk - 1) / tn) * (xn - x)
        fn = 0.5 * xn @ Q @ xn - c @ xn
        if fn > fold:           # 再起動
            y, tn = xn.copy(), 1.0
        if np.max(np.abs(xn - x)) < tol:
            x = xn
            break
        x, tk, fold = xn, tn, fn
    return x


QP_STATS = {'pdas': 0, 'fallback': 0, 'iters': 0}


def qp(Q, c, lo, up, w0=None, maxit=300, _polish=True):
    """min ½w'Qw − c'w s.t. Σw=1, lo≤w≤up。主双対の有効制約法（PDAS）、収束しなければ FISTA → その有効集合から PDAS で仕上げ"""
    n = len(c)
    w = proj_box_budget(np.full(n, 1.0 / n) if w0 is None else w0, lo, up)
    L = w <= lo + 1e-12
    U = (w >= up - 1e-12) & ~L
    seen = set()
    for it in range(maxit):
        F = ~(L | U)
        wA = np.where(L, lo, np.where(U, up, 0.0))
        nf = int(F.sum())
        if nf == 0:
            h = Q @ wA - c
            s = wA.sum()
            if abs(s - 1) < 1e-12:
                lo_nu = float(np.max(-h[L])) if L.any() else -np.inf
                hi_nu = float(np.min(-h[U])) if U.any() else np.inf
                if lo_nu <= hi_nu + 1e-15:
                    QP_STATS['pdas'] += 1; QP_STATS['iters'] += it
                    return wA
            L2, U2 = L.copy(), U.copy()
            if s <= 1 and L.any():
                j = np.where(L)[0][np.argmin(h[L])]; L2[j] = False
            if s >= 1 and U.any():
                j = np.where(U)[0][np.argmax(h[U])]; U2[j] = False
            if (L2 == L).all() and (U2 == U).all():
                break
            L, U = L2, U2
            continue
        iF = np.where(F)[0]
        iA = np.where(~F)[0]
        Kmat = np.empty((nf + 1, nf + 1))
        Kmat[:nf, :nf] = Q[np.ix_(iF, iF)]
        Kmat[:nf, nf] = 1.0
        Kmat[nf, :nf] = 1.0
        Kmat[nf, nf] = 0.0
        rhs = np.empty(nf + 1)
        rhs[:nf] = c[iF] - (Q[np.ix_(iF, iA)] @ wA[iA] if len(iA) else 0.0)
        rhs[nf] = 1.0 - wA[iA].sum()
        try:
            sol = np.linalg.solve(Kmat, rhs)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(Kmat, rhs, rcond=None)[0]
        w = wA.copy()
        w[iF] = sol[:nf]
        nu = sol[nf]
        g = Q @ w - c + nu
        newL = np.where(L, g > 0, w < lo - 1e-15)
        newU = np.where(U, g < 0, w > up + 1e-15)
        if (newL == L).all() and (newU == U).all():
            QP_STATS['pdas'] += 1; QP_STATS['iters'] += it
            return np.clip(w, lo, up)
        key = (newL.tobytes(), newU.tobytes())
        if key in seen:
            break
        seen.add(key)
        L, U = newL, newU
    if not _polish:
        return None
    QP_STATS['fallback'] += 1
    wf = qp_fista(Q, c, lo, up, w0=w)
    wp = qp(Q, c, lo, up, wf, maxit=maxit, _polish=False)
    if wp is not None:
        QP_STATS['polished'] = QP_STATS.get('polished', 0) + 1
        of = 0.5 * wf @ Q @ wf - c @ wf
        op = 0.5 * wp @ Q @ wp - c @ wp
        return wp if op <= of + 1e-13 * (1 + abs(of)) else wf
    return wf


def lp_max(mu, up):
    """max μ'w（Σw=1, 0≤w≤up）＝平均の高い順に上限まで詰める"""
    w = np.zeros(len(mu))
    rem = 1.0
    for j in np.argsort(-mu, kind='stable'):
        a = min(up[j], rem)
        w[j] = a
        rem -= a
        if rem <= 1e-15:
            break
    return w


def _illinois(fun, a, fa, b, fb, rtol=1e-9, maxit=80):
    """fun(u) の根を [a,b]（fa>0>fb）で。Illinois 法。戻り値 u"""
    side = 0
    for _ in range(maxit):
        u = (a * fb - b * fa) / (fb - fa)
        if not (min(a, b) < u < max(a, b)):
            u = 0.5 * (a + b)
        fu = fun(u)
        if fu == 0 or abs(b - a) < rtol:
            return u
        if fu > 0:
            a, fa = u, fu
            if side == 1:
                fb /= 2
            side = 1
        else:
            b, fb = u, fu
            if side == -1:
                fa /= 2
            side = -1
    return 0.5 * (a + b)


def max_sharpe(mu, Sig, lo, up, w0=None, lam0=None):
    """最大シャープ（買いだけ・上限つき）。λ の不動点 λ = μ'w(λ)/w(λ)'Σw(λ) を対数の Illinois 法で。平均が正の組み合わせが無ければ None"""
    wlp = lp_max(mu, up)
    if mu @ wlp <= 0:
        return None, None
    cache = {}
    state = {'w': w0}
    muc = mu - mu.mean()   # Σw=1 なので定数を足しても二次計画の解は同じ（λ が小さいときの桁落ちを避ける）

    def sol(u):
        if u not in cache:
            w = qp(Sig, muc / math.exp(u), lo, up, state['w'])
            state['w'] = w
            cache[u] = w
        return cache[u]

    def f(u):  # log h(λ) − log λ（h≤0 なら −大）
        w = sol(u)
        m = mu @ w
        v = w @ Sig @ w
        if m <= 0:
            return -50.0
        return math.log(m / v) - u

    u0 = math.log(lam0) if lam0 else math.log(max(1e-6, (mu @ wlp) / (wlp @ Sig @ wlp)))
    f0 = f(u0)
    a = b = u0
    fa = fb = f0
    step = 1.0
    it = 0
    if f0 > 0:
        while fb > 0 and it < 60:
            b = b + step; step *= 2; fb = f(b); it += 1
    else:
        while fa <= 0 and it < 60:
            a = a - step; step *= 2; fa = f(a); it += 1
    if fa > 0 and fb <= 0:
        u = _illinois(f, a, fa, b, fb)
    else:
        u = b if fb > 0 else a
    w = sol(u)
    # 検算: 前後でシャープが上がらないこと（上がれば黄金分割）
    shp = lambda w_: (mu @ w_) / math.sqrt(w_ @ Sig @ w_)
    s0 = shp(w)
    worse = [shp(qp(Sig, muc / math.exp(u + d), lo, up, w)) for d in (-0.2, 0.2)]
    if max(worse) > s0 + 1e-10:
        gr = (math.sqrt(5) - 1) / 2
        x0, x1 = u - 12, u + 12
        c1, c2 = x1 - gr * (x1 - x0), x0 + gr * (x1 - x0)
        s1, s2 = shp(sol(c1)), shp(sol(c2))
        for _ in range(80):
            if s1 < s2:
                x0, c1, s1 = c1, c2, s2
                c2 = x0 + gr * (x1 - x0); s2 = shp(sol(c2))
            else:
                x1, c2, s2 = c2, c1, s1
                c1 = x1 - gr * (x1 - x0); s1 = shp(sol(c1))
        u = c1 if s1 >= s2 else c2
        w = sol(u)
        QP_STATS['golden'] = QP_STATS.get('golden', 0) + 1
    return w, math.exp(u)


def te_opt(mu, Sig, bvec, lo, up, te_m, w0=None, lam0=None):
    """max μ'w s.t. (w−b)'Σ(w−b) ≤ te_m²。max μ'w − (λ/2)(w−b)'Σ(w−b) の λ を事前の TE が予算に一致するまで探す"""
    Sb = Sig @ bvec
    cache = {}
    state = {'w': w0}
    muc = mu - mu.mean()   # Σw=1 なので定数を足しても解は同じ

    def sol(u):
        if u not in cache:
            w = qp(Sig, Sb + muc / math.exp(u), lo, up, state['w'])
            state['w'] = w
            cache[u] = w
        return cache[u]

    def te(w):
        a = w - bvec
        return math.sqrt(max(0.0, a @ Sig @ a))

    def f(u):
        t = te(sol(u))
        if t <= 1e-14:
            return -50.0
        return math.log(t / te_m)

    ulo = math.log(1e-8)
    if f(ulo) <= 0:           # λ を下限まで下げても予算内
        return sol(ulo), 1e-8
    u0 = math.log(lam0) if lam0 else 0.0
    f0 = f(u0)
    a = b = u0
    fa = fb = f0
    step = 1.0
    it = 0
    if f0 > 0:
        while fb > 0 and it < 60:
            b = b + step; step *= 2; fb = f(b); it += 1
    else:
        while fa <= 0 and it < 60:
            a = max(ulo, a - step); step *= 2; fa = f(a); it += 1
            if a == ulo:
                break
    if fa > 0 and fb <= 0:
        u = _illinois(f, a, fa, b, fb, rtol=1e-7)
        # 予算を少しでも超えたら大きい側へ
        w = sol(u)
        if te(w) > te_m * 1.001:
            u = b
    else:
        u = b
    return sol(u), math.exp(u)


def erc(Sig, maxit=100):
    """リスク均等: min ½y'Σy − (1/N)Σlog y のニュートン法 → w = y/Σy"""
    n = Sig.shape[0]
    y = 1.0 / np.sqrt(np.diag(Sig))
    y *= 1.0 / math.sqrt(y @ Sig @ y)
    fval = lambda y_: 0.5 * y_ @ Sig @ y_ - np.log(y_).sum() / n
    for _ in range(maxit):
        g = Sig @ y - 1.0 / (n * y)
        if np.max(np.abs(g * y)) < 1e-13:
            break
        H = Sig + np.diag(1.0 / (n * y * y))
        dy = np.linalg.solve(H, g)
        t = 1.0
        while np.any(y - t * dy <= 0):
            t *= 0.5
        f0 = fval(y)
        while fval(y - t * dy) > f0 - 1e-4 * t * (g @ dy) and t > 1e-12:
            t *= 0.5
        y = y - t * dy
    return y / y.sum()


# ───────────────────────── 目標の重み ─────────────────────────
RULES_T = ['MS_E', 'MS_R', 'MSraw_R', 'TE2_E', 'TE2_R', 'TE4_E', 'TE4_R', 'MV', 'RP', 'POS10', 'EW']


class Targets:
    """地域ごとに、月末 i の目標の重み（材料の id → 重み）を規則ごとに作る"""

    def __init__(self, R):
        self.R = R
        self.prev = {}      # 規則 → (ids, w, λ) の温め
        self.diag = {}      # i → 診断

    def blocks(self, i):
        R = self.R
        ks, s3 = R.eligible(i)
        mk_ok = (R.cumVM[i + 1] - R.cumVM[i + 1 - WIN] == WIN) and R.VM[i + 1]
        return ks, s3, mk_ok

    def compute(self, i, rules=RULES_T):
        R = self.R
        ks, s3, mk_ok = self.blocks(i)
        ids = [(R.chars[k], 3 if s3[k] else 1) for k in ks]
        if not mk_ok:
            raise RuntimeError(f'{R.region} {R.cal[i]}: 市場の履歴が欠ける')
        if len(ks) < MINC_AFTER:
            return {r: {'MKT': 1.0} for r in rules}, {'n_blocks': len(ks), 'fallback_market': True}
        lo_ = i + 1 - WIN
        cols = [R.P3[lo_:i + 1, k] if s3[k] else R.P1[lo_:i + 1, k] for k in ks]
        X = np.column_stack(cols + [R.mkt[lo_:i + 1]])
        assert np.isfinite(X).all()
        ids_all = ids + ['MKT']
        N = X.shape[1]
        Sig, delta = lw_cc(X)
        muR = X.mean(0)
        # 拡大窓の平均（原点から i まで・値のある月だけ）
        o = max(R.origin, 0)
        cnt = np.array([(R.cumV3[i + 1, k] - R.cumV3[o, k]) if s3[k] else (R.cumV1[i + 1, k] - R.cumV1[o, k]) for k in ks]
                       + [R.cumVM[i + 1] - R.cumVM[o]], dtype=float)
        sm = np.array([(R.cumP3[i + 1, k] - R.cumP3[o, k]) if s3[k] else (R.cumP1[i + 1, k] - R.cumP1[o, k]) for k in ks]
                      + [R.cumM[i + 1] - R.cumM[o]])
        muE = sm / cnt
        TE_js = float(np.median(cnt))
        up = np.full(N, CAP); up[-1] = 1.0
        lo = np.zeros(N)
        b = np.zeros(N); b[-1] = 1.0
        out, dg = {}, {'n_blocks': len(ks), 'lw_delta': round(delta, 4)}
        mus = {}
        if any(r.endswith('_R') and not r.startswith('MSraw') for r in rules):
            mus['R'], dg['js_phi_R'] = js_shrink(muR, Sig, WIN)
        if any(r.endswith('_E') for r in rules):
            mus['E'], dg['js_phi_E'] = js_shrink(muE, Sig, TE_js)
            dg['T_js_E'] = TE_js

        def warm(rule):
            p = self.prev.get(rule)
            if not p:
                return None, None
            pid, pw, plam = p
            m = dict(zip(pid, pw))
            w0 = np.array([m.get(x, 0.0) for x in ids_all])
            if w0.sum() <= 0:
                return None, plam
            return w0 / w0.sum(), plam

        for rule in rules:
            if rule in ('MS_E', 'MS_R', 'MSraw_R'):
                mu = muR if rule == 'MSraw_R' else mus[rule[-1]]
                w0, lam0 = warm(rule)
                w, lam = max_sharpe(mu, Sig, lo, up, w0, lam0)
                if w is None:
                    w, lam = b.copy(), None
                    dg.setdefault('ms_fallback', []).append(rule)
            elif rule.startswith('TE'):
                mu = mus[rule[-1]]
                w0, lam0 = warm(rule)
                te_m = TE_BUDGET[rule[:3]] / math.sqrt(12)
                w, lam = te_opt(mu, Sig, b, lo, up, te_m, w0, lam0)
                a = w - b
                dg[f'te_exante_{rule}'] = round(math.sqrt(max(0, a @ Sig @ a)) * math.sqrt(12), 5)
            elif rule == 'MV':
                w0, _ = warm(rule)
                w, lam = qp(Sig, np.zeros(N), lo, up, w0), None
            elif rule == 'RP':
                w, lam = erc(Sig), None
            elif rule == 'POS10':
                act = X[:, :-1].mean(0) - X[:, -1].mean()
                sel = act > 0
                w = np.zeros(N)
                if sel.any():
                    w[:-1][sel] = 1.0 / sel.sum()
                else:
                    w[-1] = 1.0
                lam = None
            elif rule == 'EW':
                w, lam = np.full(N, 1.0 / N), None
            else:
                raise KeyError(rule)
            w = np.where(w < 1e-10, 0.0, w)
            w = w / w.sum()
            self.prev[rule] = (ids_all, w, lam)
            out[rule] = {x: float(v) for x, v in zip(ids_all, w) if v > 0}
        return out, dg


# ───────────────────────── 持つ・費用 ─────────────────────────
def block_ret(R, bid, j):
    if bid == 'MKT':
        v = R.mkt[j]
    else:
        k = R.chars.index(bid[0]) if not hasattr(R, '_cidx') else R._cidx[bid[0]]
        v = R.P3[j, k] if bid[1] == 3 else R.P1[j, k]
    return v if np.isfinite(v) else None


def simulate(R, targets, freq):
    """targets: {i: {id: w}}。freq 'M' or 'A'。戻り値: 超過（費用前・後）・回転・重みの診断"""
    R._cidx = {k: j for j, k in enumerate(R.chars)}
    held = None
    gross, net, sw_turn, wi_turn, cost_m = {}, {}, {}, {}, {}
    wstats = []
    missing = 0
    iend = R.T - 1
    for i in range(R.i0, iend):
        rebal = (freq == 'M') or (R.cal[i] % 100 == 12)
        sw = 0.0
        if rebal:
            tgt = targets[i]
            if held is not None:
                keys = set(tgt) | set(held)
                sw = 0.5 * sum(abs(tgt.get(x, 0.0) - held.get(x, 0.0)) for x in keys)
            held = dict(tgt)
        j = i + 1
        rs = {}
        for bid in list(held):
            v = block_ret(R, bid, j)
            if v is None:
                missing += 1
                continue
            rs[bid] = v
        if len(rs) < len(held):
            tot = sum(held[b_] for b_ in rs)
            held = {b_: held[b_] / tot for b_ in rs}
        pr = sum(held[b_] * rs[b_] for b_ in held)
        wt, wc = 0.0, 0.0
        for b_, w_ in held.items():
            if b_ == 'MKT':
                tp, c = MKT_TURN / 100.0, MKT_COST
            else:
                tp, c = within_cost(b_[0], b_[1])
            wt += w_ * tp
            wc += w_ * tp / 12 * c
        cm = sw * COST_SWITCH + wc
        ym = R.cal[j]
        gross[ym] = pr
        net[ym] = pr - cm
        sw_turn[ym] = sw
        wi_turn[ym] = wt / 12
        cost_m[ym] = cm
        wstats.append((ym, held.get('MKT', 0.0), sum(1 for v in held.values() if v > 0.01), dict(held)))
        rf = R.rf[j]
        grow = {b_: held[b_] * (1 + rs[b_] + rf) for b_ in held}
        tot = sum(grow.values())
        held = {b_: v / tot for b_, v in grow.items()}
    return {'gross': gross, 'net': net, 'switch': sw_turn, 'within': wi_turn, 'cost': cost_m, 'missing': missing, 'w': wstats}


# ───────────────────────── 地域ごとの計算 ─────────────────────────
def run_region(region):
    t0 = time.time()
    R = Region(region)
    log(f'{region}: 特性 {len(R.chars)}・暦 {R.cal[0]}〜{R.cal[-1]}・最初の組み入れ {R.cal[R.i0]}・原点 {R.cal[R.origin]}')
    TG = Targets(R)
    tg = {r: {} for r in RULES_T}
    diag = {}
    for i in range(R.i0, R.T - 1):
        out, dg = TG.compute(i)
        for r in RULES_T:
            tg[r][i] = out[r]
        diag[R.cal[i]] = dg
        if R.cal[i] % 100 == 12 and (R.cal[i] // 100) % 5 == 0:
            log(f'  {region} {R.cal[i]} 材料 {dg["n_blocks"]} δ={dg["lw_delta"]} φR={dg.get("js_phi_R")} φE={dg.get("js_phi_E")} '
                f'{time.time() - t0:.0f}s QP {QP_STATS}')
    res = {}
    for r in RULES_T:
        for f in ('M', 'A'):
            res[f'{r}_{f}'] = simulate(R, tg[r], f)
    bm = {R.cal[j]: float(R.mkt[j]) for j in range(R.T) if np.isfinite(R.mkt[j])}
    rf = {R.cal[j]: float(R.rf[j]) for j in range(R.T) if np.isfinite(R.rf[j])}
    log(f'{region}: 完了 {time.time() - t0:.0f}s QP {QP_STATS}')
    return region, {'res': res, 'diag': diag, 'bm': bm, 'rf': rf, 'start': R.cal[R.i0 + 1], 'first_rebal': R.cal[R.i0],
                    'origin': R.cal[R.origin], 'qp': dict(QP_STATS)}


# ───────────────────────── 集計 ─────────────────────────
NAME = {  # 規則_頻度 → 事前登録の名前
}
for r in RULES_T:
    for f in ('M', 'A'):
        NAME[f'{r}_{f}'] = f'{r}_{f}'


def total(ex, rf):
    return {k: v + rf[k] for k, v in ex.items() if k in rf}


def summarize(region, key, sim, bm, rf, ew_gross=None, jkp_us=None):
    g, n = sim['gross'], sim['net']
    E = M.excess_stats
    st = {'region': region, 'rule': key, 'name': f'{region}:{key}', 'start': min(g), 'end': max(g)}
    st['full'] = E(g, bm); st['train'] = E(g, bm, z=TR); st['hold'] = E(g, bm, a=HS)
    st['recent'] = E(g, bm, a=RS); st['postpub_2010'] = E(g, bm, a=PP)
    st['net_full'] = E(n, bm); st['net_train'] = E(n, bm, z=TR); st['net_hold'] = E(n, bm, a=HS); st['net_recent'] = E(n, bm, a=RS)
    ts, tb, tn = total(g, rf), total(bm, rf), total(n, rf)
    tb = {k: v for k, v in tb.items() if k in ts}
    st['roll20'] = M.rolling(ts, tb, 20); st['roll20_net'] = M.rolling(tn, tb, 20)
    st['dca20'] = M.dca(ts, tb, 20); st['dca20_net'] = M.dca(tn, tb, 20)
    st['sharpe'] = {'train': [M.sharpe(ts, rf, z=TR), M.sharpe(tb, rf, z=TR)], 'hold': [M.sharpe(ts, rf, a=HS), M.sharpe(tb, rf, a=HS)]}
    st['maxdd'] = {'s': round(M.maxdd(ts) * 100, 1), 'b': round(M.maxdd(tb) * 100, 1)}

    def turn(a=None, z=None):
        ks = [k for k in sim['switch'] if (a is None or k >= a) and (z is None or k <= z)]
        if not ks:
            return None
        yrs = len(ks) / 12
        return {'switch_pct': round(sum(sim['switch'][k] for k in ks) / yrs * 100, 1),
                'within_pct': round(sum(sim['within'][k] for k in ks) / yrs * 100, 1),
                'cost_pct_per_year': round(sum(sim['cost'][k] for k in ks) / yrs * 100, 3)}
    st['turnover_full'] = turn(); st['turnover_hold'] = turn(a=HS)
    th = st['turnover_hold']
    if th:  # 検算: apply_cost に平均の回転率を入れた版（三分位の中の費用も 0.30% で近似）
        ac = M.apply_cost(window_(g, HS), (th['switch_pct'] + th['within_pct']) / 100, COST_SWITCH)
        st['net_hold_apply_cost_check'] = E(ac, bm, a=HS)
    st['missing_in_hold'] = sim['missing']
    wh = [x for x in sim['w'] if x[0] >= HS]
    if wh:
        st['avg_market_weight_hold'] = round(S.mean(x[1] for x in wh), 3)
        st['avg_blocks_over_1pct_hold'] = round(S.mean(x[2] for x in wh), 1)
        agg = {}
        for _, _, _, hw in wh:
            for b_, v in hw.items():
                agg[b_] = agg.get(b_, 0.0) + v / len(wh)
        top = sorted(agg.items(), key=lambda x: -x[1])[:10]
        st['top_blocks_hold'] = [[('MKT' if b_ == 'MKT' else f'{b_[0]}:{"高" if b_[1] == 3 else "低"}'), round(v, 3)] for b_, v in top]
    wa = [x for x in sim['w'] if x[0] <= TR]
    if wa:
        st['avg_market_weight_train'] = round(S.mean(x[1] for x in wa), 3)
    if ew_gross is not None:
        st['vs_EW_M_hold'] = E(g, ew_gross, a=HS)
        st['vs_EW_M_full'] = E(g, ew_gross)
    if jkp_us is not None:
        st['vs_jkp_usa_mkt_vw_hold'] = E(g, jkp_us, a=HS)
        st['vs_jkp_usa_mkt_vw_full'] = E(g, jkp_us)
    return st


def window_(d, a=None, z=None):
    return {k: v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)}


def main():
    t0 = time.time()
    pre = os.path.join('out', PRE_FILES[0])
    prereg_sha = sha_of(pre)
    if not prereg_sha:
        log('⚠ 事前登録がコミットされていない。測る前にコミットすること')
        sys.exit(1)
    # 健全性
    ff = M.ff_factors()
    m = ff['mkt']
    sanity = {'french_mkt_cagr_full': round(M.cagr(m) * 100, 2), 'french_mkt_from': min(m), 'french_mkt_to': max(m),
              'french_mkt_cagr_2007_': round(M.cagr(M.window(m, HS)) * 100, 2)}
    jus = M.jkp_mkt('usa', 'vw')
    dd = M.excess_stats(jus, ff['mktrf'])
    dd7 = M.excess_stats(jus, ff['mktrf'], a=HS)
    sanity['jkp_usa_mkt_vw_minus_french_full'] = dd['ex_ann']
    sanity['jkp_usa_mkt_vw_minus_french_2007_'] = dd7['ex_ann']
    log('健全性', sanity)
    import multiprocessing as mp
    with mp.Pool(min(4, len(REGIONS))) as pool:
        got = dict(pool.map(run_region, REGIONS))
    # 系列の保存（キャッシュ・gitignore）
    ser = {reg: {k: {'gross': {str(a): round(b, 7) for a, b in v['gross'].items()},
                     'net': {str(a): round(b, 7) for a, b in v['net'].items()}} for k, v in got[reg]['res'].items()}
           for reg in REGIONS}
    for reg in REGIONS:
        ser[reg]['_benchmark_excess'] = {str(a): b for a, b in got[reg]['bm'].items()}
    json.dump(ser, open(SERIES_CACHE, 'w'))
    tested = []
    for reg in REGIONS:
        G = got[reg]
        ew = G['res']['EW_M']['gross']
        for key, sim in G['res'].items():
            st = summarize(reg, key, sim, G['bm'], G['rf'], ew_gross=(ew if key != 'EW_M' else None),
                           jkp_us=(jus if reg == 'usa' else None))
            tested.append(st)
    # Holm（主の族 110 本・保有期間の費用前 p）
    pv = {s['name']: (s['hold']['p'] if s['hold'] else None) for s in tested}
    holm_all = M.holm(pv)
    holm_reg = {}
    for reg in REGIONS:
        holm_reg.update(M.holm({k: v for k, v in pv.items() if k.startswith(reg + ':')}))
    byname = {s['name']: s for s in tested}
    for s in tested:
        others = [r for r in REGIONS if r != s['region']]
        pos, detail = 0, {}
        for r in others:
            o = byname.get(f'{r}:{s["rule"]}')
            v = o['net_full']['ex_ann'] if o and o.get('net_full') else None
            detail[r] = v
            if v is not None and v > 0:
                pos += 1
        s['repl'] = {'regions': len(others), 'positive': pos, 'net_full_ex_ann': detail}
        s['holm_p_family110'] = holm_all.get(s['name'])
        s['holm_p_region22_reference'] = holm_reg.get(s['name'])
        g, c = M.grade(s['full'], s['train'], s['hold'], s['roll20'], cost_hold=s['net_hold'], repl=s['repl'],
                       family_holm_p=s['holm_p_family110'])
        s['grade'], s['criteria'] = g, c
        s['primary'] = True
        s['family'] = 'P_primary_110'
    counts = {gg: sum(1 for s in tested if s['grade'] == gg) for gg in 'SABC'}
    log('格付け', counts)
    for s in sorted(tested, key=lambda s: -(s['net_hold']['ex_ann'] if s['net_hold'] else -99))[:15]:
        log(f"  {s['name']:28s} {s['grade']} 保有 {s['hold']['ex_ann']:+.2f} t{s['hold']['t']} 費用後 {s['net_hold']['ex_ann']:+.2f} "
            f"訓練 {s['train']['ex_ann'] if s['train'] else None} t{s['train']['t'] if s['train'] else None} 全 t{s['full']['t']} "
            f"20年勝率 {s['roll20']['win_rate'] if s['roll20'] else None} C5 {s['repl']['positive']}/4")
    diag_summary = {}
    for reg in REGIONS:
        dg = got[reg]['diag']
        vals = lambda k, a=None, z=None: [v[k] for m_, v in dg.items() if k in v and (a is None or m_ >= a) and (z is None or m_ <= z)]
        diag_summary[reg] = {'first_rebalance': got[reg]['first_rebal'], 'first_holding_month': got[reg]['start'], 'estimation_origin': got[reg]['origin'],
                             'n_blocks_first': dg[min(dg)]['n_blocks'], 'n_blocks_last': dg[max(dg)]['n_blocks'],
                             'lw_delta_mean': round(S.mean(vals('lw_delta')), 3),
                             'js_phi_R_mean_train': round(S.mean(vals('js_phi_R', z=TR)), 3) if vals('js_phi_R', z=TR) else None,
                             'js_phi_R_mean_hold': round(S.mean(vals('js_phi_R', a=HS - 1)), 3),
                             'js_phi_E_mean_train': round(S.mean(vals('js_phi_E', z=TR)), 3) if vals('js_phi_E', z=TR) else None,
                             'js_phi_E_mean_hold': round(S.mean(vals('js_phi_E', a=HS - 1)), 3),
                             'te_exante_mean': {r: round(S.mean(vals(f'te_exante_{r}')), 4) for r in ('TE2_E', 'TE2_R', 'TE4_E', 'TE4_R')},
                             'ms_fallback_months': sum(1 for v in dg.values() if v.get('ms_fallback')),
                             'market_fallback_months': sum(1 for v in dg.values() if v.get('fallback_market')),
                             'qp': got[reg]['qp']}
    # emerging の費用2倍（報告のみ）
    sens = []
    for key, sim in got['emerging']['res'].items():
        n2 = {k: sim['gross'][k] - 2 * sim['cost'][k] for k in sim['gross']}
        e = M.excess_stats(n2, got['emerging']['bm'], a=HS)
        sens.append({'name': f'emerging:{key}', 'net_hold_cost2x': e})
    obj = {'angle': 'mvo_wf', 'prereg': {'file': f'out/{PRE_FILES[0]}', 'commit': prereg_sha},
           'global_prereg': 'out/mw_prereg.json', 'sanity': sanity,
           'benchmark': {'usa': 'French Mkt-RF（超過・上限なしの時価加重）', 'others': 'その地域の JKP mkt vw（超過）'},
           'n_tested': len(tested), 'grade_counts': counts,
           'families': {'P_primary_110': {'primary': True, 'n': len(tested), 'holm': '110本の保有期間の費用前 p で Holm'}},
           'diagnostics': diag_summary, 'emerging_cost2x_report_only': sens,
           'tested': tested, 'series_cache': os.path.relpath(SERIES_CACHE, BASE),
           'runtime_sec': round(time.time() - t0), 'log_tail': LOG[-80:]}
    p = M.save(OUT, obj)
    log('保存', p, f'{os.path.getsize(p) / 1e6:.2f} MB', f'{time.time() - t0:.0f}s')


# ───────────────────────── 検算 ─────────────────────────
def selftest():
    rng = np.random.default_rng(7)
    ok = True
    # (2) 二次計画: 合成の因子構造で PDAS と FISTA を比べる
    for trial in range(12):
        N, T = 60 + 10 * trial, 120
        f = rng.normal(0.006, 0.045, T)
        B = rng.uniform(0.7, 1.3, N)
        X = np.outer(f, B) + rng.normal(0, 0.02, (T, N)) * rng.uniform(0.5, 1.5, N)
        Sig, dl = lw_cc(X)
        mu = X.mean(0)
        up = np.full(N, CAP); up[-1] = 1.0
        lo = np.zeros(N)
        for c in (np.zeros(N), mu / 3.0, Sig[:, -1] + mu / 30):
            w1 = qp(Sig, c, lo, up)
            w2 = qp_fista(Sig, c, lo, up, iters=200000, tol=1e-14)
            o1 = 0.5 * w1 @ Sig @ w1 - c @ w1
            o2 = 0.5 * w2 @ Sig @ w2 - c @ w2
            feas = abs(w1.sum() - 1) < 1e-9 and (w1 >= -1e-12).all() and (w1 <= up + 1e-12).all()
            if not (feas and o1 <= o2 + 1e-10 * (1 + abs(o2))):
                ok = False
                print('QP 不一致', trial, o1, o2, feas)
        # 最大シャープの検算: 近くの無作為な実行可能点より低くない
        w, lam = max_sharpe(mu, Sig, lo, up)
        shp = lambda v: (mu @ v) / math.sqrt(v @ Sig @ v)
        best_rand = max(shp(proj_box_budget(w + rng.normal(0, 0.01, N), lo, up)) for _ in range(300))
        if w is not None and best_rand > shp(w) + 1e-9:
            ok = False
            print('最大シャープが最大でない', trial, shp(w), best_rand)
        # TE
        b = np.zeros(N); b[-1] = 1.0
        for te_a in (0.02, 0.04):
            te_m = te_a / math.sqrt(12)
            w, lam = te_opt(mu, Sig, b, lo, up, te_m)
            a = w - b
            te = math.sqrt(a @ Sig @ a)
            if te > te_m * 1.0011 or (lam > 1e-8 and te < te_m * 0.998):
                ok = False
                print('TE 予算に一致しない', trial, te_a, te * math.sqrt(12), lam)
            # 予算内の無作為点より期待リターンが低くない
            for _ in range(200):
                v = proj_box_budget(w + rng.normal(0, 0.003, N), lo, up)
                av = v - b
                if math.sqrt(av @ Sig @ av) <= te_m and mu @ v > mu @ w + 1e-10:
                    ok = False
                    print('TE 最適でない', trial)
                    break
        # リスク均等
        w = erc(Sig)
        rc = w * (Sig @ w)
        if rc.max() / rc.min() - 1 > 1e-6:
            ok = False
            print('リスク均等でない', rc.max() / rc.min())
    print('二次計画・最大シャープ・TE・リスク均等の検算', 'OK' if ok else 'NG', QP_STATS)
    # (1) 先読みなし: jpn の実データで、t+1 以降のリターンを乱数に替えても t の重みが変わらない（戦略と市場の比較はしない）
    R = Region('jpn')
    checks = 0
    for i in [R.i0, R.i0 + 37, R.i0 + 150, R.T - 2]:
        a, _ = Targets(R).compute(i)
        P1, P3, mk = R.P1.copy(), R.P3.copy(), R.mkt.copy()
        fut = slice(i + 1, None)
        P1[fut] = np.where(np.isfinite(P1[fut]), rng.normal(0, 0.1, P1[fut].shape), np.nan)
        P3[fut] = np.where(np.isfinite(P3[fut]), rng.normal(0, 0.1, P3[fut].shape), np.nan)
        mk[fut] = np.where(np.isfinite(mk[fut]), rng.normal(0, 0.1, mk[fut].shape), np.nan)
        R2 = Region('jpn', P1, P3, mk, R.rf.copy(), R.cal, R.chars)
        assert R2.i0 == R.i0
        b_, _ = Targets(R2).compute(i)
        for r in RULES_T:
            ka, kb = set(a[r]), set(b_[r])
            if ka != kb or max(abs(a[r][x] - b_[r][x]) for x in ka) != 0.0:
                ok = False
                print('先読みの疑い', R.cal[i], r)
        checks += 1
    print('先読みなし（jpn の4か月・11規則）', 'OK' if ok else 'NG', checks)
    # (5) EW の月のリターン = 材料の単純平均
    out, _ = Targets(R).compute(R.i0)
    ew = out['EW']
    j = R.i0 + 1
    R._cidx = {k: jj for jj, k in enumerate(R.chars)}
    v = [block_ret(R, b_, j) for b_ in ew]
    hand = sum(v) / len(v)
    tg = {i: out['EW'] for i in range(R.i0, R.T - 1)}
    sim = simulate(R, tg, 'M')
    if abs(sim['gross'][R.cal[j]] - hand) > 1e-12:
        ok = False
        print('EW が単純平均に一致しない')
    print('EW の検算', 'OK' if ok else 'NG')
    return ok


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    main()
