#!/usr/bin/env python3
"""night/mw_investable_valmom_verify.py — 反証の検証（mw_investable_valmom の S 4本と B 1本）。読むだけ・門の判定には不使用。

対象（研究側の主張・out/mw_investable_valmom.json）
  S: paper:world_ex_us / paper:developed / paper:jpn / paper:world（JKP の割安4本の良い側を等分 50% ＋ 勢い ret_12_1 の良い側 50%）
  B: DODFX（Dodge & Cox International）vs EFA

独立性
  - mw_common からは『取得』（get・ff_factors・french_tables の読み取り）だけを使う。
  - JKP の三分位 CSV の読み取り・被覆率・良い側（米国 ≤2006 の第3−第1 の平均の符号で自前に決める）・合成・
    超過・Newey-West t・CAGR 差・20年窓・積立・費用・年ごとの分解・Holm は全部ここで書き直した。
  - DODFX / EFA / VGTSX は Yahoo の生 JSON（調整後終値）を自分で月次に直し、Morningstar の年次で自前に検算する。

使い方: python3 night/mw_investable_valmom_verify.py → out/mw_investable_valmom_verify.json
"""
import collections, csv, datetime, io, json, math, os, sys, zipfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけに使う

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_investable_valmom_verify.json')
CLAIM = json.load(open(os.path.join(BASE, 'out', 'mw_investable_valmom.json')))
JKP_URL = 'https://jkpfactors-data.s3.amazonaws.com/public/{sub}%5B{r}%5D_%5B{k}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
TRAIN_END, HOLD_START, RECENT_START = 200612, 200701, 201307
JKP_END = 202512
VALUE4 = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
MOM = 'ret_12_1'
NEED = VALUE4 + [MOM, 'ret_6_1']
DEV = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
       'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe', 'usa'}  # MSCI の先進国23か国
PROGRAM_BONF_T = 4.35


def ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


def rr(x, n=2):
    return None if x is None else round(float(x), n)


# ───────────────────────── 取得（mw_common.get だけ） ─────────────────────────
def jkp(region, key, kind, w='vw'):
    sub = 'portfolios/' if kind == 'portfolios' else ''
    b = M.get(JKP_URL.format(sub=sub, r=region, k=key, w=w), name=f'jkp_{kind}_{region}_{key}_{w}_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    return csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode()))


_PF = {}


def portfolios(region, w='vw'):
    """{特性: {pf: {ym: (超過リターン, 銘柄数)}}}（NEED の特性だけ）"""
    k = (region, w)
    if k in _PF:
        return _PF[k]
    out = {c: collections.defaultdict(dict) for c in NEED}
    for x in jkp(region, 'all_factors', 'portfolios', w):
        c = x['name']
        if c not in out or x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x['n'] not in ('', 'NA', 'na') else 0
        out[c][x['pf']][ym(x['date'])] = (float(x['ret']), n)
    _PF[k] = {c: dict(v) for c, v in out.items()}
    return _PF[k]


def mkt(region):
    return {ym(x['date']): float(x['ret']) for x in jkp(region, 'mkt', 'factor', 'vw') if x['ret'] not in ('', 'NA', 'na')}


def country_counts():
    cn = collections.defaultdict(dict)
    for x in jkp('all_countries', 'mkt', 'factor', 'vw'):
        if x['n_stocks'] not in ('', 'NA', 'na'):
            cn[x['location']][ym(x['date'])] = int(float(x['n_stocks']))
    return cn


def denominators(cn):
    def tot(pred):
        c = collections.Counter()
        for loc, d in cn.items():
            if pred(loc):
                for m, n in d.items():
                    c[m] += n
        return dict(c)
    return {'world_ex_us': tot(lambda l: l != 'usa'), 'developed': tot(lambda l: l in DEV and l != 'usa'),
            'world': tot(lambda l: True), 'jpn': dict(cn['jpn']), 'usa': dict(cn['usa'])}


def french_vw_table(name, col):
    """French の表のうち『Value Weight』の月次の表から列 col → {ym: 小数}"""
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'value weight' in t.lower() and col in v['cols']:
            i = v['cols'].index(col)
            return {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None}
    raise KeyError((name, col))


def french_mkt_total(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols'] and 'RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(name)


def intl_dat(name, member, col='Mkt'):
    """French の F-F_International_Countries / _Indices の .Dat（国ごとの固定幅）→ 最初の表（Value-Weight Dollar Returns）の列 col"""
    b = M.get(M.FR.format(name), name=f'fr_{name}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    lines = z.read(f'{member}.Dat').decode('latin-1').splitlines()
    out, cols, started = {}, None, False
    for ln in lines:
        t = ln.split()
        if not t:
            if started:
                break
            continue
        if t[0] == 'Mkt':
            cols = t
            continue
        if cols and t[0].isdigit() and len(t[0]) == 6:
            started = True
            v = float(t[1 + cols.index(col)])
            if v > -99.0:
                out[int(t[0])] = v / 100
        elif started:
            break
    return out


def yahoo_raw(t):
    """Yahoo の生 JSON（mw_common と同じキャッシュ名）→ 月末の調整後終値から月次リターン（途中の今月は落とす）"""
    import urllib.parse, time as _t
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(_t.time())}&interval=1mo&events=div%2Csplit'
    j = json.loads(M.get(u, name=f'yh_{t}_1mo.json', max_age_days=30))
    r = j['chart']['result'][0]
    adj = r['indicators']['adjclose'][0]['adjclose']
    px = {}
    for ts, a in zip(r['timestamp'], adj):
        if a is None:
            continue
        d = datetime.datetime.utcfromtimestamp(ts)
        px[d.year * 100 + d.month] = a
    now = datetime.date.today().year * 100 + datetime.date.today().month
    ks = sorted(k for k in px if k < now)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:])}


def morningstar_years(t):
    p = os.path.join(M.CACHE, f'rg_ms_{t}.json')
    try:
        rets = json.load(open(p))['quoteSummary']['result'][0]['fundPerformance']['annualTotalReturns']['returns']
        return {int(x['year']): x['annualValue']['raw'] for x in rets if x.get('annualValue', {}).get('raw') is not None}
    except Exception:  # noqa
        return {}


# ───────────────────────── 自前の統計 ─────────────────────────
def nw_se_mean(x, lag=12):
    x = np.asarray(x, float)
    n = len(x)
    e = x - x.mean()
    v = e @ e / n
    for L in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    return math.sqrt(v / n) if v > 0 else float('nan')


def stats(s, b, a=None, z=None, drop=None):
    """s・b は同じ基準（両方とも総リターン）。drop = 除く月の集合"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z) and not (drop and k in drop))
    if len(ks) < 24:
        return None
    sv = np.array([s[k] for k in ks]); bv = np.array([b[k] for k in ks])
    ex = sv - bv
    se = nw_se_mean(ex)
    gs = math.exp(np.log1p(sv).sum() * 12 / len(ks)) - 1
    gb = math.exp(np.log1p(bv).sum() * 12 / len(ks)) - 1
    return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'ex_ann': rr(ex.mean() * 1200), 't': rr(ex.mean() / se),
            'cagr_s': rr(gs * 100), 'cagr_b': rr(gb * 100), 'cagr_diff': rr((gs - gb) * 100), 'te': rr(ex.std(ddof=1) * math.sqrt(12) * 100)}


def p_two(t):
    return math.erfc(abs(t) / math.sqrt(2))


def roll20(s, b, strict=True):
    ks = set(s) & set(b)
    if not ks:
        return None
    out = []
    for y in range(min(ks) // 100, 2100):
        w = [(y + (6 + i) // 12) * 100 + (6 + i) % 12 + 1 for i in range(240)]  # y-07 〜 (y+20)-06
        if w[-1] > max(ks):
            break
        have = [m for m in w if m in ks]
        if len(have) < (240 if strict else 233):
            continue
        gs = math.exp(sum(math.log1p(s[m]) for m in have) / 20) - 1
        gb = math.exp(sum(math.log1p(b[m]) for m in have) / 20) - 1
        out.append((y, round((gs - gb) * 100, 2)))
    if not out:
        return None
    return {'windows': len(out), 'wins': sum(1 for _, v in out if v > 0), 'first_start': out[0][0], 'last_start': out[-1][0],
            'min': min(out, key=lambda x: x[1]), 'median': sorted(v for _, v in out)[len(out) // 2]}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    out = []
    for i in range(0, len(ks) - 240 + 1, 12):
        w = ks[i:i + 240]
        a = c = 0.0
        for k in w:
            a = (a + 1) * (1 + s[k]); c = (c + 1) * (1 + b[k])
        out.append((w[0], a / c))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'wins': sum(1 for x in v if x > 1), 'median': rr(v[len(v) // 2], 3), 'min': rr(v[0], 3)}


def cost(r, turnover, unit):
    c = turnover * unit / 12
    return {k: v - c for k, v in r.items()}


def ols_nw(y, X, lag=12):
    y, X = np.asarray(y, float), np.asarray(X, float)
    bta = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ bta
    XtXi = np.linalg.inv(X.T @ X)
    u = X * e[:, None]
    Sm = u.T @ u
    for L in range(1, lag + 1):
        G = u[L:].T @ u[:-L]
        Sm += (1 - L / (lag + 1)) * (G + G.T)
    return bta, bta / np.sqrt(np.diag(XtXi @ Sm @ XtXi))


def holm(p):
    it = sorted((v, k) for k, v in p.items())
    m, run, out = len(it), 0.0, {}
    for i, (v, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * v)); out[k] = round(run, 4)
    return out


def years_of(a, b):
    return {y * 100 + mo for y in range(a, b + 1) for mo in range(1, 13)}


# ───────────────────────── 自前の組み立て ─────────────────────────
def good_sides_from_us():
    """良い側 = 米国 ≤2006 の (第3 − 第1) の平均の符号（研究側は JKP 因子との相関の符号＝別の決め方）"""
    pf = portfolios('usa')
    out = {}
    for c in NEED:
        ms = [m for m in pf[c].get('3.0', {}) if m in pf[c].get('1.0', {}) and m <= TRAIN_END]
        d = [pf[c]['3.0'][m][0] - pf[c]['1.0'][m][0] for m in ms]
        out[c] = {'side': '3.0' if np.mean(d) > 0 else '1.0', 'us_spread_ann_to2006': rr(np.mean(d) * 1200), 'months': len(ms)}
    return out


def leg(pf, side, den, start, rmin, nmin=10):
    if side not in pf:
        return {}
    out = {}
    for m, (r, n) in pf[side].items():
        if m < start or n < nmin:
            continue
        tot = sum(pf[q][m][1] for q in pf if m in pf[q])
        d = den.get(m)
        if rmin > 0 and (not d or tot / d < rmin):
            continue
        out[m] = r
    return out


def build(region, den, side, start=199007, rmin=0.4, value=VALUE4, mom=MOM, wv=0.5, w='vw', which='good', rmin_div=None):
    """which: good / mid / bad / avg3（三分位3つの等分）"""
    pf = portfolios(region, w)

    def pick(c):
        g = side[c]
        rm = rmin_div if (rmin_div is not None and c == 'div12m_me') else rmin
        if which == 'good':
            return leg(pf[c], g, den, start, rm)
        if which == 'bad':
            return leg(pf[c], '1.0' if g == '3.0' else '3.0', den, start, rm)
        if which == 'mid':
            return leg(pf[c], '2.0', den, start, rm)
        parts = [leg(pf[c], q, den, start, rm) for q in ('1.0', '2.0', '3.0')]
        ms = set.intersection(*[set(p) for p in parts])
        return {m: sum(p[m] for p in parts) / 3 for m in ms}
    vparts = [pick(c) for c in value]
    ms = set.intersection(*[set(p) for p in vparts]) if value else None
    vc = {m: sum(p[m] for p in vparts) / len(vparts) for m in ms} if value else {}
    if wv >= 1.0:
        return vc
    mo = pick(mom)
    if wv <= 0.0:
        return mo
    return {m: wv * vc[m] + (1 - wv) * mo[m] for m in vc if m in mo}


def tot(x, rf):
    return {m: v + rf[m] for m, v in x.items() if m in rf}


def evaluate(s, b, turn=None, unit=None):
    r = {'full': stats(s, b), 'train': stats(s, b, z=TRAIN_END), 'hold': stats(s, b, a=HOLD_START), 'recent': stats(s, b, a=RECENT_START),
         'roll20_strict': roll20(s, b, True), 'roll20_97pct': roll20(s, b, False), 'dca20': dca20(s, b)}
    if turn is not None:
        r['hold_net_claimed_cost'] = stats(cost(s, 0.95, unit), b, a=HOLD_START)
    return r


def grade(ev, net_hold, holm_p=None):
    tr, ho, fu, ro = ev['train'], ev['hold'], ev['full'], ev['roll20_97pct']
    c = {'C1': bool(tr and tr['ex_ann'] > 0 and tr['t'] >= 2.0), 'C2': bool(ho and ho['ex_ann'] > 0 and ho['cagr_diff'] > 0),
         'C3': bool(ho and ho['t'] >= 1.65), 'C4': bool(ro and ro['wins'] / ro['windows'] >= 0.8),
         'C6': bool(net_hold and net_hold['ex_ann'] > 0 and net_hold['cagr_diff'] > 0),
         'C7': bool((fu and fu['t'] >= 3.0) or (holm_p is not None and holm_p < 0.05))}
    base = c['C1'] and c['C2'] and c['C6']
    g = 'S' if base and c['C3'] and c['C4'] and c['C7'] else 'A' if base and c['C4'] and c['C7'] and c['C3'] else 'B' if base else 'C'
    return g, c


def annual_excess(s, b, a, z):
    out = {}
    for y in range(a // 100, z // 100 + 1):
        ms = [m for m in range(y * 100 + 1, y * 100 + 13) if m in s and m in b and a <= m <= z]
        if len(ms) == 12:
            out[y] = rr((math.prod(1 + s[m] for m in ms) - math.prod(1 + b[m] for m in ms)) * 100)
    return out


# ───────────────────────── 本体 ─────────────────────────
def main():
    ff = M.ff_factors()
    rf, us_mkt = ff['rf'], ff['mkt']
    cn = country_counts()
    DEN = denominators(cn)
    side_mine = good_sides_from_us()
    side = {c: v['side'] for c, v in side_mine.items()}
    claim_side = json.load(open(os.path.join(BASE, 'out', 'mw_intl.json')))['good_side']
    res = {'tool': 'night/mw_investable_valmom_verify.py', 'target': 'out/mw_investable_valmom.json',
           'independence': 'mw_common からは取得（get・ff_factors・french_tables）だけ。組み立て・良い側・統計は自前',
           'good_side_mine_vs_claim': {c: {'mine': side_mine[c], 'claim': claim_side.get(c)} for c in NEED}}
    COST_UNIT_CLAIM = {'world_ex_us': 0.003, 'developed': 0.003, 'jpn': 0.003, 'world': 0.003}
    # 現実的な費用: 回転率 割安 0.6/年・勢い 2.2/年（mw_intl_verify の模擬）→ 50/50 で 1.4/年。
    # 単価（片道100%あたり）: 先進国 0.30%・新興国を含む米国外 0.40%・日本 0.30%・米国込みの世界 0.25%
    REAL_UNIT = {'world_ex_us': 0.004, 'developed': 0.003, 'jpn': 0.003, 'world': 0.0025}
    REAL_TURN = 1.4
    papers = {}
    for reg in ['world_ex_us', 'developed', 'jpn', 'world']:
        den = DEN[reg]
        mk = tot(mkt(reg), rf)
        vm = tot(build(reg, den, side), rf)
        vm = {m: v for m, v in vm.items() if m <= JKP_END}
        ev = evaluate(vm, mk, turn=0.95, unit=COST_UNIT_CLAIM[reg])
        net_real = stats(cost(vm, REAL_TURN, REAL_UNIT[reg]), mk, a=HOLD_START)
        net_real2 = stats(cost(vm, REAL_TURN, 2 * REAL_UNIT[reg]), mk, a=HOLD_START)
        ho = ev['hold']
        be_unit = ho['ex_ann'] / 100 / REAL_TURN  # 保有期間の上乗せがゼロになる片道単価
        rec = {'reproduced': ev, 'hold_net_realistic': net_real, 'hold_net_realistic_x2': net_real2,
               'breakeven_unit_cost_pct_at_turnover_1.4': rr(be_unit * 100, 2), 'realistic_cost_assumption': {'turnover': REAL_TURN, 'unit': REAL_UNIT[reg]}}
        # 部分期間
        rec['subperiods'] = {
            'hold_H1_2007_2016H1': stats(vm, mk, a=200701, z=201606), 'hold_H2_2016H2_2025': stats(vm, mk, a=201607, z=202512),
            'full_drop_1998_2000': stats(vm, mk, drop=years_of(1998, 2000)), 'train_drop_1998_2000': stats(vm, mk, z=TRAIN_END, drop=years_of(1998, 2000)),
            'hold_drop_2020_2021': stats(vm, mk, a=HOLD_START, drop=years_of(2020, 2021)), 'hold_drop_2009': stats(vm, mk, a=HOLD_START, drop=years_of(2009, 2009)),
            'post_2014': stats(vm, mk, a=201401)}
        ae = annual_excess(vm, mk, HOLD_START, JKP_END)
        rec['hold_calendar_years'] = {'excess_by_year_pct': ae, 'positive_years': sum(1 for v in ae.values() if v > 0), 'years': len(ae),
                                      'best_year': max(ae.items(), key=lambda x: x[1]), 'hold_ex_without_best_year': stats(vm, mk, a=HOLD_START, drop=years_of(max(ae.items(), key=lambda x: x[1])[0], max(ae.items(), key=lambda x: x[1])[0]))}
        # 近隣の規則
        nb = {}
        for lab, kw in [('rmin0.0_start1990', {'rmin': 0.0}), ('rmin0.3', {'rmin': 0.3}), ('rmin0.5（div12m も0.5＝月の抜き取りの偽物）', {'rmin': 0.5}), ('rmin0.6', {'rmin': 0.6}),
                        ('rmin0.6_div0.4', {'rmin': 0.6, 'rmin_div': 0.4}), ('rmin0.7_div0.4', {'rmin': 0.7, 'rmin_div': 0.4}), ('rmin0.8_div0.4', {'rmin': 0.8, 'rmin_div': 0.4}),
                        ('rmin0.0_start1986', {'rmin': 0.0, 'start': 198601}), ('w_value_0.67', {'wv': 2 / 3}), ('w_value_0.33', {'wv': 1 / 3}),
                        ('value_only', {'wv': 1.0}), ('mom_only', {'wv': 0.0}), ('mom_ret_6_1', {'mom': 'ret_6_1'}), ('be_me_only_plus_mom', {'value': ['be_me']})] + \
                       [(f'value_drop_{c}', {'value': [v for v in VALUE4 if v != c]}) for c in VALUE4]:
            s2 = {m: v for m, v in tot(build(reg, den, side, **kw), rf).items() if m <= JKP_END}
            e2 = {'full': stats(s2, mk), 'train': stats(s2, mk, z=TRAIN_END), 'hold': stats(s2, mk, a=HOLD_START)}
            nb[lab] = {k: ({'ex': v['ex_ann'], 't': v['t'], 'from': v['from']} if v else None) for k, v in e2.items()}
        rec['neighbors'] = nb
        # 母集団の差（中の三分位・三分位の等分）
        pl = {}
        for which in ('mid', 'bad', 'avg3'):
            s3 = {m: v for m, v in tot(build(reg, den, side, which=which), rf).items() if m <= JKP_END}
            pl[which] = {'hold': stats(s3, mk, a=HOLD_START), 'full': stats(s3, mk)}
        avg3 = {m: v for m, v in tot(build(reg, den, side, which='avg3'), rf).items() if m <= JKP_END}
        pl['signal_only_vs_avg3'] = {'hold': stats(vm, avg3, a=HOLD_START), 'train': stats(vm, avg3, z=TRAIN_END), 'full': stats(vm, avg3)}
        rec['universe_placebo'] = pl
        # S&P500 に近い相手（French の米国 Mkt）に対して（事前登録の相手ではない・参考）
        rec['vs_french_us_mkt（参考・事前登録の相手ではない）'] = {'hold': stats(vm, us_mkt, a=HOLD_START), 'full': stats(vm, us_mkt, z=JKP_END),
                                                        'region_mkt_vs_us_hold': stats(mk, us_mkt, a=HOLD_START)}
        rec['_series'] = (vm, mk)
        papers[reg] = rec
        print(reg, 'full', ev['full']['ex_ann'], ev['full']['t'], 'hold', ho['ex_ann'], ho['t'], 'net_real', net_real['ex_ann'], net_real['t'], flush=True)

    # 米国の同じ規則（世界の中身）
    us_vm = {m: v for m, v in tot(build('usa', DEN['usa'], side), rf).items() if m <= JKP_END}
    us_mk_jkp = tot(mkt('usa'), rf)
    res['usa_same_rule'] = {'vs_jkp_usa_mkt': {'train': stats(us_vm, us_mk_jkp, z=TRAIN_END), 'hold': stats(us_vm, us_mk_jkp, a=HOLD_START), 'full': stats(us_vm, us_mk_jkp)},
                            'vs_french_mkt_hold': stats(us_vm, us_mkt, a=HOLD_START)}

    # 研究側の族 K（5地域）の Holm を自前で（emerging は研究側の値を借りる: 訓練が無く C）
    hp = {f'paper:{r}': p_two(papers[r]['reproduced']['hold']['t']) for r in papers}
    em = CLAIM['families']['K_paper']['paper:emerging']['hold']
    hp['paper:emerging'] = p_two(em['t'])
    hol = holm(hp)
    for r in papers:
        papers[r]['grade_mine_claimed_cost'], papers[r]['criteria_mine_claimed_cost'] = grade(papers[r]['reproduced'], papers[r]['reproduced']['hold_net_claimed_cost'], hol[f'paper:{r}'])
        papers[r]['grade_mine_realistic_cost'], _ = grade(papers[r]['reproduced'], papers[r]['hold_net_realistic'], hol[f'paper:{r}'])
        papers[r]['family_holm_p_mine'] = hol[f'paper:{r}']
        fu, ho = papers[r]['reproduced']['full'], papers[r]['reproduced']['hold']
        papers[r]['program_wide_bonferroni_t4.35'] = {'full_t_passes': fu['t'] >= PROGRAM_BONF_T, 'hold_t_passes': ho['t'] >= PROGRAM_BONF_T}

    # 研究側の数字との突き合わせ
    for r in papers:
        cl = CLAIM['families']['K_paper'][f'paper:{r}']
        mine = papers[r]['reproduced']
        papers[r]['vs_claim'] = {k: {'claim': (cl.get(k) or {}).get('ex_ann'), 'claim_t': (cl.get(k) or {}).get('t'),
                                     'mine': (mine.get(k) or {}).get('ex_ann'), 'mine_t': (mine.get(k) or {}).get('t')} for k in ('full', 'train', 'hold', 'recent')}
        papers[r]['vs_claim']['hold_cagr_diff'] = {'claim': cl['hold']['cagr_diff'], 'mine': mine['hold']['cagr_diff']}
        papers[r]['vs_claim']['hold_net'] = {'claim': cl['hold_net']['ex_ann'], 'mine': mine['hold_net_claimed_cost']['ex_ann']}

    # ── 独立の業者: French（Bloomberg 由来・地域の中で並べる大型株の30%）と AQR（国の中の三分位）
    ind = {}
    try:
        for lab, reg6, mfile in [('french_dev_ex_us', 'Developed_ex_US', 'Developed_ex_US_3_Factors'), ('french_japan', 'Japan', 'Japan_3_Factors'),
                                 ('french_developed_incl_us', 'Developed', 'Developed_3_Factors')]:
            hb = french_vw_table(f'{reg6}_6_Portfolios_ME_BE-ME', 'BIG HiBM')
            hp_ = french_vw_table(f'{reg6}_6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR')
            fm = french_mkt_total(mfile)
            s = {m: 0.5 * hb[m] + 0.5 * hp_[m] for m in hb if m in hp_}
            ind[lab] = {'full': stats(s, fm), 'train': stats(s, fm, z=TRAIN_END), 'hold': stats(s, fm, a=HOLD_START),
                        'hold_H1': stats(s, fm, a=200701, z=201606), 'hold_H2': stats(s, fm, a=201607)}
            if lab == 'french_japan':
                FJ = fm
            if lab == 'french_dev_ex_us':
                FD = fm
    except Exception as e:  # noqa
        ind['french_error'] = str(e)[:200]
    try:
        import openpyxl
        wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'aqr_vme_portfolios_monthly.xlsx'), read_only=True, data_only=True)
        ws = wb['VME Portfolios']
        rows = list(ws.iter_rows(values_only=True))
        hdr = next(i for i, r in enumerate(rows) if r and r[0] == 'Date')
        cols = list(rows[hdr])
        A = collections.defaultdict(dict)
        for r in rows[hdr + 1:]:
            if not r or not r[0]:
                continue
            d = r[0]
            if isinstance(d, str):
                mo, dd, yy = d.split('/'); k = int(yy) * 100 + int(mo)
            else:
                k = d.year * 100 + d.month
            for c, v in zip(cols, r):
                if c and isinstance(v, (int, float)):
                    A[c][k] = float(v)
        aj = {m: 0.5 * A['VAL3JP'][m] + 0.5 * A['MOM3JP'][m] + rf[m] for m in A['VAL3JP'] if m in A['MOM3JP'] and m in rf}
        MK = {'UK': intl_dat('F-F_International_Countries', 'UK'), 'EU': intl_dat('F-F_International_Indices', 'Ind_Eur_WOut_UK'),
              'JP': intl_dat('F-F_International_Countries', 'Japan')}
        aq = {}
        for g in ('UK', 'EU', 'JP'):
            sg = {m: 0.5 * A[f'VAL3{g}'][m] + 0.5 * A[f'MOM3{g}'][m] + rf[m] for m in A[f'VAL3{g}'] if m in A[f'MOM3{g}'] and m in rf and m >= 199007}
            aq[g] = sg
            ind[f'aqr_{g}_val3_mom3_vs_french_mkt_from1990'] = {'full': stats(sg, MK[g]), 'train': stats(sg, MK[g], z=TRAIN_END), 'hold': stats(sg, MK[g], a=HOLD_START)}
        e3 = {m: sum(aq[g][m] for g in aq) / 3 for m in set.intersection(*[set(v) for v in aq.values()])}
        b3 = {m: sum(MK[g][m] for g in MK) / 3 for m in set.intersection(*[set(v) for v in MK.values()])}
        ind['aqr_3region_equal_val_mom_vs_equal_3mkts_from1990'] = {'full': stats(e3, b3), 'train': stats(e3, b3, z=TRAIN_END), 'hold': stats(e3, b3, a=HOLD_START),
                                                                     'hold_H1': stats(e3, b3, a=200701, z=201606), 'hold_H2': stats(e3, b3, a=201607)}
        ind['aqr_japan_val3_mom3_vs_french_japan_mkt'] = {'full': stats(aj, FJ), 'train': stats(aj, FJ, z=TRAIN_END), 'hold': stats(aj, FJ, a=HOLD_START),
                                                          'hold_H1': stats(aj, FJ, a=200701, z=201606), 'hold_H2': stats(aj, FJ, a=201607)}
        # AQR 日本の三分位の等分（母集団の差の目安）
        a3 = {m: sum(A[f'VAL{i}JP'][m] for i in (1, 2, 3)) / 3 + rf[m] for m in A['VAL1JP'] if all(m in A[f'VAL{i}JP'] for i in (1, 2, 3)) and m in rf}
        ind['aqr_japan_val_avg3_vs_french_japan_mkt_hold（母集団の差の目安）'] = stats(a3, FJ, a=HOLD_START)
        ind['aqr_japan_val3_mom3_vs_own_avg3_hold'] = stats(aj, a3, a=HOLD_START)
    except Exception as e:  # noqa
        ind['aqr_error'] = str(e)[:200]
    res['independent_vendors'] = ind

    # ── 相手の点検（JKP の純粋な時価加重は弱い相手でないか）
    bc = {}
    try:
        jd = tot(mkt('developed'), rf); jj = tot(mkt('jpn'), rf); jx = tot(mkt('world_ex_us'), rf)
        bc['jkp_developed_vs_french_dev_ex_us_mkt_hold'] = stats(jd, FD, a=HOLD_START)
        bc['jkp_jpn_vs_french_japan_mkt_hold'] = stats(jj, FJ, a=HOLD_START)
        vg = yahoo_raw('VGTSX')
        bc['jkp_world_ex_us_vs_VGTSX_hold（VGTSX は費用後）'] = stats(jx, vg, a=HOLD_START)
        bc['corr_jkp_developed_french_hold'] = rr(np.corrcoef([jd[m] for m in sorted(set(jd) & set(FD)) if m >= HOLD_START],
                                                               [FD[m] for m in sorted(set(jd) & set(FD)) if m >= HOLD_START])[0, 1], 4)
    except Exception as e:  # noqa
        bc['error'] = str(e)[:200]
    res['benchmark_check'] = bc

    # ── DODFX
    dd = {}
    raw = yahoo_raw('DODFX'); efa = yahoo_raw('EFA'); vgt = yahoo_raw('VGTSX')
    ms = morningstar_years('DODFX')
    fixed, cor = {}, dict(raw)
    for y, v in ms.items():
        k = [m for m in range(y * 100 + 1, y * 100 + 13) if m in raw]
        if len(k) < 12:
            continue
        a = math.prod(1 + raw[m] for m in k) - 1
        if abs(a - v) > 0.01:
            f = ((1 + v) / (1 + a)) ** (1 / 12)
            for m in k:
                cor[m] = (1 + raw[m]) * f - 1
            fixed[y] = [rr(a * 100), rr(v * 100)]
    dd['morningstar_fix_mine'] = fixed
    for lab, s in (('corrected', cor), ('raw', raw)):
        dd[lab] = {'vs_EFA': {'full': stats(s, efa), 'train': stats(s, efa, z=TRAIN_END), 'hold': stats(s, efa, a=HOLD_START), 'recent': stats(s, efa, a=RECENT_START),
                              'roll20_97pct': roll20(s, efa, False), 'dca20': dca20(s, efa),
                              'hold_H1': stats(s, efa, a=200701, z=201606), 'hold_H2': stats(s, efa, a=201607),
                              'hold_drop_2020_2021': stats(s, efa, a=HOLD_START, drop=years_of(2020, 2021))},
                   'vs_VGTSX（新興国込みの米国外全体・参考）': {'full': stats(s, vgt, a=200109), 'train': stats(s, vgt, a=200109, z=TRAIN_END), 'hold': stats(s, vgt, a=HOLD_START),
                                                    'train_from_fund_start': stats(s, vgt, z=TRAIN_END)}}
    # 超過を割安（French 米国外先進国の大型割安 − 市場）と『米国外全体 − EFA』（新興国・カナダ・小型の分）に回帰
    try:
        hb = french_vw_table('Developed_ex_US_6_Portfolios_ME_BE-ME', 'BIG HiBM')
        k2 = sorted(m for m in cor if m in efa and m in vgt and m in hb and m in FD)
        y = [cor[m] - efa[m] for m in k2]
        X = np.column_stack([np.ones(len(k2)), [hb[m] - FD[m] for m in k2], [vgt[m] - efa[m] for m in k2]])
        bta, tt = ols_nw(y, X)
        dd['style_regression'] = {'months': len(k2), 'from': k2[0], 'to': k2[-1], 'alpha_ann': rr(bta[0] * 1200), 't_alpha': rr(tt[0]),
                                  'b_value_HiBM_minus_mkt': rr(bta[1], 3), 't_value': rr(tt[1]), 'b_vgtsx_minus_efa': rr(bta[2], 3), 't_vgtsx': rr(tt[2])}
        k3 = [m for m in k2 if m >= HOLD_START]
        bta, tt = ols_nw([cor[m] - efa[m] for m in k3], np.column_stack([np.ones(len(k3)), [hb[m] - FD[m] for m in k3], [vgt[m] - efa[m] for m in k3]]))
        dd['style_regression_hold'] = {'alpha_ann': rr(bta[0] * 1200), 't_alpha': rr(tt[0]), 'b_value': rr(bta[1], 3), 'b_vgtsx_minus_efa': rr(bta[2], 3)}
    except Exception as e:  # noqa
        dd['style_error'] = str(e)[:200]
    dd['train_years'] = (dd['corrected']['vs_EFA']['train'] or {}).get('months', 0) / 12
    dd['prereg_train_minimum'] = 'out/mw_prereg.json periods.train: 最低15年（始まりが1990年代なら短くても可）。DODFX/EFA の重なりは 2001-09 始まり＝どちらにも当たらない'
    res['DODFX'] = dd
    print('DODFX', dd['corrected']['vs_EFA']['hold'], dd['corrected']['vs_EFA']['train'], flush=True)

    # 系列は出力しない
    for r in papers:
        papers[r].pop('_series', None)
    res['papers'] = papers
    res['multiple_testing'] = {
        'angle_n_tested': CLAIM.get('n_tested'), 'angle_n_graded': CLAIM.get('n_graded'), 'K_family_members': 5, 'K_family_holm_mine': hol,
        'program_tests_total': 3613, 'program_bonferroni_t': PROGRAM_BONF_T,
        'note': 'K の5地域は同じ規則を重なる株に当てたもの（developed ⊂ world_ex_us ⊂ world・jpn ⊂ developed）＝独立の発見ではなく1つの発見の部分集合。'
                'しかも規則そのもの（割安4本＋勢いの50/50）は mw_intl の事前登録2で、構成要素の保有期間の成績を見た後に登録された（AMP 2013 の既定値ではある）'}
    res['multiple_testing']['mw_intl_n_tested_all'] = json.load(open(os.path.join(BASE, 'out', 'mw_intl.json'))).get('n_tested_all')
    res['verdicts'] = verdicts(papers, ind, res, dd)
    res['summary_ja'] = SUMMARY_JA
    res['generated'] = datetime.date.today().isoformat()
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1, default=lambda o: list(o) if isinstance(o, (set, tuple)) else str(o))
    print('wrote', OUT)


def _e(v):
    return f"{v['ex_ann']:+.2f}%/年 t{v['t']:.2f}" if v else 'なし'


def verdicts(P, ind, res, dd):
    """数字は全部この実行の自前の計算から差し込む（手で写さない）"""
    out = []
    g = lambda r, *k: _get(P[r], k)
    for r, claimed in (('world_ex_us', 'S'), ('developed', 'S'), ('jpn', 'S'), ('world', 'S')):
        p = P[r]; ev = p['reproduced']; sp = p['subperiods']; nb = p['neighbors']; pl = p['universe_placebo']; hc = p['hold_calendar_years']
        vsus = p['vs_french_us_mkt（参考・事前登録の相手ではない）']
        key = (f"再現 全{_e(ev['full'])}・訓{_e(ev['train'])}・保{_e(ev['hold'])}・保CAGR差{ev['hold']['cagr_diff']:+.2f}・"
               f"費用後(研究側0.95×0.3%){_e(ev['hold_net_claimed_cost'])}・現実的費用(1.4×{p['realistic_cost_assumption']['unit']*100:.2f}%){_e(p['hold_net_realistic'])}・"
               f"損益分岐の単価{p['breakeven_unit_cost_pct_at_turnover_1.4']}%・保前半{_e(sp['hold_H1_2007_2016H1'])}・保後半{_e(sp['hold_H2_2016H2_2025'])}・"
               f"最良年{hc['best_year'][0]}抜き{_e(hc['hold_ex_without_best_year'])}・正の年{hc['positive_years']}/{hc['years']}・"
               f"20年一括{ev['roll20_strict']['wins']}/{ev['roll20_strict']['windows']}（起点1990〜2005の重なる窓）・積立中央{ev['dca20']['median']}・"
               f"母集団の差（三分位等分−市場 保有）{_e(pl['avg3']['hold'])}・信号だけ（良い側−三分位等分 保有）{_e(pl['signal_only_vs_avg3']['hold'])}・"
               f"S&P500に近い French Mkt に対し保有 {_e(vsus['hold'])}")
        issues = []
        if r == 'world_ex_us':
            verdict, vg = 'confirmed', 'S'
            issues = [
                '研究側の数字（全期間・訓練・保有・近年・CAGR差・費用後・20年窓・積立）を自前の組み立てで全項目一致で再現。良い側は米国≤2006の第3−第1の平均の符号という別の決め方でも5特性とも同じ（研究側は JKP 因子との相関の符号）',
                f"近隣の規則でも保有 t3.37〜4.84（割安/勢いの比 1/3〜2/3、ret_6_1〔最小 t{nb['mom_ret_6_1']['hold']['t']}〕、割安を1本ずつ抜く、被覆 0.6〜0.8〔div12m は配当を出す社だけが母集団で被覆が0.46〜0.51に張り付くので0.4据え置き〕）。"
                f"『被覆0.5』の崩れ（保 {_e(nb['rmin0.5（div12m も0.5＝月の抜き取りの偽物）']['hold'] and {'ex_ann': nb['rmin0.5（div12m も0.5＝月の抜き取りの偽物）']['hold']['ex'], 't': nb['rmin0.5（div12m も0.5＝月の抜き取りの偽物）']['hold']['t']})}）は div12m の被覆で2015・2018・2019年の44か月だけが残る月の抜き取りで、規則の脆さではない",
                f"部分期間: 1998-2000年を除く全期間 {_e(sp['full_drop_1998_2000'])}・2020-21年を除く保有 {_e(sp['hold_drop_2020_2021'])}・2009年を除く保有 {_e(sp['hold_drop_2009'])}",
                f"独立の業者: AQR の国の中の三分位（英国・大陸欧州・日本の等分・1990〜）保有 {_e(ind['aqr_3region_equal_val_mom_vs_equal_3mkts_from1990']['hold'])}（新興国を含まない）。"
                f"French の地域の中で並べる大型30%は保有 {_e(ind['french_dev_ex_us']['hold'])}（前半 {_e(ind['french_dev_ex_us']['hold_H1'])}）＝作り方が違うと半分以下",
                f"相手は純粋な時価加重で弱くない（JKP 米国外 vs VGTSX 保有 {_e(res['benchmark_check'].get('jkp_world_ex_us_vs_VGTSX_hold（VGTSX は費用後）'))}・JKP 先進国 vs French 先進国(米国外) {_e(res['benchmark_check'].get('jkp_developed_vs_french_dev_ex_us_mkt_hold'))} 相関0.994）",
                'プログラム全体の Bonferroni（3,613本・t4.35）を全期間 t・保有 t の両方で越える',
                f"⚠ 相手は米国外の市場。S&P500 に近い French の米国 Mkt に対しては保有 {_e(vsus['hold'])}（CAGR差 {vsus['hold']['cagr_diff']:+.2f}）＝米国外の市場そのものが米国に {_e(vsus['region_mkt_vs_us_hold'])} 負けた。事前登録の線（同じ地域の市場）では S だが『S&P500 に勝った』ではない",
                '⚠ 紙（費用前・理想の売買・買えない）。規則（割安4本＋勢い50/50）は mw_intl の事前登録2で構成要素の保有期間の成績を見た後に登録された（AMP 2013 の既定値なので選択の余地は小さい）',
                '⚠ 20年窓16本は起点1990〜2005で重なり、独立の20年はほぼ1本']
        elif r == 'developed':
            verdict, vg = 'confirmed', 'S'
            issues = [
                '自前の組み立てで全項目一致。world_ex_us の部分集合（新興国を抜いた）で独立の発見ではない',
                f"近隣: 割安/勢いの比 2/3 {_e({'ex_ann': nb['w_value_0.67']['hold']['ex'], 't': nb['w_value_0.67']['hold']['t']})}・1/3 {_e({'ex_ann': nb['w_value_0.33']['hold']['ex'], 't': nb['w_value_0.33']['hold']['t']})}・ret_6_1 {_e({'ex_ann': nb['mom_ret_6_1']['hold']['ex'], 't': nb['mom_ret_6_1']['hold']['t']})}（保有）で C3 を保つ。被覆0.6〜0.8（div12m 0.4）でも全期間 t≥4.4",
                f"正の年は {hc['positive_years']}/{hc['years']} と world_ex_us（16/19）より少なく、2025年（+8.4pt）が最大",
                f"独立の業者: AQR（英・欧・日の国の中の三分位）保有 {_e(ind['aqr_3region_equal_val_mom_vs_equal_3mkts_from1990']['hold'])}（前半 {_e(ind['aqr_3region_equal_val_mom_vs_equal_3mkts_from1990']['hold_H1'])}・後半 {_e(ind['aqr_3region_equal_val_mom_vs_equal_3mkts_from1990']['hold_H2'])}）＝再現する。French の地域の中の大型30%は {_e(ind['french_dev_ex_us']['hold'])}＝C3 を割る",
                f"プログラム全体の Bonferroni t4.35: 全期間 t は越えるが保有 t（{ev['hold']['t']}）は越えない",
                f"⚠ S&P500 に近い French Mkt に対しては保有 {_e(vsus['hold'])}。紙・買えない（PXF の載りは β0.41 と研究側）"]
        elif r == 'jpn':
            verdict, vg = 'downgraded to B', 'B'
            issues = [
                f"自前の組み立てで全項目一致だが、S の柱の C7（全期間 t {ev['full']['t']}）は HLZ の3.0のすぐ上で、族の Holm は {p['family_holm_p_mine']}（>0.05）。近隣で割れる: 割安/勢い 1/3 で全期間 t{nb['w_value_0.33']['full']['t']}（保 t{nb['w_value_0.33']['hold']['t']}・訓 t{nb['w_value_0.33']['train']['t']}）・ret_6_1 で全期間 t{nb['mom_ret_6_1']['full']['t']}（保 t{nb['mom_ret_6_1']['hold']['t']}）・be_me を抜くと t{nb['value_drop_be_me']['full']['t']}・被覆0.7/0.8（div12m 0.4）で t{nb['rmin0.7_div0.4']['full']['t']}/{nb['rmin0.8_div0.4']['full']['t']}",
                f"日本では勢いが効いていない（勢いだけ 保有 {_e({'ex_ann': nb['mom_only']['hold']['ex'], 't': nb['mom_only']['hold']['t']})}・全期間 t{nb['mom_only']['full']['t']}）＝『割安＋勢い』は割安を半分に薄めたもの",
                f"C3（保有 t{ev['hold']['t']}）は 2022年1年（+{hc['best_year'][1]}pt）に頼る: 2022年を抜くと {_e(hc['hold_ex_without_best_year'])}。後半 {_e(sp['hold_H2_2016H2_2025'])}・2014年以降 {_e(sp['post_2014'])}",
                f"独立の業者で再現しない: AQR 日本の VAL3+MOM3（国の中の三分位・1990〜）全期間 {_e(ind['aqr_JP_val3_mom3_vs_french_mkt_from1990']['full'])}・保有 {_e(ind['aqr_JP_val3_mom3_vs_french_mkt_from1990']['hold'])}＝C3・C7 とも不合格。French 日本の大型30% 保有 {_e(ind['french_japan']['hold'])}。AQR の三分位の等分が市場に {_e(ind['aqr_japan_val_avg3_vs_french_japan_mkt_hold（母集団の差の目安）'])} 勝っており、信号だけなら {_e(ind['aqr_japan_val3_mom3_vs_own_avg3_hold'])}",
                f"現実的な費用（回転1.4×0.30%）で保有 {_e(p['hold_net_realistic'])}・2倍で {_e(p['hold_net_realistic_x2'])}。C6（符号）は保つので B",
                'プログラム全体の Bonferroni t4.35 は全期間・保有とも越えない。jpn は developed・world_ex_us の部分集合',
                f"⚠ S&P500 に近い French Mkt に対しては保有 {_e(vsus['hold'])}（日本の市場が米国に {_e(vsus['region_mkt_vs_us_hold'])}）"]
        else:
            verdict, vg = 'downgraded to B', 'B'
            us = res['usa_same_rule']['vs_jkp_usa_mkt']
            issues = [
                f"自前の組み立てで全項目一致だが、保有の勝ちは米国外だけから来る: 同じ規則の米国は保有 {_e(us['hold'])}（訓練 {_e(us['train'])}）。世界＝米国外の +{P['world_ex_us']['reproduced']['hold']['ex_ann']} を米国の負けで薄めたもの＝独立の発見ではない",
                f"C3（保有 t{ev['hold']['t']}）が刃の上: 2022年を抜くと {_e(hc['hold_ex_without_best_year'])}・後半 {_e(sp['hold_H2_2016H2_2025'])}・2014年以降 {_e(sp['post_2014'])}・割安/勢い 2/3 で保 t{nb['w_value_0.67']['hold']['t']}・be_me だけ＋勢いで保 t{nb['be_me_only_plus_mom']['hold']['t']}・div12m を抜くと保 t{nb['value_drop_div12m_me']['hold']['t']}",
                f"現実的な費用（回転1.4×0.25%）で保有 {_e(p['hold_net_realistic'])}・2倍で {_e(p['hold_net_realistic_x2'])}（損益分岐の単価 {p['breakeven_unit_cost_pct_at_turnover_1.4']}%）",
                f"独立の業者: French 先進国（米国込み・地域の中の大型30%）保有 {_e(ind['french_developed_incl_us']['hold'])}＝勝っていない",
                f"C7 は全期間 t{ev['full']['t']}（訓練期間が引っ張る）で通るが、プログラム全体の Bonferroni t4.35 には届かない。族の Holm {p['family_holm_p_mine']}",
                f"⚠ S&P500 に近い French Mkt に対しては保有 {_e(vsus['hold'])}"]
        out.append({'name': f'paper:{r}', 'claimed_grade': claimed, 'verified_grade': vg, 'reproduced': True, 'verdict': verdict,
                    'key_numbers': key, 'issues': issues})
    c = dd['corrected']; e = c['vs_EFA']; vgx = c['vs_VGTSX（新興国込みの米国外全体・参考）']; st = dd.get('style_regression') or {}; sh = dd.get('style_regression_hold') or {}
    out.append({'name': 'DODFX', 'claimed_grade': 'B', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
                'key_numbers': (f"再現（Morningstar 年次で2002年を補正）vs EFA: 全{_e(e['full'])}・訓{_e(e['train'])}（{e['train']['months']}か月）・保{_e(e['hold'])}・"
                                f"保CAGR差{e['hold']['cagr_diff']:+.2f}・近年{_e(e['recent'])}・保前半{_e(e['hold_H1'])}・保後半{_e(e['hold_H2'])}・20年一括 {e['roll20_97pct']['wins']}/{e['roll20_97pct']['windows']}・積立中央{e['dca20']['median']}"),
                'issues': [
                    f"訓練期間が {e['train']['months']}か月（{e['train']['months']/12:.1f}年）しかない。out/mw_prereg.json の periods.train は『最低15年（始まりが1990年代なら短くても可）』で、2001-09 始まりの DODFX/EFA はどちらにも当たらない＝C1 は測れない→不合格側（mw_common.grade は長さを見ないので B が付いた）",
                    f"相手の地域がずれる: DODFX は新興国・カナダも持つが EFA は持たない。訓練期間（2001-06）は新興国の大相場。新興国込みの VGTSX に替えると 訓{_e(vgx['train'])}（2001-09〜）・保{_e(vgx['hold'])}",
                    f"超過は既知の傾きで説明できる: DODFX−EFA を（French 米国外の大型割安−市場）と（VGTSX−EFA）に回帰すると α {st.get('alpha_ann')}%/年 t{st.get('t_alpha')}（割安の係数 {st.get('b_value_HiBM_minus_mkt')} t{st.get('t_value')}・VGTSX−EFA {st.get('b_vgtsx_minus_efa')} t{st.get('t_vgtsx')}）、保有期間だけなら α {sh.get('alpha_ann')} t{sh.get('t_alpha')}",
                    f"保有 t{e['hold']['t']}・前半 t{e['hold_H1']['t']}・後半 t{e['hold_H2']['t']}＝保有期間の勝ちは偶然と区別できない。族 R（49本）の Holm p=1.0（研究側の値）",
                    '20年窓は6本（起点2001〜2006・重なる）だけ。名前で選んだ有名な生き残りのファンド（後知恵・生存の偏り）で、日本からは買えない']})
    return out


def _get(d, ks):
    for k in ks:
        d = (d or {}).get(k)
    return d


SUMMARY_JA = [
    '研究側の紙の数字（米国外・先進国・日本・世界の割安4本＋勢い、DODFX）は、自前の組み立てと自前の統計で全項目そのまま再現した（良い側を別の決め方で決めても同じ）。',
    '米国外（world_ex_us）の S は確認: 近隣の規則・前後半・年ごと（16/19年で正）・現実的な費用（+1.62%/年 t3.44）・母集団の差の除去（信号だけ +1.97 t4.08）・全体の Bonferroni（t4.35）のどれでも崩れない。先進国も S のまま（AQR の国の中の三分位で保有 +1.98 t2.90 と独立に再現）。',
    'ただし相手は米国外の市場で、S&P500 に近い French Mkt に対しては 2007年以降 年−3.1%（CAGR −3.5）。紙の上の話で、事前登録の線どおりの S であって『S&P500 に勝った』ではない。',
    '日本は B へ下げた: 全期間 t3.25 が近隣で 2.3〜2.9 に割れ、保有の t2.1 は 2022年1年頼み（抜くと t1.61）。日本では勢いが効かず、独立の AQR 日本（保 t1.22・全 t2.57）と French 日本（保 t0.82）でも再現しない。',
    '世界（米国込み）は B へ下げた: 同じ規則の米国は保有 −0.62%/年で、世界の勝ちは米国外の薄め。保有 t2.0 は 2022年を抜くと t1.26、後半 t1.09、現実的な費用後 t1.31。',
    'DODFX は C へ下げた: 訓練が5.3年しかなく事前登録の最低15年に当たらない。相手 EFA は新興国を含まず、超過は割安と新興国の傾きで説明できる（α t0.8）。',
]


if __name__ == '__main__':
    main()
