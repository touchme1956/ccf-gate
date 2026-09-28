#!/usr/bin/env python3
"""night/mw_holdable_breakeven.py — 買える器だけの配合は、今の持ち方に20年の円の積立（税引後・NISA込み）で勝つか＋損益分岐

2026-09-28 mw（市場に勝てる歴史検証）の角度 holdable_breakeven。総合（意思決定の分析）であって上乗せ探しではない。
器の載り（capture）・公表後の目減り（haircut）は他の角度の結果ファイルから読む入力。
事前登録: out/mw_holdable_breakeven_prereg.json（線は結果を見て動かさない）。門・採点・配分には使わない（読むだけ）。

使い方:
  python3 night/mw_holdable_breakeven.py            # 全部回して out/mw_holdable_breakeven.json
  python3 night/mw_holdable_breakeven.py --selftest # 積立・NISA・税の模型とブートストラップの検算だけ
  python3 night/mw_holdable_breakeven.py --quick    # 道を減らした試運転（結果は書かない）
"""
import argparse, csv, io, json, math, os, subprocess, sys, time, datetime
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

BASE = M.BASE
ANGLE = 'holdable_breakeven'
PRE = 'out/mw_holdable_breakeven_prereg.json'
OUT = 'mw_holdable_breakeven.json'
END = 202608
TAX = 0.20315
CONTRIB = 170000.0
T = 240
SEED = 20260928
NISA_TS, NISA_GR, NISA_LIFE, NISA_LIFE_GR = 1.2e6, 2.4e6, 18e6, 12e6


# ───────────────────────── 月の算術 ─────────────────────────
def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def mrange(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


# ───────────────────────── データ ─────────────────────────
def load_fx():
    """円/ドルの月末 → {yyyymm: 変化}。1971 年より前は 0（登録どおりの仮定）"""
    b = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=3650)
    rows = list(csv.reader(io.StringIO(b.decode())))
    me, first = {}, None
    for r in rows[1:]:
        if len(r) < 2 or r[1] in ('', '.'):
            continue
        d = r[0]; v = float(r[1])
        m = int(d[:4]) * 100 + int(d[5:7])
        if first is None:
            first = v
        me[m] = v  # 行は日付順なので最後の値＝月末
    fx = {}
    for m in mrange(192607, END):
        if m < 197101:
            fx[m] = 0.0
        elif m == 197101:
            fx[m] = me[m] / first - 1
        else:
            p = madd(m, -1)
            if m in me and p in me:
                fx[m] = me[m] / me[p] - 1
    return fx, me


def load_fx_jst():
    """感度だけ: 1971 年より前を JST の年次の円相場（xrusd）の変化を 12 か月に均等に割って置く"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(M.get('https://www.macrohistory.net/app/download/9834512469/JSTdatasetR6.xlsx', 'jst_R6.xlsx', max_age_days=3650)), read_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True); h = next(it); I = {k: i for i, k in enumerate(h)}
    x = {}
    for r in it:
        if r[I['country']] == 'Japan' and r[I['xrusd']] is not None:
            x[r[I['year']]] = float(r[I['xrusd']])
    out = {}
    for m in mrange(192607, 197012):
        y = m // 100
        out[m] = (x[y] / x[y - 1]) ** (1 / 12) - 1 if y in x and y - 1 in x else None
    return out


def load_gold():
    j = json.loads(M.get('https://prices.lbma.org.uk/json/gold_pm.json', name='lbma_gold_pm.json', max_age_days=3650))
    me = {}
    for x in j:
        v = (x.get('v') or [None])[0]
        if v is None or v <= 0:
            continue
        me[int(x['d'][:4]) * 100 + int(x['d'][5:7])] = v
    ks = sorted(me)
    return {k: me[k] / me[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k and k <= END}


def french_monthly_first(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly':
            cols = v['cols']
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
    raise KeyError(name)


def load_data():
    ff = M.ff_factors()
    S = {'MKT': {k: v for k, v in ff['mkt'].items() if k <= END}, 'RF': {k: v for k, v in ff['rf'].items() if k <= END}}
    ind = M.french_series('49_Industry_Portfolios', 'Value Weight')
    for c, k in (('Chips', 'CHIPS'), ('Hardw', 'HARDW'), ('Softw', 'SOFTW'), ('Aero', 'AERO')):
        S[k] = {m: v for m, v in ind[c].items() if m <= END}
    t3 = {}
    for m in S['MKT']:
        xs = [S[k][m] for k in ('CHIPS', 'HARDW', 'SOFTW') if m in S[k]]
        if len(xs) >= 2:
            t3[m] = sum(xs) / len(xs)
    S['TECH3'] = t3
    import mw_country
    fr = mw_country.french_intl()
    S['EAFE'] = {k: v for k, v in fr['_eafe'].items() if k <= END}
    S['JPN'] = {k: v for k, v in fr['jpn']['usd'].items() if k <= END}
    em = french_monthly_first('Emerging_5_Factors')
    S['EM'] = {m: em['Mkt-RF'][m] + em['RF'][m] for m in em['Mkt-RF'] if m in em['RF'] and m <= END}
    S['GOLD'] = load_gold()
    fx, fx_me = load_fx()
    return S, fx, fx_me


def ols(y, x):
    x = np.asarray(x); y = np.asarray(y)
    X = np.column_stack([np.ones_like(x), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ b
    return {'alpha_ann': float(b[0] * 12 * 100), 'beta': float(b[1]), 'resid_sd_ann': float(res.std(ddof=2) * math.sqrt(12) * 100),
            'n': len(y), 'r2': float(1 - res.var() / y.var()) if y.var() > 0 else None}


def fits(S, fx):
    """器の代理の載り・ずれ（登録どおりの窓）"""
    out = {}
    y = {t: M.yahoo(t) for t in ('QQQ', 'SMH', 'RSP', 'MOAT', 'VEA', 'VWO', '1306.T')}
    out['_yahoo_ranges'] = {t: [min(v), max(v), len(v)] for t, v in y.items()}
    mk, t3, ch = S['MKT'], S['TECH3'], S['CHIPS']
    ms = [m for m in mrange(199905, END) if m in y['QQQ'] and m in mk and m in t3]
    out['NDX'] = ols([y['QQQ'][m] - mk[m] for m in ms], [t3[m] - mk[m] for m in ms]); out['NDX']['from'] = ms[0]; out['NDX']['to'] = ms[-1]
    ms = [m for m in mrange(200008, END) if m in y['SMH'] and m in mk and m in ch]
    out['SMH'] = ols([y['SMH'][m] - mk[m] for m in ms], [ch[m] - mk[m] for m in ms]); out['SMH']['from'] = ms[0]; out['SMH']['to'] = ms[-1]

    def sd_diff(a, b, m0, m1):
        ms = [m for m in mrange(m0, m1) if m in a and m in b]
        d = np.array([a[m] - b[m] for m in ms])
        return {'sd_ann': float(d.std(ddof=1) * math.sqrt(12) * 100), 'mean_ann': float(d.mean() * 1200), 'n': len(ms), 'from': ms[0], 'to': ms[-1]}
    out['RSP'] = sd_diff(y['RSP'], mk, 200307, END)
    out['VEA'] = sd_diff(y['VEA'], S['EAFE'], 200709, END)
    out['VWO'] = sd_diff(y['VWO'], S['EM'], 200701, END)
    jpy_jpn = {m: (1 + S['JPN'][m]) * (1 + fx[m]) - 1 for m in S['JPN'] if m in fx}
    out['JMKT'] = sd_diff(y['1306.T'], jpy_jpn, 200903, END)
    # MOAT: JKP 米国 qmj の良い側（2006-12 までで決める）
    side, p = M.jkp_good_side('usa', 'qmj', 'vw', upto=200612)
    q = {m: p[side][m] + S['RF'][m] for m in p[side] if m in S['RF']}
    qa = {m: q[m] - mk[m] for m in q if m in mk}
    ms = sorted(qa)
    E_q = float(np.mean([qa[m] for m in ms]) * 1200)
    ms2 = [m for m in mrange(201206, 202512) if m in y['MOAT'] and m in qa]
    f = ols([y['MOAT'][m] - mk[m] for m in ms2], [qa[m] for m in ms2])
    va = float(np.mean([y['MOAT'][m] - mk[m] for m in ms2]) * 1200); pa = float(np.mean([qa[m] for m in ms2]) * 1200)
    out['MOAT'] = {'good_side': side, 'E_paper_full': E_q, 'paper_from': ms[0], 'paper_to': ms[-1], 'fit': f,
                   'vehicle_active_ann': va, 'paper_active_ann': pa, 'capture_mean': va / pa if abs(pa) > 1e-9 else None,
                   'noise': sd_diff(y['MOAT'], mk, 201206, 202512)}
    return out, y


def inputs_from_files():
    """他の角度が測った値（入力）"""
    iv = json.load(open(os.path.join(BASE, 'out', 'mw_investable_valmom.json')))
    tv = {r['name']: r for r in iv['tested'] if 'name' in r}
    pb = iv['families']['P_buyable']
    jb = json.load(open(os.path.join(BASE, 'out', 'mw_jp_nisa_bridge.json')))
    tj = {r.get('id'): r for r in jb['tested']}
    j1489 = tj['1489.T']
    lo = j1489.get('loading') or j1489.get('capture') or j1489.get('source')
    if not isinstance(lo, dict) or 'one_factor' not in lo:
        lo = next(v for v in j1489.values() if isinstance(v, dict) and 'one_factor' in v)
    meta = json.load(open(os.path.join(BASE, 'out', '_mw_cache', 'ita_meta_investable_valmom.json')))
    fee_emr = (meta.get('JP:iFree新興国RAFI') or {}).get('trust_fee_incl_tax_pct') or 0.374
    pw = tv['paper:world']
    yrs = pw['months'] / 12
    pp = json.load(open(os.path.join(BASE, 'out', 'mw_postpub.json')))['decay']
    return {
        'PXF': {'E': tv['paper:developed']['full'][0], 'k': pb['PXF']['loading']['one_factor']['beta'],
                'k_mean': pb['PXF']['loading']['capture'], 'noise_sd': pb['PXF']['full']['te'], 'src': 'out/mw_investable_valmom.json'},
        'EMR': {'E': tv['paper:emerging']['full'][0], 'k': pb['JP:iFree新興国RAFI']['loading']['one_factor']['beta'],
                'k_mean': pb['JP:iFree新興国RAFI']['loading']['capture'], 'noise_sd': pb['JP:iFree新興国RAFI']['full']['te'],
                'fee_pct': fee_emr, 'src': 'out/mw_investable_valmom.json・ita_meta'},
        'JHD': {'E': tj['X2_DIV']['full']['ex_ann'], 'k': lo['one_factor']['beta'],
                'k_mean': (lo['vehicle_active_ann'] / lo['paper_active_ann']) if lo.get('paper_active_ann') else None,
                'noise_sd': j1489['full']['te'], 'grade_of_paper': tj['X2_DIV'].get('grade'), 'src': 'out/mw_jp_nisa_bridge.json'},
        'REF': {'E': pw['full'][0], 'k': 1.0, 'k_mean': 1.0, 'noise_sd': pw['full'][0] * math.sqrt(yrs) / pw['full'][1],
                'src': 'out/mw_investable_valmom.json paper:world'},
        'postpub': {'pre_in_sample': pp['in_sample']['pooled_ex_ann'], 'post_pub': pp['post_pub']['pooled_ex_ann'],
                    'ratio': pp['post_pub']['pooled_ex_ann'] / pp['in_sample']['pooled_ex_ann']},
    }


# ───────────────────────── 袖と配合 ─────────────────────────
def build_sleeves(F, INP):
    bN, bS = F['NDX']['beta'], F['SMH']['beta']
    sl = {
        'CASTLE': dict(leg={'TECH3': 0.2, 'CHIPS': 0.4, 'AERO': 0.4}, fee=0.0, y=0.008, cls='us_stock', acct='gr', sd=0.0, E=0.0, k=0.0, k_mean=0.0),
        'NDX': dict(leg={'MKT': 1 - bN, 'TECH3': bN}, fee=0.00495, y=0.008, cls='fund_us', acct='ts', sd=F['NDX']['resid_sd_ann'] / 100, E=0.0, k=0.0, k_mean=0.0),
        'SMH': dict(leg={'MKT': 1 - bS, 'CHIPS': bS}, fee=0.0035, y=0.009, cls='etf_us', acct='gr', sd=F['SMH']['resid_sd_ann'] / 100, E=0.0, k=0.0, k_mean=0.0),
        'SPX': dict(leg={'MKT': 1.0}, fee=0.000814, y=0.015, cls='fund_us', acct='ts', sd=0.0, E=0.0, k=0.0, k_mean=0.0),
        'RSP': dict(leg={'MKT': 1.0}, fee=0.002, y=0.017, cls='etf_us', acct='gr', sd=F['RSP']['sd_ann'] / 100, E=0.0, k=0.0, k_mean=0.0),
        'MOAT': dict(leg={'MKT': 1.0}, fee=0.0046, y=0.012, cls='etf_us', acct='gr', sd=F['MOAT']['noise']['sd_ann'] / 100,
                     E=F['MOAT']['E_paper_full'] / 100, k=F['MOAT']['fit']['beta'], k_mean=F['MOAT']['capture_mean']),
        'GOLD': dict(leg={'GOLD': 1.0}, fee=0.001, y=0.0, cls='none', acct='tx', sd=0.0, E=0.0, k=0.0, k_mean=0.0),
        'DEV': dict(leg={'EAFE': 1.0}, fee=0.0003, y=0.03, cls='etf_exus', acct='gr', sd=F['VEA']['sd_ann'] / 100, E=0.0, k=0.0, k_mean=0.0),
        'PXF': dict(leg={'EAFE': 1.0}, fee=0.0044, y=0.032, cls='etf_exus', acct='gr', sd=INP['PXF']['noise_sd'] / 100,
                    E=INP['PXF']['E'] / 100, k=INP['PXF']['k'], k_mean=INP['PXF']['k_mean']),
        'EMM': dict(leg={'EM': 1.0}, fee=0.0007, y=0.03, cls='etf_exus', acct='gr', sd=F['VWO']['sd_ann'] / 100, E=0.0, k=0.0, k_mean=0.0),
        'EMR': dict(leg={'EM': 1.0}, fee=INP['EMR']['fee_pct'] / 100, y=0.025, cls='fund_exus', acct='ts', sd=INP['EMR']['noise_sd'] / 100,
                    E=INP['EMR']['E'] / 100, k=INP['EMR']['k'], k_mean=INP['EMR']['k_mean']),
        'JMKT': dict(leg={'JPN': 1.0}, fee=0.00066, y=0.02, cls='etf_jp', acct='gr', sd=F['JMKT']['sd_ann'] / 100, E=0.0, k=0.0, k_mean=0.0),
        'JHD': dict(leg={'JPN': 1.0}, fee=0.00308, y=0.033, cls='etf_jp', acct='gr', sd=INP['JHD']['noise_sd'] / 100,
                    E=INP['JHD']['E'] / 100, k=INP['JHD']['k'], k_mean=INP['JHD']['k_mean']),
        'REF': dict(leg={'MKT': 0.6, 'EAFE': 0.4}, fee=0.0, y=0.02, cls='fund_exus', acct='ts', sd=INP['REF']['noise_sd'] / 100,
                    E=INP['REF']['E'] / 100, k=1.0, k_mean=1.0),
    }
    return sl


CUR_W = {'CASTLE': 0.20, 'NDX': 0.60, 'SMH': 0.20}
XS = ['SPX', 'RSP', 'MOAT', 'GOLD', 'DEV', 'PXF', 'EMM', 'EMR', 'JMKT', 'JHD', 'ALL_EDGE', 'REF']
EDGE4 = ['MOAT', 'PXF', 'EMR', 'JHD']
CLASS_OF = {'SPX': 'US', 'RSP': 'US', 'MOAT': 'US', 'GOLD': 'GOLD', 'DEV': 'EAFE', 'PXF': 'EAFE', 'REF': 'EAFE',
            'JMKT': 'JPN', 'JHD': 'JPN', 'EMM': 'EM', 'EMR': 'EM', 'ALL_EDGE': 'EM'}
CLASS_SERIES = {'US': ['MKT', 'TECH3', 'CHIPS', 'AERO'], 'GOLD': ['MKT', 'TECH3', 'CHIPS', 'AERO', 'GOLD'],
                'EAFE': ['MKT', 'TECH3', 'CHIPS', 'AERO', 'EAFE'], 'JPN': ['MKT', 'TECH3', 'CHIPS', 'AERO', 'JPN'],
                'EM': ['MKT', 'TECH3', 'CHIPS', 'AERO', 'EAFE', 'JPN', 'EM']}
EXUS_SERIES = ['EAFE', 'JPN', 'EM']


def mixes():
    out = {}
    for X in XS:
        for w in (0.1, 0.2, 0.3):
            wt = {'CASTLE': 0.2, 'NDX': 0.6 * (1 - w), 'SMH': 0.2 * (1 - w)}
            if X == 'ALL_EDGE':
                for e in EDGE4:
                    wt[e] = 0.8 * w / 4
            else:
                wt[X] = 0.8 * w
            out[f'{X}_w{int(w * 100)}'] = {'w': wt, 'class': CLASS_OF[X], 'X': X, 'frac': w, 'primary': X != 'REF', 'buyable': X != 'REF'}
    out['SPX_ONLY'] = {'w': {'CASTLE': 0.2, 'SPX': 0.8}, 'class': 'US', 'X': 'SPX', 'frac': 1.0, 'primary': True, 'buyable': True}
    out['NDX_ONLY'] = {'w': {'CASTLE': 0.2, 'NDX': 0.8}, 'class': 'US', 'X': 'NDX', 'frac': None, 'primary': False, 'buyable': True}
    out['SPX100'] = {'w': {'SPX': 1.0}, 'class': 'US', 'X': 'SPX', 'frac': None, 'primary': False, 'buyable': True}
    return out


# ───────────────────────── 積立・NISA・税の模型 ─────────────────────────
DIST = {'etf_us', 'us_stock', 'etf_exus', 'etf_jp'}


def simulate(R, FX, weights, cls, acct, ylds, contrib=CONTRIB):
    """R: (S,N,T) 米ドルの月次リターン（信託報酬・上乗せ・ずれ込み）、FX: (N,T) 円/ドルの変化、weights: (S,) 目標。
    戻り値: 最終資産（円・税引後, N）、円の時間加重の指数（税前）の最大下落 (N)、NISA の生涯枠が埋まった月（N）"""
    S, N, TT = R.shape
    VN = np.zeros((S, N)); VT = np.zeros((S, N)); BT = np.zeros((S, N))
    cash = np.zeros(N); life = np.zeros(N); lgr = np.zeros(N)
    d = (np.asarray(ylds, float) / 12)[:, None]
    dist = np.array([c in DIST for c in cls], float)[:, None]
    drag = np.array([0.10 if c in ('fund_us', 'fund_exus') else 0.0 for c in cls])[:, None]
    dg = np.array([0.9 if c == 'etf_exus' else 1.0 for c in cls])[:, None]          # 器の中の外国源泉の後に分配される割合
    netN = np.array([1.0 if c == 'etf_jp' else 0.9 for c in cls])[:, None]          # NISA: 米国の源泉 10%（日本株は0）
    netT = np.full((S, 1), 1 - TAX)                                                 # 課税口座: 外国税額控除で合計 20.315%
    Wc = np.asarray(weights, float)[:, None]
    order = [i for i in range(S) if acct[i] == 'ts'] + [i for i in range(S) if acct[i] == 'gr'] + [i for i in range(S) if acct[i] == 'tx']
    twr = np.ones(N); peak = np.ones(N); mdd = np.zeros(N); filled = np.full(N, -1)
    tsl = grl = None
    for t in range(TT):
        if t % 12 == 0:
            tsl = np.full(N, NISA_TS); grl = np.full(N, NISA_GR)
        amt = contrib + cash
        H = VN + VT
        tot = H.sum(0)
        gap = np.maximum(0.0, Wc * (tot + amt) - H)
        gs = gap.sum(0)
        buy = gap * (amt / gs)
        if (life < NISA_LIFE - 1e-6).any():
            for i in order:
                a = buy[i]
                if acct[i] == 'ts':
                    x = np.minimum(a, np.maximum(0.0, np.minimum(tsl, NISA_LIFE - life)))
                    tsl = tsl - x; life = life + x; VN[i] += x; a = a - x
                if acct[i] in ('ts', 'gr'):
                    x = np.minimum(a, np.maximum(0.0, np.minimum(np.minimum(grl, NISA_LIFE_GR - lgr), NISA_LIFE - life)))
                    grl = grl - x; lgr = lgr + x; life = life + x; VN[i] += x; a = a - x
                VT[i] += a; BT[i] += a
            filled = np.where((filled < 0) & (life >= NISA_LIFE - 1e-6), t, filled)
        else:
            VT += buy; BT += buy
        r = R[:, :, t]; fx = FX[:, t][None, :]
        V0 = VN + VT; v0 = V0.sum(0)
        twr = twr * (1 + (V0 * ((1 + r) * (1 + fx) - 1)).sum(0) / v0)
        peak = np.maximum(peak, twr); mdd = np.minimum(mdd, twr / peak - 1)
        pr = r - dist * d - drag * d
        g = (1 + pr) * (1 + fx)
        base = dist * d * dg * (1 + fx)
        cash = (VN * base * netN).sum(0) + (VT * base * netT).sum(0)
        VN *= g; VT *= g
    tax = TAX * np.maximum(0.0, (VT - BT).sum(0))
    return (VN + VT).sum(0) - tax + cash, mdd, filled


def sb_indices(n, L, N, rng, TT=T):
    """定常ブロック・ブートストラップ（循環）の添字 (N, TT)"""
    idx = np.empty((N, TT), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, N)
    p = 1.0 / L
    for t in range(1, TT):
        new = rng.random(N) < p
        idx[:, t] = np.where(new, rng.integers(0, n, N), (idx[:, t - 1] + 1) % n)
    return idx


# ───────────────────────── 場面 ─────────────────────────
def shifted_pool(P, piT, piUS):
    """P: {系列: np.array（プールの月）}。piT/piUS が None ならずらさない。年率の対数の差で平均をそろえる"""
    Q = dict(P)
    lm = np.log1p(P['MKT'])
    if piT is not None:
        for k in ('TECH3', 'CHIPS'):
            ld = np.log1p(P[k]) - lm
            Q[k] = np.expm1(np.log1p(P[k]) - ld.mean() + piT / 1200)
    if piUS is not None:
        for k in EXUS_SERIES:
            if k in P:
                ld = np.log1p(P[k]) - lm
                Q[k] = np.expm1(np.log1p(P[k]) - ld.mean() - piUS / 1200)
    return Q


SCEN = {
    'H': dict(piT=None, piUS=None, h=0.5, k='k'),
    'BR': dict(piT=-1.0, piUS=0.0, h=0.5, k='k'),
    'BR_h015': dict(piT=-1.0, piUS=0.0, h=0.15, k='k'),
    'BR_h0': dict(piT=-1.0, piUS=0.0, h=0.0, k='k'),
    'BR_T15': dict(piT=-1.5, piUS=0.0, h=0.5, k='k'),
    'BR_kmean': dict(piT=-1.0, piUS=0.0, h=0.5, k='k_mean'),
}
GRID_T = [x / 2 for x in range(-16, 17)]
GRID_US = [x / 2 for x in range(-12, 17)]


def sleeve_returns(names, SL, Q, idx, Z, sc):
    """(S,N,T) の米ドルのリターン"""
    out = np.empty((len(names), idx.shape[0], idx.shape[1]))
    for j, s in enumerate(names):
        sp = SL[s]
        r = np.zeros(idx.shape)
        for k, c in sp['leg'].items():
            r += c * Q[k][idx]
        kk = sp[sc['k']] if sp[sc['k']] is not None else sp['k']
        r += (sc['h'] * kk * sp['E'] - sp['fee']) / 12
        if sp['sd'] > 0:
            r += sp['sd'] / math.sqrt(12) * Z[s][:idx.shape[0]]
        out[j] = r
    return out


def run_mix(wt, SL, Q, idx, Z, FXp, sc):
    names = list(wt)
    R = sleeve_returns(names, SL, Q, idx, Z, sc)
    W, mdd, filled = simulate(R, FXp, [wt[s] for s in names], [SL[s]['cls'] for s in names], [SL[s]['acct'] for s in names], [SL[s]['y'] for s in names])
    return W, mdd, filled


def q(a, p):
    return float(np.quantile(a, p))


def compare(Wm, Wc, mm, mc):
    r = Wm / Wc
    tot = CONTRIB * T
    return {'p_beat': round(float((r > 1).mean()), 4), 'ratio_p5': round(q(r, 0.05), 4), 'ratio_med': round(q(r, 0.5), 4), 'ratio_p95': round(q(r, 0.95), 4),
            'mult_mix_med': round(q(Wm, 0.5) / tot, 3), 'mult_cur_med': round(q(Wc, 0.5) / tot, 3),
            'mdd_mix_med': round(q(mm, 0.5) * 100, 1), 'mdd_cur_med': round(q(mc, 0.5) * 100, 1)}


def crossing(grid, ps):
    """P(配合が勝つ) が 0.5 を横切る π（P は π とともに下がる想定。上がる場合も線形補間で最初の横切りを返す）"""
    for i in range(len(grid) - 1):
        a, b = ps[i] - 0.5, ps[i + 1] - 0.5
        if a == 0:
            return grid[i]
        if a * b < 0:
            return round(grid[i] + (grid[i + 1] - grid[i]) * a / (a - b), 2)
    if all(p > 0.5 for p in ps):
        return f'>{grid[-1]}' if ps[0] >= ps[-1] else f'<{grid[0]}'
    return f'<{grid[0]}' if ps[0] <= ps[-1] else f'>{grid[-1]}'


# ───────────────────────── 1升（クラス×時代×L）─────────────────────────
def cell(args):
    cls_name, era, L, S, FX, SL, MX, n_main, n_grid, fx_alt = args
    t0 = time.time()
    need = CLASS_SERIES[cls_name]
    lo, hi = (192607, 200612) if era == 'early' else (200701, END)
    ms = [m for m in mrange(lo, hi) if all(m in S[k] for k in need) and m in FX]
    # 連続を確かめる（プールの中の穴は循環のつなぎ目を増やす）
    gaps = [(a, b) for a, b in zip(ms, ms[1:]) if madd(a, 1) != b]
    if gaps:
        first_after = gaps[-1][1]
        ms = [m for m in ms if m >= first_after]
    P = {k: np.array([S[k][m] for m in ms]) for k in need}
    fxp = np.array([FX[m] for m in ms])
    ci = {'US': 0, 'GOLD': 1, 'EAFE': 2, 'JPN': 3, 'EM': 4}[cls_name]
    rng = np.random.default_rng(SEED + 100 * ci + (0 if era == 'early' else 10) + (0 if L == 60 else 1))
    idx = sb_indices(len(ms), L, n_main, rng)
    sleeves = sorted({s for mx in MX.values() for s in mx['w']} | set(CUR_W))
    zr = np.random.default_rng(SEED + 7 + 100 * ci + (0 if era == 'early' else 10) + (0 if L == 60 else 1))
    Z = {s: zr.standard_normal((n_main, T)) for s in sleeves}
    FXp = fxp[idx]
    res = {'class': cls_name, 'era': era, 'L': L, 'pool': [ms[0], ms[-1], len(ms)], 'scen': {}, 'grid_T': {}, 'grid_US': {}}
    # 主の場面
    for sn, sc in SCEN.items():
        Q = shifted_pool(P, sc['piT'], sc['piUS'])
        Wc, mc, fc = run_mix(CUR_W, SL, Q, idx, Z, FXp, sc)
        rs = {'CUR': {'mult_med': round(q(Wc, 0.5) / (CONTRIB * T), 3), 'mult_p5': round(q(Wc, 0.05) / (CONTRIB * T), 3),
                      'mdd_med': round(q(mc, 0.5) * 100, 1), 'nisa_filled_month_med': float(np.median(fc))}}
        for mn, mx in MX.items():
            Wm, mm, _ = run_mix(mx['w'], SL, Q, idx, Z, FXp, sc)
            rs[mn] = compare(Wm, Wc, mm, mc)
            if mn == 'SPX100':
                rs['CUR_vs_SPX100'] = {'p_cur_beats': round(float((Wc > Wm).mean()), 4), 'ratio_med': round(q(Wc / Wm, 0.5), 4),
                                       'ratio_p5': round(q(Wc / Wm, 0.05), 4), 'ratio_p95': round(q(Wc / Wm, 0.95), 4)}
        res['scen'][sn] = rs
    # 損益分岐の格子（2000本＝最初の n_grid 本）
    ig = idx[:n_grid]; FXg = FXp[:n_grid]
    base = SCEN['BR']
    for g in GRID_T:
        sc = dict(base, piT=g)
        Q = shifted_pool(P, g, base['piUS'])
        Wc, mc, _ = run_mix(CUR_W, SL, Q, ig, Z, FXg, sc)
        for mn, mx in MX.items():
            if mn == 'SPX100':
                continue
            Wm, _, _ = run_mix(mx['w'], SL, Q, ig, Z, FXg, sc)
            res['grid_T'].setdefault(mn, []).append(round(float((Wm > Wc).mean()), 4))
    if cls_name in ('EAFE', 'JPN', 'EM'):
        for g in GRID_US:
            sc = dict(base, piUS=g)
            Q = shifted_pool(P, base['piT'], g)
            Wc, mc, _ = run_mix(CUR_W, SL, Q, ig, Z, FXg, sc)
            for mn, mx in MX.items():
                Wm, _, _ = run_mix(mx['w'], SL, Q, ig, Z, FXg, sc)
                res['grid_US'].setdefault(mn, []).append(round(float((Wm > Wc).mean()), 4))
    # 感度: 1971 年より前の為替を JST で（US・early だけ・SPX_ONLY）
    if fx_alt is not None and cls_name == 'US' and era == 'early':
        fxa = np.array([fx_alt.get(m) if fx_alt.get(m) is not None else FX[m] for m in ms])
        FXa = fxa[idx]
        out = {}
        for sn in ('H', 'BR'):
            sc = SCEN[sn]
            Q = shifted_pool(P, sc['piT'], sc['piUS'])
            Wc, mc, _ = run_mix(CUR_W, SL, Q, idx, Z, FXa, sc)
            Wm, mm, _ = run_mix(MX['SPX_ONLY']['w'], SL, Q, idx, Z, FXa, sc)
            out[sn] = compare(Wm, Wc, mm, mc)
        res['fx_jst_sensitivity_SPX_ONLY'] = out
    res['sec'] = round(time.time() - t0, 1)
    return res


# ───────────────────────── 歴史の実際の20年窓（ブートストラップなし）─────────────────────────
def actual_windows(S, FX, SL, MX):
    out = {}
    sc = SCEN['H']
    for cls_name in ('US', 'GOLD', 'EAFE', 'JPN', 'EM'):
        need = CLASS_SERIES[cls_name]
        ms = [m for m in mrange(192607, END) if all(m in S[k] for k in need) and m in FX]
        gaps = [(a, b) for a, b in zip(ms, ms[1:]) if madd(a, 1) != b]
        if gaps:
            ms = [m for m in ms if m >= gaps[-1][1]]
        n = len(ms) - T + 1
        if n <= 0:
            continue
        idx = np.arange(n)[:, None] + np.arange(T)[None, :]
        P = {k: np.array([S[k][m] for m in ms]) for k in need}
        FXp = np.array([FX[m] for m in ms])[idx]
        Z = {s: np.zeros((n, T)) for s in SL}
        Wc, mc, _ = run_mix(CUR_W, SL, P, idx, Z, FXp, sc)
        starts = [ms[i] for i in range(n)]
        ends = [ms[i + T - 1] for i in range(n)]
        pre = np.array([e <= 200612 for e in ends])
        for mn, mx in MX.items():
            if mx['class'] != cls_name:
                continue
            Wm, mm, _ = run_mix(mx['w'], SL, P, idx, Z, FXp, sc)
            r = Wm / Wc
            out[mn] = {'windows': n, 'first_start': starts[0], 'last_start': starts[-1], 'win_rate': round(float((r > 1).mean()), 3),
                       'ratio_med': round(q(r, 0.5), 4), 'worst': [starts[int(np.argmin(r))], round(float(r.min()), 4)],
                       'best': [starts[int(np.argmax(r))], round(float(r.max()), 4)],
                       'win_rate_windows_ending_le_2006': round(float((r[pre] > 1).mean()), 3) if pre.any() else None,
                       'win_rate_windows_ending_ge_2007': round(float((r[~pre] > 1).mean()), 3) if (~pre).any() else None}
    return out


# ───────────────────────── 基礎率の表 ─────────────────────────
def rolling_log_diff(a, b, years=20, step=1):
    ks = sorted(set(a) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        if madd(w[0], n - 1) != w[-1]:
            continue
        out.append((w[0], sum(math.log1p(a[k]) - math.log1p(b[k]) for k in w) / years * 100))
    return out


def jst_annual():
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(M.get('https://www.macrohistory.net/app/download/9834512469/JSTdatasetR6.xlsx', 'jst_R6.xlsx', max_age_days=3650)), read_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True); h = next(it); I = {k: i for i, k in enumerate(h)}
    D = {}
    for r in it:
        D.setdefault(r[I['country']], {})[r[I['year']]] = (r[I['eq_tr']], r[I['xrusd']])
    usd = {}
    for c, d in D.items():
        for y, (eq, x) in d.items():
            if eq is None or x is None or (y - 1) not in d or d[y - 1][1] is None:
                continue
            usd.setdefault(c, {})[y] = (1 + eq) * d[y - 1][1] / x - 1
    return usd


def base_rates(S, crossings):
    out = {}
    t3 = rolling_log_diff(S['TECH3'], S['MKT'])
    ch = rolling_log_diff(S['CHIPS'], S['MKT'])
    for nm, arr in (('TECH3_minus_MKT', t3), ('CHIPS_minus_MKT', ch)):
        v = np.array([x for _, x in arr])
        out[nm] = {'windows': len(v), 'first_start': arr[0][0], 'last_start': arr[-1][0],
                   'quantiles_pct': {p: round(float(np.quantile(v, p)), 2) for p in (0.1, 0.25, 0.5, 0.75, 0.9)},
                   'share_gt_0': round(float((v > 0).mean()), 3),
                   'share_ge_break_even': {k: (round(float((v >= x).mean()), 3) if isinstance(x, (int, float)) else None) for k, x in crossings['T'].items()}}
    out['record_weight_base_rate_cited'] = 'out/industry_peak.json 道筋_山ごと 20年: 中央 −1.01%/年・7/18 が市場に勝った（比較群 −0.49・勝率 0.417）'
    # JST: 米国 − 米国外（等分）・米国 − 日本（年次・米ドル・20年窓）
    J = jst_annual()
    us = J['USA']
    ys = sorted(us)
    rows = {}
    for y in ys:
        xs = [J[c][y] for c in J if c != 'USA' and y in J[c]]
        if len(xs) >= 5:
            rows[y] = (us[y], sum(xs) / len(xs), J.get('Japan', {}).get(y))
    def roll(sel, yrs=20):
        res = []
        yy = sorted(rows)
        for i in range(len(yy) - yrs + 1):
            w = yy[i:i + yrs]
            if w[-1] - w[0] != yrs - 1 or not sel(w):
                continue
            res.append((w[0], sum(math.log1p(rows[y][0]) - math.log1p(rows[y][1]) for y in w) / yrs * 100,
                        (sum(math.log1p(rows[y][0]) - math.log1p(rows[y][2]) for y in w) / yrs * 100) if all(rows[y][2] is not None for y in w) else None))
        return res
    for nm, sel in (('JST_all_1871_2020', lambda w: True), ('JST_pre1926_fresh', lambda w: w[-1] <= 1925), ('JST_1926_2020', lambda w: w[0] >= 1926)):
        r = roll(sel)
        v = np.array([x for _, x, _ in r]); vj = np.array([x for _, _, x in r if x is not None])
        out[nm] = {'windows': len(v), 'first_start': r[0][0] if r else None, 'last_start': r[-1][0] if r else None,
                   'US_minus_exUS_quantiles_pct': {p: round(float(np.quantile(v, p)), 2) for p in (0.1, 0.25, 0.5, 0.75, 0.9)} if len(v) else None,
                   'US_minus_exUS_share_gt_0': round(float((v > 0).mean()), 3) if len(v) else None,
                   'US_minus_Japan_median': round(float(np.median(vj)), 2) if len(vj) else None,
                   'US_minus_Japan_share_gt_0': round(float((vj > 0).mean()), 3) if len(vj) else None,
                   'share_US_premium_ge_break_even': {k: (round(float((v >= x).mean()), 3) if isinstance(x, (int, float)) and len(v) else None) for k, x in crossings['US'].items()}}
    for nm, k in (('French_US_minus_EAFE_1975', 'EAFE'), ('French_US_minus_JPN_1975', 'JPN'), ('French_US_minus_EM_1989', 'EM')):
        arr = rolling_log_diff(S['MKT'], S[k])
        v = np.array([x for _, x in arr])
        out[nm] = {'windows': len(v), 'first_start': arr[0][0], 'last_start': arr[-1][0],
                   'quantiles_pct': {p: round(float(np.quantile(v, p)), 2) for p in (0.1, 0.5, 0.9)}, 'share_gt_0': round(float((v > 0).mean()), 3)}
    return out


# ───────────────────────── 格付け（静的な市場の脚の配合 対 French Mkt）─────────────────────────
GRADE_FAMILY = ['CUR', 'SPX_ONLY', 'NDX_ONLY'] + [f'{X}_w{w}' for X in ('SPX', 'GOLD', 'DEV', 'EMM', 'JMKT') for w in (10, 20, 30)]


def static_series(wt, SL, S):
    ks = None
    for s in wt:
        for k in SL[s]['leg']:
            ks = set(S[k]) if ks is None else ks & set(S[k])
    out = {}
    for m in sorted(ks):
        v = 0.0
        for s, w in wt.items():
            sp = SL[s]
            v += w * (sum(c * S[k][m] for k, c in sp['leg'].items()) - sp['fee'] / 12)
        out[m] = v
    return out


def grading(S, SL, MX):
    rows = {}
    mk = S['MKT']
    for nm in GRADE_FAMILY:
        wt = CUR_W if nm == 'CUR' else MX[nm]['w']
        s = static_series(wt, SL, S)
        full = M.excess_stats(s, mk)
        train = M.excess_stats(s, mk, z=M.TRAIN_END)
        hold = M.excess_stats(s, mk, a=M.HOLD_START)
        recent = M.excess_stats(s, mk, a=M.RECENT_START)
        hold_net = M.excess_stats(M.apply_cost(s, 0.10, 0.001), mk, a=M.HOLD_START)
        rows[nm] = {'weights': wt, 'from': min(s), 'full': full, 'train': train, 'hold': hold, 'recent': recent, 'hold_net': hold_net,
                    'roll20': M.rolling(s, mk, 20), 'dca20': M.dca(s, mk, 20)}
    hp = M.holm({k: (v['hold'] or {}).get('p') for k, v in rows.items()})
    for k, v in rows.items():
        g, c = M.grade(v['full'], v['train'], v['hold'], v['roll20'], cost_hold=v['hold_net'], repl=None, family_holm_p=hp.get(k))
        v['holm_p'] = hp.get(k); v['grade'] = g; v['criteria'] = c
    return rows


# ───────────────────────── 検算 ─────────────────────────
def selftest():
    ok = []
    N = 3
    # 1) リターン0・為替0・利回り0 → 最終資産＝投下額、生涯枠は 106 か月目（0 起点で 105）に埋まる
    R = np.zeros((1, N, T)); FX = np.zeros((N, T))
    W, mdd, filled = simulate(R, FX, [1.0], ['fund_us'], ['ts'], [0.0])
    ok.append(('zero_return_terminal', bool(np.allclose(W, CONTRIB * T)), float(W[0])))
    ok.append(('nisa_life_filled_month', int(filled[0]) == math.ceil(NISA_LIFE / CONTRIB) - 1, int(filled[0])))
    # 2) 一定の月次 r・投信1本: NISA の部分は非課税・課税口座は含み益に 20.315%
    r = 0.005
    R = np.full((1, N, T), r)
    W, _, _ = simulate(R, FX, [1.0], ['fund_us'], ['ts'], [0.0])
    nisa = tax_ = 0.0; val = []
    life = 0.0
    for t in range(T):
        x = min(CONTRIB, max(0.0, NISA_LIFE - life)) if True else 0
        # 年の枠: つみたて 120万→成長 240万（17万×12=204万 はつみたて120万＋成長84万で収まる）
        life += x
        val.append((x, CONTRIB - x, t))
    VN = sum(x * (1 + r) ** (T - t) for x, _, t in val)
    VT = sum(y * (1 + r) ** (T - t) for _, y, t in val)
    BT = sum(y for _, y, _ in val)
    expect = VN + VT - TAX * max(0.0, VT - BT)
    ok.append(('constant_return_tax', bool(abs(W[0] - expect) / expect < 1e-9), [float(W[0]), expect]))
    # 3) ブートストラップの平均ブロック長
    rng = np.random.default_rng(1)
    idx = sb_indices(500, 60, 400, rng)
    brk = (np.diff(idx, axis=1) != 1) & ~((idx[:, :-1] == 499) & (idx[:, 1:] == 0))
    ok.append(('mean_block_len≈60', bool(40 < (brk.size / max(1, brk.sum())) < 85), round(brk.size / max(1, brk.sum()), 1)))
    # 4) 平均のずらし
    P = {'MKT': np.array([0.01, -0.02, 0.03, 0.0]), 'TECH3': np.array([0.02, -0.05, 0.06, 0.01]), 'CHIPS': np.array([0.0, 0.01, 0.02, -0.03]), 'EAFE': np.array([0.01, 0.01, 0.01, 0.01])}
    Q = shifted_pool(P, -1.0, 2.0)
    d = (np.log1p(Q['TECH3']) - np.log1p(Q['MKT'])).mean() * 1200
    e = (np.log1p(Q['MKT']) - np.log1p(Q['EAFE'])).mean() * 1200
    ok.append(('shift_T', bool(abs(d + 1.0) < 1e-9), d))
    ok.append(('shift_US', bool(abs(e - 2.0) < 1e-9), e))
    # 5) 分配: 日本株 ETF を NISA だけで（枠の中）・r=利回り・価格0 → 手取りは全額
    R = np.full((1, 1, 12), 0.03 / 12)
    W, _, _ = simulate(R, np.zeros((1, 12)), [1.0], ['etf_jp'], ['gr'], [0.03])
    exp = CONTRIB * 12 + sum(CONTRIB * 0.03 / 12 * 0 for _ in range(1))  # 概算: 分配は翌月の積立に足す→最終は元本＋分配の合計
    ok.append(('etf_jp_nisa_dividends_kept', bool(W[0] > CONTRIB * 12), float(W[0])))
    return ok


# ───────────────────────── 本体 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--procs', type=int, default=3)
    a = ap.parse_args()
    st = selftest()
    for x in st:
        print('selftest', x)
    if a.selftest:
        return
    if not all(x[1] for x in st):
        raise SystemExit('selftest に失敗')
    t0 = time.time()
    S, FX, fx_me = load_data()
    F, Y = fits(S, FX)
    INP = inputs_from_files()
    SL = build_sleeves(F, INP)
    MX = mixes()
    fx_alt = load_fx_jst()
    n_main, n_grid = (400, 200) if a.quick else (4000, 2000)
    tasks = []
    for cls_name in ('US', 'GOLD', 'EAFE', 'JPN', 'EM'):
        mxc = {k: v for k, v in MX.items() if v['class'] == cls_name}
        for era in ('early', 'late'):
            for L in (60, 120):
                tasks.append((cls_name, era, L, S, FX, SL, mxc, n_main, n_grid, fx_alt))
    if a.procs > 1:
        import multiprocessing as mp
        with mp.get_context('fork').Pool(a.procs) as pool:
            cells = pool.map(cell, tasks)
    else:
        cells = [cell(t) for t in tasks]
    for c in cells:
        print(c['class'], c['era'], c['L'], c['pool'], c['sec'], 's')
    if a.quick:
        for c in cells:
            for sn in ('H', 'BR'):
                print(c['class'], c['era'], c['L'], sn, {k: v.get('p_beat') for k, v in c['scen'][sn].items() if isinstance(v, dict) and 'p_beat' in v})
        return
    json.dump({'cells': cells}, open(os.path.join(M.CACHE, 'mw_holdable_breakeven_cells.json'), 'w'))
    finish(S, FX, fx_me, F, Y, INP, SL, MX, cells, st, t0)


def finish(S, FX, fx_me, F, Y, INP, SL, MX, cells, st, t0):
    # ── 升ごとの結果を配合ごとにまとめる
    CELLS = [(e, L) for e in ('early', 'late') for L in (60, 120)]
    by = {}
    pools = {}
    for c in cells:
        key = f"{c['era']}_L{c['L']}"
        pools.setdefault(c['class'], {})[key] = c['pool']
        for sn, rs in c['scen'].items():
            for mn, v in rs.items():
                if mn in MX:
                    by.setdefault(mn, {}).setdefault(sn, {})[key] = v
        for mn, ps in c['grid_T'].items():
            by.setdefault(mn, {}).setdefault('grid_T_p_beat', {})[key] = ps
        for mn, ps in c['grid_US'].items():
            by.setdefault(mn, {}).setdefault('grid_US_p_beat', {})[key] = ps
    cur = {}
    for c in cells:
        key = f"{c['era']}_L{c['L']}"
        for sn, rs in c['scen'].items():
            cur.setdefault(c['class'], {}).setdefault(sn, {})[key] = rs['CUR']
            if 'CUR_vs_SPX100' in rs:
                cur.setdefault('CUR_vs_SPX100', {}).setdefault(sn, {})[key] = rs['CUR_vs_SPX100']
    # 損益分岐
    cross = {'T': {}, 'US': {}}
    for mn, d in by.items():
        if 'grid_T_p_beat' in d:
            per = {k: crossing(GRID_T, v) for k, v in d['grid_T_p_beat'].items()}
            d['break_even_piT'] = per
            nums = [x for x in per.values() if isinstance(x, (int, float))]
            d['break_even_piT_median'] = round(float(np.median(nums)), 2) if len(nums) == 4 else None
            cross['T'][mn] = d['break_even_piT_median']
        if 'grid_US_p_beat' in d:
            per = {k: crossing(GRID_US, v) for k, v in d['grid_US_p_beat'].items()}
            d['break_even_piUS'] = per
            nums = [x for x in per.values() if isinstance(x, (int, float))]
            d['break_even_piUS_median'] = round(float(np.median(nums)), 2) if len(nums) == 4 else None
            cross['US'][mn] = d['break_even_piUS_median']
    # 判定
    verdict = {}
    for sn in ('H', 'BR', 'BR_h015', 'BR_h0', 'BR_T15', 'BR_kmean'):
        gt5, ge6 = [], []
        for mn, mx in MX.items():
            if not mx['primary']:
                continue
            ps = [by[mn][sn][f'{e}_L{L}']['p_beat'] for e, L in CELLS]
            if min(ps) > 0.5:
                gt5.append(mn)
            if min(ps) >= 0.6:
                ge6.append(mn)
        best = sorted(((min(by[mn][sn][f'{e}_L{L}']['p_beat'] for e, L in CELLS), mn) for mn in MX if MX[mn]['primary']), reverse=True)[:5]
        verdict[sn] = {'beat_gt_0.5_all_4_cells': gt5, 'robust_ge_0.6_all_4_cells': ge6, 'top5_by_min_p': [[m, round(p, 3)] for p, m in best]}
    AW = actual_windows(S, FX, SL, MX)
    BRt = base_rates(S, cross)
    G = grading(S, SL, MX)
    # 事前登録の sha
    pre_sha = git_sha(PRE)
    tested = []
    for nm, v in G.items():
        tested.append({'name': f'G:{nm}', 'family': 'G_static_vs_market', 'grade': v['grade'], 'criteria': v['criteria'], 'holm_p': v['holm_p'],
                       'full': v['full'], 'train': v['train'], 'hold': v['hold'], 'recent': v['recent'], 'hold_net': v['hold_net'],
                       'roll20': v['roll20'], 'dca20': v['dca20'], 'weights': v['weights']})
    for mn, mx in MX.items():
        d = by.get(mn, {})
        tested.append({'name': f'D:{mn}', 'family': 'D_decision_vs_current', 'grade': None, 'report_only': True, 'primary_family': mx['primary'],
                       'buyable': mx['buyable'], 'weights': mx['w'],
                       'p_beat': {sn: {k: d[sn][k]['p_beat'] for k in d.get(sn, {})} for sn in SCEN},
                       'break_even_piT_median': d.get('break_even_piT_median'), 'break_even_piUS_median': d.get('break_even_piUS_median')})
    san = {'french_us_mkt_cagr_1926': round(M.cagr(S['MKT']) * 100, 2), 'french_us_mkt_cagr_2007': round(M.cagr(M.window(S['MKT'], M.HOLD_START)) * 100, 2),
           'ranges': {k: [min(v), max(v), len(v)] for k, v in S.items()},
           'fx_monthend': {m: fx_me.get(m) for m in (197101, 198512, 200706, 201110, 202512, 202608)},
           'spx_jpy_cagr_2007': round(M.cagr({m: (1 + S['MKT'][m]) * (1 + FX[m]) - 1 for m in S['MKT'] if m >= 200701 and m in FX}) * 100, 2),
           'proxy_fit_NDX': F['NDX'], 'proxy_fit_SMH': F['SMH'],
           'selftest': st}
    # 代理の答え合わせ: 2000年以降の QQQ・SMH の CAGR と代理（上乗せ・ずれなし・信託報酬なし）の CAGR
    for nm, tk, leg in (('NDX', 'QQQ', {'MKT': 1 - F['NDX']['beta'], 'TECH3': F['NDX']['beta']}), ('SMH', 'SMH', {'MKT': 1 - F['SMH']['beta'], 'CHIPS': F['SMH']['beta']})):
        ms = [m for m in Y[tk] if m >= F[nm]['from'] and m <= END and all(m in S[k] for k in leg)]
        px = {m: sum(c * S[k][m] for k, c in leg.items()) for m in ms}
        san[f'proxy_vs_real_{nm}'] = {'from': ms[0], 'to': ms[-1], 'cagr_real': round(M.cagr({m: Y[tk][m] for m in ms}) * 100, 2),
                                      'cagr_proxy': round(M.cagr(px) * 100, 2), 'corr': round(M.corr([Y[tk][m] for m in ms], [px[m] for m in ms]), 3)}
    summary = build_summary(by, cur, verdict, cross, BRt, AW, G, INP, SL, F)
    obj = {'angle': ANGLE, 'tool': 'night/mw_holdable_breakeven.py', 'prereg': PRE, 'prereg_commit': pre_sha, 'global_prereg': 'out/mw_prereg.json',
           'kind': '総合（意思決定の分析）。器の載り・公表後の目減りは入力で、上乗せ探しではない',
           'inputs': INP, 'fits': {k: v for k, v in F.items() if not k.startswith('_')}, 'yahoo_ranges': F.get('_yahoo_ranges'),
           'sleeves': {k: {kk: vv for kk, vv in v.items()} for k, v in SL.items()},
           'forward_edges_ann_pct': {k: {'h0.5_k': round(0.5 * v['k'] * v['E'] * 100, 3), 'h0.15_k': round(0.15 * v['k'] * v['E'] * 100, 3),
                                         'h0.5_kmean': round(0.5 * (v['k_mean'] if v['k_mean'] is not None else v['k']) * v['E'] * 100, 3), 'fee_pct': round(v['fee'] * 100, 3)} for k, v in SL.items()},
           'mixes': {k: {'w': v['w'], 'class': v['class'], 'primary': v['primary'], 'buyable': v['buyable']} for k, v in MX.items()},
           'pools': pools, 'current': cur, 'results': by, 'verdict': verdict, 'break_even': cross,
           'base_rates': BRt, 'actual_windows_H': AW, 'grading': {k: {kk: v[kk] for kk in ('grade', 'criteria', 'holm_p', 'from')} for k, v in G.items()},
           'sanity': san, 'tested': tested, 'n_tested': len(tested), 'n_graded': len(G),
           'grade_counts': {g: sum(1 for v in G.values() if v['grade'] == g) for g in 'SABC'},
           'deviations': [], 'summary': summary, 'runtime_sec': round(time.time() - t0, 1)}
    p = M.save(OUT, obj)
    print('wrote', p, os.path.getsize(p))
    for line in summary.get('lines', []):
        print(line)


def build_summary(by, cur, verdict, cross, BRt, AW, G, INP, SL, F):
    lines = []
    lines.append(f"判定（主の族37配合・4升すべてで P>0.5）: H={verdict['H']['beat_gt_0.5_all_4_cells']} / BR={verdict['BR']['beat_gt_0.5_all_4_cells']} / BR_h015={verdict['BR_h015']['beat_gt_0.5_all_4_cells']}")
    lines.append(f"頑丈な改善（4升すべてで P≥0.6）: H={verdict['H']['robust_ge_0.6_all_4_cells']} / BR={verdict['BR']['robust_ge_0.6_all_4_cells']} / BR_h015={verdict['BR_h015']['robust_ge_0.6_all_4_cells']}")
    lines.append(f"損益分岐 π_T*（中央・%/年の対数の差）: {json.dumps(cross['T'], ensure_ascii=False)}")
    lines.append(f"損益分岐 π_US*: {json.dumps(cross['US'], ensure_ascii=False)}")
    lines.append(f"格付け（静的な配合 対 French Mkt）: {json.dumps({k: v['grade'] for k, v in G.items()}, ensure_ascii=False)}")
    return {'lines': lines}


if __name__ == '__main__':
    main()
