#!/usr/bin/env python3
"""night/mw_trend.py — 『市場に勝てる歴史検証』角度 trend: トレンド追随の市場タイミング（レバレッジなし・あり）

読むだけ（門の判定・採点・配分には不使用）。事前登録 out/mw_trend_prereg.json（第1族）・out/mw_trend_prereg2.json（第2族・探索）
の規則をそのまま測り、out/mw_trend.json へ書く。線は out/mw_prereg.json（mw_common.grade）。

規則（論文の既定値・結果を見る前に固定）
- Faber (2007): 月末の総リターン指数 > 10か月平均 → 翌月は株、ほかは短期金利
- Gayed & Bilello (2016): 価格指数 > 200営業日平均 → 日々L倍（L=1,1.25,1.5,2,3）、ほかは短期金利。
  信号は t の終値、売買は t+1 の終値（1日遅れ）＝ t+2 日目のリターンから新しい持ち方
- Moskowitz-Ooi-Pedersen (2012): 直近12か月の超過 > 0 → 株、ほかは短期金利
第2族（探索）: 訓練期間だけで選んだ (N日線, 幅) ／ 国債への退避 ／ ゴールデンクロス ／ 二つの信号の一致

相手（判定の主）は同じ指数をレバレッジなしで買って持つだけ。総リターンどうしで比べる。
使い方: python3 night/mw_trend.py            （第1族＋第2族を全部測って書く）
"""
import sys, os, json, math, datetime, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PRE_NAMES = ['mw_trend_prereg.json', 'mw_trend_prereg2.json', 'mw_trend_prereg3.json', 'mw_trend_prereg4.json']
OUT_NAME = 'mw_trend.json'
COST = 0.001      # 判定用: 持ち替え1回あたり資産の0.10%（全体の事前登録の既定）
COST_LO = 0.0005  # 報告: 指示書の0.05%
TAX = 0.20315
SPREAD, FEE = 0.005, 0.009
FUT_SPREAD, FUT_FEE = 0.003, 0.0  # 【事後・報告のみ】先物で持つ場合の費用
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


def fred_csv(sid):
    c = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=3650).decode()
    out = {}
    for line in c.strip().splitlines()[1:]:
        d, v = line.split(',')
        if v in ('', '.'):
            continue
        out[int(d[:4]) * 10000 + int(d[5:7]) * 100 + int(d[8:10])] = float(v)
    return out


def cp_rate():
    """NBER 商業手形金利（年率%）→ 月次の小数リターン {yyyymm: r}"""
    return {k // 100: v / 1200 for k, v in fred_csv('M13002US35620M156NNBR').items()}


def bond_index_daily():
    """FRED DGS10 → 10年額面債を毎日作り直す近似の総リターン指数 {yyyymmdd: 指数}（観測日だけ）"""
    y = fred_csv('DGS10')
    ks = sorted(y)
    idx, w = {ks[0]: 1.0}, 1.0
    for p, k in zip(ks, ks[1:]):
        c, yy = y[p] / 100, y[k] / 100
        dp = datetime.date(p // 10000, p // 100 % 100, p % 100); dk = datetime.date(k // 10000, k // 100 % 100, k % 100)
        dt = (dk - dp).days / 365.0
        m = 10 - dt
        disc = (1 + yy / 2) ** (-2 * m)
        P = (c / yy) * (1 - disc) + disc if yy > 0 else 1 + c * m
        w *= P + c * dt
        idx[k] = w
    return idx


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


def sma_band_sig(px, N, b):
    """ヒステリシスつき: 持っている間は 価格 < 平均×(1−b) で降り、降りている間は 価格 > 平均×(1+b) で戻る"""
    if b == 0:
        return sma_sig(px, N)
    ks = sorted(px)
    out, run, st = {}, 0.0, None
    for i, k in enumerate(ks):
        run += px[k]
        if i >= N:
            run -= px[ks[i - N]]
        if i >= N - 1:
            m = run / N
            if st is None:
                st = 1 if px[k] > m else 0
            elif st == 1 and px[k] < m * (1 - b):
                st = 0
            elif st == 0 and px[k] > m * (1 + b):
                st = 1
            out[k] = st
    return out


def cross_sig(px, a=50, z=200):
    """a 日線 > z 日線 → 1"""
    ks = sorted(px)
    out, ra, rz = {}, 0.0, 0.0
    for i, k in enumerate(ks):
        ra += px[k]; rz += px[k]
        if i >= a:
            ra -= px[ks[i - a]]
        if i >= z:
            rz -= px[ks[i - z]]
        if i >= z - 1:
            out[k] = 1 if ra / a > rz / z else 0
    return out


def month_ends(ks):
    return [k for i, k in enumerate(ks) if i == len(ks) - 1 or ks[i + 1] // 100 != k // 100]


def month_end_sig_sma(px, N):
    """日次価格の月末値 > 直近 N か月の月末値の平均 → {月末の日付: 0/1}"""
    me = month_ends(sorted(px))
    out = {}
    for i in range(N - 1, len(me)):
        w = [px[me[j]] for j in range(i - N + 1, i + 1)]
        out[me[i]] = 1 if px[me[i]] > sum(w) / N else 0
    return out


def month_end_sig_tsmom(daily_ex_index, months=12):
    """日次の超過指数（累積）の月末値の12か月前比 > 1 → {月末の日付: 0/1}"""
    me = month_ends(sorted(daily_ex_index))
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


def either(a, b):
    """二つの信号（日付に写した list）のどちらかが 1 なら 1（両方 0 のときだけ 0）"""
    return [None if (x is None or y is None) else (1 if (x or y) else 0) for x, y in zip(a, b)]


def cum_index(r):
    w, out = 1.0, {}
    for k in sorted(r):
        w *= 1 + r[k]; out[k] = w
    return out


def monthly_sma_sig(ms, r, N, b=0.0):
    idx = cum_index({k: r[k] for k in ms})
    return sma_band_sig({k: idx[k] for k in ms}, N, b)


def monthly_cross_sig(ms, r, a, z):
    idx = cum_index({k: r[k] for k in ms})
    return cross_sig({k: idx[k] for k in ms}, a, z)


def monthly_tsmom_sig(ms, r, rf):
    s = {}
    for i in range(11, len(ms)):
        g = 1.0
        for j in range(i - 11, i + 1):
            g *= 1 + r[ms[j]] - rf[ms[j]]
        s[ms[i]] = 1 if g > 1 else 0
    return s


# ───────────────────────── 実行 ─────────────────────────
def lev_ret(v, f, L, per, spread=SPREAD, fee=FEE):
    if L == 1:
        return v
    x = L * v - (L - 1) * (f + spread / per) - fee / per
    return max(x, -1.0)


def run_daily(D, r, rf, sig_on_D, L, lag=2, off=None, cost_mult=1, spread=SPREAD, fee=FEE):
    """日次。position[i] = sig_on_D[i-lag]。off=降りている間の資産（None なら RF）。最初の不完全な月は落とす"""
    for d in D:
        if d not in rf or d not in r or (off is not None and d not in off):
            raise RuntimeError(f'RF・リターン・退避先のどれかが無い日 {d}（0で埋めない）')
    if L != 1:
        lev = M.lever_daily({d: r[d] for d in D}, L, {d: rf[d] for d in D}, spread=spread, fee=fee)
    else:
        lev = {d: r[d] for d in D}
    idx = [i for i in range(lag, len(D)) if sig_on_D[i - lag] is not None]
    if not idx:
        return None
    first_m = D[idx[0]] // 100
    if D[idx[0] - 1] // 100 == first_m:  # 途中の月から始まる → その月を落とす
        idx = [i for i in idx if D[i] // 100 != first_m]
    keys, inv, cash, pos = [], [], [], []
    for i in idx:
        d = D[i]
        keys.append(d); inv.append(max(lev[d], -1.0)); cash.append(rf[d] if off is None else off[d]); pos.append(sig_on_D[i - lag])
    return finish(keys, inv, cash, pos, cost_mult)


def run_monthly(ms, r, rf, sig, L, lag=1, off=None, cost_mult=1):
    """月次。position[k] = sig[ms[k-lag]]（sig は月→0/1）"""
    keys, inv, cash, pos = [], [], [], []
    for i in range(lag, len(ms)):
        s = sig.get(ms[i - lag])
        if s is None:
            continue
        k = ms[i]
        if k not in r or k not in rf or (off is not None and k not in off):
            raise RuntimeError(f'月 {k} のデータ欠け（0で埋めない）')
        keys.append(k); inv.append(lev_ret(r[k], rf[k], L, 12)); cash.append(rf[k] if off is None else off[k]); pos.append(s)
    return finish(keys, inv, cash, pos, cost_mult)


def finish(keys, inv, cash, pos, cost_mult=1):
    gross, net, net05 = {}, {}, {}
    sw = 0
    for i, k in enumerate(keys):
        g = inv[i] if pos[i] else cash[i]
        gross[k] = g
        if i > 0 and pos[i] != pos[i - 1]:
            sw += 1
            net[k] = (1 + g) * (1 - COST * cost_mult) - 1
            net05[k] = (1 + g) * (1 - COST_LO * cost_mult) - 1
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
def by_decade(nm, b):
    out = {}
    for d0 in range(1920, 2030, 10):
        ks = [k for k in nm if k in b and d0 * 100 <= k <= (d0 + 9) * 100 + 12]
        if len(ks) >= 24:
            out[str(d0)] = round((M.cagr([nm[k] for k in ks]) - M.cagr([b[k] for k in ks])) * 100, 2)
    return out


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
    e['by_decade_net_cagr_diff'] = by_decade(nm, b)
    return e


def years_span(keys, daily):
    def todate(k):
        return datetime.date(k // 10000, k // 100 % 100, k % 100) if daily else datetime.date(k // 100, k % 100, 15)
    return max((todate(keys[-1]) - todate(keys[0])).days / 365.25, 1e-9)


def repl_positive(st):
    return bool(st and st['ex_ann'] > 0 and st['cagr_diff'] > 0)


# ───────────────────────── データの用意 ─────────────────────────
class Ctx:
    pass


def load():
    c = Ctx()
    c.sanity = {}
    ffd = M.ff_factors('daily'); ffm = M.ff_factors('monthly')
    c.ffd, c.ffm = ffd, ffm
    c.D_us = sorted(d for d in ffd['mkt'] if d in ffd['rf'])
    c.r_us, c.rf_us = ffd['mkt'], ffd['rf']
    mk = M.to_monthly({d: c.r_us[d] for d in c.D_us})
    c.sanity['us_mkt_cagr_full_from_daily'] = round(M.cagr(mk) * 100, 2)
    c.sanity['us_mkt_cagr_2007_from_daily'] = round(M.cagr(M.window(mk, M.HOLD_START)) * 100, 2)
    c.sanity['us_mkt_cagr_full_monthly_file'] = round(M.cagr(ffm['mkt']) * 100, 2)
    log('検算 US Mkt 年率', c.sanity)
    c.gspc = {k: v for k, v in yh_daily('^GSPC')[0].items() if k <= FR_END}
    c.ndx_px = {k: v for k, v in yh_daily('^NDX')[0].items() if k <= FR_END}
    c.qqq_adj = {k: v for k, v in yh_daily('QQQ')[1].items() if k <= FR_END}
    c.ixic_px = {k: v for k, v in yh_daily('^IXIC')[0].items() if k <= FR_END}
    c.ndx_r = ndx_tr(c, NDX_DIV)
    c.ixic_r = {k: (1 + v) * (1 + ((1 + IXIC_DIV) ** (1 / 252) - 1)) - 1 for k, v in rets(c.ixic_px).items()}
    miss = {'ndx_days_not_in_french_rf': sum(1 for k in c.ndx_r if k not in c.rf_us), 'ixic_days_not_in_french_rf': sum(1 for k in c.ixic_r if k not in c.rf_us),
            'qqq_splice_gap_days': sum(1 for k in rets(c.ndx_px) if k > min(c.qqq_adj) and k not in rets(c.qqq_adj))}
    c.sanity['missing'] = miss
    log('欠け', miss)
    c.D_ndx = sorted(k for k in c.ndx_r if k in c.rf_us)
    c.D_ixic = sorted(k for k in c.ixic_r if k in c.rf_us)
    c.us_tr_idx = cum_index({d: c.r_us[d] for d in c.D_us})
    c.us_ex_idx = cum_index({d: ffd['mktrf'][d] for d in c.D_us})
    # 月次 US
    c.ms_us = sorted(k for k in ffm['mkt'] if k in ffm['rf'])
    c.r_usm, c.rf_usm = ffm['mkt'], ffm['rf']
    # Shiller
    c.sr = shiller(); cp = cp_rate()
    ms_sh = sorted(c.sr); rf_sh = {}
    for k in ms_sh:
        if k <= 192606:
            if k in cp:
                rf_sh[k] = cp[k]
        elif k in c.rf_usm:
            rf_sh[k] = c.rf_usm[k]
    c.ms_sh = [k for k in ms_sh if k in rf_sh]; c.rf_sh = rf_sh
    c.sanity['shiller'] = {'from': c.ms_sh[0], 'to': c.ms_sh[-1], 'cagr': round(M.cagr({k: c.sr[k] for k in c.ms_sh}) * 100, 2)}
    # 国債（日次の指数 → French の日付へ前日のまま写してリターン）
    bidx = bond_index_daily()
    c.bond_first = min(bidx)
    def bond_on(D):
        vals = map_sig(D, bidx)
        out = {}
        for p, k, vp, vk in zip(D, D[1:], vals, vals[1:]):
            if vp is not None and vk is not None:
                out[k] = vk / vp - 1
        return out
    c.bond_on = bond_on
    c.bond_us = bond_on(c.D_us)
    # 国債の作り方の検算（IEF との月次）
    try:
        ief = {k: v for k, v in yh_daily('IEF')[1].items() if k <= FR_END}
        im = M.to_monthly(rets(ief))
        bm = M.to_monthly({k: v for k, v in c.bond_us.items() if k > min(ief)})
        ks = sorted(set(im) & set(bm))
        c.sanity['bond_vs_IEF_monthly'] = {'months': len(ks), 'corr': round(M.corr([im[k] for k in ks], [bm[k] for k in ks]), 3),
                                          'cagr_constructed': round(M.cagr([bm[k] for k in ks]) * 100, 2), 'cagr_IEF': round(M.cagr([im[k] for k in ks]) * 100, 2)}
        log('国債の検算', c.sanity['bond_vs_IEF_monthly'])
    except Exception as ex:  # noqa
        c.sanity['bond_vs_IEF_monthly'] = f'失敗 {ex}'
    # 地域
    c.REG_D = {'Europe': 'Europe_3_Factors_Daily', 'Japan': 'Japan_3_Factors_Daily', 'Asia_Pacific_ex_Japan': 'Asia_Pacific_ex_Japan_3_Factors_Daily',
               'Developed_ex_US': 'Developed_ex_US_3_Factors_Daily', 'North_America': 'North_America_3_Factors_Daily'}
    c.COUNTED = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Emerging']
    c.regd = {}
    for nm, fn in c.REG_D.items():
        mkt, rf = fr_region(fn, 'daily')
        D = sorted(d for d in mkt if d in rf)
        c.regd[nm] = {'D': D, 'r': mkt, 'rf': rf, 'idx': cum_index({d: mkt[d] for d in D}), 'ex_idx': cum_index({d: mkt[d] - rf[d] for d in D}),
                      'bond': None}
    c.em_mkt, c.em_rf = fr_region('Emerging_5_Factors', 'monthly')
    c.ms_em = sorted(k for k in c.em_mkt if k in c.em_rf)
    return c


def ndx_tr(c, div):
    pr = rets(c.ndx_px); qr = rets(c.qqq_adj); q0 = min(c.qqq_adj)
    out = {}
    dd = (1 + div) ** (1 / 252) - 1
    for k, v in pr.items():
        if k <= q0:
            out[k] = (1 + v) * (1 + dd) - 1
        elif k in qr:
            out[k] = qr[k]
    return out


# ───────────────────────── 地域での再現（C5） ─────────────────────────
def region_eval(c, rule):
    """rule = {'kind': 'sma'|'faber_m'|'tsmom_m'|'faber_d'|'tsmom_d'|'cross'|'dual', 'N', 'b', 'L', 'off'} →
    地域ごとの費用後の全期間の超過。off='bond' なら降りている間は米国10年国債"""
    det = {}
    k = rule['kind']; L = rule['L']; b = rule.get('b', 0.0); off_bond = rule.get('off') == 'bond'
    cm = 2 if off_bond else 1
    for nm in list(c.REG_D) + ['Emerging']:
        if nm == 'Emerging':
            ms, r, rf = c.ms_em, c.em_mkt, c.em_rf
            if k == 'sma':
                sig = monthly_sma_sig(ms, r, max(1, round(rule['N'] / 21)), b)
            elif k in ('faber_m', 'faber_d'):
                sig = monthly_sma_sig(ms, r, rule['N'], b)
            elif k == 'cross':
                sig = monthly_cross_sig(ms, r, 2, 10)
            elif k == 'dual':
                s1 = monthly_sma_sig(ms, r, 10); s2 = monthly_tsmom_sig(ms, r, rf)
                sig = {m: (1 if (s1[m] or s2[m]) else 0) for m in s1 if m in s2}
            else:
                sig = monthly_tsmom_sig(ms, r, rf)
            off = None
            if off_bond:
                bm = M.to_monthly(c.bond_us)
                ms = [m for m in ms if m in bm]
                off = bm
            run = run_monthly(ms, r, rf, sig, L, off=off, cost_mult=cm)
            s_n, s_g = run['net'], run['gross']
            bb = {k2: r[k2] for k2 in run['keys']}
        else:
            g = c.regd[nm]; D = g['D']
            off = None
            if off_bond:
                if g['bond'] is None:
                    g['bond'] = c.bond_on(D)
                off = g['bond']
                D = [d for d in D if d in off]
            if k in ('faber_m', 'tsmom_m'):
                rm = M.to_monthly({d: g['r'][d] for d in D}); rfm = M.to_monthly({d: g['rf'][d] for d in D})
                ms = sorted(rm)
                sig = monthly_sma_sig(ms, rm, rule['N'], b) if k == 'faber_m' else monthly_tsmom_sig(ms, rm, rfm)
                offm = M.to_monthly({d: off[d] for d in D}) if off is not None else None
                run = run_monthly(ms, rm, rfm, sig, L, off=offm, cost_mult=cm)
                det[nm] = pack_region(run['gross'], run['net'], {k2: rm[k2] for k2 in run['keys']})
                continue
            if k == 'sma':
                sd = map_sig(D, sma_band_sig(g['idx'], rule['N'], b))
            elif k == 'faber_d':
                sd = map_sig(D, month_end_sig_sma(g['idx'], rule['N']))
            elif k == 'tsmom_d':
                sd = map_sig(D, month_end_sig_tsmom(g['ex_idx'], 12))
            elif k == 'cross':
                sd = map_sig(D, cross_sig(g['idx'], 50, 200))
            elif k == 'dual':
                sd = either(map_sig(D, sma_sig(g['idx'], 200)), map_sig(D, month_end_sig_tsmom(g['ex_idx'], 12)))
            else:
                raise KeyError(k)
            run = run_daily(D, g['r'], g['rf'], sd, L, off=off, cost_mult=cm)
            s_n = M.to_monthly(run['net']); s_g = M.to_monthly(run['gross'])
            bb = M.to_monthly({d: g['r'][d] for d in run['keys']})
        det[nm] = pack_region(s_g, s_n, bb)
    pos = sum(1 for nm in c.COUNTED if det[nm]['positive'])
    return {'regions': len(c.COUNTED), 'positive': pos, 'counted': c.COUNTED, 'rule_positive': 'ex_ann>0 かつ cagr_diff>0（費用後・地域の全期間）', 'detail': det}


def pack_region(s_g, s_n, b):
    full_n = M.excess_stats(s_n, b)
    return {'net_full': full_n, 'gross_full': M.excess_stats(s_g, b), 'net_hold': M.excess_stats(s_n, b, a=M.HOLD_START),
            'positive': repl_positive(full_n)}


# ───────────────────────── 戦略の定義 ─────────────────────────
PP_FABER = {'post_faber_2008': 200801, 'post_gayed_2016': 201601, 'post_gayed_2017': 201701}
PP_GAYED = {'post_gayed_2016': 201601, 'post_gayed_2017': 201701}
PP_MOP = {'post_mop_2013': 201301, 'post_gayed_2016': 201601}
LS = [1, 1.25, 1.5, 2, 3]


def spec(id_, family, desc, runner, bench, blev, per_daily, post_pub, rule, tax=False, graded=True, label=None):
    return dict(id=id_, family=family, desc=desc, runner=runner, bench=bench, blev=blev, per_daily=per_daily,
                post_pub=post_pub, rule=rule, tax=tax, graded=graded, label=label)


def family1(c):
    out = []
    sig_gspc = {N: map_sig(c.D_us, sma_sig(c.gspc, N)) for N in (50, 100, 150, 200, 250, 300)}
    c.sig_gspc = sig_gspc
    sig_us_tr200 = map_sig(c.D_us, sma_sig(c.us_tr_idx, 200))
    ndx_sig = {N: map_sig(c.D_ndx, sma_sig(c.ndx_px, N)) for N in (50, 100, 150, 200, 250, 300)}
    c.ndx_sig = ndx_sig
    ixic_sig200 = map_sig(c.D_ixic, sma_sig(c.ixic_px, 200))
    us_faberD = map_sig(c.D_us, month_end_sig_sma(c.us_tr_idx, 10))
    c.us_faberD = us_faberD
    ndx_faberD = map_sig(c.D_ndx, month_end_sig_sma(c.ndx_px, 10))
    us_tsmomD = map_sig(c.D_us, month_end_sig_tsmom(c.us_ex_idx, 12))
    c.us_tsmomD = us_tsmomD
    faber_m = {}
    us_idx_m = cum_index({k: c.r_usm[k] for k in c.ms_us})
    for N in (6, 8, 10, 12):
        s = {}
        for i in range(N - 1, len(c.ms_us)):
            w = [us_idx_m[c.ms_us[j]] for j in range(i - N + 1, i + 1)]
            s[c.ms_us[i]] = 1 if us_idx_m[c.ms_us[i]] > sum(w) / N else 0
        faber_m[N] = s
    tsmom_m = {}
    for i in range(11, len(c.ms_us)):
        g = 1.0
        for j in range(i - 11, i + 1):
            g *= 1 + c.ffm['mktrf'][c.ms_us[j]]
        tsmom_m[c.ms_us[i]] = 1 if g > 1 else 0
    sh_idx = cum_index({k: c.sr[k] for k in c.ms_sh})
    sh_sig = {}
    for i in range(9, len(c.ms_sh)):
        w = [sh_idx[c.ms_sh[j]] for j in range(i - 9, i + 1)]
        sh_sig[c.ms_sh[i]] = 1 if sh_idx[c.ms_sh[i]] > sum(w) / 10 else 0

    def mk_monthly_us(sig, L):
        return lambda: run_monthly(c.ms_us, c.r_usm, c.rf_usm, sig, L)
    out.append(spec('P01_US_FABER10_L1', 'primary', 'US Faber 10か月線（French 月次）・1倍', mk_monthly_us(faber_m[10], 1), 'us_m', None, False, PP_FABER, {'kind': 'faber_m', 'N': 10, 'L': 1}, tax=True))
    out.append(spec('P02_US_TSMOM12_L1', 'primary', 'US 12か月の時系列モメンタム（French 月次）・1倍', mk_monthly_us(tsmom_m, 1), 'us_m', None, False, PP_MOP, {'kind': 'tsmom_m', 'N': 12, 'L': 1}, tax=True))
    for j, L in enumerate(LS):
        out.append(spec(f'P{3 + j:02d}_US_SMA200_L{L}', 'primary', f'US ^GSPC 200日線・French 日次 Mkt を{L}倍', (lambda L=L: run_daily(c.D_us, c.r_us, c.rf_us, sig_gspc[200], L)), 'us_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L}, tax=True))
    for j, L in enumerate(LS):
        out.append(spec(f'P{8 + j:02d}_NDX_SMA200_L{L}', 'primary', f'NDX ^NDX 200日線・NDX 総リターンを{L}倍', (lambda L=L: run_daily(c.D_ndx, c.ndx_r, c.rf_us, ndx_sig[200], L)), 'ndx_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L}, tax=True))
    out.append(spec('E01_SHILLER_FABER10_L1', 'exploratory', 'Shiller 1871〜 総リターン 10か月線（2か月遅れ）・1倍', lambda: run_monthly(c.ms_sh, c.sr, c.rf_sh, sh_sig, 1, lag=2), 'sh_m', None, False, PP_FABER, {'kind': 'faber_m', 'N': 10, 'L': 1}, tax=True))
    for j, L in enumerate(LS):
        out.append(spec(f'E{2 + j:02d}_IXIC_SMA200_L{L}', 'exploratory', f'^IXIC 200日線・{L}倍（推定配当1%）', (lambda L=L: run_daily(c.D_ixic, c.ixic_r, c.rf_us, ixic_sig200, L)), 'ixic_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L}, tax=True))
    for j, L in enumerate([1, 2, 3]):
        out.append(spec(f'E{7 + j:02d}_US_FABER10D_L{L}', 'exploratory', f'US Faber 10か月線（日次・1日遅れ）・{L}倍', (lambda L=L: run_daily(c.D_us, c.r_us, c.rf_us, us_faberD, L)), 'us_d', L, True, PP_FABER, {'kind': 'faber_d', 'N': 10, 'L': L}, tax=True))
    for j, L in enumerate([1, 2, 3]):
        out.append(spec(f'E{10 + j:02d}_NDX_FABER10D_L{L}', 'exploratory', f'NDX Faber 10か月線（日次・1日遅れ）・{L}倍', (lambda L=L: run_daily(c.D_ndx, c.ndx_r, c.rf_us, ndx_faberD, L)), 'ndx_d', L, True, PP_FABER, {'kind': 'faber_d', 'N': 10, 'L': L}, tax=True))
    out.append(spec('E13_US_SMA200TR_L1', 'exploratory', 'US French Mkt 総リターン指数の200日線・1倍', lambda: run_daily(c.D_us, c.r_us, c.rf_us, sig_us_tr200, 1), 'us_d', 1, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': 1}, tax=True))
    for j, L in enumerate([1, 2]):
        out.append(spec(f'E{14 + j:02d}_US_TSMOM12D_L{L}', 'exploratory', f'US 12か月モメンタム（日次・1日遅れ）・{L}倍', (lambda L=L: run_daily(c.D_us, c.r_us, c.rf_us, us_tsmomD, L)), 'us_d', L, True, PP_MOP, {'kind': 'tsmom_d', 'N': 12, 'L': L}, tax=True))
    for N in (50, 100, 150, 250, 300):
        for L in (1, 2):
            out.append(spec(f'G_US_SMA{N}_L{L}', 'grid', f'US ^GSPC {N}日線・{L}倍', (lambda N=N, L=L: run_daily(c.D_us, c.r_us, c.rf_us, sig_gspc[N], L)), 'us_d', L, True, PP_GAYED, {'kind': 'sma', 'N': N, 'L': L}))
    for N in (50, 100, 150, 250, 300):
        for L in (1, 2):
            out.append(spec(f'G_NDX_SMA{N}_L{L}', 'grid', f'NDX ^NDX {N}日線・{L}倍', (lambda N=N, L=L: run_daily(c.D_ndx, c.ndx_r, c.rf_us, ndx_sig[N], L)), 'ndx_d', L, True, PP_GAYED, {'kind': 'sma', 'N': N, 'L': L}))
    for N in (6, 8, 12):
        out.append(spec(f'G_US_FABER{N}_L1', 'grid', f'US {N}か月線（French 月次）・1倍', mk_monthly_us(faber_m[N], 1), 'us_m', None, False, PP_FABER, {'kind': 'faber_m', 'N': N, 'L': 1}))
    for dv, tag in ((0.0, 'div0'), (0.01, 'div1')):
        rr = ndx_tr(c, dv)
        for L in (1, 3):
            out.append(spec(f'X_NDX_{tag}_SMA200_L{L}', 'sensitivity', f'NDX 1999年以前の推定配当 {dv * 100:.0f}%/年・200日線・{L}倍',
                            (lambda rr=rr, L=L: run_daily(c.D_ndx, rr, c.rf_us, ndx_sig[200], L)), ('ndx_d_div', rr), L, True, PP_GAYED, None, graded=False))
    return out


def train_select(c, D, r, rf, px, label):
    """訓練期間（〜2006-12）だけで (N, b) を選ぶ。L=1・費用後の月次シャープレシオ最大。保有期間は一切計算しない"""
    grid = []
    runs = {}
    for N in (50, 100, 150, 200, 250, 300):
        for b in (0.0, 0.005, 0.01, 0.02, 0.03, 0.05):
            run = run_daily(D, r, rf, map_sig(D, sma_band_sig(px, N, b)), 1)
            nm = M.to_monthly({k: v for k, v in run['net'].items() if k <= 20061231})
            runs[(N, b)] = nm
    a = max(min(nm) for nm in runs.values())
    rfm = M.to_monthly({d: rf[d] for d in D if d <= 20061231})
    for (N, b), nm in runs.items():
        grid.append({'N': N, 'b': b, 'train_sharpe': M.sharpe(nm, rfm, a, M.TRAIN_END), 'train_from': a})
    best = max(grid, key=lambda g: g['train_sharpe'])
    log(f'{label} 訓練だけで選んだ', best)
    return best, grid


def family2(c):
    out = []
    sel = {}
    best, grid = train_select(c, c.D_us, c.r_us, c.rf_us, c.gspc, 'US')
    sel['US'] = {'selected': best, 'grid_train_only': grid}
    s_us = map_sig(c.D_us, sma_band_sig(c.gspc, best['N'], best['b']))
    for L in (1, 1.5, 2, 3):
        out.append(spec(f'X1_US_TRAINOPT_N{best["N"]}_b{best["b"]}_L{L}', 'exploratory2', f'US ^GSPC {best["N"]}日線・幅{best["b"] * 100:.1f}%（訓練だけで選択）・{L}倍',
                        (lambda L=L: run_daily(c.D_us, c.r_us, c.rf_us, s_us, L)), 'us_d', L, True, PP_GAYED, {'kind': 'sma', 'N': best['N'], 'b': best['b'], 'L': L}, tax=True))
    bestn, gridn = train_select(c, c.D_ndx, c.ndx_r, c.rf_us, c.ndx_px, 'NDX')
    sel['NDX'] = {'selected': bestn, 'grid_train_only': gridn}
    s_ndx = map_sig(c.D_ndx, sma_band_sig(c.ndx_px, bestn['N'], bestn['b']))
    for L in (1, 1.5, 2, 3):
        out.append(spec(f'X2_NDX_TRAINOPT_N{bestn["N"]}_b{bestn["b"]}_L{L}', 'exploratory2', f'NDX ^NDX {bestn["N"]}日線・幅{bestn["b"] * 100:.1f}%（訓練だけで選択）・{L}倍',
                        (lambda L=L: run_daily(c.D_ndx, c.ndx_r, c.rf_us, s_ndx, L)), 'ndx_d', L, True, PP_GAYED, {'kind': 'sma', 'N': bestn['N'], 'b': bestn['b'], 'L': L}, tax=True))
    c.train_selection = sel
    # X3 国債への退避（1962〜）
    D_b = [d for d in c.D_us if d in c.bond_us]
    s200_b = map_sig(D_b, sma_sig(c.gspc, 200))
    fab_b = map_sig(D_b, month_end_sig_sma(c.us_tr_idx, 10))
    for L in (1, 2, 3):
        out.append(spec(f'X3_US_SMA200_BOND_L{L}', 'exploratory2', f'US ^GSPC 200日線・降りたら10年国債・{L}倍（1962〜）',
                        (lambda L=L: run_daily(D_b, c.r_us, c.rf_us, s200_b, L, off=c.bond_us, cost_mult=2)), 'us_d', L, True, PP_GAYED, {'kind': 'sma', 'N': 200, 'L': L, 'off': 'bond'}))
    for L in (1, 2, 3):
        out.append(spec(f'X3_US_FABER10D_BOND_L{L}', 'exploratory2', f'US Faber 10か月線（日次・1日遅れ）・降りたら10年国債・{L}倍（1962〜）',
                        (lambda L=L: run_daily(D_b, c.r_us, c.rf_us, fab_b, L, off=c.bond_us, cost_mult=2)), 'us_d', L, True, PP_FABER, {'kind': 'faber_d', 'N': 10, 'L': L, 'off': 'bond'}))
    # X4 ゴールデンクロス
    gc_us = map_sig(c.D_us, cross_sig(c.gspc, 50, 200))
    gc_ndx = map_sig(c.D_ndx, cross_sig(c.ndx_px, 50, 200))
    for L in (1, 2, 3):
        out.append(spec(f'X4_US_CROSS50_200_L{L}', 'exploratory2', f'US ^GSPC 50日線>200日線・{L}倍', (lambda L=L: run_daily(c.D_us, c.r_us, c.rf_us, gc_us, L)), 'us_d', L, True, PP_GAYED, {'kind': 'cross', 'L': L}, tax=True))
    for L in (1, 2, 3):
        out.append(spec(f'X4_NDX_CROSS50_200_L{L}', 'exploratory2', f'NDX ^NDX 50日線>200日線・{L}倍', (lambda L=L: run_daily(c.D_ndx, c.ndx_r, c.rf_us, gc_ndx, L)), 'ndx_d', L, True, PP_GAYED, {'kind': 'cross', 'L': L}, tax=True))
    # X5 二つの信号の一致（両方『下』のときだけ降りる）
    dual = either(c.sig_gspc[200], c.us_tsmomD)
    for L in (1, 2, 3):
        out.append(spec(f'X5_US_DUAL_L{L}', 'exploratory2', f'US 200日線と12か月モメンタムが両方『下』のときだけ降りる・{L}倍', (lambda L=L: run_daily(c.D_us, c.r_us, c.rf_us, dual, L)), 'us_d', L, True, PP_GAYED, {'kind': 'dual', 'L': L}, tax=True))
    # 【事後・報告のみ】先物の費用で持ったら
    for base, D, r, sig, L, bench in (('P05_US_SMA200', c.D_us, c.r_us, c.sig_gspc[200], 1.5, 'us_d'), ('P06_US_SMA200', c.D_us, c.r_us, c.sig_gspc[200], 2, 'us_d'),
                                     ('P07_US_SMA200', c.D_us, c.r_us, c.sig_gspc[200], 3, 'us_d'), ('P10_NDX_SMA200', c.D_ndx, c.ndx_r, c.ndx_sig[200], 1.5, 'ndx_d'),
                                     ('P11_NDX_SMA200', c.D_ndx, c.ndx_r, c.ndx_sig[200], 2, 'ndx_d'), ('P12_NDX_SMA200', c.D_ndx, c.ndx_r, c.ndx_sig[200], 3, 'ndx_d'),
                                     ('E08_US_FABER10D', c.D_us, c.r_us, c.us_faberD, 2, 'us_d'), ('E09_US_FABER10D', c.D_us, c.r_us, c.us_faberD, 3, 'us_d')):
        out.append(spec(f'H_{base}_L{L}_FUTCOST', 'posthoc', f'【事後】{base} {L}倍を先物の費用（RF+0.3%・経費0）で',
                        (lambda D=D, r=r, sig=sig, L=L: run_daily(D, r, c.rf_us, sig, L, spread=FUT_SPREAD, fee=FUT_FEE)), bench, None, True, PP_GAYED, None, graded=False,
                        label='事後（第1族の結果を見た後の問い・判定しない）'))
    return out


# ───────────────────────── 第3族: トレンド＋ボラ目標の倍率 ─────────────────────────
def sigma_rms(D, r, a=None, z=None):
    x = [r[d] for d in D if (a is None or d >= a) and (z is None or d <= z)]
    return math.sqrt(252 * sum(v * v for v in x) / len(x))


def vt_exposure(D, r, sigma_star, Lmax, win=21):
    """月末に倍率 e = min(Lmax, σ*/σ̂) を決める（σ̂ = 直近21営業日の二乗平均の平方根×√252）→ {月末の日付: e}"""
    out = {}
    for i, d in enumerate(D):
        if (i == len(D) - 1 or D[i + 1] // 100 != d // 100) and i >= win - 1:
            w = [r[D[j]] for j in range(i - win + 1, i + 1)]
            sh = math.sqrt(252 * sum(x * x for x in w) / win)
            out[d] = min(Lmax, sigma_star / sh) if sh > 0 else Lmax
    return out


def run_daily_vt(D, r, rf, sig_on_D, e_on_D, lag=2):
    """日次。信号と倍率はどちらも i-lag の値。持つ日 = e×r − (e−1)×RF − [e>1: (e−1)×0.5%/252 + 0.9%/252]"""
    for d in D:
        if d not in rf or d not in r:
            raise RuntimeError(f'RF かリターンが無い日 {d}（0で埋めない）')
    idx = [i for i in range(lag, len(D)) if sig_on_D[i - lag] is not None and e_on_D[i - lag] is not None]
    if not idx:
        return None
    first_m = D[idx[0]] // 100
    if D[idx[0] - 1] // 100 == first_m:
        idx = [i for i in idx if D[i] // 100 != first_m]
    keys, inv, cash, pos, gross, net, net05 = [], [], [], [], {}, {}, {}
    sw, ps, pe, esum, ein = 0, None, None, 0.0, 0
    for i in idx:
        d = D[i]; s = sig_on_D[i - lag]; e = e_on_D[i - lag]; v = r[d]; f = rf[d]
        ir = e * v - (e - 1) * f - (((e - 1) * SPREAD + FEE) / 252 if e > 1 else 0.0)
        ir = max(ir, -1.0)
        g = ir if s else f
        c = 0.0
        if ps is not None and s != ps:
            c = 1.0; sw += 1
        elif s and ps and pe is not None and e != pe:
            c = abs(e - pe)
        keys.append(d); inv.append(ir); cash.append(f); pos.append(s)
        gross[d] = g; net[d] = (1 + g) * (1 - COST * c) - 1; net05[d] = (1 + g) * (1 - COST_LO * c) - 1
        if s:
            esum += e; ein += 1
        ps, pe = s, e
    return {'keys': keys, 'inv': inv, 'cash': cash, 'pos': pos, 'gross': gross, 'net': net, 'net05': net05, 'switches': sw,
            'avg_exposure_when_in': round(esum / ein, 3) if ein else None}


def region_eval_vt(c, trend, Lmax):
    """第3族の C5: Europe・Japan・Asia_Pacific_ex_Japan（日次）で同じ規則。σ* は地域の 1990-07〜2006-12"""
    det = {}
    for nm in c.REG_D:
        g = c.regd[nm]; D = g['D']
        ss = sigma_rms(D, g['r'], z=20061231)
        ed = map_sig(D, vt_exposure(D, g['r'], ss, Lmax))
        sd = map_sig(D, sma_sig(g['idx'], 200)) if trend == 'sma' else map_sig(D, month_end_sig_sma(g['idx'], 10))
        run = run_daily_vt(D, g['r'], g['rf'], sd, ed)
        det[nm] = pack_region(M.to_monthly(run['gross']), M.to_monthly(run['net']), M.to_monthly({d: g['r'][d] for d in run['keys']}))
        det[nm]['sigma_star'] = round(ss * 100, 2)
    counted = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']
    return {'regions': len(counted), 'positive': sum(1 for nm in counted if det[nm]['positive']), 'counted': counted,
            'rule_positive': 'ex_ann>0 かつ cagr_diff>0（費用後・地域の全期間）・Emerging は日次が無くボラが測れないので数えない', 'detail': det}


def family3(c):
    out = []
    s_us = sigma_rms(c.D_us, c.r_us, z=20061231)
    s_ndx = sigma_rms(c.D_ndx, c.ndx_r, z=20061231)
    c.sanity['vt_sigma_star'] = {'US_1926_2006': round(s_us * 100, 2), 'NDX_1985_2006': round(s_ndx * 100, 2)}
    log('ボラ目標 σ*', c.sanity['vt_sigma_star'])
    ones_us = [1] * len(c.D_us); ones_ndx = [1] * len(c.D_ndx)
    for L in (1, 2, 3):
        e_us = map_sig(c.D_us, vt_exposure(c.D_us, c.r_us, s_us, L))
        e_ndx = map_sig(c.D_ndx, vt_exposure(c.D_ndx, c.ndx_r, s_ndx, L))
        out.append(spec(f'V1_US_SMA200_VT_L{L}', 'exploratory3', f'US ^GSPC 200日線＋ボラ目標（σ*={s_us * 100:.1f}%・上限{L}倍）',
                        (lambda e=e_us: run_daily_vt(c.D_us, c.r_us, c.rf_us, c.sig_gspc[200], e)), 'us_d', None, True, PP_GAYED, {'kind': 'vt', 'trend': 'sma', 'L': L}))
        out.append(spec(f'V2_NDX_SMA200_VT_L{L}', 'exploratory3', f'NDX ^NDX 200日線＋ボラ目標（σ*={s_ndx * 100:.1f}%・上限{L}倍）',
                        (lambda e=e_ndx: run_daily_vt(c.D_ndx, c.ndx_r, c.rf_us, c.ndx_sig[200], e)), 'ndx_d', None, True, PP_GAYED, {'kind': 'vt', 'trend': 'sma', 'L': L}))
        out.append(spec(f'V3_US_FABER10D_VT_L{L}', 'exploratory3', f'US 10か月線（日次・1日遅れ）＋ボラ目標（上限{L}倍）',
                        (lambda e=e_us: run_daily_vt(c.D_us, c.r_us, c.rf_us, c.us_faberD, e)), 'us_d', None, True, PP_FABER, {'kind': 'vt', 'trend': 'faber_d', 'L': L}))
        if L in (1, 2):
            out.append(spec(f'R_US_VTONLY_L{L}', 'report', f'US トレンドなし・ボラ目標だけ（上限{L}倍）【報告のみ】',
                            (lambda e=e_us: run_daily_vt(c.D_us, c.r_us, c.rf_us, ones_us, e)), 'us_d', None, True, PP_GAYED, None, graded=False,
                            label='報告のみ（トレンドが何を足したかの比較・ボラ管理は別の角度の領分）'))
            out.append(spec(f'R_NDX_VTONLY_L{L}', 'report', f'NDX トレンドなし・ボラ目標だけ（上限{L}倍）【報告のみ】',
                            (lambda e=e_ndx: run_daily_vt(c.D_ndx, c.ndx_r, c.rf_us, ones_ndx, e)), 'ndx_d', None, True, PP_GAYED, None, graded=False,
                            label='報告のみ（トレンドが何を足したかの比較・ボラ管理は別の角度の領分）'))
    return out


# ───────────────────────── 第4族: 信号の平均で持つ割合を段階的に ─────────────────────────
ENS_N = (50, 100, 150, 200, 250, 300)
ENS_M = (2, 5, 7, 10, 12, 14)


def hop_frac(ex_idx, hs=(1, 3, 12)):
    """月末に h か月の超過が正の数 ÷ 3 → {月末の日付/月: 割合}（日次の超過指数でも月次の超過指数でも）"""
    ks = sorted(ex_idx)
    me = month_ends(ks) if ks[0] > 10 ** 7 else ks
    out = {}
    for i in range(max(hs), len(me)):
        out[me[i]] = sum(1 for h in hs if ex_idx[me[i]] / ex_idx[me[i - h]] > 1) / len(hs)
    return out


def ens_frac(px, Ns=ENS_N):
    """価格 > N 日線 の本数 ÷ 本数（全部の線がそろう日から）"""
    sigs = [sma_sig(px, N) for N in Ns]
    common = set(sigs[0])
    for x in sigs[1:]:
        common &= set(x)
    return {k: sum(x[k] for x in sigs) / len(Ns) for k in common}


def run_monthly_frac(ms, r, rf, e_by_m, lag=1):
    keys, gross, net, net05 = [], {}, {}, {}
    pe = None
    for i in range(lag, len(ms)):
        e = e_by_m.get(ms[i - lag])
        if e is None:
            continue
        k = ms[i]
        if k not in r or k not in rf:
            raise RuntimeError(f'月 {k} のデータ欠け（0で埋めない）')
        g = e * r[k] - (e - 1) * rf[k] - (((e - 1) * SPREAD + FEE) / 12 if e > 1 else 0.0)
        g = max(g, -1.0)
        cst = abs(e - pe) if pe is not None else 0.0
        keys.append(k); gross[k] = g; net[k] = (1 + g) * (1 - COST * cst) - 1; net05[k] = (1 + g) * (1 - COST_LO * cst) - 1
        pe = e
    return {'keys': keys, 'gross': gross, 'net': net, 'net05': net05}


def region_eval_frac(c, kind, L):
    det = {}
    for nm in c.REG_D:
        g = c.regd[nm]; D = g['D']
        f = hop_frac(g['ex_idx']) if kind == 'hop' else ens_frac(g['idx'])
        ed = [None if x is None else L * x for x in map_sig(D, f)]
        run = run_daily_vt(D, g['r'], g['rf'], [1] * len(D), ed)
        det[nm] = pack_region(M.to_monthly(run['gross']), M.to_monthly(run['net']), M.to_monthly({d: g['r'][d] for d in run['keys']}))
    ms, r, rf = c.ms_em, c.em_mkt, c.em_rf
    if kind == 'hop':
        f = hop_frac(cum_index({k: r[k] - rf[k] for k in ms}))
    else:
        idx = cum_index({k: r[k] for k in ms})
        f = ens_frac({k: idx[k] for k in ms}, ENS_M)
    run = run_monthly_frac(ms, r, rf, {k: L * v for k, v in f.items()})
    det['Emerging'] = pack_region(run['gross'], run['net'], {k: r[k] for k in run['keys']})
    return {'regions': len(c.COUNTED), 'positive': sum(1 for nm in c.COUNTED if det[nm]['positive']), 'counted': c.COUNTED,
            'rule_positive': 'ex_ann>0 かつ cagr_diff>0（費用後・地域の全期間）', 'detail': det}


def family4(c):
    out = []
    ndx_ex = cum_index({d: c.ndx_r[d] - c.rf_us[d] for d in c.D_ndx})
    fr = {'US_HOP': (c.D_us, c.r_us, hop_frac(c.us_ex_idx), 'us_d', 'hop', PP_MOP),
          'NDX_HOP': (c.D_ndx, c.ndx_r, hop_frac(ndx_ex), 'ndx_d', 'hop', PP_MOP),
          'US_ENS': (c.D_us, c.r_us, ens_frac(c.gspc), 'us_d', 'ens', PP_GAYED),
          'NDX_ENS': (c.D_ndx, c.ndx_r, ens_frac(c.ndx_px), 'ndx_d', 'ens', PP_GAYED)}
    for j, (nm, (D, r, f, bench, kind, pp)) in enumerate(fr.items()):
        fD = map_sig(D, f)
        for L in (1, 2, 3):
            eD = [None if x is None else L * x for x in fD]
            out.append(spec(f'T{j + 1}_{nm}_L{L}', 'exploratory4', f'{nm}（信号の平均で割合を段階的に）・{L}倍',
                            (lambda D=D, r=r, eD=eD: run_daily_vt(D, r, c.rf_us, [1] * len(D), eD)), bench, None, True, pp, {'kind': 'frac', 'frac': kind, 'L': L}))
    return out


# ───────────────────────── 本体 ─────────────────────────
def bench_for(c, kind, run):
    """相手（月次）・RF（月次）・日次の原資産・（原資産, RF の源）"""
    ks = run['keys']
    if kind == 'us_m':
        return {k: c.r_usm[k] for k in ks}, {k: c.rf_usm[k] for k in ks}, None, (c.r_usm, c.rf_usm)
    if kind == 'sh_m':
        return {k: c.sr[k] for k in ks}, {k: c.rf_sh[k] for k in ks}, None, (c.sr, c.rf_sh)
    rr = kind[1] if isinstance(kind, tuple) else {'us_d': c.r_us, 'ndx_d': c.ndx_r, 'ixic_d': c.ixic_r}[kind]
    return M.to_monthly({d: rr[d] for d in ks}), M.to_monthly({d: c.rf_us[d] for d in ks}), rr, (rr, c.rf_us)


def lag_check(D, sigD, run):
    pos_by = dict(zip(run['keys'], run['pos']))
    idx = {d: i for i, d in enumerate(D)}
    bad = sum(1 for d in run['keys'][:4000] if pos_by[d] != sigD[idx[d] - 2])
    return {'checked': min(4000, len(run['keys'])), 'mismatch': bad}


_G = {}


def _one(i):
    c, st = _G['c'], _G['specs'][i]
    return run_one(c, st)


def run_specs(c, specs):
    """並列（fork）で1本ずつ測る。MW_TREND_PROCS=1 なら直列"""
    n = int(os.environ.get('MW_TREND_PROCS', '3'))
    _G['c'], _G['specs'] = c, specs
    if n > 1:
        import multiprocessing as mp
        with mp.get_context('fork').Pool(n) as pool:
            res = pool.map(_one, range(len(specs)), chunksize=1)
    else:
        res = [_one(i) for i in range(len(specs))]
    tested = []
    for ent in res:
        if ent is None:
            continue
        for k, v in ent.pop('_sanity', {}).items():
            c.sanity[k] = v
        for line in ent.pop('_log', []):
            LOG.append(line)
        tested.append(ent)
    return tested


def run_one(c, st):
    if True:
        run = st['runner']()
        if run is None:
            log('実行不能', st['id']); return None
        b_m, rf_m, rr_d, (rsrc, rfsrc) = bench_for(c, st['bench'], run)
        blev_m = None
        if st['per_daily'] and st['blev'] is not None and st['blev'] != 1:
            blev_m = M.to_monthly(M.lever_daily({d: rr_d[d] for d in run['keys']}, st['blev'], {d: c.rf_us[d] for d in run['keys']}, spread=SPREAD, fee=FEE))
        e = evaluate(run, b_m, rf_m, blev_m, st['per_daily'], st['post_pub'])
        ent = {'id': st['id'], 'family': st['family'], 'desc': st['desc'], 'rule': st['rule'], 'graded': st['graded'],
               'window': [run['keys'][0], run['keys'][-1]], **e}
        if st['label']:
            ent['label'] = st['label']
        if st['id'].startswith('P03'):
            ent.setdefault('_sanity', {})['lag_check_us_sma200'] = lag_check(c.D_us, c.sig_gspc[200], run)
        if st['id'].startswith('P08'):
            ent.setdefault('_sanity', {})['lag_check_ndx_sma200'] = lag_check(c.D_ndx, c.ndx_sig[200], run)
        if 'avg_exposure_when_in' in run:
            ent['avg_exposure_when_in'] = run['avg_exposure_when_in']
        if st['rule'] is not None and st['graded']:
            k = st['rule']['kind']
            ent['repl'] = (region_eval_vt(c, st['rule']['trend'], st['rule']['L']) if k == 'vt' else
                           region_eval_frac(c, st['rule']['frac'], st['rule']['L']) if k == 'frac' else region_eval(c, st['rule']))
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
                    bl = {'keys': run['keys'], 'inv': [lev_ret(rsrc[k], rfsrc[k], st['blev'], 252) for k in run['keys']], 'cash': [rfsrc[k] for k in run['keys']]}
                    ent['tax_japan']['vs_levered_bh_windows'] = tax_report(run, bl, per, yearf, win)
        h = e['hold']; t = e['train']
        log(f"{st['id']:34s} 訓練 {t['ex_ann'] if t else None:>7} t{t['t'] if t else None} 保有 {h['ex_ann'] if h else None:>7} t{h['t'] if h else None} 幾何差 {h['cagr_diff'] if h else None} "
            f"費用後保有 {e['cost_hold']['ex_ann'] if e['cost_hold'] else None} 20年勝率 {e['roll20']['win_rate'] if e['roll20'] else None} "
            f"Sharpe訓練 {e['sharpe']['train']} 保有 {e['sharpe']['hold']} 地域 {ent.get('repl', {}).get('positive')}/{ent.get('repl', {}).get('regions')}")
        ent['_log'] = [LOG[-1]]
        return ent


def main():
    res = {'angle': 'trend', 'prereg': PRE_NAMES}
    shas = {}
    for p in PRE_NAMES:
        try:
            shas[p] = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', os.path.join('out', p)], cwd=M.BASE).decode().strip() or None
        except Exception:
            shas[p] = None
    res['prereg_commit'] = shas
    log('事前登録の commit', shas)
    c = load()
    specs = family1(c) + family2(c) + family3(c) + family4(c)
    tested = run_specs(c, specs)
    lv1 = M.lever_daily({d: c.r_us[d] for d in c.D_us[:1000]}, 1, {d: c.rf_us[d] for d in c.D_us[:1000]}, spread=SPREAD, fee=0.0)
    c.sanity['lever1_equals_bh'] = max(abs(lv1[d] - c.r_us[d]) for d in c.D_us[:1000]) < 1e-12
    # Holm と判定
    prim = {x['id']: x['hold']['p'] for x in tested if x['family'] == 'primary' and x['hold']}
    allg = {x['id']: x['hold']['p'] for x in tested if x['graded'] and x['hold']}
    hp, ha = M.holm(prim), M.holm(allg)
    for x in tested:
        if not x['graded']:
            x['grade'] = '報告のみ（判定しない）'; continue
        if x['family'] == 'primary':
            x['holm_family'] = f'primary({len(prim)})'; x['holm_p'] = hp.get(x['id'])
        else:
            x['holm_family'] = f'all_graded({len(allg)})'; x['holm_p'] = ha.get(x['id'])
        sp = {'train': tuple(x['sharpe']['train']), 'hold': tuple(x['sharpe']['hold'])}
        g, cr = M.grade(x['full'], x['train'], x['hold'], x['roll20'], cost_hold=x['cost_hold'], repl=x.get('repl'),
                        family_holm_p=x['holm_p'], sharpe_pair=sp, leveraged_or_timing=True)
        x['grade'] = g; x['criteria'] = cr
        if x['family'] != 'primary' and 'label' not in x:
            x['label'] = {'exploratory': '探索（第1族）', 'exploratory2': '探索（第2族・第1族の結果を見た後に登録）', 'exploratory3': '探索（第3族・第1族の結果を見た後に登録）', 'exploratory4': '探索（第4族・第1族の結果を見た後に登録）', 'grid': '頑健性の格子（勝ちの主張には使わない）'}[x['family']]
    res['sanity'] = c.sanity
    res['train_selection'] = getattr(c, 'train_selection', None)
    res['n_tested'] = len(tested)
    res['n_graded'] = len(allg)
    res['grades'] = {g: [x['id'] for x in tested if x.get('grade') == g] for g in ('S', 'A', 'B', 'C')}
    res['tested'] = tested
    res['log'] = LOG
    p = M.save(OUT_NAME, res)
    log('書いた', p, '格付け', {g: len(v) for g, v in res['grades'].items()})


if __name__ == '__main__':
    main()
