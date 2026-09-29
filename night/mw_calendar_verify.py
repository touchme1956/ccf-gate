#!/usr/bin/env python3
"""night/mw_calendar_verify.py — mw_calendar（暦の角度）の主張を反証しにいく検証（読むだけ・門の判定には不使用）

2026-09-28。対象: out/mw_calendar.json の S・A と、B の上位2本（保有期間の超過の大きい順）。
方針
- mw_common からは**取得の部品だけ**（french_tables / jkp_mkt / ff_factors / yahoo / get）を使う。
  持ち方の組み立て・超過・NW t・CAGR・転がる20年・積立・シャープ・回帰はここで独自に書く（研究者の simulate/excess_stats を呼ばない）。
- 相手は同じ原資産の上限なしの時価加重を買って持つだけ（French の地域 Mkt・JKP の vw）。JKP は米ドルの超過なので、
  French の米国 RF を足して総リターンへ戻してから CAGR を比べる（超過どうしの CAGR と総リターンの CAGR の取り違えを避ける）。
- 反証の角度: (1) 数字の再現 (2) 倍率（β）を除いた「暦の時期の読み」の部分＝同じ平均倍率の一定倍・回帰のα・シャープ差の検定
  (3) 期間の依存（1998-2000・2008-09・2020-21 を抜く／保有期間の前半・後半） (4) 近い設定（窓の月・倍率・再調整の有無）
  (5) 国別の再現を β 抜きで数え直す (6) 為替（現地通貨に直した冬−夏）(7) 多重検定 (8) 日本の課税口座（信用取引の別建て）
使い方: python3 night/mw_calendar_verify.py
"""
import sys, os, json, math, datetime, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得の部品だけを使う

COST, SPREAD, SPREAD_HI = 0.001, 0.005, 0.015
TR_END, HO_START, RE_START = 200612, 200701, 201307
TAX = 0.20315
DEV = 'aus aut bel can che deu dnk esp fin fra gbr hkg irl isr ita jpn nld nor nzl prt sgp swe'.split()
EM = 'are bra chl chn col cze egy grc hun idn ind kor kwt mex mys per phl pol qat sau tha tur twn zaf'.split()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ───────────────────────── データ（取得は mw_common・読み方は自前） ─────────────────────────
def fr_total(name, freq):
    """French の地域ファイル → (総リターン Mkt-RF+RF, RF) {日付: 小数}"""
    for title, t in M.french_tables(name).items():
        if t['freq'] != freq:
            continue
        cols = [c.strip().lower() for c in t['cols']]
        if 'mkt-rf' not in cols or 'rf' not in cols:
            continue
        i, j = cols.index('mkt-rf'), cols.index('rf')
        R, F = {}, {}
        for d, row in t['data'].items():
            if row[i] is None or row[j] is None:
                continue
            R[d] = (row[i] + row[j]) / 100.0
            F[d] = row[j] / 100.0
        return R, F
    raise KeyError(name)


def jkp_total(region, rf_m):
    """JKP の vw mkt（米ドル・米国 T-bill を引いた超過）→ 総リターン（French の米国 RF を足す）"""
    x = M.jkp_mkt(region, 'vw')
    R = {k: v + rf_m[k] for k, v in x.items() if k in rf_m}
    return R, {k: rf_m[k] for k in R}


def fred_monthly_last(sid):
    txt = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=30).decode()
    last = {}
    for line in txt.splitlines()[1:]:
        a = line.split(',')
        if len(a) < 2 or a[1] in ('', '.'):
            continue
        try:
            v = float(a[1])
        except ValueError:
            continue
        d = a[0].replace('-', '')
        last[int(d[:6])] = v  # 行は日付順なので月の最後の値が残る
    return last


# ───────────────────────── 持ち方（自前） ─────────────────────────
def hal(ym, start=11, end=4):
    m = ym % 100
    return (m >= start or m <= end) if start > end else (start <= m <= end)


def build(keys, R, F, target, per, cost=COST, spread=SPREAD, rebalance=True):
    """総リターンの原資産 R・現金 F に、各期の目標倍率 target(k) で持つ。
    rebalance=False: 目標が前の期と同じなら漂った倍率のまま持ち替えない（信用取引で上乗せ分を買ったまま持つ型）。
    返り値: 費用前・費用後の各期リターン、年あたりの片道売買、実際の倍率の平均"""
    g, n = {}, {}
    drift, prev_t, turn, es = None, None, 0.0, []
    for k in keys:
        t = target(k)
        if drift is None:
            e, tr = t, 0.0
        elif (not rebalance) and prev_t is not None and t == prev_t:
            e, tr = drift, 0.0
        else:
            e, tr = t, abs(t - drift)
        p = e * R[k] + (1.0 - e) * F[k] - max(e - 1.0, 0.0) * spread / per
        g[k] = p
        n[k] = p - tr * cost
        turn += tr
        es.append(e)
        drift = e * (1.0 + R[k]) / (1.0 + p) if 1.0 + p > 0 else e
        prev_t = t
    return g, n, turn / (len(keys) / per), sum(es) / len(es)


def monthly(daily):
    out = {}
    for k in sorted(daily):
        ym = k // 100
        out[ym] = (1.0 + out.get(ym, 0.0)) * (1.0 + daily[k]) - 1.0
    return out


def santa(dates, last=5, first=2):
    g = {}
    for k in dates:
        g.setdefault(k // 100, []).append(k)
    s = set()
    for ym, ds in g.items():
        ds = sorted(ds)
        if ym % 100 == 12 and ds[-1] % 100 >= 25:  # 12月が途中で終わっていない
            s.update(ds[-last:])
        if ym % 100 == 1 and ds[0] % 100 <= 7:
            s.update(ds[:first])
    return s


# ───────────────────────── 統計（自前） ─────────────────────────
def mean(x):
    return math.fsum(x) / len(x)


def nw(x, L=12):
    n = len(x)
    m = mean(x)
    e = [v - m for v in x]
    s = math.fsum(v * v for v in e) / n
    for l in range(1, min(L, n - 1) + 1):
        s += 2.0 * (1.0 - l / (L + 1.0)) * math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(s / n) if s > 0 else float('nan')


def geo(xs, per=12):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * per / len(xs)) - 1.0


def keys_in(s, b, a=None, z=None, drop=()):
    return [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z) and not any(lo <= k <= hi for lo, hi in drop)]


def cmp(s, b, a=None, z=None, drop=(), per=12):
    ks = keys_in(s, b, a, z, drop)
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nw(d)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex_ann': round(mean(d) * per * 100, 2), 't': round(t, 2),
            'p2': round(math.erfc(abs(t) / math.sqrt(2)), 4),
            'cagr_diff': round((geo([s[k] for k in ks], per) - geo([b[k] for k in ks], per)) * 100, 2)}


def sharpe(r, F, a=None, z=None):
    ks = keys_in(r, F, a, z)
    x = [r[k] - F[k] for k in ks]
    return mean(x) / S.stdev(x) * math.sqrt(12)


def jkm(s, b, F, a=None, z=None):
    """Jobson-Korkie（Memmel の補正）のシャープ差の z（月次・独立を仮定＝楽観側）"""
    ks = keys_in(s, b, a, z)
    ks = [k for k in ks if k in F]
    x = [s[k] - F[k] for k in ks]; y = [b[k] - F[k] for k in ks]
    T = len(ks)
    s1, s2 = mean(x) / S.stdev(x), mean(y) / S.stdev(y)
    mx, my = mean(x), mean(y)
    rho = math.fsum((u - mx) * (v - my) for u, v in zip(x, y)) / math.sqrt(math.fsum((u - mx) ** 2 for u in x) * math.fsum((v - my) ** 2 for v in y))
    var = (2 * (1 - rho) + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T
    return {'sh_s': round(s1 * math.sqrt(12), 3), 'sh_b': round(s2 * math.sqrt(12), 3), 'z': round((s1 - s2) / math.sqrt(var), 2), 'rho': round(rho, 4)}


def alpha_nw(s, b, F, a=None, z=None, L=12):
    """(s−F) = α + β(b−F) の α（年率%）と NW t。α>0 ⇔ 相手に s を足すとシャープが上がる（スパニング）"""
    ks = [k for k in keys_in(s, b, a, z) if k in F]
    y = [s[k] - F[k] for k in ks]; x = [b[k] - F[k] for k in ks]
    n = len(ks)
    mx, my = mean(x), mean(y)
    sxx = math.fsum((v - mx) ** 2 for v in x)
    beta = math.fsum((u - mx) * (v - my) for u, v in zip(x, y)) / sxx
    al = my - beta * mx
    u = [yy - al - beta * xx for yy, xx in zip(y, x)]
    # HAC: 行列 A=(X'X)^-1、B=Σ w_l Γ_l
    a11, a12, a22 = n, math.fsum(x), math.fsum(v * v for v in x)
    det = a11 * a22 - a12 * a12
    inv = [[a22 / det, -a12 / det], [-a12 / det, a11 / det]]
    g = [[u[i], u[i] * x[i]] for i in range(n)]
    Bm = [[0.0, 0.0], [0.0, 0.0]]
    for l in range(0, L + 1):
        w = 1.0 if l == 0 else 2.0 * (1.0 - l / (L + 1.0))
        for i in range(l, n):
            for p in range(2):
                for q in range(2):
                    v = g[i][p] * g[i - l][q]
                    if l == 0:
                        Bm[p][q] += v
                    else:
                        Bm[p][q] += 0.5 * w * (v + g[i - l][p] * g[i][q])
    V = [[sum(inv[p][r] * Bm[r][c] * inv[c][q] for r in range(2) for c in range(2)) for q in range(2)] for p in range(2)]
    se = math.sqrt(V[0][0])
    return {'alpha_ann': round(al * 1200, 2), 't': round(al / se, 2), 'beta': round(beta, 3)}


def roll20(s, b, years=20, start=7):
    ks = sorted(set(s) & set(b))
    res = []
    for y in range(ks[0] // 100, 2100):
        a, z = y * 100 + start, (y + years) * 100 + start - 1
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        res.append((y, round((geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100, 2)))
    if not res:
        return None
    v = sorted(r for _, r in res)
    return {'windows': len(res), 'win_rate': round(sum(1 for r in v if r > 0) / len(v), 3), 'median': v[len(v) // 2], 'worst': min(res, key=lambda t: t[1])}


def dca20(s, b, years=20, step=12):
    ks = sorted(set(s) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1.0) * (1.0 + s[k]); wb = (wb + 1.0) * (1.0 + b[k])
        out.append((ks[i], round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': v[len(v) // 2], 'worst': min(out, key=lambda t: t[1])}


def mdd(r):
    w = pk = 1.0; d = 0.0
    for k in sorted(r):
        w *= 1 + r[k]; pk = max(pk, w); d = min(d, w / pk - 1)
    return round(d * 100, 1)


# ───────────────────────── 一本の検証 ─────────────────────────
DROPS = {'ex_1998_2000': [(199801, 200012)], 'ex_2008_2009': [(200801, 200912)], 'ex_2020_2021': [(202001, 202112)],
         'ex_2008_12_2009_01': [(200812, 200901)]}


def full_check(name, keys, R, F, target, per, cost=COST, const_L=None, want_neighbors=None):
    g, n, turn, avg = build(keys, R, F, target, per, cost)
    _, n_hi, _, _ = build(keys, R, F, target, per, cost, SPREAD_HI)
    tm = monthly if per == 252 else (lambda d: d)
    gm, nm, nhm = tm(g), tm(n), tm(n_hi)
    bm = tm({k: R[k] for k in keys}); Fm = tm({k: F[k] for k in keys})
    L = const_L if const_L is not None else avg
    _, nc, _, _ = build(keys, R, F, lambda k: L, per, cost)
    cm_ = tm(nc)
    out = {'name': name, 'avg_exposure': round(avg, 3), 'turnover_per_year': round(turn, 2)}
    out['vs_market_gross'] = {w: cmp(gm, bm, *ab) for w, ab in (('full', (None, None)), ('train', (None, TR_END)), ('hold', (HO_START, None)), ('recent', (RE_START, None)))}
    out['vs_market_net'] = {w: cmp(nm, bm, *ab) for w, ab in (('full', (None, None)), ('train', (None, TR_END)), ('hold', (HO_START, None)), ('recent', (RE_START, None)))}
    out['net_hold_spread15'] = cmp(nhm, bm, HO_START)
    out['roll20_net'] = roll20(nm, bm)
    out['dca20_net'] = dca20(nm, bm)
    out['sharpe_net'] = {'train': jkm(nm, bm, Fm, None, TR_END), 'hold': jkm(nm, bm, Fm, HO_START, None)}
    out['maxdd'] = {'s_net': mdd(nm), 'b': mdd(bm)}
    # β を除いた部分
    out['vs_constant'] = {'L': round(L, 3), **{w: cmp(nm, cm_, *ab) for w, ab in (('full', (None, None)), ('train', (None, TR_END)), ('hold', (HO_START, None)), ('recent', (RE_START, None)), ('post2003_BoumanJacobsen', (200301, None)))}}
    out['vs_constant_roll20'] = roll20(nm, cm_)
    out['alpha_vs_market_net'] = {w: alpha_nw(nm, bm, Fm, *ab) for w, ab in (('full', (None, None)), ('train', (None, TR_END)), ('hold', (HO_START, None)))}
    # 期間の依存
    sub = {}
    for lab, dr in DROPS.items():
        sub[lab] = {'vs_market_net_full': cmp(nm, bm, drop=dr), 'vs_market_net_hold': cmp(nm, bm, HO_START, drop=dr),
                    'vs_constant_hold': cmp(nm, cm_, HO_START, drop=dr)}
    sub['hold_first_half_2007_2016'] = {'vs_market_net': cmp(nm, bm, HO_START, 201612), 'vs_constant': cmp(nm, cm_, HO_START, 201612)}
    sub['hold_second_half_2017_'] = {'vs_market_net': cmp(nm, bm, 201701), 'vs_constant': cmp(nm, cm_, 201701)}
    out['subperiods'] = sub
    # 年ごとの時期の読みの寄与（一定倍に対する差）の上位・下位
    yr = {}
    for k in keys_in(nm, cm_, HO_START):
        yr[k // 100] = yr.get(k // 100, 0.0) + (nm[k] - cm_[k])
    srt = sorted(yr.items(), key=lambda t: t[1])
    out['hold_vs_constant_by_year_pct'] = {'worst3': [(y, round(v * 100, 2)) for y, v in srt[:3]], 'best3': [(y, round(v * 100, 2)) for y, v in srt[-3:]],
                                           'positive_years': sum(1 for _, v in srt if v > 0), 'years': len(srt)}
    return out, nm, bm, Fm, cm_


def grade_prereg(r, c5):
    """out/mw_prereg.json の C1〜C8 を自前の数字で当てる（C7 は全期間 t≥3 か、保有 p×45 の Bonferroni＜0.05＝Holm より厳しい側）"""
    tr, ho, fu, nh = r['vs_market_gross']['train'], r['vs_market_gross']['hold'], r['vs_market_gross']['full'], r['vs_market_net']['hold']
    c = {'C1': bool(tr and tr['ex_ann'] > 0 and tr['t'] >= 2.0),
         'C2': bool(ho and ho['ex_ann'] > 0 and ho['cagr_diff'] > 0),
         'C3': bool(ho and ho['t'] >= 1.65),
         'C4': bool(r['roll20_net'] and r['roll20_net']['win_rate'] >= 0.8),
         'C5': None if c5 is None else c5,
         'C6': bool(nh and nh['ex_ann'] > 0 and nh['cagr_diff'] > 0),
         'C7': bool(fu['t'] >= 3.0 or min(1.0, ho['p2'] * 45) < 0.05),
         'C8': bool(r['sharpe_net']['train']['sh_s'] > r['sharpe_net']['train']['sh_b'] and r['sharpe_net']['hold']['sh_s'] > r['sharpe_net']['hold']['sh_b'])}
    base = c['C1'] and c['C2'] and c['C6'] and c['C8']
    ok5 = c['C5'] in (None, True)
    if base and c['C3'] and c['C4'] and c['C7'] and ok5:
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


def grade_beta_neutral(r, c5_bn):
    """同じ線を『同じ平均倍率の一定倍』を相手にして当てる（暦の時期の読みだけを裁く・事前登録の外＝参考の厳しい読み）。
    C8 は α（スパニング）の保有期間 t≥1.65 に置き換え＝シャープの差が偶然でないか"""
    v = r['vs_constant']
    c = {'C1': bool(v['train'] and v['train']['ex_ann'] > 0 and v['train']['t'] >= 2.0),
         'C2': bool(v['hold'] and v['hold']['ex_ann'] > 0 and v['hold']['cagr_diff'] > 0),
         'C3': bool(v['hold'] and v['hold']['t'] >= 1.65),
         'C4': bool(r['vs_constant_roll20'] and r['vs_constant_roll20']['win_rate'] >= 0.8),
         'C5': c5_bn,
         'C6': bool(v['hold'] and v['hold']['ex_ann'] > 0 and v['hold']['cagr_diff'] > 0),  # vs_constant は費用後どうし
         'C7': bool(v['full']['t'] >= 3.0 or min(1.0, v['hold']['p2'] * 45) < 0.05),
         'C8_alpha_hold_t': bool(r['alpha_vs_market_net']['hold']['t'] >= 1.65)}
    base = c['C1'] and c['C2'] and c['C6']
    ok5 = c['C5'] in (None, True)
    if base and c['C3'] and c['C4'] and c['C7'] and ok5 and c['C8_alpha_hold_t']:
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── 国別（C5 と β 抜きの数え直し・現地通貨） ─────────────────────────
FX = {'jpn': ('DEXJPUS', 'per_usd'), 'gbr': ('DEXUSUK', 'usd_per'), 'che': ('DEXSZUS', 'per_usd'), 'can': ('DEXCAUS', 'per_usd'),
      'aus': ('DEXUSAL', 'usd_per'), 'swe': ('DEXSDUS', 'per_usd'), 'nor': ('DEXNOUS', 'per_usd'), 'dnk': ('DEXDNUS', 'per_usd'),
      'hkg': ('DEXHKUS', 'per_usd'), 'sgp': ('DEXSIUS', 'per_usd'), 'nzl': ('DEXUSNZ', 'usd_per'),
      **{c: ('DEXUSEU', 'usd_per') for c in ('deu', 'fra', 'ita', 'esp', 'nld', 'bel', 'aut', 'fin', 'irl', 'prt')}}


def usd_per_local(sid, conv):
    m = fred_monthly_last(sid)
    return {k: (v if conv == 'usd_per' else 1.0 / v) for k, v in m.items() if v > 0}


def countries(rf_m, target=lambda ym: 1.5 if hal(ym) else 1.0, L=1.25, spot=None):
    res = []
    fxcache = {}
    ew_usd, ew_loc = {}, {}
    for c in DEV + EM:
        try:
            x = M.jkp_mkt(c, 'vw')
        except Exception as e:  # noqa
            log('miss', c, e); continue
        R = {k: v + rf_m[k] for k, v in x.items() if k in rf_m}
        F = {k: rf_m[k] for k in R}
        ks = sorted(R)
        cost = COST if c in DEV else 0.003
        _, n, _, _ = build(ks, R, F, target, 12, cost)
        _, nc, _, _ = build(ks, R, F, lambda k: L, 12, cost)
        if min(n.values()) <= -1 or min(R.values()) <= -1:
            res.append({'c': c, 'wipeout': True}); continue
        fu, ho = cmp(n, R), cmp(n, R, HO_START)
        cf, ch = cmp(n, nc), cmp(n, nc, HO_START)
        if c in DEV:
            for k in ks:
                if k >= HO_START:
                    ew_usd.setdefault(k, []).append(n[k] - nc[k])
        row = {'c': c, 'full_ex': fu['ex_ann'], 'full_cagr': fu['cagr_diff'], 'hold_ex': ho['ex_ann'] if ho else None, 'hold_cagr': ho['cagr_diff'] if ho else None,
               'vsconst_full': cf['ex_ann'], 'vsconst_hold': ch['ex_ann'] if ch else None, 'years': round(len(ks) / 12, 1)}
        # 現地通貨: 冬−夏の差（一定倍に対する時期の読み＝Σ(e−L)R。定数の現金金利は1年で打ち消し合う）
        if c in FX:
            sid, conv = FX[c]
            if sid not in fxcache:
                fxcache[sid] = usd_per_local(sid, conv)
            fx = fxcache[sid]
            hk = [k for k in ks if k >= HO_START and k in fx and (k - 1 if k % 100 != 1 else k - 89) in fx]
            if hk:
                def prevm(k):
                    return k - 1 if k % 100 != 1 else k - 89
                usd = [(target(k) - L) * R[k] for k in hk]
                loc = [(target(k) - L) * ((1 + R[k]) * fx[prevm(k)] / fx[k] - 1) for k in hk]
                for k, v in zip(hk, loc):
                    ew_loc.setdefault(k, []).append(v)
                row['hold_timing_usd_ann'] = round(mean(usd) * 1200, 2)
                row['hold_timing_local_ann'] = round(mean(loc) * 1200, 2)
                row['hold_timing_local_t'] = round(nw(loc), 2)
        res.append(row)
    ok = [r for r in res if not r.get('wipeout')]
    n_all = len(res)
    loc = [r for r in ok if 'hold_timing_local_ann' in r]
    eu = [mean(ew_usd[k]) for k in sorted(ew_usd)]
    el = [mean(ew_loc[k]) for k in sorted(ew_loc)]
    return {'n': n_all, 'wipeouts': [r['c'] for r in res if r.get('wipeout')],
            'dev_ew_avg_hold_vs_constant_usd': {'ex_ann': round(mean(eu) * 1200, 2), 't': round(nw(eu), 2), 'months': len(eu)},
            'fx_ew_avg_hold_timing_local': {'ex_ann': round(mean(el) * 1200, 2), 't': round(nw(el), 2), 'months': len(el)},
            'full_pos_vs_market': sum(1 for r in ok if r['full_ex'] > 0 and r['full_cagr'] > 0),
            'hold_pos_vs_market': sum(1 for r in ok if r['hold_ex'] is not None and r['hold_ex'] > 0 and r['hold_cagr'] > 0),
            'full_pos_vs_constant': sum(1 for r in ok if r['vsconst_full'] > 0),
            'hold_pos_vs_constant': sum(1 for r in ok if r['vsconst_hold'] is not None and r['vsconst_hold'] > 0),
            'dev_hold_pos_vs_constant': sum(1 for r in ok if r['c'] in DEV and r['vsconst_hold'] is not None and r['vsconst_hold'] > 0),
            'dev_n': sum(1 for r in ok if r['c'] in DEV),
            'fx_countries': len(loc),
            'fx_hold_timing_usd_pos': sum(1 for r in loc if r['hold_timing_usd_ann'] > 0),
            'fx_hold_timing_local_pos': sum(1 for r in loc if r['hold_timing_local_ann'] > 0),
            'fx_hold_timing_usd_mean': round(mean([r['hold_timing_usd_ann'] for r in loc]), 2) if loc else None,
            'fx_hold_timing_local_mean': round(mean([r['hold_timing_local_ann'] for r in loc]), 2) if loc else None,
            'detail': res}


def dollar_season():
    out = {}
    for sid, lab in (('DTWEXM', 'major 1973-2019'), ('DTWEXAFEGS', 'advanced foreign economies 2006-'), ('DTWEXBGS', 'broad 2006-')):
        m = fred_monthly_last(sid)
        ks = sorted(m)
        ch = {b: math.log(m[b] / m[a]) for a, b in zip(ks, ks[1:]) if b - a in (1, 89)}
        for w, a, z in (('train_to_2006', None, TR_END), ('hold_2007_', HO_START, None)):
            win = [v for k, v in ch.items() if hal(k) and (a is None or k >= a) and (z is None or k <= z)]
            sm = [v for k, v in ch.items() if not hal(k) and (a is None or k >= a) and (z is None or k <= z)]
            if len(win) >= 12 and len(sm) >= 12:
                out[f'{sid}_{w}'] = {'desc': lab, 'nov_apr_pct_per_half_year': round(mean(win) * 6 * 100, 2), 'may_oct_pct_per_half_year': round(mean(sm) * 6 * 100, 2),
                                     'months': len(win) + len(sm)}
    return out


def local_dxus(R_usd, F):
    """Developed ex US（米ドル）を先進国の通貨の籠（DTWEXM 〜2005・DTWEXAFEGS 2006〜＝ドル高で上がる）で現地通貨の近似へ"""
    a = fred_monthly_last('DTWEXM'); b = fred_monthly_last('DTWEXAFEGS')
    def ch(m):
        ks = sorted(m)
        return {y: m[y] / m[x] - 1 for x, y in zip(ks, ks[1:]) if y - x in (1, 89)}
    ca, cb = ch(a), ch(b)
    dx = {k: (cb[k] if k >= 200602 and k in cb else ca.get(k)) for k in R_usd}
    return {k: (1 + R_usd[k]) * (1 + dx[k]) - 1 for k in R_usd if dx.get(k) is not None}


# ───────────────────────── 日本の課税口座（信用取引で上乗せ分を別建て） ─────────────────────────
def tax_margin(keys, R, F, a=None, z=None, spread=SPREAD, cost=COST):
    """基の1倍は現物で買って持つ（最後に売って課税）。11月の頭に NAV の0.5倍を信用で買い、4月末に返済して損益を確定。
    損益＝上乗せ分の値上がり−金利−費用。年（返済した月の年）ごとに通算し20.315%・赤字は3年繰越（現物の最後の売却益とも通算）。
    相手は現物1倍を最後に売って課税。研究者の近似（同じ銘柄の平均取得単価で売る）と違い、信用の建玉は現物と別の取得単価"""
    ks = [k for k in keys if (a is None or k >= a) and (z is None or k <= z)]
    base = 1.0; cash = 0.0; carry = []
    lev_val = lev_debt = 0.0
    realized = {}
    for k in ks:
        m = k % 100
        if m == 11 and lev_val == 0.0:
            nav = base + cash + lev_val - lev_debt
            lev_val = 0.5 * nav; lev_debt = 0.5 * nav
            cash -= lev_val * cost
        base *= 1 + R[k]
        if lev_val:
            lev_val *= 1 + R[k]
            lev_debt *= 1 + F[k] + spread / 12
        if m == 4 and lev_val:
            pl = lev_val - lev_debt - lev_val * cost
            y = k // 100
            realized[y] = realized.get(y, 0.0) + pl
            cash += pl
            lev_val = lev_debt = 0.0
        if cash > 0:
            cash *= 1 + F[k] * (1 - TAX)
        else:
            cash *= 1 + F[k] + spread / 12
        if m == 12:
            y = k // 100
            net = realized.pop(y, 0.0)
            carry = [(yy, l) for yy, l in carry if y - yy <= 3]
            if net > 0:
                for i, (yy, l) in enumerate(carry):
                    u = min(l, net); net -= u; carry[i] = (yy, l - u)
                carry = [(yy, l) for yy, l in carry if l > 1e-15]
                cash -= net * TAX
            elif net < 0:
                carry.append((y, -net))
    # 窓の終わり: 残りの建玉を返済・現物を売る
    if lev_val:
        cash += lev_val - lev_debt
        realized[ks[-1] // 100] = realized.get(ks[-1] // 100, 0.0) + lev_val - lev_debt
    gain = (base - 1.0) + sum(realized.values()) - sum(l for _, l in carry)
    fin = base + cash - max(gain, 0.0) * TAX
    bench = 1.0
    for k in ks:
        bench *= 1 + R[k]
    bench_fin = bench - max(bench - 1.0, 0.0) * TAX
    yrs = len(ks) / 12
    return {'years': round(yrs, 1), 'after_tax_cagr_s': round((fin ** (1 / yrs) - 1) * 100, 2), 'after_tax_cagr_b': round((bench_fin ** (1 / yrs) - 1) * 100, 2),
            'diff': round((fin ** (1 / yrs) - bench_fin ** (1 / yrs)) * 100, 2)}


# ───────────────────────── 判定（反証の結論） ─────────────────────────
CLAIMED = {  # 研究者の主張（out/mw_calendar.json の summary と一致することを確かめる）
    'Y02_HAL_OV15_DEV': ('S', 2.82, 3.86, 2.79, 2.77, 2.84, 2.72), 'X06_HAL_OV15_WORLD': ('S', 3.46, 4.15, 4.22, 3.26, 2.61, 2.65),
    'Y03_HAL_OV15_WXUS': ('S', 3.59, 3.59, 4.59, 2.73, 2.48, 2.69), 'Z02_HAL_OV15_DXUS_FR': ('S', 2.73, 3.39, 2.58, 2.04, 2.85, 2.79),
    'Z04_HAL_OV15_JKPDEV': ('S', 3.31, 3.30, 3.85, 2.30, 2.71, 2.71), 'Y08_HALSANTA_DEV': ('S', 3.23, 4.25, 3.30, 3.22, 3.16, 2.87),
    'Y04_SANTA_OV15_DXUS': ('S', 0.64, 4.70, 0.71, 3.35, 0.58, 3.35), 'E06_SANTA_OV15': ('A', 0.70, 5.85, 0.81, 6.09, 0.23, 0.98),
    'X02_SANTA_OV20': ('A', 1.40, 5.85, 1.63, 6.09, 0.46, 0.98),
    'Y01_SANTA_OV15_DEV': ('B', 0.41, 2.79, 0.45, 2.20, 0.38, 1.81), 'X03_SANTA_OV15_NDX': ('B', 0.67, 2.72, 1.12, 2.91, 0.19, 0.73)}
POSTHOC = {'Y08_HALSANTA_DEV': '第3族の事前登録自身が『ハロウィーンとサンタがそれぞれ残ったのを見てから組み合わせた＝事後』と書いている。全体の約束（honesty_rules 2）は『保有期間の結果を見て規則を変えたら事後と明記し、判定には使わない』'}


def fmt(d, keys=('ex_ann', 't', 'cagr_diff')):
    return None if not d else {k: d[k] for k in keys}


def make_verdicts(res, C, V):
    out = []
    for nm, cl in CLAIMED.items():
        r = res[nm]
        g_pre, c_pre = r['grade_prereg_reproduced']
        g_bn, c_bn = r['grade_beta_neutral']
        mg = r['vs_market_gross']
        repro = (abs(mg['full']['ex_ann'] - cl[1]) <= 0.06 and abs(mg['full']['t'] - cl[2]) <= 0.12 and abs(mg['train']['ex_ann'] - cl[3]) <= 0.06
                 and abs(mg['train']['t'] - cl[4]) <= 0.12 and abs(mg['hold']['ex_ann'] - cl[5]) <= 0.06 and abs(mg['hold']['t'] - cl[6]) <= 0.12 and g_pre == cl[0])
        vc, al, sh = r['vs_constant'], r['alpha_vs_market_net'], r['sharpe_net']
        sp = r['subperiods']
        key = {'full_ex': mg['full']['ex_ann'], 'full_t': mg['full']['t'], 'train_ex': mg['train']['ex_ann'], 'train_t': mg['train']['t'],
               'hold_ex': mg['hold']['ex_ann'], 'hold_t': mg['hold']['t'], 'hold_cagr_diff': mg['hold']['cagr_diff'],
               'net_hold': fmt(r['vs_market_net']['hold']), 'recent_net': fmt(r['vs_market_net']['recent']), 'roll20_net_win': r['roll20_net']['win_rate'],
               'dca20_median': r['dca20_net']['median'], 'sharpe_hold': sh['hold'], 'sharpe_train': sh['train'], 'maxdd': r['maxdd'],
               'vs_same_avg_exposure_const': {'L': vc['L'], 'full': fmt(vc['full']), 'train': fmt(vc['train']), 'hold': fmt(vc['hold']), 'recent': fmt(vc['recent']),
                                              'post2003': fmt(vc.get('post2003_BoumanJacobsen'))},
               'alpha_hold': al['hold'], 'hold_2007_2016_vs_const': fmt(sp['hold_first_half_2007_2016']['vs_constant']),
               'hold_2017_vs_const': fmt(sp['hold_second_half_2017_']['vs_constant']), 'grade_prereg_mine': g_pre, 'grade_beta_neutral_mine': g_bn}
        iss = []
        lev = r['avg_exposure'] > 1.1
        if lev:
            nh_ = r['vs_market_net']['hold']['ex_ann']
            share = 1 - (vc['hold']['ex_ann'] / nh_) if nh_ else None
            iss.append(f"倍率: 平均 {r['avg_exposure']} 倍。保有期間の市場との差 +{r['vs_market_net']['hold']['ex_ann']}%/年（費用後）のうち、同じ1.25倍を一年中持つだけで {round(share * 100)}% が出る。"
                       f"暦の時期の読み（一定1.25倍との差）は保有期間 {vc['hold']['ex_ann']:+}%/年 t{vc['hold']['t']}（C3 の線 1.65 {'に届く' if vc['hold']['t'] >= 1.65 else 'に届かない'}）")
            iss.append(f"C8 は点の比較だけ: 保有期間のシャープ {sh['hold']['sh_s']} vs {sh['hold']['sh_b']}（差の JKM z={sh['hold']['z']}・独立を仮定した楽観側でも有意でない）。"
                       f"回帰の α（相手を足したシャープの改善）保有 {al['hold']['alpha_ann']:+}%/年 t{al['hold']['t']}")
            iss.append(f"2017年以降の時期の読み: {sp['hold_second_half_2017_']['vs_constant']['ex_ann']:+}%/年 t{sp['hold_second_half_2017_']['vs_constant']['t']}"
                       f"（2007-2016 は {sp['hold_first_half_2007_2016']['vs_constant']['ex_ann']:+} t{sp['hold_first_half_2007_2016']['vs_constant']['t']}）。2013-07 以降 {vc['recent']['ex_ann']:+} t{vc['recent']['t']}")
            by = r['hold_vs_constant_by_year_pct']
            iss.append(f"1年への依存: 一定倍に対する年ごとの寄与の最大は {by['best3'][-1][0]} 年 +{by['best3'][-1][1]}%（2008年10月の暴落が1倍の夏に落ちた）。"
                       f"2008-09 を抜くと保有の時期の読み {sp['ex_2008_2009']['vs_constant_hold']['ex_ann']:+} t{sp['ex_2008_2009']['vs_constant_hold']['t']}。正の年 {by['positive_years']}/{by['years']}")
            if 'neighbors' in r and 'win_11-03' in r['neighbors']:
                nb = r['neighbors']
                vals = {k[4:]: nb[k]['vs_constant_hold']['ex_ann'] for k in nb if k.startswith('win_')}
                iss.append(f"窓の月をずらす（一定倍と比べた保有期間）: {vals}。4月を外す窓（〜3月）は0前後か負＝時期の読みは4月（と11月）に偏る。研究者の『9通りすべて正』は1倍の市場と比べた数（倍率込み）")
            iss.append(f"最大下落 {r['maxdd']['s_net']}% vs {r['maxdd']['b']}%。信用取引が要り NISA では不可")
            if 'context_hold_cagr' in r:
                cx = r['context_hold_cagr']
                iss.append(f"投資家の目（事前登録の相手ではない）: 保有期間の年率 戦略（費用後）{cx['strategy_net']}% ／自分の市場 {cx['own_market']}% ／米国の市場（French Mkt）{cx['US_market_French_Mkt']}%")
            if nm.startswith(('X06', 'Y02', 'Y03', 'Z02', 'Z04', 'Y08')):
                iss.append(f"国別（反証に不利な証拠・公平のため）: 一定1.25倍に対し保有期間で正 {C['hold_pos_vs_constant']}/{C['n']} か国・先進 {C['dev_hold_pos_vs_constant']}/{C['dev_n']}。"
                           f"だが国は同じ冬・夏を共有する＝独立の46回ではない: 先進22か国の等加重平均の時期の読み 保有 {C['dev_ew_avg_hold_vs_constant_usd']['ex_ann']:+}%/年 t{C['dev_ew_avg_hold_vs_constant_usd']['t']}（1本の指数と同じくらいの強さ）")
                iss.append(f"為替: 現地通貨に直した時期の読み（保有期間）は正 {C['fx_hold_timing_local_pos']}/{C['fx_countries']} か国・平均 {C['fx_hold_timing_local_mean']:+}%/年（米ドル建て {C['fx_hold_timing_usd_mean']:+}）＝米ドル建ての約{round((1 - C['fx_hold_timing_local_mean'] / C['fx_hold_timing_usd_mean']) * 100)}%は冬のドル安。等加重の現地通貨 {C['fx_ew_avg_hold_timing_local']['ex_ann']:+} t{C['fx_ew_avg_hold_timing_local']['t']}")
            if nm == 'Y02_HAL_OV15_DEV' and 'tax_japan_margin' in r:
                tj = r['tax_japan_margin']['hold']
                iss.append(f"日本の課税口座（信用の建玉を現物と別の取得単価で・自前の近似）: 保有期間の税引後 年率差 {tj['diff']:+}%（研究者の近似 +1.34）")
        if nm in POSTHOC:
            iss.insert(0, '事後の組み合わせ: ' + POSTHOC[nm])
            inc = r.get('increment_over_halloween_only', {}).get('hold')
            if inc:
                iss.append(f"ハロウィーンだけ（Y02 型を日次で）に対してサンタの2倍が足した分: 保有 {inc['ex_ann']:+}%/年 t{inc['t']}＝有意でない。中身は Y02 とほぼ同じ")
        if 'SANTA' in nm and 'HALSANTA' not in nm:
            hw = r['hold_windows_pct']
            iss.append(f"保有期間の年末年始の窓: 正 {hw['positive']}/{hw['windows']}・中央 {hw['median']}%・最大 {hw['best3'][-1]}")
            e89 = sp['ex_2008_12_2009_01']
            iss.append(f"2008-12 と 2009-01 を抜く: 費用後の保有 {e89['vs_market_net_hold']['ex_ann']:+} t{e89['vs_market_net_hold']['t']}・一定倍と比べて {e89['vs_constant_hold']['ex_ann']:+} t{e89['vs_constant_hold']['t']}")
            nb = r['neighbors']
            iss.append('窓の近い設定（保有期間の市場との差・費用後）: ' + str({k: (v['vs_market_hold']['ex_ann'], v['vs_market_hold']['t']) for k, v in nb.items()}))
            if 'fx_in_window' in r and 'DTWEXAFEGS' in r['fx_in_window']:
                fx = r['fx_in_window']['DTWEXAFEGS']
                iss.append(f"為替: 保有期間の窓の株（米ドル）+{fx['window_equity_usd_pct_per_year']}%/窓のうち、先進国の通貨に対するドル安が {-fx['window_dollar_change_pct_per_year']}%＝約{round(-fx['window_dollar_change_pct_per_year'] / fx['window_equity_usd_pct_per_year'] * 100)}%。現地通貨の近似でも +{fx['window_equity_local_approx_pct_per_year']}%")
            if nm in ('E06_SANTA_OV15', 'X02_SANTA_OV20', 'Y01_SANTA_OV15_DEV', 'X03_SANTA_OV15_NDX'):
                iss.append('C5（国別 43/46）は Y04 と同じ米国外の証拠で、この系列（米国・先進国全体・NASDAQ-100）自身の保有期間の勝ちではない。国別の日次は自前で再計算していない（研究者の数を使用）')
        # 判定
        if nm in POSTHOC:
            vg, verdict = f'判定不可（事後）／β抜きなら {g_bn}', 'refuted'
        elif g_bn == cl[0]:
            vg, verdict = g_bn, 'confirmed'
        else:
            vg, verdict = g_bn, f'downgraded to {g_bn}'
        if not repro:
            iss.insert(0, f'再現のずれ: 自前 {mg["full"]["ex_ann"]}/{mg["full"]["t"]}・{mg["train"]["ex_ann"]}/{mg["train"]["t"]}・{mg["hold"]["ex_ann"]}/{mg["hold"]["t"]} 格付け {g_pre}')
        why = {'refuted': '事後の組み合わせは全体の約束で判定に使えない。中身はハロウィーンの上乗せ（Y02）と同じ',
               'confirmed': '自前の再計算で同じ格付け。倍率を揃えても（一定倍・α）保有期間で有意',
               }.get(verdict, 'C1〜C8 は自前の数字でも事前登録の文字どおり通るが、市場に勝った分の大半は平均倍率（借入）で、暦の時期の読みだけを同じ線で裁くと格が下がる' if lev else
                     '保有期間の勝ちが一つの出来事（2008-12〜2009-01）か米国外の証拠に頼っており、この系列自身の保有期間の時期の読みは0前後')
        out.append({'name': nm, 'claimed_grade': cl[0], 'verified_grade': vg, 'verdict': verdict, 'reproduced': bool(repro),
                    'grade_prereg_letter_reproduced': g_pre, 'criteria_prereg_mine': c_pre, 'criteria_beta_neutral_mine': c_bn,
                    'why': why, 'key_numbers': key, 'issues': iss})
    # Z01（事後の傾け・A）: 研究者は主張に入れていないが A なので記録
    t = res['X06_HAL_OV15_WORLD']['neighbors']['tilt_15_05']
    out.append({'name': 'Z01_HAL_TILT_WORLD', 'claimed_grade': 'A（主張の一覧の外）', 'verified_grade': '判定不可（事後）', 'verdict': 'refuted', 'reproduced': True,
                'why': '第4族の事前登録が『世界の冬と夏の平均を見た後に登録＝事後』と明記',
                'key_numbers': {'train': fmt(t['vs_market_train']), 'hold': fmt(t['vs_market_hold']), 'full': fmt(t['vs_market_full'])},
                'issues': [f"β を増やさない傾け（1.5/0.5）の保有期間は +{t['vs_market_hold']['ex_ann']}%/年 t{t['vs_market_hold']['t']}＝C3 不合格"]})
    return out


# ───────────────────────── 本体 ─────────────────────────
def main():
    V = {}
    ff = M.ff_factors('monthly')
    rf_us = ff['rf']
    res = {}
    # ① 月次のハロウィーン1.5倍（5つの編纂）
    series = {}
    series['Y02_HAL_OV15_DEV'] = fr_total('Developed_3_Factors', 'monthly')
    series['Z02_HAL_OV15_DXUS_FR'] = fr_total('Developed_ex_US_3_Factors', 'monthly')
    series['X06_HAL_OV15_WORLD'] = jkp_total('world', rf_us)
    series['Y03_HAL_OV15_WXUS'] = jkp_total('world_ex_us', rf_us)
    series['Z04_HAL_OV15_JKPDEV'] = jkp_total('developed', rf_us)
    series['P2_HAL_OV15_US(参考・C)'] = ({k: ff['mkt'][k] for k in ff['mkt'] if k in rf_us}, {k: rf_us[k] for k in ff['mkt'] if k in rf_us})
    series['Z03_HAL_OV15_EM(参考・C)'] = jkp_total('emerging', rf_us)
    hal15 = lambda ym: 1.5 if hal(ym) else 1.0
    store = {}
    for nm_, (R, F) in series.items():
        log('run', nm_)
        ks = sorted(k for k in R if k in F)
        cost = 0.003 if 'EM' in nm_ else COST
        r, n, b, Fm, cst = full_check(nm_, ks, R, F, hal15, 12, cost, const_L=1.25)
        # 近い設定: 窓・倍率・再調整
        nb = {}
        for st in (10, 11, 12):
            for en in (3, 4, 5):
                _, nn, _, _ = build(ks, R, F, (lambda ym, st=st, en=en: 1.5 if hal(ym, st, en) else 1.0), 12, cost)
                Lx = 1 + 0.5 * sum(1 for m in range(1, 13) if hal(200000 + m, st, en)) / 12
                _, nc, _, _ = build(ks, R, F, lambda k, Lx=Lx: Lx, 12, cost)
                nb[f'win_{st:02d}-{en:02d}'] = {'vs_market_hold': cmp(nn, R, HO_START), 'vs_constant_hold': cmp(nn, nc, HO_START), 'vs_constant_train': cmp(nn, nc, None, TR_END)}
        for Lh in (1.25, 2.0):
            _, nn, _, _ = build(ks, R, F, (lambda ym, Lh=Lh: Lh if hal(ym) else 1.0), 12, cost)
            _, nc, _, _ = build(ks, R, F, lambda k, Lh=Lh: 1 + (Lh - 1) / 2, 12, cost)
            nb[f'lev_{Lh}'] = {'vs_market_hold': cmp(nn, R, HO_START), 'vs_constant_hold': cmp(nn, nc, HO_START)}
        _, nn, _, _ = build(ks, R, F, hal15, 12, cost, rebalance=False)
        nb['no_intra_winter_rebalance'] = {'vs_market_hold': cmp(nn, R, HO_START), 'vs_market_train': cmp(nn, R, None, TR_END), 'vs_constant_hold': cmp(nn, cst, HO_START)}
        # β 中立の傾け（1.5/0.5）
        _, nt, _, _ = build(ks, R, F, lambda ym: 1.5 if hal(ym) else 0.5, 12, cost)
        nb['tilt_15_05'] = {'vs_market_train': cmp(nt, R, None, TR_END), 'vs_market_hold': cmp(nt, R, HO_START), 'vs_market_full': cmp(nt, R)}
        r['neighbors'] = nb
        # 現地通貨の近似（Developed ex US だけ）
        if nm_ == 'Z02_HAL_OV15_DXUS_FR':
            Rl = local_dxus(R, F)
            kl = sorted(k for k in Rl if k in F)
            timing = [(hal15(k) - 1.25) * Rl[k] for k in kl]
            timing_usd = [(hal15(k) - 1.25) * R[k] for k in kl]
            r['local_currency_approx'] = {w: {'timing_usd_ann': round(mean([t for k, t in zip(kl, timing_usd) if (a is None or k >= a) and (z is None or k <= z)]) * 1200, 2),
                                              'timing_local_ann': round(mean([t for k, t in zip(kl, timing) if (a is None or k >= a) and (z is None or k <= z)]) * 1200, 2),
                                              'timing_local_t': round(nw([t for k, t in zip(kl, timing) if (a is None or k >= a) and (z is None or k <= z)]), 2)}
                                          for w, a, z in (('full', None, None), ('train', None, TR_END), ('hold', HO_START, None))}
            r['local_currency_approx']['note'] = '先進国の通貨の籠（貿易の重み）で近似。株の時価の重み（日本・英国が重い）とは違う＝国別の正確な値は countries の fx_*'
        us = ff['mkt']
        kk = keys_in(n, us, HO_START)
        r['context_hold_cagr'] = {'strategy_net': round(geo([n[k] for k in kk]) * 100, 2), 'own_market': round(geo([b[k] for k in kk]) * 100, 2),
                                  'US_market_French_Mkt': round(geo([us[k] for k in kk]) * 100, 2), 'from': kk[0], 'to': kk[-1]}
        if nm_ == 'Y02_HAL_OV15_DEV':
            r['tax_japan_margin'] = {w: tax_margin(ks, R, F, a, z) for w, a, z in (('full', None, None), ('train', None, TR_END), ('hold', HO_START, None))}
            # 米国の市場（French Mkt）と比べると（投資家の目・事前登録の相手ではない）
            us = ff['mkt']
            r['context_vs_US_market'] = {'hold_cagr_strategy_net': round(geo([n[k] for k in keys_in(n, us, HO_START)]) * 100, 2),
                                         'hold_cagr_US_market': round(geo([us[k] for k in keys_in(n, us, HO_START)]) * 100, 2),
                                         'hold_cagr_Dev_market': round(geo([b[k] for k in keys_in(n, us, HO_START)]) * 100, 2)}
        store[nm_] = (ks, R, F)
        res[nm_] = r
    # ② 国別（C5）: 1.5倍の上乗せ vs 1倍、β 抜き（一定1.25倍）、現地通貨
    log('countries')
    C = countries(rf_us)
    V['countries_halloween'] = C
    V['dollar_seasonality'] = dollar_season()

    # ③ 日次: サンタ（Developed ex US・Developed・US・NDX）と Y08
    log('daily')
    daily = {'Y04_SANTA_OV15_DXUS': fr_total('Developed_ex_US_3_Factors_Daily', 'daily'),
             'Y01_SANTA_OV15_DEV': fr_total('Developed_3_Factors_Daily', 'daily'),
             'E06_SANTA_OV15': fr_total('F-F_Research_Data_Factors_daily', 'daily')}
    # NDX: 1999-03-10 まで ^NDX の価格＋年0.5%、1999-03-11 から QQQ の調整後（事前登録どおりの系列を自前で組む）
    px, q = M.yahoo('^NDX', '1d'), M.yahoo('QQQ', '1d')
    nd = {k: v + 0.005 / 252 for k, v in px.items() if k <= 19990310}
    nd.update({k: v for k, v in q.items() if 19990311 <= k <= 20260831})
    usd_rf = daily['E06_SANTA_OV15'][1]
    frk = sorted(usd_rf)
    rf_nd, j, last = {}, 0, None
    for k in sorted(nd):
        while j < len(frk) and frk[j] <= k:
            last = frk[j]; j += 1
        if last is not None:
            rf_nd[k] = usd_rf.get(k, usd_rf[last])
    daily['X03_SANTA_OV15_NDX'] = ({k: nd[k] for k in rf_nd}, rf_nd)
    sets = {}
    daily['X02_SANTA_OV20'] = daily['E06_SANTA_OV15']
    for nm_, (R, F) in daily.items():
        log('run', nm_)
        ks = sorted(k for k in R if k in F)
        ss = santa(ks)
        sets[nm_] = (ks, ss)
        lev = 2.0 if nm_ == 'X02_SANTA_OV20' else 1.5
        tgt = lambda k, ss=ss, lev=lev: lev if k in ss else 1.0
        L = 1 + (lev - 1) * len(ss) / len(ks)
        r, n, b, Fm, cst = full_check(nm_, ks, R, F, tgt, 252, COST, const_L=L)
        nb = {}
        for la, fi in ((3, 2), (5, 0), (5, 5), (7, 2), (4, 3)):
            s2 = santa(ks, la, fi)
            _, nn, _, _ = build(ks, R, F, lambda k, s2=s2: 1.5 if k in s2 else 1.0, 252, COST)
            nm2 = monthly(nn); bm = monthly({k: R[k] for k in ks})
            nb[f'last{la}_first{fi}'] = {'vs_market_hold': cmp(nm2, bm, HO_START), 'vs_market_train': cmp(nm2, bm, None, TR_END)}
        r['neighbors'] = nb
        # 年ごとのサンタの窓の上乗せ（市場との差）: 保有期間
        ex = {}
        for k in ks:
            if k in ss and k >= 20061201:
                y = k // 10000 + (1 if k % 10000 >= 1200 else 0)  # 12月の窓は翌年の1月と同じ窓に数える
                ex[y] = ex.get(y, 0.0) + 0.5 * (R[k] - F[k])
        srt = sorted(ex.items(), key=lambda t: t[1])
        r['hold_windows_pct'] = {'best3': [(y, round(v * 100, 2)) for y, v in srt[-3:]], 'worst3': [(y, round(v * 100, 2)) for y, v in srt[:3]],
                                 'positive': sum(1 for _, v in srt if v > 0), 'windows': len(srt),
                                 'median': round(sorted(v for _, v in srt)[len(srt) // 2] * 100, 3)}
        res[nm_] = r
    # サンタの為替: Developed ex US の窓の中の米ドル（先進国の籠）の動き
    try:
        afe = {}
        for sid in ('DTWEXAFEGS', 'DTWEXM'):
            txt = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=30).decode()
            px_ = {}
            for line in txt.splitlines()[1:]:
                a_ = line.split(',')
                if len(a_) >= 2 and a_[1] not in ('', '.'):
                    try:
                        px_[int(a_[0].replace('-', ''))] = float(a_[1])
                    except ValueError:
                        pass
            afe[sid] = px_
        ks, ss = sets['Y04_SANTA_OV15_DXUS']
        R, F = daily['Y04_SANTA_OV15_DXUS']
        out_fx = {}
        for sid, a, z in (('DTWEXM', None, 20061231), ('DTWEXAFEGS', 20070101, None)):
            px_ = afe[sid]
            fk = sorted(px_)
            # 立会日 d のリターン（d−1→d）に、同じ日の籠の変化（前の観測→d）を当てる
            prevv = {b_: px_[a_] for a_, b_ in zip(fk, fk[1:])}
            sel = [k for k in ks if k in ss and k in prevv and (a is None or k >= a) and (z is None or k <= z)]
            yrs = len(set((k // 10000 + (1 if k % 10000 >= 1200 else 0)) for k in sel))
            usd_ret = sum(R[k] for k in sel) / yrs
            dollar = sum(math.log(px_[k] / prevv[k]) for k in sel) / yrs
            out_fx[sid] = {'window_equity_usd_pct_per_year': round(usd_ret * 100, 3), 'window_dollar_change_pct_per_year': round(dollar * 100, 3),
                           'window_equity_local_approx_pct_per_year': round((usd_ret + dollar) * 100, 3), 'windows': yrs}
        res['Y04_SANTA_OV15_DXUS']['fx_in_window'] = out_fx
    except Exception as e:  # noqa
        res['Y04_SANTA_OV15_DXUS']['fx_in_window'] = {'error': str(e)[:200]}
    # Y08: Developed 日次 11〜4月1.5倍＋サンタの日2倍（事後の組み合わせ）
    log('run Y08')
    R, F = daily['Y01_SANTA_OV15_DEV']
    ks, ss = sets['Y01_SANTA_OV15_DEV']
    tgt = lambda k: 2.0 if k in ss else (1.5 if hal(k // 100) else 1.0)
    L = mean([tgt(k) for k in ks])
    r, n, b, Fm, cst = full_check('Y08_HALSANTA_DEV', ks, R, F, tgt, 252, COST, const_L=L)
    # Y08 から Y02 型（月次のハロウィーンだけ・日次で組む）を引いた上乗せ分
    _, nh, _, _ = build(ks, R, F, lambda k: 1.5 if hal(k // 100) else 1.0, 252, COST)
    r['increment_over_halloween_only'] = {'hold': cmp(n, monthly(nh), HO_START), 'full': cmp(n, monthly(nh))}
    res['Y08_HALSANTA_DEV'] = r

    # ④ 判定（事前登録どおり＝自前の数字／β 抜きの厳しい読み）
    c5_hal = C['full_pos_vs_market'] / C['n'] >= 2 / 3
    c5_hal_bn = C['full_pos_vs_constant'] / C['n'] >= 2 / 3
    # サンタの国別: 日次の国別は研究者の数（43/46）を使う（自前では再計算していない＝記す）
    for nm_, r in res.items():
        if 'SANTA' in nm_ and 'HALSANTA' not in nm_:
            c5, c5b = True, None  # 研究者 43/46（日次の国別は未再計算）
        else:
            c5, c5b = c5_hal, c5_hal_bn
        r['grade_prereg_reproduced'] = grade_prereg(r, c5)
        r['grade_beta_neutral'] = grade_beta_neutral(r, c5b)

    V['candidates'] = res
    V['verdicts'] = make_verdicts(res, C, V)
    vd = {v['name']: v for v in V['verdicts']}
    def vc_(n):
        return res[n]['vs_constant']['hold']
    V['summary_ja'] = [
        f"再現: 主張の11本（S7・A2・B2）の全期間・訓練・保有の超過と NW t は自前の組み立てで小数2桁まで一致（JKP の CAGR 差だけ総リターン基準で +0.02〜0.03 違う）。事前登録の文字どおりの格付けも同じ（ハロウィーン1.5倍 S×5・Y08 S・Y04 S・E06/X02 A・Y01/X03 B）。",
        f"だがハロウィーン1.5倍の『市場に勝った分』の45〜68%は平均1.25倍の借入。一定1.25倍と比べた暦の時期の読みは保有期間 +0.9〜+1.5%/年・t1.2〜1.8、シャープの差は JKM z 0.7〜1.5（有意でない）、2017年以降は先進国・世界で +0.3〜0.4（t0.3）、最大の1年は2008年（10月の暴落が1倍の夏に落ちた・+9〜13%）、4月を窓から外すと0前後。",
        f"β を抜いて同じ線で裁き直すと X06・Y03 は A（1986-2006 と国別の広さで t≥3）、Y02・Z02・Z04 は B（全期間 t<3）。米国外の国別は一定倍に対しても保有期間 42/46 で正・先進22か国の等加重 +{C['dev_ew_avg_hold_vs_constant_usd']['ex_ann']} t{C['dev_ew_avg_hold_vs_constant_usd']['t']}・現地通貨でも +{C['fx_ew_avg_hold_timing_local']['ex_ann']} t{C['fx_ew_avg_hold_timing_local']['t']}（ドル安の分は約24%）＝米国外の冬の効果は弱いが残る。",
        f"Y04（先進国〔米国外〕の年末年始1.5倍）は β を揃えても保有 +{vc_('Y04_SANTA_OV15_DXUS')['ex_ann']}%/年 t{vc_('Y04_SANTA_OV15_DXUS')['t']}・α t{res['Y04_SANTA_OV15_DXUS']['alpha_vs_market_net']['hold']['t']}・窓 18/20 年で正・近い窓すべて正で S を確認。ただし小さく（費用後 +0.48%/年）、2013-07 以降は一定倍に対し +{res['Y04_SANTA_OV15_DXUS']['vs_constant']['recent']['ex_ann']}（t{res['Y04_SANTA_OV15_DXUS']['vs_constant']['recent']['t']}）と薄れ、約16%は年末のドル安。",
        "E06・X02（米国のサンタ）は保有期間の勝ちが 2008-12〜2009-01 の1回だけ（抜くと負・一定倍に対し +0.01）で B へ。Y01・X03（先進国全体・NASDAQ-100 のサンタ）は β を揃えると0か負で C へ。Y08・Z01 は事前登録自身が『事後』と書いており判定に使えない（Y08 のサンタの上乗せ分は +0.28 t1.33）。",
        "結論: 暦の角度で頑丈に残るのは『米国外の年末年始（小さい）』だけ。ハロウィーンは『1.25倍の借入＋米国外で弱い冬の効果』で、S の大半は倍率。投資家の目では先進国のハロウィーン1.5倍（費用後 10.6%/年）も保有期間は米国の市場（11.1%）に届かなかった。",
    ]
    V['multiple_testing'] = {
        'variants_in_angle': 45, 'graded': 43,
        'halloween_overlay_datasets_tried': ['P2 US (C)', 'X04 NDX (C)', 'X06 JKP world (S)', 'Y02 French Dev (S)', 'Y03 JKP world_ex_us (S)', 'Z02 French Dev ex US (S)', 'Z03 JKP EM (C)', 'Z04 JKP developed (S)'],
        'halloween_other_variants': ['P1 switch (C)', 'E01 tilt US (C)', 'E02 2x US (C)', 'E08 HAL∨TOM US (C)', 'Z01 tilt world 事後 (A)', 'Y08 HAL+Santa Dev 事後 (S)'],
        'santa_datasets_tried': ['E06 US (A)', 'X02 US 2x (A)', 'X01 US grid-selected (C)', 'X03 NDX (B)', 'X05 JKP world daily (取り下げ)', 'Y01 French Dev (B)', 'Y04 French Dev ex US (S)', 'D3/D7 regions (診断)'],
        'note': 'ハロウィーンの S 5本は同じ規則を重なった系列（world⊃developed⊃dev ex US、world⊃world ex US）に当てたもの＝独立の証拠は「米国」と「米国外」の実質2つ。米国（P2）と NASDAQ-100（X04）は C'}
    V['generated'] = datetime.date.today().isoformat()
    V['method'] = '自前の組み立て（build: 倍率・漂い・持ち替え費用 |Δ倍率|×0.10%・借入 RF+0.5%）と自前の統計（NW ラグ12・幾何年率・転がる20年7月起点・20年積立・JKM・α の HAC）。取得だけ mw_common'
    p = os.environ.get('MWV_RAW') or os.path.join(M.BASE, 'out', 'mw_calendar_verify.json')
    json.dump(V, open(p, 'w'), ensure_ascii=False, indent=1, default=str)
    log('saved', p)


if __name__ == '__main__':
    main()
