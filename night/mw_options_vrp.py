#!/usr/bin/env python3
"""night/mw_options_vrp.py — 市場に勝てる歴史検証（mw）の角度『options_vrp』（読むだけ・門の判定には不使用）

問い: S&P500 のオプションを売る戦略（ボラティリティ・リスク・プレミアム）は、同じ揺れまで借りてそろえたとき、
S&P500 配当込みにリターンで勝つか。規則は CBOE の公表済みの指数定義そのもの＋指示書の借り方（36か月のぶれの比・上限2倍）。
事前登録: out/mw_options_vrp_prereg.json（測る前にコミット）。線は out/mw_prereg.json（mw_common.grade）。
第2部（探索）: out/mw_options_vrp_prereg2.json（第1部の結果を見た後・第2部を測る前にコミット）＝
  F 族: VRP（VIX²/12 − 日次の実現分散）で S&P500 の持ち高を変える（BTZ 2009・CT 2008・w∈[0,1.5]）と米国外4地域での答え合わせ（C5）、
  G 族: オプション売りの株の向きを過去36か月の β で消した保険料を S&P500 に1倍重ねる（Israelov・Nielsen 2015）。

使い方: python3 night/mw_options_vrp.py            → out/mw_options_vrp.json
        python3 night/mw_options_vrp.py --data-only → データの取得と指数どうしの照合だけ（戦略と市場は比べない）
"""
import sys, os, json, math, statistics as S, time, datetime, subprocess, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

ANGLE = 'options_vrp'
PRE = 'mw_options_vrp_prereg.json'
OUT = 'mw_options_vrp.json'
CB = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'
END = 202608
TE, HS, RS = M.TRAIN_END, M.HOLD_START, M.RECENT_START
t0 = time.time()
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


# ───────────────────────── データ ─────────────────────────
def cboe_daily(sym):
    b = M.get(CB.format(sym), name=f'cboe_{sym}_History.csv', max_age_days=30)
    lines = b.decode('latin-1').splitlines()
    head = [h.strip().upper() for h in lines[0].split(',')]
    ci = head.index('CLOSE') if 'CLOSE' in head else 1
    d = {}
    for line in lines[1:]:
        c = line.split(',')
        if len(c) <= ci:
            continue
        try:
            mm, dd, yy = c[0].split('/')
            v = float(c[ci])
        except ValueError:
            continue
        if v <= 0:
            continue
        d[int(yy) * 10000 + int(mm) * 100 + int(dd)] = v
    return d


def fred_daily(sid):
    c = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}_daily.csv', max_age_days=30).decode()
    out = {}
    for line in c.strip().splitlines()[1:]:
        d, v = line.split(',')
        if v in ('', '.'):
            continue
        out[int(d.replace('-', ''))] = float(v)
    return out


def monthly_from_daily(d, a=None):
    """各月の最後の観測（20日以降）→ 連続した月だけリターン。欠けた月は作らない"""
    last = {}
    for k in sorted(d):
        if a is not None and k < a:
            continue
        last[k // 100] = (k, d[k])
    ks = sorted(last)
    out = {}
    for p, k in zip(ks, ks[1:]):
        if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) != 1:
            continue
        if last[p][0] % 100 < 20 or last[k][0] % 100 < 20:
            continue
        if k > END:
            continue
        out[k] = last[k][1] / last[p][1] - 1
    return out


def shiller_div():
    import xlrd
    b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', name='shiller_ie_data.xls', max_age_days=3650)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    D = {}
    for i in range(8, sh.nrows):
        row = sh.row_values(i)
        if not isinstance(row[0], float):
            continue
        s = f'{row[0]:.2f}'
        k = int(s[:4]) * 100 + int(s[5:7])
        if isinstance(row[2], float):
            D[k] = row[2]
    return D


def cap_end(r):
    return {k: v for k, v in r.items() if k <= END}


def consecutive(ks):
    return all((b // 100 * 12 + b % 100) - (a // 100 * 12 + a % 100) == 1 for a, b in zip(ks, ks[1:]))


def load_all():
    D = {}
    src = {}
    ff = M.ff_factors()
    D['rf'] = cap_end(ff['rf'])
    D['mkt'] = cap_end(ff['mkt'])
    # S&P500 配当込み
    tr = cap_end(M.yahoo('^SP500TR'))
    spx = cboe_daily('SPX')
    dv = shiller_div()
    spm = {}
    last = {}
    for k in sorted(spx):
        last[k // 100] = spx[k]
    ks = sorted(last)
    con = {k: (last[k] + dv[k] / 12) / last[p] - 1 for p, k in zip(ks, ks[1:]) if k in dv}
    for k in range(198607, 198802):
        if k % 100 == 0 or k % 100 > 12:
            continue
        if k in con:
            spm[k] = con[k]
    for k, v in tr.items():
        spm[k] = v
    D['sp'] = dict(sorted(spm.items()))
    D['_sp_constructed'] = {k: con[k] for k in con if k <= 200612}
    D['_sp_yahoo'] = tr
    # 為替
    fx = fred_daily('DEXCAUS')
    D['_fx_n'] = len(fx)

    def cad(sym):
        c = cboe_daily(sym)
        return monthly_from_daily({k: v / fx[k] for k, v in c.items() if k in fx})
    # PUT
    put_usd = monthly_from_daily(cboe_daily('PUT'), a=20070101)
    put_yh = cap_end(M.yahoo('^PUT'))
    put_cad = cad('PUTCAD')
    put, ps = {}, {}
    for k in sorted(set(put_usd) | set(put_yh) | set(put_cad)):
        if k in put_usd:
            put[k], ps[k] = put_usd[k], 'cboe_usd'
        elif k in put_yh:
            put[k], ps[k] = put_yh[k], 'yahoo'
        elif k in put_cad:
            put[k], ps[k] = put_cad[k], 'cad_fx'
    D['PUT'] = put
    src['PUT'] = dict(collections.Counter(ps.values()))
    src['PUT_ranges'] = {s: [min(k for k in ps if ps[k] == s), max(k for k in ps if ps[k] == s)] for s in set(ps.values())}
    D['_put_parts'] = (put_usd, put_yh, put_cad)
    # BXM
    bxm_usd = monthly_from_daily(cboe_daily('BXM'), a=20020322)
    bxm_cad = cad('BXMCAD')
    bxm, bs = {}, {}
    for k in sorted(set(bxm_usd) | set(bxm_cad)):
        if k in bxm_usd:
            bxm[k], bs[k] = bxm_usd[k], 'cboe_usd'
        else:
            bxm[k], bs[k] = bxm_cad[k], 'cad_fx'
    D['BXM'] = bxm
    src['BXM'] = dict(collections.Counter(bs.values()))
    src['BXM_ranges'] = {s: [min(k for k in bs if bs[k] == s), max(k for k in bs if bs[k] == s)] for s in set(bs.values())}
    D['_bxm_parts'] = (bxm_usd, bxm_cad)
    for sym in ['BXMD', 'BXY', 'PUTY', 'CMBO', 'BXMC', 'BXMH', 'CNDR', 'BFLY', 'RXM', 'PPUT', 'CLLZ', 'CLL', 'WPUT', 'BXMW', 'VXTH',
                'VPD', 'PUTVM', 'BXMVM', 'BXD', 'BXR', 'PUTR', 'BXN']:
        D[sym] = monthly_from_daily(cboe_daily(sym))
    # 水準の断絶（事前登録 data.cleaning）: その月を欠測にする（0 にしない）
    for sym, months in BREAKS.items():
        for mth in months:
            D[sym].pop(mth, None)
    # BXM の頑健性版: 1990-02〜2002-03 を 2×BXMH − SPXTR
    alt = {}
    for k, v in bxm.items():
        if bs[k] == 'cad_fx' and k in D['BXMH'] and k in D['sp']:
            alt[k] = 2 * D['BXMH'][k] - D['sp'][k]
        elif bs[k] == 'cboe_usd':
            alt[k] = v
    D['BXM_alt'] = alt
    for k, v in D.items():
        if not k.startswith('_') and isinstance(v, dict) and v:
            ks = sorted(v)
            gaps = not consecutive(ks)
            src.setdefault('ranges', {})[k] = [ks[0], ks[-1], len(ks), 'GAPS' if gaps else 'ok']
    D['_src'] = src
    return D


BREAKS = {'CLL': [200910]}  # CLL 2009-10-16 に1日 −19.8%（SPX −0.8%）・戻らない＝水準の断絶


def break_scan():
    """1日に ±7% 超・同じ日の SPX が ±3% 未満の日を洗い出す（データの点検・市場との比較ではない）"""
    import datetime as dt
    spx = cboe_daily('SPX')
    ks = sorted(spx)
    rs = {k: spx[k] / spx[p] - 1 for p, k in zip(ks, ks[1:])}
    out = {}
    for sym in ['PUT', 'BXM', 'BXMD', 'BXY', 'PUTY', 'CMBO', 'BXMC', 'BXMH', 'CNDR', 'BFLY', 'RXM', 'PPUT', 'CLLZ', 'CLL', 'WPUT', 'BXMW',
                'VXTH', 'VPD', 'PUTVM', 'BXMVM', 'BXD', 'BXR', 'PUTR', 'BXN', 'PUTCAD', 'BXMCAD']:
        d = cboe_daily(sym)
        kk = sorted(d)
        fl = []
        for p, k in zip(kk, kk[1:]):
            dp = dt.date(p // 10000, p // 100 % 100, p % 100); dk = dt.date(k // 10000, k // 100 % 100, k % 100)
            if (dk - dp).days > 6 or k not in rs:
                continue
            r = d[k] / d[p] - 1
            if abs(r) > 0.07 and abs(rs[k]) < 0.03:
                fl.append([k, round(r * 100, 1), round(rs[k] * 100, 1)])
        if fl:
            out[sym] = fl
    return out


# ───────────────────────── 戦略の組み立て ─────────────────────────
COST = {'PUT': 0.6, 'BXM': 0.6, 'BXMD': 0.36, 'BXY': 0.36, 'PUTY': 0.36, 'CMBO': 0.48, 'BXMC': 0.45, 'BXMH': 0.3, 'CNDR': 0.96,
        'BFLY': 1.92, 'RXM': 0.96, 'PPUT': 0.36, 'CLLZ': 1.08, 'CLL': 0.48, 'WPUT': 1.3, 'BXMW': 0.65, 'VXTH': 0.3, 'VPD': 0.6,
        'PUTVM': 0.6, 'BXMVM': 0.6, 'BXD': 0.6, 'BXR': 0.6, 'PUTR': 0.6, 'BXN': 0.6, 'BXM_alt': 0.6}
SPREAD = 0.005
DL_COST = 0.0005


def unlevered(x, rf, cost_ann):
    ks = sorted(k for k in x if k in rf and k <= END)
    s = {k: x[k] for k in ks}
    net = {k: x[k] - cost_ann / 100 / 12 for k in ks}
    return s, net, None


def levered(x, b, rf, cost_ann, win=36, cap=2.0):
    ks = sorted(k for k in x if k in b and k in rf and k <= END)
    s, net, L = {}, {}, {}
    prev = None
    for i, k in enumerate(ks):
        if i < win:
            continue
        w = ks[i - win:i]
        assert w[-1] < k and len(w) == win  # 後知恵なし: t−win〜t−1 だけ
        if not consecutive(w + [k]):
            prev = None
            continue
        sx = S.stdev([x[u] for u in w]); sb = S.stdev([b[u] for u in w])
        if not sx > 0:
            continue
        l = min(cap, sb / sx)
        r = rf[k] + l * (x[k] - rf[k]) - max(l - 1, 0) * SPREAD / 12
        s[k] = r
        net[k] = r - cost_ann / 100 / 12 * l - (abs(l - prev) * DL_COST if prev is not None else 0)
        L[k] = l
        prev = l
    return s, net, L


def overlay(y, b, rf, cost_ann):
    ks = sorted(k for k in y if k in b and k in rf and k <= END)
    s = {k: b[k] + (y[k] - rf[k]) - SPREAD / 12 for k in ks}
    net = {k: s[k] - cost_ann / 100 / 12 for k in ks}
    return s, net, None


# ───────────────────────── 評価 ─────────────────────────
EPIS = {'1987-10': (198710, 198710), '1998-08': (199808, 199808), '2000-09..2002-09': (200009, 200209), '2008': (200801, 200812),
        '2008-09..2009-02': (200809, 200902), '2020-02..2020-03': (202002, 202003), '2022': (202201, 202212), '2025-02..2025-04': (202502, 202504)}


def comp(r, a, z):
    ks = [k for k in sorted(r) if a <= k <= z]
    if not ks or ks[0] != a or ks[-1] != z:
        return None
    w = 1.0
    for k in ks:
        w *= 1 + r[k]
    return round((w - 1) * 100, 2)


def same(s, b):
    ks = sorted(set(s) & set(b))
    return {k: s[k] for k in ks}, {k: b[k] for k in ks}


def evaluate(name, s, net, b, rf, L=None, meta=None, postpub=None):
    s, bb = same(s, b)
    net = {k: net[k] for k in s}
    e = {'name': name}
    e.update(meta or {})
    if len(s) < 24:
        e['status'] = 'データ不足'
        e['months'] = len(s)
        return e
    e['from'], e['to'], e['months'] = min(s), max(s), len(s)
    e['full'] = M.excess_stats(s, bb)
    e['train'] = M.excess_stats(s, bb, z=TE)
    e['hold'] = M.excess_stats(s, bb, a=HS)
    e['recent'] = M.excess_stats(s, bb, a=RS)
    if postpub:
        e['postpub_from'] = postpub
        e['postpub'] = M.excess_stats(s, bb, a=postpub)
    e['cost_full'] = M.excess_stats(net, bb)
    e['cost_hold'] = M.excess_stats(net, bb, a=HS)
    e['cost_train'] = M.excess_stats(net, bb, z=TE)
    e['roll20'] = M.rolling(s, bb, 20)
    e['dca20'] = M.dca(s, bb, 20)
    rfx = {k: rf[k] for k in s}
    e['sharpe'] = {'train': (M.sharpe(s, rfx, z=TE), M.sharpe(bb, rfx, z=TE)), 'hold': (M.sharpe(s, rfx, a=HS), M.sharpe(bb, rfx, a=HS)),
                   'full': (M.sharpe(s, rfx), M.sharpe(bb, rfx)), 'recent': (M.sharpe(s, rfx, a=RS), M.sharpe(bb, rfx, a=RS)),
                   'hold_net': (M.sharpe(net, rfx, a=HS), M.sharpe(bb, rfx, a=HS))}
    e['maxdd'] = {'full': (round(M.maxdd(s) * 100, 1), round(M.maxdd(bb) * 100, 1)),
                  'hold': (round(M.maxdd(M.window(s, HS)) * 100, 1), round(M.maxdd(M.window(bb, HS)) * 100, 1))}
    e['episodes'] = {k: (comp(s, a, z), comp(bb, a, z)) for k, (a, z) in EPIS.items()}
    e['cagr_total'] = {'full': round(M.cagr(s) * 100, 2), 'bench_full': round(M.cagr(bb) * 100, 2)}
    if L:
        lv = [L[k] for k in s if k in L]
        e['leverage'] = {'mean': round(S.mean(lv), 2), 'min': round(min(lv), 2), 'max': round(max(lv), 2),
                         'at_cap_share': round(sum(1 for x in lv if x >= 1.999) / len(lv), 3),
                         'mean_hold': round(S.mean([L[k] for k in s if k in L and k >= HS]), 2)}
    return e


def finish(e, holm_p=None, repl=None):
    if e.get('status') == 'データ不足':
        e['grade'], e['criteria'] = 'C', {'note': 'データ不足'}
        return e
    sp = e['sharpe']
    e['repl'] = repl
    g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=repl,
                   family_holm_p=holm_p, sharpe_pair={'train': sp['train'], 'hold': sp['hold']}, leveraged_or_timing=True)
    e['family_holm_p'] = holm_p
    e['grade'], e['criteria'] = g, c
    return e


# ───────────────────────── 実在の器・税 ─────────────────────────
def yahoo_raw(t):
    """mw_common.yahoo がキャッシュした JSON から分配（dividends）と終値を読む（新しく取りに行かない）"""
    p = os.path.join(M.CACHE, f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json')
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    r = j['chart']['result'][0]
    ts = r['timestamp']
    close = r['indicators']['quote'][0]['close']
    px = {}
    for tt, c in zip(ts, close):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(tt)
        px[d.year * 100 + d.month] = c
    dv = collections.defaultdict(float)
    for v in (r.get('events', {}) or {}).get('dividends', {}).values():
        d = datetime.datetime.utcfromtimestamp(v['date'])
        dv[d.year * 100 + d.month] += v['amount']
    ks = sorted(px)
    yld = {k: dv.get(k, 0.0) / px[p] for p, k in zip(ks, ks[1:])}
    meta = r.get('meta', {})
    return {'yield_m': yld, 'name': meta.get('longName') or meta.get('shortName'), 'currency': meta.get('currency')}


def jp_after_tax(r, y, rb, yb, tau_div, bench_wht=0.10, cg=0.20315, taxable=True):
    """一括1で始め、毎月: 器 = (1+r) − y×tau_div（分配の税を払って再投資）。相手（分配しない投信）= (1+rb) − yb×bench_wht。
    課税口座は最後に 値上がり益×20.315%（取得価額＝元本＋再投資した税引後分配）。年率の差を返す"""
    ks = sorted(k for k in r if k in rb and k in y and k in yb)
    if len(ks) < 24:
        return None
    w, basis, wb = 1.0, 1.0, 1.0
    for k in ks:
        net_div = w * y[k] * (1 - tau_div)
        w = w * (1 + r[k]) - w * y[k] * tau_div
        basis += net_div
        wb = wb * (1 + rb[k]) - wb * yb[k] * bench_wht
    if taxable:
        w = w - max(0.0, w - basis) * cg
        wb = wb - max(0.0, wb - 1.0) * cg
    n = len(ks) / 12
    g, gb = w ** (1 / n) - 1, wb ** (1 / n) - 1
    return {'from': ks[0], 'to': ks[-1], 'years': round(n, 1), 'cagr_after_tax': round(g * 100, 2), 'bench_after_tax': round(gb * 100, 2),
            'diff': round((g - gb) * 100, 2)}


# ───────────────────────── 第2部（prereg2・探索） ─────────────────────────
PRE2 = 'mw_options_vrp_prereg2.json'
GAMMA, WMAX, BURN, VARWIN, TCOST = 3.0, 1.5, 60, 60, 0.001
F_START = 199504


def madd(m, n):
    y, mm = divmod(m // 100 * 12 + m % 100 - 1 + n, 12)
    return y * 100 + mm + 1


def month_end_level(d):
    """各月の最後の観測（20日以降の月だけ）の水準"""
    last = {}
    for k in sorted(d):
        last[k // 100] = (k, d[k])
    return {m: v for m, (k, v) in last.items() if k % 100 >= 20 and m <= END}


def rv_monthly(px):
    """日次の水準 → その月の日次の対数リターンの二乗の和（前月末から）。15日未満・7日を超える空白をまたぐ対は使わない"""
    ks = sorted(px)
    out, cnt = {}, collections.Counter()
    for p, k in zip(ks, ks[1:]):
        dp = datetime.date(p // 10000, p // 100 % 100, p % 100); dk = datetime.date(k // 10000, k // 100 % 100, k % 100)
        if (dk - dp).days > 7:
            continue
        r = math.log(px[k] / px[p])
        out[k // 100] = out.get(k // 100, 0.0) + r * r
        cnt[k // 100] += 1
    ends = month_end_level(px)
    return {m: v for m, v in out.items() if cnt[m] >= 15 and m in ends}


def vrp_series(vol, px):
    iv, rv = month_end_level(vol), rv_monthly(px)
    return {m: (iv[m] / 100) ** 2 / 12 - rv[m] for m in sorted(iv) if m in rv}


def monthly_from_levels(px):
    e = month_end_level(px)
    ks = sorted(e)
    return {k: e[k] / e[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k}


def ols(x, y):
    mx, my = S.mean(x), S.mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx if sxx > 0 else 0.0
    return my - b * mx, b


def fc_regress(vrp, ex, h=1, burn=BURN):
    """t 月末の予測（t+1 月に使う・月あたりの超過）。対 (VRP_s, ex_{s+1..s+h} の平均) のうち s+h ≤ t のものだけ（後知恵なし）"""
    months = sorted(vrp)
    out, info = {}, {}
    for t in months:
        xs, ys = [], []
        for s_ in months:
            if madd(s_, h) > t:
                break
            fut = [ex.get(madd(s_, j)) for j in range(1, h + 1)]
            if None in fut:
                continue
            xs.append(vrp[s_]); ys.append(sum(fut) / h)
        if len(xs) < burn:
            continue
        a, b = ols(xs, ys)
        f = (a + b * vrp[t]) if b > 0 else S.mean(ys)  # CT: 傾きの符号が逆なら標本の平均
        out[madd(t, 1)] = max(f, 0.0)
        info[madd(t, 1)] = {'b': b, 'pm': S.mean(ys), 'raw': a + b * vrp[t]}
    return out, info


def fc_median(vrp, lo, hi, burn=BURN):
    """VRP_t ≥ 1990-01〜t の中央値 なら hi、下なら lo（t+1 月に使う）"""
    out, hist = {}, []
    for t in sorted(vrp):
        hist.append(vrp[t])
        if len(hist) < burn:
            continue
        out[madd(t, 1)] = hi if vrp[t] >= S.median(hist) else lo
    return out


def trailing_var(ex, win=VARWIN):
    """t+1 月に使う = ex の t−win+1〜t の分散（連続した win か月がそろうときだけ）"""
    out = {}
    for t in sorted(ex):
        w = [madd(t, -j) for j in range(win)]
        if all(u in ex for u in w):
            out[madd(t, 1)] = S.variance([ex[u] for u in w])
    return out


def weights_from(fc, var):
    return {m: min(WMAX, max(0.0, f / (GAMMA * var[m]))) for m, f in fc.items() if m in var and var[m] > 0}


def run_w(W, r, c, spread=SPREAD, cost=TCOST, start=None):
    """W: {m: 株の割合} → 総・費用後・回転。回転 = |w − 前月の w が値動きで変わった後の割合|"""
    ks = sorted(m for m in W if m in r and m in c and m <= END and (start is None or m >= start))
    gross, net, TO = {}, {}, {}
    for m in ks:
        w = W[m]
        g = c[m] + w * (r[m] - c[m]) - max(w - 1.0, 0.0) * spread / 12
        p = madd(m, -1)
        if p in gross and (1 + gross[p]) > 0:
            prev = W[p] * (1 + r[p]) / (1 + gross[p])
        else:
            prev = w
        TO[m] = abs(w - prev)
        gross[m] = g
        net[m] = g - TO[m] * cost
    return gross, net, TO


def slope(x, y):
    return ols(x, y)[1]


def hedged_overlay(X, sp, rf, cost_ann, kind, win=36, cond=None, start=None):
    """G 族: 成分 Y（kind='excess' → X − RF、'vs_sp' → X − S&P500）の株の向きを過去 win か月の β で消して S&P500 に重ねる"""
    ks = sorted(k for k in X if k in sp and k in rf and k <= END)
    Y = {k: (X[k] - rf[k]) if kind == 'excess' else (X[k] - sp[k]) for k in ks}
    E = {k: sp[k] - rf[k] for k in ks}
    s, net, B, parts = {}, {}, {}, {'Y': [], 'bE': []}
    prev = None
    for i, k in enumerate(ks):
        if i < win or (start is not None and k < start):
            continue
        w = ks[i - win:i]
        assert w[-1] < k
        if not consecutive(w + [k]):
            prev = None
            continue
        on = True
        if cond is not None:
            if k not in cond:
                continue
            on = cond[k]
        b = slope([E[u] for u in w], [Y[u] for u in w])
        if on:
            r = sp[k] + Y[k] - b * E[k] - SPREAD / 12
            n = r - cost_ann / 100 / 12 - (abs(b - prev) * DL_COST if prev is not None else 0)
            parts['Y'].append(Y[k]); parts['bE'].append(b * E[k])
        else:
            r = n = sp[k]
        s[k], net[k], B[k] = r, n, (b if on else None)
        prev = b
    return s, net, B, parts


def yahoo_levels(t):
    """日次の水準（調整後終値・無ければ終値）。mw_common.yahoo のキャッシュを読む"""
    M.yahoo(t, '1d')
    p = os.path.join(M.CACHE, f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1d.json')
    r = json.load(open(p))['chart']['result'][0]
    adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    off = (r.get('meta') or {}).get('gmtoffset') or 0  # 取引所の現地の日付に付け直す（豪州は UTC だと前日になる）
    out = {}
    for tt, a in zip(r['timestamp'], adj):
        if a is None or a <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(tt + off)
        out[d.year * 10000 + d.month * 100 + d.day] = a
    return out


def stoxx_levels(sym):
    b = M.get(f'https://www.stoxx.com/document/Indices/Current/HistoricalData/h_{sym.lower()}.txt', name=f'stoxx_h_{sym.lower()}.txt',
              max_age_days=30).decode('latin-1').splitlines()
    out = {}
    for line in b[1:]:
        c = line.split(';')
        try:
            dd, mm, yy = c[0].split('.')
            v = float(c[2])
        except (ValueError, IndexError):
            continue
        if v > 0:
            out[int(yy) * 10000 + int(mm) * 100 + int(dd)] = v
    return out


def fred_monthly_rate(sid):
    c = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=30).decode()
    out = {}
    for line in c.strip().splitlines()[1:]:
        d, v = line.split(',')
        if v in ('', '.'):
            continue
        out[int(d[:4]) * 100 + int(d[5:7])] = float(v) / 100 / 12
    return out


def f_family(vrp, r, c, start=None, spread=SPREAD):
    """F1〜F4 の持ち高と成績。start が None なら4本がそろう最初の月"""
    ex = {k: r[k] - c[k] for k in r if k in c}
    var = trailing_var(ex)
    f1, i1 = fc_regress(vrp, ex, 1)
    f2, i2 = fc_regress(vrp, ex, 3)
    Ws = {'F1': weights_from(f1, var), 'F2': weights_from(f2, var), 'F3': fc_median(vrp, 0.5, 1.0), 'F4': fc_median(vrp, 1.0, 1.5)}
    if start is None:
        start = max(min(m for m in W if m in r and m in c) for W in Ws.values())
    out = {}
    for k, W in Ws.items():
        g, n, TO = run_w(W, r, c, spread=spread, start=start)
        out[k] = (g, n, TO, {m: W[m] for m in g})
    return out, {'F1': (f1, i1), 'F2': (f2, i2)}, start, ex


def oos_r2(fc, info, ex, h, a=None, z=None):
    """CT 型の標本外 R²: 1 − Σ(y − f)² ÷ Σ(y − 標本の平均)²。y は h か月平均（t+1 から）"""
    num = den = 0.0
    n = 0
    for m in sorted(fc):
        if (a is not None and m < a) or (z is not None and m > z):
            continue
        fut = [ex.get(madd(m, j)) for j in range(h)]
        if None in fut:
            continue
        y = sum(fut) / h
        num += (y - fc[m]) ** 2
        den += (y - info[m]['pm']) ** 2
        n += 1
    return {'n': n, 'r2_pct': round((1 - num / den) * 100, 2) if den > 0 else None}


def wstats(W, TO):
    v = list(W.values())
    return {'mean_w': round(S.mean(v), 3), 'share_at_0': round(sum(1 for x in v if x <= 1e-9) / len(v), 3),
            'share_at_cap': round(sum(1 for x in v if x >= WMAX - 1e-9) / len(v), 3),
            'mean_w_train': round(S.mean([W[m] for m in W if m <= TE]), 3) if any(m <= TE for m in W) else None,
            'mean_w_hold': round(S.mean([W[m] for m in W if m >= HS]), 3) if any(m >= HS for m in W) else None,
            'turnover_per_year': round(S.mean(TO.values()) * 12, 3)}


def btz_check(vrp, ex):
    """BTZ の照合（標本内・1990-01〜2007-12）"""
    out = {}
    for h in (1, 3):
        xs, ys = [], []
        for t in sorted(vrp):
            if not (199001 <= t <= 200712):
                continue
            fut = [ex.get(madd(t, j)) for j in range(1, h + 1)]
            if None in fut:
                continue
            xs.append(vrp[t]); ys.append(sum(fut) / h)
        a, b = ols(xs, ys)
        res = [y - a - b * x for x, y in zip(xs, ys)]
        mx = S.mean(xs)
        u = [(x - mx) * e for x, e in zip(xs, res)]
        sxx = sum((x - mx) ** 2 for x in xs)
        # NW（ラグ h+2）の傾きの標準誤差
        L = h + 2
        g0 = sum(v * v for v in u)
        for j in range(1, L + 1):
            g0 += 2 * (1 - j / (L + 1)) * sum(u[i] * u[i - j] for i in range(j, len(u)))
        se = math.sqrt(g0) / sxx
        r2 = 1 - sum(e * e for e in res) / sum((y - S.mean(ys)) ** 2 for y in ys)
        out[f'h{h}'] = {'n': len(xs), 'slope': round(b, 3), 'nw_t': round(b / se, 2), 'r2_pct': round(r2 * 100, 2)}
    return out


def part2(D, res, add_fn, log_fn):
    """第2部の戦略を res に足し、報告の辞書を返す"""
    rf, sp, mkt = D['rf'], D['sp'], D['mkt']
    rep = {'prereg2': PRE2, 'prereg2_commit': git_sha(os.path.join('out', PRE2))}
    spx, vix = cboe_daily('SPX'), cboe_daily('VIX')
    vrp = vrp_series(vix, spx)
    vk = sorted(vrp)
    rep['vrp_summary'] = {'from': vk[0], 'to': vk[-1], 'months': len(vk), 'mean_pct2_m': round(S.mean(vrp.values()) * 1e4, 3),
                          'sd_pct2_m': round(S.stdev(vrp.values()) * 1e4, 3), 'share_negative': round(sum(1 for v in vrp.values() if v < 0) / len(vk), 3),
                          'min': [min(vrp, key=vrp.get), round(min(vrp.values()) * 1e4, 2)], 'max': [max(vrp, key=vrp.get), round(max(vrp.values()) * 1e4, 2)],
                          'unit': '%²/月（VIX²/12 と同じ単位）', 'gaps': not consecutive(vk)}
    exu = {k: sp[k] - rf[k] for k in sp if k in rf}
    rep['btz_check_in_sample_1990_2007'] = btz_check(vrp, exu)
    # F 族（米国）
    F, fcs, st, ex = f_family(vrp, sp, rf, start=F_START)
    rep['F_start'] = st
    names = {'F1': 'F1-BTZ1m', 'F2': 'F2-BTZ3m', 'F3': 'F3-med0.5/1', 'F4': 'F4-med1/1.5'}
    desc = {'F1': 'BTZ 1か月先の回帰＋CT・w∈[0,1.5]', 'F2': 'BTZ 3か月先の回帰＋CT・w∈[0,1.5]', 'F3': 'VRP ≥ 中央値なら1・下なら0.5',
            'F4': 'VRP ≥ 中央値なら1.5・下なら1'}
    rep['F_weights'] = {}
    for k, (g, n, TO, W) in F.items():
        e = add_fn(names[k], 'F', g, n, None, sp, 'VRP', RS, desc[k])
        e['weights'] = wstats(W, TO)
        rep['F_weights'][names[k]] = e['weights']
        rep.setdefault('F_w_series', {})[names[k]] = {str(m): round(W[m], 3) for m in sorted(W)}
    for k, h in [('F1', 1), ('F2', 3)]:
        fc, info = fcs[k]
        fcs_st = {m: v for m, v in fc.items() if m >= st}
        rep.setdefault('oos_r2', {})[names[k]] = {'train': oos_r2(fcs_st, info, ex, h, z=TE), 'hold': oos_r2(fcs_st, info, ex, h, a=HS),
                                                  'share_slope_negative': round(sum(1 for m in fcs_st if info[m]['b'] <= 0) / len(fcs_st), 3)}
    # 頑健性: 借入 +1.5%
    Fb, _, _, _ = f_family(vrp, sp, rf, start=F_START, spread=0.015)
    g, n, TO, W = Fb['F1']
    add_fn('F1-BTZ1m(借入+1.5%)', 'robust2', g, n, None, sp, 'VRP', RS, '借入 RF+1.5%')
    # G 族
    med = fc_median(vrp, False, True)
    cfg = [('G1-PUTh', 'PUT', 'excess', None), ('G2-BXMh', 'BXM', 'vs_sp', None), ('G3-BXMDh', 'BXMD', 'vs_sp', None),
           ('G4-CNDRh', 'CNDR', 'excess', None), ('G5-PUTh|VRP高', 'PUT', 'excess', med)]
    rep['G_parts'] = {}
    Gser = {}
    for nm, x, kind, cond in cfg:
        g, n, B, parts = hedged_overlay(D[x], sp, rf, COST[x], kind, cond=cond, start=F_START if cond is not None else None)
        e = add_fn(nm, 'G', g, n, None, sp, x, PP_G.get(x, RS), 'β で株の向きを消した保険料を S&P500 に1倍重ねる' + ('（VRP が中央値以上の月だけ）' if cond else ''))
        bv = [b for b in B.values() if b is not None]
        rep['G_parts'][nm] = {'beta_mean': round(S.mean(bv), 3), 'Y_ann_pct': round(S.mean(parts['Y']) * 1200, 2),
                              'betaE_ann_pct': round(S.mean(parts['bE']) * 1200, 2), 'months_on': len(bv), 'months': len(B)}
        Gser[nm] = (g, n)
    # French Mkt を相手に（頑健性）
    for k, (g, n, TO, W) in F.items():
        add_fn(names[k] + '[vs French Mkt]', 'robust2_frenchmkt', g, n, None, mkt, 'VRP', RS, '作り方は S&P500・相手だけ French Mkt')
    for nm, (g, n) in Gser.items():
        add_fn(nm + '[vs French Mkt]', 'robust2_frenchmkt', g, n, None, mkt, nm, RS, '作り方は S&P500・相手だけ French Mkt')
    # C5: 米国外
    regions = {}
    specs = [('欧州(ドイツ)', lambda: stoxx_levels('V1X'), lambda: yahoo_levels('^GDAXI'), lambda: fred_monthly_rate('IR3TIB01DEM156N'), True),
             ('インド', lambda: yahoo_levels('^INDIAVIX'), lambda: yahoo_levels('^NSEI'), lambda: fred_monthly_rate('IRSTCI01INM156N'), True),
             ('オーストラリア', lambda: yahoo_levels('^AXVI'), lambda: yahoo_levels('^AXJO'), lambda: fred_monthly_rate('IR3TIB01AUM156N'), True),
             ('ブラジル(EWZ)', lambda: fred_daily('VXEWZCLS'), lambda: yahoo_levels('EWZ'), lambda: dict(rf), True),
             ('ユーロ圏(報告のみ)', lambda: stoxx_levels('V2TX'), lambda: yahoo_levels('^STOXX50E'), lambda: fred_monthly_rate('IR3TIB01DEM156N'), False)]
    for reg, fv, fp, fr, counts in specs:
        try:
            vol, px, lr = fv(), fp(), fr()
        except Exception as ex_:  # noqa
            regions[reg] = {'status': f'取れず: {str(ex_)[:100]}', 'counts_for_C5': counts}
            log_fn('C5 取れず', reg, ex_)
            continue
        v2 = vrp_series(vol, px)
        r2 = monthly_from_levels(px)
        if len(v2) < BURN + 24:
            regions[reg] = {'status': f'VRP が {len(v2)} か月しかない', 'counts_for_C5': counts}
            continue
        FF, _, st2, _ = f_family(v2, r2, lr)
        rr = {'vrp_from': min(v2), 'vrp_to': max(v2), 'vrp_months': len(v2), 'start': st2, 'counts_for_C5': counts,
              'vrp_mean_pct2_m': round(S.mean(v2.values()) * 1e4, 3), 'vrp_share_negative': round(sum(1 for v in v2.values() if v < 0) / len(v2), 3)}
        for k, (g, n, TO, W) in FF.items():
            s_, b_ = same(g, r2)
            n_ = {m: n[m] for m in s_}
            lr_ = {m: lr[m] for m in s_ if m in lr}
            rr[names[k]] = {'gross': M.excess_stats(s_, b_), 'net': M.excess_stats(n_, b_), 'sharpe': (M.sharpe(s_, lr_), M.sharpe(b_, lr_)),
                            'weights': wstats(W, TO), 'maxdd': (round(M.maxdd(s_) * 100, 1), round(M.maxdd(b_) * 100, 1))}
        regions[reg] = rr
    rep['C5_regions'] = regions
    repl = {}
    for k in names.values():
        cnt = [r_ for r_, v in regions.items() if v.get('counts_for_C5') and k in v and v[k]['gross']]
        pos = [r_ for r_ in cnt if regions[r_][k]['gross']['ex_ann'] > 0]
        repl[k] = {'regions': len(cnt), 'positive': len(pos), 'positive_list': pos}
    rep['C5_repl'] = repl
    return rep


PP_G = {'PUT': 200801, 'BXM': 200301}


def post_hoc(D):
    """事後（判定に使わない）: O-RXM の β と α。RXM は名前どおりのリスク・リバーサル（デルタ約0.5）と判断した根拠"""
    rf, sp, mkt = D['rf'], D['sp'], D['mkt']
    out = {'label': '事後（第1部の結果を見た後・判定に使わない）'}
    x = D['RXM']
    ks = sorted(k for k in x if k in sp and k in rf)
    xs, ss = [x[k] - rf[k] for k in ks], [sp[k] - rf[k] for k in ks]
    b = slope(ss, xs)
    up = [(k, round(x[k] * 100, 1), round(sp[k] * 100, 1)) for k in ks if sp[k] > 0.08]
    out['RXM_index'] = {'beta_vs_sp': round(b, 3), 'corr': round(M.corr(xs, ss), 3), 'months_sp_up_8pct': up,
                        'note': 'CBOE の説明文は『25デルタのストラングルを売り5デルタを買う』だが、名前は Risk Reversal で、S&P500 の大きな上げの月に大きく上がる（ストラングルの売りなら上値は保険料で頭打ち）＝ 25デルタのコールを買いプットを売るリスク・リバーサルと判断'}
    s, n, L = overlay(x, sp, rf, COST['RXM'])
    for bn, bb in [('sp500tr', sp), ('french_mkt', mkt)]:
        s2, b2 = same(s, bb)
        o = {}
        for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]:
            kk = [k for k in sorted(s2) if (a is None or k >= a) and (z is None or k <= z)]
            xs = [s2[k] - rf[k] for k in kk]; ys = [b2[k] - rf[k] for k in kk]
            be = slope(ys, xs)
            al = [p - be * q for p, q in zip(xs, ys)]
            sh = lambda v: S.mean(v) / S.stdev(v) * math.sqrt(12)
            o[lab] = {'beta': round(be, 3), 'alpha_ann_pct': round(S.mean(al) * 1200, 2), 'alpha_nw_t': round(M.nw_t(al), 2),
                      'sharpe_unrounded': [round(sh(xs), 4), round(sh(ys), 4)]}
        out[f'O-RXM_vs_{bn}'] = o
    return out


# ───────────────────────── 第3部（prereg3・報告のみ・事後の点検） ─────────────────────────
PRE3 = 'mw_options_vrp_prereg3.json'


def alpha_beta(s, b, rf, a=None, z=None):
    ks = [k for k in sorted(s) if k in b and k in rf and (a is None or k >= a) and (z is None or k <= z)]
    xs = [s[k] - rf[k] for k in ks]; ys = [b[k] - rf[k] for k in ks]
    be = slope(ys, xs)
    al = [x - be * y for x, y in zip(xs, ys)]
    return {'from': ks[0], 'to': ks[-1], 'beta': round(be, 3), 'alpha_ann_pct': round(S.mean(al) * 1200, 2), 'alpha_nw_t': round(M.nw_t(al), 2)}


def part3(D, res, add_fn, log_fn):
    rf, sp = D['rf'], D['sp']
    rep = {'prereg3': PRE3, 'prereg3_commit': git_sha(os.path.join('out', PRE3)), 'label': '報告のみ・事後（格付けしない）'}
    names = {'F1': 'F1-BTZ1m', 'F2': 'F2-BTZ3m', 'F3': 'F3-med0.5/1', 'F4': 'F4-med1/1.5'}
    # R: 米国の別の指数
    R = {}
    for lab, vid, etf in [('ダウ(DIA)', 'VXDCLS', 'DIA'), ('ナスダック100(QQQ)', 'VXNCLS', 'QQQ'), ('ラッセル2000(IWM)', 'RVXCLS', 'IWM'),
                          ('新興国(EEM)', 'VXEEMCLS', 'EEM')]:
        try:
            vol, px = fred_daily(vid), yahoo_levels(etf)
        except Exception as ex_:  # noqa
            R[lab] = {'status': f'取れず: {str(ex_)[:100]}'}
            continue
        v2 = vrp_series(vol, px)
        r2 = monthly_from_levels(px)
        FF, _, st2, _ = f_family(v2, r2, rf)
        rr = {'vrp_from': min(v2), 'vrp_months': len(v2), 'start': st2}
        for k, (g, n, TO, W) in FF.items():
            e = add_fn(f'{names[k]}[{etf}]', 'report3', g, n, None, r2, etf, RS, f'第2部の規則を {lab} に当てる（報告のみ）')
            rr[names[k]] = {'hold_or_all': e.get('full'), 'net': e.get('cost_full'), 'sharpe_full': e.get('sharpe', {}).get('full'),
                            'weights': wstats(W, TO), 'maxdd': e.get('maxdd', {}).get('full')}
        R[lab] = rr
    rep['R_other_us_indices'] = R
    # P1〜P4
    spx, vix = cboe_daily('SPX'), cboe_daily('VIX')
    vrp = vrp_series(vix, spx)
    F, _, st, _ = f_family(vrp, sp, rf, start=F_START)
    P = {}
    for k, lev in [('F4', 1.25), ('F3', 0.75)]:
        g, n, TO, W = F[k]
        Wst = {m: lev for m in W}
        gs, ns, _ = run_w(Wst, sp, rf, start=st)
        e = add_fn(f'static{lev}x', 'posthoc3', gs, ns, None, sp, 'SPXTR', RS, f'いつも {lev} 倍（事後の比較用）')
        P[f'P1_{names[k]}_minus_static{lev}'] = {lab: M.excess_stats(g, gs, a=a, z=z) for lab, a, z in [('train', None, TE), ('hold', HS, None), ('full', None, None)]}
        P[f'P1_{names[k]}_minus_static{lev}_net'] = {lab: M.excess_stats(n, ns, a=a, z=z) for lab, a, z in [('train', None, TE), ('hold', HS, None), ('full', None, None)]}
        P[f'P1_static{lev}_vs_sp'] = {'train': (e.get('train') or {}), 'hold': (e.get('hold') or {}), 'sharpe': e.get('sharpe')}
    P['P2_alpha'] = {names[k]: {lab: alpha_beta(F[k][0], sp, rf, a, z) for lab, a, z in [('train', None, TE), ('hold', HS, None), ('full', None, None)]}
                     for k in F}
    # P3: VXO で 1990 年より前へ延ばす
    try:
        vxo = fred_daily('VXOCLS')
        v_old = {m: v for m, v in vrp_series(vxo, spx).items() if 198601 <= m <= 198912}
        vx = dict(v_old); vx.update(vrp)
        W4 = fc_median(vx, 1.0, 1.5)
        g, n, TO = run_w(W4, sp, rf, start=199101)
        e = add_fn('F4-med1/1.5(VXO で1991〜・事後)', 'posthoc3', g, n, None, sp, 'VRP', RS, 'VXO で 1986〜1989 の VRP をつないだ F4（事後）')
        P['P3_vxo_extension'] = {'vxo_months': len(v_old), 'vxo_vrp_mean_pct2_m': round(S.mean(v_old.values()) * 1e4, 3), 'start': min(g),
                                 'train': e.get('train'), 'hold': e.get('hold'), 'full': e.get('full'), 'sharpe': e.get('sharpe'),
                                 'train_1991_1995_only': M.excess_stats(g, same(sp, g)[0], a=199101, z=199503),
                                 'weights': wstats({m: W4[m] for m in g}, TO)}
    except Exception as ex_:  # noqa
        P['P3_vxo_extension'] = {'status': f'取れず: {str(ex_)[:100]}'}
    W = F['F4'][3]
    P['P4_episodes_F4_w'] = {lab: {str(m): W.get(m) for m in sorted(W) if a <= m <= z} for lab, a, z in
                             [('2008', 200801, 200812), ('2009H1', 200901, 200906), ('2020', 202001, 202012), ('2022', 202201, 202212)]}
    rep['P'] = P
    return rep


# ───────────────────────── 本体 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', path], cwd=M.BASE).decode().strip() or None
    except Exception:  # noqa
        return None


def sanity(D):
    out = {}
    m = M.ff_factors()['mkt']
    out['french_mkt_cagr_1926'] = round(M.cagr(m) * 100, 2)
    out['french_mkt_cagr_2007'] = round(M.cagr(M.window(m, HS)) * 100, 2)
    c, y = D['_sp_constructed'], D['_sp_yahoo']
    ks = sorted(set(c) & set(y))
    d = [c[k] - y[k] for k in ks]
    out['sp_constructed_vs_yahoo'] = {'from': ks[0], 'to': ks[-1], 'mean_pct_m': round(S.mean(d) * 100, 4), 'sd_pct_m': round(S.stdev(d) * 100, 3)}
    ks = sorted(set(D['sp']) & set(D['mkt']))
    d = [D['sp'][k] - D['mkt'][k] for k in ks]
    out['sp_vs_french_mkt'] = {'from': ks[0], 'to': ks[-1], 'mean_pct_m': round(S.mean(d) * 100, 4), 'sd_pct_m': round(S.stdev(d) * 100, 3),
                               'cagr_sp': round(M.cagr(same(D['sp'], D['mkt'])[0]) * 100, 2), 'cagr_mkt': round(M.cagr(same(D['mkt'], D['sp'])[0]) * 100, 2)}
    pu, py, pc = D['_put_parts']
    for nm, a, b in [('put_cad_vs_yahoo', pc, py), ('put_cad_vs_cboe_usd', pc, pu), ('put_yahoo_vs_cboe_usd', py, pu)]:
        ks = sorted(set(a) & set(b))
        d = [a[k] - b[k] for k in ks]
        out[nm] = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'mean_pct_m': round(S.mean(d) * 100, 4), 'sd_pct_m': round(S.stdev(d) * 100, 3),
                   'max_abs_pct': round(max(map(abs, d)) * 100, 3)}
    bu, bc = D['_bxm_parts']
    ks = sorted(set(bu) & set(bc))
    d = [bu[k] - bc[k] for k in ks]
    out['bxm_cad_vs_cboe_usd'] = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'mean_pct_m': round(S.mean(d) * 100, 4), 'sd_pct_m': round(S.stdev(d) * 100, 3)}
    alt = {k: 2 * D['BXMH'][k] - D['sp'][k] for k in D['BXMH'] if k in D['sp']}
    for nm, lo, hi, ref in [('bxm_2bxmh_vs_cad', 199002, 200203, bc), ('bxm_2bxmh_vs_usd', 200204, END, bu)]:
        ks = sorted(k for k in set(alt) & set(ref) if lo <= k <= hi)
        d = [alt[k] - ref[k] for k in ks]
        out[nm] = {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'mean_pct_m': round(S.mean(d) * 100, 4), 'sd_pct_m': round(S.stdev(d) * 100, 3)}
    out['break_scan'] = break_scan()
    out['breaks_set_missing'] = BREAKS
    out['sources'] = D['_src']
    out['fx_days'] = D['_fx_n']
    return out


def main():
    data_only = '--data-only' in sys.argv
    pre = json.load(open(os.path.join(M.BASE, 'out', PRE)))
    D = load_all()
    san = sanity(D)
    log('照合', json.dumps(san, ensure_ascii=False)[:3000])
    if data_only:
        return
    rf, sp, mkt = D['rf'], D['sp'], D['mkt']
    res = collections.OrderedDict()

    def add(name, fam, s, net, L, bench, underlying, postpub=None, desc=''):
        e = evaluate(name, s, net, bench, rf, L, meta={'family': fam, 'underlying': underlying, 'desc': desc}, postpub=postpub)
        res[name] = e
        return e
    PP = {'BXM': 200301, 'PUT': 200801}
    # A: 公平な版
    for x in ['PUT', 'BXM', 'BXMD', 'BXY', 'PUTY', 'CMBO']:
        s, n, L = levered(D[x], sp, rf, COST[x])
        add(f'L-{x}', 'A', s, n, L, sp, x, PP.get(x, RS), 'ぶれ合わせ（36か月・上限2倍）')
    for y in ['CNDR', 'BFLY', 'RXM']:
        s, n, L = overlay(D[y], sp, rf, COST[y])
        add(f'O-{y}', 'A', s, n, L, sp, y, RS, 'S&P500 ＋ 1倍重ね')
    # B: 指数そのもの
    for x in ['PUT', 'BXM', 'BXMD', 'BXY', 'PUTY', 'CMBO', 'BXMC', 'BXMH', 'CNDR', 'BFLY', 'RXM']:
        s, n, L = unlevered(D[x], rf, COST[x])
        add(f'U-{x}', 'B', s, n, L, sp, x, PP.get(x, RS), '指数そのもの')
    # C: 負の対照
    for x in ['PPUT', 'CLLZ']:
        s, n, L = unlevered(D[x], rf, COST[x])
        add(f'U-{x}', 'C', s, n, L, sp, x, RS, '負の対照（保険を買う側）')
    # 報告のみ（訓練なし）
    for x in ['CLL', 'WPUT', 'BXMW', 'VXTH', 'VPD']:
        s, n, L = unlevered(D[x], rf, COST[x])
        add(f'U-{x}', 'report_no_train', s, n, L, sp, x, RS, '訓練期間なし＝構造的にC')
    s, n, L = levered(D['WPUT'], sp, rf, COST['WPUT'])
    add('L-WPUT', 'report_no_train', s, n, L, sp, 'WPUT', RS, '訓練期間なし＝構造的にC')
    s, n, L = overlay(D['VPD'], sp, rf, COST['VPD'])
    add('O-VPD', 'report_no_train', s, n, L, sp, 'VPD', RS, '訓練期間なし＝構造的にC')
    # E: 探索
    for x in ['PUTVM', 'BXMVM']:
        s, n, L = unlevered(D[x], rf, COST[x])
        add(f'U-{x}', 'E', s, n, L, sp, x, RS, '探索（設計に後知恵の疑い）')
        s, n, L = levered(D[x], sp, rf, COST[x])
        add(f'L-{x}', 'E', s, n, L, sp, x, RS, '探索（設計に後知恵の疑い）')
    # 頑健性
    for x in ['PUT', 'BXM']:
        for w in (12, 60):
            s, n, L = levered(D[x], sp, rf, COST[x], win=w)
            add(f'L-{x}(w{w})', 'robust', s, n, L, sp, x, PP.get(x), f'窓 {w} か月')
        s, n, L = levered(D[x], sp, rf, COST[x], cap=1.5)
        add(f'L-{x}(cap1.5)', 'robust', s, n, L, sp, x, PP.get(x), '上限1.5倍')
    s, n, L = unlevered(D['BXM_alt'], rf, COST['BXM_alt'])
    add('U-BXM(alt)', 'robust', s, n, L, sp, 'BXM_alt', PP['BXM'], '1990-02〜2002-03 を 2×BXMH−SPXTR')
    s, n, L = levered(D['BXM_alt'], sp, rf, COST['BXM_alt'])
    add('L-BXM(alt)', 'robust', s, n, L, sp, 'BXM_alt', PP['BXM'], '1990-02〜2002-03 を 2×BXMH−SPXTR')
    # A を French Mkt 相手に
    for x in ['PUT', 'BXM', 'BXMD', 'BXY', 'PUTY', 'CMBO']:
        s, n, L = levered(D[x], sp, rf, COST[x])
        add(f'L-{x}[vs French Mkt]', 'robust_frenchmkt', s, n, L, mkt, x, PP.get(x, RS), 'ぶれ合わせは S&P500 のまま・相手だけ French Mkt')
    for y in ['CNDR', 'BFLY', 'RXM']:
        s, n, L = overlay(D[y], sp, rf, COST[y])
        add(f'O-{y}[vs French Mkt]', 'robust_frenchmkt', s, n, L, mkt, y, RS, 'S&P500 ＋ 1倍重ね・相手だけ French Mkt')
    # 別の米国の原資産（報告のみ）
    under = {'BXD': 'DIA', 'BXR': 'IWM', 'PUTR': 'IWM', 'BXN': 'QQQ'}
    for x, etf in under.items():
        u = cap_end(M.yahoo(etf))
        s, n, L = unlevered(D[x], rf, COST[x])
        add(f'U-{x}[vs {etf}]', 'other_underlying', s, n, L, u, x, RS, f'相手は {etf}（調整後終値）')
        s, n, L = levered(D[x], u, rf, COST[x])
        add(f'L-{x}[vs {etf}]', 'other_underlying', s, n, L, u, x, RS, f'{etf} のぶれにそろえる')

    # Holm
    famA = [k for k, e in res.items() if e['family'] in ('A', 'B', 'C')]
    hp = M.holm({k: (res[k].get('hold') or {}).get('p') for k in famA})
    famE = [k for k, e in res.items() if e['family'] == 'E']
    hpE = M.holm({k: (res[k].get('hold') or {}).get('p') for k in famE})
    for k, e in res.items():
        hk = hp.get(k) if e['family'] in ('A', 'B', 'C') else hpE.get(k) if e['family'] == 'E' else None
        finish(e, hk)
    log('判定', ' '.join(f"{k}:{e['grade']}" for k, e in res.items()))

    # 第2部（prereg2 がコミットされているときだけ測る）
    rep2 = None
    if git_sha(os.path.join('out', PRE2)):
        n1 = set(res)
        rep2 = part2(D, res, add, log)
        new = [k for k in res if k not in n1]
        famAll = [k for k, e in res.items() if e['family'] in ('A', 'B', 'C', 'E', 'F', 'G')]
        hpAll = M.holm({k: (res[k].get('hold') or {}).get('p') for k in famAll})
        famFG = [k for k in new if res[k]['family'] in ('F', 'G')]
        hpFG = M.holm({k: (res[k].get('hold') or {}).get('p') for k in famFG})
        rep2['holm'] = {'angle_wide_n': len(famAll), 'part2_only_n': len(famFG),
                      'part2_only': {k: hpFG.get(k) for k in famFG}, 'angle_wide': {k: hpAll.get(k) for k in famFG}}
        for k in new:
            e = res[k]
            base = k.split('[')[0].split('(')[0]
            rp = rep2['C5_repl'].get(base) if e['family'] in ('F',) else None
            finish(e, hpAll.get(k) if e['family'] in ('F', 'G') else None, repl=rp)
            if e['family'] in ('F', 'G'):
                e['family_holm_p_part2_only'] = hpFG.get(k)
        log('第2部の判定', ' '.join(f"{k}:{res[k]['grade']}" for k in new))
        if git_sha(os.path.join('out', PRE3)):
            n2 = set(res)
            rep3 = part3(D, res, add, log)
            for k in [k for k in res if k not in n2]:
                finish(res[k], None)
                res[k]['grade_label'] = res[k]['grade']
                res[k]['grade'] = '報告のみ'
            rep2['part3'] = rep3
            log('第3部（報告のみ）', len([k for k in res if k not in n2]), '本')
    else:
        log('第2部: prereg2 がコミットされていないので測らない')

    # 既知の数字の照合
    known = {}
    for nm, x, a, z in [('Whaley2002_BXM_1988-07..2001-12', 'BXM', 198807, 200112), ('Bondarenko2019_PUT_1988-07..2018-12', 'PUT', 198807, 201812)]:
        s = M.window(D[x], a, z); b = M.window(sp, a, z)
        s, b = same(s, b)
        known[nm] = {'cagr': round(M.cagr(s) * 100, 2), 'vol': round(S.stdev(s.values()) * math.sqrt(12) * 100, 2),
                     'sp_cagr': round(M.cagr(b) * 100, 2), 'sp_vol': round(S.stdev(b.values()) * math.sqrt(12) * 100, 2), 'months': len(s)}
    known['literature_from_memory'] = {'Whaley2002': 'BXM は S&P500 とほぼ同じリターン・ぶれ約3分の2（1988-06〜2001-12）',
                                       'Bondarenko2019': 'PUT 年率 約9.5%・ぶれ 約10% vs S&P500 約9.8%・約15%（1986-06〜2018-12）'}

    # 実在の器
    vehicles = {'GATEX': ['BXM', 'CLL'], 'ETB': ['BXM'], 'ETV': ['BXM'], 'PBP': ['BXM'], 'XYLD': ['BXM'], 'QYLD': ['BXN'], 'JEPI': ['BXM', 'PUT'],
                'JEPQ': ['BXN'], 'SPYI': ['BXM'], 'XRMI': ['CLL'], 'BUYW': ['BXMW'], 'FTHI': ['BXM'], 'DIVO': ['BXM'], 'JHEQX': ['CLL'], 'SWAN': ['PPUT']}
    real = {}
    spy_raw = None
    try:
        M.yahoo('SPY')
        spy_raw = yahoo_raw('SPY')
    except Exception as ex:  # noqa
        log('SPY 失敗', ex)
    for t, refs in vehicles.items():
        try:
            r = cap_end(M.yahoo(t))
        except Exception as ex:  # noqa
            real[t] = {'status': f'取れず: {str(ex)[:80]}'}
            continue
        e = {'from': min(r), 'to': max(r), 'months': len(r)}
        s, b = same(r, sp)
        e['vs_sp500tr'] = M.excess_stats(s, b)
        e['vs_sp500tr_hold_or_all'] = e['vs_sp500tr']
        rfx = {k: rf[k] for k in s if k in rf}
        e['sharpe'] = (M.sharpe(s, rfx), M.sharpe(b, rfx))
        e['maxdd'] = (round(M.maxdd(s) * 100, 1), round(M.maxdd(b) * 100, 1))
        e['episodes'] = {k: (comp(s, a, z), comp(b, a, z)) for k, (a, z) in EPIS.items()}
        e['vs_paper'] = {}
        for ref in refs:
            p = D.get(ref)
            if p:
                s2, p2 = same(r, p)
                e['vs_paper'][ref] = M.excess_stats(s2, p2)
        raw = yahoo_raw(t)
        if raw:
            e['name'] = raw['name']
            ys = raw['yield_m']
            yy = collections.defaultdict(float)
            for k, v in ys.items():
                yy[k // 100] += v
            e['dist_yield_by_year'] = {y: round(v * 100, 2) for y, v in sorted(yy.items()) if y * 100 + 12 <= END}
            if spy_raw:
                yb = spy_raw['yield_m']
                e['jp_tax'] = {
                    'taxable_no_credit(US10%+JP20.315%)': jp_after_tax(r, ys, sp, yb, 1 - 0.9 * (1 - 0.20315)),
                    'taxable_full_credit(20.315%)': jp_after_tax(r, ys, sp, yb, 0.20315),
                    'nisa(US10%のみ)': jp_after_tax(r, ys, sp, yb, 0.10, taxable=False),
                    'no_tax': jp_after_tax(r, ys, sp, yb, 0.0, bench_wht=0.0, taxable=False)}
        real[t] = e
    for t, why in [('PUTW', 'Yahoo: No data found, symbol may be delisted（WisdomTree の PUT 連動 ETF・上場廃止）'),
                   ('BXMX', 'Yahoo: No data found'), ('HSPX', 'Yahoo: No data found（Global X S&P500 Covered Call の旧記号）')]:
        real[t] = {'status': why}

    # 出力
    tested = []
    for k, e in res.items():
        tested.append({'name': k, 'family': e['family'], 'grade': e['grade'], 'from': e.get('from'), 'to': e.get('to'),
                       'hold_ex': (e.get('hold') or {}).get('ex_ann'), 'hold_t': (e.get('hold') or {}).get('t'),
                       'hold_cagr_diff': (e.get('hold') or {}).get('cagr_diff'), 'train_ex': (e.get('train') or {}).get('ex_ann'),
                       'train_t': (e.get('train') or {}).get('t'), 'net_cost_hold_ex': (e.get('cost_hold') or {}).get('ex_ann'),
                       'sharpe_train': e.get('sharpe', {}).get('train'), 'sharpe_hold': e.get('sharpe', {}).get('hold'),
                       'roll20_win': (e.get('roll20') or {}).get('win_rate'), 'family_holm_p': e.get('family_holm_p')})
    obj = {'angle': ANGLE, 'prereg': PRE, 'prereg_commit': git_sha(os.path.join('out', PRE)),
           'prereg2': PRE2, 'prereg2_commit': git_sha(os.path.join('out', PRE2)),
           'question': pre['question'], 'end': END, 'sanity': san, 'known_numbers': known,
           'n_tested': len(res), 'n_holm_family_ABC': len(famA), 'n_holm_family_E': len(famE),
           'tested': tested, 'strategies': res, 'real_vehicles': real, 'part2': rep2, 'post_hoc_notes': post_hoc(D),
           'runtime_sec': round(time.time() - t0, 1), 'log_tail': LOG[-40:]}
    p = M.save(OUT, obj)
    log('書いた', p, round(os.path.getsize(p) / 1e6, 2), 'MB')


if __name__ == '__main__':
    main()
