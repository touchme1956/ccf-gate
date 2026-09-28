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

    out = {'tool': 'night/mw_intl.py', 'prereg': f'out/{PRE_NAME}', 'prereg_commit': git_sha(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'representative': REP, 'good_side': side,
           'n_tested': len(tested), 'tested': tested, 'graded': graded, 'holm_family': hol,
           'regional': {loc: {k: v for k, v in d.items()} for loc, d in regional.items()},
           'country_summary': summary, 'per_country': per_country, 'sanity': sanity}
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
    print('→', p)


if __name__ == '__main__':
    main()
