#!/usr/bin/env python3
"""night/nx_pre1926x.py — 角度 nx_pre1926x を事前登録どおりに測る（読むだけ・門の判定には不使用）

問い（out/nx_pre1926x_prereg.json）: 他セッション（eknzbh の mw_*）で反証の後も S/A として残った『価格だけで作れる規則』
（業種の勢い G3・G4・P9・F1b・F3g、業種ごとの10か月線 S3 L2/L3、株の勢い F1a1・ret_12_1、株の季節性 seas_6_10an、
ハロウィーン1.5倍）を、規則が作られ選ばれたデータ（1926-07 以降の CRSP・1975/1990 年以降の国際）と重ならない
1709〜1929 年の米国（Cowles の業種・Old NYSE の株）と英国（LSE の株と業種・イングランド銀行の指数）へ、作り直さずに当てる。
成績は『元の規則の独立の時代の単位』として返す（全体の事前登録 C5 の材料）。

約束（事前登録どおり）
- 規則・データ・格付けは night/nx_pre1926x_data.py（RULES・build_*・grade_era・rule_verdict）を import して使う（写さない）。
  最初に extract_sha256・rules_sha256・data_tool_sha256 が事前登録の値と一致することを確かめ、違えば止まる。
- 格付けは criteria_independent_era（E1〜E7・S/A/B/C・NA_short）。全体の C1〜C8 は使わない（事前登録 criteria.why_not_long_history）。
  C1〜C8 は『参考（事後・格付けに使わない）』として前半を訓練・後半を保有に読み替えた値だけ並べる。
- 統計は nx_common の excess_stats（NW ラグ12）・sharpe・rolling・dca・holm・p_one・maxdd をそのまま使う。
- 族ごとの Holm（A 9・B 3・C 1・D 8・H 1）。報告 R11 に 22 単位ぜんぶの Holm。
- 結果を見た後に足した分析は post_hoc に置き『事後』と明記し、格付けには使わない。
出力: out/nx_pre1926x.json
"""
import sys, os, re, json, math, hashlib, random, collections, statistics as _stat, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402
import nx_pre1926x_data as D  # noqa: E402


class _StatShim:
    """速さだけの細工（数値は1ビットも変えない・nx_stack.py と同じ）: nx_common.excess_stats は β の和の中で
    S.mean(sv)・S.mean(bv) を要素ごとに計算し直す（O(n²)）。同じ list オブジェクトへの mean の答えを覚えて返す。
    nx_common.py 自体は書き換えない"""

    def __init__(self):
        self._last = []

    def mean(self, x):
        for o, ln, r in self._last:
            if o is x and ln == len(x):
                return r
        r = _stat.mean(x)
        self._last = ([(x, len(x), r)] + self._last)[:4]
        return r

    def __getattr__(self, name):
        return getattr(_stat, name)


C.S = _StatShim()

BASE = C.BASE
PRE = json.load(open(os.path.join(BASE, 'out', 'nx_pre1926x_prereg.json')))
OUT = 'nx_pre1926x.json'
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ═════════════════════════ 0. 凍結の確認 ═════════════════════════
def check_frozen():
    tool_sha = hashlib.sha256(open(os.path.join(BASE, 'night', 'nx_pre1926x_data.py'), 'rb').read()).hexdigest()
    o = D.load_extract()
    got = {'extract_sha256': o['extract_sha256_recomputed'], 'rules_sha256': o['rules_sha256_now'], 'data_tool_sha256': tool_sha}
    want = {k: PRE['tools'][k] for k in got}
    ok = all(got[k] == want[k] for k in got) and o['extract_sha256'] == want['extract_sha256']
    st = D.selftest()
    res = {'sha_match': ok, 'got': got, 'want': want, 'selftest': {k: v for k, v in st}, 'selftest_all_ok': all(v for _, v in st)}
    if not ok or not res['selftest_all_ok']:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        raise SystemExit('凍結の確認に失敗（事前登録の sha と違う・または selftest が FAIL）→ 止まる')
    return o, res


EXT, FROZEN = check_frozen()
X = EXT['data']


def _ik(d):
    return {int(k): v for k, v in d.items()}


# ═════════════════════════ 1. データ（抽出から） ═════════════════════════
COW_M = [int(x) for x in X['cowles']['months']]
COW_IND = {int(n): _ik(s) for n, s in X['cowles']['ind'].items()}
COW_NAMES = {int(n): v for n, v in X['cowles']['names'].items()}
COW_MKT = _ik(X['cowles']['mkt'])
COW_MKT_P = _ik(X['cowles']['mkt_price'])
LSE_SEGS = [tuple(x) for x in X['lse']['segments']]
LSE_SEG_M = [D.month_range(a, z) for a, z in LSE_SEGS]
LSE_RET = {i: _ik(r) for i, r in X['lse']['ret'].items()}
LSE_IND = {s: _ik(d) for s, d in X['lse']['ind'].items()}
LSE_SECT = X['lse']['sect']
LSE_PLAG = {i: _ik(r) for i, r in X['lse']['plag'].items()}
LSE_CAP = {i: _ik(r) for i, r in X['lse']['cap'].items()}
LSE_DY = {i: _ik(r) for i, r in X['lse']['dy'].items()}
LSE_LAST = {i: int(v) for i, v in X['lse']['last'].items()}
NY_SEGS = [tuple(x) for x in X['nyse']['segments']]
NY_M = [D.month_range(a, z) for a, z in NY_SEGS]
NY_RET = {i: _ik(r) for i, r in X['nyse']['ret'].items()}
NY_FILLED = {i: [int(k) for k in v] for i, v in X['nyse']['filled'].items()}
NY_LAST = {i: int(v) for i, v in X['nyse']['last'].items()}
NY_PW = _ik(X['nyse']['pw_index_2020'])
UK_IDX = _ik(X['uk_index']['ret'])
RATES = {k: _ik(v) for k, v in X['rates'].items()}

DATA_R = {'cowles_ind': COW_IND, 'lse_ind': LSE_IND, 'lse_stk': LSE_RET, 'nyse_stk': NY_RET}
DATA_SEGS = {'cowles_ind': [COW_M], 'lse_ind': LSE_SEG_M, 'lse_stk': LSE_SEG_M, 'nyse_stk': NY_M}


def ew(R, segs):
    out = {}
    for ms in segs:
        out.update(D.build_ew_universe(R, ms))
    return out


BENCH = {'cowles_mkt': COW_MKT, 'lse_ew': ew(LSE_RET, LSE_SEG_M), 'nyse_ew': ew(NY_RET, NY_M)}
RULES = {r['id']: r for r in D.RULES}
UNIT_IDS = [u for f in 'ABCDH' for u in D.FAMILIES[f]]
NOT_TESTABLE = dict(D.NOT_TESTABLE_BY_SHAPE)


# ═════════════════════════ 2. 組み立て（区間ごと・data 道具の build_* をそのまま） ═════════════════════════
def build(r, R=None, skip=None, cost=None, exclude=(), spread=None, segs=None, weight='ew', cap=None, bench_R=None, period=None):
    """規則 r を区間ごとに組み立ててつなぐ → {'s','net','b','turn','w','R','rf'}。
    R・skip・cost・exclude・spread は報告の変形のときだけ渡す（主は規則の台帳の値）。
    bench_R を渡すと相手（等分の母集団）もその R から作り直す（R7・R8・R9 の両側の変形）"""
    kind = r['kind']
    cost = tuple(r['cost']) if cost is None else tuple(cost)
    if kind == 'halloween':
        a, z = period or r['period']
        rate = RATES[r['rf']]
        m = R if R is not None else UK_IDX
        x = D.build_halloween(m, rate, r['winter'], r['Lev'], spread if spread is not None else r['spread'], cost, a, z)
        b = {k: v for k, v in m.items() if a <= k <= z}
        return {'s': x['s'], 'net': x['net'], 'b': b, 'turn': None, 'w': None, 'R': None, 'rf': rate}
    R = R if R is not None else DATA_R[r['data']]
    segs = segs or DATA_SEGS[r['data']]
    skip = r.get('skip') if skip is None else skip   # 季節性（stk_seas）には skip が無い
    out = {'s': {}, 'net': {}, 'turn': {}, 'w': {}, 'b': {}}
    rf = RATES.get(r.get('rf', ''), None)
    if rf is None:
        rf = RATES['uk_cash'] if r['data'].startswith('lse') else RATES['us_cash']
    for ms in segs:
        if kind == 'ind_topk':
            x = D.build_ind_topk(R, ms, r['L'], skip, r['H'], cost, K=r.get('K'), frac=r.get('frac'), minN=r['minN'], exclude=exclude)
        elif kind == 'ind_multi':
            x = D.build_ind_multi(R, ms, r['windows'], skip, r['K'], r['minN'], cost, exclude=exclude)
        elif kind == 'ind_trend':
            x = D.build_ind_trend(R, ms, rf, r['sma'], r['Lev'], skip, cost, spread if spread is not None else r['spread'], r['fee'], exclude=exclude)
        elif kind == 'stk_mom':
            x = D.build_stk_mom(R, ms, r['L'], skip, r['frac'], r['min_port'], cost, weight=weight, cap=cap, exclude=exclude)
        elif kind == 'stk_seas':
            x = D.build_stk_seas(R, ms, r['years'], r['frac'], r['min_port'], cost, weight=weight, cap=cap, exclude=exclude)
        else:
            raise ValueError(kind)
        for k in ('s', 'net', 'w'):
            out[k].update(x[k])
        if 'turn' in x:
            out['turn'].update(x['turn'])
        if kind == 'ind_trend':
            out['b'].update(x['b'])
    if kind != 'ind_trend':
        out['b'] = ew(bench_R, segs) if bench_R is not None else BENCH[r['bench']]
    out['R'] = R
    out['rf'] = rf
    return out


# ═════════════════════════ 3. 統計の束 ═════════════════════════
def restrict(d, ks):
    return {k: d[k] for k in ks if k in d}


def seg_bounds(r):
    if r['kind'] == 'halloween':
        return [tuple(r['period'])]
    return {'cowles_ind': [(COW_M[0], COW_M[-1])], 'lse_ind': LSE_SEGS, 'lse_stk': LSE_SEGS, 'nyse_stk': NY_SEGS}[r['data']]


def dca_by_seg(s, b, bounds, years=20):
    out = {}
    for a, z in bounds:
        ss = {k: v for k, v in s.items() if a <= k <= z}
        bb = {k: v for k, v in b.items() if a <= k <= z}
        out[f'{a}-{z}'] = C.dca(ss, bb, years)
    return out


def bundle(x, r, full_only=False):
    """費用後（主）と費用前の excess_stats（全期間・前半・後半）・シャープ・最大下落・20年窓・20年積立"""
    s, net, b, rf = x['s'], x['net'], x['b'], x['rf']
    ks = sorted(set(net) & set(b))
    res = {'months': len(ks), 'first': ks[0] if ks else None, 'last': ks[-1] if ks else None}
    if len(ks) < 24:
        res['full_net'] = None
        return res
    (a1, z1), (a2, z2) = D.halves(ks)
    res['halves'] = [[a1, z1], [a2, z2]]
    res['full_net'] = C.excess_stats(net, b)
    if full_only:
        return res
    res['h1_net'] = C.excess_stats(net, b, a1, z1)
    res['h2_net'] = C.excess_stats(net, b, a2, z2)
    res['full_gross'] = C.excess_stats(s, b)
    res['h1_gross'] = C.excess_stats(s, b, a1, z1)
    res['h2_gross'] = C.excess_stats(s, b, a2, z2)
    fg, fn = res['full_gross'], res['full_net']
    res['cost_drag_ann'] = round(fg['ex_ann'] - fn['ex_ann'], 3) if fg and fn else None
    res['sharpe'] = {'rf_series': r.get('rf') or ('uk_cash' if r.get('data', '').startswith('lse') else 'us_cash'),
                     'full': [C.sharpe(net, rf, ks[0], ks[-1]), C.sharpe(b, rf, ks[0], ks[-1])],
                     'h1': [C.sharpe(net, rf, a1, z1), C.sharpe(b, rf, a1, z1)],
                     'h2': [C.sharpe(net, rf, a2, z2), C.sharpe(b, rf, a2, z2)],
                     'note': '[戦略（費用後）, 相手]・その単位の現金を引いた年率。格付け（E5）に使うのは timing の規則だけ'}
    res['maxdd'] = {'s_net': round(C.maxdd(restrict(net, ks)) * 100, 2), 'b': round(C.maxdd(restrict(b, ks)) * 100, 2),
                    'note': '%・定義できる月だけをつないだ（区間の切れ目はつないで数える）'}
    res['roll20'] = C.rolling(restrict(net, ks), restrict(b, ks), 20)
    res['dca20'] = dca_by_seg(restrict(net, ks), restrict(b, ks), seg_bounds(r), 20)
    return res


def contrib_top(x, r):
    """E7 の最大寄与の構成要素（業種・株）と上位5つ"""
    if r['kind'] == 'halloween':
        return None, None
    if r['kind'] == 'ind_trend':
        c = D.contributions_trend(x['w'], x['R'], x['rf'], None)
    else:
        c = D.contributions(x['w'], x['R'], x['b'])
    top5 = sorted(c.items(), key=lambda kv: -kv[1])[:5]
    return top5[0][0], [[k, round(v, 4)] for k, v in top5]


def cname(r, k):
    if r['data'] == 'cowles_ind':
        return f'{k} {COW_NAMES.get(k, "")}'
    return str(k)


# ═════════════════════════ 4. 主: 22 単位 ═════════════════════════
def run_main():
    units = {}
    for uid in UNIT_IDS:
        r = RULES[uid]
        x = build(r)
        st = bundle(x, r)
        top, top5 = contrib_top(x, r)
        dt = None
        if top is not None:
            xd = build(r, exclude=(top,))
            dt = C.excess_stats(xd['net'], xd['b'])
        turn = None
        if x['turn']:
            tv = list(x['turn'].values())
            turn = round(_stat.mean(tv) * 0.5 * 12, 3)
        elif r['kind'] in ('ind_trend', 'halloween'):
            u = r['cost'][1]
            ks = [k for k in x['s'] if k in x['net']]
            turn = round(_stat.mean([(x['s'][k] - x['net'][k]) / u for k in ks]) * 12, 3) if ks else None
        units[uid] = {'x': x, 'stats': st, 'drop_top': {'excluded': cname(r, top) if top is not None else None, 'top5_contrib': top5,
                                                         'net_vs_b': dt}, 'turnover_ann': turn}
        fn = st.get('full_net')
        log(uid, 'months', st['months'], 'full_net', fn and (fn['ex_ann'], fn['t'], fn['cagr_diff']))
    return units


def grade_units(units, fam_of, holm_key='E4'):
    """族ごとの Holm → grade_era"""
    pone = {}
    for uid, u in units.items():
        fn = u['stats'].get('full_net')
        short = u['stats']['months'] < D.MIN_MONTHS
        pone[uid] = 1.0 if (short or not fn or fn['t'] is None) else C.p_one(fn['t'])
    fam_holm = {}
    for f in sorted(set(fam_of.values())):
        ids = [u for u in units if fam_of[u] == f]
        fam_holm.update(C.holm({u: pone[u] for u in ids}))
    out = {}
    for uid, u in units.items():
        r = RULES[uid] if uid in RULES else u['rule']
        st = u['stats']
        timing = bool(r.get('timing'))
        sh = None
        if timing and st.get('sharpe'):
            sh = {'h1': tuple(st['sharpe']['h1']), 'h2': tuple(st['sharpe']['h2'])}
        g, c = D.grade_era(st.get('full_net'), st.get('h1_net'), st.get('h2_net'), fam_holm.get(uid),
                           drop_top_net=u['drop_top']['net_vs_b'] if u.get('drop_top') else None,
                           sharpe_halves=sh, timing=timing, drop_top_applies=(r['kind'] != 'halloween'), months=st['months'])
        out[uid] = {'grade': g, 'criteria': c, 'p_one': round(pone[uid], 5), 'holm_p_one_family': fam_holm.get(uid)}
    return out


def ref_c1_c8(st, r, holm_hold):
    """参考（事後・格付けに使わない）: 前半を『訓練』・後半を『保有』に読み替えて nx_common.grade を当てた値"""
    if not st.get('full_net'):
        return None
    g, c = C.grade(st['full_gross'], st['h1_gross'], st['h2_gross'], st['roll20'], cost_hold=st['h2_net'], repl=None,
                   family_holm_p=holm_hold, sharpe_pair={'train': tuple(st['sharpe']['h1']), 'hold': tuple(st['sharpe']['h2'])} if r.get('timing') else None,
                   leveraged_or_timing=bool(r.get('timing')))
    return {'grade_reference_only': g, 'criteria': c,
            'mapping': '訓練＝前半（費用前）・保有＝後半（費用前、C6 は後半の費用後）・C4＝全期間の転がる20年窓（費用後）・C7＝全期間の費用前の t≥3 か 後半（費用前・両側 p）の族内 Holm<0.05・C8＝前半/後半の費用後のシャープ（timing だけ）・C5 は N/A（mw の約束: C1・C2・C3・C7 は費用前、C4・C6・C8 は費用後）',
            'note': '事前登録の格付けではない（criteria.why_not_long_history）。他の角度と並べるための読み替えだけ'}


# ═════════════════════════ 5. 健全性の点検（成績ではなく形） ═════════════════════════
def corr_d(a, b, ks=None):
    ks = sorted(set(a) & set(b)) if ks is None else ks
    if len(ks) < 24:
        return None
    return round(C.corr([a[k] for k in ks], [b[k] for k in ks]), 4)


def shiller_price_changes():
    import xlrd
    b = C.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', name='shiller_ie_data.xls', max_age_days=3650)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    rows = []
    for i in range(sh.nrows):
        r = sh.row_values(i)
        if not isinstance(r[0], float) or not isinstance(r[1], float):
            continue
        y = int(r[0]); m = int(round((r[0] - y) * 100))
        if 1 <= m <= 12:
            rows.append((y * 100 + m, r[1]))
    out = {}
    for (p, pp), (k, pk) in zip(rows, rows[1:]):
        if D.madd(p, 1) == k and pp:
            out[k] = pk / pp - 1
    return out


def sanity(units):
    res = {}
    # (2) Cowles C-1 − P-1 の月の差
    ks = sorted(k for k in set(COW_MKT) & set(COW_MKT_P) if k not in (191412,))
    dm = _stat.mean([COW_MKT[k] - COW_MKT_P[k] for k in ks])
    res['cowles_C1_minus_P1_monthly_mean'] = {'value': round(dm, 5), 'range': [0.0025, 0.006], 'ok': 0.0025 <= dm <= 0.006}
    # (3) Cowles P-1 と Shiller の株価の月の変化
    try:
        sp = shiller_price_changes()
        ks2 = [k for k in sorted(set(sp) & set(COW_MKT_P)) if k <= 192606 and k != 191412]
        c = corr_d(COW_MKT_P, sp, ks2)
        res['cowles_P1_vs_shiller_price'] = {'corr': c, 'n': len(ks2), 'threshold': 0.99, 'ok': c is not None and c >= 0.99}
    except Exception as e:  # noqa
        res['cowles_P1_vs_shiller_price'] = {'error': str(e), 'ok': None}
    # (4) 相手どうしの形
    cew = ew(COW_IND, [COW_M])
    res['cowles_ew_ind_vs_C1'] = {'corr': corr_d(cew, COW_MKT), 'threshold': 0.85}
    res['cowles_ew_ind_vs_C1']['ok'] = (res['cowles_ew_ind_vs_C1']['corr'] or 0) >= 0.85
    lk = [k for k in sorted(set(BENCH['lse_ew']) & set(UK_IDX)) if 187101 <= k <= 191406]
    res['lse_ew_vs_boe_1871_1914'] = {'corr': corr_d(BENCH['lse_ew'], UK_IDX, lk), 'n': len(lk), 'threshold': 0.6}
    res['lse_ew_vs_boe_1871_1914']['ok'] = (res['lse_ew_vs_boe_1871_1914']['corr'] or 0) >= 0.6
    res['nyse_ew_vs_gip_pw2020'] = {'corr': corr_d(BENCH['nyse_ew'], NY_PW), 'threshold': 0.8}
    res['nyse_ew_vs_gip_pw2020']['ok'] = (res['nyse_ew_vs_gip_pw2020']['corr'] or 0) >= 0.8
    stop = [k for k in ('cowles_ew_ind_vs_C1', 'lse_ew_vs_boe_1871_1914', 'nyse_ew_vs_gip_pw2020') if not res[k]['ok']]
    res['stop_on_shape'] = stop
    # (5) 実データでも先読みなし
    la = {}
    rnd = random.Random(11)
    for uid in UNIT_IDS:
        r = RULES[uid]
        x = units[uid]['x']
        ks = sorted(x['net'])
        if len(ks) < 10:
            la[uid] = None
            continue
        cut = ks[len(ks) // 2]
        if r['kind'] == 'halloween':
            m2 = {k: (v if k <= cut else rnd.gauss(0, 0.2)) for k, v in UK_IDX.items()}
            y = build(r, R=m2)
        else:
            R0 = DATA_R[r['data']]
            R2 = {n: {m: (v if m <= cut else rnd.gauss(0, 0.2)) for m, v in d.items()} for n, d in R0.items()}
            y = build(r, R=R2)
        la[uid] = all(abs(x['net'][m] - y['net'].get(m, 1e9)) < 1e-12 for m in ks if m <= cut)
    res['no_lookahead_real_data'] = la
    res['no_lookahead_all_ok'] = all(v for v in la.values() if v is not None)
    # (6) 組を作れる月数（事前登録の data.definable_months_by_shape と ±1 で一致するか）
    dfn = PRE['data']['definable_months_by_shape']
    shape_n = {}
    for k, v in dfn.items():
        if k == 'note':
            continue
        m = re.search(r'\d[\d,]*', v)
        n = int(m.group(0).replace(',', '')) if m else None
        ids = [k]
        if '/' in k:
            base, alt = k.split('/', 1)
            ids = [base, base.rsplit('_', 1)[0] + '_' + alt]
        for i in ids:
            shape_n[i] = (v, n)
    cmp_ = {}
    for uid in UNIT_IDS:
        txt, n_shape = shape_n.get(uid, (None, None))
        n_s = len(units[uid]['x']['net'])
        n_sb = units[uid]['stats']['months']
        cmp_[uid] = {'shape': txt, 'shape_n': n_shape, 'strategy_months': n_s, 's_and_b_months': n_sb,
                     'within_1': (n_shape is not None and abs(n_shape - n_s) <= 1)}
    res['definable_months'] = cmp_
    # (7) Holm の族の数
    res['holm_family_sizes'] = {f: len(v) for f, v in D.FAMILIES.items()}
    res['holm_family_sizes_ok'] = res['holm_family_sizes'] == {'A': 9, 'B': 3, 'C': 1, 'D': 8, 'H': 1}
    # (8) 欠測を 0 で埋めていない・区間をまたがない
    zero = {}
    for uid in UNIT_IDS:
        x = units[uid]['x']
        ks = sorted(set(x['net']))
        gap = [k for k in ks if 190801 <= k <= 191501] if RULES[uid].get('data', '').startswith('lse') else []
        zero[uid] = {'months_in_lse_gap': len(gap), 'b_months_dropped': len(set(x['b']) - set(x['net'])) if x['b'] else None,
                     's_months_without_b': len(set(x['net']) - set(x['b']))}
    res['missing_not_zero'] = zero
    return res


# ═════════════════════════ 6. 報告（格付けしない） ═════════════════════════
def ac1(d, ks=None):
    ks = sorted(d) if ks is None else ks
    pairs = [(d[a], d[b]) for a, b in zip(ks, ks[1:]) if D.madd(a, 1) == b or (a == 191407 and b == 191412)]
    if len(pairs) < 24:
        return None
    return round(C.corr([p[0] for p in pairs], [p[1] for p in pairs]), 4)


def build_ind_seas(R, months, a, bb, frac, minN, cost, exclude=()):
    """R4 の F16g（業種の季節性・eknzbh mw_momentum_prereg5 の F16 の作り方）: 月の番号 f の末に、翌月 f+1 と同じ暦月の a〜b 年前の
    業種のリターンの平均（その年数ぶん全部そろう業種だけ・同じ区間の中）で並べ、上位 K = max(2, 四捨五入(割合×N)) を等分で1か月"""
    names = [n for n in R if n not in exclude]
    coh = {}
    for f in range(len(months) - 1):
        nxt = months[f + 1]
        lags = [D.madd(nxt, -12 * y) for y in range(a, bb + 1)]
        if min(lags) < months[0]:
            continue
        sc = []
        for n in names:
            d = R[n]
            if any(m not in d for m in lags):
                continue
            sc.append((-math.fsum(d[m] for m in lags) / len(lags), str(n), n))
        N = len(sc)
        k = max(2, D.round_half_up(frac * N))
        if N < minN or N < k:
            continue
        sc.sort()
        coh[f] = [n for _, _, n in sc[:k]]
    s, net, turn, W = D._hold(months, coh, 1, R, cost)
    return {'s': s, 'net': net, 'turn': turn, 'w': W}


def r4_grid():
    out = {}
    forms = [('1-0', 1, 0), ('3-0', 3, 0), ('6-0', 6, 0), ('9-0', 9, 0), ('12-0', 12, 0), ('12-1', 11, 1)]
    seas = [(1, 1), (2, 5), (6, 10), (11, 15), (16, 20), (1, 10), (1, 20)]
    cost = ('one', 0.0005)
    for dname, R, segs, b in (('cowles', COW_IND, [COW_M], COW_MKT), ('lse', LSE_IND, LSE_SEG_M, BENCH['lse_ew'])):
        bew = ew(R, segs)
        rows = []
        for fn, L, sk in forms:
            for H in (1, 3, 6, 12):
                for fr in (0.15, 0.30):
                    s, net = {}, {}
                    for ms in segs:
                        x = D.build_ind_topk(R, ms, L, sk, H, cost, frac=fr, minN=5)
                        s.update(x['s']); net.update(x['net'])
                    e = C.excess_stats(net, b)
                    e2 = C.excess_stats(net, bew)
                    rows.append({'grid': 'F3g', 'form': fn, 'H': H, 'K': fr, 'months': len(net),
                                 'ex_ann': e and e['ex_ann'], 't': e and e['t'], 'cagr_diff': e and e['cagr_diff'],
                                 'vs_ew_ind_ex_ann': e2 and e2['ex_ann'], 'vs_ew_ind_t': e2 and e2['t']})
        for a, bb in seas:
            for fr in (0.15, 0.30):
                s, net = {}, {}
                for ms in segs:
                    x = build_ind_seas(R, ms, a, bb, fr, 5, cost)
                    s.update(x['s']); net.update(x['net'])
                e = C.excess_stats(net, b) if len(net) >= 24 else None
                e2 = C.excess_stats(net, bew) if len(net) >= 24 else None
                rows.append({'grid': 'F16g', 'years': f'{a}-{bb}', 'K': fr, 'months': len(net),
                             'ex_ann': e and e['ex_ann'], 't': e and e['t'], 'cagr_diff': e and e['cagr_diff'],
                             'vs_ew_ind_ex_ann': e2 and e2['ex_ann'], 'vs_ew_ind_t': e2 and e2['t']})

        def summ(rs, key='ex_ann', tkey='t'):
            v = [x for x in rs if x[key] is not None]
            return {'n': len(v), 'positive': sum(1 for x in v if x[key] > 0), 'share_positive': round(sum(1 for x in v if x[key] > 0) / len(v), 3) if v else None,
                    't_ge_2': sum(1 for x in v if (x[tkey] or 0) >= 2), 'share_t_ge_2': round(sum(1 for x in v if (x[tkey] or 0) >= 2) / len(v), 3) if v else None,
                    't_le_-2': sum(1 for x in v if (x[tkey] or 0) <= -2), 'not_definable': len(rs) - len(v)}
        out[dname] = {'rows': rows,
                      'summary_vs_graded_bench': {'F3g': summ([x for x in rows if x['grid'] == 'F3g']), 'F16g': summ([x for x in rows if x['grid'] == 'F16g'])},
                      'summary_vs_ew_industries': {'F3g': summ([x for x in rows if x['grid'] == 'F3g'], 'vs_ew_ind_ex_ann', 'vs_ew_ind_t'),
                                                   'F16g': summ([x for x in rows if x['grid'] == 'F16g'], 'vs_ew_ind_ex_ann', 'vs_ew_ind_t')},
                      'bench': 'cowles C-1（時価加重・総リターン）' if dname == 'cowles' else 'LSE の普通株の等分（価格だけ）',
                      'null': '帰無なら正の割合 約50%・t≥2 約2.5%（格子は強く重なる＝独立ではない）'}
    return out


def r3_costs(units):
    out = {}
    plc = {'F1a1_top_decile': 4.0, 'ret_12_1_tercile': 1.5, 'seas_6_10an_tercile': 12.0}
    for uid in UNIT_IDS:
        r = RULES[uid]
        row = {}
        for u in (0.005, 0.01):
            x = build(r, cost=(r['cost'][0], u))
            e = C.excess_stats(x['net'], x['b'])
            ks = sorted(set(x['net']) & set(x['b']))
            (a1, z1), (a2, z2) = D.halves(ks)
            h1, h2 = C.excess_stats(x['net'], x['b'], a1, z1), C.excess_stats(x['net'], x['b'], a2, z2)
            row[f'unit_{u}'] = {'full': e, 'h1_cagr_diff': h1 and h1['cagr_diff'], 'h2_cagr_diff': h2 and h2['cagr_diff']}
        if r['key'] in plc:
            x = units[uid]['x']
            s2 = C.apply_cost(x['s'], plc[r['key']], r['cost'][1])
            row['placeholder_turnover'] = {'annual_oneway': plc[r['key']], 'unit': r['cost'][1], 'full': C.excess_stats(s2, x['b'])}
        if r['kind'] == 'ind_trend':
            x = build(r, spread=0.01)
            row['spread_1pct'] = {'full': C.excess_stats(x['net'], x['b'])}
        if r['kind'] == 'halloween':
            x = build(r, spread=0.01)
            row['spread_1pct'] = {'full': C.excess_stats(x['net'], x['b'])}
        out[uid] = row
    return {'rows': out, 'note': '各規則の費用の式の形（two＝両側 Σ|Δw|×単価・one＝片道 ½Σ|Δw|×単価・moved＝出入り×L×単価・dL＝|ΔL|×単価）はそのままで単価だけ 0.50%・1.00% に替えた。'
                                 '置き値の版は mw_momentum の F1a1 年400%・mw_intl の ret_12_1 年150%・mw_momentum_prereg3 の seas_6_10an 年1200% × この角度の単価（英国 0.30%・米国 0.10%）を月割りで費用前の系列から引いた'}


def r1_asis(units):
    ids = [u for u in UNIT_IDS if RULES[u].get('asis_skip', RULES[u].get('skip')) != RULES[u].get('skip')]
    res = {}
    for uid in ids:
        r = RULES[uid]
        x = build(r, skip=r['asis_skip'])
        st = bundle(x, r)
        top, top5 = contrib_top(x, r)
        xd = build(r, skip=r['asis_skip'], exclude=(top,)) if top is not None else None
        res[uid] = {'x': x, 'stats': st, 'drop_top': {'excluded': cname(r, top), 'net_vs_b': C.excess_stats(xd['net'], xd['b']) if xd else None}, 'rule': r}
    g = grade_units(res, {u: RULES[u]['fam'] for u in res})
    out = {}
    for uid in ids:
        st = res[uid]['stats']
        out[uid + '_asis'] = {'skip': RULES[uid]['asis_skip'], 'grade_report_only': g[uid]['grade'], 'criteria': g[uid]['criteria'],
                              'holm_p_one_family_asis': g[uid]['holm_p_one_family'],
                              'full_net': st.get('full_net'), 'h1_net': st.get('h1_net'), 'h2_net': st.get('h2_net'),
                              'full_gross': st.get('full_gross'), 'sharpe': st.get('sharpe'), 'drop_top': res[uid]['drop_top'],
                              'gap_version_full_net': units[uid]['stats'].get('full_net')}
    return {'rows': out, 'note': '報告（格付けしない）: 元のまま（1か月あけない）。Holm は元のままの版どうしで族ごと（A 7・D 6）。'
                                 '1か月あけた版との差は Working（1960）の月平均の見かけの自己相関の見当'}


def r2_alt(units):
    out = {}
    cew = ew(COW_IND, [COW_M])
    lew_ind = ew(LSE_IND, LSE_SEG_M)
    for uid in UNIT_IDS:
        r = RULES[uid]
        x = units[uid]['x']
        alts = {}
        if r['data'] == 'cowles_ind':
            if r['kind'] == 'ind_trend':
                alts['cowles_C1'] = COW_MKT
            else:
                alts['cowles_ew_industries'] = cew
        elif r['data'] == 'lse_ind':
            alts['boe_index_price'] = UK_IDX
            if r['kind'] != 'ind_trend':
                alts['lse_ew_industries'] = lew_ind
        elif r['data'] == 'lse_stk':
            alts['boe_index_price'] = UK_IDX
        elif r['data'] == 'nyse_stk':
            alts['gip_pw_2020'] = NY_PW
            alts['cowles_P1_price'] = COW_MKT_P
        row = {}
        for k, b in alts.items():
            ks = sorted(set(x['net']) & set(b))
            if len(ks) < 24:
                row[k] = None
                continue
            (a1, z1), (a2, z2) = D.halves(ks)
            e = C.excess_stats(x['net'], b)
            h1, h2 = C.excess_stats(x['net'], b, a1, z1), C.excess_stats(x['net'], b, a2, z2)
            row[k] = {'full_net': e, 'h1_cagr_diff': h1 and h1['cagr_diff'], 'h2_cagr_diff': h2 and h2['cagr_diff']}
        out[uid] = row
    return {'rows': out, 'note': '報告（格付けしない）: benchmark.reported_not_graded の相手。費用後の戦略との差'}


def win_stats(x, windows, drop=None):
    out = {}
    for name, (a, z) in windows.items():
        net, b = x['net'], x['b']
        if drop:
            net = {k: v for k, v in net.items() if not (drop[0] <= k <= drop[1])}
        e = C.excess_stats(net, b, a, z)
        out[name] = e
    return out


def r5_sub(units):
    out = {}
    for uid in UNIT_IDS:
        r = RULES[uid]
        x = units[uid]['x']
        if r.get('data') == 'cowles_ind':
            w = win_stats(x, {'1871-1898': (187101, 189812), '1899-1926-06': (189901, 192606)})
            w['full_without_1914-07_1918-12'] = win_stats(x, {'full': (0, 999999)}, drop=(191407, 191812))['full']
        elif r.get('data', '').startswith('lse'):
            w = win_stats(x, {'seg1_1869-1907': (186902, 190712), 'seg2_1915-1929': (191502, 192912), '1869-1887': (186902, 188712), '1888-1907': (188801, 190712)})
        elif r.get('data') == 'nyse_stk':
            w = win_stats(x, {'1871-1898': (187101, 189812), '1899-1925': (189901, 192512), 'before_1871': (181501, 187012)})
        else:
            w = win_stats(x, {'1709-1811-08_Neal': (170905, 181108), '1811-09-1870_GRS_Acheson': (181109, 187012), '1871-1914-06_SmithHorne': (187101, 191406)})
            xr = build(r, period=D.UK_HAL_REPORT)
            w['1915-02-1925-12_report_period'] = C.excess_stats(xr['net'], xr['b'])
        out[uid] = w
    return {'rows': out, 'note': '報告（格付けしない）: 部分期間の費用後の excess_stats'}


def r7_lse(units):
    out = {}
    vw_m = [D.month_range(186902, 188712)]
    for uid in ('B_F1a1_top_decile', 'B_ret_12_1_tercile', 'B_seas_6_10an_tercile'):
        r = RULES[uid]
        row = {}
        # (a) 時価加重 1870〜1887（株数の分かる株だけで持つ・相手も時価加重）
        x = build(r, segs=vw_m, weight='vw', cap=LSE_CAP)
        bvw = {}
        for m in vw_m[0]:
            mem = [(LSE_CAP[i][m], LSE_RET[i][m]) for i in LSE_RET if m in LSE_RET[i] and m in LSE_CAP.get(i, {})]
            tot = math.fsum(c for c, _ in mem)
            if tot > 0:
                bvw[m] = math.fsum(c * v for c, v in mem) / tot
        row['vw_1870_1887'] = {'vs_vw_universe': C.excess_stats(x['net'], bvw), 'vs_ew_universe': C.excess_stats(x['net'], BENCH['lse_ew'], 186902, 188712)}
        # (b) p_{t−1} < £1 の月を外した等分（両側）
        Rp = {i: {m: v for m, v in d.items() if LSE_PLAG.get(i, {}).get(m) is not None and LSE_PLAG[i][m] >= 1} for i, d in LSE_RET.items()}
        Rp = {i: d for i, d in Rp.items() if d}
        x = build(r, R=Rp, bench_R=Rp)
        row['exclude_price_below_1'] = C.excess_stats(x['net'], x['b'])
        # (c) 配当の近似を両側に足した版（分かる月だけ足す）と、良い側と母集団の配当利回りの差
        Rd = {i: {m: v + LSE_DY.get(i, {}).get(m, 0.0) for m, v in d.items()} for i, d in LSE_RET.items()}
        x = build(r, R=Rd, bench_R=Rd)
        row['with_dividend_approx'] = C.excess_stats(x['net'], x['b'])
        xw = units[uid]['x']
        gaps, cov_s, cov_u = [], [], []
        for m, w in xw['w'].items():
            kn = [(wt, LSE_DY[i][m]) for i, wt in w.items() if m in LSE_DY.get(i, {})]
            un = [LSE_DY[i][m] for i in LSE_RET if m in LSE_RET[i] and m in LSE_DY.get(i, {})]
            nu = sum(1 for i in LSE_RET if m in LSE_RET[i])
            if not kn or not un:
                continue
            ws = math.fsum(wt for wt, _ in kn)
            gaps.append(math.fsum(wt * v for wt, v in kn) / ws - math.fsum(un) / len(un))
            cov_s.append(ws)
            cov_u.append(len(un) / nu)
        row['div_yield_gap_good_minus_universe_ann_pct'] = round(_stat.mean(gaps) * 12 * 100, 3) if gaps else None
        row['div_known_share'] = {'strategy_weight': round(_stat.mean(cov_s), 3) if cov_s else None, 'universe_count': round(_stat.mean(cov_u), 3) if cov_u else None}
        out[uid] = row
    return {'rows': out, 'note': '報告（格付けしない）: (a) 時価加重は 1869-02〜1887-12 の区間1の頭だけ（形成は全株・持つのは株数の分かる株）(b) p_{t−1}<£1 の月のリターンを落とした R で両側を作り直した（形成の窓にも効く）(c) 月の配当利回りの近似（直近4回の配当率×払込額÷12÷p_{t−1}）を分かる月だけ両側に足した。分からない月は足していない＝0 と読んだのと同じ向きの偏りが残る（被覆は div_known_share）'}


def delist_lb(R, last, segs_bounds, open_months):
    """区間の終わりより前に価格が途切れて戻らない株に、途切れた翌月 −30%（相手の母集団がその月に開いているときだけ）"""
    R2 = {i: dict(d) for i, d in R.items()}
    n = 0
    for i, d in R2.items():
        L = last.get(i)
        if L is None or not d:
            continue
        seg = next(((a, z) for a, z in segs_bounds if a <= L <= z), None)
        if seg is None or L >= seg[1]:
            continue
        nm = D.madd(L, 1)
        if nm in open_months and nm not in d:
            d[nm] = -0.30
            n += 1
    return R2, n


def r8_lb(units):
    out = {}
    lse_open = set(BENCH['lse_ew'])
    Rl, nl = delist_lb(LSE_RET, LSE_LAST, LSE_SEGS, lse_open)
    Rn, nn = delist_lb(NY_RET, NY_LAST, NY_SEGS, set(BENCH['nyse_ew']))
    for uid in ('B_F1a1_top_decile', 'B_ret_12_1_tercile', 'B_seas_6_10an_tercile'):
        x = build(RULES[uid], R=Rl, bench_R=Rl)
        out[uid] = C.excess_stats(x['net'], x['b'])
    x = build(RULES['C_ret_12_1_tercile'], R=Rn, bench_R=Rn)
    out['C_ret_12_1_tercile'] = C.excess_stats(x['net'], x['b'])
    # D: 業種を作り直す（−30% の月の業種は、最後の区切りの業種で近似）
    sect2 = {i: [list(x) for x in runs] for i, runs in LSE_SECT.items()}
    for i, d in Rl.items():
        L = LSE_LAST.get(i)
        nm = D.madd(L, 1) if L else None
        if nm is not None and d.get(nm) == -0.30 and nm not in LSE_RET[i] and sect2.get(i):
            sect2[i].append([nm, nm, sect2[i][-1][2]])
    LI2, _ = D.lse_industries({'ret': Rl, 'sect': sect2})
    blse = ew(Rl, LSE_SEG_M)
    for uid in D.FAMILIES['D']:
        r = RULES[uid]
        x = build(r, R=LI2)
        b = x['b'] if r['kind'] == 'ind_trend' else blse
        out[uid] = C.excess_stats(x['net'], b)
    return {'rows': out, 'n_penalised': {'lse_stocks': nl, 'nyse_stocks': nn},
            'note': '報告（格付けしない）: 途切れた翌月に −30% を戦略と相手の両方に置いた下限版。D は −30% を最後の区切りの業種に入れて業種を作り直した（近似）'}


def r9_filled(units):
    Rn = {}
    for i, d in NY_RET.items():
        bad = set()
        for m in NY_FILLED.get(i, []):
            bad.add(m); bad.add(D.madd(m, 1))
        Rn[i] = {m: v for m, v in d.items() if m not in bad}
    x = build(RULES['C_ret_12_1_tercile'], R=Rn, bench_R=Rn)
    return {'C_ret_12_1_tercile': C.excess_stats(x['net'], x['b']),
            'note': '報告（格付けしない）: 前後の平均で埋めたと見込まれる月の価格を欠測にした（その月と翌月のリターンを落とす）版。相手も同じ R から'}


def r10_working():
    out = {}
    out['cowles_C1'] = ac1(COW_MKT)
    out['cowles_P1'] = ac1(COW_MKT_P)
    out['cowles_ew_industries'] = ac1(ew(COW_IND, [COW_M]))
    v = [ac1(s) for s in COW_IND.values()]
    v = [x for x in v if x is not None]
    out['cowles_industries_mean_ac1'] = round(_stat.mean(v), 4) if v else None
    out['lse_ew_seg1'] = ac1({k: x for k, x in BENCH['lse_ew'].items() if k <= 190712})
    out['lse_ew_seg2'] = ac1({k: x for k, x in BENCH['lse_ew'].items() if k >= 191502})
    v = [ac1({k: x for k, x in s.items() if k <= 190712}) for s in LSE_IND.values()]
    v = [x for x in v if x is not None]
    out['lse_industries_mean_ac1_seg1'] = round(_stat.mean(v), 4) if v else None
    out['nyse_ew'] = ac1(BENCH['nyse_ew'])
    out['uk_index_1709_1914'] = ac1({k: x for k, x in UK_IDX.items() if 170905 <= k <= 191406})
    out['uk_index_1871_1914'] = ac1({k: x for k, x in UK_IDX.items() if 187101 <= k <= 191406})
    out['note'] = '報告: 相手と業種の月次リターンの1次の自己相関（規則の成績ではない）。月平均の差なら元が自己相関なしでも +0.25（Working 1960）'
    return out


# ═════════════════════════ 7. 本体 ═════════════════════════
def main():
    t0 = datetime.datetime.now()
    units = run_main()
    fam_of = {u: RULES[u]['fam'] for u in UNIT_IDS}
    G = grade_units(units, fam_of)
    # R11: 22 単位ぜんぶの Holm
    pone = {u: G[u]['p_one'] for u in UNIT_IDS}
    prog_holm = C.holm(pone)
    # 参考の C1〜C8（後半の族内 Holm は両側 p）
    hold_p = {}
    for u in UNIT_IDS:
        h2 = units[u]['stats'].get('h2_gross')
        hold_p[u] = h2['p'] if h2 and h2['p'] is not None else 1.0
    fam_hold_holm = {}
    for f in 'ABCDH':
        fam_hold_holm.update(C.holm({u: hold_p[u] for u in UNIT_IDS if fam_of[u] == f}))
    log('sanity...')
    san = sanity(units)
    if san['stop_on_shape']:
        log('⚠ 相手どうしの形の点検で閾値を下回った:', san['stop_on_shape'])
    tested = []
    for u in UNIT_IDS:
        r = RULES[u]
        st = units[u]['stats']
        tested.append({
            'id': u, 'family': r['fam'], 'key': r['key'], 'src_rules': r['src'], 'kind': r['kind'], 'what': r['what'],
            'data': r.get('data'), 'bench': r.get('bench'), 'cost_spec': list(r['cost']), 'timing': bool(r.get('timing')),
            'grade': G[u]['grade'], 'criteria_E': G[u]['criteria'], 'p_one': G[u]['p_one'], 'holm_p_one_family': G[u]['holm_p_one_family'],
            'holm_p_one_program22': prog_holm.get(u),
            'months': st['months'], 'first': st['first'], 'last': st['last'], 'halves': st.get('halves'),
            'full_net': st.get('full_net'), 'h1_net': st.get('h1_net'), 'h2_net': st.get('h2_net'),
            'full_gross': st.get('full_gross'), 'h1_gross': st.get('h1_gross'), 'h2_gross': st.get('h2_gross'),
            'cost_drag_ann_pct': st.get('cost_drag_ann'), 'turnover_ann_oneway': units[u]['turnover_ann'],
            'roll20_net': st.get('roll20'), 'dca20_net_by_segment': st.get('dca20'),
            'maxdd_pct': st.get('maxdd'), 'sharpe': st.get('sharpe'),
            'drop_top': units[u]['drop_top'],
            'train_hold_note': '訓練（〜2006）・保有（2007〜）は無い（この角度は 1709〜1929 年だけ）。前半・後半（数で二分）を代わりに置いた＝h1/h2',
            'C1_C8_reference': ref_c1_c8(st, r, fam_hold_holm.get(u)),
        })
    for u, why in NOT_TESTABLE.items():
        tested.append({'id': u, 'family': u[0], 'grade': 'NA_not_testable_by_shape', 'why': why,
                       'src_rules': RULES[u]['src'] if u in RULES else None})
    # 元の規則ごとのまとめ
    stu = PRE['why_new']['survivor_to_unit']
    gmap = {t['id']: t['grade'] for t in tested}
    verdicts = {}
    for src, lst in stu.items():
        ids = [x.split('（')[0] for x in lst]
        gs = [gmap.get(i, 'NA') for i in ids]
        verdicts[src] = {'units': dict(zip(ids, gs)), 'verdict': D.rule_verdict(gs)}
    log('reports...')
    rep = {}
    rep['R1_asis'] = r1_asis(units); log('R1 done')
    rep['R2_alt_benchmarks'] = r2_alt(units); log('R2 done')
    rep['R3_costs'] = r3_costs(units); log('R3 done')
    rep['R4_grid_breadth'] = r4_grid(); log('R4 done')
    rep['R5_subperiods'] = r5_sub(units); log('R5 done')
    rep['R6_rolling'] = {u: {'roll20_net': units[u]['stats'].get('roll20'), 'dca20_net_by_segment': units[u]['stats'].get('dca20')} for u in UNIT_IDS}
    rep['R7_lse_variants'] = r7_lse(units); log('R7 done')
    rep['R8_delisting_lower_bound'] = r8_lb(units); log('R8 done')
    rep['R9_nyse_filled'] = r9_filled(units); log('R9 done')
    rep['R10_working_diagnostics'] = r10_working()
    rep['R11_program_holm'] = {'holm_p_one': prog_holm, 'pass_0.05': [u for u, p in prog_holm.items() if p < 0.05]}
    rep['R12_turnover'] = {u: units[u]['turnover_ann'] for u in UNIT_IDS}
    grades = collections.Counter(G[u]['grade'] for u in UNIT_IDS)
    out = {
        'angle': 'nx_pre1926x', 'prereg': 'out/nx_pre1926x_prereg.json', 'generated': datetime.date.today().isoformat(),
        'frozen_check': FROZEN,
        'criteria_used': 'criteria_independent_era（nx_pre1926x_data.grade_era）。C1〜C8 は参考（事後・前半/後半の読み替え）だけ',
        'grade_counts': dict(grades),
        'tested': tested,
        'rule_level_verdicts': verdicts,
        'sanity_checks': san,
        'reports_not_graded': rep,
        'deviations_from_prereg': [],
        'post_hoc': {},
        'runtime_sec': None,
    }
    out['runtime_sec'] = (datetime.datetime.now() - t0).total_seconds()
    return out, units


if __name__ == '__main__':
    res, units = main()
    p = C.save(OUT, res)
    print('saved', p, res['grade_counts'])
