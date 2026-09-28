#!/usr/bin/env python3
"""night/nx_jst.py — 角度 nx_jst（1870年からの百五十年で国・資産の選び方）の測定（読むだけ・門の判定には不使用）

事前登録: out/nx_jst_prereg.json（測る前に commit 済み・書き換えない）。線: out/nx_prereg.json の C1〜C8（nx_common.grade）。
データ: night/nx_jst_data.py が作る out/_nx_cache/nx_jst_series.json（JST Macrohistory R6・年次・1870〜2020）。
出力: out/nx_jst.json（tested に事前登録の全規則を1本残らず・負けも）。

年次なので excess_stats(per_year=1, lag=2) を使い、転がる20年窓・積立20年・短い期間の参考 t は
この道具の中に書く（nx_common.rolling / dca は月次キー前提）。
事前登録どおりにできなかった所・解釈を要した所は deviations_from_prereg に理由つきで書く。
結果を見た後にした分析は post_hoc（『事後』・格付けに使わない）に分けて書く。
"""
import sys, os, json, math, copy, random, bisect, hashlib, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

SER = os.path.join(N.CACHE, 'nx_jst_series.json')
PRE = os.path.join(N.BASE, 'out', 'nx_jst_prereg.json')
SHA_EXPECTED = '28618a69337a347a1f2ae7b62d49d2fb80bb3fc1'
UNIVERSE = ['AUS', 'BEL', 'CHE', 'DEU', 'DNK', 'ESP', 'FIN', 'FRA', 'GBR', 'ITA', 'JPN', 'NLD', 'NOR', 'PRT', 'SWE', 'USA']
REGIONS = {'R1_core_europe': ['BEL', 'CHE', 'DEU', 'ESP', 'FRA', 'ITA', 'NLD', 'PRT'],
           'R2_nordic': ['DNK', 'FIN', 'NOR', 'SWE'],
           'R3_anglo_japan': ['AUS', 'GBR', 'JPN', 'USA']}
Y_FIRST, Y_LAST = 1870, 2020
TRAIN_Z, HOLD_A, HOLD_Z = 1949, 1950, 2020
LAG = 2
MIN_SEL, MIN_SEL_REGION = 6, 3

# 2026-09-28 検査役の指摘で直した3点（fixes 欄）。既定はすべて是正後。環境変数 NXJST_FIXES で外せる
# （例 NXJST_FIXES=none → 初版の出力をそのまま再現する。是正の前後を数えるためだけに残す）
#   tie_int : 複数の信号の順位の和を整数の位置の和で比べ、同点は ISO 順（事前登録 signals.ties。初版は浮動小数点の端数で割れていた）
#   gdp_lag : GDP 加重の重みを gdp_{t−1}/xrusd_{t−1}（t＝組み替えの年）にする（事前登録 gdp_weights・credit_lag。初版は年 t の値）
#   prt_mask: PRT 2016〜2020 の株の4列（eq_tr・eq_dp・eq_capgain・eq_div_rtn）は約1/100 の単位の誤り → 欠測（絶対のルール7）
_fx = os.environ.get('NXJST_FIXES', 'all').strip()
FIX = {k: (_fx == 'all' or k in _fx.split(',')) for k in ('tie_int', 'gdp_lag', 'prt_mask')}
PRT_FLAW_YEARS = range(2016, 2021)
PRT_FLAW_COLS = ('eq_tr', 'eq_dp', 'eq_capgain', 'eq_div_rtn')


def mask_prt(data, mode='missing'):
    """PRT 2016〜2020 の株の4列を 'missing'（None）か 'x100'（100倍＝単位の誤りを直した仮の値・感度だけ）にした写し"""
    d2 = copy.deepcopy(data)
    for y in PRT_FLAW_YEARS:
        for col in PRT_FLAW_COLS:
            v = fnum(d2['PRT'][y].get(col))
            d2['PRT'][y][col] = None if mode == 'missing' else (v * 100 if v is not None else None)
    return d2


# ───────────────────────── データ ─────────────────────────
def load_raw():
    j = json.load(open(SER))
    data = {iso: {int(y): r for y, r in d.items()} for iso, d in j['data'].items()}
    return j, data


def fnum(v):
    return v if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)) else None


class World:
    """国×年のデータと、欠測扱い（超インフレ・取引所の閉鎖）の閾値を持つ。欠測は None のまま（0 で埋めない）"""

    def __init__(self, data, hyper_thr=1.0):
        self.d = data
        self.thr = hyper_thr
        self._cache = {}

    def v(self, c, y, col):
        r = self.d.get(c, {}).get(y)
        return fnum(r.get(col)) if r else None

    def infl(self, c, y):
        a, b = self.v(c, y - 1, 'cpi'), self.v(c, y, 'cpi')
        return b / a - 1 if a and b else None

    def hyper(self, c, y):
        if self.thr is None:
            return False
        i = self.infl(c, y)
        return i is not None and i > self.thr

    def closed(self, c, y):
        return self.v(c, y, 'eq_tr_interp') == 1.0

    def missing(self, c, y):
        return self.hyper(c, y) or self.closed(c, y)

    # 年 y のリターン（基準別）。欠測扱いの国・年は None
    def ret(self, asset, basis, c, y):
        if self.missing(c, y):
            return None
        nom = {'eq': self.v(c, y, 'eq_tr'), 'bill': self.v(c, y, 'bill_rate'), 'bond': self.v(c, y, 'bond_tr')}[asset]
        if nom is None:
            return None
        if basis == 'real':
            a, b = self.v(c, y - 1, 'cpi'), self.v(c, y, 'cpi')
            return (1 + nom) / (b / a) - 1 if a and b else None
        if basis == 'usd':
            a, b = self.v(c, y - 1, 'xrusd'), self.v(c, y, 'xrusd')
            return (1 + nom) * a / b - 1 if a and b else None
        if basis == 'hedged':  # X3: 先物と同じ基準（現地の短期金利を引いた超過）。株だけ
            bill = self.v(c, y, 'bill_rate')
            return (1 + nom) / (1 + bill) - 1 if asset == 'eq' and bill is not None else None
        raise ValueError(basis)

    # ── 信号（年 t の末に分かる値だけ）──
    def cum(self, c, years, basis='real'):
        g = 1.0
        for y in years:
            r = self.ret('eq', basis, c, y)
            if r is None:
                return None
            g *= 1 + r
        return g - 1

    def credit_ratio(self, c, y, col='tloans'):
        if self.hyper(c, y):
            return None
        a, g = self.v(c, y, col), self.v(c, y, 'gdp')
        return a / g if a is not None and g else None

    def sig(self, name, c, t):
        k = (name, c, t)
        if k in self._cache:
            return self._cache[k]
        x = self._sig(name, c, t)
        self._cache[k] = x
        return x

    def _sig(self, name, c, t):
        if name == 'dy':  # 配当利回り（超インフレの年でも使える・補間の印の年は使わない）
            if self.v(c, t, 'eq_dp_interp') == 1.0 or self.v(c, t, 'eq_tr_interp') == 1.0:
                return None
            return self.v(c, t, 'eq_dp')
        if name == 'mom':
            return self.ret('eq', 'real', c, t)
        if name == 'rev':
            return self.cum(c, range(t - 4, t))
        if name == 'credit':
            a, b = self.credit_ratio(c, t - 1), self.credit_ratio(c, t - 4)
            return a - b if a is not None and b is not None else None
        if name == 'hh':
            a, b = self.credit_ratio(c, t - 1, 'thh'), self.credit_ratio(c, t - 4, 'thh')
            return a - b if a is not None and b is not None else None
        if name == 'boom':
            return self.cum(c, range(t - 2, t + 1))
        if name == 'mom2':
            return self.cum(c, range(t - 1, t + 1))
        if name == 'rev3':
            return self.cum(c, range(t - 2, t + 1))
        if name == 'rev5i':
            return self.cum(c, range(t - 4, t + 1))
        if name == 'growth':
            a, b = self.v(c, t - 1, 'rgdpmad'), self.v(c, t - 5, 'rgdpmad')
            return a / b - 1 if a and b else None
        if name == 'hmom':
            return self.ret('eq', 'hedged', c, t)
        if name == 'hrev':
            return self.cum(c, range(t - 4, t), 'hedged')
        if name == 'dy10':  # 平滑した配当利回り: t−9〜t の実質の配当の平均 ÷ t の実質の株価
            ys = list(range(t - 9, t + 1))
            if any(self.missing(c, y) for y in ys):
                return None
            p = 1.0
            px = {}
            for i, y in enumerate(ys):
                if i > 0:
                    cg = self.v(c, y, 'eq_capgain')
                    if cg is None:
                        return None
                    p *= 1 + cg
                px[y] = p
            divs = []
            for y in ys:
                dp, cpi = self.v(c, y, 'eq_dp'), self.v(c, y, 'cpi')
                if dp is None or not cpi:
                    return None
                divs.append(dp * px[y] / cpi)
            cpit = self.v(c, t, 'cpi')
            return S.mean(divs) / (px[t] / cpit)
        if name == 'yieldgap':
            dp, lt = self.v(c, t, 'eq_dp'), self.v(c, t, 'ltrate')
            if dp is None or lt is None or self.v(c, t, 'eq_dp_interp') == 1.0 or self.v(c, t, 'eq_tr_interp') == 1.0:
                return None
            return dp - lt / 100
        raise ValueError(name)

    # ── 閾値（パネル・自国の拡大窓）──
    def panel_q(self, name, q, t, min_n=50):
        """全16か国の信号 sig(name, c, s)（s ≤ t＝信用は t−1 までのデータ）の拡大窓の q 分位（線形補間）。min_n 未満は None"""
        key = ('panel', name, q, min_n)
        if key not in self._cache:
            pool, out = [], {}
            for s in range(Y_FIRST, Y_LAST + 1):
                for c in UNIVERSE:
                    x = self.sig(name, c, s)
                    if x is not None:
                        bisect.insort(pool, x)
                out[s] = (quantile(pool, q), len(pool)) if len(pool) >= min_n else (None, len(pool))
            self._cache[key] = out
        return self._cache[key].get(t, (None, 0))[0]

    def own_q(self, name, q, c, t, min_n):
        key = ('own', name, q, c, min_n)
        if key not in self._cache:
            pool, out = [], {}
            for s in range(Y_FIRST, Y_LAST + 1):
                x = self.sig(name, c, s)
                if x is not None:
                    bisect.insort(pool, x)
                out[s] = quantile(pool, q) if len(pool) >= min_n else None
            self._cache[key] = out
        return self._cache[key].get(t)

    def gdp_w(self, c, t):
        """GDP 加重の重み（ドル建て・年 t の値。欠けは5年以内の過去の値）。
        呼ぶ側が t に『組み替えの年 − 1』を渡す（事前登録 gdp_{t−1}/xrusd_{t−1}。FIX['gdp_lag'] が偽のときだけ初版の組み替えの年）"""
        for lag in range(0, 6):
            g, x = self.v(c, t - lag, 'gdp'), self.v(c, t - lag, 'xrusd')
            if g and x:
                return g / x
        return None


def quantile(sv, q):
    n = len(sv)
    if n == 0:
        return None
    pos = q * (n - 1)
    lo = int(math.floor(pos)); hi = min(lo + 1, n - 1)
    return sv[lo] * (1 - (pos - lo)) + sv[hi] * (pos - lo)


def rate(y):
    return 0.01 if y <= 1949 else (0.005 if y <= 1989 else 0.002)


# ───────────────────────── 規則の定義（事前登録の文言どおり） ─────────────────────────
SEL = {  # kind='sel'：国の選択
    'P1_dy_top3rd': dict(fam='P', sig=[('dy', 1)], k='third', basis='real', pub=2014),
    'P2_mom_top3rd': dict(fam='P', sig=[('mom', 1)], k='third', basis='real', pub=2001),
    'P3_rev_bottom3rd': dict(fam='P', sig=[('rev', -1)], k='third', basis='real', pub=2001),
    'P4_vm_top3rd': dict(fam='P', sig=[('dy', 1), ('mom', 1)], k='third', basis='real', pub=2014),
    'P5_credit_bottom3rd': dict(fam='P', sig=[('credit', -1)], k='third', basis='real', pub=2018),
    'X1a_dy_K3': dict(fam='X1', sig=[('dy', 1)], k=3, basis='real'),
    'X1b_dy_top4th': dict(fam='X1', sig=[('dy', 1)], k='quarter', basis='real'),
    'X1c_dy_top_half': dict(fam='X1', sig=[('dy', 1)], k='half', basis='real'),
    'X1d_dy10_top3rd': dict(fam='X1', sig=[('dy10', 1)], k='third', basis='real'),
    'X1e_mom2y_top3rd': dict(fam='X1', sig=[('mom2', 1)], k='third', basis='real'),
    'X1f_rev3_bottom3rd': dict(fam='X1', sig=[('rev3', -1)], k='third', basis='real'),
    'X1g_rev5incl_bottom3rd': dict(fam='X1', sig=[('rev5i', -1)], k='third', basis='real'),
    'X1h_credit_excl_top3rd': dict(fam='X1', sig=[('credit', 1)], k='third', mode='exclude', basis='real'),
    'X1i_vmc_top3rd': dict(fam='X1', sig=[('dy', 1), ('mom', 1), ('credit', -1)], k='third', basis='real'),
    'X1j_growth_top3rd': dict(fam='X1', sig=[('growth', 1)], k='third', basis='real'),
    'X3a_dy': dict(fam='X3', sig=[('dy', 1)], k='third', basis='hedged'),
    'X3b_mom': dict(fam='X3', sig=[('hmom', 1)], k='third', basis='hedged'),
    'X3c_rev': dict(fam='X3', sig=[('hrev', -1)], k='third', basis='hedged'),
    'X3d_vm': dict(fam='X3', sig=[('dy', 1), ('hmom', 1)], k='third', basis='hedged'),
    'X3e_credit': dict(fam='X3', sig=[('credit', -1)], k='third', basis='hedged'),
}
TIM = {  # kind='tim'：国ごとの切替（その国の株の買い持ちが相手）
    'P6_credit_timing': dict(fam='P', trig=('panel', 'credit', 0.8, 50), exit='bill', pub=2018),
    'P7_rzone_timing': dict(fam='P', trig=('rzone',), exit='bill', pub=2021),
    'X2a_credit80_bonds': dict(fam='X2', trig=('panel', 'credit', 0.8, 50), exit='bond'),
    'X2b_credit67_bills': dict(fam='X2', trig=('panel', 'credit', 2 / 3, 50), exit='bill'),
    'X2c_credit80_own': dict(fam='X2', trig=('own', 'credit', 0.8, 15), exit='bill'),
    'X2d_rzone_bonds': dict(fam='X2', trig=('rzone',), exit='bond'),
    'X2e_hhcredit80_bills': dict(fam='X2', trig=('panel', 'hh', 0.8, 50), exit='bill'),
    'X2f_yieldgap_bonds': dict(fam='X2', trig=('yieldgap',), exit='bond'),
    'X2g_trend_bills': dict(fam='X2', trig=('trend',), exit='bill'),
    'X2h_relmom3': dict(fam='X2', trig=('relmom3',), exit='relmom'),
    'X2i_credit80_half': dict(fam='X2', trig=('panel', 'credit', 0.8, 50), exit='bill', out_eq=0.5),
}
ORDER = ['P1_dy_top3rd', 'P2_mom_top3rd', 'P3_rev_bottom3rd', 'P4_vm_top3rd', 'P5_credit_bottom3rd', 'P6_credit_timing', 'P7_rzone_timing',
         'X1a_dy_K3', 'X1b_dy_top4th', 'X1c_dy_top_half', 'X1d_dy10_top3rd', 'X1e_mom2y_top3rd', 'X1f_rev3_bottom3rd', 'X1g_rev5incl_bottom3rd',
         'X1h_credit_excl_top3rd', 'X1i_vmc_top3rd', 'X1j_growth_top3rd',
         'X2a_credit80_bonds', 'X2b_credit67_bills', 'X2c_credit80_own', 'X2d_rzone_bonds', 'X2e_hhcredit80_bills', 'X2f_yieldgap_bonds',
         'X2g_trend_bills', 'X2h_relmom3', 'X2i_credit80_half',
         'X3a_dy', 'X3b_mom', 'X3c_rev', 'X3d_vm', 'X3e_credit', 'X4a_ew_vs_gdp']


def kcount(k, n):
    if k == 'third':
        return math.ceil(n / 3)
    if k == 'quarter':
        return math.ceil(n / 4)
    if k == 'half':
        return math.ceil(n / 2)
    return min(int(k), n)


def choose(W, spec, universe, t, min_n):
    """年 t の末の選択（年 t+1 に持つ国）。選べる国が min_n 未満なら None"""
    sigs = spec['sig']
    t = t - spec.get('skip', 0)  # 事後の診断（skip=1: 1年前の信号で選ぶ）だけが使う。事前登録の規則は skip=0
    elig = [c for c in universe if all(W.sig(nm, c, t) is not None for nm, _ in sigs) and not (spec.get('strict_elig') and W.missing(c, t))]
    n = len(elig)
    if n < min_n:
        return None, n
    if FIX['tie_int']:
        # 百分位の順位の平均 Σ(1 − p/(n−1))/m は整数の位置の和 Σp の単調減少なので、Σp で比べれば同じ順位になる。
        # 和が同じ国は事前登録どおり ISO 順（浮動小数点の端数で割らない）
        psum = {c: 0 for c in elig}
        for nm, d in sigs:
            order = sorted(elig, key=lambda c: (-d * W.sig(nm, c, t), c))
            for p, c in enumerate(order):
                psum[c] += p
        ranked = sorted(elig, key=lambda c: (psum[c], c))
    else:  # 初版（是正の前後を数えるためだけ）
        score = {c: 0.0 for c in elig}
        for nm, d in sigs:
            order = sorted(elig, key=lambda c: (-d * W.sig(nm, c, t), c))
            for p, c in enumerate(order):
                score[c] += (1 - p / (n - 1)) if n > 1 else 1.0
        ranked = sorted(elig, key=lambda c: (-score[c], c))
    k = kcount(spec['k'], n)
    if spec.get('mode') == 'exclude':
        return ranked[k:], n
    if spec.get('mode') == 'last':  # 事後の診断（三分位の反対側）
        return ranked[-k:], n
    if spec.get('mode') == 'middle':
        return ranked[k:n - k], n
    return ranked[:k], n


# ───────────────────────── 模擬 ─────────────────────────
def bench(W, universe, basis, weight='ew'):
    out = {}
    for y in range(Y_FIRST + 1, Y_LAST + 1):
        xs = []
        for c in universe:
            r = W.ret('eq', basis, c, y)
            if r is None:
                continue
            w = 1.0 if weight == 'ew' else W.gdp_w(c, y - 2 if FIX['gdp_lag'] else y - 1)  # 年 y=t+1 のリターンに gdp_{t−1}
            if w is None:
                continue
            xs.append((w, r))
        if xs:
            out[y] = sum(w * r for w, r in xs) / sum(w for w, _ in xs)
    return out


def sim_sel(W, spec, universe, basis, min_n, veh=0.003, extra=0.0):
    """国の選択を年ごとに回す → s（費用前）・cost（その年の費用）・s_lb（下限版）・保有の記録"""
    s, cost, s_lb, hold, nelig, turn = {}, {}, {}, {}, {}, {}
    prev_w, prev_y = {}, None
    for t in range(Y_FIRST, Y_LAST):
        y = t + 1
        if spec.get('all'):  # X4a: 年 y にリターンのある国すべて（主の相手そのもの）
            cand = [c for c in universe if W.ret('eq', basis, c, t) is not None]
            if len(cand) < min_n:
                prev_w, prev_y = {}, None
                continue
            sel, n = [c for c in universe], len(cand)
        else:
            sel, n = choose(W, spec, universe, t, min_n)
            if sel is None:
                prev_w, prev_y = {}, None
                continue
        rs = {c: W.ret('eq', basis, c, y) for c in sel}
        real = [c for c in sel if rs[c] is not None]
        miss = [c for c in sel if rs[c] is None]
        if not spec.get('all'):
            hold[y] = {'sel': sel, 'held': real, 'missing': miss, 'n_elig': n}
        nelig[y] = n
        if not real:
            prev_w, prev_y = {}, None
            continue
        s[y] = S.mean(rs[c] for c in real)
        s_lb[y] = s[y] if spec.get('all') else S.mean([rs[c] for c in real] + [-0.5] * len(miss))
        # 片道の売買 = ½Σ|w_new − w_drift|
        if prev_y == t and prev_w:
            g = {c: prev_w[c] * (1 + W.ret('eq', basis, c, t)) for c in prev_w}
            tot = sum(g.values())
            drift = {c: g[c] / tot for c in g}
        else:
            drift = {}
        new = {c: 1 / len(real) for c in real}
        to = 0.5 * sum(abs(new.get(c, 0) - drift.get(c, 0)) for c in set(new) | set(drift))
        turn[y] = to
        cost[y] = to * rate(y) + veh + extra
        prev_w, prev_y = new, y
    return {'s': s, 'cost': cost, 's_lb': s_lb, 'hold': hold, 'nelig': nelig, 'turn': turn}


def position(W, spec, c, t):
    """切替の規則の年 t+1 の持ち高 {'eq','bond','bill'}。信号がそろわなければ None"""
    trig = spec['trig']
    out_eq = spec.get('out_eq', 0.0)
    ex = 'bond' if spec['exit'] == 'bond' else 'bill'

    def outpos():
        p = {'eq': out_eq, 'bond': 0.0, 'bill': 0.0}
        p[ex] += 1 - out_eq
        return p
    inpos = {'eq': 1.0, 'bond': 0.0, 'bill': 0.0}
    kind = trig[0]
    if kind == 'panel':
        _, nm, q, mn = trig
        x, th = W.sig(nm, c, t), W.panel_q(nm, q, t, mn)
        if x is None or th is None:
            return None
        return outpos() if x > th else inpos
    if kind == 'own':
        _, nm, q, mn = trig
        x, th = W.sig(nm, c, t), W.own_q(nm, q, c, t, mn)
        if x is None or th is None:
            return None
        return outpos() if x > th else inpos
    if kind == 'rzone':
        x, th = W.sig('credit', c, t), W.panel_q('credit', 0.8, t, 50)
        b, tb = W.sig('boom', c, t), W.panel_q('boom', 2 / 3, t, 50)
        if None in (x, th, b, tb):
            return None
        return outpos() if (x > th and b > tb) else inpos
    if kind == 'yieldgap':
        x, med = W.sig('yieldgap', c, t), W.own_q('yieldgap', 0.5, c, t, 10)
        if x is None or med is None:
            return None
        return inpos if x > med else outpos()
    if kind == 'trend':
        if W.missing(c, t):
            return None
        e, b = W.v(c, t, 'eq_tr'), W.v(c, t, 'bill_rate')
        if e is None or b is None:
            return None
        return inpos if e > b else outpos()
    if kind == 'relmom3':
        if W.missing(c, t):
            return None
        vals = {'eq': W.v(c, t, 'eq_tr'), 'bond': W.v(c, t, 'bond_tr'), 'bill': W.v(c, t, 'bill_rate')}
        if any(v is None for v in vals.values()):
            return None
        best = max(['eq', 'bond', 'bill'], key=lambda a: (vals[a], -['eq', 'bond', 'bill'].index(a)))
        p = {'eq': 0.0, 'bond': 0.0, 'bill': 0.0}
        p[best] = 1.0
        return p
    raise ValueError(kind)


def sim_tim(W, spec, universe, basis, weight='ew', exclude=()):
    """国ごとの切替。s（規則・費用前）・b（同じ国の株の買い持ち）・cost・rf（同じ国の短期金利）・s_lb・国ごとの寄与"""
    s, b, cost, rf, s_lb, nset, frac_out, contrib = {}, {}, {}, {}, {}, {}, {}, {}
    prevpos = {}  # c -> (year, weights after drift at end of year)
    need_bond = spec['exit'] in ('bond', 'relmom')
    for t in range(Y_FIRST, Y_LAST):
        y = t + 1
        rows, rows_lb = [], []
        for c in universe:
            if c in exclude:
                continue
            p = position(W, spec, c, t)
            if p is None:
                continue
            req = W.ret('eq', basis, c, y)
            rbill = W.ret('bill', basis, c, y)
            rbond = W.ret('bond', basis, c, y) if need_bond else 0.0
            w = 1.0 if weight == 'ew' else W.gdp_w(c, t - 1 if FIX['gdp_lag'] else t)  # 年 t+1 の持ち高に gdp_{t−1}
            if w is None:
                continue
            if req is None:  # 株のリターンが欠けた年: 相手からも規則からも落とす。下限版（費用前）だけ、持っていた資産の欠けを −50% として規則に入れる
                lbv = p['eq'] * -0.5 + p['bond'] * (rbond if rbond is not None else -0.5) + p['bill'] * (rbill if rbill is not None else -0.5)
                rows_lb.append((w, lbv))
                continue
            if rbill is None or rbond is None:
                continue  # 降りる先が無い（短期金利の欠け）→ その国のその年を組から落とす（相手も）
            # 費用: 前年末の持ち高（前年に組に居なければ株100%とみなす）からの変化
            pp = prevpos.get(c)
            prev = pp[1] if pp and pp[0] == t else {'eq': 1.0, 'bond': 0.0, 'bill': 0.0}
            cst = abs(p['eq'] - prev['eq']) * rate(y) + (abs(p['bond'] - prev['bond']) + abs(p['bill'] - prev['bill'])) * 0.001
            rr = p['eq'] * req + p['bond'] * rbond + p['bill'] * rbill
            rows.append((c, w, rr, req, cst, rbill, p))
            g = {'eq': p['eq'] * (1 + req), 'bond': p['bond'] * (1 + rbond), 'bill': p['bill'] * (1 + rbill)}
            tot = sum(g.values())
            prevpos[c] = (y, {a: g[a] / tot for a in g})
        if not rows:
            continue
        tw = sum(r[1] for r in rows)
        s[y] = sum(r[1] * r[2] for r in rows) / tw
        b[y] = sum(r[1] * r[3] for r in rows) / tw
        cost[y] = sum(r[1] * r[4] for r in rows) / tw
        rf[y] = sum(r[1] * r[5] for r in rows) / tw
        nset[y] = len(rows)
        frac_out[y] = sum(r[1] * (1 - r[6]['eq']) for r in rows) / tw
        for r in rows:
            contrib[r[0]] = contrib.get(r[0], 0.0) + r[1] / tw * (r[2] - r[3])
        tw2 = tw + sum(w for w, _ in rows_lb)
        s_lb[y] = (sum(r[1] * r[2] for r in rows) + sum(w * x for w, x in rows_lb)) / tw2
    return {'s': s, 'b': b, 'cost': cost, 'rf': rf, 's_lb': s_lb, 'nset': nset, 'frac_out': frac_out, 'contrib': contrib}


# ───────────────────────── 統計（年次） ─────────────────────────
def nw_t_any(x, lag=LAG):
    n = len(x)
    if n < 3:
        return None
    m = S.mean(x); e = [v - m for v in x]
    s = sum(v * v for v in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * sum(e[i] * e[i - L] for i in range(L, n)) / n
    return m / math.sqrt(s / n) if s > 0 else None


def short(s, b, a=None, z=None, raw=False):
    """短い期間の参考（24年未満でも計算・格付けに使わない）: 算術の超過・幾何の年率差・参考 t（NW ラグ2）。raw=True は丸めない（厳密な格付けの C5 用）"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 3:
        return {'n': len(ks)} if ks else None
    ex = [s[k] - b[k] for k in ks]
    gs = math.exp(math.fsum(math.log1p(s[k]) for k in ks) / len(ks)) - 1
    gb = math.exp(math.fsum(math.log1p(b[k]) for k in ks) / len(ks)) - 1
    t = nw_t_any(ex)
    rd = (lambda x, n: x) if raw else round
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex_ann': rd(S.mean(ex) * 100, 2), 'cagr_diff': rd((gs - gb) * 100, 2),
            't_ref': rd(t, 2) if t is not None else None}


def es(s, b, a=None, z=None):
    return N.excess_stats(s, b, a, z, per_year=1, lag=LAG)


def es_raw(s, b, a=None, z=None):
    """excess_stats と同じ計算（per_year=1・NW ラグ2・24年未満は None）の、grade が見る欄だけを丸めずに返す（厳密な格付け用）"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = N.nw_t(ex, LAG)
    return {'ex_ann': S.mean(ex) * 100, 't': t, 'cagr_diff': (N.cagr([s[k] for k in ks], 1) - N.cagr([b[k] for k in ks], 1)) * 100}


def sharpe_raw(r, rf, a=None, z=None):
    ks = sorted(k for k in set(r) & set(rf) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    x = [r[k] - rf[k] for k in ks]
    sd = S.stdev(x)
    return S.mean(x) / sd if sd else None


def roll_annual(s, b, years=20, raw=False):
    ks = sorted(set(s) & set(b))
    out, skipped = [], 0
    for y0 in range(ks[0], ks[-1] - years + 2) if ks else []:
        w = range(y0, y0 + years)
        if not all(k in s and k in b for k in w):
            skipped += 1
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y0, (gs - gb) * 100 if raw else round((gs - gb) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    wr = sum(1 for _, c in out if c > 0) / len(out)
    return {'windows': len(out), 'skipped_incomplete_starts': skipped, 'wins': sum(1 for _, c in out if c > 0),
            'win_rate': wr if raw else round(wr, 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1]), 'first_start': out[0][0], 'last_start': out[-1][0]}


def dca_annual(s, b, years=20):
    ks = sorted(set(s) & set(b))
    out = []
    for y0 in ks:
        w = range(y0, y0 + years)
        if not all(k in s and k in b for k in w):
            continue
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append((y0, round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def sharpe_y(r, rf, a=None, z=None):
    return N.sharpe(r, rf, a, z, per_year=1)


def mdd(r, a=None, z=None):
    x = {k: v for k, v in r.items() if (a is None or k >= a) and (z is None or k <= z)}
    return round(N.maxdd(x) * 100, 1) if x else None


def net(s, cost, mult=1.0):
    return {k: s[k] - mult * cost.get(k, 0.0) for k in s}


def c2(st):
    return bool(st and st['ex_ann'] > 0 and st['cagr_diff'] > 0)


def p_hold(hold):
    if not hold or hold['t'] is None or hold['t'] <= 0:
        return 1.0
    return N.p_two(hold['t'])


# ───────────────────────── 1規則×1相手の評価 ─────────────────────────
def evaluate(s, b, cost, s_lb, first, timing, rf_rule=None, rf_bench=None, pub=None):
    sn = net(s, cost)
    out = {'first_hold_year': first, 'n_years': len(set(s) & set(b)),
           'train_gross': es(s, b, None, TRAIN_Z), 'hold_gross': es(s, b, HOLD_A, HOLD_Z), 'full_gross': es(s, b),
           'train_net': es(sn, b, None, TRAIN_Z), 'hold_net': es(sn, b, HOLD_A, HOLD_Z), 'full_net': es(sn, b),
           'roll20_net': roll_annual(sn, b), 'dca20_net': dca_annual(sn, b),
           'maxdd_pct': {'rule_net_full': mdd(sn), 'bench_full': mdd(b), 'rule_net_hold': mdd(sn, HOLD_A), 'bench_hold': mdd(b, HOLD_A)},
           'cost_avg_pct_hold': round(S.mean(cost[k] for k in cost if k >= HOLD_A) * 100, 3) if any(k >= HOLD_A for k in cost) else None,
           'cost_avg_pct_train': round(S.mean(cost[k] for k in cost if k <= TRAIN_Z) * 100, 3) if any(k <= TRAIN_Z for k in cost) else None}
    if rf_rule is not None:
        out['sharpe'] = {per: (sharpe_y(sn, rf_rule, a, z), sharpe_y(b, rf_bench, a, z))
                         for per, (a, z) in {'train': (None, TRAIN_Z), 'hold': (HOLD_A, HOLD_Z), 'full': (None, None)}.items()}
    # 厳密な格付け用（丸めない値で同じ線を当てる。出力には書かず、格付けと『丸めの境目』の印にだけ使う）
    out['_strict'] = {'train_gross': es_raw(s, b, None, TRAIN_Z), 'hold_gross': es_raw(s, b, HOLD_A, HOLD_Z), 'full_gross': es_raw(s, b),
                      'hold_net': es_raw(sn, b, HOLD_A, HOLD_Z), 'roll20_net': roll_annual(sn, b, raw=True),
                      'sharpe': ({per: (sharpe_raw(sn, rf_rule, a, z), sharpe_raw(b, rf_bench, a, z))
                                  for per, (a, z) in {'train': (None, TRAIN_Z), 'hold': (HOLD_A, HOLD_Z)}.items()} if rf_rule is not None else None)}
    out['periods_reported'] = {
        'p1950_1974_net': short(sn, b, 1950, 1974), 'pre_modern_all_net': short(sn, b, None, 1974),
        'p1975_2020_net': short(sn, b, 1975, 2020), 'p2007_2020_net': short(sn, b, 2007, 2020), 'p2007_2020_gross': short(s, b, 2007, 2020),
        'eras_net': {e: short(sn, b, a, z) for e, (a, z) in {'1872_1913': (1872, 1913), '1914_1949': (1914, 1949), '1950_1974': (1950, 1974),
                                                           '1975_2006': (1975, 2006), '2007_2020': (2007, 2020)}.items()},
        'post_publication_net': short(sn, b, pub, 2020) if pub else None, 'post_publication_from': pub}
    out['cost_sensitivity_hold'] = {str(m): short(net(s, cost, m), b, HOLD_A, HOLD_Z) for m in (0, 0.5, 1, 2)}
    out['lower_bound_hold_gross'] = es(s_lb, b, HOLD_A, HOLD_Z) if s_lb else None
    return out


def region_repl(res_by_region):
    """C5: 各地域の使える全期間（費用後）で 算術 > 0 かつ 幾何 > 0。20年未満の地域は数えない。
    戻り値の3つ目は丸めない値で同じ判定をした版（厳密な格付け用）"""
    det, n, k, ks = {}, 0, 0, 0
    for r, (sn, b) in res_by_region.items():
        st = short(sn, b)
        if not st or st.get('n', 0) < 20:
            det[r] = {'counted': False, 'stats_net': st}
            continue
        sr = short(sn, b, raw=True)
        pos = st['ex_ann'] > 0 and st['cagr_diff'] > 0
        n += 1; k += int(pos); ks += int(sr['ex_ann'] > 0 and sr['cagr_diff'] > 0)
        det[r] = {'counted': True, 'positive': pos, 'stats_net': st}
    return ({'regions': n, 'positive': k} if n >= 2 else None), det, ({'regions': n, 'positive': ks} if n >= 2 else None)


# ───────────────────────── 1規則の全部 ─────────────────────────
def run_sel(W, name, spec, view='main', universe=UNIVERSE):
    basis = 'usd' if view == 'sub2_usd' else spec['basis']
    extra = 0.001 if spec['basis'] == 'hedged' else 0.0
    sim = sim_sel(W, spec, universe, basis, MIN_SEL, extra=extra)
    b = bench(W, universe, basis, 'gdp' if view == 'sub1_gdp' else 'ew')
    rfb = bench_bill(W, universe, basis)
    first = min(sim['s']) if sim['s'] else None
    ev = evaluate(sim['s'], b, sim['cost'], sim['s_lb'], first, False, rf_rule=rfb, rf_bench=rfb, pub=spec.get('pub'))
    # C5: 地域ごとに同じ規則（3か国以上の年）をその地域の平均と比べる
    reg = {}
    for r, cs in REGIONS.items():
        rs = sim_sel(W, spec, cs, basis, MIN_SEL_REGION, extra=extra)
        rb = bench(W, cs, basis, 'gdp' if view == 'sub1_gdp' else 'ew')
        reg[r] = (net(rs['s'], rs['cost']), rb)
    repl, det, ev['_strict']['repl'] = region_repl(reg)
    return sim, b, ev, repl, det


def bench_bill(W, universe, basis):
    """選択の規則のシャープ（報告）用: その年に短期金利のある国の短期金利の等分平均"""
    out = {}
    for y in range(Y_FIRST + 1, Y_LAST + 1):
        xs = [W.ret('bill', 'real' if basis == 'hedged' else basis, c, y) for c in universe]
        xs = [x for x in xs if x is not None]
        if xs:
            out[y] = S.mean(xs) if basis != 'hedged' else 0.0  # 先物の基準は既に短期金利を引いてある
    return out


def run_tim(W, name, spec, view='main', universe=UNIVERSE, exclude=()):
    basis = 'usd' if view == 'sub2_usd' else 'real'
    weight = 'gdp' if view == 'sub1_gdp' else 'ew'
    sim = sim_tim(W, spec, universe, basis, weight, exclude)
    first = min(sim['s']) if sim['s'] else None
    ev = evaluate(sim['s'], sim['b'], sim['cost'], sim['s_lb'], first, True, rf_rule=sim['rf'], rf_bench=sim['rf'], pub=spec.get('pub'))
    ev['avg_fraction_out_of_stock'] = {'train': avg(sim['frac_out'], None, TRAIN_Z), 'hold': avg(sim['frac_out'], HOLD_A, HOLD_Z)}
    ev['avg_countries_in_set'] = {'train': avg(sim['nset'], None, TRAIN_Z), 'hold': avg(sim['nset'], HOLD_A, HOLD_Z)}
    reg = {}
    for r, cs in REGIONS.items():
        rs = sim_tim(W, spec, cs, basis, weight, exclude)
        reg[r] = (net(rs['s'], rs['cost']), rs['b'])
    repl, det, ev['_strict']['repl'] = region_repl(reg)
    return sim, sim['b'], ev, repl, det


def avg(d, a, z):
    x = [v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)]
    return round(S.mean(x), 3) if x else None


def grade_of(ev, repl, holm_p, timing):
    sp = ev.get('sharpe') or {}
    pair = {'train': sp.get('train'), 'hold': sp.get('hold')} if timing else None
    return N.grade(full=ev['full_gross'], train=ev['train_gross'], hold=ev['hold_gross'], roll20=ev['roll20_net'],
                   cost_hold=ev['hold_net'], repl=repl, family_holm_p=holm_p, sharpe_pair=pair, leveraged_or_timing=timing)


def sel_counts(sim):
    cnt, cnt_hold = {}, {}
    for y, h in sim['hold'].items():
        for c in h['sel']:
            cnt[c] = cnt.get(c, 0) + 1
            if y >= HOLD_A:
                cnt_hold[c] = cnt_hold.get(c, 0) + 1
    return dict(sorted(cnt.items(), key=lambda x: -x[1])), dict(sorted(cnt_hold.items(), key=lambda x: -x[1]))


def sel_contrib(W, sim, basis, universe):
    """全期間の算術の超過（費用前）の国別の分解: Σ_y (w_rule − w_bench)·(r − b)"""
    b = bench(W, universe, basis)
    con = {}
    for y, h in sim['hold'].items():
        if y not in b or not h['held']:
            continue
        bs = [c for c in universe if W.ret('eq', basis, c, y) is not None]
        for c in set(h['held']) | set(bs):
            r = W.ret('eq', basis, c, y)
            ws = 1 / len(h['held']) if c in h['held'] else 0.0
            wb = 1 / len(bs) if c in bs else 0.0
            con[c] = con.get(c, 0.0) + (ws - wb) * (r - b[y])
    return {c: round(v * 100, 2) for c, v in sorted(con.items(), key=lambda x: -x[1])}


# ───────────────────────── 検算（事前登録の sanity_checks） ─────────────────────────
def sanity(raw_json, data):
    out = {}
    out['sha1_matches'] = raw_json['sha1'] == SHA_EXPECTED
    out['sha1'] = raw_json['sha1']
    W = World(data)
    # (2) 年 t の持ち高が年 t+1 以降の値に依存しない
    rng = random.Random(1)
    look = {}
    for t in (1905, 1938, 1972, 1999):
        d2 = copy.deepcopy(data)
        for c in d2:
            for y in d2[c]:
                if y > t:
                    for col in ('eq_tr', 'eq_dp', 'eq_capgain', 'bill_rate', 'bond_tr', 'cpi', 'xrusd', 'rgdpmad', 'ltrate'):
                        if fnum(d2[c][y].get(col)) is not None:
                            d2[c][y][col] = d2[c][y][col] * rng.uniform(0.5, 1.5)
                if y >= t:  # 信用は t−1 までしか使わない
                    for col in ('tloans', 'thh', 'gdp'):
                        if fnum(d2[c][y].get(col)) is not None:
                            d2[c][y][col] = d2[c][y][col] * rng.uniform(0.5, 1.5)
        W2 = World(d2)
        same = True
        for nm, sp in SEL.items():
            if choose(W, sp, UNIVERSE, t, MIN_SEL)[0] != choose(W2, sp, UNIVERSE, t, MIN_SEL)[0]:
                same = False; look.setdefault('changed', []).append((nm, t))
        for nm, sp in TIM.items():
            for c in UNIVERSE:
                if position(W, sp, c, t) != position(W2, sp, c, t):
                    same = False; look.setdefault('changed', []).append((nm, c, t))
        look[str(t)] = same
    out['no_lookahead_selection_and_positions'] = look
    # (3) 欠測扱いが規則と相手の両方から落ちている（0 で埋めない）
    flagged = sorted((c, y) for c in UNIVERSE for y in range(Y_FIRST + 1, Y_LAST + 1) if W.missing(c, y))
    b = bench(W, UNIVERSE, 'real')
    viol = []
    for c, y in flagged:
        if W.ret('eq', 'real', c, y) is not None:
            viol.append((c, y))
    sim = sim_sel(W, SEL['P1_dy_top3rd'], UNIVERSE, 'real', MIN_SEL)
    for y, h in sim['hold'].items():
        for c in h['held']:
            if W.missing(c, y):
                viol.append(('held', c, y))
    out['missing_flagged_country_years'] = [f'{c} {y}' for c, y in flagged]
    out['missing_dropped_from_rule_and_bench'] = not viol
    out['hyperinflation_over_100pct'] = [f'{c} {y}' for c in UNIVERSE for y in range(Y_FIRST + 1, Y_LAST + 1) if W.hyper(c, y)]
    # (4) 相手（等分）= その年にリターンのある国の単純平均
    ok = all(abs(b[y] - S.mean([W.ret('eq', 'real', c, y) for c in UNIVERSE if W.ret('eq', 'real', c, y) is not None])) < 1e-12 for y in b)
    out['bench_equals_simple_average_all_years'] = ok
    # (5) 上位1/3 = ceil(N/3)、6か国未満の年は組まない
    ok5, minN = True, 99
    for nm, sp in SEL.items():
        if sp['k'] != 'third' or sp.get('mode'):
            continue
        s5 = sim_sel(W, sp, UNIVERSE, sp['basis'], MIN_SEL)
        for y, h in s5['hold'].items():
            minN = min(minN, h['n_elig'])
            if len(h['sel']) != math.ceil(h['n_elig'] / 3) or h['n_elig'] < 6:
                ok5 = False
    out['top_third_is_ceil_N_over_3_and_N_ge_6'] = ok5
    out['min_eligible_N_in_any_formation'] = minN
    # (6) Δ3 の閾値は t−1 までのデータだけ（(2) の中で信用を t 以降入れ替えて確認済み）
    out['credit_threshold_uses_data_to_t_minus_1'] = all(v for k, v in look.items() if k != 'changed')
    # (7) 片道の売買が 0〜1、全部入れ替えると 1
    tos = [v for nm, sp in SEL.items() for v in sim_sel(W, sp, UNIVERSE, sp['basis'], MIN_SEL)['turn'].values()]
    out['turnover_range'] = [round(min(tos), 4), round(max(tos), 4)]
    new = {'A': 0.5, 'B': 0.5}; drift = {'C': 0.5, 'D': 0.5}
    out['full_replacement_turnover'] = 0.5 * sum(abs(new.get(c, 0) - drift.get(c, 0)) for c in set(new) | set(drift))
    return out


# ───────────────────────── 現代の器の答え合わせ（報告・格付けしない） ─────────────────────────
ETF = {'AUS': 'EWA', 'BEL': 'EWK', 'CHE': 'EWL', 'DEU': 'EWG', 'ESP': 'EWP', 'FRA': 'EWQ', 'GBR': 'EWU', 'ITA': 'EWI', 'JPN': 'EWJ',
       'NLD': 'EWN', 'SWE': 'EWD', 'DNK': 'EDEN', 'FIN': 'EFNL', 'NOR': 'ENOR', 'PRT': 'PGAL', 'USA': 'SPY'}


def etf_check():
    import urllib.parse, datetime
    out = {'note': '報告のみ・格付けしない。Yahoo の配当込みの調整後終値（生き残りの偏りは小さい: 1996年の器は全部現存）。信号の配当利回り = 直近12か月の分配 ÷ 年末の値。勢い・逆張りは器のドル建ての年次リターン（現地の値で測る事前登録の約束は器では守れない）。P5 は BIS の信用を取っていないので測っていない'}
    yr_ret, dy = {}, {}
    fails = {}
    for c, tk in ETF.items():
        try:
            u = f'https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1=0&period2={int(__import__("time").time())}&interval=1mo&events=div%2Csplit'
            j = json.loads(N.get(u, name=f'yh_{tk}_1mo_divraw.json', max_age_days=7))
            r = j['chart']['result'][0]
            ts, adj = r['timestamp'], r['indicators']['adjclose'][0]['adjclose']
            close = r['indicators']['quote'][0]['close']
            dec_adj, dec_close = {}, {}
            for t, a, cl in zip(ts, adj, close):
                d = datetime.datetime.utcfromtimestamp(t)
                if d.month == 12 and a is not None and cl is not None:
                    dec_adj[d.year] = a; dec_close[d.year] = cl  # 月足の12月の値＝年末
            divs = {}
            for _, ev in (r.get('events', {}).get('dividends') or {}).items():
                d = datetime.datetime.utcfromtimestamp(ev['date'])
                divs[d.year] = divs.get(d.year, 0.0) + ev['amount']
            for y in dec_adj:
                if y - 1 in dec_adj:
                    yr_ret.setdefault(c, {})[y] = dec_adj[y] / dec_adj[y - 1] - 1
                dy.setdefault(c, {})[y] = divs.get(y, 0.0) / dec_close[y]
        except Exception as e:  # noqa
            fails[c] = str(e)[:120]
    out['fetch_failures'] = fails
    if len(yr_ret) < 6:
        out['result'] = 'not_obtained'
        return out
    # 年次（1997〜2025）。完全な暦年だけ（最後の年は12月まで無ければ落とす）
    years = range(1997, 2026)
    b = {}
    for y in years:
        xs = [yr_ret[c][y] for c in yr_ret if y in yr_ret[c]]
        if len(xs) >= 6:
            b[y] = S.mean(xs)
    res = {}
    for nm in ('P1_dy_top3rd', 'P2_mom_top3rd', 'P3_rev_bottom3rd', 'P4_vm_top3rd'):
        s = {}
        for y in years:
            t = y - 1
            sig = {}
            for c in yr_ret:
                if nm.startswith('P1'):
                    v = dy.get(c, {}).get(t)
                elif nm.startswith('P2'):
                    v = yr_ret[c].get(t)
                elif nm.startswith('P3'):
                    xs = [yr_ret[c].get(k) for k in range(t - 4, t)]
                    v = None if None in xs else math.prod(1 + x for x in xs) - 1
                else:
                    v = (dy.get(c, {}).get(t), yr_ret[c].get(t))
                    v = None if None in v else v
                if v is not None and y in yr_ret[c]:
                    sig[c] = v
            n = len(sig)
            if n < 6:
                continue
            if nm.startswith('P4'):
                o1 = sorted(sig, key=lambda c: (-sig[c][0], c)); o2 = sorted(sig, key=lambda c: (-sig[c][1], c))
                sc = {c: (1 - o1.index(c) / (n - 1)) + (1 - o2.index(c) / (n - 1)) for c in sig}
                sel = sorted(sig, key=lambda c: (-sc[c], c))[:math.ceil(n / 3)]
            else:
                d = -1 if nm.startswith('P3') else 1
                sel = sorted(sig, key=lambda c: (-d * sig[c], c))[:math.ceil(n / 3)]
            s[y] = S.mean(yr_ret[c][y] for c in sel)
        res[nm] = {'gross_vs_equal_etfs': short(s, b), 'years': len(s)}
    out['result'] = res
    out['years_with_bench'] = [min(b), max(b)] if b else None
    return out


# ───────────────────────── 事後の診断（結果を見た後に足した・格付けに使わない） ─────────────────────────
def posthoc(W, data):
    out = {'label': '事後（結果を見た後に足した診断）。格付けには使わない。規則の中身は変えていない'}
    main_rules = ['P1_dy_top3rd', 'P4_vm_top3rd', 'X1a_dy_K3', 'X1b_dy_top4th', 'X1c_dy_top_half', 'X1d_dy10_top3rd', 'X1i_vmc_top3rd', 'X3b_mom', 'X3d_vm']

    def run(Wx, spec, universe=UNIVERSE):
        basis = spec['basis']
        sim = sim_sel(Wx, spec, universe, basis, MIN_SEL, extra=0.001 if basis == 'hedged' else 0.0)
        return sim, bench(Wx, universe, basis)

    # A) 1年ずらし: 年 t−1 の信号で年 t+1 を持つ。配当利回り d_t/p_t と翌年のリターン (p_{t+1}+d)/p_t は同じ年末の株価 p_t を共有するので、
    #    p_t の測定誤差（年平均と年末の混在・薄い取引）だけで『高い配当利回り→翌年高いリターン』が機械的に出うる。1年ずらすとこの経路は消える
    skip = {}
    for nm in main_rules:
        sp = dict(SEL[nm]); sp['skip'] = 1
        sim, b = run(W, sp)
        sn = net(sim['s'], sim['cost'])
        skip[nm] = {'train_gross': es(sim['s'], b, None, TRAIN_Z), 'hold_gross': es(sim['s'], b, HOLD_A, HOLD_Z), 'hold_net': short(sn, b, HOLD_A, HOLD_Z),
                    'full_gross_t': (es(sim['s'], b) or {}).get('t'), 'p1950_1974_net': short(sn, b, 1950, 1974), 'p1975_2020_net': short(sn, b, 1975, 2020),
                    'p2007_2020_net': short(sn, b, 2007, 2020)}
    out['A_skip_one_year_signal'] = skip
    # B) 配当利回りの三分位の単調性（上・中・下 と 等分の相手）
    ter = {}
    for mode in ('top', 'middle', 'last'):
        sp = dict(SEL['P1_dy_top3rd']); sp['mode'] = None if mode == 'top' else mode
        sim, b = run(W, sp)
        ter[mode] = {'train_gross': short(sim['s'], b, None, TRAIN_Z), 'hold_gross': short(sim['s'], b, HOLD_A, HOLD_Z), 'full_gross': short(sim['s'], b),
                     '_s': sim['s']}
    spread = {y: ter['top']['_s'][y] - ter['last']['_s'][y] for y in ter['top']['_s'] if y in ter['last']['_s']}
    zero = {y: 0.0 for y in spread}
    ter['top_minus_bottom'] = {'train': short(spread, zero, None, TRAIN_Z), 'hold': short(spread, zero, HOLD_A, HOLD_Z), 'full': short(spread, zero),
                               'p2007_2020': short(spread, zero, 2007, 2020)}
    for k in ('top', 'middle', 'last'):
        ter[k].pop('_s')
    out['B_dy_tercile_monotonicity'] = ter
    # C) 見つけたデータの欠陥: PRT の 2016〜2020 は配当利回りが 0.03〜0.05%（それ以前は 2.6〜4.7%）＝桁の誤りとみられ、総リターンから配当が抜けている疑い。
    #    PRT の 2016〜2020 を欠測にして回し直す
    d2 = copy.deepcopy(data)
    for y in range(2016, 2021):
        for col in ('eq_tr', 'eq_dp', 'eq_capgain', 'eq_div_rtn'):
            d2['PRT'][y][col] = None
    W2 = World(d2)
    prt = {'observed_PRT_eq_dp_pct_2012_2020': {y: round(data['PRT'][y]['eq_dp'] * 100, 3) for y in range(2012, 2021)}}
    for nm in main_rules:
        sim, b = run(W2, SEL[nm])
        sn = net(sim['s'], sim['cost'])
        prt[nm] = {'hold_gross': short(sim['s'], b, HOLD_A, HOLD_Z), 'hold_net': short(sn, b, HOLD_A, HOLD_Z), 'p2007_2020_net': short(sn, b, 2007, 2020)}
    out['C_PRT_2016_2020_dividend_data_flaw'] = prt
    # D) 現代の器と同じ窓（1997〜2020）で JST の規則を見る（器の答え合わせとの比較のため）
    same = {}
    for nm in ('P1_dy_top3rd', 'P2_mom_top3rd', 'P3_rev_bottom3rd', 'P4_vm_top3rd'):
        sp = SEL[nm]
        for basis in ('real', 'usd'):
            sim = sim_sel(W, sp, UNIVERSE, basis, MIN_SEL)
            b = bench(W, UNIVERSE, basis)
            same.setdefault(nm, {})[basis] = short(sim['s'], b, 1997, 2020)
    out['D_jst_same_window_as_etf_1997_2020_gross'] = same
    # E) 転がる窓の年ごとの差（費用後）: P1 と X1b の20年・10年
    rolls = {}
    for nm in ('P1_dy_top3rd', 'X1b_dy_top4th', 'P4_vm_top3rd'):
        sim, b = run(W, SEL[nm])
        sn = net(sim['s'], sim['cost'])
        for yrs in (10, 20):
            lst = []
            for y0 in sorted(set(sn) & set(b)):
                w = range(y0, y0 + yrs)
                if all(k in sn and k in b for k in w):
                    gs = math.exp(math.fsum(math.log1p(sn[k]) for k in w) / yrs) - 1
                    gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / yrs) - 1
                    lst.append([y0, round((gs - gb) * 100, 2)])
            rolls.setdefault(nm, {})[f'{yrs}y'] = {'by_start_year': lst, 'win_rate': round(sum(1 for _, v in lst if v > 0) / len(lst), 3),
                                                   'win_rate_starts_ge_1950': round(sum(1 for y, v in lst if v > 0 and y >= 1950) / max(1, sum(1 for y, _ in lst if y >= 1950)), 3),
                                                   'last_10_starts': lst[-10:]}
    out['E_rolling_by_start_year_net'] = rolls
    # F) 超過の中身: 選んだ国と全部の国の『配当の収益（d_t/p_{t−1}）』と『名目の値上がり』の差の平均（現地通貨・名目・近似）
    sim, b = run(W, SEL['P1_dy_top3rd'])
    dd, cg = [], []
    for y, h in sim['hold'].items():
        if y < HOLD_A or not h['held']:
            continue
        allc = [c for c in UNIVERSE if W.ret('eq', 'real', c, y) is not None]
        f = lambda cs, col: [W.v(c, y, col) for c in cs if W.v(c, y, col) is not None]
        a1, a2 = f(h['held'], 'eq_div_rtn'), f(allc, 'eq_div_rtn')
        g1, g2 = f(h['held'], 'eq_capgain'), f(allc, 'eq_capgain')
        if a1 and a2:
            dd.append(S.mean(a1) - S.mean(a2))
        if g1 and g2:
            cg.append(S.mean(g1) - S.mean(g2))
    # G) 選べる国の読み方の感度: 事前登録の eligibility「かつその年が欠測扱いでない国」を文字どおり（年 t が超インフレの国も選ばない）に読んだ場合
    alt = {}
    for nm in main_rules:
        sp = dict(SEL[nm]); sp['strict_elig'] = True
        sim2, b2 = run(W, sp)
        alt[nm] = {'train_gross': short(sim2['s'], b2, None, TRAIN_Z), 'hold_gross': short(sim2['s'], b2, HOLD_A, HOLD_Z), 'hold_net': short(net(sim2['s'], sim2['cost']), b2, HOLD_A, HOLD_Z)}
    out['G_strict_eligibility_reading'] = alt
    out['F_P1_hold_components_nominal_pct'] = {'dividend_return_diff': round(S.mean(dd) * 100, 2), 'capital_gain_diff': round(S.mean(cg) * 100, 2),
                                               'note': '名目・現地通貨の単純平均の差（実質の相手との差とは基準が違う＝目安）。eq_tr と値上がり＋配当の恒等式が合わない国・年があるので足しても超過に一致しない'}
    return out


# ───────────────────────── 本体 ─────────────────────────
GRADE_ORDER = 'SABC'


def grade_strict_of(ev, holm_p_strict, timing):
    """同じ線（nx_common.grade）を丸めない値に当てる。excess_stats は t を小数2桁に丸めるので、t=2.9986 が 3.00 として C7 を通りうる"""
    st = ev['_strict']
    sp = st.get('sharpe') or {}
    pair = {'train': sp.get('train'), 'hold': sp.get('hold')} if timing else None
    return N.grade(full=st['full_gross'], train=st['train_gross'], hold=st['hold_gross'], roll20=st['roll20_net'],
                   cost_hold=st['hold_net'], repl=st.get('repl'), family_holm_p=holm_p_strict, sharpe_pair=pair, leveraged_or_timing=timing)


def run_all(W):
    """全規則×相手を回し、Holm（族×相手ごと）を掛けて格付けする。
    格付けは nx_common.grade を、登録どおりの excess_stats の値（丸めあり）と丸めない値の両方に当て、低いほうを採る（丸めの境目は不利な側へ）"""
    tested, holm_sets = {}, {}
    views = ['main', 'sub1_gdp', 'sub2_usd']
    # 1) 全規則を回す
    for name in ORDER:
        if name == 'X4a_ew_vs_gdp':
            spec = dict(fam='X4', all=True, basis='real')
            sim = sim_sel(W, spec, UNIVERSE, 'real', MIN_SEL)
            b = bench(W, UNIVERSE, 'real', 'gdp')
            rfb = bench_bill(W, UNIVERSE, 'real')
            ev = evaluate(sim['s'], b, sim['cost'], sim['s_lb'], min(sim['s']), False, rf_rule=rfb, rf_bench=rfb)
            reg = {}
            for r, cs in REGIONS.items():
                rs = sim_sel(W, spec, cs, 'real', MIN_SEL_REGION)
                reg[r] = (net(rs['s'], rs['cost']), bench(W, cs, 'real', 'gdp'))
            repl, det, ev['_strict']['repl'] = region_repl(reg)
            tested[name] = {'family': 'X4', 'kind': 'equal_country', 'views': {'main': {'ev': ev, 'repl': repl, 'repl_detail': det}}, '_sim': {'main': sim}}
            continue
        fam = (SEL.get(name) or TIM.get(name))['fam']
        timing = name in TIM
        vs = views if fam == 'P' else ['main']
        tested[name] = {'family': fam, 'kind': 'timing' if timing else 'selection', 'views': {}, '_sim': {}}
        for v in vs:
            if timing:
                sim, b, ev, repl, det = run_tim(W, name, TIM[name], v)
            else:
                sim, b, ev, repl, det = run_sel(W, name, SEL[name], v)
            tested[name]['views'][v] = {'ev': ev, 'repl': repl, 'repl_detail': det}
            tested[name]['_sim'][v] = sim
            tested[name]['_b_' + v] = b

    # 2) Holm（族×相手ごと）→ 格付け
    fams, fams_s = {}, {}
    for name, t in tested.items():
        for v in t['views']:
            ev = t['views'][v]['ev']
            fams.setdefault((t['family'], v), {})[name] = p_hold(ev['hold_gross'])
            hs = ev['_strict']['hold_gross']
            fams_s.setdefault((t['family'], v), {})[name] = 1.0 if (not hs or hs['t'] is None or hs['t'] <= 0) else N.p_two(hs['t'])
    for key, ps in fams.items():
        hp, hps = N.holm(ps), N.holm(fams_s[key])
        for name in ps:
            tested[name]['views'][key[1]]['p_hold_two_sided'] = round(ps[name], 4)
            tested[name]['views'][key[1]]['holm_p'] = hp[name]
            tested[name]['views'][key[1]]['holm_p_strict'] = hps[name]
            holm_sets[f'{key[0]}|{key[1]}'] = {'n': len(ps), 'rules': sorted(ps)}
    for name, t in tested.items():
        for v, x in t['views'].items():
            timing = t['kind'] == 'timing'
            g1, c1 = grade_of(x['ev'], x['repl'], x['holm_p'], timing)
            g2, c2_ = grade_strict_of(x['ev'], x['holm_p_strict'], timing)
            worse = GRADE_ORDER.index(g2) > GRADE_ORDER.index(g1)
            x['grade'], x['criteria'] = (g2, c2_) if worse else (g1, c1)
            x['grade_tool_rounded'], x['grade_strict_unrounded'] = g1, g2
            x['rounding_boundary'] = g1 != g2
            if g1 != g2:
                x['criteria_tool_rounded'], x['criteria_strict_unrounded'] = c1, c2_
    return tested, holm_sets


def compact(tested):
    """規則×相手ごとの要点（是正の前後・感度の比較用）"""
    out = {}
    for name in ORDER:
        t = tested[name]
        for v, x in t['views'].items():
            ev = x['ev']
            g = lambda k, f: (ev.get(k) or {}).get(f)
            st = ev['_strict']['full_gross'] or {}
            out[f'{name}|{v}'] = {'grade': x['grade'], 'grade_tool_rounded': x['grade_tool_rounded'],
                                  'train_ex': g('train_gross', 'ex_ann'), 'train_t': g('train_gross', 't'),
                                  'hold_ex': g('hold_gross', 'ex_ann'), 'hold_t': g('hold_gross', 't'),
                                  'full_t': g('full_gross', 't'), 'full_t_unrounded': round(st['t'], 4) if st.get('t') is not None else None,
                                  'hold_net_cagr_diff': g('hold_net', 'cagr_diff'), 'roll20_win_net': g('roll20_net', 'win_rate'),
                                  'C5': x['repl'], 'holm_p': x['holm_p'],
                                  'p2007_2020_net_cagr_diff': (ev['periods_reported'].get('p2007_2020_net') or {}).get('cagr_diff')}
    return out


def diff_compact(before, after):
    """compact どうしで値が動いた規則×相手だけを『前 → 後』で並べる"""
    out = {}
    for k in after:
        a, b = before.get(k, {}), after[k]
        ch = {f: [a.get(f), b[f]] for f in b if a.get(f) != b[f]}
        if ch:
            out[k] = ch
    return out


def main():
    raw, data0 = load_raw()
    pre = json.load(open(PRE))
    data = mask_prt(data0) if FIX['prt_mask'] else data0
    W = World(data, 1.0)
    W50, WNONE = World(data, 0.5), World(data, None)
    tested, holm_sets = run_all(W)

    # 3) 報告（格付けしない）: 米国だけ・米国を除く・選んだ国・最大寄与の1か国を抜いた版・欠測の閾値の感度・印
    for name, t in tested.items():
        x = t['views']['main']
        sim = t['_sim']['main']
        timing = t['kind'] == 'timing'
        spec = TIM.get(name) or SEL.get(name) or dict(fam='X4', all=True, basis='real')
        basis = spec.get('basis', 'real')
        rep = {}
        if timing:
            us = sim_tim(W, spec, ['USA'], 'real')
            exus = sim_tim(W, spec, [c for c in UNIVERSE if c != 'USA'], 'real')
            rep['usa_only_timing'] = {'hold_net': short(net(us['s'], us['cost']), us['b'], HOLD_A, HOLD_Z), 'full_net': short(net(us['s'], us['cost']), us['b'])}
            rep['ex_usa_timing'] = {'hold_net': short(net(exus['s'], exus['cost']), exus['b'], HOLD_A, HOLD_Z), 'full_net': short(net(exus['s'], exus['cost']), exus['b'])}
            con = {c: round(v * 100, 2) for c, v in sorted(sim['contrib'].items(), key=lambda z: -z[1])}
        else:
            sn = net(sim['s'], sim['cost'])
            usb = {y: W.ret('eq', basis, 'USA', y) for y in range(Y_FIRST + 1, Y_LAST + 1) if W.ret('eq', basis, 'USA', y) is not None}
            exb = bench(W, [c for c in UNIVERSE if c != 'USA'], basis)
            rep['vs_usa_only'] = {'hold_net': short(sn, usb, HOLD_A, HOLD_Z), 'full_net': short(sn, usb), 'hold_gross_stats': es(sim['s'], usb, HOLD_A, HOLD_Z)}
            rep['vs_ex_usa_equal'] = {'hold_net': short(sn, exb, HOLD_A, HOLD_Z), 'full_net': short(sn, exb), 'hold_gross_stats': es(sim['s'], exb, HOLD_A, HOLD_Z)}
            if not spec.get('all'):
                rep['selected_counts_all'], rep['selected_counts_hold'] = sel_counts(sim)
                rep['avg_selected'] = round(S.mean(len(h['sel']) for h in sim['hold'].values()), 2)
                rep['avg_eligible'] = round(S.mean(h['n_elig'] for h in sim['hold'].values()), 2)
                rep['years_with_selected_country_missing'] = sorted(f"{y}:{','.join(h['missing'])}" for y, h in sim['hold'].items() if h['missing'])
            con = sel_contrib(W, sim, basis, UNIVERSE) if not spec.get('all') else {}
        rep['contribution_by_country_full_gross_pct_sum'] = con
        if con:
            top = next(iter(con))
            uni2 = [c for c in UNIVERSE if c != top]
            if timing:
                d2 = sim_tim(W, spec, UNIVERSE, 'real', exclude=(top,))
                bb = d2['b']
            else:
                d2 = sim_sel(W, spec, uni2, basis, MIN_SEL, extra=0.001 if basis == 'hedged' else 0.0)
                bb = bench(W, uni2, basis)
            rep['drop_top_contributor'] = {'dropped': top, 'hold_gross': short(d2['s'], bb, HOLD_A, HOLD_Z), 'hold_net': short(net(d2['s'], d2['cost']), bb, HOLD_A, HOLD_Z),
                                           'full_net': short(net(d2['s'], d2['cost']), bb), 'train_net': short(net(d2['s'], d2['cost']), bb, None, TRAIN_Z)}
        # 欠測の閾値の感度（報告）
        ms = {}
        for lab, Wx in (('thr50', W50), ('none', WNONE)):
            if timing:
                d3 = sim_tim(Wx, spec, UNIVERSE, 'real'); bb = d3['b']
            else:
                d3 = sim_sel(Wx, spec, UNIVERSE, basis, MIN_SEL, extra=0.001 if basis == 'hedged' else 0.0); bb = bench(Wx, UNIVERSE, basis)
            ms[lab] = {'hold_gross': short(d3['s'], bb, HOLD_A, HOLD_Z), 'train_gross': short(d3['s'], bb, None, TRAIN_Z), 'full_net': short(net(d3['s'], d3['cost']), bb)}
        rep['missing_threshold_sensitivity'] = ms
        x['reported'] = rep
        # 印
        ev = x['ev']
        a, z = ev['periods_reported']['p1950_1974_net'], ev['periods_reported']['p1975_2020_net']
        flags = {'現代依存': bool(a and z and a.get('ex_ann') is not None and z.get('ex_ann') is not None and a['ex_ann'] <= 0 < z['ex_ann']),
                 '欠け依存': bool(c2(ev['hold_gross']) and not c2(ev['lower_bound_hold_gross']))}
        if t['family'] == 'P':
            main_win = x['grade'] in ('S', 'A')
            flags['小国寄り'] = bool(main_win and t['views']['sub1_gdp']['grade'] == 'C')
            flags['ドル依存'] = bool(main_win and not c2(t['views']['sub2_usd']['ev']['hold_gross']))
        x['flags'] = flags

    # 4) 検算・現代の器・事後の診断
    san = sanity(raw, data)
    post = posthoc(W, data)
    try:
        etf = etf_check()
    except Exception as e:  # noqa
        etf = {'result': 'not_obtained', 'error': str(e)[:200]}

    # 5) 書き出し
    out_tested = []
    for name in ORDER:
        t = tested[name]
        spec = TIM.get(name) or SEL.get(name) or {}
        fam_def = pre['families'][{'P': 'P_primary', 'X1': 'X1_selection_variants', 'X2': 'X2_timing_variants', 'X3': 'X3_hedged_basis', 'X4': 'X4_equal_country'}[t['family']]]['rules'][name]
        row = {'rule': name, 'family': t['family'], 'kind': t['kind'], 'definition_prereg': fam_def, 'views': {}}
        for v, x in t['views'].items():
            vv = {'grade': x['grade'], 'criteria': x['criteria'], 'p_hold_two_sided': x['p_hold_two_sided'], 'holm_p': x['holm_p'],
                  'repl_C5': x['repl'], 'repl_detail': x['repl_detail']}
            vv.update(x['ev'])
            if 'flags' in x:
                vv['flags'] = x['flags']
            if 'reported' in x:
                vv['reported'] = x['reported']
            row['views'][v] = vv
        out_tested.append(row)
    heads = [f"{r['rule']}（{r['views']['main']['grade']}）" for r in out_tested if r['views']['main']['grade'] in ('S', 'A')]
    summ = [{'rule': r['rule'], 'family': r['family'], 'view': v, 'grade': r['views'][v]['grade'],
             'train_ex_gross': (r['views'][v]['train_gross'] or {}).get('ex_ann'), 'train_t': (r['views'][v]['train_gross'] or {}).get('t'),
             'hold_ex_gross': (r['views'][v]['hold_gross'] or {}).get('ex_ann'), 'hold_t': (r['views'][v]['hold_gross'] or {}).get('t'),
             'hold_cagr_diff_net': (r['views'][v]['hold_net'] or {}).get('cagr_diff'), 'full_t': (r['views'][v]['full_gross'] or {}).get('t'),
             'roll20_win_net': (r['views'][v]['roll20_net'] or {}).get('win_rate'), 'holm_p': r['views'][v]['holm_p'],
             'C': ''.join(('1' if c is True else ('-' if c is None else '0')) for c in r['views'][v]['criteria'].values())}
            for r in out_tested for v in r['views']]
    obj = {'angle': 'nx_jst', 'prereg': 'out/nx_jst_prereg.json', 'data_sha1': raw['sha1'], 'generated': '2026-09-28',
           'periods': {'train': 'first hold year–1949', 'hold': '1950–2020', 'excess_stats': 'per_year=1, lag=2'},
           'headline_wins_main_S_or_A': heads,
           'summary_table': summ,
           'holm_families': holm_sets,
           'tested': out_tested,
           'sanity_checks': san,
           'real_instrument_check': etf,
           'rakuten_note': pre['real_instrument_check']['rakuten']}
    obj['deviations_from_prereg'] = DEVIATIONS
    # 事後: 勝った規則の『現代』の姿を一か所に並べる（数字は上の各欄からそのまま写す・格付けに使わない）
    mod = {}
    for r in out_tested:
        v = r['views']['main']
        if v['grade'] not in ('S', 'A'):
            continue
        rl = v['roll20_net'] or {}
        mod[r['rule']] = {'grade': v['grade'], 'p1950_1974_net': v['periods_reported']['p1950_1974_net'], 'p1975_2020_net': v['periods_reported']['p1975_2020_net'],
                          'p2007_2020_net_global_holdout': v['periods_reported']['p2007_2020_net'],
                          'post_publication_net': v['periods_reported']['post_publication_net'],
                          'roll20_worst': rl.get('worst'), 'roll20_last_start': rl.get('last_start'),
                          'etf_1997_2025_gross': ((etf.get('result') or {}).get(r['rule']) or {}).get('gross_vs_equal_etfs') if isinstance(etf.get('result'), dict) else None,
                          'skip_one_year_hold_gross': (post['A_skip_one_year_signal'].get(r['rule']) or {}).get('hold_gross')}
    post['H_winners_modern_era'] = mod
    obj['post_hoc'] = post
    p = N.save('nx_jst.json', obj)
    print('→', p)
    for r in summ:
        print(f"{r['rule']:26s} {r['view']:9s} {r['grade']}  C={r['C']}  train {r['train_ex_gross']}(t{r['train_t']})  hold {r['hold_ex_gross']}(t{r['hold_t']}) "
              f"net幾何 {r['hold_cagr_diff_net']}  full t{r['full_t']}  roll {r['roll20_win_net']}  holm {r['holm_p']}")
    print('sanity', json.dumps(san, ensure_ascii=False)[:1500])
    print('etf', json.dumps(etf, ensure_ascii=False)[:1500])
    return obj


DEVIATIONS = [
    '欠測扱い（年平均の CPI の伸び100%超・取引所の閉鎖〔eq_tr_interp=1〕）は、主の実質だけでなく副2（ドル建て）・X3（先物の基準）でも同じ国・年を落とした。事前登録は「その年のリターンを規則・相手の両方から落とす」と書くだけで基準を限っていないので、全基準で同じ国・年を欠測にした（基準ごとに母集団が変わらないように）',
    '事前登録は「その年の実質のリターンを使う信号〔勢い・逆張り〕はその国で欠け」とする。名目の株の総リターンを使う信号（X2g の株⇔短期金利の比較・X2h の三資産の比較）と X1d（平滑した配当利回り・窓の中の CPI を使う）も、欠測扱いの年を含めば欠けにした（同じ理由で時点のずれた値を使わない）。配当利回り（dy）は事前登録どおり超インフレの年でも使う',
    '配当利回りの信号は、補間の印（eq_dp_interp=1 または eq_tr_interp=1）の年は欠けにした（ESP 1937〜1940・PRT 1975〜1977。補間は後の値を使うので年末に分かった値ではない）。DEU 1946〜1947 の配当利回り 0.0（印なし・無配の年）はそのまま 0 として使った',
    '分位（P6・P7・X2b・X2c・X2e の閾値、X2f の中央値）は線形補間（numpy の既定と同じ）。『超えたら』は厳密に大きい。パネルは信号の値 Δ3(c,s)（s ≤ t＝データは t−1 まで）の全16か国の拡大窓で、年 t の横断の値そのものも含む（t−1 までのデータだけなので後知恵ではない）。P7 の株の3年の閾値のパネルも50件以上を要件にした（事前登録は信用のパネルにだけ50件と書いている）',
    '費用の片道の売買は、年 t+1 に実際にリターンのあった国（held）を等分した重みで数えた（選んだ国が欠けた年はその国を除いて等分し直す＝事前登録のリターンの数え方と一致させた）。最初の年と、組めなかった年の後の再開は現金からの買い（片道 0.5）とした。時代別の費用の率は保有する年（年 t+1）で決めた（1949年末の組み替えは 1950年の率 0.5%）',
    '切替の規則の費用: 前年に組に居なかった国の前年の持ち高は株100%（買い持ちと同じ）とみなした。切替の規則の組は、事前登録の bill_missing のとおり、降りる先が国債の規則（X2a・X2d・X2f）と三資産の X2h でも短期金利の欠けた国・年を落とした（シャープの無リスク金利に使うため）。降りる先の国債が欠けた年も落とした',
    '副1（GDP 加重）と副2（ドル建て）の切替の規則（P6・P7）: 副1は国ごとの（規則・買い持ち）を GDP の重み（年 t の値）で平均、副2は株・短期金利ともドル建てにして等分平均した（事前登録は相手ごとの見方を切替の規則について具体的に書いていない）',
    'GDP の重みの欠けは年 t から5年前（t−5）までの過去の値で埋めた',
    'X4a（16か国を等分）は、年 t に実質のリターンのある国が6か国以上になった年の翌年から組み、年 t+1 にリターンのある全ての国を等分（＝主の相手そのもの）。費用は選択と同じ（毎年の等分への組み戻しの片道の売買 × 時代別の率 ＋ 器の差 年0.3%）。C5 は各地域の等分と地域の GDP 加重の比較',
    'X1a（上位3か国）は地域の C5 でも固定の3か国（4か国の地域では4か国中3か国）',
    '下限版（欠け依存の印）: 切替の規則にも当てた——組の国の株のリターンが欠けた年は、持っていた資産のうち欠けたもの（株。超インフレの年は短期金利・国債も欠けるのでそれも）を −50% として規則にだけ入れた（相手からは落としたまま）。下限版は費用前で保有期間の C2 を見た',
    '選べる国（eligibility）の『かつその年が欠測扱いでない国』は、同じ事前登録の超インフレの項『配当利回り（比）はこの年でも使える』と合わせて、『その規則の信号の材料が欠測扱いの年に掛かっていない国』と読んだ（配当利回りの規則は年 t が超インフレでも選べる。8か国・年だけの違い）。文字どおりの読み（年 t が欠測扱いの国は選ばない）の結果は post_hoc.G に並べた',
    '現代の器の答え合わせ（報告）: PGAL（ポルトガル）は Yahoo から取れず15本で組んだ。勢い・逆張りの信号は器のドル建ての年次リターン（器では現地の値を持てない）。P5 は BIS の信用の統計を取得していないので器では測っていない',
    '最大寄与の1か国を抜いた版: 選択の規則はその国を母集団（選べる国と相手）から外して回し直し、切替の規則はその国を平均から外した（切替の閾値のパネルは16か国のまま）。寄与は全期間の算術の超過（費用前）の国別の分解 Σ_y (w_規則 − w_相手)(r − b)',
    '短い期間（2007〜2020 の14年・時代別・公表後・1950〜1974）は excess_stats が24年未満で計算しないので、算術の超過・幾何の年率差・参考の t（Newey-West ラグ2・最小3年）を自前で出した（格付けに使わない）。C5 の地域の判定も 20年以上なら同じ自前の計算（excess_stats の24年の下限に掛からないように）',
    '選択の規則のシャープ（報告）は、その年に短期金利のある国の実質の短期金利の等分平均を無リスク金利にした。X3（先物の基準）は既に短期金利を引いた超過なので無リスク金利 0',
]


if __name__ == '__main__':
    main()
