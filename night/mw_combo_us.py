#!/usr/bin/env python3
"""night/mw_combo_us.py — 『市場に勝てる歴史検証』の角度 combo_us（読むだけ・門の判定には不使用）

米国・買いだけの『複数の特徴を組み合わせた』ポートフォリオ（French の三重/二重ソートの角・JKP 三分位の良い側の混合）を
上限なしの時価加重市場（French Mkt）と比べる。規則と線は out/mw_combo_us_prereg.json（測る前にコミット）と
out/mw_prereg.json（全体の線）。結果 → out/mw_combo_us.json。

約束（mw_common と同じ）: 月次の小数・キーは yyyymm。欠測は None のまま＝混合は全部の袖に値がある月だけ（0で埋めない）。
French のポートフォリオは総リターン → French Mkt（Mkt-RF+RF）と比べる。JKP は米国 T-bill を引いた超過 → French RF を足して総リターンに。
"""
import os, sys, json, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
PREREG = 'out/mw_combo_us_prereg.json'
OUT = 'mw_combo_us.json'

FF = M.ff_factors()
MKT, RF, MKTRF = FF['mkt'], FF['rf'], FF['mktrf']


def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-n1', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── French の読み込み ─────────────────────────
_FR = {}


def fr(name):
    """→ {'cols': [...], 'ret': [ {ym: 小数} ×列 ], 'n': [...] or None, 'size': [...] or None}"""
    if name in _FR:
        return _FR[name]
    T = M.french_tables(name)
    pick = lambda f: next((v for t, v in T.items() if f(t.lower()) and v['freq'] == 'monthly'), None)
    vw = pick(lambda t: 'value weight' in t)
    nf = pick(lambda t: 'number of firms' in t)
    sz = pick(lambda t: 'average market cap' in t or 'average firm size' in t)
    if vw is None:
        raise KeyError(f'{name}: 時価加重の月次表が無い {list(T)}')
    cols = vw['cols']

    def cols_of(tab, scale):
        if tab is None:
            return None
        out = [dict() for _ in cols]
        for d, row in tab['data'].items():
            for i, x in enumerate(row[:len(cols)]):
                if x is not None:
                    out[i][d] = x / scale
        return out
    r = {'cols': cols, 'ret': cols_of(vw, 100), 'n': cols_of(nf, 1), 'size': cols_of(sz, 1)}
    _FR[name] = r
    return r


def col_index(name, label):
    c = fr(name)['cols']
    if label in c:
        return c.index(label)
    raise KeyError(f'{name}: 列「{label}」が無い {c}')


def pf(name, idx):
    return dict(fr(name)['ret'][idx])


def prev_ym(ym):
    y, m = divmod(ym, 100)
    return (y - 1) * 100 + 12 if m == 1 else ym - 1


def capw(name, idxs):
    """複数のポートフォリオを前月の（社数×平均時価総額）で時価加重合成。当月の値は使わない。
    どれか一つでも当月のリターンか前月の重みが欠ければ、その月は出さない（0で埋めない）"""
    t = fr(name)
    if t['n'] is None or t['size'] is None:
        raise KeyError(f'{name}: 社数か平均時価総額の表が無い')
    months = sorted(set.intersection(*[set(t['ret'][i]) for i in idxs]))
    out, skipped = {}, 0
    for ym in months:
        p = prev_ym(ym)
        ws = []
        for i in idxs:
            n, s = t['n'][i].get(p), t['size'][i].get(p)
            if n is None or s is None or n <= 0 or s <= 0:
                ws = None
                break
            ws.append(n * s)
        if ws is None:
            skipped += 1
            continue
        tot = sum(ws)
        out[ym] = sum(w * t['ret'][i][ym] for w, i in zip(ws, idxs)) / tot
    return out, skipped


def capw0(name, idxs):
    """capw と同じだが、前月の社数が0の箱は重み0（空の箱＝測った0。欠測ではない）。
    社数>0 なのに当月のリターンか前月の平均時価総額が欠ける月は出さない"""
    t = fr(name)
    months = sorted(set.union(*[set(t['ret'][i]) for i in idxs]))
    out, skipped = {}, 0
    for ym in months:
        p = prev_ym(ym)
        num = den = 0.0
        bad = False
        for i in idxs:
            n = t['n'][i].get(p)
            if n is None:
                bad = True; break
            if n <= 0:
                continue
            s_, r = t['size'][i].get(p), t['ret'][i].get(ym)
            if s_ is None or s_ <= 0 or r is None:
                bad = True; break
            num += n * s_ * r; den += n * s_
        if bad or den <= 0:
            skipped += 1
            continue
        out[ym] = num / den
    return out, skipped


def mix(series):
    """等分の混合（毎月組み直し）。全部の袖に値がある月だけ"""
    ks = sorted(set.intersection(*[set(s) for s in series]))
    return {k: sum(s[k] for s in series) / len(series) for k in ks}


def since(s, a):
    return {k: v for k, v in s.items() if k >= a}


def region_mkt(region):
    name = 'Emerging_5_Factors' if region == 'Emerging' else f'{region}_3_Factors'
    T = M.french_tables(name)
    v = next(v for t, v in T.items() if v['freq'] == 'monthly')
    ci = {c: i for i, c in enumerate(v['cols'])}
    out = {}
    for d, row in v['data'].items():
        a, b = row[ci['Mkt-RF']], row[ci['RF']]
        if a is not None and b is not None:
            out[d] = (a + b) / 100
    return out


# ───────────────────────── JKP ─────────────────────────
_JK = {}


def jkp_pf_n(region, key):
    """JKP 三分位（vw）→ {pf: {ym: (ret超過, 社数)}}"""
    k = (region, key)
    if k in _JK:
        return _JK[k]
    d = {}
    for x in M.jkp_rows(region, key, 'portfolios', 'vw'):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x.get('n') not in (None, '', 'NA') else None
        d.setdefault(x['pf'], {})[M._ym(x['date'])] = (float(x['ret']), n)
    _JK[k] = d
    return d


_SIDE = {}


def good_side(key):
    if key not in _SIDE:
        s, _ = M.jkp_good_side('usa', key, 'vw', upto=M.TRAIN_END)
        if s is None:
            raise RuntimeError(f'{key}: 2006-12 までで良い側が決まらない')
        _SIDE[key] = s
    return _SIDE[key]


def jkp_mix(region, keys, min_n=0, start=None):
    """良い側（米国の 2006-12 までで決めた側）の等分混合（超過）。各袖が min_n 社以上そろった月だけ"""
    series = []
    for key in keys:
        d = jkp_pf_n(region, key).get(good_side(key), {})
        series.append({ym: r for ym, (r, n) in d.items() if (n is None and min_n == 0) or (n is not None and n >= min_n)})
    m = mix(series)
    return since(m, start) if start else m


def to_total(excess):
    return {k: v + RF[k] for k, v in excess.items() if k in RF}


# ───────────────────────── 評価 ─────────────────────────
def pack(s, b, turnover, unit_cost, pubyear=None):
    full = M.excess_stats(s, b)
    net = M.apply_cost(s, turnover, unit_cost)
    ks = sorted(set(s) & set(b))
    o = {
        'full': full,
        'train': M.excess_stats(s, b, z=M.TRAIN_END),
        'hold': M.excess_stats(s, b, a=M.HOLD_START),
        'recent': M.excess_stats(s, b, a=M.RECENT_START),
        'post_pub': M.excess_stats(s, b, a=(pubyear + 1) * 100 + 1) if pubyear else None,
        'post_pub_from': (pubyear + 1) * 100 + 1 if pubyear else None,
        'cost_hold': M.excess_stats(net, b, a=M.HOLD_START),
        'cost_full': M.excess_stats(net, b),
        'stress3x_hold': M.excess_stats(M.apply_cost(s, turnover, unit_cost * 3), b, a=M.HOLD_START),
        'roll20': M.rolling(s, b, 20),
        'dca20': M.dca(s, b, 20),
        'maxdd_s': round(M.maxdd({k: s[k] for k in ks}) * 100, 1) if ks else None,
        'maxdd_b': round(M.maxdd({k: b[k] for k in ks}) * 100, 1) if ks else None,
    }
    return o


def repl_block(pairs, min_months=24):
    """pairs: {地域: (s, b)} → 各地域の全期間・保有期間の超過と、正の地域の数（min_months か月以上そろった地域だけ数える）"""
    det, pos, n = {}, 0, 0
    for rg, (s, b) in pairs.items():
        f = M.excess_stats(s, b)
        h = M.excess_stats(s, b, a=M.HOLD_START)
        nm = len(set(s) & set(b))
        det[rg] = {'full': f, 'hold': h, 'months': nm, 'counted': bool(f is not None and nm >= min_months)}
        if f is not None and nm >= min_months:
            n += 1
            pos += 1 if f['ex_ann'] > 0 else 0
    return {'regions': n, 'positive': pos, 'detail': det}


REG3 = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']
JKP7 = ['jpn', 'gbr', 'fra', 'deu', 'che', 'can', 'aus']

# 2x4x4 の位置: 規模(0=SMALL,1=BIG)*16 + 第1特徴の4分位*4 + 第2特徴の4分位（0=Lo..3=Hi）
ix3 = lambda a, b: 16 + a * 4 + b
# 5x5 の位置: 行*5 + 列（0=Lo..4=Hi）
ix5 = lambda r, c: r * 5 + c

F_BMOP, F_BMINV, F_OPINV = '32_Portfolios_ME_BEME_OP_2x4x4', '32_Portfolios_ME_BEME_INV_2x4x4', '32_Portfolios_ME_OP_INV_2x4x4'
R_BMOP = '{}_32_Portfolios_ME_BE-ME_OP_2x4x4'


def fam_A():
    S63 = 196307
    L = {}
    a1 = pf(F_OPINV, ix3(3, 0)); a2 = pf(F_BMOP, ix3(3, 3)); a3 = pf(F_BMOP, ix3(0, 3)); a4 = pf(F_BMINV, ix3(3, 0))
    a6, k6 = capw(F_OPINV, [ix3(o, i) for o in (2, 3) for i in (0, 1)])
    a7, k7 = capw(F_BMOP, [ix3(bm, o) for bm in (2, 3) for o in (2, 3)])
    a8, k8 = capw(F_BMINV, [ix3(bm, i) for bm in (2, 3) for i in (0, 1)])

    def rg_bmop(idxs, rg):
        name = R_BMOP.format(rg)
        if len(idxs) == 1:
            return pf(name, idxs[0])
        return capw(name, idxs)[0]

    def rg_pairs(idxs):
        return {rg: (rg_bmop(idxs, rg), region_mkt(rg)) for rg in REG3}

    def ref_pairs(idxs, emerg_label=None):
        d = {'Developed_ex_US': (rg_bmop(idxs, 'Developed_ex_US'), region_mkt('Developed_ex_US'))}
        if emerg_label:
            d['Emerging(2x2全規模)'] = (pf('Emerging_Markets_4_Portfolios_BE-ME_OP', col_index('Emerging_Markets_4_Portfolios_BE-ME_OP', emerg_label)), region_mkt('Emerging'))
        return d

    def proxy(rows):  # rows: [(file_suffix, label)]
        d = {}
        for rg in REG3 + ['Developed_ex_US']:
            ss = [pf(f'{rg}_25_Portfolios_{suf}', col_index(f'{rg}_25_Portfolios_{suf}', lab)) for suf, lab in rows]
            d[rg] = (mix(ss), region_mkt(rg))
        return d

    L['A1_BIG_HiOP_LoINV'] = dict(s=a1, to=0.8, uc=0.001, pub=2015, repl=None,
                                  repl_proxy=proxy([('ME_OP', 'BIG HiOP'), ('ME_INV', 'BIG LoINV')]),
                                  desc='大型×営業利益率 最上位4分位×投資 最下位4分位（FF 2x4x4）')
    L['A2_BIG_HiBM_HiOP'] = dict(s=a2, to=0.8, uc=0.001, pub=2013, repl=rg_pairs([ix3(3, 3)]), repl_ref=ref_pairs([ix3(3, 3)], 'HiBM_HiOP'),
                                 desc='大型×割安 最上位×営業利益率 最上位（profitable value）')
    L['A3_BIG_LoBM_HiOP'] = dict(s=a3, to=0.8, uc=0.001, pub=2013, repl=rg_pairs([ix3(0, 3)]), repl_ref=ref_pairs([ix3(0, 3)], 'LoBM_HiOP'),
                                 desc='大型×割高(成長) 最上位×営業利益率 最上位（quality growth・理論上あいまいな対照）')
    L['A4_BIG_HiBM_LoINV'] = dict(s=a4, to=0.8, uc=0.001, pub=2015, repl=None,
                                  repl_proxy=proxy([('ME_BE-ME', 'BIG HiBM'), ('ME_INV', 'BIG LoINV')]),
                                  desc='大型×割安 最上位×投資 最下位')
    L['A5_MIX_A1A2A4'] = dict(s=mix([a1, a2, a4]), to=0.9, uc=0.001, pub=2015, repl=None, desc='A1・A2・A4 を1/3ずつ（毎月組み直し）')
    L['A6_BIG_OPtop2_INVbot2'] = dict(s=a6, to=0.5, uc=0.001, pub=2015, repl=None, skipped=k6, desc='大型×OP 上位2分位×INV 下位2分位（4つを前月の時価で合成）')
    L['A7_BIG_BMtop2_OPtop2'] = dict(s=a7, to=0.5, uc=0.001, pub=2013, skipped=k7,
                                     repl=rg_pairs([ix3(bm, o) for bm in (2, 3) for o in (2, 3)]),
                                     repl_ref=ref_pairs([ix3(bm, o) for bm in (2, 3) for o in (2, 3)]),
                                     desc='大型×BM 上位2×OP 上位2（4つを前月の時価で合成）')
    L['A8_BIG_BMtop2_INVbot2'] = dict(s=a8, to=0.5, uc=0.001, pub=2015, repl=None, skipped=k8, desc='大型×BM 上位2×INV 下位2（4つを前月の時価で合成）')
    for v in L.values():
        v['s'] = since(v['s'], S63)
    return L


def fam_B():
    L = {}
    b1 = pf('25_Portfolios_BEME_OP_5x5', ix5(4, 4)); b2 = pf('25_Portfolios_OP_INV_5x5', ix5(4, 0))
    b3 = pf('25_Portfolios_BEME_INV_5x5', ix5(4, 0)); b4 = pf('25_Portfolios_BEME_OP_5x5', ix5(0, 4))
    b5 = pf('25_Portfolios_ME_OP_5x5', ix5(4, 4)); b6 = pf('25_Portfolios_ME_INV_5x5', ix5(4, 0))
    b7 = pf('25_Portfolios_5x5', ix5(4, 4)); b8 = pf('25_Portfolios_ME_Prior_12_2', ix5(4, 4))
    # 地域の同じ角（25 の ME×特徴）
    RG = {'op': ('ME_OP', 'BIG HiOP'), 'inv': ('ME_INV', 'BIG LoINV'), 'bm': ('ME_BE-ME', 'BIG HiBM'), 'mom': ('ME_Prior_12_2', 'BIG HiPRIOR')}
    EM = {'op': ('Emerging_Markets_6_Portfolios_ME_OP', 'BIG HiOP'), 'inv': ('Emerging_Markets_6_Portfolios_ME_INV', 'BIG LoINV'),
          'bm': ('Emerging_Markets_6_Portfolios_ME_BE-ME', 'BIG HiBM'), 'mom': ('Emerging_Markets_6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR')}

    def rgs(sig, rg):
        suf, lab = RG[sig]
        name = f'{rg}_25_Portfolios_{suf}'
        return pf(name, col_index(name, lab))

    def em(sig):
        name, lab = EM[sig]
        return pf(name, col_index(name, lab))

    def pairs(sigs):
        return {rg: (mix([rgs(g, rg) for g in sigs]), region_mkt(rg)) for rg in REG3}

    def refs(sigs):
        return {'Developed_ex_US': (mix([rgs(g, 'Developed_ex_US') for g in sigs]), region_mkt('Developed_ex_US')),
                'Emerging(2x3・上位30%)': (mix([em(g) for g in sigs]), region_mkt('Emerging'))}

    def em4(name, lab):
        return {'Emerging(2x2全規模)': (pf(name, col_index(name, lab)), region_mkt('Emerging'))}

    L['B1_HiBM_HiOP'] = dict(s=since(b1, 196307), to=0.8, uc=0.002, pub=2013, repl=None, repl_ref=em4('Emerging_Markets_4_Portfolios_BE-ME_OP', 'HiBM_HiOP'), desc='全規模 5x5 BM×OP の HiBM HiOP')
    L['B2_HiOP_LoINV'] = dict(s=since(b2, 196307), to=0.8, uc=0.002, pub=2015, repl=None, repl_ref=em4('Emerging_Markets_4_Portfolios_OP_INV', 'HiOP_LoINV'), desc='全規模 5x5 OP×INV の HiOP LoINV')
    L['B3_HiBM_LoINV'] = dict(s=since(b3, 196307), to=0.8, uc=0.002, pub=2015, repl=None, repl_ref=em4('Emerging_Markets_4_Portfolios_BE-ME_INV', 'HiBM_LoINV'), desc='全規模 5x5 BM×INV の HiBM LoINV')
    L['B4_LoBM_HiOP'] = dict(s=since(b4, 196307), to=0.8, uc=0.002, pub=2013, repl=None, repl_ref=em4('Emerging_Markets_4_Portfolios_BE-ME_OP', 'LoBM_HiOP'), desc='全規模 5x5 BM×OP の LoBM HiOP（quality growth・対照）')
    L['B5_BIG_HiOP'] = dict(s=since(b5, 196307), to=0.5, uc=0.001, pub=2015, repl=pairs(['op']), repl_ref=refs(['op']), desc='規模5分位の最上位×OP 最上位5分位')
    L['B6_BIG_LoINV'] = dict(s=since(b6, 196307), to=0.5, uc=0.001, pub=2015, repl=pairs(['inv']), repl_ref=refs(['inv']), desc='規模5分位の最上位×INV 最下位5分位')
    L['B7_BIG_HiBM'] = dict(s=b7, to=0.5, uc=0.001, pub=1992, repl=pairs(['bm']), repl_ref=refs(['bm']), desc='規模5分位の最上位×BM 最上位5分位（1926〜）')
    L['B8_BIG_HiPRIOR'] = dict(s=b8, to=4.0, uc=0.001, pub=1993, repl=pairs(['mom']), repl_ref=refs(['mom']), desc='規模5分位の最上位×勢い(12-2) 最上位5分位（毎月・1927〜）')
    L['B9_MIX_BIG_VAL_MOM'] = dict(s=mix([b7, b8]), to=2.35, uc=0.001, pub=2013, repl=pairs(['bm', 'mom']), repl_ref=refs(['bm', 'mom']), desc='B7+B8 半々（割安+勢い・大型）')
    L['B10_MIX_BIG_OP_MOM'] = dict(s=since(mix([b5, b8]), 196307), to=2.35, uc=0.001, pub=2015, repl=pairs(['op', 'mom']), repl_ref=refs(['op', 'mom']), desc='B5+B8 半々（収益性+勢い・大型）')
    L['B11_MIX_BIG_4SIG'] = dict(s=since(mix([b5, b6, b7, b8]), 196307), to=1.475, uc=0.001, pub=2015, repl=pairs(['op', 'inv', 'bm', 'mom']), repl_ref=refs(['op', 'inv', 'bm', 'mom']), desc='B5・B6・B7・B8 を1/4ずつ（大型の4信号）')
    return L


JKP_TO = {'be_me': 0.6, 'gp_at': 0.4, 'qmj': 0.6, 'ope_be': 0.5, 'chcsho_12m': 1.0, 'oaccruals_at': 1.2, 'ret_12_1': 2.5,
          # 第2段（out/mw_combo_us_prereg2.json）
          'cop_at': 0.4, 'at_gr1': 0.8, 'noa_at': 0.6, 'eqnpo_12m': 0.8, 'betabab_1260d': 0.6, 'ivol_capm_252d': 1.0,
          'qmj_prof': 0.4, 'qmj_growth': 0.8, 'qmj_safety': 0.5}
JKP_PUB = {'be_me': 1992, 'ret_12_1': 1993, 'qmj': 2013, 'gp_at': 2013, 'ope_be': 2015, 'chcsho_12m': 2008, 'oaccruals_at': 1996}


def fam_C_spec():
    return {'C1_VAL_MOM': (['be_me', 'ret_12_1'], 2013), 'C2_QMJ_MOM': (['qmj', 'ret_12_1'], 2013), 'C3_GP_MOM': (['gp_at', 'ret_12_1'], 2013),
            'C4_GP_VAL': (['gp_at', 'be_me'], 2013), 'C5_QMJ_ISS_MOM': (['qmj', 'chcsho_12m', 'ret_12_1'], 2013),
            'C6_QUAL5': (['ope_be', 'gp_at', 'qmj', 'chcsho_12m', 'oaccruals_at'], 2015), 'C7_VAL_MOM_QMJ': (['be_me', 'ret_12_1', 'qmj'], 2013)}


def fam_C():
    return jkp_family(fam_C_spec())


def fam_E_spec():
    Q5 = ['ope_be', 'gp_at', 'qmj', 'chcsho_12m', 'oaccruals_at']
    return {'E1_QUAL5_MOM': (Q5 + ['ret_12_1'], 2015), 'E2_QUAL5_VAL': (Q5 + ['be_me'], 2015), 'E3_PROF3': (['gp_at', 'ope_be', 'cop_at'], 2016),
            'E4_CAPDISC4': (['chcsho_12m', 'at_gr1', 'noa_at', 'eqnpo_12m'], 2008), 'E5_QUAL5_LOWRISK': (Q5 + ['betabab_1260d', 'ivol_capm_252d'], 2015),
            'E6_QMJ3': (['qmj_prof', 'qmj_growth', 'qmj_safety'], 2013), 'E7_QUAL8': (Q5 + ['cop_at', 'at_gr1', 'noa_at'], 2016)}


def fam_E():
    return jkp_family(fam_E_spec())


def jkp_family(spec):
    L = {}
    for sid, (keys, pub) in spec.items():
        ex = jkp_mix('usa', keys, start=196307)
        to = S.mean(JKP_TO[k] for k in keys) + 0.1
        pairs = {c: (jkp_mix(c, keys, min_n=10), M.jkp_mkt(c, 'vw')) for c in JKP7}
        refs = {c: (jkp_mix(c, keys, min_n=10), M.jkp_mkt(c, 'vw')) for c in ['world_ex_us', 'emerging']}
        L[sid] = dict(s=to_total(ex), to=round(to, 3), uc=0.002, pub=pub, repl=pairs, repl_min_months=120, repl_ref=refs, keys=keys,
                      sides={k: good_side(k) for k in keys}, desc='JKP 米国 vw 三分位の良い側を等分: ' + '+'.join(keys),
                      vs_jkp_mkt=M.excess_stats(ex, M.jkp_mkt('usa', 'vw')),
                      vs_jkp_mkt_hold=M.excess_stats(ex, M.jkp_mkt('usa', 'vw'), a=M.HOLD_START))
    return L


def fam_D():
    """第2段: French（CRSP）の BIG 行で C6 の考え方を作り直す（out/mw_combo_us_prereg2.json）"""
    row = lambda name, lab: pf(name, col_index(name, lab))
    op, ac, ni = row('25_Portfolios_ME_OP_5x5', 'BIG HiOP'), row('25_Portfolios_ME_AC_5x5', 'BIG LoAC'), row('25_Portfolios_ME_NI_5x5', 'BIG NegNI')
    inv, mom, bm = row('25_Portfolios_ME_INV_5x5', 'BIG LoINV'), row('25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR'), row('25_Portfolios_5x5', 'BIG HiBM')
    F100O, F100I = '100_Portfolios_ME_OP_10x10', '100_Portfolios_ME_INV_10x10'
    assert [fr(F100O)['cols'][i] for i in (97, 98, 99)] == ['ME10 OP8', 'ME10 OP9', 'BIG HiOP'], fr(F100O)['cols'][97:]
    assert [fr(F100I)['cols'][i] for i in (90, 91, 92)] == ['BIG LoINV', 'ME10 INV2', 'ME10 INV3'], fr(F100I)['cols'][90:93]
    mop, k1 = capw0(F100O, [97, 98, 99])
    minv, k2 = capw0(F100I, [90, 91, 92])
    RG = {'op': ('ME_OP', 'BIG HiOP'), 'inv': ('ME_INV', 'BIG LoINV'), 'bm': ('ME_BE-ME', 'BIG HiBM'), 'mom': ('ME_Prior_12_2', 'BIG HiPRIOR')}

    def proxy(sigs):
        d = {}
        for rg in REG3 + ['Developed_ex_US']:
            ss = []
            for g in sigs:
                suf, lab = RG[g]
                name = f'{rg}_25_Portfolios_{suf}'
                ss.append(pf(name, col_index(name, lab)))
            d[rg] = (mix(ss), region_mkt(rg))
        return d
    S63 = 196307
    L = {
        'D1_BIG_QUAL3': dict(s=mix([op, ac, ni]), to=0.633, uc=0.001, pub=2015, repl=None, repl_proxy=proxy(['op']), desc='French BIG: 高OP+低発生主義+株数純減 を1/3ずつ'),
        'D2_BIG_QUAL4': dict(s=mix([op, ac, ni, inv]), to=0.625, uc=0.001, pub=2015, repl=None, repl_proxy=proxy(['op', 'inv']), desc='D1+低投資 を1/4ずつ'),
        'D3_BIG_QUAL4_MOM': dict(s=mix([op, ac, ni, inv, mom]), to=1.32, uc=0.001, pub=2015, repl=None, repl_proxy=proxy(['op', 'inv', 'mom']), desc='D2+勢い を1/5ずつ'),
        'D4_BIG_QUAL4_VAL': dict(s=mix([op, ac, ni, inv, bm]), to=0.62, uc=0.001, pub=2015, repl=None, repl_proxy=proxy(['op', 'inv', 'bm']), desc='D2+割安 を1/5ずつ'),
        'D5_BIG_QUAL4_VAL_MOM': dict(s=mix([op, ac, ni, inv, bm, mom]), to=1.2, uc=0.001, pub=2015, repl=None, repl_proxy=proxy(['op', 'inv', 'bm', 'mom']), desc='D2+割安+勢い を1/6ずつ'),
        'D6_MEGA_OP_INV': dict(s=mix([mop, minv]), to=0.7, uc=0.001, pub=2015, repl=None, skipped=k1 + k2, desc='規模の最上位10分位×(OP上位3分位)と×(INV下位3分位)を半々'),
        'D7_MEGA_HiOP3': dict(s=mop, to=0.6, uc=0.001, pub=2015, repl=None, skipped=k1, desc='規模の最上位10分位×OP上位3分位（前月の時価で合成）'),
    }
    for v in L.values():
        v['s'] = since(v['s'], S63)
    return L


FAMILIES = [('A_triple', fam_A, True, 1), ('B_double', fam_B, True, 1), ('C_jkp', fam_C, True, 1),
            ('D_frbig', fam_D, False, 2), ('E_jkp2', fam_E, False, 2)]
PREREGS = {1: PREREG, 2: 'out/mw_combo_us_prereg2.json'}


LABELS = [(F_OPINV, 28, 'BIG HiOP LoINV'), (F_BMOP, 31, 'BIG HiBM HiOP'), (F_BMOP, 19, 'BIG LoBM HiOP'), (F_BMINV, 28, 'BIG HiBM LoINV'),
          ('25_Portfolios_BEME_OP_5x5', 24, 'HiBM HiOP'), ('25_Portfolios_OP_INV_5x5', 20, 'HiOP LoINV'), ('25_Portfolios_BEME_INV_5x5', 20, 'HiBM LoINV'),
          ('25_Portfolios_BEME_OP_5x5', 4, 'LoBM HiOP'), ('25_Portfolios_ME_OP_5x5', 24, 'BIG HiOP'), ('25_Portfolios_ME_INV_5x5', 20, 'BIG LoINV'),
          ('25_Portfolios_5x5', 24, 'BIG HiBM'), ('25_Portfolios_ME_Prior_12_2', 24, 'BIG HiPRIOR')]


def sanity():
    o = {}
    for name, idx, lab in LABELS:  # 位置で取った列が意図した角か（取り違えたら大声で止まる）
        assert fr(name)['cols'][idx] == lab, (name, idx, fr(name)['cols'][idx], lab)
    o['labels_checked'] = len(LABELS)
    o['french_mkt_cagr_full'] = round(M.cagr(MKT) * 100, 2)
    o['french_mkt_cagr_2007'] = round(M.cagr(M.window(MKT, M.HOLD_START)) * 100, 2)
    o['french_mkt_range'] = [min(MKT), max(MKT)]
    # 2x4x4 全32 を前月の社数×平均時価総額で合成 → Mkt に近いはず（合成の計算の検算）
    for f in (F_BMOP, F_OPINV):
        allw, sk = capw(f, list(range(32)))
        o[f'capw_all32_{f}'] = {'vs_mkt_full': M.excess_stats(allw, MKT), 'corr': round(M.corr([allw[k] for k in sorted(set(allw) & set(MKT))], [MKT[k] for k in sorted(set(allw) & set(MKT))]), 4), 'skipped_months': sk}
    jm = M.jkp_mkt('usa', 'vw')
    o['jkp_vw_mkt_vs_french_mktrf_full'] = M.excess_stats(jm, MKTRF)
    o['jkp_vw_mkt_vs_french_mktrf_hold'] = M.excess_stats(jm, MKTRF, a=M.HOLD_START)
    o['good_sides_upto_2006'] = {k: good_side(k) for k in JKP_TO}
    return o


def run(families=None):
    res = {'prereg': PREREG, 'prereg_commit': git_sha(PREREG), 'global_prereg': 'out/mw_prereg.json',
           'preregs': {st: {'file': f, 'commit': git_sha(f)} for st, f in PREREGS.items()},
           'benchmark': 'French Mkt = Mkt-RF + RF（総リターン）', 'sanity': sanity(), 'families': {}, 'tested': []}
    for fam, fn, primary, stage in (families or FAMILIES):
        L = fn()
        rows = []
        for sid, v in L.items():
            s = v['s']
            r = {'id': sid, 'family': fam, 'primary': primary, 'exploratory': not primary, 'stage': stage, 'desc': v['desc'],
                 'from': min(s) if s else None, 'to': max(s) if s else None,
                 'turnover_oneway_per_year': v['to'], 'unit_cost': v['uc'], 'pub_year': v.get('pub')}
            r.update(pack(s, MKT, v['to'], v['uc'], v.get('pub')))
            if v.get('repl'):
                r['repl'] = repl_block(v['repl'], v.get('repl_min_months', 24))
            else:
                r['repl'] = None
            if v.get('repl_ref'):
                r['repl_reference'] = repl_block(v['repl_ref'], v.get('repl_min_months', 24))
            if v.get('repl_proxy'):
                r['repl_proxy'] = repl_block(v['repl_proxy'])
            for k in ('keys', 'sides', 'vs_jkp_mkt', 'vs_jkp_mkt_hold', 'skipped'):
                if k in v:
                    r[k] = v[k]
            rows.append(r)
        hp = M.holm({r['id']: (r['hold'] or {}).get('p') for r in rows})
        for r in rows:
            r['holm_p_hold'] = hp.get(r['id'])
            rp = {'regions': r['repl']['regions'], 'positive': r['repl']['positive']} if r['repl'] else None
            g, c = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['cost_hold'], repl=rp,
                           family_holm_p=r['holm_p_hold'], leveraged_or_timing=False)
            r['grade'], r['criteria'] = g, c
        res['families'][fam] = {'n': len(rows), 'primary': primary, 'stage': stage, 'holm_p_hold': hp,
                                'grades': {r['id']: r['grade'] for r in rows}}
        res['tested'].extend(rows)
    res['n_tested'] = len(res['tested'])
    res['diagnostics_posthoc'] = {'C6_QUAL5': diagnostics_c6()}
    # 格付け S/A の戦略の説明（事後・判定に使わない）: 因子回帰と小期間
    SER = {}
    for fam, fn, primary, stage in (families or FAMILIES):
        for sid, v in fn().items():
            SER[sid] = v['s']
    expl = {}
    for r in res['tested']:
        if r['grade'] in ('S', 'A'):
            s = SER[r['id']]
            expl[r['id']] = {'factor_train': factor_reg(s, z=M.TRAIN_END), 'factor_hold': factor_reg(s, a=M.HOLD_START),
                             'factor_full': factor_reg(s), 'subperiods': subperiods(s)}
    res['diagnostics_posthoc']['explain_S_A'] = expl
    res['diagnostics_posthoc']['all_tests_multiplicity'] = all_tests_multiplicity(res['tested'])
    return res


def diagnostics_c6():
    """事後の診断（判定に使わない）: C6_QUAL5 が S になったので、壊れていないかと中身を確かめる。
    (1) 同じ5袖を vw_cap（上限つき）・ew で作ると？（2026-09-26 の longonly は vw_cap で 2007〜 +0.43 t0.5 だった＝再現できるか）
    (2) 袖ごと (3) 暦年ごとの超過 (4) 1袖ずつ抜いた版 (5) 年代ごと"""
    keys = fam_C_spec()['C6_QUAL5'][0]
    o = {'note': '事後の診断。判定には使わない（C6_QUAL5 の格付けは事前登録どおりの主の族の結果）'}

    def mixw(ks, w):
        return C_since(mix([M.jkp_portfolios('usa', k, w)[good_side(k)] for k in ks]))

    def C_since(x):
        return since(x, 196307)
    o['weighting'] = {}
    for w in ('vw', 'vw_cap', 'ew'):
        tot = to_total(mixw(keys, w))
        o['weighting'][w] = {'train': M.excess_stats(tot, MKT, z=M.TRAIN_END), 'hold': M.excess_stats(tot, MKT, a=M.HOLD_START),
                             'recent': M.excess_stats(tot, MKT, a=M.RECENT_START)}
    o['sleeves_vw'] = {}
    for k in list(JKP_TO):
        tot = to_total(C_since(M.jkp_portfolios('usa', k, 'vw')[good_side(k)]))
        o['sleeves_vw'][k] = {'side': good_side(k), 'train': M.excess_stats(tot, MKT, z=M.TRAIN_END), 'hold': M.excess_stats(tot, MKT, a=M.HOLD_START)}
    tot = to_total(mixw(keys, 'vw'))
    yrs = {}
    for k in sorted(tot):
        a = yrs.setdefault(k // 100, [1.0, 1.0, 0]); a[0] *= 1 + tot[k]; a[1] *= 1 + MKT[k]; a[2] += 1
    o['calendar_year_excess_pct'] = {y: round((a - b) * 100, 2) for y, (a, b, n) in yrs.items() if n == 12}
    hy = [v for y, v in o['calendar_year_excess_pct'].items() if y >= 2007]
    o['hold_years_positive'] = f'{sum(1 for v in hy if v > 0)}/{len(hy)}'
    o['leave_one_out'] = {}
    for k in keys:
        t2 = to_total(mixw([x for x in keys if x != k], 'vw'))
        o['leave_one_out']['without_' + k] = {'train': M.excess_stats(t2, MKT, z=M.TRAIN_END), 'hold': M.excess_stats(t2, MKT, a=M.HOLD_START)}
    o['decades'] = {}
    for a in range(1960, 2030, 10):
        st = M.excess_stats(tot, MKT, a=max(a * 100 + 1, 196307), z=a * 100 + 912)
        if st:
            o['decades'][f'{a}s'] = st
    return o


def ff6():
    """French の5因子(2x3)+Mom（小数）→ {'mktrf','smb','hml','rmw','cma','mom'}"""
    o = {}
    for name, cols in (('F-F_Research_Data_5_Factors_2x3', ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA']), ('F-F_Momentum_Factor', ['Mom'])):
        v = next(v for t, v in M.french_tables(name).items() if v['freq'] == 'monthly')
        for c in cols:
            i = v['cols'].index(c)
            o[c.lower().replace('-', '')] = {d: r[i] / 100 for d, r in v['data'].items() if r[i] is not None}
    return o


def factor_reg(s, a=None, z=None):
    """事後の説明（判定に使わない）: (戦略−市場) を SMB・HML・RMW・CMA・Mom と市場超過に回帰。年率のα・NW でない素の t"""
    import numpy as np
    F = ff6()
    names = ['mktrf', 'smb', 'hml', 'rmw', 'cma', 'mom']
    ks = sorted(k for k in s if k in MKT and all(k in F[n] for n in names) and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 60:
        return None
    y = np.array([s[k] - MKT[k] for k in ks])
    X = np.column_stack([np.ones(len(ks))] + [np.array([F[n][k] for k in ks]) for n in names])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    cov = np.linalg.inv(X.T @ X) * (e @ e) / (len(ks) - X.shape[1])
    se = np.sqrt(np.diag(cov))
    out = {'from': ks[0], 'to': ks[-1], 'alpha_ann': round(b[0] * 1200, 2), 'alpha_t': round(b[0] / se[0], 2),
           'r2': round(1 - (e @ e) / ((y - y.mean()) @ (y - y.mean())), 3)}
    for n, bb, ss in zip(names, b[1:], se[1:]):
        out[n] = [round(bb, 3), round(bb / ss, 1)]
    return out


def all_tests_multiplicity(rows):
    """事後の透明性: この角度で試した全部（主+探索）をまとめて Holm。保有期間の p と全期間の p の両方"""
    hp = M.holm({r['id']: (r['hold'] or {}).get('p') for r in rows})
    fp = M.holm({r['id']: (r['full'] or {}).get('p') for r in rows})
    return {'n': len(rows), 'holm_hold_p': hp, 'holm_full_p': fp,
            'note': '全体の線 C7 は族ごとの Holm。ここは『角度の中で試した全部』で数えた場合の参考（格付けは変えない）'}


def subperiods(s):
    return {k: M.excess_stats(s, MKT, a=a, z=z) for k, (a, z) in
            {'2007-2015': (200701, 201512), '2016-': (201601, None), '1963-1984': (196307, 198412), '1985-2006': (198501, 200612)}.items()}


def brief(res):
    print('sanity', json.dumps({k: v for k, v in res['sanity'].items() if not k.startswith('capw')}, ensure_ascii=False)[:600])
    for k, v in res['sanity'].items():
        if k.startswith('capw'):
            print(k, v['vs_mkt_full']['ex_ann'], v['vs_mkt_full']['t'], v['corr'], v['skipped_months'])
    hdr = f"{'id':26s} {'g':1s} {'full':>6s} {'t':>5s} {'train':>6s} {'t':>5s} {'hold':>6s} {'t':>5s} {'gDiff':>6s} {'net':>6s} {'rec':>6s} {'r20':>5s} {'dca':>5s} {'holm':>6s} repl"
    print(hdr)
    for r in res['tested']:
        f, tr, h, c, rc = r['full'] or {}, r['train'] or {}, r['hold'] or {}, r['cost_hold'] or {}, r['recent'] or {}
        rp = f"{r['repl']['positive']}/{r['repl']['regions']}" if r['repl'] else 'NA'
        print(f"{r['id']:26s} {r['grade']:1s} {f.get('ex_ann', 0):6.2f} {f.get('t') or 0:5.2f} {tr.get('ex_ann', 0):6.2f} {tr.get('t') or 0:5.2f} "
              f"{h.get('ex_ann', 0):6.2f} {h.get('t') or 0:5.2f} {h.get('cagr_diff', 0):6.2f} {c.get('ex_ann', 0):6.2f} {rc.get('ex_ann', 0):6.2f} "
              f"{(r['roll20'] or {}).get('win_rate', 0):5.2f} {(r['dca20'] or {}).get('win_rate', 0):5.2f} {r['holm_p_hold'] if r['holm_p_hold'] is not None else -1:6.3f} {rp}")


if __name__ == '__main__':
    res = run()
    M.save(OUT, res)
    brief(res)
