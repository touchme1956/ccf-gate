#!/usr/bin/env python3
"""night/nx_lazy.py — 角度 nx_lazy（10-K の本文が前年とどれだけ変わったか・Cohen-Malloy-Nguyen 2020『Lazy Prices』）の測定

事前登録: out/nx_lazy_prereg.json（測る前に commit 済み・書き換えない）。全体の線: out/nx_prereg.json（criteria_short_sample）。
データ: night/nx_lazy_data.py が作った out/_nx_cache/nx_lazy_members.json（月末ごとの構成の CIK）と
        out/_nx_cache/nx_lazy_signals.csv（10-K ごとの特徴量と並べる月）。株価はここで初めて Yahoo から取る。
出力: out/nx_lazy.json（tested に全50本・負けも。格付けは nx_common.grade_short）。
約束
- 規則の中身は事前登録のまま（結果を見て変えない）。事前登録どおりにできない所は deviations_from_prereg に書く
- 結果を見た後の分析は post_hoc に『事後』と明記し、格付けに使わない
- 欠測は 0 と読まない（株価が無い月は外す・0 で埋めない）
- 門・採点・配分には使わない（測定器）
"""
import sys, os, csv, json, math, time, datetime, collections, bisect, io, zipfile, re, urllib.request, urllib.error, urllib.parse, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import nx_common as N
import nx_lazy_data as D

BASE = N.BASE
CACHE = N.CACHE
PRE = os.path.join(BASE, 'out', 'nx_lazy_prereg.json')
END = 202608            # 株価の月次がそろう最後の月（2026-09 は途中）
FULL_START0 = 199707
FIRST_HALF_END, SECOND_HALF_START = 201112, 201201
COST = 0.001            # 片道 100% あたり 0.10%
COST_HI = 0.0025        # 感度 0.25%
BORROW = 0.003          # X2 の売り側の借株料（年）
LB_HIT = -0.30          # 途切れた次の月
MIN_RANK, MIN_HOLD, MIN_IND = 50, 10, 10


# ───────────────────────── 月の算術 ─────────────────────────
def ym_add(ym, k):
    y, m = divmod(ym, 100)
    n = y * 12 + (m - 1) + k
    return (n // 12) * 100 + n % 12 + 1


def ym_range(a, z):
    out = []
    while a <= z:
        out.append(a)
        a = ym_add(a, 1)
    return out


def ym_of(d):
    return int(d[:4]) * 100 + int(d[5:7])


# ───────────────────────── 株価（Yahoo 月足・調整後終値と分割だけ調整した終値） ─────────────────────────
MONTH_CHECK = collections.Counter()


def yahoo_monthly(ticker):
    """{yyyymm: (adjclose, close)}。nx_common.yahoo と同じ URL・同じキャッシュ名（yh_{t}_1mo.json）。
    404（記号が無い）は None を返し、負のキャッシュ（.404）を残す。月は UTC で読み、ニューヨーク時間で読んでも同じ月かを数える"""
    name = f'yh_{ticker.replace("^", "IDX_").replace("=", "_")}_1mo.json'
    p = os.path.join(CACHE, name)
    neg = p + '.404'
    if os.path.exists(neg) and time.time() - os.path.getmtime(neg) < 3 * 86400:
        return None
    if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < 3 * 86400 and os.path.getsize(p) > 0):
        u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
        b, err = None, None
        for i in range(5):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers=N.UA), timeout=60).read()
                break
            except urllib.error.HTTPError as e:
                err = e
                if e.code == 404:
                    open(neg, 'w').write('404')
                    return None
                time.sleep(2 ** (i + 1))
            except Exception as e:  # noqa
                err = e
                time.sleep(2 ** (i + 1))
        if b is None:
            raise RuntimeError(f'Yahoo 取得失敗 {ticker}: {err}')
        tmp = f'{p}.{os.getpid()}.tmp'
        open(tmp, 'wb').write(b)
        os.replace(tmp, p)
        time.sleep(0.25)
    try:
        j = json.load(open(p))
        r = j['chart']['result'][0]
    except Exception:  # noqa
        return None
    ts = r.get('timestamp') or []
    if not ts:
        return None
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose')
    cl = r['indicators']['quote'][0].get('close')
    if adj is None or cl is None:
        return None
    out = {}
    for t, a, c in zip(ts, adj, cl):
        d = datetime.datetime.utcfromtimestamp(t)
        ym = d.year * 100 + d.month
        dny = datetime.datetime.utcfromtimestamp(t - 5 * 3600)  # ニューヨーク（UTC−5/−4）で読んだ月
        dny4 = datetime.datetime.utcfromtimestamp(t - 4 * 3600)
        if ym <= END:
            MONTH_CHECK['bars'] += 1
            if d.day != 1:
                MONTH_CHECK['bar_not_on_day1_utc'] += 1
            if dny.year * 100 + dny.month != ym or dny4.year * 100 + dny4.month != ym:
                MONTH_CHECK['month_differs_in_new_york'] += 1
            if ym in out:
                MONTH_CHECK['duplicate_month'] += 1
        if ym > END or a is None or c is None or a <= 0 or c <= 0:
            continue
        out[ym] = (a, c)
    return out or None


def returns_of(px):
    """連続した月どうしだけでリターンを作る（間の月が抜けたら作らない＝0 で埋めない）"""
    ks = sorted(px)
    return {k: px[k][0] / px[p][0] - 1 for p, k in zip(ks, ks[1:]) if ym_add(p, 1) == k}


# ───────────────────────── 会社の同定の再現（記号 k を残す） ─────────────────────────
def relink():
    """nx_lazy_data.build_panel と同じ約束で、月末ごとの (cik → (記号 k, 道)) を作り直す。
    build_panel は CIK と道だけを残すので、C（前身）の株価の記号を決める（k が後継の記号か）ためにここで k を残す。
    結果の CIK の集合と道が nx_lazy_members.json と一致することを確かめる（sanity に書く）"""
    uni = D.load_universe()
    hist = D.sp_history()
    dates = [d for d, _ in hist]
    recs = {}
    for fn in os.listdir(D.OUTDIR):
        if fn.endswith('.json'):
            o = json.load(open(os.path.join(D.OUTDIR, fn)))
            recs[o['cik']] = o
    cand = {int(k): v for k, v in uni['candidates'].items()}
    known_sp = set(t for _, st in hist for t in st)
    spans_all, _ = D.ticker_spans(hist)
    cur_tk = {c['cik']: c['tickers'][0] for c in cand.values() if 'A_current_member' in c['via']}
    c_end = {c['cik']: max(z for a0, z in c['windows']) for c in cand.values()
             if 'C_predecessor_of_current' in c['via'] and 'A_current_member' not in c['via']
             and 'B_former_member_same_ticker_now' not in c['via'] and 'D_fts_renamed_survivor' not in c['via']}

    def siblings(cik):
        c = cand.get(cik) or {}
        return {t for t in (c.get('price_tickers') or []) + (c.get('sec_tickers') or []) + (c.get('tickers') or []) if t in known_sp}

    def own(r, cik):
        if r.get('symbols_ix'):
            got = set(r['symbols_ix'])
        else:
            cc = r.get('symbols') or {}
            if not cc:
                return set()
            mx = max(cc.values())
            got = {k for k, v in cc.items() if v == mx}
        sib = siblings(cik)
        if got & sib:
            got |= sib
        return got
    claims = {cik: [(r['filed'], own(r, cik)) for r in o['filings'] if 'fetch_err' not in ' '.join(r.get('flags', []))]
              for cik, o in recs.items()}

    def a_ok(cik, tk, me):
        da = (cand[cik].get('wiki_date_added') or {}).get(tk)
        if not da:
            return True
        for a0, z0 in spans_all.get(tk, []):
            if a0 <= me < z0:
                return da <= z0
        return False
    b_fts, c_fts = {}, {}
    for c in cand.values():
        ok = [(t, a0, z0) for t, n, top, a0, z0 in (c.get('fts_for_own_ticker') or []) if top and n >= 5]
        if ok:
            b_fts[c['cik']] = ok
        if 'C_predecessor_of_current' in c['via']:
            ok2 = {t for t, n, top in (c.get('fts_for_successor_tickers') or []) if top and n >= 5}
            if ok2:
                c_fts[c['cik']] = ok2

    def span_of(tk, me):
        for a0, z0 in spans_all.get(tk, []):
            if a0 <= me < z0:
                return a0, z0
        return None
    months = [(ym, me) for ym, me in D.month_ends(199601) if me >= dates[0]]
    link, spsize = {}, {}
    for ym, me in months:
        i = bisect.bisect_right(dates, me) - 1
        if i < 0:
            continue
        sp = hist[i][1]
        spsize[ym] = len(sp)
        lo = (datetime.date.fromisoformat(me) - datetime.timedelta(days=456)).isoformat()
        hi = (datetime.date.fromisoformat(me) + datetime.timedelta(days=456)).isoformat()
        cands_for = collections.defaultdict(list)
        for cik, cl in claims.items():
            if cik in c_end and me >= c_end[cik]:
                continue
            before = [(d, st) for d, st in cl if lo <= d <= me]
            after = [(d, st) for d, st in cl if me < d <= hi]
            near_d, near = (before[-1] if before else (after[0] if after else (None, set())))
            for k in near & sp:
                cands_for[k].append((1, near_d, cik, 'L1_claim_near'))
            for k in (set().union(*[st for _, st in cl]) & sp) - near:
                S = span_of(k, me)
                if S:
                    ds = [d for d, st in cl if k in st and S[0] <= d < S[1]]
                    if ds:
                        cands_for[k].append((2, max(ds), cik, 'L2_claim_same_span'))
            if cik in cur_tk and cur_tk[cik] in sp and a_ok(cik, cur_tk[cik], me):
                cands_for[cur_tk[cik]].append((3, '', cik, 'L3_current_ticker'))
            if before and cik in b_fts:
                for tk, a0, z0 in b_fts[cik]:
                    if tk in sp and a0 <= me < z0:
                        cands_for[tk].append((4, '', cik, 'L4_B_fts'))
            if before and cik in c_fts:
                for tk in c_fts[cik] & sp:
                    cands_for[tk].append((4, '', cik, 'L5_C_fts'))
        lk = {}
        for k, lst in cands_for.items():
            best = min(x[0] for x in lst)
            top = [x for x in lst if x[0] == best]
            if len({x[2] for x in top}) > 1:
                newest = max(x[1] for x in top)
                top2 = [x for x in top if x[1] == newest]
                if len({x[2] for x in top2}) > 1 or newest == '':
                    continue
                top = top2
            cik = top[0][2]
            if cik not in lk:
                lk[cik] = (k, top[0][3])
            else:  # 同じ会社が二つの記号で結ばれた（種類株）: 記号を足しておく
                lk[cik] = (lk[cik][0] + '|' + k, lk[cik][1])
        link[ym] = lk
    return link, spsize, cand


# ───────────────────────── 業種（French の12業種・今の SIC） ─────────────────────────
def ff12_map():
    b = N.get(N.FR.format('Siccodes12'), name='fr_Siccodes12.zip', max_age_days=365)
    z = zipfile.ZipFile(io.BytesIO(b))
    txt = z.read(z.namelist()[0]).decode('latin-1')
    rng, cur = [], None
    for line in txt.splitlines():
        m = re.match(r'^\s*(\d+)\s+(\S+)\s+', line)
        if m and not re.match(r'^\s*\d{4}-\d{4}', line):
            cur = int(m.group(1))
            continue
        m2 = re.match(r'^\s*(\d{4})-(\d{4})', line)
        if m2 and cur is not None:
            rng.append((int(m2.group(1)), int(m2.group(2)), cur))

    def f(sic):
        if sic is None:
            return 12
        for a, z_, k in rng:
            if a <= sic <= z_:
                return k
        return 12  # Other
    return f, rng


# ───────────────────────── 信号 ─────────────────────────
SIGS_HIGH = ['JAC', 'COS', 'JAC_ALL', 'COS_ALL', 'MINEDIT', 'SIMPLE', 'IT1A_COS', 'IT7_COS', 'EX13_JAC']  # 高い＝良い
SIGS_LOW = ['DNEG', 'NEGCHG', 'LEN']  # 低い＝良い
SIGS = SIGS_HIGH + SIGS_LOW
FAIL_FLAGS = ('fetch_err', 'no_main_in_txt', 'main_not_text', 'diff_err')


def fnum(x):
    if x is None or x == '' or x == 'None':
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def load_signals():
    rows = list(csv.DictReader(open(os.path.join(CACHE, 'nx_lazy_signals.csv'))))
    by_acc = {r['acc']: r for r in rows}
    stat = collections.Counter()
    per_cik = collections.defaultdict(list)     # 有効な信号（並べる月つき）
    annual = collections.defaultdict(list)      # 浮動株のための年次報告（すべて）
    for r in rows:
        cik = int(r['cik'])
        fl = r['flags'] or ''
        fail = any(x in fl for x in FAIL_FLAGS)
        annual[cik].append(r)
        stat['rows'] += 1
        if r['form'] not in D.FORMS_SIGNAL:
            stat['not_signal_form'] += 1
            continue
        if not r['prev_acc']:
            stat['no_prev'] += 1
            continue
        g = fnum(r['gap_days'])
        if g is None or not (270 <= g <= 456):
            stat['gap_out'] += 1
            continue
        pr = by_acc.get(r['prev_acc'])
        nw, pnw = fnum(r['n_words']), fnum(pr['n_words']) if pr else None
        if nw is None or nw < 1000 or pnw is None or pnw < 1000:
            stat['words_lt_1000_or_prev_missing'] += 1
            continue
        if fail or (pr and any(x in (pr['flags'] or '') for x in FAIL_FLAGS)):
            stat['fetch_fail_flag'] += 1
            continue
        if fnum(r['sim_jac']) is None or fnum(r['sim_cos']) is None:
            stat['no_similarity'] += 1
            continue
        v = {'JAC': fnum(r['sim_jac']), 'COS': fnum(r['sim_cos']), 'JAC_ALL': fnum(r['sim_jac_all']), 'COS_ALL': fnum(r['sim_cos_all']),
             'MINEDIT': fnum(r['sim_minedit']), 'SIMPLE': fnum(r['sim_simple']),
             'IT1A_COS': fnum(r['item1a_cos']), 'IT7_COS': fnum(r['item7_cos'])}
        ex = fnum(r['ex13_jac'])
        v['EX13_JAC'] = ex if ex is not None else v['JAC']  # どちらの年にも EX-13 が無ければ JAC と同じ
        ln, pln = fnum(r['lm_neg']), fnum(pr['lm_neg'])
        v['DNEG'] = (ln / nw - pln / pnw) if (ln is not None and pln is not None) else None
        wa, na = fnum(r['chg_words_added']), fnum(r['chg_neg_added'])
        v['NEGCHG'] = (na / wa) if (wa is not None and na is not None and wa >= 100) else None
        v['LEN'] = abs(math.log(nw / pnw))
        per_cik[cik].append({'acc': r['acc'], 'filed': r['filed'], 'f': int(r['formation_ym']), 'v': v,
                             'fs': r['format_switch'] == 'True', 'year': int(r['filed'][:4])})
        stat['valid'] += 1
    # 同じ CIK で 60 日以内の2件は先の1件だけ（提出日で測る）
    for cik, lst in per_cik.items():
        lst.sort(key=lambda x: x['filed'])
        keep, last = [], None
        for x in lst:
            if last and (datetime.date.fromisoformat(x['filed']) - datetime.date.fromisoformat(last)).days <= 60:
                stat['dropped_within_60d'] += 1
                continue
            keep.append(x)
            last = x['filed']
        per_cik[cik] = keep
    stat['valid_after_60d'] = sum(len(v) for v in per_cik.values())
    return per_cik, annual, by_acc, dict(stat), rows


# ───────────────────────── 浮動株 ─────────────────────────
def float_of(r):
    """(浮動株, 基準日, 出どころ)。出どころの順: XBRL → iXBRL → 本文。基準日: XBRL の end → 本文の日付 → 規則"""
    fx, fi, ft = fnum(r['float_xbrl']), fnum(r['float_ix']), fnum(r['float_text'])
    if fx and fx > 0:
        F, src = fx, 'xbrl'
    elif fi and fi > 0:
        F, src = fi, 'ix'
    elif ft and ft > 0:
        F, src = ft, 'text'
    else:
        return None
    if src == 'xbrl' and r['float_xbrl_end']:
        bd = r['float_xbrl_end']
    elif r['float_text_asof']:
        bd = r['float_text_asof']
    elif r['float_xbrl_end']:
        bd = r['float_xbrl_end']
    else:
        fd = datetime.date.fromisoformat(r['filed'])
        if r['filed'] < '2003-06-01':
            bd = (fd - datetime.timedelta(days=30)).isoformat()
        else:
            pd = datetime.date.fromisoformat(r['period']) if r['period'] else fd
            bd = D._minus_months(pd.isoformat(), 6)
    return F, ym_of(bd), src


# ───────────────────────── 組み立て ─────────────────────────
class Panel:
    pass


def build(log):
    P = Panel()
    t0 = time.time()
    link, spsize, cand = relink()
    mem_file = json.load(open(os.path.join(CACHE, 'nx_lazy_members.json')))
    # 再現の確かめ
    mism = 0
    how_mism = 0
    for ym, lst in mem_file['members'].items():
        a = set(lst)
        b = set(link.get(int(ym), {}).keys())
        if a != b:
            mism += 1
        for c, h in mem_file['how'][ym].items():
            if link.get(int(ym), {}).get(int(c), (None, None))[1] != h:
                how_mism += 1
    log['relink_check'] = {'months': len(mem_file['members']), 'months_with_different_cik_set': mism, 'cik_months_with_different_path': how_mism}
    print('relink', log['relink_check'], round(time.time() - t0, 1), 's', flush=True)
    per_cik, annual, by_acc, sstat, rows = load_signals()
    log['signal_validity'] = sstat
    P.per_cik, P.annual, P.rows = per_cik, annual, rows
    ciks = sorted(int(c) for c in cand)
    P.ciks = ciks
    P.idx = {c: i for i, c in enumerate(ciks)}
    P.cand = cand
    n = len(ciks)
    # 株価の記号（事前登録 price_mapping）
    P.dev_price = collections.Counter()

    ptk_fixed, is_c = {}, {}
    for c in ciks:
        v = cand[c]
        via = v['via']
        pt = v.get('price_tickers') or []
        c_only = ('C_predecessor_of_current' in via) and not ('A_current_member' in via or 'B_former_member_same_ticker_now' in via)
        if c_only:
            is_c[c] = set(pt)
            if 'D_fts_renamed_survivor' in via:
                P.dev_price['C_and_D_treated_as_C'] += 1
            continue
        if not pt:
            ptk_fixed[c] = None
            continue
        t = (v.get('tickers') or [pt[0]])[0] if 'A_current_member' in via else pt[0]
        if re.search(r'-P[A-Z]?$', t):
            # 今の SEC の記号が優先株だけ（普通株は上場廃止）→ 普通株の株価が無い
            ptk_fixed[c] = None
            P.dev_price['current_symbol_is_preferred_no_common_price'] += 1
            continue
        ptk_fixed[c] = t
    need = set(t for t in ptk_fixed.values() if t) | set(t for s in is_c.values() for t in s if not re.search(r'-P[A-Z]?$', t))
    need |= {'SPY', 'RSP'}
    print('Yahoo の記号', len(need), flush=True)
    px, missing = {}, []
    for k, t in enumerate(sorted(need)):
        try:
            d = yahoo_monthly(t)
        except RuntimeError as e:
            print('  取得失敗', t, e, flush=True)
            d = None
        if d:
            px[t] = d
        else:
            missing.append(t)
        if k % 100 == 0:
            print('  ', k, t, round(time.time() - t0), 's', flush=True)
    log['yahoo'] = {'tickers_requested': len(need), 'got': len(px), 'missing': sorted(missing), 'month_reading': dict(MONTH_CHECK)}
    P.px = px
    P.rets = {t: returns_of(d) for t, d in px.items()}
    # 月の格子
    months = ym_range(199601, END)
    P.months = months
    P.mi = {m: i for i, m in enumerate(months)}
    T = len(months)
    P.T, P.n = T, n
    member = np.zeros((T, n), bool)
    tick = [[None] * n for _ in range(T)]
    how = [[None] * n for _ in range(T)]
    for ym, lk in link.items():
        if ym not in P.mi:
            continue
        ti = P.mi[ym]
        for c, (k, h) in lk.items():
            i = P.idx.get(c)
            if i is None:
                continue
            member[ti, i] = True
            how[ti][i] = h
            if c in is_c:
                ks = [x for x in k.split('|') if x in is_c[c]]
                tick[ti][i] = ks[0] if ks else None
            else:
                tick[ti][i] = ptk_fixed.get(c)
    P.member, P.tick, P.how = member, tick, how
    # R[t, i] = 月 t のリターン（月末 t−1 の記号で）、CL[t, i] = 月末 t の終値（分割だけ調整）、ADJOK[t, i] = 月末 t の調整後終値があるか
    R = np.full((T, n), np.nan)
    CLprev = np.full((T, n), np.nan)
    ended = np.zeros((T, n), bool)   # 月末 t−1 の値はあるが、その記号の系列が t−1 で終わっている（t−1 < END）
    lastm = {t: max(d) for t, d in px.items()}
    for ti in range(1, T):
        for i in range(n):
            if not member[ti - 1, i]:
                continue
            t = tick[ti - 1][i]
            if not t or t not in px:
                continue
            m0, m1 = months[ti - 1], months[ti]
            p0 = px[t].get(m0)
            if p0 is None:
                continue
            CLprev[ti, i] = p0[1]
            r = P.rets[t].get(m1)
            if r is not None:
                R[ti, i] = r
            elif lastm[t] == m0 and m0 < END:
                ended[ti, i] = True
    P.R, P.CLprev, P.ended = R, CLprev, ended
    # 浮動株 → 月末 t−1 の時価（F × close_{t−1} ÷ close_{基準日の月末}）
    CAP = np.full((T, n), np.nan)
    fsrc = collections.Counter()
    ann = {}
    for c, lst in annual.items():
        L = []
        for r in sorted(lst, key=lambda x: x['filed']):
            fo = float_of(r)
            L.append((int(r['formation_ym']), fo))
        ann[c] = L
    for ti in range(1, T):
        m_prev = months[ti - 1]
        for i in range(n):
            if np.isnan(CLprev[ti, i]):
                continue
            c = ciks[i]
            t = tick[ti - 1][i]
            L = ann.get(c) or []
            fs = [x for x in L if x[0] <= m_prev]
            if not fs:
                continue
            tries = [fs[-1]] + ([fs[-2]] if len(fs) >= 2 else [])
            got = None
            for f_, fo in tries:
                if f_ < ym_add(m_prev, -24):
                    continue
                if not fo:
                    continue
                F, bm, src = fo
                pb = px[t].get(bm)
                if pb is None:
                    fsrc['base_month_close_missing'] += 1
                    continue
                got = F * CLprev[ti, i] / pb[1]
                fsrc[src + ('' if (f_, fo) == fs[-1] else '_prev')] += 1
                break
            if got is not None and got > 0:
                CAP[ti, i] = got
    P.CAP = CAP
    log['float_sources_stock_months'] = dict(fsrc)
    # 業種
    f12, rng = ff12_map()
    sic = {}
    for r in rows:
        try:
            sic[int(r['cik'])] = int(r['sic']) if r['sic'] else None
        except ValueError:
            sic[int(r['cik'])] = None
    P.ind = np.array([f12(sic.get(c)) for c in ciks])
    log['ff12_ranges'] = len(rng)
    print('panel built', round(time.time() - t0), 's', flush=True)
    return P


def signal_mats(P, delay=0, drop_fs=False):
    """SIG[name][t, i] = 月 t に使う信号（並べる月 f ∈ [t−12, t−1] の最新の有効な 10-K の値）、F[t, i] = その f"""
    T, n = P.T, P.n
    S = {s: np.full((T, n), np.nan) for s in SIGS}
    F = np.full((T, n), -1, dtype=np.int64)
    for c, lst in P.per_cik.items():
        i = P.idx.get(c)
        if i is None:
            continue
        L = [x for x in lst if not (drop_fs and x['fs'])]
        if not L:
            continue
        fs = [ym_add(x['f'], delay) for x in L]
        for ti in range(1, T):
            m = P.months[ti]
            lo, hi = ym_add(m, -12), ym_add(m, -1)
            j = bisect.bisect_right(fs, hi) - 1
            if j < 0 or fs[j] < lo:
                continue
            x = L[j]
            F[ti, i] = fs[j]
            for s in SIGS:
                v = x['v'].get(s)
                if v is not None:
                    S[s][ti, i] = v
    return S, F


# ───────────────────────── 規則 ─────────────────────────
def quintiles(score, ok):
    """score（高い＝良い）の五分位。境目は ok の会社の 20/40/60/80 パーセント点（numpy の線形補間）。境目ちょうどは下の五分位"""
    q = np.zeros(len(score), dtype=np.int8)
    vals = score[ok]
    if len(vals) < MIN_RANK:
        return None
    bps = np.percentile(vals, [20, 40, 60, 80])
    q[ok] = 1 + np.searchsorted(bps, score[ok], side='left')
    return q


def rank_month(P, spec, SIG, F, ti, U):
    """月 t の五分位（U の中で）。戻り値 dict(signal → q 配列 or None)。3か月の規則は q を f ∈ [t−3, t−1] に絞る"""
    m = P.months[ti]
    out = {}
    for s in spec['signals']:
        sign = -1.0 if s in SIGS_LOW else 1.0
        v = SIG[s][ti]
        ok = U & ~np.isnan(v)
        score = np.where(ok, sign * np.nan_to_num(v), -np.inf)
        if spec.get('industry'):
            q = np.zeros(P.n, dtype=np.int8)
            tot = 0
            for g in np.unique(P.ind[ok]):
                okg = ok & (P.ind == g)
                if okg.sum() < MIN_IND:
                    continue
                bps = np.percentile(score[okg], [20, 40, 60, 80])
                q[okg] = 1 + np.searchsorted(bps, score[okg], side='left')
                tot += okg.sum()
            if ok.sum() < MIN_RANK:
                q = None
        else:
            q = quintiles(score, ok)
        if q is not None and spec['window'] == 3:
            q = np.where(F[ti] >= ym_add(m, -3), q, 0).astype(np.int8)
        out[s] = (q, score, ok)
    return out


def weights(sel, cap, vw):
    if vw:
        w = np.where(sel, cap, 0.0)
    else:
        w = sel.astype(float)
    tot = w.sum()
    return w / tot if tot > 0 else None


def run(P, spec, SIG, F, start, drop=None, lb=False, trunc=False, keep_w=False):
    """1本の規則を月ごとに回す。戻り値: s, b（月次の小数）, to_s, to_b（片道の回転）, contrib（会社ごとの寄与）, info"""
    vw = spec['vw']
    kind = spec['kind']
    s_ret, b_ret, to_s, to_b = {}, {}, {}, {}
    contrib = np.zeros(P.n)
    prev_s = prev_b = None
    info = collections.Counter()
    q_hist = {} if keep_w else None
    for ti in range(P.mi[start], P.mi[END] + 1):
        m = P.months[ti]
        r = P.R[ti].copy()
        U = P.member[ti - 1] & ~np.isnan(r)
        if lb:
            E = P.ended[ti]
            U = U | E
            r = np.where(E, LB_HIT, r)
        if drop is not None:
            U[drop] = False
        if trunc:
            r = np.clip(r, -0.40, 1.00)
        cap = P.CAP[ti]
        base = U & ~np.isnan(cap) & (cap > 0) if vw else U
        if base.sum() == 0:
            continue
        rk = rank_month(P, spec, SIG, F, ti, U)
        rr = np.nan_to_num(r)
        wb = weights(base, np.nan_to_num(cap), vw)
        # 規則の保有
        q1 = rk[spec['signals'][0]][0]
        if kind == 'Q5':
            sel = base & (q1 == 5) if q1 is not None else None
            if sel is None or sel.sum() < MIN_HOLD:
                sel = base
                info['held_U'] += 1
            ws = weights(sel, np.nan_to_num(cap), vw)
            wbb = wb
        elif kind == 'XQ1':
            sel = base & ~(q1 == 1) if q1 is not None else base
            if q1 is None:
                info['held_U'] += 1
            ws = weights(sel, np.nan_to_num(cap), vw)
            wbb = wb
        elif kind == 'LS':
            if q1 is None:
                sel5 = sel1 = base
                info['held_U'] += 1
            else:
                sel5, sel1 = base & (q1 == 5), base & (q1 == 1)
                if sel5.sum() < MIN_HOLD:
                    sel5 = base; info['long_held_U'] += 1
                if sel1.sum() < MIN_HOLD:
                    sel1 = base; info['short_held_U'] += 1
            ws = weights(sel5, np.nan_to_num(cap), vw)
            wbb = weights(sel1, np.nan_to_num(cap), vw)
            if lb:  # 売り側の途切れは 0%（売りの儲けにしない）
                rr_b = np.where(P.ended[ti], 0.0, rr)
        elif kind == 'TOP30':
            score, ok = rk[spec['signals'][0]][1], rk[spec['signals'][0]][2]
            if q1 is None:
                sel = base
                info['held_U'] += 1
            else:
                idx = np.where(ok & base)[0]
                top = idx[np.argsort(-score[idx], kind='stable')[:30]]
                sel = np.zeros(P.n, bool)
                sel[top] = True
            ws = weights(sel, np.nan_to_num(cap), vw)
            wbb = wb
        elif kind == 'COMBO_A':  # JAC の Q1 か DNEG の Q1 に入る会社を外す
            qd = rk['DNEG'][0]
            out_ = np.zeros(P.n, bool)
            if q1 is not None:
                out_ |= (q1 == 1)
            if qd is not None:
                out_ |= (qd == 1)
            if q1 is None and qd is None:
                info['held_U'] += 1
            sel = base & ~out_
            ws = weights(sel, np.nan_to_num(cap), vw)
            wbb = wb
        elif kind == 'COMBO_B':  # JAC の Q5 のうち DNEG の Q1 でない会社
            qd = rk['DNEG'][0]
            if q1 is None:
                sel = base; info['held_U'] += 1
            else:
                sel = base & (q1 == 5)
                if qd is not None:
                    sel &= ~(qd == 1)
                if sel.sum() < MIN_HOLD:
                    sel = base; info['held_U'] += 1
            ws = weights(sel, np.nan_to_num(cap), vw)
            wbb = wb
        else:
            raise ValueError(kind)
        if ws is None or wbb is None:
            continue
        rb_vec = rr_b if (kind == 'LS' and lb) else rr
        s_ret[m] = float(ws @ rr)
        b_ret[m] = float(wbb @ rb_vec)
        contrib += (ws - wbb) * rr
        # 回転（前月の重みを当月の値動きで動かした後と比べる）
        for key, w, prev, dct in (('s', ws, prev_s, to_s), ('b', wbb, prev_b, to_b)):
            if prev is not None:
                dct[m] = 0.5 * float(np.abs(w - prev).sum())
        drift = lambda w, rv: (w * (1 + rv)) / max(1e-12, float((w * (1 + rv)).sum()))
        prev_s = drift(ws, rr)
        prev_b = drift(wbb, rb_vec)
        info['months'] += 1
        info['n_s_sum'] += int((ws > 0).sum())
        info['n_b_sum'] += int((wbb > 0).sum())
        if keep_w:
            q_hist[m] = q1
    return {'s': s_ret, 'b': b_ret, 'to_s': to_s, 'to_b': to_b, 'contrib': contrib, 'info': dict(info), 'q': q_hist}


# ───────────────────────── 規則の一覧（事前登録 families） ─────────────────────────
def rule_specs():
    R = []
    def add(name, fam, signals, kind, vw, window=12, industry=False, start=None, note=''):
        R.append({'name': name, 'family': fam, 'signals': signals, 'kind': kind, 'vw': vw, 'window': window,
                  'industry': industry, 'start_rule': start, 'note': note})
    # P（主の族）
    add('P1_JAC_Q5_VW_12', 'P', ['JAC'], 'Q5', True, 12)
    add('P2_JAC_XQ1_VW_12', 'P', ['JAC'], 'XQ1', True, 12)
    add('P3_COS_Q5_VW_12', 'P', ['COS'], 'Q5', True, 12)
    add('P4_COS_XQ1_VW_12', 'P', ['COS'], 'XQ1', True, 12)
    add('P5_JAC_Q5_VW_3', 'P', ['JAC'], 'Q5', True, 3)
    add('P6_JAC_XQ1_VW_3', 'P', ['JAC'], 'XQ1', True, 3)
    add('P7_COS_Q5_VW_3', 'P', ['COS'], 'Q5', True, 3)
    add('P8_COS_XQ1_VW_3', 'P', ['COS'], 'XQ1', True, 3)
    # X1 等分
    for nm, sg, kd, wn in (('JAC_Q5', 'JAC', 'Q5', 12), ('JAC_XQ1', 'JAC', 'XQ1', 12), ('COS_Q5', 'COS', 'Q5', 12), ('COS_XQ1', 'COS', 'XQ1', 12),
                           ('JAC_Q5', 'JAC', 'Q5', 3), ('JAC_XQ1', 'JAC', 'XQ1', 3), ('COS_Q5', 'COS', 'Q5', 3), ('COS_XQ1', 'COS', 'XQ1', 3)):
        add(f'X1_{nm}_EW_{wn}', 'X1', [sg], kd, False, wn)
    # X2 買い−売り
    for sg in ('JAC', 'COS'):
        for vw in (True, False):
            for wn in (12, 3):
                add(f'X2_{sg}_LS_{"VW" if vw else "EW"}_{wn}', 'X2', [sg], 'LS', vw, wn)
    # X3 ほかの物差し
    for sg in ('MINEDIT', 'SIMPLE', 'JAC_ALL', 'COS_ALL'):
        add(f'X3_{sg}_Q5_VW_12', 'X3', [sg], 'Q5', True, 12)
        add(f'X3_{sg}_XQ1_VW_12', 'X3', [sg], 'XQ1', True, 12)
    # X4 否定語
    for sg in ('DNEG', 'NEGCHG'):
        add(f'X4_{sg}_Q5_VW_12', 'X4', [sg], 'Q5', True, 12, note='q07leu の lmtext（dneg の五分位・等分・2001〜）と重なる族')
        add(f'X4_{sg}_XQ1_VW_12', 'X4', [sg], 'XQ1', True, 12, note='q07leu の lmtext（dneg の五分位・等分・2001〜）と重なる族')
    # X5 組み合わせ
    add('X5a_JACQ1_or_DNEGQ1_excluded_VW_12', 'X5', ['JAC', 'DNEG'], 'COMBO_A', True, 12)
    add('X5b_JACQ5_not_DNEGQ1_VW_12', 'X5', ['JAC', 'DNEG'], 'COMBO_B', True, 12)
    # X6 節
    add('X6_IT1A_COS_Q5_VW_12', 'X6', ['IT1A_COS'], 'Q5', True, 12, start='it1a')
    add('X6_IT1A_COS_XQ1_VW_12', 'X6', ['IT1A_COS'], 'XQ1', True, 12, start='it1a')
    add('X6_IT7_COS_Q5_VW_12', 'X6', ['IT7_COS'], 'Q5', True, 12)
    add('X6_IT7_COS_XQ1_VW_12', 'X6', ['IT7_COS'], 'XQ1', True, 12)
    # X7 業種の中
    add('X7_JAC_IND_Q5_VW_12', 'X7', ['JAC'], 'Q5', True, 12, industry=True)
    add('X7_JAC_IND_XQ1_VW_12', 'X7', ['JAC'], 'XQ1', True, 12, industry=True)
    # X8 EX-13
    add('X8_EX13_JAC_Q5_VW_12', 'X8', ['EX13_JAC'], 'Q5', True, 12)
    add('X8_EX13_JAC_XQ1_VW_12', 'X8', ['EX13_JAC'], 'XQ1', True, 12)
    # X9 長さ（対照）
    add('X9_LEN_Q5_VW_12', 'X9', ['LEN'], 'Q5', True, 12)
    add('X9_LEN_XQ1_VW_12', 'X9', ['LEN'], 'XQ1', True, 12)
    # X10 30社
    add('X10_JAC_TOP30_EW_12', 'X10', ['JAC'], 'TOP30', False, 12)
    add('X10_COS_TOP30_EW_12', 'X10', ['COS'], 'TOP30', False, 12)
    return R
