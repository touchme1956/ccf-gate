#!/usr/bin/env python3
"""night/mw_jp_nisa_bridge_verify.py — 角度 jp_nisa_bridge の『反証の検証』（読むだけ・門の判定には不使用）

対象: night/mw_jp_nisa_bridge.py → out/mw_jp_nisa_bridge.json が S/A と主張した候補（X2_VM）と B の上位（P1_VQ・B はこれ1本だけ）。
この道具は mw_common の**取得部品だけ**（get / french_tables / jkp_rows）を使い、為替の月末化・ポートフォリオの組み立て・
円への換算・超過・NW t・CAGR・転がる窓・積立・Holm・格付けの線は**すべて自前**で書き直した。

調べること
 1. 数字の再現（全期間・訓練・保有の超過と NW t・CAGR の差・転がる20年・積立20年・費用後の保有期間）
 2. 後知恵: 良い側の決め方（研究側の『訓練期間だけで決めた側』は JKP の符号の約束をなぞるだけか）、保有期間の結果が既知だったか
 3. 相手（純粋な時価加重か）、超過と総リターンの混同、通貨
 4. 区間の依存（1998-2000 を抜く・2020-2021 を抜く・保有期間の前半/後半・2022 より前だけ）
 5. 変数の脆さ（n の下限・勢いの窓・割安の物差し・大型株だけの隣の定義・French の 6/32 分割・脚の単独）
 6. 多重検定（角度の全本数での Holm・プログラム全体の Bonferroni の線 t 4.35・mw_japan との重複）
 7. 実行の現実（費用の損益分岐・回転の2倍×0.30%・器が無いこと）
 8. 他地域の再現を保有期間だけで（C5 は全期間で測られている）
 9. 投資家の文脈（S&P500 円・今の ETF 側に対してどうか）
出力: out/mw_jp_nisa_bridge_verify.json
"""
import json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得部品だけ）

OUT = os.path.join(M.BASE, 'out', 'mw_jp_nisa_bridge_verify.json')
RES = json.load(open(os.path.join(M.BASE, 'out', 'mw_jp_nisa_bridge.json')))
TRAIN_END, HOLD = 200612, 200701
PROGRAM_BONF_T = 4.35
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


# ═════════════════════════ 自前の統計 ═════════════════════════
def nwt(x, L=12):
    n = len(x)
    if n < 24:
        return None
    m = math.fsum(x) / n
    e = [v - m for v in x]
    s = math.fsum(v * v for v in e) / n
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(s / n) if s > 0 else None


def p2(t):
    return None if t is None else math.erfc(abs(t) / math.sqrt(2))


def geo(xs):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def mons(s, b, a=None, z=None, drop=None):
    return [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z)
            and not (drop and any(d0 <= k <= d1 for d0, d1 in drop))]


def ex(s, b, a=None, z=None, drop=None):
    ks = mons(s, b, a, z, drop)
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nwt(d)
    mu = math.fsum(d) / len(d)
    sd = math.sqrt(math.fsum((v - mu) ** 2 for v in d) / (len(d) - 1))
    gs, gb = geo([s[k] for k in ks]), geo([b[k] for k in ks])
    return {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / 12, 2), 'ex': round(mu * 1200, 2),
            't': round(t, 2) if t is not None else None, 'p': round(p2(t), 5) if t is not None else None,
            'cagr_s': round(gs * 100, 2), 'cagr_b': round(gb * 100, 2), 'cagr_diff': round((gs - gb) * 100, 2),
            'te': round(sd * math.sqrt(12) * 100, 2)}


def short(e):
    if not e:
        return None
    return f"{e['from']}〜{e['to']} {e['ex']:+.2f}%/年 t{e['t']} CAGR差{e['cagr_diff']:+.2f}"


def roll(s, b, years=20, start_month=7):
    ks = mons(s, b)
    ss = set(ks)
    out = []
    for y in range(ks[0] // 100, ks[-1] // 100 + 1):
        w, yy, mm = [], y, start_month
        for _ in range(years * 12):
            w.append(yy * 100 + mm)
            mm += 1
            if mm == 13:
                yy, mm = yy + 1, 1
        if w[-1] > ks[-1] or w[0] < ks[0]:
            continue
        have = [k for k in w if k in ss]
        if len(have) < 0.97 * len(w):
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in have) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in have) / years) - 1
        out.append((y, round((gs - gb) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'windows': len(out), 'wins': sum(1 for c in v if c > 0), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3),
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1]),
            'start_years': [y for y, _ in out]}


def dca(s, b, years=20, step=12):
    ks = mons(s, b)
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1) * (1 + s[k])
            wb = (wb + 1) * (1 + b[k])
        out.append((ks[i], round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def holm(ps):
    it = sorted((p, k) for k, p in ps.items() if p is not None)
    m, run, out = len(it), 0.0, {}
    for i, (p, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = round(run, 5)
    return out


def cost(s, turnover, unit):
    c = turnover * unit / 12
    return {k: v - c for k, v in s.items()}


def breakeven_unit(s, b, turnover, a=HOLD):
    """保有期間の CAGR 差がちょうど 0 になる『片道売買100%あたりの費用』（%）"""
    lo, hi = 0.0, 0.2
    e = ex(cost(s, turnover, hi), b, a=a)
    if e and e['cagr_diff'] > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        e = ex(cost(s, turnover, mid), b, a=a)
        if e and e['cagr_diff'] > 0:
            lo = mid
        else:
            hi = mid
    return round(lo * 100, 3)


def my_grade(full, train, hold, r20, costh, repl_pos=None, repl_n=None, holm_p=None):
    """out/mw_prereg.json の C1〜C7 を自前で（訓練期間は最低15年）"""
    c = {}
    c['C1'] = bool(train and train['years'] >= 15 and train['ex'] > 0 and (train['t'] or 0) >= 2.0)
    c['C2'] = bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0)
    c['C3'] = bool(hold and (hold['t'] or 0) >= 1.65)
    c['C4'] = bool(r20 and r20['win_rate'] >= 0.8)
    c['C5'] = None if not repl_n else (repl_pos / repl_n >= 2 / 3)
    c['C6'] = bool(costh and costh['ex'] > 0 and costh['cagr_diff'] > 0)
    c['C7'] = bool((full and (full['t'] or 0) >= 3.0) or (holm_p is not None and holm_p < 0.05))
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] is not False:
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ═════════════════════════ データ（取得は mw_common、読み解きは自前） ═════════════════════════
def fx_monthend():
    """FRED DEXJPUS（円/米ドル・日次）→ 月の最後の有効な値。欠測（'.'）は飛ばす"""
    txt = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=30).decode()
    last = {}
    for line in txt.strip().splitlines()[1:]:
        d, _, v = line.partition(',')
        try:
            x = float(v)
        except ValueError:
            continue
        k = int(d[:4]) * 100 + int(d[5:7])
        day = int(d[8:10])
        if k not in last or day >= last[k][0]:
            last[k] = (day, x)
    return {k: v for k, (_, v) in last.items()}


FX = fx_monthend()


def prev(m):
    return m - 89 if m % 100 == 1 else m - 1


def yen(r_usd):
    return {m: (1 + v) * FX[m] / FX[prev(m)] - 1 for m, v in r_usd.items() if m in FX and prev(m) in FX}


def fr_table(name, want='Average Value Weighted Returns -- Monthly'):
    for t, v in M.french_tables(name).items():
        if t.startswith(want) and v['freq'] == 'monthly':
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def fr_nfirms(name):
    for t, v in M.french_tables(name).items():
        if t.startswith('Number of Firms') and v['freq'] == 'monthly':
            return {c: {d: row[i] for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def fr_region_mkt(region):
    """{地域}_3_Factors の Mkt-RF＋RF（米ドルの総リターン）"""
    for t, v in M.french_tables(f'{region}_3_Factors').items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols'] and 'RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(region)


def us_rf_mkt():
    for t, v in M.french_tables('F-F_Research_Data_Factors').items():
        if v['freq'] == 'monthly':
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            rf = {d: row[j] / 100 for d, row in v['data'].items() if row[j] is not None}
            mk = {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
            return rf, mk
    raise KeyError('ff')


RF_US, MKT_US = us_rf_mkt()


def ym(d):
    return int(d[:4]) * 100 + int(d[5:7])


_JP = {}


def jkp_pf(loc, w='vw'):
    """JKP all_factors 三分位 → {特性: {pf: {ym: (ret超過・米ドル, n)}}}"""
    k = (loc, w)
    if k not in _JP:
        d = {}
        for x in M.jkp_rows(loc, 'all_factors', 'portfolios', w):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            n = int(float(x['n'])) if x['n'] not in ('', 'NA', 'na') else 0
            d.setdefault(x['name'], {}).setdefault(x['pf'], {})[ym(x['date'])] = (float(x['ret']), n)
        _JP[k] = d
    return _JP[k]


def jkp_mkt_ex(loc, w='vw'):
    return {ym(x['date']): float(x['ret']) for x in M.jkp_rows(loc, 'mkt', 'factor', w) if x['ret'] not in ('', 'NA', 'na')}


def blend(legs, w=None):
    ks = set(legs[0])
    for l in legs[1:]:
        ks &= set(l)
    w = w or [1 / len(legs)] * len(legs)
    return {k: math.fsum(wi * l[k] for wi, l in zip(w, legs)) for k in sorted(ks)}


def jkp_leg(pf, name, side='3.0', nmin=30):
    d = (pf.get(name) or {}).get(side) or {}
    return {m: r for m, (r, n) in d.items() if n >= nmin}


def usd_total(ex_):
    return {m: v + RF_US[m] for m, v in ex_.items() if m in RF_US}


def stats_block(s, b, turnover):
    return {
        'full': ex(s, b), 'train': ex(s, b, z=TRAIN_END), 'hold': ex(s, b, a=HOLD),
        'recent_2013_07': ex(s, b, a=201307), 'fresh_2023_04': ex(s, b, a=202304),
        'cost_hold_010': ex(cost(s, turnover, 0.001), b, a=HOLD),
        'cost_hold_2x_030': ex(cost(s, 2 * turnover, 0.003), b, a=HOLD),
        'breakeven_cost_per_unit_pct': breakeven_unit(s, b, turnover),
        'roll20': roll(s, b, 20), 'dca20': dca(s, b, 20), 'dca20_monthly_step': dca(s, b, 20, step=1),
    }


def stress_block(s, b, end):
    h1_end = 201606 if end >= 202512 else 201610
    return {
        'hold_first_half': ex(s, b, a=HOLD, z=h1_end), 'hold_second_half': ex(s, b, a=h1_end + (89 if h1_end % 100 == 12 else 1)),
        'hold_2007_2021': ex(s, b, a=HOLD, z=202112), 'hold_2007_2019': ex(s, b, a=HOLD, z=201912),
        'hold_2013_2021': ex(s, b, a=201301, z=202112), 'hold_2022_on': ex(s, b, a=202201),
        'full_drop_1998_2000': ex(s, b, drop=[(199801, 200012)]), 'train_drop_1998_2000': ex(s, b, z=TRAIN_END, drop=[(199801, 200012)]),
        'full_drop_2020_2021': ex(s, b, drop=[(202001, 202112)]), 'hold_drop_2020_2021': ex(s, b, a=HOLD, drop=[(202001, 202112)]),
        'hold_10y_windows': ten_year_windows(s, b),
    }


def ten_year_windows(s, b):
    ks = mons(s, b, a=HOLD)
    out = []
    for y in range(2007, 2030):
        a, z = y * 100 + 1, (y + 9) * 100 + 12
        if z > ks[-1]:
            break
        e = ex(s, b, a=a, z=z)
        out.append((y, e['ex'], e['t']))
    return {'n': len(out), 'positive': sum(1 for _, x, _ in out if x > 0), 'detail': out}


def yearly_excess(s, b, a=HOLD):
    """暦年ごとの幾何の超過（%・袖の年リターン − 相手の年リターン）"""
    yrs = {}
    for k in mons(s, b, a):
        y = k // 100
        yrs.setdefault(y, [1.0, 1.0])
        yrs[y][0] *= 1 + s[k]
        yrs[y][1] *= 1 + b[k]
    return {y: round((u - w) * 100, 1) for y, (u, w) in yrs.items()}


def log_share(s, b, a, z, part_a, part_z):
    """保有期間の対数の超過のうち part の区間が占める割合"""
    ks = mons(s, b, a, z)
    tot = math.fsum(math.log1p(s[k]) - math.log1p(b[k]) for k in ks)
    part = math.fsum(math.log1p(s[k]) - math.log1p(b[k]) for k in ks if part_a <= k <= part_z)
    return round(part / tot, 3) if tot else None


# ═════════════════════════ X2_VM（JKP 日本 vw・割安＋勢い・円） ═════════════════════════
def verify_x2vm():
    log('== X2_VM ==')
    pf = jkp_pf('jpn', 'vw')
    mk_ex = jkp_mkt_ex('jpn', 'vw')
    bench_yen = yen(usd_total(mk_ex))

    def build(value='be_me', mom='ret_12_1', nmin=30, w=None, pfx=None):
        p = pfx or pf
        s_ex = blend([jkp_leg(p, value, '3.0', nmin), jkp_leg(p, mom, '3.0', nmin)], w)
        return s_ex

    s_ex = build()
    s_yen = yen(usd_total(s_ex))
    rec = {'construction': '0.5×be_me 第3分位＋0.5×ret_12_1 第3分位（JKP jpn all_factors vw・各脚 n≥30・両脚がそろう月だけ）→ 超過＋French RF（米国）→ 円（DEXJPUS 月末）',
           'benchmark': 'JKP jpn mkt vw（上限なし）→ 同じく円'}
    rec.update(stats_block(s_yen, bench_yen, 1.2))
    rec['stress'] = stress_block(s_yen, bench_yen, 202512)
    rec['stress']['share_of_hold_log_excess_2022_2025'] = log_share(s_yen, bench_yen, HOLD, 202512, 202201, 202512)
    rec['stress']['train_1988_1996'] = ex(s_yen, bench_yen, z=199612)
    rec['stress']['train_1997_2006'] = ex(s_yen, bench_yen, a=199701, z=TRAIN_END)
    rec['stress']['train_drop_1990_1992'] = ex(s_yen, bench_yen, z=TRAIN_END, drop=[(199001, 199212)])
    rec['stress']['full_from_1993'] = ex(s_yen, bench_yen, a=199301)
    rec['stress']['yearly_excess_hold_pct'] = yearly_excess(s_yen, bench_yen)
    rec['usd'] = {'full': ex(usd_total(s_ex), usd_total(mk_ex)), 'hold': ex(usd_total(s_ex), usd_total(mk_ex), a=HOLD),
                  'hold_2007_2021': ex(usd_total(s_ex), usd_total(mk_ex), a=HOLD, z=202112),
                  'note': '米ドル版（mw_japan の E4_value_mom と同じ規則）'}
    # 脚の単独（どちらの脚が効いているか）
    legs = {}
    for nm in ('be_me', 'ret_12_1'):
        l = yen(usd_total(jkp_leg(pf, nm, '3.0', 30)))
        legs[nm] = {'train': ex(l, bench_yen, z=TRAIN_END), 'hold': ex(l, bench_yen, a=HOLD), 'hold_2007_2021': ex(l, bench_yen, a=HOLD, z=202112)}
    rec['legs_alone'] = legs
    lv, lm = yen(usd_total(jkp_leg(pf, 'be_me', '3.0', 30))), yen(usd_total(jkp_leg(pf, 'ret_12_1', '3.0', 30)))
    ks = [k for k in sorted(set(lv) & set(lm) & set(bench_yen))]
    av, am = [lv[k] - bench_yen[k] for k in ks], [lm[k] - bench_yen[k] for k in ks]
    mv, mm = math.fsum(av) / len(av), math.fsum(am) / len(am)
    rec['corr_active_value_mom'] = round(math.fsum((x - mv) * (y - mm) for x, y in zip(av, am)) /
                                         math.sqrt(math.fsum((x - mv) ** 2 for x in av) * math.fsum((y - mm) ** 2 for y in am)), 3)
    # 良い側の検算: 研究側の『訓練期間だけで決めた側』は JKP の符号つき因子との相関＝符号の約束をなぞるだけ。成績で見た側を自前で
    side = {}
    for nm in ('be_me', 'ret_12_1'):
        p3, p1 = jkp_leg(pf, nm, '3.0', 0), jkp_leg(pf, nm, '1.0', 0)
        ks = [k for k in sorted(set(p3) & set(p1)) if k <= TRAIN_END]
        d = [p3[k] - p1[k] for k in ks]
        side[nm] = {'train_months': len(ks), 'mean_p3_minus_p1_ann': round(math.fsum(d) / len(d) * 1200, 2), 't': round(nwt(d), 2)}
    rec['side_by_train_performance'] = side
    # 隣の定義
    nb = {}
    variants = {
        'n>=10': dict(nmin=10), 'n>=50': dict(nmin=50), 'n>=100': dict(nmin=100),
        'mom=ret_6_1': dict(mom='ret_6_1'), 'mom=ret_9_1': dict(mom='ret_9_1'), 'mom=ret_12_7': dict(mom='ret_12_7'),
        'value=bev_mev': dict(value='bev_mev'), 'value=ni_me': dict(value='ni_me'), 'value=ocf_me': dict(value='ocf_me'),
        'value=sale_me': dict(value='sale_me'), 'weights_value2/3': dict(w=[2 / 3, 1 / 3]), 'weights_mom2/3': dict(w=[1 / 3, 2 / 3]),
    }
    for k, kw in variants.items():
        sv = yen(usd_total(build(**kw)))
        nb[k] = {'train': short(ex(sv, bench_yen, z=TRAIN_END)), 'hold': short(ex(sv, bench_yen, a=HOLD)),
                 'hold_2007_2021': short(ex(sv, bench_yen, a=HOLD, z=202112)), 'full_t': (ex(sv, bench_yen) or {}).get('t')}
    # vw_cap で組んだ袖（相手は純粋な vw のまま）
    try:
        pfc = jkp_pf('jpn', 'vw_cap')
        sv = yen(usd_total(build(pfx=pfc)))
        nb['sleeve_vw_cap_vs_pure_vw'] = {'train': short(ex(sv, bench_yen, z=TRAIN_END)), 'hold': short(ex(sv, bench_yen, a=HOLD)),
                                          'hold_2007_2021': short(ex(sv, bench_yen, a=HOLD, z=202112)), 'full_t': (ex(sv, bench_yen) or {}).get('t')}
    except Exception as e:  # noqa
        nb['sleeve_vw_cap_vs_pure_vw'] = f'取得失敗 {str(e)[:120]}'
    # 大型株だけの隣（French Japan: 6分割＝時価の上位90% の BIG・25分割の ME5）
    jp_mkt_yen = yen(fr_region_mkt('Japan'))
    f6b, f6p = fr_table('Japan_6_Portfolios_ME_BE-ME'), fr_table('Japan_6_Portfolios_ME_Prior_12_2')
    f25b, f25p = fr_table('Japan_25_Portfolios_ME_BE-ME'), fr_table('Japan_25_Portfolios_ME_Prior_12_2')
    for k, (a_, b_) in {'French6_BIG_HiBM+BIG_HiPRIOR': (f6b['BIG HiBM'], f6p['BIG HiPRIOR']),
                        'French25_BIG_HiBM+BIG_HiPRIOR（研究側 P1_VM）': (f25b['BIG HiBM'], f25p['BIG HiPRIOR'])}.items():
        sv = yen(blend([a_, b_]))
        nb[k] = {'train': short(ex(sv, jp_mkt_yen, z=TRAIN_END)), 'hold': short(ex(sv, jp_mkt_yen, a=HOLD)),
                 'hold_2007_2021': short(ex(sv, jp_mkt_yen, a=HOLD, z=202112)), 'full_t': (ex(sv, jp_mkt_yen) or {}).get('t'),
                 'benchmark': 'French Japan Mkt（円）'}
    rec['neighbors'] = nb
    # 他国（JKP 先進21か国・n≥10）: 全期間（研究側の C5）と保有期間だけ
    repl = {}
    for c in ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe']:
        try:
            pc = jkp_pf(c, 'vw')
            mc = jkp_mkt_ex(c, 'vw')
        except Exception as e:  # noqa
            repl[c] = f'取得失敗 {str(e)[:80]}'
            continue
        sc = blend([jkp_leg(pc, 'be_me', '3.0', 10), jkp_leg(pc, 'ret_12_1', '3.0', 10)])
        if len(mons(sc, mc)) < 120:
            continue
        f, h, h21 = ex(sc, mc), ex(sc, mc, a=HOLD), ex(sc, mc, a=HOLD, z=202112)
        repl[c] = {'full_ex': f['ex'], 'full_t': f['t'], 'hold_ex': h['ex'] if h else None, 'hold_t': h['t'] if h else None,
                   'hold_2007_2021_ex': h21['ex'] if h21 else None}
    ok = {k: v for k, v in repl.items() if isinstance(v, dict)}
    rec['replication_jkp21'] = {
        'regions': len(ok), 'full_positive': sum(1 for v in ok.values() if v['full_ex'] > 0),
        'hold_positive': sum(1 for v in ok.values() if (v['hold_ex'] or 0) > 0),
        'hold_t_ge_1_65': sum(1 for v in ok.values() if (v['hold_t'] or 0) >= 1.65),
        'hold_2007_2021_positive': sum(1 for v in ok.values() if (v['hold_2007_2021_ex'] or 0) > 0), 'detail': repl}
    # 文脈: S&P500（French の米国 Mkt・円）に対して
    sp_yen = yen(MKT_US)
    rec['context_vs_US_market_yen'] = {'full': ex(s_yen, sp_yen, a=198802, z=202512), 'hold': ex(s_yen, sp_yen, a=HOLD, z=202512),
                                       'note': '投資家の比べる相手（S&P500≈French の米国 Mkt）に対しては日本の割安＋勢いの袖は大きく負ける'}
    # 格付け（自前・登録どおり）
    fam = {'X2_VM': rec['hold']['p']}
    for t in RES['tested']:
        if t['family'] == 'X2' and t['id'] != 'X2_VM':
            fam[t['id']] = (t.get('hold') or {}).get('p')
    hf = holm(fam)
    rec['family_holm_p_reproduced'] = hf.get('X2_VM')
    repl_pos, repl_n = rec['replication_jkp21']['full_positive'], rec['replication_jkp21']['regions']
    g, c = my_grade(rec['full'], rec['train'], rec['hold'], rec['roll20'], rec['cost_hold_010'], repl_pos, repl_n, hf.get('X2_VM'))
    rec['grade_reproduced'], rec['criteria_reproduced'] = g, c
    # ストレスの格
    st = {}
    h21 = rec['stress']['hold_2007_2021']
    st['hold_cut_2021_12'] = my_grade(rec['full'], rec['train'], h21, rec['roll20'], ex(cost(s_yen, 1.2, 0.001), bench_yen, a=HOLD, z=202112),
                                      repl_pos, repl_n, None)[0]
    st['hold_cut_2021_12_and_C5_on_2007_2021'] = my_grade(rec['full'], rec['train'], h21, rec['roll20'],
                                                          ex(cost(s_yen, 1.2, 0.001), bench_yen, a=HOLD, z=202112),
                                                          rec['replication_jkp21']['hold_2007_2021_positive'], repl_n, None)[0]
    st['drop_1998_2000'] = my_grade(rec['stress']['full_drop_1998_2000'], rec['stress']['train_drop_1998_2000'], rec['hold'], rec['roll20'],
                                    rec['cost_hold_010'], repl_pos, repl_n, hf.get('X2_VM'))[0]
    st['cost_2x_030'] = my_grade(rec['full'], rec['train'], rec['hold'], rec['roll20'], rec['cost_hold_2x_030'], repl_pos, repl_n, hf.get('X2_VM'))[0]
    st['C5_on_holdout_only'] = my_grade(rec['full'], rec['train'], rec['hold'], rec['roll20'], rec['cost_hold_010'],
                                        rec['replication_jkp21']['hold_positive'], repl_n, hf.get('X2_VM'))[0]
    rec['stress_grades'] = st
    rec['_series'] = (s_yen, bench_yen)
    log('  再現', short(rec['full']), '|', short(rec['train']), '|', short(rec['hold']), '| roll', rec['roll20']['win_rate'], '| dca', rec['dca20']['median'])
    log('  2007-2021', short(h21), '| 2022〜', short(rec['stress']['hold_2022_on']), '| share', rec['stress']['share_of_hold_log_excess_2022_2025'])
    log('  stress grades', st)
    return rec


# ═════════════════════════ P1_VQ（French Japan 大型の割安＋質・円） ═════════════════════════
def fr_rule(region, legs_cols, files):
    return blend([fr_table(f'{region}_{f}')[c] for f, c in zip(files, legs_cols)])


def verify_p1vq():
    log('== P1_VQ ==')
    B25, O25 = 'Japan_25_Portfolios_ME_BE-ME', 'Japan_25_Portfolios_ME_OP'
    hibm, hiop = fr_table(B25)['BIG HiBM'], fr_table(O25)['BIG HiOP']
    s_usd = blend([hibm, hiop])
    s_yen = yen(s_usd)
    mkt_usd = fr_region_mkt('Japan')
    b_yen = yen(mkt_usd)
    rec = {'construction': '0.5×BIG HiBM（25分割 ME×BE/ME）＋0.5×BIG HiOP（25分割 ME×OP）・Value Weight・毎月半々 → 円（DEXJPUS）',
           'benchmark': 'French Japan Mkt（Mkt-RF＋RF・米ドル）→ 円'}
    rec.update(stats_block(s_yen, b_yen, 0.45))
    rec['stress'] = stress_block(s_yen, b_yen, 202608)
    rec['stress']['share_of_hold_log_excess_2022_2026'] = log_share(s_yen, b_yen, HOLD, 202608, 202201, 202608)
    rec['stress']['yearly_excess_hold_pct'] = yearly_excess(s_yen, b_yen)
    rec['stress']['cost_hold_2007_2021_010'] = ex(cost(s_yen, 0.45, 0.001), b_yen, a=HOLD, z=202112)
    rec['usd'] = {'full': ex(s_usd, mkt_usd), 'hold': ex(s_usd, mkt_usd, a=HOLD)}
    nf_b, nf_o = fr_nfirms(B25)['BIG HiBM'], fr_nfirms(O25)['BIG HiOP']
    rec['n_firms'] = {'BIG_HiBM': {'min': min(nf_b.values()), 'min_month': min(nf_b, key=nf_b.get), 'hold_min': min(v for k, v in nf_b.items() if k >= HOLD),
                                   'hold_median': sorted(v for k, v in nf_b.items() if k >= HOLD)[len([1 for k in nf_b if k >= HOLD]) // 2]},
                      'BIG_HiOP': {'min': min(nf_o.values()), 'hold_min': min(v for k, v in nf_o.items() if k >= HOLD)}}
    # 脚の単独と隣の定義
    f6b, f6o = fr_table('Japan_6_Portfolios_ME_BE-ME'), fr_table('Japan_6_Portfolios_ME_OP')
    f32 = fr_table('Japan_32_Portfolios_ME_BE-ME_OP_2x4x4')
    f25b, f25o = fr_table(B25), fr_table(O25)
    nbs = {
        'BIG_HiBM_alone': hibm, 'BIG_HiOP_alone': hiop,
        'French6_BIG_HiBM+BIG_HiOP（上位90%・三分位）': blend([f6b['BIG HiBM'], f6o['BIG HiOP']]),
        'French32_BIG_HiBM_HiOP（割安かつ質の角・1つ）': f32['BIG HiBM HiOP'],
        'ME4+ME5（BM5・OP5 の4脚等分）': blend([f25b['ME4 BM5'], f25b['BIG HiBM'], f25o['ME4 OP5'], f25o['BIG HiOP']]),
        'ME5 BM4+OP4（一段内側）': blend([f25b['ME5 BM4'], f25o['ME5 OP4']]),
        'ME5 (BM4+BM5)+(OP4+OP5)': blend([f25b['ME5 BM4'], f25b['BIG HiBM'], f25o['ME5 OP4'], f25o['BIG HiOP']]),
        'weights_value2/3': blend([hibm, hiop], [2 / 3, 1 / 3]), 'weights_quality2/3': blend([hibm, hiop], [1 / 3, 2 / 3]),
    }
    nb = {}
    for k, sv_usd in nbs.items():
        sv = yen(sv_usd)
        f, tr, h = ex(sv, b_yen), ex(sv, b_yen, z=TRAIN_END), ex(sv, b_yen, a=HOLD)
        nb[k] = {'train': short(tr), 'hold': short(h), 'hold_2007_2021': short(ex(sv, b_yen, a=HOLD, z=202112)), 'full_t': f['t'] if f else None,
                 'grade_simple': my_grade(f, tr, h, roll(sv, b_yen), ex(cost(sv, 0.45, 0.001), b_yen, a=HOLD), None, None, None)[0]}
    rec['neighbors'] = nb
    # 他地域（研究側の C5 は全期間）: 保有期間だけでも
    repl = {}
    for reg in ('Europe', 'Asia_Pacific_ex_Japan', 'North_America'):
        sr = blend([fr_table(f'{reg}_25_Portfolios_ME_BE-ME')['BIG HiBM'], fr_table(f'{reg}_25_Portfolios_ME_OP')['BIG HiOP']])
        mr = fr_region_mkt(reg)
        repl[reg] = {'full': short(ex(sr, mr)), 'hold': short(ex(sr, mr, a=HOLD)), 'hold_2007_2021': short(ex(sr, mr, a=HOLD, z=202112)),
                     'counted_in_C5': reg != 'North_America', '_full_ex': ex(sr, mr)['ex'], '_hold_ex': ex(sr, mr, a=HOLD)['ex']}
    rec['replication'] = repl
    counted = [v for v in repl.values() if v['counted_in_C5']]
    repl_pos, repl_n = sum(1 for v in counted if v['_full_ex'] > 0), len(counted)
    # 族の Holm（P1 の3本・研究側の他2本の p を使う）
    fam = {'P1_VQ': rec['hold']['p']}
    for t in RES['tested']:
        if t['family'] == 'P1' and t['id'] != 'P1_VQ':
            fam[t['id']] = (t.get('hold') or {}).get('p')
    hf = holm(fam)
    rec['family_holm_p_reproduced'] = hf.get('P1_VQ')
    g, c = my_grade(rec['full'], rec['train'], rec['hold'], rec['roll20'], rec['cost_hold_010'], repl_pos, repl_n, hf.get('P1_VQ'))
    rec['grade_reproduced'], rec['criteria_reproduced'] = g, c
    st = {}
    h21 = rec['stress']['hold_2007_2021']
    st['hold_cut_2021_12'] = my_grade(rec['full'], rec['train'], h21, rec['roll20'], ex(cost(s_yen, 0.45, 0.001), b_yen, a=HOLD, z=202112),
                                      repl_pos, repl_n, None)[0]
    st['hold_second_half_only'] = my_grade(rec['full'], rec['train'], rec['stress']['hold_second_half'], rec['roll20'],
                                           ex(cost(s_yen, 0.45, 0.001), b_yen, a=rec['stress']['hold_second_half']['from']), repl_pos, repl_n, None)[0]
    st['drop_1998_2000'] = my_grade(rec['stress']['full_drop_1998_2000'], rec['stress']['train_drop_1998_2000'], rec['hold'], rec['roll20'],
                                    rec['cost_hold_010'], repl_pos, repl_n, hf.get('P1_VQ'))[0]
    st['cost_2x_030'] = my_grade(rec['full'], rec['train'], rec['hold'], rec['roll20'], rec['cost_hold_2x_030'], repl_pos, repl_n, hf.get('P1_VQ'))[0]
    st['usd'] = my_grade(rec['usd']['full'], ex(s_usd, mkt_usd, z=TRAIN_END), rec['usd']['hold'], roll(s_usd, mkt_usd),
                         ex(cost(s_usd, 0.45, 0.001), mkt_usd, a=HOLD), repl_pos, repl_n, None)[0]
    rec['stress_grades'] = st
    sp_yen = yen(MKT_US)
    rec['context_vs_US_market_yen'] = {'full': ex(s_yen, sp_yen, a=199007), 'hold': ex(s_yen, sp_yen, a=HOLD)}
    log('  再現', short(rec['full']), '|', short(rec['train']), '|', short(rec['hold']), '| roll', rec['roll20']['win_rate'], '| dca', rec['dca20']['median'])
    log('  2007-2021', short(h21), '| halves', short(rec['stress']['hold_first_half']), '/', short(rec['stress']['hold_second_half']))
    log('  stress grades', st)
    return rec


# ═════════════════════════ 角度全体の多重検定 ═════════════════════════
def angle_multiple_testing(x2, p1):
    ps_all, ps_graded = {}, {}
    for t in RES['tested']:
        p = (t.get('hold') or {}).get('p')
        ps_all[t['id']] = p
        if not t.get('report_only'):
            ps_graded[t['id']] = p
    ps_all['X2_VM'] = ps_graded['X2_VM'] = x2['hold']['p']
    ps_all['P1_VQ'] = ps_graded['P1_VQ'] = p1['hold']['p']
    ha, hg = holm(ps_all), holm(ps_graded)
    return {'n_tested_angle': len(ps_all), 'n_graded_non_report': len(ps_graded),
            'holm_all_31': {'X2_VM': ha.get('X2_VM'), 'P1_VQ': ha.get('P1_VQ')},
            'holm_graded_8': {'X2_VM': hg.get('X2_VM'), 'P1_VQ': hg.get('P1_VQ')},
            'program_bonferroni_t': PROGRAM_BONF_T,
            'X2_VM_full_t_yen': x2['full']['t'], 'X2_VM_full_t_usd': x2['usd']['full']['t'],
            'X2_VM_full_t_drop_1998_2000': x2['stress']['full_drop_1998_2000']['t'],
            'X2_VM_clears_program_line_yen': (x2['full']['t'] or 0) >= PROGRAM_BONF_T,
            'X2_VM_clears_program_line_usd': (x2['usd']['full']['t'] or 0) >= PROGRAM_BONF_T,
            'duplicate_note': 'X2_VM は mw_japan の E4_value_mom（同じ JKP 日本 vw の be_me＋ret_12_1 第3分位・米ドル）を円で測り直したもの。'
                              'mw_japan_verify はそれを S→A に下げている（保有 t≥1.65 は 2022〜2025 に依る・2007-2021 +0.85%/年 t1.05）。'
                              'プログラム全体では新しい独立の検定ではない'}


def main():
    x2 = verify_x2vm()
    p1 = verify_p1vq()
    mt = angle_multiple_testing(x2, p1)
    # 研究側の主張との突き合わせ
    claimed = {'X2_VM': {'full_ex': 3.56, 'full_t': 4.53, 'train_ex': 5.27, 'train_t': 4.31, 'hold_ex': 1.86, 'hold_t': 2.28, 'hold_cagr_diff': 1.94,
                         'net_cost_hold_ex': 1.74, 'recent_ex': 1.36, 'roll20_win': 1.0, 'dca20_win': 1.0, 'dca20_median': 1.385},
               'P1_VQ': {'full_ex': 2.01, 'full_t': 2.28, 'train_ex': 3.79, 'train_t': 2.78, 'hold_ex': 0.52, 'hold_t': 0.51, 'hold_cagr_diff': 0.36,
                         'net_cost_hold_ex': 0.48, 'recent_ex': 0.12, 'roll20_win': 0.882, 'dca20_win': 0.765, 'dca20_median': 1.105}}
    repro = {}
    for nm, r in (('X2_VM', x2), ('P1_VQ', p1)):
        mine = {'full_ex': r['full']['ex'], 'full_t': r['full']['t'], 'train_ex': r['train']['ex'], 'train_t': r['train']['t'],
                'hold_ex': r['hold']['ex'], 'hold_t': r['hold']['t'], 'hold_cagr_diff': r['hold']['cagr_diff'],
                'net_cost_hold_ex': r['cost_hold_010']['ex'], 'recent_ex': r['recent_2013_07']['ex'], 'roll20_win': r['roll20']['win_rate'],
                'dca20_win': r['dca20']['win_rate'], 'dca20_median': r['dca20']['median']}
        diffs = {k: round(mine[k] - claimed[nm][k], 3) for k in mine}
        repro[nm] = {'mine': mine, 'claimed': claimed[nm], 'diff': diffs, 'match_within_0_05': all(abs(v) <= 0.05 for v in diffs.values())}
    for r in (x2, p1):
        r.pop('_series', None)
    s = x2['stress']
    ps = p1['stress']
    nb, lg, rp, mt_ = x2['neighbors'], x2['legs_alone'], x2['replication_jkp21'], mt
    fjp = next((t for t in RES['tested'] if t['id'] == 'FJP'), {})
    fjp_f = fjp.get('full') or {}
    x2_issues = [
        f"数字は研究側と完全一致（全12項目の差 0.00）。相手は JKP 日本 mkt vw＝上限なしの時価加重。袖も相手も同じ RF を足してから同じ為替で円へ＝超過と総リターンの混同は無い",
        f"★重複: mw_japan の E4_value_mom（同じ規則・米ドル）を円で測り直しただけ（米ドルでも 全期間 t{x2['usd']['full']['t']}・保有 {x2['usd']['hold']['ex']:+.2f} t{x2['usd']['hold']['t']}）。"
        f"mw_japan_verify は同じ候補を S→A に下げている。プログラム全体では新しい独立の勝ちとして数えてはいけない（1本として数える）",
        f"保有期間は盲検ではない: 同じ規則の 2007〜 の成績は mw_japan（と 2026-09-26 の jkp_evidence）で既に測られており、事前登録（known_from_other_angles）自身が『割安＋勢い +1.83（S）』を引いている。"
        f"さらに割安＋勢いの組み合わせは Asness（2011『Momentum in Japan』）・Asness-Moskowitz-Pedersen（2013・日本を含む標本は 2011 年まで）で公表済み＝保有期間の前半の約5年は設計の標本内",
        f"C3（保有 t≥1.65）は 2022〜2025 に依る: 2007-2021 は {s['hold_2007_2021']['ex']:+.2f}%/年 t{s['hold_2007_2021']['t']}・2013-2021 は {s['hold_2013_2021']['ex']:+.2f}%/年・"
        f"2022〜 は {s['hold_2022_on']['ex']:+.2f}%/年 t{s['hold_2022_on']['t']}。保有期間の対数の超過の {round(s['share_of_hold_log_excess_2022_2025']*100)}% がこの4年（東証の PBR 要請・世界の割安の戻り）。"
        f"ただし保有の前半 2007-2016/06 も {s['hold_first_half']['ex']:+.2f}%/年 t{s['hold_first_half']['t']}（2008 年 {s['yearly_excess_hold_pct'].get(2008)}%）で、後半は t{s['hold_second_half']['t']}。保有期間内の10年窓は {s['hold_10y_windows']['positive']}/{s['hold_10y_windows']['n']} が正",
        f"勢いの脚は日本では単独で効いていない: ret_12_1 第3分位 対 市場 訓練 {lg['ret_12_1']['train']['ex']:+.2f}%/年 t{lg['ret_12_1']['train']['t']}・保有 {lg['ret_12_1']['hold']['ex']:+.2f}%/年。"
        f"訓練期間の第3−第1 は {x2['side_by_train_performance']['ret_12_1']['mean_p3_minus_p1_ann']:+.2f}%/年 t{x2['side_by_train_performance']['ret_12_1']['t']}＝研究側の『訓練期間だけで決めた側』は JKP の符号の約束（因子=第3−第1）をなぞるだけで成績の確認ではない。"
        f"組み合わせの効きは割安の脚（保有 {lg['be_me']['hold']['ex']:+.2f} t{lg['be_me']['hold']['t']}）と、二つの上乗せの逆相関（相関 −0.46）による追従のぶれの縮みから来る".replace('−0.46', str(x2['corr_active_value_mom'])),
        f"隣の定義: n の下限（10/50/100）では不変。勢いの窓 ret_6_1 は保有 t{nb['mom=ret_6_1']['hold'].split(' t')[1].split(' ')[0]}・ret_9_1 は t{nb['mom=ret_9_1']['hold'].split(' t')[1].split(' ')[0]}・ret_12_7 は t{nb['mom=ret_12_7']['hold'].split(' t')[1].split(' ')[0]}。"
        f"割安の物差しを ni_me にすると保有 t{nb['value=ni_me']['hold'].split(' t')[1].split(' ')[0]}（C3 割れ）・ocf_me は訓練 t{nb['value=ocf_me']['train'].split(' t')[1].split(' ')[0]}（C1 割れ）。勢いを 2/3 に厚くすると保有 t{nb['weights_mom2/3']['hold'].split(' t')[1].split(' ')[0]}。"
        f"vw_cap で組んだ袖（相手は純粋な vw のまま）は保有 t{nb['sleeve_vw_cap_vs_pure_vw']['hold'].split(' t')[1].split(' ')[0]}＝S の C3 は物差しの選び方で割れるが、A の条件は崩れない",
        f"★大型株だけの隣（French Japan）では負ける: 6分割の BIG HiBM＋BIG HiPRIOR は保有 {nb['French6_BIG_HiBM+BIG_HiPRIOR']['hold']}・2007-2021 {nb['French6_BIG_HiBM+BIG_HiPRIOR']['hold_2007_2021']}、"
        f"25分割の角（研究側 P1_VM・自身も C）は 2007-2021 {nb['French25_BIG_HiBM+BIG_HiPRIOR（研究側 P1_VM）']['hold_2007_2021']}。JKP の三分位（数百社・中小型も含む）で出る上乗せは、同じ考え方の大型株の袖では保有期間に有意でない",
        f"C5 は保有期間でも頑丈: JKP 先進21か国 全期間 {rp['full_positive']}/{rp['regions']}・保有期間だけ {rp['hold_positive']}/{rp['regions']}（t≥1.65 は {rp['hold_t_ge_1_65']}）・2007-2021 だけでも {rp['hold_2007_2021_positive']}/{rp['regions']}"
        f" → A の条件（C3 か C5）は C5 で満たす。2021-12 で保有期間を切った格は {x2['stress_grades']['hold_cut_2021_12']}",
        f"多重検定: 族（X2 の3本）の Holm p={x2['family_holm_p_reproduced']}・角度の格付けした8本で Holm p={mt_['holm_graded_8']['X2_VM']}・全31本で {mt_['holm_all_31']['X2_VM']}。"
        f"C7 は全期間 t{x2['full']['t']}（HLZ の 3.0）で通る。プログラム全体の Bonferroni の線 t{PROGRAM_BONF_T} はかろうじて越える（米ドル t{x2['usd']['full']['t']}）が、"
        f"1998-2000 を抜くと t{s['full_drop_1998_2000']['t']} で線を割る。訓練期間は 1988-1996 t{s['train_1988_1996']['t']}・1997-2006 t{s['train_1997_2006']['t']}・1990-92 抜き t{s['train_drop_1990_1992']['t']} と頑丈",
        f"費用: 回転 1.2/年×0.10% で保有 {x2['cost_hold_010']['ex']:+.2f}%/年 t{x2['cost_hold_010']['t']}・回転2倍×0.30% で {x2['cost_hold_2x_030']['ex']:+.2f}%/年 t{x2['cost_hold_2x_030']['t']}（C3 は割れ・C6 は保つ）。"
        f"損益分岐は片道100%あたり {x2['breakeven_cost_per_unit_pct']}%＝費用では崩れない",
        f"実行の現実: 紙のポートフォリオ（JKP 三分位・日本の数百社）で、NISA で持てる同じ中身の器は無い。研究側の P2 で『vm』の器とされた FJP（AlphaDEX）は MSCI Japan に {fjp_f.get('from')}〜 {fjp_f.get('ex_ann')}%/年 t{fjp_f.get('t')}。"
        f"投資家の相手（S&P500≈French 米国 Mkt・円）に対しては 保有期間 CAGR差 {x2['context_vs_US_market_yen']['hold']['cagr_diff']:+.2f}%/年＝日本の中の勝ちで、市場（S&P500）に勝つ話ではない",
    ]
    p1_issues = [
        f"数字は研究側と完全一致（全12項目の差 0.00）。相手は French Japan Mkt＝上限なしの時価加重・袖も相手も米ドルの総リターンを同じ為替で円へ",
        f"保有期間の超過は統計的に0と区別できない: {p1['hold']['ex']:+.2f}%/年 t{p1['hold']['t']}（CAGR差 {p1['hold']['cagr_diff']:+.2f}）・前半 {ps['hold_first_half']['ex']:+.2f} t{ps['hold_first_half']['t']}／後半 {ps['hold_second_half']['ex']:+.2f} t{ps['hold_second_half']['t']}・2013-07〜 {p1['recent_2013_07']['cagr_diff']:+.2f}",
        f"★B を支える C2（保有期間の CAGR 差が正）は 2022〜2026 だけに依る: 保有期間の対数の超過の {round(ps['share_of_hold_log_excess_2022_2026']*100)}%（＝2022 より前は負）。"
        f"2007-2021 は {ps['hold_2007_2021']['ex']:+.2f}%/年 CAGR差 {ps['hold_2007_2021']['cagr_diff']:+.2f}・2007-2019 は CAGR差 {ps['hold_2007_2019']['cagr_diff']:+.2f}・2013-2021 は {ps['hold_2013_2021']['cagr_diff']:+.2f}。"
        f"2021-12 で保有期間を切ると格は {p1['stress_grades']['hold_cut_2021_12']}。保有期間内の10年窓で正は {ps['hold_10y_windows']['positive']}/{ps['hold_10y_windows']['n']}",
        f"脚の単独: BIG HiBM（割安）は保有 {p1['neighbors']['BIG_HiBM_alone']['hold']}・2007-2021 {p1['neighbors']['BIG_HiBM_alone']['hold_2007_2021']}／BIG HiOP（質）は訓練から効いていない（{p1['neighbors']['BIG_HiOP_alone']['train']}・保有 {p1['neighbors']['BIG_HiOP_alone']['hold']}）。"
        f"組み合わせの訓練 t2.78 は割安の脚と分散から来ており、質の脚は日本の大型株で一度も上乗せを出していない",
        f"★隣の定義で符号が割れる: 一段内側（ME5 BM4＋OP4）保有 {p1['neighbors']['ME5 BM4+OP4（一段内側）']['hold']}／上位2段（BM4-5＋OP4-5）CAGR差 {p1['neighbors']['ME5 (BM4+BM5)+(OP4+OP5)']['hold'].split('CAGR差')[1]}／"
        f"質を 2/3 に厚く {p1['neighbors']['weights_quality2/3']['hold']}／ME4＋ME5 は訓練 t{p1['neighbors']['ME4+ME5（BM5・OP5 の4脚等分）']['train'].split(' t')[1].split(' ')[0]}（C1 割れ）／"
        f"6分割（上位90%・三分位）は保有 {p1['neighbors']['French6_BIG_HiBM+BIG_HiOP（上位90%・三分位）']['hold']} だが 2007-2021 {p1['neighbors']['French6_BIG_HiBM+BIG_HiOP（上位90%・三分位）']['hold_2007_2021']}／"
        f"32分割の割安かつ質の角は C。B は『いちばん端の角を半々』という1点でだけ立つ",
        f"費用: 回転2倍×0.30% で保有 CAGR差 {p1['cost_hold_2x_030']['cagr_diff']:+.2f}（ほぼ0）・損益分岐は片道100%あたり {p1['breakeven_cost_per_unit_pct']}%。1998-2000 を抜くと訓練が {p1['stress']['train_drop_1998_2000']['years']}年＜15年で C1 不合格（t は {p1['stress']['train_drop_1998_2000']['t']}）",
        f"他地域の保有期間: Europe {p1['replication']['Europe']['hold']}・Asia Pacific ex Japan {p1['replication']['Asia_Pacific_ex_Japan']['hold']} は正だが、2007-2021 だけだと "
        f"{p1['replication']['Europe']['hold_2007_2021']} ／ {p1['replication']['Asia_Pacific_ex_Japan']['hold_2007_2021']}（CAGR差はどちらも負）＝他地域の保有期間の正も 2022〜 の世界の割安の戻りに依る。北米（数えない）は保有 {p1['replication']['North_America']['hold']}",
        f"集中と母集団: BIG HiBM は最少 {p1['n_firms']['BIG_HiBM']['min']} 社（{p1['n_firms']['BIG_HiBM']['min_month']}）・保有期間でも最少 {p1['n_firms']['BIG_HiBM']['hold_min']} 社。French の国際データは 2007 年前後で母集団の出所が替わる（mw_japan_verify の指摘）",
        f"多重検定: 族（P1 の3本）の Holm p={p1['family_holm_p_reproduced']}・全期間 t{p1['full']['t']}＜3.0＝C7 不合格（研究側の B と同じ）。角度の格付け8本の中で唯一の B で、同じ族の P1_VM・P1_VQM は C",
        f"文脈: 投資家の相手（S&P500 円）に対して保有期間 CAGR差 {p1['context_vs_US_market_yen']['hold']['cagr_diff']:+.2f}%/年。紙の袖で、同じ中身の器は無い",
    ]
    verdicts = [
        {'name': 'X2_VM', 'claimed_grade': 'S', 'verified_grade': 'A', 'verdict': 'downgraded to A', 'reproduced': repro['X2_VM']['match_within_0_05'],
         'key_numbers': (f"再現: 訓練 {x2['train']['ex']:+.2f}%/年 t{x2['train']['t']}・保有 {x2['hold']['ex']:+.2f}%/年 t{x2['hold']['t']}（CAGR差 {x2['hold']['cagr_diff']:+.2f}）・"
                         f"全期間 {x2['full']['ex']:+.2f}%/年 t{x2['full']['t']}・費用後の保有 {x2['cost_hold_010']['ex']:+.2f}・転がる20年 {x2['roll20']['wins']}/{x2['roll20']['windows']}・"
                         f"積立20年 中央 {x2['dca20']['median']}｜2007-2021 {s['hold_2007_2021']['ex']:+.2f}%/年 t{s['hold_2007_2021']['t']}・"
                         f"2022〜 {s['hold_2022_on']['ex']:+.2f}%/年 t{s['hold_2022_on']['t']}・保有の前半 {s['hold_first_half']['ex']:+.2f} t{s['hold_first_half']['t']}／"
                         f"後半 {s['hold_second_half']['ex']:+.2f} t{s['hold_second_half']['t']}・他国の保有期間 {rp['hold_positive']}/{rp['regions']}・米ドル全期間 t{x2['usd']['full']['t']}"),
         'issues': x2_issues, 'stress_grades': x2['stress_grades'],
         'program_level': 'mw_japan の E4_value_mom（検証で A）と同じ賭けの重複。プログラム全体の勝ちの数には足さない'},
        {'name': 'P1_VQ', 'claimed_grade': 'B', 'verified_grade': 'C', 'verdict': 'downgraded to C', 'reproduced': repro['P1_VQ']['match_within_0_05'],
         'key_numbers': (f"再現: 訓練 {p1['train']['ex']:+.2f}%/年 t{p1['train']['t']}・保有 {p1['hold']['ex']:+.2f}%/年 t{p1['hold']['t']}（CAGR差 {p1['hold']['cagr_diff']:+.2f}）・"
                         f"全期間 {p1['full']['ex']:+.2f} t{p1['full']['t']}・費用後の保有 {p1['cost_hold_010']['ex']:+.2f}・転がる20年 {p1['roll20']['wins']}/{p1['roll20']['windows']}・積立20年 中央 {p1['dca20']['median']}｜"
                         f"2007-2021 {ps['hold_2007_2021']['ex']:+.2f}%/年 CAGR差{ps['hold_2007_2021']['cagr_diff']:+.2f}・前半 {ps['hold_first_half']['ex']:+.2f}／後半 {ps['hold_second_half']['ex']:+.2f}・"
                         f"2013-2021 {ps['hold_2013_2021']['ex']:+.2f}・一段内側の隣 保有 {p1['neighbors']['ME5 BM4+OP4（一段内側）']['hold']}"),
         'issues': p1_issues, 'stress_grades': p1['stress_grades'],
         'why_not_confirmed': '登録どおりの機械的な格は B で再現する。だが B の唯一の中身（保有期間の符号が費用後も正）は 2022〜2026 の4年半に全部依り、2007-2021 では負、隣の定義でも負に割れる。t0.51 の正は偶然と区別できないので C に下げる'},
    ]
    summary_ja = (
        "jp_nisa_bridge の S 1本（X2_VM）と B 1本（P1_VQ・B はこれだけ）を自前のコードで作り直し、数字は24項目すべて研究側と一致しました。相手はどちらも上限なしの時価加重で、円への換算と超過の扱いにも誤りはありません。\n"
        f"X2_VM（日本の割安＋勢い・円）は A に下げます。保有期間の t≥1.65 は 2022〜2025 年に依り（2007-2021 は {s['hold_2007_2021']['ex']:+.2f}%/年 t{s['hold_2007_2021']['t']}）、割安の物差し（ni_me）や勢いの重み（2/3）を隣に替えても C3 が割れます（勢いの窓 6/9/12-7か月では保つ）。大型株だけで組んだ同じ考え方（French の BIG の角）は 2007-2021 に負けました。\n"
        f"ただし他国の保有期間は {rp['hold_positive']}/{rp['regions']} が正（2007-2021 でも {rp['hold_2007_2021_positive']}/{rp['regions']}）で、A の条件は C5 で保ちます。\n"
        f"X2_VM は mw_japan の E4_value_mom（検証で A）を円で測り直した重複で、保有期間の結果も事前に知られていました。プログラム全体の新しい勝ちには数えません。器は無く、S&P500（円）には保有期間に CAGR で {x2['context_vs_US_market_yen']['hold']['cagr_diff']:+.2f}%/年 負けています。\n"
        f"P1_VQ（大型の割安＋質）は C に下げます。保有期間 {p1['hold']['ex']:+.2f}%/年 t{p1['hold']['t']} の正は 2022 年以降だけから来ており（2007-2021 の CAGR 差 {ps['hold_2007_2021']['cagr_diff']:+.2f}）、一段内側の隣では負、質の脚は単独では訓練期間から有意に効いていません（t0.49）。"
    )
    out = {'angle': 'jp_nisa_bridge', 'role': '反証の検証（adversarial verify）', 'researcher_file': 'night/mw_jp_nisa_bridge.py → out/mw_jp_nisa_bridge.json',
           'own_code': 'この道具の自前（mw_common は取得部品 get / french_tables / jkp_rows だけ）',
           'candidates_checked': 'S/A は X2_VM の1本・B は P1_VQ の1本だけ（主張どおり）',
           'reproduction': repro, 'X2_VM': x2, 'P1_VQ': p1, 'multiple_testing': mt, 'verdicts': verdicts, 'summary_ja': summary_ja, 'log': LOG}
    json.dump(out, open(os.environ.get('VERIFY_OUT', OUT), 'w'), ensure_ascii=False, indent=1, default=str)
    return out


if __name__ == '__main__':
    main()
