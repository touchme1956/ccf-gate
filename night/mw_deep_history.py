#!/usr/bin/env python3
"""night/mw_deep_history.py — 『市場に勝てる歴史検証』の角度 deep_history（深い歴史での独立の答え合わせ）。
読むだけ・門の判定には不使用。

事前登録: out/mw_deep_history_prereg.json（C1〜C8 の線は out/mw_prereg.json・判定は mw_common.grade）
出力:     out/mw_deep_history.json

問い: 国の割安・国の勢い・トレンド・季節性で『指数を選ぶ』規則は、これまでの mw が使っていない
      1870〜1925 年（JST・年次）と米国外16か国（1870〜2020）、BSV の 1800〜1925 年でも市場に勝つか。

使い方:
  python3 night/mw_deep_history.py --check   # データの配管だけ点検（戦略と相手の比較は出さない）
  python3 night/mw_deep_history.py           # 全部測って out/mw_deep_history.json を書く

約束（mw_common に従う）
- 年次のキーは年（int）、月次は yyyymm。リターンは小数
- 年末 Y に分かる値だけで選び、年 Y+1 のリターンに当てる（先読みなし・機械で検算する）
- 欠けた値・無効な国と年は 0 と読まない（順位にも相手にも入れない／戦略の年を空欄にする）
- H（通貨ヘッジ相当）と U（未ヘッジ米ドル）を混ぜない。BSV の系列は超過なので市場に足すとき短期金利を足さない
"""
import sys, os, io, json, math, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PREREG = 'out/mw_deep_history_prereg.json'
PREREG2 = 'out/mw_deep_history_prereg2.json'
OUT = 'mw_deep_history.json'
JST_URL = 'https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx?t=1763503850'
BSV_URL = 'https://ndownloader.figshare.com/files/26879918'

C16 = 'AUS BEL CHE DEU DNK ESP FIN FRA GBR ITA JPN NLD NOR PRT SWE USA'.split()
EUROPE13 = 'BEL CHE DEU DNK ESP FIN FRA GBR ITA NLD NOR PRT SWE'.split()
EXUS15 = [c for c in C16 if c != 'USA']
U_WAR = range(1939, 1950)          # 未ヘッジ（U）だけ全か国無効（為替の質）
COST_UNIT = 0.002                  # 片道100%あたり（国別ETF・課題の指定）
COST_STRICT = 0.010                # 感応度（1925 年以前の現実に近い厳しめ）
LAG_Y = 2
T_END = 1925                       # JST の訓練（C1）の終わり
H_START = 1926                     # JST の保有（C2・C3・C6）の始まり

LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


# ───────────────────────── データ ─────────────────────────
def jst():
    import openpyxl
    b = M.get(JST_URL, 'jst_R6.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = list(wb['Sheet1'].iter_rows(values_only=True))
    h = rows[0]
    cols = ['eq_tr', 'eq_dp', 'bill_rate', 'xrusd', 'cpi', 'gdp']
    I = {c: h.index(c) for c in cols + ['year', 'iso']}
    D = {}
    for r in rows[1:]:
        iso = r[I['iso']]
        if iso not in C16:
            continue
        D.setdefault(iso, {})[int(r[I['year']])] = {c: (float(r[I[c]]) if r[I[c]] is not None else None) for c in cols}
    return D


def bsv():
    """BSV の『Data BSV_JFE』→ {(型, 資産): {yyyymm: r}}（'NA' は欠測＝キーを作らない）"""
    import openpyxl
    b = M.get(BSV_URL, 'bsv_gfp_1800_2016.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = list(wb['Data BSV_JFE'].iter_rows(values_only=True))
    blocks, h = rows[4], rows[5]
    names, cur = [], None
    for bl, c in zip(blocks, h):
        if bl:
            cur = {'Trend': 'Trend', 'Momentum': 'Momentum', 'Value': 'Value', 'Carry': 'Carry', 'Seasonal': 'Seasonal'}.get(bl, 'BAB' if 'BAB' in str(bl) else bl)
        names.append((cur, c))
    out = {}
    for r in rows[6:]:
        if not isinstance(r[0], (int, float)) or not isinstance(r[1], (int, float)):
            continue
        k = int(r[0]) * 100 + int(r[1])
        for i, (st, a) in enumerate(names):
            if a in (None, 'Year', 'Month'):
                continue
            v = r[i]
            if isinstance(v, (int, float)):
                out.setdefault((st, a), {})[k] = float(v)
    return out


def shiller_tr():
    import xlrd
    b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', name='shiller_ie_data.xls', max_age_days=3650)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    P, Dv = {}, {}
    for i in range(8, sh.nrows):
        row = sh.row_values(i)
        if not isinstance(row[0], float):
            continue
        s = f'{row[0]:.2f}'
        k = int(s[:4]) * 100 + int(s[5:7])
        if isinstance(row[1], float):
            P[k] = row[1]
        if isinstance(row[2], float):
            Dv[k] = row[2]
    ks = sorted(P)
    return {k: (P[k] + Dv[k] / 12) / P[p] - 1 for p, k in zip(ks, ks[1:]) if k in Dv}


def fred_monthly(sid):
    c = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=3650).decode()
    out = {}
    for line in c.strip().splitlines()[1:]:
        d, v = line.split(',')
        if v in ('', '.'):
            continue
        out[int(d[:4]) * 100 + int(d[5:7])] = float(v)
    return out


def us_monthly():
    """m: 1871-02〜1926-06 Shiller、1926-07〜 French Mkt。rf: 1926-06 まで NBER 商業手形、以降 French RF"""
    sh = shiller_tr()
    ff = M.ff_factors()
    cp = {k: v / 1200 for k, v in fred_monthly('M13002US35620M156NNBR').items()}
    m, rf, src = {}, {}, {}
    for k, v in sh.items():
        if k <= 192606:
            m[k] = v; src[k] = 'shiller'
    for k, v in ff['mkt'].items():
        if k >= 192607:
            m[k] = v; src[k] = 'french'
    for k, v in cp.items():
        if k <= 192606:
            rf[k] = v
    for k, v in ff['rf'].items():
        if k >= 192607:
            rf[k] = v
    return m, rf, src, sh, ff


# ───────────────────────── JST のリターンと有効性 ─────────────────────────
class JST:
    def __init__(self, D):
        self.D = D
        self.invalid_counts = {'H': {}, 'U': {}}

    def g(self, c, Y, k):
        return self.D.get(c, {}).get(Y, {}).get(k)

    def infl(self, c, Y):
        a, b = self.g(c, Y, 'cpi'), self.g(c, Y - 1, 'cpi')
        return a / b - 1 if a is not None and b not in (None, 0) else None

    def r(self, base, c, Y):
        """有効なら (1 + r) − 1、無効なら None（0 と読まない）"""
        eq = self.g(c, Y, 'eq_tr')
        if eq is None:
            return None
        inf = self.infl(c, Y)
        if inf is None or inf >= 1.0:
            return None
        if base == 'H':
            bl, bu = self.g(c, Y, 'bill_rate'), self.g('USA', Y, 'bill_rate')
            if bl is None or bu is None:
                return None
            return (1 + eq) / (1 + bl) * (1 + bu) - 1
        if Y in U_WAR:
            return None
        x0, x1 = self.g(c, Y - 1, 'xrusd'), self.g(c, Y, 'xrusd')
        if not x0 or not x1:
            return None
        return (1 + eq) * x0 / x1 - 1

    def hx(self, c, Y):
        """H の超過（現地の短期金利を引いた株の上乗せ）。無効なら None"""
        eq, bl = self.g(c, Y, 'eq_tr'), self.g(c, Y, 'bill_rate')
        if eq is None or bl is None or self.r('H', c, Y) is None:
            return None
        return (1 + eq) / (1 + bl) - 1

    def cash(self, Y):
        return self.g('USA', Y, 'bill_rate')


# ───────────────────────── 規則（年末 Y の情報だけ） ─────────────────────────
def pct_rank(vals):
    """{c: v} → {c: 百分位 0..1}（昇順の順位 ÷ (n−1)。同値は平均順位）"""
    items = sorted(vals.items(), key=lambda x: x[1])
    n = len(items)
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        rk = (i + j) / 2
        for t in range(i, j + 1):
            out[items[t][0]] = rk / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def topk(scores, K, reverse=True):
    """同点は国コードで決める（決定的）"""
    return [c for c, _ in sorted(scores.items(), key=lambda x: ((-x[1]) if reverse else x[1], x[0]))[:K]]


def cum(J, base, c, Y, n):
    w = 1.0
    for y in range(Y - n + 1, Y + 1):
        r = J.r(base, c, y)
        if r is None:
            return None
        w *= 1 + r
    return w - 1


def select(rule, J, base, univ, Y, K=None):
    """年末 Y に分かる値だけ → 目標の重み {国 or 'CASH': w}。空欄なら None"""
    UY = [c for c in univ if J.r(base, c, Y) is not None]
    if not UY:
        return None
    if rule == 'VAL':
        sc = {c: J.g(c, Y, 'eq_dp') for c in UY if J.g(c, Y, 'eq_dp') is not None}
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K)}
    if rule == 'MOM':
        sc = {c: J.r(base, c, Y) for c in UY}
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K)}
    if rule == 'VM':
        a, b = select('VAL', J, base, univ, Y, K), select('MOM', J, base, univ, Y, K)
        if a is None or b is None:
            return None
        w = {}
        for d in (a, b):
            for c, v in d.items():
                w[c] = w.get(c, 0) + 0.5 * v
        return w
    if rule in ('AVOID1', 'AVOID3'):
        n = 1 if rule == 'AVOID1' else 3
        sc = {c: cum(J, base, c, Y, 10) for c in UY}
        sc = {c: v for c, v in sc.items() if v is not None}
        if len(sc) < n + 1:
            return None
        drop = set(topk(sc, n))
        keep = [c for c in UY if c not in drop]
        return {c: 1 / len(keep) for c in keep}
    if rule == 'TREND':
        w = {}
        for c in UY:
            sig = J.hx(c, Y) if base == 'H' else (J.r('U', c, Y) - J.cash(Y) if J.cash(Y) is not None else None)
            if sig is None:
                return None
            if sig > 0:
                w[c] = 1 / len(UY)
            else:
                w['CASH'] = w.get('CASH', 0) + 1 / len(UY)
        return w
    if rule == 'CARRY':
        sc = {}
        for c in UY:
            dp, bl = J.g(c, Y, 'eq_dp'), J.g(c, Y, 'bill_rate')
            if dp is not None and bl is not None:
                sc[c] = dp - bl
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K)}
    if rule == 'REV5':
        sc = {c: cum(J, base, c, Y, 5) for c in UY}
        sc = {c: v for c, v in sc.items() if v is not None}
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K, reverse=False)}
    if rule == 'VMRANK':
        dp = {c: J.g(c, Y, 'eq_dp') for c in UY if J.g(c, Y, 'eq_dp') is not None}
        if len(dp) < 2 * K:
            return None
        mo = {c: J.r(base, c, Y) for c in dp}
        pd, pm = pct_rank(dp), pct_rank(mo)
        sc = {c: (pd[c] + pm[c]) / 2 for c in dp}
        order = sorted(sc, key=lambda c: (-sc[c], -pm[c], c))[:K]
        return {c: 1 / K for c in order}
    if rule == 'VALTREND':
        v = select('VAL', J, base, univ, Y, K)
        if v is None:
            return None
        w = {}
        for c, x in v.items():
            s = J.hx(c, Y)
            if s is None:
                return None
            if s > 0:
                w[c] = w.get(c, 0) + x
            else:
                w['CASH'] = w.get('CASH', 0) + x
        return w
    if rule == 'RELDY':
        sc = {}
        for c in UY:
            d = J.g(c, Y, 'eq_dp')
            hist = [J.g(c, y, 'eq_dp') for y in range(Y - 10, Y)]
            hist = [x for x in hist if x is not None and x > 0]
            if d is None or len(hist) < 5:
                continue
            md = S.median(hist)
            if md > 0:
                sc[c] = d / md
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K)}
    # ── 第2族（頑健性・事前登録2）: 1年古い信号 ──
    if rule == 'VALLAG':
        sc = {c: J.g(c, Y - 1, 'eq_dp') for c in UY if J.g(c, Y - 1, 'eq_dp') is not None}
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K)}
    if rule == 'MOMSKIP':
        sc = {c: J.r(base, c, Y - 1) for c in UY if J.r(base, c, Y - 1) is not None}
        if len(sc) < 2 * K:
            return None
        return {c: 1 / K for c in topk(sc, K)}
    if rule == 'VMLAG':
        a, b = select('VALLAG', J, base, univ, Y, K), select('MOMSKIP', J, base, univ, Y, K)
        if a is None or b is None:
            return None
        w = {}
        for d in (a, b):
            for c, v in d.items():
                w[c] = w.get(c, 0) + 0.5 * v
        return w
    if rule == 'EW':
        return {c: 1 / len(UY) for c in UY}
    raise ValueError(rule)


def run_rule(J, base, rule, K=None, univ=C16, y0=1870, y1=2019):
    """年末 Y の選択を年 Y+1 に当てる。→ dict（年次の系列 {年: r}）"""
    gross, bench, turn, events = {}, {}, {}, {'renorm': 0, 'blank_all_invalid': 0}
    picks = {}
    prev = None      # 前の年の（割り直し後の）重み
    prev_r = None    # 前の年の国ごとのリターン
    for Y in range(y0, y1 + 1):
        UY = [c for c in univ if J.r(base, c, Y) is not None]
        # 相手: U_Y のうち Y+1 が有効な国の等分
        bv = [J.r(base, c, Y + 1) for c in UY if J.r(base, c, Y + 1) is not None]
        w = select(rule, J, base, univ, Y, K)
        if w is None or not bv:
            prev = None
            continue
        rr = {}
        for c in w:
            rr[c] = J.cash(Y + 1) if c == 'CASH' else J.r(base, c, Y + 1)
        valid = {c: x for c, x in w.items() if rr[c] is not None}
        if not valid:
            events['blank_all_invalid'] += 1
            prev = None
            continue
        if len(valid) < len(w):
            events['renorm'] += 1
        tot = sum(valid.values())
        wv = {c: x / tot for c, x in valid.items()}
        # 回転: 前の年の重みが年 Y に漂った姿 → 今年の目標
        if prev is not None and prev_r is not None:
            rp = sum(prev[c] * prev_r[c] for c in prev)
            drift = {c: prev[c] * (1 + prev_r[c]) / (1 + rp) for c in prev}
            keys = set(drift) | set(wv)
            to = sum(abs(wv.get(c, 0) - drift.get(c, 0)) for c in keys) / 2
        else:
            to = 0.0
        g = sum(wv[c] * rr[c] for c in wv)
        gross[Y + 1] = g
        bench[Y + 1] = sum(bv) / len(bv)
        turn[Y + 1] = to
        picks[Y + 1] = sorted(w)
        prev, prev_r = wv, {c: rr[c] for c in wv}
    net = {y: gross[y] - turn[y] * COST_UNIT for y in gross}
    net_strict = {y: gross[y] - turn[y] * COST_STRICT for y in gross}
    return {'gross': gross, 'net': net, 'net_strict': net_strict, 'bench': bench, 'turn': turn, 'events': events, 'picks': picks}


def gdp_bench(J, base, univ=C16, y0=1870, y1=2019):
    out = {}
    for Y in range(y0, y1 + 1):
        if Y in U_WAR or Y + 1 in U_WAR:
            continue
        UY = [c for c in univ if J.r(base, c, Y) is not None]
        ws = {}
        for c in UY:
            g, x = J.g(c, Y, 'gdp'), J.g(c, Y, 'xrusd')
            r1 = J.r(base, c, Y + 1)
            if g and x and r1 is not None:
                ws[c] = (g / x, r1)
        if not ws:
            continue
        tw = sum(a for a, _ in ws.values())
        out[Y + 1] = sum(a / tw * r for a, r in ws.values())
    return out


# ───────────────────────── 統計（年次の自前の部品） ─────────────────────────
def es(s, b, a=None, z=None, per_year=1, lag=LAG_Y):
    return M.excess_stats(s, b, a, z, per_year=per_year, lag=lag)


def nw_t_small(x, lag=1):
    n = len(x)
    if n < 6:
        return None
    m = S.mean(x); e = [v - m for v in x]
    s = sum(v * v for v in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * sum(e[i] * e[i - L] for i in range(L, n)) / n
    return m / math.sqrt(s / n) if s > 0 else None


def short_stats(s, b, a, z, lag=1):
    """24年未満の窓（2007〜2020 など）の自前の要約（年次）"""
    ks = sorted(k for k in set(s) & set(b) if a <= k <= z)
    if len(ks) < 6:
        return None
    ex = [s[k] - b[k] for k in ks]
    gs = math.exp(math.fsum(math.log1p(s[k]) for k in ks) / len(ks)) - 1
    gb = math.exp(math.fsum(math.log1p(b[k]) for k in ks) / len(ks)) - 1
    t = nw_t_small(ex, lag)
    return {'from': ks[0], 'to': ks[-1], 'years': len(ks), 'ex_ann': round(S.mean(ex) * 100, 2),
            't': round(t, 2) if t is not None else None, 'cagr_diff': round((gs - gb) * 100, 2),
            'win_years': sum(1 for x in ex if x > 0)}


def roll_annual(s, b, years=20):
    ks = sorted(set(s) & set(b))
    out = []
    for y in ks:
        w = list(range(y, y + years))
        if not all(k in s and k in b for k in w):
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, round((gs - gb) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'windows': len(out), 'wins': sum(1 for _, c in out if c > 0), 'win_rate': round(sum(1 for _, c in out if c > 0) / len(out), 3),
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1]),
            'note': '年次・毎年起点・20年・一括・幾何の年率差（連続20年がそろう窓だけ）'}


def dca_annual(s, b, years=20):
    ks = sorted(set(s) & set(b))
    out = []
    for y in ks:
        w = list(range(y, y + years))
        if not all(k in s and k in b for k in w):
            continue
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append((y, round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def sharpe_annual(r, J, a, z):
    ks = [k for k in sorted(r) if a <= k <= z and J.cash(k) is not None]
    if len(ks) < 24:
        return None
    x = [r[k] - J.cash(k) for k in ks]
    sd = S.stdev(x)
    return round(S.mean(x) / sd, 3) if sd else None


def mdd_annual(r):
    return round(M.maxdd(r) * 100, 1)


# ───────────────────────── 評価（JST） ─────────────────────────
def eval_jst(J, sid, base, rule, K, timing, univ=C16):
    R = run_rule(J, base, rule, K, univ)
    g, n, ns, b = R['gross'], R['net'], R['net_strict'], R['bench']
    if not g:
        return {'id': sid, 'status': 'no_data'}
    yrs = sorted(g)
    e = {'id': sid, 'base': base, 'rule': rule, 'K': K, 'timing': timing,
         'years': [yrs[0], yrs[-1]], 'n_years': len(yrs),
         'mean_turnover_oneway': round(S.mean(R['turn'].values()), 3),
         'events': R['events'],
         'full': es(g, b), 'train': es(g, b, None, T_END), 'hold': es(g, b, H_START, None),
         'full_net': es(n, b), 'train_net': es(n, b, None, T_END), 'hold_net': es(n, b, H_START, None),
         'hold_net_strict': es(ns, b, H_START, None), 'train_net_strict': es(ns, b, None, T_END),
         'disc_1926_2006': es(g, b, 1926, 2006),
         'h2007_2020': short_stats(g, b, 2007, 2020), 'h2007_2020_net': short_stats(n, b, 2007, 2020),
         'post_pub_1998_2020': short_stats(g, b, 1998, 2020) if rule in ('VAL', 'MOM', 'VM', 'VMRANK', 'REV5') else None,
         'roll20': roll_annual(g, b), 'dca20': dca_annual(g, b),
         'mdd_s': mdd_annual(g), 'mdd_b': mdd_annual(b)}
    if timing:
        e['sharpe'] = {'train': (sharpe_annual(n, J, 0, T_END), sharpe_annual(b, J, 0, T_END)),
                       'hold': (sharpe_annual(n, J, H_START, 9999), sharpe_annual(b, J, H_START, 9999))}
    # 報告: GDP の重みの相手・米国だけ
    gb = gdp_bench(J, base, univ)
    usa = {y: J.r(base, 'USA', y) for y in g if J.r(base, 'USA', y) is not None}
    e['vs_gdp_weight'] = {'train': es(g, gb, None, T_END), 'hold': es(g, gb, H_START, None)}
    e['vs_usa'] = {'train': es(g, usa, None, T_END), 'hold': es(g, usa, H_START, None)}
    e['_series'] = R
    return e


def grade_jst(e, holm_p, G2=False):
    if G2:
        R = e['_series']
        g, n, b = R['gross'], R['net'], R['bench']
        train, hold, ch = es(g, b, 1926, 2006), es(g, b, None, T_END), es(n, b, None, T_END)
    else:
        train, hold, ch = e['train'], e['hold'], e['hold_net']
    sp = None
    if e['timing']:
        sp = {'train': e['sharpe']['train'], 'hold': e['sharpe']['hold']}
        if G2:
            sp = {'train': e['sharpe']['hold'], 'hold': e['sharpe']['train']}
    return M.grade(e['full'], train, hold, e['roll20'], cost_hold=ch, repl=None, family_holm_p=holm_p,
                   sharpe_pair=sp, leveraged_or_timing=e['timing'])


# ───────────────────────── 評価（BSV・上乗せ） ─────────────────────────
BSV_T = {'Trend': 4, 'Momentum': 6, 'Value': 2, 'Carry': 6, 'Seasonal': 12, 'BAB': 4, 'Multi': 6}
STYLES = ['Trend', 'Momentum', 'Value', 'Carry', 'Seasonal', 'BAB']


def bsv_multi(B, asset):
    ks = set()
    for st in STYLES:
        ks |= set(B.get((st, asset), {}))
    out = {}
    for k in sorted(ks):
        v = [B[(st, asset)][k] for st in STYLES if k in B.get((st, asset), {})]
        if len(v) >= 4:
            out[k] = S.mean(v)
    return out


def eval_bsv(sid, F, style, m, rf, kk=0.5):
    c = BSV_T[style] * 0.001 + 0.005
    eg = {k: kk * v for k, v in F.items()}
    en = {k: kk * (v - c / 12) for k, v in F.items()}
    zero = {k: 0.0 for k in F}
    sg = {k: m[k] + eg[k] for k in eg if k in m}
    sn = {k: m[k] + en[k] for k in en if k in m}
    e = {'id': sid, 'style': style, 'k': kk, 'cost_per_unit_ann': round(c * 100, 2),
         'full': M.excess_stats(eg, zero, 180001, 201612),
         'train': M.excess_stats(eg, zero, 180001, 192512),
         'train_1871': M.excess_stats(sg, m, 187102, 192512),
         'hold': M.excess_stats(sg, m, 192601, 201612),
         'hold_net': M.excess_stats(sn, m, 192601, 201612),
         'train_net': M.excess_stats(en, zero, 180001, 192512),
         'disc_1926_2006': M.excess_stats(sg, m, 192601, 200612),
         'h2007_2016': M.excess_stats(sg, m, 200701, 201612),
         'h2007_2016_net': M.excess_stats(sn, m, 200701, 201612),
         'roll20': M.rolling(sg, m), 'dca20': M.dca(sg, m),
         'sharpe': {'train': (M.sharpe(sn, rf, 187102, 192512), M.sharpe(m, rf, 187102, 192512)),
                    'hold': (M.sharpe(sn, rf, 192601, 201612), M.sharpe(m, rf, 192601, 201612))},
         'corr_with_mkt_train': round(M.corr([F[k] for k in sorted(F) if k in m and k <= 192512], [m[k] for k in sorted(F) if k in m and k <= 192512]), 3),
         'corr_with_mkt_hold': round(M.corr([F[k] for k in sorted(F) if k in m and k >= 192601], [m[k] for k in sorted(F) if k in m and k >= 192601]), 3),
         'note': '訓練と全期間は上乗せの超過（k×F）vs 0（市場の系列に依らない・cagr は上乗せそのものの幾何）。保有は m+k×F vs m'}
    return e


def grade_over(e, holm_p):
    return M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['hold_net'], repl=None,
                   family_holm_p=holm_p, sharpe_pair=e['sharpe'], leveraged_or_timing=True)


# ───────────────────────── 評価（ハロウィーン・米国） ─────────────────────────
def hal_series(m, rf, kind, months=(11, 12, 1, 2, 3, 4), spread=0.005, cost=0.001, with_cost=True):
    out = {}
    for k in sorted(m):
        if k not in rf:
            continue
        mo = k % 100
        on = mo in months
        if kind == 'OV15':
            r = m[k] + (0.5 * (m[k] - rf[k] - spread / 12) if on else 0.0)
            tc = 0.5 * cost if mo in (months[0], (months[-1] % 12) + 1) else 0.0
        else:
            r = m[k] if on else rf[k]
            tc = 1.0 * cost if mo in (months[0], (months[-1] % 12) + 1) else 0.0
        out[k] = r - (tc if with_cost else 0.0)
    return out


def eval_hal(sid, kind, m, rf, months=(11, 12, 1, 2, 3, 4)):
    g = hal_series(m, rf, kind, months, with_cost=False)
    n = hal_series(m, rf, kind, months, with_cost=True)
    turn = 1.0 if kind == 'OV15' else 2.0
    e = {'id': sid, 'kind': kind, 'months': list(months), 'turnover_oneway_ann': turn,
         'full': M.excess_stats(g, m), 'train': M.excess_stats(g, m, 187102, 192512),
         'hold': M.excess_stats(g, m, 192607, None), 'hold_net': M.excess_stats(n, m, 192607, None),
         'train_net': M.excess_stats(n, m, 187102, 192512),
         'h2007': M.excess_stats(g, m, 200701, None), 'post_pub_2003': M.excess_stats(g, m, 200301, None),
         'roll20': M.rolling(g, m), 'dca20': M.dca(g, m),
         'sharpe': {'train': (M.sharpe(n, rf, 187102, 192512), M.sharpe(m, rf, 187102, 192512)),
                    'hold': (M.sharpe(n, rf, 192607, None), M.sharpe(m, rf, 192607, None))}}
    return e


# ───────────────────────── 点検 ─────────────────────────
def check_only():
    D = jst()
    J = JST(D)
    for base in 'HU':
        cnt = {}
        for Y in range(1870, 2021):
            cnt[Y] = sum(1 for c in C16 if J.r(base, c, Y) is not None)
        log(base, '有効な国の数', {y: cnt[y] for y in [1871, 1872, 1875, 1880, 1885, 1890, 1900, 1915, 1920, 1926, 1939, 1946, 1950, 2000, 2020]})
    B = bsv()
    log('BSV 系列', len(B), sorted(B)[:3], 'EQ Trend', min(B[('Trend', 'EQ')]), max(B[('Trend', 'EQ')]))
    m, rf, src, sh, ff = us_monthly()
    log('m', min(m), max(m), len(m), 'rf', min(rf), max(rf), len(rf))


def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-n1', '--format=%H', '--', path], cwd=M.BASE).decode().strip() or None
    except Exception:
        return None


def lookahead_check(J, specs):
    """年 Y+1 の選択を『年 Y までの行だけを残した表』から作り直して一致を確かめる"""
    bad, n = [], 0
    for sid, base, rule, K, univ in specs:
        for Y in range(1871, 2020, 3):
            full = select(rule, J, base, univ, Y, K)
            Dt = {c: {y: v for y, v in d.items() if y <= Y} for c, d in J.D.items()}
            Jt = JST(Dt)
            tr = select(rule, Jt, base, univ, Y, K)
            n += 1
            if (full is None) != (tr is None) or (full and tr and {k: round(v, 12) for k, v in full.items()} != {k: round(v, 12) for k, v in tr.items()}):
                bad.append((sid, Y))
    return {'checked': n, 'mismatch': bad[:20], 'n_mismatch': len(bad)}


def strip(e):
    return {k: v for k, v in e.items() if not k.startswith('_')}


# ───────────────────────── 第2族（事前登録2）の報告の部品 ─────────────────────────
def block_boot_p(x, block=5, reps=5000, seed=7):
    """循環ブロック・ブートストラップ: 『平均 ≤ 0』の片側 p（中心化した分布で観測の平均以上になる割合）"""
    import random
    rnd = random.Random(seed)
    n = len(x)
    if n < 10:
        return None
    m = S.mean(x)
    cnt = 0
    nb = math.ceil(n / block)
    for _ in range(reps):
        s = []
        for _ in range(nb):
            st = rnd.randrange(n)
            s.extend(x[(st + i) % n] for i in range(block))
        mb = S.mean(s[:n])
        if mb - m >= m:
            cnt += 1
    return round((cnt + 1) / (reps + 1), 4)


def win_stats(g, b, a, z):
    ks = [k for k in g if k in b and a <= k <= z]
    return es(g, b, a, z) if len(ks) >= 24 else short_stats(g, b, a, z)


def contrib(J, base, rule, K, a, z, univ=C16):
    """訓練期間の国ごとの寄与（選ばれた年の 重み×(国のリターン − 相手)）"""
    out = {}
    for Y in range(a - 1, z):
        w = select(rule, J, base, univ, Y, K)
        UY = [c for c in univ if J.r(base, c, Y) is not None]
        bv = [J.r(base, c, Y + 1) for c in UY if J.r(base, c, Y + 1) is not None]
        if w is None or not bv:
            continue
        bm = sum(bv) / len(bv)
        rr = {c: (J.cash(Y + 1) if c == 'CASH' else J.r(base, c, Y + 1)) for c in w}
        ok = {c: x for c, x in w.items() if rr[c] is not None}
        t = sum(ok.values())
        for c, x in ok.items():
            out[c] = out.get(c, 0.0) + x / t * (rr[c] - bm)
    return {c: round(v * 100, 1) for c, v in sorted(out.items(), key=lambda kv: -kv[1])}


def part2(J, ev, fam, pA):
    """事前登録2（out/mw_deep_history_prereg2.json）: 頑健性の6本の格付けと報告"""
    RB = [('RB1_VALLAG_K3', 'VALLAG', 3), ('RB2_VALLAG_K5', 'VALLAG', 5), ('RB3_MOMSKIP_K3', 'MOMSKIP', 3),
          ('RB4_MOMSKIP_K5', 'MOMSKIP', 5), ('RB5_VMLAG_K3', 'VMLAG', 3), ('RB6_VMLAG_K5', 'VMLAG', 5)]
    rb = {sid: eval_jst(J, sid, 'H', rule, K, False) for sid, rule, K in RB}
    p44 = dict(pA)
    for sid, e in rb.items():
        p44[sid] = e['hold_net']['p'] if e.get('hold_net') else None
    h44 = M.holm(p44)
    for sid, e in rb.items():
        e['family'] = 'RB'
        e['holm_p'] = h44.get(sid)
        e['holm_scope'] = '第1族38本＋第2族6本＝44本'
        e['grade'], e['criteria'] = grade_jst(e, e['holm_p'])
    rep = {}
    S_RULES = [('P1_VAL_K3', 'H', 'VAL', 3), ('P3_MOM_K3', 'H', 'MOM', 3), ('P4_MOM_K5', 'H', 'MOM', 5), ('P5_VM_K3', 'H', 'VM', 3),
               ('P6_VM_K5', 'H', 'VM', 5), ('U1_VAL_K3', 'U', 'VAL', 3), ('U2_VAL_K5', 'U', 'VAL', 5), ('U4_MOM_K5', 'U', 'MOM', 5),
               ('U5_VM_K3', 'U', 'VM', 3), ('U6_VM_K5', 'U', 'VM', 5), ('X1_CARRY_K5', 'H', 'CARRY', 5), ('X3_VMRANK_K5', 'H', 'VMRANK', 5)]
    loo, halves, boot, nowar = {}, {}, {}, {}
    WAR = set(range(1914, 1920)) | set(range(1939, 1947))
    for sid, base, rule, K in S_RULES:
        rows = []
        for c in C16:
            R = run_rule(J, base, rule, K, [x for x in C16 if x != c])
            t, h = es(R['gross'], R['bench'], None, T_END), es(R['gross'], R['bench'], H_START, None)
            rows.append((c, t['ex_ann'] if t else None, t['t'] if t else None, h['ex_ann'] if h else None, h['t'] if h else None))
        ok = [r for r in rows if r[2] is not None and r[4] is not None]
        loo[sid] = {'train_ex_min': min(r[1] for r in ok), 'train_t_min': min(r[2] for r in ok), 'train_t_max': max(r[2] for r in ok),
                    'hold_ex_min': min(r[3] for r in ok), 'hold_t_min': min(r[4] for r in ok), 'hold_t_max': max(r[4] for r in ok),
                    'worst_drop_train': min(ok, key=lambda r: r[2])[0], 'worst_drop_hold': min(ok, key=lambda r: r[4])[0],
                    'rows': rows}
        R = ev[sid]['_series']
        g, b = R['gross'], R['bench']
        halves[sid] = {'1872_1898': win_stats(g, b, 1872, 1898), '1899_1925': win_stats(g, b, 1899, 1925)}
        xt = [g[k] - b[k] for k in sorted(g) if k in b and k <= T_END]
        xh = [g[k] - b[k] for k in sorted(g) if k in b and k >= H_START]
        boot[sid] = {'train_p_one_sided': block_boot_p(xt), 'hold_p_one_sided': block_boot_p(xh)}
        g2 = {k: v for k, v in g.items() if k not in WAR}
        nowar[sid] = {'train': es(g2, b, None, T_END), 'hold': es(g2, b, H_START, None)}
    rep['R1_leave_one_out'] = loo
    rep['R2_halves'] = halves
    rep['R3_bootstrap'] = boot
    rep['R4_no_war'] = nowar
    R5 = ev['P5_VM_K3']['_series']
    yrs = sorted((k for k in R5['gross'] if k <= T_END), key=lambda k: -(R5['gross'][k] - R5['bench'][k]))[:5]
    rep['R5_contrib'] = {'top_years': [(k, round((R5['gross'][k] - R5['bench'][k]) * 100, 1), R5['picks'][k]) for k in yrs],
                         'country_contrib_train_pct_sum': contrib(J, 'H', 'VM', 3, 1872, T_END),
                         'country_contrib_hold_pct_sum': contrib(J, 'H', 'VM', 3, H_START, 2020)}
    try:
        mc = json.load(open(os.path.join(M.BASE, 'out', 'mw_country.json')))
        tt = {x['id']: x for x in mc['tested']}
        cc = {}
        for i in ['P1_mom12_K3', 'P2_mom12_K5', 'P3_bm_K3', 'P4_bm_K5', 'E2_dp_K3', 'E2_dp_K5', 'E6_mom12_K3', 'E6_bm_K3', 'E6_bm_K5']:
            x = tt.get(i)
            if not x:
                continue
            st = x.get('stats', {})
            f = lambda s: {kk: s.get(kk) for kk in ('from', 'to', 'ex_ann', 't', 'cagr_diff')} if s else None
            cc[i] = {'grade': x.get('grade'), 'universe': x.get('universe'), 'benchmark': x.get('benchmark'),
                     'train': f(st.get('train')), 'hold': f(st.get('hold')), 'hold_net': f(st.get('hold_net')), 'post_pub': f(st.get('post_pub'))}
        rep['R6_modern_crosscheck_from_mw_country'] = cc
    except Exception as ex:  # noqa
        rep['R6_modern_crosscheck_from_mw_country'] = {'error': str(ex)}
    f = lambda s: (s['ex_ann'], s['t']) if s else None
    rep['R7_bsv_recent'] = {k: {'grade': e['grade'], '1926_2006': f(e.get('disc_1926_2006')), '2007_2016': f(e.get('h2007_2016')),
                                '2007_2016_net': f(e.get('h2007_2016_net'))} for k, e in ev.items() if fam[k] in ('B', 'BM')}
    return rb, rep, len(p44)


def conclusion(ev, fam, J, rep2):
    """結論の文（数字は ev から引く）"""
    g = lambda k, w, f='ex_ann': (ev[k].get(w) or {}).get(f)
    S_ = sorted(k for k, e in ev.items() if e['grade'] == 'S')
    A_ = sorted(k for k, e in ev.items() if e['grade'] == 'A')
    B_ = sorted(k for k, e in ev.items() if e['grade'] == 'B')
    c = []
    c.append(f"格付けした {len(ev)} 本（主8・副8・探索6・BSV 14・ハロウィーン2・頑健性6）: S {len(S_)} 本・A {len(A_)} 本・B {len(B_)} 本。"
             "S の内訳は JST の国の回転（割安・勢い・その両方・キャリー）と BSV の紙の上乗せ")
    c.append(f"★本当に独立の期間 1872〜1925 年でも、国の『割安（配当利回り）＋勢い』を半分ずつ（上位3か国）は等分の相手に "
             f"+{g('P5_VM_K3','train')}%/年（t{g('P5_VM_K3','train','t')}）、1926〜2020 年も +{g('P5_VM_K3','hold')}%/年（t{g('P5_VM_K3','hold','t')}）勝った。"
             "1か国を抜いても・戦争の年を抜いても・ブロック・ブートストラップでも残る")
    c.append(f"★だが 2007〜2020 年は国の回転のすべての規則が負けた（VM 上位3か国 {g('P5_VM_K3','h2007_2020')}%/年 t{g('P5_VM_K3','h2007_2020','t')}・"
             f"割安 上位3か国 {g('P1_VAL_K3','h2007_2020')}%/年 t{g('P1_VAL_K3','h2007_2020','t')}・14年中 3〜7年しか勝たない）。"
             "ALS 1997 の公表後（1998〜2020）も −0.3〜−0.7%/年。mw_country の月次の現代のデータ（2007〜2025）でも国の勢い・割安は先進国の時価加重に −1.1〜−1.4%/年（EAFE の中では +0.5%/年前後・t<0.6）＝同じ向き。"
             "S はこの角度の事前登録の割り当て（保有 = 1926〜2020・うち2007年以降は14年）での格付けで、全体の標準の保有（2007〜）なら C2 で落ちる")
    c.append(f"頑健性: 配当利回りを1年古い値にすると上乗せは約半分（保有 +{g('RB1_VALLAG_K3','hold')}%/年 t{g('RB1_VALLAG_K3','hold','t')}）、"
             f"勢いを1年飛ばすと符号が逆（保有 {g('RB3_MOMSKIP_K3','hold')}%/年 t{g('RB3_MOMSKIP_K3','hold','t')}）＝勝ちは直近1年の値に頼る。"
             "1925 年以前の国の相対リターンの1年の自己相関は中央 +0.15（ならされた指数の疑い）で、勢いの一部が偽物である可能性は消せない")
    c.append(f"BSV（紙・買い−売り・空売り要）: 株価指数のトレンドを株に半分重ねると 1800〜1925 +{g('B1_TREND','train')}%/年 t{g('B1_TREND','train','t')}・"
             f"1926〜2016 +{g('B1_TREND','hold')}%/年。ただし 2007〜2016 は +{g('B1_TREND','h2007_2016')}%/年 t{g('B1_TREND','h2007_2016','t')}。"
             "1925 年以前の数字は論文の著者が公表済みの『前の標本』で、この mw には新しいが学界には新しくない。mw_overlay の reality_gap では、実在のトレンド・ファンドを株に重ねた 2007 年以降の上乗せは年 +0.7〜0.9%（t≈0.8〜0.9）で 2008 年と 2022 年を抜くとほぼ 0、しかも日本の個人の NISA では買えない")
    c.append(f"ハロウィーン1.5倍（米国）は 1871〜1925 年で +{g('Z1_HAL_OV15','train')}%/年 t{g('Z1_HAL_OV15','train','t')}＝C1 で落ち、mw_calendar の S を独立の昔の期間では確かめられなかった")
    return {'conclusion_ja': c,
            'deviations': [
                'mw_common.rolling / dca は月次（と日次）のキーを前提にしていて年次のキーに対応しない → 同じ定義の年次版を自前で（事前登録どおり）',
                'mw_common.excess_stats は年次で24年未満だと値を返さない → 2007〜2020（14年）と 1998〜2020 は自前の短い窓の要約（NW ラグ1）',
                '全体の訓練（〜2006）/保有（2007〜）を、年次の JST・BSV・ハロウィーンでは事前登録どおり割り当て直した（C1 = 1925 年以前）',
                'Holm は費用後の保有期間の p で掛けた（厳しい側）',
                'mw_common に不具合は見つからなかった（rolling の年次非対応は仕様の範囲）'],
            'caveats': [
                'S はこの角度の割り当て（保有 = 1926〜2020）での格付け。全体の標準の保有期間（2007〜）に当たる 2007〜2020 はすべての国の回転が負け（t 約 −2〜−3）',
                '国の生き残りの偏り: JST は市場が消えた・崩れた国（ロシア・中国・オーストリア＝ハンガリー・アルゼンチン）を含まない。割安の国選びはこうした国を拾いやすいので、上乗せは上振れしうる',
                '物価上昇率100%以上の年・戦時の欠け（DEU 1945〜49 など）は戦略と相手の両方から外した＝最悪の年が抜けている',
                '年次・16か国・初期は銘柄の少ない指数。1925 年以前の勢いはならされた指数の自己相関で作られた分がありうる',
                'VM 上位3か国の 1925 年以前の上乗せの半分強は日本（1886〜1925）の寄与。割安 上位3か国は日本を抜くと訓練の t が 1.09 に落ちる',
                '米国だけを相手にすると、VM 上位3か国は 1872〜1925 +1.8%/年 t0.95・1926〜2020 +2.65%/年 t1.61・2007〜2020 −4.9%/年 t−2.6',
                'BSV の上乗せは紙（費用前の系列・空売りと先物が要る・1925 年以前は実行不能）。個人の NISA では作れない'],
            'n_S': len(S_), 'n_A': len(A_), 'n_B': len(B_)}


def main():
    if '--check' in sys.argv:
        check_only()
        return
    D = jst()
    J = JST(D)
    B = bsv()
    m, rf, src, sh, ff = us_monthly()

    # ── 検算 ──
    sanity = {}
    mk = ff['mkt']
    sanity['french_mkt_cagr_1926'] = round(M.cagr(mk) * 100, 2)
    sanity['french_mkt_cagr_2007'] = round(M.cagr(M.window(mk, 200701)) * 100, 2)
    fy = {}
    for k, v in mk.items():
        fy.setdefault(k // 100, []).append(v)
    fr_ann = {y: math.prod(1 + x for x in v) - 1 for y, v in fy.items() if len(v) == 12}
    shy = {}
    for k, v in sh.items():
        shy.setdefault(k // 100, []).append(v)
    sh_ann = {y: math.prod(1 + x for x in v) - 1 for y, v in shy.items() if len(v) == 12}
    jus = {y: J.g('USA', y, 'eq_tr') for y in range(1871, 2021) if J.g('USA', y, 'eq_tr') is not None}
    ys = [y for y in range(1927, 2021) if y in fr_ann and y in jus]
    sanity['jst_usa_vs_french_1927_2020'] = {'corr': round(M.corr([jus[y] for y in ys], [fr_ann[y] for y in ys]), 3),
                                             'cagr_jst': round(M.cagr([jus[y] for y in ys], 1) * 100, 2), 'cagr_french': round(M.cagr([fr_ann[y] for y in ys], 1) * 100, 2), 'n': len(ys)}
    ys = [y for y in range(1872, 1926) if y in sh_ann and y in jus]
    sanity['jst_usa_vs_shiller_1872_1925'] = {'corr': round(M.corr([jus[y] for y in ys], [sh_ann[y] for y in ys]), 3),
                                              'cagr_jst': round(M.cagr([jus[y] for y in ys], 1) * 100, 2), 'cagr_shiller': round(M.cagr([sh_ann[y] for y in ys], 1) * 100, 2), 'n': len(ys)}
    sanity['bsv_eq_fullsample_mean_x12'] = {st: round(S.mean(B[(st, 'EQ')].values()) * 12 * 100, 2) for st in STYLES}
    sanity['bsv_file_summary_equities'] = {'Trend': 9.19, 'Momentum': 5.83, 'Value': 2.18, 'Carry': 6.09, 'Seasonal': 5.53, 'BAB': 3.14}
    real = {}
    for Y in range(1871, 2021):
        v = []
        for c in C16:
            eq, inf = J.g(c, Y, 'eq_tr'), J.infl(c, Y)
            if eq is not None and inf is not None and inf < 1.0:
                v.append((1 + eq) / (1 + inf) - 1)
        if v:
            real[Y] = S.mean(v)
    sanity['ew_real_local_equity_arith_1871_2020'] = round(S.mean(real.values()) * 100, 2)
    sanity['ew_real_local_equity_arith_1871_2015'] = round(S.mean([v for y, v in real.items() if y <= 2015]) * 100, 2)
    sanity['valid_country_years'] = {b_: sum(1 for c in C16 for Y in range(1870, 2021) if J.r(b_, c, Y) is not None) for b_ in 'HU'}
    sanity['hyperinflation_excluded'] = [(c, Y) for c in C16 for Y in range(1871, 2021) if J.g(c, Y, 'eq_tr') is not None and J.infl(c, Y) is not None and J.infl(c, Y) >= 1.0]
    log('検算', json.dumps(sanity, ensure_ascii=False))

    # ── JST の族 ──
    RULES8 = [('1', 'VAL', 3, False), ('2', 'VAL', 5, False), ('3', 'MOM', 3, False), ('4', 'MOM', 5, False),
              ('5', 'VM', 3, False), ('6', 'VM', 5, False), ('7', 'AVOID1', None, False), ('8', 'TREND', None, True)]
    NAMES = {'VAL': 'VAL', 'MOM': 'MOM', 'VM': 'VM', 'AVOID1': 'AVOID1', 'TREND': 'TREND'}
    ev = {}
    fam = {}
    for i, rule, K, tim in RULES8:
        sid = f'P{i}_{rule}' + (f'_K{K}' if K else '')
        ev[sid] = eval_jst(J, sid, 'H', rule, K, tim); fam[sid] = 'P'
        sid = f'U{i}_{rule}' + (f'_K{K}' if K else '')
        ev[sid] = eval_jst(J, sid, 'U', rule, K, tim); fam[sid] = 'U'
    XR = [('X1_CARRY_K5', 'CARRY', 5, False), ('X2_REV5_K5', 'REV5', 5, False), ('X3_VMRANK_K5', 'VMRANK', 5, False),
          ('X4_AVOID3', 'AVOID3', None, False), ('X5_VALTREND_K5', 'VALTREND', 5, True), ('X6_RELDY_K5', 'RELDY', 5, False)]
    for sid, rule, K, tim in XR:
        ev[sid] = eval_jst(J, sid, 'H', rule, K, tim); fam[sid] = 'X'

    # ── BSV ──
    for asset, pre in (('EQ', 'B'), ('MA', 'BM')):
        for j, st in enumerate(STYLES + ['Multi'], 1):
            F = B[(st, asset)] if st != 'Multi' else bsv_multi(B, asset)
            sid = f'{pre}{j}_{ {"Trend": "TREND", "Momentum": "MOM", "Value": "VAL", "Carry": "CARRY", "Seasonal": "SEAS", "BAB": "BAB", "Multi": "MULTI"}[st] }'
            ev[sid] = eval_bsv(sid, F, st, m, rf); ev[sid]['asset'] = asset; fam[sid] = pre

    # ── ハロウィーン ──
    ev['Z1_HAL_OV15'] = eval_hal('Z1_HAL_OV15', 'OV15', m, rf); fam['Z1_HAL_OV15'] = 'Z'
    ev['Z2_HAL_SW'] = eval_hal('Z2_HAL_SW', 'SW', m, rf); fam['Z2_HAL_SW'] = 'Z'

    # ── Holm（費用後の保有期間の p） ──
    def hp(e):
        h = e.get('hold_net')
        return h['p'] if h else None
    pP = {k: hp(e) for k, e in ev.items() if fam[k] == 'P'}
    pA = {k: hp(e) for k, e in ev.items()}
    holmP, holmA = M.holm(pP), M.holm(pA)
    n_graded = len(ev)
    log('格付けする本数', n_graded)

    # ── 格付け ──
    for k, e in ev.items():
        hpv = holmP.get(k) if fam[k] == 'P' else holmA.get(k)
        e['family'] = fam[k]
        e['holm_p'] = hpv
        e['holm_scope'] = 'P の8本' if fam[k] == 'P' else f'全{n_graded}本'
        if fam[k] in ('P', 'U', 'X'):
            gr, cr = grade_jst(e, hpv)
            e['grade'], e['criteria'] = gr, cr
            # G2（逆の割り当て・報告）: Holm は同じ族の G2 の p で
            e['_g2'] = True
        else:
            gr, cr = grade_over(e, hpv)
            e['grade'], e['criteria'] = gr, cr
    # G2 の Holm（族ごと・報告）
    for F_ in ('P', 'U', 'X'):
        ps = {}
        for k, e in ev.items():
            if fam[k] == F_:
                R = e['_series']
                h = es(R['net'], R['bench'], None, T_END)
                ps[k] = h['p'] if h else None
        hh = M.holm(ps)
        for k in ps:
            g2, c2 = grade_jst(ev[k], hh.get(k), G2=True)
            ev[k]['grade_G2_report'] = {'grade': g2, 'criteria': c2, 'holm_p': hh.get(k),
                                        'mapping': 'C1=1926〜2006・保有=1870〜1925（報告のみ）'}

    # ── 報告: 欧州だけ・米国を除く ──
    robust = {}
    for i, rule, K, tim in RULES8:
        for nm, univ in (('europe13', EUROPE13), ('exus15', EXUS15)):
            R = run_rule(J, 'H', rule, K, univ)
            robust[f'P{i}_{rule}' + (f'_K{K}' if K else '') + '_' + nm] = {
                'train': es(R['gross'], R['bench'], None, T_END), 'hold': es(R['gross'], R['bench'], H_START, None),
                'hold_net': es(R['net'], R['bench'], H_START, None)}
    # 米国だけ vs 等分
    us_vs = {}
    for base in 'HU':
        R = run_rule(J, base, 'EW', None)
        usa = {y: J.r(base, 'USA', y) for y in R['bench'] if J.r(base, 'USA', y) is not None}
        gb = gdp_bench(J, base)
        us_vs[base] = {'usa_vs_ew_train': es(usa, R['bench'], None, T_END), 'usa_vs_ew_hold': es(usa, R['bench'], H_START, None),
                       'gdpw_vs_ew_train': es(gb, R['bench'], None, T_END), 'gdpw_vs_ew_hold': es(gb, R['bench'], H_START, None),
                       'ew_cagr_train': round(M.cagr(M.window(R['bench'], None, T_END), 1) * 100, 2),
                       'ew_cagr_hold': round(M.cagr(M.window(R['bench'], H_START), 1) * 100, 2),
                       'ew_strategy_minus_bench_maxabs': max(abs(R['gross'][y] - R['bench'][y]) for y in R['gross'])}
    # ハロウィーンの半月ずらし（診断）
    hal_diag = {k: {kk: vv for kk, vv in eval_hal(k, kind, m, rf, (12, 1, 2, 3, 4, 5)).items() if kk in ('train', 'hold', 'full')}
                for k, kind in (('Z1_shift_DecMay', 'OV15'), ('Z2_shift_DecMay', 'SW'))}
    # BSV の生の系列（期間ごと）
    raw = {}
    for asset in ('EQ', 'MA'):
        for st in STYLES + ['Multi']:
            F = B[(st, asset)] if st != 'Multi' else bsv_multi(B, asset)
            zero = {k: 0.0 for k in F}
            raw[f'{st}_{asset}'] = {'1800_1925': M.excess_stats(F, zero, 180001, 192512), '1926_2006': M.excess_stats(F, zero, 192601, 200612),
                                    '2007_2016': M.excess_stats(F, zero, 200701, 201612)}

    # ── 第2族（事前登録2・頑健性） ──
    rb, rep2, n44 = part2(J, ev, fam, pA)
    for k, e in rb.items():
        ev[k] = e; fam[k] = 'RB'
    n_graded = n44
    log('第2族を足した後の格付けの本数', n_graded)

    # ── 先読みの検算 ──
    specs = [(f'P{i}', 'H', rule, K, C16) for i, rule, K, tim in RULES8] + [(f'U{i}', 'U', rule, K, C16) for i, rule, K, tim in RULES8] + \
            [(sid, 'H', rule, K, C16) for sid, rule, K, tim in XR] + \
            [(s_, 'H', r_, k_, C16) for s_, r_, k_ in (('RB1', 'VALLAG', 3), ('RB3', 'MOMSKIP', 3), ('RB5', 'VMLAG', 5))]
    la = lookahead_check(J, specs)
    sanity['lookahead_truncation_check'] = la
    log('先読みの検算', la)

    # ── まとめ ──
    tested = []
    for k, e in ev.items():
        h, hn, t = e.get('hold'), e.get('hold_net'), e.get('train')
        tested.append({'id': k, 'family': fam[k], 'grade': e['grade'],
                       'train_ex': t['ex_ann'] if t else None, 'train_t': t['t'] if t else None,
                       'hold_ex': h['ex_ann'] if h else None, 'hold_t': h['t'] if h else None,
                       'hold_net_ex': hn['ex_ann'] if hn else None, 'hold_net_cagr_diff': hn['cagr_diff'] if hn else None,
                       'full_ex': e['full']['ex_ann'] if e.get('full') else None, 'full_t': e['full']['t'] if e.get('full') else None,
                       'roll20_win': e['roll20']['win_rate'] if e.get('roll20') else None,
                       'holm_p': e['holm_p']})
        log(f"{k:18s} {e['grade']}  訓練 {t['ex_ann'] if t else None}%/年 t{t['t'] if t else None} ／ 保有 {h['ex_ann'] if h else None} t{h['t'] if h else None} "
            f"費用後 {hn['ex_ann'] if hn else None} 幾何差 {hn['cagr_diff'] if hn else None} ／ 20年窓 {e['roll20']['win_rate'] if e.get('roll20') else None} Holm {e['holm_p']}")
    out = {'angle': 'deep_history', 'prereg': PREREG, 'prereg_commit': git_sha(PREREG),
           'prereg2': PREREG2, 'prereg2_commit': git_sha(PREREG2),
           'n_tested_graded': n_graded, 'tested': tested,
           'strategies': {k: strip(e) for k, e in ev.items()},
           'report_robust_subsets': robust, 'report_usa_gdp_vs_ew': us_vs, 'report_halloween_shift': hal_diag,
           'report_bsv_raw_factors': raw, 'report_part2': rep2, 'sanity': sanity, 'log': LOG}
    # JST の系列（年次）を小さく残す: 主の族だけ
    out['series_primary'] = {k: {'gross': ev[k]['_series']['gross'], 'bench': ev[k]['_series']['bench'], 'turn': ev[k]['_series']['turn']}
                             for k in ev if fam[k] == 'P'}
    out.update(conclusion(ev, fam, J, rep2))
    p = M.save(OUT, out)
    log('書いた', p, os.path.getsize(p))


if __name__ == '__main__':
    main()
