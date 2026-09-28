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
PREREG_FILES = ['mw_industry_prereg.json']
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


def repl_targets(R):
    """GICS 11セクター版の規則（11のうち3）。R: {sector: {m: 超過}}"""
    secs = sorted(R)
    has = lambda c, m: m in R[c]

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

    return {
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
        for key, tg in repl_targets(R).items():
            r, turn, _ = run(tg, R, months)
            ks = sorted(k for k in r if k in mk)
            if len(ks) < 60:
                res.setdefault(key, {})[ctry] = {'months': len(ks), 'counted': False}
                continue
            ex = [r[k] - mk[k] for k in ks]
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


def evaluate(sid, r, turn, D, pub_year=None):
    b = D.mkt
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


def main():
    D = Data()
    sig = Sig(D)
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
        ev = evaluate(sid, r, turn, D, spec.get('pub_year'))
        ev.update({'primary': spec['primary'], 'family': spec['family'], 'rule': spec['rule']})
        key = REPL_MAP.get(sid)
        ev['repl_key'] = key
        ev['repl'] = repl_summary(rep, key) if key else None
        ev['repl_detail'] = rep.get(key) if key else None
        # 最近の持ち物（参考）
        last = max(hold)
        ev['holding_last'] = {'month': last, 'industries': hold[last] if len(hold[last]) <= 12 else f'{len(hold[last])}業種'}
        rows.append(ev)
    prim = {e['id']: e['hold']['p'] for e in rows if e['primary'] and e['hold']}
    allp = {e['id']: e['hold']['p'] for e in rows if e['hold']}
    hp, ha = M.holm(prim), M.holm(allp)
    for e in rows:
        e['holm_p_hold'] = hp.get(e['id']) if e['primary'] else ha.get(e['id'])
        e['holm_family'] = 'primary(27)' if e['primary'] else 'primary+exploratory(36)'
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=e['repl'],
                       family_holm_p=e['holm_p_hold'])
        e['grade'], e['criteria'] = g, c
    rows.sort(key=lambda e: -(e['hold']['ex_ann'] if e['hold'] else -99))
    out = {'angle': 'industry', 'prereg': PREREG, 'prereg_commit': git_sha(f'out/{PREREG}'),
           'prereg_files': {p: git_sha(f'out/{p}') for p in PREREG_FILES},
           'benchmark': 'French Mkt（Mkt−RF+RF・総リターン）', 'cost_per_100pct_twoway': COST,
           'sanity': sanity(D, sig), 'n_tested': len(rows),
           'grades': {g: [e['id'] for e in rows if e['grade'] == g] for g in 'SABC'},
           'tested': rows, 'replication_raw': rep}
    p = M.save(OUT, out)
    print('→', p)
    for e in rows:
        h, f, t = e['hold'], e['full'], e['train']
        print(f"{e['id']:<20} {'主' if e['primary'] else '探'} 全{f['ex_ann']:+6.2f}(t{f['t']:+.2f}) 訓{t['ex_ann']:+6.2f}(t{t['t']:+.2f}) "
              f"保{h['ex_ann']:+6.2f}(t{h['t']:+.2f} g{h['cagr_diff']:+.2f}) 費後{e['cost_hold']['ex_ann']:+6.2f} "
              f"roll{e['roll20']['win_rate'] if e['roll20'] else None} repl{e['repl']} holm{e['holm_p_hold']} → {e['grade']}")


if __name__ == '__main__':
    main()
