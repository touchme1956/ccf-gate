#!/usr/bin/env python3
"""night/mw_industry.py — 業種（French 49業種）を選んで市場に勝てるか（mw 角度 industry・読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して」。
事前登録: out/mw_industry_prereg.json（測る前に固定）／全体の線: out/mw_prereg.json（C1〜C8・格付け）。
相手: French Mkt（総リターン・上限なし時価加重）。業種の時価加重リターンも総リターン＝総リターンどうしで比べる。
C5（米国外）は JKP の GICS 11セクター（超過）と JKP の国の市場（vw・超過）＝超過どうし。

使い方: python3 night/mw_industry.py            → out/mw_industry.json
        python3 night/mw_industry.py --sanity   → 整合の検査だけ
"""
import sys, os, math, json, statistics as S, subprocess, zipfile, io, csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
PREREG = 'mw_industry_prereg.json'
PREREG_FILES = ['mw_industry_prereg.json', 'mw_industry_prereg2.json', 'mw_industry_prereg3.json', 'mw_industry_prereg4.json']
PREREG2 = 'mw_industry_prereg2.json'
PREREG3 = 'mw_industry_prereg3.json'
PREREG4 = 'mw_industry_prereg4.json'
OUT = 'mw_industry.json'
COST = 0.0005          # 両側の売買 100% あたり 0.05%
ETF_FEE = 0.0030       # 参考: 業種ETFの信託報酬の目安（判定に使わない）
REPL_COUNTRIES = ['jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che']
FIN = ['Banks', 'Insur', 'RlEst', 'Fin']
SIN = ['Smoke', 'Beer']
DEF = ['Food', 'Hshld', 'Util', 'Drugs', 'Hlth', 'MedEq']
SIEGEL = ['Food', 'Soda', 'Beer', 'Smoke', 'Hshld', 'Drugs', 'MedEq', 'Hlth']


# ───────────────────────── 月の算術 ─────────────────────────
def madd(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def mrange(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


# ───────────────────────── データ ─────────────────────────
class Data:
    def __init__(self):
        T = M.french_tables('49_Industry_Portfolios')
        W = M.french_tables('49_Industry_Portfolios_Wout_Div')
        vwt = T['Average Value Weighted Returns -- Monthly']
        self.cols = [c.strip() for c in vwt['cols']]
        wcols = [c.strip() for c in W['Average Value Weighted Returns -- Monthly']['cols']]
        assert wcols == self.cols, '配当なしファイルの列が違う'

        def monthly(tab, scale):
            d = tab['data']
            return {c: {m: row[j] * scale for m, row in d.items() if row[j] is not None} for j, c in enumerate(self.cols)}
        self.R = monthly(vwt, 0.01)
        self.RX = monthly(W['Average Value Weighted Returns -- Monthly'], 0.01)
        N = monthly(T['Number of Firms in Portfolios'], 1)
        SZ = monthly(T['Average Firm Size'], 1)
        # ME_i(m) = 社数 × 平均規模（m の月初＝m−1 月末の時価総額）。社数0・欠測は入れない（0で埋めない）
        self.ME = {c: {m: N[c][m] * SZ[c][m] for m in N[c] if m in SZ[c] and N[c][m] > 0 and SZ[c][m] > 0} for c in self.cols}
        bm = T['Sum of BE / Sum of ME']
        self.BM = {c: {y: row[j] for y, row in bm['data'].items() if row[j] is not None} for j, c in enumerate(self.cols)}
        ff = M.ff_factors()
        self.mkt, self.rf, self.mktrf = ff['mkt'], ff['rf'], ff['mktrf']
        self.months = sorted(set().union(*[set(self.R[c]) for c in self.cols]))
        self.end = min(self.months[-1], max(self.mkt))
        self.selectable = [c for c in self.cols if c != 'Other']

    def has(self, c, m):
        return m in self.R[c]


# ───────────────────────── 信号（m−1 月末以前だけを見る） ─────────────────────────
class Sig:
    """すべての信号は『月 m を持つための値』を返す。見てよいのは m より前の月のリターンと、m の月初の ME だけ"""

    def __init__(self, D):
        self.D = D

    def _rets(self, c, m, L, skip=0):
        ks = [madd(m, -k) for k in range(1 + skip, L + 1 + skip)]
        assert all(k < m for k in ks)
        r = self.D.R[c]
        if not all(k in r for k in ks):
            return None
        return [r[k] for k in ks]

    def cum(self, c, m, L, skip=0):
        x = self._rets(c, m, L, skip)
        return None if x is None else math.exp(math.fsum(math.log1p(v) for v in x)) - 1

    def vol(self, c, m, L=60):
        x = self._rets(c, m, L)
        return None if x is None else S.stdev(x)

    def bm(self, c, m):
        # t 年7月〜t+1 年6月は 行 t（FY t−1 の BE ÷ t−1年12月の ME）
        t = m // 100 if m % 100 >= 7 else m // 100 - 1
        v = self.D.BM[c].get(t)
        return v if v is not None and v > 0 else None

    def dy(self, c, m):
        """m は 7月。m−12〜m−1 の Σ(総リターン − 配当なしリターン)"""
        ks = [madd(m, -k) for k in range(1, 13)]
        r, rx = self.D.R[c], self.D.RX[c]
        if not all(k in r and k in rx for k in ks):
            return None
        return math.fsum(r[k] - rx[k] for k in ks)

    def npy(self, c, m):
        """m は 7月。ln(12か月の総リターン) − ln(ME(m)/ME(m−12))。ME(m) は m の月初＝m−1 月末の値"""
        x = self._rets(c, m, 12)
        me = self.D.ME[c]
        m0 = madd(m, -12)
        if x is None or m not in me or m0 not in me:
            return None
        return math.fsum(math.log1p(v) for v in x) - math.log(me[m] / me[m0])

    def share(self, m):
        me = {c: self.D.ME[c][m] for c in self.D.cols if m in self.D.ME[c]}
        tot = sum(me.values())
        return {c: v / tot for c, v in me.items()} if tot > 0 else {}

    def seas(self, c, m, years=20, need=10):
        r = self.D.R[c]
        v = [r[madd(m, -12 * k)] for k in range(1, years + 1) if madd(m, -12 * k) in r]
        return S.mean(v) if len(v) >= need else None

    def hi52(self, c, m):
        """配当なしの価格指数: m−1 月末の値 ÷ m−12〜m−1 月末の最大値"""
        rx = self.D.RX[c]
        ks = [madd(m, -k) for k in range(12, 0, -1)]   # m−12 … m−1
        if not all(k in rx for k in ks):
            return None
        p, px = 1.0, []
        for k in ks:
            p *= 1 + rx[k]; px.append(p)
        return px[-1] / max(px)


# ───────────────────────── 記録（比重が過去最大） ─────────────────────────
def record_table(D, sig):
    """{年 t: {業種: 7月の比重}}"""
    tab = {}
    for m in D.months:
        if m % 100 == 7:
            tab[m // 100] = sig.share(m)
    return tab


_REC = {}


def records(tab, t, thr, min_hist=10):
    key = (id(tab), t, thr, min_hist)
    if key in _REC:
        return _REC[key]
    out = set()
    for c, s in tab.get(t, {}).items():
        prev = [tab[y][c] for y in tab if y < t and c in tab[y]]
        if len(prev) >= min_hist and s > max(prev) and s >= thr:
            out.add(c)
    _REC[key] = out
    return out


# ───────────────────────── 目標の重み ─────────────────────────
def pick(scores, K, top=True):
    items = [(v, c) for c, v in scores.items() if v is not None]
    items.sort(key=lambda x: (-x[0], x[1]) if top else (x[0], x[1]))
    return [c for _, c in items[:K]]


def make_targets(D, sig):
    """戦略ID → target(m)（dict=目標の重み／None=入れ替えない）"""
    rec_tab = record_table(D, sig)
    avail = lambda m, cs: [c for c in cs if D.has(c, m)]

    def vw_of(cs):
        def f(m):
            w = {c: D.ME[c][m] for c in cs if D.has(c, m) and m in D.ME[c]}
            return w or None
        return f

    def vw_all_except(excl_fn):
        def f(m):
            ex = excl_fn(m)
            w = {c: D.ME[c][m] for c in D.cols if c not in ex and D.has(c, m) and m in D.ME[c]}
            return w or None
        return f

    def ew_static_annual(cs):
        def f(m):
            if m % 100 != 7:
                return None
            a = avail(m, cs)
            return {c: 1.0 for c in a} or None
        return f

    def rank_annual(score, K, top=True, weight='ew'):
        state = {}

        def f(m):
            if m % 100 == 7:
                sc = {c: score(c, m) for c in D.selectable if D.has(c, m)}
                sel = pick(sc, K, top)
                state['sel'] = sel if len(sel) == K else None
            sel = state.get('sel')
            if sel is None:
                return None
            if weight == 'vw':
                w = {c: D.ME[c][m] for c in sel if D.has(c, m) and m in D.ME[c]}
                return w or None
            return {c: 1.0 for c in sel} if m % 100 == 7 else None
        return f

    def rank_monthly(score, K, top=True):
        def f(m):
            sc = {c: score(c, m) for c in D.selectable if D.has(c, m)}
            sel = pick(sc, K, top)
            return {c: 1.0 for c in sel} if len(sel) == K else None
        return f

    def neglect(m):
        if m % 100 != 7:
            return None
        sh = sig.share(m)
        sc = {c: sh[c] for c in D.selectable if c in sh and D.has(c, m)}
        sel = pick(sc, 10, top=False)
        return {c: 1.0 for c in sel} if len(sel) == 10 else None

    def excl_record(thr, lookback=1):
        def ex(m):
            t = m // 100 if m % 100 >= 7 else m // 100 - 1
            out = set()
            for y in range(t - lookback + 1, t + 1):
                out |= records(rec_tab, y, thr)
            return out
        return ex

    def excl_losers(m):
        sc = {c: sig.cum(c, m, 12) for c in D.cols if D.has(c, m)}
        return set(pick(sc, 10, top=False))

    def excl_seas(m):
        sc = {c: sig.seas(c, m) for c in D.cols if D.has(c, m)}
        if sum(v is not None for v in sc.values()) < 20:
            return None
        return set(pick(sc, 10, top=False))

    def vw_ex_seas(m):
        ex = excl_seas(m)
        if ex is None:
            return None
        w = {c: D.ME[c][m] for c in D.cols if c not in ex and D.has(c, m) and m in D.ME[c]}
        return w or None

    def mom_ready(c, m, L):
        return sig.cum(c, m, L)

    T = {
        'A1_sin_vw': vw_of(SIN),
        'A2_sin_ew': ew_static_annual(SIN),
        'A3_def_vw': vw_of(DEF),
        'A4_def_ew': ew_static_annual(DEF),
        'A5_neglect_ew': neglect,
        'A6_siegel_vw': vw_of(SIEGEL),
        'B1_value5': rank_annual(sig.bm, 5),
        'B2_value10': rank_annual(sig.bm, 10),
        'C1_lowvol5': rank_annual(lambda c, m: sig.vol(c, m, 60), 5, top=False),
        'C2_lowvol10': rank_annual(lambda c, m: sig.vol(c, m, 60), 10, top=False),
        'D1_rev60_5': rank_annual(lambda c, m: sig.cum(c, m, 60), 5, top=False),
        'D2_rev60_10': rank_annual(lambda c, m: sig.cum(c, m, 60), 10, top=False),
        'D3_rev120_5': rank_annual(lambda c, m: sig.cum(c, m, 120), 5, top=False),
        'D4_rev120_10': rank_annual(lambda c, m: sig.cum(c, m, 120), 10, top=False),
        'E1_exrecord': vw_all_except(excl_record(0.05)),
        'F1_exfin': vw_all_except(lambda m: set(FIN)),
        'G1_mom6_5': rank_monthly(lambda c, m: mom_ready(c, m, 6), 5),
        'G2_mom6_10': rank_monthly(lambda c, m: mom_ready(c, m, 6), 10),
        'G3_mom12_5': rank_monthly(lambda c, m: mom_ready(c, m, 12), 5),
        'G4_mom12_10': rank_monthly(lambda c, m: mom_ready(c, m, 12), 10),
        'G5_avoidlosers': vw_all_except(excl_losers),
        'H1_seas5': rank_monthly(sig.seas, 5),
        'H2_seas10': rank_monthly(sig.seas, 10),
        'I1_dy5': rank_annual(sig.dy, 5),
        'I2_dy10': rank_annual(sig.dy, 10),
        'I3_npy5': rank_annual(sig.npy, 5),
        'I4_npy10': rank_annual(sig.npy, 10),
        'X1_value5_vw': rank_annual(sig.bm, 5, weight='vw'),
        'X2_value10_vw': rank_annual(sig.bm, 10, weight='vw'),
        'X3_exrecord_any': vw_all_except(excl_record(0.0)),
        'X4_exrecord_5y': vw_all_except(excl_record(0.05, lookback=5)),
        'X5_mom12_annual5': rank_annual(lambda c, m: sig.cum(c, m, 12), 5),
        'X6_mom12_annual10': rank_annual(lambda c, m: sig.cum(c, m, 12), 10),
        'X7_hi52_5': rank_monthly(sig.hi52, 5),
        'X8_hi52_10': rank_monthly(sig.hi52, 10),
        'X9_avoid_seas': vw_ex_seas,
    }
    return T


# ───────────────────────── 運用のエンジン ─────────────────────────
def run(target, R, months):
    """target(m) → dict（目標）か None（入れ替えない）。重みは値動きでずれる。
    戻り値: (月次リターン {m: r}, 両側の売買 {m: Σ|Δw|}, 持ち物 {m: [業種]})"""
    w, out, turn, hold = None, {}, {}, {}
    for m in months:
        tgt = target(m)
        if w is None and tgt is None:
            continue
        if tgt is not None:
            tot = sum(tgt.values())
            new = {c: v / tot for c, v in tgt.items() if v > 0}
        else:
            new = w
        av = {c: v for c, v in new.items() if m in R[c]}
        if not av:
            raise RuntimeError(f'{m}: 持てる業種が無い')
        s = sum(av.values())
        av = {c: v / s for c, v in av.items()}
        tv = 0.0 if w is None else math.fsum(abs(av.get(c, 0.0) - w.get(c, 0.0)) for c in set(av) | set(w))
        r = math.fsum(v * R[c][m] for c, v in av.items())
        out[m], turn[m], hold[m] = r, tv, sorted(av)
        w = {c: v * (1 + R[c][m]) / (1 + r) for c, v in av.items()}
    return out, turn, hold


def ann_turnover(turn, a=None, z=None):
    v = [x for k, x in turn.items() if (a is None or k >= a) and (z is None or k <= z)]
    return 12 * S.mean(v) if v else None


# ───────────────────────── C5: JKP GICS 11セクター ─────────────────────────
def jkp_industry(country):
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{country}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = M.get(url, name=f'jkp_industry_{country}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    rows = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode()))
    out = {}
    for x in rows:
        if x['ret'] in ('', 'NA', 'na'):
            continue
        out.setdefault(x['gics'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    return out


def resid_mom(r, mk, m):
    """Blitz-Huij-Martens: m−36〜m−1 で市場に回帰し、m−12〜m−2 の残差の平均÷標準偏差"""
    est = [madd(m, -k) for k in range(1, 37)]
    if not all(k in r and k in mk for k in est):
        return None
    x = [mk[k] for k in est]; y = [r[k] for k in est]
    mx, my = S.mean(x), S.mean(y)
    vx = math.fsum((a - mx) ** 2 for a in x)
    if vx <= 0:
        return None
    beta = math.fsum((a - mx) * (b - my) for a, b in zip(x, y)) / vx
    alpha = my - beta * mx
    e = [r[k] - alpha - beta * mk[k] for k in (madd(m, -j) for j in range(2, 13))]
    sd = S.stdev(e)
    return S.mean(e) / sd if sd > 0 else None


def repl_targets(R, mk=None):
    """GICS 11セクター版の規則（11のうち3）。R: {sector: {m: 超過}}・mk: 国の市場（超過）"""
    secs = sorted(R)
    has = lambda c, m: c in R and m in R[c]

    def cum(c, m, L):
        ks = [madd(m, -k) for k in range(1, L + 1)]
        if not all(k in R[c] for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(R[c][k]) for k in ks)) - 1

    def vol(c, m, L=60):
        ks = [madd(m, -k) for k in range(1, L + 1)]
        if not all(k in R[c] for k in ks):
            return None
        return S.stdev([R[c][k] for k in ks])

    def seas(c, m):
        v = [R[c][madd(m, -12 * k)] for k in range(1, 21) if madd(m, -12 * k) in R[c]]
        return S.mean(v) if len(v) >= 10 else None

    def rank_monthly(score, K=3, top=True):
        def f(m):
            sc = {c: score(c, m) for c in secs if has(c, m)}
            sel = pick(sc, K, top)
            return {c: 1.0 for c in sel} if len(sel) == K else None
        return f

    def rank_annual(score, K=3, top=True):
        st = {}

        def f(m):
            if m % 100 == 7:
                sc = {c: score(c, m) for c in secs if has(c, m)}
                sel = pick(sc, K, top)
                st['sel'] = sel if len(sel) == K else None
                return {c: 1.0 for c in st['sel']} if st['sel'] else None
            return None
        return f

    def static(cs):
        def f(m):
            if m % 100 != 7:
                return None
            a = [c for c in cs if has(c, m)]
            return {c: 1.0 for c in a} if len(a) == len(cs) else None
        return f

    def cum_skip(c, m, a, b):
        ks = [madd(m, -k) for k in range(a, b + 1)]
        if not all(k in R[c] for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(R[c][k]) for k in ks)) - 1

    def resmom(c, m):
        return resid_mom(R[c], mk, m) if mk else None

    def invvol(m):
        sc = {c: cum(c, m, 12) for c in secs if has(c, m)}
        sel = pick(sc, 3)
        if len(sel) < 3:
            return None
        w = {}
        for c in sel:
            v = vol(c, m, 12)
            if not v:
                return None
            w[c] = 1 / v
        return w

    def multi(m):
        cand = [c for c in secs if has(c, m)]
        pr = {c: [] for c in cand}
        for L in (1, 3, 6, 12):
            v = {c: cum(c, m, L) for c in cand}
            v = {c: x for c, x in v.items() if x is not None}
            if len(v) < 2:
                return None
            order = sorted(v, key=lambda c: (v[c], c))
            for i, c in enumerate(order):
                pr[c].append(i / (len(order) - 1))
        sel = pick({c: S.mean(x) for c, x in pr.items() if len(x) == 4}, 3)
        return {c: 1.0 for c in sel} if len(sel) == 3 else None

    def quarterly(score):
        st = {}

        def f(m):
            if m % 100 in (1, 4, 7, 10):
                sc = {c: score(c, m) for c in secs if has(c, m)}
                sel = pick(sc, 3)
                return {c: 1.0 for c in sel} if len(sel) == 3 else None
            return None
        return f

    return {
        'mom1': rank_monthly(lambda c, m: cum(c, m, 1)),
        'mom12_7': rank_monthly(lambda c, m: cum_skip(c, m, 7, 12)),
        'resmom': rank_monthly(resmom),
        'invvol': invvol,
        'multi': multi,
        'mom12q': quarterly(lambda c, m: cum(c, m, 12)),
        'def': static(['30', '35', '55']),
        'siegel': static(['30', '35']),
        'lowvol': rank_annual(lambda c, m: vol(c, m), top=False),
        'rev60': rank_annual(lambda c, m: cum(c, m, 60), top=False),
        'rev120': rank_annual(lambda c, m: cum(c, m, 120), top=False),
        'mom6': rank_monthly(lambda c, m: cum(c, m, 6)),
        'mom12': rank_monthly(lambda c, m: cum(c, m, 12)),
        'mom12a': rank_annual(lambda c, m: cum(c, m, 12)),
        'seas': rank_monthly(seas),
    }


REPL_MAP = {'A3_def_vw': 'def', 'A4_def_ew': 'def', 'A6_siegel_vw': 'siegel', 'C1_lowvol5': 'lowvol', 'C2_lowvol10': 'lowvol',
            'D1_rev60_5': 'rev60', 'D2_rev60_10': 'rev60', 'D3_rev120_5': 'rev120', 'D4_rev120_10': 'rev120',
            'G1_mom6_5': 'mom6', 'G2_mom6_10': 'mom6', 'G3_mom12_5': 'mom12', 'G4_mom12_10': 'mom12',
            'H1_seas5': 'seas', 'H2_seas10': 'seas', 'X5_mom12_annual5': 'mom12a', 'X6_mom12_annual10': 'mom12a'}


RAW = {}


def replication():
    res = {}
    for ctry in REPL_COUNTRIES:
        try:
            R = jkp_industry(ctry)
            mk = M.jkp_mkt(ctry, 'vw')
        except Exception as e:  # noqa
            res[ctry] = {'error': str(e)}
            continue
        months = sorted(set().union(*[set(v) for v in R.values()]))
        base = {}
        for key, tg in list(repl_targets(R, mk).items()) + [('mom6_state', None), ('mom12_state', None), ('dual', 'dual')]:
            if tg == 'dual':
                r = {}
                for m in months:
                    if m not in mk:
                        continue
                    sc = {c: cum_g(R, c, m, 12) for c in R if m in R[c]}
                    sel = pick(sc, 3)
                    if len(sel) < 3:
                        continue
                    r[m] = S.mean([R[c][m] if sc[c] > 0 else mk[m] for c in sel])
            elif tg is None:
                src = base[key.replace('_state', '')]
                r = {}
                for m, v in src.items():
                    ks36 = [madd(m, -k) for k in range(1, 37)]
                    if not all(k in mk for k in ks36) or m not in mk:
                        continue
                    down = math.fsum(math.log1p(mk[k]) for k in ks36) < 0
                    r[m] = mk[m] if down else v
            else:
                r, turn, _ = run(tg, R, months)
                base[key] = r
            ks = sorted(k for k in r if k in mk)
            if len(ks) < 60:
                res.setdefault(key, {})[ctry] = {'months': len(ks), 'counted': False}
                continue
            ex = [r[k] - mk[k] for k in ks]
            RAW.setdefault(key, {})[ctry] = {k: r[k] - mk[k] for k in ks}
            res.setdefault(key, {})[ctry] = {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'counted': True,
                                              'ex_ann': round(S.mean(ex) * 1200, 2), 't': (lambda t: None if t is None else round(t, 2))(M.nw_t(ex)),
                                              'cagr_diff': round((M.cagr([r[k] for k in ks]) - M.cagr([mk[k] for k in ks])) * 100, 2)}
    return res


def repl_summary(rep, key):
    d = rep.get(key) or {}
    cnt = [v for v in d.values() if isinstance(v, dict) and v.get('counted')]
    if not cnt:
        return None
    return {'regions': len(cnt), 'positive': sum(1 for v in cnt if v['ex_ann'] > 0)}


# ───────────────────────── 整合の検査 ─────────────────────────
def sanity(D, sig):
    out = {}
    m = D.mkt
    out['french_mkt_cagr_full'] = round(M.cagr(m) * 100, 2)
    out['french_mkt_cagr_2007'] = round(M.cagr(M.window(m, M.HOLD_START)) * 100, 2)
    allvw = lambda mm: {c: D.ME[c][mm] for c in D.cols if D.has(c, mm) and mm in D.ME[c]}
    r, turn, _ = run(allvw, D.R, D.months)
    st = M.excess_stats(r, m)
    out['all49_vw_vs_mkt'] = {'ex_ann': st['ex_ann'], 'te': st['te'], 'note': '49業種を月初の ME で加重した合成 − French Mkt（±0.2%/年以内なら整合）'}
    # 意図的な後知恵: その月のリターンが最も高い5業種（戦略ではない・道具の感度の確認）
    cheat = lambda mm: (lambda sc: {c: 1.0 for c in pick(sc, 5)})({c: D.R[c][mm] for c in D.selectable if D.has(c, mm)})
    r2, _, _ = run(cheat, D.R, D.months)
    st2 = M.excess_stats(r2, m)
    out['lookahead_placebo'] = {'ex_ann': st2['ex_ann'], 'note': '同じ月のリターンで選ぶ（後知恵）と桁違いになる＝エンジンは後知恵をそのまま成績に出す。本番の信号は m より前しか見ない（_rets で assert）'}
    return out


# ───────────────────────── 評価 ─────────────────────────
def r2(x):
    return None if x is None else round(x, 2)


def evaluate(sid, r, turn, b, pub_year=None):
    ks = sorted(k for k in r if k in b)
    r = {k: r[k] for k in ks}
    full = M.excess_stats(r, b)
    train = M.excess_stats(r, b, z=M.TRAIN_END)
    hold = M.excess_stats(r, b, a=M.HOLD_START)
    recent = M.excess_stats(r, b, a=M.RECENT_START)
    post = M.excess_stats(r, b, a=(pub_year + 1) * 100 + 1) if pub_year else None
    t_hold = ann_turnover(turn, a=M.HOLD_START)
    t_full = ann_turnover(turn)
    cost_hold = M.excess_stats(M.apply_cost(r, t_hold, COST), b, a=M.HOLD_START) if t_hold is not None else None
    cost_full = M.excess_stats(M.apply_cost(r, t_full, COST), b) if t_full is not None else None
    fee_hold = M.excess_stats({k: v - ETF_FEE / 12 for k, v in M.apply_cost(r, t_hold, COST).items()}, b, a=M.HOLD_START) if t_hold is not None else None
    return {'id': sid, 'start': ks[0], 'end': ks[-1],
            'turnover_twoway_ann': {'full': r2(t_full), 'hold': r2(t_hold)},
            'full': full, 'train': train, 'hold': hold, 'recent': recent, 'post_pub': post,
            'cost_hold': cost_hold, 'cost_full': cost_full, 'fee030_hold_report_only': fee_hold,
            'roll20': M.rolling(r, b, 20), 'dca20': M.dca(r, b, 20),
            'maxdd': round(M.maxdd(r) * 100, 1), 'maxdd_mkt_same': round(M.maxdd({k: b[k] for k in ks}) * 100, 1)}


def git_sha(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── 第2の族（prereg2・探索） ─────────────────────────
class GenData:
    """French の N 業種ファイル（R・ME・選べる業種）"""

    def __init__(self, n):
        T = M.french_tables(f'{n}_Industry_Portfolios')
        vwt = T['Average Value Weighted Returns -- Monthly']
        self.cols = [c.strip() for c in vwt['cols']]

        def monthly(tab, scale):
            d = tab['data']
            return {c: {m: row[j] * scale for m, row in d.items() if row[j] is not None} for j, c in enumerate(self.cols)}
        self.R = monthly(vwt, 0.01)
        N = monthly(T['Number of Firms in Portfolios'], 1)
        SZ = monthly(T['Average Firm Size'], 1)
        self.ME = {c: {m: N[c][m] * SZ[c][m] for m in N[c] if m in SZ[c] and N[c][m] > 0 and SZ[c][m] > 0} for c in self.cols}
        self.months = sorted(set().union(*[set(self.R[c]) for c in self.cols]))
        self.selectable = [c for c in self.cols if c != 'Other']

    def has(self, c, m):
        return m in self.R[c]


def cum_g(R, c, m, L):
    ks = [madd(m, -k) for k in range(1, L + 1)]
    if not all(k in R[c] for k in ks):
        return None
    return math.exp(math.fsum(math.log1p(R[c][k]) for k in ks)) - 1


def mom_target(Dx, L, K, weight='ew', min_share=None):
    def f(m):
        cand = [c for c in Dx.selectable if Dx.has(c, m)]
        if min_share is not None:
            me = {c: Dx.ME[c][m] for c in Dx.cols if m in Dx.ME[c]}
            tot = sum(me.values())
            cand = [c for c in cand if c in me and tot > 0 and me[c] / tot >= min_share]
        sel = pick({c: cum_g(Dx.R, c, m, L) for c in cand}, K)
        if len(sel) < K:
            return None
        if weight == 'vw':
            w = {c: Dx.ME[c][m] for c in sel if m in Dx.ME[c]}
            return w or None
        return {c: 1.0 for c in sel}
    return f


def state_target(D, mom):
    allvw = lambda m: {c: D.ME[c][m] for c in D.cols if D.has(c, m) and m in D.ME[c]}

    def f(m):
        ks = [madd(m, -k) for k in range(1, 37)]
        if not all(k in D.mkt for k in ks):
            return None
        down = math.fsum(math.log1p(D.mkt[k]) for k in ks) < 0
        return allvw(m) if down else mom(m)
    return f


def combo_target(D, sig, K):
    cache = {}

    def jul(m):
        return (m // 100) * 100 + 7 if m % 100 >= 7 else (m // 100 - 1) * 100 + 7

    def annual(name, fn, c, m):
        k = (name, c, jul(m))
        if k not in cache:
            cache[k] = fn(c, jul(m))
        return cache[k]

    sigs = [
        ('bm', lambda c, m: sig.bm(c, m)),
        ('rev120', lambda c, m: (lambda v: None if v is None else -v)(annual('rev120', lambda cc, mm: sig.cum(cc, mm, 120), c, m))),
        ('mom6', lambda c, m: sig.cum(c, m, 6)),
        ('mom12', lambda c, m: sig.cum(c, m, 12)),
        ('seas', lambda c, m: sig.seas(c, m)),
        ('dy', lambda c, m: annual('dy', sig.dy, c, m)),
        ('npy', lambda c, m: annual('npy', sig.npy, c, m)),
        ('hi52', lambda c, m: sig.hi52(c, m)),
    ]

    def f(m):
        cand = [c for c in D.selectable if D.has(c, m)]
        pr = {c: [] for c in cand}
        for _, fn in sigs:
            v = {c: fn(c, m) for c in cand}
            v = {c: x for c, x in v.items() if x is not None}
            if len(v) < 2:
                continue
            order = sorted(v, key=lambda c: (v[c], c))
            for i, c in enumerate(order):
                pr[c].append(i / (len(order) - 1))
        comp = {c: S.mean(x) for c, x in pr.items() if len(x) >= 6}
        sel = pick(comp, K)
        return {c: 1.0 for c in sel} if len(sel) == K else None
    return f


def spdr_data():
    tick = ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY']
    R = {t: {k: v for k, v in M.yahoo(t).items() if k <= 202608} for t in tick}
    spy = {k: v for k, v in M.yahoo('SPY').items() if k <= 202608}
    return R, spy


def part2(D, sig, rep):
    pre = json.load(open(os.path.join(BASE, 'out', PREREG2)))
    specs = {s['id']: s for s in pre['strategies']}
    rows = []
    T = {}
    for n in (10, 12, 17, 30, 38, 48):
        Dx = GenData(n)
        K = max(2, round(n / 5))
        for L in (6, 12):
            T[f'R1_n{n}_mom{L}'] = (mom_target(Dx, L, K), Dx.R, Dx.months, D.mkt)
    T['R2_mom6_5_vw'] = (mom_target(D, 6, 5, 'vw'), D.R, D.months, D.mkt)
    T['R2_mom6_10_vw'] = (mom_target(D, 6, 10, 'vw'), D.R, D.months, D.mkt)
    T['R2_mom12_5_vw'] = (mom_target(D, 12, 5, 'vw'), D.R, D.months, D.mkt)
    T['R2_mom12_10_vw'] = (mom_target(D, 12, 10, 'vw'), D.R, D.months, D.mkt)
    T['R3_mom12_5_inv'] = (mom_target(D, 12, 5, min_share=0.01), D.R, D.months, D.mkt)
    T['R3_mom12_10_inv'] = (mom_target(D, 12, 10, min_share=0.01), D.R, D.months, D.mkt)
    SR, spy = spdr_data()
    sm = sorted(set().union(*[set(v) for v in SR.values()]))

    class SD:
        pass
    sd = SD(); sd.R = SR; sd.ME = {}; sd.cols = list(SR); sd.selectable = list(SR); sd.has = lambda c, m: m in SR[c]
    T['R4_spdr_mom12'] = (mom_target(sd, 12, 3), SR, sm, spy)
    T['R4_spdr_mom6'] = (mom_target(sd, 6, 3), SR, sm, spy)
    T['R5_mom6_5_state'] = (state_target(D, mom_target(D, 6, 5)), D.R, D.months, D.mkt)
    T['R5_mom12_5_state'] = (state_target(D, mom_target(D, 12, 5)), D.R, D.months, D.mkt)
    T['R6_combo_5'] = (combo_target(D, sig, 5), D.R, D.months, D.mkt)
    T['R6_combo_10'] = (combo_target(D, sig, 10), D.R, D.months, D.mkt)
    assert set(T) == set(specs), set(T) ^ set(specs)
    for sid, spec in specs.items():
        tg, R, months, bench = T[sid]
        r, turn, hold = run(tg, R, months)
        ev = evaluate(sid, r, turn, bench, None)
        ev.update({'primary': False, 'prereg': PREREG2, 'family': 'prereg2_' + spec['group'], 'rule': spec['rule'],
                   'benchmark': spec.get('benchmark', 'French Mkt')})
        key = spec.get('repl')
        key = key.split(':')[0] if key else None
        ev['repl_key'] = key
        ev['repl'] = repl_summary(rep, key) if key else None
        ev['repl_detail'] = rep.get(key) if key else None
        last = max(hold)
        ev['holding_last'] = {'month': last, 'industries': hold[last] if len(hold[last]) <= 12 else f'{len(hold[last])}業種'}
        rows.append(ev)
    return rows


def diagnostics(D):
    """事後の診断（判定しない）: 等分の効き・無作為に5業種を選ぶ偽物の分布"""
    import random
    b = D.mkt
    out = {}
    ewA = lambda m: ({c: 1.0 for c in D.selectable if D.has(c, m)} if m % 100 == 7 else None)
    ewM = lambda m: {c: 1.0 for c in D.selectable if D.has(c, m)}
    for name, f in (('ew48_annual', ewA), ('ew48_monthly', ewM)):
        r, _, _ = run(f, D.R, D.months)
        out[name] = {k: M.excess_stats(r, b, a=a, z=z) for k, a, z in (('full', None, None), ('train', None, M.TRAIN_END), ('hold', M.HOLD_START, None))}

    def mean_ex(r, a=None, z=None):
        v = [r[k] - b[k] for k in r if k in b and (a is None or k >= a) and (z is None or k <= z)]
        return S.mean(v) * 1200
    res = []
    for it in range(200):
        rng = random.Random(it)
        f = lambda m: {c: 1.0 for c in rng.sample([c for c in D.selectable if D.has(c, m)], 5)}
        r, _, _ = run(f, D.R, D.months)
        res.append((mean_ex(r), mean_ex(r, z=M.TRAIN_END), mean_ex(r, a=M.HOLD_START)))
    for i, lab in enumerate(('full', 'train', 'hold')):
        v = sorted(x[i] for x in res)
        out[f'random5_monthly_{lab}'] = {'median': round(v[100], 2), 'p95': round(v[189], 2), 'max': round(v[-1], 2), 'n': 200}
    return out


# ───────────────────────── 第3の族（prereg3・探索） ─────────────────────────
def daily_counts(D):
    """49業種の日次（時価加重）→ {業種: {yyyymm: (上げた日, 下げた日, 日数)}}"""
    T = M.french_tables('49_Industry_Portfolios_daily')
    t = T['Average Value Weighted Returns -- Daily']
    cols = [c.strip() for c in t['cols']]
    assert cols == D.cols
    out = {c: {} for c in cols}
    for d, row in t['data'].items():
        ym = d // 100
        for c, x in zip(cols, row):
            if x is None:
                continue
            a = out[c].get(ym, (0, 0, 0))
            out[c][ym] = (a[0] + (x > 0), a[1] + (x < 0), a[2] + 1)
    return out


def part3_targets(D, sig):
    dc = daily_counts(D)
    R = D.R
    allvw = lambda m: {c: D.ME[c][m] for c in D.cols if D.has(c, m) and m in D.ME[c]}
    cand = lambda m: [c for c in D.selectable if D.has(c, m)]

    def rank_m(score, K):
        def f(m):
            sel = pick({c: score(c, m) for c in cand(m)}, K)
            return {c: 1.0 for c in sel} if len(sel) == K else None
        return f

    def cum_skip(c, m, a, b):
        ks = [madd(m, -k) for k in range(a, b + 1)]
        if not all(k in R[c] for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(R[c][k]) for k in ks)) - 1

    def fip(Kpre, K):
        def f(m):
            sc = {c: sig.cum(c, m, 12) for c in cand(m)}
            pre = pick(sc, Kpre)
            if len(pre) < Kpre:
                return None
            ids = {}
            for c in pre:
                ms = [madd(m, -k) for k in range(1, 13)]
                if not all(k in dc[c] for k in ms):
                    continue
                npos = sum(dc[c][k][0] for k in ms); nneg = sum(dc[c][k][1] for k in ms); n = sum(dc[c][k][2] for k in ms)
                ids[c] = (1 if sc[c] > 0 else -1 if sc[c] < 0 else 0) * (nneg - npos) / n
            sel = pick(ids, K, top=False)
            return {c: 1.0 for c in sel} if len(sel) == K else None
        return f

    def dual(m):
        sc = {c: sig.cum(c, m, 12) for c in cand(m)}
        sel = pick(sc, 5)
        ks = [madd(m, -k) for k in range(1, 13)]
        if len(sel) < 5 or not all(k in D.rf for k in ks):
            return None
        rf12 = math.exp(math.fsum(math.log1p(D.rf[k]) for k in ks)) - 1
        w = {}
        mw = allvw(m); tot = sum(mw.values())
        for c in sel:
            if sc[c] > rf12:
                w[c] = w.get(c, 0.0) + 0.2
            else:
                for cc, v in mw.items():
                    w[cc] = w.get(cc, 0.0) + 0.2 * v / tot
        return w

    def invvol(m):
        sel = pick({c: sig.cum(c, m, 12) for c in cand(m)}, 5)
        if len(sel) < 5:
            return None
        w = {}
        for c in sel:
            v = sig.vol(c, m, 12)
            if not v:
                return None
            w[c] = 1 / v
        return w

    def multi(m):
        cs = cand(m)
        pr = {c: [] for c in cs}
        for L in (1, 3, 6, 12):
            v = {c: sig.cum(c, m, L) for c in cs}
            v = {c: x for c, x in v.items() if x is not None}
            if len(v) < 2:
                return None
            order = sorted(v, key=lambda c: (v[c], c))
            for i, c in enumerate(order):
                pr[c].append(i / (len(order) - 1))
        sel = pick({c: S.mean(x) for c, x in pr.items() if len(x) == 4}, 5)
        return {c: 1.0 for c in sel} if len(sel) == 5 else None

    g3 = rank_m(lambda c, m: sig.cum(c, m, 12), 5)
    return {
        'P1_mom1_5': rank_m(lambda c, m: sig.cum(c, m, 1), 5),
        'P2_mom12_7_5': rank_m(lambda c, m: cum_skip(c, m, 7, 12), 5),
        'P3_resmom_5': rank_m(lambda c, m: resid_mom(R[c], D.mkt, m), 5),
        'P4_resmom_10': rank_m(lambda c, m: resid_mom(R[c], D.mkt, m), 10),
        'P5_fip_5': fip(10, 5),
        'P6_fip_10': fip(20, 10),
        'P7_dual_5': dual,
        'P8_invvol_5': invvol,
        'P9_multi_5': multi,
        'P10_mom12_5_q': lambda m: g3(m) if m % 100 in (1, 4, 7, 10) else None,
    }


def part3(D, sig, rep):
    pre = json.load(open(os.path.join(BASE, 'out', PREREG3)))
    specs = {s['id']: s for s in pre['strategies']}
    T = part3_targets(D, sig)
    assert set(T) == set(specs), set(T) ^ set(specs)
    rows = []
    for sid, spec in specs.items():
        r, turn, hold = run(T[sid], D.R, D.months)
        ev = evaluate(sid, r, turn, D.mkt, spec.get('pub_year'))
        ev.update({'primary': False, 'prereg': PREREG3, 'family': 'prereg3_momentum_refinements', 'rule': spec['rule']})
        key = spec.get('repl')
        key = key.split(':')[0] if key else None
        ev['repl_key'] = key
        ev['repl'] = repl_summary(rep, key) if key else None
        ev['repl_detail'] = rep.get(key) if key else None
        last = max(hold)
        ev['holding_last'] = {'month': last, 'industries': hold[last] if len(hold[last]) <= 12 else f'{len(hold[last])}業種'}
        rows.append(ev)
    return rows


def pooled_repl(rep_raw_series):
    """国を月ごとに平均した超過の t（参考・判定しない）"""
    out = {}
    for key, per in rep_raw_series.items():
        ms = sorted(set().union(*[set(v) for v in per.values()])) if per else []
        avg = {m: S.mean([v[m] for v in per.values() if m in v]) for m in ms if sum(m in v for v in per.values()) == len(per)}
        if len(avg) < 60:
            continue
        x = [avg[m] for m in sorted(avg)]
        t = M.nw_t(x)
        out[key] = {'countries': len(per), 'from': min(avg), 'to': max(avg), 'ex_ann': round(S.mean(x) * 1200, 2), 't': None if t is None else round(t, 2)}
    return out


def us_gics_check():
    """米国の GICS 11（JKP usa・1999〜2025）で上位3の規則（参考・判定しない・実在のセクターETFに近い形）"""
    R = jkp_industry('usa')
    mk = M.jkp_mkt('usa', 'vw')
    months = sorted(set().union(*[set(v) for v in R.values()]))
    out = {}
    for key, tg in repl_targets(R, mk).items():
        if key in ('def', 'siegel'):
            continue
        r, _, _ = run(tg, R, months)
        ks = sorted(k for k in r if k in mk)
        if len(ks) < 60:
            continue
        rr = {k: r[k] for k in ks}
        out[key] = {p: (lambda st: None if st is None else {x: st[x] for x in ('from', 'to', 'ex_ann', 't', 'cagr_diff', 'te')})(M.excess_stats(rr, mk, a=a, z=z))
                    for p, a, z in (('full', None, None), ('train', None, M.TRAIN_END), ('hold', M.HOLD_START, None))}
    return out


# ───────────────────────── prereg4: まだ見ていない国の再現パネル ─────────────────────────
def unseen_panel():
    pre = json.load(open(os.path.join(BASE, 'out', PREREG4)))
    series = {}
    for ctry in pre['countries']:
        R = jkp_industry(ctry)
        mk = M.jkp_mkt(ctry, 'vw')
        months = sorted(set().union(*[set(v) for v in R.values()]))
        tg = repl_targets(R, mk)
        rs = {}
        rs['mom12'], _, _ = run(tg['mom12'], R, months)
        rs['mom6'], _, _ = run(tg['mom6'], R, months)
        st = {}
        for m, v in rs['mom12'].items():
            ks36 = [madd(m, -k) for k in range(1, 37)]
            if m in mk and all(k in mk for k in ks36):
                st[m] = mk[m] if math.fsum(math.log1p(mk[k]) for k in ks36) < 0 else v
        rs['mom12_state'] = st
        rs['ew_sectors'], _, _ = run(lambda m: {c: 1.0 for c in R if m in R[c]} or None, R, months)
        for key, r in rs.items():
            series.setdefault(key, {})[ctry] = {m: r[m] - mk[m] for m in r if m in mk}
    for key in ('mom12', 'mom6', 'mom12_state'):
        series[key + '_minus_ew'] = {c: {m: series[key][c][m] - series['ew_sectors'][c][m] for m in series[key][c] if m in series['ew_sectors'][c]}
                                     for c in series[key]}
    out = {'prereg': PREREG4, 'prereg_commit': git_sha(f'out/{PREREG4}'), 'results': {}}

    def pooled(per):
        ms = sorted(set().union(*[set(v) for v in per.values()]))
        avg = {m: S.mean([v[m] for v in per.values() if m in v]) for m in ms if any(m in v for v in per.values())}
        x = [avg[m] for m in sorted(avg)]
        t = M.nw_t(x)
        return {'from': min(avg), 'to': max(avg), 'ex_ann': round(S.mean(x) * 1200, 2), 't': None if t is None else round(t, 2),
                'hold_2007_ex_ann': round(S.mean([avg[m] for m in avg if m >= M.HOLD_START]) * 1200, 2),
                'hold_2007_t': (lambda t: None if t is None else round(t, 2))(M.nw_t([avg[m] for m in sorted(avg) if m >= M.HOLD_START]))}
    for key, per in series.items():
        pc = {}
        for c, d in per.items():
            ks = sorted(d)
            if len(ks) < 60:
                pc[c] = {'months': len(ks), 'counted': False}
                continue
            x = [d[k] for k in ks]
            t = M.nw_t(x)
            pc[c] = {'from': ks[0], 'to': ks[-1], 'months': len(ks), 'counted': True, 'ex_ann': round(S.mean(x) * 1200, 2), 't': None if t is None else round(t, 2)}
        cnt = {c: v for c, v in pc.items() if v.get('counted')}
        res = {'per_country': pc, 'counted': len(cnt), 'positive': sum(v['ex_ann'] > 0 for v in cnt.values()),
               'pooled_all': pooled({c: per[c] for c in cnt})}
        for g, cs in pre['groups'].items():
            sub = {c: per[c] for c in cs if c in cnt}
            if sub:
                res['pooled_' + g] = pooled(sub)
                res['positive_' + g] = f"{sum(cnt[c]['ex_ann'] > 0 for c in sub)}/{len(sub)}"
        if not key.startswith('ew'):
            pa = res['pooled_all']
            res['pass_line'] = bool(res['counted'] and res['positive'] / res['counted'] >= 2 / 3 and pa['ex_ann'] > 0 and (pa['t'] or 0) >= 2.0)
        out['results'][key] = res
    return out


def main():
    D = Data()
    sig = Sig(D)
    if '--panel' in sys.argv:
        print(json.dumps(unseen_panel(), ensure_ascii=False, indent=1)[:20000])
        return
    if '--sanity' in sys.argv:
        print(json.dumps(sanity(D, sig), ensure_ascii=False, indent=1))
        return
    pre = json.load(open(os.path.join(BASE, 'out', PREREG)))
    specs = {s['id']: s for s in pre['strategies']}
    T = make_targets(D, sig)
    assert set(T) == set(specs), set(T) ^ set(specs)
    rep = replication()
    rows, holds = [], {}
    for sid, spec in specs.items():
        r, turn, hold = run(T[sid], D.R, D.months)
        ev = evaluate(sid, r, turn, D.mkt, spec.get('pub_year'))
        ev.update({'primary': spec['primary'], 'family': spec['family'], 'rule': spec['rule']})
        key = REPL_MAP.get(sid)
        ev['repl_key'] = key
        ev['repl'] = repl_summary(rep, key) if key else None
        ev['repl_detail'] = rep.get(key) if key else None
        # 最近の持ち物（参考）
        last = max(hold)
        ev['holding_last'] = {'month': last, 'industries': hold[last] if len(hold[last]) <= 12 else f'{len(hold[last])}業種'}
        rows.append(ev)
    for e in rows:
        e['prereg'] = PREREG
    prim = {e['id']: e['hold']['p'] for e in rows if e['primary'] and e['hold']}
    allp = {e['id']: e['hold']['p'] for e in rows if e['hold']}
    hp, ha = M.holm(prim), M.holm(allp)
    for e in rows:
        e['holm_p_hold'] = hp.get(e['id']) if e['primary'] else ha.get(e['id'])
        e['holm_family'] = 'primary(27)' if e['primary'] else 'primary+exploratory(36)'
    rows2 = part2(D, sig, rep) if os.path.exists(os.path.join(BASE, 'out', PREREG2)) else []
    rows3 = part3(D, sig, rep) if os.path.exists(os.path.join(BASE, 'out', PREREG3)) else []
    for fam, rr in ((PREREG2, rows2), (PREREG3, rows3)):
        pf = M.holm({e['id']: e['hold']['p'] for e in rr if e['hold']})
        for e in rr:
            e['holm_p_hold'] = pf.get(e['id'])
            e['holm_family'] = f'{fam}({len(rr)})'
    pall = M.holm({e['id']: e['hold']['p'] for e in rows + rows2 + rows3 if e['hold']})
    for e in rows + rows2 + rows3:
        e['holm_p_hold_all'] = pall.get(e['id'])
    rows = rows + rows2 + rows3
    for e in rows:
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=e['repl'],
                       family_holm_p=e['holm_p_hold'])
        e['grade'], e['criteria'] = g, c
    rows.sort(key=lambda e: -(e['hold']['ex_ann'] if e['hold'] else -99))
    out = {'angle': 'industry', 'prereg': PREREG, 'prereg_commit': git_sha(f'out/{PREREG}'),
           'prereg_files': {p: git_sha(f'out/{p}') for p in PREREG_FILES},
           'benchmark': 'French Mkt（Mkt−RF+RF・総リターン）', 'cost_per_100pct_twoway': COST,
           'sanity': sanity(D, sig), 'n_tested': len(rows),
           'grades': {g: [e['id'] for e in rows if e['grade'] == g] for g in 'SABC'},
           'tested': rows, 'replication_raw': rep,
           'diagnostics_post_hoc_not_graded': dict(diagnostics(D) if '--nodiag' not in sys.argv else {},
                                                   pooled_international=pooled_repl(RAW), us_gics_jkp=us_gics_check()),
           'unseen_panel_prereg4': unseen_panel() if os.path.exists(os.path.join(BASE, 'out', PREREG4)) else None}
    p = M.save(OUT, out)
    print('→', p)
    for e in rows:
        h, f, t = e['hold'], e['full'], e['train']
        print(f"{e['id']:<20} {'主' if e['primary'] else {PREREG: '探', PREREG2: '探2', PREREG3: '探3'}[e['prereg']]} 全{f['ex_ann']:+6.2f}(t{f['t']:+.2f}) 訓{t['ex_ann']:+6.2f}(t{t['t']:+.2f}) "
              f"保{h['ex_ann']:+6.2f}(t{h['t']:+.2f} g{h['cagr_diff']:+.2f}) 費後{e['cost_hold']['ex_ann']:+6.2f} "
              f"roll{e['roll20']['win_rate'] if e['roll20'] else None} repl{e['repl']} holm{e['holm_p_hold']} → {e['grade']}")


if __name__ == '__main__':
    main()
