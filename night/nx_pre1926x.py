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


STOP_MAP = {'cowles_ew_ind_vs_C1': ('cowles_ind',), 'lse_ew_vs_boe_1871_1914': ('lse_ind', 'lse_stk'), 'nyse_ew_vs_gip_pw2020': ('nyse_stk',)}


def sanity_shape():
    """事前登録の sanity_checks_before_results の (2)〜(4)＝相手どうしの形（成績ではない）。
    ★検査役の指摘（2026-09-28）で順番を直した: 事前登録どおり run_main（成績）より前に回し、止まる条件に触れたデータの単位は
    主の格付けに入れない（'PENDING_stop'）。(5) 以降（先読みなし・月数・族の数・欠測）は組み立てた系列が要るので後で回す"""
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
    res['stopped_data'] = sorted({d for k in stop for d in STOP_MAP[k]})
    res['stopped_units'] = [u for u in UNIT_IDS if RULES[u].get('data') in res['stopped_data']]
    res['order'] = 'この点検は成績（run_main）より前に回した（検査役の指摘で直した順番）。止まる条件に触れたデータの単位は主の格付けに入れない'
    return res


def sanity(units, shape):
    res = dict(shape)
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
            # ★検査役の指摘（2026-09-28）: one の式（½Σ|Δw|×u）は u を『売りと買いの1回ずつ』に u/2 ずつ掛けるのと同じ。
            # Jones 2002 の『片道』（売買1回ごとの費用）として u を読むなら、two の式と同じ Σ|Δw|×u にそろえる（事後・格付けに使わない）
            if r['cost'][0] == 'one':
                x = build(r, cost=('two', u))
                e = C.excess_stats(x['net'], x['b'])
                h1, h2 = C.excess_stats(x['net'], x['b'], a1, z1), C.excess_stats(x['net'], x['b'], a2, z2)
                row[f'per_side_unit_{u}'] = {'full': e, 'h1_cagr_diff': h1 and h1['cagr_diff'], 'h2_cagr_diff': h2 and h2['cagr_diff'],
                                             'formula': f'Σ|Δw| × {u}（売買の各側に {u}）'}
            elif r['cost'][0] == 'two':
                row[f'per_side_unit_{u}'] = {'same_as': f'unit_{u}', 'formula': f'Σ|Δw| × {u}（two の式はもともと売買の各側に u）'}
            else:
                row[f'per_side_unit_{u}'] = {'same_as': f'unit_{u}', 'formula': 'moved・dL の式は出入り・倍率の変化の各回に u（もともと各側）'}
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
    per_side = {}
    for uid in UNIT_IDS:
        if RULES[uid]['kind'] in ('halloween',):
            continue
        row = out[uid].get('per_side_unit_0.01') or {}
        e = row.get('full') if 'full' in row else (out[uid]['unit_0.01']['full'] if row.get('same_as') else None)
        per_side[uid] = e and {'ex_ann': e['ex_ann'], 't': e['t'], 'cagr_diff': e['cagr_diff']}
    dd = {u: v for u, v in per_side.items() if u.startswith('D_') and v}
    summ = ('売買の各側に 1%（当時の現実に近い単価・Σ|Δw|×1%・S3 は出入りの各回 1%×L）でそろえると、LSE の業種 D は 8本のうち正（算術の超過>0 かつ 幾何の差>0）'
            + str(sum(1 for v in dd.values() if v['ex_ann'] > 0 and v['cagr_diff'] > 0)) + '・算術の超過>0 だけなら '
            + str(sum(1 for v in dd.values() if v['ex_ann'] > 0)) + '・t≥2 '
            + str(sum(1 for v in dd.values() if (v['t'] or 0) >= 2)) + '（' + '・'.join(f"{u[2:]} {v['ex_ann']:+.2f} t{v['t']}" for u, v in dd.items()) + '）。'
            + '業種の勢いの6本だけなら 正 ' + str(sum(1 for u, v in dd.items() if 'S3' not in u and v['ex_ann'] > 0 and v['cagr_diff'] > 0))
            + '（算術だけなら ' + str(sum(1 for u, v in dd.items() if 'S3' not in u and v['ex_ann'] > 0)) + '）'
            + '・t≥2 ' + str(sum(1 for u, v in dd.items() if 'S3' not in u and (v['t'] or 0) >= 2)) + '。★D は止まる条件に触れたデータ（主の格付けは PENDING_stop）')
    return {'rows': out, 'per_side_1pct': per_side, 'summary_per_side_1pct': summ,
            'note': '各規則の費用の式の形（two＝両側 Σ|Δw|×単価・one＝片道 ½Σ|Δw|×単価・moved＝出入り×L×単価・dL＝|ΔL|×単価）はそのままで単価だけ 0.50%・1.00% に替えた（unit_*・事前登録の文言どおり）。'
                    '★one と two では単価の意味が違う: one の u は『片道の回転 ½Σ|Δw| あたり』＝売りと買いの各側に u/2、two の u は各側に u。'
                    'そのため unit_* の one の規則（F1b・F3g・株）は two の規則（G3・G4・P9）の半分の費用しか引いていない。'
                    '当時の売買1回ごとの費用（Jones 2002 の片道）として読むなら per_side_unit_*（Σ|Δw|×u にそろえた版・事後・検査役の指摘 2026-09-28）を使うこと。'
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


# ═════════════════════════ 7. 事後（結果を見た後に足した診断・格付けに使わない） ═════════════════════════
def coh_ind(R, months, r, skip, side='top', exclude=()):
    """D.build_ind_topk / build_ind_multi と同じ選び方（同点は名前の順）で、上位（top）か下位（bottom）の組だけを返す"""
    names = [n for n in R if n not in exclude]
    lr = {n: [math.log1p(R[n][m]) if m in R[n] else None for m in months] for n in names}
    coh = {}
    sg = -1 if side == 'top' else 1
    for f in range(len(months)):
        if r['kind'] == 'ind_topk':
            lo, hi = f - skip - r['L'] + 1, f - skip
            if lo < 0:
                continue
            sc = []
            for n in names:
                seg = lr[n][lo:hi + 1]
                if any(v is None for v in seg):
                    continue
                sc.append((sg * math.fsum(seg), str(n), n))
            N = len(sc)
            k = r['K'] if r.get('K') is not None else max(2, D.round_half_up(r['frac'] * N))
            if N < r['minN'] or N < k:
                continue
            sc.sort()
            coh[f] = [n for _, _, n in sc[:k]]
        else:  # ind_multi
            hi = f - skip
            Lmax = max(r['windows'])
            if hi - Lmax + 1 < 0:
                continue
            ok = [n for n in names if all(v is not None for v in lr[n][hi - Lmax + 1:hi + 1])]
            if len(ok) < r['minN'] or len(ok) < r['K']:
                continue
            avg = collections.defaultdict(float)
            for L in r['windows']:
                pr = D._pct_ranks({n: math.fsum(lr[n][hi - L + 1:hi + 1]) for n in ok})
                for n in ok:
                    avg[n] += pr[n] / len(r['windows'])
            coh[f] = [n for _, _, n in sorted((sg * avg[n], str(n), n) for n in ok)[:r['K']]]
    return coh


def coh_stk(R, months, r, side='top', exclude=()):
    """D.build_stk_mom / build_stk_seas と同じ選び方で上位か下位の組"""
    names = [n for n in R if n not in exclude]
    coh = {}
    sg = -1 if side == 'top' else 1
    for f in range(len(months) - (1 if r['kind'] == 'stk_seas' else 0)):
        if r['kind'] == 'stk_mom':
            lo, hi = f - r['skip'] - r['L'] + 1, f - r['skip']
            if lo < 0 or hi < lo:
                continue
            need = months[min(lo, f):f + 1]
            sc = []
            for n in names:
                d = R[n]
                if any(m not in d for m in need):
                    continue
                sc.append((sg * math.fsum(math.log1p(d[m]) for m in months[lo:hi + 1]), str(n), n))
        else:
            nxt = months[f + 1]
            lags = [D.madd(nxt, -12 * y) for y in r['years']]
            if lags[-1] < months[0]:
                continue
            sc = []
            for n in names:
                d = R[n]
                if months[f] not in d or any(m not in d for m in lags):
                    continue
                sc.append((sg * math.fsum(d[m] for m in lags) / len(lags), str(n), n))
        k = D.round_half_up(r['frac'] * len(sc))
        if k < r['min_port']:
            continue
        sc.sort()
        coh[f] = [n for _, _, n in sc[:k]]
    return coh


def hold_side(r, R_form, R_hold, side, skip=None):
    """組を R_form で選び R_hold で持つ（区間ごと）→ {'s','net','w'}"""
    segs = DATA_SEGS[r['data']]
    out = {'s': {}, 'net': {}, 'w': {}}
    for ms in segs:
        if r['kind'] in ('ind_topk', 'ind_multi'):
            coh = coh_ind(R_form, ms, r, r['skip'] if skip is None else skip, side)
            s, net, _, W = D._hold(ms, coh, r.get('H', 1), R_hold, tuple(r['cost']))
        else:
            coh = coh_stk(R_form, ms, r, side)
            x = D._hold_stk(ms, coh, R_hold, tuple(r['cost']), 'ew', None)
            s, net, W = x['s'], x['net'], x['w']
        out['s'].update(s); out['net'].update(net); out['w'].update(W)
    return out


def geo_ew(R, segs):
    """対数の平均（幾何）で束ねた等分（ノイズの分散による算術平均の上振れ〔Blume-Stambaugh 1983〕を除く診断用・投資できる形ではない）"""
    out = {}
    for ms in segs:
        for m in ms:
            v = [math.log1p(R[n][m]) for n in R if m in R[n]]
            if v:
                out[m] = math.expm1(math.fsum(v) / len(v))
    return out


def lse_industries_geo(R, sect, min_members=3):
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for i, r in R.items():
        sr = sect.get(i, [])
        for k, v in r.items():
            s = D.sector_at(sr, k)
            if s and s not in D.LSE_NOT_SELECTABLE:
                acc[s][k].append(math.log1p(v))
    return {s: {k: math.expm1(math.fsum(v) / len(v)) for k, v in d.items() if len(v) >= min_members} for s, d in acc.items()}


def yearly(net, b):
    ys = collections.defaultdict(lambda: [1.0, 1.0, 0])
    for k in set(net) & set(b):
        y = k // 100
        ys[y][0] *= 1 + net[k]; ys[y][1] *= 1 + b[k]; ys[y][2] += 1
    v = {y: round((a - bb) * 100, 2) for y, (a, bb, n) in ys.items() if n >= 6}
    return {'years': len(v), 'positive': sum(1 for x in v.values() if x > 0), 'worst3': sorted(v.items(), key=lambda kv: kv[1])[:3],
            'best3': sorted(v.items(), key=lambda kv: -kv[1])[:3]}


def es(a, b):
    e = C.excess_stats(a, b)
    return None if e is None else {k: e[k] for k in ('from', 'to', 'years', 'ex_ann', 't', 'cagr_diff', 'beta', 'vol_s', 'vol_b')}


def post_hoc(units):
    ph = {'note': '★すべて事後（格付けを見た後に足した診断）。格付けには使わない'}
    # (1) 相手どうしの形の点検で止まる条件に触れた件の調べ
    lew = BENCH['lse_ew']
    inv = {}
    for lag in (-1, 0, 1):
        ks = [k for k in sorted(lew) if 187101 <= k <= 191406 and D.madd(k, lag) in UK_IDX]
        inv[f'corr_lse_ew_t_boe_t{lag:+d}'] = round(C.corr([lew[k] for k in ks], [UK_IDX[D.madd(k, lag)] for k in ks]), 3)
    uk_all, _ = D.uk_share_prices()
    sh = {b: uk_all[9][b] / uk_all[9][a] - 1 for a, b in zip(sorted(uk_all[9]), sorted(uk_all[9])[1:]) if D.madd(a, 1) == b}
    ks = [k for k in sorted(lew) if k <= 187012 and k in sh]
    inv['corr_lse_ew_vs_smith_horne_col9_1869_1870'] = {'corr': round(C.corr([lew[k] for k in ks], [sh[k] for k in ks]), 3), 'n': len(ks)}
    ks = [k for k in sorted(lew) if k <= 187012 and k in UK_IDX]
    inv['corr_lse_ew_vs_boe_col23_acheson_1869_1870'] = {'corr': round(C.corr([lew[k] for k in ks], [UK_IDX[k] for k in ks]), 3), 'n': len(ks)}
    zeros = sum(1 for d in LSE_RET.values() for v in d.values() if v == 0.0)
    inv['share_of_zero_stock_month_returns_lse'] = round(zeros / sum(len(d) for d in LSE_RET.values()), 3)
    geo = geo_ew(LSE_RET, LSE_SEG_M)
    for a, z in ((186902, 188712), (188801, 190712), (191502, 192912)):
        inv[f'cagr_{a}_{z}'] = {'lse_ew_arith': round(C.cagr(C.window(lew, a, z)) * 100, 2), 'lse_ew_geo': round(C.cagr(C.window(geo, a, z)) * 100, 2),
                                'boe_index': round(C.cagr(C.window(UK_IDX, a, z)) * 100, 2)}
    # 同じ業種の大手の本線鉄道（普通株・説明の行が空＝本体の株）どうしの月次の相関＝ LSE の読み込みの内部の整合
    raw = D.lse_raw()['sec']
    pat = re.compile(r'^(Great Western|Midland|Great Northern|North[- ]Eastern|Caledonian|Great Eastern|North British)\b', re.I)
    hr = [i for i in LSE_RET if raw.get(i, {}).get('file') == 'rail' and pat.search(raw[i]['name']) and not (raw[i]['sec'] or '').strip()
          and sum(1 for k in LSE_RET[i] if 187101 <= k <= 191406) >= 120]
    pc = []
    for x_ in range(len(hr)):
        for y_ in range(x_ + 1, len(hr)):
            a_, b_ = LSE_RET[hr[x_]], LSE_RET[hr[y_]]
            kk = [k for k in a_ if k in b_ and 187101 <= k <= 191406]
            if len(kk) >= 60:
                pc.append(round(C.corr([a_[k] for k in kk], [b_[k] for k in kk]), 3))
    vb = []
    for i in hr:
        kk = [k for k in LSE_RET[i] if k in UK_IDX and 187101 <= k <= 191406]
        vb.append(round(C.corr([LSE_RET[i][k] for k in kk], [UK_IDX[k] for k in kk]), 3))
    inv['home_rail_majors'] = {'ids': {i: raw[i]['name'][:40] for i in hr}, 'pairwise_corr_sorted': sorted(pc),
                               'median_pairwise': _stat.median(pc) if pc else None, 'corr_each_vs_boe_1871_1914': vb}
    inv['reading'] = ('LSE の読み込みの誤りを示す明確な形は見つからなかったが確証も無い（1869〜1870 の LSE の等分と Smith-Horne の相関は corr_lse_ew_vs_smith_horne_col9_1869_1870・大手の鉄道の株どうしと指数との相関は home_rail_majors）。'
                      '1871〜1914 の相関が低い理由として測れたのは: (i) LSE の株の月の約43% が値動き0（古い気配）で等分の相手が前後の月へにじむ（t−1・t・t+1 の相関の和 ≈0.86）、'
                      '(ii) 等分の算術平均が株ごとのノイズで大きく上振れる（1869〜1887 の年率 算術 +8.75% 対 対数の平均 −1.74% 対 イングランド銀行 −0.08%）。'
                      '大手の鉄道の株は株どうし（中央 0.32）よりイングランド銀行の指数（Smith-Horne）との相関が低い（0.09〜0.37）＝指数の側の作り（25〜82証券）も一因かもしれない（未確認）。'
                      '読み込みの誤りではなくデータのノイズと薄商いと判断したが、事前登録の線（0.6）は下回った＝止まる条件に触れた')
    ph['sanity_stop_investigation'] = inv
    # (2) 勝者−敗者（同じ作り方の上位−下位）: 相手に共通の上振れ（ノイズ・等分）を消す
    ls = {}
    for uid in UNIT_IDS:
        r = RULES[uid]
        if r['kind'] in ('ind_trend', 'halloween'):
            continue
        R = DATA_R[r['data']]
        top = hold_side(r, R, R, 'top')
        same = all(abs(top['net'][m] - units[uid]['x']['net'][m]) < 1e-12 for m in units[uid]['x']['net'])
        bot = hold_side(r, R, R, 'bottom')
        b = units[uid]['x']['b']
        ls[uid] = {'top_reproduces_registered': same and len(top['net']) == len(units[uid]['x']['net']),
                   'top_minus_bottom_gross': es(top['s'], bot['s']),
                   'top_minus_bottom_net_both_legs': es(top['net'], bot['net']),
                   'bottom_net_vs_bench': es(bot['net'], b)}
    ph['winners_minus_losers'] = {'rows': ls, 'note': '上位の組と同じ作り方で下位の組を作り、差を取った（両方とも等分・同じ母集団）。等分の算術平均のノイズの上振れや古い気配は両側に同じようにかかるので、差は勢いそのものに近い'}
    log('post-hoc LS done')
    # (3) 形成の窓と保有のあいだを 2・3 か月あける（古い気配・月平均のにじみへの備えを強めた版）
    sk = {}
    for uid in UNIT_IDS:
        r = RULES[uid]
        if r['kind'] not in ('ind_topk', 'ind_multi', 'ind_trend'):
            continue
        row = {}
        for s in (2, 3):
            x = build(r, skip=s)
            row[f'skip{s}'] = es(x['net'], x['b'])
        sk[uid] = row
    ph['longer_gap'] = {'rows': sk, 'note': '業種の規則の窓の終わりを保有の月から 2・3 か月前にした（登録の版は 1 か月）'}
    log('post-hoc skip done')
    # (4) 対数の平均で束ねた版（ノイズの上振れを両側から除く）: LSE の業種・相手を幾何の等分で作り直す
    LIg = lse_industries_geo(LSE_RET, LSE_SECT)
    geo_rows = {}
    for uid in D.FAMILIES['D']:
        r = RULES[uid]
        x = build(r, R=LIg)
        b = x['b'] if r['kind'] == 'ind_trend' else geo
        geo_rows[uid] = es(x['net'], b)
    for uid in D.FAMILIES['B']:
        r = RULES[uid]
        segs = DATA_SEGS[r['data']]
        out = {}
        for ms in segs:
            coh = coh_stk(LSE_RET, ms, r, 'top')
            for j in range(1, len(ms)):
                f = j - 1
                if f not in coh:
                    continue
                m = ms[j]
                mem = [n for n in coh[f] if m in LSE_RET[n]]
                if mem:
                    out[m] = math.expm1(math.fsum(math.log1p(LSE_RET[n][m]) for n in mem) / len(mem))
        geo_rows[uid] = es(out, geo)
    ph['geometric_aggregation'] = {'rows': geo_rows, 'note': '業種の指数・株の組・相手をすべて対数の平均（幾何）で束ねた（投資できる形ではない・費用前は B、D は業種の費用後）。算術の等分の上振れ（株ごとのノイズの分散）を両側から除いた比較'}
    # (5) 株ごとの月の値動き |対数| > ln2（+100% 超・−50% 未満）を欠測にした版（両側）
    Rt = {i: {m: v for m, v in d.items() if abs(math.log1p(v)) <= math.log(2)} for i, d in LSE_RET.items()}
    Rt = {i: d for i, d in Rt.items() if d}
    LIt, _ = D.lse_industries({'ret': Rt, 'sect': LSE_SECT})
    bt = ew(Rt, LSE_SEG_M)
    trim_rows = {'dropped_stock_months': sum(len(d) for d in LSE_RET.values()) - sum(len(d) for d in Rt.values())}
    for uid in D.FAMILIES['D']:
        r = RULES[uid]
        x = build(r, R=LIt)
        trim_rows[uid] = es(x['net'], x['b'] if r['kind'] == 'ind_trend' else bt)
    for uid in D.FAMILIES['B']:
        x = build(RULES[uid], R=Rt, bench_R=Rt)
        trim_rows[uid] = es(x['net'], x['b'])
    trim_rows['lse_ew_trimmed_cagr_1869_1887'] = round(C.cagr(C.window(bt, 186902, 188712)) * 100, 2)
    ph['trimmed_extremes'] = {'rows': trim_rows, 'note': '株の月の値動きで |log(1+r)| > ln2 を両側で欠測にした（業種も作り直した）。本物の大きな値動きも落とす粗い版'}
    log('post-hoc geo/trim done')
    # (6) R7(c) の作り直し: 形成は価格だけ（登録の信号）・保有の月だけ配当の近似を両側に足す。年 30% 超の利回りは欠測扱い
    Rd = {i: {m: v + (LSE_DY[i][m] if m in LSE_DY.get(i, {}) and LSE_DY[i][m] * 12 <= 0.30 else 0.0) for m, v in d.items()} for i, d in LSE_RET.items()}
    dv = {}
    for uid in D.FAMILIES['B']:
        r = RULES[uid]
        x = hold_side(r, LSE_RET, Rd, 'top')
        dv[uid] = es(x['net'], ew(Rd, LSE_SEG_M))
    dys = sorted(v * 12 for d in LSE_DY.values() for v in d.values())
    ph['dividend_holding_only'] = {'rows': dv, 'dy_annual_quantiles_pct': {q: round(dys[int(q * (len(dys) - 1))] * 100, 2) for q in (0.5, 0.9, 0.99, 1.0)},
                                   'note': 'R7(c) の登録の実装は配当を足した R で形成もしたため、配当の近似の外れ値（年 100% 超が 1% ほど・最大 1万%）を持つ株が勝者に選ばれ続け、差が +14%/年まで膨らんだ（R7 の値は信頼できない）。ここでは形成は価格だけ・保有の月だけ配当（年30%超は足さない）'}
    # (7) 年ごとの勝ち数
    ph['calendar_years'] = {uid: yearly(units[uid]['x']['net'], units[uid]['x']['b']) for uid in UNIT_IDS}
    # (8) 保有の組の『ノイズの上振れ』（算術−幾何の月の差）: B は株、D は業種の中の株
    nb = {}
    uni_gap = []
    for m in lew:
        v = [LSE_RET[n][m] for n in LSE_RET if m in LSE_RET[n]]
        uni_gap.append(math.fsum(v) / len(v) - math.expm1(math.fsum(math.log1p(x) for x in v) / len(v)))
    nb['universe_arith_minus_geo_ann_pct'] = round(_stat.mean(uni_gap) * 1200, 2)
    for uid in D.FAMILIES['B']:
        g = []
        for m, w in units[uid]['x']['w'].items():
            g.append(math.fsum(wt * LSE_RET[n][m] for n, wt in w.items()) - math.expm1(math.fsum(wt * math.log1p(LSE_RET[n][m]) for n, wt in w.items())))
        nb[uid] = round(_stat.mean(g) * 1200, 2)
    ind_gap = {}
    for s in LSE_IND:
        ind_gap[s] = {m: LSE_IND[s][m] - LIg[s][m] for m in LSE_IND[s] if m in LIg.get(s, {})}
    for uid in D.FAMILIES['D']:
        if RULES[uid]['kind'] == 'ind_trend':
            continue
        g = [math.fsum(wt * ind_gap[n].get(m, 0.0) for n, wt in w.items()) for m, w in units[uid]['x']['w'].items()]
        nb[uid] = round(_stat.mean(g) * 1200, 2)
    allg = [v for d in ind_gap.values() for v in d.values()]
    nb['lse_industries_mean_gap_ann_pct'] = round(_stat.mean(allg) * 1200, 2)
    ph['noise_uplift'] = {'ann_pct': nb, 'note': '月ごとの（算術の平均 − 対数の平均）×12。保有の組が相手より大きければ、その分の超過はノイズの上振れで説明されうる'}
    # (9) 季節性と配当落ち: 価格だけのリターンは配当の支払いの月に下がる＝『同じ暦月の過去のリターン』が配当の月を拾う疑い
    ph['seasonality_ex_dividend'] = seas_exdiv(units)
    log('post-hoc done')
    return ph


def lse_payable():
    """IMM の dvdpayable（配当の支払いの月・例 'Mar;Sep'）→ {id: {ym: [月…]}}。out/_nx_cache/nx_pre1926x_dvdpayable.json に置く"""
    p = os.path.join(C.CACHE, 'nx_pre1926x_dvdpayable.json')
    if not os.path.exists(p):
        import zipfile, io, csv
        MONL = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
        out, cnt = {}, collections.Counter()
        for key, inner in (('lse_rail', 'Railways_new.csv'), ('lse_bank', 'Banks_new.csv'), ('lse_misc', 'Misc_new.csv')):
            z = zipfile.ZipFile(D.path(key))
            for row in csv.DictReader(io.TextIOWrapper(z.open(inner), encoding='latin-1')):
                s = (row.get('dvdpayable') or '').strip()
                if not s or s == 'NULL':
                    continue
                ms = sorted({MONL[x] for x in re.findall(r'[A-Za-z]{3}', s.lower()) if x in MONL})
                if not ms:
                    cnt['unparsed'] += 1
                    continue
                try:
                    ym = int(row['year']) * 100 + int(row['month'])
                except (ValueError, KeyError):
                    continue
                out.setdefault(row['id'], {})[ym] = ms
                cnt['rows'] += 1
        json.dump({'pay': out, 'counts': cnt}, open(p, 'w'))
    o = json.load(open(p))
    return {i: {int(k): v for k, v in d.items()} for i, d in o['pay'].items()}, o['counts']


def seas_exdiv(units):
    PAY, pcnt = lse_payable()

    def pay_at(i, m):
        """月 m の直前 12 か月以内に分かった支払いの月の一覧（先読みなし: m−1 までの記録）"""
        d = PAY.get(i)
        if not d:
            return None
        for k in range(1, 13):
            v = d.get(D.madd(m, -k))
            if v:
                return v
        return None
    r = RULES['B_seas_6_10an_tercile']
    R = LSE_RET
    res = {'payable_rows': pcnt}
    # (a) 保有の月が支払いの月（か前月）に当たる株の割合: 上位の組・下位の組・母集団
    share = {}
    for side in ('top', 'bottom'):
        x = hold_side(r, R, R, side)
        for lag in (0, 1):
            v = []
            for m, w in x['w'].items():
                kn = [(wt, (D.madd(m, lag) % 100 or 12) in p) for n, wt in w.items() for p in [pay_at(n, m)] if p]
                if kn:
                    v.append(math.fsum(wt for wt, hit in kn if hit) / math.fsum(wt for wt, _ in kn))
            share[f'{side}_paymonth_eq_hold_plus{lag}'] = round(_stat.mean(v), 3) if v else None
    for lag in (0, 1):
        v = []
        for m in BENCH['lse_ew']:
            kn = [(D.madd(m, lag) % 100 or 12) in p for n in R if m in R[n] for p in [pay_at(n, m)] if p]
            if kn:
                v.append(sum(kn) / len(kn))
        share[f'universe_paymonth_eq_hold_plus{lag}'] = round(_stat.mean(v), 3) if v else None
    res['share_of_holdings_paying'] = share
    # (b) 配当を支払いの月に置いた総リターンの近似（年の利回り＝dy×12・年30%超は足さない・支払いの回数で割る）で作り直す
    for lag, name in ((0, 'div_in_pay_month'), (1, 'div_in_month_before_pay')):
        Rt = {}
        for i, d in R.items():
            dd = {}
            for m, v in d.items():
                add = 0.0
                y = LSE_DY.get(i, {}).get(m)
                p = pay_at(i, m)
                if y is not None and y * 12 <= 0.30 and p and (D.madd(m, lag) % 100 or 12) in p:
                    add = y * 12 / len(p)
                dd[m] = v + add
            Rt[i] = dd
        row = {}
        for uid in D.FAMILIES['B']:
            rr = RULES[uid]
            top = hold_side(rr, Rt, Rt, 'top')
            bot = hold_side(rr, Rt, Rt, 'bottom')
            row[uid] = {'top_net_vs_ew': es(top['net'], ew(Rt, LSE_SEG_M)), 'top_minus_bottom_gross': es(top['s'], bot['s'])}
        res[name] = row
    res['note'] = ('事後。IMM の dvdpayable（配当の支払いの月）を生の3ファイルから読んだ。価格だけのリターンは配当落ちの月に下がるので、'
                   '『6〜10年前の同じ暦月のリターン』は配当の月でない月を拾いやすい。(b) は配当を支払いの月（か前月）に置いた総リターンの近似で作り直した版')
    return res


# ═════════════════════════ 8. 検査役の指摘（2026-09-28）による直し（事後・格付けは登録の版） ═════════════════════════
# 凍結した data 道具（sha を事前登録に刻んだ）は書き換えない。直した版はここに写して作り、登録の版と並べる（tools.measure_next の約束）。
def unit_eval(r, R=None, bench_R=None, builder=None):
    """1つの単位を組み立てて、格付けに要る束（stats・最大寄与を抜いた版）を返す。builder を渡すとそれで組み立てる（exclude を受ける関数）"""
    mk = builder or (lambda exclude=(): build(r, R=R, bench_R=bench_R, exclude=exclude))
    x = mk()
    st = bundle(x, r)
    top, top5 = contrib_top(x, r)
    dt = None
    if top is not None:
        xd = mk(exclude=(top,))
        dt = C.excess_stats(xd['net'], xd['b'])
    return {'x': x, 'stats': st, 'drop_top': {'excluded': cname(r, top) if top is not None else None, 'top5_contrib': top5, 'net_vs_b': dt}, 'rule': r}


def grade_with_family(uid, variant_unit, units, fam_of, extra=None):
    """uid だけを差し替えた版で、同じ族の Holm（他の単位は登録の版の p）を当てて grade_era。extra={uid2: 差し替え版} で複数を同時に差し替える"""
    f = fam_of[uid]
    ids = [u for u in UNIT_IDS if fam_of[u] == f]
    sub = {u: units[u] for u in ids}
    sub[uid] = variant_unit
    for u2, v2 in (extra or {}).items():
        sub[u2] = v2
    g = grade_units(sub, {u: f for u in ids})
    return g[uid]


def short_es(e):
    return None if not e else {k: e[k] for k in ('ex_ann', 't', 'cagr_diff')}


# ── (5) P9 の同点: 百分位の平均を浮動小数で足すと、数学的に同点の業種が最後の1桁の差で並ぶ（名前の順にならない）──
def _twice_ranks(vals):
    """{名前: 値} → {名前: 2×平均の順位（整数）}。D._pct_ranks の (n−1)×2 倍＝同じ母集団の中では順序が同じで、足しても丸め誤差が無い"""
    items = sorted(vals.items(), key=lambda x: x[1])
    n, out, i = len(items), {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[items[k][0]] = i + j
        i = j + 1
    return out


def build_ind_multi_exact(R, months, windows, skip, K, minN, cost, exclude=()):
    """D.build_ind_multi と同じ規則（1・3・6・12 か月の百分位の平均の上位 K・4本そろう業種だけ）で、同点を docstring どおり名前の順にした版。
    同じ月の候補は全部の窓で同じ n なので、百分位の平均の大小は『2×順位の和（整数）』の大小と同じ。→ (−順位の和, 名前) で並べる"""
    names = [n for n in R if n not in exclude]
    lr = {n: [math.log1p(R[n][m]) if m in R[n] else None for m in months] for n in names}
    Lmax = max(windows)
    coh, flips, old_coh = {}, 0, {}
    for f in range(len(months)):
        hi = f - skip
        if hi - Lmax + 1 < 0:
            continue
        ok = [n for n in names if all(v is not None for v in lr[n][hi - Lmax + 1:hi + 1])]
        if len(ok) < minN or len(ok) < K:
            continue
        tot, avg = collections.defaultdict(int), collections.defaultdict(float)
        for L in windows:
            vals = {n: math.fsum(lr[n][hi - L + 1:hi + 1]) for n in ok}
            tr, pr = _twice_ranks(vals), D._pct_ranks(vals)
            for n in ok:
                tot[n] += tr[n]
                avg[n] += pr[n] / len(windows)
        coh[f] = [n for _, _, n in sorted((-tot[n], str(n), n) for n in ok)[:K]]
        old_coh[f] = [n for _, _, n in sorted((-avg[n], str(n), n) for n in ok)[:K]]
        flips += set(coh[f]) != set(old_coh[f])
    s, net, turn, W = D._hold(months, coh, 1, R, cost)
    return {'s': s, 'net': net, 'turn': turn, 'w': W, 'flips': flips, 'formed': len(coh)}


def fix_p9_exact(units, fam_of):
    out = {}
    for uid in ('A_P9_multi_5', 'D_P9_multi_5'):
        r = RULES[uid]
        R = DATA_R[r['data']]
        info = {'flips': 0, 'formed': 0}

        def mk(exclude=(), r=r, R=R, info=info):
            o = {'s': {}, 'net': {}, 'turn': {}, 'w': {}}
            for ms in DATA_SEGS[r['data']]:
                x = build_ind_multi_exact(R, ms, r['windows'], r['skip'], r['K'], r['minN'], tuple(r['cost']), exclude=exclude)
                for k in o:
                    o[k].update(x[k])
                if not exclude:
                    info['flips'] += x['flips']; info['formed'] += x['formed']
            o['b'], o['R'] = BENCH[r['bench']], R
            o['rf'] = RATES[r['rf']]
            return o
        v = unit_eval(r, builder=mk)
        g = grade_with_family(uid, v, units, fam_of)
        st, st0 = v['stats'], units[uid]['stats']
        out[uid] = {'formation_months_changed': info['flips'], 'formation_months': info['formed'],
                    'registered': {'full_net': short_es(st0['full_net']), 'h1_cagr_diff': st0['h1_net']['cagr_diff'], 'h2_cagr_diff': st0['h2_net']['cagr_diff'],
                                   'roll20_median': (st0.get('roll20') or {}).get('median')},
                    'exact_ties': {'full_net': short_es(st['full_net']), 'h1_cagr_diff': st['h1_net']['cagr_diff'], 'h2_cagr_diff': st['h2_net']['cagr_diff'],
                                   'roll20_median': (st.get('roll20') or {}).get('median'), 'drop_top': short_es(v['drop_top']['net_vs_b'])},
                    'grade_exact_ties': g['grade'], 'criteria_exact_ties': g['criteria']}
    return out


# ── (3) D_S3 の単位の不一致: LSE の業種は価格だけ、現金の脚は総リターンの金利 ──
def build_ind_trend_split(R_sig, R_hold, months, rf, sma, Lev, skip, cost, spread, fee, exclude=()):
    """D.build_ind_trend の写し。信号（10か月線）は R_sig（登録どおり価格だけ）、保有の月のリターンと相手は R_hold。
    R_sig=R_hold なら D.build_ind_trend と1ビットも違わない（実行時に確かめる）"""
    names = [n for n in R_sig if n not in exclude]
    idx, up = {}, {}
    for n in names:
        I, u, hist, lev = {}, {}, [], None
        for g, m in enumerate(months):
            if m not in R_sig[n]:
                hist, lev = [], None
                continue
            if lev is None:
                lev, hist = 1.0, [1.0]
            lev *= 1 + R_sig[n][m]
            hist.append(lev)
            I[g] = lev
            h = hist[-sma:]
            u[g] = True if len(h) < sma else lev > math.fsum(h) / sma
        idx[n], up[n] = I, u
    s, net, b, E, W = {}, {}, {}, {}, {}
    prev_state = None
    for j in range(1, len(months)):
        m = months[j]
        g = j - 1 - skip
        if g < 0:
            continue
        U = [n for n in names if (j - 1) in idx[n] and m in R_sig[n] and g in up[n]]
        if not U or m not in rf:
            prev_state = None
            continue
        w = 1.0 / len(U)
        ups = [n for n in U if up[n][g]]
        e = Lev * w * len(ups)
        rp = Lev * math.fsum(w * R_hold[n][m] for n in ups) + (1 - e) * rf[m]
        if e > 1:
            rp -= ((e - 1) * spread + fee) / 12
        st = {n: up[n][g] for n in U}
        moved = 0.0 if prev_state is None else math.fsum(w for n in U if n in prev_state and prev_state[n] != st[n])
        s[m] = rp
        net[m] = rp - moved * Lev * cost[1]
        b[m] = math.fsum(R_hold[n][m] for n in U) / len(U)
        E[m] = e
        W[m] = {n: (Lev * w if st[n] else 0.0) for n in U}
        prev_state = st
    return {'s': s, 'net': net, 'b': b, 'E': E, 'w': W}


def lse_ind_dividend(ret, sect, dy, cap=0.30):
    """業種ごとの月の配当利回りの近似＝その月の業種の構成の株（D.lse_industries と同じ所属）の dy の等分の平均（年 cap 超は除く・分からない株は平均に入れない）"""
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for i, r in ret.items():
        sr = sect.get(i, [])
        for k in r:
            s = D.sector_at(sr, k)
            if s and s not in D.LSE_NOT_SELECTABLE:
                y = dy.get(i, {}).get(k)
                if y is not None and y * 12 <= cap:
                    acc[s][k].append(y)
    return {s: {k: math.fsum(v) / len(v) for k, v in d.items() if v} for s, d in acc.items()}


def fix_s3_dividend(units, fam_of, LI=None, ret=None, sect=None, dy=None, label='registered_panel'):
    LI = LSE_IND if LI is None else LI
    dyi = lse_ind_dividend(ret if ret is not None else LSE_RET, sect if sect is not None else LSE_SECT, dy if dy is not None else LSE_DY)
    n_all = sum(len(d) for d in LI.values())
    n_known = sum(1 for s, d in LI.items() for k in d if k in dyi.get(s, {}))
    mean_dy = _stat.mean([dyi[s][k] for s, d in LI.items() for k in d if k in dyi.get(s, {})]) * 1200
    out = {'panel': label, 'industry_dividend_yield': {'industry_months': n_all, 'with_estimate': n_known, 'mean_ann_pct': round(mean_dy, 2),
                                                       'rule': 'R7 と同じ配当の近似（直近4回の配当率×払込額÷12÷p_{t−1}・年30%超は除く）を業種の構成の株で等分に平均。分からない業種の月は足さない（0）'},
           'rows': {}}
    # 写しが登録の版と同じことの確認（R_hold=R_sig）
    same = True
    for uid in ('D_S3_FABER_L2', 'D_S3_FABER_L3'):
        r = RULES[uid]
        for ms in DATA_SEGS[r['data']]:
            a_ = D.build_ind_trend(LSE_IND, ms, RATES[r['rf']], r['sma'], r['Lev'], r['skip'], tuple(r['cost']), r['spread'], r['fee'])
            b_ = build_ind_trend_split(LSE_IND, LSE_IND, ms, RATES[r['rf']], r['sma'], r['Lev'], r['skip'], tuple(r['cost']), r['spread'], r['fee'])
            same = same and all(a_[k] == b_[k] for k in ('s', 'net', 'b', 'E', 'w'))
    out['copy_reproduces_registered'] = same
    for mult in (1.0, 0.5, 0.25):
        Rh = {s: {k: v + mult * dyi.get(s, {}).get(k, 0.0) for k, v in d.items()} for s, d in LI.items()}
        vs = {}
        for uid in ('D_S3_FABER_L2', 'D_S3_FABER_L3'):
            r = RULES[uid]
            rf = RATES[r['rf']]

            def mk(exclude=(), r=r, rf=rf, Rh=Rh):
                o = {'s': {}, 'net': {}, 'b': {}, 'w': {}, 'E': {}}
                for ms in DATA_SEGS[r['data']]:
                    x = build_ind_trend_split(LI, Rh, ms, rf, r['sma'], r['Lev'], r['skip'], tuple(r['cost']), r['spread'], r['fee'], exclude=exclude)
                    for k in o:
                        o[k].update(x[k])
                o['R'], o['rf'], o['turn'] = Rh, rf, {}
                return o
            vs[uid] = unit_eval(r, builder=mk)
        for uid, v in vs.items():
            other = {u: w for u, w in vs.items() if u != uid}
            g = grade_with_family(uid, v, units, fam_of, extra=other)
            st = v['stats']
            out['rows'][f'{uid}_div_x{mult}'] = {'full_net': short_es(st['full_net']), 'h1_cagr_diff': st['h1_net']['cagr_diff'], 'h2_cagr_diff': st['h2_net']['cagr_diff'],
                                                 'sharpe_h1': st['sharpe']['h1'], 'sharpe_h2': st['sharpe']['h2'],
                                                 'mean_exposure_E': round(_stat.mean(v['x']['E'].values()), 3),
                                                 'drop_top': short_es(v['drop_top']['net_vs_b']), 'grade': g['grade'], 'criteria': g['criteria']}
    for uid in ('D_S3_FABER_L2', 'D_S3_FABER_L3'):
        st = units[uid]['stats']
        out['rows'][f'{uid}_registered_price_only'] = {'full_net': short_es(st['full_net']), 'h1_cagr_diff': st['h1_net']['cagr_diff'], 'h2_cagr_diff': st['h2_net']['cagr_diff'],
                                                       'sharpe_h1': st['sharpe']['h1'], 'sharpe_h2': st['sharpe']['h2'],
                                                       'note': '倍率 E は配当を足した版と同じ（信号は価格だけ）'}
    out['note'] = ('事後（検査役の指摘 2026-09-28）。登録の D_S3 は株の脚が価格だけ（配当なし）で現金の脚 uk_cash が総リターンの金利＝単位が混ざる。'
                   '信号は登録どおり価格だけの業種指数、保有の月だけ配当の近似を戦略と相手（業種の等分）の両側に足した。x0.5・x0.25 は配当の近似が過大な場合の感度')
    return out


# ── (4) 英国のハロウィーンの単位の不一致: 指数は価格だけ、借入は短期金利＋0.5% を丸ごと払う ──
def fix_h_dividend(units, fam_of):
    r = RULES['H_HAL_OV15_UK']
    out = {'rows': {}}
    st0 = units['H_HAL_OV15_UK']['stats']
    out['rows']['registered_price_only'] = {'full_net': short_es(st0['full_net']), 'h1_cagr_diff': st0['h1_net']['cagr_diff'], 'h2_cagr_diff': st0['h2_net']['cagr_diff'],
                                            'sharpe_h1': st0['sharpe']['h1'], 'sharpe_h2': st0['sharpe']['h2'], 'grade': 'C（登録）'}

    def one(m, period):
        rr = dict(r)
        rr['period'] = list(period)
        x = build(rr, R=m, period=period)
        st = bundle(x, rr)
        v = {'x': x, 'stats': st, 'drop_top': None, 'rule': rr}
        g = grade_units({'H_HAL_OV15_UK': v}, {'H_HAL_OV15_UK': 'H'})['H_HAL_OV15_UK']
        return {'full_net': short_es(st['full_net']), 'h1_cagr_diff': st['h1_net']['cagr_diff'], 'h2_cagr_diff': st['h2_net']['cagr_diff'],
                'sharpe_h1': st['sharpe']['h1'], 'sharpe_h2': st['sharpe']['h2'], 'months': st['months'], 'grade': g['grade'], 'criteria': g['criteria']}
    for y in (0.01, 0.02, 0.03, 0.04, 0.05):
        m = {k: v + y / 12 for k, v in UK_IDX.items()}
        out['rows'][f'const_dy_{int(round(y * 100))}pct'] = one(m, tuple(r['period']))
    # 符号が反転する配当利回り（算術の超過・幾何の差）＝ 二分法（一定の配当・1709〜1914）
    def ex_at(y, key):
        m = {k: v + y / 12 for k, v in UK_IDX.items()}
        x = build(r, R=m)
        return C.excess_stats(x['net'], x['b'])[key]
    be = {}
    for key in ('ex_ann', 'cagr_diff'):
        lo, hi = 0.0, 0.05
        for _ in range(20):
            mid = (lo + hi) / 2
            if ex_at(mid, key) > 0:
                hi = mid
            else:
                lo = mid
        be[key] = round(hi * 100, 2)
    out['breakeven_dy_pct'] = {'arith_excess': be['ex_ann'], 'geometric_diff': be['cagr_diff'],
                               'note': '一定の配当利回りを両側に足したとき、費用後の算術の超過・幾何の年率差が 0 を超える配当（%/年・excess_stats の丸め 0.01 の範囲）'}
    dyu = {}
    for m_ in BENCH['lse_ew']:
        v = [LSE_DY[i][m_] for i in LSE_RET if m_ in LSE_RET[i] and m_ in LSE_DY.get(i, {}) and LSE_DY[i][m_] * 12 <= 0.30]
        if v:
            dyu[m_] = math.fsum(v) / len(v)
    ks = [k for k in dyu if 187101 <= k <= 191406]
    m = {k: v + dyu[k] for k, v in UK_IDX.items() if k in dyu}
    row = one(m, (187101, 190712))
    row['dy_mean_ann_pct'] = round(_stat.mean([dyu[k] for k in ks]) * 1200, 2)
    row['note'] = 'LSE の等分の配当の近似（月ごと・年30%超は除く）を指数に足した。配当の近似は LSE の区間1 だけ＝1871-01〜1907-12（健全性の点検の『1871〜1914』の 444 か月と同じ月）'
    out['rows']['lse_ew_dy_proxy_1871_1907'] = row
    x = build(r, R=UK_IDX, period=(187101, 190712))
    out['rows']['price_only_1871_1907'] = {'full_net': short_es(C.excess_stats(x['net'], x['b']))}
    out['note'] = ('事後（検査役の指摘 2026-09-28）。登録の H は価格だけの指数を 1.5 倍に持ち、借入には短期金利＋0.5% を丸ごと払う＝冬の月ごとに 0.5×配当利回り/12 だけ過小（年換算 0.25×dy）。'
                   '一定の配当利回りを戦略と相手の両側に足した感度。格付けは登録の C のまま（E5 は配当 4% 以上で不合格、3% なら合格）')
    return out


# ── (6)(7) LSE の読み込みの直し: 1株の額面（capitalpar）の変化・逆戻りしない約10倍の跳ね ──
def _jump_filter(r, mode):
    if not mode:
        return r, 0
    drop = set()
    for k, v in r.items():
        q = 1 + v
        if mode == 'gt300' and v > 3.0:
            drop.add(k)
        elif mode == 'x5' and (q >= 5 or q <= 0.2):
            drop.add(k)
        elif mode == 'x10sig' and q > 0 and any(abs(math.log(q) - e * math.log(10)) <= math.log(1.35) for e in (-2, -1, 1, 2)):
            drop.add(k)
    return {k: v for k, v in r.items() if k not in drop}, len(drop)


JUMP_NOTE = {'gt300': '株の月のリターン > +300% を欠測（検査役の再計算と同じ・両側）',
             'x5': '株の月の値の比が ×5 以上か ×1/5 以下を欠測（逆戻りしない跳ね・本物の暴落も落とす粗い版）',
             'x10sig': '株の月の値の比が 約10倍・約1/10・約100倍・約1/100（±35%）を欠測（単位の変わり目の形だけ）'}


def lse_panel_variant(par=False, jump=None):
    """D.lse_panel の写し（凍結した data 道具は書き換えない）。par=True で 1株の額面（capitalpar・月の組の3番目）の変化も落とす。
    jump で掃除の後に逆戻りしない跳ねを欠測にする（_jump_filter）。par=False・jump=None なら抽出と1ビットも違わない（実行時に確かめる）"""
    obj = D.lse_raw()
    raw, heads = obj['sec'], obj['headings']
    cnt = collections.Counter()
    ret, sect, plag, dy = {}, {}, {}, {}
    for i, rec in raw.items():
        if not D.lse_is_common(rec):
            continue
        Mo = rec['m']
        ks = sorted(k for k in Mo if Mo[k][0])
        if not ks:
            continue
        r, sruns, pl, dv = {}, [], {}, {}
        for a, b in zip(ks, ks[1:]):
            va, vb = Mo[a], Mo[b]
            if D.madd(a, 1) != b:
                continue
            sa = D.lse_sector(rec['file'], heads[va[9]])
            if sa == 'EXCLUDE':
                continue
            if (va[1] and vb[1] and va[1] != vb[1]) or (va[3] and vb[3] and va[3] != vb[3]) or (va[6] and vb[6] and va[6] != vb[6]):
                continue
            if par and va[2] and vb[2] and va[2] != vb[2]:
                cnt['drop_par_change'] += 1
                continue
            r[b] = vb[0] / va[0] - 1
            pl[b] = va[0]
            basis = va[1] or va[2] or va[3] or va[6]
            if va[7] is not None and basis:
                dv[b] = va[7] / 100 * basis / 12 / va[0]
            if sruns and sruns[-1][2] == sa and sruns[-1][1] == D.madd(b, -1):
                sruns[-1][1] = b
            else:
                sruns.append([b, b, sa])
        r = D.clean_returns(r, cnt)
        r, nj = _jump_filter(r, jump)
        cnt['drop_jump'] += nj
        if not r:
            continue
        ret[i] = r
        sect[i] = sruns
        plag[i] = {k: v for k, v in pl.items() if k in r}
        dy[i] = {k: v for k, v in dv.items() if k in r}
    return {'ret': ret, 'sect': sect, 'plag': plag, 'dy': dy, 'counts': dict(cnt)}


def lse_variant_run(units, fam_of, par, jump):
    P = lse_panel_variant(par, jump)
    ret, sect = P['ret'], P['sect']
    LI, _ = D.lse_industries({'ret': ret, 'sect': sect})
    bew = ew(ret, LSE_SEG_M)
    lk = [k for k in sorted(set(bew) & set(UK_IDX)) if 187101 <= k <= 191406]
    res = {'par': par, 'jump': jump, 'jump_note': JUMP_NOTE.get(jump), 'counts': P['counts'],
           'stock_months': sum(len(d) for d in ret.values()),
           'n_gt300': sum(1 for d in ret.values() for v in d.values() if v > 3.0),
           'n_gt500': sum(1 for d in ret.values() for v in d.values() if v > 5.0),
           'sanity_corr_lse_ew_vs_boe_1871_1914': {'corr': corr_d(bew, UK_IDX, lk), 'n': len(lk), 'threshold': 0.6},
           'lse_ew_arith_cagr_pct': {f'{a}-{z}': round(C.cagr(C.window(bew, a, z)) * 100, 2) for a, z in ((186902, 188712), (188801, 190712), (191502, 192912))}}
    res['sanity_corr_lse_ew_vs_boe_1871_1914']['ok'] = (res['sanity_corr_lse_ew_vs_boe_1871_1914']['corr'] or 0) >= 0.6
    vu = {}
    for uid in D.FAMILIES['B'] + D.FAMILIES['D']:
        r = RULES[uid]
        vu[uid] = unit_eval(r, R=(ret if r['data'] == 'lse_stk' else LI), bench_R=(ret if r['kind'] != 'ind_trend' else None))
    g = grade_units(vu, fam_of)
    rows = {}
    for uid, v in vu.items():
        st, st0 = v['stats'], units[uid]['stats']
        r = RULES[uid]
        wl = None
        if r['kind'] != 'ind_trend':
            Rv = ret if r['data'] == 'lse_stk' else LI
            top, bot = hold_side(r, Rv, Rv, 'top'), hold_side(r, Rv, Rv, 'bottom')
            wl = {'top_minus_bottom_gross': short_es(C.excess_stats(top['s'], bot['s'])), 'bottom_net_vs_bench': short_es(C.excess_stats(bot['net'], v['x']['b']))}
        rows[uid] = {'full_net': short_es(st['full_net']), 'h1_cagr_diff': st['h1_net']['cagr_diff'], 'h2_cagr_diff': st['h2_net']['cagr_diff'],
                     'drop_top': {'excluded': v['drop_top']['excluded'], 'net_vs_b': short_es(v['drop_top']['net_vs_b'])},
                     'grade': g[uid]['grade'], 'criteria': g[uid]['criteria'], 'holm_p_one_family': g[uid]['holm_p_one_family'],
                     'registered_full_net': short_es(st0['full_net']), 'winners_minus_losers': wl}
    res['rows'] = rows
    res['grade_counts_B_D'] = dict(collections.Counter(x['grade'] for x in rows.values()))
    res['_LI'], res['_ret'], res['_sect'], res['_dy'], res['_vu'] = LI, ret, sect, P['dy'], vu
    return res


def lse_variants(units, fam_of):
    base = lse_panel_variant(False, None)
    ext_ret = LSE_RET
    same = (set(base['ret']) == set(ext_ret) and all(base['ret'][i] == ext_ret[i] for i in ext_ret)
            and all(base['plag'][i] == LSE_PLAG.get(i, {}) for i in ext_ret)
            and all(base['dy'][i] == LSE_DY.get(i, {}) for i in ext_ret)
            and all([list(x) for x in base['sect'][i]] == [list(x) for x in LSE_SECT[i]] for i in ext_ret))
    out = {'copy_reproduces_registered_panel': same}
    if not same:
        raise SystemExit('LSE の写しが登録の抽出と一致しない → 止まる')
    # 額面の変化が残した月（登録の版）
    obj = D.lse_raw()
    pc = []
    for i, rec in obj['sec'].items():
        if i not in LSE_RET:
            continue
        Mo = rec['m']
        for b, v in LSE_RET[i].items():
            a = D.madd(b, -1)
            va, vb = Mo.get(a), Mo.get(b)
            if va and vb and va[2] and vb[2] and va[2] != vb[2]:
                pc.append((i, b, v, va[2], vb[2], va[0], vb[0]))
    rs = [x[2] for x in pc]
    ex = sorted(pc, key=lambda x: -x[2])[:5]
    out['par_change_months_in_registered_panel'] = {'n': len(pc), 'mean_monthly_ret': round(_stat.mean(rs), 4) if rs else None,
                                                    'n_gt300': sum(1 for x in rs if x > 3), 'n_lt_minus80': sum(1 for x in rs if x < -0.8),
                                                    'examples': [{'id': i, 'name': obj['sec'][i]['name'][:40], 'month': b, 'ret': round(v, 3), 'par': [pa, pb], 'price': [p0, p1]} for i, b, v, pa, pb, p0, p1 in ex]}
    reg_ext = {'n_gt300': sum(1 for d in LSE_RET.values() for v in d.values() if v > 3.0), 'n_gt500': sum(1 for d in LSE_RET.values() for v in d.values() if v > 5.0)}
    out['registered_panel_extremes'] = reg_ext
    V = {}
    for name, par, jump in (('par', True, None), ('gt300', False, 'gt300'), ('par_x10sig', True, 'x10sig'), ('par_x5', True, 'x5')):
        V[name] = lse_variant_run(units, fam_of, par, jump)
        log('LSE variant', name, V[name]['grade_counts_B_D'], V[name]['sanity_corr_lse_ew_vs_boe_1871_1914'])
    # 額面を直した版の上で D_S3 の配当をそろえる（(3) と (6) の両方）
    pv = V['par']
    s3par = fix_s3_dividend(pv['_vu'], fam_of, LI=pv['_LI'], ret=pv['_ret'], sect=pv['_sect'], dy=pv['_dy'], label='par_fixed_panel')
    for k in list(V):
        for kk in ('_LI', '_ret', '_sect', '_dy', '_vu'):
            V[k].pop(kk, None)
    out['variants'] = V
    out['s3_dividend_on_par_fixed_panel'] = s3par
    out['note'] = ('事後（検査役の指摘 2026-09-28）。登録の掃除（D.lse_panel）は 払込額・amntshare・sharestock の変化は落とすが、1株の額面（capitalpar）の変化を見ていない＝'
                   '額面 £10→£100 の併合などの単位の変更が +900% 前後のリターンとして残る。par で額面の変化の対も落とした。gt300・x10sig・x5 は逆戻りしない跳ねの粗い版（JUMP_NOTE）。'
                   '各版で B・D を作り直し、同じ族の Holm（族の他の単位もその版の値）で grade_era を当てた（事後・格付けは登録の版）。'
                   's3_dividend_on_par_fixed_panel は額面を直した版の上で D_S3 の配当をそろえた（族の Holm の他の単位は額面を直した版）')
    return out


DEVIATIONS = [
    {'what': '健全性の点検の順番と、止まる条件に触れたのに止まらなかったこと',
     'detail': '事前登録は sanity_checks_before_results（成績の前の点検）と書いたが、この道具は同じ実行の中で 22 単位の成績を計算して画面に出した後に点検した（私は点検の前に A〜H の超過・t を見た）。'
               'その点検で LSE の等分とイングランド銀行の指数（Smith-Horne 1871〜1914）の相関が 0.483 で線 0.6 を下回り、登録の『読み込みを疑って止まる』に当たった。止まらずに調べた（post_hoc.sanity_stop_investigation）: '
               '読み込みの誤りを示す明確な形は見つからなかった（1869〜1870 の LSE の等分と Smith-Horne の相関 0.789・n23／大手の鉄道の普通株9つの相関は株どうしの中央 0.32〔最大 0.67〕に対し Smith-Horne とは 0.09〜0.37）が、確証も無い。'
               'LSE の株の月の 43% が値動き0（古い気配）で、等分の算術平均は株ごとのノイズで大きく上振れる（1869〜1887 年率 算術 +8.75% 対 対数の平均 −1.74% 対 イングランド銀行 −0.08%）。',
     'affects_grade': True,
     'how': '★検査役の指摘（2026-09-28）で直した: 相手どうしの形の点検（sanity_shape）を成績の前に回し、止まる条件に触れたデータ（LSE）の単位＝B 3・D 8 の主の格付けを '
            "'PENDING_stop' にした（grade_counts・rule_level_verdicts・R11 はこの主の版）。登録どおりに出した格付け（S 9・A 2・B 8・C 3）は "
            "'grade_provisional_if_lse_reading_ok'・grade_counts_provisional_if_lse_reading_ok・rule_level_verdicts_provisional_if_lse_reading_ok に移した。"
            '事後の診断（勝者−敗者・幾何で束ねた版・極端値を落とした版・窓を2〜3か月あけた版）と、検査役が見つけた読み込みの穴（額面の変化・逆戻りしない約10倍の跳ね）を直した版を post_hoc に並べた。'
            '初回の実行（直す前）は点検の前に成績を画面に出した＝私は B・D の成績を見た後でこの順番に直した（汚れは消せない）'},
    {'what': '組を作れる月数の点検（±1）で、4 単位が 2〜4 か月ずれた',
     'detail': 'A_S3 L2/L3 659（事前登録『約 657』）・D_F1b 578（580）・D_S3 L2/L3 642（『約 646』）。事前登録の数は形成の窓のリターンの有無だけで数えた近似（S3 は『約』と明記）で、組み立ては保有の月にリターンのある構成要素が1つ以上あること（F1b は6つの組すべて）と現金の金利を足して要る。データも規則も変えていない',
     'affects_grade': False},
    {'what': 'R3 の『単価を片道 0.50%・1.00%』の読み方',
     'detail': '各規則の費用の式の形（two＝両側 Σ|Δw|×単価・one＝片道 ½Σ|Δw|×単価・moved・dL）はそのままで単価だけを替えた（業種の G3・G4・P9 は two なので、同じ単価でも one の規則の2倍の費用になる）', 'affects_grade': False},
    {'what': 'R7 の作り方の選び',
     'detail': '(a) 時価加重は 1869-02〜1887-12・形成は全株・持つのは株数の分かる株、相手も株数の分かる株の時価加重 (b) p_{t−1}<£1 の月のリターンを両側の R から落とした（形成の窓にも効く）(c) 登録の実装は配当を足した R で形成もした→ 配当の近似の外れ値（年 100% 超が約 1%・最大 1万%）の株が勝者に選ばれ続けて差が +14%/年に膨らんだ＝信頼できない。事後に『形成は価格だけ・保有の月だけ配当（年30%超は足さない）』を post_hoc.dividend_holding_only に置いた',
     'affects_grade': False},
    {'what': 'R8 の D（業種）', 'detail': '途切れた翌月の −30% をその株の最後の区切りの業種に入れて LSE の業種を作り直した（近似）。B・C は株のまま', 'affects_grade': False},
    {'what': 'R4 の F16g', 'detail': 'eknzbh mw_momentum_prereg5 の F16 の作り方（翌月と同じ暦月の a〜b 年前の平均・上位 K=max(2,四捨五入(割合×N))・1か月持つ・正確な回転×0.05%）。候補の下限は元に無いので、この角度の F3g と同じ 5 にした。窓は区間の中だけ（LSE の区間2 は 15 年なので 11〜15・16〜20・1〜20 年は区間1 だけ）', 'affects_grade': False},
    {'what': '全体の C1〜C8', 'detail': 'この角度の格付けは事前登録どおり criteria_independent_era（E1〜E7・grade_era）。まとめ役の依頼にある C1〜C8 は、前半を『訓練』・後半を『保有』に読み替えた参考の値（C1_C8_reference）だけで、格付けではない（C1・C2・C3・C7 は費用前、C4・C6・C8 は費用後＝mw の約束）', 'affects_grade': False},
    {'what': 'シャープの現金', 'detail': 'E5 はその単位の rf（A_S3 は us_cash・D_S3 は uk_cash・H は uk_hal）。timing でない B・C のシャープ（報告だけ）は英国 uk_cash・米国 us_cash', 'affects_grade': False},
    {'what': '事後の診断で抽出に無い欄を読んだ', 'detail': '季節性と配当落ちの診断（post_hoc.seasonality_ex_dividend）のために、IMM の生の3ファイルから dvdpayable（配当の支払いの月）を読んだ（out/_nx_cache/nx_pre1926x_dvdpayable.json）。登録の抽出（sha 凍結）には入っていない欄で、格付けには使わない', 'affects_grade': False},
    {'what': '実装の直し（規則は不変）', 'detail': '初回の実行は季節性の規則（stk_seas）に skip の欄が無いため KeyError で止まった（B_ret_12_1 まで計算・保存なし）。欄が無いときは None を渡すように直して最初から実行し直した。excess_stats の β の計算を速くする細工（nx_stack.py と同じ・数値は同一）を入れた', 'affects_grade': False},
    {'what': '検査役の指摘（2026-09-28）による直し（fixes 欄）', 'detail': '7件を確かめ、7件とも誤りと確認した。主の格付けに効くのは (1) 止まる条件の扱い（B・D を PENDING_stop）だけ。'
               '(2)〜(7) は凍結した data 道具を書き換えずに、この道具の中に写した版で直した数字を事後として並べた（tools.measure_next の約束: 格付けは登録の版）。詳細は fixes', 'affects_grade': True},
]


# ═════════════════════════ 8. 本体 ═════════════════════════
def verdict_primary(gs):
    """主のまとめ: PENDING_stop（止まる条件）と NA は数えない。格付けできる単位が PENDING だけなら『保留』"""
    real = [g for g in gs if g in ('S', 'A', 'B', 'C')]
    if not real and any(g == 'PENDING_stop' for g in gs):
        return '保留（止まる条件に触れたデータの単位だけ）'
    return D.rule_verdict(real)


def verdict_table(stu, gmap, primary=True):
    out = {}
    for src, lst in stu.items():
        ids = [x.split('（')[0] for x in lst]
        gs = [gmap.get(i, 'NA') for i in ids]
        v = {'units': dict(zip(ids, gs)), 'verdict': verdict_primary(gs) if primary else D.rule_verdict(gs)}
        pend = [i for i, g in zip(ids, gs) if g == 'PENDING_stop']
        if pend:
            v['pending_units'] = pend
        out[src] = v
    return out


def main():
    t0 = datetime.datetime.now()
    # ★事前登録どおり、相手どうしの形の点検を成績の前に回す（検査役の指摘 2026-09-28 で直した順番）
    log('sanity (shape) before results...')
    shape = sanity_shape()
    STOP = [u for u in shape['stopped_units']]
    if STOP:
        log('⚠ 相手どうしの形の点検で閾値を下回った:', shape['stop_on_shape'], '→ 主の格付けに入れない単位', STOP)
    units = run_main()
    fam_of = {u: RULES[u]['fam'] for u in UNIT_IDS}
    # 主: 止まる条件の外の単位だけを格付けする（族はデータの単位ごとなので、A・C・H の Holm は B・D に左右されない）
    G_main = grade_units({u: units[u] for u in UNIT_IDS if u not in STOP}, fam_of)
    # 暫定（LSE の読み込みが正しかったとしたら）: 止まる条件に触れた単位を登録どおりに格付けした値（主には使わない）
    G_prov = grade_units({u: units[u] for u in UNIT_IDS if u in STOP}, fam_of) if STOP else {}
    G_all = {**G_main, **G_prov}
    G = {u: ({'grade': 'PENDING_stop', 'criteria': None, 'p_one': G_prov[u]['p_one'], 'holm_p_one_family': None} if u in STOP else G_main[u]) for u in UNIT_IDS}
    # R11: 22 単位ぜんぶの Holm（主は止まった単位を p=1 で数える＝NA_short と同じ扱い・暫定は実際の p）
    pone_prov = {u: G_all[u]['p_one'] for u in UNIT_IDS}
    pone_main = {u: (1.0 if u in STOP else G_all[u]['p_one']) for u in UNIT_IDS}
    prog_holm, prog_holm_prov = C.holm(pone_main), C.holm(pone_prov)
    # 参考の C1〜C8（後半の族内 Holm は両側 p）
    hold_p = {}
    for u in UNIT_IDS:
        h2 = units[u]['stats'].get('h2_gross')
        hold_p[u] = h2['p'] if h2 and h2['p'] is not None else 1.0
    fam_hold_holm = {}
    for f in 'ABCDH':
        fam_hold_holm.update(C.holm({u: hold_p[u] for u in UNIT_IDS if fam_of[u] == f}))
    log('sanity (rest)...')
    san = sanity(units, shape)
    tested = []
    for u in UNIT_IDS:
        r = RULES[u]
        st = units[u]['stats']
        row = {
            'id': u, 'family': r['fam'], 'key': r['key'], 'src_rules': r['src'], 'kind': r['kind'], 'what': r['what'],
            'data': r.get('data'), 'bench': r.get('bench'), 'cost_spec': list(r['cost']), 'timing': bool(r.get('timing')),
            'grade': G[u]['grade'], 'criteria_E': G[u]['criteria'], 'p_one': G_all[u]['p_one'], 'holm_p_one_family': G[u]['holm_p_one_family'],
            'grade_provisional_if_lse_reading_ok': G_all[u]['grade'],
            'holm_p_one_program22': prog_holm.get(u), 'holm_p_one_program22_provisional': prog_holm_prov.get(u),
            'months': st['months'], 'first': st['first'], 'last': st['last'], 'halves': st.get('halves'),
            'full_net': st.get('full_net'), 'h1_net': st.get('h1_net'), 'h2_net': st.get('h2_net'),
            'full_gross': st.get('full_gross'), 'h1_gross': st.get('h1_gross'), 'h2_gross': st.get('h2_gross'),
            'cost_drag_ann_pct': st.get('cost_drag_ann'), 'turnover_ann_oneway': units[u]['turnover_ann'],
            'roll20_net': st.get('roll20'), 'dca20_net_by_segment': st.get('dca20'),
            'maxdd_pct': st.get('maxdd'), 'sharpe': st.get('sharpe'),
            'drop_top': units[u]['drop_top'],
            'train_hold_note': '訓練（〜2006）・保有（2007〜）は無い（この角度は 1709〜1929 年だけ）。前半・後半（数で二分）を代わりに置いた＝h1/h2',
            'C1_C8_reference': ref_c1_c8(st, r, fam_hold_holm.get(u)),
        }
        if u in STOP:
            row['criteria_E_provisional_if_lse_reading_ok'] = G_all[u]['criteria']
            row['holm_p_one_family_provisional'] = G_all[u]['holm_p_one_family']
            row['grade_flag'] = ('⚠ 事前登録の健全性の点検（LSE の等分とイングランド銀行の指数の相関 ≥0.6）が '
                                 f"{shape['lse_ew_vs_boe_1871_1914']['corr']} で線を下回った＝『読み込みを疑って止まる』条件に触れた単位（LSE を使う B・D）。"
                                 "主の格付けは 'PENDING_stop'（grade_counts・rule_level_verdicts に入れない）。登録どおりに出した値は grade_provisional_if_lse_reading_ok（暫定）。"
                                 '事後の調べ（post_hoc.sanity_stop_investigation）と、検査役が見つけた読み込みの穴を直した版（fixes・post_hoc.fix_lse_reading）を必ず並べて読むこと')
        tested.append(row)
    for u, why in NOT_TESTABLE.items():
        tested.append({'id': u, 'family': u[0], 'grade': 'NA_not_testable_by_shape', 'why': why,
                       'src_rules': RULES[u]['src'] if u in RULES else None})
    # 元の規則ごとのまとめ（主＝止まる条件の外の単位だけ・暫定＝登録どおり）
    stu = PRE['why_new']['survivor_to_unit']
    gmap = {t['id']: t['grade'] for t in tested}
    gmap_prov = dict(gmap)
    gmap_prov.update({u: G_all[u]['grade'] for u in UNIT_IDS})
    verdicts = verdict_table(stu, gmap, primary=True)
    verdicts_prov = verdict_table(stu, gmap_prov, primary=False)
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
    rep['R11_program_holm'] = {'holm_p_one': prog_holm, 'pass_0.05': [u for u, p in prog_holm.items() if p < 0.05],
                               'holm_p_one_provisional_if_lse_reading_ok': prog_holm_prov, 'pass_0.05_provisional': [u for u, p in prog_holm_prov.items() if p < 0.05],
                               'note': '主は止まる条件に触れた B・D の 11 単位を p=1 で数えた（NA_short と同じ扱い・m=22 のまま）。暫定は登録どおりの p'}
    rep['R12_turnover'] = {u: units[u]['turnover_ann'] for u in UNIT_IDS}
    grades = collections.Counter(G[u]['grade'] for u in UNIT_IDS)
    grades_prov = collections.Counter(G_all[u]['grade'] for u in UNIT_IDS)
    log('post-hoc...')
    ph = post_hoc(units)
    log('fixes (検査役の指摘)...')
    fx_p9 = fix_p9_exact(units, fam_of); log('fix P9 done')
    fx_s3 = fix_s3_dividend(units, fam_of); log('fix S3 dividend done')
    fx_h = fix_h_dividend(units, fam_of); log('fix H dividend done')
    fx_lse = lse_variants(units, fam_of); log('fix LSE reading done')
    ph['fix_p9_exact_ties'] = fx_p9
    ph['fix_s3_dividend_units_aligned'] = fx_s3
    ph['fix_h_dividend_sensitivity'] = fx_h
    ph['fix_lse_reading'] = fx_lse
    # 暫定の表: LSE の読み込みが正しかったとして、検査役の直しを当てた版の格付け（すべて事後・主には使わない）
    V = fx_lse['variants']
    s3p = fx_lse['s3_dividend_on_par_fixed_panel']['rows']
    prov_table = {}
    for u in STOP:
        row = {'registered_provisional': G_all[u]['grade']}
        for k in V:
            row[f'lse_{k}'] = V[k]['rows'][u]['grade']
        if 'S3' in u:
            row['dividend_aligned_registered_panel'] = fx_s3['rows'][f'{u}_div_x1.0']['grade']
            row['dividend_aligned_par_fixed_panel'] = s3p[f'{u}_div_x1.0']['grade']
        if u == 'D_P9_multi_5':
            row['p9_exact_ties'] = fx_p9[u]['grade_exact_ties']
        prov_table[u] = row
    corrected = {}
    for u in STOP:
        corrected[u] = (s3p[f'{u}_div_x1.0']['grade'] if 'S3' in u else V['par']['rows'][u]['grade'])
    gmap_corr = dict(gmap_prov)
    gmap_corr.update(corrected)
    fixes = build_fixes(units, G_all, grades, grades_prov, verdicts, verdicts_prov, shape, rep, fx_p9, fx_s3, fx_h, fx_lse, corrected)
    out = {
        'angle': 'nx_pre1926x', 'prereg': 'out/nx_pre1926x_prereg.json', 'generated': datetime.date.today().isoformat(),
        'frozen_check': FROZEN,
        'criteria_used': 'criteria_independent_era（nx_pre1926x_data.grade_era）。C1〜C8 は参考（事後・前半/後半の読み替え）だけ',
        'grade_counts': dict(grades),
        'grade_counts_note': ("主の格付け。事前登録の健全性の点検（LSE の等分とイングランド銀行の指数の相関 ≥0.6）に触れた LSE の単位（B 3・D 8）は 'PENDING_stop'＝格付けしない。"
                              '格付けできたのは A 9・C 1・H 1 の11単位'),
        'grade_counts_provisional_if_lse_reading_ok': dict(grades_prov),
        'grade_counts_provisional_note': ('暫定（主ではない）: 止まる条件を無視して B・D を登録どおりに格付けした値。検査役の指摘で、この S 9 のうち D_S3 の2つは単位の不一致'
                                          '（価格だけの株と総リターンの現金）に乗っていて、配当をそろえると C（→ provisional_corrected_by_fixes）'),
        'tested': tested,
        'rule_level_verdicts': verdicts,
        'rule_level_verdicts_provisional_if_lse_reading_ok': verdicts_prov,
        'provisional_grade_table_B_D': prov_table,
        'provisional_corrected_by_fixes': {
            'grades_B_D': corrected,
            'grade_counts_all22': dict(collections.Counter(gmap_corr[u] for u in UNIT_IDS)),
            'rule_level_verdicts': verdict_table(stu, gmap_corr, primary=False),
            'note': ('事後・主には使わない: LSE の読み込みが正しかったとして（止まる条件を外した仮定）、検査役が見つけた2つの明白な穴を直した版——'
                     '1株の額面（capitalpar）の変化の対を落とした LSE（fix_lse_reading.variants.par）と、D_S3 の株の脚に配当の近似を足して現金の脚と単位をそろえた版。'
                     'A・C・H は主の格付けのまま。逆戻りしない跳ね（gt300・x10sig・x5）は選び方に任意さがあるので感度として並べるだけ（provisional_grade_table_B_D）')},
        'fixes': fixes,
        'sanity_checks': san,
        'reports_not_graded': rep,
        'deviations_from_prereg': DEVIATIONS,
        'post_hoc': ph,
        'runtime_sec': None,
    }
    out['post_hoc']['interpretation'] = interpret(out)
    out['runtime_sec'] = (datetime.datetime.now() - t0).total_seconds()
    return out, units


def build_fixes(units, G_all, grades, grades_prov, verdicts, verdicts_prov, shape, rep, fx_p9, fx_s3, fx_h, fx_lse, corrected):
    V = fx_lse['variants']
    se = lambda u: short_es(units[u]['stats']['full_net'])
    r3 = rep['R3_costs']
    one_ids = [u for u in UNIT_IDS if RULES[u]['cost'][0] == 'one']
    fx = []
    fx.append({
        'id': 'F1_stop_condition', 'verified': True, 'severity': 'changes_grade',
        'finding': '事前登録の止まる条件（LSE の等分とイングランド銀行の指数の相関 ≥0.6）に触れたのに、B・D の格付けが grade_counts と rule_level_verdicts に印なしで入っていた',
        'check': f"相関 {shape['lse_ew_vs_boe_1871_1914']['corr']}（n={shape['lse_ew_vs_boe_1871_1914']['n']}）＜ 0.6 を再計算で確認。旧版は点検を成績の後に回し、log を出すだけで先へ進んでいた",
        'what_changed': "sanity_shape を run_main の前へ。止まったデータの単位（B 3・D 8）の主の格付けを 'PENDING_stop' にし、grade_counts・rule_level_verdicts・R11 を主の版にした。旧の値は *_provisional_if_lse_reading_ok へ移した",
        'before': {'grade_counts': dict(grades_prov), 'rule_level_verdicts': {k: v['verdict'] for k, v in verdicts_prov.items()}},
        'after': {'grade_counts': dict(grades), 'rule_level_verdicts': {k: v['verdict'] for k, v in verdicts.items()}},
        'affects_grade': True})
    before2 = {u: short_es(r3['rows'][u]['unit_0.01']['full']) for u in one_ids}
    after2 = {u: short_es(r3['rows'][u]['per_side_unit_0.01']['full']) for u in one_ids}
    fx.append({
        'id': 'F2_R3_one_vs_two', 'verified': True, 'severity': 'changes_numbers（報告 R3 だけ・格付けは不変）',
        'finding': "R3 の『片道 1%』で、one の式（½Σ|Δw|×u）の規則（F1b・F3g・株）は two の式（Σ|Δw|×u・G3・G4・P9）の半分の費用しか引いていなかった",
        'check': 'D._cost_of: one=0.5×Σ|Δw|×u・two=Σ|Δw|×u を確認。R3 は式の形を保って u だけ替えていた（事前登録の文言には沿う）。当時の売買1回ごとの費用として読むには各側に u が要る',
        'what_changed': "R3 の各行に per_side_unit_0.005・per_side_unit_0.01（Σ|Δw|×u にそろえた版）と summary_per_side_1pct を足し、note に one と two の単価の意味の違いを書いた",
        'before_unit_0.01_one_rules': before2, 'after_per_side_0.01_one_rules': after2,
        'summary_after': r3['summary_per_side_1pct'],
        'vs_auditor': '検査役の再計算（D_F1b +1.29 t1.02・F3g K15 +0.96 t0.45・K30 +0.03 t0.03 cd −0.26・9-0 −0.81 t−0.66・two の D_G3 +1.86 t1.57・D_P9 −3.59）と完全に一致',
        'retracted_summary': '実装者の前の要約『当時の現実に近い片道1%では LSE の D は6本のうち5本が正のまま（+1.5〜+3.8%/年）、t≥2 は F1b（t2.29）だけ』は one の規則の費用を半分に見積もっていたので撤回し、summary_after に置き換える',
        'affects_grade': False})
    s3 = fx_s3['rows']
    fx.append({
        'id': 'F3_D_S3_units', 'verified': True, 'severity': 'changes_grade（暫定の格付け。主は PENDING_stop）',
        'finding': 'D_S3（LSE の業種ごとの10か月線 2倍・3倍）は株の脚が価格だけ・現金の脚 uk_cash が総リターンの金利＝単位が混ざり、E5（前半・後半のシャープ）が有利に出ていた',
        'check': ('登録の値を再現した上で、配当の近似（R7 と同じ・年30%超は除く・業種平均 年'
                  f"{fx_s3['industry_dividend_yield']['mean_ann_pct']}%）を保有の月だけ戦略と相手の両側に足すと、前半のシャープが相手を下回る"),
        'what_changed': 'post_hoc.fix_s3_dividend_units_aligned（登録の LSE）と fix_lse_reading.s3_dividend_on_par_fixed_panel（額面を直した LSE）に並べた。格付けは登録の版（主は PENDING_stop）',
        'before': {u: {'full_net': s3[f'{u}_registered_price_only']['full_net'], 'sharpe_h1': s3[f'{u}_registered_price_only']['sharpe_h1'],
                       'sharpe_h2': s3[f'{u}_registered_price_only']['sharpe_h2'], 'grade_provisional': G_all[u]['grade']} for u in ('D_S3_FABER_L2', 'D_S3_FABER_L3')},
        'after': {k: {kk: v[kk] for kk in ('full_net', 'sharpe_h1', 'sharpe_h2', 'grade')} for k, v in s3.items() if '_div_' in k},
        'rule_note': "S3（業種ごとの10か月線）は単位をそろえると A（Cowles・総リターン同士）も D も C＝規則のまとめは『割れた』ではなく『再現せず』。D_S3 の S は『価格だけの株と総リターンの現金を混ぜたときだけ出る暫定の格付け』",
        'affects_grade': True})
    hr = fx_h['rows']
    fx.append({
        'id': 'F4_H_units', 'verified': True, 'severity': 'changes_numbers（格付け C は不変）',
        'finding': "H（英国のハロウィーン1.5倍）の負の超過は、価格だけの指数を 1.5 倍に持ちながら借入の金利を丸ごと払う単位の不一致による人工物（冬の月ごとに 0.5×配当/12 だけ過小）",
        'check': (f"登録の値（{hr['registered_price_only']['full_net']}）を再現した上で、一定の配当利回りを両側に足して再計算: 算術の超過は配当 {fx_h['breakeven_dy_pct']['arith_excess']}%・"
                  f"幾何の差は {fx_h['breakeven_dy_pct']['geometric_diff']}% を超えると正に反転する"),
        'what_changed': 'post_hoc.fix_h_dividend_sensitivity に配当 1〜5%（1709〜1914）と LSE の配当の近似（1871〜1907）と符号が反転する配当（breakeven_dy_pct）を並べた。格付けは登録の C（E5 だけで決まる: 配当 4% 以上で C、3% なら S 相当）',
        'before': hr['registered_price_only'],
        'after': {k: {kk: v.get(kk) for kk in ('full_net', 'h1_cagr_diff', 'h2_cagr_diff', 'sharpe_h1', 'sharpe_h2', 'grade', 'months')} for k, v in hr.items() if k != 'registered_price_only'},
        'reading': "『英国のハロウィーンは超過が負』とは書かない。『超過の符号は配当の扱いで反転する。格付け C は E5（シャープの比較）だけで決まり、配当 4% 以上なら C のまま、3% なら S』",
        'affects_grade': False})
    fx.append({
        'id': 'F5_P9_ties', 'verified': True, 'severity': 'changes_numbers（格付けは不変）',
        'finding': "P9 の同点が docstring の『名前の順』になっていなかった（百分位の平均を浮動小数で足すため、数学的に同点の業種が最後の1桁の差で並ぶ）",
        'check': f"組が変わる形成の月 A {fx_p9['A_P9_multi_5']['formation_months_changed']}/{fx_p9['A_P9_multi_5']['formation_months']}・D {fx_p9['D_P9_multi_5']['formation_months_changed']}/{fx_p9['D_P9_multi_5']['formation_months']}",
        'what_changed': 'post_hoc.fix_p9_exact_ties に 2×順位の和（整数）で (−和, 名前) に並べた版を置いた（凍結した data 道具の build_ind_multi は書き換えない＝格付けは登録の版）。規則の誤読（実装の誤り）の是正で、規則そのものは変えていない',
        'before': {u: fx_p9[u]['registered'] for u in fx_p9}, 'after': {u: {**fx_p9[u]['exact_ties'], 'grade': fx_p9[u]['grade_exact_ties']} for u in fx_p9},
        'affects_grade': False})
    vp = V['par']
    fx.append({
        'id': 'F6_LSE_par_change', 'verified': True, 'severity': 'changes_grade（暫定の格付け。主は PENDING_stop）',
        'finding': 'LSE の払込・分割・併合の除外が 1株の額面（capitalpar）の変化を見ておらず、額面 £10→£100 の併合などが +900% 前後のリターンとして残っていた',
        'check': (f"登録の版に額面が変わった（前後とも値あり）株×月が {fx_lse['par_change_months_in_registered_panel']['n']}（平均 月 "
                  f"{fx_lse['par_change_months_in_registered_panel']['mean_monthly_ret'] * 100:+.1f}%・+300% 超 {fx_lse['par_change_months_in_registered_panel']['n_gt300']}・"
                  f"−80% 未満 {fx_lse['par_change_months_in_registered_panel']['n_lt_minus80']}）。例は fix_lse_reading.par_change_months_in_registered_panel.examples"),
        'what_changed': "lse_panel_variant（D.lse_panel の写し・写しが抽出と1ビットも違わないことを実行時に確認）に `va[2] and vb[2] and va[2] != vb[2]` の除外を足した版で B・D を作り直した（fix_lse_reading.variants.par）",
        'before': {'grades_provisional': {u: G_all[u]['grade'] for u in D.FAMILIES['B'] + D.FAMILIES['D']},
                   'full_net': {u: se(u) for u in D.FAMILIES['B'] + D.FAMILIES['D']},
                   'sanity_corr': shape['lse_ew_vs_boe_1871_1914']['corr'],
                   'lse_ew_arith_cagr_1869_1887': ph_cagr(BENCH['lse_ew'])},
        'after': {'grades_provisional': {u: vp['rows'][u]['grade'] for u in vp['rows']},
                  'full_net': {u: vp['rows'][u]['full_net'] for u in vp['rows']},
                  'sanity_corr': vp['sanity_corr_lse_ew_vs_boe_1871_1914']['corr'],
                  'lse_ew_arith_cagr_1869_1887': vp['lse_ew_arith_cagr_pct']['186902-188712']},
        'stop_condition_after_fix': '額面を直しても相関は線 0.6 に届かない＝止まる条件は残る（主は PENDING_stop のまま）' if not vp['sanity_corr_lse_ew_vs_boe_1871_1914']['ok'] else '額面を直すと線を超える（ただし主は登録の読み込みで判定＝PENDING_stop のまま）',
        'vs_auditor': ('検査役の再計算（D_G3 cd 4.31 t4.21・B_ret 1.30 t2.36 前半/後半 +0.38/+2.25・B_seas t2.49・1869〜1887 の等分の CAGR 5.16%・相関 0.499）と向きと格付け（B_ret・B_seas が B→S、他は S のまま）は同じで、'
                       '数字は少し違う。こちらは登録の lse_panel の写し（抽出と1ビット一致を確認）に額面の条件を1つ足し、掃除（跳ねて戻る形）の前に対を落とした＝'
                       '掃除の後に額面の変わった月を消す作り方とは、跳ねて戻る形の判定に巻き込まれる月（掃除の件数 411→367）だけ違う'),
        'affects_grade': True})
    fx.append({
        'id': 'F7_LSE_non_reversing_jumps', 'verified': True, 'severity': 'changes_numbers（暫定の格付けの感度）',
        'finding': '逆戻りしない約10倍の跳ね（系列の最後の月・額面の欄が変わらない気配の単位の変更）が掃除（跳ねて戻る形だけを捕まえる）をすり抜けている',
        'check': (f"登録の版で r>+300% が {fx_lse['registered_panel_extremes']['n_gt300']}・+500% 超 {fx_lse['registered_panel_extremes']['n_gt500']}。"
                  f"額面を直した後も r>+300% が {V['par']['n_gt300']} 残る"),
        'what_changed': '事後の感度として gt300（登録の版で r>+300% を両側から欠測・検査役の再計算と同じ）・par_x10sig（額面を直した上で約10倍・約1/10・約100倍・約1/100 の月を欠測）・par_x5（額面を直した上で ×5 以上・×1/5 以下を欠測）を fix_lse_reading.variants に並べた。どれが正しいかは原本の紙面を見ないと決められないので、主にも暫定の直した版（provisional_corrected_by_fixes）にも入れない',
        'vs_auditor': '検査役の再計算（r>+300% を両側から外す: D_G3 cd 5.38→3.41 t5.11・D_S3 L2 3.39→2.61・B_F1a1 3.89→3.95）は gt300 で完全に再現した',
        'after': {k: {'grades': {u: V[k]['rows'][u]['grade'] for u in V[k]['rows']},
                      'full_net': {u: V[k]['rows'][u]['full_net'] for u in V[k]['rows']},
                      'counts': V[k]['counts'], 'sanity_corr': V[k]['sanity_corr_lse_ew_vs_boe_1871_1914']['corr']} for k in ('gt300', 'par_x10sig', 'par_x5')},
        'affects_grade': False})
    return fx


def ph_cagr(b):
    return round(C.cagr(C.window(b, 186902, 188712)) * 100, 2)


def interpret(out):
    """事後の読み（数字は同じ実行の結果から引く・格付けには使わない）"""
    T = {t['id']: t for t in out['tested']}
    ph = out['post_hoc']
    W = ph['winners_minus_losers']['rows']
    G = ph['geometric_aggregation']['rows']
    K = ph['longer_gap']['rows']
    TR = ph['trimmed_extremes']['rows']
    V = ph['fix_lse_reading']['variants']
    VP = V['par']['rows']
    S3 = ph['fix_s3_dividend_units_aligned']['rows']
    S3p = ph['fix_lse_reading']['s3_dividend_on_par_fixed_panel']['rows']
    HD = ph['fix_h_dividend_sensitivity']['rows']
    P9 = ph['fix_p9_exact_ties']
    f = lambda e: None if not e else f"{e['ex_ann']:+.2f}%/年 t{e['t']}"
    sc = out['sanity_checks']['lse_ew_vs_boe_1871_1914']
    lines = []
    gc = out['grade_counts']
    lines.append(f"主の格付け: 事前登録の止まる条件（LSE の等分とイングランド銀行の指数の相関 {sc['corr']} < 0.6）に触れた LSE の11単位（B 3・D 8）は PENDING_stop。"
                 f"格付けできた11単位（Cowles の業種 A 9・Old NYSE の C 1・英国の指数 H 1）は "
                 + '・'.join(f'{k} {v}' for k, v in sorted(gc.items()) if k != 'PENDING_stop') + f"。S は {gc.get('S', 0)}。"
                 + '格付け A 以上: ' + ('・'.join(f"{u}（{T[u]['grade']}・{f(T[u]['full_net'])}・族の Holm 後 p {T[u]['holm_p_one_family']}）" for u in UNIT_IDS if T[u]['grade'] in ('S', 'A')) or 'なし'))
    d_ids = [u for u in D.FAMILIES['D'] if RULES[u]['kind'] != 'ind_trend']
    lines.append('D（LSE の業種の勢い 6本・暫定＝止まったデータの上）: 登録どおりなら全部 S。勝者−敗者は ' + '・'.join(f"{u[2:]} {f(W[u]['top_minus_bottom_gross'])}" for u in d_ids)
                 + '。額面の変化を直しても ' + '・'.join(f"{u[2:]} {f(VP[u]['full_net'])}（{VP[u]['grade']}）" for u in d_ids)
                 + '。窓を3か月あけても ' + '・'.join(f"{u[2:]} {f(K[u]['skip3'])}" for u in d_ids)
                 + '。幾何で束ねても ' + '・'.join(f"{u[2:]} {f(G[u])}" for u in d_ids)
                 + '。極端値を落としても ' + '・'.join(f"{u[2:]} {f(TR[u])}" for u in d_ids)
                 + '。売買の各側に 1% の費用では ' + '・'.join(f"{u[2:]} {f(out['reports_not_graded']['R3_costs']['per_side_1pct'][u])}" for u in d_ids)
                 + '＝ D の業種の勢いは元の規則の費用（0.05%）なら直した版でも残るが、当時の費用（売買の各側 1%）では t≥2 に届かない（しかも読み込みの点検が通らない限り格付けしない）')
    lines.append('D の S3（業種ごとの10か月線 2倍・3倍）: 登録どおりなら S だが、株の脚が価格だけ・現金の脚が総リターンの金利＝単位が混ざっていた。'
                 '配当の近似を保有の月だけ両側に足すと ' + '・'.join(f"{u[2:]} {f(S3[u + '_div_x1.0']['full_net'])}・前半シャープ {S3[u + '_div_x1.0']['sharpe_h1'][0]} 対 {S3[u + '_div_x1.0']['sharpe_h1'][1]}（{S3[u + '_div_x1.0']['grade']}）" for u in ('D_S3_FABER_L2', 'D_S3_FABER_L3'))
                 + '。額面を直した LSE でも ' + '・'.join(f"{u[2:]} {S3p[u + '_div_x1.0']['grade']}" for u in ('D_S3_FABER_L2', 'D_S3_FABER_L3'))
                 + '＝超過は大きくなるが（借入側に偏った E の分）、E5 で落ちる。A_S3（Cowles・総リターン同士）も C なので、S3 は単位をそろえると両方の時代で再現せず')
    lines.append('B_F1a1（LSE の株の上位10%・暫定）: 登録どおりなら S だが、勝者−敗者は ' + f(W['B_F1a1_top_decile']['top_minus_bottom_gross'])
                 + '・下位10% も相手に ' + f(W['B_F1a1_top_decile']['bottom_net_vs_bench'])
                 + '。額面を直すと勝者−敗者 ' + f((VP['B_F1a1_top_decile']['winners_minus_losers'] or {}).get('top_minus_bottom_gross'))
                 + '・下位10% の対 相手 ' + f((VP['B_F1a1_top_decile']['winners_minus_losers'] or {}).get('bottom_net_vs_bench'))
                 + '＝両端の十分位がともに相手（古い気配の多い等分）に勝つ形で、勢いの再現として数えてはいけない')
    lines.append('B_ret_12_1・B_seas（LSE の株・暫定）: 登録どおりなら B（' + f(T['B_ret_12_1_tercile']['full_net']) + '・' + f(T['B_seas_6_10an_tercile']['full_net'])
                 + '）。額面の変化を直すと ' + f(VP['B_ret_12_1_tercile']['full_net']) + f"（{VP['B_ret_12_1_tercile']['grade']}）・" + f(VP['B_seas_6_10an_tercile']['full_net'])
                 + f"（{VP['B_seas_6_10an_tercile']['grade']}）。勝者−敗者（登録）は " + f(W['B_ret_12_1_tercile']['top_minus_bottom_gross']) + '・' + f(W['B_seas_6_10an_tercile']['top_minus_bottom_gross'])
                 + '。季節性は配当落ちの月を拾う部分がある（seasonality_ex_dividend）。どれも止まる条件の外に出ていないので格付けしない')
    a_ids = [u for u in D.FAMILIES['A'] if RULES[u]['kind'] != 'ind_trend']
    lines.append('A（Cowles の業種の勢い 7本）: A 2本（G3・G4）・B 5本。勝者−敗者は ' + '・'.join(f"{u[2:]} {f(W[u]['top_minus_bottom_gross'])}" for u in a_ids)
                 + '。1871〜1898（業種 6〜18）は多くが負、1899〜1926 は正（R5）。元のまま（1か月あけない）は大きく勝つ（R1）が、それは月平均の見かけの自己相関（Working 1960）。'
                 + f"P9 の同点を名前の順に直すと {f(P9['A_P9_multi_5']['exact_ties']['full_net'])}（{P9['A_P9_multi_5']['grade_exact_ties']}・t<2 のまま）")
    lines.append('H（英国のハロウィーン 1.5倍 1709〜1914）: 格付け C（登録）。登録の超過 ' + f(HD['registered_price_only']['full_net'])
                 + ' は価格だけの指数を借入で持つ単位の不一致による人工物で、配当を両側に足すと 3% ' + f(HD['const_dy_3pct']['full_net']) + f"（{HD['const_dy_3pct']['grade']}）"
                 + '・4% ' + f(HD['const_dy_4pct']['full_net']) + f"（{HD['const_dy_4pct']['grade']}）・5% " + f(HD['const_dy_5pct']['full_net']) + f"（{HD['const_dy_5pct']['grade']}）"
                 + f"＝超過の符号は配当の扱いで反転する（算術の超過は配当 {ph['fix_h_dividend_sensitivity']['breakeven_dy_pct']['arith_excess']}%・幾何の差は {ph['fix_h_dividend_sensitivity']['breakeven_dy_pct']['geometric_diff']}% を超えると正）。"
                 + '格付けは E5（シャープの比較）だけで決まり、配当 4% 以上なら C のまま、3% なら S。1871〜1907 に LSE の配当の近似を足すと '
                 + f(HD['lse_ew_dy_proxy_1871_1907']['full_net']) + f"（{HD['lse_ew_dy_proxy_1871_1907']['grade']}）。ハロウィーンは 206年で 88年だけ勝ち（価格だけ・calendar_years）")
    lines.append('C（Old NYSE の株の勢い）: B（' + f(T['C_ret_12_1_tercile']['full_net']) + '・t<2）')
    lines.append('R3（費用の感度）: ' + out['reports_not_graded']['R3_costs']['summary_per_side_1pct'])
    return lines


if __name__ == '__main__':
    res, units = main()
    p = C.save(OUT, res)
    print('saved', p, res['grade_counts'])
