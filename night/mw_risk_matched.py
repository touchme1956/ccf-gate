#!/usr/bin/env python3
"""night/mw_risk_matched.py — 『市場に勝てる歴史検証』の角度 risk_matched（読むだけ・門の判定には不使用）

問い: 市場よりシャープレシオの高い『買いだけ』のポートフォリオ（低ベータ・低ボラ・質・収益性）を、
      市場と同じぶれになるまで借入でふくらませる（ぶれが大きいものは現金で薄める）と、
      S&P500 型の純粋な市場（French Mkt）に 2007年以降も勝てたか。
事前登録: out/mw_risk_matched_prereg.json（線は out/mw_prereg.json・判定は mw_common.grade）
出力: out/mw_risk_matched.json

族
- P（主・Holm 14本）: 低リスク群の上位3源＋質群の上位3源（訓練シャープで選ぶ）＋その6本の等分混合 × {static, dynamic}
- U（参照）: P の7候補の倍率1
- X1（探索）: 残り49源の代表 × {static, dynamic}
- XU（探索・参照）: X1 の倍率1
- S（報告のみ）: P を 借入 RF+2% と 費用3倍 で
"""
import json, math, os, re, statistics as S, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

_FT, _orig_ft = {}, M.french_tables


def _ft_cached(name):  # French の zip を一度だけ読む（mw_common は変えない）
    if name not in _FT:
        _FT[name] = _orig_ft(name)
    return _FT[name]


M.french_tables = _ft_cached

BASE = M.BASE
ANGLE = 'risk_matched'
PREREG = 'mw_risk_matched_prereg.json'
LMAX, SPREAD, COST, WIN = 2.0, 0.01, 0.001, 36
RANK_A, RANK_Z = 196307, 200612
REGIONS = ['developed', 'world_ex_us', 'jpn', 'emerging']
NONUS = ['world_ex_us', 'jpn', 'emerging']

LOW_RISK = ["beta_60m", "beta_dimson_21d", "betabab_1260d", "betadown_252d", "earnings_variability", "ivol_capm_21d",
            "ivol_capm_252d", "ivol_ff3_21d", "ivol_hxz4_21d", "ocfq_saleq_std", "rmax1_21d", "rmax5_21d", "rvol_21d",
            "seas_6_10na", "turnover_126d", "zero_trades_126d", "zero_trades_21d", "zero_trades_252d"]
QUALITY = ["at_turnover", "cop_at", "cop_atl1", "dgp_dsale", "gp_at", "gp_atl1", "mispricing_perf", "ni_inc8q", "niq_at",
           "op_at", "op_atl1", "opex_at", "qmj", "qmj_growth", "qmj_prof", "qmj_safety", "sale_bev", "dolvol_var_126d",
           "ebit_bev", "ebit_sale", "f_score", "ni_be", "niq_be", "o_score", "ocf_at", "ope_be", "ope_bel1", "turnover_var_126d"]

JKP_TO = {}
for k in ["beta_60m", "betabab_1260d", "betadown_252d", "ivol_capm_252d"]:
    JKP_TO[k] = 0.4
for k in ["rvol_21d", "ivol_capm_21d", "ivol_ff3_21d", "ivol_hxz4_21d", "rmax1_21d", "rmax5_21d", "beta_dimson_21d", "zero_trades_21d"]:
    JKP_TO[k] = 1.5
for k in ["turnover_126d", "zero_trades_126d", "zero_trades_252d", "dolvol_var_126d", "turnover_var_126d"]:
    JKP_TO[k] = 0.6
for k in ["earnings_variability", "ocfq_saleq_std"]:
    JKP_TO[k] = 0.3
JKP_TO["seas_6_10na"] = 1.0
for k in ["gp_at", "gp_atl1", "cop_at", "cop_atl1", "op_at", "op_atl1", "ope_be", "ope_bel1", "ebit_bev", "ebit_sale",
          "ocf_at", "sale_bev", "at_turnover", "f_score", "o_score", "opex_at", "dgp_dsale", "ni_be"]:
    JKP_TO[k] = 0.4
for k in ["niq_at", "niq_be", "ni_inc8q"]:
    JKP_TO[k] = 0.8
for k in ["qmj", "qmj_prof", "qmj_safety", "qmj_growth", "mispricing_perf"]:
    JKP_TO[k] = 0.6
# C5 の地域で使う（French の源の対応先）
for k in ["at_gr1"]:
    JKP_TO[k] = 0.6
JKP_TO["be_me"] = 0.3
JKP_TO["ret_12_1"] = 1.5

FRENCH_SRC = {
    # 源: (ファイル, 列の選び方, 回転率, 群, 公表年, C5 の対応特徴, 意味)
    'BETA': ('Portfolios_Formed_on_BETA', 'all', 0.4, '低リスク', 2014, 'beta_60m', 'ベータ（60か月）'),
    'VAR': ('Portfolios_Formed_on_VAR', 'all', 1.5, '低リスク', 2006, 'rvol_21d', '分散（60日）'),
    'RESVAR': ('Portfolios_Formed_on_RESVAR', 'all', 1.5, '低リスク', 2006, 'ivol_ff3_21d', '残差分散（60日・FF3）'),
    'OP': ('Portfolios_Formed_on_OP', 'all', 0.4, '質', 2015, 'ope_be', '営業利益÷自己資本'),
    'INV': ('Portfolios_Formed_on_INV', 'all', 0.6, '質', 2008, 'at_gr1', '総資産の伸び'),
    'BIG_OP': ('6_Portfolios_ME_OP_2x3', 'big', 0.4, '質', 2015, 'ope_be', '大型株の営業利益÷自己資本'),
    'BIG_INV': ('6_Portfolios_ME_INV_2x3', 'big', 0.6, '質', 2008, 'at_gr1', '大型株の総資産の伸び'),
    'BIG_BM': ('6_Portfolios_2x3', 'big', 0.3, 'その他', 1992, 'be_me', '大型株の簿価÷時価'),
    'BIG_PRIOR': ('6_Portfolios_ME_Prior_12_2', 'big', 1.5, 'その他', 1993, 'ret_12_1', '大型株の勢い（12-2）'),
}


def sha_of(path):
    try:
        out = subprocess.run(['git', 'log', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip().split('\n')
        return out[-1] or None  # 最初に入ったコミット（事前登録）
    except Exception:  # noqa
        return None


def next_m(ym):
    y, m = divmod(ym, 100)
    return ym + 1 if m < 12 else (y + 1) * 100 + 1


def contiguous(d):
    ks = sorted(d)
    return all(next_m(a) == b for a, b in zip(ks, ks[1:]))


# ───────────────────────── データ ─────────────────────────
def col_center(col):
    """French の列名 → 分位の中心（%）"""
    c = col.strip()
    m = re.match(r'^(Lo|Hi) (\d+)$', c)
    if m:
        w = int(m.group(2))
        return w / 2 if m.group(1) == 'Lo' else 100 - w / 2
    if c == 'Med 40':
        return 50.0
    m = re.match(r'^Qnt (\d)$', c)
    if m:
        return (int(m.group(1)) - 0.5) * 20
    m = re.match(r'^Dec (\d+)$', c) or re.match(r'^(\d+)-Dec$', c)
    if m:
        return (int(m.group(1)) - 0.5) * 10
    if c.startswith('BIG Lo'):
        return 15.0
    if c.startswith('ME2'):
        return 50.0
    if c.startswith('BIG Hi'):
        return 85.0
    raise ValueError(col)


def tercile_of(center):
    return '1.0' if center < 100 / 3 else ('2.0' if center < 200 / 3 else '3.0')


def load_candidates(RF):
    cands = {}
    for src, (fname, how, to, grp, pub, cmap, mean) in FRENCH_SRC.items():
        s = M.french_series(fname, 'Value Weight')
        cols = [c for c in s if (how == 'all' or c.startswith('BIG') or c.startswith('ME2'))]
        for c in cols:
            name = f'FR_{src}[{c}]'
            cands[name] = {'name': name, 'kind': 'french', 'source': 'FR_' + src, 'col': c, 'group': grp, 'pub': pub,
                           'to': to, 'r': dict(s[c]), 'map': (cmap, tercile_of(col_center(c))),
                           'desc': f'French {mean}の {c}（時価加重）'}
    details = jkp_details()
    for grp, keys in (('低リスク', LOW_RISK), ('質', QUALITY)):
        for k in keys:
            try:
                p = M.jkp_portfolios('usa', k, 'vw')
            except Exception as e:  # noqa
                print('  JKP 取得失敗', k, e)
                continue
            for pf in ('1.0', '2.0', '3.0'):
                if pf not in p:
                    continue
                tot = {ym: v + RF[ym] for ym, v in p[pf].items() if ym in RF}
                name = f'JKP_{k}[{pf[0]}]'
                cands[name] = {'name': name, 'kind': 'jkp', 'source': 'JKP_' + k, 'col': pf, 'group': grp,
                               'pub': details.get(k, {}).get('pub'), 'to': JKP_TO[k], 'r': tot, 'map': (k, pf),
                               'desc': f"JKP 米国 {details.get(k, {}).get('name', k)} の三分位{pf[0]}（1=低い側・時価加重）"}
    return cands


def jkp_details():
    out = {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jkp_factor_details.xlsx'), read_only=True)
        rows = list(wb['details'].iter_rows(values_only=True))
        h = rows[0]
        ia, ic, iname = h.index('abr_jkp'), h.index('cite'), h.index('name_new')
        for r in rows[1:]:
            if not r[ia]:
                continue
            m = re.search(r'(19|20)\d{2}', str(r[ic] or ''))
            out[r[ia]] = {'pub': int(m.group(0)) if m else None, 'name': r[iname], 'cite': r[ic]}
    except Exception as e:  # noqa
        print('  Factor Details 読めず', e)
    return out


# ───────────────────────── 倍率 ─────────────────────────
def lever(r_ex, m_ex, rf, rule, L_static=None, to=0.4, cost=COST, spread=SPREAD, lmax=LMAX, win=WIN):
    """r_ex, m_ex: 月次の超過（小数）。rf: 月次 RF（重みの漂いと総リターンに使う）。
    戻り: (gross_ex, net_ex, info) 超過リターン（借入の上乗せ込み）。総リターン = 超過 + rf"""
    ks = sorted(k for k in set(r_ex) & set(m_ex) & set(rf))
    if not contiguous({k: 1 for k in ks}):  # 抜けがあれば連続した最長の区間だけ（欠測を0で埋めない）
        runs, cur = [], [ks[0]]
        for a, b in zip(ks, ks[1:]):
            if next_m(a) == b:
                cur.append(b)
            else:
                runs.append(cur); cur = [b]
        runs.append(cur)
        ks = max(runs, key=len)
    gross, net, Ls, trades = {}, {}, [], []
    hp, hm = [], []
    prevL = prev_r = prev_R = None
    for k in ks:
        if rule == 'static':
            L = L_static
        elif rule == 'unlevered':
            L = 1.0
        else:
            L = None
            if len(hp) >= win:
                sp, sm = S.stdev(hp[-win:]), S.stdev(hm[-win:])
                L = min(lmax, sm / sp) if sp > 0 else None
        hp.append(r_ex[k]); hm.append(m_ex[k])  # t の倍率を決めた後に t を履歴へ
        if L is None:
            continue
        g = L * r_ex[k] - max(L - 1, 0) * spread / 12
        c_under = L * to / 12 * cost
        if prevL is not None:
            w_drift = prevL * (1 + prev_r) / (1 + prev_R) if (1 + prev_R) > 0 else L
            tr = abs(L - w_drift)
        else:
            tr = 0.0
        trades.append(tr)
        gross[k] = g
        net[k] = g - c_under - tr * cost
        Ls.append(L)
        prevL, prev_r, prev_R = L, r_ex[k] + rf[k], g + rf[k]
    info = {'L_mean': round(S.mean(Ls), 3) if Ls else None, 'L_min': round(min(Ls), 3) if Ls else None,
            'L_max': round(max(Ls), 3) if Ls else None,
            'lev_turnover_ann': round(S.mean(trades) * 12, 3) if trades else None,
            'months': len(gross)}
    return gross, net, info


def static_L(r_ex, m_ex, z=M.TRAIN_END, lmax=LMAX):
    ks = sorted(k for k in set(r_ex) & set(m_ex) if k <= z)
    if len(ks) < 60:
        return None
    return min(lmax, S.stdev([m_ex[k] for k in ks]) / S.stdev([r_ex[k] for k in ks]))


def to_total(ex, rf):
    return {k: v + rf[k] for k, v in ex.items() if k in rf}


def sharpe_same(s_tot, b_tot, rf, a=None, z=None):
    ks = sorted(k for k in set(s_tot) & set(b_tot) & set(rf) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    def sh(d):
        x = [d[k] - rf[k] for k in ks]
        sd = S.stdev(x)
        return round(S.mean(x) / sd * math.sqrt(12), 3) if sd else None
    return (sh(s_tot), sh(b_tot))


def train_sharpe(r_tot, rf, a=RANK_A, z=RANK_Z):
    ks = [k for k in sorted(r_tot) if a <= k <= z and k in rf]
    need = (z // 100 - a // 100) * 12 + (z % 100) - (a % 100) + 1
    if len(ks) < need:
        return None
    x = [r_tot[k] - rf[k] for k in ks]
    return S.mean(x) / S.stdev(x) * math.sqrt(12)


# ───────────────────────── 地域（C5） ─────────────────────────
_REG = {}


def reg_series(region, key, pf):
    if (region, key) not in _REG:
        try:
            _REG[(region, key)] = M.jkp_portfolios(region, key, 'vw')
        except Exception as e:  # noqa
            _REG[(region, key)] = None
            print('  地域 取得失敗', region, key, str(e)[:80])
    p = _REG[(region, key)]
    return None if p is None else p.get(pf)


_RMKT = {}


def reg_mkt(region):
    if region not in _RMKT:
        _RMKT[region] = M.jkp_mkt(region, 'vw')
    return _RMKT[region]


def replicate(maps, rule, RF, to):
    """maps: [(key, pf), ...]（混合なら複数）。各地域で同じ規則。戻り: {'regions','positive','per_region',...}"""
    per = {}
    for reg in REGIONS:
        parts = [reg_series(reg, k, pf) for k, pf in maps]
        if any(p is None for p in parts):
            per[reg] = None
            continue
        ks = sorted(set.intersection(*[set(p) for p in parts]))
        r_ex = {k: S.mean([p[k] for p in parts]) for k in ks}
        m_ex = reg_mkt(reg)
        cost = 0.003 if reg == 'emerging' else COST
        L = static_L(r_ex, m_ex) if rule == 'static' else None
        if rule == 'static' and L is None:
            per[reg] = None
            continue
        # 地域の月の抜け（JKP の地域は連続のはず）を確かめる。抜けがあれば連続した最長の区間だけ
        kk = sorted(set(r_ex) & set(m_ex) & set(RF))
        if not contiguous({k: 1 for k in kk}):
            runs, cur = [], [kk[0]]
            for a, b in zip(kk, kk[1:]):
                if next_m(a) == b:
                    cur.append(b)
                else:
                    runs.append(cur); cur = [b]
            runs.append(cur)
            best = max(runs, key=len)
            r_ex = {k: r_ex[k] for k in best}
        g, n, info = lever(r_ex, m_ex, RF, rule, L_static=L, to=to, cost=cost)
        full = M.excess_stats(n, m_ex)
        hold = M.excess_stats(n, m_ex, a=M.HOLD_START)
        if full is None:
            per[reg] = None
            continue
        per[reg] = {'from': full['from'], 'to': full['to'], 'years': full['years'], 'L': round(L, 3) if L else info['L_mean'],
                    'net_ex_ann': full['ex_ann'], 't': full['t'], 'cagr_diff': full['cagr_diff'],
                    'positive': full['ex_ann'] > 0,
                    'hold_net_ex_ann': hold['ex_ann'] if hold else None, 'hold_t': hold['t'] if hold else None}
    got = [r for r in REGIONS if per.get(r)]
    pos = [r for r in got if per[r]['positive']]
    nonus = [r for r in NONUS if per.get(r)]
    return {'regions': len(got), 'positive': len(pos), 'nonus_regions': len(nonus),
            'nonus_positive': sum(1 for r in nonus if per[r]['positive']), 'per_region': per}


# ───────────────────────── 評価 ─────────────────────────
def evaluate(c, rule, MKT, MKTRF, RF, spread=SPREAD, cost=COST):
    r_ex = {k: v - RF[k] for k, v in c['r'].items() if k in RF}
    L = static_L(r_ex, MKTRF) if rule == 'static' else None
    g_ex, n_ex, info = lever(r_ex, MKTRF, RF, rule, L_static=L, to=c['to'], cost=cost, spread=spread)
    g, n = to_total(g_ex, RF), to_total(n_ex, RF)
    first = min(g)
    b = M.window(MKT, first)
    e = {'full': M.excess_stats(g, MKT), 'train': M.excess_stats(g, MKT, z=M.TRAIN_END),
         'hold': M.excess_stats(g, MKT, a=M.HOLD_START), 'recent': M.excess_stats(g, MKT, a=M.RECENT_START),
         'net_cost_full': M.excess_stats(n, MKT), 'net_cost_hold': M.excess_stats(n, MKT, a=M.HOLD_START)}
    e['roll20_net'] = M.rolling(n, MKT, 20)
    e['dca20_net'] = M.dca(n, MKT, 20)
    e['sharpe_pair'] = {'train': sharpe_same(n, MKT, RF, z=M.TRAIN_END), 'hold': sharpe_same(n, MKT, RF, a=M.HOLD_START)}
    e['L_static'] = round(L, 3) if L is not None else None
    e['lever_info'] = info
    ks = sorted(set(n) & set(b))
    e['maxdd'] = {'strategy': round(M.maxdd({k: n[k] for k in ks}) * 100, 1), 'mkt': round(M.maxdd({k: b[k] for k in ks}) * 100, 1)}
    if c.get('pub'):
        e['post_publication'] = M.excess_stats(g, MKT, a=(c['pub'] + 1) * 100 + 1)
    return e, g, n


def main():
    ff = M.ff_factors()
    MKT, MKTRF, RF = ff['mkt'], ff['mktrf'], ff['rf']
    sanity = {'french_mkt_cagr_full': round(M.cagr(MKT) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(MKT, M.HOLD_START)) * 100, 2),
              'french_mkt_range': [min(MKT), max(MKT)]}
    print('sanity', sanity)
    cands = load_candidates(RF)
    print('候補', len(cands))
    # 月の連続
    sanity['noncontiguous_candidates'] = [n for n, c in cands.items() if not contiguous(c['r'])]
    # JKP 三分位の順序（ぶれ）
    order = {}
    for k in ['beta_60m', 'betabab_1260d', 'rvol_21d', 'ivol_capm_252d']:
        vs = {pf: round(S.stdev([v for ym, v in cands[f'JKP_{k}[{pf[0]}]']['r'].items() if RANK_A <= ym <= RANK_Z]) * math.sqrt(12) * 100, 1)
              for pf in ('1.0', '2.0', '3.0')}
        order[k] = vs
    sanity['jkp_tercile_vol_order_train'] = order
    sanity['jkp_pf1_is_low'] = all(v['1.0'] < v['2.0'] < v['3.0'] for v in order.values())
    jm = M.jkp_mkt('usa', 'vw')
    ks = sorted(set(jm) & set(MKTRF))
    sanity['jkp_usa_vw_mkt_vs_french_mktrf_corr'] = round(M.corr([jm[k] for k in ks], [MKTRF[k] for k in ks]), 4)

    # 訓練のシャープ（順位づけ）
    ranking = {}
    for n, c in cands.items():
        c['train_sharpe'] = train_sharpe(c['r'], RF)
        ranking[n] = round(c['train_sharpe'], 4) if c['train_sharpe'] is not None else None
    mkt_train_sharpe = train_sharpe(MKT, RF)
    best = {}
    for n, c in cands.items():
        if c['train_sharpe'] is None:
            continue
        s = c['source']
        if s not in best or c['train_sharpe'] > cands[best[s]]['train_sharpe']:
            best[s] = n
    grp_of = {s: cands[n]['group'] for s, n in best.items()}
    lr = sorted([s for s in best if grp_of[s] == '低リスク'], key=lambda s: -cands[best[s]]['train_sharpe'])
    ql = sorted([s for s in best if grp_of[s] == '質'], key=lambda s: -cands[best[s]]['train_sharpe'])
    P_src = lr[:3] + ql[:3]
    X_src = [s for s in sorted(best, key=lambda s: -cands[best[s]]['train_sharpe']) if s not in P_src]
    print('P', [best[s] for s in P_src])
    # 混合
    parts = [cands[best[s]] for s in P_src]
    ks = sorted(set.intersection(*[set(p['r']) for p in parts]))
    blend = {'name': 'BLEND6[P]', 'kind': 'blend', 'source': 'BLEND6', 'col': '+'.join(best[s] for s in P_src), 'group': '混合',
             'pub': None, 'to': S.mean([p['to'] for p in parts]) + 0.1,
             'r': {k: S.mean([p['r'][k] for p in parts]) for k in ks}, 'maps': [p['map'] for p in parts],
             'desc': 'P の6本（低リスク3＋質3）の等分混合（毎月戻す）'}
    blend['train_sharpe'] = train_sharpe(blend['r'], RF)
    P_c = [cands[best[s]] for s in P_src] + [blend]
    X_c = [cands[best[s]] for s in X_src]

    tested = []

    def run(c, rule, fam, primary, spread=SPREAD, cost=COST, tag=''):
        e, g, n = evaluate(c, rule, MKT, MKTRF, RF, spread=spread, cost=cost)
        name = f"{fam}_{c['name']}_{rule}{tag}"
        rec = {'name': name, 'family': fam, 'primary': primary, 'rule': rule, 'candidate': c['name'], 'source': c['source'],
               'group': c['group'], 'description': f"{c['desc']} を {'訓練のぶれ比で固定倍率' if rule == 'static' else ('36か月のぶれ比で毎月倍率' if rule == 'dynamic' else '倍率1（借入なし）')}{tag}",
               'train_sharpe_unlevered_196307_200612': round(c['train_sharpe'], 3) if c.get('train_sharpe') else None,
               'turnover_ann': round(c['to'], 3), 'pub_year': c.get('pub')}
        rec.update(e)
        return rec

    fams = {'P': [], 'U': [], 'X1': [], 'XU': [], 'S': []}
    for c in P_c:
        for rule in ('static', 'dynamic'):
            fams['P'].append(run(c, rule, 'P', True))
        fams['U'].append(run(c, 'unlevered', 'U', False))
        for rule in ('static', 'dynamic'):
            fams['S'].append(run(c, rule, 'S', False, spread=0.02, tag='・借入RF+2%'))
            fams['S'].append(run(c, rule, 'S', False, cost=0.003, tag='・費用3倍'))
    for c in X_c:
        for rule in ('static', 'dynamic'):
            fams['X1'].append(run(c, rule, 'X1', False))
        fams['XU'].append(run(c, 'unlevered', 'XU', False))

    # C5
    print('C5 ...')
    rep_cache = {}
    for fam in ('P', 'U', 'X1', 'XU'):
        for rec in fams[fam]:
            c = blend if rec['candidate'] == blend['name'] else cands[rec['candidate']]
            maps = c['maps'] if c['kind'] == 'blend' else [c['map']]
            rule = 'unlevered' if rec['rule'] == 'unlevered' else rec['rule']
            key = (tuple(maps), rule)
            if key not in rep_cache:
                rep_cache[key] = replicate(maps, rule, RF, c['to'])
            rec['repl'] = rep_cache[key]
            rec['repl_map'] = [list(m) for m in maps]

    # Holm と判定
    for fam in ('P', 'U', 'X1', 'XU'):
        ps = {r['name']: (r['hold']['p'] if r['hold'] else None) for r in fams[fam]}
        hp = M.holm(ps)
        for r in fams[fam]:
            r['family_holm_p'] = hp.get(r['name'])
            lev = r['rule'] != 'unlevered'
            sp = r['sharpe_pair']
            g, crit = M.grade(r['full'], r['train'], r['hold'], r['roll20_net'], cost_hold=r['net_cost_hold'],
                              repl={'regions': r['repl']['regions'], 'positive': r['repl']['positive']} if r.get('repl') else None,
                              family_holm_p=r['family_holm_p'], sharpe_pair=sp if lev else None, leveraged_or_timing=lev)
            r['grade'], r['criteria'] = g, crit
    for r in fams['S']:
        r['grade'], r['criteria'] = None, None
        r['note'] = '報告のみ（判定しない）'

    # AQR BAB（参考）
    bab = None
    try:
        import openpyxl, io
        b = M.get('https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Betting-Against-Beta-Equity-Factors-Monthly.xlsx',
                  name='aqr_bab_monthly.xlsx', max_age_days=60)
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
        ws = wb['BAB Factors']
        rows = list(ws.iter_rows(values_only=True))
        hi = next(i for i, r in enumerate(rows) if r and r[0] == 'DATE')
        h = rows[hi]
        iu = h.index('USA')
        d = {}
        for r in rows[hi + 1:]:
            if r[0] is None or r[iu] is None:
                continue
            dt = r[0]
            ym = dt.year * 100 + dt.month if hasattr(dt, 'year') else int(str(dt)[:4]) * 100 + int(str(dt)[5:7])
            d[ym] = float(r[iu])
        z = {k: 0.0 for k in d}
        bab = {'full': M.excess_stats(d, z), 'train': M.excess_stats(d, z, z=M.TRAIN_END), 'hold': M.excess_stats(d, z, a=M.HOLD_START),
               'note': 'AQR の BAB（買い−売り・ゼロコスト・米国）。参考のみ・判定しない。ex_ann = BAB の平均（年率）'}
    except Exception as e:  # noqa
        bab = {'error': str(e)[:200]}

    # 静的倍率の検算: 訓練期間のぶれ
    chk = []
    for r in fams['P']:
        if r['rule'] == 'static' and r['train']:
            chk.append({'name': r['name'], 'L': r['L_static'], 'train_vol_s': r['train']['vol_s'], 'train_vol_b': r['train']['vol_b']})
    sanity['static_train_vol_check'] = chk
    sanity['mkt_train_sharpe_196307_200612'] = round(mkt_train_sharpe, 3)

    all_rec = [r for f in ('P', 'U', 'X1', 'XU', 'S') for r in fams[f]]
    out = {
        'angle': ANGLE, 'prereg': PREREG, 'prereg_commit': sha_of(f'out/{PREREG}'),
        'global_prereg': 'mw_prereg.json', 'global_prereg_commit': sha_of('out/mw_prereg.json'),
        'benchmark': 'French Mkt（Mkt-RF+RF・総リターン）。地域は JKP vw 市場（超過）',
        'sanity': sanity,
        'selection': {'ranking_window': [RANK_A, RANK_Z], 'n_candidates_ranked': sum(1 for v in ranking.values() if v is not None),
                      'n_candidates_total': len(ranking), 'train_sharpe_unlevered': ranking,
                      'source_best': {s: best[s] for s in best}, 'P_sources': P_src, 'X1_sources': X_src,
                      'low_risk_order': [(s, best[s], round(cands[best[s]]['train_sharpe'], 3)) for s in lr],
                      'quality_order': [(s, best[s], round(cands[best[s]]['train_sharpe'], 3)) for s in ql],
                      'blend_train_sharpe': round(blend['train_sharpe'], 3) if blend['train_sharpe'] else None},
        'aqr_bab_reference': bab,
        'deviations': [],
        'n_tested': len(all_rec), 'n_graded': sum(1 for r in all_rec if r['grade']),
        'grade_counts': {f: {g: sum(1 for r in fams[f] if r['grade'] == g) for g in 'SABC'} for f in ('P', 'U', 'X1', 'XU')},
        'tested': all_rec,
    }
    p = M.save('mw_risk_matched.json', out)
    print('saved', p, 'n_tested', len(all_rec))
    for f in ('P', 'U'):
        for r in fams[f]:
            h, hn, fu = r['hold'], r['net_cost_hold'], r['full']
            print(f"{r['name'][:60]:60s} {r['grade']} L={r['L_static'] or r['lever_info']['L_mean']} full {fu['ex_ann']:+.2f} t{fu['t']} | hold {h['ex_ann']:+.2f} t{h['t']} cagrΔ{h['cagr_diff']:+.2f} net {hn['ex_ann']:+.2f} | roll {r['roll20_net']['win_rate'] if r['roll20_net'] else None} | C5 {r['repl']['positive']}/{r['repl']['regions']} | SR {r['sharpe_pair']}")


if __name__ == '__main__':
    main()
