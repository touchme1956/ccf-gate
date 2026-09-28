#!/usr/bin/env python3
"""night/mw_gate_proxy.py — 角度 gate_proxy（読むだけ・門の判定・採点・配分には不使用）

問い: 門の考え方（index.html の Ω・堀・キル・四関門＝『壊れない質の会社を買う』）を JKP の公開特徴で写し取った
買いだけのポートフォリオは、純粋な時価加重の市場に勝ったか——とくに米国外の各国・地域・日本・米国の1990年より前で。

事前登録: out/mw_gate_proxy_prereg.json（写しの対応表・主の5本・探索の3本・期間・費用・国パネル・判定は全部そこ）。
線（C1〜C8・S/A/B/C）は out/mw_prereg.json のまま mw_common.grade で当てる。
結果 → out/mw_gate_proxy.json
"""
import os, sys, json, math, random, subprocess, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

try:
    import numpy as np
except ImportError:  # 正直な選び方の検定だけ numpy を使う
    np = None

BASE = M.BASE
ANGLE = 'gate_proxy'
PREREG = 'out/mw_gate_proxy_prereg.json'
START_US = 196307
END_JKP = 202512
PRE1990_END = 198912
NMIN = 10
UNIT_COST = 0.002
MIX_REBAL = 0.10

# ───────────────────────── 事前登録の写し（対応表） ─────────────────────────
MEASURES = {
    'M01_roic': [('ebit_bev', 1)],
    'M02_opm': [('ebit_sale', 1)],
    'M03_gpa': [('gp_at', 1)],
    'M04_conv': [('oaccruals_ni', -1)],
    'M05_accr': [('oaccruals_at', -1)],
    'M06_lev': [('netdebt_me', -1)],
    'M07_z': [('z_score', 1)],
    'M08_intcov': [('o_score', -1)],
    'M09_p1': [('ni_ivol', -1), ('ocfq_saleq_std', -1)],
    'M10_p2': [('qmj_safety', 1)],
    'M11_growth': [('sale_gr3', 1)],
    'M12_roiic': [('qmj_growth', 1)],
    'M13_shy': [('eqnpo_me', 1)],
    'M14_dil': [('chcsho_12m', -1)],
    'M15_roict': [('niq_be_chg1', 1)],
    'M16_moat': [('ni_ar1', 1)],
}
CORE = {
    'C1_roic': [('ebit_bev', 1)],
    'C2_moat': [('gp_at', 1)],
    'C3_safety': [('z_score', 1), ('netdebt_me', -1)],
    'C4_dil': [('chcsho_12m', -1)],
    'C5_accr': [('oaccruals_at', -1)],
}
KILLS = {
    'K1_roic': [('ebit_bev', 1)],
    'K2_nde': [('netdebt_me', -1)],
    'K3_intcov': [('o_score', -1)],
    'K4_z': [('z_score', 1)],
}
# E1: 文献の向きと食い違う2本を外す
AGREE = {k: v for k, v in MEASURES.items() if k != 'M11_growth'}
AGREE['M09_p1'] = [('ocfq_saleq_std', -1)]
TURN = {'ebit_bev': 0.5, 'ebit_sale': 0.4, 'gp_at': 0.4, 'oaccruals_ni': 1.2, 'oaccruals_at': 1.2, 'netdebt_me': 0.6,
        'z_score': 0.6, 'o_score': 0.8, 'ni_ivol': 0.4, 'ocfq_saleq_std': 0.5, 'qmj_safety': 0.6, 'sale_gr3': 0.8,
        'qmj_growth': 0.8, 'eqnpo_me': 0.8, 'chcsho_12m': 1.0, 'niq_be_chg1': 2.0, 'ni_ar1': 0.5}
CHARS = sorted({c for d in (MEASURES, CORE, KILLS) for v in d.values() for c, _ in v})
GATE15 = ['eqnpo_me', 'gp_at', 'ope_be', 'ebit_sale', 'qmj', 'qmj_prof', 'qmj_growth', 'qmj_safety', 'z_score',
          'earnings_variability', 'at_gr1', 'netdebt_me', 'debt_gr3', 'chcsho_12m', 'oaccruals_at']
AGGREGATES = {'all_countries', 'all_regions', 'world', 'world_ex_us', 'developed', 'emerging', 'frontier', 'usa'}
REGIONS = ['developed', 'emerging', 'world_ex_us', 'jpn', 'frontier']

LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── 取得 ─────────────────────────
_CACHE = {}
_DIR = None


def jkp_dir():
    """JKP の文献の向き（direction 列・成績ではない）"""
    global _DIR
    if _DIR is None:
        _DIR = {}
        for x in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
            if x['direction'] not in ('', 'na', 'NA'):
                _DIR[x['name']] = int(float(x['direction']))
    return _DIR


def load(region, weighting='vw', keep=None):
    """JKP all_factors 三分位 → {特徴: {'1.0'|'2.0'|'3.0': {ym: (超過, n)}}}。keep があればその特徴だけ"""
    key = (region, weighting, None if keep is None else tuple(sorted(keep)))
    if key in _CACHE:
        return _CACHE[key]
    d = {}
    for x in M.jkp_rows(region, 'all_factors', 'portfolios', weighting):
        nm = x['name']
        if keep is not None and nm not in keep:
            continue
        if x['ret'] in ('', 'NA', 'na'):
            continue
        nv = x.get('n')
        n = int(float(nv)) if nv not in (None, '', 'NA', 'na') else None
        d.setdefault(nm, {}).setdefault(x['pf'], {})[M._ym(x['date'])] = (float(x['ret']), n)
    _CACHE[key] = d
    return d


FF = M.ff_factors()
MKT, RF, MKTRF = FF['mkt'], FF['rf'], FF['mktrf']


def total(ex):
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


def win(d, a=None, z=None):
    return {k: v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)}


# ───────────────────────── 袖と合成 ─────────────────────────
def pfkey(dirn, which):
    if which == 'mid':
        return '2.0'
    good, bad = ('3.0', '1.0') if dirn > 0 else ('1.0', '3.0')
    return good if which == 'good' else bad


NDROP = {}


def tser(D, c, dirn, which):
    p = D.get(c, {}).get(pfkey(dirn, which), {})
    out = {}
    for ym, (r, n) in p.items():
        if n is not None and n >= NMIN:
            out[ym] = r
    return out


def fser(D, c, dirn):
    g, m = tser(D, c, dirn, 'good'), tser(D, c, dirn, 'mid')
    return {k: (g[k] + m[k]) / 2 for k in g if k in m}


def nser(D, c, dirn):
    g, m, b = tser(D, c, dirn, 'good'), tser(D, c, dirn, 'mid'), tser(D, c, dirn, 'bad')
    return {k: (g[k] + m[k] + b[k]) / 3 for k in g if k in m and k in b}


def mdiff(a, b):
    """yyyymm の差（月数）a−b"""
    return (a // 100 - b // 100) * 12 + (a % 100 - b % 100)


def rser(D, c, dirn, mkt):
    """E3: 過去36か月の回帰で推定した時価の割合で (a×良 + b×中)÷(a+b)"""
    g, m, b = tser(D, c, dirn, 'good'), tser(D, c, dirn, 'mid'), tser(D, c, dirn, 'bad')
    ks = sorted(k for k in g if k in m and k in b and k in mkt)
    out = {}
    for i, k in enumerate(ks):
        w = [j for j in ks[max(0, i - 36):i] if 1 <= mdiff(k, j) <= 36]
        if len(w) < 24:
            continue
        x1 = [g[j] - b[j] for j in w]; x2 = [m[j] - b[j] for j in w]; y = [mkt[j] - b[j] for j in w]
        s11 = math.fsum(u * u for u in x1); s22 = math.fsum(u * u for u in x2); s12 = math.fsum(u * v for u, v in zip(x1, x2))
        s1y = math.fsum(u * v for u, v in zip(x1, y)); s2y = math.fsum(u * v for u, v in zip(x2, y))
        det = s11 * s22 - s12 * s12
        if abs(det) < 1e-18:
            continue
        a = (s1y * s22 - s2y * s12) / det
        bb = (s2y * s11 - s1y * s12) / det
        a = min(1.0, max(0.0, a)); bb = min(1.0, max(0.0, bb))
        if a + bb <= 0.05:
            continue
        out[k] = (a * g[k] + bb * m[k]) / (a + bb)
    return out


def series_for(D, c, d, mode, mkt=None):
    if mode in ('good', 'mid', 'bad'):
        return tser(D, c, d, mode)
    if mode == 'filt':
        return fser(D, c, d)
    if mode == 'neutral':
        return nser(D, c, d)
    if mode == 'reg':
        return rser(D, c, d, mkt)
    raise ValueError(mode)


def sleeve(D, proxies, mode, mkt=None):
    ss = [series_for(D, c, d, mode, mkt) for c, d in proxies]
    out = {}
    for k in set().union(*ss):
        v = [s[k] for s in ss if k in s]
        if v:
            out[k] = math.fsum(v) / len(v)
    return out


def composite(D, measures, mode, mkt=None):
    sl = {m: sleeve(D, px, mode, mkt) for m, px in measures.items()}
    need = math.ceil(2 * len(measures) / 3)
    out, cnt = {}, []
    for k in sorted(set().union(*sl.values())):
        v = [s[k] for s in sl.values() if k in s]
        if len(v) >= need:
            out[k] = math.fsum(v) / len(v)
            cnt.append(len(v))
    info = {'need': need, 'months': len(out), 'from': min(out) if out else None, 'to': max(out) if out else None,
            'avg_sleeves': round(sum(cnt) / len(cnt), 2) if cnt else None,
            'sleeve_months': {m: len(s) for m, s in sl.items()}}
    return out, info


def turnover(measures, mode):
    t = st.mean(st.mean(TURN.get(c, 0.8) for c, _ in px) for px in measures.values())
    if mode in ('filt', 'reg'):
        t *= 0.5
    return round(t + MIX_REBAL, 3)


# ───────────────────────── 評価 ─────────────────────────
def eval_us(ex, to, name):
    s = win(total(ex), START_US, END_JKP)
    full = M.excess_stats(s, MKT)
    train = M.excess_stats(s, MKT, z=M.TRAIN_END)
    hold = M.excess_stats(s, MKT, a=M.HOLD_START)
    net = M.apply_cost(s, to, UNIT_COST)
    net3 = M.apply_cost(s, to, UNIT_COST * 3)
    o = {'name': name, 'turnover_oneway_per_year': to, 'full': full, 'train': train, 'hold': hold,
         'recent': M.excess_stats(s, MKT, a=M.RECENT_START),
         'pre1990': M.excess_stats(s, MKT, z=PRE1990_END),
         '1990_2006': M.excess_stats(s, MKT, a=199001, z=M.TRAIN_END),
         'net_full': M.excess_stats(net, MKT), 'net_hold': M.excess_stats(net, MKT, a=M.HOLD_START),
         'stress3x_hold': M.excess_stats(net3, MKT, a=M.HOLD_START),
         'roll20': M.rolling(s, MKT, 20), 'dca20': M.dca(s, MKT, 20),
         'maxdd_s': round(M.maxdd(s) * 100, 1), 'maxdd_mkt_same': round(M.maxdd({k: MKT[k] for k in s if k in MKT}) * 100, 1),
         'sharpe_full': (M.sharpe(s, RF), M.sharpe({k: MKT[k] for k in s if k in MKT}, RF))}
    return o, s


def brief(x):
    return None if x is None else {k: x.get(k) for k in ('from', 'to', 'years', 'ex_ann', 't', 'cagr_diff', 'te', 'beta')}


def eval_region(ex, mk, to):
    s, b = total(ex), total(mk)
    ks = set(s) & set(b)
    s = {k: s[k] for k in ks}; b = {k: b[k] for k in ks}
    net = M.apply_cost(s, to, UNIT_COST)
    return {'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END),
            'hold': M.excess_stats(s, b, a=M.HOLD_START), 'recent': M.excess_stats(s, b, a=M.RECENT_START),
            'net_hold': M.excess_stats(net, b, a=M.HOLD_START), 'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20)}, s, b


# ───────────────────────── 国パネル ─────────────────────────
def country_list():
    av = json.load(open(os.path.join(BASE, 'out', '_mw_cache', 'jkp_availability.json')))
    return [r for r in av['portfolios'] if r not in AGGREGATES]


def panel(builders):
    """builders: {名前: (measures, mode)} → 国ごとの成績・数・プールした t"""
    res = {nm: {'by_country': {}, 'pooled_rows': {}} for nm in builders}
    for cc in country_list():
        try:
            D = load(cc, 'vw', keep=set(CHARS))
            mk = M.jkp_mkt(cc, 'vw')
        except Exception as e:  # noqa
            log('国の取得失敗', cc, e)
            continue
        for nm, (meas, mode) in builders.items():
            ex, info = composite(D, meas, mode, mk if mode == 'reg' else None)
            s, b = total(ex), total(mk)
            ks = sorted(set(s) & set(b))
            if len(ks) < 240:
                if ks:
                    res[nm]['by_country'][cc] = {'months': len(ks), 'counted': False}
                continue
            f = M.excess_stats(s, b)
            pre = M.excess_stats(s, b, z=M.TRAIN_END)
            post = M.excess_stats(s, b, a=M.HOLD_START)
            npre = sum(1 for k in ks if k <= M.TRAIN_END); npost = sum(1 for k in ks if k >= M.HOLD_START)
            res[nm]['by_country'][cc] = {'months': len(ks), 'counted': True, 'from': ks[0], 'to': ks[-1],
                                         'avg_sleeves': info['avg_sleeves'],
                                         'full': brief(f), 'pre2007': brief(pre) if npre >= 60 else None,
                                         'post2007': brief(post) if npost >= 60 else None}
            for k in ks:
                res[nm]['pooled_rows'].setdefault(k, []).append(s[k] - b[k])
    out = {}
    for nm, r in res.items():
        bc = r['by_country']
        counted = {c: v for c, v in bc.items() if v.get('counted')}
        pos = lambda per: sum(1 for v in counted.values() if v.get(per) and v[per]['ex_ann'] > 0)
        tot = lambda per: sum(1 for v in counted.values() if v.get(per))
        pooled = {k: sum(v) / len(v) for k, v in r['pooled_rows'].items()}

        def pstat(a=None, z=None):
            ks = sorted(k for k in pooled if (a is None or k >= a) and (z is None or k <= z))
            if len(ks) < 24:
                return None
            x = [pooled[k] for k in ks]
            t = M.nw_t(x)
            return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'ex_ann': round(st.mean(x) * 1200, 2),
                    't': round(t, 2) if t is not None else None,
                    'avg_countries': round(st.mean(len(r['pooled_rows'][k]) for k in ks), 1)}
        out[nm] = {'countries_counted': len(counted),
                   'positive_full': pos('full'), 'n_full': tot('full'),
                   'positive_pre2007': pos('pre2007'), 'n_pre2007': tot('pre2007'),
                   'positive_post2007': pos('post2007'), 'n_post2007': tot('post2007'),
                   'pooled_full': pstat(), 'pooled_pre2007': pstat(z=M.TRAIN_END), 'pooled_post2007': pstat(a=M.HOLD_START),
                   'repl': {'regions': len(counted), 'positive': pos('full')},
                   'by_country': bc}
        log(f"国パネル {nm}: 国{len(counted)} 全期間 正{pos('full')}/{tot('full')} 〜2006 正{pos('pre2007')}/{tot('pre2007')} "
            f"2007〜 正{pos('post2007')}/{tot('post2007')} プール 全{out[nm]['pooled_full']} 後{out[nm]['pooled_post2007']}")
    return out


# ───────────────────────── 業種調整 ─────────────────────────
def ols(y, X):
    """y: list, X: list of rows（定数は含めない）→ (切片, 係数)。numpy が無ければ正規方程式を自前で"""
    if np is not None:
        A = np.column_stack([np.ones(len(y)), np.array(X)])
        coef, *_ = np.linalg.lstsq(A, np.array(y), rcond=None)
        return float(coef[0]), [float(c) for c in coef[1:]]
    raise RuntimeError('numpy が要る')


def industry_alpha(s_tot):
    ind = M.french_series('12_Industry_Portfolios', 'Value Weight')
    cols = sorted(ind)
    ks = sorted(k for k in s_tot if k in RF and all(k in ind[c] for c in cols))
    y = [s_tot[k] - RF[k] for k in ks]
    X = [[ind[c][k] - RF[k] for c in cols] for k in ks]
    o = {}
    a, b = ols(y, X)
    hedged = [yy - sum(bi * xi for bi, xi in zip(b, xx)) for yy, xx in zip(y, X)]
    t = M.nw_t(hedged)
    o['full_insample'] = {'alpha_ann': round(st.mean(hedged) * 1200, 2), 't': round(t, 2) if t else None, 'from': ks[0], 'to': ks[-1]}
    tr = [i for i, k in enumerate(ks) if k <= M.TRAIN_END]
    ho = [i for i, k in enumerate(ks) if k >= M.HOLD_START]
    a2, b2 = ols([y[i] for i in tr], [X[i] for i in tr])
    h2 = [y[i] - sum(bi * xi for bi, xi in zip(b2, X[i])) for i in ho]
    t2 = M.nw_t(h2)
    tr2 = [y[i] - sum(bi * xi for bi, xi in zip(b2, X[i])) for i in tr]
    t3 = M.nw_t(tr2)
    o['train_insample'] = {'alpha_ann': round(st.mean(tr2) * 1200, 2), 't': round(t3, 2) if t3 else None}
    o['hold_hedged_with_train_betas'] = {'alpha_ann': round(st.mean(h2) * 1200, 2), 't': round(t2, 2) if t2 else None}
    # CAPM（参考）
    yk = [s_tot[k] - RF[k] for k in ks if k in MKTRF]
    xk = [[MKTRF[k]] for k in ks if k in MKTRF]
    ac, bc = ols(yk, xk)
    hc = [yy - bc[0] * xx[0] for yy, xx in zip(yk, xk)]
    tc = M.nw_t(hc)
    o['capm_full'] = {'alpha_ann': round(st.mean(hc) * 1200, 2), 't': round(tc, 2) if tc else None, 'beta': round(bc[0], 3)}
    return o


# ───────────────────────── 正直な選び方の検定 ─────────────────────────
def nw_t_np(x, lag=12):
    n = len(x)
    if n < 24:
        return None
    e = x - x.mean()
    s = (e * e).sum() / n
    for L in range(1, lag + 1):
        s += 2 * (1 - L / (lag + 1)) * (e[L:] * e[:-L]).sum() / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else None


def honest(DU, p1_hold, p1_train, p2_hold, p2_train):
    D = jkp_dir()
    months = [k for k in sorted(MKT) if START_US <= k <= END_JKP]
    names = sorted(c for c in DU if c in D)
    R = np.full((len(months), len(names)), np.nan)
    idx = {k: i for i, k in enumerate(months)}
    for j, c in enumerate(names):
        for k, r in tser(DU, c, D[c], 'good').items():
            if k in idx:
                R[idx[k], j] = r
    rf = np.array([RF[k] for k in months]); mk = np.array([MKT[k] for k in months])
    tr = np.array([k <= M.TRAIN_END for k in months]); ho = np.array([k >= M.HOLD_START for k in months])
    out = {'universe': len(names), 'note': '文献の向き（JKP direction）の良い側の三分位を無作為に選んで等分。可用性は同じ 2/3 の規則・1963-07〜2025-12'}
    for size, ph, pt, lab in ((16, p1_hold, p1_train, 'P1_GATE_ALL'), (5, p2_hold, p2_train, 'P2_GATE_CORE')):
        rnd = random.Random(20260928 + size)
        need = math.ceil(2 * size / 3)
        hx, tx, htt = [], [], []
        for _ in range(4000):
            sel = rnd.sample(range(len(names)), size)
            sub = R[:, sel]
            cnt = (~np.isnan(sub)).sum(1)
            with np.errstate(invalid='ignore'):
                mean = np.nanmean(np.where(np.isnan(sub), np.nan, sub), axis=1)
            ok = cnt >= need
            ex = mean + rf - mk
            h = ex[ok & ho]; t_ = ex[ok & tr]
            hx.append(float(h.mean() * 1200)); tx.append(float(t_.mean() * 1200)); htt.append(nw_t_np(h))
        hs, ts = sorted(hx), sorted(tx)
        out[f'random{size}'] = {
            'compare_to': lab, 'draws': 4000,
            'hold_ex_p10': round(hs[400], 2), 'hold_ex_median': round(hs[2000], 2), 'hold_ex_p90': round(hs[3600], 2),
            'train_ex_median': round(ts[2000], 2), 'train_ex_p90': round(ts[3600], 2),
            'share_hold_ex_pos': round(sum(1 for v in hx if v > 0) / 4000, 3),
            'share_hold_t_ge_1_65': round(sum(1 for v in htt if (v or 0) >= 1.65) / 4000, 3),
            f'{lab}_hold_ex': ph, f'{lab}_hold_percentile': round(sum(1 for v in hx if v < ph) / 4000, 3),
            f'{lab}_train_ex': pt, f'{lab}_train_percentile': round(sum(1 for v in tx if v < pt) / 4000, 3)}
    # 単独の袖（文献の向き）で並べたとき、写しの17特徴の保有期間の順位（参考）
    single = []
    for j, c in enumerate(names):
        col = R[:, j]; ok = ~np.isnan(col) & ho
        if ok.sum() >= 120:
            single.append((float((col[ok] + rf[ok] - mk[ok]).mean() * 1200), c))
    single.sort(reverse=True)
    out['single_sleeve_hold_rank_litdir'] = {c: [x[1] for x in single].index(c) + 1 for c in CHARS if c in [x[1] for x in single]}
    out['single_sleeve_count'] = len(single)
    return out


# ───────────────────────── 城のぶれ ─────────────────────────
def castle_noise(te_p1_hold, a_list):
    tick = ['CW', 'MSFT', 'LRCX', 'ASML', 'TDG']
    ser = {t: M.yahoo(t, '1mo') for t in tick + ['SPY']}
    ks = sorted(k for k in set.intersection(*[set(v) for v in ser.values()]) if k <= 202608)
    ex = [st.mean(ser[t][k] for t in tick) - ser['SPY'][k] for k in ks]
    te = st.stdev(ex) * math.sqrt(12) * 100
    phi = lambda z: 0.5 * math.erfc(-z / math.sqrt(2))
    o = {'tickers': tick, 'from': ks[0], 'to': ks[-1], 'months': len(ks), 'te_castle_vs_spy': round(te, 2),
         'te_gate_all_hold_vs_mkt': te_p1_hold, 'caveat': '今日選ばれた5社の過去＝生き残りの偏りあり。ぶれの大きさを見るためだけに使う（リターンは見ない）', 'cases': []}
    for a in a_list:
        if a is None or a <= 0:
            continue
        for lab, T in (('castle5', te), ('gate_all_broad', te_p1_hold)):
            if not T:
                continue
            o['cases'].append({'alpha_assumed': a, 'portfolio': lab, 'te': round(T, 2),
                               'years_for_t2': round((2 * T / a) ** 2, 1),
                               'prob_lose_to_market_20y': round(phi(-a * math.sqrt(20) / T), 3)})
    return o


# ───────────────────────── 検算 ─────────────────────────
def sanity(DU):
    o = {}
    o['french_mkt_cagr_full'] = round(M.cagr(MKT) * 100, 2)
    o['french_mkt_cagr_2007'] = round(M.cagr(win(MKT, M.HOLD_START)) * 100, 2)
    jm = M.jkp_mkt('usa', 'vw')
    o['jkp_usa_vw_mkt_plus_rf_vs_french_full'] = brief(M.excess_stats(total(jm), MKT, a=START_US))
    o['jkp_usa_vw_mkt_plus_rf_vs_french_hold'] = brief(M.excess_stats(total(jm), MKT, a=M.HOLD_START))
    # 三分位の向き: corr(第3−第1, JKP 符号つき因子) の符号 = direction
    fac = {}
    for x in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
        if x['name'] in CHARS and x['ret'] not in ('', 'NA', 'na'):
            fac.setdefault(x['name'], {})[M._ym(x['date'])] = float(x['ret'])
    D = jkp_dir()
    orient = {}
    for c in CHARS:
        p3 = {k: r for k, (r, n) in DU[c]['3.0'].items()}; p1 = {k: r for k, (r, n) in DU[c]['1.0'].items()}
        ks = sorted(k for k in p3 if k in p1 and k in fac.get(c, {}))
        cr = M.corr([p3[k] - p1[k] for k in ks], [fac[c][k] for k in ks])
        orient[c] = {'corr': round(cr, 3), 'direction': D.get(c), 'ok': (cr > 0) == (D.get(c, 0) > 0)}
    o['tercile_orientation'] = orient
    o['orientation_all_ok'] = all(v['ok'] for v in orient.values())
    # n<10 で落とした月（米国・1963-07〜）
    drop = {}
    for c in CHARS:
        for pf in ('1.0', '2.0', '3.0'):
            rows = [(k, n) for k, (r, n) in DU[c][pf].items() if START_US <= k <= END_JKP]
            drop[f'{c}_{pf}'] = sum(1 for k, n in rows if n is None or n < NMIN)
    o['us_months_dropped_n_lt_10_since_1963'] = {k: v for k, v in drop.items() if v}
    o['us_n_missing_rows'] = sum(1 for c in CHARS for pf in DU[c] for k, (r, n) in DU[c][pf].items() if n is None)
    return o


def verifier_repro(DU):
    D = jkp_dir()
    ss = []
    for c in GATE15:
        g = '3.0' if D[c] > 0 else '1.0'
        ss.append(total(win({k: r for k, (r, n) in DU[c][g].items()}, START_US)))
    ks = set(ss[0])
    for x in ss[1:]:
        ks &= set(x)
    m = {k: math.fsum(x[k] for x in ss) / len(ss) for k in ks}
    return {'train': brief(M.excess_stats(m, MKT, z=M.TRAIN_END)), 'hold': brief(M.excess_stats(m, MKT, a=M.HOLD_START)),
            'expected': 'train +1.13 t2.86 ・ hold +0.82 t2.09（out/mw_combo_us_verify.json H3）'}


# ───────────────────────── 本体 ─────────────────────────
def main():
    sha = subprocess.run(['git', 'log', '-1', '--format=%H', '--', PREREG], cwd=BASE, capture_output=True, text=True).stdout.strip()
    out = {'angle': ANGLE, 'prereg': PREREG, 'prereg_commit': sha, 'global_prereg': 'out/mw_prereg.json'}
    DU = load('usa', 'vw')
    out['sanity'] = sanity(DU)
    log('検算', json.dumps({k: out['sanity'][k] for k in ('french_mkt_cagr_full', 'french_mkt_cagr_2007', 'orientation_all_ok')}, ensure_ascii=False))
    out['verifier_reproduction'] = verifier_repro(DU)
    log('反証の検証 H3 の再現', out['verifier_reproduction'])

    PRIMARY = {'P1_GATE_ALL': (MEASURES, 'good'), 'P2_GATE_CORE': (CORE, 'good'), 'P3_FILTER_ALL': (MEASURES, 'filt'),
               'P4_FILTER_CORE': (CORE, 'filt'), 'P5_FILTER_KILLS': (KILLS, 'filt')}
    EXPLOR = {'E1_GATE_ALL_AGREE': (AGREE, 'good'), 'E2_GATE_ALL_LITDIR': (None, 'good'), 'E3_FILTER_ALL_REG': (MEASURES, 'reg')}
    D = jkp_dir()
    LIT = {k: [(c, D[c]) for c, _ in v] for k, v in MEASURES.items()}
    EXPLOR['E2_GATE_ALL_LITDIR'] = (LIT, 'good')
    jm_us = M.jkp_mkt('usa', 'vw')

    tested, res, series = [], {}, {}
    for fam, block in (('A_primary', PRIMARY), ('E_exploratory', EXPLOR)):
        for nm, (meas, mode) in block.items():
            ex, info = composite(DU, meas, mode, jm_us if mode == 'reg' else None)
            to = turnover(meas, mode)
            o, s = eval_us(ex, to, nm)
            o['family'] = fam; o['availability'] = info
            # 1963-07 より前（遡及の偏りあり・報告のみ）
            o['pre1963'] = M.excess_stats(total(ex), MKT, z=START_US - 1)
            res[nm] = o; series[nm] = s
            log(f"{nm:22s} full {o['full']['ex_ann']:+.2f} t{o['full']['t']} | train {o['train']['ex_ann']:+.2f} t{o['train']['t']} | "
                f"hold {o['hold']['ex_ann']:+.2f} t{o['hold']['t']} cagr {o['hold']['cagr_diff']:+.2f} | net_hold {o['net_hold']['ex_ann']:+.2f} | "
                f"pre1990 {o['pre1990']['ex_ann']:+.2f} t{o['pre1990']['t']} | roll20 {o['roll20'] and o['roll20']['win_rate']} | to {to}")

    # 国パネル（主と探索の8本）
    builders = {nm: v for nm, v in list(PRIMARY.items()) + list(EXPLOR.items())}
    pan = panel(builders)
    out['country_panel'] = pan

    # 判定
    for fam in ('A_primary', 'E_exploratory'):
        names = [n for n, o in res.items() if o['family'] == fam]
        hp = M.holm({n: res[n]['hold']['p'] for n in names})
        for n in names:
            o = res[n]
            g, c = M.grade(o['full'], o['train'], o['hold'], o['roll20'], cost_hold=o['net_hold'], repl=pan[n]['repl'],
                           family_holm_p=hp.get(n))
            o['holm_p_hold'] = hp.get(n); o['grade'] = g; o['criteria'] = c
            o['repl'] = {k: pan[n][k] for k in ('countries_counted', 'positive_full', 'n_full', 'positive_pre2007', 'n_pre2007',
                                               'positive_post2007', 'n_post2007', 'pooled_full', 'pooled_pre2007', 'pooled_post2007')}
            tested.append({'name': n, 'family': fam, 'graded': True, 'grade': g, 'region': 'usa',
                           'hold_ex': o['hold']['ex_ann'], 'hold_t': o['hold']['t'], 'full_t': o['full']['t']})
            log(f"判定 {n}: {g} {c} holm {hp.get(n)} C5 {pan[n]['repl']}")

    # 地域の族 B（参考格付け・C5 N/A）
    regions = {}
    for rg in REGIONS:
        try:
            DR = load(rg, 'vw', keep=set(CHARS)); mk = M.jkp_mkt(rg, 'vw')
        except Exception as e:  # noqa
            regions[rg] = {'error': str(e)}
            log('地域の取得失敗', rg, e)
            continue
        regions[rg] = {}
        for nm, (meas, mode) in PRIMARY.items():
            ex, info = composite(DR, meas, mode)
            if len(set(ex) & set(mk)) < 120:
                regions[rg][nm] = {'months': len(set(ex) & set(mk)), 'skipped': '120か月未満'}
                continue
            o, s, b = eval_region(ex, mk, turnover(meas, mode))
            o['availability'] = info
            regions[rg][nm] = o
    rb = {f'{rg}:{nm}': o for rg, d in regions.items() if isinstance(d, dict) for nm, o in d.items() if isinstance(o, dict) and o.get('full')}
    hpb = M.holm({k: (o['hold'] or {}).get('p') for k, o in rb.items()})
    for k, o in rb.items():
        g, c = M.grade(o['full'], o['train'], o['hold'], o['roll20'], cost_hold=o['net_hold'], repl=None, family_holm_p=hpb.get(k))
        o['grade'] = g; o['criteria'] = c; o['holm_p_hold'] = hpb.get(k)
        tested.append({'name': k, 'family': 'B_regions', 'graded': True, 'grade': g, 'region': k.split(':')[0],
                       'hold_ex': (o['hold'] or {}).get('ex_ann'), 'hold_t': (o['hold'] or {}).get('t'), 'full_t': o['full']['t']})
        log(f"地域 {k:30s} full {o['full']['ex_ann']:+.2f} t{o['full']['t']} train {o['train'] and o['train']['ex_ann']} t{o['train'] and o['train']['t']} "
            f"hold {o['hold'] and o['hold']['ex_ann']} t{o['hold'] and o['hold']['t']} → {g}")
    out['regions'] = regions

    # 頑健性（報告のみ）
    rob = {}
    for wt in ('vw_cap', 'ew'):
        try:
            DW = load('usa', wt, keep=set(CHARS))
        except Exception as e:  # noqa
            rob[wt] = {'error': str(e)}
            continue
        rob[wt] = {}
        for nm, (meas, mode) in PRIMARY.items():
            ex, _ = composite(DW, meas, mode)
            s = win(total(ex), START_US, END_JKP)
            rob[wt][nm] = {'full': brief(M.excess_stats(s, MKT)), 'train': brief(M.excess_stats(s, MKT, z=M.TRAIN_END)),
                           'hold': brief(M.excess_stats(s, MKT, a=M.HOLD_START))}
            tested.append({'name': f'{nm}@{wt}', 'family': 'R_robustness', 'graded': False, 'region': 'usa',
                           'hold_ex': rob[wt][nm]['hold']['ex_ann'], 'hold_t': rob[wt][nm]['hold']['t']})
            log(f"頑健 {wt} {nm}: full {rob[wt][nm]['full']['ex_ann']} t{rob[wt][nm]['full']['t']} hold {rob[wt][nm]['hold']['ex_ann']} t{rob[wt][nm]['hold']['t']}")
    rob['industry_alpha'] = {}
    for nm in PRIMARY:
        rob['industry_alpha'][nm] = industry_alpha(series[nm])
        log('業種調整', nm, rob['industry_alpha'][nm])
    rob['terciles'] = {}
    for lab, meas in (('GATE_ALL', MEASURES), ('GATE_CORE', CORE)):
        rob['terciles'][lab] = {}
        for mode in ('good', 'mid', 'bad', 'neutral'):
            ex, _ = composite(DU, meas, mode)
            s = win(total(ex), START_US, END_JKP)
            rob['terciles'][lab][mode] = {'full': brief(M.excess_stats(s, MKT)), 'train': brief(M.excess_stats(s, MKT, z=M.TRAIN_END)),
                                          'hold': brief(M.excess_stats(s, MKT, a=M.HOLD_START))}
            tested.append({'name': f'{lab}:{mode}', 'family': 'R_terciles', 'graded': False, 'region': 'usa',
                           'hold_ex': rob['terciles'][lab][mode]['hold']['ex_ann'], 'hold_t': rob['terciles'][lab][mode]['hold']['t']})
        log('三分位', lab, {m: (v['full']['ex_ann'], v['hold']['ex_ann']) for m, v in rob['terciles'][lab].items()})
    rob['leave_one_out'] = {}
    for lab, meas in (('P1_GATE_ALL', MEASURES), ('P2_GATE_CORE', CORE)):
        rob['leave_one_out'][lab] = {}
        for m in meas:
            sub = {k: v for k, v in meas.items() if k != m}
            ex, _ = composite(DU, sub, 'good')
            s = win(total(ex), START_US, END_JKP)
            h = M.excess_stats(s, MKT, a=M.HOLD_START); f = M.excess_stats(s, MKT)
            rob['leave_one_out'][lab]['without_' + m] = {'full_ex': f['ex_ann'], 'full_t': f['t'], 'hold_ex': h['ex_ann'], 'hold_t': h['t']}
            tested.append({'name': f'{lab}-{m}', 'family': 'R_leave_one_out', 'graded': False, 'region': 'usa', 'hold_ex': h['ex_ann'], 'hold_t': h['t']})
    rob['single_sleeves_gatedir'] = {}
    for m, px in MEASURES.items():
        s = win(total(sleeve(DU, px, 'good')), START_US, END_JKP)
        f, tr, h = M.excess_stats(s, MKT), M.excess_stats(s, MKT, z=M.TRAIN_END), M.excess_stats(s, MKT, a=M.HOLD_START)
        rob['single_sleeves_gatedir'][m] = {'full': brief(f), 'train': brief(tr), 'hold': brief(h)}
        tested.append({'name': f'sleeve:{m}', 'family': 'R_single_sleeves', 'graded': False, 'region': 'usa', 'hold_ex': h['ex_ann'], 'hold_t': h['t']})
    out['robustness'] = rob

    if np is not None:
        out['honest_selection'] = honest(DU, res['P1_GATE_ALL']['hold']['ex_ann'], res['P1_GATE_ALL']['train']['ex_ann'],
                                         res['P2_GATE_CORE']['hold']['ex_ann'], res['P2_GATE_CORE']['train']['ex_ann'])
        log('正直な選び方', json.dumps({k: v for k, v in out['honest_selection'].items() if k.startswith('random')}, ensure_ascii=False))
    try:
        out['castle_noise'] = castle_noise(res['P1_GATE_ALL']['hold']['te'], [res['P1_GATE_ALL']['hold']['ex_ann'], 0.8])
        log('城のぶれ', out['castle_noise'])
    except Exception as e:  # noqa
        out['castle_noise'] = {'error': str(e)}

    out['results_us'] = res
    out['tested'] = tested
    out['n_tested'] = len(tested)
    out['log'] = LOG
    p = M.save('mw_gate_proxy.json', out)
    log('書いた', p, os.path.getsize(p))


if __name__ == '__main__':
    main()
