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
                       'oneway_turnover_per_year': round(sum(turn.values()) / yrs, 3) if yrs else None, 'missing_member_months': miss}


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


def kof(frac, N):
    return max(2, int(math.floor(frac * N + 0.5)))


# ───────────────────────── 評価 ─────────────────────────
TESTED = []


def evaluate(sid, fam, label, s, b, *, rule='', cost=None, turnover=None, unit=None, rf=None, repl=None, pub=None,
             timing=False, primary=False, extra=None, compact=False):
    """s・b は総リターン（同じ基準）。cost は {月: 費用}（正確な回転から）か、turnover/unit（年の片道回転×単価）"""
    ks = sorted(set(s) & set(b))
    s = {k: s[k] for k in ks}; b = {k: b[k] for k in ks}
    if cost is not None:
        net = {k: s[k] - cost.get(k, 0.0) for k in ks}
        stress = {k: s[k] - 3.0 * cost.get(k, 0.0) for k in ks}
        ann_cost = round(S.mean([cost.get(k, 0.0) for k in ks]) * 12 * 100, 3) if ks else None
    else:
        net = M.apply_cost(s, turnover, unit)
        stress = M.apply_cost(s, turnover * 1.5, unit * 2)
        ann_cost = round(turnover * unit * 100, 3)
    e = {'id': sid, 'family': fam, 'label': label, 'primary': primary, 'rule': rule, 'annual_cost_pct': ann_cost}
    e['full'] = M.excess_stats(s, b)
    e['train'] = M.excess_stats(s, b, z=TR)
    e['hold'] = M.excess_stats(s, b, a=HS)
    e['recent'] = M.excess_stats(s, b, a=RS)
    e['cost_hold'] = M.excess_stats(net, b, a=HS)
    e['cost_full'] = M.excess_stats(net, b)
    e['stress_cost_hold'] = M.excess_stats(stress, b, a=HS)
    e['roll20'] = M.rolling(s, b, 20)
    e['dca20'] = M.dca(s, b, 20)
    if not compact:
        e['cost_train'] = M.excess_stats(net, b, z=TR)
        e['roll20_net'] = M.rolling(net, b, 20)
        e['roll10'] = M.rolling(s, b, 10)
        e['dca20_net'] = M.dca(net, b, 20)
        e['maxdd_s'] = round(M.maxdd(s) * 100, 1) if s else None
        e['maxdd_b'] = round(M.maxdd(b) * 100, 1) if b else None
        e['maxdd_s_hold'] = round(M.maxdd(M.window(s, HS)) * 100, 1) if M.window(s, HS) else None
        e['maxdd_b_hold'] = round(M.maxdd(M.window(b, HS)) * 100, 1) if M.window(b, HS) else None
    if pub:
        e['postpub'] = {'from_year': pub + 1, 'stats': M.excess_stats(s, b, a=(pub + 1) * 100 + 1)}
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
    f = M.excess_stats(s, b)
    if f:
        f = dict(f); f['_hold'] = M.excess_stats(s, b, a=HS)
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
        e['grade'], e['criteria'] = g, c
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
    # sanity: JKP ff49 と French 49 業種の同じ業種（1=Agric）の差（JKP が超過なら ≈ −RF）
    try:
        jf = jkp_industry('usa', 'ff49')
        a = jf.get('1.0') or jf.get('1')
        fa = IND[49]['Agric']
        ks = sorted(k for k in set(a) & set(fa) & set(RF))
        sanity['jkp_ff49_agric_minus_french_agric_ann'] = round(S.mean(a[k] - fa[k] for k in ks) * 1200, 3)
        sanity['french_rf_ann_same_months'] = round(S.mean(RF[k] for k in ks) * 1200, 3)
        log('sanity JKP ff49 Agric − French Agric', sanity['jkp_ff49_agric_minus_french_agric_ann'], 'RF', sanity['french_rf_ann_same_months'])
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
        st = M.excess_stats(net, MKT, z=TR)
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
        base_cmp = M.excess_stats(r, mr)  # 元の（管理なし）との比較
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
             extra={'info': info, 'vs_ew_countries_control': {'full': M.excess_stats(r, ewdev), 'hold': M.excess_stats(r, ewdev, a=HS)}})
    allc = {c: CMKT[c] for c in DEV23 + EM14 if c in CMKT}
    r, cst, info = ew_rank_portfolio(allc, 11, 1, 1 / 4, 0.002)
    evaluate('F7c2_allcountries_12_1_top_quarter', 'F7', '先進23＋新興14か国の国の勢い 12-1・上位1/4 等分 vs JKP world mkt vw', r, CMKT['world'], rule='国 12-1 上位1/4', cost=cst, pub=1997, extra={'info': info})
    log('F7 done')

    # ─ F8 実在ETF ─
    efa = yh('EFA')
    for t, bm, bn in (('MTUM', spy, 'SPY'), ('PDP', spy, 'SPY'), ('IMTM', efa, 'EFA')):
        evaluate(f'F8_{t}_vs_{bn}', 'F8', f'実在ETF {t} vs {bn}（Yahoo・生き残りの偏りあり）', yh(t), bm, rule='実在ETF（費用は信託報酬込みの実績）', turnover=0.0, unit=0.0)
    log('F8 done')

    fams = ['F1', 'F2', 'F3g', 'F3s', 'F4', 'F5', 'F6', 'F7', 'F8']
    fam_holm = finalize(fams)
    all_holm = M.holm({e['id']: e['hold_p_for_holm'] for e in TESTED})
    for e in TESTED:
        e['holm_all_tested'] = all_holm.get(e['id'])
    from collections import Counter
    summary = {'n_tested': len(TESTED), 'grades': dict(Counter(e['grade'] for e in TESTED)),
               'grades_by_family': {f: dict(Counter(e['grade'] for e in TESTED if e['family'] == f)) for f in fams}}
    top = sorted([e for e in TESTED if e['cost_hold']], key=lambda e: -e['cost_hold']['ex_ann'])[:15]
    summary['top_by_net_hold_ex'] = [(e['id'], e['grade'], e['cost_hold']['ex_ann'], e['cost_hold']['t']) for e in top]
    out = {'angle': 'momentum', 'prereg': f'out/{PRE}', 'prereg_commit': sha, 'global_prereg': 'out/mw_prereg.json',
           'generated': datetime.date.today().isoformat(), 'sanity': sanity, 'family_holm': fam_holm, 'summary': summary,
           'deviations': DEVIATIONS, 'tested': TESTED, 'log': LOG[-80:]}
    p = M.save(OUT, out)
    log('saved', p, os.path.getsize(p))
    for g in ('S', 'A', 'B'):
        for e in TESTED:
            if e['grade'] == g:
                log(g, e['id'], 'hold', e['hold'] and (e['hold']['ex_ann'], e['hold']['t']), 'net', e['cost_hold'] and e['cost_hold']['ex_ann'])


DEVIATIONS = []

if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        main()
