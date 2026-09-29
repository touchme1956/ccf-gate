#!/usr/bin/env python3
"""night/mw_industry_verify.py — mw_industry（業種モメンタム）の主張を反証しにいく検証（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」の角度 industry に対する、反証役の検算。
- 取得（French の表・JKP の zip・Yahoo）だけ mw_common の fetcher を使い、
  ポートフォリオの組み立て・超過・NW t・CAGR・転がる窓・積立・費用は**ここで独自に書く**（研究者のコードは読まない・呼ばない）。
- 相手は French Mkt（Mkt−RF + RF・上限なしの時価加重）。業種の時価加重リターン（総リターン）と総リターンどうしで比べる。
- 格付けの線は out/mw_prereg.json（C1〜C8）をそのまま当てる（線は動かさない）。

検証の対象（研究者が A と主張したもの）:
  主: G3_mom12_5 / G1_mom6_5 / G4_mom12_10 / G2_mom6_10
  探索（第1・第2の族の保有期間の結果を見た後に作った）: P9_multi_5 / R5_mom12_5_state / P7_dual_5 / R5_mom6_5_state

使い方: python3 night/mw_industry_verify.py   → out/mw_industry_verify.json
"""
import sys, os, math, json, random, statistics as S, zipfile, io, csv, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけ使う（french_tables / get / jkp_mkt / yahoo）

import numpy as np

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_industry_verify.json')
TRAIN_END, HOLD, RECENT = 200612, 200701, 201307
US_END = 202608
REPL7 = ['jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che']
UNSEEN16 = ['chn', 'hkg', 'idn', 'ind', 'isr', 'ita', 'kor', 'mys', 'nor', 'pak', 'pol', 'rus', 'sgp', 'swe', 'tha', 'vnm']
CLAIMED = json.loads('''{
 "G3_mom12_5": {"grade": "A", "full_ex": 6.97, "full_t": 5.24, "train_ex": 7.96, "train_t": 5.56, "hold_ex": 2.98, "hold_t": 0.92, "hold_cagr_diff": 2.25, "net_cost_hold_ex": 2.63, "roll20_win": 1.0},
 "G1_mom6_5": {"grade": "A", "full_ex": 4.55, "full_t": 3.42, "train_ex": 5.08, "train_t": 3.58, "hold_ex": 2.38, "hold_t": 0.68, "hold_cagr_diff": 1.65, "net_cost_hold_ex": 1.9, "roll20_win": 0.963},
 "G4_mom12_10": {"grade": "A", "full_ex": 5.23, "full_t": 5.37, "train_ex": 6.16, "train_t": 5.7, "hold_ex": 1.49, "hold_t": 0.73, "hold_cagr_diff": 1.26, "net_cost_hold_ex": 1.21, "roll20_win": 1.0},
 "G2_mom6_10": {"grade": "A", "full_ex": 3.98, "full_t": 3.87, "train_ex": 4.67, "train_t": 4.07, "hold_ex": 1.2, "hold_t": 0.53, "hold_cagr_diff": 0.96, "net_cost_hold_ex": 0.81, "roll20_win": 1.0},
 "P9_multi_5": {"grade": "A", "full_ex": 5.75, "full_t": 4.42, "train_ex": 6.13, "train_t": 4.26, "hold_ex": 4.24, "hold_t": 1.39, "hold_cagr_diff": 4.17, "net_cost_hold_ex": 3.56, "roll20_win": 0.963},
 "R5_mom12_5_state": {"grade": "A", "full_ex": 5.98, "full_t": 4.78, "train_ex": 6.5, "train_t": 4.79, "hold_ex": 3.9, "hold_t": 1.28, "hold_cagr_diff": 3.35, "net_cost_hold_ex": 3.58, "roll20_win": 1.0},
 "P7_dual_5": {"grade": "A", "full_ex": 7.16, "full_t": 5.63, "train_ex": 8.03, "train_t": 5.84, "hold_ex": 3.65, "hold_t": 1.18, "hold_cagr_diff": 2.92, "net_cost_hold_ex": 3.31, "roll20_win": 1.0},
 "R5_mom6_5_state": {"grade": "A", "full_ex": 4.58, "full_t": 3.84, "train_ex": 4.97, "train_t": 4.03, "hold_ex": 3.07, "hold_t": 0.91, "hold_cagr_diff": 2.51, "net_cost_hold_ex": 2.65, "roll20_win": 0.987}
}''')


# ───────────────────────── 月の算術 ─────────────────────────
def mshift(m, k):
    y, mo = divmod(m, 100)
    i = y * 12 + mo - 1 + k
    return (i // 12) * 100 + i % 12 + 1


# ───────────────────────── 統計（独自実装） ─────────────────────────
def nwt(x, L=12):
    x = np.asarray(x, float)
    n = len(x)
    if n < 24:
        return None
    e = x - x.mean()
    v = e @ e / n
    for l in range(1, L + 1):
        v += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else None


def geo(xs):
    xs = list(xs)
    return math.exp(sum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def ex_stats(s, b, a=None, z=None):
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nwt(d)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(S.mean(d) * 1200, 2), 't': None if t is None else round(t, 2),
            'cagr_diff': round((geo(s[k] for k in ks) - geo(b[k] for k in ks)) * 100, 2),
            'te': round(S.stdev(d) * math.sqrt(12) * 100, 2)}


def roll20(s, b):
    ks = set(s) & set(b)
    ys = sorted({k // 100 for k in ks})
    res = []
    for y in ys:
        w = [mshift(y * 100 + 7, i) for i in range(240)]
        if not all(k in ks for k in w):
            continue
        res.append((y, round((geo(s[k] for k in w) - geo(b[k] for k in w)) * 100, 2)))
    if not res:
        return None
    v = sorted(x for _, x in res)
    return {'n': len(res), 'win_rate': round(sum(x > 0 for x in v) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(res, key=lambda r: r[1]), 'best': max(res, key=lambda r: r[1])}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    out = []
    for i in range(len(ks) - 240 + 1):
        if ks[i] % 100 != 7:
            continue
        w = ks[i:i + 240]
        if w[-1] != mshift(w[0], 239):
            continue
        a = c = 0.0
        for k in w:
            a = (a + 1) * (1 + s[k]); c = (c + 1) * (1 + b[k])
        out.append((w[0], round(a / c, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'n': len(out), 'win_rate': round(sum(r > 1 for r in v) / len(v), 3), 'median': v[len(v) // 2], 'worst': min(out, key=lambda r: r[1])}


def cal_years(s, b, a, z):
    out = {}
    for y in range(a // 100, z // 100 + 1):
        ks = [k for k in s if k in b and k // 100 == y and a <= k <= z]
        if len(ks) < 6:
            continue
        gs = math.prod(1 + s[k] for k in ks) - 1; gb = math.prod(1 + b[k] for k in ks) - 1
        out[y] = round((gs - gb) * 100, 1)
    return out


def ols_hac(y, X, L=12):
    """y = X b + e。b と Newey-West の t を返す（X の1列目は定数）"""
    y = np.asarray(y, float); X = np.asarray(X, float)
    n = len(y)
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe / n
    for l in range(1, L + 1):
        G = Xe[l:].T @ Xe[:-l] / n
        Sm += (1 - l / (L + 1)) * (G + G.T)
    V = n * XtX_inv @ Sm @ XtX_inv
    return b, b / np.sqrt(np.diag(V))


# ───────────────────────── データ ─────────────────────────
def load_us():
    T = M.french_tables('49_Industry_Portfolios')
    vw = T['Average Value Weighted Returns -- Monthly']
    cols = [c.strip() for c in vw['cols']]
    R = {c: {} for c in cols}
    for m, row in vw['data'].items():
        for c, x in zip(cols, row):
            if x is not None:
                R[c][m] = x / 100
    N = T['Number of Firms in Portfolios']['data']; SZ = T['Average Firm Size']['data']
    ME = {c: {} for c in cols}
    for m in N:
        for j, c in enumerate(cols):
            n_, s_ = N[m][j], SZ.get(m, [None] * len(cols))[j]
            if n_ and s_ and n_ > 0 and s_ > 0:
                ME[c][m] = n_ * s_
    F = [v for k, v in M.french_tables('F-F_Research_Data_Factors').items() if v['freq'] == 'monthly'][0]
    fc = [c.strip() for c in F['cols']]
    ff = {c: {m: row[j] / 100 for m, row in F['data'].items() if row[j] is not None} for j, c in enumerate(fc)}
    mkt = {m: ff['Mkt-RF'][m] + ff['RF'][m] for m in ff['Mkt-RF'] if m in ff['RF']}
    U = [v for k, v in M.french_tables('F-F_Momentum_Factor').items() if v['freq'] == 'monthly'][0]
    umd = {m: row[0] / 100 for m, row in U['data'].items() if row[0] is not None}
    # 合成 R6 の材料: 配当を除く時価加重リターン・Sum BE / Sum ME（行 t は t年7月〜t+1年6月に使う）
    W = M.french_tables('49_Industry_Portfolios_Wout_Div')['Average Value Weighted Returns -- Monthly']
    assert [c.strip() for c in W['cols']] == cols
    RX = {c: {} for c in cols}
    for m, row in W['data'].items():
        for c, x in zip(cols, row):
            if x is not None:
                RX[c][m] = x / 100
    B = T['Sum of BE / Sum of ME']['data']
    BM = {c: {y: row[j] for y, row in B.items() if row[j] is not None and row[j] > 0} for j, c in enumerate(cols)}
    return cols, R, ME, mkt, ff['RF'], ff['SMB'], ff['HML'], ff['Mkt-RF'], umd, RX, BM


class Panel:
    """業種 × 月。累積リターンを前計算の対数の累積和で出す"""

    def __init__(self, R, months):
        self.R = R
        self.months = months
        self.idx = {m: i for i, m in enumerate(months)}
        self.cs, self.cn = {}, {}
        for c, d in R.items():
            ls, cn = [0.0], [0]
            for m in months:
                v = d.get(m)
                ls.append(ls[-1] + (math.log1p(v) if v is not None else 0.0)); cn.append(cn[-1] + (v is not None))
            self.cs[c], self.cn[c] = ls, cn

    def cum(self, c, m, a, b):
        """m−b 〜 m−a 月（a≥1）の累積リターン。1か月でも欠けたら None"""
        assert a >= 1
        i = self.idx.get(m)
        if i is None or i - b < 0:
            return None
        lo, hi = i - b, i - a + 1   # 月インデックス [lo, hi)
        if self.cn[c][hi] - self.cn[c][lo] != hi - lo:
            return None
        return math.exp(self.cs[c][hi] - self.cs[c][lo]) - 1

    def sd(self, c, m, L):
        x = [self.R[c].get(mshift(m, -k)) for k in range(1, L + 1)]
        if any(v is None for v in x):
            return None
        return S.stdev(x)


def top(scores, K, largest=True):
    it = [(v, c) for c, v in scores.items() if v is not None]
    it.sort(key=lambda t: ((-t[0]) if largest else t[0], t[1]))
    return [c for _, c in it[:K]]


def simulate(pick_fn, R, months):
    """pick_fn(m) → 目標の重み dict（毎月入れ替え）。None なら前の重みを値動きのまま持つ。
    戻り値: 月次リターン, 両側の売買 Σ|Δw|, 重み"""
    w = None
    ret, turn, wts = {}, {}, {}
    for m in months:
        tgt = pick_fn(m)
        if tgt is None and w is None:
            continue
        if tgt is not None:
            s = sum(tgt.values()); new = {c: v / s for c, v in tgt.items() if v > 0}
        else:
            new = w
        live = {c: v for c, v in new.items() if R[c].get(m) is not None}
        s = sum(live.values()); live = {c: v / s for c, v in live.items()}
        tv = 0.0 if w is None else sum(abs(live.get(c, 0) - w.get(c, 0)) for c in set(live) | set(w))
        r = sum(v * R[c][m] for c, v in live.items())
        ret[m], turn[m], wts[m] = r, tv, live
        w = {c: v * (1 + R[c][m]) / (1 + r) for c, v in live.items()}
    return ret, turn, wts


def net_of_cost(ret, turn, per_twoway, a=None):
    ks = [k for k in turn if a is None or k >= a]
    ann_turn = 12 * S.mean([turn[k] for k in ks])
    c = ann_turn * per_twoway / 12
    return {k: v - c for k, v in ret.items()}, round(ann_turn, 2)


# ───────────────────────── 規則（独自実装） ─────────────────────────
def rules_us(P, sel, mkt, rf, X=None):
    """研究者の規則の文面（事前登録）だけから組み直す。'__MKT__' は French Mkt そのもの。
    X = {'RX': 配当なし, 'ME': 時価総額, 'BM': BE/ME} があれば P3（残差モメンタム）と R6（合成）も作る"""
    def mom(L, K, skip=0):
        def f(m):
            sc = {c: P.cum(c, m, 1 + skip, L + skip) for c in sel if P.R[c].get(m) is not None}
            ch = top(sc, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    def multi(K):
        def f(m):
            cand = [c for c in sel if P.R[c].get(m) is not None]
            score = {c: [] for c in cand}
            for L in (1, 3, 6, 12):
                v = {c: P.cum(c, m, 1, L) for c in cand}
                v = {c: x for c, x in v.items() if x is not None}
                order = sorted(v, key=lambda c: (v[c], c))
                n = len(order)
                for i, c in enumerate(order):
                    score[c].append(i / (n - 1))
            comp = {c: sum(x) / 4 for c, x in score.items() if len(x) == 4}
            ch = top(comp, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    def down(m):
        ks = [mshift(m, -k) for k in range(1, 37)]
        if not all(k in mkt for k in ks):
            return None
        return sum(math.log1p(mkt[k]) for k in ks) < 0

    def state(inner):
        def f(m):
            d = down(m)
            if d is None:
                return None
            return {'__MKT__': 1.0} if d else inner(m)
        return f

    def dual(K):
        def f(m):
            sc = {c: P.cum(c, m, 1, 12) for c in sel if P.R[c].get(m) is not None}
            ch = top(sc, K)
            ks = [mshift(m, -k) for k in range(1, 13)]
            if len(ch) < K or not all(k in rf for k in ks):
                return None
            rf12 = math.prod(1 + rf[k] for k in ks) - 1
            w = {}
            for c in ch:
                key = c if sc[c] > rf12 else '__MKT__'
                w[key] = w.get(key, 0) + 1 / K
            return w
        return f

    out = {
        'G1_mom6_5': mom(6, 5), 'G2_mom6_10': mom(6, 10), 'G3_mom12_5': mom(12, 5), 'G4_mom12_10': mom(12, 10),
        'P9_multi_5': multi(5), 'R5_mom12_5_state': state(mom(12, 5)), 'P7_dual_5': dual(5), 'R5_mom6_5_state': state(mom(6, 5)),
    }
    if X is None:
        return out, mom
    R, RX, ME, BM = P.R, X['RX'], X['ME'], X['BM']

    # P3: Blitz-Huij-Martens の残差モメンタム（業種なので市場1因子）。値は業種の集合に依らないので LOO でも使い回す
    rcache = X.setdefault('rcache', {})

    def resid(c, m):
        k = (c, m)
        if k in rcache:
            return rcache[k]
        est = [mshift(m, -j) for j in range(1, 37)]
        v = None
        if all(e in R[c] and e in mkt for e in est):
            x = np.array([mkt[e] for e in est]); y = np.array([R[c][e] for e in est])
            vx = ((x - x.mean()) ** 2).sum()
            if vx > 0:
                beta = ((x - x.mean()) * (y - y.mean())).sum() / vx
                alpha = y.mean() - beta * x.mean()
                res = np.array([R[c][mshift(m, -j)] - alpha - beta * mkt[mshift(m, -j)] for j in range(2, 13)])
                sd = res.std(ddof=1)
                v = float(res.mean() / sd) if sd > 0 else None
        rcache[k] = v
        return v

    def resmom(K):
        def f(m):
            ch = top({c: resid(c, m) for c in sel if R[c].get(m) is not None}, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    # R6: 8本の信号の百分位の平均（年次の信号は7月の値を翌年6月まで）
    def jul(m):
        return (m // 100) * 100 + 7 if m % 100 >= 7 else (m // 100 - 1) * 100 + 7

    def bm(c, m):
        return BM[c].get(m // 100 if m % 100 >= 7 else m // 100 - 1)

    def rev120(c, m):
        v = P.cum(c, jul(m), 1, 120)
        return None if v is None else -v

    def seas(c, m):
        v = [R[c][mshift(m, -12 * k)] for k in range(1, 21) if mshift(m, -12 * k) in R[c]]
        return sum(v) / len(v) if len(v) >= 10 else None

    def dy(c, m):
        j = jul(m)
        ks = [mshift(j, -k) for k in range(1, 13)]
        if not all(k in R[c] and k in RX[c] for k in ks):
            return None
        return sum(R[c][k] - RX[c][k] for k in ks)

    def npy(c, m):
        j = jul(m); j0 = mshift(j, -12)
        ks = [mshift(j, -k) for k in range(1, 13)]
        if not all(k in R[c] for k in ks) or j not in ME[c] or j0 not in ME[c]:
            return None
        return sum(math.log1p(R[c][k]) for k in ks) - math.log(ME[c][j] / ME[c][j0])

    def hi52(c, m):
        ks = [mshift(m, -k) for k in range(12, 0, -1)]
        if not all(k in RX[c] for k in ks):
            return None
        p, px = 1.0, []
        for k in ks:
            p *= 1 + RX[c][k]; px.append(p)
        return px[-1] / max(px)

    sigs = [bm, rev120, lambda c, m: P.cum(c, m, 1, 6), lambda c, m: P.cum(c, m, 1, 12), seas, dy, npy, hi52]

    scache = X.setdefault('sigcache', {})   # 信号の値は業種の集合に依らない（順位だけが依る）

    def sv(i, c, m):
        k = (i, c, m)
        if k not in scache:
            scache[k] = sigs[i](c, m)
        return scache[k]

    def combo(K):
        def f(m):
            cand = [c for c in sel if R[c].get(m) is not None]
            pr = {c: [] for c in cand}
            for i in range(len(sigs)):
                v = {c: sv(i, c, m) for c in cand}
                v = {c: x for c, x in v.items() if x is not None}
                if len(v) < 2:
                    continue
                o = sorted(v, key=lambda c: (v[c], c))
                for i, c in enumerate(o):
                    pr[c].append(i / (len(o) - 1))
            ch = top({c: sum(x) / len(x) for c, x in pr.items() if len(x) >= 6}, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    out['P3_resmom_5'] = resmom(5)
    out['R6_combo_5'] = combo(5)
    return out, mom


# ───────────────────────── 格付け（out/mw_prereg.json の線をここで書き直す） ─────────────────────────
def grade(full, train, hold, r20, cost_hold, repl, full_t_only=True):
    c = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0),
         'C2': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4': bool(r20 and r20['win_rate'] >= 0.8),
         'C5': None if not repl else (repl[1] / repl[0] >= 2 / 3),
         'C6': bool(cost_hold and cost_hold['ex'] > 0 and cost_hold['cagr_diff'] > 0),
         'C7': bool(full and (full['t'] or 0) >= 3.0)}
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── JKP の国（GICS 11） ─────────────────────────
def jkp_sectors(ctry):
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{ctry}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = M.get(url, name=f'jkp_industry_{ctry}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    R = {}
    for row in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if row['ret'] in ('', 'NA', 'na'):
            continue
        m = int(row['date'][:4]) * 100 + int(row['date'][5:7])
        R.setdefault(row['gics'], {})[m] = float(row['ret'])
    return R


def country_rules(R, mk):
    months = sorted(set().union(*[set(v) for v in R.values()]))
    P = Panel(R, months)
    secs = sorted(R)

    def mom(L, K=3):
        def f(m):
            ch = top({c: P.cum(c, m, 1, L) for c in secs if R[c].get(m) is not None}, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    def multi(K=3):
        def f(m):
            cand = [c for c in secs if R[c].get(m) is not None]
            sc = {c: [] for c in cand}
            for L in (1, 3, 6, 12):
                v = {c: P.cum(c, m, 1, L) for c in cand}
                v = {c: x for c, x in v.items() if x is not None}
                if len(v) < 2:
                    return None
                o = sorted(v, key=lambda c: (v[c], c))
                for i, c in enumerate(o):
                    sc[c].append(i / (len(o) - 1))
            ch = top({c: sum(x) / 4 for c, x in sc.items() if len(x) == 4}, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    RR = dict(R); RR['__MKT__'] = mk

    def state(inner):
        def f(m):
            ks = [mshift(m, -k) for k in range(1, 37)]
            if not all(k in mk for k in ks):
                return None
            return {'__MKT__': 1.0} if sum(math.log1p(mk[k]) for k in ks) < 0 else inner(m)
        return f

    def dual(K=3):
        def f(m):
            sc = {c: P.cum(c, m, 1, 12) for c in secs if R[c].get(m) is not None}
            ch = top(sc, K)
            if len(ch) < K:
                return None
            w = {}
            for c in ch:
                k = c if sc[c] > 0 else '__MKT__'   # JKP は T-bill を引いた超過＝累積の超過が正なら T-bill に勝った
                w[k] = w.get(k, 0) + 1 / K
            return w
        return f

    def resmom(K=3):
        def score(c, m):
            est = [mshift(m, -j) for j in range(1, 37)]
            if not all(e in R[c] and e in mk for e in est):
                return None
            x = np.array([mk[e] for e in est]); y = np.array([R[c][e] for e in est])
            vx = ((x - x.mean()) ** 2).sum()
            if vx <= 0:
                return None
            beta = ((x - x.mean()) * (y - y.mean())).sum() / vx
            alpha = y.mean() - beta * x.mean()
            res = np.array([R[c][mshift(m, -j)] - alpha - beta * mk[mshift(m, -j)] for j in range(2, 13)])
            sd = res.std(ddof=1)
            return float(res.mean() / sd) if sd > 0 else None

        def f(m):
            ch = top({c: score(c, m) for c in secs if R[c].get(m) is not None}, K)
            return {c: 1.0 for c in ch} if len(ch) == K else None
        return f

    ew = lambda m: {c: 1.0 for c in secs if R[c].get(m) is not None} or None
    out = {}
    for key, f in {'mom12': mom(12), 'mom6': mom(6), 'multi': multi(), 'mom12_state': state(mom(12)), 'mom6_state': state(mom(6)),
                   'dual': dual(), 'resmom': resmom(), 'ew11': ew}.items():
        r, _, _ = simulate(f, RR, [m for m in months if m in mk])
        out[key] = r
    return out


def pooled(per, a=None, z=None):
    ms = sorted(set().union(*[set(v) for v in per.values()]))
    avg = {m: S.mean([v[m] for v in per.values() if m in v]) for m in ms if (a is None or m >= a) and (z is None or m <= z)}
    x = [avg[m] for m in sorted(avg)]
    if len(x) < 24:
        return None
    t = nwt(x)
    return {'ex': round(S.mean(x) * 1200, 2), 't': None if t is None else round(t, 2), 'n': len(x)}


# ───────────────────────── 本体 ─────────────────────────
CLAIMED_B = {
    'P3_resmom_5': {'grade': 'B', 'full_ex': 5.35, 'full_t': 4.93, 'train_ex': 5.94, 'train_t': 4.98, 'hold_ex': 3.03, 'hold_t': 1.2, 'hold_cagr_diff': 2.67, 'net_cost_hold_ex': 2.56, 'roll20_win': 1.0},
    'R6_combo_5': {'grade': 'B', 'full_ex': 6.70, 'full_t': 6.16, 'train_ex': 7.72, 'train_t': 6.67, 'hold_ex': 2.57, 'hold_t': 0.96, 'hold_cagr_diff': 2.55, 'net_cost_hold_ex': 2.04, 'roll20_win': 1.0},
}
FAMILY = {'G1_mom6_5': 'prereg1・主', 'G2_mom6_10': 'prereg1・主', 'G3_mom12_5': 'prereg1・主', 'G4_mom12_10': 'prereg1・主',
          'R5_mom12_5_state': 'prereg2・探索（第1の族の保有期間の年ごとの成績〔2009 −11 を含む〕を見た後）',
          'R5_mom6_5_state': 'prereg2・探索（同上）', 'R6_combo_5': 'prereg2・探索（信号の選び方は訓練期間の t だけ）',
          'P9_multi_5': 'prereg3・探索（第1・第2の族の結果を見た後）', 'P7_dual_5': 'prereg3・探索（同上）', 'P3_resmom_5': 'prereg3・探索（同上）'}
RMAP = {'G1_mom6_5': 'mom6', 'G2_mom6_10': 'mom6', 'G3_mom12_5': 'mom12', 'G4_mom12_10': 'mom12', 'P9_multi_5': 'multi',
        'R5_mom12_5_state': 'mom12_state', 'R5_mom6_5_state': 'mom6_state', 'P7_dual_5': 'dual', 'P3_resmom_5': 'resmom', 'R6_combo_5': None}


def tax_drag(r, b, a, z, tax=0.20315):
    """参考: 課税口座。戦略は毎年の実現益に課税（損は翌年以降へ繰越・期限なし＝楽観側）、市場は最後に一度だけ課税。
    毎月入れ替える戦略はほぼ全部の益を毎年実現する（上限側の近似）"""
    ys = sorted({k // 100 for k in r if a <= k <= z and k in b})
    ws, carry = 1.0, 0.0
    for y in ys:
        ks = [k for k in r if k // 100 == y and a <= k <= z and k in b]
        g = ws * (math.prod(1 + r[k] for k in ks) - 1)
        base = g + carry
        if base > 0:
            ws += g - tax * base; carry = 0.0
        else:
            ws += g; carry = base
    wb = math.prod(1 + b[k] for k in b if a <= k <= z and k in r)
    wb_after = wb - tax * (wb - 1)
    n = len([k for k in r if a <= k <= z and k in b]) / 12
    return {'years': round(n, 1), 'strategy_after_tax_cagr': round((ws ** (1 / n) - 1) * 100, 2),
            'market_after_tax_cagr_deferred': round((wb_after ** (1 / n) - 1) * 100, 2),
            'diff': round((ws ** (1 / n) - wb_after ** (1 / n)) * 100, 2)}


def battery(sid, r, turn, wts, mkt, RR, ME, cols, smb, hml, umd, mktrf):
    full = ex_stats(r, mkt); train = ex_stats(r, mkt, z=TRAIN_END); hold = ex_stats(r, mkt, a=HOLD)
    n05, T2 = net_of_cost(r, turn, 0.0005, a=HOLD)
    n15, _ = net_of_cost(r, turn, 0.0015, a=HOLD)
    n30, _ = net_of_cost(r, turn, 0.0030, a=HOLD)
    hold_months = sorted(k for k in r if k >= HOLD and k in mkt)
    mid = hold_months[len(hold_months) // 2]
    r_ex2021 = {k: v for k, v in r.items() if k // 100 not in (2020, 2021)}
    r_ex9800 = {k: v for k, v in r.items() if k // 100 not in (1998, 1999, 2000)}
    yrs = cal_years(r, mkt, HOLD, US_END)
    ys = sorted(yrs.items(), key=lambda t: -t[1])
    drop1 = {k: v for k, v in r.items() if not (k >= HOLD and k // 100 == ys[0][0])}
    drop2 = {k: v for k, v in r.items() if not (k >= HOLD and k // 100 in (ys[0][0], ys[1][0]))}
    contrib = {}
    for k in hold_months:
        for c, w in wts[k].items():
            contrib[c] = contrib.get(c, 0.0) + w * (RR[c][k] - mkt[k])
    contrib = sorted(((c, round(v / len(hold_months) * 1200, 2)) for c, v in contrib.items()), key=lambda t: -t[1])
    ks = [k for k in hold_months if k in smb and k in hml and k in umd]
    b, tt = ols_hac([r[k] - mkt[k] for k in ks], [[1.0, mktrf[k], smb[k], hml[k], umd[k]] for k in ks])
    shares = []
    for k in hold_months:
        tot = sum(ME[c][k] for c in cols if k in ME[c])
        shares.append(sum(ME[c][k] for c in wts[k] if c in ME and k in ME[c]) / tot)
    return {
        'period': [min(r), max(r)], 'full': full, 'train': train, 'hold': hold, 'recent': ex_stats(r, mkt, a=RECENT),
        'post_2000': ex_stats(r, mkt, a=200001), 'post_2001_ex_1998_2000': ex_stats(r_ex9800, mkt, a=200101),
        'full_ex_1998_2000': ex_stats(r_ex9800, mkt),
        'hold_first_half': ex_stats(r, mkt, a=HOLD, z=mshift(mid, -1)), 'hold_second_half': ex_stats(r, mkt, a=mid),
        'hold_ex_2020_2021': ex_stats(r_ex2021, mkt, a=HOLD),
        'hold_drop_best_year': {'year': ys[0][0], 'stats': ex_stats(drop1, mkt, a=HOLD)},
        'hold_drop_best2_years': {'years': [ys[0][0], ys[1][0]], 'stats': ex_stats(drop2, mkt, a=HOLD)},
        'hold_calendar_years': yrs, 'hold_years_positive': f"{sum(v > 0 for v in yrs.values())}/{len(yrs)}",
        'turnover_twoway_ann_hold': T2,
        'cost_hold_005_twoway(=研究者)': ex_stats(n05, mkt, a=HOLD),
        'cost_hold_015_twoway(=片側0.30%中小型)': ex_stats(n15, mkt, a=HOLD),
        'cost_hold_030_twoway(=片側0.60%)': ex_stats(n30, mkt, a=HOLD),
        'tax_taxable_account_hold_report_only': tax_drag(n05, mkt, HOLD, US_END),
        'roll20': roll20(r, mkt), 'dca20': dca20(r, mkt),
        'hold_industry_contrib_top5': contrib[:5], 'hold_industry_contrib_bottom5': contrib[-5:],
        'hold_factor_regression': {'alpha_ann': round(b[0] * 1200, 2), 't_alpha': round(float(tt[0]), 2),
                                   'b_mktrf': round(float(b[1]), 2), 'b_smb': round(float(b[2]), 2), 't_smb': round(float(tt[2]), 2),
                                   'b_hml': round(float(b[3]), 2), 'b_umd': round(float(b[4]), 2), 't_umd': round(float(tt[4]), 2)},
        'hold_avg_market_share_of_holdings_pct': round(S.mean(shares) * 100, 2),
    }


def main():
    cols, R, ME, mkt, rf, smb, hml, mktrf, umd, RX, BM = load_us()
    months = sorted(m for m in set().union(*[set(v) for v in R.values()]) if m <= US_END and m in mkt)
    sel = [c for c in cols if c != 'Other']
    P = Panel(R, months)
    RR = dict(R); RR['__MKT__'] = mkt
    X = {'RX': RX, 'ME': ME, 'BM': BM}
    out = {'angle': 'industry', 'role': 'adversarial verifier（反証役）', 'generated': datetime.date.today().isoformat(),
           'benchmark': 'French Mkt = Mkt−RF + RF（総リターン・上限なしの時価加重・CRSP 全上場）。業種も総リターン＝総リターンどうし。国は JKP の業種（超過）と JKP の国の市場 vw（超過）＝超過どうし',
           'independence': '取得だけ mw_common（french_tables / get / jkp_mkt / yahoo）。組み立て・超過・NW t（Bartlett ラグ12）・CAGR・転がる20年（7月起点・一括）・積立20年・費用・格付けはここで独自に書いた（研究者の mw_industry.py は呼ばない）。状態・二重モメンタムの「市場」の枠は French Mkt そのもの（研究者は49業種の時価加重の合成）',
           'checked_against_criteria': 'out/mw_prereg.json の C1〜C7（C8 は該当なし）'}

    allvw = lambda m: {c: ME[c][m] for c in cols if m in ME[c] and R[c].get(m) is not None}
    r_all, _, _ = simulate(allvw, R, months)
    out['sanity'] = {'all49_vw_minus_mkt': ex_stats(r_all, mkt), 'mkt_cagr_full': round(geo(mkt[k] for k in months) * 100, 2),
                     'mkt_cagr_2007': round(geo(mkt[k] for k in months if k >= HOLD) * 100, 2),
                     'note': '49業種を月初の ME で加重した合成 − French Mkt が年 +0.10%（追従のぶれ 0.38%）＝データと相手の整合は取れている'}

    rules, mom = rules_us(P, sel, mkt, rf, X)
    res, series = {}, {}
    for sid, f in rules.items():
        r, turn, wts = simulate(f, RR, months)
        series[sid] = (r, turn, wts)
        res[sid] = battery(sid, r, turn, wts, mkt, RR, ME, cols, smb, hml, umd, mktrf)
        res[sid]['family'] = FAMILY[sid]
        e = res[sid]
        print(sid, 'full', e['full']['ex'], e['full']['t'], 'train', e['train']['ex'], e['train']['t'], 'hold', e['hold']['ex'], e['hold']['t'], e['hold']['cagr_diff'],
              'net05', e['cost_hold_005_twoway(=研究者)']['cagr_diff'], 'net15', e['cost_hold_015_twoway(=片側0.30%中小型)']['cagr_diff'],
              'ex2021', e['hold_ex_2020_2021']['cagr_diff'], 'h1', e['hold_first_half']['ex'], 'h2', e['hold_second_half']['ex'], flush=True)

    # 対照: 48業種の等分・無作為（保有期間）
    ew48 = lambda m: {c: 1.0 for c in sel if R[c].get(m) is not None}
    r_ew, _, _ = simulate(ew48, R, months)
    ctrl = {'ew48_monthly': {p: ex_stats(r_ew, mkt, a=a, z=z) for p, a, z in (('full', None, None), ('train', None, TRAIN_END), ('hold', HOLD, None))}}
    rng = random.Random(20260928)
    rnd = {}
    for K in (5, 10):
        hs, fs = [], []
        for it in range(500):
            def f(m, K=K):
                c = [x for x in sel if R[x].get(m) is not None]
                return {x: 1.0 for x in rng.sample(c, K)}
            rr, _, _ = simulate(f, R, months)
            hs.append(ex_stats(rr, mkt, a=HOLD)['ex']); fs.append(ex_stats(rr, mkt)['ex'])
        hs.sort(); fs.sort()
        rnd[K] = hs
        ctrl[f'random{K}'] = {'hold_median': hs[250], 'hold_p90': hs[450], 'hold_p95': hs[475], 'hold_max': hs[-1],
                              'full_median': fs[250], 'full_p95': fs[475], 'n': 500}
    for sid in res:
        K = 10 if sid in ('G2_mom6_10', 'G4_mom12_10') else 5
        h = res[sid]['hold']['ex']
        res[sid]['hold_percentile_vs_random_same_K'] = round(sum(x < h for x in rnd[K]) / len(rnd[K]), 3)
        r = series[sid][0]
        d = {k: r[k] - r_ew[k] + mkt[k] for k in r if k in r_ew}
        res[sid]['hold_minus_ew48'] = ex_stats(d, mkt, a=HOLD)
        res[sid]['full_minus_ew48'] = ex_stats(d, mkt)
    out['controls'] = ctrl

    # 1業種を除く（全候補）: 保有期間の超過が1業種に頼っていないか
    for sid in res:
        vals = []
        for c in sel:
            s2 = [x for x in sel if x != c]
            rl, _ = rules_us(P, s2, mkt, rf, X)
            r, _, _ = simulate(rl[sid], RR, months)
            h = ex_stats(r, mkt, a=HOLD)
            vals.append((c, h['ex'], h['t'], h['cagr_diff']))
        vals.sort(key=lambda t: t[3])
        res[sid]['leave_one_industry_out_hold'] = {'worst5_by_cagr_diff': vals[:5], 'min_ex': min(v[1] for v in vals),
                                                   'min_cagr_diff': vals[0][3], 'n_negative_cagr': sum(v[3] <= 0 for v in vals)}
        print('loo', sid, vals[0], flush=True)

    # 隣のパラメータ（L × K）
    grid = {}
    for L in (3, 6, 9, 12, 18):
        for K in (3, 5, 7, 10, 15):
            r, turn, _ = simulate(mom(L, K), R, months)
            h = ex_stats(r, mkt, a=HOLD); fl = ex_stats(r, mkt); tr = ex_stats(r, mkt, z=TRAIN_END)
            nh, _ = net_of_cost(r, turn, 0.0005, a=HOLD)
            r_ex = {k: v for k, v in r.items() if k // 100 not in (2020, 2021)}
            grid[f'L{L}_K{K}'] = {'full': [fl['ex'], fl['t']], 'train': [tr['ex'], tr['t']], 'hold': [h['ex'], h['t'], h['cagr_diff']],
                                  'net05_hold_cagr_diff': ex_stats(nh, mkt, a=HOLD)['cagr_diff'],
                                  'hold_ex_2020_21_cagr_diff': ex_stats(r_ex, mkt, a=HOLD)['cagr_diff'], 'roll20_win': roll20(r, mkt)['win_rate']}
    for L, sk in ((12, 1), (6, 1)):
        for K in (5, 10):
            r, turn, _ = simulate(mom(L - sk, K, skip=sk), R, months)
            h = ex_stats(r, mkt, a=HOLD); fl = ex_stats(r, mkt)
            grid[f'L{L}skip1_K{K}'] = {'full': [fl['ex'], fl['t']], 'hold': [h['ex'], h['t'], h['cagr_diff']]}
    hv = [v['hold'] for v in grid.values()]
    out['neighbor_grid_momentum'] = {'cells': grid, 'hold_positive': f"{sum(x[0] > 0 for x in hv)}/{len(hv)}",
                                     'hold_t_ge_1_65': f"{sum((x[1] or 0) >= 1.65 for x in hv)}/{len(hv)}",
                                     'hold_cagr_positive': f"{sum(x[2] > 0 for x in hv)}/{len(hv)}",
                                     'net05_cagr_positive': f"{sum(v['net05_hold_cagr_diff'] > 0 for v in grid.values() if 'net05_hold_cagr_diff' in v)}/25",
                                     'ex2020_21_cagr_positive': f"{sum(v['hold_ex_2020_21_cagr_diff'] > 0 for v in grid.values() if 'hold_ex_2020_21_cagr_diff' in v)}/25"}
    print('grid', {k: v for k, v in out['neighbor_grid_momentum'].items() if k != 'cells'}, flush=True)

    # 時価加重版（選んだ業種を ME で）
    vwv = {}
    for L, K in ((12, 5), (6, 5), (12, 10), (6, 10)):
        def f(m, L=L, K=K):
            ch = top({c: P.cum(c, m, 1, L) for c in sel if R[c].get(m) is not None}, K)
            if len(ch) < K:
                return None
            return {c: ME[c][m] for c in ch if m in ME[c]} or None
        r, _, _ = simulate(f, R, months)
        vwv[f'L{L}_K{K}_vw'] = {p: ex_stats(r, mkt, a=a, z=z) for p, a, z in (('full', None, None), ('train', None, TRAIN_END), ('hold', HOLD, None))}
    out['value_weighted_selection'] = vwv

    # 米国 GICS 11（JKP usa）と実在の SPDR 9本
    us = {}
    try:
        Ru = jkp_sectors('usa'); mku = M.jkp_mkt('usa', 'vw')
        cr = country_rules(Ru, mku)
        for key in ('mom12', 'mom6', 'multi', 'mom12_state', 'dual', 'resmom', 'ew11'):
            us[key] = {p: ex_stats(cr[key], mku, a=a, z=z) for p, a, z in (('full', None, None), ('pre2007', None, TRAIN_END), ('hold', HOLD, None))}
    except Exception as e:  # noqa
        us['error'] = str(e)
    try:
        tick = ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY']
        SR = {t: {k: v for k, v in M.yahoo(t).items() if k <= US_END} for t in tick}
        spy = {k: v for k, v in M.yahoo('SPY').items() if k <= US_END}
        sm = sorted(set().union(*[set(v) for v in SR.values()]))
        PS = Panel(SR, sm)
        for L in (12, 6):
            def f(m, L=L):
                ch = top({c: PS.cum(c, m, 1, L) for c in SR if SR[c].get(m) is not None}, 3)
                return {c: 1.0 for c in ch} if len(ch) == 3 else None
            r, _, _ = simulate(f, SR, sm)
            us[f'spdr9_mom{L}_top3_vs_SPY'] = {p: ex_stats(r, spy, a=a, z=z) for p, a, z in (('full', None, None), ('hold', HOLD, None), ('from2009', 200901, None))}
    except Exception as e:  # noqa
        us['spdr_error'] = str(e)
    out['us_coarse_and_real_etf'] = us

    # C5: 7か国（研究者が固定）と16か国（研究者の未見パネル）
    rep, raw, turns = {}, {}, {}
    for ctry in REPL7 + UNSEEN16:
        try:
            Rc = jkp_sectors(ctry); mk = M.jkp_mkt(ctry, 'vw')
        except Exception as e:  # noqa
            rep[ctry] = {'error': str(e)}
            continue
        cr = country_rules(Rc, mk)
        rep[ctry] = {}
        for key, r in cr.items():
            full = ex_stats(r, mk)
            if full is None or full['n'] < 60:
                rep[ctry][key] = {'counted': False}
                continue
            d = {k: r[k] - cr['ew11'][k] + mk[k] for k in r if k in cr['ew11']}
            rep[ctry][key] = {'counted': True, 'full': full, 'pre2007': ex_stats(r, mk, z=TRAIN_END), 'hold': ex_stats(r, mk, a=HOLD),
                              'minus_ew11_full': ex_stats(d, mk), 'minus_ew11_hold': ex_stats(d, mk, a=HOLD)}
            raw.setdefault(key, {})[ctry] = {k: r[k] - mk[k] for k in r if k in mk}
            raw.setdefault(key + '_minus_ew11', {})[ctry] = {k: r[k] - cr['ew11'][k] for k in r if k in cr['ew11']}
    summ = {}
    for grp, cs in (('seen7', REPL7), ('unseen16', UNSEEN16)):
        for key in ('mom12', 'mom6', 'multi', 'mom12_state', 'mom6_state', 'dual', 'resmom', 'ew11'):
            cc = [c for c in cs if rep.get(c, {}).get(key, {}).get('counted')]
            if not cc:
                continue
            pos = lambda fld: sum(1 for c in cc if (rep[c][key][fld] or {}).get('ex', -1) > 0)
            summ[f'{grp}_{key}'] = {
                'countries': len(cc), 'pos_full': pos('full'), 'pos_pre2007': pos('pre2007'), 'pos_hold': pos('hold'),
                'pos_minus_ew11_full': pos('minus_ew11_full'), 'pos_minus_ew11_hold': pos('minus_ew11_hold'),
                'pooled_full': pooled({c: raw[key][c] for c in cc}), 'pooled_hold': pooled({c: raw[key][c] for c in cc}, a=HOLD),
                'pooled_minus_ew11_full': pooled({c: raw[key + '_minus_ew11'][c] for c in cc}) if key != 'ew11' else None,
                'pooled_minus_ew11_hold': pooled({c: raw[key + '_minus_ew11'][c] for c in cc}, a=HOLD) if key != 'ew11' else None,
            }
    out['replication'] = {'note': 'C5 の再現は GICS 11 のうち上位3（49業種の上位5/10 の粗い版）。国の市場は JKP の vw（上限なし）。ew11＝その国の11セクターの等分（等分そのものの効きの対照）。unseen16 の multi・dual・resmom・mom6_state は研究者の未見パネル（prereg4）に無かった＝この検算で初めて見た数字',
                          'summary': summ, 'per_country': rep}
    print('repl', json.dumps({k: (v['pos_full'], v['pos_hold'], v['pos_minus_ew11_hold'], v['countries'], (v['pooled_hold'] or {}).get('ex'), (v['pooled_hold'] or {}).get('t')) for k, v in summ.items()}), flush=True)

    # 格付けの再計算と、頑丈さの検査
    for sid, e in res.items():
        key = RMAP[sid]
        s7 = summ.get(f'seen7_{key}') if key else None
        rf_ = (s7['countries'], s7['pos_full']) if s7 else None
        rh_ = (s7['countries'], s7['pos_hold']) if s7 else None
        rm_ = (s7['countries'], s7['pos_minus_ew11_hold']) if s7 else None
        base = dict(full=e['full'], train=e['train'], hold=e['hold'], r20=e['roll20'])
        g_std, c_std = grade(cost_hold=e['cost_hold_005_twoway(=研究者)'], repl=rf_, **base)
        g_c15, _ = grade(cost_hold=e['cost_hold_015_twoway(=片側0.30%中小型)'], repl=rf_, **base)
        g_rh, _ = grade(cost_hold=e['cost_hold_005_twoway(=研究者)'], repl=rh_, **base)
        g_rm, _ = grade(cost_hold=e['cost_hold_005_twoway(=研究者)'], repl=rm_, **base)
        g_x21, _ = grade(full=e['full'], train=e['train'], hold=e['hold_ex_2020_2021'], r20=e['roll20'], cost_hold=e['hold_ex_2020_2021'], repl=rf_)
        rob = {
            'C2_survives_drop_2020_2021': e['hold_ex_2020_2021']['ex'] > 0 and e['hold_ex_2020_2021']['cagr_diff'] > 0,
            'C2_survives_leave_one_industry_out': e['leave_one_industry_out_hold']['min_cagr_diff'] > 0,
            'C6_survives_small_mid_cost(片側0.30%)': e['cost_hold_015_twoway(=片側0.30%中小型)']['ex'] > 0 and e['cost_hold_015_twoway(=片側0.30%中小型)']['cagr_diff'] > 0,
            'both_holdout_halves_positive': e['hold_first_half']['ex'] > 0 and e['hold_second_half']['ex'] > 0,
            'C5_holds_on_2007_onward': None if not rh_ else rh_[1] / rh_[0] >= 2 / 3,
            'C5_holds_vs_equal_weight_sectors_2007_onward': None if not rm_ else rm_[1] / rm_[0] >= 2 / 3,
        }
        e['regrade'] = {'as_registered': g_std, 'criteria': c_std, 'if_cost_small_mid(片側0.30%)': g_c15,
                        'if_C5_counted_2007_onward': g_rh, 'if_C5_momentum_minus_ew11_2007_onward': g_rm,
                        'if_holdout_without_2020_2021(gross)': g_x21,
                        'repl7_full_pos': rf_, 'repl7_hold_pos': rh_, 'repl7_minus_ew11_hold_pos': rm_}
        e['robustness'] = rob
        cl = CLAIMED.get(sid) or CLAIMED_B[sid]
        e['reproduction_vs_claim'] = {
            'full_ex': [cl['full_ex'], e['full']['ex']], 'full_t': [cl['full_t'], e['full']['t']],
            'train_ex': [cl['train_ex'], e['train']['ex']], 'train_t': [cl['train_t'], e['train']['t']],
            'hold_ex': [cl['hold_ex'], e['hold']['ex']], 'hold_t': [cl['hold_t'], e['hold']['t']],
            'hold_cagr_diff': [cl['hold_cagr_diff'], e['hold']['cagr_diff']],
            'net_cost_hold_ex': [cl['net_cost_hold_ex'], e['cost_hold_005_twoway(=研究者)']['ex']],
            'roll20_win': [cl['roll20_win'], e['roll20']['win_rate']]}
        e['reproduced'] = all(abs(a - b) <= max(0.35, 0.08 * abs(a)) for a, b in e['reproduction_vs_claim'].values())
        e['claimed_grade'] = cl['grade']
    out['candidates'] = res

    try:
        ind = json.load(open(os.path.join(BASE, 'out', 'mw_industry.json')))
        n_tested = ind.get('n_tested') or len(ind.get('tested', []))
        best_hold_t = max((e['hold']['t'] or -9) for e in ind['tested'] if e.get('hold'))
    except Exception:  # noqa
        n_tested, best_hold_t = 73, None
    p_best = math.erfc(best_hold_t / math.sqrt(2)) if best_hold_t else None
    out['multiple_testing'] = {
        'variants_tested_in_angle': n_tested, 'best_hold_t_in_angle': best_hold_t,
        'best_hold_p_two_sided_raw': None if p_best is None else round(p_best, 3),
        'best_hold_p_bonferroni': None if p_best is None else round(min(1, p_best * n_tested), 3),
        'note': 'C7 は全期間 t≥3（Harvey-Liu-Zhu）で通る。全期間の約8割は公表前（Moskowitz-Grinblatt 1999 の発見の標本 1963〜1995 を含む）。保有期間だけならどの版も補正後 p=1.0'}
    add_verdicts(out)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


# ───────────────────────── 判定（反証役の結論） ─────────────────────────
# 保有期間の結果を見た後に、その結果の中の特定の出来事（2009年の勢いの崩れ）を避けるように作られた規則。
# prereg2 の what_was_checked_before_registering に「G3 の保有期間の年ごとの超過は 2009 −11 …」と明記がある。
# out/mw_prereg.json の honesty_rules「保有期間の結果を見て規則を変えたら『事後』…判定には使わない」に当たる。
HOLDOUT_INFORMED = {
    'R5_mom12_5_state': '下げ相場の後は市場を持つ手当ては、G3 の保有期間の 2009 −11%（研究者が prereg2 の登録前に見た）を避ける形。G3 との差は 2009・2010 を 0 にした分だけで、研究者の未見16か国ではこの手当てが保有期間の超過を下げた（4.17→3.16%/年）',
    'R5_mom6_5_state': '同上（G1 に同じ手当て）。未見16か国でも 4.94→3.49%/年 と下げた',
    'P7_dual_5': '二重モメンタムの G3 との差は 2009（+7.8 vs −10.9）にほぼ尽きる（研究者が prereg3 の登録前に見た年）。未見16か国では 4.25 vs 4.17%/年＝足さない',
}


EXTRA_NOTES = {
    'G3_mom12_5': '事前登録1（結果を見る前・論文の既定値）の主。1業種除く・2020-21除く・片側0.30%の費用・保有期間の前半/後半・7か国の2007年以降と等分比、の全部で A を保った。ただし同じ規則を時価加重にすると保有期間は負け、米国のセクターETF（SPDR）・GICS 11 の粗い版では勝っていない',
    'G4_mom12_10': '頑丈さの検査はすべて通ったが薄い（片側0.30%の費用後 +0.31・課税口座なら負け）',
    'P9_multi_5': '探索（第1・第2の族を見た後の prereg3 の10本の中で保有期間が最良＝大きさは選んだ分だけ割り引く）。ただし multi は研究者の未見16か国で検算していなかった規則で、この検算で初めて測ると保有期間 16/16 正・まとめて +5.48%/年 t6.01（11セクター等分との差 +4.88 t7.76）＝事後の設計でも米国外で再現した。米国 GICS 11 の粗い版は保有期間 +0.23',
    'P3_resmom_5': 'C5 を 2007年以降だけで数えると 5/7 で A の線に乗るが、登録どおり（全期間）は 4/7＝B。事後に数え方を変えて上げることはしない。保有期間の前半 +1.12（t0.37）と弱く、2022 の +42.5% に頼る',
    'R6_combo_5': '8本の信号は第1の族の訓練期間の t≥2 だけで選ばれていた（研究者の JSON で確認）。BE/ME・配当・純還元が JKP に無く C5 は N/A＝登録上 A になれない',
}


def add_verdicts(out):
    V = []
    for sid, e in out['candidates'].items():
        rg, rb = e['regrade'], e['robustness']
        g = rg['as_registered']
        fails = [k for k, v in rb.items() if v is False]
        issues = []
        if not rg['criteria']['C3']:
            c5 = rg['criteria']['C5']
            issues.append(f"保有期間の t {e['hold']['t']}（C3 の 1.65 に届かない）。" + ('A は C5（米国外）だけに頼る' if c5 else
                          ('C5 は N/A（米国外の材料が無い）＝B 止まり' if c5 is None else f"C5 も不合格（7か国の全期間で正 {rg['repl7_full_pos'][1]}/7）＝B 止まり")))
        if sid in EXTRA_NOTES:
            issues.append(EXTRA_NOTES[sid])
        if fails:
            issues.append('頑丈さの検査で落ちた: ' + ', '.join(fails))
        if sid in HOLDOUT_INFORMED:
            issues.append('事後の設計: ' + HOLDOUT_INFORMED[sid])
        yrs = e['hold_drop_best2_years']
        issues.append(f"保有期間の最良の2年 {yrs['years']} を除くと 年率差 {yrs['stats']['cagr_diff']:+.2f}")
        issues.append(f"要因回帰（保有期間）: α {e['hold_factor_regression']['alpha_ann']:+.2f}%/年 t{e['hold_factor_regression']['t_alpha']}・UMD {e['hold_factor_regression']['b_umd']} (t{e['hold_factor_regression']['t_umd']})・SMB {e['hold_factor_regression']['b_smb']} (t{e['hold_factor_regression']['t_smb']})")
        tx = e['tax_taxable_account_hold_report_only']
        issues.append(f"課税口座（参考・毎年実現）: 市場（最後に一度課税）との差 {tx['diff']:+.2f}%/年")
        issues = [x for x in issues if x]
        if g == 'A' and (fails or sid in HOLDOUT_INFORMED):
            verdict, vg = 'downgraded to B', 'B'
        elif g == e['claimed_grade']:
            verdict, vg = 'confirmed', g
        else:
            verdict, vg = f'downgraded to {g}', g
        V.append({'name': sid, 'claimed_grade': e['claimed_grade'], 'verified_grade': vg, 'verdict': verdict, 'reproduced': e['reproduced'],
                  'key_numbers': (f"全期間 {e['full']['ex']:+.2f}%/年 t{e['full']['t']}・訓練 {e['train']['ex']:+.2f} t{e['train']['t']}・保有 {e['hold']['ex']:+.2f} t{e['hold']['t']}・"
                                  f"保有の年率差 {e['hold']['cagr_diff']:+.2f}・費用後（片側0.10%）{e['cost_hold_005_twoway(=研究者)']['cagr_diff']:+.2f}・（片側0.30%）{e['cost_hold_015_twoway(=片側0.30%中小型)']['cagr_diff']:+.2f}・"
                                  f"2020-21除く {e['hold_ex_2020_2021']['cagr_diff']:+.2f}・前半/後半 {e['hold_first_half']['ex']:+.2f}/{e['hold_second_half']['ex']:+.2f}・"
                                  f"1業種除く最悪 {e['leave_one_industry_out_hold']['min_cagr_diff']:+.2f}（{e['leave_one_industry_out_hold']['worst5_by_cagr_diff'][0][0]}）・"
                                  f"転がる20年 {e['roll20']['win_rate']}・7か国 全期間{rg['repl7_full_pos']}/保有{rg['repl7_hold_pos']}/等分比{rg['repl7_minus_ew11_hold_pos']}"),
                  'issues': issues})
    out['verdicts'] = V
    us, vw, rs = out['us_coarse_and_real_etf'], out['value_weighted_selection'], out['replication']['summary']
    ng = out['neighbor_grid_momentum']
    out['family_findings'] = [
        f"数字は研究者の主張を再現した（10本とも許容差内。主の G1〜G4 は小数第2位まで一致）。相手は上限なしの時価加重（French Mkt）で、総リターンどうし／超過どうしの取り違えは無い。49業種の時価加重の合成 − French Mkt = {out['sanity']['all49_vw_minus_mkt']['ex']:+.2f}%/年",
        f"A の根拠は C5（米国外）。7か国は全期間 {rs['seen7_mom12']['pos_full']}/7・2007年以降だけでも {rs['seen7_mom12']['pos_hold']}/7・11セクター等分との差でも {rs['seen7_mom12']['pos_minus_ew11_hold']}/7（mom12）。研究者の未見16か国: mom12 保有期間 {rs['unseen16_mom12']['pooled_hold']['ex']:+.2f}%/年 t{rs['unseen16_mom12']['pooled_hold']['t']}（新興国が10か国）",
        f"ただし mom6（G1/G2 の再現）は7か国の 2007年以降・等分との差で {rs['seen7_mom6']['pos_minus_ew11_hold']}/7・まとめて {rs['seen7_mom6']['pooled_minus_ew11_hold']['ex']:+.2f}%/年 t{rs['seen7_mom6']['pooled_minus_ew11_hold']['t']}＝先進国の保有期間では再現しない",
        f"米国の保有期間は、実際に買える形では勝っていない: 選んだ5業種を時価加重 {vw['L12_K5_vw']['hold']['ex']:+.2f}%/年（年率差 {vw['L12_K5_vw']['hold']['cagr_diff']:+.2f}）・米国 GICS 11 の上位3 {us['mom12']['hold']['ex']:+.2f}・SPDR 9本の上位3 {us['spdr9_mom12_top3_vs_SPY']['hold']['ex']:+.2f}（2009〜 {us['spdr9_mom12_top3_vs_SPY']['from2009']['ex']:+.2f}）。勝ちは『細かい49業種を等分』の形に限られる",
        f"隣のパラメータ（L 3〜18か月 × K 3〜15）: 保有期間の年率差が正 {ng['hold_cagr_positive']}・t≥1.65 は {ng['hold_t_ge_1_65']}・2020-21 を除いても正 {ng['ex2020_21_cagr_positive']}（12か月は5/5、6か月は1/5）",
        f"多重検定: この角度で {out['multiple_testing']['variants_tested_in_angle']} 本。保有期間だけで裁けば最良でも補正前 p={out['multiple_testing']['best_hold_p_two_sided_raw']}＝どれも有意でない。C7 は全期間 t≥3 で通るが、全期間は公表前（発見の標本）を大きく含む",
        '保有期間の勝ちは塊: G3 は 2007 +33%・2020 +33%・2022 +37%（商品・エネルギー・Autos〔Tesla〕）、2023 −17%・2024 −30%。10/20年しか勝っていない',
    ]
    return out


if __name__ == '__main__':
    if '--verdicts-only' in sys.argv:
        o = json.load(open(OUT))
        add_verdicts(o)
        json.dump(o, open(OUT, 'w'), ensure_ascii=False, indent=1)
        for v in o['verdicts']:
            print(v['name'], v['claimed_grade'], '→', v['verified_grade'], v['verdict'])
    else:
        main()
