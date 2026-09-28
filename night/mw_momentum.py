#!/usr/bin/env python3
"""night/mw_momentum.py — 『市場に勝てる歴史検証』角度: 勢い（momentum）（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」。
事前登録 out/mw_momentum_prereg.json（族 F1〜F8・規則・費用・C5 の単位）を**測る前に**コミットしてから回す。
線は out/mw_prereg.json（C1〜C8）を night/mw_common.grade でそのまま当てる。線は結果を見て動かさない。

  python3 night/mw_momentum.py            → out/mw_momentum.json
  python3 night/mw_momentum.py --selftest  → 重ね持ち（JT）の計算を合成データで検算するだけ（結果の数字は出さない）

約束（mw_common と同じ）: 月次リターンは小数・キーは yyyymm。欠測は0と読まない。French は総リターン、JKP は超過（RF を足して総リターンに揃える）。
"""
import sys, os, json, math, subprocess, statistics as S, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
PRE = 'mw_momentum_prereg.json'
OUT = 'mw_momentum.json'
YH_END = 202608          # Yahoo の 2026-09 は月の途中なので切る
TR, HS, RS = M.TRAIN_END, M.HOLD_START, M.RECENT_START
REG3 = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']                     # 独立の米国外の地域（French）
REG_ALL = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'North_America', 'Developed', 'Developed_ex_US']
JKP_UNITS = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'emerging']  # F5・F2(JKP) の C5 単位
GICS_UNITS = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che']          # 業種の C5 単位
DEV23 = ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe', 'usa']
EM14 = ['bra', 'chl', 'chn', 'ind', 'idn', 'kor', 'mex', 'mys', 'phl', 'pol', 'tha', 'tur', 'twn', 'zaf']
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── データ ─────────────────────────
def fr_vw(name, freq='monthly'):
    return M.french_series(name, 'Value Weight', freq)


def fr_table(name, want, freq='monthly'):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == freq:
            return v
    raise KeyError(f'{name}: {want}')


def region_mkt(R):
    """地域の Mkt（総リターン・ドル建て）= Mkt-RF + RF"""
    fname = 'Emerging_5_Factors' if R == 'Emerging' else f'{R}_3_Factors'
    for t, v in M.french_tables(fname).items():
        if v['freq'] == 'monthly':
            im, ir = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[im] + row[ir]) / 100 for d, row in v['data'].items() if row[im] is not None and row[ir] is not None}
    raise KeyError(fname)


def region_25(R):
    return fr_vw(f'{R}_25_Portfolios_ME_Prior_12_2')


def region_6(R):
    return fr_vw('Emerging_Markets_6_Portfolios_ME_Prior_12_2' if R == 'Emerging' else f'{R}_6_Portfolios_ME_Prior_12_2')


def col25(me, pr):
    names = ['SMALL LoPRIOR', 'ME1 PRIOR2', 'ME1 PRIOR3', 'ME1 PRIOR4', 'SMALL HiPRIOR', 'ME2 PRIOR1', 'ME2 PRIOR2', 'ME2 PRIOR3', 'ME2 PRIOR4', 'ME2 PRIOR5',
             'ME3 PRIOR1', 'ME3 PRIOR2', 'ME3 PRIOR3', 'ME3 PRIOR4', 'ME3 PRIOR5', 'ME4 PRIOR1', 'ME4 PRIOR2', 'ME4 PRIOR3', 'ME4 PRIOR4', 'ME4 PRIOR5',
             'BIG LoPRIOR', 'ME5 PRIOR2', 'ME5 PRIOR3', 'ME5 PRIOR4', 'BIG HiPRIOR']
    return names[(me - 1) * 5 + (pr - 1)]


def avg2(a, b):
    return {k: (a[k] + b[k]) / 2 for k in set(a) & set(b)}


def vw_top_quintile_25(R):
    """25分割（規模5×勢い5）の勢い第5列を規模5つにまたがって時価加重（重み = 前月の社数 × 平均時価総額＝後知恵なし）"""
    name = f'{R}_25_Portfolios_ME_Prior_12_2' if R != 'US' else '25_Portfolios_ME_Prior_12_2'
    ret = fr_vw(name)
    nf = fr_table(name, 'Number of Firms')
    try:
        sz = fr_table(name, 'Average Firm Size')
    except KeyError:
        sz = fr_table(name, 'Average Market Cap')
    cols = [col25(me, 5) for me in range(1, 6)]
    ms = sorted(set.intersection(*[set(ret[c]) for c in cols]))
    out, lagged = {}, 0
    prev = {}
    for d in sorted(nf['data']):
        prev[d] = d
    dn = sorted(nf['data'])
    lag = {dn[i]: dn[i - 1] for i in range(1, len(dn))}
    for m in ms:
        p = lag.get(m)
        if p is None:
            continue
        num = den = 0.0
        for c in cols:
            i = nf['cols'].index(c)
            n, s = nf['data'][p][i], sz['data'].get(p, [None] * 25)[sz['cols'].index(c)]
            if n is None or s is None or n <= 0 or s <= 0 or m not in ret[c]:
                continue
            w = n * s
            num += w * ret[c][m]; den += w
        if den > 0:
            out[m] = num / den
    return out


def jkp_rows_filtered(region, key, pf, weighting='vw', min_n=10):
    d = {}
    for x in M.jkp_rows(region, key, 'portfolios', weighting):
        if x['pf'] != pf or x['ret'] in ('', 'NA', 'na'):
            continue
        try:
            n = int(float(x['n']))
        except Exception:
            continue
        if n < min_n:
            continue
        d[M._ym(x['date'])] = float(x['ret'])
    return d


def jkp_industry(region, kind='gics', weighting='vw'):
    import zipfile, io, csv
    u = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{region}%5D_%5B{kind}%5D_%5Bmonthly%5D_%5B{weighting}%5D.zip'
    b = M.get(u, name=f'jkp_industry_{region}_{kind}_{weighting}_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        out.setdefault(x[kind], {})[M._ym(x['date'])] = float(x['ret'])
    return out


def add_rf(d, rf):
    return {k: v + rf[k] for k, v in d.items() if k in rf}


def yh(t):
    return {k: v for k, v in M.yahoo(t).items() if k <= YH_END}


# ───────────────────────── mw_common.excess_stats の高速版（出力は同一）─────────────────────────
def excess_stats(s, b, a=None, z=None, per_year=12, lag=12):
    """mw_common.excess_stats と同じ式・同じ丸め。違いは β の計算で S.mean を生成式の中で毎回呼ばない（元は O(n²) で1回3秒）だけ。
    mw_common は他の角度と共有なので触らず、ここで置き換える（deviations に記録）。自己検算は --selftest の equal_check"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < max(24, per_year * 2):
        return None
    ex = [s[k] - b[k] for k in ks]
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    te = S.stdev(ex) * math.sqrt(per_year)
    vb = S.pvariance(bv)
    ms, mb = S.mean(sv), S.mean(bv)
    beta = sum((x - ms) * (y - mb) for x, y in zip(sv, bv)) / len(ks) / vb if vb else None
    t = M.nw_t(ex, lag)
    g_s, g_b = M.cagr(sv, per_year), M.cagr(bv, per_year)
    return {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / per_year, 1),
            'ex_ann': round(S.mean(ex) * per_year * 100, 2), 't': round(t, 2) if t is not None else None,
            'p': round(M.p_two(t), 4) if t is not None else None,
            'cagr_s': round(g_s * 100, 2), 'cagr_b': round(g_b * 100, 2), 'cagr_diff': round((g_s - g_b) * 100, 2),
            'te': round(te * 100, 2), 'ir': round(S.mean(ex) * per_year / te, 2) if te else None,
            'beta': round(beta, 2) if beta is not None else None,
            'vol_s': round(S.stdev(sv) * math.sqrt(per_year) * 100, 1), 'vol_b': round(S.stdev(bv) * math.sqrt(per_year) * 100, 1)}


# ───────────────────────── 重ね持ち（Jegadeesh-Titman）─────────────────────────
def jt(R, L, skip, H, K, unit):
    """R: {名前: {yyyymm: 総リターン}}。月末 i に months[i-skip-L+1 .. i-skip] の累積で並べ上位 K を等分（組）、
    組は i+1..i+H の H か月持つ。各月の目標の重み = Σ_組 (1/H)(1/K)。組の中は毎月等分に戻す（JT の標準）。
    戻り値: (月次リターン, 月の費用, 情報)。費用 = ½Σ|w_目標 − w_流れた後| × unit（片道の回転 × 単価）。最初の月の買いは数えない"""
    months = sorted(set().union(*[set(v) for v in R.values()]))
    names = sorted(R)
    n = len(months)
    lr = {nm: [math.log1p(R[nm][m]) if m in R[nm] else None for m in months] for nm in names}
    ps = {}
    for nm in names:
        s = [0.0]; c = [0]
        for v in lr[nm]:
            s.append(s[-1] + (v or 0.0)); c.append(c[-1] + (0 if v is None else 1))
        ps[nm] = (s, c)
    coh = {}
    elig = []
    for i in range(n):
        lo, hi = i - skip - L + 1, i - skip
        if lo < 0:
            continue
        sc = []
        for nm in names:
            s, c = ps[nm]
            if c[hi + 1] - c[lo] == L:
                sc.append((-(s[hi + 1] - s[lo]), nm))
        if len(sc) >= K:
            sc.sort()
            coh[i] = [nm for _, nm in sc[:K]]
            elig.append(len(sc))
    ret, cost, turn = {}, {}, {}
    prev_w, prev_r = None, None
    miss = 0
    first = min(coh) if coh else None
    if first is None:
        return {}, {}, {'months': 0}
    for j in range(first + H, n):
        act = [coh.get(i) for i in range(j - H, j)]
        if any(a is None for a in act):
            prev_w = None
            continue
        m = months[j]
        w = {}
        for a in act:
            for nm in a:
                w[nm] = w.get(nm, 0.0) + 1.0 / (H * K)
        avail = {nm: x for nm, x in w.items() if m in R[nm]}
        if len(avail) < len(w):
            miss += len(w) - len(avail)
        tot = sum(avail.values())
        if tot <= 0:
            prev_w = None
            continue
        w2 = {nm: x / tot for nm, x in avail.items()}
        rp = sum(x * R[nm][m] for nm, x in w2.items())
        if prev_w is not None:
            drift = {nm: x * (1 + prev_r[nm]) / (1 + prev_r['_p']) for nm, x in prev_w.items()}
            keys = set(drift) | set(w2)
            to = 0.5 * sum(abs(w2.get(k, 0.0) - drift.get(k, 0.0)) for k in keys)
        else:
            to = 0.0
        ret[m] = rp; turn[m] = to; cost[m] = to * unit
        prev_w = w2
        prev_r = {nm: R[nm][m] for nm in w2}; prev_r['_p'] = rp
    yrs = len(turn) / 12 if turn else 0
    return ret, cost, {'months': len(ret), 'from': min(ret) if ret else None, 'to': max(ret) if ret else None,
                       'oneway_turnover_per_year': round(sum(turn.values()) / yrs, 3) if yrs else None, 'missing_member_months': miss,
                       'eligible_median': S.median(elig) if elig else None}


def ew_rank_portfolio(R, L, skip, frac, unit, ceil_frac=True):
    """国の勢い: 月末 i に L か月（skip 飛ばし）の累積で並べ、上位 ceil(frac×適格数) を等分、翌月1か月持つ（毎月組替え）"""
    months = sorted(set().union(*[set(v) for v in R.values()]))
    ret, cost, turn = {}, {}, {}
    prev_w, prev_r = None, None
    cnt = []
    for j in range(len(months) - 1):
        i = j
        lo, hi = i - skip - L + 1, i - skip
        if lo < 0:
            continue
        ms = months[lo:hi + 1]
        sc = []
        for nm, r in R.items():
            if all(m in r for m in ms):
                sc.append((-math.fsum(math.log1p(r[m]) for m in ms), nm))
        if len(sc) < 3:
            prev_w = None
            continue
        sc.sort()
        k = math.ceil(frac * len(sc)) if ceil_frac else max(1, round(frac * len(sc)))
        sel = [nm for _, nm in sc[:k]]
        m = months[j + 1]
        avail = [nm for nm in sel if m in R[nm]]
        if not avail:
            prev_w = None
            continue
        w2 = {nm: 1 / len(avail) for nm in avail}
        rp = sum(R[nm][m] for nm in avail) / len(avail)
        if prev_w is not None:
            drift = {nm: x * (1 + prev_r[nm]) / (1 + prev_r['_p']) for nm, x in prev_w.items()}
            to = 0.5 * sum(abs(w2.get(q, 0.0) - drift.get(q, 0.0)) for q in set(drift) | set(w2))
        else:
            to = 0.0
        ret[m] = rp; turn[m] = to; cost[m] = to * unit; cnt.append(len(sc))
        prev_w = w2; prev_r = {nm: R[nm][m] for nm in avail}; prev_r['_p'] = rp
    yrs = len(turn) / 12 if turn else 0
    return ret, cost, {'months': len(ret), 'oneway_turnover_per_year': round(sum(turn.values()) / yrs, 3) if yrs else None,
                       'eligible_median': S.median(cnt) if cnt else None}


def seas_rank(R, a, b, frac=None, K=None, third=False, unit=0.0005):
    """季節性: 月末 i に、翌月 m1 と同じ暦月の a〜b 年前（m1−100y）のリターンの平均で並べる（その年数ぶん全部そろう名前だけ）。
    上位 K（または上位 1/3 切り上げ）を等分で翌月1か月持つ。後知恵なし: 1年前の同じ月 = m1−12か月 ≤ t"""
    months = sorted(set().union(*[set(v) for v in R.values()]))
    ret, cost, turn, elig = {}, {}, {}, []
    prev_w, prev_r = None, None
    for i in range(len(months) - 1):
        m1 = months[i + 1]
        sc = []
        for nm, r in R.items():
            vals = [r.get(m1 - 100 * y) for y in range(a, b + 1)]
            if all(v is not None for v in vals) and m1 - 100 * a <= months[i]:
                sc.append((-sum(vals) / len(vals), nm))
        k = (math.ceil(len(sc) / 3) if third else K)
        if not sc or k is None or len(sc) < max(k, 2):
            prev_w = None
            continue
        sc.sort()
        sel = [nm for _, nm in sc[:k]]
        avail = [nm for nm in sel if m1 in R[nm]]
        if not avail:
            prev_w = None
            continue
        w2 = {nm: 1 / len(avail) for nm in avail}
        rp = sum(R[nm][m1] for nm in avail) / len(avail)
        if prev_w is not None:
            drift = {nm: x * (1 + prev_r[nm]) / (1 + prev_r['_p']) for nm, x in prev_w.items()}
            to = 0.5 * sum(abs(w2.get(q, 0.0) - drift.get(q, 0.0)) for q in set(drift) | set(w2))
        else:
            to = 0.0
        ret[m1] = rp; turn[m1] = to; cost[m1] = to * unit; elig.append(len(sc))
        prev_w = w2; prev_r = {nm: R[nm][m1] for nm in avail}; prev_r['_p'] = rp
    yrs = len(turn) / 12 if turn else 0
    return ret, cost, {'months': len(ret), 'from': min(ret) if ret else None, 'oneway_turnover_per_year': round(sum(turn.values()) / yrs, 3) if yrs else None,
                       'eligible_median': S.median(elig) if elig else None}


def kof(frac, N):
    return max(2, int(math.floor(frac * N + 0.5)))


# ───────────────────────── 評価 ─────────────────────────
TESTED = []
SERIES = {}  # id → (s, b)（メモリの中だけ・診断用）


def evaluate(sid, fam, label, s, b, *, rule='', cost=None, turnover=None, unit=None, rf=None, repl=None, pub=None,
             timing=False, primary=False, extra=None, compact=False):
    """s・b は総リターン（同じ基準）。cost は {月: 費用}（正確な回転から）か、turnover/unit（年の片道回転×単価）"""
    ks = sorted(set(s) & set(b))
    s = {k: s[k] for k in ks}; b = {k: b[k] for k in ks}
    SERIES[sid] = (s, b)
    if cost is not None:
        net = {k: s[k] - cost.get(k, 0.0) for k in ks}
        stress = {k: s[k] - 3.0 * cost.get(k, 0.0) for k in ks}
        ann_cost = round(S.mean([cost.get(k, 0.0) for k in ks]) * 12 * 100, 3) if ks else None
    else:
        net = M.apply_cost(s, turnover, unit)
        stress = M.apply_cost(s, turnover * 1.5, unit * 2)
        ann_cost = round(turnover * unit * 100, 3)
    e = {'id': sid, 'family': fam, 'label': label, 'primary': primary, 'rule': rule, 'annual_cost_pct': ann_cost}
    e['full'] = excess_stats(s, b)
    e['train'] = excess_stats(s, b, z=TR)
    e['hold'] = excess_stats(s, b, a=HS)
    e['recent'] = excess_stats(s, b, a=RS)
    e['cost_hold'] = excess_stats(net, b, a=HS)
    e['cost_full'] = excess_stats(net, b)
    e['stress_cost_hold'] = excess_stats(stress, b, a=HS)
    e['roll20'] = M.rolling(s, b, 20)
    e['dca20'] = M.dca(s, b, 20)
    if not compact:
        e['cost_train'] = excess_stats(net, b, z=TR)
        e['roll20_net'] = M.rolling(net, b, 20)
        e['roll10'] = M.rolling(s, b, 10)
        e['dca20_net'] = M.dca(net, b, 20)
        e['maxdd_s'] = round(M.maxdd(s) * 100, 1) if s else None
        e['maxdd_b'] = round(M.maxdd(b) * 100, 1) if b else None
        e['maxdd_s_hold'] = round(M.maxdd(M.window(s, HS)) * 100, 1) if M.window(s, HS) else None
        e['maxdd_b_hold'] = round(M.maxdd(M.window(b, HS)) * 100, 1) if M.window(b, HS) else None
    if pub:
        e['postpub'] = {'from_year': pub + 1, 'stats': excess_stats(s, b, a=(pub + 1) * 100 + 1)}
    e['repl'] = repl
    if timing:
        e['sharpe_pair'] = {'train': (M.sharpe(net, rf, z=TR), M.sharpe(b, rf, z=TR)),
                            'hold': (M.sharpe(net, rf, a=HS), M.sharpe(b, rf, a=HS))}
    e['timing'] = timing
    if extra:
        e.update(extra)
    h = e['hold']
    e['hold_p_for_holm'] = (h['p'] if (h and h['t'] is not None and h['t'] > 0 and h['p'] is not None) else 1.0)
    TESTED.append(e)
    return e


def repl_summary(units):
    """units: {単位名: excess_stats（全期間）/ None}。正 = 全期間の算術の超過 > 0"""
    u = {k: v for k, v in units.items() if v}
    return {'regions': len(u), 'positive': sum(1 for v in u.values() if v['ex_ann'] > 0),
            'positive_hold': sum(1 for v in u.values() if v.get('_hold') and v['_hold']['ex_ann'] > 0),
            'detail': {k: {'full_ex': v['ex_ann'], 'full_t': v['t'], 'from': v['from'], 'to': v['to'],
                           'hold_ex': v['_hold']['ex_ann'] if v.get('_hold') else None, 'hold_t': v['_hold']['t'] if v.get('_hold') else None}
                       for k, v in u.items()},
            'missing_units': [k for k, v in units.items() if not v]}


def unit_stats(s, b):
    f = excess_stats(s, b)
    if f:
        f = dict(f); f['_hold'] = excess_stats(s, b, a=HS)
    return f


def finalize(families):
    """族ごとに Holm → 格付け"""
    fam_holm = {}
    for fam in families:
        ps = {e['id']: e['hold_p_for_holm'] for e in TESTED if fam in (e['family'] if isinstance(e['family'], list) else [e['family']])}
        fam_holm[fam] = M.holm(ps)
    for e in TESTED:
        fams = e['family'] if isinstance(e['family'], list) else [e['family']]
        e['holm_by_family'] = {f: fam_holm[f].get(e['id']) for f in fams if f in fam_holm}
        # 格付けに使う族 = 先頭の族（事前登録の主な所属）
        hp = e['holm_by_family'].get(fams[0])
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=e['repl'],
                       family_holm_p=hp, sharpe_pair=e.get('sharpe_pair'), leveraged_or_timing=e['timing'])
        # 全体の事前登録の『訓練期間は最低15年』を当てる（第3次の事前登録で明記・厳しくする方向のみ）
        if not e['train'] or e['train']['years'] < 15:
            e['grade_without_15y_rule'] = g
            g, c = M.grade(e['full'], None, e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=e['repl'],
                           family_holm_p=hp, sharpe_pair=e.get('sharpe_pair'), leveraged_or_timing=e['timing'])
            c['C1_note'] = '訓練期間が15年未満（または無い）ので C1 は不合格'
        e['grade'], e['criteria'] = g, c
        if e.get('posthoc'):
            e['grade'], e['criteria_info_only'], e['criteria'] = '事後（格付けなし）', c, None
    return fam_holm


# ───────────────────────── 自己検算 ─────────────────────────
def selftest():
    import random
    random.seed(1)
    months = [y * 100 + m for y in range(2000, 2004) for m in range(1, 13)]
    R = {f'I{i}': {m: random.gauss(0.01, 0.05) for m in months} for i in range(6)}
    # K=N・H=1 なら等分の平均と一致するはず
    r, c, info = jt(R, 1, 0, 1, 6, 0.0005)
    for m in r:
        ew = sum(R[k][m] for k in R) / 6
        assert abs(r[m] - ew) < 1e-12, (m, r[m], ew)
    # 一つの業種だけ常に最大 → K=1 なら常にそれを持ち、回転は0
    R2 = {k: dict(v) for k, v in R.items()}
    for m in months:
        R2['I0'][m] = 0.5
    r2, c2, i2 = jt(R2, 3, 0, 1, 1, 0.0005)
    assert all(abs(r2[m] - 0.5) < 1e-12 for m in r2) and all(abs(v) < 1e-12 for v in c2.values()), '固定の勝者で回転が0にならない'
    # 後知恵の検問: 月 i の組は i+1 から持つ。当月に大きく上がった業種を当月に持っていないこと
    R3 = {'A': {m: 0.0 for m in months}, 'B': {m: 0.001 for m in months}}
    R3['A'][months[10]] = 1.0   # A が 10番目の月だけ +100%（ふだんは B が上）
    r3, _, _ = jt(R3, 1, 0, 1, 1, 0.0)
    assert abs(r3[months[10]] - 0.001) < 1e-12 and r3.get(months[11]) == 0.0, '当月の値上がりを当月に取っている（後知恵）'
    # H=2 の重ね持ち: 各月の重みの合計が1
    r4, c4, i4 = jt(R, 3, 0, 2, 2, 0.0005)
    assert i4['months'] > 0
    xs = {m: random.gauss(0.01, 0.05) for m in months}; ys = {m: random.gauss(0.008, 0.04) for m in months}
    assert excess_stats(xs, ys) == M.excess_stats(xs, ys) and excess_stats(xs, ys, a=200201) == M.excess_stats(xs, ys, a=200201), 'excess_stats の高速版が mw_common と一致しない'
    # 季節性の後知恵の検問: 各年の同じ月だけ A が上がる → 翌年の同じ月に A を持つ。当年の値を使っていないこと
    months5 = [y * 100 + m for y in range(2000, 2006) for m in range(1, 13)]
    R5 = {'A': {m: (0.10 if m % 100 == 3 else 0.0) for m in months5}, 'B': {m: 0.001 for m in months5}}
    R5['A'][200003] = 0.0   # 2000年3月は上がらない → 2001年3月は B を持つはず（2000年3月の値だけが根拠）
    r5, _, _ = seas_rank(R5, 1, 1, K=1, unit=0.0)
    assert abs(r5[200103] - 0.001) < 1e-12 and abs(r5[200203] - 0.10) < 1e-12, ('季節性の窓がずれている', r5.get(200103), r5.get(200203))
    print('selftest OK', info, i2, i4)


# ───────────────────────── 本体 ─────────────────────────
def main():
    sha = subprocess.run(['git', 'log', '-1', '--format=%H', '--', f'out/{PRE}'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    ff = M.ff_factors()
    MKT, RF = ff['mkt'], ff['rf']
    sanity = {}
    sanity['us_mkt_cagr_full'] = round(M.cagr(MKT) * 100, 2)
    sanity['us_mkt_cagr_2007'] = round(M.cagr(M.window(MKT, HS)) * 100, 2)
    sanity['us_mkt_range'] = [min(MKT), max(MKT)]
    log('sanity US Mkt CAGR', sanity['us_mkt_cagr_full'], '2007〜', sanity['us_mkt_cagr_2007'])
    jk_us = M.jkp_mkt('usa', 'vw')
    both = sorted(set(jk_us) & set(MKT))
    sanity['jkp_usa_vw_plus_rf_minus_french_mkt_ann'] = round(S.mean(jk_us[k] + RF[k] - MKT[k] for k in both if k in RF) * 1200, 3)
    log('sanity JKP usa mkt vw + RF − French Mkt (年率%)', sanity['jkp_usa_vw_plus_rf_minus_french_mkt_ann'])

    # ─ F1 主: 米国の株の勢い ─
    d10 = fr_vw('10_Portfolios_Prior_12_2')
    d6 = fr_vw('6_Portfolios_ME_Prior_12_2')
    d25 = fr_vw('25_Portfolios_ME_Prior_12_2')
    us = {'F1a1_us_top_decile': (d10['Hi PRIOR'], 4.0, 0.002, '10分割 Hi PRIOR（12-2 の上位10%・時価加重）'),
          'F1a2_us_big_winners': (d6['BIG HiPRIOR'], 2.5, 0.001, '6分割 BIG HiPRIOR（大型の勢い上位30%）'),
          'F1a3_us_me5_prior5': (d25[col25(5, 5)], 3.0, 0.001, '25分割 ME5 PRIOR5（規模上位20%×勢い上位20%）'),
          'F1a4_us_me45_prior5': (avg2(d25[col25(4, 5)], d25[col25(5, 5)]), 3.0, 0.0015, '25分割 ME4・ME5 の PRIOR5 の等分')}
    # C5 の地域
    rmk = {R: region_mkt(R) for R in REG_ALL + ['Emerging']}
    r25 = {R: region_25(R) for R in REG_ALL}
    r6 = {R: region_6(R) for R in REG_ALL + ['Emerging']}
    rep = {
        'F1a1_us_top_decile': repl_summary({R: unit_stats(vw_top_quintile_25(R), rmk[R]) for R in REG3}),
        'F1a2_us_big_winners': repl_summary({R: unit_stats(r6[R]['BIG HiPRIOR'], rmk[R]) for R in REG3 + ['Emerging']}),
        'F1a3_us_me5_prior5': repl_summary({R: unit_stats(r25[R][col25(5, 5)], rmk[R]) for R in REG3}),
        'F1a4_us_me45_prior5': repl_summary({R: unit_stats(avg2(r25[R][col25(4, 5)], r25[R][col25(5, 5)]), rmk[R]) for R in REG3}),
    }
    for sid, (s, to, u, lab) in us.items():
        e = evaluate(sid, 'F1', lab, s, MKT, rule=lab, turnover=to, unit=u, repl=rep[sid], pub=1993, primary=True)
        log(sid, 'done')

    # 業種（米国 French）
    IND = {N: fr_vw(f'{N}_Industry_Portfolios') for N in (49, 30, 17, 12, 10)}
    # JKP の国別 GICS（業種の C5 単位）: 超過 → RF を足して総リターン
    GICS = {}
    for c in GICS_UNITS + ['usa']:
        g = jkp_industry(c)
        GICS[c] = {k: add_rf(v, RF) for k, v in g.items()}
    CMKT = {c: add_rf(M.jkp_mkt(c, 'vw'), RF) for c in set(GICS_UNITS + DEV23 + EM14 + ['emerging', 'developed', 'world', 'world_ex_us', 'usa'])}
    # sanity: JKP ff49 と French 49 業種（1963〜・同じ番号の業種）の差の中央値（JKP が超過なら ≈ −RF）
    try:
        jf = jkp_industry('usa', 'ff49')
        diffs, cors = [], []
        for i, c in enumerate(IND[49]):
            a, fa = jf.get(f'{i + 1}.0'), IND[49][c]
            if not a:
                continue
            ks = sorted(k for k in set(a) & set(fa) & set(RF) if k >= 196301)
            diffs.append(S.mean(a[k] - fa[k] for k in ks) * 1200)
            cors.append(M.corr([a[k] for k in ks], [fa[k] for k in ks]))
        sanity['jkp_ff49_minus_french49_median_ann'] = round(S.median(diffs), 3)
        sanity['jkp_ff49_vs_french49_median_corr'] = round(S.median(cors), 3)
        sanity['french_rf_ann_1963'] = round(S.mean(RF[k] for k in RF if k >= 196301) * 1200, 3)
        log('sanity JKP ff49 − French 49 (中央値・年率%)', sanity['jkp_ff49_minus_french49_median_ann'], 'RF', sanity['french_rf_ann_1963'], 'corr', sanity['jkp_ff49_vs_french49_median_corr'])
    except Exception as ex:  # noqa
        sanity['jkp_ff49_check_error'] = str(ex)

    FORMS = {'1-0': (1, 0), '3-0': (3, 0), '6-0': (6, 0), '9-0': (9, 0), '12-0': (12, 0), '12-1': (11, 1)}
    HOLDS = (1, 3, 6, 12)
    FRACS = (0.15, 0.30)

    gics_cache = {}

    def gics_repl(fk, H, frac):
        key = (fk, H, frac)
        if key in gics_cache:
            return gics_cache[key]
        L, sk = FORMS[fk]
        units = {}
        for c in GICS_UNITS:
            r, cst, info = jt(GICS[c], L, sk, H, kof(frac, 11), 0.0005)
            units[c] = unit_stats(r, CMKT[c])
        gics_cache[key] = repl_summary(units)
        return gics_cache[key]

    grid = {}
    for N, R in IND.items():
        for fk, (L, sk) in FORMS.items():
            for H in HOLDS:
                for frac in FRACS:
                    K = kof(frac, N)
                    r, cst, info = jt(R, L, sk, H, K, 0.0005)
                    gid = f'F3g_ind{N}_{fk}_H{H}_K{int(frac * 100)}'
                    grid[gid] = (N, fk, H, frac, K, r, cst, info)
    log('grid built', len(grid))
    # F1b（主）= 6-0・H6・15%
    for N in (49, 30, 17, 12, 10):
        gid = f'F3g_ind{N}_6-0_H6_K15'
        (N_, fk, H, frac, K, r, cst, info) = grid[gid]
        lab = f'米国 {N}業種・MG 6-6・上位{K}（15%）・重ね持ち'
        evaluate(f'F1b_ind{N}', 'F1', lab, r, MKT, rule=lab, cost=cst, repl=gics_repl('6-0', 6, 0.15), pub=1999, primary=True,
                 extra={'jt_info': info, 'K': K})
    log('F1b done')
    # F3 グリッド（240）
    for gid, (N, fk, H, frac, K, r, cst, info) in grid.items():
        lab = f'米国 {N}業種・形成{fk}・保有{H}か月・上位{K}（{int(frac * 100)}%）'
        evaluate(gid, 'F3g', lab, r, MKT, rule=lab, cost=cst, repl=gics_repl(fk, H, frac), pub=1999, extra={'jt_info': info, 'K': K}, compact=True)
    log('F3 grid done')
    # F3s: 訓練期間だけで選ぶ（費用後の超過の NW t が最大）
    def train_t(gid):
        N, fk, H, frac, K, r, cst, info = grid[gid]
        net = {k: v - cst.get(k, 0.0) for k, v in r.items()}
        st = excess_stats(net, MKT, z=TR)
        return (st['t'] if st and st['t'] is not None else -99)
    sel = {}
    for N in (49, 30, 17, 12, 10):
        cands = [g for g in grid if grid[g][0] == N]
        best = max(cands, key=lambda g: (train_t(g), -cands.index(g)))
        sel[f'F3s_ind{N}_trainbest'] = best
    allbest = max(list(grid), key=lambda g: (train_t(g), -list(grid).index(g)))
    sel['F3s_all_trainbest'] = allbest
    for sid, gid in sel.items():
        N, fk, H, frac, K, r, cst, info = grid[gid]
        lab = f'訓練期間で選んだ規則: {N}業種・形成{fk}・保有{H}・上位{K}（選んだ元 {gid}・訓練の費用後 t={train_t(gid)}）'
        evaluate(sid, 'F3s', lab, r, MKT, rule=lab, cost=cst, repl=gics_repl(fk, H, frac), pub=1999,
                 extra={'jt_info': info, 'selected_from': gid, 'train_net_t_at_selection': train_t(gid)})
    log('F3s done', sel)

    # ─ F2 地域 ─
    rep_big = repl_summary({R: unit_stats(r6[R]['BIG HiPRIOR'], rmk[R]) for R in REG3 + ['Emerging']})
    rep_me5 = repl_summary({R: unit_stats(r25[R][col25(5, 5)], rmk[R]) for R in REG3})
    for R in REG_ALL + ['Emerging']:
        evaluate(f'F2_{R}_big_winners', 'F2', f'{R} 大型×勢い上位30%（6分割 BIG HiPRIOR）vs {R} Mkt', r6[R]['BIG HiPRIOR'], rmk[R],
                 rule='6分割 BIG HiPRIOR', turnover=2.5, unit=0.002, repl=rep_big, pub=1993)
    for R in REG_ALL:
        evaluate(f'F2_{R}_me5_prior5', 'F2', f'{R} 規模上位20%×勢い上位20%（25分割）vs {R} Mkt', r25[R][col25(5, 5)], rmk[R],
                 rule='25分割 ME5 PRIOR5', turnover=3.0, unit=0.002, repl=rep_me5, pub=1993)
    # JKP の良い側（地域ごとに 2006 年までで決める）
    def jkp_good(region, key):
        side, _ = M.jkp_good_side(region, key, 'vw', upto=TR)
        if side is None:
            return None, None
        return side, add_rf(jkp_rows_filtered(region, key, side), RF)

    def jkp_repl(key):
        units, sides = {}, {}
        for u in JKP_UNITS:
            try:
                side, s = jkp_good(u, key)
            except Exception as ex:  # noqa
                side, s = None, None
                log('JKP 取得失敗', u, key, ex)
            sides[u] = side
            units[u] = unit_stats(s, CMKT[u]) if s else None
        rs = repl_summary(units); rs['sides'] = sides
        return rs
    rep_jkp_mom = jkp_repl('ret_12_1')
    for reg in ('world_ex_us', 'developed', 'emerging', 'jpn'):
        side, s = jkp_good(reg, 'ret_12_1')
        evaluate(f'F2_jkp_{reg}_ret_12_1', 'F2', f'JKP {reg} 勢い12-1 の良い側の三分位（vw）vs {reg} mkt vw', s, CMKT[reg],
                 rule=f'JKP ret_12_1 三分位 {side}', turnover=2.0, unit=0.002, repl=rep_jkp_mom, pub=1993, extra={'good_side': side})
    log('F2 done')

    # ─ F4 崩れへの備え ─
    d10d = fr_vw('10_Portfolios_Prior_12_2_Daily', 'daily')['Hi PRIOR']
    d6d = fr_vw('6_Portfolios_ME_Prior_12_2_Daily', 'daily')['BIG HiPRIOR']
    ffd = M.ff_factors('daily')
    mktd = ffd['mkt']
    sig_star = S.stdev([v for k, v in MKT.items() if k <= TR]) * math.sqrt(12)
    sanity['F4_sigma_star_train_mkt'] = round(sig_star * 100, 2)
    log('σ* (訓練期間の Mkt の年率ボラ)', round(sig_star * 100, 2))

    def realized(daily):
        ks = sorted(daily)
        out = {}
        # 月末ごとに直近126営業日
        by_m = {}
        for i, k in enumerate(ks):
            by_m[k // 100] = i
        for ym, i in by_m.items():
            if i + 1 < 126:
                continue
            w = [daily[ks[j]] for j in range(i - 125, i + 1)]
            out[ym] = math.sqrt(252 * sum(x * x for x in w) / 126)
        return out

    def nextm(ym):
        y, m = divmod(ym, 100)
        return (y + 1) * 100 + 1 if m == 12 else ym + 1

    def volman(mret, daily, to_year, unit, cap=1.5, spread=0.005):
        sig = realized(daily)
        out, cst, ws = {}, {}, {}
        prev = None
        for ym, sg in sorted(sig.items()):
            m1 = nextm(ym)
            if m1 not in mret or m1 not in RF or sg <= 0:
                continue
            w = min(cap, sig_star / sg)
            r = w * mret[m1] + (1 - w) * RF[m1] - max(0.0, w - 1) * spread / 12
            c = ((abs(w - prev) if prev is not None else 0.0) + w * to_year / 12) * unit
            out[m1] = r; cst[m1] = c; ws[m1] = w; prev = w
        return out, cst, ws

    vm = {'F4v1_volmanaged_top_decile': (d10['Hi PRIOR'], d10d, 4.0, 0.002, '変動管理つき 10分割 Hi PRIOR（上限1.5倍）'),
          'F4v2_volmanaged_big_winners': (d6['BIG HiPRIOR'], d6d, 2.5, 0.001, '変動管理つき 6分割 BIG HiPRIOR（上限1.5倍）'),
          'F4v3_volmanaged_market_control': (MKT, mktd, 0.0, 0.0005, '対照: 変動管理つきの市場そのもの（上限1.5倍）')}
    for sid, (mr, dd, to, u, lab) in vm.items():
        r, cst, ws = volman(mr, dd, to, u)
        if sid == 'F4v3_volmanaged_market_control':
            cst = {k: v for k, v in cst.items()}  # 市場は回転0（露出の変化だけ）
        wl = list(ws.values())
        base_cmp = excess_stats(r, mr)  # 元の（管理なし）との比較
        evaluate(sid, 'F4', lab, r, MKT, rule=lab, cost=cst, rf=RF, pub=2015, timing=True,
                 extra={'weight_mean': round(S.mean(wl), 3), 'weight_share_at_cap': round(sum(1 for x in wl if x >= 1.5 - 1e-9) / len(wl), 3),
                        'weight_share_below_1': round(sum(1 for x in wl if x < 1) / len(wl), 3), 'vs_unmanaged_underlying': base_cmp,
                        'sharpe_underlying': {'train': M.sharpe(mr, RF, z=TR), 'hold': M.sharpe(mr, RF, a=HS)}})
    # 弱気相場の切替
    def bear_switch(win, to_year, unit):
        ks = sorted(MKT)
        out, cst = {}, {}
        prev_state = None
        for i in range(23, len(ks) - 1):
            cum = math.fsum(math.log1p(MKT[ks[j]]) for j in range(i - 23, i + 1))
            bear = cum < 0
            m1 = ks[i + 1]
            if m1 not in win:
                continue
            r = MKT[m1] if bear else win[m1]
            c = (1.0 * unit if (prev_state is not None and bear != prev_state) else 0.0) + (0.0 if bear else to_year / 12 * unit)
            out[m1] = r; cst[m1] = c; prev_state = bear
        share = sum(1 for i in range(23, len(ks) - 1) if math.fsum(math.log1p(MKT[ks[j]]) for j in range(i - 23, i + 1)) < 0) / max(1, len(ks) - 24)
        return out, cst, share
    for sid, (win, to, u, lab) in {'F4d1_bear_switch_big_winners': (d6['BIG HiPRIOR'], 2.5, 0.001, '弱気相場（市場の過去24か月が負）は市場・それ以外は BIG HiPRIOR'),
                                   'F4d2_bear_switch_top_decile': (d10['Hi PRIOR'], 4.0, 0.002, '弱気相場は市場・それ以外は 10分割 Hi PRIOR')}.items():
        r, cst, share = bear_switch(win, to, u)
        evaluate(sid, 'F4', lab, r, MKT, rule=lab, cost=cst, rf=RF, pub=2016, timing=True, extra={'bear_share_of_months': round(share, 3)})
    log('F4 done')

    # ─ F5 JKP 勢い系の信号（米国）─
    SIG = {'ret_12_1': (2.0, 1993), 'ret_9_1': (2.5, 1993), 'ret_6_1': (3.0, 1993), 'ret_3_1': (6.0, 1993), 'ret_12_7': (2.0, 2012),
           'resff3_12_1': (2.0, 2011), 'resff3_6_1': (3.0, 2011), 'prc_highprc_252d': (1.5, 2004), 'seas_1_1an': (12.0, 2008)}
    for key, (to, pub) in SIG.items():
        side, s = jkp_good('usa', key)
        rp = rep_jkp_mom if key == 'ret_12_1' else jkp_repl(key)
        evaluate(f'F5_usa_{key}', 'F5', f'JKP 米国 {key} の良い側の三分位（vw）vs 米国 mkt vw', s, CMKT['usa'],
                 rule=f'JKP {key} 三分位 {side}', turnover=to, unit=0.001, repl=rp, pub=pub, extra={'good_side': side})
        log('F5', key, 'done')

    # ─ F6 実装できる業種の回転 ─
    spdr = {t: yh(t) for t in ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY', 'XLRE', 'XLC']}
    spy = yh('SPY')
    r, cst, info = jt(spdr, 6, 0, 6, 2, 0.0005)
    evaluate('F6_spdr_MG66_top2', 'F6', 'Select Sector SPDR・MG 6-6・上位2 vs SPY（Yahoo）', r, spy, rule='SPDR MG6-6 上位2', cost=cst, pub=1999,
             extra={'jt_info': info, 'survivorship': '業種ETFは消えないので偏りはほぼ無いが Yahoo の調整値'})
    r, cst, info = jt(GICS['usa'], 6, 0, 6, 2, 0.0005)
    evaluate('F6_jkp_gics_usa_MG66_top2', 'F6', 'JKP 米国 GICS 11業種・MG 6-6・上位2 vs 米国 mkt vw', r, CMKT['usa'], rule='GICS MG6-6 上位2', cost=cst, pub=1999, extra={'jt_info': info})
    for c in GICS_UNITS:
        r, cst, info = jt(GICS[c], 6, 0, 6, 2, 0.0005)
        evaluate(f'F6_jkp_gics_{c}_MG66_top2', 'F6', f'JKP {c} GICS 11業種・MG 6-6・上位2 vs {c} mkt vw', r, CMKT[c], rule='GICS MG6-6 上位2', cost=cst, pub=1999, extra={'jt_info': info})
    log('F6 done')

    # ─ F7 国の勢い ─
    dev = {c: CMKT[c] for c in DEV23}
    r, cst, info = ew_rank_portfolio(dev, 11, 1, 1 / 3, 0.0015)
    ewdev = {}
    for m in sorted(set().union(*[set(v) for v in dev.values()])):
        xs = [v[m] for v in dev.values() if m in v]
        if len(xs) >= 10:
            ewdev[m] = sum(xs) / len(xs)
    evaluate('F7c1_developed_12_1_top_third', 'F7', '先進23か国の国の勢い 12-1・上位1/3 等分 vs JKP developed mkt vw', r, CMKT['developed'], rule='国 12-1 上位1/3', cost=cst, pub=1997,
             extra={'info': info, 'vs_ew_countries_control': {'full': excess_stats(r, ewdev), 'hold': excess_stats(r, ewdev, a=HS)}})
    allc = {c: CMKT[c] for c in DEV23 + EM14 if c in CMKT}
    r, cst, info = ew_rank_portfolio(allc, 11, 1, 1 / 4, 0.002)
    evaluate('F7c2_allcountries_12_1_top_quarter', 'F7', '先進23＋新興14か国の国の勢い 12-1・上位1/4 等分 vs JKP world mkt vw', r, CMKT['world'], rule='国 12-1 上位1/4', cost=cst, pub=1997, extra={'info': info})
    log('F7 done')

    # ─ F8 実在ETF ─
    efa = yh('EFA')
    for t, bm, bn in (('MTUM', spy, 'SPY'), ('PDP', spy, 'SPY'), ('IMTM', efa, 'EFA')):
        evaluate(f'F8_{t}_vs_{bn}', 'F8', f'実在ETF {t} vs {bn}（Yahoo・生き残りの偏りあり）', yh(t), bm, rule='実在ETF（費用は信託報酬込みの実績）', turnover=0.0, unit=0.0)
    log('F8 done')

    # ═════════ 第2次（out/mw_momentum_prereg2.json）═════════
    REGIONS = {'all_countries', 'all_regions', 'developed', 'emerging', 'frontier', 'world', 'world_ex_us'}
    SEEN8 = {'usa', 'jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che'}
    avail = json.load(open(os.path.join(M.CACHE, 'jkp_availability.json')))
    us_side, _ = M.jkp_good_side('usa', 'ret_12_1', 'vw', upto=TR)

    def binom_p(k, n):
        return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else None

    def mkt_of(c):
        if c not in CMKT:
            try:
                CMKT[c] = add_rf(M.jkp_mkt(c, 'vw'), RF)
            except Exception as ex:  # noqa
                log('mkt 取得失敗', c, ex)
                CMKT[c] = None
        return CMKT[c]

    def panel(fid, label, series_by_c, cost_turnover=None, cost_unit=None, cost_by_c=None, pub=1993):
        units, sv, bv, cst = {}, {}, {}, {}
        for c, s_ in series_by_c.items():
            b_ = mkt_of(c)
            if not s_ or not b_:
                units[c] = {'status': 'データ無し'}
                continue
            hold_n = sum(1 for k in s_ if HS <= k <= 202512 and k in b_)
            if hold_n < 120:
                units[c] = {'status': f'保有期間 {hold_n}か月 < 120'}
                continue
            full = excess_stats(s_, b_); hold = excess_stats(s_, b_, a=HS)
            units[c] = {'status': 'ok', 'dev': c in DEV23, 'full_ex': full and full['ex_ann'], 'full_t': full and full['t'], 'from': full and full['from'],
                        'hold_ex': hold and hold['ex_ann'], 'hold_t': hold and hold['t'], 'hold_cagr_diff': hold and hold['cagr_diff']}
            for k in s_:
                if k in b_:
                    sv.setdefault(k, []).append(s_[k]); bv.setdefault(k, []).append(b_[k])
                    if cost_by_c:
                        cst.setdefault(k, []).append(cost_by_c[c].get(k, 0.0))
        ok = {c: u for c, u in units.items() if u['status'] == 'ok'}

        def sign(sub):
            n = len(sub); k = sum(1 for u in sub.values() if (u['hold_ex'] or 0) > 0)
            return {'n': n, 'positive': k, 'share': round(k / n, 3) if n else None, 'sign_p_one_sided': round(binom_p(k, n), 4) if n else None,
                    'mean_hold_ex': round(S.mean(u['hold_ex'] for u in sub.values()), 2) if n else None,
                    'median_hold_ex': round(S.median(u['hold_ex'] for u in sub.values()), 2) if n else None}
        res = {'all': sign(ok), 'developed': sign({c: u for c, u in ok.items() if u['dev']}), 'emerging_other': sign({c: u for c, u in ok.items() if not u['dev']})}
        res['pass_rule'] = bool(res['all']['n'] and res['all']['share'] >= 2 / 3 and res['all']['sign_p_one_sided'] < 0.05)
        ms = sorted(k for k in sv if len(sv[k]) >= 3)
        s_ew = {k: S.mean(sv[k]) for k in ms}; b_ew = {k: S.mean(bv[k]) for k in ms}
        extra = {'panel': res, 'units': units, 'panel_countries_per_month_median': S.median(len(sv[k]) for k in ms) if ms else None}
        if cost_by_c:
            cmap = {k: S.mean(cst[k]) for k in ms}
            evaluate(fid, fid.split('_')[0], label, s_ew, b_ew, rule=label, cost=cmap, pub=pub, extra=extra)
        else:
            evaluate(fid, fid.split('_')[0], label, s_ew, b_ew, rule=label, turnover=cost_turnover, unit=cost_unit, pub=pub, extra=extra)
        log(fid, res)

    # F9 株の勢いのパネル
    cands9 = [c for c in sorted(avail['portfolios']) if c not in REGIONS | SEEN8]
    ser9 = {}
    for c in cands9:
        if 'ret_12_1' not in set(avail['portfolios'].get(c, [])):
            ser9[c] = None; continue
        try:
            ser9[c] = add_rf(jkp_rows_filtered(c, 'ret_12_1', us_side), RF)
        except Exception as ex:  # noqa
            log('F9 取得失敗', c, ex); ser9[c] = None
    panel('F9_panel_stock_momentum_ew', f'まだ見ていない国々の JKP ret_12_1 三分位（{us_side}）の等分 vs 同じ国々の市場の等分', ser9, 2.0, 0.003)
    # F10 業種の勢いのパネル
    cands10 = [c for c in sorted(avail['industry']) if c not in REGIONS | SEEN8]
    ser10, cost10 = {}, {}
    for c in cands10:
        try:
            g = {k: add_rf(v, RF) for k, v in jkp_industry(c).items()}
            r, cst_, info = jt(g, 6, 0, 6, 2, 0.0005)
            if info.get('eligible_median') is None or info['eligible_median'] < 8:
                ser10[c] = None; log('F10 業種が少ない', c, info.get('eligible_median'))
                continue
            ser10[c], cost10[c] = r, cst_
        except Exception as ex:  # noqa
            log('F10 取得失敗', c, ex); ser10[c] = None
    panel('F10_panel_industry_momentum_ew', 'まだ見ていない国々の GICS 業種 MG6-6 上位2 の等分 vs 同じ国々の市場の等分', ser10, cost_by_c=cost10)
    # F11 実在の新興国の勢いETF
    evaluate('F11_EEMO_vs_EEM', 'F11', '実在ETF EEMO vs EEM（Yahoo・生き残りの偏りあり）', yh('EEMO'), yh('EEM'), rule='実在ETF', turnover=0.0, unit=0.0)
    # F12 事後の混合（格付けしない）
    parts = {'F1a1_us_top_decile': (d10['Hi PRIOR'], {k: 4.0 * 0.002 / 12 for k in d10['Hi PRIOR']}),
             'F1a3_us_me5_prior5': (d25[col25(5, 5)], {k: 3.0 * 0.001 / 12 for k in d25[col25(5, 5)]})}
    for N in (49, 30, 17, 12, 10):
        (_, _, _, _, K, r, cst, info) = grid[f'F3g_ind{N}_6-0_H6_K15']
        parts[f'F1b_ind{N}'] = (r, cst)
    def blend(ids):
        ms = sorted(set.intersection(*[set(parts[i][0]) for i in ids]))
        return ({k: S.mean(parts[i][0][k] for i in ids) for k in ms}, {k: S.mean(parts[i][1].get(k, 0.0) for i in ids) for k in ms})
    a7 = ['F1a1_us_top_decile', 'F1a3_us_me5_prior5', 'F1b_ind49', 'F1b_ind30', 'F1b_ind17', 'F1b_ind12', 'F1b_ind10']  # 第1次で A だった7本（prereg2 に記載）
    for sid, ids in (('F12_blend_top_decile_ind49', ['F1a1_us_top_decile', 'F1b_ind49']), ('F12_blend_F1_A7', a7)):
        r, cst = blend(ids)
        evaluate(sid, 'F12', f'事後の混合（格付けしない）: {" + ".join(ids)} の等分', r, MKT, rule='事後', cost=cst, extra={'posthoc': True, 'parts': ids})
    log('phase2 done')

    # ═════════ 第3次（out/mw_momentum_prereg3.json）═════════
    for fam, sigs, pub in (('F13', {'niq_su': 3.0, 'saleq_su': 3.0, 'ni_inc8q': 1.5, 'niq_at_chg1': 3.0, 'niq_be_chg1': 3.0, 'ocf_at_chg1': 1.5}, 1996),
                           ('F14', {'seas_2_5an': 12.0, 'seas_6_10an': 12.0, 'seas_11_15an': 12.0, 'seas_16_20an': 12.0}, 2008)):
        for key, to in sigs.items():
            try:
                side, s_ = jkp_good('usa', key)
                rp = jkp_repl(key)
            except Exception as ex:  # noqa
                log(fam, key, '取得失敗', ex)
                continue
            evaluate(f'{fam}_usa_{key}', fam, f'JKP 米国 {key} の良い側の三分位（vw）vs 米国 mkt vw', s_, CMKT['usa'],
                     rule=f'JKP {key} 三分位 {side}', turnover=to, unit=0.001, repl=rp, pub=pub, extra={'good_side': side})
            log(fam, key, 'done')
    log('phase3 done')

    # ═════════ 第4次（out/mw_momentum_prereg4.json）═════════
    for key, (to, pub) in {'seas_6_10an': (12.0, 2008), 'seas_11_15an': (12.0, 2008), 'seas_2_5an': (12.0, 2008), 'ocf_at_chg1': (1.5, 1996),
                           'niq_su': (3.0, 1996), 'niq_be_chg1': (3.0, 1996), 'niq_at_chg1': (3.0, 1996), 'saleq_su': (3.0, 1996)}.items():
        side_us, _ = M.jkp_good_side('usa', key, 'vw', upto=TR)
        ser = {}
        for c in cands9:
            if key not in set(avail['portfolios'].get(c, [])):
                ser[c] = None; continue   # JKP の一覧に無い（取得すると 403 を5回待つ）
            try:
                ser[c] = add_rf(jkp_rows_filtered(c, key, side_us), RF)
            except Exception as ex:  # noqa
                log('F15 取得失敗', c, key, ex); ser[c] = None
        panel(f'F15_panel_{key}_ew', f'まだ見ていない国々の JKP {key} 三分位（{side_us}）の等分 vs 同じ国々の市場の等分', ser, to, 0.003, pub=pub)
    log('phase4 panels done')

    # ═════════ 第5次（out/mw_momentum_prereg5.json）═════════
    WIN = {'1-1': (1, 1), '2-5': (2, 5), '6-10': (6, 10), '11-15': (11, 15), '16-20': (16, 20), '1-10': (1, 10), '1-20': (1, 20)}
    seas_repl_cache = {}

    def seas_repl(frac):
        if frac not in seas_repl_cache:
            units = {}
            for c in GICS_UNITS:
                r, cst_, info = seas_rank(GICS[c], 1, 10, K=kof(frac, 11), unit=0.0005)
                units[c] = unit_stats(r, CMKT[c])
            seas_repl_cache[frac] = repl_summary(units)
        return seas_repl_cache[frac]
    for N, R in IND.items():
        for wk, (a, b) in WIN.items():
            for frac in (0.15, 0.30):
                K = kof(frac, N)
                r, cst_, info = seas_rank(R, a, b, K=K, unit=0.0005)
                lab = f'米国 {N}業種の季節性・{wk}年前の同じ暦月・上位{K}（{int(frac * 100)}%）・1か月保有'
                if wk == '1-20' and frac == 0.15:
                    evaluate(f'F16p_ind{N}_seas_1-20', 'F16p', lab, r, MKT, rule=lab, cost=cst_, repl=seas_repl(frac), pub=2008, extra={'info': info, 'K': K})
                evaluate(f'F16g_ind{N}_seas_{wk}_K{int(frac * 100)}', 'F16g', lab, r, MKT, rule=lab, cost=cst_, repl=seas_repl(frac), pub=2008,
                         extra={'info': info, 'K': K}, compact=True)
    log('F16 done')
    r, cst_, info = seas_rank({c: CMKT[c] for c in DEV23}, 1, 10, third=True, unit=0.0015)
    evaluate('F17_country_seas_1-10_top_third', 'F17', '先進23か国の国の季節性（1〜10年前の同じ暦月）・上位1/3 等分 vs JKP developed mkt vw', r, CMKT['developed'],
             rule='国の季節性 1-10 上位1/3', cost=cst_, pub=2008, extra={'info': info})
    log('phase5 done')

    fams = ['F1', 'F2', 'F3g', 'F3s', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13', 'F14', 'F15', 'F16p', 'F16g', 'F17']
    fam_holm = finalize(fams)
    # ─ 診断（第4次・報告のみ）─
    diag = {}
    win = {'MTUM': 201305, 'IMTM': 201502, 'EEMO': 201203}
    etf = {t: M_ for t, M_ in (('MTUM', excess_stats(yh('MTUM'), spy)), ('IMTM', excess_stats(yh('IMTM'), efa)), ('EEMO', excess_stats(yh('EEMO'), yh('EEM'))))}
    diag['D1_paper_vs_real'] = {
        'MTUM': {'etf_vs_SPY': etf['MTUM'], 'paper_US_BIG_HiPRIOR': excess_stats(d6['BIG HiPRIOR'], MKT, a=win['MTUM']), 'paper_US_top_decile': excess_stats(d10['Hi PRIOR'], MKT, a=win['MTUM'])},
        'IMTM': {'etf_vs_EFA': etf['IMTM'], 'paper_DevExUS_BIG_HiPRIOR': excess_stats(r6['Developed_ex_US']['BIG HiPRIOR'], rmk['Developed_ex_US'], a=win['IMTM'])},
        'EEMO': {'etf_vs_EEM': etf['EEMO'], 'paper_EM_BIG_HiPRIOR': excess_stats(r6['Emerging']['BIG HiPRIOR'], rmk['Emerging'], a=win['EEMO'])}}
    blocks = [(200701, 201112), (201201, 201612), (201701, 202112), (202201, 202612)]
    diag['D2_blocks'], diag['D3_capm'], diag['D4_breakeven'] = {}, {}, {}
    for e in TESTED:
        if e['grade'] not in ('S', 'A') or e['family'] in ('F3g', 'F16g'):
            continue
        s_, b_ = SERIES[e['id']]
        diag['D2_blocks'][e['id']] = {f'{a // 100}-{z // 100}': (round(S.mean(s_[k] - b_[k] for k in s_ if a <= k <= z) * 1200, 2) if any(a <= k <= z for k in s_) else None) for a, z in blocks}
        ks = [k for k in sorted(s_) if k >= HS and k in RF]
        y = [s_[k] - RF[k] for k in ks]; x = [b_[k] - RF[k] for k in ks]
        mx, my = S.mean(x), S.mean(y)
        beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sum((xi - mx) ** 2 for xi in x)
        res = [yi - beta * xi for xi, yi in zip(x, y)]
        ta = M.nw_t(res)
        diag['D3_capm'][e['id']] = {'alpha_ann': round(S.mean(res) * 1200, 2), 'alpha_t': round(ta, 2) if ta is not None else None, 'beta': round(beta, 3)}
        h = e['hold']
        diag['D4_breakeven'][e['id']] = {'hold_gross_ex_ann': h['ex_ann'], 'assumed_annual_cost_pct': e['annual_cost_pct'],
                                         'cost_margin_x': round(h['ex_ann'] / e['annual_cost_pct'], 2) if e['annual_cost_pct'] else None}
    log('diagnostics done')
    all_holm = M.holm({e['id']: e['hold_p_for_holm'] for e in TESTED})
    for e in TESTED:
        e['holm_all_tested'] = all_holm.get(e['id'])
    from collections import Counter
    summary = {'n_tested': len(TESTED), 'grades': dict(Counter(e['grade'] for e in TESTED)),
               'grades_by_family': {f: dict(Counter(e['grade'] for e in TESTED if e['family'] == f)) for f in fams}}
    g3 = [e for e in TESTED if e['family'] == 'F3g']
    summary['F3_grid'] = {'n': len(g3), 'hold_net_positive': sum(1 for e in g3 if e['cost_hold'] and e['cost_hold']['ex_ann'] > 0 and e['cost_hold']['cagr_diff'] > 0),
                          'hold_t_ge_1_65': sum(1 for e in g3 if e['hold'] and (e['hold']['t'] or 0) >= 1.65),
                          'median_hold_ex': S.median(e['hold']['ex_ann'] for e in g3 if e['hold']),
                          'median_train_ex': S.median(e['train']['ex_ann'] for e in g3 if e['train']),
                          'by_N_median_hold_ex': {N: S.median(e['hold']['ex_ann'] for e in g3 if e['hold'] and e['id'].startswith(f'F3g_ind{N}_')) for N in (49, 30, 17, 12, 10)}}
    top = sorted([e for e in TESTED if e['cost_hold']], key=lambda e: -e['cost_hold']['ex_ann'])[:15]
    summary['top_by_net_hold_ex'] = [(e['id'], e['grade'], e['cost_hold']['ex_ann'], e['cost_hold']['t']) for e in top]
    sha2 = subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_momentum_prereg2.json'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    sha4 = subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_momentum_prereg4.json'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    sha5 = subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_momentum_prereg5.json'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    sha3 = subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_momentum_prereg3.json'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    out = {'angle': 'momentum', 'prereg': f'out/{PRE}', 'prereg_commit': sha, 'prereg2': 'out/mw_momentum_prereg2.json', 'prereg2_commit': sha2,
           'prereg3': 'out/mw_momentum_prereg3.json', 'prereg3_commit': sha3,
           'prereg4': 'out/mw_momentum_prereg4.json', 'prereg4_commit': sha4,
           'prereg5': 'out/mw_momentum_prereg5.json', 'prereg5_commit': sha5, 'global_prereg': 'out/mw_prereg.json',
           'generated': datetime.date.today().isoformat(), 'sanity': sanity, 'family_holm': fam_holm, 'summary': summary,
           'deviations': DEVIATIONS, 'diagnostics': diag, 'tested': TESTED, 'log': LOG[-80:]}
    p = os.path.join(BASE, 'out', OUT)
    json.dump(out, open(p, 'w'), ensure_ascii=False, separators=(',', ':'))
    log('saved', p, os.path.getsize(p))
    for g in ('S', 'A', 'B'):
        for e in TESTED:
            if e['grade'] == g:
                log(g, e['id'], 'hold', e['hold'] and (e['hold']['ex_ann'], e['hold']['t']), 'net', e['cost_hold'] and e['cost_hold']['ex_ann'])


DEVIATIONS = [
    '全体の事前登録の『訓練期間は最低15年』を第1次・第2次では格付けに当てていなかった（mw_common.grade は長さを見ない）。第3次の事前登録で明記し、全戦略に一律に当てた（厳しくする方向のみ）。影響は 1999 年以降のデータの戦略（F6・F8・F10・F11）で、旧格付けは grade_without_15y_rule に残す',
    'F3s_all_trainbest は F3s_ind30_trainbest と同じ規則（30業種・9-0・H6・15%）が選ばれた。族 F3s の Holm では2回数えている（保守側）',
    'mw_common.excess_stats の β の計算が S.mean を生成式の中で毎回呼ぶため O(n²)（1200か月で1回約3秒・約300戦略×9回で数時間）。mw_common は共有なので触らず、同じ式・同じ丸めの高速版を本スクリプト内に置いた（--selftest で出力の一致を検算）',
]

if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        main()
