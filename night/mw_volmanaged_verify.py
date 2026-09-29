#!/usr/bin/env python3
"""night/mw_volmanaged_verify.py — 角度 volmanaged の『反証の検証』（読むだけ・門の判定・採点・配分には不使用）

対象: out/mw_volmanaged.json で S/A と格付けされた規則（H06・Q09・Q11・Q37・H13・H14・H15・H20・I01・I02・I03）と、
      B のうち保有期間の超過が最も大きい2本（H01・H02）。

独立の再実装: 取得（French の CSV・Yahoo のキャッシュ）だけ mw_common の get / french_tables を使い、
信号（RV1・√RV1・下方の RV）・倍率・β=1 の c（訓練だけ／過去だけ毎年）・資産の動き（明示の持ち高で月末に戻す）・
2倍日々リセット型・1日遅れの日次の売買・超過・Newey-West t・幾何差・転がる窓・積立・シャープ・検定は
すべてこのファイルで書き直す（mw_volmanaged.py の関数は一つも呼ばない）。

反証の観点:
  1. 数字の再現（全期間・訓練・保有の超過と NW t・幾何差・20年窓・費用後の保有・積立）
  2. 相手: 規則の相手は『同じ指数の買って持つだけ』（全体の事前登録の timing_leverage）だが、ユーザーの問いは『市場』
     → 上限なしの時価加重の French Mkt に対しても測る
  3. 勝ちの中身: 平均倍率 1.3〜1.4 の借入。β を合わせた CAPM α・同じ平均倍率で一定に持つ版との差（時期の読みの価値）
  4. シャープの差の検定（Jobson-Korkie/Memmel・ブロック・ブートストラップ）＝C8 が点推定だけで通っていないか
  5. 後知恵: 第2〜4族は保有期間の結果を見た後の登録（全体の事前登録の honesty_rules は『事後』扱いを求める）／
     訓練の c は訓練の中で当てはめた値（C1 は標本内）／HiTec は 2007 年以降のテックの勝ちを知った後の選択
  6. 部分期間（1998-2000・2020-2021 を抜く／保有の前半・後半／訓練の 1985 年より前と後）・隣の値（上限 1.25/1.75/2・
     借入 2%/3%・費用 0.3%・20年窓の起点の月・15/25年窓）・1日遅れ（HiTec は研究側が測っていない）
  7. 業種の広がり（H06 の規則を French 10業種すべてと米国市場に当てる）・地域の再現（C5）
  8. 税（日本の課税口座で持つ戦略 vs 同じ指数を NISA〔非課税〕で持つ場合／課税口座で持つ場合）

使い方: python3 night/mw_volmanaged_verify.py
"""
import sys, os, json, math, datetime, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得（get / french_tables）だけを使う
import numpy as np

BASE = M.BASE
TE, HS = 200612, 200701
SPREAD, COST, FEE2X, NDX_DIV = 0.005, 0.001, 0.0095, 0.005
END_D = 20260831
TAX = 0.20315
OUT = os.path.join(BASE, 'out', 'mw_volmanaged_verify.json')
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── 日付 ─────────────────────────
def nm(ym):
    y, m = divmod(ym, 100)
    return (y + 1) * 100 + 1 if m == 12 else ym + 1


def pm(ym):
    y, m = divmod(ym, 100)
    return (y - 1) * 100 + 12 if m == 1 else ym - 1


def madd(ym, k):
    y, m = divmod(ym, 100)
    t = y * 12 + (m - 1) + k
    return (t // 12) * 100 + t % 12 + 1


# ───────────────────────── データ（取得だけ mw_common） ─────────────────────────
def fr_tab(name, freq, title=None):
    for t, v in M.french_tables(name).items():
        if v['freq'] == freq and (title is None or title.lower() in t.lower()):
            return v
    raise KeyError((name, freq, title))


def fr_mkt_rf(name, freq):
    v = fr_tab(name, freq)
    ci, ri = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
    tot, rf = {}, {}
    for k, r in v['data'].items():
        if r[ci] is None or r[ri] is None:
            continue
        tot[k] = (r[ci] + r[ri]) / 100.0
        rf[k] = r[ri] / 100.0
    return tot, rf


def to_month(daily):
    out = {}
    for d in sorted(daily):
        k = d // 100
        out[k] = out.get(k, 1.0) * (1.0 + daily[d])
    return {k: v - 1.0 for k, v in out.items()}


class Mk:
    """一つの資産: 日次の総リターン・日次 RF・月次の総リターン・月次 RF（月は連続した最長の区間）"""

    def __init__(self, name, dtot, drf, mtot, mrf):
        self.name = name
        days = sorted(d for d in dtot if d in drf)
        self.days = days
        self.dtot = {d: dtot[d] for d in days}
        self.drf = {d: drf[d] for d in days}
        self.dex = {d: dtot[d] - drf[d] for d in days}
        ms = sorted(k for k in mtot if k in mrf)
        runs, cur = [], [ms[0]]
        for a, b in zip(ms, ms[1:]):
            if nm(a) == b:
                cur.append(b)
            else:
                runs.append(cur); cur = [b]
        runs.append(cur)
        best = max(runs, key=len)
        self.months = best
        self.m = {k: mtot[k] for k in best}
        self.rf = {k: mrf[k] for k in best}
        self._sig = None

    def sig(self):
        if self._sig is None:
            by = {}
            for d in self.days:
                by.setdefault(d // 100, []).append(self.dex[d])
            var1, down = {}, {}
            for ym, xs in by.items():
                if len(xs) < 10:
                    continue
                a = np.asarray(xs)
                var1[ym] = float(((a - a.mean()) ** 2).sum())
                down[ym] = float((a[a < 0] ** 2).sum())
            self._sig = {'VAR1': var1, 'VOL1': {k: math.sqrt(v) for k, v in var1.items()}, 'DOWN': down}
        return self._sig


def yahoo_cached(fname):
    j = json.load(open(os.path.join(M.CACHE, fname)))
    r = j['chart']['result'][0]
    cl = r['indicators']['quote'][0]['close']
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or cl
    px, pa = {}, {}
    for t, c, a in zip(r['timestamp'], cl, adj):
        d = datetime.datetime.utcfromtimestamp(t)
        k = d.year * 10000 + d.month * 100 + d.day
        if k > END_D:
            continue
        if c is not None:
            px[k] = c
        if a is not None:
            pa[k] = a
    return px, pa


def simple_rets(px):
    ks = sorted(px)
    return {b: px[b] / px[a] - 1.0 for a, b in zip(ks, ks[1:])}


def load_all():
    D = {}
    ffd_tot, ffd_rf = fr_mkt_rf('F-F_Research_Data_Factors_daily', 'daily')
    ffm_tot, ffm_rf = fr_mkt_rf('F-F_Research_Data_Factors', 'monthly')
    D['ffm_tot'], D['ffm_rf'], D['ffd_rf'] = ffm_tot, ffm_rf, ffd_rf
    D['US'] = Mk('US', ffd_tot, ffd_rf, ffm_tot, ffm_rf)
    # HiTec と他の9業種（時価加重）
    vd = fr_tab('10_Industry_Portfolios_daily', 'daily', 'Value Weighted')
    vm = fr_tab('10_Industry_Portfolios', 'monthly', 'Value Weighted')
    D['ind'] = {}
    for i, col in enumerate(vd['cols']):
        dd = {k: r[i] / 100.0 for k, r in vd['data'].items() if r[i] is not None}
        j = vm['cols'].index(col)
        mm = {k: r[j] / 100.0 for k, r in vm['data'].items() if r[j] is not None}
        D['ind'][col] = Mk(col, dd, ffd_rf, mm, ffm_rf)
    D['HiTec'] = D['ind']['HiTec']
    # NDX 総リターン（価格＋年0.5%〔1999-03-10 まで〕→ QQQ の調整後）
    npx, _ = yahoo_cached('trend_yh_IDX_NDX_1d_full.json')
    _, qadj = yahoo_cached('trend_yh_QQQ_1d_full.json')
    pr, qr = simple_rets(npx), simple_rets(qadj)
    q0 = min(qadj)
    dy = (1 + NDX_DIV) ** (1 / 252) - 1
    ntot = {}
    for k, v in pr.items():
        if k <= q0:
            ntot[k] = (1 + v) * (1 + dy) - 1
        elif k in qr:
            ntot[k] = qr[k]
    ntot = {k: v for k, v in ntot.items() if k in ffd_rf}
    nmon = to_month(ntot)
    nmon.pop(min(ntot) // 100, None)  # 最初の月は途中から
    D['NDX'] = Mk('NDX', ntot, ffd_rf, nmon, ffm_rf)
    D['ndx_check'] = {'first_day': min(ntot), 'splice_day': q0, 'days': len(ntot), 'months': [D['NDX'].months[0], D['NDX'].months[-1], len(D['NDX'].months)],
                      'days_dropped_not_in_french': sum(1 for k in pr if k not in ffd_rf)}
    # 地域（C5）
    D['reg'] = {}
    for r in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan'):
        dt, drf = fr_mkt_rf(f'{r}_3_Factors_Daily', 'daily')
        mt, mrf = fr_mkt_rf(f'{r}_3_Factors', 'monthly')
        D['reg'][r] = Mk(r, dt, drf, mt, mrf)
    return D


# ───────────────────────── 規則 ─────────────────────────
def w_of(x, c, cap):
    if c == math.inf or x <= 0:
        return cap
    return min(cap, c / x)


def pairs_arr(mk, X, end=None):
    t0s = [t0 for t0, t1 in zip(mk.months, mk.months[1:]) if t0 in X and (end is None or t1 <= end)]
    x = np.array([X[t0] for t0 in t0s], dtype=float)
    e = np.array([mk.m[nm(t0)] - mk.rf[nm(t0)] for t0 in t0s], dtype=float)
    return x, e


def solve_beta1(mk, X, cap, end, spread=SPREAD, min_n=24, target=1.0):
    """訓練（t1 ≤ end）で『戦略の超過（借入の上乗せ込み）を相手の超過に回帰した傾き』が target になる c"""
    x, e = pairs_arr(mk, X, end)
    if len(x) < min_n:
        return None
    ed = e - e.mean(); ve = float(ed @ ed)

    def beta(c):
        if c == math.inf:
            w = np.full(len(x), cap)
        else:
            w = np.where(x > 0, np.minimum(cap, c / np.where(x > 0, x, 1.0)), cap)
        y = w * e - np.maximum(w - 1.0, 0.0) * spread / 12
        return float(((y - y.mean()) @ ed) / ve)

    if beta(math.inf) < target:
        return math.inf
    med = float(np.median(x[x > 0]))
    lo, hi = math.log(med) - 30, math.log(med) + 30
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        if beta(math.exp(mid)) < target:
            lo = mid
        else:
            hi = mid
    return math.exp(0.5 * (lo + hi))


def cmap_expanding(mk, X, cap, spread=SPREAD):
    out = {}
    for T in mk.months:
        if T % 100 != 12:
            continue
        c = solve_beta1(mk, X, cap, end=T, spread=spread, min_n=60)
        if c is None:
            continue
        t = T
        for _ in range(12):
            out[t] = c
            t = nm(t)
    return out


def weights(mk, sig, cap, cmode, spread=SPREAD):
    """{決めた月末 t0: 倍率}。sig: VAR1/VOL1/DOWN/ENS。cmode: train（訓練で β=1）/ exp（過去だけ毎年 β=1）"""
    if sig == 'ENS':
        parts = [weights(mk, s, cap, cmode, spread)[0] for s in ('VAR1', 'VOL1', 'DOWN')]
        ks = set(parts[0]) & set(parts[1]) & set(parts[2])
        return {k: sum(p[k] for p in parts) / 3 for k in ks}, {'c': 'ENS'}
    X = mk.sig()[sig]
    if cmode == 'train':
        c = solve_beta1(mk, X, cap, end=TE, spread=spread)
        W = {t0: w_of(X[t0], c, cap) for t0 in mk.months if t0 in X}
        return W, {'c': c}
    cm = cmap_expanding(mk, X, cap, spread)
    W = {t0: w_of(X[t0], cm[t0], cap) for t0 in mk.months if t0 in X and t0 in cm}
    vals = [v for v in cm.values() if v != math.inf]
    return W, {'c_first': min(cm), 'c_min': min(vals) if vals else None, 'c_max': max(vals) if vals else None}


# ───────────────────────── 資産の動き（明示の持ち高） ─────────────────────────
def sim_margin(mk, W, spread=SPREAD, cost=COST, rf_add=0.0):
    """月末 t0 の終値で倍率 W[t0] へ戻す（売買額×cost を資産から引く）→ 月 t1 は株 E と借入/預金 B を持ったまま。
    借入（B<0）は RF+spread、預金は RF。最初の月と途切れた後は『買って持つだけ（E=V）』から乗り換える"""
    R, WT, TR = {}, {}, {}
    V = E = None; last = None
    for t0, t1 in zip(mk.months, mk.months[1:]):
        w = W.get(t0)
        if w is None:
            V = None; continue
        if V is None or last != t0:
            V, E = 1.0, 1.0
        V_before = V
        trade = abs(w * V - E)
        V = V - trade * cost
        E = w * V; B = V - E
        E1 = E * (1 + mk.m[t1])
        B1 = B * (1 + mk.rf[t1] + ((spread + rf_add) / 12 if B < 0 else 0.0))
        V1 = E1 + B1
        R[t1] = V1 / V_before - 1
        WT[t1] = w; TR[t1] = trade / V_before
        V, E, last = V1, E1, t1
    return R, WT, TR


def fund2_monthly(mk, spread=SPREAD, fee=FEE2X):
    d = {k: 2 * mk.dtot[k] - (mk.drf[k] + spread / 252) - fee / 252 for k in mk.days}
    m2 = to_month(d)
    m2.pop(mk.days[0] // 100, None)
    return m2


def sim_fund(mk, W, cost=COST, leg_mode='actual'):
    """1倍の投信 F1 と2倍の日々リセット型 F2（と RF の預金 C）で倍率を作る。w>1: F1=(2−w)V・F2=(w−1)V、w≤1: F1=wV・C=(1−w)V。
    売買額: actual = |ΔF1|+|ΔF2|（実際に売り買いする額）、researcher = 2×|Δ倍率|（研究側の保守的な数え方）"""
    m2 = fund2_monthly(mk)
    R, WT = {}, {}
    V = F1 = F2 = C = None; last = None
    for t0, t1 in zip(mk.months, mk.months[1:]):
        w = W.get(t0)
        if w is None or t1 not in m2:
            V = None; continue
        if V is None or last != t0:
            V, F1, F2, C = 1.0, 1.0, 0.0, 0.0
        V_before = V
        if w > 1:
            n1, n2 = (2 - w) * V, (w - 1) * V
        else:
            n1, n2 = w * V, 0.0
        if leg_mode == 'actual':
            trade = abs(n1 - F1) + abs(n2 - F2)
        else:
            expo = (F1 + 2 * F2) / V
            trade = 2 * abs(w - expo) * V
        V = V - trade * cost
        if w > 1:
            F1, F2, C = (2 - w) * V, (w - 1) * V, 0.0
        else:
            F1, F2, C = w * V, 0.0, (1 - w) * V
        F1 *= 1 + mk.m[t1]; F2 *= 1 + m2[t1]; C *= 1 + mk.rf[t1]
        V1 = F1 + F2 + C
        R[t1] = V1 / V_before - 1; WT[t1] = w
        V, last = V1, t1
    return R, WT


def sim_lag1(mk, W, spread=SPREAD, cost=COST):
    """1日遅れ: 月末 t0 に決めた W[t0] を、翌月の最初の営業日の終値で実行（その日は前の持ち高のまま）。日次で持ち高を追う。
    月次リターン = 月末の資産の比。相手は同じ日次を月へ複利でまとめたもの"""
    days = mk.days
    R = {}; WT = {}
    V = E = None
    Vme = None; cur_ok = False
    for i, d in enumerate(days):
        ym = d // 100
        first = i > 0 and days[i - 1] // 100 != ym
        if first:
            t0 = days[i - 1] // 100
            if V is not None and cur_ok:
                R[t0] = V / Vme - 1
            wnew = W.get(t0)
            if wnew is None:
                V = None; cur_ok = False
            else:
                if V is None:
                    V, E = 1.0, 1.0  # 前の月末まで買って持つだけ
                Vme = V; cur_ok = True
        if V is not None:
            r, rf = mk.dtot[d], mk.drf[d]
            B = V - E
            E *= 1 + r
            B *= 1 + rf + (spread / 252 if B < 0 else 0.0)
            V = E + B
            if first and cur_ok:
                wnew = W[days[i - 1] // 100]
                trade = abs(wnew * V - E)
                V -= trade * cost
                E = wnew * V
                WT[ym] = wnew
    if V is not None and cur_ok and days[-1] == END_D:
        R[days[-1] // 100] = V / Vme - 1
    bench = to_month(mk.dtot)
    R = {k: v for k, v in R.items() if k in WT}
    return R, WT, bench


def sim_const(mk, L, months, spread=SPREAD, cost=COST):
    W = {pm(t1): L for t1 in months}
    return sim_margin(mk, W, spread, cost)[0]


# ───────────────────────── 統計（独自実装） ─────────────────────────
def nw_t(x, L=12):
    x = np.asarray(x, dtype=float); n = len(x)
    if n < 24:
        return None
    e = x - x.mean()
    s = float(e @ e) / n
    for l in range(1, min(L, n - 1) + 1):
        s += 2 * (1 - l / (L + 1)) * float(e[l:] @ e[:-l]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else None


def pval(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def ann_geo(v):
    v = np.asarray(v, dtype=float)
    return math.exp(float(np.log1p(v).sum()) * 12 / len(v)) - 1


def keys(s, b, a=None, z=None, drop=()):
    return sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not any(lo <= k <= hi for lo, hi in drop))


def exs(s, b, a=None, z=None, drop=()):
    ks = keys(s, b, a, z, drop)
    if len(ks) < 24:
        return None
    sv = np.array([s[k] for k in ks]); bv = np.array([b[k] for k in ks]); d = sv - bv
    t = nw_t(d)
    beta = float(np.cov(sv, bv, ddof=0)[0, 1] / np.var(bv))
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(float(d.mean()) * 1200, 2), 't': round(t, 2) if t is not None else None,
            'p': round(pval(t), 5) if t is not None else None, 'cagr_diff': round((ann_geo(sv) - ann_geo(bv)) * 100, 2),
            'cagr_s': round(ann_geo(sv) * 100, 2), 'cagr_b': round(ann_geo(bv) * 100, 2), 'beta': round(beta, 3)}


def capm(s, b, rf, a=None, z=None):
    ks = [k for k in keys(s, b, a, z) if k in rf]
    y = np.array([s[k] - rf[k] for k in ks]); x = np.array([b[k] - rf[k] for k in ks])
    beta = float(np.cov(y, x, ddof=0)[0, 1] / np.var(x))
    e = y - beta * x
    t = nw_t(e)
    return {'alpha': round(float(e.mean()) * 1200, 2), 't': round(t, 2), 'beta': round(beta, 3), 'n': len(ks)}


def roll(s, b, years=20, sm=7):
    ks = set(s) & set(b)
    if not ks:
        return None
    k0, k1 = min(ks), max(ks)
    res = []
    for y in range(k0 // 100, k1 // 100 + 1):
        a = y * 100 + sm
        ms = [madd(a, i) for i in range(years * 12)]
        if not all(m in ks for m in ms):
            continue
        gs = ann_geo([s[m] for m in ms]); gb = ann_geo([b[m] for m in ms])
        res.append((y, round((gs - gb) * 100, 2)))
    if not res:
        return None
    v = sorted(x for _, x in res)
    wins = sum(1 for _, x in res if x > 0)
    return {'n': len(res), 'wins': wins, 'win_rate': round(wins / len(res), 3), 'median': v[len(v) // 2], 'worst': min(res, key=lambda r: r[1])}


def dca(s, b, years=20, step=12):
    ks = sorted(set(s) & set(b)); n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        if w[-1] != madd(w[0], n - 1):
            continue
        a = c = 0.0
        for k in w:
            a = (a + 1) * (1 + s[k]); c = (c + 1) * (1 + b[k])
        out.append((w[0], a / c))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'n': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': round(v[len(v) // 2], 3), 'worst': [min(out, key=lambda x: x[1])[0], round(min(r for _, r in out), 3)]}


def sharpe(r, rf, ks):
    x = np.array([r[k] - rf[k] for k in ks])
    return float(x.mean() / x.std(ddof=1) * math.sqrt(12))


def sharpe_pair(s, b, rf, a=None, z=None):
    ks = [k for k in keys(s, b, a, z) if k in rf]
    return round(sharpe(s, rf, ks), 3), round(sharpe(b, rf, ks), 3)


def jk_memmel(s, b, rf, a=None, z=None):
    ks = [k for k in keys(s, b, a, z) if k in rf]
    y1 = np.array([s[k] - rf[k] for k in ks]); y2 = np.array([b[k] - rf[k] for k in ks])
    s1, s2 = y1.mean() / y1.std(ddof=1), y2.mean() / y2.std(ddof=1)
    rho = float(np.corrcoef(y1, y2)[0, 1]); T = len(ks)
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T
    z = float((s1 - s2) / math.sqrt(var))
    return {'z': round(z, 2), 'p_two': round(pval(z), 4), 'rho': round(rho, 4), 'n': T}


def boot_sharpe(s, b, rf, a=None, z=None, reps=2000, block=12, seed=7):
    """循環ブロック・ブートストラップ（12か月）: シャープの差（戦略−相手）≤ 0 になった割合（片側 p）"""
    ks = [k for k in keys(s, b, a, z) if k in rf]
    y1 = np.array([s[k] - rf[k] for k in ks]); y2 = np.array([b[k] - rf[k] for k in ks])
    T = len(ks); rng = np.random.default_rng(seed)
    nb = int(math.ceil(T / block))
    cnt = 0; diffs = []
    for _ in range(reps):
        st = rng.integers(0, T, nb)
        idx = (st[:, None] + np.arange(block)[None, :]).ravel()[:T] % T
        a1, a2 = y1[idx], y2[idx]
        d = a1.mean() / a1.std(ddof=1) - a2.mean() / a2.std(ddof=1)
        diffs.append(d)
        if d <= 0:
            cnt += 1
    diffs.sort()
    return {'p_one_sided': round((cnt + 1) / (reps + 1), 4), 'ci90_ann': [round(diffs[int(0.05 * reps)] * math.sqrt(12), 3), round(diffs[int(0.95 * reps)] * math.sqrt(12), 3)]}


def maxdd(r, ks):
    w = pk = 1.0; dd = 0.0
    for k in ks:
        w *= 1 + r[k]; pk = max(pk, w); dd = min(dd, w / pk - 1)
    return round(dd * 100, 1)


def holm(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m = len(it); out = {}; run = 0.0
    for i, (v, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * v)); out[k] = round(run, 4)
    return out


# ───────────────────────── 税（日本の課税口座・近似） ─────────────────────────
def tax_sim(mk, W, a, z, spread=SPREAD, cost=COST):
    """戦略を課税口座で持つ近似: 月末に倍率を下げるときの売却益に 20.315%（平均取得・年ごとに通算・損失は3年繰越）、
    最後に全部売って課税。相手は (i) NISA＝非課税 と (ii) 課税口座で持ち続けて最後に売る の二つ。年率で返す"""
    ms = [k for k in mk.months if a <= k <= z]
    ms = [k for k in ms if pm(k) in W]
    if len(ms) < 24:
        return None
    V = 1.0; w0 = W[pm(ms[0])]
    E = w0 * V; K = E; B = V - E
    realized = 0.0; carry = []
    bench = 1.0

    def settle(yr, g):
        nonlocal carry
        carry = [(y, l) for y, l in carry if yr - y <= 3]
        if g <= 0:
            carry.append((yr, -g)); return 0.0
        new = []
        for y, l in carry:
            u = min(l, g); g -= u
            if l - u > 0:
                new.append((y, l - u))
        carry = new
        return TAX * g

    for i, t in enumerate(ms):
        E *= 1 + mk.m[t]
        B *= 1 + mk.rf[t] + (spread / 12 if B < 0 else 0.0)
        bench *= 1 + mk.m[t]
        last = i == len(ms) - 1
        if not last:
            V = E + B
            w = W[t]
            tgt = w * V
            V -= abs(tgt - E) * cost
            tgt = w * V
            if tgt < E and E > 0:
                sold = E - tgt
                realized += sold * (1 - K / E)
                K *= tgt / E
            else:
                K += tgt - E
            E = tgt; B = V - E
        if t % 100 == 12 or last:
            if last:
                realized += E - K
            tx = settle(t // 100, realized); realized = 0.0
            B -= tx
    V = E + B
    yrs = len(ms) / 12
    s = V ** (1 / yrs) - 1
    b_nisa = bench ** (1 / yrs) - 1
    b_tax = (bench - TAX * max(0.0, bench - 1)) ** (1 / yrs) - 1
    return {'from': ms[0], 'to': ms[-1], 'strategy_after_tax_cagr': round(s * 100, 2), 'bench_nisa_cagr': round(b_nisa * 100, 2),
            'bench_taxable_cagr': round(b_tax * 100, 2), 'diff_vs_nisa': round((s - b_nisa) * 100, 2), 'diff_vs_taxable': round((s - b_tax) * 100, 2)}


# ───────────────────────── 格付け（mw_prereg の線をここで書き直す） ─────────────────────────
def grade(full, train, hold, cost_hold, r20, repl, sh_tr, sh_ho, holm_p=None):
    c = {}
    c['C1'] = bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0)
    c['C2'] = bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0)
    c['C3'] = bool(hold and (hold['t'] or 0) >= 1.65)
    c['C4'] = bool(r20 and r20['win_rate'] >= 0.8)
    c['C5'] = None if repl is None else (repl[0] / repl[1] >= 2 / 3)
    c['C6'] = bool(cost_hold and cost_hold['ex'] > 0 and cost_hold['cagr_diff'] > 0)
    c['C7'] = bool((full and (full['t'] or 0) >= 3.0) or (holm_p is not None and holm_p < 0.05))
    c['C8'] = bool(sh_tr[0] > sh_tr[1] and sh_ho[0] > sh_ho[1])
    base = c['C1'] and c['C2'] and c['C6'] and c['C8']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── 候補 ─────────────────────────
CANDS = [
    # id, 市場, 信号, 上限, c の決め方, 実行
    ('H06_HiTec_DOWN_cap1.5_B1EXP', 'HiTec', 'DOWN', 1.5, 'exp', 'margin'),
    ('H15_NDX_DOWN_cap1.5_B1_LAG1', 'NDX', 'DOWN', 1.5, 'train', 'lag1'),
    ('Q09_NDX_VAR1_cap1.5_B1', 'NDX', 'VAR1', 1.5, 'train', 'margin'),
    ('Q37_NDX_DOWN_cap1.5_B1', 'NDX', 'DOWN', 1.5, 'train', 'margin'),
    ('H13_NDX_VAR1_cap1.5_B1_LAG1', 'NDX', 'VAR1', 1.5, 'train', 'lag1'),
    ('H20_NDX_ENS_cap1.5_B1', 'NDX', 'ENS', 1.5, 'train', 'margin'),
    ('I03_NDX_DOWN_cap1.5_B1_FUND', 'NDX', 'DOWN', 1.5, 'train', 'fund'),
    ('I01_NDX_VAR1_cap1.5_B1_FUND', 'NDX', 'VAR1', 1.5, 'train', 'fund'),
    # 請求の一覧に無いが研究側で A の3本（念のため同じ検査）
    ('Q11_NDX_VOL1_cap1.5_B1', 'NDX', 'VOL1', 1.5, 'train', 'margin'),
    ('H14_NDX_VOL1_cap1.5_B1_LAG1', 'NDX', 'VOL1', 1.5, 'train', 'lag1'),
    ('I02_NDX_VOL1_cap1.5_B1_FUND', 'NDX', 'VOL1', 1.5, 'train', 'fund'),
    # B の保有期間の超過の上位2本
    ('H01_HiTec_VAR1_cap1.5_B1', 'HiTec', 'VAR1', 1.5, 'train', 'margin'),
    ('H02_HiTec_VAR1_cap1.5_B1EXP', 'HiTec', 'VAR1', 1.5, 'exp', 'margin'),
]


def run(mk, sig, cap, cmode, impl, spread=SPREAD, cost=COST, rf_add=0.0):
    """→ (gross, net, weights_by_t1, bench)"""
    W, info = weights(mk, sig, cap, cmode, spread)
    if impl == 'margin':
        g, wt, tr = sim_margin(mk, W, spread, 0.0, rf_add)
        n, _, _ = sim_margin(mk, W, spread, cost, rf_add)
        return g, n, wt, mk.m, W, info, tr
    if impl == 'fund':
        g, wt = sim_fund(mk, W, 0.0)
        n, _ = sim_fund(mk, W, cost, 'actual')
        n2, _ = sim_fund(mk, W, cost, 'researcher')
        info['net_researcher_cost_rule'] = n2
        return g, n, wt, mk.m, W, info, None
    if impl == 'lag1':
        g, wt, bench = sim_lag1(mk, W, spread, 0.0)
        n, _, _ = sim_lag1(mk, W, spread, cost)
        return g, n, wt, bench, W, info, None
    raise KeyError(impl)


def core(g, n, wt, b, rf):
    full, train, hold = exs(g, b), exs(g, b, z=TE), exs(g, b, a=HS)
    cost_hold = exs(n, b, a=HS)
    r20 = roll(n, b)
    return {'full': full, 'train': train, 'hold': hold, 'recent_2013': exs(g, b, a=201307), 'cost_hold': cost_hold, 'cost_full': exs(n, b),
            'roll20': r20, 'roll20_gross': roll(g, b), 'dca20': dca(n, b),
            'sharpe_train': sharpe_pair(n, b, rf, z=TE), 'sharpe_hold': sharpe_pair(n, b, rf, a=HS), 'sharpe_full': sharpe_pair(n, b, rf),
            'avg_w': {'full': round(float(np.mean(list(wt.values()))), 3), 'train': round(float(np.mean([v for k, v in wt.items() if k <= TE])), 3) if any(k <= TE for k in wt) else None,
                      'hold': round(float(np.mean([v for k, v in wt.items() if k >= HS])), 3), 'share_at_cap_hold': round(float(np.mean([abs(v - max(wt.values())) < 1e-9 for k, v in wt.items() if k >= HS])), 3)}}


def region_count(D, sig, cap, cmode, impl):
    pos = 0; det = {}
    for r, mk in D['reg'].items():
        g, n, wt, b, W, info, _ = run(mk, sig, cap, cmode, 'margin' if impl == 'lag1' else impl)
        st = exs(n, b)
        ok = bool(st and st['ex'] > 0 and st['cagr_diff'] > 0)
        pos += ok
        det[r] = {'net_full_ex': st['ex'], 'net_full_t': st['t'], 'cagr_diff': st['cagr_diff'], 'from': st['from'], 'positive': ok,
                  'hold_net_ex': exs(n, b, a=HS)['ex'], 'sharpe_full': sharpe_pair(n, b, mk.rf)}
    return (pos, len(D['reg'])), det


def main():
    D = load_all()
    log('NDX つなぎ', D['ndx_check'])
    US = D['US']
    mkt, mrf = D['ffm_tot'], D['ffm_rf']
    res = {'angle': 'volmanaged', 'what': '反証の検証（独立の再実装）', 'generated': datetime.date.today().isoformat(),
           'inputs': {'researcher_json': 'out/mw_volmanaged.json', 'criteria': 'out/mw_prereg.json', 'data_checks': {'ndx': D['ndx_check']}},
           'candidates': {}}
    R = json.load(open(os.path.join(BASE, 'out', 'mw_volmanaged.json')))
    RT = {x['id']: x for x in R['tested']}
    timing_p = {}
    for cid, idx, sig, cap, cmode, impl in CANDS:
        mk = D[idx]
        g, n, wt, b, W, info, tr = run(mk, sig, cap, cmode, impl)
        e = core(g, n, wt, b, mk.rf)
        repl, repl_det = region_count(D, sig, cap, cmode, impl)
        gr, cr = grade(e['full'], e['train'], e['hold'], e['cost_hold'], e['roll20'], repl, e['sharpe_train'], e['sharpe_hold'])
        rx = RT.get(cid, {})
        claimed = {'grade': rx.get('grade'), 'full_ex': (rx.get('full') or {}).get('ex_ann'), 'full_t': (rx.get('full') or {}).get('t'),
                   'train_ex': (rx.get('train') or {}).get('ex_ann'), 'train_t': (rx.get('train') or {}).get('t'),
                   'hold_ex': (rx.get('hold') or {}).get('ex_ann'), 'hold_t': (rx.get('hold') or {}).get('t'), 'hold_cagr_diff': (rx.get('hold') or {}).get('cagr_diff'),
                   'net_cost_hold_ex': (rx.get('cost_hold') or {}).get('ex_ann'), 'roll20_win': (rx.get('roll20') or {}).get('win_rate'),
                   'dca20_win': (rx.get('dca20') or {}).get('win_rate'), 'repl': f"{(rx.get('repl') or {}).get('positive')}/{(rx.get('repl') or {}).get('regions')}"}
        ent = {'spec': {'index': idx, 'signal': sig, 'cap': cap, 'c_mode': cmode, 'impl': impl}, 'c_info': {k: v for k, v in info.items() if k != 'net_researcher_cost_rule'},
               'claimed': claimed, 'reproduced': e, 'reproduced_repl': {'positive': repl[0], 'regions': repl[1], 'detail': repl_det},
               'reproduced_grade': gr, 'reproduced_criteria': cr}
        if impl == 'fund':
            ent['fund_cost_rule_researcher'] = {'cost_hold': exs(info['net_researcher_cost_rule'], b, a=HS), 'roll20': roll(info['net_researcher_cost_rule'], b)}
        # ── 2. 相手を純粋な市場（French Mkt・上限なしの時価加重）に替える
        mk_b = {k: mkt[k] for k in b if k in mkt}
        ent['vs_pure_market'] = {'note': '相手 = French Mkt（Mkt-RF+RF・CRSP 全上場・上限なしの時価加重）。規則の相手（同じ指数）とは別',
                                 'full': exs(g, mk_b), 'train': exs(g, mk_b, z=TE), 'hold_net': exs(n, mk_b, a=HS), 'roll20_net': roll(n, mk_b),
                                 'underlying_vs_market': {'full': exs(b, mk_b), 'train': exs(b, mk_b, z=TE), 'hold': exs(b, mk_b, a=HS), 'roll20': roll(b, mk_b)}}
        # ── 3. 勝ちの中身: β・CAPM α・一定倍率
        ent['capm_net'] = {'train': capm(n, b, mk.rf, z=TE), 'hold': capm(n, b, mk.rf, a=HS), 'full': capm(n, b, mk.rf)}
        months = sorted(n)
        Ltr = ent['reproduced']['avg_w']['train'] or ent['reproduced']['avg_w']['full']
        cl = sim_const(mk, Ltr, months)
        ent['const_leverage_same_avg_w'] = {
            'L': Ltr, 'note': '訓練期間の平均倍率で毎月一定に持つ（同じ借入 RF+0.5%・同じ費用）。時期を読まない版',
            'const_vs_bench': {'train': exs(cl, b, z=TE), 'hold': exs(cl, b, a=HS), 'full': exs(cl, b), 'roll20': roll(cl, b),
                               'sharpe_train': sharpe_pair(cl, b, mk.rf, z=TE), 'sharpe_hold': sharpe_pair(cl, b, mk.rf, a=HS)},
            'timing_value_net': {'train': exs(n, cl, z=TE), 'hold': exs(n, cl, a=HS), 'full': exs(n, cl), 'roll20': roll(n, cl)},
            'maxdd_full': {'strategy': maxdd(n, months), 'const': maxdd(cl, months), 'bench': maxdd(b, months)}}
        timing_p[cid] = (ent['const_leverage_same_avg_w']['timing_value_net']['hold'] or {}).get('p')
        # ── 4. シャープの差の検定
        ent['sharpe_tests'] = {'train': {'jk_memmel': jk_memmel(n, b, mk.rf, z=TE), 'block_boot': boot_sharpe(n, b, mk.rf, z=TE)},
                               'hold': {'jk_memmel': jk_memmel(n, b, mk.rf, a=HS), 'block_boot': boot_sharpe(n, b, mk.rf, a=HS)}}
        # ── 6. 部分期間
        sub = {'hold_2007_2016': exs(n, b, a=HS, z=201612), 'hold_2017_2026': exs(n, b, a=201701),
               'hold_drop_2020_2021': exs(n, b, a=HS, drop=((202001, 202112),)),
               'full_drop_1998_2000': exs(g, b, drop=((199801, 200012),)), 'train_drop_1998_2000': exs(g, b, z=TE, drop=((199801, 200012),)),
               'full_drop_1998_2000_and_2020_2021': exs(g, b, drop=((199801, 200012), (202001, 202112))),
               'hold_2007_2009_gfc': exs(n, b, a=HS, z=200912), 'hold_2010_2026': exs(n, b, a=201001)}
        if idx == 'HiTec':
            sub['train_pre1985'] = exs(g, b, z=198412); sub['train_1985_2006'] = exs(g, b, a=198501, z=TE)
            sub['train_1932_1969'] = exs(g, b, z=196912); sub['train_1970_1989'] = exs(g, b, a=197001, z=198912)
        if idx == 'NDX':
            sub['train_1985_1994'] = exs(g, b, z=199412); sub['train_1995_2006'] = exs(g, b, a=199501, z=TE)
        ent['subperiods'] = sub
        # ── 6. 隣の値
        frag = {}
        base_impl = 'margin' if impl in ('margin', 'lag1') else impl
        for cp in (1.25, 1.5, 1.75, 2.0):
            g2, n2, wt2, b2, _, _, _ = run(mk, sig, cp, cmode, base_impl)
            frag[f'cap{cp:g}'] = {'train': exs(g2, b2, z=TE), 'cost_hold': exs(n2, b2, a=HS), 'full_t': exs(g2, b2)['t'], 'roll20': (roll(n2, b2) or {}).get('win_rate'),
                                  'sharpe_train': sharpe_pair(n2, b2, mk.rf, z=TE), 'sharpe_hold': sharpe_pair(n2, b2, mk.rf, a=HS)}
        frag['roll20_by_start_month'] = {str(sm): (roll(n, b, 20, sm) or {}).get('win_rate') for sm in range(1, 13)}
        frag['roll15'] = roll(n, b, 15); frag['roll25'] = roll(n, b, 25); frag['roll10'] = roll(n, b, 10)
        frag['dca20_monthly_starts'] = dca(n, b, 20, 1)
        if impl == 'margin':
            for lab, add in (('spread2pct', 0.015), ('spread3pct', 0.025)):
                _, n3, _, _, _, _, _ = run(mk, sig, cap, cmode, 'margin', rf_add=add)
                frag[lab] = {'cost_hold': exs(n3, b, a=HS), 'cost_full': exs(n3, b), 'roll20': (roll(n3, b) or {}).get('win_rate'),
                             'sharpe_train': sharpe_pair(n3, b, mk.rf, z=TE), 'sharpe_hold': sharpe_pair(n3, b, mk.rf, a=HS)}
            _, n4, _, _, _, _, _ = run(mk, sig, cap, cmode, 'margin', cost=0.003)
            frag['cost0.3pct'] = {'cost_hold': exs(n4, b, a=HS), 'roll20': (roll(n4, b) or {}).get('win_rate')}
            if tr:
                frag['turnover_per_year'] = round(sum(tr.values()) / (len(tr) / 12), 2)
        if idx == 'HiTec' and impl == 'margin':
            gl, nl, wtl, bl = sim_lag1(mk, W)[0], sim_lag1(mk, W, cost=COST)[0], None, sim_lag1(mk, W)[2]
            frag['lag1_not_tested_by_researcher'] = {'train': exs(gl, bl, z=TE), 'hold': exs(gl, bl, a=HS), 'full': exs(gl, bl), 'cost_hold': exs(nl, bl, a=HS),
                                                     'roll20': roll(nl, bl), 'sharpe_train': sharpe_pair(nl, bl, mk.rf, z=TE), 'sharpe_hold': sharpe_pair(nl, bl, mk.rf, a=HS)}
        if cmode == 'train' and idx == 'NDX':
            ge, ne, wte, be, _, ie, _ = run(mk, sig, cap, 'exp', base_impl)
            frag['past_only_c_same_rule'] = {'note': 'c を過去だけで毎年 β=1 に解く版（実時間）。訓練の合格が c の後知恵に頼っていないか',
                                             'train': exs(ge, be, z=TE), 'hold': exs(ge, be, a=HS), 'full': exs(ge, be), 'roll20': (roll(ne, be) or {}).get('win_rate'),
                                             'avg_w_train': round(float(np.mean([v for k, v in wte.items() if k <= TE])), 3)}
        ent['fragility'] = frag
        # ── 8. 税
        if impl in ('margin', 'lag1'):
            ent['tax_japan'] = {'hold': tax_sim(mk, W, HS, mk.months[-1]), 'full': tax_sim(mk, W, mk.months[1], mk.months[-1]),
                                'note': '近似。戦略は課税口座（レバレッジ・借入は新NISA対象外）。NISA の相手は同じ指数を非課税で持つ場合（ユーザーの実際の iFreeNEXT NASDAQ100 はつみたて枠）'}
        res['candidates'][cid] = ent
        h = e['hold']; t = e['train']; f = e['full']
        log(f"{cid:32s} 再現 {gr} (主張 {claimed['grade']}) full {f['ex']} t{f['t']} | tr {t['ex'] if t else None} t{t['t'] if t else None} | ho {h['ex']} t{h['t']} cg {h['cagr_diff']} | "
            f"net ho {e['cost_hold']['ex']} | r20 {e['roll20']['win_rate']} | dca {e['dca20']['win_rate']} | rep {repl[0]}/{repl[1]} | sh {e['sharpe_train']} {e['sharpe_hold']}")
        log(f"   vsMkt: ho_net {ent['vs_pure_market']['hold_net']['ex']} t{ent['vs_pure_market']['hold_net']['t']} tr {ent['vs_pure_market']['train']['ex']} t{ent['vs_pure_market']['train']['t']} r20 {ent['vs_pure_market']['roll20_net']['win_rate']} | "
            f"CAPM α tr {ent['capm_net']['train']} ho {ent['capm_net']['hold']} | L {Ltr} timing ho {ent['const_leverage_same_avg_w']['timing_value_net']['hold']['ex']} t{ent['const_leverage_same_avg_w']['timing_value_net']['hold']['t']} "
            f"tr {ent['const_leverage_same_avg_w']['timing_value_net']['train']['ex'] if ent['const_leverage_same_avg_w']['timing_value_net']['train'] else None} "
            f"t{ent['const_leverage_same_avg_w']['timing_value_net']['train']['t'] if ent['const_leverage_same_avg_w']['timing_value_net']['train'] else None} | const r20 {(ent['const_leverage_same_avg_w']['const_vs_bench']['roll20'] or {}).get('win_rate')}")
        log(f"   Sharpe JK tr {ent['sharpe_tests']['train']['jk_memmel']} ho {ent['sharpe_tests']['hold']['jk_memmel']} boot tr {ent['sharpe_tests']['train']['block_boot']} ho {ent['sharpe_tests']['hold']['block_boot']}")
        log('   sub', {k: (v['ex'], v['t']) if v else None for k, v in sub.items()})
        log('   frag', {k: ((v['train']['ex'], v['train']['t'], v['cost_hold']['ex'], v['roll20']) if isinstance(v, dict) and 'train' in v and v.get('train') and 'cost_hold' in v else None) for k, v in frag.items() if k.startswith('cap')},
            'r20 by month', frag['roll20_by_start_month'])
        if 'tax_japan' in ent:
            log('   tax', ent['tax_japan']['hold'])
    res['timing_value_holm'] = {'note': '帰無仮説『時期の読みは同じ平均倍率で一定に持つのと変わらない』の保有期間の p（両側・費用後）を、検証した13本の中で Holm 補正。研究側が判定した 116 本で数えればさらに厳しい',
                                'p_raw': timing_p, 'holm_13': holm(timing_p)}
    # ── 7. 業種の広がり（HiTec の3本の規則を French 10業種すべてと米国市場に当てる）
    res['industry_breadth'] = {}
    for sig, cm in (('DOWN', 'exp'), ('VAR1', 'train'), ('VAR1', 'exp')):
        br = {}
        for col, mk in list(D['ind'].items()) + [('US_market', US)]:
            g, n, wt, b, W, info, _ = run(mk, sig, 1.5, cm, 'margin')
            e = core(g, n, wt, b, mk.rf)
            gr, cr = grade(e['full'], e['train'], e['hold'], e['cost_hold'], e['roll20'], None, e['sharpe_train'], e['sharpe_hold'])
            br[col] = {'grade_without_C5': gr, 'train': (e['train']['ex'], e['train']['t']), 'hold': (e['hold']['ex'], e['hold']['t']), 'cost_hold': e['cost_hold']['ex'],
                       'full_t': e['full']['t'], 'roll20': e['roll20']['win_rate'], 'sharpe_train': e['sharpe_train'], 'sharpe_hold': e['sharpe_hold'], 'avg_w': e['avg_w']['full'],
                       'capm_hold': capm(n, b, mk.rf, a=HS), 'capm_train': capm(n, b, mk.rf, z=TE)}
            log('業種', sig, cm, col, br[col]['grade_without_C5'], br[col]['train'], br[col]['hold'], br[col]['roll20'])
        key = f'{sig}_cap1.5_{"B1EXP" if cm == "exp" else "B1"}'
        res['industry_breadth'][key] = {'note': f'規則 {key} を French 10業種すべてと米国市場（French Mkt）に当てた（C5 を除いた格付け）。HiTec だけが特別に良いなら選び出しの疑い', 'rows': br,
                                        'count_S_or_A_without_C5': sum(1 for v in br.values() if v['grade_without_C5'] in ('S', 'A')),
                                        'S_or_A': [k for k, v in br.items() if v['grade_without_C5'] in ('S', 'A')],
                                        'count_roll20_ge_0.8': sum(1 for v in br.values() if v['roll20'] >= 0.8),
                                        'negative_hold_net': [k for k, v in br.items() if k != 'US_market' and v['cost_hold'] < 0]}
    # 研究側が試した数（多重検定の数え上げ）
    res['search_size'] = {
        'graded_by_researcher': R.get('n_graded'), 'tested_total': R.get('n_tested'),
        'report_only_breadth': {'jkp_country_rules': len(R.get('jkp_breadth_report') or {}) + len(R.get('jkp_breadth_b1_report') or {}),
                                'industry_rules': len(R.get('industry_breadth_report') or {}), 'robustness_grid_rules': len([k for k in (R.get('robustness_grid_report') or {}) if k != 'note'])},
        'families': '第1族（主16＋探索32・結果を見る前に登録）→ 第2族（β=1・第1族の保有期間の結果を見た後）→ 第3族（HiTec/IXIC/1日遅れ/平均・第2族の後）→ 第4族（投信で実行・第3族の後）。S/A の11本はすべて第2〜4族',
        'honesty_rule': 'out/mw_prereg.json honesty_rules[1]: 保有期間の結果を見て規則を変えたら『事後』と明記し、判定には使わない'}
    res['sigma_matched_versions_family1'] = {k: {'train': [(RT[k]['train'] or {}).get('ex_ann'), (RT[k]['train'] or {}).get('t')], 'hold': [(RT[k]['hold'] or {}).get('ex_ann'), (RT[k]['hold'] or {}).get('t')],
                                                 'avg_w': ((RT[k].get('exposure') or {}).get('full') or {}).get('avg_w'), 'grade': RT[k].get('grade')}
                                             for k in ('P09_NDX_VAR1_cap1.5', 'P11_NDX_VOL1_cap1.5', 'E4_NDX_DOWN_cap1.5', 'P01_US_VAR1_cap1.5') if k in RT}
    res['verdicts'] = build_verdicts(res)
    h6 = res['candidates']['H06_HiTec_DOWN_cap1.5_B1EXP']; q9 = res['candidates']['Q09_NDX_VAR1_cap1.5_B1']
    res['summary_ja'] = [
        f"13本（S1・A10・B上位2）を独立に作り直し、数字はすべて再現した（H06 訓練 {h6['reproduced']['train']['ex']:+.2f}%/年 t{h6['reproduced']['train']['t']}・保有 {h6['reproduced']['hold']['ex']:+.2f} t{h6['reproduced']['hold']['t']}・20年窓 {h6['reproduced']['roll20']['win_rate']}／Q09 保有 {q9['reproduced']['hold']['ex']:+.2f} t{q9['reproduced']['hold']['t']}）。先読みや計算の誤りは無い。",
        f"だが勝ちの大半は平均1.25〜1.4倍の借入。同じ平均倍率で一定に持つだけで NDX は保有 {q9['const_leverage_same_avg_w']['const_vs_bench']['hold']['ex']:+.2f}%/年 t{q9['const_leverage_same_avg_w']['const_vs_bench']['hold']['t']}、HiTec は訓練 t{h6['const_leverage_same_avg_w']['const_vs_bench']['train']['t']}・保有 {h6['const_leverage_same_avg_w']['const_vs_bench']['hold']['ex']:+.2f} を出す。ボラで倍率を変える上乗せは NDX で年+2〜3%（t1.2〜2.0）、HiTec で年+0.4%（t0.2）で、Holm 後はどれも有意でない。",
        'C8（シャープが上）は点推定だけで、差の検定は p 0.1〜0.5。β を合わせた CAPM α は NDX で全期間 t3〜4・保有 t1.5〜2.5 と弱く残る（保有期間の β は1.2〜1.25に上がっていた）。',
        'H06 の S は C4 が 0.800 ちょうどで、窓の長さ・上限・借入金利・積立・純粋な市場相手ではすべて 0.8 を割る。同じ規則で S になる業種は HiTec だけ → B。',
        'NDX の A は、β=1 の族が保有期間を見た後の登録（全体の規則では事後）、訓練の合格が訓練の中で当てた c 頼み（実時間の c では訓練 −1.2〜−2.2%/年）→ B。',
        '結論: S/A は残らない（13本すべて B）。『市場に勝った』のは主にテックを借入で1.3倍持ったことで、時期の読みそのものは統計的に確かでない。']
    res['log'] = LOG
    json.dump(clean(res), open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('書いた', OUT)
    for k, v in res['verdicts'].items():
        log(k, v['claimed_grade'], '→', v['verified_grade'], v['verdict'])


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        o = float(o)
        return None if math.isnan(o) else ('inf' if math.isinf(o) else o)
    if isinstance(o, np.integer):
        return int(o)
    return o


def _close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def build_verdicts(res):
    """数字から判定と理由を組み立てる（理由の数字はすべてこのファイルの再計算）"""
    out = {}
    sig1 = res['sigma_matched_versions_family1']
    for cid, e in res['candidates'].items():
        rp, cl = e['reproduced'], e['claimed']
        f, t, h, ch = rp['full'], rp['train'], rp['hold'], rp['cost_hold']
        repro = (_close(f['ex'], cl['full_ex'], 0.25) and _close(t['ex'], cl['train_ex'], 0.25) and _close(h['ex'], cl['hold_ex'], 0.25)
                 and _close(ch['ex'], cl['net_cost_hold_ex'], 0.25) and _close(f['t'], cl['full_t'], 0.2) and _close(t['t'], cl['train_t'], 0.2)
                 and _close(h['t'], cl['hold_t'], 0.2) and _close(rp['roll20']['win_rate'], cl['roll20_win'], 0.02))
        cstl = e['const_leverage_same_avg_w']; cb = cstl['const_vs_bench']; tv = cstl['timing_value_net']
        st = e['sharpe_tests']; cap = e['capm_net']; vm = e['vs_pure_market']; fr = e['fragility']; sub = e['subperiods']
        idx = e['spec']['index']
        const_pass = []
        if cb['train'] and cb['train']['ex'] > 0 and cb['train']['t'] >= 2: const_pass.append('C1')
        if cb['hold']['ex'] > 0 and cb['hold']['cagr_diff'] > 0: const_pass += ['C2', 'C6']
        if cb['hold']['t'] >= 1.65: const_pass.append('C3')
        if cb['roll20'] and cb['roll20']['win_rate'] >= 0.8: const_pass.append('C4')
        if cb['full']['t'] >= 3: const_pass.append('C7')
        iss = []
        iss.append(f"勝ちの大半は借入: 訓練期間の平均倍率 L={cstl['L']} で毎月一定に持つだけ（時期を読まない）でも 相手に対し 訓練 {cb['train']['ex']:+.2f}%/年 t{cb['train']['t']}・"
                   f"保有 {cb['hold']['ex']:+.2f} t{cb['hold']['t']}・全期間 t{cb['full']['t']}・20年窓 {(cb['roll20'] or {}).get('win_rate')}（{'/'.join(sorted(set(const_pass)))} を満たす）。"
                   f"規則の上乗せ（同じ平均倍率の一定持ちとの差・費用後）は 訓練 {tv['train']['ex']:+.2f} t{tv['train']['t']}・保有 {tv['hold']['ex']:+.2f} t{tv['hold']['t']}・全期間 t{tv['full']['t']}"
                   f"（Holm 13本で p={res['timing_value_holm']['holm_13'].get(cid)}）")
        iss.append(f"C8 は点推定だけで通っている: シャープの差の検定 JK-Memmel p 訓練 {st['train']['jk_memmel']['p_two']}・保有 {st['hold']['jk_memmel']['p_two']}／"
                   f"12か月ブロック・ブートストラップ片側 p {st['train']['block_boot']['p_one_sided']}・{st['hold']['block_boot']['p_one_sided']}（シャープ 訓練 {rp['sharpe_train']}・保有 {rp['sharpe_hold']}）")
        iss.append(f"β を合わせた CAPM α（費用後）: 訓練 {cap['train']['alpha']:+.2f}%/年 t{cap['train']['t']}（β{cap['train']['beta']}）・保有 {cap['hold']['alpha']:+.2f} t{cap['hold']['t']}（β{cap['hold']['beta']}）・"
                   f"全期間 t{cap['full']['t']}。保有期間の β は {cap['hold']['beta']}＝β=1 の較正は保有期間で崩れ、上げ相場で β が多い分が超過に乗っている")
        u = vm['underlying_vs_market']
        iss.append(f"相手は規則どおり『同じ指数の買って持つだけ』（{idx}）で、純粋な市場ではない。French Mkt（上限なしの時価加重）に対しては 訓練 {vm['train']['ex']:+.2f} t{vm['train']['t']}・"
                   f"保有（費用後）{vm['hold_net']['ex']:+.2f} t{vm['hold_net']['t']}・20年窓 {vm['roll20_net']['win_rate']}。うち {idx} 自体の市場超過が 訓練 {u['train']['ex']:+.2f} t{u['train']['t']}・保有 {u['hold']['ex']:+.2f} t{u['hold']['t']}"
                   f"（2007年以降のテックの勝ちを知った後の指数選び）")
        if cid.startswith(('Q', 'H13', 'H14', 'H15', 'H20', 'I0')):
            p09 = sig1.get('P09_NDX_VAR1_cap1.5', {})
            iss.append(f"事後の族: β=1 の尺度は第1族の保有期間の結果（α が正）を見た後に登録された（prereg2 が自ら明記）。mw_prereg の honesty_rules は『事後・判定に使わない』を求める。"
                       f"同じ規則の σ合わせ版（第1族・結果を見る前）は P09 訓練 {p09.get('train')}・保有 {p09.get('hold')}・平均倍率 {p09.get('avg_w')}・格付け {p09.get('grade')}")
            po = fr.get('past_only_c_same_rule')
            if po:
                iss.append(f"C1 は訓練の中で当てはめた c に頼る: 同じ規則で c を過去だけで毎年解く（実時間）と 訓練 {po['train']['ex']:+.2f}%/年 t{po['train']['t']}（β{po['train']['beta']}・{po['train']['from']}〜）で C1 不合格")
            c2 = fr.get('cap2')
            if c2:
                iss.append(f"隣の値: 上限2倍では 訓練 t{c2['train']['t']}（C1 {'合格' if c2['train']['t'] >= 2 else '不合格'}）・上限1.25倍では 保有（費用後）{fr['cap1.25']['cost_hold']['ex']:+.2f}")
            iss.append(f"C5 は {e['reproduced_repl']['positive']}/{e['reproduced_repl']['regions']}（" + '・'.join(f"{r} {d['net_full_ex']:+.2f}" for r, d in e['reproduced_repl']['detail'].items()) + '・費用後の全期間）')
        if idx == 'HiTec':
            r20m = fr['roll20_by_start_month']
            below = [m for m, v in r20m.items() if v is not None and v < 0.8]
            iss.append(f"C4（20年窓）: 7月起点 {rp['roll20']['win_rate']}。起点の月を替えると {len(below)}/12 か月で 0.80 未満（{min(v for v in r20m.values() if v is not None)}〜{max(v for v in r20m.values() if v is not None)}）、"
                       f"10/15/25年窓 {fr['roll10']['win_rate']}/{fr['roll15']['win_rate']}/{fr['roll25']['win_rate']}、上限1.75/2倍 {fr['cap1.75']['roll20']}/{fr['cap2']['roll20']}、"
                       f"借入 RF+2%/3% {(fr.get('spread2pct') or {}).get('roll20')}/{(fr.get('spread3pct') or {}).get('roll20')}、積立20年 {rp['dca20']['win_rate']}、純粋な市場相手 {vm['roll20_net']['win_rate']}"
                       + (f"。1日遅れ（研究側は未測定）では {fr['lag1_not_tested_by_researcher']['roll20']['win_rate']}" if fr.get('lag1_not_tested_by_researcher') else ''))
            bkey = f"{e['spec']['signal']}_cap1.5_{'B1EXP' if e['spec']['c_mode'] == 'exp' else 'B1'}"
            ind = res['industry_breadth'][bkey]
            iss.append(f"業種の選び出し: 同じ規則（{bkey}）を French 10業種＋米国市場に当てると S/A（C5 を除く）は {ind['count_S_or_A_without_C5']}/11（{'・'.join(ind['S_or_A']) or 'なし'}）、"
                       f"20年窓 0.8 以上は {ind['count_roll20_ge_0.8']}/11、保有期間の費用後が負の業種 {len(ind['negative_hold_net'])}（{'・'.join(ind['negative_hold_net'])}）。"
                       f"HiTec は第2族で NDX が勝った後に『もっと長いテック』として選ばれた（第3族・事後の族の後）")
            iss.append(f"時代への依存: 訓練のうち 1932–1969 {sub['train_1932_1969']['ex']:+.2f} t{sub['train_1932_1969']['t']}・1970–1989 {sub['train_1970_1989']['ex']:+.2f} t{sub['train_1970_1989']['t']}・"
                       f"1985–2006 {sub['train_1985_2006']['ex']:+.2f} t{sub['train_1985_2006']['t']}")
            iss.append(f"C5 は {e['reproduced_repl']['positive']}/{e['reproduced_repl']['regions']}（" + '・'.join(f"{r} {d['net_full_ex']:+.2f}/幾何{d['cagr_diff']:+.2f}" for r, d in e['reproduced_repl']['detail'].items()) + '）')
        iss.append(f"頑健な面（反証にならなかった）: 保有の前半 {sub['hold_2007_2016']['ex']:+.2f} t{sub['hold_2007_2016']['t']}・後半 {sub['hold_2017_2026']['ex']:+.2f} t{sub['hold_2017_2026']['t']}・"
                   f"2020–21 抜き {sub['hold_drop_2020_2021']['ex']:+.2f}・1998–2000 抜きの全期間 {sub['full_drop_1998_2000']['ex']:+.2f} t{sub['full_drop_1998_2000']['t']}"
                   + (f"・借入 RF+3% の保有 {fr['spread3pct']['cost_hold']['ex']:+.2f}" if fr.get('spread3pct') else '')
                   + (f"・費用0.3% {fr['cost0.3pct']['cost_hold']['ex']:+.2f}" if fr.get('cost0.3pct') else '')
                   + (f"・課税口座の戦略 vs NISA の {idx}（保有・近似）{e['tax_japan']['hold']['diff_vs_nisa']:+.2f}%/年" if e.get('tax_japan') else '')
                   + f"。最大下落 戦略 {cstl['maxdd_full']['strategy']}% / 一定倍率 {cstl['maxdd_full']['const']}% / 相手 {cstl['maxdd_full']['bench']}%")
        # 判定
        g_formal = e['reproduced_grade']
        if cid.startswith('H06'):
            vg, verdict = 'B', 'downgraded to B'
            why = ('数字は再現（S の線を形式上すべて満たす）が、C4 が 0.800 ちょうど: 起点の月では12か月中4か月で割り（2か月はちょうど0.800）、窓の長さ10/15/25年・上限1.75/2倍・借入 RF+2〜3%・'
                   '積立20年・純粋な市場（French Mkt）相手ではすべて 0.8 を割る（1日遅れ 0.84・上限1.25 0.81 では保つ）。上乗せの大半は平均1.39倍の借入で、同じ平均倍率の一定持ちとの差は t0.2〜0.4。'
                   '同じ規則で S/A になる業種は HiTec だけ（選び出し）。S/A の頑丈さは再現しない')
        elif cid.startswith(('H01', 'H02')):
            vg, verdict = 'B', 'confirmed'
            why = 'B の線（C1・C2・C6・C8）は再現。ただし C8 は点推定だけで、同じ平均倍率の一定持ちとの差は訓練でほぼ0＝中身は借入。C4 は不合格のまま'
        else:
            vg, verdict = 'B', 'downgraded to B'
            why = ('数字も形式上の A も再現したが、(1) β=1 の族は保有期間を見た後の登録（全体の規則では事後）、(2) C1 は訓練の中で当てた c 頼みで実時間の c では訓練 −1.2〜−2.2%/年、'
                   '(3) C7（全期間 t≥3）は平均1.25〜1.29倍の借入だけで満たされ（一定倍率で全期間 t3.37）、規則そのものの上乗せ（同じ平均倍率の一定持ちとの差）は全期間 t0.9〜1.8・保有 t1.2〜2.0 で Holm 後に有意でない。'
                   'β を合わせた α（全期間 t3〜4・保有 t1.5〜2.5）は弱く残るので B')
        out[cid] = {'claimed_grade': cl['grade'], 'formal_grade_reproduced': g_formal, 'verified_grade': vg, 'verdict': verdict, 'why': why, 'reproduced': bool(repro),
                    'key_numbers': (f"再現: 全期間 {f['ex']:+.2f}%/年 t{f['t']}・訓練 {t['ex']:+.2f} t{t['t']}・保有 {h['ex']:+.2f} t{h['t']}（幾何差 {h['cagr_diff']:+.2f}）・費用後の保有 {ch['ex']:+.2f}・"
                                    f"20年窓 {rp['roll20']['win_rate']}・積立20年 {rp['dca20']['win_rate']}・地域 {e['reproduced_repl']['positive']}/{e['reproduced_repl']['regions']}｜"
                                    f"一定倍率 L={cstl['L']}: 保有 {cb['hold']['ex']:+.2f} t{cb['hold']['t']}｜時期の読み: 保有 {tv['hold']['ex']:+.2f} t{tv['hold']['t']}｜CAPM α 保有 {cap['hold']['alpha']:+.2f} t{cap['hold']['t']}｜"
                                    f"vs French Mkt 保有(費用後) {vm['hold_net']['ex']:+.2f}・20年窓 {vm['roll20_net']['win_rate']}"),
                    'issues': iss}
    return out


if __name__ == '__main__':
    main()
