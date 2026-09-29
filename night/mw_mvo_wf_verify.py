#!/usr/bin/env python3
"""night/mw_mvo_wf_verify.py — 角度 mvo_wf の『反証の検証』（adversarial verifier・読むだけ・門の判定には不使用）

研究者の主張（out/mw_mvo_wf.json）のうち S・A の全64本から、事前登録の主の族の S/A 全21本＋保有期間の t の上位8本
（主以外の4本）＋研究者が要約で名指しした探索の米国の A 4本と NC_MS_E_M ＋ B の保有期間の超過の上位2本を、
**自前のコードで作り直して**反証を試みる。

独立性: mw_common からは取得（get・jkp_rows）と French の zip の置き場所（FR）だけを使う。
French の CSV の読み取り・良い側・材料になれる条件・Ledoit-Wolf・James-Stein・二次計画（自前の主有効制約法）・
最大シャープ（黄金分割）・TE の予算（二分法）・リスク均等（循環座標降下）・持ち方・漂い・費用・超過・NW t・CAGR・
20年窓・線の当てはめは自前。研究者のコード（night/mw_mvo_wf.py）は import しない。

  python3 night/mw_mvo_wf_verify.py --compute    → 系列を作る（out/_mw_cache/mw_mvo_wf_verify_series.json・4並列で約15分）
  python3 night/mw_mvo_wf_verify.py --extra      → 近いパラメータの追加分（NC_POS10 の窓）
  python3 night/mw_mvo_wf_verify.py --countries  → 国ごとの同じ規則（報告と傷(l)）
  python3 night/mw_mvo_wf_verify.py --analyze    → キャッシュから判定して out/mw_mvo_wf_verify.json を書く
"""
import sys, os, json, math, time, csv, io, zipfile, statistics as S
for _v in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M   # 取得だけ（get・jkp_rows・FR）

BASE = M.BASE
CACHE_SER = os.path.join(M.CACHE, 'mw_mvo_wf_verify_series.json')
OUTF = os.path.join(BASE, 'out', 'mw_mvo_wf_verify.json')
REGIONS = ['usa', 'world_ex_us', 'developed', 'emerging', 'jpn']
END = 202512
WIN = 120
NMIN = 10
TRAIN_END, HOLD_A, RECENT_A = 200612, 200701, 201307
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


def months(a, z):
    out = []
    y, m = divmod(a, 100)
    while y * 100 + m <= z:
        out.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ───────────────────────── 表（研究者の道具ではなく、事前登録が名指しした原本の表） ─────────────────────────
FUS = json.load(open(os.path.join(BASE, 'out', 'mw_factor_us_prereg.json')))['families']['a_jkp_tercile_vw']['list']
CHARS = [x['key'] for x in FUS]
TURN = {x['key']: float(x['turnover_pct']) / 100 for x in FUS}
UNITC = {x['key']: float(x['cost_per_100pct']) for x in FUS}
PUB = {x['key']: x.get('pub_year') for x in FUS}
AVAIL = json.load(open(os.path.join(M.CACHE, 'jkp_availability.json')))['portfolios']
CLUS = {}
with open(os.path.join(M.CACHE, 'jkp_cluster_labels.csv')) as fh:
    for r in csv.DictReader(fh):
        CLUS[r['characteristic']] = r['cluster']


def cost_of(k, side):
    """三分位の中の入れ替え（年・小数）と片道100%あたりの費用。market_equity の小型側（第1）だけ 0.60%（事前登録）"""
    c = UNITC[k]
    if k == 'market_equity':
        c = 0.006 if side == 1 else 0.003
    return TURN[k], c


MKT_TURN, MKT_C = 0.05, 0.001
SWITCH_C = 0.003


# ───────────────────────── French（自前の読み取り） ─────────────────────────
def french_monthly(name):
    b = M.get(M.FR.format(name), name=f'fr_{name}.zip')
    t = zipfile.ZipFile(io.BytesIO(b))
    txt = t.read(t.namelist()[0]).decode('latin-1')
    cols, out, started = None, {}, False
    for line in txt.splitlines():
        cells = [c.strip() for c in line.split(',')]
        if cols is None:
            if len(cells) > 2 and cells[0] == '' and 'Mkt-RF' in cells:
                cols = cells[1:]
            continue
        if cells[0].isdigit() and len(cells[0]) == 6:
            started = True
            vals = []
            for c in cells[1:1 + len(cols)]:
                try:
                    v = float(c)
                except ValueError:
                    v = None
                vals.append(None if v is None or v <= -99.99 else v / 100)
            out[int(cells[0])] = dict(zip(cols, vals))
        elif started:
            break      # 月次の表の終わり（年次の表は読まない）
    return out


# ───────────────────────── JKP の地域データ ─────────────────────────
class Reg:
    def __init__(self, region, chars_filter=None):
        self.region = region
        chars = [k for k in CHARS if k in AVAIL.get(region, [])]
        if chars_filter:
            chars = [k for k in chars if chars_filter(k)]
        P = {1: {}, 2: {}, 3: {}}
        for k in chars:
            for x in M.jkp_rows(region, k, 'portfolios', 'vw'):
                if x['pf'] not in ('1.0', '2.0', '3.0') or x['ret'] in ('', 'NA', 'na'):
                    continue
                n = x.get('n')
                if n not in (None, '', 'NA', 'na') and float(n) < NMIN:
                    continue
                P[int(float(x['pf']))].setdefault(k, {})[ym(x['date'])] = float(x['ret'])
        ff = french_monthly('F-F_Research_Data_Factors')
        self.rf_d = {m: v['RF'] for m, v in ff.items() if v['RF'] is not None}
        if region == 'usa':
            mk = {m: v['Mkt-RF'] for m, v in ff.items() if v['Mkt-RF'] is not None}
        else:
            mk = {ym(x['date']): float(x['ret']) for x in M.jkp_rows(region, 'mkt', 'factor', 'vw') if x['ret'] not in ('', 'NA', 'na')}
        self.mk_d = mk
        first = min(min(s) for s in P[1].values())
        first = min(first, min(mk))
        self.cal = months(first, END)
        T = len(self.cal)
        pos = {m: i for i, m in enumerate(self.cal)}
        self.chars = [k for k in chars if k in P[1] and k in P[3]]
        self.cidx = {k: j for j, k in enumerate(self.chars)}
        self.flip = False
        K = len(self.chars)
        self.A = {s: np.full((T, K), np.nan) for s in (1, 2, 3)}
        for s in (1, 2, 3):
            for j, k in enumerate(self.chars):
                for m, v in P[s].get(k, {}).items():
                    if m in pos:
                        self.A[s][pos[m], j] = v
        self.mkt = np.array([mk.get(m, np.nan) for m in self.cal])
        self.rf = np.array([self.rf_d.get(m, np.nan) for m in self.cal])
        # 向き（JKP の usa 因子ファイルの direction 列）
        self.dir = np.array([float(M.jkp_rows('usa', k, 'factor', 'vw')[0]['direction']) for k in self.chars])
        self._sides()

    def _sides(self):
        """月末 i ごとの良い側（3 or 1）と、両方の値がそろう月の数。走る和で自前に数える"""
        T, K = self.A[1].shape
        run_s = np.zeros(K); run_n = np.zeros(K)
        self.side = np.zeros((T, K), dtype=int)
        self.nboth = np.zeros((T, K))
        for i in range(T):
            a1, a3 = self.A[1][i], self.A[3][i]
            ok = np.isfinite(a1) & np.isfinite(a3)
            run_s[ok] += (self.dir * (a3 - a1))[ok]
            run_n[ok] += 1
            mean = np.where(run_n > 0, run_s / np.maximum(run_n, 1), 0.0)
            dirside = np.where(self.dir > 0, 3, 1)
            other = np.where(self.dir > 0, 1, 3)
            self.side[i] = np.where(mean >= 0, dirside, other)
            self.nboth[i] = run_n

    def col(self, k, side):
        return self.A[side][:, k]

    def eligible(self, i):
        """月末 i に材料になれる特性の列と側"""
        lo = i - WIN + 1
        if lo < 0 or i + 1 >= len(self.cal):
            return []
        out = []
        for k in range(len(self.chars)):
            if self.nboth[i, k] < WIN:
                continue
            s = self.side[i, k]
            if self.flip:
                s = 4 - s     # 鏡の偽薬: 悪い側
            c = self.A[s][:, k]
            if np.isfinite(c[lo:i + 1]).all() and np.isfinite(c[i + 1]):
                out.append((k, s))
        return out

    def mkt_ok(self, i):
        lo = i - WIN + 1
        return lo >= 0 and i + 1 < len(self.cal) and np.isfinite(self.mkt[lo:i + 1]).all() and np.isfinite(self.mkt[i + 1])

    def start(self):
        for i in range(WIN - 1, len(self.cal) - 1):
            if self.cal[i] % 100 == 12 and self.mkt_ok(i) and len(self.eligible(i)) >= 100:
                return i
        return None


# ───────────────────────── 推定 ─────────────────────────
def ledoit_wolf_cc(X):
    """Ledoit & Wolf (2004, JPM) の定相関の目標への縮小。論文の式から自前に書いた"""
    T, N = X.shape
    Y = X - X.mean(axis=0)
    Sm = (Y.T @ Y) / T
    s = np.sqrt(np.diag(Sm))
    corr = Sm / np.outer(s, s)
    rbar = (corr.sum() - N) / (N * (N - 1))
    F = rbar * np.outer(s, s)
    F[np.diag_indices(N)] = np.diag(Sm)
    Y2 = Y * Y
    # π_ij = mean_t[(y_i y_j − s_ij)^2]
    pi_mat = (Y2.T @ Y2) / T - Sm * Sm
    pi_hat = pi_mat.sum()
    # θ_ii,ij = mean_t[(y_i^2 − s_ii)(y_i y_j − s_ij)] = mean(y_i^3 y_j) − s_ii s_ij
    th = ((Y2 * Y).T @ Y) / T - np.diag(Sm)[:, None] * Sm
    ratio = s[None, :] / s[:, None]          # sqrt(s_jj/s_ii)
    off = ~np.eye(N, dtype=bool)
    rho_hat = np.trace(pi_mat) + rbar * (ratio * th)[off].sum()
    gamma_hat = ((F - Sm) ** 2).sum()
    kappa = (pi_hat - rho_hat) / gamma_hat
    d = min(1.0, max(0.0, kappa / T))
    return d * F + (1 - d) * Sm, d


def james_stein(mu, Sig, T):
    N = len(mu)
    m = mu.mean()
    dv = mu - m
    q = float(dv @ np.linalg.solve(Sig, dv))
    phi = 1.0 if q <= 0 else min(1.0, max(0.0, (N - 3) / (T * q)))
    return m + (1 - phi) * dv, phi


# ───────────────────────── 二次計画（自前の主有効制約法） ─────────────────────────
def project(v, u):
    """{Σw=1, 0≤w≤u} への射影（折れ点を並べて τ を厳密に）"""
    bp = np.sort(np.concatenate([v - u, v]))
    s = np.clip(v[None, :] - bp[:, None], 0, u[None, :]).sum(1)     # τ の増加で減る
    k = np.searchsorted(-s, -1.0)
    if k == 0:
        tau = bp[0] - (1.0 - s[0]) / max(1, (v > bp[0]).sum())
    elif k >= len(bp):
        tau = bp[-1]
    else:
        a, b = bp[k - 1], bp[k]
        sa, sb = s[k - 1], s[k]
        tau = a if sa == sb else a + (sa - 1.0) / (sa - sb) * (b - a)
    w = np.clip(v - tau, 0, u)
    return w / w.sum()


QPN = {'n': 0, 'it': 0, 'fail': 0}


def qp_as(Q, c, u, w0=None, maxit=30000):
    """min ½w'Qw − c'w  s.t. Σw=1, 0≤w≤u。主有効制約法で解き、回り続けた（退化）ときは射影勾配で近づけてから有効制約法で仕上げる"""
    w, ok = _qp_core(Q, c, u, w0, maxit)
    if ok:
        return w
    QPN['fail'] += 1
    wp = _pg(Q, c, u, w)
    w2, ok2 = _qp_core(Q, c, u, wp, maxit)
    f = lambda v: 0.5 * v @ Q @ v - c @ v
    if ok2 and f(w2) <= f(wp) + 1e-15 * (1 + abs(f(wp))):
        QPN['rescued'] = QPN.get('rescued', 0) + 1
        return w2
    QPN['pg_only'] = QPN.get('pg_only', 0) + 1
    return wp


def _pg(Q, c, u, w0, iters=100000):
    """射影勾配（加速・再起動つき）。退化で有効制約法が回り続けたときの予備"""
    L = float(np.linalg.eigvalsh(Q)[-1]) * 1.0001
    f = lambda v: 0.5 * v @ Q @ v - c @ v
    x = project(np.asarray(w0, float), u)
    y, t, fx = x.copy(), 1.0, f(x)
    for _ in range(iters):
        xn = project(y - (Q @ y - c) / L, u)
        fn = f(xn)
        tn = (1 + math.sqrt(1 + 4 * t * t)) / 2
        if fn > fx:
            y, t = x.copy(), 1.0
            continue
        y = xn + (t - 1) / tn * (xn - x)
        if np.abs(xn - x).max() < 1e-15:
            return xn
        x, t, fx = xn, tn, fn
    return x


def _qp_core(Q, c, u, w0=None, maxit=30000):
    """主有効制約法（Nocedal-Wright 16.3 の形）。戻り値 (w, 収束したか)"""
    n = len(c)
    w = project(np.full(n, 1.0 / n) if w0 is None else np.asarray(w0, float), u)
    lo = w <= 1e-15
    up = (w >= u - 1e-15) & ~lo
    w[lo] = 0.0
    w[up] = u[up]
    fr = ~(lo | up)
    if fr.any():
        w[fr] += (1.0 - w.sum()) / fr.sum()
    scale = 1.0 + np.abs(c).max() + np.abs(Q).max()
    tol = 1e-13 * scale
    QPN['n'] += 1
    for it in range(maxit):
        g = Q @ w - c
        F = np.flatnonzero(~(lo | up))
        if len(F) == 0:
            numin = np.max(-g[lo]) if lo.any() else -np.inf
            numax = np.min(-g[up]) if up.any() else np.inf
            if numin <= numax + tol:
                QPN['it'] += it
                return w, True
            if lo.any():
                j = np.flatnonzero(lo)[np.argmin(g[lo])]; lo[j] = False
            if up.any():
                j = np.flatnonzero(up)[np.argmax(g[up])]; up[j] = False
            continue
        nf = len(F)
        K = np.zeros((nf + 1, nf + 1))
        K[:nf, :nf] = Q[np.ix_(F, F)]
        K[:nf, nf] = 1.0
        K[nf, :nf] = 1.0
        rhs = np.concatenate([-g[F], [0.0]])
        sol = np.linalg.solve(K, rhs)
        p, nu = sol[:nf], sol[nf]
        if np.abs(p).max() <= 1e-14:
            mlo = g[lo] + nu
            mup = -(g[up] + nu)
            cand = []
            if lo.any():
                a = np.argmin(mlo); cand.append((mlo[a], 'lo', np.flatnonzero(lo)[a]))
            if up.any():
                a = np.argmin(mup); cand.append((mup[a], 'up', np.flatnonzero(up)[a]))
            if not cand or min(x[0] for x in cand) >= -tol:
                QPN['it'] += it
                return w, True
            v, kind, j = min(cand)
            if kind == 'lo':
                lo[j] = False
            else:
                up[j] = False
            continue
        wf = w[F]
        alpha, blk, bk = 1.0, None, None
        neg = p < -1e-18
        if neg.any():
            r = -wf[neg] / p[neg]
            a = np.argmin(r)
            if r[a] < alpha:
                alpha, blk, bk = r[a], F[neg][a], 'lo'
        pos = p > 1e-18
        if pos.any():
            r = (u[F][pos] - wf[pos]) / p[pos]
            a = np.argmin(r)
            if r[a] < alpha:
                alpha, blk, bk = r[a], F[pos][a], 'up'
        w[F] = wf + max(0.0, alpha) * p
        if blk is not None:
            if bk == 'lo':
                w[blk] = 0.0; lo[blk] = True
            else:
                w[blk] = u[blk]; up[blk] = True
    return w, False


def lp_top(mu, u):
    w = np.zeros(len(mu)); rem = 1.0
    for j in np.argsort(-mu, kind='stable'):
        w[j] = min(u[j], rem); rem -= w[j]
        if rem <= 1e-15:
            break
    return w


def max_sharpe(mu, Sig, u, w0=None):
    """最大シャープ（買いだけ・上限つき）。効率的フロンティアを log λ で黄金分割（自前）。正の組み合わせが無ければ None"""
    if mu @ lp_top(mu, u) <= 0:
        return None
    muc = mu - mu.mean()
    sols = {}

    def sol(x):
        if x not in sols:
            near = min(sols, key=lambda y: abs(y - x)) if sols else None
            sols[x] = qp_as(Sig, muc * math.exp(-x), u, sols[near] if near is not None else w0)
        return sols[x]

    def shp(x):
        w = sol(x)
        return (mu @ w) / math.sqrt(w @ Sig @ w)

    # Sharpe は λ に沿って単峰だが平らな所（LP の角・最小分散の端）がある＝黄金分割は平らな所で道を誤る（自前の検算で確認）。
    # そこで粗い格子（log λ 0.5 刻み）で最大の値を取る点の集まりの両端を見つけ、その両隣を 0.02 → 0.001 刻みで詰める
    def refine(xs, step):
        vals = [shp(x) for x in xs]
        m = max(vals)
        tied = [j for j, v in enumerate(vals) if v >= m - 1e-13 * (1 + abs(m))]
        cands = []
        for j in (tied[0], tied[-1]):
            a_, b_ = xs[max(0, j - 1)], xs[min(len(xs) - 1, j + 1)]
            cands.append((a_, b_))
        return cands, xs[tied[-1]]
    xs = list(np.arange(math.log(1e-5), math.log(1e7), 0.5))
    cands, best = refine(xs, 0.5)
    for step in (0.02, 0.001):
        allx = []
        for a_, b_ in cands:
            allx += list(np.arange(a_, b_ + step / 2, step))
        allx = sorted(set(allx))
        cands, best = refine(allx, step)
    return sol(best)


def te_max(mu, Sig, bvec, u, te_m, w0=None):
    """max μ'w s.t. (w−b)'Σ(w−b) ≤ te_m²。min ½w'Σw − w'(Σb + κμ) の κ を二分法（自前）"""
    muc = mu - mu.mean()
    Sb = Sig @ bvec
    sols = {}

    def sol(x):
        if x not in sols:
            near = min(sols, key=lambda y: abs(y - x)) if sols else None
            sols[x] = qp_as(Sig, Sb + muc * math.exp(x), u, sols[near] if near is not None else w0)
        return sols[x]

    def te(x):
        a = sol(x) - bvec
        return math.sqrt(max(0.0, a @ Sig @ a))

    lo_x, hi_x = math.log(1e-8), math.log(1e8)
    if te(hi_x) <= te_m:
        return sol(hi_x)
    a, b = lo_x, hi_x
    for _ in range(80):
        x = 0.5 * (a + b)
        t = te(x)
        if abs(t / te_m - 1) < 2e-4:
            break
        if t > te_m:
            b = x
        else:
            a = x
    if te(x) > te_m * 1.001:
        x = a
    return sol(x)


def risk_parity(Sig, tol=1e-12, maxit=2000):
    """等リスク寄与。min ½y'Σy − (1/N)Σlog y を循環座標降下（Griveau-Billion et al. 2013）で解き w=y/Σy"""
    n = Sig.shape[0]
    b = 1.0 / n
    y = 1.0 / np.sqrt(np.diag(Sig))
    y /= math.sqrt(y @ Sig @ y)
    d = np.diag(Sig).copy()
    for _ in range(maxit):
        yold = y.copy()
        for i in range(n):
            a = Sig[i] @ y - d[i] * y[i]
            y[i] = (-a + math.sqrt(a * a + 4 * d[i] * b)) / (2 * d[i])
        if np.max(np.abs(y - yold) / yold) < tol:
            break
    return y / y.sum()


# ───────────────────────── 目標の重み ─────────────────────────
def spec_parse(rule):
    """'NC_MS_E' → dict。追加の変種は後ろに @ をつける（例 'POS10@W60'・'MS_E@cap0.1'・'TE4_R@te0.03'）"""
    base, _, var = rule.partition('@')
    sp = {'nc': base.startswith('NC_'), 'theme': base.startswith('TH_'), 'var': var}
    core = base[3:] if (sp['nc'] or sp['theme']) else base
    sp['core'] = core
    sp['cap'] = 0.20
    sp['te'] = {'TE2': 0.02, 'TE4': 0.04}.get(core[:3])
    sp['posw'] = WIN
    for v in var.split(',') if var else []:
        if v.startswith('cap'):
            sp['cap'] = float(v[3:])
        elif v.startswith('te'):
            sp['te'] = float(v[2:])
        elif v.startswith('W'):
            sp['posw'] = int(v[1:])
    return sp


class Book:
    """地域 × 規則の組の目標の重みを月末ごとに作る"""

    def __init__(self, R, rules, i0, exclude_theme=None):
        self.R, self.rules, self.i0 = R, rules, i0
        self.origin = i0 - (WIN - 1)
        self.warm = {}
        self.exclude_theme = exclude_theme
        self.diag = {}

    def targets(self, i):
        R = self.R
        el = R.eligible(i)
        if self.exclude_theme:
            el = [(k, s) for k, s in el if CLUS[R.chars[k]] != self.exclude_theme]
        if not R.mkt_ok(i):
            raise RuntimeError('市場の履歴が欠ける')
        out = {}
        if len(el) < 30:
            return {r: {'MKT': 1.0} for r in self.rules}
        lo = i - WIN + 1
        ids = [(R.chars[k], s) for k, s in el] + ['MKT']
        X = np.column_stack([R.A[s][lo:i + 1, k] for k, s in el] + [R.mkt[lo:i + 1]])
        o = self.origin
        # 拡大窓の平均（原点から i まで・値のある月だけ）
        cols_full = [R.A[s][o:i + 1, k] for k, s in el] + [R.mkt[o:i + 1]]
        cnt = np.array([np.isfinite(c).sum() for c in cols_full], float)
        muE_raw = np.array([np.nansum(c) for c in cols_full]) / cnt
        TE_T = float(np.median(cnt))
        cst = np.array([(lambda t, c: t / 12 * c)(*cost_of(k_, s_)) for k_, s_ in ids[:-1]] + [MKT_TURN / 12 * MKT_C])
        need_tercile = any(not spec_parse(r)['theme'] for r in self.rules)
        need_theme = any(spec_parse(r)['theme'] for r in self.rules)
        cache = {}
        if need_tercile:
            Sig, dlt = ledoit_wolf_cc(X)
            cache['T'] = (X, Sig, muE_raw, TE_T, cst, ids, None)
            self.diag.setdefault(R.cal[i], {})['lw_delta'] = round(dlt, 4)
        if need_theme:
            grp = {}
            for p_, (k, s) in enumerate(el):
                grp.setdefault(CLUS[R.chars[k]], []).append(p_)
            th = sorted(t_ for t_, v in grp.items() if len(v) >= 2)
            if len(th) >= 5:
                Xt = np.column_stack([X[:, grp[t_]].mean(1) for t_ in th] + [X[:, -1]])
                Sigt, _ = ledoit_wolf_cc(Xt)
                muEt = np.array([muE_raw[grp[t_]].mean() for t_ in th] + [muE_raw[-1]])
                cstt = np.array([cst[grp[t_]].mean() for t_ in th] + [cst[-1]])
                mem = {('TH', t_): [ids[p_] for p_ in grp[t_]] for t_ in th}
                cache['H'] = (Xt, Sigt, muEt, TE_T, cstt, [('TH', t_) for t_ in th] + ['MKT'], mem)
            else:
                cache['H'] = None
        for r in self.rules:
            sp = spec_parse(r)
            key = 'H' if sp['theme'] else 'T'
            if cache[key] is None:
                out[r] = {'MKT': 1.0}
                continue
            Xr, Sig, muE, TT, cc, idr, mem = cache[key]
            N = Xr.shape[1]
            u = np.full(N, sp['cap']); u[-1] = 1.0
            bvec = np.zeros(N); bvec[-1] = 1.0
            core = sp['core']
            cadj = cc if sp['nc'] else np.zeros(N)
            w0 = None
            if r in self.warm:
                pid, pw = self.warm[r]
                mm = dict(zip(pid, pw))
                w0 = np.array([mm.get(x, 0.0) for x in idr])
                w0 = w0 / w0.sum() if w0.sum() > 0 else None
            if core in ('MS_E', 'MS_R', 'MSraw_R'):
                if core == 'MSraw_R':
                    mu = Xr.mean(0)
                elif core == 'MS_R':
                    mu, _ = james_stein(Xr.mean(0), Sig, WIN)
                else:
                    mu, _ = james_stein(muE, Sig, TT)
                w = max_sharpe(mu - cadj, Sig, u, w0)
                if w is None:
                    w = bvec.copy()
            elif core.startswith('TE'):
                if core.endswith('_E'):
                    mu, _ = james_stein(muE, Sig, TT)
                else:
                    mu, _ = james_stein(Xr.mean(0), Sig, WIN)
                w = te_max(mu - cadj, Sig, bvec, u, sp['te'] / math.sqrt(12), w0)
            elif core == 'MV':
                w = qp_as(Sig, np.zeros(N), u, w0)
            elif core == 'RP':
                w = risk_parity(Sig)
            elif core == 'POS10':
                W = sp['posw']
                lo2 = max(self.origin if W > WIN else 0, i - W + 1)
                if W == WIN:
                    mm = Xr.mean(0)
                else:
                    if mem is not None:
                        raise ValueError
                    cols = [R.A[s][lo2:i + 1, k] for k, s in el] + [R.mkt[lo2:i + 1]]
                    mm = np.array([np.nanmean(c) for c in cols])
                act = (mm[:-1] - cadj[:-1]) - (mm[-1] - cadj[-1])
                w = np.zeros(N)
                if (act > 0).any():
                    w[:-1][act > 0] = 1.0 / (act > 0).sum()
                else:
                    w[-1] = 1.0
            elif core == 'EW':
                w = np.full(N, 1.0 / N)
            elif core == 'BAD_EW':
                raise ValueError
            else:
                raise KeyError(r)
            w = np.where(w < 1e-10, 0.0, w)
            w = w / w.sum()
            self.warm[r] = (idr, w)
            if mem is None:
                out[r] = {x: float(v) for x, v in zip(idr, w) if v > 0}
            else:
                o_ = {}
                for x, v in zip(idr, w):
                    if v <= 0:
                        continue
                    if x == 'MKT':
                        o_['MKT'] = float(v)
                    else:
                        for t_ in mem[x]:
                            o_[t_] = o_.get(t_, 0.0) + float(v) / len(mem[x])
                out[r] = o_
        return out


def hold(R, tg, i0, freq, cost_mult=1.0):
    """tg: {i: {id: w}}。毎月（M）か毎年12月（A）に目標へ。費用前・費用後の超過（月）を返す"""
    held = None
    g, n = {}, {}
    sw_sum = wi_sum = 0.0
    for i in range(i0, len(R.cal) - 1):
        sw = 0.0
        if freq == 'M' or R.cal[i] % 100 == 12:
            t = tg[i]
            if held is not None:
                sw = 0.5 * sum(abs(t.get(x, 0.0) - held.get(x, 0.0)) for x in set(t) | set(held))
            held = dict(t)
        j = i + 1
        ret = {}
        for x in held:
            if x == 'MKT':
                v = R.mkt[j]
            else:
                v = R.A[x[1]][j, R.cidx[x[0]]]
            if np.isfinite(v):
                ret[x] = float(v)
        if len(ret) < len(held):
            tot = sum(held[x] for x in ret)
            held = {x: held[x] / tot for x in ret}
        pr = sum(held[x] * ret[x] for x in held)
        wc = 0.0
        for x, wx in held.items():
            tp, c = (MKT_TURN, MKT_C) if x == 'MKT' else cost_of(x[0], x[1])
            wc += wx * tp / 12 * c
        cm = (sw * SWITCH_C + wc) * cost_mult
        g[R.cal[j]] = pr
        n[R.cal[j]] = pr - cm
        rf = R.rf[j]
        gr = {x: held[x] * (1 + ret[x] + rf) for x in held}
        s = sum(gr.values())
        held = {x: v / s for x, v in gr.items()}
    return g, n


# ───────────────────────── 統計（自前） ─────────────────────────
def nw(x, L=12):
    x = np.asarray(x, float)
    n = len(x)
    e = x - x.mean()
    v = e @ e / n
    for l in range(1, L + 1):
        v += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / n
    return x.mean() / math.sqrt(v / n) if v > 0 else None


def geo(x):
    return math.exp(np.log1p(np.asarray(x)).sum() * 12 / len(x)) - 1


def st(s, b, a=None, z=None, rf=None):
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = np.array([s[k] - b[k] for k in ks])
    out = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(ex.mean() * 1200, 2), 't': (round(nw(ex), 2) if nw(ex) is not None else None),
           'cagr_diff_excess_basis': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2)}
    if rf is not None:
        out['cagr_diff_total_basis'] = round((geo([s[k] + rf[k] for k in ks]) - geo([b[k] + rf[k] for k in ks])) * 100, 2)
        out['cagr_s_total'] = round(geo([s[k] + rf[k] for k in ks]) * 100, 2)
        out['cagr_b_total'] = round(geo([b[k] + rf[k] for k in ks]) * 100, 2)
    out['te'] = round(float(np.std(ex, ddof=1)) * math.sqrt(12) * 100, 2)
    return out


def roll20(s, b, rf):
    ks = sorted(set(s) & set(b) & set(rf))
    res = []
    for y in range(ks[0] // 100, END // 100):
        w = [k for k in ks if y * 100 + 7 <= k <= (y + 20) * 100 + 6]
        if (y + 20) * 100 + 6 > ks[-1]:
            break
        if len(w) < 233:
            continue
        gs = geo([s[k] + rf[k] for k in w]); gb = geo([b[k] + rf[k] for k in w])
        res.append((y, round((gs - gb) * 100, 2)))
    if not res:
        return None
    return {'windows': len(res), 'wins': sum(1 for _, v in res if v > 0), 'win_rate': round(sum(1 for _, v in res if v > 0) / len(res), 3),
            'worst': min(res, key=lambda x: x[1]), 'starts': [res[0][0], res[-1][0]]}


# ───────────────────────── 走らせる ─────────────────────────
_REG_CACHE = {}


def get_reg(region, universe='all', flip=False):
    key = (region, universe, flip)
    if key not in _REG_CACHE:
        filt = None
        if universe == 'pub2006':
            filt = lambda k: PUB.get(k) is not None and PUB[k] <= 2006
        R = Reg(region, filt)
        R.flip = flip
        _REG_CACHE[key] = R
    return _REG_CACHE[key]


def run_task(task):
    """task = (region, universe, flip, exclude_theme, rules, i0_override)。戻り値: {名前: {'M': (g, n, n2), 'A': ...}}"""
    region, universe, flip, excl, rules, i0o = task
    t0 = time.time()
    R = get_reg(region, universe, flip)
    i0 = i0o if i0o is not None else R.start()
    B = Book(R, rules, i0, exclude_theme=excl)
    tg = {r: {} for r in rules}
    for i in range(i0, len(R.cal) - 1):
        o = B.targets(i)
        for r in rules:
            tg[r][i] = o[r]
    res = {}
    for r in rules:
        for f in ('M', 'A'):
            g, n = hold(R, tg[r], i0, f)
            _, n2 = hold(R, tg[r], i0, f, 2.0)
            _, n3 = hold(R, tg[r], i0, f, 3.0)
            res[f'{r}_{f}'] = {'g': g, 'n': n, 'n2': n2, 'n3': n3}
    tag = f'{region}|{universe}|{"flip" if flip else ""}|{excl or ""}'
    log(f'  {tag} {len(rules)}規則 {time.time() - t0:.0f}s 最初の組み入れ {R.cal[i0]} QP {QPN}')
    return tag, res, R.cal[i0]


MAIN_RULES = ['EW', 'RP', 'POS10', 'NC_POS10', 'MS_E', 'MSraw_R', 'NC_MS_E', 'NC_MSraw_R', 'TE4_E', 'TE4_R', 'TE2_R', 'TH_TE2_R']
THEMES = sorted(set(CLUS.values()))


def plan():
    """(region, universe, flip, exclude_theme, rules, i0_region_key)。i0 は主の宇宙の最初の組み入れにそろえる（変種も同じ日に始める）"""
    T = []
    heavy = [['MS_E', 'NC_MS_E'], ['MSraw_R', 'NC_MSraw_R'], ['EW', 'RP', 'POS10', 'NC_POS10', 'TE4_E', 'TE4_R', 'TE2_R', 'TH_TE2_R']]
    for reg in REGIONS:
        for grp in heavy:
            T.append((reg, 'all', False, None, grp, 'main'))
    frag = {'world_ex_us': ['POS10@W60', 'POS10@W180', 'MS_E@cap0.1', 'MS_E@cap0.3', 'TE4_R@te0.03', 'TE4_R@te0.06', 'TE2_R@te0.01',
                            'TE2_R@te0.03', 'TE4_E@te0.03', 'TE4_E@te0.06', 'NC_MS_E@cap0.1', 'NC_MS_E@cap0.3'],
            'developed': ['POS10@W60', 'POS10@W180', 'TE2_R@te0.01', 'TE2_R@te0.03', 'MSraw_R@cap0.1', 'MSraw_R@cap0.3',
                          'NC_MSraw_R@cap0.1', 'NC_MSraw_R@cap0.3'],
            'emerging': ['MSraw_R@cap0.1', 'MSraw_R@cap0.3'],
            'usa': ['TE4_R@te0.03', 'TE4_R@te0.06', 'NC_MSraw_R@cap0.1', 'NC_MSraw_R@cap0.3', 'NC_POS10@W60', 'NC_POS10@W180']}
    for reg, rr in frag.items():
        light = [r for r in rr if not r.startswith(('MS', 'NC_MS'))]
        hv = [r for r in rr if r.startswith(('MS', 'NC_MS'))]
        if light:
            T.append((reg, 'all', False, None, light, 'main'))
        for r in hv:
            T.append((reg, 'all', False, None, [r], 'main'))
    for reg in ('world_ex_us', 'developed', 'emerging', 'usa'):
        T.append((reg, 'pub2006', False, None, ['EW', 'POS10', 'RP', 'NC_POS10', 'TE4_R', 'TE2_R'], 'main'))
        T.append((reg, 'pub2006', False, None, ['MS_E', 'MSraw_R'], 'main'))
    for reg in ('world_ex_us', 'developed', 'usa'):
        T.append((reg, 'all', True, None, ['EW', 'POS10', 'TE4_R', 'TE2_R'], 'main'))
    T.append(('world_ex_us', 'all', True, None, ['MS_E'], 'main'))
    for th in THEMES:
        T.append(('world_ex_us', 'all', False, th, ['EW', 'POS10'], 'main'))
    return T


def _run(task):
    reg, uni, flip, excl, rules, _ = task
    i0 = get_reg(reg).start()
    R = get_reg(reg, uni, flip)
    # 変種の宇宙でも主の宇宙と同じ暦・同じ最初の組み入れの日
    assert R.cal == get_reg(reg).cal
    return run_task((reg, uni, flip, excl, rules, i0))


def compute_all():
    import multiprocessing as mp
    T = plan()
    # 重い順に並べる（米国の最大シャープが最も重い）
    order = sorted(T, key=lambda t: -((3 if t[0] == 'usa' else 1) * sum(4 if r.startswith(('MS', 'NC_MS')) else 1 for r in t[4])))
    ser = {}
    with mp.Pool(4) as pool:
        for tag, res, i0m in pool.imap_unordered(_run, order):
            d = ser.setdefault(tag, {'_i0': i0m})
            for k, v in res.items():
                d[k] = {kk: {str(a): round(b, 9) for a, b in vv.items()} for kk, vv in v.items()}
            json.dump(ser, open(CACHE_SER + '.tmp', 'w'))
    os.replace(CACHE_SER + '.tmp', CACHE_SER)
    return ser


if __name__ == '__main__' and '--compute' in sys.argv:
    t0 = time.time()
    compute_all()
    log('計算', round(time.time() - t0), 's')


# ───────────────────────── 判定（自前の線の当てはめ） ─────────────────────────
CANDS = [  # (名前, 選んだ理由)
    ('world_ex_us:POS10_M', 'primary'), ('world_ex_us:POS10_A', 'primary'), ('developed:POS10_M', 'primary'), ('developed:POS10_A', 'primary'),
    ('world_ex_us:EW_A', 'primary'), ('world_ex_us:EW_M', 'primary'), ('world_ex_us:RP_M', 'primary'), ('world_ex_us:RP_A', 'primary'),
    ('developed:EW_A', 'primary'), ('developed:EW_M', 'primary'), ('developed:RP_A', 'primary'), ('developed:RP_M', 'primary'),
    ('world_ex_us:MS_E_M', 'primary'), ('world_ex_us:MS_E_A', 'primary'), ('emerging:MSraw_R_M', 'primary'), ('emerging:MSraw_R_A', 'primary'),
    ('world_ex_us:TE2_R_M', 'primary'), ('world_ex_us:TE4_E_A', 'primary'), ('world_ex_us:TE4_R_M', 'primary'), ('developed:TE2_R_M', 'primary'),
    ('usa:TE4_R_M', 'primary'),
    ('world_ex_us:NC_POS10_M', 'top8_hold_t'), ('world_ex_us:NC_POS10_A', 'top8_hold_t'), ('developed:NC_POS10_M', 'top8_hold_t'),
    ('world_ex_us:TH_TE2_R_M', 'top8_hold_t'),
    ('world_ex_us:NC_MS_E_M', 'named_in_summary'), ('usa:NC_MSraw_R_M', 'named_in_summary_us_A'), ('usa:NC_POS10_M', 'us_A'), ('usa:NC_POS10_A', 'us_A'),
    ('developed:MSraw_R_A', 'best2_B'), ('developed:NC_MSraw_R_A', 'best2_B'),
]
GOOD_TAG = lambda reg: f'{reg}|all||'


def ser_get(ser, reg, key, kind='g', uni='all', flip=False, excl=None):
    tag = f'{reg}|{uni}|{"flip" if flip else ""}|{excl or ""}'
    d = ser.get(tag, {}).get(key)
    if d is None:
        return None
    return {int(a): b for a, b in d[kind].items()}


def perr(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def holm_adj(pv, name):
    items = sorted((p, k) for k, p in pv.items() if p is not None)
    m, run = len(items), 0.0
    for i, (p, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        if k == name:
            return run
    return None


def letter(c):
    ok = lambda k: c[k] is True
    base = ok('C1') and ok('C2') and ok('C6')
    if base and ok('C3') and ok('C4') and ok('C7') and c['C5'] in (None, True):
        return 'S'
    if base and ok('C4') and ok('C7') and (ok('C3') or ok('C5') is True):
        return 'A'
    if base:
        return 'B'
    return 'C'


def all3_of(R):
    out = {}
    for i, m in enumerate(R.cal):
        a = R.A[1][i]; b = R.A[2][i]; c = R.A[3][i]
        ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c)
        if ok.sum() >= 30:
            out[m] = float(((a + b + c) / 3)[ok].mean())
    return out


def drop_best_years(s, b, k=3, a=HOLD_A):
    ks = [m for m in sorted(set(s) & set(b)) if m >= a]
    yr = {}
    for m in ks:
        yr.setdefault(m // 100, 0.0)
        yr[m // 100] += s[m] - b[m]
    best = sorted(yr, key=lambda y: -yr[y])[:k]
    kept = [m for m in ks if m // 100 not in best]
    ex = np.array([s[m] - b[m] for m in kept])
    return {'dropped_years': best, 'ex': round(ex.mean() * 1200, 2), 't': round(nw(ex), 2),
            'years_won': sum(1 for v in yr.values() if v > 0), 'years': len(yr)}


NEIGH = {  # 候補の規則 → 近いパラメータ（同じ地域・同じ頻度）
    'POS10': ['POS10@W60', 'POS10@W180'], 'NC_POS10': ['NC_POS10@W60', 'NC_POS10@W180', 'POS10@W60', 'POS10@W180'],
    'MS_E': ['MS_E@cap0.1', 'MS_E@cap0.3'], 'NC_MS_E': ['NC_MS_E@cap0.1', 'NC_MS_E@cap0.3'],
    'TE4_R': ['TE4_R@te0.03', 'TE4_R@te0.06'], 'TE2_R': ['TE2_R@te0.01', 'TE2_R@te0.03'], 'TE4_E': ['TE4_E@te0.03', 'TE4_E@te0.06'],
    'MSraw_R': ['MSraw_R@cap0.1', 'MSraw_R@cap0.3'], 'NC_MSraw_R': ['NC_MSraw_R@cap0.1', 'NC_MSraw_R@cap0.3'],
    'TH_TE2_R': ['TE2_R'], 'EW': ['RP'], 'RP': ['EW'],
}
PUB_OF = {'EW': 'EW', 'POS10': 'POS10', 'RP': 'RP', 'NC_POS10': 'NC_POS10', 'TE4_R': 'TE4_R', 'TE2_R': 'TE2_R', 'MS_E': 'MS_E',
          'MSraw_R': 'MSraw_R', 'NC_MS_E': 'MS_E', 'NC_MSraw_R': 'MSraw_R', 'TE4_E': 'TE4_R', 'TH_TE2_R': 'TE2_R'}
FLIP_OF = {'EW': 'EW', 'POS10': 'POS10', 'NC_POS10': 'POS10', 'TE4_R': 'TE4_R', 'TE2_R': 'TE2_R', 'MS_E': 'MS_E', 'NC_MS_E': 'MS_E',
           'RP': 'EW', 'TH_TE2_R': 'TE2_R', 'TE4_E': 'TE4_R'}


def analyze(ser):
    claims = json.load(open(os.path.join(BASE, 'out', 'mw_mvo_wf.json')))
    by = {x['name']: x for x in claims['tested']}
    ff = french_monthly('F-F_Research_Data_Factors')
    us_mkt = {m: v['Mkt-RF'] for m, v in ff.items() if v['Mkt-RF'] is not None}
    rf = {m: v['RF'] for m, v in ff.items() if v['RF'] is not None}
    dx = french_monthly('Developed_ex_US_3_Factors')
    fr_dev = {m: v['Mkt-RF'] for m, v in dx.items() if v['Mkt-RF'] is not None}
    em = french_monthly('Emerging_5_Factors')
    fr_em = {m: v['Mkt-RF'] for m, v in em.items() if v['Mkt-RF'] is not None}
    bms, a3s = {}, {}
    for reg in REGIONS:
        R = get_reg(reg)
        bms[reg] = {m: float(v) for m, v in zip(R.cal, R.mkt) if np.isfinite(v)}
        a3s[reg] = all3_of(R)
    bench_check = {
        'jkp_developed_mkt_vs_french_dev_ex_us': {'full': st(bms['developed'], fr_dev), 'hold': st(bms['developed'], fr_dev, a=HOLD_A)},
        'jkp_world_ex_us_mkt_vs_french_dev_ex_us': {'full': st(bms['world_ex_us'], fr_dev), 'hold': st(bms['world_ex_us'], fr_dev, a=HOLD_A)},
        'jkp_emerging_mkt_vs_french_emerging': {'full': st(bms['emerging'], fr_em), 'hold': st(bms['emerging'], fr_em, a=HOLD_A)},
        'jkp_usa_mkt_vw_vs_french_mkt': None,
        'all3_vs_market_hold': {reg: st(a3s[reg], bms[reg], a=HOLD_A) for reg in REGIONS},
        'region_market_vs_us_market_hold': {reg: st(bms[reg], us_mkt, a=HOLD_A, rf=rf) for reg in REGIONS if reg != 'usa'},
    }
    try:
        jus = {ym(x['date']): float(x['ret']) for x in M.jkp_rows('usa', 'mkt', 'factor', 'vw') if x['ret'] not in ('', 'NA', 'na')}
        bench_check['jkp_usa_mkt_vw_vs_french_mkt'] = {'full': st(jus, us_mkt), 'hold': st(jus, us_mkt, a=HOLD_A)}
    except Exception as e:  # noqa
        bench_check['jkp_usa_mkt_vw_vs_french_mkt'] = str(e)
    # 族の Holm（研究者の p を使い、候補だけ自前の p に差し替える）
    fam_p = {}
    for x in claims['tested']:
        fam_p.setdefault(x['family'], {})[x['name']] = x['hold']['p'] if x['hold'] else None
    out = {}
    for name, why in CANDS:
        reg, key = name.split(':')
        rule, fq = key[:-2], key[-1]
        g = ser_get(ser, reg, key, 'g'); n = ser_get(ser, reg, key, 'n')
        n2 = ser_get(ser, reg, key, 'n2'); n3 = ser_get(ser, reg, key, 'n3')
        bm = bms[reg]
        c = by[name]
        r = {'claimed_grade': c['grade'], 'why_selected': why, 'family': c['family']}
        full, train, hold_ = st(g, bm, rf=rf), st(g, bm, z=TRAIN_END, rf=rf), st(g, bm, a=HOLD_A, rf=rf)
        nfull, ntrain, nhold = st(n, bm, rf=rf), st(n, bm, z=TRAIN_END, rf=rf), st(n, bm, a=HOLD_A, rf=rf)
        r20, r20n = roll20(g, bm, rf), roll20(n, bm, rf)
        r['own'] = {'full': full, 'train': train, 'hold': hold_, 'recent_2013_07': st(g, bm, a=RECENT_A, rf=rf),
                    'net_full': nfull, 'net_train': ntrain, 'net_hold': nhold, 'net_recent': st(n, bm, a=RECENT_A, rf=rf),
                    'roll20': r20, 'roll20_net': r20n}
        # 再現の照合
        dif = {'full_ex': round(full['ex'] - c['full']['ex_ann'], 2), 'full_t': round((full['t'] or 0) - (c['full']['t'] or 0), 2),
               'train_ex': round(train['ex'] - c['train']['ex_ann'], 2), 'train_t': round((train['t'] or 0) - (c['train']['t'] or 0), 2),
               'hold_ex': round(hold_['ex'] - c['hold']['ex_ann'], 2), 'hold_t': round((hold_['t'] or 0) - (c['hold']['t'] or 0), 2),
               'hold_cagr': round(hold_['cagr_diff_excess_basis'] - c['hold']['cagr_diff'], 2),
               'net_hold_ex': round(nhold['ex'] - c['net_hold']['ex_ann'], 2),
               'roll20_win': round(r20['win_rate'] - c['roll20']['win_rate'], 3) if r20 and c['roll20'] else None}
        r['diff_vs_claim'] = dif
        r['reproduced'] = all(abs(v) <= 0.05 for k, v in dif.items() if v is not None and k != 'roll20_win') and (dif['roll20_win'] in (None, 0.0) or abs(dif['roll20_win']) <= 0.03)
        # C5（自前）
        pos, det, deth = 0, {}, {}
        for o in REGIONS:
            if o == reg:
                continue
            on = ser_get(ser, o, key, 'n')
            v = st(on, bms[o]) if on else None
            vh = st(on, bms[o], a=HOLD_A) if on else None
            det[o] = v['ex'] if v else None
            deth[o] = vh['ex'] if vh else None
            pos += 1 if v and v['ex'] > 0 else 0
        pv = dict(fam_p[c['family']])
        pv[name] = perr(hold_['t'])
        hp = holm_adj(pv, name)
        crit = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0),
                'C2': bool(hold_['ex'] > 0 and hold_['cagr_diff_excess_basis'] > 0),
                'C3': bool((hold_['t'] or 0) >= 1.65),
                'C4': bool(r20 and r20['win_rate'] >= 0.8),
                'C5': pos / 4 >= 2 / 3,
                'C6': bool(nhold['ex'] > 0 and nhold['cagr_diff_excess_basis'] > 0),
                'C7': bool((full['t'] or 0) >= 3.0 or (hp is not None and hp < 0.05))}
        r['criteria_own'] = crit
        r['c5_own'] = {'regions': 4, 'positive': pos, 'net_full_ex': det, 'report_only_net_hold_ex': deth}
        r['holm_p_own'] = round(hp, 4) if hp is not None else None
        r['letter_grade_from_own_numbers'] = letter(crit)
        # ── 反証の点検 ──
        chk = {}
        chk['vs_US_market_French_Mkt'] = {'hold': st(g, us_mkt, a=HOLD_A, rf=rf), 'net_hold': st(n, us_mkt, a=HOLD_A, rf=rf),
                                          'full': st(g, us_mkt, rf=rf)} if reg != 'usa' else None
        if reg in ('developed', 'world_ex_us'):
            chk['vs_French_Developed_ex_US_Mkt'] = {'hold': st(g, fr_dev, a=HOLD_A), 'net_hold': st(n, fr_dev, a=HOLD_A)}
        if reg == 'emerging':
            chk['vs_French_Emerging_Mkt'] = {'hold': st(g, fr_em, a=HOLD_A), 'net_hold': st(n, fr_em, a=HOLD_A)}
        if reg == 'usa':
            chk['vs_JKP_usa_mkt_vw'] = {'hold': st(g, jus, a=HOLD_A), 'net_hold': st(n, jus, a=HOLD_A)}
        chk['vs_all3_same_universe'] = {'hold': st(g, a3s[reg], a=HOLD_A), 'net_hold': st(n, a3s[reg], a=HOLD_A),
                                        'train': st(g, a3s[reg], z=TRAIN_END)}
        chk['hold_halves'] = {'2007-01..2016-06': st(g, bm, a=200701, z=201606), '2016-07..2025-12': st(g, bm, a=201607),
                              'net_2007-01..2016-06': st(n, bm, a=200701, z=201606), 'net_2016-07..2025-12': st(n, bm, a=201607)}
        chk['cost_multiple'] = {'net_hold_1x': nhold, 'net_hold_2x': st(n2, bm, a=HOLD_A), 'net_hold_3x': st(n3, bm, a=HOLD_A),
                                'cost_pct_per_year_hold': round((hold_['ex'] - nhold['ex']), 2)}
        chk['drop_best_3_years_hold'] = drop_best_years(g, bm)
        chk['drop_best_3_years_net_hold'] = drop_best_years(n, bm)
        nb = {}
        for v in NEIGH.get(rule, []):
            gv = ser_get(ser, reg, f'{v}_{fq}', 'g'); nv = ser_get(ser, reg, f'{v}_{fq}', 'n')
            if gv:
                h, nh = st(gv, bm, a=HOLD_A), st(nv, bm, a=HOLD_A)
                tr = st(gv, bm, z=TRAIN_END)
                nb[v] = {'train_ex': tr['ex'] if tr else None, 'train_t': tr['t'] if tr else None,
                         'hold_ex': h['ex'], 'hold_t': h['t'], 'net_hold_ex': nh['ex'], 'net_hold_t': nh['t']}
        chk['neighbors'] = nb
        pr = PUB_OF.get(rule)
        if pr:
            gv = ser_get(ser, reg, f'{pr}_{fq}', 'g', uni='pub2006'); nv = ser_get(ser, reg, f'{pr}_{fq}', 'n', uni='pub2006')
            if gv:
                chk['pub2006_only'] = {'rule': pr, 'train': st(gv, bm, z=TRAIN_END), 'hold': st(gv, bm, a=HOLD_A), 'net_hold': st(nv, bm, a=HOLD_A)}
        fr_ = FLIP_OF.get(rule)
        if fr_:
            gv = ser_get(ser, reg, f'{fr_}_{fq}', 'g', flip=True); nv = ser_get(ser, reg, f'{fr_}_{fq}', 'n', flip=True)
            if gv:
                chk['mirror_placebo_bad_side'] = {'rule': fr_, 'train': st(gv, bm, z=TRAIN_END), 'hold': st(gv, bm, a=HOLD_A),
                                                  'net_hold': st(nv, bm, a=HOLD_A)}
        if reg == 'world_ex_us' and rule in ('EW', 'POS10', 'NC_POS10', 'RP'):
            base = 'EW' if rule in ('EW', 'RP') else 'POS10'
            loo = {}
            for th in THEMES:
                gv = ser_get(ser, reg, f'{base}_{fq}', 'g', excl=th)
                if gv:
                    h = st(gv, bm, a=HOLD_A)
                    loo[th] = {'hold_ex': h['ex'], 'hold_t': h['t']}
            if loo:
                chk['leave_one_theme_out'] = {'base_rule': base, 'min': min(loo.items(), key=lambda x: x[1]['hold_ex']), 'all': loo}
        r['checks'] = chk
        out[name] = r
    return out, bench_check


def plan_extra():
    return [('world_ex_us', 'all', False, None, ['NC_POS10@W60', 'NC_POS10@W180'], 'main'),
            ('developed', 'all', False, None, ['NC_POS10@W60', 'NC_POS10@W180'], 'main')]


if __name__ == '__main__' and '--extra' in sys.argv:
    import multiprocessing as mp
    ser = {}
    with mp.Pool(2) as pool:
        for tag, res, i0m in pool.imap_unordered(_run, plan_extra()):
            d = ser.setdefault(tag, {'_i0': i0m})
            for k, v in res.items():
                d[k] = {kk: {str(a): round(b, 9) for a, b in vv.items()} for kk, vv in v.items()}
    json.dump(ser, open(CACHE_SER.replace('.json', '_extra.json'), 'w'))
    log('extra done')


INDEP = {  # 候補の地域 → 中身が重ならない地域（world_ex_us ⊃ developed ⊃ jpn・world_ex_us ⊃ emerging）
    'world_ex_us': ['usa'], 'developed': ['usa', 'emerging'], 'emerging': ['usa', 'developed', 'jpn'], 'jpn': ['usa', 'emerging'],
    'usa': ['developed', 'emerging'],
}
DOWN = {'S': 'A', 'A': 'B', 'B': 'C', 'C': 'C'}


def f2(x):
    return 'NA' if x is None else f'{x:+.2f}'


def verdict(name, r):
    reg = name.split(':')[0]
    o, ck = r['own'], r['checks']
    L = r['letter_grade_from_own_numbers']
    strikes, issues = [], []
    h, nh = o['hold'], o['net_hold']
    issues.append(f"再現: 全期間 {f2(o['full']['ex'])}%/年 t{o['full']['t']}・訓練 {f2(o['train']['ex'])} t{o['train']['t']}・保有 {f2(h['ex'])} t{h['t']}"
                  f"（CAGR差 超過基準 {f2(h['cagr_diff_excess_basis'])}・総リターン基準 {f2(h['cagr_diff_total_basis'])}）・費用後 {f2(nh['ex'])} t{nh['t']}・"
                  f"20年窓 {o['roll20']['wins']}/{o['roll20']['windows']}（起点 {o['roll20']['starts'][0]}〜{o['roll20']['starts'][1]}）。研究者との差の最大 "
                  f"{max(abs(v) for v in r['diff_vs_claim'].values() if v is not None):.2f}")
    c2 = ck['cost_multiple']
    n2, n3 = c2['net_hold_2x'], c2['net_hold_3x']
    issues.append(f"費用: 保有期間の費用 {c2['cost_pct_per_year_hold']:.2f}%/年。費用後の保有 t{nh['t']}。2倍 {f2(n2['ex'])}（t{n2['t']}）・3倍 {f2(n3['ex'])}（t{n3['t']}）")
    if reg == 'emerging':
        if n2['ex'] <= 0 or (n2['t'] or 0) < 1.0:
            strikes.append(f"新興国の現実的な費用（2倍・事前登録も感度として挙げた）で費用後が {f2(n2['ex'])}（t{n2['t']}）＝残らない")
    elif n2['ex'] <= 0:
        strikes.append('費用2倍で保有期間の費用後が負け（米国外の売買費用は米国より高いのが普通）')
    if (nh['t'] or 0) < 1.65:
        strikes.append(f"費用後の保有期間の t が {nh['t']}＝費用を払った後の上乗せは統計的に偶然と区別できない")
    hv = ck['hold_halves']
    a1, a2 = hv['2007-01..2016-06'], hv['2016-07..2025-12']
    b1, b2 = hv['net_2007-01..2016-06'], hv['net_2016-07..2025-12']
    issues.append(f"保有期間の前半/後半: 費用前 {f2(a1['ex'])}(t{a1['t']}) / {f2(a2['ex'])}(t{a2['t']})・費用後 {f2(b1['ex'])} / {f2(b2['ex'])}")
    if a1['ex'] <= 0 or a2['ex'] <= 0 or b1['ex'] <= 0 or b2['ex'] <= 0:
        strikes.append('保有期間の前半か後半で負け（費用後を含む）')
    db = ck['drop_best_3_years_hold']
    issues.append(f"保有期間の良い3年 {db['dropped_years']} を除く: {f2(db['ex'])}（t{db['t']}）・勝った年 {db['years_won']}/{db['years']}")
    nb = ck.get('neighbors') or {}
    if nb:
        s_ = '・'.join(f"{k} 保有 {f2(v['hold_ex'])}(t{v['hold_t']}) 費用後 {f2(v['net_hold_ex'])}" for k, v in nb.items())
        issues.append(f"近いパラメータ: {s_}")
        bad = [k for k, v in nb.items() if v['net_hold_ex'] is not None and v['net_hold_ex'] <= 0 and not k.startswith(('EW', 'RP', 'TE2_R')) and '@' in k]
        if bad:
            strikes.append(f"近いパラメータで費用後が負け: {bad}")
    pb = ck.get('pub2006_only')
    if pb:
        issues.append(f"2006年までに公表された特性だけ（{pb['rule']}）: 訓練 {f2(pb['train']['ex'] if pb['train'] else None)} 保有 {f2(pb['hold']['ex'])}(t{pb['hold']['t']}) 費用後 {f2(pb['net_hold']['ex'])}")
        if pb['hold']['ex'] <= 0 or pb['net_hold']['ex'] <= 0:
            strikes.append('2006年までに公表された特性だけにすると保有期間（費用後）が負け＝後の知識の混入')
    mp_ = ck.get('mirror_placebo_bad_side')
    if mp_:
        issues.append(f"鏡の偽薬（同じ規則を悪い側に・{mp_['rule']}）: 訓練 {f2(mp_['train']['ex'] if mp_['train'] else None)} 保有 {f2(mp_['hold']['ex'])}(t{mp_['hold']['t']}) 費用後 {f2(mp_['net_hold']['ex'])}")
        if mp_['hold']['ex'] > 0 and mp_['hold']['ex'] >= 0.5 * h['ex']:
            strikes.append('悪い側の三分位から同じ規則で組んでも保有期間に良い側の半分以上勝つ＝『良い側』を選ぶことは効いておらず、'
                           '勝ちは最適化の仕組み（直近の平均が高い材料へ傾ける）か三分位という材料の作り方から')
    a3 = ck['vs_all3_same_universe']
    issues.append(f"同じ宇宙の選ばない混合 all3 に対して: 保有 {f2(a3['hold']['ex'])}(t{a3['hold']['t']})・費用後 {f2(a3['net_hold']['ex'])}(t{a3['net_hold']['t']})（all3 は費用なしで計算＝厳しめ）")
    lo = ck.get('leave_one_theme_out')
    if lo:
        issues.append(f"テーマを1つ抜く（{lo['base_rule']}）: 最も下がるのは {lo['min'][0]} を抜いたとき 保有 {f2(lo['min'][1]['hold_ex'])}(t{lo['min'][1]['hold_t']})")
    if reg != 'usa':
        us = ck['vs_US_market_French_Mkt']
        issues.append(f"米国の市場（French Mkt≈S&P500）に対して: 保有 {f2(us['hold']['ex'])}%/年（t{us['hold']['t']}）・総リターンの CAGR {us['hold']['cagr_s_total']}% 対 {us['hold']['cagr_b_total']}%・費用後 {f2(us['net_hold']['ex'])}＝この投資家の相手（S&P500）には保有期間に負け")
    else:
        jk = ck['vs_JKP_usa_mkt_vw']
        issues.append(f"JKP usa mkt vw に対して（報告のみ）: 保有 {f2(jk['hold']['ex'])}(t{jk['hold']['t']})")
    if 'vs_French_Developed_ex_US_Mkt' in ck:
        fd = ck['vs_French_Developed_ex_US_Mkt']
        issues.append(f"別の業者の地域の市場（French 米国を除く先進国）に対して: 保有 {f2(fd['hold']['ex'])}(t{fd['hold']['t']})・費用後 {f2(fd['net_hold']['ex'])}")
    if 'vs_French_Emerging_Mkt' in ck:
        fe = ck['vs_French_Emerging_Mkt']
        issues.append(f"別の業者の地域の市場（French 新興国）に対して: 保有 {f2(fe['hold']['ex'])}(t{fe['hold']['t']})・費用後 {f2(fe['net_hold']['ex'])}")
    cv = ck.get('by_country')
    if cv:
        top = sorted(cv['countries'].items(), key=lambda x: -x[1]['net_hold_ex'])
        issues.append(f"国ごと（{cv['rule_used']}・相手はその国の JKP mkt vw）: 費用後の保有が正 {cv['net_hold_positive']}/{cv['n']} 国（費用前 {cv['gross_hold_positive']}/{cv['n']}）・"
                      f"中央 {f2(cv['net_hold_median'])}。上位 {[(c, v['net_hold_ex']) for c, v in top[:3]]}・下位 {[(c, v['net_hold_ex']) for c, v in top[-3:]]}")
        if cv['net_hold_positive'] < cv['n'] / 2:
            strikes.append(f"国ごとに同じ規則を当てると費用後の保有期間が正の国は {cv['net_hold_positive']}/{cv['n']} だけ＝地域の勝ちは一部の国に寄る")
    ind = INDEP[reg]
    ip = sum(1 for x in ind if (r['c5_own']['net_full_ex'].get(x) or -1) > 0)
    issues.append(f"C5（自前）: {r['c5_own']['positive']}/4 地域で費用後の全期間が正 {r['c5_own']['net_full_ex']}。中身の重ならない地域（{ind}）だけなら {ip}/{len(ind)}")
    hh = r['c5_own']['report_only_net_hold_ex']
    issues.append(f"（報告のみ）同じ規則の他の地域の保有期間（2007〜）の費用後: {hh}＝正は {sum(1 for v in hh.values() if (v or -1) > 0)}/4")
    if ip / len(ind) < 2 / 3 and L == 'S':
        strikes.append(f"C5 の再現は重なった地域（world_ex_us ⊃ developed ⊃ jpn・world_ex_us ⊃ emerging）で数えている。重ならない地域では {ip}/{len(ind)}")
    if o['roll20']['windows'] < 5 and L in ('S', 'A'):
        strikes.append(f"C4 の20年窓が {o['roll20']['windows']} 本だけ（起点 {o['roll20']['starts'][0]}〜{o['roll20']['starts'][1]}）＝C4 は実質確かめられていない")
    nbt = [(k, v['train_t']) for k, v in (ck.get('neighbors') or {}).items() if '@' in k and v.get('train_t') is not None]
    if o['train']['t'] is not None and o['train']['t'] < 2.2 and any(t_ < 2.0 for _, t_ in nbt):
        strikes.append(f"C1 は線 2.0 の際（訓練 t{o['train']['t']}）で、近いパラメータ {[(k, t_) for k, t_ in nbt if t_ < 2.0]} では C1 が落ちる")
    if (h['t'] or 0) < 3.76 and (nh['t'] or 0) < 2.0:
        strikes.append(f"多重検定: 角度の300本の Bonferroni（t≈3.76）に保有の t{h['t']} が届かず、費用後の t{nh['t']} も2未満")
    if reg != 'usa' and o['roll20']['windows'] <= 12:
        issues.append(f"C4 の20年窓は {o['roll20']['windows']} 本だけで、起点 {o['roll20']['starts'][0]}〜{o['roll20']['starts'][1]}＝どの窓も保有期間（2007〜）を半分以上含む＝C2 と独立の証拠ではない")
    issues.append(f"多重検定: この角度は300本（主110＋探索190）。保有の t {h['t']} はプログラム全体の Bonferroni の線 t≈4.35 に"
                  f"{'届く' if (h['t'] or 0) >= 4.35 else '届かない'}（費用後の t {nh['t']} は届かない）。角度の中の Bonferroni（300本・両側5%）の線は t≈3.76")
    # 格付け
    if r['family'] != 'P_primary_110':
        strikes.append('探索の族（主の族の保有期間の結果を見た後に登録）' + ('。費用を平均から引く手当ては、主の族の保有期間の費用（米国の最大シャープで年1.3〜1.7%）を見てから足した'
                       if r['family'].startswith('E2') else '。テーマへまとめる手当ては論文から決めたが、主の族の結果を見た後'))
    g = L
    if strikes:
        g = DOWN[g]
        if len(strikes) >= 3:
            g = DOWN[g]
    if not r['reproduced']:
        issues.insert(0, '⚠ 数字の再現に差がある（diff_vs_claim）')
    v = 'confirmed' if g == r['claimed_grade'] else ('refuted' if g == 'C' else f'downgraded to {g}')
    if g == r['claimed_grade'] == 'C':
        v = 'confirmed'
    return g, v, strikes, issues


DEV_C = ['jpn', 'gbr', 'fra', 'deu', 'che', 'nld', 'swe', 'aus', 'can', 'hkg']
EM_C = ['kor', 'twn', 'chn', 'ind']
CTRY_RULE = {'EW': 'EW', 'RP': 'EW', 'POS10': 'POS10', 'NC_POS10': 'NC_POS10', 'MS_E': 'MS_E', 'NC_MS_E': 'NC_MS_E'}


def country_view(ctry, name):
    """（反証の点検）国ごとに同じ規則をその国の市場と比べ、勝ちが一部の国に寄っていないか。
    線は結果を見る前に決めた: 候補の地域に入る国のうち、費用後の保有期間が正の国が半分未満なら『傷』"""
    reg, key = name.split(':')
    rule = key[:-2]
    base = CTRY_RULE.get(rule)
    if not base or reg == 'usa' or not ctry:
        return None
    cs = {'world_ex_us': DEV_C + EM_C, 'developed': DEV_C, 'emerging': EM_C, 'jpn': ['jpn']}[reg]
    rows = {}
    for c in cs:
        d = (ctry.get(c) or {}).get('rules', {}).get(f'{base}_M')
        if not d or not d.get('hold'):
            continue
        rows[c] = {'start': ctry[c]['start'], 'relaxed': ctry[c]['relaxed_start'], 'hold_ex': d['hold']['ex'], 'hold_t': d['hold']['t'],
                   'net_hold_ex': d['net_hold']['ex'], 'net_hold_t': d['net_hold']['t'],
                   'net_2x_ex': d['net_hold_2x']['ex'] if d.get('net_hold_2x') else None,
                   'net_second_half_ex': d['net_second_half']['ex'] if d.get('net_second_half') else None}
    if not rows:
        return None
    pos = sum(1 for v in rows.values() if v['net_hold_ex'] > 0)
    vals = sorted(v['net_hold_ex'] for v in rows.values())
    return {'rule_used': f'{base}_M（毎月）', 'countries': rows, 'net_hold_positive': pos, 'n': len(rows),
            'net_hold_median': vals[len(vals) // 2], 'gross_hold_positive': sum(1 for v in rows.values() if v['hold_ex'] > 0)}


def main_analyze():
    t0 = time.time()
    ser = json.load(open(CACHE_SER))
    ex = CACHE_SER.replace('.json', '_extra.json')
    if os.path.exists(ex):
        for tag, d in json.load(open(ex)).items():
            ser.setdefault(tag, {}).update({k: v for k, v in d.items() if k != '_i0'})
    res, bench = analyze(ser)
    cf = CACHE_SER.replace('.json', '_countries.json')
    ctry = json.load(open(cf)) if os.path.exists(cf) else None
    for name, r in res.items():
        cv = country_view(ctry, name)
        if cv:
            r['checks']['by_country'] = cv
    verdicts, counts = {}, {}
    for name, r in res.items():
        g, v, strikes, issues = verdict(name, r)
        r['verified_grade'] = g
        r['verdict'] = v
        r['strikes'] = strikes
        r['issues'] = issues
        counts[v] = counts.get(v, 0) + 1
        o = r['own']
        r['key_numbers'] = (f"全期間 {f2(o['full']['ex'])}%/年 t{o['full']['t']}・訓練 {f2(o['train']['ex'])} t{o['train']['t']}・"
                            f"保有 {f2(o['hold']['ex'])} t{o['hold']['t']}・CAGR差 {f2(o['hold']['cagr_diff_excess_basis'])}・"
                            f"費用後 {f2(o['net_hold']['ex'])} t{o['net_hold']['t']}・20年窓 {o['roll20']['wins']}/{o['roll20']['windows']}")
        log(f"{name:28s} 主張 {r['claimed_grade']} 自前の線 {r['letter_grade_from_own_numbers']} → {g} ({v}) 再現 {r['reproduced']} | {r['key_numbers']}")
        for s_ in strikes:
            log('    ✗', s_)
    return res, bench, counts, time.time() - t0


SUMMARY_JA = '''31本（主の族の S/A 全21本＋保有期間の t の上位の探索4本＋要約で名指しされた探索の NC_MS_E_M と米国の A 3本＋B の上位2本）を自前のコードで作り直し、全本で研究者の数字を小数2桁まで再現しました（最大シャープは研究者と別の解き方で同じ解）。
反証の点検の後、S は0本です（A 13・B 10・C 8）。
米国の A 4本（TE4_R_M・探索の NC_MSraw_R_M・NC_POS10_M/A）はすべて C です。費用後の保有期間は t0.3〜0.8、保有期間の前半（2007〜2016）は負けで勝ちは2016年以降だけ、2006年までに公表された特性だけにすると保有期間は0か負けです。
米国外の 1/N・リスク均等・POS10（world_ex_us）は数字どおり（保有 +1.06〜1.14%/年 t4.7〜5.3）ですが A 止まりです。費用後は +0.44〜0.52（t2前後）で費用2倍では負け、費用後の後半（2016-07〜）は +0.02〜0.09 でほぼ0、同じ宇宙の選ばない混合 all3 に対する費用後の上乗せは +0.1〜0.2（t≈1）です。developed 版は B（国ごとに当てると費用後に勝つのは10か国中3〜4か国）。
最大シャープ（world_ex_us:MS_E）は保有 +2.0%/年 t3.4〜3.8 で A です。国ごとに当てると費用後に勝つのは14か国中6か国で、地域をまたぐ国の選び方に依ります。C1 は線の際で、角度300本の多重検定にも届きません。新興国の MSraw_R は20年窓が3本しかなく、新興国の費用（2倍）で消えるので A/B です。
最も頑丈なのは探索の NC_POS10 です（費用を引いた過去10年の勝ち材料の等分・world_ex_us 費用後 +0.83 t3.7・費用2倍でも +0.46）。ただし主の族の結果を見た後に登録したので A です。
どれも紙の上の三分位で、この投資家の相手（S&P500≈French Mkt）には保有期間に年3〜4%負けています（米国外の市場そのものが年5%以上負けた）。'''


def write(res, bench, counts, rt, summary_ja='', extra=None):
    claims = json.load(open(os.path.join(BASE, 'out', 'mw_mvo_wf.json')))
    vd = {}
    det = {}
    for name, r in res.items():
        vd[name] = {k: r[k] for k in ('claimed_grade', 'verified_grade', 'verdict', 'reproduced', 'letter_grade_from_own_numbers', 'criteria_own',
                                      'c5_own', 'holm_p_own', 'why_selected', 'family', 'key_numbers', 'strikes', 'issues')}
        det[name] = {'own': r['own'], 'diff_vs_claim': r['diff_vs_claim'], 'checks': r['checks']}
    obj = {'angle': 'mvo_wf', 'role': '反証の検証（adversarial verifier）', 'generated': time.strftime('%Y-%m-%d'),
           'inputs': {'claims': f"out/mw_mvo_wf.json（{claims['n_tested']}本・{claims['grade_counts']}）",
                      'prereg': ['out/mw_prereg.json', 'out/mw_mvo_wf_prereg.json（8f87abe）', 'out/mw_mvo_wf_prereg2.json（010ba2f）'],
                      'scope': 'S・A が64本あるので、主の族の S/A 全21本＋保有期間の t の上位8本のうち主以外の4本＋研究者が要約で名指しした探索の'
                               ' world_ex_us:NC_MS_E_M と米国の A 3本（NC_MSraw_R_M・NC_POS10_M/A）＋B の保有期間の超過の上位2本（developed:MSraw_R_A・NC_MSraw_R_A）＝31本'},
           'independence': 'mw_common からは取得（get・jkp_rows・FR の置き場所）だけを使用。French の CSV の読み取り・良い側（走る和）・材料になれる条件・'
                           'Ledoit-Wolf（論文の式から）・James-Stein・二次計画（自前の主有効制約法＋射影勾配の予備）・最大シャープ（log λ の格子を三段に詰める＝'
                           '研究者の不動点法とは別の解き方）・TE の予算（κ の二分法）・リスク均等（循環座標降下＝研究者のニュートン法とは別）・持ち方・漂い・費用・'
                           '超過・NW t・CAGR・20年窓・線の当てはめは自前。研究者のコード（night/mw_mvo_wf.py）は import していない'
                           '（開発中の診断で最大シャープの解を研究者の解法と一度だけ突き合わせ、自前の黄金分割が平らな所で道を誤ることを見つけて格子へ直した）',
           'verdict_policy': 'letter_grade_from_own_numbers は自前の数字に out/mw_prereg.json の線（C1〜C7・C5 も自前で数え直し・C7 の Holm は研究者の族の p に'
                             '候補だけ自前の p を差し替え）をそのまま当てた格付け。verified_grade はその上で反証の点検を効かせた判断で、次のどれかに当たるごとに'
                             '「傷」1つ——(a) 費用2倍で保有期間の費用後が負け（新興国は費用2倍で t<1 でも）(b) 費用後の保有の t<1.65 '
                             '(c) 保有期間の前半（2007-01〜2016-06）か後半（2016-07〜2025-12）で費用前・費用後のどれかが負け '
                             '(d) 近いパラメータ（窓・上限・TE 予算）で費用後が負け (e) 2006年までに公表された特性だけで保有期間（費用後）が負け '
                             '(f) 悪い側の三分位から同じ規則で組んでも保有期間に半分以上勝つ (g) S の C5 が重なった地域でしか成り立たない '
                             '(h) C4 の20年窓が5本未満 (i) C1 が線の際（t<2.2）で近いパラメータでは落ちる '
                             '(j) 保有の t が角度の300本の Bonferroni（3.76）に届かず費用後の t も2未満 (k) 探索の族 '
                             '(l) 国ごとに同じ規則（毎月版）を当てて費用後の保有期間が正の国が半分未満（米国外の EW・RP・POS10・MS_E 系だけ・線は結果を見る前に決めた）。'
                             '傷1〜2で1段、3以上で2段下げる。迷ったら下げた。米国の市場（French Mkt）に対する数字はこの投資家の相手として報告するが、'
                             '格付けは事前登録どおり同じ地域の相手で行う',
           'counts': counts, 'summary_ja': summary_ja, 'verdicts': vd, 'benchmark_checks': bench, 'details': det,
           'extra': extra or {}, 'runtime_sec': round(rt), 'log_tail': LOG[-150:]}
    json.dump(obj, open(OUTF, 'w'), ensure_ascii=False, indent=1, default=lambda x: float(x) if isinstance(x, np.floating) else int(x) if isinstance(x, np.integer) else str(x))
    log('保存', OUTF, f'{os.path.getsize(OUTF) / 1e6:.2f} MB')


COUNTRIES = ['jpn', 'gbr', 'fra', 'deu', 'che', 'nld', 'swe', 'aus', 'can', 'hkg', 'kor', 'twn', 'chn', 'ind']


def _run_country(c):
    """（報告のみ）国ごとに同じ規則: 勝ちが一部の国に寄っていないか。始まりは主の規則（材料100本）→無ければ60本へ緩めて記録"""
    t0 = time.time()
    try:
        R = get_reg(c)
    except Exception as e:  # noqa
        return c, {'error': str(e)}, None, None
    i0, relaxed = R.start(), False
    if i0 is None:
        for i in range(WIN - 1, len(R.cal) - 1):
            if R.cal[i] % 100 == 12 and R.mkt_ok(i) and len(R.eligible(i)) >= 60:
                i0, relaxed = i, True
                break
    if i0 is None:
        return c, {'error': '材料が足りない'}, None, None
    rules = ['EW', 'POS10', 'NC_POS10', 'MS_E', 'NC_MS_E']
    B = Book(R, rules, i0)
    tg = {r: {} for r in rules}
    for i in range(i0, len(R.cal) - 1):
        o = B.targets(i)
        for r in rules:
            tg[r][i] = o[r]
    bm = {m: float(v) for m, v in zip(R.cal, R.mkt) if np.isfinite(v)}
    out = {}
    for r in rules:
        g, n = hold(R, tg[r], i0, 'M')
        _, n2 = hold(R, tg[r], i0, 'M', 2.0)
        out[f'{r}_M'] = {'full': st(g, bm), 'train': st(g, bm, z=TRAIN_END), 'hold': st(g, bm, a=HOLD_A), 'net_hold': st(n, bm, a=HOLD_A),
                         'net_hold_2x': st(n2, bm, a=HOLD_A), 'net_second_half': st(n, bm, a=201607)}
    log(f'  国 {c} 最初の組み入れ {R.cal[i0]}{"（材料60本に緩めた）" if relaxed else ""} {time.time() - t0:.0f}s')
    return c, out, R.cal[i0], relaxed


if __name__ == '__main__' and '--countries' in sys.argv:
    import multiprocessing as mp
    res = {}
    with mp.Pool(4) as pool:
        for c, out, s0, rl in pool.imap_unordered(_run_country, COUNTRIES):
            res[c] = {'start': s0, 'relaxed_start': rl, 'rules': out}
    json.dump(res, open(CACHE_SER.replace('.json', '_countries.json'), 'w'), default=float)
    log('countries done')


if __name__ == '__main__' and '--analyze' in sys.argv:
    res, bench, counts, rt = main_analyze()
    cf = CACHE_SER.replace('.json', '_countries.json')
    extra = {'by_country_all': json.load(open(cf)) if os.path.exists(cf) else None,
             'qp_note': '二次計画は自前の主有効制約法。退化で回り続けた回（全体の約0.02%）は射影勾配の予備へ。31本すべてで研究者の数字を小数2桁で再現したので結果への影響は無い'}
    write(res, bench, counts, rt, SUMMARY_JA, extra)
