#!/usr/bin/env python3
"""night/mw_etf_tactical_verify.py — 角度 etf_tactical の『反証の検証』（読むだけ・門の判定には不使用）

研究側（night/mw_etf_tactical.py → out/mw_etf_tactical.json）が S/A と格付けした候補を、
**自分の実装**で作り直して反証を試みる。mw_common からは取得（ff_factors・french_series・yahoo・get）だけを借り、
ポートフォリオの組み方・超過・NW t・CAGR 差・転がる20年・積立・費用は全部ここで書く。

独立性
- 月次リターンは Yahoo の**日次**の調整後終値から自分で作る（研究側は Yahoo の月次の足を使った）。月末の値＝その月の最後の取引日。
- 1日遅れ・月中・任意の営業日の区切りは French 日次の暦で自分で作る。
- 順位・等分・ドリフト・売買量・費用も自前。

使い方: python3 night/mw_etf_tactical_verify.py   → out/mw_etf_tactical_verify.json
"""
import sys, os, io, csv, json, math, zipfile, datetime, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得だけに使う）

END = 202608
TRAIN_END, HOLD_START = 200612, 200701
C_SIDE, C_SIDE_STRESS = 0.0005, 0.0015
OUT = 'mw_etf_tactical_verify.json'
LOG = []

FSEL = ['FSPTX', 'FSENX', 'FIDSX', 'FSUTX', 'FSPHX', 'FSDAX', 'FDLSX', 'FSLBX', 'FSCHX', 'FDFAX', 'FSELX', 'FSTCX', 'FSCSX', 'FDCPX',
        'FSAGX', 'FBIOX', 'FSVLX', 'FSPCX', 'FSRPX', 'FSAVX', 'FSHCX', 'FBMPX', 'FSRBX', 'FSHOX', 'FSDPX', 'FSRFX', 'FSLEX', 'FSCPX',
        'FNARX', 'FBSOX', 'FSMEX', 'FWRLX', 'FPHAX']
DEAD = ['FSESX', 'FSNGX', 'FSAIX', 'FSDCX', 'FCYIX', 'FSCGX']
COMMOD = ['FSENX', 'FNARX', 'FSAGX', 'FSESX', 'FSNGX']          # エネルギー・天然資源・金鉱・エネルギーサービス・天然ガス
RYDEX = ['RYKIX', 'RYBIX', 'RYOIX', 'RYCIX', 'RYSIX', 'RYEIX', 'RYVIX', 'RYFIX', 'RYHIX', 'RYIIX', 'RYLIX', 'RYPMX', 'RYRIX',
         'RYTIX', 'RYMIX', 'RYPIX', 'RYUIX', 'RYHRX']
FR10 = ['NoDur', 'Durbl', 'Manuf', 'Enrgy', 'HiTec', 'Telcm', 'Shops', 'Hlth', 'Utils']


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def ymd(d):
    return d.year * 10000 + d.month * 100 + d.day


def todate(k):
    return datetime.date(k // 10000, k // 100 % 100, k % 100)


# ───────────────────────── 自前の統計 ─────────────────────────
def nwt(x, L=12):
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
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1 if xs else None


def pval(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def stats(s, b, a=None, z=None, drop=None):
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z) and not (drop and drop(k)))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nwt(ex)
    gs, gb = geo([s[k] for k in ks]), geo([b[k] for k in ks])
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(sum(ex) / len(ex) * 1200, 2), 't': round(t, 2) if t else None,
            'p': round(pval(t), 4) if t else None, 'cagr_diff': round((gs - gb) * 100, 2), 'cagr_s': round(gs * 100, 2), 'cagr_b': round(gb * 100, 2),
            'te': round(S.stdev(ex) * math.sqrt(12) * 100, 2)}


def roll20(s, b):
    ks = sorted(k for k in s if k in b)
    out = []
    for y in range(ks[0] // 100, 2100):
        a, z = y * 100 + 7, (y + 20) * 100 + 6
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < 233:
            continue
        out.append((y, round((geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100, 2)))
    if not out:
        return None
    v = [c for _, c in out]
    return {'windows': len(out), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3), 'median': sorted(v)[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'last': out[-1]}


def dca20(s, b):
    ks = sorted(k for k in s if k in b)
    out = []
    for i in range(0, len(ks) - 240 + 1, 12):
        w = ks[i:i + 240]
        vs = vb = 0.0
        for k in w:
            vs = (vs + 1) * (1 + s[k]); vb = (vb + 1) * (1 + b[k])
        out.append((w[0], vs / vb))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': round(v[len(v) // 2], 3),
            'worst': round(v[0], 3)}


def holm(p):
    it = sorted((v, k) for k, v in p.items() if v is not None)
    m, out, run = len(it), {}, 0.0
    for i, (v, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 4)
    return out


def grade(full, train, hold, r20, net_hold, repl_ok, holm_p):
    c = {'C1': bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2),
         'C2': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3': bool(hold and (hold['t'] or 0) >= 1.65),
         'C4': bool(r20 and r20['win_rate'] >= 0.8),
         'C5': repl_ok,
         'C6': bool(net_hold and net_hold['ex'] > 0 and net_hold['cagr_diff'] > 0),
         'C7': bool((full and (full['t'] or 0) >= 3) or (holm_p is not None and holm_p < 0.05))}
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── データ（自前で組む） ─────────────────────────
def yahoo_daily_levels(t):
    """Yahoo 日次の調整後終値 → {yyyymmdd: 水準}（取得は mw_common の fetcher、読み取りは自前）"""
    M.yahoo(t, interval='1d')                   # キャッシュを新しくする（戻り値は使わない）
    p = os.path.join(M.CACHE, f'yh_{t}_1d.json')
    r = json.load(open(p))['chart']['result'][0]
    adj = r['indicators']['adjclose'][0]['adjclose']
    out = {}
    for ts, a in zip(r['timestamp'], adj):
        if a is None or a <= 0:
            continue
        out[ymd(datetime.datetime.utcfromtimestamp(ts).date())] = a
    return out


def month_end_returns(lv, first_month=None):
    """日次水準 → 暦月の月次リターン（その月の最後の取引日どうし）。月の最後の観測が月末から7日より前なら欠測（0で埋めない）"""
    last = {}
    for d in sorted(lv):
        last[d // 100] = d
    out = {}
    for m in sorted(last):
        p = madd(m, -1)
        if p not in last:
            continue
        # 月末に近いこと（最後の観測が月末の7日前より後）
        dm = todate(last[m]); dp = todate(last[p])
        eom = (datetime.date(dm.year + (dm.month == 12), dm.month % 12 + 1, 1) - datetime.timedelta(days=1))
        eop = (datetime.date(dp.year + (dp.month == 12), dp.month % 12 + 1, 1) - datetime.timedelta(days=1))
        if (eom - dm).days > 7 or (eop - dp).days > 7:
            continue
        if first_month and m < first_month:
            continue
        if m > END:
            continue
        out[m] = lv[last[m]] / lv[last[p]] - 1
    return out


def contiguous_to_end(d):
    ks = sorted(d)
    start = ks[0]
    for a, b in zip(ks, ks[1:]):
        if madd(a, 1) != b:
            start = b
    return {k: v for k, v in d.items() if k >= start}


def av_dead(t):
    rows = sorted(csv.DictReader(open(os.path.join(M.CACHE, f'av_dead_select_{t}.csv'))), key=lambda r: r['date'])
    px = {int(r['date'][:4]) * 100 + int(r['date'][5:7]): float(r['adj']) for r in rows}
    ks = sorted(px)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k and k <= END}


def boundaries(days, k=None, n=None):
    """French 日次の暦 → 各月の区切りの日（k=月の k 営業日目・n=月の最後から n 番目の営業日）"""
    bym = {}
    for d in days:
        bym.setdefault(d // 100, []).append(d)
    out = {}
    for m, v in bym.items():
        if k is not None and len(v) >= k:
            out[m] = v[k - 1]
        if n is not None and len(v) >= n:
            out[m] = v[-n]
    return out


def interval_returns(lv, bnd, maxgap=5):
    """区切り bnd[m] → bnd[m+1] の区間リターン（ラベル m）。区切りの日に値が無ければ、5日以内の直前の値"""
    ks = sorted(lv)
    import bisect

    def level(d):
        i = bisect.bisect_right(ks, d) - 1
        if i < 0:
            return None
        if (todate(d) - todate(ks[i])).days > maxgap:
            return None
        return lv[ks[i]]
    out = {}
    first = ks[0]
    for m in sorted(bnd):
        m2 = madd(m, 1)
        if m2 not in bnd or bnd[m] <= first:
            continue
        a, b = level(bnd[m]), level(bnd[m2])
        if a and b:
            out[m] = b / a - 1
    return out


def bench_interval(daily, bnd):
    days = sorted(daily)
    pos = {d: i for i, d in enumerate(days)}
    out = {}
    for m in sorted(bnd):
        m2 = madd(m, 1)
        if m2 not in bnd:
            continue
        v = 1.0
        for d in days[pos[bnd[m]] + 1:pos[bnd[m2]] + 1]:
            v *= 1 + daily[d]
        out[m] = v - 1
    return out


# ───────────────────────── 自前のエンジン ─────────────────────────
def cum(r, t, k):
    v = 1.0
    for j in range(k):
        x = r.get(madd(t, -j))
        if x is None:
            return None
        v *= 1 + x
    return v - 1


SCORES = {
    'blend': lambda r, t: _avg([cum(r, t, k) for k in (1, 3, 6, 12)]),
    'r12': lambda r, t: cum(r, t, 12),
    'r6': lambda r, t: cum(r, t, 6),
    'r3': lambda r, t: cum(r, t, 3),
    'r1': lambda r, t: cum(r, t, 1),
    'blend_no_r1': lambda r, t: _avg([cum(r, t, k) for k in (3, 6, 12)]),
    'r12skip1': lambda r, t: (None if cum(r, t, 12) is None else (1 + cum(r, t, 12)) / (1 + r[t]) - 1),
    'w13612': lambda r, t: _w13612(r, t),
}


def _avg(p):
    return None if None in p else sum(p) / len(p)


def _w13612(r, t):
    p = [cum(r, t, k) for k in (1, 3, 6, 12)]
    return None if None in p else 12 * p[0] + 4 * p[1] + 2 * p[2] + p[3]


def run_momo(sig, K, score='blend', hold=None, universe=None, min_n=20, end=END, trade_day=None, need12=True):
    """t の終わりまでの sig（区間リターン）で順位を付け、上位 K を等分で t+1 に持つ。
    eligible = 直近12区間がそろい（need12）、かつ t+1 の保有リターンがある（＝翌区間も存在する）もの。
    trade_day: {t: 約定日 yyyymmdd}（短期解約手数料の日数計算用）。
    戻り値: dict(gross, net, stress, fee075, turnover, weights, roundtrips)"""
    hold = hold or sig
    names = [f for f in (universe or list(sig)) if f in sig and sig[f]]
    months = sorted(set().union(*[set(sig[f]) for f in names]))
    sc = SCORES[score]
    gross, net, stress, fee, turn, wts = {}, {}, {}, {}, {}, {}
    prev = None               # 値動き後の重み
    entry = {}                # 保有中ファンドの買い始めの約定日
    started = False
    rts = []                  # (約定日, ファンド, 保有日数) の往復
    for t in months:
        n1 = madd(t, 1)
        if n1 > end:
            break
        elig = []
        for f in names:
            if n1 not in hold.get(f, {}):
                continue
            if need12 and cum(sig[f], t, 12) is None:
                continue
            v = sc(sig[f], t)
            if v is None:
                continue
            elig.append((-v, names.index(f), f))
        if not started and len(elig) < min_n:
            continue
        if len(elig) < K:
            if started:
                raise RuntimeError(f'開始後に対象が {len(elig)} 本しかない: {t}')
            continue
        top = [f for _, _, f in sorted(elig)[:K]]
        w = {f: 1 / K for f in top}
        tr = 0.0
        fee_t = 0.0
        td = trade_day.get(t) if trade_day else None
        if started:
            for f in set(w) | set(prev):
                d = w.get(f, 0) - prev.get(f, 0)
                tr += abs(d)
                if d < -1e-12 and td and f in entry:
                    days = (todate(td) - todate(entry[f])).days
                    if days < 30:                     # FIFO: 買い始めから30日未満なら売りに 0.75%
                        fee_t += -d * 0.0075
                    if f not in w:
                        rts.append((td, f, days))
        started = True
        for f in list(entry):
            if f not in w:
                del entry[f]
        for f in w:
            if f not in entry and td:
                entry[f] = td
        rp = sum(w[f] * hold[f][n1] for f in w)
        gross[n1] = rp
        net[n1] = rp - C_SIDE * tr
        stress[n1] = rp - C_SIDE_STRESS * tr
        fee[n1] = rp - C_SIDE * tr - fee_t
        turn[n1] = tr
        wts[t] = w
        prev = {f: w[f] * (1 + hold[f][n1]) / (1 + rp) for f in w}
    return {'gross': gross, 'net': net, 'stress': stress, 'fee075': fee, 'turnover': turn, 'weights': wts, 'roundtrips': rts}


def full_eval(res, bench, drop_eras=True, repl=None, holm_p=None):
    g, n = res['gross'], res['net']
    full, train, hold = stats(g, bench), stats(g, bench, z=TRAIN_END), stats(g, bench, a=HOLD_START)
    net_hold = stats(n, bench, a=HOLD_START)
    r20 = roll20(n, bench)
    ks = sorted(g)
    halfk = [k for k in ks if k >= HOLD_START and k in bench]
    mid = halfk[len(halfk) // 2] if halfk else None
    out = {'start': ks[0], 'end': ks[-1], 'full': full, 'train': train, 'hold': hold, 'net_hold': net_hold,
           'stress030_hold': stats(res['stress'], bench, a=HOLD_START), 'fee075_short_hold': stats(res['fee075'], bench, a=HOLD_START),
           'roll20': r20, 'dca20': dca20(n, bench),
           'turnover_oneway_ann': round(S.mean(res['turnover'].values()) / 2 * 12, 2),
           'hold_first_half': stats(g, bench, a=HOLD_START, z=madd(mid, -1)) if mid else None,
           'hold_second_half': stats(g, bench, a=mid) if mid else None,
           'hold_2007_2016': stats(g, bench, a=200701, z=201612), 'hold_2017_on': stats(g, bench, a=201701)}
    if drop_eras:
        dr = lambda k: (199801 <= k <= 200012) or (202001 <= k <= 202112)
        out['drop_1998_2000_2020_2021'] = {'full': stats(g, bench, drop=dr), 'train': stats(g, bench, z=TRAIN_END, drop=dr),
                                           'hold': stats(g, bench, a=HOLD_START, drop=dr)}
    # 保有期間の年ごとの超過（純）と、上位3年を除いた超過
    yr = {}
    for k in sorted(n):
        if k in bench and k >= HOLD_START:
            a_, b_ = yr.get(k // 100, (1.0, 1.0))
            yr[k // 100] = (a_ * (1 + n[k]), b_ * (1 + bench[k]))
    ye = {y: round((a_ - b_) * 100, 1) for y, (a_, b_) in yr.items()}
    out['hold_yearly_excess_net'] = ye
    top3 = sorted(ye, key=lambda y: -ye[y])[:3]
    out['hold_without_best3_years'] = {'years_removed': top3, 'stats': stats(n, bench, a=HOLD_START, drop=lambda k: k // 100 in top3)}
    if repl is not None or True:
        gr, cr = grade(full, train, hold, r20, net_hold, repl, holm_p)
        out['grade_reproduced'], out['criteria'] = gr, cr
    return out


def contrib(res, hold, bench, a=HOLD_START):
    c, w_, n = {}, {}, 0
    for t, w in res['weights'].items():
        m = madd(t, 1)
        if m < a or m not in bench:
            continue
        n += 1
        for f, x in w.items():
            c[f] = c.get(f, 0) + x * (hold[f][m] - bench[m])
            w_[f] = w_.get(f, 0) + x
    return {f: {'w': round(w_[f] / n, 3), 'c': round(c[f] / n * 1200, 2)} for f in sorted(c, key=lambda z: -c[z])}


def short(st):
    if not st:
        return None
    return {k: st[k] for k in ('ex', 't', 'cagr_diff', 'n') if k in st}


# ───────────────────────── 本体 ─────────────────────────
def main():
    res = {'angle': 'etf_tactical', 'role': 'adversarial verifier（反証の検証）', 'generated': datetime.date.today().isoformat(),
           'researcher_files': ['night/mw_etf_tactical.py', 'out/mw_etf_tactical.json', 'out/mw_etf_tactical_prereg*.json'],
           'independence': '月次は Yahoo 日次の調整後終値から自前で作成（研究側は Yahoo 月次の足）。順位・等分・ドリフト・売買量・費用・超過・NW t（ラグ12）・CAGR・転がる20年・積立は自前。mw_common は取得だけ'}
    ff = M.ff_factors()
    mkt, rf = {k: v for k, v in ff['mkt'].items() if k <= END}, ff['rf']
    ffd = M.ff_factors('daily')
    mkd = ffd['mkt']
    days = sorted(d for d in mkd if d in ffd['rf'])
    lastbd = boundaries(days, n=1)

    # ── データ
    lv, R = {}, {}
    ym = {}
    for t in FSEL:
        lv[t] = yahoo_daily_levels(t)
        ym[t] = M.yahoo(t)                                   # 研究側の源（比較用）
        first = min(ym[t])                                   # 研究側と同じ始まり（Yahoo 月次の最初のリターンの月）
        R[t] = contiguous_to_end(month_end_returns(lv[t], first_month=first))
    # データの点検: 自前の月次（日次から）と Yahoo 月次の足
    dchk = {}
    for t in FSEL:
        ks = [k for k in R[t] if k in ym[t] and k <= END]
        diffs = [abs(R[t][k] - ym[t][k]) for k in ks]
        dchk[t] = {'months': len(ks), 'max_abs_diff_pct': round(max(diffs) * 100, 3), 'n_diff_gt_0.1pct': sum(1 for d in diffs if d > 0.001),
                   'first': min(R[t]), 'last': max(R[t])}
    res['data_check_daily_vs_monthly'] = dchk
    log('data check: max diff over funds (pct)', max(v['max_abs_diff_pct'] for v in dchk.values()),
        'funds with >0.1% months', sum(1 for v in dchk.values() if v['n_diff_gt_0.1pct']))
    # 死んだ6本（AV・研究側が手で写した CSV）の点検: 生きている近い業種との相関
    dead = {t: av_dead(t) for t in DEAD}
    kin = {'FSESX': 'FSENX', 'FSNGX': 'FSENX', 'FSAIX': 'FSRFX', 'FSDCX': 'FSTCX', 'FCYIX': 'FSDAX', 'FSCGX': 'FSDAX'}
    dd = {}
    for t, d in dead.items():
        ks = [k for k in d if k in R[kin[t]]]
        dd[t] = {'from': min(d), 'to': max(d), 'n': len(d), 'kin': kin[t],
                 'corr_with_kin': round(M.corr([d[k] for k in ks], [R[kin[t]][k] for k in ks]), 3),
                 'max_abs_month_pct': round(max(abs(v) for v in d.values()) * 100, 1)}
    res['dead_funds_check'] = {'note': 'Alpha Vantage の再取得は日次上限（25回）に当たり不能 → 同じ業種の生きたファンドとの相関で写し間違いの大きいものが無いかだけ確認', 'funds': dd}

    # ── 候補の再現（暦月）
    tdays = {t: lastbd.get(t) for t in range(198001, END + 1)}
    RD = dict(R)
    RD.update({'AV_' + t: d for t, d in dead.items()})
    fseld = FSEL + ['AV_' + t for t in DEAD]
    runs = {}
    runs['G3_FSEL_K3_BL'] = (run_momo(R, 3, 'blend', universe=FSEL, trade_day=tdays), R, mkt)
    runs['G4_FSEL_K6_BL'] = (run_momo(R, 6, 'blend', universe=FSEL, trade_day=tdays), R, mkt)
    runs['G1_FSEL_K3_R12'] = (run_momo(R, 3, 'r12', universe=FSEL, trade_day=tdays), R, mkt)
    runs['H3_FSELD_K3_BL'] = (run_momo(RD, 3, 'blend', universe=fseld, trade_day=tdays), RD, mkt)
    runs['H1_FSELD_K3_R12'] = (run_momo(RD, 3, 'r12', universe=fseld, trade_day=tdays), RD, mkt)
    # 1日遅れ（翌月最初の営業日の引け → その次の月の最初の営業日の引け）
    fbd = boundaries(days, k=1)
    Rh = {t: interval_returns(lv[t], fbd) for t in FSEL}
    mk_lag = bench_interval(mkd, fbd)
    tdl = {t: fbd.get(madd(t, 1)) for t in range(198001, END + 1)}
    runs['D3_FSEL_K3_BL_LAG1'] = (run_momo(R, 3, 'blend', hold=Rh, universe=FSEL, end=202607, trade_day=tdl), Rh, mk_lag)
    RhD = dict(Rh)
    RhD.update({'AV_' + t: d for t, d in dead.items()})
    runs['W3_FSELD_K3_BL_LAG1'] = (run_momo(RD, 3, 'blend', hold=RhD, universe=fseld, end=202607, trade_day=tdl), RhD, mk_lag)
    # French 10業種（紙の上）
    ind = M.french_series('10_Industry_Portfolios', 'Value Weight')
    F10 = {c: {k: v for k, v in ind[c].items() if k <= END} for c in FR10}
    runs['X3_SECT3BL_L'] = (run_momo(F10, 3, 'blend', min_n=9), F10, mkt)
    runs['X7_SECTK1_L'] = (run_momo(F10, 1, 'r12', min_n=9), F10, mkt)
    # French 30業種（紙の上・B の上位）
    i30 = M.french_series('30_Industry_Portfolios', 'Value Weight')
    F30 = {c.strip(): {k: v for k, v in i30[c].items() if k <= END} for c in i30 if c.strip().lower() != 'other'}
    g6 = run_momo(F30, 3, 'r12', min_n=29)
    a0 = min(runs['G1_FSEL_K3_R12'][0]['gross'])
    for key in ('gross', 'net', 'stress', 'fee075', 'turnover'):
        g6[key] = {k: v for k, v in g6[key].items() if k >= a0}
    g6['weights'] = {k: v for k, v in g6['weights'].items() if madd(k, 1) >= a0}
    runs['G6_FR30_K3_R12'] = (g6, F30, mkt)
    # 候補の一覧には無いが研究側の結果で A になっている行（『S か A の全部』を見るため）
    runs['G2_FSEL_K6_R12'] = (run_momo(R, 6, 'r12', universe=FSEL, trade_day=tdays), R, mkt)
    runs['H4_FSELD_K6_BL'] = (run_momo(RD, 6, 'blend', universe=fseld, trade_day=tdays), RD, mkt)
    runs['D4_FSEL_K6_BL_LAG1'] = (run_momo(R, 6, 'blend', hold=Rh, universe=FSEL, end=202607, trade_day=tdl), Rh, mk_lag)
    runs['W4_FSELD_K6_BL_LAG1'] = (run_momo(RD, 6, 'blend', hold=RhD, universe=fseld, end=202607, trade_day=tdl), RhD, mk_lag)
    runs['P5_SECT3_L'] = (run_momo(F10, 3, 'r12', min_n=9), F10, mkt)
    runs['X7_SECTK2_L'] = (run_momo(F10, 2, 'r12', min_n=9), F10, mkt)
    runs['X7_SECTK4_L'] = (run_momo(F10, 4, 'r12', min_n=9), F10, mkt)

    # Holm（研究側の族の中）: 研究側の p を使い、自分の候補の p だけ差し替えて再計算
    rj = json.load(open(os.path.join(M.BASE, 'out', 'mw_etf_tactical.json')))
    fam, allp = {}, {}
    for r in rj['tested']:
        if 'error' in r:
            continue
        p = (r.get('cost_hold') or {}).get('p')
        fam.setdefault(r['family'], {})[r['id']] = p
        if not r['family'].startswith('reference'):
            allp[r['id']] = p
    res['multiple_testing'] = {'n_rows_tested_by_researcher': len(rj['tested']), 'n_non_reference': len(allp),
                               'families': {f: len(v) for f, v in fam.items()}}

    # C5（研究側の JKP GICS 7か国）を自分で作り直す: 同じ規則を GICS 11 に（K=3→1・K=6→2）、国の vw 市場と比べる
    def gics(country):
        b = M.get(f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{country}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip',
                  name=f'jkp_industry_{country}_gics_vw_monthly.zip')
        z = zipfile.ZipFile(io.BytesIO(b))
        out = {}
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
            out.setdefault('G' + x['gics'], {})[m] = float(x['ret'])          # 超過のまま（市場も超過で比べる＝同じ基準）
        return out

    def repl(k, score, countries=('jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che'), a=None):
        pos, n, byc = 0, 0, {}
        for c in countries:
            G = gics(c)
            mk = M.jkp_mkt(c, 'vw')
            # その月に窓がそろったセクターから（k+1 本以上）
            months = sorted(set().union(*[set(v) for v in G.values()]))
            g = {}
            for t in months:
                n1 = madd(t, 1)
                el = []
                for s_, r in G.items():
                    if n1 not in r:
                        continue
                    v = SCORES[score](r, t) if cum(r, t, 12) is not None else None
                    if v is not None:
                        el.append((-v, s_))
                if len(el) < k + 1:
                    continue
                top = [s_ for _, s_ in sorted(el)[:k]]
                g[n1] = sum(G[s_][n1] for s_ in top) / k
            st = stats(g, mk, a=a)
            if st is None:
                byc[c] = None
                continue
            n += 1
            pos += st['ex'] > 0
            byc[c] = short(st)
        return {'regions': n, 'positive': pos, 'ok': (pos / n >= 2 / 3) if n else None, 'by_country': byc}

    rep_cache = {}
    def rep(k, score, a=None):
        key = (k, score, a)
        if key not in rep_cache:
            rep_cache[key] = repl(k, score, a=a)
        return rep_cache[key]
    repl_map = {'G3_FSEL_K3_BL': (1, 'blend'), 'G4_FSEL_K6_BL': (2, 'blend'), 'G1_FSEL_K3_R12': (1, 'r12'), 'H3_FSELD_K3_BL': (1, 'blend'),
                'H1_FSELD_K3_R12': (1, 'r12'), 'D3_FSEL_K3_BL_LAG1': (1, 'blend'), 'W3_FSELD_K3_BL_LAG1': (1, 'blend'),
                'X3_SECT3BL_L': (3, 'blend'), 'X7_SECTK1_L': (1, 'r12'), 'G6_FR30_K3_R12': (1, 'r12'),
                'G2_FSEL_K6_R12': (2, 'r12'), 'H4_FSELD_K6_BL': (2, 'blend'), 'D4_FSEL_K6_BL_LAG1': (2, 'blend'),
                'W4_FSELD_K6_BL_LAG1': (2, 'blend'), 'P5_SECT3_L': (3, 'r12'), 'X7_SECTK2_L': (2, 'r12'), 'X7_SECTK4_L': (4, 'r12')}
    # 米国の GICS 11（JKP・紙の上）でも同じ規則: 研究側の C5 は米国外だけを見ているので、米国の粗い区分でも効くかを見る
    usg = {}
    for (k, sc) in ((1, 'blend'), (2, 'blend'), (1, 'r12'), (3, 'blend')):
        usg[f'K{k}_{sc}'] = repl(k, sc, countries=('usa',))['by_country']['usa']
        usg[f'K{k}_{sc}_hold'] = repl(k, sc, countries=('usa',), a=HOLD_START)['by_country']['usa']
    res['us_jkp_gics_same_rule'] = usg

    cand = {}
    for rid, (r, H, bench) in runs.items():
        fam_id = next((f for f, v in fam.items() if rid in v), None)
        p_mine = (stats(r['net'], bench, a=HOLD_START) or {}).get('p')
        pf = dict(fam.get(fam_id, {}))
        pf[rid] = p_mine
        hp = holm(pf).get(rid)
        pa = dict(allp)
        pa[rid] = p_mine
        hp_all = holm(pa).get(rid)
        k_, sc_ = repl_map[rid]
        rp = rep(k_, sc_)
        rp_hold = rep(k_, sc_, a=HOLD_START)
        ev = full_eval(r, bench, repl=rp['ok'], holm_p=hp)
        ev['holm_p_in_researcher_family'] = {'family': fam_id, 'n': len(pf), 'p': hp}
        ev['holm_p_across_whole_angle'] = {'n': len(pa), 'p': hp_all}
        ev['bonferroni_p_across_whole_angle'] = round(min(1.0, (p_mine or 1) * len(pa)), 4)
        ev['repl_jkp_gics_full'] = rp
        ev['repl_jkp_gics_hold_2007on'] = rp_hold
        ev['hold_contrib_top8'] = dict(list(contrib(r, H, bench).items())[:8])
        cand[rid] = ev
        h, tr, fu = ev['hold'] or {}, ev['train'] or {}, ev['full'] or {}
        log(f"{rid:22s} {ev['start']}-{ev['end']} tr {tr.get('ex')} t{tr.get('t')} | ho {h.get('ex')} t{h.get('t')} cg {h.get('cagr_diff')} | "
            f"net {ev['net_hold']['ex']} | full {fu.get('ex')} t{fu.get('t')} | r20 {ev['roll20']['win_rate'] if ev['roll20'] else None} "
            f"| turn {ev['turnover_oneway_ann']} | grade {ev['grade_reproduced']} | holm_fam {hp} holm_all {hp_all}")
    res['candidates_reproduced'] = cand

    # ── 反証の試み1: 区切りの日（暦）をずらす（信号も保有も同じずらした月・生きている33本）
    off = {}
    for label, kw in [(f'k{k}', {'k': k}) for k in range(1, 16)] + [(f'n{n}', {'n': n}) for n in range(1, 6)]:
        bnd = boundaries(days, **kw)
        Ri = {t: interval_returns(lv[t], bnd) for t in FSEL}
        # 研究側と同じ始まりにそろえる（Yahoo 月次の最初の月より前は使わない）
        Ri = {t: {m: v for m, v in d.items() if m >= min(ym[t])} for t, d in Ri.items()}
        bi = bench_interval(mkd, bnd)
        row = {}
        for (K, sc) in ((3, 'blend'), (6, 'blend'), (3, 'r12'), (6, 'r12')):
            rr = run_momo(Ri, K, sc, universe=FSEL, end=202607)
            row[f'K{K}_{sc}'] = {'hold': short(stats(rr['gross'], bi, a=HOLD_START)), 'net_hold': short(stats(rr['net'], bi, a=HOLD_START)),
                                 'full': short(stats(rr['gross'], bi)), 'train': short(stats(rr['gross'], bi, z=TRAIN_END))}
        off[label] = row
        log('offset', label, {k: (v['hold'] or {}).get('ex') for k, v in row.items()}, {k: (v['hold'] or {}).get('t') for k, v in row.items()})
    summ = {}
    for key in ('K3_blend', 'K6_blend', 'K3_r12', 'K6_r12'):
        hx = [off[l][key]['hold']['ex'] for l in off if off[l][key]['hold']]
        ht = [off[l][key]['hold']['t'] for l in off if off[l][key]['hold']]
        fx = [off[l][key]['full']['t'] for l in off if off[l][key]['full']]
        ks_ = [l for l in off if l.startswith('k')]
        summ[key] = {'hold_ex_mean_all24': round(S.mean(hx), 2), 'hold_ex_min': min(hx), 'hold_ex_max': max(hx),
                     'hold_t_mean': round(S.mean(ht), 2), 'n_hold_t_ge_1.65': sum(1 for x in ht if x >= 1.65), 'n_offsets': len(ht),
                     'hold_ex_mean_k1_to_k15': round(S.mean(off[l][key]['hold']['ex'] for l in ks_), 2),
                     'full_t_mean': round(S.mean(fx), 2), 'n_full_t_ge_3': sum(1 for x in fx if x >= 3)}
    res['calendar_offsets'] = {'what': 'k=月の k 営業日目（1〜15・2001年9月は15営業日しか無いので16以上は作れない）の引け、n=月の最後から n 番目の営業日の引けで区切った『ずらした月』。信号（r1・r3・r6・r12）も保有も同じずらした月。相手は同じ区間の French 日次 Mkt。n1≒暦月（G 族）、k1≒D 族の保有区間（ただし D は信号が暦月）、k11=M 族',
                               'by_offset': off, 'summary': summ}

    # ── 反証の試み2: 近い規則（K と点の取り方の格子・暦月・生きている33本）
    grid = {}
    for K in (2, 3, 4, 5, 6):
        for sc in ('blend', 'r12', 'r6', 'r3', 'r1', 'blend_no_r1', 'r12skip1', 'w13612'):
            rr = run_momo(R, K, sc, universe=FSEL)
            grid[f'K{K}_{sc}'] = {'hold': short(stats(rr['gross'], mkt, a=HOLD_START)), 'net_hold': short(stats(rr['net'], mkt, a=HOLD_START)),
                                  'train': short(stats(rr['gross'], mkt, z=TRAIN_END)), 'full': short(stats(rr['gross'], mkt))}
    hx = sorted((v['hold']['ex'], k) for k, v in grid.items())
    res['neighbor_grid'] = {'what': 'K=2〜6 × 点の取り方8種（暦月・生きている33本・研究側の族に無いものを含む）', 'cells': grid,
                            'hold_ex_median': hx[len(hx) // 2][0], 'hold_ex_mean': round(S.mean(x for x, _ in hx), 2),
                            'share_hold_t_ge_1.65': round(sum(1 for v in grid.values() if (v['hold']['t'] or 0) >= 1.65) / len(grid), 3),
                            'rank_of_K3_blend': 1 + [k for _, k in sorted(hx, reverse=True)].index('K3_blend'), 'n_cells': len(grid),
                            'best': hx[-1], 'worst': hx[0]}
    log('grid hold ex median', res['neighbor_grid']['hold_ex_median'], 'mean', res['neighbor_grid']['hold_ex_mean'],
        'share t>=1.65', res['neighbor_grid']['share_hold_t_ge_1.65'], 'rank K3_blend', res['neighbor_grid']['rank_of_K3_blend'])

    # ── 反証の試み3: 1本ずつ抜く・商品系を抜く（G3・H3）
    loo = {}
    for base_id, U, RR in (('G3', FSEL, R), ('H3', fseld, RD)):
        vals = []
        for f in U:
            u2 = [x for x in U if x != f]
            rr = run_momo(RR, 3, 'blend', universe=u2)
            st = stats(rr['gross'], mkt, a=HOLD_START)
            vals.append((st['ex'], st['t'], f))
        vals.sort()
        u3 = [x for x in U if x.replace('AV_', '') not in COMMOD]
        rr = run_momo(RR, 3, 'blend', universe=u3, min_n=min(20, len(u3) - 5))
        loo[base_id] = {'leave_one_out_min': vals[0], 'leave_one_out_max': vals[-1], 'n_t_ge_1.65': sum(1 for v in vals if v[1] >= 1.65),
                        'n': len(vals), 'without_commodity_funds': {'removed': COMMOD, 'hold': short(stats(rr['gross'], mkt, a=HOLD_START)),
                                                                     'full': short(stats(rr['gross'], mkt)), 'train': short(stats(rr['gross'], mkt, z=TRAIN_END))}}
        log('LOO', base_id, loo[base_id]['leave_one_out_min'], 'no-commod', loo[base_id]['without_commodity_funds']['hold'])
    res['leave_out'] = loo

    # ── 反証の試み4: 独立の実在ファンド群（Rydex の業種ファンド18本・1998〜・短期売買を想定した設計で解約手数料なし）
    RY = {}
    for t in RYDEX:
        try:
            RY[t] = contiguous_to_end(month_end_returns(yahoo_daily_levels(t)))
        except Exception as e:  # noqa
            log('rydex fail', t, str(e)[:80])
    ry = {}
    for (K, sc) in ((2, 'blend'), (3, 'blend'), (4, 'blend'), (2, 'r12'), (3, 'r12'), (4, 'r12')):
        rr = run_momo(RY, K, sc, min_n=15)
        ry[f'K{K}_{sc}'] = {'start': min(rr['gross']), 'hold': short(stats(rr['gross'], mkt, a=HOLD_START)),
                            'net_hold': short(stats(rr['net'], mkt, a=HOLD_START)),
                            'train_1999_2006': short(stats(rr['gross'], mkt, z=TRAIN_END)),
                            'hold_2007_2016': short(stats(rr['gross'], mkt, a=200701, z=201612)), 'hold_2017_on': short(stats(rr['gross'], mkt, a=201701))}
    ew = {}
    ks_ = sorted(set().union(*[set(v) for v in RY.values()]))
    for k in ks_:
        xs = [RY[t][k] for t in RY if k in RY[t]]
        if len(xs) >= 15:
            ew[k] = sum(xs) / len(xs)
    ry['EW_all'] = {'hold': short(stats(ew, mkt, a=HOLD_START))}
    res['rydex_replication'] = {'funds': {t: [min(v), max(v)] for t, v in RY.items()}, 'results': ry,
                                'note': 'Rydex の業種ファンドは頻繁な売買を前提に作られ短期の解約手数料が無い（信託報酬は約1.6%と重い＝戦略に不利な側）。研究側は見ていない独立の実物の群。生き残りの偏りあり'}
    log('rydex', {k: (v.get('hold') or {}).get('ex') for k, v in ry.items()}, {k: (v.get('hold') or {}).get('t') for k, v in ry.items()})

    # ── 反証の試み5: 紙の上の細かい業種（CRSP・生き残りの偏りなし）で同じ (r1+r3+r6+r12)/4
    fp = {}
    i49 = M.french_series('49_Industry_Portfolios', 'Value Weight')
    F49 = {c.strip(): {k: v for k, v in i49[c].items() if k <= END} for c in i49 if c.strip().lower() != 'other'}
    for nm, FF, Ks in (('FR30', F30, (3, 6)), ('FR49', F49, (5, 10))):
        for K in Ks:
            for sc in ('blend', 'r12'):
                rr = run_momo(FF, K, sc, min_n=len(FF) - 5)
                fp[f'{nm}_K{K}_{sc}'] = {'hold': short(stats(rr['gross'], mkt, a=HOLD_START)), 'net_hold': short(stats(rr['net'], mkt, a=HOLD_START)),
                                         'full': short(stats(rr['gross'], mkt)), 'from_1987_07_train': short(stats(rr['gross'], mkt, a=198707, z=TRAIN_END)),
                                         'turnover': round(S.mean(rr['turnover'].values()) / 2 * 12, 2)}
    res['paper_fine_industries'] = fp
    log('paper fine', {k: (v['hold'] or {}).get('ex') for k, v in fp.items()}, {k: (v['hold'] or {}).get('t') for k, v in fp.items()})

    # ── 反証の試み6: French 10業種（X3・X7）の耐久財（Tesla を含む）抜き・近い K
    xs = {}
    names8 = [c for c in FR10 if c != 'Durbl']
    for (K, sc, lab) in ((3, 'blend', 'X3'), (1, 'r12', 'X7K1')):
        rr = run_momo(F10, K, sc, universe=names8, min_n=8)
        xs[f'{lab}_without_Durbl'] = {'hold': short(stats(rr['gross'], mkt, a=HOLD_START)), 'full': short(stats(rr['gross'], mkt))}
    for K in (1, 2, 3, 4):
        for sc in ('blend', 'r12', 'r6', 'r3', 'r1'):
            rr = run_momo(F10, K, sc, min_n=9)
            xs[f'K{K}_{sc}'] = {'hold': short(stats(rr['gross'], mkt, a=HOLD_START)), 'full': short(stats(rr['gross'], mkt)),
                                'train': short(stats(rr['gross'], mkt, z=TRAIN_END))}
    res['french10_checks'] = xs
    log('F10', {k: (v['hold'] or {}).get('ex') for k, v in xs.items()})
    # French 10業種の日次で、区切りの日をずらしても X3・X7・P5 が残るか
    f10d = M.french_series('10_Industry_Portfolios_daily', 'Value Weight', freq='daily')
    f10lv = {}
    for c in FR10:
        L, lvc = 1.0, {}
        for d in sorted(f10d[c]):
            L *= 1 + f10d[c][d]
            lvc[d] = L
        f10lv[c] = lvc
    offx = {}
    for label, kw in [(f'k{k}', {'k': k}) for k in range(1, 16)] + [(f'n{n}', {'n': n}) for n in range(1, 6)]:
        bnd = boundaries(days, **kw)
        Fi = {c: interval_returns(f10lv[c], bnd) for c in FR10}
        bi = bench_interval(mkd, bnd)
        row = {}
        for (K, sc, lab) in ((3, 'blend', 'X3'), (1, 'r12', 'X7K1'), (3, 'r12', 'P5'), (2, 'r12', 'X7K2')):
            rr = run_momo(Fi, K, sc, min_n=9, end=202607)
            row[lab] = {'hold': short(stats(rr['gross'], bi, a=HOLD_START)), 'full': short(stats(rr['gross'], bi)),
                        'train': short(stats(rr['gross'], bi, z=TRAIN_END))}
        offx[label] = row
    sx = {}
    for lab in ('X3', 'X7K1', 'P5', 'X7K2'):
        hx = [offx[l][lab]['hold']['ex'] for l in offx]
        ht = [offx[l][lab]['hold']['t'] for l in offx]
        sx[lab] = {'hold_ex_mean': round(S.mean(hx), 2), 'hold_ex_min': min(hx), 'hold_ex_max': max(hx), 'hold_t_mean': round(S.mean(ht), 2),
                   'n_hold_t_ge_1.65': sum(1 for x in ht if x >= 1.65), 'n_offsets': len(ht),
                   'full_t_mean': round(S.mean(offx[l][lab]['full']['t'] for l in offx), 2)}
    res['french10_calendar_offsets'] = {'by_offset': offx, 'summary': sx}
    log('F10 offsets', sx)

    # ── 反証の試み7: 実行の現実（Fidelity の往復の頻度）
    rt = {}
    for rid in ('G3_FSEL_K3_BL', 'D3_FSEL_K3_BL_LAG1', 'H3_FSELD_K3_BL', 'W3_FSELD_K3_BL_LAG1', 'G4_FSEL_K6_BL', 'G1_FSEL_K3_R12'):
        r = runs[rid][0]
        trips = r['roundtrips']
        hold_trips = [x for x in trips if x[0] >= 20070101]
        yrs = (len([k for k in r['gross'] if k >= HOLD_START])) / 12
        # 同じファンドで 90 日以内に 30日以内の往復が2回（Fidelity の過剰売買の目安）
        by_f = {}
        for d, f, dd_ in trips:
            if dd_ <= 30:
                by_f.setdefault(f, []).append(d)
        viol = 0
        for f, ds in by_f.items():
            ds.sort()
            for a_, b_ in zip(ds, ds[1:]):
                if (todate(b_) - todate(a_)).days <= 90:
                    viol += 1
        rt[rid] = {'exits_per_year_hold': round(len(hold_trips) / yrs, 2),
                   'share_exits_within_30d': round(sum(1 for x in trips if x[2] < 30) / len(trips), 3) if trips else None,
                   'share_exits_within_31d': round(sum(1 for x in trips if x[2] <= 31) / len(trips), 3) if trips else None,
                   'two_short_roundtrips_same_fund_within_90d': viol}
    res['execution_realism'] = rt

    # ── 判定（自分の数字で）
    verdicts = build_verdicts(res)
    res['adjudication_rules'] = ADJUDICATION_RULES
    res['verdicts'] = verdicts
    res['summary_ja'] = SUMMARY_JA
    res['log'] = LOG
    p = os.path.join(M.BASE, 'out', OUT)
    json.dump(res, open(p, 'w'), ensure_ascii=False, indent=1)
    print('saved', p, os.path.getsize(p))


def build_verdicts(res):
    """数字から機械的に作る材料（最終の言葉は手で書き足す: VERDICT_TEXT）"""
    out = {}
    for rid, ev in res['candidates_reproduced'].items():
        out[rid] = {'grade_reproduced_mechanical': ev['grade_reproduced'], 'criteria': ev['criteria'],
                    'hold': short(ev['hold']), 'train': short(ev['train']), 'full': short(ev['full']), 'net_hold': short(ev['net_hold']),
                    'fee075_short_hold': short(ev['fee075_short_hold']), 'roll20_win': (ev['roll20'] or {}).get('win_rate'),
                    'dca20_median': (ev['dca20'] or {}).get('median'), 'drop_eras': {k: short(v) for k, v in ev['drop_1998_2000_2020_2021'].items()},
                    'holm_family': ev['holm_p_in_researcher_family'], 'holm_whole_angle': ev['holm_p_across_whole_angle'],
                    'repl_full': (ev['repl_jkp_gics_full']['positive'], ev['repl_jkp_gics_full']['regions']),
                    'repl_hold': (ev['repl_jkp_gics_hold_2007on']['positive'], ev['repl_jkp_gics_hold_2007on']['regions'])}
        if rid in VERDICT_TEXT:
            out[rid].update(VERDICT_TEXT[rid])
    return out


# ───────────────────────── 判定の言葉（数字を見た後に書いた・下の規則で機械的に当てた） ─────────────────────────
ADJUDICATION_RULES = [
    'R1: 研究側と同じ線（out/mw_prereg.json の C1〜C7）を自前の数字で機械的に当て直す（全候補で研究側の数字と一致＝再現は成功）',
    'R2: 基準は「その実装の一点」ではなく近傍でも成り立つこと。C3（保有 t≥1.65）と C7（全期間 t≥3 か Holm<0.05）は、'
    '入れ替えの日を月の1〜15営業日目と月末から1〜5営業日目の20通りにずらした平均でも成り立つときだけ合格とする（月末という一点の当たりを除く）',
    'R3: 生き残りの偏りを直した版（死んだ Select 6本を入れた H・W 族）がある規則は、そちらの数字で裁く（G・D 族は H・W 族に置き換わる）',
    'R4: C5 は研究側の定義（JKP GICS・7か国・1999-07〜2025-12）に加え、保有期間（2007〜）だけでも 2/3 以上の国で正であること（主張は保有期間の勝ち）',
    'R5: C2 は、保有期間の勝ちが一つの業種（寄与1位）か 1998-2000・2020-2021 を除いたときにも正であること',
]

_FSEL_COMMON = ('共通の弱点: (i) 20通りの入れ替え日の平均は K3・(r1+r3+r6+r12)/4 で保有 +3.77%/年・t 平均 1.55（t≥1.65 は 20 中 9）、全期間 t≥3 は 20 中 4 だけ＝月末（と翌月1日目）は分布の上の端 '
                '(ii) 研究側の族の Holm は 0.13〜0.92、角度全体（参照を除く76本）の Holm・Bonferroni は 1.0 '
                '(iii) 保有期間の勝ちは 2020・2022・2025 の3年（テック・エネルギー・金鉱）に集中し、上位3年を除くと −1.0〜+1.5%/年 '
                '(iv) 独立の実在ファンド群 Rydex 業種18本（1998〜・短期手数料なし）では同じ規則が保有期間 −1.05%/年（K3）〜+0.44（K4）、12か月版でも +1.1〜+1.9（t≤0.65）で再現しない。'
                'CRSP の細かい業種（French 30/49・紙の上・生き残りの偏りなし）でも保有 +2.1〜+3.4%/年だが t 0.77〜1.39、米国 JKP GICS 11 の同じ規則は保有 −0.13〜+1.21（t≤0.51） '
                '(v) 訓練期間（1987〜2006）は生き残りだけ＋1999年（+72%）頼み: K3・(r1+r3+r6+r12)/4 の版は 1998-2000 と 2020-21 を除くと全期間 t 2.7〜2.9・訓練 t 1.8〜1.9 '
                '(vi) 日本の居住者は Fidelity Select（米国籍投信）を買えない。'
                '一方で K3・(r1+r3+r6+r12)/4 の保有期間の符号は頑丈: 20通りの入れ替え日すべて・33通りの1本抜きすべて・前半後半・費用のどの版でも正。')

VERDICT_TEXT = {
    'G3_FSEL_K3_BL': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                      'reasons': ['再現: 訓練 +9.08 t2.44・保有 +5.61 t2.43（CAGR 差 +5.70）・費用後 +5.17・全期間 t3.34・20年窓 20/20・積立中央 2.20＝機械的には S',
                                  '生き残りの偏りあり（今あるファンドだけ）。死んだ6本を足すだけで保有 +4.39 に落ちる（H3）→ R3 で H3 に置き換わる',
                                  'R2: 入れ替え日を20通りにずらすと保有 平均 +3.77（最小 +1.98・最大 +5.77）・t 平均 1.55・全期間 t 平均 2.78 → C3・C7 が落ちる',
                                  '近傍の格子（K2〜6 × 点8種＝40）で 3位、中央 +3.53、t≥1.65 は 47.5%', _FSEL_COMMON]},
    'D3_FSEL_K3_BL_LAG1': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                           'reasons': ['再現: 保有 +5.05 t2.35・費用後 +4.60・全期間 t3.29・Holm（族4本）0.13',
                                       '1日遅れ（翌月1営業日目）は20通りの入れ替え日の中で最も良い側（k1 = +5.77）に当たる',
                                       '生き残りの偏りを直していない（死んだ6本を入れた W3 は +4.45 t1.95）',
                                       '保有期間の前半 +6.71（t2.67）→ 後半 +3.40（t0.95）', _FSEL_COMMON]},
    'W3_FSELD_K3_BL_LAG1': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                            'reasons': ['再現: 保有 +4.45 t1.95・費用後 +3.98 t1.74・全期間 t3.15（死んだ6本は暦月で近似・AV から手で写した値＝AV の日次上限で再取得できず、同業種の生きたファンドとの相関 0.78〜0.97 で大きな写し間違いは無いことだけ確認）',
                                        '後半が弱い: 前半 +6.79（t2.91）→ 後半 +2.12（t0.53）、2017〜 +3.26（t0.87）',
                                        '1998-2000・2020-21 を除くと全期間 t 2.66 → C7 は全期間 t でしか通っておらず（族 Holm 0.33）ここで落ちる',
                                        '30日未満の保有の売りに 0.75%（FIFO）で保有 +3.54 t1.55（C3 割れ）。上位3年を除くと +0.33',
                                        'R2 の暦の平均（生きている版で月末比 ×0.68）を当てると保有 ≈+3%/年・t≈1.3', _FSEL_COMMON]},
    'H3_FSELD_K3_BL': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                       'reasons': ['再現: 保有 +4.39 t1.89・費用後 +3.92 t1.69・全期間 t3.15・族 Holm 0.37',
                                   '1本抜きの最悪（FSPTX）で +3.36 t1.38、商品系5本（FSENX FNARX FSAGX FSESX FSNGX）を抜くと +2.95 t1.48',
                                   '30日未満の売りに 0.75%（FIFO）で +3.48 t1.49。後半 +3.49 t0.86。上位3年を除くと +0.01',
                                   '1998-2000・2020-21 を除くと全期間 t 2.73（C7 割れ）。1999年以前に消えたファンド・AV に無い FNINX/FDPMX/FSPFX は直っていない',
                                   _FSEL_COMMON]},
    'X3_SECT3BL_L': {'verdict': 'downgraded to A', 'verified_grade': 'A', 'reproduced': True,
                     'reasons': ['再現: 訓練 +3.61 t4.46・保有 +3.89 t1.85・費用後 +3.59・全期間 t4.75（1927〜・CRSP＝生き残りの偏りなし）',
                                 'R2: French 10業種の日次で入れ替え日を20通りにずらすと保有 平均 +2.03（最小 −0.03）・t 平均 0.93・t≥1.65 は 1/20 → C3 は月末の一点の当たり',
                                 '耐久財（Tesla を含む）を抜くと保有 +1.59 t0.86、上位3年（2020・2022・2008）を除くと −0.27。近傍 K4 は +0.90、K3 の r12 +2.53 t1.10',
                                 'C7（全期間 t 平均 4.34）と C5（米国外7か国で全期間 7/7・保有期間 6/7）は頑丈 → 定義上 A は残る',
                                 'ただし紙の上だけ: 同じ規則を買える SPDR 9本で回すと保有 −1.01%/年（研究側）・Rydex でも再現せず・米国 JKP GICS 11 の上位3は保有 +0.64（t0.40）＝分類（SIC の Durbl）に依存。買える形の勝ちではない']},
    'G4_FSEL_K6_BL': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                      'reasons': ['再現: 保有 +3.39 t1.86・費用後 +2.99 t1.63・全期間 t3.46',
                                  'R2: 入れ替え日20通りで保有 平均 +1.97（最小 +0.63）・t 平均 1.09・全期間 t 平均 2.82 → C3・C7 が落ちる',
                                  'R3: 死んだ6本を入れた H4 は保有 +2.87 t1.52（C3 割れ）・30日未満の売りに 0.75% で +2.08 t1.08',
                                  '後半 +2.45 t0.89、上位3年を除くと +0.88', _FSEL_COMMON]},
    'X7_SECTK1_L': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                    'reasons': ['再現: 保有 +6.69 t1.14（CAGR 差 +5.41）・全期間 t3.95。機械的には A（C3 は落ち、C5 の全期間 6/7 で A）',
                                'R4: C5 を保有期間だけで見ると 4/7（2/3 未満）→ A の条件（C3 か C5）が両方落ちる',
                                'R5: 耐久財（Tesla）を抜くと保有 +1.22 t0.29（CAGR 差 +0.69）、上位3年（2020 +154%・2022 +84%・2010）を除くと −4.57。1998-2000・2020-21 を除くと CAGR 差 +0.51',
                                '入れ替え日20通りで保有 平均 +5.76・t 平均 1.08（t≥1.65 は 0/20）。常に1業種100%＝追従のぶれが極端',
                                '実物（SPDR/Fidelity 9本）では 2007〜 −2.2%/年（研究側）']},
    'G1_FSEL_K3_R12': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                       'reasons': ['再現: 保有 +3.60 t1.24・全期間 t3.01（線ちょうど）・C5 全期間 6/7（保有期間だけなら 4/7）',
                                   'R3: 死んだ6本を入れた H1 は全期間 t2.99 で C7 割れ＝研究側も B',
                                   'R2: 入れ替え日20通りで保有 平均 +3.07・t 平均 1.10、全期間 t≥3 は 2/20',
                                   '保有期間の前半 +0.02（2007-2016 は −1.03）・後半 +7.18、上位3年を除くと −0.96', _FSEL_COMMON]},
    'G6_FR30_K3_R12': {'verdict': 'confirmed', 'verified_grade': 'B', 'reproduced': True,
                       'reasons': ['再現: 保有 +3.79 t0.87（CAGR 差 +2.60）・費用後 +3.45・全期間（1987〜の同じ窓）t2.05 → B',
                                   '弱い B: 前半 +0.85（CAGR 差 −0.08）、上位3年（2022 +73%・2020・2007）を除くと −3.14、1998-2000・2020-21 を除くと CAGR 差 +0.27。C5 保有期間 4/7']},
    'H1_FSELD_K3_R12': {'verdict': 'confirmed', 'verified_grade': 'B', 'reproduced': True,
                        'reasons': ['再現: 保有 +3.06 t1.02・費用後 +2.71・全期間 t2.99 → B',
                                    '弱い B: 前半 −0.07（2007-2016 −1.08）・後半 +6.20、上位3年を除くと −1.58']},
    # 候補一覧には無いが研究側の結果で A だった行
    'G2_FSEL_K6_R12': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                       'reasons': ['再現: 保有 +2.74 t1.40・全期間 t3.02（線ちょうど）', 'R2: 入れ替え日20通りで全期間 t 平均 2.88・保有 t 平均 1.20（0/20 が t≥1.65）→ C7 落ち',
                                   '生き残りを直した H2 は研究側も B。上位3年を除くと −0.19']},
    'H4_FSELD_K6_BL': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                       'reasons': ['再現: 保有 +2.87 t1.52・全期間 t3.27', 'R2: 生きている版の暦の平均で全期間 t 2.82 → C7 は月末の一点頼み。1998-2000・2020-21 を除くと全期間 t 2.88',
                                   '30日未満の売りに 0.75% で +2.08 t1.08、後半 +1.66 t0.59、上位3年を除くと +0.02']},
    'D4_FSEL_K6_BL_LAG1': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                           'reasons': ['再現: 保有 +2.49 t1.44・全期間 t3.15', '生き残りの偏りあり（W4 は +2.28）。後半 +0.82 t0.30、1998-2000・2020-21 を除くと全期間 t2.65']},
    'W4_FSELD_K6_BL_LAG1': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                            'reasons': ['再現: 保有 +2.28 t1.26・全期間 t3.12', '後半 +0.23 t0.08、30日未満の売りに 0.75% で +1.38 t0.75、1998-2000・2020-21 を除くと全期間 t2.66、上位3年を除くと −0.42']},
    'P5_SECT3_L': {'verdict': 'confirmed', 'verified_grade': 'A', 'reproduced': True,
                   'reasons': ['再現: 保有 +2.53 t1.10・全期間 t4.94（1927〜）・C5 全期間 7/7・保有期間 7/7',
                               '入れ替え日20通りすべてで保有が正（最小 +1.02・平均 +1.96・t 平均 0.91）、全期間 t 平均 4.71 → A の条件（C5 経由）は近傍でも成り立つ',
                               'ただし弱い: 1998-2000・2020-21 を除くと保有 +0.91、上位3年を除くと −1.68。紙の上だけで、買える SPDR 版は保有 −0.2%/年（C）']},
    'X7_SECTK2_L': {'verdict': 'downgraded to B', 'verified_grade': 'B', 'reproduced': True,
                    'reasons': ['再現: 保有 +2.29 t0.66・全期間 t4.50・C5 7/7', 'R5: 1998-2000・2020-21 を除くと保有 −0.49（CAGR 差 −0.88）＝保有期間の勝ちは 2020-21 だけ。上位3年を除くと −3.70']},
    'X7_SECTK4_L': {'verdict': 'confirmed', 'verified_grade': 'A', 'reproduced': True,
                    'reasons': ['再現: 保有 +1.58 t0.92・全期間 t4.90・C5 全期間 7/7・保有期間 7/7',
                                '弱い: 後半 +0.32 t0.10、1998-2000・2020-21 を除くと +0.42、上位3年を除くと −1.02。紙の上だけ（買える SPDR 版は研究側で C）']},
}

SUMMARY_JA = [
    '研究側の数字は自前の実装（Yahoo 日次から作った月次・自前の順位と費用・NW t）で全候補とも小数第2位まで一致した。データの誤り・後知恵・相手（純粋な時価加重の French Mkt）の取り違えは見つからなかった',
    'しかし S の6本はどれも S に耐えなかった。Fidelity Select の業種の勢いは、入れ替えの日を月の中で20通りにずらすと保有期間の上乗せが平均 +3.8%/年・t 1.55 に下がり、S を支えた「全期間 t≥3」も20通り中4通りでしか成り立たない（月末は分布の上の端）',
    '勝ちは 2020・2022・2025 の3年（テック・エネルギー・金鉱）に集中し、その3年を除くとほぼ0。死んだファンドを入れると 5.6→4.4%/年、角度全体の多重検定（76本）では有意でない',
    '独立の実在ファンド群（Rydex の業種ファンド18本・1998〜）で同じ規則を回すと 2007年以降 −1.1〜+0.4%/年で再現しない。CRSP の細かい業種（紙の上）でも +2〜+3%/年・t≤1.4',
    'それでも保有期間の符号はどの日・どの1本抜き・どの費用でも正＝「弱い勝ち（B）」までは確認できた。Fidelity 系の S/A はすべて B へ格下げ',
    'French 10業種（紙の上）の X3 は A へ格下げ（C3 は月末の一点頼みだが、100年の全期間と米国外の再現は頑丈）。X7（上位1業種）は Tesla と2年頼みで B。どちらも買える ETF では負ける',
    '結論: この角度で「市場に勝てる」と言える頑丈な規則（S）は残らなかった。日本の個人が実行できる形（楽天の ETF）は研究側でも C',
]


if __name__ == '__main__':
    main()
