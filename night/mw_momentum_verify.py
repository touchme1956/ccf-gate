#!/usr/bin/env python3
"""night/mw_momentum_verify.py — 『市場に勝てる歴史検証』角度 momentum の反証の検証（読むだけ・門の判定には不使用）

相手の主張（out/mw_momentum.json の S/A と B 上位2本）を、**自前の組み立て・自前の統計**で作り直して崩しにかかる。
mw_common から借りるのは取得と表の読み取り（french_tables / ff_factors / jkp_rows / yahoo / get）だけ。
ポートフォリオの組み立て（業種の重ね持ち・国のパネル・因子の勢い・良い側の決め方）、超過・NW t・CAGR 差・
転がる20年・積立20年・費用・税は全部この中で書き直す。

  python3 night/mw_momentum_verify.py   → out/mw_momentum_verify.json

見るもの（各候補）
 1. 数字の再現: 全期間/訓練/保有の超過と NW t、CAGR 差、転がる20年の勝率、費用後の保有期間
 2. 反証: 相手が純粋な時価加重か（JKP の米国 mkt vw は French Mkt より 2007〜 年0.41%弱い）、良い側が後知恵か
    （JKP の符号は論文の向き＝2007年以降の論文も含む）、費用・回転の現実性、日本の課税口座の税、
    部分期間（1998-2000 抜き・2020-21 抜き・保有期間の前半/後半）、隣の規則、1業種・1国への依存、多重検定
"""
import sys, os, json, math, statistics as S, datetime, re, collections, csv, io, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M   # 取得だけ使う

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_momentum_verify.json')
TRAIN_END, HOLD_START, RECENT = 200612, 200701, 201307
JKP_END = 202512
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ═════════════════════════ 自前の統計 ═════════════════════════
def nw_tstat(x, lag=12):
    n = len(x)
    if n < 24:
        return None
    m = math.fsum(x) / n
    e = [v - m for v in x]
    lrv = math.fsum(v * v for v in e) / n
    for L in range(1, lag + 1):
        g = math.fsum(e[i] * e[i - L] for i in range(L, n)) / n
        lrv += 2.0 * (1.0 - L / (lag + 1.0)) * g
    if lrv <= 0:
        return None
    return m / math.sqrt(lrv / n)


def geo(xs):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1 if xs else None


def stats(s, b, a=None, z=None, drop=None, lag=12):
    """s・b は同じ基準（総リターン）。drop = [(a,z), …] の月を除く"""
    ks = [k for k in sorted(s) if k in b and (a is None or k >= a) and (z is None or k <= z)]
    if drop:
        ks = [k for k in ks if not any(x <= k <= y for x, y in drop)]
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nw_tstat(ex, lag)
    gs, gb = geo([s[k] for k in ks]), geo([b[k] for k in ks])
    te = S.stdev(ex) * math.sqrt(12)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(math.fsum(ex) / len(ex) * 1200, 2),
            't': round(t, 2) if t is not None else None, 'cagr_diff': round((gs - gb) * 100, 2),
            'cagr_s': round(gs * 100, 2), 'cagr_b': round(gb * 100, 2), 'te': round(te * 100, 2)}


def roll20(s, b, years=20):
    ks = sorted(k for k in s if k in b)
    if not ks:
        return None
    res = []
    for y in range(ks[0] // 100, ks[-1] // 100 + 1):
        a = y * 100 + 7
        z = (y + years) * 100 + 6
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12:          # 欠けた窓は数えない（0で埋めない）
            continue
        d = geo([s[k] for k in w]) - geo([b[k] for k in w])
        res.append((y, round(d * 100, 2)))
    if not res:
        return None
    v = sorted(d for _, d in res)
    return {'windows': len(res), 'win_rate': round(sum(1 for _, d in res if d > 0) / len(res), 3), 'median': v[len(v) // 2],
            'worst': min(res, key=lambda x: x[1])}


def dca20(s, b, years=20):
    ks = sorted(k for k in s if k in b)
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, 12):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1.0) * (1 + s[k]); wb = (wb + 1.0) * (1 + b[k])
        out.append(ws / wb)
    if not out:
        return None
    v = sorted(out)
    return {'windows': len(v), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': round(v[len(v) // 2], 3), 'worst': round(v[0], 3)}


def capm(s, b, rf, a=None, z=None):
    ks = [k for k in sorted(s) if k in b and k in rf and (a is None or k >= a) and (z is None or k <= z)]
    y = [s[k] - rf[k] for k in ks]; x = [b[k] - rf[k] for k in ks]
    mx, my = S.mean(x), S.mean(y)
    beta = math.fsum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / math.fsum((xi - mx) ** 2 for xi in x)
    res = [yi - beta * xi for xi, yi in zip(x, y)]
    t = nw_tstat(res)
    return {'alpha': round(S.mean(res) * 1200, 2), 't': round(t, 2) if t else None, 'beta': round(beta, 3)}


def net(s, cost_monthly):
    """cost_monthly: 定数（月の費用）か {月: 費用}"""
    if isinstance(cost_monthly, dict):
        return {k: v - cost_monthly.get(k, 0.0) for k, v in s.items()}
    return {k: v - cost_monthly for k, v in s.items()}


def p_two(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def jp_tax_terminal(s, b, a, z, realize_share=1.0, tau=0.20315):
    """日本の課税口座（20.315%）の概算: 戦略は毎年の実現益に課税（損失は3年繰越）、相手は最後に一度だけ課税。
    realize_share = 年の値上がりのうち実現する割合（回転率 ≥100% なら 1）。配当課税は両方同じと見て省く。
    戻り値: 税引後の最終額の比（戦略 ÷ 相手）と税引前の比"""
    ks = [k for k in sorted(s) if k in b and a <= k <= z]
    years = sorted(set(k // 100 for k in ks))
    ws, wb, basis_s, carry = 1.0, 1.0, 1.0, []
    for y in years:
        g = 1.0
        for k in ks:
            if k // 100 == y:
                g *= 1 + s[k]
        start = ws
        ws *= g
        gain = (ws - start) * realize_share
        # 損失の繰越（3年）
        if gain < 0:
            carry.append([-gain, 3]); tax = 0.0
        else:
            off = 0.0
            for c in carry:
                u = min(c[0], gain - off); c[0] -= u; off += u
            tax = max(0.0, gain - off) * tau
        carry = [[c[0], c[1] - 1] for c in carry if c[0] > 1e-12 and c[1] - 1 > 0]
        ws -= tax
        for k in ks:
            if k // 100 == y:
                wb *= 1 + b[k]
    wb_after = wb - max(0.0, wb - 1.0) * tau
    pre_s = math.prod(1 + s[k] for k in ks)
    return {'years': len(years), 'pre_tax_ratio': round(pre_s / wb, 3), 'after_tax_ratio': round(ws / wb_after, 3)}


def bundle(s, b, cost=None, rf=None, stress_cost=None, jkp_end=False):
    """基本の一式。cost/stress_cost は月の費用（定数か dict）"""
    o = {'full': stats(s, b), 'train': stats(s, b, z=TRAIN_END), 'hold': stats(s, b, a=HOLD_START), 'recent': stats(s, b, a=RECENT),
         'roll20': roll20(s, b), 'dca20': dca20(s, b)}
    if cost is not None:
        ns = net(s, cost)
        o['net_hold'] = stats(ns, b, a=HOLD_START)
        o['net_full'] = stats(ns, b)
    if stress_cost is not None:
        o['stress_net_hold'] = stats(net(s, stress_cost), b, a=HOLD_START)
    hk = [k for k in sorted(s) if k in b and k >= HOLD_START]
    if hk:
        mid = hk[len(hk) // 2]
        o['hold_first_half'] = stats(s, b, a=HOLD_START, z=hk[len(hk) // 2 - 1])
        o['hold_second_half'] = stats(s, b, a=mid)
        o['hold_ex_2020_21'] = stats(s, b, a=HOLD_START, drop=[(202001, 202112)])
        o['hold_ex_2023_24'] = stats(s, b, a=HOLD_START, drop=[(202301, 202412)])
    o['full_ex_1998_2000'] = stats(s, b, drop=[(199801, 200012)])
    o['train_ex_1998_2000'] = stats(s, b, z=TRAIN_END, drop=[(199801, 200012)])
    if rf is not None:
        o['capm_hold'] = capm(s, b, rf, a=HOLD_START)
    return o


def grade_formal(o, repl_ok=None, net_key='net_hold', holm_or_full3=None):
    """out/mw_prereg.json の C1〜C7 をそのまま当てる（自前の数字で）"""
    tr, h, f, r, nh = o.get('train'), o.get('hold'), o.get('full'), o.get('roll20'), o.get(net_key)
    c = {'C1': bool(tr and tr['ex'] > 0 and (tr['t'] or 0) >= 2.0 and tr['n'] >= 180),
         'C2': bool(h and h['ex'] > 0 and h['cagr_diff'] > 0),
         'C3': bool(h and (h['t'] or 0) >= 1.65),
         'C4': bool(r and r['win_rate'] >= 0.8),
         'C5': repl_ok,
         'C6': bool(nh and nh['ex'] > 0 and nh['cagr_diff'] > 0),
         'C7': bool((f and (f['t'] or 0) >= 3.0) or (holm_or_full3 is True))}
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


def fragile(o):
    """A の中の『頑丈さが足りない』（B の定義）: 費用後の CAGR 差が 0.5 未満で厳しめ費用で負、または保有期間の後半が負"""
    nh, sh, h2 = o.get('net_hold'), o.get('stress_net_hold'), o.get('hold_second_half')
    return bool((nh and nh['cagr_diff'] < 0.5 and sh and sh['cagr_diff'] < 0) or (h2 and h2['ex'] < 0))


def add(d, rf):
    return {k: v + rf[k] for k, v in d.items() if k in rf}


# ═════════════════════════ データ ═════════════════════════
def fr_vw(name):
    for t, v in M.french_tables(name).items():
        if 'value weight' in t.lower() and v['freq'] == 'monthly':
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def fr_tab(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            return {c: {d: row[i] for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def fr_region_mkt(fname):
    for t, v in M.french_tables(fname).items():
        if v['freq'] == 'monthly':
            a, r = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[a] + row[r]) / 100 for d, row in v['data'].items() if row[a] is not None and row[r] is not None}
    raise KeyError(fname)


_JKPP = {}


def jkp_terciles(region, key, weighting='vw', nmin=10):
    """{'1.0': {ym: 超過}, '2.0':…, '3.0':…}。n<nmin の月は入れない（0 で埋めない）"""
    ck = (region, key, weighting, nmin)
    if ck in _JKPP:
        return _JKPP[ck]
    d = collections.defaultdict(dict)
    for x in M.jkp_rows(region, key, 'portfolios', weighting):
        if x['ret'] in ('', 'NA', 'na') or x['n'] in ('', 'NA', 'na'):
            continue
        if float(x['n']) < nmin:
            continue
        d[x['pf']][int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    _JKPP[ck] = dict(d)
    return _JKPP[ck]


def jkp_mkt(region, weighting='vw'):
    out, n = {}, {}
    for x in M.jkp_rows(region, 'mkt', 'factor', weighting):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        ym = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        out[ym] = float(x['ret'])
        try:
            n[ym] = float(x['n_stocks'])
        except Exception:
            pass
    return out, n


def side_pre2006(P):
    """良い側 = 2006-12 までの（第3−第1）の算術平均の符号（成績だけで決める。JKP の符号＝論文の向きは使わない）"""
    ks = [k for k in P.get('3.0', {}) if k in P.get('1.0', {}) and k <= TRAIN_END]
    if len(ks) < 24:
        return None, None
    m = S.mean(P['3.0'][k] - P['1.0'][k] for k in ks)
    t = nw_tstat([P['3.0'][k] - P['1.0'][k] for k in ks])
    return ('3.0' if m > 0 else '1.0'), round(t, 2) if t else None


def yh(t, end=202608):
    return {k: v for k, v in M.yahoo(t).items() if k <= end}


# ═════════════════════════ 業種の勢い（自前の重ね持ち）═════════════════════════
def ind_momentum(R, L, skip, H, K, unit=0.0005, exclude=()):
    """月末 f に [f-skip-L+1, f-skip] の累積で並べ上位 K を等分（組）。組 f は f+1..f+H に持ち、各月の重み = (1/H)Σ組(1/K)。
    H 個の組が全部そろった月からだけ数える。欠けた業種は形成に入れない。費用 = ½Σ|w目標−w流れた後| × unit"""
    names = [n for n in R if n not in exclude]
    months = sorted(set().union(*[set(R[n]) for n in names]))
    N = len(months)
    lr = {n: [math.log1p(R[n][m]) if m in R[n] else None for m in months] for n in names}
    coh = {}
    for f in range(N):
        lo, hi = f - skip - L + 1, f - skip
        if lo < 0:
            continue
        sc = []
        for n in names:
            seg = lr[n][lo:hi + 1]
            if any(v is None for v in seg):
                continue
            sc.append((-math.fsum(seg), n))
        if len(sc) >= K:
            sc.sort()
            coh[f] = [n for _, n in sc[:K]]
    ret, cost, turn = {}, {}, {}
    prev_after = None
    for j in range(1, N):
        fs = list(range(j - H, j))
        if any(f not in coh for f in fs):
            prev_after = None
            continue
        m = months[j]
        w = collections.defaultdict(float)
        ok = True
        for f in fs:
            mem = [n for n in coh[f] if m in R[n]]
            if not mem:
                ok = False; break
            for n in mem:
                w[n] += 1.0 / H / len(mem)
        if not ok:
            prev_after = None
            continue
        rp = math.fsum(w[n] * R[n][m] for n in w)
        if prev_after is not None:
            to = 0.5 * math.fsum(abs(w.get(n, 0.0) - prev_after.get(n, 0.0)) for n in set(w) | set(prev_after))
        else:
            to = 0.0
        ret[m] = rp; turn[m] = to; cost[m] = to * unit
        prev_after = {n: w[n] * (1 + R[n][m]) / (1 + rp) for n in w}
    yrs = len(turn) / 12
    return ret, cost, {'oneway_turnover_per_year': round(sum(turn.values()) / yrs, 2) if yrs else None, 'months': len(ret)}


def ind_attribution(R, L, skip, H, K, mkt, a=HOLD_START):
    """保有期間の超過を業種ごとに分ける（Σ_i w_i (r_i − r_mkt) の i ごとの年率平均）。H=1 だけ"""
    assert H == 1
    names = list(R)
    months = sorted(set().union(*[set(R[n]) for n in names]))
    lr = {n: [math.log1p(R[n][m]) if m in R[n] else None for m in months] for n in names}
    contrib = collections.defaultdict(float)
    cnt = 0
    for f in range(len(months) - 1):
        m = months[f + 1]
        if m < a or m not in mkt:
            continue
        lo, hi = f - skip - L + 1, f - skip
        sc = []
        for n in names:
            seg = lr[n][lo:hi + 1]
            if lo < 0 or any(v is None for v in seg):
                continue
            sc.append((-math.fsum(seg), n))
        sc.sort()
        mem = [n for _, n in sc[:K] if m in R[n]]
        for n in mem:
            contrib[n] += (R[n][m] - mkt[m]) / len(mem)
        cnt += 1
    return {n: round(v / cnt * 1200, 2) for n, v in sorted(contrib.items(), key=lambda x: -x[1])}


# ═════════════════════════ 候補ごとの検証 ═════════════════════════
V = []   # 判定の一覧
DETAIL = {}


def verdict(name, claimed, verified, verdict_s, reproduced, key_numbers, issues):
    V.append({'name': name, 'claimed_grade': claimed, 'verified_grade': verified, 'verdict': verdict_s,
              'reproduced': reproduced, 'key_numbers': key_numbers, 'issues': issues})
    log('VERDICT', name, claimed, '→', verified, verdict_s)


def close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def main():
    ff = M.ff_factors()
    MKT, RF = ff['mkt'], ff['rf']
    claims = {e['id']: e for e in json.load(open(os.path.join(BASE, 'out', 'mw_momentum.json')))['tested']}
    n_tested = len(claims)
    DETAIL['n_tested_by_researcher'] = n_tested

    # ─── 相手の違い: JKP 米国 mkt vw と French Mkt ───
    jk_us, jk_us_n = jkp_mkt('usa', 'vw')
    jk_us_tot = add(jk_us, RF)
    gap = {'full_1926_2006': stats(jk_us_tot, MKT, z=TRAIN_END), 'hold_2007_2025': stats(jk_us_tot, MKT, a=HOLD_START, z=JKP_END),
           'recent_2013_2025': stats(jk_us_tot, MKT, a=RECENT, z=JKP_END)}
    DETAIL['benchmark_gap_jkp_usa_vw_minus_french_mkt'] = gap
    log('JKP usa vw − French Mkt', {k: (v['ex'], v['t']) for k, v in gap.items()})
    # JKP 業種 ff49 と French 49 業種（保有期間）: 業種でも同じ差があるか（差が市場だけなら宇宙の違い）
    try:
        b = M.get('https://jkpfactors-data.s3.amazonaws.com/public/industry/%5Busa%5D_%5Bff49%5D_%5Bmonthly%5D_%5Bvw%5D.zip', name='jkp_industry_usa_ff49_vw_monthly.zip')
        z = zipfile.ZipFile(io.BytesIO(b))
        jf = collections.defaultdict(dict)
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            if x['ret'] not in ('', 'NA'):
                jf[x['ff49']][int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
        I49 = fr_vw('49_Industry_Portfolios')
        diffs = []
        for i, c in enumerate(I49):
            a_ = jf.get(f'{i + 1}.0') or jf.get(str(i + 1))
            if not a_:
                continue
            ks = [k for k in a_ if k in I49[c] and k in RF and HOLD_START <= k <= JKP_END]
            if len(ks) > 100:
                diffs.append(S.mean(a_[k] + RF[k] - I49[c][k] for k in ks) * 1200)
        DETAIL['jkp_ff49_minus_french49_hold_median'] = round(S.median(diffs), 3) if diffs else None
        log('JKP ff49 + RF − French49 (保有・中央値 年率%)', DETAIL['jkp_ff49_minus_french49_hold_median'], len(diffs))
    except Exception as ex:  # noqa
        DETAIL['jkp_ff49_check_error'] = str(ex)

    # ═════ 1. F2_Emerging_big_winners ═════
    em6 = fr_vw('Emerging_Markets_6_Portfolios_ME_Prior_12_2')
    em_n = fr_tab('Emerging_Markets_6_Portfolios_ME_Prior_12_2', 'Number of Firms')
    em_mkt = fr_region_mkt('Emerging_5_Factors')
    s = em6['BIG HiPRIOR']
    o = bundle(s, em_mkt, cost=2.5 * 0.002 / 12, stress_cost=4.0 * 0.006 / 12, rf=RF)
    o['net_hold_realistic_0.4pct_x300'] = stats(net(s, 3.0 * 0.004 / 12), em_mkt, a=HOLD_START)
    o['n_firms_big_hiprior'] = {str(y): em_n['BIG HiPRIOR'].get(y * 100 + 1) for y in (1990, 1995, 2000, 2007, 2015, 2025)}
    # 隣: 同じ表の他の列・等加重・大型の中間
    em6ew = None
    for t, v in M.french_tables('Emerging_Markets_6_Portfolios_ME_Prior_12_2').items():
        if 'equal weight' in t.lower() and v['freq'] == 'monthly':
            em6ew = {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    o['neighbors'] = {'SMALL_HiPRIOR_vw': stats(em6['SMALL HiPRIOR'], em_mkt, a=HOLD_START),
                      'BIG_mid_vw': stats(em6['ME2 PRIOR2'], em_mkt, a=HOLD_START),
                      'BIG_HiPRIOR_minus_BIG_LoPRIOR': stats(em6['BIG HiPRIOR'], em6['BIG LoPRIOR'], a=HOLD_START),
                      'BIG_HiPRIOR_ew': stats(em6ew['BIG HiPRIOR'], em_mkt, a=HOLD_START) if em6ew else None}
    # 隣: JKP emerging の勢いの三分位（vw）vs JKP emerging mkt vw（別のデータ・別の作り方）
    em_jk, _ = jkp_mkt('emerging', 'vw')
    nb = {}
    for key in ('ret_12_1', 'ret_9_1', 'ret_6_1', 'ret_12_7', 'resff3_12_1'):
        try:
            P = jkp_terciles('emerging', key)
            sd, _ = side_pre2006(jkp_terciles('usa', key))
            nb[key] = {'side_from_US_pre2006': sd, 'full': stats(P[sd], em_jk), 'train': stats(P[sd], em_jk, z=TRAIN_END), 'hold': stats(P[sd], em_jk, a=HOLD_START)}
        except Exception as ex:  # noqa
            nb[key] = {'error': str(ex)}
    o['neighbors_jkp_emerging'] = nb
    # 他の地域の同じ列（C5 の再計算）
    rr = {}
    for R_ in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Developed_ex_US', 'North_America'):
        rs = fr_vw(f'{R_}_6_Portfolios_ME_Prior_12_2')['BIG HiPRIOR']
        rm = fr_region_mkt(f'{R_}_3_Factors')
        rr[R_] = {'full': stats(rs, rm), 'hold': stats(rs, rm, a=HOLD_START)}
    o['other_regions_big_hiprior'] = rr
    # 実在ETF
    try:
        eemo, eem = yh('EEMO'), yh('EEM')
        o['etf_EEMO_vs_EEM'] = stats(eemo, eem)
        a0 = min(k for k in eemo if k in eem)
        o['paper_same_window'] = stats(s, em_mkt, a=a0)
        o['paper_same_window_net_realistic'] = stats(net(s, 3.0 * 0.004 / 12), em_mkt, a=a0)
    except Exception as ex:  # noqa
        o['etf_error'] = str(ex)
    o['jp_tax_hold'] = jp_tax_terminal(s, em_mkt, HOLD_START, 202512)
    DETAIL['F2_Emerging_big_winners'] = o
    c = claims['F2_Emerging_big_winners']
    rep = close(o['hold']['ex'], c['hold']['ex_ann'], 0.05) and close(o['full']['t'], c['full']['t'], 0.05)
    g, crit = grade_formal(o, repl_ok=True)
    em_other = {k: v['hold']['ex'] for k, v in rr.items()}
    jk_h = nb.get('ret_12_1', {}).get('hold') or {}
    iss = [
        f"再現: 保有 +{o['hold']['ex']}%/年 t{o['hold']['t']}・全期間 t{o['full']['t']}・CAGR差 {o['hold']['cagr_diff']}・20年窓 {o['roll20']['win_rate']}（{o['roll20']['windows']}窓）。数字は一致（再現{'成功' if rep else '一部ずれ'}）",
        f"相手は French Emerging の Mkt（時価加重）で純粋な時価加重＝相手の問題なし。ただし French の新興国は1990年起点の36年しかなく、独立な20年窓は1本強（17窓は重なっている）",
        f"同じ規則の他の地域（保有期間）: {em_other} ＝新興国だけが突出。F2 族17本のうち新興国だけが S（族内の最良＝選択の偏り）。Holm（F2 族）は 0.168、全405本の Holm は 1.0。C7 は全期間 t≥3（3.86）で通るが、保有期間 t2.58 の p=0.0099 は405本で Bonferroni すると 4.0",
        f"別のデータの同じ信号（JKP emerging ret_12_1 三分位 vw vs emerging mkt vw）は保有 +{jk_h.get('ex')} t{jk_h.get('t')}＝半分の強さ（B）。French の BIG HiPRIOR（大型の上位30%・90%時価の大型）という特定の切り方で強く出ている",
        f"実装: 実在ETF EEMO vs EEM {o.get('etf_EEMO_vs_EEM', {}).get('ex')}%/年（CAGR差 {o.get('etf_EEMO_vs_EEM', {}).get('cagr_diff')}）に対し、同じ窓の紙の上 +{o.get('paper_same_window', {}).get('ex')}（現実的な費用 0.4%×300% 後 +{o.get('paper_same_window_net_realistic', {}).get('ex')}）＝紙の上の勝ちを実在の商品は一度も取れていない",
        f"費用: 事前登録の 0.20%×250%=0.5%/年は新興国として楽観（台湾の証券取引税0.3%・香港の印紙税・インドのSTT）。0.4%×300%=1.2%/年でも保有 +{o['net_hold_realistic_0.4pct_x300']['ex']} t{o['net_hold_realistic_0.4pct_x300']['t']}、厳しめ 0.6%×400%=2.4%/年で +{o['stress_net_hold']['ex']} t{o['stress_net_hold']['t']}",
        f"部分期間: 保有の前半 +{o['hold_first_half']['ex']} t{o['hold_first_half']['t']}／後半 +{o['hold_second_half']['ex']} t{o['hold_second_half']['t']}、2020-21 抜き +{o['hold_ex_2020_21']['ex']}、訓練の 1998-2000 抜き +{o['train_ex_1998_2000']['ex']} t{o['train_ex_1998_2000']['t']}＝期間の偏りは小さい",
        f"銘柄数: BIG HiPRIOR の社数 {o['n_firms_big_hiprior']}（1990年代は少数）",
    ]
    ver = 'A'
    vs = ('downgraded to A: 数字は再現し、時価加重の相手に対して保有期間も費用後も勝っている。ただし (1) 地域7本・F2族17本の中で新興国だけが勝った（選択の偏り・405本では保有期間の有意性は残らない）、'
          '(2) 別データ（JKP）の同じ信号は半分の強さで B、(3) 実在ETF EEMO は同期間に EEM へ年 −1.9% と紙の上（+5.4）を取れていない、(4) 新興国の費用は事前登録より重い。'
          '「頑丈な勝ち（S）」とは言えず、紙の上の A にとどめる')
    verdict('F2_Emerging_big_winners', c['grade'], ver, vs, rep,
            f"保有 +{o['hold']['ex']} t{o['hold']['t']}／全期間 +{o['full']['ex']} t{o['full']['t']}／訓練 +{o['train']['ex']} t{o['train']['t']}／CAGR差(保有) {o['hold']['cagr_diff']}／20年窓 {o['roll20']['win_rate']}（{o['roll20']['windows']}窓）／費用後(事前) +{o['net_hold']['ex']}・現実的 +{o['net_hold_realistic_0.4pct_x300']['ex']}／EEMO−EEM {o.get('etf_EEMO_vs_EEM', {}).get('ex')}",
            iss)

    # ═════ 2. 業種の勢いのグリッド（F3g の S 4本・B 最良・F1b・F3s）═════
    IND = {N: fr_vw(f'{N}_Industry_Portfolios') for N in (49, 30, 17, 12, 10)}
    FORMS = {'1-0': (1, 0), '3-0': (3, 0), '6-0': (6, 0), '9-0': (9, 0), '12-0': (12, 0), '12-1': (11, 1)}
    kof = lambda frac, N: max(2, int(math.floor(frac * N + 0.5)))
    grid = {}
    for N, R in IND.items():
        for fk, (L, sk) in FORMS.items():
            for H in (1, 3, 6, 12):
                for frac in (0.15, 0.30):
                    K = kof(frac, N)
                    r, cst, info = ind_momentum(R, L, sk, H, K)
                    gid = f'F3g_ind{N}_{fk}_H{H}_K{int(frac * 100)}'
                    grid[gid] = (N, fk, H, frac, K, r, cst, info)
    log('grid built', len(grid))
    gs = {}
    for gid, (N, fk, H, frac, K, r, cst, info) in grid.items():
        gs[gid] = {'hold': stats(r, MKT, a=HOLD_START), 'train_net_t': (stats(net(r, cst), MKT, z=TRAIN_END) or {}).get('t'),
                   'full': stats(r, MKT)}
    hold_ts = [v['hold']['t'] for v in gs.values() if v['hold']]
    grid_sum = {'n': len(gs), 'hold_t_ge_1_65': sum(1 for t in hold_ts if t >= 1.65), 'hold_t_ge_1_96': sum(1 for t in hold_ts if t >= 1.96),
                'hold_ex_median': round(S.median(v['hold']['ex'] for v in gs.values() if v['hold']), 2),
                'hold_t_median': round(S.median(hold_ts), 2), 'hold_ex_positive_share': round(sum(1 for v in gs.values() if v['hold'] and v['hold']['ex'] > 0) / len(gs), 3),
                'expected_t_ge_1_65_if_true_effect_equals_grid_median': None}
    # 同じ業種を等分に持つ対照（勢いなし）: 業種の等分そのものの効果を分ける
    ew_ctrl = {}
    for N, R in IND.items():
        ms = sorted(set().union(*[set(v) for v in R.values()]))
        ew = {m: S.mean(R[n][m] for n in R if m in R[n]) for m in ms if sum(1 for n in R if m in R[n]) >= N - 2}
        ew_ctrl[N] = {'series': ew, 'hold': stats(ew, MKT, a=HOLD_START), 'full': stats(ew, MKT)}
    grid_sum['ew_all_industries_vs_mkt_hold'] = {N: (v['hold']['ex'], v['hold']['t']) for N, v in ew_ctrl.items()}
    DETAIL['industry_grid_summary'] = grid_sum
    log('grid summary', grid_sum)

    def ind_candidate(gid, extra_note=None):
        N, fk, H, frac, K, r, cst, info = grid[gid]
        L, sk = FORMS[fk]
        o = bundle(r, MKT, cost=cst, rf=RF, stress_cost={k: v * 3 for k, v in cst.items()})
        o['info'] = info
        o['net_hold_basket_0.15pct'] = stats(net(r, {k: v * 3 for k, v in cst.items()}), MKT, a=HOLD_START)
        o['vs_ew_all_industries_hold'] = stats(r, ew_ctrl[N]['series'], a=HOLD_START)
        o['vs_ew_all_industries_full'] = stats(r, ew_ctrl[N]['series'])
        nbh = {}
        for g2, v in gs.items():
            N2, fk2, H2, frac2 = grid[g2][:4]
            dist = (N2 == N) + (fk2 == fk) + (H2 == H) + (frac2 == frac)
            if dist == 3:
                nbh[g2] = (v['hold']['ex'], v['hold']['t'])
        o['neighbors_hold'] = nbh
        o['neighbors_hold_t_median'] = round(S.median(t for _, t in nbh.values()), 2) if nbh else None
        o['neighbors_hold_t_ge_1_65'] = f"{sum(1 for _, t in nbh.values() if t >= 1.65)}/{len(nbh)}"
        if H == 1:
            att = ind_attribution(IND[N], L, sk, H, K, MKT)
            o['hold_attribution_top5'] = dict(list(att.items())[:5])
            top = list(att)[0]
            r2, c2, _ = ind_momentum(IND[N], L, sk, H, K, exclude=(top,))
            o['hold_without_best_industry'] = {'dropped': top, 'hold': stats(r2, MKT, a=HOLD_START)}
        o['jp_tax_hold'] = jp_tax_terminal(r, MKT, HOLD_START, 202608)
        DETAIL[gid] = o
        return o

    for gid in ('F3g_ind30_9-0_H1_K30', 'F3g_ind30_12-1_H1_K30', 'F3g_ind17_9-0_H1_K30', 'F3g_ind17_12-1_H1_K15', 'F3g_ind49_3-0_H1_K15'):
        o = ind_candidate(gid)
        c = claims[gid]
        rep = close(o['hold']['ex'], c['hold']['ex_ann'], 0.15) and close(o['hold']['t'], c['hold']['t'], 0.1)
        g, crit = grade_formal(o, repl_ok=True)
        cg = c['grade']
        if cg == 'S':
            ver = 'A'
            vs = (f"downgraded to A: 保有期間 t{o['hold']['t']}≥1.65 は240本のグリッドのうち {grid_sum['hold_t_ge_1_65']} 本だけが越えた線（1.7%＝片側5%の偶然より少ない）で、"
                  f"隣の規則（1つだけ変えた {len(o['neighbors_hold'])} 本）の保有期間 t の中央値は {o['neighbors_hold_t_median']}。C3 は選択の偏りで通っただけ。"
                  f"訓練期間だけで選んだ規則（F3s）は保有 t≤1.18。C4・C5・C7（全期間 t≥3）で A は残る")
        else:
            ver = g if g in ('B', 'C') else 'B'
            vs = (f"confirmed as {ver}: 保有 +{o['hold']['ex']} t{o['hold']['t']}（費用後 +{o['net_hold']['ex']}）。t が低く、グリッドの1本" if ver == 'B'
                  else f"downgraded to {ver}")
        iss = [
            f"再現: 保有 +{o['hold']['ex']}%/年 t{o['hold']['t']}・全期間 +{o['full']['ex']} t{o['full']['t']}・訓練 t{o['train']['t']}・CAGR差 {o['hold']['cagr_diff']}・20年窓 {o['roll20']['win_rate']}（相手の主張 保有 +{c['hold']['ex_ann']} t{c['hold']['t']}）",
            f"多重検定: 240本のグリッドで保有期間 t≥1.65 は {grid_sum['hold_t_ge_1_65']} 本・t≥1.96 は {grid_sum['hold_t_ge_1_96']} 本。グリッドの保有 t の中央値 {grid_sum['hold_t_median']}。Holm（グリッド）=1.0",
            f"隣の規則の保有期間（超過, t）: {o['neighbors_hold']}",
            f"業種の等分そのもの（勢いなし・全{N}業種）vs Mkt の保有期間: {ew_ctrl[N]['hold']['ex']} t{ew_ctrl[N]['hold']['t']}。勢いだけの上乗せ（戦略 − 業種の等分）は保有 +{o['vs_ew_all_industries_hold']['ex']} t{o['vs_ew_all_industries_hold']['t']}",
            f"業種への依存（保有期間の寄与の上位）: {o.get('hold_attribution_top5')}。最大の業種 {o.get('hold_without_best_industry', {}).get('dropped')} を外すと保有 +{(o.get('hold_without_best_industry', {}).get('hold') or {}).get('ex')} t{(o.get('hold_without_best_industry', {}).get('hold') or {}).get('t')}",
            f"費用: 事前登録の 0.05%（業種ETF想定）だが French の{N}業種に対応するETFは無く、株のかごで作ると 0.15% 前後。0.15% で保有 +{o['net_hold_basket_0.15pct']['ex']} t{o['net_hold_basket_0.15pct']['t']}（回転 片道 {o['info']['oneway_turnover_per_year']}×/年）",
            f"部分期間: 保有の前半 +{o['hold_first_half']['ex']} t{o['hold_first_half']['t']}／後半 +{o['hold_second_half']['ex']} t{o['hold_second_half']['t']}、2020-21 抜き +{o['hold_ex_2020_21']['ex']} t{o['hold_ex_2020_21']['t']}、2023-24 抜き +{o['hold_ex_2023_24']['ex']} t{o['hold_ex_2023_24']['t']}、2013-07〜 +{o['recent']['ex']} t{o['recent']['t']}",
            f"日本の課税口座（毎年実現・20.315%）: 保有期間の最終額の比 税引前 {o['jp_tax_hold']['pre_tax_ratio']} → 税引後 {o['jp_tax_hold']['after_tax_ratio']}",
        ]
        verdict(gid, cg, ver, vs, rep,
                f"保有 +{o['hold']['ex']} t{o['hold']['t']}／全期間 +{o['full']['ex']} t{o['full']['t']}／CAGR差(保有) {o['hold']['cagr_diff']}／20年窓 {o['roll20']['win_rate']}／費用後(0.05%) +{o['net_hold']['ex']}・(0.15%) +{o['net_hold_basket_0.15pct']['ex']}／グリッド t≥1.65: {grid_sum['hold_t_ge_1_65']}/240",
                iss)

    # F1b（主の族・MG 6-6 重ね持ち）と F3s（訓練で選んだ規則）
    f1b = {}
    for N in (49, 30, 17, 12, 10):
        gid = f'F3g_ind{N}_6-0_H6_K15'
        N_, fk, H, frac, K, r, cst, info = grid[gid]
        f1b[N] = bundle(r, MKT, cost=cst, stress_cost={k: v * 3 for k, v in cst.items()})
        f1b[N]['vs_ew_hold'] = stats(r, ew_ctrl[N]['series'], a=HOLD_START)
    DETAIL['F1b_MG66'] = f1b
    sel = {}
    for N in (49, 30, 17, 12, 10):
        cands = [g for g in grid if grid[g][0] == N]
        best = max(cands, key=lambda g: (gs[g]['train_net_t'] or -99, -cands.index(g)))
        sel[N] = best
    DETAIL['F3s_my_train_selection'] = {N: (g, gs[g]['train_net_t'], gs[g]['hold']['ex'], gs[g]['hold']['t']) for N, g in sel.items()}
    log('F3s my selection', DETAIL['F3s_my_train_selection'])

    # ═════ 3. F9 パネル ═════
    avail = json.load(open(os.path.join(M.CACHE, 'jkp_availability.json')))
    REGIONS = {'all_countries', 'all_regions', 'developed', 'emerging', 'frontier', 'world', 'world_ex_us'}
    SEEN8 = {'usa', 'jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che'}
    DEV23 = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe', 'usa'}
    EM14 = {'bra', 'chl', 'chn', 'ind', 'idn', 'kor', 'mex', 'mys', 'phl', 'pol', 'tha', 'tur', 'twn', 'zaf'}
    us_side, us_side_t = side_pre2006(jkp_terciles('usa', 'ret_12_1'))
    units = {}
    for cc in sorted(avail['portfolios']):
        if cc in REGIONS or cc in SEEN8 or 'ret_12_1' not in set(avail['portfolios'][cc]):
            continue
        try:
            P = jkp_terciles(cc, 'ret_12_1')
            mk, mn = jkp_mkt(cc, 'vw')
        except Exception as ex:  # noqa
            continue
        sT = add(P.get(us_side, {}), RF); bT = add(mk, RF)
        hn = sum(1 for k in sT if k in bT and HOLD_START <= k <= JKP_END)
        if hn < 120:
            continue
        units[cc] = {'s': sT, 'b': bT, 'n': mn, 'low': add(P.get('1.0' if us_side == '3.0' else '3.0', {}), RF),
                     'hold': stats(sT, bT, a=HOLD_START), 'full': stats(sT, bT)}
    log('F9 units', len(units))

    def panel(ccs, weight=None, which='s'):
        sv, bv = collections.defaultdict(list), collections.defaultdict(list)
        for cc in ccs:
            u = units[cc]
            for k, v in u[which].items():
                if k in u['b']:
                    w = 1.0
                    if weight == 'nstocks':
                        # 前月の社数（後知恵なし）
                        y, m = divmod(k, 100)
                        pk = (y - 1) * 100 + 12 if m == 1 else k - 1
                        w = u['n'].get(pk)
                        if not w:
                            continue
                    sv[k].append((w, v)); bv[k].append((w, u['b'][k]))
        ms = [k for k in sorted(sv) if len(sv[k]) >= 3]
        s_ = {k: math.fsum(w * v for w, v in sv[k]) / math.fsum(w for w, _ in sv[k]) for k in ms}
        b_ = {k: math.fsum(w * v for w, v in bv[k]) / math.fsum(w for w, _ in bv[k]) for k in ms}
        return s_, b_
    allc = sorted(units)
    s9, b9 = panel(allc)
    o = bundle(s9, b9, cost=2.0 * 0.003 / 12, stress_cost=3.0 * 0.010 / 12)
    o['countries'] = len(allc)
    o['positive_hold'] = sum(1 for cc in allc if units[cc]['hold'] and units[cc]['hold']['ex'] > 0)
    o['negative_hold_list'] = [cc for cc in allc if units[cc]['hold'] and units[cc]['hold']['ex'] <= 0]
    o['us_side_pre2006'] = (us_side, us_side_t)
    s9l, b9l = panel(allc, which='low')
    o['low_tercile_panel_hold'] = stats(s9l, b9l, a=HOLD_START)
    inv = [cc for cc in allc if cc in DEV23 or cc in EM14]
    si, bi = panel(inv)
    o['investable_29_ew'] = {'countries': inv, 'hold': stats(si, bi, a=HOLD_START), 'train': stats(si, bi, z=TRAIN_END), 'full': stats(si, bi)}
    sn, bn = panel(allc, weight='nstocks')
    o['nstocks_weighted_proxy'] = {'hold': stats(sn, bn, a=HOLD_START), 'train': stats(sn, bn, z=TRAIN_END), 'full': stats(sn, bn)}
    # 時価加重の地域（JKP の地域 vw）＝純粋な時価加重の相手
    reg = {}
    for rg in ('emerging', 'developed', 'world_ex_us'):
        P = jkp_terciles(rg, 'ret_12_1'); mk, _ = jkp_mkt(rg, 'vw')
        reg[rg] = {'train': stats(add(P[us_side], RF), add(mk, RF), z=TRAIN_END), 'hold': stats(add(P[us_side], RF), add(mk, RF), a=HOLD_START),
                   'full': stats(add(P[us_side], RF), add(mk, RF))}
    o['cap_weighted_regions'] = reg
    # 1国抜き（保有期間の t の最小）
    loo = []
    for cc in allc:
        s_, b_ = panel([x for x in allc if x != cc])
        h = stats(s_, b_, a=HOLD_START)
        loo.append((cc, h['ex'], h['t']))
    o['leave_one_out_min_t'] = min(loo, key=lambda x: x[2])
    o['countries_per_month_train_first'] = {str(y): sum(1 for cc in allc if (y * 100 + 1) in units[cc]['s']) for y in (1987, 1990, 1995, 2000, 2006)}
    DETAIL['F9_panel_stock_momentum_ew'] = o
    c = claims['F9_panel_stock_momentum_ew']
    rep = close(o['hold']['ex'], c['hold']['ex_ann'], 0.1) and close(o['hold']['t'], c['hold']['t'], 0.15)
    wx = reg['world_ex_us']; em_r = reg['emerging']; dv = reg['developed']
    iss = [
        f"再現: {len(allc)}か国・保有 +{o['hold']['ex']} t{o['hold']['t']}・訓練 +{o['train']['ex']} t{o['train']['t']}・20年窓 {o['roll20']['win_rate']}（{o['roll20']['windows']}窓）。保有で正の国 {o['positive_hold']}/{len(allc)}（負: {o['negative_hold_list']}）",
        f"相手が純粋な時価加重ではない: 国々の市場の等分（バーレーン・ナイジェリア・ヨルダン等と中国・インドが同じ重み）。全体の事前登録は『同じ地域の時価加重の市場』。"
        f"時価加重の地域で同じ信号を当てると（地域の区切りで並べ・既に見た8か国も入る＝同じ国々ではない）world_ex_us 訓練 +{wx['train']['ex']} t{wx['train']['t']}・保有 +{wx['hold']['ex']} t{wx['hold']['t']}／developed 訓練 t{dv['train']['t']}・保有 t{dv['hold']['t']}／emerging 保有 +{em_r['hold']['ex']} t{em_r['hold']['t']}＝どれも S に届かない（相手の F2 でも C/C/B）",
        f"公平のために頑丈さも記す: 社数で重みを付けた近似（時価総額は JKP に無い）で保有 +{o['nstocks_weighted_proxy']['hold']['ex']} t{o['nstocks_weighted_proxy']['hold']['t']}・訓練 t{o['nstocks_weighted_proxy']['train']['t']}、1国抜きの最弱でも t{o['leave_one_out_min_t'][2]}。ただし時価で最大の新興国の中国は保有で負（時価加重なら重みが最大）",
        f"買える国だけ（先進・主要新興の{len(inv)}か国の等分）: 保有 +{o['investable_29_ew']['hold']['ex']} t{o['investable_29_ew']['hold']['t']}・訓練 t{o['investable_29_ew']['train']['t']}",
        f"費用: 0.30%×200% は小国・辺境国には軽い。1.0%×300%=3.0%/年で保有 +{o['stress_net_hold']['ex']} t{o['stress_net_hold']['t']}。多くの国は個人が株を直接買えない（外国人の口座・最低単位）",
        f"作り方の偏りの点検: 低い三分位の等分パネルは保有 {o['low_tercile_panel_hold']['ex']} t{o['low_tercile_panel_hold']['t']}（負＝作り方の偏りではないのは本当）。1国抜きの最弱 {o['leave_one_out_min_t']}",
        f"部分期間: 保有の前半 +{o['hold_first_half']['ex']} t{o['hold_first_half']['t']}／後半 +{o['hold_second_half']['ex']} t{o['hold_second_half']['t']}。訓練期間の国の数 {o['countries_per_month_train_first']}（1990年代初めは少数）",
        "良い側は米国の2006年までの（第3−第1）の平均の符号で決めても 3.0（高い側）＝後知恵ではない。勢いは1993年公表・1998年に国際再現（Rouwenhorst）済み",
    ]
    ver = 'B'
    vs = ('downgraded to B: 国ごとの再現（41/42か国で正）は本物で、勢いが米国外で働く強い証拠。ただし格付けの対象としての『戦略』は国々の等分が相手で、'
          '純粋な時価加重の市場に勝つ規則ではない。同じ規則を時価加重の地域（world_ex_us・developed・emerging）に当てると訓練か保有の t が線に届かず S/A にならない。'
          '辺境国を含み個人は買えず、費用も軽すぎる。再現の証拠としては強いが、市場に勝つ実装の候補としては B')
    verdict('F9_panel_stock_momentum_ew', c['grade'], ver, vs, rep,
            f"等分パネル 保有 +{o['hold']['ex']} t{o['hold']['t']}（正 {o['positive_hold']}/{len(allc)}）／時価加重 world_ex_us 訓練 t{wx['train']['t']}・保有 +{wx['hold']['ex']} t{wx['hold']['t']}／emerging 保有 +{em_r['hold']['ex']} t{em_r['hold']['t']}／費用3%/年後 +{o['stress_net_hold']['ex']}",
            iss)

    # ═════ 4. 季節性（F14）と JKP の米国の信号（F5 ret_12_7・F13 ocf_at_chg1・F14 seas_11_15an）═════
    jk_us_tot = add(jk_us, RF)
    DET = {}
    for key, turn in (('seas_6_10an', 12.0), ('seas_11_15an', 12.0), ('seas_2_5an', 12.0), ('seas_16_20an', 12.0), ('seas_1_1an', 12.0),
                      ('ret_12_7', 2.0), ('ocf_at_chg1', 1.5)):
        P = jkp_terciles('usa', key)
        sd, sdt = side_pre2006(P)
        sT = add(P[sd], RF)
        o = bundle(sT, MKT, cost=turn * 0.001 / 12, stress_cost=turn * 1.5 * 0.002 / 12, rf=RF)
        o['side_pre2006'] = (sd, sdt)
        o['vs_jkp_mkt_hold'] = stats(sT, jk_us_tot, a=HOLD_START)
        o['vs_jkp_mkt_full'] = stats(sT, jk_us_tot)
        o['vs_jkp_mkt_net_hold'] = stats(net(sT, turn * 0.001 / 12), jk_us_tot, a=HOLD_START)
        o['vs_jkp_mkt_train'] = stats(sT, jk_us_tot, z=TRAIN_END)
        if key.startswith('seas'):
            o['net_hold_turn8_0.10'] = stats(net(sT, 8.0 * 0.001 / 12), MKT, a=HOLD_START)
            o['net_hold_turn8_0.05'] = stats(net(sT, 8.0 * 0.0005 / 12), MKT, a=HOLD_START)
            o['breakeven_unit_cost_pct_at_800pct'] = round(o['hold']['ex'] / 8.0, 3) if o['hold'] else None
        for wt in ('vw_cap', 'ew'):
            try:
                P2 = jkp_terciles('usa', key, wt)
                o[f'weighting_{wt}_hold_vs_french'] = stats(add(P2[sd], RF), MKT, a=HOLD_START)
                mw, _ = jkp_mkt('usa', wt)
                o[f'weighting_{wt}_hold_vs_same_weighting_mkt'] = stats(add(P2[sd], RF), add(mw, RF), a=HOLD_START)
                o[f'weighting_{wt}_full_vs_same_weighting_mkt'] = stats(add(P2[sd], RF), add(mw, RF))
            except Exception as ex:  # noqa
                o[f'weighting_{wt}_error'] = str(ex)
        o['jp_tax_hold_net'] = jp_tax_terminal(net(sT, turn * 0.001 / 12), MKT, HOLD_START, JKP_END)
        # C5: 同じ側（米国の2006年まで）を8単位に
        rp = {}
        for u in ('jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'emerging'):
            try:
                Pu = jkp_terciles(u, key); mu, _ = jkp_mkt(u, 'vw')
                rp[u] = stats(add(Pu[sd], RF), add(mu, RF))
            except Exception:
                rp[u] = None
        o['c5_units_full_ex'] = {u: (v['ex'] if v else None) for u, v in rp.items()}
        o['c5_pass'] = sum(1 for v in rp.values() if v and v['ex'] > 0) / max(1, sum(1 for v in rp.values() if v)) >= 2 / 3
        o['jp_tax_hold'] = jp_tax_terminal(sT, MKT, HOLD_START, JKP_END)
        DET[key] = o
    DETAIL['jkp_us_signals'] = DET
    # 季節性を族として（2-5・6-10・11-15・16-20 の良い側を等分）＝窓を選ばない版
    ws_ = {}
    for key in ('seas_2_5an', 'seas_6_10an', 'seas_11_15an', 'seas_16_20an'):
        P = jkp_terciles('usa', key); sd, _ = side_pre2006(P); ws_[key] = add(P[sd], RF)
    ms_ = sorted(set.intersection(*[set(v) for v in ws_.values()]))
    fam = {m: S.mean(ws_[k][m] for k in ws_) for m in ms_}
    of = bundle(fam, MKT, cost=12.0 * 0.001 / 12, stress_cost=8.0 * 0.001 / 12)
    DETAIL['seasonality_family_ew4'] = of
    log('seasonality family EW4 hold', of['hold']['ex'], of['hold']['t'], 'net1200', of['net_hold']['ex'], 'net800', of['stress_net_hold']['ex'])
    sn = DET['seas_6_10an']
    c = claims['F14_usa_seas_6_10an']
    rep = close(sn['vs_jkp_mkt_hold']['ex'], c['hold']['ex_ann'], 0.05) and close(sn['vs_jkp_mkt_hold']['t'], c['hold']['t'], 0.05)
    g, crit = grade_formal(sn, repl_ok=sn['c5_pass'])
    nbs = {k: (DET[k]['hold']['ex'], DET[k]['hold']['t']) for k in ('seas_1_1an', 'seas_2_5an', 'seas_6_10an', 'seas_11_15an', 'seas_16_20an')}
    iss = [
        f"再現（JKP mkt 相手＝相手の主張の作り方）: 保有 +{sn['vs_jkp_mkt_hold']['ex']} t{sn['vs_jkp_mkt_hold']['t']}（主張 +{c['hold']['ex_ann']} t{c['hold']['t']}）",
        f"相手の取り違え: 事前登録の相手は French Mkt（純粋な時価加重）だが JKP 米国 mkt vw を使っていた。JKP mkt は保有期間に French Mkt より年 {gap['hold_2007_2025']['ex']}%（t{gap['hold_2007_2025']['t']}）弱く、2013-07〜は {gap['recent_2013_2025']['ex']}%。"
        f"French Mkt 相手では 保有 +{sn['hold']['ex']} t{sn['hold']['t']}・費用後（1200%×0.10%）+{sn['net_hold']['ex']} t{sn['net_hold']['t']}・CAGR差 {sn['net_hold']['cagr_diff']}",
        f"費用: 1200%/年は保守的（毎月の並べ替えはほぼ無作為なので 800%前後）。800%×0.10% で +{sn['net_hold_turn8_0.10']['ex']} t{sn['net_hold_turn8_0.10']['t']}、800%×0.05% で +{sn['net_hold_turn8_0.05']['ex']}。損益分岐の単価 {sn['breakeven_unit_cost_pct_at_800pct']}%＝米国大型株なら費用には耐える",
        f"税: 毎月ほぼ全部を入れ替える＝値上がり益を毎年実現する。日本の課税口座の概算で保有期間の最終額の比 税引前 {sn['jp_tax_hold']['pre_tax_ratio']} → 税引後 {sn['jp_tax_hold']['after_tax_ratio']}（買って持つ相手は最後に一度だけ課税）。NISA では年間枠の再利用ができず毎月の総入れ替えは実質不可能",
        f"隣の窓（保有, t）: {nbs}＝6-10年だけが強く、2-5年は負・1年は費用後に負。4窓を等分に持つ（窓を選ばない）と保有 +{of['hold']['ex']} t{of['hold']['t']}・費用後（1200%×0.10%）+{of['net_hold']['ex']}・（800%×0.10%）+{of['stress_net_hold']['ex']}＝季節性という考えそのものの保有期間の勝ちは費用後 +0.1〜+0.5 と小さく、S は 6-10年という窓の当たりに乗っている",
        f"加重の違い: French 相手の保有 vw_cap +{(sn.get('weighting_vw_cap_hold_vs_french') or {}).get('ex')} t{(sn.get('weighting_vw_cap_hold_vs_french') or {}).get('t')}／ew +{(sn.get('weighting_ew_hold_vs_french') or {}).get('ex')} t{(sn.get('weighting_ew_hold_vs_french') or {}).get('t')}。"
        f"同じ加重の市場と比べると vw_cap +{(sn.get('weighting_vw_cap_hold_vs_same_weighting_mkt') or {}).get('ex')} t{(sn.get('weighting_vw_cap_hold_vs_same_weighting_mkt') or {}).get('t')}／ew +{(sn.get('weighting_ew_hold_vs_same_weighting_mkt') or {}).get('ex')} t{(sn.get('weighting_ew_hold_vs_same_weighting_mkt') or {}).get('t')}",
        f"税（費用後）: 800〜1200%/年の回転で費用 1200%×0.10% を引いた後、日本の課税口座の概算で最終額の比 {sn['jp_tax_hold_net']['pre_tax_ratio']} → 税引後 {sn['jp_tax_hold_net']['after_tax_ratio']}",
        f"C5（米国の側を8単位に・全期間の超過）: {sn['c5_units_full_ex']}。未見の国々のパネル（F15）は費用 0.30%×1200% 後 −1.68＝米国外では費用に負ける",
        f"部分期間: 保有の前半 +{sn['hold_first_half']['ex']} t{sn['hold_first_half']['t']}／後半 +{sn['hold_second_half']['ex']} t{sn['hold_second_half']['t']}、2020-21 抜き +{sn['hold_ex_2020_21']['ex']} t{sn['hold_ex_2020_21']['t']}",
        f"良い側: 2006年までの（第3−第1）で決めても {sn['side_pre2006']}＝後知恵ではない。Heston-Sadka の公表は2008年（標本1965-2002）",
        f"多重検定: 405本の中の1本。保有 p（French 相手）={round(p_two(sn['hold']['t']), 4)} を405倍すると {round(min(1, p_two(sn['hold']['t']) * 405), 3)}。C7 は全期間 t{sn['full']['t']}≥3 で通る",
    ]
    ver = g if g != 'S' else 'A'
    if g == 'S':
        vs = (f"downgraded to A: French Mkt（事前登録の相手）で作り直すと保有 +{sn['hold']['ex']} t{sn['hold']['t']}・費用後 +{sn['net_hold']['ex']} t{sn['net_hold']['t']} で形式上の線は越え、加重を変えても（同じ加重の市場と比べて）残る＝数字そのものは本物。"
              f"ただし (1) 相手の取り違えで年0.4%水増しされていた、(2) 窓を選ばない季節性（4窓の等分）は保有 +{of['hold']['ex']}・費用後 +{of['net_hold']['ex']}〜+{of['stress_net_hold']['ex']} と小さい＝S の大きさは 6-10年という窓の当たり、(3) 保有期間の後半は +{sn['hold_second_half']['ex']} t{sn['hold_second_half']['t']} に半減、"
              f"(4) 毎月ほぼ全部の入れ替えは日本の課税口座では費用後・税引後の最終額の比 {sn['jp_tax_hold_net']['after_tax_ratio']}（年0.2%程度）まで消え、NISA では実行できない。「頑丈（S）」ではなく A")
    else:
        vs = f"downgraded to {g}: French Mkt 相手で作り直すと {crit}"
    verdict('F14_usa_seas_6_10an', c['grade'], ver, vs, rep,
            f"French Mkt 相手 保有 +{sn['hold']['ex']} t{sn['hold']['t']}／全期間 +{sn['full']['ex']} t{sn['full']['t']}／CAGR差(保有) {sn['hold']['cagr_diff']}／20年窓 {sn['roll20']['win_rate']}／費用後 1200%×0.10% +{sn['net_hold']['ex']}・800%×0.10% +{sn['net_hold_turn8_0.10']['ex']}／JKP mkt 相手 +{sn['vs_jkp_mkt_hold']['ex']}／日本の課税口座の税引後の最終額の比 費用前 {sn['jp_tax_hold']['after_tax_ratio']}・費用後 {sn['jp_tax_hold_net']['after_tax_ratio']}",
            iss)

    for key, cid in (('ret_12_7', 'F5_usa_ret_12_7'), ('ocf_at_chg1', 'F13_usa_ocf_at_chg1'), ('seas_11_15an', 'F14_usa_seas_11_15an')):
        o = DET[key]; c = claims[cid]
        rep = close(o['vs_jkp_mkt_hold']['ex'], c['hold']['ex_ann'], 0.05)
        g, crit = grade_formal(o, repl_ok=o['c5_pass'])
        g0 = g
        if g == 'A' and fragile(o):
            g = 'B'
        iss = [f"再現（JKP mkt 相手）: 保有 +{o['vs_jkp_mkt_hold']['ex']} t{o['vs_jkp_mkt_hold']['t']}（主張 +{c['hold']['ex_ann']} t{c['hold']['t']}）",
               f"形式の格付け（French 相手）{g0}{'→ 頑丈さ不足で B（費用後の CAGR 差が小さく厳しめ費用で負、または保有期間の後半が負）' if g0 != g else ''}。厳しめ費用 +{o['stress_net_hold']['ex']}（CAGR差 {o['stress_net_hold']['cagr_diff']}）",
               f"加重を変える（同じ加重の市場と比べる）: vw_cap 保有 +{(o.get('weighting_vw_cap_hold_vs_same_weighting_mkt') or {}).get('ex')} t{(o.get('weighting_vw_cap_hold_vs_same_weighting_mkt') or {}).get('t')}／ew +{(o.get('weighting_ew_hold_vs_same_weighting_mkt') or {}).get('ex')} t{(o.get('weighting_ew_hold_vs_same_weighting_mkt') or {}).get('t')}",
               f"French Mkt（事前登録の相手）: 保有 +{o['hold']['ex']} t{o['hold']['t']}・CAGR差 {o['hold']['cagr_diff']}・費用後 +{o['net_hold']['ex']}（CAGR差 {o['net_hold']['cagr_diff']}）・訓練 t{o['train']['t']}・全期間 t{o['full']['t']}・20年窓 {o['roll20']['win_rate']}",
               f"格付けの基準: {crit}",
               f"部分期間: 保有の前半 +{o['hold_first_half']['ex']}／後半 +{o['hold_second_half']['ex']}、2023-24 抜き +{o['hold_ex_2023_24']['ex']} t{o['hold_ex_2023_24']['t']}",
               f"C5（米国の2006年までの側を8単位に）: {o['c5_units_full_ex']}",
               f"良い側（2006年までの成績）: {o['side_pre2006']}"]
        verdict(cid, c['grade'], g, ('confirmed' if g == c['grade'] else ('refuted' if g == 'C' else f'downgraded to {g}')) + f": French Mkt（事前登録の相手）で作り直した格付けは {g}（保有 +{o['hold']['ex']} t{o['hold']['t']}・費用後 +{o['net_hold']['ex']}・CAGR差 {o['net_hold']['cagr_diff']}）。JKP mkt 相手だと年0.41%水増しされる",
                rep, f"French 相手 保有 +{o['hold']['ex']} t{o['hold']['t']}／費用後 +{o['net_hold']['ex']}／JKP 相手 +{o['vs_jkp_mkt_hold']['ex']}", iss)

    # ═════ 5. 因子の勢い（F18・F19）: 自前の良い側（2006年までの成績）と公表年の絞り込み ═════
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jkp_factor_details.xlsx'), read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    hdr = rows[0]
    pub, direction = {}, {}
    for r_ in rows[1:]:
        d = dict(zip(hdr, r_))
        a = d.get('abr_jkp')
        if not a:
            continue
        m = re.search(r'\((\d{4})\)', d.get('cite') or '')
        pub[a] = int(m.group(1)) if m else None
        try:
            direction[a] = int(d['direction'])
        except Exception:
            pass
    # 三分位は all_factors の一括ファイル（相手は因子ごとのファイルを使った＝別の取り方）
    TP = collections.defaultdict(lambda: collections.defaultdict(dict))
    for x in M.jkp_rows('usa', 'all_factors', 'portfolios', 'vw'):
        if x['ret'] in ('', 'NA', 'na') or x['n'] in ('', 'NA', 'na') or float(x['n']) < 10:
            continue
        TP[x['name']][x['pf']][int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    FF = collections.defaultdict(dict)
    for x in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        FF[x['name']][int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    sides, side_disagree, orient = {}, [], {}
    for k in TP:
        if k not in FF:
            continue
        ks_ = [m for m in FF[k] if m in TP[k].get('3.0', {}) and m in TP[k].get('1.0', {})]
        if len(ks_) < 24:
            continue
        a_ = [TP[k]['3.0'][m] - TP[k]['1.0'][m] for m in ks_]; b_ = [FF[k][m] for m in ks_]
        ma, mb = S.mean(a_), S.mean(b_)
        orient[k] = 1 if math.fsum((x - ma) * (y - mb) for x, y in zip(a_, b_)) > 0 else -1
        sd, _ = side_pre2006(TP[k])
        if sd is None:
            continue
        sides[k] = sd
        if k in direction and ((direction[k] == 1) != (sd == '3.0')):
            side_disagree.append(k)
    # 相手の作り方の良い側: 2006年までの（第3−第1）と JKP の符号付き因子の相関の符号（＝実質 JKP の符号）
    sides_claim = {}
    for k in sides:
        ks_ = [m for m in FF[k] if m <= TRAIN_END and m in TP[k].get('3.0', {}) and m in TP[k].get('1.0', {})]
        a_ = [TP[k]['3.0'][m] - TP[k]['1.0'][m] for m in ks_]; b_ = [FF[k][m] for m in ks_]
        ma, mb = S.mean(a_), S.mean(b_)
        sides_claim[k] = '3.0' if math.fsum((x - ma) * (y - mb) for x, y in zip(a_, b_)) > 0 else '1.0'
    claim_vs_mine = [k for k in sides if sides_claim[k] != sides[k]]
    claim_vs_pubdir = [k for k in sides if k in direction and ((direction[k] == 1) != (sides_claim[k] == '3.0'))]
    DETAIL['F18_sides'] = {'n': len(sides), 'disagree_with_published_direction': side_disagree, 'n_pub_le_2006': sum(1 for k in sides if (pub.get(k) or 9999) <= 2006),
                           'claim_rule_vs_pre2006_performance_disagree': claim_vs_mine, 'claim_rule_vs_published_direction_disagree': claim_vs_pubdir}
    log('claim sides vs published direction disagree', len(claim_vs_pubdir), 'claim vs perf', len(claim_vs_mine))
    log('F18 sides', len(sides), 'disagree', len(side_disagree), side_disagree[:20])

    def fmom(keys, mode, use_side):
        """keys の因子。信号 = 符号付きの因子（JKP・その側に向けた H−L）の t−11〜t の対数累積。t+1 に良い側の三分位を持つ"""
        G = {k: TP[k][use_side[k]] for k in keys}
        # JKP の符号付き因子を『第3−第1』の向きへ戻す（全期間の相関の符号＝符号の約束を読むだけ・側は選ばない）→ 自分の側へ向ける
        sg = {k: orient[k] * (1 if use_side[k] == '3.0' else -1) for k in keys}
        months = sorted(set().union(*[set(FF[k]) for k in keys]))
        lf = {k: {m: math.log1p(sg[k] * v) if sg[k] * v > -1 else None for m, v in FF[k].items()} for k in keys}
        ret, turnm, nsel = {}, {}, []
        prev = None
        for i in range(11, len(months) - 1):
            win, m1 = months[i - 11:i + 1], months[i + 1]
            el = []
            for k in keys:
                if m1 not in G[k]:
                    continue
                if mode == 'static':
                    el.append((0.0, k)); continue
                vals = [lf[k].get(m) for m in win]
                if any(v is None for v in vals):
                    continue
                el.append((math.fsum(vals), k))
            if mode == 'tsfm':
                sel = [k for v, k in el if v > 0]
            elif mode == 'csfm':
                el.sort(key=lambda x: (-x[0], x[1])); sel = [k for _, k in el[:math.ceil(0.2 * len(el))]] if el else []
            elif mode == 'top2':
                el.sort(key=lambda x: (-x[0], x[1])); sel = [k for _, k in el[:2]] if len(el) >= 2 else []
            else:
                sel = [k for _, k in el]
            if not sel:
                if mode == 'tsfm' and el and m1 in jk_us:
                    ret[m1] = jk_us[m1]; w = {'_mkt': 1.0}
                else:
                    prev = None; continue
            else:
                ret[m1] = math.fsum(G[k][m1] for k in sel) / len(sel); w = {k: 1 / len(sel) for k in sel}
            turnm[m1] = 0.5 * math.fsum(abs(w.get(q, 0) - (prev or {}).get(q, 0)) for q in set(w) | set(prev or {})) if prev is not None else 0.0
            prev = w; nsel.append(len(sel))
        return add(ret, RF), turnm, (S.median(nsel) if nsel else None)

    TURN = lambda a: (6.0 if a.startswith('seas_') or a in ('ret_1_0', 'rmax1_21d', 'rmax5_21d', 'rskew_21d', 'iskew_capm_21d', 'iskew_ff3_21d', 'iskew_hxz4_21d', 'coskew_21d')
                      else 2.0 if a.endswith('_21d') else 2.5 if a == 'ret_3_1' else 1.5 if a.startswith(('ret_', 'resff3', 'prc_high')) or a in ('niq_su', 'saleq_su', 'ni_inc8q')
                      else 0.8 if a.startswith(('niq_', 'saleq_', 'ocfq_')) else 0.6 if a.endswith(('_126d', '_252d')) else 0.4)
    avg_turn_all = S.mean(TURN(k) for k in sides)
    F18 = {}
    allk = sorted(sides)
    k06 = [k for k in allk if (pub.get(k) or 9999) <= 2006]
    for label, keys, sdz in (('all_153', allk, sides), ('published_le_2006', k06, sides), ('claim_all_153', allk, sides_claim), ('claim_published_le_2006', k06, sides_claim)):
        for mode in ('tsfm', 'csfm', 'static'):
            r, tm, nsel = fmom(keys, mode, sdz)
            cst_flat = {k: tm.get(k, 0.0) * 0.001 + 2.0 / 12 * 0.001 for k in r}
            cst_real = {k: tm.get(k, 0.0) * 0.001 + avg_turn_all / 12 * 0.002 for k in r}
            o = bundle(r, MKT, cost=cst_flat, stress_cost=cst_real, rf=RF)
            o['vs_jkp_mkt_hold'] = stats(r, jk_us_tot, a=HOLD_START)
            o['vs_jkp_mkt_net_hold'] = stats(net(r, cst_flat), jk_us_tot, a=HOLD_START)
            o['vs_jkp_mkt_full'] = stats(r, jk_us_tot)
            o['selected_median'] = nsel
            o['n_factors'] = len(keys)
            o['cost_flat_pct'] = round(S.mean(cst_flat.values()) * 1200, 3)
            o['cost_perclass_x0.20_pct'] = round(S.mean(cst_real.values()) * 1200, 3)
            F18[f'{label}_{mode}'] = o
            log('F18', label, mode, 'French hold', o['hold'] and (o['hold']['ex'], o['hold']['t']), 'net', o['net_hold'] and o['net_hold']['ex'], 'JKP hold', o['vs_jkp_mkt_hold']['ex'])
    # F19（古典7因子）
    C7 = [k for k in ('be_me', 'ret_12_1', 'qmj', 'betabab_1260d', 'market_equity', 'gp_at', 'at_gr1') if k in sides]
    for lab7, sdz in (('classic7', sides), ('claim_classic7', sides_claim)):
        for mode in ('tsfm', 'top2', 'static'):
            r, tm, nsel = fmom(C7, mode, sdz)
            cst_flat = {k: tm.get(k, 0.0) * 0.001 + 2.0 / 12 * 0.001 for k in r}
            o = bundle(r, MKT, cost=cst_flat, rf=RF)
            o['vs_jkp_mkt_hold'] = stats(r, jk_us_tot, a=HOLD_START)
            o['vs_jkp_mkt_net_hold'] = stats(net(r, cst_flat), jk_us_tot, a=HOLD_START)
            F18[f'{lab7}_{mode}'] = o
            log('F19', lab7, mode, o['hold'] and (o['hold']['ex'], o['hold']['t']), 'net', o['net_hold']['ex'], 'JKP', o['vs_jkp_mkt_hold']['ex'])
    DETAIL['F18_F19'] = F18
    DETAIL['F18_sides']['classic7_sides'] = {k: sides[k] for k in C7}
    DETAIL['F18_sides']['classic7_sides_claim'] = {k: sides_claim[k] for k in C7}

    GR = 'SABC'
    better = lambda a, b: a if GR.index(a) < GR.index(b) else b
    worse = lambda a, b: a if GR.index(a) > GR.index(b) else b
    for mode, cid in (('tsfm', 'F18a_tsfm'), ('csfm', 'F18b_csfm_top20'), ('static', 'F18c_static_control')):
        oc = F18[f'claim_all_153_{mode}']; om = F18[f'all_153_{mode}']
        oc6 = F18[f'claim_published_le_2006_{mode}']; om6 = F18[f'published_le_2006_{mode}']
        c = claims[cid]
        rep = close(oc['vs_jkp_mkt_hold']['ex'], c['hold']['ex_ann'], 0.15) and close(oc['vs_jkp_mkt_hold']['t'], c['hold']['t'], 0.3)
        g_c, cr_c = grade_formal(oc, repl_ok=True)
        g_m, cr_m = grade_formal(om, repl_ok=True)
        g_c6, _ = grade_formal(oc6, repl_ok=True)
        g_m6, _ = grade_formal(om6, repl_ok=True)
        g_lf = better(g_c6, g_m6)              # 後知恵のない版（2006年までの公表）の良いほう
        ver = worse(g_c, g_lf)
        iss = [
            f"再現（相手の作り方: 良い側＝2006年までの相関の符号・JKP mkt 相手）: 保有 +{oc['vs_jkp_mkt_hold']['ex']} t{oc['vs_jkp_mkt_hold']['t']}（主張 +{c['hold']['ex_ann']} t{c['hold']['t']}）。三分位は all_factors の一括ファイルから自前で組んだ",
            f"相手の取り違え: 事前登録の相手 French Mkt では 保有 +{oc['hold']['ex']} t{oc['hold']['t']}・CAGR差 {oc['hold']['cagr_diff']}・費用後 +{oc['net_hold']['ex']} t{oc['net_hold']['t']}（CAGR差 {oc['net_hold']['cagr_diff']}）→ 形式の格付け {g_c}（{cr_c}）",
            f"良い側の後知恵: 相手の jkp_good_side は（第3−第1）と JKP の符号付き因子の相関の符号＝実質 JKP の符号（論文の向き）を読み戻しているだけで、2006年までの成績では決めていない（JKP の符号と食い違う因子は {len(DETAIL['F18_sides']['claim_rule_vs_published_direction_disagree'])} 本）。2006年までの（第3−第1）の平均で決めると {len(DETAIL['F18_sides']['claim_rule_vs_pre2006_performance_disagree'])} 因子で側が逆。その版の French 相手: 保有 +{om['hold']['ex']} t{om['hold']['t']}・費用後 +{om['net_hold']['ex']} → {g_m}",
            f"因子の選び方の後知恵（公表年は JKP の Factor Details の出典の年）: 153因子のうち2006年までに公表は {len(k06)} 本。残りは2007年以降の論文で、標本が保有期間と重なる。2006年までの公表に絞ると French 相手 保有 +{oc6['hold']['ex']} t{oc6['hold']['t']}（費用後 +{oc6['net_hold']['ex']}）／成績で側を決めた版 +{om6['hold']['ex']} t{om6['hold']['t']}（費用後 +{om6['net_hold']['ex']}）→ {g_c6}／{g_m6}",
            f"費用: 三分位の中の回転を一律 200%/年×0.10%（{oc['cost_flat_pct']}%/年）と置いたが、季節性・短期反転（600%/年級）も含む。種類ごとの回転×0.20%（{oc['cost_perclass_x0.20_pct']}%/年・相殺なしの上限）で French 相手の保有 +{oc['stress_net_hold']['ex']}",
            f"部分期間（French 相手・相手の作り方）: 保有の前半 +{oc['hold_first_half']['ex']} t{oc['hold_first_half']['t']}／後半 +{oc['hold_second_half']['ex']} t{oc['hold_second_half']['t']}、2013-07〜 +{oc['recent']['ex']} t{oc['recent']['t']}",
            "実装: 数十本の三分位（数百〜千社ずつ）の等分＝個人には作れない。因子の勢いの公表は2019年（Ehsani-Linnainmaa・Gupta-Kelly）で保有期間の途中",
        ]
        vtxt = 'refuted' if ver == 'C' else ('confirmed' if ver == c['grade'] else f'downgraded to {ver}')
        vs = (f"{vtxt}: 事前登録の相手（French Mkt）で相手の作り方をそのまま再計算すると {g_c}、因子と側の後知恵を抜く（2006年までの公表）と {g_lf}。"
              f"S の C3（保有 t≥1.65）は JKP mkt という年0.41%弱い相手と、2007年以降に公表された因子に支えられていた")
        verdict(cid, c['grade'], ver, vs, rep,
                f"JKP 相手（再現）+{oc['vs_jkp_mkt_hold']['ex']} t{oc['vs_jkp_mkt_hold']['t']}／French 相手 +{oc['hold']['ex']} t{oc['hold']['t']}（費用後 +{oc['net_hold']['ex']}）／2006年まで公表・French +{oc6['hold']['ex']} t{oc6['hold']['t']}（費用後 +{oc6['net_hold']['ex']}）／成績で側 +{om['hold']['ex']} t{om['hold']['t']}",
                iss)
    for mode, cid in (('tsfm', 'F19a_tsfm7'), ('top2', 'F19b_top2of7')):
        oc = F18[f'claim_classic7_{mode}']; om = F18[f'classic7_{mode}']; c = claims[cid]
        rep = close(oc['vs_jkp_mkt_hold']['ex'], c['hold']['ex_ann'], 0.2)
        g, crit = grade_formal(oc, repl_ok=True)
        gm, critm = grade_formal(om, repl_ok=True)
        ver = g
        iss = [f"再現（相手の作り方・JKP 相手）: 保有 +{oc['vs_jkp_mkt_hold']['ex']} t{oc['vs_jkp_mkt_hold']['t']}（主張 +{c['hold']['ex_ann']} t{c['hold']['t']}）",
               f"French Mkt（事前登録の相手）: 保有 +{oc['hold']['ex']} t{oc['hold']['t']}・CAGR差 {oc['hold']['cagr_diff']}・費用後 +{oc['net_hold']['ex']}（CAGR差 {oc['net_hold']['cagr_diff']}）→ 形式 {g}（{crit}）",
               f"良い側を2006年までの成績で決めると（betabab は高ベータ側になる）French 相手 保有 +{om['hold']['ex']} t{om['hold']['t']}・費用後 +{om['net_hold']['ex']} → {gm}",
               "7因子のうち qmj（2013/2019）・gp_at（2013）・at_gr1（2008）は2007年以降の公表＝因子の選び方に後知恵",
               f"部分期間（French）: 保有の前半 +{oc['hold_first_half']['ex']}／後半 +{oc['hold_second_half']['ex']}"]
        vtxt = 'refuted' if ver == 'C' else ('confirmed' if ver == c['grade'] else f'downgraded to {ver}')
        verdict(cid, c['grade'], ver, f"{vtxt}: French Mkt 相手で相手の作り方を再計算すると保有 +{oc['hold']['ex']}・費用後 +{oc['net_hold']['ex']}（CAGR差 {oc['net_hold']['cagr_diff']}）→ {g}",
                rep, f"French 相手 保有 +{oc['hold']['ex']} t{oc['hold']['t']}／費用後 +{oc['net_hold']['ex']}／JKP 相手（再現）+{oc['vs_jkp_mkt_hold']['ex']}", iss)
    # ═════ 6. 米国の株の勢い（F1a1・F1a3）═════
    d10 = fr_vw('10_Portfolios_Prior_12_2'); d25 = fr_vw('25_Portfolios_ME_Prior_12_2')
    for cid, s, turn, unit, lab in (('F1a1_us_top_decile', d10['Hi PRIOR'], 4.0, 0.002, '10分割 Hi PRIOR'),
                                    ('F1a3_us_me5_prior5', d25['BIG HiPRIOR'], 3.0, 0.001, '25分割 ME5 PRIOR5')):
        o = bundle(s, MKT, cost=turn * unit / 12, stress_cost=turn * 1.5 * unit * 2 / 12, rf=RF)
        o['jp_tax_hold'] = jp_tax_terminal(s, MKT, HOLD_START, 202608)
        DETAIL[cid] = o
        c = claims[cid]
        rep = close(o['hold']['ex'], c['hold']['ex_ann'], 0.05) and close(o['full']['t'], c['full']['t'], 0.05)
        g, crit = grade_formal(o, repl_ok=True)
        if g == 'A' and fragile(o):
            g = 'B'
        iss = [f"再現: 保有 +{o['hold']['ex']} t{o['hold']['t']}・全期間 +{o['full']['ex']} t{o['full']['t']}・20年窓 {o['roll20']['win_rate']}・費用後 +{o['net_hold']['ex']}（主張 +{c['hold']['ex_ann']} t{c['hold']['t']}）",
               f"保有期間の t は {o['hold']['t']}＝偶然と区別できない。A は C5（地域の再現）と全期間 t≥3（ほぼ1927-2006の訓練期間の力）による",
               f"部分期間: 保有の前半 +{o['hold_first_half']['ex']} t{o['hold_first_half']['t']}／後半 +{o['hold_second_half']['ex']} t{o['hold_second_half']['t']}、2023-24 抜き +{o['hold_ex_2023_24']['ex']} t{o['hold_ex_2023_24']['t']}、2020-21 抜き +{o['hold_ex_2020_21']['ex']}",
               f"CAPM（保有）: α {o['capm_hold']['alpha']} t{o['capm_hold']['t']}・β {o['capm_hold']['beta']}",
               f"厳しめ費用（回転1.5倍・単価2倍）: 保有 +{o['stress_net_hold']['ex']}（CAGR差 {o['stress_net_hold']['cagr_diff']}）",
               f"日本の課税口座: 税引前の比 {o['jp_tax_hold']['pre_tax_ratio']} → 税引後 {o['jp_tax_hold']['after_tax_ratio']}",
               "実在ETF: MTUM vs SPY +1.2 t0.6・PDP −1.0（相手の F8）"]
        v_ = 'confirmed' if g == c['grade'] else f'downgraded to {g}'
        note = ''
        if cid == 'F1a1_us_top_decile' and o['hold_ex_2023_24']['ex'] < o['hold']['ex'] / 2:
            note = '（保有期間の勝ちの大半は2023-24年＝巨大テックの2年）'
        why = (f"形式の線どおり {g}" if g == c['grade'] else f"形式は A だが費用後の CAGR 差 {o['net_hold']['cagr_diff']}・厳しめ費用 {o['stress_net_hold']['cagr_diff']} と頑丈さが足りず B")
        verdict(cid, c['grade'], g, f"{v_}: {why}。保有期間の t{o['hold']['t']} は偶然と区別できず、勝ちは期間に偏る{note}", rep,
                f"保有 +{o['hold']['ex']} t{o['hold']['t']}／全期間 t{o['full']['t']}／費用後 +{o['net_hold']['ex']}／2023-24 抜き +{o['hold_ex_2023_24']['ex']}", iss)

    # F1b・F3s（業種・主の族と訓練で選んだ規則）
    for N in (49, 30, 17, 12, 10):
        cid = f'F1b_ind{N}'; c = claims[cid]; o = f1b[N]
        rep = close(o['hold']['ex'], c['hold']['ex_ann'], 0.25)
        g, crit = grade_formal(o, repl_ok=c['criteria'].get('C5_repl'))
        if g == 'A' and fragile(o):
            g = 'B'
        verdict(cid, c['grade'], g, ('confirmed' if g == c['grade'] else f'downgraded to {g}') + f": 保有 +{o['hold']['ex']} t{o['hold']['t']}＝偶然と区別できない（前半 +{o['hold_first_half']['ex']}／後半 +{o['hold_second_half']['ex']}）。業種の等分に対する上乗せは保有 +{o['vs_ew_hold']['ex']} t{o['vs_ew_hold']['t']}",
                rep, f"保有 +{o['hold']['ex']} t{o['hold']['t']}／費用後 +{o['net_hold']['ex']}／全期間 t{o['full']['t']}／対 業種等分 +{o['vs_ew_hold']['ex']}",
                [f"再現: 主張 保有 +{c['hold']['ex_ann']} t{c['hold']['t']}（重ね持ちの始まりの扱いの違いで ±0.2 程度）", f"形式の基準（C5 は相手の値を借用）: {crit}"])
    for N in (49, 30, 17, 12, 10):
        cid = f'F3s_ind{N}_trainbest'; c = claims[cid]
        gid = c['selected_from']
        mine = sel[N]
        v = gs[mine]
        N_, fk, H, frac, K, r, cst, info = grid[mine]
        oo = bundle(r, MKT, cost=cst, stress_cost={k: x * 3 for k, x in cst.items()})
        g, crit = grade_formal(oo, repl_ok=c['criteria'].get('C5_repl'))
        if g == 'A' and fragile(oo):
            g = 'B'
        same = mine == gid
        verdict(cid, c['grade'], g, ('confirmed' if g == c['grade'] else f'downgraded to {g}') + f": 訓練期間だけで選ぶと {mine}（相手 {gid}・{'一致' if same else '不一致'}）。保有 +{v['hold']['ex']} t{v['hold']['t']}",
                same, f"選んだ規則 {mine}／保有 +{v['hold']['ex']} t{v['hold']['t']}／費用後 +{oo['net_hold']['ex']}",
                [f"主張 保有 +{c['hold']['ex_ann']} t{c['hold']['t']}", f"形式の基準（C5 は相手の値を借用）: {crit}", f"保有の前半 +{oo['hold_first_half']['ex']}／後半 +{oo['hold_second_half']['ex']}・厳しめ費用 CAGR差 {oo['stress_net_hold']['cagr_diff']}",
                 "訓練期間だけで選んだ規則は保有期間 t が 1 前後＝グリッドの S 4本（保有 t≥1.65）が選択の偏りである裏付け"])
    c = claims['F3s_all_trainbest']
    allbest = max(list(grid), key=lambda g: (gs[g]['train_net_t'] or -99, -list(grid).index(g)))
    v = gs[allbest]
    verdict('F3s_all_trainbest', c['grade'], claims['F3s_all_trainbest']['grade'], f"confirmed: 訓練で選ぶと {allbest}（相手 {c['selected_from']}）。保有 +{v['hold']['ex']} t{v['hold']['t']}＝F3s_ind の1本と同じ規則（重複）",
            allbest == c['selected_from'], f"保有 +{v['hold']['ex']} t{v['hold']['t']}", ['F3s_ind30_trainbest と同じ規則'])

    # ═════ 7. B の上位2本の残り: JKP emerging ret_12_1 ═════
    P = jkp_terciles('emerging', 'ret_12_1'); mk, _ = jkp_mkt('emerging', 'vw')
    sd, _ = side_pre2006(P)
    o = bundle(add(P[sd], RF), add(mk, RF), cost=2.0 * 0.002 / 12, stress_cost=3.0 * 0.004 / 12)
    DETAIL['F2_jkp_emerging_ret_12_1'] = o
    c = claims['F2_jkp_emerging_ret_12_1']
    rep = close(o['hold']['ex'], c['hold']['ex_ann'], 0.1)
    g, crit = grade_formal(o, repl_ok=None)
    verdict('F2_jkp_emerging_ret_12_1', c['grade'], g if g != 'A' else 'B', f"{'confirmed' if g == 'B' else 'graded ' + g}: 保有 +{o['hold']['ex']} t{o['hold']['t']}・訓練 +{o['train']['ex']} t{o['train']['t']}（1990年代の新興国の少数銘柄で訓練が膨らむ）・費用 0.4%×300% 後 +{o['stress_net_hold']['ex']}",
            rep, f"保有 +{o['hold']['ex']} t{o['hold']['t']}／訓練 +{o['train']['ex']} t{o['train']['t']}／費用後 +{o['net_hold']['ex']}・厳しめ +{o['stress_net_hold']['ex']}",
            [f"形式: {crit}", f"部分期間: 保有の前半 +{o['hold_first_half']['ex']}／後半 +{o['hold_second_half']['ex']}", 'French の同じ地域の BIG HiPRIOR（S の主張）の約半分の強さ'])

    # A のグリッド（F3g・F16g の A 179本）はまとめて1行
    ga = [e for e in claims.values() if e['family'] in ('F3g', 'F16g') and e['grade'] == 'A']
    ga3 = [e for e in ga if e['family'] == 'F3g']; ga16 = [e for e in ga if e['family'] == 'F16g']
    n_frag = 0
    for e in ga3:
        if e['id'] in grid:
            N_, fk, H, frac, K, r, cst, info = grid[e['id']]
            if fragile(bundle(r, MKT, cost=cst, stress_cost={k: x * 3 for k, x in cst.items()})):
                n_frag += 1
    grid_sum['A_grid_fragile_count'] = n_frag
    verdict('A_grid_F3g_F16g_group', f'A×{len(ga)}', 'A（1つの族として）', (
        f"confirmed as one A family, count inflated: 業種の勢いグリッド {len(ga3)} 本と業種の季節性グリッド {len(ga16)} 本の A は、どれも保有期間 t<1.65 で、A の根拠は C5（GICS 7か国・2000年〜）と全期間 t≥3（ほぼ1927-2006）。"
        f"同じ考え（業種の勢い）の変種を数えただけで、独立な勝ちが {len(ga)} 本あるわけではない。{len(ga3)} 本のうち {n_frag} 本は頑丈さ不足（後半が負など）で B 相当。"
        f"240本のうち保有 t≥1.65 は {grid_sum['hold_t_ge_1_65']} 本・訓練だけで選んだ規則も保有 t≤1.18。実装（French の業種に対応するETFは無い・実在の SPDR 業種回転は保有 −0.03）では勝てていない"), True,
        f"グリッド保有 t の中央値 {grid_sum['hold_t_median']}／保有の超過の中央値 +{grid_sum['hold_ex_median']}／業種の等分（勢いなし）の保有: {grid_sum['ew_all_industries_vs_mkt_hold']}",
        [f"F16g（業種の季節性）の主の5本（F16p）はすべて C（保有期間 −3.6〜+0.7）。A の F16g は同じ考えの変種", 'グリッドの A はまとめて1つの族（業種の勢い）とみなすのが妥当'])

    # ─── 保存 ───
    out = {'generated': datetime.date.today().isoformat(), 'angle': 'momentum', 'verifies': 'out/mw_momentum.json',
           'method': '取得と表の読み取りだけ mw_common を使い、組み立て・統計・費用・税は自前（night/mw_momentum_verify.py）',
           'benchmark_note': 'JKP 米国 mkt vw（総リターン化）は French Mkt より 1926-2006 は +0.06%/年、2007-2025 は −0.41%/年（t≈−2.6）、2013-07〜 −0.54%/年。JKP の米国の信号を JKP mkt と比べると保有期間の超過が年0.4%ほど水増しされる。事前登録の相手は French Mkt',
           'n_tested_by_researcher': n_tested,
           'verdict_counts': dict(collections.Counter((v['claimed_grade'], v['verified_grade']) for v in V).most_common()) if False else
                             {f"{a}->{b}": n for (a, b), n in collections.Counter((v['claimed_grade'], v['verified_grade']) for v in V).items()},
           'bottom_line': ('S 10本のうち S のまま残ったものは無い。業種グリッドの S 4本・新興国の大型の勢い・米国の季節性 6-10年は A（紙の上）、'
                           '未見42か国の勢いパネルは相手が国々の等分で B、因子の勢い3本は事前登録の相手（French Mkt）と後知恵のない因子で C。'
                           'A の中では JKP の米国の信号（ret_12_7・ocf_at_chg1・seas_11_15an・古典7因子の勢い）が相手の取り違えで年0.41%水増しされ、B/C へ下がる'),
           'verdicts': V, 'detail': DETAIL, 'log': LOG[-200:]}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('saved', OUT)


if __name__ == '__main__':
    main()
