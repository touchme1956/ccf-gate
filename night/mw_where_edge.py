#!/usr/bin/env python3
"""night/mw_where_edge.py — 角度 where_edge（監査・記述のみ・門の判定には不使用）

問い: 現金ベースの営業収益性 cop_at（Ball et al. 2016）の『上乗せ』は、どこにあるのか。
  - JKP（CRSP/Compustat・上限なし時価加重の上位1/3）は、業種で調整しても 2007年以降に上乗せが残ると言う
  - SEC の株ごとの作り直し（night/mw_sec_replication.py・上位500社・2010-07〜2026-08）は、上乗せの約3/4が
    技術（FF12 BusEq）の比重で、技術を除くと 0 前後だと言う
  この食い違いを『方法（回帰で業種を引く／組み方で業種をそろえる）× データ（JKP／SEC）』の 2×2 で監査する。
  規則探しではない。仮説 H1〜H3 は測る前に固定（out/mw_where_edge_prereg.json）。格付け（S/A）はしない。

段
  check : 測る前の点検（件数・範囲だけ。戦略と市場の比較はしない）
  run   : 全部を計算して out/mw_where_edge.json
"""
import sys, os, io, json, math, time, zipfile, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M
import mw_sec_replication as SR
import numpy as np

PRE_NAME = 'mw_where_edge_prereg.json'
OUT_NAME = 'mw_where_edge.json'
JKP_START, JKP_END = 196307, 202512
SEC_START, SEC_END = SR.START, SR.END            # 201007, 202608
COMMON = (SEC_START, JKP_END)                    # 両方のデータがそろう窓 2010-07〜2025-12
HOLD = (M.HOLD_START, JKP_END)
TRAIN = (JKP_START, M.TRAIN_END)
TECH12 = 'BusEq'
TECH49 = ('Hardw', 'Softw', 'Chips', 'LabEq')
DECADES = [('1963-07〜1969', 196307, 196912), ('1970年代', 197001, 197912), ('1980年代', 198001, 198912),
           ('1990年代', 199001, 199912), ('2000〜2006', 200001, 200612), ('2007〜2016', 200701, 201612), ('2017〜2025', 201701, 202512)]
DEV = ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
       'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe']
COST = 0.001      # 片道100%あたり0.10%（大型株・mw_prereg の既定）
FAMILY = ['JKP_reg12_hold', 'JKP_reg49_hold', 'SEC_reg12', 'SEC_reg49', 'SEC_CN12', 'SEC_CN49', 'H2_within_BusEq', 'H3_CN49_exBusEq']


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── French ─────────────────────────
FF = M.ff_factors()
MKT, MKTRF, RF = FF['mkt'], FF['mktrf'], FF['rf']


def fr_monthly(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            return v
    raise KeyError(f'{name}: {want}')


def fr_ind(name):
    """French 業種ファイル → (列, {列: {ym: 総リターン小数}}, 市場の業種の重み {ym: {列: w}}〔前月の社数×平均規模〕)"""
    ret = fr_monthly(name, 'Average Value Weighted Returns')
    nf = fr_monthly(name, 'Number of Firms')
    sz = fr_monthly(name, 'Average Firm Size')
    cols = ret['cols']
    r = {c: {d: row[i] / 100 for d, row in ret['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
    ks = sorted(nf['data'])
    W = {}
    for p, k in zip(ks, ks[1:]):
        w = {}
        for i, c in enumerate(cols):
            n, s = nf['data'][p][i], (sz['data'].get(p) or [None] * len(cols))[i]
            if n is None or s is None or n <= 0 or s <= 0:
                continue
            w[c] = n * s
        tot = sum(w.values())
        if tot > 0:
            W[k] = {c: x / tot for c, x in w.items()}
    return cols, r, W


def me10():
    v = fr_monthly('Portfolios_Formed_on_ME', 'Value Weight Returns')
    i = v['cols'].index('Hi 10')
    return {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None}


def sic_map(n):
    """French の SIC→業種の対応（Siccodes12 / Siccodes49）。範囲に無い SIC は 'Other'（French の作法）"""
    if n == 12:
        return SR.ff12_fn()
    b = M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes49.zip', name='fr_Siccodes49_map.zip', max_age_days=3650)
    z = zipfile.ZipFile(io.BytesIO(b))
    rng, cur = [], None
    for l in z.read(z.namelist()[0]).decode('latin-1').split('\n'):
        p = l.split()
        if not p:
            continue
        if p[0].isdigit() and len(p) >= 2:
            cur = p[1]
        elif '-' in p[0] and cur:
            a, b_ = p[0].split('-')
            rng.append((int(a), int(b_), cur))

    def f(sic):
        try:
            x = int(sic)
        except (TypeError, ValueError):
            return None
        for a, b_, k in rng:
            if a <= x <= b_:
                return k
        return 'Other'
    return f


# ───────────────────────── 回帰（Newey-West） ─────────────────────────
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
    se = np.sqrt(np.maximum(np.diag(V), 0))
    yc = Y - Y.mean()
    r2 = 1 - (e @ e) / (yc @ yc) if yc @ yc > 0 else None
    return b, se, r2


def vif(X, j):
    """列 j（切片は 0 列）の分散拡大係数 = 1/(1−R²)。ほかの説明変数で j をどれだけ言い当てられるか（共線性の点検）"""
    others = [i for i in range(X.shape[1]) if i != j]
    b = np.linalg.lstsq(X[:, others], X[:, j], rcond=None)[0]
    e = X[:, j] - X[:, others] @ b
    yc = X[:, j] - X[:, j].mean()
    r2 = 1 - (e @ e) / (yc @ yc) if yc @ yc > 0 else 0.0
    return round(float(1 / max(1 - r2, 1e-9)), 1)


def reg(y, xs, a, z, tech=(), min_n=36):
    """y: {ym: 月次の差}、xs: [(名前, {ym: 値})]。全部そろう月だけ（欠測は0にしない）。
    平均の分解: 生の差の平均 = α + Σ b_j × mean(x_j)（最小二乗・切片ありで厳密に成り立つ）。
    tech: 技術の説明変数の名前（寄与の合計と VIF を出す）"""
    ks = sorted(k for k in y if a <= k <= z and all(k in x for _, x in xs))
    if len(ks) < max(min_n, len(xs) + 12):
        return None
    Y = np.array([y[k] for k in ks])
    X = np.column_stack([np.ones(len(ks))] + [np.array([x[k] for k in ks]) for _, x in xs])
    b, se, r2 = ols_nw(Y, X)
    t = float(b[0] / se[0]) if se[0] > 0 else None
    mu = X.mean(axis=0)
    contrib = {nm: float(bb * m * 1200) for (nm, _), bb, m in zip(xs, b[1:], mu[1:])}
    o = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'raw_ann': round(float(Y.mean() * 1200), 2),
         'alpha_ann': round(float(b[0] * 1200), 2), 't': round(t, 2) if t is not None else None,
         'p': round(M.p_two(t), 4) if t is not None else None, 'r2': round(float(r2), 3) if r2 is not None else None,
         'coef': {nm: [round(float(bb), 3), round(float(bb / s), 2) if s > 0 else None] for (nm, _), bb, s in zip(xs, b[1:], se[1:])},
         'contrib_ann': {nm: round(v, 2) for nm, v in contrib.items()}}
    ind = {nm: v for nm, v in contrib.items() if nm not in ('mktrf', 'mkt', 'bench_rf', 'me10_rel')}
    o['market_part_ann'] = round(sum(v for nm, v in contrib.items() if nm in ('mktrf', 'mkt', 'bench_rf')), 2)
    o['industry_part_ann'] = round(sum(ind.values()), 2)
    if 'me10_rel' in contrib:
        o['me10_part_ann'] = round(contrib['me10_rel'], 2)
    if tech:
        o['tech_part_ann'] = round(sum(contrib.get(nm, 0.0) for nm in tech), 2)
        o['tech_share_of_raw'] = round(o['tech_part_ann'] / o['raw_ann'], 3) if o['raw_ann'] > 0 else None
        o['tech_coef_sum'] = round(sum(float(bb) for (nm, _), bb in zip(xs, b[1:]) if nm in tech), 3)
        names = [nm for nm, _ in xs]
        o['tech_vif'] = {nm: vif(X, names.index(nm) + 1) for nm in tech if nm in names}
    o['identity_check'] = round(o['alpha_ann'] + sum(contrib.values()) - o['raw_ann'], 6)
    return o


def mean_t(d, a=None, z=None):
    x = [v for k, v in sorted(d.items()) if (a is None or k >= a) and (z is None or k <= z)]
    if len(x) < 24:
        return None
    t = M.nw_t(x)
    return {'n': len(x), 'from': min(k for k in d if (a is None or k >= a)), 'mean_ann': round(S.mean(x) * 1200, 2),
            't': round(t, 2) if t is not None else None, 'p': round(M.p_two(t), 4) if t is not None else None}


def months_between(a, b):
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def sn_rolling(y, xs, W):
    """直前 W か月（連続）で係数を推定し、当月の業種・市場の成分を引く（切片は引かない）→ {ym}。
    当月の係数は当月より前のデータだけ＝後知恵なし（reality_gap の SN と同じ作り方）"""
    ks = sorted(k for k in y if all(k in x for _, x in xs))
    out = {}
    for i in range(W, len(ks)):
        win = ks[i - W:i]
        if months_between(win[0], ks[i]) != W:
            continue
        Y = np.array([y[k] for k in win])
        X = np.column_stack([np.ones(W)] + [np.array([x[k] for k in win]) for _, x in xs])
        b = np.linalg.lstsq(X, Y, rcond=None)[0]
        k = ks[i]
        out[k] = y[k] - sum(float(bb) * x[k] for bb, (_, x) in zip(b[1:], xs))
    return out


def diff(a, b):
    return {k: a[k] - b[k] for k in a if k in b}


# ───────────────────────── SEC（株ごと） ─────────────────────────
def cn_weights(u, members, score, indf):
    """組み方で業種をそろえる（construction-neutral）: 業種ごとに cop_at の上位 ceil(n/3)（得点のある社の中）を時価加重、
    業種の重みは母集団（members 全社・得点の有無を問わない）の業種の時価の比。得点のある社が1社もいない業種は外して按分し直す（0で埋めない）"""
    indw, grp = {}, {}
    for c in members:
        g = indf(c)
        if g is None:
            continue
        indw[g] = indw.get(g, 0.0) + u[c]['fcap']
        if c in score:
            grp.setdefault(g, []).append(c)
    wsum = sum(indw[g] for g in grp)
    tot_all = sum(indw.values())
    w = {}
    for g, cs in grp.items():
        cs = sorted(cs, key=lambda c: (-score[c], -u[c]['fcap']))
        pick = cs[:max(1, math.ceil(len(cs) / 3))]
        tot = sum(u[c]['fcap'] for c in pick)
        for c in pick:
            w[u[c]['ticker']] = indw[g] / wsum * u[c]['fcap'] / tot
    return w, (round(wsum / tot_all, 4) if tot_all else None)


def sec_build(verbose=False):
    panel = SR.build_panel()
    uni, price, diag, sic, tick = SR.build_universe(panel, fetch=False, verbose=verbose)
    rets = {x: v[0] for x, v in price.items() if v}
    f49 = sic_map(49)
    C, info = {}, {'n': {}, 'cn_coverage': {}, 'ind12': {}, 'ind49': {}}
    for t in SR.YEARS:
        u = uni[t]
        R, sc = SR.scores(u)
        for c in R:
            R[c]['ff49'] = f49(R[c]['sic'])
            info['ind12'][(t, u[c]['ticker'])] = R[c]['ff12']
            info['ind49'][(t, u[c]['ticker'])] = R[c]['ff49']
        cop = sc['cop_at']

        def put(nm, w):
            if w:
                C.setdefault(nm, {})[t] = w
        RB = [c for c in R if R[c]['ff12'] == TECH12]
        RX = [c for c in R if R[c]['ff12'] != TECH12]
        copB = {c: cop[c] for c in RB if c in cop}
        copX = {c: cop[c] for c in RX if c in cop}
        put('T3VW', SR._w(u, SR.top_by(cop, u, frac=1 / 3), True))
        put('U_exfin', SR._w(u, list(R), True))
        put('U_all', SR._w(u, list(u), True))
        w12, cv12 = cn_weights(u, list(R), cop, lambda c: R[c]['ff12'])
        w49, cv49 = cn_weights(u, list(R), cop, lambda c: R[c]['ff49'])
        put('CN12', w12); put('CN49', w49)
        put('BusEq_T3VW', SR._w(u, SR.top_by(copB, u, frac=1 / 3), True))
        put('BusEq_all', SR._w(u, RB, True))
        put('exB_T3VW', SR._w(u, SR.top_by(copX, u, frac=1 / 3), True))
        put('U_exfin_exBusEq', SR._w(u, RX, True))
        wx49, cvx49 = cn_weights(u, RX, cop, lambda c: R[c]['ff49'])
        wx12, cvx12 = cn_weights(u, RX, cop, lambda c: R[c]['ff12'])
        put('CN49_exB', wx49); put('CN12_exB', wx12)
        # 同じ母集団の業種（FF12・金融を除く）＝回帰の副（自前の業種）用
        for g in sorted({R[c]['ff12'] for c in R}):
            put('IND12_' + g, SR._w(u, [c for c in R if R[c]['ff12'] == g], True))
        info['n'][t] = {'universe': len(u), 'exfin': len(R), 'exfin_with_cop': len(cop), 'BusEq': len(RB), 'BusEq_with_cop': len(copB),
                        'exBusEq': len(RX), 'exBusEq_with_cop': len(copX),
                        'ff49_inds_exfin': len({R[c]['ff49'] for c in R}), 'ff49_inds_exBusEq': len({R[c]['ff49'] for c in RX}),
                        'picks_CN12': len(w12), 'picks_CN49': len(w49), 'picks_CN49_exB': len(wx49),
                        'picks_T3VW': len(C['T3VW'].get(t, {})), 'picks_BusEq_T3VW': len(C['BusEq_T3VW'].get(t, {}))}
        info['cn_coverage'][t] = {'CN12': cv12, 'CN49': cv49, 'CN49_exB': cvx49, 'CN12_exB': cvx12}
    return uni, rets, C, info


def ind_fn(info, key):
    mp = info[key]

    def f(m, k):
        t = m // 100 if m % 100 >= 7 else m // 100 - 1
        return mp.get((t, k), '?')
    return f


# ───────────────────────── JKP 地域（国ごと） ─────────────────────────
def jkp_gics(c):
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{c}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = M.get(url, name=f'jkp_industry_{c}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    import csv
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        out.setdefault(x['gics'], {})[M._ym(x['date'])] = float(x['ret'])
    return out


def jkp_pf_n(c, key='cop_at', w='vw'):
    d = {}
    for x in M.jkp_rows(c, key, 'portfolios', w):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        d.setdefault(x['pf'], {})[M._ym(x['date'])] = (float(x['ret']), float(x['n']) if x.get('n') not in (None, '', 'NA') else None)
    return d


# ───────────────────────── 測る前の点検 ─────────────────────────
def check():
    uni, rets, C, info = sec_build(verbose=False)
    for t in SR.YEARS:
        print(t, info['n'][t], info['cn_coverage'][t])
    print('months per series', {k: (min(v), max(v), len(v)) for k, v in list(C.items())[:3]})
    for nm, key in (('French 12', '12_Industry_Portfolios'), ('French 49', '49_Industry_Portfolios')):
        cols, r, W = fr_ind(key)
        print(nm, len(cols), min(r[cols[0]]), max(r[cols[0]]))
    print('ME10', min(me10()), max(me10()), 'French mkt', min(MKT), max(MKT))
    for c in DEV:
        try:
            g = jkp_gics(c)
            p = jkp_pf_n(c)
            mk = M.jkp_mkt(c, 'vw')
            p3 = p.get('3.0', {})
            nh = [n for k, (r, n) in p3.items() if k >= M.HOLD_START and n is not None]
            print(c, 'gics', len(g), min(min(v) for v in g.values()), 'pf3', min(p3) if p3 else None, len(p3), 'median n hold', S.median(nh) if nh else None, 'mkt', min(mk))
        except Exception as e:  # noqa
            print(c, 'ERR', str(e)[:100])
    ex = os.path.join(M.BASE, 'out', 'mw_ex27.json')
    print('ex27 json', os.path.exists(ex))


# ───────────────────────── 本体 ─────────────────────────
def run():
    t0 = time.time()
    pre = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
    c12, i12, W12 = fr_ind('12_Industry_Portfolios')
    c49, i49, W49 = fr_ind('49_Industry_Portfolios')
    rel12 = [(c, {k: v - MKT[k] for k, v in i12[c].items() if k in MKT}) for c in c12]
    rel49 = [(c, {k: v - MKT[k] for k, v in i49[c].items() if k in MKT}) for c in c49]
    X12 = [('mktrf', MKTRF)] + rel12
    X49 = [('mktrf', MKTRF)] + rel49
    ME10 = me10()
    me10_rel = {k: ME10[k] - MKT[k] for k in ME10 if k in MKT}
    res = {'angle': 'where_edge', 'tool': 'night/mw_where_edge.py', 'prereg': PRE_NAME, 'prereg_commit': sha_of(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'label': '記述の監査（格付け S/A はしない＝事前登録どおり）'}
    tested = []
    fam = {}

    # ── JKP（データ1）
    side, pp = M.jkp_good_side('usa', 'cop_at', 'vw', upto=M.TRAIN_END)
    P = {k: v for k, v in pp[side].items() if JKP_START <= k <= JKP_END}
    PA = diff(P, MKTRF)
    P_tot = {k: v + RF[k] for k, v in P.items() if k in RF}
    jk = {'good_side': side, 'series': 'JKP usa cop_at 上位1/3・上限なし時価加重（vw）・超過', 'benchmark': 'French Mkt-RF（超過どうし）'}
    jk['raw'] = {w: M.excess_stats(P, MKTRF, a, z) for w, (a, z) in
                 {'full': (JKP_START, JKP_END), 'train': TRAIN, 'hold': HOLD, 'recent': (M.RECENT_START, JKP_END), 'common_2010_07_2025_12': COMMON}.items()}
    jk['roll20_total'] = M.rolling(P_tot, MKT, 20)
    jk['dca20_total'] = M.dca(P_tot, MKT, 20)
    wins = {'full': (JKP_START, JKP_END), 'train': TRAIN, 'hold': HOLD, 'recent': (M.RECENT_START, JKP_END), 'common_2010_07_2025_12': COMMON}
    jk['reg12'] = {w: reg(PA, X12, a, z, tech=(TECH12,)) for w, (a, z) in wins.items()}
    jk['reg49'] = {w: reg(PA, X49, a, z, tech=TECH49) for w, (a, z) in wins.items()}
    jk['reg12_plus_me10'] = {w: reg(PA, X12 + [('me10_rel', me10_rel)], a, z, tech=(TECH12,)) for w, (a, z) in wins.items() if w in ('train', 'hold', 'common_2010_07_2025_12')}
    fam['JKP_reg12_hold'] = jk['reg12']['hold']
    fam['JKP_reg49_hold'] = jk['reg49']['hold']
    # JKP × 組み方で中立の代理（株ごとのデータが無いので、直前の窓の係数で業種・市場を引く SN）
    SN60 = sn_rolling(PA, X12, 60)
    SN120 = sn_rolling(PA, X12, 120)
    jk['cn_proxy_SN'] = {'note': 'JKP には株ごとのデータが無く組み方で中立にできない。直前60/120か月の係数で業種（FF12）と市場の成分を引いた差（後知恵なし）を代理にする。家族（Holm）には入れない',
                         'SN60': {w: mean_t(SN60, a, z) for w, (a, z) in wins.items()},
                         'SN120': {w: mean_t(SN120, a, z) for w, (a, z) in wins.items()}}
    # 年代ごとの分解（回帰が言う業種の重み × 業種の超過）
    dec = {}
    for lab, a, z in DECADES + [('訓練 1963-07〜2006', *TRAIN), ('保有 2007〜2025', *HOLD)]:
        r = reg(PA, X12, a, z, tech=(TECH12,))
        r49 = reg(PA, X49, a, z, tech=TECH49)
        mw = [W12[k].get(TECH12, 0) for k in W12 if a <= k <= z]
        dec[lab] = {'raw_ann': r['raw_ann'], 'alpha_ann': r['alpha_ann'], 't': r['t'], 'market_part_ann': r['market_part_ann'],
                    'industry_part_ann': r['industry_part_ann'], 'BusEq_coef（市場に対する技術の上乗せの重み）': r['coef'][TECH12][0],
                    'BusEq_rel_mean_ann（技術−市場）': round(S.mean(v for k, v in dict(rel12)[TECH12].items() if a <= k <= z) * 1200, 2),
                    'tech_part_ann_FF12': r['tech_part_ann'], 'tech_share_FF12': r['tech_share_of_raw'], 'tech_vif_FF12': r['tech_vif'],
                    'tech_part_ann_FF49': r49['tech_part_ann'] if r49 else None, 'alpha_ann_FF49': r49['alpha_ann'] if r49 else None,
                    'market_BusEq_weight_avg': round(S.mean(mw), 3) if mw else None, 'n': r['n']}
    jk['decade_decomposition'] = dec
    tr, ho = dec['訓練 1963-07〜2006'], dec['保有 2007〜2025']
    jmp = None
    if tr['tech_share_FF12'] is not None and ho['tech_share_FF12'] is not None:
        jmp = bool(ho['tech_share_FF12'] >= 2 * max(tr['tech_share_FF12'], 0.0) and ho['tech_share_FF12'] >= 1 / 3)
    jk['tech_share_jumped_after_2007'] = {'rule': '保有の技術の寄与の比 ≥ 2×訓練の比 かつ ≥ 1/3（FF12）', 'train': tr['tech_share_FF12'], 'hold': ho['tech_share_FF12'], 'jumped': jmp}
    res['jkp'] = jk
    tested += [{'name': 'JKP_reg12_hold', 'role': 'family（Holm）'}, {'name': 'JKP_reg49_hold', 'role': 'family（Holm）'},
               {'name': 'JKP_raw_P3_vs_Mkt', 'role': 'report'}, {'name': 'JKP_reg12/49 他の窓', 'role': 'report'},
               {'name': 'JKP_reg12_plus_me10', 'role': 'report（感度）'}, {'name': 'JKP_SN60/SN120', 'role': 'report（JKP×組み方中立の代理）'},
               {'name': 'JKP_decade_decomposition', 'role': 'report（記述）'}]

    # ── SEC（データ2）
    uni, rets, C, info = sec_build()
    ser, turn, drops = {}, {}, {}
    for nm, coh in C.items():
        ser[nm], turn[nm], drops[nm] = SR.simulate(coh, rets)
    spy = SR.yahoo_series('SPY')[0]
    B = ser['U_exfin']
    rfw = {k: RF[k] for k in RF}

    def block(s, b, nm):
        net = M.apply_cost(s, turn[nm] or 0.0, COST)
        d = {'full': M.excess_stats(s, b, SEC_START, SEC_END), 'common_2010_07_2025_12': M.excess_stats(s, b, *COMMON),
             'recent': M.excess_stats(s, b, M.RECENT_START, SEC_END),
             'first_half_2010_2018': M.excess_stats(s, b, SEC_START, 201806), 'second_half_2018_2026': M.excess_stats(s, b, 201807, SEC_END),
             'net_cost_full': M.excess_stats(net, b, SEC_START, SEC_END), 'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20),
             'roll10': M.rolling(s, b, 10), 'dca10': M.dca(s, b, 10),
             'turnover_oneway_ann': round(turn[nm], 3) if turn[nm] is not None else None, 'dropped_stock_months': drops[nm]}
        return d
    sec = {'series': 'SEC XBRL 上位500社（浮動株時価）・毎年7月組み直し・Yahoo 配当込み（mw_sec_replication と同じ母集団・同じ価格）',
           'window': [SEC_START, SEC_END], 'n_by_year': info['n'], 'cn_coverage_by_year': info['cn_coverage']}
    port = {}
    for nm, bn in (('T3VW', 'U_exfin'), ('CN12', 'U_exfin'), ('CN49', 'U_exfin'), ('BusEq_T3VW', 'BusEq_all'),
                   ('exB_T3VW', 'U_exfin_exBusEq'), ('CN49_exB', 'U_exfin_exBusEq'), ('CN12_exB', 'U_exfin_exBusEq')):
        port[nm] = {'benchmark': bn, 'vs': {bn: block(ser[nm], ser[bn], nm)}}
        for extra in ('U_all', 'SPY'):
            port[nm]['vs'][extra] = {'full': M.excess_stats(ser[nm], ser[extra] if extra == 'U_all' else spy, SEC_START, SEC_END)}
    sec['portfolios'] = port
    # 回帰（方法1）: 主は French の業種（JKP と同じ説明変数）
    yT = diff(ser['T3VW'], B)
    sec['reg12'] = {w: reg(yT, X12, a, z, tech=(TECH12,)) for w, (a, z) in {'full': (SEC_START, SEC_END), 'common_2010_07_2025_12': COMMON}.items()}
    sec['reg49'] = {w: reg(yT, X49, a, z, tech=TECH49) for w, (a, z) in {'full': (SEC_START, SEC_END), 'common_2010_07_2025_12': COMMON}.items()}
    fam['SEC_reg12'] = sec['reg12']['full']
    fam['SEC_reg49'] = sec['reg49']['full']
    # 感度（報告のみ）
    yTa = diff(ser['T3VW'], ser['U_all'])
    own = [('bench_rf', {k: B[k] - RF[k] for k in B if k in RF})] + \
          [(g[6:], diff(ser[g], B)) for g in sorted(ser) if g.startswith('IND12_') and g != 'IND12_Other']
    sec['sensitivity'] = {
        'reg12_vs_U_all': reg(yTa, X12, SEC_START, SEC_END, tech=(TECH12,)),
        'reg49_vs_U_all': reg(yTa, X49, SEC_START, SEC_END, tech=TECH49),
        'reg12_plus_me10': reg(yT, X12 + [('me10_rel', me10_rel)], SEC_START, SEC_END, tech=(TECH12,)),
        'reg_own_universe_ind12（自前の業種・Other を落とす）': reg(yT, own, SEC_START, SEC_END, tech=(TECH12,)),
        'CN12_own_reg12（組み方中立の組の回帰α＝整合の点検）': reg(diff(ser['CN12'], B), X12, SEC_START, SEC_END, tech=(TECH12,)),
        'CN49_own_reg49': reg(diff(ser['CN49'], B), X49, SEC_START, SEC_END, tech=TECH49),
        'H3_CN49_exB_reg49': reg(diff(ser['CN49_exB'], ser['U_exfin_exBusEq']), X49, SEC_START, SEC_END, tech=TECH49),
    }
    # 実際の持ち高での分解（Brinson・FF12 と FF49）
    det = {nm: SR.simulate_detail(C[nm], rets) for nm in ('T3VW', 'U_exfin', 'CN12', 'CN49')}
    f12, f49 = ind_fn(info, 'ind12'), ind_fn(info, 'ind49')
    br = {'T3VW_vs_U_exfin_FF12': SR.brinson(det['T3VW'][1], det['U_exfin'][1], rets, f12),
          'T3VW_vs_U_exfin_FF49': SR.brinson(det['T3VW'][1], det['U_exfin'][1], rets, f49),
          'CN12_vs_U_exfin_FF12（配分≈0のはず）': SR.brinson(det['CN12'][1], det['U_exfin'][1], rets, f12),
          'CN49_vs_U_exfin_FF49（配分≈0のはず）': SR.brinson(det['CN49'][1], det['U_exfin'][1], rets, f49)}
    for k, v in br.items():
        v['by_industry'] = dict(list(v['by_industry'].items())[:10])
    a12 = br['T3VW_vs_U_exfin_FF12']
    tot = a12['allocation_ann'] + a12['selection_ann']
    sec['brinson'] = br
    sec['brinson_allocation_share_FF12'] = round(a12['allocation_ann'] / tot, 3) if tot > 0 else None
    t49 = br['T3VW_vs_U_exfin_FF49']
    sec['tech_in_brinson'] = {'FF12_BusEq_alloc': a12['by_industry'].get(TECH12, {}).get('alloc'), 'FF12_BusEq_select': a12['by_industry'].get(TECH12, {}).get('select'),
                              'FF49_tech_alloc': round(sum(t49['by_industry'].get(g, {}).get('alloc', 0) for g in TECH49), 2),
                              'regression_implied_tech_part_FF12': sec['reg12']['full']['tech_part_ann'],
                              'regression_implied_industry_part_FF12': sec['reg12']['full']['industry_part_ann']}
    fam['SEC_CN12'] = port['CN12']['vs']['U_exfin']['full']
    fam['SEC_CN49'] = port['CN49']['vs']['U_exfin']['full']
    fam['H2_within_BusEq'] = port['BusEq_T3VW']['vs']['BusEq_all']['full']
    fam['H3_CN49_exBusEq'] = port['CN49_exB']['vs']['U_exfin_exBusEq']['full']
    res['sec'] = sec
    tested += [{'name': n, 'role': 'family（Holm）'} for n in ('SEC_reg12', 'SEC_reg49', 'SEC_CN12', 'SEC_CN49', 'H2_within_BusEq', 'H3_CN49_exBusEq')]
    tested += [{'name': 'SEC_T3VW_vs_U_exfin', 'role': 'report'}, {'name': 'SEC_exB_T3VW_vs_U_exfin_exBusEq（H2 の後半）', 'role': 'report（H2 の条件）'},
               {'name': 'SEC_CN12_exB', 'role': 'report'}] + [{'name': 'SEC_sens_' + k, 'role': 'report（感度）'} for k in sec['sensitivity']] + \
              [{'name': 'SEC_brinson_' + k, 'role': 'report（記述）'} for k in br]

    # ── 家族の Holm
    pv = {k: (v or {}).get('p') for k, v in fam.items()}
    hm = M.holm(pv)
    famo = {}
    for k in FAMILY:
        v = fam.get(k) or {}
        is_reg = 'alpha_ann' in v
        famo[k] = {'estimate_ann': v.get('alpha_ann') if is_reg else v.get('ex_ann'), 't': v.get('t'), 'p': v.get('p'), 'holm_p': hm.get(k),
                   'kind': '回帰α' if is_reg else '組み方の超過（算術平均）', 'from': v.get('from'), 'to': v.get('to')}
    res['family'] = famo

    # ── 仮説（事前登録どおり）
    reg12 = sec['reg12']['full']; cn12 = port['CN12']['vs']['U_exfin']['full']; cn49 = port['CN49']['vs']['U_exfin']['full']
    reg49 = sec['reg49']['full']
    h1 = bool(reg12['alpha_ann'] > 0 and reg12['alpha_ann'] >= 2 * cn12['ex_ann'])
    h1b = bool(reg49['alpha_ann'] > 0 and reg49['alpha_ann'] >= 2 * cn49['ex_ann'])
    wb = port['BusEq_T3VW']['vs']['BusEq_all']['full']; xb = port['exB_T3VW']['vs']['U_exfin_exBusEq']['full']
    h2 = bool(wb['ex_ann'] > 0 and (wb['t'] or 0) >= 1.65 and xb['ex_ann'] <= 0)
    h3v = port['CN49_exB']['vs']['U_exfin_exBusEq']['full']
    h3 = bool(h3v['ex_ann'] > 0 and (h3v['t'] or 0) >= 1.65)
    share = sec['brinson_allocation_share_FF12']
    if h3:
        outcome = '(c) 技術の外にも上乗せがある'
    elif h2:
        outcome = '(b) 技術の中での選別'
    elif share is not None and share >= 0.5:
        outcome = '(a) 主に技術の比重（業種の配分）'
    else:
        outcome = '判定なし（(a)(b)(c) のどれの条件にも当たらない）'
    if h2 and h3:
        outcome = '(b)+(c) 技術の中の選別と、技術の外の上乗せの両方'
    res['hypotheses'] = {
        'H1_regression_inflation': {'rule': 'SEC T3VW の FF12 回帰α > 0 かつ ≥ 2×組み方中立 CN12 の超過', 'reg_alpha': reg12['alpha_ann'], 'reg_t': reg12['t'],
                                    'cn_excess': cn12['ex_ann'], 'cn_t': cn12['t'], 'holds': h1,
                                    'FF49_secondary': {'reg_alpha': reg49['alpha_ann'], 'cn_excess': cn49['ex_ann'], 'holds': h1b}},
        'H2_selection_within_tech': {'rule': 'BusEq の中の cop_at 上位1/3（時価加重）が BusEq 全体（時価加重）に t≥1.65 で勝ち、かつ BusEq を除いた版（上位1/3 vs 除いた全体）の超過 ≤ 0',
                                     'within': {'ex_ann': wb['ex_ann'], 't': wb['t'], 'cagr_diff': wb['cagr_diff']},
                                     'ex_BusEq_version': {'ex_ann': xb['ex_ann'], 't': xb['t']}, 'holds': h2},
        'H3_edge_outside_tech': {'rule': 'BusEq を除き FF49 で組み方を中立にした版が 除いた全体に 超過>0 かつ t≥1.65',
                                 'ex_ann': h3v['ex_ann'], 't': h3v['t'], 'cagr_diff': h3v['cagr_diff'], 'holds': h3},
        'outcome': outcome, 'brinson_allocation_share_FF12': share}
    tested += [{'name': 'H1', 'role': '仮説'}, {'name': 'H2', 'role': '仮説'}, {'name': 'H3', 'role': '仮説'}]

    # ── 地域（米国外・国ごと）
    reg_c = {}
    for c in DEV:
        try:
            g = jkp_gics(c)
            p = jkp_pf_n(c)
            mk = M.jkp_mkt(c, 'vw')
        except Exception as e:  # noqa
            reg_c[c] = {'error': str(e)[:120]}; continue
        p3n = p.get(side, {})
        p3 = {k: r for k, (r, n) in p3n.items()}
        nh = [n for k, (r, n) in p3n.items() if M.HOLD_START <= k <= JKP_END and n is not None]
        hold_ks = [k for k in p3 if M.HOLD_START <= k <= JKP_END and k in mk]
        o = {'median_n_good_tercile_hold': S.median(nh) if nh else None, 'hold_months': len(hold_ks)}
        if not nh or S.median(nh) < 10 or len(hold_ks) < 120:
            o['excluded'] = '良い三分位の社数の中央 <10 か 保有の月 <120'
            reg_c[c] = o; continue
        # 窓の月の95%以上にあるセクターだけ（欠けは0にしない）
        sect = [s_ for s_, v in g.items() if sum(1 for k in hold_ks if k in v) >= 0.95 * len(hold_ks)]
        y = diff(p3, mk)
        xs = [('mkt', mk)] + [('G' + s_, diff(g[s_], mk)) for s_ in sorted(sect)]
        o['sectors'] = sorted(sect)
        o['raw_hold'] = M.excess_stats(p3, mk, *HOLD)
        o['reg_gics_hold'] = reg(y, xs, *HOLD, tech=('G45',))
        o['reg_capm_hold'] = reg(y, [('mkt', mk)], *HOLD)
        reg_c[c] = o
    got = [c for c, o in reg_c.items() if o.get('reg_gics_hold')]
    al = [reg_c[c]['reg_gics_hold']['alpha_ann'] for c in got]
    regional = {'rule': 'JKP の各国（先進国・米国を除く22か国）の cop_at 良い三分位（vw）−その国の vw 市場を、その国の GICS 11セクター（−市場）と市場で回帰（保有 2007〜2025）',
                'countries': reg_c, 'n_measured': len(got), 'n_alpha_pos': sum(1 for a in al if a > 0),
                'share_alpha_pos': round(sum(1 for a in al if a > 0) / len(al), 3) if al else None,
                'median_alpha': round(S.median(al), 2) if al else None,
                'n_t_ge_1_65': sum(1 for c in got if (reg_c[c]['reg_gics_hold']['t'] or 0) >= 1.65),
                'n_raw_pos': sum(1 for c in got if reg_c[c]['raw_hold'] and reg_c[c]['raw_hold']['ex_ann'] > 0)}
    for r_ in ('developed', 'world_ex_us'):
        try:
            sd, pr = M.jkp_good_side(r_, 'cop_at', 'vw', upto=M.TRAIN_END)
            mk = M.jkp_mkt(r_, 'vw')
            p3 = pr[side]
            regional[r_] = {'good_side_estimated': sd, 'used_side': side,
                            'raw': {w: M.excess_stats(p3, mk, a, z) for w, (a, z) in {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': HOLD}.items()},
                            'capm_hold': reg(diff(p3, mk), [('mkt', mk)], *HOLD),
                            'note': '地域の業種リターンは JKP に無い（国ごとのみ）ので、地域全体は業種調整なし'}
        except Exception as e:  # noqa
            regional[r_] = {'error': str(e)[:120]}
    res['regional_oos'] = regional
    tested += [{'name': f'regional_{c}', 'role': 'report（米国外の答え合わせ）'} for c in DEV] + \
              [{'name': 'regional_developed', 'role': 'report'}, {'name': 'regional_world_ex_us', 'role': 'report'}]

    # ── EX-27（別の角度が作る 1996〜2001 のパネル。あれば引用するだけ）
    exp = os.path.join(M.BASE, 'out', 'mw_ex27.json')
    if os.path.exists(exp):
        try:
            e = json.load(open(exp))
            pick = {}

            def walk(o, path=''):
                if isinstance(o, dict):
                    for k, v in o.items():
                        kp = f'{path}/{k}'
                        if any(s_ in k for s_ in ('exBusEq', 'IN_T3SM', 'tech_share', 'T3VW')) and len(json.dumps(v, ensure_ascii=False)) < 4000:
                            pick[kp] = v
                        elif len(pick) < 80:
                            walk(v, kp)
            walk(e)
            res['ex27'] = {'source': 'out/mw_ex27.json（別の角度 ex27 の結果・ここでは再計算しない）', 'commit': sha_of('out/mw_ex27.json'), 'picked': pick}
        except Exception as e:  # noqa
            res['ex27'] = {'error': str(e)[:200]}
    else:
        res['ex27'] = {'status': '未実施（実行時に out/mw_ex27.json が無かった）'}
    tested.append({'name': 'ex27_citation', 'role': 'report（あれば引用）'})

    # ── 点検
    sr_prev = {}
    try:
        d = json.load(open(os.path.join(M.BASE, 'out', 'mw_sec_replication.json')))
        sr_prev = {'cop_at_T3VW_vs_U_all': d['strategies']['cop_at_T3VW']['vs']['U_all']['full'],
                   'cop_at_T3VW_exBusEq_vs_U_exfin_exBusEq': d['exploratory_prereg2']['strategies']['cop_at_T3VW_exBusEq']['vs']['U_exfin_exBusEq']['full']}
    except Exception:  # noqa
        pass
    rg_prev = None
    try:
        d = json.load(open(os.path.join(M.BASE, 'out', 'mw_reality_gap.json')))
        rg_prev = d['part1_decomposition']['P1_cop_at']['hold']['M2_ind12']
        rg_prev = {k: rg_prev.get(k) for k in ('alpha_ann', 'alpha_t_nw', 'n')}
    except Exception:  # noqa
        pass
    chk = {'french_mkt_cagr_full': round(M.cagr(MKT) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(MKT, M.HOLD_START)) * 100, 2),
           'french_last_month': max(MKT), 'french_ind12_last': max(i12['BusEq']), 'french_ind49_last': max(i49['Softw']),
           'reproduce_sec_T3VW_vs_U_all': {'now': M.excess_stats(ser['T3VW'], ser['U_all'], SEC_START, SEC_END), 'before': sr_prev.get('cop_at_T3VW_vs_U_all')},
           'reproduce_sec_exB': {'now': port['exB_T3VW']['vs']['U_exfin_exBusEq']['full'], 'before': sr_prev.get('cop_at_T3VW_exBusEq_vs_U_exfin_exBusEq')},
           'reproduce_reality_gap_P1_cop_at_hold_M2_ind12': {'now': {k: fam['JKP_reg12_hold'][k] for k in ('alpha_ann', 't', 'n')}, 'before': rg_prev},
           'identity_alpha_plus_contrib_eq_raw_max_abs': max(abs(v['identity_check']) for v in [fam['JKP_reg12_hold'], fam['JKP_reg49_hold'], fam['SEC_reg12'], fam['SEC_reg49']]),
           'sec_months': [min(ser['T3VW']), max(ser['T3VW']), len(ser['T3VW'])],
           'excess_vs_total': 'JKP は超過どうし（P−Mkt-RF）、SEC は総リターンどうし（組−母集団）。回帰の説明変数は French（業種−Mkt は総リターンどうし・市場は Mkt-RF）',
           'look_ahead': 'SEC は6月30日までに提出された10-Kと6月末の浮動株時価で組み、7月から翌6月まで保有。SN は当月より前の窓の係数だけ。JKP・French は作り方が後知恵を避けている'}
    res['checks'] = chk
    res['tested'] = tested
    res['n_tested'] = len(tested)
    res['deviations'] = [
        'JKP には株ごとのデータが無いので、JKP×組み方中立のセルは作れない。代理として直前60/120か月の係数で業種を引いた SN を報告（家族に入れない）',
        '米国外の答え合わせは地域全体ではなく国ごと（JKP の業種リターンは国ごとの GICS しか無い。地域全体は業種調整なしの生の差と CAPM α を報告）',
        'EX-27（1996〜2001）は別の角度 ex27 のパネル。ここでは作らず、実行時に out/mw_ex27.json があれば引用するだけ']
    res['runtime_s'] = round(time.time() - t0)
    p = M.save(OUT_NAME, res)
    print('→', p)
    print(json.dumps(res['family'], ensure_ascii=False, indent=1))
    print(json.dumps(res['hypotheses'], ensure_ascii=False, indent=1))
    return res


if __name__ == '__main__':
    stage = sys.argv[1] if len(sys.argv) > 1 else 'run'
    {'check': check, 'run': run}[stage]()
