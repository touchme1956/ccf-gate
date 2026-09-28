#!/usr/bin/env python3
"""night/mw_own_exposure.py — 角度 own_exposure（読むだけ・記述・門の判定・採点・配分には不使用）

問い: 今の配分（ETF側＝iFreeNEXT NASDAQ100 60 / SMH 20・個別20＝CW・MSFT・LRCX・ASML・TDG 等分）の
『市場に対する超過』は、検証済みの割増（質: Q＝JKP cop_at の良い側−市場・G＝門の写し P1−市場）に
どれだけ載っていて、どれだけが割増の検証されていない業種（と超大型・β）の賭けか。
1985-2006 と 2007-2025 で載りは安定か。城は NASDAQ100（と半導体）を持った上で質を足しているか。
castle_rule の相手は何がよいか。米ドルと円で。

事前登録: out/mw_own_exposure_prereg.json（系列・説明変数・式・窓・判断の規則は全部そこ）。
記述の角度なので格付けは結論に使わない（参考として mw_common.grade の結果を記録するだけ）。
結果 → out/mw_own_exposure.json
"""
import sys, os, io, csv, json, math, subprocess, datetime, time, urllib.request, http.cookiejar, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M
import numpy as np

BASE = M.BASE
ANGLE = 'own_exposure'
PREREG = 'out/mw_own_exposure_prereg.json'
OUT = 'mw_own_exposure.json'
HOLD_A, HOLD_Z = 200701, 202512
PREM_A, PREM_Z = 196307, 200612          # 割増 E[Q]・E[G] の窓
LONG_A, LONG_Z = 192607, 200612          # 業種・β・規模の長期平均（参考）
HAIRCUTS = (0.44, 0.50, 0.56)
CASTLE_NAMES = ['CW', 'MSFT', 'LRCX', 'ASML', 'TDG']
W_NET = {'NDX_TR': 0.75, 'SEMI': 0.25}
W_MIX = {'NDX_TR': 0.60, 'SEMI': 0.20, 'CASTLE': 0.20}
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


# ───────────────────────── データ ─────────────────────────
FF = M.ff_factors()
MKT, RF, MKTRF = FF['mkt'], FF['rf'], FF['mktrf']
FR_END = max(MKT)


def fr_monthly(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            return v
    raise KeyError(f'{name}: {want}')


def fr_cols(name, want, cols):
    v = fr_monthly(name, want)
    out = {}
    for c in cols:
        i = v['cols'].index(c)
        out[c] = {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None}
    return out


def yh(t):
    """Yahoo 月次（配当込みの調整後終値）。French の終わりより後（途中の月）は使わない"""
    return {k: v for k, v in M.yahoo(t).items() if k <= FR_END}


def splice(a, b, cut):
    """cut 以前は a・cut より後は b"""
    out = {k: v for k, v in a.items() if k <= cut}
    out.update({k: v for k, v in b.items() if k > cut})
    return out


def blend(parts):
    """{名前: (重み, 系列)} → 全部そろう月だけの加重（毎月組み直し）"""
    ks = set.intersection(*[set(s) for _, s in parts.values()])
    return {k: math.fsum(w * s[k] for w, s in parts.values()) for k in sorted(ks)}


def active(s, b):
    return {k: s[k] - b[k] for k in s if k in b}


def win(d, a=None, z=None):
    return {k: v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)}


def ann_mean(d, a=None, z=None):
    x = [v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)]
    if len(x) < 24:
        return None
    t = M.nw_t(x)
    return {'n': len(x), 'mean_ann': round(S.mean(x) * 1200, 3), 't_nw': round(t, 2) if t is not None else None}


# ───────────────────────── 回帰 ─────────────────────────
def ols_nw(Y, X, lag=12):
    n, k = X.shape
    XtXi = np.linalg.pinv(X.T @ X)
    b = XtXi @ X.T @ Y
    e = Y - X @ b
    u = X * e[:, None]
    Sm = u.T @ u
    for L in range(1, min(lag, n - 1) + 1):
        G = u[L:].T @ u[:-L]
        Sm = Sm + (1 - L / (lag + 1)) * (G + G.T)
    V = XtXi @ Sm @ XtXi
    se = np.sqrt(np.maximum(np.diag(V), 0))
    yc = Y - Y.mean()
    r2 = 1 - (e @ e) / (yc @ yc) if yc @ yc > 0 else None
    return b, se, r2


def reg(y, xs, a=None, z=None, groups=None):
    """y: {ym: v}・xs: [(名前, {ym: v})]。全部そろう月だけ（欠測は0にしない）。
    実現の分解: 平均y = α + Σ b_j·平均x_j（OLS の恒等式）を年率%で。groups={群名: [変数名]} で合計も"""
    ks = sorted(k for k in y if (a is None or k >= a) and (z is None or k <= z) and all(k in x for _, x in xs))
    need = max(36, len(xs) + 24)
    if len(ks) < need:
        return None
    Y = np.array([y[k] for k in ks])
    X = np.column_stack([np.ones(len(ks))] + [np.array([x[k] for k in ks]) for _, x in xs])
    b, se, r2 = ols_nw(Y, X)
    means = X.mean(axis=0)
    contrib = {nm: round(float(bb * mm) * 1200, 3) for (nm, _), bb, mm in zip(xs, b[1:], means[1:])}
    o = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'y_mean_ann': round(float(Y.mean()) * 1200, 3),
         'alpha_ann': round(float(b[0]) * 1200, 3), 'alpha_t': round(float(b[0] / se[0]), 2) if se[0] > 0 else None,
         'r2': round(float(r2), 3) if r2 is not None else None,
         'coef': {nm: [round(float(bb), 3), round(float(bb / s), 2) if s > 0 else None, round(float(s), 4)]
                  for (nm, _), bb, s in zip(xs, b[1:], se[1:])},
         'contrib_ann': contrib}
    if groups:
        o['contrib_group_ann'] = {g: round(sum(contrib[v] for v in vs if v in contrib), 3) for g, vs in groups.items()}
        o['contrib_group_ann']['alpha'] = o['alpha_ann']
    o['_b'] = [float(v) for v in b]  # 予測用（保存時に消す）
    o['_names'] = [nm for nm, _ in xs]
    return o


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not str(k).startswith('_')}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def phi(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


# ───────────────────────── 為替・投信 ─────────────────────────
def fx_monthly():
    b = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=3)
    lv, daily = {}, {}
    for row in csv.reader(io.StringIO(b.decode())):
        if not row or row[0].startswith('observation') or row[0] == 'DATE':
            continue
        try:
            v = float(row[1])
        except ValueError:
            continue  # '.'＝休日（0 にしない）
        d = int(row[0].replace('-', ''))
        daily[d] = v
        lv[d // 100] = v  # 月の最後の値で上書き
    ks = sorted(lv)
    r = {k: lv[k] / lv[p] - 1 for p, k in zip(ks, ks[1:]) if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}
    return r, lv, daily


def to_jpy(s, fxr):
    return {k: (1 + v) * (1 + fxr[k]) - 1 for k, v in s.items() if k in fxr}


def ifree_nav():
    """投資信託協会の CSV（基準価額・分配金）。User-Agent は mw_common のもの（メールを載せない）"""
    p = os.path.join(M.CACHE, 'ifree_ndx_nav.csv')
    if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < 3 * 86400 and os.path.getsize(p) > 1000):
        base = 'https://toushin-lib.fwg.ne.jp'
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        op.addheaders = [('User-Agent', M.UA['User-Agent'])]
        op.open(base + '/FdsWeb/FDST000000', timeout=60).read()
        b = op.open(base + '/FdsWeb/FDST030000/csv-file-download?isinCd=JP90C000GUN2&associFundCd=04317188', timeout=90).read()
        os.makedirs(M.CACHE, exist_ok=True)
        open(p, 'wb').write(b)
    txt = open(p, 'rb').read().decode('cp932', errors='replace')
    rows = []
    for r in csv.reader(io.StringIO(txt)):
        if not r or not r[0][:4].isdigit():
            continue
        d = int(r[0][0:4]) * 10000 + int(r[0][5:7]) * 100 + int(r[0][8:10])
        nav = float(r[1]) if r[1].strip() else None
        dist = float(r[3]) if len(r) > 3 and r[3].strip() else 0.0
        if nav is not None:
            rows.append((d, nav, dist))
    rows.sort()
    me, dist_m = {}, {}
    for d, nav, dist in rows:
        me[d // 100] = (d, nav)
        dist_m[d // 100] = dist_m.get(d // 100, 0.0) + dist
    ks = sorted(me)
    ret = {k: (me[k][1] + dist_m.get(k, 0.0)) / me[p][1] - 1 for p, k in zip(ks, ks[1:])
           if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}
    return {k: v for k, v in ret.items() if k <= FR_END}, me, rows


# ───────────────────────── 事後（結果を見た後に足した記述・格付けなし） ─────────────────────────
def posthoc(V, attr, IND12, IND12X, ME10a, CH49, raw, X_MKT):
    o = {'label': '事後（結果を見た後に足した記述。事前登録の外・判断の材料にだけ使う）'}
    # (1) 業種の長期平均は算術。ぶれの大きい業種は算術の超過が年率の差（CAGR）より大きく出る
    lr = {}
    I12tot = {c: {k: v + MKT[k] for k, v in s.items() if k in MKT} for c, s in IND12.items()}
    for c in list(I12tot) + ['Hardw', 'Softw', 'Chips', 'LabEq']:
        tot = I12tot[c] if c in I12tot else CH49[c]
        for wn, (a, z) in {'1926-07..2006-12': (LONG_A, LONG_Z), '1965-01..2006-12': (196501, LONG_Z), '1926-07..2026-08': (LONG_A, FR_END)}.items():
            es = M.excess_stats(tot, MKT, a, z)
            lr.setdefault(c, {})[wn] = {'arith_ex_ann': es['ex_ann'], 'cagr_diff': es['cagr_diff'], 't': es['t']}
    o['industry_longrun_arith_vs_cagr'] = lr
    o['industry_longrun_note'] = ('(b) の「業種の長期平均×載り」は算術の平均で数えた。ぶれの大きい業種（BusEq・Chips）は算術の超過が年率の差より'
                                  '大きく出る（分散の差の半分ほど）。複利で効くのは年率の差のほう')
    # (2) 2026 の業種だけの予測を 49業種の技術4本（IND12x）で
    xs = X_MKT + [(c, s) for c, s in IND12X.items()] + [('ME10a', ME10a)]
    ind26x = {}
    for vn in ['NDX_TR', 'SEMI', 'NET', 'MIX', 'CASTLE5']:
        y = active(V[vn], MKT)
        r = reg(y, xs, HOLD_A, HOLD_Z)
        rows = [(k, y[k], math.fsum(b * x[k] for b, (_, x) in zip(r['_b'][1:], xs))) for k in sorted(y)
                if k > HOLD_Z and all(k in x for _, x in xs)]
        if rows:
            ind26x[vn] = {'hold_r2': r['r2'], 'realized_sum_pct': round(sum(v for _, v, _ in rows) * 100, 2),
                          'pred_no_alpha_sum_pct': round(sum(p for _, _, p in rows) * 100, 2),
                          'corr_month': round(M.corr([v for _, v, _ in rows], [p for _, _, p in rows]), 3)}
    o['ind2026_with_IND12x'] = ind26x
    # (3) 城の追従のぶれの床: CASTLE5 を Mkt・NDX_TR・SEMI の総リターンへ回帰した残差（手元の ETF で作れる最良の線形の相手）
    c5 = V['CASTLE5']
    parts = [('Mkt', MKT), ('NDX_TR', V['NDX_TR']), ('SEMI', V['SEMI'])]
    def fit(a, z):
        ks = [k for k in sorted(c5) if a <= k <= z and all(k in s for _, s in parts)]
        Y = np.array([c5[k] for k in ks]); X = np.column_stack([np.array([s[k] for k in ks]) for _, s in parts])
        b = np.linalg.lstsq(X, Y, rcond=None)[0]
        return b, ks
    b_all, ks = fit(200604, FR_END)
    res = [c5[k] - sum(float(bb) * s[k] for bb, (_, s) in zip(b_all, parts)) for k in ks]
    o['castle_te_floor_in_sample'] = {'weights': {nm: round(float(bb), 3) for bb, (nm, _) in zip(b_all, parts)}, 'from': ks[0], 'to': ks[-1],
                                      'te': round(S.stdev(res) * math.sqrt(12) * 100, 2),
                                      'years_for_t2_at_3pt': round((2 * S.stdev(res) * math.sqrt(12) * 100 / 3) ** 2, 1),
                                      'note': '同じ期間で推定した重み（後知恵の当てはめ）＝どの相手を選んでもぶれはこれより下がらない目安'}
    b1, _ = fit(200604, 201512)
    ks2 = [k for k in sorted(c5) if 201601 <= k <= FR_END and all(k in s for _, s in parts)]
    res2 = [c5[k] - sum(float(bb) * s[k] for bb, (_, s) in zip(b1, parts)) for k in ks2]
    o['castle_te_floor_out_of_sample'] = {'weights_2006_2015': {nm: round(float(bb), 3) for bb, (nm, _) in zip(b1, parts)},
                                          'applied': [ks2[0], ks2[-1]], 'te': round(S.stdev(res2) * math.sqrt(12) * 100, 2)}
    # 同じ 2016〜 の NET の TE（比較）
    d3 = [c5[k] - V['NET'][k] for k in ks2 if k in V['NET']]
    o['castle_te_vs_NET_2016_on'] = round(S.stdev(d3) * math.sqrt(12) * 100, 2)
    return o


def summary(o):
    A, B, C, D = o['attribution'], o['b_expected'], o['c_castle_incremental'], o['d_castle_benchmark']
    pr, P, J, I = o['b_premia'], o['post_hoc_事後'], o['jpy'], o['oos']['ifree_nav']
    net_h, net_t = A['NET']['A4_ind']['hold'], A['NET']['A4_ind']['train']
    q5n = o['a_stability']['NET']['A5q']['Q']; q5x = o['a_stability']['NDX_TR']['A5q']['Q']
    bn = B['NET']['hold']
    cq = C['CASTLE5']['C_NETq']['hold']['coef']['Q']; cg = C['CASTLE5']['C_NETg']['hold']['coef']['G']
    c4 = A['CASTLE5']['A4_ind']['hold']
    te = D['decision']['te_usd_all']; nt = D['USD']['all_200604_202608']['NET']
    L = []
    L.append(f"ETF側（iFreeNEXT NASDAQ100 60 / SMH 20＝NASDAQ100 75%・半導体25%）は 2007〜2025 に市場（French の時価加重≒S&P500）より年 {net_h['y_mean_ann']:+.1f}%（算術）上だった。"
             f"そのうち業種（ほぼ技術=BusEq）だけで {net_h['contrib_group_ann']['industry']:+.1f}%／年を説明できる（R² {net_h['r2']}）。1994〜2006 は超過 {net_t['y_mean_ann']:+.1f}%／年・t {o['vehicles_vs_market']['NET']['train']['t']} で、2000〜02年の崩れを挟み統計的には0と区別できない")
    L.append(f"質の上乗せ（cop_at の良い側−市場）への載りは、β だけ除くと ETF側 {bn['b1_A2_bq'][0]}（t {bn['b1_A2_bq'][1]}）、業種を除くと {q5n['hold']}。"
             f"業種を除いた載りは 1994〜2006 {q5n['train']} → 2007〜2025 {q5n['hold']}（差の t {q5n['t_diff']}）、NASDAQ100 は {q5x['train']}→{q5x['hold']} と安定していた")
    L.append(f"検証済みの割増から期待できる上乗せ（載り×1963〜2006 の割増 {pr['E_Q_1963_2006']}%×公表後の割り引き 0.44〜0.56）は ETF側で年 "
             f"{bn['b2_A5q_expected']['0.44']}〜{bn['b2_A5q_expected']['0.56']}%（業種を除いた載り）、上限でも {bn['b1_A2_expected_Q']['0.44']}〜{bn['b1_A2_expected_Q']['0.56']}%。"
             f"純粋な質の三分位（載り1）なら {pr['pure_quality_expected（b_q=1）']['0.44']}〜{pr['pure_quality_expected（b_q=1）']['0.56']}%。つまり ETF側はすでに質を 0.3〜1.4 単位持っている")
    bl = P['industry_longrun_arith_vs_cagr']['BusEq']
    L.append(f"残り（2007年以降の実現の大半）は割増の検証されていない業種の賭け。技術（BusEq）の対市場の年率の差は 1926〜2006 で {bl['1926-07..2006-12']['cagr_diff']:+.2f}%・"
             f"1965〜2006 で {bl['1965-01..2006-12']['cagr_diff']:+.2f}%＝長い目ではほぼ0で、2007年以降の +4〜5%／年を将来の期待に数える根拠は無い")
    L.append(f"城5社は NASDAQ100 と SMH を持った上で質を足していない: 質への載り {cq[0]}（t {cq[1]}）・門の写しへの載り {cg[0]}（t {cg[1]}）。"
             f"城の 2007〜2025 の超過 {c4['y_mean_ann']:+.1f}%／年のうち {c4['alpha_ann']:+.1f}% は説明できない部分＝今日の知識で選んだ5社の後知恵（参考の格付け S は無効）")
    L.append(f"castle_rule の相手: 城の超過と ETF側の超過は相関 {D['orthogonality']['corr_castle_active_vs_NET_active']}（独立ではない）。追従のぶれは 市場 {te['Mkt']}%・QQQM {te['NDX_TR']}%・ETF側の配合 {te['NET']}% "
             f"→ 事前の規則で『ETF側の配合（NASDAQ100 75 / SMH 25）』を推奨。ただし差は小さく、後知恵で最良の組み合わせでも {P['castle_te_floor_in_sample']['te']}%")
    L.append(f"このぶれでは +3pt／年を t=2 で見分けるのに約 {nt['years_for_t2_at_3pt']:.0f} 年かかる。上乗せが本当は0でも 3年で +3pt 以上に見える確率 {nt['P_obs_ge_3pt_if_true0（=P_obs_lt_0_if_true3）'][3]:.0%}・5年で {nt['P_obs_ge_3pt_if_true0（=P_obs_lt_0_if_true3）'][5]:.0%}（castle_rule はほぼ運で動く）")
    L.append(f"円建て（2007-01〜2026-08）: ETF側 年 {J['NET']['hold']['cagr_jpy']}%（米ドル {J['NET']['hold']['cagr_usd']}%）・市場 {J['Mkt']['hold']['cagr_jpy']}%（{J['Mkt']['hold']['cagr_usd']}%）。超過の構造は円でも同じ（為替は両方に掛かる）")
    if 'lag_aligned_vs_QQQ_jpy' in I:
        la = I['lag_aligned_vs_QQQ_jpy']
        L.append(f"iFreeNEXT の実物（2018-09〜2026-08・基準価額）は前営業日の QQQ（円）と差 {la['mean_diff_ann']:+.2f}%／年・ぶれ {la['te']}%・β {la['beta']}＝NASDAQ100 の分析がそのまま当てはまる（信託報酬の差の分だけ低い）")
    i26, x26 = o['oos']['ind2026'].get('NET'), P['ind2026_with_IND12x'].get('NET')
    if i26 and x26:
        L.append(f"2026年1〜8月の答え合わせ: ETF側の対市場 {i26['realized_sum_pct']:+.1f}%（8か月の和）に対し、12業種の載りの予測 {i26['pred_no_alpha_sum_pct']:+.1f}%・技術を4つに割った事後の版 {x26['pred_no_alpha_sum_pct']:+.1f}%＝今年も業種（とくに半導体）の賭けが動かしている")
    return L


# ───────────────────────── 本体 ─────────────────────────
def main():
    out = {'angle': ANGLE, 'prereg': PREREG, 'prereg_commit': sha_of(PREREG), 'global_prereg': 'out/mw_prereg.json',
           'global_prereg_commit': sha_of('out/mw_prereg.json'), 'stance': '記述の角度（格付けは結論に使わない）'}
    dev = []

    # ── 手段 ──
    raw = {t: yh(t) for t in ['^NDX', 'QQQ', '^SOX', 'SMH', 'XLK', '^GSPC'] + CASTLE_NAMES}
    NDX_PR = raw['^NDX']
    NDX_TR = splice(raw['^NDX'], raw['QQQ'], 199903)
    SEMI = splice(raw['^SOX'], raw['SMH'], 200006)
    CH49 = fr_cols('49_Industry_Portfolios', 'Average Value Weighted Returns', ['Hardw', 'Softw', 'Chips', 'LabEq'])
    SEMI_CHIPS = win(CH49['Chips'], 198511, FR_END)
    XLK = raw['XLK']
    names = {t: raw[t] for t in CASTLE_NAMES}
    CASTLE, CASTLE5, ncount = {}, {}, {}
    for k in sorted(set().union(*[set(s) for s in names.values()])):
        v = [s[k] for s in names.values() if k in s]
        ncount[k] = len(v)
        if len(v) >= 3:
            CASTLE[k] = math.fsum(v) / len(v)
        if len(v) == 5:
            CASTLE5[k] = CASTLE[k]
    NET = blend({'NDX_TR': (0.75, NDX_TR), 'SEMI': (0.25, SEMI)})
    NET_CHIPS = blend({'NDX_TR': (0.75, NDX_TR), 'SEMI': (0.25, SEMI_CHIPS)})
    MIX = blend({'NDX_TR': (0.60, NDX_TR), 'SEMI': (0.20, SEMI), 'CASTLE': (0.20, CASTLE)})
    V = {'NDX_TR': NDX_TR, 'NDX_PR': NDX_PR, 'SEMI': SEMI, 'SEMI_CHIPS': SEMI_CHIPS, 'XLK': XLK, 'NET': NET,
         'NET_CHIPS': NET_CHIPS, 'MIX': MIX, 'CASTLE': CASTLE, 'CASTLE5': CASTLE5}
    out['series_coverage'] = {k: {'from': min(s), 'to': max(s), 'months': len(s)} for k, s in list(V.items()) + [(t, names[t]) for t in CASTLE_NAMES]}
    out['castle_names_count_first_month'] = {n: min(k for k, c in ncount.items() if c >= n) for n in (3, 4, 5) if any(c >= n for c in ncount.values())}

    # ── 説明変数 ──
    side, pfs = M.jkp_good_side('usa', 'cop_at', 'vw', upto=M.TRAIN_END)
    Qex = pfs[side]
    Q = active(Qex, MKTRF)
    import mw_gate_proxy as GP
    DU = GP.load('usa', 'vw', keep=set(GP.CHARS))
    Gex, ginfo = GP.composite(DU, GP.MEASURES, 'good')
    G = active(Gex, MKTRF)
    I12 = fr_cols('12_Industry_Portfolios', 'Average Value Weighted Returns',
                  ['NoDur', 'Durbl', 'Manuf', 'Enrgy', 'Chems', 'BusEq', 'Telcm', 'Utils', 'Shops', 'Hlth', 'Money', 'Other'])
    IND12 = {c: active(s, MKT) for c, s in I12.items()}
    IND12X = {c: v for c, v in IND12.items() if c != 'BusEq'}
    IND12X.update({c: active(CH49[c], MKT) for c in ('Hardw', 'Softw', 'Chips', 'LabEq')})
    ME10 = fr_cols('Portfolios_Formed_on_ME', 'Value Weight Returns', ['Hi 10'])['Hi 10']
    ME10a = active(ME10, MKT)
    JKP_END = min(max(Q), max(G))
    out['regressors'] = {'Q_good_side': side, 'Q': {'from': min(Q), 'to': max(Q)}, 'G': {'from': min(G), 'to': max(G), 'info': ginfo},
                         'jkp_end': JKP_END, 'french_end': FR_END}
    log('Q 良い側', side, 'JKP の終わり', JKP_END, 'French の終わり', FR_END)

    X_MKT = [('MktRF', MKTRF)]
    X_Q, X_G = [('Q', Q)], [('G', G)]
    X_IND = [(c, s) for c, s in IND12.items()] + [('ME10a', ME10a)]
    X_INDX = [(c, s) for c, s in IND12X.items()] + [('ME10a', ME10a)]
    GRP = {'beta': ['MktRF'], 'quality_Q': ['Q'], 'quality_G': ['G'], 'industry': list(IND12) , 'mega_ME10a': ['ME10a']}
    GRPX = {'beta': ['MktRF'], 'quality_Q': ['Q'], 'quality_G': ['G'], 'industry': list(IND12X), 'mega_ME10a': ['ME10a']}
    MODELS = {'A0_raw': ([], None), 'A1_capm': (X_MKT, GRP), 'A2_q': (X_MKT + X_Q, GRP), 'A3_g': (X_MKT + X_G, GRP),
              'A4_ind': (X_MKT + X_IND, GRP), 'A5_full': (X_MKT + X_Q + X_G + X_IND, GRP),
              'A5q': (X_MKT + X_Q + X_IND, GRP), 'A5g': (X_MKT + X_G + X_IND, GRP), 'A6_full_x': (X_MKT + X_Q + X_G + X_INDX, GRPX)}

    # ── 検算 ──
    san = {}
    san['french_mkt_cagr_full'] = round(M.cagr(MKT) * 100, 2)
    san['french_mkt_cagr_2007'] = round(M.cagr(win(MKT, M.HOLD_START)) * 100, 2)
    gs = raw['^GSPC']
    lagc = {}
    for L in (-1, 0, 1):
        ks = [k for k in sorted(gs) if 198601 <= k <= 202512]
        def sh(k, L):
            y, m = divmod(k, 100); m += L
            if m == 0: y, m = y - 1, 12
            if m == 13: y, m = y + 1, 1
            return y * 100 + m
        pr = [(gs[k], MKT[sh(k, L)]) for k in ks if sh(k, L) in MKT]
        lagc[f'French を {L:+d} か月ずらす'] = round(M.corr([a for a, _ in pr], [b for _, b in pr]), 4)
    san['yahoo_month_alignment_corr_GSPC_vs_FrenchMkt'] = lagc
    san['Q_full_196307_202512'] = ann_mean(Q, 196307, 202512)
    san['Q_train_196307_200612'] = ann_mean(Q, 196307, 200612)
    san['Q_hold'] = ann_mean(Q, HOLD_A, HOLD_Z)
    san['Q_expected（mw_reality_gap P1_cop_at）'] = 'full +2.23 t3.92 / train +1.95 t2.71 / hold +2.88 t3.22'
    san['G_hold'] = ann_mean(G, HOLD_A, HOLD_Z)
    san['G_full_196307_202512'] = ann_mean(G, 196307, 202512)
    san['G_expected（mw_gate_proxy P1_GATE_ALL）'] = 'hold +0.98 t2.36・full t3.91'
    san['QQQ_hold_vs_Mkt_200701_202608'] = M.excess_stats(raw['QQQ'], MKT, a=M.HOLD_START)
    san['QQQ_expected（mw_reality_gap）'] = '+5.06 t3.47'
    san['QQQ_minus_NDXprice_199904_202608（配当−信託報酬の目安）'] = ann_mean(active(raw['QQQ'], raw['^NDX']), 199904, FR_END)
    san['SMH_minus_SOXprice_200007_202608'] = ann_mean(active(raw['SMH'], raw['^SOX']), 200007, FR_END)
    san['monthly_extremes'] = {t: [round(min(s.values()) * 100, 1), round(max(s.values()) * 100, 1)] for t, s in raw.items()}
    san['corr_Q_G'] = {w: round(M.corr(*zip(*[(Q[k], G[k]) for k in sorted(set(Q) & set(G)) if a <= k <= z])), 3)
                       for w, (a, z) in {'1985-11..2006-12': (198511, 200612), 'hold': (HOLD_A, HOLD_Z), '1963-07..2025-12': (196307, 202512)}.items()}
    out['sanity'] = san
    log('検算', json.dumps({k: san[k] for k in ('french_mkt_cagr_full', 'french_mkt_cagr_2007', 'yahoo_month_alignment_corr_GSPC_vs_FrenchMkt')}, ensure_ascii=False))
    log('Q', san['Q_full_196307_202512'], san['Q_train_196307_200612'], san['Q_hold'], '| G hold', san['G_hold'], '| corr QG', san['corr_Q_G'])
    log('QQQ hold', {k: san['QQQ_hold_vs_Mkt_200701_202608'][k] for k in ('ex_ann', 't')}, 'QQQ−NDX価格', san['QQQ_minus_NDXprice_199904_202608（配当−信託報酬の目安）'])

    # ── 窓 ──
    def windows_for(s):
        st0 = min(s)
        return {'train': (st0, M.TRAIN_END), 'hold': (HOLD_A, HOLD_Z), 'full': (st0, HOLD_Z), 'recent': (M.RECENT_START, HOLD_Z)}

    # ── (a) 分解・載りの安定 ──
    ATTR = ['NDX_TR', 'NDX_PR', 'SEMI', 'SEMI_CHIPS', 'XLK', 'NET', 'NET_CHIPS', 'MIX', 'CASTLE', 'CASTLE5']
    attr = {}
    for vn in ATTR:
        y = active(V[vn], MKT)
        W = windows_for(V[vn])
        attr[vn] = {}
        for mn, (xs, grp) in MODELS.items():
            attr[vn][mn] = {}
            for wn, (a, z) in W.items():
                if vn == 'CASTLE5' and wn == 'train':
                    continue
                if vn == 'SEMI_CHIPS' and mn == 'A6_full_x':
                    attr[vn][mn][wn] = None  # 被説明変数（Chips−Mkt）が説明変数に入っている＝R²=1 の恒等式（意味なし）
                    continue
                attr[vn][mn][wn] = reg(y, xs, a, z, grp)
        a5 = attr[vn]['A5_full']
        log(f"{vn:10s} A5 train", a5.get('train') and {k: a5['train']['coef'][k][:2] for k in ('MktRF', 'Q', 'G', 'BusEq', 'ME10a')},
            'α', a5.get('train') and a5['train']['alpha_ann'], '| hold', a5.get('hold') and {k: a5['hold']['coef'][k][:2] for k in ('MktRF', 'Q', 'G', 'BusEq', 'ME10a')},
            'α', a5.get('hold') and a5['hold']['alpha_ann'], 'R2', a5.get('hold') and a5['hold']['r2'])
    stab = {}
    for vn in ATTR:
        stab[vn] = {}
        for mn in ('A2_q', 'A3_g', 'A4_ind', 'A5_full', 'A5q', 'A5g', 'A6_full_x'):
            tr, ho = attr[vn][mn].get('train'), attr[vn][mn].get('hold')
            if not tr or not ho:
                continue
            d = {}
            for nm in tr['coef']:
                b1, _, s1 = tr['coef'][nm]; b2, _, s2 = ho['coef'][nm]
                se = math.sqrt(s1 * s1 + s2 * s2)
                d[nm] = {'train': b1, 'hold': b2, 'diff': round(b2 - b1, 3), 't_diff': round((b2 - b1) / se, 2) if se > 0 else None}
            d['alpha_ann（train・hold）'] = {'train': tr['alpha_ann'], 'hold': ho['alpha_ann']}
            d['r2（train・hold）'] = {'train': tr['r2'], 'hold': ho['r2']}
            stab[vn][mn] = d
    out['a_stability'] = stab

    # ── (b) 期待できる超過 ──
    EQ = ann_mean(Q, PREM_A, PREM_Z)['mean_ann']
    EG = ann_mean(G, PREM_A, PREM_Z)['mean_ann']
    qn = reg(Q, X_MKT + X_IND, PREM_A, PREM_Z)
    gn = reg(G, X_MKT + X_IND, PREM_A, PREM_Z)
    EQn, EGn = qn['alpha_ann'], gn['alpha_ann']
    long_ind = {c: ann_mean(s, LONG_A, LONG_Z)['mean_ann'] for c, s in IND12.items()}
    long_mktrf = ann_mean(MKTRF, LONG_A, LONG_Z)['mean_ann']
    long_me10a = ann_mean(ME10a, LONG_A, LONG_Z)['mean_ann']
    prem = {'E_Q_1963_2006': EQ, 'E_G_1963_2006': EG, 'E_Q_industry_neutral_alpha_1963_2006': EQn, 'E_Q_industry_neutral_t': qn['alpha_t'],
            'E_G_industry_neutral_alpha_1963_2006': EGn, 'E_G_industry_neutral_t': gn['alpha_t'],
            'Q_realized_hold': ann_mean(Q, HOLD_A, HOLD_Z), 'G_realized_hold': ann_mean(G, HOLD_A, HOLD_Z),
            'haircuts': HAIRCUTS, 'pure_quality_expected（b_q=1）': {str(h): round(EQ * h, 2) for h in HAIRCUTS},
            'long_run_1926_2006': {'MktRF': long_mktrf, 'ME10a': long_me10a, 'IND12': long_ind}}
    out['b_premia'] = prem
    log('割増 E[Q]', EQ, 'E[G]', EG, '業種中立 E[Q]', EQn, 't', qn['alpha_t'], 'E[G]', EGn, 't', gn['alpha_t'])
    bexp = {}
    for vn in ['NDX_TR', 'SEMI', 'XLK', 'NET', 'NET_CHIPS', 'MIX', 'CASTLE', 'CASTLE5']:
        bexp[vn] = {}
        for wn in ('train', 'hold', 'full'):
            a2, a3, a4, a5 = (attr[vn][m].get(wn) for m in ('A2_q', 'A3_g', 'A4_ind', 'A5_full'))
            a5q, a5g = attr[vn]['A5q'].get(wn), attr[vn]['A5g'].get(wn)
            if not a4:
                continue
            e = {'realized_active_mean': a4['y_mean_ann']}
            if a2:
                e['b1_A2_bq'] = a2['coef']['Q'][:2]
                e['b1_A2_expected_Q'] = {str(h): round(a2['coef']['Q'][0] * EQ * h, 2) for h in HAIRCUTS}
            if a3:
                e['b1_A3_bg'] = a3['coef']['G'][:2]
                e['b1_A3_expected_G'] = {str(h): round(a3['coef']['G'][0] * EG * h, 2) for h in HAIRCUTS}
            if a5:
                bq, bg = a5['coef']['Q'][0], a5['coef']['G'][0]
                e['b2_A5_bq_bg'] = {'Q': a5['coef']['Q'][:2], 'G': a5['coef']['G'][:2]}
                e['b2_A5_expected'] = {str(h): round((bq * EQ + bg * EG) * h, 2) for h in HAIRCUTS}
                e['b2_A5_expected_ind_neutral_premia'] = {str(h): round((bq * EQn + bg * EGn) * h, 2) for h in HAIRCUTS}
                e['A5_realized_parts'] = a5['contrib_group_ann']
            if a5q:
                e['b2_A5q_expected'] = {str(h): round(a5q['coef']['Q'][0] * EQ * h, 2) for h in HAIRCUTS}
                e['b2_A5q_expected_ind_neutral'] = {str(h): round(a5q['coef']['Q'][0] * EQn * h, 2) for h in HAIRCUTS}
            if a5g:
                e['b2_A5g_expected'] = {str(h): round(a5g['coef']['G'][0] * EG * h, 2) for h in HAIRCUTS}
            e['industry_only_A4_realized_parts'] = a4['contrib_group_ann']
            e['industry_only_A4_r2'] = a4['r2']
            e['industry_A4_longrun_base_rate'] = round(sum(a4['coef'][c][0] * long_ind[c] for c in IND12), 2)
            e['beta_A4_longrun'] = round(a4['coef']['MktRF'][0] * long_mktrf, 2)
            e['mega_A4_longrun'] = round(a4['coef']['ME10a'][0] * long_me10a, 2)
            bexp[vn][wn] = e
        if bexp[vn].get('hold'):
            h = bexp[vn]['hold']
            log(f"(b) {vn:9s} hold 実現 {h['realized_active_mean']:+.2f} | 期待(質) A2 {h.get('b1_A2_expected_Q', {}).get('0.5')} A5 {h.get('b2_A5_expected', {}).get('0.5')} "
                f"| 業種だけ A4 {h['industry_only_A4_realized_parts']}")
    out['b_expected'] = bexp

    # ── (c) 城の上乗せの載り（NDX・SEMI を持った上で） ──
    ndx_a, semi_a = active(NDX_TR, MKT), active(SEMI, MKT)
    CM = {'C_NDX': X_MKT + [('NDX_act', ndx_a)] + X_Q + X_G,
          'C_NET': X_MKT + [('NDX_act', ndx_a), ('SEMI_act', semi_a)] + X_Q + X_G,
          'C_NETq': X_MKT + [('NDX_act', ndx_a), ('SEMI_act', semi_a)] + X_Q,
          'C_NETg': X_MKT + [('NDX_act', ndx_a), ('SEMI_act', semi_a)] + X_G,
          'C_NET_ind': X_MKT + [('NDX_act', ndx_a), ('SEMI_act', semi_a)] + X_Q + X_G + X_IND}
    cinc = {}
    for vn, s in [('CASTLE', CASTLE), ('CASTLE5', CASTLE5)] + [(t, names[t]) for t in CASTLE_NAMES]:
        y = active(s, MKT)
        cinc[vn] = {}
        for mn, xs in CM.items():
            if vn in CASTLE_NAMES and mn not in ('C_NET', 'C_NETq', 'C_NET_ind'):
                continue
            cinc[vn][mn] = {}
            for wn, (a, z) in {'train': (min(s), M.TRAIN_END), 'hold': (HOLD_A, HOLD_Z), 'full': (min(s), HOLD_Z)}.items():
                if vn == 'CASTLE5' and wn == 'train':
                    continue
                r = reg(y, xs, a, z)
                if r:
                    bq = r['coef'].get('Q', [0])[0]; bg = r['coef'].get('G', [0])[0]
                    r['expected_incremental_quality'] = {str(h): round((bq * EQ + bg * EG) * h, 2) for h in HAIRCUTS}
                cinc[vn][mn][wn] = r
        for mn in ('C_NET', 'C_NETq'):
            r = cinc[vn].get(mn, {}).get('hold')
            if r:
                log(f"(c) {vn:8s} {mn:6s} hold", {k: r['coef'][k][:2] for k in r['coef'] if k in ('NDX_act', 'SEMI_act', 'Q', 'G')}, 'α', r['alpha_ann'], 't', r['alpha_t'], 'R2', r['r2'])
    out['c_castle_incremental'] = cinc

    # ── (d) castle_rule の相手 ──
    FX, FXL, FXD = fx_monthly()
    bench = {'Mkt': MKT, 'NDX_TR': NDX_TR, 'SEMI': SEMI, 'NET': NET}
    dres = {}
    for cur in ('USD', 'JPY'):
        c5 = CASTLE5 if cur == 'USD' else to_jpy(CASTLE5, FX)
        dres[cur] = {}
        for wn, (a, z) in {'all_200604_202608': (200604, FR_END), 'hold_200701_202608': (200701, FR_END)}.items():
            dres[cur][wn] = {}
            for bn, b in bench.items():
                bb = b if cur == 'USD' else to_jpy(b, FX)
                ks = [k for k in sorted(c5) if a <= k <= z and k in bb]
                d = [c5[k] - bb[k] for k in ks]
                te = S.stdev(d) * math.sqrt(12) * 100
                vb = S.pvariance([bb[k] for k in ks])
                beta = sum((c5[k] - S.mean([c5[j] for j in ks])) * (bb[k] - S.mean([bb[j] for j in ks])) for k in ks) / len(ks) / vb
                dres[cur][wn][bn] = {'n': len(ks), 'te': round(te, 2), 'corr': round(M.corr([c5[k] for k in ks], [bb[k] for k in ks]), 3),
                                     'beta': round(beta, 2), 'mean_diff_ann': round(S.mean(d) * 1200, 2),
                                     'years_for_t2_at_3pt': round((2 * te / 3) ** 2, 1),
                                     'P_obs_ge_3pt_if_true0（=P_obs_lt_0_if_true3）': {T: round(phi(-3 * math.sqrt(T) / te), 3) for T in (3, 5, 10)}}
    # 独立か: 城の対 Mkt と NET の対 Mkt
    ks = [k for k in sorted(CASTLE5) if k in NET and k in MKT and k <= FR_END]
    cr = M.corr([CASTLE5[k] - MKT[k] for k in ks], [NET[k] - MKT[k] for k in ks])
    crn = M.corr([CASTLE5[k] - MKT[k] for k in ks], [NDX_TR[k] - MKT[k] for k in ks])
    tes = {bn: dres['USD']['all_200604_202608'][bn]['te'] for bn in ('Mkt', 'NDX_TR', 'NET')}
    best = min(tes, key=tes.get)
    rec = 'NET' if tes['NET'] - tes[best] <= 0.5 else best
    dres['orthogonality'] = {'corr_castle_active_vs_NET_active': round(cr, 3), 'R2': round(cr * cr, 3),
                             'corr_castle_active_vs_NDX_active': round(crn, 3), 'independent': abs(cr) < 0.3, 'months': len(ks)}
    dres['decision'] = {'te_usd_all': tes, 'lowest': best, 'recommended': rec,
                        'rule': '最小の TE。ただし NET が最小との差 0.5pt 以内なら NET（事前登録どおり）'}
    out['d_castle_benchmark'] = dres
    log('(d) TE', tes, '推奨', rec, '独立か', dres['orthogonality'])

    # ── 手段の超過（参考の格付け） ──
    COST = {'NDX_TR': 0.0, 'SEMI': 0.0, 'XLK': 0.0, 'NET': 0.15, 'NET_CHIPS': 0.15, 'MIX': 0.15 + 0.2 * 0.40, 'CASTLE': 0.40, 'CASTLE5': 0.40}
    veh, hp_in = {}, {}
    for vn in ['NDX_TR', 'SEMI', 'XLK', 'NET', 'NET_CHIPS', 'MIX', 'CASTLE', 'CASTLE5', 'NDX_PR', 'SEMI_CHIPS']:
        s = V[vn]
        o = {'full': M.excess_stats(s, MKT), 'train': M.excess_stats(s, MKT, z=M.TRAIN_END), 'hold': M.excess_stats(s, MKT, a=M.HOLD_START),
             'recent': M.excess_stats(s, MKT, a=M.RECENT_START), 'roll20': M.rolling(s, MKT, 20), 'dca20': M.dca(s, MKT, 20),
             'maxdd': round(M.maxdd(s) * 100, 1), 'maxdd_mkt_same': round(M.maxdd({k: MKT[k] for k in s if k in MKT}) * 100, 1),
             'sharpe_hold': (M.sharpe(s, RF, a=M.HOLD_START), M.sharpe({k: MKT[k] for k in s if k in MKT}, RF, a=M.HOLD_START))}
        if vn in COST:
            o['turnover_oneway_per_year'] = COST[vn]; o['unit_cost'] = 0.001
            o['cost_hold'] = M.excess_stats(M.apply_cost(s, COST[vn], 0.001), MKT, a=M.HOLD_START)
            if o['hold']:
                hp_in[vn] = o['hold']['p']
        veh[vn] = o
    hp = M.holm(hp_in)
    tested = []
    for vn, o in veh.items():
        rec_ = {'name': vn, 'family': 'vehicles_reference', 'primary': False, 'reference_only': True}
        if vn in COST:
            g, c = M.grade(o['full'], o['train'], o['hold'], o['roll20'], cost_hold=o['cost_hold'], repl=None, family_holm_p=hp.get(vn))
            o['holm_p_hold'] = hp.get(vn); o['grade_reference'] = g; o['criteria'] = c
            if vn in ('CASTLE', 'CASTLE5'):
                o['grade_reference_invalid'] = '2026年に門が選んだ5社（事後に勝者と分かっている生き残り）を過去へ当てた＝後知恵の選択。格付けは勝ちの証拠にならない'
            rec_.update({'grade_reference': g, 'criteria': c})
        for k in ('full', 'train', 'hold', 'recent'):
            if o[k]:
                rec_[k] = {kk: o[k][kk] for kk in ('from', 'to', 'ex_ann', 't', 'cagr_diff', 'te', 'beta')}
        tested.append(rec_)
        log(f"手段 {vn:10s} full {o['full']['ex_ann']:+.2f} t{o['full']['t']} | train {o['train'] and o['train']['ex_ann']} t{o['train'] and o['train']['t']} | "
            f"hold {o['hold']['ex_ann']:+.2f} t{o['hold']['t']} | roll20 {o['roll20'] and o['roll20']['win_rate']} | 参考 {o.get('grade_reference')}")
    out['vehicles_vs_market'] = veh

    # ── 円 ──
    jp = {}
    mj = to_jpy(MKT, FX)
    for vn in ['NDX_TR', 'SEMI', 'NET', 'NET_CHIPS', 'MIX', 'CASTLE', 'CASTLE5', 'Mkt']:
        s = MKT if vn == 'Mkt' else V[vn]
        sj = to_jpy(s, FX)
        r = {}
        for wn, (a, z) in {'train': (min(s), M.TRAIN_END), 'hold': (HOLD_A, FR_END), 'full': (min(s), FR_END)}.items():
            if vn == 'CASTLE5' and wn == 'train':
                continue
            su, sj_ = win(s, a, z), win(sj, a, z)
            r[wn] = {'from': min(su), 'to': max(su), 'cagr_usd': round(M.cagr(su) * 100, 2), 'cagr_jpy': round(M.cagr(sj_) * 100, 2)}
            if vn != 'Mkt':
                es = M.excess_stats(sj, mj, a, z)
                r[wn]['active_jpy_vs_Mkt_jpy'] = es and {k: es[k] for k in ('ex_ann', 't', 'cagr_diff', 'te')}
        if vn != 'Mkt':
            r['dca20_jpy_vs_Mkt_jpy'] = M.dca(sj, mj, 20)
            if vn in ('NET', 'MIX', 'NDX_TR'):
                y = active(sj, mj)
                r['A5_jpy'] = {wn: reg(y, MODELS['A5_full'][0], a, z, GRP) for wn, (a, z) in
                               {'train': (min(s), M.TRAIN_END), 'hold': (HOLD_A, HOLD_Z)}.items()}
        jp[vn] = r
    out['jpy'] = jp
    log('円 NET hold', jp['NET']['hold'], '| MIX hold', jp['MIX']['hold'])

    # ── 事後に届いたデータでの答え合わせ（out of sample） ──
    oos = {}
    # 2026 の業種だけ
    ind26 = {}
    for vn in ['NDX_TR', 'SEMI', 'NET', 'MIX', 'CASTLE5']:
        r = attr[vn]['A4_ind'].get('hold')
        y = active(V[vn], MKT)
        xs = MODELS['A4_ind'][0]
        rows = []
        for k in sorted(y):
            if k <= HOLD_Z or not all(k in x for _, x in xs):
                continue
            p_no = math.fsum(b * x[k] for b, (_, x) in zip(r['_b'][1:], xs))
            rows.append((k, y[k], p_no, p_no + r['_b'][0]))
        if rows:
            ind26[vn] = {'months': [k for k, *_ in rows], 'realized_sum_pct': round(sum(v for _, v, _, _ in rows) * 100, 2),
                         'pred_no_alpha_sum_pct': round(sum(p for _, _, p, _ in rows) * 100, 2),
                         'pred_with_alpha_sum_pct': round(sum(p for _, _, _, p in rows) * 100, 2),
                         'corr_month': round(M.corr([v for _, v, _, _ in rows], [p for _, _, p, _ in rows]), 3) if len(rows) > 2 else None}
    oos['ind2026'] = ind26
    log('2026 業種だけ', ind26)
    post = {}
    if JKP_END > HOLD_Z:
        for vn in ['NDX_TR', 'SEMI', 'NET', 'MIX', 'CASTLE5']:
            post[vn] = reg(active(V[vn], MKT), MODELS['A5_full'][0], HOLD_Z + 1, JKP_END, GRP)
    else:
        post = {'status': f'データ無し（JKP の終わり {JKP_END}）。JKP が 2026 年を公開したらこの窓に入る'}
    oos['post2025_jkp'] = post
    # iFreeNEXT
    try:
        ifr, me, rows = ifree_nav()
        qj = to_jpy(raw['QQQ'], FX)
        ks = [k for k in sorted(ifr) if k in qj]
        d = [ifr[k] - qj[k] for k in ks]
        ino = {'nav_first': rows[0][:2], 'nav_last': rows[-1][:2], 'months': len(ifr), 'distributions_total': sum(x[2] for x in rows),
               'same_month_vs_QQQ_jpy': {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'mean_diff_ann': round(S.mean(d) * 1200, 2),
                                         'te': round(S.stdev(d) * math.sqrt(12) * 100, 2),
                                         'corr': round(M.corr([ifr[k] for k in ks], [qj[k] for k in ks]), 4),
                                         'cagr_ifree': round(M.cagr([ifr[k] for k in ks]) * 100, 2), 'cagr_qqq_jpy': round(M.cagr([qj[k] for k in ks]) * 100, 2)}}
        # 前営業日の米国終値に合わせた版
        qd = M.yahoo('QQQ', interval='1d')
        lvl, x = {}, 1.0
        for k in sorted(qd):
            x *= 1 + qd[k]; lvl[k] = x
        usd_days = sorted(lvl)
        fxd = sorted(FXD)
        import bisect

        def px_jpy_before(d):
            i = bisect.bisect_left(usd_days, d) - 1
            if i < 0:
                return None
            u = usd_days[i]
            j = bisect.bisect_right(fxd, u) - 1
            if j < 0:
                return None
            return lvl[u] * FXD[fxd[j]], u
        lag = {}
        mk = sorted(me)
        for p, k in zip(mk, mk[1:]):
            a_, b_ = px_jpy_before(me[p][0]), px_jpy_before(me[k][0])
            if a_ and b_ and k <= FR_END:
                lag[k] = b_[0] / a_[0] - 1
        ks2 = [k for k in sorted(ifr) if k in lag]
        d2 = [ifr[k] - lag[k] for k in ks2]
        _vb = S.pvariance([lag[k] for k in ks2]); _mi = S.mean([ifr[k] for k in ks2]); _ml = S.mean([lag[k] for k in ks2])
        ino['lag_aligned_vs_QQQ_jpy'] = {'from': ks2[0], 'to': ks2[-1], 'n': len(ks2), 'mean_diff_ann': round(S.mean(d2) * 1200, 2),
                                         'beta': round(sum((ifr[k] - _mi) * (lag[k] - _ml) for k in ks2) / len(ks2) / _vb, 3),
                                         'te': round(S.stdev(d2) * math.sqrt(12) * 100, 2),
                                         'corr': round(M.corr([ifr[k] for k in ks2], [lag[k] for k in ks2]), 4)}
        yi, yq = active(ifr, mj), active(qj, mj)
        ks3 = [k for k in yi if k in yq]
        ino['A5_ifree_jpy_201809_202512'] = reg({k: yi[k] for k in ks3}, MODELS['A5_full'][0], None, HOLD_Z, GRP)
        ino['A5_qqq_jpy_same_months'] = reg({k: yq[k] for k in ks3}, MODELS['A5_full'][0], None, HOLD_Z, GRP)
        ino['A2_ifree_jpy'] = reg({k: yi[k] for k in ks3}, MODELS['A2_q'][0], None, HOLD_Z, GRP)
        ino['A2_qqq_jpy_same_months'] = reg({k: yq[k] for k in ks3}, MODELS['A2_q'][0], None, HOLD_Z, GRP)
        oos['ifree_nav'] = ino
        log('iFreeNEXT', ino['same_month_vs_QQQ_jpy'], '| 前営業日合わせ', ino['lag_aligned_vs_QQQ_jpy'])
    except Exception as e:  # noqa
        oos['ifree_nav'] = {'error': repr(e)}
        dev.append(f'iFreeNEXT の基準価額を取得できなかった: {e!r}')
    out['oos'] = oos
    out['post_hoc_事後'] = posthoc(V, attr, IND12, IND12X, ME10a, CH49, raw, X_MKT)

    out['attribution'] = attr
    dev += ['2026 の業種だけの予測は、事前登録が α を足すか書いていなかったので、α を足さない版（業種・β・超大型だけ）を主にし、足した版も並べた',
            'SEMI_CHIPS の A6（49業種の Chips を説明変数に入れる式）は被説明変数そのものが説明変数に入る恒等式（R²=1）なので出さない',
            'iFreeNEXT の同じ暦月の回帰（A5・A2）は、基準価額が前営業日の米国の終値で決まる1営業日のずれで載りが薄まる（中身の違いではない）。答え合わせの主は前営業日に合わせた QQQ との比較',
            '事後の記述（業種の算術と年率の差・2026 を 49業種の技術4本で・城の追従のぶれの床）を post_hoc_事後 に足した。格付けなし']
    out['tested'] = tested
    out['n_tested'] = len(tested)
    out['n_regressions'] = sum(1 for v in attr.values() for m in v.values() for w in m.values() if w) + \
        sum(1 for v in cinc.values() for m in v.values() for w in m.values() if w)
    out['deviations'] = dev
    out['log'] = LOG
    out['summary_ja'] = summary(out)
    p = M.save(OUT, strip(out))
    print('saved', p, os.path.getsize(p))


if __name__ == '__main__':
    main()
