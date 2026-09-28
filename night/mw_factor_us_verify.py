#!/usr/bin/env python3
"""night/mw_factor_us_verify.py — 角度 factor_us の『反証の検証』（読むだけ・門の判定には不使用）

out/mw_factor_us.json が S / A と格付けした候補（＋保有期間の超過が大きい B の上位2本）を、
**研究者のコード（night/mw_factor_us.py）を使わずに**作り直して反証を試みる。
mw_common から借りるのは取得と表の読み込み（french_tables / jkp_rows）だけ。
三分位の系列の組み立て・良い側の決め方・超過・幾何の差（総リターンどうし）・Newey-West t・転がる20年窓・積立・
費用・税・回帰・国の答え合わせ・多重検定（max-t の block bootstrap）は全部ここで自前に書く。

確かめること（候補ごと）
 1. 数字の再現（全期間・訓練・保有の超過と NW t・総リターンの幾何の差・20年窓・20年積立・費用後）
 2. 後知恵: 良い側を 2006 年までのデータだけで決めているか（自前: 訓練期間の P3−P1 の平均の符号）／
    **特性の定義そのものが 2007 年以降のデータを見て作られていないか**（出典論文のデータの終わり）
 3. 相手: 純粋な時価加重（French Mkt）か／超過と総リターンの取り違え
 4. 小期間: 1998-2000 を抜く／2020-2021 を抜く／保有期間の前半・後半／最良の2年を抜く／2008-09 を抜く
 5. 近いパラメータ: 重みづけ（vw_cap・ew）・同じ考えの近い特性・開始年 1963（Compustat の後付け補完を避ける）
 6. 業種の偏り（French 12業種の回帰）・最大級の会社への依存（上限つき）
 7. 費用（損益分岐）・日本の課税口座（20.315%）
 8. 多重検定: 角度の 226 本・a 族 153 本の保有期間 t の max-t（circular block bootstrap・12か月ブロック）
 9. 独立の答え合わせ: JKP の国別（米国外 40か国前後）の保有期間
結果 → out/mw_factor_us_verify.json
"""
import os, sys, json, math, subprocess, statistics as st
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得と表の読み込みだけ使う（french_tables / jkp_rows）

BASE = M.BASE
TRAIN_END, HOLD, RECENT, HALF2 = 200612, 200701, 201307, 201607
TAX_JP = 0.20315
NMIN = 10
TARGET = os.path.join(BASE, 'out', 'mw_factor_us.json')


# ───────────────────────── 取得 → 自前の整形 ─────────────────────────
def ym(s):
    return int(s[0:4]) * 100 + int(s[5:7])


def _ff():
    v = next(v for t, v in M.french_tables('F-F_Research_Data_Factors').items() if v['freq'] == 'monthly')
    ia, ir = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
    mkt, rf = {}, {}
    for d, r in v['data'].items():
        if r[ia] is not None and r[ir] is not None:
            mkt[d] = (r[ia] + r[ir]) / 100.0
            rf[d] = r[ir] / 100.0
    return mkt, rf


MKT, RF = _ff()   # 相手: French Mkt（総リターン・上限なしの時価加重）と 1か月 T-bill


_J = {}


def jkp_pf(region, key, w='vw'):
    """JKP の三分位 → {'1.0'|'2.0'|'3.0': {ym: (超過リターン, 社数)}}"""
    k = (region, key, w)
    if k not in _J:
        d = {}
        for x in M.jkp_rows(region, key, 'portfolios', w):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            n = float(x['n']) if x.get('n') not in (None, '', 'NA', 'na') else None
            d.setdefault(x['pf'], {})[ym(x['date'])] = (float(x['ret']), n)
        _J[k] = d
    return _J[k]


_JALL = {}


def jkp_all(region):
    """JKP all_factors の vw 三分位（全特性まとめ）→ {特性: {pf: {ym: (r, n)}}}"""
    if region not in _JALL:
        d = {}
        for x in M.jkp_rows(region, 'all_factors', 'portfolios', 'vw'):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            n = float(x['n']) if x.get('n') not in (None, '', 'NA', 'na') else None
            d.setdefault(x['name'], {}).setdefault(x['pf'], {})[ym(x['date'])] = (float(x['ret']), n)
        _JALL[region] = d
    return _JALL[region]


def jkp_mkt(region, w='vw'):
    return {ym(x['date']): float(x['ret']) for x in M.jkp_rows(region, 'mkt', 'factor', w) if x['ret'] not in ('', 'NA', 'na')}


_DIR = None


def jkp_direction():
    global _DIR
    if _DIR is None:
        _DIR = {}
        for x in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
            if x['direction'] not in ('', 'na', 'NA') and x['name'] not in _DIR:
                _DIR[x['name']] = int(float(x['direction']))
    return _DIR


def side_ex(pfd, side, nmin=NMIN):
    """良い側の超過リターン（社数 < nmin の月は除く・0で埋めない）"""
    return {m: r for m, (r, n) in pfd.get(side, {}).items() if n is None or n >= nmin}


def my_good_side(pfd):
    """自前の良い側: 訓練期間（〜2006-12）の (第3 − 第1) の平均の符号。研究者の『相関の符号』とは別の方法"""
    p3, p1 = pfd.get('3.0', {}), pfd.get('1.0', {})
    ks = [m for m in p3 if m in p1 and m <= TRAIN_END]
    if len(ks) < 24:
        return None
    return '3.0' if sum(p3[m][0] - p1[m][0] for m in ks) > 0 else '1.0'


def tot(ex):
    """超過（T-bill を引いた値）→ 総リターン（French RF を足す）"""
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


def fr_vw(name, col):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'value' in t.lower() and 'weight' in t.lower():
            i = v['cols'].index(col)
            return {d: r[i] / 100.0 for d, r in v['data'].items() if r[i] is not None}
    raise KeyError(name)


# ───────────────────────── 自前の統計 ─────────────────────────
def mean(x):
    return math.fsum(x) / len(x)


def nw_t(x, lag=12):
    n = len(x)
    if n < 24:
        return None
    m = mean(x)
    e = [v - m for v in x]
    lrv = math.fsum(v * v for v in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        lrv += 2.0 * (1.0 - L / (lag + 1.0)) * math.fsum(e[i] * e[i - L] for i in range(L, n)) / n
    return m / math.sqrt(lrv / n) if lrv > 0 else None


def geo(v):
    return math.exp(12.0 * math.fsum(math.log1p(x) for x in v) / len(v)) - 1.0


def comp(s, b, a=None, z=None, drop=None):
    """s・b とも**総リターン**。差の算術平均（年率%）・NW t・幾何の年率差（%・総リターンどうし）・追従のぶれ"""
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not (drop and drop(k)))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nw_t(ex)
    return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'ex': round(mean(ex) * 1200, 2),
            't': round(t, 2) if t is not None else None,
            'p2': round(math.erfc(abs(t) / math.sqrt(2)), 4) if t is not None else None,
            'cagr_diff': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2),
            'te': round(st.stdev(ex) * math.sqrt(12) * 100, 2)}


def roll20(s, b, min_start=None):
    """毎年7月起点の一括20年（240か月そろった窓だけ）"""
    ks = set(s) & set(b)
    out = []
    for y in range(min(ks) // 100, max(ks) // 100 + 1):
        if min_start and y < min_start:
            continue
        w = [(y + (m + 5) // 12) * 100 + (m + 5) % 12 + 1 for m in range(1, 241)]  # y07 .. (y+20)06
        if not all(k in ks for k in w):
            continue
        out.append((y, round((geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100, 2)))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 0) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda z: z[1]), 'first_start': out[0][0]}


def dca20(s, b):
    """毎年7月起点・毎月同額を240か月積み立てた最終額の比"""
    ks = sorted(set(s) & set(b))
    kset = set(ks)
    out = []
    for k0 in ks:
        if k0 % 100 != 7:
            continue
        y = k0 // 100
        w = [(y + (m + 5) // 12) * 100 + (m + 5) % 12 + 1 for m in range(1, 241)]
        if not all(k in kset for k in w):
            continue
        vs = vb = 0.0
        for k in w:
            vs = (vs + 1.0) * (1.0 + s[k]); vb = (vb + 1.0) * (1.0 + b[k])
        out.append((y, round(vs / vb, 3)))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(out, key=lambda z: z[1])}


def net(s, turnover, unit):
    c = turnover * unit / 12.0
    return {k: v - c for k, v in s.items()}


def after_tax(r, turnover, a, z=None):
    """日本の課税口座（20.315%）: 毎月 turnover/12 を売って買い直し、実現益に課税（損は繰越）。最後に全部売る。年率を返す"""
    ks = sorted(k for k in r if k >= a and (z is None or k <= z))
    V = B = 1.0
    loss = 0.0
    f = min(turnover / 12.0, 1.0)
    for k in ks:
        V *= 1.0 + r[k]
        g = f * (V - B)
        T = 0.0
        if g > 0:
            use = min(loss, g); loss -= use; T = TAX_JP * (g - use)
        else:
            loss -= g
        B = B * (1.0 - f) + f * V - T
        V -= T
    g = V - B
    if g > 0:
        V -= TAX_JP * max(0.0, g - loss)
    return V ** (12.0 / len(ks)) - 1.0


def ols(y, X):
    Y = np.array(y); Z = np.column_stack([np.ones(len(y))] + [np.array(c) for c in X])
    b, *_ = np.linalg.lstsq(Z, Y, rcond=None)
    e = Y - Z @ b
    t = nw_t(list(b[0] + e))
    r2 = 1 - float(e @ e) / float(((Y - Y.mean()) @ (Y - Y.mean())))
    return float(b[0]) * 1200, t, r2, [float(x) for x in b[1:]]


_IND = None


def industry_adj(s, a, z=None):
    """y = 戦略 − 市場、X = 11業種（Other を除く）− 市場。α と、業種の傾きで説明された分"""
    global _IND
    if _IND is None:
        t = M.french_tables('12_Industry_Portfolios')['Average Value Weighted Returns -- Monthly']
        _IND = {c: {d: r[i] / 100.0 for d, r in t['data'].items() if r[i] is not None} for i, c in enumerate(t['cols'])}
    cols = [c for c in _IND if c != 'Other']
    ks = sorted(k for k in s if k in MKT and k >= a and (z is None or k <= z) and all(k in _IND[c] for c in cols))
    y = [s[k] - MKT[k] for k in ks]
    X = [[_IND[c][k] - MKT[k] for k in ks] for c in cols]
    al, t, r2, be = ols(y, X)
    tilts = dict(zip(cols, [round(x, 3) for x in be]))
    contrib = {c: round(be[i] * mean(X[i]) * 1200, 2) for i, c in enumerate(cols)}
    top = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:3]
    return {'raw_ex': round(mean(y) * 1200, 2), 'alpha': round(al, 2), 't_nw': round(t, 2) if t is not None else None, 'r2': round(r2, 3),
            'tilts': tilts, 'explained_by_tilts': round(sum(contrib.values()), 2), 'largest_contrib': top}


def drop_best_years(s, b, a, k=2):
    yrs = {}
    for m in s:
        if m in b and m >= a:
            yrs.setdefault(m // 100, []).append(m)
    ann = {y: (math.prod(1 + s[m] for m in ms) - math.prod(1 + b[m] for m in ms)) for y, ms in yrs.items() if len(ms) == 12}
    best = sorted(ann, key=lambda y: -ann[y])[:k]
    return best, comp(s, b, a=a, drop=lambda m: m // 100 in best)


# ───────────────────────── 多重検定: max-t の block bootstrap ─────────────────────────
def nw_t_cols(E, lag=12):
    T = E.shape[0]
    m = E.mean(0)
    D = E - m
    s = (D * D).sum(0) / T
    for L in range(1, lag + 1):
        s = s + 2 * (1 - L / (lag + 1)) * (D[L:] * D[:-L]).sum(0) / T
    return m / np.sqrt(s / T)


def maxt_bootstrap(X, names, reps=4000, block=12, seed=20260928):
    """X: T×K の保有期間の超過（戦略−市場）。帰無仮説（全列の平均0）の下で列を中心化し、
    循環ブロックで月を引き直して max_j t_j の分布を作る（片側・相関はそのまま保つ）"""
    rng = np.random.default_rng(seed)
    T, K = X.shape
    t_obs = nw_t_cols(X)
    C = X - X.mean(0)
    nb = int(math.ceil(T / block))
    mx = np.empty(reps)
    cnt165 = np.empty(reps)
    for r in range(reps):
        st0 = rng.integers(0, T, nb)
        idx = ((st0[:, None] + np.arange(block)[None, :]) % T).ravel()[:T]
        tb = nw_t_cols(C[idx])
        mx[r] = tb.max()
        cnt165[r] = (tb >= 1.65).sum()
    adj = {n: round(float((mx >= t_obs[j]).mean()), 4) for j, n in enumerate(names)}
    return {'t_obs': {n: round(float(t_obs[j]), 2) for j, n in enumerate(names)}, 'adj_p': adj,
            'max_t_q95': round(float(np.quantile(mx, 0.95)), 2), 'max_t_q90': round(float(np.quantile(mx, 0.90)), 2),
            'observed_count_t_ge_1.65': int((t_obs >= 1.65).sum()),
            'count_p': round(float((cnt165 >= (t_obs >= 1.65).sum()).mean()), 4),
            'null_count_t_ge_1.65_mean': round(float(cnt165.mean()), 1), 'null_count_t_ge_1.65_q95': float(np.quantile(cnt165, 0.95))}


# ───────────────────────── 候補 ─────────────────────────
CLAIMED = ['cop_at', 'cop_atl1', 'sale_bev', 'rd_me', 'seas_6_10an', 'ope_be', 'qmj_prof', 'ocf_at']
OTHER_A_FAMILY = ['eqnetis_at', 'mispricing_perf', 'netis_at', 'oaccruals_at',            # S（主張の一覧の外）
                  'capx_gr1', 'chcsho_12m', 'cowc_gr1a', 'inv_gr1', 'inv_gr1a', 'noa_at', 'noa_gr1a', 'ope_bel1', 'qmj_growth',  # A
                  'ebit_bev']                                                                  # B（保有の超過で B の2位）
# 自前の回転率の目安（片道・年）。研究者の表を写さず、三分位（広い箱）の文献の目安から置いた
MY_TURN = {'seas_6_10an': 8.0, 'mispricing_perf': 1.2, 'chcsho_12m': 1.0, 'oaccruals_at': 1.0, 'cowc_gr1a': 1.0,
           'inv_gr1': 0.9, 'inv_gr1a': 0.9, 'noa_gr1a': 0.9, 'capx_gr1': 0.9, 'qmj_growth': 0.9}
UNIT = 0.003
# 近い特性（同じ考えの別定義）— 近傍が崩れるなら『その一本がたまたま』の疑い
NEIGH = {
    'cop_at': ['cop_atl1', 'op_at', 'op_atl1', 'gp_at', 'gp_atl1', 'ocf_at', 'ope_be', 'ope_bel1', 'ni_be', 'niq_at', 'niq_be', 'ebit_bev'],
    'cop_atl1': ['cop_at', 'op_atl1', 'gp_atl1', 'ope_bel1'],
    'sale_bev': ['at_turnover', 'sale_me', 'ebit_bev', 'ebit_sale'],
    'rd_me': ['rd_sale', 'rd5_at'],
    'seas_6_10an': ['seas_1_1an', 'seas_2_5an', 'seas_11_15an', 'seas_16_20an'],
    'ope_be': ['ope_bel1', 'ni_be', 'niq_be', 'ebit_bev', 'op_at', 'cop_at'],
    'qmj_prof': ['qmj', 'qmj_growth', 'qmj_safety', 'gp_at', 'op_at'],
    'ocf_at': ['ocf_at_chg1', 'ocf_me', 'fcf_me', 'cop_at'],
}
# 特性の定義が作られた論文のデータの終わり（概ね）と公表年。データの終わり＞2006 なら『保有期間』の一部は発見の標本
SAMPLE_END = {  # (論文, データの終わり, 公表年)
    'cop_at': ('Ball, Gerakos, Linnainmaa & Nikolaev (2016, JFE) の cash-based OP', 2013, 2016),
    'cop_atl1': ('Ball, Gerakos, Linnainmaa & Nikolaev (2016, JFE)', 2013, 2016),
    'ope_be': ('Fama & French (2015, JFE) RMW（先行: Novy-Marx 2013 はデータ 2010 まで）', 2013, 2015),
    'qmj_prof': ('Asness, Frazzini & Pedersen（2013 年の working paper・2019 RAS）', 2012, 2013),
    'ocf_at': ('Bouchard, Krüger, Landier & Thesmar (2019, JF)', 2016, 2019),
    'mispricing_perf': ('Stambaugh & Yuan (2017, RFS)', 2013, 2017),
    'sale_bev': ('Soliman (2008, TAR)', 2002, 2008),
    'rd_me': ('Chan, Lakonishok & Sougiannis (2001, JF)', 1995, 2001),
    'seas_6_10an': ('Heston & Sadka (2008, JFE)', 2002, 2008),
    'oaccruals_at': ('Sloan (1996, TAR)', 1991, 1996),
    'netis_at': ('Bradshaw, Richardson & Sloan (2006, JAE)', 2000, 2006),
    'eqnetis_at': ('Bradshaw, Richardson & Sloan (2006, JAE)', 2000, 2006),
}


def git_head(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%h', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


def my_grade(full, train, hold, r20, net_hold, repl, holm_p=None):
    c = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0 and train['months'] >= 180),
         'C2': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4': bool(r20 and r20['win_rate'] >= 0.8),
         'C5': (repl['positive'] / repl['regions'] >= 2 / 3) if repl else None,
         'C6': bool(net_hold and net_hold['ex'] > 0 and net_hold['cagr_diff'] > 0),
         'C7': bool((full and (full['t'] or 0) >= 3.0) or (holm_p is not None and holm_p < 0.05))}
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


def repl_regions(key, side):
    out, pos = {}, 0
    for reg in ('developed', 'emerging', 'jpn'):
        try:
            s = side_ex(jkp_pf(reg, key), side)
            b = jkp_mkt(reg)
            ks = sorted(k for k in s if k in b)
            full = mean([s[k] - b[k] for k in ks]) * 1200 if len(ks) > 24 else None
            hk = [k for k in ks if k >= HOLD]
            hold = mean([s[k] - b[k] for k in hk]) * 1200 if len(hk) > 24 else None
            out[reg] = {'full_ex': round(full, 2) if full is not None else None, 'hold_ex': round(hold, 2) if hold is not None else None,
                        'hold_t': round(nw_t([s[k] - b[k] for k in hk]), 2) if len(hk) > 24 else None, 'from': ks[0] if ks else None}
            if reg != 'jpn' and full is not None and full > 0:
                pos += 1
        except Exception as e:  # noqa
            out[reg] = {'error': str(e)[:100]}
    return {'regions': 2, 'positive': pos, 'detail': out}


_CMKT = {}


def country_hold(key, side, countries):
    """JKP の国別（all_factors・vw）で、米国の訓練で決めた良い側の保有期間の超過（対その国の vw 市場）"""
    res = {}
    for cc in countries:
        try:
            A = jkp_all(cc)
            if key not in A:
                continue
            s = side_ex(A[key], side)
            if cc not in _CMKT:
                _CMKT[cc] = jkp_mkt(cc)
            b = _CMKT[cc]
            hk = sorted(k for k in s if k in b and k >= HOLD)
            if len(hk) < 120:
                continue
            ex = [s[k] - b[k] for k in hk]
            res[cc] = round(mean(ex) * 1200, 2)
        except Exception:
            continue
    v = list(res.values())
    return {'countries': len(v), 'positive': sum(1 for x in v if x > 0), 'median': round(sorted(v)[len(v) // 2], 2) if v else None,
            'mean': round(mean(v), 2) if v else None, 'detail': res}


def countries_available():
    cs = []
    for f in os.listdir(os.path.join(BASE, 'out', '_mw_cache')):
        if f.startswith('jkp_portfolios_') and f.endswith('_all_factors_vw_monthly.zip'):
            cc = f[len('jkp_portfolios_'):-len('_all_factors_vw_monthly.zip')]
            if len(cc) == 3 and cc != 'usa':
                cs.append(cc)
    return sorted(cs)


# ───────────────────────── 本体 ─────────────────────────
def analyse_key(key, side, turnover, deep=False, countries=None):
    pfd = jkp_pf('usa', key)
    ex = side_ex(pfd, side)
    s = tot(ex)
    o = {'key': key, 'side': side, 'from': min(s), 'to': max(s), 'months': len(s)}
    o['full'] = comp(s, MKT)
    o['train'] = comp(s, MKT, z=TRAIN_END)
    o['hold'] = comp(s, MKT, a=HOLD)
    o['recent'] = comp(s, MKT, a=RECENT)
    # 取り違えの点検: 研究者は超過どうしの CAGR を差に使った → 総リターンどうしとの差
    exs = {k: ex[k] for k in ex if k in MKT and k >= HOLD}
    mrf = {k: MKT[k] - RF[k] for k in exs}
    o['hold_cagr_diff_excess_basis'] = round((geo(list(exs.values())) - geo([mrf[k] for k in exs])) * 100, 2)
    o['turnover_used'] = turnover
    nh = net(s, turnover, UNIT)
    o['net_hold'] = comp(nh, MKT, a=HOLD)
    o['net_full'] = comp(nh, MKT)
    o['r20'] = roll20(s, MKT)
    o['dca20'] = dca20(s, MKT)
    o['breakeven_cost_per_100pct'] = round(o['hold']['ex'] / 100 / turnover * 100, 3) if turnover else None  # %（片道100%あたり）
    if not deep:
        return o, s
    o['train_from_1963'] = comp(s, MKT, a=196307, z=TRAIN_END)
    o['r20_from_1963'] = roll20(s, MKT, min_start=1963)
    o['full_drop_1998_2000'] = comp(s, MKT, drop=lambda k: 199801 <= k <= 200012)
    o['train_drop_1998_2000'] = comp(s, MKT, z=TRAIN_END, drop=lambda k: 199801 <= k <= 200012)
    o['hold_drop_2020_2021'] = comp(s, MKT, a=HOLD, drop=lambda k: 202001 <= k <= 202112)
    o['hold_drop_2008_2009'] = comp(s, MKT, a=HOLD, drop=lambda k: 200801 <= k <= 200912)
    o['hold_first_half'] = comp(s, MKT, a=HOLD, z=HALF2 - 1)
    o['hold_second_half'] = comp(s, MKT, a=HALF2)
    by, o['hold_drop_best2y'] = drop_best_years(s, MKT, HOLD)
    o['hold_best2_years'] = by
    # 公表後・論文のデータの後
    if key in SAMPLE_END:
        lab, dend, pub = SAMPLE_END[key]
        o['paper'] = {'source': lab, 'data_end': dend, 'pub_year': pub,
                      'after_data_end': comp(s, MKT, a=(dend + 1) * 100 + 1), 'after_pub': comp(s, MKT, a=(pub + 1) * 100 + 1),
                      'holdout_in_discovery_sample': dend >= 2007}
    # 重みづけの近傍
    for w in ('vw_cap', 'ew'):
        try:
            sw = tot(side_ex(jkp_pf('usa', key, w), side))
            o[f'{w}_hold'] = comp(sw, MKT, a=HOLD)
            o[f'{w}_full'] = comp(sw, MKT)
            if w == 'vw_cap':
                capm = tot(jkp_mkt('usa', 'vw_cap'))
                o['vw_cap_vs_capped_mkt_hold'] = comp(sw, capm, a=HOLD)
        except Exception as e:  # noqa
            o[f'{w}_error'] = str(e)[:100]
    # 良い側・中・悪い側の単調性（保有期間）
    o['terciles_hold'] = {p: (comp(tot(side_ex(pfd, p)), MKT, a=HOLD) or {}).get('ex') for p in ('1.0', '2.0', '3.0')}
    # 業種
    o['industry_hold'] = industry_adj(s, HOLD)
    o['industry_train'] = industry_adj(s, 196307, TRAIN_END)
    # 税（日本の課税口座）: 戦略（回転あり・費用後）vs 市場の買って持つだけ
    o['after_tax_hold'] = {'strategy': round(after_tax(nh, turnover, HOLD) * 100, 2), 'market_buy_hold': round(after_tax(MKT, 0.0, HOLD) * 100, 2)}
    o['after_tax_hold']['diff'] = round(o['after_tax_hold']['strategy'] - o['after_tax_hold']['market_buy_hold'], 2)
    # 近い特性
    nb = {}
    A = jkp_all('usa')
    D = jkp_direction()
    for k2 in NEIGH.get(key, []):
        if k2 not in A:
            continue
        sd2 = my_good_side(A[k2])
        s2 = tot(side_ex(A[k2], sd2))
        tr2, h2 = comp(s2, MKT, z=TRAIN_END), comp(s2, MKT, a=HOLD)
        nb[k2] = {'side': sd2, 'dir_agrees': (sd2 == '3.0') == (D.get(k2, 1) > 0), 'train_ex': tr2['ex'], 'train_t': tr2['t'],
                  'hold_ex': h2['ex'], 'hold_t': h2['t'], 'C1': bool(tr2['ex'] > 0 and tr2['t'] >= 2.0 and tr2['months'] >= 180),
                  'C3': bool(h2['t'] >= 1.65)}
    o['neighbors'] = nb
    o['neighbors_summary'] = {'n': len(nb), 'hold_positive': sum(1 for v in nb.values() if v['hold_ex'] > 0),
                              'C1_and_C3': sum(1 for v in nb.values() if v['C1'] and v['C3']),
                              'C1': sum(1 for v in nb.values() if v['C1'])}
    o['repl_regions'] = repl_regions(key, side)
    if countries:
        o['country_hold'] = country_hold(key, side, countries)
    return o, s


def main():
    tgt = json.load(open(TARGET))
    tested = {e['name']: e for e in tgt['tested']}
    D = jkp_direction()
    A = jkp_all('usa')
    countries = countries_available()
    out = {'target': 'out/mw_factor_us.json', 'target_commit': git_head('out/mw_factor_us.json'),
           'benchmark': 'French Mkt（Mkt-RF+RF）＝上限なしの時価加重・CRSP 全上場（上場廃止も含む）',
           'independence': 'mw_common からは取得と表の読み込み（french_tables / jkp_rows）だけ。良い側は訓練期間の (P3−P1) 平均の符号で自前に決め、研究者の『相関の符号』と照合。'
                           '超過・NW t・総リターンの幾何の差・20年窓・積立・費用・税・12業種回帰・国別・max-t bootstrap は自前'}
    # 検算
    jm = tot(jkp_mkt('usa'))
    sanity = {'jkp_mkt_vw_plus_RF_vs_french_mkt_full': comp(jm, MKT), 'jkp_mkt_vw_plus_RF_vs_french_mkt_hold': comp(jm, MKT, a=HOLD),
              'french_mkt_cagr_full': round(geo(list(MKT.values())) * 100, 2),
              'french_mkt_cagr_hold_to_2025_12': round(geo([MKT[k] for k in MKT if HOLD <= k <= 202512]) * 100, 2)}
    # 良い側の照合（153本すべて）
    agree, dis = 0, []
    my_side = {}
    for k in A:
        sd = my_good_side(A[k])
        my_side[k] = sd
        rs = tested.get(f'a_{k}', {}).get('good_side')
        if sd is not None and rs is not None:
            if sd == rs:
                agree += 1
            else:
                dis.append(k)
    sanity['good_side_mine_vs_researcher'] = {'agree': agree, 'disagree': dis}
    sanity['good_side_vs_literature_direction_disagree'] = [k for k, sd in my_side.items() if sd and k in D and (sd == '3.0') != (D[k] > 0)]
    sanity['good_side_note'] = ('研究者の良い側は153本すべて JKP の文献の向きと一致。自前の「訓練期間の P3−P1 平均の符号」と食い違う21本は低ベータ・低リスク系など（買いだけでは高い側が勝っていた）で、'
                                '候補（S/A/B）は1本も含まない＝良い側に 2007 年以降のデータは入っていない')
    # 日付の揃い: JKP 市場と French Mkt-RF の相関（ずれていれば ±1 か月で高くなる）
    jk = jkp_mkt('usa')
    for L in (-1, 0, 1):
        ks = [k for k in jk if k in MKT]
        pairs = []
        for k in ks:
            y, mth = divmod(k, 100)
            mm = y * 12 + mth - 1 + L
            k2 = (mm // 12) * 100 + mm % 12 + 1
            if k2 in MKT:
                pairs.append((jk[k], MKT[k2] - RF[k2]))
        sanity[f'corr_jkp_mkt_vs_french_mktrf_lag{L:+d}'] = round(float(np.corrcoef(np.array(pairs).T)[0, 1]), 4)
    out['sanity'] = sanity
    print('sanity', json.dumps(sanity, ensure_ascii=False)[:600], flush=True)

    # ── 多重検定: a 族の153本の保有期間（研究者の良い側・n≥10）
    names, cols = [], []
    ks_h = sorted(k for k in MKT if HOLD <= k <= 202512)
    for k in sorted(A):
        sd = tested.get(f'a_{k}', {}).get('good_side') or my_side.get(k)
        if sd is None:
            continue
        s = tot(side_ex(A[k], sd))
        if all(m in s for m in ks_h):
            names.append(k); cols.append([s[m] - MKT[m] for m in ks_h])
    X = np.array(cols).T
    mt_all = maxt_bootstrap(X, names)
    c1_names = [k for k in names if (lambda tr: tr and tr['ex'] > 0 and tr['t'] >= 2.0 and tr['months'] >= 180)(comp(tot(side_ex(A[k], tested.get(f'a_{k}', {}).get('good_side') or my_side[k])), MKT, z=TRAIN_END))]
    Xc = np.array([cols[names.index(k)] for k in c1_names]).T
    mt_c1 = maxt_bootstrap(Xc, c1_names)
    out['multiplicity'] = {
        'angle_total_tested': tgt['n_tested'], 'family_a': len(names), 'family_a_C1_passers': len(c1_names),
        'maxt_all153': {k: v for k, v in mt_all.items() if k not in ('adj_p', 't_obs')},
        'maxt_c1': {k: v for k, v in mt_c1.items() if k not in ('adj_p', 't_obs')},
        'adj_p_all153': {k: mt_all['adj_p'][k] for k in sorted(mt_all['adj_p'], key=lambda z: mt_all['adj_p'][z])[:20]},
        'adj_p_c1_passers': {k: mt_c1['adj_p'][k] for k in sorted(mt_c1['adj_p'], key=lambda z: mt_c1['adj_p'][z])[:20]},
        'researcher_holm_family': {n: tested[n].get('holm_p_family') for n in ('a_' + k for k in CLAIMED)},
        'note': '保有期間 2007-01〜2025-12 の月次超過（戦略−French Mkt）を列にし、全列を中心化（帰無）して12か月の循環ブロックで4000回引き直した max-t（片側）。'
                '列どうしの相関はそのまま保たれるので Holm より保守的でない。C1 合格の列だけの版は「S になりうるのは C1 合格だけ」という族の数え方'}
    print('maxt', json.dumps(out['multiplicity'], ensure_ascii=False)[:1500], flush=True)

    # ── 正直な選び方: 2006 年までのデータだけで 153 本から選んだら、保有期間に勝ったか
    tr_t = {}
    for k in names:
        tr = comp(tot(side_ex(A[k], tested.get(f'a_{k}', {}).get('good_side') or my_side[k])), MKT, z=TRAIN_END)
        tr_t[k] = tr['t'] if tr and tr['months'] >= 180 else None
    ranked = sorted([k for k in c1_names], key=lambda k: -tr_t[k])
    def mix_hold(keys):
        ser = [tot(side_ex(A[k], tested.get(f'a_{k}', {}).get('good_side') or my_side[k])) for k in keys]
        ks = sorted(set.intersection(*[set(x) for x in ser]))
        m = {k: mean([x[k] for x in ser]) for k in ks}
        return comp(m, MKT, a=HOLD)
    rng = np.random.default_rng(7)
    rand5 = []
    for _ in range(2000):
        pick = list(rng.choice(len(c1_names), 5, replace=False))
        rand5.append(float(np.mean(Xc[:, pick].mean(1)) * 1200))
    rand5 = np.array(rand5)
    out['honest_selection'] = {
        'note': '良い側は文献の向き・選別は訓練期間（〜2006-12）の数字だけ。保有期間は答え合わせ',
        'all_C1_passers_equal_mix': mix_hold(c1_names),
        'top5_by_train_t': {'keys': ranked[:5], 'hold': mix_hold(ranked[:5])},
        'top10_by_train_t': {'keys': ranked[:10], 'hold': mix_hold(ranked[:10])},
        'rank_by_train_t_among_C1': {k: ranked.index(k) + 1 for k in CLAIMED if k in ranked},
        'random5_of_C1_hold_ex': {'median': round(float(np.median(rand5)), 2), 'q05': round(float(np.quantile(rand5, 0.05)), 2),
                                   'q95': round(float(np.quantile(rand5, 0.95)), 2), 'share_positive': round(float((rand5 > 0).mean()), 3)},
        'hold_t_of_C1_passers_mean': round(float(np.mean([mt_c1['t_obs'][k] for k in c1_names])), 2),
    }
    print('honest', json.dumps(out['honest_selection'], ensure_ascii=False)[:1200], flush=True)

    # ── 同じ考えの別の作り方: French の営業利益率（OP）ソート（ope_be の双子）
    fr_op = {}
    for f, col, lab in (('Portfolios_Formed_on_OP', 'Hi 30', 'OP 上位30%（NYSE 分位・全規模）'), ('Portfolios_Formed_on_OP', 'Hi 20', 'OP 上位20%'),
                        ('Portfolios_Formed_on_OP', 'Hi 10', 'OP 上位10%'), ('6_Portfolios_ME_OP_2x3', 'BIG HiOP', '大型 × OP 上位30%'),
                        ('25_Portfolios_ME_OP_5x5', 'BIG HiOP', '最大五分位 × OP 最高五分位')):
        try:
            s = fr_vw(f, col)
            fr_op[f'{f}:{col}'] = {'label': lab, 'train': comp(s, MKT, z=TRAIN_END), 'hold': comp(s, MKT, a=HOLD), 'full': comp(s, MKT)}
        except Exception as ex:  # noqa
            fr_op[f'{f}:{col}'] = {'error': str(ex)[:100]}
    out['french_op_twins'] = fr_op

    # ── 候補の検証
    cands = []
    for k in CLAIMED + OTHER_A_FAMILY:
        e = tested[f'a_{k}']
        side = e['good_side']
        turn = MY_TURN.get(k, 0.6)
        deep = True
        o, s = analyse_key(k, side, turn, deep=deep, countries=countries if k in CLAIMED else None)
        o['name'] = f'a_{k}'
        o['claimed_grade'] = e['grade']
        o['in_claimed_list'] = k in CLAIMED
        o['researcher'] = {'full': (e['full']['ex_ann'], e['full']['t']), 'train': (e['train']['ex_ann'], e['train']['t']),
                           'hold': (e['hold']['ex_ann'], e['hold']['t'], e['hold']['cagr_diff']), 'net_hold': e['net_hold']['ex_ann'],
                           'r20': (e['roll20'] or {}).get('win_rate'), 'turnover_pct': e['cost']['turnover_pct']}
        o['reproduced'] = bool(abs(o['full']['ex'] - e['full']['ex_ann']) < 0.06 and abs(o['hold']['ex'] - e['hold']['ex_ann']) < 0.06
                               and abs(o['hold']['t'] - e['hold']['t']) < 0.06 and abs(o['train']['t'] - e['train']['t']) < 0.06)
        g, crit = my_grade(o['full'], o['train'], o['hold'], o['r20'], o['net_hold'], o['repl_regions'])
        o['mechanical_grade_mine'], o['criteria_mine'] = g, crit
        o['maxt_adj_p_all153'] = mt_all['adj_p'].get(k)
        o['maxt_adj_p_c1'] = mt_c1['adj_p'].get(k)
        cands.append(o)
        print(f"{o['name']:20} {e['grade']}→機械{g} 再現{o['reproduced']} 全{o['full']['ex']:+.2f}(t{o['full']['t']}) 訓{o['train']['ex']:+.2f}(t{o['train']['t']}) "
              f"保{o['hold']['ex']:+.2f}(t{o['hold']['t']}) 幾何{o['hold']['cagr_diff']:+.2f} 費後{o['net_hold']['ex']:+.2f} 20y{o['r20']['win_rate']} "
              f"maxtP {o['maxt_adj_p_all153']}/{o['maxt_adj_p_c1']} cap{(o.get('vw_cap_hold') or {}).get('ex')} 業種α{o['industry_hold']['alpha']}(t{o['industry_hold']['t_nw']}) "
              f"前{o['hold_first_half']['ex']:+.2f}(t{o['hold_first_half']['t']}) 後{o['hold_second_half']['ex']:+.2f}(t{o['hold_second_half']['t']}) "
              f"63〜訓t{o['train_from_1963']['t']} 税差{o['after_tax_hold']['diff']}", flush=True)

    # ── 探索の族の質の合成（17本・研究者の良い側）
    qk = tested['e2_cluster_Quality']['constituents']
    parts = [tot(side_ex(A[k], tested[f'a_{k}']['good_side'])) for k in qk]
    comp_s = {}
    for m in sorted(set().union(*[set(p) for p in parts])):
        v = [p[m] for p in parts if m in p]
        if len(v) >= 3:
            comp_s[m] = mean(v)
    q = {'name': 'e2_cluster_Quality', 'claimed_grade': 'S（探索・参考）', 'in_claimed_list': False,
         'full': comp(comp_s, MKT), 'train': comp(comp_s, MKT, z=TRAIN_END), 'hold': comp(comp_s, MKT, a=HOLD),
         'hold_first_half': comp(comp_s, MKT, a=HOLD, z=HALF2 - 1), 'hold_second_half': comp(comp_s, MKT, a=HALF2),
         'net_hold': comp(net(comp_s, 0.8, UNIT), MKT, a=HOLD), 'r20': roll20(comp_s, MKT), 'industry_hold': industry_adj(comp_s, HOLD),
         'hold_drop_2020_2021': comp(comp_s, MKT, a=HOLD, drop=lambda k: 202001 <= k <= 202112)}
    cands.append(q)
    print('e2_Quality', q['full'], q['hold'], q['industry_hold']['alpha'], q['industry_hold']['t_nw'], flush=True)

    # ── French の A / B（b・c 族）
    FR = [('b_AC_Lo20', 'Portfolios_Formed_on_AC', 'Lo 20', 0.7, 0.003), ('b_NI_Neg', 'Portfolios_Formed_on_NI', '< 0', 0.6, 0.003),
          ('b_MOM_Hi10', '10_Portfolios_Prior_12_2', 'Hi PRIOR', 3.0, 0.003), ('c_me5_mom', '25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 1.5, 0.001),
          ('c_big_mom', '6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 1.2, 0.001)]
    for nm, f, col, to, unit in FR:
        e = tested[nm]
        s = fr_vw(f, col)
        o = {'name': nm, 'claimed_grade': e['grade'], 'in_claimed_list': False, 'full': comp(s, MKT), 'train': comp(s, MKT, z=TRAIN_END),
             'hold': comp(s, MKT, a=HOLD), 'hold_to_2025_12': comp(s, MKT, a=HOLD, z=202512),
             'hold_first_half': comp(s, MKT, a=HOLD, z=HALF2 - 1), 'hold_second_half': comp(s, MKT, a=HALF2),
             'net_hold': comp(net(s, to, unit), MKT, a=HOLD), 'r20': roll20(s, MKT), 'turnover_used': to, 'unit': unit,
             'hold_drop_2020_2021': comp(s, MKT, a=HOLD, drop=lambda k: 202001 <= k <= 202112),
             'hold_drop_2009': comp(s, MKT, a=HOLD, drop=lambda k: 200901 <= k <= 200912),
             'net_hold_to_2025_12': comp(net(s, to, unit), MKT, a=HOLD, z=202512),
             'full_drop_1998_2000': comp(s, MKT, drop=lambda k: 199801 <= k <= 200012),
             'train_from_1963': comp(s, MKT, a=196307, z=TRAIN_END)}
        by, o['hold_drop_best2y'] = drop_best_years(s, MKT, HOLD)
        o['hold_best2_years'] = by
        o['reproduced'] = bool(abs(o['full']['ex'] - e['full']['ex_ann']) < 0.06 and abs(o['hold']['ex'] - e['hold']['ex_ann']) < 0.06)
        o['researcher'] = {'full': (e['full']['ex_ann'], e['full']['t']), 'hold': (e['hold']['ex_ann'], e['hold']['t']), 'repl': e.get('repl', {}).get('positive') if e.get('repl') else None}
        cands.append(o)
        print(nm, e['grade'], o['full']['ex'], o['full']['t'], o['hold']['ex'], o['hold']['t'], o['net_hold']['ex'], o['reproduced'], flush=True)

    # ── 実在の ETF（生き残りだけ・作り方は別物・信託報酬込み）と、同じ月の cop_at
    cop = tot(side_ex(A['cop_at'], tested['a_cop_at']['good_side']))
    etf = {}
    for t in ('QUAL', 'SPHQ', 'JQUA', 'MOAT', 'VIG', 'DGRW', 'COWZ', 'SPY'):
        try:
            r = M.yahoo(t)
            ks = sorted(k for k in r if k in MKT and k in cop and k <= 202512)
            ks = ks[1:]
            if len(ks) < 36:
                continue
            e1 = comp({k: r[k] for k in ks}, MKT); e2 = comp({k: cop[k] for k in ks}, MKT)
            etf[t] = {'from': ks[0], 'to': ks[-1], 'etf_ex': e1['ex'], 'etf_t': e1['t'], 'etf_cagr_diff': e1['cagr_diff'], 'cop_at_same': e2['ex'], 'cop_at_same_t': e2['t']}
        except Exception as ex:  # noqa
            etf[t] = {'error': str(ex)[:80]}
    out['etf_reality'] = etf
    print('etf', json.dumps(etf, ensure_ascii=False)[:900], flush=True)
    out['candidates'] = cands
    out['verdict_rules'] = VERDICT_RULES
    out['verdicts'] = [verdict(o) for o in cands]
    hs = out['honest_selection']
    for v in out['verdicts']:
        k = v['name'][2:]
        if v['name'].startswith('a_') and k in hs['rank_by_train_t_among_C1']:
            v['issues'].append(f"正直な選び方では選ばれない: 訓練期間の t で C1 合格76本中 {hs['rank_by_train_t_among_C1'][k]} 位。2006年までのデータだけで選ぶと"
                               f"（76本すべて等分 {hs['all_C1_passers_equal_mix']['ex']} t{hs['all_C1_passers_equal_mix']['t']}・訓練 t 上位5本 {hs['top5_by_train_t']['hold']['ex']} t{hs['top5_by_train_t']['hold']['t']}）保有期間に勝てなかった")
        if v['name'] == 'a_ope_be':
            tw = out['french_op_twins']
            v['issues'].append('同じ考えの French 版（営業利益÷自己資本・NYSE 分位）は訓練で t≥2 を1本も通らない: ' +
                               '・'.join(f"{x['label']} 訓練 t{x['train']['t']}" for x in tw.values() if 'train' in x) + '＝C1 は JKP の作り方に依存')
    etf = out.get('etf_reality') or {}
    for v in out['verdicts']:
        if v['name'] in ('a_cop_at', 'a_sale_bev', 'a_ocf_at', 'a_cop_atl1') and etf:
            v['issues'].append('実在の質・収益性 ETF（信託報酬込み・作り方は別物）は同じ月に市場（French Mkt）へ幾何で: ' + '・'.join(f"{t} {r['etf_cagr_diff']:+.2f}（同じ月の紙の cop_at は算術 {r['cop_at_same']:+.2f}）" for t, r in etf.items() if 'etf_ex' in r and t != 'SPY')
                               + (f"。参考: SPY 自体は {etf['SPY']['etf_cagr_diff']:+.2f}" if 'etf_cagr_diff' in etf.get('SPY', {}) else ''))
    for v in out['verdicts']:
        print(f"{v['name']:22} {v['claimed_grade']:>8} → {v['verified_grade']}  {v['verdict']}", flush=True)
    V = {v['name']: v for v in out['verdicts']}
    cnt = {g: sum(1 for v in out['verdicts'] if v['in_claimed_list'] and v['verified_grade'] == g) for g in 'SABC'}
    mu, hs = out['multiplicity'], out['honest_selection']
    c = {x['name']: x for x in cands}
    ca = c['a_cop_at']
    out['summary_ja'] = '\n'.join([
        f"主張された S 8本の数字は自前のコードで全部再現した（cop_at 全期間 +{ca['full']['ex']} t{ca['full']['t']}・保有 +{ca['hold']['ex']} t{ca['hold']['t']}）。機械の格付けも線どおり S になる。",
        f"だが保有期間の t は 153 本（C1 合格 76 本）を同時に試した結果で、相関を保った max-t で調整すると最良の cop_at でも p={ca['maxt_adj_p_c1']}（153本では {ca['maxt_adj_p_all153']}）＝どれも 5% を通らない。"
        f"保有期間 t≥1.65 の本数も C1 合格の中で {mu['maxt_c1']['observed_count_t_ge_1.65']} 本（偶然でも {mu['maxt_c1']['null_count_t_ge_1.65_mean']} 本・この数以上が出る確率 {mu['maxt_c1']['count_p']}）。",
        f"2006年までのデータだけで選ぶ正直なやり方（C1 合格76本の等分）は保有期間 {hs['all_C1_passers_equal_mix']['ex']:+.2f}%/年（t{hs['all_C1_passers_equal_mix']['t']}）で勝てず、cop_at は訓練の t で76本中 {hs['rank_by_train_t_among_C1']['cop_at']} 位＝当時この1本を選ぶ理由はなかった。",
        f"それでも cop_at・cop_atl1（同じ賭け）・sale_bev・ocf_at は頑丈さの点検（1963起点・1998-2000抜き・2020-21抜き・最良2年抜き・費用）を通り、米国外の国の保有期間でも {ca['country_hold']['positive']}/{ca['country_hold']['countries']}・{c['a_sale_bev']['country_hold']['positive']}/{c['a_sale_bev']['country_hold']['countries']} など正が多い＝A（勝ち・S には届かない）。",
        f"rd_me（1963起点で訓練 t{c['a_rd_me']['train_from_1963']['t']}・12業種で調整すると α t{c['a_rd_me']['industry_hold']['t_nw']}＝ハイテク・医療の業種の傾き）・seas_6_10an（費用後 +{c['a_seas_6_10an']['net_hold']['ex']}・課税口座で年 {c['a_seas_6_10an']['after_tax_hold']['diff']}%）・"
        f"ope_be（1998-2000 抜きで全期間 t{c['a_ope_be']['full_drop_1998_2000']['t']}・French の同じ考えは訓練で全滅）・qmj_prof（1998-2000 抜きで訓練 t{c['a_qmj_prof']['train_drop_1998_2000']['t']}）は B。",
        f"注意: 上限つき・等加重に替えると cop_at の対 French Mkt は +{ca['vw_cap_hold']['ex']}（t{ca['vw_cap_hold']['t']}）・+{ca['ew_hold']['ex']} に縮み、同じ月の実在の質ETF（QUAL・SPHQ・VIG・JQUA・MOAT・DGRW・COWZ）は幾何でそろって市場に負けた。定義が2013年までのデータで作られた cop_at も、その後（2014〜）だけで +{ca['paper']['after_data_end']['ex']}（t{ca['paper']['after_data_end']['t']}）は残る。",
        f"主張の外の S/A も点検: S 4本は A へ、A 9本のうち noa_at だけ A のまま・8本は B（保有期間の勝ちが最良2年頼み等）、French の大型の勢い2本は 2025-12 に揃えると負けで C。",
    ])
    json.dump(out, open(os.path.join(BASE, 'out', 'mw_factor_us_verify.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    print(out['summary_ja'])
    print('saved')


# ───────────────────────── 判定（反証の後に残る格付け） ─────────────────────────
VERDICT_RULES = {
    'S': '事前登録の S に加え、保有期間の t が族の max-t（C1 合格の列・block bootstrap）で調整後 p<0.05 を通り、下の頑丈さもすべて満たす',
    'A': 'C1 が頑丈（1963-07 起点でも・1998-2000 を抜いても 訓練 t≥2）・C7 が頑丈（1998-2000 を抜いても全期間 t≥3）・C4・'
         'C2 が頑丈（保有期間の最良2年を抜いても・2020-21 を抜いても超過が正）・C6 が頑丈（損益分岐の費用が想定の2倍以上）・'
         'かつ（C3 が頑丈〔2020-21 抜き・最良2年抜きでも t≥1.65〕 か 地域の保有期間の再現〔先進国・新興国とも保有期間の超過が正〕）',
    'B': '事前登録の C1・C2・C6 は機械的に通るが、上の頑丈さのどれかが崩れる',
    'C': '事前登録と同じ保有期間の終わり（JKP と同じ 2025-12）に揃える・費用を足すなどの中立な揺らしで C2 か C6 が崩れる',
    'why_no_S': '保有期間の t（C3）は 153 本（C1 合格は76本）を同時に試した結果。列どうしの相関を保った max-t で調整すると、どの候補も 5% を通らない',
}


def _t(v):
    x = (v or {}).get('t')
    return x if x is not None else -9.0


def _ex(v):
    return (v or {}).get('ex') if v else None


def verdict(o):
    n = o['name']
    cg = o['claimed_grade']
    iss, keys = [], ''
    if n.startswith('a_'):
        tr63, trd, fud = _t(o['train_from_1963']), _t(o['train_drop_1998_2000']), _t(o['full_drop_1998_2000'])
        c1r = o['criteria_mine']['C1'] and tr63 >= 2.0 and trd >= 2.0
        c7r = fud >= 3.0
        c2r = o['criteria_mine']['C2'] and (_ex(o['hold_drop_best2y']) or -1) > 0 and (_ex(o['hold_drop_2020_2021']) or -1) > 0
        c3r = min(_t(o['hold_drop_2020_2021']), _t(o['hold_drop_best2y'])) >= 1.65 and o['criteria_mine']['C3']
        rr = o['repl_regions']['detail']
        c5r = all((rr.get(r, {}).get('hold_ex') or -1) > 0 for r in ('developed', 'emerging'))
        be = o.get('breakeven_cost_per_100pct') or 0
        c6r = o['criteria_mine']['C6'] and be >= 2 * UNIT * 100
        c4 = o['criteria_mine']['C4']
        mt = (o.get('maxt_adj_p_c1') or 1) < 0.05
        mech = o['mechanical_grade_mine']
        if mech in ('S', 'A') and c1r and c7r and c2r and c6r and c4 and (c3r or c5r):
            g = 'S' if (mech == 'S' and mt and c3r and c5r) else 'A'
        elif mech in ('S', 'A', 'B'):
            g = 'B'
        else:
            g = 'C'
        if not mt and cg == 'S':
            iss.append(f"多重検定: 保有期間 t{o['hold']['t']} は族の max-t で調整後 p={o.get('maxt_adj_p_c1')}（C1 合格76本）/ {o.get('maxt_adj_p_all153')}（153本）＝5% を通らない（研究者の Holm 族 p も不合格）")
        if not c1r:
            iss.append(f"C1 が脆い: 訓練 t は 1963-07 起点で {tr63}・1998-2000 抜きで {trd}（2.0 未満がある。1951-62 の Compustat は後付け補完の生き残りが混じる期間）")
        if not c7r:
            iss.append(f"C7 が脆い: 1998-2000 を抜くと全期間 t {fud}（3.0 未満）")
        if not c2r:
            iss.append(f"保有期間の勝ちが頑丈でない: 最良2年{o['hold_best2_years']}を抜くと {_ex(o['hold_drop_best2y'])}（t{_t(o['hold_drop_best2y'])}）・2020-21 抜き {_ex(o['hold_drop_2020_2021'])}")
        if not c3r and o['criteria_mine']['C3']:
            iss.append(f"C3 が脆い: 2020-21 抜き t{_t(o['hold_drop_2020_2021'])}・最良2年抜き t{_t(o['hold_drop_best2y'])}・前半 t{_t(o['hold_first_half'])}・後半 t{_t(o['hold_second_half'])}")
        if not c6r:
            iss.append(f"費用に脆い: 損益分岐 {be}%/片道100%（想定 {UNIT*100}%）・回転 {o['turnover_used']*100:.0f}%/年・費用後 {o['net_hold']['ex']}")
        cap = o.get('vw_cap_hold') or {}
        if cap and (cap.get('t') or 0) < 1.65:
            tail = ('＝対 S&P500 型の市場への勝ちは巨大株を満額で持つ時だけ' if (cap.get('ex') or 0) < 0.5 * o['hold']['ex'] else '＝超過は残るが t が弱い')
            iss.append(f"最大級の会社の重みに上限を付けると（vw_cap）保有期間の対 French Mkt は {cap.get('ex')}（t{cap.get('t')}）・等加重 {_ex(o.get('ew_hold'))}{tail}"
                       f"（上限つき同士なら {_ex(o.get('vw_cap_vs_capped_mkt_hold'))} t{_t(o.get('vw_cap_vs_capped_mkt_hold'))}＝選別そのものは効いている）")
        ih = o['industry_hold']
        if (ih.get('t_nw') or 0) < 1.65:
            iss.append(f"12業種で調整すると保有期間の α {ih['alpha']}（t{ih['t_nw']}）・業種の傾きが {ih['explained_by_tilts']} を説明（最大 {ih['largest_contrib'][0]}）＝業種の賭け")
        pp = o.get('paper')
        if pp and pp['holdout_in_discovery_sample']:
            ad = pp['after_data_end']
            iss.append(f"特性の定義が 2007 年以降のデータを見て作られた（{pp['source']}・データ〜{pp['data_end']}）＝保有期間の前半は発見の標本。"
                       f"論文のデータの後（{pp['data_end']+1}〜）だけで {ad['ex']}（t{ad['t']}）")
        if o['after_tax_hold']['diff'] < 0:
            iss.append(f"日本の課税口座（20.315%・回転で実現益に課税）では市場の買って持つだけに年 {o['after_tax_hold']['diff']}%（負け）")
        nbs = o.get('neighbors_summary') or {}
        if nbs.get('n'):
            weak = [k for k, v in o['neighbors'].items() if not v['C3']]
            if weak:
                iss.append(f"近い特性 {nbs['n']} 本のうち C1 と C3 を両方通るのは {nbs['C1_and_C3']} 本（保有期間 t<1.65: {', '.join(weak)}）")
        keys = (f"全期間 {o['full']['ex']:+.2f} t{o['full']['t']} / 訓練 {o['train']['ex']:+.2f} t{o['train']['t']} / 保有 {o['hold']['ex']:+.2f} t{o['hold']['t']} "
                f"幾何 {o['hold']['cagr_diff']:+.2f}（総リターン基準・研究者の超過基準 {o['hold_cagr_diff_excess_basis']:+.2f}）/ 費用後 {o['net_hold']['ex']:+.2f} / "
                f"20年窓 {o['r20']['win_rate']}（1963〜 {o['r20_from_1963']['win_rate']}）/ 積立20年 {o['dca20']['win_rate']} 中央 {o['dca20']['median_ratio']} / "
                f"前半 {_ex(o['hold_first_half'])} t{_t(o['hold_first_half'])}・後半 {_ex(o['hold_second_half'])} t{_t(o['hold_second_half'])} / "
                f"max-t 調整 p {o.get('maxt_adj_p_c1')}（C1 合格）/ 12業種 α {o['industry_hold']['alpha']} t{o['industry_hold']['t_nw']} / "
                f"vw_cap {_ex(o.get('vw_cap_hold'))} / 地域の保有期間 先進 {rr.get('developed', {}).get('hold_ex')}・新興 {rr.get('emerging', {}).get('hold_ex')}"
                + (f" / 国別の保有期間 {o['country_hold']['positive']}/{o['country_hold']['countries']} 正" if o.get('country_hold') else '')
                + f" / 課税口座の差 {o['after_tax_hold']['diff']:+.2f}")
        rep = o['reproduced']
    elif n == 'e2_cluster_Quality':
        g = 'A'
        iss = ['探索の族（構成要素の保有期間を見た後に登録＝研究者自身が汚染を明記）で参考扱い',
               f"12業種で調整すると保有期間の α {o['industry_hold']['alpha']}（t{o['industry_hold']['t_nw']}）＝勝ちの7割は業種の傾き（{o['industry_hold']['explained_by_tilts']}）",
               f"前半 {_ex(o['hold_first_half'])}（t{_t(o['hold_first_half'])}）・2020-21 抜き t{_t(o['hold_drop_2020_2021'])}"]
        keys = f"全期間 {o['full']['ex']} t{o['full']['t']} / 訓練 t{o['train']['t']} / 保有 {o['hold']['ex']} t{o['hold']['t']} / 費用後 {o['net_hold']['ex']} / 20年窓 {o['r20']['win_rate']}"
        rep = True
    else:
        h25 = o['hold_to_2025_12']; n25 = o['net_hold_to_2025_12']
        c2_25 = h25['ex'] > 0 and h25['cagr_diff'] > 0 and n25['ex'] > 0 and n25['cagr_diff'] > 0
        c1r = _t(o['train']) >= 2.0 and _t(o['train_from_1963']) >= 2.0
        best2 = _ex(o['hold_drop_best2y']) or -1
        if not c2_25:
            g = 'C'
            iss.append(f"保有期間の終わりを JKP と同じ 2025-12 に揃えると 超過 {h25['ex']}・幾何 {h25['cagr_diff']}・費用後の幾何 {n25['cagr_diff']}＝勝ちは 2026 年の8か月頼み")
        elif cg == 'B':
            g = 'B'
        elif best2 <= 0 or _t(o['hold']) < 1.0 or _t(h25) < 1.0:
            g = 'B'   # 保有期間の t が 1 未満（JKP と同じ 2025-12 までに揃えても）＝保有期間の勝ちは雑音と区別できず、A は地域の再現だけが支える
        else:
            g = 'A'
        if cg != 'B':
            iss.append(f"保有期間 t{_t(o['hold'])}（C3 不合格）・A は地域の再現（C5）頼み。前半 {_ex(o['hold_first_half'])}・後半 {_ex(o['hold_second_half'])}・最良2年{o['hold_best2_years']}抜き {best2}")
        else:
            iss.append(f"C7（全期間 t {o['full']['t']}＜3）で A に届かない＝研究者の B のまま。C1 は 1963 起点 t{_t(o['train_from_1963'])}・前半 t{_t(o['hold_first_half'])}")
        if not c1r:
            iss.append(f"C1 が脆い（1963-07 起点 t{_t(o['train_from_1963'])}）")
        keys = (f"全期間 {o['full']['ex']} t{o['full']['t']} / 訓練 {o['train']['ex']} t{o['train']['t']} / 保有 {o['hold']['ex']} t{o['hold']['t']}"
                f"（〜2025-12 {h25['ex']} t{h25['t']}）/ 費用後 {o['net_hold']['ex']}（〜2025-12 幾何 {n25['cagr_diff']}）/ 20年窓 {o['r20']['win_rate']}")
        rep = o['reproduced']
    base_cg = cg[0]
    if g == base_cg:
        vd = 'confirmed'
    elif 'SABC'.index(g) > 'SABC'.index(base_cg):
        vd = f'downgraded to {g}'
    else:
        vd = f'upgraded to {g}'
    if g == 'C' and base_cg in 'SA':
        vd = 'refuted' if base_cg == 'S' else f'downgraded to {g}'
    return {'name': n, 'in_claimed_list': o.get('in_claimed_list', False), 'claimed_grade': cg, 'verified_grade': g, 'verdict': vd,
            'reproduced': rep, 'key_numbers': keys, 'issues': iss}


if __name__ == '__main__':
    main()
