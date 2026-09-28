#!/usr/bin/env python3
"""night/mw_jp_aftertax_verify.py — 角度 jp_aftertax の『反証の検証』（読むだけ・門の判定には不使用）

研究側（night/mw_jp_aftertax.py）が S と言った8本（E1・E2・E1m・X2 の R0 税前 / R1 枠なし非課税）と、
B のうち保有期間の超過が最も大きい2本（E4 Fidelity 上位3 の R0・R1）を、自前の組み立てで作り直して崩しに行く。

独立性:
- mw_common からは取得の関数（ff_factors・jkp_rows・get・french_tables・yahoo・CACHE）だけを使う。
- 戦略の組み立て（cop_at の三分位 LS・門の16本の合成・Fidelity の順位と帯・費用）と、
  超過・NW t・CAGR・転がる20年窓・積立・格付けは全部ここで書き直した（研究側・mw_common の統計関数は呼ばない）。
- Fidelity の生きている33本は Yahoo の『日次』から月末のリターンを作り直す（研究側は Yahoo の月次の足）。
  死んだ6本は研究側と同じ Alpha Vantage の月次 CSV（ほかに無い）。

主な点検:
 (1) 相手: 事前登録の全体の線（out/mw_prereg.json）は『純粋な時価加重の French Mkt』。研究側の一括の格付けは
     相手の指数ファンドにだけ年 0.10% の費用を置き、戦略（個別株の直接保有＝費用0）には置かない。純粋な相手でも測る。
 (2) 後知恵: cop_at は 2016 年公表（Ball ほか・標本〜2013）で、mega_tilt の17特徴の中で保有期間が最良だったものを
     この角度が E1 に選んでいる。公表後（2017〜）と、17特徴の中の順位を出す。
 (3) Fidelity Select の実在の費用: 2003-09-22 まで 3% の申込手数料（1990-10 以前は 2%＋解約時 1%）・30日未満の
     売り 0.75%（SEC Form 497・Fidelity Select Portfolios 2003）。研究側は入れていない。
 (4) 入れ替えの日（月末以外の営業日）・近い母数（K と帯）・1本抜き・上位3年抜き・前半後半・1998-2000/2020-21 抜き。
 (5) 多重検定: この角度の tested 数・元の角度の選び方・プログラム全体の数で Bonferroni。
"""
import sys, os, io, json, math, csv, zipfile, datetime, bisect, statistics as S, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  取得の関数だけ使う

import numpy as np  # noqa: E402

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_jp_aftertax_verify.json')
TRAIN_END, HOLD_START, RECENT_START = 200612, 200701, 201307
JKP_START, JKP_END, FR_END = 196307, 202512, 202608
HALF_SPLIT = 201607            # 保有期間の前半 2007-01〜2016-06 ／ 後半 2016-07〜
POSTPUB_COP = 201701           # Ball, Gerakos, Linnainmaa, Nikolaev (JFE 2016) の公表の翌年
BENCH_FEE = 0.0010
WH = 0.10
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def mrange(a, z):
    out, m = [], a
    while m <= z:
        out.append(m)
        m = madd(m, 1)
    return out


# ───────────────────────── 自前の統計 ─────────────────────────
def nw_t(x, L=12):
    n = len(x)
    if n < 24:
        return None
    mu = math.fsum(x) / n
    e = [v - mu for v in x]
    s = math.fsum(v * v for v in e) / n
    for l in range(1, min(L, n - 1) + 1):
        g = math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
        s += 2 * (1 - l / (L + 1)) * g
    return mu / math.sqrt(s / n) if s > 0 else None


def pval(t):
    return None if t is None else math.erfc(abs(t) / math.sqrt(2))


def geo(xs):
    xs = list(xs)
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def ex(s, b, a=None, z=None, drop=None):
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not (drop and k in drop))
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nw_t(d)
    gs, gb = geo(s[k] for k in ks), geo(b[k] for k in ks)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(math.fsum(d) / len(d) * 1200, 2),
            't': round(t, 2) if t is not None else None, 'p': round(pval(t), 5) if t is not None else None,
            'cagr_diff': round((gs - gb) * 100, 2)}


def roll20(s, b, years=20):
    """7月起点・一括20年の幾何の年率差（全月そろう窓だけ）"""
    ks = set(s) & set(b)
    if not ks:
        return None
    y0, last = min(ks) // 100, max(ks)
    out = []
    for y in range(y0, 2100):
        a, z = y * 100 + 7, (y + years) * 100 + 6
        if z > last:
            break
        w = mrange(a, z)
        if not all(k in ks for k in w):
            continue
        out.append((y, round((geo(s[k] for k in w) - geo(b[k] for k in w)) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'n': len(out), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def dca20(s, b, years=20, load=None):
    """1月起点・毎月1ずつ（名目）240か月積み立てた最終額の比。load(m) = その月の積立に掛かる申込手数料（戦略側だけ）"""
    ks = set(s) & set(b)
    y0, last = min(ks) // 100, max(ks)
    out = []
    for y in range(y0, 2100):
        a, z = y * 100 + 1, (y + years - 1) * 100 + 12
        if z > last:
            break
        w = mrange(a, z)
        if not all(k in ks for k in w):
            continue
        ws = wb = 0.0
        for k in w:
            c = 1.0 - (load(k) if load else 0.0)
            ws = (ws + c) * (1 + s[k]); wb = (wb + 1.0) * (1 + b[k])
        out.append((a, round(ws / wb, 4)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'n': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1])}


def holm(ps):
    it = sorted((p, k) for k, p in ps.items() if p is not None)
    m, run, out = len(it), 0.0, {}
    for i, (p, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = round(run, 4)
    return out


def grade(full, train, hold, net_hold, r20, holm_p=None):
    """out/mw_prereg.json の C1〜C7（C5 は地域の税データが無いので N/A・C8 は該当なし）。欠けは不合格側"""
    c = {'C1_train': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0),
         'C2_hold_sign': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3_hold_t': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4_roll20': bool(r20 and r20['win_rate'] >= 0.8),
         'C5_repl': None,
         'C6_net_cost': bool(net_hold and net_hold['ex'] > 0 and net_hold['cagr_diff'] > 0),
         'C7_multi': bool((full and (full['t'] or 0) >= 3.0) or (holm_p is not None and holm_p < 0.05))}
    ok = lambda k: c[k] is True
    base = ok('C1_train') and ok('C2_hold_sign') and ok('C6_net_cost')
    if base and ok('C3_hold_t') and ok('C4_roll20') and ok('C7_multi'):
        g = 'S'
    elif base and ok('C4_roll20') and ok('C7_multi') and ok('C3_hold_t'):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


def pack(s, b, first, last, gross=None, holm_p=None):
    """s: 費用後（net）の総リターン, b: 相手。gross を渡せば C2/C3 は gross、C6 は net（mw_common の使い方）。
    渡さなければ全部 net（研究側の一括の格付けと同じ扱い）"""
    g_ = gross if gross is not None else s
    full = ex(g_, b, first, last)
    train = ex(g_, b, first, TRAIN_END)
    hold = ex(g_, b, max(first, HOLD_START), last)
    nh = ex(s, b, max(first, HOLD_START), last)
    rec = ex(s, b, max(first, RECENT_START), last)
    r20 = roll20({k: v for k, v in s.items() if first <= k <= last}, b)
    gr, c = grade(full, train, hold, nh, r20, holm_p)
    return {'grade': gr, 'criteria': c, 'full': full, 'train': train, 'hold': hold, 'net_hold': nh, 'recent': rec, 'roll20': r20}


def brief(p):
    f, tr, h, nh = p['full'], p['train'], p['hold'], p['net_hold']
    return (f"{p['grade']} full {f and f['ex']} t{f and f['t']} | train {tr and tr['ex']} t{tr and tr['t']} | "
            f"hold {h and h['ex']} t{h and h['t']} cd {h and h['cagr_diff']} | net {nh and nh['ex']} | r20 {(p['roll20'] or {}).get('win_rate')}")


def ols_hedge(y, X_rows, train_keys, hold_keys):
    """訓練期間の係数（定数つき OLS）で保有期間の y をヘッジした残差の平均と NW t"""
    Xt = np.array([[1.0] + X_rows[k] for k in train_keys])
    yt = np.array([y[k] for k in train_keys])
    beta, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
    res = [y[k] - float(np.dot(beta[1:], X_rows[k])) for k in hold_keys]
    t = nw_t(res)
    return {'alpha_hold': round(S.mean(res) * 1200, 2), 't': round(t, 2) if t is not None else None,
            'raw_hold': round(S.mean(y[k] for k in hold_keys) * 1200, 2), 'train_intercept': round(float(beta[0]) * 1200, 2)}


# ───────────────────────── データ ─────────────────────────
def load_french():
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if k <= FR_END}
    rf = {k: v for k, v in ff['rf'].items() if k <= FR_END}
    return mkt, rf


def div_return():
    """French 12業種（配当込み − 配当抜き）を 社数×平均規模 で加重 → 市場の月次の配当リターン（自前）"""
    wi = M.french_tables('12_Industry_Portfolios')
    wo = M.french_tables('12_Industry_Portfolios_Wout_Div')

    def pick(T, want):
        for k, v in T.items():
            if want.lower() in k.lower() and v['freq'] == 'monthly':
                return v
        raise KeyError(want)
    a, b = pick(wi, 'Average Value Weighted Returns'), pick(wo, 'Average Value Weighted Returns')
    nf, sz = pick(wi, 'Number of Firms'), pick(wi, 'Average Firm Size')
    out = {}
    for m, row in a['data'].items():
        if m > FR_END or m not in b['data'] or m not in nf['data'] or m not in sz['data']:
            continue
        num = den = 0.0
        bad = False
        for i in range(len(row)):
            x, y, n, s = row[i], b['data'][m][i], nf['data'][m][i], sz['data'][m][i]
            if None in (x, y, n, s):
                bad = True
                break
            num += n * s * (x - y) / 100; den += n * s
        if not bad and den > 0:
            out[m] = num / den
    return out


def industries12():
    for k, v in M.french_tables('12_Industry_Portfolios').items():
        if 'average value weighted returns' in k.lower() and v['freq'] == 'monthly':
            return v['cols'], {m: [x / 100 for x in row] for m, row in v['data'].items() if None not in row}
    raise KeyError('12 ind')


def jkp_port_vw():
    """JKP 米国 all_factors 三分位（vw）→ {特徴: {pf: {ym: (超過, n)}}}"""
    d = {}
    for x in M.jkp_rows('usa', 'all_factors', 'portfolios', 'vw'):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        n = x.get('n')
        n = int(float(n)) if n not in (None, '', 'NA', 'na') else None
        d.setdefault(x['name'], {}).setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = (float(x['ret']), n)
    return d


def jkp_dirs(weighting='vw'):
    return {x['name']: int(float(x['direction'])) for x in M.jkp_rows('usa', 'all_factors', 'factor', weighting)
            if x['direction'] not in ('', 'NA', 'na')}


def jkp_factor_ret(name, weighting='vw'):
    return {int(x['date'][:4]) * 100 + int(x['date'][5:7]): float(x['ret']) for x in M.jkp_rows('usa', 'all_factors', 'factor', weighting)
            if x['name'] == name and x['ret'] not in ('', 'NA', 'na')}


def tercile_ls(P, name, dirn, nmin=10):
    """自前: 向き × (第3 − 第1)（どちらも n ≥ nmin の月）"""
    p1, p3 = P[name].get('1.0', {}), P[name].get('3.0', {})
    return {k: dirn * (p3[k][0] - p1[k][0]) for k in p3 if k in p1 and (p3[k][1] or 0) >= nmin and (p1[k][1] or 0) >= nmin}


def good_side(P, name, dirn, nmin=10):
    p = P[name].get('3.0' if dirn > 0 else '1.0', {})
    return {k: r for k, (r, n) in p.items() if n is not None and n >= nmin}


def mega_ls(name, dirn):
    u = f'https://jkpfactors-data.s3.amazonaws.com/public/factor/%5Busa%5D_%5B{name}%5D_%5Bmega%5D.zip'
    b = M.get(u, name=f'jkp_size_usa_{name}_mega.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na') or int(float(x['n'])) < 50:
            continue
        out[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret']) * dirn
    return out


# ── Fidelity Select（研究側の一覧＝etf_tactical の FSEL 33本＋死んだ6本。一覧は定義なので写す）
FSEL = ['FSPTX', 'FSENX', 'FIDSX', 'FSUTX', 'FSPHX', 'FSDAX', 'FDLSX', 'FSLBX', 'FSCHX', 'FDFAX', 'FSELX', 'FSTCX', 'FSCSX', 'FDCPX',
        'FSAGX', 'FBIOX', 'FSVLX', 'FSPCX', 'FSRPX', 'FSAVX', 'FSHCX', 'FBMPX', 'FSRBX', 'FSHOX', 'FSDPX', 'FSRFX', 'FSLEX', 'FSCPX',
        'FNARX', 'FBSOX', 'FSMEX', 'FWRLX', 'FPHAX']
DEAD = ['FSESX', 'FSNGX', 'FSAIX', 'FSDCX', 'FCYIX', 'FSCGX']


def ymd_of(ts):
    d = datetime.datetime.utcfromtimestamp(ts).date()
    return d.year * 10000 + d.month * 100 + d.day


def todate(k):
    return datetime.date(k // 10000, k // 100 % 100, k % 100)


def daily_levels(t):
    M.yahoo(t, interval='1d')      # 取得（キャッシュ）だけ mw_common。読み取りは自前
    r = json.load(open(os.path.join(M.CACHE, f'yh_{t}_1d.json')))['chart']['result'][0]
    adj = r['indicators']['adjclose'][0]['adjclose']
    return {ymd_of(ts): a for ts, a in zip(r['timestamp'], adj) if a is not None and a > 0}


def month_end_from_daily(lv):
    last = {}
    for d in sorted(lv):
        last[d // 100] = d
    out = {}
    for m in sorted(last):
        p = madd(m, -1)
        if p not in last or m > FR_END:
            continue
        dm, dp = todate(last[m]), todate(last[p])
        em = datetime.date(dm.year + (dm.month == 12), dm.month % 12 + 1, 1) - datetime.timedelta(days=1)
        ep = datetime.date(dp.year + (dp.month == 12), dp.month % 12 + 1, 1) - datetime.timedelta(days=1)
        if (em - dm).days > 7 or (ep - dp).days > 7:
            continue          # 月末の値が無い月は欠測（0で埋めない）
        out[m] = lv[last[m]] / lv[last[p]] - 1
    return out


def contiguous_tail(d):
    ks = sorted(d)
    if not ks:
        return {}
    st = ks[0]
    for a, b in zip(ks, ks[1:]):
        if madd(a, 1) != b:
            st = b
    return {k: v for k, v in d.items() if k >= st}


def av_dead(t):
    rows = sorted(csv.DictReader(open(os.path.join(M.CACHE, f'av_dead_select_{t}.csv'))), key=lambda r: r['date'])
    px = {int(r['date'][:4]) * 100 + int(r['date'][5:7]): float(r['adj']) for r in rows}
    ks = sorted(px)
    return contiguous_tail({k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k and k <= FR_END})


# ───────────────────────── 業種の勢いの自前エンジン ─────────────────────────
def mom_run(R, names, K=3, exit_rank=None, score='blend', end=FR_END, min_n=20, day=None):
    """月末（または区切り）t までの値だけで t+1 を持つ。exit_rank=None → 毎月上位 K を等分（E4）。
    exit_rank=E → 持っているものは順位が E より下がるまで持ち、続けて持つものは値動きのまま・空いた重みを新入りへ等分（X2）。
    戻り値: gross{m}, turnover{m}（Σ|Δw|）, weights{t}, entries（(銘柄, 入った t)）, exits（(銘柄, 入った t, 出た t)）"""
    months = sorted(set().union(*[set(R[s]) for s in names if R.get(s)]))
    last_of = {s: max(R[s]) for s in names if R.get(s)}

    def cum(s, t, k):
        v = 1.0
        for j in range(k):
            x = R[s].get(madd(t, -j))
            if x is None:
                return None
            v *= 1 + x
        return v - 1

    def sc(s, t):
        if score == 'r12':
            return cum(s, t, 12)
        p = [cum(s, t, k) for k in (1, 3, 6, 12)]
        return None if None in p else sum(p) / 4

    gross, turn, wpath = {}, {}, {}
    held_since = {}
    exits = []
    prev = None      # 目標の重み（t−1 に決めた）
    prev_t = None
    started = False
    for t in months:
        nx = madd(t, 1)
        if nx > end:
            break
        avail = []
        for i, s in enumerate(names):
            if not R.get(s) or last_of[s] < min(nx, end):
                continue
            v = sc(s, t)
            if v is not None:
                avail.append((-v, i, s))
        if len(avail) < min_n:
            if started:
                raise RuntimeError(f'開始後に対象が {len(avail)} 本: {t}')
            continue
        ranked = [s for _, _, s in sorted(avail)]
        rank = {s: i + 1 for i, s in enumerate(ranked)}
        drift = None
        if prev is not None and prev_t == madd(t, -1):
            g = {s: prev[s] * (1 + R[s][t]) for s in prev}
            tot = sum(g.values())
            drift = {s: v / tot for s, v in g.items()}
        if exit_rank is None or drift is None:
            w = {s: 1.0 / K for s in ranked[:K]}
        else:
            keep = {s: v for s, v in drift.items() if rank.get(s, 10 ** 9) <= exit_rank}
            freed = 1.0 - sum(keep.values())
            need = K - len(keep)
            ent = [s for s in ranked if s not in keep][:need] if need > 0 else []
            w = dict(keep)
            for s in ent:
                w[s] = freed / len(ent)
            if not ent and freed > 1e-12:
                tt = sum(w.values())
                w = {s: v / tt for s, v in w.items()}
        if not all(nx in R[s] for s in w):
            raise RuntimeError(f'保有の翌月が無い {t} {w}')
        tr = 0.0
        if drift is not None:
            tr = sum(abs(w.get(s, 0.0) - drift.get(s, 0.0)) for s in set(w) | set(drift))
            for s in drift:
                if s not in w:
                    exits.append((s, held_since.pop(s), t))
        for s in w:
            if s not in held_since:
                held_since[s] = t
        started = True
        gross[nx] = math.fsum(w[s] * R[s][nx] for s in w)
        turn[nx] = tr
        wpath[t] = w
        prev, prev_t = w, t
    return gross, turn, wpath, exits


def short_fee(exits, wpath, R, bdays, fee=0.0075):
    """30日未満で売った分に fee（入った区切りの日と出た区切りの日の暦日差 < 30）。区切りの日 bdays[t]。
    X2 は続けて持つものに買い増しが無いので1ロット。E4 は毎月の等分への戻しで買い増しがあるが、ここでは入った月の
    1か月後に丸ごと出る売りだけを数える（下限側の近似）。→ {出た月の次の月（リターンの月）: 引く割合}"""
    out = {}
    for s, t0, t1 in exits:
        if t1 != madd(t0, 1):
            continue
        d0, d1 = bdays.get(t0), bdays.get(t1)
        if d0 is None or d1 is None:
            continue
        if (todate(d1) - todate(d0)).days < 30:
            # 売った額 ＝ t1 の時点の重み（t0 に決めた重み × 値動き）
            w0 = wpath[t0][s]
            rp = math.fsum(wpath[t0][x] * R[x][t1] for x in wpath[t0])
            wt = w0 * (1 + R[s][t1]) / (1 + rp)
            out[madd(t1, 1)] = out.get(madd(t1, 1), 0.0) + fee * wt
    return out


def with_costs(gross, turn, cs=0.0005, extra=None):
    return {m: gross[m] - cs * turn[m] - (extra.get(m, 0.0) if extra else 0.0) for m in gross}


def build_verdicts(res):
    """判定（数字は res から読む。文は数字を見た後に書いた＝判定の理由の説明）"""
    C, D = res['candidates'], res['cands_detail']
    sel, jp, off = res['e1_selection'], res['stress_jp_retail_commission_vs_pure'], res['calendar_offsets_live33_vs_pure_net']['summary']
    bon = res['multiple_testing']['bonferroni_full_period_vs_pure']

    def s(p):
        return f"{p['ex']:+.2f} t{p['t']}" if p else '—'

    def nums(name, base):
        c = C[name]
        a, b = c['reproduced_vs_fee_benchmark'], c['vs_pure_benchmark']
        return (f"研究側の相手（指数ファンド −0.10%/年）で再現: 全期間 {s(a['full'])}・訓練 {s(a['train'])}・保有 {s(a['hold'])}・CAGR差 {a['hold']['cagr_diff']:+.2f}・"
                f"20年窓 {a['roll20']['win_rate']:.0%}＝{a['grade']}（主張と一致）。純粋な French Mkt 相手: 全期間 {s(b['full'])}・訓練 {s(b['train'])}・"
                f"保有 {s(b['hold'])}・CAGR差 {b['hold']['cagr_diff']:+.2f}・費用後 {s(b['net_hold'])}・最近(2013-07〜) {s(b['recent'])}・20年窓 {b['roll20']['win_rate']:.0%}＝{b['grade']}")

    V = []
    for rg in ('R0_pretax', 'R1_nisa_unlimited'):
        # E1
        nm = f'E1_cop_tilt__lump__{rg}'
        r = D['E1_cop_tilt']['robust_vs_pure_net']
        V.append({'name': nm, 'claimed_grade': 'S', 'verified_grade': 'S', 'verdict': 'confirmed', 'reproduced': True,
                  'key_numbers': nums(nm, 'E1_cop_tilt') + f"。積立20年（名目・純粋な相手）{D['E1_cop_tilt']['dca20_vs_pure']['win_rate']:.0%}・中央 {D['E1_cop_tilt']['dca20_vs_pure']['median']}",
                  'issues': [
                      f"主張の数字は相手の側だけに年0.10%の費用を置いた分だけ甘い（保有 +0.91 t3.61 → 純粋な相手で +0.81 t3.22・全期間 t5.20 → 4.37）。事前登録の全体の線は純粋な時価加重を相手にするので、正しい数字は後者。格付けは S のまま",
                      f"後知恵の選び方: cop_at は mega_tilt の同じ λ の14特徴のうち保有期間の t が1位（14本の平均 t {sel['mean_hold_t_of_all']}）で、訓練期間だけなら{sel['cop_at_rank_train']}位。論文の公表は2016年（標本〜2013）で保有期間の前半は論文の標本の中。ただし14本で Bonferroni をかけても保有 t3.22 の片側 p×14 ≈ 0.01 で C3 は残る",
                      f"近い定義9本（cop_atl1・op_at・ocf_at・ope_be・gp_at・ebit_bev・qmj_prof・vw_cap・ew）はどれも保有 t 2.37〜3.46＝『cop_at だけの当たり』ではなく収益性の傾け全体が効いている",
                      f"頑丈さ（純粋な相手・費用後）: 保有の前半 {s(r['hold_first_half_2007_2016H1'])}・後半 {s(r['hold_second_half_2016H2_'])}・公表後2017〜 {s(r['post_2017'])}・業種12でヘッジ（訓練の係数）{r['industry12_hedged_train_beta']['alpha_hold']:+.2f} t{r['industry12_hedged_train_beta']['t']}・最良3年を除く {s(r['hold_ex_drop_top3_years'])}・1998-2000/2020-21 を除く全期間 {s(r['drop_1998_2000_2020_2021']['full'])}・費用3倍 {s(r['cost_x3'])}。どれでも崩れない",
                      f"多重検定: 全期間 p×プログラム全体 {res['multiple_testing']['program_tested_rows_all_mw']}本 = {bon['E1_cop_tilt']['bonferroni_program']}（ぎりぎり）。米国外の再現は mega_tilt で 9/10 地域が正（日本は −0.10 t−0.36）",
                      "実行の現実性: 『市場＋0.11×(良い三分位−悪い三分位)』を個別株で直接持つには数千銘柄が要り、日本の個人（月17万円）には作れない。λ=0.11 が買いだけに収まるかは French の OP（cop_at ではない）の悪い側の時価総額からの近似で、JKP の三分位の時価総額では確かめられていない",
                      f"日本の米国株の手数料（0.495%×売り買い）を実現率に掛けても 保有 {s(jp['E1_cop_tilt']['hold'])}＝{jp['E1_cop_tilt']['grade_vs_pure']}（回転が小さいので効かない）",
                      "R0 と R1 は同じ上乗せ（R1 は両側に同じ配当源泉を引くだけ）で、2本の独立の確認ではない"]})
        # E1m
        nm = f'E1m_cop_mega__lump__{rg}'
        r = D['E1m_cop_mega']['robust_vs_pure_net']
        V.append({'name': nm, 'claimed_grade': 'S', 'verified_grade': 'A', 'verdict': 'downgraded to A', 'reproduced': True,
                  'key_numbers': nums(nm, 'E1m_cop_mega') + f"。積立20年（純粋な相手）中央 {D['E1m_cop_mega']['dca20_vs_pure']['median']}",
                  'issues': [
                      "主張の保有 +0.28 t3.52 のうち +0.10 は相手の側だけの費用（純粋な相手なら +0.18 t2.28）。上乗せの36%・t の3分の1が作り方の非対称から来ている",
                      f"C3（保有 t2.28）は選び方で割り引く: mega の特徴34本の族の中で cop_at を後から選んでおり、その族の Holm は最良の cop_at でも 0.50（mega_tilt_verify）。片側 p×14（この検証の近い族）でも ≈0.16",
                      f"頑丈さ: 保有の前半 {s(r['hold_first_half_2007_2016H1'])}・後半 {s(r['hold_second_half_2016H2_'])}（どちらも1.65前後）・公表後2017〜 {s(r['post_2017'])}・最良3年を除く {s(r['hold_ex_drop_top3_years'])}・業種ヘッジ {r['industry12_hedged_train_beta']['alpha_hold']:+.2f} t{r['industry12_hedged_train_beta']['t']}",
                      f"C5 は mega_tilt の地域版（同じ cop_at・JKP vw）で 9/10 地域が正 → C3 を割り引いても A は残る。全期間 t4.54 で C7 も合格（プログラム全体の Bonferroni {bon['E1m_cop_mega']['bonferroni_program']}）",
                      f"大きさは +0.18%/年（20年の積立で最終額 +2%）。日本の米国株の手数料を入れると 保有 {s(jp['E1m_cop_mega']['hold'])}＝{jp['E1m_cop_mega']['grade_vs_pure']}。mega の順位加重を数百銘柄で直接持つのは個人には作れない",
                      "R0 と R1 は同じ上乗せ"]})
        # E2
        nm = f'E2_gate_P1__lump__{rg}'
        r = D['E2_gate_P1']['robust_vs_pure_net']
        lo = res['e2_leave_one_measure_out_vs_pure_net']
        V.append({'name': nm, 'claimed_grade': 'S', 'verified_grade': 'A', 'verdict': 'downgraded to A', 'reproduced': True,
                  'key_numbers': nums(nm, 'E2_gate_P1') + f"。自前の合成（16本・11本以上そろう月・良い三分位の等分）で実現率 {res['e2_realization_per_year']}/年",
                  'issues': [
                      "主張の保有 +0.89 t2.15 は相手の側だけの費用込み。純粋な相手なら +0.79 t1.91（C3 すれすれ）・20年窓 97.7%",
                      f"保有期間の上乗せは後半だけ: 前半 2007〜2016H1 {s(r['hold_first_half_2007_2016H1'])}・後半 {s(r['hold_second_half_2016H2_'])}。最良3年（{', '.join(r['hold_top3_years'])}）を除くと {s(r['hold_ex_drop_top3_years'])}",
                      f"業種（French 12）を訓練期間の係数でヘッジすると保有 {r['industry12_hedged_train_beta']['alpha_hold']:+.2f} t{r['industry12_hedged_train_beta']['t']}＝上乗せの大半は業種の傾き",
                      f"1998-2000・2020-21 を除くと 全期間 {s(r['drop_1998_2000_2020_2021']['full'])}（C7 の t≥3 を割る）・保有 {s(r['drop_1998_2000_2020_2021']['hold'])}。費用3倍で保有 {s(r['cost_x3'])}",
                      f"16本の1本抜き: 保有 t {lo['hold_t_min']}〜{lo['hold_t_max']}（中央 {lo['hold_t_median']}）・全期間 t≥3 は {lo['share_full_t_ge_3']:.0%}",
                      "保有期間は新しい答え合わせではない（gate_proxy_verify: 登録前に見えていた H3 と相関0.895）。C3 を割り引き、C5 は gate_proxy_verify の国パネル 34/36（私は再計算していない）に頼って A",
                      f"日本の個人が米国株を直接売買すると（0.495%×売り買い×実現率 {res['e2_realization_per_year']}）年 {jp['E2_gate_P1']['cost_per_year_pct']}% かかり、保有 {s(jp['E2_gate_P1']['hold'])}＝{jp['E2_gate_P1']['grade_vs_pure']}。数百銘柄の三分位は個人には作れない",
                      "R0 と R1 は同じ上乗せ"]})
        # X2
        nm = f'X2_fsel_bl_buf__lump__{rg}'
        d = D['X2_fsel_bl_buf']
        r = d['robust_vs_pure_net']
        rf_ = d['real_fees']
        g = res['fidelity_neighbor_grid_vs_pure_net']
        l1 = res['x2_leave_one_fund_out_vs_pure_net']
        V.append({'name': nm, 'claimed_grade': 'S', 'verified_grade': 'B', 'verdict': 'downgraded to B', 'reproduced': True,
                  'key_numbers': nums(nm, 'X2_fsel_bl_buf') + f"。回転 {d['turnover_oneway_per_year']}/年（片道）",
                  'issues': [
                      f"S は C7 の『全期間 t≥3.0』だけで通っていて、その t{C[nm]['reproduced_vs_fee_benchmark']['full']['t']} は相手の側だけの費用 0.10%/年で作られている。純粋な French Mkt 相手では 全期間 t{C[nm]['vs_pure_benchmark']['full']['t']}・族の Holm 0.35（研究側）で C7 不合格＝機械的に B",
                      f"Fidelity Select の実在の費用（SEC Form 497・2003）を入れていない: 2003-09-22 まで申込手数料 3%（1990-10 以前は 2%＋解約時 1%）・30日未満の売り 0.75%。入れると 保有 {s(rf_['short_fee_0.75_only_vs_pure']['hold'])}（C3 割れ）・全期間 {s(rf_['load_plus_short_fee_vs_pure']['full'])}・訓練 {s(rf_['load_plus_short_fee_vs_pure']['train'])}＝{rf_['grade_vs_pure_with_real_fees'][0]}。積立20年は勝率 {d['dca20_vs_pure_with_load_and_short_fee']['win_rate']:.0%}",
                      f"入れ替えの日をずらすと（生きた33本・20通り）保有の平均 +{off['X2']['hold_ex_mean']} t{off['X2']['hold_t_mean']}、t≥1.65 は {off['X2']['share_hold_t_ge_1.65']:.0%}、全期間 t≥3 は {off['X2']['share_full_t_ge_3']:.0%}（月末だけ）。月末は20通り中 保有 t で{off['X2']['month_end_rank_of_hold_t']}位＝分布の上の端",
                      f"保有期間の上乗せは最良3年（{', '.join(r['hold_top3_years'])}）で全部: 除くと {s(r['hold_ex_drop_top3_years'])}。後半 2016H2〜 {s(r['hold_second_half_2016H2_'])}。寄与の上位はエネルギー・天然資源（FSENX・FNARX）・バイオ・半導体",
                      f"訓練は1999年とITバブル頼み: 1998-2000・2020-21 を除くと訓練 {s(r['drop_1998_2000_2020_2021']['train'])}（C1 割れ）",
                      f"近い母数32通り（K2〜6・帯・順位の作り方）で S は {g['share_grade_S']:.0%}・A も0。12か月の順位にすると保有 t {min(v['hold_t'] for k, v in g['grid'].items() if k.startswith('r12')):.2f}〜{max(v['hold_t'] for k, v in g['grid'].items() if k.startswith('r12')):.2f}。1本抜きで全期間 t≥3 は {l1['share_full_t_ge_3']:.0%}、最悪（{l1['worst_hold'][0]}抜き）保有 {l1['worst_hold'][1]['hold_ex']:+.2f} t{l1['worst_hold'][1]['hold_t']}",
                      f"生き残りの偏り: 死んだ6本を足すと保有 {res['x2_live_only_vs_pure_net']['hold']['ex']:+.2f}→{C[nm]['vs_pure_benchmark']['hold']['ex']:+.2f} に下がる。1999年以前に消えた Select と AV に無いものは入っていない＝真の上乗せはさらに小さい向き",
                      "多重検定: E4 は etf_tactical の探索の族（角度全体で参照を除く76本・Holm 1.0）から来ており、X2 はこの角度の主の族の結果を見た後の探索。日本の居住者は買えない",
                      "それでも保有期間の符号は20通りの日・39通りの1本抜き・費用のどの版でも正、訓練 t≥2 もずらしの80%で残る＝B（有望・弱い）までは支持する",
                      "R0 と R1 は同じ上乗せ"]})
        # E4
        nm = f'E4_fsel_top3__lump__{rg}'
        d = D['E4_fsel_top3']
        r = d['robust_vs_pure_net']
        rf_ = d['real_fees']
        V.append({'name': nm, 'claimed_grade': 'B', 'verified_grade': 'B', 'verdict': 'confirmed', 'reproduced': True,
                  'key_numbers': nums(nm, 'E4_fsel_top3') + f"。回転 {d['turnover_oneway_per_year']}/年（片道）",
                  'issues': [
                      "B は純粋な相手でも同じ（全期間 t2.94 で C7 不合格・保有 t1.69）",
                      f"実在の費用（申込手数料 3%・30日未満 0.75%）で 保有 {s(rf_['short_fee_0.75_only_vs_pure']['hold'])}・訓練 {s(rf_['load_plus_short_fee_vs_pure']['train'])}＝{rf_['grade_vs_pure_with_real_fees'][0]}（30日未満の売りは出口の {rf_['share_exits_lt30d']:.0%}）",
                      f"入れ替えの日のずらし20通りで保有の平均 +{off['E4']['hold_ex_mean']} t{off['E4']['hold_t_mean']}（t≥1.65 は {off['E4']['share_hold_t_ge_1.65']:.0%}）、月末は保有 t で{off['E4']['month_end_rank_of_hold_t']}位",
                      f"最良3年（{', '.join(r['hold_top3_years'])}）を除くと保有 {s(r['hold_ex_drop_top3_years'])}・後半 {s(r['hold_second_half_2016H2_'])}・1998-2000/2020-21 抜きの訓練 {s(r['drop_1998_2000_2020_2021']['train'])}",
                      "etf_tactical_verify と同じ結論（弱い B）。日本の居住者は買えない。R0 と R1 は同じ上乗せ"]})
    return V


def lump_with_load(s, b, a, z):
    """一括の窓 [a, z] で、申込手数料を入れた戦略の幾何の年率 − 相手の年率"""
    w = mrange(a, z)
    Ws = math.exp(math.fsum(math.log1p(s[k]) for k in w))
    Wb = math.exp(math.fsum(math.log1p(b[k]) for k in w))
    if a < 199010:
        Ws *= 0.98 * 0.99
    elif a < 200309:
        Ws *= 0.97
    n = len(w) / 12
    return Ws ** (1 / n) - Wb ** (1 / n)


def load_series(s, a):
    """期間統計用: 期間の最初の月に申込手数料を1回だけ引いた系列（算術の超過に 3%/年数 が入る）"""
    out = dict(s)
    k0 = min(k for k in s if k >= a)
    hit = 0.03 if k0 < 200309 else 0.0
    if k0 < 199010:
        hit = 0.02
    out[k0] = (1 + s[k0]) * (1 - hit) - 1
    return out


# ───────────────────────── 本体 ─────────────────────────
def main():
    res = {'angle': 'jp_aftertax', 'role': 'adversarial verifier（反証の検証）', 'generated': datetime.date.today().isoformat(),
           'researcher_files': ['night/mw_jp_aftertax.py', 'out/mw_jp_aftertax_prereg.json', 'out/mw_jp_aftertax_prereg2.json', 'out/mw_jp_aftertax.json'],
           'independence': ('mw_common からは取得の関数（ff_factors・jkp_rows・get・french_tables・yahoo・CACHE）だけ。三分位 LS・門の16本の合成・'
                            'Fidelity の順位と帯・費用・超過・NW t・CAGR・20年窓・積立・格付けは自前。Fidelity の生きた33本は Yahoo 日次から月末を作り直した'),
           'benchmarks': {'pure': 'French Mkt（Mkt-RF+RF・上限なしの時価加重）＝全体の事前登録の相手', 'fee': '研究側の相手: French Mkt − 年0.10%（指数ファンドの費用）。戦略側（個別株の直接保有）は費用0'}}
    res['scope'] = ('検証したのは一括の格付け（R0 税前・R1 枠なし非課税）と税前の積立20年。研究側の税と NISA の模擬（R2・R3・X1 置き場所・損出し）は'
                    '作り直していない（主張の S/A はどれも R0/R1 の行で、税を入れた行は研究側でも C か B）')
    res['sources_fees'] = {'fidelity_select_load': 'https://www.sec.gov/Archives/edgar/data/0000320351/000035705703000016/main.htm（Form 497・2003: 2003-09-22 から申込手数料 3% を廃止・1990-10-12 以前は 2%＋解約時 1%・Select 間の交換には後払いの手数料なし・30日未満の売り 0.75%・交換 $7.50）。ここでは申込手数料を窓の最初の1回だけ掛けた（交換には掛からないと置いた＝戦略に甘い側）',
                           'jp_us_stock_commission': '楽天証券・SBI証券の米国株の約定代金の 0.495%（上限 22ドル）＝事前登録の外の試験に使った仮定'}
    mkt, rf = load_french()
    mkt_fee ={k: v - BENCH_FEE / 12 for k, v in mkt.items()}
    dy = div_return()
    icols, ind = industries12()
    Xind = {m: [row[i] - mkt[m] for i in range(len(icols))] for m, row in ind.items() if m in mkt}
    claimed = json.load(open(os.path.join(BASE, 'out', 'mw_jp_aftertax.json')))
    CL = {x['name']: x for x in claimed['tested'] if x.get('kind') == 'lump_grade'}

    def r1(s, bench):
        """R1（枠なしの非課税・米国配当の源泉10%は両側とも戻らない）"""
        return ({k: v - WH * dy[k] for k, v in s.items() if k in dy}, {k: v - WH * dy[k] for k, v in bench.items() if k in dy})

    # ───── E1・E1m・E2（JKP）
    P = jkp_port_vw()
    D = jkp_dirs('vw')
    cop_ls = tercile_ls(P, 'cop_at', D['cop_at'])
    fac = jkp_factor_ret('cop_at', 'vw')
    ks = sorted(k for k in cop_ls if k in fac and JKP_START <= k <= JKP_END)
    res['e1_ls_check'] = {'my_ls_vs_jkp_factor_corr': round(float(np.corrcoef([cop_ls[k] for k in ks], [fac[k] for k in ks])[0, 1]), 4),
                          'my_ls_mean_ann': round(S.mean(cop_ls[k] for k in ks) * 1200, 2), 'jkp_factor_mean_ann': round(S.mean(fac[k] for k in ks) * 1200, 2),
                          'months': len(ks), 'direction': D['cop_at']}
    log('E1 LS の検算', res['e1_ls_check'])

    def tilt(ls, lam, T, cu):
        g = {k: mkt[k] + lam * ls[k] for k in ls if k in mkt and JKP_START <= k <= JKP_END}
        n = {k: v - T * cu / 12 for k, v in g.items()}
        return g, n

    cands = {}
    E1g, E1n = tilt(cop_ls, 0.11, 0.11 * 2 * 0.4 + 0.04, 0.001)
    megals = mega_ls('cop_at', D['cop_at'])
    E1mg, E1mn = tilt(megals, 0.04, 0.04 * 2 * 0.4 + 0.04, 0.001)

    # E2: 門の16本（事前登録の対応表の写し＝定義）
    MEAS = {'M01_roic': [('ebit_bev', 1)], 'M02_opm': [('ebit_sale', 1)], 'M03_gpa': [('gp_at', 1)], 'M04_conv': [('oaccruals_ni', -1)],
            'M05_accr': [('oaccruals_at', -1)], 'M06_lev': [('netdebt_me', -1)], 'M07_z': [('z_score', 1)], 'M08_intcov': [('o_score', -1)],
            'M09_p1': [('ni_ivol', -1), ('ocfq_saleq_std', -1)], 'M10_p2': [('qmj_safety', 1)], 'M11_growth': [('sale_gr3', 1)],
            'M12_roiic': [('qmj_growth', 1)], 'M13_shy': [('eqnpo_me', 1)], 'M14_dil': [('chcsho_12m', -1)], 'M15_roict': [('niq_be_chg1', 1)],
            'M16_moat': [('ni_ar1', 1)]}
    TURN = {'ebit_bev': 0.5, 'ebit_sale': 0.4, 'gp_at': 0.4, 'oaccruals_ni': 1.2, 'oaccruals_at': 1.2, 'netdebt_me': 0.6, 'z_score': 0.6,
            'o_score': 0.8, 'ni_ivol': 0.4, 'ocfq_saleq_std': 0.5, 'qmj_safety': 0.6, 'sale_gr3': 0.8, 'qmj_growth': 0.8, 'eqnpo_me': 0.8,
            'chcsho_12m': 1.0, 'niq_be_chg1': 2.0, 'ni_ar1': 0.5}

    def composite(meas):
        sl = {}
        for mname, px in meas.items():
            ss = [good_side(P, c, d) for c, d in px]
            sl[mname] = {k: math.fsum(s[k] for s in ss if k in s) / sum(1 for s in ss if k in s) for k in set().union(*ss)}
        need = math.ceil(2 * len(meas) / 3)
        out = {}
        for k in set().union(*sl.values()):
            v = [s[k] for s in sl.values() if k in s]
            if len(v) >= need:
                out[k] = math.fsum(v) / len(v)
        return {k: v + rf[k] for k, v in out.items() if k in rf and JKP_START <= k <= JKP_END}

    def e2_T(meas):
        return S.mean(S.mean(TURN.get(c, 0.8) for c, _ in px) for px in meas.values()) + 0.10 + 0.04

    E2g = composite(MEAS)
    T2 = e2_T(MEAS)
    E2n = {k: v - T2 * 0.002 / 12 for k, v in E2g.items()}
    res['e2_realization_per_year'] = round(T2, 3)

    jkp_last = min(max(E1g), JKP_END)
    for nm, g_, n_ in (('E1_cop_tilt', E1g, E1n), ('E1m_cop_mega', E1mg, E1mn), ('E2_gate_P1', E2g, E2n)):
        first = min(n_)
        rec = {}
        # R0: 研究側の相手（費用0.10%）／純粋な相手
        rec['R0_vs_fee_net'] = pack(n_, mkt_fee, first, jkp_last)
        rec['R0_vs_pure_net'] = pack(n_, mkt, first, jkp_last)
        rec['R0_vs_pure_gross_C2C3_net_C6'] = pack(n_, mkt, first, jkp_last, gross=g_)
        s1, b1 = r1(n_, mkt_fee)
        rec['R1_vs_fee_net'] = pack(s1, b1, first, jkp_last)
        s1p, b1p = r1(n_, mkt)
        rec['R1_vs_pure_net'] = pack(s1p, b1p, first, jkp_last)
        # 積立20年（税前・名目の毎月1）
        rec['dca20_vs_fee'] = dca20({k: v for k, v in n_.items() if k <= jkp_last}, mkt_fee)
        rec['dca20_vs_pure'] = dca20({k: v for k, v in n_.items() if k <= jkp_last}, mkt)
        # 頑丈さ（純粋な相手・費用後）
        rob = {}
        rob['hold_first_half_2007_2016H1'] = ex(n_, mkt, HOLD_START, madd(HALF_SPLIT, -1))
        rob['hold_second_half_2016H2_'] = ex(n_, mkt, HALF_SPLIT, jkp_last)
        drop = set(mrange(199801, 200012)) | set(mrange(202001, 202112))
        rob['drop_1998_2000_2020_2021'] = {'full': ex(n_, mkt, first, jkp_last, drop), 'train': ex(n_, mkt, first, TRAIN_END, drop),
                                           'hold': ex(n_, mkt, HOLD_START, jkp_last, drop)}
        rob['drop_2008_2009_hold'] = ex(n_, mkt, HOLD_START, jkp_last, set(mrange(200801, 200912)))
        rob['post_2017'] = ex(n_, mkt, POSTPUB_COP, jkp_last)
        rob['cost_x3'] = ex({k: g_[k] - 3 * (g_[k] - n_[k]) for k in n_}, mkt, HOLD_START, jkp_last)
        # 業種（French 12）を訓練期間の係数でヘッジ
        y = {k: n_[k] - mkt[k] for k in n_ if k in Xind}
        trk = [k for k in sorted(y) if k <= TRAIN_END]
        hok = [k for k in sorted(y) if HOLD_START <= k <= jkp_last]
        rob['industry12_hedged_train_beta'] = ols_hedge(y, Xind, trk, hok)
        # 暦年: 保有期間で最も良い3年を除く
        yr = {}
        for k in n_:
            if HOLD_START <= k <= jkp_last:
                yr.setdefault(k // 100, []).append(n_[k] - mkt[k])
        ys = sorted(yr, key=lambda y_: -math.fsum(yr[y_]))
        top3 = ys[:3]
        rob['hold_top3_years'] = {str(y_): round(math.fsum(yr[y_]) * 100, 2) for y_ in top3}
        rob['hold_ex_drop_top3_years'] = ex(n_, mkt, HOLD_START, jkp_last, {k for k in n_ if k // 100 in top3})
        rec['robust_vs_pure_net'] = rob
        cands[nm] = rec
        log(nm, 'R0 vs fee  ', brief(rec['R0_vs_fee_net']))
        log(nm, 'R0 vs pure ', brief(rec['R0_vs_pure_net']))
        log(nm, 'R1 vs fee  ', brief(rec['R1_vs_fee_net']))
        log(nm, 'R1 vs pure ', brief(rec['R1_vs_pure_net']))
        log(nm, 'dca', rec['dca20_vs_fee'], rec['dca20_vs_pure'])
        log(nm, 'robust', json.dumps(rob, ensure_ascii=False))

    # E1 の選び方: mega_tilt の P-B 17本（同じ λ=0.11・同じ費用）の中の順位（保有期間）
    pb = ['gp_at', 'ope_be', 'qmj', 'qmj_prof', 'cop_at', 'chcsho_12m', 'oaccruals_at', 'ret_12_1', 'be_me', 'ni_me', 'at_gr1',
          'ivol_capm_252d', 'betabab_1260d', 'niq_su']
    sel = {}
    for c in pb:
        if c not in P or c not in D:
            continue
        ls = tercile_ls(P, c, D[c])
        g_, n_ = tilt(ls, 0.11, 0.11 * 2 * 0.4 + 0.04, 0.001)
        h = ex(n_, mkt, HOLD_START, jkp_last)
        tr = ex(n_, mkt, min(n_), TRAIN_END)
        pp = ex(n_, mkt, POSTPUB_COP, jkp_last)
        sel[c] = {'train_ex': tr and tr['ex'], 'train_t': tr and tr['t'], 'hold_ex': h and h['ex'], 'hold_t': h and h['t'],
                  'post2017_ex': pp and pp['ex'], 'post2017_t': pp and pp['t']}
    order_hold = sorted(sel, key=lambda c: -(sel[c]['hold_t'] or -9))
    order_train = sorted(sel, key=lambda c: -(sel[c]['train_t'] or -9))
    res['e1_selection'] = {'features_at_lambda_0.11_vs_pure_net': sel, 'rank_by_hold_t': order_hold, 'rank_by_train_t': order_train,
                           'cop_at_rank_hold': order_hold.index('cop_at') + 1, 'cop_at_rank_train': order_train.index('cop_at') + 1,
                           'mean_hold_t_of_all': round(S.mean(sel[c]['hold_t'] for c in sel), 2),
                           'note': 'mega_tilt の P-B 14特徴（Q5/QM/QMV の合成3本は除く）を同じ λ・費用で。cop_at は 2016 年公表（標本〜2013）＝保有期間の前半は論文の標本の中'}
    log('E1 の選び方', json.dumps(res['e1_selection'], ensure_ascii=False)[:1500])
    # E1 の近い定義（同じ λ）: 別の収益性・別の重み付け
    nb = {}
    for c in ['cop_atl1', 'op_at', 'ocf_at', 'ope_be', 'gp_at', 'ebit_bev', 'qmj_prof']:
        if c in P:
            g_, n_ = tilt(tercile_ls(P, c, D[c]), 0.11, 0.128, 0.001)
            nb[c] = {'hold': ex(n_, mkt, HOLD_START, jkp_last), 'post2017': ex(n_, mkt, POSTPUB_COP, jkp_last), 'full': ex(n_, mkt, min(n_), jkp_last)}
    for w_ in ['vw_cap', 'ew']:
        try:
            fr_ = jkp_factor_ret('cop_at', w_)
            g_, n_ = tilt(fr_, 0.11, 0.128, 0.001)
            nb['cop_at_' + w_] = {'hold': ex(n_, mkt, HOLD_START, jkp_last), 'post2017': ex(n_, mkt, POSTPUB_COP, jkp_last), 'full': ex(n_, mkt, min(n_), jkp_last)}
        except Exception as e:  # noqa
            nb['cop_at_' + w_] = str(e)[:100]
    res['e1_neighbors_lambda_0.11_vs_pure_net'] = nb
    log('E1 近隣', json.dumps({k: (v['hold'] if isinstance(v, dict) else v) for k, v in nb.items()}, ensure_ascii=False)[:1500])
    # E2 の1本抜き
    loo = {}
    for mname in MEAS:
        mm = {k: v for k, v in MEAS.items() if k != mname}
        g_ = composite(mm)
        n_ = {k: v - e2_T(mm) * 0.002 / 12 for k, v in g_.items()}
        loo[mname] = {'hold': ex(n_, mkt, HOLD_START, jkp_last), 'full': ex(n_, mkt, min(n_), jkp_last), 'train': ex(n_, mkt, min(n_), TRAIN_END)}
    ht = sorted(v['hold']['t'] for v in loo.values())
    res['e2_leave_one_measure_out_vs_pure_net'] = {'detail': loo, 'hold_t_min': ht[0], 'hold_t_median': ht[len(ht) // 2], 'hold_t_max': ht[-1],
                                                   'share_hold_t_ge_1.65': round(sum(1 for v in ht if v >= 1.65) / len(ht), 3),
                                                   'share_full_t_ge_3': round(sum(1 for v in loo.values() if v['full']['t'] >= 3) / len(loo), 3)}
    log('E2 1本抜き', res['e2_leave_one_measure_out_vs_pure_net']['hold_t_min'], res['e2_leave_one_measure_out_vs_pure_net']['hold_t_median'])

    # ───── E4・X2（Fidelity Select）
    R = {}
    ymchk = {}
    for t in FSEL:
        lv = daily_levels(t)
        R[t] = contiguous_tail(month_end_from_daily(lv))
        mo = M.yahoo(t)
        kk = [k for k in R[t] if k in mo and k <= FR_END]
        ymchk[t] = {'from': min(R[t]), 'n': len(R[t]), 'mean_abs_diff_vs_yahoo_monthly_pct': round(S.mean(abs(R[t][k] - mo[k]) for k in kk) * 100, 3) if kk else None}
    for t in DEAD:
        R['AV_' + t] = av_dead(t)
    res['fidelity_data'] = {'live_from_daily': ymchk, 'dead_from_av': {t: [min(R['AV_' + t]), max(R['AV_' + t])] for t in DEAD}}
    names_all = FSEL + ['AV_' + t for t in DEAD]
    # 区切りの日（月末の最後の営業日）: French 日次の暦
    ffd = M.ff_factors('daily')
    days = sorted(ffd['mktrf'])
    lastday = {}
    for d in days:
        lastday[d // 100] = d

    def fid_eval(K, E, score, names=names_all, R_=R, bench=mkt, bdays=lastday, fee075=True):
        g_, tr_, wp, exits = mom_run(R_, names, K, E, score)
        n_ = with_costs(g_, tr_)
        out = {'turnover_oneway_per_year': round(S.mean(tr_.values()) * 12 / 2, 2), 'first': min(g_), 'last': max(g_)}
        out['gross'], out['net'], out['wpath'], out['exits'] = g_, n_, wp, exits
        if fee075:
            sf = short_fee(exits, wp, R_, bdays)
            out['net_fee075'] = with_costs(g_, tr_, extra=sf)
            out['share_exits_lt30d'] = round(len(sf) / max(1, len(exits)), 3)
        return out

    X2 = fid_eval(3, 6, 'blend')
    E4 = fid_eval(3, None, 'blend')
    first4 = min(E4['net'])
    fid = {}
    for nm, e in (('X2_fsel_bl_buf', X2), ('E4_fsel_top3', E4)):
        first, last = min(e['net']), FR_END
        rec = {'turnover_oneway_per_year': e['turnover_oneway_per_year'], 'from': first}
        rec['R0_vs_fee_net'] = pack(e['net'], mkt_fee, first, last)
        rec['R0_vs_pure_net'] = pack(e['net'], mkt, first, last)
        rec['R0_vs_pure_gross_C2C3_net_C6'] = pack(e['net'], mkt, first, last, gross=e['gross'])
        s1, b1 = r1(e['net'], mkt_fee)
        rec['R1_vs_fee_net'] = pack(s1, b1, first, last)
        s1p, b1p = r1(e['net'], mkt)
        rec['R1_vs_pure_net'] = pack(s1p, b1p, first, last)
        # 実在の費用: 申込手数料（期間の最初に1回）＋30日未満 0.75%
        nf = e['net_fee075']
        rec['real_fees'] = {'short_fee_0.75_only_vs_pure': {'hold': ex(nf, mkt, HOLD_START, last), 'full': ex(nf, mkt, first, last), 'train': ex(nf, mkt, first, TRAIN_END)},
                            'share_exits_lt30d': e['share_exits_lt30d']}
        full_l = load_series(nf, first)
        train_l = load_series(nf, first)
        rec['real_fees']['load_plus_short_fee_vs_pure'] = {'full': ex(full_l, mkt, first, last), 'train': ex(train_l, mkt, first, TRAIN_END),
                                                           'hold': ex(nf, mkt, HOLD_START, last)}
        # 一括20年窓（7月起点）に申込手数料
        wins = []
        for y in range(first // 100, 2100):
            a, z = y * 100 + 7, (y + 20) * 100 + 6
            if a < first:
                continue
            if z > last:
                break
            wins.append((y, round(lump_with_load(nf, mkt, a, z) * 100, 2)))
        rec['real_fees']['roll20_with_load_and_short_fee_vs_pure'] = {'n': len(wins), 'win_rate': round(sum(1 for _, c in wins if c > 0) / len(wins), 3) if wins else None,
                                                                    'median': sorted(c for _, c in wins)[len(wins) // 2] if wins else None, 'worst': min(wins, key=lambda x: x[1]) if wins else None}
        rec['real_fees']['grade_vs_pure_with_real_fees'] = grade(ex(full_l, mkt, first, last), ex(train_l, mkt, first, TRAIN_END),
                                                                 ex(nf, mkt, HOLD_START, last), ex(nf, mkt, HOLD_START, last),
                                                                 {'win_rate': rec['real_fees']['roll20_with_load_and_short_fee_vs_pure']['win_rate'] or 0})
        loadf = lambda m: 0.03 if m < 200309 else 0.0
        rec['dca20_vs_fee'] = dca20(e['net'], mkt_fee)
        rec['dca20_vs_pure'] = dca20(e['net'], mkt)
        rec['dca20_vs_pure_with_load_and_short_fee'] = dca20(nf, mkt, load=loadf)
        rob = {}
        n_ = e['net']
        rob['hold_first_half_2007_2016H1'] = ex(n_, mkt, HOLD_START, madd(HALF_SPLIT, -1))
        rob['hold_second_half_2016H2_'] = ex(n_, mkt, HALF_SPLIT, last)
        drop = set(mrange(199801, 200012)) | set(mrange(202001, 202112))
        rob['drop_1998_2000_2020_2021'] = {'full': ex(n_, mkt, first, last, drop), 'train': ex(n_, mkt, first, TRAIN_END, drop), 'hold': ex(n_, mkt, HOLD_START, last, drop)}
        rob['train_drop_1999'] = ex(n_, mkt, first, TRAIN_END, set(mrange(199901, 199912)))
        yr = {}
        for k in n_:
            if HOLD_START <= k <= last:
                yr.setdefault(k // 100, []).append(n_[k] - mkt[k])
        ys = sorted(yr, key=lambda y_: -math.fsum(yr[y_]))
        rob['hold_top3_years'] = {str(y_): round(math.fsum(yr[y_]) * 100, 2) for y_ in ys[:3]}
        rob['hold_ex_drop_top3_years'] = ex(n_, mkt, HOLD_START, last, {k for k in n_ if k // 100 in ys[:3]})
        # どのファンドが保有期間の超過を作ったか（Σ w×(r − mkt)）
        ctb = {}
        for t_, w in e['wpath'].items():
            m1 = madd(t_, 1)
            if m1 < HOLD_START:
                continue
            for s, x in w.items():
                ctb[s] = ctb.get(s, 0.0) + x * (R[s][m1] - mkt[m1])
        tot = sum(ctb.values())
        top = sorted(ctb.items(), key=lambda kv: -kv[1])[:5]
        rob['hold_contribution_top5_funds_pct_of_total'] = {s: round(v / tot * 100, 1) for s, v in top} if tot else None
        rec['robust_vs_pure_net'] = rob
        fid[nm] = rec
        log(nm, 'R0 vs fee  ', brief(rec['R0_vs_fee_net']))
        log(nm, 'R0 vs pure ', brief(rec['R0_vs_pure_net']))
        log(nm, 'R1 vs pure ', brief(rec['R1_vs_pure_net']))
        log(nm, 'real fees', json.dumps(rec['real_fees'], ensure_ascii=False)[:900])
        log(nm, 'dca', rec['dca20_vs_fee'], rec['dca20_vs_pure'], rec['dca20_vs_pure_with_load_and_short_fee'])
        log(nm, 'robust', json.dumps(rob, ensure_ascii=False)[:1500])
    # 近い母数（純粋な相手・費用後・0.75% なし）
    grid = {}
    for score in ('blend', 'r12'):
        for K, E in ((2, 2), (2, 3), (2, 4), (2, 6), (3, 3), (3, 4), (3, 5), (3, 6), (3, 7), (3, 9), (4, 4), (4, 6), (4, 8), (4, 12), (5, 10), (6, 12)):
            e = fid_eval(K, None if E == K else E, score, fee075=False)
            p_ = pack(e['net'], mkt, min(e['net']), FR_END)
            grid[f'{score}_K{K}_E{E}'] = {'grade': p_['grade'], 'full_t': p_['full']['t'], 'train_t': p_['train']['t'], 'hold_ex': p_['hold']['ex'],
                                          'hold_t': p_['hold']['t'], 'turnover': e['turnover_oneway_per_year']}
    ht = [v['hold_t'] for v in grid.values()]
    res['fidelity_neighbor_grid_vs_pure_net'] = {'grid': grid, 'n': len(grid), 'hold_t_median': sorted(ht)[len(ht) // 2],
                                                 'share_grade_S': round(sum(1 for v in grid.values() if v['grade'] == 'S') / len(grid), 3),
                                                 'share_grade_A_or_S': round(sum(1 for v in grid.values() if v['grade'] in 'AS') / len(grid), 3),
                                                 'blend_only_share_S': round(sum(1 for k, v in grid.items() if k.startswith('blend') and v['grade'] == 'S') / 16, 3)}
    log('Fidelity 近隣', json.dumps({k: (v['grade'], v['full_t'], v['hold_ex'], v['hold_t']) for k, v in grid.items()}, ensure_ascii=False))
    # 1本抜き（X2）
    l1 = {}
    for s in names_all:
        e = fid_eval(3, 6, 'blend', names=[x for x in names_all if x != s], fee075=False)
        h = ex(e['net'], mkt, HOLD_START, FR_END)
        f = ex(e['net'], mkt, min(e['net']), FR_END)
        l1[s] = {'hold_ex': h['ex'], 'hold_t': h['t'], 'full_t': f['t']}
    res['x2_leave_one_fund_out_vs_pure_net'] = {'worst_hold': min(l1.items(), key=lambda kv: kv[1]['hold_t']),
                                                'share_full_t_ge_3': round(sum(1 for v in l1.values() if v['full_t'] >= 3) / len(l1), 3),
                                                'share_hold_t_ge_1.65': round(sum(1 for v in l1.values() if v['hold_t'] >= 1.65) / len(l1), 3),
                                                'detail': l1}
    log('X2 1本抜き', res['x2_leave_one_fund_out_vs_pure_net']['worst_hold'], res['x2_leave_one_fund_out_vs_pure_net']['share_full_t_ge_3'])
    # 死んだ6本を抜くと（生き残りの偏りの向き）
    e = fid_eval(3, 6, 'blend', names=FSEL, fee075=False)
    res['x2_live_only_vs_pure_net'] = {'hold': ex(e['net'], mkt, HOLD_START, FR_END), 'full': ex(e['net'], mkt, min(e['net']), FR_END)}
    log('X2 生きた33本だけ', res['x2_live_only_vs_pure_net'])

    # 入れ替えの日をずらす（生きた33本だけ・日次から・相手は同じ区間の French 日次 Mkt）
    lvs = {t: daily_levels(t) for t in FSEL}
    dmkt = {d: ffd['mktrf'][d] + ffd['rf'][d] for d in days}
    bym = {}
    for d in days:
        bym.setdefault(d // 100, []).append(d)

    def bounds(k=None, n=None):
        out = {}
        for m, v in bym.items():
            if k is not None and len(v) >= k:
                out[m] = v[k - 1]
            if n is not None and len(v) >= n:
                out[m] = v[-n]
        return out

    def interval(lv, bnd):
        ks = sorted(lv)
        out = {}
        for m in sorted(bnd):
            m2 = madd(m, 1)
            if m2 not in bnd:
                continue
            vals = []
            for d in (bnd[m], bnd[m2]):
                i = bisect.bisect_right(ks, d) - 1
                if i < 0 or (todate(d) - todate(ks[i])).days > 5:
                    vals.append(None)
                else:
                    vals.append(lv[ks[i]])
            if None not in vals:
                out[m2] = vals[1] / vals[0] - 1     # ラベル＝区間の終わりの月（月末版と同じ向き）
        return contiguous_tail({k: v for k, v in out.items() if k <= FR_END})

    def bench_int(bnd):
        pos = {d: i for i, d in enumerate(days)}
        out = {}
        for m in sorted(bnd):
            m2 = madd(m, 1)
            if m2 not in bnd:
                continue
            v = 1.0
            for d in days[pos[bnd[m]] + 1:pos[bnd[m2]] + 1]:
                v *= 1 + dmkt[d]
            out[m2] = v - 1
        return out

    offs = {}
    for lab, kw in [('n1_month_end', {'n': 1})] + [(f'k{k}', {'k': k}) for k in range(1, 16)] + [(f'n{n}', {'n': n}) for n in (2, 3, 5, 8)]:
        bnd = bounds(**kw)
        Ro = {t: interval(lvs[t], bnd) for t in FSEL}
        bo = bench_int(bnd)
        row = {}
        for nm, K, E in (('X2', 3, 6), ('E4', 3, None)):
            g_, tr_, wp, exits = mom_run(Ro, FSEL, K, E, 'blend')
            n_ = with_costs(g_, tr_)
            f0 = min(n_)
            row[nm] = {'full': ex(n_, bo, f0, FR_END), 'train': ex(n_, bo, f0, TRAIN_END), 'hold': ex(n_, bo, HOLD_START, FR_END)}
        offs[lab] = row
        log('ずらし', lab, 'X2', row['X2']['hold'] and (row['X2']['hold']['ex'], row['X2']['hold']['t']), 'full t', row['X2']['full']['t'],
            '| E4', row['E4']['hold'] and (row['E4']['hold']['ex'], row['E4']['hold']['t']))
    summ = {}
    for nm in ('X2', 'E4'):
        hs = [v[nm]['hold']['ex'] for v in offs.values()]
        hts = [v[nm]['hold']['t'] for v in offs.values()]
        fts = [v[nm]['full']['t'] for v in offs.values()]
        trs = [v[nm]['train']['t'] for v in offs.values()]
        summ[nm] = {'n_offsets': len(hs), 'hold_ex_mean': round(S.mean(hs), 2), 'hold_t_mean': round(S.mean(hts), 2),
                    'share_hold_t_ge_1.65': round(sum(1 for x in hts if x >= 1.65) / len(hts), 3),
                    'share_full_t_ge_3': round(sum(1 for x in fts if x >= 3) / len(fts), 3),
                    'share_train_t_ge_2': round(sum(1 for x in trs if x >= 2) / len(trs), 3),
                    'month_end_hold': offs['n1_month_end'][nm]['hold'], 'month_end_full_t': offs['n1_month_end'][nm]['full']['t'],
                    'month_end_rank_of_hold_t': sorted(hts, reverse=True).index(offs['n1_month_end'][nm]['hold']['t']) + 1}
    res['calendar_offsets_live33_vs_pure_net'] = {'what': '区切りの日を月の k 営業日目 / 最後から n 番目の営業日へ。生きた33本だけ（死んだ6本は日次が無い）', 'summary': summ, 'by_offset': offs}
    log('ずらしの要約', json.dumps(summ, ensure_ascii=False)[:1500])

    # ───── 日本の個人が米国の個別株を直接持つ場合の手数料（事前登録の外の試験・判定は変えない）
    # 楽天・SBI の米国株の手数料は約定代金の 0.495%（上限 22ドル）。数千銘柄を月17万円で持つと1銘柄の売買は小さく上限に届かない。
    # 売って買い直す（年の実現率 T）ごとに売り・買いで 0.495%×2（ドルのまま＝為替の手数料は入れない＝軽い側）
    jp = {}
    for nm, g_, T in (('E1_cop_tilt', E1g, 0.11 * 2 * 0.4 + 0.04), ('E1m_cop_mega', E1mg, 0.04 * 2 * 0.4 + 0.04), ('E2_gate_P1', E2g, T2)):
        n_ = {k: v - T * 0.0099 / 12 for k, v in g_.items()}
        p_ = pack(n_, mkt, min(n_), jkp_last)
        jp[nm] = {'cost_per_year_pct': round(T * 0.99, 3), 'grade_vs_pure': p_['grade'], 'full': p_['full'], 'train': p_['train'], 'hold': p_['hold']}
        log('日本の手数料', nm, brief(p_))
    res['stress_jp_retail_commission_vs_pure'] = jp

    # ───── 多重検定
    progN = 0
    import glob
    for f in glob.glob(os.path.join(BASE, 'out', 'mw_*.json')):
        b_ = os.path.basename(f)
        if 'prereg' in b_ or 'verify' in b_:
            continue
        try:
            j = json.load(open(f))
            if isinstance(j.get('tested'), list):
                progN += len(j['tested'])
        except Exception:  # noqa
            pass
    res['multiple_testing'] = {'angle_tested_rows': len(claimed['tested']), 'angle_distinct_strategies': 13,
                               'angle_lump_grade_rows': len(CL), 'program_tested_rows_all_mw': progN,
                               'origin': {'E1': 'mega_tilt X3b の17本（λ_vw・探索の族）の中で保有期間 t が最大だったものを、この角度が E1 に選んだ',
                                          'E1m': 'mega_tilt X1_lamfeas（mega 34本の族の Holm は最良の cop_at でも 0.50・mega_tilt_verify）',
                                          'E2': 'gate_proxy P1（gate_proxy_verify で A へ格下げ・保有期間は登録前に H3 として既知）',
                                          'X2_E4': 'etf_tactical の探索の族 exploratory3（E4）＝角度全体で参照を除く76本・その角度の Holm 1.0。X2 はこの角度の主の族の結果を見た後の探索（事前登録2）'}}

    # ───── 判定
    V = []

    def cl(name):
        x = CL.get(name, {})
        return {'grade': x.get('grade'), 'full': (x.get('full') or {}).get('ex_ann'), 'full_t': (x.get('full') or {}).get('t'),
                'hold': (x.get('hold') or {}).get('ex_ann'), 'hold_t': (x.get('hold') or {}).get('t')}

    def pick(rec, key):
        p = rec[key]
        return {'grade': p['grade'], 'full': p['full'], 'train': p['train'], 'hold': p['hold'], 'net_hold': p['net_hold'], 'recent': p['recent'], 'roll20': p['roll20']}

    res['candidates'] = {}
    for base, rec in list(cands.items()) + list(fid.items()):
        for rg in ('R0_pretax', 'R1_nisa_unlimited'):
            key = 'R0' if rg == 'R0_pretax' else 'R1'
            nm = f'{base}__lump__{rg}'
            res['candidates'][nm] = {'claimed': cl(nm), 'reproduced_vs_fee_benchmark': pick(rec, f'{key}_vs_fee_net'),
                                     'vs_pure_benchmark': pick(rec, f'{key}_vs_pure_net')}
    res['cands_detail'] = {k: {kk: vv for kk, vv in v.items() if kk not in ('R0_vs_fee_net', 'R0_vs_pure_net', 'R1_vs_fee_net', 'R1_vs_pure_net')}
                           for k, v in list(cands.items()) + list(fid.items())}
    bon = {}
    for base, rec in list(cands.items()) + list(fid.items()):
        f = rec['R0_vs_pure_net']['full']
        pf = pval(f['t'])   # 丸める前の p（t から）
        bon[base] = {'full_t_vs_pure': f['t'], 'full_p': float(f'{pf:.3g}'), 'bonferroni_program': round(min(1.0, pf * progN), 4)}
    res['multiple_testing']['bonferroni_full_period_vs_pure'] = bon
    res['verdicts'] = build_verdicts(res)
    res['log'] = LOG
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('書いた', OUT)


if __name__ == '__main__':
    main()
