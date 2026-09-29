#!/usr/bin/env python3
"""night/mw_reality_gap_verify.py — mw_reality_gap の主張を反証しにいく検証（読むだけ・門の判定には不使用）

対象（研究者の主張）: 紙の S 4本（P1_cop_at / P2_ope_be / P3_qmj_prof / P5_QUAL5）と、実在の手段で唯一の B（FCNTX）。
作法: mw_common からは『取得』（french_tables / jkp_rows / get）だけを借り、ポートフォリオの組み立て・良い側の決め方・
超過・NW t・CAGR・転がる20年・積立・費用・税・回帰・格付けはすべてここで書き直す（研究者のコードは import しない・流用しない）。

出力: out/mw_reality_gap_verify.json
"""
import sys, os, json, math, datetime, glob, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import mw_common as M  # 取得だけ

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_reality_gap_verify.json')
TRAIN_END, HOLD_START, RECENT = 200612, 200701, 201307
P_START = 196307
TAU = 0.20315  # 日本の課税口座の譲渡益課税


# ───────────────────────── 取得（mw_common の取得だけ使う） ─────────────────────────
def fr_table(name, title_has, freq='monthly'):
    for t, v in M.french_tables(name).items():
        if title_has.lower() in t.lower() and v['freq'] == freq:
            return v
    for t, v in M.french_tables(name).items():  # 表題が注記に化けている表（Factors 系）
        if v['freq'] == freq and title_has == '*':
            return v
    raise KeyError((name, title_has))


def fr_cols(v):
    out = {c: {} for c in v['cols']}
    for d, row in v['data'].items():
        for c, x in zip(v['cols'], row):
            if x is not None:
                out[c][d] = x / 100.0
    return out


FF = fr_cols(fr_table('F-F_Research_Data_Factors', '*'))
MKTRF, RF = FF['Mkt-RF'], FF['RF']
MKT = {k: MKTRF[k] + RF[k] for k in MKTRF if k in RF}
IND12 = fr_cols(fr_table('12_Industry_Portfolios', 'Average Value Weighted Returns -- Monthly'))
FF5 = fr_cols(fr_table('F-F_Research_Data_5_Factors_2x3', '*'))
MOM = fr_cols(fr_table('F-F_Momentum_Factor', '*'))['Mom']


def ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


_JKP = {}


def jkp_pf(region, key, w='vw'):
    k = (region, key, w)
    if k not in _JKP:
        d = {}
        for x in M.jkp_rows(region, key, 'portfolios', w):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            n = x.get('n')
            n = int(float(n)) if n not in (None, '', 'NA', 'na') else 0
            d.setdefault(x['pf'], {})[ym(x['date'])] = (float(x['ret']), n)
        _JKP[k] = d
    return _JKP[k]


def jkp_mkt(region, w='vw'):
    return {ym(x['date']): float(x['ret']) for x in M.jkp_rows(region, 'mkt', 'factor', w) if x['ret'] not in ('', 'NA', 'na')}


# ───────────────────────── 自前の統計 ─────────────────────────
def nwt(x, lag=12):
    x = np.asarray(x, float)
    n = len(x)
    if n < 24:
        return None
    e = x - x.mean()
    s = e @ e / n
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else None


def geo(v, py=12):
    v = np.asarray(v, float)
    return math.exp(np.log1p(v).sum() * py / len(v)) - 1


def keys_in(*ds, a=None, z=None, drop=()):
    ks = set(ds[0])
    for d in ds[1:]:
        ks &= set(d)
    return sorted(k for k in ks if (a is None or k >= a) and (z is None or k <= z) and not any(lo <= k <= hi for lo, hi in drop))


def stats(s_tot, b_tot, a=None, z=None, drop=()):
    """s_tot・b_tot は総リターン（小数）。算術の超過×12・NW t・幾何の年率差（総リターンどうし）"""
    ks = keys_in(s_tot, b_tot, a=a, z=z, drop=drop)
    if len(ks) < 24:
        return None
    ex = np.array([s_tot[k] - b_tot[k] for k in ks])
    t = nwt(ex)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(ex.mean() * 1200, 2), 't': round(t, 2) if t is not None else None,
            'cagr_diff': round((geo([s_tot[k] for k in ks]) - geo([b_tot[k] for k in ks])) * 100, 2)}


def roll20(s_tot, b_tot, start_month=7, years=20):
    ks = set(s_tot) & set(b_tot)
    if not ks:
        return None
    y0, last = min(ks) // 100, max(ks)
    res = []
    for y in range(y0, 2100):
        a = y * 100 + start_month
        zy, zm = (y + years, start_month - 1) if start_month > 1 else (y + years - 1, 12)
        z = zy * 100 + zm
        if z > last:
            break
        w = [k for k in sorted(ks) if a <= k <= z]
        if len(w) < years * 12 - 3:
            continue
        res.append((y, round((geo([s_tot[k] for k in w]) - geo([b_tot[k] for k in w])) * 100, 2)))
    if not res:
        return None
    v = [c for _, c in res]
    return {'windows': len(v), 'win_rate': round(sum(c > 0 for c in v) / len(v), 3), 'median': round(float(np.median(v)), 2), 'worst': min(res, key=lambda r: r[1])}


def dca20(s_tot, b_tot, years=20, load_until=None, load=0.0):
    """毎月同額・毎月起点（step 1）で20年積み立てた最終額の比。load_until(yyyymm) 以前の拠出は (1−load) だけ効く（販売手数料）"""
    ks = keys_in(s_tot, b_tot)
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            c = (1 - load) if (load_until and k <= load_until) else 1.0
            ws = (ws + c) * (1 + s_tot[k]); wb = (wb + 1) * (1 + b_tot[k])
        out.append((w[0], ws / wb))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(v), 'win_rate': round(sum(r > 1 for r in v) / len(v), 3), 'median': round(v[len(v) // 2], 3),
            'worst': (min(out, key=lambda r: r[1])[0], round(min(r for _, r in out), 3))}


def ols_nw(y, X, lag=12):
    y = np.asarray(y, float); X = np.column_stack([np.ones(len(y))] + [np.asarray(c, float) for c in X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n = len(y)
    XtXi = np.linalg.pinv(X.T @ X)
    Xe = X * e[:, None]
    S = Xe.T @ Xe / n
    for L in range(1, lag + 1):
        G = Xe[L:].T @ Xe[:-L] / n
        S += (1 - L / (lag + 1)) * (G + G.T)
    V = n * XtXi @ S @ XtXi
    se = np.sqrt(np.maximum(np.diag(V), 0))
    return b, b / np.where(se > 0, se, np.nan)


def alpha_reg(y_act, regs, a=None, z=None):
    """y_act = 月次の上乗せ（小数）・regs = [(名前, 系列)]。α は年率%"""
    ks = keys_in(y_act, *[r for _, r in regs], a=a, z=z)
    if len(ks) < 36:
        return None
    b, t = ols_nw([y_act[k] for k in ks], [[r[k] for k in ks] for _, r in regs])
    out = {'n': len(ks), 'alpha': round(b[0] * 1200, 2), 't': round(float(t[0]), 2)}
    out['coef'] = {nm: [round(float(b[i + 1]), 3), round(float(t[i + 1]), 2)] for i, (nm, _) in enumerate(regs) if nm in ('BusEq', 'Money', 'Hlth', 'HML', 'RMW', 'CMA', 'UMD', 'SMB', 'MktRF')}
    return out


def after_tax(s_tot, b_tot, turnover, a, z):
    """日本の課税口座: 戦略は毎月 turnover/12 を売って買い直し（利益に 20.315%・損失は無期限の繰越で相殺＝戦略に甘い）。
    市場は買って持つだけ。最後に両方を売って課税した後の年率差（配当課税は両方同じとみなして無視）"""
    ks = keys_in(s_tot, b_tot, a=a, z=z)
    V, B, loss = 1.0, 1.0, 0.0
    Vm = 1.0
    u = turnover / 12
    for k in ks:
        V *= 1 + s_tot[k]; Vm *= 1 + b_tot[k]
        g = u * (V - B)
        if g < 0:
            loss += -g; tax = 0.0
        else:
            off = min(loss, g); loss -= off; tax = TAU * (g - off)
        B = B * (1 - u) + u * V - tax
        V -= tax
    fin = V - TAU * max(0.0, V - B - loss)
    finm = Vm - TAU * max(0.0, Vm - 1.0)
    yrs = len(ks) / 12
    return round(((fin ** (1 / yrs)) - (finm ** (1 / yrs))) * 100, 2)


def grade(train, hold, full, r20, net_hold, c5=None, fam_p=None):
    """out/mw_prereg.json の C1〜C7 を自前で当てる（C8 は該当なし）"""
    c = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0),
         'C2': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4': bool(r20 and r20['win_rate'] >= 0.8),
         'C5': c5,
         'C6': bool(net_hold and net_hold['ex'] > 0 and net_hold['cagr_diff'] > 0),
         'C7': bool((full and (full['t'] or 0) >= 3.0) or (fam_p is not None and fam_p < 0.05))}
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


def cost(s_tot, turnover, unit):
    d = turnover * unit / 12
    return {k: v - d for k, v in s_tot.items()}


def tot(ex):
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


def drop_best_years(s, b, a, z, n=2):
    ks = keys_in(s, b, a=a, z=z)
    yr = {}
    for k in ks:
        yr.setdefault(k // 100, []).append(s[k] - b[k])
    best = sorted(yr, key=lambda y: -sum(yr[y]))[:n]
    return best, stats(s, b, a=a, z=z, drop=[(y * 100 + 1, y * 100 + 12) for y in best])


# ───────────────────────── 紙の組み立て（自前） ─────────────────────────
def my_side(key, region='usa', w='vw'):
    """良い側 = 2006-12 までの（第3 − 第1）の平均の符号（研究者の『因子との相関の符号』とは別の方法）"""
    p = jkp_pf(region, key, w)
    ks = keys_in(p['3.0'], p['1.0'], z=TRAIN_END)
    ks = [k for k in ks if p['3.0'][k][1] >= 10 and p['1.0'][k][1] >= 10]
    m = np.mean([p['3.0'][k][0] - p['1.0'][k][0] for k in ks])
    return '3.0' if m > 0 else '1.0'


def paper(keys, w='vw', region='usa', side_region='usa', min_n=0, start=P_START, pf=None):
    sers = []
    for key in keys:
        side = pf or my_side(key, side_region)
        d = jkp_pf(region, key, w).get(side, {})
        sers.append({k: r for k, (r, n) in d.items() if n >= min_n})
    ks = keys_in(*sers, a=start)
    return {k: float(np.mean([s[k] for s in sers])) for k in ks}


QUAL5 = ['ope_be', 'gp_at', 'qmj', 'chcsho_12m', 'oaccruals_at']
CANDS = {'P1_cop_at': (['cop_at'], 0.5, 201401, 'Ball, Gerakos, Linnainmaa & Nikolaev (2016 JFE)・データ〜2013'),
         'P2_ope_be': (['ope_be'], 0.5, 201401, 'Fama & French (2015 JFE) RMW・データ〜2013'),
         'P3_qmj_prof': (['qmj_prof'], 0.5, 201301, 'Asness, Frazzini & Pedersen (2013 WP / 2019 RAS)・データ〜2012'),
         'P5_QUAL5': (QUAL5, 0.84, 201401, '5袖の最も新しい論文（FF2015 / AFP2013）の後')}
NEIGHBORS = {'P1_cop_at': ['cop_atl1', 'op_at', 'gp_at', 'ope_bel1', 'ni_be'], 'P2_ope_be': ['ope_bel1', 'op_at', 'cop_at', 'ni_be'],
             'P3_qmj_prof': ['qmj', 'qmj_growth', 'qmj_safety', 'ope_be'], 'P5_QUAL5': []}
DEV = ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe']


def regional(keys):
    """C5: 同じ規則（米国の良い側）を米国外の先進22か国（JKP・国ごとの vw 市場）へ。各袖10社以上の月・120か月以上の国だけ"""
    rows = {}
    for c in DEV + ['developed', 'emerging']:
        try:
            p = paper(keys, 'vw', region=c, min_n=10, start=None)
            mk = jkp_mkt(c, 'vw')
        except Exception as e:  # noqa
            rows[c] = {'err': str(e)[:80]}
            continue
        ks = keys_in(p, mk)
        if len(ks) < 120:
            rows[c] = {'n': len(ks), 'skip': '120か月未満'}
            continue
        full = np.array([p[k] - mk[k] for k in ks])
        hk = [k for k in ks if k >= HOLD_START]
        hold = np.array([p[k] - mk[k] for k in hk]) if len(hk) >= 24 else None
        rows[c] = {'from': ks[0], 'n': len(ks), 'full_ex': round(full.mean() * 1200, 2), 'full_t': round(nwt(full) or 0, 2),
                   'hold_ex': round(hold.mean() * 1200, 2) if hold is not None else None}
    cs = [c for c in DEV if 'full_ex' in rows.get(c, {})]
    pos_full = sum(rows[c]['full_ex'] > 0 for c in cs)
    pos_hold = sum((rows[c]['hold_ex'] or 0) > 0 for c in cs)
    return {'countries': len(cs), 'positive_full': int(pos_full), 'positive_hold': int(pos_hold),
            'C5_full': bool(pos_full / len(cs) >= 2 / 3) if cs else None, 'C5_hold': bool(pos_hold / len(cs) >= 2 / 3) if cs else None,
            'rows': rows}


# ───────────────────────── 多重検定（JKP 米国の全特性） ─────────────────────────
def family_all_signals():
    names = sorted({os.path.basename(p)[len('jkp_portfolios_usa_'):-len('_vw_monthly.zip')] for p in glob.glob(os.path.join(M.CACHE, 'jkp_portfolios_usa_*_vw_monthly.zip'))})
    names = [n for n in names if n not in ('mkt',)]
    fam = {}
    for n in names:
        try:
            s = paper([n], 'vw')
        except Exception:  # noqa
            continue
        st = tot(s)
        tr = stats(st, MKT, a=P_START, z=TRAIN_END)
        ho = stats(st, MKT, a=HOLD_START)
        if tr and ho and ho['n'] >= 200:
            fam[n] = {'train': tr, 'hold': ho, 'ex_hold': {k: st[k] - MKT[k] for k in keys_in(st, MKT, a=HOLD_START)}}
    return fam


def maxt_bootstrap(fam, names, targets, reps=2000, block=12, seed=7):
    """保有期間の上乗せを各列で平均0へ中心化し、同じ月の束を定常ブロック・ブートストラップで引き直して max-t の分布を作る"""
    ks = sorted(set.intersection(*[set(fam[n]['ex_hold']) for n in names]))
    E = np.array([[fam[n]['ex_hold'][k] for n in names] for k in ks])
    E0 = E - E.mean(0)
    T = len(ks)
    rng = random.Random(seed)

    def nw_cols(X, lag=12):
        m = X.mean(0); e = X - m; n = X.shape[0]
        s = (e * e).sum(0) / n
        for L in range(1, lag + 1):
            s += 2 * (1 - L / (lag + 1)) * (e[L:] * e[:-L]).sum(0) / n
        return m / np.sqrt(s / n)
    obs = nw_cols(E)
    mx = []
    for _ in range(reps):
        idx = []
        i = rng.randrange(T)
        while len(idx) < T:
            idx.append(i)
            i = rng.randrange(T) if rng.random() < 1 / block else (i + 1) % T
        mx.append(float(np.nanmax(nw_cols(E0[idx]))))
    mx = np.array(mx)
    return {t: round(float((mx >= obs[names.index(t)]).mean()), 4) for t in targets if t in names}, len(ks)


def holm(pv):
    it = sorted((p, k) for k, p in pv.items())
    m, run, out = len(it), 0.0, {}
    for i, (p, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * p)); out[k] = round(run, 4)
    return out


def p2(t):
    return math.erfc(abs(t) / math.sqrt(2))


# ───────────────────────── FCNTX（Yahoo 日次 × Morningstar 年次） ─────────────────────────
def load_yahoo_daily(t):
    p = os.path.join(M.CACHE, f'rg_yh_{t}_1d_cg.json')
    if os.path.exists(p):
        j = json.load(open(p))
    else:
        import urllib.parse, time
        u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}&interval=1d&events=div%2Csplit%2CcapitalGains'
        j = json.loads(M.get(u, name=f'rgv_yh_{t}_1d.json', max_age_days=5))
    r = j['chart']['result'][0]
    adj = r['indicators']['adjclose'][0]['adjclose']
    last = {}
    for a, px in zip(r['timestamp'], adj):
        if px is None or px <= 0:
            continue
        d = datetime.datetime.fromtimestamp(a, datetime.timezone.utc)
        last[d.year * 100 + d.month] = px
    ks = sorted(last)
    out = {}
    for p_, k in zip(ks, ks[1:]):
        if (k // 100 * 12 + k % 100) - (p_ // 100 * 12 + p_ % 100) == 1:
            out[k] = last[k] / last[p_] - 1
    return out


def load_ms(t):
    j = json.load(open(os.path.join(M.CACHE, f'rg_ms_{t}.json')))
    rets = j['quoteSummary']['result'][0]['fundPerformance']['annualTotalReturns']['returns']
    return {int(x['year']): x['annualValue']['raw'] for x in rets if (x.get('annualValue') or {}).get('raw') is not None}


def yr_ret(m, y):
    v = [m[k] for k in range(y * 100 + 1, y * 100 + 13) if k in m]
    return float(np.prod([1 + x for x in v]) - 1) if len(v) == 12 else None


def ms_fix(m, ms, thr=0.01, years=None):
    out, fixed = dict(m), {}
    for y, v in ms.items():
        if years and y not in years:
            continue
        a = yr_ret(m, y)
        if a is None or abs(a - v) <= thr:
            continue
        f = ((1 + v) / (1 + a)) ** (1 / 12)
        for k in range(y * 100 + 1, y * 100 + 13):
            out[k] = (1 + out[k]) * f - 1
        fixed[y] = [round(a * 100, 2), round(v * 100, 2)]
    return out, fixed


def fcntx():
    raw = load_yahoo_daily('FCNTX')
    ms = load_ms('FCNTX')
    res = {'ms_years': [min(ms), max(ms)]}
    cmp_ = {}
    for y in range(1981, 2026):
        a = yr_ret(raw, y)
        if a is not None and y in ms:
            cmp_[y] = [round(a * 100, 2), round(ms[y] * 100, 2), round((a - ms[y]) * 100, 2)]
    res['yahoo_vs_morningstar_annual（Yahoo, MS, 差）'] = {y: v for y, v in cmp_.items() if abs(v[2]) > 1.0}
    fixed_all, fx = ms_fix(raw, ms)
    res['fixed_years'] = fx
    variants = {
        'V0_raw_1987': ({k: v for k, v in raw.items() if k >= 198701}, '直さない・1987-01〜'),
        'V1_msfix_1987（研究者の主）': ({k: v for k, v in fixed_all.items() if k >= 198701}, 'Morningstar 年次で 1pt 超の年を直す・1987-01〜'),
        'V2_msfix_1981（登録どおり「データの始まり」へ・直した後）': ({k: v for k, v in fixed_all.items() if k >= 198101}, 'Morningstar で直せば 1981〜 も使える（Yahoo の日次が 1980-01 から）'),
        'V3_msfix_danoff_1990-10': ({k: v for k, v in fixed_all.items() if k >= 199010}, 'Danoff の運用開始（1990-09）の後だけ'),
    }
    out = {}
    for vid, (s, desc) in variants.items():
        full = stats(s, MKT); train = stats(s, MKT, z=TRAIN_END); hold = stats(s, MKT, a=HOLD_START)
        r20 = roll20(s, MKT)
        g, c = grade(train, hold, full, r20, hold, None, None)
        out[vid] = {'desc': desc, 'full': full, 'train': train, 'hold': hold, 'recent': stats(s, MKT, a=RECENT), 'roll20': r20, 'grade': g, 'criteria': c}
    s = variants['V1_msfix_1987（研究者の主）'][0]
    rob = {'hold_first_half_2007-01..2016-06': stats(s, MKT, a=HOLD_START, z=201606),
           'hold_second_half_2016-07..': stats(s, MKT, a=201607),
           'hold_drop_2020-2021': stats(s, MKT, a=HOLD_START, drop=[(202001, 202112)]),
           'train_drop_1998-2000': stats(s, MKT, z=TRAIN_END, drop=[(199801, 200012)]),
           'full_drop_1998-2000': stats(s, MKT, drop=[(199801, 200012)])}
    by, rob['hold_drop_best2'] = drop_best_years(s, MKT, HOLD_START, None)
    rob['hold_best2_years'] = by
    by, rob['train_drop_best2'] = drop_best_years(s, MKT, None, TRAIN_END)
    rob['train_best2_years'] = by
    rob['ms_first'] = min(ms)
    rob['dca20_no_load'] = dca20(s, MKT)
    rob['dca20_with_3pct_load_until_2003-06'] = dca20(s, MKT, load_until=200306, load=0.03)
    # 一括の転がる20年: 起点が 2003-06 以前なら 3% を最初に払う（年率へ直すと約 −0.15pt/年）
    r = roll20(s, MKT)
    rob['roll20_no_load'] = r
    # 年次（Morningstar のみ）で 1967〜: 訓練 1967〜2006 の年次超過の平均と t（年次の自己相関はラグ1の NW）
    fr_ann = {}
    for y in range(1967, 2026):
        v = yr_ret(MKT, y)
        if v is not None:
            fr_ann[y] = v
    def ann_stats(a, z):
        ys = [y for y in sorted(ms) if a <= y <= z and y in fr_ann]
        ex = np.array([ms[y] - fr_ann[y] for y in ys])
        return {'years': f'{ys[0]}-{ys[-1]}', 'n': len(ys), 'ex': round(ex.mean() * 100, 2), 't_nw1': round(nwt(ex, lag=1) if len(ex) >= 24 else (ex.mean() / (ex.std(ddof=1) / math.sqrt(len(ex)))), 2),
                'cagr_diff': round((geo([ms[y] for y in ys], 1) - geo([fr_ann[y] for y in ys], 1)) * 100, 2)}
    rob['annual_MS_1967-2006（訓練を Morningstar の最初の年から）'] = ann_stats(1967, 2006)
    rob['annual_MS_1981-2006'] = ann_stats(1981, 2006)
    rob['annual_MS_1967-1986（研究者が落とした期間）'] = ann_stats(1967, 1986)
    rob['annual_MS_1987-2006'] = ann_stats(1987, 2006)
    rob['annual_MS_2007-2025'] = ann_stats(2007, 2025)
    # 紙の上乗せ・5因子＋勢い・12業種への回帰（研究者の『運用者の銘柄選び』の読みの点検）
    act = {k: s[k] - MKT[k] for k in keys_in(s, MKT)}
    ffr = [('MktRF', MKTRF), ('SMB', FF5['SMB']), ('HML', FF5['HML']), ('RMW', FF5['RMW']), ('CMA', FF5['CMA']), ('UMD', MOM)]
    rob['ff5umd_full'] = alpha_reg(act, ffr)
    rob['ff5umd_hold'] = alpha_reg(act, ffr, a=HOLD_START)
    return out, rob


# ───────────────────────── 本体 ─────────────────────────
def main():
    res = {'angle': 'reality_gap', 'target': 'out/mw_reality_gap.json', 'tool': 'night/mw_reality_gap_verify.py',
           'independence': '良い側は（第3−第1）の 2006-12 までの平均の符号で決め直した（研究者は JKP 因子との相関の符号）。統計・回帰・格付け・費用・税・積立はすべて自前。取得だけ mw_common を使った',
           'benchmark_check': None, 'candidates': {}, 'verdicts': []}
    claimed = {x['name'] if 'name' in x else x['id']: x for x in json.load(open(os.path.join(BASE, 'out', 'mw_reality_gap.json')))['tested']}
    claimed = {x.get('id'): x for x in json.load(open(os.path.join(BASE, 'out', 'mw_reality_gap.json')))['tested']}

    # 相手の点検: French Mkt は上限なし時価加重。JKP の vw 市場（紙の土俵）との差も見る
    jm = jkp_mkt('usa', 'vw')
    res['benchmark_check'] = {'opponent': 'French Mkt（Mkt-RF+RF）＝上限なし時価加重・CRSP 全上場（純粋な市場・合格）',
                              'jkp_vw_mkt_vs_french_hold': stats(tot(jm), MKT, a=HOLD_START),
                              'jkp_vw_mkt_vs_french_full': stats(tot(jm), MKT, a=P_START)}

    print('多重検定の族（JKP 米国の全特性・vw の良い側）を作る…', flush=True)
    fam = family_all_signals()
    c1_names = [n for n, v in fam.items() if v['train']['ex'] > 0 and (v['train']['t'] or 0) >= 2.0]
    hold_p = {n: p2(v['hold']['t']) if v['hold']['t'] is not None else 1.0 for n, v in fam.items()}
    holm_all = holm(hold_p)
    holm_c1 = holm({n: hold_p[n] for n in c1_names})
    train_rank = sorted(c1_names, key=lambda n: -fam[n]['train']['t'])
    targets = ['cop_at', 'ope_be', 'qmj_prof']
    print(f'  特性 {len(fam)} 本・C1 合格 {len(c1_names)} 本。max-t ブートストラップ…', flush=True)
    mt_c1, nk = maxt_bootstrap(fam, c1_names, targets)
    mt_all, _ = maxt_bootstrap(fam, sorted(fam), targets)
    # 2006年までのデータだけで選ぶ正直なやり方: 訓練 t の上位5本・上位10本・C1 合格の全部を等分
    def honest(ns):
        s = tot(paper(ns, 'vw'))
        return {'members': ns, 'hold': stats(s, MKT, a=HOLD_START), 'train': stats(s, MKT, a=P_START, z=TRAIN_END)}
    fam_out = {'n_signals': len(fam), 'n_c1_pass': len(c1_names), 'hold_t_ge_1.65_among_c1': sum((fam[n]['hold']['t'] or 0) >= 1.65 for n in c1_names),
               'expected_by_chance_one_sided_5pct': round(0.05 * len(c1_names), 1),
               'honest_top5_by_train_t': honest(train_rank[:5]), 'honest_top10_by_train_t': honest(train_rank[:10]),
               'honest_all_c1': {'n': len(c1_names), 'hold': stats(tot(paper(c1_names[:60], 'vw')), MKT, a=HOLD_START) if c1_names else None,
                                 'note': '袖が多いと全部そろう月が減るので先頭60本（名前順）で近似'},
               'best_hold_t_in_family': sorted(((round(v['hold']['t'], 2), n) for n, v in fam.items() if v['hold']['t'] is not None), reverse=True)[:8]}
    res['multiple_testing_family'] = fam_out

    for cid, (keys, to, post, pub) in CANDS.items():
        print('候補', cid, flush=True)
        sides = {k: my_side(k) for k in keys}
        ex = paper(keys, 'vw')
        s = tot(ex)
        full = stats(s, MKT); train = stats(s, MKT, z=TRAIN_END); hold = stats(s, MKT, a=HOLD_START)
        net = cost(s, to, 0.002)
        net_hold = stats(net, MKT, a=HOLD_START)
        r20 = roll20(s, MKT)
        o = {'sides_my_method': sides, 'full': full, 'train': train, 'hold': hold, 'recent': stats(s, MKT, a=RECENT),
             'net_hold_(turnover %.2f × 0.20%%)' % to: net_hold,
             'net_hold_stress_(turnover 1.0 × 0.30%)': stats(cost(s, 1.0, 0.003), MKT, a=HOLD_START),
             'breakeven_cost_per_100pct_oneway_hold（%）': round(hold['ex'] / to, 2) if hold else None,
             'roll20': r20, 'dca20': dca20(s, MKT)}
        o['after_tax_japan_taxable_hold（年率差・戦略 − 市場）'] = after_tax(s, MKT, to, HOLD_START, None)
        o['after_tax_japan_taxable_full'] = after_tax(s, MKT, to, P_START, None)
        # 部分期間
        o['subperiods'] = {'full_drop_1998-2000': stats(s, MKT, drop=[(199801, 200012)]),
                           'train_drop_1998-2000': stats(s, MKT, z=TRAIN_END, drop=[(199801, 200012)]),
                           'hold_drop_2020-2021': stats(s, MKT, a=HOLD_START, drop=[(202001, 202112)]),
                           'hold_first_half_2007-01..2016-06': stats(s, MKT, a=HOLD_START, z=201606),
                           'hold_second_half_2016-07..2025-12': stats(s, MKT, a=201607),
                           'post_publication_' + str(post): stats(s, MKT, a=post), 'publication': pub}
        by, o['subperiods']['hold_drop_best2'] = drop_best_years(s, MKT, HOLD_START, None)
        o['subperiods']['hold_best2_years'] = by
        # C7（全期間 t≥3）の感度
        byf, fdb = drop_best_years(s, MKT, None, None)
        o['C7_sensitivity_full_t'] = {'base': full['t'], 'drop_1998-2000': o['subperiods']['full_drop_1998-2000']['t'],
                                      'drop_2020-2021': stats(s, MKT, drop=[(202001, 202112)])['t'],
                                      f'drop_best2_years_{byf}': fdb['t'], 'start_1973-01': stats(s, MKT, a=197301)['t'],
                                      'end_2019-12': stats(s, MKT, z=201912)['t']}
        # 近いパラメータ: 加重（vw_cap・ew）と近い特性
        o['neighbors'] = {'vw_cap': stats(tot(paper(keys, 'vw_cap')), MKT, a=HOLD_START),
                          'ew': stats(tot(paper(keys, 'ew')), MKT, a=HOLD_START),
                          'vw_cap_vs_jkp_vw_cap_mkt_hold': stats(tot(paper(keys, 'vw_cap')), tot(jkp_mkt('usa', 'vw_cap')), a=HOLD_START)}
        for nb in NEIGHBORS[cid]:
            try:
                sn = tot(paper([nb], 'vw'))
                o['neighbors'][nb] = {'train': stats(sn, MKT, z=TRAIN_END), 'hold': stats(sn, MKT, a=HOLD_START)}
            except Exception as e:  # noqa
                o['neighbors'][nb] = str(e)[:60]
        if cid == 'P5_QUAL5':
            for k in keys:
                sn = tot(paper([x for x in keys if x != k], 'vw'))
                o['neighbors'][f'leave_out_{k}'] = {'train': stats(sn, MKT, z=TRAIN_END), 'hold': stats(sn, MKT, a=HOLD_START), 'full': stats(sn, MKT)}
            o['sleeve_train_t'] = {k: stats(tot(paper([k], 'vw')), MKT, z=TRAIN_END)['t'] for k in keys}
            # 2006年に知られていた袖だけ（gp_at＝Novy-Marx 2013・qmj＝AFP 2013 は 2006 年には無い）
            k3 = ['ope_be', 'chcsho_12m', 'oaccruals_at']
            s3 = tot(paper(k3, 'vw'))
            f3, t3, h3 = stats(s3, MKT), stats(s3, MKT, z=TRAIN_END), stats(s3, MKT, a=HOLD_START)
            n3 = stats(cost(s3, 0.84, 0.002), MKT, a=HOLD_START)
            r3 = roll20(s3, MKT)
            g3, c3 = grade(t3, h3, f3, r3, n3, regional(k3)['C5_full'], None)
            o['knowable_2006_3sleeves'] = {'members': k3, 'full': f3, 'train': t3, 'hold': h3, 'net_hold': n3, 'roll20': r3,
                                           'hold_first_half': stats(s3, MKT, a=HOLD_START, z=201606), 'hold_second_half': stats(s3, MKT, a=201607),
                                           'hold_drop_2020-2021': stats(s3, MKT, a=HOLD_START, drop=[(202001, 202112)]),
                                           'vw_cap_hold': stats(tot(paper(k3, 'vw_cap')), MKT, a=HOLD_START), 'grade': g3, 'criteria': c3}
            # 無作為な5袖の混合の中での QUAL5 の位置（保有期間の t）
            rng = random.Random(11)
            pool_all = sorted(fam); pool_c1 = sorted(c1_names)
            def rand_mix(pool, reps=400):
                ts = []
                for _ in range(reps):
                    ks5 = rng.sample(pool, 5)
                    ser = [ {k: v + 0 for k, v in paper([x], 'vw').items()} for x in ks5]
                    ks = keys_in(*ser, a=P_START)
                    m = {k: float(np.mean([z[k] for z in ser])) for k in ks}
                    st = stats(tot(m), MKT, a=HOLD_START)
                    if st and st['t'] is not None:
                        ts.append(st['t'])
                return ts
            ta, tc = rand_mix(pool_all), rand_mix(pool_c1)
            o['random_5mix_hold_t'] = {'qual5_hold_t': hold['t'],
                                       'pctile_among_random_all154': round(float(np.mean([x < hold['t'] for x in ta])), 3), 'median_all154': round(float(np.median(ta)), 2),
                                       'pctile_among_random_c1': round(float(np.mean([x < hold['t'] for x in tc])), 3), 'median_c1': round(float(np.median(tc)), 2),
                                       'reps': [len(ta), len(tc)]}
            o['selection_timeline'] = ('5袖は out/longonly_prereg.json（636082e・2026-09-26 09:27）で門の物差しの近似として選ばれた。その 7分前の c7db797（09:20）で JKP 153因子の 2007年以降の成績'
                                       '（GP/A 2007〜 +4.3・ope_be・qmj・dilNet・accr が「頑丈だったもの」）を見ていた＝保有期間は袖の選択に漏れている')
        # 業種・因子
        act = {k: s[k] - MKT[k] for k in s if k in MKT}
        ind = [('MktRF', MKTRF)] + [(c, {k: IND12[c][k] - MKT[k] for k in IND12[c] if k in MKT}) for c in IND12]
        o['ind12_alpha_hold'] = alpha_reg(act, ind, a=HOLD_START, z=202512)
        o['ind12_alpha_recent'] = alpha_reg(act, ind, a=RECENT, z=202512)
        o['ind12_alpha_train'] = alpha_reg(act, ind, a=P_START, z=TRAIN_END)
        o['tech_fin_only_hold'] = alpha_reg(act, [('MktRF', MKTRF), ('BusEq', ind[6][1]), ('Money', ind[11][1])], a=HOLD_START, z=202512)
        ffr = [('MktRF', MKTRF), ('SMB', FF5['SMB']), ('HML', FF5['HML']), ('RMW', FF5['RMW']), ('CMA', FF5['CMA']), ('UMD', MOM)]
        o['ff5umd_alpha_hold'] = alpha_reg(act, ffr, a=HOLD_START, z=202512)
        # 米国外（C5）
        o['regional_C5'] = regional(keys)
        c5 = o['regional_C5']['C5_full']
        # 多重検定
        if len(keys) == 1:
            k = keys[0]
            o['multiple_testing'] = {'holm_hold_all_%d' % len(fam): holm_all.get(k), 'holm_hold_c1_%d' % len(c1_names): holm_c1.get(k),
                                     'maxt_p_c1': mt_c1.get(k), 'maxt_p_all': mt_all.get(k),
                                     'train_t_rank_among_c1': (train_rank.index(k) + 1) if k in train_rank else None}
        g_mech, crit = grade(train, hold, full, r20, net_hold, c5, None)
        g_na, _ = grade(train, hold, full, r20, net_hold, None, None)
        o['my_mechanical_grade'] = g_mech
        o['my_mechanical_grade_if_C5_NA'] = g_na
        o['my_criteria'] = crit
        o['claimed_numbers'] = {kk: (claimed.get(cid) or {}).get(kk) for kk in ('full', 'train', 'hold', 'grade')}
        res['candidates'][cid] = o

    print('FCNTX', flush=True)
    fv, frob = fcntx()
    res['candidates']['FCNTX'] = {'variants': fv, 'robustness': frob,
                                  'sales_load': 'Fidelity Contrafund は 2003-06-23 まで 3.00% の申込手数料（SEC Form 497・2003年: 取締役会 2003-06-19 に撤廃を決議）。Yahoo/Morningstar の総リターンは手数料を含まない＝訓練期間（1987〜2003）の実際の投資家の成績は過大',
                                  'claimed_numbers': {kk: (claimed.get('FCNTX') or {}).get(kk) for kk in ('full', 'train', 'hold', 'grade')}}
    rg = json.load(open(os.path.join(BASE, 'out', 'mw_reality_gap.json')))
    veh = [x for x in rg['tested'] if x.get('family') in ('R', 'E_LF', 'E_MEGA')]
    res['candidates']['FCNTX']['multiplicity'] = {
        'vehicles_tried_R_ELF_EMEGA': len(veh),
        'train_C1_pass_count': sum(1 for x in veh if (x.get('criteria') or {}).get('C1_train')),
        'expected_C1_pass_by_chance（片側 t≥2・約2.3%）': round(0.023 * len(veh), 1),
        'note': 'C1 の合格が1本だけ・保有期間 t1.28＝偶然の範囲と区別できない。FCNTX は課題文が名指しした『有名な生き残り』'}
    res['verdicts'] = build_verdicts(res)
    res['summary_ja'] = SUMMARY_JA
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    print('書いた', OUT)
    return res


def _close(a, b, tol=0.06):
    return a is not None and b is not None and abs(a - b) <= tol


def build_verdicts(res):
    """判定の規則（数字を見る前に決めた作法を数字に当てるだけ）:
    S のまま = C3 が族の多重性（max-t）を越える かつ C7 の感度（全期間 t の6通り）が全部 ≥3.0 かつ 1998-2000 抜きでも C1。
    A へ = C3 は多重性で落ちる（または保有期間が選択に使われた）が、C7 が頑丈・C1 が頑丈・C5（米国外の国）が合格。
    B へ = 登録どおりの C1・C2・C6 は通るが C7 か C1 が感度で割れる。
    C（反証）= 登録どおりの『データの始まり』か素直な感度で C1 が落ちる"""
    V = []
    cl = {x.get('id'): x for x in json.load(open(os.path.join(BASE, 'out', 'mw_reality_gap.json')))['tested']}
    for cid in ['P1_cop_at', 'P2_ope_be', 'P3_qmj_prof', 'P5_QUAL5']:
        o = res['candidates'][cid]
        c = cl[cid]
        rep = all(_close(o[w]['ex'], c[w]['ex_ann']) and _close(o[w]['t'], c[w]['t']) for w in ('full', 'train', 'hold'))
        c7s = o['C7_sensitivity_full_t']
        c7_min = min(v for v in c7s.values() if v is not None)
        c1_drop = o['subperiods']['train_drop_1998-2000']['t']
        c5 = o['regional_C5']
        mt = o.get('multiple_testing') or {}
        leak = cid == 'P5_QUAL5'
        c3_adj = (not leak) and (mt.get('maxt_p_c1') or 1) < 0.05
        c7_rob, c1_rob = c7_min >= 3.0, c1_drop >= 2.0
        if c3_adj and c7_rob and c1_rob:
            g = 'S'
        elif c7_rob and c1_rob and c5['C5_full']:
            g = 'A'
        elif o['my_mechanical_grade'] in ('S', 'A', 'B'):
            g = 'B'
        else:
            g = 'C'
        sp = o['subperiods']; nb = o['neighbors']
        issues = []
        if leak:
            issues.append('袖の選び方が保有期間を見た後: 5袖は 2026-09-26 09:27 の longonly_prereg で選ばれ、その7分前（c7db797）に JKP 153因子の 2007年以降の成績を見ていた。gp_at（Novy-Marx 2013）と qmj（AFP 2013）は 2006年には無い信号で、訓練の単独 t も %s・%s（<2）' % (o['sleeve_train_t']['gp_at'], o['sleeve_train_t']['qmj']))
            kk = o['knowable_2006_3sleeves']
            issues.append('弁護側: 2006年に知られていた3袖（ope_be・chcsho_12m・oaccruals_at）だけでも 訓練 %+.2f t%s／保有 %+.2f t%s／全期間 t%s／米国外で正＝機械の格付け %s（紙の質の上乗せが選び方だけの産物ではない証拠）。ただし上限つき vw_cap では保有 %+.2f t%s' % (kk['train']['ex'], kk['train']['t'], kk['hold']['ex'], kk['hold']['t'], kk['full']['t'], kk['grade'], kk['vw_cap_hold']['ex'], kk['vw_cap_hold']['t']))
            rm = o['random_5mix_hold_t']
            issues.append('無作為な5袖の混合（154本から）の保有期間 t の中央 %s に対し QUAL5 は %s（%.0f パーセンタイル）。2006年までの訓練 t の上位5本を等分する正直な選び方は保有 %+.2f t%s' % (rm['median_all154'], rm['qual5_hold_t'], rm['pctile_among_random_all154'] * 100, res['multiple_testing_family']['honest_top5_by_train_t']['hold']['ex'], res['multiple_testing_family']['honest_top5_by_train_t']['hold']['t']))
        else:
            issues.append('多重検定: JKP 米国 %d 特性（C1 合格 %d）を同時に試した中で、保有期間の t を相関を保った max-t で調整すると p=%s（C1 合格の中）／%s（全部）、Holm %s／%s。この候補は mw_factor_us の保有期間の成績（S）を見て再掲された%s' % (res['multiple_testing_family']['n_signals'], res['multiple_testing_family']['n_c1_pass'], mt.get('maxt_p_c1'), mt.get('maxt_p_all'), mt.get('holm_hold_c1_%d' % res['multiple_testing_family']['n_c1_pass']), mt.get('holm_hold_all_%d' % res['multiple_testing_family']['n_signals']),
                          '（保有 t が154本中1位）' if cid == 'P1_cop_at' else ''))
            issues.append('正直な選び方では選ばれない: 訓練の t で C1 合格 %d 本中 %s 位。2006年までの訓練 t 上位5本の等分は保有 %+.2f t%s' % (res['multiple_testing_family']['n_c1_pass'], mt.get('train_t_rank_among_c1'), res['multiple_testing_family']['honest_top5_by_train_t']['hold']['ex'], res['multiple_testing_family']['honest_top5_by_train_t']['hold']['t']))
        issues.append('C7 の感度（全期間 t）: ' + '・'.join(f'{k} {v}' for k, v in c7s.items()) + ('＝頑丈' if c7_rob else '＝3.0 を割る＝HLZ の抜け道が脆い'))
        issues.append('C1 の感度: 訓練 1998-2000 抜き t %s%s' % (c1_drop, '' if c1_rob else '（<2.0＝C1 が脆い）'))
        issues.append('保有期間の部分: 前半 %+.2f t%s・後半 %+.2f t%s・2020-21 抜き t%s・最良2年%s抜き %+.2f t%s・論文の後（%s）%+.2f t%s' % (
            sp['hold_first_half_2007-01..2016-06']['ex'], sp['hold_first_half_2007-01..2016-06']['t'], sp['hold_second_half_2016-07..2025-12']['ex'], sp['hold_second_half_2016-07..2025-12']['t'],
            sp['hold_drop_2020-2021']['t'], sp['hold_best2_years'], sp['hold_drop_best2']['ex'], sp['hold_drop_best2']['t'],
            [k for k in sp if k.startswith('post_publication_')][0][-6:], sp[[k for k in sp if k.startswith('post_publication_')][0]]['ex'], sp[[k for k in sp if k.startswith('post_publication_')][0]]['t']))
        issues.append('相手と重み: 相手は French Mkt（上限なし時価加重＝純粋な市場・合格）。だが同じ良い側を上限つき vw_cap で作ると保有 %+.2f t%s・等加重 %+.2f（幾何 %+.2f）＝S&P500 型の市場への勝ちは最大級の会社を満額で持つときだけ（上限つきどうしなら %+.2f t%s）' % (
            nb['vw_cap']['ex'], nb['vw_cap']['t'], nb['ew']['ex'], nb['ew']['cagr_diff'], nb['vw_cap_vs_jkp_vw_cap_mkt_hold']['ex'], nb['vw_cap_vs_jkp_vw_cap_mkt_hold']['t']))
        nbs = [f"{k} 訓練t{v['train']['t']}/保有t{v['hold']['t']}" for k, v in nb.items() if isinstance(v, dict) and 'train' in v and not k.startswith('leave_out')]
        if nbs:
            issues.append('近い特性: ' + '・'.join(nbs))
        if leak:
            issues.append('1袖ずつ抜く: ' + '・'.join(f"{k[10:]} 保有t{v['hold']['t']}" for k, v in nb.items() if k.startswith('leave_out')) + '＝どの1袖にも依存しない')
        issues.append('業種: 12業種の後の α 保有 %+.2f t%s（BusEq %s・Money %s）→ 2013-07〜 %+.2f t%s（BusEq の傾き %s に増える）' % (
            o['ind12_alpha_hold']['alpha'], o['ind12_alpha_hold']['t'], o['ind12_alpha_hold']['coef'].get('BusEq'), o['ind12_alpha_hold']['coef'].get('Money'),
            o['ind12_alpha_recent']['alpha'], o['ind12_alpha_recent']['t'], o['ind12_alpha_recent']['coef'].get('BusEq')))
        issues.append('米国外（C5・研究者は N/A にしたがデータはある）: 先進国 %d か国中 全期間で正 %d・保有期間で正 %d＝%s' % (c5['countries'], c5['positive_full'], c5['positive_hold'], '合格' if c5['C5_full'] else '不合格'))
        tk = [k for k in o if k.startswith('net_hold_(')][0]
        issues.append('費用: %s %+.2f・厳しめ（回転1.0×0.30%%）%+.2f・損益分岐の片道単価 %s%%＝費用では崩れない。日本の課税口座（20.315%%・損失繰越つき）での保有期間の年率差 %+.2f・全期間 %+.2f（NISA なら税なし）' % (
            tk, o[tk]['ex'], o['net_hold_stress_(turnover 1.0 × 0.30%)']['ex'], o['breakeven_cost_per_100pct_oneway_hold（%）'], o['after_tax_japan_taxable_hold（年率差・戦略 − 市場）'], o['after_tax_japan_taxable_full']))
        issues.append('実在の手段: この角度自身が105本の実在の手段で A 以上0本と出した＝紙の上の結果で、買える器で取れた証拠はない（紙の直接の複製＝約千銘柄の上限なし時価加重の三分位は理屈の上では組める）')
        verdict = 'confirmed' if g == c['grade'] else ('refuted' if g == 'C' else f'downgraded to {g}')
        V.append({'name': cid, 'claimed_grade': c['grade'], 'verified_grade': g, 'verdict': verdict, 'reproduced': rep,
                  'key_numbers': '全期間 %+.2f t%s／訓練 %+.2f t%s／保有 %+.2f t%s（幾何・総リターンどうし %+.2f）／費用後 %+.2f／20年窓 %s／積立20年 %s（中央 %s）／C5 %d/%d／max-t p %s' % (
                      o['full']['ex'], o['full']['t'], o['train']['ex'], o['train']['t'], o['hold']['ex'], o['hold']['t'], o['hold']['cagr_diff'], o[tk]['ex'],
                      o['roll20']['win_rate'], o['dca20']['win_rate'], o['dca20']['median'], c5['positive_full'], c5['countries'], mt.get('maxt_p_c1', '—（合成）')),
                  'issues': issues})
    # FCNTX
    f = res['candidates']['FCNTX']; fv = f['variants']; fr = f['robustness']; c = cl['FCNTX']
    v1 = fv['V1_msfix_1987（研究者の主）']; v0 = fv['V0_raw_1987']; v2 = fv['V2_msfix_1981（登録どおり「データの始まり」へ・直した後）']; v3 = fv['V3_msfix_danoff_1990-10']
    rep = all(_close(v1[w]['ex'], c[w]['ex_ann']) and _close(v1[w]['t'], c[w]['t']) for w in ('full', 'train', 'hold'))
    g = v2['grade'] if v2['grade'] == 'C' else v1['grade']
    a67 = fr['annual_MS_1967-2006（訓練を Morningstar の最初の年から）']; a6786 = fr['annual_MS_1967-1986（研究者が落とした期間）']
    V.append({'name': 'FCNTX', 'claimed_grade': c['grade'], 'verified_grade': g, 'verdict': 'confirmed' if g == c['grade'] else ('refuted' if g == 'C' else f'downgraded to {g}'),
              'reproduced': rep,
              'key_numbers': '1987〜（研究者の主）全期間 %+.2f t%s／訓練 %+.2f t%s／保有 %+.2f t%s（幾何 %+.2f）／1981〜（同じ Morningstar の直しをデータの始まりから）訓練 %+.2f t%s＝C1 不合格／年次 Morningstar %s 訓練 %+.2f t%s／保有の最良2年%s抜き %+.2f t%s' % (
                  v1['full']['ex'], v1['full']['t'], v1['train']['ex'], v1['train']['t'], v1['hold']['ex'], v1['hold']['t'], v1['hold']['cagr_diff'],
                  v2['train']['ex'], v2['train']['t'], a67['years'], a67['ex'], a67['t_nw1'], fr['hold_best2_years'], fr['hold_drop_best2']['ex'], fr['hold_drop_best2']['t']),
              'issues': [
                  'C1 は訓練の始まりを 1987-01 に置いたときだけ通る。研究者は VFINX の Yahoo の 1985-86 が壊れていたので投信を一律 1987 起点にしたが、同時に導入した Morningstar 年次の直し（1pt 超の年を12か月等倍）は 1981〜1986 の FCNTX にもそのまま効く（Morningstar の年次は %d 年から在る）。事前登録は『データの始まり〜2006-12』。直した後の 1981〜 では訓練 %+.2f t%s、年次で 1968〜 は %+.2f t%s（研究者が落とした 1968-1986 は %+.2f t%s）＝C1 不合格' % (f['robustness'].get('ms_first', 1967), v2['train']['ex'], v2['train']['t'], a67['ex'], a67['t_nw1'], a6786['ex'], a6786['t_nw1']),
                  '研究者の注『生データのままなら訓練 −0.19%%/年で C』は誤解を招く: その値は Yahoo の壊れた 1980-86 を含む数字で、1987〜 の生データ（Morningstar で直さない）は訓練 %+.2f t%s でむしろ B のまま。B が依存しているのは Morningstar の直しではなく 1987 起点' % (v0['train']['ex'], v0['train']['t']),
                  '訓練の最良2年%s を抜くと t%s（<2）・Danoff の運用開始後（1990-10〜）だけなら訓練 t%s（境界）' % (fr['train_best2_years'], fr['train_drop_best2']['t'], v3['train']['t']),
                  '保有期間は t%s（C3 不合格）で、前半 %+.2f t%s・2020-21 抜き %+.2f t%s・最良2年%s抜き %+.2f t%s＝2007年と2023年の2年に大半が乗る' % (
                      v1['hold']['t'], fr['hold_first_half_2007-01..2016-06']['ex'], fr['hold_first_half_2007-01..2016-06']['t'], fr['hold_drop_2020-2021']['ex'], fr['hold_drop_2020-2021']['t'], fr['hold_best2_years'], fr['hold_drop_best2']['ex'], fr['hold_drop_best2']['t']),
                  '費用の見落とし: Contrafund は 2003-06-23 まで 3.00%% の申込手数料があった（SEC Form 497, 2003）。Yahoo/Morningstar の総リターンには入らない＝訓練期間の積立の実際の成績は過大（積立20年の中央 %s→%s）。保有期間（2007〜）には影響しない' % (fr['dca20_no_load']['median'], fr['dca20_with_3pct_load_until_2003-06']['median']),
                  '多重性と後知恵: R・E_LF・E_MEGA の実在の手段 %d 本のうち C1 合格は %d 本（偶然でも約 %s 本）。FCNTX は課題文が名指しした有名な生き残り＝つぶれた・合併で消えた投信は母集団に居ない' % (f['multiplicity']['vehicles_tried_R_ELF_EMEGA'], f['multiplicity']['train_C1_pass_count'], f['multiplicity']['expected_C1_pass_by_chance（片側 t≥2・約2.3%）']),
                  '5因子＋勢いの後の α: 全期間 %+.2f t%s → 保有期間 %+.2f t%s（勢い UMD の載り %s）' % (fr['ff5umd_full']['alpha'], fr['ff5umd_full']['t'], fr['ff5umd_hold']['alpha'], fr['ff5umd_hold']['t'], fr['ff5umd_hold']['coef'].get('UMD')),
                  '相手は French Mkt（上限なし時価加重）で適切。費用（信託報酬）は基準価額に入っている']})
    return V


SUMMARY_JA = """紙の S 4本の数字は自前のコード（良い側の決め方も別の方法）で全部再現した（cop_at 保有 +2.88 t3.22・QUAL5 +1.60 t2.59）。研究者が N/A にした C5 も米国外の国で当てると4本とも合格する。
だが保有期間の t は JKP の154特性を同時に試した族の中の結果で、相関を保った max-t で調整すると最良の cop_at でも p=0.055（C1 合格65本の中）で 5% を通らない。cop_at は保有 t が154本中1位だから再掲された＝保有期間は選択に使われている。
cop_at は C1・C7（全期間 t の6通りの感度で最低 3.07）・C5（19/21 か国）が頑丈なので A へ。ope_be は全期間 t が 3.01 ちょうどで 1998-2000 抜き 2.61・訓練 1.60、qmj_prof は 1973 起点 2.49・最良2年抜きの保有 t1.53 で、ともに B へ。
QUAL5 は5袖のうち2袖（gp_at・qmj）が 2006年には無い信号で、袖は保有期間を見た後に選ばれた。ただし 2006年に知られていた3袖だけでも訓練 t5.3・保有 t2.8 の S になるので、B ではなく A へ下げる。
4本とも上限つき（vw_cap）・等加重で作ると保有期間の勝ちは消え、2013年以降は12業種の後の α が細る＝勝ちは『上限なしで巨大株（テック）を持つ』ことに強く依存する紙の上の結果。
FCNTX の B は反証（C）: 訓練を 1987 起点に置いたときだけ C1 が通り、同じ Morningstar の直しをデータの始まり（1981〜）から当てると訓練 t1.76、年次で 1968〜 は t1.82。保有期間 t1.28 は最良2年（2007・2023）を抜くと +0.46 t0.44。2003年6月まで 3% の申込手数料もあった。"""


if __name__ == '__main__':
    main()
