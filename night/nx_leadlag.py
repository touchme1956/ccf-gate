#!/usr/bin/env python3
"""night/nx_leadlag.py — nx 角度 leadlag（業種どうしの先行・遅行）の**測る道具**（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…探し続けて」。
ただし線を下げて勝ちを作らない。事前登録 out/nx_leadlag_prereg.json（測る前に固定・この道具はそれを書き換えない）と
全体の線 out/nx_prereg.json（C1〜C8・格付け S/A/B/C）をそのまま当てる。統計と格付けは night/nx_common.py。

何を測るか
  『業種自身の過去』ではなく『他の業種の過去』で業種を選ぶ規則が、買いだけで French Mkt（≒S&P500）に勝つか。
    主の族（格付け・Holm は5本の中で）:
      P1 顧客の業種の前月（Menzly-Ozbas 2010）／P2 仕入れ先の業種の前月／P3 両方の平均
      P4 全30業種の前月から LASSO で選んだ予言（Rapach-Strauss-Tu-Zhou 2019・AICc・OLS post-LASSO・拡大窓）
      P5 同じ手法を49業種で
    探索の族21本（E1〜E21・格付けはするが『探索』）、対照・偽の規則・後知恵・古い表、米国外7か国（C5）、実在のセクターETF。
  重みは night/nx_leadlag_data.py の out/_nx_cache/nx_leadlag_io.json（BEA の産業連関表 → French 49業種）。
  最初に sha256(tables) が事前登録の値と一致するかを確かめ、違えば止まる。

実装の約束（事前登録どおり）
  - t 月末に分かる値（t 月の業種リターン・t 月の行の社数×平均時価・t 月末に公表済みの表）だけで t+1 月を持つ。
  - LASSO は自前の座標降下法（covariance update・前の λ の解から温めて始める・max|Δβ|<1e-8 か 10,000 周）。
    同じ更新式・同じ順番・同じ停止則を C で書いて ctypes で呼ぶ（numpy だけだと 49業種で1か月30秒かかると計測したため）。
    起動時に numpy の参照実装と合成データで一致すること、λ→0 で OLS、λ≥λ_max で全て0 を確かめる（リターンのデータでは確かめない）。
  - 費用は片道100%あたり 0.10%（感度 0.30%）。E19・E20 は 0.30%（感度 0.50%）。回転 = ½Σ|新しい重み − 流した前月の重み|（最初の月は1）。

使い方: python3 night/nx_leadlag.py            → out/nx_leadlag.json
        （LASSO の予言は out/_nx_cache/nx_leadlag_fc_*.npz にためる。入力と手順の指紋が同じなら読み直すだけ）
"""
import sys, os, json, math, hashlib, time, ctypes, subprocess, datetime
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402

PRE = os.path.join(N.BASE, 'out', 'nx_leadlag_prereg.json')
IO = os.path.join(N.CACHE, 'nx_leadlag_io.json')
OUTNAME = 'nx_leadlag.json'
LOG = os.path.join(N.CACHE, 'nx_leadlag_run.log')
COST, COST_SENS = 0.001, 0.003
COST_HOU, COST_HOU_SENS = 0.003, 0.005
PP_MO, PP_RSTZ, PP_2007PAPERS = 201101, 202001, 200801
COUNTRIES = ['jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che']
ETF = {'XLE': '10', 'XLB': '15', 'XLI': '20', 'XLY': '25', 'XLP': '30', 'XLV': '35', 'XLF': '40', 'XLK': '45', 'XLC': '50', 'XLU': '55', 'XLRE': '60'}
T0 = time.time()


def log(*a):
    s = f'[{time.time() - T0:7.1f}s] ' + ' '.join(str(x) for x in a)
    print(s, flush=True)
    with open(LOG, 'a') as h:
        h.write(s + '\n')


def nxt(ym):
    y, m = divmod(ym, 100)
    return (y + 1) * 100 + 1 if m == 12 else ym + 1


def prv(ym):
    y, m = divmod(ym, 100)
    return (y - 1) * 100 + 12 if m == 1 else ym - 1


def mrange(a, z):
    out, x = [], a
    while x <= z:
        out.append(x); x = nxt(x)
    return out


def K5(n):
    return int(math.floor(n / 5 + 0.5))


def K10(n):
    return int(math.floor(n / 10 + 0.5))


def K5min1(n):
    return max(1, K5(n))


# ───────────────────────── LASSO（座標降下）─────────────────────────
C_SRC = r'''
#include <math.h>
/* covariance-update coordinate descent, one response column at a time, warm start along the lambda grid.
   G p*p row-major (symmetric), C p*m, lams nlam*m, mask p*m (0/1) or NULL (masked coefficient stays 0).
   objective (1/2n)|y-Xb|^2 + lam[alpha|b|_1 + (1-alpha)/2 |b|^2] with standardized X (G = X'X/n), C = X'y/n.
   stop: max|delta b| < tol within a sweep, or maxit sweeps. coef_out nlam*p*m, sweeps_out nlam*m */
void cd_path(int p, int m, int nlam, const double *G, const double *C, const double *lams,
             double alpha, const unsigned char *mask, double tol, int maxit,
             double *coef_out, int *sweeps_out) {
  double b[512], g[512];
  for (int col = 0; col < m; col++) {
    for (int j = 0; j < p; j++) { b[j] = 0.0; g[j] = C[j*m+col]; }
    for (int k = 0; k < nlam; k++) {
      double lam = lams[k*m+col], thr = lam*alpha, ridge = lam*(1.0-alpha);
      int it;
      for (it = 0; it < maxit; it++) {
        double maxd = 0.0;
        for (int j = 0; j < p; j++) {
          if (mask && !mask[j*m+col]) continue;
          double gjj = G[j*p+j];
          double rj = g[j] + gjj*b[j];
          double a = fabs(rj) - thr;
          double nb = a > 0 ? (rj > 0 ? a : -a)/(gjj+ridge) : 0.0;
          double d = nb - b[j];
          if (d != 0.0) {
            const double *Gj = G + (long)j*p;
            for (int i = 0; i < p; i++) g[i] -= Gj[i]*d;
            b[j] = nb;
            double ad = fabs(d); if (ad > maxd) maxd = ad;
          }
        }
        if (maxd < tol) { it++; break; }
      }
      sweeps_out[k*m+col] = it;
      for (int j = 0; j < p; j++) coef_out[((long)k*p + j)*m + col] = b[j];
    }
  }
}
'''
_LIB = None


def lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    src = os.path.join(N.CACHE, 'nx_leadlag_cd.c')
    flags = ['-O3', '-march=native', '-ffp-contract=off']   # FMA を使わない＝-O2 のスカラーと同じ丸め（合成データでビット一致を確かめた）
    so = os.path.join(N.CACHE, 'nx_leadlag_cd_' + hashlib.sha1((C_SRC + ' '.join(flags)).encode()).hexdigest()[:10] + '.so')
    if not os.path.exists(so):
        open(src, 'w').write(C_SRC)
        subprocess.check_call(['gcc', *flags, '-shared', '-fPIC', '-o', so, src])
    L = ctypes.CDLL(so)
    dp = np.ctypeslib.ndpointer(dtype=np.float64, flags='C_CONTIGUOUS')
    ip = np.ctypeslib.ndpointer(dtype=np.int32, flags='C_CONTIGUOUS')
    L.cd_path.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, dp, dp, dp, ctypes.c_double, ctypes.c_void_p,
                          ctypes.c_double, ctypes.c_int, dp, ip]
    L.cd_path.restype = None
    _LIB = L
    return L


def cd_path(G, C, lams, alpha=1.0, mask=None, tol=1e-8, maxit=10000):
    G = np.ascontiguousarray(G, dtype=np.float64)
    C = np.ascontiguousarray(C, dtype=np.float64)
    lams = np.ascontiguousarray(lams, dtype=np.float64)
    p, m = C.shape
    nlam = lams.shape[0]
    coef = np.zeros((nlam, p, m))
    sw = np.zeros((nlam, m), dtype=np.int32)
    mk = None
    if mask is not None:
        mk = np.ascontiguousarray(mask, dtype=np.uint8)
    lib().cd_path(p, m, nlam, G, C, lams, float(alpha), mk.ctypes.data if mk is not None else None, tol, maxit, coef, sw)
    return coef, sw


def cd_path_numpy(G, C, lams, alpha=1.0, mask=None, tol=1e-8, maxit=10000):
    """参照実装（numpy・1列ずつ・同じ更新式）。起動時の一致検査だけに使う"""
    p, m = C.shape
    nlam = lams.shape[0]
    coef = np.zeros((nlam, p, m))
    for col in range(m):
        b = np.zeros(p)
        for k in range(nlam):
            lam = lams[k, col]
            for _ in range(maxit):
                maxd = 0.0
                for j in range(p):
                    if mask is not None and not mask[j, col]:
                        continue
                    rj = C[j, col] - G[j] @ b + G[j, j] * b[j]
                    nb = np.sign(rj) * max(abs(rj) - lam * alpha, 0.0) / (G[j, j] + lam * (1 - alpha))
                    maxd = max(maxd, abs(nb - b[j])); b[j] = nb
                if maxd < tol:
                    break
            coef[k, :, col] = b
    return coef


def lam_grid(C, alpha=1.0, mask=None, nlam=100, ratio=1e-4):
    A = np.abs(C if mask is None else C * mask)
    lmax = A.max(0) / alpha
    return lmax[None, :] * ratio ** (np.arange(nlam) / (nlam - 1))[:, None], lmax


def lasso_sanity():
    """合成データだけで確かめる（リターンのデータでは確かめない）"""
    rng = np.random.default_rng(12345)
    n, p, m = 240, 12, 4
    f = rng.normal(0, 1, (n, 1))
    X = f @ rng.uniform(0.3, 1.2, (1, p)) + rng.normal(0, 1, (n, p))
    B0 = np.zeros((p, m)); B0[:3] = rng.normal(0, 0.5, (3, m))
    Y = X @ B0 + rng.normal(0, 1, (n, m))
    mu, sd = X.mean(0), X.std(0)
    Xs = (X - mu) / sd
    Yc = Y - Y.mean(0)
    G = Xs.T @ Xs / n; C = Xs.T @ Yc / n
    out = {}
    lams, lmax = lam_grid(C)
    cf, sw = cd_path(G, C, lams)
    cf_np = cd_path_numpy(G, C, lams)
    out['c_vs_numpy_max_abs_diff'] = float(np.abs(cf - cf_np).max())
    out['c_vs_numpy_active_set_mismatch'] = int(((cf != 0) != (cf_np != 0)).sum())
    z, _ = cd_path(G, C, np.vstack([lmax, 2 * lmax]))
    out['zero_at_lambda_max'] = bool(np.all(z == 0))
    ols = np.linalg.solve(G, C)
    t0, _ = cd_path(G, C, np.full((1, m), 1e-13), tol=1e-13, maxit=100000)
    out['lambda_to_0_vs_ols_max_abs_diff'] = float(np.abs(t0[0] - ols).max())
    t1, _ = cd_path(G, C, np.full((1, m), 1e-13))
    out['lambda_to_0_vs_ols_max_abs_diff_tol1e-8'] = float(np.abs(t1[0] - ols).max())
    le, lmaxe = lam_grid(C, alpha=0.5)
    ze, _ = cd_path(G, C, np.vstack([lmaxe]), alpha=0.5)
    out['enet_zero_at_lambda_max'] = bool(np.all(ze == 0))
    ce, _ = cd_path(G, C, le, alpha=0.5)
    ce_np = cd_path_numpy(G, C, le, alpha=0.5)
    out['enet_c_vs_numpy_max_abs_diff'] = float(np.abs(ce - ce_np).max())
    mask = np.ones((p, m), dtype=np.uint8); mask[0, 0] = 0; mask[1, 1] = 0
    lm, _ = lam_grid(C, mask=mask)
    cm, _ = cd_path(G, C, lm, mask=mask)
    cm_np = cd_path_numpy(G, C, lm, mask=mask)
    out['mask_c_vs_numpy_max_abs_diff'] = float(np.abs(cm - cm_np).max())
    out['mask_respected'] = bool(np.all(cm[:, 0, 0] == 0) and np.all(cm[:, 1, 1] == 0))
    ok = (out['c_vs_numpy_max_abs_diff'] < 1e-10 and out['c_vs_numpy_active_set_mismatch'] == 0 and out['zero_at_lambda_max']
          and out['lambda_to_0_vs_ols_max_abs_diff'] < 1e-8 and out['enet_zero_at_lambda_max'] and out['enet_c_vs_numpy_max_abs_diff'] < 1e-10
          and out['mask_c_vs_numpy_max_abs_diff'] < 1e-10 and out['mask_respected'])
    out['ok'] = bool(ok)
    return out


def fit_forecast(X, Y, x_t, method, mask=None):
    """1か月ぶんの推定と予言。X: n×p（説明変数＝前月の超過）、Y: n×m（被説明＝当月の超過）、x_t: p（t 月の超過）。
    method: 'lasso'（AICc・OLS post-LASSO）/'enet'（α=0.5・AICc は enet の当てはめの RSS）/'ols'/'combo'。
    返り: 予言 (m,)、選ばれた説明変数の数 (m,)、最大の周回数、10,000 周に達した数"""
    n, p = X.shape
    m = Y.shape[1]
    mu, sd = X.mean(0), X.std(0)
    assert np.all(sd > 0)
    Xs = (X - mu) / sd
    xs_t = (x_t - mu) / sd
    ybar = Y.mean(0)
    Yc = Y - ybar
    G = Xs.T @ Xs / n
    Cc = Xs.T @ Yc / n
    yy = (Yc ** 2).mean(0)
    if method == 'ols':
        b = np.linalg.lstsq(G, Cc, rcond=None)[0]
        return ybar + xs_t @ b, np.full(m, p), 0, 0
    if method == 'combo':
        return ybar + (xs_t[:, None] * Cc / np.diag(G)[:, None]).mean(0), np.full(m, p), 0, 0
    alpha = 0.5 if method == 'enet' else 1.0
    lams, _ = lam_grid(Cc, alpha=alpha, mask=mask)
    coef, sw = cd_path(G, Cc, lams, alpha=alpha, mask=mask)
    act = coef != 0
    fc = np.empty(m); nsel = np.empty(m, dtype=int)
    inv_cache = {}
    for col in range(m):
        best = None
        seen = {}
        for k in range(lams.shape[0]):
            A = act[k, :, col]
            if method == 'lasso':
                key = A.tobytes()
                if key not in seen:
                    idx = np.flatnonzero(A)
                    if len(idx) == 0:
                        rss, f = yy[col], ybar[col]
                    else:
                        if key not in inv_cache:
                            try:
                                inv_cache[key] = np.linalg.inv(G[np.ix_(idx, idx)])
                            except np.linalg.LinAlgError:
                                inv_cache[key] = np.linalg.pinv(G[np.ix_(idx, idx)])
                        b = inv_cache[key] @ Cc[idx, col]
                        rss = yy[col] - b @ Cc[idx, col]
                        f = ybar[col] + b @ xs_t[idx]
                    kk = len(idx) + 1
                    aic = n * math.log(max(rss, 1e-300)) + 2 * kk + 2 * kk * (kk + 1) / (n - kk - 1)
                    seen[key] = (aic, f, len(idx))
                val = seen[key]
            else:
                idx = np.flatnonzero(A)
                b = coef[k, idx, col]
                rss = yy[col] - 2 * b @ Cc[idx, col] + b @ G[np.ix_(idx, idx)] @ b
                kk = len(idx) + 1
                aic = n * math.log(max(rss, 1e-300)) + 2 * kk + 2 * kk * (kk + 1) / (n - kk - 1)
                val = (aic, ybar[col] + b @ xs_t[idx], len(idx))
            if best is None or val[0] < best[0]:   # 同点なら大きい λ（先に見た方）を残す
                best = val
        fc[col], nsel[col] = best[1], best[2]
    return fc, nsel, int(sw.max()), int((sw >= 10000).sum())


def rstz_forecasts(name, months, Xex, Yex, s_first, t_first, t_last, method, mask=None, rolling=None, fp_extra=''):
    """完全な（欠けの無い）パネルの拡大窓（rolling なら直近 rolling 組）の予言。
    months: 月の並び、Xex: T×p（説明変数の元＝超過）、Yex: T×m。窓の月 s は s_first〜t（x は s−1）。予言は t_first〜t_last の信号の月 t → t+1 を持つ。
    返り: {t: 予言 (m,)}、診断"""
    idx = {mm: i for i, mm in enumerate(months)}
    si, t0i, t1i = idx[s_first], idx[t_first], idx[t_last]
    assert t0i - si + 1 >= 120, '初期窓が120組に満たない'
    fp = hashlib.sha1((name + method + str(rolling) + str(s_first) + str(t_first) + str(t_last) + fp_extra + C_SRC).encode()
                      + Xex[si - 1:t1i + 1].tobytes() + Yex[si:t1i + 1].tobytes()
                      + (mask.tobytes() if mask is not None else b'')).hexdigest()[:16]
    cp = os.path.join(N.CACHE, f'nx_leadlag_fc_{name}_{fp}.npz')
    if os.path.exists(cp):
        z = np.load(cp)
        F = {int(t): z['F'][i] for i, t in enumerate(z['t'])}
        return F, json.loads(str(z['diag']))
    assert not np.isnan(Xex[si - 1:t1i + 1]).any() and not np.isnan(Yex[si:t1i + 1]).any()
    F, nsel_all, maxsw, nonconv = {}, [], 0, 0
    tt = time.time()
    for ti in range(t0i, t1i + 1):
        a = si if rolling is None else max(si, ti - rolling + 1)
        s = np.arange(a, ti + 1)
        assert s.max() == ti and s.min() >= si   # 先読みの検査: 窓は t まで
        X, Y, x_t = Xex[s - 1], Yex[s], Xex[ti]
        fc, nsel, sw, nc = fit_forecast(X, Y, x_t, method, mask)
        F[months[ti]] = fc
        nsel_all.append(nsel); maxsw = max(maxsw, sw); nonconv += nc
        if (ti - t0i) % 60 == 0:
            log(f'  {name} {months[ti]} ({ti - t0i + 1}/{t1i - t0i + 1}) 経過 {time.time() - tt:.0f}s 平均の選択数 {np.mean(nsel):.1f}')
    ns = np.array(nsel_all)
    diag = {'months': len(F), 'first_signal': months[t0i], 'last_signal': months[t1i],
            'mean_selected_regressors': round(float(ns.mean()), 2), 'median_selected': float(np.median(ns)),
            'share_forecast_equal_to_mean(no regressor)': round(float((ns == 0).mean()), 3),
            'max_sweeps_one_lambda': maxsw, 'lambda_fits_hit_10000_sweeps': nonconv, 'seconds': round(time.time() - tt, 1)}
    np.savez(cp, t=np.array(sorted(F)), F=np.array([F[t] for t in sorted(F)]), diag=json.dumps(diag))
    return F, diag


def rstz_forecasts_missing(months, R, s_first_i, method='lasso', min_obs=120):
    """欠けのあるパネル（米国外の GICS・実在の ETF）の拡大窓の予言。
    説明変数 = 窓の始まり（x の最初の月＝s_first−1）から t まで欠けの無い列。被説明 = t にリターンがあり、
    窓の中で y がそろう月が min_obs 以上の列（欠けた月は飛ばす）。同じ月の組の列はまとめて推定する。
    返り: {t: 予言（欠けた列は NaN）}"""
    T, n = R.shape
    F = {}
    for ti in range(s_first_i + min_obs - 1, T - 1):
        J = [j for j in range(n) if not np.isnan(R[s_first_i - 1:ti + 1, j]).any()]
        if len(J) < 2:
            continue
        s_all = np.arange(s_first_i, ti + 1)
        groups = {}
        for i in range(n):
            if np.isnan(R[ti, i]):
                continue
            ok = s_all[~np.isnan(R[s_all, i])]
            if len(ok) < min_obs:
                continue
            groups.setdefault(ok.tobytes(), (ok, []))[1].append(i)
        if not groups:
            continue
        fc = np.full(n, np.nan)
        for ok, cols in groups.values():
            assert ok.max() <= ti
            X, Y, x_t = R[np.ix_(ok - 1, J)], R[np.ix_(ok, cols)], R[ti, J]
            f, _, _, _ = fit_forecast(X, Y, x_t, method)
            fc[cols] = f
        F[months[ti]] = fc
    return F


# ───────────────────────── データ ─────────────────────────
class Panel:
    def __init__(self, months, names, R, CAP=None, EW=None):
        self.months, self.names, self.R, self.CAP, self.EW = list(months), list(names), R, CAP, EW
        self.idx = {m: i for i, m in enumerate(self.months)}
        self.n = len(self.names)


def french_panel(name):
    T = N.french_tables(name)
    vw, ew = T['Average Value Weighted Returns -- Monthly'], T['Average Equal Weighted Returns -- Monthly']
    nf, sz = T['Number of Firms in Portfolios'], T['Average Firm Size']
    cols = [c.strip() for c in vw['cols']]
    months = sorted(vw['data'])
    assert months == mrange(months[0], months[-1])
    for t in (ew, nf, sz):
        assert sorted(t['data']) == months

    def arr(tab, scale):
        A = np.full((len(months), len(cols)), np.nan)
        for i, mm in enumerate(months):
            for j, v in enumerate(tab['data'][mm]):
                if v is not None:
                    A[i, j] = v * scale
        return A
    NF, SZ = arr(nf, 1.0), arr(sz, 1.0)
    CAP = NF * SZ
    return Panel(months, cols, arr(vw, 0.01), CAP, arr(ew, 0.01))


def dict_to_panel(d, names, months=None):
    """{名前: {ym: r}} → Panel（欠けは NaN）"""
    if months is None:
        ks = sorted(set().union(*[set(v) for v in d.values()]))
        months = mrange(ks[0], ks[-1])
    R = np.full((len(months), len(names)), np.nan)
    ix = {m: i for i, m in enumerate(months)}
    for j, nm in enumerate(names):
        for k, v in d.get(nm, {}).items():
            if k in ix:
                R[ix[k], j] = v
    return Panel(months, names, R)


def jkp_gics(country):
    import zipfile, io, csv
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{country}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = N.get(url, name=f'jkp_industry_{country}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        g = str(int(float(x['gics'])))
        out.setdefault(g, {})[N._ym(x['date'])] = float(x['ret'])
    return out


# ───────────────────────── 規則の実行 ─────────────────────────
def run_rule(P, sig_fn, t_list, K_fn, weighting, hold_R=None, overlap=1, missing_hold=0.0, record=False):
    """t_list の各月 t（連続）に sig_fn(t) で順位を付け、上位 K を weighting（'vw' か 'ew'）で t+1 月に持つ。
    overlap>1 なら直近 overlap 回の形成の重みを等分に重ねる。返り: リターン {h}, 回転 {h}, 付帯情報"""
    hold_R = P.R if hold_R is None else hold_R
    for a, b in zip(t_list, t_list[1:]):
        assert b == nxt(a), '信号の月が連続していない'
    rets, tos, nuniv, Ws = {}, {}, {}, {}
    forms, prev = [], None
    for t in t_list:
        ti = P.idx[t]
        if ti + 1 >= len(P.months):
            break
        h = P.months[ti + 1]
        sig = sig_fn(t)
        valid = np.flatnonzero(np.isfinite(sig))
        assert len(valid) > 0, f'{t}: 順位に入る業種が無い'
        K = K_fn(len(valid))
        assert K >= 1
        sel = sorted(valid.tolist(), key=lambda i: (-sig[i], i))[:K]
        w = np.zeros(P.n)
        if weighting == 'vw':
            c = P.CAP[ti, sel]
            assert np.all(np.isfinite(c)) and np.all(c > 0), f'{t}: 時価が無い業種を選んだ'
            w[sel] = c / c.sum()
        else:
            w[sel] = 1.0 / K
        assert abs(w.sum() - 1) < 1e-9 and int((w > 0).sum()) == K
        forms.append(w); forms = forms[-overlap:]
        wc = np.mean(forms, axis=0)
        rh = hold_R[ti + 1]
        rh0 = np.where(np.isfinite(rh), rh, missing_hold)
        r = float(wc @ rh0)
        to = 1.0 if prev is None else 0.5 * float(np.abs(wc - prev).sum())
        assert -1e-12 <= to <= 1 + 1e-9
        prev = wc * (1 + rh0) / (1 + r)
        rets[h], tos[h], nuniv[h] = r, to, len(valid)
        if record:
            Ws[h] = wc
    meta = {'hold_from': min(rets), 'hold_to': max(rets), 'months': len(rets),
            'universe_n_min': min(nuniv.values()), 'universe_n_max': max(nuniv.values())}
    return rets, tos, meta, Ws


def net_of(r, to, c):
    return {k: r[k] - to[k] * c for k in r}


def partner_signal(W, r):
    """W: 行ごとの相手の重み（自分は0）、r: t 月のリターン（欠けは NaN）→ 相手の加重平均（その月にリターンのある相手だけで割り直す）。
    自分に t 月のリターンが無い業種・相手が1つも無い業種は NaN"""
    mask = np.isfinite(r)
    rr = np.where(mask, r, 0.0)
    den = W @ mask.astype(float)
    num = W @ rr
    sig = np.full(len(r), np.nan)
    ok = (den > 0) & mask
    sig[ok] = num[ok] / den[ok]
    return sig


def compound(P, t, J):
    """t−J+1〜t の J か月の複利（どれかが欠けたら NaN）"""
    ti = P.idx[t]
    if ti - J + 1 < 0:
        return np.full(P.n, np.nan)
    blk = P.R[ti - J + 1:ti + 1]
    out = np.prod(1 + blk, axis=0) - 1
    out[np.isnan(blk).any(axis=0)] = np.nan
    return out


def table_at(t, sched):
    ok = [s for s in sched if s['signal'] <= t]
    if not ok:
        return None
    s = ok[-1]
    assert s['signal'] <= t   # 先読みの検査
    return s['table']


# ───────────────────────── 評価 ─────────────────────────
def nw_ols(y, X, lag=12):
    y = np.asarray(y); X = np.column_stack([np.ones(len(y)), np.asarray(X)])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        Gm = Xe[L:].T @ Xe[:-L]
        S += w * (Gm + Gm.T)
    V = XtXi @ S @ XtXi
    se = np.sqrt(np.diag(V))
    return b, se


def evaluate(name, gross, to, bench, rf, post_pub=None, cost=COST, cost_sens=COST_SENS, extra_spans=None):
    net, net_s = net_of(gross, to, cost), net_of(gross, to, cost_sens)
    es = N.excess_stats
    st = {'full': es(gross, bench), 'train': es(gross, bench, z=N.TRAIN_END), 'hold': es(gross, bench, a=N.HOLD_START),
          'recent_2013_07': es(gross, bench, a=N.RECENT_START),
          'post_publication': es(gross, bench, a=post_pub) if post_pub else None,
          '1970_1989': es(gross, bench, a=197001, z=198912), '1990_2006': es(gross, bench, a=199001, z=200612)}
    if extra_spans:
        for k, (a, z) in extra_spans.items():
            st[k] = es(gross, bench, a=a, z=z)
    ks = sorted(gross)
    tov = [to[k] for k in ks]
    cst = {'cost_per_oneway': cost, 'cost_sensitivity': cost_sens,
           'oneway_turnover_per_year': round(float(np.mean(tov)) * 12, 3),
           'net_main': {'full': es(net, bench), 'train': es(net, bench, z=N.TRAIN_END), 'hold': es(net, bench, a=N.HOLD_START)},
           'net_sensitivity': {'full': es(net_s, bench), 'train': es(net_s, bench, z=N.TRAIN_END), 'hold': es(net_s, bench, a=N.HOLD_START)}}
    bw = {k: bench[k] for k in ks if k in bench}
    out = {'span': [ks[0], ks[-1]], 'stats_gross': st, 'cost': cst,
           'roll20_net': N.rolling(net, bench), 'roll20_gross': N.rolling(gross, bench),
           'dca20_net_ratio': N.dca(net, bench, 20), 'dca20_gross_ratio': N.dca(gross, bench, 20),
           'maxdd': {'rule_gross': round(N.maxdd(gross) * 100, 1), 'rule_net': round(N.maxdd(net) * 100, 1), 'bench_same_span': round(N.maxdd(bw) * 100, 1)},
           'sharpe': {'train': [N.sharpe(gross, rf, z=N.TRAIN_END), N.sharpe(bench, rf, a=ks[0], z=N.TRAIN_END)],
                      'hold': [N.sharpe(gross, rf, a=N.HOLD_START), N.sharpe(bench, rf, a=N.HOLD_START, z=ks[-1])],
                      'train_net': N.sharpe(net, rf, z=N.TRAIN_END), 'hold_net': N.sharpe(net, rf, a=N.HOLD_START),
                      'note': '[規則, 相手]。C8 は E21（時期選び）だけ必須。ほかは報告のみ'}}
    return out, net


def grade_entry(e, holm_p, repl=None, timing=False):
    st = e['stats_gross']
    sp = {'train': tuple(e['sharpe']['train']), 'hold': tuple(e['sharpe']['hold'])} if timing else None
    g, c = N.grade(st['full'], st['train'], st['hold'], e['roll20_net'], e['cost']['net_main']['hold'], repl, holm_p, sp, timing)
    e['criteria'] = c
    e['grade'] = g
    e['holm_p_in_family'] = holm_p
    return g


def pct_rank(x, arr):
    arr = np.asarray(arr)
    return round(float((arr < x).mean() + 0.5 * (arr == x).mean()), 3)


# ───────────────────────── 本体 ─────────────────────────
def main():
    open(LOG, 'w').close()
    pre = json.load(open(PRE))
    exp_sha = pre['tools']['io_tables_sha256'][:64]
    io = json.load(open(IO))
    got = hashlib.sha256(json.dumps(io['tables'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if got != exp_sha:
        raise SystemExit(f'止まる: 重み表の sha256 が事前登録と違う（事前登録 {exp_sha} / 手元 {got}）')
    log('重み表の sha256 は事前登録と一致', got)
    res = {'angle': 'nx_leadlag', 'prereg': 'out/nx_leadlag_prereg.json',
           'prereg_file_sha256': hashlib.sha256(open(PRE, 'rb').read()).hexdigest(),
           'io_tables_sha256': {'expected_in_prereg': exp_sha, 'computed': got, 'match': True},
           'criteria': 'criteria_long_history（nx_common.grade・C1〜C8・S/A/B/C）。事前登録 criteria.which のとおり',
           'benchmark': 'French Mkt（Mkt-RF＋RF・総リターン）。C5 は各国の JKP 市場 vw（超過どうし）。実在の ETF は SPY',
           'tested': [], 'deviations_from_prereg': [], 'sanity': {}}
    dev = res['deviations_from_prereg']
    dev.append({'what': 'LASSO の座標降下の内側のループを C で書き ctypes で呼んだ（numpy だけの実装ではない）',
                'why': 'numpy だけでは49業種×49説明変数×100λで1か月あたり約30秒（合成データで計測）＝P5 だけで約5時間。同じ更新式（covariance update）・同じ座標の順番・同じ温め始め・同じ停止則（max|Δβ|<1e-8 か 10,000 周）。起動時に numpy の参照実装と合成データで一致（最大差・有効集合の不一致の数を sanity に記録）',
                'affects_grade': False})
    dev[-1]['why'] += '。コンパイルは -O3 -march=native -ffp-contract=off（FMA を使わず -O2 のスカラーと合成データでビット一致を確かめた）'
    dev.append({'what': 'LASSO は業種（列）ごとに独立に解き、停止則も業種ごと（事前登録の「各業種 i ごとに回帰」のとおり）。λ の格子は列ごとの λ_max から',
                'why': '事前登録の定義そのもの（記録のため）', 'affects_grade': False})
    dev.append({'what': 'E12（elastic net）の λ_max は max|X\'y|/(nα)（glmnet の約束＝λ_max で係数がすべて0）。格子は同じ100点・λ_max×1e-4 まで',
                'why': '事前登録は E12 の λ の格子を書いていない。P5 の格子の定義（λ_max で全て0）を elastic net に移すとこの形になる', 'affects_grade': False})
    dev.append({'what': 'E4（K=3 の重なり）は、直近3回の形成の重み（各形成は形成時の時価の重み）を毎月1/3ずつ足した重みで持つ（各形成の持ち物を月の中で流さない）',
                'why': '事前登録は「直近3か月の形成の持ち物を1/3ずつ重ねて持つ」とだけ書いている。Jegadeesh-Titman の1/3ずつの月次の等分と同じ', 'affects_grade': False})
    dev.append({'what': 'C5 の P4・P5（各国 GICS の LASSO）と実在の ETF の R2 の欠け: 説明変数＝窓の最初の月（x）から t まで欠けの無いセクター、被説明＝t にリターンがあり窓の中で y がそろう月が120以上のセクター（欠けた月は飛ばす）。同じ月の組のセクターはまとめて推定',
                'why': '事前登録は「欠けたセクターは信号にも順位にも入れない」とだけ書いている。欠けのある系列を LASSO に入れる最も近い形。結果として 不動産（2016-10〜）と deu のエネルギー（2007-08〜2013-01）は順位に入らない',
                'affects_grade': 'C5 の P4_P5 の単位（7か国）に影響しうる。P4・P5 の格付けは C5 を通じてだけ影響'})
    dev.append({'what': 'E21 の C8 は費用前のシャープ（規則 対 Mkt・訓練と保有）で判定し、費用後のシャープも併記',
                'why': '事前登録は C8 に使う系列を書いていない。C1〜C3・C7 と同じ費用前にそろえた（費用は C6 が見る）', 'affects_grade': 'E21 だけ（探索）'})
    dev.append({'what': 'E19・E20 の回転は業種の段だけで数える（業種の中の EW の毎月の等分への戻しの売買は数えない）',
                'why': 'French の EW ポートフォリオの中身の回転は公開データに無い。費用 0.30% の判定はこの過小な回転に掛かる', 'affects_grade': 'E19・E20 の C6（費用が過小に出る向き）'})
    dev.append({'what': '公表後の報告の起点（格付けに使わない）: 探索の MO 系 2011-01・RSTZ 系（E12〜E18）2020-01・Hou／Hong-Torous-Valkanov（E19〜E21）2008-01',
                'why': '事前登録は P1〜P5 の起点だけ書いている', 'affects_grade': False})

    # ── LASSO の自前実装の検査（合成データだけ）
    sc = lasso_sanity()
    res['sanity']['lasso_synthetic'] = sc
    log('LASSO の合成データ検査', sc)
    if not sc['ok']:
        raise SystemExit('止まる: LASSO の自前実装の検査に落ちた')

    # ── データ
    ff = N.ff_factors()
    mkt, rf, mktrf = ff['mkt'], ff['rf'], ff['mktrf']
    P49 = french_panel('49_Industry_Portfolios')
    P30 = french_panel('30_Industry_Portfolios')
    assert P49.names == io['industries'], 'French 49 の列の並びが重み表と違う'
    assert P49.months[-1] == 202608 and P30.months[-1] == 202608
    rf_arr = np.array([rf[m] for m in P49.months])
    log('French 49/30 業種', P49.months[0], P49.months[-1])
    sched, sched_early = sorted(io['schedule'], key=lambda s: s['signal']), sorted(io['schedule_early_exploratory'], key=lambda s: s['signal'])
    sched_early_full = sched_early + sched
    names = P49.names
    nI = len(names)
    ix = {nm: i for i, nm in enumerate(names)}

    def mat(dct, labels):
        M = np.zeros((len(labels), len(labels)))
        li = {nm: i for i, nm in enumerate(labels)}
        for a, row in dct.items():
            for b, v in row.items():
                if a != b:
                    M[li[a], li[b]] = v
        return M
    TB = {}
    for y, t in io['tables'].items():
        Cw, Sw = mat(t['customer_w'], names), mat(t['supplier_w'], names)

        def second(Wm):
            W2 = Wm + Wm @ Wm
            np.fill_diagonal(W2, 0.0)
            rs = W2.sum(1, keepdims=True)
            return np.divide(W2, rs, out=np.zeros_like(W2), where=rs > 0)
        TB[y] = {'C': Cw, 'S': Sw, 'Cm': mat(t['customer_w_modal'], names), 'Sm': mat(t['supplier_w_modal'], names),
                 'C2': second(Cw), 'S2': second(Sw),
                 'GC': mat(t['gics_customer_w'], io['gics11']), 'GS': mat(t['gics_supplier_w'], io['gics11'])}

    # ── 表の使用の記録（先読みの検査）
    usage = {}
    for label, sc_, a in (('main', sched, 197001), ('early_E10', sched_early_full, 195201)):
        u = {}
        for t in mrange(a, 202607):
            y = table_at(t, sc_)
            assert y is not None
            u.setdefault(y, [t, t, 0])
            u[y][1] = t; u[y][2] += 1
        usage[label] = {y: {'first_signal': v[0], 'last_signal': v[1], 'months': v[2]} for y, v in u.items()}
    res['sanity']['table_in_force'] = usage
    res['sanity']['lookahead_assert'] = '各月の信号で使う表は schedule の signal ≤ t の最新（table_at の assert）。LASSO の窓の最後は t（rstz_forecasts の assert）'

    t_mo = mrange(197001, 202607)

    def mo_sig(kind, sched_=sched, key_c='C', key_s='S', J=1, fixed=None, perm=None):
        def f(t):
            y = fixed or table_at(t, sched_)
            r_self = P49.R[P49.idx[t]]
            r_p = r_self if J == 1 else compound(P49, t, J)
            Cw, Sw = TB[y][key_c], TB[y][key_s]
            if perm is not None:
                Cw, Sw = Cw[np.ix_(perm, perm)], Sw[np.ix_(perm, perm)]
            mask_self = np.isfinite(r_self)
            if kind in ('cus', 'comp'):
                cus = partner_signal(Cw, r_p)
                cus[~mask_self] = np.nan
            if kind in ('sup', 'comp'):
                sup = partner_signal(Sw, r_p)
                sup[~mask_self] = np.nan
            if kind == 'cus':
                return cus
            if kind == 'sup':
                return sup
            return (cus + sup) / 2
        return f

    rules = {}   # name → dict(gross, to, meta, family, post_pub, cost, cost_sens, spec)

    def add(name, family, spec, out, post_pub, cost=COST, cost_sens=COST_SENS, bench=None):
        r, to, meta, W = out
        rules[name] = {'gross': r, 'to': to, 'meta': meta, 'family': family, 'spec': spec, 'post_pub': post_pub,
                       'cost': cost, 'cost_sens': cost_sens, 'W': W}
        log(f'{name}: {meta["hold_from"]}〜{meta["hold_to"]}（{meta["months"]}か月）')

    # ── 主の族 P1〜P3（Menzly-Ozbas）
    add('P1_MO_customer_vw', 'primary', '顧客の業種の前月（CUS）の上位 K=round(N/5) を時価加重', run_rule(P49, mo_sig('cus'), t_mo, K5, 'vw', record=True), PP_MO)
    add('P2_MO_supplier_vw', 'primary', '仕入れ先の業種の前月（SUP）の上位 K を時価加重', run_rule(P49, mo_sig('sup'), t_mo, K5, 'vw', record=True), PP_MO)
    add('P3_MO_composite_vw', 'primary', '(CUS+SUP)/2 の上位 K を時価加重', run_rule(P49, mo_sig('comp'), t_mo, K5, 'vw', record=True), PP_MO)

    # ── LASSO の予言（P4・P5 ほか）
    def ex_panel(P):
        rfa = np.array([rf[m] for m in P.months])
        return P.R - rfa[:, None]
    X30, X49 = ex_panel(P30), ex_panel(P49)
    fcd = {}
    log('P4 の予言（FF30・拡大窓 1960-01〜）')
    F4, fcd['P4'] = rstz_forecasts('P4', P30.months, X30, X30, 196001, 196912, 202607, 'lasso')
    log('P5 の予言（FF49・拡大窓 1969-08〜）')
    F5, fcd['P5'] = rstz_forecasts('P5', P49.months, X49, X49, 196908, 197907, 202607, 'lasso')

    def fsig(F):
        return lambda t: F[t]
    add('P4_RSTZ_lasso_ff30_vw', 'primary', 'FF30 の全30業種の前月の超過で LASSO（AICc・post-LASSO OLS・拡大窓）→ 予言の上位 K=6 を時価加重',
        run_rule(P30, fsig(F4), mrange(196912, 202607), K5, 'vw', record=True), PP_RSTZ)
    add('P5_RSTZ_lasso_ff49_vw', 'primary', 'FF49 で同じ手法 → 上位 K=10 を時価加重', run_rule(P49, fsig(F5), mrange(197907, 202607), K5, 'vw', record=True), PP_RSTZ)

    # ── 探索の族
    add('E1_MO_customer_ew', 'exploratory', 'P1 を業種の等分で', run_rule(P49, mo_sig('cus'), t_mo, K5, 'ew'), PP_MO)
    add('E2_MO_supplier_ew', 'exploratory', 'P2 を等分で', run_rule(P49, mo_sig('sup'), t_mo, K5, 'ew'), PP_MO)
    add('E3_MO_composite_ew', 'exploratory', 'P3 を等分で', run_rule(P49, mo_sig('comp'), t_mo, K5, 'ew'), PP_MO)
    add('E4_MO_composite_vw_K3', 'exploratory', 'P3 の形成を直近3回ぶん1/3ずつ重ねる（形成時の時価の重みを毎月1/3ずつ）', run_rule(P49, mo_sig('comp'), t_mo, K5, 'vw', overlap=3), PP_MO)
    add('E5_MO_composite_vw_J3', 'exploratory', '相手の業種の t−2〜t の3か月の複利で COMP', run_rule(P49, mo_sig('comp', J=3), t_mo, K5, 'vw'), PP_MO)
    add('E6_MO_composite_vw_J12', 'exploratory', '相手の業種の t−11〜t の12か月の複利で COMP', run_rule(P49, mo_sig('comp', J=12), t_mo, K5, 'vw'), PP_MO)
    add('E7_MO_composite_vw_modal', 'exploratory', '部門を最大の割合の French 業種へ丸ごと寄せた重みで P3', run_rule(P49, mo_sig('comp', key_c='Cm', key_s='Sm'), t_mo, K5, 'vw'), PP_MO)
    add('E8_MO_composite_vw_2nd', 'exploratory', '直接＋2段目のつながり（対角を除き行を割り直した W+W·W）で P3', run_rule(P49, mo_sig('comp', key_c='C2', key_s='S2'), t_mo, K5, 'vw'), PP_MO)

    comp = mo_sig('comp')

    def ortho(t):
        s = comp(t)
        r = P49.R[P49.idx[t]]
        ok = np.isfinite(s) & np.isfinite(r)
        out = np.full(nI, np.nan)
        A = np.column_stack([np.ones(ok.sum()), r[ok]])
        b = np.linalg.lstsq(A, s[ok], rcond=None)[0]
        out[ok] = s[ok] - A @ b
        return out
    add('E9_MO_composite_vw_ortho', 'exploratory', '毎月、業種の横断で COMP を [1, 自分の前月] に回帰した残差で順位', run_rule(P49, ortho, t_mo, K5, 'vw'), PP_MO)
    add('E10_MO_composite_vw_early', 'exploratory', '1947・1958 の85部門表で 1952-02 から持つ早い延長（その後は主の schedule）',
        run_rule(P49, mo_sig('comp', sched_=sched_early_full), mrange(195201, 202607), K5, 'vw'), PP_MO)
    add('E11_MO_composite_vw_K5', 'exploratory', 'K=round(N/10)（49業種で5）', run_rule(P49, comp, t_mo, K10, 'vw'), PP_MO)

    log('E12 の予言（elastic net α=0.5）')
    F12, fcd['E12'] = rstz_forecasts('E12', P49.months, X49, X49, 196908, 197907, 202607, 'enet')
    add('E12_RSTZ_enet_ff49_vw', 'exploratory', 'P5 の LASSO を elastic net（α=0.5）に', run_rule(P49, fsig(F12), mrange(197907, 202607), K5, 'vw'), PP_RSTZ)
    log('E13 の予言（自分の前月を除く）')
    own_mask = (1 - np.eye(nI)).astype(np.uint8)
    F13, fcd['E13'] = rstz_forecasts('E13', P49.months, X49, X49, 196908, 197907, 202607, 'lasso', mask=own_mask)
    add('E13_RSTZ_lasso_ff49_vw_others', 'exploratory', 'P5 から自分の前月を説明変数から除く', run_rule(P49, fsig(F13), mrange(197907, 202607), K5, 'vw'), PP_RSTZ)
    F14, fcd['E14'] = rstz_forecasts('E14', P49.months, X49, X49, 196908, 197907, 202607, 'combo')
    add('E14_RSTZ_combo_ff49_vw', 'exploratory', '49本の単回帰の予言の単純平均（予言の組み合わせ）', run_rule(P49, fsig(F14), mrange(197907, 202607), K5, 'vw'), PP_RSTZ)
    F15, fcd['E15'] = rstz_forecasts('E15', P49.months, X49, X49, 196908, 197907, 202607, 'ols')
    add('E15_RSTZ_ols_ff49_vw', 'exploratory', '49本すべての OLS（罰なし）', run_rule(P49, fsig(F15), mrange(197907, 202607), K5, 'vw'), PP_RSTZ)
    add('E16_RSTZ_lasso_ff30_ew', 'exploratory', 'P4 を等分で', run_rule(P30, fsig(F4), mrange(196912, 202607), K5, 'ew'), PP_RSTZ)
    add('E17_RSTZ_lasso_ff49_ew', 'exploratory', 'P5 を等分で', run_rule(P49, fsig(F5), mrange(197907, 202607), K5, 'ew'), PP_RSTZ)
    log('E18 の予言（直近120組の転がる窓）')
    F18, fcd['E18'] = rstz_forecasts('E18', P49.months, X49, X49, 196908, 197907, 202607, 'lasso', rolling=120)
    add('E18_RSTZ_lasso_ff49_vw_roll120', 'exploratory', 'P5 を直近120組の転がる窓で', run_rule(P49, fsig(F18), mrange(197907, 202607), K5, 'vw'), PP_RSTZ)

    # E19・E20（Hou 2007）
    t_hou = mrange(192607, 202607)

    def hou(kind):
        def f(t):
            ti = P49.idx[t]
            v, e = P49.R[ti], P49.EW[ti]
            s = v.copy() if kind == 'big' else v - e
            s[~(np.isfinite(v) & np.isfinite(e))] = np.nan
            return s
        return f
    add('E19_HOU_big2small_ew', 'exploratory', '業種の VW の前月で順位 → 上位 K 業種の EW リターンを等分', run_rule(P49, hou('big'), t_hou, K5, 'ew', hold_R=P49.EW), PP_2007PAPERS, COST_HOU, COST_HOU_SENS)
    add('E20_HOU_gap_ew', 'exploratory', 'VW−EW の前月の差で順位 → 上位 K 業種の EW を等分', run_rule(P49, hou('gap'), t_hou, K5, 'ew', hold_R=P49.EW), PP_2007PAPERS, COST_HOU, COST_HOU_SENS)

    # E21（Hong-Torous-Valkanov・時期選び）
    log('E21 の予言（市場の超過・49業種＋市場の前月）')
    mk_ex = np.array([mktrf[m] for m in P49.months])
    X21 = np.column_stack([X49, mk_ex])
    F21, fcd['E21'] = rstz_forecasts('E21', P49.months, X21, mk_ex[:, None], 196908, 197907, 202607, 'lasso')
    r21, to21, prev = {}, {}, None
    for t in mrange(197907, 202607):
        h = nxt(t)
        pos = 'mkt' if F21[t][0] > 0 else 'rf'
        r21[h] = mkt[h] if pos == 'mkt' else rf[h]
        to21[h] = 1.0 if prev is None else (1.0 if pos != prev else 0.0)
        prev = pos
    share_in = round(sum(1 for t in mrange(197907, 202607) if F21[t][0] > 0) / len(mrange(197907, 202607)), 3)
    rules['E21_HTV_timing'] = {'gross': r21, 'to': to21, 'meta': {'hold_from': 197908, 'hold_to': 202608, 'months': len(r21), 'share_months_in_market': share_in},
                               'family': 'exploratory', 'spec': '市場の翌月の超過を49業種＋市場の前月の超過で LASSO 予言し、>0 なら Mkt、≦0 なら RF', 'post_pub': PP_2007PAPERS,
                               'cost': COST, 'cost_sens': COST_SENS, 'W': {}, 'timing': True}
    res['lasso_diagnostics'] = fcd

    # ── 対照（報告のみ）
    own = lambda t: P49.R[P49.idx[t]].copy()  # noqa: E731
    ctrl = run_rule(P49, own, t_mo, K5, 'vw')
    ew49 = {}
    for t in t_mo:
        h = nxt(t)
        v = P49.R[P49.idx[h]]
        ew49[h] = float(np.nanmean(v))
    hind = run_rule(P49, mo_sig('comp', fixed='2017'), t_mo, K5, 'vw')
    stale = run_rule(P49, mo_sig('comp', fixed='1963'), t_mo, K5, 'vw')

    # ── 評価と格付け
    entries = {}
    for name, R_ in rules.items():
        e, net = evaluate(name, R_['gross'], R_['to'], mkt, rf, R_['post_pub'], R_['cost'], R_['cost_sens'],
                          extra_spans={'1926_1969': (192601, 196912)} if name.startswith(('E19', 'E20')) else ({'1952_1969': (195201, 196912)} if name.startswith('E10') else None))
        e.update({'name': name, 'family': R_['family'], 'spec': R_['spec'], 'meta': R_['meta']})
        if name.startswith(('E19', 'E20')):
            ewavg = {}
            for h in R_['gross']:
                v = P49.EW[P49.idx[h]]
                ewavg[h] = float(np.nanmean(v))
            e['vs_ew_industry_average_report'] = {'spec': '49業種の EW リターンの等分平均（小型への傾きだけの勝ちを見分ける・報告のみ）',
                                                  'full': N.excess_stats(R_['gross'], ewavg), 'train': N.excess_stats(R_['gross'], ewavg, z=N.TRAIN_END),
                                                  'hold': N.excess_stats(R_['gross'], ewavg, a=N.HOLD_START)}
        entries[name] = e
        R_['net'] = net
    fam_p = {f: N.holm({n: e['stats_gross']['hold']['p'] for n, e in entries.items() if e['family'] == f}) for f in ('primary', 'exploratory')}

    # ── C5（米国外7か国）
    log('C5: 米国外7か国')
    g11 = io['gics11']
    c5 = {'unit': '米国外7か国の JKP GICS 11セクター（超過）対 その国の JKP 市場 vw（超過）', 'countries': {}}
    for c in COUNTRIES:
        d = jkp_gics(c)
        Pc = dict_to_panel(d, g11)
        mk = N.jkp_mkt(c, 'vw')
        cc = {'sectors_present': {g: [min(d[g]), max(d[g]), len(d[g])] for g in sorted(d)}, 'span': [Pc.months[0], Pc.months[-1]]}
        tl = [t for t in Pc.months if t < Pc.months[-1]]
        for kind, lab in (('cus', 'P1'), ('sup', 'P2'), ('comp', 'P3')):
            def gsig(t, kind=kind):
                y = table_at(t, sched)
                r = Pc.R[Pc.idx[t]]
                cus = partner_signal(TB[y]['GC'], r); sup = partner_signal(TB[y]['GS'], r)
                return cus if kind == 'cus' else sup if kind == 'sup' else (cus + sup) / 2
            r, to, meta, _ = run_rule(Pc, gsig, tl, K5min1, 'ew', missing_hold=0.0)
            cc[lab] = {'excess': N.excess_stats(r, mk), 'excess_net010': N.excess_stats(net_of(r, to, COST), mk),
                       'oneway_turnover_per_year': round(float(np.mean(list(to.values()))) * 12, 3), 'meta': meta}
        s0 = Pc.idx[199908]
        Fc = rstz_forecasts_missing(Pc.months, Pc.R, s0)
        tl2 = sorted(Fc)
        r, to, meta, _ = run_rule(Pc, lambda t: Fc[t], tl2, K5min1, 'ew', missing_hold=0.0)
        cc['P4_P5'] = {'excess': N.excess_stats(r, mk), 'excess_net010': N.excess_stats(net_of(r, to, COST), mk),
                       'oneway_turnover_per_year': round(float(np.mean(list(to.values()))) * 12, 3), 'meta': meta}
        for lab in ('P1', 'P2', 'P3', 'P4_P5'):
            ex = cc[lab]['excess']
            cc[lab]['positive'] = bool(ex and ex['cagr_diff'] > 0)
        c5['countries'][c] = cc
        log(f'  C5 {c}: ' + ' '.join(f"{lab} {cc[lab]['excess']['cagr_diff'] if cc[lab]['excess'] else None}" for lab in ('P1', 'P2', 'P3', 'P4_P5')))
    repl = {}
    for lab in ('P1', 'P2', 'P3', 'P4_P5'):
        pos = sum(1 for c in COUNTRIES if c5['countries'][c][lab]['positive'])
        repl[lab] = {'regions': len(COUNTRIES), 'positive': pos}
    c5['summary'] = {k: {**v, 'pass(>=5/7)': v['positive'] >= 5} for k, v in repl.items()}
    res['c5'] = c5
    repl_of = {'P1_MO_customer_vw': repl['P1'], 'P2_MO_supplier_vw': repl['P2'], 'P3_MO_composite_vw': repl['P3'],
               'P4_RSTZ_lasso_ff30_vw': repl['P4_P5'], 'P5_RSTZ_lasso_ff49_vw': repl['P4_P5']}

    for name, e in entries.items():
        grade_entry(e, fam_p[e['family']].get(name), repl_of.get(name) if e['family'] == 'primary' else None,
                    timing=bool(rules[name].get('timing')))
        if e['family'] == 'exploratory':
            e['grade_label'] = f"{e['grade']}（探索）"

    # ── 対照・偽の規則・後知恵・古い表（報告のみ）
    log('対照・偽の規則')
    controls = {}
    ce, _ = evaluate('CTRL_own1m_vw', ctrl[0], ctrl[1], mkt, rf)
    controls['CTRL_own1m_vw'] = {**ce, 'spec': '自分の前月のリターンの上位 K を時価加重（1か月の業種の勢い）', 'meta': ctrl[2]}
    controls['CTRL_ew49'] = {'spec': '49業種（VW リターン）の等分平均・毎月等分に戻す', 'stats_gross': {
        'full': N.excess_stats(ew49, mkt), 'train': N.excess_stats(ew49, mkt, z=N.TRAIN_END), 'hold': N.excess_stats(ew49, mkt, a=N.HOLD_START)}}
    for nm, o in (('HINDSIGHT_fixed2017', hind), ('STALE_fixed1963', stale)):
        ce, _ = evaluate(nm, o[0], o[1], mkt, rf, PP_MO)
        controls[nm] = {**ce, 'spec': 'P3 を2017年表で全期間（後知恵）' if nm.startswith('HIND') else 'P3 を1963年表で最後まで（表を更新しない）', 'meta': o[2]}
    # 回帰: (規則−Mkt) = a + b1 (CTRL−Mkt) + b2 (Mkt−RF)
    regs = {}
    for nm in ('P1_MO_customer_vw', 'P2_MO_supplier_vw', 'P3_MO_composite_vw', 'P5_RSTZ_lasso_ff49_vw', 'P4_RSTZ_lasso_ff30_vw'):
        g = rules[nm]['gross']
        ks = sorted(k for k in g if k in ctrl[0] and k in mkt)
        y = [g[k] - mkt[k] for k in ks]
        X = [[ctrl[0][k] - mkt[k], mktrf[k]] for k in ks]
        b, se = nw_ols(y, X)
        regs[nm] = {'months': len(ks), 'alpha_ann_pct': round(b[0] * 1200, 2), 'alpha_nw_t': round(b[0] / se[0], 2),
                    'beta_ctrl_own1m_excess': round(b[1], 3), 'beta_ctrl_t': round(b[1] / se[1], 2), 'beta_mktrf': round(b[2], 3)}
        # 保有期間だけ
        kh = [k for k in ks if k >= N.HOLD_START]
        b2, se2 = nw_ols([g[k] - mkt[k] for k in kh], [[ctrl[0][k] - mkt[k], mktrf[k]] for k in kh])
        regs[nm]['hold_alpha_ann_pct'] = round(b2[0] * 1200, 2); regs[nm]['hold_alpha_nw_t'] = round(b2[0] / se2[0], 2)
    controls['regression_on_CTRL_own1m'] = {'spec': '(規則−Mkt) を [1, (CTRL_own1m−Mkt), (Mkt−RF)] に回帰した切片（年率%・NW t ラグ12）。事前登録は P3・P5。P1・P2・P4 も同じ式で報告', 'results': regs}
    # 偽の規則
    rng = np.random.default_rng(20260928)
    real = entries['P3_MO_composite_vw']['stats_gross']['full']
    pl_ex, pl_cd, pl_t = [], [], []
    for i in range(200):
        perm = rng.permutation(nI)
        r, to, _, _ = run_rule(P49, mo_sig('comp', perm=perm), t_mo, K5, 'vw')
        s = N.excess_stats(r, mkt)
        pl_ex.append(s['ex_ann']); pl_cd.append(s['cagr_diff']); pl_t.append(s['t'] or 0)
    controls['PLACEBO_P3'] = {'spec': 'P3 の重み行列の業種の名札を並べ替えた（行と列に同じ並べ替え・全期間で固定）200回。乱数の種 20260928（numpy default_rng の permutation を続けて200回）',
                              'placebo_full_ex_ann': {'median': float(np.median(pl_ex)), 'p05': float(np.percentile(pl_ex, 5)), 'p95': float(np.percentile(pl_ex, 95)), 'max': float(np.max(pl_ex))},
                              'placebo_full_cagr_diff': {'median': float(np.median(pl_cd)), 'p05': float(np.percentile(pl_cd, 5)), 'p95': float(np.percentile(pl_cd, 95)), 'max': float(np.max(pl_cd))},
                              'placebo_full_t': {'median': float(np.median(pl_t)), 'p95': float(np.percentile(pl_t, 95))},
                              'real_P3_full': {'ex_ann': real['ex_ann'], 'cagr_diff': real['cagr_diff'], 't': real['t']},
                              'real_percentile_ex_ann': pct_rank(real['ex_ann'], pl_ex), 'real_percentile_cagr_diff': pct_rank(real['cagr_diff'], pl_cd),
                              'share_placebo_ge_real_ex_ann': round(float(np.mean(np.array(pl_ex) >= real['ex_ann'])), 3)}
    res['controls_report_only'] = controls

    # ── 実在のセクター ETF と JKP 米国 GICS（報告のみ・格付けしない）
    log('実在のセクター ETF（Yahoo）と JKP 米国 GICS')
    real_chk = {}
    try:
        et = {}
        for tk, g in ETF.items():
            et[g] = {k: v for k, v in N.yahoo(tk).items() if k <= 202608}
        spy = {k: v for k, v in N.yahoo('SPY').items() if k <= 202608}
        Pe = dict_to_panel(et, g11)
        Pe = Panel([m for m in Pe.months if m >= 199901], g11, Pe.R[Pe.idx[199901]:])
        tl = Pe.months[:-1]

        def esig(t):
            y = table_at(t, sched)
            r = Pe.R[Pe.idx[t]]
            return (partner_signal(TB[y]['GC'], r) + partner_signal(TB[y]['GS'], r)) / 2
        r, to, meta, _ = run_rule(Pe, esig, tl, K5, 'ew')
        e1, _ = evaluate('R1_etf', r, to, spy, rf)
        real_chk['R1_etf_P3_gics'] = {**e1, 'meta': meta, 'spec': 'P3 の GICS 版（米国の表の gics 重み・上位 K=round(N/5) を等分）を Select Sector SPDR（配当込み）に当てる。相手 SPY'}
        rfe = np.array([rf[m] for m in Pe.months])
        Fe = rstz_forecasts_missing(Pe.months, Pe.R - rfe[:, None], Pe.idx[199902])
        r, to, meta, _ = run_rule(Pe, lambda t: Fe[t], sorted(Fe), K5, 'ew')
        e2, _ = evaluate('R2_etf', r, to, spy, rf)
        real_chk['R2_etf_P5_gics'] = {**e2, 'meta': meta, 'spec': 'P5 の GICS 版（ETF 自身の超過で LASSO・初期窓120組）。相手 SPY'}
        # 参考: SPY と French Mkt の差（同じ期間）
        real_chk['SPY_vs_FrenchMkt_1999_2026'] = N.excess_stats(spy, mkt, a=199901)
    except Exception as ex:  # noqa
        real_chk['etf_error'] = repr(ex)
    try:
        du = jkp_gics('usa')
        Pu = dict_to_panel(du, g11)
        mku = N.jkp_mkt('usa', 'vw')
        tl = Pu.months[:-1]

        def usig(t):
            y = table_at(t, sched)
            r = Pu.R[Pu.idx[t]]
            return (partner_signal(TB[y]['GC'], r) + partner_signal(TB[y]['GS'], r)) / 2
        r, to, meta, _ = run_rule(Pu, usig, tl, K5, 'ew')
        real_chk['R1_jkp_us_P3_gics'] = {'excess': N.excess_stats(r, mku), 'excess_net010': N.excess_stats(net_of(r, to, COST), mku),
                                         'hold': N.excess_stats(r, mku, a=N.HOLD_START), 'meta': meta, 'spec': 'JKP 米国 GICS（超過）に P3 の GICS 版。相手 JKP 米国市場 vw'}
        Fu = rstz_forecasts_missing(Pu.months, Pu.R, Pu.idx[199908])
        r, to, meta, _ = run_rule(Pu, lambda t: Fu[t], sorted(Fu), K5, 'ew')
        real_chk['R2_jkp_us_P5_gics'] = {'excess': N.excess_stats(r, mku), 'excess_net010': N.excess_stats(net_of(r, to, COST), mku), 'meta': meta,
                                         'spec': 'JKP 米国 GICS に P5 の GICS 版（2009-08〜）'}
    except Exception as ex:  # noqa
        real_chk['jkp_us_error'] = repr(ex)
    res['real_instrument_check_report_only'] = real_chk

    # ── tested（1本残らず）
    tested = []
    for name, e in entries.items():
        tested.append({k: e[k] for k in ('name', 'family', 'spec', 'grade', 'criteria', 'holm_p_in_family', 'span', 'stats_gross', 'cost',
                                        'roll20_net', 'roll20_gross', 'dca20_net_ratio', 'dca20_gross_ratio', 'maxdd', 'sharpe', 'meta',
                                        'vs_ew_industry_average_report') if k in e}
                      | ({'grade_label': e['grade_label']} if 'grade_label' in e else {})
                      | ({'c5_repl': repl_of[name]} if name in repl_of else {}))
    for nm, v in controls.items():
        tested.append({'name': nm, 'family': 'control_report_only', 'grade': None, **{k: v[k] for k in v if k != 'W'}})
    for c in COUNTRIES:
        for lab in ('P1', 'P2', 'P3', 'P4_P5'):
            v = res['c5']['countries'][c][lab]
            tested.append({'name': f'C5_{c}_{lab}', 'family': 'c5_unit', 'grade': None, 'positive': v['positive'], 'excess': v['excess'], 'excess_net010': v['excess_net010']})
    for nm, v in real_chk.items():
        if isinstance(v, dict):
            tested.append({'name': nm, 'family': 'real_instrument_report_only', 'grade': None, **v})
    res['tested'] = tested
    res['test_count'] = {'primary': sum(1 for e in entries.values() if e['family'] == 'primary'),
                         'exploratory': sum(1 for e in entries.values() if e['family'] == 'exploratory'),
                         'c5_units': 7 * 4, 'placebo_runs': 200, 'controls': len(controls), 'real_instrument': len([v for v in real_chk.values() if isinstance(v, dict)])}
    res['holm'] = fam_p
    res['grades'] = {n: e['grade'] for n, e in entries.items()}
    # 事後の診断に使う系列を手元にためる（JSON には入れない）
    np.save(os.path.join(N.CACHE, 'nx_leadlag_series.npy'), {n: {'gross': r['gross'], 'to': r['to'], 'W': r['W']} for n, r in rules.items()} | {'CTRL_own1m_vw': {'gross': ctrl[0], 'to': ctrl[1]}}, allow_pickle=True)
    return res, rules, entries, P49, P30, mkt, rf, mktrf, ctrl


NBER = [(196912, 197011), (197311, 197503), (198001, 198007), (198107, 198211), (199007, 199103), (200103, 200111), (200712, 200906), (202002, 202004)]


def post_hoc(res, rules, entries, P49, P30, mkt, rf, mktrf, ctrl):
    """事後（結果を見た後）の診断。格付けには使わない"""
    out = {'label': '事後（結果を見た後の診断・格付けに使わない）', 'items': {}}
    it = out['items']
    rec = lambda k: any(a <= k <= z for a, z in NBER)  # noqa: E731
    # (a) 10年ごとの幾何の超過（費用前）
    dec = {}
    for n, R_ in rules.items():
        g = R_['gross']
        row = {}
        for a in range(1950, 2030, 10):
            s = N.excess_stats(g, mkt, a=a * 100 + 1, z=(a + 9) * 100 + 12)
            if s:
                row[f'{a}s'] = s['cagr_diff']
        dec[n] = row
    it['decade_cagr_diff_gross'] = {'spec': '10年ごとの幾何の年率差（規則−Mkt・費用前・%）', 'rows': dec}
    # (b) 景気後退（NBER の日付・公開の知識）と拡大の月の超過の平均（年率%）
    rc = {}
    for n, R_ in rules.items():
        g = R_['gross']
        ex_r = [g[k] - mkt[k] for k in g if rec(k)]
        ex_e = [g[k] - mkt[k] for k in g if not rec(k)]
        ex_rh = [g[k] - mkt[k] for k in g if rec(k) and k >= N.HOLD_START]
        rc[n] = {'recession_months': len(ex_r), 'recession_ex_ann': round(float(np.mean(ex_r)) * 1200, 2) if ex_r else None,
                 'expansion_ex_ann': round(float(np.mean(ex_e)) * 1200, 2) if ex_e else None,
                 'expansion_t': N.nw_t(ex_e) and round(N.nw_t(ex_e), 2),
                 'hold_recession_months': len(ex_rh), 'hold_recession_ex_ann': round(float(np.mean(ex_rh)) * 1200, 2) if ex_rh else None}
    it['recession_vs_expansion'] = {'spec': 'NBER の景気後退の月（1969-12〜1970-11 ほか8回）とそれ以外の月の、規則−Mkt の算術平均×12（%）。RSTZ は景気後退で勝つと書いていた', 'rows': rc}
    # (c) 保有期間の業種ごとの寄与（主の族）: Σ_h w_{h,i}(r_{h,i} − Mkt_h) を年率に
    contrib = {}
    for n in ('P1_MO_customer_vw', 'P2_MO_supplier_vw', 'P3_MO_composite_vw', 'P4_RSTZ_lasso_ff30_vw', 'P5_RSTZ_lasso_ff49_vw'):
        W = rules[n]['W']
        P = P30 if n.startswith('P4') else P49
        for lab, a, z in (('train', 0, N.TRAIN_END), ('hold', N.HOLD_START, 999999)):
            ks = [h for h in sorted(W) if a <= h <= z]
            if not ks:
                continue
            c = np.zeros(P.n); held = np.zeros(P.n)
            for h in ks:
                rh = np.nan_to_num(P.R[P.idx[h]])
                c += W[h] * (rh - mkt[h]); held += (W[h] > 0)
            c = c / len(ks) * 1200
            order = np.argsort(-c)
            contrib.setdefault(n, {})[lab] = {'months': len(ks), 'sum_ex_ann': round(float(c.sum()), 2),
                                              'top5': [(P.names[i], round(float(c[i]), 2), int(held[i])) for i in order[:5]],
                                              'bottom5': [(P.names[i], round(float(c[i]), 2), int(held[i])) for i in order[-5:]],
                                              'sum_without_top1': round(float(c.sum() - c[order[0]]), 2)}
    it['industry_contribution'] = {'spec': '(業種, 寄与の年率%, 持った月数)。寄与 = Σ_h w_{h,i}(r_{h,i} − Mkt_h)／月数×12。合計は算術の超過に一致。sum_without_top1 は最大の寄与の1業種を引いた会計上の残り（持ち替えは考えない）', 'rows': contrib}
    # (d) 対照（自分の前月）との超過の相関
    cr = {}
    for n, R_ in rules.items():
        ks = sorted(k for k in R_['gross'] if k in ctrl[0])
        if len(ks) > 24:
            cr[n] = round(N.corr([R_['gross'][k] - mkt[k] for k in ks], [ctrl[0][k] - mkt[k] for k in ks]), 3)
    it['corr_excess_with_CTRL_own1m'] = cr
    return out


if __name__ == '__main__':
    res, rules, entries, P49, P30, mkt, rf, mktrf, ctrl = main()
    res['post_hoc'] = post_hoc(res, rules, entries, P49, P30, mkt, rf, mktrf, ctrl)
    res['seconds'] = round(time.time() - T0, 1)
    p = N.save(OUTNAME, res)
    log('書いた', p)
    for n, e in entries.items():
        st = e['stats_gross']
        log(f"{n:34s} {e['grade']}  train {st['train']['ex_ann'] if st['train'] else None} (t {st['train']['t'] if st['train'] else None})"
            f"  hold {st['hold']['ex_ann']} (t {st['hold']['t']}) cagr {st['hold']['cagr_diff']}  full t {st['full']['t']}")
