#!/usr/bin/env python3
"""night/nx_osap_info.py — nx 角度 osap_info（情報の仲介者の信号）の**測る道具**（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…探し続けて」。
ただし線を下げて勝ちを作らない。事前登録 out/nx_osap_info_prereg.json（測る前に固定・この道具は書き換えない）と
全体の線 out/nx_prereg.json（C1〜C8・格付け S/A/B/C・短い標本の線）をそのまま当てる。統計と格付けは night/nx_common.py。

何を測るか
  OSAP（Chen-Zimmermann 2025-10 版）の情報の仲介者の信号（空売り残高・格下げ・アナリストの予想修正・予想のばらつき・
  長期成長予想・推奨・オプションの歪み）の『良い側の組』を時価加重・買いだけで持ち、French Mkt（Mkt-RF＋RF）と比べる。
  規則の台帳は night/nx_osap_info_data.py の RULES を import する（写さない）。
  最初に rules_sha256 と series_sha256 を計算し直し、事前登録の値と違えば止まる。

族と線（事前登録 criteria）
  P（主・長い歴史 6本）: grade()（C1〜C8）。Holm は P の6本の中（保有期間・費用前・両側 p）。C5・C8 は N/A。
  Q（主・短い標本 3本）: grade_short()。halves＝月数で二等分／drop_top＝【代用】最大の暦年を抜く／
                          lower_bound＝【代用】費用 0.30%。Holm は Q の3本の中（全期間・費用前・片側 p）。
  XL（探索 21本）: P と同じ線・Holm は XL の中。XS（探索 16本）: Q と同じ線・Holm は XS の中。
  R（報告のみ 2本）: 格付けしない。R1〜R9 の報告（事前登録 R_report_only_other）。
  『事後』の節は結果を見た後の診断で、格付けには使わない。

費用（事前登録 cost_assumption）
  保有の月 t の費用 = その月の片道の回転（nx_osap_info_turnover.json の monthly_vw・時価の代わりの重み）× 単価。
  最初の月は回転1.0。回転の値が無い月はその規則の評価の窓の中の月次の回転の中央値。単価 0.10%（判定）・0.30%（感度）。
  2×3 の BH は年1.0（毎月 1/12）。MIX は構成の規則の毎月の回転の平均。

使い方: python3 night/nx_osap_info.py   → out/nx_osap_info.json
"""
import sys, os, json, math, hashlib, time, csv, statistics as S
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
from nx_osap_info_data import RULES, rules_sha, PORTS_OUT, TURN_OUT, FILES  # noqa: E402

PRE = os.path.join(N.BASE, 'out', 'nx_osap_info_prereg.json')
OUTNAME = 'nx_osap_info.json'
UNIT, UNIT3 = 0.001, 0.003
TE, HS, RS = N.TRAIN_END, N.HOLD_START, N.RECENT_START
T0 = time.time()
DEV = []  # 事前登録からのずれ（理由つき）
NOTES = []  # 実装の注記（ずれではない読み方の確定）


def log(*a):
    print(f'[{time.time() - T0:6.1f}s]', *a, flush=True)


def nxt(ym):
    y, m = divmod(ym, 100)
    return (y + 1) * 100 + 1 if m == 12 else ym + 1


def sha_obj(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# ───────────────────────── 読み込みと指紋の確認 ─────────────────────────
def load():
    pre = json.load(open(PRE))
    j = json.load(open(PORTS_OUT))
    turn = json.load(open(TURN_OUT))
    rs = rules_sha()
    exp_rs, exp_ss = pre['tools']['rules_sha256'], pre['tools']['series_sha256']
    if not (rs == exp_rs == j['rules_sha256'] == turn['rules_sha256']):
        raise SystemExit(f'rules_sha256 が事前登録と違う: 計算 {rs} / 事前登録 {exp_rs} / ports {j["rules_sha256"]} / turnover {turn["rules_sha256"]}')
    ss_blob = sha_obj({'series': j['series']})  # データの道具（cmd_ports）と同じ計算＝{'series': series}
    ss_bare = sha_obj(j['series'])
    if not (ss_blob == exp_ss == j['series_sha256']):
        raise SystemExit(f'series_sha256 が事前登録と違う: 計算 {ss_blob} / 事前登録 {exp_ss}')
    NOTES.append("series_sha256 は事前登録の値と一致（データの道具 cmd_ports と同じく {'series': series} を json.dumps(sort_keys=True, separators=(',',':')) した sha256）。"
                 f"事前登録の sha_note の文言『series を json.dumps した』どおりに series だけを包まずに計算すると {ss_bare[:16]}… になる＝文言が包みの一段を省いていただけで、数字は測る前のものと同一")
    return pre, j, turn, {'rules_sha256': rs, 'series_sha256_recomputed': ss_blob, 'matches_prereg': True, 'series_sha256_bare_series_only': ss_bare}


def prereg_rules(pre):
    out = {}
    for fam in ('P_primary_long', 'Q_primary_short', 'XL_exploratory_long', 'XS_exploratory_short', 'R_report_only_rules'):
        for x in pre['families'][fam]:
            out[x['id']] = x
    return out


# ───────────────────────── 系列 ─────────────────────────
def rule_series(j, r):
    d = j['series'][r['file']][r['signal']][r['port']]
    a, z = j['starts'][r['id']], j['ends'][r['id']]
    out, nlong = {}, {}
    for m, (ret, n) in d.items():
        m = int(m)
        if a <= m <= z and ret is not None:
            out[m] = ret / 100.0
            nlong[m] = n
    return out, nlong, a, z


def turnover_series(turn, r, months, key='monthly_vw'):
    """保有の月ごとの片道の回転（月次）。最初の月は1.0・値が無い月は窓の中の中央値"""
    ms = sorted(months)
    if r['file'] == 'ff93':
        return {m: 1.0 / 12 for m in ms}, {'kind': 'ff93_BH_theory', 'annual': 1.0, 'filled_months': 0}
    tv = turn['rules'][r['id']][key]
    inwin = [v for k, v in tv.items() if ms[0] <= int(k) <= ms[-1]]
    med = S.median(inwin)
    out, filled = {}, 0
    for i, m in enumerate(ms):
        if i == 0:
            out[m] = 1.0
        elif str(m) in tv:
            out[m] = tv[str(m)]
        else:
            out[m] = med; filled += 1
    return out, {'kind': key, 'median_monthly_in_window': round(med, 5), 'filled_months': filled,
                 'charged_annual_all': round(12 * S.mean(out.values()), 3),
                 'charged_annual_hold': round(12 * S.mean([v for k, v in out.items() if k >= HS]), 3) if any(k >= HS for k in out) else None}


def with_cost(r, tov, unit):
    return {m: v - tov[m] * unit for m, v in r.items()}


# ───────────── 勝ちの数は丸める前の値で数える（検査役の指摘の是正・2026-09-28 v2） ─────────────
# nx_common.rolling は窓ごとの年率差を %・小数2桁に丸めてから『>0 なら勝ち』を数え、nx_common.dca は倍率を小数3桁に
# 丸めてから『>1 なら勝ち』を数える。このため +0.001〜+0.005%/年 の窓が負けに数えられていた（この角度で7か所）。
# C4 は「市場に勝った割合」＝差が正の窓の割合なので、数えるのは丸める前の差。丸めは表示（median/worst/best）だけに残す。
# 兄弟の角度 nx_osap_intang.py（F1_rolling_rounding）と同じ直し方にそろえた: nx_common.py は全角度の共通部品なので
# ここでは書き換えない（直すなら全角度で同時に＝まとめ役）。窓の切り方は nx_common と同じ式をここに写し、
# 丸めた値が nx_common の戻り値と一致すること（窓数・中央・丸めた勝ちの数）を毎回確かめる（ずれたら止まる）。
FIXROWS = []  # 丸めで勝ちの数が変わった箇所（fixes に出す）


def _roll_exact_diffs(s, b, years, start_month):
    ks = sorted(set(s) & set(b))
    out = []
    y0, last = ks[0] // 100, ks[-1]
    for y in range(y0, 2100):
        a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, gs - gb))
    return out


def rolling_x(s, b, years=20, start_month=7, where=None):
    """nx_common.rolling と同じ戻り値。ただし wins / win_rate は丸める前の差 > 0 で数える"""
    ro = N.rolling(s, b, years, start_month)
    if not ro:
        return ro
    d = _roll_exact_diffs(s, b, years, start_month)
    rounded = sorted(round(c * 100, 2) for _, c in d)
    if len(d) != ro['windows'] or rounded[len(rounded) // 2] != ro['median'] or sum(1 for c in rounded if c > 0) != ro['wins']:
        raise SystemExit('rolling_x: 窓の切り方が nx_common.rolling と一致しない')
    we = sum(1 for _, c in d if c > 0)
    if we != ro['wins']:
        ro['wins_nx_common_rounded'] = ro['wins']
        ro['win_rate_nx_common_rounded'] = ro['win_rate']
        ro['wins_changed_by_rounding'] = [[y, round(c * 100, 6)] for y, c in d if c > 0 and round(c * 100, 2) <= 0]
        FIXROWS.append({'where': where, 'kind': 'rolling20', 'windows': len(d),
                        'before_nx_common_rounded': {'wins': ro['wins'], 'win_rate': ro['win_rate']},
                        'after_unrounded': {'wins': we, 'win_rate': round(we / len(d), 3)},
                        'windows_changed_start_year_and_diff_pct_per_year': ro['wins_changed_by_rounding']})
    ro['wins'] = we
    ro['win_rate'] = round(we / len(d), 3)
    return ro


def dca_x(s, b, years=20, step=12, where=None):
    """nx_common.dca と同じ戻り値。ただし win_rate は丸める前の倍率 > 1 で数える"""
    ro = N.dca(s, b, years, step)
    if not ro:
        return ro
    ks = sorted(set(s) & set(b))
    n = years * 12
    raw = []
    for i in range(0, len(ks) - n + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        raw.append((ks[i], ws / wb))
    if len(raw) != ro['windows'] or round(sum(1 for _, r in raw if round(r, 3) > 1) / len(raw), 3) != ro['win_rate']:
        raise SystemExit('dca_x: 窓の切り方が nx_common.dca と一致しない')
    wr = round(sum(1 for _, r in raw if r > 1) / len(raw), 3)
    if wr != ro['win_rate']:
        ro['win_rate_nx_common_rounded'] = ro['win_rate']
        ro['wins_changed_by_rounding'] = [[k, r] for k, r in raw if r > 1 and round(r, 3) <= 1]
        FIXROWS.append({'where': where, 'kind': 'dca20', 'windows': len(raw),
                        'before_nx_common_rounded': {'win_rate': ro['win_rate']}, 'after_unrounded': {'win_rate': wr},
                        'windows_changed_start_month_and_ratio': ro['wins_changed_by_rounding']})
    ro['win_rate'] = wr
    return ro


# ───────────────────────── 統計の小道具 ─────────────────────────
def halves(r, b):
    ks = sorted(set(r) & set(b))
    n = len(ks)
    f, s = ks[:n // 2], ks[n // 2:]
    return N.excess_stats(r, b, a=f[0], z=f[-1]), N.excess_stats(r, b, a=s[0], z=s[-1]), (f[0], f[-1], s[0], s[-1])


def drop_top_year(r, b):
    ks = sorted(set(r) & set(b))
    yrs = {}
    for k in ks:
        yrs.setdefault(k // 100, []).append(k)
    ann = {}
    for y, mm in yrs.items():
        pr = math.prod(1 + r[k] for k in mm); pb = math.prod(1 + b[k] for k in mm)
        ann[y] = pr - pb
    top = max(ann, key=ann.get)
    r2 = {k: v for k, v in r.items() if k // 100 != top}
    return N.excess_stats(r2, b), top, round(ann[top] * 100, 2), len(yrs[top])


def mdd(r, ks):
    return round(N.maxdd({k: r[k] for k in ks}) * 100, 1)


def sub(d, a=None, z=None):
    return {k: v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)}


def hac_ols(y, X, lag=12):
    """OLS と Newey-West（Bartlett）の標準誤差"""
    X = np.asarray(X, float); y = np.asarray(y, float)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    u = X * e[:, None]
    Sm = u.T @ u
    n = len(y)
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        G = u[L:].T @ u[:-L]
        Sm += w * (G + G.T)
    V = XtX_inv @ Sm @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return beta, beta / se, r2


# ───────────────────────── 因子（R4）と JKP（R7） ─────────────────────────
def load_factors():
    ff = N.ff_factors()
    f5 = [v for v in N.french_tables('F-F_Research_Data_5_Factors_2x3').values() if v['freq'] == 'monthly'][0]
    mo = [v for v in N.french_tables('F-F_Momentum_Factor').values() if v['freq'] == 'monthly'][0]
    fac = {}
    cols5 = [c.lower().replace('-', '') for c in f5['cols']]
    for d, row in f5['data'].items():
        if None in row:
            continue
        x = dict(zip(cols5, [v / 100 for v in row]))
        fac[d] = [x['mktrf'], x['smb'], x['hml'], x['rmw'], x['cma']]
    mom = {d: row[0] / 100 for d, row in mo['data'].items() if row[0] is not None}
    fac = {d: v + [mom[d]] for d, v in fac.items() if d in mom}
    return ff, fac, mom


def market_ew(rf):
    """等分の市場（総リターン・小数）。主: JKP usa mkt（ew・超過）＋ French RF。照合: French の時価の十分位（Portfolios_Formed_on_ME）の
    等分リターンを各月の社数で加重＝全上場の等分の再構成。取れなければ (None, None, 理由)"""
    err = []
    ew = ew_fr = None
    try:
        jk = N.jkp_mkt('usa', 'ew')
        ew = {k: v + rf[k] for k, v in jk.items() if k in rf}
    except Exception as ex_:  # noqa
        err.append(f'JKP usa mkt ew の取得に失敗: {ex_}')
    try:
        t = N.french_tables('Portfolios_Formed_on_ME')
        et, nt = t['Average Equal Weighted Returns -- Monthly'], t['Number of Firms in Portfolios']
        dec = ['Lo 10'] + [f'{i}-Dec' for i in range(2, 10)] + ['Hi 10']  # French の CSV の十分位の列名（Excel 流に '2-Dec' と書かれている）
        if not all(c in et['cols'] and c in nt['cols'] for c in dec):
            raise KeyError(f'十分位の列が無い: {et["cols"]}')
        ew_fr = {}
        for d, row in et['data'].items():
            if d not in nt['data']:
                continue
            rr, nn = dict(zip(et['cols'], row)), dict(zip(nt['cols'], nt['data'][d]))
            if any(rr[c] is None or nn[c] is None for c in dec) or sum(nn[c] for c in dec) <= 0:
                continue
            ew_fr[d] = sum(nn[c] * rr[c] for c in dec) / sum(nn[c] for c in dec) / 100
    except Exception as ex_:  # noqa
        err.append(f'French の等分の再構成に失敗: {ex_}')
        ew_fr = None
    if ew is None and ew_fr:
        ew, ew_fr = ew_fr, None
        err.append('主の JKP が取れないので French の再構成を主に使った')
    return ew, ew_fr, (err or None)


def factor_alpha(r, rf, fac, a=None, z=None):
    ks = sorted(k for k in r if k in fac and k in rf and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 36:
        return None
    y = [r[k] - rf[k] for k in ks]
    X = [[1.0] + fac[k] for k in ks]
    beta, t, r2 = hac_ols(y, X)
    names = ['alpha', 'mktrf', 'smb', 'hml', 'rmw', 'cma', 'umd']
    return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'alpha_ann': round(beta[0] * 1200, 2), 't_alpha': round(float(t[0]), 2),
            'loadings': {n: round(float(b), 3) for n, b in zip(names[1:], beta[1:])},
            't_loadings': {n: round(float(x), 2) for n, x in zip(names[1:], t[1:])}, 'r2': round(float(r2), 3)}


# ───────────────────────── 1本の規則を測る ─────────────────────────
def measure(rid, r, tov, tov_ew, b, rf, fam, pub, fac):
    ks = sorted(set(r) & set(b))
    a, z = ks[0], ks[-1]
    rc1, rc3 = with_cost(r, tov, UNIT), with_cost(r, tov, UNIT3)
    res = {'window': {'from': a, 'to': z, 'months': len(ks), 'train_months': sum(1 for k in ks if k <= TE), 'hold_months': sum(1 for k in ks if k >= HS)}}
    g = lambda s, **kw: N.excess_stats(s, b, **kw)
    res['gross'] = {'full': g(r), 'train': g(r, z=TE), 'hold': g(r, a=HS), 'recent_201307': g(r, a=RS)}
    res['cost_010'] = {'full': g(rc1), 'train': g(rc1, z=TE), 'hold': g(rc1, a=HS), 'recent_201307': g(rc1, a=RS)}
    res['cost_030'] = {'full': g(rc3), 'train': g(rc3, z=TE), 'hold': g(rc3, a=HS)}
    if tov_ew is not None:
        rce = with_cost(r, tov_ew, UNIT)
        res['cost_010_ew_turnover_sensitivity'] = {'full': g(rce), 'hold': g(rce, a=HS)}
    res['roll20_cost010'] = rolling_x(rc1, b, years=20, start_month=7, where=f'results.{rid}.res.roll20_cost010（C4・長い歴史の線の格付けに使う）')
    res['roll20_gross'] = rolling_x(r, b, years=20, start_month=7, where=f'results.{rid}.res.roll20_gross（報告のみ）')
    res['dca20_cost010'] = dca_x(rc1, b, 20, where=f'results.{rid}.res.dca20_cost010（R9・報告のみ）')
    res['maxdd_pct'] = {'rule_gross': mdd(r, ks), 'rule_cost010': mdd(rc1, ks), 'bench': mdd(b, ks),
                        'rule_gross_hold': mdd(r, [k for k in ks if k >= HS]), 'bench_hold': mdd(b, [k for k in ks if k >= HS])}
    sp = lambda s, **kw: N.sharpe(s, rf, **kw)
    res['sharpe'] = {'note': '報告のみ（C8 は N/A＝株100%・借入なし・時期選びなし）',
                     'full': {'rule': sp(r, a=a, z=z), 'rule_cost010': sp(rc1, a=a, z=z), 'bench': sp(b, a=a, z=z)},
                     'train': {'rule': sp(r, a=a, z=TE), 'rule_cost010': sp(rc1, a=a, z=TE), 'bench': sp(b, a=a, z=TE)},
                     'hold': {'rule': sp(r, a=HS, z=z), 'rule_cost010': sp(rc1, a=HS, z=z), 'bench': sp(b, a=HS, z=z)}}
    if pub:
        res['R5_pre_post_publication'] = {'post_from': pub, 'pre': g(r, z=pub - 1 if pub % 100 != 1 else (pub // 100 - 1) * 100 + 12), 'post': g(r, a=pub),
                                          'post_cost010': g(rc1, a=pub)}
    res['R4_factor_alpha'] = {'full': factor_alpha(r, rf, fac), 'train': factor_alpha(r, rf, fac, z=TE), 'hold': factor_alpha(r, rf, fac, a=HS)}
    ann_turn_hold = 12 * S.mean([tov[k] for k in ks if k >= HS]) if any(k >= HS for k in ks) else None
    h = res['gross']['hold']
    res['R8_break_even_unit_pct'] = {'hold_cagr_diff_gross_pct': h['cagr_diff'] if h else None, 'annual_turnover_hold_charged': round(ann_turn_hold, 3) if ann_turn_hold else None,
                                     'break_even_unit_pct': (round(h['cagr_diff'] / ann_turn_hold, 3) if h and ann_turn_hold and h['cagr_diff'] > 0 else None),
                                     'note': '保有期間の費用前の幾何の年率差（%）÷ 年間の片道の回転＝勝ちが消える単価（%/片道100%）。差が0以下なら空欄（費用前から負け）'}
    if fam in ('Q', 'XS'):
        fh, sh, cut = halves(r, b)
        dt, topy, topv, topn = drop_top_year(r, b)
        res['short'] = {'first_half': fh, 'second_half': sh, 'halves_cut': cut,
                        'drop_top_year': dt, 'dropped_year': topy, 'dropped_year_excess_pct': topv, 'dropped_year_months': topn,
                        'cost_full': res['cost_010']['full'], 'lower_bound_cost030_full': res['cost_030']['full']}
    return res, rc1


def summarize(e):
    """tested の1行（格付けと主な数字）"""
    gs, c1, c3 = e['res']['gross'], e['res']['cost_010'], e['res']['cost_030']
    pick = lambda s, k: (s or {}).get(k)
    role = {'P': '主（長い歴史）', 'Q': '主（短い標本）', 'XL': '探索（長い歴史の線）', 'XS': '探索（短い標本の線）', 'R': '報告のみ'}[e['fam']]
    row = {'rule': e['id'], 'family': e['fam'], 'role': role, 'signal': e.get('signal'), 'grade': e['grade'],
           'full_ex_ann': pick(gs['full'], 'ex_ann'), 'full_t': pick(gs['full'], 't'), 'full_cagr_diff': pick(gs['full'], 'cagr_diff'),
           'train_ex_ann': pick(gs['train'], 'ex_ann'), 'train_t': pick(gs['train'], 't'),
           'hold_ex_ann': pick(gs['hold'], 'ex_ann'), 'hold_t': pick(gs['hold'], 't'), 'hold_cagr_diff': pick(gs['hold'], 'cagr_diff'),
           'hold_cost010_cagr_diff': pick(c1['hold'], 'cagr_diff'), 'full_cost010_cagr_diff': pick(c1['full'], 'cagr_diff'),
           'full_cost030_cagr_diff': pick(c3['full'], 'cagr_diff'),
           'roll20_win_rate_cost010': pick(e['res']['roll20_cost010'], 'win_rate'), 'dca20_median_ratio_cost010': pick(e['res']['dca20_cost010'], 'median_ratio'),
           'holm': e.get('holm_p'), 'window': [e['res']['window']['from'], e['res']['window']['to']]}
    return row


# ───────────────────────── 事後の診断（結果を見た後に足した・格付けに使わない） ─────────────────────────
def capm(r, rf, mkt_rf, a=None, z=None):
    ks = sorted(k for k in r if k in rf and k in mkt_rf and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 36:
        return None
    beta, t, r2 = hac_ols([r[k] - rf[k] for k in ks], [[1.0, mkt_rf[k]] for k in ks])
    return {'from': ks[0], 'to': ks[-1], 'alpha_ann': round(beta[0] * 1200, 2), 't_alpha': round(float(t[0]), 2), 'beta': round(float(beta[1]), 3), 'r2': round(float(r2), 3)}


def posthoc(E, RC1, b, rf, mktrf, r3=None):
    """事後。格付け A・B の規則の勝ちの中身を分ける（どの年から来たか・β で説明できるか・公表後・費用後の保有期間）"""
    out = {'note': '【事後】結果（格付け）を見た後に足した診断。格付け・判定には使わない。対象は主と探索の族で A か B の規則',
           'rules': {}}
    tg = [rid for rid, e in E.items() if e['fam'] in ('P', 'Q', 'XL', 'XS') and e['grade'][0] in ('S', 'A', 'B')]
    for rid in tg:
        e = E[rid]
        r, rc = e['s'], RC1[rid]
        ks = sorted(set(r) & set(b))
        yrs = {}
        for k in ks:
            yrs.setdefault(k // 100, []).append(k)
        ann = {y: round((math.prod(1 + r[k] for k in mm) - math.prod(1 + b[k] for k in mm)) * 100, 2) for y, mm in yrs.items()}
        logex = {y: math.fsum(math.log1p(r[k]) - math.log1p(b[k]) for k in mm) for y, mm in yrs.items()}
        tot = math.fsum(logex.values())
        bub = math.fsum(v for y, v in logex.items() if 1999 <= y <= 2002)
        r_x = {k: v for k, v in r.items() if not (1999 <= k // 100 <= 2002)}
        rc_x = {k: v for k, v in rc.items() if not (1999 <= k // 100 <= 2002)}
        # 訓練期間だけで推した β で市場を伸ばした相手（β を上げただけの勝ちかを見る）
        cp_tr = capm(r, rf, mktrf, z=TE)
        levb = None
        if cp_tr:
            bt = cp_tr['beta']
            lev = {k: rf[k] + bt * mktrf[k] for k in ks if k in rf and k in mktrf}
            levb = {'beta_from_train': bt, 'hold_gross_vs_beta_market': N.excess_stats(r, lev, a=HS), 'hold_cost010_vs_beta_market': N.excess_stats(rc, lev, a=HS),
                    'full_gross_vs_beta_market': N.excess_stats(r, lev)}
        hc = N.excess_stats(rc, b, a=HS)
        out['rules'][rid] = {
            'grade': e['grade'], 'family': e['fam'],
            'annual_excess_pct_by_year_gross': ann,
            'top5_years': sorted(ann.items(), key=lambda x: -x[1])[:5], 'bottom5_years': sorted(ann.items(), key=lambda x: x[1])[:5],
            'share_of_log_excess_from_1999_2002': round(bub / tot, 3) if tot else None, 'log_excess_total': round(tot, 4), 'log_excess_1999_2002': round(bub, 4),
            'without_1999_2002_gross': N.excess_stats(r_x, b), 'without_1999_2002_cost010': N.excess_stats(rc_x, b),
            'capm': {'full': capm(r, rf, mktrf), 'train': cp_tr, 'hold': capm(r, rf, mktrf, a=HS)},
            'vs_beta_matched_market': levb,
            'hold_cost010': hc, 'hold_cost010_p_one': round(N.p_one(hc['t']), 4) if hc and hc['t'] is not None else None,
            'post_publication_cost010': (e['res'].get('R5_pre_post_publication') or {}).get('post_cost010'),
        }
    # 勝ちの規則どうしの重なり（全期間の月次の超過の相関）
    ex = {rid: {k: E[rid]['s'][k] - b[k] for k in E[rid]['s'] if k in b} for rid in tg}
    cm = {}
    for i in tg:
        cm[i] = {}
        for j2 in tg:
            kk = sorted(set(ex[i]) & set(ex[j2]))
            cm[i][j2] = round(N.corr([ex[i][k] for k in kk], [ex[j2][k] for k in kk]), 3) if len(kk) >= 36 else None
    out['corr_of_monthly_excess_among_targets'] = cm
    # 族を問わず、保有期間（2007〜）に費用後で市場に勝った規則の一覧（格付けではない）
    lst = []
    for rid, e in E.items():
        h = e['res']['cost_010']['hold']
        if h and h['cagr_diff'] > 0:
            lst.append({'rule': rid, 'family': e['fam'], 'grade': e['grade'], 'hold_cost010_cagr_diff': h['cagr_diff'], 'hold_cost010_t': h['t'],
                        'hold_cost010_p_one': round(N.p_one(h['t']), 4) if h['t'] is not None else None})
    out['hold_cost010_winners_any_family'] = {'count': len(lst), 'of': len(E), 'rows': sorted(lst, key=lambda x: -x['hold_cost010_cagr_diff'])}
    # 長い歴史の線の族（P・XL）で費用前の C1 と C2 がともに成り立った割合（R3 の偽物の基礎率と並べる）
    c12 = {f: [rid for rid, e in E.items() if e['fam'] == f and e['checks'] and e['checks'].get('C1_train') and e['checks'].get('C2_hold_sign')] for f in ('P', 'XL')}
    # 是正 F2（2026-09-28 v2）: 偶然の基礎率は同じ重みどうしで並べる。P・XL は全部 時価加重の組 対 時価加重の French Mkt。
    # 時価加重の偽物は4本しかないので、いちばん近い代わりは 等分の偽物 対 等分の市場。登録どおりの率（等分の偽物 対 時価加重の市場）は並べない
    sw = (r3 or {}).get('same_weight') or {}
    base_ew = (sw.get('ew_placebos_vs_ew_market') or {}).get('rate_C1_and_C2')

    def binom_tails(k, n, p):
        if p is None or n == 0:
            return None
        pmf = [math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(n + 1)]
        return {'p_at_least_k': round(math.fsum(pmf[k:]), 4), 'p_at_most_k': round(math.fsum(pmf[:k + 1]), 4)}
    cmpx = {}
    for f, v in c12.items():
        n = sum(1 for e in E.values() if e['fam'] == f)
        cmpx[f] = {'rules': v, 'count': len(v), 'of': n, 'rate': round(len(v) / n, 3) if n else None, 'weighting': '時価加重の組 対 時価加重の French Mkt',
                   'binomial_vs_ew_placebo_same_weight_rate': binom_tails(len(v), n, base_ew)}
    out['C1_and_C2_pre_cost_rate_vs_placebo'] = dict(cmpx, **{
        'placebo_same_weight': {'EW_placebos_vs_EW_market': sw.get('ew_placebos_vs_ew_market'),
                                'EW_placebos_vs_French_EW_crosscheck': sw.get('ew_placebos_vs_french_ew_crosscheck'),
                                'VW_placebos_vs_French_Mkt': sw.get('vw_placebos_vs_french_mkt')},
        'placebo_registered_mixed_weights_not_comparable': (r3 or {}).get('all'),
        'note': '【是正 F2】P・XL の率は時価加重どうし。偽物の基礎率も同じ重みどうしで並べる: 時価加重の偽物は4本だけ（率にならない）なので、等分の偽物 対 等分の市場 を'
                'いちばん近い代わりにした。登録どおりの R3 の all（等分の偽物110本を時価加重の French Mkt と比べた 10.6%）は重みが混ざっていて並べられない。'
                '二項の裾（binomial_vs_ew_placebo_same_weight_rate）は族の規則を独立な試行とみなした記述だけ（同じ信号の五分位・十分位・2×3 が並ぶので独立ではない）。格付けに使わない'})
    return out


# ───────────────────────── 本体 ─────────────────────────
def main():
    pre, j, turn, shainfo = load()
    PR = prereg_rules(pre)
    ff, fac, mom = load_factors()
    b_all, rf = ff['mkt'], ff['rf']
    log('指紋一致', shainfo['rules_sha256'][:12], shainfo['series_sha256_recomputed'][:12], 'French Mkt', min(b_all), max(b_all))

    E = {}
    tov_by = {}
    for r in RULES:
        if r['signal'] == 'MIX':
            continue
        s, nlong, a, z = rule_series(j, r)
        p = PR[r['id']]
        if (p['eval_from'], p['eval_to']) != (a, z):
            raise SystemExit(f'{r["id"]}: 評価の窓が事前登録と違う {p["eval_from"]}-{p["eval_to"]} vs {a}-{z}')
        tov, tinfo = turnover_series(turn, r, s)
        tov_ew = None
        if r['file'] != 'ff93':
            tov_ew, _ = turnover_series(turn, r, s, key='monthly_ew')
        tov_by[r['id']] = tov
        E[r['id']] = {'id': r['id'], 'fam': r['fam'], 'signal': r['signal'], 'file': r['file'], 'port': r['port'], 's': s, 'tov': tov, 'tov_ew': tov_ew,
                      'turnover_info': tinfo, 'pub': (p.get('op') or {}).get('post_publication_from'), 'nlong_median': S.median([v for v in nlong.values() if v is not None])}
    # MIX（全構成がそろう月だけ・等分）
    for r in RULES:
        if r['signal'] != 'MIX':
            continue
        parts = r['parts']
        common = sorted(set.intersection(*[set(E[pp]['s']) for pp in parts]))
        s = {m: S.mean(E[pp]['s'][m] for pp in parts) for m in common}
        tov = {m: S.mean(E[pp]['tov'][m] for pp in parts) for m in common}
        tov_ew = {m: S.mean(E[pp]['tov_ew'][m] for pp in parts) for m in common} if all(E[pp]['tov_ew'] for pp in parts) else None
        p = PR.get(r['id']) or next(x for x in pre['families']['XL_exploratory_long'] + pre['families']['XS_exploratory_short'] if x['id'] == r['id'])
        if (p['eval_from'], p['eval_to']) != (common[0], common[-1]):
            raise SystemExit(f'{r["id"]}: MIX の窓が事前登録と違う {p["eval_from"]}-{p["eval_to"]} vs {common[0]}-{common[-1]}')
        E[r['id']] = {'id': r['id'], 'fam': r['fam'], 'signal': 'MIX', 'parts': parts, 's': s, 'tov': tov, 'tov_ew': tov_ew,
                      'turnover_info': {'kind': 'mean_of_parts_monthly', 'charged_annual_all': round(12 * S.mean(tov.values()), 3),
                                        'charged_annual_hold': round(12 * S.mean([v for k, v in tov.items() if k >= HS]), 3)}, 'pub': None}
    log('系列', len(E), '本')
    DEV.append('事前登録 tools.sha_note の文言は「series を json.dumps した sha256」だが、データの道具（cmd_ports）と事前登録の値は {\'series\': series} を包んだ sha256。包んだ計算で事前登録の値と一致したので止めずに進めた（数字は測る前のもの・格付けに影響なし）。包まない値も fingerprints に併記')
    DEV.append('R2（論文どおりの組）の評価の窓は事前登録に書かれていないので、対応する主の規則と同じ窓（eval_from〜eval_to）に揃えた（報告のみ・格付けに影響なし）')
    DEV.append('Q・XS の各規則に、長い歴史の線 C1〜C8 を同じ数字に当てた結果を long_criteria_reference_not_used として参考に併記した（事前登録に無い追加の報告。格付けには使わない）')
    DEV.append('シャープ・最大下落・CAPM を全規則に報告として併記した（C8 は事前登録どおり N/A のまま）。post_hoc_事後 の節は結果を見た後の追加の診断で、格付けには使わない')
    NOTES.append('2×3 の BH の費用は事前登録 cost_assumption.ff93_BH の文言どおり毎月 1.0×単価/12 だけを引いた（最初の月に別途 1.0 の買い付けは足していない。足しても全期間で一度きりの 0.10%）')
    NOTES.append('MIX の費用は事前登録どおり構成の規則の毎月の回転の平均（各構成の最初の月の 1.0 はその構成の開始月にだけ入る。MIX6 の最初の月 1985-01 は P2 の開始月と同じなので P2 の 1.0 が平均に入る）。MIX 自身の最初の月に 1.0 を置き直してはいない（差は一度きり 0.1% 未満）')
    NOTES.append('短い標本の drop_top（代用）の暦年は窓の端の欠けた年（例 1996年は2月から）もその月だけで積を取った（事前登録は暦年とだけ書いている）')
    NOTES.append('回転の値が無い月を埋める中央値は、その規則の評価の窓（eval_from〜eval_to）の中の月次の回転の中央値（事前登録の「その規則の全期間」を評価の窓と読んだ）。主の9本で埋めた月は0')

    # 測る
    RC1 = {}
    for rid, e in E.items():
        e['res'], RC1[rid] = measure(rid, e['s'], e['tov'], e['tov_ew'], b_all, rf, e['fam'], e['pub'], fac)
    log('測定済み')

    # Holm（族ごと）
    holm = {}
    for fam in ('P', 'XL'):
        ids = [x['id'] for x in RULES if x['fam'] == fam]
        holm[fam] = N.holm({i: (E[i]['res']['gross']['hold'] or {}).get('p') for i in ids})
    for fam in ('Q', 'XS'):
        ids = [x['id'] for x in RULES if x['fam'] == fam]
        pv = {}
        for i in ids:
            f = E[i]['res']['gross']['full']
            pv[i] = N.p_one(f['t']) if f and f['t'] is not None else None
        holm[fam] = N.holm(pv)
    # 格付け
    for rid, e in E.items():
        res, fam = e['res'], e['fam']
        gs, c1 = res['gross'], res['cost_010']
        if fam in ('P', 'XL'):
            e['holm_p'] = holm[fam].get(rid)
            gr, ck = N.grade(gs['full'], gs['train'], gs['hold'], res['roll20_cost010'], cost_hold=c1['hold'], repl=None,
                             family_holm_p=e['holm_p'], sharpe_pair=None, leveraged_or_timing=False)
            e['grade'], e['checks'] = gr, ck
            e['criteria'] = 'criteria_long_history（C1〜C8）' + ('・探索' if fam == 'XL' else '・主')
        elif fam in ('Q', 'XS'):
            e['holm_p'] = holm[fam].get(rid)
            sh = res['short']
            gr, ck = N.grade_short(gs['full'], sh['first_half'], sh['second_half'], sh['drop_top_year'], sh['cost_full'], sh['lower_bound_cost030_full'],
                                   family_holm_p_one=e['holm_p'])
            e['grade'] = gr + ('（代用あり）' if gr == 'S' else '')
            e['checks'] = ck
            e['criteria'] = 'criteria_short_sample' + ('・探索' if fam == 'XS' else '・主') + '（drop_top は最大の暦年を抜く代用・lower_bound は費用0.30%の代用）'
            # 参考（格付けに使わない）: 長い歴史の線 C1〜C8 を同じ数字に当てた場合
            g2, ck2 = N.grade(gs['full'], gs['train'], gs['hold'], res['roll20_cost010'], cost_hold=c1['hold'], repl=None, family_holm_p=None)
            e['long_criteria_reference_not_used'] = {'grade': g2, 'checks': ck2, 'note': '参考のみ・格付けに使わない（事前登録は短い標本の線。訓練が15年に満たない）。C7 は Holm なし＝全期間 t≥3 だけ'}
        else:
            e['holm_p'] = None
            e['grade'] = '報告のみ（格付けしない）'
            e['checks'] = None
            e['criteria'] = 'R（事前登録 R_report_only_rules）'
    # 丸めた勝ちの数（nx_common.rolling のまま）で格付けした場合と突き合わせる（是正 F1 の前後）
    for fr in FIXROWS:
        if fr['kind'] != 'rolling20' or 'roll20_cost010' not in fr['where']:
            continue
        rid = fr['where'].split('.')[1]
        e = E[rid]
        res, gs, c1 = e['res'], e['res']['gross'], e['res']['cost_010']
        ro = res['roll20_cost010']
        ro_r = dict(ro, wins=ro['wins_nx_common_rounded'], win_rate=ro['win_rate_nx_common_rounded'])
        if e['fam'] in ('P', 'XL'):
            gb, cb = N.grade(gs['full'], gs['train'], gs['hold'], ro_r, cost_hold=c1['hold'], repl=None, family_holm_p=e['holm_p'])
            fr.update({'graded_by': '長い歴史の線（C1〜C8）', 'C4_before': cb['C4_roll20'], 'C4_after': e['checks']['C4_roll20'],
                       'grade_before': gb, 'grade_after': e['grade']})
        elif e['fam'] in ('Q', 'XS'):
            gb, cb = N.grade(gs['full'], gs['train'], gs['hold'], ro_r, cost_hold=c1['hold'], repl=None, family_holm_p=None)
            fr.update({'graded_by': '短い標本の線（C4 は使わない）。長い歴史の線の参考（long_criteria_reference_not_used）だけに効く',
                       'C4_before': cb['C4_roll20'], 'C4_after': e['long_criteria_reference_not_used']['checks']['C4_roll20'],
                       'reference_grade_before': gb, 'reference_grade_after': e['long_criteria_reference_not_used']['grade'], 'grade': e['grade']})
        else:
            fr.update({'graded_by': '報告のみ（格付けしない）', 'C4_before': ro_r['win_rate'] >= 0.8, 'C4_after': ro['win_rate'] >= 0.8})
    log('格付け済み')

    # ───── 報告 R1〜R9 ─────
    reports = {}
    main9 = ['P1_ShortInterest_q5vw', 'P2_CredRatDG_notDG_vwf', 'P3_REV6_q5vw', 'P4_AnalystRevision_q5vw', 'P5_ForecastDispersion_q5vw',
             'P6_fgr5yrLag_q5vw', 'Q1_ConsRecomm_strongbuy_op', 'Q2_ChangeInRecommendation_q5vw', 'Q3_skew1_q5vw']
    RR = {x['id']: x for x in RULES}
    # R1 買い−売り
    r1 = {}
    for rid in main9:
        x = RR[rid]
        f = x['file']
        ls = j['series'][f][x['signal']]['LS']
        a, z = E[rid]['res']['window']['from'], E[rid]['res']['window']['to']
        d = {int(m): v[0] / 100 for m, v in ls.items() if v[0] is not None and a <= int(m) <= z}

        def st(dd):
            v = list(dd.values())
            if len(v) < 24:
                return None
            t = N.nw_t(v)
            return {'from': min(dd), 'to': max(dd), 'months': len(v), 'mean_pct_month': round(S.mean(v) * 100, 3), 'mean_ann_pct': round(S.mean(v) * 1200, 2),
                    't': round(t, 2) if t is not None else None}
        r1[rid] = {'file': f, 'LS': '05−01' if x['port'] == '05' else '02−01', 'full': st(d), 'train': st(sub(d, z=TE)), 'hold': st(sub(d, a=HS)),
                   'op_reported': pre['prior']['op_reported'].get(x['signal'])}
    reports['R1_LS'] = {'note': '買い−売り（OSAP の LS 列＝良い側−悪い側・恒等を確認済み）。データが論文の効果の向きを再現しているかの確認だけ。格付けしない', 'rules': r1}
    # R2 論文どおりの組の良い側
    r2 = {}
    for rid in main9:
        x = RR[rid]
        d = j['series']['op'][x['signal']]
        top = max((k for k in d if k != 'LS'), key=int)
        a, z = E[rid]['res']['window']['from'], E[rid]['res']['window']['to']
        s = {int(m): v[0] / 100 for m, v in d[top].items() if v[0] is not None and a <= int(m) <= z}
        doc = (PR[rid].get('op') or {})
        r2[rid] = {'op_port': top, 'op_stock_weight': doc.get('op_stock_weight'), 'full': N.excess_stats(s, b_all), 'train': N.excess_stats(s, b_all, z=TE),
                   'hold': N.excess_stats(s, b_all, a=HS)}
    reports['R2_op_style'] = {'note': '論文どおりの組（PredictorPortsFull・重みも論文どおり＝多くは等分）の良い側 対 French Mkt・費用前・同じ評価の窓。等分は小型株に傾く参考。格付けしない', 'rules': r2}
    # R3 偽物の基礎率
    doc = {x['Acronym']: x for x in csv.DictReader(open(os.path.join(N.CACHE, FILES['doc'][1]), encoding='utf-8-sig'))}
    # 偽物の組の重み（是正 F2・2026-09-28 v2）: OSAP は SignalDoc の 'Stock Weight' を sweight に読み（Portfolios/Code/00_SettingsAndTools.R）、
    # 'NA' は readr の既定で欠測→ 01_PortfolioFunction.R の `if (is.na(sweight)) {sweight = 'EW'}` で等分、さらに sweight=='VW' 以外は
    # weight=1（等分）。偽物（40_PlaceboPorts.R は同じ loop_over_strategies）も同じ。＝'VW' だけが時価加重、それ以外は等分。
    ew_mkt, ew_mkt_fr, ew_err = market_ew(rf)

    def placebo_weight(sname):
        w = (doc.get(sname, {}).get('Stock Weight') or '').strip()
        return ('VW', w) if w == 'VW' else ('EW', w or 'NA')

    def c12(s, bench):
        tr = N.excess_stats(s, bench, z=TE); ho = N.excess_stats(s, bench, a=HS)
        c1 = bool(tr and tr['ex_ann'] > 0 and (tr['t'] or 0) >= 2.0)
        c2 = bool(ho and ho['ex_ann'] > 0 and ho['cagr_diff'] > 0)
        return tr, ho, c1, c2

    r3rows = []
    for sname, v in j['series']['placebo'].items():
        d = v['long']
        ms = sorted(int(m) for m in d)
        wkind, wdoc = placebo_weight(sname)
        thin = [m for m in ms if d[str(m)][1] is None or d[str(m)][1] < 20]
        a = ms[0] if not thin else next((m for m in ms if m > max(thin)), None)
        if a is None:
            r3rows.append({'signal': sname, 'cat': doc.get(sname, {}).get('Cat.Data'), 'stock_weight': wkind, 'stock_weight_signaldoc': wdoc,
                           'eligible': False, 'why': '組の銘柄数が最後まで20未満'})
            continue
        s = {m: d[str(m)][0] / 100 for m in ms if m >= a and d[str(m)][0] is not None}
        tr, ho, c1, c2 = c12(s, b_all)
        tm = sum(1 for m in s if m <= TE)
        elig = tm >= 180 and tr is not None and ho is not None
        row = {'signal': sname, 'cat': doc.get(sname, {}).get('Cat.Data'), 'stock_weight': wkind, 'stock_weight_signaldoc': wdoc,
               'long_port': v['long_port'], 'from': a, 'train_months': tm, 'eligible': elig,
               'C1': c1, 'C2': c2, 'C1_and_C2': c1 and c2, 'train_ex_ann': (tr or {}).get('ex_ann'), 'train_t': (tr or {}).get('t'),
               'hold_ex_ann': (ho or {}).get('ex_ann'), 'hold_cagr_diff': (ho or {}).get('cagr_diff')}
        # 同じ重みの市場と比べた版（等分の偽物は等分の市場・時価加重の偽物は French Mkt のまま）
        if wkind == 'EW' and ew_mkt:
            tr2, ho2, c1b, c2b = c12(s, ew_mkt)
            row.update({'same_weight_bench': 'EW（JKP usa mkt ew＋French RF）', 'C1_same_weight': c1b, 'C2_same_weight': c2b, 'C1_and_C2_same_weight': c1b and c2b,
                        'train_ex_ann_same_weight': (tr2 or {}).get('ex_ann'), 'train_t_same_weight': (tr2 or {}).get('t'),
                        'hold_ex_ann_same_weight': (ho2 or {}).get('ex_ann'), 'hold_cagr_diff_same_weight': (ho2 or {}).get('cagr_diff'),
                        'eligible_same_weight': elig and tr2 is not None and ho2 is not None})
            if ew_mkt_fr:
                _, _, c1f, c2f = c12(s, ew_mkt_fr)
                row.update({'C1_and_C2_vs_french_ew_crosscheck': c1f and c2f})
        elif wkind == 'VW':
            row.update({'same_weight_bench': 'VW（French Mkt）', 'C1_same_weight': c1, 'C2_same_weight': c2, 'C1_and_C2_same_weight': c1 and c2,
                        'eligible_same_weight': elig})
        r3rows.append(row)

    def rate(rows):
        el = [x for x in rows if x['eligible']]
        return {'eligible': len(el), 'C1': sum(x['C1'] for x in el), 'C2': sum(x['C2'] for x in el), 'C1_and_C2': sum(x['C1_and_C2'] for x in el),
                'rate_C1_and_C2': round(sum(x['C1_and_C2'] for x in el) / len(el), 3) if el else None}

    def rate_sw(rows, key='C1_and_C2_same_weight'):
        el = [x for x in rows if x.get('eligible_same_weight')]
        return {'eligible': len(el), 'C1': sum(x['C1_same_weight'] for x in el), 'C2': sum(x['C2_same_weight'] for x in el),
                'C1_and_C2': sum(x[key] for x in el), 'rate_C1_and_C2': round(sum(x[key] for x in el) / len(el), 3) if el else None}

    ew_rows = [x for x in r3rows if x['stock_weight'] == 'EW']
    vw_rows = [x for x in r3rows if x['stock_weight'] == 'VW']
    ew_tr = N.excess_stats(ew_mkt, b_all, z=TE) if ew_mkt else None
    ew_ho = N.excess_stats(ew_mkt, b_all, a=HS, z=202412) if ew_mkt else None
    sw = {'note': '【是正 F2（2026-09-28 v2）・事前登録の後に足した報告】偽物は同じ重みの市場と比べる。OSAP の偽物114本のうち時価加重は4本だけ（SignalDoc の Stock Weight が VW）、'
                  '残り110本は等分（NA 88本〔OSAP のコードで EW に置き換わる〕・EW 22本）。等分の組を時価加重の French Mkt と比べると、等分の市場そのものの超過'
                  f"（French Mkt に対し 訓練 {(ew_tr or {}).get('cagr_diff')}%/年・保有〔2007-01〜2024-12〕{(ew_ho or {}).get('cagr_diff')}%/年 の幾何差）が C1 を膨らませ C2 をしぼませる。"
                  '規則 P・XL は全部時価加重なので、比べる基礎率は同じ重みどうし',
          'ew_placebos_vs_ew_market': rate_sw(ew_rows) if ew_mkt else None,
          'ew_placebos_vs_french_ew_crosscheck': (rate_sw([x for x in ew_rows if 'C1_and_C2_vs_french_ew_crosscheck' in x], 'C1_and_C2_vs_french_ew_crosscheck') if ew_mkt_fr else None),
          'vw_placebos_vs_french_mkt': rate(vw_rows), 'vw_placebo_signals': [x['signal'] for x in vw_rows],
          'all_same_weight': rate_sw(r3rows) if ew_mkt else None,
          'ew_placebos_vs_french_mkt_mixed_weights': rate(ew_rows),
          'ew_market': {'primary': 'JKP usa mkt（ew・無リスク金利を引いた超過）＋ French RF', 'crosscheck': 'French Portfolios_Formed_on_ME の十分位の等分リターンを各月の社数で加重（全上場の等分の再構成）',
                        'primary_vs_french_mkt_train': ew_tr,
                        'primary_vs_french_mkt_hold_to_202412': ew_ho,
                        'primary_vs_french_mkt_hold_to_last': N.excess_stats(ew_mkt, b_all, a=HS) if ew_mkt else None,
                        'crosscheck_vs_primary_full': N.excess_stats(ew_mkt_fr, ew_mkt) if ew_mkt and ew_mkt_fr else None,
                        'error': ew_err},
          'caveat': '等分の偽物の基礎率は『時価加重の規則の基礎率』そのものではない（時価加重の偽物は4本しかなく率にならない）。等分の組は小型株に傾き、同じ等分の市場と比べてもなお小型の効果の分だけ時期によって振れる。いちばん近い代わりとして並べる'}
    reports['R3_placebo_base_rate'] = {'note': 'OSAP の偽物114本（最大の番号の組）対 French Mkt・費用前・開始は同じ機械の規則（組の銘柄数20未満の最後の月の翌月）。訓練15年以上のものの中で C1 と C2 がともに成り立つ割合＝偶然の基礎率。格付けしない。'
                                               '⚠ 登録どおりの all は重みが混ざっている（偽物の110本は等分の組・相手の French Mkt は時価加重）。時価加重の規則 P・XL と並べるのは same_weight の率（是正 F2）',
                                       'all': rate(r3rows), 'all_label': '登録どおり（対 French Mkt・重みの混在＝等分の偽物110本を時価加重の市場と比べている。時価加重の規則の率とは並べない）',
                                       'info_Analyst_Trading': rate([x for x in r3rows if x['cat'] in ('Analyst', 'Trading')]),
                                       'by_cat': {c: rate([x for x in r3rows if x['cat'] == c]) for c in sorted({x['cat'] for x in r3rows if x['cat']})},
                                       'by_stock_weight_vs_french_mkt': {'EW': rate(ew_rows), 'VW': rate(vw_rows)},
                                       'same_weight': sw,
                                       'info_Analyst_Trading_same_weight': rate_sw([x for x in r3rows if x['cat'] in ('Analyst', 'Trading')]),
                                       'rows': r3rows}
    # R4 は各規則の中（R4_factor_alpha）。ここは一覧
    reports['R4_factor_alpha_index'] = {rid: {k: ({'alpha_ann': v['alpha_ann'], 't_alpha': v['t_alpha']} if v else None) for k, v in e['res']['R4_factor_alpha'].items()} for rid, e in E.items()}
    reports['R4_note'] = '(r − RF) を French の Mkt-RF・SMB・HML・RMW・CMA（5因子2×3）・UMD（Mom）に回帰。alpha は年率%・NW t（ラグ12）。費用前'
    # R5・R6 は各規則の中。一覧
    reports['R5_pre_post_publication_index'] = {rid: ({'post_from': e['res']['R5_pre_post_publication']['post_from'],
                                                       'pre_cagr_diff': (e['res']['R5_pre_post_publication']['pre'] or {}).get('cagr_diff'),
                                                       'post_cagr_diff': (e['res']['R5_pre_post_publication']['post'] or {}).get('cagr_diff'),
                                                       'post_t': (e['res']['R5_pre_post_publication']['post'] or {}).get('t')} if 'R5_pre_post_publication' in e['res'] else None)
                                                for rid, e in E.items()}
    reports['R6_recent_201307_index'] = {rid: {'gross': e['res']['gross']['recent_201307'], 'cost010_cagr_diff': (e['res']['cost_010']['recent_201307'] or {}).get('cagr_diff')} for rid, e in E.items()}
    # R7 業績の勢いとの重なり
    try:
        gside, pn = N.jkp_good_side('usa', 'niq_su', 'vw_cap', upto=TE)
        jm = N.jkp_mkt('usa', 'vw_cap')
        niq = {m: pn[gside][m] - jm[m] for m in pn[gside] if m in jm}
        r7 = {'jkp_niq_su_good_side_by_train_only': gside}
        for rid in ('P3_REV6_q5vw', 'P4_AnalystRevision_q5vw', 'XL2_REV6_d10vw', 'XL3_AnalystRevision_d10vw'):
            s = E[rid]['s']
            ex = {m: s[m] - b_all[m] for m in s if m in b_all}
            out = {}
            for lab, a in (('full', None), ('hold', HS)):
                k1 = sorted(m for m in ex if m in niq and (a is None or m >= a))
                k2 = sorted(m for m in ex if m in mom and (a is None or m >= a))
                out[lab] = {'corr_niq_su_excess': round(N.corr([ex[m] for m in k1], [niq[m] for m in k1]), 3), 'months_niq': len(k1),
                            'corr_umd': round(N.corr([ex[m] for m in k2], [mom[m] for m in k2]), 3), 'months_umd': len(k2)}
            r7[rid] = out
        reports['R7_overlap_with_earnings_momentum'] = r7
    except Exception as ex_:  # noqa
        reports['R7_overlap_with_earnings_momentum'] = {'error': f'JKP の取得に失敗: {ex_}'}
        DEV.append(f'R7 を出せなかった（JKP の取得に失敗: {ex_}）')
    reports['R8_break_even_index'] = {rid: e['res']['R8_break_even_unit_pct'] for rid, e in E.items()}
    reports['R9_dca20_index'] = {rid: e['res']['dca20_cost010'] for rid, e in E.items()}
    log('報告済み')
    mktrf = {k: v[0] for k, v in fac.items()}
    ph = posthoc(E, RC1, b_all, rf, mktrf, reports['R3_placebo_base_rate'])
    log('事後の診断済み')

    # ───── 出力 ─────
    tested = [summarize(E[x['id']]) for x in RULES]
    grades = {}
    for fam in ('P', 'Q', 'XL', 'XS'):
        ids = [x['id'] for x in RULES if x['fam'] == fam]
        c = {}
        for i in ids:
            gg = E[i]['grade'][0]
            c[gg] = c.get(gg, 0) + 1
        grades[fam] = c
    results = {}
    for x in RULES:
        e = E[x['id']]
        results[x['id']] = {k: v for k, v in e.items() if k not in ('s', 'tov', 'tov_ew')}
        results[x['id']]['nlong_median'] = e.get('nlong_median')
    # ───── 是正の記録（検査役の指摘・2026-09-28 v2） ─────
    r3 = reports['R3_placebo_base_rate']
    sw = r3['same_weight']
    roll_rows = [fr for fr in FIXROWS if fr['kind'] == 'rolling20']
    grade_rows = [fr for fr in roll_rows if 'grade_before' in fr]
    c4_changed = [fr['where'] for fr in roll_rows if fr.get('C4_before') is not None and fr.get('C4_before') != fr.get('C4_after')]
    gr_changed = [fr['where'] for fr in grade_rows if fr['grade_before'] != fr['grade_after']] + \
                 [fr['where'] for fr in roll_rows if 'reference_grade_before' in fr and fr['reference_grade_before'] != fr['reference_grade_after']]
    ph_c = ph['C1_and_C2_pre_cost_rate_vs_placebo']
    fixes = [
        {'id': 'F1_rolling_rounding_2026-09-28',
         'reported_by': '検査役（独立の再計算: OSAP と French の原本を自前で読み直して全46本＋報告2本を別コードで再計算）',
         'what': 'nx_common.rolling が転がる20年窓の幾何差を %・小数2桁に丸めてから『>0』で勝ちを数えていた（nx_common.py L334・L338）。真の差が +0.001〜+0.005%/年 の窓が負けに数えられた。'
                 'nx_common.dca も倍率を小数3桁に丸めてから『>1』を数える同じ型（L353 付近）',
         'verified': '本当の誤り。C4 は「転がる20年窓で市場に勝った割合」＝差が正の窓の割合で、丸めは数え方の副作用（規則の誤読の是正であって事前登録の規則は変えていない）。'
                     '丸める前の差で数え直すと、検査役の挙げた7か所（P2 費用前 1997・Q1 費用後 1996・XL6 費用後 1982・XL17 費用前 1992・XL18 費用後 1998・XL20 費用後 2003・R_CredRatDG_from1970 費用前 1997）がそのまま出た（changes）。'
                     'dca（R9・報告のみ）は丸めで勝ちの数が変わった窓は ' + ('あった（changes の kind=dca20）' if any(fr['kind'] == 'dca20' for fr in FIXROWS) else '無かった（この角度では数字は変わらない）'),
         'how': '兄弟の角度 nx_osap_intang.py の F1 と同じ直し方にそろえた: この角度の中に rolling_x / dca_x を作り、nx_common と同じ窓で丸める前の差・倍率で勝ちを数える。丸めた値（median・worst・best）は表示にそのまま残す。'
                '窓の切り方は nx_common の戻り値と毎回照合（窓数・中央・丸めた勝ちの数が一致しなければ止まる）。nx_common.py は全角度の共通部品（mw_common.py と同一の定義）なので書き換えていない＝直すならまとめ役が全角度で同時に。'
                '丸めで変わった欄には wins_nx_common_rounded / win_rate_nx_common_rounded / wins_changed_by_rounding を残した',
         'changes': FIXROWS,
         'c4_changes': c4_changed, 'grade_changes': gr_changed,
         'result': f"丸めで勝ちの数が変わった箇所 {len(FIXROWS)} 件（転がる20年窓 {len(roll_rows)}・積立20年 {len(FIXROWS) - len(roll_rows)}）。"
                   f"格付けに使う欄（P・XL の roll20_cost010）は {len(grade_rows)} 件。C4 の合否が変わったもの {len(c4_changed)} 件・格付け（参考の格付けを含む）が変わったもの {len(gr_changed)} 件"},
        {'id': 'F2_placebo_weighting_2026-09-28',
         'reported_by': '検査役（悪魔の代弁者・反証を探す）',
         'what': 'R3 の偶然の基礎率（登録どおり: 偽物 対 French Mkt）は、偽物114本のうち110本が等分の組（SignalDoc の Stock Weight が NA 88・EW 22。NA は OSAP の 01_PortfolioFunction.R で EW に置き換わる）で、'
                 'それを時価加重の French Mkt と比べていた。その率（10.6%）を、時価加重の規則 P（2/6）・XL（1/21）と事後の節で並べていた',
         'verified': '本当の誤り（比べる相手の重みの不一致）。確かめたこと: (1) SignalDoc の偽物の Stock Weight は NA 88・EW 22・VW 4 (2) OSAP のコード（GitHub OpenSourceAP/CrossSection の Portfolios/Code）で '
                     "00_SettingsAndTools.R が 'Stock Weight' を sweight に読み、01_PortfolioFunction.R L86 `if (is.na(sweight)) {sweight = 'EW'}`・L269 で sweight=='VW' 以外は weight=1、"
                     '40_PlaceboPorts.R は同じ loop_over_strategies を使う (3) 等分の市場（JKP usa mkt ew＋French RF）は French Mkt に対し 訓練 '
                     f"{(sw['ew_market']['primary_vs_french_mkt_train'] or {}).get('cagr_diff')}%/年・保有（〜2024-12＝OSAP の最後の月）{(sw['ew_market']['primary_vs_french_mkt_hold_to_202412'] or {}).get('cagr_diff')}%/年 の幾何差"
                     f"（検査役の −4.1 は French の最後の月までの窓: {(sw['ew_market']['primary_vs_french_mkt_hold_to_last'] or {}).get('cagr_diff')}%/年。French の十分位から等分の市場を再構成した照合の系列は主の系列と全期間の幾何差 "
                     f"{(sw['ew_market']['crosscheck_vs_primary_full'] or {}).get('cagr_diff')}%/年で、偽物の率も同じ）。偽物の C1∧C2 の数は 等分どうし {sw['ew_placebos_vs_ew_market']['C1_and_C2']}/{sw['ew_placebos_vs_ew_market']['eligible']}・"
                     f"等分の偽物 対 時価加重の相手 {sw['ew_placebos_vs_french_mkt_mixed_weights']['C1_and_C2']}/{sw['ew_placebos_vs_french_mkt_mixed_weights']['eligible']}・"
                     f"時価加重の偽物 {sw['vw_placebos_vs_french_mkt']['C1_and_C2']}/{sw['vw_placebos_vs_french_mkt']['eligible']}（検査役の数 27/109・12/109・0/4 と照合）。R3 は報告のみで格付けには影響しない",
         'how': '登録どおりの R3（all・by_cat・info_Analyst_Trading）は数字を変えずに残し、重みが混ざっていると明記した。各行に stock_weight を足し、same_weight の節で '
                '等分の偽物は等分の市場と、時価加重の偽物（4本）は French Mkt と別々に比べた（照合に French の十分位から作った等分の市場も併記）。'
                '事後の節 C1_and_C2_pre_cost_rate_vs_placebo は同じ重みどうしの率（等分の偽物 対 等分の市場）に並べ替え、登録どおりの率は not_comparable の欄に移した',
         'before': {'placebo_rate_used_in_post_hoc': r3['all'], 'P': f"{ph_c['P']['count']}/{ph_c['P']['of']}", 'XL': f"{ph_c['XL']['count']}/{ph_c['XL']['of']}",
                    'reading': '偽物の基礎率 10.6% に対し P の 2/6（33%）は上に見えた'},
         'after': {'EW_placebos_vs_EW_market': sw['ew_placebos_vs_ew_market'], 'EW_placebos_vs_French_EW_crosscheck': sw['ew_placebos_vs_french_ew_crosscheck'],
                   'VW_placebos_vs_French_Mkt': sw['vw_placebos_vs_french_mkt'],
                   'EW_placebos_vs_French_Mkt_mixed': sw['ew_placebos_vs_french_mkt_mixed_weights'],
                   'P_binomial_vs_ew_rate': ph_c['P']['binomial_vs_ew_placebo_same_weight_rate'], 'XL_binomial_vs_ew_rate': ph_c['XL']['binomial_vs_ew_placebo_same_weight_rate']},
         'grade_changes': [], 'note': 'R3 と事後の節は格付けに使わないので、格付けは1本も変わらない'},
    ]
    _ew = sw['ew_placebos_vs_ew_market'] or {}
    _bp = ph_c['P']['binomial_vs_ew_placebo_same_weight_rate'] or {}
    _bx = ph_c['XL']['binomial_vs_ew_placebo_same_weight_rate'] or {}
    fixes[1]['after']['reading'] = (f"同じ重みどうしの偶然の基礎率は 等分の偽物 対 等分の市場で {_ew.get('C1_and_C2')}/{_ew.get('eligible')}＝{_ew.get('rate_C1_and_C2')}"
                                    f"（時価加重の偽物は {sw['vw_placebos_vs_french_mkt']['C1_and_C2']}/{sw['vw_placebos_vs_french_mkt']['eligible']}・率にならない）。"
                                    f"P の {ph_c['P']['count']}/{ph_c['P']['of']} はこの率から見て P(X≥{ph_c['P']['count']})={_bp.get('p_at_least_k')}＝偶然の率と見分けがつかない。"
                                    f"XL の {ph_c['XL']['count']}/{ph_c['XL']['of']} は P(X≤{ph_c['XL']['count']})={_bx.get('p_at_most_k')}（下側・独立でない試行の記述だけ）")
    DEV.append('（規則の誤読の是正・2026-09-28 v2）転がる20年窓（C4）と20年積立の『勝ち』は丸める前の差（>0）・倍率（>1）で数えた。nx_common.rolling / dca は丸めてから数えるため '
               '+0.001〜+0.005%/年 の窓が負けに入っていた。窓の切り方・表示の丸めは nx_common のまま（兄弟の角度 nx_osap_intang と同じ直し方。詳細と前後の数字は fixes F1）')
    DEV.append('（事前登録の後に足した報告・2026-09-28 v2）R3 の偽物は110本が等分の組なので、同じ重みの市場と比べた基礎率（等分の偽物 対 等分の市場〔JKP usa mkt ew＋French RF・照合に French の十分位の再構成〕、'
               '時価加重の偽物4本 対 French Mkt）を same_weight に足した。登録どおりの all（対 French Mkt）は数字を変えずに残した。事後の節の比較は同じ重みどうしに替えた（fixes F2）')
    out = {'angle': 'nx_osap_info', 'version': 2, 'prereg': 'out/nx_osap_info_prereg.json', 'global_prereg': 'out/nx_prereg.json',
           'fixes': fixes,
           'fingerprints': shainfo,
           'benchmark': {'graded': 'French Mkt（Mkt-RF＋RF）・総リターンどうし', 'french_last_month': max(b_all), 'osap_last_month': 202412},
           'cost': {'unit_graded': UNIT, 'unit_sensitivity': UNIT3, 'turnover': '保有の月ごとの片道の回転（時価の代わりの重み）・最初の月1.0・欠けは窓の中の中央値・BH は年1.0・MIX は構成の平均'},
           'grade_counts': grades, 'holm': holm, 'tested': tested, 'results': results, 'reports': reports,
           'post_hoc_事後': ph,
           'deviations_from_prereg': DEV, 'implementation_notes': NOTES,
           'runtime_sec': round(time.time() - T0, 1)}
    p = N.save(OUTNAME, out)
    log('→', p)
    for row in tested:
        print(f"{row['rule']:40s} {row['family']:2s} {row['grade']:14s} full {row['full_ex_ann']} t{row['full_t']} | train {row['train_ex_ann']} t{row['train_t']} | "
              f"hold {row['hold_ex_ann']} t{row['hold_t']} gd{row['hold_cagr_diff']} c1 {row['hold_cost010_cagr_diff']} | roll {row['roll20_win_rate_cost010']} | holm {row['holm']}")
    return out


if __name__ == '__main__':
    main()
