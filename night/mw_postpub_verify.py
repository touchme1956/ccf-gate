#!/usr/bin/env python3
"""night/mw_postpub_verify.py — mw_postpub（公表されたらすぐ採用）の主張を反証しに行く検証（読むだけ・門には不使用）

2026-09-28 の mw（市場に勝てる歴史検証）の敵対的検証。研究側（night/mw_postpub.py）の S/A 候補と、
保有期間の超過で上位の B 2本を、独立に作り直したコードで再計算し、弱点を探す。

独立に書いたもの: 出典表の読み取り（公表年・向き・群）、三分位の読み込み（銘柄数つき）、
  実時間の採用者（Z）・市場＋傾き（ZT）・特徴ごとの良い側（C）の構成、超過の平均・Newey-West t・幾何の年率差・
  転がる20年窓・毎月積立20年・費用・格付け（C1〜C7 を out/mw_prereg.json から読み直して実装）。
mw_common からは取得（jkp_rows / jkp_mkt / ff_factors / french_series / yahoo）だけを使う。

使い方: python3 night/mw_postpub_verify.py  → out/mw_postpub_verify.json
"""
import sys, os, re, math, json, collections, datetime, random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得だけ）

OUT = os.path.join(M.BASE, 'out', 'mw_postpub_verify.json')
TRAIN_END, HOLD_START, RECENT_START, END = 200612, 200701, 201307, 202512
HOLD_MID = 201607          # 保有期間の前半 2007-01〜2016-06 / 後半 2016-07〜2025-12
REG_START = 199001
COST = 0.003               # 片道100%あたり（研究側の事前登録の既定）
COUNTRIES = ['gbr', 'deu', 'fra', 'can', 'aus', 'che', 'ita', 'esp', 'nld', 'swe', 'hkg', 'sgp', 'kor', 'twn', 'ind', 'chn',
             'bel', 'dnk', 'nor', 'fin', 'aut', 'nzl', 'zaf', 'mex', 'mys', 'tha', 'idn', 'phl', 'tur', 'pol', 'chl', 'grc']
DETAILS = os.path.join(M.CACHE, 'jkp_factor_details.xlsx')


# ───────────────────────── 統計（独自実装） ─────────────────────────
def mean(x):
    return math.fsum(x) / len(x)


def sd(x):
    m = mean(x)
    return math.sqrt(math.fsum((v - m) ** 2 for v in x) / (len(x) - 1))


def nw_t(x, L=12):
    n = len(x)
    m = mean(x)
    e = [v - m for v in x]
    s = math.fsum(v * v for v in e) / n
    for l in range(1, min(L, n - 1) + 1):
        s += 2 * (1 - l / (L + 1)) * math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(s / n) if s > 0 else float('nan')


def p2(t):
    return math.erfc(abs(t) / math.sqrt(2))


def geo(r):
    return math.exp(math.fsum(math.log1p(v) for v in r) * 12 / len(r)) - 1


def cmp(s, b, a=None, z=None, excl=None):
    """s・b は総リターン（小数・月次）。差の算術平均（%/年）・NW t・幾何の年率差・追従のぶれ"""
    ks = [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z) and not (excl and excl(k))]
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nw_t(d)
    return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'ex': round(mean(d) * 1200, 2), 't': round(t, 2), 'p': round(p2(t), 5),
            'cagr_diff': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2), 'te': round(sd(d) * math.sqrt(12) * 100, 2)}


def roll20(s, b):
    ks = sorted(set(s) & set(b))
    have = set(ks)
    out = []
    for y in range(ks[0] // 100, 2100):
        a, z = y * 100 + 7, (y + 20) * 100 + 6
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < 0.97 * 240:
            continue
        out.append((y, round((geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100, 2)))
    if not out:
        return None
    return {'windows': len(out), 'wins': sum(1 for _, v in out if v > 0), 'win_rate': round(sum(1 for _, v in out if v > 0) / len(out), 3),
            'worst': min(out, key=lambda x: x[1]), 'first_start': out[0][0], 'last_start': out[-1][0]}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    out = []
    for i in range(0, len(ks) - 240 + 1, 12):
        ws = wb = 0.0
        for k in ks[i:i + 240]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append((ks[i], round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1])}


def holm(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m, run, out = len(it), 0.0, {}
    for i, (v, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 4)
    return out


def bh(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m = len(it)
    out, run = {}, 1.0
    for i in range(m - 1, -1, -1):
        v, k = it[i]
        run = min(run, v * m / (i + 1))
        out[k] = round(run, 4)
    return out


def net(s, turn, unit):
    c = turn * unit / 12
    return {k: v - c for k, v in s.items()}


PRE = json.load(open(os.path.join(M.BASE, 'out', 'mw_prereg.json')))


def grade(full, train, hold, r20, cost_hold, repl, holm_p):
    """out/mw_prereg.json の C1〜C7 を独自に実装（C8 は該当なし）"""
    c = {'C1_train': bool(train and train['ex'] > 0 and train['t'] >= 2.0),
         'C2_hold_sign': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3_hold_t': bool(hold and hold['t'] >= 1.65),
         'C4_roll20': bool(r20 and r20['win_rate'] >= 0.8),
         'C5_repl': (repl[1] / repl[0] >= 2 / 3) if repl and repl[0] else None,
         'C6_net_cost': bool(cost_hold and cost_hold['ex'] > 0 and cost_hold['cagr_diff'] > 0),
         'C7_multi': bool((full and full['t'] >= 3.0) or (holm_p is not None and holm_p < 0.05))}
    base = c['C1_train'] and c['C2_hold_sign'] and c['C6_net_cost']
    if base and c['C3_hold_t'] and c['C4_roll20'] and c['C7_multi'] and c['C5_repl'] in (None, True):
        g = 'S'
    elif base and c['C4_roll20'] and c['C7_multi'] and (c['C3_hold_t'] or c['C5_repl'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── データ（独自の読み取り） ─────────────────────────
def read_details():
    import openpyxl
    if not os.path.exists(DETAILS):
        M.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Factor%20Details.xlsx',
              name='jkp_factor_details.xlsx', max_age_days=3650)
    rows = list(openpyxl.load_workbook(DETAILS, read_only=True).worksheets[0].iter_rows(values_only=True))
    h = rows[0]
    D = {}
    for r in rows[1:]:
        d = dict(zip(h, r))
        a = d.get('abr_jkp')
        if not a:
            continue
        m = re.search(r'\((\d{4})\)', d.get('cite') or '')
        tt = re.findall(r'\d+(?:\.\d+)?', str(d.get('t-stat') or ''))
        D[a] = {'pub': int(m.group(1)) if m else None, 'dir': int(d['direction']), 'group': (d.get('group') or '').strip(),
                'cite': d.get('cite'), 'tmin': min(float(x) for x in tt) if tt else None, 'name': d.get('name_new') or d.get('name')}
        D[a]['good'] = '3.0' if D[a]['dir'] == 1 else '1.0'
        D[a]['bad'] = '1.0' if D[a]['dir'] == 1 else '3.0'
    return D


# 回転率（年・片道）＝研究側の事前登録の表（仮定）を独自に書き写したもの
_TURN = [
    (6.0, lambda a: a.startswith('seas_')),
    (6.0, lambda a: a in {'ret_1_0', 'rmax1_21d', 'rmax5_21d', 'rskew_21d', 'iskew_capm_21d', 'iskew_ff3_21d', 'iskew_hxz4_21d', 'coskew_21d'}),
    (2.0, lambda a: a in {'rvol_21d', 'ivol_ff3_21d', 'ivol_capm_21d', 'ivol_hxz4_21d', 'beta_dimson_21d', 'bidaskhl_21d', 'zero_trades_21d', 'rmax5_rvol_21d'}),
    (2.5, lambda a: a == 'ret_3_1'),
    (1.5, lambda a: a in {'ret_6_1', 'ret_9_1', 'ret_12_1', 'ret_12_7', 'resff3_6_1', 'resff3_12_1', 'prc_highprc_252d'}),
    (1.5, lambda a: a in {'niq_su', 'saleq_su', 'ni_inc8q'}),
    (0.8, lambda a: a in {'niq_be', 'niq_at', 'niq_be_chg1', 'niq_at_chg1', 'saleq_gr1', 'ocfq_saleq_std'}),
    (0.6, lambda a: a in {'turnover_126d', 'turnover_var_126d', 'dolvol_126d', 'dolvol_var_126d', 'ami_126d', 'zero_trades_126d', 'zero_trades_252d', 'ivol_capm_252d', 'betadown_252d'}),
    (0.3, lambda a: a in {'ret_60_12', 'beta_60m', 'betabab_1260d', 'corr_1260d', 'market_equity', 'prc', 'age'}),
    (0.6, lambda a: a in {'qmj', 'qmj_prof', 'qmj_growth', 'qmj_safety', 'mispricing_perf', 'mispricing_mgmt', 'f_score', 'o_score', 'z_score', 'kz_index'}),
]


def turn_of(a):
    for t, f in _TURN:
        if f(a):
            return t
    return 0.4


# 規模・流動性そのものに近い特徴（小型株への傾きを直接持つ）＝除外の感度に使う（事後の分類）
SIZE_LIQ = {'market_equity', 'prc', 'dolvol_126d', 'dolvol_var_126d', 'ami_126d', 'zero_trades_21d', 'zero_trades_126d',
            'zero_trades_252d', 'turnover_126d', 'turnover_var_126d', 'bidaskhl_21d', 'age', 'rvol_21d', 'ivol_capm_21d',
            'ivol_ff3_21d', 'ivol_hxz4_21d', 'ivol_capm_252d'}


def load_pf(region):
    """{特徴: {三分位: {ym: (超過リターン, 銘柄数)}}}"""
    P = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in M.jkp_rows(region, 'all_factors', 'portfolios', 'vw'):
        if r['ret'] in ('', 'NA', 'na') or r['n'] in ('', 'NA', 'na'):
            continue
        ym = int(r['date'][:4]) * 100 + int(r['date'][5:7])
        if ym > END:
            continue
        P[r['name']][r['pf']][ym] = (float(r['ret']), float(r['n']))
    return P


def side(P, a, pf, nmin):
    return {m: v[0] for m, v in P.get(a, {}).get(pf, {}).items() if v[1] >= nmin}


def tilt(P, D, a, nmin, which='good'):
    """良い側（または悪い側）− 3つの三分位の等分平均。3つとも銘柄数 nmin 以上の月だけ"""
    t1, t2, t3 = (side(P, a, pf, nmin) for pf in ('1.0', '2.0', '3.0'))
    g = {'1.0': t1, '2.0': t2, '3.0': t3}[D[a]['good'] if which == 'good' else D[a]['bad']]
    return {m: g[m] - (t1[m] + t2[m] + t3[m]) / 3 for m in set(t1) & set(t2) & set(t3)}


def maturity(P, nmin=20, need=50):
    c = collections.Counter(m for a in P for m, v in P[a].get('3.0', {}).items() if v[1] >= nmin)
    ok = [m for m, v in c.items() if v >= need]
    return min(ok) if ok else None


def adopt_dates(D, lag=0):
    return {a: (d['pub'] + 1 + lag) * 100 + 1 for a, d in D.items() if d['pub']}


def build_Z(P, D, chars, adopt, start, nmin=20, which='good', weights=None):
    """採用済みで当月に値のある特徴の、指定の側の三分位を等分（weights があれば群の等分など）"""
    ser = {a: side(P, a, D[a][which] if which in ('good', 'bad') else which, nmin) for a in chars}
    months = sorted({m for a in chars for m in ser[a]})
    out, turn, cnt = {}, {}, {}
    begun = False
    for m in months:
        if m < start or m > END:
            continue
        act = [a for a in chars if adopt.get(a) is not None and adopt[a] <= m and m in ser[a]]
        if not begun:
            if len(act) < 3:
                continue
            begun = True
        if not act:
            continue
        if weights == 'group':
            gs = collections.defaultdict(list)
            for a in act:
                gs[D[a]['group']].append(a)
            w = {a: 1 / len(gs) / len(v) for v in gs.values() for a in v}
        else:
            w = {a: 1 / len(act) for a in act}
        out[m] = math.fsum(w[a] * ser[a][m] for a in act)
        turn[m] = math.fsum(w[a] * turn_of(a) for a in act)
        cnt[m] = len(act)
    return out, turn, cnt


def build_ZT(mkt, P, D, chars, adopt, start, nmin=20, which='good'):
    T = {a: tilt(P, D, a, nmin, which) for a in chars if a in P}
    out, cnt = {}, {}
    begun = False
    for m in sorted(k for k in mkt if start <= k <= END):
        act = [a for a in T if adopt.get(a) is not None and adopt[a] <= m and m in T[a]]
        if not begun:
            if len(act) < 3:
                continue
            begun = True
        out[m] = mkt[m] + (math.fsum(T[a][m] for a in act) / len(act) if act else 0.0)
        cnt[m] = len(act)
    return out, cnt


def tot(ex, rf):
    return {k: v + rf[k] for k, v in ex.items() if k in rf}


def mean_turn(turn, a=HOLD_START):
    v = [t for k, t in turn.items() if k >= a]
    return mean(v) if v else None


def full_eval(s_ex, b_ex, rf, th):
    s, b = tot(s_ex, rf), tot(b_ex, rf)
    ks = set(s) & set(b)
    s = {k: s[k] for k in ks}; b = {k: b[k] for k in ks}
    e = {'full': cmp(s, b), 'train': cmp(s, b, z=TRAIN_END), 'hold': cmp(s, b, a=HOLD_START), 'recent': cmp(s, b, a=RECENT_START),
         'hold_1st_half': cmp(s, b, a=HOLD_START, z=HOLD_MID - 1), 'hold_2nd_half': cmp(s, b, a=HOLD_MID),
         'full_drop_1998_2000': cmp(s, b, excl=lambda k: 199801 <= k <= 200012),
         'full_drop_1997_1999': cmp(s, b, excl=lambda k: 199701 <= k <= 199912),
         'hold_drop_2020_2021': cmp(s, b, a=HOLD_START, excl=lambda k: 202001 <= k <= 202112),
         'hold_drop_2008_2009': cmp(s, b, a=HOLD_START, excl=lambda k: 200801 <= k <= 200912),
         'turnover_hold': round(th, 3) if th is not None else None,
         'roll20': roll20(s, b), 'dca20': dca20(s, b)}
    for u in (0.003, 0.0045, 0.006, 0.01):
        e[f'net_hold_{u * 100:.2f}pct'] = cmp(net(s, th, u), b, a=HOLD_START) if th is not None else None
    e['cost_hold'] = e['net_hold_0.30pct']
    e['breakeven_cost_pct_oneway'] = round(e['hold']['ex'] / th, 2) if th and e['hold'] else None
    e['net_hold_turn1.5x_0.30pct'] = cmp(net(s, th * 1.5, 0.003), b, a=HOLD_START) if th is not None else None
    # 暦年ごとの幾何の差と、1年ずつ抜いたときの保有期間の超過（影響の大きい年）
    ys = collections.defaultdict(list)
    for k in sorted(ks):
        ys[k // 100].append(k)
    ann = {y: round((math.prod(1 + s[k] for k in v) - math.prod(1 + b[k] for k in v)) * 100, 1) for y, v in ys.items() if len(v) == 12}
    e['annual_diff'] = ann
    hy = [y for y in ann if y >= 2007]
    loo = {y: cmp(s, b, a=HOLD_START, excl=lambda k, y=y: k // 100 == y)['ex'] for y in hy}
    e['hold_leave_one_year_out_min'] = min(loo.items(), key=lambda x: x[1]) if loo else None
    top2 = sorted(hy, key=lambda y: -ann[y])[:2]
    e['hold_drop_best2_years'] = {'years': top2, 'stats': cmp(s, b, a=HOLD_START, excl=lambda k: k // 100 in top2)}
    return e, s, b


def after_tax(s, b, turn, a=HOLD_START, tax=0.20315):
    """日本の課税口座の粗い推定: 毎月 turn/12 を売って実現益（平均取得単価）に課税し、手取りを買い直す。
    最後に両方を清算して含み益に課税（市場は買って持つだけ＝最後に1回だけ課税）"""
    ks = [k for k in sorted(set(s) & set(b)) if k >= a]
    v, basis = 1.0, 1.0
    for k in ks:
        v *= 1 + s[k]
        f = turn / 12
        sell = v * f
        gain = f * (v - basis)
        tx = max(0.0, gain) * tax
        basis = basis * (1 - f) + (sell - tx)
        v -= tx
    v_end = v - max(0.0, v - basis) * tax
    w = 1.0
    for k in ks:
        w *= 1 + b[k]
    w_end = w - max(0.0, w - 1.0) * tax
    yrs = len(ks) / 12
    return {'years': round(yrs, 1), 'cagr_after_tax_strategy': round((v_end ** (1 / yrs) - 1) * 100, 2),
            'cagr_after_tax_market_buyhold': round((w_end ** (1 / yrs) - 1) * 100, 2),
            'diff': round((v_end ** (1 / yrs) - w_end ** (1 / yrs)) * 100, 2),
            'note': '損失の繰越・配当課税は入れていない粗い推定（NISA なら課税なし）'}


def slim(e):
    """JSON を軽くする（主要な数字だけ）"""
    keep = ['full', 'train', 'hold', 'recent', 'hold_1st_half', 'hold_2nd_half', 'full_drop_1998_2000', 'full_drop_1997_1999',
            'hold_drop_2020_2021', 'hold_drop_2008_2009', 'turnover_hold', 'roll20', 'dca20', 'net_hold_0.30pct', 'net_hold_0.45pct',
            'net_hold_0.60pct', 'net_hold_1.00pct', 'net_hold_turn1.5x_0.30pct', 'breakeven_cost_pct_oneway', 'hold_leave_one_year_out_min',
            'hold_drop_best2_years', 'annual_diff']
    return {k: e.get(k) for k in keep}


def short(x):
    return None if x is None else {k: x[k] for k in ('ex', 't', 'cagr_diff') if k in x}


# ───────────────────────── 本体 ─────────────────────────
def main():
    random.seed(20260928)
    D = read_details()
    known = sorted(a for a, d in D.items() if d['pub'])
    ad0, ad3 = adopt_dates(D, 0), adopt_dates(D, 3)
    ff = M.ff_factors()
    rf, mktrf = ff['rf'], ff['mktrf']
    res = {'angle': 'postpub', 'verifier': 'night/mw_postpub_verify.py', 'generated': datetime.date.today().isoformat(),
           'independent_parts': '出典表の読み取り・三分位（銘柄数つき）・採用者 Z / 市場＋傾き ZT / 特徴の良い側 C の構成・超過・NW t・幾何の差・20年窓・積立・費用・格付け（C1〜C7）',
           'shared_parts': 'mw_common の取得（jkp_rows・jkp_mkt・ff_factors・french_series・yahoo）だけ',
           'n_chars': len(D), 'n_pub_known': len(known)}
    orig = json.load(open(os.path.join(M.BASE, 'out', 'mw_postpub.json')))
    OT = {v['name']: v for v in orig['tested']}

    # ════════ 国の族（Z・ZT）: 32か国すべてを作り直す（C5 と縮小推定のため） ════════
    fam = {'Z': {}, 'ZT': {}}
    series = {}
    cinfo = {}
    for c in COUNTRIES:
        P = load_pf(c)
        mk = M.jkp_mkt(c, 'vw')
        mat = maturity(P)
        if mat is None or mat > 199912:
            cinfo[c] = {'excluded': mat}
            continue
        st = max(REG_START, mat)
        z, zt_turn, zc = build_Z(P, D, known, ad0, st)
        th = mean_turn(zt_turn)
        ztt, _ = build_ZT(mk, P, D, known, ad0, st)
        for fk, ser in (('Z', z), ('ZT', ztt)):
            e, s_tot, b_tot = full_eval(ser, mk, rf, th)
            fam[fk][c] = e
            series[(fk, c)] = (s_tot, b_tot, th)
        cinfo[c] = {'start': st, 'P': P, 'mk': mk, 'turn': th}
        print(c, st, 'Z hold', short(fam['Z'][c]['hold']), 'ZT hold', short(fam['ZT'][c]['hold']), flush=True)

    cands_country = ['Z_kor', 'ZT_kor', 'ZT_dnk', 'ZT_nor', 'Z_idn', 'ZT_zaf', 'Z_tur']
    ver = {}
    for fk in ('Z', 'ZT'):
        rows = fam[fk]
        fpos = {c: bool(v['full'] and v['full']['ex'] > 0) for c, v in rows.items()}
        hp = holm({c: v['hold']['p'] for c, v in rows.items() if v['hold']})
        for c, v in rows.items():
            others = [fpos[o] for o in rows if o != c]
            v['C5_other_countries'] = [len(others), sum(others)]
            v['holm_p_family32'] = hp.get(c)
            g, crit = grade(v['full'], v['train'], v['hold'], v['roll20'], v['cost_hold'], v['C5_other_countries'], hp.get(c))
            v['grade_reproduced'], v['criteria'] = g, crit
    # 族ごとの縮小推定（国どうしの真の差の分散 τ² を、観測のばらつき − 標本誤差の平均 で推定）
    shrink = {}
    for fk in ('Z', 'ZT'):
        xs = {c: (v['hold']['ex'], abs(v['hold']['ex'] / v['hold']['t']) if v['hold']['t'] else None) for c, v in fam[fk].items() if v['hold']}
        mu = mean([x for x, _ in xs.values()])
        var_obs = sd([x for x, _ in xs.values()]) ** 2
        se2 = mean([se ** 2 for _, se in xs.values() if se])
        tau2 = max(0.0, var_obs - se2)
        shrink[fk] = {'pooled_hold_mean': round(mu, 2), 'obs_sd': round(math.sqrt(var_obs), 2), 'mean_se': round(math.sqrt(se2), 2),
                      'tau': round(math.sqrt(tau2), 2),
                      'posterior_hold_ex': {c: round(mu + (tau2 / (tau2 + se ** 2) if tau2 + se ** 2 > 0 else 0) * (x - mu), 2) for c, (x, se) in xs.items()},
                      'note': 'τ≈0 なら国ごとの差は標本誤差で説明でき、どの国の最善の推定値も族の平均に近い（勝者の呪い）'}
        # 32か国の中の最大の保有 t が偶然で出る確率（国どうしが独立で真の効果が族の平均のときの粗い見積もり）
    res['country_shrinkage'] = shrink

    # 多重検定: 角度で試した全239本（研究側の p を使い、候補は自分の p に置き換え）
    allp = {k: (v['eval']['hold'] or {}).get('p') for k, v in OT.items()}

    # 国の候補の詳しい検査
    for name in cands_country:
        fk, c = name.split('_')
        e = fam[fk][c]
        P, mk, st, th = cinfo[c]['P'], cinfo[c]['mk'], cinfo[c]['start'], cinfo[c]['turn']
        s_tot, b_tot, _ = series[(fk, c)]
        allp[name] = e['hold']['p']
        v = {'claimed_grade': OT[name]['grade'], 'reproduced_grade': e['grade_reproduced'], 'criteria': e['criteria'],
             'stats': slim(e), 'holm_p_family32': e['holm_p_family32'], 'C5_other_countries': e['C5_other_countries']}
        # 相手を替える: 上限つき（vw_cap）と等ウェイト（ew）の国の市場（純粋な vw が正の相手・参考）
        alt = {}
        for w in ('vw_cap', 'ew'):
            try:
                bm = M.jkp_mkt(c, w)
                alt[w] = {'full': short(cmp(s_tot, tot(bm, rf))), 'hold': short(cmp(s_tot, tot(bm, rf), a=HOLD_START))}
            except Exception as ex:  # noqa
                alt[w] = f'取得失敗 {ex}'
        mkvwcap = M.jkp_mkt(c, 'vw_cap')
        mkew = M.jkp_mkt(c, 'ew')
        alt['market_vw_minus_vw_cap'] = {'full': short(cmp(tot(mk, rf), tot(mkvwcap, rf), a=st)), 'hold': short(cmp(tot(mk, rf), tot(mkvwcap, rf), a=HOLD_START))}
        alt['market_ew_minus_vw'] = {'full': short(cmp(tot(mkew, rf), tot(mk, rf), a=st)), 'hold': short(cmp(tot(mkew, rf), tot(mk, rf), a=HOLD_START))}
        v['alt_benchmarks_reference'] = alt
        # 構造の偏りの対照: 真ん中・悪い側の採用者（Z の型）と、市場＋悪い側の傾き（ZT の型）
        ctrl = {}
        for lab, which in (('mid_adopter', '2.0'), ('bad_adopter', 'bad')):
            zz, _, _ = build_Z(P, D, known, ad0, st, which=which)
            ctrl[lab] = {'full': short(cmp(tot(zz, rf), tot(mk, rf))), 'hold': short(cmp(tot(zz, rf), tot(mk, rf), a=HOLD_START))}
        zb, _ = build_ZT(mk, P, D, known, ad0, st, which='bad')
        ctrl['mkt_plus_bad_tilt'] = {'full': short(cmp(tot(zb, rf), tot(mk, rf))), 'hold': short(cmp(tot(zb, rf), tot(mk, rf), a=HOLD_START))}
        v['structural_controls'] = ctrl
        v['size_concentration_regression'] = {'hold': reg2(s_tot, tot(mk, rf), tot(mkew, rf), tot(mkvwcap, rf), HOLD_START),
                                              'full': reg2(s_tot, tot(mk, rf), tot(mkew, rf), tot(mkvwcap, rf), None)}
        # 近い設定（事前登録の外の感度）
        nb = {}

        def run(label, **kw):
            chars = kw.pop('chars', known)
            adopt = kw.pop('adopt', ad0)
            nmin = kw.pop('nmin', 20)
            if fk == 'Z':
                ser, tt, _ = build_Z(P, D, chars, adopt, st, nmin=nmin, weights=kw.pop('weights', None))
                thh = mean_turn(tt)
            else:
                ser, _ = build_ZT(mk, P, D, chars, adopt, st, nmin=nmin)
                thh = th
            s2, b2 = tot(ser, rf), tot(mk, rf)
            h = cmp(s2, b2, a=HOLD_START)
            nb[label] = {'full': short(cmp(s2, b2)), 'train': short(cmp(s2, b2, z=TRAIN_END)), 'hold': short(h),
                         'net_hold_0.30': short(cmp(net(s2, thh, 0.003), b2, a=HOLD_START)) if thh else None}
        run('nmin10', nmin=10)
        run('nmin30', nmin=30)
        run('nmin50', nmin=50)
        run('adopt_pub_plus4', adopt=ad3)
        run('only_paper_t_ge3', chars=[a for a in known if D[a]['tmin'] is not None and D[a]['tmin'] >= 3])
        run('drop_size_liquidity_chars', chars=[a for a in known if a not in SIZE_LIQ])
        run('drop_seasonal_and_21d', chars=[a for a in known if turn_of(a) < 2.0])
        if fk == 'Z':
            run('group_balanced', weights='group')
        for g in sorted({D[a]['group'] for a in known}):
            run(f'leave_out_group_{g}', chars=[a for a in known if D[a]['group'] != g])
        v['neighbors'] = nb
        v['after_tax_japan_taxable_rough'] = after_tax(s_tot, b_tot, th)
        ver[name] = v
        print(name, 'reproduced', e['grade_reproduced'], short(e['full']), short(e['train']), short(e['hold']), flush=True)

    # ════════ 特徴ごと（census）: 米国の良い側の三分位 対 French Mkt ════════
    PU = load_pf('usa')
    mkt_tot = tot(mktrf, rf)
    cen = {}
    for a in D:
        g = side(PU, a, D[a]['good'], 20)
        if not g:
            continue
        s = tot(g, rf)
        ks = set(s) & set(mkt_tot)
        s = {k: s[k] for k in ks}
        cen[a] = s
    cen_hold_p = {a: cmp(s, mkt_tot, a=HOLD_START)['p'] for a, s in cen.items()}
    holm153 = holm(cen_hold_p)
    clean = [a for a in cen if D[a]['pub'] and D[a]['pub'] <= 2006]
    holm83 = holm({a: cen_hold_p[a] for a in clean})
    # 公表2006以前の83本の保有期間の分布（研究側の数字の再計算）
    hs = {a: cmp(cen[a], mkt_tot, a=HOLD_START) for a in clean}
    tr = {a: cmp(cen[a], mkt_tot, z=TRAIN_END) for a in clean}
    n165 = sum(1 for a in clean if hs[a]['t'] >= 1.65)
    # 帰無（各特徴の真の超過=0）で 83本中 k本以上が t≥1.65 になる二項の確率（独立を仮定・楽観側）
    pbin = sum(math.comb(len(clean), k) * 0.05 ** k * 0.95 ** (len(clean) - k) for k in range(n165, len(clean) + 1))
    res['census_clean_recount'] = {'n': len(clean), 'hold_mean': round(mean([hs[a]['ex'] for a in clean]), 2),
                                   'hold_t_ge_1_65': n165, 'expected_if_null': round(0.05 * len(clean), 1),
                                   'binomial_p_at_least_that_many': round(pbin, 3),
                                   'hold_t_le_-1_65': sum(1 for a in clean if hs[a]['t'] <= -1.65),
                                   'corr_train_t_hold_ex': round(M.corr([tr[a]['t'] for a in clean], [hs[a]['ex'] for a in clean]), 3),
                                   'top_by_hold_t': sorted(((a, hs[a]['ex'], hs[a]['t']) for a in clean), key=lambda x: -x[2])[:8]}
    ind12 = M.french_series('12_Industry_Portfolios', 'Value Weight')
    for name, a in (('C_netis_at', 'netis_at'), ('C_rd_me', 'rd_me'), ('C_gp_at', 'gp_at'), ('C_ope_bel1', 'ope_bel1')):
        s = cen[a]
        th = turn_of(a)
        e, s_tot, b_tot = full_eval({k: v - rf[k] for k, v in s.items()}, mktrf, rf, th)
        allp[name] = e['hold']['p']
        g, crit = grade(e['full'], e['train'], e['hold'], e['roll20'], e['cost_hold'], None, holm153.get(a))
        # 地域での再現（研究側と同じ4地域・良い側 対 地域の vw 市場・1990〜）＝C5
        rep = {}
        for reg in ('world_ex_us', 'developed', 'jpn', 'emerging'):
            PR = load_pf(reg) if reg not in _REGCACHE else _REGCACHE[reg]
            _REGCACHE[reg] = PR
            rg = side(PR, a, D[a]['good'], 20)
            bm = M.jkp_mkt(reg, 'vw')
            x = cmp(tot(rg, rf), tot(bm, rf), a=REG_START) if rg else None
            tl = tilt(PR, D, a, 20)
            xt = [tl[k] for k in sorted(tl) if k >= REG_START]
            rep[reg] = {'good_vs_mkt': short(x), 'tilt_vs_avg3': [round(mean(xt) * 1200, 2), round(nw_t(xt), 2)] if len(xt) >= 24 else None}
        npos = sum(1 for r in rep.values() if r['good_vs_mkt'] and r['good_vs_mkt']['ex'] > 0)
        g, crit = grade(e['full'], e['train'], e['hold'], e['roll20'], e['cost_hold'], (4, npos), holm153.get(a))
        v = {'claimed_grade': OT[name]['grade'], 'reproduced_grade': g, 'criteria': crit, 'stats': slim(e), 'pub': D[a]['pub'],
             'clean_holdout': bool(D[a]['pub'] and D[a]['pub'] <= 2006), 'holm_p_153': holm153.get(a), 'holm_p_83clean': holm83.get(a),
             'regions': rep}
        if D[a]['pub']:
            v['post_publication'] = short(cmp(s_tot, b_tot, a=(D[a]['pub'] + 1) * 100 + 1))
            v['post_publication_months'] = cmp(s_tot, b_tot, a=(D[a]['pub'] + 1) * 100 + 1)['months']
        # 三分位ぜんぶ 対 市場（保有期間）と、良い側 − 3つの平均（特徴を持つ会社の中での傾き）
        terc = {}
        for pf in ('1.0', '2.0', '3.0'):
            x = tot(side(PU, a, pf, 20), rf)
            terc[pf] = {'hold': short(cmp(x, mkt_tot, a=HOLD_START)), 'full': short(cmp(x, mkt_tot))}
        tl = tilt(PU, D, a, 20)
        tlh = [tl[k] for k in sorted(tl) if k >= HOLD_START]
        tlf = [tl[k] for k in sorted(tl)]
        v['terciles_vs_mkt'] = terc
        v['tilt_good_minus_avg3'] = {'hold': [round(mean(tlh) * 1200, 2), round(nw_t(tlh), 2)], 'full': [round(mean(tlf) * 1200, 2), round(nw_t(tlf), 2)]}
        v['tercile_n_stocks'] = {y: PU[a][D[a]['good']].get(y * 100 + 6, (None, None))[1] for y in (1975, 1990, 2000, 2007, 2015, 2025)}
        # 業種の回帰（保有期間）: (良い側 − 市場) を 12業種の (業種 − 市場) に回帰したときの切片
        v['industry_regression_hold'] = ind_reg(s_tot, mkt_tot, ind12, HOLD_START)
        v['industry_regression_full'] = ind_reg(s_tot, mkt_tot, ind12, None)
        v['after_tax_japan_taxable_rough'] = after_tax(s_tot, b_tot, th)
        cen_detail = {}
        neigh = {'netis_at': ['eqnetis_at', 'dbnetis_at', 'chcsho_12m', 'eqnpo_12m', 'eqnpo_me', 'eqpo_me'],
                 'rd_me': ['rd_sale', 'rd5_at', 'opex_at'], 'gp_at': ['gp_atl1', 'ope_be', 'ope_bel1', 'cop_at', 'op_at'],
                 'ope_bel1': ['ope_be', 'gp_at', 'op_at', 'cop_at']}.get(a, [])
        for nb_ in neigh:
            if nb_ in cen:
                cen_detail[nb_] = {'pub': D[nb_]['pub'], 'hold': short(cmp(cen[nb_], mkt_tot, a=HOLD_START)), 'full': short(cmp(cen[nb_], mkt_tot)),
                                   'hold_1st_half': short(cmp(cen[nb_], mkt_tot, a=HOLD_START, z=HOLD_MID - 1)),
                                   'hold_2nd_half': short(cmp(cen[nb_], mkt_tot, a=HOLD_MID))}
        v['neighbor_characteristics'] = cen_detail
        ver[name] = v
        print(name, 'reproduced', g, short(e['full']), short(e['train']), short(e['hold']), flush=True)

    # 実在の手段での確かめ: 自社株買いの ETF（PKW・2006-12 設定）対 SPY（Yahoo・生き残りの偏りあり・配当込み）
    try:
        pkw, spy = M.yahoo('PKW'), M.yahoo('SPY')
        ver['C_netis_at']['real_etf_check_PKW_vs_SPY'] = {'hold_to_2025': short(cmp(pkw, spy, a=200701, z=202512)),
                                                           'to_latest': short(cmp(pkw, spy, a=200701)),
                                                           'vs_french_mkt': short(cmp(pkw, mkt_tot, a=200701)),
                                                           'note': 'PKW＝過去12か月で株数を5%以上減らした米国株（Invesco BuyBack Achievers・経費0.6%前後）。紙の三分位（低い純発行）の実在の写し。Yahoo の調整後終値'}
    except Exception as ex:  # noqa
        ver['C_netis_at']['real_etf_check_PKW_vs_SPY'] = f'取得失敗 {ex}'

    # 多重検定（角度で試した全本数）
    hall = holm(allp)
    ball = bh(allp)
    res['multiple_testing_all_tested'] = {'n': sum(1 for x in allp.values() if x is not None),
                                          'holm': {k: hall.get(k) for k in ver}, 'bh_fdr': {k: ball.get(k) for k in ver}}
    hc64 = holm({f'{fk}_{c}': fam[fk][c]['hold']['p'] for fk in fam for c in fam[fk] if fam[fk][c]['hold']})
    hf64 = holm({f'{fk}_{c}': fam[fk][c]['full']['p'] for fk in fam for c in fam[fk] if fam[fk][c]['full']})
    hf64d = holm({f'{fk}_{c}': fam[fk][c]['full_drop_1998_2000']['p'] for fk in fam for c in fam[fk] if fam[fk][c]['full_drop_1998_2000']})
    res['multiple_testing_country_64'] = {k: {'holm_hold_p': hc64.get(k), 'holm_full_p': hf64.get(k), 'holm_full_p_drop_1998_2000': hf64d.get(k)} for k in cands_country}
    res['multiple_testing_country_64_note'] = ('国の族は 32か国×2版＝64本を試した。国の全期間は米国の論文の標本の外なので、全期間の p を 64本で Holm 補正するのが'
                                              '選択（勝った国を選ぶこと）に対する公正な C7 の代わり。C7 の「全期間 t≥3」は1本の検定の線で、64本の中の最良を選ぶことを補正しない')
    # 研究プログラム全体（mw_*.json の tested の合計）での Bonferroni（参考）
    import glob
    ntot = 0
    for f in glob.glob(os.path.join(M.BASE, 'out', 'mw_*.json')):
        b_ = os.path.basename(f)
        if 'prereg' in b_ or 'verify' in b_:
            continue
        try:
            dd = json.load(open(f))
            ntot += len(dd['tested']) if isinstance(dd.get('tested'), list) else int(dd.get('n_tested') or 0)
        except Exception:  # noqa
            pass
    res['program_wide'] = {'n_tested_all_mw_angles': ntot,
                           'bonferroni_hold_p': {k: round(min(1.0, (allp.get(k) or 1) * ntot), 4) for k in ver},
                           'bonferroni_full_p_countries': {k: round(min(1.0, fam[k.split('_')[0]][k.split('_')[1]]['full']['p'] * ntot), 4) for k in cands_country}}

    res['country_family_reproduced'] = {fk: {c: {'grade': v['grade_reproduced'], 'full': short(v['full']), 'train': short(v['train']),
                                                 'hold': short(v['hold']), 'net_0.30': short(v['net_hold_0.30pct']),
                                                 'net_0.60': short(v['net_hold_0.60pct']), 'turn': v['turnover_hold']}
                                             for c, v in fam[fk].items()} for fk in fam}
    for fk in fam:
        hs_ = [v['hold']['ex'] for v in fam[fk].values() if v['hold']]
        n6 = [v['net_hold_0.60pct']['ex'] for v in fam[fk].values() if v['net_hold_0.60pct']]
        n10 = [v['net_hold_1.00pct']['ex'] for v in fam[fk].values() if v['net_hold_1.00pct']]
        res['country_family_reproduced'][f'summary_{fk}'] = {'n': len(hs_), 'hold_mean': round(mean(hs_), 2), 'hold_pos': sum(1 for x in hs_ if x > 0),
                                                             'net0.60_mean': round(mean(n6), 2), 'net0.60_pos': sum(1 for x in n6 if x > 0),
                                                             'net1.00_mean': round(mean(n10), 2), 'net1.00_pos': sum(1 for x in n10 if x > 0),
                                                             'grades': dict(collections.Counter(v['grade_reproduced'] for v in fam[fk].values()))}
    res['candidates'] = ver
    res['verdicts'] = VERDICTS
    res['general_findings'] = GENERAL
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    print('wrote', OUT)


_REGCACHE = {}

# ───────────────────────── 判定（この検証の数字を読んで書いた・静的な文） ─────────────────────────
GENERAL = [
    '全8候補と上位B 2本の数字は、独立のコードで小数2桁まで一致した（出典表・三分位・構成・統計・格付けを別に実装）。計算の誤りは見つからなかった',
    '相手は純粋な時価加重（米国は French Mkt、国は JKP の国の vw 市場）で正しい。上限つき・等ウェイトの相手は使っていない（参考として別に並べた）',
    '国の族: 32か国の保有期間の超過のばらつきは、ほぼ標本誤差で説明できる（ZT で国どうしの真の差 τ≈0.15%/年、Z で≈0.26）。各国の最善の推定値は族の平均（ZT +0.71・Z +0.95）に縮む＝S の国は「32か国の中で運よく訓練期間も強かった国」の色が濃い。保有期間で最も強い国（台湾 t4.33・豪州 t3.87・インド t3.54）は訓練期間（C1）で落ちて C になっている',
    '国の族を試した本数は 64本（32か国×2版）。全期間の p を 64本で Holm 補正すると、残るのは Z_kor・ZT_kor・ZT_dnk だけ（ZT_nor 0.073・Z_idn 0.059・ZT_zaf 0.136）',
    '費用: 片道0.30%は韓国（売却時の取引税）・南ア（購入時の証券取引税0.25%）・インドネシアの小型株には甘い。族の平均は 0.60% で ZT +0.04（正17/32）・1.00% で −0.42（正3/32）',
    '特徴ごと（census）: 公表2006以前の83本のうち保有期間 t≥1.65 は 6本で、帰無（真の超過0）の期待 4.2本と区別できない（二項 p 0.235）。訓練の t は保有期間を当てない（相関0.08）。C7 の「全期間 t≥3」は論文自身の発見の標本を含み、83本から保有期間で選んだことを補正しない',
    '研究プログラム全体（mw の全角度で試した 2,757本）で Bonferroni をかけると、保有期間の p で残る候補は無い（Z_kor でも 0.165）。全期間の p なら Z_kor だけが残る',
]

VERDICTS = {
    'Z_kor': {'verdict': 'confirmed', 'verified_grade': 'S', 'reasons': [
        '再現: 全期間 +2.57%/年 t4.74・訓練 +4.29 t4.00・保有 +1.44 t4.02・CAGR差 +1.69・費用後 +1.09・20年窓 12/12・積立 12/12（中央1.349）',
        '頑丈: 保有の前半 +1.58 t3.80／後半 +1.29 t2.29、2020-21を抜いて +1.58、最良の2年（2024・2016）を抜いて +1.10 t3.25、近い設定15本（銘柄数の下限10/30/50・公表+4年から・論文t≥3だけ・規模/流動性の特徴を除く・短期の特徴を除く・群の等分・群を1つずつ抜く）すべてで訓練 t≥2.46・保有 t≥2.74',
        '小型寄り・巨大株の抑えでは説明できない: (戦略−vw) を (ew−vw)・(vw_cap−vw) に回帰した保有期間の切片 +1.32 t3.43。多重検定も Holm(64本・保有) 0.0038・Holm(角度の239本) 0.014 で残る',
        '注意: 全期間の超過の半分近くは三分位を等分に持つ構造（真ん中の三分位の採用者 全期間 +1.47・保有 +0.67 t1.40）。韓国の等ウェイト市場には保有期間で −0.72。損益分岐の費用は片道1.23%（0.60%で +0.74 t2.06、1.00%で +0.27）。32か国の縮小推定では +1.12。20年窓12本は大きく重なる（独立は2本弱）。事前登録4は新興国の集計（韓国を含む・保有 +1.23 t5.25）を見た後。数百の韓国株を持つ形で、写す投信・ETFは無い。プログラム全体2,757本の Bonferroni は保有の p では 0.165（全期間なら残る）'],
        'key_numbers': 'full +2.57 t4.74 / train +4.29 t4.00 / hold +1.44 t4.02 / CAGR +1.69 / net0.30 +1.09 / net0.60 +0.74 t2.06 / roll20 12/12 / alpha(size,cap) +1.32 t3.43 / Holm64 0.0038'},
    'ZT_kor': {'verdict': 'downgraded to A', 'verified_grade': 'A', 'reasons': [
        '再現: 全期間 +1.28 t3.98・訓練 +1.56 t2.75・保有 +1.10 t2.90・CAGR差 +1.36・費用後 +0.75',
        '保有期間は頑丈（近い設定すべてで保有 t≥2.19、規模・巨大株を除いた切片 +0.76 t2.15、全期間 Holm(64) 0.0044）',
        'S（頑丈）には届かない: 訓練期間の合格が近い設定で崩れる（公表+4年から t0.39・銘柄数50以上 t0.69・収益性の群を抜く t0.90・割安の群を抜く t1.03）。保有の前半は +0.76 t1.76。保有の Holm は 64本で 0.19・239本で 0.83',
        '韓国の現実の費用（売却時の取引税0.15〜0.3%＋手数料）で片道0.45%なら +0.57 t1.51、0.60%なら +0.40 t1.05（損益分岐0.94%）。ZT は市場＋ロング・ショートの傾きで、買いだけで作れるかは確かめていない。縮小推定 +0.77'],
        'key_numbers': 'full +1.28 t3.98 / train +1.56 t2.75 / hold +1.10 t2.90 / net0.30 +0.75 / net0.60 +0.40 t1.05 / train t under P+4 0.39'},
    'ZT_dnk': {'verdict': 'downgraded to A', 'verified_grade': 'A', 'reasons': [
        '再現: 全期間 +1.98 t3.95・訓練 +2.02 t2.51・保有 +1.95 t3.04・CAGR差 +2.25・費用後 +1.60',
        '保有期間は頑丈（前半 +1.94・後半 +1.96、最良の2年を抜いて +1.51 t2.45、規模・巨大株を除いた切片 +2.18 t4.39、損益分岐1.69%、全期間 Holm(64) 0.005）',
        'S には届かない: 訓練の合格が近い設定で崩れる（銘柄数30以上 t0.92・論文t≥3だけ t1.00・公表+4年から t1.84）。実際に買える買いだけの版 Z_dnk は C（保有 +2.12 t1.62・訓練 t1.78）＝S は検証していない重ね（ロング・ショート）の版に乗っている。デンマークは少数の巨大株（ノボ等）が各三分位の時価の大半を占め、傾きを重ねると中型株の重みが負になりうる',
        '保有の Holm は 64本で 0.126・239本で 0.53、プログラム全体の全期間 Bonferroni 0.22。縮小推定 +0.78。暦年では 2015〜2020 がほぼ負で、勝ちは 2010-13 と 2021-25 に集まる'],
        'key_numbers': 'full +1.98 t3.95 / train +2.02 t2.51 / hold +1.95 t3.04 / net0.30 +1.60 / long-only Z_dnk hold t1.62 (C) / shrunk +0.78'},
    'ZT_nor': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reasons': [
        '再現: 全期間 +1.39 t3.21・訓練 +2.37 t3.15・保有 +0.84 t1.78・費用後 +0.52',
        'C7 が崩れる: 1997-99 を抜くと全期間 t2.77、全期間 Holm(64) 0.073・保有 Holm(32) 0.83',
        'C3 が崩れやすい: 最良の2年（2022・2021）を抜くと +0.30 t0.76、保有の後半 t1.24、銘柄数30以上で保有 t1.44・訓練 t0.51',
        '費用 0.45% で +0.36 t0.76・0.60% で +0.20。日本の課税口座の粗い推定では −0.14。買いだけの版 Z_nor は B'],
        'key_numbers': 'hold +0.84 t1.78 / drop 2021-22 +0.30 t0.76 / full t drop 1997-99 2.77 / net0.60 +0.20'},
    'Z_idn': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reasons': [
        '再現: 全期間 +1.91 t3.28・訓練 +3.20 t2.92・保有 +1.19 t1.95・費用後 +0.84',
        'C7 が崩れる: 1998-2000 を抜くと全期間 t2.37、全期間 Holm(64) 0.059・保有 Holm(32) 0.96',
        '訓練の勝ちは三分位を等分に持つ構造の分: 偏りを除いた ZT_idn の訓練は −0.56（C）。保有期間の切片は規模・巨大株を除くと +0.82 t1.41（上限つき市場への感応 0.49）',
        '保有の後半 +0.73 t0.68・直近（2013-07〜）+0.62 t0.74、最良の2年を抜いて +0.63 t1.05。費用 0.60% で +0.49 t0.80（インドネシア小型株の現実の費用はもっと高い）'],
        'key_numbers': 'hold +1.19 t1.95 / 2nd half +0.73 t0.68 / full t drop 1998-2000 2.37 / ZT_idn train -0.56'},
    'ZT_zaf': {'verdict': 'downgraded to C', 'verified_grade': 'C', 'reasons': [
        '再現: 全期間 +1.18 t3.02・訓練 +2.29 t3.96・保有 +0.44 t1.01・費用後 +0.10 t0.23',
        '損益分岐の費用は片道0.38%。南アは購入時の証券取引税だけで0.25%（片道平均で約0.13%）に売買の幅が乗るので、現実の費用で C6 が落ちる（0.45% で −0.07、0.60% で −0.24）',
        'C7 も崩れる: 1998-2000 を抜くと全期間 t2.66、全期間 Holm(64) 0.136。最良の2年を抜くと +0.06。日本の課税口座の粗い推定で −0.71'],
        'key_numbers': 'hold +0.44 t1.01 / net0.30 +0.10 / breakeven 0.38% / net0.45 -0.07'},
    'C_netis_at': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reasons': [
        '再現: 全期間 +1.86 t3.85・訓練 +2.10 t3.31・保有 +1.41 t2.00・CAGR差 +1.48・費用後 +1.29・20年窓 35/35',
        '保有期間の勝ちは後半だけ: 前半（2007-01〜2016-06）−0.01・後半 +2.82。2020-21 を抜くと t1.47（C3 落ち）、2023-24 を抜くと +0.66 t0.99',
        '同じ族の近い特徴は保有期間で負けか0: 負債の純発行 −0.80・株数の変化 +0.31・純還元(12か月) −0.53・純還元/時価 +0.48・還元/時価 +0.14（株式の純発行だけ +1.17 t1.84）。実在の自社株買い ETF（PKW・2007〜2025）は SPY に +0.12・CAGR −0.20',
        '多重検定: 83本の中で Holm 1.0。83本中 t≥1.65 は6本で偶然の期待4.2本と区別できない（二項 p 0.235）。C7 は全期間 t（論文の発見の標本 1971-2000 を含む）でだけ合格し、83本から保有期間で選んだことを補正しない。日本では +0.43 t0.44'],
        'key_numbers': 'hold +1.41 t2.00 / 1st half -0.01 / 2nd half +2.82 / drop 2020-21 t1.47 / PKW vs SPY +0.12 / Holm83 1.0'},
    'C_rd_me': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reasons': [
        '再現: 全期間 +2.87 t3.13・訓練 +2.73 t2.29・保有 +3.24 t2.91・CAGR差 +3.29・費用後 +3.12・20年窓 46/49',
        '保有期間の超過の約3/4は業種: 12業種の回帰で切片 +0.78 t0.62（事業機器 β0.40・ヘルスケア β0.32）。研究開発をする会社の真ん中の三分位も +2.66 t2.23 で、会社の中での傾き（良い側−3つの平均）は +1.69 t1.74',
        '2年に依存: 2009（+23.4）と 2023（+20.2）を抜くと +1.61 t1.58（C3 落ち）',
        'C7 が崩れる: 1998-2000 を抜くと全期間 t2.85、Holm は153本で 0.55・83本で 0.30。83本から保有期間で選んだ中の1本（偶然の期待と区別できない数）',
        '支持する点: 米国外4地域すべてで正（world_ex_us +3.22 t3.04・日本 +4.20 t3.64、会社の中の傾きでも ex-US +2.03 t2.79）、公表後（2002〜）+3.11 t2.37、費用に強い（損益分岐8%）。census の中では最も筋が良いが、米国の保有期間の勝ちは主にテックの時代の業種の賭け'],
        'key_numbers': 'hold +3.24 t2.91 / industry alpha +0.78 t0.62 / drop 2009+2023 +1.61 t1.58 / full t drop 1998-2000 2.85 / Holm83 0.30'},
    'C_gp_at': {'verdict': 'confirmed', 'verified_grade': 'B', 'reasons': [
        '再現: 全期間 +1.74 t2.85・訓練 +1.51 t2.04・保有 +2.41 t2.40・費用後 +2.29（B）',
        '公表2013・論文の標本は2010まで＝保有期間の大半が論文の標本と重なり、勝ちには数えられない。公表後（2014〜）でも +2.52 t2.16、業種を除いた保有の切片 +0.73 t1.94。C7 は全期間 t2.85 で落ちる'],
        'key_numbers': 'hold +2.41 t2.40 / post-pub +2.52 t2.16 / full t 2.85'},
    'C_ope_bel1': {'verdict': 'confirmed', 'verified_grade': 'B', 'reasons': [
        '再現: 全期間 +1.40 t2.99・訓練 +1.23 t2.18・保有 +1.88 t2.33・費用後 +1.76（B）',
        '出典が無く公表年が分からない（JKP の変種）＝保有期間を標本の外と言えない。全期間 t2.99 で C7 に僅かに届かない。保有の前半 t1.21・後半 t2.59'],
        'key_numbers': 'hold +1.88 t2.33 / full t 2.99'},
    'Z_tur': {'verdict': 'confirmed', 'verified_grade': 'B', 'reasons': [
        '（参考・国の族で最良の B）再現: 全期間 +2.31 t2.84・保有 +1.52 t2.07・費用後 +1.17',
        '保有期間の勝ちはほぼ集中度の違い: 規模・巨大株を除いた切片 +0.35 t0.55（上限つき市場への感応 0.85）。偏りを除いた ZT_tur は C'],
        'key_numbers': 'hold +1.52 t2.07 / alpha(size,cap) +0.35 t0.55'},
}


def reg2(s, m, ew, cap, a):
    """(s − vw) = α + β1 (ew − vw) + β2 (vw_cap − vw)。小型寄り（等ウェイト）と巨大株の抑え（上限つき）で説明できる分を除いた切片"""
    import numpy as np  # noqa
    ks = [k for k in sorted(set(s) & set(m) & set(ew) & set(cap)) if a is None or k >= a]
    y = np.array([s[k] - m[k] for k in ks])
    X = np.array([[1.0, ew[k] - m[k], cap[k] - m[k]] for k in ks])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ b
    cov = (r @ r) / (len(y) - 3) * np.linalg.inv(X.T @ X)
    return {'alpha_ann': round(float(b[0]) * 1200, 2), 't_ols': round(float(b[0] / math.sqrt(cov[0, 0])), 2),
            'beta_ew_minus_vw': round(float(b[1]), 3), 'beta_cap_minus_vw': round(float(b[2]), 3),
            'r2': round(float(1 - (r @ r) / ((y - y.mean()) @ (y - y.mean()))), 3), 'months': len(ks)}


def ind_reg(s, m, ind, a):
    """(s − m) = α + Σ β_j (業種_j − m) の最小二乗（12業種のうち 他 を除く11本）。α は %/年、t は素朴な OLS"""
    cols = [c for c in ind if c.strip().lower() != 'other']
    ks = [k for k in sorted(set(s) & set(m)) if (a is None or k >= a) and all(k in ind[c] for c in cols)]
    y = [s[k] - m[k] for k in ks]
    X = [[1.0] + [ind[c][k] - m[k] for c in cols] for k in ks]
    import numpy as np  # noqa
    Xa, ya = np.array(X), np.array(y)
    beta, *_ = np.linalg.lstsq(Xa, ya, rcond=None)
    r = ya - Xa @ beta
    s2 = (r @ r) / (len(ya) - Xa.shape[1])
    cov = s2 * np.linalg.inv(Xa.T @ Xa)
    big = sorted(((c, round(float(b), 2)) for c, b in zip(cols, beta[1:])), key=lambda x: -abs(x[1]))[:4]
    return {'alpha_ann': round(float(beta[0]) * 1200, 2), 't_ols': round(float(beta[0] / math.sqrt(cov[0, 0])), 2),
            'raw_ex_ann': round(mean(y) * 1200, 2), 'largest_betas': big, 'months': len(ks)}


if __name__ == '__main__':
    main()
