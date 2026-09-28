#!/usr/bin/env python3
"""night/mw_mega_tilt.py — 『市場に勝てる歴史検証』の角度 mega_tilt（読むだけ・門の判定には不使用）

問い: 大型株の投資家が作れる形『市場（上限なしの時価加重）＋ λ ×（大型株の中の買い−売り）』で、
      S&P500 型の純粋な市場（French Mkt）に勝てたか。
事前登録: out/mw_mega_tilt_prereg.json（線は out/mw_prereg.json・判定は mw_common.grade）
出力: out/mw_mega_tilt.json

族
- P（主・Holm 34本）: P-A 米国 mega の順位加重 LS（JKP 規模別・向きを掛ける）×λ0.2 ／ P-B 米国 JKP 'vw' 三分位 LS ×λ0.2
- X1（探索）: 同じものを λ=0.33、P-A を λ_feas（訓練期間だけで決めた買いだけの上限）
- X2（探索）: French の BIG（2x3）・ME5（5x5）の時価加重 LS ×λ0.2
"""
import csv, io, json, math, os, random, statistics as S, subprocess, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

BASE = M.BASE
PREREG = 'mw_mega_tilt_prereg.json'
PR = json.load(open(os.path.join(BASE, 'out', PREREG)))
CH = {k: v for k, v in PR['characteristics'].items() if not k.startswith('_')}
QUAL = ['gp_at', 'ope_be', 'qmj', 'qmj_prof', 'cop_at']
REGIONS = ['developed', 'world_ex_us', 'jpn', 'emerging', 'gbr', 'deu', 'fra', 'che', 'can', 'aus']
COUNTRIES = ['jpn', 'emerging', 'gbr', 'deu', 'fra', 'che', 'can', 'aus']
LAM = 0.2
COST = 0.001
JKP_END = 202512


def sha_of(path):
    try:
        return subprocess.run(['git', 'log', '--diff-filter=A', '--format=%H', '--', path], cwd=BASE,
                              capture_output=True, text=True).stdout.strip().split('\n')[-1] or None
    except Exception:  # noqa
        return None


# ───────────────────────── データ ─────────────────────────
def directions_from_xlsx():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jkp_factor_details.xlsx'), read_only=True)
    rows = list(wb['details'].iter_rows(values_only=True))
    h = rows[0]
    ia, idr = h.index('abr_jkp'), h.index('direction')
    return {r[ia]: int(r[idr]) for r in rows[1:] if r[ia] and r[idr] is not None}


def mega_raw(k, sz='mega', nmin=50):
    """JKP 規模別（characteristic-managed・順位加重・向き無し）→ ({ym: ret 向きなし}, {ym: n})"""
    u = f'https://jkpfactors-data.s3.amazonaws.com/public/factor/%5Busa%5D_%5B{k}%5D_%5B{sz}%5D.zip'
    b = M.get(u, name=f'jkp_size_usa_{k}_{sz}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    r, n = {}, {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        ym = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        n[ym] = int(x['n'])
        if int(x['n']) >= nmin:
            r[ym] = float(x['ret'])
    return r, n


def vw_all(region):
    """JKP all_factors（vw・符号つき）→ {特徴: {ym: ret}}。国は n_stocks_min≥10、地域は n_countries≥3"""
    out = {}
    for x in M.jkp_rows(region, 'all_factors', 'factor', 'vw'):
        if x['name'] not in CH or x['ret'] in ('', 'NA', 'na'):
            continue
        if 'n_stocks_min' in x and x['n_stocks_min'] not in ('', 'NA') and int(float(x['n_stocks_min'])) < 10:
            continue
        if 'n_countries' in x and x['n_countries'] not in ('', 'NA') and int(float(x['n_countries'])) < 3:
            continue
        out.setdefault(x['name'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    return out


def ftab(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            return v
    raise KeyError(f'{name}: {want}')


def fr_raw(name, want):
    """French の社数・平均時価総額の表 → {列: {ym: 値}}（百分率ではないので 100 で割らない）"""
    v = ftab(name, want)
    out = {c: {} for c in v['cols']}
    for d, row in v['data'].items():
        for c, x in zip(v['cols'], row):
            if x is not None:
                out[c][d] = x
    return out


def fr_capshare(name, cols):
    """French の社数×平均時価総額から cols の時価総額 → {ym: $百万}"""
    n = fr_raw(name, 'Number of Firms')
    try:
        a = fr_raw(name, 'Average Market Cap')
    except KeyError:
        a = fr_raw(name, 'Average Firm Size')
    out = {}
    for d in n[cols[0]]:
        v = 0.0
        ok = True
        for c in cols:
            if d in n[c] and d in a[c]:
                v += n[c][d] * a[c][d]
            else:
                ok = False
        if ok:
            out[d] = v
    return out


def total_cap():
    return fr_capshare('Portfolios_Formed_on_ME', ['Lo 30', 'Med 40', 'Hi 30'])


def me_p80():
    b = M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/ME_Breakpoints_CSV.zip', name='fr_ME_Breakpoints.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = {}
    for line in z.read(z.namelist()[0]).decode('latin-1').splitlines():
        c = [x.strip() for x in line.split(',')]
        if c and c[0].isdigit() and len(c[0]) == 6 and len(c) >= 22:
            out[int(c[0])] = float(c[17])  # 5,10,…,80 → 16番目の分位（列 2+15）
    return out


def prev_month(ym):
    y, m = divmod(ym, 100)
    return (y - 1) * 100 + 12 if m == 1 else ym - 1


def fr_region_mkt(name):
    """French 地域の3因子（または5因子）→ 総リターン（USD）"""
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(name)


# ───────────────────────── 組み立て ─────────────────────────
def blend(series_list, weights=None):
    ks = set(series_list[0])
    for s in series_list[1:]:
        ks &= set(s)
    w = weights or [1 / len(series_list)] * len(series_list)
    return {k: sum(wi * s[k] for wi, s in zip(w, series_list)) for k in sorted(ks)}


def blend_def(name):
    if name == 'Q5':
        return QUAL, None
    if name == 'QM':
        return QUAL + ['ret_12_1'], [0.5 / 5] * 5 + [0.5]
    if name == 'QMV':
        return QUAL + ['ret_12_1', 'be_me'], [1 / 15] * 5 + [1 / 3, 1 / 3]
    raise KeyError(name)


def turnover_of(comps, weights=None):
    w = weights or [1 / len(comps)] * len(comps)
    return sum(wi * CH[c]['turnover'] for wi, c in zip(w, comps))


def build(ls_by_char, name):
    """特徴 or 混合の LS を作る。混合は構成要素がすべてそろう月だけ"""
    if name in CH:
        return ls_by_char.get(name)
    comps, w = blend_def(name)
    ss = [ls_by_char.get(c) for c in comps]
    if any(s is None or not s for s in ss):
        return None
    return blend(ss, w)


# ───────────────────────── 評価 ─────────────────────────
def tilt(mkt, ls, lam, to):
    ks = sorted(k for k in set(mkt) & set(ls) if k <= JKP_END)
    s = {k: mkt[k] + lam * ls[k] for k in ks}
    b = {k: mkt[k] for k in ks}
    net = M.apply_cost(s, to * lam * 2, COST)
    net3 = M.apply_cost(s, to * lam * 2, COST * 3)
    return s, b, net, net3


def repl_test(ls_regional, lam, to, mkts=None):
    """C5: 地域ごとに 費用後の λ×LS の算術平均 > 0 か"""
    per = {}
    for reg, ls in ls_regional.items():
        if not ls or len(ls) < 60:
            continue
        c = to * lam * 2 * COST / 12
        ks = sorted(k for k in ls if k <= JKP_END)
        ex = [lam * ls[k] - c for k in ks]
        rec = {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / 12, 1), 'net_ex_ann': round(S.mean(ex) * 1200, 2),
               't': (lambda t: round(t, 2) if t is not None else None)(M.nw_t(ex)), 'positive': S.mean(ex) > 0}
        hk = [k for k in ks if k >= M.HOLD_START]
        if len(hk) >= 24:
            hx = [lam * ls[k] - c for k in hk]
            rec['hold_net_ex_ann'] = round(S.mean(hx) * 1200, 2)
            rec['hold_t'] = (lambda t: round(t, 2) if t is not None else None)(M.nw_t(hx))
        if mkts and reg in mkts:
            m = mkts[reg]
            s = {k: m[k] + lam * ls[k] - c for k in ks if k in m}
            st = M.excess_stats(s, m)
            if st:
                rec['cagr_diff'] = st['cagr_diff']
        per[reg] = rec
    n = len(per)
    k = sum(1 for v in per.values() if v['positive'])
    cn = [r for r in per if r in COUNTRIES]
    return {'regions': n, 'positive': k, 'countries_only': {'regions': len(cn), 'positive': sum(1 for r in cn if per[r]['positive'])},
            'per_region': per}


def evaluate(name, family, desc, mkt, ls, lam, to, pub=None, repl=None, primary=False, extra=None):
    if not ls:
        return {'name': name, 'family': family, 'description': desc, 'error': 'データ無し'}
    s, b, net, net3 = tilt(mkt, ls, lam, to)
    full = M.excess_stats(s, b)
    train = M.excess_stats(s, b, z=M.TRAIN_END)
    hold = M.excess_stats(s, b, a=M.HOLD_START)
    recent = M.excess_stats(s, b, a=M.RECENT_START)
    cost_hold = M.excess_stats(net, b, a=M.HOLD_START)
    cost3_hold = M.excess_stats(net3, b, a=M.HOLD_START)
    post = M.excess_stats(s, b, a=(pub + 1) * 100 + 1) if pub else None
    roll = M.rolling(net, b, 20)
    dc = M.dca(net, b, 20)
    rec = {'name': name, 'family': family, 'primary': primary, 'description': desc, 'lambda': lam,
           'turnover_leg': round(to, 3), 'annual_cost_pct': round(to * lam * 2 * COST * 100, 4),
           'full': full, 'train': train, 'hold': hold, 'recent': recent, 'net_cost_hold': cost_hold,
           'net_cost3_hold': cost3_hold, 'post_publication': post, 'pub_year': pub,
           'roll20_net': roll, 'dca20_net': dc,
           'maxdd': {'tilt': round(M.maxdd(s) * 100, 1), 'mkt': round(M.maxdd(b) * 100, 1)},
           'repl': repl}
    if extra:
        rec.update(extra)
    return rec


def finish_family(recs):
    """族の中で Holm（保有期間・費用前の p）→ 判定"""
    ps = {r['name']: r['hold']['p'] for r in recs if r.get('hold') and r['hold'].get('p') is not None}
    hp = M.holm(ps)
    for r in recs:
        if r.get('error'):
            r['grade'] = 'C'
            continue
        r['family_holm_p'] = hp.get(r['name'])
        rp = r.get('repl')
        g, c = M.grade(r['full'], r['train'], r['hold'], r['roll20_net'], cost_hold=r['net_cost_hold'],
                       repl={'regions': rp['regions'], 'positive': rp['positive']} if rp else None,
                       family_holm_p=r['family_holm_p'])
        r['grade'], r['criteria'] = g, c
    return recs


# ───────────────────────── 実行可能性（λ の上限） ─────────────────────────
def pareto_negmass(n5, a5, xmin, total, n_rank, lam, draws=30, seed=0):
    """mega の中で順位と規模が無相関と仮定し、λ×順位加重 LS を足したときの負の重みの合計（推定）"""
    if a5 <= xmin or n5 < 10:
        return None
    alpha = a5 / (a5 - xmin)
    rnd = random.Random(seed)
    n = n_rank
    p = [(r + 1) / (n + 1) for r in range(n)]
    dev = [x - 0.5 for x in p]
    sc = sum(abs(d) for d in dev) / 2
    w = [d / sc for d in dev]
    out = []
    for _ in range(draws):
        caps = [min(xmin * (1 - rnd.random()) ** (-1 / alpha), total * 0.08) for _ in range(n)]
        rnd.shuffle(caps)
        neg = 0.0
        for c, wi in zip(caps, w):
            v = c / total + lam * wi
            if v < 0:
                neg += -v
        out.append(neg)
    return S.median(out)


def feasibility(mega_n):
    tot = total_cap()
    p80 = me_p80()
    worst, typ = {}, {}
    for ym, n in mega_n.items():
        pm = prev_month(ym)
        if ym in tot and pm in p80 and n >= 50:
            base = p80[pm] / tot[ym]
            worst[ym] = base * n / 4
            typ[ym] = base * n / 2
    tr = sorted(v for k, v in worst.items() if k <= M.TRAIN_END)
    lam_feas = max(0.01, math.floor(S.median(tr) * 100) / 100) if tr else None

    def summ(d, a=None, z=None):
        v = sorted(x for k, x in d.items() if (a is None or k >= a) and (z is None or k <= z))
        if not v:
            return None
        return {'min': round(v[0], 4), 'p05': round(v[int(len(v) * 0.05)], 4), 'median': round(v[len(v) // 2], 4), 'max': round(v[-1], 4), 'months': len(v)}
    # Pareto 推定（毎年12月）
    q = fr_raw('Portfolios_Formed_on_ME', 'Number of Firms')
    try:
        qa = fr_raw('Portfolios_Formed_on_ME', 'Average Firm Size')
    except KeyError:
        qa = fr_raw('Portfolios_Formed_on_ME', 'Average Market Cap')
    neg = {}
    for ym in sorted(mega_n):
        if ym % 100 != 12 or ym not in tot or prev_month(ym) not in p80 or mega_n[ym] < 50:
            continue
        n5, a5 = q['Hi 20'].get(ym), qa['Hi 20'].get(ym)
        if not n5 or not a5:
            continue
        v = {}
        for lam in (0.05, 0.1, 0.2, 0.33):
            nm = pareto_negmass(int(n5), a5, p80[prev_month(ym)], tot[ym], mega_n[ym], lam, seed=ym)
            v[str(lam)] = round(nm * 100, 2) if nm is not None else None
        neg[ym // 100] = v
    negsum = {}
    for lam in ('0.05', '0.1', '0.2', '0.33'):
        vals = [v[lam] for v in neg.values() if v.get(lam) is not None]
        hv = [v[lam] for y, v in neg.items() if y >= 2007 and v.get(lam) is not None]
        negsum[lam] = {'median_pct': round(S.median(vals), 2) if vals else None, 'max_pct': max(vals) if vals else None,
                       'median_2007_pct': round(S.median(hv), 2) if hv else None}
    return {'mega_worst_case_bound': {'full': summ(worst), 'train': summ(worst, z=M.TRAIN_END), 'hold': summ(worst, a=M.HOLD_START)},
            'mega_typical_bound': {'full': summ(typ), 'train': summ(typ, z=M.TRAIN_END), 'hold': summ(typ, a=M.HOLD_START)},
            'lambda_feas': lam_feas,
            'lambda_feas_rule': '〜2006 の各月の最悪ケース上限（NYSE 80%点 ÷ 市場全体 × n/4・n=ret_12_1 の mega 銘柄数）の中央値を 0.01 単位で切り捨て',
            'pareto_negative_mass_pct_by_lambda': negsum,
            'pareto_negative_mass_pct_by_year': {str(y): v for y, v in sorted(neg.items()) if y % 5 == 0 or y >= 2020},
            'note': '負の重みの合計＝λ×順位加重 LS を足したとき売りが必要になる割合（ポートフォリオ全体の%）。順位と規模が mega の中で無相関という仮定の推定'}, tot


def french_lam_max(name, bad_cols, tot):
    cap = fr_capshare(name, bad_cols)
    r = {k: cap[k] / tot[k] for k in cap if k in tot and tot[k] > 0}
    v = sorted(r.values())
    if not v:
        return None
    share_ok = sum(1 for x in v if x >= LAM) / len(v)
    return {'min': round(v[0], 3), 'p05': round(v[int(len(v) * 0.05)], 3), 'median': round(v[len(v) // 2], 3),
            'share_months_ge_0.2': round(share_ok, 3), 'long_only_at_0.2': share_ok >= 0.95}


# ───────────────────────── French の答え合わせ（X2）の定義 ─────────────────────────
FR2 = {  # 2x3 BIG: (ファイル, 良い側, 悪い側, 対応する JKP 特徴, 米国外のファイル接尾辞)
    'F2_be_me': ('6_Portfolios_2x3', 'BIG HiBM', 'BIG LoBM', 'be_me', 'BE-ME'),
    'F2_ni_me': ('6_Portfolios_ME_EP_2x3', 'BIG HiEP', 'BIG LoEP', 'ni_me', None),
    'F2_ope_be': ('6_Portfolios_ME_OP_2x3', 'BIG HiOP', 'BIG LoOP', 'ope_be', 'OP'),
    'F2_at_gr1': ('6_Portfolios_ME_INV_2x3', 'BIG LoINV', 'BIG HiINV', 'at_gr1', 'INV'),
    'F2_ret_12_1': ('6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 'ret_12_1', 'Prior_12_2'),
}
FR5 = {  # 5x5 ME5
    'F5_be_me': ('25_Portfolios_5x5', 'BIG HiBM', 'BIG LoBM', 'be_me', 'BE-ME'),
    'F5_ope_be': ('25_Portfolios_ME_OP_5x5', 'BIG HiOP', 'BIG LoOP', 'ope_be', 'OP'),
    'F5_at_gr1': ('25_Portfolios_ME_INV_5x5', 'BIG LoINV', 'BIG HiINV', 'at_gr1', 'INV'),
    'F5_ret_12_1': ('25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 'ret_12_1', 'Prior_12_2'),
    'F5_oaccruals_at': ('25_Portfolios_ME_AC_5x5', 'BIG LoAC', 'BIG HiAC', 'oaccruals_at', None),
    'F5_chcsho_12m': ('25_Portfolios_ME_NI_5x5', 'BIG NegNI', 'BIG HiNI', 'chcsho_12m', None),
    'F5_betabab_1260d': ('25_Portfolios_ME_BETA_5x5', 'BIG LoBETA', 'BIG HiBETA', 'betabab_1260d', None),
    'F5_ivol_capm_252d': ('25_Portfolios_ME_RESVAR_5x5', 'BIG LoVAR', 'BIG HiVAR', 'ivol_capm_252d', None),
}
FR_INTL = {'Developed_ex_US': 'Developed_ex_US_3_Factors', 'Europe': 'Europe_3_Factors', 'Japan': 'Japan_3_Factors',
           'Asia_Pacific_ex_Japan': 'Asia_Pacific_ex_Japan_3_Factors', 'Emerging_Markets': 'Emerging_5_Factors'}


def fr_ls(name, good, bad):
    v = M.french_series(name, 'Value Weight')
    return {k: v[good][k] - v[bad][k] for k in v[good] if k in v[bad]}


def fr_intl_ls(suffix, good_short, bad_short):
    out = {}
    for reg in FR_INTL:
        try:
            v = M.french_series(f'{reg}_6_Portfolios_ME_{suffix}', 'Value Weight')
        except Exception as e:  # noqa
            print('  French 米国外なし', reg, suffix, e)
            continue
        g = [c for c in v if c.replace(' ', '') == good_short.replace(' ', '')]
        bcol = [c for c in v if c.replace(' ', '') == bad_short.replace(' ', '')]
        if g and bcol:
            out[reg] = {k: v[g[0]][k] - v[bcol[0]][k] for k in v[g[0]] if k in v[bcol[0]]}
    return out


# ───────────────────────── 本体 ─────────────────────────
def main():
    out = {'angle': 'mega_tilt', 'prereg': PREREG, 'prereg_commit': sha_of(f'out/{PREREG}'),
           'global_prereg': 'mw_prereg.json', 'global_prereg_commit': sha_of('out/mw_prereg.json'),
           'benchmark': 'French Mkt（Mkt-RF+RF）', 'jkp_end': JKP_END, 'sanity': {}, 'deviations': [], 'tested': []}
    # ── 向き
    dx = directions_from_xlsx()
    bad = {k: (CH[k]['direction'], dx.get(k)) for k in CH if dx.get(k) != CH[k]['direction']}
    out['sanity']['direction_matches_xlsx'] = not bad
    if bad:
        raise SystemExit(f'向きが事前登録と xlsx で違う: {bad}')
    # ── 市場
    ff = M.ff_factors()
    mkt, mktrf = ff['mkt'], ff['mktrf']
    out['sanity']['french_mkt_cagr_full'] = round(M.cagr(mkt) * 100, 2)
    out['sanity']['french_mkt_cagr_2007'] = round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)
    jm = M.jkp_mkt('usa', 'vw')
    ks = sorted(set(jm) & set(mktrf))
    out['sanity']['jkp_usa_vw_mkt_minus_french_mktrf'] = {
        'full_pct_yr': round(S.mean(jm[k] - mktrf[k] for k in ks) * 1200, 2),
        'hold_pct_yr': round(S.mean(jm[k] - mktrf[k] for k in ks if k >= M.HOLD_START) * 1200, 2),
        'corr': round(M.corr([jm[k] for k in ks], [mktrf[k] for k in ks]), 4)}
    # ── 米国の LS（P-A mega・P-B vw）
    mega, mega_n_all = {}, {}
    for k in CH:
        r, n = mega_raw(k)
        mega[k] = {ym: v * CH[k]['direction'] for ym, v in r.items()}
        mega_n_all[k] = n
    vwu = vw_all('usa')
    # 検算: vw の符号つき因子 = (3−1)×direction
    chk = {}
    for k in CH:
        p = M.jkp_portfolios('usa', k, 'vw')
        if '3.0' in p and '1.0' in p and k in vwu:
            kk = sorted(set(p['3.0']) & set(p['1.0']) & set(vwu[k]))
            chk[k] = round(M.corr([(p['3.0'][m] - p['1.0'][m]) * CH[k]['direction'] for m in kk], [vwu[k][m] for m in kk]), 4)
    out['sanity']['vw_factor_vs_tercile_spread_corr'] = chk
    # 検算: mega×direction と全規模 vw の相関（正であるべき）
    out['sanity']['mega_signed_vs_vw_signed_corr'] = {
        k: round(M.corr([mega[k][m] for m in sorted(set(mega[k]) & set(vwu.get(k, {})))],
                        [vwu[k][m] for m in sorted(set(mega[k]) & set(vwu.get(k, {})))]), 3) for k in CH if k in vwu}
    neg_corr = [k for k, v in out['sanity']['mega_signed_vs_vw_signed_corr'].items() if v <= 0]
    out['sanity']['mega_sign_ok'] = not neg_corr
    # 検算: French 2x3 BIG OP と JKP mega ope_be の相関
    fop = fr_ls('6_Portfolios_ME_OP_2x3', 'BIG HiOP', 'BIG LoOP')
    kk = sorted(set(fop) & set(mega['ope_be']))
    out['sanity']['french_bigOP_vs_mega_ope_be_corr'] = round(M.corr([fop[m] for m in kk], [mega['ope_be'][m] for m in kk]), 3)
    fbm = fr_ls('6_Portfolios_2x3', 'BIG HiBM', 'BIG LoBM')
    kk = sorted(set(fbm) & set(mega['be_me']))
    out['sanity']['french_bigBM_vs_mega_be_me_corr'] = round(M.corr([fbm[m] for m in kk], [mega['be_me'][m] for m in kk]), 3)
    fpr = fr_ls('6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR')
    kk = sorted(set(fpr) & set(mega['ret_12_1']))
    out['sanity']['french_bigPrior_vs_mega_ret_12_1_corr'] = round(M.corr([fpr[m] for m in kk], [mega['ret_12_1'][m] for m in kk]), 3)
    print('検算', json.dumps(out['sanity'], ensure_ascii=False))
    # ── 米国外（C5）
    reg_vw = {r: vw_all(r) for r in REGIONS}
    reg_mkt = {r: M.jkp_mkt(r, 'vw') for r in REGIONS}
    # ── 実行可能性
    feas, tot = feasibility(mega_n_all['ret_12_1'])
    out['feasibility'] = feas
    lam_feas = feas['lambda_feas']
    print('実行可能性', json.dumps({k: v for k, v in feas.items() if k != 'pareto_negative_mass_pct_by_year'}, ensure_ascii=False))
    # JKP vw 三分位の悪い側の時価総額（French 2x3 の BIG+SMALL の悪い側で近似）
    approx = {}
    for key, (fname, g, bcol, jk, _) in FR2.items():
        sb = bcol.replace('BIG', 'SMALL')
        approx[jk] = french_lam_max(fname, [bcol, sb], tot)
    out['feasibility']['vw_tercile_bad_side_capshare_approx_by_french_2x3'] = approx
    out['feasibility']['french_bad_side_capshare'] = {}
    for key, (fname, g, bcol, jk, _) in list(FR2.items()) + list(FR5.items()):
        out['feasibility']['french_bad_side_capshare'][key] = french_lam_max(fname, [bcol], tot)
    names = list(CH) + ['Q5', 'QM', 'QMV']

    def to_of(nm):
        if nm in CH:
            return CH[nm]['turnover']
        c, w = blend_def(nm)
        return turnover_of(c, w)

    def pub_of(nm):
        if nm in CH:
            return CH[nm]['pub']
        c, _ = blend_def(nm)
        return max(CH[x]['pub'] for x in c)

    def repl_for(nm, lam):
        regls = {r: build(reg_vw[r], nm) for r in REGIONS}
        return repl_test({r: v for r, v in regls.items() if v}, lam, to_of(nm), reg_mkt)

    fams = {}
    # P（主）
    P = []
    for nm in names:
        desc = CH[nm]['意味'] if nm in CH else PR['blends'][nm]
        P.append(evaluate(f'PA_mega_{nm}', 'P', f'米国 mega 順位加重 LS: {desc}', mkt, build(mega, nm), LAM, to_of(nm), pub_of(nm),
                          repl_for(nm, LAM), primary=True))
    for nm in names:
        desc = CH[nm]['意味'] if nm in CH else PR['blends'][nm]
        P.append(evaluate(f'PB_vw_{nm}', 'P', f'米国 vw 三分位 LS（全規模・時価加重）: {desc}', mkt, build(vwu, nm), LAM, to_of(nm), pub_of(nm),
                          repl_for(nm, LAM), primary=True))
    fams['P'] = finish_family(P)
    # X1 λ=0.33
    X1a = []
    for nm in names:
        X1a.append(evaluate(f'X1_mega_{nm}_lam033', 'X1_lam033', f'P-A と同じ・λ=0.33', mkt, build(mega, nm), 0.33, to_of(nm), pub_of(nm), repl_for(nm, 0.33)))
    for nm in names:
        X1a.append(evaluate(f'X1_vw_{nm}_lam033', 'X1_lam033', f'P-B と同じ・λ=0.33', mkt, build(vwu, nm), 0.33, to_of(nm), pub_of(nm), repl_for(nm, 0.33)))
    fams['X1_lam033'] = finish_family(X1a)
    X1b = []
    for nm in names:
        X1b.append(evaluate(f'X1_mega_{nm}_lamfeas', 'X1_lamfeas', f'P-A と同じ・λ_feas={lam_feas}（訓練期間だけで決めた買いだけの上限）', mkt,
                            build(mega, nm), lam_feas, to_of(nm), pub_of(nm), repl_for(nm, lam_feas)))
    fams['X1_lamfeas'] = finish_family(X1b)
    # X2 French
    X2 = []
    frls = {}
    for key, (fname, g, bcol, jk, suf) in list(FR2.items()) + list(FR5.items()):
        ls = fr_ls(fname, g, bcol)
        frls[key] = ls
        if suf:
            gi = g.replace('BIG ', 'BIG ')
            intl = fr_intl_ls(suf, g, bcol)
            fm = {r: fr_region_mkt(FR_INTL[r]) for r in intl}
            rp = repl_test(intl, LAM, CH[jk]['turnover'], fm)
            rp['source'] = 'French 米国外 6_Portfolios の BIG の行'
        else:
            rp = repl_for(jk, LAM)
            rp['source'] = 'JKP vw 三分位（French に米国外が無い）'
        X2.append(evaluate(key, 'X2', f'French {fname}: {g} − {bcol}（時価加重・{CH[jk]["意味"]}）', mkt, ls, LAM, CH[jk]['turnover'], CH[jk]['pub'], rp,
                           extra={'long_only_capshare': out['feasibility']['french_bad_side_capshare'].get(key)}))
    for key, parts in (('F2_QM', ['F2_ope_be', 'F2_ret_12_1']), ('F2_QMV', ['F2_ope_be', 'F2_ret_12_1', 'F2_be_me'])):
        ls = blend([frls[p] for p in parts])
        jks = [FR2[p][3] for p in parts]
        intl_parts = [fr_intl_ls(FR2[p][4], FR2[p][1], FR2[p][2]) for p in parts]
        regs = set(intl_parts[0])
        for ip in intl_parts[1:]:
            regs &= set(ip)
        intl = {r: blend([ip[r] for ip in intl_parts]) for r in regs}
        fm = {r: fr_region_mkt(FR_INTL[r]) for r in intl}
        to = turnover_of(jks)
        rp = repl_test(intl, LAM, to, fm)
        rp['source'] = 'French 米国外 6_Portfolios の BIG の行'
        X2.append(evaluate(key, 'X2', f'French 2x3 BIG の混合: {" + ".join(parts)}（等分）', mkt, ls, LAM, to, max(CH[j]['pub'] for j in jks), rp))
    fams['X2'] = finish_family(X2)
    for f, recs in fams.items():
        out['tested'].extend(recs)
    out['n_tested'] = len(out['tested'])
    out['families'] = {f: {'n': len(r), 'grades': {g: sum(1 for x in r if x.get('grade') == g) for g in 'SABC'}} for f, r in fams.items()}
    out['deviations'].append('JKP の規模別（mega）は三分位の時価加重ではなく順位加重の characteristic-managed portfolio だった（作成コード portfolios.R の cmp 節で確認）。そのため λ=0.2 は厳密な買いだけでは作れない可能性が高い（feasibility 参照）')
    out['deviations'].append('JKP の規模別は米国しか公開されていないので、P-A の C5（再現）は同じ特徴の JKP vw 三分位 LS（全規模・時価加重）の米国外10地域で代用')
    p = M.save('mw_mega_tilt.json', out)
    # 表示
    print('\n族  名前                         格  全期間(t)      訓練(t)       保有(t)       保有費用後  最近   20年勝率  C5')
    for r in out['tested']:
        if r.get('error'):
            print(r['name'], 'ERR', r['error']); continue
        f = lambda s: f"{s['ex_ann']:+5.2f}({s['t']:+4.1f})" if s else '   —      '
        rp = r.get('repl') or {}
        print(f"{r['family']:10} {r['name'][:30]:30} {r['grade']}  {f(r['full'])}  {f(r['train'])}  {f(r['hold'])}  "
              f"{r['net_cost_hold']['ex_ann'] if r['net_cost_hold'] else '—':>6}  {r['recent']['ex_ann'] if r['recent'] else '—':>5}  "
              f"{r['roll20_net']['win_rate'] if r['roll20_net'] else '—':>5}  {rp.get('positive')}/{rp.get('regions')}")
    print('書いた', p)


if __name__ == '__main__':
    main()
