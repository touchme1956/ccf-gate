#!/usr/bin/env python3
"""night/edge/r9_taxable_lev.py — 第9回 C_taxable_leverage（事前登録 out/edge_prereg_r9.json）

NISA を使い切った後の課税口座（特定口座）での毎月同額の積立に、控えめな倍率を使うと 1倍の持ち続けより手取りが増えるか。
判定ではなく計画の材料（事前登録）。読むだけ・門の採点に不使用。凍結した spec・fam_*.py は変えない（import だけ）。

  指数   S&P500 の代わり＝Ken French の日次の米国市場（Mkt-RF＋RF・配当込み）／NASDAQ-100＝^NDX 日次（Yahoo・価格だけ・配当は無し）
  金利   French の日次 RF（NDX の日付にも前の値を引き継いで当てる）。窓の終わりは French の最後の日 2026-08-31
  為替   FRED DEXJPUS（日次・無い日は前の値）
  ① 1倍の持ち続け（経費0）
  ② 1.25倍・1.5倍（参考 2倍）の毎日リセット（fam_levtrend._lev＝h.lev_daily：借りた分に rf+0.4%/年・経費0.9%/年）を持ち続け
  ③ 1.5倍＋200日平均（fam_levtrend.positions・d200）：上なら1.5倍、下なら1倍へ乗り換え（売って買う＝課税）。
     主は1営業日遅れ（delay=1＝日本から執行できる形）、delay=0 を併記。乗り換えのたびに売った額の 0.1%（凍結の費用）
  ④ 1.5倍＋ぶれ目標（spec_voltarget.json の凍結の中身＝前日までの63営業日のぶれで『その時点までの全期間の平均のぶれ』を割る・
     scale=vol・月1回）の上限だけ事前登録どおり 1.5 にする。w≤1: 1倍を w・残りを短期金利（MMF）／w>1: 1.5倍型を 2(w−1)・1倍を残り。
     月初の積立の日に組み替え（信号は前日の終値まで）。売った額の 0.1%
  税     特定口座：売るたびに円で測った売却益（総平均法）に 20.315%、同じ暦年の損益は通算（源泉徴収で年の中の累計に合わせて徴収・還付）。
         損失の繰越は無し（事前登録）。窓の最後に全部売って清算。配当課税は入れていない（事前登録の範囲外・下の⚠）
  積立   毎月の最初の取引日の終値で 1円ぶん（比しか見ないので額は効かない）をドルに替えて入れる。240回。窓の終わり＝240か月目の最後の取引日
  窓     20年の転がる窓。開始 1986-11（NDX の200日平均とぶれ目標の履歴がそろう月）〜2006-09。『1986年以降』＝全部／『2001年以降』＝2001-01〜
  物差し 税の後の最終額の比（対①）の中央・最悪・最良・1を超えた窓の割合／最大下落（戦略の1単位の値・税の前・ドルと円）
  実物   QLD（2倍 NDX）・SSO（2倍 S&P500）・QQQ・SPY の Yahoo 日次 adjclose で 2006-07〜2026-08 の積立（1窓）と転がる10年

判定の線は事前登録に無いので、結果を見る前にこのファイルの verdict() で決めた（下）。
全期間を読むので EDGE_PHASE=holdout で走らせる。
"""
import os, sys, json, math, time, csv, io, datetime, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if os.environ.get('EDGE_PHASE') != 'holdout':
    sys.exit('EDGE_PHASE=holdout で走らせる')
import harness as h
import fam_levtrend as fl
import fam_voltarget as fv

OUT = os.path.join(h.BASE, 'out', 'edge', 'r9_taxable_lev.json')
TAX = 0.20315
COST = 0.001
END = 20260831
W0, W1 = 198611, 200609          # 20年窓の開始月
SPLIT = 200101
NM = 240


# ───────────────────────── データ ─────────────────────────
def yahoo_daily(sym):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2={int(time.time())}&interval=1d'
    j = json.loads(h.cached(f'yhdp_{sym}.json', url, 30))
    res = j['chart']['result'][0]
    gmt = (res.get('meta') or {}).get('gmtoffset') or 0
    ind = res['indicators']
    ser = (ind.get('adjclose') or [{}])[0].get('adjclose') or ind['quote'][0]['close']
    o = {}
    for t, v in zip(res['timestamp'], ser):
        if v is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t + gmt)
        o[d.year * 10000 + d.month * 100 + d.day] = float(v)
    return o


def px_to_ret_d(px):
    ks = sorted(px)
    return {b: px[b] / px[a] - 1 for a, b in zip(ks, ks[1:])}


def fx_daily():
    raw = h.cached('fred_DEXJPUS.csv', 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', 20).decode()
    o = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) < 2 or row[1] in ('.', ''):
            continue
        o[int(row[0].replace('-', ''))] = float(row[1])
    return o


def ffill(src, keys):
    ks = sorted(src)
    out, j, last = {}, 0, None
    for k in keys:
        while j < len(ks) and ks[j] <= k:
            last = src[ks[j]]; j += 1
        out[k] = last
    return out


# ───────────────────────── 口座（特定口座） ─────────────────────────
class Account:
    """ドル建ての口数と円の取得原価（総平均法）。売るたびに暦年の累計損益に合わせて源泉徴収・還付"""
    def __init__(self, tax=TAX):
        self.u, self.basis, self.cash = {}, {}, 0.0
        self.year, self.R, self.T, self.tax = None, 0.0, 0.0, tax
        self.taxpaid = 0.0

    def _yr(self, d):
        y = d // 10000
        if y != self.year:
            self.year, self.R, self.T = y, 0.0, 0.0

    def sell(self, f, usd, nav, fx, d, cost):
        self._yr(d)
        hold = self.u.get(f, 0.0) * nav
        if hold <= 0 or usd <= 0:
            return
        usd = min(usd, hold)
        frac = usd / hold
        b = self.basis[f] * frac
        self.basis[f] -= b
        self.u[f] -= usd / nav
        proceeds = usd * (1 - cost)
        self.R += proceeds * fx - b
        due = self.tax * max(0.0, self.R)
        delta = due - self.T
        self.T = due
        self.taxpaid += delta
        self.cash += proceeds - delta / fx

    def buy(self, f, usd, nav, fx):
        if usd <= 0:
            return
        self.u[f] = self.u.get(f, 0.0) + usd / nav
        self.basis[f] = self.basis.get(f, 0.0) + usd * fx
        self.cash -= usd

    def value(self, navs):
        return sum(self.u[f] * navs[f] for f in self.u) + self.cash

    def rebalance(self, w, navs, fx, d, cost):
        V = self.value(navs)
        for f in list(self.u):
            tgt = w.get(f, 0.0) * V
            hv = self.u[f] * navs[f]
            if hv > tgt + 1e-12 * max(V, 1e-9):
                self.sell(f, hv - tgt, navs[f], fx, d, cost)
        V = self.value(navs)
        defs = {f: max(0.0, w[f] * V - self.u.get(f, 0.0) * navs[f]) for f in w}
        tot = sum(defs.values())
        if tot <= 0 or self.cash <= 0:
            return
        k = min(1.0, self.cash / tot)
        for f, x in defs.items():
            self.buy(f, x * k, navs[f], fx)

    def liquidate(self, navs, fx, d):
        for f in list(self.u):
            if self.u[f] > 0:
                self.sell(f, self.u[f] * navs[f], navs[f], fx, d, 0.0)
        return self.cash * fx


# ───────────────────────── 戦略 ─────────────────────────
def build_index(r, rf_all, dates):
    """dates: この指数の取引日。→ funds の日次 NAV（その日の終値の後）"""
    rf = ffill(rf_all, dates)
    r = {d: r[d] for d in dates}
    funds = {'1x': r, 'cash': rf}
    for L in (1.25, 1.5, 2.0):
        funds[f'L{L}'] = fl._lev(r, rf, L, 0.004, 0.009)
    nav = {}
    for f, ser in funds.items():
        v, o = 1.0, []
        for d in dates:
            v *= 1 + ser[d]
            o.append(v)
        nav[f] = o
    return nav, r, rf


def policies(dates, r, rf):
    """各戦略: {'events': {日の添字: 目標の重み}, 'contrib_w': 関数(添字)->重み}"""
    idx = {d: i for i, d in enumerate(dates)}
    first = {}
    for i, d in enumerate(dates):
        first.setdefault(d // 100, i)
    P = {}
    for f in ('1x', 'L1.25', 'L1.5', 'L2.0'):
        P[{'1x': '①1倍', 'L1.25': '②1.25倍', 'L1.5': '②1.5倍', 'L2.0': '②2倍（参考）'}[f]] = ('hold', {f: 1.0})
    # ③ 200日平均
    for dl in (1, 0):
        spec = dict(fl.DEFAULT); spec.update({'L': 1.5, 'signal': 'd200', 'out': '1x', 'delay': dl})
        pos = fl.positions(dates, r, rf, spec)
        # 添字 j の終値で、j+1 日の持ち高 pos[j+1] に合わせる
        tgt = {}
        for j in range(len(dates) - 1):
            p = pos[j + 1]
            if p is None:
                continue
            tgt[j] = {'L1.5': 1.0} if p == 1 else {'1x': 1.0}
        P[f'③1.5倍＋200日平均（{"1営業日遅れ" if dl else "遅れなし"}）'] = ('switch', tgt)
    # ④ ぶれ目標（凍結の voltarget の中身・上限だけ 1.5）
    vs = json.load(open(os.path.join(h.BASE, 'out', 'edge', 'spec_voltarget.json')))['spec']
    vs = dict(vs); vs['cap'] = 1.5
    x = [r[d] - rf[d] for d in dates]
    cum = fv._signal_tools(dates, x)
    vt = {}
    for m, i in first.items():
        w = fv.weight_at(i, vs, dates, cum)       # 前日の終値まで
        if w is None:
            continue
        vt[i] = ({'1x': w, 'cash': 1 - w} if w <= 1 else {'L1.5': 2 * (w - 1), '1x': 1 - 2 * (w - 1)}, w)
    P['④1.5倍＋ぶれ目標'] = ('vol', vt)
    return P, first


_CHG = {}


def simulate(kind, pol, nav, dates, fxd, first, s, tax=TAX, contrib=True, last_idx=None):
    """開始月 s から240か月の積立。→ (税の後の円, 税の前の円, 払った税の円, 積んだ円)"""
    acc = Account(tax)
    months = [h.add_months(s, k) for k in range(NM)]
    end_m = months[-1]
    if last_idx is None:
        nxt = h.add_months(end_m, 1)
        last_idx = (first[nxt] - 1) if nxt in first else len(dates) - 1
    cidx = {first[m] for m in months}
    i0 = first[s]
    navs = lambda i: {f: nav[f][i] for f in nav}
    cur = None
    if kind == 'switch':
        ch = _CHG.get(id(pol))
        if ch is None:
            ch = _CHG[id(pol)] = sorted(j for j in pol if (j - 1) not in pol or pol[j] != pol[j - 1])
        evs = sorted(set(k for k in ch if i0 <= k <= last_idx) | cidx)
    else:
        evs = sorted(cidx)
    for i in evs:
        fx = fxd[dates[i]]
        nv = navs(i)
        if kind == 'hold':
            w = pol
        elif kind == 'switch':
            if i in pol:
                cur = pol[i]
            if cur is None:
                raise RuntimeError('信号がそろわない')
            w = cur
        else:
            w = pol[i][0]
        if i in cidx:
            acc.cash += 1.0 / fx
        cost = 0.0 if kind == 'hold' else COST
        acc.rebalance(w, nv, fx, dates[i], cost)
    fx = fxd[dates[last_idx]]
    nv = navs(last_idx)
    pre = acc.value(nv) * fx
    # 税の前＝清算せず・源泉された税も戻さない値ではなく「税率0で同じ売買をした値」を別に出す
    post = acc.liquidate(nv, fx, dates[last_idx])
    return post, acc.taxpaid


def unit_series(kind, pol, nav, dates, i0, i1):
    """戦略の1単位の値（税の前・ドル）：i0 に 1 を入れ、同じ売買（費用込み・税0）で i1 まで。日次"""
    acc = Account(0.0)
    acc.cash = 1.0
    cur = None
    out = []
    for i in range(i0, i1 + 1):
        nv = {f: nav[f][i] for f in nav}
        w = None
        if kind == 'hold':
            if i == i0:
                w = pol
        elif kind == 'switch':
            if i in pol and pol[i] != cur:
                cur = pol[i]; w = cur
            elif i == i0:
                w = cur
        else:
            if i in pol:
                w = pol[i][0]
        if w is not None:
            acc.rebalance(w, nv, 1.0, 20000101, 0.0 if kind == 'hold' else COST)
        out.append(acc.value(nv))
    return out


def mdd(v):
    pk, dd = v[0], 0.0
    for x in v:
        pk = max(pk, x); dd = min(dd, x / pk - 1)
    return dd


def q(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    a = int(math.floor(k)); b = min(a + 1, len(xs) - 1)
    return xs[a] + (xs[b] - xs[a]) * (k - a)


def summarize(vals):
    return {'n': len(vals), '中央': round(S.median(vals), 3), '最悪': round(min(vals), 3), '下位10%': round(q(vals, 0.1), 3),
            '最良': round(max(vals), 3), '1を超えた窓': f'{sum(v > 1 for v in vals)}/{len(vals)}'}


def run_index(name, r_all, rf_all, fxd_src, dates):
    nav, r, rf = build_index(r_all, rf_all, dates)
    fxd = ffill(fxd_src, dates)
    P, first = policies(dates, r, rf)
    starts = [m for m in h.month_range(W0, W1)]
    res, raw = {}, {}
    for nm, (kind, pol) in P.items():
        post, taxes = [], []
        for s in starts:
            a, t = simulate(kind, pol, nav, dates, fxd, first, s)
            post.append(a); taxes.append(t)
        raw[nm] = post
        res[nm] = {'_post': post, '_tax': taxes}
    base = raw['①1倍']
    out = {}
    for nm in P:
        kind, pol = P[nm]
        ratio = [a / b for a, b in zip(raw[nm], base)]
        mult = raw[nm]                                   # 積んだ240円に対する税の後の倍率×240
        pre_idx = [i for i, s in enumerate(starts) if s < SPLIT]
        post_idx = [i for i, s in enumerate(starts) if s >= SPLIT]
        # 最大下落（1単位・税の前）：全期間（1986-11〜）と 2001〜、ドルと円
        i0 = first[W0]; i2001 = first[SPLIT]; i1 = len(dates) - 1
        u = unit_series(kind, pol, nav, dates, i0, i1)
        uy = [x * fxd[dates[i0 + k]] for k, x in enumerate(u)]
        u01 = u[i2001 - i0:]
        uy01 = uy[i2001 - i0:]
        # 窓の中の最大下落（ドル・1単位）の中央と最悪
        wdd = []
        for s in starts:
            a = first[s]; e = first.get(h.add_months(s, NM), len(dates)) - 1
            wdd.append(mdd(u[a - i0:e - i0 + 1]))
        cg = lambda v, a, b: (v[b] / v[a]) ** (252 / (b - a)) - 1
        o = {
            '税の後の最終額の比（対①）': {'1986年以降に始まる窓（全部）': summarize(ratio),
                                         '1986-11〜2000-12 に始まる窓': summarize([ratio[i] for i in pre_idx]),
                                         '2001年以降に始まる窓': summarize([ratio[i] for i in post_idx])},
            '税の後の倍率（積んだ円に対して）': {'全部': summarize([x / NM for x in mult]),
                                             '2001年以降': summarize([mult[i] / NM for i in post_idx])},
            '払った税（最終額に対する割合の中央）': round(S.median(t / (a + t) for a, t in zip(res[nm]['_post'], res[nm]['_tax'])) * 100, 1),
            '最大下落（1単位・税の前・日次）': {'1986-11〜・ドル': round(mdd(u) * 100, 1), '1986-11〜・円': round(mdd(uy) * 100, 1),
                                             '2001〜・ドル': round(mdd(u01) * 100, 1), '2001〜・円': round(mdd(uy01) * 100, 1),
                                             '20年窓の中の最大下落（ドル）中央': round(S.median(wdd) * 100, 1),
                                             '20年窓の中の最大下落（ドル）最悪': round(min(wdd) * 100, 1)},
            '年率（1単位・税の前・ドル）': {'1986-11〜': round(cg(u, 0, len(u) - 1) * 100, 2), '2001〜': round(cg(u01, 0, len(u01) - 1) * 100, 2)},
        }
        if kind == 'switch':
            sw = sum(1 for j in pol if j >= i0 and j - 1 in pol and pol[j] != pol[j - 1])
            o['乗り換えの回数（1986-11〜・年あたり）'] = round(sw / ((i1 - i0) / 252), 2)
        if kind == 'vol':
            ws = [v[1] for i, v in pol.items() if i >= i0]
            o['ぶれ目標の倍率'] = {'平均': round(S.mean(ws), 3), '1.5の上限に当たった月の割合': round(sum(w >= 1.5 - 1e-9 for w in ws) / len(ws), 3),
                                '1未満の月の割合': round(sum(w < 1 for w in ws) / len(ws), 3)}
        out[nm] = o
    return out, starts


# ───────────────────────── 実物（QLD・SSO） ─────────────────────────
def real_products(fx_src):
    out = {}
    for one, two, nm in (('QQQ', 'QLD', 'NASDAQ-100'), ('SPY', 'SSO', 'S&P500')):
        p1, p2 = yahoo_daily(one), yahoo_daily(two)
        ds = sorted(d for d in set(p1) & set(p2) if d <= END)
        if not ds:
            out[nm] = '取れなかった'; continue
        # 信号用の1倍は上場来の全部（200日の履歴）
        d1 = sorted(d for d in p1 if d <= END)
        r1_all = px_to_ret_d({d: p1[d] for d in d1})
        dates = ds[1:]
        fxd = ffill(fx_src, dates)
        nav = {'1x': [p1[d] / p1[dates[0]] for d in dates], 'L2': [p2[d] / p2[dates[0]] for d in dates]}
        first = {}
        for i, d in enumerate(dates):
            first.setdefault(d // 100, i)
        # 200日平均（1倍の実物の adjclose で・前日までの終値）
        pos_all = fl.positions(d1[1:], r1_all, {d: 0.0 for d in d1[1:]},
                               dict(fl.DEFAULT, **{'L': 2.0, 'signal': 'd200', 'out': '1x', 'delay': 1}))
        pmap = dict(zip(d1[1:], pos_all))
        sw = {}
        for j in range(len(dates) - 1):
            p = pmap.get(dates[j + 1])
            if p is not None:
                sw[j] = {'L2': 1.0} if p == 1 else {'1x': 1.0}
        pols = {'①1倍（' + one + '）': ('hold', {'1x': 1.0}), '②2倍（' + two + '）持ち続け': ('hold', {'L2': 1.0}),
                '③2倍＋200日平均（1営業日遅れ・' + two + '/' + one + '）': ('switch', sw)}
        # 参考: 実物で1.5倍に近い形＝半分ずつを月1回合わせる
        pols['参考 ' + two + '半分＋' + one + '半分を毎月合わせる（≈1.5倍）'] = ('vol', {first[m]: ({'L2': 0.5, '1x': 0.5}, 1.5) for m in first})
        s0 = min(m for m in first if first[m] > 0 and m > dates[0] // 100)
        mlast = END // 100
        n_all = (mlast // 100 * 12 + mlast % 100) - (s0 // 100 * 12 + s0 % 100) + 1
        res = {'窓': f'{s0}〜{mlast}（{n_all}か月・1窓）', 'data': f'Yahoo 日次 adjclose {one} {two}（共通 {dates[0]}〜{dates[-1]}）'}
        base_full, base10 = None, None
        tbl = {}
        global NM
        keep = NM
        for pn, (kind, pol) in pols.items():
            NM = n_all
            a, t = simulate(kind, pol, nav, dates, fxd, first, s0)
            NM = 120
            st10 = [m for m in h.month_range(s0, h.add_months(mlast, -119))]
            r10 = [simulate(kind, pol, nav, dates, fxd, first, s)[0] for s in st10]
            NM = keep
            u = unit_series(kind, pol, nav, dates, 0, len(dates) - 1)
            tbl[pn] = {'_a': a, '_r10': r10, '税の後の倍率（積んだ円に対して）': round(a / n_all, 3),
                       '最大下落（1単位・税の前・日次・ドル）': round(mdd(u) * 100, 1),
                       '年率（1単位・税の前・ドル）': round(((u[-1] / u[0]) ** (252 / (len(u) - 1)) - 1) * 100, 2)}
        b = tbl['①1倍（' + one + '）']
        for pn in tbl:
            tbl[pn]['税の後の最終額の比（対①）'] = round(tbl[pn]['_a'] / b['_a'], 3)
            tbl[pn]['転がる10年の積立・税の後の比（対①）'] = summarize([x / y for x, y in zip(tbl[pn]['_r10'], b['_r10'])])
        for pn in tbl:
            tbl[pn].pop('_a'); tbl[pn].pop('_r10')
        res['結果'] = tbl
        out[nm] = res
    return out


# ───────────────────────── 判定（結果を見る前に決めた線） ─────────────────────────
VERDICT_RULE = ('事前登録に判定の線が無いので、結果を見る前にコードで決めた: 倍率を使う形（②1.25/1.5・③1営業日遅れ・④）のどれかが、'
                '両方の指数で『1986年以降の窓』と『2001年以降の窓』の両方で 税の後の比の中央>1 かつ 最悪≥0.9 かつ '
                '2001〜の最大下落（ドル）が①より5pt以上深くない → 『手取りが増える形がある』／中央>1 の形はあるが上の条件を満たさない → '
                '『リスクの代金に見合わない』／どれも中央≤1 → 『増えない』。②2倍と③遅れなしは参考で判定に入れない')
CANDS = ['②1.25倍', '②1.5倍', '③1.5倍＋200日平均（1営業日遅れ）', '④1.5倍＋ぶれ目標']


def verdict(res):
    ok, med_up = [], []
    for c in CANDS:
        good, up = True, True
        for ix in res:
            o = res[ix][c]; b = res[ix]['①1倍']
            for k in ('1986年以降に始まる窓（全部）', '2001年以降に始まる窓'):
                s = o['税の後の最終額の比（対①）'][k]
                up &= s['中央'] > 1
                good &= s['中央'] > 1 and s['最悪'] >= 0.9
            good &= o['最大下落（1単位・税の前・日次）']['2001〜・ドル'] >= b['最大下落（1単位・税の前・日次）']['2001〜・ドル'] - 5
        if good: ok.append(c)
        if up: med_up.append(c)
    v = '手取りが増える形がある' if ok else ('リスクの代金に見合わない' if med_up else '増えない')
    return v, ok, med_up


READING = [
    '②の持ち続け（1.25倍・1.5倍）は、税の後の比の中央が両方の指数で1を少し超える（全窓 1.02〜1.15）が、1986-2000 に始まる窓だけなら S&P 1.25倍 0.999・NDX 1.25倍 0.963・NDX 1.5倍 0.979＝ほぼ五分。上乗せは2001年以降に始まる窓（全部 2021〜2026 に終わる上げ相場）に偏る',
    '最悪の窓は①より 15〜34% 少ない手取り（S&P 1.5倍 0.761・NDX 1.5倍 0.664）で、最大下落は S&P −55%→−74%・NDX −83%→−95%（1.5倍）＝上乗せはリスクを増やした分',
    '③200日平均（1.5倍・日本から執行できる1営業日遅れ）は税の後に①へ負ける（中央 S&P 0.956・NDX 0.963／1を超えた窓は 1986-2000 開始で 9/170・8/170）。税の前の年率は①を上回る（S&P 12.29 vs 11.27・NDX 16.24 vs 14.29）ので、負けは年6〜7回の乗り換えで売却益に毎回課税される分（払った税は最終額の 17.7〜20.2% vs ① 12.9〜14.3%）と、乗り換えの費用',
    '④ぶれ目標は下落を浅くする（S&P −55%→−42%・NDX −83%→−63%）。NDX では 1986-2000 に始まる窓で中央 1.198（164/170 で①超え）だが、2001年以降に始まる窓は中央 0.927・最悪 0.844＝上げ相場の窓では現金に降りる月（32%）が負けになる。S&P では全窓 0.970・2001以降 0.761',
    '実物（2倍の QLD・SSO・2006-07〜2026-08 の1窓）は税の後に①の 4.37倍（QLD）・2.64倍（SSO）と大きく勝つが、これは NASDAQ-100 と S&P500 の上げ相場の一度きりの窓で、紙の上の 2倍を 1986年から転がすと NDX は中央 0.890・最悪 0.342（1986-2000 開始の窓）',
]


def main():
    fr_r, fr_rf = h.us_market_daily()
    fxs = fx_daily()
    ndx_px = yahoo_daily('^NDX')
    ndx_r = px_to_ret_d({d: v for d, v in ndx_px.items() if d <= END})
    last = min(max(fr_r), END)
    d_sp = sorted(d for d in fr_r if 19850101 <= d <= last)
    d_nd = sorted(d for d in ndx_r if d <= last)
    res = {}
    res['S&P500（French 米国市場・配当込み）'], starts = run_index('sp', fr_r, fr_rf, fxs, d_sp)
    res['NASDAQ-100（^NDX・配当なし）'], _ = run_index('ndx', ndx_r, fr_rf, fxs, d_nd)
    v, ok, up = verdict(res)
    rp = real_products(fxs)
    doc = {
        'key': 'C_taxable_leverage', 'round': 9, 'as_of': datetime.date.today().isoformat(),
        'prereg': 'out/edge_prereg_r9.json の C_taxable_leverage（判定ではなく計画の材料）',
        'verdict': v, 'verdict_rule': VERDICT_RULE, '条件を満たした形': ok, '中央>1 の形（両指数・両区分）': up,
        'method': {
            'data': {'S&P500': 'Ken French F-F_Research_Data_Factors_daily（Mkt-RF＋RF・配当込み）', 'NASDAQ-100': 'Yahoo ^NDX 日次の終値（価格指数・配当は入っていない）',
                     'rf': 'French 日次 RF（NDX の日付へ前の値を引き継ぐ）', 'fx': 'FRED DEXJPUS（日次・ニューヨーク正午・無い日は前の値）',
                     '期間の終わり': f'{last}（French の最後の日）', '窓の開始': f'{W0}〜{W1}（{len(starts)}窓・2001年以降は {sum(s >= SPLIT for s in starts)}窓）'},
            'leverage': '毎日リセット（fam_levtrend._lev＝h.lev_daily・暦年の取引日数で日割り）：借りた分 (L−1) に rf+0.4%/年、経費 0.9%/年（凍結の費用モデル）',
            'rule3': 'fam_levtrend.positions（signal=d200・ma=200・out=1x）を L=1.5 で。主は delay=1（前日の終値の信号を当日の終値で）。乗り換え＝全部売って全部買う',
            'rule4': 'spec_voltarget.json（scale=vol・lookback=63・target=exp・min_hist=252）の weight_at を月初の日に前日の終値までで。上限だけ 1.5（事前登録）。w≤1 は残りを短期金利の MMF（これも売れば課税）、w>1 は 1.5倍型を 2(w−1)',
            'tax': '特定口座・総平均法・円で測る。売るたびに暦年の累計損益に 20.315% を合わせて源泉（年の中の損失は通算して還付）・損失の繰越なし・窓の最後に全部売って清算',
            'costs': '乗り換え・組み替えで売った額の 0.1%（凍結）。積立の買い・最後の清算は無料。①の経費は0（実物の SPY 0.09%・QQQ 0.20% は入れていない）',
            'contrib': '毎月の最初の取引日の終値で1円をその日のレートでドルへ。240回。窓の終わり＝240か月目の最後の取引日',
        },
        '⚠限界': [
            '配当の税を入れていない（事前登録の範囲外）: 実物の1倍の ETF（SPY・QQQ）は配当が毎年課税される（米国10%＋日本20.315%・外国税額控除は別）一方、スワップで倍率を掛ける型は配当をほとんど出さない＝紙の上の①は S&P500 で少し有利に出ている（年0.4%前後の差になりうる）',
            'NASDAQ-100 は価格指数で配当（年0.6〜1%）が入っていない＝①も倍率の型も少し低く出る（倍率の型のほうが L倍ぶん多く抜けている）',
            'レバレッジ型は NISA で持てない（成長投資枠の対象外）。楽天の米国 ETF の取扱（out/broker_lineup.json 2026-08-24）: QLD・SSO・TQQQ・UPRO・SPXL は在るが、1.25倍・1.5倍の単一の商品は無い＝②1.25/1.5・③④は2倍型と1倍の組み合わせで作る必要がある（その組み合わせは毎日リセットではないので結果は少し違う）',
            '為替の手数料（楽天 1ドル0.25円前後）は入れていない（積立と最後の換金は全部の形で同じ・ドルの中の乗り換えには掛からない）',
            '損失の3年繰越（確定申告）を入れていない＝下げの年に売った形（③④）は少し不利に出ている',
            '20年窓は重なっている（独立な窓は 1986〜2006 開始で1つ分ほど・2001年以降の窓は全部 2021〜2026 に終わる＝同じ上げ相場で終わる）',
            '1987-10-19 のような一日の暴落を毎日リセットの型は L倍で受ける（S&P −17%・1.5倍なら −26%）。紙の上はそれも入っているが、実物では値付けの乱れが加わる',
        ],
        '読み（結果を見た後に書いた・判定は変えない）': READING,
        'results': {ix: {k: {kk: vv for kk, vv in o.items()} for k, o in res[ix].items()} for ix in res},
        '実物の参考（2倍の実物・課税口座の同じ計算）': rp,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'verdict': v, 'ok': ok, 'up': up}, ensure_ascii=False))
    for ix in res:
        print('==', ix)
        for k, o in res[ix].items():
            a = o['税の後の最終額の比（対①）']
            print(f"{k:34s} 全{a['1986年以降に始まる窓（全部）']['中央']:.3f}/{a['1986年以降に始まる窓（全部）']['最悪']:.3f}  01+ {a['2001年以降に始まる窓']['中央']:.3f}/{a['2001年以降に始まる窓']['最悪']:.3f}  "
                  f"DD01 {o['最大下落（1単位・税の前・日次）']['2001〜・ドル']} DD86 {o['最大下落（1単位・税の前・日次）']['1986-11〜・ドル']}  tax {o['払った税（最終額に対する割合の中央）']}  "
                  f"x {o['税の後の倍率（積んだ円に対して）']['全部']['中央']}")
    print(json.dumps(rp, ensure_ascii=False, indent=1)[:3000])


if __name__ == '__main__':
    main()
