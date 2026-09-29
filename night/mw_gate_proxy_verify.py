#!/usr/bin/env python3
"""night/mw_gate_proxy_verify.py — 角度 gate_proxy の反証の検証（読むだけ・門の判定・採点・配分には不使用）

目的: night/mw_gate_proxy.py の主張（米国 P1_GATE_ALL / P2_GATE_CORE = S、P4_FILTER_CORE = A、P3_FILTER_ALL = B、
探索 E1/E2 = S、地域 emerging P1/P2（と P4）= S）を、**別の実装**で数字から作り直し、反証を試みる。

独立性の約束
- mw_common からは**取得だけ**を使う（jkp_rows の元 zip・jkp_mkt・ff_factors・french_tables・french_series）。
- 三分位の読み込み・袖と合成の組み立て・超過・NW t・CAGR 差・転がる20年・積立・費用・格付けの線は全部ここで書き直した
  （numpy の配列で月の添字を持つ。研究者のコードは dict＋statistics）。
- 線は out/mw_prereg.json の C1〜C8 をそのまま（ここで動かさない）。

結果 → out/mw_gate_proxy_verify.json
"""
import os, sys, json, math, csv, io, zipfile, random, itertools, subprocess
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけ

BASE = M.BASE
CACHE = os.path.join(BASE, 'out', '_mw_cache')
Y0 = 1926
NMON = (2026 - Y0 + 1) * 12
NMIN = 10
UNIT = 0.002
REBAL = 0.10
US_A, US_Z = 196307, 202512
TR_Z, HO_A = 200612, 200701


def ix(ym):
    return (ym // 100 - Y0) * 12 + (ym % 100 - 1)


YM = np.array([(Y0 + i // 12) * 100 + (i % 12 + 1) for i in range(NMON)])


def arr_from(d):
    a = np.full(NMON, np.nan)
    for k, v in d.items():
        i = ix(k)
        if 0 <= i < NMON:
            a[i] = v
    return a


# ───────────── 取得（元 zip を自前で読む） ─────────────
_JK = {}


def jkp_pf(region, weighting='vw', keep=None):
    """{(name, pf): 配列（超過・n<10 は nan）} と {(name,pf): n 配列}"""
    key = (region, weighting)
    if key in _JK:
        R, N = _JK[key]
    else:
        p = os.path.join(CACHE, f'jkp_portfolios_{region}_all_factors_{weighting}_monthly.zip')
        if not os.path.exists(p):
            M.jkp_rows(region, 'all_factors', 'portfolios', weighting)  # 取得してキャッシュさせるだけ
        z = zipfile.ZipFile(p)
        rd = csv.reader(io.StringIO(z.read(z.namelist()[0]).decode()))
        hdr = next(rd)
        iN, iP, iNn, iD, iR = hdr.index('name'), hdr.index('pf'), hdr.index('n'), hdr.index('date'), hdr.index('ret')
        R, N = {}, {}
        for row in rd:
            r = row[iR]
            if r in ('', 'NA', 'na'):
                continue
            k = (row[iN], row[iP])
            if k not in R:
                R[k] = np.full(NMON, np.nan); N[k] = np.full(NMON, np.nan)
            d = row[iD]
            i = (int(d[:4]) - Y0) * 12 + int(d[5:7]) - 1
            if not (0 <= i < NMON):
                continue
            R[k][i] = float(r)
            nv = row[iNn]
            N[k][i] = float(nv) if nv not in ('', 'NA', 'na') else np.nan
        _JK[key] = (R, N)
    if keep is None:
        return R, N
    return {k: v for k, v in R.items() if k[0] in keep}, {k: v for k, v in N.items() if k[0] in keep}


def terc(R, N, c, dirn, which):
    if which == 'mid':
        pf = '2.0'
    else:
        good, bad = ('3.0', '1.0') if dirn > 0 else ('1.0', '3.0')
        pf = good if which == 'good' else bad
    k = (c, pf)
    if k not in R:
        return np.full(NMON, np.nan)
    a = R[k].copy()
    a[~(N[k] >= NMIN)] = np.nan  # n 欠測も n<10 も nan（0 で埋めない）
    return a


def char_series(R, N, c, dirn, mode):
    if mode in ('good', 'mid', 'bad'):
        return terc(R, N, c, dirn, mode)
    g, m, b = terc(R, N, c, dirn, 'good'), terc(R, N, c, dirn, 'mid'), terc(R, N, c, dirn, 'bad')
    if mode == 'filt':
        return (g + m) / 2  # 両方ないと nan
    if mode == 'neutral':
        return (g + m + b) / 3
    if mode == 'good_mid_minus_neutral':
        return (g + m) / 2 - (g + m + b) / 3
    raise ValueError(mode)


def build(R, N, measures, mode, need_rule='2/3'):
    """measures: {袖: [(特徴, 向き), ...]}。袖=使える特徴の平均、合成=使える袖の平均（袖が必要数以上の月だけ）"""
    sl = []
    for px in measures.values():
        S = np.vstack([char_series(R, N, c, d, mode) for c, d in px])
        cnt = (~np.isnan(S)).sum(0)
        with np.errstate(invalid='ignore', divide='ignore'):
            v = np.where(cnt > 0, np.nansum(S, 0) / np.maximum(cnt, 1), np.nan)
        sl.append(v)
    S = np.vstack(sl)
    cnt = (~np.isnan(S)).sum(0)
    k = len(measures)
    need = {'2/3': math.ceil(2 * k / 3), 'all': k, 'one': 1}[need_rule]
    with np.errstate(invalid='ignore', divide='ignore'):
        out = np.where(cnt >= need, np.nansum(S, 0) / np.maximum(cnt, 1), np.nan)
    return out


# ───────────── 統計（自前） ─────────────
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


def pnorm2(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def mask(a=None, z=None, drop=()):
    m = np.ones(NMON, bool)
    if a is not None:
        m &= YM >= a
    if z is not None:
        m &= YM <= z
    for lo, hi in drop:
        m &= ~((YM >= lo) & (YM <= hi))
    return m


def st(s, b, a=None, z=None, drop=()):
    m = mask(a, z, drop) & ~np.isnan(s) & ~np.isnan(b)
    n = int(m.sum())
    if n < 24:
        return None
    x, y = s[m], b[m]
    ex = x - y
    t = nwt(ex)
    gs = math.exp(np.log1p(x).mean() * 12) - 1
    gb = math.exp(np.log1p(y).mean() * 12) - 1
    cov = np.cov(x, y, ddof=0)
    return {'from': int(YM[m][0]), 'to': int(YM[m][-1]), 'months': n,
            'ex_ann': round(float(ex.mean() * 1200), 2), 't': None if t is None else round(t, 2),
            'p': None if t is None else round(pnorm2(t), 4),
            'cagr_diff': round((gs - gb) * 100, 2), 'te': round(float(ex.std(ddof=1) * math.sqrt(12) * 100), 2),
            'beta': round(float(cov[0, 1] / cov[1, 1]), 3)}


def roll20(s, b, a=US_A, z=US_Z):
    ok = ~np.isnan(s) & ~np.isnan(b) & mask(a, z)
    res = []
    for y in range(a // 100, 2100):
        lo, hi = y * 100 + 7, (y + 20) * 100 + 6
        if hi > z:
            break
        w = (YM >= lo) & (YM <= hi)
        if (w & ok).sum() < 240 * 0.97:
            continue
        ww = w & ok
        gs = math.exp(np.log1p(s[ww]).sum() / 20) - 1
        gb = math.exp(np.log1p(b[ww]).sum() / 20) - 1
        res.append((y, round((gs - gb) * 100, 2)))
    if not res:
        return None
    v = sorted(r for _, r in res)
    return {'windows': len(res), 'wins': sum(r > 0 for _, r in res), 'win_rate': round(sum(r > 0 for _, r in res) / len(res), 3),
            'median': v[len(v) // 2], 'worst': min(res, key=lambda q: q[1])}


def dca20(s, b, a=US_A, z=US_Z):
    ok = np.where(~np.isnan(s) & ~np.isnan(b) & mask(a, z))[0]
    out = []
    for i in range(0, len(ok) - 240 + 1, 12):
        w = ok[i:i + 240]
        ws = wb = 0.0
        for j in w:
            ws = (ws + 1) * (1 + s[j]); wb = (wb + 1) * (1 + b[j])
        out.append(ws / wb)
    if not out:
        return None
    v = sorted(out)
    return {'windows': len(v), 'win_rate': round(sum(r > 1 for r in v) / len(v), 3), 'median': round(v[len(v) // 2], 3), 'worst': round(v[0], 3)}


def grade(tr, ho, full, rl, net, repl_frac, holm_p):
    c = {'C1': bool(tr and tr['ex_ann'] > 0 and (tr['t'] or 0) >= 2.0),
         'C2': bool(ho and ho['ex_ann'] > 0 and ho['cagr_diff'] > 0),
         'C3': bool(ho and (ho['t'] or 0) >= 1.65),
         'C4': bool(rl and rl['win_rate'] >= 0.8),
         'C5': None if repl_frac is None else repl_frac >= 2 / 3,
         'C6': bool(net and net['ex_ann'] > 0 and net['cagr_diff'] > 0),
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


def holm(pv):
    it = sorted((p, k) for k, p in pv.items() if p is not None)
    m, run, o = len(it), 0.0, {}
    for i, (p, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * p)); o[k] = round(run, 4)
    return o


# ───────────── 写しの定義（事前登録どおり・自分で書き写した） ─────────────
MEAS = {
    'M01_roic': [('ebit_bev', 1)], 'M02_opm': [('ebit_sale', 1)], 'M03_gpa': [('gp_at', 1)],
    'M04_conv': [('oaccruals_ni', -1)], 'M05_accr': [('oaccruals_at', -1)], 'M06_lev': [('netdebt_me', -1)],
    'M07_z': [('z_score', 1)], 'M08_intcov': [('o_score', -1)], 'M09_p1': [('ni_ivol', -1), ('ocfq_saleq_std', -1)],
    'M10_p2': [('qmj_safety', 1)], 'M11_growth': [('sale_gr3', 1)], 'M12_roiic': [('qmj_growth', 1)],
    'M13_shy': [('eqnpo_me', 1)], 'M14_dil': [('chcsho_12m', -1)], 'M15_roict': [('niq_be_chg1', 1)],
    'M16_moat': [('ni_ar1', 1)]}
CORE = {'C1_roic': [('ebit_bev', 1)], 'C2_moat': [('gp_at', 1)], 'C3_safety': [('z_score', 1), ('netdebt_me', -1)],
        'C4_dil': [('chcsho_12m', -1)], 'C5_accr': [('oaccruals_at', -1)]}
AGREE = {k: v for k, v in MEAS.items() if k != 'M11_growth'}
AGREE['M09_p1'] = [('ocfq_saleq_std', -1)]
TURN = {'ebit_bev': 0.5, 'ebit_sale': 0.4, 'gp_at': 0.4, 'oaccruals_ni': 1.2, 'oaccruals_at': 1.2, 'netdebt_me': 0.6,
        'z_score': 0.6, 'o_score': 0.8, 'ni_ivol': 0.4, 'ocfq_saleq_std': 0.5, 'qmj_safety': 0.6, 'sale_gr3': 0.8,
        'qmj_growth': 0.8, 'eqnpo_me': 0.8, 'chcsho_12m': 1.0, 'niq_be_chg1': 2.0, 'ni_ar1': 0.5}
GATE15 = ['eqnpo_me', 'gp_at', 'ope_be', 'ebit_sale', 'qmj', 'qmj_prof', 'qmj_growth', 'qmj_safety', 'z_score',
          'earnings_variability', 'at_gr1', 'netdebt_me', 'debt_gr3', 'chcsho_12m', 'oaccruals_at']
AGG = {'all_countries', 'all_regions', 'world', 'world_ex_us', 'developed', 'emerging', 'frontier', 'usa'}


def turnover(meas, mode):
    t = float(np.mean([np.mean([TURN.get(c, 0.8) for c, _ in px]) for px in meas.values()]))
    if mode == 'filt':
        t *= 0.5
    return t + REBAL


def lit_dirs():
    d = {}
    p = os.path.join(CACHE, 'jkp_factor_usa_all_factors_vw_monthly.zip')
    if not os.path.exists(p):
        M.jkp_rows('usa', 'all_factors', 'factor', 'vw')
    z = zipfile.ZipFile(p)
    rd = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode()))
    for x in rd:
        if x['direction'] not in ('', 'NA', 'na') and x['name'] not in d:
            d[x['name']] = int(float(x['direction']))
    return d


LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def main():
    out = {'angle': 'gate_proxy', 'role': 'adversarial verifier（反証の検証）', 'target': 'night/mw_gate_proxy.py → out/mw_gate_proxy.json',
           'independence': 'mw_common は取得だけ。三分位の読み込み・合成・統計・格付けはこのファイルで書き直した（numpy 配列）'}
    # ─── 事前登録の時刻 ───
    g = lambda *a: subprocess.run(['git'] + list(a), cwd=BASE, capture_output=True, text=True).stdout.strip()
    out['timeline'] = {
        'prereg_commit': g('log', '-1', '--format=%h %ad %s', '--date=iso', '--', 'out/mw_gate_proxy_prereg.json'),
        'results_commit': g('log', '-1', '--format=%h %ad %s', '--date=iso', '--', 'out/mw_gate_proxy.json'),
        'factor_us_results_commit': g('log', '-1', '--format=%h %ad', '--date=iso', '--', 'out/mw_factor_us.json'),
        'combo_us_verify_commit': g('log', '-1', '--format=%h %ad', '--date=iso', '--', 'out/mw_combo_us_verify.json'),
        'code_lines_deleted_between_prereg_and_results': [l for l in g('diff', '5533996', '3c9c122', '--', 'night/mw_gate_proxy.py').splitlines() if l.startswith('-') and not l.startswith('---')],
    }
    ff = M.ff_factors()
    RF = arr_from(ff['rf']); MKT = arr_from(ff['mkt'])
    R, N = jkp_pf('usa', 'vw')
    # 三分位の向きの独立の検算: market_equity の 1.0 は小型（NYSE 区切りなので銘柄数が多い）
    me1, me3 = N[('market_equity', '1.0')], N[('market_equity', '3.0')]
    m2000 = (YM >= 200001) & (YM <= 200012)
    out['orientation_check'] = {'market_equity_n_pf1_2000': float(np.nanmean(me1[m2000])), 'market_equity_n_pf3_2000': float(np.nanmean(me3[m2000])),
                                'pf3_is_high_value': bool(np.nanmean(me1[m2000]) > np.nanmean(me3[m2000]))}
    jm = arr_from(M.jkp_mkt('usa', 'vw'))
    tot = lambda ex: ex + RF
    usm = mask(US_A, US_Z)

    def evaluate(ex, to):
        s = np.where(usm, tot(ex), np.nan)
        net = s - to * UNIT / 12
        o = {'full': st(s, MKT), 'train': st(s, MKT, z=TR_Z), 'hold': st(s, MKT, a=HO_A),
             'net_hold': st(net, MKT, a=HO_A), 'net3x_hold': st(s - 3 * to * UNIT / 12, MKT, a=HO_A),
             'recent_2013_07': st(s, MKT, a=201307),
             'hold_1st_half_2007_2016H1': st(s, MKT, a=200701, z=201606),
             'hold_2nd_half_2016H2_2025': st(s, MKT, a=201607, z=202512),
             'post_pub_2016_on': st(s, MKT, a=201601),
             'hold_ex_2020_2021': st(s, MKT, a=HO_A, drop=[(202001, 202112)]),
             'full_ex_1998_2000_and_2020_2021': st(s, MKT, drop=[(199801, 200012), (202001, 202112)]),
             'train_ex_1998_2000': st(s, MKT, z=TR_Z, drop=[(199801, 200012)]),
             'pre1990': st(s, MKT, z=198912),
             'vs_jkp_vw_mkt_hold': st(s, tot(jm), a=HO_A),
             'roll20': roll20(s, MKT), 'dca20': dca20(s, MKT),
             'turnover_assumed': round(to, 3)}
        h = o['hold']
        if h:
            cost_ann = to * UNIT * 100
            o['breakeven_cost_multiple_hold'] = round(h['ex_ann'] / cost_ann, 2) if cost_ann else None
            o['breakeven_unit_cost_pct_per_100pct_turnover'] = round(h['ex_ann'] / to, 2)
        # 暦年ごとの保有期間の超過（1年への依存）
        ys = {}
        for y in range(2007, 2026):
            w = mask(y * 100 + 1, y * 100 + 12) & ~np.isnan(s)
            if w.sum() == 12:
                ys[y] = round((np.prod(1 + s[w]) - np.prod(1 + MKT[w])) * 100, 2)
        o['hold_calendar_year_excess'] = ys
        if ys:
            v = sorted(ys.values(), reverse=True)
            o['hold_years_positive'] = f"{sum(1 for x in ys.values() if x > 0)}/{len(ys)}"
            o['hold_sum_excess_all_years'] = round(sum(v), 2)
            o['hold_sum_excess_without_best2'] = round(sum(v[2:]), 2)
        return o, s

    DIR = lit_dirs()
    LIT = {k: [(c, DIR[c]) for c, _ in v] for k, v in MEAS.items()}
    STRATS = {'P1_GATE_ALL': (MEAS, 'good'), 'P2_GATE_CORE': (CORE, 'good'), 'P3_FILTER_ALL': (MEAS, 'filt'),
              'P4_FILTER_CORE': (CORE, 'filt'), 'P5_FILTER_KILLS': ({'K1': [('ebit_bev', 1)], 'K2': [('netdebt_me', -1)], 'K3': [('o_score', -1)], 'K4': [('z_score', 1)]}, 'filt'),
              'E1_GATE_ALL_AGREE': (AGREE, 'good'), 'E2_GATE_ALL_LITDIR': (LIT, 'good')}
    res, ser, exs = {}, {}, {}
    for nm, (meas, mode) in STRATS.items():
        ex = build(R, N, meas, mode)
        o, s = evaluate(ex, turnover(meas, mode))
        res[nm] = o; ser[nm] = s; exs[nm] = ex
        h = o['hold']
        log(f"{nm:20s} full {o['full']['ex_ann']:+.2f} t{o['full']['t']} | train {o['train']['ex_ann']:+.2f} t{o['train']['t']} | hold {h['ex_ann']:+.2f} t{h['t']} "
            f"cagr {h['cagr_diff']:+.2f} | net {o['net_hold']['ex_ann']:+.2f} | 1st {o['hold_1st_half_2007_2016H1']['ex_ann']:+.2f} t{o['hold_1st_half_2007_2016H1']['t']} "
            f"2nd {o['hold_2nd_half_2016H2_2025']['ex_ann']:+.2f} t{o['hold_2nd_half_2016H2_2025']['t']} | roll {o['roll20']['wins']}/{o['roll20']['windows']} dca {o['dca20']}")

    # ─── 研究者の数字との突き合わせ ───
    claimed = json.load(open(os.path.join(BASE, 'out', 'mw_gate_proxy.json')))
    cmp_ = {}
    for nm in STRATS:
        c = claimed['results_us'].get(nm)
        if not c:
            continue
        o = res[nm]
        cmp_[nm] = {k: {'claimed': (c[k]['ex_ann'], c[k]['t']), 'mine': (o[k]['ex_ann'], o[k]['t'])} for k in ('full', 'train', 'hold', 'net_hold')}
        cmp_[nm]['hold_cagr_diff'] = {'claimed': c['hold']['cagr_diff'], 'mine': o['hold']['cagr_diff']}
        cmp_[nm]['roll20'] = {'claimed': (c['roll20']['wins'], c['roll20']['windows']), 'mine': (o['roll20']['wins'], o['roll20']['windows'])}
        cmp_[nm]['dca20'] = {'claimed': (c['dca20']['win_rate'], c['dca20']['median_ratio']), 'mine': (o['dca20']['win_rate'], o['dca20']['median'])}
        cmp_[nm]['max_abs_gap_ex'] = round(max(abs(cmp_[nm][k]['claimed'][0] - cmp_[nm][k]['mine'][0]) for k in ('full', 'train', 'hold', 'net_hold')), 3)
    out['reproduction_vs_claimed'] = cmp_

    # ─── H3 との重なり（米国の保有期間は既知だったか） ───
    h3 = np.vstack([terc(R, N, c, DIR[c], 'good') for c in GATE15])
    h3m = np.where((~np.isnan(h3)).all(0), h3.mean(0), np.nan)
    hm = mask(HO_A, US_Z)
    ov = {}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'E2_GATE_ALL_LITDIR'):
        a_ = exs[nm] - (MKT - RF); b_ = h3m - (MKT - RF)
        ok = hm & ~np.isnan(a_) & ~np.isnan(b_)
        ov[nm] = round(float(np.corrcoef(a_[ok], b_[ok])[0, 1]), 3)
    s_h3 = np.where(usm, tot(h3m), np.nan)
    out['prior_knowledge_overlap'] = {
        'H3_hold_mine': st(s_h3, MKT, a=HO_A), 'H3_train_mine': st(s_h3, MKT, z=TR_Z),
        'chars_shared_with_H3': {'P1': sorted({c for v in MEAS.values() for c, _ in v} & set(GATE15)), 'P2': sorted({c for v in CORE.values() for c, _ in v} & set(GATE15))},
        'corr_of_hold_excess_with_H3': ov,
        'note': 'P1・P2 の保有期間の超過は、事前登録の前に研究者が知っていた H3（mw_combo_us_verify）とほぼ同じ系列＝米国の保有期間は新しい答え合わせではない'}
    log('H3 との相関', ov)

    # ─── 単独の袖の保有期間の成績（mw_factor_us で登録前に見えていた） ───
    single = {}
    for c in sorted({c for v in list(MEAS.values()) + list(CORE.values()) for c, _ in v}):
        for dname, d in (('gate', dict(sum(MEAS.values(), []) + sum(CORE.values(), [])).get(c)), ('lit', DIR.get(c))):
            s = np.where(usm, tot(terc(R, N, c, d, 'good')), np.nan)
            single[f'{c}@{dname}'] = {'train': st(s, MKT, z=TR_Z)['ex_ann'], 'hold': st(s, MKT, a=HO_A)['ex_ann'], 'hold_t': st(s, MKT, a=HO_A)['t']}
    out['single_sleeves'] = single

    # ─── P2 の「重い柱」の選び方: 16袖から5本を選ぶ全 4368 通りの中の位置 ───
    sl16 = {m: build(R, N, {m: px}, 'good') for m, px in MEAS.items()}
    keys = list(MEAS)
    S16 = np.vstack([sl16[k] for k in keys])
    mt, mh = mask(US_A, TR_Z), mask(HO_A, US_Z)
    mk_ex = MKT - RF
    tr_list, ho_list, combos = [], [], []
    for cmb in itertools.combinations(range(16), 5):
        sub = S16[list(cmb)]
        cnt = (~np.isnan(sub)).sum(0)
        with np.errstate(invalid='ignore', divide='ignore'):
            v = np.where(cnt >= 4, np.nansum(sub, 0) / np.maximum(cnt, 1), np.nan)
        e = v - mk_ex
        a1 = e[mt & ~np.isnan(e)]; a2 = e[mh & ~np.isnan(e)]
        tr_list.append(a1.mean() * 1200); ho_list.append(a2.mean() * 1200); combos.append(cmb)
    tr_a, ho_a = np.array(tr_list), np.array(ho_list)
    p2 = res['P2_GATE_CORE']
    analog = [tuple(sorted(keys.index(k) for k in s)) for s in (('M01_roic', 'M03_gpa', 'M06_lev', 'M14_dil', 'M05_accr'), ('M01_roic', 'M03_gpa', 'M07_z', 'M14_dil', 'M05_accr'))]
    faithful = ('M01_roic', 'M16_moat', 'M02_opm', 'M04_conv', 'M12_roiic')  # 門の実効ウェイト（ROIC 36.5%・堀 23%・営業利益率 5.5%・FCF転換・ROIIC）に沿った5本
    fi = tuple(sorted(keys.index(k) for k in faithful))
    fidx = combos.index(fi)
    ffx = build(R, N, {k: MEAS[k] for k in faithful}, 'good')
    fo, _ = evaluate(ffx, turnover({k: MEAS[k] for k in faithful}, 'good'))
    out['p2_selection'] = {
        'all_5_of_16': len(combos),
        'train_median': round(float(np.median(tr_a)), 2), 'hold_median': round(float(np.median(ho_a)), 2),
        'hold_p90': round(float(np.percentile(ho_a, 90)), 2), 'hold_p99': round(float(np.percentile(ho_a, 99)), 2),
        'P2_hold_percentile_among_5of16': round(float((ho_a < p2['hold']['ex_ann']).mean()), 3),
        'P2_train_percentile_among_5of16': round(float((tr_a < p2['train']['ex_ann']).mean()), 3),
        'analog_subsets': {','.join(keys[i] for i in a): {'train': round(float(tr_a[combos.index(a)]), 2), 'hold': round(float(ho_a[combos.index(a)]), 2),
                                                          'train_pct': round(float((tr_a < tr_a[combos.index(a)]).mean()), 3),
                                                          'hold_pct': round(float((ho_a < ho_a[combos.index(a)]).mean()), 3)} for a in analog},
        'gate_weight_faithful_core': {'sleeves': faithful, 'train': round(float(tr_a[fidx]), 2), 'hold': round(float(ho_a[fidx]), 2),
                                      'hold_pct': round(float((ho_a < ho_a[fidx]).mean()), 3),
                                      'full_stats': fo['full'], 'hold_stats': fo['hold'], 'net_hold': fo['net_hold']},
        'corr_train_vs_hold_across_subsets': round(float(np.corrcoef(tr_a, ho_a)[0, 1]), 3),
        'share_hold_positive': round(float((ho_a > 0).mean()), 3),
        'note': 'P2 の袖（安全=z と純負債の平均・moat=gp_at）は 16袖の部分集合ではないので、近い2つの部分集合（M06 か M07）で位置を見る。'
                '門自身の実効ウェイト（prereg の effective_weights_note）で重いのは ROIC・堀・営業利益率で、純負債は −0.4%、株数(dilNet)は表示のみ'}
    log('P2 選び方', json.dumps({k: v for k, v in out['p2_selection'].items() if k not in ('gate_weight_faithful_core',)}, ensure_ascii=False))
    log('門に忠実な5本', faithful, fo['full']['ex_ann'], fo['full']['t'], fo['hold']['ex_ann'], fo['hold']['t'])

    # ─── 近い写し（パラメータの近隣）───
    ALT = {
        'M01_roic': [[('ebit_bev', 1)], [('ope_be', 1)], [('op_at', 1)], [('ni_be', 1)]],
        'M02_opm': [[('ebit_sale', 1)]],
        'M03_gpa': [[('gp_at', 1)], [('gp_atl1', 1)], [('cop_at', 1)]],
        'M04_conv': [[('oaccruals_ni', -1)], [('taccruals_ni', -1)]],
        'M05_accr': [[('oaccruals_at', -1)], [('taccruals_at', -1)], [('cowc_gr1a', -1)]],
        'M06_lev': [[('netdebt_me', -1)], [('debt_me', -1)], [('at_be', -1)]],
        'M07_z': [[('z_score', 1)]],
        'M08_intcov': [[('o_score', -1)], [('kz_index', -1)]],
        'M09_p1': [[('ni_ivol', -1), ('ocfq_saleq_std', -1)], [('earnings_variability', -1)], [('ocfq_saleq_std', -1)]],
        'M10_p2': [[('qmj_safety', 1)], [('betadown_252d', -1)], [('beta_60m', -1)]],
        'M11_growth': [[('sale_gr3', 1)], [('sale_gr1', 1)], [('saleq_gr1', 1)]],
        'M12_roiic': [[('qmj_growth', 1)], [('niq_at_chg1', 1)], [('ocf_at_chg1', 1)]],
        'M13_shy': [[('eqnpo_me', 1)], [('eqnpo_12m', 1)], [('eqpo_me', 1)]],
        'M14_dil': [[('chcsho_12m', -1)], [('eqnetis_at', -1)], [('netis_at', -1)]],
        'M15_roict': [[('niq_be_chg1', 1)], [('niq_at_chg1', 1)]],
        'M16_moat': [[('ni_ar1', 1)], [('ni_inc8q', 1)]]}
    # 袖ごとの候補の系列を先に作る
    alt_s = {m: [build(R, N, {m: px}, 'good') for px in lst] for m, lst in ALT.items()}
    rnd = random.Random(7)
    rows = []
    need16 = math.ceil(2 * 16 / 3)
    for _ in range(1500):
        pick = [alt_s[m][rnd.randrange(len(alt_s[m]))] for m in ALT]
        S_ = np.vstack(pick)
        cnt = (~np.isnan(S_)).sum(0)
        with np.errstate(invalid='ignore', divide='ignore'):
            v = np.where(cnt >= need16, np.nansum(S_, 0) / np.maximum(cnt, 1), np.nan)
        s = np.where(usm, tot(v), np.nan)
        f_, t_, h_ = st(s, MKT), st(s, MKT, z=TR_Z), st(s, MKT, a=HO_A)
        rows.append((f_['ex_ann'], f_['t'], t_['ex_ann'], t_['t'], h_['ex_ann'], h_['t']))
    A = np.array(rows, float)
    p1h = res['P1_GATE_ALL']['hold']['ex_ann']
    out['neighbors_P1_mapping'] = {
        'draws': len(rows), 'alternatives_per_sleeve': {m: [[c for c, _ in px] for px in lst] for m, lst in ALT.items()},
        'hold_ex_p10_p50_p90': [round(float(np.percentile(A[:, 4], q)), 2) for q in (10, 50, 90)],
        'hold_t_p10_p50_p90': [round(float(np.percentile(A[:, 5], q)), 2) for q in (10, 50, 90)],
        'share_hold_t_ge_1_65': round(float((A[:, 5] >= 1.65).mean()), 3),
        'share_full_t_ge_3': round(float((A[:, 1] >= 3).mean()), 3),
        'share_train_t_ge_2': round(float((A[:, 3] >= 2).mean()), 3),
        'share_all_three': round(float(((A[:, 5] >= 1.65) & (A[:, 1] >= 3) & (A[:, 3] >= 2) & (A[:, 4] > 0)).mean()), 3),
        'P1_hold_percentile_among_neighbors': round(float((A[:, 4] < p1h).mean()), 3)}
    log('P1 近隣', json.dumps({k: v for k, v in out['neighbors_P1_mapping'].items() if k != 'alternatives_per_sleeve'}, ensure_ascii=False))

    alt_f = {m: [build(R, N, {m: px}, 'filt') for px in lst] for m, lst in ALT.items()}
    rnd = random.Random(8)
    rows = []
    to3 = turnover(MEAS, 'filt')
    for _ in range(800):
        pick = [alt_f[m][rnd.randrange(len(alt_f[m]))] for m in ALT]
        S_ = np.vstack(pick)
        cnt = (~np.isnan(S_)).sum(0)
        with np.errstate(invalid='ignore', divide='ignore'):
            v = np.where(cnt >= need16, np.nansum(S_, 0) / np.maximum(cnt, 1), np.nan)
        s_ = np.where(usm, tot(v), np.nan)
        f_, t_, h_, n_ = st(s_, MKT), st(s_, MKT, z=TR_Z), st(s_, MKT, a=HO_A), st(s_ - to3 * UNIT / 12, MKT, a=HO_A)
        rows.append((f_['ex_ann'], f_['t'], t_['ex_ann'], t_['t'], h_['ex_ann'], h_['t'], n_['ex_ann'], n_['cagr_diff']))
    A = np.array(rows, float)
    out['neighbors_P3_mapping'] = {
        'draws': len(rows),
        'hold_ex_p10_p50_p90': [round(float(np.percentile(A[:, 4], q)), 2) for q in (10, 50, 90)],
        'net_hold_ex_p10_p50_p90': [round(float(np.percentile(A[:, 6], q)), 2) for q in (10, 50, 90)],
        'share_train_C1': round(float(((A[:, 2] > 0) & (A[:, 3] >= 2)).mean()), 3),
        'share_C6_net_positive': round(float(((A[:, 6] > 0) & (A[:, 7] > 0)).mean()), 3),
        'share_grade_B_or_better_C1_C2_C6': round(float(((A[:, 2] > 0) & (A[:, 3] >= 2) & (A[:, 4] > 0) & (A[:, 6] > 0) & (A[:, 7] > 0)).mean()), 3),
        'P3_hold_percentile_among_neighbors': round(float((A[:, 4] < res['P3_FILTER_ALL']['hold']['ex_ann']).mean()), 3)}
    log('P3 近隣', json.dumps(out['neighbors_P3_mapping'], ensure_ascii=False))

    ALT2 = {'C1': [[('ebit_bev', 1)], [('ope_be', 1)], [('op_at', 1)], [('ni_be', 1)]],
            'C2': [[('gp_at', 1)], [('gp_atl1', 1)], [('cop_at', 1)], [('ni_ar1', 1)]],
            'C3': [[('z_score', 1), ('netdebt_me', -1)], [('z_score', 1)], [('netdebt_me', -1)], [('o_score', -1), ('netdebt_me', -1)], [('qmj_safety', 1)]],
            'C4': [[('chcsho_12m', -1)], [('eqnetis_at', -1)], [('netis_at', -1)]],
            'C5': [[('oaccruals_at', -1)], [('taccruals_at', -1)], [('oaccruals_ni', -1)]]}
    for mode_nm, mode in (('P2', 'good'), ('P4', 'filt')):
        a2 = {m: [build(R, N, {m: px}, mode) for px in lst] for m, lst in ALT2.items()}
        rows = []
        for combo in itertools.product(*[range(len(ALT2[m])) for m in ALT2]):
            S_ = np.vstack([a2[m][i] for m, i in zip(ALT2, combo)])
            cnt = (~np.isnan(S_)).sum(0)
            with np.errstate(invalid='ignore', divide='ignore'):
                v = np.where(cnt >= 4, np.nansum(S_, 0) / np.maximum(cnt, 1), np.nan)
            s = np.where(usm, tot(v), np.nan)
            f_, t_, h_ = st(s, MKT), st(s, MKT, z=TR_Z), st(s, MKT, a=HO_A)
            rows.append((f_['ex_ann'], f_['t'], t_['ex_ann'], t_['t'], h_['ex_ann'], h_['t']))
        A = np.array(rows, float)
        base_h = res['P2_GATE_CORE' if mode_nm == 'P2' else 'P4_FILTER_CORE']['hold']['ex_ann']
        out[f'neighbors_{mode_nm}_mapping'] = {
            'combos': len(rows),
            'hold_ex_p10_p50_p90': [round(float(np.percentile(A[:, 4], q)), 2) for q in (10, 50, 90)],
            'hold_t_p10_p50_p90': [round(float(np.percentile(A[:, 5], q)), 2) for q in (10, 50, 90)],
            'share_hold_ex_pos': round(float((A[:, 4] > 0).mean()), 3),
            'share_hold_t_ge_1_65': round(float((A[:, 5] >= 1.65).mean()), 3),
            'share_full_t_ge_3': round(float((A[:, 1] >= 3).mean()), 3),
            'share_train_t_ge_2': round(float((A[:, 3] >= 2).mean()), 3),
            f'{mode_nm}_hold_percentile_among_neighbors': round(float((A[:, 4] < base_h).mean()), 3)}
        log(f'{mode_nm} 近隣', json.dumps(out[f'neighbors_{mode_nm}_mapping'], ensure_ascii=False))

    # 必要な袖の数の規則を変える
    out['need_rule'] = {}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P3_FILTER_ALL', 'P4_FILTER_CORE'):
        meas, mode = STRATS[nm]
        out['need_rule'][nm] = {}
        for rule in ('all', 'one'):
            s = np.where(usm, tot(build(R, N, meas, mode, rule)), np.nan)
            out['need_rule'][nm][rule] = {'full': st(s, MKT), 'hold': st(s, MKT, a=HO_A)}

    # ─── 重みづけ: 上限つき・等加重の三分位で（相手は French Mkt のまま）───
    out['weighting'] = {}
    for w in ('vw_cap', 'ew'):
        Rw, Nw = jkp_pf('usa', w)
        mw = arr_from(M.jkp_mkt('usa', w))
        out['weighting'][w] = {'jkp_mkt_vs_french_hold': st(np.where(usm, tot(mw), np.nan), MKT, a=HO_A)}
        for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P3_FILTER_ALL', 'P4_FILTER_CORE'):
            meas, mode = STRATS[nm]
            s = np.where(usm, tot(build(Rw, Nw, meas, mode)), np.nan)
            out['weighting'][w][nm] = {'hold_vs_french': st(s, MKT, a=HO_A), 'full_vs_french': st(s, MKT)}
        log('重み', w, {nm: (v['hold_vs_french']['ex_ann'], v['hold_vs_french']['t']) for nm, v in out['weighting'][w].items() if nm.startswith('P')})

    # ─── 作り方の偏り（3つの三分位の等分）───
    out['construction_bias_us'] = {}
    for nm, meas in (('GATE_ALL', MEAS), ('GATE_CORE', CORE)):
        neu = np.where(usm, tot(build(R, N, meas, 'neutral')), np.nan)
        good = np.where(usm, tot(build(R, N, meas, 'good')), np.nan)
        filt = np.where(usm, tot(build(R, N, meas, 'filt')), np.nan)
        out['construction_bias_us'][nm] = {'neutral_vs_mkt_full': st(neu, MKT), 'neutral_vs_mkt_hold': st(neu, MKT, a=HO_A),
                                           'good_minus_neutral_hold': st(good, neu, a=HO_A), 'filt_minus_neutral_hold': st(filt, neu, a=HO_A),
                                           'filt_minus_neutral_full': st(filt, neu)}

    # ─── 業種（French 12・時価加重）でヘッジ: 訓練期間の係数で保有期間を ───
    ind = M.french_series('12_Industry_Portfolios', 'Value Weight')
    IND = np.vstack([arr_from(ind[c]) for c in sorted(ind)])
    out['industry_hedge'] = {}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P3_FILTER_ALL', 'P4_FILTER_CORE'):
        s = ser[nm]
        y = s - RF
        X = IND - RF
        ok = ~np.isnan(y) & ~np.isnan(X).any(0) & usm
        tr = ok & (YM <= TR_Z); ho = ok & (YM >= HO_A)
        Xt = np.column_stack([np.ones(tr.sum()), X[:, tr].T])
        b = np.linalg.lstsq(Xt, y[tr], rcond=None)[0]
        resid_h = y[ho] - X[:, ho].T @ b[1:]
        resid_t = y[tr] - X[:, tr].T @ b[1:]
        Xf = np.column_stack([np.ones(ok.sum()), X[:, ok].T])
        bf = np.linalg.lstsq(Xf, y[ok], rcond=None)[0]
        resid_f = y[ok] - X[:, ok].T @ bf[1:]
        # 市場との差の系列を業種の対市場の差でヘッジ（訓練で係数）
        e = s - MKT
        Xe = IND - MKT
        be = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), Xe[:, tr].T]), e[tr], rcond=None)[0]
        rh = e[ho] - Xe[:, ho].T @ be[1:]
        out['industry_hedge'][nm] = {
            'full_insample_alpha': round(float(resid_f.mean() * 1200), 2), 'full_insample_t': round(nwt(resid_f), 2),
            'train_insample_alpha': round(float(resid_t.mean() * 1200), 2), 'train_t': round(nwt(resid_t), 2),
            'hold_alpha_train_betas': round(float(resid_h.mean() * 1200), 2), 'hold_t': round(nwt(resid_h), 2),
            'excess_vs_mkt_hedged_hold_alpha': round(float(rh.mean() * 1200), 2), 'excess_vs_mkt_hedged_hold_t': round(nwt(rh), 2)}
        log('業種', nm, out['industry_hedge'][nm])

    # ─── 税（日本の課税口座・参考）: 年の回転分だけ含み益を実現して 20.315% ───
    def after_tax(s, rate=0.20315, f=1.0, a=HO_A, z=US_Z):
        """毎年末に保有の割合 f を売って買い直す（含み益の f を実現）。損は繰越。最後に残りの含み益へ課税"""
        m = mask(a, z) & ~np.isnan(s)
        v, B, carry = 1.0, 1.0, 0.0
        yrs = sorted({int(q) // 100 for q in YM[m]})
        f = min(1.0, f)
        for y in yrs:
            w = m & (YM // 100 == y)
            v *= float(np.prod(1 + s[w]))
            if f > 0 and y != yrs[-1]:
                g = f * (v - B)
                if g > 0:
                    T = rate * max(0.0, g - carry); carry = max(0.0, carry - g)
                else:
                    T = 0.0; carry += -g
                B = (1 - f) * B + f * v - T
                v -= T
        g = v - B
        v -= rate * max(0.0, g - carry)
        n = m.sum() / 12
        return v ** (1 / n) - 1
    tax = {}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE'):
        s = ser[nm]
        to = res[nm]['turnover_assumed']
        net = s - to * UNIT / 12
        g_s = after_tax(net, f=to); g_b = after_tax(MKT, f=0.0)
        pre_s = math.exp(np.log1p(net[mask(HO_A, US_Z)]).mean() * 12) - 1; pre_b = math.exp(np.log1p(MKT[mask(HO_A, US_Z)]).mean() * 12) - 1
        tax[nm] = {'pre_tax_cagr_diff_net_cost': round((pre_s - pre_b) * 100, 2), 'after_tax_cagr_diff_taxable_jp': round((g_s - g_b) * 100, 2),
                   'turnover_as_realization_rate': to}
    tax['model'] = '保有期間 2007-2025。戦略は毎年末に「回転率×含み益」を実現して 20.315%（損は繰越）。市場は最後に一度だけ課税。配当の課税は両方同じとして省く。NISA では税は無い＝判定には使わない（報告のみ）'
    out['tax_japan_taxable'] = tax
    log('税', tax)

    # ─── 多重検定（角度の中と、プログラム全体）───
    import glob
    total_tested = 0
    for f in glob.glob(os.path.join(BASE, 'out', 'mw_*.json')):
        b_ = os.path.basename(f)
        if 'prereg' in b_ or 'verify' in b_:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        t = d.get('tested')
        total_tested += len(t) if isinstance(t, list) else int(d.get('n_tested') or 0)
    primaries = ['P1_GATE_ALL', 'P2_GATE_CORE', 'P3_FILTER_ALL', 'P4_FILTER_CORE', 'P5_FILTER_KILLS']
    hp = holm({n: res[n]['hold']['p'] for n in primaries})
    mt_ = {'angle_tested': claimed.get('n_tested'), 'program_tested_all_mw_angles': total_tested,
           'holm_hold_primary_family_mine': hp}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P4_FILTER_CORE'):
        pf = pnorm2(res[nm]['full']['t']); ph = pnorm2(res[nm]['hold']['t'])
        mt_[nm] = {'full_p': float('%.3g' % pf), 'bonferroni_full_angle': round(min(1, pf * (claimed.get('n_tested') or 1)), 4),
                   'bonferroni_full_program': round(min(1, pf * total_tested), 4),
                   'hold_p': float('%.3g' % ph), 'bonferroni_hold_program': round(min(1, ph * total_tested), 4)}
    out['multiple_testing'] = mt_
    log('多重', mt_)

    # ─── 無作為の16本・5本の混合（研究者の正直な選び方を別の種で）───
    names = sorted(c for c in {k[0] for k in R} if c in DIR)
    G = np.vstack([terc(R, N, c, DIR[c], 'good') for c in names])
    rg = np.random.default_rng(11)
    hs = {}
    for size, nm in ((16, 'P1_GATE_ALL'), (5, 'P2_GATE_CORE')):
        need = math.ceil(2 * size / 3)
        th, tt = [], []
        for _ in range(3000):
            sel = rg.choice(len(names), size, replace=False)
            sub = G[sel]
            cnt = (~np.isnan(sub)).sum(0)
            with np.errstate(invalid='ignore', divide='ignore'):
                v = np.where(cnt >= need, np.nansum(sub, 0) / np.maximum(cnt, 1), np.nan)
            e = v - mk_ex
            th.append(np.nanmean(np.where(mh, e, np.nan)) * 1200); tt.append(np.nanmean(np.where(mt, e, np.nan)) * 1200)
        th, tt = np.array(th), np.array(tt)
        hs[nm] = {'draws': 3000, 'hold_median': round(float(np.median(th)), 2), 'train_median': round(float(np.median(tt)), 2),
                  'hold_percentile': round(float((th < res[nm]['hold']['ex_ann']).mean()), 3),
                  'train_percentile': round(float((tt < res[nm]['train']['ex_ann']).mean()), 3)}
    out['random_mixes_litdir'] = hs
    log('無作為', hs)

    # ─── 国パネル（C5）と作り方の偏りを引いた版 ───
    av = json.load(open(os.path.join(CACHE, 'jkp_availability.json')))
    countries = [c for c in av['portfolios'] if c not in AGG]
    chars = sorted({c for v in list(MEAS.values()) + list(CORE.values()) + list(LIT.values()) + list(AGREE.values()) for c, _ in v})
    pan = {nm: {'by': {}, 'pool': [], 'pool_adj': []} for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P3_FILTER_ALL', 'P4_FILTER_CORE', 'E1_GATE_ALL_AGREE', 'E2_GATE_ALL_LITDIR')}
    for cc in countries:
        try:
            Rc, Nc = jkp_pf(cc, 'vw', keep=set(chars))
            mc = arr_from(M.jkp_mkt(cc, 'vw'))
        except Exception as e:  # noqa
            log('国の取得失敗', cc, e)
            continue
        for nm in pan:
            meas, mode = STRATS[nm]
            v = build(Rc, Nc, meas, mode)
            nu = build(Rc, Nc, meas, 'neutral')
            ok = ~np.isnan(v) & ~np.isnan(mc) & (YM <= US_Z)
            if ok.sum() < 240:
                continue
            e = np.where(ok, v - mc, np.nan)
            ea = np.where(ok & ~np.isnan(nu), v - nu, np.nan)
            r = {'months': int(ok.sum()), 'from': int(YM[ok][0]),
                 'full': round(float(np.nanmean(e) * 1200), 2)}
            po = ok & (YM >= HO_A)
            pr = ok & (YM <= TR_Z)
            r['post2007'] = round(float(e[po].mean() * 1200), 2) if po.sum() >= 60 else None
            r['pre2007'] = round(float(e[pr].mean() * 1200), 2) if pr.sum() >= 60 else None
            r['full_minus_neutral'] = round(float(np.nanmean(ea) * 1200), 2) if (~np.isnan(ea)).sum() >= 60 else None
            # 幾何（総リターンどうし）
            sT, bT = tot(v)[ok], tot(mc)[ok]
            r['full_cagr_diff'] = round((math.exp(np.log1p(sT).mean() * 12) - math.exp(np.log1p(bT).mean() * 12)) * 100, 2)
            pan[nm]['by'][cc] = r
            pan[nm]['pool'].append(e); pan[nm]['pool_adj'].append(ea)
    out['country_panel'] = {}
    for nm, P in pan.items():
        by = P['by']
        cnt = len(by)
        pos = sum(1 for v in by.values() if v['full'] > 0)
        pos_g = sum(1 for v in by.values() if v['full_cagr_diff'] > 0)
        post = [v['post2007'] for v in by.values() if v['post2007'] is not None]
        pre = [v['pre2007'] for v in by.values() if v['pre2007'] is not None]
        adj = [v['full_minus_neutral'] for v in by.values() if v['full_minus_neutral'] is not None]
        Pm = np.vstack(P['pool']); Pa = np.vstack(P['pool_adj'])
        with np.errstate(invalid='ignore'):
            pm = np.nanmean(Pm, 0); pa = np.nanmean(Pa, 0)
        o = {'countries': cnt, 'positive_full': pos, 'positive_full_geometric': pos_g, 'C5_pass': pos / cnt >= 2 / 3 if cnt else None,
             'positive_post2007': f'{sum(1 for x in post if x > 0)}/{len(post)}', 'positive_pre2007': f'{sum(1 for x in pre if x > 0)}/{len(pre)}',
             'positive_full_minus_neutral': f'{sum(1 for x in adj if x > 0)}/{len(adj)}',
             'C5_pass_after_construction_adjustment': (sum(1 for x in adj if x > 0) / len(adj) >= 2 / 3) if adj else None}
        for lab, a, z in (('full', None, None), ('pre2007', None, TR_Z), ('post2007', HO_A, None), ('post2016', 201601, None)):
            for vv, nm2 in ((pm, 'pooled'), (pa, 'pooled_minus_neutral')):
                m = ~np.isnan(vv) & mask(a, z)
                x = vv[m]
                if len(x) >= 24:
                    o[f'{nm2}_{lab}'] = {'ex_ann': round(float(x.mean() * 1200), 2), 't': round(nwt(x), 2), 'months': int(len(x))}
        o['by_country'] = by
        out['country_panel'][nm] = o
        log('国', nm, {k: v for k, v in o.items() if k != 'by_country'})

    # ─── 地域: emerging（相手を JKP と French の2通りで）───
    fe = [v for k, v in M.french_tables('Emerging_5_Factors').items() if v['freq'] == 'monthly'][0]
    i_m, i_rf = fe['cols'].index('Mkt-RF'), fe['cols'].index('RF')
    FEM = arr_from({d: r[i_m] / 100 + r[i_rf] / 100 for d, r in fe['data'].items() if r[i_m] is not None and r[i_rf] is not None})
    Re, Ne = jkp_pf('emerging', 'vw', keep=set(chars))
    JEM = tot(arr_from(M.jkp_mkt('emerging', 'vw')))
    em = {'jkp_mkt_vs_french_emerging': {'1989_1996': st(JEM, FEM, a=198907, z=199612), '1997_2006': st(JEM, FEM, a=199701, z=200612),
                                         '2007_2025': st(JEM, FEM, a=200701, z=202512),
                                         'corr_pre2007': round(float(np.corrcoef(JEM[mask(198907, 200612)], FEM[mask(198907, 200612)])[0, 1]), 3),
                                         'corr_post2007': round(float(np.corrcoef(JEM[mask(200701, 202512)], FEM[mask(200701, 202512)])[0, 1]), 3)}}
    emn = {}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P4_FILTER_CORE'):
        meas, mode = STRATS[nm]
        v = build(Re, Ne, meas, mode)
        s = np.where(mask(None, US_Z), tot(v), np.nan)
        to = turnover(meas, mode)
        o = {}
        for bn, B in (('jkp_emerging_vw', JEM), ('french_emerging', FEM)):
            ok = ~np.isnan(s) & ~np.isnan(B)
            ss = np.where(ok, s, np.nan); bb = np.where(ok, B, np.nan)
            full, tr, ho = st(ss, bb), st(ss, bb, z=TR_Z), st(ss, bb, a=HO_A)
            net = st(ss - to * UNIT / 12, bb, a=HO_A)
            a0 = int(YM[ok][0]) if ok.any() else None
            rl = roll20(ss, bb, a=a0, z=US_Z)
            o[bn] = {'full': full, 'train': tr, 'hold': ho, 'net_hold': net, 'roll20': rl,
                     'hold_1st_half': st(ss, bb, a=200701, z=201606), 'hold_2nd_half': st(ss, bb, a=201607, z=202512),
                     'train_1990s_only': st(ss, bb, z=199912), 'train_2000_2006': st(ss, bb, a=200001, z=TR_Z),
                     'dca20': dca20(ss, bb, a=a0, z=US_Z)}
            o[bn]['grade_C5_na'] = grade(tr, ho, full, rl, net, None, None)
        emn[nm] = o
        log('emerging', nm, {bn: (x['full']['ex_ann'], x['full']['t'], x['train']['ex_ann'], x['train']['t'], x['hold']['ex_ann'], x['hold']['t'], x['roll20'] and (x['roll20']['wins'], x['roll20']['windows'])) for bn, x in o.items()})
    em['strategies'] = emn
    # emerging の三分位の銘柄数（初期の薄さ）
    nmin = {}
    for c in ('ebit_bev', 'gp_at', 'z_score', 'chcsho_12m', 'oaccruals_at'):
        k = (c, '3.0') if (c, '3.0') in Ne else None
        if k:
            for y in (1991, 1995, 2000, 2010, 2020):
                w = mask(y * 100 + 1, y * 100 + 12)
                nmin[f'{c}_{y}'] = None if np.isnan(Ne[k][w]).all() else float(np.nanmean(Ne[k][w]))
    em['tercile_n_samples'] = nmin
    out['emerging'] = em

    # ─── 米国の格付けを自前で（C5 は国パネルの自前の数）───
    hp_e = holm({n: res[n]['hold']['p'] for n in ('E1_GATE_ALL_AGREE', 'E2_GATE_ALL_LITDIR')})
    grades = {}
    for nm in ('P1_GATE_ALL', 'P2_GATE_CORE', 'P3_FILTER_ALL', 'P4_FILTER_CORE', 'E1_GATE_ALL_AGREE', 'E2_GATE_ALL_LITDIR'):
        o = res[nm]
        cp = out['country_panel'].get(nm)
        rf_ = (cp['positive_full'] / cp['countries']) if cp else None
        g_, c_ = grade(o['train'], o['hold'], o['full'], o['roll20'], o['net_hold'], rf_, (hp if nm[0] == 'P' else hp_e).get(nm))
        grades[nm] = {'grade_mine': g_, 'criteria_mine': c_}
        # 作り方の偏りを引いた C5 での格付け（参考）
        if cp:
            adj_frac = None
            num, den = cp['positive_full_minus_neutral'].split('/')
            adj_frac = int(num) / int(den) if int(den) else None
            grades[nm]['grade_if_C5_construction_adjusted'] = grade(o['train'], o['hold'], o['full'], o['roll20'], o['net_hold'], adj_frac, (hp if nm[0] == 'P' else hp_e).get(nm))[0]
        # C3 を『汚れていて使えない』と見なした（米国の保有期間は H3 で既知）ときの格付け＝C3 を不合格として当てる
        c3off = dict(o['hold']); c3off['t'] = 0.0
        g2 = grade(o['train'], c3off, o['full'], o['roll20'], o['net_hold'], rf_, None)
        grades[nm]['grade_if_US_hold_t_discounted'] = g2[0]
    out['grades_reproduced'] = grades
    out['results_us'] = res
    out['log'] = LOG
    return out


if __name__ == '__main__':
    o = main()
    p = os.path.join(BASE, 'out', 'mw_gate_proxy_verify.json')
    prev = {}
    if os.path.exists(p):
        try:
            prev = json.load(open(p))
        except Exception:
            prev = {}
    for k in ('verdicts', 'summary_ja', 'verdict_notes'):
        if k in prev:
            o[k] = prev[k]
    json.dump(o, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, 'item') else str(x))
    print('書いた', p)
