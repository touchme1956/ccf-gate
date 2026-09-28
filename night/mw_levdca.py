#!/usr/bin/env python3
"""night/mw_levdca.py — 市場に勝てる歴史検証(mw)・角度 levdca: 構造的レバレッジ × 毎月積立（読むだけ・門の判定には不使用）

事前登録: out/mw_levdca_prereg.json（規則・線は測る前に固定。ここで動かさない）
出力    : out/mw_levdca.json

族
- P（主・格付け）: 一定倍率の日次リセット（French 市場 L=1.25/1.5/2/3・NASDAQ-100 L=1.25/1.5/2）、
                    信用取引の月次リバランス（L=1.25/1.5/2・借入 RF+1.5%）、訓練期間のケリー最適 L とその半分（3構造）
- E1（探索・格付け）: 株＋長期国債を借入で持ち上げる（60/40×1.5/×2・訓練固定のリスクパリティ・HFEA 近似）
- LC（ライフサイクル・格付け外の LC判定）: Ayres-Nalebuff 2008/2013（前半2倍→後半1倍、目標額ルール）
- S（報告のみ）: Shiller 1871〜 の信用取引型

約束: 月次リターンは小数。総リターンどうしで比べる。欠測を0で埋めない（RF が欠けたら止める）。
"""
import io, json, math, os, subprocess, sys, statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import numpy as np  # noqa: E402

PREREG = 'mw_levdca_prereg.json'
PREREG2 = 'mw_levdca_prereg2.json'
PREREG3 = 'mw_levdca_prereg3.json'
OUT = 'mw_levdca.json'
TAX = 0.20315
FEE_ETF, SPREAD_ETF = 0.009, 0.005      # レバレッジETF型（mw_common.lever_daily の既定と同じ）
SPREAD_MARGIN = 0.015                   # 信用取引の借入 = RF + 1.5%/年
COST_UNIT = 0.001                       # 片道 100% あたり 0.10%（大型株）
NDX_DIV, QQQ_FEE = 0.003, 0.002         # 1999-03-10 までの ^NDX に足す配当の推定・QQQ に足し戻す信託報酬
END_D, END_M = 20260831, 202608         # French の RF の終わり
HORIZONS = (20, 25, 30)
LGRID_KELLY = [round(0.5 + 0.05 * i, 2) for i in range(71)]  # 0.50〜4.00
LGRID_TWIN = [round(1.0 + 0.05 * i, 2) for i in range(21)]    # 1.00〜2.00
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


# ───────────────────────── データ ─────────────────────────
def check_contiguous_months(keys, name):
    for a, b in zip(keys, keys[1:]):
        y, m = divmod(a, 100)
        nb = a + 1 if m < 12 else (y + 1) * 100 + 1
        if b != nb:
            raise ValueError(f'{name}: 月が飛んでいる {a}→{b}（欠けを0で埋めない）')


def french_daily():
    ff = M.ff_factors('daily')
    mkt = {k: v for k, v in ff['mkt'].items() if k <= END_D}
    rf = {k: v for k, v in ff['rf'].items() if k <= END_D}
    miss = [k for k in mkt if k not in rf]
    if miss:
        raise ValueError(f'French 日次: RF の欠け {len(miss)} 日')
    return mkt, rf


def french_monthly():
    ff = M.ff_factors('monthly')
    mkt = {k: v for k, v in ff['mkt'].items() if k <= END_M}
    rf = {k: v for k, v in ff['rf'].items() if k <= END_M}
    check_contiguous_months(sorted(mkt), 'French 月次')
    return mkt, rf


def region(name, freq):
    """French 地域の表 → (総リターン, RF, 欠けで捨てた日数)。欠けは捨てる（0 にしない）"""
    for t, v in M.french_tables(name).items():
        if v['freq'] != freq:
            continue
        i_m, i_rf = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
        tot, rf, skip = {}, {}, 0
        for d, row in v['data'].items():
            if row[i_m] is None or row[i_rf] is None:
                skip += 1
                continue
            if (freq == 'daily' and d > END_D) or (freq == 'monthly' and d > END_M):
                continue
            tot[d] = (row[i_m] + row[i_rf]) / 100
            rf[d] = row[i_rf] / 100
        return tot, rf, skip
    raise KeyError(name)


def ndx_total(div=NDX_DIV, qqq_fee=QQQ_FEE):
    nd = M.yahoo('^NDX', '1d')
    q = M.yahoo('QQQ', '1d')
    out = {}
    for k, v in nd.items():
        if k <= 19990310:
            out[k] = v + div / 252
    for k, v in q.items():
        if 19990311 <= k <= END_D:
            out[k] = v + qqq_fee / 252
    return out


def shiller_tr():
    import xlrd
    b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', 'shiller_ie_data.xls', max_age_days=60)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    P, D = {}, {}
    for i in range(8, sh.nrows):
        row = sh.row_values(i)
        d = row[0]
        if not isinstance(d, float):
            continue
        y = int(d)
        m = int(round((d - y) * 100))
        k = y * 100 + m
        if isinstance(row[1], float) and row[1] > 0:
            P[k] = row[1]
        if isinstance(row[2], float):
            D[k] = row[2]
    ks = sorted(P)
    r = {}
    for a, k in zip(ks, ks[1:]):
        if k in D:
            r[k] = (P[k] + D[k] / 12) / P[a] - 1
    return r


def goyal():
    import openpyxl
    b = M.get('https://docs.google.com/spreadsheets/d/17mw_IpaiLFDrGnrPRQ2o1ugV5nJsZuD1/export?format=xlsx',
              'goyal_predictors_2025.xlsx', max_age_days=60)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = list(wb['Monthly'].iter_rows(values_only=True))
    h = list(rows[0])
    iy, irf, iltr = h.index('yyyymm'), h.index('Rfree'), h.index('ltr')
    rf, ltr = {}, {}
    for r in rows[1:]:
        if r[iy] is None:
            continue
        k = int(r[iy])
        if r[irf] is not None:
            rf[k] = float(r[irf])
        if r[iltr] is not None:
            ltr[k] = float(r[iltr])
    return rf, ltr


# ───────────────────────── 戦略の型 ─────────────────────────
def lev_daily(r, L, rf, spread=SPREAD_ETF, fee=FEE_ETF):
    """日次で L 倍（L>1 は mw_common.lever_daily と同じ式。L≤1 は株 L・残りを RF・費用なし）"""
    for k in r:
        if k not in rf:
            raise ValueError(f'RF の欠け {k}（0 で埋めない）')
    if L > 1:
        return M.lever_daily(r, L, rf, spread=spread, fee=fee)
    return {k: L * v + (1 - L) * rf[k] for k, v in r.items()}


def margin_m(r, L, rf, spread=SPREAD_MARGIN, cost=0.0):
    """月末に L 倍へ戻す信用取引型。戻しの売買 = L×|L−1|×|r − 借入(or 貸付)金利|（持ち分比）に cost を掛けて引く。
    戻り値: (月次リターン, 月次の売買量, 破産した月)"""
    out, tv, ruin = {}, {}, []
    for k, v in r.items():
        if k not in rf:
            raise ValueError(f'RF の欠け {k}')
        rb = rf[k] + (spread / 12 if L > 1 else 0.0)
        g = L * v - (L - 1) * rb
        t = L * abs(L - 1) * abs(v - rb)
        g -= cost * t
        if g <= -1:
            ruin.append(k)
            g = -0.999999  # 系列の統計が壊れないように（破産の月は別に数えて報告する）
        out[k], tv[k] = g, t
    return out, tv, ruin


def mix_m(s, bnd, rf, ws, L, spread=SPREAD_MARGIN, fee=0.0, cost=0.0):
    """株 ws・長期国債 1−ws の混合を L 倍（毎月末に目標へ戻す）。売買 = 各資産の目標とのずれの合計（持ち分比）"""
    wb = 1 - ws
    out, tv = {}, {}
    for k in sorted(set(s) & set(bnd) & set(rf)):
        rb = rf[k] + (spread / 12 if L > 1 else 0.0)
        g = L * (ws * s[k] + wb * bnd[k]) - (L - 1) * rb - fee / 12
        t = L * (ws * abs(s[k] - g) + wb * abs(bnd[k] - g))
        out[k], tv[k] = g - cost * t, t
    return out, tv


def hfea_m(s, bnd, rf, cost=0.0):
    """HFEA 近似: 3倍株 55%・3倍長期国債 45%（ETF型の費用・月次近似）。売買 = 二つの ETF の間の戻し"""
    out, tv = {}, {}
    for k in sorted(set(s) & set(bnd) & set(rf)):
        fin = 2 * (rf[k] + SPREAD_ETF / 12) + FEE_ETF / 12
        u, t3 = 3 * s[k] - fin, 3 * bnd[k] - fin
        g = 0.55 * u + 0.45 * t3
        t = 0.55 * abs(u - g) + 0.45 * abs(t3 - g)
        out[k], tv[k] = g - cost * t, t
    return out, tv


def growth(r):
    x = list(r.values())
    if any(v <= -1 for v in x):
        return -1.0
    return M.cagr(x)


# ───────────────────────── 毎月積立（窓をまとめて numpy で） ─────────────────────────
def sim_const(r, n):
    """一定の月次リターン列 r（np.array）で n か月積立。全起点をまとめて回す。
    戻り値: 最終額, 口座の最大下落, 破産フラグ"""
    W = len(r) - n + 1
    V = np.zeros(W); pk = np.zeros(W); dd = np.zeros(W); ruin = np.zeros(W, bool)
    for t in range(n):
        f = 1 + r[t:t + W]
        ruin |= f <= 0
        V = np.maximum((V + 1) * f, 0.0)
        pk = np.maximum(pk, V)
        dd = np.minimum(dd, np.where(pk > 0, V / np.where(pk > 0, pk, 1) - 1, 0))
    return V, dd, ruin


def sim_policy(r, rb, rf, n, policy):
    """倍率が窓の中で変わる信用取引型（ライフサイクル）。policy(t, V後の持ち分, n) → L の配列。
    月次 = L×r − (L−1)×借入（L>1）/ L×r + (1−L)×RF（L≤1）"""
    W = len(r) - n + 1
    V = np.zeros(W); pk = np.zeros(W); dd = np.zeros(W); ruin = np.zeros(W, bool)
    Ls = []
    for t in range(n):
        V = V + 1
        L = policy(t, V, n)
        rr, bb, ff = r[t:t + W], rb[t:t + W], rf[t:t + W]
        g = np.where(L > 1, L * rr - (L - 1) * bb, L * rr + (1 - L) * ff)
        f = 1 + g
        ruin |= f <= 0
        V = np.maximum(V * f, 0.0)
        pk = np.maximum(pk, V)
        dd = np.minimum(dd, np.where(pk > 0, V / np.where(pk > 0, pk, 1) - 1, 0))
        Ls.append(float(np.mean(L)))
    return V, dd, ruin, Ls


def sim_switch(r_a, r_b, n, switch_t, tax=False):
    """前半 r_a（例: 2倍日次型）→ switch_t か月目の初めに全額を r_b（無レバ）へ乗り換え。tax=True なら乗り換え時と最後に 20.315%"""
    W = len(r_a) - n + 1
    V = np.zeros(W); basis = np.zeros(W); pk = np.zeros(W); dd = np.zeros(W); ruin = np.zeros(W, bool)
    for t in range(n):
        if t == switch_t and tax:
            gain = np.maximum(V - basis, 0)
            V = V - TAX * gain
            basis = V.copy()
        V = V + 1; basis = basis + 1
        f = 1 + (r_a[t:t + W] if t < switch_t else r_b[t:t + W])
        ruin |= f <= 0
        V = np.maximum(V * f, 0.0)
        pk = np.maximum(pk, V)
        dd = np.minimum(dd, np.where(pk > 0, V / np.where(pk > 0, pk, 1) - 1, 0))
    if tax:
        V = V - TAX * np.maximum(V - basis, 0)
    return V, dd, ruin


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else None


def dca_summary(keys, n, Vs, Vb, dds, ddb, ruin=None):
    """窓の最終額（戦略 Vs・無レバ Vb）→ 訓練の窓（終点≤2006-12）・保有の窓（終点≥2007-01）・全窓の要約"""
    W = len(Vs)
    ends = np.array([keys[i + n - 1] for i in range(W)])
    starts = np.array([keys[i] for i in range(W)])
    out = {}
    for lab, mask in (('train_windows', ends <= M.TRAIN_END), ('hold_windows', ends >= M.HOLD_START), ('all_windows', ends > 0)):
        if not mask.any():
            out[lab] = None
            continue
        s, b = Vs[mask], Vb[mask]
        ratio = s / b
        i_min = int(np.argmin(ratio))
        ms, mb = s / n, b / n
        out[lab] = {
            'windows': int(mask.sum()), 'first_start': int(starts[mask][0]), 'last_start': int(starts[mask][-1]),
            'win_rate': round(float(np.mean(s > b)), 3),
            'ratio_median': round(pct(ratio, 50), 3), 'ratio_p05': round(pct(ratio, 5), 3),
            'ratio_worst': [int(starts[mask][i_min]), round(float(ratio[i_min]), 3)],
            'ratio_best': round(float(ratio.max()), 3),
            'below_contrib_s': round(float(np.mean(ms < 1)), 3), 'below_contrib_b': round(float(np.mean(mb < 1)), 3),
            'mult_median_s': round(pct(ms, 50), 3), 'mult_median_b': round(pct(mb, 50), 3),
            'mult_p05_s': round(pct(ms, 5), 3), 'mult_p05_b': round(pct(mb, 5), 3),
            'mult_min_s': round(float(ms.min()), 3), 'mult_min_b': round(float(mb.min()), 3),
            'acct_dd_median_s': round(pct(dds[mask], 50) * 100, 1), 'acct_dd_worst_s': round(float(dds[mask].min()) * 100, 1),
            'acct_dd_median_b': round(pct(ddb[mask], 50) * 100, 1), 'acct_dd_worst_b': round(float(ddb[mask].min()) * 100, 1),
            'ruined_windows': int(ruin[mask].sum()) if ruin is not None else 0,
        }
    return out


def arr(d, keys):
    return np.array([d[k] for k in keys])


def dca_block(s, b, rf=None, tax_etf=False):
    """一定型の戦略 s と無レバ b の毎月積立（20/25/30年・1か月刻み）＋10年（起点 2007-01 以降）"""
    keys = sorted(set(s) & set(b))
    check_contiguous_months(keys, 'dca')
    rs, rb_ = arr(s, keys), arr(b, keys)
    res = {}
    for H in HORIZONS + (10,):
        n = H * 12
        if len(keys) < n:
            continue
        Vs, dds, ru = sim_const(rs, n)
        Vb, ddb, _ = sim_const(rb_, n)
        if H == 10:
            st = np.array(keys[:len(Vs)])
            m = st >= M.HOLD_START
            if not m.any():
                continue
            res['10y_start_2007plus'] = {'windows': int(m.sum()), 'win_rate': round(float(np.mean(Vs[m] > Vb[m])), 3),
                                         'ratio_median': round(pct(Vs[m] / Vb[m], 50), 3), 'ratio_worst': round(float((Vs[m] / Vb[m]).min()), 3)}
            continue
        d = dca_summary(keys, n, Vs, Vb, dds, ddb, ru)
        if tax_etf:
            aft = Vs - TAX * np.maximum(Vs - n, 0)
            b_tax = Vb - TAX * np.maximum(Vb - n, 0)
            ends = np.array([keys[i + n - 1] for i in range(len(Vs))])
            d['tax_japan'] = {}
            for lab, mask in (('train_windows', ends <= M.TRAIN_END), ('hold_windows', ends >= M.HOLD_START), ('all_windows', ends > 0)):
                if mask.any():
                    d['tax_japan'][lab] = {
                        'win_vs_unlevered_nisa': round(float(np.mean(aft[mask] > Vb[mask])), 3),
                        'win_vs_unlevered_taxable': round(float(np.mean(aft[mask] > b_tax[mask])), 3),
                        'ratio_median_vs_nisa': round(pct(aft[mask] / Vb[mask], 50), 3),
                        'ratio_worst_vs_nisa': round(float((aft[mask] / Vb[mask]).min()), 3)}
        res[f'{H}y'] = d
    return res


# ───────────────────────── 評価（格付けする系列） ─────────────────────────
def evaluate(name, fam, desc, s, b, rf, *, s_net=None, lev=True, extra=None):
    e = {'name': name, 'family': fam, 'description': desc, 'leveraged_or_timing': lev}
    e['full'] = M.excess_stats(s, b)
    e['train'] = M.excess_stats(s, b, z=M.TRAIN_END)
    e['hold'] = M.excess_stats(s, b, a=M.HOLD_START)
    e['recent'] = M.excess_stats(s, b, a=M.RECENT_START)
    e['cost_hold'] = M.excess_stats(s_net if s_net is not None else s, b, a=M.HOLD_START)
    e['roll20'] = M.rolling(s, b, 20)
    e['dca20_mw'] = M.dca(s, b, 20)
    e['sharpe'] = {'train': (M.sharpe(s, rf, z=M.TRAIN_END), M.sharpe(b, rf, z=M.TRAIN_END)),
                   'hold': (M.sharpe(s, rf, a=M.HOLD_START), M.sharpe(b, rf, a=M.HOLD_START)),
                   'full': (M.sharpe(s, rf), M.sharpe(b, rf))}
    e['maxdd'] = {'full_s': round(M.maxdd(s) * 100, 1), 'full_b': round(M.maxdd(b) * 100, 1),
                  'hold_s': round(M.maxdd(M.window(s, M.HOLD_START)) * 100, 1), 'hold_b': round(M.maxdd(M.window(b, M.HOLD_START)) * 100, 1)}
    if extra:
        e.update(extra)
    return e


def finish_grade(e, holm_p, repl):
    e['holm_p_hold'] = holm_p
    e['repl'] = repl
    sp = {'train': e['sharpe']['train'], 'hold': e['sharpe']['hold']}
    g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=repl,
                   family_holm_p=holm_p, sharpe_pair=sp, leveraged_or_timing=e['leveraged_or_timing'])
    e['grade'], e['criteria'] = g, c
    return e


def kelly_pick(make, lo=None, hi=M.TRAIN_END):
    """訓練期間の年率（幾何）を最大にする L（グリッド）。make(L) → 月次系列"""
    best, table = None, []
    for L in LGRID_KELLY:
        g = growth(M.window(make(L), lo, hi))
        table.append((L, round(g * 100, 2)))
        if best is None or g > best[1]:
            best = (L, g)
    half = round(round(best[0] / 2 / 0.05) * 0.05, 2)
    return best[0], half, table


# ───────────────────────── 本体 ─────────────────────────
def main():
    prereg_sha = subprocess.run(['git', 'log', '-1', '--format=%H', '--', f'out/{PREREG}'], cwd=M.BASE,
                                capture_output=True, text=True).stdout.strip()
    log('prereg commit', prereg_sha)

    # データ
    mkt_d, rf_d = french_daily()
    mkt_m, rf_m = french_monthly()
    mkt_dm = M.to_monthly(mkt_d)
    rf_dm = M.to_monthly(rf_d)
    ndx_d = ndx_total()
    ndx_m = M.to_monthly(ndx_d)
    sanity = {}
    sanity['french_mkt_cagr_full'] = round(M.cagr(mkt_m) * 100, 2)
    sanity['french_mkt_cagr_2007'] = round(M.cagr(M.window(mkt_m, M.HOLD_START)) * 100, 2)
    sanity['daily_to_monthly_vs_monthly_file'] = M.excess_stats(mkt_dm, mkt_m)
    l1 = M.to_monthly(M.lever_daily(mkt_d, 1.0, rf_d, spread=0.0, fee=0.0))
    sanity['L1_nofee_equals_market_maxabsdiff'] = max(abs(l1[k] - mkt_dm[k]) for k in mkt_dm)
    ndx_px = M.yahoo('^NDX', '1d')
    qq = M.yahoo('QQQ', '1d')
    ov = sorted(k for k in set(ndx_px) & set(qq) if 19990311 <= k <= END_D)
    sanity['ndx_splice_overlap'] = {'days': len(ov), 'qqq_minus_ndxprice_ann_pct': round(S.mean(qq[k] - ndx_px[k] for k in ov) * 252 * 100, 2),
                                    'note': 'QQQ(配当込み・信託報酬控除後) − ^NDX 価格 の年率差 ≈ 配当利回り − 信託報酬'}
    sanity['ndx_daily_extremes'] = [min(ndx_d.values()), max(ndx_d.values())]
    log('sanity', json.dumps(sanity, ensure_ascii=False)[:600])

    tested = []
    fam_P, fam_E = [], []

    # ── P1: French 日次リセット
    for L in (1.25, 1.5, 2.0, 3.0):
        s = M.to_monthly(lev_daily(mkt_d, L, rf_d))
        e = evaluate(f'P1_daily_L{L:g}', 'P', f'French 市場を毎日 {L:g} 倍に保つ（レバレッジETF型: 信託報酬0.9%・借入RF+0.5%）', s, mkt_dm, rf_m,
                     extra={'L': L, 'kind': 'daily', 'underlying': 'french'})
        e['dca'] = dca_block(s, mkt_dm, tax_etf=True)
        fam_P.append(e)
    # ── P2: French 月次 信用取引
    for L in (1.25, 1.5, 2.0):
        s, tv, ruin = margin_m(mkt_m, L, rf_m)
        sn, _, _ = margin_m(mkt_m, L, rf_m, cost=COST_UNIT)
        e = evaluate(f'P2_margin_L{L:g}', 'P', f'French 市場を毎月末に {L:g} 倍へ戻す信用取引（借入 RF+1.5%・戻しの売買に0.10%）', s, mkt_m, rf_m, s_net=sn,
                     extra={'L': L, 'kind': 'margin', 'underlying': 'french', 'ruin_months': ruin,
                            'turnover_ann_train': round(S.mean(v for k, v in tv.items() if k <= M.TRAIN_END) * 12, 3),
                            'turnover_ann_hold': round(S.mean(v for k, v in tv.items() if k >= M.HOLD_START) * 12, 3)})
        e['dca'] = dca_block(sn, mkt_m)
        fam_P.append(e)
    # ── P3: NASDAQ-100 日次リセット
    for L in (1.25, 1.5, 2.0):
        s = M.to_monthly(lev_daily(ndx_d, L, rf_d))
        e = evaluate(f'P3_ndx_daily_L{L:g}', 'P', f'NASDAQ-100 総リターン推定を毎日 {L:g} 倍（レバレッジETF型）', s, ndx_m, rf_m,
                     extra={'L': L, 'kind': 'daily', 'underlying': 'ndx'})
        e['dca'] = dca_block(s, ndx_m, tax_etf=True)
        fam_P.append(e)
    # 事前登録1の感度（報告のみ）: NASDAQ-100 の 1999-03 以前の配当推定 0.0% / 0.6%
    ndx_sens = {}
    for dv in (0.0, 0.006):
        nd2 = ndx_total(div=dv); nm2 = M.to_monthly(nd2)
        ndx_sens[f'div{dv:.1%}'] = {f'L{L:g}': {'full': M.excess_stats(M.to_monthly(lev_daily(nd2, L, rf_d)), nm2),
                                              'train': M.excess_stats(M.to_monthly(lev_daily(nd2, L, rf_d)), nm2, z=M.TRAIN_END)}
                                    for L in (1.5, 2.0)}
    sanity['ndx_dividend_sensitivity_report_only'] = ndx_sens
    # ── P4: ケリー（訓練だけで L を決める）
    kel = {}
    Lk, Lh, tab = kelly_pick(lambda L: M.to_monthly(lev_daily(mkt_d, L, rf_d)))
    kel['daily'] = {'kelly': Lk, 'half': Lh, 'train_grid_cagr': tab}
    Lk2, Lh2, tab2 = kelly_pick(lambda L: margin_m(mkt_m, L, rf_m)[0])
    kel['margin'] = {'kelly': Lk2, 'half': Lh2, 'train_grid_cagr': tab2}
    Lk3, Lh3, tab3 = kelly_pick(lambda L: M.to_monthly(lev_daily(ndx_d, L, rf_d)))
    kel['ndx'] = {'kelly': Lk3, 'half': Lh3, 'train_grid_cagr': tab3}
    log('kelly (train only)', {k: (v['kelly'], v['half']) for k, v in kel.items()})
    for tag, L in (('kelly', Lk), ('halfkelly', Lh)):
        s = M.to_monthly(lev_daily(mkt_d, L, rf_d))
        e = evaluate(f'P4_{tag}_daily', 'P', f'French 日次型・訓練期間のケリー{"最適" if tag == "kelly" else "の半分"} L={L:g}', s, mkt_dm, rf_m,
                     extra={'L': L, 'kind': 'daily', 'underlying': 'french'})
        e['dca'] = dca_block(s, mkt_dm, tax_etf=True)
        fam_P.append(e)
    for tag, L in (('kelly', Lk2), ('halfkelly', Lh2)):
        s, tv, ruin = margin_m(mkt_m, L, rf_m)
        sn, _, _ = margin_m(mkt_m, L, rf_m, cost=COST_UNIT)
        e = evaluate(f'P4_{tag}_margin', 'P', f'French 信用取引型・訓練期間のケリー{"最適" if tag == "kelly" else "の半分"} L={L:g}', s, mkt_m, rf_m, s_net=sn,
                     extra={'L': L, 'kind': 'margin', 'underlying': 'french', 'ruin_months': ruin})
        e['dca'] = dca_block(sn, mkt_m)
        fam_P.append(e)
    for tag, L in (('kelly', Lk3), ('halfkelly', Lh3)):
        s = M.to_monthly(lev_daily(ndx_d, L, rf_d))
        e = evaluate(f'P4_{tag}_ndx', 'P', f'NASDAQ-100 日次型・訓練期間（1985-10〜2006-12）のケリー{"最適" if tag == "kelly" else "の半分"} L={L:g}', s, ndx_m, rf_m,
                     extra={'L': L, 'kind': 'daily', 'underlying': 'ndx'})
        e['dca'] = dca_block(s, ndx_m, tax_etf=True)
        fam_P.append(e)
    # 事後（判定に使わない）: 保有期間の最適 L
    post = {'daily': kelly_pick(lambda L: M.to_monthly(lev_daily(mkt_d, L, rf_d)), lo=M.HOLD_START, hi=None)[0],
            'margin': kelly_pick(lambda L: margin_m(mkt_m, L, rf_m)[0], lo=M.HOLD_START, hi=None)[0],
            'ndx': kelly_pick(lambda L: M.to_monthly(lev_daily(ndx_d, L, rf_d)), lo=M.HOLD_START, hi=None)[0]}
    kel['post_hoc_hold_optimal_L_事後'] = post

    # ── 地域の再現（C5）
    reg_d = {n: region(f'{n}_3_Factors_Daily', 'daily') for n in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan')}
    reg_m = {n: region(f'{n}_3_Factors', 'monthly') for n in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan')}
    reg_m['Emerging'] = region('Emerging_5_Factors', 'monthly')
    repl_cache = {}

    def repl_for(kind, L):
        key = (kind, L)
        if key in repl_cache:
            return repl_cache[key]
        det = {}
        if kind == 'daily':
            for n, (tot, rf, skip) in reg_d.items():
                s = M.to_monthly(lev_daily(tot, L, rf)); b = M.to_monthly(tot)
                full, hold = M.excess_stats(s, b), M.excess_stats(s, b, a=M.HOLD_START)
                det[n] = {'full': full, 'hold': hold, 'positive': bool(full and full['ex_ann'] > 0 and full['cagr_diff'] > 0), 'skipped_days': skip}
        else:
            for n, (tot, rf, skip) in reg_m.items():
                s = margin_m(tot, L, rf)[0]
                full, hold = M.excess_stats(s, tot), M.excess_stats(s, tot, a=M.HOLD_START)
                det[n] = {'full': full, 'hold': hold, 'positive': bool(full and full['ex_ann'] > 0 and full['cagr_diff'] > 0), 'skipped_months': skip}
        r = {'regions': len(det), 'positive': sum(1 for v in det.values() if v['positive']), 'detail': det}
        repl_cache[key] = r
        return r

    # ── 信用取引の維持率割れの診断（月中の日次の最安値）
    def margin_calls(L):
        by_m = {}
        for k in sorted(mkt_d):
            by_m.setdefault(k // 100, []).append(mkt_d[k])
        hits = []
        for ym, xs in by_m.items():
            c, cmin = 1.0, 1.0
            for x in xs:
                c *= 1 + x; cmin = min(cmin, c)
            ratio = (L * cmin - (L - 1)) / (L * cmin) if L * cmin > 0 else -1
            if ratio < 0.25:
                hits.append((ym, round(cmin - 1, 3)))
        return {'months': len(hits), 'list': hits[:30]}

    for e in fam_P:
        if e['kind'] == 'margin' and e['L'] > 1:
            e['margin_call_months_maint25'] = margin_calls(e['L'])

    # ── E1: 株＋長期国債（探索）
    gy_rf, ltr = goyal()
    s_m = {k: v for k, v in mkt_m.items() if k in ltr}
    b_m = {k: ltr[k] for k in s_m}
    rf_e = {k: rf_m[k] for k in s_m}
    tr_keys = [k for k in s_m if k <= M.TRAIN_END]
    sig_s = S.stdev([s_m[k] for k in tr_keys]); sig_b = S.stdev([b_m[k] for k in tr_keys])
    w_rp = (1 / sig_s) / (1 / sig_s + 1 / sig_b)
    rp0 = [w_rp * s_m[k] + (1 - w_rp) * b_m[k] for k in tr_keys]
    L_rp = sig_s / S.stdev(rp0)
    e1_params = {'train_sigma_stock_m': round(sig_s, 5), 'train_sigma_bond_m': round(sig_b, 5), 'w_stock_rp': round(w_rp, 4), 'L_rp': round(L_rp, 3)}
    log('E1 params (train only)', e1_params)
    e1_specs = [
        ('E1a_6040_L1', '株60/長期国債40・無レバ（参照）', dict(ws=0.6, L=1.0), False),
        ('E1b_6040_L1.5', '60/40 を 1.5 倍（信用取引 RF+1.5%）', dict(ws=0.6, L=1.5), True),
        ('E1c_6040_L2', '60/40 を 2 倍（信用取引 RF+1.5%）', dict(ws=0.6, L=2.0), True),
        ('E1d_rp_train', f'リスクパリティ（訓練固定: 株{w_rp:.1%}・倍率{L_rp:.2f}・RF+1.5%）', dict(ws=w_rp, L=L_rp), True),
        ('E1f_rp_train_futures', f'リスクパリティ（同じ重み・倍率・借入 RF+0.5%）', dict(ws=w_rp, L=L_rp, spread=0.005), True),
    ]
    for name, desc, kw, lev in e1_specs:
        s, tv = mix_m(s_m, b_m, rf_e, **kw)
        sn, _ = mix_m(s_m, b_m, rf_e, cost=COST_UNIT, **kw)
        e = evaluate(name, 'E1', desc, s, s_m, rf_e, s_net=sn, lev=lev,
                     extra={'L': kw['L'], 'kind': 'mix', 'underlying': 'french+ltr', 'w_stock': kw['ws'],
                            'turnover_ann_hold': round(S.mean(v for k, v in tv.items() if k >= M.HOLD_START) * 12, 3),
                            'post_publication_2013': M.excess_stats(s, s_m, a=201301)})
        e['dca'] = dca_block(sn, s_m)
        fam_E.append(e)
    s, tv = hfea_m(s_m, b_m, rf_e)
    sn, _ = hfea_m(s_m, b_m, rf_e, cost=COST_UNIT)
    e = evaluate('E1e_hfea_approx', 'E1', 'HFEA 近似（3倍株55%・3倍長期国債45%・ETF型の費用・月次近似）', s, s_m, rf_e, s_net=sn,
                 extra={'L': 3.0, 'kind': 'mix', 'underlying': 'french+ltr', 'w_stock': 0.55,
                        'turnover_ann_hold': round(S.mean(v for k, v in tv.items() if k >= M.HOLD_START) * 12, 3)})
    e['dca'] = dca_block(sn, s_m)
    fam_E.append(e)

    # ── Holm と格付け
    hp = M.holm({e['name']: (e['hold'] or {}).get('p') for e in fam_P})
    hpe = M.holm({e['name']: (e['hold'] or {}).get('p') for e in fam_P + fam_E})
    for e in fam_P:
        repl = repl_for('daily' if e['kind'] == 'daily' else 'margin', e['L'])
        finish_grade(e, hp.get(e['name']), repl)
        tested.append(e)
    for e in fam_E:
        finish_grade(e, hpe.get(e['name']), None)
        tested.append(e)

    # ── LC: ライフサイクル（格付け外の LC判定）
    lc = []
    keys_m = sorted(mkt_m)
    r_m, rf_a = arr(mkt_m, keys_m), arr(rf_m, keys_m)
    rb_a = rf_a + SPREAD_MARGIN / 12

    def pv_remaining(t, n, rate=0.03):
        m = n - 1 - t  # この月の積立の後に残る回数
        i = (1 + rate) ** (1 / 12) - 1
        return (1 - (1 + i) ** (-m)) / i if m > 0 else 0.0

    pol_half = lambda t, V, n: np.full_like(V, 2.0 if t < n // 2 else 1.0)  # noqa: E731
    pol_target = lambda t, V, n: np.minimum(2.0, 1.0 + pv_remaining(t, n) / np.maximum(V, 1e-12))  # noqa: E731

    def const_pol(L):
        return lambda t, V, n: np.full_like(V, L)

    def lc_eval(name, desc, keys, r, rb, rf, policy, twin_kind, base_r, extra_masks=None):
        res = {'name': name, 'family': 'LC', 'description': desc, 'grade': 'N/A（月次系列なし・LC判定を見る）', 'horizons': {}}
        for H in HORIZONS:
            n = H * 12
            if len(keys) < n:
                continue
            V, dd, ru, Ls = sim_policy(r, rb, rf, n, policy)
            Vb, ddb, _ = sim_const(base_r, n)
            d = dca_summary(keys, n, V, Vb, dd, ddb, ru)
            d['avg_leverage_path'] = [round(x, 3) for x in Ls[::12]]
            # 双子（W4）: 同じ構造の一定 L で訓練の窓の中央値がライフサイクル以上になる最小の L
            ends = np.array([keys[i + n - 1] for i in range(len(V))])
            trm = ends <= M.TRAIN_END
            hom = ends >= M.HOLD_START
            twin = None
            if trm.any():
                med_lc = np.median(V[trm] / n)
                for L in LGRID_TWIN:
                    Vt, _, _, _ = sim_policy(r, rb, rf, n, const_pol(L))
                    if np.median(Vt[trm] / n) >= med_lc:
                        twin = (L, Vt)
                        break
            if twin:
                L, Vt = twin
                d['twin'] = {'L': L,
                             'p05_lc_train': round(pct(V[trm] / n, 5), 3), 'p05_twin_train': round(pct(Vt[trm] / n, 5), 3),
                             'p05_lc_hold': round(pct(V[hom] / n, 5), 3) if hom.any() else None,
                             'p05_twin_hold': round(pct(Vt[hom] / n, 5), 3) if hom.any() else None,
                             'win_vs_twin_all': round(float(np.mean(V > Vt)), 3)}
            else:
                d['twin'] = {'L': None, 'note': '1.00〜2.00 の一定倍率で訓練の中央値に届くものが無い'}
            if extra_masks:
                for lab, fn in extra_masks.items():
                    mm = np.array([fn(keys[i], keys[i + n - 1]) for i in range(len(V))])
                    if mm.any():
                        d[lab] = {'windows': int(mm.sum()), 'win_rate': round(float(np.mean(V[mm] > Vb[mm])), 3),
                                  'ratio_median': round(pct(V[mm] / Vb[mm], 50), 3), 'ratio_worst': round(float((V[mm] / Vb[mm]).min()), 3)}
            res['horizons'][f'{H}y'] = d
        res['LC_judgement'] = lc_judge(res)
        return res

    def lc_judge(res):
        d = res['horizons'].get('20y')
        if not d:
            return None
        tw, hw, aw = d['train_windows'], d['hold_windows'], d['all_windows']
        W1 = bool(tw and tw['win_rate'] >= 0.8)
        W2 = bool(hw and hw['win_rate'] >= 0.8)
        W3 = bool(aw and aw['mult_min_s'] >= aw['mult_min_b'])
        t = d.get('twin') or {}
        W4 = bool(t.get('L') and t.get('p05_lc_hold') is not None and t['p05_lc_train'] >= t['p05_twin_train'] and t['p05_lc_hold'] >= t['p05_twin_hold'])
        return {'W1': W1, 'W2': W2, 'W3': W3, 'W4_efficiency': W4, 'LC_pass': W1 and W2 and W3, 'LC_efficient': W1 and W2 and W3 and W4}

    post_pub = {'end_2009plus': lambda a, z: z >= 200901}
    lc.append(lc_eval('LC1_margin_half', 'French 月次・前半2倍（信用 RF+1.5%）→後半1倍', keys_m, r_m, rb_a, rf_a, pol_half, 'margin', r_m, post_pub))
    lc.append(lc_eval('LC2_margin_target', 'French 月次・Ayres-Nalebuff 目標額ルール（λ=1・上限2倍・残りの積立の現在価値を年3%で割引）', keys_m, r_m, rb_a, rf_a, pol_target, 'margin', r_m, post_pub))

    # LC3/LC4: ETF 型の乗り換え（前半 2倍日次 → 後半 無レバ）
    def lc_switch(name, desc, lev_m, base_m):
        keys = sorted(set(lev_m) & set(base_m))
        check_contiguous_months(keys, name)
        ra, rb2 = arr(lev_m, keys), arr(base_m, keys)
        res = {'name': name, 'family': 'LC', 'description': desc, 'grade': 'N/A（月次系列なし・LC判定を見る）', 'horizons': {}}
        # 双子の候補（一定の日次型 L）
        for H in HORIZONS:
            n = H * 12
            if len(keys) < n:
                continue
            V, dd, ru = sim_switch(ra, rb2, n, n // 2)
            Vb, ddb, _ = sim_const(rb2, n)
            d = dca_summary(keys, n, V, Vb, dd, ddb, ru)
            Vt_tax, _, _ = sim_switch(ra, rb2, n, n // 2, tax=True)
            ends = np.array([keys[i + n - 1] for i in range(len(V))])
            d['tax_japan'] = {}
            for lab, mask in (('train_windows', ends <= M.TRAIN_END), ('hold_windows', ends >= M.HOLD_START), ('all_windows', ends > 0)):
                if mask.any():
                    d['tax_japan'][lab] = {'win_vs_unlevered_nisa': round(float(np.mean(Vt_tax[mask] > Vb[mask])), 3),
                                           'ratio_median_vs_nisa': round(pct(Vt_tax[mask] / Vb[mask], 50), 3)}
            trm, hom = ends <= M.TRAIN_END, ends >= M.HOLD_START
            twin = None
            base_d = res.setdefault('_base_daily', None)
            if trm.any():
                med = np.median(V[trm] / n)
                for L in LGRID_TWIN:
                    lm = lev_cache(desc_under[name], L)
                    Vt, _, _ = sim_const(arr(lm, keys), n)
                    if np.median(Vt[trm] / n) >= med:
                        twin = (L, Vt)
                        break
            if twin:
                L, Vt = twin
                d['twin'] = {'L': L, 'p05_lc_train': round(pct(V[trm] / n, 5), 3), 'p05_twin_train': round(pct(Vt[trm] / n, 5), 3),
                             'p05_lc_hold': round(pct(V[hom] / n, 5), 3) if hom.any() else None,
                             'p05_twin_hold': round(pct(Vt[hom] / n, 5), 3) if hom.any() else None,
                             'win_vs_twin_all': round(float(np.mean(V > Vt)), 3)}
            else:
                d['twin'] = {'L': None}
            res['horizons'][f'{H}y'] = d
        res.pop('_base_daily', None)
        res['LC_judgement'] = lc_judge(res)
        return res

    _lc_cache = {}

    def lev_cache(under, L):
        k = (under, L)
        if k not in _lc_cache:
            src = mkt_d if under == 'french' else ndx_d
            _lc_cache[k] = M.to_monthly(lev_daily(src, L, rf_d))
        return _lc_cache[k]

    desc_under = {'LC3_etf_half': 'french', 'LC4_ndx_etf_half': 'ndx'}
    lc.append(lc_switch('LC3_etf_half', 'French: 前半 2倍日次型 → 後半 無レバへ乗り換え', lev_cache('french', 2.0), mkt_dm))
    lc.append(lc_switch('LC4_ndx_etf_half', 'NASDAQ-100: 前半 2倍日次型 → 後半 無レバへ乗り換え', lev_cache('ndx', 2.0), ndx_m))

    # ── Shiller 1871〜（報告のみ＋LC5）
    sh = shiller_tr()
    sh_keys = sorted(k for k in sh if k in gy_rf)
    check_contiguous_months(sh_keys, 'Shiller')
    sh = {k: sh[k] for k in sh_keys}
    sh_rf = {k: gy_rf[k] for k in sh_keys}
    shiller_rep = []
    for L in (1.25, 1.5, 2.0):
        s, tv, ruin = margin_m(sh, L, sh_rf)
        shiller_rep.append({'name': f'S_shiller_margin_L{L:g}', 'family': 'S', 'L': L,
                            'description': f'Shiller S&P 総リターンを毎月末に {L:g} 倍（借入 Goyal Rfree+1.5%）・報告のみ',
                            'full': M.excess_stats(s, sh), 'pre1926': M.excess_stats(s, sh, z=192606),
                            'train': M.excess_stats(s, sh, z=M.TRAIN_END), 'hold': M.excess_stats(s, sh, a=M.HOLD_START),
                            'sharpe_pre1926': (M.sharpe(s, sh_rf, z=192606), M.sharpe(sh, sh_rf, z=192606)),
                            'sharpe_full': (M.sharpe(s, sh_rf), M.sharpe(sh, sh_rf)),
                            'roll20': M.rolling(s, sh, 20), 'ruin_months': ruin,
                            'dca': dca_block(s, sh), 'grade': '報告のみ（格付けしない）'})
    r_s, rf_s = arr(sh, sh_keys), arr(sh_rf, sh_keys)
    rb_s = rf_s + SPREAD_MARGIN / 12
    pre = {'end_pre1926_07': lambda a, z: z <= 192606}
    lc.append(lc_eval('LC5_shiller_half', 'Shiller 1871〜: 前半2倍→後半1倍（借入 Goyal Rfree+1.5%）', sh_keys, r_s, rb_s, rf_s, pol_half, 'margin', r_s, pre))
    lc.append(lc_eval('LC5_shiller_target', 'Shiller 1871〜: 目標額ルール（λ=1・上限2倍）', sh_keys, r_s, rb_s, rf_s, pol_target, 'margin', r_s, pre))

    # ── ETF 費用モデルの検算（規則は変えない）
    etf_check = {}
    try:
        sp = M.yahoo('^SP500TR', '1d')
        for tk, L, under in (('SSO', 2.0, sp), ('UPRO', 3.0, sp), ('QLD', 2.0, ndx_d), ('TQQQ', 3.0, ndx_d)):
            act = M.yahoo(tk, '1d')
            ks = sorted(k for k in act if k in under and k in rf_d and k <= END_D)
            model = lev_daily({k: under[k] for k in ks}, L, rf_d)
            a_m, m_m = M.to_monthly({k: act[k] for k in ks}), M.to_monthly(model)
            ks_m = sorted(a_m)[1:-1]  # 端の月は欠けがあるので除く
            etf_check[tk] = {'from': ks[0], 'to': ks[-1], 'L': L,
                             'cagr_actual': round(M.cagr([a_m[k] for k in ks_m]) * 100, 2),
                             'cagr_model': round(M.cagr([m_m[k] for k in ks_m]) * 100, 2)}
            etf_check[tk]['model_minus_actual'] = round(etf_check[tk]['cagr_model'] - etf_check[tk]['cagr_actual'], 2)
    except Exception as ex:  # noqa
        etf_check['error'] = str(ex)[:200]

    # ── 探索2（out/mw_levdca_prereg2.json）
    ctx = dict(mkt_d=mkt_d, rf_d=rf_d, mkt_m=mkt_m, rf_m=rf_m, mkt_dm=mkt_dm, ndx_d=ndx_d, ndx_m=ndx_m,
               s_m=s_m, b_m=b_m, rf_e=rf_e, sh=sh, sh_rf=sh_rf, reg_m=reg_m, lev_cache=lev_cache, fam_P=fam_P, fam_E=fam_E)
    r2 = round2(ctx)
    r3 = round3(ctx)

    # ── まとめ
    all_graded = fam_P + fam_E + r2['E2']
    out = {
        'angle': 'levdca', 'prereg': PREREG, 'prereg_commit': prereg_sha,
        'prereg2': PREREG2, 'prereg2_commit': r2['prereg2_commit'],
        'n_tested': len(all_graded) + len(lc) + len(shiller_rep) + len(r2['LCR']),
        'sanity': sanity, 'kelly': kel, 'e1_params_train_only': e1_params, 'etf_model_check': etf_check,
        'round2_verdict_LC2': r2['verdict'],
        'prereg3': PREREG3, 'prereg3_commit': r3['prereg3_commit'], 'round3_bootstrap': r3['result'],
        'tested': all_graded + lc + shiller_rep + r2['LCR'],
        'log': LOG,
    }
    p = M.save(OUT, out)
    log('saved', p)


# ───────────────────────── 探索2 ─────────────────────────
def pv_rem(t, n, rate=0.03):
    m = n - 1 - t
    i = (1 + rate) ** (1 / 12) - 1
    return (1 - (1 + i) ** (-m)) / i if m > 0 else 0.0


def pol_target_gen(cap=2.0, rate=0.03):
    return lambda t, V, n: np.minimum(cap, 1.0 + pv_rem(t, n, rate) / np.maximum(V, 1e-12))


def pol_const(L):
    return lambda t, V, n: np.full_like(V, L)


def sim_general(Nm, n, factor_fn, policy):
    """窓をまとめて積立。factor_fn(L配列, 月の添字配列) → 1+その月の口座リターン（0 以下は破産）"""
    W = Nm - n + 1
    base = np.arange(W)
    V = np.zeros(W); pk = np.zeros(W); dd = np.zeros(W); ruin = np.zeros(W, bool)
    for t in range(n):
        V = V + 1
        L = policy(t, V, n)
        f = factor_fn(L, base + t)
        ruin |= f <= 0
        V = np.maximum(V * f, 0.0)
        pk = np.maximum(pk, V)
        dd = np.minimum(dd, np.where(pk > 0, V / np.where(pk > 0, pk, 1) - 1, 0))
    return V, dd, ruin


def lc_generic(name, desc, keys, factor_fn, base_r, policy, twin=True, horizons=HORIZONS, tax=False, extra_masks=None):
    Nm = len(keys)
    res = {'name': name, 'family': 'LCR', 'description': desc, 'grade': 'N/A（月次系列なし・LC判定を見る）', 'horizons': {}}
    for H in horizons:
        n = H * 12
        if Nm < n:
            continue
        V, dd, ru = sim_general(Nm, n, factor_fn, policy)
        Vb, ddb, _ = sim_const(base_r, n)
        d = dca_summary(keys, n, V, Vb, dd, ddb, ru)
        ends = np.array([keys[i + n - 1] for i in range(len(V))])
        trm, hom = ends <= M.TRAIN_END, ends >= M.HOLD_START
        if twin:
            tw = None
            if trm.any():
                med = np.median(V[trm] / n)
                for L in LGRID_TWIN:
                    Vt, _, _ = sim_general(Nm, n, factor_fn, pol_const(L))
                    if np.median(Vt[trm] / n) >= med:
                        tw = (L, Vt)
                        break
            if tw:
                L, Vt = tw
                d['twin'] = {'L': L, 'p05_lc_train': round(pct(V[trm] / n, 5), 3), 'p05_twin_train': round(pct(Vt[trm] / n, 5), 3),
                             'p05_lc_hold': round(pct(V[hom] / n, 5), 3) if hom.any() else None,
                             'p05_twin_hold': round(pct(Vt[hom] / n, 5), 3) if hom.any() else None,
                             'win_vs_twin_all': round(float(np.mean(V > Vt)), 3)}
            else:
                d['twin'] = {'L': None, 'note': '双子なし（訓練の窓が無いか、1.00〜2.00 で届かない）'}
        if tax:
            aft = V - TAX * np.maximum(V - n, 0)
            d['tax_japan_all_windows'] = {'win_vs_unlevered_nisa': round(float(np.mean(aft > Vb)), 3),
                                          'ratio_median_vs_nisa': round(pct(aft / Vb, 50), 3),
                                          'note': '最後に口座全体の利益へ課税（毎月の戻しの実現益は無視＝楽観側）'}
        if extra_masks:
            for lab, fn in extra_masks.items():
                mm = np.array([fn(keys[i], keys[i + n - 1]) for i in range(len(V))])
                if mm.any():
                    d[lab] = region_rule(V[mm], Vb[mm], n)
        res['horizons'][f'{H}y'] = d
    res['LC_judgement'] = lc_judge_generic(res)
    return res


def lc_judge_generic(res):
    d = res['horizons'].get('20y')
    if not d:
        return None
    tw, hw, aw = d['train_windows'], d['hold_windows'], d['all_windows']
    W1 = bool(tw and tw['win_rate'] >= 0.8)
    W2 = bool(hw and hw['win_rate'] >= 0.8)
    W3 = bool(aw and aw['mult_min_s'] >= aw['mult_min_b'])
    t = d.get('twin') or {}
    W4 = bool(t.get('L') and t.get('p05_lc_hold') is not None and t['p05_lc_train'] >= t['p05_twin_train'] and t['p05_lc_hold'] >= t['p05_twin_hold'])
    return {'W1': W1, 'W2': W2, 'W3': W3, 'W4_efficiency': W4, 'LC_pass': W1 and W2 and W3, 'LC_efficient': W1 and W2 and W3 and W4,
            'W1_train_windows': tw['windows'] if tw else 0}


def region_rule(V, Vb, n):
    r = V / Vb
    out = {'windows': int(len(V)), 'win_rate': round(float(np.mean(V > Vb)), 3), 'ratio_median': round(pct(r, 50), 3),
           'ratio_worst': round(float(r.min()), 3), 'mult_min_s': round(float(V.min() / n), 3), 'mult_min_b': round(float(Vb.min() / n), 3)}
    out['positive'] = bool(out['win_rate'] >= 0.5 and out['ratio_median'] > 1 and out['mult_min_s'] >= out['mult_min_b'])
    return out


def margin_factor(r, rb, rf):
    def f(L, idx):
        rr, bb, ff = r[idx], rb[idx], rf[idx]
        return 1 + np.where(L > 1, L * rr - (L - 1) * bb, L * rr + (1 - L) * ff)
    return f


def round2(ctx):
    sha2 = subprocess.run(['git', 'log', '-1', '--format=%H', '--', f'out/{PREREG2}'], cwd=M.BASE, capture_output=True, text=True).stdout.strip()
    log('prereg2 commit', sha2)
    mkt_d, rf_d, mkt_m, rf_m, mkt_dm = ctx['mkt_d'], ctx['rf_d'], ctx['mkt_m'], ctx['rf_m'], ctx['mkt_dm']
    ndx_d, ndx_m, lev_cache = ctx['ndx_d'], ctx['ndx_m'], ctx['lev_cache']
    LCR = []
    pol = pol_target_gen()

    # LCR1: 月中の追証（維持率30%）
    days_by_m = {}
    for k in sorted(mkt_d):
        days_by_m.setdefault(k // 100, []).append(k)
    keys1 = sorted(days_by_m)
    check_contiguous_months(keys1, 'LCR1')
    Pd, Bd = [], []
    for ym in keys1:
        ds = days_by_m[ym]
        Pd.append(np.cumprod([1 + mkt_d[d] for d in ds]))
        Bd.append(np.cumprod([1 + rf_d[d] + SPREAD_MARGIN / 252 for d in ds]))
    Pend = np.array([p[-1] for p in Pd]); Bend = np.array([b[-1] for b in Bd])
    X = np.array([float(np.max(b / p)) for p, b in zip(Pd, Bd)])
    rf1 = np.array([float(np.prod([1 + rf_d[d] for d in days_by_m[ym]]) - 1) for ym in keys1])
    MAINT = 0.30
    trig_log = {}

    def mc_factor(L, idx):
        f = np.where(L > 1, L * Pend[idx] - (L - 1) * Bend[idx], L * Pend[idx] + (1 - L) * (1 + rf1[idx]))
        trig = (L > 1) & ((L - 1) / np.where(L > 1, L, 1) * X[idx] > 1 - MAINT)
        for w in np.nonzero(trig)[0]:
            m, l = idx[w], L[w]
            P, B = Pd[m], Bd[m]
            thr = (1 - MAINT) * l / (l - 1)
            tau = int(np.argmax(B / P > thr))
            E = l * P[tau] - (l - 1) * B[tau]
            f[w] = E * P[-1] / P[tau] if E > 0 else 0.0
            trig_log[keys1[m]] = trig_log.get(keys1[m], 0) + 1
        return f

    base1 = arr(mkt_dm, keys1)
    e = lc_generic('LCR1_margincall_daily', 'LC2（French 日次）・月中に持ち分比率が30%を割った日の終値で全部返して1倍へ', keys1, mc_factor, base1, pol)
    e['margin_call_months_hit'] = sorted(trig_log)[:40]
    e['margin_call_months_count'] = len(trig_log)
    LCR.append(e)

    # LCR2 / LCR4: 2倍日次型＋無レバの組み合わせ
    def mix_factor(r2, r1):
        def f(L, idx):
            a, b = r2[idx], r1[idx]
            g = (L - 1) * a + (2 - L) * b
            turn = (L - 1) * np.abs(a - g) + (2 - L) * np.abs(b - g)
            return 1 + g - COST_UNIT * turn
        return f

    for name, under, base_m in (('LCR2_etfmix_french', 'french', mkt_dm), ('LCR4_etfmix_ndx', 'ndx', ndx_m)):
        l2 = lev_cache(under, 2.0)
        keys = sorted(set(l2) & set(base_m))
        check_contiguous_months(keys, name)
        r2, r1 = arr(l2, keys), arr(base_m, keys)
        LCR.append(lc_generic(name, f'LC2（{under}）を 2倍日次型 (L−1) ＋ 無レバ (2−L) の組み合わせで作る（追証なし）', keys,
                              mix_factor(r2, r1), r1, pol, tax=True))

    # LCR3: NASDAQ-100 の信用取引型
    keys3 = sorted(k for k in ndx_m if k in rf_m)
    check_contiguous_months(keys3, 'LCR3')
    r3, rf3 = arr(ndx_m, keys3), arr(rf_m, keys3)
    LCR.append(lc_generic('LCR3_margin_ndx', 'LC2（NASDAQ-100 月次・信用 RF+1.5%）', keys3, margin_factor(r3, rf3 + SPREAD_MARGIN / 12, rf3), r3, pol))

    # LCR5: 地域
    reg_res = {}
    for rn, (tot, rf, skip) in ctx['reg_m'].items():
        keys = sorted(tot)
        check_contiguous_months(keys, rn)
        rr, rff = arr(tot, keys), arr(rf, keys)
        n = 240
        V, dd, ru = sim_general(len(keys), n, margin_factor(rr, rff + SPREAD_MARGIN / 12, rff), pol)
        Vb, ddb, _ = sim_const(rr, n)
        rule = region_rule(V, Vb, n)
        rule['first_start'], rule['last_start'] = keys[0], keys[len(V) - 1]
        rule['acct_dd_worst_s'] = round(float(dd.min()) * 100, 1); rule['acct_dd_worst_b'] = round(float(ddb.min()) * 100, 1)
        rule['ruined_windows'] = int(ru.sum())
        reg_res[rn] = rule
    LCR.append({'name': 'LCR5_regions', 'family': 'LCR', 'description': 'LC2（信用 RF+1.5%）を French 地域の月次（米ドル）に当てた 20年窓',
                'grade': 'N/A（再現の点検）', 'regions': reg_res, 'positive': sum(1 for v in reg_res.values() if v['positive']), 'n_regions': len(reg_res)})

    # LCR9: Shiller の 1926年以前に終わる窓
    sh, sh_rf = ctx['sh'], ctx['sh_rf']
    shk = sorted(sh)
    rs, rfs = arr(sh, shk), arr(sh_rf, shk)
    n = 240
    V, dd, ru = sim_general(len(shk), n, margin_factor(rs, rfs + SPREAD_MARGIN / 12, rfs), pol)
    Vb, ddb, _ = sim_const(rs, n)
    ends = np.array([shk[i + n - 1] for i in range(len(V))])
    m = ends <= 192606
    pre = region_rule(V[m], Vb[m], n)
    pre['first_start'], pre['last_start'] = shk[0], shk[int(np.nonzero(m)[0][-1])]
    LCR.append({'name': 'LCR9_shiller_pre1926', 'family': 'LCR', 'description': 'LC2（Shiller・Goyal Rfree+1.5%）のうち終点が 1926-06 以前の 20年窓（独立の時代）',
                'grade': 'N/A（再現の点検）', 'result': pre})

    # 報告のみ: LCR6（上限1.5）・LCR7（RF+3%）・LCR8（割引率）
    keysm = sorted(mkt_m)
    rm, rfm = arr(mkt_m, keysm), arr(rf_m, keysm)
    LCR.append(lc_generic('LCR6_cap1.5', '報告のみ: LC2 の上限 1.5 倍（French 月次・信用 RF+1.5%）', keysm,
                          margin_factor(rm, rfm + SPREAD_MARGIN / 12, rfm), rm, pol_target_gen(cap=1.5), horizons=(20,)))
    LCR.append(lc_generic('LCR7_borrow_rf3', '報告のみ: LC2 の借入 RF+3.0%（French 月次）', keysm,
                          margin_factor(rm, rfm + 0.03 / 12, rfm), rm, pol, horizons=(20,)))
    for rate in (0.01, 0.05):
        LCR.append(lc_generic(f'LCR8_discount{int(rate * 100)}', f'報告のみ: LC2 の割引率 {rate:.0%}（French 月次・信用 RF+1.5%）', keysm,
                              margin_factor(rm, rfm + SPREAD_MARGIN / 12, rfm), rm, pol_target_gen(rate=rate), horizons=(20,)))
    for e in LCR:
        if e['name'].startswith(('LCR6', 'LCR7', 'LCR8')):
            e['report_only'] = True

    # 判定（事前登録2の verdict）
    j = {e['name']: e for e in LCR}
    v = {'LCR1_LC_pass': bool(j['LCR1_margincall_daily']['LC_judgement']['LC_pass']),
         'LCR2_LC_pass': bool(j['LCR2_etfmix_french']['LC_judgement']['LC_pass']),
         'regions_positive': f"{j['LCR5_regions']['positive']}/{j['LCR5_regions']['n_regions']}",
         'regions_ok': j['LCR5_regions']['positive'] >= 3,
         'pre1926_positive': bool(j['LCR9_shiller_pre1926']['result']['positive'])}
    v['LC2_robust'] = v['LCR1_LC_pass'] and v['LCR2_LC_pass'] and v['regions_ok'] and v['pre1926_positive']
    v['missing'] = [k for k in ('LCR1_LC_pass', 'LCR2_LC_pass', 'regions_ok', 'pre1926_positive') if not v[k]]
    log('round2 verdict', v)

    # E2: 積み重ね（格付け）
    s_m, b_m, rf_e = ctx['s_m'], ctx['b_m'], ctx['rf_e']
    E2 = []
    for name, wb in (('E2a_stack_100_50', 0.5), ('E2b_stack_100_100', 1.0)):
        def stack(cost):
            out, tv = {}, {}
            for k in sorted(set(s_m) & set(b_m) & set(rf_e)):
                rb = rf_e[k] + 0.005 / 12
                g = s_m[k] + wb * (b_m[k] - rb)
                t = abs(s_m[k] - g) + wb * abs(b_m[k] - g)
                out[k], tv[k] = g - cost * t, t
            return out, tv
        s, tv = stack(0.0)
        sn, _ = stack(COST_UNIT)
        e = evaluate(name, 'E2', f'株100%＋長期国債{wb:.0%}を借入（RF+0.5%）で積み重ね・毎月末に戻す', s, s_m, rf_e, s_net=sn,
                     extra={'L': 1 + wb, 'kind': 'stack', 'underlying': 'french+ltr',
                            'turnover_ann_hold': round(S.mean(v for k, v in tv.items() if k >= M.HOLD_START) * 12, 3)})
        e['dca'] = dca_block(sn, s_m)
        E2.append(e)
    hp = M.holm({e['name']: (e['hold'] or {}).get('p') for e in ctx['fam_P'] + ctx['fam_E'] + E2})
    for e in E2:
        finish_grade(e, hp.get(e['name']), None)
    return {'LCR': LCR, 'E2': E2, 'verdict': v, 'prereg2_commit': sha2}


# ───────────────────────── 探索3: ブロック・ブートストラップ ─────────────────────────
def stationary_idx(rng, N, n, paths, mean_block=24):
    p = 1.0 / mean_block
    idx = np.empty((paths, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, N, paths)
    for t in range(1, n):
        new = rng.random(paths) < p
        idx[:, t] = np.where(new, rng.integers(0, N, paths), (idx[:, t - 1] + 1) % N)
    return idx


def boot_dca(n, step):
    """step(t, V) → 1+その月の口座リターン（全パスの配列）。戻り値: 最終額, 口座の最大下落"""
    V = None; pk = None; dd = None
    for t in range(n):
        V = (np.zeros_like(step.shape_ref) if V is None else V) + 1
        f = step(t, V)
        V = np.maximum(V * f, 0.0)
        pk = V.copy() if pk is None else np.maximum(pk, V)
        dd = np.zeros_like(V) if dd is None else dd
        dd = np.minimum(dd, np.where(pk > 0, V / np.where(pk > 0, pk, 1) - 1, 0))
    return V, dd


def round3(ctx):
    sha3 = subprocess.run(['git', 'log', '-1', '--format=%H', '--', f'out/{PREREG3}'], cwd=M.BASE, capture_output=True, text=True).stdout.strip()
    log('prereg3 commit', sha3)
    mkt_m, rf_m, mkt_dm = ctx['mkt_m'], ctx['rf_m'], ctx['mkt_dm']
    r2x_m = ctx['lev_cache']('french', 2.0)
    keys = sorted(set(mkt_m) & set(rf_m) & set(mkt_dm) & set(r2x_m))
    check_contiguous_months(keys, 'boot')
    A = {'m': arr(mkt_m, keys), 'rf': arr(rf_m, keys), 'dm': arr(mkt_dm, keys), 'r2': arr(r2x_m, keys)}
    N, n, PATHS = len(keys), 240, 10000
    rng = np.random.default_rng(20260928)
    idx = stationary_idx(rng, N, n, PATHS, 24)
    res = {'paths': PATHS, 'months': n, 'mean_block': 24, 'seed': 20260928, 'data': f'{keys[0]}〜{keys[-1]}', 'scenarios': {}}
    for sc in ('hist', 'erp_minus3', 'borrow_rf3'):
        cut = 0.0025 if sc == 'erp_minus3' else 0.0
        spread = (0.03 if sc == 'borrow_rf3' else SPREAD_MARGIN) / 12
        m = A['m'][idx] - cut; rf = A['rf'][idx]; dm = A['dm'][idx] - cut; r2 = A['r2'][idx] - 2 * cut
        rb = rf + spread

        def run(fn):
            fn.shape_ref = np.zeros(PATHS)
            return boot_dca(n, fn)

        def margin_step(policy):
            def f(t, V):
                L = policy(t, V, n)
                return 1 + np.where(L > 1, L * m[:, t] - (L - 1) * rb[:, t], L * m[:, t] + (1 - L) * rf[:, t])
            return f

        def mix_step(policy):
            def f(t, V):
                L = policy(t, V, n)
                a, b = r2[:, t], dm[:, t]
                g = (L - 1) * a + (2 - L) * b
                return 1 + g - COST_UNIT * ((L - 1) * np.abs(a - g) + (2 - L) * np.abs(b - g))
            return f

        base_m, dd_bm = run(lambda t, V: 1 + m[:, t])
        base_d, dd_bd = run(lambda t, V: 1 + dm[:, t])
        strat = {'LC2': (margin_step(pol_target_gen()), 'm'), 'LC2_cap1.5': (margin_step(pol_target_gen(cap=1.5)), 'm'),
                 'const_margin_1.25': (margin_step(pol_const(1.25)), 'm'), 'const_margin_1.5': (margin_step(pol_const(1.5)), 'm')}
        if sc != 'borrow_rf3':
            strat['P1_daily_2x'] = (lambda t, V: 1 + r2[:, t], 'd')
            strat['LCR2_etfmix'] = (mix_step(pol_target_gen()), 'd')
        out = {}
        for name, (fn, bk) in strat.items():
            V, dd = run(fn)
            Vb, ddb = (base_m, dd_bm) if bk == 'm' else (base_d, dd_bd)
            ratio = V / Vb
            aft = V - TAX * np.maximum(V - n, 0)
            out[name] = {'win_vs_unlevered': round(float(np.mean(V > Vb)), 4), 'ratio_median': round(pct(ratio, 50), 3), 'ratio_p05': round(pct(ratio, 5), 3),
                         'below_contrib_s': round(float(np.mean(V < n)), 4), 'below_contrib_b': round(float(np.mean(Vb < n)), 4),
                         'mult_p05_s': round(pct(V / n, 5), 3), 'mult_p05_b': round(pct(Vb / n, 5), 3),
                         'mult_median_s': round(pct(V / n, 50), 3), 'mult_median_b': round(pct(Vb / n, 50), 3),
                         'acct_dd_median_s': round(pct(dd, 50) * 100, 1), 'acct_dd_median_b': round(pct(ddb, 50) * 100, 1),
                         'aftertax_win_vs_unlevered_nisa': round(float(np.mean(aft > Vb)), 4),
                         'aftertax_ratio_median_vs_nisa': round(pct(aft / Vb, 50), 3)}
        res['scenarios'][sc] = out
        log('boot', sc, {k: (v['win_vs_unlevered'], v['mult_p05_s'], v['mult_p05_b'], v['aftertax_win_vs_unlevered_nisa']) for k, v in out.items()})
    h, e3 = res['scenarios']['hist']['LC2'], res['scenarios']['erp_minus3']['LC2']
    res['reading'] = {
        'LC2_survives_bootstrap': bool(h['win_vs_unlevered'] >= 0.8 and h['mult_p05_s'] >= h['mult_p05_b']),
        'LC2_vanishes_if_erp_minus3': bool(e3['win_vs_unlevered'] < 0.5),
        'tax_eats_win_hist': bool(h['aftertax_win_vs_unlevered_nisa'] < 0.5),
        'tax_eats_win_erp_minus3': bool(e3['aftertax_win_vs_unlevered_nisa'] < 0.5)}
    log('round3 reading', res['reading'])
    return {'result': res, 'prereg3_commit': sha3}


if __name__ == '__main__':
    main()
