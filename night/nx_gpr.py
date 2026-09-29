#!/usr/bin/env python3
"""night/nx_gpr.py — 角度 nx_gpr（地政学リスク指数が跳ねた後の6か月だけ株を厚く持つ）を事前登録どおりに測る
（読むだけ・門の判定には不使用）

問い: Caldara & Iacoviello (2022, AER) の歴史の地政学リスク指数 GPRH（米国の3紙・1900〜）が
      (a) 前12か月の平均からの対数の跳ねが 1900年からの拡大窓の上位10%、または (b) 水準が直近240か月の上位10% に
      なったと月初の公表（1か月遅れ）で分かった後の6か月だけ株を厚く持つ規則——借入で 1.0→1.5倍（P1・P2）／
      現金2割を投じて 0.8→1.0（P3・P4）／積立の予備金の投入（D1・D2）——は、French Mkt に訓練（1926-07〜2006-12）でも
      保有（2007-01〜2026-08）でも費用後に勝ち、シャープでも上回るか。国別の GPRC で米国外43か国に当てても効くか（C5）。
事前登録: out/nx_gpr_prereg.json（commit 7f6db45f・測る前）。線は out/nx_prereg.json（C1〜C8・S/A/B/C）。
データ: night/nx_gpr_data.py を import する（写さない）。信号 out/_nx_cache/nx_gpr_signals.json の signals_sha256・
        rules_sha256・データ道具の sha256・GPR の xls の sha256 を最初に確かめ、違えば止まる。--selftest も最初に走らせる。
出力: out/nx_gpr.json（tested に 主4・探索12・積立2 の全規則＝負けも残す。対照・報告も tested に要約を残す）

約束（事前登録どおり）
- 格付けは nx_common.grade（長い歴史の線）。C1・C2・C3・C7 は費用前（借入の上乗せ金利は引いた後・売買の費用の前）、
  C4・C6・C8 は費用後（売買の費用 片道 0.10%）。C8（訓練・保有の両方でシャープが Mkt を上回る）は全規則で必須。
- C4（転がる20年窓）と20年積立の勝ちは**丸める前の差**で数える（nx_common.rolling / dca は小数2桁・3桁に丸めてから
  数えるので 0〜0.005%/年の小さな勝ちが負けに数えられる）。丸めた数え方の結果も併記する。
- Holm（C7）の元の p は丸める前の NW t から p_two（事前登録『p_two(NW t)』の文字どおり）。丸めた p の Holm も併記。
- C5 の『正の国』は丸める前の幾何の年率差 > 0 で数える（丸めた数え方も併記）。
- 結果を見た後の分析は post_hoc に置き『事後』と明記し、格付けには使わない。
"""
import sys, os, json, math, hashlib, subprocess, datetime, random, statistics as _stat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_gpr_data as D  # noqa: E402
import numpy as np  # noqa: E402


class _StatShim:
    """速さだけの細工（数値は1ビットも変えない。nx_sentcond.py・nx_stack.py と同じ）: nx_common.excess_stats は β の和の中で
    S.mean(sv)・S.mean(bv) を要素ごとに計算し直す（O(n²)・分数の厳密計算）。同じ list への mean の答えを覚えて返す。
    nx_common.py 自体は書き換えない（他の角度と同じ物差しを保つ）"""

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


N.S = _StatShim()

BASE = N.BASE
PREREG_PATH = os.path.join(BASE, 'out', 'nx_gpr_prereg.json')
PR = json.load(open(PREREG_PATH))
OUTNAME = 'nx_gpr.json'
TE, HS = N.TRAIN_END, N.HOLD_START
FULL_A, FULL_Z = D.FULL
add, months = D.add, D.months
SPREAD, TRADE = D.COSTS['spread'], D.COSTS['trade']
P_RULES = [k for k, v in D.RULES.items() if v['family'] == 'P']
E_RULES = [k for k, v in D.RULES.items() if v['family'] == 'E']
D_RULES = [k for k, v in D.RULES.items() if v['family'] == 'D']


def _hex64(s):
    return s.strip()[:64]


def sha_file(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def git(*a):
    try:
        return subprocess.check_output(['git', '-C', BASE] + list(a), stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa
        return None


# ───────────────────────── 最初に確かめる（結果を見てから作り直していない証明） ─────────────────────────
EXP = {k: _hex64(PR['tools'][k]) for k in ('data_tool_sha256', 'rules_sha256', 'signals_sha256', 'gpr_file_sha256')}
if sha_file(D.__file__) != EXP['data_tool_sha256']:
    sys.exit(f'止まる: night/nx_gpr_data.py の sha256 {sha_file(D.__file__)} が事前登録 {EXP["data_tool_sha256"]} と違う')
if D.rules_sha() != EXP['rules_sha256']:
    sys.exit(f'止まる: rules_sha256 {D.rules_sha()} が事前登録と違う')
SIGF = json.load(open(D.OUT))
if SIGF['signals_sha256'] != EXP['signals_sha256'] or D.signals_sha(SIGF['signals']) != EXP['signals_sha256']:
    sys.exit('止まる: 信号の signals_sha256 が事前登録と違う')
if not D.selftest():
    sys.exit('止まる: nx_gpr_data.py --selftest が NG')
COLS, LABELS, GPR_SHA = D.load_gpr()
if GPR_SHA != EXP['gpr_file_sha256']:
    sys.exit(f'止まる: GPR の xls の sha256 {GPR_SHA} が事前登録と違う')
SIGS = SIGF['signals']


def on_from(m):
    return {int(k): bool(v) for k, v in m.items()}


# ───────────────────────── 市場 ─────────────────────────
FF = N.ff_factors()
MKT = N.window(FF['mkt'], FULL_A, FULL_Z)
RF = N.window(FF['rf'], FULL_A, FULL_Z)
MKTRF = N.window(FF['mktrf'], FULL_A, FULL_Z)

ON = {rk: on_from(SIGS[rk]['off1']) for rk in D.RULES if rk != 'E10_resid'}
ON2 = {rk: on_from(SIGS[rk]['off2_pre1926']) for rk in D.RULES if rk != 'E10_resid'}
ON['E10_resid'] = D.rule_on('E10_resid', COLS, off=1, mkt=FF['mkt'])   # 市場のリターンを使うので測る道具の側で作る（定義は D.resid_spike_decisions）


def sim(on, w_on, w_off, r=None, rf=None, spread=SPREAD, trade=TRADE):
    r = MKT if r is None else r
    rf = RF if rf is None else rf
    return D.timing_returns(D.weights(on, w_on, w_off), r, rf, spread, trade)


# ───────────────────────── 物差し ─────────────────────────
def rolling_exact(s, b, years=20, start_month=7, per_year=12):
    """nx_common.rolling と同じ窓・同じ出力の形。勝ちは丸める前の gs−gb > 0 で数える（nx_leadlag.rolling_exact と同じ直し方）。
    nx_common の数え方（小数2桁の%に丸めてから >0）の結果も wins_nx_common_rounded に併記"""
    ks = sorted(set(s) & set(b))
    if not ks:
        return None
    raw = []
    y0 = ks[0] // 100
    last = ks[-1]
    for y in range(y0, 2100):
        a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * per_year * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        raw.append((y, gs - gb))
    if not raw:
        return None
    wins = sum(1 for _, c in raw if c > 0)
    wins_r = sum(1 for _, c in raw if round(c * 100, 2) > 0)
    v = sorted(c for _, c in raw)
    wy, wc = min(raw, key=lambda x: x[1])
    by, bc = max(raw, key=lambda x: x[1])
    return {'windows': len(raw), 'wins': wins, 'win_rate': round(wins / len(raw), 3),
            'median': round(v[len(v) // 2] * 100, 2), 'worst': (wy, round(wc * 100, 2)), 'best': (by, round(bc * 100, 2)),
            'wins_nx_common_rounded': wins_r, 'win_rate_nx_common_rounded': round(wins_r / len(raw), 3)}


def dca_exact(s, b, years=20, step=12):
    """nx_common.dca と同じ窓・同じ出力の形。勝ち（倍率>1）は丸める前の倍率で数える"""
    ks = sorted(set(s) & set(b))
    n = years * 12
    raw = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        raw.append((w[0], ws / wb))
    if not raw:
        return None
    v = sorted(r for _, r in raw)
    wy, wr = min(raw, key=lambda x: x[1])
    by, br = max(raw, key=lambda x: x[1])
    wins = sum(1 for r in v if r > 1)
    wins_r = sum(1 for r in v if round(r, 3) > 1)
    return {'windows': len(raw), 'win_rate': round(wins / len(raw), 3), 'median_ratio': round(v[len(v) // 2], 3),
            'worst': (wy, round(wr, 3)), 'best': (by, round(br, 3)), 'win_rate_nx_common_rounded': round(wins_r / len(raw), 3)}


def exact(g, b, a=None, z=None):
    """丸める前の（NW t・算術平均の差×12・幾何の年率差）"""
    ks = sorted(k for k in set(g) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = [g[k] - b[k] for k in ks]
    t = N.nw_t(ex)
    return {'t': t, 'p_two': N.p_two(t), 'ex_ann': math.fsum(ex) / len(ks) * 12,
            'cagr_diff': cagr_safe([g[k] for k in ks]) - cagr_safe([b[k] for k in ks]), 'n': len(ks)}


def cagr_safe(x):
    """N.cagr と同じ。ただし月の損が −100% 以上（借入の規則で資産が0以下になる月）があれば、その月で資産が尽きた＝幾何の年率 −100%"""
    x = list(x)
    if any(v <= -1 for v in x):
        return -1.0
    return N.cagr(x)


def es(s, b, a=None, z=None):
    """N.excess_stats をそのまま使う。ただし規則の月の損が −100% 以上の月（借入 1.5倍で国の市場が −66.7% を超えて下げた月:
    VEN 2018 など）が窓にあると N.cagr の対数が作れないので、その場合だけ:
      幾何（cagr_s）は −100%（その月で資産が尽きた・証拠金の追加や強制決済は事前登録の模型の外）、cagr_diff = −100 − cagr_b、
      算術の超過（ex_ann）と NW t・p は元の（切らない）差から計算し直し、ほかの欄（te・ir・β・vol）は −100% 以上の月を
      −99.9999999% に切った列で N.excess_stats が出した値（wiped_out に月を名指し）"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    bad = [k for k in ks if s[k] <= -1]
    if not bad:
        return N.excess_stats(s, b, a, z)
    s2 = {k: (v if v > -1 else -0.999999999) for k, v in s.items()}
    st = N.excess_stats(s2, b, a, z)
    if st is None:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = N.nw_t(ex)
    st['ex_ann'] = round(math.fsum(ex) / len(ex) * 12 * 100, 2)
    st['t'] = round(t, 2) if t is not None else None
    st['p'] = round(N.p_two(t), 4) if t is not None else None
    st['cagr_s'] = -100.0
    st['cagr_diff'] = round(-100.0 - st['cagr_b'], 2)
    st['wiped_out'] = bad
    return st


def shp(r, a=None, z=None, rf=None):
    return N.sharpe(r, RF if rf is None else rf, a, z)


def mdd(r, a=None, z=None):
    w = N.window(r, a, z)
    return round(N.maxdd(w) * 100, 1) if w else None


PER_MAIN = [('full', None, None), ('train', None, TE), ('hold', HS, None)]
PER_R4 = [('recent_2013_07', D.RECENT, None), ('post_wp_2018_03', D.POSTPUB_WP, None),
          ('post_lexicon_2021_11', D.POST_LEXICON, None), ('post_aer_2022_05', D.POSTPUB_AER, None)]


def evaluate(g, n, tv, bench=None, rf=None, periods=PER_MAIN + PER_R4, dca=True):
    bench = MKT if bench is None else bench
    rf = RF if rf is None else rf
    ks = sorted(g)
    a0, z0 = ks[0], ks[-1]
    b = {k: bench[k] for k in ks if k in bench}
    out = {'span': [a0, z0], 'months': len(ks)}
    out['gross'] = {p: es(g, b, a, z) for p, a, z in periods}
    out['net'] = {p: es(n, b, a, z) for p, a, z in periods}
    out['exact_gross'] = {p: exact(g, b, a, z) for p, a, z in PER_MAIN}
    out['exact_net_hold'] = exact(n, b, HS)
    out['sharpe'] = {p: {'rule_net': shp(n, a, z, rf), 'rule_gross': shp(g, a, z, rf), 'mkt': shp(b, a, z, rf)} for p, a, z in PER_MAIN}
    out['roll20_net'] = rolling_exact(n, b)
    out['roll20_gross'] = rolling_exact(g, b)
    if dca:
        out['dca20_net'] = dca_exact(n, b, 20)
        out['dca20_gross'] = dca_exact(g, b, 20)
    out['maxdd_pct'] = {p: {'rule_gross': mdd(g, a, z), 'rule_net': mdd(n, a, z), 'mkt': mdd(b, a, z)} for p, a, z in PER_MAIN}
    tvs = [tv[k] for k in ks]
    out['turnover'] = {'oneway_per_year': round(float(np.mean(tvs)) * 12, 3), 'trade_cost_per_oneway': TRADE, 'borrow_spread': SPREAD,
                       'cost_drag_pct_per_year': round(float(np.mean(tvs)) * 12 * TRADE * 100, 3)}
    return out


def on_count(on, ks):
    out = {}
    for p, a, z in PER_MAIN + PER_R4:
        d = [m for m in ks if (a is None or m >= a) and (z is None or m <= z)]
        o = [m for m in d if on.get(m)]
        ep = sum(1 for m in o if not on.get(add(m, -1), False))
        out[p] = {'months': len(d), 'on': len(o), 'episodes': ep}
    return out


def rule_text(rid):
    fam = D.RULES[rid]['family']
    src = {'P': 'P_primary', 'E': 'E_exploratory', 'D': 'D_dca'}[fam]
    return PR['families'][src].get(rid)


# ───────────────────────── 主・探索の規則 ─────────────────────────
SER = {}


def rule_entry(rid):
    r = D.RULES[rid]
    on = ON[rid]
    g, n, tv = sim(on, r['w_on'], r['w_off'])
    SER[rid] = (g, n, tv)
    e = {'id': rid, 'family': r['family'], 'kind': 'graded_rule', 'exploratory': r['family'] == 'E', 'text': rule_text(rid),
         'spec': {'sig': list(r['sig']) if isinstance(r['sig'], tuple) else r['sig'], 'H': r['H'], 'w_on': r['w_on'], 'w_off': r['w_off'],
                  'signal_def': ({s: D.SIG[s] for s in r['sig']} if isinstance(r['sig'], tuple) else D.SIG[r['sig']]),
                  'spread': SPREAD, 'trade_cost': TRADE}}
    e.update(evaluate(g, n, tv))
    e['on_months'] = on_count(on, sorted(g))
    wd = D.weights(on, r['w_on'], r['w_off'])
    wv = [wd[m] for m in sorted(g)]
    e['avg_equity_weight'] = {'full': round(float(np.mean(wv)), 4),
                              'train': round(float(np.mean([x for m, x in zip(sorted(g), wv) if m <= TE])), 4),
                              'hold': round(float(np.mean([x for m, x in zip(sorted(g), wv) if m >= HS])), 4)}
    return e


# ───────────────────────── C5（米国外43か国・国の GPRC・P 族だけ） ─────────────────────────
JKP = {c: D.jkp_country_mkt(c) for c in D.NON_US + ['USA']}


def country_tr(c):
    ex = JKP[c] or {}
    return {m: ex[m] + RF[m] for m in ex if m in RF and m <= D.C5_END}


def country_on(c, sk):
    return {m: v for m, v in on_from(SIGS['_country_GPRC'][c][sk]).items() if m <= D.C5_END}


def eval_simple(g, n, bench, rf=None, halves=True):
    ks = sorted(g)
    b = {k: bench[k] for k in ks}
    x = exact(g, b)
    o = {'months': len(ks), 'span': [ks[0], ks[-1]] if ks else None,
         'gross': es(g, b), 'net': es(n, b),
         'cagr_diff_exact_pct': round(x['cagr_diff'] * 100, 4) if x else None,
         'sharpe_rule_net_vs_mkt': [shp(n, rf=rf or RF), shp(b, rf=rf or RF)]}
    if halves and len(ks) >= 48:
        mid = ks[len(ks) // 2]
        o['first_half'] = es(g, b, z=add(mid, -1))
        o['second_half'] = es(g, b, a=mid)
    return o


def c5_rule(rk, signal='country', month_set=None):
    """signal: 'country'（国の GPRC＝C5 の本体）／'global'（全体の GPRH＝R7）／'hist'（国の歴史版 GPRHC＝R8）。
    month_set: {国: 月の集合} を渡すとその月だけで測る（R7・R8 を C5 と同じ月にそろえる）"""
    r = D.RULES[rk]
    sk = r['sig']
    per = {}
    for c in D.NON_US + ['USA']:
        tr = country_tr(c)
        if not tr:
            per[c] = None
            continue
        if signal == 'country':
            on = country_on(c, sk)
        elif signal == 'global':
            on = ON[rk]
        else:
            on = HIST_ON[c][sk]
        on = {m: v for m, v in on.items() if m <= D.C5_END}
        if month_set is not None:
            on = {m: v for m, v in on.items() if m in month_set.get(c, ())}
        g, n, tv = sim(on, r['w_on'], r['w_off'], r=tr)
        if len(g) < 24:
            per[c] = {'months': len(g)}
            continue
        per[c] = eval_simple(g, n, tr, halves=False)
    counted = [c for c in D.NON_US if per.get(c) and per[c]['months'] >= D.C5_MIN_MONTHS]
    pos = [c for c in counted if per[c]['cagr_diff_exact_pct'] > 0]
    pos_r = [c for c in counted if per[c]['gross']['cagr_diff'] > 0]
    return {'rule': rk, 'signal': signal, 'regions': len(counted), 'positive': len(pos), 'share': round(len(pos) / len(counted), 3) if counted else None,
            'pass_2_3': (len(pos) / len(counted) >= 2 / 3) if counted else None, 'positive_rounded_count': len(pos_r),
            'positive_countries': pos, 'negative_countries': [c for c in counted if c not in pos],
            'median_cagr_diff_pct': round(float(np.median([per[c]['cagr_diff_exact_pct'] for c in counted])), 3) if counted else None,
            'mean_cagr_diff_pct': round(float(np.mean([per[c]['cagr_diff_exact_pct'] for c in counted])), 3) if counted else None,
            'per_country': {c: ({'months': v['months'], 'cagr_diff_exact_pct': v['cagr_diff_exact_pct'], 'ex_ann': v['gross']['ex_ann'], 't': v['gross']['t'],
                                 'net_cagr_diff': v['net']['cagr_diff'], 'sharpe_rule_net_vs_mkt': v['sharpe_rule_net_vs_mkt'], 'span': v['span'],
                                 'wiped_out_months': v['gross'].get('wiped_out')}
                                if v and 'gross' in v else v) for c, v in per.items()},
            'USA_report_only': per.get('USA') and {k: per['USA'][k] for k in ('months', 'cagr_diff_exact_pct', 'span')}}


HIST_ON = {}


def build_hist_on():
    for c in D.NON_US + ['USA']:
        G = COLS['GPRHC_' + c]
        HIST_ON[c] = {}
        for sk in ('jump', 'level240'):
            s = D.SIG[sk]
            dec = D.spike_decisions(G, s['kind'], s['lag'], s['thr'], s['min_n'], s['window'], D.COUNTRY_CFRAC if s['kind'] == 'jump' else 0.0)
            HIST_ON[c][sk] = D.on_state(dec, 6, 1)


# ───────────────────────── 積立の族 D ─────────────────────────
def dca_reserve_exact(on, r, rf, years=20, step=12, share_off=0.8):
    """D.dca_reserve と同じ帳簿（写しではなく、丸める前の比と窓の終わりの予備金を取るための検算器）。
    すべての窓で round(比,4) が D.dca_reserve と一致することを assert してから使う"""
    ks = sorted(m for m in on if m in r and m in rf)
    n = years * 12
    out = []
    i = 0
    while i + n <= len(ks):
        w = ks[i:i + n]
        if add(w[0], n - 1) != w[-1]:
            i += step
            continue
        Eb = Er = Rv = 0.0
        for m in w:
            Eb = (Eb + 1.0) * (1 + r[m])
            if on[m]:
                Er = (Er + 1.0 + Rv) * (1 + r[m])
                Rv = 0.0
            else:
                Er = (Er + share_off) * (1 + r[m])
                Rv = (Rv + (1.0 - share_off)) * (1 + rf[m])
        out.append((w[0], (Er + Rv) / Eb, Rv))
        i += step
    return out


def dca_block(on, r, rf, years, step=12, train_end=None):
    rows = D.dca_reserve(on, r, rf, years=years, step=step)
    ex = dca_reserve_exact(on, r, rf, years=years, step=step)
    assert [x[0] for x in rows] == [x[0] for x in ex], 'dca の窓の並びが違う'
    for a, b in zip(rows, ex):
        assert abs(a[1] - round(b[1], 4)) < 1e-12, ('dca の比が D.dca_reserve と違う', a, b)
    if train_end is not None:
        keep = [i for i, x in enumerate(rows) if add(x[0], years * 12 - 1) <= train_end]
        rows = [rows[i] for i in keep]
        ex = [ex[i] for i in keep]
    if not rows:
        return None
    v = sorted(x[1] for x in ex)
    n = len(v)
    med_upper = v[n // 2]
    med_conv = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    s = D.dca_summary(rows)
    s.update({'win_rate_exact': round(sum(1 for x in v if x > 1) / n, 3), 'wins_exact': sum(1 for x in v if x > 1),
              'median_ratio_exact_upper': round(med_upper, 5), 'median_ratio_exact_conventional': round(med_conv, 5),
              'windows_ending_with_reserve_share': round(sum(1 for x in ex if x[2] > 1e-12) / n, 3),
              'deploys_median': sorted(x[3] for x in rows)[n // 2], 'deploys_min_max': [min(x[3] for x in rows), max(x[3] for x in rows)],
              'rows': [[x[0], round(e[1], 5), x[2], x[3], round(e[2], 3)] for x, e in zip(rows, ex)],
              'rows_cols': ['窓の始まり', '比（丸める前・小数5桁）', '予備金の最大（月の拠出の何か月分）', '予備金を投じた回数', '窓の終わりに残った予備金']})
    return s


def d_entry(rid, rf_for_reserve=None, label=None):
    r = D.RULES[rid]
    base_rule = {'D1_dca_jump': 'P1_lev_jump', 'D2_dca_level': 'P2_lev_level'}[rid]
    on = ON[base_rule]
    rfr = RF if rf_for_reserve is None else rf_for_reserve
    full = dca_block(on, MKT, rfr, 20)
    train = dca_block(on, MKT, rfr, 20, train_end=TE)
    on_h = {m: v for m, v in on.items() if HS <= m <= FULL_Z}
    hold = dca_block(on_h, N.window(MKT, HS), N.window(rfr, HS), 10)
    line = {'D_C4': bool(full and full['win_rate_exact'] >= 0.8),
            'D_C1': bool(train and train['median_ratio_exact_upper'] > 1),
            'D_C2': bool(hold and hold['median_ratio_exact_upper'] > 1)}
    line_conv = {'D_C1_conventional_median': bool(train and train['median_ratio_exact_conventional'] > 1),
                 'D_C2_conventional_median': bool(hold and hold['median_ratio_exact_conventional'] > 1)}
    e = {'id': rid if label is None else f'{rid}_{label}', 'family': 'D', 'kind': 'dca_rule' if label is None else 'report', 'text': rule_text(rid),
         'spec': {'on_same_as': base_rule, 'share_off': r['share_off'], 'H': r['H'], 'reserve_rate': 'French RF' if rf_for_reserve is None else 'ゼロ（R13）'},
         'full_20y_81': full, 'train_20y_end_le_2006': train, 'hold_10y_from_2007': hold,
         'dca_line': line, 'dca_line_pass': all(line.values()), 'dca_line_conventional_median_check': line_conv,
         'median_rule': '中央値は D.dca_summary と同じ v[n//2]（窓が偶数なら上の中央値）。普通の中央値（真ん中2つの平均）も併記'}
    return e


# ───────────────────────── 対照（報告のみ） ─────────────────────────
def ctrl_const(rules=None):
    out = {}
    for rk in (rules or P_RULES):
        r = D.RULES[rk]
        g, n, tv = SER[rk]
        w = D.weights(ON[rk], r['w_on'], r['w_off'])
        wbar = float(np.mean([w[m] for m in sorted(g) if m <= TE]))
        cg, cn, ctv = D.timing_returns({m: wbar for m in g}, MKT, RF, SPREAD, TRADE)
        out[rk] = {'w_bar_train': round(wbar, 5),
                   'const_vs_mkt_gross': {p: es(cg, MKT, a, z) for p, a, z in PER_MAIN},
                   'const_vs_mkt_net': {p: es(cn, MKT, a, z) for p, a, z in PER_MAIN},
                   'rule_minus_const_gross': {p: es(g, cg, a, z) for p, a, z in PER_MAIN},
                   'rule_minus_const_net': {p: es(n, cn, a, z) for p, a, z in PER_MAIN},
                   'sharpe_const_net': {p: shp(cn, a, z) for p, a, z in PER_MAIN},
                   'sharpe_rule_net': {p: shp(n, a, z) for p, a, z in PER_MAIN},
                   'note': '規則 − CTRL_const ＝時期の当たり外れの分（同じ平均の株の割合をいつも持つ対照に対する超過）'}
    return out


def ctrl_placebo(rules=None):
    out = {}
    for rk in (rules or P_RULES):
        r = D.RULES[rk]
        L = sorted(SER[rk][0])          # 規則の持つ月（P 族は French の全月・E10 は 1937-07〜）
        n = len(L)
        seq = [ON[rk][m] for m in L]

        def exs(g):
            d = [g[m] - MKT[m] for m in L]
            f = math.fsum(d) / n * 12 * 100
            it = [x for m, x in zip(L, d) if m <= TE]
            ih = [x for m, x in zip(L, d) if m >= HS]
            return f, math.fsum(it) / len(it) * 12 * 100, math.fsum(ih) / len(ih) * 12 * 100

        rg = SER[rk][0]
        actual = exs(rg)
        dist = {'full': [], 'train': [], 'hold': []}
        for k in range(12, n - 12 + 1):
            onk = {L[i]: seq[(i - k) % n] for i in range(n)}
            g, _, _ = sim(onk, r['w_on'], r['w_off'])
            f, t_, h = exs(g)
            dist['full'].append(f); dist['train'].append(t_); dist['hold'].append(h)
        res = {'shifts': len(dist['full']), 'k_range': [12, n - 12]}
        for i, p in enumerate(('full', 'train', 'hold')):
            v = sorted(dist[p])
            a = actual[i]
            pct = (sum(1 for x in v if x < a) + 0.5 * sum(1 for x in v if x == a)) / len(v)
            res[p] = {'rule_ex_ann_pct': round(a, 3), 'percentile_in_placebo': round(pct, 3),
                      'placebo_q05_q50_q95': [round(v[int(0.05 * len(v))], 3), round(v[len(v) // 2], 3), round(v[int(0.95 * len(v)) - 1], 3)]}
        out[rk] = res
    return out


def ctrl_dip():
    P = D.pct_series(MKT, min_n=120, window=None)
    dec = {m: (p <= 0.10) for m, p in P.items()}   # 判断の月 t の市場のリターンは t 月末に分かる
    on = D.on_state(dec, 6, 1)
    g, n, tv = sim(on, 1.5, 1.0)
    e = evaluate(g, n, tv, periods=PER_MAIN, dca=False)
    e['on_months'] = on_count(on, sorted(g))
    jac = {}
    for rk in ('P1_lev_jump', 'P2_lev_level'):
        ks = [m for m in g if m in ON[rk]]
        A = {m for m in ks if on[m]}
        B = {m for m in ks if ON[rk][m]}
        jac[rk] = {'jaccard': round(len(A & B) / len(A | B), 3) if A | B else None, 'both': len(A & B), 'dip_only': len(A - B), 'gpr_only': len(B - A)}
    e['jaccard_on_months_vs'] = jac
    e['text'] = PR['families']['controls_report_only']['CTRL_dip']
    return e


def ctrl_overlap():
    out = {}
    for rk, sk in (('P1_lev_jump', 'jump'), ('P2_lev_level', 'level240')):
        dec = D.decisions_for(sk, COLS)
        ts = [t for t, v in dec.items() if v and add(FULL_A, 1) <= t <= FULL_Z]
        neg_t = sum(1 for t in ts if MKT[t] < 0)
        neg_t1 = sum(1 for t in ts if MKT[add(t, -1)] < 0)
        both = sum(1 for t in ts if MKT[t] < 0 and MKT[add(t, -1)] < 0)
        either = sum(1 for t in ts if MKT[t] < 0 or MKT[add(t, -1)] < 0)
        allm = [t for t in dec if add(FULL_A, 1) <= t <= FULL_Z]
        base_neg = sum(1 for t in allm if MKT[t] < 0) / len(allm)
        out[rk] = {'spike_decision_months': len(ts), 'share_r_t_neg': round(neg_t / len(ts), 3), 'share_r_t_minus1_neg': round(neg_t1 / len(ts), 3),
                   'share_both_neg': round(both / len(ts), 3), 'share_either_neg': round(either / len(ts), 3),
                   'base_rate_r_neg_all_months': round(base_neg, 3)}
    return out


# ───────────────────────── 報告 ─────────────────────────
def r1_pre1926():
    sh, sh_sha = D.shiller_tr()
    cp, cp_sha = D.nber_cp()
    out = {'bench': 'Shiller の名目の総リターン（月平均の株価）', 'rf_and_borrow_base': 'NBER の商業手形（FRED M13002US35620M156NNBR）', 'off': 2}
    for rk in P_RULES:
        r = D.RULES[rk]
        on = {m: v for m, v in ON2[rk].items() if D.PRE1926[0] <= m <= D.PRE1926[1]}
        g, n, tv = sim(on, r['w_on'], r['w_off'], r=sh, rf=cp)
        b = {k: sh[k] for k in g}
        out[rk] = {'span': [min(g), max(g)], 'months': len(g), 'on': sum(1 for m in g if on[m]),
                   'gross': es(g, b), 'net': es(n, b), 'cagr_diff_exact_pct': round(exact(g, b)['cagr_diff'] * 100, 4),
                   'sharpe_rule_net_vs_mkt': [shp(n, rf=cp), shp(b, rf=cp)], 'maxdd_rule_net_vs_mkt': [mdd(n), mdd(b)]}
    for rid, base in (('D1_dca_jump', 'P1_lev_jump'), ('D2_dca_level', 'P2_lev_level')):
        on = {m: v for m, v in ON2[base].items() if D.PRE1926[0] <= m <= D.PRE1926[1]}
        out[rid] = dca_block(on, sh, cp, 10)
    return out


def r2_realtime():
    out = {}
    rt_all = SIGS['_realtime_vintage_decisions']
    for rk, sk in (('P1_lev_jump', 'jump'), ('P2_lev_level', 'level240')):
        rt = {int(t): x for t, x in rt_all[sk].items()}
        for t, x in rt.items():
            assert x['data_to'] <= add(t, -1), ('R2: 判断の月 t に t−1 より後の版を使っている', t, x)
        dec_latest = D.decisions_for(sk, COLS)
        dec = {t: v for t, v in dec_latest.items() if t < D.VINT_FIRST}
        dec.update({t: x['spike'] for t, x in rt.items()})
        on_rt = D.on_state(dec, D.RULES[rk]['H'], 1)
        win = months(D.POST_LEXICON, FULL_Z)
        r = D.RULES[rk]
        on_mix = dict(ON[rk])
        for m in win:
            on_mix[m] = on_rt[m]
        g_rt, n_rt, _ = sim(on_mix, r['w_on'], r['w_off'])
        g_l, n_l, _ = SER[rk]
        gw_rt = {m: g_rt[m] for m in win}
        gw_l = {m: g_l[m] for m in win}
        mw = {m: MKT[m] for m in win}
        out[rk] = {'window': [win[0], win[-1]], 'months': len(win),
                   'decisions_realtime': len(rt), 'decisions_differ_from_latest': sum(1 for t in rt if t in dec_latest and rt[t]['spike'] != dec_latest[t]),
                   'on_months_realtime': sum(1 for m in win if on_rt[m]), 'on_months_latest': sum(1 for m in win if ON[rk][m]),
                   'on_months_differ': [m for m in win if on_rt[m] != ON[rk][m]],
                   'realtime_vs_mkt_gross': es(gw_rt, mw), 'latest_vs_mkt_gross': es(gw_l, mw),
                   'realtime_minus_latest_gross': es(gw_rt, gw_l),
                   'decisions_before_2021_10': '版が無いので最新の版の判断を使った（2021-10 より前の判断は 2021-11〜2022-03 の持つ月に H=6 で効く）',
                   'assert': '全判断の月で 版の中身の最後の月 ≤ t−1 を確かめた'}
    return out


def r3_old():
    out = {}
    z = 202110
    for rk in ('P1_lev_jump', 'P2_lev_level'):
        r = D.RULES[rk]
        on_old = on_from(SIGS['_old_method_GPRH'][rk])
        on_old = {m: v for m, v in on_old.items() if m <= z}
        g_o, n_o, _ = sim(on_old, r['w_on'], r['w_off'])
        g_c, n_c, _ = SER[rk]
        ks = [m for m in g_o if FULL_A <= m <= z]
        go = {m: g_o[m] for m in ks}
        gc = {m: g_c[m] for m in ks}
        mw = {m: MKT[m] for m in ks}
        A = {m for m in ks if on_old[m]}
        B = {m for m in ks if ON[rk][m]}
        out[rk] = {'span': [ks[0], ks[-1]], 'months': len(ks), 'on_old': len(A), 'on_current': len(B), 'both': len(A & B),
                   'jaccard': round(len(A & B) / len(A | B), 3), 'agree_share': round(sum(1 for m in ks if on_old[m] == ON[rk][m]) / len(ks), 3),
                   'old_vs_mkt_gross': {p: es(go, mw, a, zz) for p, a, zz in (('full', None, None), ('train', None, TE), ('hold', HS, None))},
                   'current_vs_mkt_gross_same_span': {p: es(gc, mw, a, zz) for p, a, zz in (('full', None, None), ('train', None, TE), ('hold', HS, None))},
                   'old_minus_current_gross': es(go, gc)}
    return out


def r4_periods(entries):
    return {rid: {'gross': {p: entries[rid]['gross'].get(p) for p, _, _ in PER_R4}, 'net': {p: entries[rid]['net'].get(p) for p, _, _ in PER_R4},
                  'on_months': {p: entries[rid]['on_months'].get(p) for p, _, _ in PER_R4}} for rid in P_RULES + E_RULES}


def r5_lev125():
    out = {}
    for rk in ('P1_lev_jump', 'P2_lev_level'):
        g, n, tv = sim(ON[rk], 1.25, 1.0)
        e = evaluate(g, n, tv, periods=PER_MAIN)
        out[rk + '_w125'] = {k: e[k] for k in ('gross', 'net', 'sharpe', 'roll20_net', 'dca20_net', 'maxdd_pct', 'turnover')}
    return out


def r6_costs():
    out = {}
    variants = [('spread_0.5%', 0.005, TRADE), ('spread_3.0%', 0.03, TRADE), ('trade_0.05%', SPREAD, 0.0005), ('trade_0.30%', SPREAD, 0.003)]
    for rid in P_RULES + E_RULES:
        r = D.RULES[rid]
        out[rid] = {}
        for lab, sp, tc in variants:
            g, n, tv = sim(ON[rid], r['w_on'], r['w_off'], spread=sp, trade=tc)
            nh = es(n, MKT, HS)
            out[rid][lab] = {'gross': {p: es(g, MKT, a, z) for p, a, z in PER_MAIN},
                             'net': {p: es(n, MKT, a, z) for p, a, z in PER_MAIN},
                             'C6_would_hold': bool(nh and nh['ex_ann'] > 0 and nh['cagr_diff'] > 0),
                             'sharpe_net_train_hold_vs_mkt': [[shp(n, None, TE), shp(MKT, min(g), TE)], [shp(n, HS), shp(MKT, HS)]],
                             'roll20_net_win_rate': (rolling_exact(n, MKT) or {}).get('win_rate')}
    return out


def c5_month_sets(res_by_rule):
    """C5（国の GPRC）で実際に測った月の集合（国ごと・信号の種類ごと）"""
    sets = {}
    for sk, rk in (('jump', 'P1_lev_jump'), ('level240', 'P2_lev_level')):
        sets[sk] = {}
        for c in D.NON_US + ['USA']:
            tr = country_tr(c)
            on = country_on(c, sk)
            sets[sk][c] = {m for m in on if m in tr and m in RF}
    return sets


def r9_japan():
    tr = country_tr('JPN')
    out = {'currency': '米ドル（JKP は米ドル建て・円建ては無い）', 'country_signal_GPRC_JPN': {}, 'global_signal_GPRH': {}}
    for rk in P_RULES:
        r = D.RULES[rk]
        for lab, on in (('country_signal_GPRC_JPN', country_on('JPN', r['sig'])), ('global_signal_GPRH', {m: v for m, v in ON[rk].items() if m <= D.C5_END})):
            g, n, tv = sim(on, r['w_on'], r['w_off'], r=tr)
            o = eval_simple(g, n, tr)
            o['maxdd_rule_net_vs_mkt'] = [mdd(n), mdd({k: tr[k] for k in g})]
            o['train_to_2006'] = es(g, tr, z=TE) if sum(1 for m in g if m <= TE) >= 24 else None
            o['hold_from_2007'] = es(g, tr, a=HS)
            out[lab][rk] = o
    for rid, base in (('D1_dca_jump', 'P1_lev_jump'), ('D2_dca_level', 'P2_lev_level')):
        sk = D.RULES[base]['sig']
        out['country_signal_GPRC_JPN'][rid] = dca_block(country_on('JPN', sk), tr, RF, 20)
        out['global_signal_GPRH'][rid] = dca_block({m: v for m, v in ON[base].items() if m <= D.C5_END}, tr, RF, 20)
    return out


def r10_nasdaq():
    out = {}
    for t in ('QQQ', '^NDX'):
        try:
            ser = {m: v for m, v in N.yahoo(t).items() if m <= FULL_Z}
        except Exception as e:  # noqa
            out[t] = f'取得失敗 {e}'
            continue
        o = {'span': D.span(ser), 'note': ('配当込み（調整後終値）' if t == 'QQQ' else '価格のみ（配当を含まない・規則も相手も同じ）') + '・生き残りの偏りあり・2026-09 は途中の月なので使わない'}
        for rk in P_RULES:
            r = D.RULES[rk]
            g, n, tv = sim(ON[rk], r['w_on'], r['w_off'], r=ser)
            x = eval_simple(g, n, ser)
            x['train_to_2006'] = es(g, ser, z=TE) if sum(1 for m in g if m <= TE) >= 24 else None
            x['hold_from_2007'] = es(g, ser, a=HS)
            x['maxdd_rule_net_vs_mkt'] = [mdd(n), mdd({k: ser[k] for k in g})]
            x['dca20_net'] = dca_exact(n, {k: ser[k] for k in g}, 20)
            o[rk] = x
        for rid, base in (('D1_dca_jump', 'P1_lev_jump'), ('D2_dca_level', 'P2_lev_level')):
            o[rid] = dca_block(ON[base], ser, RF, 20)
        out[t] = o
    return out


def r12_recent_index():
    out = {}
    for rk in ('P1_lev_jump', 'P2_lev_level'):
        r = D.RULES[rk]
        on = D.rule_on(rk, COLS, off=1, series_override='GPR')
        g, n, tv = sim(on, r['w_on'], r['w_off'])
        e = evaluate(g, n, tv, periods=PER_MAIN, dca=False)
        e['on_months'] = on_count(on, sorted(g))
        e['note'] = '最近の指数 GPR（10紙・1985〜）。訓練が 1995/96〜2006 の11年しか無く線の15年に足りないので報告だけ'
        out[rk] = e
    return out


def r13_zero_rate():
    zero = {m: 0.0 for m in RF}
    return {rid: d_entry(rid, rf_for_reserve=zero, label='R13_reserve_zero_rate') for rid in D_RULES}


# ───────────────────────── 点検 ─────────────────────────
def lookahead_check():
    """持つ月 m の判断に使った GPR（と E10 の市場のリターン）の最後の月が m−2 以前（French・lag1・off1）、E8 は m−1 以前、
    Shiller の時代（off2）は m−3 以前であることを、実データで『それより後の値を極端な値に替えても on(m) が変わらない』で確かめる。
    力の検査: 使ってよい最後の月（m−2・E8 は m−1）の値だけを極端に大きくすると、off の月が on に変わること"""
    rnd = random.Random(20260928)
    L = months(FULL_A, FULL_Z)
    res = {}
    plan = [('P1_lev_jump', 2), ('P2_lev_level', 2), ('E11_level_exp', 2), ('E6_acts', 2), ('E7_threats', 2), ('E8_lag0', 1),
            ('E1_H1', 2), ('E3_H12', 2), ('E12_both', 2), ('E10_resid', 2)]
    for rk, lagm in plan:
        r = D.RULES[rk]
        sigs = r['sig'] if isinstance(r['sig'], tuple) else (r['sig'],)
        series = sorted({D.SIG[s]['series'] for s in sigs})
        n_samp = 12 if rk == 'E10_resid' else 30
        base = ON[rk]
        cand = [m for m in L if m in base]
        samp = sorted(rnd.sample(cand, n_samp))
        bad = []
        for m in samp:
            cut = add(m, -lagm)
            cols2 = dict(COLS)
            for s in series:
                cols2[s] = {k: (v if k <= cut else (1e6 if k % 2 else 1e-3)) for k, v in COLS[s].items()}
            mk2 = {k: (v if k <= cut else (0.3 if k % 2 else -0.3)) for k, v in FF['mkt'].items()}
            on2 = D.rule_on(rk, cols2, off=1, mkt=mk2)
            if on2.get(m) != base[m]:
                bad.append(m)
        # 力の検査（off の月に、使ってよい最後の月の値だけを極端に大きくする）
        offs = [m for m in cand if not base[m]]
        psamp = sorted(rnd.sample(offs, min(n_samp, len(offs))))
        flipped = 0
        for m in psamp:
            last_ok = add(m, -lagm)
            cols2 = dict(COLS)
            for s in series:
                cols2[s] = dict(COLS[s]); cols2[s][last_ok] = COLS[s][last_ok] * 1e4
            on2 = D.rule_on(rk, cols2, off=1, mkt=FF['mkt'])
            flipped += int(on2.get(m) is True)
        res[rk] = {'allowed_last_data_month': f'm−{lagm}', 'samples': len(samp), 'changed_when_later_data_perturbed': bad,
                   'power_off_months_tried': len(psamp), 'power_flipped_to_on': flipped}
        assert not bad, ('先読みの疑い', rk, bad)
    # Shiller の時代（off=2 → m−3 以前）
    bad = []
    for rk in ('P1_lev_jump', 'P2_lev_level'):
        base = ON2[rk]
        cand = [m for m in base if D.PRE1926[0] <= m <= D.PRE1926[1]]
        for m in sorted(rnd.sample(cand, 15)):
            cut = add(m, -3)
            cols2 = dict(COLS)
            cols2['GPRH'] = {k: (v if k <= cut else (1e6 if k % 2 else 1e-3)) for k, v in COLS['GPRH'].items()}
            if D.rule_on(rk, cols2, off=2).get(m) != base[m]:
                bad.append((rk, m))
    res['pre1926_off2'] = {'allowed_last_data_month': 'm−3', 'changed_when_later_data_perturbed': bad}
    assert not bad
    return res


def data_sanity(entries):
    s = {}
    # French
    mx = max(abs(FF['mkt'][d] - (FF['mktrf'][d] + FF['rf'][d])) for d in FF['mkt'])
    s['french_mkt_eq_mktrf_plus_rf_max_abs_diff'] = mx
    assert mx < 1e-12
    s['french_span'] = [min(MKT), max(MKT), len(MKT)]
    assert max(MKT) == FULL_Z and len(MKT) == 1202
    for rid, (g, n, tv) in SER.items():
        assert max(g) <= FULL_Z and min(g) >= FULL_A, rid
    s['no_month_after_202608'] = True
    s['jkp_last_month'] = {c: max(v) for c, v in JKP.items() if v}
    assert all(max(v) <= D.C5_END for v in JKP.values() if v)
    # 帳簿: w=1 なら市場と一致・売買0
    g1, n1, t1 = D.timing_returns({m: 1.0 for m in MKT}, MKT, RF, SPREAD, TRADE)
    s['w1_equals_mkt_max_abs_diff'] = max(abs(g1[m] - MKT[m]) for m in MKT)
    s['w1_turnover_max'] = max(t1.values())
    assert s['w1_equals_mkt_max_abs_diff'] < 1e-12 and s['w1_turnover_max'] < 1e-12
    # 費用: gross − net の合計 = 売買量×0.10% の合計
    cc = {}
    for rid, (g, n, tv) in SER.items():
        a = math.fsum(g[m] - n[m] for m in g)
        b = math.fsum(tv[m] * TRADE for m in g)
        cc[rid] = abs(a - b)
        assert abs(a - b) < 1e-10, rid
    s['cost_identity_max_abs_diff'] = max(cc.values())
    # on の月数が事前登録の形と一致
    shape = SIGF['shape']['on_shapes_US']
    exp_lit = {'P1_lev_jump': (305, 74), 'P3_unlev_jump': (305, 74), 'D1_dca_jump': (305, 74), 'P2_lev_level': (208, 54), 'P4_unlev_level': (208, 54),
               'D2_dca_level': (208, 54), 'E11_level_exp': (90, 4), 'E12_both': (115, 38), 'E1_H1': (83, 21), 'E3_H12': (517, 116),
               'E4_thr80': (564, 126), 'E5_thr95': (170, 24), 'E6_acts': (337, 75), 'E7_threats': (303, 60)}
    oc = {}
    for rid in D.RULES:
        if rid == 'E10_resid':
            continue
        on = ON[rid]
        tr_ = sum(1 for m in months(FULL_A, TE) if on[m]); ho = sum(1 for m in months(HS, FULL_Z) if on[m])
        ok = tr_ == shape[rid]['train']['on'] and ho == shape[rid]['hold']['on']
        if rid in exp_lit:
            ok = ok and (tr_, ho) == exp_lit[rid]
        oc[rid] = {'train_on': tr_, 'hold_on': ho, 'match_prereg_shape': ok}
        assert ok, (rid, tr_, ho)
    s['on_months_match_prereg'] = oc
    # 信号の作り直しの一致（保存された信号＝sha 確認済み ↔ xls からの作り直し）
    rc = {}
    for rid in D.RULES:
        if rid == 'E10_resid':
            continue
        a1 = D.rule_on(rid, COLS, off=1)
        a2 = D.rule_on(rid, COLS, off=2)
        rc[rid] = (a1 == ON[rid]) and all(a2[m] == v for m, v in ON2[rid].items())
        assert rc[rid], rid
    s['signals_recomputed_from_xls_equal_saved'] = rc
    # C5 の評価の月数（データ道具の形と一致・JKP の欠けを0と置いていない）
    c5m = SIGF['shape']['c5_eval_months']
    mism = {}
    for c in D.NON_US:
        tr = country_tr(c)
        for sk in ('jump', 'level240'):
            on = country_on(c, sk)
            g, _, _ = sim(on, 1.5, 1.0, r=tr)
            if len(g) != c5m[c][sk]:
                mism[f'{c}_{sk}'] = (len(g), c5m[c][sk])
            gaps = [m for m in on if m not in tr and min(tr) <= m <= max(tr)]
            assert all(m not in g for m in gaps)
    s['c5_eval_months_mismatch'] = mism
    assert not mism
    s['c5_eval_months_examples'] = {c: c5m[c] for c in ('JPN', 'EGY', 'RUS', 'SAU', 'VNM', 'UKR')}
    # 積立の帳簿（実データで）: 予備金の割合0（share_off=1）なら比1、いつも on なら比1
    rows1 = D.dca_reserve(ON['P1_lev_jump'], MKT, RF, 20, 12, share_off=1.0)
    rows2 = D.dca_reserve({m: True for m in MKT}, MKT, RF, 20, 12)
    s['dca_share_off_1_ratio_max_abs_dev'] = max(abs(x[1] - 1) for x in rows1)
    s['dca_always_on_ratio_max_abs_dev'] = max(abs(x[1] - 1) for x in rows2)
    s['dca_windows'] = len(rows1)
    assert s['dca_share_off_1_ratio_max_abs_dev'] < 1e-9 and s['dca_always_on_ratio_max_abs_dev'] < 1e-9 and len(rows1) == 81
    # E10 の最初の月
    s['E10_first_on_month'] = min(m for m in ON['E10_resid'] if m >= FULL_A)
    s['lookahead'] = lookahead_check()
    s['selftest'] = 'OK（D.selftest() を最初に走らせた）'
    s['sha256'] = {'data_tool': sha_file(D.__file__), 'rules': D.rules_sha(), 'signals': SIGF['signals_sha256'], 'gpr_xls': GPR_SHA,
                   'all_match_prereg': True}
    return s


# ───────────────────────── 事後（格付けに使わない） ─────────────────────────
def nw_reg_dummy(y, d, lag=12):
    y = np.array(y, float); X = np.column_stack([np.ones(len(y)), np.array(d, float)])
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    e = y - X @ b
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:-L]
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi
    se = np.sqrt(np.diag(V))
    return b, se


def episodes(on, ks):
    eps, cur = [], None
    for m in ks:
        if on.get(m):
            if cur is None:
                cur = [m, m]
            else:
                cur[1] = m
        elif cur is not None:
            eps.append(tuple(cur)); cur = None
    if cur is not None:
        eps.append(tuple(cur))
    return eps


def post_hoc(entries):
    ph = {'label': '事後（結果を見た後の診断）。格付けには使わない'}
    L = months(FULL_A, FULL_Z)
    # (1) on の月と off の月の株の上乗せ（Mkt−RF）の差: 時期の情報そのもの
    cond = {}
    for rid in P_RULES[:2] + E_RULES:
        on = ON[rid]
        ks = [m for m in L if m in on]
        res = {}
        for p, a, z in PER_MAIN:
            kk = [m for m in ks if (a is None or m >= a) and (z is None or m <= z)]
            y = [MKTRF[m] for m in kk]
            d = [1.0 if on[m] else 0.0 for m in kk]
            b, se = nw_reg_dummy(y, d)
            mo = [MKTRF[m] for m in kk if on[m]]; mf = [MKTRF[m] for m in kk if not on[m]]
            res[p] = {'on_months': len(mo), 'mktrf_on_ann_pct': round(float(np.mean(mo)) * 1200, 2) if mo else None,
                      'mktrf_off_ann_pct': round(float(np.mean(mf)) * 1200, 2) if mf else None,
                      'diff_ann_pct': round(float(b[1]) * 1200, 2), 'nw_t_diff': round(float(b[1] / se[1]), 2),
                      'vol_on_ann_pct': round(float(np.std(mo, ddof=1)) * math.sqrt(12) * 100, 1) if len(mo) > 1 else None,
                      'vol_off_ann_pct': round(float(np.std(mf, ddof=1)) * math.sqrt(12) * 100, 1) if len(mf) > 1 else None}
        cond[rid] = res
    ph['conditional_equity_premium_on_vs_off'] = {'what': 'on の月と off の月の French Mkt−RF の平均（年率%）と差（NW t・ラグ12）。差が正でないと、借入の規則は β を増やしただけになる',
                                                   'by_rule_signal': cond}
    # (2) 局面ごとの寄与（P1・P2 と B 以上の規則）
    focus = list(dict.fromkeys(['P1_lev_jump', 'P2_lev_level'] + [r for r in P_RULES + E_RULES if entries[r]['grade'] in ('S', 'A', 'B')]))
    ep = {}
    for rid in focus:
        g = SER[rid][0]
        ks = sorted(g)
        rows = []
        for a, z in episodes(ON[rid], ks):
            mm = [m for m in ks if a <= m <= z]
            ex = math.fsum(math.log1p(g[m]) - math.log1p(MKT[m]) for m in mm)
            mk = math.exp(math.fsum(math.log1p(MKT[m]) for m in mm)) - 1
            rows.append({'from': a, 'to': z, 'months': len(mm), 'mkt_return_pct': round(mk * 100, 1), 'rule_minus_mkt_log_pct': round(ex * 100, 2)})
        tr = [x for x in rows if x['to'] <= TE]; ho = [x for x in rows if x['from'] >= HS]
        srt = sorted(rows, key=lambda x: x['rule_minus_mkt_log_pct'])
        ep[rid] = {'episodes': len(rows), 'train_episodes': len(tr), 'hold_episodes': len(ho),
                   'train_sum_log_pct': round(sum(x['rule_minus_mkt_log_pct'] for x in tr), 2),
                   'hold_sum_log_pct': round(sum(x['rule_minus_mkt_log_pct'] for x in ho), 2),
                   'train_positive_episodes': sum(1 for x in tr if x['rule_minus_mkt_log_pct'] > 0),
                   'hold_positive_episodes': sum(1 for x in ho if x['rule_minus_mkt_log_pct'] > 0),
                   'worst5': srt[:5], 'best5': srt[-5:][::-1], 'hold_all': ho}
        # 保有期間: 最大の寄与の局面を抜いたら
        if ho:
            top = max(ho, key=lambda x: x['rule_minus_mkt_log_pct'])
            keep = {m: g[m] for m in ks if m >= HS and not (top['from'] <= m <= top['to'])}
            ep[rid]['hold_drop_top_episode'] = {'dropped': [top['from'], top['to']], 'stats': es(keep, MKT)}
    ph['episodes'] = ep
    # (3) 年代別の費用前の超過（P 族）
    dec = {}
    for rid in P_RULES:
        g = SER[rid][0]
        dec[rid] = {}
        for y0 in range(1926, 2030, 10):
            a, z = max(y0 * 100 + 1, FULL_A), min((y0 + 9) * 100 + 12, FULL_Z)
            st = es(g, MKT, a, z)
            dec[rid][f'{y0}s'] = {k: st[k] for k in ('ex_ann', 't', 'cagr_diff')} if st else None
    ph['by_decade_gross'] = dec
    # (4) 探索の族にも CTRL_const と偽の信号（循環ずらし）を当てる（事前登録は P 族だけ＝ここは事後）。
    #     E4（C8 だけで落ちた・最も惜しい）が『β を増やしただけ』かを見るため
    ph['timing_value_E_family'] = {'label': '事後（事前登録の対照は P 族だけ。E 族へ広げたのは結果を見た後）',
                                   'CTRL_const': ctrl_const(E_RULES), 'CTRL_placebo_shift': ctrl_placebo(E_RULES)}
    return ph


# ───────────────────────── 本体 ─────────────────────────
def main():
    t0 = datetime.datetime.now(datetime.timezone.utc)
    entries = {rid: rule_entry(rid) for rid in P_RULES + E_RULES}
    build_hist_on()
    # C5（P 族）
    c5 = {rk: c5_rule(rk, 'country') for rk in P_RULES}
    # Holm（丸める前の p・保有・費用前・両側）
    holm = {}
    for fam, ids in (('P', P_RULES), ('E', E_RULES)):
        pv = {rid: entries[rid]['exact_gross']['hold']['p_two'] for rid in ids}
        pr = {rid: entries[rid]['gross']['hold']['p'] for rid in ids}
        holm[fam] = {'p_exact': {k: (round(v, 6) if v is not None else None) for k, v in pv.items()}, 'holm_exact': N.holm(pv),
                     'p_rounded': pr, 'holm_rounded': N.holm(pr)}
    # 格付け
    rb = []
    for rid in P_RULES + E_RULES:
        e = entries[rid]
        repl = {'regions': c5[rid]['regions'], 'positive': c5[rid]['positive']} if rid in c5 else None
        hp = holm[e['family']]['holm_exact'].get(rid)
        sp = {'train': (e['sharpe']['train']['rule_net'], e['sharpe']['train']['mkt']), 'hold': (e['sharpe']['hold']['rule_net'], e['sharpe']['hold']['mkt'])}
        g, c = N.grade(full=e['gross']['full'], train=e['gross']['train'], hold=e['gross']['hold'], roll20=e['roll20_net'],
                       cost_hold=e['net']['hold'], repl=repl, family_holm_p=hp, sharpe_pair=sp, leveraged_or_timing=True)
        e['grade'], e['criteria'], e['repl_C5'], e['holm_p_in_family'] = g, c, repl, hp
        e['grade_function'] = 'nx_common.grade（長い歴史の線）'
        e['grade_inputs'] = {'full/train/hold': '費用前（借入の上乗せ 1.5% は引いた後・売買の費用の前）対 French Mkt', 'roll20': '費用後の転がる20年窓（丸める前の差で勝ちを数える）',
                             'cost_hold': '費用後（片道 0.10%）の保有', 'repl': 'C5（P 族だけ・E は N/A）', 'family_holm_p': f"{e['family']} 族の Holm（丸める前の p）",
                             'sharpe_pair': '費用後の規則のシャープ 対 Mkt（French RF を引く）', 'leveraged_or_timing': True}
        # 丸めの境界の検査（格付けは変えない＝記録だけ）
        def fx(st, ex):
            if st is None or ex is None:
                return st
            st = dict(st); st['t'] = ex['t']; st['ex_ann'] = ex['ex_ann'] * 100; st['cagr_diff'] = ex['cagr_diff'] * 100
            return st
        eg = e['exact_gross']
        nh = e['exact_net_hold']
        g_exact, _ = N.grade(fx(e['gross']['full'], eg['full']), fx(e['gross']['train'], eg['train']), fx(e['gross']['hold'], eg['hold']), e['roll20_net'],
                             fx(e['net']['hold'], nh), repl, hp, sp, True)
        rr = dict(e['roll20_net']); rr['win_rate'] = rr['win_rate_nx_common_rounded']
        g_round, _ = N.grade(e['gross']['full'], e['gross']['train'], e['gross']['hold'], rr, e['net']['hold'], repl,
                             holm[e['family']]['holm_rounded'].get(rid), sp, True)
        e['rounding_check'] = {'grade_all_exact': g_exact, 'grade_all_rounded_nx_common': g_round}
        if len({g, g_exact, g_round}) > 1:
            rb.append({'rule': rid, 'official': g, 'all_exact': g_exact, 'all_rounded': g_round})
    # 積立
    dents = {rid: d_entry(rid) for rid in D_RULES}
    # 対照・報告
    controls = {'CTRL_const': ctrl_const(), 'CTRL_placebo_shift': ctrl_placebo(), 'CTRL_dip': ctrl_dip(), 'CTRL_overlap': ctrl_overlap()}
    msets = c5_month_sets(c5)
    reports = {}
    reports['R1_pre1926'] = r1_pre1926()
    reports['R2_realtime_vintage'] = r2_realtime()
    reports['R3_old_method'] = r3_old()
    reports['R4_periods'] = r4_periods(entries)
    reports['R5_leverage_125'] = r5_lev125()
    reports['R6_cost_sensitivity'] = r6_costs()
    reports['R7_country_global_signal'] = {'same_months_as_C5': {rk: c5_rule(rk, 'global', month_set=msets[D.RULES[rk]['sig']]) for rk in P_RULES},
                                          'all_jkp_months': {rk: c5_rule(rk, 'global') for rk in P_RULES}}
    reports['R8_country_hist_signal'] = {'same_months_as_C5': {rk: c5_rule(rk, 'hist', month_set=msets[D.RULES[rk]['sig']]) for rk in P_RULES},
                                        'all_jkp_months': {rk: c5_rule(rk, 'hist') for rk in P_RULES},
                                        'cfrac_jump': D.COUNTRY_CFRAC}
    reports['R9_japan'] = r9_japan()
    reports['R10_nasdaq100'] = r10_nasdaq()
    reports['R11_dca_of_P'] = {rk: {'dca20_net': entries[rk]['dca20_net'], 'dca20_gross': entries[rk]['dca20_gross']} for rk in P_RULES}
    reports['R12_recent_index'] = r12_recent_index()
    reports['R13_reserve_zero_rate'] = r13_zero_rate()
    sanity = data_sanity(entries)
    sanity['rounding_boundary_check'] = {'crossings': rb, 'note': '空なら丸めは格付けに影響しない。格付けは Holm を丸める前の p で、C4 の勝ちは丸める前の差で数え、t と符号は excess_stats の丸めた値（nx_common.grade のまま）で当てた'}
    ph = post_hoc(entries)
    return entries, dents, c5, holm, controls, reports, sanity, ph, t0


def compact(e):
    st, nh = e['gross'], e['net']['hold']
    return {'id': e['id'], 'family': e['family'], 'grade': e['grade'],
            'train_ex_ann': st['train']['ex_ann'], 'train_t': st['train']['t'],
            'hold_ex_ann': st['hold']['ex_ann'], 'hold_cagr_diff': st['hold']['cagr_diff'], 'hold_t': st['hold']['t'],
            'hold_net_ex_ann': nh['ex_ann'], 'hold_net_cagr_diff': nh['cagr_diff'],
            'full_ex_ann': st['full']['ex_ann'], 'full_t': st['full']['t'], 'full_cagr_diff': st['full']['cagr_diff'],
            'roll20_net_win_rate': e['roll20_net']['win_rate'], 'dca20_net_median': e['dca20_net']['median_ratio'] if e.get('dca20_net') else None,
            'sharpe_train_rule_net_vs_mkt': [e['sharpe']['train']['rule_net'], e['sharpe']['train']['mkt']],
            'sharpe_hold_rule_net_vs_mkt': [e['sharpe']['hold']['rule_net'], e['sharpe']['hold']['mkt']],
            'maxdd_full_rule_net_vs_mkt': [e['maxdd_pct']['full']['rule_net'], e['maxdd_pct']['full']['mkt']],
            'repl_C5': e.get('repl_C5'), 'holm_p': e.get('holm_p_in_family'),
            'failed': [c for c, v in e['criteria'].items() if v is False], 'criteria': e['criteria']}


def run():
    entries, dents, c5, holm, controls, reports, sanity, ph, t0 = main()
    table = [compact(entries[r]) for r in P_RULES + E_RULES]
    order = {'S': 0, 'A': 1, 'B': 2, 'C': 3}
    best = sorted(table, key=lambda x: (order[x['grade']], -sum(1 for v in x['criteria'].values() if v is True), -(x['hold_net_cagr_diff'] or -99)))[0]
    grade_summary = {r['id']: r['grade'] for r in table}
    grade_summary.update({rid: ('積立の線 合格' if dents[rid]['dca_line_pass'] else '積立の線 不合格') for rid in D_RULES})
    counts = {g: sum(1 for r in table if r['grade'] == g) for g in 'SABC'}

    # tested（1本残らず）: 規則18本＋対照＋報告の要約
    tested = [entries[r] for r in P_RULES + E_RULES] + [dents[r] for r in D_RULES]
    for rk, v in controls['CTRL_const'].items():
        tested.append({'id': f'CTRL_const_{rk}', 'kind': 'control', 'w_bar_train': v['w_bar_train'],
                       'rule_minus_const_gross': v['rule_minus_const_gross'], 'const_vs_mkt_gross_train_hold': [v['const_vs_mkt_gross']['train'], v['const_vs_mkt_gross']['hold']]})
    for rk, v in controls['CTRL_placebo_shift'].items():
        tested.append({'id': f'CTRL_placebo_shift_{rk}', 'kind': 'control', 'shifts': v['shifts'],
                       'percentile_full_train_hold': [v['full']['percentile_in_placebo'], v['train']['percentile_in_placebo'], v['hold']['percentile_in_placebo']]})
    cd = controls['CTRL_dip']
    tested.append({'id': 'CTRL_dip', 'kind': 'control', 'gross': {p: cd['gross'][p] for p in ('full', 'train', 'hold')}, 'jaccard': cd['jaccard_on_months_vs']})
    tested.append({'id': 'CTRL_overlap', 'kind': 'control', 'result': controls['CTRL_overlap']})
    for rk in P_RULES:
        v = reports['R1_pre1926'][rk]
        tested.append({'id': f'R1_pre1926_{rk}', 'kind': 'report', 'gross': v['gross'], 'cagr_diff_exact_pct': v['cagr_diff_exact_pct']})
    for rid in D_RULES:
        v = reports['R1_pre1926'][rid]
        tested.append({'id': f'R1_pre1926_{rid}', 'kind': 'report', 'win_rate_exact': v and v['win_rate_exact'], 'median_ratio': v and v['median_ratio_exact_upper'], 'windows': v and v['windows']})
    for rk, v in reports['R2_realtime_vintage'].items():
        tested.append({'id': f'R2_realtime_{rk}', 'kind': 'report', 'on_months_differ': v['on_months_differ'], 'realtime_minus_latest_gross': v['realtime_minus_latest_gross']})
    for rk, v in reports['R3_old_method'].items():
        tested.append({'id': f'R3_old_method_{rk}', 'kind': 'report', 'jaccard': v['jaccard'], 'old_vs_mkt_gross': v['old_vs_mkt_gross']})
    tested.append({'id': 'R4_periods', 'kind': 'report', 'rules': len(reports['R4_periods']), 'where': 'reports.R4_periods'})
    for rk, v in reports['R5_leverage_125'].items():
        tested.append({'id': f'R5_{rk}', 'kind': 'report', 'gross': v['gross'], 'sharpe': v['sharpe']})
    tested.append({'id': 'R6_cost_sensitivity', 'kind': 'report', 'variants': 4, 'rules': len(reports['R6_cost_sensitivity']),
                   'C6_would_hold': {rid: {lab: x['C6_would_hold'] for lab, x in v.items()} for rid, v in reports['R6_cost_sensitivity'].items()}})
    for var in ('same_months_as_C5', 'all_jkp_months'):
        for rk, v in reports['R7_country_global_signal'][var].items():
            tested.append({'id': f'R7_{var}_{rk}', 'kind': 'report', 'regions': v['regions'], 'positive': v['positive'], 'median_cagr_diff_pct': v['median_cagr_diff_pct']})
        for rk, v in reports['R8_country_hist_signal'][var].items():
            tested.append({'id': f'R8_{var}_{rk}', 'kind': 'report', 'regions': v['regions'], 'positive': v['positive'], 'median_cagr_diff_pct': v['median_cagr_diff_pct']})
    for lab in ('country_signal_GPRC_JPN', 'global_signal_GPRH'):
        for k, v in reports['R9_japan'][lab].items():
            if k.startswith('D'):
                tested.append({'id': f'R9_{lab}_{k}', 'kind': 'report', 'win_rate_exact': v and v['win_rate_exact'], 'median_ratio': v and v['median_ratio_exact_upper'], 'windows': v and v['windows']})
            else:
                tested.append({'id': f'R9_{lab}_{k}', 'kind': 'report', 'gross': v['gross'], 'cagr_diff_exact_pct': v['cagr_diff_exact_pct']})
    for t, o in reports['R10_nasdaq100'].items():
        if isinstance(o, str):
            tested.append({'id': f'R10_{t}', 'kind': 'report', 'error': o}); continue
        for k, v in o.items():
            if k in ('span', 'note'):
                continue
            if k.startswith('D'):
                tested.append({'id': f'R10_{t}_{k}', 'kind': 'report', 'win_rate_exact': v and v['win_rate_exact'], 'median_ratio': v and v['median_ratio_exact_upper'], 'windows': v and v['windows']})
            else:
                tested.append({'id': f'R10_{t}_{k}', 'kind': 'report', 'gross': v['gross'], 'cagr_diff_exact_pct': v['cagr_diff_exact_pct']})
    for rk in P_RULES:
        tested.append({'id': f'R11_dca_{rk}', 'kind': 'report', 'dca20_net': reports['R11_dca_of_P'][rk]['dca20_net']})
    for rk, v in reports['R12_recent_index'].items():
        tested.append({'id': f'R12_recent_index_{rk}', 'kind': 'report', 'gross': {p: v['gross'][p] for p in ('full', 'train', 'hold')}})
    for rid, v in reports['R13_reserve_zero_rate'].items():
        tested.append({'id': v['id'], 'kind': 'report', 'dca_line': v['dca_line'], 'dca_line_pass': v['dca_line_pass']})

    deviations = [
        {'item': 'C4（転がる20年窓）と20年積立の勝ちの数え方', 'prereg': 'nx_common.rolling（毎年7月起点・一括）',
         'implemented': '同じ窓・同じ出力の形で、勝ちは丸める前の差（>0）・倍率（>1）で数えた（rolling_exact / dca_exact）。nx_common の数え方（丸めてから数える）の結果も併記',
         'why': 'nx_common.rolling は窓ごとの年率差を小数2桁の%に丸めてから >0 を数えるので、0〜0.005%/年の小さな勝ちが負けに数えられる（検査役の指摘・まとめ役の指示）',
         'affects_grade': '丸めた数え方と格付けが違う規則は data_sanity.rounding_boundary_check に名指し（空なら影響なし）'},
        {'item': 'C7 の Holm の元の p', 'prereg': 'p_two(NW t)', 'implemented': '丸める前の NW t から p_two（excess_stats の p は小数4桁に丸めてある）。丸めた p の Holm も holm.*.holm_rounded に併記',
         'affects_grade': 'rounding_boundary_check を見よ'},
        {'item': 'C5 の『正の国』の数え方', 'prereg': 'その国の費用前の幾何の年率差（cagr_diff）> 0',
         'implemented': '丸める前の幾何の年率差 > 0 で数えた（excess_stats の cagr_diff は小数2桁の%）。丸めた数え方の数も c5.*.positive_rounded_count に併記',
         'affects_grade': '丸めた数え方と正の国の数が違えば c5 に出る（違っても 2/3 の線をまたがなければ影響なし）'},
        {'item': 'D 族の比の中央値・勝ちの数え方', 'prereg': '比の中央値 > 1・比 > 1 の割合 ≥ 80%（D.dca_reserve は比を小数4桁に丸める）',
         'implemented': 'D.dca_reserve をそのまま呼び、同じ帳簿の検算器 dca_reserve_exact で丸める前の比を取り（全窓で round(比,4) の一致を assert）、勝ちと中央値は丸める前の比で数えた。中央値は D.dca_summary と同じ v[n//2]（保有の10窓では上の中央値）。普通の中央値（真ん中2つの平均）の判定も dca_line_conventional_median_check に併記',
         'why': '窓の終わりに残った予備金（事前登録 also_report）を出すには帳簿の最後の値が要る。D.dca_reserve は返さない',
         'affects_grade': '積立の線（D_C1・D_C2）が中央値の定義で変われば dca_line_conventional_median_check に出る'},
        {'item': 'R2（実時間の版）の 2021-10 より前の判断', 'prereg': '2021-10〜2026-08 の判断をその月末に出ていた版だけで作り直す',
         'implemented': '2021-10 より前の判断（2021-11〜2022-03 の持つ月に H=6 で効く）は、それより古い版が公開されていないので最新の版の判断を使った', 'affects_grade': '無し（報告）'},
        {'item': 'R7・R8（国の市場に別の信号）の期間', 'prereg': '期間の記載なし（C5 の別の作り）',
         'implemented': '主は C5 と同じ月（国ごとに GPRC の信号で測った月）にそろえた。JKP の全部の月（〜2025-12）で測った版も all_jkp_months に併記。R8 の jump の c は国の指数と同じ 0.1',
         'affects_grade': '無し（報告）'},
        {'item': 'R9（日本）の全体の信号の期間', 'prereg': '期間の記載なし', 'implemented': 'JKP の日本の全部の月（1986-01〜2025-12）。積立は20年の窓（12か月ずつ）', 'affects_grade': '無し（報告）'},
        {'item': 'R3（古い方法）の期間', 'prereg': '1926-07〜2021-10', 'implemented': 'そのとおり（古い版の最後の判断 2021-10 → 持つ月 2021-11 は使わない）', 'affects_grade': '無し'},
        {'item': '借入の規則で月の損が −100% 以上になった国（C5・R7・R8 の P1・P2）', 'prereg': '借入は月次で1.5倍に戻す模型（証拠金の追加・強制決済は入れない＝known_limits）。月の損が −100% を超える場合の扱いの記載なし',
         'implemented': '1.5倍で国の市場が −66.7% を超えて下げた月（VEN 2018 など）は、その月で資産が尽きた（幾何の年率 −100%・cagr_diff = −100 − 相手の年率）とした。算術の超過と NW t は切らない元の差から。該当の国と月は c5.*.per_country.*.wiped_out_months に名指し',
         'why': '対数が作れず N.excess_stats が止まる。資産が0以下になった口座は現実には強制決済で終わる＝その国では規則が市場に負けたと数えるのが最も近い形',
         'affects_grade': '無し（C5 は P1 18/43・P2 22/43 で、VEN を正に数えても 2/3＝29 に届かない）'},
        {'item': 'CTRL_overlap の『その月と前月の市場のリターンが負』', 'prereg': '割合（記述だけ）',
         'implemented': '読みが二通りあるので、t が負・t−1 が負・両方負・どちらか負 の4つの割合と、全月で負の月の基礎率を出した', 'affects_grade': '無し'},
    ]

    lines = []
    for r in table:
        lines.append(f"{r['id']}（{r['grade']}）: 訓練 {r['train_ex_ann']:+}%/年 t{r['train_t']}／保有 算術 {r['hold_ex_ann']:+} 幾何 {r['hold_cagr_diff']:+} t{r['hold_t']}（費用後 幾何 {r['hold_net_cagr_diff']:+}）／全期間 t{r['full_t']}／20年窓 {r['roll20_net_win_rate']}／シャープ 訓練 {r['sharpe_train_rule_net_vs_mkt'][0]} 対 {r['sharpe_train_rule_net_vs_mkt'][1]}・保有 {r['sharpe_hold_rule_net_vs_mkt'][0]} 対 {r['sharpe_hold_rule_net_vs_mkt'][1]}"
                     + (f"／C5 {r['repl_C5']['positive']}/{r['repl_C5']['regions']}" if r['repl_C5'] else '') + f"／落ちた基準 {r['failed']}")
    for rid in D_RULES:
        d = dents[rid]
        lines.append(f"{rid}: 20年窓（81）で比>1 {d['full_20y_81']['win_rate_exact']}・訓練61窓の中央 {d['train_20y_end_le_2006']['median_ratio_exact_upper']}・保有10窓の中央 {d['hold_10y_from_2007']['median_ratio_exact_upper']} → {'積立の線 合格' if d['dca_line_pass'] else '積立の線 不合格'}")

    T = {r['id']: r for r in table}
    p1, e4 = T['P1_lev_jump'], T['E4_thr80']
    cc = controls['CTRL_const']['P1_lev_jump']['rule_minus_const_gross']
    e4c = ph['timing_value_E_family']['CTRL_const']['E4_thr80']
    pl1 = controls['CTRL_placebo_shift']['P1_lev_jump']
    cond1 = ph['conditional_equity_premium_on_vs_off']['by_rule_signal']['P1_lev_jump']
    summary_ja = (
        f"{'・'.join(f'{g} {counts[g]}' for g in 'SABC')}（16本すべて {'C' if counts['C'] == 16 else '—'}）。積立の予備金の規則 D1・D2 は積立の線に不合格"
        f"（20年窓81で比>1 は D1 {dents['D1_dca_jump']['full_20y_81']['win_rate_exact']}・D2 {dents['D2_dca_level']['full_20y_81']['win_rate_exact']}）。"
        f"主の P1（跳ねの後6か月 1.5倍）: 訓練 {p1['train_ex_ann']:+}%/年 t{p1['train_t']}（C1 の t≥2 に届かず）・保有 幾何 {p1['hold_cagr_diff']:+}%/年 t{p1['hold_t']}・"
        f"シャープは訓練 {p1['sharpe_train_rule_net_vs_mkt'][0]} 対 {p1['sharpe_train_rule_net_vs_mkt'][1]}・保有 {p1['sharpe_hold_rule_net_vs_mkt'][0]} 対 {p1['sharpe_hold_rule_net_vs_mkt'][1]} で両方 Mkt 以下（C8 不合格）・C5 {p1['repl_C5']['positive']}/{p1['repl_C5']['regions']}。"
        f"同じ平均の株の割合（{controls['CTRL_const']['P1_lev_jump']['w_bar_train']}倍）をいつも持つ対照に対しては 全期間 {cc['full']['ex_ann']:+}%/年 t{cc['full']['t']}・保有 {cc['hold']['ex_ann']:+} t{cc['hold']['t']}、"
        f"偽の信号（循環ずらし {pl1['shifts']}通り）の中では全期間 {pl1['full']['percentile_in_placebo']}・保有 {pl1['hold']['percentile_in_placebo']} の分位＝超過の大半は β（平均の割合が1を超える分）で、時期の情報は小さく有意でない。"
        f"最も惜しいのは探索の E4（閾値を上位20%に下げた P1）: C1〜C7 はすべて合格（訓練 t{e4['train_t']}・保有 t{e4['hold_t']}・全期間 t{e4['full_t']}・20年窓 {e4['roll20_net_win_rate']}）だが "
        f"シャープが訓練 {e4['sharpe_train_rule_net_vs_mkt'][0]} 対 {e4['sharpe_train_rule_net_vs_mkt'][1]}・保有 {e4['sharpe_hold_rule_net_vs_mkt'][0]} 対 {e4['sharpe_hold_rule_net_vs_mkt'][1]} で C8 に落ちた。"
        f"（事後）E4 は平均 {e4c['w_bar_train']}倍を常に持つ対照に 全期間 {e4c['rule_minus_const_gross']['full']['ex_ann']:+}%/年 t{e4c['rule_minus_const_gross']['full']['t']}・保有 {e4c['rule_minus_const_gross']['hold']['ex_ann']:+} t{e4c['rule_minus_const_gross']['hold']['t']} しか上回らない＝勝ちの中身はほぼ借入の β。"
        f"（事後）跳ねの後6か月の Mkt−RF は off の月より 訓練 {cond1['train']['diff_ann_pct']:+}%/年（NW t{cond1['train']['nw_t_diff']}）・保有 {cond1['hold']['diff_ann_pct']:+}（t{cond1['hold']['nw_t_diff']}）高いが有意でない。"
        f"減らす向きの E9 は負け、現金2割の P3・P4 は構造どおり負け。線は下げていない。門・採点・配分には入れない。")

    out = {
        'angle': 'nx_gpr',
        'summary_ja': summary_ja,
        'headline': f"地政学リスク指数（GPR）が跳ねた後に株を厚く持つ規則 16本（主4・探索12）: S {counts['S']}・A {counts['A']}・B {counts['B']}・C {counts['C']}／積立2本: "
                    + '・'.join(f"{rid} {'合格' if dents[rid]['dca_line_pass'] else '不合格'}" for rid in D_RULES),
        'summary_lines': lines,
        'best': {'id': best['id'], 'grade': best['grade'], 'criteria_passed': sum(1 for v in best['criteria'].values() if v is True),
                 'why': '格付けが最も高く、同じ格付けの中で合格した基準の数が最も多く、次に保有の費用後の幾何の差が大きい規則'},
        'grade_summary': grade_summary, 'grade_counts': counts,
        'table': table,
        'deviations_from_prereg': deviations,
        'prereg': {'path': 'out/nx_gpr_prereg.json', 'commit': git('log', '-1', '--format=%H', '--', 'out/nx_gpr_prereg.json'),
                   'unchanged_since_commit': git('diff', '--quiet', 'HEAD', '--', 'out/nx_gpr_prereg.json') == '' },
        'script': 'night/nx_gpr.py', 'data_tool': 'night/nx_gpr_data.py',
        'stance': PR['stance_before_results'],
        'benchmark': PR['benchmark'],
        'conventions': {'gross': '借入の上乗せ 1.5%/年（1 を超える分だけ・RF に足す）は引いた後・売買の費用の前', 'net': 'さらに売買の費用 片道 0.10%',
                        'C1_C2_C3_C7': '費用前', 'C4_C6_C8': '費用後', 'C4_count': '丸める前の差', 'holm': '丸める前の p（両側）',
                        'periods': {'full': [FULL_A, FULL_Z], 'train': [FULL_A, TE], 'hold': [HS, FULL_Z], 'E10': 'その信号の最初の持つ月から'}},
        'data_sanity': sanity,
        'holm': holm,
        'c5': c5,
        'tested_count': {'graded': len(P_RULES) + len(E_RULES), 'dca_line': len(D_RULES), 'all_entries_in_tested': len(tested)},
        'tested': tested,
        'controls_report_only': controls,
        'reports': reports,
        'post_hoc': ph,
        'predictions_before_results': PR['predictions_before_results'],
        'known_limits': PR['known_limits'],
        'run': {'started_utc': t0.isoformat(), 'finished_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'git_head': git('rev-parse', 'HEAD')},
    }
    p = N.save(OUTNAME, out)
    print(out['headline'])
    for ln in lines:
        print(ln)
    print('best', out['best'])
    print('rounding crossings', sanity['rounding_boundary_check']['crossings'])
    print('saved', p)


if __name__ == '__main__':
    run()
