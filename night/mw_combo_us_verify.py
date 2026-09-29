#!/usr/bin/env python3
"""night/mw_combo_us_verify.py — 角度 combo_us の『反証の検証』（読むだけ・門の判定には不使用）

out/mw_combo_us.json が S / A と格付けした候補（と保有期間の超過が大きい B の上位2本）を、
**研究者のコードを使わずに**作り直して反証を試みる。
mw_common から借りるのは取得（french_tables / jkp_rows / yahoo）だけ。
ポートフォリオの組み立て・良い側の決め方・超過・CAGR・Newey-West t・転がる20年窓・積立・Holm・
費用・税・回帰・国の答え合わせは全部ここで自前に書く。

確かめること（候補ごと）
 1. 数字の再現（全期間・訓練・保有の超過と NW t・幾何の差・20年窓・費用後）
 2. 後知恵: 信号の時点／良い側を 2007年以降のデータで選んでいないか／**袖（どの特徴を混ぜるか）を
    2007年以降の成績を見た後に選んでいないか**（2026-09-26 の jkp_evidence → longonly の経緯）
 3. 相手が純粋な時価加重（French Mkt）か／超過と総リターンの取り違え／JKP の銘柄集合の差
 4. 小期間（1998-2000・2020-2021 を抜く／保有期間の前半・後半／2008-09 を抜く）
 5. 近いパラメータ（1袖抜き・重みづけ・開始年・規模の1段下）
 6. 業種の偏り（12業種）・規模の偏り（French BIG 行そのもの対 Mkt）
 7. 費用（自前の回転率の見積もり）と損益分岐・日本の課税口座の税（20.315%）
 8. 多重検定（角度の40本・mw 全体の本数）
 9. **正直な選び方の検定**: 2006年までのデータだけで JKP 153 特徴から袖を選んだら、保有期間に勝ったか
    （上位5本・t≥2 の全部・門の物差しの全部・ランダムな5本の分布の中で C6 はどこか）
結果 → out/mw_combo_us_verify.json
"""
import os, sys, json, math, random, statistics as st, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけ使う（french_tables / jkp_rows / yahoo）

BASE = M.BASE
TRAIN_END, HOLD_START, RECENT, HALF2 = 200612, 200701, 201307, 201607
TAX_JP = 0.20315


# ───────────────────────── 取得（読むだけ）→ 自前の整形 ─────────────────────────
def fr_table(name, want):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and want in t.lower():
            return v
    raise KeyError(f'{name}: {want}')


def fr_col(name, label):
    v = fr_table(name, 'value weight')
    i = v['cols'].index(label)
    return {d: r[i] / 100.0 for d, r in v['data'].items() if r[i] is not None}


def fr_row(name, labels):
    return [fr_col(name, lab) for lab in labels]


def _ff():
    v = next(v for t, v in M.french_tables('F-F_Research_Data_Factors').items() if v['freq'] == 'monthly')
    ia, ir = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
    mkt, rf, mrf = {}, {}, {}
    for d, r in v['data'].items():
        if r[ia] is not None and r[ir] is not None:
            mkt[d] = (r[ia] + r[ir]) / 100.0; rf[d] = r[ir] / 100.0; mrf[d] = r[ia] / 100.0
    return mkt, rf, mrf


MKT, RF, MKTRF = _ff()


def region_mkt(rg):
    v = next(v for t, v in M.french_tables(f'{rg}_3_Factors').items() if v['freq'] == 'monthly')
    ia, ir = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
    return {d: (r[ia] + r[ir]) / 100.0 for d, r in v['data'].items() if r[ia] is not None and r[ir] is not None}


def ym_of(s):
    return int(s[0:4]) * 100 + int(s[5:7])


_JALL = {}


def jkp_all(region, weighting='vw'):
    """JKP の all_factors 三分位 → {特徴: {'1.0'|'2.0'|'3.0': {ym: (超過, 社数)}}}"""
    k = (region, weighting)
    if k in _JALL:
        return _JALL[k]
    d = {}
    for x in M.jkp_rows(region, 'all_factors', 'portfolios', weighting):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x.get('n') not in (None, '', 'NA', 'na') else None
        d.setdefault(x['name'], {}).setdefault(x['pf'], {})[ym_of(x['date'])] = (float(x['ret']), n)
    _JALL[k] = d
    return d


def jkp_one(region, key, weighting):
    d = {}
    for x in M.jkp_rows(region, key, 'portfolios', weighting):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x.get('n') not in (None, '', 'NA', 'na') else None
        d.setdefault(x['pf'], {})[ym_of(x['date'])] = (float(x['ret']), n)
    return d


def jkp_mkt(region, weighting='vw'):
    return {ym_of(x['date']): float(x['ret']) for x in M.jkp_rows(region, 'mkt', 'factor', weighting) if x['ret'] not in ('', 'NA', 'na')}


_DIR = None


def jkp_direction():
    """JKP の予言の向き（文献の符号・成績ではない）。+1 なら第3分位（高い側）が良い側"""
    global _DIR
    if _DIR is None:
        _DIR = {}
        for x in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
            if x['direction'] not in ('', 'na', 'NA'):
                _DIR[x['name']] = int(float(x['direction']))
    return _DIR


def jkp_factor_all(region='usa'):
    f = {}
    for x in M.jkp_rows(region, 'all_factors', 'factor', 'vw'):
        if x['ret'] not in ('', 'NA', 'na'):
            f.setdefault(x['name'], {})[ym_of(x['date'])] = float(x['ret'])
    return f


def good(key):
    return '3.0' if jkp_direction()[key] > 0 else '1.0'


def bad(key):
    return '1.0' if jkp_direction()[key] > 0 else '3.0'


# ───────────────────────── 自前の統計 ─────────────────────────
def mean(x):
    return math.fsum(x) / len(x)


def nw_t(x, lag=12):
    n = len(x)
    if n < 24:
        return None
    m = mean(x)
    e = [v - m for v in x]
    lrv = math.fsum(v * v for v in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        w = 1.0 - L / (lag + 1.0)
        lrv += 2.0 * w * math.fsum(e[i] * e[i - L] for i in range(L, n)) / n
    return m / math.sqrt(lrv / n) if lrv > 0 else None


def p2(t):
    return math.erfc(abs(t) / math.sqrt(2.0)) if t is not None else None


def geo_ann(v):
    return math.exp(12.0 * math.fsum(math.log1p(x) for x in v) / len(v)) - 1.0


def comp(s, b, a=None, z=None, drop=None, lag=12):
    """s・b とも総リターン。差の算術平均（年率%）・NW t・両側 p・幾何の年率差（%）・月数"""
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not (drop and drop(k)))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nw_t(ex, lag)
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    vb = st.pvariance(bv)
    ms, mb = mean(sv), mean(bv)
    beta = math.fsum((x - ms) * (y - mb) for x, y in zip(sv, bv)) / len(ks) / vb if vb else None
    return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'ex': round(mean(ex) * 1200, 2),
            't': round(t, 2) if t is not None else None, 'p': round(p2(t), 4) if t is not None else None,
            'cagr_diff': round((geo_ann(sv) - geo_ann(bv)) * 100, 2), 'te': round(st.stdev(ex) * math.sqrt(12) * 100, 2),
            'beta': round(beta, 3) if beta is not None else None}


def roll20(s, b):
    ks = set(s) & set(b)
    if not ks:
        return None
    y0, y1 = min(ks) // 100, max(ks) // 100
    out = []
    for y in range(y0, y1 + 1):
        w = [(y + (m - 1 + 6) // 12) * 100 + (m - 1 + 6) % 12 + 1 for m in range(1, 241)]  # y07 .. (y+20)06
        if not all(k in ks for k in w):
            continue
        out.append((y, round((geo_ann([s[k] for k in w]) - geo_ann([b[k] for k in w])) * 100, 2)))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 0) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda z: z[1])}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    out = []
    for i, k0 in enumerate(ks):
        if k0 % 100 != 7 or i + 240 > len(ks):
            continue
        w = ks[i:i + 240]
        if (w[-1] // 100 - w[0] // 100) * 12 + (w[-1] % 100 - w[0] % 100) != 239:
            continue  # 月が飛んでいる窓は数えない
        vs = vb = 0.0
        for k in w:
            vs = (vs + 1.0) * (1.0 + s[k]); vb = (vb + 1.0) * (1.0 + b[k])
        out.append((k0 // 100, round(vs / vb, 3)))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(out, key=lambda z: z[1])}


def holm(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m, run, out = len(it), 0.0, {}
    for i, (v, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 4)
    return out


def net(s, turnover, unit):
    c = turnover * unit / 12.0
    return {k: v - c for k, v in s.items()}


def mixeq(series):
    ks = set(series[0])
    for x in series[1:]:
        ks &= set(x)
    return {k: math.fsum(x[k] for x in series) / len(series) for k in sorted(ks)}


def since(s, a):
    return {k: v for k, v in s.items() if k >= a}


def total(ex):
    return {k: v + RF[k] for k, v in ex.items() if k in RF}


def after_tax_cagr(r, turnover, a, z=None):
    """日本の課税口座（20.315%）: 毎月 turnover/12 を売って買い直し、実現益に課税（損失は繰り越し）。最後に全部売る"""
    ks = sorted(k for k in r if k >= a and (z is None or k <= z))
    V = B = 1.0
    loss = 0.0
    f = turnover / 12.0
    for k in ks:
        V *= 1.0 + r[k]
        g = f * (V - B)
        T = 0.0
        if g > 0:
            use = min(loss, g); loss -= use; T = TAX_JP * (g - use)
        else:
            loss += -g
        B = B * (1.0 - f) + f * V - T
        V -= T
    g = V - B
    if g > 0:
        g = max(0.0, g - loss)
        V -= TAX_JP * g
    return V ** (12.0 / len(ks)) - 1.0


def ols_alpha(y, X, lag=12):
    """y = a + X b。α（年率%）と、α+残差の系列の NW t（β を固定とみなす近似）"""
    import numpy as np
    Y = np.array(y); Z = np.column_stack([np.ones(len(y))] + [np.array(c) for c in X])
    b, *_ = np.linalg.lstsq(Z, Y, rcond=None)
    e = Y - Z @ b
    t = nw_t(list(b[0] + e), lag)
    r2 = 1 - float(e @ e) / float(((Y - Y.mean()) @ (Y - Y.mean())))
    return {'alpha': round(float(b[0]) * 1200, 2), 't_nw': round(t, 2) if t is not None else None, 'r2': round(r2, 3), 'betas': [round(float(x), 3) for x in b[1:]]}


_IND = None


def industries12():
    global _IND
    if _IND is None:
        v = fr_table('12_Industry_Portfolios', 'value weight')
        _IND = {c: {d: r[i] / 100.0 for d, r in v['data'].items() if r[i] is not None} for i, c in enumerate(v['cols'])}
    return _IND


def industry_adj(s, a=None, z=None):
    ind = industries12()
    cols = [c for c in ind if c != 'Other']
    ks = sorted(k for k in s if k in MKT and all(k in ind[c] for c in cols) and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 60:
        return None
    y = [s[k] - MKT[k] for k in ks]
    X = [[ind[c][k] - MKT[k] for k in ks] for c in cols]
    o = ols_alpha(y, X)
    o['tilts'] = dict(zip(cols, o.pop('betas')))
    # 業種の傾きが説明した分（β×その期間の業種の超過の平均）
    o['explained_by_tilts'] = round(sum(o['tilts'][c] * mean(X[i]) for i, c in enumerate(cols)) * 1200, 2)
    o['raw_ex'] = round(mean(y) * 1200, 2)
    return o


_FF6 = None


def ff6():
    global _FF6
    if _FF6 is None:
        o = {}
        for name, cols in (('F-F_Research_Data_5_Factors_2x3', ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA']), ('F-F_Momentum_Factor', ['Mom'])):
            v = next(v for t, v in M.french_tables(name).items() if v['freq'] == 'monthly')
            for c in cols:
                i = v['cols'].index(c)
                o[c] = {d: r[i] / 100.0 for d, r in v['data'].items() if r[i] is not None}
        _FF6 = o
    return _FF6


def factor_adj(s, a=None, z=None):
    F = ff6()
    names = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom']
    ks = sorted(k for k in s if k in MKT and all(k in F[n] for n in names) and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 60:
        return None
    o = ols_alpha([s[k] - MKT[k] for k in ks], [[F[n][k] for k in ks] for n in names])
    o['loadings'] = dict(zip(names, o.pop('betas')))
    return o


# ───────────────────────── 候補の組み立て（自前） ─────────────────────────
Q5 = ['ope_be', 'gp_at', 'qmj', 'chcsho_12m', 'oaccruals_at']
JKP_SPECS = {
    'C6_QUAL5': (Q5, 2015, True), 'E3_PROF3': (['gp_at', 'ope_be', 'cop_at'], 2016, False),
    'E7_QUAL8': (Q5 + ['cop_at', 'at_gr1', 'noa_at'], 2016, False), 'E1_QUAL5_MOM': (Q5 + ['ret_12_1'], 2015, False),
    'E2_QUAL5_VAL': (Q5 + ['be_me'], 2015, False), 'C2_QMJ_MOM': (['qmj', 'ret_12_1'], 2013, True),
    'C3_GP_MOM': (['gp_at', 'ret_12_1'], 2013, True), 'C5_QMJ_ISS_MOM': (['qmj', 'chcsho_12m', 'ret_12_1'], 2013, True),
    'E5_QUAL5_LOWRISK': (Q5 + ['betabab_1260d', 'ivol_capm_252d'], 2015, False),
}
# 自前の回転率の見積もり（片道・年）。研究者の表を写さず、三分位（広い箱）の文献の目安から保守側に置く。
MY_TO = {'ope_be': 0.6, 'gp_at': 0.5, 'cop_at': 0.5, 'oaccruals_at': 1.2, 'qmj': 0.8, 'chcsho_12m': 1.0, 'at_gr1': 0.9,
         'noa_at': 0.6, 'be_me': 0.6, 'ret_12_1': 3.0, 'betabab_1260d': 0.6, 'ivol_capm_252d': 1.5}
JKP_UNIT = 0.002  # 片道100%あたり（全規模の時価加重三分位）

FR_BIG = {  # French 規模の最上位5分位（BIG）の行
    'op': ('25_Portfolios_ME_OP_5x5', 'BIG HiOP', 'ME4 OP5', 0.6), 'ac': ('25_Portfolios_ME_AC_5x5', 'BIG LoAC', 'ME4 AC1', 0.6),
    'ni': ('25_Portfolios_ME_NI_5x5', 'BIG NegNI', 'ME4 NegNI', 0.8), 'inv': ('25_Portfolios_ME_INV_5x5', 'BIG LoINV', 'ME4 INV1', 0.6),
    'bm': ('25_Portfolios_5x5', 'BIG HiBM', 'ME4 BM5', 0.6), 'mom': ('25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'ME4 PRIOR5', 4.5),
}
FR_SPECS = {
    'D5_BIG_QUAL4_VAL_MOM': (['op', 'ac', 'ni', 'inv', 'bm', 'mom'], 196307, 2015, False),
    'D4_BIG_QUAL4_VAL': (['op', 'ac', 'ni', 'inv', 'bm'], 196307, 2015, False),
    'D2_BIG_QUAL4': (['op', 'ac', 'ni', 'inv'], 196307, 2015, False),
    'B8_BIG_HiPRIOR': (['mom'], None, 1993, True),
    'B9_MIX_BIG_VAL_MOM': (['bm', 'mom'], None, 2013, True),
    'B11_MIX_BIG_4SIG': (['op', 'inv', 'bm', 'mom'], 196307, 2015, True),
}
FR_UNIT = 0.001
REG_SUF = {'op': ('ME_OP', 'BIG HiOP'), 'inv': ('ME_INV', 'BIG LoINV'), 'bm': ('ME_BE-ME', 'BIG HiBM'), 'mom': ('ME_Prior_12_2', 'BIG HiPRIOR')}
REG3 = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']
JKP7 = ['jpn', 'gbr', 'fra', 'deu', 'che', 'can', 'aus']


def jkp_mix_region(region, keys, weighting='vw', min_n=0, side=None, start=196307):
    A = jkp_all(region, 'vw') if weighting == 'vw' else None
    ser = []
    for k in keys:
        d = (A[k] if A is not None else jkp_one(region, k, weighting))
        sd = (side or good)(k)
        if sd not in d:
            return {}
        ser.append({ym: r for ym, (r, n) in d[sd].items() if n is None or n >= min_n})
    m = mixeq(ser)
    return since(m, start) if start else m


def build_all():
    C = {}
    for sid, (keys, pub, primary) in JKP_SPECS.items():
        ex = jkp_mix_region('usa', keys)
        C[sid] = {'kind': 'jkp', 'keys': keys, 'pub': pub, 'primary': primary, 's': total(ex), 'ex_rf': ex,
                  'to': round(mean([MY_TO[k] for k in keys]) + 0.1, 3), 'unit': JKP_UNIT}
    for sid, (sl, start, pub, primary) in FR_SPECS.items():
        ss = [fr_col(FR_BIG[g][0], FR_BIG[g][1]) for g in sl]
        m = mixeq(ss) if len(ss) > 1 else dict(ss[0])
        if start:
            m = since(m, start)
        to = mean([FR_BIG[g][3] for g in sl]) + (0.1 if len(sl) > 1 else 0.0)
        C[sid] = {'kind': 'french', 'sleeves': sl, 'pub': pub, 'primary': primary, 's': m, 'to': round(to, 3), 'unit': FR_UNIT, 'start': start}
    b2 = since(fr_col('25_Portfolios_OP_INV_5x5', 'HiOP LoINV'), 196307)
    C['B2_HiOP_LoINV'] = {'kind': 'french_all', 'pub': 2015, 'primary': True, 's': b2, 'to': 1.0, 'unit': 0.002}
    return C


# ───────────────────────── 判定（全体の線をそのまま自前で当てる） ─────────────────────────
def my_grade(full, train, hold, r20, cost_hold, repl, holm_p):
    c = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0),
         'C2': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4': bool(r20 and r20['win_rate'] >= 0.8),
         'C5': (repl['positive'] / repl['counted'] >= 2 / 3) if repl and repl.get('counted') else None,
         'C6': bool(cost_hold and cost_hold['ex'] > 0 and cost_hold['cagr_diff'] > 0),
         'C7': bool((full and (full['t'] or 0) >= 3.0) or (holm_p is not None and holm_p < 0.05))}
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── 国の答え合わせ（自前） ─────────────────────────
def repl_jkp(keys, since_ym=None):
    det, pos, cnt, hpos, hcnt = {}, 0, 0, 0, 0
    for c in JKP7:
        try:
            sx = jkp_mix_region(c, keys, min_n=10, start=None)
            mk = jkp_mkt(c, 'vw')
        except Exception as e:  # noqa
            det[c] = {'error': str(e)[:120]}
            continue
        common = sorted(set(sx) & set(mk))
        f = comp(sx, mk) if len(common) >= 120 else None
        h = comp(sx, mk, a=since_ym or HOLD_START) if sum(1 for k in common if k >= (since_ym or HOLD_START)) >= 60 else None
        det[c] = {'months': len(common), 'full_ex': f and f['ex'], 'full_t': f and f['t'], 'post_ex': h and h['ex'], 'post_t': h and h['t']}
        if f:
            cnt += 1; pos += f['ex'] > 0
        if h:
            hcnt += 1; hpos += h['ex'] > 0
    return {'counted': cnt, 'positive': pos, 'post_counted': hcnt, 'post_positive': hpos, 'post_from': since_ym or HOLD_START, 'detail': det}


def repl_french(sleeves, since_ym=None):
    det, pos, cnt, hpos, hcnt = {}, 0, 0, 0, 0
    for rg in REG3:
        ss = [fr_col(f'{rg}_25_Portfolios_{REG_SUF[g][0]}', REG_SUF[g][1]) for g in sleeves]
        sx = mixeq(ss) if len(ss) > 1 else dict(ss[0])
        mk = region_mkt(rg)
        f = comp(sx, mk)
        h = comp(sx, mk, a=since_ym or HOLD_START)
        det[rg] = {'full_ex': f and f['ex'], 'full_t': f and f['t'], 'post_ex': h and h['ex'], 'post_t': h and h['t']}
        if f:
            cnt += 1; pos += f['ex'] > 0
        if h:
            hcnt += 1; hpos += h['ex'] > 0
    return {'counted': cnt, 'positive': pos, 'post_counted': hcnt, 'post_positive': hpos, 'post_from': since_ym or HOLD_START, 'detail': det}


# ───────────────────────── 候補ごとの検証 ─────────────────────────
DROP_9800_2021 = lambda k: 199801 <= k <= 200012 or 202001 <= k <= 202112
DROP_0809 = lambda k: 200801 <= k <= 200912
DROP_2022 = lambda k: 202201 <= k <= 202212


def verify_one(sid, c):
    s = c['s']
    o = {'from': min(s), 'to': max(s), 'turnover_assumed': c['to'], 'unit_cost': c['unit']}
    o['full'] = comp(s, MKT)
    o['train'] = comp(s, MKT, z=TRAIN_END)
    o['hold'] = comp(s, MKT, a=HOLD_START)
    o['recent'] = comp(s, MKT, a=RECENT)
    o['post_pub'] = comp(s, MKT, a=(c['pub'] + 1) * 100 + 1)
    o['post_pub_from'] = (c['pub'] + 1) * 100 + 1
    o['hold_half1'] = comp(s, MKT, a=HOLD_START, z=HALF2 - 1 if HALF2 % 100 != 1 else HALF2 - 89)
    o['hold_half2'] = comp(s, MKT, a=HALF2)
    o['drop_1998_2000_2020_2021'] = {'full': comp(s, MKT, drop=DROP_9800_2021), 'train': comp(s, MKT, z=TRAIN_END, drop=DROP_9800_2021),
                                     'hold': comp(s, MKT, a=HOLD_START, drop=DROP_9800_2021)}
    o['hold_drop_2008_2009'] = comp(s, MKT, a=HOLD_START, drop=DROP_0809)
    o['hold_drop_2022'] = comp(s, MKT, a=HOLD_START, drop=DROP_2022)
    o['roll20'] = roll20(s, MKT)
    o['dca20'] = dca20(s, MKT)
    o['cost_hold'] = comp(net(s, c['to'], c['unit']), MKT, a=HOLD_START)
    o['cost_hold_3x'] = comp(net(s, c['to'], c['unit'] * 3), MKT, a=HOLD_START)
    h = o['hold']
    o['breakeven_unit_cost_pct_per_100pct_turnover'] = round(h['ex'] / c['to'], 2) if h and c['to'] else None
    o['after_tax_JP_taxable_hold'] = {
        'strategy_cagr': round(after_tax_cagr(net(s, c['to'], c['unit']), c['to'], HOLD_START) * 100, 2),
        'market_buyhold_cagr': round(after_tax_cagr(MKT, 0.0, HOLD_START, max(s)) * 100, 2)}
    o['after_tax_JP_taxable_hold']['diff'] = round(o['after_tax_JP_taxable_hold']['strategy_cagr'] - o['after_tax_JP_taxable_hold']['market_buyhold_cagr'], 2)
    o['industry12_hold'] = industry_adj(s, a=HOLD_START)
    o['industry12_train'] = industry_adj(s, z=TRAIN_END)
    o['ff6_hold'] = factor_adj(s, a=HOLD_START)
    # 年ごとの超過（保有期間）＝どの年に頼っているか
    yrs = {}
    for k in sorted(s):
        if k >= HOLD_START and k in MKT:
            a = yrs.setdefault(k // 100, [1.0, 1.0, 0]); a[0] *= 1 + s[k]; a[1] *= 1 + MKT[k]; a[2] += 1
    ye = {y: round((a - b) * 100, 2) for y, (a, b, n) in yrs.items() if n == 12}
    o['hold_calendar_excess'] = ye
    o['hold_years_positive'] = f"{sum(1 for v in ye.values() if v > 0)}/{len(ye)}"
    top2 = sorted(ye.items(), key=lambda z: -z[1])[:2]
    o['hold_top2_years'] = top2
    o['hold_drop_top2_years'] = comp(s, MKT, a=HOLD_START, drop=lambda k: k // 100 in [y for y, _ in top2])
    return o


def neighbors_jkp(sid, c):
    keys = c['keys']
    o = {}
    if len(keys) > 2:
        o['leave_one_out_hold'] = {}
        for k in keys:
            t = total(jkp_mix_region('usa', [x for x in keys if x != k]))
            h = comp(t, MKT, a=HOLD_START)
            o['leave_one_out_hold']['without_' + k] = {'ex': h['ex'], 't': h['t'], 'train_t': comp(t, MKT, z=TRAIN_END)['t']}
    o['sleeves'] = {}
    for k in keys:
        d = jkp_all('usa')[k]
        sl = {}
        for side, lab in ((good(k), 'good'), ('2.0', 'mid'), (bad(k), 'bad')):
            t = total(since({ym: r for ym, (r, n) in d[side].items()}, 196307))
            sl[lab] = {'train': (comp(t, MKT, z=TRAIN_END) or {}).get('ex'), 'train_t': (comp(t, MKT, z=TRAIN_END) or {}).get('t'),
                       'hold': (comp(t, MKT, a=HOLD_START) or {}).get('ex'), 'hold_t': (comp(t, MKT, a=HOLD_START) or {}).get('t')}
        o['sleeves'][k] = sl
    o['start_1972'] = {'train': comp(c['s'], MKT, a=197201, z=TRAIN_END), 'full': comp(c['s'], MKT, a=197201)}
    # 重みづけ（上限つき・等加重）を同じ重みの JKP 市場と
    o['weighting'] = {}
    for w in ('vw_cap', 'ew'):
        try:
            sx = jkp_mix_region('usa', keys, weighting=w)
            mk = jkp_mkt('usa', w)
            o['weighting'][w] = {'vs_same_w_jkp_mkt_train': comp(sx, mk, z=TRAIN_END), 'vs_same_w_jkp_mkt_hold': comp(sx, mk, a=HOLD_START),
                                 'vs_french_mkt_hold': comp(total(sx), MKT, a=HOLD_START)}
        except Exception as e:  # noqa
            o['weighting'][w] = {'error': str(e)[:160]}
    o['vs_jkp_vw_mkt_hold'] = comp(c['ex_rf'], jkp_mkt('usa', 'vw'), a=HOLD_START)
    return o


def neighbors_french(sid, c):
    sl = c['sleeves']
    o = {}
    ss4 = [fr_col(FR_BIG[g][0], FR_BIG[g][2]) for g in sl]
    m4 = mixeq(ss4) if len(ss4) > 1 else dict(ss4[0])
    if c.get('start'):
        m4 = since(m4, c['start'])
    o['ME4_row_same_rule'] = {'train': comp(m4, MKT, z=TRAIN_END), 'hold': comp(m4, MKT, a=HOLD_START), 'full': comp(m4, MKT)}
    # BIG 行そのもの（規模の最上位5分位を社数×平均時価総額で合成）＝規模の賭けの分
    name = '25_Portfolios_ME_OP_5x5'
    v = fr_table(name, 'value weight'); nf = fr_table(name, 'number of firms'); sz = fr_table(name, 'average market cap')
    idx = [v['cols'].index(l) for l in ['BIG LoOP', 'ME5 OP2', 'ME5 OP3', 'ME5 OP4', 'BIG HiOP']]
    big = {}
    ks = sorted(v['data'])
    for p, k in zip(ks, ks[1:]):
        ws = [(nf['data'][p][i] or 0) * (sz['data'][p][i] or 0) for i in idx]
        rs = [v['data'][k][i] for i in idx]
        if sum(ws) > 0 and all(r is not None for r in rs):
            big[k] = sum(w * r for w, r in zip(ws, rs)) / sum(ws) / 100.0
    o['BIG_quintile_vs_mkt'] = {'train': comp(big, MKT, z=TRAIN_END), 'hold': comp(big, MKT, a=HOLD_START)}
    o['vs_BIG_quintile'] = {'train': comp(c['s'], big, z=TRAIN_END), 'hold': comp(c['s'], big, a=HOLD_START), 'full': comp(c['s'], big)}
    if len(sl) > 2:
        o['leave_one_out_hold'] = {}
        for g in sl:
            ss = [fr_col(FR_BIG[x][0], FR_BIG[x][1]) for x in sl if x != g]
            m = mixeq(ss)
            if c.get('start'):
                m = since(m, c['start'])
            h = comp(m, MKT, a=HOLD_START)
            o['leave_one_out_hold']['without_' + g] = {'ex': h['ex'], 't': h['t']}
    o['sleeves_hold'] = {g: (lambda h: {'ex': h['ex'], 't': h['t']})(comp(fr_col(FR_BIG[g][0], FR_BIG[g][1]), MKT, a=HOLD_START)) for g in sl}
    return o


# ───────────────────────── 正直な選び方の検定（2006年までのデータだけで袖を選ぶ） ─────────────────────────
GATE15 = ['eqnpo_me', 'gp_at', 'ope_be', 'ebit_sale', 'qmj', 'qmj_prof', 'qmj_growth', 'qmj_safety', 'z_score',
          'earnings_variability', 'at_gr1', 'netdebt_me', 'debt_gr3', 'chcsho_12m', 'oaccruals_at']


def honest_selection(c6_hold_ex):
    A = jkp_all('usa')
    D = jkp_direction()
    rows = {}
    for k in sorted(A):
        if k not in D or good(k) not in A[k] or bad(k) not in A[k]:
            continue
        g = total(since({ym: r for ym, (r, n) in A[k][good(k)].items()}, 196307))
        b = total(since({ym: r for ym, (r, n) in A[k][bad(k)].items()}, 196307))
        tr = comp(g, MKT, z=TRAIN_END)
        if tr is None or tr['months'] < 360:
            continue
        ls_tr = comp(g, b, z=TRAIN_END)
        rows[k] = {'g': g, 'train_lo_ex': tr['ex'], 'train_lo_t': tr['t'], 'train_ls_t': ls_tr['t'],
                   'hold_lo': comp(g, MKT, a=HOLD_START)}
    names = sorted(rows)

    def hold_of(ks):
        m = mixeq([rows[k]['g'] for k in ks])
        h = comp(m, MKT, a=HOLD_START)
        tr = comp(m, MKT, z=TRAIN_END)
        return {'n_sleeves': len(ks), 'sleeves': ks, 'train_ex': tr['ex'], 'train_t': tr['t'], 'hold_ex': h['ex'], 'hold_t': h['t'],
                'hold_cagr_diff': h['cagr_diff']}
    by_lo = sorted(names, key=lambda k: -(rows[k]['train_lo_t'] or -9))
    by_ls = sorted(names, key=lambda k: -(rows[k]['train_ls_t'] or -9))
    out = {'universe': len(names), 'note': '良い側は JKP の文献上の向き（成績ではない）。順位と選別は 1963-07〜2006-12 だけで決め、2007〜 を答え合わせに使う'}
    out['rank_of_C6_sleeves_by_train_longonly_t'] = {k: by_lo.index(k) + 1 for k in Q5 if k in rows}
    out['rank_of_C6_sleeves_by_train_longshort_t'] = {k: by_ls.index(k) + 1 for k in Q5 if k in rows}
    out['C6_sleeves_train_longonly_t'] = {k: rows[k]['train_lo_t'] for k in Q5 if k in rows}
    for n in (3, 5, 10):
        out[f'H1_top{n}_by_train_longonly_t'] = hold_of(by_lo[:n])
        out[f'H1b_top{n}_by_train_longshort_t'] = hold_of(by_ls[:n])
    pool = [k for k in names if (rows[k]['train_lo_t'] or 0) >= 2.0]
    out['H2_all_train_longonly_t_ge_2'] = hold_of(pool)
    pool_ls = [k for k in names if (rows[k]['train_ls_t'] or 0) >= 2.0]
    out['H2b_all_train_longshort_t_ge_2'] = hold_of(pool_ls)
    g15 = [k for k in GATE15 if k in rows]
    out['H3_gate_proxies_all15'] = hold_of(g15)
    g15p = [k for k in g15 if (rows[k]['train_ls_t'] or 0) >= 2.0]
    out['H3b_gate_proxies_train_longshort_t_ge_2'] = hold_of(g15p)
    out['H4_all_153_equal'] = hold_of(names)
    # ランダムな5本（2006年までに long-only t≥2 だった袖から）
    rnd = random.Random(20260928)
    draws = []
    for _ in range(4000):
        ks = rnd.sample(pool, 5)
        m = mixeq([rows[k]['g'] for k in ks])
        h = comp(m, MKT, a=HOLD_START)
        draws.append((h['ex'], h['t']))
    ex = sorted(d[0] for d in draws)
    out['H5_random5_from_trainpool'] = {
        'pool_size': len(pool), 'draws': len(draws), 'hold_ex_median': ex[len(ex) // 2], 'hold_ex_p90': ex[int(len(ex) * 0.9)],
        'hold_ex_p10': ex[int(len(ex) * 0.1)], 'share_hold_ex_pos': round(sum(1 for e in ex if e > 0) / len(ex), 3),
        'share_hold_t_ge_1_65': round(sum(1 for d in draws if (d[1] or 0) >= 1.65) / len(draws), 3),
        'C6_hold_ex': c6_hold_ex, 'C6_percentile': round(sum(1 for e in ex if e < c6_hold_ex) / len(ex), 3),
        'C6_sleeves_in_pool': [k for k in Q5 if k in pool]}
    rnd2 = random.Random(7)
    draws2 = []
    for _ in range(4000):
        ks = rnd2.sample(names, 5)
        m = mixeq([rows[k]['g'] for k in ks])
        draws2.append(comp(m, MKT, a=HOLD_START)['ex'])
    draws2.sort()
    out['H6_random5_from_all'] = {'draws': len(draws2), 'hold_ex_median': draws2[len(draws2) // 2], 'hold_ex_p90': draws2[int(len(draws2) * 0.9)],
                                  'C6_percentile': round(sum(1 for e in draws2 if e < c6_hold_ex) / len(draws2), 3)}
    # 単独の袖で保有期間の成績が最も良かった側（後知恵の上限）
    hl = sorted(((rows[k]['hold_lo']['ex'], k) for k in names), reverse=True)
    out['posthoc_best_single_sleeves_hold'] = hl[:10]
    out['C6_sleeves_hold_rank_among_153'] = {k: [x[1] for x in hl].index(k) + 1 for k in Q5}
    return out


# ───────────────────────── 検算 ─────────────────────────
def sanity():
    o = {}
    jm = jkp_mkt('usa', 'vw')
    ks = sorted(set(jm) & set(MKTRF))
    for lag in (-1, 0, 1):
        pairs = [(jm[ks[i]], MKTRF[ks[i + lag]]) for i in range(max(0, -lag), len(ks) - max(0, lag))]
        a = [x for x, _ in pairs]; b = [y for _, y in pairs]
        ma, mb = mean(a), mean(b)
        cr = math.fsum((x - ma) * (y - mb) for x, y in pairs) / math.sqrt(math.fsum((x - ma) ** 2 for x in a) * math.fsum((y - mb) ** 2 for y in b))
        o[f'corr_jkp_mkt_vs_french_mktrf_lag{lag}'] = round(cr, 4)
    o['jkp_vw_mkt_plus_frenchRF_vs_french_mkt_full'] = comp(total(jm), MKT)
    o['jkp_vw_mkt_plus_frenchRF_vs_french_mkt_hold'] = comp(total(jm), MKT, a=HOLD_START)
    # 良い側: JKP の向き と (第3−第1)×符号つき因子の相関（2006まで）が一致するか（153本すべて）
    A, F = jkp_all('usa'), jkp_factor_all('usa')
    agree = dis = 0
    bad_list = []
    for k, d in A.items():
        if k not in F or '3.0' not in d or '1.0' not in d:
            continue
        ms = sorted(m for m in set(d['3.0']) & set(d['1.0']) & set(F[k]) if m <= TRAIN_END)
        if len(ms) < 60:
            continue
        x = [d['3.0'][m][0] - d['1.0'][m][0] for m in ms]; y = [F[k][m] for m in ms]
        mx, my = mean(x), mean(y)
        cr = math.fsum((a - mx) * (b - my) for a, b in zip(x, y))
        if (cr > 0) == (jkp_direction()[k] > 0):
            agree += 1
        else:
            dis += 1; bad_list.append(k)
    o['good_side_direction_vs_corr_upto2006'] = {'agree': agree, 'disagree': dis, 'disagree_list': bad_list}
    o['french_mkt_cagr_full'] = round(geo_ann(list(MKT.values())) * 100, 2)
    o['french_mkt_cagr_hold'] = round(geo_ann([v for k, v in MKT.items() if k >= HOLD_START]) * 100, 2)
    # 研究者の良い側と一致するか
    try:
        R = json.load(open(os.path.join(BASE, 'out', 'mw_combo_us.json')))
        rs = R['sanity']['good_sides_upto_2006']
        o['good_side_matches_researcher'] = {k: (rs[k] == good(k)) for k in rs}
    except Exception as e:  # noqa
        o['good_side_matches_researcher'] = str(e)[:100]
    return o


def etf_reality(c6):
    out = {}
    for t in ['QUAL', 'SPHQ', 'JQUA', 'MOAT', 'DGRW', 'VIG', 'QUS', 'FQAL', 'USMV']:
        try:
            r = {k: v for k, v in M.yahoo(t, '1mo').items() if k in MKT}
        except Exception as e:  # noqa
            out[t] = {'error': str(e)[:100]}
            continue
        ks = sorted(set(r) & set(c6))
        if len(ks) < 36:
            out[t] = {'error': 'short'}
            continue
        e = comp({k: r[k] for k in ks}, MKT)
        c = comp({k: c6[k] for k in ks}, MKT)
        out[t] = {'from': ks[0], 'to': ks[-1], 'etf_ex': e['ex'], 'etf_t': e['t'], 'etf_cagr_diff': e['cagr_diff'], 'C6_ex_same_months': c['ex'], 'C6_t_same_months': c['t']}
    return out


def main():
    R = json.load(open(os.path.join(BASE, 'out', 'mw_combo_us.json')))
    rr = {r['id']: r for r in R['tested']}
    C = build_all()
    res = {'target': 'out/mw_combo_us.json', 'target_commit': subprocess.run(['git', 'log', '-n1', '--format=%h', '--', 'out/mw_combo_us.json'], cwd=BASE, capture_output=True, text=True).stdout.strip(),
           'benchmark': 'French Mkt（Mkt-RF+RF）＝上限なしの時価加重・CRSP 全上場',
           'independence': 'mw_common からは取得（french_tables / jkp_rows / yahoo）だけを使用。良い側は JKP の direction 欄（文献の向き）で決め、研究者の相関の方法とは別。統計・窓・積立・Holm・費用・税・回帰は自前',
           'sanity': sanity(), 'candidates': {}}
    print('sanity', json.dumps(res['sanity'], ensure_ascii=False)[:900])
    for sid, c in C.items():
        v = verify_one(sid, c)
        if c['kind'] == 'jkp':
            v['neighbors'] = neighbors_jkp(sid, c)
            v['repl_full'] = repl_jkp(c['keys'])
            v['repl_postpub'] = repl_jkp(c['keys'], since_ym=(c['pub'] + 1) * 100 + 1)
        elif c['kind'] == 'french':
            v['neighbors'] = neighbors_french(sid, c)
            if all(g in REG_SUF for g in c['sleeves']):
                v['repl_full'] = repl_french(c['sleeves'])
                v['repl_postpub'] = repl_french(c['sleeves'], since_ym=max(HOLD_START, (c['pub'] + 1) * 100 + 1))
            else:
                v['repl_full'] = None
        else:
            v['repl_full'] = None
        r0 = rr.get(sid, {})
        v['researcher'] = {'grade': r0.get('grade'), 'full': (r0.get('full') or {}).get('ex_ann'), 'full_t': (r0.get('full') or {}).get('t'),
                           'train': (r0.get('train') or {}).get('ex_ann'), 'train_t': (r0.get('train') or {}).get('t'),
                           'hold': (r0.get('hold') or {}).get('ex_ann'), 'hold_t': (r0.get('hold') or {}).get('t'),
                           'hold_cagr_diff': (r0.get('hold') or {}).get('cagr_diff'), 'net_hold': (r0.get('cost_hold') or {}).get('ex_ann'),
                           'roll20': (r0.get('roll20') or {}).get('win_rate'), 'holm_p_hold': r0.get('holm_p_hold'), 'family': r0.get('family'),
                           'turnover': r0.get('turnover_oneway_per_year')}
        f, h = v['full'], v['hold']
        v['reproduced_match'] = bool(abs(f['ex'] - (v['researcher']['full'] or 0)) <= 0.1 and abs(h['ex'] - (v['researcher']['hold'] or 0)) <= 0.1
                                     and abs(h['t'] - (v['researcher']['hold_t'] or 0)) <= 0.1)
        res['candidates'][sid] = v
        print(f"{sid:22s} full {f['ex']:5.2f} t{f['t']:5.2f} | train {v['train']['ex']:5.2f} t{v['train']['t']:5.2f} | hold {h['ex']:5.2f} t{h['t']:5.2f} cd{h['cagr_diff']:5.2f}"
              f" | net {v['cost_hold']['ex']:5.2f} | r20 {v['roll20']['win_rate']} | H1 {v['hold_half1']['ex']:5.2f}/{v['hold_half1']['t']} H2 {v['hold_half2']['ex']:5.2f}/{v['hold_half2']['t']}"
              f" | pub+ {v['post_pub']['ex']}/{v['post_pub']['t']} | tax {v['after_tax_JP_taxable_hold']['diff']} | match {v['reproduced_match']}")
    # 多重検定: 角度の40本（再現した本は自前の p、残りは研究者の p）
    allp = {r['id']: (r.get('hold') or {}).get('p') for r in R['tested']}
    for sid, v in res['candidates'].items():
        allp[sid] = v['hold']['p']
    hp40 = holm(allp)
    fams = {}
    for r in R['tested']:
        fams.setdefault(r['family'], []).append(r['id'])
    fam_holm = {}
    for fam, ids in fams.items():
        fam_holm.update(holm({i: allp[i] for i in ids}))
    n_prog = 0
    import glob
    for fp in glob.glob(os.path.join(BASE, 'out', 'mw_*.json')):
        if 'prereg' in fp or 'verify' in fp:
            continue
        try:
            d = json.load(open(fp))
            n_prog += len(d.get('tested') or [])
        except Exception:  # noqa
            pass
    res['multiplicity'] = {'angle_n': len(allp), 'holm_hold_angle40': {k: hp40[k] for k in res['candidates']},
                           'holm_hold_family': {k: fam_holm.get(k) for k in res['candidates']},
                           'mw_program_tests_so_far': n_prog,
                           'bonferroni_t_needed_program': round(abs(__import__('statistics').NormalDist().inv_cdf(0.025 / max(n_prog, 1))), 2),
                           'bonferroni_t_needed_angle40': round(abs(__import__('statistics').NormalDist().inv_cdf(0.025 / 40)), 2)}
    for sid, v in res['candidates'].items():
        g, cr = my_grade(v['full'], v['train'], v['hold'], v['roll20'], v['cost_hold'], v.get('repl_full'), res['multiplicity']['holm_hold_family'][sid])
        v['my_mechanical_grade'], v['my_criteria'] = g, cr
        # C7 を『角度の40本での Holm』だけで判定した場合（全期間 t≥3 の抜け道を使わない＝訓練期間は文献の発見の標本なので）
        v['grade_if_C7_only_via_holm_angle40'] = my_grade(dict(v['full'], t=0), v['train'], v['hold'], v['roll20'], v['cost_hold'],
                                                          v.get('repl_full'), res['multiplicity']['holm_hold_angle40'][sid])[0]
        print(sid, 'mech', g, cr, '| C7 only by angle Holm ->', v['grade_if_C7_only_via_holm_angle40'])
    res['honest_selection'] = honest_selection(res['candidates']['C6_QUAL5']['hold']['ex'])
    print('honest', json.dumps({k: v for k, v in res['honest_selection'].items() if k.startswith('H') or k.startswith('rank') or k.startswith('C6')}, ensure_ascii=False)[:3000])
    res['etf_reality'] = etf_reality(C['C6_QUAL5']['s'])
    print('etf', json.dumps(res['etf_reality'], ensure_ascii=False)[:1200])
    for sid, v in res['candidates'].items():
        v.pop('s', None)
    res['leak_timeline'] = {
        'c7db797_2026-09-26T09:20': 'jkp_evidence: JKP 153因子の 2007〜 の成績（vw_cap の買い−売り）を米国・日本・世界で計算。'
                                    '『門の側で頑丈だったもの: GP/A・営業利益÷自己資本・質・株数を増やさない・発生主義』と、報われなかった物差し（営業利益率・財務の安全・利益の安定）を名指し',
        '636082e_2026-09-26T09:27': 'longonly 事前登録: 上の5本（ope_be・gp_at・qmj・chcsho_12m・oaccruals_at）をまさに選んだ（7分後）',
        'bdbd4ab_2026-09-26T09:29': '訂正: vw_cap 市場は純粋な時価加重に 2007〜 年1.38% 負けていた（＝vw で作れば +1.8 前後になると分かっていた）',
        '5520d51_2026-09-28T12:14': 'combo_us 事前登録: C6_QUAL5 に同じ5本を vw で登録（prereg 本文も『2026-09-26 の longonly と同じ顔ぶれ』と明記）',
        'reading': 'C6 の袖の選び方は保有期間（2007〜2025）の成績を見た後。保有期間は C6 にとって答え合わせではない。'
                   'さらに GP/A（2013・1963-2010 のデータ）・FF5 の OP（2015・〜2013）・QMJ（2013/2019・〜2012）の発見に使われた標本は 2007〜2013 を含む'}
    res['verdicts'] = verdicts(res)
    res['summary_ja'] = SUMMARY_JA
    M.save('mw_combo_us_verify.json', res)
    for v in res['verdicts']:
        print(v['name'], v['claimed_grade'], '->', v['verdict'], '|', v['key_numbers'])
    return res


# ───────────────────────── 判定（反証の結論） ─────────────────────────
# 判定の規則（数字を見る前に決めた既定）: 数字が再現し、全体の線の機械判定を保ったうえで、
# (a) 袖の選び方が保有期間を見た後なら、保有期間の t と C7 は『答え合わせ』として数えない
# (b) C7 は『角度の40本の Holm』で見る（全期間 t≥3 は訓練期間＝文献の発見の標本を含むので抜け道にしない）
# (c) 保有期間の勝ちが2年を抜くと消える・後半/公表後に負け・近い作り方で消える → さらに一段下げる
# 迷ったら疑う側に倒す。
VERDICT = {
    'C6_QUAL5': ('downgraded to B', 'B', ['袖の選び方が保有期間を見た後（leak_timeline）', '正直な選び方では保有期間の超過が0前後（honest_selection）',
                                          'C7 は全期間 t≥3 の抜け道だけ・族 Holm 0.067・40本 Holm 0.36', '上限つき/等加重に替えると French Mkt に対して消える',
                                          '同じ月の実在の質ETFは全部負け']),
    'E3_PROF3': ('downgraded to B', 'B', ['探索（C6 と『収益性は 2007〜 も効いた』を知った後）', '開始を1972にすると訓練 t<2（C1 が崩れる）',
                                          '公表後（2017〜）の7か国は 2/7 しか正でない＝米国だけの勝ち', '40本 Holm 0.128']),
    'E7_QUAL8': ('downgraded to B', 'B', ['探索（C6 を見た後）', '40本 Holm 0.26', '上限つきにすると French Mkt に +0.4 t0.4', '業種調整で半分以下']),
    'E1_QUAL5_MOM': ('downgraded to B', 'B', ['探索', '公表後 t1.4・前半 t1.4', '費用3倍で t0.8', '日本の課税口座では市場に負け']),
    'E2_QUAL5_VAL': ('downgraded to B', 'B', ['探索', '保有期間の正の年は 10/19', '上位2年を抜くと t1.7', '日本の課税口座では市場に負け']),
    'D5_BIG_QUAL4_VAL_MOM': ('downgraded to B', 'B', ['探索（C6 を見た後）', '同じ規則を規模の1段下（ME4）に当てると保有期間 ±0',
                                                      '保有期間の前半は +0.5 t0.8＝後半（2022/2025）頼み', 'C5 は N/A（米国外の答え合わせなし）']),
    'D4_BIG_QUAL4_VAL': ('downgraded to B', 'B', ['探索', 'ME4 に当てると保有期間 ±0', '前半 +0.4 t0.6・上位2年（2025/2021）を抜くと t1.3', 'C5 は N/A']),
    'B8_BIG_HiPRIOR': ('downgraded to B', 'B', ['保有期間 t0.4＝ほぼ0', '2007 と 2024 を抜くと負け', '損益分岐の単価 0.17%・費用3倍で負け',
                                                '日本の課税口座では年 −1.1%', 'A は訓練期間（勢いの発見の標本）と 1990-2006 中心の地域の全期間に乗っているだけ']),
    'B9_MIX_BIG_VAL_MOM': ('downgraded to B', 'B', ['保有期間 t1.0・前半は負け', 'ME4 では保有期間 −1.1', '20年窓 94%・積立 89%']),
    'B11_MIX_BIG_4SIG': ('downgraded to B', 'B', ['保有期間 t1.4・前半 +0.4', 'ME4 では保有期間 −0.6', '2022 を抜くと t0.8']),
    'C2_QMJ_MOM': ('downgraded to B', 'B', ['保有期間 t0.6・上位2年を抜くと負け', '費用3倍で負け・課税口座で −0.9', '業種調整後 α −0.2']),
    'C3_GP_MOM': ('downgraded to B', 'B', ['保有期間 t1.1・上位2年（2007/2020）を抜くと +0.3', '費用3倍で負け・課税口座で −0.4', '業種調整後 α −0.1']),
    'C5_QMJ_ISS_MOM': ('downgraded to B', 'B', ['保有期間 t0.7', 'qmj を抜くと保有期間 −0.1', '費用3倍で負け・課税口座で −0.8']),
    'E5_QUAL5_LOWRISK': ('downgraded to B', 'B', ['探索', '保有期間 t1.4・後半 t0.7・公表後 +0.4', '上位2年を抜くと t0.5']),
    'D2_BIG_QUAL4': ('confirmed', 'B', ['探索（B のまま）', '保有期間の前半・後半とも +1.1〜1.3 で揃う', 'LoAC の袖を抜くと t0.7']),
    'B2_HiOP_LoINV': ('downgraded to C', 'C', ['保有期間の勝ちは 2009（+23%）と 2010（+22%）の2年だけ・抜くと +0.4 t0.2',
                                               '後半（2016-07〜）−1.7・公表後（2016〜）−1.0・2013-07〜 −0.4', '全規模＝小型株の反発頼み']),
}
CLAIMED = ['C6_QUAL5', 'E3_PROF3', 'E7_QUAL8', 'E1_QUAL5_MOM', 'E2_QUAL5_VAL', 'D5_BIG_QUAL4_VAL_MOM', 'D4_BIG_QUAL4_VAL', 'B8_BIG_HiPRIOR']


def verdicts(res):
    out = []
    H = res['honest_selection']
    for sid, (vd, g, notes) in VERDICT.items():
        v = res['candidates'][sid]
        f, tr, h, c = v['full'], v['train'], v['hold'], v['cost_hold']
        k = (f"全期間 {f['ex']:+.2f}%/年 t{f['t']} ／ 訓練 {tr['ex']:+.2f} t{tr['t']} ／ 保有 {h['ex']:+.2f} t{h['t']}（幾何 {h['cagr_diff']:+.2f}）"
             f" ／ 費用後 {c['ex']:+.2f}（回転{v['turnover_assumed']}×{v['unit_cost']*100:.1f}%） ／ 20年窓 {v['roll20']['win_rate']:.3f}"
             f" ／ 前半 {v['hold_half1']['ex']:+.2f} t{v['hold_half1']['t']}・後半 {v['hold_half2']['ex']:+.2f} t{v['hold_half2']['t']}"
             f" ／ 上位2年{[y for y, _ in v['hold_top2_years']]}抜き {v['hold_drop_top2_years']['ex']:+.2f} t{v['hold_drop_top2_years']['t']}"
             f" ／ 課税口座 {v['after_tax_JP_taxable_hold']['diff']:+.2f} ／ 12業種α {v['industry12_hold']['alpha']:+.2f} t{v['industry12_hold']['t_nw']}"
             f" ／ Holm 族 {res['multiplicity']['holm_hold_family'][sid]}・40本 {res['multiplicity']['holm_hold_angle40'][sid]}")
        iss = list(notes)
        if sid == 'C6_QUAL5':
            iss.append(f"正直な選び方（2006年までの t 上位5本）の保有期間 {H['H1_top5_by_train_longonly_t']['hold_ex']:+.2f} t{H['H1_top5_by_train_longonly_t']['hold_t']}"
                       f"・t≥2 の全{H['H2_all_train_longonly_t_ge_2']['n_sleeves']}本 {H['H2_all_train_longonly_t_ge_2']['hold_ex']:+.2f}"
                       f"・ランダム5本の中で C6 は {H['H5_random5_from_trainpool']['C6_percentile']*100:.1f} パーセンタイル")
            iss.append(f"C6 の袖の訓練期間の単独 t（対市場）: {H['C6_sleeves_train_longonly_t']}（gp_at・qmj は 2006 までは t<2）")
            iss.append(f"弁護側の証拠: 1998-2000/2020-21 を抜いても保有 {v['drop_1998_2000_2020_2021']['hold']['ex']:+.2f} t{v['drop_1998_2000_2020_2021']['hold']['t']}・"
                       f"2016〜 {v['post_pub']['ex']:+.2f} t{v['post_pub']['t']}・7か国の保有期間 {v['repl_full']['post_positive']}/{v['repl_full']['post_counted']} 正（2016〜は "
                       f"{v['repl_postpub']['post_positive']}/{v['repl_postpub']['post_counted']}）・成績を見ずに決めた門の物差し15本の混合でも保有 "
                       f"{H['H3_gate_proxies_all15']['hold_ex']:+.2f} t{H['H3_gate_proxies_all15']['hold_t']}＝本物の上乗せは C6 の半分程度と読むのが妥当")
            w = v['neighbors']['weighting']
            iss.append(f"上限つき vw_cap は French Mkt に保有 {w['vw_cap']['vs_french_mkt_hold']['ex']:+.2f} t{w['vw_cap']['vs_french_mkt_hold']['t']}・"
                       f"等加重 {w['ew']['vs_french_mkt_hold']['ex']:+.2f}＝勝ちは最大級の会社を満額で持つ時だけ")
            e = res['etf_reality']
            iss.append('実在ETF（同じ月の C6）: ' + '・'.join(f"{t} {e[t]['etf_ex']:+.2f}（C6 {e[t]['C6_ex_same_months']:+.2f}）" for t in ('QUAL', 'SPHQ', 'VIG', 'MOAT', 'JQUA') if 'etf_ex' in e.get(t, {})))
        out.append({'name': sid, 'claimed_grade': v['researcher']['grade'], 'in_claimed_list': sid in CLAIMED, 'mechanical_grade_reproduced': v['my_mechanical_grade'],
                    'verdict': vd, 'verified_grade': g, 'reproduced': v['reproduced_match'], 'key_numbers': k, 'issues': iss})
    return out


SUMMARY_JA = ('研究者の数字は16本すべて自前のコードで再現した（C6 全期間 +1.62 t4.94・保有 +1.60 t2.59）。機械の格付け（S7本・A7本）も線どおりには再現する。\n'
              'だが C6 の5つの袖は 2026-09-26 に 2007〜2025 の成績を見た後で選ばれており、保有期間は C6 の答え合わせになっていない。\n'
              '2006年までのデータだけで JKP 153 特徴から袖を選ぶと保有期間の超過は −0.3〜+0.1%/年で、C6 はランダムな5本の混合の上位0.7%にいる＝選び方の結果。\n'
              'C7 は全期間 t≥3（訓練＝文献の発見の標本）でしか通らず、角度の40本の Holm では全候補が不合格。上限つき・等加重・規模の1段下にすると保有期間の勝ちは消え、実在の質ETFは同じ月に全部負けた。\n'
              '判定: S/A の14本はすべて B へ（保有期間の符号と費用後の正は残る）、D2 は B のまま、B2 は2009-10年頼みで C。\n'
              '弁護側: 成績を見ずに決めた門の物差し15本の混合でも保有期間 +0.8%/年 t2.1・12業種調整後の C6 α +0.8 t3.3・7か国の保有期間 7/7 正＝質の上乗せは本物でも C6 の半分程度（年+0.8%前後）と読むのが妥当。')


if __name__ == '__main__':
    main()
