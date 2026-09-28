#!/usr/bin/env python3
"""night/mw_trend.py — 『市場に勝てる歴史検証』角度 trend: トレンド追随の市場タイミング（レバレッジなし・あり）

読むだけ（門の判定・採点・配分には不使用）。事前登録 out/mw_trend_prereg.json の規則をそのまま測り、
out/mw_trend.json へ書く。線は out/mw_prereg.json（mw_common.grade）。

規則（論文の既定値・結果を見る前に固定）
- Faber (2007): 月末の総リターン指数 > 10か月平均 → 翌月は株、ほかは短期金利
- Gayed & Bilello (2016): 価格指数 > 200営業日平均 → 日々L倍（L=1,1.25,1.5,2,3）、ほかは短期金利。
  信号は t の終値、売買は t+1 の終値（1日遅れ）＝ t+2 日目のリターンから新しい持ち方
- Moskowitz-Ooi-Pedersen (2012): 直近12か月の超過 > 0 → 株、ほかは短期金利

相手（判定の主）は同じ指数をレバレッジなしで買って持つだけ。総リターンどうしで比べる。
"""
import sys, os, json, math, datetime, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PRE_NAME = 'mw_trend_prereg.json'
OUT_NAME = 'mw_trend.json'
COST = 0.001      # 判定用: 持ち替え1回あたり資産の0.10%（全体の事前登録の既定）
COST_LO = 0.0005  # 報告: 指示書の0.05%
TAX = 0.20315
SPREAD, FEE = 0.005, 0.009
YH_P2 = 1790000000  # Yahoo の取得の終わり（2026-09-21・キャッシュの再現のため固定。French の終わり 2026-08-31 で切る）
NDX_DIV, IXIC_DIV = 0.005, 0.010
FR_END = 20260831

LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── データ ─────────────────────────
def yh_daily(tk):
    """Yahoo 日次 → (終値 dict, 調整後終値 dict) キーは yyyymmdd"""
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1=-2000000000&period2={YH_P2}&interval=1d&events=div%2Csplit'
    j = json.loads(M.get(u, name=f'trend_yh_{tk.replace("^", "IDX_")}_1d_full.json', max_age_days=3650))
    r = j['chart']['result'][0]
    cl = r['indicators']['quote'][0]['close']
    adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or cl
    px, pa = {}, {}
    for t, c, a in zip(r['timestamp'], cl, adj):
        d = datetime.datetime.utcfromtimestamp(t)
        k = d.year * 10000 + d.month * 100 + d.day
        if c is not None:
            px[k] = c
        if a is not None:
            pa[k] = a
    return px, pa


def rets(px):
    ks = sorted(px)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:])}


def fr_region(name, freq):
    """French 地域ファイル → (Mkt 総リターン, RF)（小数）"""
    for t, v in M.french_tables(name).items():
        if v['freq'] == freq:
            ci, ri = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            mkt, rf = {}, {}
            for d, row in v['data'].items():
                if row[ci] is None or row[ri] is None:
                    continue
                mkt[d] = (row[ci] + row[ri]) / 100
                rf[d] = row[ri] / 100
            return mkt, rf
    raise KeyError(name)


def shiller():
    """Shiller ie_data.xls → 月次総リターン {yyyymm: r}（月平均価格・配当のある月まで）"""
    import xlrd
    b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', name='shiller_ie_data.xls', max_age_days=3650)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    P, D = {}, {}
    for i in range(8, sh.nrows):
        row = sh.row_values(i)
        if not isinstance(row[0], float):
            continue
        s = f'{row[0]:.2f}'
        k = int(s[:4]) * 100 + int(s[5:7])
        if isinstance(row[1], float):
            P[k] = row[1]
        if isinstance(row[2], float):
            D[k] = row[2]
    ks = sorted(P)
    r = {}
    for p, k in zip(ks, ks[1:]):
        if k in D and p in P:
            r[k] = (P[k] + D[k] / 12) / P[p] - 1
    return r


def cp_rate():
    """NBER 商業手形金利（年率%）→ 月次の小数リターン {yyyymm: r}"""
    c = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=M13002US35620M156NNBR', name='fred_M13002US35620M156NNBR.csv', max_age_days=3650).decode()
    out = {}
    for line in c.strip().splitlines()[1:]:
        d, v = line.split(',')
        if v in ('', '.'):
            continue
        out[int(d[:4]) * 100 + int(d[5:7])] = float(v) / 1200
    return out


# ───────────────────────── 信号 ─────────────────────────
def sma_sig(px, N):
    """{日付: 価格} → {日付: 0/1}（価格 > 当日を含む N 個の平均）。N 個そろう日から"""
    ks = sorted(px)
    out, run = {}, 0.0
    for i, k in enumerate(ks):
        run += px[k]
        if i >= N:
            run -= px[ks[i - N]]
        if i >= N - 1:
            out[k] = 1 if px[k] > run / N else 0
    return out


def month_end_sig_sma(px, N):
    """日次価格の月末値 > 直近 N か月の月末値の平均 → {月末の日付: 0/1}"""
    ks = sorted(px)
    me = []
    for i, k in enumerate(ks):
        if i == len(ks) - 1 or ks[i + 1] // 100 != k // 100:
            me.append(k)
    out = {}
    for i in range(N - 1, len(me)):
        w = [px[me[j]] for j in range(i - N + 1, i + 1)]
        out[me[i]] = 1 if px[me[i]] > sum(w) / N else 0
    return out


def month_end_sig_tsmom(daily_ex_index, months=12):
    """日次の超過指数（累積）の月末値の12か月前比 > 1 → {月末の日付: 0/1}"""
    ks = sorted(daily_ex_index)
    me = [k for i, k in enumerate(ks) if i == len(ks) - 1 or ks[i + 1] // 100 != k // 100]
    out = {}
    for i in range(months, len(me)):
        out[me[i]] = 1 if daily_ex_index[me[i]] / daily_ex_index[me[i - months]] > 1 else 0
    return out


def map_sig(dates, sig):
    """各日付に『その日以前の最新の信号』を写す（無ければ None）"""
    sk = sorted(sig)
    out, j, cur = [], 0, None
    for d in dates:
        while j < len(sk) and sk[j] <= d:
            cur = sig[sk[j]]; j += 1
        out.append(cur)
    return out


def cum_index(r):
    w, out = 1.0, {}
    for k in sorted(r):
        w *= 1 + r[k]; out[k] = w
    return out


# ───────────────────────── 実行 ─────────────────────────
def lev_ret(v, f, L, per):
    if L == 1:
        return v
    x = L * v - (L - 1) * (f + SPREAD / per) - FEE / per
    return max(x, -1.0)


def run_daily(D, r, rf, sig_on_D, L, lag=2):
    """日次。position[i] = sig_on_D[i-lag]。戻り値: dict（keys, inv, cash, pos, gross, net, net05, 切替数）。最初の不完全な月は落とす"""
    for d in D:
        if d not in rf or d not in r:
            raise RuntimeError(f'RF かリターンが無い日 {d}（0で埋めない）')
    lev = M.lever_daily({d: r[d] for d in D}, L, {d: rf[d] for d in D}, spread=SPREAD, fee=FEE if L > 1 else 0.0) if L != 1 else {d: r[d] for d in D}
    idx = [i for i in range(lag, len(D)) if sig_on_D[i - lag] is not None]
    if not idx:
        return None
    first_m = D[idx[0]] // 100
    if D[idx[0] - 1] // 100 == first_m:  # 途中の月から始まる → その月を落とす
        idx = [i for i in idx if D[i] // 100 != first_m]
    keys, inv, cash, pos = [], [], [], []
    for i in idx:
        d = D[i]
        keys.append(d); inv.append(max(lev[d], -1.0)); cash.append(rf[d]); pos.append(sig_on_D[i - lag])
    return finish(keys, inv, cash, pos)


def run_monthly(ms, r, rf, sig, L, lag=1):
    """月次。position[k] = sig[ms[k-lag]]（sig は月→0/1）"""
    keys, inv, cash, pos = [], [], [], []
    for i in range(lag, len(ms)):
        s = sig.get(ms[i - lag])
        if s is None:
            continue
        k = ms[i]
        if k not in r or k not in rf:
            raise RuntimeError(f'月 {k} のデータ欠け（0で埋めない）')
        keys.append(k); inv.append(lev_ret(r[k], rf[k], L, 12)); cash.append(rf[k]); pos.append(s)
    return finish(keys, inv, cash, pos)


def finish(keys, inv, cash, pos):
    gross, net, net05 = {}, {}, {}
    sw = 0
    for i, k in enumerate(keys):
        g = inv[i] if pos[i] else cash[i]
        gross[k] = g
        if i > 0 and pos[i] != pos[i - 1]:
            sw += 1
            net[k] = (1 + g) * (1 - COST) - 1
            net05[k] = (1 + g) * (1 - COST_LO) - 1
        else:
            net[k] = g; net05[k] = g
    return {'keys': keys, 'inv': inv, 'cash': cash, 'pos': pos, 'gross': gross, 'net': net, 'net05': net05, 'switches': sw}


# ───────────────────────── 税（日本の課税口座） ─────────────────────────
def tax_sim(keys, inv, cash, pos, yearf, t=TAX, cost=COST):
    """売るたびに実現益へ課税（同じ年は通算・源泉徴収の還付あり）、赤字は3年繰越、現金の利息は受け取るたびに課税、
    窓の終わりに全部売って課税。戻り値: 最終の資産（初期=1）と払った税"""
    st = {'V': 1.0, 'B': None, 'inv': False, 'ytd': 0.0, 'paid': 0.0, 'cf': [], 'year': None, 'taxes': 0.0}

    def avail(y):
        return sum(l for yy, l in st['cf'] if y - 3 <= yy <= y - 1)

    def realize(G):
        st['ytd'] += G
        owed = t * max(0.0, st['ytd'] - avail(st['year']))
        delta = owed - st['paid']
        st['V'] -= delta; st['paid'] = owed; st['taxes'] += delta

    def close_year():
        y = st['year']
        if st['ytd'] < 0:
            st['cf'].append([y, -st['ytd']])
        elif st['ytd'] > 0:
            need = st['ytd']
            for e in st['cf']:
                if y - 3 <= e[0] <= y - 1 and need > 0:
                    u = min(e[1], need); e[1] -= u; need -= u
        st['cf'] = [e for e in st['cf'] if e[1] > 1e-15 and e[0] >= y - 2]
        st['ytd'] = 0.0; st['paid'] = 0.0

    for i, k in enumerate(keys):
        y = yearf(k)
        if st['year'] is None:
            st['year'] = y
        elif y != st['year']:
            close_year(); st['year'] = y
        p = bool(pos[i])
        if i == 0:
            if p:
                st['B'] = st['V']
            st['inv'] = p
        elif p != st['inv']:
            if st['inv']:
                realize(st['V'] - st['B'])
                st['V'] *= 1 - cost
            else:
                st['V'] *= 1 - cost
                st['B'] = st['V']
            st['inv'] = p
        if st['inv']:
            st['V'] *= 1 + inv[i]
        else:
            it = st['V'] * cash[i]
            st['V'] += it * (1 - t) if it > 0 else it
            if it > 0:
                st['taxes'] += it * t
    if st['inv']:
        realize(st['V'] - st['B'])
    return st['V'], st['taxes']


def ann(W, n, per):
    return (W ** (per / n) - 1) if W > 0 and n else None


def tax_report(run, bh_run, per, yearf, windows):
    """run と bh_run は同じ keys。windows = {名前: (a, z)}"""
    out = {}
    for nm, (a, z) in windows.items():
        ix = [i for i, k in enumerate(run['keys']) if (a is None or k >= a) and (z is None or k <= z)]
        if len(ix) < per * 2:
            continue
        sl = lambda arr: [arr[i] for i in ix]
        ks = sl(run['keys'])
        Wt, taxes = tax_sim(ks, sl(run['inv']), sl(run['cash']), sl(run['pos']), yearf)
        Wn, _ = tax_sim(ks, sl(run['inv']), sl(run['cash']), sl(run['pos']), yearf, t=0.0)
        Bt, _ = tax_sim(ks, sl(bh_run['inv']), sl(bh_run['cash']), [1] * len(ix), yearf)
        Bn, _ = tax_sim(ks, sl(bh_run['inv']), sl(bh_run['cash']), [1] * len(ix), yearf, t=0.0)
        n = len(ix)
        f = lambda x: round(ann(x, n, per) * 100, 2) if ann(x, n, per) is not None else None
        out[nm] = {'from': ks[0], 'to': ks[-1], 'taxable_cagr': f(Wt), 'nisa_cagr': f(Wn), 'bh_taxable_cagr': f(Bt), 'bh_nisa_cagr': f(Bn),
                   'taxable_diff': round(f(Wt) - f(Bt), 2) if None not in (f(Wt), f(Bt)) else None,
                   'nisa_diff': round(f(Wn) - f(Bn), 2) if None not in (f(Wn), f(Bn)) else None,
                   'taxes_paid_over_initial': round(taxes, 3)}
    return out


def tax_rolling(run, bh_run, per, yearf, years=20):
    """転がる20年窓（毎年7月起点・一括）で、課税後に買い持ち（課税後）に勝った割合"""
    ks = run['keys']
    if not ks:
        return None
    daily = per > 12
    y0, y1 = (ks[0] // 10000, ks[-1] // 10000) if daily else (ks[0] // 100, ks[-1] // 100)
    res = []
    for y in range(y0, y1 + 1):
        a = y * 10000 + 701 if daily else y * 100 + 7
        z = (y + years) * 10000 + 630 if daily else (y + years) * 100 + 6
        if z > ks[-1] or a < ks[0]:
            continue
        ix = [i for i, k in enumerate(ks) if a <= k <= z]
        if len(ix) < years * per * 0.97:
            continue
        sl = lambda arr: [arr[i] for i in ix]
        k2 = sl(ks)
        Wt, _ = tax_sim(k2, sl(run['inv']), sl(run['cash']), sl(run['pos']), yearf)
        Bt, _ = tax_sim(k2, sl(bh_run['inv']), sl(bh_run['cash']), [1] * len(ix), yearf)
        res.append((y, round((ann(Wt, len(ix), per) - ann(Bt, len(ix), per)) * 100, 2)))
    if not res:
        return None
    v = sorted(c for _, c in res)
    return {'windows': len(res), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(res, key=lambda x: x[1]), 'best': max(res, key=lambda x: x[1])}


# ───────────────────────── 評価 ─────────────────────────
def evaluate(run, bench_m, rf_m, blev_m, per_daily, post_pub):
    """月次の gross/net と相手（月次）から統計を作る"""
    if per_daily:
        gm = M.to_monthly(run['gross']); nm = M.to_monthly(run['net']); n5 = M.to_monthly(run['net05'])
    else:
        gm, nm, n5 = run['gross'], run['net'], run['net05']
    b = bench_m
    e = {}
    e['full'] = M.excess_stats(gm, b)
    e['train'] = M.excess_stats(gm, b, z=M.TRAIN_END)
    e['hold'] = M.excess_stats(gm, b, a=M.HOLD_START)
    e['recent'] = M.excess_stats(gm, b, a=M.RECENT_START)
    e['post_pub'] = {nmn: M.excess_stats(gm, b, a=a) for nmn, a in post_pub.items()}
    e['net_full'] = M.excess_stats(nm, b)
    e['net_train'] = M.excess_stats(nm, b, z=M.TRAIN_END)
    e['cost_hold'] = M.excess_stats(nm, b, a=M.HOLD_START)
    e['cost_hold_005'] = M.excess_stats(n5, b, a=M.HOLD_START)
    e['roll20'] = M.rolling(nm, b, 20)
    e['roll20_gross'] = M.rolling(gm, b, 20)
    e['dca20'] = M.dca(nm, b, 20)
    sp = {}
    for nmn, (a, z) in {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None), 'recent': (M.RECENT_START, None)}.items():
        sp[nmn] = [M.sharpe(nm, rf_m, a, z), M.sharpe(b, rf_m, a, z)]
    e['sharpe'] = sp
    e['maxdd'] = {'s_monthly': round(M.maxdd(nm) * 100, 1), 'b_monthly': round(M.maxdd({k: b[k] for k in nm if k in b}) * 100, 1)}
    if per_daily:
        e['maxdd']['s_daily'] = round(M.maxdd(run['net']) * 100, 1)
    if blev_m is not None:
        e['vs_levered_bh'] = {'full': M.excess_stats(gm, blev_m), 'train': M.excess_stats(gm, blev_m, z=M.TRAIN_END), 'hold': M.excess_stats(gm, blev_m, a=M.HOLD_START),
                              'maxdd_levered_bh_monthly': round(M.maxdd({k: blev_m[k] for k in nm if k in blev_m}) * 100, 1)}
    n = len(run['keys'])
    e['time_in_market'] = round(sum(run['pos']) / n, 3)
    e['switches_per_year'] = round(run['switches'] / years_span(run['keys'], per_daily), 2)
    return e


def years_span(keys, daily):
    def todate(k):
        return datetime.date(k // 10000, k // 100 % 100, k % 100) if daily else datetime.date(k // 100, k % 100, 15)
    return max((todate(keys[-1]) - todate(keys[0])).days / 365.25, 1e-9)


def repl_positive(st):
    return bool(st and st['ex_ann'] > 0 and st['cagr_diff'] > 0)


# ───────────────────────── 本体 ─────────────────────────
def main():
    res = {'angle': 'trend', 'prereg': PRE_NAME}
    try:
        sha = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', os.path.join('out', PRE_NAME)], cwd=M.BASE).decode().strip()
    except Exception:
        sha = None
    res['prereg_commit'] = sha
    log('事前登録の commit', sha)

    # ---- US ----
    ffd = M.ff_factors('daily')
    ffm = M.ff_factors('monthly')
    D_us = sorted(d for d in ffd['mkt'] if d in ffd['rf'])
    r_us, rf_us = ffd['mkt'], ffd['rf']
    sanity = {}
    mk = M.to_monthly({d: r_us[d] for d in D_us})
    sanity['us_mkt_cagr_full_from_daily'] = round(M.cagr(mk) * 100, 2)
    sanity['us_mkt_cagr_2007_from_daily'] = round(M.cagr(M.window(mk, M.HOLD_START)) * 100, 2)
    sanity['us_mkt_cagr_full_monthly_file'] = round(M.cagr(ffm['mkt']) * 100, 2)
    log('検算 US Mkt 年率', sanity)
    gspc, _ = yh_daily('^GSPC')
    gspc = {k: v for k, v in gspc.items() if k <= FR_END}
    ndx_px, _ = yh_daily('^NDX')
    ndx_px = {k: v for k, v in ndx_px.items() if k <= FR_END}
    _, qqq_adj = yh_daily('QQQ')
    qqq_adj = {k: v for k, v in qqq_adj.items() if k <= FR_END}
    ixic_px, _ = yh_daily('^IXIC')
    ixic_px = {k: v for k, v in ixic_px.items() if k <= FR_END}

    # NDX 総リターン（日次）
    def ndx_tr(div):
        pr = rets(ndx_px)
        qr = rets(qqq_adj)
        q0 = min(qqq_adj)
        out = {}
        dd = (1 + div) ** (1 / 252) - 1
        for k, v in pr.items():
            if k <= q0:
                out[k] = (1 + v) * (1 + dd) - 1
            elif k in qr:
                out[k] = qr[k]
        return out
    ndx_r = ndx_tr(NDX_DIV)
    ixic_r = {k: (1 + v) * (1 + ((1 + IXIC_DIV) ** (1 / 252) - 1)) - 1 for k, v in rets(ixic_px).items()}
    miss = {'ndx_days_not_in_french_rf': sum(1 for k in ndx_r if k not in rf_us), 'ixic_days_not_in_french_rf': sum(1 for k in ixic_r if k not in rf_us),
            'qqq_splice_gap_days': sum(1 for k in rets(ndx_px) if k > min(qqq_adj) and k not in rets(qqq_adj))}
    sanity['missing'] = miss
    log('欠け', miss)
    D_ndx = sorted(k for k in ndx_r if k in rf_us)
    D_ixic = sorted(k for k in ixic_r if k in rf_us)

    # 信号
    sig_gspc = {N: map_sig(D_us, sma_sig(gspc, N)) for N in (50, 100, 150, 200, 250, 300)}
    us_tr_idx = cum_index({d: r_us[d] for d in D_us})
    sig_us_tr200 = map_sig(D_us, sma_sig(us_tr_idx, 200))
    ndx_sig = {N: map_sig(D_ndx, sma_sig(ndx_px, N)) for N in (50, 100, 150, 200, 250, 300)}
    ixic_sig200 = map_sig(D_ixic, sma_sig(ixic_px, 200))
    us_faberD = map_sig(D_us, month_end_sig_sma(us_tr_idx, 10))
    ndx_faberD = map_sig(D_ndx, month_end_sig_sma(ndx_px, 10))
    us_ex_idx = cum_index({d: ffd['mktrf'][d] for d in D_us})
    us_tsmomD = map_sig(D_us, month_end_sig_tsmom(us_ex_idx, 12))

    # 日次の遅れの機械検算（持ち方の変化の日と信号の日の差）
    def lag_check(D, sigD, run):
        pos_by = dict(zip(run['keys'], run['pos']))
        bad = 0; n = 0
        idx = {d: i for i, d in enumerate(D)}
        for d in run['keys'][:4000]:
            i = idx[d]; n += 1
            if pos_by[d] != sigD[i - 2]:
                bad += 1
        return {'checked': n, 'mismatch': bad}

    # 月次
    ms_us = sorted(k for k in ffm['mkt'] if k in ffm['rf'])
    r_usm, rf_usm = ffm['mkt'], ffm['rf']
    us_idx_m = cum_index({k: r_usm[k] for k in ms_us})
    faber_m = {}
    for N in (6, 8, 10, 12):
        s = {}
        for i in range(N - 1, len(ms_us)):
            w = [us_idx_m[ms_us[j]] for j in range(i - N + 1, i + 1)]
            s[ms_us[i]] = 1 if us_idx_m[ms_us[i]] > sum(w) / N else 0
        faber_m[N] = s
    tsmom_m = {}
    for i in range(11, len(ms_us)):
        g = 1.0
        for j in range(i - 11, i + 1):
            g *= 1 + ffm['mktrf'][ms_us[j]]
        tsmom_m[ms_us[i]] = 1 if g > 1 else 0

    # Shiller
    sr = shiller()
    cp = cp_rate()
    ms_sh = sorted(sr)
    rf_sh = {}
    for k in ms_sh:
        if k <= 192606:
            if k in cp:
                rf_sh[k] = cp[k]
        elif k in rf_usm:
            rf_sh[k] = rf_usm[k]
    ms_sh = [k for k in ms_sh if k in rf_sh]
    sh_idx = cum_index({k: sr[k] for k in ms_sh})
    sh_sig = {}
    for i in range(9, len(ms_sh)):
        w = [sh_idx[ms_sh[j]] for j in range(i - 9, i + 1)]
        sh_sig[ms_sh[i]] = 1 if sh_idx[ms_sh[i]] > sum(w) / 10 else 0
    sanity['shiller'] = {'from': ms_sh[0], 'to': ms_sh[-1], 'cagr': round(M.cagr({k: sr[k] for k in ms_sh}) * 100, 2)}
    log('Shiller', sanity['shiller'])

    # ---- 地域 ----
    REG_D = {'Europe': 'Europe_3_Factors_Daily', 'Japan': 'Japan_3_Factors_Daily', 'Asia_Pacific_ex_Japan': 'Asia_Pacific_ex_Japan_3_Factors_Daily',
             'Developed_ex_US': 'Developed_ex_US_3_Factors_Daily', 'North_America': 'North_America_3_Factors_Daily'}
    COUNTED = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Emerging']
    regd = {}
    for nm, fn in REG_D.items():
        mkt, rf = fr_region(fn, 'daily')
        D = sorted(d for d in mkt if d in rf)
        regd[nm] = {'D': D, 'r': mkt, 'rf': rf, 'idx': cum_index({d: mkt[d] for d in D}),
                    'ex_idx': cum_index({d: mkt[d] - rf[d] for d in D})}
    em_mkt, em_rf = fr_region('Emerging_5_Factors', 'monthly')
    ms_em = sorted(k for k in em_mkt if k in em_rf)

    def monthly_sma_sig(ms, r, N):
        idx = cum_index({k: r[k] for k in ms})
        s = {}
        for i in range(N - 1, len(ms)):
            w = [idx[ms[j]] for j in range(i - N + 1, i + 1)]
            s[ms[i]] = 1 if idx[ms[i]] > sum(w) / N else 0
        return s

    def monthly_tsmom_sig(ms, r, rf):
        s = {}
        for i in range(11, len(ms)):
            g = 1.0
            for j in range(i - 11, i + 1):
                g *= 1 + r[ms[j]] - rf[ms[j]]
            s[ms[i]] = 1 if g > 1 else 0
        return s

    def region_eval(rule):
        """rule = {'kind': 'sma'|'faber_m'|'tsmom_m'|'faber_d'|'tsmom_d', 'N', 'L'} → 地域ごとの費用後の全期間の超過"""
        det = {}
        for nm in list(REG_D) + ['Emerging']:
            if nm == 'Emerging':
                ms, r, rf = ms_em, em_mkt, em_rf
                k = rule['kind']; L = rule['L']
                if k == 'sma':
                    sig = monthly_sma_sig(ms, r, max(1, round(rule['N'] / 21)))
                elif k in ('faber_m', 'faber_d'):
                    sig = monthly_sma_sig(ms, r, rule['N'])
                else:
                    sig = monthly_tsmom_sig(ms, r, rf)
                run = run_monthly(ms, r, rf, sig, L)
                s_n, s_g = run['net'], run['gross']
                b = {k2: r[k2] for k2 in run['keys']}
            else:
                g = regd[nm]; D = g['D']; L = rule['L']; k = rule['kind']
                if k == 'sma':
                    run = run_daily(D, g['r'], g['rf'], map_sig(D, sma_sig(g['idx'], rule['N'])), L)
                elif k == 'faber_d':
                    run = run_daily(D, g['r'], g['rf'], map_sig(D, month_end_sig_sma(g['idx'], rule['N'])), L)
                elif k == 'tsmom_d':
                    run = run_daily(D, g['r'], g['rf'], map_sig(D, month_end_sig_tsmom(g['ex_idx'], 12)), L)
                else:
                    rm = M.to_monthly({d: g['r'][d] for d in D}); rfm = M.to_monthly({d: g['rf'][d] for d in D})
                    ms = sorted(rm)
                    sig = monthly_sma_sig(ms, rm, rule['N']) if k == 'faber_m' else monthly_tsmom_sig(ms, rm, rfm)
                    run = run_monthly(ms, rm, rfm, sig, L)
                    s_n, s_g = run['net'], run['gross']
                    b = {k2: rm[k2] for k2 in run['keys']}
                    det[nm] = pack_region(s_g, s_n, b)
                    continue
                s_n = M.to_monthly(run['net']); s_g = M.to_monthly(run['gross'])
                b = M.to_monthly({d: g['r'][d] for d in run['keys']})
            det[nm] = pack_region(s_g, s_n, b)
        pos = sum(1 for nm in COUNTED if det[nm]['positive'])
        return {'regions': len(COUNTED), 'positive': pos, 'counted': COUNTED, 'detail': det}

    def pack_region(s_g, s_n, b):
        full_n = M.excess_stats(s_n, b)
        return {'net_full': full_n, 'gross_full': M.excess_stats(s_g, b), 'net_hold': M.excess_stats(s_n, b, a=M.HOLD_START),
                'positive': repl_positive(full_n)}

    # ---- 戦略の定義 ----
    strategies = []  # dict(id, family, desc, kind, ...)

    def add(id_, family, desc, runner, bench, rfm, blev, per_daily, post_pub, rule, tax=False, graded=True, extra=None):
        strategies.append(dict(id=id_, family=family, desc=desc, runner=runner, bench=bench, rfm=rfm, blev=blev, per_daily=per_daily,
                               post_pub=post_pub, rule=rule, tax=tax, graded=graded, extra=extra or {}))

    PP_FABER = {'post_faber_2008': 200801, 'post_gayed_2016': 201601, 'post_gayed_2017': 201701}
    PP_GAYED = {'post_gayed_2016': 201601, 'post_gayed_2017': 201701}
    PP_MOP = {'post_mop_2013': 201301, 'post_gayed_2016': 201601}

    # 月次 US
    def mk_monthly_us(sig, L):
        return lambda: run_monthly(ms_us, r_usm, rf_usm, sig, L)
    add('P01_US_FABER10_L1', 'primary', 'US Faber 10か月線（French 月次）・1倍', mk_monthly_us(faber_m[10], 1), 'us_m', 'us_m', None, False, PP_FABER, {'kind': 'faber_m', 'N': 10, 'L': 1}, tax=True)
    add('P02_US_TSMOM12_L1', 'primary', 'US 12か月の時系列モメンタム（French 月次）・1倍', mk_monthly_us(tsmom_m, 1), 'us_m', 'us_m', None, False, PP_MOP, {'kind': 'tsmom_m', 'N': 12, 'L': 1}, tax=True)
    LS = [1, 1.25, 1.5, 2, 3]
    for j, L in enumerate(LS):
        add(f'P{3 + j:02d}_US_SMA200_L{L}', 'primary', f'US ^GSPC 200日線・French 日次 Mkt を{L}倍', (lambda L=L: run_daily(D_us, r_us, rf_us, sig_gspc[200], L)), 'us_d', 'us_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L}, tax=True)
    for j, L in enumerate(LS):
        add(f'P{8 + j:02d}_NDX_SMA200_L{L}', 'primary', f'NDX ^NDX 200日線・NDX 総リターンを{L}倍', (lambda L=L: run_daily(D_ndx, ndx_r, rf_us, ndx_sig[200], L)), 'ndx_d', 'ndx_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L}, tax=True)
    # 探索
    add('E01_SHILLER_FABER10_L1', 'exploratory', 'Shiller 1871〜 総リターン 10か月線（2か月遅れ）・1倍', lambda: run_monthly(ms_sh, sr, rf_sh, sh_sig, 1, lag=2), 'sh_m', 'sh_m', None, False, PP_FABER, {'kind': 'faber_m', 'N': 10, 'L': 1}, tax=True)
    for j, L in enumerate(LS):
        add(f'E{2 + j:02d}_IXIC_SMA200_L{L}', 'exploratory', f'^IXIC 200日線・{L}倍（推定配当1%）', (lambda L=L: run_daily(D_ixic, ixic_r, rf_us, ixic_sig200, L)), 'ixic_d', 'ixic_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L}, tax=True)
    for j, L in enumerate([1, 2, 3]):
        add(f'E{7 + j:02d}_US_FABER10D_L{L}', 'exploratory', f'US Faber 10か月線（日次・1日遅れ）・{L}倍', (lambda L=L: run_daily(D_us, r_us, rf_us, us_faberD, L)), 'us_d', 'us_d', L, True, PP_FABER, {'kind': 'faber_d', 'N': 10, 'L': L}, tax=True)
    for j, L in enumerate([1, 2, 3]):
        add(f'E{10 + j:02d}_NDX_FABER10D_L{L}', 'exploratory', f'NDX Faber 10か月線（日次・1日遅れ）・{L}倍', (lambda L=L: run_daily(D_ndx, ndx_r, rf_us, ndx_faberD, L)), 'ndx_d', 'ndx_d', L, True, PP_FABER, {'kind': 'faber_d', 'N': 10, 'L': L}, tax=True)
    add('E13_US_SMA200TR_L1', 'exploratory', 'US French Mkt 総リターン指数の200日線・1倍', lambda: run_daily(D_us, r_us, rf_us, sig_us_tr200, 1), 'us_d', 'us_d', 1, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': 1}, tax=True)
    for j, L in enumerate([1, 2]):
        add(f'E{14 + j:02d}_US_TSMOM12D_L{L}', 'exploratory', f'US 12か月モメンタム（日次・1日遅れ）・{L}倍', (lambda L=L: run_daily(D_us, r_us, rf_us, us_tsmomD, L)), 'us_d', 'us_d', L, True, PP_MOP, {'kind': 'tsmom_d', 'N': 12, 'L': L}, tax=True)
    # 格子
    for N in (50, 100, 150, 250, 300):
        for L in (1, 2):
            add(f'G_US_SMA{N}_L{L}', 'grid', f'US ^GSPC {N}日線・{L}倍', (lambda N=N, L=L: run_daily(D_us, r_us, rf_us, sig_gspc[N], L)), 'us_d', 'us_d', L, True, PP_GAYED, {'kind': 'sma', 'N': N, 'L': L})
    for N in (50, 100, 150, 250, 300):
        for L in (1, 2):
            add(f'G_NDX_SMA{N}_L{L}', 'grid', f'NDX ^NDX {N}日線・{L}倍', (lambda N=N, L=L: run_daily(D_ndx, ndx_r, rf_us, ndx_sig[N], L)), 'ndx_d', 'ndx_d', L, True, PP_GAYED, {'kind': 'sma', 'N': N, 'L': L})
    for N in (6, 8, 12):
        add(f'G_US_FABER{N}_L1', 'grid', f'US {N}か月線（French 月次）・1倍', mk_monthly_us(faber_m[N], 1), 'us_m', 'us_m', None, False, PP_FABER, {'kind': 'faber_m', 'N': N, 'L': 1})
    # 感度（報告のみ）
    for dv, tag in ((0.0, 'div0'), (0.01, 'div1')):
        rr = ndx_tr(dv)
        for L in (1, 3):
            add(f'X_NDX_{tag}_SMA200_L{L}', 'sensitivity', f'NDX 1999年以前の推定配当 {dv * 100:.0f}%/年・200日線・{L}倍',
                (lambda rr=rr, L=L: run_daily(D_ndx, rr, rf_us, ndx_sig[200], L)), ('ndx_d_div', rr), 'ndx_d', L, True, PP_GAYED, None, graded=False)

    # ---- 実行 ----
    bench_cache = {}

    def bench_for(kind, run):
        """相手（月次）・RF（月次）・レバレッジ込み買い持ち（月次）を run の日付で作る"""
        ks = run['keys']
        if kind == 'us_m':
            return {k: r_usm[k] for k in ks}, {k: rf_usm[k] for k in ks}, None, (r_usm, rf_usm)
        if kind == 'sh_m':
            return {k: sr[k] for k in ks}, {k: rf_sh[k] for k in ks}, None, (sr, rf_sh)
        if isinstance(kind, tuple):
            rr = kind[1]
        else:
            rr = {'us_d': r_us, 'ndx_d': ndx_r, 'ixic_d': ixic_r}[kind]
        b = M.to_monthly({d: rr[d] for d in ks})
        rfm = M.to_monthly({d: rf_us[d] for d in ks})
        return b, rfm, rr, (rr, rf_us)

    tested = []
    runs = {}
    for st in strategies:
        run = st['runner']()
        if run is None:
            log('実行不能', st['id']); continue
        b_m, rf_m, rr_d, (rsrc, rfsrc) = bench_for(st['bench'], run)
        blev_m = None
        if st['per_daily'] and st['blev'] is not None and st['blev'] != 1:
            blev_d = M.lever_daily({d: rr_d[d] for d in run['keys']}, st['blev'], {d: rf_us[d] for d in run['keys']}, spread=SPREAD, fee=FEE)
            blev_m = M.to_monthly(blev_d)
        e = evaluate(run, b_m, rf_m, blev_m, st['per_daily'], st['post_pub'])
        ent = {'id': st['id'], 'family': st['family'], 'desc': st['desc'], 'rule': st['rule'], 'graded': st['graded'],
               'window': [run['keys'][0], run['keys'][-1]], **e}
        if st['id'].startswith('P03'):
            sanity['lag_check_us_sma200'] = lag_check(D_us, sig_gspc[200], run)
        if st['id'].startswith('P08'):
            sanity['lag_check_ndx_sma200'] = lag_check(D_ndx, ndx_sig[200], run)
        # C5
        if st['rule'] is not None and st['graded']:
            ent['repl'] = region_eval(st['rule'])
        # 税
        if st['tax']:
            per = 252 if st['per_daily'] else 12
            yearf = (lambda k: k // 10000) if st['per_daily'] else (lambda k: k // 100)
            bh = {'keys': run['keys'], 'inv': [rsrc[k] for k in run['keys']], 'cash': [rfsrc[k] for k in run['keys']]}
            win = {'full': (None, None), 'train': (None, 20061231 if st['per_daily'] else 200612), 'hold': (20070101 if st['per_daily'] else 200701, None),
                   'post_gayed_2016': (20160101 if st['per_daily'] else 201601, None)}
            ent['tax_japan'] = {'windows': tax_report(run, bh, per, yearf, win)}
            if st['family'] == 'primary':
                ent['tax_japan']['rolling20_taxable_vs_bh_taxable'] = tax_rolling(run, bh, per, yearf)
                if st['blev'] not in (None, 1):
                    # 同じ L の買い持ち（課税後）とも
                    bl = {'keys': run['keys'], 'inv': [lev_ret(rsrc[k], rfsrc[k], st['blev'], 252) for k in run['keys']], 'cash': [rfsrc[k] for k in run['keys']]}
                    ent['tax_japan']['vs_levered_bh_windows'] = tax_report(run, bl, per, yearf, win)
        tested.append(ent)
        runs[st['id']] = run
        h = e['hold']; t = e['train']
        log(f"{st['id']:26s} 訓練 {t['ex_ann'] if t else None:>7} t{t['t'] if t else None} 保有 {h['ex_ann'] if h else None:>7} t{h['t'] if h else None} 幾何差 {h['cagr_diff'] if h else None} "
            f"費用後保有 {e['cost_hold']['ex_ann'] if e['cost_hold'] else None} 20年勝率 {e['roll20']['win_rate'] if e['roll20'] else None} "
            f"Sharpe訓練 {e['sharpe']['train']} 保有 {e['sharpe']['hold']} 地域 {ent.get('repl', {}).get('positive')}/{ent.get('repl', {}).get('regions')}")

    # L=1 のレバレッジ込み買い持ちが買い持ちと一致するか
    lv1 = M.lever_daily({d: r_us[d] for d in D_us[:1000]}, 1, {d: rf_us[d] for d in D_us[:1000]}, spread=SPREAD, fee=0.0)
    sanity['lever1_equals_bh'] = max(abs(lv1[d] - r_us[d]) for d in D_us[:1000]) < 1e-12

    # ---- Holm と判定 ----
    prim = {x['id']: x['hold']['p'] for x in tested if x['family'] == 'primary' and x['hold']}
    allg = {x['id']: x['hold']['p'] for x in tested if x['graded'] and x['hold']}
    hp = M.holm(prim); ha = M.holm(allg)
    for x in tested:
        if not x['graded']:
            x['grade'] = '報告のみ（判定しない）'; continue
        if x['family'] == 'primary':
            x['holm_family'] = 'primary(12)'; x['holm_p'] = hp.get(x['id'])
        else:
            x['holm_family'] = f'all_graded({len(allg)})'; x['holm_p'] = ha.get(x['id'])
        sp = {'train': tuple(x['sharpe']['train']), 'hold': tuple(x['sharpe']['hold'])}
        g, c = M.grade(x['full'], x['train'], x['hold'], x['roll20'], cost_hold=x['cost_hold'], repl=x.get('repl'),
                       family_holm_p=x['holm_p'], sharpe_pair=sp, leveraged_or_timing=True)
        x['grade'] = g; x['criteria'] = c
        if x['family'] != 'primary':
            x['label'] = '探索' if x['family'] == 'exploratory' else '頑健性の格子（勝ちの主張には使わない）'
    res['sanity'] = sanity
    res['n_tested'] = len(tested)
    res['grades'] = {g: [x['id'] for x in tested if x.get('grade') == g] for g in ('S', 'A', 'B', 'C')}
    res['tested'] = tested
    res['log'] = LOG
    p = M.save(OUT_NAME, res)
    log('書いた', p, '格付け', {g: len(v) for g, v in res['grades'].items()})


if __name__ == '__main__':
    main()
