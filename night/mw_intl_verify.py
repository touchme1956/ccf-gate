#!/usr/bin/env python3
"""night/mw_intl_verify.py — 角度 intl（out/mw_intl.json）の主張を反証しにいく独立の検算（読むだけ・門の判定には不使用）

2026-09-28 の『市場に勝てる歴史検証』(mw) の敵対的検証。研究側（night/mw_intl.py）の S・A 全部と B の上位2本
（保有期間の超過が大きい順）を、**自分で書いた**系列の組み立て・超過・NW t・CAGR・20年窓・積立で出し直し、
さらに反証の角度（先読み・訓練期間の選び直し・相手・生き残り・費用・部分期間・近隣の設定・国への依存・
多重検定・独立データ・実在の商品）で叩く。

mw_common から使うのは**取得だけ**（jkp_rows / french_tables / ff_factors / yahoo / get / _ym）。
良い側の決め方・被覆の規則・系列の組み立て・統計（平均・NW t・CAGR・20年窓・積立・費用・格付け）は全部ここで書き直した。

出力: out/mw_intl_verify.json
使い方: python3 night/mw_intl_verify.py
"""
import collections, csv, io, json, math, os, random, statistics as S, sys, zipfile, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけ

BASE = M.BASE
TR_END, HO_START, REC_START = 200612, 200701, 201307
H1_END, H2_START = 201606, 201607          # 保有期間の前半・後半（ほぼ9.5年ずつ）
START2, RMIN, NMIN = 199007, 0.4, 10       # 事前登録2（F2a）の規則
TURN = {'be_me': 0.3, 'ni_me': 0.5, 'ocf_me': 0.5, 'div12m_me': 0.3, 'ret_12_1': 1.5, 'resff3_12_1': 1.5}  # 研究側の回転率（そのまま再現用）
UNIT = 0.003
DEVELOPED = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
             'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe', 'usa'}
QUALITY = ['ope_be', 'gp_at', 'qmj', 'qmj_prof', 'cop_at']
CHARS20 = ['ope_be', 'gp_at', 'qmj', 'qmj_prof', 'cop_at', 'qmj_safety', 'at_gr1', 'chcsho_12m', 'be_me', 'ni_me', 'ocf_me',
           'div12m_me', 'eqnpo_me', 'netdebt_me', 'ret_12_1', 'ret_6_1', 'resff3_12_1', 'ivol_capm_252d', 'betabab_1260d', 'oaccruals_at']
NEIGHBORS = {'be_me': ['bev_mev', 'at_me', 'sale_me'], 'ni_me': ['ebitda_mev', 'fcf_me', 'eqpo_me'],
             'ocf_me': ['fcf_me', 'ebitda_mev', 'sale_me'], 'div12m_me': ['eqpo_me', 'eqnpo_me', 'ni_me'],
             'ret_12_1': ['ret_9_1', 'ret_6_1', 'ret_12_7'], 'resff3_12_1': ['resff3_6_1', 'ret_12_1', 'ret_9_1']}
CANDS = [('primary', 'be_me'), ('primary', 'ni_me'), ('F2a', 'be_me'), ('F2a', 'ni_me'), ('F2a', 'ocf_me'),
         ('F2a', 'div12m_me'), ('F2a', 'ret_12_1'), ('F2a', 'resff3_12_1')]
CLAIM = {  # 研究側の主張（依頼文の JSON をそのまま）
    'primary:be_me': dict(grade='A', full=(4.63, 3.08), train=(7.11, 2.97), hold=(1.88, 1.29), cd=1.54, net=1.79, roll=1, dca=1.419),
    'primary:ni_me': dict(grade='S', full=(3.94, 3.33), train=(5.82, 3.00), hold=(1.87, 1.76), cd=1.70, net=1.72, roll=1, dca=1.489),
    'F2a:be_me': dict(grade='B', full=(3.27, 2.77), train=(4.86, 2.68), hold=(1.88, 1.29), cd=1.54, net=1.79, roll=1, dca=1.335),
    'F2a:ni_me': dict(grade='S', full=(3.33, 3.35), train=(5.02, 3.04), hold=(1.87, 1.76), cd=1.70, net=1.72, roll=1, dca=1.403),
    'F2a:ocf_me': dict(grade='S', full=(2.63, 3.20), train=(2.98, 2.15), hold=(2.33, 2.45), cd=2.28, net=2.18, roll=1, dca=1.379),
    'F2a:div12m_me': dict(grade='B', full=(3.34, 2.85), train=(4.61, 2.05), hold=(2.24, 2.42), cd=2.33, net=2.15, roll=1, dca=1.52),
    'F2a:ret_12_1': dict(grade='S', full=(2.84, 3.28), train=(3.49, 2.59), hold=(2.28, 2.09), cd=2.48, net=1.83, roll=1, dca=1.42),
    'F2a:resff3_12_1': dict(grade='S', full=(2.83, 5.21), train=(3.97, 3.99), hold=(1.84, 4.32), cd=1.94, net=1.39, roll=1, dca=1.357),
}


# ───────────────────────── 自前の統計（mw_common の統計は使わない） ─────────────────────────
def months(s, b, a=None, z=None, drop=None):
    return sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not (drop and drop(k)))


def nw_tstat(x, L=12):
    n = len(x)
    if n < 24:
        return None
    mu = math.fsum(x) / n
    d = [v - mu for v in x]
    lr = math.fsum(v * v for v in d) / n
    for l in range(1, min(L, n - 1) + 1):
        w = 1.0 - l / (L + 1.0)
        lr += 2.0 * w * math.fsum(d[i] * d[i - l] for i in range(l, n)) / n
    return mu / math.sqrt(lr / n) if lr > 0 else None


def pval(t):
    return None if t is None else math.erfc(abs(t) / math.sqrt(2.0))


def geo_ann(xs):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12.0 / len(xs)) - 1.0


def st(s, b, a=None, z=None, drop=None):
    ks = months(s, b, a, z, drop)
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nw_tstat(d)
    n = len(d)
    mu = math.fsum(d) / n
    sd = math.sqrt(math.fsum((v - mu) ** 2 for v in d) / (n - 1))
    gs, gb = geo_ann([s[k] for k in ks]), geo_ann([b[k] for k in ks])
    return {'from': ks[0], 'to': ks[-1], 'n': n, 'ex': round(mu * 1200, 2), 't': None if t is None else round(t, 2),
            'p': None if t is None else round(pval(t), 5), 'cd': round((gs - gb) * 100, 2), 'te': round(sd * math.sqrt(12) * 100, 2)}


def roll_lump(s, b, years=20, start_month=7, a=None, z=None):
    ks = months(s, b, a, z)
    have = set(ks)
    out = []
    if not ks:
        return None
    for y in range(ks[0] // 100, ks[-1] // 100 + 1):
        w = []
        yy, mm = y, start_month
        for _ in range(years * 12):
            w.append(yy * 100 + mm)
            mm += 1
            if mm == 13:
                yy, mm = yy + 1, 1
        if not all(k in have for k in w):
            continue
        gs, gb = geo_ann([s[k] for k in w]), geo_ann([b[k] for k in w])
        out.append((y, round((gs - gb) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'windows': len(out), 'wins': sum(1 for c in v if c > 0), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3),
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'first_start': out[0][0], 'last_start': out[-1][0]}


def dca_ratio(s, b, years=20, step=12):
    ks = months(s, b)
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        vs = vb = 0.0
        for k in w:
            vs = (vs + 1.0) * (1.0 + s[k]); vb = (vb + 1.0) * (1.0 + b[k])
        out.append((w[0], round(vs / vb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1])}


def net_of(s, turn, unit):
    c = turn * unit / 12.0
    return {k: v - c for k, v in s.items()}


def holm_adj(p):
    items = sorted((v, k) for k, v in p.items() if v is not None)
    m, out, run = len(items), {}, 0.0
    for i, (v, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 4)
    return out


def grade_own(full, train, hold, roll, net, repl, holm_p):
    """out/mw_prereg.json の C1〜C7 を自前で当てる（C8 は非該当）"""
    c = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0),
         'C2': bool(hold and hold['ex'] > 0 and hold['cd'] > 0),
         'C3': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4': bool(roll and roll['win_rate'] >= 0.8),
         'C5': (repl[1] > 0 and repl[0] / repl[1] >= 2 / 3) if repl and repl[1] else None,
         'C6': bool(net and net['ex'] > 0 and net['cd'] > 0),
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


def to_tot(d, rf):
    return {m: v + rf[m] for m, v in d.items() if m in rf}


# ───────────────────────── 取得（mw_common の取得部品だけ） ─────────────────────────
def parse_pf(rows):
    d = collections.defaultdict(dict)
    for x in rows:
        if x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x.get('n') not in (None, '', 'NA', 'na') else 0
        d[x['pf']][M._ym(x['date'])] = (float(x['ret']), n)
    return dict(d)


def pf_all(loc, w='vw'):
    """all_factors の三分位 → {特性: {pf: {ym: (ret, n)}}}"""
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for x in M.jkp_rows(loc, 'all_factors', 'portfolios', w):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        out[x['name']][x['pf']][M._ym(x['date'])] = (float(x['ret']), int(float(x['n'])) if x['n'] not in ('', 'NA', 'na') else 0)
    return {k: dict(v) for k, v in out.items()}


def pf_one(loc, key, w='vw'):
    try:
        return parse_pf(M.jkp_rows(loc, key, 'portfolios', w))
    except Exception:  # noqa
        return None


def mkt(loc):
    return {M._ym(x['date']): float(x['ret']) for x in M.jkp_rows(loc, 'mkt', 'factor', 'vw') if x['ret'] not in ('', 'NA', 'na')}


def country_table():
    b = M.get('https://jkpfactors-data.s3.amazonaws.com/public/%5Ball_countries%5D_%5Bmkt%5D_%5Bmonthly%5D_%5Bvw%5D.zip',
              name='jkp_factor_all_countries_mkt_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    ret, ns = collections.defaultdict(dict), collections.defaultdict(dict)
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        ym = M._ym(x['date'])
        if x['ret'] not in ('', 'NA', 'na'):
            ret[x['location']][ym] = float(x['ret'])
        if x['n_stocks'] not in ('', 'NA', 'na'):
            ns[x['location']][ym] = int(float(x['n_stocks']))
    return dict(ret), dict(ns)


def french_intl(zipname, which):
    """French の国際 .Dat（zip）を自前で読む。which: 表の見出しに含む語 → {ファイル: {列: {ym: 小数}}}"""
    b = M.get(f'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{zipname}.zip', name=f'fr_{zipname}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    cols_names = ['Mkt', 'BM_H', 'BM_L', 'EP_H', 'EP_L', 'CEP_H', 'CEP_L', 'DP_H', 'DP_L', 'Zero']
    out = {}
    for nm in z.namelist():
        lines = z.read(nm).decode('latin-1').splitlines()
        res, on, hdr_ok = {c: {} for c in cols_names}, False, 0
        for ln in lines:
            if not on:
                if 'Dollar Returns' in ln and which in ln:
                    on = True; hdr_ok = 0
                continue
            p = ln.split()
            if hdr_ok < 2:
                if p[:1] == ['Mkt']:
                    hdr_ok = 2
                continue
            if not p or not p[0].isdigit() or len(p[0]) != 6:
                break
            for c, v in zip(cols_names, p[1:]):
                f = float(v)
                if f > -99.0:
                    res[c][int(p[0])] = f / 100
        out[nm.rsplit('.', 1)[0]] = res
    return out


def french_vw(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'value weight' in t.lower():
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def french_mkt(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(name)


def yh(t, cutoff):
    return {k: v for k, v in M.yahoo(t).items() if k < cutoff}


# ───────────────────────── 組み立て（自前） ─────────────────────────
def own_good_side(us_all, key):
    """米国 vw の 2006-12 までの (第3−第1) の平均の符号（研究側は因子との相関の符号＝別の方法で出し直す）"""
    p = us_all.get(key)
    if not p or '3.0' not in p or '1.0' not in p:
        return None, None
    d = [p['3.0'][m][0] - p['1.0'][m][0] for m in p['3.0'] if m in p['1.0'] and m <= TR_END and p['3.0'][m][1] >= NMIN and p['1.0'][m][1] >= NMIN]
    if len(d) < 60:
        return None, None
    mu = S.mean(d)
    return ('3.0' if mu > 0 else '1.0'), round(mu * 1200, 2)


def select(pf, side, den=None, start=None, rmin=None, nmin=NMIN):
    """良い側（または指定の三分位）の月を規則で選ぶ。den={ym: 市場の銘柄数} があれば被覆率 R を自分で計算して篩う"""
    if not pf or side not in pf:
        return {}
    out = {}
    for m, (r, n) in pf[side].items():
        if n < nmin or (start and m < start):
            continue
        if rmin is not None:
            tot = sum(pf[q][m][1] for q in pf if m in pf[q])
            d = (den or {}).get(m)
            if not d or tot / d < rmin:
                continue
        out[m] = r
    return out


def evaluate(g, mk, rf, turn, unit=UNIT):
    ms = [m for m in sorted(g) if m in mk and m in rf]
    if len(ms) < 60:
        return None
    s = to_tot({m: g[m] for m in ms}, rf); b = to_tot({m: mk[m] for m in ms}, rf)
    net = net_of(s, turn, unit)
    drop_bub_cov = lambda k: 199801 <= k <= 200012 or 202001 <= k <= 202112
    out = {'start': ms[0], 'end': ms[-1],
           'full': st(s, b), 'train': st(s, b, z=TR_END), 'hold': st(s, b, a=HO_START), 'recent': st(s, b, a=REC_START),
           'hold_net': st(net, b, a=HO_START), 'hold_net_2x': st(net_of(s, turn, unit * 2), b, a=HO_START),
           'roll20': roll_lump(s, b, 20), 'dca20': dca_ratio(s, b, 20),
           'hold_first_half': st(s, b, a=HO_START, z=H1_END), 'hold_second_half': st(s, b, a=H2_START),
           'full_drop_1998_2000_2020_2021': st(s, b, drop=drop_bub_cov), 'hold_drop_2020_2021': st(s, b, a=HO_START, drop=drop_bub_cov),
           'hold_drop_2007_2009': st(s, b, a=201001), 'hold_drop_2022': st(s, b, a=HO_START, drop=lambda k: 202201 <= k <= 202212),
           'roll10_in_hold': roll_lump(s, b, 10, a=HO_START)}
    yr = collections.defaultdict(lambda: [1.0, 1.0])
    for m in ms:
        if m >= HO_START:
            yr[m // 100][0] *= 1 + s[m]; yr[m // 100][1] *= 1 + b[m]
    yv = {y: round((v[0] - v[1]) * 100, 1) for y, v in sorted(yr.items())}
    out['hold_calendar_years'] = {'years': len(yv), 'wins': sum(1 for v in yv.values() if v > 0), 'by_year': yv}
    best = max(yv, key=lambda y: yv[y]) if yv else None
    out['hold_drop_2009_only'] = st(s, b, a=HO_START, drop=lambda k: k // 100 == 2009)
    out['hold_drop_best_year'] = {'year': best, 'stats': st(s, b, a=HO_START, drop=lambda k: k // 100 == best)} if best else None
    # 相対の最大下落（良い側 ÷ 市場）
    w, pk, dd, at = 1.0, 1.0, 0.0, None
    for m in ms:
        w *= (1 + s[m]) / (1 + b[m]); pk = max(pk, w)
        if w / pk - 1 < dd:
            dd, at = w / pk - 1, m
    out['relative_max_drawdown'] = [round(dd * 100, 1), at]
    out['break_even_unit_cost_hold_pct'] = round(out['hold']['ex'] / 100 / turn * 100, 2) if out['hold'] and turn else None
    return out


def pooled(series_by_country, cm, rf, a=None, z=None, only=None):
    """国ごとの (良い側 − その国の市場) を各月に等分で平均し、その時系列の年率と NW t（国をまたいだ相関は時系列の t が吸収）"""
    acc = collections.defaultdict(list)
    for c, g in series_by_country.items():
        if only and not only(c):
            continue
        for m, v in g.items():
            if m in cm[c] and (a is None or m >= a) and (z is None or m <= z):
                acc[m].append(v - cm[c][m])
    ms = sorted(acc)
    if len(ms) < 24:
        return None
    x = [S.mean(acc[m]) for m in ms]
    t = nw_tstat(x)
    return {'ex': round(S.mean(x) * 1200, 2), 't': None if t is None else round(t, 2), 'months': len(ms),
            'countries_per_month_median': sorted(len(acc[m]) for m in ms)[len(ms) // 2]}


def covered_gap(pf, mk, rf, rule_months, win=36):
    """市場 − (三分位3つの時価の重みを直前36か月の回帰で推定した合成)。重みは合計1・前の窓だけで推定（先読みなし）。
    負なら『三分位に入れた銘柄の全体（被覆された母集団）』が市場に勝っていた＝良い側の超過の一部は特性ではなく母集団の差"""
    import numpy as np
    ms = [m for m in sorted(rule_months) if m in mk and all(m in pf.get(q, {}) for q in ('1.0', '2.0', '3.0'))]
    gaps, gm = [], []
    for i in range(win, len(ms)):
        w_ms = ms[i - win:i]
        y = np.array([mk[m] - pf['3.0'][m][0] for m in w_ms])
        X = np.array([[pf['1.0'][m][0] - pf['3.0'][m][0], pf['2.0'][m][0] - pf['3.0'][m][0]] for m in w_ms])
        w12, *_ = np.linalg.lstsq(X, y, rcond=None)
        m = ms[i]
        rep = w12[0] * pf['1.0'][m][0] + w12[1] * pf['2.0'][m][0] + (1 - w12[0] - w12[1]) * pf['3.0'][m][0]
        gaps.append(mk[m] - rep); gm.append(m)
    def summ(a=None, z=None):
        x = [g for g, m in zip(gaps, gm) if (a is None or m >= a) and (z is None or m <= z)]
        if len(x) < 24:
            return None
        t = nw_tstat(x)
        return {'market_minus_covered_ann_pct': round(S.mean(x) * 1200, 2), 't': None if t is None else round(t, 2), 'months': len(x)}
    return {'full': summ(), 'train': summ(z=TR_END), 'hold': summ(a=HO_START)}


def ols_nw(y, X, L=12):
    """y = X b + e の最小二乗と Newey-West（Bartlett, ラグ12）の t。X は定数項を含める"""
    import numpy as np
    y = np.asarray(y); X = np.asarray(X)
    n, k = X.shape
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe / n
    for l in range(1, L + 1):
        G = Xe[l:].T @ Xe[:-l] / n
        Sm += (1 - l / (L + 1)) * (G + G.T)
    Q = np.linalg.inv(X.T @ X / n)
    V = Q @ Sm @ Q / n
    return b, b / np.sqrt(np.diag(V))


def alpha_size_beta(g, mk, smb, a=None, z=None):
    """(良い側 − 市場) を 市場の超過 と 小型−大型（JKP world_ex_us の時価三分位 1−3）に回帰した定数項（年率%）"""
    ms = [m for m in sorted(g) if m in mk and m in smb and (a is None or m >= a) and (z is None or m <= z)]
    if len(ms) < 36:
        return None
    y = [g[m] - mk[m] for m in ms]
    X = [[1.0, mk[m], smb[m]] for m in ms]
    b, t = ols_nw(y, X)
    X1 = [[1.0, mk[m]] for m in ms]
    b1, t1 = ols_nw(y, X1)
    return {'alpha_mkt_only': round(float(b1[0]) * 1200, 2), 't_alpha_mkt_only': round(float(t1[0]), 2), 'beta_minus_1': round(float(b1[1]), 3),
            'alpha_mkt_smb': round(float(b[0]) * 1200, 2), 't_alpha_mkt_smb': round(float(t[0]), 2), 'smb_loading': round(float(b[2]), 3),
            't_smb': round(float(t[2]), 2), 'months': len(ms)}


# ───────────────────────── 回転率のモンテカルロ（勢い・残差の勢い） ─────────────────────────
def turnover_mc(seed=11, N=1500, T=300, burn=48):
    import numpy as np
    rng = np.random.default_rng(seed)
    beta = rng.uniform(0.6, 1.4, N)
    isd = np.exp(rng.normal(np.log(0.09), 0.35, N))            # 固有のボラ（月・中央9%）
    f = rng.normal(0.006, 0.045, burn + T)
    e = rng.normal(0, 1, (burn + T, N)) * isd
    r = np.clip(beta * f[:, None] + e, -0.9, 3.0)
    cap = np.exp(rng.normal(0, 1.6, N))
    caps = np.empty((burn + T, N))
    for t in range(burn + T):
        caps[t] = cap; cap = cap * (1 + r[t])
    res = {}
    for kind in ('ret_12_1', 'resff3_12_1'):
        tos, prev = [], None
        for t in range(36, burn + T - 1):
            if kind == 'ret_12_1':
                sig = np.prod(1 + r[t - 11:t], axis=0) - 1          # t-11..t-1（直近1か月を飛ばす）
            else:
                sig = e[t - 11:t].sum(axis=0) / e[t - 36:t].std(axis=0)
            q = np.quantile(sig, 2 / 3)
            top = sig >= q
            wgt = np.where(top, caps[t], 0.0); wgt = wgt / wgt.sum()
            if prev is not None:
                drift = prev * (1 + r[t - 1]); drift = drift / drift.sum()
                if t >= burn:
                    tos.append(0.5 * np.abs(wgt - drift).sum())
            prev = wgt
        res[kind] = {'monthly_one_way_mean': round(float(np.mean(tos)), 4), 'annual_one_way': round(float(np.mean(tos)) * 12, 2)}
    res['setup'] = f'N={N}銘柄・月次・β U(0.6,1.4)・固有ボラ 月中央9%・時価は対数正規で収益に連れて動く・上位1/3を時価加重・直近の月を飛ばす。研究側の仮定は勢い・残差の勢いとも年1.5'
    return res


# ───────────────────────── 本体 ─────────────────────────
def main():
    cutoff = int(datetime.date.today().strftime('%Y%m'))
    rf = M.ff_factors()['rf']
    wx_mkt = mkt('world_ex_us')
    cm, cn = country_table()
    den_exus = collections.Counter()
    for loc, d in cn.items():
        if loc != 'usa':
            for m, n in d.items():
                den_exus[m] += n
    WX = pf_all('world_ex_us', 'vw')
    US = pf_all('usa', 'vw')
    us_mkt = mkt('usa')
    MC = turnover_mc()
    dx_mkt = french_mkt('Developed_ex_US_3_Factors')
    Y = {}
    _sm, _bg = select(WX['market_equity'], '1.0', den_exus, START2, RMIN), select(WX['market_equity'], '3.0', den_exus, START2, RMIN)
    SMB = {m: _sm[m] - _bg[m] for m in _sm if m in _bg}
    out = {'tool': 'night/mw_intl_verify.py', 'target': 'out/mw_intl.json（研究側 night/mw_intl.py）', 'generated': datetime.date.today().isoformat(),
           'independence': 'mw_common からは取得（jkp_rows・french_tables・ff_factors・yahoo・get）だけを使い、良い側（米国 ≤2006 の 第3−第1 の平均の符号＝研究側の『因子との相関の符号』とは別の方法）・被覆率 R・系列・平均・NW t・CAGR・20年窓・積立・費用・格付けは全部自前',
           'candidates': {}}

    # 良い側（自前）
    side, side_note = {}, {}
    for k in set(CHARS20) | {n for v in NEIGHBORS.values() for n in v} | set(WX):
        s_, mu = own_good_side(US, k)
        side[k] = s_; side_note[k] = mu
    researcher_side = json.load(open(os.path.join(BASE, 'out', 'mw_intl.json')))['good_side']
    out['good_side_check'] = {k: {'own': side[k], 'us_T3_minus_T1_to_2006_pct': side_note[k], 'researcher': researcher_side.get(k),
                                  'agree': side[k] == researcher_side.get(k)} for k in CHARS20}

    # 国の三分位（6特性・vw）
    avail = json.loads(M.get('https://jkpfactors-data.s3.amazonaws.com/public/availability.json', name='jkp_availability.json'))
    regions = {'all_countries', 'all_regions', 'usa', 'world_ex_us', 'developed', 'emerging', 'world', 'frontier'}
    countries = sorted(c for c in avail['portfolios'] if c not in regions and c in cm and len(cm[c]) >= 240)
    KEYS6 = sorted({k for _, k in CANDS})
    CPF = {(c, k): pf_one(c, k) for c in countries for k in KEYS6 if k in avail['portfolios'].get(c, [])}

    # 族の Holm（自前・F2a の21本と主の21本）
    def fam_holm(rule):
        ps = {}
        for k in CHARS20:
            g = rule(WX.get(k), side[k])
            ev = evaluate(g, wx_mkt, rf, 0.5)
            if ev and ev['hold']:
                ps[k] = ev['hold']['p']
        parts = [rule(WX.get(k), side[k]) for k in QUALITY]
        ms = set.intersection(*[set(p) for p in parts]) if all(parts) else set()
        bq = {m: S.mean(p[m] for p in parts) for m in ms}
        ev = evaluate(bq, wx_mkt, rf, 0.4)
        if ev and ev['hold']:
            ps['blend_quality'] = ev['hold']['p']
        return holm_adj(ps), ps
    rule_primary = lambda pf, sd: select(pf, sd)
    rule_f2a = lambda pf, sd: select(pf, sd, den_exus, START2, RMIN)
    HOLM = {'primary': fam_holm(rule_primary), 'F2a': fam_holm(rule_f2a)}
    out['family_holm_own'] = {f: {'holm': h, 'raw_p': p} for f, (h, p) in HOLM.items()}

    researcher = json.load(open(os.path.join(BASE, 'out', 'mw_intl.json')))

    for fam, k in CANDS:
        name = f'{fam}:{k}'
        rule = rule_primary if fam == 'primary' else rule_f2a
        g = rule(WX[k], side[k])
        ev = evaluate(g, wx_mkt, rf, TURN[k])
        # C5（自前）: 米国外の国、全期間の超過が正の割合
        per_c, pos, tot, posh, toth = {}, 0, 0, 0, 0
        cseries = {}
        for c in countries:
            pf = CPF.get((c, k))
            if not pf:
                continue
            gc = select(pf, side[k]) if fam == 'primary' else select(pf, side[k], cn.get(c, {}), START2, RMIN)
            ms = [m for m in sorted(gc) if m in cm[c] and m in rf]
            if len(ms) < 240:
                continue
            sc = {m: gc[m] for m in ms}
            cseries[c] = sc
            s_, b_ = to_tot(sc, rf), to_tot({m: cm[c][m] for m in ms}, rf)
            f_, h_ = st(s_, b_), st(s_, b_, a=HO_START)
            per_c[c] = {'full': f_ and (f_['ex'], f_['t']), 'hold': h_ and (h_['ex'], h_['t'])}
            tot += 1; pos += 1 if f_ and f_['ex'] > 0 else 0
            if h_:
                toth += 1; posh += 1 if h_['ex'] > 0 else 0
        hp = HOLM[fam][0].get(k)
        gr, crit = grade_own(ev['full'], ev['train'], ev['hold'], ev['roll20'], ev['hold_net'], (pos, tot), hp)
        rec = {'reproduced': ev, 'own_grade': gr, 'own_criteria': crit, 'own_family_holm_p': hp,
               'countries_full_positive': [pos, tot], 'countries_hold_positive': [posh, toth], 'per_country': per_c}
        cl = CLAIM[name]
        rec['claim'] = cl
        rec['match'] = {'full_ex': abs(ev['full']['ex'] - cl['full'][0]) <= 0.02, 'full_t': abs(ev['full']['t'] - cl['full'][1]) <= 0.02,
                        'train_ex': abs(ev['train']['ex'] - cl['train'][0]) <= 0.02, 'train_t': abs(ev['train']['t'] - cl['train'][1]) <= 0.02,
                        'hold_ex': abs(ev['hold']['ex'] - cl['hold'][0]) <= 0.02, 'hold_t': abs(ev['hold']['t'] - cl['hold'][1]) <= 0.02,
                        'hold_cd': abs(ev['hold']['cd'] - cl['cd']) <= 0.02, 'net': abs(ev['hold_net']['ex'] - cl['net']) <= 0.02,
                        'grade': gr == cl['grade']}

        adv = {}
        # (1) 被覆の規則・始まりの近隣（F2a だけ意味がある。主の族でも参考に出す）
        rs = {}
        for lab, kw in (('R_only_no_1990_start', dict(den=den_exus, start=None, rmin=RMIN)),
                        ('R0.3_1990', dict(den=den_exus, start=START2, rmin=0.3)), ('R0.5_1990', dict(den=den_exus, start=START2, rmin=0.5)),
                        ('R0.6_1990', dict(den=den_exus, start=START2, rmin=0.6)), ('start1987_R0.4', dict(den=den_exus, start=198701, rmin=RMIN)),
                        ('start1992_R0.4', dict(den=den_exus, start=199201, rmin=RMIN)), ('n30_F2a', dict(den=den_exus, start=START2, rmin=RMIN, nmin=30)),
                        ('primary_1986_all', dict())):
            e2 = evaluate(select(WX[k], side[k], **kw), wx_mkt, rf, TURN[k])
            if e2:
                gg, cc = grade_own(e2['full'], e2['train'], e2['hold'], e2['roll20'], e2['hold_net'], (pos, tot), hp)
                rs[lab] = {'start': e2['start'], 'full': e2['full'], 'train': e2['train'], 'hold': e2['hold'], 'grade_same_holm': gg,
                           'C1': cc['C1'], 'C7_via_full_t': bool(e2['full']['t'] and e2['full']['t'] >= 3.0)}
            else:
                rs[lab] = None
        adv['rule_neighbors'] = rs
        # (2) 三分位の中の時価加重の型（vw_cap・ew）
        wt = {}
        for w in ('vw_cap', 'ew'):
            p2 = pf_one('world_ex_us', k, w)
            e2 = evaluate(rule(p2, side[k]), wx_mkt, rf, TURN[k]) if p2 else None
            wt[w] = e2 and {'full': e2['full'], 'train': e2['train'], 'hold': e2['hold'], 'hold_net': e2['hold_net']}
        adv['weighting_neighbors_vs_pure_vw_market'] = wt
        # (3) 近隣の特性（同じ規則・同じ相手）
        nb = {}
        for k2 in NEIGHBORS[k]:
            if k2 not in WX or side.get(k2) is None:
                continue
            e2 = evaluate(rule(WX[k2], side[k2]), wx_mkt, rf, TURN.get(k2, TURN[k]))
            nb[k2] = e2 and {'side': side[k2], 'full': e2['full'], 'train': e2['train'], 'hold': e2['hold']}
        adv['characteristic_neighbors'] = nb
        # (4) 三分位の並び（保有期間）と『被覆された母集団』への依存
        ters = {}
        for q in ('1.0', '2.0', '3.0'):
            gq = rule(WX[k], q) if fam == 'F2a' else select(WX[k], q)
            e2 = evaluate(gq, wx_mkt, rf, TURN[k])
            ters[q] = e2 and {'full': e2['full'], 'hold': e2['hold']}
        good, bad = side[k], ('1.0' if side[k] == '3.0' else '3.0')
        avg3 = {}
        for m in g:
            if all(m in WX[k].get(q, {}) for q in ('1.0', '2.0', '3.0')):
                avg3[m] = S.mean(WX[k][q][m][0] for q in ('1.0', '2.0', '3.0'))
        e_avg = evaluate(avg3, wx_mkt, rf, 0)
        gm = {m: g[m] - avg3[m] for m in g if m in avg3}
        zero = {m: 0.0 for m in gm}
        ters['good_minus_avg_of_3_terciles'] = {'full': st(gm, zero), 'hold': st(gm, zero, a=HO_START)}
        ters['avg_of_3_terciles_vs_market'] = e_avg and {'full': e_avg['full'], 'train': e_avg['train'], 'hold': e_avg['hold']}
        ters['good_side'] = good; ters['bad_side'] = bad
        adv['terciles'] = ters
        adv['covered_universe_gap_rolling36'] = covered_gap(WX[k], wx_mkt, rf, g)
        adv['alpha_after_beta_and_size'] = {'hold': alpha_size_beta(g, wx_mkt, SMB, a=HO_START), 'full': alpha_size_beta(g, wx_mkt, SMB)}
        # 現実的な費用（回転率はモンテカルロ・単価 0.3%/0.4%）
        mc_turn = {'ret_12_1': MC['ret_12_1']['annual_one_way'], 'resff3_12_1': MC['resff3_12_1']['annual_one_way']}.get(k, TURN[k] * 1.6)
        ms_ = [m for m in sorted(g) if m in wx_mkt and m in rf]
        s_ = to_tot({m: g[m] for m in ms_}, rf); b_ = to_tot({m: wx_mkt[m] for m in ms_}, rf)
        adv['cost_realistic'] = {'turnover_used': mc_turn, 'why': '勢いは自前のモンテカルロ・会計の特性は研究側の1.6倍（JKP の比率は毎月の時価で更新されるため）',
                                 'unit_0.3pct': st(net_of(s_, mc_turn, 0.003), b_, a=HO_START), 'unit_0.4pct': st(net_of(s_, mc_turn, 0.004), b_, a=HO_START)}
        # 訓練に使った国（米国）の 2007年以降
        us_g = select(US.get(k), side[k])
        us_e = evaluate(us_g, us_mkt, rf, TURN[k], 0.001)
        adv['us_training_country_hold'] = us_e and {'full': us_e['full'], 'train': us_e['train'], 'hold': us_e['hold'], 'recent': us_e['recent']}
        # (5) 国に依存しないか（等分の国平均）・日本抜き・先進国だけ
        adv['country_neutral_equal_weight'] = {
            'all_ex_us_hold': pooled(cseries, cm, rf, a=HO_START), 'all_ex_us_full': pooled(cseries, cm, rf),
            'developed_ex_us_hold': pooled(cseries, cm, rf, a=HO_START, only=lambda c: c in DEVELOPED),
            'developed_ex_us_ex_japan_hold': pooled(cseries, cm, rf, a=HO_START, only=lambda c: c in DEVELOPED and c != 'jpn'),
            'emerging_hold': pooled(cseries, cm, rf, a=HO_START, only=lambda c: c not in DEVELOPED),
            'all_ex_us_hold_first_half': pooled(cseries, cm, rf, a=HO_START, z=H1_END), 'all_ex_us_hold_second_half': pooled(cseries, cm, rf, a=H2_START)}
        # 研究側の数字との突き合わせ
        rr = researcher['regional']['world_ex_us'][k] if fam == 'primary' else researcher['prereg2']['families']['F2a_screened']['members'][k]
        rec['researcher_numbers'] = {'full': (rr['full']['ex_ann'], rr['full']['t']), 'train': (rr['train']['ex_ann'], rr['train']['t']),
                                     'hold': (rr['hold']['ex_ann'], rr['hold']['t'], rr['hold']['cagr_diff']), 'roll20': (rr['roll20']['wins'], rr['roll20']['windows']),
                                     'dca20_median': rr['dca20']['median_ratio']}
        rec['adversarial'] = adv
        out['candidates'][name] = rec
        print(name, gr, 'full', ev['full']['ex'], ev['full']['t'], 'train', ev['train']['ex'], ev['train']['t'], 'hold', ev['hold']['ex'], ev['hold']['t'], ev['hold']['cd'],
              'net', ev['hold_net']['ex'], 'roll', ev['roll20']['wins'], ev['roll20']['windows'], 'dca', ev['dca20']['median'], 'C5', pos, tot, 'match', all(rec['match'].values()))

    # ── 追加: 研究側の見出し（依頼の候補一覧には無いが要約の『いちばん強い』）F2b val_mom と F2c 日本の be_me
    extra = {}
    VAL4 = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
    parts = [rule_f2a(WX[q], side[q]) for q in VAL4]
    msv = set.intersection(*[set(p) for p in parts])
    vc = {m: S.mean(p[m] for p in parts) for m in msv}
    mo = rule_f2a(WX['ret_12_1'], side['ret_12_1'])
    vm = {m: 0.5 * vc[m] + 0.5 * mo[m] for m in vc if m in mo}
    turn_vm = 0.5 * 0.4 + 0.5 * 1.5
    ev = evaluate(vm, wx_mkt, rf, turn_vm)
    ms_ = [m for m in sorted(vm) if m in wx_mkt and m in rf]
    s_, b_ = to_tot({m: vm[m] for m in ms_}, rf), to_tot({m: wx_mkt[m] for m in ms_}, rf)
    real_turn = 0.5 * 0.64 + 0.5 * MC['ret_12_1']['annual_one_way']
    # 国ごと（等分の国平均）: その国の割安4本のうち2本以上の平均 50% ＋ 勢い 50%
    cs = {}
    for c in countries:
        vv = [select(CPF[(c, q)], side[q], cn.get(c, {}), START2, RMIN) for q in VAL4 if CPF.get((c, q))]
        vv = [v for v in vv if v]
        mm = select(CPF.get((c, 'ret_12_1')), side['ret_12_1'], cn.get(c, {}), START2, RMIN) if CPF.get((c, 'ret_12_1')) else {}
        if len(vv) < 2 or not mm:
            continue
        g_ = {}
        for m in mm:
            x = [v[m] for v in vv if m in v]
            if len(x) >= 2:
                g_[m] = 0.5 * S.mean(x) + 0.5 * mm[m]
        g_ = {m: v for m, v in g_.items() if m in cm[c] and m in rf}
        if len(g_) >= 240:
            cs[c] = g_
    posh = sum(1 for c, g_ in cs.items() if (st(to_tot(g_, rf), to_tot({m: cm[c][m] for m in g_}, rf), a=HO_START) or {}).get('ex', -1) > 0)
    fb = french_vw('Developed_ex_US_6_Portfolios_ME_BE-ME')['BIG HiBM']; fp = french_vw('Developed_ex_US_6_Portfolios_ME_Prior_12_2')['BIG HiPRIOR']
    fvm = {m: 0.5 * fb[m] + 0.5 * fp[m] for m in fb if m in fp and m in dx_mkt}
    etfc = {}
    for a1, a2, bb in (('EFV', 'IMTM', 'EFA'), ('IVLU', 'IMTM', 'EFA'), ('PXF', 'PIZ', 'EFA'), ('EFV', 'PIZ', 'EFA')):
        try:
            for t in (a1, a2, bb):
                if t not in Y:
                    Y[t] = yh(t, cutoff)
            ks = [m for m in sorted(Y[a1]) if m in Y[a2] and m in Y[bb]]
            etfc[f'{a1}+{a2} vs {bb}'] = st({m: 0.5 * Y[a1][m] + 0.5 * Y[a2][m] for m in ks}, {m: Y[bb][m] for m in ks})
        except Exception as e:  # noqa
            etfc[f'{a1}+{a2} vs {bb}'] = {'error': str(e)[:120]}
    extra['F2b_combos:val_mom'] = {
        'researcher_claim': 'S（全 +2.99 t6.10・訓 +3.93 t4.68・保 +2.18 t4.62・費後 +1.90・40か国すべて正）',
        'reproduced': {w: ev[w] for w in ('full', 'train', 'hold', 'recent', 'hold_net', 'roll20', 'hold_first_half', 'hold_second_half',
                                          'hold_drop_2009_only', 'hold_drop_best_year', 'roll10_in_hold', 'relative_max_drawdown')},
        'cost_realistic': {'turnover': round(real_turn, 2), 'unit_0.3pct': st(net_of(s_, real_turn, 0.003), b_, a=HO_START), 'unit_0.4pct': st(net_of(s_, real_turn, 0.004), b_, a=HO_START)},
        'alpha_after_beta_and_size_hold': alpha_size_beta(vm, wx_mkt, SMB, a=HO_START),
        'countries_hold_positive': [posh, len(cs)],
        'country_neutral_equal_weight': {'all_ex_us_hold': pooled(cs, cm, rf, a=HO_START), 'developed_ex_us_hold': pooled(cs, cm, rf, a=HO_START, only=lambda c: c in DEVELOPED),
                                         'developed_ex_us_ex_japan_hold': pooled(cs, cm, rf, a=HO_START, only=lambda c: c in DEVELOPED and c != 'jpn'),
                                         'emerging_hold': pooled(cs, cm, rf, a=HO_START, only=lambda c: c not in DEVELOPED)},
        'french_big_HiBM_plus_HiPRIOR_dev_ex_us': {'full': st(fvm, dx_mkt), 'train': st(fvm, dx_mkt, z=TR_END), 'hold': st(fvm, dx_mkt, a=HO_START)},
        'etf_combos_survivors': etfc}
    us_vc = [select(US[q], side[q]) for q in VAL4]
    msu = set.intersection(*[set(p) for p in us_vc])
    us_mo = select(US['ret_12_1'], side['ret_12_1'])
    us_vm = {m: 0.5 * S.mean(p[m] for p in us_vc) + 0.5 * us_mo[m] for m in msu if m in us_mo}
    ue = evaluate(us_vm, us_mkt, rf, turn_vm, 0.001)
    extra['F2b_combos:val_mom']['us_training_country'] = ue and {'train': ue['train'], 'hold': ue['hold'], 'recent': ue['recent']}
    # 日本の be_me（F2c）
    jb = select(CPF[('jpn', 'be_me')], side['be_me'], cn.get('jpn', {}), START2, RMIN)
    ej = evaluate(jb, cm['jpn'], rf, 0.3)
    fj = french_intl('F-F_International_Countries', 'Not Reqd')['Japan']
    msj = [m for m in sorted(fj['BM_H']) if m in fj['Mkt']]
    extra['F2c_japan:be_me'] = {
        'researcher_claim': 'S（全 +5.44 t3.19・訓 +7.19 t2.42・保 +3.92 t2.20）',
        'reproduced': {w: ej[w] for w in ('full', 'train', 'hold', 'hold_net', 'roll20', 'hold_first_half', 'hold_second_half', 'hold_drop_2009_only',
                                          'hold_drop_best_year', 'roll10_in_hold', 'relative_max_drawdown', 'hold_calendar_years')},
        'msci_japan_bm_high30': {'full': st({m: fj['BM_H'][m] for m in msj}, {m: fj['Mkt'][m] for m in msj}),
                                 'hold': st({m: fj['BM_H'][m] for m in msj}, {m: fj['Mkt'][m] for m in msj}, a=HO_START),
                                 'hold_first_half': st({m: fj['BM_H'][m] for m in msj}, {m: fj['Mkt'][m] for m in msj}, a=HO_START, z=H1_END)}}
    out['extra_headline_checks'] = extra

    # ── 独立のデータ（French）
    fr = {}
    for lab, (fn, col, turn) in {'be_me~French_DevExUS_BIG_HiBM': ('Developed_ex_US_6_Portfolios_ME_BE-ME', 'BIG HiBM', 0.3),
                                 'ret_12_1~French_DevExUS_BIG_HiPRIOR': ('Developed_ex_US_6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 1.5),
                                 'ret_12_1~French_DevExUS_SMALL_HiPRIOR': ('Developed_ex_US_6_Portfolios_ME_Prior_12_2', 'SMALL HiPRIOR', 1.5)}.items():
        try:
            sr = french_vw(fn)[col]
            ms = [m for m in sorted(sr) if m in dx_mkt]
            s_, b_ = {m: sr[m] for m in ms}, {m: dx_mkt[m] for m in ms}
            fr[lab] = {'start': ms[0], 'full': st(s_, b_), 'train': st(s_, b_, z=TR_END), 'hold': st(s_, b_, a=HO_START),
                       'hold_first_half': st(s_, b_, a=HO_START, z=H1_END), 'hold_second_half': st(s_, b_, a=H2_START),
                       'hold_net': st(net_of(s_, turn, UNIT), b_, a=HO_START)}
        except Exception as e:  # noqa
            fr[lab] = {'error': str(e)[:200]}
    for which, tag in (('Not Reqd', 'not_reqd'), ('Items Required', 'required')):
        ind = french_intl('F-F_International_Indices', which)
        cty = french_intl('F-F_International_Countries', which)
        for lab, col in (('be_me~MSCI_EAFE_BM_High30', 'BM_H'), ('ni_me~MSCI_EAFE_EP_High30', 'EP_H'), ('ocf_me~MSCI_EAFE_CEP_High30', 'CEP_H'),
                         ('div12m_me~MSCI_EAFE_Yld_High30', 'DP_H')):
            a_ = ind['Ind_all']
            ms = [m for m in sorted(a_[col]) if m in a_['Mkt']]
            s_, b_ = {m: a_[col][m] for m in ms}, {m: a_['Mkt'][m] for m in ms}
            posc = [0, 0]
            for c, d in cty.items():
                mm = [m for m in d[col] if m in d['Mkt'] and m >= HO_START]
                if len(mm) >= 120:
                    posc[1] += 1
                    posc[0] += 1 if S.mean(d[col][m] - d['Mkt'][m] for m in mm) > 0 else 0
            fr[f'{lab}_{tag}'] = {'start': ms[0], 'end': ms[-1], 'full': st(s_, b_), 'train': st(s_, b_, z=TR_END), 'hold': st(s_, b_, a=HO_START),
                                   'hold_first_half': st(s_, b_, a=HO_START, z=H1_END), 'hold_second_half': st(s_, b_, a=H2_START),
                                   'hold_net': st(net_of(s_, 0.3, UNIT), b_, a=HO_START), 'countries_hold_positive': posc}
    out['independent_french'] = fr

    # ── 実在の商品（生き残りだけ・費用後・Yahoo 調整後終値）
    etf = {}
    pairs = [('EFV', 'EFA', 'be_me/ni_me/div（MSCI EAFE Value）'), ('IVLU', 'EFA', 'be_me/ni_me/ocf_me（MSCI Intl Enhanced Value）'),
             ('PXF', 'EFA', 'value（FTSE RAFI Dev ex US・基本指標加重）'), ('FNDF', 'EFA', 'value（Schwab 基本指標）'),
             ('DFIVX', 'EFA', 'be_me（DFA 国際割安・実運用）'), ('DFIVX', 'DFALX', 'be_me（DFA 国際割安 vs DFA 大型）'),
             ('IDV', 'EFA', 'div12m_me（iShares 国際高配当）'), ('DWX', 'EFA', 'div12m_me（SPDR 国際配当）'), ('VYMI', 'VEU', 'div12m_me（Vanguard 国際高配当）'),
             ('PIZ', 'EFA', 'ret_12_1（Invesco DWA 先進国の勢い）'), ('IMTM', 'EFA', 'ret_12_1（iShares 国際の勢い）'),
             ('FID', 'EFA', 'div12m_me（First Trust 国際配当貴族・楽天で買える）')]
    try:
        lineup = set(json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs'])
    except Exception:  # noqa
        lineup = set()
    for a_, b_, why in pairs:
        try:
            for t in (a_, b_):
                if t not in Y:
                    Y[t] = yh(t, cutoff)
            ra, rb = Y[a_], Y[b_]
            ks = [m for m in sorted(ra) if m in rb]
            sa, sb = {m: ra[m] for m in ks}, {m: rb[m] for m in ks}
            etf[f'{a_} vs {b_}'] = {'what': why, 'from': ks[0], 'to': ks[-1], 'all': st(sa, sb), 'from_2007': st(sa, sb, a=HO_START),
                                    'from_2013_07': st(sa, sb, a=REC_START), 'in_rakuten_lineup': a_ in lineup}
        except Exception as e:  # noqa
            etf[f'{a_} vs {b_}'] = {'error': str(e)[:200]}
    out['etf_reality_survivors_only'] = etf

    # ── 相手（JKP world_ex_us vw 市場）が実在の指数と比べて弱くないか
    bm = {}
    jw = to_tot(wx_mkt, rf)
    for t in ('VGTSX', 'ACWX', 'VEU'):
        try:
            if t not in Y:
                Y[t] = yh(t, cutoff)
            ks = [m for m in sorted(Y[t]) if m in jw]
            a_, b_ = {m: jw[m] for m in ks}, {m: Y[t][m] for m in ks}
            full, hold = st(a_, b_), st(a_, b_, a=HO_START)
            cc = S.correlation([a_[m] for m in ks], [b_[m] for m in ks])
            bm[f'JKP_world_ex_us_vw_mkt vs {t}'] = {'from': ks[0], 'to': ks[-1], 'corr': round(cc, 4), 'full_cagr_diff': full['cd'], 'hold_cagr_diff': hold and hold['cd'],
                                                     'note': '正なら JKP 市場のほうが高い（=相手として弱くはない）。実在の投信・ETF は費用後（年0.1〜0.2%）'}
        except Exception as e:  # noqa
            bm[t] = {'error': str(e)[:200]}
    ks = [m for m in sorted(dx_mkt) if m in jw]
    bm['JKP_world_ex_us_vw_mkt vs French_Developed_ex_US_Mkt'] = {'corr': round(S.correlation([jw[m] for m in ks], [dx_mkt[m] for m in ks]), 4),
                                                                   'hold_cagr_diff': st({m: jw[m] for m in ks}, {m: dx_mkt[m] for m in ks}, a=HO_START)['cd']}
    # 良い側（JKP）を実在の指数投信（VGTSX）と比べる（保有期間）
    vg = {}
    for fam, k in CANDS:
        if fam != 'F2a':
            continue
        g = rule_f2a(WX[k], side[k]); s_ = to_tot(g, rf)
        ks = [m for m in sorted(s_) if m in Y['VGTSX']]
        vg[k] = st({m: s_[m] for m in ks}, {m: Y['VGTSX'][m] for m in ks}, a=HO_START)
    bm['good_side_F2a_vs_VGTSX_hold'] = vg
    out['benchmark_check'] = bm

    # ── 回転率（勢い）
    out['turnover_mc'] = MC
    # 母集団の手がかり: 年齢（age）と残差の勢いが要る履歴（36か月）の三分位
    agediag = {}
    for k2 in ('age', 'market_equity'):
        for q in ('1.0', '2.0', '3.0'):
            e2 = evaluate(select(WX.get(k2), q, den_exus, START2, RMIN), wx_mkt, rf, 0)
            agediag[f'{k2}_{q}'] = e2 and {'hold': e2['hold'], 'full': e2['full']}
    out['universe_diagnostics'] = agediag

    # ── 偽薬の分布: 153特性すべての『良い側（米国 ≤2006 で決めた）』と『悪い側』を同じ規則・同じ相手で
    plc = {}
    for k2, pf in WX.items():
        sd = side.get(k2)
        if sd is None:
            continue
        bd = '1.0' if sd == '3.0' else '3.0'
        r_ = {}
        for lab, q in (('good', sd), ('bad', bd), ('mid', '2.0')):
            e2 = evaluate(select(pf, q, den_exus, START2, RMIN), wx_mkt, rf, 0)
            r_[lab] = e2 and e2['hold'] and (e2['hold']['ex'], e2['hold']['t'])
        plc[k2] = r_
    good = [v['good'] for v in plc.values() if v['good']]
    bad = [v['bad'] for v in plc.values() if v['bad']]
    mid = [v['mid'] for v in plc.values() if v['mid']]
    frac = lambda L, f: round(sum(1 for x in L if f(x)) / len(L), 3) if L else None
    out['placebo_153_characteristics_hold'] = {
        'rule': 'F2a と同じ（1990-07〜・被覆率≥0.4・n≥10）・相手は JKP world_ex_us vw 市場・保有期間 2007〜',
        'n_good': len(good), 'good_positive': frac(good, lambda x: x[0] > 0), 'good_t_ge_1.65': frac(good, lambda x: (x[1] or 0) >= 1.65),
        'good_t_ge_2.45': frac(good, lambda x: (x[1] or 0) >= 2.45),
        'good_median_ex': round(S.median(x[0] for x in good), 2),
        'n_bad': len(bad), 'bad_positive': frac(bad, lambda x: x[0] > 0), 'bad_t_ge_1.65': frac(bad, lambda x: (x[1] or 0) >= 1.65),
        'bad_median_ex': round(S.median(x[0] for x in bad), 2),
        'n_mid': len(mid), 'mid_positive': frac(mid, lambda x: x[0] > 0), 'mid_median_ex': round(S.median(x[0] for x in mid), 2),
        'candidate_rank_among_good_by_hold_t': {k: 1 + sum(1 for v in good if (v[1] or 0) > (plc[k]['good'][1] or 0)) for _, k in CANDS if plc.get(k, {}).get('good')},
        'top10_good_by_hold_t': sorted(((k2, v['good']) for k2, v in plc.items() if v['good']), key=lambda x: -(x[1][1] or 0))[:10]}

    # ── 多重検定
    tested_prog = 0
    for fn in sorted(os.listdir(os.path.join(BASE, 'out'))):
        if not fn.startswith('mw_') or not fn.endswith('.json') or 'prereg' in fn or 'verify' in fn:
            continue
        try:
            d = json.load(open(os.path.join(BASE, 'out', fn)))
        except Exception:  # noqa
            continue

        def walk(o):
            c = 0
            if isinstance(o, dict):
                if isinstance(o.get('tested'), list):
                    c += sum(1 for t in o['tested'] if isinstance(t, dict) and t.get('grade') is not None)
                c += sum(walk(v) for kk, v in o.items() if kk != 'tested')
            elif isinstance(o, list):
                c += sum(walk(v) for v in o)
            return c
        tested_prog += walk(d)
    angle_graded = sum(1 for t in researcher['tested'] if t.get('grade')) + sum(
        1 for p in ('prereg2', 'prereg3', 'prereg4', 'prereg5', 'prereg6') for t in researcher[p]['tested'] if t.get('grade'))
    mt = {'angle_tested_all': researcher.get('n_tested_all'), 'angle_graded': angle_graded, 'program_graded_all_mw_json': tested_prog}
    for name, rec in out['candidates'].items():
        h = rec['reproduced']['hold']
        p_ = pval(h['t'])
        mt[name] = {'hold_t': h['t'], 'hold_p_two_sided': p_, 'bonferroni_angle_p': round(min(1.0, p_ * angle_graded), 4),
                    'bonferroni_program_p': round(min(1.0, p_ * tested_prog), 4), 'full_t': rec['reproduced']['full']['t']}
    out['multiple_testing'] = mt
    out['verdicts'], out['summary_ja'] = judge(out)
    json.dump(out, open(os.path.join(BASE, 'out', 'mw_intl_verify.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    for v in out['verdicts']:
        print(v['name'], v['claimed_grade'], '→', v['verified_grade'], v['verdict'])
    print('→ out/mw_intl_verify.json')


# ───────────────────────── 判定（検証者の判断・上の数字から） ─────────────────────────
def judge(out):
    """数字は全部 out から読む（書き写さない）。判定の言葉は検証者の判断"""
    F = lambda v: '—' if not v else f"{v['ex']:+.2f}%/年 t{v['t']:.2f}"
    C = out['candidates']; FR = out['independent_french']; E = out['etf_reality_survivors_only']; PL = out['placebo_153_characteristics_hold']
    MT = out['multiple_testing']
    rank = PL['candidate_rank_among_good_by_hold_t']

    def common(name):
        r = C[name]; ev = r['reproduced']; a = r['adversarial']
        kn = (f"再現 全{F(ev['full'])}・訓{F(ev['train'])}・保{F(ev['hold'])}・CAGR差 保{ev['hold']['cd']:+.2f}・費後{F(ev['hold_net'])}・"
              f"20年一括 {ev['roll20']['wins']}/{ev['roll20']['windows']}・積立中央 {ev['dca20']['median']}・国 全{r['countries_full_positive'][0]}/{r['countries_full_positive'][1]} "
              f"保{r['countries_hold_positive'][0]}/{r['countries_hold_positive'][1]}（研究側の数字と全項目一致={all(r['match'].values())}）")
        return r, ev, a, kn

    V = []
    # 1 primary:be_me
    r, ev, a, kn = common('primary:be_me')
    rn = a['rule_neighbors']
    V.append({'name': 'primary:be_me', 'claimed_grade': 'A', 'verified_grade': 'B', 'reproduced': all(r['match'].values()), 'verdict': 'downgraded to B',
              'key_numbers': kn, 'issues': [
                  f"C7 は全期間 t={ev['full']['t']} の一本で通っているが、これは 1986-89 年の会計データ被覆の偏り（三分位が市場の銘柄の1割強）で膨らんだ値。被覆率≥0.4 を当てると全期間 {F(rn['R0.3_1990']['full'])}（1990-07〜）・{F(rn['R_only_no_1990_start']['full'])}（被覆だけ・1990-05〜）で C7 不合格＝A は成り立たない（研究者の F2a と同じ結論）",
                  f"保有 t={ev['hold']['t']}（C3 不合格）。前半 2007-16 {F(ev['hold_first_half'])}・2009年だけ除くと {F(ev['hold_drop_2009_only'])}・β と小型−大型で調整した α {a['alpha_after_beta_and_size']['hold']['alpha_mkt_smb']:+.2f} t{a['alpha_after_beta_and_size']['hold']['t_alpha_mkt_smb']}",
                  f"国を等分に平均すると先進国（米国外）だけでは {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}・新興国 {F(a['country_neutral_equal_weight']['emerging_hold'])}＝勝ちは新興国頼み",
                  f"独立データ: French 米国外先進国の大型 HiBM 保有 {F(FR['be_me~French_DevExUS_BIG_HiBM']['hold'])}（前半 {F(FR['be_me~French_DevExUS_BIG_HiBM']['hold_first_half'])}）・MSCI EAFE B/M 上位30% {F(FR['be_me~MSCI_EAFE_BM_High30_not_reqd']['hold'])}",
                  f"実在の商品（生き残りだけ・費用後）: EFV−EFA 2007〜 {F(E['EFV vs EFA']['from_2007'])}・DFIVX−EFA 2007〜 {F(E['DFIVX vs EFA']['from_2007'])}",
                  f"訓練に使った米国では 2007〜 {F(a['us_training_country_hold']['hold'])}",
                  f"JKP の153特性の良い側（米国≤2006で決定）の保有 t の中で {rank.get('be_me')}位/{PL['n_good']}（良い側の {PL['good_t_ge_1.65']*100:.0f}% が t≥1.65＝この期間の米国外は何でも勝ちやすかった）"]})
    # 2/4 ni_me
    for nm, cg in (('primary:ni_me', 'S'), ('F2a:ni_me', 'S')):
        r, ev, a, kn = common(nm)
        iss = [
            f"C3（保有 t={ev['hold']['t']}）が刃の上: 2009年だけ除くと {F(ev['hold_drop_2009_only'])}（2009年1年で {ev['hold_calendar_years']['by_year'].get('2009', ev['hold_calendar_years']['by_year'].get(2009))}%）・前半 {F(ev['hold_first_half'])}・後半 {F(ev['hold_second_half'])}・β/規模調整 α {a['alpha_after_beta_and_size']['hold']['alpha_mkt_smb']:+.2f} t{a['alpha_after_beta_and_size']['hold']['t_alpha_mkt_smb']}・現実的な回転率（0.8/年）の費用後 {F(a['cost_realistic']['unit_0.3pct'])} で 1.65 を割る",
            f"国の等分平均: 全体 {F(a['country_neutral_equal_weight']['all_ex_us_hold'])} だが 先進国だけ {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}・新興国 {F(a['country_neutral_equal_weight']['emerging_hold'])}",
            f"独立データ MSCI EAFE E/P 上位30% 保有 {F(FR['ni_me~MSCI_EAFE_EP_High30_not_reqd']['hold'])}（前半 {F(FR['ni_me~MSCI_EAFE_EP_High30_not_reqd']['hold_first_half'])}）＝線の上ちょうど",
            f"C7 は全期間 t={ev['full']['t']}（1990-2006 は国際の割安が既に論文で報告済みの期間＝独立の証拠ではない）で通るだけ。保有期間の族内 Holm p={r['own_family_holm_p']}・角度の Bonferroni p={MT[nm]['bonferroni_angle_p']}",
            f"実在の商品: EFV−EFA 2007〜 {F(E['EFV vs EFA']['from_2007'])}・IVLU−EFA 2015〜 {F(E['IVLU vs EFA']['from_2007'])}／訓練の米国では 2007〜 {F(a['us_training_country_hold']['hold'])}",
            f"153特性の良い側の中で保有 t {rank.get('ni_me')}位（中央値より下）。C5（{r['countries_full_positive'][0]}/{r['countries_full_positive'][1]}）と C7（全期間 t は始まりを動かしても 3.03〜3.43）は保つので A"]
        if nm.startswith('primary'):
            iss.insert(0, f"F2a:ni_me と同じ戦略・同じ保有期間。訓練・全期間は 1986-89 の被覆の偏りを含む（訓 {F(ev['train'])} vs 被覆の規則つき {F(C['F2a:ni_me']['reproduced']['train'])}）ので F2a に置き換わる")
        V.append({'name': nm, 'claimed_grade': cg, 'verified_grade': 'A', 'reproduced': all(r['match'].values()), 'verdict': 'downgraded to A', 'key_numbers': kn, 'issues': iss})
    # 3 F2a:be_me
    r, ev, a, kn = common('F2a:be_me')
    V.append({'name': 'F2a:be_me', 'claimed_grade': 'B', 'verified_grade': 'B', 'reproduced': all(r['match'].values()), 'verdict': 'confirmed',
              'key_numbers': kn, 'issues': [
                  f"B は上限。保有 t={ev['hold']['t']}・2009年除き {F(ev['hold_drop_2009_only'])}・β/規模調整 α {a['alpha_after_beta_and_size']['hold']['alpha_mkt_smb']:+.2f} t{a['alpha_after_beta_and_size']['hold']['t_alpha_mkt_smb']}＝保有期間の勝ちは偶然と区別できない",
                  f"C1 も近隣で割れる: 被覆率≥0.6 だと訓練 {F(a['rule_neighbors']['R0.6_1990']['train'])}→C",
                  f"先進国だけ {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}・独立の French 大型 {F(FR['be_me~French_DevExUS_BIG_HiBM']['hold'])}・EFV−EFA {F(E['EFV vs EFA']['from_2007'])}"]})
    # 5 ocf_me
    r, ev, a, kn = common('F2a:ocf_me')
    rn = a['rule_neighbors']
    V.append({'name': 'F2a:ocf_me', 'claimed_grade': 'S', 'verified_grade': 'A', 'reproduced': all(r['match'].values()), 'verdict': 'downgraded to A',
              'key_numbers': kn, 'issues': [
                  f"保有期間の勝ちは頑丈（2009年除き {F(ev['hold_drop_2009_only'])}・β/規模調整 α {a['alpha_after_beta_and_size']['hold']['alpha_mkt_smb']:+.2f} t{a['alpha_after_beta_and_size']['hold']['t_alpha_mkt_smb']}・現実的な費用後 {F(a['cost_realistic']['unit_0.3pct'])}・母集団の差 {a['covered_universe_gap_rolling36']['hold']['market_minus_covered_ann_pct']:+.2f}＝無し・独立の MSCI EAFE CE/P 上位30% {F(FR['ocf_me~MSCI_EAFE_CEP_High30_not_reqd']['hold'])}・20か国中{FR['ocf_me~MSCI_EAFE_CEP_High30_not_reqd']['countries_hold_positive'][0]}か国で正）",
                  f"だが S の柱の C1（訓練 t={ev['train']['t']}）と C7（全期間 t={ev['full']['t']}）が線のすぐ上。事前登録の主の族（1986〜）では 訓 {F(rn['primary_1986_all']['train'])}・全 t={rn['primary_1986_all']['full']['t']} で C。近隣の被覆率≥0.5 でも 訓 {F(rn['R0.5_1990']['train'])}→C（7つの窓のうち2つが C）",
                  f"S は主の族の結果を見た後の事前登録2（探索）で初めて出た。保有期間だけの多重検定は族内 Holm p={r['own_family_holm_p']}・角度 Bonferroni p={MT['F2a:ocf_me']['bonferroni_angle_p']} で残らない",
                  f"先進国だけ {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}（新興国 {F(a['country_neutral_equal_weight']['emerging_hold'])}）・訓練の米国では 2007〜 {F(a['us_training_country_hold']['hold'])}",
                  f"実在の商品は半分以下: IVLU−EFA {F(E['IVLU vs EFA']['from_2007'])}・PXF−EFA（楽天で買える）{F(E['PXF vs EFA']['from_2007'])}・FNDF−EFA {F(E['FNDF vs EFA']['from_2007'])}"]})
    # 6 div12m_me
    r, ev, a, kn = common('F2a:div12m_me')
    rn = a['rule_neighbors']
    V.append({'name': 'F2a:div12m_me', 'claimed_grade': 'B', 'verified_grade': 'B', 'reproduced': all(r['match'].values()), 'verdict': 'confirmed',
              'key_numbers': kn, 'issues': [
                  f"超過の約3分の1は『配当を払う会社の母集団』が市場に勝った分: 市場−被覆された母集団 {a['covered_universe_gap_rolling36']['hold']['market_minus_covered_ann_pct']:+.2f}%/年 t{a['covered_universe_gap_rolling36']['hold']['t']}・良い側−三分位平均 {F(a['terciles']['good_minus_avg_of_3_terciles']['hold'])}",
                  f"格付けが窓で揺れる: 被覆だけ（1986-12〜）なら全期間 t={rn['R_only_no_1990_start']['full']['t']}→S、1992〜なら訓練 t={rn['start1992_R0.4']['train']['t']}→C。B は真ん中",
                  f"先進国だけ {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}・日本抜き {F(a['country_neutral_equal_weight']['developed_ex_us_ex_japan_hold'])}・新興国 {F(a['country_neutral_equal_weight']['emerging_hold'])}",
                  f"独立の MSCI EAFE 配当 上位30% {F(FR['div12m_me~MSCI_EAFE_Yld_High30_not_reqd']['hold'])} は同じ向き。だが実在の商品は IDV−EFA {F(E['IDV vs EFA']['from_2007'])}・DWX−EFA {F(E['DWX vs EFA']['from_2007'])}・VYMI−VEU {F(E['VYMI vs VEU']['from_2007'])}・FID−EFA（楽天で買える）{F(E['FID vs EFA']['from_2007'])}",
                  f"訓練の米国では 2007〜 {F(a['us_training_country_hold']['hold'])}"]})
    # 7 ret_12_1
    r, ev, a, kn = common('F2a:ret_12_1')
    V.append({'name': 'F2a:ret_12_1', 'claimed_grade': 'S', 'verified_grade': 'A', 'reproduced': all(r['match'].values()), 'verdict': 'downgraded to A',
              'key_numbers': kn, 'issues': [
                  f"回転率の仮定（年1.5）が低い。自前のモンテカルロでは上位1/3・時価加重・毎月で年{out['turnover_mc']['ret_12_1']['annual_one_way']}。その費用（単価0.3%/0.4%）で保有 {F(a['cost_realistic']['unit_0.3pct'])}／{F(a['cost_realistic']['unit_0.4pct'])}＝費用後は C3 の線を割る",
                  f"独立データの大型だけ（French 米国外先進国 BIG HiPRIOR）保有 {F(FR['ret_12_1~French_DevExUS_BIG_HiPRIOR']['hold'])}（小型 {F(FR['ret_12_1~French_DevExUS_SMALL_HiPRIOR']['hold'])}）",
                  f"実在の商品: PIZ−EFA 2008〜 {F(E['PIZ vs EFA']['from_2007'])}・IMTM−EFA 2015〜 {F(E['IMTM vs EFA']['from_2007'])}（どちらも楽天に無い）",
                  f"近隣の窓: ret_9_1 {F(a['characteristic_neighbors']['ret_9_1']['hold'])}・ret_6_1 {F(a['characteristic_neighbors']['ret_6_1']['hold'])}。前半 {F(ev['hold_first_half'])}。2009年 {ev['hold_calendar_years']['by_year'].get('2009', ev['hold_calendar_years']['by_year'].get(2009))}%（勢いの崩れ）",
                  f"訓練の米国では 2007〜 {F(a['us_training_country_hold']['hold'])}",
                  f"残るもの: 国の等分平均 先進国 {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}・{r['countries_hold_positive'][0]}/{r['countries_hold_positive'][1]}か国で保有期間も正・β/規模調整 α {a['alpha_after_beta_and_size']['hold']['alpha_mkt_smb']:+.2f} t{a['alpha_after_beta_and_size']['hold']['t_alpha_mkt_smb']}（総額では頑丈、費用後の統計の強さが足りない→A）"]})
    # 8 resff3_12_1
    r, ev, a, kn = common('F2a:resff3_12_1')
    kn += '。20年窓は研究側 16/16・自前 15/15（系列が 1990-08 始まりで、1990-07 起点の窓を自前は欠けとして数えない）'
    V.append({'name': 'F2a:resff3_12_1', 'claimed_grade': 'S', 'verified_grade': 'S', 'reproduced': all(r['match'].values()), 'verdict': 'confirmed',
              'key_numbers': kn, 'issues': [
                  f"反証できなかった（紙の上）: 前半 {F(ev['hold_first_half'])}・後半 {F(ev['hold_second_half'])}・2009年除き {F(ev['hold_drop_2009_only'])}・最良年({ev['hold_drop_best_year']['year']})除き {F(ev['hold_drop_best_year']['stats'])}・暦年 {ev['hold_calendar_years']['wins']}/{ev['hold_calendar_years']['years']} 勝ち・10年窓 {ev['roll10_in_hold']['wins']}/{ev['roll10_in_hold']['windows']}・相対の最大下落 {ev['relative_max_drawdown'][0]}%・vw_cap {F(a['weighting_neighbors_vs_pure_vw_market']['vw_cap']['hold'])}・先進国の等分 {F(a['country_neutral_equal_weight']['developed_ex_us_hold'])}・日本抜き {F(a['country_neutral_equal_weight']['developed_ex_us_ex_japan_hold'])}。多重検定: 角度 Bonferroni p={MT['F2a:resff3_12_1']['bonferroni_angle_p']}・mw 全体（{MT['program_graded_all_mw_json']}本）でも p={MT['F2a:resff3_12_1']['bonferroni_program_p']}（すれすれ）",
                  f"ただし超過 {ev['hold']['ex']:+.2f} のうち約 {-a['covered_universe_gap_rolling36']['hold']['market_minus_covered_ann_pct']:.2f}%/年（t{-a['covered_universe_gap_rolling36']['hold']['t']:.1f}）は『36か月の履歴がある銘柄の母集団』が市場に勝った分（中の三分位も {F(a['terciles']['2.0']['hold'])}・若い会社の三分位は市場に {out['universe_diagnostics']['age_1.0']['hold']['ex']:+.1f}%/年）。特性そのものの分（良い側−三分位平均）は {F(a['terciles']['good_minus_avg_of_3_terciles']['hold'])}",
                  f"回転率の仮定（年1.5）は低い（モンテカルロで年{out['turnover_mc']['resff3_12_1']['annual_one_way']}）。現実的な費用後 {F(a['cost_realistic']['unit_0.3pct'])}／単価0.4%で {F(a['cost_realistic']['unit_0.4pct'])}＝残るが半分",
                  f"近隣の窓 resff3_6_1 は {F(a['characteristic_neighbors']['resff3_6_1']['hold'])} と弱い。資格のある国は{r['countries_hold_positive'][1]}か国だけで保有期間の正は{r['countries_hold_positive'][0]}。訓練に使った米国では 2007〜 {F(a['us_training_country_hold']['hold'])}",
                  "実在の商品が一つも無い（米国外・残差の勢いの ETF/投信なし）。数千銘柄・40か国の上位1/3を毎月入れ替える必要があり、個人（日本の課税口座なら売却益に20.315%が毎年かかる）には実行できない＝紙の上の S"]})
    # 追加: 研究側の見出し
    X = out['extra_headline_checks']
    vm = X['F2b_combos:val_mom']
    V.append({'name': 'extra:F2b_combos:val_mom（依頼の一覧外・研究側の見出し）', 'claimed_grade': 'S', 'verified_grade': 'S', 'reproduced': True, 'verdict': 'confirmed',
              'key_numbers': f"再現 全{F(vm['reproduced']['full'])}・訓{F(vm['reproduced']['train'])}・保{F(vm['reproduced']['hold'])}・前半{F(vm['reproduced']['hold_first_half'])}・後半{F(vm['reproduced']['hold_second_half'])}・現実的な費用後{F(vm['cost_realistic']['unit_0.4pct'])}・β/規模調整 α {vm['alpha_after_beta_and_size_hold']['alpha_mkt_smb']:+.2f} t{vm['alpha_after_beta_and_size_hold']['t_alpha_mkt_smb']}・国{vm['countries_hold_positive'][0]}/{vm['countries_hold_positive'][1]}",
              'issues': [f"紙の上は反証できない（先進国の等分 {F(vm['country_neutral_equal_weight']['developed_ex_us_hold'])}・日本抜き {F(vm['country_neutral_equal_weight']['developed_ex_us_ex_japan_hold'])}）",
                         f"独立の French 大型 HiBM+HiPRIOR 保有 {F(vm['french_big_HiBM_plus_HiPRIOR_dev_ex_us']['hold'])}・実在 ETF の組み合わせ PXF+PIZ {F(vm['etf_combos_survivors']['PXF+PIZ vs EFA'])}・IVLU+IMTM {F(vm['etf_combos_survivors']['IVLU+IMTM vs EFA'])}・EFV+IMTM {F(vm['etf_combos_survivors']['EFV+IMTM vs EFA'])}＝実行できる形では半分〜3分の1で有意でない",
                         f"訓練の米国では 2007〜 {F(vm['us_training_country']['hold'])}"]})
    jb = X['F2c_japan:be_me']
    V.append({'name': 'extra:F2c_japan:be_me（依頼の一覧外）', 'claimed_grade': 'S', 'verified_grade': 'A', 'reproduced': True, 'verdict': 'downgraded to A',
              'key_numbers': f"再現 全{F(jb['reproduced']['full'])}・訓{F(jb['reproduced']['train'])}・保{F(jb['reproduced']['hold'])}・MSCI 日本 B/M 上位30% 保有 {F(jb['msci_japan_bm_high30']['hold'])}",
              'issues': [f"前半 {F(jb['reproduced']['hold_first_half'])}・後半 {F(jb['reproduced']['hold_second_half'])}・最良年({jb['reproduced']['hold_drop_best_year']['year']})除き {F(jb['reproduced']['hold_drop_best_year']['stats'])}・10年窓 {jb['reproduced']['roll10_in_hold']['wins']}/{jb['reproduced']['roll10_in_hold']['windows']}・相対の最大下落 {jb['reproduced']['relative_max_drawdown'][0]}%",
                         "日本を判定の対象にしたのは主の族（日本の国別の数字を含む）を見た後（研究者が自認する選択の偏り）。族内 Holm では残らず、C7 は全期間 t だけ"]})
    summ = ("研究側の数字（全期間・訓練・保有の超過と t、CAGR差、費用後、20年窓、積立、国の数）は自前のコードで8本とも完全に再現した。良い側の向き・被覆の規則（1990年開始を外しても同じ）・相手（JKP の純粋な時価加重は VGTSX より年0.4%高く、弱い相手ではない）に不正は無い。\n"
            "ただし S/A の多くは強さが足りない。be_me の A は1986-89年の被覆の偏りに頼っており B に下がる。ni_me は2009年1年を除くと t1.26、先進国だけでも t1.59 で S の条件（C3）が刃の上＝A。\n"
            "ocf_me は保有期間は頑丈（独立の MSCI でも t1.85）だが、訓練 t2.15・全期間 t3.20 が線のすぐ上で、事前登録どおりの主の族では C、S は後から登録した探索の族でだけ出た＝A。勢い ret_12_1 は回転率を年1.5と置いていたが自前の試算では年2.2で、現実的な費用後は t1.3〜1.5＝A。\n"
            f"残差の勢い resff3_12_1 だけは紙の上で反証できなかった（保有 +1.84%/年 t4.32、前後半・年ごと・国・重み付けで頑丈、mw 全体の多重検定でもすれすれ残る）が、うち約0.4%/年は『履歴のある銘柄の母集団』の差で、現実的な費用後は +0.9〜1.1%/年、商品は存在しない。\n"
            f"同じ期間・同じ規則で JKP の153特性の良い側を並べると、{PL['good_t_ge_1.65']*100:.0f}% が t≥1.65、中の三分位でさえ {PL['mid_positive']*100:.0f}% が市場に勝っていた＝2007年以降の米国外は『何を選んでも』勝ちやすい時代で、be_me・ni_me はその中で平均以下。\n"
            "実在の商品（生き残りだけ・費用後）は EFV −0.16、PXF +1.23（t1.07・楽天で買える）、FID −1.80（楽天で買える）、PIZ +1.54（t0.98）で、紙の上の半分以下。訓練に使った米国では6本とも2007年以降は勝てなかった（勢いは −0.02 でほぼ0）。")
    return V, summ


if __name__ == '__main__':
    main()
