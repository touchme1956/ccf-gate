#!/usr/bin/env python3
"""night/mw_factor_us.py — 角度 factor_us: 米国の『一つの特性で良い側だけを買う』を純粋な時価加重の市場と比べる（読むだけ・門には不使用）

事前登録: out/mw_factor_us_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を mw_common.grade でそのまま当てる。
出力: out/mw_factor_us.json（試した全部を tested に残す＝多重検定の数）

族
  a  JKP usa の153特性・上限なし時価加重(vw)の三分位の良い側（良い側は訓練期間だけで jkp_good_side が決める）
  b  French の単一ソート（時価加重）の理論の良い側・十分位と上位30%（または五分位）
  c  French の大型株版（25分割の最大五分位・6分割の大・32分割の大・100分割の最大十分位）
  d  訓練期間だけで選んだ合成（d1: a の C1 合格の等分／d2: c の単一特性で C1 合格の等分）
相手: French Mkt-RF（超過どうし）。転がる20年窓と積立は総リターンどうし（超過＋French RF 対 French Mkt）。
"""
import sys, os, json, math, subprocess, statistics as S
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PRE_NAME = 'mw_factor_us_prereg.json'
PRE = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
OUT_NAME = 'mw_factor_us.json'
NMIN = 10          # 良い側の三分位の銘柄数がこれ未満の月は除く（事前登録）
COMP_MIN = 5       # 合成は構成要素が5本以上ある月だけ（事前登録）

FF = M.ff_factors()
MKTRF, RF, MKT = FF['mktrf'], FF['rf'], FF['mkt']
JKPMKT = M.jkp_mkt('usa', 'vw')


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


# ───────────────────────── データ ─────────────────────────
def jkp_tercile(region, key, side):
    """JKP の vw 三分位（超過）。良い側の銘柄数 n<NMIN の月は除く（0で埋めない）"""
    out = {}
    for x in M.jkp_rows(region, key, 'portfolios', 'vw'):
        if x['pf'] != side or x['ret'] in ('', 'NA', 'na'):
            continue
        n = x.get('n')
        if n not in (None, '', 'NA', 'na') and float(n) < NMIN:
            continue
        out[M._ym(x['date'])] = float(x['ret'])
    return out


_FS = {}
def fr_cols(name):
    """French ファイルの時価加重月次表 → {列: {yyyymm: 小数総リターン}}"""
    if name not in _FS:
        _FS[name] = M.french_series(name, want='Value Weight')
    return _FS[name]


_FF_REG = {}
def fr_region_factors(region):
    name = 'Emerging_5_Factors' if region == 'Emerging_Markets' else f'{region}_3_Factors'
    if name not in _FF_REG:
        for t, v in M.french_tables(name).items():
            if v['freq'] == 'monthly':
                cols = v['cols']
                i_m, i_rf = cols.index('Mkt-RF'), cols.index('RF')
                mk, rf = {}, {}
                for d, row in v['data'].items():
                    if row[i_m] is not None and row[i_rf] is not None:
                        mk[d] = row[i_m] / 100; rf[d] = row[i_rf] / 100
                _FF_REG[name] = (mk, rf)
                break
    return _FF_REG[name]


def ew(series_list, min_n=1):
    """毎月、その月にデータがある系列の平均（min_n 本未満の月は使わない）"""
    ks = sorted(set().union(*[set(s) for s in series_list])) if series_list else []
    out = {}
    for k in ks:
        v = [s[k] for s in series_list if k in s]
        if len(v) >= min_n:
            out[k] = sum(v) / len(v)
    return out


def to_excess(tot, rf=RF):
    return {k: v - rf[k] for k, v in tot.items() if k in rf}


# ───────────────────────── 測定 ─────────────────────────
def evaluate(s_ex, turnover_pct, cost_unit, pub_year=None):
    r = {}
    r['full'] = M.excess_stats(s_ex, MKTRF)
    tr = M.excess_stats(s_ex, MKTRF, z=M.TRAIN_END)
    r['train'] = tr
    r['train_len_ok'] = bool(tr and tr['years'] >= 15)
    r['hold'] = M.excess_stats(s_ex, MKTRF, a=M.HOLD_START)
    r['recent'] = M.excess_stats(s_ex, MKTRF, a=M.RECENT_START)
    net = M.apply_cost(s_ex, turnover_pct / 100, cost_unit)
    r['cost'] = {'turnover_pct': turnover_pct, 'cost_per_100pct': cost_unit, 'drag_pct_per_year': round(turnover_pct / 100 * cost_unit * 100, 3)}
    r['net_hold'] = M.excess_stats(net, MKTRF, a=M.HOLD_START)
    r['net_full'] = M.excess_stats(net, MKTRF)
    tot = {k: v + RF[k] for k, v in s_ex.items() if k in RF}
    r['roll20'] = M.rolling(tot, MKT, 20)
    r['roll10'] = M.rolling(tot, MKT, 10)
    r['dca20'] = M.dca(tot, MKT, 20)
    r['vs_jkp_mkt_vw'] = {'full': M.excess_stats(s_ex, JKPMKT), 'hold': M.excess_stats(s_ex, JKPMKT, a=M.HOLD_START)}
    if pub_year:
        r['post_pub'] = {'from_year': pub_year + 1, 'stats': M.excess_stats(s_ex, MKTRF, a=(pub_year + 1) * 100 + 1)}
    return r


def repl_jkp(key_sides, regions=('developed', 'emerging'), info_regions=('jpn',)):
    """JKP 地域で同じ良い側（合成なら構成要素の平均）を当てる。無い地域は『正でない』に数える"""
    out, pos = {}, 0
    for reg in tuple(regions) + tuple(info_regions):
        try:
            parts = [jkp_tercile(reg, k, sd) for k, sd in key_sides]
            parts = [p for p in parts if p]
            s = parts[0] if len(key_sides) == 1 and parts else (ew(parts, COMP_MIN) if parts else {})
            b = M.jkp_mkt(reg, 'vw')
            st_full = M.excess_stats(s, b) if s else None
            st_hold = M.excess_stats(s, b, a=M.HOLD_START) if s else None
        except Exception as e:  # noqa
            st_full, st_hold = None, None
            out[reg] = {'error': str(e)[:120]}
        ok = bool(st_full and st_full['ex_ann'] > 0)
        out[reg] = dict(out.get(reg, {}), full=st_full, hold=st_hold, positive=ok, counted=reg in regions)
        if reg in regions and ok:
            pos += 1
    return {'regions': len(regions), 'positive': pos, 'detail': out}


def repl_french(spec):
    """French の地域ファイルで同じ作り方を当てる。無い／読めない地域は『正でない』"""
    out, pos = {}, 0
    for reg in spec['regions']:
        name = f"{reg}_{spec['file_suffix']}"
        try:
            cols = fr_cols(name)
            tot = cols[spec['col']]
            mk, rf = fr_region_factors(reg)
            ex = {k: v - rf[k] for k, v in tot.items() if k in rf}
            st_full = M.excess_stats(ex, mk); st_hold = M.excess_stats(ex, mk, a=M.HOLD_START)
            ok = bool(st_full and st_full['ex_ann'] > 0)
            out[reg] = {'file': name, 'full': st_full, 'hold': st_hold, 'positive': ok}
        except Exception as e:  # noqa
            ok = False
            out[reg] = {'file': name, 'error': str(e)[:160], 'positive': False}
        pos += ok
    return {'regions': len(spec['regions']), 'positive': pos, 'detail': out}


def c1(r):
    t = r['train']
    return bool(r['train_len_ok'] and t and t['ex_ann'] > 0 and (t['t'] or 0) >= 2.0)


def prefetch(jobs):
    def run(j):
        try:
            M.jkp_rows(*j) if j[0] != 'fr' else M.french_tables(j[1])
        except Exception:
            pass
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(run, jobs))


# ───────────────────────── 本体 ─────────────────────────
def main():
    fam = PRE['families']
    tested = []
    # 先にまとめて取りに行く（キャッシュを温めるだけ）
    a_keys = [x['key'] for x in fam['a_jkp_tercile_vw']['list']]
    jobs = []
    for k in a_keys:
        jobs += [('usa', k, 'portfolios', 'vw'), ('usa', k, 'factor', 'vw'), ('developed', k, 'portfolios', 'vw'),
                 ('emerging', k, 'portfolios', 'vw'), ('jpn', k, 'portfolios', 'vw')]
    jobs += [('developed', 'mkt', 'factor', 'vw'), ('emerging', 'mkt', 'factor', 'vw'), ('jpn', 'mkt', 'factor', 'vw')]
    frn = {x['file'] for x in fam['b_french_single_sort_vw']['list']} | {x['file'] for x in fam['c_french_largecap']['list']}
    for x in fam['c_french_largecap']['list']:
        if x['repl']:
            for reg in x['repl']['regions']:
                frn.add(f"{reg}_{x['repl']['file_suffix']}")
                frn.add('Emerging_5_Factors' if reg == 'Emerging_Markets' else f'{reg}_3_Factors')
    jobs += [('fr', n) for n in sorted(frn)]
    print('prefetch', len(jobs), flush=True)
    prefetch(jobs)

    # ── sanity
    sanity = {
        'french_mkt_cagr_full': round(M.cagr(MKT) * 100, 2), 'french_mkt_from_to': [min(MKT), max(MKT)],
        'french_mkt_cagr_2007': round(M.cagr(M.window(MKT, M.HOLD_START)) * 100, 2),
        'jkp_mkt_vw_vs_french_mktrf': {'full': M.excess_stats(JKPMKT, MKTRF), 'hold': M.excess_stats(JKPMKT, MKTRF, a=M.HOLD_START),
                                       'recent': M.excess_stats(JKPMKT, MKTRF, a=M.RECENT_START)},
    }
    print('sanity', json.dumps({k: v for k, v in sanity.items() if k != 'jkp_mkt_vw_vs_french_mktrf'}), flush=True)

    # ── a
    a_res, a_side, a_series = {}, {}, {}
    for spec in fam['a_jkp_tercile_vw']['list']:
        k = spec['key']
        side, _ = M.jkp_good_side('usa', k, 'vw', upto=M.TRAIN_END)
        ent = {'name': f'a_{k}', 'family': 'a', 'primary': True, 'key': k, 'cluster': spec['cluster'], 'cite': spec['cite'],
               'description': f"JKP usa {k}（{spec['cluster']}）vw 三分位の良い側"}
        if side is None:
            ent['status'] = '訓練データが24ヶ月未満で良い側を決められない（評価しない）'
            tested.append(ent); continue
        s = jkp_tercile('usa', k, side)
        a_side[k], a_series[k] = side, s
        ent.update({'good_side': side, 'jkp_direction': spec['jkp_direction'],
                    'side_matches_direction': (spec['jkp_direction'] is None) or ((side == '3.0') == (spec['jkp_direction'] > 0)),
                    'months': len(s), 'from': min(s) if s else None})
        ent.update(evaluate(s, spec['turnover_pct'], spec['cost_per_100pct'], spec['pub_year']))
        ent['repl'] = repl_jkp([(k, side)])
        a_res[k] = ent
        tested.append(ent)
    print('a done', len(a_res), flush=True)

    # ── b
    for spec in fam['b_french_single_sort_vw']['list']:
        cols = fr_cols(spec['file'])
        miss = [c for c in spec['cols'] if c not in cols]
        ent = {'name': spec['name'], 'family': 'b', 'primary': True, 'description': f"{spec['file']} {'+'.join(spec['cols'])}（{spec['good_side']}）",
               'file': spec['file'], 'cols': spec['cols'], 'cite': spec['cite']}
        if miss:
            ent['status'] = f'列が無い: {miss}'; tested.append(ent); continue
        tot = cols[spec['cols'][0]] if len(spec['cols']) == 1 else ew([cols[c] for c in spec['cols']], len(spec['cols']))
        s = to_excess(tot)
        ent.update({'months': len(s), 'from': min(s)})
        ent.update(evaluate(s, spec['turnover_pct'], spec['cost_per_100pct'], spec['pub_year']))
        cp = spec['repl_jkp_counterpart']
        if cp in a_side:
            ent['repl'] = repl_jkp([(cp, a_side[cp])]); ent['repl']['note'] = f'近似: JKP の {cp}（米国の訓練の良い側 {a_side[cp]}）'
        else:
            ent['repl'] = {'regions': 2, 'positive': 0, 'note': f'{cp} の良い側が無い＝正でない'}
        tested.append(ent)
    print('b done', flush=True)

    # ── c
    c_res = {}
    for spec in fam['c_french_largecap']['list']:
        cols = fr_cols(spec['file'])
        ent = {'name': spec['name'], 'family': 'c', 'primary': True, 'description': f"{spec['file']} {spec['cols'][0]}（{spec['desc']}）",
               'file': spec['file'], 'cols': spec['cols']}
        if spec['cols'][0] not in cols:
            ent['status'] = f"列が無い: {spec['cols'][0]}"; tested.append(ent); continue
        s = to_excess(cols[spec['cols'][0]])
        span = (min(s), max(s))
        n_span = sum(1 for k in MKTRF if span[0] <= k <= span[1])
        ent.update({'months': len(s), 'from': span[0], 'empty_months_in_span': n_span - len(s)})
        ent.update(evaluate(s, spec['turnover_pct'], spec['cost_per_100pct'], spec['pub_year']))
        ent['repl'] = repl_french(spec['repl']) if spec['repl'] else None
        c_res[spec['name']] = (ent, s, spec)
        tested.append(ent)
    print('c done', flush=True)

    # ── d（選ぶのは訓練の数字だけ。選ばれた一覧を先に確定してから保有期間を測る）
    d1_keys = sorted(k for k, e in a_res.items() if c1(e))
    d2_names = sorted(n for n, (e, s, sp) in c_res.items() if (n.startswith('c_me5_') or (n.startswith('c_big_') and n.count('_') == 2)) and c1(e))
    selection = {'d1_constituents': d1_keys, 'd2_constituents': d2_names,
                 'd2_candidates': sorted(n for n in c_res if n.startswith('c_me5_') or (n.startswith('c_big_') and n.count('_') == 2))}
    to_map = {x['key']: x['turnover_pct'] for x in fam['a_jkp_tercile_vw']['list']}
    if d1_keys:
        s = ew([a_series[k] for k in d1_keys], COMP_MIN)
        ent = {'name': 'd1_jkp_trainsel_composite', 'family': 'd', 'primary': True,
               'description': f'JKP 良い側三分位のうち訓練 C1 合格 {len(d1_keys)} 本の毎月等分', 'constituents': d1_keys, 'months': len(s), 'from': min(s)}
        ent.update(evaluate(s, S.mean(to_map[k] for k in d1_keys), 0.003))
        ent['repl'] = repl_jkp([(k, a_side[k]) for k in d1_keys])
        tested.append(ent)
    if d2_names:
        s = ew([c_res[n][1] for n in d2_names], COMP_MIN)
        ent = {'name': 'd2_largecap_trainsel_composite', 'family': 'd', 'primary': True,
               'description': f'French 大型株の単一特性版のうち訓練 C1 合格 {len(d2_names)} 本の毎月等分', 'constituents': d2_names, 'months': len(s), 'from': min(s) if s else None}
        if s:
            ent.update(evaluate(s, S.mean(c_res[n][2]['turnover_pct'] for n in d2_names), 0.001))
        ent['repl'] = None
        tested.append(ent)

    # ── Holm と格付け
    fams = {}
    for e in tested:
        if e.get('hold'):
            fams.setdefault(e['family'], {})[e['name']] = e['hold']['p']
    holm_fam = {f: M.holm(p) for f, p in fams.items()}
    holm_all = M.holm({n: p for f in fams.values() for n, p in f.items()})
    for e in tested:
        if not e.get('hold') and not e.get('full'):
            e['grade'], e['criteria'] = 'C', {'note': e.get('status', 'データなし')}
            continue
        hp = holm_fam.get(e['family'], {}).get(e['name'])
        e['holm_p_family'] = hp
        e['holm_p_angle'] = holm_all.get(e['name'])
        repl = e.get('repl')
        g, crit = M.grade(e['full'], e['train'] if e['train_len_ok'] else None, e['hold'], e['roll20'], cost_hold=e['net_hold'],
                          repl=({'regions': repl['regions'], 'positive': repl['positive']} if repl else None), family_holm_p=hp)
        e['grade'], e['criteria'] = g, crit
        e['c7_only_via_family_holm'] = bool(crit['C7_multi'] and not ((e['full']['t'] or 0) >= 3.0) and not ((e['holm_p_angle'] or 1) < 0.05))

    counts = {}
    for e in tested:
        counts.setdefault(e['family'], {}).setdefault(e['grade'], 0)
        counts[e['family']][e['grade']] += 1
    ranked = sorted([e for e in tested if e.get('net_hold')], key=lambda e: -e['net_hold']['ex_ann'])
    out = {'tool': 'night/mw_factor_us.py', 'angle': 'factor_us', 'prereg': f'out/{PRE_NAME}', 'prereg_commit': sha_of(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'global_prereg_commit': sha_of('out/mw_prereg.json'),
           'n_tested': len(tested), 'grade_counts': counts, 'selection_train_only': selection, 'sanity': sanity,
           'top_by_net_hold_excess': [{'name': e['name'], 'grade': e['grade'], 'net_hold_ex': e['net_hold']['ex_ann'], 'hold_t': e['hold']['t'],
                                       'full_t': e['full']['t'], 'train_t': e['train']['t'] if e['train'] else None,
                                       'roll20_win': e['roll20']['win_rate'] if e['roll20'] else None} for e in ranked[:25]],
           'tested': tested}
    p = M.save(OUT_NAME, out)
    print('saved', p, os.path.getsize(p))
    print('grade counts', counts)
    for e in ranked[:30]:
        f = lambda v: f"{v['ex_ann']:+6.2f}(t{v['t']:+.2f})" if v else '     —      '
        print(f"{e['grade']} {e['name'][:34]:34} 全{f(e['full'])} 訓{f(e['train'])} 保{f(e['hold'])} 費後保{f(e['net_hold'])} "
              f"20年窓{(e['roll20'] or {}).get('win_rate')} 再現{(e.get('repl') or {}).get('positive')}/{(e.get('repl') or {}).get('regions')} Holm{e.get('holm_p_family')}")


# ───────────────────────── 事後の点検（結果を見た後に足した・判定には使わない）─────────────────────────
def ex_fin_market():
    """French 49業種から金融（Banks・Insur・RlEst・Fin）を除いた時価加重の市場（総リターン）。
    重みは前月の『平均規模×社数』（当月の値は使わない）"""
    t = M.french_tables('49_Industry_Portfolios')
    ret = t['Average Value Weighted Returns -- Monthly']; sz = t['Average Firm Size']; nf = t['Number of Firms in Portfolios']
    cols = ret['cols']; fin = {'Banks', 'Insur', 'RlEst', 'Fin'}
    ks = sorted(ret['data']); out_all, out_xf = {}, {}
    for p, k in zip(ks, ks[1:]):
        num_a = den_a = num_x = den_x = 0.0
        for i, c in enumerate(cols):
            r, s, n = ret['data'][k][i], sz['data'].get(p, [None] * 49)[i], nf['data'].get(p, [None] * 49)[i]
            if r is None or s is None or n is None or s <= 0 or n <= 0:
                continue
            w = s * n
            num_a += w * r / 100; den_a += w
            if c not in fin:
                num_x += w * r / 100; den_x += w
        if den_a > 0:
            out_all[k] = num_a / den_a; out_xf[k] = num_x / den_x
    return out_all, out_xf


def post_hoc():
    p = os.path.join(M.BASE, 'out', OUT_NAME)
    j = json.load(open(p))
    fam = PRE['families']
    a_turn = {x['key']: x['turnover_pct'] for x in fam['a_jkp_tercile_vw']['list']}
    ph = {'label': '事後（結果を見た後に足した点検・格付けには使わない）', 'why': 'S/A が多数出たので「見かけの勝ちではないか」をまず疑う: 上限なし時価加重（巨大株）への依存・金融を避けた効果・時期の偏り・互いの重なり・良い側と悪い側の単調性'}
    all_mkt, xf_mkt = ex_fin_market()
    ph['ex_fin_market_check'] = {'rebuilt_all_vs_french_mkt': M.excess_stats(all_mkt, MKT), 'ex_fin_vs_french_mkt_hold': M.excess_stats(xf_mkt, MKT, a=M.HOLD_START)}
    mkt_rows = {M._ym(x['date']): float(x['n_stocks']) for x in M.jkp_rows('usa', 'mkt', 'factor', 'vw') if x.get('n_stocks') not in (None, '', 'NA')}
    subs = [('2007-2012', 200701, 201212), ('2013-2019', 201301, 201912), ('2020-', 202001, None), ('2007-2019', 200701, 201912)]
    targets = [e for e in j['tested'] if e.get('grade') in ('S', 'A', 'B') and e['family'] in ('a', 'b', 'c')]
    res = {}
    hold_series = {}
    for e in targets:
        r = {'grade': e['grade']}
        if e['family'] == 'a':
            k, side = e['key'], e['good_side']
            s = jkp_tercile('usa', k, side)
            bad = '1.0' if side == '3.0' else '3.0'
            # 網羅率: 三分位の銘柄数の合計 ÷ JKP 市場の銘柄数（保有期間の平均）
            ns = {}
            for x in M.jkp_rows('usa', k, 'portfolios', 'vw'):
                m = M._ym(x['date'])
                if m >= M.HOLD_START and x.get('n') not in (None, '', 'NA'):
                    ns[m] = ns.get(m, 0) + float(x['n'])
            cov = [ns[m] / mkt_rows[m] for m in ns if m in mkt_rows and mkt_rows[m] > 0]
            r['coverage_hold'] = round(S.mean(cov), 3) if cov else None
            r['bad_side_hold'] = M.excess_stats(jkp_tercile('usa', k, bad), MKTRF, a=M.HOLD_START)
            r['middle_hold'] = M.excess_stats(jkp_tercile('usa', k, '2.0'), MKTRF, a=M.HOLD_START)
            for wt in ('vw_cap', 'ew'):
                try:
                    sw = {M._ym(x['date']): float(x['ret']) for x in M.jkp_rows('usa', k, 'portfolios', wt) if x['pf'] == side and x['ret'] not in ('', 'NA', 'na')
                          and not (x.get('n') not in (None, '', 'NA') and float(x['n']) < NMIN)}
                    r[f'{wt}_full'] = M.excess_stats(sw, MKTRF); r[f'{wt}_hold'] = M.excess_stats(sw, MKTRF, a=M.HOLD_START)
                except Exception as ex:  # noqa
                    r[f'{wt}_error'] = str(ex)[:100]
        else:
            spec = next(x for x in fam['b_french_single_sort_vw']['list'] + fam['c_french_largecap']['list'] if x['name'] == e['name'])
            cols = fr_cols(spec['file'])
            tot = cols[spec['cols'][0]] if len(spec['cols']) == 1 else ew([cols[c] for c in spec['cols']], len(spec['cols']))
            s = to_excess(tot)
        tot = {k2: v + RF[k2] for k2, v in s.items() if k2 in RF}
        mk_same = {k2: MKT[k2] for k2 in tot if k2 in MKT}
        r['maxdd'] = {'full': [round(M.maxdd(tot) * 100, 1), round(M.maxdd(mk_same) * 100, 1)],
                      'hold': [round(M.maxdd(M.window(tot, M.HOLD_START)) * 100, 1), round(M.maxdd(M.window(mk_same, M.HOLD_START)) * 100, 1)],
                      'note': '[戦略, 同じ月の市場]（%）'}
        if e['family'] == 'a':
            try:  # 上限つき同士（上限つき良い側 対 JKP 上限つき市場）＝上限の有無で『良い側の上乗せ』自体が変わるか
                capm = M.jkp_mkt('usa', 'vw_cap')
                swc = {M._ym(x['date']): float(x['ret']) for x in M.jkp_rows('usa', e['key'], 'portfolios', 'vw_cap') if x['pf'] == e['good_side'] and x['ret'] not in ('', 'NA', 'na')}
                r['vw_cap_vs_capped_market_hold'] = M.excess_stats(swc, capm, a=M.HOLD_START)
            except Exception as ex:  # noqa
                r['vw_cap_vs_capped_market_error'] = str(ex)[:100]
        r['vs_ex_fin_market_hold'] = M.excess_stats(tot, xf_mkt, a=M.HOLD_START)
        r['vs_ex_fin_market_full'] = M.excess_stats(tot, xf_mkt)
        r['subperiods'] = {lab: M.excess_stats(s, MKTRF, a=a, z=z) for lab, a, z in subs}
        res[e['name']] = r
        if e['grade'] == 'S':
            hold_series[e['name']] = {k2: s[k2] - MKTRF[k2] for k2 in s if k2 in MKTRF and k2 >= M.HOLD_START}
    ph['per_strategy'] = res
    # S どうしの重なり（保有期間の超過の相関・実効的な独立の本数）
    names = sorted(hold_series)
    if len(names) >= 2:
        ks = sorted(set.intersection(*[set(hold_series[n]) for n in names]))
        import numpy as np
        X = np.array([[hold_series[n][k2] for n in names] for k2 in ks])
        C = np.corrcoef(X.T)
        lam = np.linalg.eigvalsh(C)
        ph['S_overlap'] = {'names': names, 'months': len(ks), 'mean_offdiag_corr': round(float((C.sum() - len(names)) / (len(names) ** 2 - len(names))), 3),
                           'effective_n_bets': round(float(lam.sum() ** 2 / (lam ** 2).sum()), 2),
                           'corr': {a: {b: round(float(C[i, jx]), 2) for jx, b in enumerate(names)} for i, a in enumerate(names)}}
    # 実在の質・収益性系 ETF（生き残りの偏りあり・作り方は別物）と、同じ窓での JKP の規則の比較
    etf = {}
    comp = {}
    for n in ('a_cop_at', 'a_qmj_prof', 'a_ope_be', 'a_sale_bev'):
        e = next((x for x in j['tested'] if x['name'] == n), None)
        if e:
            comp[n] = {k2: v + RF[k2] for k2, v in jkp_tercile('usa', e['key'], e['good_side']).items() if k2 in RF}
    qe = next((x for x in j['tested'] if x['name'] == 'e2_cluster_Quality'), None)
    if qe:
        a_side = {x['key']: x['good_side'] for x in j['tested'] if x.get('family') == 'a' and x.get('good_side')}
        qs = ew([jkp_tercile('usa', k2, a_side[k2]) for k2 in qe['constituents']], 3)
        comp['e2_cluster_Quality'] = {k2: v + RF[k2] for k2, v in qs.items() if k2 in RF}
    for t in ('QUAL', 'SPHQ', 'JQUA', 'FQAL', 'OUSA', 'DGRW', 'MOAT', 'COWZ', 'VIG', 'QDF', 'QUS', 'USMV', 'SPY'):
        try:
            r_etf = M.yahoo(t)
        except Exception as ex:  # noqa
            etf[t] = {'error': str(ex)[:80]}; continue
        a0 = min(r_etf)
        row = {'etf_vs_french_mkt': M.excess_stats(r_etf, MKT, a=a0), 'same_window_to_2025_12': {}}
        row['etf_vs_french_mkt_to_2025_12'] = M.excess_stats(r_etf, MKT, a=a0, z=202512)
        for n, cs in comp.items():
            row['same_window_to_2025_12'][n] = M.excess_stats(cs, MKT, a=a0, z=202512)
        etf[t] = row
    ph['etf_reality_check'] = {'note': '事後・Yahoo の調整後終値（配当込み）・生き残った ETF だけ（生き残りの偏り）・信託報酬込み。ETF の作り方（業種中立・上限・スコア加重）は JKP の三分位と別物', 'rows': etf}
    j['post_hoc_事後'] = ph
    M.save(OUT_NAME, j)
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.1f})" if v and v.get('t') is not None else '    —     '
    for t, row in etf.items():
        if 'error' in row:
            print(t, row['error']); continue
        sw = row['same_window_to_2025_12']
        print(f"ETF {t:5} {f(row['etf_vs_french_mkt'])} 〜2025-12 {f(row['etf_vs_french_mkt_to_2025_12'])} | 同窓 cop_at {f(sw.get('a_cop_at'))} Quality合成 {f(sw.get('e2_cluster_Quality'))}")
    print('ex-fin check', ph['ex_fin_market_check'])
    for n, r in res.items():
        sp = r['subperiods']
        print(f"{r['grade']} {n[:22]:22} cov{r.get('coverage_hold')} 悪{f(r.get('bad_side_hold'))} 中{f(r.get('middle_hold'))} cap{f(r.get('vw_cap_hold'))} ew{f(r.get('ew_hold'))} 対非金融{f(r['vs_ex_fin_market_hold'])} "
              f"07-12{f(sp['2007-2012'])} 13-19{f(sp['2013-2019'])} 20-{f(sp['2020-'])}")
    if 'S_overlap' in ph:
        print('S overlap', ph['S_overlap']['mean_offdiag_corr'], ph['S_overlap']['effective_n_bets'])


# ───────────────────────── 探索の族 e2（out/mw_factor_us_prereg2.json・測る前に登録）─────────────────────────
def explore2():
    PRE2 = 'mw_factor_us_prereg2.json'
    pre2 = json.load(open(os.path.join(M.BASE, 'out', PRE2)))
    p = os.path.join(M.BASE, 'out', OUT_NAME)
    j = json.load(open(p))
    j['tested'] = [e for e in j['tested'] if e.get('family') != 'e2']   # 再実行しても二重に数えない
    a_ent = {e['key']: e for e in j['tested'] if e.get('family') == 'a' and e.get('good_side')}
    turn = {x['key']: x['turnover_pct'] for x in PRE['families']['a_jkp_tercile_vw']['list']}
    ser = {k: jkp_tercile('usa', k, e['good_side']) for k, e in a_ent.items()}
    groups = [(f'e2_cluster_{c.replace(" ", "_").replace("-", "_")}', c, [k for k in ks if k in a_ent], 3)
              for c, ks in pre2['families']['e2_jkp_cluster_composites']['clusters'].items()]
    groups.append(('e2_zoo_all153', '全153特性', sorted(a_ent), 10))
    new = []
    for name, lab, keys, mn in groups:
        s = ew([ser[k] for k in keys], mn)
        ent = {'name': name, 'family': 'e2', 'primary': False, 'exploratory': True,
               'description': f'探索: JKP {lab} の良い側 vw 三分位 {len(keys)} 本の毎月等分（構成要素{mn}本以上の月）', 'constituents': keys,
               'months': len(s), 'from': min(s) if s else None}
        ent.update(evaluate(s, S.mean(turn[k] for k in keys), 0.003))
        # 地域の再現（同じ構成要素・同じ良い側・同じ最低本数）
        rep, pos = {}, 0
        for reg in ('developed', 'emerging', 'jpn'):
            parts = [x for x in (jkp_tercile(reg, k, a_ent[k]['good_side']) for k in keys) if x]
            rs = ew(parts, mn) if parts else {}
            b = M.jkp_mkt(reg, 'vw')
            st_f = M.excess_stats(rs, b) if rs else None
            ok = bool(st_f and st_f['ex_ann'] > 0)
            rep[reg] = {'full': st_f, 'hold': M.excess_stats(rs, b, a=M.HOLD_START) if rs else None, 'positive': ok, 'counted': reg != 'jpn'}
            pos += ok and reg != 'jpn'
        ent['repl'] = {'regions': 2, 'positive': pos, 'detail': rep}
        new.append(ent)
    hp = M.holm({e['name']: e['hold']['p'] for e in new if e.get('hold')})
    for e in new:
        g, crit = M.grade(e['full'], e['train'] if e['train_len_ok'] else None, e['hold'], e['roll20'], cost_hold=e['net_hold'],
                          repl={'regions': 2, 'positive': e['repl']['positive']}, family_holm_p=hp.get(e['name']))
        e['holm_p_family'] = hp.get(e['name']); e['grade'] = g; e['criteria'] = crit
        e['grade_label'] = f'{g}（探索・参考）'
    j['tested'] += new
    j['n_tested'] = len(j['tested'])
    j['exploratory_prereg2'] = {'prereg': f'out/{PRE2}', 'prereg_commit': sha_of(f'out/{PRE2}'),
                                'grade_counts': {g: sum(1 for e in new if e['grade'] == g) for g in 'SABC'}}
    counts = {}
    for e in j['tested']:
        counts.setdefault(e['family'], {}).setdefault(e['grade'], 0); counts[e['family']][e['grade']] += 1
    j['grade_counts'] = counts
    M.save(OUT_NAME, j)
    f = lambda v: f"{v['ex_ann']:+5.2f}(t{v['t']:+.2f})" if v and v.get('t') is not None else '    —      '
    for e in new:
        print(f"{e['grade']} {e['name'][:34]:34} n{len(e['constituents']):3} 全{f(e['full'])} 訓{f(e['train'])} 保{f(e['hold'])} 費後{f(e['net_hold'])} "
              f"20年窓{(e['roll20'] or {}).get('win_rate')} 再現{e['repl']['positive']}/2 Holm{e['holm_p_family']}")


if __name__ == '__main__':
    if '--post-hoc' in sys.argv:
        post_hoc()
    elif '--explore2' in sys.argv:
        explore2()
    else:
        main()
