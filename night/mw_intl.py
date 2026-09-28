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

    out = {'tool': 'night/mw_intl.py', 'prereg': f'out/{PRE_NAME}', 'prereg_commit': git_sha(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'representative': REP, 'good_side': side,
           'n_tested': len(tested), 'tested': tested, 'graded': graded, 'holm_family': hol,
           'regional': {loc: {k: v for k, v in d.items()} for loc, d in regional.items()},
           'country_summary': summary, 'per_country': per_country, 'sanity': sanity, 'prereg2': p2}
    out['n_tested_all'] = len(tested) + len(p2['tested'])
    p = M.save('mw_intl.json', out)
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
            'angle_wide_holm_reference': M.holm(all_hold_p), 'n_graded_angle': len(all_hold_p), 'tested': tested}


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



if __name__ == '__main__':
    main()
