#!/usr/bin/env python3
"""night/nx_osap_zoo.py — 角度 nx_osap_zoo（OSAP の残りの予言変数の全数調査・大型株だけの FF93 型 BH）を事前登録どおりに測る
（読むだけ・門の判定には不使用）

問い: Chen & Zimmermann の Open Source Asset Pricing（2025.10 版・CRSP/Compustat・上場廃止込み）の予言変数のうち、
      JKP 153・q07leu・兄弟 nx_osap_intang/nx_osap_info・他セッションが試していない連続の変数 29 本について、
      論文の向きの良い側を『大型株だけ』で持つ——NYSE の時価の中央値より大きく、変数が NYSE の70%点を超える会社を
      毎年6月に選び、7月〜翌6月まで時価加重で持つ（OSAP の FF93style の BH）——と、French Mkt（上限なしの時価加重）に
      訓練期間（〜2006-12）でも保有期間（2007-01〜2024-12）でも費用後に勝つか。
事前登録: out/nx_osap_zoo_prereg.json（commit 7b4701b0・測る前）。線は out/nx_prereg.json（C1〜C8・S/A/B/C と短い標本の線）。
データ: night/nx_osap_zoo_data.py の出力 out/_nx_cache/nx_osap_zoo_ports.json（extract/rules/class の3つの sha を最初に確かめる）。
出力: out/nx_osap_zoo.json（tested に主 Z 29本・探索 ZC 3本を1本残らず＝負けも残す・報告 R1〜R11・事後の診断は post_hoc）

約束（事前登録どおり）
- s = BH の月次の総リターン（OSAP の % を /100）、b = French Mkt（Mkt-RF + RF・総リターン）。比べるのは 2024-12 まで
- 評価は良い側の銘柄数 Nlong が初めて20以上になった月から。その後に20未満の月は落とす（0で埋めない）
- s_net = s − 回転×0.30%/12（毎月）。BH の回転は上限の 1.0（年 0.30%）。合成 ZC は脚の回転の平均 1.0 ＋ 0.10 ＝ 1.1（年 0.33%）
- C1・C2・C3・C7 は費用前、C4（転がる20年窓・毎年7月起点・一括）と C6 は費用後。C5・C8 は N/A
- C4 の勝ちは丸める前の差 > 0 で数える（兄弟 nx_osap_intang の rolling_x を import）
- Holm: Z の29本で1つ（長い歴史の28本＝保有期間の費用前の NW t の両側 p・DelDRC＝全期間の費用前の NW t の片側 p）。ZC は3本で別に
- DelDRC は短い標本の線（grade_short）。drop_top は【代用】最大の暦年を抜く・lower_bound は【代用】費用3倍（0.90%/年）
- R_dup（重複の報告）は格付けの文字を付けない。C1〜C6 の真偽と excess_stats だけ
- 結果を見た後の分析は post_hoc に置き『事後』と明記し、格付けには使わない
"""
import sys, os, json, math, statistics as _stat, hashlib, subprocess, datetime, csv, io, zipfile
from statistics import NormalDist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_osap_zoo_data as Z  # noqa: E402  CLASS・RULES・REPORT・定数・eval_window・rules_sha・class_sha（写さない）
import nx_osap_intang as I  # noqa: E402  rolling_x・dca_x・size_halves・ols_nw・filt を import（写さない）。import 時に nx_common の statistics を速さだけの薄い包みに差し替える（数値は同じ）

S = _stat
BASE = N.BASE
PREREG_PATH = os.path.join(BASE, 'out', 'nx_osap_zoo_prereg.json')
PR = json.load(open(PREREG_PATH))
OUTNAME = 'nx_osap_zoo.json'
PORTS_PATH = os.path.join(N.CACHE, 'nx_osap_zoo_ports.json')
TE, HS, RS = N.TRAIN_END, N.HOLD_START, N.RECENT_START
LAST = Z.LAST          # 202412
NMIN = Z.NMIN          # 20
UNIT = Z.COST_PER_UNIT  # 0.003
HOLD_H1 = (200701, 201512)
HOLD_H2 = (201601, 202412)
ZFAM, ZCFAM = 'Z', 'ZC'


# ───────────────────────── 小道具 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def r2(x, n=2):
    return None if x is None else round(x, n)


def sub(d, a=None, z=None):
    return {k: v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)}


# ───────────────────────── データ ─────────────────────────
X = json.load(open(PORTS_PATH))
SIG = X['signals']
DOC = X['signaldoc']
FF = N.ff_factors()
MKT_ALL, RF_ALL, MKTRF_ALL = FF['mkt'], FF['rf'], FF['mktrf']
MKT = N.window(MKT_ALL, z=LAST)
RF = N.window(RF_ALL, z=LAST)
RULES = {r['id']: r for r in Z.RULES}
REPORT = {r['id']: r for r in Z.REPORT}
ZP = PR['families']['Z_primary']['rules']
ZCP = PR['families']['ZC_exploratory']['rules']


def pre_sha(key):
    return PR['tools'][key][:64]


def check_sha():
    ext = Z._sha(SIG)
    rs, cs = Z.rules_sha(), Z.class_sha()
    ok = {'extract_sha256_file': X['extract_sha256'], 'extract_sha256_recomputed': ext, 'extract_sha256_prereg': pre_sha('extract_sha256'),
          'rules_sha256_file': X['rules_sha256'], 'rules_sha256_recomputed': rs, 'rules_sha256_prereg': pre_sha('rules_sha256'),
          'class_sha256_file': X['class_sha256'], 'class_sha256_recomputed': cs, 'class_sha256_prereg': pre_sha('class_sha256')}
    good = (X['extract_sha256'] == ext == pre_sha('extract_sha256')) and (X['rules_sha256'] == rs == pre_sha('rules_sha256')) \
        and (X['class_sha256'] == cs == pre_sha('class_sha256'))
    ok['ok'] = good
    if not good:
        print(json.dumps(ok, indent=1))
        raise SystemExit('sha が事前登録と一致しない。止まる')
    # 原本の sha（ports の記録・今のキャッシュ）と事前登録の data.files の照合
    src = {}
    for k, v in PR['data']['files'].items():
        want = v.get('sha256')
        rec = X['sources'].get(k, {}).get('sha256') if k in X['sources'] else None
        cache = v.get('cache')
        now = sha256_file(os.path.join(N.CACHE, cache)) if cache and os.path.exists(os.path.join(N.CACHE, cache)) else None
        src[k] = {'prereg': want, 'ports_record': rec, 'cache_now': now,
                  'match': (want is None) or ((rec in (None, want)) and (now in (None, want)))}
    ok['sources'] = src
    ok['sources_all_match'] = all(v['match'] for v in src.values())
    if not ok['sources_all_match']:
        print(json.dumps(src, indent=1))
        raise SystemExit('原本の sha が事前登録と違う（事前登録の sha_rule: 両方の版で測る必要がある）。止まる')
    return ok


def rule_end(sig, file, rows):
    """データの道具と同じ終わりの規則（再計算して shape と照合する）"""
    last_ret = max(m for m, r, n in rows if r is not None)
    end = min(last_ret, LAST)
    rend = None
    if file == 'FF93style':
        q = SIG.get(sig, {}).get('QuintilesVW', {}).get('05', [])
        ys = [m // 100 for m, r, n in q if r is not None and m % 100 == 7]
        if ys:
            rend = (max(ys) + 1) * 100 + 6
            end = min(end, rend)
    return end, rend


def series(sig, file, port):
    """評価の窓（Z.eval_window そのもの）の中で Nlong≥20 の月だけ → ({ym: r}, 形)"""
    rows = SIG[sig][file][port]
    end, rend = rule_end(sig, file, rows)
    st, good, drop, gaps = Z.eval_window(rows, end)
    s = {m: r for m, r, n in good}
    tr = [m for m in s if m <= TE]
    ho = [m for m in s if m >= HS]
    nl = [n for m, r, n in good]
    shape = {'eval_from': st, 'eval_to': good[-1][0] if good else None, 'months': len(good), 'train_months': len(tr),
             'train_years': round(len(tr) / 12, 1), 'hold_months': len(ho), 'dropped_after_start_nlong_lt20': drop, 'gaps': gaps,
             'nlong_median': S.median(nl) if nl else None, 'nlong_min': min(nl) if nl else None,
             'nlong_median_hold': S.median([n for m, r, n in good if m >= HS]) if ho else None, 'rule_end': rend, 'end_used': end}
    return s, shape, {m: n for m, r, n in good}


def port_months(sig, file, port, months):
    """同じ信号の別の組を、指定の月（BH の評価の月）の中で Nlong≥20 かつ ret がある月だけ取る"""
    rows = SIG[sig][file].get(port) or []
    return {m: r for m, r, n in rows if m in months and r is not None and n is not None and n >= NMIN}


def net_of(s, turn, unit=UNIT):
    c = turn * unit / 12
    return {m: v - c for m, v in s.items()}


def net_of_m(s, turn_m, unit=UNIT, mult=1.0):
    return {m: v - turn_m[m] * mult * unit / 12 for m, v in s.items()}


def maxdd_same(s, b, a=None, z=None):
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if not ks:
        return None
    return {'s': r2(N.maxdd({k: s[k] for k in ks}) * 100, 1), 'b': r2(N.maxdd({k: b[k] for k in ks}) * 100, 1), 'from': ks[0], 'to': ks[-1]}


def sharpe_block(s, sn, b, a=None, z=None):
    return {'s_gross': N.sharpe(s, RF, a, z), 's_net': N.sharpe(sn, RF, a, z), 'mkt_same_months': N.sharpe({k: b[k] for k in s if k in b}, RF, a, z)}


def halves(r, b):
    ks = sorted(set(r) & set(b))
    n = len(ks)
    f, s = ks[:n // 2], ks[n // 2:]
    return N.excess_stats(r, b, a=f[0], z=f[-1]), N.excess_stats(r, b, a=s[0], z=s[-1]), (f[0], f[-1], s[0], s[-1])


def drop_top_year(r, b):
    """【代用】暦年の幾何の超過（Π(1+s)−Π(1+b)）が最大の1暦年を抜く（兄弟 info と同じ）"""
    ks = sorted(set(r) & set(b))
    yrs = {}
    for k in ks:
        yrs.setdefault(k // 100, []).append(k)
    ann = {y: math.prod(1 + r[k] for k in mm) - math.prod(1 + b[k] for k in mm) for y, mm in yrs.items()}
    top = max(ann, key=ann.get)
    rr = {k: v for k, v in r.items() if k // 100 != top}
    return N.excess_stats(rr, b), top, round(ann[top] * 100, 2), len(yrs[top])


def year_excess(s, b, a=None, z=None):
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    yrs = {}
    for k in ks:
        yrs.setdefault(k // 100, []).append(k)
    return {y: round((math.prod(1 + s[k] for k in mm) - math.prod(1 + b[k] for k in mm)) * 100, 2) for y, mm in sorted(yrs.items())}


def periods_for(sig_rule):
    """期間の切り方（R3 を含む）。sig_rule は事前登録の Z の規則（op・post_publication_from）か None（合成）"""
    P = {'full': (None, LAST), 'train': (None, TE), 'hold': (HS, LAST), 'recent': (RS, LAST),
         'hold_2007_2015': HOLD_H1, 'hold_2016_2024': HOLD_H2}
    if sig_rule:
        pp = sig_rule.get('post_publication_from')
        if pp:
            P['post_pub'] = (pp, LAST)
        op = sig_rule.get('op', {}).get('sample')
        if op and all(str(x).isdigit() for x in op):
            a, z = int(op[0]) * 100 + 1, int(op[1]) * 100 + 12
            P['op_sample'] = (a, z)
            P['before_op'] = (None, (int(op[0]) - 1) * 100 + 12)
            P['after_op'] = ((int(op[1]) + 1) * 100 + 1, LAST)
    return P


def stats_block(s, sn, P, b=None):
    b = MKT if b is None else b
    gross = {k: N.excess_stats(s, b, a, z) for k, (a, z) in P.items()}
    net = {k: N.excess_stats(sn, b, a, z) for k, (a, z) in P.items()}
    if 'op_sample' in P:
        a, z = P['op_sample']
        out_s = {m: v for m, v in s.items() if not (a <= m <= z)}
        out_sn = {m: v for m, v in sn.items() if not (a <= m <= z)}
        gross['outside_op_sample'] = N.excess_stats(out_s, b)
        net['outside_op_sample'] = N.excess_stats(out_sn, b)
    return gross, net


# ───────────────────────── 系列を作る ─────────────────────────
SER = {}   # id → {'s', 'turn_m', 'turn_ann', 'shape', 'nlong'}


def build_single(r):
    s, shape, nl = series(r['signal'], r['file'], r['port'])
    return {'s': s, 'turn_m': {m: r['turn'] for m in s}, 'turn_ann': r['turn'], 'shape': shape, 'nlong': nl}


def build_composite(r):
    legs = [SER[p] for p in r['parts']]
    turns = [RULES[p]['turn'] for p in r['parts']]
    months = sorted(set().union(*[set(l['s']) for l in legs]))
    s, turn_m, nlegs, wsum = {}, {}, {}, {}
    for m in months:
        use = [(l['s'][m], t) for l, t in zip(legs, turns) if m in l['s']]
        if len(use) < r['min_legs']:
            continue
        w = 1.0 / len(use)
        s[m] = math.fsum(w * x for x, _ in use)
        turn_m[m] = S.mean([t for _, t in use]) + r['turn_add']
        nlegs[m] = len(use)
        wsum[m] = w * len(use)
    return {'s': s, 'turn_m': turn_m, 'turn_ann': round(S.mean(turn_m.values()), 4) if turn_m else None,
            'shape': {'eval_from': min(s) if s else None, 'eval_to': max(s) if s else None, 'months': len(s),
                      'train_months': sum(1 for m in s if m <= TE), 'hold_months': sum(1 for m in s if m >= HS)},
            'nlegs': nlegs, 'wsum': wsum, 'legs_hist': {k: sum(1 for v in nlegs.values() if v == k) for k in sorted(set(nlegs.values()))}}


# ───────────────────────── 測る ─────────────────────────
def evaluate(rid, ser, prule):
    s = ser['s']
    sn = net_of_m(s, ser['turn_m'])
    P = periods_for(prule)
    gross, net = stats_block(s, sn, P)
    out = {
        'gross': gross, 'net': net,
        'roll20_net': I.rolling_x(sn, MKT, 20, 7), 'roll20_gross': I.rolling_x(s, MKT, 20, 7),
        'roll10_net': I.rolling_x(sn, MKT, 10, 7), 'roll10_gross': I.rolling_x(s, MKT, 10, 7),
        'dca20_net': I.dca_x(sn, MKT, 20, 12), 'dca20_gross': I.dca_x(s, MKT, 20, 12),
        'maxdd': {'full': maxdd_same(s, MKT), 'hold': maxdd_same(s, MKT, HS), 'full_net': maxdd_same(sn, MKT), 'train': maxdd_same(s, MKT, None, TE)},
        'sharpe': {'train': sharpe_block(s, sn, MKT, None, TE), 'hold': sharpe_block(s, sn, MKT, HS, LAST), 'full': sharpe_block(s, sn, MKT)},
        'periods_used': {k: [a, z] for k, (a, z) in P.items()},
    }
    return out


def short_block(ser):
    """DelDRC（短い標本の線）の入力"""
    s = ser['s']
    sn = net_of_m(s, ser['turn_m'])
    s3 = net_of_m(s, ser['turn_m'], mult=3.0)
    fh, sh, cut = halves(s, MKT)
    dt, topy, topv, topn = drop_top_year(s, MKT)
    ks = sorted(set(s) & set(MKT))
    t_exact = N.nw_t([s[k] - MKT[k] for k in ks])
    return {'first_half': fh, 'second_half': sh, 'halves_cut': cut,
            'drop_top_year': dt, 'dropped_year': topy, 'dropped_year_excess_pct': topv, 'dropped_year_months': topn,
            'cost_full': N.excess_stats(sn, MKT), 'lower_bound_cost3x_full': N.excess_stats(s3, MKT),
            'full_t_unrounded': t_exact, 'p_one_from_unrounded_t': round(N.p_one(t_exact), 4)}


# ───────────────────────── 報告 ─────────────────────────
def r_dup_turn(sig):
    if sig in Z.R_DUP_FAST:
        return 6.0
    pp = str(DOC[sig]['Portfolio Period']).strip()
    return Z.R_DUP_TURN.get(pp, Z.R_DUP_TURN['NA'])


def c1_c6(gross, net, roll20):
    _, c = N.grade(full=gross['full'], train=gross['train'], hold=gross['hold'], roll20=roll20, cost_hold=net['hold'],
                   repl=None, family_holm_p=None, leveraged_or_timing=False)
    return {k: c[k] for k in ('C1_train', 'C2_hold_sign', 'C3_hold_t', 'C4_roll20', 'C5_repl', 'C6_net_cost')}


def report_series(rid):
    r = REPORT[rid]
    sig = r['signal']
    port = X['vwforce_top_port'][sig] if r['port'] == 'TOP' else r['port']
    s, shape, nl = series(sig, r['file'], port)
    turn = r.get('turn') if r.get('turn') is not None else r_dup_turn(sig)
    return s, shape, turn, port


def corr_excess(a, b, lo=None, hi=None):
    ks = sorted(k for k in set(a) & set(b) & set(MKT) if (lo is None or k >= lo) and (hi is None or k <= hi))
    if len(ks) < 24:
        return None
    return round(N.corr([a[k] - MKT[k] for k in ks], [b[k] - MKT[k] for k in ks]), 3)


def dup_report(rid):
    s, shape, turn, port = report_series(rid)
    sn = net_of(s, turn)
    P = {'full': (None, LAST), 'train': (None, TE), 'hold': (HS, LAST), 'recent': (RS, LAST)}
    gross, net = stats_block(s, sn, P)
    ro = I.rolling_x(sn, MKT, 20, 7)
    out = {'id': rid, 'family': REPORT[rid]['fam'], 'signal': REPORT[rid]['signal'], 'file': REPORT[rid]['file'], 'port': port,
           'turn_assumed_eknzbh': turn, 'cost_pct_per_year': round(turn * UNIT * 100, 4), 'shape': shape,
           'gross': gross, 'net': net, 'roll20_net': I._ro_brief(ro, ('windows', 'wins', 'win_rate', 'median', 'worst', 'best')),
           'criteria_C1_C6': c1_c6(gross, net, ro) if gross['train'] and gross['hold'] else None,
           'grade': '報告のみ（格付けの文字・C7 は出さない＝事前登録）'}
    return out, s


def factor_data():
    T5 = N.french_tables('F-F_Research_Data_5_Factors_2x3')
    t5 = next(v for k, v in T5.items() if v['freq'] == 'monthly')
    cols = [c.lower().replace('-', '') for c in t5['cols']]
    F5 = {c: {d: row[i] / 100 for d, row in t5['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
    Tm = N.french_tables('F-F_Momentum_Factor')
    tm = next(v for k, v in Tm.items() if v['freq'] == 'monthly')
    UMD = {d: row[0] / 100 for d, row in tm['data'].items() if row[0] is not None}
    return F5, UMD


def alpha_block(s, F5, UMD, a=None, z=None, extra=None):
    """y = s − RF。CAPM（Mkt-RF）と FF5+UMD（＋extra）。アルファは年率%・NW t（ラグ12）"""
    out = {}
    ks = sorted(k for k in s if k in RF and k in MKTRF_ALL and (a is None or k >= a) and (z is None or k <= z) and k <= LAST)
    if len(ks) >= 36:
        b, t = I.ols_nw([s[k] - RF[k] for k in ks], [[MKTRF_ALL[k] for k in ks]])
        out['capm'] = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'alpha_ann_pct': round(float(b[0]) * 1200, 2), 'alpha_t': round(float(t[0]), 2),
                       'beta_mkt': round(float(b[1]), 3)}
    keys = ['mktrf', 'smb', 'hml', 'rmw', 'cma']
    ks = sorted(k for k in s if k in RF and all(k in F5[c] for c in keys) and k in UMD and (a is None or k >= a) and (z is None or k <= z) and k <= LAST
                and (extra is None or k in extra))
    if len(ks) >= 36:
        Xs = [[F5[c][k] for k in ks] for c in keys] + [[UMD[k] for k in ks]]
        names = keys + ['umd']
        if extra is not None:
            Xs.append([extra[k] for k in ks])
            names.append('tech')
        b, t = I.ols_nw([s[k] - F5['rf'][k] for k in ks], Xs)
        out['ff5_umd' + ('_tech' if extra is not None else '')] = {
            'from': ks[0], 'to': ks[-1], 'n': len(ks), 'alpha_ann_pct': round(float(b[0]) * 1200, 2), 'alpha_t': round(float(t[0]), 2),
            'loadings': {n: round(float(v), 3) for n, v in zip(names, b[1:])}, 'loading_t': {n: round(float(v), 2) for n, v in zip(names, t[1:])}}
    return out


# ───────────────────────── 確かめ ─────────────────────────
def data_sanity(results, halves_chk):
    chk = {}
    # 2. CLASS と SignalDoc の212本
    doc = Z.signaldoc()
    chk['class_vs_signaldoc_predictors'] = Z.check_class(doc)
    # 3. FF93 の恒等式 LS = ½(SH+BH) − ½(SL+BL)
    worst, n, fails = 0.0, 0, []
    for sgn, v in SIG.items():
        if 'FF93style' not in v:
            continue
        P = {p: {m: r for m, r, nn in v['FF93style'].get(p, []) if r is not None} for p in ('SH', 'BH', 'SL', 'BL', 'LS')}
        for m, ls in P['LS'].items():
            if all(m in P[p] for p in ('SH', 'BH', 'SL', 'BL')):
                e = abs(ls - (0.5 * (P['SH'][m] + P['BH'][m]) - 0.5 * (P['SL'][m] + P['BL'][m])))
                n += 1
                worst = max(worst, e)
                if e >= 1e-6:
                    fails.append([sgn, m, e])
    chk['ff93_identity'] = {'months_checked': n, 'max_abs_err_decimal': worst, 'fails_ge_1e-6': len(fails), 'ok': not fails}
    if fails:
        raise SystemExit(f'FF93 の恒等式が合わない: {fails[:5]}')
    # 4. 向き
    lag = X['signallag_check']
    bad = {k: v for k, v in lag.items() if v['share_BH_gt_BL'] != 1.0}
    chk['direction_BH_gt_BL'] = {'signals': len(lag), 'not_all_months': bad, 'ok': not bad}
    # 5. ret の単位
    big = []
    for sgn, v in SIG.items():
        for f, ports in v.items():
            for p, rows in ports.items():
                if p == 'LS':
                    continue
                for m, r, nn in rows:
                    if r is not None and abs(r) > 1.0:
                        big.append([sgn, f, p, m, r])
    chk['ret_units_abs_gt_1'] = {'count': len(big), 'examples': big[:10], 'ok': not big}
    if big:
        raise SystemExit(f'|月次| > 1.0 の月がある（単位の誤りの疑い）: {big[:5]}')
    # 6. French
    mk = [k for k in FF['mktrf'] if k in FF['rf']]
    diff = max(abs(FF['mkt'][k] - (FF['mktrf'][k] + FF['rf'][k])) for k in mk)
    used_after = sorted({m for x in results for per in ('full',) for m in [((x['gross'][per] or {}).get('to'))] if m and m > LAST})
    chk['french'] = {'mkt_eq_mktrf_plus_rf_max_abs_diff': diff, 'french_last_month': max(FF['mktrf']), 'mkt_used_last_month': max(MKT),
                     'any_comparison_after_2024_12': used_after, 'ok': diff < 1e-12 and max(MKT) <= LAST and not used_after}
    # 7. 評価の窓の形が事前登録と一致
    mism = {}
    keys = ('eval_from', 'eval_to', 'months', 'train_months', 'hold_months', 'dropped_after_start_nlong_lt20', 'gaps', 'nlong_median', 'nlong_median_hold', 'nlong_min')
    for rid, pre in PR['data']['shape_primary'].items():
        mine = SER[rid]['shape']
        d = {k: (pre.get(k), mine.get(k)) for k in keys if k in pre and pre.get(k) != mine.get(k)}
        if d:
            mism[rid] = d
    for rid, pre in PR['data']['shape_report'].items():
        mine = REP_SHAPE.get(rid)
        if mine is None:
            mism[rid] = 'not computed'
            continue
        d = {k: (pre.get(k), mine.get(k)) for k in pre if k in mine and k not in ('file', 'port') and pre.get(k) != mine.get(k)}
        if d:
            mism[rid] = d
    chk['shape_vs_prereg'] = {'primary_checked': len(PR['data']['shape_primary']), 'report_checked': len(PR['data']['shape_report']),
                              'mismatches': mism, 'ok': not mism}
    if mism:
        raise SystemExit(f'評価の窓の形が事前登録と違う: {json.dumps(mism, ensure_ascii=False)[:800]}')
    # 8. 合成
    comp = {}
    for rid in ZCP:
        sr = SER[rid]
        comp[rid] = {'min_legs_rule': RULES[rid]['min_legs'], 'min_legs_seen': min(sr['nlegs'].values()), 'max_legs_seen': max(sr['nlegs'].values()),
                     'weights_sum_max_abs_err': max(abs(w - 1) for w in sr['wsum'].values()), 'legs_hist': sr['legs_hist'],
                     'ok': min(sr['nlegs'].values()) >= RULES[rid]['min_legs'] and max(abs(w - 1) for w in sr['wsum'].values()) < 1e-12}
    chk['composites'] = comp
    # 9. 大型の半分＋小型の半分 ≒ French Mkt
    chk['size_halves'] = halves_chk
    return chk


def q5_vs_intang(dup_series):
    """10. R_dupQ5 の系列が兄弟 intang の R5（QuintilesVW の05・同じファイル）と一致するか"""
    zp = os.path.join(N.CACHE, 'osap_PredictorAltPorts_QuintilesVW.zip')
    sha = sha256_file(zp)
    want = PR['data']['files']['QuintilesVW']['sha256']
    intang_sha = None
    try:
        intang_sha = json.load(open(os.path.join(BASE, 'out', 'nx_osap_intang.json')))['reports']['R5_base_rate']['quintilesvw_sha256']
    except Exception:  # noqa
        pass
    z = zipfile.ZipFile(zp)
    rows = {}
    want_sigs = {Z_: 1 for Z_ in Z.Z_IDS}
    for r in csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig')):
        if r['port'] != '05' or r['signalname'] not in want_sigs or r['ret'] in ('', 'NA', 'NaN'):
            continue
        n = int(float(r['Nlong'])) if r['Nlong'] not in ('', 'NA') else None
        rows.setdefault(r['signalname'], []).append([Z.D.ym(r['date']), float(r['ret']) / 100.0, n])
    res = {}
    try:
        ib = json.load(open(os.path.join(BASE, 'out', 'nx_osap_intang.json')))['reports']['R5_base_rate']['by_signal']
    except Exception:  # noqa
        ib = {}
    for sg in Z.Z_IDS:
        s_int, st, drop = I.filt(sorted(rows[sg]))
        mine = dup_series[f'R_dupQ5_{sg}']
        same_keys = sorted(s_int) == sorted(mine)
        mx = max(abs(s_int[k] - mine[k]) for k in mine) if same_keys else None
        ent = {'same_months': same_keys, 'max_abs_diff': mx}
        if sg in ib:
            tr = N.excess_stats(mine, MKT, None, TE)
            ho = N.excess_stats(mine, MKT, HS, LAST)
            ent['intang_json_vs_mine'] = {'train_ex_ann': (ib[sg].get('train_ex_ann'), tr['ex_ann'] if tr else None),
                                          'hold_ex_ann': (ib[sg].get('hold_ex_ann'), ho['ex_ann'] if ho else None),
                                          'hold_t': (ib[sg].get('hold_t'), ho['t'] if ho else None)}
            ent['intang_json_match'] = all(a == b for a, b in ent['intang_json_vs_mine'].values())
        res[sg] = ent
    ok = sha == want and all(v['same_months'] and v['max_abs_diff'] == 0 for v in res.values())
    return {'quintilesvw_sha_now': sha, 'prereg': want, 'intang_R5_recorded_sha': intang_sha, 'by_signal': res,
            'intang_json_all_match': all(v.get('intang_json_match', True) for v in res.values()), 'ok': ok}


# ───────────────────────── 独立の答え合わせ・他セッションとの再計算 ─────────────────────────
def r8_independent(byid):
    out = {}
    ll_path = os.path.join(BASE, 'out', 'nx_leadlag.json')
    st = subprocess.run(['git', 'status', '--porcelain', '--', 'out/nx_leadlag.json', 'night/nx_leadlag.py'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    try:
        L = json.load(open(ll_path))
        prim = [x for x in L['tested'] if x.get('family') == 'primary']
        ll = {x['name']: {'hold_ex_ann': ((x.get('stats_gross') or {}).get('hold') or {}).get('ex_ann'),
                          'hold_t': ((x.get('stats_gross') or {}).get('hold') or {}).get('t'),
                          'grade': x.get('grade')} for x in prim}
    except Exception as e:  # noqa
        ll = {'error': str(e)}
    mine = {}
    for rid in ('Z_CustomerMomentum_BH', 'Z_iomom_cust_BH', 'Z_iomom_supp_BH', 'Z_IndRetBig_BH', 'Z_EarnSupBig_BH', 'Z_retConglomerate_BH', 'ZC2_LINKS'):
        h = byid[rid]['gross']['hold']
        mine[rid] = {'hold_ex_ann': h['ex_ann'] if h else None, 'hold_t': h['t'] if h else None, 'grade': byid[rid]['grade']}
    ll_signs = sorted({(v['hold_ex_ann'] > 0) for v in ll.values() if isinstance(v, dict) and v.get('hold_ex_ann') is not None}) if 'error' not in ll else []
    agree = {}
    if ll_signs and len(ll_signs) == 1:
        s0 = ll_signs[0]
        agree = {rid: ((v['hold_ex_ann'] or 0) > 0) == s0 for rid, v in mine.items()}
    out['a_nx_leadlag'] = {'read_after_this_angle_numbers_fixed': True, 'nx_leadlag_file': 'out/nx_leadlag.json（作業ツリー）',
                           'nx_leadlag_git_status': st or '変更なし', 'nx_leadlag_commit': git_sha(ll_path),
                           'caution': 'nx_leadlag はこの時点で「測定の途中（検査・是正の途中）」とコミットされた版（git status が変更を示せば未コミットの作業も含む）。確定版で数字が変わりうる',
                           'nx_leadlag_primary_hold': ll, 'this_angle_hold': mine,
                           'nx_leadlag_primary_hold_signs': ['正' if x else '負' for x in ll_signs],
                           'sign_agreement_with_nx_leadlag': agree or '（nx_leadlag の主の5本の保有の符号が揃っていないので一つの符号とは比べない。表を読む）'}
    # (b) main の moat4 C1・moat_dr
    bb = {}
    for sgn in ('OrderBacklog', 'OrderBacklogChg', 'DelDRC'):
        x = byid[f'Z_{sgn}_BH']
        ots = x['R2_inside_large']
        bb[sgn] = {'osap_sign': int(DOC[sgn]['Sign']), 'good_side_BH': {per: {k: (x['gross'][per] or {}).get(k) for k in ('ex_ann', 't', 'cagr_diff')}
                                                                    for per in ('full', 'train', 'hold', 'recent')},
                   'bad_side_BL': {per: {k: ((ots['BL_vs_mkt'][per] or {}).get(k)) for k in ('ex_ann', 't', 'cagr_diff')} for per in ('full', 'train', 'hold')},
                   'grade': x['grade']}
    out['b_main_moat4_moat_dr'] = {
        'main_conclusions_quoted_from_CLAUDE_md': {
            'moat4_C1': '受注残の倍率（2019-21・185-231社）差+1.5〜+3.1 だが p=0.25、STRL 1社を抜くと3アンカーとも負＝不合格（受注残が多い群を良いとした向き）',
            'moat_dr': '前受収益の倍率（2013/16/17/18・開示373-515社）2013だけ +5.5pt だが利益の63%が NVDA（抜くと −2.2）・2016-18 は3つとも負け（−2.1〜−4.0）＝不合格（前受収益が多い群を良いとした向き）'},
        'this_angle': bb,
        'direction_note': 'OSAP の OrderBacklog は Sign −1（受注残が少ない側が良い＝BH）で、main の moat4 の向き（多いほうが良い）とは逆。main と同じ向き（受注残の多い大型株）は BL（大型の悪い側）にあたる。OrderBacklogChg（受注残の増加・Sign +1）と DelDRC（前受収益の増加・Sign +1）は main の水準の倍率ではなく変化の量＝同じ考えの別の量',
    }
    return out


def r11_eknzbh(dups):
    ref = 'origin/claude/market-winning-backtest-eknzbh'
    try:
        head = subprocess.run(['git', 'log', '-1', '--format=%H %ci', ref], cwd=BASE, capture_output=True, text=True).stdout.strip()
        blob = subprocess.run(['git', 'show', f'{ref}:out/mw_oap_signals.json'], cwd=BASE, capture_output=True).stdout
        E = json.loads(blob)
    except Exception as e:  # noqa
        return {'error': str(e)}
    idx = {}
    for x in E['tested']:
        pf = str(x.get('portfolio') or '')
        idx.setdefault((x.get('signal'), pf), []).append(x)
    rows, diffs = {}, []
    for rid, d in dups.items():
        sig = d['signal']
        if d['file'] == 'QuintilesVW':
            cands = [v for (sg, pf), vs in idx.items() if sg == sig and 'Quintile' in pf and pf.endswith(':05') for v in vs]
        else:
            cands = [v for (sg, pf), vs in idx.items() if sg == sig and 'VWforce' in pf and pf.endswith(':' + d['port']) for v in vs]
        if not cands:
            rows[rid] = {'eknzbh': '該当なし'}
            continue
        e = cands[0]
        ev = e.get('eval') or {}
        ent = {'eknzbh_id': e.get('id'), 'eknzbh_family': e.get('family'), 'eknzbh_portfolio': e.get('portfolio'),
               'eknzbh_grade': e.get('grade'), 'eval_start': (ev.get('start'), d['shape']['eval_from']),
               'months': (ev.get('months'), d['shape']['months']), 'eknzbh_turnover_per_year': ev.get('turnover_per_year'), 'this_turn': d['turn_assumed_eknzbh']}
        for per in ('train', 'hold', 'full'):
            a = ev.get(per) or {}
            b = d['gross'].get(per) or {}
            ent[per] = {k: (a.get(k), b.get(k)) for k in ('ex_ann', 't', 'cagr_diff')}
            if a.get('ex_ann') is not None and b.get('ex_ann') is not None:
                diffs.append(abs(a['ex_ann'] - b['ex_ann']))
        a, b = (ev.get('cost_hold') or {}), (d['net'].get('hold') or {})
        ent['net_hold'] = {k: (a.get(k), b.get(k)) for k in ('ex_ann', 'cagr_diff')}
        if len(cands) > 1:
            ent['note'] = f'eknzbh に同じ信号・組が {len(cands)} 本（family {[c.get("family") for c in cands]}）＝最初のものと比べた'
        rows[rid] = ent
    return {'read_after_R4_R10_fixed': True, 'ref': ref, 'head': head, 'by_rule': rows,
            'ex_ann_abs_diff': {'n': len(diffs), 'max': max(diffs) if diffs else None, 'median': S.median(diffs) if diffs else None},
            'how_to_read': '各欄は（eknzbh の値, この角度の値）。費用前の excess_stats。評価の開始月・月数が違えば数字も違う（eknzbh は自分の Nlong の規則）'}


def program_bonferroni(byid):
    """事前登録の数え方: 各角度の事前登録の格付けの本数（test_count）を数え直す。結果の JSON の本数も並べる"""
    import glob
    per = {}
    for p in sorted(glob.glob(os.path.join(BASE, 'out', 'nx_*_prereg.json'))):
        ang = os.path.basename(p)[:-len('_prereg.json')]
        try:
            tc = json.load(open(p)).get('test_count') or {}
        except Exception:  # noqa
            continue
        if isinstance(tc, dict):
            if isinstance(tc.get('total_graded'), int):
                n = tc['total_graded']
            elif isinstance(tc.get('primary'), int):
                n = tc['primary'] + (tc.get('exploratory') or 0 if isinstance(tc.get('exploratory'), int) else 0)
            else:
                n = sum(v for k, v in tc.items() if isinstance(v, int) and k not in ('report_only',))
        elif isinstance(tc, int):
            n = tc
        else:
            n = None
        rn = None
        rp = os.path.join(BASE, 'out', f'{ang}.json')
        if os.path.exists(rp) and ang != 'nx_osap_zoo':
            try:
                tt = json.load(open(rp)).get('tested')
                if isinstance(tt, list):
                    rn = len(tt)
            except Exception:  # noqa
                pass
        per[ang] = {'prereg_graded': n, 'result_json_tested_entries': rn}
    Ntot = sum(v['prereg_graded'] for v in per.values() if v['prereg_graded'])
    tstar = NormalDist().inv_cdf(1 - 0.025 / Ntot)
    Nref = Ntot + PR['criteria']['program_bonferroni']['reference_including_eknzbh_osap']['eknzbh_mw_oap_signals_graded']
    tref = NormalDist().inv_cdf(1 - 0.025 / Nref)
    rows = {}
    for rid, x in byid.items():
        h, f = x['gross']['hold'], x['gross']['full']
        rows[rid] = {'hold_t': h['t'] if h else None, 'full_t': f['t'] if f else None,
                     'hold_abs_t_ge_tstar': bool(h and h['t'] is not None and abs(h['t']) >= tstar),
                     'full_t_ge_tstar': bool(f and f['t'] is not None and f['t'] >= tstar),
                     'full_t_ge_tstar_ref_with_eknzbh': bool(f and f['t'] is not None and f['t'] >= tref)}
    return {'N': Ntot, 't_star': round(tstar, 3), 'N_at_registration': PR['criteria']['program_bonferroni']['N_at_registration'],
            't_star_at_registration': PR['criteria']['program_bonferroni']['t_star_at_registration'], 'breakdown': per,
            'reference_with_eknzbh_osap': {'N': Nref, 't_star': round(tref, 3)}, 'by_rule': rows,
            'passing_hold': [k for k, v in rows.items() if v['hold_abs_t_ge_tstar']], 'passing_full': [k for k, v in rows.items() if v['full_t_ge_tstar']],
            'note': '格付けには使わない（事前登録）。|保有の t| は負けの向きでも数える'}


# ───────────────────────── 事後の診断（格付けに使わない） ─────────────────────────
def post_hoc(results, byid, F5, UMD):
    ph = {'_note': '事後＝結果を見た後に足した診断。格付けには使わない'}
    # (1) 保有期間の年ごとの幾何の超過（費用後）
    yb = {}
    for x in results:
        sr = SER[x['id']]
        sn = net_of_m(sr['s'], sr['turn_m'])
        ye = year_excess(sn, MKT, HS, LAST)
        pos = sum(1 for v in ye.values() if v > 0)
        top = max(ye, key=ye.get) if ye else None
        yb[x['id']] = {'net_by_year_pct': ye, 'years_positive': f'{pos}/{len(ye)}', 'best_year': [top, ye.get(top)] if top else None,
                       'worst_year': [min(ye, key=ye.get), min(ye.values())] if ye else None}
    ph['hold_by_year_net'] = yb
    # (2) テックの傾き（French 49業種の Chips・Softw・Hardw の等分 − Mkt）を FF5+勢いに足した回帰（保有・全期間）
    try:
        ind = N.french_series('49_Industry_Portfolios', 'Value Weight')
        tech = {m: (ind['Chips'][m] + ind['Softw'][m] + ind['Hardw'][m]) / 3 - MKT_ALL[m]
                for m in ind['Chips'] if m in ind['Softw'] and m in ind['Hardw'] and m in MKT_ALL and m <= LAST}
        tt = {}
        for x in results:
            s = SER[x['id']]['s']
            tt[x['id']] = {'hold': alpha_block(s, F5, UMD, HS, LAST, extra=tech).get('ff5_umd_tech'),
                           'full': alpha_block(s, F5, UMD, None, LAST, extra=tech).get('ff5_umd_tech')}
        ph['tech_tilt_regression'] = {'what': 'y = s − RF を Mkt-RF・SMB・HML・RMW・CMA・UMD・TECH（49業種の Chips/Softw/Hardw の等分 − Mkt）で回帰した切片（年率%・NW t）',
                                      'by_rule': tt}
    except Exception as e:  # noqa
        ph['tech_tilt_regression'] = {'error': str(e)}
    # (3) 29本の BH の超過どうしの相関（独立の試行の数の見当）
    ids = [x['id'] for x in results if x['family'] == ZFAM]
    ex = {i: {m: SER[i]['s'][m] - MKT[m] for m in SER[i]['s'] if m in MKT} for i in ids}
    for lab, lo, hi in (('hold', HS, LAST), ('full_1988_07_on', 198807, LAST)):
        cs = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ex[ids[i]], ex[ids[j]]
                ks = sorted(k for k in set(a) & set(b) if lo <= k <= hi)
                if len(ks) >= 60:
                    cs.append(N.corr([a[k] for k in ks], [b[k] for k in ks]))
        if cs:
            rbar = S.mean(cs)
            m = len(ids)
            ph[f'pairwise_excess_corr_{lab}'] = {'pairs': len(cs), 'mean': round(rbar, 3), 'median': round(S.median(cs), 3),
                                                 'effective_tests_approx': round(m / (1 + (m - 1) * max(rbar, 0)), 1),
                                                 'how': '有効な試行の数 ≈ m ÷ (1 + (m−1)×平均の相関)（粗い近似）'}
    # (4) BH と Q5（同じ信号の全銘柄の第5五分位）の保有の超過の順位の一致
    try:
        bh = [(byid[f'Z_{sg}_BH']['gross']['hold']['ex_ann'], DUPS[f'R_dupQ5_{sg}']['gross']['hold']['ex_ann']) for sg in Z.Z_IDS]
        rk = lambda v: {i: r for r, i in enumerate(sorted(range(len(v)), key=lambda k: v[k]))}
        ra, rb = rk([a for a, _ in bh]), rk([b for _, b in bh])
        ph['bh_vs_q5_hold_rank_corr'] = round(N.corr([ra[i] for i in range(len(bh))], [rb[i] for i in range(len(bh))]), 3)
        ph['bh_vs_q5_hold_ex_ann_corr'] = round(N.corr([a for a, _ in bh], [b for _, b in bh]), 3)
    except Exception as e:  # noqa
        ph['bh_vs_q5'] = {'error': str(e)}
    # (5) 訓練の超過が大きい規則ほど保有でも大きいか（規則をまたいだ相関・Z の29本）
    th = [((x['gross']['train'] or {}).get('ex_ann'), (x['gross']['hold'] or {}).get('ex_ann')) for x in results if x['family'] == ZFAM and x['gross']['train'] and x['gross']['hold']]
    ph['train_vs_hold_ex_ann_corr_Z'] = {'n': len(th), 'corr': round(N.corr([a for a, _ in th], [b for _, b in th]), 3)}
    # (6) 保有期間の算術の超過の分布（Z の29本・費用前）と、正の本数の二項の見当
    hv = sorted((x['gross']['hold'] or {}).get('ex_ann') for x in results if x['family'] == ZFAM and x['gross']['hold'])
    pos = sum(1 for v in hv if v > 0)
    ph['hold_ex_ann_distribution_Z'] = {'n': len(hv), 'positive': pos, 'median': S.median(hv), 'min': hv[0], 'max': hv[-1]}
    tv = sorted((x['gross']['train'] or {}).get('ex_ann') for x in results if x['family'] == ZFAM and x['gross']['train'])
    ph['train_ex_ann_distribution_Z'] = {'n': len(tv), 'positive': sum(1 for v in tv if v > 0), 'median': S.median(tv), 'min': tv[0], 'max': tv[-1]}
    # (7) 母集団の粗い代わり: 同じ信号の大型の3組（BL・BM・BH）の等分 vs Mkt。「その信号を持つ大型株に居ること」の効果の見当
    up = {}
    for x in results:
        if not x.get('signal'):
            continue
        sg = x['signal']
        months = set(SER[x['id']]['s'])
        bl = port_months(sg, 'FF93style', 'BL', months)
        bm = port_months(sg, 'FF93style', 'BM', months)
        bh = SER[x['id']]['s']
        prox = {m: (bl[m] + bm[m] + bh[m]) / 3 for m in months if m in bl and m in bm}
        up[x['id']] = {'proxy_vs_mkt': {k: N.excess_stats(prox, MKT, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))},
                       'BH_vs_proxy': {k: N.excess_stats(bh, prox, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))}}
    ph['universe_proxy'] = {'what': '大型の3組（BL・BM・BH・各組は時価加重）を等分した系列＝「その信号のデータがある大型株」の粗い代わり（組の時価が無いので等分）。proxy_vs_mkt が大きければ、BH の勝ちの多くは信号の並べ方ではなく母集団に居ること',
                            'by_rule': up}
    # (8) 実在の指数: QQQ（NASDAQ100・配当込み・Yahoo）との比較（B 以上の規則だけ）
    try:
        qqq = N.yahoo('QQQ')
        qq = {}
        for x in results:
            if x['grade'][0] not in ('S', 'A', 'B'):
                continue
            sr = SER[x['id']]
            sn = net_of_m(sr['s'], sr['turn_m'])
            qq[x['id']] = {'gross_vs_qqq': {k: N.excess_stats(sr['s'], qqq, a, z) for k, (a, z) in (('overlap', (None, LAST)), ('hold', (HS, LAST)))},
                           'net_vs_qqq': {k: N.excess_stats(sn, qqq, a, z) for k, (a, z) in (('overlap', (None, LAST)), ('hold', (HS, LAST)))},
                           'qqq_vs_mkt_same_months': {k: N.excess_stats({m: qqq[m] for m in sr['s'] if m in qqq}, MKT, a, z) for k, (a, z) in (('overlap', (None, LAST)), ('hold', (HS, LAST)))}}
        ph['vs_QQQ'] = {'what': 'B 以上の規則を QQQ（Yahoo の配当込み調整後終値・1999-03〜）と同じ月で比べる。持ち主の ETF 側（NASDAQ100）と比べて上乗せがあるか', 'first_month': min(qqq), 'by_rule': qq}
    except Exception as e:  # noqa
        ph['vs_QQQ'] = {'error': str(e)}
    # (9) 基礎率: OSAP の FF93style にある全信号の BH（大型の良い側）に同じ線を当てる
    try:
        ph['base_rate_ff93_bh'] = base_rate_ff93()
    except Exception as e:  # noqa
        ph['base_rate_ff93_bh'] = {'error': str(e)}
    return ph


def base_rate_ff93():
    """事後: OSAP の FF93style の全信号の BH について
    (a) 長い歴史の線（grade・評価の開始〜min(最後のリターン, 2024-12)・Holm は全信号で1つ・費用 年0.30%）
    (b) 短い標本の線（grade_short）を DelDRC と同じ窓 2002-07〜2024-12 に切って当てた場合（Holm は全信号で1つ・代用は DelDRC と同じ）
    の格付けの分布。DelDRC の A・BetaTailRisk/ChAssetTurnover の B が、どの信号にでも付く程度のものかの見当（格付けには使わない）"""
    b = Z.D.fetch('FF93style')
    rows = {}
    for r in Z.D.rows_of('FF93style', b):
        if r['port'] != 'BH' or not r['date'][:4].isdigit():
            continue
        ret = float(r['ret']) / 100.0 if r['ret'] not in ('', 'NA', 'NaN') else None
        n = int(float(r['Nlong'])) if r['Nlong'] not in ('', 'NA') else None
        rows.setdefault(r['signalname'], []).append([Z.D.ym(r['date']), ret, n])
    longres, shortres = {}, {}
    pl, ps = {}, {}
    for sg, rw in rows.items():
        rw.sort()
        good = [x for x in rw if x[1] is not None]
        if not good:
            continue
        end = min(max(m for m, r, n in good), LAST)
        st, gd, drop, gaps = Z.eval_window(rw, end)
        s = {m: r for m, r, n in gd}
        if len([m for m in s if m <= TE]) >= 180 and len([m for m in s if m >= HS]) >= 120:
            sn = net_of(s, 1.0)
            e = {'full': N.excess_stats(s, MKT, None, LAST), 'train': N.excess_stats(s, MKT, None, TE), 'hold': N.excess_stats(s, MKT, HS, LAST),
                 'hold_net': N.excess_stats(sn, MKT, HS, LAST), 'roll20_net': I.rolling_x(sn, MKT, 20, 7)}
            longres[sg] = e
            pl[sg] = e['hold']['p'] if e['hold'] else None
        s2 = {m: r for m, r in s.items() if 200207 <= m <= LAST}
        if len(s2) >= 240:
            fh, sh, _ = halves(s2, MKT)
            dt = drop_top_year(s2, MKT)[0]
            ks = sorted(set(s2) & set(MKT))
            t = N.nw_t([s2[k] - MKT[k] for k in ks])
            shortres[sg] = {'full': N.excess_stats(s2, MKT), 'fh': fh, 'sh': sh, 'dt': dt, 'cost': N.excess_stats(net_of(s2, 1.0), MKT),
                            'lb': N.excess_stats(net_of(s2, 3.0), MKT), 'beta': (N.excess_stats(s2, MKT) or {}).get('beta')}
            ps[sg] = round(N.p_one(t), 4)
    hl, hs = N.holm(pl), N.holm(ps)
    cl, cs = {}, {}
    for sg, e in longres.items():
        g, c = N.grade(full=e['full'], train=e['train'], hold=e['hold'], roll20=e['roll20_net'], cost_hold=e['hold_net'], repl=None,
                       family_holm_p=hl.get(sg), leveraged_or_timing=False)
        cl.setdefault(g, []).append(sg)
    betas_a, betas_all = [], []
    for sg, e in shortres.items():
        g, c = N.grade_short(e['full'], e['fh'], e['sh'], e['dt'], e['cost'], e['lb'], family_holm_p_one=hs.get(sg))
        cs.setdefault(g, []).append(sg)
        if e['beta'] is not None:
            betas_all.append(e['beta'])
            if g in ('A', 'S'):
                betas_a.append(e['beta'])
    exs = sorted((e['full'] or {}).get('ex_ann') for e in shortres.values() if e['full'])
    return {'n_signals_in_file': len(rows),
            'long_line': {'n': len(longres), 'rule': '訓練 15年以上かつ保有 10年以上の月がある信号。費用 年0.30%・Holm は全信号で1つ',
                          'counts': {g: len(v) for g, v in sorted(cl.items())}, 'lists_non_C': {g: sorted(v) for g, v in cl.items() if g != 'C'}},
            'short_line_2002_07_to_2024_12': {'n': len(shortres), 'rule': '2002-07〜2024-12 に Nlong≥20 の月が240以上ある信号。DelDRC と同じ代用（最大の暦年を抜く・費用3倍）・Holm は全信号で1つ',
                                             'counts': {g: len(v) for g, v in sorted(cs.items())}, 'lists_A_S': {g: sorted(v) for g, v in cs.items() if g in ('A', 'S')},
                                             'full_ex_ann_median': S.median(exs) if exs else None, 'share_full_ex_ann_positive': round(sum(1 for v in exs if v > 0) / len(exs), 3) if exs else None,
                                             'beta_median_all': S.median(betas_all) if betas_all else None, 'beta_median_A_S': S.median(betas_a) if betas_a else None},
            'note': '事後。FF93style の BH は信号ごとに SignalDoc の Sign を掛けた後の良い側。終わりは min(最後のリターン, 2024-12)（主の族の「最後の6月の組を1年」の規則は当てていない）'}


# ───────────────────────── 本体 ─────────────────────────
REP_SHAPE = {}
DUPS = {}


def main():
    t0 = datetime.datetime.now()
    shachk = check_sha()
    # 系列
    for r in Z.RULES:
        if 'signal' in r:
            SER[r['id']] = build_single(r)
    for r in Z.RULES:
        if 'parts' in r:
            SER[r['id']] = build_composite(r)

    results = []
    for r in Z.RULES:
        ser = SER[r['id']]
        prule = ZP.get(r['id'])
        x = {'id': r['id'], 'family': r['fam'], 'exploratory': r['fam'] == ZCFAM,
             'what': (prule or {}).get('what') or r.get('what'), 'signal': r.get('signal'), 'file': r.get('file'), 'port': r.get('port'),
             'parts': r.get('parts'), 'class': (prule or {}).get('class'), 'criteria_line': (prule or {}).get('criteria', 'long'),
             'flags': (prule or {}).get('flags'), 'op': (prule or {}).get('op'),
             'turn_assumed': ser['turn_ann'], 'cost_pct_per_year': round(ser['turn_ann'] * UNIT * 100, 4) if ser['turn_ann'] else None,
             'shape': ser['shape']}
        x.update(evaluate(r['id'], ser, prule))
        if 'parts' in r:
            x['legs_hist'] = ser['legs_hist']
            x['cost_note'] = '月ごとに 使った脚の回転の平均（1.0）＋0.10 × 0.30%／12'
        if x['criteria_line'] == 'short':
            x['short'] = short_block(ser)
        results.append(x)
    byid = {x['id']: x for x in results}

    # Holm（Z 29本で1つ・ZC 3本で1つ）
    pvZ = {}
    for x in results:
        if x['family'] != ZFAM:
            continue
        if x['criteria_line'] == 'short':
            pvZ[x['id']] = x['short']['p_one_from_unrounded_t']
            x['holm_input_p'] = {'kind': '全期間の費用前の NW t の片側 p（p_one）', 'p': pvZ[x['id']]}
        else:
            pvZ[x['id']] = (x['gross']['hold'] or {}).get('p')
            x['holm_input_p'] = {'kind': '保有期間の費用前の NW t の両側 p（excess_stats の p・小数4桁）', 'p': pvZ[x['id']]}
    pvC = {x['id']: (x['gross']['hold'] or {}).get('p') for x in results if x['family'] == ZCFAM}
    for x in results:
        if x['family'] == ZCFAM:
            x['holm_input_p'] = {'kind': '保有期間の費用前の NW t の両側 p', 'p': pvC[x['id']]}
    holm = {ZFAM: N.holm(pvZ), ZCFAM: N.holm(pvC)}

    # 格付け
    for x in results:
        hp = holm[x['family']].get(x['id'])
        x['family_holm_p'] = hp
        if x['criteria_line'] == 'short':
            sh = x['short']
            g, c = N.grade_short(x['gross']['full'], sh['first_half'], sh['second_half'], sh['drop_top_year'], sh['cost_full'],
                                 sh['lower_bound_cost3x_full'], family_holm_p_one=hp)
            x['grade'] = g + ('（代用あり）' if g == 'S' else '')
            x['criteria'] = c
            x['grading_call'] = 'nx_common.grade_short（criteria_short_sample）。drop_top は【代用】最大の暦年を抜く・lower_bound は【代用】費用3倍（0.90%/年）'
            g2, c2 = N.grade(full=x['gross']['full'], train=x['gross']['train'], hold=x['gross']['hold'], roll20=x['roll20_net'],
                             cost_hold=x['net']['hold'], repl=None, family_holm_p=None, leveraged_or_timing=False)
            x['long_criteria_reference_not_used'] = {'grade': g2, 'criteria': c2, 'note': '参考のみ・格付けに使わない（訓練 4.5年＝短い標本の線）。C7 は Holm なし＝全期間 t≥3 だけ'}
        else:
            g, c = N.grade(full=x['gross']['full'], train=x['gross']['train'], hold=x['gross']['hold'], roll20=x['roll20_net'],
                           cost_hold=x['net']['hold'], repl=None, family_holm_p=hp, leveraged_or_timing=False)
            x['grade'] = g
            x['criteria'] = c
            x['grading_call'] = 'nx_common.grade（criteria_long_history）: full/train/hold＝費用前・roll20＝費用後（丸める前の差で勝ちを数える）・cost_hold＝費用後の保有・repl=None（C5 N/A）・leveraged_or_timing=False（C8 N/A）'
        if x['exploratory']:
            x['grade_label'] = f"探索 {x['grade']}"
        x['C1_to_C8'] = x['criteria'] if x['criteria_line'] != 'short' else None

    # ── 報告 ──
    halves_ser, hchk = I.size_halves()
    F5, UMD = factor_data()
    for x in results:
        sr = SER[x['id']]
        s = sr['s']
        sn = net_of_m(s, sr['turn_m'])
        # R1 大型の半分
        P = {'full': (None, LAST), 'train': (None, TE), 'hold': (HS, LAST), 'recent': (RS, LAST)}
        x['R1_vs_big_half'] = {'gross': {k: N.excess_stats(s, halves_ser['big'], a, z) for k, (a, z) in P.items()},
                               'net': {k: N.excess_stats(sn, halves_ser['big'], a, z) for k, (a, z) in P.items()},
                               'roll20_net': I._ro_brief(I.rolling_x(sn, halves_ser['big'], 20, 7), ('windows', 'wins', 'win_rate', 'median', 'worst', 'best'))}
        # R2 大型の中（単一の信号だけ）
        if x.get('signal'):
            sg = x['signal']
            months = set(s)
            bl = port_months(sg, 'FF93style', 'BL', months)
            bm = port_months(sg, 'FF93style', 'BM', months)
            ls = {m: r for m, r, nn in SIG[sg]['FF93style']['LS'] if m in months and r is not None}
            zero = {m: 0.0 for m in ls}
            shp, sh_shape, _ = series(sg, 'FF93style', 'SH')
            x['R2_inside_large'] = {
                'months_rule': 'BL・BM は BH の評価の月の中で自分の Nlong≥20 の月だけ。SH は自分の評価の窓（Nlong≥20）',
                'BL_vs_mkt': {k: N.excess_stats(bl, MKT, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))},
                'BM_vs_mkt': {k: N.excess_stats(bm, MKT, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))},
                'BH_minus_BL': {k: N.excess_stats(s, bl, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))},
                'LS_osap_vs_zero': {k: N.excess_stats(ls, zero, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))},
                'SH_vs_small_half': {k: N.excess_stats(shp, halves_ser['small'], a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))},
                'SH_eval_from': sh_shape['eval_from'],
                'note': 'BH_minus_BL と LS は ex_ann と t を読む（cagr の欄は差の系列には意味が薄い）',
            }
        # R5 費用の感度
        cs = {}
        for name, unit, tm in (('turn_x0.5', UNIT, 0.5), ('unit0.10', 0.001, 1.0), ('unit0.60', 0.006, 1.0)):
            snn = net_of_m(s, sr['turn_m'], unit, tm)
            h = N.excess_stats(snn, MKT, HS, LAST)
            ro = I.rolling_x(snn, MKT, 20, 7)
            cs[name] = {'hold_net': {k: h[k] for k in ('ex_ann', 't', 'cagr_diff')} if h else None,
                        'C6_net_cost': bool(h and h['ex_ann'] > 0 and h['cagr_diff'] > 0),
                        'roll20_net': I._ro_brief(ro, ('wins', 'windows', 'win_rate', 'median')), 'C4_roll20': bool(ro and ro['win_rate'] >= 0.8)}
        x['R5_cost_sensitivity'] = cs
        # R6 その他の指標
        x['R6_other'] = {per: {k: (x['gross'][per] or {}).get(k) for k in ('beta', 'te', 'ir', 'vol_s', 'vol_b')} for per in ('full', 'train', 'hold')}
        # R7 因子のアルファ
        x['R7_factor_alpha'] = {'hold': alpha_block(s, F5, UMD, HS, LAST), 'full': alpha_block(s, F5, UMD, None, LAST),
                                'note': 'FF5 は 1963-07 から＝全期間の FF5+UMD は 1963-07 以降。y = s − RF（費用前）'}

    # R4・R10・R9: 重複の報告と訓練だけ・薄いもの
    for rid, r in REPORT.items():
        d, s = dup_report(rid)
        REP_SHAPE[rid] = {k: d['shape'][k] for k in d['shape']}
        REP_SHAPE[rid].update({'file': r['file'], 'port': d['port']})
        d['_s'] = s
        DUPS[rid] = d
    for sg in Z.Z_IDS:
        d = DUPS[f'R_dupQ5_{sg}']
        bh = SER[f'Z_{sg}_BH']['s']
        d['corr_monthly_excess_BH_vs_Q5'] = {'train': corr_excess(bh, d['_s'], None, TE), 'hold': corr_excess(bh, d['_s'], HS, LAST),
                                             'full': corr_excess(bh, d['_s'], None, LAST)}
    dup_series = {rid: d['_s'] for rid, d in DUPS.items()}
    for d in DUPS.values():
        d.pop('_s', None)
    r4 = {rid: d for rid, d in DUPS.items() if rid.startswith('R_dupQ5_')}
    r10 = {rid: d for rid, d in DUPS.items() if rid.startswith('R_dupVWF_') and REPORT[rid]['fam'] == 'R_dup'}
    r9 = {rid: d for rid, d in DUPS.items() if REPORT[rid]['fam'] in ('R_train', 'R_thin')}
    for d in r9.values():
        d['criteria_C1_C6'] = None
        d['grade'] = '報告のみ（格付けしない＝事前登録 R9）'
    r4_c = {k: sum(1 for d in r4.values() if d['criteria_C1_C6'] and d['criteria_C1_C6'][k]) for k in ('C1_train', 'C2_hold_sign', 'C3_hold_t', 'C4_roll20', 'C6_net_cost')}
    r10_c = {k: sum(1 for d in r10.values() if d['criteria_C1_C6'] and d['criteria_C1_C6'][k]) for k in ('C1_train', 'C2_hold_sign', 'C3_hold_t', 'C4_roll20', 'C6_net_cost')}
    r4_all = [rid for rid, d in r4.items() if d['criteria_C1_C6'] and all(d['criteria_C1_C6'][k] for k in ('C1_train', 'C2_hold_sign', 'C6_net_cost'))]
    r10_all = [rid for rid, d in r10.items() if d['criteria_C1_C6'] and all(d['criteria_C1_C6'][k] for k in ('C1_train', 'C2_hold_sign', 'C6_net_cost'))]

    q5chk = q5_vs_intang(dup_series)
    r8 = r8_independent(byid)
    r11 = r11_eknzbh({**r4, **r10})
    pb = program_bonferroni(byid)
    sanity = data_sanity(results, hchk)
    sanity['sha'] = shachk
    sanity['r4_q5_series_vs_intang_R5'] = q5chk
    ph = post_hoc(results, byid, F5, UMD)

    # 丸めで勝ちの数が変わった窓の記録（事前登録どおり丸める前で数えた・nx_common の丸めで数えた場合との違い）
    rounding = []
    for x in results:
        for k in ('roll20_net', 'roll20_gross', 'roll10_net', 'roll10_gross', 'dca20_net', 'dca20_gross'):
            ro = x.get(k)
            if ro and ('wins_nx_common_rounded' in ro or 'win_rate_nx_common_rounded' in ro):
                row = {'where': f"tested.{x['id']}.{k}", 'rounded': ro.get('win_rate_nx_common_rounded'), 'unrounded': ro.get('win_rate'),
                       'windows_changed': ro.get('wins_changed_by_rounding')}
                if k == 'roll20_net':
                    row['C4_if_rounded'] = (ro.get('win_rate_nx_common_rounded') or 0) >= 0.8
                    row['C4_unrounded_used'] = (ro.get('win_rate') or 0) >= 0.8
                rounding.append(row)

    # まとめ
    summ = {}
    for x in results:
        summ.setdefault(x['family'], {}).setdefault(x['grade'], []).append(x['id'])
    headline = []
    for x in results:
        g, n = x['gross'], x['net']
        headline.append({'id': x['id'], 'grade': x.get('grade_label', x['grade']), 'eval_from': x['shape']['eval_from'],
                         'train_ex_ann': (g['train'] or {}).get('ex_ann'), 'train_t': (g['train'] or {}).get('t'),
                         'hold_ex_ann': (g['hold'] or {}).get('ex_ann'), 'hold_t': (g['hold'] or {}).get('t'), 'hold_cagr_diff': (g['hold'] or {}).get('cagr_diff'),
                         'hold_cagr_diff_net': (n['hold'] or {}).get('cagr_diff'), 'full_ex_ann': (g['full'] or {}).get('ex_ann'), 'full_t': (g['full'] or {}).get('t'),
                         'roll20_net': f"{(x['roll20_net'] or {}).get('wins')}/{(x['roll20_net'] or {}).get('windows')}" if x['roll20_net'] else None,
                         'dca20_net_median': (x['dca20_net'] or {}).get('median_ratio'), 'holm_p': x['family_holm_p'],
                         'criteria_passed': [k for k, v in x['criteria'].items() if v is True]})

    deviations = [
        'DelDRC の Holm の入力の片側 p は、全期間の費用前の NW t を丸める前の値から出した（excess_stats の t は小数2桁に丸めた値で、grade_short が中で出す p_one はその丸めた t から出る）。長い歴史の28本の両側 p も excess_stats が丸める前の t から出した p（小数4桁）なので、同じ作法に揃えた。事前登録は「全期間の費用前の NW t の片側 p」とだけ書いている。格付けへの影響は tested の Z_DelDRC_BH の short.p_one_from_unrounded_t と criteria.p_one を並べて見られる',
        'R2 の BL・BM は、BH の評価の月の中で自分の Nlong≥20 かつ ret がある月だけを使った（事前登録に月の規則が無い）。SH は自分の評価の窓（Nlong が初めて20以上・その後20未満を落とす）。報告のみ',
        'R3 の「原論文の標本の外」は before_op（標本の開始の前年まで）・after_op（標本の終わりの翌年から）・outside_op_sample（両方を合わせた月）の3つで出した。報告のみ',
        'R5 の回転 0.5 は、BH は 1.0→0.5、合成 ZC は（脚の平均＋0.10）の全体に 0.5 を掛けた（1.1→0.55）。報告のみ',
        'R7 の FF5+UMD の全期間は FF5 が始まる 1963-07 以降（それより前に始まる規則は短くなる）。回帰は y = s − RF（費用前）。報告のみ',
        'R4・R10 の C4 も丸める前の差で勝ちを数えた（主と同じ）。R_dupQ5 の費用は事前登録どおり eknzbh の置き値（SignalDoc の Portfolio Period 別・速い信号は 6.0）。R_DUP_FAST は事前登録の台帳どおり Z にある3本だけ（eknzbh の速い信号の一覧に R_dupVWF の16本は無いことを確かめた）',
        'R9 の3本（Activism1・Activism2 の BH・Governance の VWforce）と PIN は使える期間の excess_stats だけ。保有期間の月が少ない（6・2・30か月）ものは excess_stats が None を返す（24か月未満）',
        'R8 (a) は作業ツリーの out/nx_leadlag.json（この時点で「測定の途中」とコミットされた版）を読んだ。nx_leadlag の確定版で数字が変わりうる',
        'プログラム全体の Bonferroni の N は、測る時点の作業ツリーにある各角度の事前登録（out/nx_*_prereg.json・まだコミットされていないものも含む＝この実行では nx_gpr）の test_count から数え直した（事前登録の数え方）。結果の JSON の tested の本数も並べた。報告のみ',
        '事後の診断（post_hoc: 保有期間の年ごとの分解・テックの傾きを足した回帰・29本の超過の相関・BH と Q5 の順位の一致・訓練と保有の相関・母集団の粗い代わり〔大型の3組の等分〕・QQQ との比較・OSAP の FF93 の全信号の BH の基礎率〔長い歴史の線と、2002-07〜の短い標本の線〕）は結果を見た後に足した。格付けには使っていない。summary_ja の「勝ちの中身」と「結論」の文はこれを読んで書いた',
        '（逸脱ではない注記）兄弟 nx_osap_intang を import すると、nx_common の statistics が同じ list への mean の答えを覚えるだけの薄い包みに差し替わる（数値は同じ・nx_common.py は書き換えていない）',
        '（逸脱ではない注記）転がる20年窓・10年窓・20年積立は、Nlong<20 で落ちた月を s と b の両方から落として数える nx_common の窓の切り方のまま（主の29本は落ちる月 0）',
    ]

    def ex(rid, per='hold', kind='gross'):
        e = byid[rid][kind].get(per)
        return f"{e['ex_ann']:+.2f}%/年 t{e['t']}" if e else '—'

    def cd(rid, per='hold', kind='net'):
        e = byid[rid][kind].get(per)
        return f"{e['cagr_diff']:+.2f}%/年" if e else '—'

    def ro(rid):
        v = byid[rid]['roll20_net']
        return f"{v['wins']}/{v['windows']}" if v else '—'

    zres = [x for x in results if x['family'] == ZFAM]
    best = sorted(zres, key=lambda x: ({'S': 0, 'A': 1, 'B': 2}.get(x['grade'][0], 3), -((x['gross']['hold'] or {}).get('t') or -99)))
    summary = [
        f"主の族 Z（29本・大型株だけの FF93 型 BH・年1回の組み直し・時価加重・費用 0.30%/年）: " +
        ' / '.join(f"{g}={len(v)}本" for g, v in sorted(summ.get(ZFAM, {}).items())) +
        f"。探索 ZC（3本）: " + ' / '.join(f"{g}={v}" for g, v in sorted(summ.get(ZCFAM, {}).items())),
        '主の族で格付けの良い順の上位5本: ' + '；'.join(
            f"{x['id']} {x['grade']}（訓練 {ex(x['id'], 'train')}・保有 {ex(x['id'])}・費用後の保有の年率差 {cd(x['id'])}・20年窓 {ro(x['id'])}・Holm p={x['family_holm_p']}）"
            for x in best[:5]),
        f"保有期間（2007-2024・費用前）の超過が正の本数: {ph['hold_ex_ann_distribution_Z']['positive']}/{ph['hold_ex_ann_distribution_Z']['n']}（中央 {ph['hold_ex_ann_distribution_Z']['median']}%/年）。"
        f"訓練期間の正: {ph['train_ex_ann_distribution_Z']['positive']}/{ph['train_ex_ann_distribution_Z']['n']}（中央 {ph['train_ex_ann_distribution_Z']['median']}%/年）。"
        f"訓練と保有の超過の相関（規則をまたいで・事後）{ph['train_vs_hold_ex_ann_corr_Z']['corr']}",
        f"プログラム全体の Bonferroni（N={pb['N']}・t*={pb['t_star']}）を越えた規則: 保有 {pb['passing_hold'] or 'なし'}・全期間 {pb['passing_full'] or 'なし'}",
        f"R4 重複の報告（QuintilesVW の05・29本・格付けしない）: C1 {r4_c['C1_train']}・C2 {r4_c['C2_hold_sign']}・C3 {r4_c['C3_hold_t']}・C4 {r4_c['C4_roll20']}・C6 {r4_c['C6_net_cost']} 本。C1∧C2∧C6 {r4_all or 'なし'}。"
        f"R10（VWforce の良い側・16本）: C1 {r10_c['C1_train']}・C2 {r10_c['C2_hold_sign']}・C3 {r10_c['C3_hold_t']}・C4 {r10_c['C4_roll20']}・C6 {r10_c['C6_net_cost']} 本。C1∧C2∧C6 {r10_all or 'なし'}",
    ]
    # 勝ちの中身（事後の診断を読んだ文。格付けは上のまま）
    try:
        dd = byid['Z_DelDRC_BH']
        a7 = dd['R7_factor_alpha']
        tt = ph['tech_tilt_regression']['by_rule']['Z_DelDRC_BH']
        u = ph['universe_proxy']['by_rule']['Z_DelDRC_BH']
        r2d = dd['R2_inside_large']
        br = ph.get('base_rate_ff93_bh', {}).get('short_line_2002_07_to_2024_12', {})
        q = ph.get('vs_QQQ', {}).get('by_rule', {}).get('Z_DelDRC_BH', {})
        summary.append(
            f"唯一の A は Z_DelDRC_BH（前受収益の増加・大型株・短い標本の線 2002-07〜2024-12）: 全期間 {ex('Z_DelDRC_BH', 'full')}（片側 p={dd['criteria']['p_one']}）・前半/後半とも正・"
            f"最大の年（{dd['short']['dropped_year']}年 {dd['short']['dropped_year_excess_pct']:+.2f}%）を抜いても正・費用3倍でも正。ただし族の Holm 後 p={dd['family_holm_p']}（S に届かない）。"
            f"事後の診断: β={dd['gross']['full']['beta']}・CAPM のアルファ 全期間 {a7['full']['capm']['alpha_ann_pct']}%/年 t{a7['full']['capm']['alpha_t']}・"
            f"FF5+勢い 保有 {a7['hold']['ff5_umd']['alpha_ann_pct']}%/年 t{a7['hold']['ff5_umd']['alpha_t']}・テックの傾きを足すと 保有 {tt['hold']['alpha_ann_pct']}%/年 t{tt['hold']['alpha_t']}"
            f"（テックの係数 {tt['hold']['loadings']['tech']}・t{tt['hold']['loading_t']['tech']}）。大型の中の並べ方 BH−BL は保有 {r2d['BH_minus_BL']['hold']['ex_ann']:+.2f}%/年 t{r2d['BH_minus_BL']['hold']['t']}、"
            f"中の組 BM も対 Mkt 保有 {r2d['BM_vs_mkt']['hold']['ex_ann']:+.2f}%/年 t{r2d['BM_vs_mkt']['hold']['t']}、3組の等分（母集団の代わり）は保有 {u['proxy_vs_mkt']['hold']['ex_ann']:+.2f}%/年 t{u['proxy_vs_mkt']['hold']['t']}"
            f"＝勝ちの大半は『前受収益を持つ大型株（ソフトウェア・テック寄り）に居ること』とβで、前受収益の増加で並べたことの上乗せは小さい。"
            + (f"QQQ と同じ月で比べると 費用後 {q['net_vs_qqq']['overlap']['ex_ann']:+.2f}%/年 t{q['net_vs_qqq']['overlap']['t']}・幾何 {q['net_vs_qqq']['overlap']['cagr_diff']:+.2f}%/年。" if q.get('net_vs_qqq', {}).get('overlap') else '')
            + (f"基礎率（事後）: OSAP の FF93 の全信号の BH を同じ窓・同じ短い標本の線に当てると {br.get('n')} 本中 A {br.get('counts', {}).get('A', 0)}・S {br.get('counts', {}).get('S', 0)}・B {br.get('counts', {}).get('B', 0)}・C {br.get('counts', {}).get('C', 0)}（β の中央 全体 {br.get('beta_median_all')}・A/S {br.get('beta_median_A_S')}）" if br else ''))
        bt, ca = byid['Z_BetaTailRisk_BH'], byid['Z_ChAssetTurnover_BH']
        bl = ph.get('base_rate_ff93_bh', {}).get('long_line', {})
        summary.append(
            f"B の2本: BetaTailRisk（裾のリスクのβ）は訓練 {ex('Z_BetaTailRisk_BH', 'train')}・保有 {ex('Z_BetaTailRisk_BH')} だが市場のβ {bt['gross']['full']['beta']}・"
            f"CAPM のアルファ 全期間 {bt['R7_factor_alpha']['full']['capm']['alpha_ann_pct']}%/年 t{bt['R7_factor_alpha']['full']['capm']['alpha_t']}・シャープは訓練 {bt['sharpe']['train']['s_net']} 対 {bt['sharpe']['train']['mkt_same_months']}、保有 {bt['sharpe']['hold']['s_net']} 対 {bt['sharpe']['hold']['mkt_same_months']}（市場より低い）"
            f"＝市場より多く上下するだけの勝ち。ChAssetTurnover（資産回転率の改善）は訓練 {ex('Z_ChAssetTurnover_BH', 'train')}・20年窓 {ro('Z_ChAssetTurnover_BH')} だが保有 {ex('Z_ChAssetTurnover_BH')}（C3 不合格）・保有の前半 2007-2015 は "
            f"{ca['gross']['hold_2007_2015']['ex_ann']:+.2f}%/年・単価 0.60% では C6 も落ちる"
            + (f"。基礎率（事後）: FF93 の全信号の BH を長い歴史の線に当てると {bl.get('n')} 本中 " + '・'.join(f"{g} {v}" for g, v in bl.get('counts', {}).items()) if bl else ''))
        summary.append(
            f"独立の答え合わせ: R11 eknzbh（mw_oap_signals）の同じ組 {r11['ex_ann_abs_diff']['n']} 箇所の超過の差は最大 {r11['ex_ann_abs_diff']['max']}＝別のコードで同じ数字（再現の誤差 0）。"
            f"R8 つながりの信号の保有（費用前）: " + '・'.join(f"{rid.replace('Z_', '').replace('_BH', '')} {ex(rid)}" for rid in ('Z_CustomerMomentum_BH', 'Z_iomom_cust_BH', 'Z_iomom_supp_BH', 'Z_IndRetBig_BH', 'Z_EarnSupBig_BH', 'Z_retConglomerate_BH', 'ZC2_LINKS'))
            + f"（nx_leadlag の主の5本の保有: " + '・'.join(f"{k} {v['hold_ex_ann']:+.2f}" for k, v in r8['a_nx_leadlag']['nx_leadlag_primary_hold'].items() if isinstance(v, dict) and v.get('hold_ex_ann') is not None) + '）。'
            f"受注残は main と逆の向き（少ない側＝BH）が保有 {ex('Z_OrderBacklog_BH')} だが訓練 {ex('Z_OrderBacklog_BH', 'train')}（C1 不合格）、main と同じ向きの BL は保有 {byid['Z_OrderBacklog_BH']['R2_inside_large']['BL_vs_mkt']['hold']['ex_ann']:+.2f}%/年")
        summary.append('結論: 線（C1〜C8・短い標本の線）は動かしていない。長い歴史の線で A・S は0本。短い標本の線で DelDRC が A（勝ち）になったが、Holm と Bonferroni は通らず、事後の診断ではβとテックの傾きと母集団で説明がつく——「前受収益の増加で選ぶ」ことの独自の上乗せとは言えない')
    except Exception as e:  # noqa
        summary.append(f'（勝ちの中身の文を作れなかった: {e}）')

    obj = {
        'generated': datetime.date.today().isoformat(),
        'angle': 'nx_osap_zoo（OSAP の残りの予言変数29本の良い側を、大型株だけ・年1回の組み直し・時価加重〔FF93 型の BH〕で買って持つ）',
        'prereg': {'path': 'out/nx_osap_zoo_prereg.json', 'commit': git_sha(PREREG_PATH), 'global': 'out/nx_prereg.json'},
        'script': 'night/nx_osap_zoo.py',
        'data_tool': {'path': 'night/nx_osap_zoo_data.py', 'commit': git_sha(os.path.join(BASE, 'night', 'nx_osap_zoo_data.py')),
                      'ports': 'out/_nx_cache/nx_osap_zoo_ports.json（gitignore）', 'extract_sha256': X['extract_sha256'], 'rules_sha256': X['rules_sha256'],
                      'class_sha256': X['class_sha256']},
        'reused_from_sibling': {'module': 'night/nx_osap_intang.py', 'commit': git_sha(os.path.join(BASE, 'night', 'nx_osap_intang.py')),
                                'functions': ['rolling_x（C4・丸める前の差で勝ちを数える）', 'dca_x', 'size_halves（R1・R2 の大型/小型の半分）', 'ols_nw（R7）', 'filt（確かめ10 のみ）', '_ro_brief'],
                                'nx_common_rolling_rounding_fix_central': '入っていない（nx_common.rolling / dca は今も丸めてから数える）→ 兄弟の rolling_x / dca_x を使った'},
        'stance': '測定器。門・採点・配分には入れない。線（C1〜C8・短い標本の線）は結果を見て動かしていない。負けた規則も全部 tested に残す',
        'benchmark': 'French Mkt（Mkt-RF + RF・総リターン・上限なしの時価加重）。2024-12 まで（OSAP の終わり）',
        'conventions': {'C1_C2_C3_C7': '費用前（s 対 Mkt）', 'C4_C6': '費用後（s_net 対 Mkt）。C4 は毎年7月起点の転がる20年窓・一括・丸める前の差 > 0 で勝ち',
                        'C5': 'N/A（事前登録）', 'C8': 'N/A（買いだけ・借入なし・時期選びなし）',
                        'cost': 'BH は回転 1.0（上限）× 0.30%＝年 0.30%。ZC は（1.0＋0.10）× 0.30%＝年 0.33%。毎月 1/12 を引く',
                        'grading': '長い歴史 28本＋ZC 3本＝nx_common.grade()（criteria_long_history）。DelDRC＝nx_common.grade_short()（criteria_short_sample・代用2つ）'},
        'summary_ja': summary,
        'data_sanity': sanity,
        'deviations_from_prereg': deviations,
        'rounding_record': {'what': 'nx_common の丸めた数え方と、事前登録どおりの丸める前の数え方で勝ちの数が食い違った窓（空なら違いなし）', 'rows': rounding,
                            'C4_changed_by_rounding': [r['where'] for r in rounding if 'C4_if_rounded' in r and r['C4_if_rounded'] != r['C4_unrounded_used']]},
        'holm': holm,
        'grade_summary': summ,
        'headline': headline,
        'tested_count': {'graded': len(results), 'Z': sum(1 for x in results if x['family'] == ZFAM), 'ZC': sum(1 for x in results if x['family'] == ZCFAM),
                         'prereg_total_graded': PR['test_count']['total_graded']},
        'tested': results,
        'reports': {
            'R1_big_half_benchmark': 'tested の各規則の R1_vs_big_half（French の ME 十分位の6〜10を時価で合わせた大型の半分）',
            'R2_inside_large': 'tested の単一の信号の規則の R2_inside_large（BL・BM・BH−BL・OSAP の LS・SH 対 小型の半分）',
            'R3_subperiods': 'tested の各規則の gross/net の recent・hold_2007_2015・hold_2016_2024・post_pub・op_sample・before_op・after_op・outside_op_sample',
            'R4_duplicate_Q5': {'what': PR['families']['R_report_only']['R4_duplicate_Q5'], 'count_passed': r4_c, 'C1_C2_C6_all': r4_all, 'rules': r4},
            'R5_cost_sensitivity': 'tested の各規則の R5_cost_sensitivity',
            'R6_other_metrics': 'tested の各規則の sharpe・maxdd・R6_other・dca20_net/gross・roll10_net/gross',
            'R7_factor_alpha': 'tested の各規則の R7_factor_alpha',
            'R8_independent_checks': r8,
            'R9_train_or_thin': {'what': PR['families']['R_report_only']['R9_train_or_thin'], 'rules': r9},
            'R10_duplicate_discrete': {'what': PR['families']['R_report_only']['R10_duplicate_discrete'], 'count_passed': r10_c, 'C1_C2_C6_all': r10_all, 'rules': r10},
            'R11_crosscheck_eknzbh': r11,
        },
        'program_bonferroni': pb,
        'post_hoc': ph,
        'known_limits': PR['known_limits'],
        'seconds': round((datetime.datetime.now() - t0).total_seconds(), 1),
    }
    p = N.save(OUTNAME, obj)
    print('書いた:', p)
    print('格付け:', json.dumps(summ, ensure_ascii=False))
    for h in headline:
        print(json.dumps(h, ensure_ascii=False))
    print('R4:', r4_c, r4_all)
    print('R10:', r10_c, r10_all)
    print('Bonferroni:', pb['N'], pb['t_star'], pb['passing_hold'], pb['passing_full'])
    return obj


if __name__ == '__main__':
    main()
