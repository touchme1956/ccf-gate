#!/usr/bin/env python3
"""night/mw_dominant_market_verify.py — 角度 dominant_market の反証の検証（読むだけ・門の判定には不使用）

対象: out/mw_dominant_market.json の B 2本
  E1_SC_XUS   : French の米国外20か国のうち、前年末の時価（世界銀行）が小さい半分を等分・毎年1月
  F1_SC_JKPDEV: 同じ規則を JKP の米国外先進国22か国に当てたもの

方針（検証役の約束）
- mw_common は**取得だけ**に使う（M.get / M.ff_factors / M.jkp_mkt）。French の .Dat の読み方・時価の推定・
  ポートフォリオの組み方・超過・NW t・CAGR・転がる窓・積立・費用は**このファイルの中で独自に書く**。
- 研究者の数字を再現したうえで、壊しに行く: 相手（French Ind_all＝上限なしの時価加重の米国外）、
  国の生き残り（マレーシア 1994-2001・ポルトガル 1998〜・ギリシャ 2002-2013・イスラエル 2011〜）、
  隣の規則（分位・戻す月・時価の遅れ・中の重み・大きさの物差し）、期間の抜き取り、費用、無作為の半分との比較。
- 出力: out/mw_dominant_market_verify.json
"""
import sys, os, io, json, math, zipfile, random, statistics as S, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけ（get / ff_factors / jkp_mkt）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRU = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}.zip'
WBU = 'https://api.worldbank.org/v2/country/all/indicator/{}?format=json&per_page=20000&date={}'
FRFILE = {'GBR': 'UK', 'AUT': 'Austria', 'AUS': 'Austrlia', 'BEL': 'Belgium', 'CAN': 'Canada', 'DNK': 'Denmark',
          'FIN': 'Finland', 'FRA': 'France', 'DEU': 'Germany', 'HKG': 'HongKong', 'IRL': 'Ireland', 'ITA': 'Italy',
          'JPN': 'Japan', 'NLD': 'Nethrlnd', 'NZL': 'NewZland', 'NOR': 'Norway', 'SGP': 'Singapor', 'ESP': 'Spain',
          'SWE': 'Sweden', 'CHE': 'Swtzrlnd', 'MYS': 'Malaysia'}
X20 = sorted(c for c in FRFILE if c != 'MYS')
DEV22 = 'JPN GBR DEU FRA CHE NLD SWE DNK NOR FIN BEL AUT ITA ESP IRL PRT CAN AUS NZL HKG SGP ISR'.split()
TRAIN_END, HOLD0, RECENT0 = 200612, 200701, 201307
OUT = {}


# ───────────────────────── 読み（独自） ─────────────────────────
def dat_block(txt, cur='Dollar'):
    """French の .Dat の最初の『<cur> Returns … Not Reqd』の月次の表の Mkt 列 → {yyyymm: 小数}"""
    st, out = 0, {}
    for ln in txt.splitlines():
        tok = ln.split()
        if st == 0:
            if cur in ln and 'Returns' in ln and 'Not Reqd' in ln:
                st = 1
            continue
        if st == 1:
            if tok and tok[0] == 'Mkt':
                st = 2
            continue
        if tok and tok[0].isdigit() and len(tok[0]) == 6:
            v = float(tok[1])
            if v > -99.0:
                out[int(tok[0])] = v / 100.0
            continue
        if out:
            break
    return out


def load_french():
    zt = zipfile.ZipFile(io.BytesIO(M.get(FRU.format('F-F_International_Countries'), name='fr_F-F_International_Countries.zip')))
    zx = zipfile.ZipFile(io.BytesIO(M.get(FRU.format('F-F_International_Countries_Wout_Div'), name='fr_F-F_International_Countries_Wout_Div.zip')))
    zi = zipfile.ZipFile(io.BytesIO(M.get(FRU.format('F-F_International_Indices'), name='fr_F-F_International_Indices.zip')))
    tot, px, loc = {}, {}, {}
    for c, f in FRFILE.items():
        t = zt.read(f + '.Dat').decode('latin-1')
        tot[c] = dat_block(t, 'Dollar')
        loc[c] = dat_block(t, 'Local')
        px[c] = dat_block(zx.read(f + '.Dat').decode('latin-1'), 'Dollar')
    ind_all = dat_block(zi.read('Ind_all.Dat').decode('latin-1'), 'Dollar')
    return tot, px, loc, ind_all


def load_wb(ind, name, dates):
    j = json.loads(M.get(WBU.format(ind, dates), name=name, max_age_days=3650))
    return {(r['countryiso3code'], int(r['date'])): float(r['value']) for r in j[1] if r['value'] is not None}


# ───────────────────────── 時価の推定（独自の掃除） ─────────────────────────
def year_growth(ser, Y):
    ms = [Y * 100 + m for m in range(1, 13)]
    if all(m in ser for m in ms):
        return math.prod(1 + ser[m] for m in ms)
    return None


def cap_est(c, wbcap, growser, mode='clean', y0=1974, y1=2025):
    """年末の時価の推定 {Y: 値}。
    raw  : 観測があれば観測、無ければ前年の推定を価格で運ぶ
    clean: 観測が運んだ値の 0.5〜2 倍の外なら棄却（運んだ値を使う）。ただし棄却された観測が2年続けて互いに整合したら
           2年目を新しい水準として採る（その年までに分かることだけで決まる）"""
    est, prev, rej_prev = {}, None, None
    for Y in range(y0, y1 + 1):
        obs = wbcap.get((c, Y))
        g = year_growth(growser, Y) if growser is not None else None
        carried = prev * g if (prev is not None and g is not None) else None
        v = None
        if mode == 'raw':
            v = obs if obs is not None else carried
        else:
            if obs is not None and (carried is None or 0.5 <= obs / carried <= 2.0):
                v, rej_prev = obs, None
            elif obs is not None:
                if rej_prev is not None and g is not None and 0.5 <= obs / (rej_prev * g) <= 2.0:
                    v, rej_prev = obs, None
                else:
                    v, rej_prev = carried, obs
            else:
                v = carried
                rej_prev = rej_prev * g if (rej_prev is not None and g is not None) else None
        est[Y] = v
        prev = v
    return est


# ───────────────────────── ポートフォリオ（独自） ─────────────────────────
def nxt(m):
    y, mm = divmod(m, 100)
    return (y + 1) * 100 + 1 if mm == 12 else m + 1


def sim(wfun, rets, y0, y1, rebal=1):
    """年に一度 rebal 月に目標へ戻し、年の中は漂わせる。途中で系列が切れた国はその月に売って残りへ比例で回す（0 と読まない）。
    → (月次リターン, {年: 片道回転}, {年: 目標})"""
    out, turn, tgt = {}, {}, {}
    drift = None
    for Y in range(y0, y1 + 1):
        w = wfun(Y)
        if not w:
            drift = None
            continue
        tgt[Y] = w
        turn[Y] = 0.5 * sum(abs(w.get(c, 0) - drift.get(c, 0)) for c in set(w) | set(drift)) if drift else 0.0
        h = dict(w)
        m = Y * 100 + rebal
        for _ in range(12):
            av = [c for c in h if m in rets[c]]
            if not av:
                break
            V = sum(h.values())
            if len(av) < len(h):
                Va = sum(h[c] for c in av)
                h = {c: h[c] * V / Va for c in av}
            out[m] = sum(h[c] * rets[c][m] for c in h) / V
            for c in h:
                h[c] *= 1 + rets[c][m]
            m = nxt(m)
        t = sum(h.values())
        drift = {c: v / t for c, v in h.items()}
    return out, turn, tgt


def net(r, turn, fee, tc, rebal=1):
    o = {}
    for m, v in r.items():
        Y = m // 100 if m % 100 >= rebal else m // 100 - 1
        d = fee / 12 + (tc * turn.get(Y, 0.0) if m % 100 == rebal else 0.0)
        o[m] = v - d
    return o


# ───────────────────────── 統計（独自） ─────────────────────────
def nwt(x, L=12):
    n = len(x)
    mu = sum(x) / n
    e = [v - mu for v in x]
    lrv = sum(v * v for v in e) / n
    for l in range(1, L + 1):
        lrv += 2 * (1 - l / (L + 1)) * sum(e[i] * e[i - l] for i in range(l, n)) / n
    return mu / math.sqrt(lrv / n)


def geo(xs):
    return math.exp(sum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def st(s, b, a=None, z=None, drop=None):
    ks = [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z) and not (drop and drop(k))]
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(sum(d) / len(d) * 1200, 2), 't': round(nwt(d), 2),
            'cagr_diff': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2),
            'cagr_s': round(geo([s[k] for k in ks]) * 100, 2), 'cagr_b': round(geo([b[k] for k in ks]) * 100, 2)}


def roll20(s, b):
    ks = set(s) & set(b)
    res = []
    for Y in range(1900, 2100):
        ms, m = [], Y * 100 + 7
        for _ in range(240):
            ms.append(m); m = nxt(m)
        if ms[-1] > max(ks):
            break
        if not all(k in ks for k in ms):
            continue
        res.append((Y, (geo([s[k] for k in ms]) - geo([b[k] for k in ms])) * 100))
    if not res:
        return None
    v = sorted(x for _, x in res)
    return {'windows': len(res), 'wins': sum(1 for x in v if x > 0), 'median': round(v[len(v) // 2], 2), 'worst': [res[[x for _, x in res].index(v[0])][0], round(v[0], 2)]}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    res = []
    for i in range(0, len(ks) - 239, 12):
        w = ks[i:i + 240]
        vs = vb = 0.0
        for k in w:
            vs = (vs + 1) * (1 + s[k]); vb = (vb + 1) * (1 + b[k])
        res.append(vs / vb)
    if not res:
        return None
    v = sorted(res)
    return {'windows': len(v), 'wins': sum(1 for x in v if x > 1), 'median': round(v[len(v) // 2], 3), 'worst': round(v[0], 3)}


def pack(s, b, turn=None, fee=0.004, tc=0.0015, rebal=1, full=True):
    o = {'full': st(s, b), 'train': st(s, b, None, TRAIN_END), 'hold': st(s, b, HOLD0), 'recent': st(s, b, RECENT0)}
    if turn is not None:
        sn = net(s, turn, fee, tc, rebal)
        o['hold_net'] = st(sn, b, HOLD0)
        o['avg_turn'] = round(S.mean(turn.values()), 3) if turn else None
    if full:
        o['roll20'] = roll20(s, b)
        o['dca20'] = dca20(s, b)
    return o


def brief(p):
    """判定に効く数字だけ"""
    g = lambda k, f: (p.get(k) or {}).get(f)
    return {'train': [g('train', 'ex'), g('train', 't')], 'hold': [g('hold', 'ex'), g('hold', 't'), g('hold', 'cagr_diff')],
            'hold_net': [g('hold_net', 'ex'), g('hold_net', 'cagr_diff')] if 'hold_net' in p else None,
            'full': [g('full', 'ex'), g('full', 't')]}


def b_grade(p):
    """B の線（C1・C2・C6）だけを独自に当てる"""
    tr, ho, hn = p.get('train'), p.get('hold'), p.get('hold_net')
    c1 = bool(tr and tr['ex'] > 0 and tr['t'] >= 2.0)
    c2 = bool(ho and ho['ex'] > 0 and ho['cagr_diff'] > 0)
    c6 = bool(hn and hn['ex'] > 0 and hn['cagr_diff'] > 0)
    c3 = bool(ho and ho['t'] >= 1.65)
    return {'C1': c1, 'C2': c2, 'C3': c3, 'C6': c6, 'B_or_better': c1 and c2 and c6}


# ───────────────────────── 本体 ─────────────────────────
def main():
    tot, px, loc, ind_all = load_french()
    wbcap = load_wb('CM.MKT.LCAP.CD', 'wb_mktcap_all.json', '1970:2025')
    wbgdp = load_wb('NY.GDP.MKTP.CD', 'wb_gdp_all.json', '1960:2025')
    ff = M.ff_factors()
    rf = ff['rf']
    jk = {}
    for c in DEV22 + ['GRC', 'MYS']:
        jk[c] = {k: v + rf[k] for k, v in M.jkp_mkt(c.lower(), 'vw').items() if k in rf}
    jdev = {k: v + rf[k] for k, v in M.jkp_mkt('developed', 'vw').items() if k in rf}
    OUT['data'] = {'french_country_span': {c: [min(v), max(v), len(v)] for c, v in tot.items()},
                   'ind_all_span': [min(ind_all), max(ind_all)],
                   'wb_cap_last_obs': {c: max([Y for (cc, Y) in wbcap if cc == c] or [None]) for c in X20 + ['MYS', 'PRT', 'GRC', 'ISR']},
                   'note': 'WB の時価は多くの国で途中で途切れる（SWE 2003・DNK/FIN 2004・ITA 2014・GBR 2014〔2021-22 だけ再開〕・NLD 2017・FRA/BEL/IRL/PRT 2018・NOR 2019）＝保有期間の大きさの順位の多くは価格で運んだ推定'}

    # 時価の推定（French の国は配当抜きの価格で運ぶ／JKP だけの国は総リターンで運ぶ）
    caps = {}
    for mode in ('clean', 'raw'):
        caps[mode] = {c: cap_est(c, wbcap, px[c], mode) for c in FRFILE}
        for c in ('PRT', 'GRC', 'ISR'):
            caps[mode][c] = cap_est(c, wbcap, jk[c], mode)

    # ═════════ E1: French 20 か国 ═════════
    frs = {c: min(v) for c, v in tot.items()}
    R = dict(tot)
    for c in ('PRT', 'GRC', 'ISR'):
        R[c] = jk[c]

    def universe(Y, extra=(), mode='clean', lag=1):
        u = [c for c in X20 if frs[c] <= Y * 100 + 1]
        for c, a, z in extra:
            if a <= Y <= z and (Y * 100 + 1) in R[c]:   # その年の1月に系列が生きている国だけ
                u.append(c)
        k = {c: caps[mode][c].get(Y - lag) for c in u}
        return {c: v for c, v in k.items() if v}

    def small_rule(frac=0.5, mode='clean', extra=(), lag=1, inner='ew', size='cap', n_fix=None):
        def f(Y):
            k = universe(Y, extra, mode, lag)
            if len(k) < 4:
                return None
            if size == 'gdp':
                g = {c: wbgdp.get((c, Y - 2)) for c in k}
                if any(v is None for v in g.values()):
                    g = {c: v for c, v in g.items() if v}
                rank = g
            else:
                rank = k
            n = n_fix(len(rank)) if n_fix else int(math.floor(len(rank) * frac))
            n = max(1, n)
            sm = sorted(rank, key=lambda c: (rank[c], c))[:n]
            if inner == 'cap':
                t = sum(k[c] for c in sm)
                return {c: k[c] / t for c in sm}
            return {c: 1.0 / n for c in sm}
        return f

    def capw(mode='clean', extra=(), lag=1):
        def f(Y):
            k = universe(Y, extra, mode, lag)
            if len(k) < 2:
                return None
            t = sum(k.values())
            return {c: v / t for c, v in k.items()}
        return f

    E = {}
    s, turn, tgt = sim(small_rule(), R, 1976, 2025)
    b, _, _ = sim(capw(), R, 1976, 2025)
    E['repro_clean'] = pack(s, b, turn)
    E['repro_clean']['weights_sample'] = {Y: sorted(tgt[Y]) for Y in (1976, 1990, 2007, 2025) if Y in tgt}
    E['repro_clean']['universe_size'] = {Y: len(universe(Y)) for Y in (1976, 1980, 1990, 2007, 2025)}
    E['repro_clean']['B_lines'] = b_grade(E['repro_clean'])
    s_raw, turn_raw, _ = sim(small_rule(mode='raw'), R, 1976, 2025)
    b_raw, _, _ = sim(capw(mode='raw'), R, 1976, 2025)
    E['repro_raw_caps'] = brief(pack(s_raw, b_raw, turn_raw, full=False))
    # 相手の点検: 自作の時価加重 vs French Ind_all（上限なしの時価加重の米国外・MSCI 型）
    E['bench_check'] = {'own_capw_vs_ind_all': st(b, ind_all), 'own_capw_vs_ind_all_hold': st(b, ind_all, HOLD0),
                        'corr': round(M.corr([b[k] for k in sorted(set(b) & set(ind_all))], [ind_all[k] for k in sorted(set(b) & set(ind_all))]), 4)}
    # 相手を公式の地域の市場に替える（事前登録の non_US の相手）
    E['vs_french_ind_all'] = pack(s, ind_all, turn)
    E['vs_french_ind_all']['B_lines'] = b_grade(E['vs_french_ind_all'])
    E['vs_jkp_developed_vw'] = brief(pack(s, jdev, turn, full=False))

    # 国の生き残り（その時点で先進国に分類されていた国を宇宙に戻す）
    surv = {
        'plus_MYS_1994_2001': [('MYS', 1994, 2001)],
        'plus_PRT_1998on': [('PRT', 1998, 2025)],
        'plus_GRC_2002_2013': [('GRC', 2002, 2013)],
        'plus_ISR_2011on': [('ISR', 2011, 2025)],
        'plus_all_four': [('MYS', 1994, 2001), ('PRT', 1998, 2025), ('GRC', 2002, 2013), ('ISR', 2011, 2025)],
        'plus_PRT_GRC_ISR': [('PRT', 1998, 2025), ('GRC', 2002, 2013), ('ISR', 2011, 2025)],
    }
    E['survivorship'] = {}
    for nm, ex in surv.items():
        ss, tt, tg = sim(small_rule(extra=ex), R, 1976, 2025)
        bb, _, _ = sim(capw(extra=ex), R, 1976, 2025)
        p = pack(ss, bb, tt, full=False)
        p2 = pack(ss, ind_all, tt, full=False)
        E['survivorship'][nm] = {'vs_same_capw': brief(p), 'vs_same_capw_B': b_grade(p)['B_or_better'],
                                 'vs_ind_all': brief(p2), 'vs_ind_all_B': b_grade(p2)['B_or_better'],
                                 'held_extra': {Y: [c for c in tg[Y] if c in ('MYS', 'PRT', 'GRC', 'ISR')] for Y in sorted(tg) if any(c in ('MYS', 'PRT', 'GRC', 'ISR') for c in tg[Y])}}

    # 隣の規則
    nb = {}
    for nm, kw in (('frac_1_3', {'frac': 1 / 3}), ('frac_0_4', {'frac': 0.4}), ('frac_0_6', {'frac': 0.6}), ('frac_2_3', {'frac': 2 / 3}),
                   ('smallest_5', {'n_fix': lambda n: 5}), ('all_but_largest_5', {'n_fix': lambda n: n - 5}),
                   ('cap_lag_2y', {'lag': 2}), ('inner_capweight', {'inner': 'cap'}), ('size_by_gdp', {'size': 'gdp'}),
                   ('equal_all(E2)', {'frac': 1.0})):
        ss, tt, _ = sim(small_rule(**kw), R, 1976, 2025)
        p = pack(ss, b, tt, full=False)
        nb[nm] = dict(brief(p), B=b_grade(p)['B_or_better'])
    ss, tt, _ = sim(small_rule(), R, 1976, 2025, rebal=7)
    bb, _, _ = sim(capw(), R, 1976, 2025, rebal=7)
    p = pack(ss, bb, tt, rebal=7, full=False)
    nb['rebalance_july'] = dict(brief(p), B=b_grade(p)['B_or_better'])
    E['neighbors_vs_same_capw'] = nb

    # 期間の抜き取り（相手は自作の時価加重）
    E['subperiods'] = {
        'drop_1998_2000': st(s, b, drop=lambda k: 199801 <= k <= 200012),
        'train_drop_1990_1991_japan_crash': st(s, b, None, TRAIN_END, drop=lambda k: 199001 <= k <= 199112),
        'hold_drop_2020_2021': st(s, b, HOLD0, drop=lambda k: 202001 <= k <= 202112),
        'hold_first_half_2007_2016H1': st(s, b, HOLD0, 201606),
        'hold_second_half_2016H2_2025': st(s, b, 201607),
        'hold_2007_2012': st(s, b, HOLD0, 201212),
        'hold_2013_2025': st(s, b, 201301),
        'hold_drop_2022_2025': st(s, b, HOLD0, 202112),
    }
    # 保有期間の国ごとの寄与（超過 = Σ 重み×(国のリターン − 相手)。年の中は漂った重みで）
    contrib = {}
    for Y in range(2007, 2026):
        if Y not in tgt:
            continue
        h = dict(tgt[Y]); m = Y * 100 + 1
        for _ in range(12):
            if m not in b:
                break
            V = sum(h.values())
            for c in h:
                if m in R[c]:
                    contrib[c] = contrib.get(c, 0.0) + h[c] / V * (R[c][m] - b[m])
            for c in h:
                if m in R[c]:
                    h[c] *= 1 + R[c][m]
            m = nxt(m)
    nm_ = len([k for k in b if HOLD0 <= k <= 202512])
    E['hold_contrib_pp_per_year'] = {c: round(v / nm_ * 1200, 2) for c, v in sorted(contrib.items(), key=lambda x: -x[1])}
    # 費用の感度（保有期間）
    E['cost_sensitivity_hold'] = {}
    for nm, fee, tc in (('prereg_0.40fee_0.15tc', 0.004, 0.0015), ('etf_0.45fee_0.30tc', 0.0045, 0.003), ('etf_0.50fee_0.30tc', 0.005, 0.003),
                        ('etf_0.50fee_0.30tc_vs_ind_all', 0.005, 0.003)):
        bench = ind_all if nm.endswith('ind_all') else b
        x = st(net(s, turn, fee, tc), bench, HOLD0)
        E['cost_sensitivity_hold'][nm] = [x['ex'], x['t'], x['cagr_diff']]
    # 無作為の半分（等分）と比べる: 『小さい』が特別か、『時価加重でない』だけか
    rnd = random.Random(20260928)
    tr_l, ho_l = [], []
    for _ in range(300):
        seeds = {}

        def rf_(Y, seeds=seeds):
            k = universe(Y)
            if len(k) < 4:
                return None
            n = len(k) // 2
            if Y not in seeds:
                seeds[Y] = rnd.sample(sorted(k), n)
            return {c: 1.0 / n for c in seeds[Y]}
        rs, _, _ = sim(rf_, R, 1976, 2025)
        tr_l.append(st(rs, b, None, TRAIN_END)['ex']); ho_l.append(st(rs, b, HOLD0)['ex'])
    pr = lambda L, v: round(sum(1 for x in L if x < v) / len(L), 3)
    E['placebo_random_half'] = {'n': 300, 'train_ex_median': round(S.median(tr_l), 2), 'hold_ex_median': round(S.median(ho_l), 2),
                                'train_ex_p90': round(sorted(tr_l)[269], 2), 'hold_ex_p90': round(sorted(ho_l)[269], 2),
                                'E1_train_pct': pr(tr_l, E['repro_clean']['train']['ex']), 'E1_hold_pct': pr(ho_l, E['repro_clean']['hold']['ex']),
                                'note': '毎年、宇宙から無作為に半分を選んで等分（小さい順ではない）。相手は自作の時価加重'}
    # 実在の器（国別 ETF・配当込み・信託報酬込み・生き残りの偏りあり）: 研究者の F4 を独自に作り直し、
    # MSCI が先進国に入れていた時期のギリシャ（GREK 2012-2013）・ポルトガル（PGAL 2014〜）・イスラエル（EIS 2011〜）を足した版と比べる
    ETF = {'EWA': 'AUS', 'EWO': 'AUT', 'EWK': 'BEL', 'EWC': 'CAN', 'EWQ': 'FRA', 'EWG': 'DEU', 'EWH': 'HKG', 'EWI': 'ITA', 'EWJ': 'JPN',
           'EWN': 'NLD', 'EWS': 'SGP', 'EWP': 'ESP', 'EWD': 'SWE', 'EWL': 'CHE', 'EWU': 'GBR', 'ENZL': 'NZL', 'EIRL': 'IRL', 'ENOR': 'NOR',
           'EFNL': 'FIN', 'EDEN': 'DNK'}
    EXTRA = {'EIS': ('ISR', 2011, 2030), 'GREK': ('GRC', 2012, 2013), 'PGAL': ('PRT', 2014, 2030)}
    try:
        yr = {}
        for t in list(ETF) + list(EXTRA) + ['EFA']:
            try:
                yr[t] = {k: v for k, v in M.yahoo(t).items() if k <= 202608}
            except Exception as ex:  # noqa
                yr[t] = {}
                OUT.setdefault('etf_fetch_fail', []).append(f'{t}: {ex}')
        if not yr.get('PGAL'):
            # PGAL（Global X MSCI Portugal・2013-11〜）は Yahoo から消えている（404）＝閉じた器は取れない（生き残りの偏りの実例）。
            # 代わりに JKP のポルトガル（vw・総）から信託報酬 0.58%/年を引いた値を 2014 年から当てる（代理・旗）
            yr['PGAL'] = {k: v - 0.0058 / 12 for k, v in jk['PRT'].items() if 201312 <= k <= 202608}
            OUT['pgal_proxy'] = 'PGAL は Yahoo に無い（404）。JKP prt vw − 0.58%/年 で代理'
        capE = {c: caps['clean'][c] for c in list(ETF.values()) + ['ISR', 'GRC', 'PRT']}

        def etf_rule(extra, small=True):
            def f(Y):
                k = {}
                for t, c in ETF.items():
                    if yr[t] and min(yr[t]) <= Y * 100 + 1 and Y * 100 + 1 in yr[t] and capE[c].get(Y - 1):
                        k[t] = capE[c][Y - 1]
                if extra:
                    for t, (c, a, z) in EXTRA.items():
                        if a <= Y <= z and yr[t] and Y * 100 + 1 in yr[t] and capE[c].get(Y - 1):
                            k[t] = capE[c][Y - 1]
                if len(k) < 4:
                    return None
                if not small:
                    tt = sum(k.values()); return {t: v / tt for t, v in k.items()}
                n = len(k) // 2
                return {t: 1.0 / n for t in sorted(k, key=lambda t: (k[t], t))[:n]}
            return f
        E['etf_check'] = {'span': {t: [min(v), max(v)] if v else None for t, v in yr.items()}}
        for nm, ex_ in (('ishares_only', False), ('plus_EIS_GREK_PGAL', True)):
            es, et, etg = sim(etf_rule(ex_), yr, 1997, 2026)
            eb, _, _ = sim(etf_rule(ex_, small=False), yr, 1997, 2026)
            E['etf_check'][nm] = {'vs_EFA_hold': st(es, yr['EFA'], HOLD0), 'vs_EFA_hold_first_half': st(es, yr['EFA'], HOLD0, 201606),
                                  'vs_EFA_2007_2012': st(es, yr['EFA'], HOLD0, 201212),
                                  'vs_same_capw_hold': st(es, eb, HOLD0), 'vs_EFA_full': st(es, yr['EFA']),
                                  'held_greek_portugal': {Y: [t for t in etg[Y] if t in ('GREK', 'PGAL', 'EIS')] for Y in sorted(etg) if any(t in ('GREK', 'PGAL', 'EIS') for t in etg[Y])},
                                  'cost_extra_0.15tc': st(net(es, et, 0.0, 0.0015), yr['EFA'], HOLD0)}
        E['etf_check']['note'] = ('ETF の値動きに信託報酬が入っている（EFA も同じ）。ETF は今も残るものだけ（生き残りの偏りあり）。'
                                  'ギリシャ ETF は 2011-12 まで無く、2008〜2011 のギリシャの崩れは ETF では持てなかった')
    except Exception as ex:  # noqa
        E['etf_check'] = f'失敗: {ex}'
    OUT['E1_SC_XUS'] = E

    # ═════════ F1: JKP の米国外先進国 22 か国 ═════════
    js = {c: min(v) for c, v in jk.items()}
    capJ = {}
    for mode in ('clean',):
        for c in DEV22 + ['GRC']:
            g = px[c] if c in px else jk[c]  # French にある国は配当抜きの価格で運ぶ（研究者は JKP の総リターンで運んだ）
            capJ[c] = cap_est(c, wbcap, g, mode)

    def fu(Y, members, lag=1):
        u = [c for c in members(Y) if js[c] <= Y * 100 + 1]
        k = {c: capJ[c].get(Y - lag) for c in u}
        return {c: v for c, v in k.items() if v}

    def f_small(members, frac=0.5):
        def f(Y):
            k = fu(Y, members)
            if len(k) < 4:
                return None
            n = int(math.floor(len(k) * frac))
            sm = sorted(k, key=lambda c: (k[c], c))[:n]
            return {c: 1.0 / n for c in sm}
        return f

    def f_cap(members):
        def f(Y):
            k = fu(Y, members)
            t = sum(k.values())
            return {c: v / t for c, v in k.items()} if len(k) >= 2 else None
        return f
    base_m = lambda Y: list(DEV22)
    msci_m = lambda Y: [c for c in DEV22 if not (c == 'PRT' and Y < 1998) and not (c == 'ISR' and Y < 2011)] + (['GRC'] if 2002 <= Y <= 2013 else [])
    F = {}
    fs, ft, ftg = sim(f_small(base_m), jk, 1987, 2025)
    fb, _, _ = sim(f_cap(base_m), jk, 1987, 2025)
    F['repro'] = pack(fs, fb, ft)
    F['repro']['B_lines'] = b_grade(F['repro'])
    F['repro']['weights_sample'] = {Y: sorted(ftg[Y]) for Y in (1987, 2000, 2007, 2012, 2025) if Y in ftg}
    F['vs_jkp_developed_vw'] = pack(fs, jdev, ft, full=False)
    F['vs_jkp_developed_vw']['B_lines'] = b_grade(F['vs_jkp_developed_vw'])
    F['vs_french_ind_all'] = brief(pack(fs, ind_all, ft, full=False))
    ms_, mt, mtg = sim(f_small(msci_m), jk, 1987, 2025)
    mb, _, _ = sim(f_cap(msci_m), jk, 1987, 2025)
    F['msci_membership'] = pack(ms_, mb, mt, full=False)
    F['msci_membership']['B_lines'] = b_grade(F['msci_membership'])
    F['msci_membership']['note'] = 'ポルトガルは 1998 年から・イスラエルは 2011 年から・ギリシャは 2002〜2013 年（MSCI が先進国に入れていた時期を暦年に丸めた）'
    F['msci_membership']['vs_jkp_developed_vw'] = brief(pack(ms_, jdev, mt, full=False))
    fnb = {}
    for nm, fr_ in (('frac_1_3', 1 / 3), ('frac_0_4', 0.4), ('frac_0_6', 0.6)):
        a_, t_, _ = sim(f_small(base_m, fr_), jk, 1987, 2025)
        p = pack(a_, fb, t_, full=False)
        fnb[nm] = dict(brief(p), B=b_grade(p)['B_or_better'])
    F['neighbors'] = fnb
    F['subperiods'] = {'hold_first_half': st(fs, fb, HOLD0, 201606), 'hold_second_half': st(fs, fb, 201607),
                       'hold_drop_2020_2021': st(fs, fb, HOLD0, drop=lambda k: 202001 <= k <= 202112),
                       'train_drop_1998_2000': st(fs, fb, None, TRAIN_END, drop=lambda k: 199801 <= k <= 200012)}
    F['cost_sensitivity_hold'] = {nm: (lambda x: [x['ex'], x['t'], x['cagr_diff']])(st(net(fs, ft, fee, tc), fb, HOLD0))
                                  for nm, fee, tc in (('prereg_0.40_0.15', 0.004, 0.0015), ('etf_0.50_0.30', 0.005, 0.003))}
    OUT['F1_SC_JKPDEV'] = F

    OUT['generated'] = datetime.date.today().isoformat()
    return OUT


def f3(x):
    return None if x is None else [x['ex'], x['t'], x['cagr_diff']]


def verdicts(o):
    """計算した数字から判定の記録を組む（文面の数字はすべて o から引く）"""
    E, F = o['E1_SC_XUS'], o['F1_SC_JKPDEV']
    rc, ia = E['repro_clean'], E['vs_french_ind_all']
    sv = E['survivorship']
    pa = sv['plus_PRT_GRC_ISR']
    nb = E['neighbors_vs_same_capw']
    sub = E['subperiods']
    pl = E['placebo_random_half']
    etf = E['etf_check'] if isinstance(E['etf_check'], dict) else {}
    e1 = {
        'name': 'E1_SC_XUS', 'claimed_grade': 'B', 'verified_grade': 'C', 'verdict': 'downgraded to C', 'reproduced': True,
        'reproduction': {
            'hold_same_capw': f3(rc['hold']), 'hold_net': [rc['hold_net']['ex'], rc['hold_net']['cagr_diff']],
            'train_same_capw_own_cap_cleaning': f3(rc['train']), 'full': f3(rc['full']), 'roll20': rc['roll20'], 'dca20': rc['dca20'],
            'vs_french_ind_all(prereg の非米国の相手)': {'train': f3(ia['train']), 'hold': f3(ia['hold']), 'hold_net': [ia['hold_net']['ex'], ia['hold_net']['cagr_diff']],
                                                     'roll20': ia['roll20'], 'B_lines': ia['B_lines']},
            'note': '保有期間は研究者と小数2桁まで一致（+1.49 t1.29 CAGR差+0.97・費用後 +1.08/+0.54）。訓練は自作の時価の掃除で +3.66 t2.23（研究者 +4.07 t2.61）——差は 1977〜80 年の世界銀行の誤値（日本・英国・スウェーデン）の扱いで相手の重みが変わるため。世界銀行に依らない French Ind_all を相手にすると訓練 +4.06 t2.62 で、研究者の数字を支持する',
        },
        'issues': [
            f"国の生き残り（最重要）: French の20か国は、MSCI がその時点で先進国に入れていたポルトガル（1998〜）・ギリシャ（2002〜2013）・イスラエル（2011〜）を含まない。この3か国を宇宙と相手の両方へ戻すと保有 {pa['vs_same_capw']['hold']}（超過・t・CAGR差）・費用後 {pa['vs_same_capw']['hold_net']}（超過・CAGR差）＝C2 と C6 が落ちる（相手を Ind_all にしても 費用後 {pa['vs_ind_all']['hold_net']}）。ギリシャだけでも費用後のCAGR差 {sv['plus_GRC_2002_2013']['vs_same_capw']['hold_net'][1]}、ポルトガルだけでも Ind_all 相手で {sv['plus_PRT_1998on']['vs_ind_all']['hold_net'][1]}。落ちた国は保有期間の結果を見て外されたのではない（French の一覧はマレーシアが 2001 年で切れていることから少なくとも 2001 年ごろには固まっていたとみられる・未確認）が、除かれた小さい先進国が保有期間にちょうど崩れた国なので、結果はこの一覧に依存する",
            f"マレーシア（French の一覧に 1994-01〜2001-10 ある）を戻しても訓練は崩れない（{sv['plus_MYS_1994_2001']['vs_same_capw']['train']}）。研究者がマレーシアを除いたことは結果を有利にしていない",
            f"隣の規則に脆い: 小さい1/3 は保有のCAGR差 {nb['frac_1_3']['hold'][2]}（C2 落ち）、小さい5か国 {nb['smallest_5']['hold'][2]}、0.4 は訓練 t {nb['frac_0_4']['train'][1]}（C1 落ち）、2/3 は訓練 t {nb['frac_2_3']['train'][1]}、大きさを GDP で測ると訓練 t {nb['size_by_gdp']['train'][1]}・費用後CAGR差 {nb['size_by_gdp']['hold_net'][1]}。B を保つのは 0.6・大きい5か国を除く・時価2年遅れ・中を時価加重・7月に戻す の5本（10本中5本）",
            f"保有期間の勝ちは 2013 年以降だけ: 2007〜2012 は CAGR差 {sub['hold_2007_2012']['cagr_diff']}、前半（2007〜2016上）{f3(sub['hold_first_half_2007_2016H1'])}、後半（2016下〜2025）{f3(sub['hold_second_half_2016H2_2025'])}。2020〜21を抜いても {f3(sub['hold_drop_2020_2021'])}",
            f"『小さい』が効いているかの無作為の対照: 毎年ランダムに半分の国を等分すると保有の超過の中央 {pl['hold_ex_median']}（90%点 {pl['hold_ex_p90']}）。E1 の保有 {rc['hold']['ex']} は無作為の {pl['E1_hold_pct']*100:.0f}%点＝保有期間の超過の大半は『時価加重でない（日英の大きい重みを薄める）』ことで、小さい順に選んだ上乗せ（約 {round(rc['hold']['ex']-pl['hold_ex_median'],2)}%/年）は偶然と区別できない（訓練は {pl['E1_train_pct']*100:.0f}%点）",
            f"保有期間の国ごとの寄与（%/年）: {E['hold_contrib_pp_per_year']}＝一国には頼っていない（デンマーク〔ノボ〕が最大 {E['hold_contrib_pp_per_year'].get('DNK')}）",
            f"費用: 信託報酬の上乗せ 0.50%/年・片道 0.30% でも保有の費用後 {E['cost_sensitivity_hold']['etf_0.50fee_0.30tc']}（Ind_all 相手 {E['cost_sensitivity_hold']['etf_0.50fee_0.30tc_vs_ind_all']}）＝費用だけでは落ちない。課税口座では毎年の戻し（片道 約{rc['avg_turn']*100:.0f}%）で売却益の課税が前倒しになる（数字には入れていない）",
            "実在の器（iShares の国別 ETF・信託報酬込み）で独自に作り直すと EFA に対し保有 " + (f"{f3(etf['ishares_only']['vs_EFA_hold'])}、ギリシャ GREK（2012-13）・ポルトガル（PGAL は Yahoo から消えており JKP で代理）・イスラエル EIS（2011〜）を足しても {f3(etf['plus_EIS_GREK_PGAL']['vs_EFA_hold'])}" if etf else '（取得失敗）') + "。これは E1 を支える材料だが、2007〜2011 は ETF が15か国分しか無く、小さい半分に豪州・スイスが入った別の組み合わせで、指数の E1（2007〜2012 は負け）とは中身が違う＝『どの国が宇宙にいるか』で結果が±3%/年振れることの実例でもある。訓練期間（15年）が無いので格付けには使えない",
            "多重検定: 角度の試行 212（うち格付け17）。E は主の族（12本すべて C）を見た後に登録した探索の族で、C_W3 の地域の再現（等分 vs 時価）を一部見ている。族内 Holm の保有 p 0.39。訓練の p 0.009 も格付けした17本で Bonferroni すれば 0.15",
            "先読み: 重みは年末 Y−1 の時価（世界銀行の値・価格で運ぶ推定）で年 Y の1月に決まり、リターンの先読みは無い。ただし世界銀行の表そのものは後から整えられた系列",
        ],
        'key_numbers': (f"再現: 保有 +{rc['hold']['ex']} t{rc['hold']['t']} CAGR差 +{rc['hold']['cagr_diff']}・費用後 +{rc['hold_net']['ex']}/+{rc['hold_net']['cagr_diff']}（一致）／Ind_all 相手 訓練 +{ia['train']['ex']} t{ia['train']['t']}・保有 +{ia['hold']['ex']}・費用後CAGR差 +{ia['hold_net']['cagr_diff']}／"
                        f"その時点の先進国（+葡・希・以）: 保有 CAGR差 {pa['vs_same_capw']['hold'][2]}・費用後 {pa['vs_same_capw']['hold_net'][1]} → C／2007-12 CAGR差 {sub['hold_2007_2012']['cagr_diff']}／無作為の半分の {pl['E1_hold_pct']*100:.0f}%点"),
        'why_grade': 'B の線（C1・C2・C6）は French の20か国の一覧の上でだけ成り立つ。その時点で先進国だった小さい国を戻す（生き残りの偏りを除く）と C2・C6 が落ち、隣の分位（1/3・0.4・2/3・GDP）でも半分が落ちる。懐疑を既定にして C へ下げる。実在の ETF 版は保有で勝っているが、訓練が無く宇宙の組み合わせが偶然に違うので、格を戻す根拠にはしない',
    }
    rp, mm = F['repro'], F['msci_membership']
    fnb, fsub = F['neighbors'], F['subperiods']
    f1 = {
        'name': 'F1_SC_JKPDEV', 'claimed_grade': 'B', 'verified_grade': 'C', 'verdict': 'downgraded to C', 'reproduced': True,
        'reproduction': {'train': f3(rp['train']), 'hold': f3(rp['hold']), 'hold_net': [rp['hold_net']['ex'], rp['hold_net']['cagr_diff']], 'roll20': rp['roll20'], 'dca20': rp['dca20'],
                         'vs_jkp_developed_vw': brief(F['vs_jkp_developed_vw']),
                         'note': '訓練は一致（+5.44 t2.77 vs 研究者 +5.45 t2.77）。保有は +1.43 t1.17（研究者 +1.10 t0.90）——時価を運ぶのに French の配当抜きの価格を使った（研究者は JKP の総リターン）ため小さい半分の顔ぶれが一部の年で変わる。どちらでも B の線は通るが、保有の大きさが時価の推定の方法で ±0.3%/年動く'},
        'issues': [
            f"分類の後知恵: JKP の22か国はポルトガルを 1987 年から・イスラエルを 1995 年から先進国として持つ（MSCI の先進国入りは 1998・2010）。一方でギリシャ（2001〜2013 に先進国）を持たない。その時点の分類に揃えると 訓練 {f3(mm['train'])}・保有 {f3(mm['hold'])}・費用後 {[mm['hold_net']['ex'], mm['hold_net']['cagr_diff']]} → C6 が落ちて C（JKP developed 相手でも {mm['vs_jkp_developed_vw']['hold_net']}）",
            f"隣の分位: 1/3 は費用後 {fnb['frac_1_3']['hold_net']}、0.4 は費用後 {fnb['frac_0_4']['hold_net']}（どちらも C）。0.6 だけ B",
            f"保有の前半（2007〜2016上）{f3(fsub['hold_first_half'])}・後半 {f3(fsub['hold_second_half'])}＝勝ちは後半",
            "独立ではない: E1 と同じ規則で、22か国中20か国が重なる。C5 の再現（新興国 F3）は t0.6 で、宇宙を替えた頑丈さの証拠としては弱い",
            "多重検定: E1 を見た後の探索の族（2本）で Holm の保有 p 0.73。C7 は届かない",
        ],
        'key_numbers': (f"再現: 訓練 +{rp['train']['ex']} t{rp['train']['t']}・保有 +{rp['hold']['ex']} t{rp['hold']['t']} CAGR差 +{rp['hold']['cagr_diff']}・費用後 +{rp['hold_net']['ex']}/+{rp['hold_net']['cagr_diff']}／"
                        f"その時点の分類: 保有 CAGR差 {mm['hold']['cagr_diff']}・費用後 {mm['hold_net']['cagr_diff']} → C／1/3・0.4 は費用後 負"),
        'why_grade': 'その時点の MSCI の分類で宇宙を作ると費用後の CAGR差が負（C6 落ち）。隣の分位でも落ちる。E1 の言い換えで独立の支えにならない',
    }
    return [e1, f1]


def save_final(o):
    v = verdicts(o)
    res = {
        'angle': 'dominant_market', 'role': 'adversarial verifier（反証の検証）', 'generated': o['generated'],
        'verified_file': 'out/mw_dominant_market.json', 'criteria_file': 'out/mw_prereg.json',
        'method': ('French の国別 .Dat・世界銀行の時価・JKP の国別を mw_common の取得部品で取り、.Dat の読み方・時価の推定（独自の掃除）・'
                   '年1回の戻しと年の中の漂い・系列が切れた国の売却・超過・NW t・CAGR・転がる20年・20年積立・費用はこのファイルで独自に実装。'
                   '相手は自作の同じ宇宙の時価加重に加え、prereg の非米国の相手 French Ind_all（上限なしの時価加重）と JKP developed vw'),
        'verdicts': v,
        'details': o,
        'summary_ja': SUMMARY,
    }
    p = os.path.join(BASE, 'out', 'mw_dominant_market_verify.json')
    json.dump(res, open(p, 'w'), ensure_ascii=False, indent=1, default=str)
    return p, res


SUMMARY = ('角度 dominant_market の B 2本を独自のコードで作り直した。E1（米国外20か国の小さい半分を等分）は保有期間の数字が研究者と一致し'
           '（+1.49%/年 t1.29・費用後 +1.08）、相手を French の米国外市場 Ind_all にしても B の線は通った。\n'
           'だが French の一覧にはその時点で先進国だったポルトガル（1998〜）・ギリシャ（2002〜13）・イスラエル（2011〜）が無い。'
           '戻すと保有の CAGR 差は −0.01、費用後 −0.44 で C2・C6 が落ちる（C）。\n'
           '隣の規則（小さい1/3・0.4・2/3・GDP で測る）でも半分が落ち、保有期間の勝ちは 2013 年以降だけ（2007〜12 は CAGR 差 −1.42）。\n'
           '無作為に半分の国を等分しても保有は +0.96 で、E1 はその 85%点＝『小さい』の上乗せは偶然と区別できない。\n'
           'F1（JKP 22か国版）もその時点の分類に揃えると費用後の CAGR 差が −0.39 で C。E1 と同じ規則の言い換えで独立の支えにならない。\n'
           '実在の iShares 国別 ETF で作り直すと EFA に保有 +2.15%/年（t2.01）勝っていたが、宇宙の組み合わせが偶然に違い、訓練期間も無いので格は戻さない。\n'
           '判定: E1・F1 とも B → C へ下げる。A・S は元から無い。')


if __name__ == '__main__':
    o = main()
    p, res = save_final(o)
    print('wrote', p)
    for v in res['verdicts']:
        print(v['name'], v['verdict'], v['key_numbers'])
    E, F = o['E1_SC_XUS'], o['F1_SC_JKPDEV']
    print('E1 repro', brief(E['repro_clean']), E['repro_clean']['roll20'], E['repro_clean']['dca20'], E['repro_clean']['avg_turn'])
    print('E1 weights', E['repro_clean']['weights_sample'], E['repro_clean']['universe_size'])
    print('E1 raw caps', E['repro_raw_caps'])
    print('bench check', E['bench_check'])
    print('E1 vs ind_all', brief(E['vs_french_ind_all']), E['vs_french_ind_all']['B_lines'], E['vs_french_ind_all']['roll20'])
    print('E1 vs jkp dev', E['vs_jkp_developed_vw'])
    for k, v in E['survivorship'].items():
        print('surv', k, v['vs_same_capw'], v['vs_same_capw_B'], '| ind_all', v['vs_ind_all'], v['vs_ind_all_B'])
        print('    held', v['held_extra'])
    for k, v in E['neighbors_vs_same_capw'].items():
        print('nb', k, v)
    for k, v in E['subperiods'].items():
        print('sub', k, v and (v['ex'], v['t'], v['cagr_diff']))
    print('contrib', E['hold_contrib_pp_per_year'])
    print('cost', E['cost_sensitivity_hold'])
    print('placebo', E['placebo_random_half'])
    print('F1 repro', brief(F['repro']), F['repro']['roll20'], F['repro']['dca20'], F['repro']['weights_sample'])
    print('F1 vs jdev', brief(F['vs_jkp_developed_vw']), 'ind_all', F['vs_french_ind_all'])
    print('F1 msci', brief(F['msci_membership']), F['msci_membership']['B_lines'], F['msci_membership']['vs_jkp_developed_vw'])
    print('F1 nb', F['neighbors'])
    print('F1 sub', {k: v and (v['ex'], v['t'], v['cagr_diff']) for k, v in F['subperiods'].items()})
    print('F1 cost', F['cost_sensitivity_hold'])
