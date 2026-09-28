#!/usr/bin/env python3
"""night/mw_japan.py — 『市場に勝てる歴史検証』角度 japan: 日本株（買いだけ）で純粋な日本の市場に勝てるか（読むだけ・門の判定には不使用）

事前登録: out/mw_japan_prereg.json（測る前に固定）。線と格付けは out/mw_prereg.json（C1〜C8）を mw_common.grade() でそのまま当てる。
出力: out/mw_japan.json（試したものは全部 tested に残す）

データ
- JKP 日本の三分位（'vw'＝上限なしの時価加重が主・'vw_cap' は報告）。米ドル建て・米国短期国債を引いた超過 → French の RF を足して総リターンにして比べる
- Ken French『International Research Returns Data』の Japan.Dat（1975〜・円建て・上位30%）と他20か国
- Ken French の Japan 6/32 ポートフォリオ（1990-07〜・米ドル）と Asia_Pacific_ex_Japan / Europe（再現）
- Yahoo の日本の高配当 ETF（報告のみ）
"""
import csv, io, json, math, os, re, subprocess, sys, zipfile, statistics as S
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

PREREG = 'mw_japan_prereg.json'
COST, COST_HI = 0.001, 0.003
JKP_START = 198701
HOLD, TRAIN_END, RECENT = M.HOLD_START, M.TRAIN_END, M.RECENT_START

RF = M.ff_factors()['rf']

# ───────────────────────── 取得 ─────────────────────────
AVAIL = json.loads(M.get('https://jkpfactors-data.s3.amazonaws.com/public/availability.json', name='jkp_availability.json'))['portfolios']


def jkp_dirs():
    b = M.get('https://jkpfactors-data.s3.amazonaws.com/public/%5Busa%5D_%5Ball_factors%5D_%5Bmonthly%5D_%5Bvw_cap%5D.zip',
              name='jkp_factor_usa_all_factors_vw_cap_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    d = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        d[x['name']] = int(x['direction'])
    return d


DIRS = jkp_dirs()
_PF = {}


def pf(region, key, w='vw'):
    """JKP 三分位（超過・米ドル）。取れなければ None（0 と読まない）"""
    k = (region, key, w)
    if k not in _PF:
        if key not in AVAIL.get(region, []):
            _PF[k] = None
        else:
            try:
                _PF[k] = M.jkp_portfolios(region, key, w)
            except Exception as e:  # noqa
                print('  取得失敗', k, e)
                _PF[k] = None
    return _PF[k]


_MK = {}


def mkt(region, w='vw'):
    k = (region, w)
    if k not in _MK:
        try:
            _MK[k] = M.jkp_mkt(region, w)
        except Exception as e:  # noqa
            print('  市場の取得失敗', k, e)
            _MK[k] = None
    return _MK[k]


def prefetch(pairs, w='vw'):
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda rk: pf(rk[0], rk[1], w), pairs))


def good_side(key):
    return '3.0' if DIRS[key] == 1 else '1.0'


def jkp_strat(region, keys, w='vw', sides=None, start=None):
    """keys の良い側を等分（毎月組み替え）。構成要素がそろう月だけ。超過（米ドル）"""
    comps = []
    for i, k in enumerate(keys):
        p = pf(region, k, w)
        if p is None:
            return None
        sd = (sides or {}).get(k, good_side(k))
        if sd not in p:
            return None
        comps.append(p[sd])
    ms = set(comps[0])
    for c in comps[1:]:
        ms &= set(c)
    return {m: sum(c[m] for c in comps) / len(comps) for m in sorted(ms) if start is None or m >= start}


_PFN = {}


def pfn(region, key, w='vw'):
    """JKP 三分位の銘柄数 n → {pf: {yyyymm: n}}（取れなければ None）"""
    k = (region, key, w)
    if k not in _PFN:
        if pf(region, key, w) is None:
            _PFN[k] = None
        else:
            d = {}
            for x in M.jkp_rows(region, key, 'portfolios', w):
                if x['n'] not in ('', 'NA'):
                    d.setdefault(x['pf'], {})[M._ym(x['date'])] = int(float(x['n']))
            _PFN[k] = d
    return _PFN[k]


def comp_n(region, key, side, w='vw', nmin=30):
    """選んだ分位のリターン（超過）を、その分位の銘柄数が nmin 以上の月だけ"""
    p, n = pf(region, key, w), pfn(region, key, w)
    if p is None or n is None or side not in p:
        return {}
    nn = n.get(side, {})
    return {m: v for m, v in p[side].items() if nn.get(m, 0) >= nmin}


def composite(region, comps, w='vw', nmin=30, need='half', start=None):
    """comps=[(特徴, 側)]。その月に使える構成要素の等分平均。need='half'＝半分以上・'all'＝全部そろう月だけ"""
    series = [comp_n(region, k, sd, w, nmin) for k, sd in comps]
    ms = set()
    for s in series:
        ms |= set(s)
    out = {}
    for m in sorted(ms):
        if start is not None and m < start:
            continue
        v = [s[m] for s in series if m in s]
        if (need == 'all' and len(v) == len(series)) or (need == 'half' and len(v) * 2 >= len(series) and v):
            out[m] = sum(v) / len(v)
    return out


def tot(ex):
    """超過 + RF → 米ドルの総リターン（RF が無い月は落とす）"""
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


# French International Countries
FR_INTL_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip'
FR_COLS = ['Mkt', 'BM_H', 'BM_L', 'EP_H', 'EP_L', 'CEP_H', 'CEP_L', 'YLD_H', 'YLD_L', 'YLD_0']
FR_FILES = {'Japan': 'Japan.Dat', 'UK': 'UK.Dat', 'Austria': 'Austria.Dat', 'Australia': 'Austrlia.Dat', 'Belgium': 'Belgium.Dat',
            'Canada': 'Canada.Dat', 'Denmark': 'Denmark.Dat', 'Finland': 'Finland.Dat', 'France': 'France.Dat', 'Germany': 'Germany.Dat',
            'HongKong': 'HongKong.Dat', 'Ireland': 'Ireland.Dat', 'Italy': 'Italy.Dat', 'Malaysia': 'Malaysia.Dat',
            'Netherlands': 'Nethrlnd.Dat', 'NewZealand': 'NewZland.Dat', 'Norway': 'Norway.Dat', 'Singapore': 'Singapor.Dat',
            'Spain': 'Spain.Dat', 'Sweden': 'Sweden.Dat', 'Switzerland': 'Swtzrlnd.Dat'}
_FRI = {}


def fr_intl(country, cur='Local'):
    k = (country, cur)
    if k in _FRI:
        return _FRI[k]
    z = zipfile.ZipFile(io.BytesIO(M.get(FR_INTL_URL, name='fr_F-F_International_Countries.zip')))
    out = {c: {} for c in FR_COLS}
    active = False
    for line in z.read(FR_FILES[country]).decode('latin-1').splitlines():
        if 'Value-Weight' in line:
            active = (cur in line) and ('Not Reqd' in line)
            continue
        m = re.match(r'^\s*(\d{6})\s+(.*)$', line)
        if active and m:
            for c, x in zip(FR_COLS, m.group(2).split()):
                v = float(x)
                if v <= -99.99 or v == -999:
                    continue
                out[c][int(m.group(1))] = v / 100
    _FRI[k] = out
    return out


def fr_blend(d, cols):
    ms = set(d[cols[0]])
    for c in cols[1:]:
        ms &= set(d[c])
    return {m: sum(d[c][m] for c in cols) / len(cols) for m in sorted(ms)}


def fr_vw(name):
    for t, v in M.french_tables(name).items():
        if 'value weight' in t.lower() and v['freq'] == 'monthly':
            out = {c: {} for c in v['cols']}
            for d, row in v['data'].items():
                for c, x in zip(v['cols'], row):
                    if x is not None:
                        out[c][d] = x / 100
            return out
    raise KeyError(name)


def fr_mkt(region):
    for t, v in M.french_tables(f'{region}_3_Factors').items():
        if v['freq'] == 'monthly':
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(region)


# ───────────────────────── 評価 ─────────────────────────
def evaluate(sid, family, label, s, b, turnover, rf=None, pub=None, meta=None):
    """s・b は同じ通貨の総リターン。格付けは族の Holm の後で付ける"""
    rf = rf or RF
    r = {'id': sid, 'family': family, 'label': label, 'turnover': turnover}
    if meta:
        r.update(meta)
    if not s or not b:
        r['error'] = 'データなし'
        return r
    r['full'] = M.excess_stats(s, b)
    r['train'] = M.excess_stats(s, b, z=TRAIN_END)
    r['hold'] = M.excess_stats(s, b, a=HOLD)
    r['recent'] = M.excess_stats(s, b, a=RECENT)
    net = M.apply_cost(s, turnover, COST)
    net_hi = M.apply_cost(s, turnover, COST_HI)
    r['cost_hold'] = M.excess_stats(net, b, a=HOLD)
    r['cost_hold_030'] = M.excess_stats(net_hi, b, a=HOLD)
    r['cost_full'] = M.excess_stats(net, b)
    r['roll20'] = M.rolling(s, b, 20)
    r['dca20'] = M.dca(s, b, 20)
    r['sub'] = {'2007-12': M.excess_stats(s, b, a=200701, z=201212), '2013-19': M.excess_stats(s, b, a=201301, z=201912),
                '2020-': M.excess_stats(s, b, a=202001)}
    if pub:
        r['post_pub'] = M.excess_stats(s, b, a=(pub + 1) * 100 + 1)
    ks = sorted(set(s) & set(b))
    r['maxdd'] = {'s': round(M.maxdd({k: s[k] for k in ks}) * 100, 1), 'b': round(M.maxdd({k: b[k] for k in ks}) * 100, 1)}
    if rf is not None:
        r['sharpe'] = {w: (M.sharpe({k: s[k] for k in ks}, rf, a, z), M.sharpe({k: b[k] for k in ks}, rf, a, z))
                       for w, a, z in (('full', None, None), ('train', None, TRAIN_END), ('hold', HOLD, None))}
    return r


def finish_family(rows, fam_name):
    """族の中で保有期間の p を Holm 補正し、格付けを付ける"""
    ps = {r['id']: r['hold']['p'] for r in rows if r.get('hold') and r['hold'].get('p') is not None}
    hp = M.holm(ps)
    for r in rows:
        r['family_size'] = len(ps)
        r['holm_p'] = hp.get(r['id'])
        if r.get('error'):
            r['grade'], r['criteria'] = 'C', {'error': r['error']}
            continue
        # 是正（第2の事前登録）: 全体の事前登録の『訓練期間は最低15年』を当てる（mw_common.grade は見ていない）
        tr = r['train']
        if tr and tr['years'] < 15:
            r['train_short'] = f"訓練期間 {tr['years']}年 < 15年 → C1 不合格"
            tr = None
        # E6_jpsel: 訓練期間で選んだので C7 は保有期間の Holm だけ（全期間 t を使わない＝より厳しく）
        full = None if r.get('c7_holm_only') else r['full']
        g, c = M.grade(full, tr, r['hold'], r['roll20'], r['cost_hold'], r.get('repl'), r['holm_p'])
        r['grade'], r['criteria'] = g, c
    return rows


# ───────────────────────── 再現（C5） ─────────────────────────
JKP_REPL = ['aus', 'hkg', 'sgp', 'nzl', 'gbr', 'deu', 'fra', 'che', 'nld', 'swe', 'ita', 'esp', 'dnk', 'nor', 'bel', 'fin', 'aut', 'irl', 'prt']
FR_REPL = [c for c in FR_FILES if c != 'Japan']


def repl_jkp(keys, w='vw', sides=None):
    det = {}
    for c in JKP_REPL:
        if any(k not in AVAIL.get(c, []) for k in keys):
            continue
        s = jkp_strat(c, keys, w, sides)
        b = mkt(c, 'vw')
        if not s or not b:
            continue
        st = M.excess_stats(s, b)
        if st:
            det[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
    return {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det}


def repl_fr(cols):
    det = {}
    for c in FR_REPL:
        d = fr_intl(c, 'Local')
        if any(len(d[x]) < 36 for x in cols) or len(d['Mkt']) < 36:
            continue
        s = fr_blend(d, cols)
        st = M.excess_stats(s, d['Mkt'])
        if st:
            det[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
    return {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det}


# ───────────────────────── 族 ─────────────────────────
PRE = json.load(open(os.path.join(M.BASE, 'out', PREREG)))
TURN = PRE['costs']['turnover_oneway_per_year']
PUB = PRE['publication_years']
P_SINGLES = ['div12m_me', 'be_me', 'ni_me', 'ocf_me', 'eqnpo_me', 'eqnpo_12m', 'chcsho_12m', 'ope_be', 'gp_at', 'qmj', 'ret_12_1',
             'ivol_capm_252d', 'at_gr1']
P_BLENDS = {'B1_div_value_payout': ['div12m_me', 'be_me', 'eqnpo_me'], 'B2_quality_value': ['qmj', 'be_me']}
FR_P = {'FR_BM_H': ['BM_H'], 'FR_EP_H': ['EP_H'], 'FR_CEP_H': ['CEP_H'], 'FR_YLD_H': ['YLD_H'], 'FR_VAL4': ['BM_H', 'EP_H', 'CEP_H', 'YLD_H']}
E4 = {'E4_def_value': ['be_me', 'ivol_capm_252d'], 'E4_value_mom': ['be_me', 'ret_12_1'], 'E4_payout_quality': ['eqnpo_me', 'qmj'],
      'E4_cheap_quality': ['qmj', 'ni_me'], 'E4_value5': ['div12m_me', 'be_me', 'ni_me', 'ocf_me', 'eqnpo_me'],
      'E4_value_quality_mom': ['be_me', 'qmj', 'ret_12_1'], 'E4_mispricing': ['mispricing_mgmt', 'mispricing_perf'],
      'E4_lowrisk': ['ivol_capm_252d', 'betabab_1260d']}
E4_TURN = {'mispricing_mgmt': 1.0, 'mispricing_perf': 1.0, 'betabab_1260d': 0.8}


def turn_of(k):
    return TURN.get(k, E4_TURN.get(k))


def census_turn(k):
    short = ['ret_1_0', 'ret_3_1', 'rmax', 'rskew_21d', 'iskew_', 'rvol_21d', 'beta_dimson_21d', 'coskew_21d', 'bidaskhl_21d',
             'zero_trades_21d', 'seas_1_1']
    if any(k.startswith(x) for x in short) or (k.startswith('ivol_') and k.endswith('_21d')):
        return 6.0
    if k in ('ret_6_1', 'ret_9_1', 'ret_12_1', 'ret_12_7', 'prc_highprc_252d') or k.startswith('resff3_') or k.startswith('seas_'):
        return 2.5
    if k.startswith('niq_') or k.startswith('saleq_') or k.startswith('ocfq_') or k == 'ni_inc8q':
        return 1.5
    return 0.8


def run_P(bj_tot):
    rows = []
    for k in P_SINGLES:
        s = jkp_strat('jpn', [k], 'vw', start=JKP_START)
        r = evaluate(f'P_JKP_{k}', 'P', PRE['families']['P（主・格付け・Holm は P の20本で）']['JKP_singles（jpn・vw・論文の向きの良い側1/3 vs jpn vw 市場）'][k],
                     tot(s), bj_tot, turn_of(k), pub=PUB.get(k), meta={'source': 'JKP jpn vw', 'side': good_side(k), 'n_last': n_last('jpn', k), 'comps': [[k, good_side(k), 'vw']]})
        r['repl'] = repl_jkp([k])
        rows.append(r)
    for bid, ks in P_BLENDS.items():
        s = jkp_strat('jpn', ks, 'vw', start=JKP_START)
        r = evaluate(f'P_JKP_{bid}', 'P', '＋'.join(ks), tot(s), bj_tot, S.mean(turn_of(k) for k in ks), meta={'source': 'JKP jpn vw', 'comps': [[k, good_side(k), 'vw'] for k in ks]})
        r['repl'] = repl_jkp(ks)
        rows.append(r)
    fj = fr_intl('Japan', 'Local')
    for fid, cols in FR_P.items():
        s = fr_blend(fj, cols)
        r = evaluate(f'P_{fid}', 'P', '＋'.join(cols) + '（French Intl 日本・円）', s, fj['Mkt'], 0.4, rf=None,
                     meta={'source': 'French International Countries Japan（円・Not Reqd）'})
        r['repl'] = repl_fr(cols)
        rows.append(r)
    return finish_family(rows, 'P')


def n_last(region, key):
    try:
        rows = M.jkp_rows(region, key, 'portfolios', 'vw')
        last = max(x['date'] for x in rows)
        return {x['pf']: int(x['n']) for x in rows if x['date'] == last}
    except Exception:  # noqa
        return None


def run_E1():
    jm = fr_mkt('Japan')
    rf_j = {d: v for d, v in RF.items()}
    spec = {'FR6_BIG_HiBM': ('6_Portfolios_ME_BE-ME', ['BIG HiBM'], 0.4), 'FR6_BIG_HiOP': ('6_Portfolios_ME_OP', ['BIG HiOP'], 0.4),
            'FR6_BIG_LoINV': ('6_Portfolios_ME_INV', ['BIG LoINV'], 0.4), 'FR6_BIG_HiPRIOR': ('6_Portfolios_ME_Prior_12_2', ['BIG HiPRIOR'], 2.0),
            'FR32_BIG_HiBM_HiOP': ('32_Portfolios_ME_BE-ME_OP_2x4x4', ['BIG HiBM HiOP'], 0.4)}
    rows = []

    def build(region, key):
        if key == 'FR6_BIG_VALQ':
            a, b = build(region, 'FR6_BIG_HiBM'), build(region, 'FR6_BIG_HiOP')
            return {m: (a[m] + b[m]) / 2 for m in sorted(set(a) & set(b))} if a and b else None
        f, cols, _ = spec[key]
        try:
            d = fr_vw(f'{region}_{f}')
        except Exception as e:  # noqa
            print('  French 取得失敗', region, f, e)
            return None
        return d.get(cols[0])

    for key in list(spec) + ['FR6_BIG_VALQ']:
        s = build('Japan', key)
        to = spec[key][2] if key in spec else 0.4
        r = evaluate(key, 'E1', key, s, jm, to, rf=rf_j, meta={'source': 'French Japan 6/32 portfolios（米ドル）'})
        det = {}
        for reg in ('Asia_Pacific_ex_Japan', 'Europe'):
            sr = build(reg, key)
            try:
                mr = fr_mkt(reg)
            except Exception:  # noqa
                mr = None
            if sr and mr:
                st = M.excess_stats(sr, mr)
                if st:
                    det[reg] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
        r['repl'] = {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det}
        rows.append(r)
    return finish_family(rows, 'E1')


def run_E2(bj_tot):
    rows = []
    for k in P_SINGLES:
        s = jkp_strat('jpn', [k], 'vw_cap', start=JKP_START)
        r = evaluate(f'E2_JKPcap_{k}', 'E2', k + '（vw_cap）', tot(s) if s else None, bj_tot, turn_of(k), meta={'source': 'JKP jpn vw_cap', 'side': good_side(k), 'comps': [[k, good_side(k), 'vw_cap']]})
        r['repl'] = repl_jkp([k], 'vw_cap')
        rows.append(r)
    for bid, ks in P_BLENDS.items():
        s = jkp_strat('jpn', ks, 'vw_cap', start=JKP_START)
        r = evaluate(f'E2_JKPcap_{bid}', 'E2', '＋'.join(ks) + '（vw_cap）', tot(s) if s else None, bj_tot, S.mean(turn_of(k) for k in ks),
                     meta={'source': 'JKP jpn vw_cap', 'comps': [[k, good_side(k), 'vw_cap'] for k in ks]})
        r['repl'] = repl_jkp(ks, 'vw_cap')
        rows.append(r)
    return finish_family(rows, 'E2')


def run_E3(bj_tot):
    keys = sorted(k for k in AVAIL['jpn'] if k != 'all_factors')
    prefetch([('jpn', k) for k in keys])
    rows = []
    for k in keys:
        p = pf('jpn', k)
        if p is None or k not in DIRS:
            rows.append({'id': f'E3_{k}', 'family': 'E3', 'label': k, 'error': 'データなし'})
            continue
        gs = good_side(k)
        tr = [p['3.0'][m] - p['1.0'][m] for m in sorted(set(p['3.0']) & set(p['1.0'])) if JKP_START <= m <= TRAIN_END]
        jp = ('3.0' if S.mean(tr) > 0 else '1.0') if len(tr) >= 60 else None
        for side, tag in ((gs, 'paper'), (jp, 'jpside')):
            if side is None or (tag == 'jpside' and side == gs):
                continue
            s = {m: v for m, v in p[side].items() if m >= JKP_START}
            r = evaluate(f'E3_{k}' + ('' if tag == 'paper' else '_jpside'), 'E3', k, tot(s), bj_tot, census_turn(k),
                         meta={'source': 'JKP jpn vw', 'side': side, 'side_rule': tag, 'paper_dir': DIRS[k], 'jp_train_ls_mean_ann': round(S.mean(tr) * 1200, 2) if tr else None, 'comps': [[k, side, 'vw']]})
            r['_keys'] = (k, side)
            rows.append(r)
    # C5 は C1・C2・C6 が合格したものだけ（事前登録どおり）
    for r in rows:
        if r.get('error'):
            continue
        c1 = bool(r['train'] and r['train']['ex_ann'] > 0 and (r['train']['t'] or 0) >= 2.0)
        c2 = bool(r['hold'] and r['hold']['ex_ann'] > 0 and r['hold']['cagr_diff'] > 0)
        c6 = bool(r['cost_hold'] and r['cost_hold']['ex_ann'] > 0 and r['cost_hold']['cagr_diff'] > 0)
        if c1 and c2 and c6:
            k, side = r['_keys']
            prefetch([(c, k) for c in JKP_REPL])
            r['repl'] = repl_jkp([k], 'vw', sides={k: side})
    for r in rows:
        r.pop('_keys', None)
    return finish_family(rows, 'E3')


def run_E4(bj_tot):
    rows = []
    for bid, ks in E4.items():
        s = jkp_strat('jpn', ks, 'vw', start=JKP_START)
        r = evaluate(bid, 'E4', '＋'.join(ks), tot(s) if s else None, bj_tot, S.mean(turn_of(k) for k in ks), meta={'source': 'JKP jpn vw', 'comps': [[k, good_side(k), 'vw'] for k in ks]})
        prefetch([(c, k) for c in JKP_REPL for k in ks])
        r['repl'] = repl_jkp(ks)
        rows.append(r)
    return finish_family(rows, 'E4')


ETFS = ['1489.T', '1577.T', '1698.T', '2529.T', '1478.T', '1399.T', '1651.T', '1494.T', '2564.T']


def etf_ok(s):
    """ひと月に ±40% を超える月がある ETF 系列は壊れている（TOPIX がそこまで動いた月はない）"""
    return bool(s) and not any(v < -0.4 or v > 0.4 for v in s.values())


def etf_row(sid, fam, label, s, b):
    ks = set(s) & set(b)
    st = M.excess_stats(s, b)
    return {'id': sid, 'family': fam, 'label': label, 'full': st,
            'dca_all': M.dca(s, b, max(1, (len(ks) // 12) - 1), step=12) if st else None,
            'maxdd': {'s': round(M.maxdd({k: s[k] for k in ks}) * 100, 1), 'b': round(M.maxdd({k: b[k] for k in ks}) * 100, 1)} if ks else None,
            'grade': '報告のみ（格付けしない）'}


def run_E5():
    """第2の事前登録で是正: 相手は 1305.T（1306.T の Yahoo 系列は分割未調整で壊れている）。照合に 1348.T"""
    bench = {}
    for t in ('1305.T', '1348.T', '1306.T'):
        try:
            x = M.yahoo(t)
        except Exception:  # noqa
            x = None
        bench[t] = x if etf_ok(x) else None
    out = [{'id': 'E5_bench_check', 'family': 'E5', 'label': '相手の TOPIX ETF の系列の健全性',
            'grade': '報告のみ（格付けしない）', 'ok': {t: v is not None for t, v in bench.items()}}]
    for t in ETFS:
        try:
            s = M.yahoo(t)
        except Exception as e:  # noqa
            out.append({'id': f'E5_{t}', 'family': 'E5', 'error': str(e)[:100], 'grade': '報告のみ（格付けしない）'})
            continue
        if not etf_ok(s):
            out.append({'id': f'E5_{t}', 'family': 'E5', 'error': '系列が壊れている（±40%超の月）', 'grade': '報告のみ（格付けしない）'})
            continue
        r = etf_row(f'E5_{t}', 'E5', PRE['data']['ETF']['tickers'][t] + ' vs 1305.T', s, bench['1305.T'])
        if bench.get('1348.T'):
            st2 = M.excess_stats(s, bench['1348.T'])
            r['vs_1348'] = {k: st2[k] for k in ('from', 'to', 'ex_ann', 't', 'cagr_diff')} if st2 else None
        out.append(r)
    return out


def run_E8():
    out = []
    try:
        s, b = M.yahoo('EWJV'), M.yahoo('EWJ')
        out.append(etf_row('E8_EWJV_vs_EWJ', 'E8', 'iShares MSCI Japan Value vs iShares MSCI Japan（米ドル）', s, b)
                   if etf_ok(s) and etf_ok(b) else {'id': 'E8_EWJV_vs_EWJ', 'family': 'E8', 'error': '系列が壊れている', 'grade': '報告のみ（格付けしない）'})
    except Exception as e:  # noqa
        out.append({'id': 'E8_EWJV_vs_EWJ', 'family': 'E8', 'error': str(e)[:100], 'grade': '報告のみ（格付けしない）'})
    return out


# ───────────────────────── 第2の事前登録: E6・E7 ─────────────────────────
PRE2 = 'mw_japan_prereg2.json'
CLUSTERS = None


def clusters():
    global CLUSTERS
    if CLUSTERS is None:
        b = M.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Cluster%20Labels.csv', name='jkp_cluster_labels.csv')
        CLUSTERS = {}
        for x in csv.DictReader(io.StringIO(b.decode())):
            CLUSTERS.setdefault(x['cluster'], []).append(x['characteristic'])
    return CLUSTERS


def select_by_train(region, keys, a, z, nmin=30):
    """訓練期間 [a, z] だけで各特徴の側（第1 or 第3分位）を選び、NW t≥2.0・15年以上のものを返す"""
    b = mkt(region, 'vw')
    bt = tot(b)
    sel, log = [], {}
    for k in keys:
        best = None
        for side in ('1.0', '3.0'):
            s = {m: v for m, v in comp_n(region, k, side, 'vw', nmin).items() if a <= m <= z}
            st = M.excess_stats(tot(s), bt, a, z) if s else None
            if st and st['years'] >= 15 and (best is None or st['ex_ann'] > best[1]['ex_ann']):
                best = (side, st)
        if best:
            log[k] = {'side': best[0], 'ex_ann': best[1]['ex_ann'], 't': best[1]['t'], 'years': best[1]['years']}
            if (best[1]['t'] or 0) >= 2.0:
                sel.append((k, best[0]))
    return sel, log


def repl_comp(comps, nmin=10, min_years=10):
    det = {}
    for c in JKP_REPL:
        use = [(k, sd) for k, sd in comps if k in AVAIL.get(c, [])]
        if len(use) * 2 < len(comps):
            continue
        prefetch([(c, k) for k, _ in use])
        # その国で使えない構成要素は『そろわない』側に数える（半分の条件は全体の本数に対して）
        series = [comp_n(c, k, sd, 'vw', nmin) for k, sd in use]
        ms = set().union(*[set(x) for x in series]) if series else set()
        s = {}
        for m in sorted(ms):
            v = [x[m] for x in series if m in x]
            if len(v) * 2 >= len(comps):
                s[m] = sum(v) / len(v)
        b = mkt(c, 'vw')
        if not s or not b:
            continue
        st = M.excess_stats(s, b)
        if st and st['years'] >= min_years:
            det[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
    return {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det}


def run_E6(bj_tot):
    keys = sorted(k for k in AVAIL['jpn'] if k != 'all_factors' and k in DIRS)
    prefetch([('jpn', k) for k in keys])
    ukeys = sorted(k for k in AVAIL['usa'] if k != 'all_factors' and k in DIRS)
    prefetch([('usa', k) for k in ukeys])
    specs = {}
    jsel, jlog = select_by_train('jpn', keys, JKP_START, TRAIN_END)
    specs['E6_jpsel_t2'] = (jsel, '日本の訓練期間で選んだ特徴（NW t≥2）を等分', {'c7_holm_only': True, 'selection_log': jlog})
    usel, ulog = select_by_train('usa', ukeys, 196307, TRAIN_END)
    usel = [(k, sd) for k, sd in usel if k in keys]
    specs['E6_ussel_t2'] = (usel, '米国の訓練期間（1963-07〜2006-12）で選んだ特徴を日本に当てる', {'selection_log': ulog})
    specs['E6_all153'] = ([(k, good_side(k)) for k in keys], '全特徴の論文の向きの良い側を等分', {})
    for cl, members in sorted(clusters().items()):
        comps = [(k, good_side(k)) for k in members if k in keys]
        specs['E6_theme_' + cl.replace(' ', '_').replace('-', '_')] = (comps, f'JKP クラスタ「{cl}」の良い側を等分', {})
    rows = []
    for sid, (comps, label, extra) in specs.items():
        s = composite('jpn', comps, 'vw', 30, 'half', start=JKP_START)
        to = S.mean(census_turn(k) for k, _ in comps) if comps else 0
        meta = {'source': 'JKP jpn vw（n≥30 の月・半分以上そろう月）', 'comps': [[k, sd, 'vw'] for k, sd in comps], 'n_comps': len(comps)}
        meta.update({k: v for k, v in extra.items() if k != 'selection_log'})
        r = evaluate(sid, 'E6', label, tot(s) if s else None, bj_tot, to, meta=meta)
        if 'selection_log' in extra:
            r['selected'] = [[k, sd] for k, sd in comps]
        rows.append(r)
    for r in rows:
        if r.get('error'):
            continue
        c1 = bool(r['train'] and r['train']['years'] >= 15 and r['train']['ex_ann'] > 0 and (r['train']['t'] or 0) >= 2.0)
        c2 = bool(r['hold'] and r['hold']['ex_ann'] > 0 and r['hold']['cagr_diff'] > 0)
        c6 = bool(r['cost_hold'] and r['cost_hold']['ex_ann'] > 0 and r['cost_hold']['cagr_diff'] > 0)
        if c1 and c2 and c6:
            r['repl'] = repl_comp([tuple(x[:2]) for x in r['comps']])
    return finish_family(rows, 'E6'), {'jp_selection': jlog, 'us_selection': ulog}


def run_E7():
    jm = fr_mkt('Japan')
    cells = {'E7_ME5_BM5': ['BIG HiBM'], 'E7_ME5_BM45': ['ME5 BM4', 'BIG HiBM'], 'E7_ME45_BM5': ['ME4 BM5', 'BIG HiBM'],
             'E7_ME45_BM45': ['ME4 BM4', 'ME4 BM5', 'ME5 BM4', 'BIG HiBM']}
    d = {reg: fr_vw(f'{reg}_25_Portfolios_ME_BE-ME') for reg in ('Japan', 'Asia_Pacific_ex_Japan', 'Europe')}
    rows = []
    for sid, cs in cells.items():
        s = fr_blend(d['Japan'], cs)
        r = evaluate(sid, 'E7', '＋'.join(cs) + '（French Japan 25分割・米ドル）', s, jm, 0.5, meta={'source': 'French Japan_25_Portfolios_ME_BE-ME'})
        det = {}
        for reg in ('Asia_Pacific_ex_Japan', 'Europe'):
            st = M.excess_stats(fr_blend(d[reg], cs), fr_mkt(reg))
            if st:
                det[reg] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
        r['repl'] = {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det}
        rows.append(r)
    return finish_family(rows, 'E7')


def robust_n30(r, bj_tot):
    """事後の頑健性（格付けに使わない）: 構成する分位が30銘柄以上の月だけで訓練期間を測り直す"""
    comps = r.get('comps')
    if not comps:
        return None
    w = comps[0][2]
    need = 'half' if r['family'] == 'E6' else 'all'
    s = composite('jpn', [(k, sd) for k, sd, _ in comps], w, 30, need, start=JKP_START)
    st = M.excess_stats(tot(s), bj_tot, z=TRAIN_END) if s else None
    return {'train_n30': st, 'note': '事後（格付けに使わない）'}


def sanity():
    ff = M.ff_factors()
    out = {'US_mkt_cagr_all': round(M.cagr(ff['mkt']) * 100, 2), 'US_mkt_cagr_2007': round(M.cagr(M.window(ff['mkt'], HOLD)) * 100, 2)}
    f = M.jkp_factor('jpn', 'div12m_me', 'vw_cap')
    x = list(f.values())
    out['JKP_jpn_div12m_me_ls_vwcap'] = {'from': min(f), 'to': max(f), 'mean_ann': round(S.mean(x) * 1200, 2),
                                         't_simple': round(S.mean(x) / (S.stdev(x) / math.sqrt(len(x))), 2), 't_nw': round(M.nw_t(x), 2)}
    jm = tot(mkt('jpn', 'vw'))
    fm = fr_mkt('Japan')
    ks = sorted(k for k in set(jm) & set(fm) if k >= 199007)
    out['JKP_vs_French_Japan_mkt'] = {'from': ks[0], 'to': ks[-1], 'corr': round(M.corr([jm[k] for k in ks], [fm[k] for k in ks]), 4),
                                      'cagr_jkp': round(M.cagr([jm[k] for k in ks]) * 100, 2), 'cagr_french': round(M.cagr([fm[k] for k in ks]) * 100, 2)}
    jc = tot(mkt('jpn', 'vw_cap'))
    st = M.excess_stats(jc, jm)
    out['JKP_jpn_vwcap_mkt_minus_vw_mkt'] = st
    fl, fd = fr_intl('Japan', 'Local'), fr_intl('Japan', 'Dollar')
    ks2 = sorted(set(fl['Mkt']) & set(fd['Mkt']))
    out['FR_intl_Japan_mkt'] = {'from': ks2[0], 'to': ks2[-1], 'cagr_local': round(M.cagr([fl['Mkt'][k] for k in ks2]) * 100, 2),
                                'cagr_dollar': round(M.cagr([fd['Mkt'][k] for k in ks2]) * 100, 2),
                                'implied_fx_cagr': round((((1 + M.cagr([fd['Mkt'][k] for k in ks2])) / (1 + M.cagr([fl['Mkt'][k] for k in ks2]))) - 1) * 100, 2)}
    ks3 = sorted(k for k in set(fd['Mkt']) & set(fm))
    out['FR_intl_Japan_dollar_vs_FF_Japan_mkt'] = {'corr': round(M.corr([fd['Mkt'][k] for k in ks3], [fm[k] for k in ks3]), 4), 'n': len(ks3)}
    return out


DEVIATIONS = [
    "ETF（E5・報告のみ）: 相手の 1306.T は Yahoo の系列が分割の未調整で壊れていた（2014-12 −90%・2026-02 −91%・2026-03 +961%）。第1回の ETF の結果は無効。第2の事前登録で 1305.T へ替え、1348.T を照合に出した",
    "mw_common.grade() は全体の事前登録の『訓練期間は最低15年』を見ていない（共通部品の穴・mw_common は編集していない）。この道具で15年未満の訓練期間を C1 不合格にした（第2の事前登録）。これで P の B1（配当＋割安＋還元）は第1回の S から C に変わった（eqnpo_me の日本のデータが1987〜1999年に途切れ途切れで訓練期間13.2年）",
    "JKP 日本の会計系の特徴は1987〜88年に三分位あたり6〜13銘柄、qmj は1993-04まで3〜7銘柄しかない。事前登録に銘柄数の下限は無かったので格付けはそのまま。n≥30 の月だけで測り直した訓練期間の値を robust に『事後』として付けた（qmj を含む B2 と E4 の割安＋質＋勢いは n≥30 だと訓練期間13.7年で15年を割る）",
    "diagnostics（事後・格付けに使わない）: 三分位の等分平均そのものが市場に少し勝つ（小型寄りの傾き）かを確かめる『偽薬』＝同じ特徴の3つの分位を全部等分に持った場合と、反対側を持った場合を並べた",
]


def diagnostics(fams, bj_tot):
    """事後の診断（格付けに使わない）: 偽薬（同じ特徴の3分位を全部等分）と反対側"""
    out = {}
    for f, rows in fams.items():
        for r in rows:
            if r.get('grade') not in ('S', 'A', 'B') or not r.get('comps'):
                continue
            comps = [(k, sd) for k, sd, _ in r['comps']]
            w = r['comps'][0][2]
            need = 'half' if f == 'E6' else 'all'
            plc = [(k, sd) for k, _ in comps for sd in ('1.0', '2.0', '3.0')]
            opp = [(k, '1.0' if sd == '3.0' else '3.0') for k, sd in comps]
            nmin = 30 if f == 'E6' else 0
            s = tot(composite('jpn', comps, w, nmin, need, start=JKP_START))
            p = tot(composite('jpn', plc, w, nmin, need, start=JKP_START))
            o = tot(composite('jpn', opp, w, nmin, need, start=JKP_START))
            d = {}
            for nm, x, b in (('placebo_vs_mkt', p, bj_tot), ('opposite_vs_mkt', o, bj_tot), ('strategy_vs_placebo', s, p)):
                d[nm] = {w2: (lambda st: {k: st[k] for k in ('ex_ann', 't', 'cagr_diff')} if st else None)(M.excess_stats(x, b, a, z))
                         for w2, a, z in (('train', None, TRAIN_END), ('hold', HOLD, None))}
            out[r['id']] = d
    return out


def git_sha(path):
    try:
        return subprocess.check_output(['git', '-C', M.BASE, 'log', '-n1', '--format=%H', '--', path], text=True).strip() or None
    except Exception:  # noqa
        return None


def compact(r):
    """JSON を小さく保つ（E3 は詳細を削る）"""
    r = dict(r)
    for k in ('sub', 'sharpe', 'cost_full'):
        r.pop(k, None)
    return r


def main():
    only = sys.argv[1:]
    bj = mkt('jpn', 'vw')
    bj_tot = tot({m: v for m, v in bj.items() if m >= JKP_START})
    prefetch([('jpn', k) for k in P_SINGLES + ['mispricing_mgmt', 'mispricing_perf', 'betabab_1260d']])
    prefetch([('jpn', k) for k in P_SINGLES], 'vw_cap')
    prefetch([(c, k) for c in JKP_REPL for k in P_SINGLES])
    out = {'angle': 'japan', 'prereg': 'out/' + PREREG, 'prereg_commit': git_sha('out/' + PREREG),
           'prereg2': 'out/' + PRE2, 'prereg2_commit': git_sha('out/' + PRE2),
           'benchmark': 'JKP jpn mkt vw（上限なし）＋RF（米ドル総リターン）／French Intl は同じ表の Mkt（円）／French 6/32 は Japan_3_Factors の Mkt',
           'cost_unit': COST, 'sanity': sanity()}
    print('sanity', json.dumps(out['sanity'], ensure_ascii=False)[:800])
    fams = {}
    fams['P'] = run_P(bj_tot)
    fams['E1'] = run_E1()
    fams['E2'] = run_E2(bj_tot)
    fams['E4'] = run_E4(bj_tot)
    fams['E3'] = run_E3(bj_tot)
    fams['E5'] = run_E5()
    fams['E6'], sel = run_E6(bj_tot)
    fams['E7'] = run_E7()
    fams['E8'] = run_E8()
    out['selection_logs'] = sel
    for f, rows in fams.items():
        for r in rows:
            if r.get('grade') in ('S', 'A', 'B') and r.get('comps'):
                r['robust'] = robust_n30(r, bj_tot)
    out['diagnostics'] = diagnostics(fams, bj_tot)
    out['deviations'] = DEVIATIONS
    tested = []
    for f, rows in fams.items():
        for r in rows:
            tested.append(compact(r) if f in ('E3',) else r)
    out['tested'] = tested
    out['n_tested'] = sum(1 for r in tested if r['family'] not in ('E5', 'E8'))
    out['n_tested_incl_etf'] = len(tested)
    out['grade_counts'] = {f: {g: sum(1 for r in rows if r.get('grade') == g) for g in ('S', 'A', 'B', 'C')} for f, rows in fams.items() if f not in ('E5', 'E8')}
    p = M.save('mw_japan.json', out)
    print('saved', p, os.path.getsize(p))
    for f, rows in fams.items():
        print('==', f)
        for r in sorted(rows, key=lambda r: -((r.get('hold') or r.get('full') or {}).get('ex_ann') or -99))[:25]:
            h = r.get('hold') or {}
            t = r.get('train') or {}
            fu = r.get('full') or {}
            print(f"  {r['id'][:34]:34s} {r.get('grade','-'):3s} train {t.get('ex_ann')!s:>6} t{t.get('t')!s:>5} | hold {h.get('ex_ann')!s:>6} t{h.get('t')!s:>5} cg{h.get('cagr_diff')!s:>6} | full t{fu.get('t')!s:>5} | roll {((r.get('roll20') or {}).get('win_rate'))} | repl {(r.get('repl') or {}).get('positive')}/{(r.get('repl') or {}).get('regions')} holm {r.get('holm_p')}")


if __name__ == '__main__':
    main()
