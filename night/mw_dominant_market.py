#!/usr/bin/env python3
"""night/mw_dominant_market.py — 『市場に勝てる歴史検証』の角度 dominant_market（読むだけ・門の判定には不使用）

問い: 『その時いちばん大きい／いちばん勝ってきた市場』に毎月積み立てる既定（＝今の S&P500・米国テック）は、
      16か国（JST 1870〜2020）と French の国別（1976〜2025）の投資家それぞれの自国通貨・実質で見て、
      世界に分ける積立に、どれだけの頻度で・どれだけ深く負けた（後悔した）か。
      あわせて、同じデータで『市場に勝つ規則』（世界に分ける／支配的な市場に寄せる／業種の勝者に寄せる）を
      out/mw_prereg.json の線（C1〜C8）で裁く。

事前登録: out/mw_dominant_market_prereg.json（線は out/mw_prereg.json・判定は mw_common.grade）
出力:     out/mw_dominant_market.json

使い方:
  python3 night/mw_dominant_market.py --check   # データの配管だけ点検（戦略と相手の比較は出さない）
  python3 night/mw_dominant_market.py           # 全部測って out/mw_dominant_market.json を書く

約束（mw_common に従う）
- 月次は yyyymm・年次は年（int）。リターンは小数
- 年末 Y−1（月次は Y−1 年12月末）に分かる値だけで年 Y の重みを決める（先読みなし・assert で検算）
- 欠けた値は 0 と読まない（ルール7）。JST の戦時の為替（1939〜1949）は未ヘッジの換算に使わない（deep_history と同じ）。
  超インフレ（年率100%以上）の国・年は無効
- JST の gdp 列は国ごとに単位が違う（十億・百万・兆）。世界銀行の米ドル GDP と 1960〜2020 の中央値で突き合わせ、
  10 の冪に丸めた単位で直す（直さずに gdp/xrusd を国の間で比べると、スペインや豪州が『世界最大』になる）
"""
import sys, os, io, json, math, zipfile, subprocess, statistics as S, argparse, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PREREG = 'out/mw_dominant_market_prereg.json'
PREREG2 = 'out/mw_dominant_market_prereg2.json'
PREREG3 = 'out/mw_dominant_market_prereg3.json'
OUT = 'mw_dominant_market.json'
JST_URL = 'https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx?t=1763503850'
WB = 'https://api.worldbank.org/v2/country/all/indicator/{}?format=json&per_page=20000&date={}'

C16 = 'AUS BEL CHE DEU DNK ESP FIN FRA GBR ITA JPN NLD NOR PRT SWE USA'.split()
FRF = {'GBR': 'UK', 'AUT': 'Austria', 'AUS': 'Austrlia', 'BEL': 'Belgium', 'CAN': 'Canada', 'DNK': 'Denmark',
       'FIN': 'Finland', 'FRA': 'France', 'DEU': 'Germany', 'HKG': 'HongKong', 'IRL': 'Ireland', 'ITA': 'Italy',
       'JPN': 'Japan', 'NLD': 'Nethrlnd', 'NZL': 'NewZland', 'NOR': 'Norway', 'SGP': 'Singapor', 'ESP': 'Spain',
       'SWE': 'Sweden', 'CHE': 'Swtzrlnd'}          # マレーシア（1994〜2001 で途切れる）は入れない
C21 = sorted(FRF) + ['USA']
EUR = 'AUT BEL CHE DEU DNK ESP FIN FRA GBR IRL ITA NLD NOR SWE'.split()
APAC = 'JPN AUS HKG SGP NZL'.split()
U_WAR = range(1939, 1950)
FEE_GAP = 0.001        # 年率: 複数国に分けた器の信託報酬の上乗せ（単一国の器に対して）
WHT = 0.002            # 年率: 自国の外の保有に掛かる源泉税の引きずり（重みに比例）
TC = 0.001             # 片道100%あたりの売買費用
MAJOR_W = 0.03         # D2 の『主要市場』= 相手の世界の重み 3% 以上
MAJOR_R = 0.10         # 地域の再現: 地域の時価の 10% 以上
T_MAJOR = 0.02         # 業種の再現（T1M）: 市場の時価の 2% 以上
RENORM_MIN = 0.85      # 複数国の器: 有効な国の重みがこれ未満の年は空欄（欠けた国を他の国の平均で埋めすぎない）
LS = (20, 25, 30)
M0, M1 = 197601, 202512   # 月次（French の国別の終わりは 2025-12）
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def ym_add(ym, k):
    y, m = divmod(ym, 100)
    n = y * 12 + (m - 1) + k
    return (n // 12) * 100 + n % 12 + 1


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = ym_add(m, 1)
    return out


# ───────────────────────── データ ─────────────────────────
def wb(ind, name, dates='1960:2025'):
    b = M.get(WB.format(ind, dates), name=name, max_age_days=3650)
    j = json.loads(b)
    return {(r['countryiso3code'], int(r['date'])): float(r['value']) for r in j[1] if r['value'] is not None}


def load_jst():
    import openpyxl
    b = M.get(JST_URL, 'jst_R6.xlsx', max_age_days=3650)
    wbk = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = list(wbk['Sheet1'].iter_rows(values_only=True))
    h = rows[0]
    cols = ['eq_tr', 'eq_capgain', 'cpi', 'xrusd', 'gdp']
    I = {c: h.index(c) for c in cols + ['year', 'iso']}
    D = {}
    for r in rows[1:]:
        iso = r[I['iso']]
        if iso not in C16:
            continue
        D.setdefault(iso, {})[int(r[I['year']])] = {c: (float(r[I[c]]) if r[I[c]] is not None else None) for c in cols}
    return D


def parse_fr_dat(txt):
    """French の国別 .Dat を節ごとに読む（night/mw_country.py の parse_fr_dat と同じ読み方の写し。他の角度のファイルに依存しないため）"""
    secs, cur, kind, grp, cols = {}, None, None, None, None
    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            cur = None
            continue
        tok = line.split()
        if tok[0].isdigit() and len(tok[0]) in (4, 6) and kind:
            freq = 'm' if len(tok[0]) == 6 else 'a'
            key = (kind, grp, freq)
            if cur is None:
                if key in secs:
                    key = key + (len(secs),)
                cur = secs[key] = {'cols': cols, 'data': {}}
            vals = []
            for v in tok[1:]:
                try:
                    f = float(v)
                except ValueError:
                    f = None
                vals.append(None if f is None or f <= -99.99 or f == -999 else f)
            cur['data'][int(tok[0])] = vals
            continue
        cur = None
        low = line.lower()
        if 'dollar' in low and 'return' in low:
            kind = 'USD'
        elif 'local' in low and 'return' in low:
            kind = 'LOC'
        elif 'ratio' in low or 'annual value-weight averages' in low:
            kind = 'RATIO'
        if 'not req' in low:
            grp = 'NR'
        elif 'required' in low or ' reqd' in low:
            grp = 'RQ'
        if tok[0] in ('Mkt', 'Firms'):
            cols = tok
    return secs


def load_french():
    """{国: {'usd': 総, 'loc': 現地総, 'px': ドル建て配当抜き}}（月次・小数）＋ 米国（French Mkt 総）"""
    zt = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip',
                                          name='fr_F-F_International_Countries.zip')))
    zx = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries_Wout_Div.zip',
                                          name='fr_F-F_International_Countries_Wout_Div.zip')))
    F = {}
    for c, f in FRF.items():
        a = parse_fr_dat(zt.read(f + '.Dat').decode('latin-1'))
        b = parse_fr_dat(zx.read(f + '.Dat').decode('latin-1'))
        col = lambda sec: {k: v[sec['cols'].index('Mkt')] / 100 for k, v in sec['data'].items() if v[sec['cols'].index('Mkt')] is not None}
        F[c] = {'usd': col(a[('USD', 'NR', 'm')]), 'loc': col(a[('LOC', 'NR', 'm')]), 'px': col(b[('USD', 'NR', 'm')])}
    ff = M.ff_factors()
    F['USA'] = {'usd': dict(ff['mkt']), 'loc': dict(ff['mkt']), 'px': None}
    return F, ff


# ───────────────────────── 時価総額の実時間の掃除 ─────────────────────────
def clean_caps(obs, growth, y0, y1):
    """obs {Y: 年末の時価（USD）}、growth(a, b) = 年末 a → 年末 b のドル建て価格の倍率（取れなければ None）。
    実時間: 年 Y の推定は Y 以前の観測だけで決まる。
    - 直前に採った観測を価格で運んだ値に対し 0.5〜2 倍の外なら棄却（世界銀行の表の桁違い・入力誤りの対策）
    - 互いに整合する棄却が3つ続いたら新しい水準と認めて採る
    - 観測の無い年は直前に採った観測を価格で運ぶ（純発行は 0 とみなす＝carry）。最初の観測より前は推定しない"""
    est, rej = {}, []
    last, pend = None, []
    for Y in range(y0, y1 + 1):
        if Y in obs:
            v = obs[Y]
            if last is None:
                last, pend = (Y, v), []
            else:
                g = growth(last[0], Y)
                if g is None:
                    last, pend = (Y, v), []
                else:
                    ratio = v / (last[1] * g)
                    if 0.5 <= ratio <= 2.0:
                        last, pend = (Y, v), []
                    else:
                        gp = growth(pend[-1][0], Y) if pend else None
                        if pend and gp is not None and 0.5 <= v / (pend[-1][1] * gp) <= 2.0:
                            pend.append((Y, v))
                        else:
                            pend = [(Y, v)]
                        if len(pend) >= 3:
                            rej.append((Y, round(ratio, 3), 'new_level_accepted'))
                            last, pend = (Y, v), []
                        else:
                            rej.append((Y, round(ratio, 3), 'rejected'))
        if last is not None:
            if last[0] == Y:
                est[Y] = (last[1], 'obs')
            else:
                g = growth(last[0], Y)
                if g is not None:
                    est[Y] = (last[1] * g, 'carry')
    return est, rej


def memo(f):
    """メソッドの結果を (引数) で覚える（重みと信号は年ごとに一度だけ計算する）"""
    def g(self, *a, **k):
        fz = lambda x: tuple(x) if isinstance(x, list) else x
        key = (f.__name__, tuple(fz(x) for x in a), tuple(sorted((kk, fz(v)) for kk, v in k.items())))
        c = self.__dict__.setdefault('_memo', {})
        if key not in c:
            c[key] = f(self, *a, **k)
        return c[key]
    return g


# ───────────────────────── JST（年次・16か国） ─────────────────────────
class JST:
    def __init__(self, D, wb_gdp, wb_cap):
        self.D = D
        # gdp の単位を 10 の冪で直す
        self.unit = {}
        for c in C16:
            rs = []
            for Y in range(1960, 2021):
                g, x = self.g(c, Y, 'gdp'), self.g(c, Y, 'xrusd')
                if g and x and (c, Y) in wb_gdp:
                    rs.append(wb_gdp[(c, Y)] / (g / x))
            m = S.median(rs)
            p = round(math.log10(m))
            self.unit[c] = {'pow10': p, 'resid_median': round(m / 10 ** p, 3), 'n': len(rs)}
            assert 0.8 < m / 10 ** p < 1.25, (c, m)
        self.first = {c: min(y for y in D[c] if D[c][y]['eq_tr'] is not None) for c in C16}
        # 時価総額（1975〜・世界銀行・実時間の掃除）
        self.cap, self.cap_rej = {}, {}
        for c in C16:
            obs = {Y: v for (cc, Y), v in wb_cap.items() if cc == c and Y <= 2019}
            est, rej = clean_caps(obs, lambda a, b, c=c: self.px_growth(c, a, b), 1975, 2019)
            self.cap[c], self.cap_rej[c] = est, rej

    def g(self, c, Y, k):
        return self.D.get(c, {}).get(Y, {}).get(k)

    def infl(self, c, Y):
        a, b = self.g(c, Y, 'cpi'), self.g(c, Y - 1, 'cpi')
        if a is None or b in (None, 0):
            return None
        v = a / b - 1
        return v if v < 1.0 else None

    def fx(self, c, Y):
        """その国の通貨のドル建ての変化 (x_{Y-1}/x_Y − 1)。戦時（1939〜1949）は無効"""
        if Y in U_WAR:
            return None
        x0, x1 = self.g(c, Y - 1, 'xrusd'), self.g(c, Y, 'xrusd')
        if not x0 or not x1:
            return None
        return x0 / x1 - 1

    def r_usd(self, c, Y):
        eq = self.g(c, Y, 'eq_tr')
        if eq is None or self.infl(c, Y) is None:
            return None
        if c == 'USA':
            return eq if Y not in U_WAR else None
        f = self.fx(c, Y)
        return None if f is None else (1 + eq) * (1 + f) - 1

    def r_real_local(self, c, Y):
        eq, i = self.g(c, Y, 'eq_tr'), self.infl(c, Y)
        return None if eq is None or i is None else (1 + eq) / (1 + i) - 1

    def px_growth(self, c, a, b):
        w = 1.0
        for t in range(a + 1, b + 1):
            cg = self.g(c, t, 'eq_capgain')
            if cg is None or self.infl(c, t) is None:
                return None
            if c != 'USA':
                f = self.fx(c, t)
                if f is None:
                    return None
                w *= (1 + cg) * (1 + f)
            else:
                w *= 1 + cg
        return w

    def gdp_usd(self, c, Y):
        g, x = self.g(c, Y, 'gdp'), self.g(c, Y, 'xrusd')
        return g / x * 10 ** self.unit[c]['pow10'] if g and x else None

    def r_home(self, h, j, Y):
        """自国 h の通貨・実質で見た市場 j の年 Y のリターン。無効なら None"""
        ih = self.infl(h, Y)
        if ih is None:
            return None
        if j == h:
            eq = self.g(j, Y, 'eq_tr')
            return None if eq is None or self.infl(j, Y) is None else (1 + eq) / (1 + ih) - 1
        if Y in U_WAR:
            return None
        ru = self.r_usd(j, Y)
        if ru is None:
            return None
        if h == 'USA':
            return (1 + ru) / (1 + ih) - 1
        fh = self.fx(h, Y)
        return None if fh is None else (1 + ru) / (1 + fh) / (1 + ih) - 1

    # ── 年 Y の重み（年末 Y−1 までの情報だけ） ──
    def univ(self, Y):
        return [c for c in C16 if self.first[c] <= Y - 1]

    @memo
    def w_gdp(self, Y):
        g = {c: self.gdp_usd(c, Y - 2) for c in self.univ(Y)}
        g = {c: v for c, v in g.items() if v}
        t = sum(g.values())
        return {c: v / t for c, v in g.items()} if g else None

    @memo
    def w_cap(self, Y):
        if Y < 1976 or Y - 1 > 2019:
            return None
        k = {c: self.cap[c].get(Y - 1) for c in self.univ(Y)}
        k = {c: v[0] for c, v in k.items() if v}
        t = sum(k.values())
        return {c: v / t for c, v in k.items()} if k else None

    @memo
    def w_bench(self, Y):
        return self.w_cap(Y) if Y >= 1976 else self.w_gdp(Y)

    @memo
    def w_ew(self, Y):
        u = self.univ(Y)
        return {c: 1 / len(u) for c in u}

    @memo
    def d1(self, Y):
        w = self.w_cap(Y) if Y >= 1976 else self.w_gdp(Y)
        return max(w, key=w.get) if w else None

    @memo
    def d2(self, Y, detail=False):
        wb_ = self.w_bench(Y)
        if not wb_:
            return None
        major = [c for c, v in wb_.items() if v >= MAJOR_W]
        yrs = list(range(Y - 20, Y))
        assert max(yrs) < Y
        war = any(y in U_WAR for y in yrs)
        sc = {}
        for c in major:
            w = 1.0
            for y in yrs:
                r = self.r_real_local(c, y) if war else self.r_usd(c, y)
                if r is None:
                    w = None; break
                w *= 1 + r
            if w is not None:
                sc[c] = w
        if not sc:
            return None
        best = max(sc, key=lambda c: (sc[c], c))
        return (best, 'real_local' if war else 'usd', len(sc)) if detail else best


def jst_weights(J, name, Y, h=None):
    if name == 'D1':
        c = J.d1(Y); return {c: 1.0} if c else None
    if name == 'D2':
        c = J.d2(Y); return {c: 1.0} if c else None
    if name == 'D3':
        return {'USA': 1.0}
    if name == 'W1':
        return J.w_gdp(Y)
    if name == 'W2':
        return J.w_cap(Y)
    if name == 'Wb':
        return J.w_bench(Y)
    if name == 'W3':
        return J.w_ew(Y)
    if name == 'H':
        return {h: 1.0} if J.first[h] <= Y - 1 else None
    if name == 'H50':
        b = J.w_bench(Y)
        if not b or J.first[h] > Y - 1:
            return None
        w = {c: 0.5 * v for c, v in b.items()}
        w[h] = w.get(h, 0) + 0.5
        return w
    raise ValueError(name)


MULTI = {'W1', 'W2', 'Wb', 'W3', 'H50'}


def jst_year(J, name, Y, h, stats):
    """年 Y の (総, 費用後, 自国外の重み, 回転) を返す。無効なら None"""
    w = jst_weights(J, name, Y, h)
    if not w:
        return None
    if name in MULTI and Y in U_WAR:
        return None
    rr = {c: J.r_home(h, c, Y) for c in w}
    valid = {c: v for c, v in w.items() if rr[c] is not None}
    if len(w) == 1 and not valid:
        return None
    vs = sum(valid.values())
    if vs < RENORM_MIN:
        return None
    if vs < 0.9999:
        stats['renorm'] = stats.get('renorm', 0) + 1
    r = sum(v * rr[c] for c, v in valid.items()) / vs
    # 回転: 前の年の重みがドル建てで漂った姿 → 今年の目標
    turn = 0.0
    wp = jst_weights(J, name, Y - 1, h)
    if wp:
        ru = {c: J.r_usd(c, Y - 1) for c in wp}
        if all(v is not None for v in ru.values()):
            tot = sum(wp[c] * (1 + ru[c]) for c in wp)
            drift = {c: wp[c] * (1 + ru[c]) / tot for c in wp}
            turn = 0.5 * sum(abs(w.get(c, 0) - drift.get(c, 0)) for c in set(w) | set(drift))
    foreign = sum(v for c, v in w.items() if c != h)
    cost = FEE_GAP * (name in MULTI) + WHT * foreign + TC * turn
    return r, r - cost, foreign, turn


def dca_annual(rs):
    """年次の近似（年の半ばに 1 実質単位ずつ積み立て）: w ← w(1+r) + √(1+r)"""
    w = 0.0
    for r in rs:
        w = w * (1 + r) + math.sqrt(1 + r)
    return w


def jst_flows(J, name, h, s, L):
    """流れだけ（売らない）: 毎年の積立をその年の D に入れ、持った国はそのまま持ち続ける。自国外は源泉税の引きずり"""
    hold = {}
    for Y in range(s, s + L):
        d = jst_weights(J, name, Y, h)
        if not d:
            return None
        c = next(iter(d))
        for j in list(hold):
            r = J.r_home(h, j, Y)
            if r is None:
                return None
            hold[j] *= 1 + r - (WHT if j != h else 0.0)
        r = J.r_home(h, c, Y)
        if r is None:
            return None
        hold[c] = hold.get(c, 0.0) + math.sqrt(1 + r - (WHT if c != h else 0.0))
    return sum(hold.values())


# ───────────────────────── French（月次・21か国） ─────────────────────────
class FR:
    def __init__(self, F, J, wb_gdp, wb_cap, wb_cpi):
        self.F, self.J, self.gdp, self.cpi = F, J, wb_gdp, wb_cpi
        self.start = {c: min(F[c]['usd']) for c in C21 if c != 'USA'}
        self.start['USA'] = M0
        # ドル建て価格の暦年の倍率（12か月そろう年だけ）
        self.pxa = {}
        for c in C21:
            src = F[c]['px'] if F[c]['px'] is not None else F[c]['usd']  # 米国は価格だけの系列が無い → 総（点検にしか使わない・米国の時価は欠けが無い）
            a = {}
            for Y in range(1975, 2026):
                ms = [Y * 100 + m for m in range(1, 13)]
                if all(m in src for m in ms):
                    a[Y] = math.prod(1 + src[m] for m in ms)
            self.pxa[c] = a
        self.cap, self.cap_rej = {}, {}
        for c in C21:
            obs = {Y: v for (cc, Y), v in wb_cap.items() if cc == c}
            est, rej = clean_caps(obs, lambda a, b, c=c: self.px_growth(c, a, b), 1975, 2025)
            self.cap[c], self.cap_rej[c] = est, rej
        # 自国通貨のドル建ての変化（French の USD と現地の比から）
        self.fxm = {}
        for c in C21:
            if c == 'USA':
                self.fxm[c] = {m: 0.0 for m in F['USA']['usd']}
            else:
                u, l = F[c]['usd'], F[c]['loc']
                self.fxm[c] = {m: (1 + u[m]) / (1 + l[m]) - 1 for m in u if m in l}

    def px_growth(self, c, a, b):
        w = 1.0
        for t in range(a + 1, b + 1):
            if t not in self.pxa[c]:
                return None
            w *= self.pxa[c][t]
        return w

    def univ(self, Y, members=None):
        return [c for c in (members or C21) if self.start[c] <= Y * 100 + 1]


    @memo
    def w_gdp(self, Y, members=None):
        g = {c: self.gdp.get((c, Y - 2)) for c in self.univ(Y, members)}
        g = {c: v for c, v in g.items() if v}
        t = sum(g.values())
        return {c: v / t for c, v in g.items()} if g else None

    @memo
    def w_cap(self, Y, members=None):
        k = {c: self.cap[c].get(Y - 1) for c in self.univ(Y, members)}
        k = {c: v[0] for c, v in k.items() if v}
        t = sum(k.values())
        return {c: v / t for c, v in k.items()} if k else None

    @memo
    def w_ew(self, Y, members=None):
        u = self.univ(Y, members)
        return {c: 1 / len(u) for c in u}

    @memo
    def d1(self, Y, members=None):
        w = self.w_cap(Y, members)
        return max(w, key=w.get) if w else None

    @memo
    def trail20(self, c, Y):
        """年 Y−20〜Y−1 のドル建ての累積（French の月次が 240 か月そろえば French、無ければ JST の年次）。無ければ None"""
        ms = months((Y - 20) * 100 + 1, (Y - 1) * 100 + 12)
        assert ms[-1] < Y * 100 + 1
        u = self.F[c]['usd']
        if all(m in u for m in ms):
            return math.prod(1 + u[m] for m in ms), 'french'
        if c in C16 and Y - 1 <= 2020:
            w = 1.0
            for y in range(Y - 20, Y):
                r = self.J.r_usd(c, y)
                if r is None:
                    return None
                w *= 1 + r
            return w, 'jst'
        return None

    @memo
    def d2(self, Y, members=None, thr=MAJOR_W, detail=False):
        w = self.w_cap(Y, members)
        if not w:
            return None
        sc = {}
        for c, v in w.items():
            if v >= thr:
                t = self.trail20(c, Y)
                if t:
                    sc[c] = t
        if not sc:
            return None
        best = max(sc, key=lambda c: (sc[c][0], c))
        return (best, sc[best][1], len(sc)) if detail else best


def fr_weights(Fo, name, Y, h=None, members=None):
    if name == 'D1':
        c = Fo.d1(Y, members); return {c: 1.0} if c else None
    if name == 'D2':
        c = Fo.d2(Y, members, MAJOR_W if members is None else MAJOR_R); return {c: 1.0} if c else None
    if name == 'D3':
        return {'USA': 1.0}
    if name == 'D3R':   # 地域の再現: 1976 年の最大の国をずっと持つ
        c = Fo.d1(1976, members); return {c: 1.0} if c else None
    if name in ('W2', 'Wb'):
        return Fo.w_cap(Y, members)
    if name == 'W1':
        return Fo.w_gdp(Y, members)
    if name == 'W3':
        return Fo.w_ew(Y, members)
    if name == 'H':
        return {h: 1.0} if Fo.start[h] <= Y * 100 + 1 else None
    if name == 'H50':
        b = Fo.w_cap(Y)
        if not b or Fo.start[h] > Y * 100 + 1:
            return None
        w = {c: 0.5 * v for c, v in b.items()}
        w[h] = w.get(h, 0) + 0.5
        return w
    raise ValueError(name)


def fund_monthly(wfun, rets, y0=1976, y1=2025, rebal_month=1, renorm=False):
    """年に一度（rebal_month）目標へ戻し、年の中は漂わせる（買って持つ）。→ (月次リターン, {年: 回転}, {年: 目標の重み}, 事象)
    renorm=True（第2の事前登録の新興国）: 欠けた月は残りの国で割り直し（有効な重み 85% 未満ならその月は空欄）、欠けた国は動かさない"""
    out, turn, wts, ev = {}, {}, {}, {'blank_years': 0, 'missing_month': 0, 'renorm_months': 0, 'blank_months': 0}
    prev_h = None
    for Y in range(y0, y1 + 1):
        w = wfun(Y)
        start = Y * 100 + rebal_month
        ms = months(start, ym_add(start, 11))
        if not w:
            prev_h = None; ev['blank_years'] += 1
            continue
        if prev_h is not None:
            tot = sum(prev_h.values())
            drift = {c: v / tot for c, v in prev_h.items()}
            turn[Y] = 0.5 * sum(abs(w.get(c, 0) - drift.get(c, 0)) for c in set(w) | set(drift))
        else:
            turn[Y] = 0.0
        wts[Y] = w
        h = dict(w)
        ok = True
        for m in ms:
            vals = {c: rets[c].get(m) for c in h}
            if renorm and any(v is None for v in vals.values()) and m <= min(max(rets[c]) for c in h):
                tot = sum(h.values())
                vs = sum(h[c] for c in h if vals[c] is not None)
                if vs / tot < RENORM_MIN:
                    ev['blank_months'] += 1
                    continue
                ev['renorm_months'] += 1
                out[m] = sum(h[c] * vals[c] for c in h if vals[c] is not None) / vs
                for c in h:
                    if vals[c] is not None:
                        h[c] *= 1 + vals[c]
                continue
            if any(v is None for v in vals.values()):
                if all(rets[c].get(m) is None for c in h) and m > max(max(rets[c]) for c in h):
                    ok = False; break          # データの終わり
                ev['missing_month'] += 1
                ok = False; break
            tot = sum(h.values())
            out[m] = sum(h[c] * vals[c] for c in h) / tot
            for c in h:
                h[c] *= 1 + vals[c]
        prev_h = h if ok else None
    return out, turn, wts, ev


def net_monthly(r, turn, wts, multi, foreign_of, fee=FEE_GAP, rebal_month=1, tc=TC):
    """月次の費用後: 毎月 (fee×複数国 + WHT×自国外の重み)/12、目標へ戻す月に TC×回転"""
    out = {}
    for m, v in r.items():
        Y = m // 100 if m % 100 >= rebal_month else m // 100 - 1
        w = wts.get(Y)
        if w is None:
            continue
        d = (fee * multi + WHT * foreign_of(w)) / 12
        if m % 100 == rebal_month:
            d += tc * turn.get(Y, 0.0)
        out[m] = v - d
    return out


def to_home(r_usd, fx):
    return {m: (1 + v) / (1 + fx[m]) - 1 for m, v in r_usd.items() if m in fx}


# ───────────────────────── 分布・判定 ─────────────────────────
def pct(v, q):
    if not v:
        return None
    v = sorted(v)
    i = (len(v) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 4)


def dist(R):
    """R = W/D（分けた側 ÷ 既定）の並び → 後悔の分布（D/W も出す）"""
    if not R:
        return None
    inv = [1 / x for x in R]
    return {'n': len(R), 'W_over_D': {f'p{int(q*100):02d}': pct(R, q) for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)},
            'P_W_gt_D': round(sum(1 for x in R if x > 1) / len(R), 3),
            'P_D_over_W_lt_0.7': round(sum(1 for x in inv if x < 0.7) / len(R), 3),
            'P_D_over_W_lt_0.5': round(sum(1 for x in inv if x < 0.5) / len(R), 3),
            'P_W_over_D_lt_0.7': round(sum(1 for x in R if x < 0.7) / len(R), 3),
            'min': round(min(R), 3), 'max': round(max(R), 3)}


def decide(rows, min_windows=5, cut=1945):
    """rows = [(home, start, R)]。事前登録の判定: 各バケツ（≤cut / >cut）で中央 R>1 の自国が 2/3 以上 ∧ 全体の 10% 点 R>1"""
    res = {}
    for bk, f in (('A_le1945', lambda s: s <= cut), ('B_ge1946', lambda s: s > cut)):
        per = {}
        for h, s, R in rows:
            if f(s):
                per.setdefault(h, []).append(R)
        med = {h: round(S.median(v), 4) for h, v in per.items() if len(v) >= min_windows}
        n = len(med)
        res[bk] = {'homes_counted': n, 'homes_median_gt1': sum(1 for v in med.values() if v > 1),
                   'homes_median_lt1': sum(1 for v in med.values() if v < 1),
                   'share_gt1': round(sum(1 for v in med.values() if v > 1) / n, 3) if n else None,
                   'share_lt1': round(sum(1 for v in med.values() if v < 1) / n, 3) if n else None,
                   'median_by_home': med, 'dist': dist([R for h, s, R in rows if f(s)])}
    allR = [R for _, _, R in rows]
    p10, p90 = pct(allR, 0.10), pct(allR, 0.90)
    a = res['A_le1945']; b = res['B_ge1946']
    okA = a['share_gt1'] is not None and a['share_gt1'] >= 2 / 3
    okB = b['share_gt1'] is not None and b['share_gt1'] >= 2 / 3
    dA = a['share_lt1'] is not None and a['share_lt1'] >= 2 / 3
    dB = b['share_lt1'] is not None and b['share_lt1'] >= 2 / 3
    res['pooled'] = dist(allR)
    res['verdict'] = {'a_bucketA_W_median_gt1_2of3': okA, 'b_bucketB_W_median_gt1_2of3': okB, 'c_pooled_p10_gt1': bool(p10 and p10 > 1),
                      'W_beats_D_robust': bool(okA and okB and p10 and p10 > 1), 'W_tends_to_beat_D': bool(okA and okB),
                      'D_beats_W': bool(dA and dB and p90 and p90 < 1)}
    return res


def episodes(starts, L):
    """重ならない窓の数（独立な試行の上限の目安）"""
    s = sorted(set(starts))
    n, last = 0, None
    for x in s:
        if last is None or x >= last + L:
            n += 1; last = x
    return n


# ───────────────────────── 部品: 点検 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-n', '1', '--format=%H', '--', path], cwd=M.BASE).decode().strip() or None
    except Exception:
        return None


def check():
    wb_gdp = wb('NY.GDP.MKTP.CD', 'wb_gdp_all.json')
    wb_cap = wb('CM.MKT.LCAP.CD', 'wb_mktcap_all.json', '1970:2025')
    wb_cpi = wb('FP.CPI.TOTL', 'wb_cpi_all.json')
    J = JST(load_jst(), wb_gdp, wb_cap)
    log('JST gdp の単位', {c: J.unit[c]['pow10'] for c in C16})
    log('JST 最初の株の年', J.first)
    for c in C16:
        if J.cap_rej[c]:
            log('JST caps 棄却', c, J.cap_rej[c])
    F, ff = load_french()
    Fo = FR(F, J, wb_gdp, wb_cap, wb_cpi)
    log('French 始まり', Fo.start)
    for c in C21:
        if Fo.cap_rej[c]:
            log('French caps 棄却', c, Fo.cap_rej[c])
    prev = None
    for Y in range(1871, 2021):
        d1 = J.d1(Y); d2 = J.d2(Y, detail=True)
        cur = (d1, d2[0] if d2 else None)
        if cur != prev:
            log('JST', Y, 'D1', d1, 'D2', d2)
            prev = cur
    prev = None
    for Y in range(1976, 2026):
        cur = (Fo.d1(Y), Fo.d2(Y, detail=True))
        if cur != prev:
            log('FR', Y, 'D1', cur[0], 'D2', cur[1], 'univ', len(Fo.univ(Y)))
            prev = cur
    for Y in (1976, 1990, 2000, 2025):
        w = Fo.w_cap(Y)
        imp = sum(v for c, v in w.items() if Fo.cap[c][Y - 1][1] == 'carry')
        log('FR W2', Y, {c: round(v, 3) for c, v in sorted(w.items(), key=lambda x: -x[1])[:5]}, 'carry share', round(imp, 3))
        log('FR W1', Y, {c: round(v, 3) for c, v in sorted(Fo.w_gdp(Y).items(), key=lambda x: -x[1])[:5]})
    for Y in (1900, 1950, 1980, 2019):
        log('JST Wb', Y, {c: round(v, 3) for c, v in sorted(J.w_bench(Y).items(), key=lambda x: -x[1])[:5]})
    log('CPI 範囲', {c: (min(y for (cc, y) in wb_cpi if cc == c), max(y for (cc, y) in wb_cpi if cc == c)) for c in C21})


# ───────────────────────── 本体 ─────────────────────────
def main():
    t0 = time.time()
    wb_gdp = wb('NY.GDP.MKTP.CD', 'wb_gdp_all.json')
    wb_cap = wb('CM.MKT.LCAP.CD', 'wb_mktcap_all.json', '1970:2025')
    wb_cpi = wb('FP.CPI.TOTL', 'wb_cpi_all.json')
    J = JST(load_jst(), wb_gdp, wb_cap)
    F, ff = load_french()
    Fo = FR(F, J, wb_gdp, wb_cap, wb_cpi)
    out = {'angle': 'dominant_market', 'prereg': PREREG, 'prereg_commit': git_sha(PREREG), 'script_commit_at_run': git_sha('night/mw_dominant_market.py'),
           'criteria_file': 'out/mw_prereg.json'}
    tested = []

    # ═══════════ 第1部: JST（年次・16か国・自国通貨の実質の積立） ═══════════
    STR_J = ['D1', 'D2', 'D3', 'W1', 'W2', 'Wb', 'W3', 'H', 'H50']
    stats = {}
    yr = {}   # (name, h) → {Y: (r, rnet, foreign, turn)}
    for h in C16:
        for nm in STR_J:
            d = {}
            for Y in range(1871, 2021):
                x = jst_year(J, nm, Y, h, stats)
                if x is not None:
                    d[Y] = x
            yr[(nm, h)] = d
    log('JST 年次の系列', len(yr), '再正規化', stats, round(time.time() - t0, 1), 's')

    def jst_terminal(nm, h, s, L, net=True, flows=False):
        if flows and nm in ('D1', 'D2'):
            return jst_flows(J, nm, h, s, L)
        d = yr[(nm, h)]
        rs = []
        for Y in range(s, s + L):
            if Y not in d:
                return None
            rs.append(d[Y][1] if net else d[Y][0])
        return dca_annual(rs)

    PAIRS_J = [(D, W) for D in ('D1', 'D2', 'D3') for W in ('Wb', 'W1', 'W3')] + [('H', 'Wb'), ('D3', 'H'), ('D3', 'H50'), ('H50', 'Wb')]
    part1 = {}
    rows_primary = {}
    for D, W in PAIRS_J:
        for L in LS:
            for mode in ('net', 'gross', 'net_switch'):
                if mode == 'net_switch' and D not in ('D1', 'D2'):
                    continue
                rows = []
                for h in C16:
                    for s in range(1871, 2021 - L + 1):
                        tw = jst_terminal(W, h, s, L, net=(mode != 'gross'))
                        td = jst_terminal(D, h, s, L, net=(mode != 'gross'), flows=(mode == 'net' and D in ('D1', 'D2')))
                        if tw is None or td is None:
                            continue
                        rows.append((h, s, round(tw / td, 4)))
                key = f'{D}_vs_{W}_L{L}_{mode}'
                res = decide(rows)
                starts = [s for _, s, _ in rows]
                res['n_windows'] = len(rows)
                res['independent_windows_A'] = episodes([s for s in starts if s <= 1945], L)
                res['independent_windows_B'] = episodes([s for s in starts if s > 1945], L)
                # 終わりの年で分ける: 1926 年より前に終わる / 1926〜2006 / 2007 以降
                res['by_end'] = {'end_le1925': dist([R for h, s, R in rows if s + L - 1 <= 1925]),
                                 'end_1926_2006': dist([R for h, s, R in rows if 1926 <= s + L - 1 <= 2006]),
                                 'end_ge2007': dist([R for h, s, R in rows if s + L - 1 >= 2007])}
                # 自国の間の相関（同じ起点で並べた log R の平均の対の相関）
                byh = {}
                for h, s, R in rows:
                    byh.setdefault(h, {})[s] = math.log(R)
                cs = []
                hs = sorted(byh)
                for i in range(len(hs)):
                    for j in range(i + 1, len(hs)):
                        com = sorted(set(byh[hs[i]]) & set(byh[hs[j]]))
                        if len(com) >= 10:
                            cs.append(M.corr([byh[hs[i]][k] for k in com], [byh[hs[j]][k] for k in com]))
                res['cross_home_mean_corr_logR'] = round(S.mean(cs), 3) if cs else None
                part1[key] = res
                if mode == 'net' and W == 'Wb' and D in ('D1', 'D2', 'D3'):
                    rows_primary[key] = rows
                tested.append({'name': f'J_{key}', 'kind': 'regret_dca_jst', 'primary_decision': (W == 'Wb' and D in ('D1', 'D2', 'D3') and mode == 'net'),
                               'primary_cell': (W == 'Wb' and L == 20 and mode == 'net' and D in ('D1', 'D2', 'D3')), 'verdict': res['verdict']})
    out['part1_jst_regret'] = part1
    out['part1_rows_primary'] = {k: [[h, s, R] for h, s, R in v] for k, v in rows_primary.items() if k.endswith('_L20_net')}
    # 自国ごとの実質の倍率（参考・L=20・費用後）
    mult = {}
    for nm in ('D1', 'D2', 'D3', 'Wb', 'W3', 'H'):
        for h in C16:
            v = [jst_terminal(nm, h, s, 20, flows=(nm in ('D1', 'D2'))) for s in range(1871, 2002)]
            v = [x / 20 for x in v if x is not None]
            if v:
                mult[f'{nm}_{h}'] = {'n': len(v), 'median': round(S.median(v), 3), 'p10': pct(v, 0.1), 'min': round(min(v), 3)}
    out['part1_real_multiple_L20'] = mult
    # 選ばれた市場（信号）の記録
    out['part1_signals'] = {'D1': {Y: J.d1(Y) for Y in range(1871, 2021)}, 'D2': {Y: J.d2(Y, detail=True) for Y in range(1871, 2021)}}
    sw = [Y for Y in range(1872, 2021) if J.d2(Y) and J.d2(Y - 1) and J.d2(Y) != J.d2(Y - 1)]
    out['part1_D2_switches'] = sw
    # 記述: 米国の家計（実質ドル）の年次の差（格付けはしない: 2007〜2020 は 14 年しか無い）
    desc = {}
    for D, W in (('D3', 'Wb'), ('D3', 'W3'), ('D2', 'Wb'), ('D1', 'Wb')):
        a = {Y: v[0] for Y, v in yr[(W, 'USA')].items()}
        b = {Y: v[0] for Y, v in yr[(D, 'USA')].items()}
        desc[f'{W}_minus_{D}'] = {'full': M.excess_stats(a, b, per_year=1, lag=2), 'pre1926': M.excess_stats(a, b, None, 1925, per_year=1, lag=2),
                                  '1926_2006': M.excess_stats(a, b, 1926, 2006, per_year=1, lag=2),
                                  '2007_2020_cagr_diff': round((M.cagr(M.window(a, 2007), 1) - M.cagr(M.window(b, 2007), 1)) * 100, 2)}
    out['part1_usd_annual_desc'] = desc
    log('第1部 済', round(time.time() - t0, 1), 's')

    # ═══════════ 第2部: French（月次・21か国・自国通貨の積立） ═══════════
    R = {c: F[c]['usd'] for c in C21}
    fundF = {}
    for nm in ('D1', 'D2', 'D3', 'W1', 'W2', 'W3'):
        fundF[nm] = fund_monthly(lambda Y, nm=nm: fr_weights(Fo, nm, Y), R)
    for h in C21:
        fundF[('H', h)] = fund_monthly(lambda Y, h=h: fr_weights(Fo, 'H', Y, h), R)
        fundF[('H50', h)] = fund_monthly(lambda Y, h=h: fr_weights(Fo, 'H50', Y, h), R)
    log('French の器', {k if isinstance(k, str) else '_'.join(k): (len(v[0]), v[3]) for k, v in fundF.items() if isinstance(k, str)})

    def cpi_idx(h, Y):
        return wb_cpi.get((h, Y))

    def home_series(nm, h, net=True):
        f = fundF[nm] if nm in fundF else fundF[(nm, h)]
        r, turn, wts, _ = f
        multi = nm in MULTI
        rr = net_monthly(r, turn, wts, multi, lambda w: sum(v for c, v in w.items() if c != h)) if net else r
        return to_home(rr, Fo.fxm[h])

    def fr_terminal(series, h, s, L):
        ms = months(s * 100 + 1, (s + L - 1) * 100 + 12)
        c0 = cpi_idx(h, s - 1)
        if c0 is None:
            return None
        w = 0.0
        for m in ms:
            if m not in series:
                return None
            ci = cpi_idx(h, m // 100 - 1)
            if ci is None:
                return None
            w = (w + ci / c0) * (1 + series[m])
        return w

    def fr_flows(nm, h, s, L):
        ms = months(s * 100 + 1, (s + L - 1) * 100 + 12)
        c0 = cpi_idx(h, s - 1)
        if c0 is None:
            return None
        hold = {}
        fx = Fo.fxm[h]
        for m in ms:
            Y = m // 100
            d = fr_weights(Fo, nm, Y)
            ci = cpi_idx(h, Y - 1)
            if not d or ci is None or m not in fx:
                return None
            c = next(iter(d))
            hold[c] = hold.get(c, 0.0) + ci / c0
            for j in list(hold):
                r = R[j].get(m)
                if r is None:
                    return None
                hold[j] *= (1 + r) / (1 + fx[m]) - (WHT / 12 if j != h else 0.0)
        return sum(hold.values())

    homeS = {}
    for h in C21:
        for nm in ('D1', 'D2', 'D3', 'W1', 'W2', 'W3', 'H', 'H50'):
            homeS[(nm, h, 'net')] = home_series(nm, h, True)
            homeS[(nm, h, 'gross')] = home_series(nm, h, False)
    part2 = {}
    rows2_primary = {}
    PAIRS_F = [(D, W) for D in ('D1', 'D2', 'D3') for W in ('W2', 'W1', 'W3')] + [('H', 'W2'), ('D3', 'H'), ('D3', 'H50'), ('H50', 'W2')]
    for D, W in PAIRS_F:
        for L in LS:
            for mode in ('net', 'gross', 'net_switch'):
                if mode == 'net_switch' and D not in ('D1', 'D2'):
                    continue
                rows = []
                for h in C21:
                    for s in range(1976, 2025 - L + 2):
                        if Fo.start[h] > s * 100 + 1:
                            continue
                        tw = fr_terminal(homeS[(W, h, 'gross' if mode == 'gross' else 'net')], h, s, L)
                        if mode == 'net' and D in ('D1', 'D2'):
                            td = fr_flows(D, h, s, L)
                        else:
                            td = fr_terminal(homeS[(D, h, 'gross' if mode == 'gross' else 'net')], h, s, L)
                        if tw is None or td is None:
                            continue
                        rows.append((h, s, round(tw / td, 4)))
                key = f'{D}_vs_{W}_L{L}_{mode}'
                allR = [x for _, _, x in rows]
                per = {}
                for h, s, x in rows:
                    per.setdefault(h, []).append(x)
                med = {h: round(S.median(v), 4) for h, v in per.items() if len(v) >= 5}
                res = {'n_windows': len(rows), 'independent_windows': episodes([s for _, s, _ in rows], L), 'pooled': dist(allR),
                       'median_by_home': med, 'share_homes_median_gt1': round(sum(1 for v in med.values() if v > 1) / len(med), 3) if med else None,
                       'by_end': {'end_le2006': dist([x for h, s, x in rows if s + L - 1 <= 2006]), 'end_ge2007': dist([x for h, s, x in rows if s + L - 1 >= 2007])}}
                p10 = pct(allR, 0.1)
                res['verdict_secondary'] = {'W_median_gt1_2of3_homes': bool(res['share_homes_median_gt1'] is not None and res['share_homes_median_gt1'] >= 2 / 3),
                                            'pooled_p10_gt1': bool(p10 and p10 > 1)}
                part2[key] = res
                if mode == 'net' and W == 'W2' and D in ('D1', 'D2', 'D3') and L == 20:
                    rows2_primary[key] = rows
                tested.append({'name': f'F_{key}', 'kind': 'regret_dca_french', 'primary_decision': False, 'verdict': res['verdict_secondary']})
    out['part2_french_regret'] = part2
    out['part2_rows_primary'] = {k: [[h, s, x] for h, s, x in v] for k, v in rows2_primary.items()}
    out['part2_signals'] = {'D1': {Y: Fo.d1(Y) for Y in range(1976, 2026)}, 'D2': {Y: Fo.d2(Y, detail=True) for Y in range(1976, 2026)}}
    log('第2部 済', round(time.time() - t0, 1), 's')

    # ── 円の投資家（別に報告） ──
    jp = {}
    for L in LS:
        for s in range(1976, 2025 - L + 2):
            row = {}
            for nm in ('D1', 'D2', 'D3', 'W1', 'W2', 'W3', 'H', 'H50'):
                if nm in ('D1', 'D2'):
                    t = fr_flows(nm, 'JPN', s, L)
                else:
                    t = fr_terminal(homeS[(nm, 'JPN', 'net')], 'JPN', s, L)
                ce = wb_cpi.get(('JPN', s + L - 1))
                # 実質の倍率 = 最終額を最終年の物価で割り戻した値 ÷ 積み立てた実質の単位（12L）
                row[nm] = round(t * wb_cpi[('JPN', s - 1)] / ce / (12 * L), 3) if t and ce else None
            jp[f'L{L}_{s}'] = row
    out['jpy_investor_real_multiple_net'] = jp
    # 名目の倍率（brief の数字の照合用・費用前・毎月1円）
    jpn_nom = {}
    for s, e in ((1976, 1995), (1990, 2009), (2006, 2025)):
        ms = months(s * 100 + 1, e * 100 + 12)
        row = {}
        for nm in ('D3', 'H', 'W2'):
            ser = homeS[(nm, 'JPN', 'gross')]
            w = 0.0
            for m in ms:
                w = (w + 1) * (1 + ser[m])
            row[nm] = round(w / len(ms), 2)
        jpn_nom[f'{s}_{e}'] = row
    out['jpy_nominal_multiple_check'] = jpn_nom

    # ═══════════ 第3部: 格付け（ドル建て・月次・1976〜2025） ═══════════
    us = F['USA']['usd']
    w2 = fundF['W2'][0]

    def usd_net(nm, direction):
        r, turn, wts, _ = fundF[nm]
        if direction == 'A':      # 世界に分ける器 vs 米国: 器の上乗せ + 米国の外の源泉税
            return net_monthly(r, turn, wts, True, lambda w: sum(v for c, v in w.items() if c != 'USA'))
        if direction == 'B':      # 支配的な市場 vs 世界: 米国の外にいる分の源泉税 + 売買
            return net_monthly(r, turn, wts, False, lambda w: sum(v for c, v in w.items() if c != 'USA'))
        if direction == 'C':      # 時価でない重み vs 時価の世界: 器の上乗せ + 売買
            return net_monthly(r, turn, wts, True, lambda w: 0.0)
        raise ValueError(direction)

    GP = [('A_W1', 'W1', 'A', 'US'), ('A_W2', 'W2', 'A', 'US'), ('A_W3', 'W3', 'A', 'US'),
          ('B_D1', 'D1', 'B', 'W2'), ('B_D2', 'D2', 'B', 'W2'), ('B_D3', 'D3', 'B', 'W2'),
          ('C_W1', 'W1', 'C', 'W2'), ('C_W3', 'W3', 'C', 'W2')]
    # 地域の再現
    reg = {}
    for R_, mem in (('EUR', EUR), ('APAC', APAC)):
        for nm in ('D1', 'D2', 'D3R', 'W1', 'W2', 'W3'):
            reg[(R_, nm)] = fund_monthly(lambda Y, nm=nm, mem=mem: fr_weights(Fo, nm, Y, members=mem), R)[0]
    REPL = {'A_W1': ('W1', 'D1'), 'A_W2': ('W2', 'D1'), 'A_W3': ('W3', 'D1'), 'B_D1': ('D1', 'W2'), 'B_D2': ('D2', 'W2'),
            'B_D3': ('D3R', 'W2'), 'C_W1': ('W1', 'W2'), 'C_W3': ('W3', 'W2')}
    graded = {}
    for gid, nm, dirn, bn in GP:
        s = fundF[nm][0]
        b = us if bn == 'US' else w2
        sn = usd_net(nm, dirn)
        ks = [k for k in s if k in b]
        s = {k: s[k] for k in ks}
        sn = {k: sn[k] for k in ks if k in sn}
        e = {'id': gid, 'strategy': nm, 'direction': dirn, 'benchmark': 'French Mkt（米国・上限なし時価加重）' if bn == 'US' else 'W2（21か国の時価加重・世界銀行の時価）',
             'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, None, M.TRAIN_END), 'hold': M.excess_stats(s, b, M.HOLD_START),
             'recent': M.excess_stats(s, b, M.RECENT_START), 'hold_net': M.excess_stats(sn, b, M.HOLD_START), 'full_net': M.excess_stats(sn, b),
             'roll20': M.rolling(s, b, 20), 'roll20_net': M.rolling(sn, b, 20), 'dca20': M.dca(s, b, 20), 'dca20_net': M.dca(sn, b, 20),
             'mdd_s': round(M.maxdd(s) * 100, 1), 'mdd_b': round(M.maxdd({k: b[k] for k in ks}) * 100, 1),
             'avg_turnover_oneway_per_year': round(S.mean(fundF[nm][1].values()), 3) if fundF[nm][1] else None}
        units = {}
        a_, b_ = REPL[gid]
        for R_ in ('EUR', 'APAC'):
            x, y = reg[(R_, a_)], reg[(R_, b_)]
            st = M.excess_stats(x, y)
            units[R_] = {'strategy': a_, 'bench': b_, 'full_ex_ann': st and st['ex_ann'], 'full_t': st and st['t'],
                         'hold_ex_ann': (M.excess_stats(x, y, M.HOLD_START) or {}).get('ex_ann')}
        e['repl'] = {'regions': len(units), 'positive': sum(1 for v in units.values() if v['full_ex_ann'] is not None and v['full_ex_ann'] > 0), 'units': units}
        graded[gid] = e
    hp = {g: (e['hold']['p'] if e['hold'] and (e['hold']['t'] or 0) > 0 else 1.0) for g, e in graded.items()}
    hh = M.holm(hp)
    for g, e in graded.items():
        e['family'] = 'GP'
        e['holm_p_hold'] = hh.get(g)
        gr, cr = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['hold_net'], repl=e['repl'], family_holm_p=hh.get(g))
        e['grade'], e['criteria'] = gr, cr
        tested.append({'name': g, 'kind': 'graded_usd_monthly', 'family': 'GP', 'primary': True, 'grade': gr})
    out['part3_graded_GP'] = graded
    out['part3_regional_series_note'] = '地域の再現: EUR 14か国 / APAC 5か国。A は地域の最大の国（D1）に対して、B・C は地域の時価加重（W2）に対して。正 = 1976〜2025 の超過の算術平均 > 0'
    log('第3部 GP 済', {g: (e['grade'], e['hold'] and e['hold']['ex_ann'], e['train'] and e['train']['t']) for g, e in graded.items()})

    # ── T: 業種の傾け（米国・French 49/12 業種・7月に年1回） ──
    mkt = ff['mkt']
    Tg = {}
    for tid, n_ind, N, major in (('T1_49_20', 49, 20, False), ('T1_12_20', 12, 20, False), ('T1_49_10', 49, 10, False), ('T1M_49_20', 49, 20, True)):
        ind = M.french_series(f'{n_ind}_Industry_Portfolios', 'Average Value Weighted Returns -- Monthly')
        size = None
        if major:
            tb = M.french_tables(f'{n_ind}_Industry_Portfolios')
            nf = next(v for k, v in tb.items() if k.startswith('Number of Firms') and v['freq'] == 'monthly')
            az = next(v for k, v in tb.items() if k.startswith('Average Firm Size') and v['freq'] == 'monthly')
            size = (nf, az)
        rets = dict(ind)
        rets['MKT'] = mkt
        picks = {}

        def wT(Y, ind=ind, N=N, size=size, picks=picks):
            ms = months((Y - N) * 100 + 7, Y * 100 + 6)
            assert ms[-1] < Y * 100 + 7
            if ms[0] < 192607:
                return None
            sc = {}
            for c, r in ind.items():
                if all(m in r for m in ms):
                    if size:
                        nf, az = size
                        m6 = Y * 100 + 6
                        tot = sum((nf['data'][m6][i] or 0) * (az['data'][m6][i] or 0) for i in range(len(nf['cols'])))
                        i = nf['cols'].index(c)
                        n_, a_ = nf['data'][m6][i], az['data'][m6][i]
                        if n_ is None or a_ is None or tot <= 0 or n_ * a_ / tot < T_MAJOR:
                            continue
                    sc[c] = math.fsum(math.log1p(r[m]) for m in ms)
            if len(sc) < 2:
                return None
            top = sorted(sc, key=lambda c: (-sc[c], c))[:2]
            picks[Y] = top
            return {top[0]: 0.4, top[1]: 0.4, 'MKT': 0.2}
        r, turn, wts, ev = fund_monthly(wT, rets, y0=1936, y1=2026, rebal_month=7)
        r = {k: v for k, v in r.items() if k <= max(mkt)}
        rn = net_monthly(r, turn, wts, True, lambda w: 0.0, fee=0.0008, rebal_month=7)
        ks = [k for k in r if k in mkt]
        e = {'id': tid, 'industries': n_ind, 'trail_years': N, 'major_only': major, 'from': min(ks), 'to': max(ks),
             'full': M.excess_stats(r, mkt), 'train': M.excess_stats(r, mkt, None, M.TRAIN_END), 'hold': M.excess_stats(r, mkt, M.HOLD_START),
             'recent': M.excess_stats(r, mkt, M.RECENT_START), 'hold_net': M.excess_stats(rn, mkt, M.HOLD_START), 'full_net': M.excess_stats(rn, mkt),
             'roll20': M.rolling(r, mkt, 20), 'dca20': M.dca(r, mkt, 20), 'dca20_net': M.dca(rn, mkt, 20),
             'avg_turnover_oneway_per_year': round(S.mean(turn.values()), 3) if turn else None,
             'picks_last10': {Y: picks[Y] for Y in sorted(picks)[-10:]}, 'picks_all': picks, 'events': ev, 'repl': None}
        Tg[tid] = e
    hp = {g: (e['hold']['p'] if e['hold'] and (e['hold']['t'] or 0) > 0 else 1.0) for g, e in Tg.items()}
    hh = M.holm(hp)
    for g, e in Tg.items():
        e['family'] = 'T'
        e['holm_p_hold'] = hh.get(g)
        gr, cr = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['hold_net'], repl=None, family_holm_p=hh.get(g))
        e['grade'], e['criteria'] = gr, cr
        tested.append({'name': g, 'kind': 'graded_usd_monthly', 'family': 'T', 'primary': g == 'T1_49_20', 'grade': gr})
    out['part3_graded_T'] = Tg
    log('第3部 T 済', {g: (e['grade'], e['hold'] and e['hold']['ex_ann']) for g, e in Tg.items()})

    # ═══════════ 第4部: 探索の族 E（out/mw_dominant_market_prereg2.json・米国外で支配的な国に寄せない重み） ═══════════
    out['prereg2'] = PREREG2
    out['prereg2_commit'] = git_sha(PREREG2)
    XUS = sorted(FRF)

    def wx_cap(Y):
        return Fo.w_cap(Y, XUS)

    def wx_sc(Y):
        w = wx_cap(Y)
        if not w:
            return None
        n = len(w) // 2
        small = sorted(w, key=lambda c: (w[c], c))[:n]
        return {c: 1 / n for c in small} if n else None

    def wx_ew(Y):
        w = wx_cap(Y)
        return {c: 1 / len(w) for c in w} if w else None

    def wx_gdp(Y):
        w = wx_cap(Y)
        if not w:
            return None
        g = {c: wb_gdp.get((c, Y - 2)) for c in w}
        g = {c: v for c, v in g.items() if v}
        t = sum(g.values())
        return {c: v / t for c, v in g.items()} if g else None
    bx = fund_monthly(wx_cap, R)[0]
    # 新興国（JKP・総に直す）
    rf = ff['rf']
    EMC = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
    em = {}
    for c in EMC:
        em[c.upper()] = {k: v + rf[k] for k, v in M.jkp_mkt(c, 'vw').items() if k in rf}
    em_b = {k: v + rf[k] for k, v in M.jkp_mkt('emerging', 'vw').items() if k in rf}
    em_start = {c: min(v) for c, v in em.items()}

    def em_univ(Y):
        return [c for c in em if em_start[c] <= Y * 100 + 1]

    def em_ew(Y):
        u = em_univ(Y)
        return {c: 1 / len(u) for c in u} if u else None

    def em_gdp(Y):
        g = {c: wb_gdp.get((c, Y - 2)) for c in em_univ(Y)}
        g = {c: v for c, v in g.items() if v}
        t = sum(g.values())
        return {c: v / t for c, v in g.items()} if g else None
    em_series = {'E2_EW_XUS': fund_monthly(em_ew, em, 1989, 2025, renorm=True), 'E3_GDP_XUS': fund_monthly(em_gdp, em, 1989, 2025, renorm=True)}
    Eg = {}
    for gid, wf in (('E1_SC_XUS', wx_sc), ('E2_EW_XUS', wx_ew), ('E3_GDP_XUS', wx_gdp)):
        r, turn, wts, ev = fund_monthly(wf, R)
        rn = net_monthly(r, turn, wts, True, lambda w: 0.0, fee=0.004, tc=0.0015)
        e = {'id': gid, 'benchmark': '米国外20か国の時価加重（世界銀行の時価・実時間の掃除）', 'events': ev,
             'full': M.excess_stats(r, bx), 'train': M.excess_stats(r, bx, None, M.TRAIN_END), 'hold': M.excess_stats(r, bx, M.HOLD_START),
             'recent': M.excess_stats(r, bx, M.RECENT_START), 'hold_net': M.excess_stats(rn, bx, M.HOLD_START), 'full_net': M.excess_stats(rn, bx),
             'roll20': M.rolling(r, bx, 20), 'roll20_net': M.rolling(rn, bx, 20), 'dca20': M.dca(r, bx, 20), 'dca20_net': M.dca(rn, bx, 20),
             'avg_turnover_oneway_per_year': round(S.mean(turn.values()), 3) if turn else None,
             'weights_sample': {Y: {c: round(v, 3) for c, v in sorted(wts[Y].items(), key=lambda x: -x[1])} for Y in (1976, 1990, 2007, 2025) if Y in wts}}
        if gid in em_series:
            x, _, _, evx = em_series[gid]
            st = M.excess_stats(x, em_b)
            e['repl'] = {'regions': 1, 'positive': int(bool(st and st['ex_ann'] > 0)),
                         'units': {'EM': {'full_ex_ann': st and st['ex_ann'], 'full_t': st and st['t'],
                                          'train_ex_ann': (M.excess_stats(x, em_b, None, M.TRAIN_END) or {}).get('ex_ann'),
                                          'hold_ex_ann': (M.excess_stats(x, em_b, M.HOLD_START) or {}).get('ex_ann'), 'events': evx}}}
        else:
            e['repl'] = None
        Eg[gid] = e
    hp = {g: (e['hold']['p'] if e['hold'] and (e['hold']['t'] or 0) > 0 else 1.0) for g, e in Eg.items()}
    hh = M.holm(hp)
    for g, e in Eg.items():
        e['family'] = 'E（探索・prereg2）'
        e['holm_p_hold'] = hh.get(g)
        gr, cr = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['hold_net'], repl=e['repl'], family_holm_p=hh.get(g))
        e['grade'], e['criteria'] = gr, cr
        tested.append({'name': g, 'kind': 'graded_usd_monthly', 'family': 'E', 'primary': False, 'exploratory': True, 'grade': gr})
    out['part4_graded_E'] = Eg
    # 点検: 米国外の時価加重 vs JKP developed（米国外）・French Ind_all
    try:
        jdev = {k: v + rf[k] for k, v in M.jkp_mkt('developed', 'vw').items() if k in rf}
        zi = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Indices.zip',
                                              name='fr_F-F_International_Indices.zip')))
        a = parse_fr_dat(zi.read('Ind_all.Dat').decode('latin-1'))
        sec = a[('USD', 'NR', 'm')]
        ind_all = {k: v[sec['cols'].index('Mkt')] / 100 for k, v in sec['data'].items() if v[sec['cols'].index('Mkt')] is not None}
        com = sorted(set(bx) & set(jdev))
        com2 = sorted(set(bx) & set(ind_all))
        out['part4_sanity'] = {'bench_xus_vs_jkp_developed': M.excess_stats(bx, jdev), 'corr_jkp_developed': round(M.corr([bx[k] for k in com], [jdev[k] for k in com]), 4),
                               'bench_xus_vs_french_ind_all': M.excess_stats(bx, ind_all), 'corr_french_ind_all': round(M.corr([bx[k] for k in com2], [ind_all[k] for k in com2]), 4)}
    except Exception as ex:  # noqa
        out['part4_sanity'] = f'失敗: {ex}'
    log('第4部 E 済', {g: (e['grade'], e['train'] and (e['train']['ex_ann'], e['train']['t']), e['hold'] and (e['hold']['ex_ann'], e['hold']['t'])) for g, e in Eg.items()})

    # ═══════════ 第5部: 探索の族 F（out/mw_dominant_market_prereg3.json・小さい国の頑丈さ） ═══════════
    out['prereg3'] = PREREG3
    out['prereg3_commit'] = git_sha(PREREG3)
    DEV22 = 'jpn gbr deu fra che nld swe dnk nor fin bel aut ita esp irl prt can aus nzl hkg sgp isr'.split()
    jk = {}
    for c in DEV22 + ['grc']:
        jk[c.upper()] = {k: v + rf[k] for k, v in M.jkp_mkt(c, 'vw').items() if k in rf}
    for c, v in em.items():
        jk.setdefault(c, v)
    jstart = {c: min(v) for c, v in jk.items()}

    def ann_growth(ser):
        a = {}
        for Y in range(1970, 2027):
            ms = [Y * 100 + m for m in range(1, 13)]
            if all(m in ser for m in ms):
                a[Y] = math.prod(1 + ser[m] for m in ms)
        return a
    capJ = {}
    for c, ser in jk.items():
        a = ann_growth(ser)
        g = (lambda x, y, a=a: math.prod(a[t] for t in range(x + 1, y + 1)) if all(t in a for t in range(x + 1, y + 1)) else None)
        obs = {Y: v for (cc, Y), v in wb_cap.items() if cc == c}
        capJ[c] = clean_caps(obs, g, 1975, 2025)

    def sc_pair(univ_fn, cap_est):
        """(小さい半分の等分, 同じ宇宙の時価加重) の重みの関数の組"""
        def both(Y):
            k = {c: cap_est[c].get(Y - 1) for c in univ_fn(Y) if c in cap_est}
            k = {c: v[0] for c, v in k.items() if v}
            if len(k) < 2:
                return None, None
            t = sum(k.values())
            n = len(k) // 2
            small = sorted(k, key=lambda c: (k[c], c))[:n]
            return {c: 1 / n for c in small}, {c: v / t for c, v in k.items()}
        return (lambda Y: both(Y)[0]), (lambda Y: both(Y)[1])
    capJe = {c: v[0] for c, v in capJ.items()}
    u_f1 = lambda Y: [c.upper() for c in DEV22 if jstart[c.upper()] <= Y * 100 + 1]
    u_f1b = lambda Y: u_f1(Y) + (['GRC'] if 2002 <= Y <= 2013 and jstart['GRC'] <= Y * 100 + 1 else [])
    u_f3 = lambda Y: [c for c in em if em_start[c] <= Y * 100 + 1]
    runs = {}
    for fid, uf, y0, y1 in (('F1_SC_JKPDEV', u_f1, 1987, 2025), ('F1b_SC_JKPDEV_GRC', u_f1b, 1987, 2025), ('F3_SC_EM', u_f3, 2001, 2025)):
        sf, bf = sc_pair(uf, capJe)
        rs = fund_monthly(sf, jk, y0, y1, renorm=True)
        rb = fund_monthly(bf, jk, y0, y1, renorm=True)
        runs[fid] = (rs, rb)
    f3s, f3b = runs['F3_SC_EM'][0][0], runs['F3_SC_EM'][1][0]
    f3 = {'full': M.excess_stats(f3s, f3b), 'hold': M.excess_stats(f3s, f3b, M.HOLD_START), 'first': min(f3s), 'last': max(f3s),
          'events': runs['F3_SC_EM'][0][3], 'n_countries_2001': len(u_f3(2001)), 'with_caps_2001': sum(1 for c in u_f3(2001) if capJe[c].get(2000))}
    Fg = {}
    for fid in ('F1_SC_JKPDEV', 'F1b_SC_JKPDEV_GRC'):
        (r, turn, wts, ev), (b, _, _, _) = runs[fid]
        rn = net_monthly(r, turn, wts, True, lambda w: 0.0, fee=0.004, tc=0.0015)
        e = {'id': fid, 'benchmark': '同じ宇宙の時価加重（世界銀行の時価・実時間の掃除・JKP の総リターンで運ぶ）', 'events': ev,
             'full': M.excess_stats(r, b), 'train': M.excess_stats(r, b, None, M.TRAIN_END), 'hold': M.excess_stats(r, b, M.HOLD_START),
             'recent': M.excess_stats(r, b, M.RECENT_START), 'hold_net': M.excess_stats(rn, b, M.HOLD_START), 'full_net': M.excess_stats(rn, b),
             'roll20': M.rolling(r, b, 20), 'roll20_net': M.rolling(rn, b, 20), 'dca20': M.dca(r, b, 20), 'dca20_net': M.dca(rn, b, 20),
             'avg_turnover_oneway_per_year': round(S.mean(turn.values()), 3) if turn else None,
             'weights_sample': {Y: sorted(wts[Y]) for Y in (1987, 2000, 2007, 2012, 2025) if Y in wts},
             'repl': {'regions': 1, 'positive': int(bool(f3['full'] and f3['full']['ex_ann'] > 0)), 'units': {'EM_F3': f3}}}
        Fg[fid] = e
    hp = {g: (e['hold']['p'] if e['hold'] and (e['hold']['t'] or 0) > 0 else 1.0) for g, e in Fg.items()}
    hh = M.holm(hp)
    for g, e in Fg.items():
        e['family'] = 'F（探索・prereg3）'
        e['holm_p_hold'] = hh.get(g)
        gr, cr = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['hold_net'], repl=e['repl'], family_holm_p=hh.get(g))
        e['grade'], e['criteria'] = gr, cr
        tested.append({'name': g, 'kind': 'graded_usd_monthly', 'family': 'F', 'primary': False, 'exploratory': True, 'grade': gr})
    out['part5_graded_F'] = Fg
    out['part5_F3_em'] = f3
    tested.append({'name': 'F3_SC_EM', 'kind': 'replication_report', 'family': 'F', 'grade': None,
                   'full_ex_ann': f3['full'] and f3['full']['ex_ann']})

    # F2: JST（年次・米国外15か国・米ドル未ヘッジ・GDP の大きさ）
    XUS15 = [c for c in C16 if c != 'USA']
    f2 = {'sc': {}, 'gdpw': {}, 'ew': {}}
    for Y in range(1872, 2021):
        if Y in U_WAR:
            continue
        u = [c for c in XUS15 if J.first[c] <= Y - 1]
        g = {c: J.gdp_usd(c, Y - 2) for c in u}
        g = {c: v for c, v in g.items() if v}
        if len(g) < 4:
            continue
        n = len(g) // 2
        small = sorted(g, key=lambda c: (g[c], c))[:n]
        tot = sum(g.values())
        for k, w in (('sc', {c: 1 / n for c in small}), ('gdpw', {c: v / tot for c, v in g.items()}), ('ew', {c: 1 / len(g) for c in g})):
            rr = {c: J.r_usd(c, Y) for c in w}
            vs = sum(v for c, v in w.items() if rr[c] is not None)
            if vs < RENORM_MIN:
                continue
            f2[k][Y] = sum(v * rr[c] for c, v in w.items() if rr[c] is not None) / vs

    def short(s_, b_, a, z):
        ks = sorted(k for k in set(s_) & set(b_) if a <= k <= z)
        if len(ks) < 6:
            return None
        ex = [s_[k] - b_[k] for k in ks]
        gs = math.exp(math.fsum(math.log1p(s_[k]) for k in ks) / len(ks)) - 1
        gb = math.exp(math.fsum(math.log1p(b_[k]) for k in ks) / len(ks)) - 1
        m = S.mean(ex); sd = S.stdev(ex)
        return {'from': ks[0], 'to': ks[-1], 'years': len(ks), 'ex_ann': round(m * 100, 2), 't_iid': round(m / sd * math.sqrt(len(ks)), 2) if sd else None,
                'cagr_diff': round((gs - gb) * 100, 2), 'win_years': sum(1 for x in ex if x > 0)}
    f2rep = {}
    for bn in ('gdpw', 'ew'):
        f2rep[f'sc_vs_{bn}'] = {f'{a}_{z}': short(f2['sc'], f2[bn], a, z) for a, z in ((1871, 1938), (1950, 2006), (2007, 2020), (1871, 2020))}
        f2rep[f'sc_vs_{bn}']['nw_full'] = M.excess_stats(f2['sc'], f2[bn], per_year=1, lag=2)
    a1, a2 = f2rep['sc_vs_gdpw']['1871_1938'], f2rep['sc_vs_gdpw']['1950_2006']
    f2rep['replicates_vs_gdpw'] = bool(a1 and a2 and a1['ex_ann'] > 0 and a2['ex_ann'] > 0)
    out['part5_F2_jst'] = f2rep
    tested.append({'name': 'F2_SC_JST_GDP', 'kind': 'replication_report', 'family': 'F', 'grade': None, 'replicates': f2rep['replicates_vs_gdpw']})

    # F4: 実在の国別 ETF（Yahoo・生き残りの偏りあり）
    ETFS = {'EWA': 'AUS', 'EWO': 'AUT', 'EWK': 'BEL', 'EWC': 'CAN', 'EWQ': 'FRA', 'EWG': 'DEU', 'EWH': 'HKG', 'EWI': 'ITA', 'EWJ': 'JPN',
            'EWN': 'NLD', 'EWS': 'SGP', 'EWP': 'ESP', 'EWD': 'SWE', 'EWL': 'CHE', 'EWU': 'GBR', 'ENZL': 'NZL', 'EIRL': 'IRL', 'ENOR': 'NOR',
            'EFNL': 'FIN', 'EDEN': 'DNK', 'EIS': 'ISR'}
    et, f4 = {}, {}
    try:
        for tk, c in ETFS.items():
            et[c] = M.yahoo(tk)
        efa = M.yahoo('EFA')
        capE = {c: (Fo.cap[c] if c in Fo.cap else capJe.get(c, {})) for c in et}
        etstart = {c: min(v) for c, v in et.items()}
        sf, bf = sc_pair(lambda Y: [c for c in et if etstart[c] <= Y * 100 + 1], capE)
        rs = fund_monthly(sf, et, 1997, 2026, renorm=True)
        rb = fund_monthly(bf, et, 1997, 2026, renorm=True)
        f4 = {'vs_same_etfs_capw': M.excess_stats(rs[0], rb[0]), 'vs_EFA': M.excess_stats(rs[0], efa),
              'hold_vs_same': M.excess_stats(rs[0], rb[0], M.HOLD_START), 'hold_vs_EFA': M.excess_stats(rs[0], efa, M.HOLD_START),
              'events': rs[3], 'first': min(rs[0]), 'last': max(rs[0]), 'avg_turnover': round(S.mean(rs[1].values()), 3) if rs[1] else None,
              'note': 'ETF の値動きに信託報酬が入っている（費用後に近い）。生き残った ETF だけ'}
    except Exception as ex:  # noqa
        f4 = {'error': str(ex)}
    out['part5_F4_etf'] = f4
    tested.append({'name': 'F4_SC_ETF', 'kind': 'reality_check_report', 'family': 'F', 'grade': None})

    # 事後（E1 を見た後に決めた診断・格付けしない）
    ph = {}
    e1r = fund_monthly(wx_sc, R)[0]
    ph['subperiods'] = {f'{a}_{z}': M.excess_stats(e1r, bx, a, z) for a, z in ((197601, 199012), (199101, 200612), (200701, 201512), (201601, 202512))}
    loo = {}
    for c in XUS:
        mem = [x for x in XUS if x != c]
        sf, bf = sc_pair(lambda Y, mem=mem: [x for x in mem if Fo.start[x] <= Y * 100 + 1], {x: Fo.cap[x] for x in mem})
        a_ = fund_monthly(sf, R)[0]
        b_ = fund_monthly(bf, R)[0]
        st, sh = M.excess_stats(a_, b_, None, M.TRAIN_END), M.excess_stats(a_, b_, M.HOLD_START)
        loo[c] = {'train_ex': st and st['ex_ann'], 'train_t': st and st['t'], 'hold_ex': sh and sh['ex_ann'], 'hold_t': sh and sh['t']}
    ph['leave_one_out'] = loo
    ph['leave_one_out_min'] = {'train': min((v['train_ex'], k) for k, v in loo.items()), 'hold': min((v['hold_ex'], k) for k, v in loo.items())}
    RL = {c: F[c]['loc'] for c in XUS}
    e1l, bxl = fund_monthly(wx_sc, RL)[0], fund_monthly(wx_cap, RL)[0]
    ph['local_currency'] = {'full': M.excess_stats(e1l, bxl), 'train': M.excess_stats(e1l, bxl, None, M.TRAIN_END), 'hold': M.excess_stats(e1l, bxl, M.HOLD_START),
                            'note': '同じ重みの規則を現地通貨のリターンで回した超過。米ドルの超過との差が為替の寄与の目安'}
    cnt = {}
    for Y in range(1976, 2026):
        w = wx_sc(Y)
        for c in w:
            cnt[c] = cnt.get(c, 0) + 1
    ph['years_held_by_country'] = dict(sorted(cnt.items(), key=lambda x: -x[1]))
    out['part5_posthoc_E1_not_graded'] = ph
    log('第5部 F 済', {g: (e['grade'], e['train'] and (e['train']['ex_ann'], e['train']['t']), e['hold'] and (e['hold']['ex_ann'], e['hold']['t'])) for g, e in Fg.items()},
        'F3', f3['full'] and f3['full']['ex_ann'], 'F2', f2rep['replicates_vs_gdpw'])

    # ═══════════ 点検 ═══════════
    san = {}
    san['us_mkt_cagr_1926_2026'] = round(M.cagr(mkt) * 100, 2)
    san['us_mkt_cagr_2007_on'] = round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)
    fa = {}
    for k, v in mkt.items():
        fa[k // 100] = fa.get(k // 100, 1.0) * (1 + v)
    ja = {Y: J.g('USA', Y, 'eq_tr') for Y in range(1927, 2021)}
    san['jst_usa_vs_french_cagr_1927_2020'] = {'jst': round(M.cagr(ja, 1) * 100, 2), 'french': round(M.cagr({Y: fa[Y] - 1 for Y in range(1927, 2021)}, 1) * 100, 2),
                                               'corr_annual': round(M.corr([ja[Y] for Y in range(1927, 2021)], [fa[Y] - 1 for Y in range(1927, 2021)]), 3)}
    # 円: 暗黙の為替 vs FRED
    try:
        c = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=3650).decode().strip().splitlines()
        last = {}
        for line in c[1:]:
            d, v = line.split(',')
            if v not in ('', '.'):
                last[int(d[:4]) * 100 + int(d[5:7])] = float(v)
        ks = sorted(last)
        fr_ = {k: last[p] / last[k] - 1 for p, k in zip(ks, ks[1:])}
        com = sorted(set(fr_) & set(Fo.fxm['JPN']) & set(range(M0, M1 + 1)))
        san['jpy_implied_vs_fred'] = {'n': len(com), 'corr': round(M.corr([fr_[k] for k in com], [Fo.fxm['JPN'][k] for k in com]), 4),
                                      'cagr_implied': round(M.cagr({k: Fo.fxm['JPN'][k] for k in com}) * 100, 3), 'cagr_fred': round(M.cagr({k: fr_[k] for k in com}) * 100, 3)}
    except Exception as ex:  # noqa
        san['jpy_implied_vs_fred'] = f'失敗: {ex}'
    # JKP の世界（上限なし時価加重・1986〜）と W2
    try:
        rf = ff['rf']
        jw = {k: v + rf[k] for k, v in M.jkp_mkt('world', 'vw').items() if k in rf}
        jd = {k: v + rf[k] for k, v in M.jkp_mkt('developed', 'vw').items() if k in rf}
        san['W2_vs_jkp_world_vw'] = M.excess_stats(w2, jw)
        san['W2_vs_jkp_developed_vw'] = M.excess_stats(w2, jd)
        com = sorted(set(w2) & set(jw))
        san['W2_jkp_world_corr'] = round(M.corr([w2[k] for k in com], [jw[k] for k in com]), 4)
    except Exception as ex:  # noqa
        san['W2_vs_jkp_world_vw'] = f'失敗: {ex}'
    san['jst_gdp_units'] = J.unit
    san['caps_rejected_jst'] = {c: v for c, v in J.cap_rej.items() if v}
    san['caps_rejected_french'] = {c: v for c, v in Fo.cap_rej.items() if v}
    san['W2_carry_share_by_year'] = {Y: round(sum(v for c, v in Fo.w_cap(Y).items() if Fo.cap[c][Y - 1][1] == 'carry'), 3) for Y in range(1976, 2026)}
    san['jst_renorm_events'] = stats
    san['french_fund_events'] = {k: v[3] for k, v in fundF.items() if isinstance(k, str)}
    out['sanity'] = san
    # ═══════════ まとめ（数字は上の結果から機械で拾う） ═══════════
    P1 = out['part1_jst_regret']
    summ = {'decision_primary_JST_L20_net': {}, 'decision_robustness': {}}
    for D in ('D1', 'D2', 'D3'):
        v = P1[f'{D}_vs_Wb_L20_net']
        summ['decision_primary_JST_L20_net'][D] = {'verdict': v['verdict'], 'W_over_D_p10_p50_p90': [v['pooled']['W_over_D'][q] for q in ('p10', 'p50', 'p90')],
                                                   'P_D_over_W_lt_0.7': v['pooled']['P_D_over_W_lt_0.7'], 'P_W_over_D_lt_0.7': v['pooled']['P_W_over_D_lt_0.7'],
                                                   'homes_W_median_gt1_A': f"{v['A_le1945']['homes_median_gt1']}/{v['A_le1945']['homes_counted']}",
                                                   'homes_W_median_gt1_B': f"{v['B_ge1946']['homes_median_gt1']}/{v['B_ge1946']['homes_counted']}",
                                                   'independent_windows_A_B': [v['independent_windows_A'], v['independent_windows_B']],
                                                   'cross_home_corr_logR': v['cross_home_mean_corr_logR']}
        summ['decision_robustness'][D] = {f'L{L}': P1[f'{D}_vs_Wb_L{L}_net']['verdict'] for L in LS}
    P2 = out['part2_french_regret']
    summ['french_1976_2025_L20_net'] = {D: {'share_homes_W_median_gt1': P2[f'{D}_vs_W2_L20_net']['share_homes_median_gt1'],
                                            'W_over_D_p10_p50_p90': [P2[f'{D}_vs_W2_L20_net']['pooled']['W_over_D'][q] for q in ('p10', 'p50', 'p90')],
                                            'P_D_over_W_lt_0.7': P2[f'{D}_vs_W2_L20_net']['pooled']['P_D_over_W_lt_0.7']} for D in ('D1', 'D2', 'D3')}
    allg = {}
    for fam in ('part3_graded_GP', 'part3_graded_T', 'part4_graded_E', 'part5_graded_F'):
        for g, e in out[fam].items():
            allg[g] = {'grade': e['grade'], 'train': e['train'] and [e['train']['ex_ann'], e['train']['t']], 'hold': e['hold'] and [e['hold']['ex_ann'], e['hold']['t']],
                       'hold_net': e['hold_net'] and e['hold_net']['ex_ann'], 'full_t': e['full'] and e['full']['t']}
    summ['graded'] = allg
    summ['grade_counts'] = {k: sum(1 for v in allg.values() if v['grade'] == k) for k in 'SABC'}
    out['summary'] = summ
    out['deviations'] = [
        '費用後（C6）は mw_common.apply_cost の一定の平均回転ではなく、毎年1月（業種は7月）の実際の回転×単価と、年率の器の上乗せ・源泉税を月割りで引いた（平均回転は avg_turnover_oneway_per_year に記録）',
        'French の国別のデータは 2025-12 で終わるので、月次の部（第2〜4部）の終わりは 2025-12（米国の French Mkt は 2026-08 まであるが揃えた）',
        'B（支配的な市場 vs 世界）の費用は戦略の側だけに掛け、相手の W2 には掛けない（戦略に厳しい側）',
        '他の角度の道具で見つけた問題（直していない・報告のみ）: (1) mw_deep_history の gdp_bench は JST の gdp の単位（十億・百万・兆）を直さずに gdp/xrusd を国の間で比べている＝その GDP 加重の報告（vs_gdp_weight・gdpw_vs_ew）の重みは誤り。(2) JKP の地域 developed は米国を含まない（米国外の先進国）。mw_common の注記はこれを書いていない（mw_country_verify は気づいている）',
        '実行時の mw_common.yahoo は別の作業者のコミット前の変更（取引所の時刻で月を切る・抜けた月をまたがない）を含んでいた（使ったのは第5部の F4 の ETF だけ）',
        'JST の D1（最大の市場）は 1975 年以前は GDP の代理（=米国）。1914年頃までの最大の株式市場はロンドンだったはずで、D に有利な後知恵を含む（事前登録どおり旗）',
        '世界銀行の時価総額の入力誤り（日本1977-78・英国1979-80・仏伊墺1998・ノルウェー1984・フィンランド1999〜・シンガポール1982-83・スウェーデン1977-78）は事前登録の実時間の規則で棄却・補った（sanity.caps_rejected_*）。フィンランドの 1999 年以降は約1/5 の水準が『新しい水準』として採られた（誤りの可能性が高いが規則どおり）'
    ]
    out['tested'] = tested
    out['n_tested'] = len(tested)
    out['log'] = LOG
    p = M.save(OUT, out)
    log('書いた', p, os.path.getsize(p), round(time.time() - t0, 1), 's')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if a.check:
        check()
    else:
        main()
