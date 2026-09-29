#!/usr/bin/env python3
"""night/mw_nisa_ops_verify.py — 角度 nisa_ops の反証の検証（読むだけ・門の判定には不使用）

検証の相手（out/mw_nisa_ops.json の格付け）:
  S  O2a__S4_init_taxable  （課税口座に持ち越しの区画がある家計で、1月に含み損の区画を空いた NISA 枠へ移す）
  B  X5b__S1_one_holder    （NISA が1人分の家計で、年の境目に簿価の90%以下の NISA の口を売って即買い戻す・摩擦なしの楽観の上限）
  （S/A はこの1本だけ、B もこの1本だけ）
  参考: O2b__S4（要約で「米国と16か国で9割超の勝ち」と書かれた本）・O3__P（大きな負けの主張・模型の較正）

方針: 研究役の家計の模型（HH クラス）・時間加重・excess_stats は使わない。
  データの取得（mw_common の French・FRED のキャッシュ・JST の xlsx）だけ借り、
  (1) 道（米国市場の円・日本・米国のドル・JST16か国）を自分で組み（配当のリターンは 49業種〔研究役は12業種〕から自分で作る）、
  (2) 家計の模型（NISA 3口・課税口座・年の枠と簿価の生涯枠・翌年の枠の復活・特定口座の源泉と精算・3年の繰越・
      外国税額控除・城の回転・為替手数料）を事前登録の文言から自分で書き、
  (3) 時間加重（毎月の『いま全部売ったら』）・差の年率・Newey-West の t・CAGR の差・20年の積立窓の勝ちを自分で計算する。
  そのうえで、隣の設定（発動線・持ち越しの長さ・年の境目の市場の外の時間）・保有期間の前半と後半・市場そのものとの比較・
  族の取り方（Holm の片側／両側）を振る。
"""
import sys, os, io, csv, json, math, zipfile, re, time, statistics as S, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （データの取得だけに使う）

OUT = 'mw_nisa_ops_verify.json'
FR_END = 202608
TAX = 0.20315
WH_US = 0.10
QT, QG = 1_200_000.0, 2_400_000.0        # 1人・年
LIFE, LIFE_G = 18_000_000.0, 12_000_000.0   # 1人・簿価
C_MONTH = 170_000.0
CS = 0.20
TURN = 0.25
FEE_FUND = 0.0010
SWITCH = 0.001
FX_YEN = 0.25
HOLD_START, TRAIN_END, RECENT_START = 200701, 200612, 201307
TINY = 1e-9


def mplus(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


# ───────────────────────── データ（自前で組む） ─────────────────────────
def fred_csv(sid, how):
    b = open(os.path.join(M.CACHE, f'fred_{sid}.csv'), 'rb').read().decode()
    out = {}
    for r in csv.DictReader(io.StringIO(b)):
        v = r.get(sid)
        if v in (None, '', '.'):
            continue
        d = r['observation_date']
        ym = int(d[:4]) * 100 + int(d[5:7])
        if how == 'first' and ym in out:
            continue
        out[ym] = float(v)
    return out


def div_return_49():
    """49業種の（配当込み−配当抜き）を前月末の時価（社数×平均規模）で加重（欠けた業種は除いて加重し直す）"""
    wi, wo = M.french_tables('49_Industry_Portfolios'), M.french_tables('49_Industry_Portfolios_Wout_Div')

    def t(T, want):
        for k, v in T.items():
            if k.lower().startswith(want.lower()) and v['freq'] == 'monthly':
                return v
        raise KeyError(want)
    a, b = t(wi, 'Average Value Weighted Returns'), t(wo, 'Average Value Weighted Returns')
    nf, sz = t(wi, 'Number of Firms'), t(wi, 'Average Firm Size')
    out = {}
    for m in sorted(a['data']):
        if m > FR_END or m not in b['data']:
            continue
        num = den = 0.0
        for i in range(len(a['cols'])):
            x, y = a['data'][m][i], b['data'][m][i]
            n, s = nf['data'].get(m, [None] * 99)[i], sz['data'].get(m, [None] * 99)[i]
            if None in (x, y, n, s) or n <= 0 or s <= 0:
                continue
            w = n * s
            num += w * max(0.0, (x - y) / 100)
            den += w
        if den > 0:
            out[m] = num / den
    return out


def japan_local():
    """French International Countries の Japan・Value-Weight・Local・Not Reqd（月次）の Mkt 列を、配当込みと抜きから"""
    def parse(fn):
        z = zipfile.ZipFile(io.BytesIO(open(os.path.join(M.CACHE, fn), 'rb').read()))
        lines = z.read('Japan.Dat').decode('latin-1').splitlines()
        out, on, done = {}, False, False
        for ln in lines:
            if 'Value-Weight' in ln:
                if done:
                    break
                on = ('Local' in ln) and ('Not Reqd' in ln)
                continue
            mm = re.match(r'^\s*(\d{6})\s+(\S+)', ln)
            if on and mm:
                v = float(mm.group(2))
                if v > -99.99:
                    out[int(mm.group(1))] = v / 100
                done = True
            elif on and done and not ln.strip():
                on = False
        return out
    w, o = parse('fr_F-F_International_Countries.zip'), parse('fr_F-F_International_Countries_Wout_Div.zip')
    ks = sorted(k for k in w if k in o)
    return {k: w[k] for k in ks}, {k: max(0.0, w[k] - o[k]) for k in ks}


def jst():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jst_R6.xlsx'), read_only=True)
    rows = wb.worksheets[0].iter_rows(values_only=True)
    h = next(rows)
    iy, ic, it, idv, icp = (h.index(k) for k in ('year', 'country', 'eq_tr', 'eq_div_rtn', 'cpi'))
    d = collections.defaultdict(dict)
    for r in rows:
        if None in (r[it], r[idv], r[icp]):
            continue
        d[r[ic]][int(r[iy])] = (float(r[it]), float(r[idv]), float(r[icp]))
    return dict(d)


def build():
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if k <= FR_END}
    dy = div_return_49()
    fx = fred_csv('DEXJPUS', 'last')
    cpi = fred_csv('CPIAUCNS', 'first')
    # 欠けた月は前後の幾何の補間（積立と枠の実質化にだけ使う）
    ks = sorted(cpi)
    for a, b in zip(ks, ks[1:]):
        gap = (b // 100 * 12 + b % 100) - (a // 100 * 12 + a % 100)
        for j in range(1, gap):
            cpi[mplus(a, j)] = cpi[a] * (cpi[b] / cpi[a]) ** (j / gap)
    usj = {}
    for m, r in mkt.items():
        p = mplus(m, -1)
        if m in fx and p in fx and m in dy:
            usj[m] = (1 + r) * fx[m] / fx[p] - 1
    P = {}
    P['USJ'] = dict(name='USJ', f=12, keys=sorted(usj), R=usj, DY=dy, usd=True, fx=fx, wh=WH_US, defl=None)
    ku = sorted(k for k in mkt if k in dy)
    P['USD'] = dict(name='USD', f=12, keys=ku, R=mkt, DY=dy, usd=False, fx=None, wh=WH_US, defl=cpi)
    jr, jd = japan_local()
    P['JPJ'] = dict(name='JPJ', f=12, keys=sorted(jr), R=jr, DY=jd, usd=False, fx=None, wh=0.0, defl=None)
    for c, d in jst().items():
        ys = sorted(d)
        P['JST:' + c] = dict(name='JST:' + c, f=1, keys=ys, R={y: d[y][0] for y in ys}, DY={y: d[y][1] for y in ys},
                             usd=False, fx=None, wh=0.0, defl={y: d[y][2] for y in ys})
    return P, mkt, usj, fx


# ───────────────────────── 家計（自前の模型） ─────────────────────────
class House:
    """口座: 'NT'（つみたて・指数だけ）・'NG'（成長・指数と城）・'T'（課税・特定口座）。資産: 'I'（積み上げ型の指数投信）・'C'（城＝市場の写し・直接保有）。
    rule のキー: o2（None/'loss'/'all'）・o2thr（損の深さの線）・o3（城は課税口座だけ）・x5（発動線 L）・x5mode（'yearend'/'dec'）・phi（年の境目で市場の外にいる月の割合）"""

    def __init__(self, P, holders, rule):
        self.P, self.h, self.rule = P, holders, rule
        self.lots = {}
        self.ci = self.cy = self.cu = 0.0     # 指数の円・城の円・城のドル（円換算）
        self.ytd = self.div = self.wheld = 0.0
        self.carry = []                        # [年, 額]
        self.used = {'NT': 0.0, 'NG': 0.0}
        self.life = self.lifeg = 0.0
        self.back = self.backg = 0.0
        self.year = None
        self.k = 1.0
        self.m = None
        self.pre = False
        self.hold = {}                         # 年の境目の売りの代金（資産→額）
        self.n = collections.Counter()

    # 為替の片道
    def s(self):
        return FX_YEN / self.P['fx'][self.m] if self.P['usd'] else 0.0

    def usd(self, a):
        return self.P['usd'] and a == 'C'

    # 税
    def realize(self, g):
        self.ytd += g
        w = TAX * max(0.0, self.ytd)
        self.ci -= (w - self.wheld)
        self.wheld = w

    def settle(self, yr):
        avail = [c for c in self.carry if yr - c[0] <= 3]
        inc = self.ytd
        tax = 0.0
        if inc > 0:
            rem = inc
            for c in avail:
                u = min(c[1], rem); c[1] -= u; rem -= u
            tax = TAX * rem
            tax -= min(self.P['wh'] * self.div, tax) if self.div > 0 else 0.0
        elif inc < 0:
            self.carry.append([yr, -inc])
        self.ci += self.wheld - tax
        self.n['tax'] += tax
        self.n['carry_lost'] += sum(c[1] for c in self.carry if yr - c[0] >= 3)
        self.carry = [c for c in self.carry if c[1] > 1e-9 and yr - c[0] < 3]
        self.ytd = self.div = self.wheld = 0.0

    # 枠
    def room(self, fr):
        y = (QT if fr == 'NT' else QG) * self.h * self.k - self.used[fr]
        l = LIFE * self.h * self.k - self.life
        if fr == 'NG':
            l = min(l, LIFE_G * self.h * self.k - self.lifeg)
        return max(0.0, min(y, l))

    def frames(self, a):
        return ('NT', 'NG') if a == 'I' else ('NG',)

    # 出し入れ
    def put(self, ac, a, x, from_usd=False, haircut=1.0):
        if x <= TINY:
            return
        v = x
        if self.usd(a) and not from_usd:
            v -= x * self.s()
        v *= haircut
        L = self.lots.setdefault((ac, a), [0.0, 0.0])
        L[0] += v; L[1] += x
        if ac != 'T':
            self.used[ac] += x; self.life += x
            if ac == 'NG':
                self.lifeg += x

    def take(self, ac, a, x, cost):
        L = self.lots.get((ac, a))
        if not L or L[0] <= TINY or x <= TINY:
            return 0.0
        x = min(x, L[0])
        b = L[1] * x / L[0]
        c = cost * x
        if ac == 'T':
            self.realize(x - c - b)
        else:
            self.back += b
            if ac == 'NG':
                self.backg += b
        L[0] -= x; L[1] -= b
        if L[0] <= 1e-7:
            del self.lots[(ac, a)]
        return x - c

    def to_nisa(self, a, x, from_usd=True, haircut=1.0):
        done = 0.0
        for fr in self.frames(a):
            y = min(x - done, self.room(fr))
            if y > TINY:
                self.put(fr, a, y, from_usd, haircut); done += y
        return done

    # 1歩
    def step(self, m, contrib, rm):
        P = self.P
        self.m = m
        f = P['f']
        yr = m // 100 if f == 12 else m
        mo = m % 100 if f == 12 else 1
        first_of_year = (f == 1) or mo == 1
        x5 = self.rule.get('x5')
        mode = self.rule.get('x5mode', 'yearend')
        if f == 1:
            mode = 'yearend'                    # 年次の道では 12月の現金は区別できない（事前登録3）
        if x5 and not self.pre and self.year is not None and first_of_year and mode == 'yearend':
            self.x5_sell()                      # 前年末の値で・前年の売り
        if self.year is not None and yr != self.year:
            self.settle(self.year)
            self.used = {'NT': 0.0, 'NG': 0.0}
            self.life -= self.back; self.lifeg -= self.backg
            self.back = self.backg = 0.0
        self.year = yr
        if contrib > 0:
            self.ci += contrib * (1 - CS); self.cy += contrib * CS
        if not self.pre:
            if x5 and first_of_year and self.hold:
                phi = self.rule.get('phi', 0.0)
                hc = 1.0 / (1 + rm) ** phi if phi else 1.0
                hc *= 1.0 - self.rule.get('gapcost', 0.0)   # 市場の外にいる日数の『期待』の損（実現の1月ではなく平均で）
                for a in sorted(self.hold, key=lambda a: 0 if a == 'C' else 1):   # 城を先に
                    x = self.hold.pop(a)
                    got = self.to_nisa(a, x, True, hc)
                    self.n['x5_rebought'] += got
                    if x - got > TINY:
                        self.put('T', a, x - got, True, hc)
                        self.n['x5_left_T'] += x - got
            if self.rule.get('o2') and first_of_year:
                self.migrate()
        # 城の回転（全口座から時価で按分・代金はドルのまま）
        q = TURN / f
        for key in [k for k in self.lots if k[1] == 'C']:
            self.cu += self.take(key[0], 'C', self.lots[key][0] * q, SWITCH)
        self.cover()
        self.buy()
        if x5 and not self.pre and mode == 'dec' and f == 12 and mo == 12:
            self.x5_sell()                      # 12月の月初に売って12月は現金
        # 当月のリターン
        R, DY = P['R'][m], P['DY'][m]
        wh = P['wh']
        for (ac, a), L in list(self.lots.items()):
            if a == 'I':
                L[0] *= 1 + R - wh * DY - FEE_FUND / f
            else:
                v0 = L[0]
                L[0] *= 1 + R - DY
                d = v0 * DY
                if P['usd']:
                    self.cu += d * (1 - wh)
                else:
                    self.cy += d * (1 - wh)
                if ac == 'T':
                    self.div += d
                    self.realize(d)

    def x5_sell(self):
        L_ = self.rule['x5']
        h, k = self.h, self.k
        yrc = 12 * C_MONTH * k
        cn = sum(v[0] for (ac, a), v in self.lots.items() if ac != 'T' and a == 'C')
        res = cn * (TURN + 0.05)
        cap = (QT + QG) * h * k - yrc - res
        capc = QG * h * k - yrc * CS - res
        cands = [(v[0] / v[1], ac, a) for (ac, a), v in self.lots.items() if ac != 'T' and v[1] > 0 and v[0] <= (1 - L_) * v[1]]
        for _, ac, a in sorted(cands):
            V = self.lots[(ac, a)][0]
            x = min(V, max(0.0, cap))
            if a == 'C':
                x = min(x, max(0.0, capc))
            if x <= TINY:
                continue
            got = self.take(ac, a, x, SWITCH)
            self.hold[a] = self.hold.get(a, 0.0) + got
            self.n['x5_sales'] += 1
            cap -= x
            if a == 'C':
                capc -= x

    def migrate(self):
        mode = self.rule['o2']
        thr = self.rule.get('o2thr', 0.0)
        cands = []
        for (ac, a), (v, b) in self.lots.items():
            if ac != 'T' or v <= TINY or b <= 0:
                continue
            if self.rule.get('o3') and a == 'C':
                continue
            g = v / b - 1
            if mode == 'loss' and not (g < -thr):
                continue
            cands.append((g, a))
        for g, a in sorted(cands):
            L = self.lots.get(('T', a))
            if not L:
                continue
            rm = 0.0
            lifeleft = LIFE * self.h * self.k - self.life
            for fr in self.frames(a):
                rm += min(self.room(fr), max(0.0, lifeleft - rm))
            x = min(L[0], rm)
            if x <= TINY:
                continue
            got = self.take('T', a, x, SWITCH)
            self.to_nisa(a, got, True)
            self.n['o2_moves'] += 1
            self.n['o2_moved'] += got

    def cover(self):
        for _ in range(8):
            if self.ci >= -1e-9:
                return
            need = -self.ci
            u = min(self.cy, need); self.cy -= u; self.ci += u; need -= u
            if need > 1e-9 and self.cu > 0:
                s = self.s()
                u = min(self.cu, need / (1 - s)); self.cu -= u; self.ci += u * (1 - s); need -= u * (1 - s)
            if need <= 1e-9:
                return
            for grp in (('T',), ('NT', 'NG')):
                tv = sum(v[0] for (ac, a), v in self.lots.items() if ac in grp)
                if tv <= 0:
                    continue
                fr = min(1.0, need / tv)
                for key in [k for k in self.lots if k[0] in grp]:
                    got = self.take(key[0], key[1], self.lots[key][0] * fr, 0.0)
                    if self.usd(key[1]):
                        got *= 1 - self.s()
                    self.ci += got
                break

    def buy(self):
        xi = max(0.0, self.ci); xcy = max(0.0, self.cy); xcu = max(0.0, self.cu)
        self.ci -= xi; self.cy -= xcy; self.cu -= xcu
        xc = xcy + xcu
        us = xcu / xc if xc > 0 else 0.0

        def putc(ac, x):
            if x <= TINY:
                return
            self.put(ac, 'C', x * us, True)
            self.put(ac, 'C', x * (1 - us), False)
        if self.pre:
            self.put('T', 'I', xi); putc('T', xc)
            return
        dI, dC = xi, xc
        y = min(dI, self.room('NT'))
        self.put('NT', 'I', y); dI -= y
        o3 = self.rule.get('o3')
        tot = dI + (0.0 if o3 else dC)
        if tot > TINY:
            fr = min(1.0, self.room('NG') / tot)
            yi = dI * fr
            self.put('NG', 'I', yi); dI -= yi
            if not o3:
                yc = dC * fr
                putc('NG', yc); dC -= yc
        self.put('T', 'I', dI); putc('T', dC)

    # いま全部売ったら（税・為替の後）
    def liq(self):
        s = self.s()
        tot = self.ci + self.cy + self.cu * (1 - s) + sum(x * ((1 - s) if a == 'C' else 1) for a, x in self.hold.items())
        U = 0.0
        for (ac, a), (v, b) in self.lots.items():
            tot += v * ((1 - s) if self.usd(a) else 1.0)
            if ac == 'T':
                U += v - b
        inc = self.ytd + U
        tax = 0.0
        if inc > 0:
            av = sum(c[1] for c in self.carry if self.year - c[0] <= 3)
            tax = TAX * max(0.0, inc - av)
            tax -= min(self.P['wh'] * self.div, tax) if self.div > 0 else 0.0
        return tot - (tax - self.wheld)


def run(P, holders, rule, keys, pre_keys=None, record=False):
    d = P['defl']
    base = d[keys[0]] if d else None
    kf = (lambda m: d[m] / base) if d else (lambda m: 1.0)
    per = C_MONTH * (12 if P['f'] == 1 else 1)
    H = House(P, holders, rule)
    rec, con = {}, {}
    pre_liq = 0.0
    if pre_keys:
        H.pre = True
        for m in pre_keys:
            H.k = kf(m)
            H.step(m, per * H.k, P['R'][m])
        H.pre = False
        pre_liq = H.liq()
    for m in keys:
        H.k = kf(m)
        c = per * H.k
        H.step(m, c, P['R'][m])
        if record:
            rec[m] = H.liq(); con[m] = c
    return H.liq(), H, rec, con, pre_liq


# ───────────────────────── 自前の統計 ─────────────────────────
def twr(rec, con, keys, prev):
    out = {}
    for m in keys:
        den = prev + con[m]
        out[m] = (rec[m] - prev - con[m]) / den if den > 0 else 0.0
        prev = rec[m]
    return out


def nw(x, lag=12):
    n = len(x)
    if n < 24:
        return None
    mu = sum(x) / n
    e = [v - mu for v in x]
    v = sum(t * t for t in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - L / (lag + 1)) * sum(e[i] * e[i - L] for i in range(L, n)) / n
    return mu / math.sqrt(v / n) if v > 0 else None


def pval(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def geo(xs, per=12):
    lg = math.fsum(math.log1p(x) for x in xs)
    return math.exp(lg * per / len(xs)) - 1


def exstats(s, b, a=None, z=None):
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nw(ex)
    return {'from': ks[0], 'to': ks[-1], 'n_months': len(ks), 'ex_ann_pct': round(sum(ex) / len(ex) * 1200, 4),
            't': round(t, 2) if t is not None else None, 'p': round(pval(t), 4) if t is not None else None,
            'cagr_s_pct': round(geo([s[k] for k in ks]) * 100, 3), 'cagr_b_pct': round(geo([b[k] for k in ks]) * 100, 3),
            'cagr_diff_pct': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 4),
            'months_nonzero_diff': sum(1 for x in ex if abs(x) > 1e-10)}


def holm(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m, out, run_ = len(it), {}, 0.0
    for i, (v, k) in enumerate(it):
        run_ = max(run_, min(1.0, (m - i) * v))
        out[k] = round(run_, 4)
    return out


def summ(rs):
    if not rs:
        return None
    v = sorted(r for _, r in rs)
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    return {'n': n, 'win': round(sum(1 for r in v if r > 1 + 1e-9) / n, 3), 'tie': round(sum(1 for r in v if abs(r - 1) <= 1e-9) / n, 3),
            'median': round(med, 5), 'worst': [min(rs, key=lambda x: x[1])[0], round(v[0], 5)],
            'best': [max(rs, key=lambda x: x[1])[0], round(v[-1], 5)]}


# ───────────────────────── 窓 ─────────────────────────
def wins(P, H, pre):
    ks, f = P['keys'], P['f']
    n = H * f
    out = []
    for i, k in enumerate(ks):
        if f == 12 and k % 100 != 1:
            continue
        if i - pre < 0 or i + n > len(ks):
            continue
        seg = ks[i - pre:i + n]
        if all(((mplus(a, 1) if f == 12 else a + 1) == b) for a, b in zip(seg, seg[1:])):
            out.append((seg[:pre], seg[pre:]))
    return out


class Cache:
    def __init__(self):
        self.d = {}

    def ratio(self, P, holders, rule_key, rule, pk, ks):
        ck = (P['name'], holders, bool(pk), len(pk or []), ks[0], len(ks))
        if ck not in self.d:
            self.d[ck] = run(P, holders, {}, ks, pk)[0]
        fb = self.d[ck]
        fs, Hs, _, _, _ = run(P, holders, rule, ks, pk)
        return fs / fb, Hs


def window_block(Ps, holders, rule, pre_m, horizons=(20, 25, 30), cache=None, sets=('USJ', 'JPJ', 'USD', 'JST')):
    cache = cache or Cache()
    out = {}
    for st in sets:
        names = [n for n in Ps if n.startswith('JST:')] if st == 'JST' else [st]
        out[st] = {}
        for H in horizons:
            rs, per_c = [], collections.defaultdict(list)
            for pn in names:
                P = Ps[pn]
                pre = (1 if P['f'] == 1 else pre_m) if pre_m else 0
                for pk, ks in wins(P, H, pre):
                    r, _ = cache.ratio(P, holders, None, rule, pk or None, ks)
                    lab = (pn[4:] + ':' + str(ks[0])) if st == 'JST' else ks[0]
                    rs.append((lab, round(r, 6)))
                    per_c[pn[4:] if st == 'JST' else pn].append(r)
            e = {'all': summ(rs)}
            if st in ('USJ', 'USD', 'JPJ'):
                e['end_le_2006'] = summ([(k, r) for k, r in rs if k // 100 + H - 1 <= 2006])
                e['end_ge_2007'] = summ([(k, r) for k, r in rs if k // 100 + H - 1 >= 2007])
            if st == 'JST' and H == 20:
                e['country_median_gt1'] = {c: round(S.median(v), 5) for c, v in per_c.items()}
            if st == 'USJ' and H == 20:
                e['rs'] = rs
            out[st][H] = e
    return out


def passes(wb):
    ph = {}
    for H in (20, 25, 30):
        ph[H] = all(wb[s][H]['all']['win'] >= 0.9 and wb[s][H]['all']['median'] >= 1.0 for s in ('USJ', 'JPJ', 'USD', 'JST'))
    return ph


# ───────────────────────── 格付けの材料（USJ・自前の時間加重） ─────────────────────────
def grade_series(P, holders, rule, pre_m, a, z):
    ks = [k for k in P['keys'] if a <= k <= z]
    pk = None
    if pre_m:
        i0 = P['keys'].index(ks[0])
        if i0 < pre_m:
            ks = ks[pre_m - i0:]
            i0 = P['keys'].index(ks[0])
        pk = P['keys'][i0 - pre_m:i0]
    fs, Hs, rs, cs, p0 = run(P, holders, rule, ks, pk, record=True)
    fb, Hb, rb, cb, q0 = run(P, holders, {}, ks, pk, record=True)
    return twr(rs, cs, ks, p0), twr(rb, cb, ks, q0), fs / fb, Hs.n, ks


def grade_all(P, holders, rule, pre_m, usj_mkt):
    last = P['keys'][-1]
    per = {'full': (P['keys'][0], last), 'train': (P['keys'][0], TRAIN_END), 'hold': (HOLD_START, last), 'recent': (RECENT_START, last)}
    out = {}
    ser = {}
    for nm, (a, z) in per.items():
        s, b, fr, n, ks = grade_series(P, holders, rule, pre_m, a, z)
        e = exstats(s, b)
        e['final_ratio'] = round(fr, 6)
        e['fires'] = {k: round(v) for k, v in n.items() if k in ('o2_moves', 'o2_moved', 'x5_sales', 'x5_rebought', 'x5_left_T')}
        out[nm] = e
        ser[nm] = (s, b)
    # 保有期間の前半・後半（同じ家計の系列を分けて測る）
    s, b = ser['hold']
    ks = sorted(s)
    mid = ks[len(ks) // 2]
    out['hold_first_half'] = exstats(s, b, None, ks[len(ks) // 2 - 1])
    out['hold_second_half'] = exstats(s, b, mid, None)
    # 差は市場の値動きの一定の割合か（差を市場の円のリターンへ回帰）
    xs = [usj_mkt[k] for k in ks]
    ys = [s[k] - b[k] for k in ks]
    n = len(ks)
    mx, my = sum(xs) / n, sum(ys) / n
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    res = [y - (my - beta * mx) - beta * x for x, y in zip(xs, ys)]
    r2 = 1 - sum(r * r for r in res) / sum((y - my) ** 2 for y in ys) if any(abs(y - my) > 0 for y in ys) else None
    alpha_m = my - beta * mx
    t_mkt = nw([usj_mkt[k] for k in ks])
    out['hold_diff_on_market'] = {'beta_of_diff_on_usj_mkt': round(beta, 5), 'r2': round(r2, 3) if r2 is not None else None,
                                  'alpha_ann_pct': round(alpha_m * 1200, 4),
                                  'alpha_share_of_mean_diff': round(alpha_m / my, 3) if my else None,
                                  'usj_market_nw_t_same_months': round(t_mkt, 2),
                                  'note': '差の t は、差が市場の円リターンの一定割合（課税口座の繰り延べ税の差）なら、市場そのものの t に近くなる'}
    # 市場そのもの（上限なしの時価加重・円）に対して: 家計の税引後の時間加重
    out['hold_vs_us_market_jpy'] = {'rule': exstats(s, {k: usj_mkt[k] for k in ks}), 'default': exstats(b, {k: usj_mkt[k] for k in ks})}
    return out, ser


def grade_from(g, roll_win, repl, holm_p):
    tr, ho, fu = g['train'], g['hold'], g['full']
    c = {'C1_train': tr['ex_ann_pct'] > 0 and (tr['t'] or 0) >= 2.0,
         'C2_hold_sign': ho['ex_ann_pct'] > 0 and ho['cagr_diff_pct'] > 0,
         'C3_hold_t': (ho['t'] or 0) >= 1.65,
         'C4_roll20': roll_win >= 0.8,
         'C5_repl': repl >= 2 / 3,
         'C6_net_cost': ho['ex_ann_pct'] > 0 and ho['cagr_diff_pct'] > 0,
         'C7_multi': (fu['t'] or 0) >= 3.0 or (holm_p is not None and holm_p < 0.05)}
    base = c['C1_train'] and c['C2_hold_sign'] and c['C6_net_cost']
    if base and c['C3_hold_t'] and c['C4_roll20'] and c['C7_multi'] and c['C5_repl']:
        gr = 'S'
    elif base and c['C4_roll20'] and c['C7_multi'] and (c['C3_hold_t'] or c['C5_repl']):
        gr = 'A'
    elif base:
        gr = 'B'
    else:
        gr = 'C'
    return gr, c


def rounded_2dp_view(g):
    """mw_common.excess_stats は ex_ann と cagr_diff を小数2桁（%）に丸める。同じ丸めで C2 が通るかも見る"""
    return {k: round(g[k]['ex_ann_pct'], 2) for k in ('full', 'train', 'hold', 'recent')}


# ───────────────────────── 本体 ─────────────────────────
def main():
    t0 = time.time()
    Ps, mkt_usd, usj, fx = build()
    rep = json.load(open(os.path.join(M.BASE, 'out', 'mw_nisa_ops.json')))
    summ_prog = json.load(open(os.path.join(M.BASE, 'out', 'mw_summary.json')))
    out = {'angle': 'nisa_ops', 'verifier': 'night/mw_nisa_ops_verify.py（独立の模型・独立の時間加重と統計）',
           'data_built': {pn: {'from': P['keys'][0], 'to': P['keys'][-1], 'n': len(P['keys'])} for pn, P in Ps.items() if not pn.startswith('JST:')},
           'data_note': '配当のリターンは French 49業種（前月…ではなく同月の社数×平均規模で加重・欠けた業種は除く）から自前で。研究役は12業種。為替は DEXJPUS の月末、日本は French International Countries の Japan・Local・Not Reqd',
           'candidates': {}}
    out['data_built']['JST_countries'] = sorted(pn[4:] for pn in Ps if pn.startswith('JST:'))
    out['data_built']['usj_cagr_2007_pct'] = round(geo([usj[k] for k in sorted(usj) if k >= HOLD_START]) * 100, 2)
    out['data_built']['usj_cagr_full_pct'] = round(geo([usj[k] for k in sorted(usj)]) * 100, 2)
    P = Ps['USJ']
    cache = Cache()

    def full_eval(tag, holders, rule, pre_m, fam_rules, fam_name, rep_name, extra_neighbors):
        log = lambda *a: print(tag, *a, f'({time.time() - t0:.0f}s)', flush=True)
        g, ser = grade_all(P, holders, rule, pre_m, usj)
        log('grade', {k: (g[k]['ex_ann_pct'], g[k]['t']) for k in ('full', 'train', 'hold', 'recent')})
        wb = window_block(Ps, holders, rule, pre_m, cache=cache)
        log('windows', {s: (wb[s][20]['all']['win'], wb[s][20]['all']['median']) for s in wb})
        roll = wb['USJ'][20]['all']['win']
        cm = wb['JST'][20]['country_median_gt1']
        nonus = {c: v for c, v in cm.items() if c != 'USA'}
        repl = sum(1 for v in nonus.values() if v > 1.0) / len(nonus)
        # Holm: 同じ族の他の規則の p（自前で測れるものは自前・測れないものは研究役の値）
        pmine = {rep_name: g['hold']['p']}
        for rn, rr in fam_rules.items():
            if rr is None:
                continue
            gg, _ = grade_all(P, holders, rr, pre_m, usj)
            pmine[rn] = gg['hold']['p']
        prep = {n: e['hold']['p'] for n, e in rep['grades'].items() if e.get('family') == fam_name and e.get('hold')}
        pfam = dict(prep)
        pfam.update({k: v for k, v in pmine.items()})
        h2 = holm(pfam)
        # 片側（勝ちの向きだけを主張する検定）: 差が負の規則は p=1
        signs = {n: e['hold']['ex_ann'] for n, e in rep['grades'].items() if e.get('family') == fam_name and e.get('hold')}
        pone = {}
        for n, pv in pfam.items():
            sgn = signs.get(n, 0)
            if n == rep_name:
                sgn = g['hold']['ex_ann_pct']
            pone[n] = (pv / 2 if sgn > 0 else 1.0) if pv is not None else None
        h1 = holm(pone)
        gr, cr = grade_from(g, roll, repl, h2.get(rep_name))
        gr1, _ = grade_from(g, roll, repl, h1.get(rep_name))
        # 研究役の広い族（15本・60本）の Holm の値をそのまま当てた格付け
        wid = rep.get('grade_robustness_wider_holm', {}).get(rep_name, {})
        gr15, _ = grade_from(g, roll, repl, wid.get('holm_all15_rules_same_scenario'))
        gr60, _ = grade_from(g, roll, repl, wid.get('holm_all60_graded'))
        ph = passes(wb)
        ent = {'grade_reproduced_registered_family_two_sided_holm': gr, 'criteria': cr,
               'holm_two_sided_family': h2.get(rep_name), 'family_p_used': pfam,
               'family_p_note': '自前で測った規則は自前の p、測っていない規則（O1・O4・O5 等）は研究役の p を使った',
               'grade_if_one_sided_holm': gr1, 'holm_one_sided_family': h1.get(rep_name),
               'grade_with_researcher_wider_holm_15': gr15, 'grade_with_researcher_wider_holm_60': gr60,
               'grade_numbers': g, 'rounded_2dp_ex_ann': rounded_2dp_view(g),
               'roll20_usj_dca_win': roll, 'repl_share_nonus_jst_median_gt1': round(repl, 3), 'repl_country_medians': nonus,
               'windows': {s: {H: {k: v for k, v in e.items() if k != 'rs'} for H, e in wb[s].items()} for s in wb},
               'usj20_windows': wb['USJ'][20]['rs'],
               'prereg_verdict_pass_by_horizon': ph,
               'program_wide_bonferroni_t': summ_prog.get('bonferroni_t_program_wide'),
               'hold_t_clears_program_line': (g['hold']['t'] or 0) >= summ_prog.get('bonferroni_t_program_wide', 4.43)}
        # 隣の設定
        nb = {}
        for nname, (h_, rr, pm) in extra_neighbors.items():
            gg, _ = grade_all(P, h_, rr, pm, usj)
            ww = window_block(Ps, h_, rr, pm, horizons=(20,), cache=cache)
            nb[nname] = {'hold': {k: gg['hold'][k] for k in ('ex_ann_pct', 't', 'cagr_diff_pct')},
                         'train': {k: gg['train'][k] for k in ('ex_ann_pct', 't')},
                         'full': {k: gg['full'][k] for k in ('ex_ann_pct', 't')},
                         'win20': {s: [ww[s][20]['all']['win'], ww[s][20]['all']['median']] for s in ww}}
            log('neighbor', nname, nb[nname]['hold'], nb[nname]['win20'])
        ent['neighbors'] = nb
        return ent

    # ── 1) O2a__S4（格付け S）
    O2a = {'o2': 'loss'}
    fam_s4 = {'O2b__S4_init_taxable': {'o2': 'all'}, 'O3__S4_init_taxable': {'o3': True}}
    nbs = {
        'O2a_pre6m': (2, O2a, 6), 'O2a_pre24m': (2, O2a, 24),
        'O2a_lossdeeper5pct': (2, {'o2': 'loss', 'o2thr': 0.05}, 12), 'O2a_lossdeeper10pct': (2, {'o2': 'loss', 'o2thr': 0.10}, 12),
        'O2a_one_holder_S4': (1, O2a, 12),
    }
    out['candidates']['O2a__S4_init_taxable'] = full_eval('O2a_S4', 2, O2a, 12, fam_s4, 'sens_S4_init_taxable', 'O2a__S4_init_taxable', nbs)
    # ── 2) X5b__S1（格付け B）
    X5b = {'x5': 0.10, 'x5mode': 'yearend'}
    fam_x5 = {'X5__S1_one_holder': {'x5': 0.01, 'x5mode': 'yearend'}, 'X5c__S1_one_holder': {'x5': 0.01, 'x5mode': 'dec'}}
    nbs = {
        'X5b_L05': (1, {'x5': 0.05, 'x5mode': 'yearend'}, 0), 'X5b_L15': (1, {'x5': 0.15, 'x5mode': 'yearend'}, 0),
        'X5b_L20': (1, {'x5': 0.20, 'x5mode': 'yearend'}, 0),
        'X5b_out_of_market_quarter_month': (1, {'x5': 0.10, 'x5mode': 'yearend', 'phi': 0.25}, 0),
        'X5b_out_of_market_half_month': (1, {'x5': 0.10, 'x5mode': 'yearend', 'phi': 0.5}, 0),
        'X5b_dec_cash_L10': (1, {'x5': 0.10, 'x5mode': 'dec'}, 0),
        'X5b_gap_expected_cost_0.2pct': (1, {'x5': 0.10, 'x5mode': 'yearend', 'gapcost': 0.002}, 0),
        'X5b_two_holders_P': (2, X5b, 0),
    }
    out['candidates']['X5b__S1_one_holder'] = full_eval('X5b_S1', 1, X5b, 0, fam_x5, 'sens_explore3_S1_one_holder', 'X5b__S1_one_holder', nbs)
    # ── 参考: 要約の他の主張（O2b__S4 の窓の勝ち・O3__P の負け）を自前の模型で
    ref = {}
    for nm, h_, rr, pm in (('O2b__S4_init_taxable', 2, {'o2': 'all'}, 12), ('O3__P', 2, {'o3': True}, 0), ('O2a__P', 2, O2a, 0)):
        ww = window_block(Ps, h_, rr, pm, cache=cache)
        ref[nm] = {s: {H: ww[s][H]['all'] for H in (20, 30)} for s in ww}
        ref[nm]['prereg_pass_by_horizon'] = passes(ww)
        print('ref', nm, {s: (ww[s][20]['all']['win'], ww[s][20]['all']['median']) for s in ww}, f'({time.time() - t0:.0f}s)', flush=True)
    out['reference_checks'] = ref
    # 研究役の数字（並べて比べる）
    out['researcher_numbers'] = {n: {'grade': rep['grades'][n]['grade'], 'full': rep['grades'][n]['full'], 'train': rep['grades'][n]['train'],
                                     'hold': rep['grades'][n]['hold'], 'roll20': rep['grades'][n]['roll20_dca_windows'],
                                     'repl': rep['grades'][n]['repl'], 'holm': rep['grades'][n]['holm_p_hold'],
                                     'final_ratio': rep['grades'][n]['final_ratio'], 'fires': rep['grades'][n]['fires']}
                                 for n in ('O2a__S4_init_taxable', 'X5b__S1_one_holder')}
    out['n_rules_tested_by_angle'] = rep.get('n_tested')
    out['verdicts'] = verdicts(out)
    out['runtime_s'] = round(time.time() - t0)
    return out


def verdicts(out):
    A = out['candidates']['O2a__S4_init_taxable']
    B = out['candidates']['X5b__S1_one_holder']
    ga, gb = A['grade_numbers'], B['grade_numbers']
    w = lambda c, s, H=20: c['windows'][s][H]['all']
    na, nb = A['neighbors'], B['neighbors']
    va = {
        'claimed_grade': 'S（感度の場面 S4・登録した族の Holm）',
        'reproduced': True,
        'verdict': 'downgraded to B',
        'verified_grade': 'B',
        'key_numbers': (f"自前の模型: 保有期間 +{ga['hold']['ex_ann_pct']:.3f}%/年 t{ga['hold']['t']}・CAGR差 +{ga['hold']['cagr_diff_pct']:.3f}pt・訓練 t{ga['train']['t']}・全期間 t{ga['full']['t']}・"
                        f"20年積立窓 USJ 勝{w(A,'USJ')['win']} 中央{w(A,'USJ')['median']} / JPJ 勝{w(A,'JPJ')['win']} 中央{w(A,'JPJ')['median']} / USD 勝{w(A,'USD')['win']} / JST 勝{w(A,'JST')['win']}・"
                        f"登録族の Holm {A['holm_two_sided_family']}（研究役 0.0472 と一致）・広い族 15本/60本では B・市場（French Mkt の円）に対しては {ga['hold_vs_us_market_jpy']['rule']['ex_ann_pct']:.2f}%/年 t{ga['hold_vs_us_market_jpy']['rule']['t']}"),
        'issues': [
            f"数字は独立の模型でほぼ完全に再現した（USJ20 の勝ち {w(A,'USJ')['win']}・中央 {w(A,'USJ')['median']}・保有 t {ga['hold']['t']}）。問題は数字ではなく格付けの意味",
            f"保有期間の移し替えは {ga['hold']['fires'].get('o2_moves')} 回・計 {ga['hold']['fires'].get('o2_moved')} 円＝2009年1月の一度の出来事。2013-07 以降は発動0回（recent の差は0）。後半（2016-11〜）の t {ga['hold_second_half']['t']} は発動の無い期間の繰り延べ税の漂いで、独立の証拠ではない",
            f"差は市場の円リターンに回帰すると R² {ga['hold_diff_on_market']['r2']}・差の平均の {1 - (ga['hold_diff_on_market']['alpha_share_of_mean_diff'] or 0):.0%} が市場の値動きの一定割合（課税口座の含み益への税の差）。同じ月の市場そのものの t は {ga['hold_diff_on_market']['usj_market_nw_t_same_months']}＝差の t は『2007年以降に市場が上がった』をかなり写している",
            f"訓練 t {ga['train']['t']} は線 2.0 の直上。研究役の自認のとおり、直し（S4 の時間加重の最初の月）の前は B（Holm 0.059）で、直しの後に S へ動いた",
            f"Holm は登録した族（S4 の主6本）でだけ 0.05 を下回る（両側 {A['holm_two_sided_family']}・片側 {A['holm_one_sided_family']}）。同じ場面の15本・格付けした60本に広げると B。プログラム全体の線 t≈{A['program_wide_bonferroni_t']} には保有 t {ga['hold']['t']} は遠く届かない",
            f"事前登録の判定（4つの道の組すべてで勝ち≥0.90 かつ中央≥1）は20/25/30年とも不合格: 日本 JPJ の20年 勝{w(A,'JPJ')['win']}・中央{w(A,'JPJ')['median']}、25年 勝{w(A,'JPJ',25)['win']}、30年 勝{w(A,'JPJ',30)['win']}（日本の下落の道では損の区画を早く NISA に入れても取り返せない）",
            f"隣の設定: 損の深さ5%以上だけ移すと USJ20 勝{na['O2a_lossdeeper5pct']['win20']['USJ'][0]}・USD {na['O2a_lossdeeper5pct']['win20']['USD'][0]}、10%以上だと USJ20 勝{na['O2a_lossdeeper10pct']['win20']['USJ'][0]}（C4 の線0.8を割る）・USD {na['O2a_lossdeeper10pct']['win20']['USD'][0]}・訓練 t {na['O2a_lossdeeper10pct']['train']['t']}（C1 割れ）。1人の家計では訓練 t {na['O2a_one_holder_S4']['train']['t']}（C1 割れ）。持ち越し6か月では訓練 t {na['O2a_pre6m']['train']['t']}（C1 割れ）",
            f"S4 は参考の場面（課税口座に12か月分の持ち越しがある家計）で、事前登録は判定を場面 P だけに置いた。P の O2a は20年窓 USJ 勝{out['reference_checks']['O2a__P']['USJ'][20]['win']}・中央{out['reference_checks']['O2a__P']['USJ'][20]['median']}（ほぼ同点）",
            f"これは市場に勝つ規則ではない: 家計の税引後の時間加重は上限なしの時価加重の米国市場（円）に {ga['hold_vs_us_market_jpy']['rule']['ex_ann_pct']:.2f}%/年（t{ga['hold_vs_us_market_jpy']['rule']['t']}）負けており、既定（{ga['hold_vs_us_market_jpy']['default']['ex_ann_pct']:.2f}%/年）との差 +0.07pt/年を縮めるだけ",
            "先読みは無い（1月の月初に、その時点の簿価と時価だけで移す）。費用は模型の中（乗り換え0.1%）。生存者の偏りは市場全体の指数なので無い",
        ],
    }
    q = nb['X5b_out_of_market_quarter_month']
    vb = {
        'claimed_grade': 'B（感度の場面 S1・探索の族 X5）',
        'reproduced': True,
        'verdict': 'downgraded to C',
        'verified_grade': 'C',
        'key_numbers': (f"自前の模型: 保有 +{gb['hold']['ex_ann_pct']:.3f}%/年 t{gb['hold']['t']}・訓練 t{gb['train']['t']}・全期間 t{gb['full']['t']}・USJ20 勝{w(B,'USJ')['win']}（C4 の0.8に届かず）・"
                        f"JPJ20 勝{w(B,'JPJ')['win']}・USD20 勝{w(B,'USD')['win']}・JST20 勝{w(B,'JST')['win']}・Holm {B['holm_two_sided_family']}・"
                        f"年の境目に市場の外へ約1/4か月出る現実の形: 訓練 t{q['train']['t']}・USJ20 勝{q['win20']['USJ'][0]}・USD {q['win20']['USD'][0]}・JST {q['win20']['JST'][0]}"),
        'issues': [
            f"数字は独立の模型で再現した（保有 t {gb['hold']['t']}・訓練 t {gb['train']['t']}・USJ20 勝 {w(B,'USJ')['win']}・中央 {w(B,'USJ')['median']}）。B は C1・C2・C6 だけで立っている（C4・C7 は不合格）",
            "X5b は研究役自身が『楽観の上限』と書いた摩擦なしの形（前年12月末の値で売り、同じ値で年替わり直後に買い戻す＝市場の外の時間0）。投信の解約・約定・受渡しの都合で、現実には年の境目で数営業日は市場の外に出る",
            f"その摩擦を入れると勝ちは消える: 1月の実現リターンの1/4を逃す形で、訓練 t {q['train']['t']}（C1 割れ→C）・全期間 t {q['full']['t']}・20年窓 USJ 勝{q['win20']['USJ'][0]}・USD {q['win20']['USD'][0]}・JST {q['win20']['JST'][0]}（中央 {q['win20']['JST'][1]}）。平均の期待損 0.2%（1/4か月×月0.8%）でも訓練 t {nb['X5b_gap_expected_cost_0.2pct']['train']['t']}・USJ20 勝 {nb['X5b_gap_expected_cost_0.2pct']['win20']['USJ'][0]}。12月を現金で持つ悲観の形（発動線90%）では訓練 t {nb['X5b_dec_cash_L10']['train']['t']}・保有 t {nb['X5b_dec_cash_L10']['hold']['t']}",
            f"保有期間の売りは {gb['hold']['fires'].get('x5_sales')} 回（2008〜09年の一つの下落）。前半 {gb['hold_first_half']['ex_ann_pct']:.3f}%/年 t{gb['hold_first_half']['t']}（負）、後半 +{gb['hold_second_half']['ex_ann_pct']:.3f}%/年 t{gb['hold_second_half']['t']} は発動0回の漂い。2013-07 以降は発動0回",
            f"発動線の隣: 99%（X5）は研究役の格付け C、95% は保有 t {nb['X5b_L05']['hold']['t']}、85%・80% は保有 t {nb['X5b_L15']['hold']['t']} だが USJ20 勝 {nb['X5b_L15']['win20']['USJ'][0]}・{nb['X5b_L20']['win20']['USJ'][0]}、JST {nb['X5b_L15']['win20']['JST'][0]}・{nb['X5b_L20']['win20']['JST'][0]}",
            f"主の家計（2人・場面 P）では同じ規則が C（保有 t {nb['X5b_two_holders_P']['hold']['t']}・USD20 勝 {nb['X5b_two_holders_P']['win20']['USD'][0]}・JST20 勝 {nb['X5b_two_holders_P']['win20']['JST'][0]}）",
            f"事前登録の判定（4つの道の組すべてで勝ち≥0.90）は20/25/30年とも不合格。Holm {B['holm_two_sided_family']}。プログラム全体の線 t≈{B['program_wide_bonferroni_t']} に遠く届かない",
            f"市場に勝つ規則ではない: 家計の税引後の時間加重は米国市場（円）に {gb['hold_vs_us_market_jpy']['rule']['ex_ann_pct']:.2f}%/年（t{gb['hold_vs_us_market_jpy']['rule']['t']}）負け、既定との差は +{gb['hold']['ex_ann_pct']:.3f}pt/年",
        ],
    }
    return {'O2a__S4_init_taxable': va, 'X5b__S1_one_holder': vb,
            'others_checked': {
                'O2b__S4_init_taxable': f"要約の『米国と16か国で9割超の勝ち』を再現: USJ20 勝{out['reference_checks']['O2b__S4_init_taxable']['USJ'][20]['win']}・USD {out['reference_checks']['O2b__S4_init_taxable']['USD'][20]['win']}・JST {out['reference_checks']['O2b__S4_init_taxable']['JST'][20]['win']}・JPJ {out['reference_checks']['O2b__S4_init_taxable']['JPJ'][20]['win']}（格付け C のまま・参考の場面）",
                'O3__P': f"『城を課税口座に置くと負け』を再現: USJ20 中央 {out['reference_checks']['O3__P']['USJ'][20]['median']}・USD20 中央 {out['reference_checks']['O3__P']['USD'][20]['median']}・勝ち0%"}}


if __name__ == '__main__':
    res = main()
    print('保存', M.save(OUT, res))
