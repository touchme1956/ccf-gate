#!/usr/bin/env python3
"""night/mw_options_vrp_verify.py — mw 角度『options_vrp』の反証の検証（独立の実装・読むだけ・門の判定には不使用）

研究側（night/mw_options_vrp.py → out/mw_options_vrp.json）の数字を、自前のコードで作り直して反証を試みる。
共有するのは mw_common.get / yahoo（取得とキャッシュだけ）。CSV・JSON・xls の読み込み、月末の切り方、
S&P500 配当込みの月次、VRP、持ち高、超過・NW t・CAGR 差・20年窓・シャープの差の検定・格付けは全部ここで書き直した。

対象（out/mw_options_vrp.json に S/A は1本・B は0本）:
  1. O-RXM[vs French Mkt]（頑健性の行・S）
  2. O-RXM（主の族 A・C・C8 だけ不合格）
  3. F4-med1/1.5（探索の族 F・C・C1 だけ不合格＝線の最も近く）
  4. O-VPD（保有期間の超過が最大 +10.9%/年・報告のみ・C）

使い方: python3 night/mw_options_vrp_verify.py → out/mw_options_vrp_verify.json
"""
import sys, os, json, math, statistics as S, datetime, random, zipfile, io, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  取得（get / yahoo のキャッシュ）だけに使う

END, TE, HS, RS = 202608, 200612, 200701, 201307
OUT = os.path.join(M.BASE, 'out', 'mw_options_vrp_verify.json')
CBOE = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'
ND = S.NormalDist()


# ───────────────────────── 読み込み（自前） ─────────────────────────
def ym_add(m, n):
    y, mm = divmod(m // 100 * 12 + m % 100 - 1 + n, 12)
    return y * 100 + mm + 1


def cboe_close(sym):
    txt = M.get(CBOE.format(sym), name=f'cboe_{sym}_History.csv', max_age_days=30).decode('latin-1').splitlines()
    hdr = [h.strip().upper() for h in txt[0].split(',')]
    col = hdr.index('CLOSE') if 'CLOSE' in hdr else len(hdr) - 1
    out = {}
    for ln in txt[1:]:
        c = ln.split(',')
        try:
            m_, d_, y_ = (int(x) for x in c[0].split('/'))
            v = float(c[col])
        except (ValueError, IndexError):
            continue
        if v > 0:
            out[y_ * 10000 + m_ * 100 + d_] = v
    return out


def fred_d(sid, name):
    txt = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=name, max_age_days=30).decode().splitlines()
    out = {}
    for ln in txt[1:]:
        a, b = ln.split(',')
        if b.strip() in ('', '.'):
            continue
        out[int(a.replace('-', ''))] = float(b)
    return out


def fred_m_rate(sid):
    """年率% → 月次の小数（/12）"""
    d = fred_d(sid, f'fred_{sid}.csv')
    return {k // 100: v / 100 / 12 for k, v in d.items()}


def yahoo_daily(t):
    """Yahoo 日次（調整後終値）を取引所の現地の日付で"""
    p = os.path.join(M.CACHE, f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1d.json')
    if not os.path.exists(p):
        M.yahoo(t, '1d')
    r = json.load(open(p))['chart']['result'][0]
    off = (r.get('meta') or {}).get('gmtoffset') or 0
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    out = {}
    for ts, a in zip(r['timestamp'], adj):
        if a is None or a <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(ts + off)
        out[d.year * 10000 + d.month * 100 + d.day] = a
    return out


def stoxx(sym):
    txt = M.get(f'https://www.stoxx.com/document/Indices/Current/HistoricalData/h_{sym.lower()}.txt', name=f'stoxx_h_{sym.lower()}.txt',
                max_age_days=30).decode('latin-1').splitlines()
    out = {}
    for ln in txt[1:]:
        c = ln.split(';')
        try:
            d_, m_, y_ = (int(x) for x in c[0].split('.'))
            v = float(c[2])
        except (ValueError, IndexError):
            continue
        if v > 0:
            out[y_ * 10000 + m_ * 100 + d_] = v
    return out


def french_ff3():
    b = M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip', name='fr_F-F_Research_Data_Factors.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    mkt, rf = {}, {}
    for ln in z.read(z.namelist()[0]).decode('latin-1').splitlines():
        c = [x.strip() for x in ln.split(',')]
        if len(c) >= 5 and c[0].isdigit() and len(c[0]) == 6:
            k = int(c[0])
            if k in mkt:  # 月次表だけ（年次表は4桁なので入らない）
                continue
            mkt[k] = (float(c[1]) + float(c[4])) / 100
            rf[k] = float(c[4]) / 100
    return mkt, rf


def shiller_D():
    import xlrd
    b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', name='shiller_ie_data.xls', max_age_days=3650)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    D = {}
    for i in range(sh.nrows):
        row = sh.row_values(i)
        if isinstance(row[0], float) and row[0] > 1800 and isinstance(row[2], float):
            y = int(row[0]); m = int(round((row[0] - y) * 100))
            D[y * 100 + m] = row[2]
    return D


def month_last(d, min_day=24):
    """各月の最後の観測。最後の観測が月の min_day 日より前の月は落とす（途中の値を月末と読まない）"""
    last = {}
    for k in sorted(d):
        last[k // 100] = (k % 100, d[k])
    return {m: v for m, (dd, v) in last.items() if dd >= min_day}


def mret(levels):
    ks = sorted(levels)
    return {k: levels[k] / levels[p] - 1 for p, k in zip(ks, ks[1:]) if ym_add(p, 1) == k and k <= END}


# ───────────────────────── 統計（自前） ─────────────────────────
def nwt(x, L=12):
    n = len(x)
    mu = sum(x) / n
    e = [v - mu for v in x]
    s = sum(v * v for v in e) / n
    for j in range(1, L + 1):
        s += 2 * (1 - j / (L + 1)) * sum(e[i] * e[i - j] for i in range(j, n)) / n
    return mu / math.sqrt(s / n)


def geo(x):
    return math.exp(sum(math.log1p(v) for v in x) * 12 / len(x)) - 1


def cmp_(s, b, a=None, z=None):
    ks = [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z)]
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    mb = sum(bv) / len(bv); ms = sum(sv) / len(sv)
    beta = sum((x - ms) * (y - mb) for x, y in zip(sv, bv)) / sum((y - mb) ** 2 for y in bv)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(sum(d) / len(d) * 1200, 2), 't': round(nwt(d), 2),
            'cagr_s': round(geo(sv) * 100, 2), 'cagr_b': round(geo(bv) * 100, 2), 'cagr_diff': round((geo(sv) - geo(bv)) * 100, 2),
            'beta': round(beta, 3)}


def sharpe(r, rf, a=None, z=None):
    ks = [k for k in sorted(set(r) & set(rf)) if (a is None or k >= a) and (z is None or k <= z)]
    x = [r[k] - rf[k] for k in ks]
    return sum(x) / len(x) / S.stdev(x) * math.sqrt(12)


def sharpe_test(s, b, rf, a=None, z=None, reps=2000, block=12, seed=7):
    """シャープの差: Jobson-Korkie（Memmel 補正）の z と、循環ブロック・ブートストラップの P(差≤0)"""
    ks = [k for k in sorted(set(s) & set(b) & set(rf)) if (a is None or k >= a) and (z is None or k <= z)]
    x = [s[k] - rf[k] for k in ks]; y = [b[k] - rf[k] for k in ks]
    T = len(ks)

    def sr(v):
        return (sum(v) / len(v)) / S.stdev(v)
    s1, s2 = sr(x), sr(y)
    mx, my = sum(x) / T, sum(y) / T
    rho = sum((p - mx) * (q - my) for p, q in zip(x, y)) / math.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y))
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T
    zjk = (s1 - s2) / math.sqrt(var)
    rnd = random.Random(seed)
    diffs = []
    nb = math.ceil(T / block)
    for _ in range(reps):
        idx = []
        for _b in range(nb):
            st = rnd.randrange(T)
            idx += [(st + j) % T for j in range(block)]
        idx = idx[:T]
        xx = [x[i] for i in idx]; yy = [y[i] for i in idx]
        diffs.append((sr(xx) - sr(yy)) * math.sqrt(12))
    diffs.sort()
    return {'n': T, 'sharpe_s': round(s1 * math.sqrt(12), 4), 'sharpe_b': round(s2 * math.sqrt(12), 4), 'diff': round((s1 - s2) * math.sqrt(12), 4),
            'corr': round(rho, 3), 'jk_memmel_z': round(zjk, 2), 'boot_p_diff_le_0': round(sum(1 for d in diffs if d <= 0) / reps, 3),
            'boot_90ci': [round(diffs[int(0.05 * reps)], 3), round(diffs[int(0.95 * reps)], 3)]}


def roll20(s, b):
    ks = set(s) & set(b)
    out = []
    y = min(ks) // 100
    while True:
        a, z = y * 100 + 7, (y + 20) * 100 + 6
        if z > max(ks):
            break
        w = [k for k in sorted(ks) if a <= k <= z]
        if len(w) >= 233:  # 240 の 97%
            out.append((y, round((geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100, 2)))
        y += 1
    if not out:
        return None
    return {'windows': len(out), 'win_rate': round(sum(1 for _, v in out if v > 0) / len(out), 3), 'worst': min(out, key=lambda t: t[1]),
            'median': sorted(v for _, v in out)[len(out) // 2]}


def maxdd(r, a=None):
    w = pk = 1.0; dd = 0.0
    for k in sorted(r):
        if a and k < a:
            continue
        w *= 1 + r[k]; pk = max(pk, w); dd = min(dd, w / pk - 1)
    return round(dd * 100, 1)


def compound(r, a, z):
    ks = [k for k in sorted(r) if a <= k <= z]
    if not ks or ks[0] != a or ks[-1] != z:
        return None
    w = 1.0
    for k in ks:
        w *= 1 + r[k]
    return round((w - 1) * 100, 1)


def alpha(s, b, rf, a=None, z=None):
    ks = [k for k in sorted(set(s) & set(b) & set(rf)) if (a is None or k >= a) and (z is None or k <= z)]
    x = [s[k] - rf[k] for k in ks]; y = [b[k] - rf[k] for k in ks]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    be = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((q - my) ** 2 for q in y)
    al = [p - be * q for p, q in zip(x, y)]
    return {'beta': round(be, 3), 'alpha_ann': round(sum(al) / len(al) * 1200, 2), 'alpha_t': round(nwt(al), 2)}


def grade(full, train, hold, net_hold, r20, sh_tr, sh_ho, repl=None):
    """out/mw_prereg.json の C1〜C8（C7 は全期間 t≥3 のみで判定・Holm は使わない）を自前で当てる"""
    c = {'C1': bool(train and train['ex'] > 0 and train['t'] >= 2.0),
         'C2': bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0),
         'C3': bool(hold and hold['t'] >= 1.65),
         'C4': bool(r20 and r20['win_rate'] >= 0.8),
         'C5': None if repl is None else repl,
         'C6': bool(net_hold and net_hold['ex'] > 0 and net_hold['cagr_diff'] > 0),
         'C7': bool(full and full['t'] >= 3.0),
         'C8': bool(sh_tr and sh_ho and sh_tr[0] > sh_tr[1] and sh_ho[0] > sh_ho[1])}
    base = c['C1'] and c['C2'] and c['C6'] and c['C8']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


def block(s, net, b, rf, repl=None):
    """全期間・訓練・保有・直近・費用後・20年窓・シャープ・格付けを一まとめに（相手は戦略と同じ月だけに切る）"""
    b = {k: b[k] for k in s if k in b}
    full, train, hold = cmp_(s, b), cmp_(s, b, z=TE), cmp_(s, b, a=HS)
    nh = cmp_(net, b, a=HS)
    r20 = roll20(s, b)
    sh_tr = (round(sharpe(s, rf, z=TE), 4), round(sharpe(b, rf, z=TE), 4)) if train else None
    sh_ho = (round(sharpe(s, rf, a=HS), 4), round(sharpe(b, rf, a=HS), 4))
    g, c = grade(full, train, hold, nh, r20, sh_tr, sh_ho, repl)
    return {'full': full, 'train': train, 'hold': hold, 'recent_2013_07': cmp_(s, b, a=RS), 'net_hold': nh, 'net_train': cmp_(net, b, z=TE),
            'roll20': r20, 'sharpe_train': sh_tr, 'sharpe_hold': sh_ho, 'grade': g, 'criteria': c}


def lev(sp, rf, L, spread=0.005):
    return {k: rf[k] + L * (sp[k] - rf[k]) - max(L - 1, 0) * spread / 12 for k in sp if k in rf}


EPIS = {'1987-10': (198710, 198710), '2000-09..2002-09': (200009, 200209), '2008': (200801, 200812), '2008-09..2009-02': (200809, 200902),
        '2018-02': (201802, 201802), '2020-02..2020-03': (202002, 202003), '2022': (202201, 202212)}


# ───────────────────────── データ ─────────────────────────
def build_data():
    log = {}
    mkt, rf = french_ff3()
    mkt = {k: v for k, v in mkt.items() if k <= END}
    rf = {k: v for k, v in rf.items() if k <= END}
    # S&P500 配当込み: Yahoo ^SP500TR 日次→自前の月末。1988-02 より前は CBOE SPX 月末＋Shiller D/12
    M.yahoo('^SP500TR', '1d')
    tr = mret(month_last(yahoo_daily('^SP500TR')))
    spx_d = cboe_close('SPX')
    spx_m = month_last(spx_d)
    D = shiller_D()
    sp = dict(tr)
    built = {}
    for k in sorted(spx_m):
        p = ym_add(k, -1)
        if p in spx_m and k in D and k < min(tr):
            built[k] = (spx_m[k] + D[k] / 12) / spx_m[p] - 1
    for k, v in built.items():
        if 198607 <= k:
            sp[k] = v
    log['sp500tr_from'] = min(sp); log['yahoo_tr_from'] = min(tr); log['built_months'] = sorted(k for k in built if k >= 198607)
    # 研究側の月次（Yahoo 月足）との照合
    try:
        yhm = M.yahoo('^SP500TR')
        ks = sorted(set(yhm) & set(tr))
        d = [tr[k] - yhm[k] for k in ks]
        log['sp_daily_monthend_vs_yahoo_monthly'] = {'n': len(ks), 'mean_pct': round(S.mean(d) * 100, 4), 'max_abs_pct': round(max(map(abs, d)) * 100, 3)}
    except Exception as e:  # noqa
        log['sp_daily_monthend_vs_yahoo_monthly'] = str(e)[:100]
    ks = sorted(set(sp) & set(mkt))
    dd = [sp[k] - mkt[k] for k in ks]
    log['sp_vs_french_mkt'] = {'from': ks[0], 'n': len(ks), 'mean_diff_pct_m': round(S.mean(dd) * 100, 4), 'corr': round(M.corr([sp[k] for k in ks], [mkt[k] for k in ks]), 4)}
    return mkt, rf, sp, spx_d, log


# ───────────────────────── 1・2: O-RXM ─────────────────────────
def rxm_part(mkt, rf, sp, research):
    rxm = mret(month_last(cboe_close('RXM')))
    out = {'data': {'rxm_from': min(rxm), 'rxm_to': max(rxm), 'months': len(rxm)}}
    ks = sorted(k for k in rxm if k in sp and k in rf and k <= END)
    # RXM そのものの β（リスク・リバーサル＝デルタ約0.5 なら β≈0.5）
    out['RXM_index_vs_sp'] = alpha({k: rxm[k] for k in ks}, sp, rf)

    def overlay(kx=1.0, spread=0.005, cost=0.0096):
        s = {k: sp[k] + kx * (rxm[k] - rf[k]) - spread / 12 for k in ks}
        n = {k: s[k] - kx * cost / 12 for k in ks}
        return s, n
    s, n = overlay()
    # 研究側と同じ比較（相手: French Mkt ＝ S の行／相手: S&P500 配当込み ＝ 主の行）
    out['vs_french_mkt'] = block(s, n, mkt, rf)
    out['vs_sp500tr'] = block(s, n, sp, rf)
    out['sharpe_test'] = {'vs_french_mkt_train': sharpe_test(s, mkt, rf, z=TE), 'vs_french_mkt_hold': sharpe_test(s, mkt, rf, a=HS),
                          'vs_sp500tr_train': sharpe_test(s, sp, rf, z=TE), 'vs_sp500tr_hold': sharpe_test(s, sp, rf, a=HS)}
    out['alpha'] = {bn: {lab: alpha(s, bb, rf, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]}
                    for bn, bb in [('french_mkt', mkt), ('sp500tr', sp)]}
    # β をそろえた相手: 設計上のデルタ（25Δコール買い＋25Δプット売り＝0.5）から決まる 1.5 倍の S&P500（同じ借入 RF+0.5%）
    L15 = {k: v for k, v in lev(sp, rf, 1.5).items() if k in s}
    out['vs_static_1.5x_sp'] = {lab: cmp_(s, L15, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]}
    out['vs_static_1.5x_sp_net'] = {lab: cmp_(n, L15, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]}
    # ただの 1.5 倍の S&P500 を同じ線（相手 French Mkt）で格付けすると？（費用は先物の借入 0.5% のみ・売買は月0）
    out['plain_1.5x_sp_graded_vs_french_mkt'] = block(L15, L15, mkt, rf)
    L145 = {k: v for k, v in lev(sp, rf, 1.45).items() if k in s}
    out['plain_1.45x_sp_graded_vs_french_mkt'] = block(L145, L145, mkt, rf)
    # 過去36か月の β で合わせた借りた S&P500（後知恵なし）
    Lb = {}
    for i, k in enumerate(ks):
        if i < 36:
            continue
        w = ks[i - 36:i]
        b_ = alpha({u: s[u] for u in w}, {u: sp[u] for u in w}, rf)['beta']
        Lb[k] = rf[k] + b_ * (sp[k] - rf[k]) - max(b_ - 1, 0) * 0.005 / 12
    out['vs_trailing_beta_matched_sp'] = {lab: cmp_(s, Lb, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]}
    # 部分期間
    out['subperiods_vs_french_mkt'] = {lab: cmp_(s, mkt, a, z) for lab, a, z in
                                       [('2007-01..2016-10', 200701, 201610), ('2016-11..2026-08', 201611, 202608),
                                        ('2007-01..2012-12', 200701, 201212), ('2013-01..2026-08', 201301, 202608),
                                        ('1986-07..1996-09', 198607, 199609), ('1996-10..2006-12', 199610, 200612)]}
    out['subperiods_vs_static_1.5x'] = {lab: cmp_(s, L15, a, z) for lab, a, z in
                                        [('2007-01..2016-10', 200701, 201610), ('2016-11..2026-08', 201611, 202608)]}
    # 隣の設定（重ねる倍率・借入の上乗せ・費用）
    nb = {}
    for kx in (0.5, 1.0, 1.5):
        for spr in (0.0, 0.005, 0.015):
            s2, n2 = overlay(kx, spr)
            b2 = block(s2, n2, mkt, rf)
            nb[f'k{kx}_spread{spr * 100:.1f}%'] = {'grade_vs_french_mkt': b2['grade'], 'train_t': b2['train']['t'], 'hold_ex': b2['hold']['ex'],
                                                   'hold_t': b2['hold']['t'], 'sharpe_train': b2['sharpe_train'], 'sharpe_hold': b2['sharpe_hold'],
                                                   'failed': [k for k, v in b2['criteria'].items() if v is False]}
    s3, n3 = overlay(1.0, 0.005, 0.0192)
    nb['k1.0_spread0.5%_cost1.92%'] = {'net_hold': cmp_(n3, mkt, a=HS)}
    out['neighbors_vs_french_mkt'] = nb
    # 1988-02 から（作った S&P500 の月と 1987年10月を外す）
    s88 = {k: v for k, v in s.items() if k >= 198802}
    out['from_1988_02_vs_french_mkt'] = block(s88, {k: n[k] for k in s88}, mkt, rf)
    out['maxdd'] = {'strategy': maxdd(s), 'french_mkt': maxdd({k: mkt[k] for k in s}), 'sp500tr': maxdd({k: sp[k] for k in s}),
                    'static_1.5x_sp': maxdd(L15)}
    out['episodes'] = {e: {'O-RXM': compound(s, a, z), 'french_mkt': compound(mkt, a, z), 'static_1.5x_sp': compound(L15, a, z)}
                       for e, (a, z) in EPIS.items()}
    # 日本の個人（課税口座）: 先物・オプションの損益は申告分離 20.315%・3年の繰越控除。毎年の損益に課税
    #   相手: S&P500 の投信を NISA で（税なし）／課税口座で最後に売る（20.315% を最後に1回）
    def taxed_annual(r, a, z):
        ks2 = [k for k in sorted(r) if a <= k <= z]
        w = 1.0; carry = []
        for y in sorted({k // 100 for k in ks2}):
            w0 = w
            for k in ks2:
                if k // 100 == y:
                    w *= 1 + r[k]
            g = w - w0
            if g < 0:
                carry.append([y, -g])
            else:
                for c in carry:
                    if c[0] >= y - 3 and g > 0:
                        u = min(c[1], g); c[1] -= u; g -= u
                w -= g * 0.20315
            carry = [c for c in carry if c[1] > 1e-12 and c[0] >= y - 2]
        return w ** (12 / len(ks2)) - 1

    def deferred(r, a, z, tax=True):
        ks2 = [k for k in sorted(r) if a <= k <= z]
        w = 1.0
        for k in ks2:
            w *= 1 + r[k]
        if tax:
            w -= max(0.0, w - 1) * 0.20315
        return w ** (12 / len(ks2)) - 1
    jp = {}
    for lab, a, z in [('hold_2007-01..2026-08', 200701, 202608), ('full_1986-07..2026-08', 198607, 202608)]:
        nn = {k: n[k] for k in n}
        jp[lab] = {'strategy_taxed_every_year': round(taxed_annual(nn, a, z) * 100, 2),
                   'sp500_nisa_no_tax': round(deferred(sp, a, z, False) * 100, 2),
                   'sp500_taxable_sell_at_end': round(deferred(sp, a, z, True) * 100, 2),
                   'note': '年率・米ドル建て。投信の中の米国源泉10%（配当利回り約1.5〜2%×10%＝年0.15〜0.2%）は相手側に引いていない＝相手に有利ではなく戦略に有利な近似'}
    out['japan_tax'] = jp
    out['research_numbers'] = research
    return out


# ───────────────────────── 3: F4（VRP で持ち高を変える） ─────────────────────────
def rv_and_vrp(vol, px, min_obs=15):
    """VRP_m = (月末の VIX 型指数/100)²/12 − その月の日次の対数リターンの二乗和（前月末の終値から）"""
    ks = sorted(px)
    rv, cnt = collections.defaultdict(float), collections.Counter()
    for p, k in zip(ks, ks[1:]):
        dp = datetime.date(p // 10000, p // 100 % 100, p % 100); dk = datetime.date(k // 10000, k // 100 % 100, k % 100)
        if (dk - dp).days > 7:
            continue
        rv[k // 100] += math.log(px[k] / px[p]) ** 2
        cnt[k // 100] += 1
    iv = month_last(vol, min_day=20)
    pe = month_last(px, min_day=20)
    return {m: (iv[m] / 100) ** 2 / 12 - rv[m] for m in sorted(iv) if m in rv and cnt[m] >= min_obs and m in pe and m <= END}


def median_rule(sig, lo, hi, burn=60, q=0.5, window=None):
    """sig_t ≥ 1990-01〜t の q 分位（burn か月以上）なら hi、下なら lo を t+1 月に"""
    out, hist = {}, []
    for t in sorted(sig):
        hist.append(sig[t])
        h = hist if window is None else hist[-window:]
        if len(hist) < burn:
            continue
        srt = sorted(h)
        thr = srt[int(q * (len(srt) - 1))] if q != 0.5 else S.median(h)
        out[ym_add(t, 1)] = hi if sig[t] >= thr else lo
    return out


def run_weights(W, r, c, start, spread=0.005, tc=0.001):
    g, n, prev_g = {}, {}, None
    ks = [m for m in sorted(W) if m >= start and m in r and m in c and m <= END]
    for m in ks:
        w = W[m]
        x = c[m] + w * (r[m] - c[m]) - max(w - 1, 0) * spread / 12
        p = ym_add(m, -1)
        if p in g:
            drift = W[p] * (1 + r[p]) / (1 + g[p])
            to = abs(w - drift)
        else:
            to = 0.0
        g[m] = x; n[m] = x - to * tc
    return g, n


def f4_part(mkt, rf, sp, spx_d, research):
    vix = cboe_close('VIX')
    vrp = rv_and_vrp(vix, spx_d)
    out = {'vrp': {'from': min(vrp), 'to': max(vrp), 'months': len(vrp), 'mean_pct2': round(S.mean(vrp.values()) * 1e4, 3)}}
    W = median_rule(vrp, 1.0, 1.5)
    g, n = run_weights(W, sp, rf, 199504)
    out['weights'] = {'mean': round(S.mean(W[m] for m in g), 3), 'share_hi': round(sum(1 for m in g if W[m] > 1) / len(g), 3),
                      'mean_train': round(S.mean(W[m] for m in g if m <= TE), 3), 'mean_hold': round(S.mean(W[m] for m in g if m >= HS), 3)}
    rw = research.get('F_w_series') or {}
    if rw:
        agree = sum(1 for m in g if str(m) in rw and abs(rw[str(m)] - W[m]) < 1e-9)
        out['weights_agree_with_research'] = f'{agree}/{sum(1 for m in g if str(m) in rw)}'
    out['vs_sp500tr'] = block(g, n, sp, rf)
    out['vs_french_mkt'] = block(g, n, mkt, rf)
    out['sharpe_test'] = {'vs_sp500tr_train': sharpe_test(g, sp, rf, z=TE), 'vs_sp500tr_hold': sharpe_test(g, sp, rf, a=HS)}
    out['alpha_vs_sp500tr'] = {lab: alpha(g, sp, rf, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]}
    # 時期の選び方の価値＝いつも 1.25 倍（中央値で分けるので事前に決まる平均）との差
    st = {m: 1.25 for m in W}
    gs, ns = run_weights(st, sp, rf, 199504)
    out['static_1.25x_vs_sp500tr'] = block(gs, ns, sp, rf)
    out['F4_minus_static_1.25x'] = {lab: cmp_(g, gs, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None),
                                                                            ('2007-01..2016-10', 200701, 201610), ('2016-11..2026-08', 201611, 202608)]}
    out['F4_minus_static_1.25x_net'] = {lab: cmp_(n, ns, a, z) for lab, a, z in [('full', None, None), ('train', None, TE), ('hold', HS, None)]}
    out['subperiods_vs_sp500tr'] = {lab: cmp_(g, sp, a, z) for lab, a, z in
                                    [('2007-01..2016-10', 200701, 201610), ('2016-11..2026-08', 201611, 202608),
                                     ('2007-01..2012-12', 200701, 201212), ('2013-01..2026-08', 201301, 202608),
                                     ('1995-04..2000-12', 199504, 200012), ('2001-01..2006-12', 200101, 200612)]}
    out['maxdd'] = {'F4': maxdd(g), 'sp500tr': maxdd({k: sp[k] for k in g}), 'static_1.25x': maxdd(gs)}
    out['episodes'] = {e: {'F4': compound(g, a, z), 'sp500tr': compound(sp, a, z), 'static_1.25x': compound(gs, a, z)}
                       for e, (a, z) in EPIS.items()}
    out['w_2020'] = {str(m): W.get(m) for m in range(202001, 202007)}
    # 隣の設定（すべて事後・格付けに使わない）
    nb = {}

    def row(Wx, start=199504, lab=''):
        gx, nx = run_weights(Wx, sp, rf, start)
        b = block(gx, nx, sp, rf)
        mw = S.mean(Wx[m] for m in gx)
        stx = {m: mw for m in Wx}
        gsx, _ = run_weights(stx, sp, rf, start)
        d_ = cmp_(gx, gsx, a=HS); d_t = cmp_(gx, gsx, z=TE)
        return {'grade': b['grade'], 'train_ex': b['train']['ex'], 'train_t': b['train']['t'], 'hold_ex': b['hold']['ex'], 'hold_t': b['hold']['t'],
                'full_t': b['full']['t'], 'sharpe_train': b['sharpe_train'], 'sharpe_hold': b['sharpe_hold'], 'mean_w': round(mw, 3),
                'timing_vs_static_same_mean_w_train': [d_t['ex'], d_t['t']], 'timing_vs_static_same_mean_w_hold': [d_['ex'], d_['t']],
                'failed': [k for k, v in b['criteria'].items() if v is False]}
    for hi in (1.25, 1.5, 1.75, 2.0):
        nb[f'hi{hi}'] = row(median_rule(vrp, 1.0, hi))
    for q in (0.4, 0.6):
        nb[f'quantile{q}'] = row(median_rule(vrp, 1.0, 1.5, q=q))
    for burn in (36, 120):
        nb[f'burn{burn}'] = row(median_rule(vrp, 1.0, 1.5, burn=burn))
    nb['rolling_120m_median'] = row(median_rule(vrp, 1.0, 1.5, window=120))
    nb['start_1995-01'] = row(W, start=199501)
    vixm = {m: v for m, v in month_last(vix, 20).items() if m in vrp}
    nb['signal_VIX_level'] = row(median_rule(vixm, 1.0, 1.5))
    rvonly = {m: vixm[m] ** 2 / 1e4 / 12 - vrp[m] for m in vrp if m in vixm}
    nb['signal_low_RV'] = row(median_rule({m: -v for m, v in rvonly.items()}, 1.0, 1.5))
    out['neighbors_post_hoc'] = nb
    # VXO で 1986〜1989 を足して訓練を 1991-01 から（研究側の P3 と同じ考え・独立の実装）
    vxo = fred_d('VXOCLS', 'fred_VXOCLS_daily.csv')
    vold = {m: v for m, v in rv_and_vrp(vxo, spx_d).items() if 198601 <= m <= 198912}
    vx = dict(vold); vx.update(vrp)
    Wx = median_rule(vx, 1.0, 1.5)
    gx, nx = run_weights(Wx, sp, rf, 199101)
    out['vxo_extension_1991'] = {'train': cmp_(gx, sp, z=TE), 'hold': cmp_(gx, sp, a=HS), 'full': cmp_(gx, sp),
                                 'sharpe_train': (round(sharpe(gx, rf, z=TE), 4), round(sharpe(sp, rf, 199101, TE), 4))}
    # C5: 米国外4地域（研究側と同じ地域・自前の実装）。相手（地元の買って持つだけ）に加え、いつも 1.25 倍 との差とシャープも
    regions = {}
    specs = [('ドイツ', lambda: stoxx('V1X'), lambda: yahoo_daily('^GDAXI'), lambda: fred_m_rate('IR3TIB01DEM156N'), 'DAX は配当込み'),
             ('インド', lambda: yahoo_daily('^INDIAVIX'), lambda: yahoo_daily('^NSEI'), lambda: fred_m_rate('IRSTCI01INM156N'), 'NIFTY は価格のみ'),
             ('オーストラリア', lambda: yahoo_daily('^AXVI'), lambda: yahoo_daily('^AXJO'), lambda: fred_m_rate('IR3TIB01AUM156N'), 'ASX200 は価格のみ'),
             ('ブラジル(EWZ)', lambda: fred_d('VXEWZCLS', 'fred_VXEWZCLS_daily.csv'), lambda: yahoo_daily('EWZ'), lambda: dict(rf), 'EWZ は分配込み・米ドル')]
    for reg, fv, fp, fr, note in specs:
        try:
            vol, px, lr = fv(), fp(), fr()
        except Exception as e:  # noqa
            regions[reg] = {'status': str(e)[:120]}
            continue
        v2 = rv_and_vrp(vol, px)
        r2 = mret(month_last(px, 20))
        W2 = median_rule(v2, 1.0, 1.5)
        start = min(m for m in W2 if m in r2 and m in lr)
        g2, n2 = run_weights(W2, r2, lr, start)
        st2 = {m: 1.25 for m in W2}
        gs2, _ = run_weights(st2, r2, lr, start)
        b2 = {k: r2[k] for k in g2}
        lr2 = {k: lr[k] for k in g2 if k in lr}
        regions[reg] = {'note': note, 'start': start, 'vs_local_buyhold': cmp_(g2, b2), 'net_vs_local_buyhold': cmp_(n2, b2),
                        'minus_static_1.25x': cmp_(g2, gs2), 'sharpe': (round(sharpe(g2, lr2), 3), round(sharpe(b2, lr2), 3)),
                        'mean_w': round(S.mean(W2[m] for m in g2), 3)}
    pos_arith = [r for r, v in regions.items() if v.get('vs_local_buyhold') and v['vs_local_buyhold']['ex'] > 0]
    pos_geo = [r for r, v in regions.items() if v.get('vs_local_buyhold') and v['vs_local_buyhold']['cagr_diff'] > 0]
    pos_timing = [r for r, v in regions.items() if v.get('minus_static_1.25x') and v['minus_static_1.25x']['ex'] > 0]
    sh_up = [r for r, v in regions.items() if v.get('sharpe') and v['sharpe'][0] > v['sharpe'][1]]
    out['C5_regions'] = regions
    out['C5_summary'] = {'regions': len(regions), 'arith_excess_positive': pos_arith, 'geo_cagr_diff_positive': pos_geo,
                         'beats_static_1.25x': pos_timing, 'sharpe_above_local': sh_up}
    return out


# ───────────────────────── 4: O-VPD ─────────────────────────
def vpd_part(mkt, rf, sp):
    vpd = mret(month_last(cboe_close('VPD')))
    ks = sorted(k for k in vpd if k in sp and k in rf)
    s = {k: sp[k] + (vpd[k] - rf[k]) - 0.005 / 12 for k in ks}
    n = {k: s[k] - 0.006 / 12 for k in ks}
    out = {'from': min(s), 'vs_sp500tr': block(s, n, sp, rf), 'vs_french_mkt': block(s, n, mkt, rf),
           'alpha_vs_sp500tr': alpha(s, sp, rf), 'VPD_index_vs_sp': alpha({k: vpd[k] for k in ks}, sp, rf),
           'sharpe_test_vs_sp500tr': sharpe_test(s, sp, rf),
           'subperiods_vs_sp500tr': {lab: cmp_(s, sp, a, z) for lab, a, z in [('2007-12..2016-12', 200712, 201612), ('2017-01..2026-08', 201701, 202608),
                                                                              ('2009-04..2026-08（2008年の暴落の後から）', 200904, 202608)]},
           'maxdd': {'O-VPD': maxdd(s), 'sp500tr': maxdd({k: sp[k] for k in s})},
           'episodes': {e: {'O-VPD': compound(s, a, z), 'sp500tr': compound(sp, a, z)} for e, (a, z) in EPIS.items()}}
    L2 = {k: v for k, v in lev(sp, rf, 2.0).items() if k in s}
    out['vs_static_2x_sp'] = cmp_(s, L2)
    return out


# ───────────────────────── 判定 ─────────────────────────
def verdicts(rx, f4, vp, mt):
    V = []
    a, b = rx['vs_french_mkt'], rx['vs_sp500tr']
    st = rx['sharpe_test']
    s15 = rx['vs_static_1.5x_sp']; s15n = rx['vs_static_1.5x_sp_net']
    p145 = rx['plain_1.45x_sp_graded_vs_french_mkt']
    sub = rx['subperiods_vs_french_mkt']
    jp = rx['japan_tax']['hold_2007-01..2026-08']
    nb = rx['neighbors_vs_french_mkt']
    V.append({'name': 'O-RXM[vs French Mkt]', 'claimed_grade': 'S', 'reproduced': True, 'verified_grade': 'C', 'verdict': 'refuted',
              'key_numbers': (f"再現 全期間 +{a['full']['ex']}%/年 t{a['full']['t']}・訓練 +{a['train']['ex']} t{a['train']['t']}・保有 +{a['hold']['ex']} t{a['hold']['t']}"
                              f"・CAGR差 +{a['hold']['cagr_diff']}・20年窓 {a['roll20']['win_rate']:.0%}・費用後の保有 +{a['net_hold']['ex']}（研究と一致）。"
                              f"β {a['hold']['beta']}。1.5倍の S&P500 との差: 保有 +{s15['hold']['ex']} t{s15['hold']['t']}・費用後 {s15n['hold']['ex']} t{s15n['hold']['t']}。"
                              f"シャープ 保有 {st['vs_french_mkt_hold']['sharpe_s']} 対 {st['vs_french_mkt_hold']['sharpe_b']}（z {st['vs_french_mkt_hold']['jk_memmel_z']}・P(差≤0) {st['vs_french_mkt_hold']['boot_p_diff_le_0']}）"),
              'issues': [
                  '事前登録（prereg1 robustness_not_candidates）がこの行を『候補にしない』頑健性の行と定めている＝S は判定の対象外',
                  f"RXM は β {rx['RXM_index_vs_sp']['beta']}（25デルタのコール買い＋プット売り＝デルタ約0.5）。重ねた姿は約1.5倍に借りた S&P500 で、α は対 S&P500 配当込み {rx['alpha']['sp500tr']['hold']['alpha_ann']}%/年 t{rx['alpha']['sp500tr']['hold']['alpha_t']}（保有）・対 French Mkt {rx['alpha']['french_mkt']['hold']['alpha_ann']} t{rx['alpha']['french_mkt']['hold']['alpha_t']}",
                  f"オプションを使わないただの 1.45倍の S&P500 が同じ線・同じ相手で {p145['grade']}（訓練 t{p145['train']['t']}・保有 t{p145['hold']['t']}・全期間 t{p145['full']['t']}・シャープ 訓練 {p145['sharpe_train']} 保有 {p145['sharpe_hold']}）＝ S は借りた分で作れる",
                  f"C8 の合格は相手の取り違え: 作りは S&P500 だが相手は French Mkt。訓練のシャープは S&P500 配当込み {b['sharpe_train'][1]} ＞ French Mkt {a['sharpe_train'][1]}。自分の原資産（S&P500 配当込み）相手では訓練 {b['sharpe_train'][0]} 対 {b['sharpe_train'][1]}・保有 {b['sharpe_hold'][0]} 対 {b['sharpe_hold'][1]} で両方負け＝主の行は C",
                  f"シャープの差は保有 +{st['vs_french_mkt_hold']['diff']}（90%区間 {st['vs_french_mkt_hold']['boot_90ci']}）・訓練 +{st['vs_french_mkt_train']['diff']}（z {st['vs_french_mkt_train']['jk_memmel_z']}）＝雑音",
                  f"1.5倍の S&P500（同じ借入 RF+0.5%）に対して オプション費用（年0.96%）後は 保有 {s15n['hold']['ex']}%/年・全期間 {s15n['full']['ex']}＝オプションは費用分だけ損",
                  f"保有期間の前半 2007-01〜2016-10 +{sub['2007-01..2016-10']['ex']} t{sub['2007-01..2016-10']['t']}・2007〜2012 {sub['2007-01..2012-12']['ex']}（CAGR差 {sub['2007-01..2012-12']['cagr_diff']}）＝勝ちは 2013年以降の上げ相場（β1.46）にほぼ全部。後半 +{sub['2016-11..2026-08']['ex']} t{sub['2016-11..2026-08']['t']}",
                  f"隣の設定: 借入の上乗せ 1.5%（個人の信用・先物の現実に近い）で {nb['k1.0_spread1.5%']['grade_vs_french_mkt']}（落ちる線 {nb['k1.0_spread1.5%']['failed']}）・重ね0.5倍で {nb['k0.5_spread0.5%']['grade_vs_french_mkt']}・費用2倍で費用後の保有 t{nb['k1.0_spread0.5%_cost1.92%']['net_hold']['t']}",
                  f"最大下落 {rx['maxdd']['strategy']}%（市場 {rx['maxdd']['french_mkt']}）・1987年10月 {rx['episodes']['1987-10']['O-RXM']}%・2020年2〜3月 {rx['episodes']['2020-02..2020-03']['O-RXM']}%（市場 {rx['episodes']['2020-02..2020-03']['french_mkt']}）",
                  f"日本の個人: SPX オプションと先物は NISA の外・損益は毎年 20.315%。保有期間の税引後 年{jp['strategy_taxed_every_year']}% ＜ NISA の S&P500 年{jp['sp500_nisa_no_tax']}%",
                  f"多重検定: 保有 t{a['hold']['t']}・全期間 t{a['full']['t']}。角度の96本の Bonferroni 線 t{mt['bonferroni_t_angle_(two-sided_5%)']}・プログラム全体 {mt['bonferroni_t_program_wide']} に届かない",
                  'RXM の 1986〜 の歴史は後から計算したもの（CBOE の説明文も『ストラングルの売り』と実物に合わない）。生き残りの偏りは無い（指数）']})
    b = rx['vs_sp500tr']
    V.append({'name': 'O-RXM（主の族 A）', 'claimed_grade': 'C', 'reproduced': True, 'verified_grade': 'C', 'verdict': 'confirmed',
              'key_numbers': f"保有 +{b['hold']['ex']} t{b['hold']['t']}・訓練 +{b['train']['ex']} t{b['train']['t']}・シャープ 訓練 {b['sharpe_train']} 保有 {b['sharpe_hold']}（C8 不合格）",
              'issues': ['保有期間の超過が研究側で2番目に大きい行。中身は上と同じ約1.5倍の S&P500・α ≈ 0', 'C の判定をそのまま支持']})
    v = f4['vs_sp500tr']; d = f4['F4_minus_static_1.25x']; dn = f4['F4_minus_static_1.25x_net']; c5 = f4['C5_summary']; nb = f4['neighbors_post_hoc']
    fm = f4['vs_french_mkt']
    V.append({'name': 'F4-med1/1.5（探索・線の最も近く）', 'claimed_grade': 'C', 'reproduced': True, 'verified_grade': 'C', 'verdict': 'confirmed',
              'key_numbers': (f"持ち高 {f4['weights_agree_with_research']} で一致。訓練 +{v['train']['ex']} t{v['train']['t']}・保有 +{v['hold']['ex']} t{v['hold']['t']}・費用後 +{v['net_hold']['ex']}"
                              f"・全期間 t{v['full']['t']}・20年窓 {v['roll20']['win_rate']:.0%}。いつも1.25倍との差 保有 +{d['hold']['ex']} t{d['hold']['t']}（費用後 +{dn['hold']['ex']} t{dn['hold']['t']}）"),
              'issues': [
                  f"C は近い取りこぼしで、脆い方向は『上がる』側: 始まりを 1995-01（規則が作れる最初の月）にすると訓練 t{nb['start_1995-01']['train_t']} で {nb['start_1995-01']['grade']}、分位を 40% にすると {nb['quantile0.4']['grade']}（60% なら {nb['quantile0.6']['grade']}・120か月の助走なら訓練 t{nb['burn120']['train_t']}）。だが S になっても中身は変わらない",
                  f"超過の t は高い側の倍率（1.25/1.5/1.75/2.0）に依らず同じ（訓練 t は 1.25倍 {nb['hi1.25']['train_t']}・2.0倍 {nb['hi2.0']['train_t']}）＝超過は（w−1）×株の上乗せそのもの。w は常に1以上なので C2・C4・C6 は『株が現金に勝った』の検定になる",
                  f"時期の選び方の価値（いつも1.25倍との差）: 保有 +{d['hold']['ex']} t{d['hold']['t']}・前半 2007-01〜2016-10 +{d['2007-01..2016-10']['ex']} t{d['2007-01..2016-10']['t']}・後半 2016-11〜 {d['2016-11..2026-08']['ex']} t{d['2016-11..2026-08']['t']}＝後半で消えた",
                  f"米国外（C5 の 3/4）: 算術の超過が正は {c5['arith_excess_positive']}、幾何（CAGR差）が正は {c5['geo_cagr_diff_positive']}、いつも1.25倍に勝ったのは {c5['beats_static_1.25x']}、シャープが地元を上回ったのは {c5['sharpe_above_local'] or 'なし（0/4）'}＝3/4 は借りた分の数え上げ",
                  f"相手を French Mkt にすると 訓練 t{fm['train']['t']}・全期間 t{fm['full']['t']}（C1・C7 不合格）",
                  f"シャープの差 訓練 +{f4['sharpe_test']['vs_sp500tr_train']['diff']}（P(差≤0) {f4['sharpe_test']['vs_sp500tr_train']['boot_p_diff_le_0']}）・保有 +{f4['sharpe_test']['vs_sp500tr_hold']['diff']}（{f4['sharpe_test']['vs_sp500tr_hold']['boot_p_diff_le_0']}）＝雑音",
                  f"訓練の中でも 2001-01〜2006-12 は {f4['subperiods_vs_sp500tr']['2001-01..2006-12']['ex']}%/年・1995〜2000 の上げ相場 +{f4['subperiods_vs_sp500tr']['1995-04..2000-12']['ex']} に依存",
                  f"VXO で 1991 年へ延ばすと訓練 +{f4['vxo_extension_1991']['train']['ex']} t{f4['vxo_extension_1991']['train']['t']}・シャープ {f4['vxo_extension_1991']['sharpe_train']}（相手より低い）",
                  f"信号を VIX の水準に替えると保有のシャープ {nb['signal_VIX_level']['sharpe_hold']}＝相手以下",
                  f"最大下落 {f4['maxdd']['F4']}%（S&P500 {f4['maxdd']['sp500tr']}）・2020年1〜3月は 1.5倍のまま → 2〜3月 {f4['episodes']['2020-02..2020-03']['F4']}%（S&P500 {f4['episodes']['2020-02..2020-03']['sp500tr']}）",
                  f"多重検定: 全期間 t{v['full']['t']} ＜ 角度の Bonferroni {mt['bonferroni_t_angle_(two-sided_5%)']} ＜ プログラム {mt['bonferroni_t_program_wide']}。研究側の Holm も第2部だけで p 0.046・角度全体で 0.143"]})
    x = vp['vs_sp500tr']
    V.append({'name': 'O-VPD（保有期間の超過が最大・報告のみ）', 'claimed_grade': 'C', 'reproduced': True, 'verified_grade': 'C', 'verdict': 'confirmed',
              'key_numbers': f"2007-12〜 +{x['hold']['ex']}%/年 t{x['hold']['t']}・CAGR差 +{x['hold']['cagr_diff']}・β {vp['alpha_vs_sp500tr']['beta']}・α {vp['alpha_vs_sp500tr']['alpha_ann']} t{vp['alpha_vs_sp500tr']['alpha_t']}",
              'issues': ['訓練期間が無い（2007-12〜）＝C1 は構造的に不合格', f"VIX 先物の売り（VPD）の β は {vp['VPD_index_vs_sp']['beta']}＝重ねると約2倍の S&P500。2倍の S&P500 に CAGR で {vp['vs_static_2x_sp']['cagr_diff']}%/年 負け",
                         f"シャープ {x['sharpe_hold'][0]} ＜ S&P500 {x['sharpe_hold'][1]}（C8 不合格）・最大下落 {vp['maxdd']['O-VPD']}%・2008年 {vp['episodes']['2008']['O-VPD']}%・2020年2〜3月 {vp['episodes']['2020-02..2020-03']['O-VPD']}%",
                         f"勝ちは 2009年4月以降（+{vp['subperiods_vs_sp500tr']['2009-04..2026-08（2008年の暴落の後から）']['ex']}）＝始まりが 2008年の暴落の直前か後かで決まる"]})
    return V


# ───────────────────────── 本体 ─────────────────────────
def main():
    R = json.load(open(os.path.join(M.BASE, 'out', 'mw_options_vrp.json')))
    Sx = R['strategies']
    summ = json.load(open(os.path.join(M.BASE, 'out', 'mw_summary.json')))

    def rnum(k):
        e = Sx[k]
        pick = lambda x: None if not x else [x.get('ex_ann'), x.get('t'), x.get('cagr_diff')]
        return {'grade': e['grade'], 'full': pick(e.get('full')), 'train': pick(e.get('train')), 'hold': pick(e.get('hold')),
                'net_hold': pick(e.get('cost_hold')), 'roll20': (e.get('roll20') or {}).get('win_rate'), 'sharpe': e.get('sharpe'),
                'criteria': e.get('criteria')}
    mkt, rf, sp, spx_d, dlog = build_data()
    out = {'angle': 'options_vrp', 'verifier': 'adversarial verifier（独立の実装）', 'generated': datetime.date.today().isoformat(),
           'independent_parts': ['CBOE CSV・Yahoo 日次 JSON・FRED・STOXX・French CSV・Shiller xls の自前の読み込み',
                                 'S&P500 配当込みの月次（Yahoo 日次→自前の月末・1988-02 より前は SPX 月末＋Shiller 配当）',
                                 '重ね（O-RXM・O-VPD）・VRP・中央値の持ち高・回転の費用の組み立て',
                                 '超過・NW t（ラグ12）・CAGR 差・20年窓・シャープ・シャープ差の検定（JK-Memmel と循環ブロック・ブートストラップ）・α/β・格付け C1〜C8',
                                 'β をそろえた相手（1.5倍・過去36か月の β）・いつも 1.25 倍・隣の設定・米国外4地域・日本の税の試算'],
           'shared_parts': ['mw_common.get（取得とキャッシュ）・mw_common.yahoo（キャッシュの作成のみ）・mw_common.corr（照合の相関1か所）'],
           'sanity': dlog}
    cands = {}
    rx = rxm_part(mkt, rf, sp, {'O-RXM[vs French Mkt]': rnum('O-RXM[vs French Mkt]'), 'O-RXM': rnum('O-RXM')})
    cands['O-RXM (S の行 = 相手 French Mkt ／ 主の行 = 相手 S&P500 配当込み)'] = rx
    f4 = f4_part(mkt, rf, sp, spx_d, {'F_w_series': R['part2']['F_w_series']['F4-med1/1.5']})
    f4['research_numbers'] = rnum('F4-med1/1.5')
    cands['F4-med1/1.5'] = f4
    vp = vpd_part(mkt, rf, sp)
    vp['research_numbers'] = rnum('O-VPD')
    cands['O-VPD'] = vp
    out['candidates'] = cands
    n_angle = R['n_tested']
    bonf_angle = ND.inv_cdf(1 - 0.05 / n_angle / 2)
    out['multiple_testing'] = {'angle_tests': n_angle, 'bonferroni_t_angle_(two-sided_5%)': round(bonf_angle, 2),
                               'program_tests': summ.get('program_tests_total'), 'bonferroni_t_program_wide': summ.get('bonferroni_t_program_wide'),
                               'best_t': {'O-RXM[vs French Mkt] hold/full': [rx['vs_french_mkt']['hold']['t'], rx['vs_french_mkt']['full']['t']],
                                          'F4 hold/full': [f4['vs_sp500tr']['hold']['t'], f4['vs_sp500tr']['full']['t']],
                                          'O-VPD hold': vp['vs_sp500tr']['hold']['t']},
                               'note': '研究側の Holm は族 A＋B＋C の22本と F＋G を足した35本だけ。探索・頑健性・報告のみを含む96本では線 t≈3.47、プログラム全体では 4.35'}
    out['verdicts'] = verdicts(rx, f4, vp, out['multiple_testing'])
    out['conclusion_ja'] = (
        'この角度で線（S/A/B）に乗った唯一の行 O-RXM[vs French Mkt]（S）は、数字は完全に再現したが反証された（C）。'
        'RXM は設計上デルタ約0.5のリスク・リバーサルで、重ねた姿は約1.5倍に借りた S&P500。オプションを一切使わない『1.45倍の S&P500』でも同じ線で S になる'
        '＝線を越えたのは借りた分と、作りは S&P500 なのに相手が French Mkt という食い違い（訓練のシャープ 0.501 と 0.476 の差）のおかげ。'
        '1.5倍の S&P500 を相手にするとオプション費用後 全期間 −0.57・保有 −0.50%/年。F4（探索・C）と O-VPD（C）も中身は借りた分で、時期の選び方・保険料の上乗せは年0〜1%・統計は偶然と区別できない。')
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('書いた', OUT)
    return out


if __name__ == '__main__':
    main()
