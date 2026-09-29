#!/usr/bin/env python3
"""night/nx_lse_validate.py — LSE（IMM・1869〜1929）の読み込みの妥当性だけを裁く（規則の成績は計算しない・門の判定には不使用）

事前登録: out/nx_lse_validate_prereg.json（この道具より前に書いた）。
nx_pre1926x で止まる条件（LSE の等分とイングランド銀行の Smith-Horne の月次の相関 ≥0.6）が 0.4827 で発火し、
LSE を使う11単位（B 3・D 8）が PENDING_stop になった。その保留を、事前に決めた別の検査で決着させる:

  決着（decision）: LSE の等分（登録の lse_ew）を暦年の対数の変化に束ね、JST R6 の英国の eq_capgain
  （1871〜1907 = Grossman 2002・1916〜1929 = Barclays 大型30社）と同じ年どうしの Pearson の相関が
  P1・P2 の両方で ≥0.80、同じ年の相関が1年ずらした相関より大きい、年数が足りる——を
  『登録の版』と『CGT の読みの規則を足した版（cgt_clean）』の両方で満たせば『妥当』、1つでも欠ければ『検定不能』。
  線は事前登録の decision.thresholds_for_tool から読む（この道具には書かない）。

約束
- 規則の組み立て（build_*）・超過・t・シャープ・grade_era を呼ばない。out/nx_pre1926x.json は読むだけ。
- 最初に事前登録の inputs_frozen の sha256 を確かめ、1つでも違えば止まる。
- 登録の版を自分の組み立て（旗をすべて切った版）で1ビットも違わずに再現できることを確かめ、違えば止まる。
- 欠測は0で埋めない（年の12か月が1つでも無い年は使わない）。
出力: out/nx_lse_validate.json
"""
import sys, os, re, json, math, hashlib, collections, statistics, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402
import nx_pre1926x_data as D  # noqa: E402

BASE = C.BASE
PRE_PATH = os.path.join(BASE, 'out', 'nx_lse_validate_prereg.json')
PRE = json.load(open(PRE_PATH))
TH = PRE['decision']['thresholds_for_tool']
OUT = 'nx_lse_validate.json'
PENDING = PRE['parent']['pending_units']
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def sha256(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


# ═════════════════════════ 0. 凍結の確認 ═════════════════════════
def check_frozen():
    fz = PRE['inputs_frozen']
    cache = C.CACHE
    want = {
        'nx_pre1926x_data.py': (os.path.join(BASE, 'night', 'nx_pre1926x_data.py'), fz['nx_pre1926x_data.py']),
        'yale_lse_Railways_new.csv.zip': (os.path.join(cache, 'yale_lse_Railways_new.csv.zip'), fz['yale_lse_Railways_new.csv.zip']),
        'yale_lse_Banks_new.csv.zip': (os.path.join(cache, 'yale_lse_Banks_new.csv.zip'), fz['yale_lse_Banks_new.csv.zip']),
        'yale_lse_Misc_new.csv.zip': (os.path.join(cache, 'yale_lse_Misc_new.csv.zip'), fz['yale_lse_Misc_new.csv.zip']),
        'boe_millennium.xlsx': (os.path.join(cache, 'boe_millennium.xlsx'), fz['boe_millennium.xlsx']),
        'jst_R6.xlsx': (os.path.join(cache, 'jst_R6.xlsx'), fz['jst_R6.xlsx']),
        'nx_jst_series.json': (os.path.join(cache, 'nx_jst_series.json'), [v for k, v in fz.items() if k.startswith('nx_jst_series.json')][0]),
        'out/nx_pre1926x.json': (os.path.join(BASE, 'out', 'nx_pre1926x.json'), fz['out/nx_pre1926x.json']),
    }
    got = {k: sha256(p) for k, (p, _) in want.items()}
    ok = {k: got[k] == w for k, (_, w) in want.items()}
    ext_key = [k for k in fz if k.startswith('extract_sha256')][0]
    res = {'files': {k: {'sha256': got[k], 'ok': ok[k]} for k in want}, 'extract_sha256_expected': fz[ext_key]}
    if not all(ok.values()):
        print(json.dumps(res, ensure_ascii=False, indent=1))
        raise SystemExit('凍結の確認に失敗（事前登録の sha と違う）→ 止まる')
    return res


FROZEN = check_frozen()
# nx_pre1926x を import すると、その凍結の確認（extract・rules・data 道具の sha と selftest）が走り、登録の BENCH['lse_ew'] が得られる。
# 規則の組み立て・成績の関数は呼ばない（main() は __main__ のときだけ）
import nx_pre1926x as M  # noqa: E402

if M.FROZEN['got']['extract_sha256'] != FROZEN['extract_sha256_expected']:
    raise SystemExit('extract の sha が事前登録と違う → 止まる')
LSE_EW_REG = M.BENCH['lse_ew']
SEG_M = M.LSE_SEG_M


# ═════════════════════════ 1. 注記の読み（cgt_clean の c1〜c5・事前登録 panels.cgt_clean） ═════════════════════════
DISC_PREM = {'d', 'dis', 'ds', 'dx', 'p', 'pm', 'xp'}
CAPITAL_EVENT = {'xr', 'r', 'xb', 'b', 'xn', 'n', 'xc'}
UNREAD_TOKENS = {'a', 'l', '7', 'x2', 'x3'}


def note_info(v10):
    s = (v10 or '').split('|')[0].replace('Ã\x82Â£', '£').lower().strip()
    toks = [t.rstrip('.') for t in re.split(r'[;\s,]+', s) if t.strip()]
    toks = [t for t in toks if t]
    return {
        'c2': bool(set(toks) & DISC_PREM),
        'c3': bool(set(toks) & CAPITAL_EVENT),
        'dollar': '$' in s,
        'pound': '£' in s,
        'c5': ('?' in s) or ('unreadable' in s) or s in ('...', '..') or bool(set(toks) & UNREAD_TOKENS),
    }


def build_panel(drop=frozenset(), tag=False):
    """D.lse_panel の組み立て（nx_pre1926x.lse_panel_variant と同じ手順）に、drop の類（c1〜c5）の対を落とす旗を足した写し。
    drop が空なら登録の版（抽出と1ビットも違わないことを main で確かめる）。tag=True なら残ったリターンごとに当たった類を返す"""
    obj = D.lse_raw()
    raw, heads = obj['sec'], obj['headings']
    cnt = collections.Counter()
    ret, tags = {}, {}
    for i, rec in raw.items():
        if not D.lse_is_common(rec):
            continue
        Mo = rec['m']
        ks = sorted(k for k in Mo if Mo[k][0])
        if not ks:
            continue
        r, tg = {}, {}
        for a, b in zip(ks, ks[1:]):
            va, vb = Mo[a], Mo[b]
            if D.madd(a, 1) != b:
                continue
            sa = D.lse_sector(rec['file'], heads[va[9]])
            if sa == 'EXCLUDE':
                continue
            if (va[1] and vb[1] and va[1] != vb[1]) or (va[3] and vb[3] and va[3] != vb[3]) or (va[6] and vb[6] and va[6] != vb[6]):
                continue
            na, nb = note_info(va[10]), note_info(vb[10])
            hits = set()
            if va[2] and vb[2] and va[2] != vb[2]:
                hits.add('c1')
            if na['c2'] or nb['c2']:
                hits.add('c2')
            if na['c3'] or nb['c3']:
                hits.add('c3')
            if na['dollar'] != nb['dollar'] or na['pound'] != nb['pound']:
                hits.add('c4')
            if na['c5'] or nb['c5']:
                hits.add('c5')
            if hits & drop:
                for h in sorted(hits & drop):
                    cnt['drop_' + h] += 1
                cnt['drop_pairs_any'] += 1
                continue
            r[b] = vb[0] / va[0] - 1
            if tag and hits:
                tg[b] = hits
        r = D.clean_returns(r, cnt)
        if not r:
            continue
        ret[i] = r
        if tag:
            tags[i] = {k: v for k, v in tg.items() if k in r}
    return {'ret': ret, 'tags': tags, 'counts': dict(cnt)}


# ═════════════════════════ 2. 集計（等分・年・ずれの相関） ═════════════════════════
def ew(R):
    out = {}
    for ms in SEG_M:
        out.update(D.build_ew_universe(R, ms))
    return out


def month_counts(R):
    c = collections.Counter()
    for r in R.values():
        for k in r:
            c[k] += 1
    return c


def annual_log(mon, counts=None, min_n=0, years=None):
    """{ym: r} → {y: Σ ln(1+r)}。その年の12か月が1つでも無い（または株数が min_n 未満の月がある）年は使わない"""
    ys = sorted({k // 100 for k in mon}) if years is None else years
    out = {}
    for y in ys:
        ms = [y * 100 + m for m in range(1, 13)]
        if all(k in mon for k in ms) and (counts is None or all(counts.get(k, 0) >= min_n for k in ms)):
            out[y] = math.fsum(math.log1p(mon[k]) for k in ms)
    return out


def corr_pairs(a, b, keys):
    keys = [k for k in keys if k in a and k in b]
    if len(keys) < 3:
        return None, len(keys)
    return C.corr([a[k] for k in keys], [b[k] for k in keys]), len(keys)


def lag_corrs(L, J, yrs):
    """同じ期間の年の中だけで: lag k の相関 = corr(L[y], J[y+k])（y と y+k の両方が期間の中にあり、両方の値がある年）"""
    Ys = set(yrs)
    out = {}
    for k in (-1, 0, 1):
        ys = [y for y in yrs if y in L and (y + k) in Ys and (y + k) in J]
        if len(ys) < 3:
            out[k] = (None, len(ys))
            continue
        out[k] = (C.corr([L[y] for y in ys], [J[y + k] for y in ys]), len(ys))
    return out


def spearman(x, y):
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for t in range(i, j + 1):
                r[o[t]] = (i + j) / 2 + 1
            i = j + 1
        return r
    return C.corr(rk(x), rk(y))


def fisher_ci(r, n, z90=1.6448536269514722):
    if r is None or n < 4 or abs(r) >= 1:
        return None
    z = math.atanh(r)
    se = 1 / math.sqrt(n - 3)
    return [round(math.tanh(z - z90 * se), 3), round(math.tanh(z + z90 * se), 3)]


def monthly_idx_ret(level):
    ks = sorted(level)
    return {b: level[b] / level[a] - 1 for a, b in zip(ks, ks[1:]) if D.madd(a, 1) == b}


def monthly_lags(x, y, a, z):
    """x_t と y_{t+k}（k=−1,0,+1）の月次の相関。月は a〜z で両方あるもの"""
    out = {}
    for k in (-1, 0, 1):
        ks = [m for m in sorted(x) if a <= m <= z and D.madd(m, k) in y]
        out[k] = (round(C.corr([x[m] for m in ks], [y[D.madd(m, k)] for m in ks]), 4) if len(ks) > 3 else None, len(ks))
    s = sum(v[0] for v in out.values() if v[0] is not None)
    return {'lag_-1': out[-1], 'lag_0': out[0], 'lag_+1': out[1], 'sum_-1_0_+1': round(s, 4)}


def r4(x):
    return None if x is None else round(x, 4)


# ═════════════════════════ 3. 自己検査（合成データ） ═════════════════════════
def selftest():
    res = []
    # 年の束ね: 12か月の対数の和・1か月欠けたら使わない
    mon = {189001 + i: 0.01 for i in range(12)}
    a = annual_log(mon)
    res.append(('annual_sum', abs(a[1890] - 12 * math.log1p(0.01)) < 1e-12))
    mon2 = dict(mon)
    mon2.pop(189006)
    res.append(('annual_drop_incomplete', annual_log(mon2) == {}))
    # 株数の下限
    res.append(('annual_min_n', annual_log(mon, counts={k: 50 for k in mon}, min_n=100) == {}))
    # ずれの相関: J が L を1年遅らせたものなら lag +1 が 1.0、lag 0 は小さい
    import random
    rnd = random.Random(7)
    yrs = list(range(1871, 1908))
    L = {y: rnd.gauss(0, 0.1) for y in yrs}
    J = {y + 1: v for y, v in L.items()}
    lc = lag_corrs(L, J, yrs)
    res.append(('lag_detects_shift', abs(lc[1][0] - 1) < 1e-9 and abs(lc[0][0]) < 0.6))
    J0 = dict(L)
    lc0 = lag_corrs(L, J0, yrs)
    res.append(('lag0_identity', abs(lc0[0][0] - 1) < 1e-9 and lc0[0][0] > max(lc0[-1][0], lc0[1][0])))
    # 注記の読み
    res.append(('note_disc', note_info('dis.|')['c2'] and note_info('x; d|')['c2'] and not note_info('x|xd')['c2']))
    res.append(('note_rights', note_info('x; r|')['c3'] and note_info('xb|')['c3'] and not note_info('x|')['c3']))
    res.append(('note_currency', note_info('Ã\x82Â£; x|')['pound'] and note_info('$|')['dollar'] and not note_info('|$')['dollar']))
    res.append(('note_unread', note_info('...|')['c5'] and note_info('?|')['c5'] and note_info('then unreadable|')['c5'] and not note_info('x|...')['c5']))
    res.append(('note_freetext_kept', not any(note_info('x; Calculated at 6 per cent.|')[k] for k in ('c2', 'c3', 'c5'))))
    # Spearman
    res.append(('spearman', abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-12 and abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-12))
    return res


# ═════════════════════════ 4. 決着の検査 ═════════════════════════
def jst_gbr():
    d = json.load(open(os.path.join(C.CACHE, 'nx_jst_series.json')))['data']['GBR']
    raw = {int(y): r.get('eq_capgain') for y, r in d.items() if isinstance(r.get('eq_capgain'), float)}
    med = statistics.median(abs(v) for v in raw.values())
    if med > 0.5:
        raise SystemExit(f'JST eq_capgain の単位が小数でない（|中央| {med}）→ 止まる')
    return {y: math.log1p(v) for y, v in raw.items()}, raw


def decide_panel(name, L, J):
    p1 = list(range(TH['P1_years'][0], TH['P1_years'][1] + 1))
    p2 = list(range(TH['P2_years'][0], TH['P2_years'][1] + 1))
    out = {'panel': name}
    for tag, yrs, thr, nmin in (('P1', p1, TH['V1_min_corr'], TH['V4_min_years_P1']), ('P2', p2, TH['V2_min_corr'], TH['V4_min_years_P2'])):
        lc = lag_corrs(L, J, yrs)
        r0, n0 = lc[0]
        ys = [y for y in yrs if y in L and y in J]
        sp = spearman([L[y] for y in ys], [J[y] for y in ys]) if len(ys) > 3 else None
        timing_ok = (r0 is not None and all(lc[k][0] is None or r0 > lc[k][0] for k in (-1, 1)))
        out[tag] = {'years': [ys[0], ys[-1]] if ys else None, 'n': n0, 'corr': r4(r0),
                    'corr_unrounded': r0, 'min_corr': thr, 'corr_ok': (r0 is not None and r0 >= thr),
                    'lag_-1': [r4(lc[-1][0]), lc[-1][1]], 'lag_+1': [r4(lc[1][0]), lc[1][1]], 'timing_ok': timing_ok,
                    'n_ok': n0 >= nmin, 'min_years': nmin, 'fisher90': fisher_ci(r0, n0), 'spearman': r4(sp),
                    'years_dropped': [y for y in yrs if y not in L]}
    out['V1'] = out['P1']['corr_ok']
    out['V2'] = out['P2']['corr_ok']
    out['V3'] = out['P1']['timing_ok'] and out['P2']['timing_ok']
    out['V4'] = out['P1']['n_ok'] and out['P2']['n_ok']
    out['pass'] = bool(out['V1'] and out['V2'] and out['V3'] and out['V4'])
    return out


# ═════════════════════════ 5. 報告（決着に使わない） ═════════════════════════
def dec_level(level, y):
    return level.get(y * 100 + 12)


def annual_from_dec(level, y0, y1):
    out = {}
    for y in range(y0, y1 + 1):
        a, b = dec_level(level, y - 1), dec_level(level, y)
        if a and b:
            out[y] = math.log(b / a)
    return out


def ew_subset(R, sect, keep, a, z, min_n):
    out = {}
    for ms in SEG_M:
        for m in ms:
            if not (a <= m <= z):
                continue
            v = [R[i][m] for i in R if m in R[i] and keep(D.sector_at(sect.get(i, []), m))]
            if len(v) >= min_n:
                out[m] = math.fsum(v) / len(v)
    return out


def vw(R, cap, a, z, min_n):
    out, nn = {}, {}
    for ms in SEG_M:
        for m in ms:
            if not (a <= m <= z):
                continue
            w = [(cap[i][m], R[i][m]) for i in R if m in R[i] and m in cap.get(i, {}) and cap[i][m] and cap[i][m] > 0]
            if len(w) >= min_n:
                s = math.fsum(c for c, _ in w)
                out[m] = math.fsum(c * r for c, r in w) / s
                nn[m] = len(w)
    return out, nn


def robust_annual(R, years):
    bh, med = {}, {}
    for y in years:
        ms = [y * 100 + m for m in range(1, 13)]
        g = [math.fsum(math.log1p(r[k]) for k in ms) for r in R.values() if all(k in r for k in ms)]
        if len(g) >= 100:
            bh[y] = math.log1p(statistics.fmean(math.exp(x) - 1 for x in g))
            med[y] = statistics.median(g)
    return bh, med


def reports(L_reg, J, panels, uk):
    rep = {}
    sh = uk[9]
    sh_m = monthly_idx_ret(sh)
    # R1 相手どうし
    sh_a = annual_from_dec(sh, 1871, 1913)
    rc, n = corr_pairs(sh_a, J, range(1871, 1914))
    bm = uk[12]
    bm_a = annual_from_dec(bm, 1897, 1906)
    rb, nb = corr_pairs(bm_a, J, range(1897, 1907))
    rbl, nbl = corr_pairs(bm_a, L_reg, range(1897, 1907))
    rep['R1_comparator_vs_comparator'] = {
        'smith_horne_vs_JST_1871_1913': {'corr': r4(rc), 'n': n},
        'bankers_magazine_col12_vs_JST_1897_1906': {'corr': r4(rb), 'n': nb},
        'bankers_magazine_col12_vs_lse_ew_registered_1897_1906': {'corr': r4(rbl), 'n': nbl}}
    # R2 元の相手を年次で（汚れあり）
    sh_a2 = annual_from_dec(sh, 1870, 1907)
    r2, n2 = corr_pairs(L_reg, sh_a2, range(1870, 1908))
    rep['R2_original_comparator_annual'] = {'lse_ew_registered_vs_smith_horne_1870_1907': {'corr': r4(r2), 'n': n2},
                                            'note': '★汚れ: 月次のずれの和 ≈0.86 を知った上で登録した（決着に使わない）'}
    # R3 工業株だけ（Smith-Horne が除いた5部門を抜く）
    excl = {'RAIL', 'BANK', 'INSURANCE', 'MINES', 'LAND_MORTGAGE_FIN'}
    ind = ew_subset(M.LSE_RET, M.LSE_SECT, lambda s: s is not None and s not in excl, 186902, 190712, 30)
    ind_a = annual_log(ind)
    ri, ni = corr_pairs(ind_a, sh_a2, range(1870, 1908))
    rep['R3_like_for_like_industrials'] = {
        'what': 'LSE の等分から RAIL・BANK・INSURANCE・MINES・LAND_MORTGAGE_FIN を抜いた株（t−1 の業種・月に30社以上）',
        'monthly_vs_smith_horne_1871_1907': monthly_lags(ind, sh_m, 187101, 190712),
        'registered_full_ew_monthly_vs_smith_horne_1871_1907': monthly_lags(L_monthly_reg(), sh_m, 187101, 190712),
        'annual_vs_smith_horne_1870_1907': {'corr': r4(ri), 'n': ni},
        'annual_vs_JST_1871_1907': dict(zip(('corr', 'n'), (lambda t: (r4(t[0]), t[1]))(corr_pairs(ind_a, J, range(1871, 1908)))))}
    # R4 時価加重（1870〜1887）
    vwm, vwn = vw(M.LSE_RET, M.LSE_CAP, 187001, 188712, 200)
    vwa = annual_log(vwm)
    rv, nv = corr_pairs(vwa, J, range(1871, 1888))
    rep['R4_value_weighted_1870_1887'] = {
        'months': len(vwm), 'stocks_per_month_median': statistics.median(vwn.values()) if vwn else None,
        'annual_vs_JST_1871_1887': {'corr': r4(rv), 'n': nv},
        'registered_ew_annual_vs_JST_1871_1887': dict(zip(('corr', 'n'), (lambda t: (r4(t[0]), t[1]))(corr_pairs(L_reg, J, range(1871, 1888))))),
        'monthly_vs_smith_horne_1871_1887': monthly_lags(vwm, sh_m, 187101, 188712)}
    # R5 頑丈な集計
    yrs = list(range(1871, 1908)) + list(range(1916, 1930))
    bh, med = robust_annual(M.LSE_RET, yrs)
    rep['R5_robust_aggregates'] = {}
    for nm, s in (('ew_buy_and_hold', bh), ('median_log', med)):
        rep['R5_robust_aggregates'][nm] = {p: dict(zip(('corr', 'n'), (lambda t: (r4(t[0]), t[1]))(corr_pairs(s, J, rg))))
                                           for p, rg in (('P1', range(1871, 1908)), ('P2', range(1916, 1930)))}
    # R7 P2 の月次
    L_m = L_monthly_reg()
    rep['R7_period2_monthly'] = {
        'col13_bankers_magazine_1915_03_1921_01': monthly_lags(L_m, monthly_idx_ret(uk[13]), 191503, 192101),
        'col14_morgan_20th_1915_03_1925_03': monthly_lags(L_m, monthly_idx_ret(uk[14]), 191503, 192503),
        'col17_bm_variable_dividend_1922_01_1929_12': monthly_lags(L_m, monthly_idx_ret(uk[17]), 192201, 192912)}
    # R8 古い気配
    zc, tc = collections.Counter(), collections.Counter()
    for r in M.LSE_RET.values():
        for k, v in r.items():
            tc[k // 100] += 1
            if v == 0.0:
                zc[k // 100] += 1
    big_z = big_t = oth_z = oth_t = 0
    for m in sorted({k for r in M.LSE_RET.values() for k in r if 187001 <= k <= 188712}):
        w = [(M.LSE_CAP[i][m], M.LSE_RET[i][m]) for i in M.LSE_RET if m in M.LSE_RET[i] and m in M.LSE_CAP.get(i, {}) and M.LSE_CAP[i][m]]
        w.sort(key=lambda t: -t[0])
        for j, (_, v) in enumerate(w):
            if j < 50:
                big_t += 1; big_z += (v == 0.0)
            else:
                oth_t += 1; oth_z += (v == 0.0)
    rep['R8_staleness'] = {'zero_share_by_year': {y: round(zc[y] / tc[y], 3) for y in sorted(tc)},
                           'zero_share_all': round(sum(zc.values()) / sum(tc.values()), 4),
                           'top50_by_cap_1870_1887': {'zero_share': round(big_z / big_t, 4) if big_t else None, 'n': big_t},
                           'others_with_cap_1870_1887': {'zero_share': round(oth_z / oth_t, 4) if oth_t else None, 'n': oth_t},
                           'expectation_prereg': '大型株の値動き0の割合は 15% 未満'}
    return rep


def L_monthly_reg():
    return LSE_EW_REG


# ═════════════════════════ 6. 決着の後の格付けの写し ═════════════════════════
ORDER = {'S': 4, 'A': 3, 'B': 2, 'C': 1}


def grades_after(valid):
    res = json.load(open(os.path.join(BASE, 'out', 'nx_pre1926x.json')))
    tested = {t['id']: t for t in res['tested']}
    table = res.get('provisional_grade_table_B_D', {})
    units = {}
    for u in PENDING:
        t = tested[u]
        if t.get('grade') != 'PENDING_stop':
            raise SystemExit(f'{u} の主の格付けが PENDING_stop でない（{t.get("grade")}）→ 止まる')
        reg = t['grade_provisional_if_lse_reading_ok']
        var = table.get(u, {})
        vg = [g for g in var.values() if g in ORDER]
        floor = min(vg, key=lambda g: ORDER[g]) if vg else None
        units[u] = {'final_grade': reg if valid else '検定不能',
                    'registered_provisional': reg,
                    'reading_variants_from_nx_pre1926x': var,
                    'floor_across_computed_variants': floor,
                    'flag': 'resolved_by_post_hoc_validation' if valid else 'unverifiable_data'}
    # 規則のまとめ（格付けの文字列だけから・nx_pre1926x_data.rule_verdict）
    verdicts = {}
    for key, v in res['rule_level_verdicts'].items():
        gs = {}
        for uid, g in v['units'].items():
            gs[uid] = units[uid]['final_grade'] if uid in units else g
        verdicts[key] = {'units': gs, 'verdict': D.rule_verdict(list(gs.values())),
                         'verdict_before（主・保留を数えない）': v['verdict']}
        if valid:
            fl = {uid: (units[uid]['floor_across_computed_variants'] if uid in units else g) for uid, g in v['units'].items()}
            verdicts[key]['verdict_with_variant_floor（参考）'] = D.rule_verdict(list(fl.values()))
    counts = collections.Counter(u['final_grade'] for u in units.values())
    return units, verdicts, dict(counts)


# ═════════════════════════ 7. 本体 ═════════════════════════
def main():
    t0 = datetime.datetime.now()
    out = {'angle': 'nx_lse_validate', 'prereg': 'out/nx_lse_validate_prereg.json',
           'prereg_sha256_at_run': sha256(PRE_PATH),
           'prereg_mtime_utc': datetime.datetime.utcfromtimestamp(os.path.getmtime(PRE_PATH)).isoformat() + 'Z',
           'tool_sha256_at_run': sha256(os.path.abspath(__file__)),
           'run_started_utc': datetime.datetime.utcnow().isoformat() + 'Z',
           'frozen_check': FROZEN, 'nx_pre1926x_frozen_check': {'sha_match': M.FROZEN['sha_match'], 'selftest_all_ok': M.FROZEN['selftest_all_ok']}}
    st = selftest()
    out['selftest'] = {k: v for k, v in st}
    if not all(v for _, v in st):
        print(out['selftest'])
        raise SystemExit('selftest が FAIL → 止まる')
    log('selftest OK', len(st))

    # 登録の版を1ビット再現
    reg = build_panel(frozenset(), tag=True)
    same = (set(reg['ret']) == set(M.LSE_RET) and all(reg['ret'][i] == M.LSE_RET[i] for i in reg['ret']))
    out['registered_reproduced_bit_exact'] = same
    if not same:
        raise SystemExit('登録の版を再現できない → 止まる')
    ew_reg_again = ew(reg['ret'])
    if ew_reg_again != LSE_EW_REG:
        raise SystemExit('登録の lse_ew を再現できない → 止まる')
    log('registered panel reproduced bit-exact')
    clean = build_panel(frozenset({'c1', 'c2', 'c3', 'c4', 'c5'}))
    par = build_panel(frozenset({'c1'}))
    # 額面だけの版が nx_pre1926x.lse_panel_variant(par=True) と一致するか（写しの点検）
    pv = M.lse_panel_variant(par=True)
    out['par_only_matches_nx_pre1926x_variant'] = (set(pv['ret']) == set(par['ret']) and all(pv['ret'][i] == par['ret'][i] for i in par['ret']))

    J, Jraw = jst_gbr()
    panels = {}
    for name, P in (('registered', reg), ('cgt_clean', clean), ('par_only', par)):
        mon = LSE_EW_REG if name == 'registered' else ew(P['ret'])
        cnts = month_counts(P['ret'])
        L = annual_log(mon, counts=cnts, min_n=TH['min_stocks_per_month'])
        panels[name] = {'mon': mon, 'L': L, 'counts': cnts, 'ret': P['ret']}

    dec = {name: decide_panel(name, panels[name]['L'], J) for name in ('registered', 'cgt_clean')}
    par_stats = decide_panel('par_only', panels['par_only']['L'], J)
    valid = dec['registered']['pass'] and dec['cgt_clean']['pass']
    verdict = '妥当' if valid else '検定不能'
    out['decision'] = {'rule': PRE['decision']['rule'], 'thresholds': TH, 'by_panel': dec, 'valid': valid, 'verdict': verdict}
    for nm, d in dec.items():
        log(nm, 'P1', d['P1']['corr'], d['P1']['n'], 'lag', d['P1']['lag_-1'], d['P1']['lag_+1'],
            '| P2', d['P2']['corr'], d['P2']['n'], 'lag', d['P2']['lag_-1'], d['P2']['lag_+1'], '| pass', d['pass'])
    log('DECISION:', verdict)

    # 報告
    uk, desc = D.uk_share_prices()
    rep = reports(panels['registered']['L'], J, panels, uk)
    rep['R6_other_panels'] = {'par_only': par_stats}
    # R9 欠陥の数（登録の版）
    tc = collections.Counter()
    big = collections.Counter()
    tot = sum(len(r) for r in reg['ret'].values())
    for i, tg in reg['tags'].items():
        for k, hs in tg.items():
            for h in hs:
                tc[h] += 1
                if abs(reg['ret'][i][k]) > 1.0:
                    big[h] += 1
            tc['any'] += 1
            if abs(reg['ret'][i][k]) > 1.0:
                big['any'] += 1
    rep['R9_defect_counts_registered'] = {'stock_months_total': tot,
                                          'by_class': {h: {'n': tc[h], 'abs_r_gt_100pct': big[h], 'share_of_all': round(tc[h] / tot, 5)} for h in ('c1', 'c2', 'c3', 'c4', 'c5', 'any')},
                                          'clean_build_counts': clean['counts'], 'par_build_counts': par['counts'],
                                          'stock_months_clean': sum(len(r) for r in clean['ret'].values())}
    # R10 登録 対 clean
    mr, mc = panels['registered']['mon'], panels['cgt_clean']['mon']
    ks = sorted(set(mr) & set(mc))
    r10 = {'monthly_corr_all': r4(C.corr([mr[k] for k in ks], [mc[k] for k in ks])), 'n': len(ks), 'arith_mean_x12_pct': {}}
    for a, z in ((186902, 188712), (188801, 190712), (191502, 192912)):
        kk = [k for k in ks if a <= k <= z]
        r10['arith_mean_x12_pct'][f'{a}-{z}'] = {'registered': round(statistics.fmean(mr[k] for k in kk) * 1200, 2),
                                                 'cgt_clean': round(statistics.fmean(mc[k] for k in kk) * 1200, 2)}
    rep['R10_registered_vs_clean'] = r10
    # R11 は decision.by_panel の fisher90・spearman
    rep['R11_ci'] = {nm: {p: {'corr': d[p]['corr'], 'fisher90': d[p]['fisher90'], 'spearman': d[p]['spearman']} for p in ('P1', 'P2')} for nm, d in dec.items()}
    # 年ごとの系列（読み返しのため）
    rep['annual_series'] = {
        'years': sorted(set(panels['registered']['L']) | set(J)),
        'lse_ew_registered_log': {y: round(v, 5) for y, v in sorted(panels['registered']['L'].items())},
        'lse_ew_cgt_clean_log': {y: round(v, 5) for y, v in sorted(panels['cgt_clean']['L'].items())},
        'jst_gbr_log1p_eq_capgain': {y: round(v, 5) for y, v in sorted(J.items()) if 1870 <= y <= 1930}}
    out['reports_not_decisive'] = rep

    units, verdicts, counts = grades_after(valid)
    out['grades_after_decision'] = {'units': units, 'grade_counts_11': counts, 'rule_level_verdicts': verdicts,
                                    'note': (PRE['grades_after_decision']['if_valid'] if valid else PRE['grades_after_decision']['if_unverifiable']),
                                    'summary_rule': PRE['grades_after_decision']['summary_rule']}
    out['runtime_sec'] = round((datetime.datetime.now() - t0).total_seconds(), 1)
    out['log'] = LOG
    return out


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        for k, v in selftest():
            print(k, 'OK' if v else 'FAIL')
        sys.exit(0)
    res = main()
    p = C.save(OUT, res)
    print('saved', p)
