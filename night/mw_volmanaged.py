#!/usr/bin/env python3
"""night/mw_volmanaged.py — 『市場に勝てる歴史検証』角度 volmanaged: ボラティリティで倍率を変える市場投資

読むだけ（門の判定・採点・配分には不使用）。事前登録 out/mw_volmanaged_prereg.json の規則をそのまま測り、
out/mw_volmanaged.json へ書く。線は out/mw_prereg.json（mw_common.grade）。

規則（Moreira & Muir 2017 の既定値・結果を見る前に固定）
- 月末 t に倍率 w_t = min(上限, c / X_t)（X = 前月の実現分散 RV1 / √RV1 / 6か月の RV6 / EWMA / 下方の RV）、翌月 t+1 に使う
- トレンドつき: 月末の総リターン指数が10か月線より下なら w_t = 0（全額 RF）
- 1倍を超えた分は RF+0.5%/年で借りる。売買費用は |w_t − 漂った倍率| × 0.10%
- c は訓練期間（〜2006-12）だけで『ぶれが相手と同じ』になるように解く（主）／過去だけで毎年解き直す（探索 E1）
相手は同じ指数をレバレッジなしで買って持つだけ（総リターンどうし）。

使い方: python3 night/mw_volmanaged.py            （全部測って書く）
        python3 night/mw_volmanaged.py --check    （データと検算だけ。戦略と市場を比べた数字は出さない）
"""
import sys, os, json, math, datetime, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M
import numpy as np

PRE_NAMES = ['mw_volmanaged_prereg.json', 'mw_volmanaged_prereg2.json', 'mw_volmanaged_prereg3.json']
IXIC_DIV = 0.010
OUT_NAME = 'mw_volmanaged.json'
COST = 0.001       # 判定用: 片道売買100%あたり0.10%（全体の事前登録の既定）
COST_LO = 0.0005   # 報告: 指示書の0.05%
SPREAD = 0.005     # 1倍を超えた分の借入の上乗せ（年率）
SPREAD_HI = 0.02   # 報告: 日本の個人の信用取引に近い上乗せ
TAX = 0.20315
NDX_DIV = 0.005
FR_END = 20260831
YH_P2 = 1790000000  # trend の角度と同じ URL（キャッシュを共有）
POST_PUB = 201701
MIN_DAYS = 10
EXP_MIN = 60
CAPS = [1.5, 2.0]

LOG = []


def _excess_stats_fast(s, b, a=None, z=None, per_year=12, lag=12):
    """mw_common.excess_stats と同じ計算（同じ式・同じ丸め）。β の計算で S.mean を要素ごとに呼び直す二乗の遅さだけを避ける
    （mw_common は他の角度が使うので編集しない。平均を一度だけ計算するので値は一致する）"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < max(24, per_year * 2):
        return None
    ex = [s[k] - b[k] for k in ks]
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    te = S.stdev(ex) * math.sqrt(per_year)
    vb = S.pvariance(bv)
    ms_, mb_ = S.mean(sv), S.mean(bv)
    beta = sum((x - ms_) * (y - mb_) for x, y in zip(sv, bv)) / len(ks) / vb if vb else None
    t = M.nw_t(ex, lag)
    g_s, g_b = M.cagr(sv, per_year), M.cagr(bv, per_year)
    return {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / per_year, 1),
            'ex_ann': round(S.mean(ex) * per_year * 100, 2), 't': round(t, 2) if t is not None else None,
            'p': round(M.p_two(t), 4) if t is not None else None,
            'cagr_s': round(g_s * 100, 2), 'cagr_b': round(g_b * 100, 2), 'cagr_diff': round((g_s - g_b) * 100, 2),
            'te': round(te * 100, 2), 'ir': round(S.mean(ex) * per_year / te, 2) if te else None,
            'beta': round(beta, 2) if beta is not None else None,
            'vol_s': round(S.stdev(sv) * math.sqrt(per_year) * 100, 1), 'vol_b': round(S.stdev(bv) * math.sqrt(per_year) * 100, 1)}


_ORIG_EXCESS_STATS = M.excess_stats
M.excess_stats = _excess_stats_fast


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── データ ─────────────────────────
def yh_daily(tk):
    """Yahoo 日次 → (終値 dict, 調整後終値 dict) キーは yyyymmdd（trend の角度と同じ URL・キャッシュ名）"""
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1=-2000000000&period2={YH_P2}&interval=1d&events=div%2Csplit'
    j = json.loads(M.get(u, name=f'trend_yh_{tk.replace("^", "IDX_")}_1d_full.json', max_age_days=3650))
    r = j['chart']['result'][0]
    cl = r['indicators']['quote'][0]['close']
    adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or cl
    px, pa = {}, {}
    for t, c, a in zip(r['timestamp'], cl, adj):
        d = datetime.datetime.utcfromtimestamp(t)
        k = d.year * 10000 + d.month * 100 + d.day
        if c is not None:
            px[k] = c
        if a is not None:
            pa[k] = a
    return px, pa


def rets(px):
    ks = sorted(px)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:])}


def fr_region(name, freq):
    """French 地域ファイル → (Mkt 総リターン, RF)（小数）"""
    for t, v in M.french_tables(name).items():
        if v['freq'] == freq:
            ci, ri = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            mkt, rf = {}, {}
            for d, row in v['data'].items():
                if row[ci] is None or row[ri] is None:
                    continue
                mkt[d] = (row[ci] + row[ri]) / 100
                rf[d] = row[ri] / 100
            return mkt, rf
    raise KeyError(name)


class Mk:
    """一つの市場: 日次の超過（RV 用）・日次の総リターンと RF（E5 用）・月次の総リターンと RF"""

    def __init__(self, name, dex, dtot, drf, m, rf, train_end=M.TRAIN_END):
        self.name = name
        self.dex, self.dtot, self.drf = dex, dtot, drf
        ms = sorted(k for k in m if k in rf)
        # 月は連続していること（欠けを埋めない＝連続でない所で切る: 最長の連続区間を使う）
        runs, cur = [], [ms[0]]
        for a, b in zip(ms, ms[1:]):
            if nxt(a) == b:
                cur.append(b)
            else:
                runs.append(cur); cur = [b]
        runs.append(cur)
        best = max(runs, key=len)
        self.gaps = len(runs) - 1
        self.months = best
        self.m = {k: m[k] for k in best}
        self.rf = {k: rf[k] for k in best}
        self.train_end = train_end
        self._X = {}
        self.trend = sma10(self.months, self.m)

    def X(self, kind):
        if kind not in self._X:
            self._X[kind] = measures(self.dex)[kind]
        return self._X[kind]


def nxt(ym):
    y, mo = divmod(ym, 100)
    return (y + 1) * 100 + 1 if mo == 12 else ym + 1


def prv(ym):
    y, mo = divmod(ym, 100)
    return (y - 1) * 100 + 12 if mo == 1 else ym - 1


_MEAS = {}


def measures(dex):
    """日次の超過 {yyyymmdd: r} → {'VAR1','VOL1','VAR6','EWMA','DOWN': {yyyymm: 値}}（欠測は入れない）"""
    key = id(dex)
    if key in _MEAS:
        return _MEAS[key]
    by = {}
    for d in sorted(dex):
        by.setdefault(d // 100, []).append(dex[d])
    var1, down, ewma = {}, {}, {}
    for ym, xs in by.items():
        if len(xs) >= MIN_DAYS:
            mu = sum(xs) / len(xs)
            var1[ym] = sum((x - mu) ** 2 for x in xs)
            down[ym] = sum(x * x for x in xs if x < 0)
    yms = sorted(by)
    var6 = {}
    for i in range(5, len(yms)):
        w = yms[i - 5:i + 1]
        if any(nxt(a) != b for a, b in zip(w, w[1:])) or any(len(by[k]) < MIN_DAYS for k in w):
            continue
        xs = [x for k in w for x in by[k]]
        mu = sum(xs) / len(xs)
        var6[yms[i]] = sum((x - mu) ** 2 for x in xs) / 6
    # EWMA（RiskMetrics λ=0.94）: 最初の21日の二乗平均で始め、月末の値を記録（最初の月は記録しない）
    ds = sorted(dex)
    lam, v = 0.94, None
    for i, d in enumerate(ds):
        r = dex[d]
        if v is None:
            if i == 20:
                v = sum(dex[x] ** 2 for x in ds[:21]) / 21
            continue
        v = lam * v + (1 - lam) * r * r
        if i == len(ds) - 1 or ds[i + 1] // 100 != d // 100:
            ewma[d // 100] = v * 21  # 月あたりへ（尺度は c が吸収する）
    first = ds[0] // 100
    ewma.pop(first, None)
    out = {'VAR1': var1, 'VOL1': {k: math.sqrt(x) for k, x in var1.items()}, 'VAR6': var6, 'EWMA': ewma, 'DOWN': down}
    _MEAS[key] = out
    return out


def sma10(months, m):
    """月末の総リターン指数 > 直近10か月の平均 → 1（t の値は t の月末までで決まる）"""
    idx, w = {}, 1.0
    for k in months:
        w *= 1 + m[k]
        idx[k] = w
    out = {}
    for i in range(9, len(months)):
        vals = [idx[months[j]] for j in range(i - 9, i + 1)]
        out[months[i]] = 1 if idx[months[i]] > sum(vals) / 10 else 0
    return out


# ───────────────────────── 規則 ─────────────────────────
def weight(x, c, cap, on):
    if on == 0:
        return 0.0
    if c == math.inf:
        return cap
    if x == 0:
        return cap
    return min(cap, c / x)


def pairs(mk, X, trend, end=None, start=None):
    """(t0, t1) の組: t0 の月末に X と（トレンドなら）信号が分かり、t1 = 翌月のリターンがある"""
    out = []
    for t0, t1 in zip(mk.months, mk.months[1:]):
        if end is not None and t1 > end:
            break
        if start is not None and t1 < start:
            continue
        x = X.get(t0)
        if x is None:
            continue
        on = 1
        if trend:
            on = mk.trend.get(t0)
            if on is None:
                continue
        out.append((t0, t1, x, on))
    return out


def solve_c(mk, X, cap, trend, end, spread=SPREAD, min_pairs=24):
    """訓練（t1 ≤ end）の超過のぶれが相手と同じになる c（上限・トレンドを掛けた後の規則そのもの）。二分法（対数）"""
    P = pairs(mk, X, trend, end=end)
    if len(P) < min_pairs:
        return None, None
    xs = np.array([p[2] for p in P]); on = np.array([p[3] for p in P], dtype=float)
    ex = np.array([mk.m[p[1]] - mk.rf[p[1]] for p in P])
    target = ex.std(ddof=1)

    def sd(c):
        if c == math.inf:
            w = np.full(len(xs), cap)
        else:
            with np.errstate(divide='ignore'):
                w = np.where(xs > 0, np.minimum(cap, c / np.where(xs > 0, xs, 1.0)), cap)
        w = w * on
        s = w * ex - np.maximum(w - 1, 0) * spread / 12
        return s.std(ddof=1)

    if cap != math.inf and sd(math.inf) < target:
        return math.inf, {'pairs': len(P), 'target_sd': float(target), 'sd_at_c': float(sd(math.inf)), 'note': '上限いっぱいでも届かない → c=∞'}
    med = float(np.median(xs[xs > 0])) if (xs > 0).any() else 1.0
    lo, hi = math.log(med * 1e-8), math.log(med * 1e8)
    for _ in range(80):
        mid = (lo + hi) / 2
        if sd(math.exp(mid)) < target:
            lo = mid
        else:
            hi = mid
    c = math.exp((lo + hi) / 2)
    return c, {'pairs': len(P), 'from': P[0][1], 'to': P[-1][1], 'target_sd_ann': round(float(target) * math.sqrt(12) * 100, 3),
               'sd_at_c_ann': round(float(sd(c)) * math.sqrt(12) * 100, 3)}


def solve_c_beta(mk, X, cap, trend, end, spread=SPREAD, min_pairs=24, target_beta=1.0):
    """第2族: 訓練（t1 ≤ end）で『戦略の超過を相手の超過に回帰した傾き β = 1』になる c（上限・トレンドを掛けた後の規則そのもの）。二分法（対数）"""
    P = pairs(mk, X, trend, end=end)
    if len(P) < min_pairs:
        return None, None
    xs = np.array([p[2] for p in P]); on = np.array([p[3] for p in P], dtype=float)
    ex = np.array([mk.m[p[1]] - mk.rf[p[1]] for p in P])
    exd = ex - ex.mean(); vx = (exd ** 2).sum()

    def beta(c):
        if c == math.inf:
            w = np.full(len(xs), cap)
        else:
            w = np.where(xs > 0, np.minimum(cap, c / np.where(xs > 0, xs, 1.0)), cap)
        w = w * on
        s = w * ex - np.maximum(w - 1, 0) * spread / 12
        return float(((s - s.mean()) * exd).sum() / vx)

    if cap != math.inf and beta(math.inf) < target_beta:
        return math.inf, {'pairs': len(P), 'beta_at_c': beta(math.inf), 'note': '上限いっぱいでも β が1に届かない → c=∞'}
    med = float(np.median(xs[xs > 0])) if (xs > 0).any() else 1.0
    lo, hi = math.log(med * 1e-8), math.log(med * 1e8)
    for _ in range(80):
        mid = (lo + hi) / 2
        if beta(math.exp(mid)) < target_beta:
            lo = mid
        else:
            hi = mid
    c = math.exp((lo + hi) / 2)
    return c, {'pairs': len(P), 'from': P[0][1], 'to': P[-1][1], 'beta_at_c': round(beta(c), 4)}


def c_expanding(mk, X, cap, trend, solver=None):
    """毎年12月末に、その時点までの全データで c を解き、12月末〜翌年11月末に決める倍率に使う（60か月そろってから）"""
    solver = solver or solve_c
    out = {}
    decs = [k for k in mk.months if k % 100 == 12]
    for T in decs:
        c, _ = solver(mk, X, cap, trend, end=T, min_pairs=EXP_MIN)
        if c is None:
            continue
        t = T
        for _ in range(12):
            out[t] = c
            t = nxt(t)
    return out


def run_monthly(mk, X, cap, c, trend, c_by=None, w_by=None):
    """月次: w_t（t の月末に決定）を t+1 に使う。gross / net / net05 / net_sp2 と倍率・売買額。
    w_by を渡すと、その倍率（キーは決めた月末 t0）をそのまま使う（第3族の3信号の平均）"""
    g, n, n5, ns2, W, TR = {}, {}, {}, {}, {}, {}
    prev_w = prev_t1 = None
    prev_s = None
    gaps = 0
    for t0, t1 in zip(mk.months, mk.months[1:]):
        if w_by is not None:
            w = w_by.get(t0)
            if w is None:
                if prev_w is not None:
                    gaps += 1
                prev_w = None
                continue
        else:
            x = X.get(t0)
            on = mk.trend.get(t0) if trend else 1
            cc = c if c_by is None else c_by.get(t0)
            if x is None or on is None or cc is None:
                if prev_w is not None:
                    gaps += 1
                prev_w = None
                continue
            w = weight(x, cc, cap, on)
        m, rf = mk.m[t1], mk.rf[t1]
        if prev_w is not None and prev_t1 == t0:
            drift = prev_w * (1 + mk.m[t0]) / (1 + prev_s) if (1 + prev_s) != 0 else prev_w
        else:
            drift = 1.0  # 買って持つだけから乗り換える
        trade = abs(w - drift)
        sg = w * m + (1 - w) * rf - max(w - 1, 0) * SPREAD / 12
        s2 = w * m + (1 - w) * rf - max(w - 1, 0) * SPREAD_HI / 12
        g[t1] = sg
        n[t1] = sg - trade * COST
        n5[t1] = sg - trade * COST_LO
        ns2[t1] = s2 - trade * COST
        W[t1] = w; TR[t1] = trade
        prev_w, prev_t1, prev_s = w, t1, sg
    return {'gross': g, 'net': n, 'net05': n5, 'net_sp2': ns2, 'w': W, 'trade': TR, 'gaps': gaps}


def run_daily_lag(mk, X, cap, c, trend):
    """E5: 月末 t に決めた倍率を、t+1 の最初の営業日の終値で売買（日次で持ち高を追う）。月末の資産から月次リターン"""
    D = sorted(d for d in mk.dtot if d in mk.drf)
    out = {}
    for label, cost in (('gross', 0.0), ('net', COST)):
        Wt = 1.0; E = 1.0; B = 0.0
        started = False
        last_me = None
        w_pending = None
        wk = {}
        prev_d = None
        for i, d in enumerate(D):
            ym = d // 100
            new_month = prev_d is not None and prev_d // 100 != ym
            if new_month:
                # 前の月末（prev_d）で倍率が決まる
                t0 = prev_d // 100
                x = X.get(t0); on = mk.trend.get(t0) if trend else 1
                w_pending = weight(x, c, cap, on) if (x is not None and on is not None) else None
                if started:
                    out.setdefault(label, {})[t0] = Wt / last_me - 1
                if w_pending is not None and not started:
                    started = True; Wt = 1.0; E = 1.0; B = 0.0
                last_me = Wt
                first_day = True
            else:
                first_day = False
            if started:
                r = mk.dtot[d]; rf = mk.drf[d]
                E *= 1 + r
                if B < 0:
                    dd = (datetime.date(d // 10000, d // 100 % 100, d % 100) - datetime.date(prev_d // 10000, prev_d // 100 % 100, prev_d % 100)).days
                    B *= 1 + rf + SPREAD * dd / 365
                else:
                    B *= 1 + rf
                Wt = E + B
                if first_day and w_pending is not None:
                    tgt = w_pending * Wt
                    Wt -= abs(tgt - E) * cost
                    E = w_pending * Wt
                    B = Wt - E
                    wk[ym] = w_pending
                elif first_day and w_pending is None:
                    pass  # 倍率が決まらない月は前の持ち高のまま（欠けを埋めない: この月は記録から外す）
            prev_d = d
        # 最後の月（月末まで来ていれば）
        if started and D and (D[-1] == FR_END or D[-1] // 100 < FR_END // 100):
            out.setdefault(label, {})[D[-1] // 100] = Wt / last_me - 1
        out['w_' + label] = wk
    # 月の中で倍率が決まらなかった月は外す
    ok = set(out.get('w_net', {}))
    g = {k: v for k, v in out.get('gross', {}).items() if k in ok}
    n = {k: v for k, v in out.get('net', {}).items() if k in ok}
    bench = M.to_monthly({d: mk.dtot[d] for d in D})
    return {'gross': g, 'net': n, 'net05': None, 'net_sp2': None, 'w': out.get('w_net', {}), 'trade': {}, 'gaps': 0, 'bench': bench}


# ───────────────────────── 評価 ─────────────────────────
def capm_alpha(s, b, rf, a=None, z=None):
    ks = sorted(k for k in set(s) & set(b) & set(rf) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 36:
        return None
    y = [s[k] - rf[k] for k in ks]; x = [b[k] - rf[k] for k in ks]
    mx, my = S.mean(x), S.mean(y)
    beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sum((xi - mx) ** 2 for xi in x)
    e = [yi - beta * xi for xi, yi in zip(x, y)]
    t = M.nw_t(e, 12)
    r2 = M.corr(x, y) ** 2
    res = [yi - my - beta * (xi - mx) for xi, yi in zip(x, y)]
    sde = S.stdev(res) * math.sqrt(12)
    return {'from': ks[0], 'to': ks[-1], 'alpha_ann': round(S.mean(e) * 1200, 2), 't': round(t, 2) if t is not None else None, 'beta': round(beta, 3),
            'r2': round(r2, 3), 'appraisal': round(S.mean(e) * 12 / sde, 3) if sde else None}


def sharpe_test(s, b, rf, a=None, z=None):
    """Jobson-Korkie（Memmel 2003 の補正）: 月次のシャープレシオの差の z"""
    ks = sorted(k for k in set(s) & set(b) & set(rf) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 36:
        return None
    y1 = [s[k] - rf[k] for k in ks]; y2 = [b[k] - rf[k] for k in ks]
    s1, s2 = S.mean(y1) / S.stdev(y1), S.mean(y2) / S.stdev(y2)
    rho = M.corr(y1, y2); T = len(ks)
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T
    zz = (s1 - s2) / math.sqrt(var) if var > 0 else None
    return {'sr_s_ann': round(s1 * math.sqrt(12), 3), 'sr_b_ann': round(s2 * math.sqrt(12), 3), 'rho': round(rho, 3), 'z': round(zz, 2) if zz is not None else None,
            'p_two': round(M.p_two(zz), 4) if zz is not None else None, 'months': T}


def by_decade(s, b):
    out = {}
    for d0 in range(1920, 2030, 10):
        ks = [k for k in s if k in b and d0 * 100 <= k < (d0 + 10) * 100]
        if len(ks) >= 24:
            out[f'{d0}s'] = round((M.cagr([s[k] for k in ks]) - M.cagr([b[k] for k in ks])) * 100, 2)
    return out


def exposure_stats(run, a=None, z=None):
    W = {k: v for k, v in run['w'].items() if (a is None or k >= a) and (z is None or k <= z)}
    if not W:
        return None
    v = list(W.values())
    mx = max(v)
    tr = [x for k, x in run['trade'].items() if k in W]
    yrs = len(v) / 12
    return {'avg_w': round(S.mean(v), 3), 'median_w': round(S.median(v), 3), 'max_w': round(mx, 3), 'min_w': round(min(v), 3),
            'share_over1': round(sum(1 for x in v if x > 1 + 1e-12) / len(v), 3),
            'share_at_max': round(sum(1 for x in v if abs(x - mx) < 1e-9) / len(v), 3),
            'share_zero': round(sum(1 for x in v if x == 0) / len(v), 3),
            'turnover_per_year': round(sum(tr) / yrs, 2) if tr else None}


def evaluate(run, b, rf):
    g, n = run['gross'], run['net']
    e = {}
    e['full'] = M.excess_stats(g, b)
    e['train'] = M.excess_stats(g, b, z=M.TRAIN_END)
    e['hold'] = M.excess_stats(g, b, a=M.HOLD_START)
    e['recent'] = M.excess_stats(g, b, a=M.RECENT_START)
    e['post_pub_2017'] = M.excess_stats(g, b, a=POST_PUB)
    e['net_full'] = M.excess_stats(n, b)
    e['net_train'] = M.excess_stats(n, b, z=M.TRAIN_END)
    e['cost_hold'] = M.excess_stats(n, b, a=M.HOLD_START)
    e['net_recent'] = M.excess_stats(n, b, a=M.RECENT_START)
    e['net_post_pub_2017'] = M.excess_stats(n, b, a=POST_PUB)
    if run.get('net05'):
        e['cost_hold_005'] = M.excess_stats(run['net05'], b, a=M.HOLD_START)
    if run.get('net_sp2'):
        e['spread2_hold'] = M.excess_stats(run['net_sp2'], b, a=M.HOLD_START)
        e['spread2_full'] = M.excess_stats(run['net_sp2'], b)
    e['roll20'] = M.rolling(n, b, 20)
    e['roll20_gross'] = M.rolling(g, b, 20)
    e['dca20'] = M.dca(n, b, 20)
    sp = {}
    for nm, (a, z) in {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None), 'recent': (M.RECENT_START, None), 'post_pub_2017': (POST_PUB, None)}.items():
        ks = [k for k in n if k in b]
        sp[nm] = [M.sharpe(n, rf, a, z), M.sharpe({k: b[k] for k in ks}, rf, a, z)]
    e['sharpe'] = sp
    e['sharpe_test'] = {'train': sharpe_test(n, b, rf, z=M.TRAIN_END), 'hold': sharpe_test(n, b, rf, a=M.HOLD_START)}
    e['capm_alpha_net'] = {'full': capm_alpha(n, b, rf), 'train': capm_alpha(n, b, rf, z=M.TRAIN_END), 'hold': capm_alpha(n, b, rf, a=M.HOLD_START)}
    ks = [k for k in n if k in b]
    e['maxdd'] = {'s_monthly': round(M.maxdd(n) * 100, 1), 'b_monthly': round(M.maxdd({k: b[k] for k in ks}) * 100, 1)}
    if run['trade']:
        e['exposure'] = {'full': exposure_stats(run), 'train': exposure_stats(run, z=M.TRAIN_END), 'hold': exposure_stats(run, a=M.HOLD_START)}
    else:
        v = list(run['w'].values())
        e['exposure'] = {'full': {'avg_w': round(S.mean(v), 3), 'max_w': round(max(v), 3)} if v else None}
    e['by_decade_net_cagr_diff'] = by_decade(n, b)
    return e


def positive(st):
    return bool(st and st['ex_ann'] > 0 and st['cagr_diff'] > 0)


# ───────────────────────── 税（報告） ─────────────────────────
def tax_window(mk, run, months):
    """日本の課税口座の近似（月次）。months の最初の月から最後の月まで。戦略と買って持つだけの税引後の年率"""
    ms = [k for k in months if k in run['w']]
    if len(ms) < 24:
        return None
    Wt = 1.0; w0 = run['w'][ms[0]]
    E = w0 * Wt; K = E; B = Wt - E
    carry = []  # (年, 損失)
    realized = 0.0
    bE, bK = 1.0, 1.0

    def settle(year, gain):
        nonlocal carry
        carry = [(y, l) for y, l in carry if year - y <= 3]
        if gain <= 0:
            carry.append((year, -gain)); return 0.0
        g = gain
        new = []
        for y, l in carry:
            use = min(l, g); g -= use
            if l - use > 0:
                new.append((y, l - use))
        carry = new
        return TAX * g

    for i, t in enumerate(ms):
        m, rf = mk.m[t], mk.rf[t]
        E *= 1 + m
        B *= 1 + rf + (SPREAD / 12 if B < 0 else 0)
        Wt = E + B
        bE *= 1 + m
        last = i == len(ms) - 1
        if not last:
            w = run['w'][ms[i + 1]]
            tgt = w * Wt
            Wt -= abs(tgt - E) * COST
            tgt = w * Wt
            if tgt < E:
                sold = E - tgt
                realized += sold * (1 - K / E) if E > 0 else 0.0
                K *= tgt / E if E > 0 else 0.0
            else:
                K += tgt - E
            E = tgt; B = Wt - E
        if t % 100 == 12 or last:
            if last:
                realized += E - K
            tax = settle(t // 100, realized)
            realized = 0.0
            B -= tax; Wt = E + B
    yrs = len(ms) / 12
    b_tax = TAX * max(0.0, bE - bK)
    s_cagr = (Wt) ** (1 / yrs) - 1 if Wt > 0 else -1
    b_cagr = (bE - b_tax) ** (1 / yrs) - 1
    return {'from': ms[0], 'to': ms[-1], 'years': round(yrs, 1), 's_after_tax_cagr': round(s_cagr * 100, 2), 'b_after_tax_cagr': round(b_cagr * 100, 2),
            'diff': round((s_cagr - b_cagr) * 100, 2)}


def tax_report(mk, run):
    ks = sorted(run['w'])
    out = {'hold': tax_window(mk, run, [k for k in ks if k >= M.HOLD_START]), 'full': tax_window(mk, run, ks)}
    rolls = []
    y0 = ks[0] // 100
    for y in range(y0, 2100):
        a, z = y * 100 + 7, (y + 20) * 100 + 6
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < 233:
            continue
        r = tax_window(mk, run, w)
        if r:
            rolls.append((y, r['diff']))
    if rolls:
        v = sorted(d for _, d in rolls)
        out['rolling20'] = {'windows': len(rolls), 'win_rate': round(sum(1 for _, d in rolls if d > 0) / len(rolls), 3), 'median': v[len(v) // 2],
                            'worst': min(rolls, key=lambda x: x[1]), 'best': max(rolls, key=lambda x: x[1])}
    out['note'] = '近似: 倍率を下げる月の売却益に課税（年ごとに通算・損失3年繰越）・最後に全部売る。配当の課税と信用の金利の経費算入は入れない'
    return out


# ───────────────────────── データの用意 ─────────────────────────
class Ctx:
    pass


def load():
    c = Ctx()
    c.sanity = {}
    ffd = M.ff_factors('daily'); ffm = M.ff_factors('monthly')
    D = sorted(d for d in ffd['mkt'] if d in ffd['rf'])
    us_dex = {d: ffd['mktrf'][d] for d in D}
    us_dtot = {d: ffd['mkt'][d] for d in D}
    us_drf = {d: ffd['rf'][d] for d in D}
    c.us = Mk('US', us_dex, us_dtot, us_drf, ffm['mkt'], ffm['rf'])
    c.sanity['us_mkt_cagr_full_monthly_file'] = round(M.cagr(ffm['mkt']) * 100, 2)
    c.sanity['us_mkt_cagr_2007_monthly_file'] = round(M.cagr(M.window(ffm['mkt'], M.HOLD_START)) * 100, 2)
    dm = M.to_monthly(us_dtot)
    ks = sorted(set(dm) & set(ffm['mkt']))
    diffs = [abs(dm[k] - ffm['mkt'][k]) for k in ks]
    c.sanity['us_daily_to_monthly_vs_file'] = {'months': len(ks), 'max_abs_diff_pct': round(max(diffs) * 100, 3), 'mean_abs_diff_pct': round(S.mean(diffs) * 100, 4),
                                               'corr': round(M.corr([dm[k] for k in ks], [ffm['mkt'][k] for k in ks]), 5)}
    c.sanity['us_months'] = [c.us.months[0], c.us.months[-1], len(c.us.months), 'gaps', c.us.gaps]
    log('検算 US', c.sanity)
    # NDX
    ndx_px = {k: v for k, v in yh_daily('^NDX')[0].items() if k <= FR_END}
    qqq = {k: v for k, v in yh_daily('QQQ')[1].items() if k <= FR_END}
    pr, qr, q0 = rets(ndx_px), rets(qqq), min(qqq)
    dd = (1 + NDX_DIV) ** (1 / 252) - 1
    ndx_tot = {}
    for k, v in pr.items():
        if k <= q0:
            ndx_tot[k] = (1 + v) * (1 + dd) - 1
        elif k in qr:
            ndx_tot[k] = qr[k]
    Dn = sorted(k for k in ndx_tot if k in ffd['rf'])
    miss = sum(1 for k in ndx_tot if k not in ffd['rf'])
    ndx_dtot = {k: ndx_tot[k] for k in Dn}
    ndx_drf = {k: ffd['rf'][k] for k in Dn}
    ndx_dex = {k: ndx_tot[k] - ffd['rf'][k] for k in Dn}
    nm = M.to_monthly(ndx_dtot)
    first_month = Dn[0] // 100
    nm.pop(first_month, None)  # 最初の月は途中から（1985-10-02〜）なので月次リターンに使わない（RV には使う）
    c.ndx = Mk('NDX', ndx_dex, ndx_dtot, ndx_drf, nm, ffm['rf'])
    # つなぎ目の検算: 1999-03-11 以降の NDX 価格リターンと QQQ の相関・年率の差（配当と経費の差）
    kk = sorted(k for k in pr if k > q0 and k in qr)
    c.sanity['ndx_splice'] = {'days_not_in_french_rf': miss, 'corr_ndx_price_vs_qqq_daily_after_splice': round(M.corr([pr[k] for k in kk], [qr[k] for k in kk]), 5),
                              'cagr_ndx_price_after_splice': round(M.cagr([pr[k] for k in kk], 252) * 100, 2), 'cagr_qqq_after_splice': round(M.cagr([qr[k] for k in kk], 252) * 100, 2),
                              'splice_day': q0, 'returns_around_splice': {str(k): round(ndx_tot[k] * 100, 3) for k in Dn if 19990305 <= k <= 19990316},
                              'months': [c.ndx.months[0], c.ndx.months[-1], len(c.ndx.months)]}
    log('検算 NDX', c.sanity['ndx_splice'])
    # 地域
    c.REG = {'Europe': 'Europe', 'Japan': 'Japan', 'Asia_Pacific_ex_Japan': 'Asia_Pacific_ex_Japan', 'Developed_ex_US': 'Developed_ex_US', 'North_America': 'North_America'}
    c.COUNTED = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']
    c.reg = {}
    for nmk, fn in c.REG.items():
        dmk, drf = fr_region(fn + '_3_Factors_Daily', 'daily')
        mm, mrf = fr_region(fn + '_3_Factors', 'monthly')
        Dr = sorted(d for d in dmk if d in drf)
        c.reg[nmk] = Mk(nmk, {d: dmk[d] - drf[d] for d in Dr}, {d: dmk[d] for d in Dr}, {d: drf[d] for d in Dr}, mm, mrf)
        c.sanity[f'region_{nmk}'] = [c.reg[nmk].months[0], c.reg[nmk].months[-1], len(c.reg[nmk].months), 'gaps', c.reg[nmk].gaps]
    c.ffm = ffm
    c.ffd = ffd
    # 第3族: HiTec（French 10業種・時価加重）
    ind_d = M.french_series('10_Industry_Portfolios_daily', 'Value Weight', 'daily')
    ind_m = M.french_series('10_Industry_Portfolios', 'Value Weight', 'monthly')
    c.ind10 = {}
    for col in ind_d:
        Dd = sorted(d for d in ind_d[col] if d in ffd['rf'])
        c.ind10[col] = Mk(col, {d: ind_d[col][d] - ffd['rf'][d] for d in Dd}, {d: ind_d[col][d] for d in Dd}, {d: ffd['rf'][d] for d in Dd},
                          ind_m[col], ffm['rf'])
    c.hitec = c.ind10['HiTec']
    c.sanity['hitec'] = [c.hitec.months[0], c.hitec.months[-1], len(c.hitec.months), 'gaps', c.hitec.gaps,
                         'cagr', round(M.cagr(c.hitec.m) * 100, 2), 'cagr_2007', round(M.cagr(M.window(c.hitec.m, M.HOLD_START)) * 100, 2)]
    # 第3族: NASDAQ 総合（価格＋推定配当1%）
    ixp = {k: v for k, v in yh_daily('^IXIC')[0].items() if k <= FR_END}
    ddi = (1 + IXIC_DIV) ** (1 / 252) - 1
    ixr = {k: (1 + v) * (1 + ddi) - 1 for k, v in rets(ixp).items()}
    Di = sorted(k for k in ixr if k in ffd['rf'])
    ixm = M.to_monthly({k: ixr[k] for k in Di})
    ixm.pop(Di[0] // 100, None)
    c.ixic = Mk('IXIC', {k: ixr[k] - ffd['rf'][k] for k in Di}, {k: ixr[k] for k in Di}, {k: ffd['rf'][k] for k in Di}, ixm, ffm['rf'])
    c.sanity['ixic'] = [c.ixic.months[0], c.ixic.months[-1], len(c.ixic.months), 'gaps', c.ixic.gaps, 'days_not_in_french', sum(1 for k in ixr if k not in ffd['rf']),
                        'cagr', round(M.cagr(c.ixic.m) * 100, 2)]
    log('検算 HiTec/IXIC', c.sanity['hitec'], c.sanity['ixic'])
    return c


def ind_breadth(c):
    """報告のみ: A の3規則 × {B1, B1EXP} を French 10業種に、VAR1 × {B1, B1EXP} を49業種に"""
    res = {}
    ind49_d = M.french_series('49_Industry_Portfolios_daily', 'Value Weight', 'daily')
    ind49_m = M.french_series('49_Industry_Portfolios', 'Value Weight', 'monthly')
    ffd, ffm = c.ffd, c.ffm
    c.ind49 = {}
    for col in ind49_d:
        dd = ind49_d[col]; mm = ind49_m.get(col, {})
        if not dd or min(dd) > 19260702 or len(dd) < 26000 or len(mm) < 1190:
            continue  # 1926-07 から欠けの無い業種だけ（事前登録どおり）
        Dd = sorted(d for d in dd if d in ffd['rf'])
        c.ind49[col] = Mk(col, {d: dd[d] - ffd['rf'][d] for d in Dd}, None, None, mm, ffm['rf'])
    for panel, mks, sigs in (('ind10', c.ind10, ('VAR1', 'VOL1', 'DOWN')), ('ind49', c.ind49, ('VAR1',))):
        for sg in sigs:
            for cm in ('train_b1', 'expanding_b1'):
                key = f'{panel}_{sg}_cap1.5_{cm}'
                rows = {}
                for nm, mk in mks.items():
                    run, info = run_rule(mk, sg, 1.5, cm)
                    if run is None:
                        rows[nm] = {'note': info.get('note')}; continue
                    f = M.excess_stats(run['net'], mk.m); h = M.excess_stats(run['net'], mk.m, a=M.HOLD_START)
                    tr = M.excess_stats(run['gross'], mk.m, z=M.TRAIN_END)
                    rows[nm] = {'full_ex': f['ex_ann'], 'full_t': f['t'], 'full_cagr_diff': f['cagr_diff'],
                                'train_ex': tr['ex_ann'] if tr else None, 'train_t': tr['t'] if tr else None,
                                'hold_ex': h['ex_ann'] if h else None, 'hold_t': h['t'] if h else None, 'hold_cagr_diff': h['cagr_diff'] if h else None,
                                'sharpe_full': [M.sharpe(run['net'], mk.rf), M.sharpe({k: mk.m[k] for k in run['net']}, mk.rf)],
                                'sharpe_hold': [M.sharpe(run['net'], mk.rf, a=M.HOLD_START), M.sharpe({k: mk.m[k] for k in run['net']}, mk.rf, a=M.HOLD_START)]}
                ok = {k: v for k, v in rows.items() if 'full_ex' in v}
                cnt = lambda f: sum(1 for v in ok.values() if f(v))
                res[key] = {'n': len(ok), 'full_positive': cnt(lambda v: v['full_ex'] > 0 and v['full_cagr_diff'] > 0),
                            'train_t_ge2': cnt(lambda v: (v['train_t'] or 0) >= 2), 'hold_positive': cnt(lambda v: v['hold_ex'] is not None and v['hold_ex'] > 0 and v['hold_cagr_diff'] > 0),
                            'sharpe_up_full': cnt(lambda v: None not in v['sharpe_full'] and v['sharpe_full'][0] > v['sharpe_full'][1]),
                            'sharpe_up_hold': cnt(lambda v: None not in v['sharpe_hold'] and v['sharpe_hold'][0] > v['sharpe_hold'][1]),
                            'median_full_ex': round(S.median([v['full_ex'] for v in ok.values()]), 2) if ok else None,
                            'median_hold_ex': round(S.median([v['hold_ex'] for v in ok.values() if v['hold_ex'] is not None]), 2) if ok else None,
                            'detail': rows}
                log(f"業種 {key}: n {res[key]['n']} 全期間で正 {res[key]['full_positive']} 訓練 t≥2 {res[key]['train_t_ge2']} 保有で正 {res[key]['hold_positive']} "
                    f"シャープ上 全期間 {res[key]['sharpe_up_full']} 保有 {res[key]['sharpe_up_hold']} 中央 全期間 {res[key]['median_full_ex']} 保有 {res[key]['median_hold_ex']}")
    return res


JKP_C = 'aus aut bel bra can che chl chn col cze deu dnk egy esp fin fra gbr grc hkg hun idn ind irl isr ita jpn kor mex mys nld nor nzl per phl pol prt sgp swe tha tur twn zaf'.split()


def load_jkp(c):
    out = {}
    for cc in JKP_C:
        try:
            rows = M.jkp_rows(cc, 'mkt', 'factor', 'vw', 'daily')
            dex = {}
            for x in rows:
                if x['ret'] in ('', 'NA', 'na'):
                    continue
                d = int(x['date'][:4]) * 10000 + int(x['date'][5:7]) * 100 + int(x['date'][8:10])
                dex[d] = float(x['ret'])
            mex = M.jkp_mkt(cc, 'vw')
            rf = c.ffm['rf']
            mt = {k: v + rf[k] for k, v in mex.items() if k in rf}
            ms = set(k // 100 for k in dex)
            mt = {k: v for k, v in mt.items() if k in ms}
            out[cc] = Mk(cc, dex, None, None, mt, rf)
        except Exception as ex:  # noqa
            log('JKP 取得失敗', cc, ex)
    return out


# ───────────────────────── 戦略の定義 ─────────────────────────
LABELS = {'exploratory': '探索（第1族の事前登録に含めて結果を見る前に固定）',
          'exploratory2': '探索（第2族・第1族の結果を見た後に登録）',
          'exploratory3': '探索（第3族・第2族の結果を見た後に登録）'}
SIG = {'VAR1': ('VAR1', False), 'VOL1': ('VOL1', False), 'VAR6': ('VAR6', False), 'VAR1T': ('VAR1', True),
       'EWMA': ('EWMA', False), 'DOWN': ('DOWN', False), 'VOL1T': ('VOL1', True)}


def specs():
    out = []
    i = 0
    for idx in ('US', 'NDX'):
        for sg in ('VAR1', 'VOL1', 'VAR6', 'VAR1T'):
            for cap in CAPS:
                i += 1
                out.append({'id': f'P{i:02d}_{idx}_{sg}_cap{cap:g}', 'family': 'primary', 'idx': idx, 'sig': sg, 'cap': cap, 'cmode': 'train', 'lag': 0})
    for p in list(out):
        q = dict(p); q['id'] = 'E1_' + p['id'] + '_EXP'; q['family'] = 'exploratory'; q['cmode'] = 'expanding'
        out.append(q)
    for fam, sg in (('E3', 'EWMA'), ('E4', 'DOWN'), ('E6', 'VOL1T')):
        for idx in ('US', 'NDX'):
            for cap in CAPS:
                out.append({'id': f'{fam}_{idx}_{sg}_cap{cap:g}', 'family': 'exploratory', 'idx': idx, 'sig': sg, 'cap': cap, 'cmode': 'train', 'lag': 0})
    for idx in ('US', 'NDX'):
        for cap in CAPS:
            out.append({'id': f'E5_{idx}_VAR1_LAG1_cap{cap:g}', 'family': 'exploratory', 'idx': idx, 'sig': 'VAR1', 'cap': cap, 'cmode': 'train', 'lag': 1})
    # 第2族（prereg2）: c を β=1 で解く
    base = [p for p in out if p['family'] == 'primary']
    j = 0
    for p in base:
        j += 1
        out.append({**p, 'id': f"Q{j:02d}_{p['idx']}_{p['sig']}_cap{p['cap']:g}_B1", 'family': 'exploratory2', 'cmode': 'train_b1'})
    for p in base:
        j += 1
        out.append({**p, 'id': f"Q{j:02d}_{p['idx']}_{p['sig']}_cap{p['cap']:g}_B1EXP", 'family': 'exploratory2', 'cmode': 'expanding_b1'})
    for idx in ('US', 'NDX'):
        for sg in ('DOWN', 'VOL1T'):
            for cap in CAPS:
                j += 1
                out.append({'id': f'Q{j:02d}_{idx}_{sg}_cap{cap:g}_B1', 'family': 'exploratory2', 'idx': idx, 'sig': sg, 'cap': cap, 'cmode': 'train_b1', 'lag': 0})
    # 第3族（prereg3）
    h = 0
    for idx in ('HiTec', 'IXIC'):
        for sg in ('VAR1', 'VOL1', 'DOWN'):
            for cm in ('train_b1', 'expanding_b1'):
                h += 1
                out.append({'id': f"H{h:02d}_{idx}_{sg}_cap1.5_{'B1' if cm == 'train_b1' else 'B1EXP'}", 'family': 'exploratory3', 'idx': idx, 'sig': sg, 'cap': 1.5, 'cmode': cm, 'lag': 0})
    for sg in ('VAR1', 'VOL1', 'DOWN'):
        h += 1
        out.append({'id': f'H{h:02d}_NDX_{sg}_cap1.5_B1_LAG1', 'family': 'exploratory3', 'idx': 'NDX', 'sig': sg, 'cap': 1.5, 'cmode': 'train_b1', 'lag': 1})
    for idx in ('US', 'NDX'):
        for cap in CAPS:
            for cm in ('train_b1', 'expanding_b1'):
                h += 1
                out.append({'id': f"H{h:02d}_{idx}_ENS_cap{cap:g}_{'B1' if cm == 'train_b1' else 'B1EXP'}", 'family': 'exploratory3', 'idx': idx, 'sig': 'ENS', 'cap': cap, 'cmode': cm, 'lag': 0})
    return out


def weights_of(mk, sg, cap, cmode):
    """規則の倍率 {t0: w}（決めた月末がキー）"""
    kind, trend = SIG[sg]
    X = mk.X(kind)
    if cmode in ('train', 'train_b1'):
        c, _ = (solve_c if cmode == 'train' else solve_c_beta)(mk, X, cap, trend, end=mk.train_end)
        if c is None:
            return None
        cb = None
    else:
        cb = c_expanding(mk, X, cap, trend, solver=solve_c if cmode == 'expanding' else solve_c_beta)
        c = None
    out = {}
    for t0 in mk.months:
        x = X.get(t0); on = mk.trend.get(t0) if trend else 1
        cc = c if cb is None else cb.get(t0)
        if x is None or on is None or cc is None:
            continue
        out[t0] = weight(x, cc, cap, on)
    return out


def run_ens(mk, cap, cmode):
    parts = [weights_of(mk, sg, cap, cmode) for sg in ('VAR1', 'VOL1', 'DOWN')]
    if any(p is None for p in parts):
        return None, {'note': '訓練期間が短すぎる'}
    ks = set(parts[0]) & set(parts[1]) & set(parts[2])
    wb = {k: sum(p[k] for p in parts) / 3 for k in ks}
    return run_monthly(mk, None, cap, None, False, w_by=wb), {'ens': 'VAR1・VOL1・DOWN の倍率の平均（各自 β=1 の c）', 'cmode': cmode}


def run_rule(mk, sg, cap, cmode, lag=0):
    if sg == 'ENS':
        return run_ens(mk, cap, cmode)
    kind, trend = SIG[sg]
    X = mk.X(kind)
    info = {}
    if cmode in ('train', 'train_b1'):
        c, ci = (solve_c if cmode == 'train' else solve_c_beta)(mk, X, cap, trend, end=mk.train_end)
        if c is None:
            return None, {'note': '訓練期間が短すぎる'}
        info['c'] = c if c != math.inf else 'inf'; info['c_solve'] = ci
        if lag:
            run = run_daily_lag(mk, X, cap, c, trend)
        else:
            run = run_monthly(mk, X, cap, c, trend)
    elif cmode in ('expanding', 'expanding_b1'):
        cb = c_expanding(mk, X, cap, trend, solver=solve_c if cmode == 'expanding' else solve_c_beta)
        if not cb:
            return None, {'note': '60か月そろわない'}
        vals = sorted(set(v for v in cb.values() if v != math.inf))
        info['c_expanding'] = {'first_month': min(cb), 'n_years': len(cb) // 12, 'min': min(vals) if vals else None, 'max': max(vals) if vals else None,
                               'n_inf_years': sum(1 for v in cb.values() if v == math.inf) // 12}
        run = run_monthly(mk, X, cap, None, trend, c_by=cb)
    else:
        raise KeyError(cmode)
    return run, info


def region_repl(c, sp):
    key = (sp['sig'], sp['cap'], sp['cmode'], sp['lag'])
    if not hasattr(c, 'repl_cache'):
        c.repl_cache = {}
    if key not in c.repl_cache:
        c.repl_cache[key] = _region_repl(c, sp)
    return c.repl_cache[key]


def _region_repl(c, sp):
    det = {}
    for nm, mk in c.reg.items():
        run, info = run_rule(mk, sp['sig'], sp['cap'], sp['cmode'], sp['lag'])
        if run is None:
            det[nm] = {'note': info.get('note')}; continue
        b = run.get('bench') or mk.m
        full_n = M.excess_stats(run['net'], b)
        det[nm] = {'net_full': full_n, 'net_hold': M.excess_stats(run['net'], b, a=M.HOLD_START), 'gross_full': M.excess_stats(run['gross'], b),
                   'sharpe_full': [M.sharpe(run['net'], mk.rf), M.sharpe({k: b[k] for k in run['net'] if k in b}, mk.rf)],
                   'sharpe_hold': [M.sharpe(run['net'], mk.rf, a=M.HOLD_START), M.sharpe({k: b[k] for k in run['net'] if k in b}, mk.rf, a=M.HOLD_START)],
                   'positive': positive(full_n), 'positive_hold': positive(M.excess_stats(run['net'], b, a=M.HOLD_START)),
                   'c': info.get('c'), 'avg_w': round(S.mean(run['w'].values()), 3) if run['w'] else None}
    pos = sum(1 for nm in c.COUNTED if det.get(nm, {}).get('positive'))
    posh = sum(1 for nm in c.COUNTED if det.get(nm, {}).get('positive_hold'))
    return {'regions': len(c.COUNTED), 'positive': pos, 'positive_hold_report': posh, 'counted': c.COUNTED,
            'rule_positive': 'ex_ann>0 かつ cagr_diff>0（費用後・地域の全期間）', 'detail': det}


def run_one(c, sp):
    mk = {'US': c.us, 'NDX': c.ndx, 'HiTec': getattr(c, 'hitec', None), 'IXIC': getattr(c, 'ixic', None)}[sp['idx']]
    run, info = run_rule(mk, sp['sig'], sp['cap'], sp['cmode'], sp['lag'])
    if run is None:
        log('実行不能', sp['id'], info); return None
    b = run.get('bench') or mk.m
    rf = mk.rf
    e = evaluate(run, b, rf)
    ent = {'id': sp['id'], 'family': sp['family'], 'graded': True, 'rule': {k: sp[k] for k in ('idx', 'sig', 'cap', 'cmode', 'lag')}, **info,
           'window': [min(run['net']), max(run['net'])], 'gaps': run['gaps'], **e}
    ent['repl'] = region_repl(c, sp)
    if sp['family'] == 'primary' or (sp['family'] == 'exploratory2' and sp['cmode'] == 'train_b1' and sp['sig'] in ('VAR1', 'VOL1', 'VAR6', 'VAR1T')):
        ent['tax_japan'] = tax_report(mk, run)
    if sp['family'] != 'primary':
        ent['label'] = LABELS[sp['family']]
    h, t = e['hold'], e['train']
    log(f"{sp['id']:34s} 訓練 {t['ex_ann'] if t else None:>6} t{t['t'] if t else None} 保有 {h['ex_ann'] if h else None:>6} t{h['t'] if h else None} 幾何差 {h['cagr_diff'] if h else None} "
        f"費用後保有 {e['cost_hold']['ex_ann'] if e['cost_hold'] else None} 20年勝率 {e['roll20']['win_rate'] if e['roll20'] else None} "
        f"Sharpe訓練 {e['sharpe']['train']} 保有 {e['sharpe']['hold']} 地域 {ent['repl']['positive']}/{ent['repl']['regions']} 平均倍率 {(e['exposure'].get('full') or {}).get('avg_w')}")
    return ent


def report_only(c):
    out = []
    for idx, mk in (('US', c.us), ('NDX', c.ndx)):
        run, info = run_rule(mk, 'VAR1', math.inf, 'train')
        e = evaluate(run, mk.m, mk.rf)
        out.append({'id': f'R0{1 if idx == "US" else 2}_{idx}_VAR1_nocap', 'family': 'report', 'graded': False, 'grade': '報告のみ（判定しない）',
                    'rule': {'idx': idx, 'sig': 'VAR1', 'cap': 'なし', 'cmode': 'train'}, **info, 'window': [min(run['net']), max(run['net'])], **e})
        log(f"{out[-1]['id']:34s} 保有 {e['hold']['ex_ann'] if e['hold'] else None} 訓練 {e['train']['ex_ann'] if e['train'] else None} 最大倍率 {e['exposure']['full']['max_w']}")
    # R03 論文の再現（全期間 c・1926-08〜2015-12・借入の上乗せ・費用なし）
    mk = c.us
    X = mk.X('VAR1')
    P = pairs(mk, X, False, end=201512)
    xs = np.array([p[2] for p in P]); ex = np.array([mk.m[p[1]] - mk.rf[p[1]] for p in P])
    inv = 1 / xs
    cc = ex.std(ddof=1) / (inv * ex).std(ddof=1)
    s = {p[1]: cc / p[2] * (mk.m[p[1]] - mk.rf[p[1]]) + mk.rf[p[1]] for p in P}
    a = capm_alpha(s, mk.m, mk.rf)
    rep = {'id': 'R03_MM_reproduction', 'family': 'report', 'graded': False, 'grade': '報告のみ（判定しない）',
           'desc': 'US・VAR1・上限なし・c を 1926-08〜2015-12 の全体で決める（論文と同じ後知恵）・借入の上乗せと費用なし', 'c_full_sample': cc,
           'capm': a, 'sharpe_managed': M.sharpe(s, mk.rf), 'sharpe_market': M.sharpe({k: mk.m[k] for k in s}, mk.rf),
           'max_w': round(float((cc * inv).max()), 2), 'paper_table1_mkt_from_memory': 'α≈4.86%/年・β≈0.61・R²≈0.37（記憶による・原本と照合していない）'}
    log('R03 論文の再現', rep['capm'], rep['sharpe_managed'], rep['sharpe_market'], rep['max_w'])
    out.append(rep)
    return out


def jkp_breadth(c, cmode='train'):
    if not hasattr(c, 'jkp'):
        c.jkp = load_jkp(c)
    J = c.jkp
    res = {}
    for sg in ('VAR1', 'VOL1', 'VAR6', 'VAR1T'):
        for cap in CAPS:
            key = f'{sg}_cap{cap:g}'
            rows = {}
            for cc, mk in J.items():
                kind, trend = SIG[sg]
                X = mk.X(kind)
                ntrain = len([p for p in pairs(mk, X, trend, end=M.TRAIN_END)])
                if ntrain < 120:
                    rows[cc] = {'note': f'訓練の月が {ntrain} < 120'}; continue
                run, info = run_rule(mk, sg, cap, cmode)
                if run is None:
                    rows[cc] = {'note': info.get('note')}; continue
                f = M.excess_stats(run['net'], mk.m); h = M.excess_stats(run['net'], mk.m, a=M.HOLD_START)
                shf = [M.sharpe(run['net'], mk.rf), M.sharpe({k: mk.m[k] for k in run['net']}, mk.rf)]
                shh = [M.sharpe(run['net'], mk.rf, a=M.HOLD_START), M.sharpe({k: mk.m[k] for k in run['net']}, mk.rf, a=M.HOLD_START)]
                rows[cc] = {'full_ex': f['ex_ann'] if f else None, 'full_cagr_diff': f['cagr_diff'] if f else None, 'full_t': f['t'] if f else None,
                            'hold_ex': h['ex_ann'] if h else None, 'hold_cagr_diff': h['cagr_diff'] if h else None, 'hold_t': h['t'] if h else None,
                            'sharpe_full': shf, 'sharpe_hold': shh, 'from': f['from'] if f else None, 'avg_w': round(S.mean(run['w'].values()), 3)}
            ok = {k: v for k, v in rows.items() if 'full_ex' in v and v['full_ex'] is not None}
            pf = sum(1 for v in ok.values() if v['full_ex'] > 0 and v['full_cagr_diff'] > 0)
            ph = sum(1 for v in ok.values() if v['hold_ex'] is not None and v['hold_ex'] > 0 and v['hold_cagr_diff'] > 0)
            sf = sum(1 for v in ok.values() if None not in v['sharpe_full'] and v['sharpe_full'][0] > v['sharpe_full'][1])
            shh_ = sum(1 for v in ok.values() if None not in v['sharpe_hold'] and v['sharpe_hold'][0] > v['sharpe_hold'][1])
            med = lambda xs: round(S.median(xs), 2) if xs else None
            res[key] = {'countries': len(ok), 'positive_full': pf, 'positive_hold': ph, 'sharpe_up_full': sf, 'sharpe_up_hold': shh_,
                        'median_full_ex': med([v['full_ex'] for v in ok.values()]), 'median_hold_ex': med([v['hold_ex'] for v in ok.values() if v['hold_ex'] is not None]),
                        'detail': rows}
            log(f'JKP {cmode} {key}: 国 {len(ok)} 全期間で正 {pf} 保有で正 {ph} シャープ上 全期間 {sf} 保有 {shh_} 中央 全期間 {res[key]["median_full_ex"]} 保有 {res[key]["median_hold_ex"]}')
    return res


def main():
    check = '--check' in sys.argv
    res = {'angle': 'volmanaged', 'prereg': PRE_NAMES}
    shas = {}
    for p in PRE_NAMES:
        try:
            shas[p] = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', os.path.join('out', p)], cwd=M.BASE).decode().strip() or None
        except Exception:
            shas[p] = None
    res['prereg_commit'] = shas
    log('事前登録の commit', shas)
    c = load()
    if check:
        print(json.dumps(c.sanity, ensure_ascii=False, indent=1)[:4000])
        return
    tested = []
    for sp in specs():
        ent = run_one(c, sp)
        if ent is not None:
            tested.append(ent)
    # 検算: 添字（倍率は前月の RV から決まる）と c の一致
    mk = c.us; X = mk.X('VAR1')
    cc, ci = solve_c(mk, X, 1.5, False, end=M.TRAIN_END)
    run = run_monthly(mk, X, 1.5, cc, False)
    bad = sum(1 for t1, w in run['w'].items() if abs(w - min(1.5, cc / X[prv(t1)])) > 1e-12)
    c.sanity['lookahead_index_check_P01'] = {'months': len(run['w']), 'mismatch': bad, 'rule': 'w[t1] == min(1.5, c/RV1[t1 の前月])'}
    c.sanity['c_solve_P01'] = ci
    tw = {k: run['net'][k] for k in list(run['net'])[:400]}
    c.sanity['excess_stats_fast_equals_mw_common'] = _ORIG_EXCESS_STATS(tw, mk.m) == _excess_stats_fast(tw, mk.m)
    # Holm と判定
    prim = {x['id']: x['hold']['p'] for x in tested if x['family'] == 'primary' and x['hold']}
    allg = {x['id']: x['hold']['p'] for x in tested if x['graded'] and x['hold']}
    hp, ha = M.holm(prim), M.holm(allg)
    for x in tested:
        if x['family'] == 'primary':
            x['holm_family'] = f'primary({len(prim)})'; x['holm_p'] = hp.get(x['id'])
        else:
            x['holm_family'] = f'all_graded({len(allg)})'; x['holm_p'] = ha.get(x['id'])
        sp = {'train': tuple(x['sharpe']['train']), 'hold': tuple(x['sharpe']['hold'])}
        g, cr = M.grade(x['full'], x['train'], x['hold'], x['roll20'], cost_hold=x['cost_hold'], repl=x.get('repl'),
                        family_holm_p=x['holm_p'], sharpe_pair=sp, leveraged_or_timing=True)
        x['grade'] = g; x['criteria'] = cr
    tested += report_only(c)
    res['jkp_breadth_report'] = jkp_breadth(c)
    res['jkp_breadth_b1_report'] = jkp_breadth(c, 'train_b1')
    res['industry_breadth_report'] = ind_breadth(c)
    res['sanity'] = c.sanity
    res['n_tested'] = len(tested)
    res['n_graded'] = len(allg)
    res['grades'] = {g: [x['id'] for x in tested if x.get('grade') == g] for g in ('S', 'A', 'B', 'C')}
    res['tested'] = tested
    res['log'] = LOG
    p = M.save(OUT_NAME, res)
    log('書いた', p, '格付け', {g: len(v) for g, v in res['grades'].items()})


if __name__ == '__main__':
    main()
