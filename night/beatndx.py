#!/usr/bin/env python3
"""night/beatndx.py — NASDAQ100 を超えるポートフォリオの作り方を、二つの時代で総当たりする（bx・読むだけ）

2026-10-12 ユーザー「いろいろな方法を駆使してNASDAQを超えるポートフォリオを作ってみて。」
事前登録: out/beatndx_prereg.json（作り方13本・二つの時代・合格の線を、結果を見る前に固定）。
門・採点・配分（portfolio.json）・CCF15 の規則には触れない。判定に使わない。

  python3 night/beatndx.py        → out/beatndx.json（作り方ごとの20年積立の比・一括の年率・判定・提案）
  python3 night/beatndx.py data   → データの検算だけ（合成と ^NDX・QQQ／借入の費用の仮定と QLD）を表示

約束（事前登録の implementation と同じ）
- 日次で組み、月次にまとめる。月の中の倍率は毎日戻す（レバレッジ型の商品と同じ形）。
- 1倍を超える分は 短期金利＋年1.5% を払い、1倍より下の分は短期金利を受け取る。
- 月の初めに持ち方を変えた量（危険資産ごとの重みの変化の絶対値の合計・元手に対する割合）×0.1% を、
  その時点の元手から引く。新しく入れるお金の買付には掛けない（どの作り方も同じに買うので）。
  毎日の倍率の戻しには掛けない（年1.5% に含める）。
- 信号はその月の前の月末までの値だけで決める（先読みなし）。時代の始まりより前の値も使う（同じ一本の系列）。
- データ: A＝Ken French の日次（CRSP 由来）。B＝Yahoo の日次の配当込みの値（QQQ・SMH・SPY）。
  B の信号が QQQ の始まり（1999-03-11）より前を見るときは A と同じ合成でつなぐ。SMH の前（〜2000-06-05）は Chips。
キャッシュ: out/_mw_cache/・out/_gaps_cache/（repo に入れない）
"""
import csv, datetime, hashlib, io, json, math, os, statistics as S, subprocess, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as MW   # noqa: E402
import gaps_common as G  # noqa: E402

PRE = os.path.join(BASE, 'out', 'beatndx_prereg.json')
OUT = os.path.join(BASE, 'out', 'beatndx.json')

SPREAD = 0.015        # 1倍を超える分の上乗せ（年）
TRADE = 0.001         # 持ち方を変えた量 1 あたりの費用
DAYS = 252
TECH_W, MKT_W = 0.65, 0.35
ERA = {'A': (196507, 199912), 'B': (200001, 202609)}
DCA20 = {'A': (196507, 198001), 'B': (200001, 200610)}     # 20年積立の起点（毎月）
DCA10 = {'A': (196507, 199001), 'B': (200001, 201610)}     # 10年積立の起点（参考）
QQQ_FIRST, SMH_FIRST = 19990311, 20000606                 # Yahoo の最初のリターンの日
B_LAST_DAY = 20260930
LINES = {'median': 1.05, 'win_rate': 0.60, 'worst': 0.80}
METHODS = ['B0', 'L125', 'L150', 'LIFE', 'TR150', 'TR100', 'VT', 'S30', 'S50', 'DM', 'MK130', 'RP150', 'C1']
LABEL = {
    'B0': 'NASDAQ100 の持ち続け（相手）', 'L125': 'NASDAQ100 を毎日1.25倍', 'L150': 'NASDAQ100 を毎日1.5倍',
    'LIFE': '年齢に合わせた倍率（はじめ2倍→1倍）', 'TR150': '勢いで倍率（上1.5倍・下1倍）', 'TR100': '勢いで現金へ（上1倍・下現金）',
    'VT': 'ぶれで倍率（年20%÷前月のぶれ・0.5〜1.5倍）', 'S30': 'NASDAQ100 70%＋半導体30%', 'S50': 'NASDAQ100 50%＋半導体50%',
    'DM': '回す（NASDAQ100・半導体・米国株全体の12か月の勝者／現金）', 'MK130': '米国株全体を毎日1.3倍',
    'RP150': 'NASDAQ100 60%＋10年国債40%を毎日1.5倍', 'C1': 'TR150 を50%＋S30 を50%'}


# ───────────────────────── 小さな部品（check_beatndx.py が検査する） ─────────────────────────
def add_months(m, k):
    return G.add_months(m, k)


def month_range(a, b):
    return G.month_range(a, b)


def by_month(series):
    out = {}
    for d in sorted(series):
        out.setdefault(d // 100, []).append(d)
    return out


def latest_getter(series):
    """{日付: 値} → 関数 f(d)＝d 以前で最も新しい値（無ければ None）。前日のまま、を素直に書く"""
    ks = sorted(series)
    import bisect

    def f(d):
        i = bisect.bisect_right(ks, d)
        return series[ks[i - 1]] if i else None
    return f


def lev_day(r, L, f, spread=SPREAD):
    """L 倍（毎日戻す）。1倍を超える分は f＋spread/252 を払い、1倍より下の分は f を受け取る"""
    return L * r + (1 - L) * f - max(L - 1.0, 0.0) * spread / DAYS


def lev_month(series, days, L, rf, spread=SPREAD):
    g = 1.0
    for d in days:
        g *= 1 + lev_day(series[d], L, rf(d), spread)
    return g - 1


def compound(series, days):
    g = 1.0
    for d in days:
        g *= 1 + series[d]
    return g - 1


def bond_price(c, y, n=20):
    """利札 c（年・半年ごと）・満期10年（n=20回）の債券の、利回り y での値（額面1）"""
    if abs(y) < 1e-12:
        return 1 + c / 2 * n
    v = (1 + y / 2) ** -n
    return c / y * (1 - v) + v


def bond_daily(yld, dates):
    """前日の利回りを利札とする10年債の値の変化＋前日の利回り÷252。欠けた日は利回りが前日のまま"""
    get = latest_getter(yld)
    out, prev = {}, None
    for d in dates:
        y = get(d)
        if y is None:
            continue
        if prev is not None:
            out[d] = bond_price(prev, y) - 1 + prev / DAYS
        prev = y
    return out


def tech_daily(ind, w, dbm):
    """Hardw・Softw・Chips を前月末の時価総額で加重（月の中は値動きで重みが動く＝時価加重の指数と同じ）"""
    out = {}
    for m, ds in sorted(dbm.items()):
        V = {k: w[k][m] for k in ind if (w[k].get(m) or 0) > 0}
        if not V:
            continue
        for d in ds:
            num = den = 0.0
            for k in V:
                r = ind[k].get(d)
                if r is not None:
                    num += V[k] * r
                    den += V[k]
            if den <= 0:
                continue
            out[d] = num / den
            for k in V:
                r = ind[k].get(d)
                if r is not None:
                    V[k] *= 1 + r
    return out


def life_L(i, n):
    """積立の i か月目（0から）の倍率。n=240: i<60 は2倍・60≤i<180 は2→1倍へまっすぐ・180以上は1倍（n で縮める）"""
    a, b = n / 4, 3 * n / 4
    if i < a:
        return 2.0
    if i < b:
        return 2.0 - (i - a) / (b - a)
    return 1.0


def tr_signal(levels, m, k=10):
    """m の月の倍率を決める信号: 前の月末の水準が、前の月末までの直近 k か月末の平均より上か（True/False/None）"""
    ks = [add_months(m, -j) for j in range(1, k + 1)]
    if any(x not in levels for x in ks):
        return None
    return levels[ks[0]] > sum(levels[x] for x in ks) / k


def vt_L(prev_days_returns, target=0.20, lo=0.5, hi=1.5):
    if len(prev_days_returns) < 2:
        return None
    sd = S.stdev(prev_days_returns) * math.sqrt(DAYS)
    if sd <= 0:
        return hi
    return min(hi, max(lo, target / sd))


def dm_pick(r12, rf12):
    """r12: {名前: 12か月の上昇率}（並びの順で同点を決める）。最も高いものが rf12 より低ければ None（現金）"""
    best = None
    for k, v in r12.items():
        if best is None or v > r12[best]:
            best = k
    return None if best is None or r12[best] < rf12 else best


def drift_w(w, a, b):
    """月初に w : 1−w で持った2つが a・b 動いたあとの、1つ目の重み"""
    x, y = w * (1 + a), (1 - w) * (1 + b)
    return x / (x + y)


def dca_final(r, c, months):
    """毎月の初めに1を入れる。その前に、今ある元手から c[m]（持ち方を変えた費用の割合）を引く"""
    v = 0.0
    for m in months:
        v = v * (1 - c.get(m, 0.0)) + 1.0
        v *= 1 + r[m]
    return v


def irr_from_final(V, n):
    """毎月の初めに1を n 回入れて最後に V → 年率。V＝Σ_{k=1..n}(1+i)^k を二分法で解く"""
    def fv(i):   # (1+i)^n−1 は i が小さいと桁落ちするので expm1・log1p で
        return n if abs(i) < 1e-15 else (1 + i) * math.expm1(n * math.log1p(i)) / i
    lo, hi = -0.2, 0.2
    if (fv(lo) - V) * (fv(hi) - V) > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if (fv(lo) - V) * (fv(mid) - V) <= 0:
            hi = mid
        else:
            lo = mid
    return (1 + (lo + hi) / 2) ** 12 - 1


def lump_series(r, c, months):
    out = {}
    for i, m in enumerate(months):
        cm = c.get(m, 0.0) if i else 0.0
        out[m] = (1 - cm) * (1 + r[m]) - 1
    return out


# ───────────────────────── データ ─────────────────────────
def _yahoo_close(t):
    """Yahoo の日次の終値（^IRX の利回りの水準など）。mw_common.yahoo と同じキャッシュを読む"""
    import urllib.parse
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}&interval=1d&events=div%2Csplit'
    j = json.loads(MW.get(u, name=f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1d.json', max_age_days=3))
    r = j['chart']['result'][0]
    off = r.get('meta', {}).get('gmtoffset') or 0
    out = {}
    for ts, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
        if c is None:
            continue
        dt = datetime.datetime.utcfromtimestamp(ts + off)
        out[dt.year * 10000 + dt.month * 100 + dt.day] = c
    return out


def _dgs10_daily():
    raw = G._cached('fred_DGS10.csv', 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10').decode()
    out = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) < 2 or row[1] in ('.', ''):
            continue
        try:
            out[int(row[0][:4]) * 10000 + int(row[0][5:7]) * 100 + int(row[0][8:10])] = float(row[1]) / 100
        except ValueError:
            continue
    return out


def _french():
    ff = MW.ff_factors('daily')
    tb = MW.french_tables('49_Industry_Portfolios_daily')
    vw = next(v for t, v in tb.items() if t.startswith('Average Value Weighted Returns') and v['freq'] == 'daily')
    keys = ('Hardw', 'Softw', 'Chips')
    ix = {k: vw['cols'].index(k) for k in keys}
    ind = {k: {} for k in keys}
    for d, row in vw['data'].items():
        for k, i in ix.items():
            if row[i] is not None:
                ind[k][d] = row[i] / 100
    tm = MW.french_tables('49_Industry_Portfolios')
    nf = next(v for t, v in tm.items() if t.startswith('Number of Firms') and v['freq'] == 'monthly')
    sz = next(v for t, v in tm.items() if t.startswith('Average Firm Size') and v['freq'] == 'monthly')
    w = {k: {} for k in keys}
    for k in keys:
        i = nf['cols'].index(k)
        j = sz['cols'].index(k)
        for m, row in nf['data'].items():
            n, s = row[i], (sz['data'].get(m) or [None] * 99)[j]
            if n and s and n > 0 and s > 0:
                w[k][m] = n * s      # French の平均時価総額は組入れ時点（前月末）の値
    fdates = sorted(d for d in ff['rf'] if d in ff['mkt'])
    tech = tech_daily(ind, w, by_month(fdates))
    proxy = {d: TECH_W * tech[d] + MKT_W * ff['mkt'][d] for d in fdates if d in tech}
    return ff, ind, proxy


def build():
    ff, ind, proxy = _french()
    yld = _dgs10_daily()
    qqq, smh, spy = MW.yahoo('QQQ', '1d'), MW.yahoo('SMH', '1d'), MW.yahoo('SPY', '1d')
    irx = _yahoo_close('^IRX')
    f_rf = latest_getter(ff['rf'])
    last_ff = max(ff['rf'])
    irx_get = latest_getter(irx)

    def rf_b(d):
        if d in ff['rf']:
            return ff['rf'][d]
        if d > last_ff:
            v = irx_get(d)
            return v / 100 / DAYS if v is not None else f_rf(d)
        return f_rf(d)

    E = {}
    # A: 1965-07〜1999-12（信号のための前の値も同じ系列から）
    da = sorted(d for d in proxy if d <= 19991231)
    E['A'] = {'ndx': {d: proxy[d] for d in da}, 'semi': {d: ind['Chips'][d] for d in da if d in ind['Chips']},
              'mkt': {d: ff['mkt'][d] for d in da}, 'rf': f_rf}
    E['A']['bond'] = bond_daily(yld, [d for d in da if d >= 19620102])
    # B: 2000-01〜2026-09。QQQ の前は合成・SMH の前は Chips・SPY の前は French の市場（信号のためだけ）
    ndx = {d: proxy[d] for d in proxy if d < QQQ_FIRST}
    ndx.update({d: v for d, v in qqq.items() if QQQ_FIRST <= d <= B_LAST_DAY})
    semi = {d: ind['Chips'][d] for d in ind['Chips'] if d < SMH_FIRST}
    semi.update({d: v for d, v in smh.items() if SMH_FIRST <= d <= B_LAST_DAY})
    spy_first = min(spy)
    mkt = {d: ff['mkt'][d] for d in ff['mkt'] if d < spy_first}
    mkt.update({d: v for d, v in spy.items() if d <= B_LAST_DAY})
    E['B'] = {'ndx': ndx, 'semi': semi, 'mkt': mkt, 'rf': rf_b}
    E['B']['bond'] = bond_daily(yld, sorted(d for d in ndx if d >= 19620102))
    for e in E.values():
        e['dbm'] = {k: by_month(e[k]) for k in ('ndx', 'semi', 'mkt')}
        e['mon'] = {k: {m: compound(e[k], ds) for m, ds in e['dbm'][k].items()} for k in ('ndx', 'semi', 'mkt')}
        e['rfm'] = {m: compound({d: e['rf'](d) for d in ds}, ds) for m, ds in e['dbm']['ndx'].items()}
        lv, g = {}, 1.0
        for m in sorted(e['mon']['ndx']):
            g *= 1 + e['mon']['ndx'][m]
            lv[m] = g
        e['level'] = lv
    raw = {'qqq': qqq, 'proxy': proxy, 'irx': irx, 'yld': yld, 'ff_last': last_ff, 'spy_first': spy_first}
    return E, raw


# ───────────────────────── 作り方 ─────────────────────────
def strat(e, name, months, _cache=None):
    """→ (r: {月: 費用前の月次リターン}, c: {月: 費用の割合}, sw: {月: 持ち方の目標が変わったか}, tr: {月: 変えた量})"""
    ndx, dbm, rf = e['ndx'], e['dbm'], e['rf']
    r, c, sw, tr = {}, {}, {}, {}
    mon = e['mon']
    if name == 'B0':
        for m in months:
            r[m] = mon['ndx'][m]
        return r, c, sw, tr
    if name in ('L125', 'L150', 'MK130'):
        L = {'L125': 1.25, 'L150': 1.5, 'MK130': 1.3}[name]
        key = 'mkt' if name == 'MK130' else 'ndx'
        for m in months:
            r[m] = lev_month(e[key], dbm[key][m], L, rf)
        return r, c, sw, tr
    if name == 'RP150':
        comp = {d: 0.6 * ndx[d] + 0.4 * e['bond'][d] for d in ndx if d in e['bond']}
        for m in months:
            ds = [d for d in dbm['ndx'][m] if d in comp]
            r[m] = lev_month(comp, ds, 1.5, rf)
        return r, c, sw, tr
    if name in ('TR150', 'TR100', 'VT'):
        prevL = None
        for m in [add_months(months[0], -1)] + months:
            if name == 'VT':
                pm = add_months(m, -1)
                L = vt_L([ndx[d] for d in dbm['ndx'].get(pm, [])])
            else:
                s = tr_signal(e['level'], m)
                L = None if s is None else ((1.5 if s else 1.0) if name == 'TR150' else (1.0 if s else 0.0))
            if L is None:
                raise RuntimeError(f'{name}: {m} の信号に要る値が無い')
            if m in months:
                r[m] = lev_month(ndx, dbm['ndx'][m], L, rf)
                t = abs(L - prevL)
                tr[m], c[m], sw[m] = t, TRADE * t, t > 1e-12
            prevL = L
        return r, c, sw, tr
    if name in ('S30', 'S50'):
        w = 0.7 if name == 'S30' else 0.5
        for m in months:
            pm = add_months(m, -1)
            r[m] = w * mon['ndx'][m] + (1 - w) * mon['semi'][m]
            t = 2 * abs(w - drift_w(w, mon['ndx'][pm], mon['semi'][pm]))
            tr[m], c[m], sw[m] = t, TRADE * t, False
        return r, c, sw, tr
    if name == 'DM':
        assets = ('ndx', 'semi', 'mkt')
        prev = 'unset'
        for m in [add_months(months[0], -1)] + months:
            win = [add_months(m, -j) for j in range(12, 0, -1)]
            if any(x not in mon[a] for a in assets for x in win) or any(x not in e['rfm'] for x in win):
                raise RuntimeError(f'DM: {m} の12か月に要る値が無い')
            r12 = {a: math.prod(1 + mon[a][x] for x in win) - 1 for a in assets}
            rf12 = math.prod(1 + e['rfm'][x] for x in win) - 1
            pick = dm_pick(r12, rf12)
            if m in months:
                r[m] = e['rfm'][m] if pick is None else mon[pick][m]
                if pick == prev:
                    t = 0.0
                elif pick is None or prev is None:
                    t = 1.0
                else:
                    t = 2.0
                tr[m], c[m], sw[m] = t, TRADE * t, t > 0
            prev = pick
        return r, c, sw, tr
    if name == 'C1':
        ra, ca, swa, _ = strat(e, 'TR150', months)
        rb, cb, _, _ = strat(e, 'S30', [add_months(months[0], -1)] + months)
        for m in months:
            pm = add_months(m, -1)
            r[m] = 0.5 * ra[m] + 0.5 * rb[m]
            if pm in ra:
                t = 2 * abs(0.5 - drift_w(0.5, ra[pm], rb[pm]))
            else:   # 時代の最初の月: 前の月の TR150 を同じ規則で作る
                rpa, _, _, _ = strat(e, 'TR150', [pm])
                t = 2 * abs(0.5 - drift_w(0.5, rpa[pm], rb[pm]))
            tr[m] = t
            c[m] = 0.5 * ca.get(m, 0.0) + 0.5 * cb.get(m, 0.0) + TRADE * t
            sw[m] = swa.get(m, False)
        return r, c, sw, tr
    raise KeyError(name)


def life_window(e, start, n, cache):
    """LIFE の1つの窓: (r, c) を返す（倍率は窓の中の月の順番で決まる）"""
    months = [add_months(start, i) for i in range(n)]
    r, c, prevL = {}, {}, None
    for i, m in enumerate(months):
        L = round(life_L(i, n), 12)
        k = (m, L)
        if k not in cache:
            cache[k] = lev_month(e['ndx'], e['dbm']['ndx'][m], L, e['rf'])
        r[m] = cache[k]
        if prevL is not None:
            c[m] = TRADE * abs(L - prevL)
        prevL = L
    return months, r, c


# ───────────────────────── 測る ─────────────────────────
def dca_stats(ratios, finals_b0=None):
    v = [x for _, x in ratios]
    return {'windows': len(v), 'median': round(S.median(v), 4), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3),
            'worst': [ratios[min(range(len(v)), key=lambda i: v[i])][0], round(min(v), 4)],
            'best': [ratios[max(range(len(v)), key=lambda i: v[i])][0], round(max(v), 4)]}


def measure(E):
    res = {}
    for era, (a, z) in ERA.items():
        e = E[era]
        months = month_range(a, z)
        miss = [m for m in months if m not in e['mon']['ndx'] or m not in e['mon']['semi'] or m not in e['mon']['mkt']]
        if miss:
            raise RuntimeError(f'{era}: 月が欠けている {miss[:5]}')
        S_ = {k: strat(e, k, months) for k in METHODS if k != 'LIFE'}
        b0 = S_['B0'][0]
        rfm = {m: e['rfm'][m] for m in months}
        out = {}
        life_cache = {}
        for k in METHODS:
            row = {'label': LABEL[k]}
            for nm, (s0, s1), n in (('dca20', DCA20[era], 240), ('dca10', DCA10[era], 120)):
                starts = month_range(s0, s1)
                ratios, irr_s, irr_b = [], [], []
                for st in starts:
                    ms = [add_months(st, i) for i in range(n)]
                    if ms[-1] > z:
                        raise RuntimeError(f'{era} {nm}: 窓が時代の外へ出る {st}')
                    fb = dca_final(b0, {}, ms)
                    if k == 'LIFE':
                        _, r, c = life_window(e, st, n, life_cache)
                    else:
                        r, c = S_[k][0], S_[k][1]
                    fs = dca_final(r, c, ms)
                    ratios.append((st, fs / fb))
                    irr_s.append(irr_from_final(fs, n))
                    irr_b.append(irr_from_final(fb, n))
                st_ = dca_stats(ratios)
                st_['irr_median'] = round(S.median(irr_s) * 100, 2)
                st_['irr_median_b0'] = round(S.median(irr_b) * 100, 2)
                st_['irr_worst'] = round(min(irr_s) * 100, 2)
                st_['irr_worst_b0'] = round(min(irr_b) * 100, 2)
                row[nm] = st_
            if k != 'LIFE':
                r, c, sw, tr = S_[k]
                ls = lump_series(r, c, months)
                yrs = len(months) / 12
                row['lump'] = {'cagr': round(MW.cagr(ls) * 100, 2), 'vol': round(S.stdev(ls.values()) * math.sqrt(12) * 100, 1),
                               'maxdd': round(MW.maxdd(ls) * 100, 1), 'sharpe': MW.sharpe(ls, rfm)}
                if k != 'B0':
                    ex = MW.excess_stats(ls, {m: b0[m] for m in months})
                    row['lump'].update({'ex_ann_vs_b0': ex['ex_ann'], 't_vs_b0': ex['t'], 'cagr_diff_vs_b0': ex['cagr_diff'],
                                        'beta_vs_b0': ex['beta'], 'te': ex['te']})
                row['trades'] = {'switches_per_year': round(sum(1 for m in months if sw.get(m)) / yrs, 2),
                                 'turnover_per_year': round(sum(tr.get(m, 0.0) for m in months) / yrs, 3),
                                 'cost_per_year_pct': round(sum(c.get(m, 0.0) for m in months) / yrs * 100, 3)}
                # 最悪の年（暦年）・一番深い下落の時期
                yr = {}
                for m in months:
                    yr[m // 100] = (1 + yr.get(m // 100, 0.0)) * (1 + ls[m]) - 1
                wy = min(yr, key=yr.get)
                row['lump']['worst_year'] = [wy, round(yr[wy] * 100, 1)]
            out[k] = row
        b0c = out['B0']['lump']['cagr']
        for k in METHODS:
            if k == 'B0':
                continue
            d = out[k]['dca20']
            ok = {'median': d['median'] >= LINES['median'], 'win_rate': d['win_rate'] >= LINES['win_rate'],
                  'worst': d['worst'][1] >= LINES['worst']}
            if k != 'LIFE':
                ok['lump'] = out[k]['lump']['cagr'] > b0c
            out[k]['criteria'] = ok
            out[k]['passed'] = all(ok.values())
        res[era] = {'months': [months[0], months[-1]], 'methods': out}
    return res


def verdicts(res):
    V = {}
    for k in METHODS:
        if k == 'B0':
            continue
        pa, pb = res['A']['methods'][k]['passed'], res['B']['methods'][k]['passed']
        if pa and pb:
            v = 'NASDAQ100 を超えた（両方の時代）'
        elif pa or pb:
            v = f"片方の時代だけ（{'A' if pa else 'B'}）"
        else:
            v = '超えなかった'
        unmet = sum(1 for era in 'AB' for x in res[era]['methods'][k]['criteria'].values() if not x)
        V[k] = {'verdict': v, 'unmet': unmet,
                'min_worst': min(res[era]['methods'][k]['dca20']['worst'][1] for era in 'AB'),
                'min_median': min(res[era]['methods'][k]['dca20']['median'] for era in 'AB')}
    both = [k for k, x in V.items() if x['verdict'].startswith('NASDAQ100 を超えた')]
    if both:
        top = max(V[k]['min_worst'] for k in both)
        near = [k for k in both if V[k]['min_worst'] >= top - 0.01]
        pick = max(near, key=lambda k: (V[k]['min_median'], V[k]['min_worst']))
        sel = {'kind': '両方の時代で超えた作り方から選んだ', 'pick': pick, 'label': LABEL[pick], 'candidates': both}
    else:
        pick = min(V, key=lambda k: (V[k]['unmet'], -V[k]['min_median']))
        sel = {'kind': '両方の時代で超えた作り方は無かった（いちばん近かったもの）', 'pick': pick, 'label': LABEL[pick], 'candidates': []}
    return V, sel


def data_checks(E, raw):
    """参考（結果で作り方は変えない）: 合成と本物の比較・借入の費用の仮定と QLD"""
    out = {}
    prx = MW.to_monthly(raw['proxy'])
    ndx_p = MW.to_monthly(MW.yahoo('^NDX', '1d'))
    for nm, other, a, z in (('合成 vs ^NDX（値段だけ・配当なし）', ndx_p, 198601, 199912),
                            ('合成 vs QQQ（配当込み）', MW.to_monthly({d: v for d, v in raw['qqq'].items() if d <= B_LAST_DAY}), 199904, min(202608, raw['ff_last'] // 100))):
        ks = [m for m in month_range(a, z) if m in prx and m in other]
        out[nm] = {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'corr': round(MW.corr([prx[m] for m in ks], [other[m] for m in ks]), 3),
                   'cagr_proxy': round(MW.cagr([prx[m] for m in ks]) * 100, 2), 'cagr_other': round(MW.cagr([other[m] for m in ks]) * 100, 2),
                   'vol_proxy': round(S.stdev([prx[m] for m in ks]) * math.sqrt(12) * 100, 1),
                   'vol_other': round(S.stdev([other[m] for m in ks]) * math.sqrt(12) * 100, 1)}
    qld = MW.yahoo('QLD', '1d')
    e = E['B']
    q0 = min(qld)
    ds = [d for d in sorted(qld) if d <= B_LAST_DAY and d in e['ndx']]
    mo = {}
    for d in ds:
        m = d // 100
        mo.setdefault(m, [1.0, 1.0])
        mo[m][0] *= 1 + qld[d]
        mo[m][1] *= 1 + lev_day(e['ndx'][d], 2.0, e['rf'](d))
    ks = [m for m in sorted(mo) if m > q0 // 100]     # 最初の月（途中から）は外す
    out['QLD（実物の2倍） vs この検証の2倍（短期金利＋1.5%）'] = {
        'from': ks[0], 'to': ks[-1], 'months': len(ks),
        'cagr_qld': round(MW.cagr([mo[m][0] - 1 for m in ks]) * 100, 2),
        'cagr_model': round(MW.cagr([mo[m][1] - 1 for m in ks]) * 100, 2)}
    x = out['QLD（実物の2倍） vs この検証の2倍（短期金利＋1.5%）']
    x['diff_model_minus_qld'] = round(x['cagr_model'] - x['cagr_qld'], 2)
    # 資産そのものの年率（各時代）
    for era, (a, z) in ERA.items():
        ms = month_range(a, z)
        out[f'資産の年率（{era}）'] = {k: round(MW.cagr([E[era]['mon'][k][m] for m in ms]) * 100, 2) for k in ('ndx', 'semi', 'mkt')}
        out[f'資産の年率（{era}）']['rf'] = round(MW.cagr([E[era]['rfm'][m] for m in ms]) * 100, 2)
    return out


def _git(*a):
    try:
        return subprocess.run(['git', *a], cwd=BASE, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None


def main(argv):
    pre = open(PRE, 'rb').read()
    sha = hashlib.sha256(pre).hexdigest()
    E, raw = build()
    if argv and argv[0] == 'data':
        print(json.dumps(data_checks(E, raw), ensure_ascii=False, indent=1))
        return
    res = measure(E)
    V, sel = verdicts(res)
    obj = {'title': 'NASDAQ100 を超えるポートフォリオの作り方を二つの時代で総当たり（bx）', 'generated': datetime.date.today().isoformat(),
           'prereg': 'out/beatndx_prereg.json', 'prereg_sha256': sha,
           'prereg_commit': _git('log', '-1', '--format=%h', '--', 'out/beatndx_prereg.json'),
           'tool_commit': _git('log', '-1', '--format=%h', '--', 'night/beatndx.py'),
           'lines': LINES, 'costs': {'spread': SPREAD, 'trade': TRADE},
           'eras': {k: {'months': v['months']} for k, v in res.items()},
           'verdicts': V, 'selection': sel, 'results': res, 'data_checks': data_checks(E, raw),
           'note': '判定は事前登録の線のとおり（税の前）。20年の窓は重なっているので、独立した20年は A で約1.7回・B で約1.3回しかない'}
    tmp = OUT + '.tmp'
    json.dump(obj, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print('prereg sha256', sha)
    for k in METHODS:
        if k == 'B0':
            continue
        a, b = res['A']['methods'][k], res['B']['methods'][k]
        print(f"{k:6s} A 中央{a['dca20']['median']:.3f} 勝{a['dca20']['win_rate']:.2f} 最悪{a['dca20']['worst'][1]:.3f} | "
              f"B 中央{b['dca20']['median']:.3f} 勝{b['dca20']['win_rate']:.2f} 最悪{b['dca20']['worst'][1]:.3f} → {V[k]['verdict']}")
    print('提案:', sel)


if __name__ == '__main__':
    main(sys.argv[1:])
