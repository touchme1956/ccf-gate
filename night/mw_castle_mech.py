#!/usr/bin/env python3
"""night/mw_castle_mech.py — 角度 castle_mech（読むだけ・門の判定には不使用）

問い: 『cop_at（現金ベースの営業収益性）で選んだ米国大型株』の上乗せは、投資家の実際の城の仕組み
      （4〜5社・毎月の積立を不足が最大の1社へ・株価では売らない・城20%・土台 S&P500 / NASDAQ100）の中でも残るか。
  Part 1  事象時間の減衰: 毎年7月の組（2010〜2025）を組み直さずに持ち、1〜10年目の超過を出す。
          2〜5年目の暦の時間の合成（重なる組に頑健）で『持続』を判定（平均>0 かつ NW t≥1.65）。
  Part 2  投資家の仕組み: 月¥170,000 を 80% 土台・20% 城。城は不足最大の1社へ。売るのは母集団から外れたときだけ。
          比較: (a) 毎年組み直す城 (b) 無作為の巨大株5社の城 (c) 土台100%。円・税引後（課税口座／NISA の枠つき／併用）。

事前登録: out/mw_castle_mech_prereg.json（測る前にコミット）。線は out/mw_prereg.json（mw_common.grade）。
出力: out/mw_castle_mech.json

使い方:
  python3 night/mw_castle_mech.py --selftest   # 合成データで模型だけ確かめる（戦略と市場は比べない）
  python3 night/mw_castle_mech.py --check      # データの有無だけ
  python3 night/mw_castle_mech.py              # 全部
"""
import sys, os, json, math, random, time, statistics as S, subprocess
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import mw_sec_replication as SR  # noqa: E402

ANGLE = 'castle_mech'
PRE = 'mw_castle_mech_prereg.json'
OUT = 'mw_castle_mech.json'
START, END = 201007, 202608
COH = list(range(2010, 2026))           # Part 1 の組
KMAX = 10
TAX, WH = 0.20315, 0.10
Q_TSUMI, Q_GROWTH, LIFE, LIFE_G = 1_200_000, 2_400_000, 18_000_000, 12_000_000
CONTRIB, CONTRIB_ALT = 170_000, 100_000
CF = 0.20                               # 城の割合
COST = 0.001                            # 片道100%あたり（大型株の既定）
COST_JP_CASTLE, COST_JP_CORE = 0.0066, 0.0
QQQM_FEE_ADJ = 0.0005                   # QQQ(0.20%) → QQQM(0.15%)
R_DRAWS = 300
SEED = 20260928
BOOT_N = 10000
BOOT_H = (10, 15, 20, 30)
DECAY_TURN = 0.25
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def addm(k, n):
    return SR._addm(k, n)


def mrange(a, z):
    out, k = [], a
    while k <= z:
        out.append(k); k = SR._nextm(k)
    return out


def jyear(m):
    return m // 100 if m % 100 >= 7 else m // 100 - 1


def git_sha(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── データ ─────────────────────────
def div_yield(ret, cl):
    """配当利回り（月）= adjclose のリターン − close のリターン。close が無い月は直前12か月の中央値（無ければ0・件数）"""
    dy, stat = {}, {'filled_median': 0, 'filled_zero': 0, 'neg_clipped': 0}
    ks = sorted(ret)
    for m in ks:
        p = addm(m, -1)
        if m in cl and p in cl and cl[p] > 0:
            d = ret[m] - (cl[m] / cl[p] - 1)
            if d < -0.001:
                stat['neg_clipped'] += 1; d = 0.0
            elif d < 0:
                d = 0.0
            dy[m] = min(d, 0.5)
        else:
            dy[m] = None
    for i, m in enumerate(ks):
        if dy[m] is None:
            prev = [dy[k] for k in ks[max(0, i - 12):i] if dy[k] is not None]
            if prev:
                dy[m] = S.median(prev); stat['filled_median'] += 1
            else:
                dy[m] = 0.0; stat['filled_zero'] += 1
    return dy, stat


def fx_monthly():
    b = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=30)
    fx = {}
    for line in b.decode().splitlines()[1:]:
        p = line.split(',')
        if len(p) < 2 or p[1].strip() in ('', '.'):
            continue
        k = int(p[0][:4]) * 100 + int(p[0][5:7])
        fx[k] = float(p[1])          # 月の最後の観測が残る（日付の昇順）
    return fx


def load():
    t0 = time.time()
    panel = SR.build_panel()
    uni, price, diag, sic, tick = SR.build_universe(panel, fetch=True, verbose=False)
    R, DY, dystat = {}, {}, {'filled_median': 0, 'filled_zero': 0, 'neg_clipped': 0}
    for x, v in price.items():
        if not v:
            continue
        R[x] = v[0]
        DY[x], st = div_yield(v[0], v[1])
        for k in st:
            dystat[k] += st[k]
    cores = {}
    for nm, tk, adj in (('SPX', 'SPY', 0.0), ('NDX', 'QQQ', QQQM_FEE_ADJ)):
        ys = SR.yahoo_series(tk)
        r = {k: v + adj / 12 for k, v in ys[0].items()}
        d, _ = div_yield(ys[0], ys[1])
        cores[nm] = (r, d)
    fx = fx_monthly()
    ff = M.ff_factors()
    log(f'データ: {time.time() - t0:.1f}s ティッカー {len(R)} 配当の穴 {dystat}')
    return {'uni': uni, 'R': R, 'DY': DY, 'dystat': dystat, 'cores': cores, 'fx': fx, 'ff': ff}


def forms(uni):
    F = {k: {} for k in ('T3VW', 'M100_T3VW', 'M100_T5', 'M100_T10')}
    B = {'U_all': {}, 'M100': {}}
    UT, pools = {}, {'b1_M100_exfin': {}, 'b2_M100_top_third_cop_at': {}}
    for t in SR.YEARS:
        u = uni[t]
        R_, sc = SR.scores(u)
        F['T3VW'][t] = {u[c]['ticker']: u[c]['fcap'] for c in SR.top_by(sc['cop_at'], u, frac=1 / 3)}
        m100 = {c: u[c] for c in sorted(u, key=lambda c: -u[c]['fcap'])[:100]}
        Rm, scm = SR.scores(m100)
        t3 = SR.top_by(scm['cop_at'], m100, frac=1 / 3)
        F['M100_T3VW'][t] = {m100[c]['ticker']: m100[c]['fcap'] for c in t3}
        F['M100_T5'][t] = {m100[c]['ticker']: 1.0 for c in SR.top_by(scm['cop_at'], m100, n=5)}
        F['M100_T10'][t] = {m100[c]['ticker']: 1.0 for c in SR.top_by(scm['cop_at'], m100, n=10)}
        B['U_all'][t] = {r['ticker']: r['fcap'] for r in u.values()}
        B['M100'][t] = {m100[c]['ticker']: m100[c]['fcap'] for c in m100}
        UT[t] = {r['ticker'] for r in u.values()}
        pools['b1_M100_exfin'][t] = sorted(m100[c]['ticker'] for c in Rm)
        pools['b2_M100_top_third_cop_at'][t] = sorted(m100[c]['ticker'] for c in t3)
    return F, B, UT, pools


# ───────────────────────── Part 1: 事象時間 ─────────────────────────
def bh(w0, R, months):
    tot = sum(w0.values())
    cur = {k: v / tot for k, v in w0.items()}
    out, drops = {}, 0
    for m in months:
        av = {k: v for k, v in cur.items() if m in R.get(k, {})}
        drops += len(cur) - len(av)
        if not av:
            break
        tv = sum(av.values())
        out[m] = sum(v * R[k][m] for k, v in av.items()) / tv
        cur = {k: v * (1 + R[k][m]) for k, v in av.items()}
    return out, drops


def comp12(r, ms):
    if not all(m in r for m in ms):
        return None
    return math.prod(1 + r[m] for m in ms) - 1


def part1(D, F, B):
    R = D['R']
    bench = {nm: SR.simulate(B[nm], R)[0] for nm in B}
    ff = D['ff']
    fm = {k: v for k, v in ff['mkt'].items() if START <= k <= END}
    spy = D['cores']['SPX'][0]
    out = {'bench_cagr': {nm: round(M.cagr(v) * 100, 2) for nm, v in bench.items()}}
    series = {}
    for form, pb in (('T3VW', 'U_all'), ('M100_T3VW', 'M100'), ('M100_T5', 'M100')):
        paths, drops = {}, {}
        for t in COH:
            ms = mrange(t * 100 + 7, min((t + KMAX) * 100 + 6, END))
            paths[t], drops[t] = bh(F[form][t], R, ms)
        b = bench[pb]
        ek = {}
        for k in range(1, KMAX + 1):
            s = {}
            for m in mrange(START, END):
                t = jyear(m) - k + 1
                if t in paths and m in paths[t]:
                    s[m] = paths[t][m]
            ek[k] = s
        aged = {}
        for m in mrange(START, END):
            v = [ek[k][m] for k in (2, 3, 4, 5) if m in ek[k]]
            if v:
                aged[m] = sum(v) / len(v)
        by_k = {}
        for k in range(1, KMAX + 1):
            st = M.excess_stats(ek[k], b)
            tab = {}
            for t in COH:
                ms = mrange((t + k - 1) * 100 + 7, (t + k) * 100 + 6)
                a_, b_ = comp12(paths[t], ms), comp12(b, ms)
                if a_ is not None and b_ is not None:
                    tab[t] = round((a_ - b_) * 100, 2)
            vals = list(tab.values())
            by_k[k] = {'vs_' + pb: st, 'vs_FF_Mkt': M.excess_stats(ek[k], fm), 'n_cohorts_full_year': len(vals),
                       'cohort_annual_excess_pct': tab,
                       'mean_cohort_excess': round(S.mean(vals), 2) if vals else None,
                       'share_cohorts_positive': round(sum(1 for x in vals if x > 0) / len(vals), 2) if vals else None}
        st = M.excess_stats(aged, b)
        persist = bool(st and st['ex_ann'] > 0 and (st['t'] or 0) >= 1.65)
        aged15 = {}
        for m in mrange(START, END):
            v = [ek[k][m] for k in (1, 2, 3, 4, 5) if m in ek[k]]
            if v:
                aged15[m] = sum(v) / len(v)
        a610 = {}
        for m in mrange(START, END):
            v = [ek[k][m] for k in range(6, 11) if m in ek[k]]
            if v:
                a610[m] = sum(v) / len(v)
        out[form] = {'primary_benchmark': pb, 'drops_stock_months': sum(drops.values()),
                     'by_event_year': by_k,
                     'aged_2_5': {'vs_' + pb: st, 'vs_FF_Mkt': M.excess_stats(aged, fm), 'vs_SPY': M.excess_stats(aged, spy),
                                  'persistence_criterion_pass': persist},
                     'aged_1_5_report': {'vs_' + pb: M.excess_stats(aged15, b)},
                     'aged_6_10_report': {'vs_' + pb: M.excess_stats(a610, b)},
                     'year1_vs_' + pb + '_to_2026_06': M.excess_stats(ek[1], b, START, 202606)}
        series['decay_aged25_' + form] = aged
    return out, series, bench


# ───────────────────────── Part 2: 口座と税の模型 ─────────────────────────
class Book:
    def __init__(self, regime, kc, kk):
        self.reg, self.kc, self.kk = regime, kc, kk
        self.pos = {}                    # (口座, 資産) -> [USD 時価, 円の取得費]
        self.cb = {}
        self.cash = 0.0                  # 城の現金（USD）
        self.ytd = self.withheld = 0.0
        self.carry = []
        self.q = {'NT': 0.0, 'NG': 0.0}
        self.life = self.life_g = self.pend = self.pend_g = 0.0
        self.st = {'tax_gain_jpy': 0.0, 'tax_div_jpy': 0.0, 'sales_usd': 0.0, 'n_sales': 0, 'cost_usd': 0.0,
                   'nisa_nt_jpy': 0.0, 'nisa_ng_jpy': 0.0, 'taxable_buy_jpy': 0.0, 'carry_expired_jpy': 0.0}

    def taxed(self):
        return self.reg in ('taxable', 'nisa_q')

    def _add(self, acct, a, usd, jpy, kap):
        self.cb[a] = self.cb.get(a, 0.0) + jpy          # 報告用: 社ごとに買った円の合計（売った代金の入れ直しを含む）
        p = self.pos.setdefault((acct, a), [0.0, 0.0])
        p[0] += usd * (1 - kap); p[1] += jpy
        self.st['cost_usd'] += usd * kap
        if acct == 'T':
            self.st['taxable_buy_jpy'] += jpy

    def buy(self, a, usd, fxr, core=False):
        if usd <= 1e-9:
            return
        kap = self.kk if core else self.kc
        jpy = usd * fxr
        if self.reg == 'nisa_q':
            for fr in (('NT', 'NG') if core else ('NG',)):
                capy = (Q_TSUMI if fr == 'NT' else Q_GROWTH) - self.q[fr]
                capl = LIFE - self.life
                if fr == 'NG':
                    capl = min(capl, LIFE_G - self.life_g)
                x = min(jpy, max(0.0, capy), max(0.0, capl))
                if x > 1e-6:
                    self._add(fr, a, x / fxr, x, kap)
                    self.q[fr] += x; self.life += x
                    self.st['nisa_nt_jpy' if fr == 'NT' else 'nisa_ng_jpy'] += x
                    if fr == 'NG':
                        self.life_g += x
                    jpy -= x
                if jpy <= 1e-6:
                    return
            self._add('T', a, jpy / fxr, jpy, kap)
        else:
            self._add({'pretax': 'P', 'taxable': 'T', 'nisa_inf': 'F'}[self.reg], a, usd, jpy, kap)

    def held(self, a):
        return sum(v[0] for (ac, x), v in self.pos.items() if x == a)

    def assets(self):
        return {x for (ac, x) in self.pos}

    def realize(self, g, fxr):
        if not self.taxed():
            return
        self.ytd += g
        tgt = TAX * max(0.0, self.ytd)
        d = tgt - self.withheld
        self.cash -= d / fxr
        self.withheld = tgt
        self.st['tax_gain_jpy'] += d

    def sell(self, a, frac, fxr, core=False, count=True):
        kap = self.kk if core else self.kc
        for key in [k for k in self.pos if k[1] == a]:
            acct = key[0]
            v, b = self.pos[key]
            x, bb = v * frac, b * frac
            proc = x * (1 - kap)
            self.st['cost_usd'] += x * kap
            self.cash += proc
            if acct == 'T':
                self.realize(proc * fxr - bb, fxr)
            elif acct in ('NT', 'NG'):
                self.pend += bb
                if acct == 'NG':
                    self.pend_g += bb
            if frac >= 1 - 1e-12:
                del self.pos[key]
            else:
                self.pos[key] = [v - x, b - bb]
            if count:
                self.st['sales_usd'] += x
        if count:
            self.st['n_sales'] += 1

    def settle(self, year, fxr):
        if self.taxed():
            self.carry = [c for c in self.carry if year - c[0] <= 3]
            if self.ytd > 0:
                avail = sum(c[1] for c in self.carry)
                use = min(avail, self.ytd); rem = use
                for c in self.carry:
                    u = min(c[1], rem); c[1] -= u; rem -= u
                self.cash += TAX * use / fxr
                self.st['tax_gain_jpy'] -= TAX * use
            elif self.ytd < 0:
                self.carry.append([year, -self.ytd])
            self.st['carry_expired_jpy'] += sum(c[1] for c in self.carry if year - c[0] >= 3)
            self.carry = [c for c in self.carry if c[1] > 1e-9 and year - c[0] < 3]
            self.ytd = self.withheld = 0.0
        if self.reg == 'nisa_q':
            self.q = {'NT': 0.0, 'NG': 0.0}
            self.life -= self.pend; self.life_g -= self.pend_g
            self.pend = self.pend_g = 0.0

    def month_returns(self, m, rets, divs, fxm):
        """月のリターン（配当込み）。配当の税を引いて同じ銘柄へ再投資。戻り値: 税引前の (前, 後) を資産ごと"""
        for key in list(self.pos):
            acct, a = key
            v, b = self.pos[key]
            r = rets[a][m]; d = divs[a].get(m, 0.0)
            div = v * d
            rate = 0.0
            if self.reg != 'pretax':
                rate = TAX if acct == 'T' else WH
            self.pos[key] = [v * (1 + r) - rate * div, b + ((1 - rate) * div * fxm if acct == 'T' else 0.0)]
            self.st['tax_div_jpy'] += rate * div * fxm

    def liquidate(self, fxr, year):
        for a in list(self.assets()):
            self.sell(a, 1.0, fxr, core=(a == 'CORE'), count=False)
        self.settle(year, fxr)
        return self.cash * fxr


def waterfill(amount, sf, shares):
    """sf {a: 不足}（負もあり）→ 配分 {a: x}。不足の大きい順に水位を揃える。全部埋めて余れば目標の割合で"""
    posv = {a: v for a, v in sf.items() if v > 0}
    tot = sum(posv.values())
    if amount >= tot:
        x = dict(posv)
        left = amount - tot
        ssum = sum(shares[a] for a in sf)
        for a in sf:
            x[a] = x.get(a, 0.0) + left * shares[a] / ssum
        return x
    items = sorted(posv.items(), key=lambda z: -z[1])
    cum = 0.0
    L = 0.0
    for i, (a, v) in enumerate(items):
        cum += v
        L = (cum - amount) / (i + 1)
        nxt = items[i + 1][1] if i + 1 < len(items) else -1e18
        if L >= nxt:
            break
    return {a: v - L for a, v in items if v > L}


D = None   # 作業者が fork で受け継ぐ


def rets_of(core):
    R = dict(D['R']); DYv = dict(D['DY'])
    R['CORE'], DYv['CORE'] = D['cores'][core]
    return R, DYv


def simulate(cfg):
    """cfg: {'regime','cf','rule'('mech'|'annual'|'none'),'sel'{J:{tk:share}},'core','contrib','kc','kk','start','end','record'}"""
    R, DYv = rets_of(cfg['core'])
    fx = D['fx']; UT = D['UT']
    bk = Book(cfg['regime'], cfg['kc'], cfg['kk'])
    cf, rule, sel = cfg['cf'], cfg['rule'], cfg.get('sel') or {}
    months = mrange(cfg['start'], cfg['end'])
    Jc, year = None, None
    twr_c, twr_w, cval = {}, {}, {}
    forced = uni_exit = 0
    contrib_jpy = 0.0
    for m in months:
        y = m // 100
        fxr = fx[addm(m, -1)]
        if year is not None and y != year:
            bk.settle(year, fxr)
        year = y
        # 価格の系列が途切れた城の銘柄 → 前月末の値で現金化
        for a in [a for a in bk.assets() if a != 'CORE' and m not in R.get(a, {})]:
            bk.sell(a, 1.0, fxr); forced += 1
        J = jyear(m)
        newf = J != Jc
        if newf:
            Jc = J
            Sel = sel.get(J, {})
            if rule in ('mech', 'annual'):
                for a in [a for a in bk.assets() if a != 'CORE' and a not in UT.get(J, set())]:
                    bk.sell(a, 1.0, fxr); uni_exit += 1
            if rule == 'annual':
                for a in [a for a in bk.assets() if a != 'CORE' and a not in Sel]:
                    bk.sell(a, 1.0, fxr)
        E = {a: s for a, s in Sel.items() if m in R.get(a, {})} if cf > 0 else {}
        es = sum(E.values())
        c_usd = cfg['contrib'] / fxr
        contrib_jpy += cfg['contrib']
        bk.buy('CORE', (1 - cf) * c_usd, fxr, core=True)
        cu = cf * c_usd
        if cf > 0 and E:
            sh = {a: s / es for a, s in E.items()}
            if rule == 'mech':
                tv = sum(v[0] for v in bk.pos.values()) + bk.cash + cu
                sf = {a: cf * tv * sh[a] - bk.held(a) for a in E}
                best = max(sf, key=lambda a: (sf[a], a))
                bk.buy(best, cu, fxr)
                if bk.cash > 1e-9:
                    tv = sum(v[0] for v in bk.pos.values()) + bk.cash
                    sf = {a: cf * tv * sh[a] - bk.held(a) for a in E}
                    amt = bk.cash; bk.cash = 0.0
                    for a, x in waterfill(amt, sf, sh).items():
                        bk.buy(a, x, fxr)
            elif rule == 'annual':
                if newf:
                    cv = sum(v[0] for (ac, a), v in bk.pos.items() if a != 'CORE') + bk.cash + cu
                    for a in list(E):
                        h = bk.held(a); tg = cv * sh[a]
                        if h > tg * 1.0001 and h > 0:
                            bk.sell(a, (h - tg) / h, fxr)
                    avail = bk.cash + cu; bk.cash = 0.0
                    dfc = {a: max(0.0, cv * sh[a] - bk.held(a)) for a in E}
                    tot = sum(dfc.values())
                    for a in E:
                        x = avail * dfc[a] / tot if tot > avail else dfc[a] + (avail - tot) * sh[a]
                        bk.buy(a, x, fxr)
                else:
                    avail = bk.cash + cu; bk.cash = 0.0
                    for a in E:
                        bk.buy(a, avail * sh[a], fxr)
        elif cf > 0:
            bk.cash += cu                      # 買える社が無い月は現金で待つ
        # 月のリターン
        v0c = sum(v[0] for (ac, a), v in bk.pos.items() if a != 'CORE') + bk.cash
        v0w = v0c + sum(v[0] for (ac, a), v in bk.pos.items() if a == 'CORE')
        g1c = bk.cash + sum(v[0] * (1 + R[a][m]) for (ac, a), v in bk.pos.items() if a != 'CORE')
        g1w = g1c + sum(v[0] * (1 + R[a][m]) for (ac, a), v in bk.pos.items() if a == 'CORE')
        if v0c > 0:
            twr_c[m] = g1c / v0c - 1
            cval[m] = v0c
        if v0w > 0:
            twr_w[m] = g1w / v0w - 1
        bk.month_returns(m, R, DYv, fx[m])
    fxe = fx[months[-1]]
    held = (sum(v[0] for v in bk.pos.values()) + bk.cash) * fxe
    held_castle = (sum(v[0] for (ac, a), v in bk.pos.items() if a != 'CORE') + bk.cash) * fxe
    nh = len([a for a in bk.assets() if a != 'CORE'])
    avgc = S.mean(cval.values()) if cval else None
    turn = (bk.st['sales_usd'] / len(months) * 12 / avgc) if avgc else None
    endpos = {a: bk.held(a) * fxe for a in bk.assets() if a != 'CORE'}
    liq = bk.liquidate(fxe, months[-1] // 100)
    res = {'held_jpy': held, 'liquidated_jpy': liq, 'castle_held_jpy': held_castle, 'contrib_jpy': contrib_jpy,
           'n_castle_names_end': nh, 'forced_sales': forced, 'universe_exit_sales': uni_exit, 'turnover_oneway_ann': turn,
           'stats': bk.st}
    if cfg.get('record'):
        res['twr_castle'] = twr_c; res['twr_whole'] = twr_w
    if cfg.get('pos'):
        res['castle_end_jpy'] = endpos
        res['bought_jpy'] = {a: v for a, v in bk.cb.items() if a != 'CORE'}
    return res


def run_many(cfgs, procs=4):
    with Pool(procs) as p:
        return p.map(simulate, cfgs, chunksize=4)


# ───────────────────────── 自己検査（合成データ） ─────────────────────────
def selftest():
    global D
    ms = mrange(201001, 203012)
    r = {m: 0.01 for m in ms}
    D = {'R': {'A': dict(r), 'B': {m: 0.02 for m in ms}}, 'DY': {'A': {m: 0.0 for m in ms}, 'B': {m: 0.0 for m in ms}},
         'cores': {'SPX': ({m: 0.01 for m in ms}, {m: 0.0 for m in ms})}, 'fx': {m: 100.0 for m in ms},
         'UT': {y: {'A', 'B'} for y in range(2009, 2031)}}
    base = {'regime': 'pretax', 'cf': 0.0, 'rule': 'none', 'sel': {}, 'core': 'SPX', 'contrib': 100000, 'kc': 0.0, 'kk': 0.0,
            'start': 201007, 'end': 202006}
    n = 120
    fv = 100000 * ((1.01 ** n - 1) / 0.01) * 1.01
    a = simulate(base)
    ok1 = abs(a['held_jpy'] - fv) < 1e-3
    b = simulate(dict(base, cf=0.2, rule='mech', sel={y: {'B': 1.0} for y in range(2009, 2031)}))
    fvb = 20000 * ((1.02 ** n - 1) / 0.02) * 1.02 + 0.8 * fv
    ok2 = abs(b['held_jpy'] - fvb) < 1e-3
    c = simulate(dict(base, regime='taxable'))
    ok3 = abs(c['liquidated_jpy'] - (fv - TAX * (fv - 100000 * n))) < 1e-3
    d = simulate(dict(base, regime='nisa_q', contrib=1_000_000, record=False))
    st = d['stats']
    ok4 = abs(st['nisa_nt_jpy'] + st['nisa_ng_jpy'] - LIFE) < 1 and st['nisa_ng_jpy'] <= LIFE_G + 1
    # 城を半分ずつ（mech の水位）: A と B を等分目標 → 不足の大きい方へ
    e = simulate(dict(base, cf=0.2, rule='annual', sel={y: {'A': 1.0, 'B': 1.0} for y in range(2009, 2031)}))
    ok5 = e['held_jpy'] > a['held_jpy']
    wf = waterfill(10, {'x': 8, 'y': 5, 'z': -1}, {'x': 1, 'y': 1, 'z': 1})
    ok6 = abs(wf['x'] - 6.5) < 1e-9 and abs(wf['y'] - 3.5) < 1e-9 and 'z' not in wf
    res = {'closed_form_core': ok1, 'single_name_castle': ok2, 'taxable_liquidation': ok3, 'nisa_lifetime_cap': ok4,
           'annual_runs': ok5, 'waterfill': ok6}
    log('自己検査', res)
    return res


# ───────────────────────── 集計 ─────────────────────────
def usd_twr_to_jpy(r, fx):
    return {m: (1 + v) * fx[m] / fx[addm(m, -1)] - 1 for m, v in r.items() if m in fx and addm(m, -1) in fx}


def boot(castle_jpy, core_jpy, H, n=BOOT_N, seed=SEED, cf=CF):
    """7月〜6月の年のまとまり（2010〜2025の16個）を復元抽出して H 年つなぎ、80/20 の積立 ÷ 土台100% の比"""
    rng = random.Random(seed)
    blocks = []
    for J in COH:
        ms = mrange(J * 100 + 7, (J + 1) * 100 + 6)
        if all(m in castle_jpy and m in core_jpy for m in ms):
            blocks.append([(castle_jpy[m], core_jpy[m]) for m in ms])
    ratios = []
    for _ in range(n):
        vc = vk = vb = 0.0
        for _y in range(H):
            for rc, rk in blocks[rng.randrange(len(blocks))]:
                vc = (vc + cf) * (1 + rc); vk = (vk + 1 - cf) * (1 + rk); vb = (vb + 1) * (1 + rk)
        ratios.append((vc + vk) / vb)
    ratios.sort()
    q = lambda p: round(ratios[min(len(ratios) - 1, int(p * len(ratios)))], 3)
    return {'blocks': len(blocks), 'draws': n, 'p_beat_core': round(sum(1 for x in ratios if x > 1) / n, 3),
            'p05': q(0.05), 'median': q(0.5), 'p95': q(0.95)}


def years_to_t2(s, b):
    st = M.excess_stats(s, b)
    if not st:
        return None
    T = st['years']; t = st['t']; mu = st['ex_ann']; te = st['te']
    out = {'years_observed': T, 'ex_ann': mu, 't': t, 'te': te,
           'years_needed_from_t': round(T * (2 / t) ** 2, 1) if t and t > 0 else '届かない（t≤0）',
           'years_needed_from_mu_te': round((2 * te / mu) ** 2, 1) if mu > 0 else '届かない（平均≤0）',
           'if_edge_1_2_3pct': {f'{e}%': round((2 * te / e) ** 2, 1) for e in (1, 2, 3)}}
    return out


def ex27_rerun():
    """ex27 の角度が各年（1996〜2001）の社ごとの値を出していれば Part 1 を当てる（配管だけ後で書く）"""
    cand = [os.path.join(M.BASE, 'out', 'mw_ex27.json')]
    for p in cand:
        if os.path.exists(p):
            try:
                d = json.load(open(p))
            except Exception:  # noqa
                continue
            if isinstance(d, dict) and d.get('panel_for_decay'):
                return {'status': 'panel_found_but_adapter_not_written', 'file': p}
    return {'status': 'N/A', 'why': 'ex27 の角度の社ごとのパネル（1996〜2001）がリポジトリに無い（実行の時点）'}


def main():
    global D
    t0 = time.time()
    st = selftest()
    if not all(st.values()):
        raise SystemExit('自己検査が通らない')
    D = load()
    F, B, UT, pools = forms(D['uni'])
    D['UT'] = UT
    ff = D['ff']
    fm = {k: v for k, v in ff['mkt'].items() if START <= k <= END}
    fx = D['fx']
    # ── 点検
    chk = {'french_mkt_cagr_all': round(M.cagr(ff['mkt']) * 100, 2),
           'french_mkt_cagr_2007': round(M.cagr(M.window(ff['mkt'], M.HOLD_START)) * 100, 2),
           'french_last_month': max(ff['mkt']), 'dividend_yield_fill': D['dystat'],
           'fx_2010_06': fx.get(201006), 'fx_2026_08': fx.get(202608)}
    # ── Part 1
    p1, dser, bench = part1(D, F, B)
    try:
        sr = json.load(open(os.path.join(M.BASE, 'out', 'mw_sec_replication.json')))
        chk['U_all_cagr_window_mine'] = round(M.cagr(bench['U_all']) * 100, 2)
        chk['U_all_cagr_window_sec_replication'] = sr['checks'].get('U_all_cagr_window')
    except Exception as e:  # noqa
        chk['sec_replication_read_error'] = str(e)
    log('Part1 済', round(time.time() - t0, 1))
    # ── Part 2: 選ぶ社
    SEL = {'N5': {J: F['M100_T5'][J] for J in SR.YEARS}, 'N10': {J: F['M100_T10'][J] for J in SR.YEARS},
           'T3': {J: F['M100_T3VW'][J] for J in SR.YEARS}}
    base = {'cf': CF, 'contrib': CONTRIB, 'kc': COST, 'kk': COST, 'start': START, 'end': END}
    full = {}
    cfgs, keys = [], []
    for core in ('SPX', 'NDX'):
        for reg in ('pretax', 'taxable', 'nisa_q', 'nisa_inf'):
            keys.append(('core_only', core, reg)); cfgs.append(dict(base, cf=0.0, rule='none', core=core, regime=reg))
            for sv in SEL:
                for rule in ('mech', 'annual'):
                    keys.append((f'{rule}_{sv}', core, reg))
                    cfgs.append(dict(base, rule=rule, sel=SEL[sv], core=core, regime=reg, record=(reg == 'pretax')))
    # 感度（報告のみ）
    for core in ('SPX', 'NDX'):
        for reg in ('pretax', 'taxable', 'nisa_q'):
            keys.append(('core_only|jpcost', core, reg)); cfgs.append(dict(base, cf=0.0, rule='none', core=core, regime=reg, kc=COST_JP_CASTLE, kk=COST_JP_CORE))
            keys.append(('mech_N5|jpcost', core, reg)); cfgs.append(dict(base, rule='mech', sel=SEL['N5'], core=core, regime=reg, kc=COST_JP_CASTLE, kk=COST_JP_CORE))
            keys.append(('annual_N5|jpcost', core, reg)); cfgs.append(dict(base, rule='annual', sel=SEL['N5'], core=core, regime=reg, kc=COST_JP_CASTLE, kk=COST_JP_CORE))
            keys.append(('core_only|100k', core, reg)); cfgs.append(dict(base, cf=0.0, rule='none', core=core, regime=reg, contrib=CONTRIB_ALT))
            keys.append(('mech_N5|100k', core, reg)); cfgs.append(dict(base, rule='mech', sel=SEL['N5'], core=core, regime=reg, contrib=CONTRIB_ALT))
    res = run_many(cfgs)
    for k, r in zip(keys, res):
        full[k] = r
    log('Part2 全期間 済', round(time.time() - t0, 1))
    wealth = {}
    for (arm, core, reg), r in full.items():
        base_arm = 'core_only' + (arm[arm.index('|'):] if '|' in arm else '')
        cb = full[(base_arm, core, reg)]
        wealth.setdefault(arm, {}).setdefault(core, {})[reg] = {
            'held_jpy': round(r['held_jpy']), 'liquidated_jpy': round(r['liquidated_jpy']), 'contrib_jpy': round(r['contrib_jpy']),
            'ratio_vs_core_held': round(r['held_jpy'] / cb['held_jpy'], 4), 'ratio_vs_core_liquidated': round(r['liquidated_jpy'] / cb['liquidated_jpy'], 4),
            'castle_held_jpy': round(r['castle_held_jpy']), 'n_castle_names_end': r['n_castle_names_end'],
            'forced_sales': r['forced_sales'], 'universe_exit_sales': r['universe_exit_sales'],
            'turnover_oneway_ann': round(r['turnover_oneway_ann'], 3) if r['turnover_oneway_ann'] is not None else None,
            'tax_gain_jpy': round(r['stats']['tax_gain_jpy']), 'tax_div_jpy': round(r['stats']['tax_div_jpy']),
            'n_sales': r['stats']['n_sales'], 'nisa_used_jpy': round(r['stats']['nisa_nt_jpy'] + r['stats']['nisa_ng_jpy'])}
    # ── 格付け（城の時間加重・USD・pretax・S&P500 土台）
    spy = D['cores']['SPX'][0]; ndx = D['cores']['NDX'][0]
    graded = {}
    series = dict(dser)
    turns = {}
    for sv in SEL:
        for rule in ('mech', 'annual'):
            r = full[(f'{rule}_{sv}', 'SPX', 'pretax')]
            nm = f'castle_{rule}_{sv}'
            series[nm] = r['twr_castle']; turns[nm] = r['turnover_oneway_ann'] or 0.0
    for nm in dser:
        turns[nm] = DECAY_TURN
    PRIM = ['decay_aged25_T3VW', 'decay_aged25_M100_T3VW', 'decay_aged25_M100_T5',
            'castle_mech_N5', 'castle_mech_N10', 'castle_mech_T3', 'castle_annual_N5', 'castle_annual_N10', 'castle_annual_T3']
    pv = {}
    for nm in PRIM:
        s = series[nm]
        h = M.excess_stats(s, fm, M.HOLD_START)
        pv[nm] = h['p'] if h else None
    hp = M.holm(pv)
    for nm in PRIM:
        s = series[nm]
        fl = M.excess_stats(s, fm)
        hd = M.excess_stats(s, fm, M.HOLD_START)
        rc = M.excess_stats(s, fm, M.RECENT_START)
        ch = M.excess_stats(M.apply_cost(s, turns[nm], COST), fm, M.HOLD_START)
        r20 = M.rolling(s, fm, 20); d20 = M.dca(s, fm, 20)
        g, c = M.grade(fl, None, hd, r20, cost_hold=ch, repl=None, family_holm_p=hp.get(nm))
        graded[nm] = {'name': nm, 'primary': True, 'benchmark': 'French Mkt（総リターン）', 'full': fl, 'train': None, 'hold': hd, 'recent': rc,
                      'net_cost_hold': ch, 'turnover_oneway_ann': round(turns[nm], 3), 'roll20': r20, 'dca20': d20,
                      'roll10': M.rolling(s, fm, 10), 'dca10': M.dca(s, fm, 10),
                      'vs_SPY': M.excess_stats(s, spy), 'vs_NDX_QQQM': M.excess_stats(s, ndx), 'holm_p': hp.get(nm), 'grade': g, 'criteria': c,
                      'cagr': round(M.cagr(s) * 100, 2), 'maxdd': round(M.maxdd(s) * 100, 1)}
    # 全体（80/20）の時間加重 対 土台（報告）
    whole = {}
    for sv in SEL:
        for rule in ('mech', 'annual'):
            for core, cs in (('SPX', spy), ('NDX', ndx)):
                w = full[(f'{rule}_{sv}', core, 'pretax')]['twr_whole']
                whole[f'{rule}_{sv}|{core}'] = M.excess_stats(w, cs)
    # t=2 に要る年数（城 対 土台）
    t2 = {}
    for sv in SEL:
        for rule in ('mech', 'annual'):
            for core, cs in (('SPX', spy), ('NDX', ndx)):
                t2[f'{rule}_{sv}|{core}'] = years_to_t2(full[(f'{rule}_{sv}', core, 'pretax')]['twr_castle'], cs)
    log('格付け 済', round(time.time() - t0, 1))
    # ── 10・15年の窓（毎月起点）
    wins = {}
    cfgs, keys = [], []
    for H in (10, 15):
        starts = [s for s in mrange(START, END) if addm(s, H * 12 - 1) <= END]
        for s in starts:
            e = addm(s, H * 12 - 1)
            for core in ('SPX', 'NDX'):
                for reg in ('pretax', 'taxable', 'nisa_q'):
                    b2 = dict(base, start=s, end=e, core=core, regime=reg)
                    keys.append((H, s, 'core_only', core, reg)); cfgs.append(dict(b2, cf=0.0, rule='none'))
                    for arm, sv, rule in (('mech_N5', 'N5', 'mech'), ('annual_N5', 'N5', 'annual'), ('mech_N10', 'N10', 'mech'), ('mech_T3', 'T3', 'mech')):
                        keys.append((H, s, arm, core, reg)); cfgs.append(dict(b2, rule=rule, sel=SEL[sv]))
    res = run_many(cfgs)
    W = dict(zip(keys, res))
    for (H, s, arm, core, reg), r in W.items():
        if arm == 'core_only':
            continue
        cb = W[(H, s, 'core_only', core, reg)]
        fld = 'held_jpy' if reg == 'pretax' else 'liquidated_jpy'
        wins.setdefault(f'{H}y', {}).setdefault(arm, {}).setdefault(core, {}).setdefault(reg, []).append((s, r[fld] / cb[fld]))
    wsum = {}
    for H, a1 in wins.items():
        for arm, a2 in a1.items():
            for core, a3 in a2.items():
                for reg, v in a3.items():
                    rs = sorted(x for _, x in v)
                    wsum.setdefault(H, {}).setdefault(arm, {}).setdefault(core, {})[reg] = {
                        'windows': len(v), 'p_beat_core': round(sum(1 for x in rs if x > 1) / len(rs), 3),
                        'median_ratio': round(rs[len(rs) // 2], 4), 'worst': min(v, key=lambda z: z[1]), 'best': max(v, key=lambda z: z[1])}
    for H in wsum:
        for arm in wsum[H]:
            for core in wsum[H][arm]:
                for reg in wsum[H][arm][core]:
                    x = wsum[H][arm][core][reg]
                    x['worst'] = [x['worst'][0], round(x['worst'][1], 4)]; x['best'] = [x['best'][0], round(x['best'][1], 4)]
    log('窓 済', round(time.time() - t0, 1))
    # ── 無作為の城（全期間・pretax と taxable）
    rnd = {}
    cfgs, keys = [], []
    rng = random.Random(SEED)
    for pool, P in pools.items():
        for i in range(R_DRAWS):
            sel = {J: {x: 1.0 for x in rng.sample(P[J], min(5, len(P[J])))} for J in SR.YEARS}
            for core in ('SPX', 'NDX'):
                for reg in ('pretax', 'taxable'):
                    keys.append((pool, i, core, reg)); cfgs.append(dict(base, rule='mech', sel=sel, core=core, regime=reg))
    res = run_many(cfgs)
    RR = dict(zip(keys, res))
    for pool in pools:
        for core in ('SPX', 'NDX'):
            for reg in ('pretax', 'taxable'):
                fld = 'held_jpy' if reg == 'pretax' else 'liquidated_jpy'
                cb = full[('core_only', core, reg)][fld]
                me = full[('mech_N5', core, reg)][fld]
                v = sorted(RR[(pool, i, core, reg)][fld] / cb for i in range(R_DRAWS))
                q = lambda p: round(v[min(len(v) - 1, int(p * len(v)))], 4)
                rnd.setdefault(pool, {}).setdefault(core, {})[reg] = {
                    'draws': len(v), 'p_beat_core': round(sum(1 for x in v if x > 1) / len(v), 3), 'p05': q(0.05), 'median': q(0.5), 'p95': q(0.95),
                    'cop_at_mech_N5_ratio': round(me / cb, 4), 'cop_at_mech_N5_percentile': round(sum(1 for x in v if x < me / cb) / len(v), 3)}
    log('無作為 済', round(time.time() - t0, 1))
    # ── bootstrap（城の円の月次・pretax・mech）
    bs = {}
    for sv in SEL:
        for core in ('SPX', 'NDX'):
            cj = usd_twr_to_jpy(full[(f'mech_{sv}', core, 'pretax')]['twr_castle'], fx)
            kj = usd_twr_to_jpy(D['cores'][core][0], fx)
            bs[f'mech_{sv}|{core}'] = {f'{H}y': boot(cj, kj, H) for H in BOOT_H}
    for core in ('SPX', 'NDX'):
        cj = usd_twr_to_jpy(full[('annual_N5', core, 'pretax')]['twr_castle'], fx)
        kj = usd_twr_to_jpy(D['cores'][core][0], fx)
        bs[f'annual_N5|{core}'] = {f'{H}y': boot(cj, kj, H) for H in BOOT_H}
    log('bootstrap 済', round(time.time() - t0, 1))
    # ── 年ごと（7月〜6月）の城と土台（報告）
    ann = {}
    for nm in ('castle_mech_N5', 'castle_annual_N5', 'castle_mech_T3'):
        s = series[nm]
        ann[nm] = {J: round((comp12(s, mrange(J * 100 + 7, (J + 1) * 100 + 6)) or float('nan')) * 100, 1) for J in COH}
    for nm, s in (('SPY', spy), ('QQQM', ndx), ('FF_Mkt', fm)):
        ann[nm] = {J: round(comp12(s, mrange(J * 100 + 7, (J + 1) * 100 + 6)) * 100, 1) for J in COH}
    # ── 城の中身（mech_N5・終わりの時点）
    tested = [{'name': nm, 'role': 'primary', 'grade': graded[nm]['grade']} for nm in PRIM]
    for form in ('T3VW', 'M100_T3VW', 'M100_T5'):
        for k in range(1, KMAX + 1):
            tested.append({'name': f'decay_{form}_year{k}', 'role': 'report_event_year', 'grade': None})
        tested += [{'name': f'decay_{form}_aged_1_5', 'role': 'report', 'grade': None}, {'name': f'decay_{form}_aged_6_10', 'role': 'report', 'grade': None}]
    for arm in wealth:
        for core in ('SPX', 'NDX'):
            tested.append({'name': f'wealth_{arm}_{core}', 'role': 'report_wealth（税の扱い4通り以内）', 'grade': None})
    for pool in pools:
        tested.append({'name': f'random5_{pool}', 'role': 'report_distribution', 'grade': None})
    for k in bs:
        tested.append({'name': f'bootstrap_{k}', 'role': 'report_bootstrap', 'grade': None})
    out = {'angle': ANGLE, 'prereg': PRE, 'prereg_commit': git_sha(f'out/{PRE}'),
           'global_prereg': 'out/mw_prereg.json',
           'period': {'part1': '組 2010〜2025・保有 2010-07〜2026-08', 'part2': '2010-07〜2026-08'},
           'train': None, 'train_note': 'XBRL は2009年から＝訓練期間が無い。C1 は構造的に不合格＝格は最高でも C（brief どおり記述の扱い）',
           'selftest': st, 'checks': chk, 'part1_event_time_decay': p1,
           'graded_primary': graded, 'whole_portfolio_twr_vs_core': whole,
           'wealth_full_window': wealth, 'windows_10_15y': wsum, 'random_castles': rnd, 'cohort_bootstrap': bs,
           'years_to_t2': t2, 'annual_returns_jul_jun_pct': ann,
           'castle_selection_N5': {J: sorted(F['M100_T5'][J]) for J in SR.YEARS},
           'ex27_out_of_sample': ex27_rerun(),
           'tested': tested, 'n_tested': len(tested), 'log': LOG, 'runtime_s': round(time.time() - t0, 1)}
    p = M.save(OUT, out)
    log('保存', p, round(os.path.getsize(p) / 1e6, 2), 'MB')


# ───────────────────────── 探索の族（prereg2） ─────────────────────────
PRE2 = 'mw_castle_mech_prereg2.json'
MEGA6 = {'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA'}


def filt(uni, keep):
    return {t: {c: r for c, r in uni[t].items() if keep(r)} for t in uni}


def aged_of(Fform, R, lo=2, hi=5):
    """組ごとに買って持つ → k 年目の系列 → lo〜hi 年目の暦の合成（part1 と同じ作り方）"""
    paths = {}
    for t in COH:
        ms = mrange(t * 100 + 7, min((t + KMAX) * 100 + 6, END))
        paths[t], _ = bh(Fform[t], R, ms)
    aged = {}
    for m in mrange(START, END):
        v = []
        for k in range(lo, hi + 1):
            t = jyear(m) - k + 1
            if t in paths and m in paths[t]:
                v.append(paths[t][m])
        if v:
            aged[m] = sum(v) / len(v)
    return aged


def sub2(s, b):
    return {'2010_07_2018_06': M.excess_stats(s, b, START, 201806), '2018_07_2026_08': M.excess_stats(s, b, 201807, END)}


def run2():
    global D
    t0 = time.time()
    outp = os.path.join(M.BASE, 'out', OUT)
    main_ = json.load(open(outp))
    D = load()
    uni = D['uni']
    F, B, UT, pools = forms(uni)
    D['UT'] = UT
    R = D['R']
    fm = {k: v for k, v in D['ff']['mkt'].items() if START <= k <= END}
    spy = D['cores']['SPX'][0]; ndx = D['cores']['NDX'][0]
    bench0 = {nm: SR.simulate(B[nm], R)[0] for nm in B}
    base = {'cf': CF, 'contrib': CONTRIB, 'kc': COST, 'kk': COST, 'start': START, 'end': END}
    PB = {'T3VW': 'U_all', 'M100_T3VW': 'M100', 'M100_T5': 'M100'}
    SELK = {'N5': 'M100_T5', 'N10': 'M100_T10', 'T3': 'M100_T3VW'}
    # 主の系列（小分け用）
    prim = {}
    for form in PB:
        prim['decay_aged25_' + form] = aged_of(F[form], R)
    cfgs, keys = [], []
    for sv, fk in SELK.items():
        for rule in ('mech', 'annual'):
            keys.append(f'castle_{rule}_{sv}'); cfgs.append(dict(base, rule=rule, sel={J: F[fk][J] for J in SR.YEARS}, core='SPX', regime='pretax', record=True))
    for k, r in zip(keys, run_many(cfgs)):
        prim[k] = r['twr_castle']
    # E2
    E2, E2ser, E2bench, E2wealth = {}, {}, {}, {}
    exF = {}
    for tag, keep in (('exMega6', lambda r: r['ticker'] not in MEGA6), ('exBusEq', lambda r: r.get('ff12') != 'BusEq')):
        u2 = filt(uni, keep)
        F2, B2, UT2, pools2 = forms(u2)
        exF[tag] = F2
        b2 = {nm: SR.simulate(B2[nm], R)[0] for nm in B2}
        for form, pb in PB.items():
            nm = f'decay_aged25_{form}_{tag}'
            E2ser[nm] = aged_of(F2[form], R)
            E2bench[nm] = {'own_' + pb + '_' + tag: b2[pb], 'orig_' + pb: bench0[pb]}
    cfgs, keys = [], []
    for tag in exF:
        for sv, fk in SELK.items():
            sel = {J: exF[tag][fk][J] for J in SR.YEARS}
            keys.append((f'castle_mech_{sv}_{tag}', 'SPX', 'pretax', True)); cfgs.append(dict(base, rule='mech', sel=sel, core='SPX', regime='pretax', record=True))
            for core in ('SPX', 'NDX'):
                for reg in ('pretax', 'taxable', 'nisa_q'):
                    if (core, reg) == ('SPX', 'pretax'):
                        continue
                    keys.append((f'castle_mech_{sv}_{tag}', core, reg, False)); cfgs.append(dict(base, rule='mech', sel=sel, core=core, regime=reg))
    # 質で選ばない巨大株の城（仕組みだけの対照）
    capsel = {}
    for J in SR.YEARS:
        u = uni[J]
        m100 = {c: u[c] for c in sorted(u, key=lambda c: -u[c]['fcap'])[:100]}
        Rm, _sc = SR.scores(m100)
        capsel[J] = {m100[c]['ticker']: m100[c]['fcap'] for c in Rm}
    for core in ('SPX', 'NDX'):
        for reg in ('pretax', 'taxable', 'nisa_q'):
            keys.append(('megacap_index_castle', core, reg, False)); cfgs.append(dict(base, rule='mech', sel=capsel, core=core, regime=reg))
            keys.append(('core_only', core, reg, False)); cfgs.append(dict(base, cf=0.0, rule='none', core=core, regime=reg))
    keys.append(('castle_mech_N5', 'SPX', 'pretax', 'pos')); cfgs.append(dict(base, rule='mech', sel={J: F['M100_T5'][J] for J in SR.YEARS}, core='SPX', regime='pretax', pos=True))
    RES = dict(zip(keys, run_many(cfgs)))
    for (nm, core, reg, rec), r in RES.items():
        if rec is True:
            E2ser[nm] = r['twr_castle']
    core_w = {(c, g): RES[('core_only', c, g, False)] for c in ('SPX', 'NDX') for g in ('pretax', 'taxable', 'nisa_q')}
    for (nm, core, reg, rec), r in RES.items():
        if nm in ('core_only',) or rec == 'pos':
            continue
        fld = 'held_jpy' if reg == 'pretax' else 'liquidated_jpy'
        E2wealth.setdefault(nm, {}).setdefault(core, {})[reg] = {'ratio_vs_core': round(r[fld] / core_w[(core, reg)][fld], 4),
                                                                   'n_castle_names_end': r['n_castle_names_end'], 'universe_exit_sales': r['universe_exit_sales']}
    # 格付け（E2）
    MEM = json.load(open(os.path.join(M.BASE, 'out', PRE2)))['family_E2_graded_exploratory']['members']
    pv = {}
    for nm in MEM:
        h = M.excess_stats(E2ser[nm], fm, M.HOLD_START); pv[nm] = h['p'] if h else None
    hp = M.holm(pv)
    graded = {}
    for nm in MEM:
        s_ = E2ser[nm]
        turn = DECAY_TURN if nm.startswith('decay') else None
        if turn is None:
            k = (nm, 'SPX', 'pretax', True)
            turn = RES[k]['turnover_oneway_ann'] or 0.0
        fl = M.excess_stats(s_, fm); hd = M.excess_stats(s_, fm, M.HOLD_START)
        ch = M.excess_stats(M.apply_cost(s_, turn, COST), fm, M.HOLD_START)
        r20 = M.rolling(s_, fm, 20)
        g, c = M.grade(fl, None, hd, r20, cost_hold=ch, repl=None, family_holm_p=hp.get(nm))
        rec = {'name': nm, 'primary': False, 'exploratory': 'prereg2', 'benchmark': 'French Mkt', 'full': fl, 'train': None, 'hold': hd,
               'recent': M.excess_stats(s_, fm, M.RECENT_START), 'net_cost_hold': ch, 'turnover_oneway_ann': round(turn, 3), 'roll20': r20,
               'dca20': M.dca(s_, fm, 20), 'vs_SPY': M.excess_stats(s_, spy), 'vs_NDX_QQQM': M.excess_stats(s_, ndx),
               'holm_p_E2': hp.get(nm), 'grade': g, 'criteria': c, 'subperiods_vs_FF_Mkt': sub2(s_, fm)}
        if nm in E2bench:
            for bn, b in E2bench[nm].items():
                st = M.excess_stats(s_, b)
                rec['vs_' + bn] = st
                rec['persistence_pass_vs_' + bn] = bool(st and st['ex_ann'] > 0 and (st['t'] or 0) >= 1.65)
        graded[nm] = rec
    # 小分け（主）
    subs = {}
    for nm, s_ in prim.items():
        d_ = {'vs_FF_Mkt': sub2(s_, fm)}
        if nm.startswith('decay'):
            form = nm[len('decay_aged25_'):]
            d_['vs_' + PB[form]] = sub2(s_, bench0[PB[form]])
        subs[nm] = d_
    # 組の中央値
    cm = {}
    p1 = main_['part1_event_time_decay']
    for form in PB:
        cm[form] = {}
        for k in range(1, KMAX + 1):
            v = list(p1[form]['by_event_year'][str(k)]['cohort_annual_excess_pct'].values())
            cm[form][k] = {'n': len(v), 'median': round(S.median(v), 2) if v else None, 'mean': round(S.mean(v), 2) if v else None}
        v25 = [x for k in (2, 3, 4, 5) for x in p1[form]['by_event_year'][str(k)]['cohort_annual_excess_pct'].values()]
        cm[form]['years_2_5_pooled'] = {'n': len(v25), 'median': round(S.median(v25), 2), 'mean': round(S.mean(v25), 2),
                                        'share_positive': round(sum(1 for x in v25 if x > 0) / len(v25), 3)}
    log('E2 済', round(time.time() - t0, 1))
    # 1社ずつ除く
    names = sorted({x for J in SR.YEARS for x in F['M100_T5'][J]})
    loo = {'decay_aged25_M100_T5': {}, 'castle_mech_N5': {}}
    cfgs, keys = [], []
    Bx_all = {}
    for x in names:
        ux = filt(uni, lambda r, x=x: r['ticker'] != x)
        Fx, Bx, _u, _p = forms(ux)
        bx = SR.simulate(Bx['M100'], R)[0]
        Bx_all[x] = bx
        ag = aged_of(Fx['M100_T5'], R)
        a1 = M.excess_stats(ag, bx); a2 = M.excess_stats(ag, fm)
        loo['decay_aged25_M100_T5'][x] = {'vs_M100_rebuilt': [a1['ex_ann'], a1['t']], 'vs_FF_Mkt': [a2['ex_ann'], a2['t']]}
        keys.append(x); cfgs.append(dict(base, rule='mech', sel={J: Fx['M100_T5'][J] for J in SR.YEARS}, core='SPX', regime='pretax', record=True))
    cb_core = RES[('core_only', 'SPX', 'pretax', False)]['held_jpy']
    for x, r in zip(keys, run_many(cfgs)):
        s_ = r['twr_castle']
        a1 = M.excess_stats(s_, Bx_all[x]); a2 = M.excess_stats(s_, fm)
        loo['castle_mech_N5'][x] = {'vs_M100_rebuilt': [a1['ex_ann'], a1['t']], 'vs_FF_Mkt': [a2['ex_ann'], a2['t']],
                                    'wealth_ratio_vs_SPX_core_pretax': round(r['held_jpy'] / cb_core, 4)}
    loo_sum = {}
    for k, v in loo.items():
        ff_ = sorted((vv['vs_FF_Mkt'][0], x) for x, vv in v.items())
        mb = sorted((vv['vs_M100_rebuilt'][0], x) for x, vv in v.items())
        loo_sum[k] = {'n_names': len(v), 'min_vs_FF_Mkt': ff_[0], 'median_vs_FF_Mkt': ff_[len(ff_) // 2][0], 'max_vs_FF_Mkt': ff_[-1],
                      'min_vs_M100': mb[0], 'median_vs_M100': mb[len(mb) // 2][0], 'min_t_vs_FF_Mkt': min(((vv['vs_FF_Mkt'][1], x) for x, vv in v.items()))}
    log('1社ずつ 済', round(time.time() - t0, 1))
    # 城の中身（mech_N5・終わり）
    rp = RES[('castle_mech_N5', 'SPX', 'pretax', 'pos')]
    tot = sum(rp['castle_end_jpy'].values())
    top = sorted(rp['castle_end_jpy'].items(), key=lambda z: -z[1])
    contrib = {'castle_end_total_jpy': round(tot), 'n_names': len(top),
               'top10': [{'ticker': a, 'end_jpy': round(v), 'share': round(v / tot, 3), 'bought_jpy': round(rp['bought_jpy'].get(a, 0.0)),
                          'multiple': round(v / rp['bought_jpy'][a], 2) if rp['bought_jpy'].get(a) else None} for a, v in top[:10]],
               'mega6_share_of_end_value': round(sum(v for a, v in top if a in MEGA6) / tot, 3),
               'bought_total_jpy': round(sum(rp['bought_jpy'].values()))}
    mic = {core: {reg: None for reg in ('pretax', 'taxable', 'nisa_q')} for core in ('SPX', 'NDX')}
    for core in ('SPX', 'NDX'):
        for reg in ('pretax', 'taxable', 'nisa_q'):
            fld = 'held_jpy' if reg == 'pretax' else 'liquidated_jpy'
            mic[core][reg] = round(RES[('megacap_index_castle', core, reg, False)][fld] / core_w[(core, reg)][fld], 4)
    tested2 = [{'name': nm, 'role': 'exploratory_prereg2', 'grade': graded[nm]['grade']} for nm in MEM]
    tested2 += [{'name': f'loo_{k}_{x}', 'role': 'report_leave_one_out_prereg2', 'grade': None} for k in loo for x in loo[k]]
    tested2 += [{'name': 'megacap_index_castle', 'role': 'report_control_prereg2', 'grade': None}]
    main_['exploratory_prereg2'] = {'prereg': PRE2, 'prereg_commit': git_sha(f'out/{PRE2}'), 'graded_E2': graded, 'holm_E2': hp,
                                    'wealth_E2': E2wealth, 'subperiods_primary': subs, 'cohort_median_primary': cm,
                                    'leave_one_name_out': loo, 'leave_one_name_out_summary': loo_sum, 'castle_mech_N5_contributors': contrib,
                                    'megacap_index_castle_wealth_ratio': mic, 'runtime_s': round(time.time() - t0, 1)}
    main_['tested'] = [x for x in main_['tested'] if not str(x.get('role', '')).endswith('prereg2')] + tested2
    main_['n_tested'] = len(main_['tested'])
    p_ = M.save(OUT, main_)
    log('保存', p_, round(os.path.getsize(p_) / 1e6, 2), 'MB')


# ───────────────────────── 探索の対照（prereg3） ─────────────────────────
PRE3 = 'mw_castle_mech_prereg3.json'


def run3():
    global D
    t0 = time.time()
    outp = os.path.join(M.BASE, 'out', OUT)
    main_ = json.load(open(outp))
    D = load()
    uni = D['uni']
    F, B, UT, pools = forms(uni)
    R = D['R']
    fm = {k: v for k, v in D['ff']['mkt'].items() if START <= k <= END}
    spy = D['cores']['SPX'][0]
    bench0 = {nm: SR.simulate(B[nm], R)[0] for nm in B}
    nullF = {'aged_null_U_all': B['U_all'], 'aged_null_M100': B['M100'], 'aged_null_M100_exfin': {}}
    for J in SR.YEARS:
        u = uni[J]
        m100 = {c: u[c] for c in sorted(u, key=lambda c: -u[c]['fcap'])[:100]}
        Rm, _sc = SR.scores(m100)
        nullF['aged_null_M100_exfin'][J] = {m100[c]['ticker']: m100[c]['fcap'] for c in Rm}
    nulls, nser = {}, {}
    for nm, Fm in nullF.items():
        ag = aged_of(Fm, R)
        nser[nm] = ag
        pb = 'U_all' if nm == 'aged_null_U_all' else 'M100'
        nulls[nm] = {'vs_' + pb: M.excess_stats(ag, bench0[pb]), 'vs_FF_Mkt': M.excess_stats(ag, fm), 'vs_SPY': M.excess_stats(ag, spy),
                     'subperiods_vs_' + pb: sub2(ag, bench0[pb])}
    adj = {}
    for form, nn in (('T3VW', 'aged_null_U_all'), ('M100_T3VW', 'aged_null_M100'), ('M100_T5', 'aged_null_M100')):
        ag = aged_of(F[form], R)
        diff = {m: ag[m] - nser[nn][m] for m in ag if m in nser[nn]}
        zero = {m: 0.0 for m in diff}
        st = M.excess_stats(diff, zero)
        adj[form] = {'minus': nn, 'diff_stats': st, 'persist_after_control': bool(st and st['ex_ann'] > 0 and (st['t'] or 0) >= 1.65),
                     'subperiods': sub2(diff, zero)}
    # 無作為の5社の2〜5年目
    rng = random.Random(SEED)
    T5 = aged_of(F['M100_T5'], R)
    t5ex = M.excess_stats(T5, bench0['M100'])['ex_ann']
    rnd = {}
    for pool in ('b1_M100_exfin', 'b2_M100_top_third_cop_at'):
        P = pools[pool]
        v = []
        for i in range(R_DRAWS):
            Fr = {J: {x: 1.0 for x in rng.sample(P[J], min(5, len(P[J])))} for J in SR.YEARS}
            ag = aged_of(Fr, R)
            v.append(M.excess_stats(ag, bench0['M100'])['ex_ann'])
        v.sort()
        q = lambda p: round(v[min(len(v) - 1, int(p * len(v)))], 2)
        rnd[pool] = {'draws': len(v), 'share_positive': round(sum(1 for x in v if x > 0) / len(v), 3), 'p05': q(0.05), 'median': q(0.5), 'p95': q(0.95),
                     'mean': round(S.mean(v), 2), 'M100_T5_ex': t5ex, 'M100_T5_percentile': round(sum(1 for x in v if x < t5ex) / len(v), 3)}
    main_['exploratory_prereg3'] = {'prereg': PRE3, 'prereg_commit': git_sha(f'out/{PRE3}'), 'aged_null_controls': nulls,
                                    'adjusted_persistence': adj, 'aged_random5_vs_M100': rnd, 'runtime_s': round(time.time() - t0, 1)}
    tested3 = [{'name': nm, 'role': 'report_control_prereg3', 'grade': None} for nm in nulls] + \
              [{'name': f'adjusted_persistence_{f}', 'role': 'report_control_prereg3', 'grade': None} for f in adj] + \
              [{'name': f'aged_random5_{p}', 'role': 'report_distribution_prereg3', 'grade': None} for p in rnd]
    main_['tested'] = [x for x in main_['tested'] if not str(x.get('role', '')).endswith('prereg3')] + tested3
    main_['n_tested'] = len(main_['tested'])
    p_ = M.save(OUT, main_)
    log('保存', p_, round(os.path.getsize(p_) / 1e6, 2), 'MB', round(time.time() - t0, 1))


def finalize():
    """見出し（JSON の数字を拾うだけ・新しい検定はしない）"""
    outp = os.path.join(M.BASE, 'out', OUT)
    d = json.load(open(outp))
    p1 = d['part1_event_time_decay']; g = d['graded_primary']; W = d['wealth_full_window']
    e2 = d.get('exploratory_prereg2', {}); e3 = d.get('exploratory_prereg3', {})
    h = {'grades': {nm: r['grade'] for nm, r in g.items()},
         'persistence_aged_2_5': {f: {'vs': p1[f]['primary_benchmark'], 'ex_ann': p1[f]['aged_2_5']['vs_' + p1[f]['primary_benchmark']]['ex_ann'],
                                      't': p1[f]['aged_2_5']['vs_' + p1[f]['primary_benchmark']]['t'], 'pass': p1[f]['aged_2_5']['persistence_criterion_pass'],
                                      'after_null_control': (e3.get('adjusted_persistence', {}).get(f, {}).get('diff_stats') or {}).get('ex_ann'),
                                      'ex_mega6_vs_FF_Mkt': (e2.get('graded_E2', {}).get(f'decay_aged25_{f}_exMega6', {}).get('full') or {}).get('ex_ann')}
                                  for f in ('T3VW', 'M100_T3VW', 'M100_T5')},
         'event_year_ex_vs_primary': {f: {k: p1[f]['by_event_year'][str(k)]['vs_' + p1[f]['primary_benchmark']]['ex_ann'] for k in range(1, KMAX + 1)} for f in ('T3VW', 'M100_T3VW', 'M100_T5')},
         'castle_vs_FF_Mkt': {nm: [r['full']['ex_ann'], r['full']['t'], r['holm_p']] for nm, r in g.items() if nm.startswith('castle')},
         'wealth_ratio_mech_N5': {c: {reg: W['mech_N5'][c][reg]['ratio_vs_core_liquidated'] for reg in W['mech_N5'][c]} for c in W['mech_N5']},
         'wealth_ratio_annual_N5': {c: {reg: W['annual_N5'][c][reg]['ratio_vs_core_liquidated'] for reg in W['annual_N5'][c]} for c in W['annual_N5']},
         'windows_p_beat': {H: {arm: {c: d['windows_10_15y'][H][arm][c]['taxable']['p_beat_core'] for c in d['windows_10_15y'][H][arm]} for arm in d['windows_10_15y'][H]} for H in d['windows_10_15y']},
         'bootstrap_p_beat': {k: {H: v[H]['p_beat_core'] for H in v} for k, v in d['cohort_bootstrap'].items()},
         'years_to_t2_mech_N5': {c: d['years_to_t2'][f'mech_N5|{c}']['years_needed_from_t'] for c in ('SPX', 'NDX')}}
    d['ex27_out_of_sample'] = ex27_rerun()
    d['headline'] = h
    d['deviations'] = [
        '事前登録の out_of_sample（EX-27 1996〜2001 での再実行）は行えなかった: 実行の時点で ex27 の角度の社ごとのパネルがリポジトリに無く、SEC を二重に叩かない約束（ルール5）どおり自分では集めていない＝N/A',
        '事前登録の後に模型へ足したのは報告用の記録だけ（社ごとに買った円・終わりの時価。売買・税・判定の規則は不変）。自己検査6項目は足した後も合格',
        '格付けの保有期間はデータのある 2010-07（decay は 2011-07）〜2026-08＝全期間と同じ。訓練期間なし・16年しか無いので転がる20年窓（C4）も構造的に不合格',
        '配当利回り（税の計算だけに使う）は adjclose と close のリターンの差。配当の無い月にもごく小さな正の値が出る（丸めの誤差・SPY で年1.76% と常識の範囲）',
        '事前登録の『NISA の枠つき』は枠の中に収まらない分を課税口座へ回す併用（nisa_q）。月¥100,000 の感度では生涯枠がほぼ16年もつので、NISA だけに近い姿はそちらで見る',
        '1年目の点検: T3VW 対 U_all は 2026-06 まで +1.81%/年（mw_sec_replication の2026-08まで +1.90 と、最後の2か月の分だけ違う＝想定どおり）',
    ]
    M.save(OUT, d)
    print(json.dumps(h, ensure_ascii=False, indent=1))


def check():
    global D
    D = load()
    F, B, UT, pools = forms(D['uni'])
    for J in SR.YEARS:
        print(J, len(UT[J]), {k: len(F[k][J]) for k in F}, {k: len(v[J]) for k, v in pools.items()})
    print('fx', min(D['fx']), max(D['fx']), 'cores', {k: (min(v[0]), max(v[0])) for k, v in D['cores'].items()})


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    elif '--prereg2' in sys.argv:
        run2()
    elif '--prereg3' in sys.argv:
        run3()
    elif '--finalize' in sys.argv:
        finalize()
    elif '--check' in sys.argv:
        check()
    else:
        main()
