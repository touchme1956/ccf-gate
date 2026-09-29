#!/usr/bin/env python3
"""night/mw_country_verify.py — mw_country の主張への反証の検証（読むだけ・門の判定には不使用）

検証する主張（out/mw_country.json）:
  S: E2_dp_K3（相手 JKP developed＝米国抜き）／D1_f20_dp_K3／D4_eafe_dp_K3／D6_f20_dp_K2
  A: P2_mom12_K5（相手 JKP developed＝米国抜き）
  B の上位2本（保有期間の超過順）: E3_mom12_K3（+1.62）／E3_bm_K3（+1.48）。P7_usrow_12（+0.42・主の族の唯一の B）も併せて確かめる

独立性: mw_common からは取得（M.get のキャッシュ）と URL の型だけを使う。
  French の .Dat / CSV の読み取り・JKP の CSV の読み取り・配当利回り・売買の再生・超過・NW t・CAGR・20年窓・費用・合否の線は
  すべてこのファイルで書き直した（研究側の mw_country.py の関数は一つも呼ばない）。

出力: out/mw_country_verify.json
"""
import sys, os, io, re, csv, json, math, zipfile, random, datetime, statistics as ST
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得（キャッシュ）と URL の型だけ

BASE = M.BASE
FR_CSV = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'
FR_ZIP = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}.zip'
TRAIN_END, HOLD_START, RECENT_START = 200612, 200701, 201307

FR_FILES = {'gbr': 'UK', 'aut': 'Austria', 'aus': 'Austrlia', 'bel': 'Belgium', 'can': 'Canada', 'dnk': 'Denmark',
            'fin': 'Finland', 'fra': 'France', 'deu': 'Germany', 'hkg': 'HongKong', 'irl': 'Ireland', 'ita': 'Italy',
            'jpn': 'Japan', 'nld': 'Nethrlnd', 'nzl': 'NewZland', 'nor': 'Norway', 'sgp': 'Singapor', 'esp': 'Spain',
            'swe': 'Sweden', 'che': 'Swtzrlnd'}
F20 = sorted(FR_FILES)
EAFE19 = [c for c in F20 if c != 'can']
DEV23 = 'usa jpn gbr deu fra che nld swe dnk nor fin bel aut ita esp irl prt can aus nzl hkg sgp isr'.split()
DXUS22 = [c for c in DEV23 if c != 'usa']
V21 = F20 + ['usa']
NMIN = 20
COST_DEV = (0.0015, 0.0040)   # 片道100%あたりの売買・国別ETFの信託報酬の差（研究側の事前登録どおり）
COST_BROAD = (0.0005, 0.0)
N_TESTED_ANGLE = 97


# ───────────────────────── 月の算術 ─────────────────────────
def madd(ym, k):
    y, m = divmod(ym, 100)
    n = y * 12 + m - 1 + k
    return (n // 12) * 100 + n % 12 + 1


def mrange(a, z):
    out = []
    while a <= z:
        out.append(a); a = madd(a, 1)
    return out


# ───────────────────────── 読み取り（自前） ─────────────────────────
def _zip_text(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    return z, z.read(z.namelist()[0]).decode('latin-1')


def fr_csv_monthly(name):
    """French の因子 CSV の最初の月次表 → {yyyymm: {列: 小数}}"""
    _, txt = _zip_text(M.get(FR_CSV.format(name), name=f'fr_{name}.zip'))
    cols, out = None, {}
    for line in txt.splitlines():
        cells = [c.strip() for c in line.split(',')]
        if cols is None:
            if len(cells) > 2 and cells[0] == '' and 'RF' in cells:
                cols = cells[1:]
            continue
        if re.fullmatch(r'\d{6}', cells[0]):
            out[int(cells[0])] = {c: float(v) / 100 for c, v in zip(cols, cells[1:]) if v != ''}
        elif out:
            break
    return out


def parse_dat(txt):
    """French の国別 .Dat → {(種類, 組, 頻度[, 連番]): {'cols': [...], 'rows': {日付: [値 or None]}}}"""
    secs, kind, grp, cols, cur = {}, None, None, None, None
    for raw in txt.splitlines():
        s = raw.strip()
        if not s:
            cur = None
            continue
        tok = s.split()
        if re.fullmatch(r'\d{4}|\d{6}', tok[0]):
            if cols is None or kind is None:
                continue
            key = (kind, grp, 'm' if len(tok[0]) == 6 else 'a')
            if cur is None:
                if key in secs:
                    key = key + (len(secs),)
                cur = secs[key] = {'cols': list(cols), 'rows': {}}
            vals = []
            for v in tok[1:]:
                f = float(v)
                vals.append(None if f <= -99.99 or f == -999 else f)
            cur['rows'][int(tok[0])] = vals
            continue
        cur = None
        low = s.lower()
        if re.search(r'dollar\s+returns', low):
            kind = 'USD'
        elif re.search(r'local\s+returns', low):
            kind = 'LOC'
        elif 'average of annual' in low or 'value-weight ratios' in low:
            kind = 'RATIO'
        if 'not req' in low:
            grp = 'NR'
        elif 'required' in low:
            grp = 'RQ'
        if tok[0] in ('Mkt', 'Firms'):
            cols = tok
    return secs


def col_of(sec, name, scale=0.01):
    i = sec['cols'].index(name)
    return {d: v[i] * scale for d, v in sec['rows'].items() if i < len(v) and v[i] is not None}


def load_french_countries():
    zt, _ = _zip_text(M.get(FR_ZIP.format('F-F_International_Countries'), name='fr_F-F_International_Countries.zip'))
    zx, _ = _zip_text(M.get(FR_ZIP.format('F-F_International_Countries_Wout_Div'), name='fr_F-F_International_Countries_Wout_Div.zip'))
    D = {}
    for c, f in FR_FILES.items():
        a = parse_dat(zt.read(f + '.Dat').decode('latin-1'))
        b = parse_dat(zx.read(f + '.Dat').decode('latin-1'))
        rt = a[('RATIO', 'NR', 'a')]
        D[c] = {'usd': col_of(a[('USD', 'NR', 'm')], 'Mkt'), 'loc': col_of(a[('LOC', 'NR', 'm')], 'Mkt'),
                'locx': col_of(b[('LOC', 'NR', 'm')], 'Mkt'), 'usdx': col_of(b[('USD', 'NR', 'm')], 'Mkt'),
                'firms': col_of(rt, 'Firms', 1.0), 'bm': col_of(rt, 'B/M'), 'yld': col_of(rt, 'Yld')}
    zi, _ = _zip_text(M.get(FR_ZIP.format('F-F_International_Indices'), name='fr_F-F_International_Indices.zip'))
    ia = parse_dat(zi.read('Ind_all.Dat').decode('latin-1'))
    eafe = col_of(ia[('USD', 'NR', 'm')], 'Mkt')
    eafe_loc = col_of(ia[('LOC', 'NR', 'm')], 'Mkt')
    return D, eafe, eafe_loc


def load_jkp(c):
    """JKP の国・地域 mkt vw（超過・ドル建て）→ ({ym: 超過}, {ym: 銘柄数 or 国数})"""
    b = M.get(M.JKP.format(sub='', r=c, k='mkt', f='monthly', w='vw'), name=f'jkp_factor_{c}_mkt_vw_monthly.zip')
    _, txt = _zip_text(b)
    ret, n = {}, {}
    for row in csv.DictReader(io.StringIO(txt)):
        if row['ret'] in ('', 'NA', 'na'):
            continue
        ym = int(row['date'][:4]) * 100 + int(row['date'][5:7])
        ret[ym] = float(row['ret'])
        k = row.get('n_stocks') or row.get('n_countries')
        n[ym] = int(k) if k not in (None, '', 'na', 'NA') else None
    return ret, n


# ───────────────────────── 統計（自前） ─────────────────────────
def nw(x, L=12):
    n = len(x)
    if n < 24:
        return None
    mu = sum(x) / n
    e = [v - mu for v in x]
    s = sum(v * v for v in e) / n
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * sum(e[i] * e[i - l] for i in range(l, n)) / n
    return mu / math.sqrt(s / n) if s > 0 else None


def geo(xs):
    return math.exp(sum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def comp(s, b, a=None, z=None, drop=()):
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not any(lo <= k <= hi for lo, hi in drop))
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nw(d)
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    mb = sum(bv) / len(bv); ms = sum(sv) / len(sv)
    cov = sum((x - ms) * (y - mb) for x, y in zip(sv, bv)); vb = sum((y - mb) ** 2 for y in bv)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(sum(d) / len(d) * 1200, 2), 't': round(t, 2) if t is not None else None,
            'cagr_diff': round((geo(sv) - geo(bv)) * 100, 2), 'cagr_s': round(geo(sv) * 100, 2), 'cagr_b': round(geo(bv) * 100, 2),
            'beta': round(cov / vb, 2) if vb else None}


def roll20(s, b):
    ks = sorted(k for k in s if k in b)
    if not ks:
        return None
    res = []
    for y in range(ks[0] // 100, 2100):
        a, z = y * 100 + 7, (y + 20) * 100 + 6
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < 240 * 0.97:
            continue
        res.append((y, round((math.exp(sum(math.log1p(s[k]) for k in w) / 20) - math.exp(sum(math.log1p(b[k]) for k in w) / 20)) * 100, 2)))
    if not res:
        return None
    return {'windows': len(res), 'win_rate': round(sum(1 for _, v in res if v > 0) / len(res), 3),
            'worst': min(res, key=lambda x: x[1]), 'median': sorted(v for _, v in res)[len(res) // 2]}


def net_of(r, ann_turn, cpu, er):
    c = (ann_turn * cpu + er) / 12
    return {k: v - c for k, v in r.items()}


def p2(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def zcrit(alpha_two, m):
    """Bonferroni の両側 t 線（正規近似）"""
    target = alpha_two / m / 2
    lo, hi = 0.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(mid / math.sqrt(2)) > target:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)


def criteria(full, train, hold, r20, hold_net):
    c1 = bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0)
    c2 = bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0)
    c3 = bool(hold and (hold['t'] or 0) >= 1.65)
    c4 = bool(r20 and r20['win_rate'] >= 0.8)
    c6 = bool(hold_net and hold_net['ex'] > 0 and hold_net['cagr_diff'] > 0)
    c7 = bool(full and (full['t'] or 0) >= 3.0)  # Holm の経路は別に出す
    base = c1 and c2 and c6
    if base and c3 and c4 and c7:
        g = 'S'
    elif base and c4 and c7 and c3:
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, {'C1': c1, 'C2': c2, 'C3': c3, 'C4': c4, 'C6': c6, 'C7_full_t3': c7}


# ───────────────────────── 世界 ─────────────────────────
class Data:
    def __init__(self):
        ff = fr_csv_monthly('F-F_Research_Data_Factors')
        self.rf = {k: v['RF'] for k, v in ff.items()}
        self.fmkt = {k: v['Mkt-RF'] + v['RF'] for k, v in ff.items()}
        dev = fr_csv_monthly('Developed_3_Factors')
        dxu = fr_csv_monthly('Developed_ex_US_3_Factors')
        self.fr_dev = {k: v['Mkt-RF'] + v['RF'] for k, v in dev.items()}
        self.fr_dxus = {k: v['Mkt-RF'] + v['RF'] for k, v in dxu.items()}
        self.fr, self.eafe, self.eafe_loc = load_french_countries()
        self.j, self.jn = {}, {}
        for c in sorted(set(DEV23)):
            ex, n = load_jkp(c)
            self.j[c] = {k: v + self.rf[k] for k, v in ex.items() if k in self.rf}
            self.jn[c] = n
        self.reg = {}
        for r in ('developed', 'world_ex_us', 'world'):
            ex, _ = load_jkp(r)
            self.reg[r] = {k: v + self.rf[k] for k, v in ex.items() if k in self.rf}
        # 米国の配当利回り: E2（V21＝米国込み）で米国が上位3に入るかを見るためだけの近似（下の _us_dp_proxy）
        self.us_dp = self._us_dp_proxy()

    def _us_dp_proxy(self):
        """米国の配当利回りの近似: Portfolios_Formed_on_ME の Hi 30（大型株）の配当込み−配当抜きの12か月和。
        研究側の式（規模3組の時価加重）とは別の作り方。E2 で米国が上位3に入るかの判定にだけ使う"""
        def table(name, want):
            _, txt = _zip_text(M.get(FR_CSV.format(name), name=f'fr_{name}.zip'))
            out, cols, on = {}, None, False
            for line in txt.splitlines():
                cells = [c.strip() for c in line.split(',')]
                if not on:
                    if want.lower() in line.lower():
                        on = True
                    continue
                if cols is None:
                    if cells[0] == '' and len(cells) > 3:
                        cols = cells[1:]
                    continue
                if re.fullmatch(r'\d{6}', cells[0]):
                    out[int(cells[0])] = dict(zip(cols, [float(x) / 100 if float(x) > -99 else None for x in cells[1:1 + len(cols)]]))
                elif out:
                    break
            return out
        try:
            a = table('Portfolios_Formed_on_ME', 'Value Weight Returns -- Monthly')
            b = table('Portfolios_Formed_on_ME_Wout_Div', 'Value Weight Returns -- Monthly')
        except Exception as e:  # noqa
            print('米国の利回りの近似が作れない', e)
            return {}
        d = {k: a[k]['Hi 30'] - b[k]['Hi 30'] for k in a if k in b and a[k].get('Hi 30') is not None and b[k].get('Hi 30') is not None}
        return d

    # --- 信号 ---
    def dp(self, c, end, n=12):
        """end（yyyymm）までの n か月の配当リターンの和（現地通貨・配当込み−配当抜き）"""
        if c == 'usa':
            src = self.us_dp
            v = [src.get(madd(end, -i)) for i in range(n)]
            return None if any(x is None for x in v) else sum(v)
        f = self.fr[c]
        v = []
        for i in range(n):
            m = madd(end, -i)
            a, b = f['loc'].get(m), f['locx'].get(m)
            if a is None or b is None:
                return None
            v.append(a - b)
        return sum(v)

    def dp_compound(self, c, end):
        """別の定義: (Π(1+配当込み) ÷ Π(1+配当抜き)) − 1"""
        if c == 'usa':
            return self.dp(c, end)
        f = self.fr[c]
        g1 = g2 = 1.0
        for i in range(12):
            m = madd(end, -i)
            a, b = f['loc'].get(m), f['locx'].get(m)
            if a is None or b is None:
                return None
            g1 *= 1 + a; g2 *= 1 + b
        return g1 / g2 - 1

    def elig_jkp(self, c, t):
        n = self.jn.get(c, {}).get(t)
        return n is not None and n >= NMIN

    def elig_fr(self, c, t):
        Y = t // 100 if t % 100 >= 6 else t // 100 - 1
        f = self.fr.get(c, {}).get('firms', {}).get(Y)
        return f is not None and f >= NMIN

    def cum(self, r, t, a, b):
        g = 1.0
        for k in range(a, b - 1, -1):
            v = r.get(madd(t, -k))
            if v is None:
                return None
            g *= 1 + v
        return g - 1


# ───────────────────────── 売買の再生（自前・研究側と別の書き方） ─────────────────────────
GRID = mrange(197501, 202608)


def run_annual(select, ret, rm=6, K=None):
    """毎年 rm 月末に select(t) → 国のリスト（等分）。12か月は買って持つ（各国の価値を別々に積み上げ、その和の比で月次を出す）。
    欠けた国はその月から除き、残りの価値で続ける（0 と読まない）。戻り: r, 年率回転, 保有記録, 欠けの件数"""
    r, hold, turns = {}, {}, []
    vals = None          # {国: 価値}（その保有年の初めを 1/K とする）
    miss = 0
    for i in range(len(GRID) - 1):
        t, t1 = GRID[i], GRID[i + 1]
        if t % 100 == rm:
            sel = select(t)
            if sel:
                new = {c: 1 / len(sel) for c in sel}
                if vals:
                    tot = sum(vals.values())
                    old = {c: v / tot for c, v in vals.items()}
                    turns.append(sum(abs(new.get(c, 0) - old.get(c, 0)) for c in set(new) | set(old)) / 2)
                else:
                    turns.append(0.0)
                vals = dict(new)
            else:
                vals = None
        if not vals:
            continue
        got = {c: ret(c, t1) for c in vals}
        av = {c: x for c, x in got.items() if x is not None}
        if len(av) < len(got):
            miss += 1
        if not av:
            vals = None
            continue
        before = sum(vals[c] for c in av)
        after = sum(vals[c] * (1 + av[c]) for c in av)
        r[t1] = after / before - 1
        hold[t1] = {c: vals[c] / before for c in av}
        vals = {c: vals[c] * (1 + av[c]) for c in av}
    ann_turn = sum(turns) / max(1, len(r)) * 12 if r else 0.0
    return r, ann_turn, hold, miss


def run_monthly(select, ret):
    """毎月末に select(t) → 国のリスト（等分）→ t+1 のリターン。回転は漂った重みとの差"""
    r, hold, tsum = {}, {}, 0.0
    prev = None
    for i in range(len(GRID) - 1):
        t, t1 = GRID[i], GRID[i + 1]
        sel = select(t)
        if not sel:
            prev = None
            continue
        w = {c: 1 / len(sel) for c in sel}
        got = {c: ret(c, t1) for c in w}
        av = {c: x for c, x in got.items() if x is not None}
        if not av:
            prev = None
            continue
        tw = sum(w[c] for c in av)
        rp = sum(w[c] * av[c] for c in av) / tw
        if prev is not None:
            tsum += sum(abs(w.get(c, 0) - prev.get(c, 0)) for c in set(w) | set(prev)) / 2
        r[t1] = rp
        hold[t1] = {c: w[c] / tw for c in av}
        prev = {c: w[c] / tw * (1 + av[c]) / (1 + rp) for c in av}
    return r, (tsum / len(r) * 12 if r else 0.0), hold, 0


def topk(sc, K, hi=True):
    return [c for c in sorted(sc, key=lambda c: ((-sc[c]) if hi else sc[c], c))[:K]]


def after_tax_cagr(hold, ret, a=HOLD_START, z=202512, rate=0.20315, carry_years=3):
    """日本の課税口座（特定口座・売却益 20.315%・年内で損益通算・損失は3年繰越）で、保有の記録 hold{ym: {資産: 重み}} を
    なぞった場合の税引後の年率（最後に全部売って課税）。配当への課税は入れない（両者とも総リターンで再投資）。
    税は年末に口座から比例で払う（その売却で生じる二次の実現益は無視＝戦略に甘い側の近似）"""
    ms = [k for k in sorted(hold) if a <= k <= z]
    if not ms:
        return None
    pos = {}   # 資産: [価値, 取得額]
    wealth = 1.0
    real = 0.0
    carry = []  # [(年, 損失)]
    year = ms[0] // 100
    first = True

    def settle(y, final=False):
        nonlocal real, carry, pos
        gain = real
        carry = [(yy, l) for yy, l in carry if y - yy <= carry_years]
        if gain > 0:
            for i, (yy, l) in enumerate(carry):
                use = min(l, gain)
                gain -= use
                carry[i] = (yy, l - use)
            carry = [(yy, l) for yy, l in carry if l > 1e-12]
            tax = gain * rate
        else:
            carry.append((y, -gain))
            tax = 0.0
        real = 0.0
        tot = sum(v for v, _ in pos.values())
        if tax > 0 and tot > 0:
            f = 1 - tax / tot
            pos = {k: [v * f, b * f] for k, (v, b) in pos.items()}
        return tax

    for k in ms:
        if k // 100 != year:
            settle(year)
            year = k // 100
        tgt = hold[k]
        tot = sum(v for v, _ in pos.values()) if pos else 1.0
        # 月初に目標の重みへ（hold は月初の重み）。売る側は平均取得で実現益
        new = {}
        for asset in set(pos) | set(tgt):
            v, bsis = pos.get(asset, [0.0, 0.0])
            want = tot * tgt.get(asset, 0.0)
            if want < v - 1e-12:  # 売る
                sold = v - want
                real += sold - bsis * sold / v
                bsis = bsis * want / v
                v = want
            elif want > v + 1e-12:  # 買う
                bsis += want - v
                v = want
            if v > 1e-12:
                new[asset] = [v, bsis]
        pos = new
        pos = {asset: [v * (1 + ret(asset, k)), b] for asset, (v, b) in pos.items()}
    # 最後に全部売る
    for asset, (v, b) in pos.items():
        real += v - b
    tot = sum(v for v, _ in pos.values())
    tax_end = settle(year, final=True)
    final = tot - tax_end
    yrs = len(ms) / 12
    return round((final ** (1 / yrs) - 1) * 100, 2)


def bh_after_tax_cagr(r, a=HOLD_START, z=202512, rate=0.20315):
    ms = [k for k in sorted(r) if a <= k <= z]
    w = math.prod(1 + r[k] for k in ms)
    final = w - max(0.0, w - 1) * rate
    return round((final ** (12 / len(ms)) - 1) * 100, 2)


# ───────────────────────── 検証の本体 ─────────────────────────
def evaluate(r, b, ann_turn, cost):
    cpu, er = cost
    net = net_of(r, ann_turn, cpu, er)
    full, train, hold = comp(r, b), comp(r, b, z=TRAIN_END), comp(r, b, a=HOLD_START)
    hn = comp(net, b, a=HOLD_START)
    r20 = roll20(r, b)
    g, c = criteria(full, train, hold, r20, hn)
    return {'full': full, 'train': train, 'hold': hold, 'hold_net': hn, 'recent': comp(r, b, a=RECENT_START), 'roll20': r20,
            'annual_turnover': round(ann_turn, 3), 'cost_drag_pct': round((ann_turn * cost[0] + cost[1]) * 100, 3),
            'grade_mechanical': g, 'criteria': c}


def brief(e):
    if not e:
        return None
    return {k: e[k] for k in ('ex', 't', 'cagr_diff', 'from', 'to') if k in e}


def hold_share(hold, a=HOLD_START, z=None):
    ms = [k for k in hold if k >= a and (z is None or k <= z)]
    cnt, wt = {}, {}
    for k in ms:
        for c, w in hold[k].items():
            cnt[c] = cnt.get(c, 0) + 1; wt[c] = wt.get(c, 0) + w
    return {c: {'avg_w': round(wt[c] / len(ms), 3), 'months_share': round(cnt[c] / len(ms), 3)}
            for c in sorted(wt, key=lambda c: -wt[c])[:8]} if ms else None


def main():
    Dt = Data()
    out = {'angle': 'country', 'role': 'adversarial verifier', 'generated': datetime.date.today().isoformat(),
           'independence': 'mw_common からは取得（M.get）と URL の型だけ。解析・配当利回り・売買の再生・統計・合否は自前',
           'n_tested_by_researcher': N_TESTED_ANGLE}
    jr = lambda c, t: Dt.j.get(c, {}).get(t)
    fr_usd = lambda c, t: Dt.fr[c]['usd'].get(t)
    fr_loc = lambda c, t: Dt.fr[c]['loc'].get(t)
    B = {'fr_dxus': Dt.fr_dxus, 'fr_dev': Dt.fr_dev, 'jkp_dev': Dt.reg['developed'], 'jkp_usa': Dt.j['usa'],
         'eafe': Dt.eafe, 'jkp_world': Dt.reg['world'], 'fr_mkt': Dt.fmkt}

    # 点検: 相手の中身（JKP developed は米国を含むか）
    ks = [k for k in Dt.reg['developed'] if 200701 <= k <= 202512 and k in Dt.fr_dxus and k in Dt.fr_dev]
    corr = lambda a, b: ST.correlation([a[k] for k in ks], [b[k] for k in ks])
    out['benchmark_check'] = {
        'jkp_developed_corr_with_fr_dev_ex_us_2007_2025': round(corr(Dt.reg['developed'], Dt.fr_dxus), 4),
        'jkp_developed_corr_with_fr_dev_incl_us_2007_2025': round(corr(Dt.reg['developed'], Dt.fr_dev), 4),
        'cagr_2007_2025': {'jkp_developed': round(geo([Dt.reg['developed'][k] for k in ks]) * 100, 2),
                           'fr_dev_ex_us': round(geo([Dt.fr_dxus[k] for k in ks]) * 100, 2),
                           'fr_dev_incl_us': round(geo([Dt.fr_dev[k] for k in ks]) * 100, 2),
                           'jkp_usa': round(geo([Dt.j['usa'][k] for k in ks]) * 100, 2)},
        'verdict': 'JKP developed は米国抜き（French Developed_ex_US と同じ動き）。研究側の申告どおり'}

    # ── 配当利回りの年次規則（共通の組み立て） ──
    def dp_sel(univ, K, elig, sig='dp', lag_end=None, hi=True):
        def s(t):
            Y = t // 100
            end = lag_end(t) if lag_end else (Y - 1) * 100 + 12
            sc = {}
            for c in univ:
                if not elig(c, t):
                    continue
                if sig == 'dp':
                    v = Dt.dp(c, end)
                elif sig == 'dpc':
                    v = Dt.dp_compound(c, end)
                elif sig == 'yld':
                    v = Dt.fr[c]['yld'].get(Y) if c != 'usa' else None
                elif sig == 'bm':
                    v = Dt.fr[c]['bm'].get(Y) if c != 'usa' else None
                if v is not None:
                    sc[c] = v
            if len(sc) < 2 * K:
                return None
            return topk(sc, K, hi)
        return s

    C = {}
    # 1) D1_f20_dp_K3 vs French Developed_ex_US
    rD1, tD1, hD1, mD1 = run_annual(dp_sel(F20, 3, Dt.elig_jkp), jr)
    C['D1_f20_dp_K3'] = e = evaluate(rD1, B['fr_dxus'], tD1, COST_DEV)
    e['missing_months'] = mD1
    e['held_hold_period'] = hold_share(hD1)
    e['vs_fr_dev_incl_us'] = {'full': brief(comp(rD1, B['fr_dev'])), 'hold': brief(comp(rD1, B['fr_dev'], a=HOLD_START))}
    e['vs_us'] = {'full': brief(comp(rD1, B['jkp_usa'])), 'hold': brief(comp(rD1, B['jkp_usa'], a=HOLD_START))}
    e['claimed'] = {'full': [5.01, 3.32], 'train': [6.63, 2.37], 'hold': [3.6, 2.71], 'hold_cagr_diff': 3.18, 'net': 3.14, 'roll20': 1.0}

    # 2) E2_dp_K3（V21＝米国込みの21か国）vs JKP developed（米国抜き）＝登録どおりの相手、と French Developed（米国込み）
    rE2, tE2, hE2, _ = run_annual(dp_sel(V21, 3, Dt.elig_jkp), jr)
    C['E2_dp_K3'] = e = evaluate(rE2, B['jkp_dev'], tE2, COST_DEV)
    e['benchmark'] = 'JKP developed（米国抜き）'
    e['vs_fr_dev_incl_us'] = evaluate(rE2, B['fr_dev'], tE2, COST_DEV)
    e['us_months_held'] = sum(1 for k in hE2 if 'usa' in hE2[k])
    e['same_as_D1_in_hold'] = all(set(hE2[k]) == set(hD1.get(k, {})) for k in hE2 if k >= 199007)
    e['claimed'] = {'full': [4.96, 3.44], 'train': [6.08, 2.48], 'hold': [3.76, 2.81], 'hold_cagr_diff': 3.32, 'net': 3.31}

    # 3) D4_eafe_dp_K3 vs EAFE（French の国別ドル建て・社数≥20）
    rD4, tD4, hD4, mD4 = run_annual(dp_sel(EAFE19, 3, Dt.elig_fr), fr_usd)
    C['D4_eafe_dp_K3'] = e = evaluate(rD4, B['eafe'], tD4, COST_DEV)
    e['held_hold_period'] = hold_share(hD4)
    e['independent_1976_1985'] = brief(comp(rD4, B['eafe'], z=198512))
    e['sub_1976_1980'] = brief(comp(rD4, B['eafe'], z=198012))
    e['sub_1981_1985'] = brief(comp(rD4, B['eafe'], a=198101, z=198512))
    e['same_countries_as_D1_hold_share'] = round(sum(1 for k in hD4 if k >= HOLD_START and k in hD1 and set(hD4[k]) == set(hD1[k]))
                                                 / max(1, sum(1 for k in hD4 if k >= HOLD_START)), 3)
    e['claimed'] = {'full': [4.48, 3.26], 'train': [5.1, 2.46], 'hold': [3.49, 2.75], 'hold_cagr_diff': 3.06, 'net': 3.04}

    # 4) D6_f20_dp_K2
    rD6, tD6, hD6, _ = run_annual(dp_sel(F20, 2, Dt.elig_jkp), jr)
    C['D6_f20_dp_K2'] = e = evaluate(rD6, B['fr_dxus'], tD6, COST_DEV)
    e['claimed'] = {'full': [5.53, 3.07], 'train': [7.88, 2.48], 'hold': [3.49, 1.96], 'hold_cagr_diff': 2.87, 'net': 3.01}

    # 5) 勢い（毎月）
    def mom_sel(univ, K, elig, ret_src):
        def s(t):
            sc = {}
            for c in univ:
                if not elig(c, t):
                    continue
                v = Dt.cum(ret_src.get(c, {}), t, 11, 1)
                if v is not None:
                    sc[c] = v
            if len(sc) < 2 * K:
                return None
            return topk(sc, K)
        return s
    rP2, tP2, hP2, _ = run_monthly(mom_sel(DEV23, 5, Dt.elig_jkp, Dt.j), jr)
    C['P2_mom12_K5'] = e = evaluate(rP2, B['jkp_dev'], tP2, COST_DEV)
    e['benchmark'] = 'JKP developed（米国抜き）＝研究側の A の相手'
    e['vs_fr_dev_incl_us'] = evaluate(rP2, B['fr_dev'], tP2, COST_DEV)
    e['us_share_of_months_hold'] = round(sum(1 for k in hP2 if k >= HOLD_START and 'usa' in hP2[k]) / max(1, sum(1 for k in hP2 if k >= HOLD_START)), 3)
    # 米国の保有を取り除いた寄与: 米国の枠を米国外の相手で置き換えた版（米国の効きを測る）
    rP2x = {k: v - hP2[k].get('usa', 0) * (Dt.j['usa'][k] - B['jkp_dev'][k]) for k, v in rP2.items() if k in B['jkp_dev'] and k in Dt.j['usa']}
    e['us_slot_replaced_by_benchmark_vs_jkp_dev'] = {'full': brief(comp(rP2x, B['jkp_dev'])), 'hold': brief(comp(rP2x, B['jkp_dev'], a=HOLD_START))}
    e['claimed'] = {'full': [4.93, 3.02], 'train': [8.34, 3.12], 'hold': [1.33, 1.02], 'hold_cagr_diff': 1.12, 'net': 0.48}

    rE3m, tE3m, hE3m, _ = run_monthly(mom_sel(DXUS22, 3, Dt.elig_jkp, Dt.j), jr)
    C['E3_mom12_K3'] = e = evaluate(rE3m, B['fr_dxus'], tE3m, COST_DEV)
    e['claimed'] = {'full': [5.84, 3.36], 'train': [10.7, 4.03], 'hold': [1.62, 0.95], 'hold_cagr_diff': 1.33, 'net': 0.72}

    rE3b, tE3b, hE3b, _ = run_annual(dp_sel(F20, 3, Dt.elig_jkp, sig='bm'), jr)
    C['E3_bm_K3'] = e = evaluate(rE3b, B['fr_dxus'], tE3b, COST_DEV)
    e['claimed'] = {'full': [5.72, 2.98], 'train': [10.6, 3.33], 'hold': [1.48, 0.89], 'hold_cagr_diff': 0.93, 'net': 1.03}

    # 6) P7 米国と米国外の切替（12-0）
    def usrow(a, b):
        def s(t):
            g = {}
            for x in ('usa', 'world_ex_us'):
                src = Dt.j['usa'] if x == 'usa' else Dt.reg['world_ex_us']
                v = Dt.cum(src, t, a, b)
                if v is None:
                    return None
                g[x] = v
            return ['usa'] if g['usa'] >= g['world_ex_us'] else ['world_ex_us']
        return s
    rr = lambda c, t: Dt.j['usa'].get(t) if c == 'usa' else Dt.reg['world_ex_us'].get(t)
    rP7, tP7, hP7, _ = run_monthly(usrow(11, 0), rr)
    C['P7_usrow_12'] = e = evaluate(rP7, B['fr_dev'], tP7, COST_BROAD)
    e['us_share_hold'] = round(sum(1 for k in hP7 if k >= HOLD_START and 'usa' in hP7[k]) / max(1, sum(1 for k in hP7 if k >= HOLD_START)), 3)
    e['claimed'] = {'full': [1.93, 1.94], 'train': [3.67, 2.24], 'hold': [0.42, 0.4], 'hold_cagr_diff': 0.38, 'net': 0.37}

    # 再現の判定（主張と自前の差）
    for k, e in C.items():
        cl = e.get('claimed')
        if not cl:
            continue
        diffs = {'full_ex': round(e['full']['ex'] - cl['full'][0], 2), 'full_t': round(e['full']['t'] - cl['full'][1], 2),
                 'train_ex': round(e['train']['ex'] - cl['train'][0], 2), 'hold_ex': round(e['hold']['ex'] - cl['hold'][0], 2),
                 'hold_t': round(e['hold']['t'] - cl['hold'][1], 2), 'hold_net_ex': round(e['hold_net']['ex'] - cl['net'], 2)}
        e['reproduction_diff'] = diffs
        e['reproduced'] = all(abs(v) <= 0.15 for v in diffs.values())

    # ───────── 頑丈さ: 配当利回り（D1 の規則） ─────────
    R = {}
    # (a) K の隣
    R['K_grid_hold'] = {}
    for K in range(1, 9):
        r_, t_, _, _ = run_annual(dp_sel(F20, K, Dt.elig_jkp), jr)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        R['K_grid_hold'][K] = {'full': brief(ev['full']), 'train': brief(ev['train']), 'hold': brief(ev['hold']), 'hold_net_ex': ev['hold_net']['ex'], 'grade': ev['grade_mechanical']}
    # (b) 売買の月（同じ信号＝前年12月末の利回り、売買だけ1〜12月末にずらす。7〜12月は信号が古くなるだけで先読みは無い）
    R['rebalance_month_same_signal'] = {}
    for m in range(1, 13):
        r_, t_, _, _ = run_annual(dp_sel(F20, 3, Dt.elig_jkp, lag_end=lambda t: (t // 100 - 1) * 100 + 12), jr, rm=m)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        R['rebalance_month_same_signal'][m] = {'full': brief(ev['full']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    # (c) 新しい信号（その月末までの12か月の利回りで選ぶ・12か月持つ）
    R['rebalance_month_fresh_signal'] = {}
    for m in range(1, 13):
        r_, t_, _, _ = run_annual(dp_sel(F20, 3, Dt.elig_jkp, lag_end=lambda t: t), jr, rm=m)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        R['rebalance_month_fresh_signal'][m] = {'full': brief(ev['full']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    # (d) 物差しの別定義
    for sig in ('dpc', 'yld'):
        r_, t_, _, _ = run_annual(dp_sel(F20, 3, Dt.elig_jkp, sig=sig), jr)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        R[f'signal_{sig}_K3'] = {'full': brief(ev['full']), 'train': brief(ev['train']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    # (e) 一か国ずつ除く（20か国すべて）
    R['leave_one_out_hold'] = {}
    for x in F20:
        r_, t_, _, _ = run_annual(dp_sel([c for c in F20 if c != x], 3, Dt.elig_jkp), jr)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        R['leave_one_out_hold'][x] = {'full': brief(ev['full']), 'train': brief(ev['train']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    r_, t_, _, _ = run_annual(dp_sel([c for c in F20 if c not in ('nzl', 'aus')], 3, Dt.elig_jkp), jr)
    ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
    R['drop_nzl_and_aus'] = {'full': brief(ev['full']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    # 実装できた国: 2007年に iShares の国別ETFがあった15か国（NZ・愛・諾・芬・丁は 2010〜2012 年まで ETF が無い）
    etf15 = ['jpn', 'deu', 'gbr', 'can', 'aus', 'fra', 'che', 'nld', 'swe', 'esp', 'ita', 'hkg', 'sgp', 'bel', 'aut']
    r_, t_, _, _ = run_annual(dp_sel(etf15, 3, Dt.elig_jkp), jr)
    ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
    R['etf15_countries_index_returns'] = {'full': brief(ev['full']), 'train': brief(ev['train']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    # (f) 相手を『同じ国々の等分（年次・買って持つ）』に: 信号の無い小国の傾きを除く
    ew_sel = lambda t: [c for c in F20 if Dt.elig_jkp(c, t) and Dt.dp(c, (t // 100 - 1) * 100 + 12) is not None] or None
    rEW, tEW, _, _ = run_annual(ew_sel, jr)
    R['ew_f20_annual_vs_fr_dxus'] = {'full': brief(comp(rEW, B['fr_dxus'])), 'train': brief(comp(rEW, B['fr_dxus'], z=TRAIN_END)),
                                     'hold': brief(comp(rEW, B['fr_dxus'], a=HOLD_START))}
    R['D1_vs_ew_f20'] = {'full': brief(comp(rD1, rEW)), 'train': brief(comp(rD1, rEW, z=TRAIN_END)), 'hold': brief(comp(rD1, rEW, a=HOLD_START))}
    # (g) でたらめに3か国（毎年6月）を選んだ場合の分布と、D1 の順位
    random.seed(20260928)
    elig_years = {}
    for t in GRID:
        if t % 100 == 6:
            el = [c for c in F20 if Dt.elig_jkp(c, t) and Dt.dp(c, (t // 100 - 1) * 100 + 12) is not None]
            if len(el) >= 6:
                elig_years[t] = el
    sims_h, sims_f = [], []
    for _ in range(2000):
        pick = {t: random.sample(el, 3) for t, el in elig_years.items()}
        r_, _, _, _ = run_annual(lambda t: pick.get(t), jr)
        h = comp(r_, B['fr_dxus'], a=HOLD_START); f = comp(r_, B['fr_dxus'])
        sims_h.append(h['ex']); sims_f.append(f['ex'])
    sims_h.sort(); sims_f.sort()
    pct = lambda arr, x: round(sum(1 for v in arr if v < x) / len(arr), 3)
    R['random3_countries'] = {'n_sims': len(sims_h), 'hold_ex_median': sims_h[len(sims_h) // 2], 'hold_ex_p95': sims_h[int(0.95 * len(sims_h))],
                              'full_ex_median': sims_f[len(sims_f) // 2], 'full_ex_p95': sims_f[int(0.95 * len(sims_f))],
                              'D1_hold_percentile': pct(sims_h, C['D1_f20_dp_K3']['hold']['ex']),
                              'D1_full_percentile': pct(sims_f, C['D1_f20_dp_K3']['full']['ex'])}
    # (h) 区間
    b = B['fr_dxus']
    R['D1_subperiods'] = {
        'hold_2007_2015': brief(comp(rD1, b, a=200701, z=201512)), 'hold_2016_2025': brief(comp(rD1, b, a=201601)),
        'hold_ex_2025': brief(comp(rD1, b, a=HOLD_START, z=202412)),
        'full_drop_1998_2000_and_2020_2021': brief(comp(rD1, b, drop=((199801, 200012), (202001, 202112)))),
        'hold_drop_2020_2021': brief(comp(rD1, b, a=HOLD_START, drop=((202001, 202112),))),
        'train_drop_1998_2000': brief(comp(rD1, b, z=TRAIN_END, drop=((199801, 200012),))),
        'post_keppler_1992': brief(comp(rD1, b, a=199201)),
    }
    # (i) 通貨: French の現地通貨建てリターンで同じ規則（相手は EAFE の現地通貨）
    rL, tL, _, _ = run_annual(dp_sel(EAFE19, 3, Dt.elig_fr), fr_loc)
    R['D4_local_currency'] = {'full': brief(comp(rL, Dt.eafe_loc)), 'hold': brief(comp(rL, Dt.eafe_loc, a=HOLD_START))}
    # (j) 取引先（ベンダー）をそろえる: D1 の規則を French の国別ドル建てリターンで（相手 French Developed_ex_US）
    rV, tV, _, _ = run_annual(dp_sel(F20, 3, Dt.elig_jkp), fr_usd)
    R['D1_with_french_returns'] = {'full': brief(comp(rV, b)), 'hold': brief(comp(rV, b, a=HOLD_START))}
    # (k) 三分位の上−下（年次・買って持つ）
    terc = {}
    for g in ('top', 'bot'):
        def s(t, g=g):
            el = {c: Dt.dp(c, (t // 100 - 1) * 100 + 12) for c in F20 if Dt.elig_jkp(c, t)}
            el = {c: v for c, v in el.items() if v is not None}
            if len(el) < 6:
                return None
            ks_ = sorted(el, key=lambda c: (-el[c], c))
            n3 = round(len(ks_) / 3)
            return ks_[:n3] if g == 'top' else ks_[-n3:]
        terc[g], _, _, _ = run_annual(s, jr)
    ls = {k: terc['top'][k] - terc['bot'][k] for k in terc['top'] if k in terc['bot']}
    zero = {k: 0.0 for k in ls}
    R['tercile_top_minus_bottom'] = {'full': brief(comp(ls, zero)), 'train': brief(comp(ls, zero, z=TRAIN_END)), 'hold': brief(comp(ls, zero, a=HOLD_START))}
    # (l) NZ・豪州の年ごとの寄与（保有期間）
    con = {}
    for k in rD1:
        if k < HOLD_START or k not in b:
            continue
        for c, w in hD1[k].items():
            con[c] = con.get(c, 0.0) + w * (jr(c, k) - b[k])
    nh = sum(1 for k in rD1 if k >= HOLD_START and k in b)
    R['D1_contribution_hold_pct_per_year'] = {c: round(v / nh * 1200, 2) for c, v in sorted(con.items(), key=lambda x: -x[1])}
    # (m) NZ の利回りの出どころ: French の社数が 2008 年に桁で増える（MSCI→Bloomberg）
    R['nzl_firms_and_dp'] = {Y: {'firms': Dt.fr['nzl']['firms'].get(Y), 'dp_prevDec_pct': round((Dt.dp('nzl', (Y - 1) * 100 + 12) or float('nan')) * 100, 2),
                                 'yld_table_pct': round(Dt.fr['nzl']['yld'].get(Y, float('nan')) * 100, 2)} for Y in (2005, 2006, 2007, 2008, 2009, 2010, 2015, 2020, 2025)}
    out['robustness_dp'] = R

    # ───────── 頑丈さ: E3 の B（隣の K・等分・後半） ─────────
    RB = {}
    for K in (2, 3, 4, 5):
        r_, t_, _, _ = run_monthly(mom_sel(DXUS22, K, Dt.elig_jkp, Dt.j), jr)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        RB[f'E3_mom12_K{K}'] = {'hold': brief(ev['hold']), 'hold_net_ex': ev['hold_net']['ex'], 'grade': ev['grade_mechanical']}
        r_, t_, _, _ = run_annual(dp_sel(F20, K, Dt.elig_jkp, sig='bm'), jr)
        ev = evaluate(r_, B['fr_dxus'], t_, COST_DEV)
        RB[f'E3_bm_K{K}'] = {'hold': brief(ev['hold']), 'hold_net_ex': ev['hold_net']['ex'], 'grade': ev['grade_mechanical']}
    ew22 = lambda t: [c for c in DXUS22 if Dt.elig_jkp(c, t) and jr(c, madd(t, 1)) is not None] or None
    rEW22, _, _, _ = run_monthly(ew22, jr)
    RB['ew_dxus22_monthly_vs_fr_dxus'] = {'full': brief(comp(rEW22, b)), 'hold': brief(comp(rEW22, b, a=HOLD_START))}
    RB['E3_mom12_K3_vs_ew22'] = {'hold': brief(comp(rE3m, rEW22, a=HOLD_START)), 'full': brief(comp(rE3m, rEW22))}
    RB['E3_bm_K3_vs_ewF20'] = {'hold': brief(comp(rE3b, rEW, a=HOLD_START)), 'full': brief(comp(rE3b, rEW))}
    for nm, rs in (('E3_mom12_K3', rE3m), ('E3_bm_K3', rE3b), ('P7_usrow_12', rP7)):
        bb = B['fr_dev'] if nm.startswith('P7') else b
        RB[f'{nm}_halves'] = {'2007_2015': brief(comp(rs, bb, a=200701, z=201512)), '2016_end': brief(comp(rs, bb, a=201601))}
    # P7 の隣: 12-1・6-0・9-0
    for nm, (a_, b_) in {'12_1': (11, 1), '6_0': (5, 0), '9_0': (8, 0), '3_0': (2, 0)}.items():
        r_, t_, _, _ = run_monthly(usrow(a_, b_), rr)
        ev = evaluate(r_, B['fr_dev'], t_, COST_BROAD)
        RB[f'P7_usrow_{nm}'] = {'full': brief(ev['full']), 'hold': brief(ev['hold']), 'grade': ev['grade_mechanical']}
    RB['P7_train_drop_1998_2000'] = brief(comp(rP7, B['fr_dev'], z=TRAIN_END, drop=((199801, 200012),)))
    RB['P7_vs_us_hold'] = brief(comp(rP7, B['jkp_usa'], a=HOLD_START))
    out['robustness_B'] = RB

    # ───────── 税（日本の課税口座・売却益のみ）と源泉税の見積り ─────────
    TX = {}
    TX['check_rate0_equals_pretax_D1'] = [after_tax_cagr(hD1, jr, rate=0.0), round(geo([rD1[k] for k in rD1 if HOLD_START <= k <= 202512]) * 100, 2)]
    for nm, (hh, rf_, bb) in {'D1_f20_dp_K3': (hD1, jr, B['fr_dxus']), 'P7_usrow_12': (hP7, rr, B['fr_dev']),
                               'E3_mom12_K3': (hE3m, jr, B['fr_dxus']), 'E3_bm_K3': (hE3b, jr, B['fr_dxus'])}.items():
        s_at = after_tax_cagr(hh, rf_)
        b_at = bh_after_tax_cagr(bb)
        TX[nm] = {'after_tax_cagr_strategy': s_at, 'after_tax_cagr_benchmark_buy_and_hold': b_at, 'after_tax_cagr_diff': round(s_at - b_at, 2),
                  'note': '2007-01〜2025-12 の一括・売買費用と信託報酬の差は含まない（税だけの効き）'}
    # 配当の源泉税: 選んだ3か国の利回りと同じ国々の等分の利回りの差（保有期間の平均）×15%
    ex_y = []
    for Y in range(2007, 2026):
        t = Y * 100 + 6
        el = {c: Dt.dp(c, (Y - 1) * 100 + 12) for c in F20 if Dt.elig_jkp(c, t)}
        el = {c: v for c, v in el.items() if v is not None}
        top = topk(el, 3)
        ex_y.append(sum(el[c] for c in top) / 3 - sum(el.values()) / len(el))
    TX['D1_extra_dividend_yield_vs_equal_weight_pct'] = round(sum(ex_y) / len(ex_y) * 100, 2)
    TX['D1_withholding_drag_estimate_pct_per_year'] = round(sum(ex_y) / len(ex_y) * 0.15 * 100, 2)
    TX['note'] = ('源泉税: 研究側のリターン（JKP・French）は配当を税引前で再投資した総リターン。実在の国別ETFは外国の源泉税（多くは15%）を引かれる。'
                  '利回りの高い3か国を持つと、同じ国々の等分より利回りが高い分だけ余分に引かれる（時価加重の相手との差はこれより大きい）。'
                  '課税口座では配当そのものにも 20.315% がかかる（ここでは入れていない）')
    out['taxes'] = TX

    # ───────── 請求一覧に無い B の上位（E4_em_mom12_K3・保有 +3.18）も念のため ─────────
    EM24 = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
    em = {}
    emn = {}
    for c in EM24:
        try:
            ex, n = load_jkp(c)
        except Exception as e_:  # noqa
            continue
        em[c] = {k: v + Dt.rf[k] for k, v in ex.items() if k in Dt.rf}
        emn[c] = n
    exr, _ = load_jkp('emerging')
    bem = {k: v + Dt.rf[k] for k, v in exr.items() if k in Dt.rf}
    el_em = lambda c, t: (emn.get(c, {}).get(t) or 0) >= NMIN
    EX = {}
    for K in (2, 3, 4, 5):
        def s(t, K=K):
            sc = {c: Dt.cum(em[c], t, 11, 1) for c in em if el_em(c, t)}
            sc = {c: v for c, v in sc.items() if v is not None}
            return topk(sc, K) if len(sc) >= 2 * K else None
        r_, t_, h_, _ = run_monthly(s, lambda c, t: em.get(c, {}).get(t))
        ev = evaluate(r_, bem, t_, (0.0030, 0.0050))
        EX[f'E4_em_mom12_K{K}'] = {'full': brief(ev['full']), 'train': brief(ev['train']), 'hold': brief(ev['hold']), 'hold_net_ex': ev['hold_net']['ex'],
                                   'grade': ev['grade_mechanical'], 'halves': {'2007_2015': brief(comp(r_, bem, a=200701, z=201512)), '2016_end': brief(comp(r_, bem, a=201601))},
                                   'recent': brief(ev['recent'])}
    ew_em = lambda t: [c for c in em if el_em(c, t) and em[c].get(madd(t, 1)) is not None] or None
    rEWem, _, _, _ = run_monthly(ew_em, lambda c, t: em.get(c, {}).get(t))
    EX['ew_em_vs_jkp_emerging'] = {'full': brief(comp(rEWem, bem)), 'hold': brief(comp(rEWem, bem, a=HOLD_START))}
    out['extra_not_in_claim_list'] = EX

    # ───────── 多重検定 ─────────
    out['multiple_testing'] = {
        'n_variants_in_angle': N_TESTED_ANGLE,
        'bonferroni_two_sided_t_for_97': zcrit(0.05, N_TESTED_ANGLE),
        'bonferroni_two_sided_t_for_20_dividend_variants': zcrit(0.05, 20),
        'D_family_holm_p_hold_reported': {'D1_f20_dp_K3': 0.0804, 'D4_eafe_dp_K3': 0.0767, 'D6_f20_dp_K2': 0.5522},
        'bonferroni97_p_hold': {k: round(min(1.0, N_TESTED_ANGLE * p2(e['hold']['t'])), 3) for k, e in C.items()},
        'bonferroni97_p_full': {k: round(min(1.0, N_TESTED_ANGLE * p2(e['full']['t'])), 3) for k, e in C.items()},
        'note': 'D 族（配当利回り）は第1回の結果（E2_dp_K3 が米国抜きの相手に S）を見た後に作った族。保有期間は同じ国・同じ年なので新しい証拠ではない。'
                'C7 は全期間 t≥3.0 の経路でだけ通っており、その全期間は族を作る前に見ていた'}
    out['candidates'] = C
    out['verdicts'] = build_verdicts(out)
    out['summary_ja'] = SUMMARY_JA
    return out


SUMMARY_JA = [
    '主張された8本（S 4・A 1・B 3）の数字は、自前のコードで全部そのまま再現した（差 0.00）。数字の誤りは無い',
    'だが S/A の5本はどれも S/A を保てない。E2_dp_K3（S）と P2_mom12_K5（A）は米国を含む国の集合を『米国抜きの相手』と比べていた。米国込みの相手（French Developed）では両方 C（保有 +1.06%/年 t0.6 ／ −1.37%/年）',
    '配当利回り上位3か国（D1・D4・D6）は結果を見た後に作った族で、保有期間は E2 と同じ国・同じ年＝新しい証拠ではない。97本を試した角度の Bonferroni の線 t3.47 に全期間 t（3.32・3.26・3.07）は届かない',
    '脆さ: 売買時点の最新の利回りで選ぶと保有 +0.4〜+2.6%/年（6月は +1.05・t0.8）、NZ と豪州を抜くと +0.38%、三分位の上−下は +0.06%、小国を等分に持つ効きを除いた訓練期間の上乗せは t0.73、JKP より前の独立な1976〜85年は +0.37%（t0.09）',
    '→ D1・D4・D6 は B（探索どまり・証拠にしない）、E2・P2 は C。B の3本（E3 勢い・E3 割安・P7 切替）は B のまま確認したが保有 t は 0.4〜0.95 で勝ちとは言えない。P7 は日本の課税口座では税引後 −0.25%/年',
    '研究側の主の結論（米国込みの先進国市場に勝つ国選びの規則は無い）は検証でも変わらない',
]


def build_verdicts(o):
    C, R, RB, TX, MT = o['candidates'], o['robustness_dp'], o['robustness_B'], o['taxes'], o['multiple_testing']
    f = lambda e: f"{e['ex']:+.2f}%/年（t{e['t']}）"
    V = []
    d1 = C['D1_f20_dp_K3']
    fresh = R['rebalance_month_fresh_signal']
    fresh_vals = [v['hold']['ex'] for v in fresh.values()]
    common_dp = [
        f"事後の族: D 族は E2_dp_K3 の保有期間の結果を見た後に作った（事前登録3の honest_context）。保有期間の持ち物は E2 と同じ国・同じ年＝新しい証拠ではない。事前登録の誠実さの約束『保有期間の結果を見て規則を変えたら事後と明記し判定に使わない』に当たる",
        f"多重検定: この角度は {MT['n_variants_in_angle']} 本を試した。Bonferroni の両側 t の線 {MT['bonferroni_two_sided_t_for_97']} に対し全期間 t は D1 {C['D1_f20_dp_K3']['full']['t']}・D4 {C['D4_eafe_dp_K3']['full']['t']}・D6 {C['D6_f20_dp_K2']['full']['t']}（補正後 p 全期間 {MT['bonferroni97_p_full']['D1_f20_dp_K3']}・保有 {MT['bonferroni97_p_hold']['D1_f20_dp_K3']}）。D 族内 Holm でも保有 p 0.080。C7 は『全期間 t≥3.0』の字面だけで通っており、その全期間は族を作る前に見ていた",
        f"信号の鮮度: 売買する月末までの最新12か月の利回りで選ぶと保有期間 {min(fresh_vals):+.2f}〜{max(fresh_vals):+.2f}%/年（12か月中 {sum(1 for v in fresh.values() if v['grade']=='C')} か月で C）。6月末に最新の利回りなら {f(fresh[6]['hold'] if 6 in fresh else fresh['6']['hold'])}。同じ暦年の利回りを12月末にすぐ売買すると {f(fresh[12]['hold'] if 12 in fresh else fresh['12']['hold'])}、6か月待つ（D1）と +3.60、12か月待つと +3.89＝古い信号ほど良い（割安ではなく勢いの負けを避けた効き、または偶然）",
        f"物差しの定義: 複利で数えた利回り {f(R['signal_dpc_K3']['hold'])}（B）、French の年次表の Yld {f(R['signal_yld_K3']['hold'])}（B）",
        f"国への依存: 保有期間の超過 +3.60 のうち NZ が +{R['D1_contribution_hold_pct_per_year']['nzl']}。NZ を除くと {f(R['leave_one_out_hold']['nzl']['hold'])}、豪州を除くと {f(R['leave_one_out_hold']['aus']['hold'])}、両方除くと {f(R['drop_nzl_and_aus']['hold'])}（C）",
        'K の隣（下で埋める）',
    ]
    kg = R['K_grid_hold']
    kget = lambda K: kg.get(K) or kg.get(str(K))
    common_dp[-1] = 'K の隣（保有期間）: ' + '・'.join(f"K={K} {kget(K)['hold']['ex']:+.2f}({kget(K)['grade']})" for K in range(1, 9))
    common_dp += [
        f"単調さが無い: 三分位の上−下は保有期間 {f(R['tercile_top_minus_bottom']['hold'])}。同じ国々の等分（年次・買って持つ）に対する D1 の上乗せは訓練期間 {f(R['D1_vs_ew_f20']['train'])}＝訓練期間の勝ちの大半は小国を等分に持つ効き（等分 vs 相手 訓練 {f(R['ew_f20_annual_vs_fr_dxus']['train'])}）",
        "データの切れ目: French の国別は 2007 年に MSCI→Bloomberg へ替わり、配当リターンは 2006 年まで毎月ならした値（利回り÷12）、2007 年からは実際の支払い月の塊（特別配当込み）。NZ は 2007-09 の1か月で 3.99%（2007年の利回り 7.65% vs 年次表 5.25%）→ 2008〜09 年の選定が定義で入れ替わり1年で約12pt の差",
        "国の集合の後知恵: French の20か国はポルトガルとギリシャ（ユーロ危機の間も先進国・EAFE の一員で高利回りの負け組）を含まない。利回りのデータが無く量れないが、向きは戦略に有利",
        f"米国込みの市場（French Developed）には保有期間 {f(d1['vs_fr_dev_incl_us']['hold'])}、米国には {f(d1['vs_us']['hold'])}",
        f"実装: 2007 年に国別ETFがあった15か国（NZ・愛・諾・芬・丁の ETF は 2010〜12 年から）に限ると、指数のリターンでも保有 {f(R['etf15_countries_index_returns']['hold'])}（{R['etf15_countries_index_returns']['grade']}）",
    ]
    positives_dp = [
        f"再現は完全（差 0.00）。取引先をそろえても（French の国別リターン）保有 {f(R['D1_with_french_returns']['hold'])}",
        f"保有期間の前後半とも正（2007-15 {f(R['D1_subperiods']['hold_2007_2015'])}・2016- {f(R['D1_subperiods']['hold_2016_2025'])}）、2020-21 を除いても {f(R['D1_subperiods']['hold_drop_2020_2021'])}",
        f"でたらめな3か国（2000回）に対し保有期間で {R['random3_countries']['D1_hold_percentile']*100:.1f} 百分位（中央 {R['random3_countries']['hold_ex_median']:+.2f}・95% 点 {R['random3_countries']['hold_ex_p95']:+.2f}）",
        f"同じ信号のまま売買の月をずらしても保有 +2.5〜+4.0（信号の古さに依存するのは上のとおり）。日本の課税口座の売却益課税を入れても税引後 {TX['D1_f20_dp_K3']['after_tax_cagr_diff']:+.2f}%/年（費用前）。余分な源泉税は約 {TX['D1_withholding_drag_estimate_pct_per_year']}%/年",
    ]
    e2 = C['E2_dp_K3']
    V.append({'name': 'E2_dp_K3（相手＝JKP developed＝米国抜き）', 'claimed_grade': 'S', 'reproduced': e2['reproduced'],
              'key_numbers': f"再現 全期間 {f(e2['full'])}・訓練 {f(e2['train'])}・保有 {f(e2['hold'])}・幾何差 {e2['hold']['cagr_diff']:+.2f}・費用後 {e2['hold_net']['ex']:+.2f}。相手を米国込みの French Developed にすると 訓練 {f(e2['vs_fr_dev_incl_us']['train'])}・保有 {f(e2['vs_fr_dev_incl_us']['hold'])}・費用後 {e2['vs_fr_dev_incl_us']['hold_net']['ex']:+.2f} → {e2['vs_fr_dev_incl_us']['grade_mechanical']}",
              'verdict': 'refuted', 'verified_grade': 'C',
              'issues': [f"相手の取り違え: 国の集合 V21 は米国を含むのに、相手 JKP developed は米国を含まない（相関 {o['benchmark_check']['jkp_developed_corr_with_fr_dev_ex_us_2007_2025']} で French Developed_ex_US と同じ）。事前登録1の相手の説明は『米国が約半分〜7割』、全体の約束は『同じ地域の時価加重』。その相手では C（C1 も落ちる）",
                         f"米国を一度も持たなかった（{e2['us_months_held']} か月）＝1990-07 以降は D1 と同じ持ち物（{e2['same_as_D1_in_hold']}）。S は D1 と同じ一つの結果の数え直しで、D1 の脆さ（下）をそのまま持つ"] + common_dp[1:5]})
    V.append({'name': 'D1_f20_dp_K3（米国を除く20か国・相手 French Developed_ex_US）', 'claimed_grade': 'S', 'reproduced': d1['reproduced'],
              'key_numbers': f"再現 全期間 {f(d1['full'])}・訓練 {f(d1['train'])}・保有 {f(d1['hold'])}・幾何差 {d1['hold']['cagr_diff']:+.2f}・費用後 {d1['hold_net']['ex']:+.2f}・20年窓 {d1['roll20']['win_rate']}（{d1['roll20']['windows']}窓・重なる）",
              'verdict': 'downgraded to B', 'verified_grade': 'B',
              'issues': common_dp + ['良い点（反証できなかったこと）: ' + ' ／ '.join(positives_dp)]})
    d4 = C['D4_eafe_dp_K3']
    V.append({'name': 'D4_eafe_dp_K3（French/MSCI 1976〜・相手 EAFE）', 'claimed_grade': 'S', 'reproduced': d4['reproduced'],
              'key_numbers': f"再現 全期間 {f(d4['full'])}・訓練 {f(d4['train'])}・保有 {f(d4['hold'])}・費用後 {d4['hold_net']['ex']:+.2f}。独立な 1976-07〜1985-12 は {f(d4['independent_1976_1985'])}（1976-80 {f(d4['sub_1976_1980'])}・1981-85 {f(d4['sub_1981_1985'])}）",
              'verdict': 'downgraded to B', 'verified_grade': 'B',
              'issues': [f"保有期間は D1 と同じ国の組が {d4['same_countries_as_D1_hold_share']*100:.0f}% の月＝独立の確認ではない",
                         f"唯一の独立な期間（JKP より前の 1976〜85）で再現しない: {f(d4['independent_1976_1985'])}",
                         f"多重検定: 全期間 t {d4['full']['t']} は Bonferroni(97) の {MT['bonferroni_two_sided_t_for_97']} に届かない（補正後 p {MT['bonferroni97_p_full']['D4_eafe_dp_K3']}）。事後の族",
                         f"現地通貨建てなら保有 {f(R['D4_local_currency']['hold'])}＝約 +0.8%/年は通貨",
                         'D1 と同じ脆さ（信号の鮮度・NZ/豪州・K・三分位）を共有する'] })
    d6 = C['D6_f20_dp_K2']
    V.append({'name': 'D6_f20_dp_K2', 'claimed_grade': 'S', 'reproduced': d6['reproduced'],
              'key_numbers': f"再現 全期間 {f(d6['full'])}・訓練 {f(d6['train'])}・保有 {f(d6['hold'])}・費用後 {d6['hold_net']['ex']:+.2f}・2013-07〜 {f(d6['recent'])}",
              'verdict': 'downgraded to B', 'verified_grade': 'B',
              'issues': ['K の頑丈さを見るために結果の後で足した隣の値（事後）。K=1 は C、K=4 以上は B/C',
                         f"保有 t {d6['hold']['t']} は C3 の線 1.65 をかろうじて越えるだけ。全期間 t {d6['full']['t']} は Bonferroni(97) の {MT['bonferroni_two_sided_t_for_97']} に届かない・D 族内 Holm p 0.55",
                         'D1 と同じ国（NZ・豪州）への依存と信号の鮮度の脆さを共有する']})
    p2c = C['P2_mom12_K5']
    V.append({'name': 'P2_mom12_K5（相手＝JKP developed＝米国抜き）', 'claimed_grade': 'A', 'reproduced': p2c['reproduced'],
              'key_numbers': f"再現 全期間 {f(p2c['full'])}・訓練 {f(p2c['train'])}・保有 {f(p2c['hold'])}・費用後 {p2c['hold_net']['ex']:+.2f}。米国込みの相手では 保有 {f(p2c['vs_fr_dev_incl_us']['hold'])}・費用後 {p2c['vs_fr_dev_incl_us']['hold_net']['ex']:+.2f}・20年窓 {p2c['vs_fr_dev_incl_us']['roll20']['win_rate']} → C",
              'verdict': 'refuted', 'verified_grade': 'C',
              'issues': [f"相手の取り違え: 国の集合 DEV23 は米国を含み、保有期間の {p2c['us_share_of_months_hold']*100:.1f}% の月で米国を持った。米国を含まない相手と比べると、米国が勝った時代に米国を持つだけで機械的に有利",
                         f"米国の枠を相手に置き換えると保有 {f(p2c['us_slot_replaced_by_benchmark_vs_jkp_dev']['hold'])}",
                         f"米国抜きの相手に対してさえ保有 t {p2c['hold']['t']}（C3 不合格）・費用後 {p2c['hold_net']['ex']:+.2f}。A は C5（新興国・フロンティアの再現）に頼っており、フロンティアの単位はジンバブエの公定レートのハイパーインフレで汚れている",
                         '研究側の訂正後の主の相手（French Developed）でも C と研究側自身が書いている']})
    for nm, cl in (('E3_mom12_K3', '米国外の部分・勢い上位3'), ('E3_bm_K3', '米国外の部分・B/M 上位3')):
        e = C[nm]
        ks = [k for k in RB if re.fullmatch(re.escape(nm[:-1]) + r'\d', k)]
        nb = '・'.join(f"K={k[-1]} 保有 {RB[k]['hold']['ex']:+.2f} 費用後 {RB[k]['hold_net_ex']:+.2f}({RB[k]['grade']})" for k in sorted(ks))
        vs_ew = RB['E3_mom12_K3_vs_ew22'] if nm == 'E3_mom12_K3' else RB['E3_bm_K3_vs_ewF20']
        V.append({'name': f'{nm}（{cl}・相手 French Developed_ex_US）', 'claimed_grade': 'B', 'reproduced': e['reproduced'],
                  'key_numbers': f"再現 全期間 {f(e['full'])}・訓練 {f(e['train'])}・保有 {f(e['hold'])}・費用後 {e['hold_net']['ex']:+.2f}・2013-07〜 {f(e['recent'])}",
                  'verdict': 'confirmed', 'verified_grade': 'B',
                  'issues': [f"保有期間の t は {e['hold']['t']}＝0 と区別できない（B の定義どおり弱い）",
                             f"隣の K: {nb}",
                             f"同じ国々の等分に対する上乗せは保有 {f(vs_ew['hold'])}（等分そのものが相手に保有 {f(RB['ew_dxus22_monthly_vs_fr_dxus']['hold'])}）＝勝ちの半分は小国の等分",
                             f"前後半: 2007-15 {f(RB[nm + '_halves']['2007_2015'])}・2016- {f(RB[nm + '_halves']['2016_end'])}",
                             f"日本の課税口座の売却益課税だけで税引後 {TX[nm]['after_tax_cagr_diff']:+.2f}%/年（費用前）。費用 {e['cost_drag_pct']}%/年を引くと" + ('ほぼ0以下' if TX[nm]['after_tax_cagr_diff'] - e['cost_drag_pct'] < 0.3 else '正'),
                             '多重検定: 97 本の中の一本・Holm でも Bonferroni でも有意でない']})
    p7 = C['P7_usrow_12']
    V.append({'name': 'P7_usrow_12（米国と米国外の切替・相手 French Developed）', 'claimed_grade': 'B', 'reproduced': p7['reproduced'],
              'key_numbers': f"再現 全期間 {f(p7['full'])}・訓練 {f(p7['train'])}・保有 {f(p7['hold'])}・費用後 {p7['hold_net']['ex']:+.2f}・2013-07〜 {f(p7['recent'])}",
              'verdict': 'confirmed', 'verified_grade': 'B',
              'issues': [f"保有 t {p7['hold']['t']}＝0 と区別できない。後半 2016- {f(RB['P7_usrow_12_halves']['2016_end'])}",
                         f"参照期間の隣: 12-1 {f(RB['P7_usrow_12_1']['hold'])}・6-0 {f(RB['P7_usrow_6_0']['hold'])}・9-0 {f(RB['P7_usrow_9_0']['hold'])}・3-0 {f(RB['P7_usrow_3_0']['hold'])}（いずれも C）",
                         f"訓練は 1998-2000 を除いても {f(RB['P7_train_drop_1998_2000'])}（C1 は頑丈）",
                         f"日本の課税口座（年1回ほど乗り換え→売却益を毎回実現）では税引後 {TX['P7_usrow_12']['after_tax_cagr_diff']:+.2f}%/年＝買って持つ相手に負ける（NISA なら B のまま）",
                         f"米国そのものには保有 {f(RB['P7_vs_us_hold'])}。保有期間の {p7['us_share_hold']*100:.0f}% の月で米国を持っていた"]})
    return V


if __name__ == '__main__':
    o = main()
    json.dump(o, open(os.path.join(BASE, 'out', 'mw_country_verify.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    C = o['candidates']
    for k, e in C.items():
        print(k, 'full', brief(e['full']), 'train', brief(e['train']), 'hold', brief(e['hold']), 'net', e['hold_net']['ex'],
              'r20', e['roll20'] and e['roll20']['win_rate'], e['grade_mechanical'], 'repro', e.get('reproduced'), e.get('reproduction_diff'))
