#!/usr/bin/env python3
"""night/mw_reality_gap.py — 角度 reality_gap: 紙の上の『質の良い側』と実在の質ETF・投信の差を分解する（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」の第3巡。
問い: 紙の上（JKP 米国 vw 三分位の良い側）の質は 2007年以降も French Mkt に勝ったのに、実在の質ETF は負けた。なぜか。
      実在の手段で紙の上乗せを取れたものはあるか。

事前登録: out/mw_reality_gap_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を mw_common.grade でそのまま当てる。
出力: out/mw_reality_gap.json（試した全部を tested に残す＝多重検定の数）

部品
  part1 分解: 紙の上乗せ y = P − MktRF を 12/49業種・5因子＋勢い・金融除外の市場へ回帰（Newey-West t）。被覆（三分位）・上限（vw_cap/ew）
  part2 実在の手段: Yahoo の日次の調整後終値（分配込み）→ 月次。French Mkt と比べ、紙の上乗せへの載りと『実装の目減り』を出す
  part3 業種中立: SN60/SN120（直前の窓の係数で業種成分を引いた紙の上乗せ）・スタイル分析で紙の業種の重み
  I 族: P5 の業種の写し（直前の窓のスタイル分析の重みで翌月の業種を持つ）＝買いだけ・業種の器
"""
import sys, os, json, math, subprocess, datetime, time, urllib.parse, urllib.request, statistics as S
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M
import numpy as np

PRE_NAME = 'mw_reality_gap_prereg.json'
OUT_NAME = 'mw_reality_gap.json'
JKP_END = 202512
P_START = 196307

FF = M.ff_factors()
MKTRF, RF, MKT = FF['mktrf'], FF['rf'], FF['mkt']


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


# ───────────────────────── French ─────────────────────────
def fr_monthly(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            return v
    raise KeyError(f'{name}: {want}')


def industries(name):
    """French 業種ファイル → (列, {列: {ym: 総リターン小数}}, 社数表, 平均規模表)"""
    ret = fr_monthly(name, 'Average Value Weighted Returns')
    nf = fr_monthly(name, 'Number of Firms')
    sz = fr_monthly(name, 'Average Firm Size')
    cols = ret['cols']
    r = {c: {d: row[i] / 100 for d, row in ret['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
    return cols, r, nf, sz


def ff5_umd():
    v = next(v for t, v in M.french_tables('F-F_Research_Data_5_Factors_2x3').items() if v['freq'] == 'monthly')
    cols = [c.lower().replace('-', '') for c in v['cols']]
    out = {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
    mom = next(v for t, v in M.french_tables('F-F_Momentum_Factor').items() if v['freq'] == 'monthly')
    out['umd'] = {d: row[0] / 100 for d, row in mom['data'].items() if row[0] is not None}
    return out


def region_ff(name5, mom_name):
    v = next(v for t, v in M.french_tables(name5).items() if v['freq'] == 'monthly')
    cols = [c.lower().replace('-', '') for c in v['cols']]
    out = {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
    mm = next(v for t, v in M.french_tables(mom_name).items() if v['freq'] == 'monthly')
    out['umd'] = {d: row[0] / 100 for d, row in mm['data'].items() if row[0] is not None}
    out['mkt'] = {d: out['mktrf'][d] + out['rf'][d] for d in out['mktrf'] if d in out['rf']}
    return out


def mkt_weights(nf, sz, cols):
    """前月の『平均規模×社数』の市場の業種の重み → {ym: {列: 重み}}（当月の値は使わない）"""
    ks = sorted(nf['data'])
    out = {}
    for p, k in zip(ks, ks[1:]):
        w = {}
        for i, c in enumerate(cols):
            n, s = nf['data'][p][i], sz['data'].get(p, [None] * len(cols))[i]
            if n is None or s is None or n <= 0 or s <= 0:
                continue
            w[c] = n * s
        tot = sum(w.values())
        if tot > 0:
            out[k] = {c: x / tot for c, x in w.items()}
    return out


def ex_fin_market():
    """French 49業種から Banks・Insur・RlEst・Fin を除いた時価加重の市場（前月の平均規模×社数・factor_us と同じ作り方）"""
    cols, r, nf, sz = industries('49_Industry_Portfolios')
    W = mkt_weights(nf, sz, cols)
    fin = {'Banks', 'Insur', 'RlEst', 'Fin'}
    all_, xf = {}, {}
    for k, w in W.items():
        na = da = nx = dx = 0.0
        for c, x in w.items():
            v = r[c].get(k)
            if v is None:
                continue
            na += x * v; da += x
            if c not in fin:
                nx += x * v; dx += x
        if da > 0 and dx > 0:
            all_[k] = na / da; xf[k] = nx / dx
    return all_, xf


# ───────────────────────── JKP ─────────────────────────
_JK = {}


def jkp_pf_n(region, key, weighting='vw'):
    k = (region, key, weighting)
    if k not in _JK:
        d = {}
        for x in M.jkp_rows(region, key, 'portfolios', weighting):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            n = int(float(x['n'])) if x.get('n') not in (None, '', 'NA', 'na') else None
            d.setdefault(x['pf'], {})[M._ym(x['date'])] = (float(x['ret']), n)
        _JK[k] = d
    return _JK[k]


_SIDE = {}


def good_side(key):
    """良い側は米国 vw の 2006-12 までで決める（combo_us と同じ）。vw_cap/ew/地域版も同じ側を使う"""
    if key not in _SIDE:
        s, _ = M.jkp_good_side('usa', key, 'vw', upto=M.TRAIN_END)
        if s is None:
            raise RuntimeError(f'{key}: 2006-12 までで良い側が決まらない')
        _SIDE[key] = s
    return _SIDE[key]


def mix(series):
    ks = sorted(set.intersection(*[set(s) for s in series])) if series else []
    return {k: sum(s[k] for s in series) / len(series) for k in ks}


def since(s, a):
    return {k: v for k, v in s.items() if k >= a}


def paper(keys, weighting='vw', region='usa', min_n=0, start=P_START, pf=None):
    """良い側（pf を渡せばその三分位）の等分混合（超過）。各袖が min_n 社以上の月だけ（欠測は0にしない）"""
    ser = []
    for key in keys:
        d = jkp_pf_n(region, key, weighting).get(pf or good_side(key), {})
        ser.append({ym: r for ym, (r, n) in d.items() if min_n == 0 or (n is not None and n >= min_n)})
    m = mix(ser)
    return since(m, start) if start else m


def to_total(ex):
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


def active(ex, bench_ex):
    return {k: ex[k] - bench_ex[k] for k in ex if k in bench_ex}


# ───────────────────────── 回帰 ─────────────────────────
def ols_nw(Y, X, lag=12):
    n, k = X.shape
    XtXi = np.linalg.pinv(X.T @ X)
    b = XtXi @ X.T @ Y
    e = Y - X @ b
    u = X * e[:, None]
    Sm = u.T @ u
    for L in range(1, min(lag, n - 1) + 1):
        G = u[L:].T @ u[:-L]
        Sm = Sm + (1 - L / (lag + 1)) * (G + G.T)
    V = XtXi @ Sm @ XtXi
    se_nw = np.sqrt(np.maximum(np.diag(V), 0))
    s2 = (e @ e) / max(n - k, 1)
    se_ols = np.sqrt(np.maximum(np.diag(XtXi) * s2, 0))
    yc = Y - Y.mean()
    r2 = 1 - (e @ e) / (yc @ yc) if yc @ yc > 0 else None
    return b, se_nw, se_ols, r2, e


def reg(y, xs, a=None, z=None, lag=12, min_n=36, coefs=True):
    """y: {ym: v}、xs: [(名前, {ym: v})]。全部がそろう月だけ（欠測は0にしない）"""
    ks = sorted(k for k in y if (a is None or k >= a) and (z is None or k <= z) and all(k in x for _, x in xs))
    if len(ks) < max(min_n, len(xs) + 12):
        return None
    Y = np.array([y[k] for k in ks])
    X = np.column_stack([np.ones(len(ks))] + [np.array([x[k] for k in ks]) for _, x in xs])
    b, se, so, r2, _ = ols_nw(Y, X, lag)
    o = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'alpha_ann': round(float(b[0]) * 1200, 2),
         'alpha_t_nw': round(float(b[0] / se[0]), 2) if se[0] > 0 else None,
         'alpha_t_ols': round(float(b[0] / so[0]), 2) if so[0] > 0 else None,
         'r2': round(float(r2), 3) if r2 is not None else None}
    if coefs:
        o['coef'] = {nm: [round(float(bb), 3), round(float(bb / s), 2) if s > 0 else None] for (nm, _), bb, s in zip(xs, b[1:], se[1:])}
    return o


def sn_rolling(y, xs, W, a_min=None):
    """直前 W か月（t−W〜t−1 が全部そろう）で係数を推定し、当月の成分を引く（切片は引かない）→ {ym: SN}"""
    ks = sorted(k for k in y if all(k in x for _, x in xs))
    out = {}
    for i in range(W, len(ks)):
        win = ks[i - W:i]
        # 連続した月であることを確かめる（途中に欠けがあれば飛ばす）
        if months_between(win[0], ks[i]) != W:
            continue
        Y = np.array([y[k] for k in win])
        X = np.column_stack([np.ones(W)] + [np.array([x[k] for k in win]) for _, x in xs])
        b = np.linalg.lstsq(X, Y, rcond=None)[0]
        k = ks[i]
        out[k] = y[k] - sum(float(bb) * x[k] for bb, (_, x) in zip(b[1:], xs))
    return out


def months_between(a, b):
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def mean_t(d, a=None, z=None):
    x = [v for k, v in sorted(d.items()) if (a is None or k >= a) and (z is None or k <= z)]
    if len(x) < 24:
        return None
    t = M.nw_t(x)
    return {'n': len(x), 'mean_ann': round(S.mean(x) * 1200, 2), 't_nw': round(t, 2) if t is not None else None}


# ───────────────────────── スタイル分析（重み≥0・合計1） ─────────────────────────
def nnls(A, b, tol=1e-12, maxiter=500):
    """Lawson-Hanson の非負最小二乗"""
    m, n = A.shape
    P = np.zeros(n, bool)
    x = np.zeros(n)
    w = A.T @ (b - A @ x)
    it = 0
    while (~P).any() and np.max(np.where(~P, w, -np.inf)) > tol and it < maxiter:
        it += 1
        j = int(np.argmax(np.where(~P, w, -np.inf)))
        P[j] = True
        while True:
            z = np.zeros(n)
            z[P] = np.linalg.lstsq(A[:, P], b, rcond=None)[0]
            if (z[P] > tol).all():
                break
            mask = P & (z <= tol)
            den = x[mask] - z[mask]
            alpha = np.min(np.where(den > 0, x[mask] / np.where(den > 0, den, 1), 1.0))
            x = x + alpha * (z - x)
            P = P & (x > tol)
            if not P.any():
                z = np.zeros(n)
                break
        x = z
        w = A.T @ (b - A @ x)
    return x


def style_weights(Y, X, pen=100.0):
    """min ||X w − Y||² s.t. w≥0, Σw=1（合計1は罰則の行で課し、最後に合計1へ割り戻す）"""
    A = np.vstack([X, pen * np.ones((1, X.shape[1]))])
    b = np.concatenate([Y, [pen]])
    w = nnls(A, b)
    s = w.sum()
    return w / s if s > 0 else None


def replica(target_ex, ind_tot, cols, W=None, min_w=60, start=P_START):
    """P5（超過）を業種（超過）へスタイル分析 → t−1 までの重みで当月の業種（総リターン）を持つ。
    W=None は拡大窓（min_w か月以上）。戻り値: (総リターン {ym}, 重み {ym: {列: w}}, 各月の片道回転率 {ym})"""
    months = sorted(k for k in RF if k >= start)
    ks = [k for k in months if k in target_ex]
    ret, wts, turn = {}, {}, {}
    prev_w, prev_drift = None, None
    for t in months:
        past = [k for k in ks if k < t]
        if W is not None:
            past = past[-W:]
            if len(past) < W or months_between(past[0], t) != W:
                continue
        elif len(past) < min_w:
            continue
        use = [c for c in cols if all(k in ind_tot[c] for k in past)]
        if len(use) < 2:
            continue
        Y = np.array([target_ex[k] for k in past])
        X = np.column_stack([np.array([ind_tot[c][k] - RF[k] for k in past]) for c in use])
        w = style_weights(Y, X)
        if w is None:
            continue
        wd = {c: float(x) for c, x in zip(use, w) if x > 1e-6}
        avail = {c: x for c, x in wd.items() if t in ind_tot[c]}
        sw = sum(avail.values())
        if sw <= 0:
            continue
        avail = {c: x / sw for c, x in avail.items()}
        r = sum(x * ind_tot[c][t] for c, x in avail.items())
        ret[t] = r
        wts[t] = avail
        if prev_drift is not None:
            keys = set(avail) | set(prev_drift)
            turn[t] = 0.5 * sum(abs(avail.get(c, 0) - prev_drift.get(c, 0)) for c in keys)
        prev_drift = {c: x * (1 + ind_tot[c][t]) / (1 + r) for c, x in avail.items()}
    return ret, wts, turn


# ───────────────────────── Yahoo（日次の調整後終値・分配込み） ─────────────────────────
def yh_daily(t):
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}'
         f'&interval=1d&events=div%2Csplit%2CcapitalGains')
    j = json.loads(M.get(u, name=f'rg_yh_{t.replace("^", "IDX_")}_1d_cg.json', max_age_days=3))
    r = j['chart']['result'][0]
    ts = r.get('timestamp') or []
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    days, px = [], []
    for a, p in zip(ts, adj):
        if p is None or p <= 0:
            continue
        d = datetime.datetime.fromtimestamp(a, datetime.timezone.utc)
        days.append(d.year * 10000 + d.month * 100 + d.day); px.append(p)
    ev = set()
    for kind in ('dividends', 'capitalGains'):
        for e in (r.get('events') or {}).get(kind, {}).values():
            d = datetime.datetime.fromtimestamp(e['date'], datetime.timezone.utc)
            ev.add(datetime.date(d.year, d.month, d.day))
    # 検算（事後に見つけたデータの穴・結果ではなくデータの検算で決めた）: Yahoo が分割イベントを持ちながら調整後終値に
    # 反映していないことがある（CFIMX 2025-05-12 の 10:1・139→14.5）。分割の日の値動きが分割比と 10% 以内で一致するときだけ、
    # それより前の値を分割比で割り戻す（一致しないときは Yahoo がすでに調整済みとみなして触らない）
    fixes = []
    for e in (r.get('events') or {}).get('splits', {}).values():
        num, den = float(e.get('numerator') or 0), float(e.get('denominator') or 0)
        if num <= 0 or den <= 0:
            continue
        d = datetime.datetime.fromtimestamp(e['date'], datetime.timezone.utc)
        dk = d.year * 10000 + d.month * 100 + d.day
        i = next((j for j, x in enumerate(days) if x >= dk), None)
        if i is None or i == 0:
            continue
        jump = px[i] / px[i - 1]
        if abs(jump * num / den - 1) < 0.10:
            f = den / num
            px = [p * f if j < i else p for j, p in enumerate(px)]
            fixes.append({'date': dk, 'ratio': f'{num:g}:{den:g}', 'jump_before_fix': round(jump, 4)})
    itype = (r.get('meta') or {}).get('instrumentType')
    return days, px, ev, fixes, itype


FUND_DATA_START = 198701
# S&P 500 の年次総リターン（%・公開の値）。Yahoo の VFINX と突き合わせて投信の古いデータの信頼性を検算する
SP500_TR = {1985: 32.16, 1986: 18.47, 1987: 5.23, 1988: 16.81, 1989: 31.49, 1990: -3.10, 1991: 30.47, 1992: 7.62, 1993: 10.08, 1994: 1.32,
            1995: 37.58, 1996: 22.96, 1997: 33.36, 1998: 28.58, 1999: 21.04, 2000: -9.10, 2001: -11.89, 2002: -22.10, 2003: 28.68,
            2004: 10.88, 2005: 4.91, 2006: 15.79, 2007: 5.49, 2008: -37.00}


def yh_daily_unfixed(t):
    """事前登録どおりの生データ（分割の未反映を直さない）"""
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}'
         f'&interval=1d&events=div%2Csplit%2CcapitalGains')
    r = json.loads(M.get(u, name=f'rg_yh_{t.replace("^", "IDX_")}_1d_cg.json', max_age_days=3))['chart']['result'][0]
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    days, px = [], []
    for a, p in zip(r.get('timestamp') or [], adj):
        if p is None or p <= 0:
            continue
        d = datetime.datetime.fromtimestamp(a, datetime.timezone.utc)
        days.append(d.year * 10000 + d.month * 100 + d.day); px.append(p)
    return days, px


_OP = {}


def ms_annual(t):
    """Yahoo quoteSummary の fundPerformance.annualTotalReturns（Morningstar の年次総リターン）→ {年: 小数}。
    事後に足した検算（投信の Yahoo 日次がキャピタルゲイン分配を取りこぼす年があると分かったため）。無ければ {}"""
    import http.cookiejar
    p = os.path.join(M.CACHE, f'rg_ms_{t}.json')
    if not (os.path.exists(p) and os.path.getsize(p) > 0 and time.time() - os.path.getmtime(p) < 30 * 86400):
        try:
            if 'op' not in _OP:
                cj = http.cookiejar.CookieJar()
                op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
                ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                op.addheaders = [('User-Agent', ua), ('Accept', 'text/html'), ('Accept-Language', 'en-US,en;q=0.9')]
                op.open('https://finance.yahoo.com/quote/SPY/', timeout=60).read()
                op.addheaders = [('User-Agent', ua), ('Accept', '*/*')]
                crumb = None
                for i in range(6):
                    try:
                        crumb = op.open('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=60).read().decode(); break
                    except Exception:  # noqa
                        time.sleep(10 * (i + 1))
                _OP['op'], _OP['crumb'] = op, crumb
            b = _OP['op'].open(f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(t)}?modules=fundPerformance&crumb={_OP['crumb']}", timeout=60).read()
            open(p, 'wb').write(b)
        except Exception:  # noqa
            return {}
    try:
        rets = json.load(open(p))['quoteSummary']['result'][0]['fundPerformance']['annualTotalReturns']['returns']
    except Exception:  # noqa
        return {}
    return {int(x['year']): x['annualValue']['raw'] for x in rets if x.get('annualValue', {}).get('raw') is not None}


def ms_correct(m, ms, thr=1.0):
    """暦年の Yahoo（月次の積）と Morningstar の年次が thr ポイントを超えて違う年だけ、その年の12か月を同じ倍率で直し、
    年の積が Morningstar と一致するようにする（倍率を月に等分）。直した年の {年: [Yahoo, Morningstar]} を返す"""
    out, fixed = dict(m), {}
    for y, v in ms.items():
        a = annual(m, y)
        if a is None or abs(a - v * 100) <= thr:
            continue
        k = ((1 + v) / (1 + a / 100)) ** (1 / 12)
        for mm in range(y * 100 + 1, y * 100 + 13):
            out[mm] = (1 + out[mm]) * k - 1
        fixed[y] = [a, round(v * 100, 2)]
    return out, fixed


def annual(m, y):
    ms = [m[k] for k in range(y * 100 + 1, y * 100 + 13) if k in m]
    if len(ms) < 12:
        return None
    g = 1.0
    for v in ms:
        g *= 1 + v
    return round((g - 1) * 100, 2)


def monthly_from_daily(days, px):
    last = {}
    for d, p in zip(days, px):
        last[d // 100] = p
    ks = sorted(last)
    out = {}
    for p, k in zip(ks, ks[1:]):
        if months_between(p, k) == 1:
            out[k] = last[k] / last[p] - 1
    return out


def dist_flags(days, px, ev, mkt_daily, thr=-0.04):
    """『手段 − 日次 Mkt』< thr かつ ±5日以内に分配イベントが無い日（分配の取りこぼし疑い）"""
    out = []
    for i in range(1, len(days)):
        d = days[i]
        if d not in mkt_daily:
            continue
        r = px[i] / px[i - 1] - 1
        if r - mkt_daily[d] < thr:
            dd = datetime.date(d // 10000, d // 100 % 100, d % 100)
            if not any(abs((dd - e).days) <= 5 for e in ev):
                out.append((d, round(r * 100, 2), round(mkt_daily[d] * 100, 2)))
    return out


# ───────────────────────── 手段の一覧（事前登録どおり） ─────────────────────────
PRE = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
G = PRE['part2_real_vehicles']['groups']
GROUPS = {}
for gname, lst in G.items():
    code = gname.split('（')[0]
    for t in lst:
        GROUPS[t] = code
SUBWIN = {'SPHQ_VLT': ('SPHQ', 200601, 201006), 'SPHQ_HQR': ('SPHQ', 201007, 201603), 'SPHQ_Q': ('SPHQ', 201604, None),
          'VDIGX_DG': ('VDIGX', 200301, None)}
INTL = {t for t, g in GROUPS.items() if g == 'ETF_INTL'} | {'EFA'}
GLOBAL = {t for t, g in GROUPS.items() if g == 'GLOBAL'}
QFUND = [t for t, g in GROUPS.items() if g in ('QF', 'DG')]
LONGFUND_R = [t for t, g in GROUPS.items() if g in ('QF', 'DG', 'GR')]

# 第2段（探索・out/mw_reality_gap_prereg2.json）
PRE2_NAME = 'mw_reality_gap_prereg2.json'
PRE2 = json.load(open(os.path.join(M.BASE, 'out', PRE2_NAME)))
for gname, lst in PRE2['families'].items():
    if not isinstance(lst, list):
        continue
    code = gname.split('（')[0]
    for t in lst:
        GROUPS.setdefault(t, code)
E_LF = [t for t, g in GROUPS.items() if g == 'E_LF']
FAMILY_OF_GROUP = {'E_LF': 'E_LF', 'COMP_E': 'E_LF', 'E_MEGA': 'E_MEGA', 'SANITY': 'SANITY', 'E_SANITY': 'SANITY'}


def main():
    res = {'angle': 'reality_gap', 'tool': 'night/mw_reality_gap.py', 'prereg': f'out/{PRE_NAME}', 'prereg_commit': sha_of(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'global_prereg_commit': sha_of('out/mw_prereg.json'),
           'benchmark': 'French Mkt（Mkt-RF + RF・総リターン）。紙は超過どうし（P − Mkt-RF）。米国外の手段は French Developed_ex_US、世界は French Developed'}
    tested = []

    # ── 業種・因子
    c12, ind12, nf12, sz12 = industries('12_Industry_Portfolios')
    c49, ind49, nf49, sz49 = industries('49_Industry_Portfolios')
    F5 = ff5_umd()
    rel12 = [(c, {k: v - MKT[k] for k, v in ind12[c].items() if k in MKT}) for c in c12]
    rel49 = [(c, {k: v - MKT[k] for k, v in ind49[c].items() if k in MKT}) for c in c49]
    ffx = [('mktrf', MKTRF)] + [(f, F5[f]) for f in ('smb', 'hml', 'rmw', 'cma', 'umd')]
    rebuilt_all, exfin = ex_fin_market()
    exfin_rel = {k: exfin[k] - MKT[k] for k in exfin if k in MKT}
    W12 = mkt_weights(nf12, sz12, c12)
    DEVX = region_ff('Developed_ex_US_5_Factors', 'Developed_ex_US_Mom_Factor')
    DEV = region_ff('Developed_5_Factors', 'Developed_Mom_Factor')
    FFD = M.ff_factors('daily')
    mkt_daily = FFD['mkt']

    # ── 紙
    Q5 = ['ope_be', 'gp_at', 'qmj', 'chcsho_12m', 'oaccruals_at']
    PKEYS = {'P1_cop_at': ['cop_at'], 'P2_ope_be': ['ope_be'], 'P3_qmj_prof': ['qmj_prof'], 'P4_gp_at': ['gp_at'], 'P5_QUAL5': Q5}
    PAP = {k: paper(v) for k, v in PKEYS.items()}
    op = fr_monthly('Portfolios_Formed_on_OP', 'Value Weight Returns')
    ih = op['cols'].index('Hi 30')
    PAP['P6_FR_OP_HI30'] = {d: row[ih] / 100 - RF[d] for d, row in op['data'].items() if row[ih] is not None and d in RF}
    P5 = PAP['P5_QUAL5']
    P5A = active(P5, MKTRF)
    P5_cap = paper(Q5, 'vw_cap')
    P5_ew = paper(Q5, 'ew')
    JKP_MKT_CAP = M.jkp_mkt('usa', 'vw_cap')
    JKP_MKT_VW = M.jkp_mkt('usa', 'vw')
    P5_dev = paper(Q5, 'vw', region='developed', min_n=10, start=None)
    JKP_DEV = M.jkp_mkt('developed', 'vw')
    P5_devA = active(P5_dev, JKP_DEV)

    # ── 検算
    san = {'french_mkt_cagr_full': round(M.cagr(MKT) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(MKT, M.HOLD_START)) * 100, 2),
           'french_mkt_range': [min(MKT), max(MKT)],
           'P5_hold_vs_mktrf（combo_us C6_QUAL5 の 1.6%/年 t2.59 を再現するはず）': M.excess_stats(P5, MKTRF, a=M.HOLD_START),
           'P5_train_vs_mktrf（combo_us 1.63 t4.2）': M.excess_stats(P5, MKTRF, z=M.TRAIN_END),
           'rebuilt_49ind_all_vs_french_mkt': M.excess_stats(rebuilt_all, MKT),
           'jkp_vw_mkt_vs_french_mktrf_hold': M.excess_stats(JKP_MKT_VW, MKTRF, a=M.HOLD_START),
           'jkp_developed_mkt_vs_french_devx_mktrf': M.excess_stats(JKP_DEV, DEVX['mktrf']),
           'corr_jkp_dev_vs_french_devx': round(M.corr(*zip(*[(JKP_DEV[k], DEVX['mktrf'][k]) for k in sorted(set(JKP_DEV) & set(DEVX['mktrf']))])), 4),
           'good_sides': {k: good_side(k) for k in Q5 + ['cop_at', 'qmj_prof']}}
    m0 = reg(P5A, [], a=M.HOLD_START, z=JKP_END, coefs=False)
    san['M0_nw_t_equals_excess_stats_t'] = [m0['alpha_t_nw'], san['P5_hold_vs_mktrf（combo_us C6_QUAL5 の 1.6%/年 t2.59 を再現するはず）']['t']]
    res['sanity'] = san

    # ── part1 分解
    WINS = {'train': (P_START, M.TRAIN_END), 'hold': (M.HOLD_START, JKP_END), 'full': (P_START, JKP_END), 'recent': (M.RECENT_START, JKP_END)}
    p1 = {}
    for pk, pser in PAP.items():
        y = active(pser, MKTRF)
        d = {}
        for wn, (a, z) in WINS.items():
            d[wn] = {'M0_raw': reg(y, [], a, z, coefs=False),
                     'M1_capm': reg(y, [('mktrf', MKTRF)], a, z),
                     'M2_ind12': reg(y, [('mktrf', MKTRF)] + rel12, a, z),
                     'M3_ind49': reg(y, [('mktrf', MKTRF)] + rel49, a, z, coefs=(pk == 'P5_QUAL5')),
                     'M4_ff5umd': reg(y, ffx, a, z),
                     'M5_ind12_ff5umd': reg(y, ffx + rel12, a, z),
                     'M6_exfin': reg(y, [('mktrf', MKTRF), ('exfin_minus_mkt', exfin_rel)], a, z),
                     'vs_exfin_market_total': M.excess_stats(to_total(pser), exfin, a=a, z=z)}
        p1[pk] = d
    res['part1_decomposition'] = p1

    # 被覆
    cov = {}
    mkt_n = {M._ym(x['date']): float(x['n_stocks']) for x in M.jkp_rows('usa', 'mkt', 'factor', 'vw') if x.get('n_stocks') not in (None, '', 'NA')}
    for key in ['cop_at', 'ope_be', 'qmj_prof', 'gp_at', 'qmj', 'chcsho_12m', 'oaccruals_at']:
        pfs = jkp_pf_n('usa', key, 'vw')
        g = good_side(key)
        order = {'good': g, 'middle': '2.0', 'bad': '1.0' if g == '3.0' else '3.0'}
        o = {'good_side': g}
        ser = {}
        for lab, pf in order.items():
            s = since({ym: r for ym, (r, n) in pfs[pf].items()}, P_START)
            ser[lab] = s
            o[lab] = {'train': M.excess_stats(s, MKTRF, z=M.TRAIN_END), 'hold': M.excess_stats(s, MKTRF, a=M.HOLD_START)}
        avg3 = mix(list(ser.values()))
        o['avg3'] = {'train': M.excess_stats(avg3, MKTRF, z=M.TRAIN_END), 'hold': M.excess_stats(avg3, MKTRF, a=M.HOLD_START)}
        cnt = {}
        for ym in pfs['1.0']:
            if ym in pfs['2.0'] and ym in pfs['3.0'] and ym in mkt_n and all(pfs[p][ym][1] is not None for p in ('1.0', '2.0', '3.0')):
                cnt[ym] = sum(pfs[p][ym][1] for p in ('1.0', '2.0', '3.0')) / mkt_n[ym]
        o['count_coverage'] = {'train': round(S.mean(v for k, v in cnt.items() if P_START <= k <= M.TRAIN_END), 3) if cnt else None,
                               'hold': round(S.mean(v for k, v in cnt.items() if k >= M.HOLD_START), 3) if cnt else None}
        o['R3_coverage_bias'] = bool(o['middle']['hold'] and o['bad']['hold'] and o['middle']['hold']['ex_ann'] > 0 and o['bad']['hold']['ex_ann'] > 0)
        cov[key] = o
    res['part1_coverage'] = cov

    # 上限・等加重・地域
    res['part1_capping'] = {
        'P5_vw': {w: M.excess_stats(P5, MKTRF, a=a, z=z) for w, (a, z) in WINS.items()},
        'P5_vw_cap': {w: M.excess_stats(P5_cap, MKTRF, a=a, z=z) for w, (a, z) in WINS.items()},
        'P5_ew': {w: M.excess_stats(P5_ew, MKTRF, a=a, z=z) for w, (a, z) in WINS.items()},
        'P5_vw_cap_vs_jkp_capped_market': {w: M.excess_stats(P5_cap, JKP_MKT_CAP, a=a, z=z) for w, (a, z) in WINS.items()},
        'jkp_capped_market_vs_french_mktrf': {w: M.excess_stats(JKP_MKT_CAP, MKTRF, a=a, z=z) for w, (a, z) in WINS.items()},
        'P5_vw_cap_ind12': {w: reg(active(P5_cap, MKTRF), [('mktrf', MKTRF)] + rel12, a, z) for w, (a, z) in WINS.items() if w in ('train', 'hold')},
    }
    res['part1_regional'] = {'P5_developed_vs_jkp_developed_mkt': {w: M.excess_stats(P5_dev, JKP_DEV, a=a, z=z) for w, (a, z) in
                                                                    {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None), 'recent': (M.RECENT_START, None)}.items()},
                             'P5_developed_ff5umd_devx': {w: reg(P5_devA, [('mktrf', JKP_DEV)] + [(f, DEVX[f]) for f in ('smb', 'hml', 'rmw', 'cma', 'umd')], a, z)
                                                          for w, (a, z) in {'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None)}.items()}}

    # ── part3 業種中立
    x12 = [('mktrf', MKTRF)] + rel12
    SN60 = sn_rolling(P5A, x12, 60)
    SN120 = sn_rolling(P5A, x12, 120)
    p3 = {'SN_is_alpha（窓の中の係数・後知恵あり）': {w: (p1['P5_QUAL5'][w]['M2_ind12'] or {}).get('alpha_ann') for w in WINS},
          'SN60': {w: mean_t(SN60, a, z) for w, (a, z) in WINS.items()},
          'SN120': {w: mean_t(SN120, a, z) for w, (a, z) in WINS.items()},
          'raw_P5_active': {w: mean_t(P5A, a, z) for w, (a, z) in WINS.items()}}
    # 紙の業種の重み（スタイル分析）と市場の業種の重み
    iw = {}
    for w, (a, z) in (('train', (P_START, M.TRAIN_END)), ('hold', (M.HOLD_START, JKP_END))):
        ks = [k for k in sorted(P5) if a <= k <= z and all(k in ind12[c] for c in c12)]
        wv = style_weights(np.array([P5[k] for k in ks]), np.column_stack([np.array([ind12[c][k] - RF[k] for k in ks]) for c in c12]))
        mw = {c: round(S.mean(W12[k].get(c, 0) for k in ks if k in W12), 4) for c in c12}
        iw[w] = {'paper_style_weights': {c: round(float(x), 4) for c, x in zip(c12, wv)}, 'market_weights_avg': mw,
                 'active_weights': {c: round(float(x) - mw[c], 4) for c, x in zip(c12, wv)}}
    p3['industry_weights_proxy'] = iw
    res['part3_sector_neutral'] = p3

    # ── I 族（業種の写し）
    fam_I = {}
    specs = {'I1_IND12_W60': (c12, ind12, 60), 'I2_IND12_W120': (c12, ind12, 120), 'I3_IND12_EXP': (c12, ind12, None), 'I4_IND49_W120': (c49, ind49, 120)}
    for sid, (cols, it, Wn) in specs.items():
        r, wts, turn = replica(P5, it, cols, W=Wn)
        th = [v for k, v in turn.items() if k >= M.HOLD_START]
        to_ann = round(S.mean(th) * 12, 3) if th else None
        net = M.apply_cost(r, to_ann or 0, 0.001)
        net = {k: v - 0.001 / 12 for k, v in net.items()}
        avg_w_hold = {}
        for k, w in wts.items():
            if k >= M.HOLD_START:
                for c, x in w.items():
                    avg_w_hold[c] = avg_w_hold.get(c, 0) + x
        nh = sum(1 for k in wts if k >= M.HOLD_START)
        avg_w_hold = {c: round(x / nh, 4) for c, x in sorted(avg_w_hold.items(), key=lambda z: -z[1])[:12]} if nh else {}
        fam_I[sid] = dict(s=r, net=net, turnover=to_ann, avg_w_hold=avg_w_hold, desc=PRE['families_graded']['I（主）: 業種の写し（買いだけ・業種の器で紙の業種の偏りを取れるか）'][sid])

    def eval_series(s, bench, net=None):
        o = {'full': M.excess_stats(s, bench), 'train': M.excess_stats(s, bench, z=M.TRAIN_END), 'hold': M.excess_stats(s, bench, a=M.HOLD_START),
             'recent': M.excess_stats(s, bench, a=M.RECENT_START)}
        o['cost_hold'] = M.excess_stats(net, bench, a=M.HOLD_START) if net is not None else o['hold']
        o['roll20'] = M.rolling(s, bench, 20)
        o['dca20'] = M.dca(s, bench, 20)
        return o

    I_ev = {sid: eval_series(v['s'], MKT, v['net']) for sid, v in fam_I.items()}
    holm_I = M.holm({sid: (e['hold'] or {}).get('p') for sid, e in I_ev.items()})
    for sid, e in I_ev.items():
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=None, family_holm_p=holm_I.get(sid))
        tested.append({'id': sid, 'family': 'I', 'primary': True, 'exploratory': False, 'desc': fam_I[sid]['desc'],
                       'turnover_oneway_per_year_hold': fam_I[sid]['turnover'], 'unit_cost': 0.001, 'fee_per_year': 0.001,
                       'avg_weights_hold_top': fam_I[sid]['avg_w_hold'], **e, 'holm_p_hold': holm_I.get(sid), 'grade': g, 'criteria': c,
                       'vs_P5_total_hold': M.excess_stats(v_s := fam_I[sid]['s'], to_total(P5), a=M.HOLD_START)})

    # ── part2 実在の手段
    tickers = sorted(GROUPS)
    raw = {}

    def fetch(t):
        try:
            return t, yh_daily(t), None
        except Exception as e:  # noqa
            return t, None, str(e)[:200]
    with ThreadPoolExecutor(6) as ex:
        for t, v, err in ex.map(fetch, tickers):
            raw[t] = (v, err)
    VM, VM_RAW, flags, errors, split_fixes, cut = {}, {}, {}, {}, {}, {}
    ms_check, ms_cov, ms_fixed = {}, {}, {}
    for t, (v, err) in raw.items():
        if v is None or not v[0]:
            errors[t] = err or 'no data'
            continue
        days, px, ev, fx, itype = v
        m = monthly_from_daily(days, px)
        if fx:
            split_fixes[t] = fx
        # 事前登録どおりの生データ（分割の未反映・1987年より前の投信も含む）は別に残す
        VM_RAW[t] = monthly_from_daily(*yh_daily_unfixed(t))
        if itype == 'MUTUALFUND' and min(m) < FUND_DATA_START:
            cut[t] = min(m)
            m = {k: v for k, v in m.items() if k >= FUND_DATA_START}
        ms = ms_annual(t) if t != 'BRK-A' else {}
        ms_check[t] = {y: [annual(m, y), round(v * 100, 2)] for y, v in ms.items() if annual(m, y) is not None and abs(annual(m, y) - v * 100) > 1.0}
        ms_cov[t] = len([y for y in ms if annual(m, y) is not None])
        if itype == 'MUTUALFUND' and ms:
            m, fx2 = ms_correct(m, ms)
            if fx2:
                ms_fixed[t] = fx2
        VM[t] = m
        if t not in INTL and t not in GLOBAL:
            flags[t] = [f for f in dist_flags(days, px, ev, mkt_daily) if itype != 'MUTUALFUND' or f[0] // 100 >= FUND_DATA_START]
    res['part2_fetch'] = {'errors': errors, 'n_ok': len(VM),
                          'split_fixes（分割イベントがあるのに調整後終値に未反映だったものを直した）': split_fixes,
                          'fund_data_start（投信は 1987-01 から。VFINX の Yahoo 年次が 1985 −9.6pt・1986 −9.2pt と S&P500 総リターンから外れ、1987〜は信託報酬の範囲で一致したため）': {'start': FUND_DATA_START, 'trimmed_from': cut},
                          'distribution_flags（分配の取りこぼし疑い・日次 手段−Mkt < −4% かつ ±5日に分配なし）': {t: f for t, f in flags.items() if f},
                          'morningstar_check（事後の検算: 暦年の Yahoo と Morningstar 年次総リターンが 1pt 超違う年 [Yahoo, MS]・直す前）': {t: v for t, v in ms_check.items() if v},
                          'morningstar_years_compared': ms_cov,
                          'morningstar_fixed（投信だけ・その年の12か月を等倍で直して年次を Morningstar に合わせた）': ms_fixed,
                          'note': 'ETF は Morningstar と 1pt 超違う年が1つも無かった（Yahoo の値のまま）。投信は分配（主にキャピタルゲイン）の取りこぼしで Yahoo が大きく低く出る年があった。'}

    def bench_of(t):
        base = t.split('_')[0] if t in SUBWIN else t
        if base in INTL:
            return DEVX['mkt'], 'French Developed_ex_US Mkt', DEVX
        if base in GLOBAL:
            return DEV['mkt'], 'French Developed Mkt', DEV
        return MKT, 'French Mkt', None

    series = {}
    for t, r in VM.items():
        series[t] = r
    for sid, (base, a, z) in SUBWIN.items():
        if base in VM:
            series[sid] = M.window(VM[base], a, z)
    # 合成
    def comp(members, min_n):
        ks = sorted(set().union(*[set(series[m]) for m in members if m in series]))
        out = {}
        for k in ks:
            v = [series[m][k] for m in members if m in series and k in series[m]]
            if len(v) >= min_n:
                out[k] = sum(v) / len(v)
        return out
    etf_us = [t for t, g in GROUPS.items() if g == 'ETF_US']
    qf_members = [('VDIGX_DG' if t == 'VDIGX' else t) for t in QFUND]
    series['COMP_QETF_US'] = comp(etf_us, 2)
    series['COMP_QFUND'] = comp(qf_members, 3)
    # 第2段（探索）の合成
    series['COMP_LF'] = comp(E_LF, 3)
    series['COMP_ALLFUNDS'] = comp([('VDIGX_DG' if t == 'VDIGX' else t) for t in LONGFUND_R] + E_LF, 3)
    CAPF = active(JKP_MKT_CAP, JKP_MKT_VW)   # 上限の効果（JKP の上限つき市場 − 上限なし市場・超過どうし）

    ev_R = {}
    for t, r in series.items():
        base = t.split('_')[0] if t in SUBWIN else t
        grp = 'SUB' if t in SUBWIN else ('COMP_E' if t in ('COMP_LF', 'COMP_ALLFUNDS') else ('COMP' if t.startswith('COMP_') else GROUPS.get(t)))
        B, bname, RFF = bench_of(t)
        r = {k: v for k, v in r.items() if k in B}
        if len(r) < 36:
            continue
        e = eval_series(r, B)
        e['group'] = grp; e['bench'] = bname; e['months'] = len(r)
        y = {k: r[k] - B[k] for k in r}
        yj = {k: v for k, v in y.items() if k <= JKP_END}
        if base in INTL:
            e['paper_reg'] = reg(yj, [('paper_active_P5dev', P5_devA), ('mktrf', DEVX['mktrf'])], min_n=36)
            pa = {k: P5_devA[k] for k in yj if k in P5_devA}
            e['ff5umd'] = reg(y, [('mktrf', DEVX['mktrf'])] + [(f, DEVX[f]) for f in ('smb', 'hml', 'rmw', 'cma', 'umd')], min_n=36)
        elif base in GLOBAL:
            e['paper_reg'] = reg(yj, [('paper_active_P5us', P5A), ('paper_active_P5dev', P5_devA), ('mktrf', DEV['mktrf'])], min_n=36)
            pa = {k: P5A[k] for k in yj if k in P5A}
            e['ff5umd'] = reg(y, [('mktrf', DEV['mktrf'])] + [(f, DEV[f]) for f in ('smb', 'hml', 'rmw', 'cma', 'umd')], min_n=36)
        else:
            e['paper_reg'] = reg(yj, [('paper_active_P5', P5A), ('mktrf', MKTRF)], min_n=36)
            pa = {k: P5A[k] for k in yj if k in P5A}
            e['ind12'] = reg(y, [('mktrf', MKTRF)] + rel12, min_n=36)
            e['ff5umd'] = reg(y, ffx, min_n=36)
            e['sn60_loading'] = reg(yj, [('SN60', SN60)] + [('mktrf', MKTRF)] + rel12, min_n=36)
            e['sn60_loading'] = {kk: vv for kk, vv in (e['sn60_loading'] or {}).items() if kk != 'coef'} | (
                {'SN60_coef': e['sn60_loading']['coef']['SN60']} if e['sn60_loading'] else {})
            if e['ind12']:
                e['ind12']['coef'] = {c: v for c, v in e['ind12']['coef'].items()}
            e['diag_capping（判定なし）'] = reg(yj, [('paper_active_P5', P5A), ('cap_factor', CAPF), ('mktrf', MKTRF)], min_n=36)
        e['paper_same_months'] = mean_t(pa)
        e['gap_vs_paper'] = mean_t({k: yj[k] - pa[k] for k in pa})
        # 感度: 分配の取りこぼし疑いの月を欠測に
        fl = flags.get(base) or []
        if fl:
            bad = {d // 100 for d, _, _ in fl}
            e['hold_excluding_flagged_months'] = M.excess_stats({k: v for k, v in r.items() if k not in bad}, B, a=M.HOLD_START)
            e['flagged_months'] = sorted(bad)
        ev_R[t] = e

    # 検算: VFINX（S&P500 の投信）の Yahoo 年次と S&P500 総リターン
    vf = VM_RAW.get('VFINX', {})
    res['sanity']['vfinx_vs_sp500_tr_annual'] = {y: {'yahoo_raw': annual(vf, y), 'sp500_tr': v, 'diff': round(annual(vf, y) - v, 2) if annual(vf, y) is not None else None}
                                                 for y, v in SP500_TR.items()}
    # 事前登録どおりの生データ（直す前）での判定を別に残す（直した手段だけ）
    changed = sorted(set(split_fixes) | set(cut) | set(ms_fixed))
    raw_block = {}
    for t in changed:
        B, bname, _ = bench_of(t)
        r = {k: v for k, v in VM_RAW[t].items() if k in B}
        e = eval_series(r, B)
        raw_block[t] = {'from': min(r), 'full': e['full'], 'train': e['train'], 'hold': e['hold'], 'roll20': e['roll20'],
                        'grade_without_holm': M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['hold'])[0]}
    res['as_registered_raw_data（直す前の Yahoo 生データ・判定には使わない）'] = raw_block

    fam_of = {t: FAMILY_OF_GROUP.get(e['group'], 'R') for t, e in ev_R.items()}
    holm_by = {}
    for fam in ('R', 'E_LF', 'E_MEGA'):
        holm_by.update(M.holm({t: (ev_R[t]['hold'] or {}).get('p') for t in ev_R if fam_of[t] == fam}))
    for t, e in ev_R.items():
        fam = fam_of[t]
        in_fam = fam != 'SANITY'
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=None,
                       family_holm_p=holm_by.get(t) if in_fam else None)
        tested.append({'id': t, 'family': fam, 'primary': fam == 'R', 'exploratory': fam.startswith('E_'),
                       'stage': 2 if fam.startswith('E_') or e['group'] == 'E_SANITY' else 1, 'group': e['group'],
                       'desc': f"実在の手段 {t}（{e['group']}）対 {e['bench']}", 'unit_cost': 0.0, 'turnover_oneway_per_year_hold': 0.0,
                       **{k: v for k, v in e.items() if k not in ('group',)}, 'holm_p_hold': holm_by.get(t) if in_fam else None,
                       'grade': g, 'criteria': c})

    # ── P_ref（再掲・族外）
    PREF = {k: (v, {'P5_QUAL5': 0.84, 'P6_FR_OP_HI30': 0.5}.get(k, 0.5)) for k, v in PAP.items()}
    PREF['P5_QUAL5_vw_cap'] = (P5_cap, 0.84)
    PREF['P5_QUAL5_ew'] = (P5_ew, 0.84)
    pref_ev = {}
    for k, (ex_, to) in PREF.items():
        net = M.apply_cost(ex_, to, 0.002)
        tot = to_total(ex_)
        o = {'full': M.excess_stats(ex_, MKTRF), 'train': M.excess_stats(ex_, MKTRF, z=M.TRAIN_END), 'hold': M.excess_stats(ex_, MKTRF, a=M.HOLD_START),
             'recent': M.excess_stats(ex_, MKTRF, a=M.RECENT_START), 'cost_hold': M.excess_stats(net, MKTRF, a=M.HOLD_START),
             'roll20': M.rolling(tot, MKT, 20), 'dca20': M.dca(tot, MKT, 20), 'turnover': to}
        pref_ev[k] = o
    dev_o = {'full': M.excess_stats(P5_dev, JKP_DEV), 'train': M.excess_stats(P5_dev, JKP_DEV, z=M.TRAIN_END),
             'hold': M.excess_stats(P5_dev, JKP_DEV, a=M.HOLD_START), 'recent': M.excess_stats(P5_dev, JKP_DEV, a=M.RECENT_START)}
    dev_o['cost_hold'] = M.excess_stats(M.apply_cost(P5_dev, 0.84, 0.002), JKP_DEV, a=M.HOLD_START)
    dev_o['roll20'] = M.rolling(P5_dev, JKP_DEV, 20); dev_o['dca20'] = None; dev_o['turnover'] = 0.84
    pref_ev['P5_QUAL5_developed'] = dev_o
    holm_P = M.holm({k: (o['hold'] or {}).get('p') for k, o in pref_ev.items()})
    for k, o in pref_ev.items():
        g, c = M.grade(o['full'], o['train'], o['hold'], o['roll20'], cost_hold=o['cost_hold'], repl=None, family_holm_p=holm_P.get(k))
        tested.append({'id': k, 'family': 'P_ref', 'primary': False, 'exploratory': False, 'desc': '紙の再掲（他の角度で判定済み・または診断）',
                       **o, 'unit_cost': 0.002, 'holm_p_hold': holm_P.get(k), 'grade': g, 'criteria': c})

    res['tested'] = tested
    res['n_tested'] = len(tested)
    FAMS = ('R', 'I', 'E_LF', 'E_MEGA', 'P_ref', 'SANITY')
    res['n_tested_by_family'] = {f: sum(1 for x in tested if x['family'] == f) for f in FAMS}
    res['grade_counts'] = {f: {g: sum(1 for x in tested if x['family'] == f and x['grade'] == g) for g in 'SABC'} for f in FAMS}
    res['preregs'] = {'1': {'file': f'out/{PRE_NAME}', 'commit': sha_of(f'out/{PRE_NAME}'), 'families': ['R（主）', 'I（主）', 'P_ref（族外）']},
                      '2': {'file': f'out/{PRE2_NAME}', 'commit': sha_of(f'out/{PRE2_NAME}'), 'families': ['E_LF（探索）', 'E_MEGA（探索）'], 'exploratory': True}}

    # ── 事前登録の読み方（R1〜R7）
    res['rules'] = rules(res, p1, cov, ev_R, tested)
    return res


def rules(res, p1, cov, ev_R, tested):
    o = {}
    h = p1['P5_QUAL5']['hold']
    raw = h['M0_raw']['alpha_ann']

    def lab(m):
        a, t = m['alpha_ann'], m['alpha_t_nw']
        if a <= 0.5 * raw and (t or 0) < 1.65:
            return '保有期間の上乗せは主に業種の傾き'
        if a >= 0.5 * raw and (t or 0) >= 1.65:
            return '業種を除いても残る'
        return '一部が業種'
    o['R1_industry_12'] = {'raw_hold': raw, 'alpha_hold': h['M2_ind12']['alpha_ann'], 't': h['M2_ind12']['alpha_t_nw'], 'reading': lab(h['M2_ind12'])}
    o['R1_industry_49（副）'] = {'alpha_hold': h['M3_ind49']['alpha_ann'], 't': h['M3_ind49']['alpha_t_nw'], 'reading': lab(h['M3_ind49'])}
    o['R2_factors'] = {'alpha_hold': h['M4_ff5umd']['alpha_ann'], 't': h['M4_ff5umd']['alpha_t_nw'],
                       'reading': '既知の因子（RMW 等）で説明される' if (h['M4_ff5umd']['alpha_t_nw'] or 0) < 1.65 else '既知の因子を除いても残る'}
    o['R3_coverage'] = {k: v['R3_coverage_bias'] for k, v in cov.items()}
    cp = res['part1_capping']
    vw_h, cap_h = cp['P5_vw']['hold']['ex_ann'], cp['P5_vw_cap']['hold']['ex_ann']
    o['R4_capping'] = {'vw_hold': vw_h, 'vw_cap_hold': cap_h, 'reading': '巨大株に上限を掛けると上乗せの半分以上が消える' if cap_h <= 0.5 * vw_h else '上限を掛けても半分以上残る'}
    ex_h = h['vs_exfin_market_total']['ex_ann']
    o['R5_exfin'] = {'vs_exfin_hold': ex_h, 'vs_mkt_hold': raw, 'reading': '金融を避けた効果では説明されない' if ex_h >= 0.5 * raw else '金融を避けた効果が半分以上'}
    cap = []
    for x in tested:
        if x['family'] != 'R':
            continue
        hd, pr = x.get('hold') or {}, x.get('paper_reg') or {}
        cf = (pr.get('coef') or {})
        b = next((v for k, v in cf.items() if k.startswith('paper_active')), None)
        ok = bool(hd and hd['ex_ann'] > 0 and (hd['t'] or 0) >= 1.65 and b and b[0] >= 0.5 and (b[1] or 0) >= 2 and x['grade'] in ('S', 'A', 'B'))
        if ok:
            cap.append({'id': x['id'], 'grade': x['grade'], 'hold_ex': hd['ex_ann'], 'hold_t': hd['t'], 'loading': b, 'C7': x['criteria']['C7_multi']})
    o['R6_captured'] = cap
    sn = res['part3_sector_neutral']['SN60']['hold']
    q = next((x for x in tested if x['id'] == 'QUAL'), None)
    o['R7_sector_neutral'] = {'SN60_hold': sn, 'QUAL_hold': (q or {}).get('hold'),
                              'reading': '業種中立にすると紙の上でも上乗せは統計的に残らない' if sn and (sn['t_nw'] or 0) < 1.65 else '業種中立でも紙の上では残る'}
    iA = [x['id'] for x in tested if x['family'] == 'I' and x['grade'] in ('S', 'A')]
    rA = [c['id'] for c in cap if c['C7']]
    o['verdict'] = {'I_family_A_or_better': iA, 'R6_with_C7': rA,
                    'reading': '実在・買いだけで市場に勝つ質の上乗せを取る方法がある' if (iA or rA) else 'この角度では見つからない（実在・買いだけで紙の質の上乗せを多重検定込みで取った手段は無い）'}
    return o


def brief(res):
    print(json.dumps(res['sanity'], ensure_ascii=False)[:1500])
    for x in res['tested']:
        f, tr, h, c = x.get('full') or {}, x.get('train') or {}, x.get('hold') or {}, x.get('cost_hold') or {}
        r20 = (x.get('roll20') or {}).get('win_rate')
        pr = (x.get('paper_reg') or {})
        b = next((v for k, v in (pr.get('coef') or {}).items() if k.startswith('paper_active')), None)
        print(f"{x['family']:6s} {x['id']:22s} {x['grade']} full {f.get('ex_ann', 0):6.2f} t{f.get('t') or 0:5.2f} | tr {tr.get('ex_ann', 0):6.2f} t{tr.get('t') or 0:5.2f} "
              f"| ho {h.get('ex_ann', 0):6.2f} t{h.get('t') or 0:5.2f} g{h.get('cagr_diff', 0):6.2f} | net {c.get('ex_ann', 0):6.2f} | r20 {r20} | holm {x.get('holm_p_hold')} | b {b} a {pr.get('alpha_ann')} t{pr.get('alpha_t_nw')}")
    print(json.dumps(res['rules'], ensure_ascii=False, indent=1)[:4000])


if __name__ == '__main__':
    res = main()
    p = M.save(OUT_NAME, res)
    brief(res)
    print('saved', p, os.path.getsize(p))
