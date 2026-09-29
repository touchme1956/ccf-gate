#!/usr/bin/env python3
"""night/mw_risk_matched_verify.py — 角度 risk_matched の主張を『反証する側』から独立に検算する（読むだけ・門の判定には不使用）

対象: out/mw_risk_matched.json の主張のうち、報告された8本
  P_JKP_ocf_at[3]_dynamic / P_JKP_ocf_at[3]_static / U_JKP_ocf_at[3]_unlevered /
  X5_X5_QLR_ALL_{beta_dynamic, beta_static, dynamic, static} / X5_X5_Q_ALL_beta_dynamic

約束
- mw_common からは『取得』だけを使う（ff_factors・jkp_rows・yahoo）。ポートフォリオの組み立て・倍率・費用・
  超過・NW t・CAGR・転がる20年・積立は、このファイルの中で独自に書く（研究者の lever/excess_stats/rolling を呼ばない）。
- 相手は French の Mkt（Mkt-RF + RF・上限なしの時価加重）。JKP の三分位は超過なので French の RF を足して総リターン。
- 出力: out/mw_risk_matched_verify.json
"""
import json, math, os, sys, statistics as S, datetime, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得だけ）

BASE = M.BASE
TRAIN_END, HOLD_START, RECENT = 200612, 200701, 201307
LMAX, SPREAD, COST, WIN = 2.0, 0.01, 0.001, 36

QUALITY = ["at_turnover", "cop_at", "cop_atl1", "dgp_dsale", "gp_at", "gp_atl1", "mispricing_perf", "ni_inc8q", "niq_at",
           "op_at", "op_atl1", "opex_at", "qmj", "qmj_growth", "qmj_prof", "qmj_safety", "sale_bev", "dolvol_var_126d",
           "ebit_bev", "ebit_sale", "f_score", "ni_be", "niq_be", "o_score", "ocf_at", "ope_be", "ope_bel1", "turnover_var_126d"]
LOW_RISK = ["beta_60m", "beta_dimson_21d", "betabab_1260d", "betadown_252d", "earnings_variability", "ivol_capm_21d",
            "ivol_capm_252d", "ivol_ff3_21d", "ivol_hxz4_21d", "ocfq_saleq_std", "rmax1_21d", "rmax5_21d", "rvol_21d",
            "seas_6_10na", "turnover_126d", "zero_trades_126d", "zero_trades_21d", "zero_trades_252d"]
# 回転率（片道・年率）: 事前登録の表を自分で写し直した（研究者の辞書は使わない）
TO = {}
for k in ["beta_60m", "betabab_1260d", "betadown_252d", "ivol_capm_252d"]: TO[k] = 0.4
for k in ["rvol_21d", "ivol_capm_21d", "ivol_ff3_21d", "ivol_hxz4_21d", "rmax1_21d", "rmax5_21d", "beta_dimson_21d", "zero_trades_21d"]: TO[k] = 1.5
for k in ["turnover_126d", "zero_trades_126d", "zero_trades_252d", "dolvol_var_126d", "turnover_var_126d"]: TO[k] = 0.6
for k in ["earnings_variability", "ocfq_saleq_std"]: TO[k] = 0.3
TO["seas_6_10na"] = 1.0
for k in ["gp_at", "gp_atl1", "cop_at", "cop_atl1", "op_at", "op_atl1", "ope_be", "ope_bel1", "ebit_bev", "ebit_sale",
          "ocf_at", "sale_bev", "at_turnover", "f_score", "o_score", "opex_at", "dgp_dsale", "ni_be"]: TO[k] = 0.4
for k in ["niq_at", "niq_be", "ni_inc8q"]: TO[k] = 0.8
for k in ["qmj", "qmj_prof", "qmj_safety", "qmj_growth", "mispricing_perf"]: TO[k] = 0.6


# ───────────────────────── 自前の小道具 ─────────────────────────
def nxt(ym):
    y, m = divmod(ym, 100)
    return ym + 1 if m < 12 else (y + 1) * 100 + 1


def ymd(s):
    return int(s[:4]) * 100 + int(s[5:7])


_PF = {}


def pf(region, key, w='vw'):
    """JKP の三分位を自分で読む → ({'1.0': {ym: 超過}, ...}, {'1.0': {ym: 銘柄数}})"""
    if (region, key, w) not in _PF:
        r, n = collections.defaultdict(dict), collections.defaultdict(dict)
        for x in M.jkp_rows(region, key, 'portfolios', w):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            r[x['pf']][ymd(x['date'])] = float(x['ret'])
            try:
                n[x['pf']][ymd(x['date'])] = float(x['n'])
            except ValueError:
                pass
        _PF[(region, key, w)] = (dict(r), dict(n))
    return _PF[(region, key, w)]


def jfac(region, key, w='vw'):
    out = {}
    for x in M.jkp_rows(region, key, 'factor', w):
        if x['ret'] not in ('', 'NA', 'na'):
            out[ymd(x['date'])] = float(x['ret'])
    return out


def mean(x):
    return math.fsum(x) / len(x)


def sd(x):
    m = mean(x)
    return math.sqrt(math.fsum((v - m) ** 2 for v in x) / (len(x) - 1))


def nwt(x, L=12):
    n = len(x)
    if n < 24:
        return None
    m = mean(x)
    e = [v - m for v in x]
    lrv = math.fsum(v * v for v in e) / n
    for l in range(1, L + 1):
        lrv += 2 * (1 - l / (L + 1)) * math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(lrv / n) if lrv > 0 else None


def geo(x):
    return math.exp(math.fsum(math.log1p(v) for v in x) * 12 / len(x)) - 1


def beta(x, m):
    mx, mm = mean(x), mean(m)
    vm = math.fsum((b - mm) ** 2 for b in m)
    return math.fsum((a - mx) * (b - mm) for a, b in zip(x, m)) / vm


def stats(s, b, a=None, z=None, drop=None):
    """s, b: 総リターン {ym: r}。差の算術年率・NW t・CAGR の差・月数"""
    ks = [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z)
          and not (drop and any(d0 <= k <= d1 for d0, d1 in drop))]
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nwt(d)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(mean(d) * 1200, 2), 't': round(t, 2) if t is not None else None,
            'cagr_diff': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2)}


def capm(s_ex, m_ex, a=None, z=None):
    """CAPM の α（年率%）と NW t・β。s_ex, m_ex は超過"""
    ks = [k for k in sorted(set(s_ex) & set(m_ex)) if (a is None or k >= a) and (z is None or k <= z)]
    x, m = [s_ex[k] for k in ks], [m_ex[k] for k in ks]
    b = beta(x, m)
    al = mean(x) - b * mean(m)
    res = [xi - b * mi for xi, mi in zip(x, m)]
    t = nwt(res)
    return {'alpha': round(al * 1200, 2), 't_alpha_approx': round(t, 2) if t else None, 'beta': round(b, 3), 'n': len(ks)}


def roll20(s, b, years=20):
    ks = sorted(set(s) & set(b))
    out = []
    for y in range(ks[0] // 100, 2100):
        a, z = y * 100 + 7, (y + years) * 100 + 6
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        out.append((y, (math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - math.exp(math.fsum(math.log1p(b[k]) for k in w) / years)) * 100))
    if not out:
        return None
    oos = [c for y, c in out if y * 100 + 7 >= HOLD_START]
    return {'windows': len(out), 'win_rate': round(sum(c > 0 for _, c in out) / len(out), 3),
            'worst': [out[min(range(len(out)), key=lambda i: out[i][1])][0], round(min(c for _, c in out), 2)],
            'windows_fully_after_2006': len(oos),
            'windows_touching_ranking_window_196307_200612': sum(1 for y, _ in out if y * 100 + 7 <= 200612 and (y + 20) * 100 + 6 >= 196307)}


def dca20(s, b, step=12):
    ks = sorted(set(s) & set(b))
    out = []
    for i in range(0, len(ks) - 240 + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + 240]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append(ws / wb)
    v = sorted(out)
    return {'windows': len(v), 'win_rate': round(sum(r > 1 for r in v) / len(v), 3), 'median': round(v[len(v) // 2], 3)}


def contig_longest(ks):
    runs, cur = [], [ks[0]]
    for a, b in zip(ks, ks[1:]):
        if nxt(a) == b:
            cur.append(b)
        else:
            runs.append(cur); cur = [b]
    runs.append(cur)
    return max(runs, key=len)


def lever(r_ex, m_ex, rf, rule, to, cost=COST, spread=SPREAD, lmax=LMAX, win=WIN, train_end=TRAIN_END, to_mult=1.0):
    """自前の倍率エンジン。r_ex, m_ex: 超過。戻り (総・費用前, 総・費用後, 倍率の列)"""
    ks = contig_longest(sorted(set(r_ex) & set(m_ex) & set(rf)))
    Lfix = None
    if rule in ('static', 'beta_static'):
        tr = [k for k in ks if k <= train_end]
        if len(tr) < 60:
            return None, None, None
        x, m = [r_ex[k] for k in tr], [m_ex[k] for k in tr]
        if rule == 'static':
            Lfix = min(lmax, sd(m) / sd(x))
        else:
            b = beta(x, m)
            Lfix = lmax if b <= 0 else min(lmax, 1 / b)
    gross, net, Ls = {}, {}, {}
    hx, hm = [], []
    prev = None  # (L, 資産の総リターン, 戦略の総リターン)
    for k in ks:
        if rule == 'unlevered':
            L = 1.0
        elif Lfix is not None:
            L = Lfix
        elif len(hx) >= win:
            xx, mm = hx[-win:], hm[-win:]
            if rule == 'dynamic':
                L = min(lmax, sd(mm) / sd(xx))
            else:
                b = beta(xx, mm)
                L = lmax if b <= 0 else min(lmax, 1 / b)
        else:
            L = None
        hx.append(r_ex[k]); hm.append(m_ex[k])
        if L is None:
            continue
        g_ex = L * r_ex[k] - max(L - 1.0, 0.0) * spread / 12
        c = L * to * to_mult / 12 * cost
        if prev is not None:
            wdrift = prev[0] * (1 + prev[1]) / (1 + prev[2])
            c += abs(L - wdrift) * cost
        gross[k] = g_ex + rf[k]
        net[k] = g_ex - c + rf[k]
        Ls[k] = L
        prev = (L, r_ex[k] + rf[k], g_ex + rf[k])
    return gross, net, Ls


def tax_drag(net_tot, bench_tot, turnover, a=HOLD_START, z=None, rate=0.20315):
    """日本の課税口座: 戦略は毎月 turnover/12 を売って含み益に課税（損は繰り越して相殺）、相手は買って持つだけ。
    最後に両方とも清算して課税。平均取得単価で近似。税引後の年率の差（%）を返す"""
    ks = [k for k in sorted(set(net_tot) & set(bench_tot)) if k >= a and (z is None or k <= z)]
    V, basis, carry = 1.0, 1.0, 0.0
    for k in ks:
        V *= 1 + net_tot[k]
        sell = V * turnover / 12
        gain = sell * (1 - basis / V)
        basis -= basis * turnover / 12
        g = gain + carry
        if g > 0:
            tax, carry = g * rate, 0.0
        else:
            tax, carry = 0.0, g
        V -= tax
        basis += sell - tax  # 売った代金（税引後）で買い直す＝取得単価が上がる
    V_after = V - max(V - basis + carry, 0) * rate
    W = 1.0
    for k in ks:
        W *= 1 + bench_tot[k]
    W_after = W - max(W - 1.0, 0) * rate
    yrs = len(ks) / 12
    # 税前（同じ窓）
    Vp = 1.0
    for k in ks:
        Vp *= 1 + net_tot[k]
    Vp_after = Vp - max(Vp - 1.0, 0) * rate  # 一度も売らずに最後に清算した場合（上限の比較）
    return {'years': round(yrs, 1), 'after_tax_cagr_diff': round(((V_after) ** (1 / yrs) - (W_after) ** (1 / yrs)) * 100, 2),
            'pretax_cagr_diff': round((Vp ** (1 / yrs) - W ** (1 / yrs)) * 100, 2),
            'no_turnover_tax_cagr_diff': round((Vp_after ** (1 / yrs) - W_after ** (1 / yrs)) * 100, 2)}


# ───────────────────────── データ ─────────────────────────
ff = M.ff_factors()
MKT, MKTRF, RF = ff['mkt'], ff['mktrf'], ff['rf']


def good_side_own(key, upto=TRAIN_END):
    """自前の良い側: 訓練期間の (三分位3 − 三分位1) の平均の符号（JKP の符号つき因子は使わない）"""
    p, _ = pf('usa', key)
    ks = [k for k in sorted(set(p.get('3.0', {})) & set(p.get('1.0', {}))) if k <= upto]
    if len(ks) < 24:
        return None
    return '3.0' if mean([p['3.0'][k] - p['1.0'][k] for k in ks]) > 0 else '1.0'


def good_side_sharpe(key, upto=TRAIN_END):
    """自前の良い側その2（角度の考え方に合わせる）: 訓練期間のシャープレシオが高いほうの端（三分位1 か 3）"""
    p, _ = pf('usa', key)
    out = {}
    for s_ in ('1.0', '3.0'):
        x = [v for k, v in sorted(p.get(s_, {}).items()) if k <= upto]
        out[s_] = mean(x) / sd(x) if len(x) >= 60 else None
    if None in out.values():
        return None
    return '3.0' if out['3.0'] > out['1.0'] else '1.0'


def top_months(n, k=12, a=HOLD_START):
    ks = [x for x in sorted(set(n) & set(MKT)) if x >= a]
    d = sorted(((n[x] - MKT[x]) * 100, x) for x in ks)
    return {'best': [[x, round(v, 2)] for v, x in d[::-1][:k]], 'worst': [[x, round(v, 2)] for v, x in d[:6]]}


def good_side_jkpfactor(key, upto=TRAIN_END):
    p, _ = pf('usa', key)
    f = jfac('usa', key, 'vw')
    ks = [k for k in sorted(set(p.get('3.0', {})) & set(p.get('1.0', {})) & set(f)) if k <= upto]
    d = [p['3.0'][k] - p['1.0'][k] for k in ks]
    ff_ = [f[k] for k in ks]
    md, mf = mean(d), mean(ff_)
    c = math.fsum((a - md) * (b - mf) for a, b in zip(d, ff_))
    return '3.0' if c > 0 else '1.0'


def ew_blend(series, min_share=0.5):
    months = sorted(set().union(*[set(s) for s in series]))
    need = math.ceil(len(series) * min_share)
    out = {}
    for k in months:
        v = [s[k] for s in series if k in s]
        if len(v) >= need:
            out[k] = mean(v)
    ks = contig_longest(sorted(out))
    return {k: out[k] for k in ks}


def build_group(keys, sides, region='usa', w='vw'):
    ser = []
    for k in keys:
        sd_ = sides.get(k)
        if sd_ is None:
            continue
        try:
            p, _ = pf(region, k, w)
        except Exception:  # noqa
            continue
        if p.get(sd_):
            ser.append(p[sd_])
    return ew_blend(ser), len(ser)


def _erfcinv(y):
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erfc(mid) > y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def to_tot(ex):
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


def evaluate(ex, rule, to, **kw):
    """ex: 候補の超過。戻り: 数字の辞書と系列"""
    g, n, Ls = lever(ex, MKTRF, RF, rule, to, **kw)
    if g is None:
        return None, None, None, None
    out = {'full': stats(g, MKT), 'train': stats(g, MKT, z=TRAIN_END), 'hold': stats(g, MKT, a=HOLD_START),
           'hold_net': stats(n, MKT, a=HOLD_START), 'recent': stats(g, MKT, a=RECENT),
           'roll20_net': roll20(n, MKT), 'dca20_net': dca20(n, MKT),
           'L_mean': round(mean(list(Ls.values())), 3), 'L_min': round(min(Ls.values()), 3), 'L_max': round(max(Ls.values()), 3)}
    return out, g, n, Ls


def sharpe_pair(s_tot, a=None, z=None):
    ks = [k for k in sorted(set(s_tot) & set(MKT)) if (a is None or k >= a) and (z is None or k <= z)]
    xs = [s_tot[k] - RF[k] for k in ks]
    xm = [MKT[k] - RF[k] for k in ks]
    return (round(mean(xs) / sd(xs) * math.sqrt(12), 3), round(mean(xm) / sd(xm) * math.sqrt(12), 3))


def robustness(g, n, label_to=None):
    """反証のための切り方（すべて費用後 n で、相手 French Mkt）"""
    r = {}
    r['full_from_196307'] = stats(n, MKT, a=196307)
    r['full_excl_ranking_window_196307_200612'] = stats(n, MKT, drop=[(196307, 200612)])
    r['hold_drop_2020_2021'] = stats(n, MKT, a=HOLD_START, drop=[(202001, 202112)])
    r['full_drop_1998_2000'] = stats(n, MKT, drop=[(199801, 200012)])
    r['hold_half1_200701_201606'] = stats(n, MKT, a=HOLD_START, z=201606)
    r['hold_half2_201607_end'] = stats(n, MKT, a=201607)
    r['hold_200701_201512_in_paper_sample'] = stats(n, MKT, a=HOLD_START, z=201512)
    r['post_2016'] = stats(n, MKT, a=201601)
    r['post_2020'] = stats(n, MKT, a=202001)
    r['hold_drop_2023_2025_ai'] = stats(n, MKT, a=HOLD_START, z=202212)
    r['sub_2007_2012'] = stats(n, MKT, a=200701, z=201212)
    r['sub_2013_2019'] = stats(n, MKT, a=201301, z=201912)
    r['sub_2020_end'] = stats(n, MKT, a=202001)
    ks = [k for k in sorted(set(n) & set(MKT)) if k >= HOLD_START]
    d = sorted((n[k] - MKT[k] for k in ks), reverse=True)
    r['hold_drop_best12_months'] = round(mean(d[12:]) * 1200, 2)
    r['hold_drop_best24_months'] = round(mean(d[24:]) * 1200, 2)
    # 保有期間の超過のうち最良の12か月が占める割合
    r['share_of_hold_excess_from_best12'] = round(math.fsum(d[:12]) / math.fsum(d), 2) if math.fsum(d) > 0 else None
    return r


def main():
    res = {'generated': datetime.date.today().isoformat(), 'angle': 'risk_matched', 'verifier': 'adversarial',
           'method': 'mw_common は取得（ff_factors / jkp_rows / yahoo）だけを使い、三分位の読み込み・良い側・等分混合・倍率（static/dynamic/beta）・費用・借入・超過・NW t・CAGR・転がる20年・積立・税を自前で書いた',
           'data_checks': {}, 'candidates': {}}
    # ── データの基準 ──
    jm = jfac('usa', 'mkt', 'vw')
    dc = {}
    for a, z in [(192607, 200612), (200701, 202512)]:
        ks = [k for k in sorted(jm) if a <= k <= z and k in MKTRF]
        dc[f'{a}_{z}'] = {'jkp_vw_mkt': round(mean([jm[k] for k in ks]) * 1200, 2), 'french_mktrf': round(mean([MKTRF[k] for k in ks]) * 1200, 2),
                          'french_mkt_total': round(mean([MKT[k] for k in ks]) * 1200, 2)}
    dc['verdict'] = 'JKP の ret は超過（JKP vw 市場 ≈ French Mkt-RF）。RF を足して French Mkt（総）と比べるのは正しい。保有期間は JKP vw 市場が French より年0.4%低い＝French を相手にするのは戦略に不利な側（保守的）'
    _, nn = pf('usa', 'ocf_at')
    dc['ocf_at_stock_counts'] = {str(y): [nn[p].get(y) for p in ('1.0', '2.0', '3.0')] for y in (195011, 195512, 196012, 196306, 197012, 200012, 202512)}
    res['data_checks'] = dc

    # ══════════════ 1. ocf_at[3]（主の族） ══════════════
    p, _ = pf('usa', 'ocf_at')
    ex = p['3.0']
    ocf = {}
    for rule in ('dynamic', 'static', 'unlevered'):
        e, g, n, Ls = evaluate(ex, rule, TO['ocf_at'])
        e['sharpe_train'] = sharpe_pair(n, z=TRAIN_END)
        e['sharpe_hold'] = sharpe_pair(n, a=HOLD_START)
        e['robust'] = robustness(g, n)
        e['tax_japan_taxable_hold'] = tax_drag(n, MKT, TO['ocf_at'])
        e['cost3x_turnover2x_hold'] = stats(lever(ex, MKTRF, RF, rule, TO['ocf_at'], cost=0.003, to_mult=2.0)[1], MKT, a=HOLD_START)
        e['spread_2pct_hold'] = stats(lever(ex, MKTRF, RF, rule, TO['ocf_at'], spread=0.02)[1], MKT, a=HOLD_START)
        ocf[rule] = e
        print('ocf_at', rule, e['full'], e['train'], e['hold'], e['hold_net'], e['roll20_net'], e['dca20_net'], e['L_mean'])
    # 近傍: 三分位2・窓24/60・他の質の特徴（倍率1・費用後・保有）・vw_cap・ew
    nb = {}
    for wname, w in (('vw_cap', 'vw_cap'), ('ew', 'ew')):
        pp, _ = pf('usa', 'ocf_at', w)
        for rule in ('dynamic', 'static', 'unlevered'):
            e, g, n, _ = evaluate(pp['3.0'], rule, TO['ocf_at'])
            nb[f'ocf_at[3]_{wname}_{rule}'] = {'full': e['full'], 'train': e['train'], 'hold_net': e['hold_net']}
    e, g, n, _ = evaluate(p['2.0'], 'dynamic', TO['ocf_at'])
    nb['ocf_at[2]_vw_dynamic'] = {'full': e['full'], 'hold_net': e['hold_net']}
    for W in (24, 60, 120):
        e, g, n, _ = evaluate(ex, 'dynamic', TO['ocf_at'], win=W)
        nb[f'ocf_at[3]_dynamic_win{W}'] = {'full': e['full'], 'hold_net': e['hold_net'], 'L_mean': e['L_mean']}
    for k in ['cop_at', 'cop_atl1', 'op_at', 'op_atl1', 'gp_at', 'gp_atl1', 'ope_be', 'ebit_bev', 'ebit_sale', 'ni_be', 'niq_at', 'qmj', 'qmj_prof', 'f_score', 'sale_bev']:
        pp, _ = pf('usa', k)
        e, g, n, _ = evaluate(pp['3.0'], 'unlevered', TO[k])
        ec, _, _, _ = evaluate(pf('usa', k, 'vw_cap')[0]['3.0'], 'unlevered', TO[k])
        nb[f'{k}[3]_unlevered'] = {'train': e['train'], 'hold_net': e['hold_net'], 'post_2020': robustness(g, n)['post_2020'],
                                   'vw_cap_hold_net': ec['hold_net']}
    vals = [v['hold_net']['ex'] for k, v in nb.items() if 'vw_cap_hold_net' in v]
    capv = [v['vw_cap_hold_net']['ex'] for k, v in nb.items() if 'vw_cap_hold_net' in v]
    nb['_summary_quality_top_tercile_unlevered'] = {'n': len(vals), 'hold_net_positive': sum(v > 0 for v in vals), 'median_hold_net': round(S.median(vals), 2),
                                                    'vw_cap_positive': sum(v > 0 for v in capv), 'vw_cap_median': round(S.median(capv), 2)}
    # vw − vw_cap の差（巨大株の上乗せ）と相手の巨大株: 同じ三分位の vw と vw_cap の差を保有期間で
    pc = pf('usa', 'ocf_at', 'vw_cap')[0]['3.0']
    ks = [k for k in sorted(set(ex) & set(pc)) if k >= HOLD_START]
    nb['ocf_at[3]_vw_minus_vwcap_hold'] = {'ex': round(mean([ex[k] - pc[k] for k in ks]) * 1200, 2), 't': round(nwt([ex[k] - pc[k] for k in ks]), 2)}
    ks = [k for k in sorted(set(ex) & set(pc)) if 196307 <= k <= TRAIN_END]
    nb['ocf_at[3]_vw_minus_vwcap_train'] = {'ex': round(mean([ex[k] - pc[k] for k in ks]) * 1200, 2), 't': round(nwt([ex[k] - pc[k] for k in ks]), 2)}
    jc = jfac('usa', 'mkt', 'vw_cap')
    ks = [k for k in sorted(set(jm) & set(jc)) if k >= HOLD_START]
    nb['market_vw_minus_vwcap_hold'] = {'ex': round(mean([jm[k] - jc[k] for k in ks]) * 1200, 2)}
    # CAPM α（倍率1・超過）
    nb['ocf_at[3]_capm_train_196307'] = capm(ex, MKTRF, a=196307, z=TRAIN_END)
    nb['ocf_at[3]_capm_hold'] = capm(ex, MKTRF, a=HOLD_START)
    nb['ocf_at[3]_capm_post2020'] = capm(ex, MKTRF, a=202001)
    ocf['neighbors'] = nb
    res['candidates']['ocf_at'] = ocf

    # 多重検定（研究者の tested を数える）
    d = json.load(open(os.path.join(BASE, 'out', 'mw_risk_matched.json')))
    fam = collections.Counter(r['family'] for r in d['tested'])
    graded = [r for r in d['tested'] if r.get('grade')]
    n_graded_paper = sum(1 for r in graded if r['family'] != 'R')
    P = [r for r in d['tested'] if r['family'] == 'P']
    mt = {'family_sizes': dict(fam), 'n_tested': len(d['tested']), 'n_graded_paper_non_ETF': n_graded_paper,
          'n_candidates_ranked_in_selection': d['selection']['n_candidates_ranked'],
          'P_family_size': len(P)}

    def p2(t):
        return math.erfc(abs(t) / math.sqrt(2))
    for rule in ('dynamic', 'static'):
        t = ocf[rule]['hold']['t']
        mt[f'ocf_at_{rule}_hold_t'] = t
        mt[f'ocf_at_{rule}_hold_p_two_sided'] = round(p2(t), 4)
        mt[f'ocf_at_{rule}_bonferroni_P14'] = round(min(1, p2(t) * 14), 3)
        mt[f'ocf_at_{rule}_bonferroni_all_graded_paper'] = round(min(1, p2(t) * n_graded_paper), 3)
    # 選び出しの窓で t が膨らむか: 保有期間 t だけで BHY 相当（HLZ の t≥3 を保有期間に当てると）
    mt['note'] = ('C7 は全期間 t≥3 で合格しているが、全期間には候補を選んだ訓練の窓（196307〜200612・{}候補を訓練シャープで順位づけ）が入る。'
                  '選び出しに使っていない月（1950〜1963-06 と 2007〜）だけの t と、保有期間 t の族内ボンフェローニを併記した').format(d['selection']['n_candidates_ranked'])
    res['multiple_testing'] = mt

    # ══════════════ 2. X5（選び出しなしの混合） ══════════════
    sides_j = {k: good_side_jkpfactor(k) for k in QUALITY + LOW_RISK}
    sides_o = {k: good_side_own(k) for k in QUALITY + LOW_RISK}
    diff_sides = {k: (sides_j[k], sides_o[k]) for k in sides_j if sides_j[k] != sides_o[k]}
    res['x5_good_sides'] = {'jkp_factor_corr_upto_200612': sides_j, 'own_mean_spread_upto_200612': sides_o, 'disagree': diff_sides,
                            'researcher': d.get('x5_good_sides'), 'match_researcher': sides_j == d.get('x5_good_sides')}
    # 良い側を後から（全期間）決めたら変わるか
    sides_full = {k: good_side_own(k, upto=209912) for k in QUALITY + LOW_RISK}
    res['x5_good_sides']['sides_flip_if_chosen_with_full_data'] = {k: (sides_o[k], sides_full[k]) for k in sides_o if sides_o[k] != sides_full[k]}

    to_q = mean([TO[k] for k in QUALITY]) + 0.1
    to_l = mean([TO[k] for k in LOW_RISK]) + 0.1
    to_ql = 0.5 * to_q + 0.5 * to_l + 0.1
    x5 = {}
    for side_name, sides in (('jkp', sides_j), ('own', sides_o)):
        q, nq = build_group(QUALITY, sides)
        l, nl = build_group(LOW_RISK, sides)
        ks = sorted(set(q) & set(l))
        ql = {k: 0.5 * q[k] + 0.5 * l[k] for k in ks}
        for gname, ser, to in (('Q_ALL', q, to_q), ('QLR_ALL', ql, to_ql), ('LR_ALL', l, to_l)):
            for rule in ('beta_dynamic', 'beta_static', 'dynamic', 'static', 'unlevered'):
                if side_name == 'own' and not (gname == 'QLR_ALL' or (gname == 'Q_ALL' and rule == 'beta_dynamic')):
                    continue
                e, g, n, Ls = evaluate(ser, rule, to)
                e['sharpe_train'] = sharpe_pair(n, z=TRAIN_END)
                e['sharpe_hold'] = sharpe_pair(n, a=HOLD_START)
                if side_name == 'jkp':
                    e['robust'] = robustness(g, n)
                    e['cost3x_turnover2x_hold'] = stats(lever(ser, MKTRF, RF, rule, to, cost=0.003, to_mult=2.0)[1], MKT, a=HOLD_START)
                    e['spread_2pct_hold'] = stats(lever(ser, MKTRF, RF, rule, to, spread=0.02)[1], MKT, a=HOLD_START)
                    e['spread_3pct_hold'] = stats(lever(ser, MKTRF, RF, rule, to, spread=0.03)[1], MKT, a=HOLD_START)
                    e['tax_japan_taxable_hold'] = tax_drag(n, MKT, to * e['L_mean'])
                    # 倍率の寄与: 借入の上乗せ部分（(L−1)×市場超過）と CAPM α
                    kk = [k for k in sorted(n) if k >= HOLD_START]
                    e['hold_mean_L_minus_1_times_mkt_ex'] = round(mean([(Ls[k] - 1) * MKTRF[k] for k in kk]) * 1200, 2)
                x5[f'{side_name}_{gname}_{rule}'] = e
                print('X5', side_name, gname, rule, e['full'], e['train'], e['hold'], e['hold_net'], e['roll20_net']['win_rate'] if e['roll20_net'] else None, e['L_mean'])
        if side_name == 'jkp':
            x5['_capm_QLR_unlevered_train_196307'] = capm(ql, MKTRF, a=196307, z=TRAIN_END)
            x5['_capm_QLR_unlevered_hold'] = capm(ql, MKTRF, a=HOLD_START)
            x5['_capm_QLR_unlevered_post2020'] = capm(ql, MKTRF, a=202001)
            x5['_capm_Q_unlevered_hold'] = capm(q, MKTRF, a=HOLD_START)
            x5['_n_features'] = {'Q': nq, 'LR': nl}
            x5['_turnover'] = {'Q': round(to_q, 3), 'LR': round(to_l, 3), 'QLR': round(to_ql, 3)}
            # vw_cap 版（巨大株を抑える）
            qc, _ = build_group(QUALITY, sides, w='vw_cap')
            lc, _ = build_group(LOW_RISK, sides, w='vw_cap')
            kk = sorted(set(qc) & set(lc))
            qlc = {k: 0.5 * qc[k] + 0.5 * lc[k] for k in kk}
            for rule in ('beta_dynamic', 'beta_static', 'dynamic', 'static'):
                e, g, n, _ = evaluate(qlc, rule, to_ql)
                x5[f'jkp_QLR_ALL_{rule}_VWCAP'] = {'train': e['train'], 'hold_net': e['hold_net'], 'full': e['full']}
            e, g, n, _ = evaluate(qc, 'beta_dynamic', to_q)
            x5['jkp_Q_ALL_beta_dynamic_VWCAP'] = {'train': e['train'], 'hold_net': e['hold_net'], 'full': e['full']}
            # 近傍: 倍率の窓 24/60・上限 1.5・混合比 70/30・30/70
            for W in (24, 60):
                for rule in ('dynamic', 'beta_dynamic'):
                    e, g, n, _ = evaluate(ql, rule, to_ql, win=W)
                    x5[f'jkp_QLR_ALL_{rule}_win{W}'] = {'hold_net': e['hold_net'], 'full': e['full'], 'L_mean': e['L_mean']}
            for wq in (0.3, 0.7):
                mix = {k: wq * q[k] + (1 - wq) * l[k] for k in ks}
                for rule in ('dynamic', 'beta_dynamic'):
                    e, g, n, _ = evaluate(mix, rule, to_ql)
                    x5[f'jkp_Q{int(wq*100)}LR{int(100-wq*100)}_{rule}'] = {'hold_net': e['hold_net'], 'full': e['full'], 'L_mean': e['L_mean']}
            # 地域（C5）を自前で: 4地域・同じ側・同じ規則
            reg = {}
            for R in ('developed', 'world_ex_us', 'jpn', 'emerging'):
                rq, _ = build_group(QUALITY, sides, region=R)
                rl, _ = build_group(LOW_RISK, sides, region=R)
                kk = sorted(set(rq) & set(rl))
                rql = {k: 0.5 * rq[k] + 0.5 * rl[k] for k in kk}
                rm = jfac(R, 'mkt', 'vw')
                row = {}
                for rule in ('beta_dynamic', 'beta_static', 'dynamic', 'static', 'unlevered'):
                    for nm, ser_, to_ in (('QLR', rql, to_ql), ('Q', rq, to_q)):
                        g_, n_, L_ = lever(ser_, rm, RF, rule, to_, cost=0.003 if R == 'emerging' else COST)
                        if n_ is None:
                            row[f'{nm}_{rule}'] = None
                            continue
                        # 超過どうし: 戦略総 − RF vs 地域市場超過
                        s_ex = {k: v - RF[k] for k, v in n_.items()}
                        rm_t = {k: rm[k] for k in s_ex if k in rm}
                        fu = stats(s_ex, rm_t)
                        ho = stats(s_ex, rm_t, a=HOLD_START)
                        row[f'{nm}_{rule}'] = {'full_ex': fu['ex'], 'full_t': fu['t'], 'from': fu['from'], 'hold_ex': ho['ex'] if ho else None, 'hold_t': ho['t'] if ho else None}
                reg[R] = row
            x5['_regions_own'] = reg
    res['candidates']['x5'] = x5

    # ══════════════ 3. 現実の小さな答え合わせ（ETF） ══════════════
    etf = {}
    try:
        spy = M.yahoo('SPY', '1mo')
        for t in ('USMV', 'SPLV', 'QUAL', 'SPHQ', 'JQUA', 'DGRW'):
            e_ = M.yahoo(t, '1mo')
            ks = [k for k in sorted(set(e_) & set(spy)) if k <= 202608]
            dd = [e_[k] - spy[k] for k in ks]
            etf[t] = {'from': ks[0], 'to': ks[-1], 'unlevered_ex_vs_SPY': round(mean(dd) * 1200, 2), 't': round(nwt(dd), 2) if nwt(dd) else None,
                      'cagr_diff': round((geo([e_[k] for k in ks]) - geo([spy[k] for k in ks])) * 100, 2)}
    except Exception as ex_:  # noqa
        etf['error'] = str(ex_)[:200]
    # 紙の同じ窓（ETF の窓）で ocf_at[3] の倍率1
    e, g, n, _ = evaluate(ex, 'unlevered', TO['ocf_at'])
    for t in ('QUAL', 'SPHQ', 'JQUA', 'DGRW'):
        if t in etf:
            s_ = stats(n, MKT, a=etf[t]['from'])
            etf[t]['paper_ocf_at3_same_window_vs_FrenchMkt'] = s_
    res['etf_reality'] = etf

    # ══════════════ 4. 追加の反証 ══════════════
    add = {}
    # (a) 良い側を『訓練シャープ』で決める（角度の考え方どおり・JKP の文献の向きを使わない）
    sides_s = {k: good_side_sharpe(k) for k in QUALITY + LOW_RISK}
    add['sides_sharpe_disagree_with_jkp'] = {k: (sides_j[k], sides_s[k]) for k in sides_s if sides_s[k] != sides_j[k]}
    q, _ = build_group(QUALITY, sides_s)
    l, _ = build_group(LOW_RISK, sides_s)
    ks = sorted(set(q) & set(l))
    ql = {k: 0.5 * q[k] + 0.5 * l[k] for k in ks}
    for rule in ('beta_dynamic', 'beta_static', 'dynamic', 'static', 'unlevered'):
        e, g, n, _ = evaluate(ql, rule, to_ql)
        add[f'QLR_sharpe_sides_{rule}'] = {'full': e['full'], 'train': e['train'], 'hold': e['hold'], 'hold_net': e['hold_net'], 'L_mean': e['L_mean']}
    e, g, n, _ = evaluate(q, 'beta_dynamic', to_q)
    add['Q_sharpe_sides_beta_dynamic'] = {'full': e['full'], 'train': e['train'], 'hold': e['hold'], 'hold_net': e['hold_net']}
    # (b) 保有期間の超過を作った月
    e, g, n, _ = evaluate(ex, 'dynamic', TO['ocf_at'])
    add['ocf_at_dynamic_top_months'] = top_months(n)
    qj, _ = build_group(QUALITY, sides_j)
    lj, _ = build_group(LOW_RISK, sides_j)
    kk = sorted(set(qj) & set(lj))
    qlj = {k: 0.5 * qj[k] + 0.5 * lj[k] for k in kk}
    e, g, n, Ls = evaluate(qlj, 'beta_dynamic', to_ql)
    add['QLR_beta_dynamic_top_months'] = top_months(n)
    add['QLR_beta_dynamic_L_by_year'] = {str(y): round(mean([Ls[k] for k in Ls if k // 100 == y]), 3) for y in range(2007, 2026)}
    # (c) 税: 回転率を半分にしたら（混合の中で売買が相殺される場合）
    add['tax_QLR_beta_dynamic_half_turnover'] = tax_drag(n, MKT, to_ql * 1.095 / 2)
    add['tax_QLR_beta_dynamic_quarter_turnover'] = tax_drag(n, MKT, to_ql * 1.095 / 4)
    e2, g2, n2, _ = evaluate(ex, 'dynamic', TO['ocf_at'])
    add['tax_ocf_at_dynamic_half_turnover'] = tax_drag(n2, MKT, TO['ocf_at'] / 2)
    # (d) 角度全体の多重検定（保有期間の p を、紙の上で格付けした全 245 本で）
    def p2(t):
        return math.erfc(abs(t) / math.sqrt(2))
    allp = sorted(p2(r['hold']['t']) for r in d['tested'] if r.get('grade') and r['family'] != 'R' and r.get('hold') and r['hold'].get('t') is not None)
    m = len(allp)
    # Benjamini-Hochberg の閾値（全体）
    bh = max([i + 1 for i, pv in enumerate(allp) if pv <= 0.05 * (i + 1) / m] or [0])
    add['angle_wide_multiple_testing'] = {'m': m, 'bonferroni_t_needed_two_sided_5pct': round(math.sqrt(2) * _erfcinv(0.05 / m), 2),
                                          'bh_5pct_discoveries': bh, 'bh_p_cutoff': round(0.05 * bh / m, 5) if bh else None,
                                          'claimed_hold_t': {'ocf_at_dynamic': 2.8, 'ocf_at_static': 2.44, 'ocf_at_unlevered': 2.14, 'QLR_beta_dynamic': 2.94,
                                                             'QLR_beta_static': 2.75, 'QLR_dynamic': 2.73, 'QLR_static': 2.42, 'Q_beta_dynamic': 2.96}}
    # (e) 早い時期（1950〜1963-06・Compustat の後から足された時期）を除いた全期間 t（C7 の頑丈さ）
    for nm, ser, to, rule in (('ocf_at_dynamic', ex, TO['ocf_at'], 'dynamic'), ('ocf_at_static', ex, TO['ocf_at'], 'static'),
                              ('ocf_at_unlevered', ex, TO['ocf_at'], 'unlevered'), ('QLR_beta_dynamic', qlj, to_ql, 'beta_dynamic'),
                              ('QLR_beta_static', qlj, to_ql, 'beta_static'), ('QLR_dynamic', qlj, to_ql, 'dynamic'), ('QLR_static', qlj, to_ql, 'static'),
                              ('Q_beta_dynamic', qj, to_q, 'beta_dynamic')):
        e, g, n, _ = evaluate(ser, rule, to)
        add.setdefault('C7_gross_full_t_variants', {})[nm] = {'full_gross': (e['full']['ex'], e['full']['t']), 'from_196307_gross': (stats(g, MKT, a=196307)['ex'], stats(g, MKT, a=196307)['t']),
                                                              'excl_196307_200612_gross': (stats(g, MKT, drop=[(196307, 200612)])['ex'], stats(g, MKT, drop=[(196307, 200612)])['t']),
                                                              'hold_only_gross': (e['hold']['ex'], e['hold']['t'])}
    res['additional'] = add
    return res


SUMMARY = [
    '8本とも数字は自前のコードで完全に再現（full/train/hold・NW t・CAGR差・費用後・20年窓）。JKP は超過・相手は上限なしの French Mkt で、基準の混在は無い',
    'しかし 8本とも S から B へ格下げ。営業CF÷総資産（ocf_at）の3本は C7 を全期間 t≥3 でしか満たさず、その全期間には216候補から選んだ訓練の窓が入る（除くと t1.7〜2.3・保有の Holm 0.07〜0.19）',
    'ocf_at の保有期間の勝ちは巨大株を満額持つことが源: 上限つき（vw_cap）で −0.5〜+0.3・等加重で −1.7〜+0.6（訓練期間はどちらも +2.7〜+7.3）。三分位の中の巨大株の上乗せは訓練 −1.9 → 保有 +1.6 と向きが逆転した。最良24か月を除くと負（最良12か月のうち6か月が2008〜09）',
    '質＋低リスクの混合（X5）4本は選び出しなしで C7 も頑丈・4地域とも正・側の決め方を変えても同じ。だが結果を見た後の探索で、2016-07以降は +0.6〜0.8（t<1.3）・2020以降 +0.3〜0.5、上限つきで負、最良24か月を除くと負',
    '信用は NISA で使えないので課税口座: 研究者の回転率で税引後の年率差は X5 が +0.2 前後（QLR static は −0.01）、ocf_at は +1.1〜1.7 残る',
    '実在の質ETF（QUAL/SPHQ/DGRW）は同じ窓で SPY に負け、紙は +1.5〜2.2＝紙の上の勝ちは実在の器では取れていない',
    '結論: 『2007〜2025 の上限なし時価加重の米国で、質に傾けた箱は市場に勝った』は事実として頑丈だが、選び出し・巨大株・数か月・税を剥がすと S/A の頑丈さは残らない（B）',
]


def build_verdicts(res):
    """数字から判定を組み立てる（判定の理由は数字を引いて書く）"""
    o, x, a = res['candidates']['ocf_at'], res['candidates']['x5'], res['additional']
    mt, c7 = res['multiple_testing'], a['C7_gross_full_t_variants']
    nb = o['neighbors']
    V = []

    def num(e):
        return (f"full {e['full']['ex']:+.2f} t{e['full']['t']} / train {e['train']['ex']:+.2f} t{e['train']['t']} / hold {e['hold']['ex']:+.2f} t{e['hold']['t']} "
                f"CAGR差 {e['hold']['cagr_diff']:+.2f} / 費用後 hold {e['hold_net']['ex']:+.2f} / 20年窓 {e['roll20_net']['win_rate']} / 積立20年 勝率 {e['dca20_net']['win_rate']} 中央 {e['dca20_net']['median']} / 倍率平均 {e['L_mean']}")
    common_ocf = [
        f"C7 は全期間 t≥3 でだけ合格。全期間には候補を選んだ窓（196307〜200612・{mt['n_candidates_ranked_in_selection']}候補を訓練シャープで順位づけ）が入る。その窓を除くと t<3（下の数字）。保有期間 t の族内 Holm は 0.071（動）/0.19（固定）で 0.05 に届かず、角度全体（紙の上の格付け{a['angle_wide_multiple_testing']['m']}本）のボンフェローニは保有 t≥{a['angle_wide_multiple_testing']['bonferroni_t_needed_two_sided_5pct']} が要る＝C7 は選び出しの窓を数えないと成り立たない",
        f"三分位の中の vw−vw_cap（倍率1）は訓練 {nb['ocf_at[3]_vw_minus_vwcap_train']['ex']:+.2f}（t{nb['ocf_at[3]_vw_minus_vwcap_train']['t']}）→ 保有 {nb['ocf_at[3]_vw_minus_vwcap_hold']['ex']:+.2f}（t{nb['ocf_at[3]_vw_minus_vwcap_hold']['t']}）＝保有期間の勝ちの源は、訓練期間には逆に効いていた『巨大株の上乗せ』",
        f"保有期間の最良12か月（動）のうち6か月が 2008〜2009 の危機（{', '.join(str(m[0]) for m in a['ocf_at_dynamic_top_months']['best'] if 200801 <= m[0] <= 200912)}）",
        "原論文（Bouchaud ほか 2019・標本 1990〜2015）と保有期間 2007〜2015 が重なる＝保有期間の前半は文献の標本の中（下の『公表後』が本当の答え合わせ）",
        f"転がる20年窓は全部が選び出しの窓にかかる（完全に2007年以降の窓は0本）＝C4 は実質すべて標本内",
        f"実在の質ETFは同じ窓で SPY に負け（QUAL {res['etf_reality'].get('QUAL', {}).get('unlevered_ex_vs_SPY')} / SPHQ {res['etf_reality'].get('SPHQ', {}).get('unlevered_ex_vs_SPY')} / DGRW {res['etf_reality'].get('DGRW', {}).get('unlevered_ex_vs_SPY')} / JQUA {res['etf_reality'].get('JQUA', {}).get('unlevered_ex_vs_SPY')} %/年）、同じ窓の紙は +1.5〜+2.2",
        f"反証できなかった点: 数字は完全に再現。質の上位三分位（vw・倍率1）は{nb['_summary_quality_top_tercile_unlevered']['n']}特徴中{nb['_summary_quality_top_tercile_unlevered']['hold_net_positive']}で保有期間に正（中央 {nb['_summary_quality_top_tercile_unlevered']['median_hold_net']:+.2f}）＝選び出しの運ではない。CAPM α は訓練 {nb['ocf_at[3]_capm_train_196307']['alpha']} t{nb['ocf_at[3]_capm_train_196307']['t_alpha_approx']}・保有 {nb['ocf_at[3]_capm_hold']['alpha']} t{nb['ocf_at[3]_capm_hold']['t_alpha_approx']}。費用3倍×回転2倍・借入 RF+2% でも正。窓 24/60/120 か月でも同じ",
    ]
    for rule, nm, gr in (('dynamic', 'P_JKP_ocf_at[3]_dynamic', 'S'), ('static', 'P_JKP_ocf_at[3]_static', 'S'), ('unlevered', 'U_JKP_ocf_at[3]_unlevered', 'S')):
        e = o[rule]
        key = {'dynamic': 'ocf_at_dynamic', 'static': 'ocf_at_static', 'unlevered': 'ocf_at_unlevered'}[rule]
        iss = [f"選び出しの窓を除いた全期間 {c7[key]['excl_196307_200612_gross'][0]:+.2f} t{c7[key]['excl_196307_200612_gross'][1]}（C7 の t≥3 に届かない）"] + common_ocf[:1] + common_ocf[1:]
        cp, ew_ = nb[f'ocf_at[3]_vw_cap_{rule}'], nb[f'ocf_at[3]_ew_{rule}']
        iss.append(f"巨大株依存（この規則）: vw_cap 版の保有（費用後）{cp['hold_net']['ex']:+.2f} t{cp['hold_net']['t']}（訓練は {cp['train']['ex']:+.2f} t{cp['train']['t']}）・等加重 {ew_['hold_net']['ex']:+.2f}")
        iss.append(f"この規則の小区間（費用後）: 2007-12 {e['robust']['sub_2007_2012']['ex']:+.2f} t{e['robust']['sub_2007_2012']['t']} / 2013-19 {e['robust']['sub_2013_2019']['ex']:+.2f} t{e['robust']['sub_2013_2019']['t']} / 2020-（公表後）{e['robust']['sub_2020_end']['ex']:+.2f} t{e['robust']['sub_2020_end']['t']}・"
                   f"保有の前半 {e['robust']['hold_half1_200701_201606']['ex']:+.2f} t{e['robust']['hold_half1_200701_201606']['t']} / 後半 {e['robust']['hold_half2_201607_end']['ex']:+.2f} t{e['robust']['hold_half2_201607_end']['t']}・"
                   f"2020-21 を除く {e['robust']['hold_drop_2020_2021']['ex']:+.2f} t{e['robust']['hold_drop_2020_2021']['t']}・全期間から 1998-2000 を除く t{e['robust']['full_drop_1998_2000']['t']}・"
                   f"最良12か月を除く {e['robust']['hold_drop_best12_months']:+.2f} / 24か月を除く {e['robust']['hold_drop_best24_months']:+.2f}（最良12か月が超過の {int(e['robust']['share_of_hold_excess_from_best12'] * 100)}%）")
        iss.append(f"日本の課税口座（20.315%・回転率0.4）: 税引後の年率差 {e['tax_japan_taxable_hold']['after_tax_cagr_diff']:+.2f}（税前 {e['tax_japan_taxable_hold']['pretax_cagr_diff']:+.2f}）")
        if rule != 'unlevered':
            iss.append(f"倍率は平均 {e['L_mean']}＝借入はほぼ使っていない。『同じリスクで勝つ』ではなく、倍率1の質の三分位（U）と同じもの")
        V.append({'name': nm, 'claimed_grade': gr, 'reproduced': True, 'verified_grade': 'B', 'verdict': 'downgraded to B',
                  'key_numbers': num(e), 'issues': iss})
    common_x5 = [
        '事前登録5（探索）は第1〜4族の結果を見た後に登録: 構成要素（質の上位三分位の保有期間 +2〜3%/年・低リスクは借入で勝つ）の保有期間の成績を知ったうえで『質＋低リスク』を選んだ（登録文が自認）。全体の約束（honesty_rules 2）は保有期間を見て作った規則を判定に使わない。事前登録どおりの同じ考え（P の BLEND6＝低リスク3＋質3 をぶれ合わせ）は A（保有 +1.27〜1.34 t1.25〜1.30）どまり',
        f"倍率1の同じ混合は保有 {x['jkp_QLR_ALL_unlevered']['hold']['ex']:+.2f} t{x['jkp_QLR_ALL_unlevered']['hold']['t']}（C）。勝ちの全部が β {x['_capm_QLR_unlevered_hold']['beta']}→1 の持ち上げで、CAPM α 保有 {x['_capm_QLR_unlevered_hold']['alpha']} t{x['_capm_QLR_unlevered_hold']['t_alpha_approx']} を超過に変えたもの（理屈どおり）だが、α は 2020〜 {x['_capm_QLR_unlevered_post2020']['alpha']} t{x['_capm_QLR_unlevered_post2020']['t_alpha_approx']} に縮んだ",
        f"巨大株依存: vw_cap で作ると保有 {x['jkp_QLR_ALL_beta_dynamic_VWCAP']['hold_net']['ex']:+.2f}〜{x['jkp_QLR_ALL_static_VWCAP']['hold_net']['ex']:+.2f}（訓練は +2.07〜+2.68 t3.1〜3.8）＝訓練で効いた形は保有期間に効かず、勝ちは上限なしの時価加重でだけ",
        f"信用（借入）は NISA で使えない＝課税口座。研究者の回転率（{x['_turnover']['QLR']}×倍率）で税引後の年率差は +0.2 前後（回転が半分なら {a['tax_QLR_beta_dynamic_half_turnover']['after_tax_cagr_diff']:+.2f}・1/4 なら {a['tax_QLR_beta_dynamic_quarter_turnover']['after_tax_cagr_diff']:+.2f}）",
        f"角度全体の多重検定: 紙の上の格付け {a['angle_wide_multiple_testing']['m']}本・Holm/ボンフェローニは保有 t≥{a['angle_wide_multiple_testing']['bonferroni_t_needed_two_sided_5pct']} が要る（届かない）。BH 5% の切れ目は p≤{a['angle_wide_multiple_testing']['bh_p_cutoff']}（t≈2.92）",
        '反証できなかった点: 数字は完全に再現。良い側を自前の『訓練シャープ』で決め直すと JKP の向きと違うのは 1特徴だけで、結果もほぼ同じ。4地域すべて正（自前の再計算）。倍率の窓 24/60 か月・費用3倍×回転2倍・借入 RF+2〜3% でも保有期間は正。C7 は選び出しの窓を除いても t≥3（選び出しをしていない混合なので全期間 t は汚れていない）',
    ]
    for rule, nm in (('beta_dynamic', 'X5_X5_QLR_ALL_beta_dynamic'), ('beta_static', 'X5_X5_QLR_ALL_beta_static'), ('dynamic', 'X5_X5_QLR_ALL_dynamic'), ('static', 'X5_X5_QLR_ALL_static')):
        e = x[f'jkp_QLR_ALL_{rule}']
        ss = a[f'QLR_sharpe_sides_{rule}']
        iss = list(common_x5)
        iss.append(f"この規則（費用後）: 保有の前半 {e['robust']['hold_half1_200701_201606']['ex']:+.2f} t{e['robust']['hold_half1_200701_201606']['t']} / 後半（2016-07〜） {e['robust']['hold_half2_201607_end']['ex']:+.2f} t{e['robust']['hold_half2_201607_end']['t']}・2020〜 {e['robust']['post_2020']['ex']:+.2f} t{e['robust']['post_2020']['t']}・"
                   f"2020-21 を除く {e['robust']['hold_drop_2020_2021']['ex']:+.2f} t{e['robust']['hold_drop_2020_2021']['t']}・全期間から 1998-2000 を除く t{e['robust']['full_drop_1998_2000']['t']}・"
                   f"最良24か月を除く {e['robust']['hold_drop_best24_months']:+.2f}・最良12か月が超過の {int(e['robust']['share_of_hold_excess_from_best12'] * 100)}%")
        iss.append(f"税引後（研究者の回転率）{e['tax_japan_taxable_hold']['after_tax_cagr_diff']:+.2f}（税前 {e['tax_japan_taxable_hold']['pretax_cagr_diff']:+.2f}）・費用3倍×回転2倍 {e['cost3x_turnover2x_hold']['ex']:+.2f}")
        iss.append(f"訓練シャープで良い側を決め直した版: 保有 {ss['hold']['ex']:+.2f} t{ss['hold']['t']}（費用後 {ss['hold_net']['ex']:+.2f}）")
        V.append({'name': nm, 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'B', 'verdict': 'downgraded to B',
                  'key_numbers': num(e) + f" / 選び出しの窓を除く全期間 t{c7['QLR_' + rule]['excl_196307_200612_gross'][1]}", 'issues': iss})
    e = x['jkp_Q_ALL_beta_dynamic']
    iss = [common_x5[0],
           f"倍率は平均 {e['L_mean']}（{e['L_min']}〜{e['L_max']}）＝倍率1の質の混合に小さなβの時機を足しただけ。同じ混合の5規則の中の最良: 倍率1 {x['jkp_Q_ALL_unlevered']['hold']['ex']:+.2f} t{x['jkp_Q_ALL_unlevered']['hold']['t']}・固定 {x['jkp_Q_ALL_static']['hold']['ex']:+.2f} t{x['jkp_Q_ALL_static']['hold']['t']}（B）・β固定 {x['jkp_Q_ALL_beta_static']['hold']['ex']:+.2f} t{x['jkp_Q_ALL_beta_static']['hold']['t']}",
           f"C7 は族内 Holm 0.0465（境目）か全期間 t{e['full']['t']}（1963-07 から {c7['Q_beta_dynamic']['from_196307_gross'][1]}・選び出しの窓を除くと {c7['Q_beta_dynamic']['excl_196307_200612_gross'][1]}）＝ぎりぎり。訓練 t{e['train']['t']}",
           f"巨大株依存: vw_cap 版 保有 {x['jkp_Q_ALL_beta_dynamic_VWCAP']['hold_net']['ex']:+.2f}（訓練 {x['jkp_Q_ALL_beta_dynamic_VWCAP']['train']['ex']:+.2f} t{x['jkp_Q_ALL_beta_dynamic_VWCAP']['train']['t']}）＝ocf_at と同じ現象（上限なしの時価加重の質）",
           f"小区間: 2013-19 {e['robust']['sub_2013_2019']['ex']:+.2f} t{e['robust']['sub_2013_2019']['t']}・2020〜 {e['robust']['post_2020']['ex']:+.2f} t{e['robust']['post_2020']['t']}・最良24か月を除く {e['robust']['hold_drop_best24_months']:+.2f}",
           f"税引後（課税口座）{e['tax_japan_taxable_hold']['after_tax_cagr_diff']:+.2f}（税前 {e['tax_japan_taxable_hold']['pretax_cagr_diff']:+.2f}）",
           f"反証できなかった点: 数字は完全に再現・訓練シャープで側を決め直しても保有 {a['Q_sharpe_sides_beta_dynamic']['hold']['ex']:+.2f} t{a['Q_sharpe_sides_beta_dynamic']['hold']['t']}・4地域すべて正・BH 5%（角度全体）はかろうじて通る（t2.96）"]
    V.append({'name': 'X5_X5_Q_ALL_beta_dynamic', 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'B', 'verdict': 'downgraded to B',
              'key_numbers': num(e), 'issues': iss})
    return V


if __name__ == '__main__':
    out = main()
    out['verdicts'] = build_verdicts(out)
    out['summary_ja'] = SUMMARY
    out['note_outside_claims'] = ('主張の外（格付け S だが報告されていない）: X2_FR_VAR[Dec 2]_beta_static の保有 +5.95%/年は French の分散の十分位15列から訓練シャープで1列を選んだもの。'
                                  '同じ表の倍率1の保有期間は Dec 2 +2.37 に対し隣の Lo 10 −2.02・Dec 3 −0.90・Lo 20 −0.11＝孤立した1列で、選び出しの運の型。勝ちとして数えないこと')
    p = os.path.join(BASE, 'out', 'mw_risk_matched_verify.json')
    json.dump(out, open(p, 'w'), ensure_ascii=False, indent=1)
    print('saved', p)
