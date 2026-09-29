#!/usr/bin/env python3
"""night/mw_mega_tilt_verify.py — 角度 mega_tilt の反証の検証（読むだけ・門の判定には不使用）

役割: 別の担当が out/mw_mega_tilt.json で主張した候補（S/A と、保有期間の超過が大きい B の上位2本）を、
      **自分で書いた組み立てと統計**で作り直し、崩せるかを試す。
- 取得だけ mw_common の fetcher（M.get / M.ff_factors / M.jkp_rows / M.french_tables）を使う。
- 傾けた形 s = Mkt + λ×LS の組み立て・超過・NW t・CAGR 差・転がる窓・積立・費用・Holm はここで独立に実装する。
- 相手は French Mkt（Mkt-RF + RF＝上限なしの時価加重・CRSP 全上場）。

出力: out/mw_mega_tilt_verify.json
"""
import csv, io, json, math, os, sys, zipfile, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得だけに使う）

BASE = M.BASE
LAM = 0.2
JKP_END = 202512
CANDS = ['gp_at', 'ope_be', 'qmj', 'qmj_prof', 'cop_at', 'chcsho_12m', 'oaccruals_at', 'ret_12_1']
CLAIMED_GRADE = {'gp_at': 'B', 'ope_be': 'B', 'qmj': 'S', 'qmj_prof': 'S', 'cop_at': 'S', 'chcsho_12m': 'A', 'oaccruals_at': 'A', 'ret_12_1': 'A'}
ALL14 = ['gp_at', 'ope_be', 'qmj', 'qmj_prof', 'cop_at', 'chcsho_12m', 'oaccruals_at', 'ret_12_1', 'be_me', 'ni_me', 'at_gr1',
         'ivol_capm_252d', 'betabab_1260d', 'niq_su']
PUB = {'gp_at': 2013, 'ope_be': 2015, 'qmj': 2018, 'qmj_prof': 2018, 'cop_at': 2016, 'chcsho_12m': 2008, 'oaccruals_at': 1996,
       'ret_12_1': 1993, 'niq_su': 1984}
TURN = {'gp_at': 0.4, 'ope_be': 0.4, 'qmj': 0.4, 'qmj_prof': 0.4, 'cop_at': 0.4, 'chcsho_12m': 0.8, 'oaccruals_at': 0.8, 'ret_12_1': 1.5,
        'be_me': 0.4, 'ni_me': 0.4, 'at_gr1': 0.8, 'ivol_capm_252d': 0.8, 'betabab_1260d': 0.4, 'niq_su': 1.5}
COUNTRIES = ['jpn', 'gbr', 'deu', 'fra', 'che', 'can', 'aus', 'emerging']


# ───────────── 自前の統計（mw_common の統計は使わない） ─────────────
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
    v = math.fsum(a * a for a in e) / n
    for l in range(1, L + 1):
        c = math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
        v += 2 * (1 - l / (L + 1)) * c
    return m / math.sqrt(v / n) if v > 0 else None


def corr(a, b):
    ma, mb = mean(a), mean(b)
    va = math.fsum((x - ma) ** 2 for x in a); vb = math.fsum((y - mb) ** 2 for y in b)
    return math.fsum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def pval(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def geo(x):
    return math.exp(math.fsum(math.log1p(v) for v in x) * 12 / len(x)) - 1


def stats(s, b, a=None, z=None, drop=None):
    ks = [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z) and not (drop and drop(k))]
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nwt(d)
    return {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'ex_ann': round(mean(d) * 1200, 3),
            't': round(t, 3) if t is not None else None, 'p': round(pval(t), 4) if t is not None else None,
            'cagr_diff': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 3)}


def roll(s, b, years=20, a=None, z=None):
    ks = sorted(set(s) & set(b))
    out = []
    for y in range(ks[0] // 100, 2100):
        lo, hi = y * 100 + 7, (y + years) * 100 + 6
        if hi > ks[-1]:
            break
        if (a and lo < a) or (z and hi > z):
            continue
        w = [k for k in ks if lo <= k <= hi]
        if len(w) < years * 12 * 0.97:
            continue
        out.append((y, round((geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100, 3)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'windows': len(out), 'wins': sum(1 for c in v if c > 0), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3),
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'first_start': out[0][0], 'last_start': out[-1][0]}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    out = []
    for i in range(0, len(ks) - 240 + 1, 12):
        ws = wb = 0.0
        for k in ks[i:i + 240]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append(ws / wb)
    out.sort()
    return {'windows': len(out), 'win_rate': round(sum(1 for r in out if r > 1) / len(out), 3), 'median_ratio': round(out[len(out) // 2], 3),
            'worst_ratio': round(out[0], 3)} if out else None


def inv(A):
    n = len(A)
    Mx = [list(r) + [1.0 if i == j else 0.0 for j in range(n)] for i, r in enumerate(A)]
    for c in range(n):
        pv = max(range(c, n), key=lambda r: abs(Mx[r][c]))
        Mx[c], Mx[pv] = Mx[pv], Mx[c]
        d = Mx[c][c]
        Mx[c] = [v / d for v in Mx[c]]
        for r in range(n):
            if r != c:
                f = Mx[r][c]
                Mx[r] = [a - f * bb for a, bb in zip(Mx[r], Mx[c])]
    return [r[n:] for r in Mx]


def ols_hac(y, X, L=12):
    """定数項は X の第1列に入れておく。係数と Newey-West の t（サンドイッチ）"""
    n, k = len(y), len(X[0])
    XtX = [[math.fsum(r[i] * r[j] for r in X) for j in range(k)] for i in range(k)]
    Xi = inv(XtX)
    Xty = [math.fsum(r[i] * yy for r, yy in zip(X, y)) for i in range(k)]
    bta = [math.fsum(Xi[i][j] * Xty[j] for j in range(k)) for i in range(k)]
    e = [yy - math.fsum(bb * xx for bb, xx in zip(bta, r)) for r, yy in zip(X, y)]
    g = [[r[i] * ee for i in range(k)] for r, ee in zip(X, e)]
    S_ = [[math.fsum(gg[i] * gg[j] for gg in g) for j in range(k)] for i in range(k)]
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        for i in range(k):
            for j in range(k):
                c = math.fsum(g[t][i] * g[t - l][j] + g[t - l][i] * g[t][j] for t in range(l, n))
                S_[i][j] += w * c
    V = [[math.fsum(Xi[i][a] * S_[a][b] * Xi[b][j] for a in range(k) for b in range(k)) for j in range(k)] for i in range(k)]
    return bta, [bta[i] / math.sqrt(V[i][i]) if V[i][i] > 0 else None for i in range(k)]


def holm(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m, run, out = len(it), 0.0, {}
    for i, (v, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 4)
    return out


# ───────────── データ（取得は M.get、読み取りは自前） ─────────────
def jkp_size(char, grp):
    u = f'https://jkpfactors-data.s3.amazonaws.com/public/factor/%5Busa%5D_%5B{char}%5D_%5B{grp}%5D.zip'
    b = M.get(u, name=f'jkp_size_usa_{char}_{grp}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    r, n = {}, {}
    for row in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if row['ret'] in ('', 'NA', 'na'):
            continue
        ym = int(row['date'][:4]) * 100 + int(row['date'][5:7])
        n[ym] = int(row['n'])
        r[ym] = float(row['ret'])
    return r, n


def directions():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jkp_factor_details.xlsx'), read_only=True)
    rows = list(wb['details'].iter_rows(values_only=True))
    h = rows[0]
    ia, idr = h.index('abr_jkp'), h.index('direction')
    return {r[ia]: int(r[idr]) for r in rows[1:] if r[ia] and r[idr] is not None}


def jkp_vw_signed(region):
    """JKP all_factors（vw・予言の向き済み）。国は n_stocks_min≥10 の月だけ（researcher と同じ最低限のふるい）"""
    out = {}
    for x in M.jkp_rows(region, 'all_factors', 'factor', 'vw'):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        if x.get('n_stocks_min') not in (None, '', 'NA') and int(float(x['n_stocks_min'])) < 10:
            continue
        if x.get('n_countries') not in (None, '', 'NA') and int(float(x['n_countries'])) < 3:
            continue
        out.setdefault(x['name'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    return out


def french_vw(name):
    """French の portfolio ファイルの最初の Value Weight 月次表 → {列: {ym: 小数}}（自前でたどる）"""
    for t, v in M.french_tables(name).items():
        if 'value weight' in t.lower() and v['freq'] == 'monthly':
            out = {c: {} for c in v['cols']}
            for d, row in v['data'].items():
                for c, x in zip(v['cols'], row):
                    if x is not None:
                        out[c][d] = x / 100
            return out
    raise KeyError(name)


def french_table(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            return v
    raise KeyError(name + ' ' + want)


# ───────────── 組み立て ─────────────
def tilt(mkt, ls, lam, cost_annual=0.0):
    ks = [k for k in sorted(set(mkt) & set(ls)) if k <= JKP_END]
    s = {k: mkt[k] + lam * ls[k] - cost_annual / 12 for k in ks}
    b = {k: mkt[k] for k in ks}
    return s, b


def grade_from(c):
    ok = lambda k: c.get(k) is True
    na = lambda k: c.get(k) is None or c.get(k) is True
    base = ok('C1') and ok('C2') and ok('C6')
    if base and ok('C3') and ok('C4') and ok('C7') and na('C5'):
        return 'S'
    if base and ok('C4') and ok('C7') and (ok('C3') or ok('C5')):
        return 'A'
    if base:
        return 'B'
    return 'C'


def main():
    ff = M.ff_factors()
    mkt, mktrf, rf = ff['mkt'], ff['mktrf'], ff['rf']
    dx = directions()
    i49 = french_vw('49_Industry_Portfolios')
    grp = {'tech': ['Hardw', 'Softw', 'Chips'], 'fin': ['Banks', 'Insur', 'Fin', 'RlEst'], 'energy': ['Oil', 'Coal'], 'health': ['Hlth', 'MedEq', 'Drugs'], 'util': ['Util']}
    global IND
    IND = {g: {k: mean([i49[c][k] for c in cs]) for k in i49[cs[0]] if all(k in i49[c] for c in cs)} for g, cs in grp.items()}
    vwu = jkp_vw_signed('usa')
    out = {'angle': 'mega_tilt', 'verifier': 'night/mw_mega_tilt_verify.py', 'benchmark': 'French Mkt = Mkt-RF + RF（上限なしの時価加重）',
           'method_notes': [
               'LS は JKP の規模別 CMP（mega＝NYSE 80%点超の中で順位加重・買い1/売り1・ret_exc_lead1m）。JKP の作成コード portfolios.R 278-296行で自分でも確認（weight = (p_rank−mean)/(Σ|dev|/2)）。向きは Factor Details.xlsx の direction を掛け、JKP 公開の vw 符号つき因子との相関が正であることで独立に確かめた',
               's = French Mkt + λ×LS − 費用/12、b = French Mkt。LS は自己資金ゼロ（買い−売り）なので総リターンと超過を混ぜていない。超過 s−b は λ×LS そのもの＝ t 値は λ によらない',
               'n（mega の銘柄数）≥ 50 の月だけ（研究側と同じ）。統計（NW t ラグ12・CAGR・転がる窓・積立・Holm）はすべて自前実装']}
    # ── 程度の確認: JKP 'vw' 市場（超過）+ RF と French Mkt
    jm = {}
    for x in M.jkp_rows('usa', 'mkt', 'factor', 'vw'):
        if x['ret'] not in ('', 'NA', 'na'):
            jm[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    ks = [k for k in sorted(set(jm) & set(mktrf)) if k >= 200701]
    out['benchmark_check'] = {'jkp_vw_mkt_minus_french_mktrf_2007_pct_yr': round(mean([jm[k] - mktrf[k] for k in ks]) * 1200, 2),
                              'note': 'French Mkt は純粋な時価加重。JKP の vw_cap（上限つき）や ew は相手に使っていない'}
    # ── LS を作る（mega と large）
    LS, LSL, NM = {}, {}, {}
    sign_chk = {}
    for c in ALL14:
        r, n = jkp_size(c, 'mega')
        d = dx[c]
        LS[c] = {k: v * d for k, v in r.items() if n[k] >= 50}
        NM[c] = n
        kk = sorted(set(LS[c]) & set(vwu.get(c, {})))
        sign_chk[c] = round(corr([LS[c][k] for k in kk], [vwu[c][k] for k in kk]), 3) if kk else None
    for c in CANDS:
        try:
            r, n = jkp_size(c, 'large')
            LSL[c] = {k: v * dx[c] for k, v in r.items() if n[k] >= 50}
        except Exception as e:  # noqa
            LSL[c] = None
            print('large 取得失敗', c, e)
    out['direction_check_corr_mega_signed_vs_jkp_vw_signed'] = sign_chk
    out['directions_used'] = {c: dx[c] for c in ALL14}
    # ── 族 P（34本）の保有期間 p を自分で作り直す（Holm 用）
    pP = {}
    for c in ALL14:
        s, b = tilt(mkt, LS[c], LAM)
        st = stats(s, b, a=200701)
        pP['PA_' + c] = st['p'] if st else None
        if c in vwu:
            s2, b2 = tilt(mkt, {k: v for k, v in vwu[c].items()}, LAM)
            st2 = stats(s2, b2, a=200701)
            pP['PB_' + c] = st2['p'] if st2 else None
    # 混合 Q5 / QM / QMV（mega・vw）も族に入っていたので作る
    Q = ['gp_at', 'ope_be', 'qmj', 'qmj_prof', 'cop_at']

    def mix(src, parts, w):
        ks = set(src[parts[0]])
        for p in parts[1:]:
            ks &= set(src[p])
        return {k: sum(wi * src[p][k] for wi, p in zip(w, parts)) for k in ks}
    for tag, src in (('PA_', LS), ('PB_', vwu)):
        for nm, parts, w in (('Q5', Q, [0.2] * 5), ('QM', Q + ['ret_12_1'], [0.1] * 5 + [0.5]),
                             ('QMV', Q + ['ret_12_1', 'be_me'], [1 / 15] * 5 + [1 / 3, 1 / 3])):
            ls = mix(src, parts, w)
            s, b = tilt(mkt, ls, LAM)
            st = stats(s, b, a=200701)
            pP[tag + nm] = st['p'] if st else None
    holmP = holm(pP)
    out['family_P_holdout_p_recomputed'] = {k: pP[k] for k in sorted(pP)}
    out['family_P_holm_recomputed'] = holmP
    # 研究側の試した数（角度の中）とプログラム全体
    res = json.load(open(os.path.join(BASE, 'out', 'mw_mega_tilt.json')))
    n_angle = len(res['tested'])
    n_prog = 0
    per_angle = {}
    for f in glob.glob(os.path.join(BASE, 'out', 'mw_*.json')):
        bn = os.path.basename(f)
        if 'prereg' in bn or 'verify' in bn or bn == 'mw_prereg.json':
            continue
        try:
            j = json.load(open(f))
        except Exception:  # noqa
            continue
        t = j.get('tested')
        if isinstance(t, list):
            per_angle[bn] = len(t)
            n_prog += len(t)
    out['multiple_testing_counts'] = {'angle_mega_tilt_tested': n_angle, 'program_mw_tested_total_so_far': n_prog, 'per_file': per_angle}
    # ── 実行可能性（買いだけ）: 研究側の λ_feas を自前で近似（最小の mega 銘柄＝NYSE 80%点が、最も悪い順位の売り重み 4λ/n を持つ）
    try:
        bp = M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/ME_Breakpoints_CSV.zip', name='fr_ME_Breakpoints.zip')
        z = zipfile.ZipFile(io.BytesIO(bp))
        p80 = {}
        for line in z.read(z.namelist()[0]).decode('latin-1').splitlines():
            c = [x.strip() for x in line.split(',')]
            if c and c[0].isdigit() and len(c[0]) == 6 and len(c) >= 22:
                p80[int(c[0])] = float(c[17])
        nt = french_table('Portfolios_Formed_on_ME', 'Number of Firms')
        try:
            at = french_table('Portfolios_Formed_on_ME', 'Average Firm Size')
        except KeyError:
            at = french_table('Portfolios_Formed_on_ME', 'Average Market Cap')
        cols = ['Lo 30', 'Med 40', 'Hi 30']
        ix = [nt['cols'].index(c) for c in cols]
        ia = [at['cols'].index(c) for c in cols]
        tot = {}
        for d in nt['data']:
            if d in at['data']:
                rn, ra = nt['data'][d], at['data'][d]
                if all(rn[i] is not None for i in ix) and all(ra[i] is not None for i in ia):
                    tot[d] = sum(rn[i] * ra[j] for i, j in zip(ix, ia))
        bound = {}
        for ym, n in NM['ret_12_1'].items():
            pm = ym - 1 if ym % 100 != 1 else ym - 89
            if n >= 50 and pm in p80 and ym in tot:
                # 最も悪い順位の重みは ≈ −λ×0.5/(n/8) = −4λ/n。これが時価の重み p80/tot を超えない最大の λ
                bound[ym] = p80[pm] / tot[ym] * n / 4
        tr = sorted(v for k, v in bound.items() if k <= 200612)
        ho = sorted(v for k, v in bound.items() if k >= 200701)
        out['feasibility_check'] = {'lambda_longonly_worstcase_train_median': round(tr[len(tr) // 2], 4),
                                    'lambda_longonly_worstcase_hold_median': round(ho[len(ho) // 2], 4),
                                    'note': 'λ=0.2 は順位加重の売り側の重みが最小の mega 銘柄の時価の重みを約4〜5倍上回る＝買いだけでは作れない（研究側の λ_feas=0.04 と一致）'}
    except Exception as e:  # noqa
        out['feasibility_check'] = {'error': str(e)}
    # ── 米国外（国だけ8つ）の 2007〜（JKP vw 三分位・向き済み）
    intl = {r: jkp_vw_signed(r) for r in COUNTRIES}
    # ── French の独立の作り方（時価加重・BIG/ME5）の近い形
    FRN = {'ope_be': [('25_Portfolios_ME_OP_5x5', 'BIG HiOP', 'BIG LoOP'), ('6_Portfolios_ME_OP_2x3', 'BIG HiOP', 'BIG LoOP')],
           'oaccruals_at': [('25_Portfolios_ME_AC_5x5', 'BIG LoAC', 'BIG HiAC')],
           'chcsho_12m': [('25_Portfolios_ME_NI_5x5', 'BIG NegNI', 'BIG HiNI')],
           'ret_12_1': [('25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR'), ('6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR')]}
    frcache = {}

    def fr_ls(name, g, bcol):
        if name not in frcache:
            frcache[name] = french_vw(name)
        v = frcache[name]
        gcol = [c for c in v if c.replace(' ', '') == g.replace(' ', '')][0]
        bc = [c for c in v if c.replace(' ', '') == bcol.replace(' ', '')][0]
        return {k: v[gcol][k] - v[bc][k] for k in v[gcol] if k in v[bc]}

    claimed = {r['name']: r for r in res['tested']}
    V = {}
    for c in CANDS:
        ls = LS[c]
        rec = {'claimed_grade': CLAIMED_GRADE[c]}
        s, b = tilt(mkt, ls, LAM)
        sn, _ = tilt(mkt, ls, LAM, TURN[c] * LAM * 2 * 0.001)
        rec['full'] = stats(s, b)
        rec['train'] = stats(s, b, z=200612)
        rec['hold'] = stats(s, b, a=200701)
        rec['hold_net_cost'] = stats(sn, b, a=200701)
        rec['roll20_net'] = roll(sn, b)
        rec['dca20_net'] = dca20(sn, b)
        # 研究側との一致
        cr = claimed.get('PA_mega_' + c, {})
        rec['match_researcher'] = {k: [(cr.get(k2) or {}).get('ex_ann'), (cr.get(k2) or {}).get('t'), rec[k]['ex_ann'] if rec[k] else None, rec[k]['t'] if rec[k] else None]
                                   for k, k2 in (('full', 'full'), ('train', 'train'), ('hold', 'hold'), ('hold_net_cost', 'net_cost_hold'))}
        rec['match_researcher']['roll20'] = [(cr.get('roll20_net') or {}).get('win_rate'), (rec['roll20_net'] or {}).get('win_rate')]
        # ── 反証の検査
        chk = {}
        # 訓練の t の丸め
        chk['train_t_unrounded'] = rec['train']['t']
        # Compustat 以前（1963-07 より前は Compustat の後付けで生き残りの偏りが強い）を除いた訓練
        chk['train_1963_07_2006'] = stats(s, b, a=196307, z=200612)
        # 保有期間の前半・後半
        chk['hold_2007_2016H1'] = stats(s, b, a=200701, z=201606)
        chk['hold_2016H2_2025'] = stats(s, b, a=201607)
        chk['hold_ex_2008_2009'] = stats(s, b, a=200701, drop=lambda k: 200801 <= k <= 200912)
        chk['hold_ex_2020_2021'] = stats(s, b, a=200701, drop=lambda k: 202001 <= k <= 202112)
        chk['full_ex_1998_2000_and_2020_2021'] = stats(s, b, drop=lambda k: 199801 <= k <= 200012 or 202001 <= k <= 202112)
        chk['recent_2013_07'] = stats(s, b, a=201307)
        if c in PUB:
            chk['post_publication'] = stats(s, b, a=(PUB[c] + 1) * 100 + 1)
            chk['pub_year'] = PUB[c]
        # 保有期間だけの転がる10年窓
        chk['roll10_within_hold_net'] = roll(sn, b, years=10, a=200701)
        # 暦年の勝ち
        yrs = {}
        for k in sorted(s):
            if 200701 <= k <= JKP_END:
                a_ = yrs.setdefault(k // 100, [1.0, 1.0]); a_[0] *= 1 + s[k]; a_[1] *= 1 + b[k]
        diffs = {y: (v[0] - v[1]) * 100 for y, v in yrs.items()}
        chk['hold_calendar_years_won'] = f"{sum(1 for v in diffs.values() if v > 0)}/{len(diffs)}"
        best = max(diffs, key=diffs.get)
        chk['hold_best_year'] = [best, round(diffs[best], 2)]
        chk['hold_ex_best_year'] = stats(s, b, a=200701, drop=lambda k, y=best: k // 100 == y)
        # 費用の現実性: 回転率3倍 × 片道 0.3%（中小型並み／日本の個人の米国株手数料 0.495% に近い）
        s9, _ = tilt(mkt, ls, LAM, TURN[c] * 3 * LAM * 2 * 0.003)
        chk['hold_net_cost_turnover3x_cost0.3pct'] = stats(s9, b, a=200701)
        s8, _ = tilt(mkt, ls, LAM, TURN[c] * 3 * LAM * 2 * 0.001)
        chk['hold_net_cost_turnover3x_cost0.1pct'] = stats(s8, b, a=200701)
        # 業種への依存: 保有期間の λ×LS を Mkt-RF と業種の対市場スプレッド（テック・金融・エネルギー・ヘルスケア・公益）で回帰した切片
        hk = [k for k in sorted(ls) if 200701 <= k <= JKP_END and k in mktrf and all(k in IND[g] for g in IND)]
        y = [LAM * ls[k] for k in hk]
        X = [[1.0, mktrf[k]] + [IND[g][k] - mkt[k] for g in IND] for k in hk]
        bt, tt = ols_hac(y, X)
        chk['hold_industry_adjusted'] = {'alpha_ann': round(bt[0] * 1200, 3), 't_alpha': round(tt[0], 3),
                                         'loadings': {n_: [round(bt[i + 2], 3), round(tt[i + 2], 2)] for i, n_ in enumerate(IND)},
                                         'beta_mktrf': [round(bt[1], 3), round(tt[1], 2)], 'months': len(hk)}
        s_jp, _ = tilt(mkt, ls, LAM, TURN[c] * 3 * LAM * 2 * 0.00495)
        chk['hold_net_cost_turnover3x_cost0.495pct'] = stats(s_jp, b, a=200701)
        # 買いだけの大きさ λ=0.04
        s4, b4 = tilt(mkt, ls, 0.04, TURN[c] * 0.04 * 2 * 0.001)
        chk['hold_longonly_lambda0.04_net'] = stats(s4, b4, a=200701)
        # 近い作り方: large（NYSE 50〜80%点）、JKP vw 三分位（全規模・時価加重）、French（BIG・時価加重）
        if LSL.get(c):
            sl, bl = tilt(mkt, LSL[c], LAM)
            chk['neighbor_large'] = {'train': stats(sl, bl, z=200612), 'hold': stats(sl, bl, a=200701)}
        if c in vwu:
            sv, bv = tilt(mkt, vwu[c], LAM)
            chk['neighbor_jkp_vw_tercile'] = {'train': stats(sv, bv, z=200612), 'hold': stats(sv, bv, a=200701)}
        for (fname, g, bc) in FRN.get(c, []):
            fl = fr_ls(fname, g, bc)
            sf, bf = tilt(mkt, fl, LAM)
            chk[f'neighbor_french_{fname}'] = {'train': stats(sf, bf, z=200612), 'hold': stats(sf, bf, a=200701)}
        # 米国外（国だけ8つ）の 2007〜 と全期間
        per = {}
        for reg in COUNTRIES:
            ser = intl[reg].get(c)
            if not ser:
                continue
            hk = [k for k in sorted(ser) if 200701 <= k <= JKP_END]
            fk = [k for k in sorted(ser) if k <= JKP_END]
            cst = TURN[c] * LAM * 2 * 0.001 / 12
            per[reg] = {'full_net_ex': round(mean([LAM * ser[k] - cst for k in fk]) * 1200, 2),
                        'hold_net_ex': round(mean([LAM * ser[k] - cst for k in hk]) * 1200, 2) if len(hk) >= 24 else None,
                        'hold_t': (lambda t: round(t, 2) if t is not None else None)(nwt([ser[k] for k in hk])) if len(hk) >= 24 else None}
        chk['intl_countries'] = per
        chk['intl_countries_positive_full'] = f"{sum(1 for v in per.values() if v['full_net_ex'] > 0)}/{len(per)}"
        chk['intl_countries_positive_hold'] = f"{sum(1 for v in per.values() if (v['hold_net_ex'] or 0) > 0)}/{len(per)}"
        chk['intl_countries_hold_t_ge_1.65'] = f"{sum(1 for v in per.values() if (v['hold_t'] or 0) >= 1.65)}/{len(per)}"
        # 多重検定
        hp = rec['hold']['p']
        chk['holdout_p'] = hp
        chk['holdout_holm_in_family_P34_recomputed'] = holmP.get('PA_' + c)
        chk['holdout_bonferroni_angle'] = round(min(1.0, hp * n_angle), 4)
        chk['holdout_bonferroni_program'] = round(min(1.0, hp * n_prog), 4)
        fp = rec['full']['p']
        chk['full_p'] = fp
        chk['full_bonferroni_angle'] = round(min(1.0, (fp or 0) * n_angle), 5)
        rec['checks'] = chk
        # ── 線の再計算（研究側の C5 は研究側の値をそのまま＝10地域の全期間）
        rp = (cr.get('repl') or {})
        c5 = (rp.get('positive', 0) / rp['regions'] >= 2 / 3) if rp.get('regions') else None
        C = {'C1': rec['train']['ex_ann'] > 0 and rec['train']['t'] >= 2.0,
             'C2': rec['hold']['ex_ann'] > 0 and rec['hold']['cagr_diff'] > 0,
             'C3': rec['hold']['t'] >= 1.65,
             'C4': (rec['roll20_net'] or {}).get('win_rate', 0) >= 0.8,
             'C5': c5,
             'C6': rec['hold_net_cost']['ex_ann'] > 0 and rec['hold_net_cost']['cagr_diff'] > 0,
             'C7': (rec['full']['t'] >= 3.0) or ((holmP.get('PA_' + c) or 1) < 0.05)}
        rec['criteria_reproduced'] = C
        rec['grade_reproduced_mechanical'] = grade_from(C)
        # 1963-07 以降の訓練なら C1 は？
        t63 = chk['train_1963_07_2006']
        C63 = dict(C)
        C63['C1'] = t63['ex_ann'] > 0 and t63['t'] >= 2.0
        f63 = stats(s, b, a=196307)
        C63['C7'] = (f63['t'] >= 3.0) or ((holmP.get('PA_' + c) or 1) < 0.05)
        rec['checks']['full_from_1963_07'] = f63
        rec['grade_if_train_from_1963_07'] = grade_from(C63)
        # C7 を保有期間の多重検定だけで見たら（全期間 t は訓練＝文献の標本内が 3/4 を占める）
        Ch = dict(C)
        Ch['C7'] = (holmP.get('PA_' + c) or 1) < 0.05
        rec['grade_if_C7_by_holdout_holm_only'] = grade_from(Ch)
        V[c] = rec
        print(c, rec['grade_reproduced_mechanical'], 'full', rec['full']['ex_ann'], rec['full']['t'], 'train', rec['train']['ex_ann'], rec['train']['t'],
              'hold', rec['hold']['ex_ann'], rec['hold']['t'], rec['hold']['cagr_diff'], 'net', rec['hold_net_cost']['ex_ann'],
              'roll', rec['roll20_net']['win_rate'], 't63', t63['t'], 'g63', rec['grade_if_train_from_1963_07'], 'holm', holmP.get('PA_' + c))
    out['candidates'] = V
    # ── 補足: 主の族 P の残りの S/A（研究側の要約の見出し PB_vw_cop_at を含む）を同じ検査で
    MIX = {'Q5': (Q, [0.2] * 5), 'QM': (Q + ['ret_12_1'], [0.1] * 5 + [0.5]), 'QMV': (Q + ['ret_12_1', 'be_me'], [1 / 15] * 5 + [1 / 3, 1 / 3])}
    TO_MIX = {'Q5': 0.4, 'QM': 0.5 * 0.4 + 0.5 * 1.5, 'QMV': (0.4 + 1.5 + 0.4) / 3}
    PUB_MIX = {'Q5': 2018, 'QM': 2018, 'QMV': 2018}
    supp = {}
    for r in res['tested']:
        if r.get('family') != 'P' or r.get('grade') not in ('S', 'A'):
            continue
        nm = r['name']
        tag, base = nm[:3], nm.split('_', 2)[2]
        if tag == 'PA_' and base in CANDS:
            continue
        src = LS if tag == 'PA_' else vwu
        ls = mix(src, *MIX[base]) if base in MIX else src.get(base)
        if not ls:
            continue
        to = TO_MIX.get(base, TURN.get(base, 0.8))
        pub = PUB_MIX.get(base, PUB.get(base))
        s, b = tilt(mkt, ls, LAM)
        sn, _ = tilt(mkt, ls, LAM, to * LAM * 2 * 0.001)
        s9, _ = tilt(mkt, ls, LAM, to * 3 * LAM * 2 * 0.003)
        hold = stats(s, b, a=200701)
        yrs = {}
        for k in sorted(s):
            if 200701 <= k <= JKP_END:
                a_ = yrs.setdefault(k // 100, [1.0, 1.0]); a_[0] *= 1 + s[k]; a_[1] *= 1 + b[k]
        best = max(yrs, key=lambda y: yrs[y][0] - yrs[y][1])
        hk = [k for k in sorted(ls) if 200701 <= k <= JKP_END and k in mktrf and all(k in IND[g] for g in IND)]
        bt, tt = ols_hac([LAM * ls[k] for k in hk], [[1.0, mktrf[k]] + [IND[g][k] - mkt[k] for g in IND] for k in hk])
        fr = stats(s, b)
        tr63 = stats(s, b, a=196307, z=200612)
        rec = {'claimed_grade': r['grade'], 'full': fr, 'train': stats(s, b, z=200612), 'train_1963_07_2006': tr63, 'hold': hold,
               'hold_net_cost': stats(sn, b, a=200701), 'roll20_net': (roll(sn, b) or {}).get('win_rate'),
               'hold_2007_2016H1': stats(s, b, a=200701, z=201606), 'hold_2016H2_2025': stats(s, b, a=201607),
               'hold_ex_2008_2009': stats(s, b, a=200701, drop=lambda k: 200801 <= k <= 200912),
               'hold_ex_best_year': [best, stats(s, b, a=200701, drop=lambda k, y=best: k // 100 == y)],
               'hold_net_cost_turnover3x_cost0.3pct': stats(s9, b, a=200701),
               'post_publication': stats(s, b, a=(pub + 1) * 100 + 1) if pub else None, 'pub_year': pub,
               'hold_industry_adjusted_alpha': [round(bt[0] * 1200, 3), round(tt[0], 3)], 'fin_loading': [round(bt[3], 3), round(tt[3], 2)],
               'holdout_holm_P34': holmP.get(tag + base), 'matches_researcher_hold': [r['hold']['ex_ann'], r['hold']['t'], hold['ex_ann'], hold['t']]}
        supp[nm] = rec
        print('supp', nm, r['grade'], 'hold', hold['ex_ann'], hold['t'], 'tr63', tr63['t'] if tr63 else None, 'exbest', rec['hold_ex_best_year'][1]['t'],
              'ind', rec['hold_industry_adjusted_alpha'], 'post', (rec['post_publication'] or {}).get('ex_ann'), (rec['post_publication'] or {}).get('t'),
              'c3x', rec['hold_net_cost_turnover3x_cost0.3pct']['ex_ann'], 'h1/h2', rec['hold_2007_2016H1']['t'], rec['hold_2016H2_2025']['t'])
    out['supplementary_other_P_S_A'] = supp
    return out


VERDICTS = {  # 数字を見たあとに書いた判定（機械の線の再計算は candidates[*].grade_reproduced_mechanical）
    'PA_mega_cop_at': {'verdict': 'confirmed', 'verified_grade': 'S',
        'why': '数字は完全に再現（保有 +0.95%/年 t2.37・全期間 t5.54・20年窓 54/54）。1963年7月以降の訓練 t4.15・2008-09除外 t2.13・2020-21除外 t2.09・最良年(2020)除外 t2.14・回転3倍×0.3% +0.81 t2.01・隣の large t3.25・vw t3.27・公表後(2017〜) +1.08 t1.97・業種調整後も +0.40 t2.33 で崩れない。★ただし大きさ: 保有期間の超過の約6割は業種（金融を売り t−9.9・テック/ヘルスケアを買い）で、業種調整後は +0.40%/年。λ=0.2 は買いだけでは作れず（売りが要る）、買いだけの上限 λ≈0.04 では +0.19%/年（業種調整後なら約 +0.08%/年）。保有期間だけの多重検定（族34本の Holm 0.50・角度204本）は越えない＝C7 は全期間 t で通っている'},
    'PA_mega_qmj': {'verdict': 'downgraded to A', 'verified_grade': 'A',
        'why': '基本の数字は再現（保有 +0.76 t1.98）が、C3（t≥1.65）が揺らぐ: 最良年(2011)除外 t1.64・回転3倍×0.3% t1.61・隣の large +0.41 t1.09・前後半 t1.52/1.33。公表後(2019〜) +0.44 t0.81＝本当の標本外では有意でない。登録前に CLAUDE.md が mega の qmj の2007〜の結果（+3.8 t2.0）を記録しており、保有期間の符号を知った上で選ばれている。C5（米国外 10/10・国8/8 が保有期間でも正）と C7（全期間 t3.66・1963〜 t3.23）は残るので A'},
    'PA_mega_qmj_prof': {'verdict': 'downgraded to A', 'verified_grade': 'A',
        'why': '保有 t1.83 は線の0.18上で、ほぼどの揺さぶりでも割れる: 2008-09除外 t1.60・2020-21除外 t1.64・最良年除外 t1.50・回転3倍×0.3% t1.48・隣の large t1.58・業種調整後 +0.32 t1.66（金融を売る負荷 t−10.5）。公表後(2019〜) +0.29 t0.48。qmj・gp_at とほぼ同じ信号で独立でない。C5・C7（全期間 t3.52）は残るので A'},
    'PA_mega_chcsho_12m': {'verdict': 'downgraded to B', 'verified_grade': 'B',
        'why': '米国 mega の保有期間は +0.24%/年 t0.58＝統計的にゼロ。19年中10年しか勝たず、最良年(2022)を除くと超過は 0.00。回転3倍×0.3% で −0.05、日本の個人の米国株手数料(0.495%)並みなら −0.24。独立の作り方も保有期間はゼロ（JKP vw +0.13 t0.25・French ME5 NI +0.26 t0.34）。A は訓練期間（CRSP 1927〜）と米国外（全規模 vw）で取っており、2007年以降の米国大型株で市場に勝った証拠ではない。C2/C6 が基本費用でかろうじて正なので B（C に近い）'},
    'PA_mega_oaccruals_at': {'verdict': 'downgraded to B', 'verified_grade': 'B',
        'why': '保有 +0.47 t1.51 だが、暦年で勝ったのは19年中8年（半分未満）・後半(2016H2〜) +0.21 t0.50・2008-09除外 t1.00・最良年(2020)除外 t0.95・業種調整後 +0.21 t0.99・French ME5 AC の保有 +0.38 t0.72・日本の個人の費用なら約0。平均は2008-09と2020の数か月に乗っている。訓練(1963〜 t3.83)と米国外(国8/8)は強いが、2007年以降の米国大型株の勝ちとしては弱い＝B'},
    'PA_mega_ret_12_1': {'verdict': 'downgraded to B', 'verified_grade': 'B',
        'why': '保有 +0.50 t0.85・最良年(2007)除外 +0.29 t0.51・業種調整後 t0.52。回転率 1.5/年/脚 の仮定は 12-1 勢いとしては低すぎ（文献の月次見直しは年3〜5回）、回転3倍×0.3% で −0.04、日本の個人の費用で −0.39。独立の作り方の保有期間は French 2x3 BIG +0.10 t0.12・JKP vw +0.15 t0.21。A は1927〜2006年と米国外で取ったもの＝B'},
    'PA_mega_gp_at': {'verdict': 'downgraded to C', 'verified_grade': 'C',
        'why': 'C1 の訓練 t は 2.001（線を 0.001 上回るだけ）。Compustat の後付け（生き残りの偏り）が強い1963年6月以前を除くと t1.66 で C1 不合格、JKP vw の同じ特徴でも訓練 t1.83（研究側の PB_vw_gp_at も C1 で C）。C7 も不合格（全期間 t2.65）。保有期間の後半 +0.48 t0.65・公表後(2014〜) +0.62 t1.02・業種調整後 +0.29 t1.51。しかも mega の GP/A の2007〜の結果は登録前に CLAUDE.md に記録済み＝後知恵'},
    'PA_mega_ope_be': {'verdict': 'downgraded to C', 'verified_grade': 'C',
        'why': '1963年7月以降の訓練 t1.66 で C1 不合格（研究側の D5 自身が同じ数字を出している）。独立の作り方（French 時価加重）でも訓練 t は ME5 0.85・2x3 BIG 1.40 で C1 に届かない＝2006年の投資家には選べなかった特徴。保有期間は +0.63 t2.07・業種調整後 +0.66 t2.48 と悪くないが、公表後(2016〜) +0.40 t0.89・隣の large t1.16・後半 t1.05。C7 不合格（全期間 t2.91）。登録前に保有期間の符号が CLAUDE.md に記録済み'},
    'PB_vw_cop_at（補足・研究側の要約の見出し）': {'verdict': 'confirmed', 'verified_grade': 'S',
        'why': '主張リストには無いが要約の見出しなので同じ検査を当てた: 保有 +1.50 t3.27 を再現・1963〜の訓練 t3.19・最良年除外 t2.89・前後半 t2.20/2.47・業種調整後 +0.75 t4.03・公表後(2017〜) +1.74 t2.80・回転3倍×0.3% +1.36。族の Holm 0.037 で保有期間だけでも多重検定を越える唯一の本。ただし λ=0.2 は買いだけでは作れず、研究側の買いだけの見込み λ≈0.11 で約 +0.8%/年、業種調整後はその約半分'},
}
SUMMARY_JA = [
    '8本（mega 順位加重 λ=0.2）の数字は自前の組み立て・統計で全部再現した（差は丸めの範囲）。相手は純粋な時価加重（French Mkt）で、超過と総リターンの混同・信号の時期ずれは見つからない。',
    '確定: cop_at だけが S のまま（1963〜の訓練・業種調整・最良年除外・費用3倍・隣の large/vw・公表後 t1.97 のどれでも崩れない）。ただし業種調整後は +0.40%/年、買いだけの λ≈0.04 では +0.19%/年しか無い。',
    '格下げ: qmj・qmj_prof は S→A（保有 t が最良年除外・費用3倍・隣の large・公表後でほぼ全部 1.65 を割る）。chcsho_12m・oaccruals_at・ret_12_1 は A→B（米国大型株の2007〜は t0.6〜1.5・最良年を除くとほぼゼロ・現実の費用で消える）。',
    'gp_at・ope_be は B→C: 訓練 t が Compustat の後付けが強い1963年以前を除くと 1.66 で C1 不合格（gp_at はもともと t2.001 で線上）。French の独立の作り方でも ope_be の訓練 t は 0.85/1.40。',
    '共通の弱点: 保有期間だけの多重検定（族34本の Holm）を越えるのは mega では0本（最良 cop_at 0.50）。質の特徴の多くは2007年以降の標本で論文になり、mega の2007〜の結果は登録前に CLAUDE.md にあった＝保有期間は完全な標本外ではない。',
    '補足: 研究側の見出し PB_vw_cop_at（時価加重三分位）は S を確認（保有 t3.27・業種調整後 t4.03・公表後 t2.80・Holm 0.037）。勝ちの芯は「現金ベースの営業利益÷総資産への小さな傾け」1本で、大きさは買いだけで年 +0.2〜0.8% 程度。',
]


def finalize(out):
    V = out['candidates']
    ver = {}
    for c, r in V.items():
        ch = r['checks']
        issues = []
        if r['claimed_grade'] != r['grade_reproduced_mechanical']:
            issues.append(f"機械的な線の再計算で格が {r['claimed_grade']}→{r['grade_reproduced_mechanical']}")
        if ch['holdout_holm_in_family_P34_recomputed'] >= 0.05:
            issues.append(f"保有期間 p={ch['holdout_p']} は族34本の Holm で {ch['holdout_holm_in_family_P34_recomputed']}（角度{out['multiple_testing_counts']['angle_mega_tilt_tested']}本の Bonferroni {ch['holdout_bonferroni_angle']}）＝保有期間だけでは多重検定を越えない。C7 は全期間 t（訓練＝文献の標本内が約3/4）で通っている")
        if r['grade_if_train_from_1963_07'] != r['grade_reproduced_mechanical']:
            issues.append(f"Compustat の後付けが強い1963年6月以前を除くと訓練 t={ch['train_1963_07_2006']['t']} → 格 {r['grade_if_train_from_1963_07']}")
        pp = ch.get('post_publication')
        if pp and PUB.get(c, 0) >= 2007:
            issues.append(f"論文の標本が保有期間に重なる（公表{PUB[c]}）。公表後だけ（{pp['from']}〜）は {pp['ex_ann']:+.2f}%/年 t{pp['t']}")
        h1, h2 = ch['hold_2007_2016H1'], ch['hold_2016H2_2025']
        if h1['t'] < 1.65 or h2['t'] < 1.65:
            issues.append(f"保有期間の前半 {h1['ex_ann']:+.2f}(t{h1['t']})・後半 {h2['ex_ann']:+.2f}(t{h2['t']})")
        l4 = ch['hold_longonly_lambda0.04_net']
        issues.append(f"λ=0.2 は買いだけでは作れない（売りが要る・日本の個人口座では米国株の空売りは実質不可）。買いだけの上限 λ≈0.04 では保有期間 {l4['ex_ann']:+.2f}%/年")
        nl = ch.get('neighbor_large')
        if nl and nl['hold']['t'] is not None and nl['hold']['t'] < 1.65:
            issues.append(f"隣の銘柄群 large（NYSE 50〜80%点）では保有期間 {nl['hold']['ex_ann']:+.2f} t{nl['hold']['t']}")
        ver[c] = issues
    out['issues_auto'] = ver
    out['verdicts_written_after_seeing_numbers'] = VERDICTS
    out['summary_ja'] = SUMMARY_JA
    return out


if __name__ == '__main__':
    o = main()
    o = finalize(o)
    p = os.path.join(BASE, 'out', 'mw_mega_tilt_verify.json')
    json.dump(o, open(p, 'w'), ensure_ascii=False, indent=1)
    print('書いた', p)
