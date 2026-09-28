#!/usr/bin/env python3
"""night/mw_calendar.py — 暦のアノマリーで市場に勝てるか（mw の角度 calendar・読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」の一角。
事前登録: out/mw_calendar_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）。出力: out/mw_calendar.json

規則（詳しくは事前登録）
- ハロウィーン（11〜4月）・月替わり（最終立会日＋最初の3立会日）・祝日前・1月の小型株・FOMC 発表日
- 切替（株↔短期金利）と上乗せ（1.5倍↔1倍）。暦は前もって分かるので、持ち方は当日の暦だけで決まる
- 相手: French Mkt（上限なしの時価加重）を買って持つだけ。日次の規則は同じ日次 Mkt を月次へ直したものと比べる
- 国別（C5）: JKP の国別 mkt（vw・超過・米ドル建て）46か国

使い方: python3 night/mw_calendar.py
"""
import sys, os, re, json, math, datetime, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PREREG = 'mw_calendar_prereg.json'
COST, COST_LO = 0.001, 0.0005          # 持ち替え 片道100%あたり（判定 / 報告）
SPREAD, SPREAD_HI = 0.005, 0.015        # 借入の上乗せ（年）
TAX = 0.20315
DEV = 'aus aut bel can che deu dnk esp fin fra gbr hkg irl isr ita jpn nld nor nzl prt sgp swe'.split()
EM = 'are bra chl chn col cze egy grc hun idn ind kor kwt mex mys per phl pol qat sau tha tur twn zaf'.split()
TR_END, HO_START, RE_START = M.TRAIN_END, M.HOLD_START, M.RECENT_START


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ───────────────────────── 暦 ─────────────────────────
def ymd(k):
    return datetime.date(k // 10000, k // 100 % 100, k % 100)


def dkey(d):
    return d.year * 10000 + d.month * 100 + d.day


def month_groups(dates):
    g = {}
    for k in dates:
        g.setdefault(k // 100, []).append(k)
    return g


def edges_ok(dates):
    """最初の月が途中から始まるか・最後の月が途中で終わるか（事前登録 data_edges）"""
    first_partial = ymd(dates[0]).day >= 8
    last_partial = ymd(dates[-1]).day < 25
    return first_partial, last_partial


def tom_set(dates, before=1, after=3):
    g = month_groups(dates)
    yms = sorted(g)
    fp, lp = edges_ok(dates)
    s = set()
    for i, ym in enumerate(yms):
        ds = g[ym]
        if not (i == len(yms) - 1 and lp):
            s.update(ds[-before:])
        if not (i == 0 and fp):
            s.update(ds[:after])
    return s


def ariel_set(dates):
    """前月の最終立会日＋暦の1〜15日の立会日"""
    g = month_groups(dates)
    yms = sorted(g)
    fp, lp = edges_ok(dates)
    s = set(k for k in dates if k % 100 <= 15)
    for i, ym in enumerate(yms):
        if not (i == len(yms) - 1 and lp):
            s.add(g[ym][-1])
    if fp:  # 途中から始まる最初の月の前半は、始まる前の日を持てないだけで、暦の前半の日は分かる
        pass
    return s


def santa_set(dates):
    g = month_groups(dates)
    yms = sorted(g)
    fp, lp = edges_ok(dates)
    s = set()
    for i, ym in enumerate(yms):
        if ym % 100 == 12 and not (i == len(yms) - 1 and lp):
            s.update(g[ym][-5:])
        if ym % 100 == 1 and not (i == 0 and fp):
            s.update(g[ym][:2])
    return s


def easter(y):
    a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4
    f = (b + 8) // 25; g = (b - f + 1) // 3; h = (19 * a + b - d - g + 15) % 30
    i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mo = (h + l - 7 * m + 114) // 31; da = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(y, mo, da)


_EASTER = {}


def scheduled_holiday(d):
    """定例の祝日の窓（事前登録 preholiday_US_primary）。d は平日"""
    m, dd, wd = d.month, d.day, d.weekday()  # 月曜=0
    if (m == 12 and dd == 31) or (m == 1 and dd <= 3):
        return 'newyear'
    if m == 1 and 15 <= dd <= 21 and wd == 0:
        return 'mlk'
    if m == 2 and 11 <= dd <= 13:
        return 'lincoln'
    if m == 2 and (21 <= dd <= 23 or (15 <= dd <= 21 and wd == 0)):
        return 'washington'
    if d.year not in _EASTER:
        _EASTER[d.year] = easter(d.year) - datetime.timedelta(days=2)
    if d == _EASTER[d.year]:
        return 'goodfriday'
    if m == 5 and (29 <= dd <= 31 or (25 <= dd <= 31 and wd == 0)):
        return 'memorial'
    if m == 6 and 18 <= dd <= 20:
        return 'juneteenth'
    if m == 7 and 3 <= dd <= 5:
        return 'independence'
    if m == 9 and 1 <= dd <= 7 and wd == 0:
        return 'labor'
    if m == 10 and 11 <= dd <= 13:
        return 'columbus'
    if m == 11 and 2 <= dd <= 8 and wd == 1:
        return 'election'
    if m == 11 and 10 <= dd <= 12:
        return 'veterans'
    if m == 11 and 20 <= dd <= 30 and wd == 3:
        return 'thanksgiving'
    if m == 12 and 24 <= dd <= 26:
        return 'christmas'
    return None


def normal_weekdays(dates):
    """その市場のその年に、半分以上の週で取引がある曜日（日〜木に取引する国では金土が休み）"""
    by = {}
    for k in dates:
        d = ymd(k)
        y, w = d.isocalendar()[0], d.isocalendar()[1]
        e = by.setdefault(y, {'weeks': set(), 'wd': {}})
        e['weeks'].add(w); e['wd'][d.weekday()] = e['wd'].get(d.weekday(), 0) + 1
    return {y: set(wd for wd, n in e['wd'].items() if n >= 0.5 * len(e['weeks'])) for y, e in by.items()}


def preholiday_set(dates, mode='scheduled', maxgap=None):
    """次の立会日までに平日が欠けている立会日。mode='scheduled' は定例の祝日の窓に入る平日があるときだけ。
    mode='local' はその市場の平日（normal_weekdays）で欠けを数える（国別）。'all' は月〜金"""
    s, gaps = set(), []
    nw = normal_weekdays(dates) if mode == 'local' else None
    for a, b in zip(dates, dates[1:]):
        da, db = ymd(a), ymd(b)
        wk = [da + datetime.timedelta(i) for i in range(1, (db - da).days)]
        if nw is not None:
            wk = [x for x in wk if x.weekday() in nw.get(x.isocalendar()[0], {0, 1, 2, 3, 4})]
        else:
            wk = [x for x in wk if x.weekday() < 5]
        if not wk:
            continue
        if maxgap is not None and len(wk) > maxgap:
            continue
        if mode == 'scheduled' and not any(scheduled_holiday(x) for x in wk):
            gaps.append((a, [dkey(x) for x in wk], False))
            continue
        gaps.append((a, [dkey(x) for x in wk], True))
        s.add(a)
    return s, gaps


SYN = 29.530588853
REF = datetime.datetime(2000, 1, 6, 18, 14)


def lunar_set(dates):
    s = set()
    for k in dates:
        d = ymd(k)
        age = ((datetime.datetime(d.year, d.month, d.day, 12) - REF).total_seconds() / 86400) % SYN
        if age <= 7 or age >= SYN - 7:
            s.add(k)
    return s


# ───────────────────────── FOMC ─────────────────────────
MON = {m: i + 1 for i, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split())}


def fomc_dates():
    """定例 FOMC の発表日（会合の最終日）。1994〜2020 は fomchistorical、2021〜 は fomccalendars"""
    out, bad = set(), []
    for y in range(1994, 2021):
        t = M.get(f'https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm', name=f'fomc_hist_{y}.htm', max_age_days=3650).decode('utf-8', 'ignore')
        for h in re.findall(r'<h5[^>]*>([^<]*)</h5>', t):
            h = ' '.join(h.replace('&nbsp;', ' ').split())
            if 'Meeting' not in h or re.search(r'(?i)conference call|unscheduled|cancel|notation', h):
                continue
            m = re.match(r'([A-Za-z]+)(?:/([A-Za-z]+))?\s+(\d+)(?:\s*-\s*(\d+))?\b.*?Meeting\s*-\s*(\d{4})', h)
            if not m:
                bad.append(h); continue
            mon = (m.group(2) or m.group(1))[:3].lower()
            day = int(m.group(4) or m.group(3))
            out.add(datetime.date(int(m.group(5)), MON[mon], day))
    t = M.get('https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm', name='fomc_calendars.htm', max_age_days=30).decode('utf-8', 'ignore')
    panels = sorted((m.start(), int(m.group(1))) for m in re.finditer(r'(\d{4}) FOMC Meetings', t))
    for m in re.finditer(r'fomc-meeting__month[^>]*>\s*<strong>([^<]*)</strong>.*?fomc-meeting__date[^>]*>([^<]*)<', t, re.S):
        yr = [y for p, y in panels if p <= m.start()]
        if not yr:
            continue
        yr = yr[-1]
        if yr < 2021:
            continue
        mo, dt = m.group(1).strip(), m.group(2).strip()
        if re.search(r'(?i)notation|unscheduled|cancel', mo + ' ' + dt):
            continue
        mon = mo.split('/')[-1][:3].lower()
        day = int(re.findall(r'\d+', dt)[-1])
        out.add(datetime.date(yr, MON[mon], day))
    ds = sorted(d for d in out if d <= datetime.date(2026, 8, 31))
    merged = [d for i, d in enumerate(ds) if not (i + 1 < len(ds) and (ds[i + 1] - d).days <= 3)]  # 3日以内の2つは後の日（発表日）に寄せる
    return merged, bad


# ───────────────────────── 計算 ─────────────────────────
def simulate(keys, r, rf, expo, cost, spread, per):
    """倍率 e（株）・1−e（現金 RF、負なら借入 RF+spread）。持ち替え |e − 漂った倍率| × cost。
    戻り値: 費用前・費用後のリターン、年あたりの売買（片道100%の回数）、平均の倍率"""
    g, n, drift, turn, es = {}, {}, None, 0.0, []
    for k in keys:
        e = expo(k)
        p = e * r[k] + (1 - e) * rf[k] - max(e - 1, 0.0) * spread / per
        tr = 0.0 if drift is None else abs(e - drift)
        g[k], n[k] = p, p - tr * cost
        turn += tr; es.append(e)
        drift = e * (1 + r[k]) / (1 + p) if 1 + p > 0 else e
    yrs = len(keys) / per
    return g, n, turn / yrs, S.mean(es)


def simulate_ex(keys, rx, expo, cost, spread, per):
    """超過どうし（国別・JKP）: 株の倍率 e・現金の超過0・借入は (e−1)×spread"""
    g, n, drift = {}, {}, None
    for k in keys:
        e = expo(k)
        p = e * rx[k] - max(e - 1, 0.0) * spread / per
        tr = 0.0 if drift is None else abs(e - drift)
        g[k], n[k] = p, p - tr * cost
        drift = e * (1 + rx[k]) / (1 + p) if 1 + p > 0 else e
    return g, n


def rotation(keys, r_a, r_b, in_b, cost_switch):
    """1月の小型株: in_b(k) の月は r_b、ほかは r_a。持ち替えのたびに cost_switch"""
    g, n, prev, sw = {}, {}, None, 0
    for k in keys:
        b = in_b(k)
        g[k] = r_b[k] if b else r_a[k]
        c = cost_switch if (prev is not None and b != prev) else 0.0
        sw += 1 if c else 0
        n[k] = g[k] - c
        prev = b
    return g, n, sw / (len(keys) / 12)


# ───────────────────────── 税（報告のみ） ─────────────────────────
def tax_sim(keys, rets, rf, weights, cost, spread, per, yearf):
    """日本の課税口座の近似。rets={資産: {k: r}}、weights(k)={資産: 倍率}、cost={資産: 片道費用}。
    売るたびに平均取得単価で実現益・年ごとに通算して20.315%・赤字は3年繰越・現金の利息は受取時に課税・借入の利息は経費。最後に全部売る"""
    H, C = {}, 1.0
    st = {'realized': 0.0, 'ded': 0.0, 'carry': []}

    def close_year(y):
        net = st['realized'] - st['ded']
        st['carry'] = [(yy, l) for yy, l in st['carry'] if y - yy <= 3]
        tax = 0.0
        if net > 0:
            for i, (yy, l) in enumerate(st['carry']):
                use = min(l, net); net -= use; st['carry'][i] = (yy, l - use)
                if net <= 0:
                    break
            st['carry'] = [(yy, l) for yy, l in st['carry'] if l > 1e-15]
            if net > 0:
                tax = net * TAX
        elif net < 0:
            st['carry'].append((y, -net))
        st['realized'] = st['ded'] = 0.0
        return tax

    year, first = None, True
    for k in keys:
        y = yearf(k)
        if year is not None and y != year:
            C -= close_year(year)
        year = y
        nav = C + sum(v for v, b in H.values())
        w = weights(k)
        for a in sorted(set(H) | set(w)):
            v, b = H.get(a, (0.0, 0.0))
            d = w.get(a, 0.0) * nav - v
            if d < -1e-15:
                s = -d
                st['realized'] += s * (1 - b / v) if v > 0 else 0.0
                b = b * (1 - s / v) if v > 0 else 0.0
                v -= s; C += s
            elif d > 1e-15:
                v += d; b += d; C -= d
            if not first:
                C -= abs(d) * cost.get(a, COST)
            H[a] = (v, b)
        first = False
        for a in H:
            v, b = H[a]
            H[a] = (v * (1 + rets[a][k]), b)
        if C >= 0:
            C += C * rf[k] * (1 - TAX)
        else:
            i = C * (rf[k] + spread / per)
            C += i; st['ded'] += -i
    for a, (v, b) in H.items():
        st['realized'] += v - b; C += v
    C -= close_year(year)
    return C


def tax_report(keys, rets, rf, weights, cost, spread, per, yearf):
    out = {}
    for nm, a, z in (('full', None, None), ('train', None, TR_END), ('hold', HO_START, None)):
        ks = [k for k in keys if (a is None or (k // 100 if per == 252 else k) >= a) and (z is None or (k // 100 if per == 252 else k) <= z)]
        if len(ks) < per * 5:
            continue
        ws = tax_sim(ks, rets, rf, weights, cost, spread, per, yearf)
        wb = tax_sim(ks, rets, rf, lambda k: {'m': 1.0}, cost, spread, per, yearf)
        yrs = len(ks) / per
        out[nm] = {'years': round(yrs, 1), 'after_tax_cagr_s': round((ws ** (1 / yrs) - 1) * 100, 2),
                   'after_tax_cagr_b': round((wb ** (1 / yrs) - 1) * 100, 2),
                   'diff': round(((ws ** (1 / yrs)) - (wb ** (1 / yrs))) * 100, 2)}
    return out


# ───────────────────────── 評価 ─────────────────────────
def evaluate(g, n, b, rf, post_pubs, extra=None):
    """g・n・b・rf は月次。g=費用前、n=費用後（0.10%）"""
    ev = {
        'full': M.excess_stats(g, b), 'train': M.excess_stats(g, b, z=TR_END), 'hold': M.excess_stats(g, b, a=HO_START),
        'recent': M.excess_stats(g, b, a=RE_START),
        'net_full': M.excess_stats(n, b), 'net_train': M.excess_stats(n, b, z=TR_END), 'net_hold': M.excess_stats(n, b, a=HO_START),
        'roll20_net': M.rolling(n, b, 20), 'dca20_net': M.dca(n, b, 20),
        'sharpe': {'train': (M.sharpe(n, rf, z=TR_END), M.sharpe(b, rf, z=TR_END)),
                   'hold': (M.sharpe(n, rf, a=HO_START), M.sharpe(b, rf, a=HO_START)),
                   'full': (M.sharpe(n, rf), M.sharpe(b, rf))},
        'maxdd': {'s_net': round(M.maxdd(n) * 100, 1), 'b': round(M.maxdd({k: b[k] for k in n if k in b}) * 100, 1)},
        'postpub': {},
    }
    for lab, a in post_pubs:
        ev['postpub'][lab] = {'gross': M.excess_stats(g, b, a=a), 'net': M.excess_stats(n, b, a=a)}
    if extra:
        ev.update(extra)
    return ev


def compact(st):
    if not st:
        return None
    return {k: st[k] for k in ('from', 'to', 'years', 'ex_ann', 't', 'p', 'cagr_s', 'cagr_b', 'cagr_diff', 'te', 'ir', 'beta', 'vol_s', 'vol_b')}


# ───────────────────────── データ ─────────────────────────
def fr_region_daily(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'daily':
            cols = [c.lower().replace('-', '') for c in v['cols']]
            im, ir = cols.index('mktrf'), cols.index('rf')
            mk, rf = {}, {}
            for d, row in v['data'].items():
                if row[im] is not None and row[ir] is not None:
                    mk[d] = (row[im] + row[ir]) / 100; rf[d] = row[ir] / 100
            return mk, rf
    raise KeyError(name)


def jkp_daily(c):
    rows = M.jkp_rows(c, 'mkt', 'factor', 'vw', 'daily')
    return {int(x['date'].replace('-', '')): float(x['ret']) for x in rows if x['ret'] not in ('', 'NA', 'na')}


def load():
    ffd, ffm = M.ff_factors('daily'), M.ff_factors('monthly')
    me = M.french_series('Portfolios_Formed_on_ME', 'Value Weight', 'monthly')
    D = sorted(k for k in ffd['mkt'] if k in ffd['rf'])
    fomc, bad = fomc_dates()
    return {'ffd': ffd, 'ffm': ffm, 'me': me, 'D': D, 'fomc': fomc, 'fomc_bad': bad}


# ───────────────────────── 規則 ─────────────────────────
def hal(ym):
    return ym % 100 in (11, 12, 1, 2, 3, 4)


def daily_rule_sets(dates, fomc_keys, us=True):
    """日次の規則が使う暦の集合（その市場の暦で）"""
    ds = sorted(dates)
    if us:
        ph, gaps = preholiday_set(ds, 'scheduled')
        ph_all, _ = preholiday_set(ds, 'all')
    else:
        ph, gaps = preholiday_set(ds, 'local', maxgap=5)
        ph_all = ph
    dset = set(ds)
    fom = set(k for k in fomc_keys if k in dset)
    prev = {b: a for a, b in zip(ds, ds[1:])}
    fom2 = fom | set(prev[k] for k in fom if k in prev)
    return {'tom': tom_set(ds), 'ph': ph, 'ph_all': ph_all, 'fomc': fom, 'fomc2': fom2, 'santa': santa_set(ds),
            'ariel': ariel_set(ds), 'lunar': lunar_set(ds), 'gaps': gaps, 'dates': ds}


def lazy(c, key, fn):
    if key not in c:
        c[key] = fn(c['dates'])
    return c[key]


def turn_set(dates, m, a, b):
    """月 m の最後の a 立会日＋翌月の最初の b 立会日（m=12 なら12月→1月＝年末年始）"""
    g = month_groups(dates)
    yms = sorted(g)
    fp, lp = edges_ok(dates)
    m2 = 1 if m == 12 else m + 1
    s = set()
    for i, ym in enumerate(yms):
        if ym % 100 == m and a > 0 and not (i == len(yms) - 1 and lp):
            s.update(g[ym][-a:])
        if ym % 100 == m2 and b > 0 and not (i == 0 and fp):
            s.update(g[ym][:b])
    return s


# 各戦略: (id, 族, 説明, 種類, 規則)。種類: 'd'=日次の倍率、'm'=月次の倍率、'rot'=1月の小型株
def specs():
    L = []
    P, E = 'primary', 'exploratory'
    L.append(('P1_HAL_SW', P, 'ハロウィーンの切替（11〜4月 Mkt・5〜10月 RF）', 'm', lambda ym, c: 1.0 if hal(ym) else 0.0, 'hal'))
    L.append(('P2_HAL_OV15', P, 'ハロウィーンの上乗せ（11〜4月1.5倍・5〜10月1倍）', 'm', lambda ym, c: 1.5 if hal(ym) else 1.0, 'hal'))
    L.append(('P3_TOM_SW', P, '月替わりの切替（TOM の日だけ Mkt）', 'd', lambda k, c: 1.0 if k in c['tom'] else 0.0, 'tom'))
    L.append(('P4_TOM_OV15', P, '月替わりの上乗せ（TOM 1.5倍）', 'd', lambda k, c: 1.5 if k in c['tom'] else 1.0, 'tom'))
    L.append(('P5_PH_SW', P, '祝日前の切替（定例の祝日の前日だけ Mkt）', 'd', lambda k, c: 1.0 if k in c['ph'] else 0.0, 'ph'))
    L.append(('P6_PH_OV15', P, '祝日前の上乗せ（1.5倍）', 'd', lambda k, c: 1.5 if k in c['ph'] else 1.0, 'ph'))
    L.append(('P7_JAN_SC10', P, '1月の小型株（1月は Lo 10・ほかは Mkt）', 'rot', 'Lo 10', 'jan'))
    L.append(('P8_FOMC_SW', P, 'FOMC 発表日の切替（1994-02〜）', 'd', lambda k, c: 1.0 if k in c['fomc'] else 0.0, 'fomc'))
    L.append(('P9_FOMC_OV15', P, 'FOMC 発表日の上乗せ（1.5倍・1994-02〜）', 'd', lambda k, c: 1.5 if k in c['fomc'] else 1.0, 'fomc'))
    L.append(('E01_HAL_TILT', E, 'ハロウィーンの傾け（11〜4月1.5倍・5〜10月0.5倍＝平均1.0）', 'm', lambda ym, c: 1.5 if hal(ym) else 0.5, 'hal'))
    L.append(('E02_HAL_OV20', E, 'ハロウィーンの上乗せ2倍', 'm', lambda ym, c: 2.0 if hal(ym) else 1.0, 'hal'))
    L.append(('E03_TOM_OV20', E, '月替わりの上乗せ2倍', 'd', lambda k, c: 2.0 if k in c['tom'] else 1.0, 'tom'))
    L.append(('E04_TOM_TILT', E, '月替わりの傾け（TOM 1.5倍・ほか0.88倍）', 'd', lambda k, c: 1.5 if k in c['tom'] else 0.88, 'tom'))
    L.append(('E05_ARIEL_OV15', E, 'Ariel 型の月の前半1.5倍', 'd', lambda k, c: 1.5 if k in c['ariel'] else 1.0, 'tom'))
    L.append(('E06_SANTA_OV15', E, 'サンタクロース・ラリー1.5倍', 'd', lambda k, c: 1.5 if k in c['santa'] else 1.0, 'santa'))
    L.append(('E07_CALCOMBO_OV15', E, 'TOM∨祝日前∨FOMC∨サンタ 1.5倍', 'd',
              lambda k, c: 1.5 if (k in c['tom'] or k in c['ph'] or k in c['fomc'] or k in c['santa']) else 1.0, 'tom'))
    L.append(('E08_HALTOM_OV15', E, '11〜4月∨TOM 1.5倍', 'd', lambda k, c: 1.5 if (hal(k // 100) or k in c['tom']) else 1.0, 'hal'))
    L.append(('E09_LUNAR_OV15', E, '新月の前後±7日 1.5倍', 'd', lambda k, c: 1.5 if k in c['lunar'] else 1.0, 'lunar'))
    L.append(('E10_JAN_BAROMETER', E, '1月のバロメーター（1月が負なら2〜12月は RF）', 'jb', None, 'hirsch'))
    L.append(('E11_PRES_OV15', E, '大統領選挙の前年は通年1.5倍', 'm', lambda ym, c: 1.5 if (ym // 100) % 4 == 3 else 1.0, 'hirsch'))
    L.append(('E12_JAN_SC20', E, '1月の小型株（Lo 20）', 'rot', 'Lo 20', 'jan'))
    L.append(('E13_JAN_SC30', E, '1月の小型株（Lo 30）', 'rot', 'Lo 30', 'jan'))
    L.append(('E14_SEPT_AVOID', E, '9月を避ける（9月は RF）', 'm', lambda ym, c: 0.0 if ym % 100 == 9 else 1.0, 'none'))
    L.append(('E15_FOMC2D_OV15', E, 'FOMC の前日と発表日 1.5倍', 'd', lambda k, c: 1.5 if k in c['fomc2'] else 1.0, 'fomc'))
    L.append(('S_PH_ALLGAP_SW', 'sensitivity', '祝日前の切替（平日の欠けすべて・後知恵を含む）', 'd', lambda k, c: 1.0 if k in c['ph_all'] else 0.0, 'ph'))
    L.append(('S_PH_ALLGAP_OV15', 'sensitivity', '祝日前の上乗せ（平日の欠けすべて・後知恵を含む）', 'd', lambda k, c: 1.5 if k in c['ph_all'] else 1.0, 'ph'))
    return L


POSTPUB = {'hal': [('post2003', 200301)], 'tom': [('post1988', 198801)], 'ph': [('post1991', 199101)],
           'jan': [('post1984', 198401)], 'fomc': [('post2012', 201201), ('post2016', 201601)],
           'hirsch': [('post1973', 197301)], 'santa': [('post1973', 197301)], 'lunar': [('post2007', 200701)], 'none': []}


# ───────────────────────── 国別（C5） ─────────────────────────
def country_data():
    cm, cd, cs, miss = {}, {}, {}, {'monthly': [], 'daily': [], 'size': []}
    for c in DEV + EM:
        try:
            cm[c] = M.jkp_mkt(c, 'vw')
        except Exception as e:  # noqa
            miss['monthly'].append(c); log('monthly miss', c, e)
        try:
            cd[c] = jkp_daily(c)
        except Exception as e:  # noqa
            miss['daily'].append(c); log('daily miss', c, e)
        try:
            p = M.jkp_portfolios(c, 'market_equity', 'vw')
            cs[c] = p.get('1.0')
            if not cs[c]:
                miss['size'].append(c)
        except Exception as e:  # noqa
            miss['size'].append(c); log('size miss', c, e)
    return cm, cd, cs, miss


def country_eval(spec, CD, fomc_keys, rf_m, keep=None):
    sid, fam, desc, kind, rule, tag = spec
    cm, cd, cs, miss = CD
    res = []
    for c in DEV + EM:
        cost = COST if c in DEV else 0.003
        try:
            if kind == 'm':
                rx = cm.get(c)
                if not rx:
                    continue
                ks = sorted(rx)
                g, n = simulate_ex(ks, rx, lambda ym: rule(ym, None), cost, SPREAD, 12)
                b = {k: rx[k] for k in ks}
            elif kind == 'jb':
                rx = cm.get(c)
                if not rx:
                    continue
                ks = [k for k in sorted(rx) if k in rf_m]
                jan = {k // 100: (rx[k] + rf_m[k]) for k in ks if k % 100 == 1}
                g, n = jb_ex(ks, rx, jan, cost)
                b = {k: rx[k] for k in g}
            elif kind == 'rot':
                rx, sm = cm.get(c), cs.get(c)
                if not rx or not sm:
                    continue
                ks = sorted(set(rx) & set(sm))
                g, n, _ = rotation(ks, rx, sm, lambda ym: ym % 100 == 1, 0.004 if c in DEV else 0.006)
                b = {k: rx[k] for k in ks}
            else:
                rx = cd.get(c)
                if not rx:
                    continue
                ks = sorted(rx)
                if c not in CAL_CACHE:
                    CAL_CACHE[c] = daily_rule_sets(ks, fomc_keys, us=False)
                cal = CAL_CACHE[c]
                if tag == 'fomc':
                    ks = [k for k in ks if k >= 19940201]
                gd, nd = simulate_ex(ks, rx, lambda k: rule(k, cal), cost, SPREAD, 252)
                g, n = M.to_monthly(gd), M.to_monthly(nd)
                b = M.to_monthly({k: rx[k] for k in ks})
            if keep is not None:
                keep[c] = (n, b)
            if min(n.values()) <= -1:  # 全損＝その国は負け（分母に残す・ルール7: 黙って落とさない）
                wk = min(k for k in n if n[k] <= -1)
                res.append([c, None, None, None, None, None, round(len(n) / 12, 1), f'全損 {wk}'])
                continue
            st = M.excess_stats(n, b)
            sh = M.excess_stats(n, b, a=HO_START)
            if not st:
                continue
            res.append([c, st['ex_ann'], st['cagr_diff'], st['t'], sh['ex_ann'] if sh else None, sh['cagr_diff'] if sh else None, st['years']])
        except Exception as e:  # noqa
            log('country err', sid, c, repr(e))
    pos = sum(1 for x in res if x[1] is not None and x[1] > 0 and x[2] > 0)
    pos_h = sum(1 for x in res if x[4] is not None and x[4] > 0 and x[5] > 0)
    nh = sum(1 for x in res if x[4] is not None or x[1] is None)
    dev = [x for x in res if x[0] in DEV]
    ok = [x[1] for x in res if x[1] is not None]
    return {'regions': len(res), 'positive': pos, 'share': round(pos / len(res), 3) if res else None,
            'hold_positive': pos_h, 'hold_regions': nh, 'wipeouts': [x[0] for x in res if x[1] is None],
            'dev_positive': sum(1 for x in dev if x[1] is not None and x[1] > 0 and x[2] > 0), 'dev_regions': len(dev),
            'median_ex_ann': round(S.median(ok), 2) if ok else None,
            'jpn': next((x for x in res if x[0] == 'jpn'), None),
            'detail_cols': ['国', '全期間の超過(費用後)', '幾何の年率差', 't', '保有の超過', '保有の幾何差', '年数'], 'detail': res}


def jb_ex(ks, rx, jan, cost):
    g, n, prev = {}, {}, None
    for k in ks:
        y, m = k // 100, k % 100
        if m == 1:
            e = 1.0
        elif y in jan:
            e = 1.0 if jan[y] > 0 else 0.0
        else:
            e = 1.0  # その年の1月のデータが無い＝規則が決まらない→市場のまま（空欄を0と読まない）
        p = e * rx[k]
        c = cost * abs(e - prev) if prev is not None else 0.0
        g[k], n[k] = p, p - c
        prev = e
    return g, n


CAL_CACHE = {}


# ───────────────────────── 第2族（探索・out/mw_calendar_prereg2.json） ─────────────────────────
def ndx_tr():
    """NDX の日次総リターン: 1999-03-10 までは ^NDX の価格＋推定配当 年0.5%、1999-03-11 からは QQQ の調整後"""
    px, q = M.yahoo('^NDX', '1d'), M.yahoo('QQQ', '1d')
    tr = {k: v + 0.005 / 252 for k, v in px.items() if k <= 19990310}
    tr.update({k: v for k, v in q.items() if k >= 19990311})
    return {k: tr[k] for k in sorted(tr) if k <= 20260831}


def rf_carry(keys, rf):
    """keys の日の RF。French に無い日は直前の French の日の RF（0で埋めない）。使った日数も返す"""
    fr = sorted(rf)
    out, miss, j, last = {}, 0, 0, None
    for k in keys:
        while j < len(fr) and fr[j] <= k:
            last = fr[j]; j += 1
        if k in rf:
            out[k] = rf[k]
        elif last is not None:
            out[k] = rf[last]; miss += 1
    return out, miss


def eval_total(ks, r, rf, rule, per, tag, const_ok=True):
    """総リターンの原資産に倍率の規則を当てて evaluate（費用0.10%・0.05%・借入1.5% も）"""
    gd, nd, turn, avg = simulate(ks, r, rf, rule, COST, SPREAD, per)
    _, nd5, _, _ = simulate(ks, r, rf, rule, COST_LO, SPREAD, per)
    _, ndh, _, _ = simulate(ks, r, rf, rule, COST, SPREAD_HI, per)
    tm = M.to_monthly if per == 252 else (lambda x: x)
    g, n, n5, nh = tm(gd), tm(nd), tm(nd5), tm(ndh)
    b = tm({k: r[k] for k in ks}); rfm = tm({k: rf[k] for k in ks})
    ev = evaluate(g, n, b, rfm, POSTPUB.get(tag, []))
    ev['net_hold_cost005'] = M.excess_stats(n5, b, a=HO_START)
    ev['net_hold_spread15_or_smallcost1pct'] = M.excess_stats(nh, b, a=HO_START)
    ev['avg_exposure'] = round(avg, 3); ev['turnover_oneway_per_year'] = round(turn, 2)
    if const_ok and avg > 1.0001:
        _, ndc, _, _ = simulate(ks, r, rf, lambda k: avg, COST, SPREAD, per)
        cst = tm(ndc)
        ev['vs_constant_exposure'] = {'const_L': round(avg, 3), 'full': compact(M.excess_stats(n, cst)),
                                      'train': compact(M.excess_stats(n, cst, z=TR_END)), 'hold': compact(M.excess_stats(n, cst, a=HO_START))}
    return ev, n, b


def eval_excess(ks, rx, rule, per, tag, cost=COST, cost_lo=COST_LO):
    """超過の原資産（JKP）に倍率の規則。シャープレシオは超過そのもの（RF=0 として渡す）"""
    gd, nd = simulate_ex(ks, rx, rule, cost, SPREAD, per)
    _, nd5 = simulate_ex(ks, rx, rule, cost_lo, SPREAD, per)
    _, ndh = simulate_ex(ks, rx, rule, cost, SPREAD_HI, per)
    tm = M.to_monthly if per == 252 else (lambda x: x)
    g, n, n5, nh = tm(gd), tm(nd), tm(nd5), tm(ndh)
    b = tm({k: rx[k] for k in ks})
    zero = {k: 0.0 for k in b}
    ev = evaluate(g, n, b, zero, POSTPUB.get(tag, []))
    ev['net_hold_cost005'] = M.excess_stats(n5, b, a=HO_START)
    ev['net_hold_spread15_or_smallcost1pct'] = M.excess_stats(nh, b, a=HO_START)
    avg = S.mean(rule(k) for k in ks)
    ev['avg_exposure'] = round(avg, 3)
    if avg > 1.0001:
        _, ndc = simulate_ex(ks, rx, lambda k: avg, cost, SPREAD, per)
        cst = tm(ndc)
        ev['vs_constant_exposure'] = {'const_L': round(avg, 3), 'full': compact(M.excess_stats(n, cst)),
                                      'train': compact(M.excess_stats(n, cst, z=TR_END)), 'hold': compact(M.excess_stats(n, cst, a=HO_START))}
    ev['note'] = '超過どうし（JKP・米国 T-bill を引いた値）。シャープレシオは超過の平均÷標準偏差'
    return ev, n, b


def family2(ctx, CD, cal, tested):
    D, r, rf, ffm, fomc_keys = ctx['D'], ctx['r'], ctx['rf'], ctx['ffm'], ctx['fomc_keys']
    bm_d = ctx['bm_d']
    X = 'exploratory2'
    diag = {}
    # X01: 年末年始の窓を訓練期間だけで選ぶ
    log('X01 grid')
    grid = []
    for a in range(1, 11):
        for b_ in range(0, 11):
            win = turn_set(D, 12, a, b_)
            _, nd, _, _ = simulate(D, r, rf, lambda k: 1.5 if k in win else 1.0, COST, SPREAD, 252)
            n = M.to_monthly(nd)
            tr = M.excess_stats(n, bm_d, z=TR_END); ho = M.excess_stats(n, bm_d, a=HO_START)
            grid.append({'a': a, 'b': b_, 'train_net_ex': tr['ex_ann'], 'train_net_t': tr['t'], 'hold_net_ex': ho['ex_ann'], 'hold_net_t': ho['t'],
                         'hold_net_cagr_diff': ho['cagr_diff']})
    best = max(grid, key=lambda x: (x['train_net_t'], -(x['a'] + x['b'])))
    A, B = best['a'], best['b']
    diag['D4_toy_grid_surface'] = {'selected': (A, B), 'selection': '訓練（〜2006）の費用後の NW t が最大', 'grid': grid,
                                   'hold_net_positive_share': round(sum(1 for x in grid if x['hold_net_ex'] > 0 and x['hold_net_cagr_diff'] > 0) / len(grid), 3)}
    log('X01 selected', A, B, best)
    toy_key = f'toy_{A}_{B}'
    specs2 = [
        ('X01_TOY_SEL', X, f'年末年始の窓（訓練で選んだ 12月の最後の{A}立会日＋1月の最初の{B}立会日）1.5倍', 'd',
         lambda k, c: 1.5 if k in lazy(c, toy_key, lambda ds: turn_set(ds, 12, A, B)) else 1.0, 'santa'),
        ('X02_SANTA_OV20', X, 'サンタクロース・ラリー2倍', 'd', lambda k, c: 2.0 if k in c['santa'] else 1.0, 'santa'),
    ]
    for sp in specs2:
        sid, fam, desc, kind, rule, tag = sp
        log('run', sid)
        ev, n, b = eval_total(D, r, rf, lambda k: rule(k, cal), 252, tag)
        ev['repl'] = country_eval(sp, CD, fomc_keys, ffm['rf'])
        ev['tax_japan'] = None
        tested.append({'id': sid, 'family': fam, 'desc': desc, 'kind': kind, 'ev': ev})
    # X03・X04: NASDAQ-100
    ndx = ndx_tr()
    kn = sorted(ndx)
    rfn, miss = rf_carry(kn, rf)
    kn = [k for k in kn if k in rfn]
    big = sorted(((k, v) for k, v in ndx.items() if abs(v) > 0.2), key=lambda x: -abs(x[1]))
    diag['ndx_data'] = {'from': kn[0], 'to': kn[-1], 'days': len(kn), 'rf_carried_days': miss, 'abs_ret_gt_20pct': big[:10]}
    santa_n = santa_set(kn)
    for sid, desc, rule, tag in (('X03_SANTA_OV15_NDX', 'NASDAQ-100 にサンタ1.5倍', lambda k: 1.5 if k in santa_n else 1.0, 'santa'),
                                 ('X04_HAL_OV15_NDX', 'NASDAQ-100 にハロウィーン1.5倍（日次）', lambda k: 1.5 if hal(k // 100) else 1.0, 'hal')):
        log('run', sid)
        ev, n, b = eval_total(kn, ndx, rfn, rule, 252, tag)
        ev['tax_japan'] = None
        tested.append({'id': sid, 'family': X, 'desc': desc, 'kind': 'd_ndx', 'ev': ev,
                       'repl_from': 'E06_SANTA_OV15' if 'SANTA' in sid else 'P2_HAL_OV15'})
    # X05・X06: 世界（JKP world vw）
    wd = jkp_daily('world')
    kw = sorted(wd)
    santa_w = santa_set(kw)
    log('run X05')
    ev, n, b = eval_excess(kw, wd, lambda k: 1.5 if k in santa_w else 1.0, 252, 'santa')
    tested.append({'id': 'X05_SANTA_OV15_WORLD', 'family': X, 'desc': '世界の市場（JKP world）にサンタ1.5倍', 'kind': 'd_world', 'ev': ev, 'repl_from': 'E06_SANTA_OV15'})
    wm = M.jkp_mkt('world', 'vw')
    km = sorted(wm)
    log('run X06')
    ev, n, b = eval_excess(km, wm, lambda ym: 1.5 if hal(ym) else 1.0, 12, 'hal')
    tested.append({'id': 'X06_HAL_OV15_WORLD', 'family': X, 'desc': '世界の市場（JKP world 月次）にハロウィーン1.5倍', 'kind': 'm_world', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})
    # X07: 年末年始の小型株（Lo 30 日次）
    log('run X07')
    lo30 = M.french_series('Portfolios_Formed_on_ME_Daily', 'Value Weight', 'daily')['Lo 30']
    ks = [k for k in D if k in lo30]
    win = turn_set(ks, 12, 1, 5)
    gd, nd, _ = rotation(ks, r, lo30, lambda k: k in win, 0.004)
    _, nd5, _ = rotation(ks, r, lo30, lambda k: k in win, 0.003)
    _, ndh, _ = rotation(ks, r, lo30, lambda k: k in win, 0.011)
    sw = sum(1 for a_, b2 in zip(ks, ks[1:]) if (a_ in win) != (b2 in win)) / (len(ks) / 252)
    g, n, n5, nh = M.to_monthly(gd), M.to_monthly(nd), M.to_monthly(nd5), M.to_monthly(ndh)
    b = M.to_monthly({k: r[k] for k in ks}); rfm = M.to_monthly({k: rf[k] for k in ks})
    ev = evaluate(g, n, b, rfm, [('post1984', 198401)])
    ev['net_hold_cost005'] = M.excess_stats(n5, b, a=HO_START)
    ev['net_hold_spread15_or_smallcost1pct'] = M.excess_stats(nh, b, a=HO_START)
    ev['avg_exposure'] = 1.0; ev['turnover_oneway_per_year'] = round(sw, 2); ev['tax_japan'] = None
    ev['repl'] = {'regions': 0, 'positive': 0, 'note': '国別の日次の小型株が無い＝N/A'}
    tested.append({'id': 'X07_TOY_SC30', 'family': X, 'desc': '年末年始（12月の最終立会日＋1月の最初の5立会日）は Lo 30、ほかは Mkt', 'kind': 'rot_d', 'ev': ev})

    # 診断（判定しない）
    log('diagnostics')
    d1 = {}
    for m in range(1, 12):
        win = turn_set(D, m, 5, 2)
        _, nd, _, _ = simulate(D, r, rf, lambda k: 1.5 if k in win else 1.0, COST, SPREAD, 252)
        n = M.to_monthly(nd)
        d1[f'{m:02d}->{(m % 12) + 1:02d}'] = {'full': compact(M.excess_stats(n, bm_d)), 'train': compact(M.excess_stats(n, bm_d, z=TR_END)),
                                            'hold': compact(M.excess_stats(n, bm_d, a=HO_START))}
    diag['D1_placebo_other_months'] = d1
    # D2: 2008-12・2009-01 を除く（事後の疑い）
    sp6 = [t for t in specs() if t[0] == 'E06_SANTA_OV15'][0]
    _, nd, _, _ = simulate(D, r, rf, lambda k: sp6[4](k, cal), COST, SPREAD, 252)
    n = M.to_monthly(nd)
    ex = (200812, 200901)
    nn = {k: v for k, v in n.items() if k not in ex}; bb = {k: v for k, v in bm_d.items() if k not in ex}
    keep = {}
    country_eval(sp6, CD, fomc_keys, ffm['rf'], keep=keep)
    cnt = []
    for c, (cn, cb) in keep.items():
        st = M.excess_stats({k: v for k, v in cn.items() if k not in ex}, {k: v for k, v in cb.items() if k not in ex}, a=HO_START)
        if st:
            cnt.append((c, st['ex_ann'], st['cagr_diff']))
    diag['D2_santa_ex_2008'] = {'label': '事後（結果を見た後の疑い）・判定しない', 'us_hold_net': compact(M.excess_stats(nn, bb, a=HO_START)),
                                'us_hold_net_with': compact(M.excess_stats(n, bm_d, a=HO_START)),
                                'countries_hold_positive': sum(1 for c, e, g_ in cnt if e > 0 and g_ > 0), 'countries': len(cnt),
                                'detail': cnt}
    # D3: JKP usa 日次で同じサンタ
    ud = jkp_daily('usa')
    ku = sorted(ud)
    su = santa_set(ku)
    ev3, n3, b3 = eval_excess(ku, ud, lambda k: 1.5 if k in su else 1.0, 252, 'santa')
    diag['D3_santa_jkp_us'] = {'full': compact(ev3['full']), 'train': compact(ev3['train']), 'hold': compact(ev3['hold']),
                               'net_hold': compact(ev3['net_hold']), 'net_full': compact(ev3['net_full'])}
    return diag


# ───────────────────────── 第3族（探索・out/mw_calendar_prereg3.json） ─────────────────────────
def fr_region_monthly(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly':
            cols = [c.lower().replace('-', '') for c in v['cols']]
            im, ir = cols.index('mktrf'), cols.index('rf')
            mk, rf = {}, {}
            for d, row in v['data'].items():
                if row[im] is not None and row[ir] is not None:
                    mk[d] = (row[im] + row[ir]) / 100; rf[d] = row[ir] / 100
            return mk, rf
    raise KeyError(name)


def fomc_cycle_class(D, fomc_keys):
    """CMVJ 2019: 発表日=0 の立会日で数え、偶数週（−1..3, 9..13, 19..23, 29..33）='even'、奇数週（4..8, 14..18, 24..28）='odd'、34日以降='other'"""
    idx = {k: i for i, k in enumerate(D)}
    fi = sorted(idx[k] for k in fomc_keys if k in idx)
    out, j = {}, 0
    for i, k in enumerate(D):
        while j < len(fi) and fi[j] < i:
            j += 1
        nxt = fi[j] if j < len(fi) else None      # i 以降で最初の発表日
        last = fi[j - 1] if j > 0 else None      # i より前の最後の発表日
        if nxt is not None and nxt == i:
            cd = 0
        elif nxt is not None and nxt - i == 1:
            cd = -1
        elif last is not None:
            cd = i - last
        else:
            out[k] = 'none'; continue
        if -1 <= cd <= 3 or 9 <= cd <= 13 or 19 <= cd <= 23 or 29 <= cd <= 33:
            out[k] = 'even'
        elif 4 <= cd <= 8 or 14 <= cd <= 18 or 24 <= cd <= 28:
            out[k] = 'odd'
        else:
            out[k] = 'other'
    return out


US_CYC = {}


def local_cycle(ds):
    """国の暦の日 d に、d 以前で最も新しい米国の立会日の周期の区分を当てる"""
    us = sorted(US_CYC)
    out, j = {}, 0
    for k in ds:
        while j < len(us) and us[j] <= k:
            j += 1
        out[k] = US_CYC[us[j - 1]] if j > 0 else 'none'
    return out


def fx_diag(D, santa):
    """【事後】ドルの季節性: FRED の日次の為替。サンタの日とほかの日、11〜4月と5〜10月の平均の変化（%/日）"""
    out = {}
    for sid, desc in (('DTWEXM', '主要通貨に対するドル（上がる＝ドル高）'), ('DTWEXBGS', '広義のドル（上がる＝ドル高）'), ('DEXJPUS', '1ドルあたりの円（上がる＝円安・ドル高）')):
        try:
            txt = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=30).decode()
        except Exception as e:  # noqa
            out[sid] = {'error': str(e)[:200]}; continue
        px = {}
        for line in txt.splitlines()[1:]:
            a = line.split(',')
            if len(a) >= 2 and a[1] not in ('', '.'):
                try:
                    px[int(a[0].replace('-', ''))] = float(a[1])
                except ValueError:
                    pass
        ks = sorted(px)
        ch = {b: math.log(px[b] / px[a]) for a, b in zip(ks, ks[1:])}
        sa = [v for k, v in ch.items() if k in santa]
        ot = [v for k, v in ch.items() if k not in santa]
        win = [v for k, v in ch.items() if hal(k // 100)]
        sum_ = [v for k, v in ch.items() if not hal(k // 100)]
        out[sid] = {'desc': desc, 'from': ks[0], 'to': ks[-1],
                    'santa_days_mean_pct': round(S.mean(sa) * 100, 4) if sa else None, 'n_santa': len(sa),
                    'other_days_mean_pct': round(S.mean(ot) * 100, 4) if ot else None,
                    'santa_window_sum_pct_per_year': round(S.mean(sa) * 7 * 100, 3) if sa else None,
                    'nov_apr_ann_pct': round(S.mean(win) * 252 * 100, 2) if win else None,
                    'may_oct_ann_pct': round(S.mean(sum_) * 252 * 100, 2) if sum_ else None}
    return out


def family3(ctx, CD, cal, tested):
    D, r, rf, ffm, fomc_keys = ctx['D'], ctx['r'], ctx['rf'], ctx['ffm'], ctx['fomc_keys']
    Y = 'exploratory3'
    diag = {}
    dev_d, dev_rf = fr_region_daily('Developed_3_Factors_Daily')
    kd = sorted(k for k in dev_d if k in dev_rf)
    santa_dev = santa_set(kd)
    log('run Y01')
    ev, n, b = eval_total(kd, dev_d, dev_rf, lambda k: 1.5 if k in santa_dev else 1.0, 252, 'santa')
    ev['tax_japan'] = tax_report(kd, {'m': dev_d}, dev_rf, lambda k: {'m': 1.5 if k in santa_dev else 1.0}, {'m': COST}, SPREAD, 252, lambda k: k // 10000)
    tested.append({'id': 'Y01_SANTA_OV15_DEV', 'family': Y, 'desc': 'French Developed 日次にサンタ1.5倍', 'kind': 'd_dev', 'ev': ev, 'repl_from': 'E06_SANTA_OV15'})
    dev_m, dev_rfm = fr_region_monthly('Developed_3_Factors')
    km = sorted(k for k in dev_m if k in dev_rfm)
    log('run Y02')
    ev, n, b = eval_total(km, dev_m, dev_rfm, lambda ym: 1.5 if hal(ym) else 1.0, 12, 'hal')
    ev['tax_japan'] = tax_report(km, {'m': dev_m}, dev_rfm, lambda ym: {'m': 1.5 if hal(ym) else 1.0}, {'m': COST}, SPREAD, 12, lambda k: k // 100)
    tested.append({'id': 'Y02_HAL_OV15_DEV', 'family': Y, 'desc': 'French Developed 月次にハロウィーン1.5倍', 'kind': 'm_dev', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})
    wx = M.jkp_mkt('world_ex_us', 'vw')
    kx = sorted(wx)
    log('run Y03')
    ev, n, b = eval_excess(kx, wx, lambda ym: 1.5 if hal(ym) else 1.0, 12, 'hal')
    tested.append({'id': 'Y03_HAL_OV15_WXUS', 'family': Y, 'desc': 'JKP world_ex_us 月次にハロウィーン1.5倍', 'kind': 'm_wxus', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})
    dx_d, dx_rf = fr_region_daily('Developed_ex_US_3_Factors_Daily')
    kx2 = sorted(k for k in dx_d if k in dx_rf)
    santa_dx = santa_set(kx2)
    log('run Y04')
    ev, n, b = eval_total(kx2, dx_d, dx_rf, lambda k: 1.5 if k in santa_dx else 1.0, 252, 'santa')
    ev['tax_japan'] = None
    tested.append({'id': 'Y04_SANTA_OV15_DXUS', 'family': Y, 'desc': 'French Developed_ex_US 日次にサンタ1.5倍', 'kind': 'd_dxus', 'ev': ev, 'repl_from': 'E06_SANTA_OV15'})
    # FOMC 周期
    US_CYC.clear(); US_CYC.update(fomc_cycle_class(D, fomc_keys))
    ks94 = [k for k in D if k >= 19940201]
    cyc_counts = {c_: sum(1 for k in ks94 if US_CYC[k] == c_) for c_ in ('even', 'odd', 'other', 'none')}
    diag['fomc_cycle_day_counts'] = cyc_counts
    POSTPUB['fomccyc'] = [('post2016', 201601), ('post2020', 202001)]
    ysp = [('Y05_FOMCCYC_SW', Y, 'FOMC 周期の偶数週は Mkt・ほかは RF', 'd', lambda k, c: 1.0 if (c['cyc'] if 'cyc' in c else lazy(c, 'cyc', local_cycle)).get(k) == 'even' else 0.0, 'fomccyc'),
           ('Y06_FOMCCYC_OV15', Y, 'FOMC 周期の偶数週1.5倍', 'd', lambda k, c: 1.5 if lazy(c, 'cyc', local_cycle).get(k) == 'even' else 1.0, 'fomccyc'),
           ('Y07_FOMCCYC_TILT', Y, 'FOMC 周期の偶数週1.5倍・奇数週0.5倍', 'd',
            lambda k, c: {'even': 1.5, 'odd': 0.5}.get(lazy(c, 'cyc', local_cycle).get(k), 1.0), 'fomccyc')]
    cal_us = dict(cal); cal_us['cyc'] = US_CYC
    for sp in ysp:
        sid, fam, desc, kind, rule, tag = sp
        log('run', sid)
        ev, n, b = eval_total(ks94, r, rf, lambda k: rule(k, cal_us), 252, tag)
        ev['tax_japan'] = None
        # 国別: 1994-02 以降の日だけ（country_eval の 'fomc' タグと同じ扱い）
        ev['repl'] = country_eval((sid, fam, desc, kind, rule, 'fomc'), CD, fomc_keys, ffm['rf'])
        tested.append({'id': sid, 'family': fam, 'desc': desc, 'kind': kind, 'ev': ev})
    log('run Y08')
    ev, n, b = eval_total(kd, dev_d, dev_rf, lambda k: 2.0 if k in santa_dev else (1.5 if hal(k // 100) else 1.0), 252, 'hal')
    ev['tax_japan'] = None
    tested.append({'id': 'Y08_HALSANTA_DEV', 'family': Y, 'desc': '【事後の組み合わせ】Developed 日次: 11〜4月1.5倍＋サンタの日2倍', 'kind': 'd_dev', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})

    # 診断
    diag['D5_fx'] = {'label': '事後（結果を見た後の疑い）・判定しない', **fx_diag(D, cal['santa'])}
    d7 = {}
    for nm in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'North_America', 'Developed_ex_US'):
        try:
            mk, rr = fr_region_daily(f'{nm}_3_Factors_Daily')
            kk = sorted(k for k in mk if k in rr)
            ss = santa_set(kk)
            e7, _, _ = eval_total(kk, mk, rr, lambda k: 1.5 if k in ss else 1.0, 252, 'santa', const_ok=False)
            d7[nm] = {k: compact(e7[k]) for k in ('full', 'train', 'hold', 'net_full', 'net_hold')}
        except Exception as e:  # noqa
            d7[nm] = {'error': str(e)[:200]}
    diag['D7_french_regions_santa'] = d7
    wd = jkp_daily('world')
    import collections
    wkc = collections.Counter(ymd(k).weekday() for k in wd)
    wm = M.jkp_mkt('world', 'vw'); mm = M.to_monthly(wd)
    def vol(xs):
        return round(S.stdev(xs) * math.sqrt(12) * 100, 2)
    diag['D8_world_daily_defect'] = {'weekday_counts_mon0': dict(sorted(wkc.items())),
                                     'hold_vol_daily_compounded': vol([mm[k] for k in mm if k >= HO_START and k in wm]),
                                     'hold_vol_monthly_file': vol([wm[k] for k in mm if k >= HO_START and k in wm]),
                                     'train_vol_daily_compounded': vol([mm[k] for k in mm if k <= TR_END and k in wm]),
                                     'train_vol_monthly_file': vol([wm[k] for k in mm if k <= TR_END and k in wm]),
                                     'verdict': 'JKP world 日次は湾岸・イスラエルだけが取引する日（日曜・土曜）を含む＝その日の値は世界ではない。X05 は取り下げ'}
    return diag


# ───────────────────────── 第4族（探索・out/mw_calendar_prereg4.json） ─────────────────────────
def by_decade(n, b):
    out = {}
    for lab, a, z in (('1986-1995', 198601, 199512), ('1996-2005', 199601, 200512), ('2006-2015', 200601, 201512), ('2016-', 201601, 209912)):
        st = M.excess_stats(n, b, a=a, z=z)
        out[lab] = compact(st) if st else None
    return out


def in_window(m, start, end):
    return (start <= m <= 12 or 1 <= m <= end) if start > end else (start <= m <= end)


def family4(ctx, CD, cal, tested):
    D, rf, ffm = ctx['D'], ctx['rf'], ctx['ffm']
    Z = 'exploratory4'
    diag = {}
    wm = M.jkp_mkt('world', 'vw'); kw = sorted(wm)
    log('run Z01')
    ev, n, b = eval_excess(kw, wm, lambda ym: 1.5 if hal(ym) else 0.5, 12, 'hal')
    tested.append({'id': 'Z01_HAL_TILT_WORLD', 'family': Z, 'desc': '【事後】JKP world: 11〜4月1.5倍・5〜10月0.5倍（平均1.0倍）', 'kind': 'm_world', 'ev': ev, 'repl_from': 'E01_HAL_TILT'})
    dx_m, dx_rfm = fr_region_monthly('Developed_ex_US_3_Factors')
    kx = sorted(k for k in dx_m if k in dx_rfm)
    log('run Z02')
    ev, n, b = eval_total(kx, dx_m, dx_rfm, lambda ym: 1.5 if hal(ym) else 1.0, 12, 'hal')
    ev['tax_japan'] = None
    tested.append({'id': 'Z02_HAL_OV15_DXUS_FR', 'family': Z, 'desc': 'French Developed_ex_US 月次にハロウィーン1.5倍', 'kind': 'm_dxus', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})
    em = M.jkp_mkt('emerging', 'vw'); ke = sorted(em)
    log('run Z03')
    ev, n, b = eval_excess(ke, em, lambda ym: 1.5 if hal(ym) else 1.0, 12, 'hal', cost=0.003, cost_lo=0.0015)
    tested.append({'id': 'Z03_HAL_OV15_EM', 'family': Z, 'desc': 'JKP emerging 月次にハロウィーン1.5倍（費用0.30%）', 'kind': 'm_em', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})
    dv = M.jkp_mkt('developed', 'vw'); kv = sorted(dv)
    log('run Z04')
    ev, n, b = eval_excess(kv, dv, lambda ym: 1.5 if hal(ym) else 1.0, 12, 'hal')
    tested.append({'id': 'Z04_HAL_OV15_JKPDEV', 'family': Z, 'desc': 'JKP developed 月次にハロウィーン1.5倍', 'kind': 'm_jkpdev', 'ev': ev, 'repl_from': 'P2_HAL_OV15'})

    # D9: 10年ごと
    d9 = {}
    _, n = simulate_ex(kw, wm, lambda ym: 1.5 if hal(ym) else 1.0, COST, SPREAD, 12)
    d9['X06_HAL_OV15_WORLD'] = by_decade(n, wm)
    dev_m, dev_rfm = fr_region_monthly('Developed_3_Factors')
    km = sorted(k for k in dev_m if k in dev_rfm)
    _, n, _, _ = simulate(km, dev_m, dev_rfm, lambda ym: 1.5 if hal(ym) else 1.0, COST, SPREAD, 12)
    d9['Y02_HAL_OV15_DEV'] = by_decade(n, dev_m)
    wx = M.jkp_mkt('world_ex_us', 'vw')
    _, n = simulate_ex(sorted(wx), wx, lambda ym: 1.5 if hal(ym) else 1.0, COST, SPREAD, 12)
    d9['Y03_HAL_OV15_WXUS'] = by_decade(n, wx)
    dxd, dxrf = fr_region_daily('Developed_ex_US_3_Factors_Daily')
    kd = sorted(k for k in dxd if k in dxrf)
    sd = santa_set(kd)
    _, nd, _, _ = simulate(kd, dxd, dxrf, lambda k: 1.5 if k in sd else 1.0, COST, SPREAD, 252)
    d9['Y04_SANTA_OV15_DXUS'] = by_decade(M.to_monthly(nd), M.to_monthly({k: dxd[k] for k in kd}))
    diag['D9_by_decade'] = d9
    # D10: 窓をずらす
    d10 = {}
    for st_ in (10, 11, 12):
        for en in (3, 4, 5):
            _, n = simulate_ex(kw, wm, lambda ym: 1.5 if in_window(ym % 100, st_, en) else 1.0, COST, SPREAD, 12)
            d10[f'{st_:02d}-{en:02d}'] = {'full': compact(M.excess_stats(n, wm)), 'train': compact(M.excess_stats(n, wm, z=TR_END)),
                                         'hold': compact(M.excess_stats(n, wm, a=HO_START))}
    diag['D10_window_surface'] = d10
    # D11: 円建て
    try:
        txt = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=30).decode()
        px = {}
        for line in txt.splitlines()[1:]:
            a = line.split(',')
            if len(a) >= 2 and a[1] not in ('', '.'):
                try:
                    px[int(a[0].replace('-', ''))] = float(a[1])
                except ValueError:
                    pass
        me_ = {}
        for k in sorted(px):
            me_[k // 100] = px[k]  # 月の最後の値
        ms = sorted(me_)
        fx = {b_: me_[b_] / me_[a_] - 1 for a_, b_ in zip(ms, ms[1:])}
        rfm = ffm['rf']
        ks = [k for k in kw if k in fx and k in rfm]
        _, n = simulate_ex(ks, wm, lambda ym: 1.5 if hal(ym) else 1.0, COST, SPREAD, 12)
        sj = {k: (1 + n[k] + rfm[k]) * (1 + fx[k]) - 1 for k in ks}
        bj = {k: (1 + wm[k] + rfm[k]) * (1 + fx[k]) - 1 for k in ks}
        diag['D11_japan_yen'] = {'full': compact(M.excess_stats(sj, bj)), 'train': compact(M.excess_stats(sj, bj, z=TR_END)),
                                 'hold': compact(M.excess_stats(sj, bj, a=HO_START)),
                                 'note': '円建ての総リターンどうし（借入はドルの RF+0.5% の近似）'}
    except Exception as e:  # noqa
        diag['D11_japan_yen'] = {'error': str(e)[:200]}
    return diag


# ───────────────────────── 本体 ─────────────────────────
def run():
    c = load()
    ffd, ffm, me, D = c['ffd'], c['ffm'], c['me'], c['D']
    r, rf = ffd['mkt'], ffd['rf']
    bm_d = M.to_monthly({k: r[k] for k in D})
    rf_dm = M.to_monthly({k: rf[k] for k in D})
    fomc_keys = [dkey(d) for d in c['fomc']]
    cal = daily_rule_sets(D, fomc_keys, us=True)
    Dset = set(D)
    sanity = {
        'mkt_cagr_full_monthly_file': round(M.cagr(ffm['mkt']) * 100, 2),
        'mkt_cagr_2007_monthly_file': round(M.cagr(M.window(ffm['mkt'], HO_START)) * 100, 2),
        'mkt_cagr_full_daily_to_monthly': round(M.cagr(bm_d) * 100, 2),
        'daily_vs_monthly_mean_abs_diff_pct': round(S.mean(abs(bm_d[k] - ffm['mkt'][k]) for k in bm_d if k in ffm['mkt']) * 100, 4),
        'daily_days': len(D), 'daily_from': D[0], 'daily_to': D[-1],
        'fomc_n': len(c['fomc']), 'fomc_bad_headings': c['fomc_bad'][:20],
        'fomc_by_year': {y: sum(1 for d in c['fomc'] if d.year == y) for y in range(1994, 2027)},
        'fomc_not_trading_day': [k for k in fomc_keys if k not in Dset],
        'n_tom_days_per_year': round(len(cal['tom']) / (len(D) / 252), 2),
        'n_ph_days_per_year': round(len(cal['ph']) / (len(D) / 252), 2),
        'n_ph_all_days_per_year': round(len(cal['ph_all']) / (len(D) / 252), 2),
        'ph_excluded_gaps_unscheduled': [(a, w) for a, w, ok in cal['gaps'] if not ok][:80],
        'n_ph_excluded': sum(1 for a, w, ok in cal['gaps'] if not ok),
    }
    # 文献との突き合わせ（日次の平均・%）
    def dm(sel, a=None, z=None):
        xs = [r[k] for k in D if sel(k) and (a is None or k >= a) and (z is None or k <= z)]
        return {'n': len(xs), 'mean_pct': round(S.mean(xs) * 100, 4)} if xs else None
    lit = {
        'TOM_vs_other_1926_2005': [dm(lambda k: k in cal['tom'], z=20051231), dm(lambda k: k not in cal['tom'], z=20051231)],
        'TOM_vs_other_2007_': [dm(lambda k: k in cal['tom'], a=20070101), dm(lambda k: k not in cal['tom'], a=20070101)],
        'PH_vs_other_1963_1982': [dm(lambda k: k in cal['ph'], 19630101, 19821231), dm(lambda k: k not in cal['ph'], 19630101, 19821231)],
        'PH_vs_other_2007_': [dm(lambda k: k in cal['ph'], a=20070101), dm(lambda k: k not in cal['ph'], a=20070101)],
        'FOMC_vs_other_1994_2011': [dm(lambda k: k in cal['fomc'], 19940201, 20111231), dm(lambda k: k not in cal['fomc'], 19940201, 20111231)],
        'FOMC_vs_other_2012_': [dm(lambda k: k in cal['fomc'], a=20120101), dm(lambda k: k not in cal['fomc'], a=20120101)],
        'HAL_monthly_excess_NovApr_vs_MayOct_1926_2006': [round(S.mean(ffm['mktrf'][k] for k in ffm['mktrf'] if hal(k) and k <= TR_END) * 100, 3),
                                                          round(S.mean(ffm['mktrf'][k] for k in ffm['mktrf'] if not hal(k) and k <= TR_END) * 100, 3)],
        'HAL_monthly_excess_NovApr_vs_MayOct_2007_': [round(S.mean(ffm['mktrf'][k] for k in ffm['mktrf'] if hal(k) and k >= HO_START) * 100, 3),
                                                      round(S.mean(ffm['mktrf'][k] for k in ffm['mktrf'] if not hal(k) and k >= HO_START) * 100, 3)],
        'JAN_Lo10_minus_Mkt_Jan_vs_other_1926_2006': [round(S.mean(me['Lo 10'][k] - ffm['mkt'][k] for k in me['Lo 10'] if k % 100 == 1 and k <= TR_END and k in ffm['mkt']) * 100, 3),
                                                      round(S.mean(me['Lo 10'][k] - ffm['mkt'][k] for k in me['Lo 10'] if k % 100 != 1 and k <= TR_END and k in ffm['mkt']) * 100, 3)],
        'JAN_Lo10_minus_Mkt_Jan_vs_other_2007_': [round(S.mean(me['Lo 10'][k] - ffm['mkt'][k] for k in me['Lo 10'] if k % 100 == 1 and k >= HO_START and k in ffm['mkt']) * 100, 3),
                                                  round(S.mean(me['Lo 10'][k] - ffm['mkt'][k] for k in me['Lo 10'] if k % 100 != 1 and k >= HO_START and k in ffm['mkt']) * 100, 3)],
    }
    log('US calendars ready', sanity['n_tom_days_per_year'], sanity['n_ph_days_per_year'], sanity['fomc_n'])

    # 検算: 倍率1で一度も持ち替えない＝相手と一致
    g1, n1, _, _ = simulate(D, r, rf, lambda k: 1.0, COST, SPREAD, 252)
    sanity['identity_L1_maxabs'] = max(abs(M.to_monthly(n1)[k] - bm_d[k]) for k in bm_d)

    CD = country_data()
    log('countries', {k: len(v) for k, v in zip(('m', 'd', 's'), CD[:3])}, CD[3])
    rf_m = ffm['rf']
    tested = []
    for sp in specs():
        sid, fam, desc, kind, rule, tag = sp
        log('run', sid)
        if kind == 'd':
            ks = [k for k in D if k >= 19940201] if tag == 'fomc' else D
            gd, nd, turn, avg = simulate(ks, r, rf, lambda k: rule(k, cal), COST, SPREAD, 252)
            _, nd5, _, _ = simulate(ks, r, rf, lambda k: rule(k, cal), COST_LO, SPREAD, 252)
            _, ndh, _, _ = simulate(ks, r, rf, lambda k: rule(k, cal), COST, SPREAD_HI, 252)
            g, n, n5, nh = M.to_monthly(gd), M.to_monthly(nd), M.to_monthly(nd5), M.to_monthly(ndh)
            b = {k: bm_d[k] for k in g}; rfx = rf_dm
            const = None
            if avg > 1.0001 or 'TILT' in sid:
                _, ndc, _, _ = simulate(ks, r, rf, lambda k: avg, COST, SPREAD, 252)
                const = M.to_monthly(ndc)
            taxw = lambda k: {'m': rule(k, cal)}
            tax = tax_report(ks, {'m': r}, rf, taxw, {'m': COST}, SPREAD, 252, lambda k: k // 10000) if fam == 'primary' else None
        elif kind == 'm':
            ks = sorted(k for k in ffm['mkt'] if k in ffm['rf'])
            g, n, turn, avg = simulate(ks, ffm['mkt'], ffm['rf'], lambda ym: rule(ym, None), COST, SPREAD, 12)
            _, n5, _, _ = simulate(ks, ffm['mkt'], ffm['rf'], lambda ym: rule(ym, None), COST_LO, SPREAD, 12)
            _, nh, _, _ = simulate(ks, ffm['mkt'], ffm['rf'], lambda ym: rule(ym, None), COST, SPREAD_HI, 12)
            b = {k: ffm['mkt'][k] for k in ks}; rfx = ffm['rf']
            const = None
            if avg > 1.0001 or 'TILT' in sid:
                _, const, _, _ = simulate(ks, ffm['mkt'], ffm['rf'], lambda ym: avg, COST, SPREAD, 12)
            tax = tax_report(ks, {'m': ffm['mkt']}, ffm['rf'], lambda ym: {'m': rule(ym, None)}, {'m': COST}, SPREAD, 12, lambda k: k // 100) if fam == 'primary' else None
        elif kind == 'jb':
            ks = sorted(k for k in ffm['mkt'] if k in ffm['rf'])
            jan = {k // 100: ffm['mkt'][k] for k in ks if k % 100 == 1}
            rule_jb = lambda ym: 1.0 if (ym % 100 == 1 or jan.get(ym // 100, 1) > 0) else 0.0
            g, n, turn, avg = simulate(ks, ffm['mkt'], ffm['rf'], rule_jb, COST, SPREAD, 12)
            _, n5, _, _ = simulate(ks, ffm['mkt'], ffm['rf'], rule_jb, COST_LO, SPREAD, 12)
            nh = n
            b = {k: ffm['mkt'][k] for k in ks}; rfx = ffm['rf']; const = None; tax = None
        elif kind == 'rot':
            ks = sorted(k for k in ffm['mkt'] if k in me[rule])
            g, n, turn = rotation(ks, ffm['mkt'], me[rule], lambda ym: ym % 100 == 1, 0.004)
            _, n5, _ = rotation(ks, ffm['mkt'], me[rule], lambda ym: ym % 100 == 1, 0.003)
            _, nh, _ = rotation(ks, ffm['mkt'], me[rule], lambda ym: ym % 100 == 1, 0.011)  # 小型の側1.0%
            avg = 1.0
            b = {k: ffm['mkt'][k] for k in ks}; rfx = ffm['rf']; const = None
            tax = tax_report(ks, {'m': ffm['mkt'], 's': me[rule]}, ffm['rf'], lambda ym: {'s': 1.0} if ym % 100 == 1 else {'m': 1.0},
                             {'m': 0.001, 's': 0.003}, SPREAD, 12, lambda k: k // 100) if fam == 'primary' else None
        ev = evaluate(g, n, b, rfx, POSTPUB.get(tag, []))
        ev['net_hold_cost005'] = M.excess_stats(n5, b, a=HO_START)
        ev['net_hold_spread15_or_smallcost1pct'] = M.excess_stats(nh, b, a=HO_START)
        ev['avg_exposure'] = round(avg, 3)
        ev['turnover_oneway_per_year'] = round(turn, 2)
        if const:
            ev['vs_constant_exposure'] = {'const_L': round(avg, 3), 'full': compact(M.excess_stats(n, const)),
                                          'train': compact(M.excess_stats(n, const, z=TR_END)), 'hold': compact(M.excess_stats(n, const, a=HO_START))}
        ev['tax_japan'] = tax
        # 国別（C5）
        repl = country_eval(sp, CD, fomc_keys, rf_m)
        ev['repl'] = repl
        tested.append({'id': sid, 'family': fam, 'desc': desc, 'kind': kind, 'ev': ev})

    # 第2族（探索）
    ctx = {'D': D, 'r': r, 'rf': rf, 'ffm': ffm, 'fomc_keys': fomc_keys, 'bm_d': bm_d}
    diag = family2(ctx, CD, cal, tested)
    diag.update(family3(ctx, CD, cal, tested))
    diag.update(family4(ctx, CD, cal, tested))
    byid = {t['id']: t for t in tested}
    for t in tested:
        if t.get('repl_from'):
            t['ev']['repl'] = dict(byid[t['repl_from']]['ev']['repl'], note=f"同じ規則＝{t['repl_from']} の国別の数を使う")

    # Holm と判定
    prim = {t['id']: (t['ev']['hold'] or {}).get('p') for t in tested if t['family'] == 'primary'}
    allg = {t['id']: (t['ev']['hold'] or {}).get('p') for t in tested if t['family'] in ('primary', 'exploratory')}
    allg2 = {t['id']: (t['ev']['hold'] or {}).get('p') for t in tested if t['family'] in ('primary', 'exploratory', 'exploratory2')}
    allg3 = {t['id']: (t['ev']['hold'] or {}).get('p') for t in tested if t['family'] in ('primary', 'exploratory', 'exploratory2', 'exploratory3')}
    allg4 = {t['id']: (t['ev']['hold'] or {}).get('p') for t in tested if t['family'] in ('primary', 'exploratory', 'exploratory2', 'exploratory3', 'exploratory4')}
    hp, ha, ha2, ha3, ha4 = M.holm(prim), M.holm(allg), M.holm(allg2), M.holm(allg3), M.holm(allg4)
    for t in tested:
        ev = t['ev']
        fam = t['family']
        hpv = {'primary': hp, 'exploratory': ha, 'exploratory2': ha2, 'exploratory3': ha3, 'exploratory4': ha4}.get(fam, ha4).get(t['id'])
        t['holm_p_all43'] = ha4.get(t['id'])
        t['holm_p_all31'] = ha2.get(t['id'])
        t['holm_p_all39'] = ha3.get(t['id'])
        repl = ev['repl']
        g_, crit = M.grade(ev['full'], ev['train'], ev['hold'], ev['roll20_net'], cost_hold=ev['net_hold'],
                           repl={'regions': repl['regions'], 'positive': repl['positive']} if repl['regions'] else None,
                           family_holm_p=hpv, sharpe_pair={'train': ev['sharpe']['train'], 'hold': ev['sharpe']['hold']},
                           leveraged_or_timing=True)
        t['holm_p'] = hpv
        t['holm_family'] = {'primary': 'primary(9)', 'exploratory': 'all_graded(24)', 'exploratory2': f'all_graded({len(allg2)})',
                            'exploratory3': f'all_graded({len(allg3)})', 'exploratory4': f'all_graded({len(allg4)})'}.get(fam)
        t['grade'] = g_ if fam in ('primary', 'exploratory', 'exploratory2', 'exploratory3', 'exploratory4') else f'（判定しない）{g_}'
        t['criteria'] = crit
        if t['id'] == 'X05_SANTA_OV15_WORLD':
            t['withdrawn'] = ('取り下げ（測った後に見つけたデータの欠陥）: JKP world 日次は湾岸・イスラエルだけが取引する日曜・土曜を含み、'
                              'その日の値は世界の値ではない（日次を積み上げた2007年以降の揺れ 21.1% vs 月次ファイル 16.0%）。'
                              '格付けは記録に残すが勝ちとして数えない。代わりは Y01（French Developed 日次）')
            t['grade'] = f'取り下げ（計算上は {g_}）'
    return {'sanity': sanity, 'literature_check': lit, 'tested': tested, 'holm_primary': hp, 'holm_all_graded': ha,
            'holm_all_graded2': ha2, 'holm_all_graded3': ha3, 'holm_all_graded4': ha4, 'diagnostics': diag}


def shrink(ev):
    out = {}
    for k, v in ev.items():
        if isinstance(v, dict) and 'ex_ann' in v:
            out[k] = compact(v)
        elif k == 'postpub':
            out[k] = {lab: {'gross': compact(x['gross']), 'net': compact(x['net'])} for lab, x in v.items()}
        else:
            out[k] = v
    return out


def main():
    before = {}
    try:
        old = json.load(open(os.path.join(M.BASE, 'out', 'mw_calendar.json')))
        if old.get('gulf_weekend_fix_repl_before'):  # 直す前の数は一度だけ記録（後の実行で上書きしない）
            before = old['gulf_weekend_fix_repl_before']
        for t in ([] if before else old.get('tested', [])):
            if t['id'] in ('P5_PH_SW', 'P6_PH_OV15', 'E07_CALCOMBO_OV15', 'S_PH_ALLGAP_SW', 'S_PH_ALLGAP_OV15') and t.get('repl'):
                before[t['id']] = {'positive': t['repl']['positive'], 'regions': t['repl']['regions'], 'hold_positive': t['repl'].get('hold_positive')}
    except Exception:  # noqa
        pass
    res = run()
    try:
        sha = subprocess.run(['git', 'log', '-1', '--format=%H', '--', f'out/{PREREG}'], cwd=M.BASE, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        sha = None
    tested = []
    for t in res['tested']:
        tested.append({'id': t['id'], 'family': t['family'], 'desc': t['desc'], 'grade': t['grade'], 'criteria': t['criteria'],
                       'holm_p_hold': t['holm_p'], 'holm_family': t['holm_family'], 'holm_p_all31': t.get('holm_p_all31'),
                       'holm_p_all39': t.get('holm_p_all39'), 'holm_p_all43': t.get('holm_p_all43'), 'withdrawn': t.get('withdrawn'), 'repl_from': t.get('repl_from'), **shrink(t['ev'])})
    summary = [{'id': t['id'], 'family': t['family'], 'grade': t['grade'],
                'full_ex': (t['full'] or {}).get('ex_ann'), 'full_t': (t['full'] or {}).get('t'),
                'train_ex': (t['train'] or {}).get('ex_ann'), 'train_t': (t['train'] or {}).get('t'),
                'hold_ex': (t['hold'] or {}).get('ex_ann'), 'hold_t': (t['hold'] or {}).get('t'), 'hold_cagr_diff': (t['hold'] or {}).get('cagr_diff'),
                'net_hold_ex': (t['net_hold'] or {}).get('ex_ann'), 'net_hold_cagr_diff': (t['net_hold'] or {}).get('cagr_diff'),
                'roll20_win': (t['roll20_net'] or {}).get('win_rate'), 'sharpe_train': t['sharpe']['train'], 'sharpe_hold': t['sharpe']['hold'],
                'repl': f"{t['repl']['positive']}/{t['repl']['regions']}", 'avg_exposure': t['avg_exposure']} for t in tested]
    out = {'angle': 'calendar', 'prereg': f'out/{PREREG}', 'prereg_commit': sha, 'global_prereg': 'out/mw_prereg.json',
           'benchmark': 'French Mkt（Mkt-RF + RF・上限なしの時価加重）。日次の規則は同じ日次 Mkt を月次へ直したもの。国別は JKP の国の mkt（超過どうし）',
           'sanity': res['sanity'], 'literature_check': res['literature_check'],
           'prereg2': 'out/mw_calendar_prereg2.json',
           'prereg2_commit': subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_calendar_prereg2.json'], cwd=M.BASE, capture_output=True, text=True).stdout.strip(),
           'prereg3': 'out/mw_calendar_prereg3.json',
           'prereg3_commit': subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_calendar_prereg3.json'], cwd=M.BASE, capture_output=True, text=True).stdout.strip(),
           'holm_primary': res['holm_primary'], 'holm_all_graded': res['holm_all_graded'], 'holm_all_graded2': res['holm_all_graded2'],
           'holm_all_graded3': res['holm_all_graded3'], 'holm_all_graded4': res['holm_all_graded4'],
           'prereg4': 'out/mw_calendar_prereg4.json',
           'prereg4_commit': subprocess.run(['git', 'log', '-1', '--format=%H', '--', 'out/mw_calendar_prereg4.json'], cwd=M.BASE, capture_output=True, text=True).stdout.strip(),
           'diagnostics': res['diagnostics'],
           'gulf_weekend_fix_repl_before': before,
           'deviations': [
               '判定の費用は持ち替え1回0.10%（全体の事前登録の既定）。指示書の0.05%は報告のみ（線を下げない側）',
               '国別（C5）で倍率を掛けた戦略が1か月で−100%以下になった国（bra・per・isr・mex）が第1回の実行で math domain error により黙って分母から落ちていた→第2回から全損＝負けとして分母に残す（格付けは不変）',
               '国別の祝日前の判定が月〜金を平日と決め打ちしていた→日〜木に取引する国で毎週木曜が祝日前になっていた→第3回からその国の平日で数える（直す前の数は gulf_weekend_fix_repl_before）',
               'X05（JKP world 日次のサンタ）は測った後にデータの欠陥が分かり取り下げ（Holm の数には残す）',
               'FOMC の日程で3日以内に並ぶ2つの Meeting（2003年9月15日・16日）は後の日にまとめた（測る前に事前登録へ追記）',
               '感謝祭の窓を 11/20〜11/28 → 11/20〜11/30 に直した（1938年までは最後の木曜。測る前に事前登録へ追記）',
               'mw_common.sharpe は小数3桁に丸める。P2・E11 の保有期間の C8 は 0.651 vs 0.652 の差で不合格（丸めの前でも小さい側）',
           ],
           'summary': summary, 'tested': tested}
    p = M.save('mw_calendar.json', out)
    log('saved', p, os.path.getsize(p))
    for s in summary:
        print(s)


if __name__ == '__main__':
    main()
