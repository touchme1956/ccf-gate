#!/usr/bin/env python3
"""night/mw_intl.py — 『市場に勝てる歴史検証』(mw) の角度 intl（独立の再現・読むだけ・門の判定には不使用）

問い: 米国の 2006-12 までのデータだけで決めた『良い側の1/3（買いだけ・上限なしの時価加重）』は、
      米国外の各国・各地域で『その国の純粋な時価加重の市場（JKP vw mkt）』に勝ったか。
事前登録: out/mw_intl_prereg.json（線は out/mw_prereg.json）。出力: out/mw_intl.json
使い方: python3 night/mw_intl.py
"""
import collections, concurrent.futures as CF, csv, io, json, math, os, statistics as S, subprocess, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PRE_NAME = 'mw_intl_prereg.json'
PRE = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
GROUPS = ['quality_profitability', 'investment_issuance', 'value_payout', 'momentum', 'low_risk', 'accruals']
CHARS = [k for g in GROUPS for k in PRE['characteristics'][g]]
DESC = {k: v for g in GROUPS for k, v in PRE['characteristics'][g].items()}
PUB = PRE['characteristics']['publication_year']
TURN = PRE['cost']['annual_oneway_turnover']
QUALITY = ['ope_be', 'gp_at', 'qmj', 'qmj_prof', 'cop_at']
N_MIN, N_SENS, MIN_MONTHS = 10, 30, 240
REP = 'world_ex_us'
REGIONS = ['world_ex_us', 'developed', 'emerging', 'world', 'frontier']
DEVELOPED = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
             'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe', 'usa'}
COST = {'dev': 0.003, 'em': 0.005, 'usa': 0.001}
S3 = 'https://jkpfactors-data.s3.amazonaws.com/public/'


def _fast_excess_stats(s, b, a=None, z=None, per_year=12, lag=12):
    """mw_common.excess_stats と同じ式・同じ丸め。違いは β の中で平均を毎回計算し直さないことだけ
    （共通部品は sum((x - S.mean(sv)) ...) で平均を要素ごとに再計算し O(n²)・480か月で0.5秒/回。
    この角度は約1万回呼ぶので、共通部品は触らずここで差し替える。一致は起動時に自己検査する）"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < max(24, per_year * 2):
        return None
    ex = [s[k] - b[k] for k in ks]
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    n = len(ks)
    mex, ms, mb = math.fsum(ex) / n, math.fsum(sv) / n, math.fsum(bv) / n
    te = math.sqrt(math.fsum((v - mex) ** 2 for v in ex) / (n - 1)) * math.sqrt(per_year)
    vb = math.fsum((v - mb) ** 2 for v in bv) / n
    beta = math.fsum((x - ms) * (y - mb) for x, y in zip(sv, bv)) / n / vb if vb else None
    t = M.nw_t(ex, lag)
    g_s, g_b = M.cagr(sv, per_year), M.cagr(bv, per_year)
    sd_s = math.sqrt(math.fsum((v - ms) ** 2 for v in sv) / (n - 1)); sd_b = math.sqrt(math.fsum((v - mb) ** 2 for v in bv) / (n - 1))
    return {'from': ks[0], 'to': ks[-1], 'years': round(n / per_year, 1),
            'ex_ann': round(mex * per_year * 100, 2), 't': round(t, 2) if t is not None else None,
            'p': round(M.p_two(t), 4) if t is not None else None,
            'cagr_s': round(g_s * 100, 2), 'cagr_b': round(g_b * 100, 2), 'cagr_diff': round((g_s - g_b) * 100, 2),
            'te': round(te * 100, 2), 'ir': round(mex * per_year / te, 2) if te else None,
            'beta': round(beta, 2) if beta is not None else None,
            'vol_s': round(sd_s * math.sqrt(per_year) * 100, 1), 'vol_b': round(sd_b * math.sqrt(per_year) * 100, 1)}


def _selftest_fast():
    import random
    rnd = random.Random(7)
    for n in (30, 240, 480):
        s = {190001 + i: rnd.gauss(0.01, 0.05) for i in range(n)}
        b = {k: v * 0.9 + rnd.gauss(0, 0.02) for k, v in s.items()}
        slow, fast = _ORIG_EXCESS_STATS(s, b), _fast_excess_stats(s, b)
        assert slow == fast, (slow, fast)
    return True


_ORIG_EXCESS_STATS = M.excess_stats
M.excess_stats = _fast_excess_stats


def unit_cost(loc):
    if loc == 'usa':
        return COST['usa']
    if loc in ('world_ex_us', 'developed', 'world') or loc in DEVELOPED:
        return COST['dev']
    return COST['em']


# ───────────────────────── 取得 ─────────────────────────
def availability():
    return json.loads(M.get(S3 + 'availability.json', name='jkp_availability.json', max_age_days=30))


def country_mkts():
    b = M.get(S3 + '%5Ball_countries%5D_%5Bmkt%5D_%5Bmonthly%5D_%5Bvw%5D.zip', name='jkp_factor_all_countries_mkt_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = collections.defaultdict(dict)
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        out[x['location']][M._ym(x['date'])] = float(x['ret'])
    return dict(out)


def country_nstocks():
    """国ごとの市場の銘柄数 {国: {ym: n_stocks}}（被覆率の分母・事前登録2）"""
    b = M.get(S3 + '%5Ball_countries%5D_%5Bmkt%5D_%5Bmonthly%5D_%5Bvw%5D.zip', name='jkp_factor_all_countries_mkt_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = collections.defaultdict(dict)
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['n_stocks'] in ('', 'NA', 'na'):
            continue
        out[x['location']][M._ym(x['date'])] = int(float(x['n_stocks']))
    return dict(out)


def pf_with_n(loc, key):
    """三分位 → {'1.0': {ym: (ret, n)}, ...}。取れなければ None（0で埋めない）"""
    try:
        rows = M.jkp_rows(loc, key, 'portfolios', 'vw')
    except Exception as e:  # noqa
        return None
    d = {}
    for x in rows:
        if x['ret'] in ('', 'NA', 'na'):
            continue
        d.setdefault(x['pf'], {})[M._ym(x['date'])] = (float(x['ret']), int(float(x['n'])) if x['n'] not in ('', 'NA') else 0)
    return d


def us_direction(key):
    try:
        rows = M.jkp_rows('usa', key, 'factor', 'vw')
        return int(rows[0]['direction'])
    except Exception:  # noqa
        return None


# ───────────────────────── 集計の小道具 ─────────────────────────
def to_total(d, rf):
    return {m: v + rf[m] for m, v in d.items() if m in rf}


def good_series(pf, side, nmin):
    if not pf or side not in pf:
        return {}
    return {m: r for m, (r, n) in pf[side].items() if n >= nmin}


def compact(st):
    if not st:
        return None
    return {'ex': st['ex_ann'], 't': st['t'], 'cd': st['cagr_diff'], 'y': st['years']}


def four(s, b):
    return {'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END),
            'hold': M.excess_stats(s, b, a=M.HOLD_START), 'recent': M.excess_stats(s, b, a=M.RECENT_START)}


def ts_stats(x, a=None, z=None):
    """時系列（{ym: 値}）の年率平均と NW t"""
    v = [x[k] for k in sorted(x) if (a is None or k >= a) and (z is None or k <= z)]
    if len(v) < 24:
        return None
    t = M.nw_t(v)
    return {'ex': round(S.mean(v) * 1200, 2), 't': round(t, 2) if t is not None else None, 'months': len(v)}


def git_sha(path):
    try:
        return subprocess.check_output(['git', '-C', M.BASE, 'log', '-n1', '--format=%H', '--', path], text=True).strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── 本体 ─────────────────────────
def main():
    fast_ok = _selftest_fast()
    av = availability()
    ff = M.ff_factors()
    rf = ff['rf']
    cm = country_mkts()
    rmk = {r: M.jkp_mkt(r, 'vw') for r in REGIONS + ['usa']}

    # 候補の国: 米国以外・三分位のファイルがある・市場が240か月以上
    cand = sorted(c for c in av['portfolios'] if c not in ('all_countries', 'all_regions', 'usa') and c not in REGIONS
                  and len(cm.get(c, {})) >= MIN_MONTHS)

    # 先にまとめて取る（キャッシュに入る）
    jobs = [(c, k) for k in CHARS for c in cand if k in av['portfolios'].get(c, [])]
    jobs += [(r, k) for k in CHARS for r in REGIONS + ['usa']]
    PF = {}
    with CF.ThreadPoolExecutor(6) as ex:
        for (loc, key), res in zip(jobs, ex.map(lambda j: pf_with_n(*j), jobs)):
            PF[(loc, key)] = res
    fetch_failed = [f'{l}:{k}' for (l, k), v in PF.items() if v is None and k in av['portfolios'].get(l, [])]

    # 良い側（米国・〜2006-12・vw）
    side, side_check = {}, {}
    for k in CHARS:
        s, _ = M.jkp_good_side('usa', k, 'vw', upto=M.TRAIN_END)
        side[k] = s
        d = us_direction(k)
        side_check[k] = {'good_side': s, 'jkp_direction': d,
                         'agrees': (d == 1 and s == '3.0') or (d == -1 and s == '1.0') if d in (1, -1) else None}

    # ── 国ごと
    per_country = {}
    usable = {}  # (k, c) -> 使える月の良い側（超過・米国T-bill）
    for k in CHARS:
        rows = {}
        for c in cand:
            pf = PF.get((c, k))
            if pf is None:
                continue
            g = good_series(pf, side[k], N_MIN)
            ms = sorted(set(g) & set(cm[c]) & set(rf))
            rec = {'months': len(ms)}
            if len(ms) < MIN_MONTHS:
                rec['qualifies'] = False
                rows[c] = rec
                continue
            usable[(k, c)] = {m: g[m] for m in ms}
            s = to_total({m: g[m] for m in ms}, rf); b = to_total({m: cm[c][m] for m in ms}, rf)
            f = four(s, b)
            net = M.excess_stats(M.apply_cost(s, TURN[k], unit_cost(c)), b, a=M.HOLD_START)
            g30 = good_series(pf, side[k], N_SENS)
            ms30 = sorted(set(g30) & set(cm[c]) & set(rf))
            s30 = to_total({m: g30[m] for m in ms30}, rf); b30 = to_total({m: cm[c][m] for m in ms30}, rf)
            f30 = {'full': M.excess_stats(s30, b30), 'hold': M.excess_stats(s30, b30, a=M.HOLD_START)} if len(ms30) >= MIN_MONTHS else None
            ns = sorted(pf[side[k]][m][1] for m in ms)
            rec.update({'qualifies': True, 'start': ms[0], 'end': ms[-1], 'n_median': ns[len(ns) // 2], 'dev': c in DEVELOPED,
                        **{w: compact(v) for w, v in f.items()}, 'hold_net': compact(net),
                        'n30': {w: compact(v) for w, v in f30.items()} if f30 else None})
            rows[c] = rec
        per_country[k] = rows

    # blend（国ごと）
    rows = {}
    for c in cand:
        comps = [k for k in QUALITY if (k, c) in usable]
        if len(comps) < 3:
            continue
        allm = sorted(set().union(*[set(usable[(k, c)]) for k in comps]))
        g = {}
        for m in allm:
            v = [usable[(k, c)][m] for k in comps if m in usable[(k, c)]]
            if len(v) >= 3:
                g[m] = S.mean(v)
        ms = sorted(set(g) & set(cm[c]) & set(rf))
        rec = {'months': len(ms), 'components': comps}
        if len(ms) < MIN_MONTHS:
            rec['qualifies'] = False; rows[c] = rec; continue
        usable[('blend_quality', c)] = {m: g[m] for m in ms}
        s = to_total({m: g[m] for m in ms}, rf); b = to_total({m: cm[c][m] for m in ms}, rf)
        f = four(s, b)
        net = M.excess_stats(M.apply_cost(s, TURN['blend_quality'], unit_cost(c)), b, a=M.HOLD_START)
        rec.update({'qualifies': True, 'start': ms[0], 'end': ms[-1], 'dev': c in DEVELOPED,
                    **{w: compact(v) for w, v in f.items()}, 'hold_net': compact(net)})
        rows[c] = rec
    per_country['blend_quality'] = rows
    FAM = CHARS + ['blend_quality']

    # 国の数え上げと、国をまたいだ平均
    summary = {}
    for k in FAM:
        q = {c: r for c, r in per_country[k].items() if r.get('qualifies')}
        cnt = lambda w, sub=None: (sum(1 for c, r in q.items() if r.get(w) and (sub is None or sub(c)) and r[w]['ex'] > 0),
                                   sum(1 for c, r in q.items() if r.get(w) and (sub is None or sub(c))))
        pos_full, n_full = cnt('full'); pos_tr, n_tr = cnt('train'); pos_h, n_h = cnt('hold'); pos_rec, n_rec = cnt('recent')
        pos_hn = sum(1 for r in q.values() if r.get('hold_net') and r['hold_net']['ex'] > 0 and r['hold_net']['cd'] > 0)
        dv = lambda c: c in DEVELOPED
        em = lambda c: c not in DEVELOPED
        n30 = {c: r['n30'] for c, r in q.items() if r.get('n30')}
        # 国をまたいだ平均（各月、資格を満たす国の 良い側−市場 の単純平均）
        pooled = collections.defaultdict(list)
        for c in q:
            for m, v in usable[(k, c)].items():
                pooled[m].append(v - cm[c][m])
        pm = {m: S.mean(v) for m, v in pooled.items()}
        ncty = sorted(len(v) for v in pooled.values())
        summary[k] = {
            'countries': len(q),
            'positive_full': [pos_full, n_full], 'positive_train': [pos_tr, n_tr], 'positive_hold': [pos_h, n_h], 'positive_recent': [pos_rec, n_rec],
            'positive_hold_net_of_cost': [pos_hn, n_h],
            'developed_positive_full': list(cnt('full', dv)), 'developed_positive_hold': list(cnt('hold', dv)),
            'emerging_positive_full': list(cnt('full', em)), 'emerging_positive_hold': list(cnt('hold', em)),
            'median_country_ex_full': round(S.median(r['full']['ex'] for r in q.values() if r.get('full')), 2) if q else None,
            'median_country_ex_hold': round(S.median(r['hold']['ex'] for r in q.values() if r.get('hold')), 2) if q else None,
            'sens_n30_positive_full': [sum(1 for v in n30.values() if v['full'] and v['full']['ex'] > 0), sum(1 for v in n30.values() if v['full'])],
            'sens_n30_positive_hold': [sum(1 for v in n30.values() if v['hold'] and v['hold']['ex'] > 0), sum(1 for v in n30.values() if v['hold'])],
            'pooled_equal_weight_countries': {'full': ts_stats(pm), 'train': ts_stats(pm, z=M.TRAIN_END), 'hold': ts_stats(pm, a=M.HOLD_START),
                                              'recent': ts_stats(pm, a=M.RECENT_START),
                                              'countries_per_month': {'min': ncty[0], 'median': ncty[len(ncty) // 2], 'max': ncty[-1]} if ncty else None},
            'japan': per_country[k].get('jpn'),
        }

    # ── 地域（代表 world_ex_us と報告の地域）と米国の参考
    def region_series(loc, k):
        if k == 'blend_quality':
            parts = [good_series(PF.get((loc, q)), side[q], N_MIN) for q in QUALITY]
            if not all(parts):
                return {}
            ms = set.intersection(*[set(p) for p in parts])
            return {m: S.mean(p[m] for p in parts) for m in ms}
        return good_series(PF.get((loc, k)), side[k], N_MIN)

    regional, rep_raw = {}, {}
    for loc in REGIONS + ['usa']:
        mk = rmk[loc]
        regional[loc] = {}
        for k in FAM:
            g = region_series(loc, k)
            ms = sorted(set(g) & set(mk) & set(rf))
            if len(ms) < 60:
                regional[loc][k] = {'months': len(ms), 'note': 'データ不足'}
                continue
            s = to_total({m: g[m] for m in ms}, rf); b = to_total({m: mk[m] for m in ms}, rf)
            f = four(s, b)
            uc = unit_cost(loc)
            net = M.excess_stats(M.apply_cost(s, TURN[k], uc), b, a=M.HOLD_START)
            net2 = M.excess_stats(M.apply_cost(s, TURN[k], uc * 2), b, a=M.HOLD_START)
            pub = PUB.get(k) if k != 'blend_quality' else max(PUB[q] for q in QUALITY)
            post = M.excess_stats(s, b, a=(pub + 1) * 100 + 1) if pub and pub + 1 <= 2023 else None
            rec = {'months': len(ms), 'start': ms[0], 'end': ms[-1], **f, 'hold_net': net, 'hold_net_2x': net2,
                   'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20), 'post_pub': {'from': (pub + 1) * 100 + 1 if pub else None, 'stats': post},
                   'unit_cost': uc, 'turnover': TURN[k]}
            regional[loc][k] = rec
            if loc == REP:
                rep_raw[k] = (s, b)

    # ── 主の族の判定（代表 world_ex_us）
    hp = {k: (regional[REP][k]['hold'] or {}).get('p') for k in FAM if regional[REP][k].get('hold')}
    hol = M.holm(hp)
    tested, graded = [], {}
    for k in FAM:
        r = regional[REP][k]
        sm = summary[k]
        repl = {'regions': sm['positive_full'][1], 'positive': sm['positive_full'][0]}
        g, crit = M.grade(r.get('full'), r.get('train'), r.get('hold'), r.get('roll20'), cost_hold=r.get('hold_net'),
                          repl=repl, family_holm_p=hol.get(k))
        graded[k] = {'grade': g, 'criteria': crit, 'holm_p': hol.get(k), 'repl': repl,
                     'repl_hold_reported': {'regions': sm['positive_hold'][1], 'positive': sm['positive_hold'][0]}}
        tested.append({'name': f'intl_{k}', 'family': 'primary', 'series': f'{REP} の良い側（{side[k] if k in side else "質5本の平均"}）vs {REP} の vw 市場',
                       'description': DESC.get(k, '質の型5本（ope_be・gp_at・qmj・qmj_prof・cop_at）の良い側を等分'),
                       'grade': g, 'criteria': crit})
    for loc in REGIONS + ['usa']:
        if loc == REP:
            continue
        for k in FAM:
            tested.append({'name': f'{loc}_{k}', 'family': 'reported' if loc != 'usa' else 'reference_us_train_country',
                           'series': f'{loc} の良い側 vs {loc} の vw 市場', 'grade': None})
    for k in FAM:
        tested.append({'name': f'countries_{k}', 'family': 'reported', 'series': f'米国外 {summary[k]["countries"]} か国それぞれ（国の数え上げ・国をまたいだ平均）', 'grade': None})

    # ── 検算
    sanity = {}
    fm = ff['mkt']
    ju = to_total(rmk['usa'], rf)
    ks = sorted(set(ju) & set(fm))
    sanity['jkp_usa_vw_vs_french_mkt'] = {'from': ks[0], 'to': ks[-1], 'corr': round(M.corr([ju[k] for k in ks], [fm[k] for k in ks]), 4),
                                         'cagr_jkp': round(M.cagr({k: ju[k] for k in ks}) * 100, 2), 'cagr_french': round(M.cagr({k: fm[k] for k in ks}) * 100, 2),
                                         'french_cagr_2007_on': round(M.cagr(M.window(fm, M.HOLD_START)) * 100, 2)}
    try:
        dx = None
        for t, v in M.french_tables('Developed_ex_US_3_Factors').items():
            if v['freq'] == 'monthly':
                i = v['cols'].index('Mkt-RF')
                dx = {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None}
                break
        wx = rmk['world_ex_us']
        ks = sorted(set(dx) & set(wx))
        sanity['jkp_world_ex_us_vs_french_developed_ex_us'] = {'from': ks[0], 'to': ks[-1], 'corr': round(M.corr([wx[k] for k in ks], [dx[k] for k in ks]), 4),
                                                              'mean_jkp': round(S.mean(wx[k] for k in ks) * 1200, 2), 'mean_french': round(S.mean(dx[k] for k in ks) * 1200, 2)}
    except Exception as e:  # noqa
        sanity['jkp_world_ex_us_vs_french_developed_ex_us'] = {'error': str(e)}
    sanity['good_side_vs_jkp_direction'] = side_check
    sanity['fetch_failed'] = fetch_failed
    sanity['fast_excess_stats_selftest'] = fast_ok
    sanity['candidate_countries'] = cand

    p2 = prereg2(dict(av=av, rf=rf, cm=cm, rmk=rmk, PF=PF, side=side, cand=cand, primary_hold_p=hp, primary_tested=tested))

    p3 = prereg3(dict(rf=rf, rmk=rmk, PF=PF, side=side, all_hold_p=p2.pop('_all_hold_p')))
    p4 = prereg4(dict(all_hold_p=p3.pop('_all_hold_p')))
    p5 = prereg5(dict(all_hold_p=p4.pop('_all_hold_p')))

    ph = post_hoc(dict(rf=rf, rmk=rmk, PF=PF, side=side, cm=cm, cand=cand), p2, p3)

    out = {'tool': 'night/mw_intl.py', 'prereg': f'out/{PRE_NAME}', 'prereg_commit': git_sha(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'representative': REP, 'good_side': side,
           'n_tested': len(tested), 'tested': tested, 'graded': graded, 'holm_family': hol,
           'regional': {loc: {k: v for k, v in d.items()} for loc, d in regional.items()},
           'country_summary': summary, 'per_country': per_country, 'sanity': sanity, 'prereg2': p2, 'prereg3': p3, 'prereg4': p4, 'prereg5': p5, 'post_hoc_diagnostics': ph}
    out['n_tested_all'] = len(tested) + len(p2['tested']) + len(p3['tested']) + len(p4['tested']) + len(p5['tested'])
    out.setdefault('generated', __import__('datetime').date.today().isoformat())
    p = os.path.join(M.BASE, 'out', 'mw_intl.json')
    with open(p, 'w') as fh:  # 2MB 未満に収めるため字下げなし（共通部品の save は indent=1 で 2.2MB になった）
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'))
    # 画面
    print('prereg', out['prereg_commit'])
    print('sanity', json.dumps({k: v for k, v in sanity.items() if k not in ('good_side_vs_jkp_direction', 'candidate_countries')}, ensure_ascii=False))
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.1f})" if v else '   —      '
    for k in FAM:
        r = regional[REP][k]; sm = summary[k]; gg = graded[k]
        print(f"{k:15} {gg['grade']} 全{f(r.get('full'))} 訓{f(r.get('train'))} 保{f(r.get('hold'))} 近{f(r.get('recent'))} "
              f"費後{f(r.get('hold_net'))} 20年{(r.get('roll20') or {}).get('wins')}/{(r.get('roll20') or {}).get('windows')} "
              f"国 全{sm['positive_full'][0]}/{sm['positive_full'][1]} 保{sm['positive_hold'][0]}/{sm['positive_hold'][1]} "
              f"平均 保{(sm['pooled_equal_weight_countries']['hold'] or {}).get('ex')} holm {gg['holm_p']}")
    print_prereg2(p2)
    print_prereg3(p3)
    print_prereg4(p4)
    print_prereg5(p5)
    print('事後の診断', json.dumps({k: (v if not isinstance(v, dict) else {kk: (vv if not isinstance(vv, dict) or 'ex_ann' not in vv else (vv['ex_ann'], vv['t'], vv['te'])) for kk, vv in v.items()}) for k, v in ph.items()}, ensure_ascii=False, default=str)[:4000])
    print('→', p)

# ───────────────────────── 事前登録2（out/mw_intl_prereg2.json） ─────────────────────────
PRE2_NAME = 'mw_intl_prereg2.json'
START2, RTHR, RTHR_HI = 199007, 0.4, 0.6
VALUE4 = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
COMBOS = ['value_composite', 'val_mom', 'val_qual', 'qual_mom', 'val_mom_qual', 'all20']
TURN2 = {'value_composite': 0.40, 'val_mom': 0.95, 'val_qual': 0.40, 'qual_mom': 0.95, 'val_mom_qual': 0.767}
PUB2 = {'value_composite': 2004, 'val_mom': 2013, 'val_qual': 2013, 'qual_mom': 2019, 'val_mom_qual': 2019, 'all20': 2023}
FAM27 = CHARS + ['blend_quality'] + COMBOS
DESC2 = {'blend_quality': '質の型5本（ope_be・gp_at・qmj・qmj_prof・cop_at）の良い側を等分',
         'value_composite': '割安4本（be_me・ni_me・ocf_me・div12m_me）の良い側を等分',
         'val_mom': '割安4本の平均50%＋勢い(ret_12_1)50%', 'val_qual': '割安4本の平均50%＋質5本の平均50%',
         'qual_mom': '質5本の平均50%＋勢い50%', 'val_mom_qual': '割安・勢い・質を1/3ずつ', 'all20': '20特性の良い側を等分'}


def prereg2(ctx):
    rf, cm, rmk, PF, side, cand = ctx['rf'], ctx['cm'], ctx['rmk'], ctx['PF'], ctx['side'], ctx['cand']
    cn = country_nstocks()
    turn = dict(TURN); turn.update(TURN2); turn['all20'] = round(S.mean(TURN[k] for k in CHARS), 3)

    def den_sum(pred):
        c = collections.Counter()
        for loc, d in cn.items():
            if pred(loc):
                for m, n in d.items():
                    c[m] += n
        return dict(c)
    DEN = {'world_ex_us': den_sum(lambda l: l != 'usa'), 'world': den_sum(lambda l: True),
           'developed': den_sum(lambda l: l in DEVELOPED), 'emerging': den_sum(lambda l: l not in DEVELOPED)}

    def cov(loc, k, m):
        pf = PF.get((loc, k)); d = (DEN.get(loc) or cn.get(loc, {})).get(m)
        if not pf or not d:
            return None
        return sum(pf[q][m][1] for q in pf if m in pf[q]) / d

    def screened(loc, k, rthr=RTHR, use_R=True):
        pf = PF.get((loc, k))
        if not pf or side[k] not in pf:
            return {}
        out = {}
        for m, (r, n) in pf[side[k]].items():
            if n < N_MIN or m < START2:
                continue
            if use_R:
                rr = cov(loc, k, m)
                if rr is None or rr < rthr:
                    continue
            out[m] = r
        return out

    def mix(parts):
        if not parts or not all(parts):
            return {}
        ms = set.intersection(*[set(q) for q in parts])
        return {m: S.mean(q[m] for q in parts) for m in ms}

    def region_strats(loc, rthr=RTHR, use_R=True):
        base = {k: screened(loc, k, rthr, use_R) for k in CHARS}
        out = dict(base)
        out['blend_quality'] = mix([base[k] for k in QUALITY])
        vc = mix([base[k] for k in VALUE4]); bq = out['blend_quality']; mo = base['ret_12_1']
        out['value_composite'] = vc
        out['val_mom'] = mix([vc, mo]); out['val_qual'] = mix([vc, bq]); out['qual_mom'] = mix([bq, mo]); out['val_mom_qual'] = mix([vc, mo, bq])
        out['all20'] = mix([base[k] for k in CHARS])
        return out

    def country_strats(c):
        base = {k: screened(c, k) for k in CHARS if PF.get((c, k))}
        out = dict(base)
        nq = lambda v: len(set(v) & set(cm[c]) & set(rf))
        comps = [k for k in QUALITY if k in base and nq(base[k]) >= MIN_MONTHS]
        if len(comps) >= 3:  # F2a の blend は主の族と同じ規則（構成要素が個別に資格・月に3本以上）
            g = {}
            for m in set().union(*[set(base[k]) for k in comps]):
                v = [base[k][m] for k in comps if m in base[k]]
                if len(v) >= 3:
                    g[m] = S.mean(v)
            out['blend_quality'] = g

        def grp(keys, need):
            ks = [k for k in keys if k in base and base[k]]
            g = {}
            for m in (set().union(*[set(base[k]) for k in ks]) if ks else set()):
                v = [base[k][m] for k in ks if m in base[k]]
                if len(v) >= need:
                    g[m] = S.mean(v)
            return g
        vc, bqm, mo = grp(VALUE4, 2), grp(QUALITY, 3), base.get('ret_12_1', {})
        out['value_composite'] = vc
        out['val_mom'] = mix([vc, mo]); out['val_qual'] = mix([vc, bqm]); out['qual_mom'] = mix([bqm, mo]); out['val_mom_qual'] = mix([vc, mo, bqm])
        out['all20'] = grp(CHARS, 12)
        return out

    def diag(loc, k, g, mk):
        """被覆の偏りの診断: 三分位3つの単純平均 − 市場（年率%）。良い側と同じ月で"""
        pf = PF.get((loc, k))
        if not pf or k not in CHARS:
            return None
        res = {}
        for w, a, z in (('train', None, M.TRAIN_END), ('hold', M.HOLD_START, None)):
            v = [S.mean(pf[q][m][0] for q in ('1.0', '2.0', '3.0')) - mk[m] for m in sorted(g)
                 if m in mk and all(m in pf.get(q, {}) for q in ('1.0', '2.0', '3.0')) and (a is None or m >= a) and (z is None or m <= z)]
            res[w] = round(S.mean(v) * 1200, 2) if len(v) >= 24 else None
        return res

    def evaluate(g, mk, k, loc):
        ms = sorted(set(g) & set(mk) & set(rf))
        if len(ms) < 60:
            return {'months': len(ms), 'note': 'データ不足（被覆の規則で測れる月が60未満）'}
        s = to_total({m: g[m] for m in ms}, rf); b = to_total({m: mk[m] for m in ms}, rf)
        f = four(s, b); uc = unit_cost(loc)
        pub = PUB.get(k) or PUB2.get(k) or (max(PUB[q] for q in QUALITY) if k == 'blend_quality' else None)
        post = M.excess_stats(s, b, a=(pub + 1) * 100 + 1) if pub and pub + 1 <= 2023 else None
        return {'months': len(ms), 'start': ms[0], 'end': ms[-1], **f,
                'hold_net': M.excess_stats(M.apply_cost(s, turn[k], uc), b, a=M.HOLD_START),
                'hold_net_2x': M.excess_stats(M.apply_cost(s, turn[k], uc * 2), b, a=M.HOLD_START),
                'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20),
                'post_pub': {'from': (pub + 1) * 100 + 1 if pub else None, 'stats': post}, 'unit_cost': uc, 'turnover': turn[k]}

    # ── 国ごと（被覆の規則つき）
    CS = {c: country_strats(c) for c in cand}
    per = {k: {} for k in FAM27}
    pooled_src = {k: collections.defaultdict(list) for k in FAM27}
    for c in cand:
        for k in FAM27:
            g = CS[c].get(k) or {}
            ms = sorted(set(g) & set(cm[c]) & set(rf))
            if len(ms) < MIN_MONTHS:
                continue
            s = to_total({m: g[m] for m in ms}, rf); b = to_total({m: cm[c][m] for m in ms}, rf)
            full, hold = M.excess_stats(s, b), M.excess_stats(s, b, a=M.HOLD_START)
            net = M.excess_stats(M.apply_cost(s, turn[k], unit_cost(c)), b, a=M.HOLD_START)
            per[k][c] = {'m': len(ms), 'start': ms[0], 'full': compact(full), 'hold': compact(hold),
                         'hold_net_ok': bool(net and net['ex_ann'] > 0 and net['cagr_diff'] > 0)}
            for m in ms:
                pooled_src[k][m].append(g[m] - cm[c][m])

    def counts(k, exclude=()):
        q = {c: r for c, r in per[k].items() if c not in exclude}
        pf_ = sum(1 for r in q.values() if r['full'] and r['full']['ex'] > 0)
        ph = sum(1 for r in q.values() if r['hold'] and r['hold']['ex'] > 0)
        return {'countries': len(q), 'positive_full': [pf_, sum(1 for r in q.values() if r['full'])],
                'positive_hold': [ph, sum(1 for r in q.values() if r['hold'])],
                'positive_hold_net_of_cost': [sum(1 for r in q.values() if r['hold_net_ok']), sum(1 for r in q.values() if r['hold'])],
                'developed_positive_hold': [sum(1 for c, r in q.items() if c in DEVELOPED and r['hold'] and r['hold']['ex'] > 0), sum(1 for c in q if c in DEVELOPED)],
                'emerging_positive_hold': [sum(1 for c, r in q.items() if c not in DEVELOPED and r['hold'] and r['hold']['ex'] > 0), sum(1 for c in q if c not in DEVELOPED)],
                'median_country_ex_hold': round(S.median(r['hold']['ex'] for r in q.values() if r['hold']), 2) if q else None}

    pooled = {}
    for k in FAM27:
        pm = {m: S.mean(v) for m, v in pooled_src[k].items()}
        pooled[k] = {'full': ts_stats(pm), 'train': ts_stats(pm, z=M.TRAIN_END), 'hold': ts_stats(pm, a=M.HOLD_START), 'recent': ts_stats(pm, a=M.RECENT_START)}

    # ── 地域・日本の系列
    RS = {loc: region_strats(loc) for loc in ('world_ex_us', 'world', 'developed', 'emerging')}
    RS['jpn'] = {k: CS['jpn'].get(k, {}) for k in FAM27}
    MK = {'world_ex_us': rmk['world_ex_us'], 'world': rmk['world'], 'developed': rmk['developed'], 'emerging': rmk['emerging'], 'jpn': cm['jpn']}

    fams = {'F2a_screened': ('world_ex_us', CHARS + ['blend_quality'], ()),
            'F2b_combos': ('world_ex_us', COMBOS, ()),
            'F2c_japan': ('jpn', FAM27, ('jpn',)),
            'F2d_world': ('world', FAM27, ())}
    families, tested, all_hold_p = {}, [], {f'primary:{k}': v for k, v in ctx['primary_hold_p'].items()}
    for fam, (loc, members, excl) in fams.items():
        recs = {k: evaluate(RS[loc].get(k, {}), MK[loc], k, loc) for k in members}
        hp = {k: (r.get('hold') or {}).get('p') for k, r in recs.items() if r.get('hold')}
        hol = M.holm(hp)
        for k, r in recs.items():
            cc = counts(k, excl)
            repl = {'regions': cc['positive_full'][1], 'positive': cc['positive_full'][0]}
            g, crit = M.grade(r.get('full'), r.get('train'), r.get('hold'), r.get('roll20'), cost_hold=r.get('hold_net'),
                              repl=repl, family_holm_p=hol.get(k))
            r.update({'grade': g, 'criteria': crit, 'holm_p': hol.get(k), 'repl': repl, 'countries': cc,
                      'pooled_countries': pooled[k] if not excl else None, 'coverage_diag': diag(loc, k, RS[loc].get(k, {}), MK[loc])})
            if r.get('hold') and r['hold'].get('p') is not None:
                all_hold_p[f'{fam}:{k}'] = r['hold']['p']
            tested.append({'name': f'{fam}:{k}', 'family': fam, 'series': f'{loc} の良い側 vs {loc} の vw 市場（被覆の規則つき）',
                           'description': DESC.get(k) or DESC2.get(k), 'grade': g, 'criteria': crit})
        families[fam] = {'series': loc, 'members': recs, 'holm': hol}

    reported = {}
    for loc in ('developed', 'emerging'):
        reported[loc] = {}
        for k in FAM27:
            r = evaluate(RS[loc].get(k, {}), MK[loc], k, loc)
            r['coverage_diag'] = diag(loc, k, RS[loc].get(k, {}), MK[loc])
            reported[loc][k] = r
            tested.append({'name': f'reported:{loc}:{k}', 'family': 'reported', 'series': f'{loc}（被覆の規則つき）', 'grade': None})
    sens = {}
    for lab, kw in (('start_1990_07_only', dict(use_R=False)), ('R_ge_0.6', dict(rthr=RTHR_HI))):
        rs = region_strats('world_ex_us', **kw)
        sens[lab] = {}
        for k in FAM27:
            r = evaluate(rs.get(k, {}), rmk['world_ex_us'], k, 'world_ex_us')
            sens[lab][k] = {w: r.get(w) for w in ('months', 'start', 'full', 'train', 'hold', 'hold_net', 'roll20', 'note') if w in r}
            tested.append({'name': f'sensitivity:{lab}:{k}', 'family': 'sensitivity', 'series': 'world_ex_us', 'grade': None})
    for k in FAM27:
        tested.append({'name': f'countries_screened:{k}', 'family': 'reported', 'series': f'米国外 {len(per[k])} か国それぞれ（被覆の規則つき）', 'grade': None})

    return {'prereg': f'out/{PRE2_NAME}', 'prereg_commit': git_sha(f'out/{PRE2_NAME}'), 'rule': {'start': START2, 'R_min': RTHR, 'n_min': N_MIN},
            'turnover': turn, 'families': families, 'reported': reported, 'sensitivity': sens,
            'countries': {k: {'counts_ex_us': counts(k), 'per_country': per[k]} for k in FAM27},
            'angle_wide_holm_reference': M.holm(all_hold_p), 'n_graded_angle': len(all_hold_p), 'tested': tested, '_all_hold_p': all_hold_p}


def print_prereg2(p2):
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.1f})" if v else '    —     '
    for fam, d in p2['families'].items():
        print(f"== {fam}（{d['series']}）")
        for k, r in d['members'].items():
            if 'full' not in r:
                print(f"{k:15} {r.get('grade')} {r.get('note')}"); continue
            cc = r['countries']; dg = r.get('coverage_diag') or {}
            print(f"{k:15} {r['grade']} {r['start']} 全{f(r['full'])} 訓{f(r['train'])} 保{f(r['hold'])} 近{f(r['recent'])} 費後{f(r['hold_net'])} "
                  f"20年{(r['roll20'] or {}).get('wins')}/{(r['roll20'] or {}).get('windows')} 国 全{cc['positive_full'][0]}/{cc['positive_full'][1]} "
                  f"保{cc['positive_hold'][0]}/{cc['positive_hold'][1]} holm {r['holm_p']} 診断 訓{dg.get('train')} 保{dg.get('hold')}")


# ───────────────────────── 事前登録3（out/mw_intl_prereg3.json） ─────────────────────────
PRE3_NAME = 'mw_intl_prereg3.json'
FR_REG = {'Developed_ex_US': ('Developed_ex_US', 'Developed_ex_US_3_Factors'), 'Europe': ('Europe', 'Europe_3_Factors'),
          'Japan': ('Japan', 'Japan_3_Factors'), 'Asia_Pacific_ex_Japan': ('Asia_Pacific_ex_Japan', 'Asia_Pacific_ex_Japan_3_Factors'),
          'Emerging_Markets': ('Emerging_Markets', 'Emerging_5_Factors'), 'Developed': ('Developed', 'Developed_3_Factors'),
          'North_America': ('North_America', 'North_America_3_Factors')}
FR_LEG = {'fr_value': ('ME_BE-ME', 'BIG HiBM'), 'fr_mom': ('ME_Prior_12_2', 'BIG HiPRIOR'), 'fr_prof': ('ME_OP', 'BIG HiOP'), 'fr_inv': ('ME_INV', 'BIG LoINV')}
FR_COMBO = {'fr_val_mom': ['fr_value', 'fr_mom'], 'fr_val_prof': ['fr_value', 'fr_prof'], 'fr_val_mom_prof': ['fr_value', 'fr_mom', 'fr_prof']}
FR_TURN = {'fr_value': 0.3, 'fr_mom': 1.5, 'fr_prof': 0.3, 'fr_inv': 0.4}
FR_DESC = {'fr_value': 'BIG HiBM（割安・大型株の上位30%）', 'fr_mom': 'BIG HiPRIOR（勢い）', 'fr_prof': 'BIG HiOP（収益性）', 'fr_inv': 'BIG LoINV（投資が控えめ）',
           'fr_val_mom': 'BIG HiBM 50%＋BIG HiPRIOR 50%', 'fr_val_prof': 'BIG HiBM 50%＋BIG HiOP 50%', 'fr_val_mom_prof': 'BIG HiBM・HiPRIOR・HiOP を1/3ずつ'}
ETF_PAIRS = [('EFV', 'EFA'), ('EFG', 'EFA'), ('IMTM', 'EFA'), ('IQLT', 'EFA'), ('IVLU', 'EFA'), ('INTF', 'EFA'), ('EFV+IMTM', 'EFA'), ('IVLU+IMTM', 'EFA'), ('EWJV', 'EWJ')]


def _fr_vw(name):
    return M.french_series(name, want='Average Value Weighted Returns -- Monthly')


def _fr_mkt(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols'] and 'RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(name)


def prereg3(ctx):
    rf, rmk, PF, side = ctx['rf'], ctx['rmk'], ctx['PF'], ctx['side']
    turn = dict(FR_TURN)
    for k, parts in FR_COMBO.items():
        turn[k] = round(S.mean(FR_TURN[q] for q in parts), 3)
    unit = lambda reg: 0.005 if reg == 'Emerging_Markets' else 0.003

    def series(reg):
        pre, fac = FR_REG[reg]
        mk = _fr_mkt(fac)
        legs = {}
        for k, (suf, col) in FR_LEG.items():
            try:
                legs[k] = _fr_vw(f'{pre}_6_Portfolios_{suf}')[col]
            except Exception as e:  # noqa
                legs[k] = {}
        for k, parts in FR_COMBO.items():
            if all(legs[q] for q in parts):
                ms = set.intersection(*[set(legs[q]) for q in parts])
                legs[k] = {m: S.mean(legs[q][m] for q in parts) for m in ms}
            else:
                legs[k] = {}
        return legs, mk

    def ev(g, mk, k, reg):
        ms = sorted(set(g) & set(mk))
        if len(ms) < 60:
            return {'months': len(ms), 'note': 'データ不足'}
        s = {m: g[m] for m in ms}; b = {m: mk[m] for m in ms}
        f = four(s, b)
        return {'months': len(ms), 'start': ms[0], 'end': ms[-1], **f,
                'hold_net': M.excess_stats(M.apply_cost(s, turn[k], unit(reg)), b, a=M.HOLD_START),
                'hold_net_2x': M.excess_stats(M.apply_cost(s, turn[k], unit(reg) * 2), b, a=M.HOLD_START),
                'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20), 'turnover': turn[k], 'unit_cost': unit(reg)}

    members = list(FR_LEG) + list(FR_COMBO)
    allreg = {}
    for reg in FR_REG:
        legs, mk = series(reg)
        allreg[reg] = {k: ev(legs[k], mk, k, reg) for k in members}
    # 検算: French の Developed_ex_US の市場と JKP world_ex_us の市場（総リターン）
    fx = _fr_mkt('Developed_ex_US_3_Factors'); jw = to_total(rmk['world_ex_us'], rf)
    ks = sorted(set(fx) & set(jw))
    check = {'french_dev_ex_us_vs_jkp_world_ex_us_mkt_corr': round(M.corr([fx[k] for k in ks], [jw[k] for k in ks]), 4),
             'french_mean': round(S.mean(fx[k] for k in ks) * 1200, 2), 'jkp_mean': round(S.mean(jw[k] for k in ks) * 1200, 2), 'from': ks[0], 'to': ks[-1]}

    rep = allreg['Developed_ex_US']
    hp = {k: (r.get('hold') or {}).get('p') for k, r in rep.items() if r.get('hold')}
    hol = M.holm(hp)
    tested, graded = [], {}
    C5R = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Emerging_Markets']
    for k in members:
        r = rep[k]
        pos = sum(1 for reg in C5R if (allreg[reg][k].get('full') or {}).get('ex_ann', -1) > 0)
        nreg = sum(1 for reg in C5R if allreg[reg][k].get('full'))
        repl = {'regions': nreg, 'positive': pos}
        posh = sum(1 for reg in C5R if (allreg[reg][k].get('hold') or {}).get('ex_ann', -1) > 0)
        g, crit = M.grade(r.get('full'), r.get('train'), r.get('hold'), r.get('roll20'), cost_hold=r.get('hold_net'), repl=repl, family_holm_p=hol.get(k))
        graded[k] = {'grade': g, 'criteria': crit, 'holm_p': hol.get(k), 'repl': repl, 'repl_hold_reported': {'regions': nreg, 'positive': posh}}
        tested.append({'name': f'F3a_french_dev_ex_us:{k}', 'family': 'F3a_french_dev_ex_us', 'series': 'French Developed ex US 大型株 vs 同地域の市場',
                       'description': FR_DESC[k], 'grade': g, 'criteria': crit})
    for reg in FR_REG:
        if reg == 'Developed_ex_US':
            continue
        for k in members:
            tested.append({'name': f'french_reported:{reg}:{k}', 'family': 'reported', 'series': f'French {reg}', 'grade': None})

    # ETF の現実の確認（判定しない）
    etf = {}
    for a, b in ETF_PAIRS:
        try:
            if '+' in a:
                x, y = a.split('+'); rx, ry = M.yahoo(x), M.yahoo(y)
                ms = set(rx) & set(ry)
                ra = {m: (rx[m] + ry[m]) / 2 for m in ms}
            else:
                ra = M.yahoo(a)
            rb = M.yahoo(b)
            ks = sorted(set(ra) & set(rb))
            ks = [k for k in ks if k < int(__import__('datetime').date.today().strftime('%Y%m'))]  # 途中の月を除く
            sa, sb = {k: ra[k] for k in ks}, {k: rb[k] for k in ks}
            etf[f'{a} vs {b}'] = {'full': M.excess_stats(sa, sb), 'hold_2013_07': M.excess_stats(sa, sb, a=M.RECENT_START)}
        except Exception as e:  # noqa
            etf[f'{a} vs {b}'] = {'error': str(e)[:200]}
        tested.append({'name': f'etf:{a} vs {b}', 'family': 'reported_etf', 'series': 'Yahoo 調整後終値（生き残りの偏りあり）', 'grade': None})

    # 米国の組み合わせ（JKP usa・vw・判定しない）
    def gs(k):
        pf = PF.get(('usa', k))
        return {m: r for m, (r, n) in pf[side[k]].items() if n >= N_MIN} if pf else {}
    base = {k: gs(k) for k in CHARS}

    def mix(parts):
        if not all(parts):
            return {}
        ms = set.intersection(*[set(q) for q in parts])
        return {m: S.mean(q[m] for q in parts) for m in ms}
    bq = mix([base[k] for k in QUALITY]); vc = mix([base[k] for k in VALUE4]); mo = base['ret_12_1']
    usc = {'value_composite': vc, 'val_mom': mix([vc, mo]), 'val_qual': mix([vc, bq]), 'qual_mom': mix([bq, mo]),
           'val_mom_qual': mix([vc, mo, bq]), 'all20': mix([base[k] for k in CHARS])}
    us = {}
    mk = rmk['usa']
    for k, g in usc.items():
        ms = sorted(set(g) & set(mk) & set(rf))
        if len(ms) < 60:
            us[k] = {'months': len(ms)}; continue
        sa = to_total({m: g[m] for m in ms}, rf); sb = to_total({m: mk[m] for m in ms}, rf)
        us[k] = {'start': ms[0], **four(sa, sb), 'roll20': M.rolling(sa, sb, 20)}
        tested.append({'name': f'us_combo:{k}', 'family': 'reported_us', 'series': 'JKP usa vw（良い側を決めた国）', 'grade': None})

    all_p = dict(ctx['all_hold_p'])
    for k, r in rep.items():
        if r.get('hold') and r['hold'].get('p') is not None:
            all_p[f'F3a_french_dev_ex_us:{k}'] = r['hold']['p']
    return {'prereg': f'out/{PRE3_NAME}', 'prereg_commit': git_sha(f'out/{PRE3_NAME}'), 'check': check,
            'families': {'F3a_french_dev_ex_us': {'members': {k: dict(rep[k], **graded[k]) for k in members}, 'holm': hol}},
            'french_regions': {reg: d for reg, d in allreg.items() if reg != 'Developed_ex_US'},
            'etf_reality_check': etf, 'us_combos': us, 'angle_wide_holm_reference': M.holm(all_p), 'n_graded_angle': len(all_p), 'tested': tested, '_all_hold_p': all_p}


def print_prereg3(p3):
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.1f})" if v else '    —     '
    print('== F3a（French Developed ex US）', p3['check'])
    for k, r in p3['families']['F3a_french_dev_ex_us']['members'].items():
        if 'full' not in r:
            print(k, r.get('grade'), r.get('note')); continue
        print(f"{k:16} {r['grade']} {r['start']} 全{f(r['full'])} 訓{f(r['train'])} 保{f(r['hold'])} 近{f(r['recent'])} 費後{f(r['hold_net'])} "
              f"20年{(r['roll20'] or {}).get('wins')}/{(r['roll20'] or {}).get('windows')} 地域 全{r['repl']['positive']}/{r['repl']['regions']} "
              f"保{r['repl_hold_reported']['positive']}/{r['repl_hold_reported']['regions']} holm {r['holm_p']} te {r['hold']['te']}")
    for reg, d in p3['french_regions'].items():
        print(' ', reg, ' '.join(f"{k}:{d[k]['full']['ex_ann']:+.1f}/{d[k]['hold']['ex_ann']:+.1f}(t{d[k]['hold']['t']:+.1f})" for k in d if d[k].get('full') and d[k].get('hold')))
    for k, v in p3['etf_reality_check'].items():
        print('  ETF', k, f(v.get('full')), v.get('full') and (v['full']['from'], v['full']['cagr_diff']), 'error' in v and v['error'])
    for k, v in p3['us_combos'].items():
        print('  US', k, v.get('start'), '全', f(v.get('full')), '訓', f(v.get('train')), '保', f(v.get('hold')), '20年', (v.get('roll20') or {}).get('wins'), (v.get('roll20') or {}).get('windows'))
    ah = p3['angle_wide_holm_reference']
    print('  angle-wide holm <0.05 (n=%d):' % p3['n_graded_angle'], {k: v for k, v in sorted(ah.items(), key=lambda x: x[1]) if v < 0.05})

# ───────────────────────── 事前登録4（out/mw_intl_prereg4.json） ─────────────────────────
PRE4_NAME = 'mw_intl_prereg4.json'
F4_COLS = ['Mkt', 'BM_H', 'BM_L', 'EP_H', 'EP_L', 'CEP_H', 'CEP_L', 'DP_H', 'DP_L', 'Zero']
F4_MEM = {'f4_bm': ['BM_H'], 'f4_ep': ['EP_H'], 'f4_cep': ['CEP_H'], 'f4_dp': ['DP_H'], 'f4_value4': ['BM_H', 'EP_H', 'CEP_H', 'DP_H']}
F4_DESC = {'f4_bm': 'B/M 上位30%（国の中で並べる）', 'f4_ep': 'E/P 上位30%', 'f4_cep': 'CE/P 上位30%', 'f4_dp': '配当利回り 上位30%', 'f4_value4': '割安4本を等分'}


def _f4_read(zipname):
    """French の国際 .Dat（zip）→ {ファイル名: {列: {ym: 小数}}}。最初の表（米ドル・All 4 Not Reqd）だけ"""
    b = M.get(f'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{zipname}.zip', name=f'fr_{zipname}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = {}
    for nm in z.namelist():
        txt = z.read(nm).decode('latin-1').splitlines()
        cols = {c: {} for c in F4_COLS}
        started = False
        for line in txt:
            parts = line.split()
            if not started:
                if parts[:3] == ['Mkt', 'High', 'Low']:
                    started = True
                continue
            if not parts:
                break
            if not parts[0].isdigit() or len(parts[0]) != 6:
                break
            ym = int(parts[0])
            for c, v in zip(F4_COLS, parts[1:]):
                x = float(v)
                if x > -99.9:
                    cols[c][ym] = x / 100
        out[nm.rsplit('.', 1)[0]] = cols
    return out


def prereg4(ctx):
    C = _f4_read('F-F_International_Countries'); I_ = _f4_read('F-F_International_Indices')
    unit, turn = 0.003, 0.3

    def strat(cols, k):
        parts = [cols[c] for c in F4_MEM[k]]
        if not all(parts):
            return {}
        ms = set.intersection(*[set(q) for q in parts])
        return {m: S.mean(q[m] for q in parts) for m in ms}

    def ev(cols, k):
        g, mk = strat(cols, k), cols['Mkt']
        ms = sorted(set(g) & set(mk))
        if len(ms) < 60:
            return {'months': len(ms), 'note': 'データ不足'}
        s_, b_ = {m: g[m] for m in ms}, {m: mk[m] for m in ms}
        return {'months': len(ms), 'start': ms[0], 'end': ms[-1], **four(s_, b_),
                'hold_net': M.excess_stats(M.apply_cost(s_, turn, unit), b_, a=M.HOLD_START),
                'hold_net_2x': M.excess_stats(M.apply_cost(s_, turn, unit * 2), b_, a=M.HOLD_START),
                'roll20': M.rolling(s_, b_, 20), 'dca20': M.dca(s_, b_, 20), 'turnover': turn, 'unit_cost': unit}

    cty = {c: {k: ev(cols, k) for k in F4_MEM} for c, cols in C.items()}
    idx = {c: {k: ev(cols, k) for k in F4_MEM} for c, cols in I_.items()}
    fams = {'F4a_eafe_value': (idx['Ind_all'], ()), 'F4b_japan_value': (cty['Japan'], ('Japan',))}
    families, tested, all_p = {}, [], dict(ctx['all_hold_p'])
    for fam, (rep, excl) in fams.items():
        hp = {k: (r.get('hold') or {}).get('p') for k, r in rep.items() if r.get('hold')}
        hol = M.holm(hp)
        mem = {}
        for k, r in rep.items():
            q = {c: d[k] for c, d in cty.items() if c not in excl and d[k].get('months', 0) >= MIN_MONTHS and d[k].get('full')}
            repl = {'regions': len(q), 'positive': sum(1 for v in q.values() if v['full']['ex_ann'] > 0)}
            repl_h = {'regions': sum(1 for v in q.values() if v.get('hold')), 'positive': sum(1 for v in q.values() if v.get('hold') and v['hold']['ex_ann'] > 0)}
            g, crit = M.grade(r.get('full'), r.get('train'), r.get('hold'), r.get('roll20'), cost_hold=r.get('hold_net'), repl=repl, family_holm_p=hol.get(k))
            mem[k] = dict(r, grade=g, criteria=crit, holm_p=hol.get(k), repl=repl, repl_hold_reported=repl_h)
            if r.get('hold') and r['hold'].get('p') is not None:
                all_p[f'{fam}:{k}'] = r['hold']['p']
            tested.append({'name': f'{fam}:{k}', 'family': fam, 'series': 'French 国際（MSCI→Bloomberg）国の中で並べた割安 上位30% vs 市場',
                           'description': F4_DESC[k], 'grade': g, 'criteria': crit})
        families[fam] = {'members': mem, 'holm': hol}
    for c in cty:
        for k in F4_MEM:
            tested.append({'name': f'f4_country:{c}:{k}', 'family': 'reported', 'series': f'French 国別 {c}', 'grade': None})
    for c in idx:
        if c != 'Ind_all':
            for k in F4_MEM:
                tested.append({'name': f'f4_index:{c}:{k}', 'family': 'reported', 'series': f'French 指数 {c}', 'grade': None})
    compactc = {c: {k: {w: compact(v.get(w)) for w in ('full', 'train', 'hold')} | {'months': v.get('months'), 'start': v.get('start')} for k, v in d.items()} for c, d in cty.items()}
    return {'prereg': f'out/{PRE4_NAME}', 'prereg_commit': git_sha(f'out/{PRE4_NAME}'), 'families': families,
            'indices_reported': {c: d for c, d in idx.items() if c != 'Ind_all'}, 'countries': compactc,
            'angle_wide_holm_reference': M.holm(all_p), 'n_graded_angle': len(all_p), 'tested': tested, '_all_hold_p': all_p}


def print_prereg4(p4):
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.1f})" if v else '    —     '
    for fam, d in p4['families'].items():
        print('==', fam)
        for k, r in d['members'].items():
            if 'full' not in r:
                print(k, r.get('grade'), r.get('note')); continue
            print(f"{k:10} {r['grade']} {r['start']} 全{f(r['full'])} 訓{f(r['train'])} 保{f(r['hold'])} 近{f(r['recent'])} 費後{f(r['hold_net'])} "
                  f"20年{(r['roll20'] or {}).get('wins')}/{(r['roll20'] or {}).get('windows')} 国 全{r['repl']['positive']}/{r['repl']['regions']} "
                  f"保{r['repl_hold_reported']['positive']}/{r['repl_hold_reported']['regions']} holm {r['holm_p']} te {r['hold']['te']}")
    for c, d in p4['indices_reported'].items():
        print(' ', c, ' '.join(f"{k}:{d[k]['full']['ex_ann']:+.1f}/{d[k]['hold']['ex_ann']:+.1f}(t{d[k]['hold']['t']:+.1f})" for k in d if d[k].get('full')))
    ah = p4['angle_wide_holm_reference']
    print('  angle-wide holm <0.05 (n=%d):' % p4['n_graded_angle'], {k: v for k, v in sorted(ah.items(), key=lambda x: x[1]) if v < 0.05})


# ───────────────────────── 事前登録5（out/mw_intl_prereg5.json） ─────────────────────────
PRE5_NAME = 'mw_intl_prereg5.json'
F5_PAIRS = {'dfa_intl_value': ('DFIVX', 'DFALX'), 'dfa_em_value': ('DFEVX', 'DFEMX'), 'dfa_intl_small_value': ('DISVX', 'DFISX'), 'dfa_intl_core': ('DFIEX', 'DFALX')}


def prereg5(ctx):
    cur = int(datetime_today().strftime('%Y%m'))
    Y = {}

    def y(t):
        if t not in Y:
            Y[t] = {k: v for k, v in M.yahoo(t).items() if k < cur}
        return Y[t]
    recs = {}
    for k, (a, b) in F5_PAIRS.items():
        ra, rb = y(a), y(b)
        ks = sorted(set(ra) & set(rb))
        s_, b_ = {m: ra[m] for m in ks}, {m: rb[m] for m in ks}
        f = four(s_, b_)
        recs[k] = {'pair': f'{a} vs {b}', 'months': len(ks), 'start': ks[0], 'end': ks[-1], **f, 'hold_net': f['hold'],
                   'roll20': M.rolling(s_, b_, 20), 'dca20': M.dca(s_, b_, 20)}
    hp = {k: (r.get('hold') or {}).get('p') for k, r in recs.items() if r.get('hold')}
    hol = M.holm(hp)
    vals = ['dfa_intl_value', 'dfa_em_value', 'dfa_intl_small_value']
    repl = {'regions': sum(1 for k in vals if recs[k].get('full')), 'positive': sum(1 for k in vals if (recs[k].get('full') or {}).get('ex_ann', -1) > 0)}
    tested, all_p = [], dict(ctx['all_hold_p'])
    for k, r in recs.items():
        g, crit = M.grade(r.get('full'), r.get('train'), r.get('hold'), r.get('roll20'), cost_hold=r.get('hold_net'), repl=repl, family_holm_p=hol.get(k))
        r.update(grade=g, criteria=crit, holm_p=hol.get(k), repl=repl)
        if r.get('hold') and r['hold'].get('p') is not None:
            all_p[f'F5a_dfa_funds:{k}'] = r['hold']['p']
        tested.append({'name': f'F5a_dfa_funds:{k}', 'family': 'F5a_dfa_funds', 'series': r['pair'] + '（Yahoo・費用後・生き残りの偏りあり）', 'grade': g, 'criteria': crit})
    rep = {}
    for a, b in (('DFALX', 'EFA'), ('DFIVX', 'EFA')):
        ra, rb = y(a), y(b); ks = sorted(set(ra) & set(rb))
        st = M.excess_stats({m: ra[m] for m in ks}, {m: rb[m] for m in ks})
        rep[f'{a} vs {b}'] = dict(st or {}, corr=round(M.corr([ra[m] for m in ks], [rb[m] for m in ks]), 4))
        tested.append({'name': f'f5_reported:{a} vs {b}', 'family': 'reported', 'series': 'Yahoo', 'grade': None})
    return {'prereg': f'out/{PRE5_NAME}', 'prereg_commit': git_sha(f'out/{PRE5_NAME}'), 'families': {'F5a_dfa_funds': {'members': recs, 'holm': hol}},
            'reported': rep, 'angle_wide_holm_reference': M.holm(all_p), 'n_graded_angle': len(all_p), 'tested': tested}


def datetime_today():
    import datetime as _d
    return _d.date.today()


def print_prereg5(p5):
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.1f})" if v else '    —     '
    print('== F5a_dfa_funds')
    for k, r in p5['families']['F5a_dfa_funds']['members'].items():
        print(f"{k:22} {r['grade']} {r['pair']} {r['start']} 全{f(r.get('full'))} 訓{f(r.get('train'))} 保{f(r.get('hold'))} 近{f(r.get('recent'))} "
              f"cagr差 全{(r.get('full') or {}).get('cagr_diff')} 保{(r.get('hold') or {}).get('cagr_diff')} 20年{(r.get('roll20') or {}).get('wins')}/{(r.get('roll20') or {}).get('windows')} holm {r['holm_p']}")
    for k, v in p5['reported'].items():
        print('  ', k, f(v if 'ex_ann' in v else None), 'cagr', v.get('cagr_s'), v.get('cagr_b'), 'corr', v.get('corr'))
    ah = p5['angle_wide_holm_reference']
    print('  angle-wide holm <0.05 (n=%d):' % p5['n_graded_angle'], {k: v for k, v in sorted(ah.items(), key=lambda x: x[1]) if v < 0.05})



# ───────────────────────── 事後の診断（結果を見た後に足した・判定しない） ─────────────────────────
def post_hoc(ctx, p2, p3):
    """事後: JKP と French の差の出どころ・保有期間の前後半・年ごと・相対の最大下落。判定には使わない"""
    rf, rmk, PF, side, cm, cand = ctx['rf'], ctx['rmk'], ctx['PF'], ctx['side'], ctx['cm'], ctx['cand']
    out = {'label': '事後（結果を見た後に足した診断・判定には使わない）'}
    cn = country_nstocks()
    exus = collections.Counter()
    for loc, d in cn.items():
        if loc != 'usa':
            for m, n in d.items():
                exus[m] += n

    def scr(loc, k, den):
        pf = PF.get((loc, k))
        if not pf:
            return {}
        o = {}
        for m, (r, n) in pf[side[k]].items():
            if n < N_MIN or m < START2 or not den.get(m):
                continue
            if sum(pf[q][m][1] for q in pf if m in pf[q]) / den[m] >= RTHR:
                o[m] = r
        return o

    def mix(parts):
        if not all(parts):
            return {}
        ms = set.intersection(*[set(q) for q in parts])
        return {m: S.mean(q[m] for q in parts) for m in ms}

    def rel_dd(s, b):
        w, pk, dd, at = 1.0, 1.0, 0.0, None
        for k in sorted(set(s) & set(b)):
            w *= (1 + s[k]) / (1 + b[k]); pk = max(pk, w)
            if w / pk - 1 < dd:
                dd, at = w / pk - 1, k
        return round(dd * 100, 1), at

    def yearly(s, b, a=M.HOLD_START):
        yr = collections.defaultdict(lambda: [1.0, 1.0])
        for k in sorted(set(s) & set(b)):
            if k >= a:
                yr[k // 100][0] *= 1 + s[k]; yr[k // 100][1] *= 1 + b[k]
        return {y: round((v[0] - v[1]) * 100, 1) for y, v in sorted(yr.items())}

    wx = {k: scr('world_ex_us', k, exus) for k in CHARS}
    vm = mix([mix([wx[k] for k in VALUE4]), wx['ret_12_1']])
    mk = rmk['world_ex_us']
    ms = sorted(set(vm) & set(mk) & set(rf))
    s = to_total({m: vm[m] for m in ms}, rf); b = to_total({m: mk[m] for m in ms}, rf)
    out['jkp_world_ex_us_val_mom'] = {'hold_2007_2015': M.excess_stats(s, b, a=200701, z=201512), 'hold_2016_2025': M.excess_stats(s, b, a=201601),
                                      'yearly_hold': yearly(s, b), 'relative_max_drawdown_hold': rel_dd({k: s[k] for k in s if k >= M.HOLD_START}, b),
                                      'relative_max_drawdown_full': rel_dd(s, b)}
    one = mix([wx['be_me'], wx['ret_12_1']])
    ms1 = sorted(set(one) & set(mk) & set(rf))
    s1 = to_total({m: one[m] for m in ms1}, rf); b1 = to_total({m: mk[m] for m in ms1}, rf)
    out['jkp_world_ex_us_bm_plus_mom_single_measure'] = {'why': 'French と同じ B/M だけの割安で作ると（割安4本の平均との差を見る）', **four(s1, b1)}
    # 国の群ごとの単純平均（先進国・新興国）
    grp = {'developed_ex_us': [c for c in cand if c in DEVELOPED], 'emerging_and_other': [c for c in cand if c not in DEVELOPED]}
    for g, cs in grp.items():
        pool = collections.defaultdict(list)
        for c in cs:
            base = {k: scr(c, k, cn.get(c, {})) for k in VALUE4 + ['ret_12_1'] if PF.get((c, k))}
            vv = [base[k] for k in VALUE4 if k in base and base[k]]
            if len(vv) < 2 or not base.get('ret_12_1'):
                continue
            vc = {}
            for m in set().union(*[set(v) for v in vv]):
                x = [v[m] for v in vv if m in v]
                if len(x) >= 2:
                    vc[m] = S.mean(x)
            v2 = mix([vc, base['ret_12_1']])
            mm = sorted(set(v2) & set(cm[c]) & set(rf))
            if len(mm) < MIN_MONTHS:
                continue
            for m in mm:
                pool[m].append(v2[m] - cm[c][m])
        pm = {m: S.mean(v) for m, v in pool.items()}
        out[f'val_mom_equal_weight_countries_{g}'] = {'countries': len(cs), 'full': ts_stats(pm), 'train': ts_stats(pm, z=M.TRAIN_END), 'hold': ts_stats(pm, a=M.HOLD_START)}
    # French の val_mom（Developed ex US）の前後半・年ごと
    fx = _fr_mkt('Developed_ex_US_3_Factors')
    hb = _fr_vw('Developed_ex_US_6_Portfolios_ME_BE-ME')['BIG HiBM']; hp = _fr_vw('Developed_ex_US_6_Portfolios_ME_Prior_12_2')['BIG HiPRIOR']
    fv = mix([hb, hp]); ms2 = sorted(set(fv) & set(fx))
    s2 = {m: fv[m] for m in ms2}; b2 = {m: fx[m] for m in ms2}
    out['french_dev_ex_us_val_mom'] = {'hold_2007_2015': M.excess_stats(s2, b2, a=200701, z=201512), 'hold_2016_2026': M.excess_stats(s2, b2, a=201601),
                                       'yearly_hold': yearly(s2, b2), 'relative_max_drawdown_hold': rel_dd({k: s2[k] for k in s2 if k >= M.HOLD_START}, b2)}
    # 日本の割安（JKP be_me）の相対の最大下落・年ごと
    jb = scr('jpn', 'be_me', cn.get('jpn', {}))
    ms3 = sorted(set(jb) & set(cm['jpn']) & set(rf))
    s3 = to_total({m: jb[m] for m in ms3}, rf); b3 = to_total({m: cm['jpn'][m] for m in ms3}, rf)
    out['jkp_japan_be_me'] = {'yearly_hold': yearly(s3, b3), 'relative_max_drawdown_full': rel_dd(s3, b3),
                              'hold_2007_2015': M.excess_stats(s3, b3, a=200701, z=201512), 'hold_2016_2025': M.excess_stats(s3, b3, a=201601)}
    return out



if __name__ == '__main__':
    main()
