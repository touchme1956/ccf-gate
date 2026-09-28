#!/usr/bin/env python3
"""night/nx_stack.py — 角度 nx_stack（リターンの積み重ね）を事前登録どおりに測る（読むだけ・門の判定には不使用）

問い: 市場（French Mkt）を100%持ったうえに、市場とほぼ独立の上乗せ（AQR の自己資金ゼロの買い−売り・時系列の勢い・
      商品の買い持ち・信用の上乗せ）を、訓練期間のぶれで年10%に揃えた固定の倍率 k で借入なしに重ねると、
      費用を引いても市場に勝つか。β を足しただけ（シャープが上がらない）ではないか。
事前登録: out/nx_stack_prereg.json（commit 7c5ec72d・測る前）。線は out/nx_prereg.json（C1〜C8・S/A/B/C）。
データ: night/nx_stack_data.py の load()（out/_nx_cache/nx_stack_series.json）。
出力: out/nx_stack.json（tested に 79 本すべて＝負けも残す）

約束（事前登録どおり）
- s_gross = Mkt + k×F、s_net = s_gross − c/12、b = Mkt（どちらも総リターン）。超過 = k×F（− c/12）
- k = 0.10 ÷（訓練期間の F の月次標準偏差 × √12）。訓練期間の最後で決めて保有期間は動かさない
- C1・C2・C3・C7 は費用前、C4・C6・C8 は費用後
- Holm は族ごと（P 8本・X1 の各変形 8本・X2 22本・X3 10本・X4 5本・X5 2本は片側）
- 実物のファンドの答え合わせは格付けに入れない（real_instrument_check）
- 結果を見た後の分析は post_hoc に置き『事後』と明記し、格付けには使わない
"""
import sys, os, json, math, statistics as S, hashlib, subprocess, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_stack_data as D  # noqa: E402

import statistics as _stat  # noqa: E402


class _StatShim:
    """速さだけの細工（数値は1ビットも変えない）: nx_common.excess_stats は β の和の中で S.mean(sv)・S.mean(bv) を
    要素ごとに計算し直す（分数の厳密計算 × O(n²)・1200か月で1回 約1秒）。同じ list オブジェクトへの mean の答えを覚えて返す。
    list を強参照で持つので id の再利用は起きず、答えは statistics.mean そのもの。他の関数はそのまま statistics へ渡す。
    nx_common.py 自体は書き換えない（他の角度と同じ物差しを保つ）"""

    def __init__(self):
        self._last = []

    def mean(self, x):
        for o, ln, r in self._last:
            if o is x and ln == len(x):
                return r
        r = _stat.mean(x)
        self._last = ([(x, len(x), r)] + self._last)[:4]
        return r

    def __getattr__(self, name):
        return getattr(_stat, name)


N.S = _StatShim()

BASE = N.BASE
PREREG_PATH = os.path.join(BASE, 'out', 'nx_stack_prereg.json')
PR = json.load(open(PREREG_PATH))
OUTNAME = 'nx_stack.json'
TE, HS, RS = N.TRAIN_END, N.HOLD_START, N.RECENT_START
FUND = 0.3  # 重ねる資金調達（%/年）

SER, META = D.load()
MKT, RF = SER['FF|Mkt'], SER['FF|RF']
LAST = max(MKT)
SHILLER = SER['SHILLER|nominal_TR']


# ───────────────────────── 小道具 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def sha1_file(p):
    try:
        return hashlib.sha1(open(p, 'rb').read()).hexdigest()[:12]
    except OSError:
        return None


def sd_ann(vals):
    return S.stdev(vals) * math.sqrt(12) if len(vals) > 2 else None


def train_sigma(F, a, base=MKT, z=TE):
    v = [F[m] for m in sorted(F) if m in base and a <= m <= z]
    return sd_ann(v), len(v)


def prev_months(ym, n):
    y, m = divmod(ym, 100)
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(y * 100 + m)
    return out


def trailing_k(F, target, kfix, a, z):
    """X1c: 毎月末に直近36か月（t−36〜t−1）のぶれで target に揃える k_t。k_t は kfix の 1/3〜3倍に制限。
    36か月がそろわない月（最初の36か月・商品の欠けの直後）は重ねない＝その月は落とす"""
    kt = {}
    for m in sorted(F):
        if not (a <= m <= z):
            continue
        w = prev_months(m, 36)
        if not all(x in F for x in w):
            continue
        s = sd_ann([F[x] for x in w])
        if not s:
            continue
        kt[m] = min(max(target / s, kfix / 3), kfix * 3)
    return kt


def build(F, base, a, z, k=None, kt=None, cost_pct=0.0):
    """→ (s_gross, s_net, b)。F と base の両方がある月だけ（欠けを0と読まない）"""
    ms = [m for m in sorted(F) if m in base and a <= m <= z and (kt is None or m in kt)]
    g, n, b = {}, {}, {}
    for m in ms:
        kk = kt[m] if kt is not None else k
        g[m] = base[m] + kk * F[m]
        n[m] = g[m] - cost_pct / 100 / 12
        b[m] = base[m]
    return g, n, b


def span_of(F, base=MKT, a=None, z=None):
    ks = [m for m in F if m in base and (a is None or m >= a) and (z is None or m <= z)]
    return (min(ks), max(ks)) if ks else (None, None)


def es(s, b, a=None, z=None):
    return N.excess_stats(s, b, a, z)


def shp(r, a=None, z=None):
    return N.sharpe(r, RF, a, z)


def corr_w(F, a=None, z=None):
    ks = [m for m in sorted(F) if m in MKT and (a is None or m >= a) and (z is None or m <= z)]
    if len(ks) < 24:
        return None
    return round(N.corr([F[m] for m in ks], [MKT[m] for m in ks]), 3)


def positive(st):
    return bool(st and st['ex_ann'] > 0 and st['cagr_diff'] > 0)


# ───────────────────────── 規則の定義（事前登録から） ─────────────────────────
PFAM = PR['families']['P_primary']['rules']
P_MGMT = {'P1_macro_multistyle': 1.5, 'P2_macro_value': 1.0, 'P3_macro_momentum': 1.0, 'P4_macro_carry': 1.0,
          'P5_macro_defensive': 1.0, 'P6_tsmom': 1.0, 'P7_commodity_long': 0.5, 'P8_credit': 0.5}
P_SERIES = {'P1_macro_multistyle': 'CFP|All Macro Multi-style', 'P2_macro_value': 'CFP|All Macro Value',
            'P3_macro_momentum': 'CFP|All Macro Momentum', 'P4_macro_carry': 'CFP|All Macro Carry',
            'P5_macro_defensive': 'CFP|All Macro Defensive', 'P6_tsmom': 'TSMOM|TSMOM',
            'P7_commodity_long': 'CLR|EW_excess', 'P8_credit': 'CRP|CORP_XS'}
P_UNITS = {
    'P1_macro_multistyle': ['CFP|Equity indices Multi-style', 'CFP|Fixed income Multi-style', 'CFP|Currencies Multi-style', 'CFP|Commodities Multi-style'],
    'P2_macro_value': ['CFP|Equity indices Value', 'CFP|Fixed income Value', 'CFP|Currencies Value', 'CFP|Commodities Value'],
    'P3_macro_momentum': ['CFP|Equity indices Momentum', 'CFP|Fixed income Momentum', 'CFP|Currencies Momentum', 'CFP|Commodities Momentum'],
    'P4_macro_carry': ['CFP|Equity indices Carry', 'CFP|Fixed income Carry', 'CFP|Currencies Carry', 'CFP|Commodities Carry'],
    'P5_macro_defensive': ['CFP|Equity indices Defensive', 'CFP|Fixed income Defensive'],
    'P6_tsmom': ['TSMOM|TSMOM^EQ', 'TSMOM|TSMOM^FI', 'TSMOM|TSMOM^FX', 'TSMOM|TSMOM^CM'],
    'P7_commodity_long': ['ERA_1877_1926'],
    'P8_credit': [],
}
P_POSTPUB = {'P1_macro_multistyle': 202001, 'P2_macro_value': 201401, 'P3_macro_momentum': 201401, 'P4_macro_carry': 201901,
             'P5_macro_defensive': 201501, 'P6_tsmom': 201301, 'P7_commodity_long': 200701, 'P8_credit': None}
P_TRAIN_A = {'P6_tsmom': 198501}  # 他は 192607
ERA = (187702, 192606)


def p_rule(pid, scale='fixed', target=0.10, mgmt_mult=1.0, family='P', rid=None):
    return {'id': rid or pid, 'parent': pid, 'family': family, 'overlay': P_SERIES[pid], 'F': SER[P_SERIES[pid]],
            'train_a': P_TRAIN_A.get(pid, 192607), 'mgmt': P_MGMT[pid] * (mgmt_mult if mgmt_mult is not None else 1.0), 'scale': scale, 'target': target,
            'units': P_UNITS[pid], 'unit_kind': 'era' if pid == 'P7_commodity_long' else ('none' if not P_UNITS[pid] else 'series'),
            'post_pub': P_POSTPUB[pid], 'post_pub_ref': 201901 if pid == 'P7_commodity_long' else None,
            'prereg_text': PFAM[pid]['overlay']}


def build_rules():
    R = []
    for pid in P_SERIES:
        R.append(p_rule(pid))
    # X1: 大きさだけ変える
    for pid in P_SERIES:
        R.append(p_rule(pid, 'fixed', 0.05, 0.5, 'X1a_vol5', f'X1a_vol5|{pid}'))
    for pid in P_SERIES:
        R.append(p_rule(pid, 'fixed', 0.15, 1.5, 'X1b_vol15', f'X1b_vol15|{pid}'))
    for pid in P_SERIES:
        R.append(p_rule(pid, 'trailing36', 0.10, 1.0, 'X1c_trailing36', f'X1c_trailing36|{pid}'))
    for pid in P_SERIES:
        R.append(p_rule(pid, 'notional1', None, None, 'X1d_notional1', f'X1d_notional1|{pid}'))
    # X2: 資産クラス別の単体
    for txt in PR['families']['X2_single_asset_class']['rules']:
        nm = txt.split(' ⚠')[0].strip()
        R.append({'id': f'X2|{nm}', 'parent': None, 'family': 'X2', 'overlay': nm, 'F': SER[nm], 'train_a': None,
                  'mgmt': 1.5 if 'Multi-style' in nm else 1.0, 'scale': 'fixed', 'target': 0.10, 'units': [],
                  'unit_kind': 'none', 'post_pub': None, 'prereg_text': txt})
    # X3: 別の作り方
    x3 = PR['families']['X3_other_constructions']['rules']
    vm = {m: (SER['VME|VAL^AA'][m] + SER['VME|MOM^AA'][m]) / 2 for m in SER['VME|VAL^AA'] if m in SER['VME|MOM^AA']}
    R += [
        {'id': 'X3a_vme_val_aa', 'overlay': 'VME|VAL^AA', 'F': SER['VME|VAL^AA'], 'mgmt': 1.0},
        {'id': 'X3b_vme_mom_aa', 'overlay': 'VME|MOM^AA', 'F': SER['VME|MOM^AA'], 'mgmt': 1.0},
        {'id': 'X3c_vme_valmom_aa', 'overlay': '(VME|VAL^AA + VME|MOM^AA)/2', 'F': vm, 'mgmt': 1.5},
        {'id': 'X3d_clr_ls_carry', 'overlay': 'CLR|LS_excess', 'F': SER['CLR|LS_excess'], 'mgmt': 1.0, 'units': ['ERA_1877_1926'], 'unit_kind': 'era'},
        {'id': 'X3e_cfp_commodity_market', 'overlay': 'CFP|Commodities Market', 'F': SER['CFP|Commodities Market'], 'mgmt': 0.5},
        {'id': 'X3f_cfp_allmacro_market', 'overlay': 'CFP|All Macro Market', 'F': SER['CFP|All Macro Market'], 'mgmt': 0.3},
        {'id': 'X3g_cfp_fi_market', 'overlay': 'CFP|Fixed income Market', 'F': SER['CFP|Fixed income Market'], 'mgmt': 0.2},
        {'id': 'X3h_cfp_eq_market', 'overlay': 'CFP|Equity indices Market', 'F': SER['CFP|Equity indices Market'], 'mgmt': 0.2},
        {'id': 'X3i_styles_plus_trend', 'overlay': '0.5×(k_P1×P1 + k_P6×P6) → 1985-01〜2006-12 のぶれで10%', 'F': None, 'mgmt': 1.5, 'train_a': 198501, 'combo': ['P1_macro_multistyle', 'P6_tsmom']},
        {'id': 'X3j_four_styles_plus_trend', 'overlay': 'mean(k_P2×P2 … k_P6×P6) → 1985-01〜2006-12 のぶれで10%', 'F': None, 'mgmt': 1.5, 'train_a': 198501,
         'combo': ['P2_macro_value', 'P3_macro_momentum', 'P4_macro_carry', 'P5_macro_defensive', 'P6_tsmom']},
    ]
    for r in R[-10:]:
        r.update({'parent': None, 'family': 'X3', 'scale': 'fixed', 'target': 0.10, 'post_pub': None, 'prereg_text': x3[r['id']]})
        r.setdefault('train_a', None); r.setdefault('units', []); r.setdefault('unit_kind', 'none')
    # X4: 株の銘柄選び（参考）
    x4 = [('CFP|US Stock Selection Multi-style', ['CFP|Intl Stock Selection Multi-style']),
          ('CFP|Intl Stock Selection Multi-style', ['CFP|US Stock Selection Multi-style']),
          ('CFP|All asset classes Multi-style', []),
          ('BAB|USA', ['BAB|Global Ex USA']),
          ('BAB|Global Ex USA', ['BAB|USA'])]
    for nm, units in x4:
        R.append({'id': f'X4|{nm}', 'parent': None, 'family': 'X4', 'overlay': nm, 'F': SER[nm], 'train_a': None, 'mgmt': 1.5,
                  'scale': 'fixed', 'target': 0.10, 'units': units, 'unit_kind': 'series' if units else 'none', 'post_pub': None,
                  'prereg_text': nm})
    return R


# ───────────────────────── 倍率 ─────────────────────────
KFIX = {}  # P の固定の k（X1c の制限・X3i/j の部品に使う）


def combo_series(r):
    parts = []
    for pid in r['combo']:
        F = SER[P_SERIES[pid]]
        s, _ = train_sigma(F, P_TRAIN_A.get(pid, 192607))
        parts.append((pid, F, 0.10 / s))
    ms = sorted(set.intersection(*[set(F) for _, F, _ in parts]))
    return {m: S.fmean(k * F[m] for _, F, k in parts) for m in ms}, {pid: round(k, 4) for pid, _, k in parts}


def scale_of(r, F, train_a, base=MKT, cost_mgmt=None):
    """→ (k or None, kt or None, cost_pct, info)"""
    sig, n = train_sigma(F, train_a, base)
    info = {'train_sigma_ann_pct': round(sig * 100, 3), 'train_months': n}
    if r['scale'] == 'fixed':
        k = r['target'] / sig
        return k, None, r['mgmt'] + FUND, dict(info, k=round(k, 5))
    if r['scale'] == 'notional1':
        pid = r['parent']
        mg = P_MGMT[pid] * sig / 0.10
        return 1.0, None, mg + FUND, dict(info, k=1.0, mgmt_pct=round(mg, 4))
    raise ValueError(r['scale'])


# ───────────────────────── C5（独立の単位） ─────────────────────────
def unit_eval(r, uname, k_parent=None, kfix_parent=None):
    """単位に親と同じ作り方を当て、使えるデータの全期間で費用後の超過（算術・幾何とも）が正かを見る"""
    if uname == 'ERA_1877_1926':
        F = r['F']
        a, z = ERA
        cost = r['_cost']
        if r['scale'] == 'trailing36':
            kt = trailing_k(F, 0.10, kfix_parent, a, z)
            g, n, b = build(F, SHILLER, a, z, kt=kt, cost_pct=cost)
            kinfo = {'k': 'trailing36（親の固定 k を制限の基準）'}
        else:
            k = k_parent  # 事前登録: 『同じ k と同じ費用』
            g, n, b = build(F, SHILLER, a, z, k=k, cost_pct=cost)
            kinfo = {'k': round(k, 5), 'k_rule': '親と同じ k（事前登録 P7 の C5_units の明記どおり）'}
        st = es(n, b)
        return {'unit': '1877-02〜1926-06（土台 Shiller の名目の総リターン）', **kinfo, 'cost_pct': round(cost, 4),
                'net_full': st, 'gross_full': es(g, b), 'positive': positive(st)}
    F = SER[uname]
    ua = min(m for m in F if m in MKT)
    sig, nmo = train_sigma(F, ua)
    if r['scale'] == 'fixed':
        k = r['target'] / sig
        cost = r['mgmt'] + FUND
        g, n, b = build(F, MKT, ua, LAST, k=k, cost_pct=cost)
        kinfo = {'k': round(k, 5)}
    elif r['scale'] == 'notional1':
        k = 1.0
        mg = P_MGMT[r['parent']] * sig / 0.10
        cost = mg + FUND
        g, n, b = build(F, MKT, ua, LAST, k=k, cost_pct=cost)
        kinfo = {'k': 1.0, 'mgmt_pct': round(mg, 4)}
    else:  # trailing36: 単位自身の固定 k を制限の基準にする
        kf = 0.10 / sig
        cost = r['mgmt'] + FUND
        kt = trailing_k(F, 0.10, kf, ua, LAST)
        g, n, b = build(F, MKT, ua, LAST, kt=kt, cost_pct=cost)
        kinfo = {'k': 'trailing36', 'k_fixed_base': round(kf, 5)}
    st = es(n, b)
    return {'unit': uname, 'unit_train': f'{ua}〜{TE}', 'train_sigma_ann_pct': round(sig * 100, 3), **kinfo,
            'cost_pct': round(cost, 4), 'net_full': st, 'gross_full': es(g, b), 'positive': positive(st)}


# ───────────────────────── 1本を測る ─────────────────────────
def evaluate(r):
    if r.get('combo'):
        F, parts_k = combo_series(r)
        r['F'] = F
    F = r['F']
    fa, fz = span_of(F)
    train_a = r['train_a'] or fa
    out = {'id': r['id'], 'family': r['family'], 'overlay': r['overlay'], 'prereg_text': r['prereg_text']}
    if r.get('combo'):
        out['component_k'] = parts_k
    if r['scale'] in ('fixed', 'notional1'):
        k, kt, cost, info = scale_of(r, F, train_a)
        r['_k'] = k
    else:  # trailing36
        kf = KFIX[r['parent']]
        cost = r['mgmt'] + FUND
        kt = trailing_k(F, r['target'], kf, train_a, fz)
        k = None
        sig, n_ = train_sigma(F, train_a)
        info = {'k': 'trailing36', 'k_fixed_base': round(kf, 5), 'k_min': round(min(kt.values()), 5), 'k_max': round(max(kt.values()), 5),
                'k_median': round(S.median(kt.values()), 5), 'train_sigma_ann_pct': round(sig * 100, 3),
                'dropped_first_months': sum(1 for m in F if train_a <= m <= fz and m in MKT and m not in kt)}
    r['_cost'] = cost
    g, n, b = build(F, MKT, train_a, fz, k=k, kt=kt, cost_pct=cost)
    a0, z0 = min(g), max(g)
    out.update({'span': f'{a0}〜{z0}', 'train': f'{a0}〜{TE}', 'hold': f'{HS}〜{z0}', 'scale': r['scale'],
                'target_vol': r['target'], 'cost_pct_per_year': round(cost, 4), 'mgmt_pct': round(cost - FUND, 4), 'funding_pct': FUND, **info})
    if r['family'] == 'P':
        KFIX[r['id']] = k
    # 検算
    kof = (lambda m: kt[m]) if kt is not None else (lambda m: k)
    ident = max(abs(g[m] - MKT[m] - kof(m) * F[m]) for m in g)
    trv = sd_ann([kof(m) * F[m] for m in g if m <= TE])
    out['sanity'] = {'identity_max_abs_err': ident, 'identity_ok': ident < 1e-12,
                     'train_realized_vol_pct': round(trv * 100, 3),
                     'train_vol_matches_target': (abs(trv - r['target']) < 1e-9) if r['scale'] == 'fixed' else None,
                     'last_month_le_mkt_last': z0 <= LAST}
    # 超過
    full, train, hold = es(g, b), es(g, b, z=TE), es(g, b, a=HS)
    nfull, ntrain, nhold = es(n, b), es(n, b, z=TE), es(n, b, a=HS)
    out['gross'] = {'full': full, 'train': train, 'hold': hold, 'recent_2013_07': es(g, b, a=RS)}
    out['net'] = {'full': nfull, 'train': ntrain, 'hold': nhold, 'recent_2013_07': es(n, b, a=RS)}
    if r.get('post_pub'):
        out['post_publication'] = {'from': r['post_pub'], 'gross': es(g, b, a=r['post_pub']), 'net': es(n, b, a=r['post_pub'])}
        if r.get('post_pub_ref'):
            out['post_publication']['ref_from'] = r['post_pub_ref']
            out['post_publication']['ref_net'] = es(n, b, a=r['post_pub_ref'])
    out['roll20_net'] = N.rolling(n, b)
    out['roll20_gross'] = N.rolling(g, b)
    out['dca20_net_ratio'] = N.dca(n, b)
    out['maxdd'] = {'s_net_full': round(N.maxdd(n) * 100, 1), 'mkt_full': round(N.maxdd(b) * 100, 1),
                    's_net_hold': round(N.maxdd(N.window(n, HS)) * 100, 1), 'mkt_hold': round(N.maxdd(N.window(b, HS)) * 100, 1)}
    out['sharpe'] = {p: {'s_net': shp(n, a, z), 's_gross': shp(g, a, z), 'mkt': shp(b, a, z)}
                     for p, a, z in (('train', None, TE), ('hold', HS, None), ('full', None, None), ('recent_2013_07', RS, None))}
    out['corr_overlay_mkt'] = {'train': corr_w(F, a0, TE), 'hold': corr_w(F, HS, z0)}
    out['not_independent_of_market'] = any(c is not None and abs(c) > 0.3 for c in out['corr_overlay_mkt'].values())
    # 費用の感度（報告のみ）
    mg = cost - FUND
    sens = {}
    for mm in (0, 0.5, 1, 1.5, 2):
        for ff in (0, 0.3, 0.6):
            c2 = mg * mm + ff
            n2 = {m: g[m] - c2 / 100 / 12 for m in g}
            h2 = es(n2, b, a=HS)
            f2 = es(n2, b)
            sens[f'mgmt×{mm}+fund{ff}'] = {'cost_pct': round(c2, 4), 'hold_ex_ann': h2['ex_ann'] if h2 else None,
                                          'hold_cagr_diff': h2['cagr_diff'] if h2 else None, 'full_cagr_diff': f2['cagr_diff'] if f2 else None,
                                          'C6_would_pass': positive(h2)}
    out['cost_sensitivity'] = sens
    # C5
    if r['unit_kind'] == 'none':
        out['C5_units'] = []
        out['repl'] = None
    else:
        us = [unit_eval(r, u, k_parent=k, kfix_parent=KFIX.get(r['parent'])) for u in r['units']]
        out['C5_units'] = us
        out['repl'] = {'regions': len(us), 'positive': sum(1 for u in us if u['positive'])}
        if r['unit_kind'] == 'era' and r['scale'] == 'fixed':
            # 報告のみ: その時代自身のぶれで k を決めた版（事前登録の一般則『単位自身の訓練期間』の読み方）
            sig_e, _ = train_sigma(F, ERA[0], SHILLER, ERA[1])
            ke = r['target'] / sig_e
            g2, n2, b2 = build(F, SHILLER, ERA[0], ERA[1], k=ke, cost_pct=cost)
            out['C5_era_own_k_report_only'] = {'k': round(ke, 5), 'net_full': es(n2, b2), 'positive': positive(es(n2, b2))}
    out['_series'] = (g, n, b)
    return out


# ───────────────────────── 短い標本（X5） ─────────────────────────
def evaluate_short(rid, F_raw, mgmt, a_rule, text):
    F = {m: F_raw[m] - RF[m] for m in F_raw if m in RF}
    cost = mgmt + FUND
    g, n, b = build(F, MKT, a_rule, LAST, k=1.0, cost_pct=cost)
    _, n2, _ = build(F, MKT, a_rule, LAST, k=1.0, cost_pct=2 * cost)
    ms = sorted(g)
    h = len(ms) // 2
    first, second = set(ms[:h]), set(ms[h:])
    sub = lambda d, keep: {m: v for m, v in d.items() if m in keep}  # noqa: E731
    top = max(ms, key=lambda m: g[m] - b[m])
    keep = set(ms) - {top}
    full = es(g, b)
    res = {'id': rid, 'family': 'X5', 'overlay': text, 'span': f'{ms[0]}〜{ms[-1]}', 'k': 1.0, 'cost_pct_per_year': round(cost, 4),
           'halves': {'first': f'{ms[0]}〜{ms[h - 1]}', 'second': f'{ms[h]}〜{ms[-1]}'},
           'gross': {'full': full, 'first_half': es(sub(g, first), sub(b, first)), 'second_half': es(sub(g, second), sub(b, second)),
                     'drop_top_month': es(sub(g, keep), sub(b, keep)), 'recent_2013_07': es(g, b, a=RS)},
           'drop_top_month_which': top,
           'net': {'full': es(n, b), 'first_half': es(sub(n, first), sub(b, first)), 'second_half': es(sub(n, second), sub(b, second)),
                   'double_cost_full': es(n2, b)},
           'sharpe': {p: {'s_net': shp(sub(n, ks)), 's_gross': shp(sub(g, ks)), 'mkt': shp(sub(b, ks))}
                      for p, ks in (('full', set(ms)), ('first_half', first), ('second_half', second))},
           'maxdd': {'s_net_full': round(N.maxdd(n) * 100, 1), 'mkt_full': round(N.maxdd(b) * 100, 1)},
           'corr_overlay_mkt': {'full': corr_w(F, ms[0], ms[-1])},
           'roll20_net': N.rolling(n, b), 'dca20_net_ratio': N.dca(n, b),
           'sanity': {'identity_max_abs_err': max(abs(g[m] - MKT[m] - F[m]) for m in g)}}
    res['p_one_full_gross'] = round(N.p_one(full['t']), 6) if full and full['t'] is not None else None
    res['_series'] = (g, n, b)
    return res


# ───────────────────────── 実物の答え合わせ（格付けに入れない） ─────────────────────────
def fund_ex(t):
    s = SER.get('YH|' + t)
    if not s:
        return None, None
    zeros = sorted(m for m, v in s.items() if v == 0.0)
    ex = {m: v - RF[m] for m, v in s.items() if m in RF and m <= LAST and v != 0.0}  # 月途中の最後の月（RF に無い）と、ちょうど0の月（欠けの疑い）を落とす
    return ex, zeros


def ann_mean(x):
    return round(S.fmean(x) * 12 * 100, 2) if x else None


def geo_ann(x):
    return round((math.exp(math.fsum(math.log1p(v) for v in x) * 12 / len(x)) - 1) * 100, 2) if x else None


def compare_fund_paper(t, paper_name, paper, scale_to_fund=True):
    fe, zeros = fund_ex(t)
    if fe is None:
        return {'fund': t, 'error': '取得できず'}
    ms = sorted(m for m in fe if m in paper)
    if len(ms) < 12:
        return {'fund': t, 'paper': paper_name, 'months': len(ms), 'note': '重なる月が12か月未満'}
    f = [fe[m] for m in ms]
    p = [paper[m] for m in ms]
    c = (S.stdev(f) / S.stdev(p)) if scale_to_fund else 1.0
    ps = [c * v for v in p]
    d = [x - y for x, y in zip(f, ps)]
    return {'fund': t, 'paper': paper_name, 'from': ms[0], 'to': ms[-1], 'months': len(ms), 'zero_months_dropped': zeros,
            'paper_scale': round(c, 4) if scale_to_fund else 1.0,
            'fund_ex_ann_arith': ann_mean(f), 'paper_ann_arith': ann_mean(ps), 'fund_minus_paper_ann_arith': ann_mean(d),
            'fund_ex_ann_geo': geo_ann(f), 'paper_ann_geo': geo_ann(ps),
            'fund_vol': round(S.stdev(f) * math.sqrt(12) * 100, 2), 'corr': round(N.corr(f, p), 3),
            'diff_t_nw': (lambda t_: round(t_, 2) if t_ is not None else None)(N.nw_t(d))}


def real_checks():
    out = {'note': '格付けに入れない報告。Yahoo の調整後終値（配当込み）・今も存在するファンドだけ（生き残りの偏りあり）。最後の月（2026-09・月の途中）とちょうど0の月（欠けの疑い）は落とした',
           'PUTW': '取得できず（Yahoo 404・データの道具の段階で）'}
    P6 = SER['TSMOM|TSMOM']
    out['managed_futures_vs_P6'] = [compare_fund_paper(t, 'TSMOM|TSMOM（ファンドの実現のぶれに合わせた大きさ）', P6)
                                    for t in ('AQMIX', 'QMHIX', 'ASFYX', 'PQTIX', 'DBMF', 'KMLM', 'CTA')]
    out['style_premia_vs_P1'] = [compare_fund_paper(t, nm + '（ファンドのぶれに合わせた大きさ）', SER[nm])
                                 for t in ('QSPIX', 'QRPRX') for nm in ('CFP|All Macro Multi-style', 'CFP|All asset classes Multi-style')]
    out['commodity'] = [compare_fund_paper(t, 'CLR|EW_excess（1倍の元本どうし）', SER['CLR|EW_excess'], scale_to_fund=False) for t in ('DBC', 'GSG')]
    out['commodity'].append(compare_fund_paper('COM', 'TSMOM|TSMOM^CM（ファンドのぶれに合わせた大きさ・COM は買いか休みで売らない）', SER['TSMOM|TSMOM^CM']))
    fe, zeros = fund_ex('HYZD')
    ms = sorted(fe)
    x = [fe[m] for m in ms]
    out['credit_HYZD_alone'] = {'from': ms[0], 'to': ms[-1], 'months': len(ms), 'zero_months_dropped': zeros,
                                'ex_rf_ann_arith': ann_mean(x), 'ex_rf_ann_geo': geo_ann(x), 't_nw': round(N.nw_t(x), 2),
                                'vol': round(S.stdev(x) * math.sqrt(12) * 100, 2), 'corr_mkt': round(N.corr(x, [MKT[m] for m in ms]), 3),
                                'note': 'P8 のデータ（〜2014-12）と重ならないのでファンド単独（HYZD − RF）。HYZD は金利をヘッジしたハイイールド＝信用の超過に近いが同じ物ではない'}
    spy = {m: v for m, v in SER['YH|SPY'].items() if m <= LAST and v != 0.0}
    st = {}
    for t in ('RSST', 'RSSB', 'RSBT', 'RSSY', 'NTSX', 'GDE'):
        s = {m: v for m, v in SER['YH|' + t].items() if m <= LAST and v != 0.0}
        st[t] = {'vs_SPY': es(s, spy), 'vs_FrenchMkt': es(s, MKT), 'sharpe': shp(s), 'sharpe_mkt_same_months': shp({m: MKT[m] for m in s if m in MKT}),
                 'maxdd': round(N.maxdd(s) * 100, 1), 'maxdd_mkt_same_months': round(N.maxdd({m: MKT[m] for m in s if m in MKT}) * 100, 1)}
    out['stacked_etfs'] = st
    ps = {}
    for t in ('AQMIX', 'QMHIX', 'QSPIX', 'QRPRX', 'ASFYX', 'PQTIX', 'DBMF', 'KMLM', 'CTA', 'COM', 'HYZD', 'DBC', 'GSG'):
        fe, _ = fund_ex(t)
        s = {m: MKT[m] + fe[m] for m in fe if m in MKT}
        b = {m: MKT[m] for m in s}
        ps[t] = {'stack_vs_mkt': es(s, b), 'sharpe_stack': shp(s), 'sharpe_mkt': shp(b), 'maxdd_stack': round(N.maxdd(s) * 100, 1),
                 'maxdd_mkt': round(N.maxdd(b) * 100, 1), 'dca_note': '期間が20年未満なので積立20年は無い'}
    out['paper_stack_with_real_fund'] = {'rule': 'Mkt + 1.0×（ファンド − RF）を Mkt と比べる（RSST 型の 100/100 をそのファンドで作ったら・資金調達の上乗せは引いていない）',
                                         'funds': ps}
    out['rakuten'] = PR['real_instrument_check']['rakuten']
    return out


# ───────────────────────── 検算（事前登録の sanity_checks_before_results） ─────────────────────────
def data_sanity():
    v = PR['data']
    want = {'CFP': v['aqr_century']['vintage'], 'TSMOM': v['aqr_tsmom']['vintage'], 'VME': v['aqr_vme']['vintage'],
            'BAB': v['aqr_bab']['vintage'], 'CLR': v['aqr_clr']['vintage'], 'CRP': v['aqr_credit']['vintage'],
            'CBOE_PUT': v['cboe']['vintage'], 'CBOE_BXM': v['cboe']['vintage'], 'SHILLER': v['shiller']['vintage']}
    files = {'CFP': 'aqr_Century-of-Factor-Premia-Monthly.xlsx', 'TSMOM': 'aqr_Time-Series-Momentum-Factors-Monthly.xlsx',
             'VME': 'aqr_Value-and-Momentum-Everywhere-Factors-Monthly.xlsx', 'BAB': 'aqr_Betting-Against-Beta-Equity-Factors-Monthly.xlsx',
             'CLR': 'aqr_Commodities-for-the-Long-Run-Index-Level-Data-Monthly.xlsx', 'CRP': 'aqr_Credit-Risk-Premium-Preliminary-Paper-Data.xlsx',
             'CBOE_PUT': 'cboe_PUT.csv', 'CBOE_BXM': 'cboe_BXM.csv', 'SHILLER': 'shiller_ie_data.xls'}
    sha = {}
    for k, f in files.items():
        now = sha1_file(os.path.join(N.CACHE, f))
        in_json = META['sha1'].get(k)
        sha[k] = {'prereg_vintage': want[k], 'series_json': in_json, 'cache_file_now': now,
                  'match': bool(in_json and in_json in want[k] and now == in_json)}
    gap = [m for m in range(194308, 194909) if 1 <= m % 100 <= 12]
    comm = {c: [m for m in gap if m in SER[c]] for c in ('CFP|Commodities Multi-style', 'CFP|Commodities Value', 'CFP|Commodities Momentum', 'CFP|Commodities Carry')}
    clr = SER['CLR|EW_excess']
    ks = sorted(clr)
    x = [clr[k] for k in ks]
    ac1 = N.corr(x[:-1], x[1:])
    after = {k: max(s) for k, s in SER.items() if (k.startswith('CFP|') or k.startswith('TSMOM|') or k.startswith('VME|') or k.startswith('BAB|') or k.startswith('CLR|')) and max(s) > LAST}
    return {'sha1_vintage': sha, 'sha1_all_match': all(v['match'] for v in sha.values()),
            'commodity_gap_1943_08_1949_08_present_months': comm, 'commodity_gap_dropped': all(not v for v in comm.values()),
            'CLR_read_as_returns': {'abs_gt_0.5': sum(1 for v in x if abs(v) > 0.5), 'lag1_autocorr': round(ac1, 3), 'has_negative': any(v < 0 for v in x)},
            'aqr_months_after_mkt_last': after, 'mkt_last': LAST}


# ───────────────────────── 事後の診断（格付けに使わない） ─────────────────────────
def post_hoc(results):
    """結果を見た後に足した診断。すべて『事後』＝格付けに使わない"""
    ph = {'label': '事後（結果を見た後に足した分析・格付けに使わない）'}
    periods = [(192607, 194512), (194601, 196912), (197001, 198912), (199001, 200612), (200701, 201212), (201301, 201912), (202001, 202608)]
    dec = {}
    for r in results:
        if r['family'] not in ('P',):
            continue
        g, n, b = r['_series']
        row = {}
        for a, z in periods:
            st = es(n, b, a, z)
            row[f'{a}〜{z}'] = {'net_ex_ann': st['ex_ann'], 'net_cagr_diff': st['cagr_diff'], 't': st['t']} if st else None
        dec[r['id']] = row
    ph['net_excess_by_era_P'] = dec
    # 市場の下落月（Mkt の月次が下位10%）での上乗せ＝『危機のときに効くか』
    cr = {}
    for r in results:
        if r['family'] != 'P':
            continue
        g, n, b = r['_series']
        ms = [m for m in g]
        vals = sorted(MKT[m] for m in ms)
        cut = vals[len(vals) // 10]
        worst = [m for m in ms if MKT[m] <= cut]
        rest = [m for m in ms if MKT[m] > cut]
        cr[r['id']] = {'mkt_bottom10pct_months': len(worst), 'overlay_ann_in_bottom10': ann_mean([g[m] - b[m] for m in worst]),
                       'overlay_ann_other_months': ann_mean([g[m] - b[m] for m in rest])}
    ph['overlay_in_market_down_months_P'] = cr
    # 保有期間の年ごとの上乗せ（費用後）＝どの年に勝ち負けが集中したか（P と、格付けが B 以上の規則）
    yr = {}
    for r in results:
        if not (r['family'] == 'P' or r.get('grade') in ('S', 'A', 'B')):
            continue
        g, n, b = r['_series']
        row = {}
        for y in range(2007, 2027):
            ms = [m for m in n if m // 100 == y]
            if not ms:
                continue
            ss = math.prod(1 + n[m] for m in ms) - 1
            bb = math.prod(1 + b[m] for m in ms) - 1
            row[y] = round((ss - bb) * 100, 2)
        yr[r['id']] = row
    ph['hold_calendar_year_net_diff_pct'] = yr

    # 勝ちの中身（S・A の規則と P6）: 保有期間の勝ちが一握りの月・年に寄っていないか
    win = {}
    for r in results:
        if not (r.get('grade') in ('S', 'A') or r['id'] == 'P6_tsmom'):
            continue
        g, n, b = r['_series']
        hm = [m for m in n if m >= HS]
        exn = {m: n[m] - b[m] for m in hm}
        keep = lambda f: ({m: n[m] for m in hm if f(m)}, {m: b[m] for m in hm if f(m)})  # noqa: E731
        top12 = set(sorted(hm, key=lambda m: exn[m], reverse=True)[:12])
        pos_sum = sum(v for v in exn.values())
        top5 = sorted(exn.values(), reverse=True)[:5]
        row = {}
        for lab, f in (('hold_all', lambda m: True), ('ex_2008', lambda m: m // 100 != 2008),
                       ('ex_2008_2022', lambda m: m // 100 not in (2008, 2022)), ('ex_top12_months', lambda m: m not in top12),
                       ('first_half_2007_2016', lambda m: m <= 201612), ('second_half_2017_', lambda m: m >= 201701)):
            s2, b2 = keep(f)
            st = es(s2, b2)
            row[lab] = {'net_ex_ann': st['ex_ann'], 'net_cagr_diff': st['cagr_diff'], 't': st['t'], 'years': st['years']} if st else None
        row['top5_months_share_of_hold_arith_excess'] = round(sum(top5) / pos_sum, 3) if pos_sum > 0 else None
        row['top12_months'] = sorted(top12)
        row['hold_realized_overlay_vol_pct'] = r['gross']['hold']['te'] if r['gross']['hold'] else None
        row['train_realized_overlay_vol_pct'] = r['gross']['train']['te'] if r['gross']['train'] else None
        win[r['id']] = row
    ph['winners_concentration'] = win

    # P6 の4資産クラス（C5 の単位）を保有期間だけで見る
    p6u = {}
    for nm in P_UNITS['P6_tsmom']:
        F = SER[nm]
        sig, _ = train_sigma(F, 198501)
        g, n, b = build(F, MKT, 198501, LAST, k=0.10 / sig, cost_pct=1.3)
        st = es(n, b, a=HS)
        p6u[nm] = {'k': round(0.10 / sig, 5), 'hold_net': st}
    ph['P6_units_hold_only'] = p6u

    # 紙の P6 の重ね と 実物のマネージドフューチャーズで重ねた場合 を同じ月で比べる
    P6 = SER['TSMOM|TSMOM']
    kp6 = KFIX['P6_tsmom']
    mf = {}
    for t in ('AQMIX', 'QMHIX', 'ASFYX', 'PQTIX', 'DBMF', 'KMLM', 'CTA'):
        fe, _ = fund_ex(t)
        ms = sorted(m for m in fe if m in P6 and m in MKT)
        b = {m: MKT[m] for m in ms}
        real = {m: MKT[m] + fe[m] - FUND / 100 / 12 for m in ms}
        paper10 = {m: MKT[m] + kp6 * P6[m] - 1.3 / 100 / 12 for m in ms}
        vf = S.stdev([fe[m] for m in ms]) * math.sqrt(12)
        cf = vf / (S.stdev([P6[m] for m in ms]) * math.sqrt(12))
        paper_f = {m: MKT[m] + cf * P6[m] - (1.0 * vf / 0.10 + FUND) / 100 / 12 for m in ms}
        e1, e2, e3 = es(real, b), es(paper10, b), es(paper_f, b)
        mf[t] = {'from': ms[0], 'to': ms[-1], 'months': len(ms), 'fund_vol_pct': round(vf * 100, 2),
                 'real_stack_minus_funding0.3_cagr_diff': e1['cagr_diff'] if e1 else None, 'real_stack_t': e1['t'] if e1 else None,
                 'real_stack_sharpe': shp(real), 'mkt_sharpe': shp(b),
                 'paper_P6_stack_k_fixed_net_cagr_diff': e2['cagr_diff'] if e2 else None,
                 'paper_P6_stack_at_fund_vol_net_cagr_diff': e3['cagr_diff'] if e3 else None}
    ph['managed_futures_real_vs_paper_stack_same_months'] = {
        'note': '実物: Mkt +（ファンド − RF）− 資金調達0.3%/年（ファンドの信託報酬と売買費用は実績に入っている）。紙: P6 の固定の k・費用1.3%、およびファンドの実現のぶれに合わせた大きさ・運用費用はぶれに比例（1.0%×ぶれ/10%）＋0.3%',
        'funds': mf}

    # 株の銘柄選び（X4）の紙が実物でどうだったか: AQR Equity Market Neutral（QMNIX・2014-11〜）を結果を見た後に取得して並べる
    try:
        SER['YH|QMNIX'] = N.yahoo('QMNIX')
        qm = {}
        for nm in ('CFP|All Stock Selection Multi-style', 'CFP|US Stock Selection Multi-style', 'CFP|Intl Stock Selection Multi-style'):
            qm[nm] = compare_fund_paper('QMNIX', nm + '（ファンドのぶれに合わせた大きさ）', SER[nm])
        fe, _ = fund_ex('QMNIX')
        ms = sorted(m for m in fe if m in MKT)
        real = {m: MKT[m] + fe[m] - FUND / 100 / 12 for m in ms}
        b = {m: MKT[m] for m in ms}
        e1 = es(real, b)
        ph['X4_real_check_QMNIX'] = {'note': '事後に取得（事前登録の実物の一覧に無い）。QMNIX は米国＋米国外の株の銘柄選びの買い−売り（市場中立）。生き残りの偏りあり',
                                     'vs_paper': qm,
                                     'real_stack_minus_funding0.3': e1, 'real_stack_sharpe': shp(real), 'mkt_sharpe': shp(b)}
    except Exception as e:  # noqa
        ph['X4_real_check_QMNIX'] = {'error': str(e)}

    # 79本すべてを1つの族とみなした Holm（保有期間・費用前・両側）＝事前登録より厳しい見方
    allp = {r['id']: (r['gross']['hold'] or {}).get('p') for r in results}
    h = N.holm(allp)
    ph['holm_all_77_long_history_rules'] = {'n': len(allp), 'passing_lt_0.05': {k: v for k, v in h.items() if v < 0.05}}
    return ph


# ───────────────────────── 本体 ─────────────────────────
def main():
    rules = build_rules()
    results = []
    for r in rules:
        results.append(evaluate(r))
    # X5（短い標本）
    x5 = PR['families']['X5_option_writing_short']['rules']
    shorts = [evaluate_short('X5a_put', SER['CBOE|PUT'], 0.45, 200702, x5['X5a_put']),
              evaluate_short('X5b_bxm', SER['CBOE|BXM'], 0.6, 200206, x5['X5b_bxm'])]

    # Holm（族ごと・保有期間・費用前・両側）
    fams = {}
    for x in results:
        fams.setdefault(x['family'], []).append(x)
    holm = {}
    for fam, xs in fams.items():
        hp = N.holm({x['id']: (x['gross']['hold'] or {}).get('p') for x in xs})
        holm[fam] = {'n': len(xs), 'raw_p_hold_gross_two_sided': {x['id']: (x['gross']['hold'] or {}).get('p') for x in xs}, 'holm_p': hp}
        for x in xs:
            x['family_holm_p'] = hp.get(x['id'])
    hp5 = N.holm({x['id']: x['p_one_full_gross'] for x in shorts})
    holm['X5'] = {'n': 2, 'raw_p_one_full_gross': {x['id']: x['p_one_full_gross'] for x in shorts}, 'holm_p_one': hp5}

    # 格付け
    for x in results:
        sp = {'train': (x['sharpe']['train']['s_net'], x['sharpe']['train']['mkt']),
              'hold': (x['sharpe']['hold']['s_net'], x['sharpe']['hold']['mkt'])}
        g, c = N.grade(full=x['gross']['full'], train=x['gross']['train'], hold=x['gross']['hold'], roll20=x['roll20_net'],
                       cost_hold=x['net']['hold'], repl=x['repl'], family_holm_p=x['family_holm_p'], sharpe_pair=sp, leveraged_or_timing=True)
        x['criteria'] = c
        x['grade'] = g
        x['grading_inputs'] = {'full': '費用前の全期間', 'train': '費用前の訓練', 'hold': '費用前の保有', 'roll20': '費用後の20年窓',
                               'cost_hold': '費用後の保有', 'repl': x['repl'], 'family_holm_p': x['family_holm_p'], 'sharpe_pair': sp}
        x['exploratory'] = x['family'] != 'P'
    for x in shorts:
        x['family_holm_p_one'] = hp5.get(x['id'])
        g0, c = N.grade_short(full=x['gross']['full'], first_half=x['gross']['first_half'], second_half=x['gross']['second_half'],
                              drop_top=x['gross']['drop_top_month'], cost_full=x['net']['full'], lower_bound=x['net']['double_cost_full'],
                              family_holm_p_one=x['family_holm_p_one'])
        sh_ok = all(v['s_net'] is not None and v['mkt'] is not None and v['s_net'] > v['mkt'] for v in x['sharpe'].values())
        c['sharpe_all_three_beat_mkt'] = sh_ok
        x['grade_before_sharpe_gate'] = g0
        x['grade'] = g0 if sh_ok else 'C'
        x['criteria'] = c
        x['criteria_mapping'] = {'drop_top': '超過が最も大きかった1か月を抜いても正（費用前）', 'lower_bound': '費用2倍でも正',
                                 'sharpe_gate': '全期間・前半・後半のすべてで s_net のシャープが Mkt を上回らなければ C'}
        x['exploratory'] = True

    allr = results + shorts
    ph = post_hoc(results)
    for x in allr:
        x.pop('_series', None)

    summ = {}
    for x in allr:
        summ.setdefault(x['family'], {}).setdefault(x['grade'], []).append(x['id'])
    headline = []
    for x in allr:
        if x['family'] == 'X5':
            headline.append({'id': x['id'], 'grade': x['grade'], 'gross_full_ex_ann': x['gross']['full']['ex_ann'],
                             'net_full_cagr_diff': x['net']['full']['cagr_diff'], 'p_one': x['p_one_full_gross']})
            continue
        headline.append({'id': x['id'], 'grade': x['grade'], 'k': x.get('k'),
                         'train_ex_ann_gross': (x['gross']['train'] or {}).get('ex_ann'), 'train_t': (x['gross']['train'] or {}).get('t'),
                         'hold_ex_ann_gross': (x['gross']['hold'] or {}).get('ex_ann'), 'hold_t': (x['gross']['hold'] or {}).get('t'),
                         'hold_cagr_diff_net': (x['net']['hold'] or {}).get('cagr_diff'), 'full_t': (x['gross']['full'] or {}).get('t'),
                         'roll20_net_win': (x['roll20_net'] or {}).get('win_rate'), 'repl': x['repl'], 'holm_p': x.get('family_holm_p'),
                         'sharpe_train_net_vs_mkt': (x['sharpe']['train']['s_net'], x['sharpe']['train']['mkt']),
                         'sharpe_hold_net_vs_mkt': (x['sharpe']['hold']['s_net'], x['sharpe']['hold']['mkt']),
                         'criteria_passed': [k for k, v in x['criteria'].items() if v is True]})

    deviations = [
        'X1（大きさだけ変える8本×4）の C5 は事前登録に明記が無い。最も近い形として、親 P と同じ独立の単位に、同じ大きさの変え方（5%・15%・直近36か月・1倍）と同じ費用の決め方を当てた。格付けに効いたのは X1c_trailing36|P2_macro_value の1本だけ（C3 が不合格で C5 が合格＝A。C5 を N/A と読めば B）。P6 の4変形の S は C5 を N/A と読んでも S のまま',
        'X1c（直近36か月のぶれ）: 36の暦月（t−36〜t−1）がすべてそろわない月は重ねずに落とした（最初の36か月に加え、商品の単位では 1943-08〜1949-08 の欠けの直後の36か月）。k_t の制限の基準は親 P の固定の k（単位では単位自身の固定の k）',
        'P7 と X3d の C5（1877-02〜1926-06）は、事前登録の P7 の単位の明記『同じ k と同じ費用』に従い親の k を使った。一般則『単位自身の訓練期間のぶれ』で k を決めた版は C5_era_own_k_report_only に報告だけ（格付けには不使用）',
        'X5b の期間は事前登録の規則の欄どおり 2002-06 から（データの道具は 2002-05 のリターンも作れるが、規則の欄の期間を優先した）',
        'X5 の grade_short: full・前半・後半・最大の1か月を抜いた版と片側 p は費用前、cost は費用後、lower_bound は費用2倍の費用後で渡した（事前登録の置き換え2か所とシャープの門はそのまま）',
        'Holm の p は nx_common.excess_stats が返す丸めた p（小数4桁）をそのまま使った（他の角度と同じ物差し）',
        '（逸脱ではない注記）速さのために nx_common の statistics を、同じ list への mean の答えを覚えるだけの薄い包みに差し替えた（nx_common.py は書き換えていない。excess_stats の戻り値が素の statistics と完全に一致することを確かめた）',
        '（逸脱ではない注記）実物の答え合わせに、事前登録の一覧に無い QMNIX（AQR Equity Market Neutral）を結果を見た後に足した＝post_hoc に置き、格付けにも real_instrument_check にも入れていない',
    ]

    byid = {x['id']: x for x in allr}
    p6 = byid['P6_tsmom']
    w6 = ph['winners_concentration']['P6_tsmom']
    mfr = ph['managed_futures_real_vs_paper_stack_same_months']['funds']
    summary = [
        f"主の族 P（8本）: S={summ['P'].get('S', [])} / A={summ['P'].get('A', [])} / B={summ['P'].get('B', [])} / C={summ['P'].get('C', [])}",
        (f"P6 時系列の勢い（AQR TSMOM・58先物）を k={p6['k']} で重ねた: 訓練 1985-2006 の超過 {p6['gross']['train']['ex_ann']}%/年 t{p6['gross']['train']['t']}・"
         f"保有 2007-2026-05 {p6['gross']['hold']['ex_ann']}%/年 t{p6['gross']['hold']['t']}（費用1.3%後の幾何の差 {p6['net']['hold']['cagr_diff']}%/年）・"
         f"20年窓 {p6['roll20_net']['wins']}/{p6['roll20_net']['windows']}・シャープ 保有 {p6['sharpe']['hold']['s_net']} 対 {p6['sharpe']['hold']['mkt']}・C5 {p6['repl']['positive']}/{p6['repl']['regions']}"),
        (f"ただし P6 の保有期間の勝ちは細い（事後の診断）: 族の中の Holm 後 p={p6['family_holm_p']}（C7 は全期間 t{p6['gross']['full']['t']} で通った＝訓練期間の強さに支えられている）・"
         f"2008年を除くと {w6['ex_2008']['net_cagr_diff']}%/年・2008と2022を除くと {w6['ex_2008_2022']['net_cagr_diff']}%/年・上位12か月を除くと {w6['ex_top12_months']['net_cagr_diff']}%/年・"
         f"2017年以降 {w6['second_half_2017_']['net_cagr_diff']}%/年 t{w6['second_half_2017_']['t']}。株価指数の勢い（TSMOM^EQ）は保有期間で {ph['P6_units_hold_only']['TSMOM|TSMOM^EQ']['hold_net']['cagr_diff']}%/年"),
        ('実物のマネージドフューチャーズで重ねた場合（Mkt +（ファンド−RF）− 0.3%・事後）: ' +
         '・'.join(f"{t} {v['real_stack_minus_funding0.3_cagr_diff']}%/年（{v['from']}〜{v['to']}・t{v['real_stack_t']}）" for t, v in mfr.items())),
        f"P2 マクロの割安は A（保有 t{byid['P2_macro_value']['gross']['hold']['t']}・費用後の保有 {byid['P2_macro_value']['net']['hold']['cagr_diff']}%/年＝ほぼ0）。P1・P3・P4・P5・P7・P8 は C",
        f"X4（株の銘柄選び・参考・他セッションと重なる）: Intl Stock Selection MS の紙は保有 {byid['X4|CFP|Intl Stock Selection Multi-style']['gross']['hold']['ex_ann']}%/年 t{byid['X4|CFP|Intl Stock Selection Multi-style']['gross']['hold']['t']} だが、実物の QMNIX（2014-11〜）と同じぶれで比べると 実物−紙 = {ph['X4_real_check_QMNIX']['vs_paper']['CFP|Intl Stock Selection Multi-style'].get('fund_minus_paper_ann_arith')}%/年（t{ph['X4_real_check_QMNIX']['vs_paper']['CFP|Intl Stock Selection Multi-style'].get('diff_t_nw')}・事後）＝紙が実物を大きく上回る",
        "X5（オプション売り・短い標本）: 超過は正だがシャープが市場を上回らない（β を足しただけ）→ C",
        '重ねる型は先物・信用取引が要り、日本の個人が NISA で持つ手段は無い。楽天の海外ETF 742本にも重ね型・マネージドフューチャーズの ETF は無い（事前登録の rakuten）',
    ]

    obj = {
        'generated': datetime.date.today().isoformat(),
        'summary_ja': summary,
        'angle': 'nx_stack（リターンの積み重ね）',
        'prereg': {'path': 'out/nx_stack_prereg.json', 'commit': git_sha(PREREG_PATH), 'global': 'out/nx_prereg.json'},
        'script': 'night/nx_stack.py',
        'stance': '測定器。門・採点・配分には入れない。線（C1〜C8）は結果を見て動かしていない。負けた規則も全部 tested に残す',
        'benchmark': 'French Mkt（Mkt-RF + RF）。s と b はどちらも総リターン',
        'conventions': {'C1_C2_C3_C7': '費用前（s_gross 対 Mkt）', 'C4_C6_C8': '費用後（s_net 対 Mkt）',
                        'k': '0.10 ÷ 訓練期間（データの始まり〜2006-12）の上乗せの月次標準偏差×√12。保有期間は固定',
                        'C5': '単位ごとに親と同じ作り方（単位自身の訓練期間のぶれで k・親と同じ費用）を当て、使えるデータの全期間で費用後の超過の算術平均と幾何の年率差がともに正なら『正』'},
        'data_sanity': data_sanity(),
        'deviations_from_prereg': deviations,
        'holm': holm,
        'grade_summary': summ,
        'headline': headline,
        'tested_count': {'graded': len(allr), 'prereg_total_graded': PR['test_count']['total_graded']},
        'tested': allr,
        'real_instrument_check': real_checks(),
        'post_hoc': ph,
        'known_limits': PR['known_limits'],
    }
    p = N.save(OUTNAME, obj)
    print('書いた:', p)
    print('格付け:', json.dumps(summ, ensure_ascii=False))
    for h in headline:
        print(json.dumps(h, ensure_ascii=False))


if __name__ == '__main__':
    main()
