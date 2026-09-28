#!/usr/bin/env python3
"""night/mw_flow_tilt.py — 『市場に勝てる歴史検証』の角度 flow_tilt（入金だけを割安な地域へ向ける積立）。
読むだけ・門の判定には不使用。

事前登録: out/mw_flow_tilt_prereg.json（C1〜C8 の線は out/mw_prereg.json・判定は mw_common.grade）
出力:     out/mw_flow_tilt.json

問い: 毎月の入金だけを、自分の過去20年に比べて配当利回りが最も高い（割安な）地域へ向け、一度も売らず入れ替えない
      積立（つみたて枠に入る形・回転0）は、円建ての毎月積立の最終額で、時価加重の全世界（オール・カントリー）と
      S&P500 の既定の積立に勝つか。1986〜2025 の月次（JKP・French・MSCI）と、JST の年次の長い歴史（1881〜2020）で。

使い方:
  python3 night/mw_flow_tilt.py --check   # データの配管だけ点検（戦略と相手の比較は出さない）
  python3 night/mw_flow_tilt.py           # 全部測って out/mw_flow_tilt.json を書く

約束（mw_common に従う）
- 月次は yyyymm・年次は年の int。リターンは小数。JKP は超過 → French RF を足して総リターンに
- 月末 t に分かる値だけで決め、月 t+1 の入金に当てる（先読みなし）
- 欠けた値は 0 と読まない（候補から外す・空欄にする）
"""
import sys, os, io, json, math, zipfile, subprocess, statistics as S, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PREREG = 'out/mw_flow_tilt_prereg.json'
PREREG2 = 'out/mw_flow_tilt_prereg2.json'
OUT = 'mw_flow_tilt.json'
FR_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}.zip'
MSCI_URL = ('https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?currency_symbol=USD&index_variant={v}'
            '&start_date=19970101&end_date=20260831&data_frequency=END_OF_MONTH&baseValue=false&index_codes={c}')
JST_URL = 'https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx?t=1763503850'

START, END = 198601, 202512          # 入金の月（JKP の終わり）
TRAIN_END, HOLD_START, RECENT_START = M.TRAIN_END, M.HOLD_START, M.RECENT_START
WIN, MINN = 240, 120                 # rel の窓（20年）と最低の月数（10年）

FEE = {'US': 0.0937, 'W': 0.0578, 'XUS': 0.11, 'JP': 0.143, 'EU': 0.20, 'EM': 0.152, 'SP': 0.0937}   # %/年
WH = {'US': 0.10, 'JP': 0.0, 'EU': 0.15, 'EM': 0.15, 'XUS': 0.13, 'SP': 0.10}                        # W は混合
TAX = 0.20315

FR_FILES = {'gbr': 'UK', 'aut': 'Austria', 'aus': 'Austrlia', 'bel': 'Belgium', 'can': 'Canada', 'dnk': 'Denmark',
            'fin': 'Finland', 'fra': 'France', 'deu': 'Germany', 'hkg': 'HongKong', 'irl': 'Ireland', 'ita': 'Italy',
            'jpn': 'Japan', 'mys': 'Malaysia', 'nld': 'Nethrlnd', 'nzl': 'NewZland', 'nor': 'Norway', 'sgp': 'Singapor',
            'esp': 'Spain', 'swe': 'Sweden', 'che': 'Swtzrlnd'}
REG = {'EUR14': (['gbr', 'aut', 'bel', 'dnk', 'fin', 'fra', 'deu', 'irl', 'ita', 'nld', 'nor', 'esp', 'swe', 'che'], 'Ind_Eur_With_UK'),
       'AP6': (['aus', 'hkg', 'jpn', 'mys', 'nzl', 'sgp'], 'Ind_Asia_Pacific'),
       'SCAN4': (['dnk', 'fin', 'nor', 'swe'], 'Ind_Scandanavia'),
       'EURXUK13': (['aut', 'bel', 'dnk', 'fin', 'fra', 'deu', 'irl', 'ita', 'nld', 'nor', 'esp', 'swe', 'che'], 'Ind_Eur_WOut_UK')}
C5_REGIONS = ('EUR14', 'AP6')

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


def r2(x, n=2):
    return None if x is None else round(x, n)


# ───────────────────────── French の .Dat（国別・地域合成） ─────────────────────────
def parse_fr_dat(txt):
    """French の国別 .Dat を節ごとに読む → {(種類, 組, 頻度): {'cols', 'data'}}（mw_country と同じ読み方の写し）"""
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


def fr_zip(name):
    return zipfile.ZipFile(io.BytesIO(M.get(FR_URL.format(name), name=f'fr_{name}.zip', max_age_days=3650)))


def col(sec, name='Mkt'):
    i = sec['cols'].index(name)
    return {k: v[i] / 100 for k, v in sec['data'].items() if i < len(v) and v[i] is not None}


# ───────────────────────── データ ─────────────────────────
class Data:
    def __init__(self):
        ff = M.ff_factors()
        self.rf, self.sp = ff['rf'], ff['mkt']
        self.usd, self.div = {}, {}
        # JKP（超過 + RF）
        self.jkp_ex = {}
        for key, reg in (('US', 'usa'), ('XUS', 'world_ex_us'), ('JP', 'jpn'), ('EM', 'emerging'), ('W', 'world')):
            ex = M.jkp_mkt(reg, 'vw')
            self.jkp_ex[key] = ex
            self.usd[key] = {k: v + self.rf[k] for k, v in ex.items() if k in self.rf}
        self.usd['SP'] = dict(self.sp)
        # French の地域合成（配当込み・配当抜き）
        zt, zx = fr_zip('F-F_International_Indices'), fr_zip('F-F_International_Indices_Wout_Div')
        self.ind_usd, self.ind_div = {}, {}
        for f in ('Ind_all', 'Ind_Eur_With_UK', 'Ind_Asia_Pacific', 'Ind_Scandanavia', 'Ind_Eur_WOut_UK', 'Ind_UK'):
            a, b = parse_fr_dat(zt.read(f + '.Dat').decode('latin-1')), parse_fr_dat(zx.read(f + '.Dat').decode('latin-1'))
            self.ind_usd[f] = col(a[('USD', 'NR', 'm')])
            lt, lx = col(a[('LOC', 'NR', 'm')]), col(b[('LOC', 'NR', 'm')])
            self.ind_div[f] = {k: lt[k] - lx[k] for k in lt if k in lx}
        self.usd['EU'] = self.ind_usd['Ind_Eur_With_UK']
        # French の国別
        zt, zx = fr_zip('F-F_International_Countries'), fr_zip('F-F_International_Countries_Wout_Div')
        self.c_usd, self.c_div, self.c_firms = {}, {}, {}
        for c, f in FR_FILES.items():
            a, b = parse_fr_dat(zt.read(f + '.Dat').decode('latin-1')), parse_fr_dat(zx.read(f + '.Dat').decode('latin-1'))
            self.c_usd[c] = col(a[('USD', 'NR', 'm')])
            lt, lx = col(a[('LOC', 'NR', 'm')]), col(b[('LOC', 'NR', 'm')])
            self.c_div[c] = {k: lt[k] - lx[k] for k in lt if k in lx}
            rt = a[('RATIO', 'NR', 'a')]
            i = rt['cols'].index('Firms')
            self.c_firms[c] = {y: v[i] for y, v in rt['data'].items() if v[i] is not None}
        # 配当のリターン（現地通貨）
        self.div['US'] = self.us_div()
        self.div['XUS'] = self.ind_div['Ind_all']
        self.div['JP'] = self.c_div['jpn']
        self.div['EU'] = self.ind_div['Ind_Eur_With_UK']
        self.div['EM'] = self.msci_div(891800)
        self.div['SP'] = self.div['US']
        # 円/ドル（月末）
        self.fx = self.fred_month_end('DEXJPUS')
        # W の米国の重み（源泉税の混合だけに使う）
        self.w_us = self.est_w_us()

    @staticmethod
    def us_div():
        """French の規模別（Lo30/Med40/Hi30）を社数×平均規模で時価加重 → 配当込み−配当抜き（月次）"""
        def tab(name, want):
            for t, v in M.french_tables(name).items():
                if t.lower().startswith(want.lower()) and v['freq'] == 'monthly':
                    return v
            raise KeyError(want)
        G = ['Lo 30', 'Med 40', 'Hi 30']
        tot, ex = tab('Portfolios_Formed_on_ME', 'Average Value Weight Returns'), tab('Portfolios_Formed_on_ME_Wout_Div', 'Average Value Weight Returns')
        nf, sz = tab('Portfolios_Formed_on_ME', 'Number of Firms'), tab('Portfolios_Formed_on_ME', 'Average Firm Size')
        out = {}
        for m in sorted(tot['data']):
            if m not in ex['data'] or m not in nf['data'] or m not in sz['data']:
                continue
            ws = st = sx = 0.0
            ok = True
            for g in G:
                n, a = nf['data'][m][nf['cols'].index(g)], sz['data'][m][sz['cols'].index(g)]
                a1, b1 = tot['data'][m][tot['cols'].index(g)], ex['data'][m][ex['cols'].index(g)]
                if None in (n, a, a1, b1):
                    ok = False; break
                w = n * a
                ws += w; st += w * a1 / 100; sx += w * b1 / 100
            if ok and ws > 0:
                out[m] = st / ws - sx / ws
        return out

    @staticmethod
    def msci_levels(code, v):
        j = json.loads(M.get(MSCI_URL.format(v=v, c=code), name=f'mwft_msci_{code}_{v}_USD.json', max_age_days=3650))
        return {x['calc_date'] // 100: x['level_eod'] for x in j['indexes']['INDEX_LEVELS']}

    def msci_div(self, code):
        g, p = self.msci_levels(code, 'GRTR'), self.msci_levels(code, 'STRD')
        out = {}
        for k in sorted(g):
            q = ym_add(k, -1)
            if q in g and k in p and q in p and g[q] and p[q]:
                out[k] = (g[k] / g[q]) / (p[k] / p[q]) - 1
        return out

    @staticmethod
    def fred_month_end(sid):
        c = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=3650).decode()
        last = {}
        for line in c.strip().splitlines()[1:]:
            d, v = line.split(',')
            if v in ('', '.'):
                continue
            k = int(d[:4]) * 100 + int(d[5:7])
            last[k] = (d, float(v)) if k not in last or d > last[k][0] else last[k]
        return {k: v for k, (_, v) in last.items()}

    def est_w_us(self):
        """world = w·usa + (1−w)·world_ex_us を月 t−12〜t−1 で最小二乗 → 月 t に使う w。最初の12か月は 1986 年の推定で置く（相手の源泉税だけ・記録）"""
        U, X, W = self.jkp_ex['US'], self.jkp_ex['XUS'], self.jkp_ex['W']
        ks = sorted(set(U) & set(X) & set(W))
        w, fit = {}, []
        for i, t in enumerate(ks):
            if i < 12:
                continue
            win = ks[i - 12:i]
            xs = [U[k] - X[k] for k in win]; ys = [W[k] - X[k] for k in win]
            sxx = sum(x * x for x in xs)
            if sxx <= 0:
                continue
            b = sum(x * y for x, y in zip(xs, ys)) / sxx
            w[t] = b
            res = [y - b * x for x, y in zip(xs, ys)]
            fit.append(1 - sum(e * e for e in res) / sum((y - S.mean(ys)) ** 2 for y in ys) if sum((y - S.mean(ys)) ** 2 for y in ys) > 0 else None)
        first = w[min(w)]
        for t in ks:
            if t not in w:
                w[t] = first
        self.w_fit = [f for f in fit if f is not None]
        return w

    # --- 変換 ---
    def fxr(self, m):
        a, b = self.fx.get(m), self.fx.get(ym_add(m, -1))
        return None if a is None or b is None else a / b - 1

    def ret(self, b, m, net=False, jpy=True):
        """器 b の月 m のリターン（net=信託報酬と源泉税を引く、jpy=円建て）。欠けたら None"""
        r = self.usd.get(b, {}).get(m)
        if r is None:
            return None
        if net:
            r -= FEE[b] / 100 / 12
            if b == 'W':
                du, dx, w = self.div['US'].get(m), self.div['XUS'].get(m), self.w_us.get(m)
                if du is None or dx is None or w is None:
                    return None
                r -= w * WH['US'] * du + (1 - w) * WH['XUS'] * dx
            else:
                d = self.div[b].get(m)
                if d is None:
                    if WH[b] == 0:
                        d = 0.0  # 源泉税率0の器は配当が分からなくても差し引きは0（配当そのものを0と読んでいるのではない）
                    else:
                        return None
                r -= WH[b] * d
        if jpy:
            f = self.fxr(m)
            if f is None:
                return None
            r = (1 + r) * (1 + f) - 1
        return r


# ───────────────────────── 信号 ─────────────────────────
def dy_series(div):
    out = {}
    for t in sorted(div):
        v = [div.get(ym_add(t, -k)) for k in range(12)]
        if all(x is not None for x in v):
            out[t] = sum(v)
    return out


def rel_series(dy, win=WIN, minn=MINN):
    out = {}
    for t in sorted(dy):
        h = [dy[s] for s in (ym_add(t, -k) for k in range(win)) if s in dy]
        if len(h) >= minn:
            md = S.median(h)
            if md > 0:
                out[t] = dy[t] / md
    return out


def mom_series(r):
    out = {}
    for t in sorted(r):
        v = [r.get(ym_add(t, -k)) for k in range(1, 12)]
        if all(x is not None for x in v):
            g = 1.0
            for x in v:
                g *= 1 + x
            out[t] = g - 1
    return out


def pick_top(rel, cands, t, order):
    sc = [(rel[c][t], -order.index(c), c) for c in cands if t in rel.get(c, {})]
    if not sc:
        return None
    return max(sc)[2]


def veto_mom(mom, cands, t):
    """mom が空欄の候補は外し、下位 ⌊n/3⌋ を外す"""
    have = [c for c in cands if t in mom.get(c, {})]
    n = len(have)
    k = n // 3
    if k == 0:
        return have
    worst = sorted(have, key=lambda c: (mom[c][t], c))[:k]
    return [c for c in have if c not in worst]


# ───────────────────────── 入金の道 ─────────────────────────
def simulate(choice, retf, start, end, move_to=None, events=None):
    """choice: {決める月 t: {器: 重み}}。入金は月 m の初めに choice[m−1]。retf(器, m) → リターン。
    move_to: 持っている器のデータが終わったら、その持ち分をこの器へ置き換える（R だけ・事前登録どおり）。無ければ止める。
    → (時間加重リターン {m}, 最後の持ち分 {器: 値}, 器ごとの入金 {器: 合計})"""
    H, flows, twr = {}, {}, {}
    V = 0.0
    for m in months(start, end):
        w = choice.get(ym_add(m, -1))
        if w is None:
            raise RuntimeError(f'入金の向け先が空: {m}')
        for b, x in w.items():
            H[b] = H.get(b, 0.0) + x
            flows[b] = flows.get(b, 0.0) + x
        base = V + 1.0
        for b in list(H):
            if retf(b, m) is None and move_to is not None and b != move_to:
                H[move_to] = H.get(move_to, 0.0) + H.pop(b)
                if events is not None:
                    events.append([m, b])
        for b in H:
            r = retf(b, m)
            if r is None:
                raise RuntimeError(f'リターンが欠けた: {b} {m}')
            H[b] *= 1 + r
        V = sum(H.values())
        twr[m] = V / base - 1
    return twr, H, flows


def dca_ratio(choice, retf, bench_b, start, n, move_to=None):
    """start から n か月の積立の最終額（戦略・相手・入金の合計）"""
    H, B, C = {}, 0.0, 0
    for m in months(start, ym_add(start, n - 1)):
        w = choice[ym_add(m, -1)]
        for b, x in w.items():
            H[b] = H.get(b, 0.0) + x
        B += 1.0; C += 1
        for b in list(H):
            if move_to is not None and b != move_to and retf(b, m) is None:
                H[move_to] = H.get(move_to, 0.0) + H.pop(b)
        for b in H:
            H[b] *= 1 + retf(b, m)
        B *= 1 + retf(bench_b, m)
    return sum(H.values()), B, C


def after_tax(W, C):
    return W - TAX * max(0.0, W - C)


def dca_windows(choice, retf, bench_b, first, last_end, years=20, step=12, move_to=None):
    n = years * 12
    out = []
    s = first
    while ym_add(s, n - 1) <= last_end:
        w, b, c = dca_ratio(choice, retf, bench_b, s, n, move_to)
        out.append((s, w / b, after_tax(w, c) / after_tax(b, c)))
        s = ym_add(s, step)
    if not out:
        return None
    def summ(i):
        v = sorted(x[i] for x in out)
        worst = min(out, key=lambda x: x[i]); best = max(out, key=lambda x: x[i])
        return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median_ratio': round(v[len(v) // 2], 4),
                'worst': [worst[0], round(worst[i], 4)], 'best': [best[0], round(best[i], 4)]}
    span = (ym_add(out[-1][0], n - 1) // 100) - out[0][0] // 100 + 1
    return {'nisa': summ(1), 'taxable_exit': summ(2), 'years': years, 'step_months': step,
            'independent_windows_approx': round(span / years, 1), 'first_start': out[0][0], 'last_start': out[-1][0]}


def runs(choice, keys):
    """月ごとの向け先を連続の塊へ（報告用）"""
    out, cur, a = [], None, None
    for t in keys:
        w = choice[t]
        lab = '+'.join(f'{b}{int(round(x * 100))}' if x < 1 else b for b, x in sorted(w.items()))
        if lab != cur:
            if cur is not None:
                out.append([a, prev, cur])
            cur, a = lab, t
        prev = t
    out.append([a, prev, cur])
    return out


# ───────────────────────── 主の族 P ─────────────────────────
ORDER1 = ['US', 'XUS']
ORDER3 = ['US', 'JP', 'EU', 'EM']


def build_signals(D):
    dy = {b: dy_series(D.div[b]) for b in ('US', 'XUS', 'JP', 'EU', 'EM')}
    rel = {b: rel_series(dy[b]) for b in dy}
    mom = {b: mom_series(D.usd[b]) for b in ('US', 'JP', 'EU', 'EM')}
    return dy, rel, mom


def p_choices(rel, mom):
    decide = months(ym_add(START, -1), ym_add(END, -1))
    ch = {'F1_US_vs_XUS': {}, 'F2_half_world_half_F1': {}, 'F3_4regions_top1': {}, 'F4_F3_mom_veto': {}}
    fallback = {k: 0 for k in ch}
    for t in decide:
        p = pick_top(rel, ORDER1, t, ORDER1)
        if p is None:
            ch['F1_US_vs_XUS'][t] = {'W': 1.0}; fallback['F1_US_vs_XUS'] += 1
            ch['F2_half_world_half_F1'][t] = {'W': 1.0}; fallback['F2_half_world_half_F1'] += 1
        else:
            ch['F1_US_vs_XUS'][t] = {p: 1.0}
            ch['F2_half_world_half_F1'][t] = {'W': 0.5, p: 0.5}
        p3 = pick_top(rel, ORDER3, t, ORDER3)
        if p3 is None:
            ch['F3_4regions_top1'][t] = {'W': 1.0}; fallback['F3_4regions_top1'] += 1
        else:
            ch['F3_4regions_top1'][t] = {p3: 1.0}
        cands = [c for c in ORDER3 if t in rel.get(c, {})]
        keep = veto_mom(mom, cands, t)
        p4 = pick_top(rel, keep, t, ORDER3)
        if p4 is None:
            ch['F4_F3_mom_veto'][t] = {'W': 1.0}; fallback['F4_F3_mom_veto'] += 1
        else:
            ch['F4_F3_mom_veto'][t] = {p4: 1.0}
    return ch, fallback


# ───────────────────────── 再現 R（国の単位・独立の地域） ─────────────────────────
def r_region(D, reg):
    cs, bench = REG[reg]
    dy = {c: dy_series(D.c_div[c]) for c in cs}
    rel = {c: rel_series(dy[c]) for c in cs}
    mom = {c: mom_series(D.c_usd[c]) for c in cs}
    decide = months(ym_add(START, -1), ym_add(END, -1))
    out = {'top1': {}, 'half': {}, 'top1_mom': {}}
    fb = {k: 0 for k in out}
    for t in decide:
        Y = t // 100
        el = [c for c in cs if (D.c_firms[c].get(Y) or 0) >= 20 and t in rel[c] and ym_add(t, 1) in D.c_usd[c]]
        p = pick_top(rel, el, t, cs)
        if p is None:
            out['top1'][t] = {'B': 1.0}; out['half'][t] = {'B': 1.0}; fb['top1'] += 1; fb['half'] += 1
        else:
            out['top1'][t] = {p: 1.0}; out['half'][t] = {'B': 0.5, p: 0.5}
        keep = veto_mom(mom, el, t)
        p2 = pick_top(rel, keep, t, cs)
        if p2 is None:
            out['top1_mom'][t] = {'B': 1.0}; fb['top1_mom'] += 1
        else:
            out['top1_mom'][t] = {p2: 1.0}
    B = D.ind_usd[bench]

    def retf(b, m):
        return B.get(m) if b == 'B' else D.c_usd[b].get(m)
    res = {}
    for rule, ch in out.items():
        ev = []
        twr, H, flows = simulate(ch, retf, START, END, move_to='B', events=ev)
        tot = sum(flows.values())
        res[rule] = {'full': M.excess_stats(twr, B, START, END), 'train': M.excess_stats(twr, B, START, TRAIN_END),
                     'hold': M.excess_stats(twr, B, HOLD_START, END), 'fallback_months': fb[rule], 'data_end_moves': ev,
                     'dca20': dca_windows(ch, retf, 'B', START, END, move_to='B'),
                     'flow_share': {b: round(v / tot, 3) for b, v in sorted(flows.items(), key=lambda x: -x[1])}}
    return res


_CBM = {}


def country_bm_monthly(c):
    """国の B/M の月次（年次の B/M(Y)〔×100 を小数へ〕を Y 年7月から・現地の配当抜きの価格で動かす）"""
    if c not in _CBM:
        zt, zx = fr_zip('F-F_International_Countries'), fr_zip('F-F_International_Countries_Wout_Div')
        f = FR_FILES[c]
        rt = parse_fr_dat(zt.read(f + '.Dat').decode('latin-1'))[('RATIO', 'NR', 'a')]
        i = rt['cols'].index('B/M')
        bm = {y: v[i] / 100 for y, v in rt['data'].items() if v[i] is not None}
        px = price_index(col(parse_fr_dat(zx.read(f + '.Dat').decode('latin-1'))[('LOC', 'NR', 'm')]))
        _CBM[c] = bm_monthly(bm, px, 197501, END)
    return _CBM[c]


def r_region2(D, reg, rule):
    """事前登録2の C5: 同じ仕組みを地域の中の国で（米ドル・費用なし・相手は地域の時価加重）"""
    cs, bench = REG[reg]
    rel = {c: rel_series(dy_series(D.c_div[c])) for c in cs}
    mom = {c: mom_series(D.c_usd[c]) for c in cs}
    rbm = {c: rel_series(country_bm_monthly(c)) for c in cs} if rule == 'bm_top1' else None
    decide = months(ym_add(START, -1), ym_add(END, -1))
    ch, fb = {}, 0
    for t in decide:
        Y = t // 100
        base = [c for c in cs if (D.c_firms[c].get(Y) or 0) >= 20 and ym_add(t, 1) in D.c_usd[c]]
        w = None
        if rule in ('top1', 'top3'):
            el = sorted([c for c in base if t in rel[c]], key=lambda c: (-rel[c][t], c))
            K = 1 if rule == 'top1' else 3
            if len(el) >= K:
                w = {c: 1 / K for c in el[:K]}
        elif rule == 'mom_top1':
            el = [c for c in base if t in mom[c]]
            if el:
                w = {max(el, key=lambda c: (mom[c][t], c)): 1.0}
        elif rule == 'vm_top1':
            el = [c for c in base if t in rel[c] and t in mom[c]]
            if el:
                pr, pm = pct_rank({c: rel[c][t] for c in el}), pct_rank({c: mom[c][t] for c in el})
                w = {max(el, key=lambda c: ((pr[c] + pm[c]) / 2, rel[c][t])): 1.0}
        elif rule == 'agree':
            el = [c for c in base if t in rel[c] and t in mom[c]]
            if el:
                a = max(el, key=lambda c: (rel[c][t], c)); b = max(el, key=lambda c: (mom[c][t], c))
                w = {a: 1.0} if a == b else {'B': 1.0}
        elif rule == 'bm_top1':
            el = [c for c in base if t in rbm[c]]
            if el:
                w = {max(el, key=lambda c: (rbm[c][t], c)): 1.0}
        if w is None:
            w = {'B': 1.0}; fb += 1
        ch[t] = w
    B = D.ind_usd[bench]

    def retf(b, m):
        return B.get(m) if b == 'B' else D.c_usd[b].get(m)
    twr, H, flows = simulate(ch, retf, START, END, move_to='B')
    return {'full': M.excess_stats(twr, B, START, END), 'hold': M.excess_stats(twr, B, HOLD_START, END), 'fallback_months': fb,
            'dca20': dca_windows(ch, retf, 'B', START, END, move_to='B')}


# ───────────────────────── JST（年次・長い歴史） ─────────────────────────
C16 = 'AUS BEL CHE DEU DNK ESP FIN FRA GBR ITA JPN NLD NOR PRT SWE USA'.split()


def jst_load():
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


class JST:
    """mw_deep_history.JST と同じ H（米ドルへヘッジした形）の定義の写し"""
    def __init__(self, D):
        self.D = D

    def g(self, c, Y, k):
        return self.D.get(c, {}).get(Y, {}).get(k)

    def r(self, c, Y):
        eq = self.g(c, Y, 'eq_tr')
        if eq is None:
            return None
        a, b = self.g(c, Y, 'cpi'), self.g(c, Y - 1, 'cpi')
        inf = a / b - 1 if a is not None and b not in (None, 0) else None
        if inf is None or inf >= 1.0:
            return None
        bl, bu = self.g(c, Y, 'bill_rate'), self.g('USA', Y, 'bill_rate')
        if bl is None or bu is None:
            return None
        return (1 + eq) / (1 + bl) * (1 + bu) - 1

    def gw(self, c, Y):
        g, x = self.g(c, Y, 'gdp'), self.g(c, Y, 'xrusd')
        return g / x if g and x and g > 0 and x > 0 else None

    def dp(self, c, Y):
        v = self.g(c, Y, 'eq_dp')
        return v if v is not None and v > 0 else None


def jst_build(J, y0=1871, y1=2020):
    """→ ret[器][Y]（USA・XUS・B・EW・各国）と dp[器][Y]"""
    ret, dp = {'USA': {}, 'XUS': {}, 'B': {}, 'EW': {}}, {'USA': {}, 'XUS': {}}
    for c in C16:
        ret.setdefault(c, {}); dp.setdefault(c, {})
        for Y in range(y0 - 1, y1 + 1):
            r = J.r(c, Y)
            if r is not None:
                ret[c][Y] = r
            d = J.dp(c, Y)
            if d is not None:
                dp[c][Y] = d
    ret['USA'] = dict(ret['USA'])
    for Y in range(y0 - 1, y1 + 1):
        # 年 Y の重みで年 Y+1 のリターン
        for key, univ in (('XUS', [c for c in C16 if c != 'USA']), ('B', C16)):
            num = den = 0.0
            for c in univ:
                w = J.gw(c, Y)
                if w and (Y + 1) in ret[c]:
                    num += w * ret[c][Y + 1]; den += w
            if den > 0:
                ret[key][Y + 1] = num / den
        ew = [ret[c][Y + 1] for c in C16 if Y in ret[c] and (Y + 1) in ret[c]]
        if ew:
            ret['EW'][Y + 1] = sum(ew) / len(ew)
        num = den = 0.0
        for c in C16:
            if c == 'USA':
                continue
            w = J.gw(c, Y)
            if w and Y in dp[c]:
                num += w * dp[c][Y]; den += w
        if den > 0:
            dp['XUS'][Y] = num / den
    dp['USA'] = dict(dp['USA'])
    return ret, dp


def jst_rel(dp, Y, key):
    d = dp.get(key, {}).get(Y)
    h = [dp[key][y] for y in range(Y - 19, Y + 1) if y in dp.get(key, {})]
    if d is None or len(h) < 10:
        return None
    md = S.median(h)
    return d / md if md > 0 else None


def jst_choices(ret, dp, y_from, y_to):
    """年 Y 末に決めて年 Y+1 の入金へ（Y = y_from−1 … y_to−1）"""
    ch = {k: {} for k in ('J1_US_vs_XUS15', 'J2_half_world_half_J1', 'J3_country_top1_rel', 'J4_country_top3_dp')}
    for Y in range(y_from - 1, y_to):
        ru, rx = jst_rel(dp, Y, 'USA'), jst_rel(dp, Y, 'XUS')
        if ru is None and rx is None:
            p = 'B'
        elif rx is None or (ru is not None and ru >= rx):
            p = 'USA'
        else:
            p = 'XUS'
        ch['J1_US_vs_XUS15'][Y] = {p: 1.0}
        ch['J2_half_world_half_J1'][Y] = {'B': 1.0} if p == 'B' else {'B': 0.5, p: 0.5}
        sc = [(jst_rel(dp, Y, c), c) for c in C16 if Y in ret[c]]
        sc = [(v, c) for v, c in sc if v is not None]
        ch['J3_country_top1_rel'][Y] = {max(sc, key=lambda x: (x[0], x[1]))[1]: 1.0} if sc else {'B': 1.0}
        sc = sorted(((dp[c][Y], c) for c in C16 if Y in ret[c] and Y in dp[c]), key=lambda x: (-x[0], x[1]))
        ch['J4_country_top3_dp'][Y] = {c: 1 / 3 for _, c in sc[:3]} if len(sc) >= 3 else {'B': 1.0}
    return ch


def jst_simulate(choice, ret, y_from, y_to, impute='xus', fee=0.0):
    """年初に1を入れる。持っている国の年 Y のリターンが無効なら XUS で置く（worst なら有効な国で最悪）"""
    H, twr = {}, {}
    V = 0.0
    ev = {'imputed_holding_years': 0, 'imputed_wealth_share_max': 0.0}
    for Y in range(y_from, y_to + 1):
        for b, x in choice[Y - 1].items():
            H[b] = H.get(b, 0.0) + x
        base = V + 1.0
        worst = min((ret[c][Y] for c in C16 if Y in ret[c]), default=None)
        imp_val = 0.0
        for b in H:
            r = ret[b].get(Y)
            if r is None:
                r = ret['XUS'].get(Y) if impute == 'xus' else worst
                ev['imputed_holding_years'] += 1
                imp_val += H[b]
                if r is None:
                    raise RuntimeError(f'JST: 置く値も無い {b} {Y}')
            H[b] *= 1 + r - fee
        V = sum(H.values())
        if imp_val and base:
            ev['imputed_wealth_share_max'] = max(ev['imputed_wealth_share_max'], round(imp_val / base, 4))
        twr[Y] = V / base - 1
    return twr, H, ev


def jst_dca(choice, ret, bench, y0, years, fee=0.0):
    H, B = {}, 0.0
    for Y in range(y0, y0 + years):
        for b, x in choice[Y - 1].items():
            H[b] = H.get(b, 0.0) + x
        B += 1
        for b in H:
            r = ret[b].get(Y)
            if r is None:
                r = ret['XUS'][Y]
            H[b] *= 1 + r - fee
        B *= 1 + ret[bench][Y]
    return sum(H.values()) / B


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
    ks = sorted(k for k in set(s) & set(b) if a <= k <= z)
    if len(ks) < 6:
        return None
    ex = [s[k] - b[k] for k in ks]
    gs = math.exp(math.fsum(math.log1p(s[k]) for k in ks) / len(ks)) - 1
    gb = math.exp(math.fsum(math.log1p(b[k]) for k in ks) / len(ks)) - 1
    t = nw_t_small(ex, lag)
    return {'from': ks[0], 'to': ks[-1], 'years': len(ks), 'ex_ann': round(S.mean(ex) * 100, 2),
            't': round(t, 2) if t is not None else None, 'p': round(M.p_two(t), 4) if t is not None else None,
            'cagr_diff': round((gs - gb) * 100, 2), 'win_years': sum(1 for x in ex if x > 0)}


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
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def summ_ratios(lst):
    if not lst:
        return None
    v = sorted(r for _, r in lst)
    return {'windows': len(lst), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median_ratio': round(v[len(v) // 2], 4),
            'worst': [min(lst, key=lambda x: x[1])[0], round(min(v), 4)], 'best': [max(lst, key=lambda x: x[1])[0], round(max(v), 4)]}


# ───────────────────────── 探索の第2族（事前登録2） ─────────────────────────
X_FEE_COUNTRY, X_WH_COUNTRY = 0.50, 0.15


def price_index(ex):
    """配当抜きの月次 → 水準 {ym}（最初の月の前月末を1・月が抜けたら以後を切る＝0 と読まない）"""
    p, lv = {}, 1.0
    ks = sorted(ex)
    if not ks:
        return p
    prev = ym_add(ks[0], -1)
    p[prev] = 1.0
    for k in ks:
        if k != ym_add(prev, 1):
            break
        lv *= 1 + ex[k]; p[k] = lv; prev = k
    return p


def us_ex_div():
    """US の配当抜きの月次（規模別の時価加重・us_div と同じ重み）"""
    def tab(name, want):
        for t, v in M.french_tables(name).items():
            if t.lower().startswith(want.lower()) and v['freq'] == 'monthly':
                return v
        raise KeyError(want)
    G = ['Lo 30', 'Med 40', 'Hi 30']
    ex = tab('Portfolios_Formed_on_ME_Wout_Div', 'Average Value Weight Returns')
    nf, sz = tab('Portfolios_Formed_on_ME', 'Number of Firms'), tab('Portfolios_Formed_on_ME', 'Average Firm Size')
    out = {}
    for m in sorted(ex['data']):
        if m not in nf['data'] or m not in sz['data']:
            continue
        ws = sx = 0.0
        ok = True
        for g in G:
            n, a, b1 = nf['data'][m][nf['cols'].index(g)], sz['data'][m][sz['cols'].index(g)], ex['data'][m][ex['cols'].index(g)]
            if None in (n, a, b1):
                ok = False; break
            ws += n * a; sx += n * a * b1 / 100
        if ok and ws > 0:
            out[m] = sx / ws
    return out


def us_bm_annual():
    """US の B/M(Y) = Σ_g (Sum of BE / Sum of ME)_g × 重み_g（Y 年7月の社数×平均規模）"""
    tabs = M.french_tables('Portfolios_Formed_on_BE-ME')
    ratio = next(v for t, v in tabs.items() if t.lower().startswith('sum of be') and v['freq'] == 'annual')
    nf = next(v for t, v in tabs.items() if t.lower().startswith('number of firms') and v['freq'] == 'monthly')
    sz = next(v for t, v in tabs.items() if t.lower().startswith('average firm size') and v['freq'] == 'monthly')
    out = {}
    for y, row in ratio['data'].items():
        m = y * 100 + 7
        if m not in nf['data'] or m not in sz['data']:
            continue
        num = den = 0.0
        ok = False
        for g in ['<= 0', 'Lo 30', 'Med 40', 'Hi 30']:
            s = row[ratio['cols'].index(g)]
            n, a = nf['data'][m][nf['cols'].index(g)], sz['data'][m][sz['cols'].index(g)]
            if s is None or n is None or a is None or n <= 0:
                continue
            num += s * n * a; den += n * a
            if g != '<= 0':
                ok = True
        if ok and den > 0:
            out[y] = num / den
    return out


def bm_monthly(bm_y, px, t0, t1):
    """B/M(t) = B/M(Y) × P(Y−1年12月) ÷ P(t)。B/M(Y) は Y 年7月末から（それまでは Y−1）"""
    out = {}
    for t in months(t0, t1):
        Y = t // 100 if t % 100 >= 7 else t // 100 - 1
        b, p0, p1 = bm_y.get(Y), px.get((Y - 1) * 100 + 12), px.get(t)
        if b is None or p0 is None or p1 is None or p1 <= 0 or b <= 0:
            continue
        out[t] = b * p0 / p1
    return out


def pct_rank(vals):
    items = sorted(vals.items(), key=lambda x: (x[1], x[0]))
    n = len(items)
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[items[k][0]] = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def dca_two(chA, chB, retf, start, n, move_to=None):
    """二つの入金の道の最終額の比（A ÷ B）"""
    wa, _, c = dca_ratio(chA, retf, 'W', start, n, move_to)
    wb, _, _ = dca_ratio(chB, retf, 'W', start, n, move_to)
    return wa / wb, after_tax(wa, c) / after_tax(wb, c)


def dca_two_windows(chA, chB, retf, first, last_end, years=20, step=12, move_to=None):
    n = years * 12
    lst, s = [], first
    while ym_add(s, n - 1) <= last_end:
        a, b = dca_two(chA, chB, retf, s, n, move_to)
        lst.append((s, a, b))
        s = ym_add(s, step)
    if not lst:
        return None
    return {'nisa': summ_ratios([(x[0], x[1]) for x in lst]), 'taxable_exit': summ_ratios([(x[0], x[2]) for x in lst])}


def hold_worse(a, b):
    """二つの道の保有期間の要約から、小さい方（厳しい側）を grade に渡す形へ"""
    if not a or not b:
        return None
    return {'ex_ann': min(a['ex_ann'], b['ex_ann']), 'cagr_diff': min(a['cagr_diff'], b['cagr_diff']),
            't': min(a['t'] if a['t'] is not None else -99, b['t'] if b['t'] is not None else -99),
            'p': max(a['p'] if a.get('p') is not None else 1, b['p'] if b.get('p') is not None else 1), 'from_paths': ['1986〜の道の2007〜', '2007〜新しく始めた道']}


def jst_dca_two(chA, chB, ret, y0, years):
    def run(ch):
        H = {}
        for Y in range(y0, y0 + years):
            for b, x in ch[Y - 1].items():
                H[b] = H.get(b, 0.0) + x
            for b in H:
                r = ret[b].get(Y)
                if r is None:
                    r = ret['XUS'][Y]
                H[b] *= 1 + r
        return sum(H.values())
    return run(chA) / run(chB)


def run_part2(D, dy, rel, mom, chP, gross, net, Wg, Wn, SPn, decide, ret, dp, chA_J, chB_J):
    log('── 事前登録2（探索） ──')
    P2 = json.load(open(os.path.join(M.BASE, PREREG2)))
    # --- 追加の信号 ---
    mom = dict(mom)
    mom['XUS'] = mom_series(D.usd['XUS'])
    # B/M（US・JP・EU）
    zt, zx = fr_zip('F-F_International_Indices'), fr_zip('F-F_International_Indices_Wout_Div')
    eu_rt = parse_fr_dat(zt.read('Ind_Eur_With_UK.Dat').decode('latin-1'))[('RATIO', 'NR', 'a')]
    eu_bm = {y: v[0] for y, v in eu_rt['data'].items() if v and v[0] is not None}
    eu_px = price_index(col(parse_fr_dat(zx.read('Ind_Eur_With_UK.Dat').decode('latin-1'))[('LOC', 'NR', 'm')]))
    zc, zcx = fr_zip('F-F_International_Countries'), fr_zip('F-F_International_Countries_Wout_Div')
    jp_rt = parse_fr_dat(zc.read('Japan.Dat').decode('latin-1'))[('RATIO', 'NR', 'a')]
    i = jp_rt['cols'].index('B/M')
    jp_bm = {y: v[i] / 100 for y, v in jp_rt['data'].items() if v[i] is not None}
    jp_px = price_index(col(parse_fr_dat(zcx.read('Japan.Dat').decode('latin-1'))[('LOC', 'NR', 'm')]))
    us_px = price_index(us_ex_div())
    us_bm = us_bm_annual()
    bmm = {'US': bm_monthly(us_bm, us_px, 192701, END), 'JP': bm_monthly(jp_bm, jp_px, 197501, END), 'EU': bm_monthly(eu_bm, eu_px, 197501, END)}
    relbm = {b: rel_series(v) for b, v in bmm.items()}
    sanity2 = {'bm_levels': {b: {str(k): r2(v.get(k), 3) for k in (198612, 198912, 200003, 200902, 202512)} for b, v in bmm.items()},
               'relbm_first': {b: min(v) if v else None for b, v in relbm.items()}}
    # 国（米国外先進国・French）
    ctry = [c for c in FR_FILES]
    cdy = {c: dy_series(D.c_div[c]) for c in ctry}
    crel = {c: rel_series(cdy[c]) for c in ctry}
    for c in ctry:
        k = 'c_' + c
        D.usd[k] = D.c_usd[c]; D.div[k] = D.c_div[c]; FEE[k] = X_FEE_COUNTRY; WH[k] = X_WH_COUNTRY
    # --- 選び方 ---
    X = {k: {} for k in P2['families']['X_monthly']['strategies']}
    fb = {k: 0 for k in X}
    N = {}
    for t in decide:
        wu = D.w_us[ym_add(t, 1)]
        N[t] = {'US': wu, 'XUS': 1 - wu}
        # X1
        cands = [c for c in ORDER3 if t in rel.get(c, {}) and t in mom.get(c, {})]
        if cands:
            pr, pm = pct_rank({c: rel[c][t] for c in cands}), pct_rank({c: mom[c][t] for c in cands})
            best = max(cands, key=lambda c: ((pr[c] + pm[c]) / 2, rel[c][t]))
            X['X1_VM4_top1'][t] = {best: 1.0}
        else:
            X['X1_VM4_top1'][t] = {'W': 1.0}; fb['X1_VM4_top1'] += 1
        # X2・X3
        v = pick_top(rel, ORDER1, t, ORDER1) if all(t in rel[b] for b in ORDER1) else None
        mm = max(ORDER1, key=lambda b: mom[b][t]) if all(t in mom[b] for b in ORDER1) else None
        if v is not None and mm is not None and v == mm:
            X['X2_agree_US_XUS'][t] = {v: 1.0}
        else:
            X['X2_agree_US_XUS'][t] = {'W': 1.0}
            if v is None or mm is None:
                fb['X2_agree_US_XUS'] += 1
        if mm is None:
            X['X3_mom_US_XUS'][t] = {'W': 1.0}; fb['X3_mom_US_XUS'] += 1
        else:
            X['X3_mom_US_XUS'][t] = {mm: 1.0}
        # X4
        p4 = pick_top(relbm, ['US', 'JP', 'EU'], t, ['US', 'JP', 'EU'])
        if p4 is None:
            X['X4_relBM3_top1'][t] = {'W': 1.0}; fb['X4_relBM3_top1'] += 1
        else:
            X['X4_relBM3_top1'][t] = {p4: 1.0}
        # X5・X6（米国は時価の重み、米国外は国で）
        Y = t // 100
        el = [c for c in ctry if (D.c_firms[c].get(Y) or 0) >= 20 and t in crel[c] and ym_add(t, 1) in D.c_usd[c]]
        order = sorted(el, key=lambda c: (-crel[c][t], c))
        for name, K in (('X5_UScap_XUScountry_top3', 3), ('X6_UScap_XUScountry_top1', 1)):
            if len(order) >= K:
                w = {'US': wu}
                for c in order[:K]:
                    w['c_' + c] = (1 - wu) / K
                X[name][t] = w
            else:
                X[name][t] = {'US': wu, 'XUS': 1 - wu}; fb[name] += 1
        # X7
        if t in rel['US'] and t in rel['XUS']:
            a, b = wu * rel['US'][t], (1 - wu) * rel['XUS'][t]
            X['X7_prop_US_XUS'][t] = {'US': a / (a + b), 'XUS': b / (a + b)}
        else:
            X['X7_prop_US_XUS'][t] = {'W': 1.0}; fb['X7_prop_US_XUS'] += 1

    # 先進国の時価加重（X5・X6 の報告の相手・gross）
    D.usd['DEV'] = {k: v + D.rf[k] for k, v in M.jkp_mkt('developed', 'vw').items() if k in D.rf}
    # --- 中立の道 N ---
    twNg, _, _ = simulate(N, gross, START, END)
    twNn, _, _ = simulate(N, net, START, END)
    rep = {'N_neutral_flow_vs_W': {'gross_full': M.excess_stats(twNg, Wg, START, END), 'net_full': M.excess_stats(twNn, Wn, START, END),
                                   'net_hold': M.excess_stats(twNn, Wn, HOLD_START, END), 'dca20_vs_W': dca_windows(N, net, 'W', START, END)},
           'P_vs_neutral_flow_dca20_posthoc': {}}
    for name, c in chP.items():
        rep['P_vs_neutral_flow_dca20_posthoc'][name] = dca_two_windows(c, N, net, START, END)
    log('N vs W', rep['N_neutral_flow_vs_W']['net_full']['ex_ann'], rep['N_neutral_flow_vs_W']['dca20_vs_W']['nisa'])
    log('P vs N（事後）', {k: v['nisa']['median_ratio'] for k, v in rep['P_vs_neutral_flow_dca20_posthoc'].items()})
    # --- X を測る ---
    DEVg = {m: gross('DEV', m) for m in months(START, END)}
    tested, pv = [], {}
    XR = {}
    for name, c in X.items():
        mt = 'XUS' if name.startswith(('X5', 'X6')) else None
        ev = []
        twg, _, flows = simulate(c, gross, START, END, move_to=mt, events=ev)
        twn, Hn, _ = simulate(c, net, START, END, move_to=mt)
        fr_g, _, _ = simulate(c, gross, HOLD_START, END, move_to=mt)
        fr_n, _, _ = simulate(c, net, HOLD_START, END, move_to=mt)
        e = {'gross': {k: M.excess_stats(twg, Wg, a, z) for k, (a, z) in (('full', (START, END)), ('train', (START, TRAIN_END)), ('hold', (HOLD_START, END)), ('recent', (RECENT_START, END)))},
             'net': {k: M.excess_stats(twn, Wn, a, z) for k, (a, z) in (('full', (START, END)), ('train', (START, TRAIN_END)), ('hold', (HOLD_START, END)), ('recent', (RECENT_START, END)))},
             'fresh2007_gross': M.excess_stats(fr_g, Wg, HOLD_START, END), 'fresh2007_net': M.excess_stats(fr_n, Wn, HOLD_START, END),
             'fresh2007_net_vs_sp500': M.excess_stats(fr_n, SPn, HOLD_START, END)}
        tot = sum(flows.values()); totH = sum(Hn.values())
        x = {'name': name, 'family': 'X（探索・事前登録2）', 'primary': False, 'exploratory': True, 'graded': True,
             'description': P2['families']['X_monthly']['strategies'][name], **e,
             'roll20_lump_net': M.rolling(twn, Wn, 20),
             'dca20_world': dca_windows(c, net, 'W', START, END, 20, 12, move_to=mt),
             'dca20_world_step1': dca_windows(c, net, 'W', START, END, 20, 1, move_to=mt),
             'dca20_sp500': dca_windows(c, net, 'SP', START, END, 20, 12, move_to=mt),
             'dca15_world_step1': dca_windows(c, net, 'W', START, END, 15, 1, move_to=mt),
             'dca10_world_step1': dca_windows(c, net, 'W', START, END, 10, 1, move_to=mt),
             'dca20_vs_neutral_flow': dca_two_windows(c, N, net, START, END, move_to=mt),
             'flow_share': {b: round(v / tot, 3) for b, v in sorted(flows.items(), key=lambda x: -x[1])[:10]},
             'final_holding_share': {b: round(v / totH, 3) for b, v in sorted(Hn.items(), key=lambda x: -x[1])[:10]},
             'fallback_months': fb[name], 'data_end_moves': ev[:20]}
        if not name.startswith(('X5', 'X6')):
            x['choice_runs'] = runs(c, decide)
        else:
            x['vs_developed_gross'] = {'full': M.excess_stats(twg, DEVg, START, END), 'hold': M.excess_stats(twg, DEVg, HOLD_START, END),
                                       'dca20': dca_windows(c, gross, 'DEV', START, END, 20, 12, move_to=mt)['nisa']}
            cnt = {}
            for t in decide:
                for b in c[t]:
                    if b.startswith('c_'):
                        cnt[b[2:]] = cnt.get(b[2:], 0) + 1
            x['country_months_chosen'] = dict(sorted(cnt.items(), key=lambda z: -z[1]))
        XR[name] = x
        pv[name] = max(e['net']['hold']['p'] or 1, e['fresh2007_net']['p'] or 1)
        log(name, 'train', e['gross']['train']['ex_ann'], e['gross']['train']['t'], '| hold', e['gross']['hold']['ex_ann'], e['gross']['hold']['t'],
            '| fresh', e['fresh2007_net']['ex_ann'], e['fresh2007_net']['t'], '| DCA20 W', x['dca20_world']['nisa']['median_ratio'], x['dca20_world']['nisa']['win_rate'],
            '| vsN', x['dca20_vs_neutral_flow']['nisa']['median_ratio'])
    # R の再現（C5・事前登録2の mapping）。X7 は N/A
    xmap = {'X1_VM4_top1': 'vm_top1', 'X2_agree_US_XUS': 'agree', 'X3_mom_US_XUS': 'mom_top1', 'X4_relBM3_top1': 'bm_top1',
            'X5_UScap_XUScountry_top3': 'top3', 'X6_UScap_XUScountry_top1': 'top1'}
    R2 = {reg: {rule: r_region2(D, reg, rule) for rule in sorted(set(xmap.values()))} for reg in C5_REGIONS}
    rep['R2_replication'] = {reg: {rule: {'full': v['full'], 'hold': v['hold'], 'dca20': v['dca20']['nisa'] if v['dca20'] else None, 'fallback_months': v['fallback_months']}
                                   for rule, v in rr.items()} for reg, rr in R2.items()}
    log('R2', {reg: {rule: (v['full']['ex_ann'], v['full']['t']) for rule, v in rr.items()} for reg, rr in R2.items()})
    holm = M.holm(pv)
    for name, x in XR.items():
        hw = hold_worse(x['gross']['hold'], x['fresh2007_gross'])
        cw = hold_worse(x['net']['hold'], x['fresh2007_net'])
        lump, dcaw = x['roll20_lump_net'], x['dca20_world']['nisa']
        roll_for_grade = {'win_rate': min(lump['win_rate'] if lump else 0.0, dcaw['win_rate'] if dcaw else 0.0),
                          'lump_win_rate': lump['win_rate'] if lump else None, 'dca_win_rate': dcaw['win_rate'] if dcaw else None}
        repl = None
        if name in xmap:
            rule = xmap[name]
            det = {reg: R2[reg][rule]['full']['ex_ann'] for reg in C5_REGIONS}
            repl = {'regions': len(C5_REGIONS), 'positive': sum(1 for v in det.values() if v > 0), 'rule': rule, 'detail': det}
        g, crit = M.grade(x['gross']['full'], x['gross']['train'], hw, roll_for_grade, cost_hold=cw, repl=repl, family_holm_p=holm.get(name))
        x.update({'hold_for_grade': hw, 'cost_hold_for_grade': cw, 'roll20_for_grade': roll_for_grade, 'repl': repl,
                  'family_holm_p': holm.get(name), 'holm_input_p': pv[name], 'grade': g, 'criteria': crit})
        tested.append(x)
        log(name, 'grade', g, crit)

    # --- Y（JST） ---
    def y_choices(y_from, y_to):
        out = {'Y1_country_VM_top3': {}, 'Y2_agree_US_XUS15': {}}
        for Y in range(y_from - 1, y_to):
            sc = {c: (dp[c][Y], ret[c][Y]) for c in C16 if Y in ret[c] and Y in dp[c]}
            if len(sc) >= 3:
                pd_, pm_ = pct_rank({c: v[0] for c, v in sc.items()}), pct_rank({c: v[1] for c, v in sc.items()})
                top = sorted(sc, key=lambda c: (-(pd_[c] + pm_[c]) / 2, -pd_[c], c))[:3]
                out['Y1_country_VM_top3'][Y] = {c: 1 / 3 for c in top}
            else:
                out['Y1_country_VM_top3'][Y] = {'B': 1.0}
            j1 = chB_J['J1_US_vs_XUS15'].get(Y) or chA_J['J1_US_vs_XUS15'].get(Y)
            v = list(j1)[0]
            ru, rx = ret['USA'].get(Y), ret['XUS'].get(Y)
            mm = None if ru is None or rx is None else ('USA' if ru >= rx else 'XUS')
            out['Y2_agree_US_XUS15'][Y] = {v: 1.0} if (mm is not None and v == mm) else {'B': 1.0}
        return out
    yA, yB = y_choices(1881, 1925), y_choices(1926, 2020)
    # 中立の道（GDP の重みで入金・売らない）
    def ngdp(y_from, y_to):
        out = {}
        for Y in range(y_from - 1, y_to):
            ws = {c: JST_GW[c][Y] for c in C16 if Y in JST_GW[c]}
            tot = sum(ws.values())
            out[Y] = {c: w / tot for c, w in ws.items()}
        return out
    NA, NB = ngdp(1881, 1925), ngdp(1926, 2020)
    Bb = ret['B']
    twNB, _, _ = jst_simulate(NB, ret, 1926, 2020)
    twNA, _, _ = jst_simulate(NA, ret, 1881, 1925)
    rep['N_gdp_flow_vs_B'] = {'B_1926_2020': M.excess_stats(twNB, Bb, 1926, 2020, per_year=1, lag=2), 'A_1881_1925': M.excess_stats(twNA, Bb, 1881, 1925, per_year=1, lag=2),
                              'dca20_B': summ_ratios([(y0, jst_dca_two(NB, {Y: {'B': 1.0} for Y in range(1925, 2020)}, ret, y0, 20)) for y0 in range(1926, 2002)])}
    rep['J_vs_N_gdp_dca20_posthoc'] = {name: {'B': summ_ratios([(y0, jst_dca_two(chB_J[name], NB, ret, y0, 20)) for y0 in range(1926, 2002)]),
                                              'A': summ_ratios([(y0, jst_dca_two(chA_J[name], NA, ret, y0, 20)) for y0 in range(1881, 1907)])} for name in chB_J}
    log('N_gdp vs B', rep['N_gdp_flow_vs_B']['B_1926_2020']['ex_ann'], rep['N_gdp_flow_vs_B']['dca20_B'])
    log('J vs N_gdp（事後）', {k: (v['B']['median_ratio'], v['B']['win_rate'], v['A']['median_ratio']) for k, v in rep['J_vs_N_gdp_dca20_posthoc'].items()})
    YR, ypv = {}, {}
    for name in yA:
        twA, _, evA = jst_simulate(yA[name], ret, 1881, 1925)
        twB, _, evB = jst_simulate(yB[name], ret, 1926, 2020)
        twBn, _, _ = jst_simulate(yB[name], ret, 1926, 2020, fee=0.0005)
        fr, _, _ = jst_simulate(yB[name], ret, 2007, 2020)
        frn, _, _ = jst_simulate(yB[name], ret, 2007, 2020, fee=0.0005)
        e = {'A_1881_1925': M.excess_stats(twA, Bb, 1881, 1925, per_year=1, lag=2), 'full_1926_2020': M.excess_stats(twB, Bb, 1926, 2020, per_year=1, lag=2),
             'train_1926_2006': M.excess_stats(twB, Bb, 1926, 2006, per_year=1, lag=2), 'hold_2007_2020': short_stats(twB, Bb, 2007, 2020),
             'hold_2007_2020_net': short_stats(twBn, Bb, 2007, 2020), 'fresh2007': short_stats(fr, Bb, 2007, 2020), 'fresh2007_net': short_stats(frn, Bb, 2007, 2020)}
        dcaB = [(y0, jst_dca(yB[name], ret, 'B', y0, 20)) for y0 in range(1926, 2002)]
        x = {'name': name, 'family': 'Y（探索・JST・事前登録2）', 'primary': False, 'exploratory': True, 'graded': True,
             'description': P2['families']['Y_JST']['strategies'][name], **e, 'roll20_lump_B': roll_annual(twB, Bb, 20),
             'dca20_B_path': summ_ratios(dcaB), 'dca20_A_path': summ_ratios([(y0, jst_dca(yA[name], ret, 'B', y0, 20)) for y0 in range(1881, 1907)]),
             'dca20_vs_N_gdp_B': summ_ratios([(y0, jst_dca_two(yB[name], NB, ret, y0, 20)) for y0 in range(1926, 2002)]),
             'dca20_vs_N_gdp_A': summ_ratios([(y0, jst_dca_two(yA[name], NA, ret, y0, 20)) for y0 in range(1881, 1907)]),
             'imputation_A': evA, 'imputation_B': evB}
        YR[name] = x
        ypv[name] = max(e['hold_2007_2020_net']['p'] or 1, e['fresh2007_net']['p'] or 1)
        log(name, 'A', e['A_1881_1925']['ex_ann'], e['A_1881_1925']['t'], '| train', e['train_1926_2006']['ex_ann'], e['train_1926_2006']['t'],
            '| hold', e['hold_2007_2020']['ex_ann'], '| fresh', e['fresh2007']['ex_ann'], '| DCA B', x['dca20_B_path']['median_ratio'], x['dca20_B_path']['win_rate'],
            '| vsN', x['dca20_vs_N_gdp_B']['median_ratio'])
    yholm = M.holm(ypv)
    for name, x in YR.items():
        hw = hold_worse(x['hold_2007_2020'], x['fresh2007'])
        cw = hold_worse(x['hold_2007_2020_net'], x['fresh2007_net'])
        lump, dcab = x['roll20_lump_B'], x['dca20_B_path']
        roll_for_grade = {'win_rate': min(lump['win_rate'] if lump else 0.0, dcab['win_rate'] if dcab else 0.0)}
        repl = {'regions': 1, 'positive': 1 if x['A_1881_1925']['ex_ann'] > 0 else 0, 'what': '道 A（1881〜1925）'}
        g, crit = M.grade(x['full_1926_2020'], x['train_1926_2006'], hw, roll_for_grade, cost_hold=cw, repl=repl, family_holm_p=yholm.get(name))
        x.update({'hold_for_grade': hw, 'cost_hold_for_grade': cw, 'roll20_for_grade': roll_for_grade, 'repl': repl, 'family_holm_p': yholm.get(name), 'grade': g, 'criteria': crit})
        tested.append(x)
        log(name, 'grade', g, crit)
    last = decide[-1]
    rep['_now'] = {k: X[k][last] for k in X if not k.startswith(('X5', 'X6'))}
    rep['_now'].update({k: {b: round(v, 3) for b, v in X[k][last].items()} for k in X if k.startswith(('X5', 'X6'))})
    rep['sanity2'] = sanity2
    rep['prereg2_commit'] = git_sha(PREREG2)
    return tested, rep


JST_GW = {}


# ───────────────────────── 点検（--check） ─────────────────────────
def check():
    D = Data()
    for b in ('US', 'XUS', 'JP', 'EM', 'W', 'EU', 'SP'):
        ks = sorted(D.usd[b]); log('ret', b, ks[0], ks[-1], len(ks))
    for b, d in D.div.items():
        ks = sorted(d); log('div', b, ks[0], ks[-1], len(ks))
    dy, rel, mom = build_signals(D)
    for b in rel:
        ks = sorted(rel[b]); log('rel 空欄でない最初', b, ks[0] if ks else None, ks[-1] if ks else None, len(ks))
    ks = sorted(D.fx); log('fx', ks[0], ks[-1])
    log('w_us の当てはまり R2 中央', r2(S.median(D.w_fit), 4), '最小', r2(min(D.w_fit), 4))
    for c in FR_FILES:
        ks = sorted(D.c_usd[c]); log('国', c, ks[0], ks[-1])


def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-1', '--format=%h', '--', path], cwd=M.BASE, text=True).strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── 本体 ─────────────────────────
def main():
    t0 = time.time()
    D = Data()
    dy, rel, mom = build_signals(D)
    ch, fallback = p_choices(rel, mom)
    decide = months(ym_add(START, -1), ym_add(END, -1))

    gross = lambda b, m: D.ret(b, m, net=False, jpy=True)
    net = lambda b, m: D.ret(b, m, net=True, jpy=True)
    Wg = {m: gross('W', m) for m in months(START, END)}
    Wn = {m: net('W', m) for m in months(START, END)}
    SPn = {m: net('SP', m) for m in months(START, END)}

    sanity = {}
    # 1) 米国の市場の再現（mw_common の検算値 10.4%・11.1%）
    sanity['french_mkt_cagr_full'] = r2(M.cagr(D.sp) * 100); sanity['french_mkt_cagr_2007'] = r2(M.cagr(M.window(D.sp, HOLD_START)) * 100)
    ks = sorted(set(D.usd['US']) & set(D.sp)); ks = [k for k in ks if START <= k <= END]
    sanity['jkp_usa_vs_french_mkt'] = {'corr': r2(M.corr([D.usd['US'][k] for k in ks], [D.sp[k] for k in ks]), 4),
                                      'cagr_jkp': r2(M.cagr([D.usd['US'][k] for k in ks]) * 100), 'cagr_french': r2(M.cagr([D.sp[k] for k in ks]) * 100)}
    # 2) 世界 = w·米国 + (1−w)·米国外 の恒等式
    sanity['w_us_fit'] = {'r2_median': r2(S.median(D.w_fit), 5), 'r2_min': r2(min(D.w_fit), 4),
                          'w_us': {str(k): r2(D.w_us.get(k), 3) for k in (198701, 199012, 200003, 201012, 202512)}}
    # 3) 配当利回りの水準（見た目の常識）
    sanity['dy_levels_pct'] = {b: {str(k): r2(dy[b].get(k, float('nan')) * 100) if k in dy[b] else None
                                   for k in (198612, 198912, 200003, 200902, 201212, 202512)} for b in dy}
    # 4) 円: JKP の日本（円換算）と French の日本（現地通貨）
    zt = fr_zip('F-F_International_Countries')
    jl = col(parse_fr_dat(zt.read('Japan.Dat').decode('latin-1'))[('LOC', 'NR', 'm')])
    kk = [m for m in months(START, END) if m in jl and gross('JP', m) is not None]
    sanity['jpn_jkp_in_yen_vs_french_local'] = {'corr': r2(M.corr([gross('JP', m) for m in kk], [jl[m] for m in kk]), 4),
                                                'cagr_jkp_yen': r2(M.cagr([gross('JP', m) for m in kk]) * 100), 'cagr_french_local': r2(M.cagr([jl[m] for m in kk]) * 100)}
    # 5) 模型の検算: いつも W へ → 超過ちょうど0／時価の重みで US・XUS へ分ける → ほぼ0
    allw = {t: {'W': 1.0} for t in decide}
    tw, _, _ = simulate(allw, gross, START, END)
    sanity['sim_all_world_max_abs_diff'] = max(abs(tw[m] - Wg[m]) for m in tw)
    capw = {t: {'US': D.w_us[ym_add(t, 1)], 'XUS': 1 - D.w_us[ym_add(t, 1)]} for t in decide}
    tw, _, _ = simulate(capw, gross, START, END)
    es = M.excess_stats(tw, Wg, START, END)
    sanity['sim_capweight_flow_vs_world'] = {'ex_ann': es['ex_ann'], 'te': es['te'], 'cagr_diff': es['cagr_diff'],
                                             'note': '入金を時価の重み（推定）で US・XUS に分けて売らない道は、重みが漂う分だけ W とずれる（0 に近いはず）'}
    w_ratio = dca_windows(allw, gross, 'W', START, END)
    sanity['dca_all_world_ratio'] = w_ratio['nisa']['median_ratio']
    # 6) 先読みなしの構造: 向け先は月 t−1 までの信号だけ（rel・mom のキーは決める月）
    sanity['no_lookahead'] = '入金の月 m の向け先は choice[m−1]＝月 m−1 末の rel・mom だけで決まる（rel は月 m−1 までの配当のリターン、mom は m−12〜m−2）'
    log('sanity', json.dumps(sanity, ensure_ascii=False)[:1500])

    # ── P の族 ──
    tested, pvals = [], {}
    P = {}
    for name, c in ch.items():
        twg, Hg, flows = simulate(c, gross, START, END)
        twn, Hn, _ = simulate(c, net, START, END)
        e = {'gross': {k: M.excess_stats(twg, Wg, a, z) for k, (a, z) in (('full', (START, END)), ('train', (START, TRAIN_END)), ('hold', (HOLD_START, END)), ('recent', (RECENT_START, END)))},
             'net': {k: M.excess_stats(twn, Wn, a, z) for k, (a, z) in (('full', (START, END)), ('train', (START, TRAIN_END)), ('hold', (HOLD_START, END)), ('recent', (RECENT_START, END)))}}
        fresh, _, _ = simulate(c, net, HOLD_START, END)
        tot = sum(flows.values()); totH = sum(Hn.values())
        P[name] = {
            'name': name, 'family': 'P（主）', 'primary': True, 'graded': True,
            'description': json.load(open(os.path.join(M.BASE, PREREG)))['families']['P_primary']['strategies'][name],
            **e,
            'roll20_lump_net': M.rolling(twn, Wn, 20),
            'roll20_lump_gross': M.rolling(twg, Wg, 20),
            'dca20_world': dca_windows(c, net, 'W', START, END, 20, 12),
            'dca20_world_step1': dca_windows(c, net, 'W', START, END, 20, 1),
            'dca20_sp500': dca_windows(c, net, 'SP', START, END, 20, 12),
            'dca20_sp500_step1': dca_windows(c, net, 'SP', START, END, 20, 1),
            'dca15_world_step1': dca_windows(c, net, 'W', START, END, 15, 1),
            'dca10_world_step1': dca_windows(c, net, 'W', START, END, 10, 1),
            'dca10_sp500_step1': dca_windows(c, net, 'SP', START, END, 10, 1),
            'fresh_start_2007_net': M.excess_stats(fresh, Wn, HOLD_START, END),
            'fresh_start_2007_net_vs_sp500': M.excess_stats(fresh, SPn, HOLD_START, END),
            'vs_sp500_net': {k: M.excess_stats(twn, SPn, a, z) for k, (a, z) in (('full', (START, END)), ('train', (START, TRAIN_END)), ('hold', (HOLD_START, END)))},
            'flow_share': {b: round(v / tot, 3) for b, v in sorted(flows.items(), key=lambda x: -x[1])},
            'flow_share_hold': None,
            'final_holding_share': {b: round(v / totH, 3) for b, v in sorted(Hn.items(), key=lambda x: -x[1])},
            'fallback_months': fallback[name],
            'choice_runs': runs(c, decide),
        }
        fh = {}
        for t in decide:
            if ym_add(t, 1) >= HOLD_START:
                for b, x in c[t].items():
                    fh[b] = fh.get(b, 0) + x
        P[name]['flow_share_hold'] = {b: round(v / sum(fh.values()), 3) for b, v in sorted(fh.items(), key=lambda x: -x[1])}
        pvals[name] = e['net']['hold']['p'] if e['net']['hold'] and e['net']['hold']['p'] is not None else None
        log(name, 'gross full', e['gross']['full']['ex_ann'], e['gross']['full']['t'], '| train', e['gross']['train']['ex_ann'], e['gross']['train']['t'],
            '| hold', e['gross']['hold']['ex_ann'], e['gross']['hold']['t'], '| net hold', e['net']['hold']['ex_ann'],
            '| DCA20 W', P[name]['dca20_world']['nisa'], '| DCA20 SP', P[name]['dca20_sp500']['nisa']['median_ratio'])

    # ── R（再現・C5） ──
    R = {}
    for reg in REG:
        R[reg] = r_region(D, reg)
        log('R', reg, {k: (v['full']['ex_ann'], v['full']['t'], v['hold']['ex_ann']) for k, v in R[reg].items()})
    mapping = {'F1_US_vs_XUS': 'top1', 'F2_half_world_half_F1': 'half', 'F3_4regions_top1': 'top1', 'F4_F3_mom_veto': 'top1_mom'}

    holm = M.holm(pvals)
    for name, x in P.items():
        rule = mapping[name]
        pos = sum(1 for reg in C5_REGIONS if R[reg][rule]['full'] and R[reg][rule]['full']['ex_ann'] > 0)
        repl = {'regions': len(C5_REGIONS), 'positive': pos, 'rule': rule,
                'detail': {reg: {'full_ex': R[reg][rule]['full']['ex_ann'], 'full_t': R[reg][rule]['full']['t'], 'hold_ex': R[reg][rule]['hold']['ex_ann'] if R[reg][rule]['hold'] else None} for reg in C5_REGIONS}}
        lump, dcaw = x['roll20_lump_net'], x['dca20_world']['nisa']
        roll_for_grade = {'win_rate': min(lump['win_rate'] if lump else 0.0, dcaw['win_rate'] if dcaw else 0.0),
                          'lump_win_rate': lump['win_rate'] if lump else None, 'dca_win_rate': dcaw['win_rate'] if dcaw else None}
        g, crit = M.grade(x['gross']['full'], x['gross']['train'], x['gross']['hold'], roll_for_grade, cost_hold=x['net']['hold'],
                          repl=repl, family_holm_p=holm.get(name))
        x.update({'repl': repl, 'roll20_for_grade': roll_for_grade, 'family_holm_p': holm.get(name), 'grade': g, 'criteria': crit})
        tested.append(x)
        log(name, 'grade', g, crit)

    # ── J（JST） ──
    Jd = JST(jst_load())
    ret, dp = jst_build(Jd)
    for c in C16:  # 事前登録2の中立の道（GDP の重みで入金）用: 年 Y に GDP の重みがあり年 Y のリターンが有効な国
        JST_GW[c] = {Y: Jd.gw(c, Y) for Y in range(1869, 2021) if Jd.gw(c, Y) and Y in ret[c]}
    chA = jst_choices(ret, dp, 1881, 1925)
    chB = jst_choices(ret, dp, 1926, 2020)
    Jres, jp = {}, {}
    for name in chA:
        twA, _, evA = jst_simulate(chA[name], ret, 1881, 1925)
        twB, HB, evB = jst_simulate(chB[name], ret, 1926, 2020)
        twBw, _, _ = jst_simulate(chB[name], ret, 1926, 2020, impute='worst')
        twBn, _, _ = jst_simulate(chB[name], ret, 1926, 2020, fee=0.0005)
        Bb = ret['B']
        e = {'A_1881_1925': M.excess_stats(twA, Bb, 1881, 1925, per_year=1, lag=2),
             'full_1926_2020': M.excess_stats(twB, Bb, 1926, 2020, per_year=1, lag=2),
             'train_1926_2006': M.excess_stats(twB, Bb, 1926, 2006, per_year=1, lag=2),
             'hold_2007_2020': short_stats(twB, Bb, 2007, 2020, lag=1),
             'hold_2007_2020_net': short_stats(twBn, Bb, 2007, 2020, lag=1),
             'full_1926_2020_worst_impute': M.excess_stats(twBw, Bb, 1926, 2020, per_year=1, lag=2),
             'vs_EW_full_1926_2020': M.excess_stats(twB, ret['EW'], 1926, 2020, per_year=1, lag=2),
             'vs_EW_A_1881_1925': M.excess_stats(twA, ret['EW'], 1881, 1925, per_year=1, lag=2),
             'vs_USA_full_1926_2020': M.excess_stats(twB, ret['USA'], 1926, 2020, per_year=1, lag=2)}
        dcaB = [(y0, jst_dca(chB[name], ret, 'B', y0, 20)) for y0 in range(1926, 2020 - 20 + 2)]
        dcaA = [(y0, jst_dca(chA[name], ret, 'B', y0, 20)) for y0 in range(1881, 1925 - 20 + 2)]
        dcaUS = [(y0, jst_dca(chB[name], ret, 'USA', y0, 20)) for y0 in range(1926, 2020 - 20 + 2)]
        rollB = roll_annual(twB, Bb, 20)
        fl = {}
        for Y in range(1925, 2020):
            for b, x in chB[name][Y].items():
                fl[b] = fl.get(b, 0) + x
        Jres[name] = {'name': name, 'family': 'J（JST の長い歴史・年次）', 'primary': False, 'graded': True,
                      'description': json.load(open(os.path.join(M.BASE, PREREG)))['families']['J_long_view']['strategies'][name],
                      **e, 'roll20_lump_B': rollB,
                      'dca20_B_path': summ_ratios(dcaB), 'dca20_A_path': summ_ratios(dcaA), 'dca20_B_vs_USA': summ_ratios(dcaUS),
                      'dca20_B_windows_touching_2007': summ_ratios([x for x in dcaB if x[0] >= 1988]),
                      'dca20_B_windows_ending_by_2006': summ_ratios([x for x in dcaB if x[0] + 19 <= 2006]),
                      'imputation_A': evA, 'imputation_B': evB,
                      'flow_share_B': {b: round(v / sum(fl.values()), 3) for b, v in sorted(fl.items(), key=lambda x: -x[1])[:8]}}
        h = e['hold_2007_2020_net']
        jp[name] = h['p'] if h else None
        log(name, 'A', e['A_1881_1925']['ex_ann'], e['A_1881_1925']['t'], '| train', e['train_1926_2006']['ex_ann'], e['train_1926_2006']['t'],
            '| hold', e['hold_2007_2020']['ex_ann'], e['hold_2007_2020']['t'], '| DCA20 B', Jres[name]['dca20_B_path'])
    jholm = M.holm(jp)
    for name, x in Jres.items():
        lump, dcab = x['roll20_lump_B'], x['dca20_B_path']
        roll_for_grade = {'win_rate': min(lump['win_rate'] if lump else 0.0, dcab['win_rate'] if dcab else 0.0),
                          'lump_win_rate': lump['win_rate'] if lump else None, 'dca_win_rate': dcab['win_rate'] if dcab else None}
        # grade() は excess_stats の形（ex_ann・t・cagr_diff）を読む。保有は短い窓の自前の要約
        hold, hold_net = x['hold_2007_2020'], x['hold_2007_2020_net']
        repl = {'regions': 1, 'positive': 1 if x['A_1881_1925'] and x['A_1881_1925']['ex_ann'] > 0 else 0, 'what': '道 A（1881〜1925）の超過が正'}
        g, crit = M.grade(x['full_1926_2020'], x['train_1926_2006'], hold, roll_for_grade, cost_hold=hold_net, repl=repl, family_holm_p=jholm.get(name))
        x.update({'repl': repl, 'roll20_for_grade': roll_for_grade, 'family_holm_p': jholm.get(name), 'grade': g, 'criteria': crit})
        tested.append(x)
        log(name, 'grade', g, crit)

    # ── R を tested にも（格付けしない・多重検定の数に入れる） ──
    for reg, rr in R.items():
        for rule, v in rr.items():
            tested.append({'name': f'R_{reg}_{rule}', 'family': 'R（再現・C5 用・格付けしない）', 'primary': False, 'graded': False,
                           'in_C5': reg in C5_REGIONS, **v})

    # ── いまの信号（前向きの記録・判定には使わない） ──
    last = max(t for t in decide)
    now = {'decision_month': last, 'rel': {b: r2(rel[b].get(last), 3) for b in rel}, 'dy_pct': {b: r2(dy[b][last] * 100) if last in dy[b] else None for b in dy},
           'mom_12_1': {b: r2(mom[b].get(last), 3) for b in mom}, 'choices': {k: ch[k][last] for k in ch}}
    try:
        ip = json.load(open(os.path.join(M.BASE, 'out', 'industry_peak.json')))
        rec = [x.get('業種') for x in ip.get('今_記録を付けている業種', [])]
        now['F5_tech_share_state'] = {'source': 'out/industry_peak.json（読むだけ）', 'latest_year': ip.get('比重の最新の年'),
                                      'industries_at_record': rec, 'F5_would_divert': bool({'Softw', 'Chips'} & set(rec)),
                                      'note': 'F5 は前向きだけ・報告のみ（歴史では測らない）'}
    except Exception as e:  # noqa
        now['F5_tech_share_state'] = {'error': str(e)[:200]}

    # ── 探索の第2族（事前登録2）: X・Y と、売らない積立の中立の道 N ──
    part2 = None
    if os.path.exists(os.path.join(M.BASE, PREREG2)):
        tested2, part2 = run_part2(D, dy, rel, mom, ch, gross, net, Wg, Wn, SPn, decide, ret, dp, chA, chB)
        tested += tested2
        now['part2_choices'] = part2.pop('_now', None)

    out = {'angle': 'flow_tilt', 'prereg': PREREG, 'prereg_commit': git_sha(PREREG),
           'prereg2': PREREG2 if part2 else None, 'prereg2_commit': git_sha(PREREG2) if part2 else None,
           'global_prereg': 'out/mw_prereg.json', 'global_prereg_commit': git_sha('out/mw_prereg.json'),
           'n_tested': len(tested), 'n_graded': sum(1 for x in tested if x.get('graded')),
           'grades': {x['name']: x.get('grade', '格付け外') for x in tested},
           'sanity': sanity, 'current_signal': now, 'part2': part2, 'tested': tested, 'log': LOG[-120:], 'runtime_s': round(time.time() - t0, 1)}
    p = M.save(OUT, out)
    log('書いた', p, round(os.path.getsize(p) / 1e6, 2), 'MB')


if __name__ == '__main__':
    if '--check' in sys.argv:
        check()
    else:
        main()
