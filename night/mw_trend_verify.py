#!/usr/bin/env python3
"""night/mw_trend_verify.py — 角度 trend（第5族: 業種ごとの10か月線×倍率）の『反証の検証』（読むだけ・門には不使用）

目的: out/mw_trend.json が S/B と格付けした候補（S1_L2, S3_L2, S1_L3, S3_L3, S2_L3, S2_L2）を、
研究者のコード（night/mw_trend.py）を使わず**自分で組み直して**数字を出し直し、崩れる所を探す。
mw_common からは取得（french_tables / ff_factors / get / jkp_mkt）だけを使い、
ポートフォリオの組み立て・超過・CAGR・NW t・転がる窓・シャープレシオ・判定の線は全部ここで書き直した。

点検の項目
 V0 再現（研究者の約束どおりの式で同じ数字が出るか・丸めない t）
 V1 重みの時点（French の Average Firm Size が月初か月末か＝後知恵の有無）を French Mkt への追従で確かめる
 V2 実行の遅れ（同じ終値で売買 → 翌日・2日・5日・1か月遅れ）と、日次の持ち高の伸び方（月中に放置 vs 日々L倍の ETF）
 V3 相手を『同じリスクまで倍率を掛けた市場』にしたら（β・倍率だけの勝ちか）
 V4 区間の依存（保有期間の前半/後半・2008 抜き・2008+2022 抜き・2020-21 抜き・1998-2000 抜き・2010〜・1934〜）
 V5 近い値の規則（N=6/8/9/11/12/14 か月）
 V6 業種の依存（1業種ずつ『常に持つ』にしてタイミングを外す）
 V7 費用と借入（実際の売買量〔倍率の掛け直しを含む〕・0.30%/0.50%・借入 RF+1/2/3%）
 V8 シャープレシオの差の検定（Jobson-Korkie/Memmel＋ブロック・ブートストラップ）と CAPM α
 V9 米国外（JKP 6か国）で、相手を『等分の業種』ではなく『その国の時価加重の市場』にしたら
 V10 日本の課税口座の近似（毎年の実現益に20.315%・3年繰越）
 V11 多重検定（角度の中の判定104本・探索の第5族であること）
"""
import sys, os, math, json, random, zipfile, io, csv, datetime, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M   # 取得だけに使う

TRAIN_END, HOLD = 200612, 200701
END = 202608
OUTP = os.path.join(M.BASE, 'out', 'mw_trend_verify.json')
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── 月の算術 ─────────────────────────
def mshift(m, k):
    y, mo = divmod(m, 100)
    i = y * 12 + mo - 1 + k
    return (i // 12) * 100 + i % 12 + 1


# ───────────────────────── データ ─────────────────────────
def ind_monthly(name):
    t = M.french_tables(name)

    def pick(prefix):
        for k, v in t.items():
            if k.startswith(prefix) and v['freq'] == 'monthly':
                return v
        raise KeyError(prefix)
    vr, nf, sz = pick('Average Value Weighted Returns -- Monthly'), pick('Number of Firms in Portfolios'), pick('Average Firm Size')
    cols = vr['cols']
    R = {c: {} for c in cols}
    CAP = {c: {} for c in cols}
    for m, row in vr['data'].items():
        for c, x in zip(cols, row):
            if x is not None:
                R[c][m] = x / 100.0
    for m, row in sz['data'].items():
        nrow = nf['data'].get(m)
        if not nrow:
            continue
        for c, a, n in zip(cols, row, nrow):
            if a is not None and n is not None and a > 0 and n > 0:
                CAP[c][m] = a * n
    return cols, R, CAP


def ind_daily(name):
    t = M.french_tables(name)
    for k, v in t.items():
        if k.startswith('Average Value Weighted Returns -- Daily') and v['freq'] == 'daily':
            cols = v['cols']
            R = {c: {} for c in cols}
            for d, row in v['data'].items():
                for c, x in zip(cols, row):
                    if x is not None:
                        R[c][d] = x / 100.0
            return cols, R
    raise KeyError(name)


def ff_monthly():
    f = M.ff_factors('monthly')
    return f['mkt'], f['rf'], f['mktrf']


def ff_daily():
    f = M.ff_factors('daily')
    return f['mkt'], f['rf']


# ───────────────────────── 信号（自前） ─────────────────────────
def sma_signals(cols, R, N):
    """業種ごとの総リターン指数（月末）> 直近 N 本の月末値の平均 → 1。月が途切れたら履歴を捨てる"""
    sig = {}
    for c in cols:
        lvl, hist, s, prevk = 1.0, [], {}, None
        for k in sorted(R[c]):
            if prevk is not None and k != mshift(prevk, 1):
                hist = []
            lvl *= 1 + R[c][k]
            hist.append(lvl)
            if len(hist) >= N:
                s[k] = 1 if lvl > sum(hist[-N:]) / N else 0
            prevk = k
        sig[c] = s
    return sig


# ───────────────────────── 月次の組み立て（自前） ─────────────────────────
def bt_monthly(cols, R, CAP, rf, sig, L, start=192705, end=END, wlag=1, skip=0, spread=0.005, fee=0.009,
               cost=0.001, turnover='flip', force_on=(), missing_on=1, borrow_add=None):
    """月 m: 重み = 表の月 (m−wlag) の時価総額、信号 = 月 (m−1−skip) の月末。株の割合 E = L×Σ_上 w。
    E>1 なら借入 (E−1)×(RF+spread) と経費 fee（研究者の事前登録の式）。
    turnover: 'flip' = 出入りした業種の重み×L（研究者の式）/ 'full' = 前月の持ち高が値動きで伸びた後から目標へ戻す実際の売買量
    borrow_add: {月: 年率の上乗せ} を渡すと spread の代わりに使う"""
    g_out, n_out, E_out = {}, {}, {}
    prev_on = prev_h = prev_r = None
    prev_g = 0.0
    for m in sorted(k for k in rf if start <= k <= end):
        wm = mshift(m, -wlag)
        inc = [c for c in cols if m in R[c] and wm in CAP[c]]
        if not inc:
            continue
        W = sum(CAP[c][wm] for c in inc)
        w = {c: CAP[c][wm] / W for c in inc}
        sm = mshift(m, -1 - skip)
        on = {c: (1 if c in force_on else sig[c].get(sm, missing_on)) for c in inc}
        f = sum(w[c] for c in inc if on[c])
        E = L * f
        eq = sum(w[c] * R[c][m] for c in inc if on[c])
        sp = spread if borrow_add is None else borrow_add.get(m, spread)
        g = L * eq + (1 - E) * rf[m]
        if E > 1:
            g -= ((E - 1) * sp + fee) / 12
        g = max(g, -1.0)
        h = {c: L * w[c] for c in inc if on[c]}
        if turnover == 'flip':
            tv = sum(w[c] * L for c in inc if prev_on is not None and c in prev_on and prev_on[c] != on[c])
        else:
            if prev_h is None:
                tv = 0.0
            else:
                tv = 0.0
                for c in set(h) | set(prev_h):
                    pre = prev_h.get(c, 0.0) * (1 + prev_r.get(c, 0.0)) / (1 + prev_g)
                    tv += abs(h.get(c, 0.0) - pre)
        g_out[m] = g
        n_out[m] = (1 + g) * (1 - cost * tv) - 1
        E_out[m] = E
        prev_on, prev_h, prev_g = on, h, g
        prev_r = {c: R[c][m] for c in inc}
    return g_out, n_out, E_out


def turnover_stats(cols, R, CAP, rf, sig, L, a=HOLD, z=END):
    """実際の年あたり売買量（full）と研究者の式（flip）の比較"""
    out = {}
    for mode in ('flip', 'full'):
        g, n, _ = bt_monthly(cols, R, CAP, rf, sig, L, cost=1.0, turnover=mode)
        ks = [k for k in g if a <= k <= z]
        # cost=1.0 なので (1+g)(1−tv)−1 から tv を戻す
        tv = [(1 - (1 + n[k]) / (1 + g[k])) for k in ks]
        out[mode] = round(sum(tv) / len(ks) * 12, 2)
    return out


# ───────────────────────── 日次の組み立て（自前） ─────────────────────────
def bt_daily(D, cols, Rd, CAP, rfd, L, N=10, lag=1, mode='margin', spread=0.005, fee=0.009, etf_fee=0.0095,
             cost=0.001, turnover='flip'):
    """日次。月末の終値で信号（業種の日次総リターン指数の月末値 > 直近 N 本の月末値の平均）、
    lag 営業日あとの終値で入れ替える（lag=0 は信号と同じ終値）。重みは入る月の前月の表の時価総額。
    mode='margin': 業種を L×w で持ち、足りない分は借入（RF+spread）、E>1 の日は経費 fee/252（研究者の式）。月中は放置。
    mode='etf'   : 上の業種ごとに w の元本を『日々 L 倍に戻す ETF』（経費 etf_fee・借入 RF+spread）へ。残りは RF。月中は放置。
    欠けた日次リターン（49業種で数百日）は、その日だけ現金（RF）と同じ扱いにして件数を数える"""
    n = len(D)
    me = [i for i in range(n - 1) if D[i] // 100 != D[i + 1] // 100] + [n - 1]
    lvl = {c: 1.0 for c in cols}
    hist = {c: [] for c in cols}
    sig_at = {}
    mei = set(me)
    for i, d in enumerate(D):
        for c in cols:
            r = Rd[c].get(d)
            if r is not None:
                lvl[c] *= 1 + r
        if i in mei:
            s = {}
            for c in cols:
                if Rd[c].get(d) is None and not hist[c]:
                    continue
                hist[c].append(lvl[c])
                if len(hist[c]) >= N:
                    s[c] = 1 if lvl[c] > sum(hist[c][-N:]) / N else 0
            sig_at[i] = s
    reb = {}
    for i in me:
        j = i + lag
        if j < n:
            reb[j] = i
    V = 1.0
    h = {}
    cash = 1.0
    started = False
    prev_on = None
    rets = {}
    miss = 0
    for i in range(n):
        d = D[i]
        if started:
            V0 = V
            sp = spread(d) if callable(spread) else spread
            for c in list(h):
                r = Rd[c].get(d)
                if r is None:
                    r = rfd[d]
                    miss += 1
                if mode == 'etf':
                    r = L * r - (L - 1) * (rfd[d] + sp / 252) - (etf_fee / 252 if L != 1 else 0.0)
                h[c] *= 1 + r
            gx = sum(h.values())
            if cash >= 0:
                cash *= 1 + rfd[d]
            else:
                cash *= 1 + rfd[d] + sp / 252
            if mode == 'margin' and L > 1 and gx > V0 * (1 + 1e-12):
                cash -= fee / 252 * V0
            V = gx + cash
            rets[d] = V / V0 - 1
        if i in reb:
            i0 = reb[i]
            s = sig_at.get(i0, {})
            # 入る月＝ i0 の翌日の月
            m_next = D[i0 + 1] // 100 if i0 + 1 < n else None
            if m_next is None:
                continue
            wm = mshift(m_next, -1)
            inc = [c for c in cols if wm in CAP[c] and c in s]
            if not inc:
                continue
            W = sum(CAP[c][wm] for c in inc)
            w = {c: CAP[c][wm] / W for c in inc}
            on = {c: s[c] for c in inc}
            if mode == 'margin':
                tgt = {c: V * L * w[c] for c in inc if on[c]}
            else:
                tgt = {c: V * w[c] for c in inc if on[c]}
            if turnover == 'flip':
                tv = sum(w[c] * L for c in inc if prev_on is not None and c in prev_on and prev_on[c] != on[c])
            else:
                tv = sum(abs(tgt.get(c, 0.0) - h.get(c, 0.0)) for c in set(tgt) | set(h)) / V if started else 0.0
            cu = cost(d) if callable(cost) else cost
            V *= 1 - cu * tv
            if started and d in rets:
                rets[d] = (1 + rets[d]) * (1 - cu * tv) - 1
            if mode == 'margin':
                h = {c: V * L * w[c] for c in inc if on[c]}
            else:
                h = {c: V * w[c] for c in inc if on[c]}
            cash = V - sum(h.values())
            prev_on = on
            started = True
    # 月次へ（最初の不完全な月は捨てる）
    mo = {}
    for d in sorted(rets):
        ym = d // 100
        mo[ym] = (1 + mo.get(ym, 0.0)) * (1 + rets[d]) - 1
    ks = sorted(mo)
    if ks:
        mo.pop(ks[0])
    return mo, miss


# ───────────────────────── 統計（自前） ─────────────────────────
def keys_of(*ds, a=None, z=None, drop=None):
    ks = set(ds[0])
    for d in ds[1:]:
        ks &= set(d)
    ks = sorted(k for k in ks if (a is None or k >= a) and (z is None or k <= z))
    if drop:
        ks = [k for k in ks if not any(lo <= k <= hi for lo, hi in drop)]
    return ks


def nw(x, lag=12):
    n = len(x)
    mu = sum(x) / n
    e = [v - mu for v in x]
    s = sum(v * v for v in e) / n
    for Lg in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - Lg / (lag + 1)) * sum(e[i] * e[i - Lg] for i in range(Lg, n)) / n
    return mu / math.sqrt(s / n) if s > 0 else float('nan')


def gcagr(xs):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def cmp(s, b, a=None, z=None, drop=None):
    ks = keys_of(s, b, a=a, z=z, drop=drop)
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nw(ex)
    cs, cb = gcagr([s[k] for k in ks]), gcagr([b[k] for k in ks])
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex_ann': round(sum(ex) / len(ex) * 1200, 2), 't': round(t, 3),
            't_raw': t, 'cagr_s': round(cs * 100, 2), 'cagr_b': round(cb * 100, 2), 'cagr_diff': round((cs - cb) * 100, 2)}


def sharpe(s, rf, a=None, z=None, drop=None):
    ks = keys_of(s, rf, a=a, z=z, drop=drop)
    x = [s[k] - rf[k] for k in ks]
    sd = S.stdev(x)
    return round(sum(x) / len(x) / sd * math.sqrt(12), 3)


def vol(s, a=None, z=None):
    ks = keys_of(s, a=a, z=z)
    return S.stdev([s[k] for k in ks]) * math.sqrt(12)


def capm(s, b, rf, a=None, z=None, drop=None):
    ks = keys_of(s, b, rf, a=a, z=z, drop=drop)
    y = [s[k] - rf[k] for k in ks]
    x = [b[k] - rf[k] for k in ks]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sum((xi - mx) ** 2 for xi in x)
    res = [yi - beta * xi for xi, yi in zip(x, y)]
    return {'alpha_ann': round(sum(res) / len(res) * 1200, 2), 't': round(nw(res), 2), 'beta': round(beta, 3)}


def roll20(s, b, years=20):
    ks = set(s) & set(b)
    y0, y1 = min(ks) // 100, max(ks) // 100
    out = []
    for y in range(y0, y1 + 1):
        a, z = y * 100 + 7, (y + years) * 100 + 6
        w = [k for k in sorted(ks) if a <= k <= z]
        if len(w) < years * 12:
            continue
        out.append((y, (gcagr([s[k] for k in w]) - gcagr([b[k] for k in w])) * 100))
    if not out:
        return None
    wins = sum(1 for _, v in out if v > 0)
    return {'windows': len(out), 'wins': wins, 'win_rate': round(wins / len(out), 3),
            'median': round(sorted(v for _, v in out)[len(out) // 2], 2),
            'worst': [out[min(range(len(out)), key=lambda i: out[i][1])][0], round(min(v for _, v in out), 2)]}


def dca20(s, b, years=20):
    ks = sorted(set(s) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, 12):
        w = ks[i:i + n]
        vs = vb = 0.0
        for k in w:
            vs = (vs + 1) * (1 + s[k])
            vb = (vb + 1) * (1 + b[k])
        out.append(vs / vb)
    v = sorted(out)
    return {'windows': len(v), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': round(v[len(v) // 2], 3)}


def sr_test(s, b, rf, a=None, z=None):
    """Jobson-Korkie（Memmel 2003 の補正）"""
    ks = keys_of(s, b, rf, a=a, z=z)
    x = [s[k] - rf[k] for k in ks]
    y = [b[k] - rf[k] for k in ks]
    T = len(ks)
    s1, s2 = S.mean(x) / S.stdev(x), S.mean(y) / S.stdev(y)
    mx, my = S.mean(x), S.mean(y)
    rho = sum((u - mx) * (v - my) for u, v in zip(x, y)) / math.sqrt(sum((u - mx) ** 2 for u in x) * sum((v - my) ** 2 for v in y))
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T
    zv = (s1 - s2) / math.sqrt(var)
    return {'sr_s': round(s1 * math.sqrt(12), 3), 'sr_b': round(s2 * math.sqrt(12), 3), 'z': round(zv, 2), 'p_two': round(math.erfc(abs(zv) / math.sqrt(2)), 3)}


def sr_boot(s, b, rf, a=None, z=None, block=12, reps=2000, seed=7):
    """円環ブロック・ブートストラップ（12か月）でシャープレシオの差が0以下になる割合（片側 p）"""
    ks = keys_of(s, b, rf, a=a, z=z)
    x = [s[k] - rf[k] for k in ks]
    y = [b[k] - rf[k] for k in ks]
    T = len(ks)
    rnd = random.Random(seed)

    def sr(v):
        sd = S.pstdev(v)
        return sum(v) / len(v) / sd if sd else 0.0
    d0 = sr(x) - sr(y)
    cnt = 0
    for _ in range(reps):
        idx = []
        while len(idx) < T:
            st = rnd.randrange(T)
            idx.extend((st + j) % T for j in range(block))
        idx = idx[:T]
        xx = [x[i] for i in idx]
        yy = [y[i] for i in idx]
        if sr(xx) - sr(yy) <= 0:
            cnt += 1
    return {'diff_ann': round(d0 * math.sqrt(12), 3), 'p_one_sided': round(cnt / reps, 3)}


def lev_market(b, rf, k, spread=0.005):
    """市場を k 倍（月次で掛け直し・借入 RF+spread）"""
    return {m: rf[m] + k * (b[m] - rf[m]) - (max(k - 1, 0) * spread / 12) for m in b if m in rf}


def p_two(t):
    return math.erfc(abs(t) / math.sqrt(2))


# ───────────────────────── 判定（自前・out/mw_prereg.json の線） ─────────────────────────
def my_grade(full, train, hold, costhold, roll, sh_train, sh_hold, repl=None, holm_p=None):
    c = {
        'C1_train': train['ex_ann'] > 0 and train['t_raw'] >= 2.0,
        'C2_hold_sign': hold['ex_ann'] > 0 and hold['cagr_diff'] > 0,
        'C3_hold_t': hold['t_raw'] >= 1.65,
        'C4_roll20': roll['win_rate'] >= 0.8,
        'C5_repl': None if repl is None else repl,
        'C6_net_cost': costhold['ex_ann'] > 0 and costhold['cagr_diff'] > 0,
        'C7_multi': full['t_raw'] >= 3.0 or (holm_p is not None and holm_p < 0.05),
        'C8_sharpe': sh_train[0] > sh_train[1] and sh_hold[0] > sh_hold[1],
    }
    ok = lambda k: c[k] is True
    na = lambda k: c[k] is None or c[k] is True
    base = ok('C1_train') and ok('C2_hold_sign') and ok('C6_net_cost') and ok('C8_sharpe')
    if base and ok('C3_hold_t') and ok('C4_roll20') and ok('C7_multi') and na('C5_repl'):
        g = 'S'
    elif base and ok('C4_roll20') and ok('C7_multi') and (ok('C3_hold_t') or ok('C5_repl')):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


def strip(d):
    if isinstance(d, dict):
        return {k: strip(v) for k, v in d.items() if k != 't_raw'}
    if isinstance(d, list):
        return [strip(v) for v in d]
    return d


# ───────────────────────── JKP（米国外） ─────────────────────────
def jkp_ind(ctry):
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{ctry}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = M.get(url, name=f'jkp_industry_{ctry}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    R = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        R.setdefault(x['gics'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
    return R


def jkp_country(ctry, rf, L, cost=0.001):
    Rx = jkp_ind(ctry)
    cols = sorted(Rx)
    R = {g: {m: v + rf[m] for m, v in Rx[g].items() if m in rf} for g in cols}
    sig = sma_signals(cols, R, 10)
    ms = sorted(set().union(*[set(R[g]) for g in cols]))
    gross, net, bh = {}, {}, {}
    prev_on = None
    for m in ms[1:]:
        mp = mshift(m, -1)
        inc = [g for g in cols if m in R[g] and mp in sig[g]]
        if len(inc) < 3 or m not in rf:
            continue
        w = 1.0 / len(inc)
        on = {g: sig[g][mp] for g in inc}
        f = w * sum(on.values())
        E = L * f
        eq = sum(w * R[g][m] for g in inc if on[g])
        gr = L * eq + (1 - E) * rf[m] - (((E - 1) * 0.005 + 0.009) / 12 if E > 1 else 0.0)
        tv = sum(w * L for g in inc if prev_on is not None and g in prev_on and prev_on[g] != on[g])
        gross[m] = gr
        net[m] = (1 + gr) * (1 - cost * tv) - 1
        bh[m] = sum(w * R[g][m] for g in inc)
        prev_on = on
    try:
        mk = M.jkp_mkt(ctry, 'vw')
        mkt = {m: v + rf[m] for m, v in mk.items() if m in rf}
    except Exception as e:  # noqa
        mkt = None
        log('JKP mkt 取得失敗', ctry, e)
    return net, bh, mkt


# ───────────────────────── 税（日本の課税口座の近似） ─────────────────────────
def tax_monthly(cols, R, CAP, rf, sig, L, a, z, t=0.20315, etf_fee=0.0095, spread=0.005, cost=0.001):
    """業種ごとに『L 倍の業種 ETF』（月次近似: L r − (L−1)(RF+spread)/12 − fee/12）を上の業種だけ w の元本で持つ。
    毎月、目標へ戻す売買（総平均法で実現益）。実現益・利息は暦年で通算し 20.315%、損は3年繰越。窓の終わりに全部売って課税。
    相手: 市場を窓の初めに買い、終わりに売って課税（配当課税は両方とも無視）"""
    V = 1.0
    P = {}
    B = {}
    cash = 1.0
    carry = []  # [(年, 損)]
    realized = 0.0
    yr = None
    ks = [m for m in sorted(rf) if a <= m <= z]

    def settle(y, G):
        nonlocal carry
        carry = [(yy, l) for yy, l in carry if y - yy <= 3]
        if G > 0:
            for i, (yy, l) in enumerate(carry):
                use = min(l, G)
                G -= use
                carry[i] = (yy, l - use)
            carry = [(yy, l) for yy, l in carry if l > 1e-12]
            return G * t
        elif G < 0:
            carry.append((y, -G))
        return 0.0
    for m in ks:
        y = m // 100
        if yr is not None and y != yr:
            tax = settle(yr, realized)
            cash -= tax
            realized = 0.0
        yr = y
        wm = mshift(m, -1)
        inc = [c for c in cols if m in R[c] and wm in CAP[c]]
        W = sum(CAP[c][wm] for c in inc)
        w = {c: CAP[c][wm] / W for c in inc}
        on = {c: sig[c].get(mshift(m, -1), 1) for c in inc}
        V = sum(P.values()) + cash
        tgt = {c: V * w[c] for c in inc if on[c]}
        tv = 0.0
        for c in set(tgt) | set(P):
            cur = P.get(c, 0.0)
            new = tgt.get(c, 0.0)
            if new < cur:
                sell = cur - new
                realized += sell * (1 - B[c] / cur) if cur > 0 else 0.0
                B[c] = B[c] * new / cur if cur > 0 else 0.0
                cash += sell
            elif new > cur:
                B[c] = B.get(c, 0.0) + (new - cur)
                cash -= new - cur
            P[c] = new
            tv += abs(new - cur)
        cash -= cost * tv
        for c in list(P):
            if P[c] <= 0:
                P.pop(c)
                B.pop(c, None)
                continue
            r = R[c][m]
            er = L * r - (L - 1) * (rf[m] + spread / 12) - (etf_fee / 12 if L != 1 else 0.0)
            P[c] *= 1 + er
        intr = cash * rf[m]
        if intr > 0:
            realized += intr
        cash += intr
    # 窓の終わり: 全部売る
    for c in list(P):
        realized += P[c] - B[c]
        cash += P[c]
    cash -= settle(yr, realized)
    n = len(ks)
    strat = cash ** (12 / n) - 1
    # 買い持ち
    wb = 1.0
    for m in ks:
        wb *= 1 + MKT[m]
    bh_after = (wb - max(wb - 1, 0) * t) ** (12 / n) - 1
    bh_pre = wb ** (12 / n) - 1
    return {'strategy_after_tax_cagr': round(strat * 100, 2), 'market_after_tax_cagr': round(bh_after * 100, 2),
            'market_pre_tax_cagr': round(bh_pre * 100, 2), 'diff_after_tax': round((strat - bh_after) * 100, 2)}


# ───────────────────────── 本体 ─────────────────────────
MKT = RF = None


def main():
    global MKT, RF
    mkt, rf, mktrf = ff_monthly()
    MKT, RF = mkt, rf
    mkt_d, rf_d = ff_daily()
    c10, R10, C10 = ind_monthly('10_Industry_Portfolios')
    c49, R49, C49 = ind_monthly('49_Industry_Portfolios')
    log('French Mkt', min(mkt), max(mkt), '10業種', min(R10['NoDur']), max(R10['NoDur']))
    res = {'angle': 'trend', 'what': '第5族（業種ごとの10か月線×倍率）の反証の検証。研究者のコードを使わず自分で組み直した',
           'data_end': max(mkt), 'benchmark': 'French Mkt（Mkt-RF+RF・上限なしの時価加重・CRSP 全上場）'}

    # ── V1 重みの時点 ──
    v1 = {}
    for nm, cols, R, CAP in (('10', c10, R10, C10), ('49', c49, R49, C49)):
        for wl in (0, 1):
            rec = {}
            for m in mkt:
                wm = mshift(m, -wl)
                inc = [c for c in cols if m in R[c] and wm in CAP[c]]
                if not inc:
                    continue
                W = sum(CAP[c][wm] for c in inc)
                rec[m] = sum(CAP[c][wm] / W * R[c][m] for c in inc)
            ks = keys_of(rec, mkt, a=192707)
            te = S.stdev([rec[k] - mkt[k] for k in ks]) * math.sqrt(12) * 100
            v1[f'ind{nm}_wlag{wl}'] = {'te_vs_french_mkt': round(te, 3), 'mean_diff_ann': round(sum(rec[k] - mkt[k] for k in ks) / len(ks) * 1200, 3)}
    v1['reading'] = ('wlag0 = 表の月 m の Average Firm Size を月 m の重みに、wlag1 = 月 m−1 の値（研究者の既定）。'
                     '追従のぶれが小さいほうが French の値付けの時点に近い。wlag0 のほうが小さければ表の月 m の値は月初（月 m−1 末）＝'
                     '研究者の wlag1 は1か月余分に古い（安全側）。後知恵は無い')
    res['V1_weight_timing'] = v1
    log('V1', v1)

    sig10 = {N: sma_signals(c10, R10, N) for N in (6, 8, 9, 10, 11, 12, 14)}
    sig49 = {N: sma_signals(c49, R49, N) for N in (6, 8, 9, 10, 11, 12, 14)}

    # ── V0 再現（研究者の約束どおり） ──
    CLAIM = {
        'S1_US_IND10_FABER_L2': dict(train_ex=5.12, train_t=2.59, hold_ex=4.76, hold_t=1.72, hold_cagr_diff=4.57, net_cost_hold_ex=4.43, full_ex=5.05, full_t=3.0, roll20_win=0.875, grade='S'),
        'S3_US_IND49_FABER_L2': dict(train_ex=5.18, train_t=2.88, hold_ex=4.8, hold_t=1.89, hold_cagr_diff=4.78, net_cost_hold_ex=4.45, full_ex=5.11, full_t=3.35, roll20_win=0.875, grade='S'),
        'S1_US_IND10_FABER_L3': dict(train_ex=11.67, train_t=3.67, hold_ex=12.42, hold_t=2.77, hold_cagr_diff=10.65, net_cost_hold_ex=11.93, full_ex=11.82, full_t=4.38, roll20_win=0.863, grade='S'),
        'S3_US_IND49_FABER_L3': dict(train_ex=11.72, train_t=3.95, hold_ex=12.46, hold_t=2.94, hold_cagr_diff=11.09, net_cost_hold_ex=11.93, full_ex=11.87, full_t=4.7, roll20_win=0.875, grade='S'),
        'S2_US_IND10_FABERD_L3': dict(train_ex=11.85, train_t=3.73, hold_ex=11.09, hold_t=2.37, hold_cagr_diff=8.87, net_cost_hold_ex=10.59, full_ex=11.7, full_t=4.31, roll20_win=0.863, grade='S'),
        'S2_US_IND10_FABERD_L2': dict(train_ex=5.19, train_t=2.67, hold_ex=3.96, hold_t=1.37, hold_cagr_diff=3.6, net_cost_hold_ex=3.63, full_ex=4.94, full_t=2.97, roll20_win=0.9, grade='B'),
    }
    series = {}
    for L in (1, 2, 3):
        series[f'S1_L{L}'] = bt_monthly(c10, R10, C10, rf, sig10[10], L)
        series[f'S3_L{L}'] = bt_monthly(c49, R49, C49, rf, sig49[10], L)

    # 日次（10業種・49業種）
    D_all = sorted(rf_d)
    c10d, R10d = ind_daily('10_Industry_Portfolios_daily')
    assert c10d == c10
    D10 = [d for d in D_all if all(d in R10d[c] for c in c10d) and d <= 20260831]
    c49d, R49d = ind_daily('49_Industry_Portfolios_daily')
    assert c49d == c49
    D49 = [d for d in D_all if d in R49d['Food'] and d <= 20260831]
    for L in (1, 2, 3):
        mo, miss = bt_daily(D10, c10, R10d, C10, rf_d, L, lag=1, mode='margin')
        gmo, _ = bt_daily(D10, c10, R10d, C10, rf_d, L, lag=1, mode='margin', cost=0.0)
        series[f'S2_L{L}'] = (gmo, mo, None)
    log('daily done')

    def full_eval(g, n, label):
        e = {'full': cmp(g, mkt), 'train': cmp(g, mkt, z=TRAIN_END), 'hold': cmp(g, mkt, a=HOLD),
             'cost_hold': cmp(n, mkt, a=HOLD), 'net_full': cmp(n, mkt), 'roll20_net': roll20(n, mkt), 'roll20_gross': roll20(g, mkt),
             'dca20_net': dca20(n, mkt),
             'sharpe_net': {'train': (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=min(n), z=TRAIN_END)),
                            'hold': (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD))},
             'sharpe_gross': {'train': (sharpe(g, rf, z=TRAIN_END), sharpe(mkt, rf, a=min(g), z=TRAIN_END)),
                              'hold': (sharpe(g, rf, a=HOLD), sharpe(mkt, rf, a=HOLD))}}
        return e

    rep = {}
    mapping = {'S1_US_IND10_FABER_L2': 'S1_L2', 'S3_US_IND49_FABER_L2': 'S3_L2', 'S1_US_IND10_FABER_L3': 'S1_L3',
               'S3_US_IND49_FABER_L3': 'S3_L3', 'S2_US_IND10_FABERD_L3': 'S2_L3', 'S2_US_IND10_FABERD_L2': 'S2_L2'}
    for name, key in mapping.items():
        g, n, _ = series[key]
        e = full_eval(g, n, name)
        cl = CLAIM[name]
        e['reproduced_vs_claim'] = {
            'train_ex': [e['train']['ex_ann'], cl['train_ex']], 'train_t': [round(e['train']['t_raw'], 3), cl['train_t']],
            'hold_ex': [e['hold']['ex_ann'], cl['hold_ex']], 'hold_t': [round(e['hold']['t_raw'], 3), cl['hold_t']],
            'hold_cagr_diff': [e['hold']['cagr_diff'], cl['hold_cagr_diff']], 'net_cost_hold_ex': [e['cost_hold']['ex_ann'], cl['net_cost_hold_ex']],
            'full_ex': [e['full']['ex_ann'], cl['full_ex']], 'full_t_unrounded': [round(e['full']['t_raw'], 4), cl['full_t']],
            'roll20_net_win': [e['roll20_net']['win_rate'], cl['roll20_win']]}
        gr, crit = my_grade(e['full'], e['train'], e['hold'], e['cost_hold'], e['roll20_net'], e['sharpe_net']['train'], e['sharpe_net']['hold'], repl=True)
        e['my_grade_same_rules'] = gr
        e['my_criteria'] = crit
        rep[name] = e
        log('V0', name, json.dumps(strip(e['reproduced_vs_claim']), ensure_ascii=False), gr)
    res['V0_reproduction'] = strip(rep)

    # ── V2 実行の遅れと持ち高の伸び方（10業種） ──
    v2 = {}
    for L in (1, 2, 3):
        row = {}
        g, n, _ = series[f'S1_L{L}']
        row['monthly_same_close'] = {'hold_net': strip(cmp(n, mkt, a=HOLD)), 'sharpe_hold_net': sharpe(n, rf, a=HOLD), 'full_t': cmp(g, mkt)['t']}
        g2, n2, _ = bt_monthly(c10, R10, C10, rf, sig10[10], L, skip=1)
        row['monthly_1month_late'] = {'hold_net': strip(cmp(n2, mkt, a=HOLD)), 'sharpe_hold_net': sharpe(n2, rf, a=HOLD), 'full_t': cmp(g2, mkt)['t'],
                                      'train_t': cmp(g2, mkt, z=TRAIN_END)['t']}
        for lag in (0, 1, 2, 5):
            for mode in ('margin', 'etf'):
                if L == 1 and mode == 'etf':
                    continue
                mo, _ = bt_daily(D10, c10, R10d, C10, rf_d, L, lag=lag, mode=mode, turnover='full')
                gmo, _ = bt_daily(D10, c10, R10d, C10, rf_d, L, lag=lag, mode=mode, cost=0.0)
                h = cmp(mo, mkt, a=HOLD)
                row[f'daily_lag{lag}_{mode}'] = {'hold_net': strip(h), 'sharpe_hold_net': sharpe(mo, rf, a=HOLD),
                                                 'sharpe_train_net': sharpe(mo, rf, z=TRAIN_END), 'mkt_sharpe_train': sharpe(mkt, rf, a=min(mo), z=TRAIN_END),
                                                 'train_t_gross': cmp(gmo, mkt, z=TRAIN_END)['t'], 'full_t_gross': cmp(gmo, mkt)['t'],
                                                 'hold_t_gross': cmp(gmo, mkt, a=HOLD)['t'], 'roll20_net': roll20(mo, mkt)['win_rate']}
        v2[f'L{L}'] = row
        log('V2 L', L, json.dumps({k: (v['hold_net']['cagr_diff'], v['sharpe_hold_net']) for k, v in row.items()}, ensure_ascii=False))
    # 49業種の日次（研究者は回していない）
    v2['IND49_daily'] = {}
    for L in (2, 3):
        for lag in (0, 1):
            for mode in ('margin', 'etf'):
                mo, miss = bt_daily(D49, c49, R49d, C49, rf_d, L, lag=lag, mode=mode, turnover='full')
                gmo, _ = bt_daily(D49, c49, R49d, C49, rf_d, L, lag=lag, mode=mode, cost=0.0)
                e = full_eval(gmo, mo, 'x')
                gr, crit = my_grade(e['full'], e['train'], e['hold'], e['cost_hold'], e['roll20_net'], e['sharpe_net']['train'], e['sharpe_net']['hold'], repl=True)
                v2['IND49_daily'][f'L{L}_lag{lag}_{mode}'] = {'hold_net': strip(e['cost_hold']), 'hold_t_gross': e['hold']['t'],
                                                              'train_t_gross': e['train']['t'], 'full_t_gross': e['full']['t'],
                                                              'sharpe_net': e['sharpe_net'], 'roll20_net': e['roll20_net']['win_rate'],
                                                              'grade_if_graded': gr, 'missing_day_holdings': miss}
                log('V2 49d', L, lag, mode, e['cost_hold']['cagr_diff'], e['hold']['t'], e['sharpe_net'], gr)
    res['V2_execution'] = v2

    # ── V3 同じリスクまで倍率を掛けた市場 ──
    v3 = {}
    for key in ('S1_L1', 'S3_L1', 'S1_L2', 'S3_L2', 'S1_L3', 'S3_L3', 'S2_L2', 'S2_L3'):
        g, n, E = series[key]
        row = {}
        for per, a, z in (('train', None, TRAIN_END), ('hold', HOLD, None), ('since2010', 201001, None), ('full', None, None)):
            ks = keys_of(n, mkt, rf, a=a, z=z)
            xs = {k: n[k] for k in ks}
            k_vol = vol(xs) / vol({k: mkt[k] for k in ks})
            lm = lev_market(mkt, rf, k_vol)
            c = cmp(n, lm, a=a, z=z)
            avgE = None
            if E:
                avgE = sum(E[k] for k in ks if k in E) / len([k for k in ks if k in E])
                lmE = lev_market(mkt, rf, avgE)
                cE = cmp(n, lmE, a=a, z=z)
            else:
                cE = None
            row[per] = {'vol_ratio': round(k_vol, 3), 'vs_vol_matched_market': strip(c),
                        'avg_exposure': round(avgE, 3) if avgE else None, 'vs_same_avg_exposure_market': strip(cE) if cE else None,
                        'capm': capm(n, mkt, rf, a=a, z=z)}
        v3[key] = row
        log('V3', key, {p: (row[p]['vs_vol_matched_market']['cagr_diff'], row[p]['vs_vol_matched_market']['t']) for p in row})
    res['V3_risk_matched'] = v3

    # ── V4 区間の依存 ──
    v4 = {}
    for key in ('S1_L2', 'S3_L2', 'S1_L3', 'S3_L3', 'S2_L2', 'S2_L3', 'S1_L1'):
        g, n, _ = series[key]
        row = {
            'hold_first_half_2007_2016': strip(cmp(n, mkt, a=HOLD, z=201610)),
            'hold_second_half_2016_2026': strip(cmp(n, mkt, a=201611)),
            'hold_drop_2008': strip(cmp(n, mkt, a=HOLD, drop=[(200801, 200812)])),
            'hold_drop_2008_2022': strip(cmp(n, mkt, a=HOLD, drop=[(200801, 200812), (202201, 202212)])),
            'hold_drop_2020_2021': strip(cmp(n, mkt, a=HOLD, drop=[(202001, 202112)])),
            'hold_drop_2007_2009': strip(cmp(n, mkt, a=HOLD, drop=[(200701, 200912)])),
            'since_2010': strip(cmp(n, mkt, a=201001)),
            'full_drop_1998_2000': strip(cmp(g, mkt, drop=[(199801, 200012)])),
            'full_drop_1998_2000_and_2020_2021': strip(cmp(g, mkt, drop=[(199801, 200012), (202001, 202112)])),
            'train_from_1934_gross': strip(cmp(g, mkt, a=193401, z=TRAIN_END)),
            'train_drop_1929_1933_gross': strip(cmp(g, mkt, z=TRAIN_END, drop=[(192909, 193306)])),
            'train_1946_2006_gross': strip(cmp(g, mkt, a=194601, z=TRAIN_END)),
            'sharpe_net_since2010': [sharpe(n, rf, a=201001), sharpe(mkt, rf, a=201001)],
            'sharpe_net_hold_drop_2008': [sharpe(n, rf, a=HOLD, drop=[(200801, 200812)]), sharpe(mkt, rf, a=HOLD, drop=[(200801, 200812)])],
            'sharpe_net_second_half': [sharpe(n, rf, a=201611), sharpe(mkt, rf, a=201611)],
            'sharpe_net_first_half': [sharpe(n, rf, a=HOLD, z=201610), sharpe(mkt, rf, a=HOLD, z=201610)],
        }
        # 年ごとの差（保有期間）
        yrs = {}
        for y in range(2007, 2027):
            ks = keys_of(n, mkt, a=y * 100 + 1, z=y * 100 + 12)
            if len(ks) >= 6:
                ps = math.prod(1 + n[k] for k in ks) - 1
                pb = math.prod(1 + mkt[k] for k in ks) - 1
                yrs[y] = round((ps - pb) * 100, 1)
        row['hold_calendar_year_diff'] = yrs
        tot = sum(yrs.values())
        top2 = sorted(yrs.items(), key=lambda x: -x[1])[:2]
        row['hold_sum_of_year_diffs'] = round(tot, 1)
        row['hold_top2_years'] = top2
        v4[key] = row
        log('V4', key, 'H1', row['hold_first_half_2007_2016']['cagr_diff'], row['hold_first_half_2007_2016']['t'],
            'H2', row['hold_second_half_2016_2026']['cagr_diff'], row['hold_second_half_2016_2026']['t'],
            'no2008', row['hold_drop_2008']['cagr_diff'], row['hold_drop_2008']['t'], 'no08/22', row['hold_drop_2008_2022']['cagr_diff'],
            'since2010', row['since_2010']['cagr_diff'], row['since_2010']['t'], 'sh2010', row['sharpe_net_since2010'], 'top2', top2)
    res['V4_subperiods'] = v4

    # ── V5 近い値の規則 ──
    v5 = {}
    for nm, cols, R, CAP, sg in (('IND10', c10, R10, C10, sig10), ('IND49', c49, R49, C49, sig49)):
        for L in (1, 2, 3):
            for N in (6, 8, 9, 10, 11, 12, 14):
                start = max(192705, mshift(192607, N))
                g, n, _ = bt_monthly(cols, R, CAP, rf, sg[N], L, start=start)
                tr, ho, fu, ch = cmp(g, mkt, z=TRAIN_END), cmp(g, mkt, a=HOLD), cmp(g, mkt), cmp(n, mkt, a=HOLD)
                rl = roll20(n, mkt)
                shn = (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=start, z=TRAIN_END))
                shh = (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD))
                gr, _ = my_grade(fu, tr, ho, ch, rl, shn, shh, repl=True)
                v5[f'{nm}_L{L}_N{N}'] = {'train_ex': tr['ex_ann'], 'train_t': tr['t'], 'hold_ex': ho['ex_ann'], 'hold_t': ho['t'],
                                         'hold_net_cagr_diff': ch['cagr_diff'], 'full_t': fu['t'], 'roll20': rl['win_rate'],
                                         'sharpe_hold_net': shh, 'sharpe_train_net': shn, 'grade_same_rules_assuming_C5_pass': gr}
        log('V5', nm, {k: (v['hold_net_cagr_diff'], v['hold_t'], v['grade_same_rules_assuming_C5_pass']) for k, v in v5.items() if k.startswith(nm)})
    res['V5_neighbors'] = v5

    # ── V6 業種の依存（10業種・L2）：1業種ずつタイミングを外す ──
    v6 = {}
    g0, n0, _ = series['S1_L2']
    base_h = cmp(n0, mkt, a=HOLD)
    base_f = cmp(g0, mkt)
    for c in c10:
        g, n, _ = bt_monthly(c10, R10, C10, rf, sig10[10], 2, force_on={c})
        h = cmp(n, mkt, a=HOLD)
        f = cmp(g, mkt)
        v6[c] = {'hold_net_cagr_diff': h['cagr_diff'], 'hold_t': h['t'], 'full_t': f['t'],
                 'timing_contrib_hold_cagr': round(base_h['cagr_diff'] - h['cagr_diff'], 2)}
    v6['_base'] = {'hold_net_cagr_diff': base_h['cagr_diff'], 'hold_t': base_h['t'], 'full_t': base_f['t']}
    res['V6_industry_leave_timing_out_L2'] = v6
    log('V6', {k: (v['hold_net_cagr_diff'], v.get('timing_contrib_hold_cagr')) for k, v in v6.items()})

    # ── V7 費用と借入 ──
    v7 = {'turnover_per_year_hold': {}}
    for key, cols, R, CAP, sg in (('S1', c10, R10, C10, sig10[10]), ('S3', c49, R49, C49, sig49[10])):
        for L in (2, 3):
            v7['turnover_per_year_hold'][f'{key}_L{L}'] = turnover_stats(cols, R, CAP, rf, sg, L)
            row = {}
            for cst in (0.001, 0.003, 0.005, 0.01):
                g, n, _ = bt_monthly(cols, R, CAP, rf, sg, L, cost=cst, turnover='full')
                row[f'full_turnover_cost{cst}'] = {'hold': strip(cmp(n, mkt, a=HOLD)), 'train': strip(cmp(n, mkt, z=TRAIN_END)),
                                                   'sharpe_train': (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=192705, z=TRAIN_END)),
                                                   'sharpe_hold': (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD)), 'roll20': roll20(n, mkt)['win_rate']}
            for sp in (0.01, 0.02, 0.03):
                g, n, _ = bt_monthly(cols, R, CAP, rf, sg, L, spread=sp, turnover='full')
                row[f'borrow_rf_plus_{int(sp*100)}pct'] = {'hold': strip(cmp(n, mkt, a=HOLD)), 'train_gross_t': cmp(g, mkt, z=TRAIN_END)['t'],
                                                           'train_gross_ex': cmp(g, mkt, z=TRAIN_END)['ex_ann'], 'full_gross_t': cmp(g, mkt)['t'],
                                                           'sharpe_train': (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=192705, z=TRAIN_END)),
                                                           'sharpe_hold': (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD)), 'roll20': roll20(n, mkt)['win_rate']}
            # 歴史に合わせた費用: 1927-1974 片道0.50%・1975-1999 0.25%・2000- 0.10%（Jones 2002 の目安を丸めた）、借入 RF+2%（1927-1981）/RF+1%（1982-）
            cm = {m: (0.005 if m < 197505 else 0.0025 if m < 200001 else 0.001) for m in rf}
            ba = {m: (0.02 if m < 198201 else 0.01) for m in rf}
            g, n, E = bt_monthly(cols, R, CAP, rf, sg, L, turnover='full', borrow_add=ba, cost=0.0)
            # 費用を月ごとの単価で当て直す
            _, nfull1, _ = bt_monthly(cols, R, CAP, rf, sg, L, turnover='full', borrow_add=ba, cost=1.0)
            nh = {m: (1 + g[m]) * (1 - cm[m] * (1 - (1 + nfull1[m]) / (1 + g[m]))) - 1 for m in g}
            row['historical_costs_and_borrow'] = {'train': strip(cmp(nh, mkt, z=TRAIN_END)), 'hold': strip(cmp(nh, mkt, a=HOLD)), 'full': strip(cmp(nh, mkt)),
                                                  'sharpe_train': (sharpe(nh, rf, z=TRAIN_END), sharpe(mkt, rf, a=192705, z=TRAIN_END)),
                                                  'roll20': roll20(nh, mkt)['win_rate'],
                                                  'note': '片道 0.50%（〜1975-04）/0.25%（〜1999）/0.10%（2000〜）、借入 RF+2%（〜1981）/RF+1%（1982〜）。事後の感度（判定しない）'}
            g, n, E = bt_monthly(cols, R, CAP, rf, sg, L, turnover='full', borrow_add=ba, cost=0.0, fee=0.0)
            _, nfull1, _ = bt_monthly(cols, R, CAP, rf, sg, L, turnover='full', borrow_add=ba, cost=1.0, fee=0.0)
            nh = {m: (1 + g[m]) * (1 - cm[m] * (1 - (1 + nfull1[m]) / (1 + g[m]))) - 1 for m in g}
            row['historical_costs_and_borrow_margin_nofee'] = {'train': strip(cmp(nh, mkt, z=TRAIN_END)), 'train_gross_t': cmp(g, mkt, z=TRAIN_END)['t'],
                                                               'hold': strip(cmp(nh, mkt, a=HOLD)), 'full': strip(cmp(nh, mkt)),
                                                               'full_gross_t': cmp(g, mkt)['t'],
                                                               'sharpe_train': (sharpe(nh, rf, z=TRAIN_END), sharpe(mkt, rf, a=192705, z=TRAIN_END)),
                                                               'sharpe_hold': (sharpe(nh, rf, a=HOLD), sharpe(mkt, rf, a=HOLD)),
                                                               'roll20': roll20(nh, mkt)['win_rate'],
                                                               'note': '上と同じ費用・借入で、信用買いに ETF の経費0.9% は掛けない版'}
            v7[f'{key}_L{L}'] = row
            log('V7', key, L, {k: (v['hold']['cagr_diff'] if 'hold' in v else None) for k, v in row.items()},
                'hist train t', row['historical_costs_and_borrow']['train']['t'])
    v7['reg_t_note'] = ('米国の証拠金規制（Reg T・1934〜）の当初証拠金率は 1934〜1974 に 40〜100%（1946-47 は 100%＝信用買い不可、1958 90%、1968 80%）、'
                        '1974 以降 50%。個人が株を2倍で持つ（50%）ことは 1945〜1974 の大半で違法、3倍（33%）は 1934〜2007（ポートフォリオ・マージン導入）まで'
                        '先物以外では不可。業種の先物は無い。訓練期間の L2/L3 の成績は、実行できない仮想の持ち方の成績')
    res['V7_costs_borrow'] = v7

    # ── V8 シャープレシオの差・α ──
    v8 = {}
    for key in ('S1_L1', 'S3_L1', 'S1_L2', 'S3_L2', 'S1_L3', 'S3_L3', 'S2_L2', 'S2_L3'):
        g, n, _ = series[key]
        v8[key] = {'jk_train': sr_test(n, mkt, rf, z=TRAIN_END), 'jk_hold': sr_test(n, mkt, rf, a=HOLD),
                   'boot_hold': sr_boot(n, mkt, rf, a=HOLD), 'boot_full': sr_boot(n, mkt, rf),
                   'capm_hold': capm(n, mkt, rf, a=HOLD), 'capm_full': capm(n, mkt, rf), 'capm_since2010': capm(n, mkt, rf, a=201001)}
        log('V8', key, v8[key])
    res['V8_sharpe_alpha'] = v8

    # ── V9 米国外（相手を国の時価加重の市場に） ──
    v9 = {}
    for ctry in ('jpn', 'gbr', 'deu', 'fra', 'can', 'aus'):
        row = {}
        for L in (1, 2):
            net, bh, mk = jkp_country(ctry, rf, L)
            row[f'L{L}'] = {'vs_equal_weight_industries_full': strip(cmp(net, bh)), 'vs_equal_weight_industries_hold': strip(cmp(net, bh, a=HOLD)),
                            'vs_country_vw_market_full': strip(cmp(net, mk)) if mk else None,
                            'vs_country_vw_market_hold': strip(cmp(net, mk, a=HOLD)) if mk else None,
                            'sharpe_full': [sharpe(net, rf), sharpe(bh, rf, a=min(net)), sharpe(mk, rf, a=min(net)) if mk else None],
                            'sharpe_hold': [sharpe(net, rf, a=HOLD), sharpe(bh, rf, a=HOLD), sharpe(mk, rf, a=HOLD) if mk else None]}
        v9[ctry] = row
        log('V9', ctry, {L: (row[L]['vs_equal_weight_industries_full']['cagr_diff'], (row[L]['vs_country_vw_market_full'] or {}).get('cagr_diff'),
                              (row[L]['vs_country_vw_market_hold'] or {}).get('cagr_diff'), row[L]['sharpe_full'], row[L]['sharpe_hold']) for L in row})
    cnt = {}
    for L in ('L1', 'L2'):
        for tgt in ('vs_equal_weight_industries_full', 'vs_country_vw_market_full', 'vs_country_vw_market_hold'):
            k = 0
            for ctry in v9:
                x = v9[ctry][L][tgt]
                if x and x['ex_ann'] > 0 and x['cagr_diff'] > 0:
                    k += 1
            cnt[f'{L}_{tgt}'] = f'{k}/{len(v9)}'
        cnt[f'{L}_sharpe_up_vs_vw_market_full'] = f"{sum(1 for c in v9 if v9[c][L]['sharpe_full'][2] is not None and v9[c][L]['sharpe_full'][0] > v9[c][L]['sharpe_full'][2])}/{len(v9)}"
        cnt[f'{L}_sharpe_up_vs_vw_market_hold'] = f"{sum(1 for c in v9 if v9[c][L]['sharpe_hold'][2] is not None and v9[c][L]['sharpe_hold'][0] > v9[c][L]['sharpe_hold'][2])}/{len(v9)}"
    v9['_counts'] = cnt
    v9['_note'] = 'JKP の業種は 2000 年前後から（25〜26年）で、保有期間と大半が重なる。2000-02 と 2008 の世界同時の下げが全部の国に入る＝独立の試行ではない'
    res['V9_international'] = v9
    log('V9 counts', cnt)

    # ── V10 税 ──
    v10 = {}
    for key, cols, R, CAP, sg in (('S1', c10, R10, C10, sig10[10]), ('S3', c49, R49, C49, sig49[10])):
        for L in (1, 2, 3):
            v10[f'{key}_L{L}'] = {'hold': tax_monthly(cols, R, CAP, rf, sg, L, HOLD, END), 'since2016': tax_monthly(cols, R, CAP, rf, sg, L, 201601, END),
                                  'full': tax_monthly(cols, R, CAP, rf, sg, L, 192705, END)}
            log('V10', key, L, v10[f'{key}_L{L}'])
    v10['note'] = 'NISA ではレバレッジ型・信用取引は持てない。課税口座で、業種ごとに L 倍 ETF（経費0.95%）を持つ月次近似。配当課税は両方とも無視'
    res['V10_tax_japan'] = v10

    # ── V11 多重検定 ──
    prev = json.load(open(os.path.join(M.BASE, 'out', 'mw_trend.json')))
    graded = [x for x in prev['tested'] if x.get('graded')]
    ps = {x['id']: (x.get('hold') or {}).get('p') for x in graded}
    n_tests = len(graded)
    bonf_t = None
    # 両側 p = 0.05 / n の z
    lo, hi = 0.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if p_two(mid) > 0.05 / n_tests:
            lo = mid
        else:
            hi = mid
    bonf_t = round(hi, 2)
    my_hold_p = {}
    for name, key in mapping.items():
        my_hold_p[name] = p_two(rep[name]['hold']['t_raw'])
    ps2 = dict(ps)
    ps2.update(my_hold_p)
    items = sorted((p, k) for k, p in ps2.items() if p is not None)
    m_ = len(items)
    holm = {}
    run = 0.0
    for i, (p, k) in enumerate(items):
        run = max(run, min(1.0, (m_ - i) * p))
        holm[k] = round(run, 4)
    res['V11_multiple_testing'] = {
        'n_graded_in_angle': n_tests, 'n_tested_in_angle': len(prev['tested']),
        'bonferroni_two_sided_t_for_full_period': bonf_t,
        'holm_hold_p': {k: holm.get(k) for k in mapping},
        'full_t_unrounded': {k: round(rep[k]['full']['t_raw'], 4) for k in mapping},
        'family5_registered_after_seeing_holdout': ('out/mw_trend_prereg5.json の why_this_family が、第1族の P01（市場全体の10か月線・1倍）の'
                                                    '保有期間のシャープレシオ 0.744 vs 0.652 を見て『遅い月次の信号』と『レバレッジ』を選んだと書いている＝'
                                                    '保有期間（2007〜）を見てから族を選んだ。第5族にとって保有期間はもう手つかずの答え合わせではない'),
        'posthoc_market_level_L3_note': ('研究者の事後の H_P01_US_FABER10_L3（市場全体の10か月線・月次・3倍・判定しない）は full t3.56・train t2.95・hold t2.26・'
                                          'シャープ 訓練0.475>0.409・保有0.708>0.652・転がる20年0.80 で、同じ線なら S 相当。業種に分けなくても L3 は通る＝'
                                          'S の源は「業種」より「同じ終値で売買する月次の10か月線＋倍率」')}
    log('V11', res['V11_multiple_testing'])

    res['V12_executable_grades'] = exec_grades(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49)
    res['V13_executable_historical_frictions'] = exec_hist(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49)
    res['V14_execution_lags'] = exec_lags(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49)
    res['verdicts'] = verdicts(res)
    res['log'] = LOG
    json.dump(res, open(OUTP, 'w'), ensure_ascii=False, indent=1, default=str)
    return res


def exec_grades(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49):
    """V12: 実行できる形（月末の信号を翌営業日の終値で売買・月中は放置）で、事前登録の線をそのまま当てた格付けと、
    『超過と β の混ざり』を外した格付け（C3・C7 の t を CAPM α の t に置き換え）。借入は3通り:
    researcher = 研究者の式（RF+0.5%・E>1 で経費0.9%）／ retail = 個人の信用（RF+1.5%・経費なし）／ etf = 業種ごとの日々L倍 ETF（経費0.95%・RF+0.5%）。
    C5 は JKP 6か国で同じ L・費用後・相手はその国の時価加重の市場（全期間）"""
    out = {}
    c5 = {}
    for L in (2, 3):
        k = 0
        for ctry in ('jpn', 'gbr', 'deu', 'fra', 'can', 'aus'):
            net, bh, mk = jkp_country(ctry, rf, L)
            x = cmp(net, mk) if mk else None
            if x and x['ex_ann'] > 0 and x['cagr_diff'] > 0:
                k += 1
        c5[L] = k / 6 >= 2 / 3
        out[f'C5_vw_market_L{L}'] = f'{k}/6'
    for nm, cols, Rd, CAP, D in (('IND10', c10, R10d, C10, D10), ('IND49', c49, R49d, C49, D49)):
        for L in (2, 3):
            for tag, kw in (('researcher', dict(mode='margin', spread=0.005, fee=0.009)),
                            ('retail', dict(mode='margin', spread=0.015, fee=0.0)),
                            ('etf', dict(mode='etf', spread=0.005, etf_fee=0.0095))):
                n, _ = bt_daily(D, cols, Rd, CAP, rf_d, L, lag=1, turnover='full', **kw)
                g, _ = bt_daily(D, cols, Rd, CAP, rf_d, L, lag=1, cost=0.0, **kw)
                full, train, hold, ch = cmp(g, mkt), cmp(g, mkt, z=TRAIN_END), cmp(g, mkt, a=HOLD), cmp(n, mkt, a=HOLD)
                rl = roll20(n, mkt)
                sht = (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=min(n), z=TRAIN_END))
                shh = (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD))
                gr, cr = my_grade(full, train, hold, ch, rl, sht, shh, repl=c5[L])
                af, ah, at = capm(g, mkt, rf), capm(g, mkt, rf, a=HOLD), capm(g, mkt, rf, z=TRAIN_END)
                full_a = dict(full, t_raw=af['t'])
                hold_a = dict(hold, t_raw=ah['t'])
                train_a = dict(train, t_raw=at['t'])
                gra, cra = my_grade(full_a, train_a, hold_a, ch, rl, sht, shh, repl=c5[L])
                out[f'{nm}_L{L}_lag1_{tag}'] = {
                    'train_ex': train['ex_ann'], 'train_t': train['t'], 'hold_ex': hold['ex_ann'], 'hold_t': hold['t'], 'full_t': full['t'],
                    'hold_net': strip(ch), 'roll20_net': rl['win_rate'], 'sharpe_train': sht, 'sharpe_hold': shh,
                    'capm_alpha_t': {'full': af['t'], 'train': at['t'], 'hold': ah['t'], 'hold_alpha': ah['alpha_ann'], 'beta': af['beta']},
                    'grade_prereg_rules': gr, 'criteria': cr, 'grade_alpha_t_for_C1_C3_C7': gra, 'criteria_alpha': cra}
                log('V12', nm, L, tag, 'hold_net', ch['cagr_diff'], 'hold t', hold['t'], 'alpha t h/f', ah['t'], af['t'], 'sh', sht, shh, gr, gra)
    return out


def exec_hist(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49):
    """V13（事後の感度・判定しない）: 実行できる形（翌営業日・信用買い・ETF 経費なし）に、時代に合わせた摩擦を当てる。
    片道の売買費用 0.50%（〜1975-04・固定手数料の時代）/0.25%（〜1999）/0.10%（2000〜）、借入 RF+2%（〜1981）/RF+1%（1982〜）"""
    cf = lambda d: 0.005 if d < 19750501 else 0.0025 if d < 20000101 else 0.001
    sf = lambda d: 0.02 if d < 19820101 else 0.01
    out = {}
    for nm, cols, Rd, CAP, D in (('IND10', c10, R10d, C10, D10), ('IND49', c49, R49d, C49, D49)):
        for L in (2, 3):
            n, _ = bt_daily(D, cols, Rd, CAP, rf_d, L, lag=1, mode='margin', spread=sf, fee=0.0, cost=cf, turnover='full')
            g, _ = bt_daily(D, cols, Rd, CAP, rf_d, L, lag=1, mode='margin', spread=sf, fee=0.0, cost=0.0)
            full, train, hold, ch = cmp(g, mkt), cmp(g, mkt, z=TRAIN_END), cmp(g, mkt, a=HOLD), cmp(n, mkt, a=HOLD)
            # C1 を費用後でも見る（この感度の要点）
            train_net = cmp(n, mkt, z=TRAIN_END)
            rl = roll20(n, mkt)
            sht = (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=min(n), z=TRAIN_END))
            shh = (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD))
            gr, cr = my_grade(full, train, hold, ch, rl, sht, shh, repl=True)
            grn, crn = my_grade(cmp(n, mkt), train_net, cmp(n, mkt, a=HOLD), ch, rl, sht, shh, repl=True)
            out[f'{nm}_L{L}'] = {'train_gross': strip(train), 'train_net': strip(train_net), 'hold_net': strip(ch), 'full_net': strip(cmp(n, mkt)),
                                 'roll20_net': rl, 'sharpe_train': sht, 'sharpe_hold': shh,
                                 'grade_prereg_rules_gross_t': gr, 'failed': [k for k, v in cr.items() if v is False],
                                 'grade_if_C1_C3_C7_on_net': grn, 'failed_net': [k for k, v in crn.items() if v is False]}
            log('V13', nm, L, 'train net', train_net['ex_ann'], train_net['t'], 'hold', ch['cagr_diff'], 'roll', rl['win_rate'], sht, shh, gr, grn)
    return out


def exec_lags(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49):
    """V14: 実行の遅れを 2・5 営業日に延ばしたとき、保有期間のシャープレシオ（C8）と費用後の差がどれだけ残るか。
    あわせて保有期間の後半（2016-11〜）と 2010〜 のシャープレシオ（市場 vs 戦略）"""
    out = {}
    for nm, cols, Rd, CAP, D in (('IND10', c10, R10d, C10, D10), ('IND49', c49, R49d, C49, D49)):
        for L in (2, 3):
            for lag in (1, 2, 5):
                for tag, kw in (('researcher', dict(mode='margin', spread=0.005, fee=0.009)), ('etf', dict(mode='etf', spread=0.005, etf_fee=0.0095))):
                    n, _ = bt_daily(D, cols, Rd, CAP, rf_d, L, lag=lag, turnover='full', **kw)
                    ch = cmp(n, mkt, a=HOLD)
                    out[f'{nm}_L{L}_lag{lag}_{tag}'] = {
                        'hold_net_cagr_diff': ch['cagr_diff'], 'hold_net_t': ch['t'],
                        'sharpe_hold': (sharpe(n, rf, a=HOLD), sharpe(mkt, rf, a=HOLD)),
                        'sharpe_train': (sharpe(n, rf, z=TRAIN_END), sharpe(mkt, rf, a=min(n), z=TRAIN_END)),
                        'sharpe_hold_2nd_half': (sharpe(n, rf, a=201611), sharpe(mkt, rf, a=201611)),
                        'sharpe_since2010': (sharpe(n, rf, a=201001), sharpe(mkt, rf, a=201001)),
                        'sr_boot_hold': sr_boot(n, mkt, rf, a=HOLD, reps=1000)}
                    log('V14', nm, L, lag, tag, ch['cagr_diff'], out[f'{nm}_L{L}_lag{lag}_{tag}']['sharpe_hold'], out[f'{nm}_L{L}_lag{lag}_{tag}']['sharpe_hold_2nd_half'])
    return out


def verdicts(res):
    """格付けの判定（反証の検証）。数字は上の各節から引く。線は out/mw_prereg.json のまま。
    方針: (1) 研究者の数字を自前で再現できたか (2) 実行できる形（翌営業日の終値）での格付け (3) 倍率の β を外した保有期間の有意性
    （同じリスクまで倍率を掛けた市場との差・シャープレシオの差のブートストラップ）(4) 近い値の規則・時代に合わせた摩擦・遅れ で崩れるか。
    迷ったら低いほうへ（懐疑の既定）"""
    V0, V2, V3, V4, V5, V8 = res['V0_reproduction'], res['V2_execution'], res['V3_risk_matched'], res['V4_subperiods'], res['V5_neighbors'], res['V8_sharpe_alpha']
    V11, V12, V13, V14 = res['V11_multiple_testing'], res['V12_executable_grades'], res['V13_executable_historical_frictions'], res['V14_execution_lags']
    ft = V11['full_t_unrounded']
    for kk in V4:  # 年のキーは実行中は int、JSON では str → str にそろえる
        V4[kk]['hold_calendar_year_diff'] = {str(y): v for y, v in V4[kk]['hold_calendar_year_diff'].items()}

    def rv(name):
        r = V0[name]['reproduced_vs_claim']
        return (f"再現（自前/主張）: 訓練 {r['train_ex'][0]}/{r['train_ex'][1]}%・t {r['train_t'][0]}/{r['train_t'][1]}、保有 {r['hold_ex'][0]}/{r['hold_ex'][1]}%・"
                f"t {r['hold_t'][0]}/{r['hold_t'][1]}、保有の CAGR 差 {r['hold_cagr_diff'][0]}/{r['hold_cagr_diff'][1]}、費用後の保有 {r['net_cost_hold_ex'][0]}/{r['net_cost_hold_ex'][1]}、"
                f"全期間 {r['full_ex'][0]}/{r['full_ex'][1]}%・t（丸めない）{r['full_t_unrounded'][0]}、転がる20年 {r['roll20_net_win'][0]}/{r['roll20_net_win'][1]}")

    def rm(key):
        h, s10 = V3[key]['hold']['vs_vol_matched_market'], V3[key]['since2010']['vs_vol_matched_market']
        return (f"同じ値動き（{V3[key]['hold']['vol_ratio']}倍）まで倍率を掛けた市場と比べると保有期間 {h['cagr_diff']:+}%/年・t {h['t']}、2010年〜 {s10['cagr_diff']:+}%/年")

    def sb(key):
        return f"保有期間のシャープレシオの差 {V8[key]['boot_hold']['diff_ann']}（ブートストラップ片側 p {V8[key]['boot_hold']['p_one_sided']}・JK p {V8[key]['jk_hold']['p_two']}）"
    out = []
    # 1
    k = 'S1_US_IND10_FABER_L2'
    e = V12['IND10_L2_lag1_researcher']
    out.append({'name': k, 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'B', 'verdict': 'downgraded to B',
                'key_numbers': rv(k) + f"。実行できる翌日版: 保有 t {e['hold_t']}・全期間 t {e['full_t']} → {e['grade_prereg_rules']}",
                'issues': [f"C7 は全期間 t={ft[k]} で 3.0 を 0.004 だけ上回って通っている（角度の104本の Bonferroni 相当は t {V11['bonferroni_two_sided_t_for_full_period']}・Holm p {V11['holm_hold_p'][k]}）",
                           f"月末の信号と同じ終値で売買する形で、実行できない。翌営業日の終値で売買する実行版は研究者の S2_L2 と同じく B（自前: 保有 t {e['hold_t']}・全期間 t {e['full_t']}。個人の信用 RF+1.5% でも ETF でも B）",
                           f"近い値の規則で崩れる: N=6 {V5['IND10_L2_N6']['grade_same_rules_assuming_C5_pass']}・8 {V5['IND10_L2_N8']['grade_same_rules_assuming_C5_pass']}・9 {V5['IND10_L2_N9']['grade_same_rules_assuming_C5_pass']}・11 {V5['IND10_L2_N11']['grade_same_rules_assuming_C5_pass']}・12 {V5['IND10_L2_N12']['grade_same_rules_assuming_C5_pass']}・14 {V5['IND10_L2_N14']['grade_same_rules_assuming_C5_pass']}（S は 10 と 11 だけ）",
                           rm('S1_L2') + '。' + sb('S1_L2') + f"。保有期間の後半（2016-11〜）のシャープレシオ {V4['S1_L2']['sharpe_net_second_half'][0]} vs 市場 {V4['S1_L2']['sharpe_net_second_half'][1]}",
                           f"保有期間の勝ちは暴落の年より倍率の効いた上げ相場の年から: 2013 {V4['S1_L2']['hold_calendar_year_diff']['2013']:+}pt・2021 {V4['S1_L2']['hold_calendar_year_diff']['2021']:+}・2017 {V4['S1_L2']['hold_calendar_year_diff']['2017']:+}・2008 {V4['S1_L2']['hold_calendar_year_diff']['2008']:+}",
                           f"時代に合わせた摩擦（片道0.50%〜1975・借入 RF+2%〜1981）では実行版の訓練の費用後 t {V13['IND10_L2']['train_net']['t']}（C1 を費用後で見ると C）",
                           '第5族は第1〜4族の保有期間の結果（P01 1倍のシャープ 0.744 vs 0.652）を見てから選ばれた＝保有期間は手つかずの答え合わせではない']})
    # 2
    k = 'S3_US_IND49_FABER_L2'
    e = V12['IND49_L2_lag1_researcher']
    out.append({'name': k, 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'A', 'verdict': 'downgraded to A',
                'key_numbers': rv(k) + f"。実行できる翌日版（研究者は回していない）: 保有 t {e['hold_t']}・全期間 t {e['full_t']}・費用後の保有 CAGR 差 {e['hold_net']['cagr_diff']} → {e['grade_prereg_rules']}",
                'issues': [f"49業種の翌日版は保有期間 t {e['hold_t']} < 1.65 で C3 落ち → A（ETF 版も {V12['IND49_L2_lag1_etf']['grade_prereg_rules']}・保有 t {V12['IND49_L2_lag1_etf']['hold_t']}。ETF の経費を掛けない個人の信用だけ S）",
                           f"全期間 t {ft[k]} は104本の Bonferroni 相当 {V11['bonferroni_two_sided_t_for_full_period']} に届かない・Holm p {V11['holm_hold_p'][k]}",
                           rm('S3_L2') + '。' + sb('S3_L2') + f"。2010年〜のシャープ {V4['S3_L2']['sharpe_net_since2010'][0]} vs {V4['S3_L2']['sharpe_net_since2010'][1]}、後半 {V4['S3_L2']['sharpe_net_second_half'][0]} vs {V4['S3_L2']['sharpe_net_second_half'][1]}",
                           f"近い値の規則は比較的頑丈（N=9〜12 は S、6/8/14 は A）。1日を5日の遅れにすると ETF 版の保有シャープ {V14['IND49_L2_lag5_etf']['sharpe_hold'][0]} vs 0.652 まで縮む",
                           f"時代に合わせた摩擦の実行版は費用前の t なら {V13['IND49_L2']['grade_prereg_rules_gross_t']}、費用後の t なら {V13['IND49_L2']['grade_if_C1_C3_C7_on_net']}",
                           'C5 の米国外は11の GICS 業種の等分（49業種の時価加重ではない）で 2000〜2025 のみ＝保有期間と重なり、2000-02 と 2008 の世界同時の下げが全部の国に入る。相手を国の時価加重の市場にしても L2 は 6/6 で正（保有期間は 5/6）',
                           '49業種×2倍は 49 の業種かごを信用で持つ必要があり、業種の2倍 ETF では組めない。第5族は保有期間を見てから選ばれた']})
    # 3
    k = 'S1_US_IND10_FABER_L3'
    e = V12['IND10_L3_lag1_researcher']
    out.append({'name': k, 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'B', 'verdict': 'downgraded to B',
                'key_numbers': rv(k) + f"。実行できる翌日版: 保有シャープ {e['sharpe_hold'][0]} vs {e['sharpe_hold'][1]}（ETF {V12['IND10_L3_lag1_etf']['sharpe_hold'][0]}・ETF 5日遅れ {V14['IND10_L3_lag5_etf']['sharpe_hold'][0]}）",
                'issues': ['同じ終値で売買する形は実行できない。実行版（S2_L3）は事前登録の線では S だが、以下のとおり C8（シャープ）と C4 が実装の細部で揺れる',
                           f"β {V8['S1_L3']['capm_full']['beta']} の倍率なので、1倍の市場に対する超過の t は株式の上乗せを含む。CAPM α の保有期間 t は同じ終値版 {V8['S1_L3']['capm_hold']['t']}、実行版 {V12['IND10_L3_lag1_researcher']['capm_alpha_t']['hold']}・個人の信用 {V12['IND10_L3_lag1_retail']['capm_alpha_t']['hold']}・ETF {V12['IND10_L3_lag1_etf']['capm_alpha_t']['hold']}",
                           rm('S1_L3') + '。' + sb('S1_L3'),
                           f"実行版の保有期間のシャープの差 {V14['IND10_L3_lag1_researcher']['sr_boot_hold']['diff_ann']}（p {V14['IND10_L3_lag1_researcher']['sr_boot_hold']['p_one_sided']}）、ETF で5日遅れなら {V14['IND10_L3_lag5_etf']['sharpe_hold'][0]} < 0.652 で C8 落ち（→ C）",
                           f"時代に合わせた摩擦の実行版は転がる20年 {V13['IND10_L3']['roll20_net']['win_rate']} < 0.8 で C4 落ち → {V13['IND10_L3']['grade_prereg_rules_gross_t']}",
                           f"保有期間の後半・2010年〜のシャープは市場を下回る（{V4['S1_L3']['sharpe_net_second_half'][0]} vs {V4['S1_L3']['sharpe_net_second_half'][1]}／{V4['S1_L3']['sharpe_net_since2010'][0]} vs {V4['S1_L3']['sharpe_net_since2010'][1]}）",
                           '研究者自身の事後の H_P01_US_FABER10_L3（市場全体の10か月線・月次・3倍）も同じ線で S 相当＝勝ちの源は「業種」ではなく「月次の10か月線＋同じ終値＋倍率」',
                           '最大下落 −91.8%（1929-33）・保有期間 −42.8%。米国の証拠金規制で個人の3倍の信用買いは 1934〜2007 に不可、業種の先物は無い＝訓練期間は実行できない仮想の成績。日本の信用取引では追証で途中で切られうる']})
    # 4
    k = 'S3_US_IND49_FABER_L3'
    e = V12['IND49_L3_lag1_researcher']
    out.append({'name': k, 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'A', 'verdict': 'downgraded to A',
                'key_numbers': rv(k) + f"。実行できる翌日版（研究者は回していない）: 保有 t {e['hold_t']}・全期間 t {e['full_t']}・費用後の保有 CAGR 差 {e['hold_net']['cagr_diff']}・保有シャープ {e['sharpe_hold'][0]} vs {e['sharpe_hold'][1]} → {e['grade_prereg_rules']}",
                'issues': [f"いちばん頑丈な候補: 実行版は3つの持ち方（研究者の式・個人の信用・ETF）すべてで事前登録の線なら S、時代に合わせた摩擦でも {V13['IND49_L3']['grade_prereg_rules_gross_t']}、近い値 N=6〜14 もすべて S。数字の誤りは見つからない",
                           'ただし S の要の C3（保有期間の有意性）は倍率込みの超過で通っている: ' + rm('S3_L3') + '。' + sb('S3_L3') + f"。実行版のシャープの差 {V14['IND49_L3_lag1_researcher']['sr_boot_hold']['diff_ann']}（p {V14['IND49_L3_lag1_researcher']['sr_boot_hold']['p_one_sided']}）",
                           f"保有期間の後半（2016-11〜）のシャープはどの持ち方でも市場未満（{V14['IND49_L3_lag1_researcher']['sharpe_hold_2nd_half'][0]} vs {V14['IND49_L3_lag1_researcher']['sharpe_hold_2nd_half'][1]}）、2010年〜も {V14['IND49_L3_lag1_researcher']['sharpe_since2010'][0]} vs {V14['IND49_L3_lag1_researcher']['sharpe_since2010'][1]}＝保有期間のリスクあたりの勝ちは 2007-09 に集中",
                           f"ETF で5日遅れなら保有シャープ {V14['IND49_L3_lag5_etf']['sharpe_hold'][0]} < 0.652 で C8 落ち",
                           f"Holm p {V11['holm_hold_p'][k]}・CAPM α の全期間 t {V8['S3_L3']['capm_full']['t']}（Bonferroni 相当 {V11['bonferroni_two_sided_t_for_full_period']} ぎりぎり）。第5族は保有期間を見てから選ばれた",
                           '最大下落 −91.3%。49業種×3倍は ETF では組めず、1934〜2007 の個人には法的にも不可＝訓練期間は仮想']})
    # 5
    k = 'S2_US_IND10_FABERD_L3'
    out.append({'name': k, 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'B', 'verdict': 'downgraded to B',
                'key_numbers': rv(k) + '（日次は組み方の細部が違うので僅かにずれる・格付けは同じ S）',
                'issues': [sb('S2_L3') + '＝保有期間のリスクあたりの上乗せはほぼ0。' + rm('S2_L3'),
                           f"CAPM α の保有期間 t {V8['S2_L3']['capm_hold']['t']}（費用後）・ETF {V12['IND10_L3_lag1_etf']['capm_alpha_t']['hold']}＝β を外すと C3 落ち",
                           f"ETF（日々3倍に戻す実在の型）で保有シャープ {V14['IND10_L3_lag1_etf']['sharpe_hold'][0]}、5日遅れで {V14['IND10_L3_lag5_etf']['sharpe_hold'][0]} < 0.652 → C8 落ち（C）。C8 は実装の細部で表裏が変わる",
                           f"時代に合わせた摩擦では転がる20年 {V13['IND10_L3']['roll20_net']['win_rate']} で C4 落ち → B",
                           f"保有期間の後半のシャープ {V4['S2_L3']['sharpe_net_second_half'][0]} vs {V4['S2_L3']['sharpe_net_second_half'][1]}・2010年〜 {V4['S2_L3']['sharpe_net_since2010'][0]} vs {V4['S2_L3']['sharpe_net_since2010'][1]}",
                           '日次の最大下落 −94%。1934〜2007 の個人の3倍は不可。第5族は保有期間を見てから選ばれた']})
    # 6
    k = 'S2_US_IND10_FABERD_L2'
    out.append({'name': k, 'claimed_grade': 'B', 'reproduced': True, 'verified_grade': 'B', 'verdict': 'confirmed',
                'key_numbers': rv(k),
                'issues': ['事前登録の線では B のまま（C3 保有 t・C7 全期間 t が足りない）。ETF・個人の信用・2〜5日遅れでも費用後の保有 CAGR 差は +2.7〜+3.4%/年で正',
                           sb('S2_L2') + '。' + rm('S2_L2'),
                           f"ETF 5日遅れの保有シャープ {V14['IND10_L2_lag5_etf']['sharpe_hold'][0]} vs 0.652＝C8 は紙一重",
                           f"時代に合わせた摩擦では訓練の費用後 t {V13['IND10_L2']['train_net']['t']}（C1 を費用後で見ると C）",
                           'NISA では持てない。課税口座の近似（月次・ETF）で保有期間の税引後の差 ' + str(res['V10_tax_japan']['S1_L2']['hold']['diff_after_tax']) + '%/年（同じ終値版）']})
    return out


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('--v12', '--v13', '--v14'):
        mkt, rf, _ = ff_monthly()
        MKT, RF = mkt, rf
        _, rf_d = ff_daily()
        c10, R10, C10 = ind_monthly('10_Industry_Portfolios')
        c49, R49, C49 = ind_monthly('49_Industry_Portfolios')
        _, R10d = ind_daily('10_Industry_Portfolios_daily')
        _, R49d = ind_daily('49_Industry_Portfolios_daily')
        D_all = sorted(rf_d)
        D10 = [d for d in D_all if all(d in R10d[c] for c in c10) and d <= 20260831]
        D49 = [d for d in D_all if d in R49d['Food'] and d <= 20260831]
        res = json.load(open(OUTP))
        if sys.argv[1:2] == ['--v12']:
            res['V12_executable_grades'] = exec_grades(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49)
        if sys.argv[1:2] != ['--v14']:
            res['V13_executable_historical_frictions'] = exec_hist(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49)
        res['V14_execution_lags'] = exec_lags(mkt, rf, rf_d, c10, R10d, C10, D10, c49, R49d, C49, D49)
        json.dump(res, open(OUTP, 'w'), ensure_ascii=False, indent=1, default=str)
    else:
        main()
