#!/usr/bin/env python3
"""night/nx_lazy.py — 角度 nx_lazy（10-K の本文が前年とどれだけ変わったか・Cohen-Malloy-Nguyen 2020『Lazy Prices』）の測定

事前登録: out/nx_lazy_prereg.json（測る前に commit 済み・書き換えない）。全体の線: out/nx_prereg.json（criteria_short_sample）。
データ: night/nx_lazy_data.py が作った out/_nx_cache/nx_lazy_members.json（月末ごとの構成の CIK）と
        out/_nx_cache/nx_lazy_signals.csv（10-K ごとの特徴量と並べる月）。株価はここで初めて Yahoo から取る。
出力: out/nx_lazy.json（tested に全50本・負けも。格付けは nx_common.grade_short）。
走らせ方: python3 night/nx_lazy.py（測定・約2分）→ python3 night/nx_lazy.py --post-hoc（事後の診断を post_hoc に足す・格付けに使わない）
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
from zoneinfo import ZoneInfo
NY = ZoneInfo('America/New_York')


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
        dny = datetime.datetime.fromtimestamp(t, NY)  # ニューヨーク時間（夏時間込み）で読んだ月
        if ym <= END:
            MONTH_CHECK['bars'] += 1
            if d.day != 1:
                MONTH_CHECK['bar_not_on_day1_utc'] += 1
            if dny.year * 100 + dny.month != ym:
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
FLOAT_FIX = collections.Counter()
FLOAT_RANGE = (1e6, 1e13)   # nx_lazy_data.cover_float が本文の値に掛けている範囲（100万〜10兆ドル）を、XBRL・iXBRL の値にも同じく掛ける


def _scale_error(tag, txt):
    """XBRL/iXBRL の値と本文の値の比が 1000 の整数乗（×1000・×100万…）から 2.5 倍以内＝単位（scale）の付け違い"""
    if not (tag and txt):
        return False
    l = math.log10(tag / txt)
    k = round(l / 3)
    return k != 0 and abs(l - 3 * k) < math.log10(2.5)


def float_of(r):
    """(浮動株, 基準日, 出どころ)。出どころの順: XBRL → iXBRL → 本文。基準日: XBRL の end → 本文の日付 → 規則。
    検問（事前登録に無い・株価と成績を見る前に、U の時価加重と SPY の相関 0.706 の原因として決めた）:
      (a) どの出どころも 100万〜10兆ドルの外なら欠測（本文の値に取得器が掛けていた範囲を XBRL・iXBRL にも掛ける）
      (b) XBRL（無ければ iXBRL）の値と本文の値の比が 1000 の整数乗から 2.5 倍以内なら、タグの単位の付け違いとみて本文の値を使う"""
    lo, hi = FLOAT_RANGE
    fx, fi, ft = fnum(r['float_xbrl']), fnum(r['float_ix']), fnum(r['float_text'])
    for nm, v in (('xbrl', fx), ('ix', fi), ('text', ft)):
        if v is not None and v > 0 and not (lo <= v <= hi):
            FLOAT_FIX[f'{nm}_out_of_range_dropped'] += 1
    fx = fx if (fx and lo <= fx <= hi) else None
    fi = fi if (fi and lo <= fi <= hi) else None
    ft = ft if (ft and lo <= ft <= hi) else None
    if fx and _scale_error(fx, ft):
        FLOAT_FIX['xbrl_scale_error_used_text'] += 1
        fx = fi = None
    elif not fx and fi and _scale_error(fi, ft):
        FLOAT_FIX['ix_scale_error_used_text'] += 1
        fi = None
    if fx:
        F, src = fx, 'xbrl'
    elif fi:
        F, src = fi, 'ix'
    elif ft:
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
    mc = {'bars': 0, 'bar_not_on_day1_utc': 0, 'month_differs_in_new_york': 0, 'duplicate_month': 0}
    mc.update(MONTH_CHECK)
    log['yahoo'] = {'tickers_requested': len(need), 'got': len(px), 'missing': sorted(missing), 'month_reading': mc,
                    'month_reading_note': 'Yahoo の月足の時刻は各月1日 00:00（ニューヨーク時間）＝ UTC 04:00/05:00。UTC で読んでもニューヨーク時間で読んでも同じ月（食い違い 0）。2026-09 の途中の足は END=202608 で切った'}
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
    P.spsize = spsize
    P.link_counts, P.conflicts = mem_file.get('link_counts'), mem_file.get('ticker_conflicts_dropped')
    P.is_c = is_c
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
    # (c) 時系列の検問: 浮動株 ÷ 基準日の終値（分割だけ調整）＝株数に当たる値が、同じ会社の前後3年の他の年次報告の中央値と
    #     1000 の整数乗から 2.5 倍以内だけずれていたら、単位の付け違い（本文が千ドル単位の表を $ で読んだ等）とみて欠測にする
    #     （事前登録の『無ければその前の年次報告の値（24か月以内）』の道へ回す）
    tk_of = {}
    for i in range(n):
        cnt = collections.Counter(tick[ti][i] for ti in range(T) if tick[ti][i])
        if cnt:
            tk_of[ciks[i]] = cnt.most_common(1)[0][0]
    for c, L in ann.items():
        t = tk_of.get(c)
        if not t or t not in px:
            continue
        sh = []
        for j, (f_, fo) in enumerate(L):
            pb = px[t].get(fo[1]) if fo else None
            sh.append(fo[0] / pb[1] if (fo and pb) else None)
        newL = list(L)
        for j, (f_, fo) in enumerate(L):
            if sh[j] is None:
                continue
            ref = [sh[k] for k in range(len(L)) if k != j and sh[k] is not None and abs((L[k][0] // 100) - (f_ // 100)) <= 3]
            if not ref:
                continue
            med = float(np.median(ref))
            if _scale_error(sh[j], med):
                FLOAT_FIX['time_series_scale_error_dropped'] += 1
                newL[j] = (f_, None)
                continue
            # (d) 1年だけの飛び: 前後の年次報告の株数に当たる値がたがいに2倍以内で一致しているのに、この報告だけ両方から5倍を超えて離れている
            pj = next((sh[k] for k in range(j - 1, -1, -1) if sh[k] is not None), None)
            nj = next((sh[k] for k in range(j + 1, len(L)) if sh[k] is not None), None)
            if pj and nj and max(pj, nj) / min(pj, nj) <= 2 and min(sh[j] / pj, pj / sh[j]) < 0.2 and min(sh[j] / nj, nj / sh[j]) < 0.2:
                FLOAT_FIX['one_year_spike_dropped'] += 1
                newL[j] = (f_, None)
        ann[c] = newL
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
    P.ann = ann
    log['float_sources_stock_months'] = dict(fsrc)
    log['float_checks_reports'] = dict(FLOAT_FIX)
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
        if lb:
            info['lb_hit_s'] += int(((ws > 0) & P.ended[ti]).sum())
            info['lb_hit_b'] += int(((wbb > 0) & P.ended[ti]).sum())
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


# ───────────────────────── 統計（丸める前の差で勝ちを数える） ─────────────────────────
def rolling_u(s, b, years=20, start_month=7):
    """nx_common.rolling と同じ窓（毎年7月起点・一括）。勝ちは丸める前の差で数える（丸めた差が 0.00 になる窓を負けにしない）"""
    ks = sorted(set(s) & set(b))
    if not ks:
        return None
    out = []
    for y in range(ks[0] // 100, 2100):
        a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, (gs - gb) * 100))
    if not out:
        return None
    v = sorted(c for _, c in out)
    wins = sum(1 for _, c in out if c > 0)
    return {'windows': len(out), 'wins': wins, 'win_rate': round(wins / len(out), 3), 'median': round(v[len(v) // 2], 2),
            'worst': [out[min(range(len(out)), key=lambda i: out[i][1])][0], round(min(v), 2)],
            'best': [out[max(range(len(out)), key=lambda i: out[i][1])][0], round(max(v), 2)],
            'by_start_year': [[y, round(c, 3)] for y, c in out]}


def dca_u(s, b, years=20, step=12):
    ks = sorted(set(s) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append((w[0], ws / wb))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': round(v[len(v) // 2], 4),
            'worst': [min(out, key=lambda x: x[1])[0], round(min(v), 4)], 'best': [max(out, key=lambda x: x[1])[0], round(max(v), 4)],
            'by_start': [[a, round(r, 4)] for a, r in out]}


def ex(s, b, a=None, z=None, months=None):
    if months is not None:
        s = {k: v for k, v in s.items() if k in months}
    return N.excess_stats(s, b, a, z)


def sub_months(ms, drop_years):
    return {m for m in ms if m // 100 not in drop_years}


def cost_series(res, kind, c):
    s = {m: v - res['to_s'].get(m, 0.0) * c for m, v in res['s'].items()}
    if kind == 'LS':
        b = {m: v + res['to_b'].get(m, 0.0) * c + BORROW / 12 for m, v in res['b'].items()}
    else:
        b = dict(res['b'])
    return s, b


def compact(e):
    return None if e is None else {k: e[k] for k in ('from', 'to', 'years', 'ex_ann', 't', 'p', 'cagr_diff', 'te', 'beta')}


# ───────────────────────── 本体 ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='規則の名前（カンマ区切り）。試しだけ')
    a = ap.parse_args()
    t0 = time.time()
    pre = json.load(open(PRE))
    log = {}
    P = build(log)
    SIG, F = signal_mats(P)
    print('signals', round(time.time() - t0), 's', flush=True)
    ff = N.ff_factors()
    rf, mkt = ff['rf'], ff['mkt']
    spy = returns_of(P.px['SPY']) if 'SPY' in P.px else {}
    rsp = returns_of(P.px['RSP']) if 'RSP' in P.px else {}

    # 始まりの月（JAC の 12か月の信号が U に 50社以上そろう最初の7月）
    def first_july(sig, frm=FULL_START0):
        for m in P.months:
            if m < frm or m % 100 != 7:
                continue
            ti = P.mi[m]
            U = P.member[ti - 1] & ~np.isnan(P.R[ti])
            if (U & ~np.isnan(SIG[sig][ti])).sum() >= MIN_RANK:
                return m, int((U & ~np.isnan(SIG[sig][ti])).sum())
        return None, 0
    FULL_START, n0 = first_july('JAC')
    IT1A_START, n1 = first_july('IT1A_COS')
    log['start'] = {'full_start': FULL_START, 'jac_ranked_at_start': n0, 'it1a_start': IT1A_START, 'it1a_ranked_at_start': n1,
                    'why': '事前登録 criteria.full: 12か月の窓に信号が50社以上そろう最初の7月（1997-07 で足りればそのまま）。IT1A は Item 1A の信号が50社以上そろう最初の7月'}
    print('start', log['start'], flush=True)

    specs = rule_specs()
    if a.only:
        specs = [s for s in specs if s['name'] in a.only.split(',')]
    SIGd, Fd = signal_mats(P, delay=1)
    SIGf, Ff = signal_mats(P, drop_fs=True)
    results = []
    for sp in specs:
        st = IT1A_START if sp['start_rule'] == 'it1a' else FULL_START
        kind = sp['kind']
        res = run(P, sp, SIG, F, st)
        s, b = res['s'], res['b']
        ms = sorted(set(s) & set(b))
        e_full = ex(s, b, st, END)
        e_train = ex(s, b, st, N.TRAIN_END)
        e_hold = ex(s, b, N.HOLD_START, END)
        e_h1 = ex(s, b, st, FIRST_HALF_END)
        e_h2 = ex(s, b, SECOND_HALF_START, END)
        sc, bc = cost_series(res, kind, COST)
        sc2, bc2 = cost_series(res, kind, COST_HI)
        e_cost_full, e_cost_train, e_cost_hold = ex(sc, bc, st, END), ex(sc, bc, st, N.TRAIN_END), ex(sc, bc, N.HOLD_START, END)
        # 最大寄与の1社を除く
        top = int(np.argmax(res['contrib']))
        res_d = run(P, sp, SIG, F, st, drop=top)
        e_drop = ex(res_d['s'], res_d['b'], st, END)
        # 下限版
        res_lb = run(P, sp, SIG, F, st, lb=True)
        e_lb = ex(res_lb['s'], res_lb['b'], st, END)
        # 報告のみの感度
        res_tr = run(P, sp, SIG, F, st, trunc=True)
        res_dl = run(P, sp, SIGd, Fd, st)
        res_fs = run(P, sp, SIGf, Ff, st)
        # 族の格付けのための片側 p は下で Holm
        tk = next((P.tick[ti][top] for ti in range(P.T - 1, -1, -1) if P.tick[ti][top]), None)
        roll = rolling_u(s, b, 20)
        dcar = dca_u(s, b, 20)
        units = {'out_of_paper_2015_01': ex(s, b, 201501, END), 'post_ssrn_2017_01': ex(s, b, 201701, END), 'post_jf_2020_07': ex(s, b, 202007, END)}
        sens = {
            'formation_delayed_1m': compact(ex(res_dl['s'], res_dl['b'], st, END)),
            'cost_0.25pct_full': compact(ex(sc2, bc2, st, END)),
            'returns_truncated_-40_+100': compact(ex(res_tr['s'], res_tr['b'], st, END)),
            'excl_2000_2002_2008_2009': compact(ex(s, b, st, END, months=sub_months(ms, {2000, 2001, 2002, 2008, 2009}))),
            'period_1997_07_2014_12': compact(ex(s, b, st, 201412)),
            'period_2015_01_end': compact(units['out_of_paper_2015_01']),
            'period_2017_01_end': compact(units['post_ssrn_2017_01']),
            'period_2020_07_end': compact(units['post_jf_2020_07']),
            'no_format_switch_signals': compact(ex(res_fs['s'], res_fs['b'], st, END)),
            'start_2001_07': compact(ex(s, b, 200107, END)),
            'recent_2013_07_end': compact(ex(s, b, N.RECENT_START, END)),
        }
        if kind == 'LS':
            pass
        elif sp['vw']:
            sens['vs_SPY'] = compact(ex(s, spy, st, END))
            sens['vs_French_Mkt'] = compact(ex(s, mkt, st, END))
            sens['benchmark_U_vw_vs_SPY'] = compact(ex(b, spy, st, END))
        else:
            sens['vs_RSP_2003_05'] = compact(ex(s, rsp, 200305, END))
            sens['benchmark_U_ew_vs_RSP'] = compact(ex(b, rsp, 200305, END))
        months_n = res['info'].get('months', 0) or 1
        r = {'rule': sp['name'], 'family': sp['family'], 'spec': {k: sp[k] for k in ('signals', 'kind', 'vw', 'window', 'industry')},
             'role': 'primary' if sp['family'] == 'P' else 'exploratory',
             'note': sp['note'], 'start': st, 'end': END,
             'full': e_full, 'train': e_train, 'hold': e_hold, 'first_half': e_h1, 'second_half': e_h2,
             'cost_0.10pct': {'full': e_cost_full, 'train': e_cost_train, 'hold': e_cost_hold,
                              'turnover_oneway_annual_rule': round(12 * S_mean(res['to_s']), 3),
                              'turnover_oneway_annual_other_side' if kind == 'LS' else 'turnover_oneway_annual_benchmark_not_charged': round(12 * S_mean(res['to_b']), 3)},
             'drop_top': {'cik': P.ciks[top], 'name': P.cand[P.ciks[top]].get('name'), 'ticker': tk,
                          'contrib_sum': round(float(res['contrib'][top]), 4), 'full': e_drop},
             'lower_bound_-30pct': {'full': e_lb, 'stock_months_hit_in_rule': res_lb['info'].get('lb_hit_s', 0),
                                    'stock_months_hit_in_other': res_lb['info'].get('lb_hit_b', 0)},
             'roll20_lump_sum': roll, 'dca20_ratio': dcar,
             'maxdd': {'rule': round(N.maxdd({k: s[k] for k in ms}) * 100, 1), 'benchmark': round(N.maxdd({k: b[k] for k in ms}) * 100, 1)},
             'sharpe': {p: {'rule': N.sharpe(s, rf, a_, z_), 'benchmark': N.sharpe(b, rf, a_, z_)}
                        for p, (a_, z_) in {'train': (st, N.TRAIN_END), 'hold': (N.HOLD_START, END), 'full': (st, END)}.items()},
             'independent_units_report': {k: compact(v) for k, v in units.items()},
             'report_only_sensitivities': sens,
             'holdings': {'avg_rule': round(res['info'].get('n_s_sum', 0) / months_n, 1), 'avg_other': round(res['info'].get('n_b_sum', 0) / months_n, 1),
                          'months': res['info'].get('months'), 'months_rule_held_U': res['info'].get('held_U', 0),
                          'months_long_side_held_U': res['info'].get('long_held_U', 0), 'months_short_side_held_U': res['info'].get('short_held_U', 0)}}
        r['_series'] = (s, b)
        results.append(r)
        print(f"{sp['name']:36s} full {e_full['ex_ann'] if e_full else None} t {e_full['t'] if e_full else None} hold {e_hold['ex_ann'] if e_hold else None} "
              f"cost {e_cost_full['cagr_diff'] if e_cost_full else None} drop {e_drop['cagr_diff'] if e_drop else None} lb {e_lb['cagr_diff'] if e_lb else None} "
              f"({round(time.time() - t0)}s)", flush=True)
    # 族ごとの Holm と格付け
    fams = collections.defaultdict(list)
    for r in results:
        fams[r['family']].append(r)
    for fam, lst in fams.items():
        p1 = {r['rule']: N.p_one(r['full']['t']) if r['full'] and r['full']['t'] is not None else None for r in lst}
        h1 = N.holm(p1)
        p2 = {r['rule']: (r['hold']['p'] if r['hold'] else None) for r in lst}
        h2 = N.holm(p2)
        for r in lst:
            g, c = N.grade_short(r['full'], r['first_half'], r['second_half'], r['drop_top']['full'], r['cost_0.10pct']['full'],
                                 r['lower_bound_-30pct']['full'], h1.get(r['rule']))
            r['family_holm_p_one_full'] = h1.get(r['rule'])
            r['grade'] = g
            r['criteria_short_sample'] = c
            u = r['independent_units_report']
            repl = {'regions': 3, 'positive': sum(1 for v in u.values() if v and v['ex_ann'] > 0 and v['cagr_diff'] > 0)}
            gl, cl = N.grade(r['full'], r['train'], r['hold'], r['roll20_lump_sum'], r['cost_0.10pct']['hold'], repl, h2.get(r['rule']))
            r['C1_C8_long_history_reference'] = {'grade_if_long_history': gl, 'criteria': cl, 'family_holm_p_hold_two_sided': h2.get(r['rule']),
                                                 'C5_units': '2015-01〜・2017-01〜・2020-07〜（重なっている＝独立ではない・参考）',
                                                 'note': '参考。この角度は事前登録で criteria_short_sample（grade_short）を使うと決めた。C4 は丸める前の差で勝ちを数えた'}
    log['elapsed_s_rules'] = round(time.time() - t0)
    return P, SIG, F, results, log, (FULL_START, IT1A_START), (rf, mkt, spy, rsp), pre


def S_mean(d):
    v = list(d.values())
    return sum(v) / len(v) if v else 0.0


# ───────────────────────── 測る前の点検（事前登録 sanity_checks_before_results） ─────────────────────────
KNOWN = [('AutoNation', 350698, '2003-02〜2017-07 だけ構成'), ('Applied Industrial', 109563, '一度も入らない'),
         ('Google Inc.', 1288776, '2006-04〜2016-01'), ('AT&T (旧SBC)', 732717, '1996-01〜'), ('Elevance', 1156039, '2002-07〜'),
         ('Meta', 1326801, '2013-12〜'), ('Lumen', 18926, '1999-03〜2023-02'), ('Visa', 1403161, '2009-12〜'), ('Qwest', 1037949, '2000-07〜2011-03（株価は引けない）')]


def bench_series(P, start, vw=True):
    out = {}
    for ti in range(P.mi[start], P.mi[END] + 1):
        r = P.R[ti]
        U = P.member[ti - 1] & ~np.isnan(r)
        if vw:
            U = U & ~np.isnan(P.CAP[ti])
            w = np.where(U, np.nan_to_num(P.CAP[ti]), 0.0)
        else:
            w = U.astype(float)
        if w.sum() > 0:
            out[P.months[ti]] = float((w / w.sum()) @ np.nan_to_num(r))
    return out


def sanity(P, SIG, F, start, spy, mkt, log):
    out = {}
    # 1 被覆（毎年6月末の構成 → 7月の保有）
    cov = {}
    for m in P.months:
        if m % 100 != 6 or m < 199606:
            continue
        ti = P.mi[m]
        if ti + 1 >= P.T:
            continue
        tn = ti + 1
        mem = P.member[ti]
        U = mem & ~np.isnan(P.R[tn])
        Uvw = U & ~np.isnan(P.CAP[tn])
        sig = U & ~np.isnan(SIG['JAC'][tn])
        # 浮動株の無い会社の時価の近似（年齢を問わず最新の浮動株を終値で転がす）で、時価加重の重みの被覆を見積もる
        approx, nofloat = 0.0, 0
        for i in np.where(U & ~Uvw)[0]:
            L = [x for x in (P.ann.get(P.ciks[i]) or []) if x[0] <= m and x[1]]
            if not L:
                nofloat += 1
                continue
            Fv, bm, _ = L[-1][1]
            t = P.tick[ti][i]
            pb = P.px.get(t, {}).get(bm) if t else None
            approx += Fv * (P.CLprev[tn, i] / pb[1] if pb else 1.0)
        capsum = float(np.nansum(np.where(Uvw, P.CAP[tn], 0)))
        cov[m] = {'sp_members': P.spsize.get(m), 'linked_ciks': int(mem.sum()), 'priced': int(U.sum()),
                  'priced_share_of_sp': round(U.sum() / P.spsize.get(m, 1), 3), 'with_float_vw': int(Uvw.sum()),
                  'float_count_share_of_priced': round(Uvw.sum() / max(1, U.sum()), 3),
                  'float_weight_share_of_priced_approx': round(capsum / (capsum + approx), 3) if capsum else None,
                  'priced_without_any_float': nofloat, 'with_jac_signal_12m': int(sig.sum()),
                  'vw_cap_sum_bn_usd': round(capsum / 1e9, 1)}
    out['coverage_june'] = cov
    out['link_paths_cik_months'] = P.link_counts
    out['ticker_conflicts_dropped'] = P.conflicts
    out['relink_check'] = log.get('relink_check')
    # C（前身）の株価
    cm = cp = 0
    for ti in range(P.T):
        for i in np.where(P.member[ti])[0]:
            if P.ciks[i] in P.is_c:
                cm += 1
                if P.tick[ti][i]:
                    cp += 1
    out['C_predecessor_cik_months'] = {'linked': cm, 'with_successor_price_ticker': cp}
    # 2 同定の既知の例
    ident = {}
    for nm, c, exp in KNOWN:
        i = P.idx.get(c)
        if i is None:
            ident[nm] = {'expected': exp, 'got': '候補に無い'}
            continue
        ms = [P.months[ti] for ti in range(P.T) if P.member[ti, i]]
        spells, cur = [], None
        for m in ms:
            if cur and ym_add(cur[1], 1) == m:
                cur[1] = m
            else:
                if cur:
                    spells.append(cur)
                cur = [m, m]
        if cur:
            spells.append(cur)
        priced = sum(1 for ti in range(1, P.T) if P.member[ti - 1, i] and not np.isnan(P.R[ti, i]))
        ident[nm] = {'expected': exp, 'spells': spells, 'priced_months': priced}
    out['identity_examples'] = ident
    # 3 相手（U の時価加重）と SPY
    bv, be = bench_series(P, start, True), bench_series(P, start, False)
    ks = sorted(set(bv) & set(spy))
    out['benchmark_vs_SPY'] = {'corr_monthly': round(N.corr([bv[k] for k in ks], [spy[k] for k in ks]), 4),
                               'U_vw_minus_SPY': N.excess_stats(bv, spy, start, END),
                               'U_vw_minus_French_Mkt': N.excess_stats(bv, mkt, start, END),
                               'U_ew_minus_SPY': N.excess_stats(be, spy, start, END),
                               'by_period_U_vw_minus_SPY': {p: compact(N.excess_stats(bv, spy, a_, z_)) for p, (a_, z_) in
                                                           {'1997_07_2006_12': (start, 200612), '2007_01_2016_12': (200701, 201612), '2017_01_end': (201701, END)}.items()},
                               'note': '差は『生き残りの偏り（株価の取れる現存の会社だけ）と同定の誤り・浮動株の近似』の大きさ。相関 0.97 未満なら原因を書く'}
    # 4 信号（年ごと）
    by_year = collections.defaultdict(lambda: collections.defaultdict(list))
    fs_year = collections.Counter(); n_year = collections.Counter()
    for c, lst in P.per_cik.items():
        for x in lst:
            y = x['year']
            n_year[y] += 1
            fs_year[y] += x['fs']
            for s_ in SIGS:
                v = x['v'].get(s_)
                if v is not None:
                    by_year[y][s_].append(v)
    out['signals_by_filing_year'] = {y: {'valid_signals': n_year[y], 'format_switch_share': round(fs_year[y] / n_year[y], 3),
                                         'median': {s_: round(float(np.median(v)), 4) for s_, v in by_year[y].items()},
                                         'count': {s_: len(v) for s_, v in by_year[y].items()}} for y in sorted(n_year)}
    # 五分位ごとの社数・恒等式・大きな動き・様式の切り替わり（JAC・12か月・U の中）
    qcnt = collections.defaultdict(lambda: np.zeros(6))
    ident_dev = 0.0
    big = []
    bigcnt = collections.Counter()
    fsq = collections.defaultdict(lambda: [0, 0])
    fs_of = {}
    for c, lst in P.per_cik.items():
        for x in lst:
            fs_of[(P.idx.get(c), x['f'])] = x['fs']
    for ti in range(P.mi[start], P.mi[END] + 1):
        m = P.months[ti]
        r = P.R[ti]
        U = P.member[ti - 1] & ~np.isnan(r)
        v = SIG['JAC'][ti]
        ok = U & ~np.isnan(v)
        q = quintiles(np.where(ok, np.nan_to_num(v), -np.inf), ok)
        if q is None:
            continue
        for k in range(1, 6):
            qcnt[m // 100][k] += (q == k).sum()
        qcnt[m // 100][0] += 1
        Uvw = U & ~np.isnan(P.CAP[ti])
        capU = np.nansum(np.where(Uvw, P.CAP[ti], 0))
        cx = np.nansum(np.where(Uvw & ~(q == 1), P.CAP[ti], 0)) + np.nansum(np.where(Uvw & (q == 1), P.CAP[ti], 0))
        ident_dev = max(ident_dev, abs(cx - capU) / capU)
        for i in np.where(U)[0]:
            rv = r[i]
            grp = 'Q1' if q[i] == 1 else ('Q5' if q[i] == 5 else ('unranked' if q[i] == 0 else 'Q2_4'))
            if rv < -0.40 or rv > 1.00:
                bigcnt[grp] += 1
                big.append((abs(rv), P.tick[ti - 1][i], P.ciks[i], m, round(float(rv), 4), grp))
            if q[i] > 0:
                key = (i, int(F[ti, i]))
                fsq[int(q[i])][0] += 1
                fsq[int(q[i])][1] += bool(fs_of.get(key, False))
    out['quintile_counts_avg_per_month_JAC12'] = {y: [round(float(a[k] / a[0]), 1) for k in range(1, 6)] for y, a in sorted(qcnt.items())}
    out['identity_XQ1_plus_Q1_equals_U_vw_max_rel_dev'] = ident_dev
    big.sort(reverse=True)
    out['extreme_stock_months_lt_-40_or_gt_+100'] = {'count_by_group': dict(bigcnt),
                                                     'top50': [{'ticker': b_[1], 'cik': b_[2], 'month': b_[3], 'ret': b_[4], 'group_JAC12': b_[5]} for b_ in big[:50]]}
    out['format_switch_share_by_quintile_JAC12'] = {q: round(v[1] / v[0], 4) if v[0] else None for q, v in sorted(fsq.items())}
    # 6 取得の失敗の印（提出年ごと）
    fl = collections.defaultdict(collections.Counter)
    for r in P.rows:
        for f in (r['flags'] or '').split('|'):
            if f:
                fl[int(r['filed'][:4])][f] += 1
    out['flags_by_filing_year'] = {y: dict(c) for y, c in sorted(fl.items())}
    # 途切れた系列
    out['series_ended_stock_months_in_sample'] = int(sum(P.ended[ti].sum() for ti in range(P.mi[start], P.mi[END] + 1)))
    return out, bv, be


# ───────────────────────── 事前登録の外の報告（格付けに使わない）: 五分位ごとの成績 ─────────────────────────
def quintile_table(P, SIG, F, start, sig='JAC', vw=True):
    """各五分位（12か月・U の中の境目）を時価加重（または等分）で持った月次 − U の時価加重（等分）。単調かを見る（報告のみ）"""
    qs = {k: {} for k in range(1, 6)}
    bb = {}
    sign = -1.0 if sig in SIGS_LOW else 1.0
    for ti in range(P.mi[start], P.mi[END] + 1):
        m = P.months[ti]
        r = P.R[ti]
        U = P.member[ti - 1] & ~np.isnan(r)
        cap = P.CAP[ti]
        base = U & ~np.isnan(cap) if vw else U
        v = SIG[sig][ti]
        ok = U & ~np.isnan(v)
        q = quintiles(np.where(ok, sign * np.nan_to_num(v), -np.inf), ok)
        wb = weights(base, np.nan_to_num(cap), vw)
        if q is None or wb is None:
            continue
        rr = np.nan_to_num(r)
        bb[m] = float(wb @ rr)
        for k in range(1, 6):
            w = weights(base & (q == k), np.nan_to_num(cap), vw)
            if w is not None:
                qs[k][m] = float(w @ rr)
    out = {}
    for k in range(1, 6):
        out[f'Q{k}'] = {p: compact(N.excess_stats(qs[k], bb, a_, z_)) for p, (a_, z_) in
                        {'full': (start, END), 'train': (start, N.TRAIN_END), 'hold': (N.HOLD_START, END),
                         'first_half': (start, FIRST_HALF_END), 'second_half': (SECOND_HALF_START, END), 'post_2015': (201501, END)}.items()}
    return out


DEVIATIONS = [
    {'what': '浮動株の検問を足した（(a) XBRL・iXBRL の値にも 100万〜10兆ドルの範囲 ／ (b) XBRL（無ければ iXBRL）と本文の比が 1000 の整数乗から 2.5 倍以内なら本文 ／ (c) 株数に当たる値（浮動株÷基準日の終値）が同じ会社の前後3年の中央値から 1000 の整数乗だけずれたら欠測 ／ (d) 前後の報告が2倍以内で一致しているのに1年だけ両方から5倍を超えて離れたら欠測。(c)(d) の欠測は事前登録の『その前の年次報告（24か月以内）』の道へ回す）',
     'why': '事前登録の点検『U_t の時価加重と SPY の相関（0.97 未満なら浮動株か同定に誤り）』が 0.706 だった。原因は XBRL の dei:EntityPublicFloat の単位の付け違い（MTB・ZBH・HST・PKG・NEM・IQV・QCOM は ×100万、WAT・DPZ・GRMN・SHW・TKO・HBAN は ×1000、ALB は 1e18）で、1社が U の重みの 99% を持つ月があった。本文の値には取得器が 100万〜10兆ドルの範囲を掛けていたが XBRL・iXBRL の値には掛けていなかった。(c)(d) は本文の千ドル単位の表を $ として読んだ年（PEP・BAC・DUK ほか）と1年だけの飛び（EXC 2009 ほか）。検問は浮動株の値と相手の相関だけを見て決め、規則の成績は1つも計算する前。検問後の相関 0.9933',
     'affects_grading': '時価加重の規則すべて（主の族 P を含む）の重み。規則の中身・線は不変'},
    {'what': '株価の記号: 今の SEC の記号が優先株だけの会社（811830 Santander Holdings USA〔旧 Sovereign〕・1527469 Athene）は普通株の株価が無いとして外した。EIDP（旧 DuPont・C と D の両方）は C の約束（その月の記号 k が後継の記号なら k の株価）で扱った',
     'why': '事前登録は A・B・D に『今の SEC の記号』を当てるが、優先株の値動きを普通株の代わりに使うのは誤り', 'affects_grading': '小さい（3社）'},
    {'what': 'C（前身）の株価の記号は、その月に構成表と結んだ記号 k が後継の記号のどれかなら k そのもの（GOOGL/GOOG のような種類株を取り違えない）', 'why': '事前登録『C は後継の記号を、その月の前身の自分の記号が後継の記号と同じとき』の最も近い形', 'affects_grading': '無し〜小さい'},
    {'what': '浮動株の『無ければその前の年次報告の値（24か月以内）』の 24か月の制限を、最新の年次報告にも掛けた（並べる月が t−1 の24か月より前の報告の浮動株は使わない）', 'why': '構成に居るのに2年以上年次報告が無い会社の古い浮動株で重みを作らないため', 'affects_grading': '小さい'},
    {'what': '同じ CIK で『並べる月が 60 日以内の2件』は提出日の差で測った', 'why': '並べる月は月の単位なので、日数は提出日で測るのが最も近い', 'affects_grading': '無し（該当 0 件）'},
    {'what': '下限版（途切れた次の月に −30%）: 株価のある会社で、標本の終わりより前に系列が途切れたものが 0 件だった（Yahoo は今ある記号の履歴しか返さない）。したがって下限版は全期間の結果と同じになった',
     'why': '事前登録どおりに実装した結果。事前登録も『株価がはじめから無い会社はこの方法では入れられない（被覆で報告）』と書いている', 'affects_grading': 'grade_short の lower_bound は full と同じ判定になる（生き残りの偏りを挟む役には立っていない）'},
    {'what': '費用: 毎月の実際の片道の回転 × 0.10% をその月に引いた（nx_common.apply_cost の年率を均して引く形ではない）。最初の月の組み入れは費用を取らない（相手も同じく最初に買う）', 'why': '事前登録『毎月 ½Σ|w_t − w̃_{t−1}| × 0.10%』の字面どおり', 'affects_grading': '無し（総額は同じ）'},
    {'what': '五分位の境目は numpy.percentile（線形補間）。境目ちょうどは下の五分位（低い＝悪い側の向きに直した値で）', 'why': '事前登録に補間の方法の指定が無い', 'affects_grading': '無し〜小さい'},
    {'what': '『株価のある会社が10社未満なら U_t を持つ』を 12か月の規則にも当て、時価加重の規則では浮動株のある会社で数えた。買い−売り（X2）は足りない側だけ U を持つ。30社（X10）は並べる会社が50社未満の月は U', 'why': '事前登録の Q5_rule の一般の約束を同じ形で当てた', 'affects_grading': '無し〜小さい'},
    {'what': 'X7 の業種は French の Siccodes12（EDGAR の今の SIC）。SIC が無い・どの範囲にも入らない会社は 12（Other）。業種の中の信号が10社未満の業種は並べない。並べる会社が全体で50社未満の月は U', 'why': '事前登録どおり（Other の扱いの指定が無いので French の既定に従った）', 'affects_grading': '無し'},
    {'what': 'drop_top は最大寄与の1社を U から全期間除いた（境目の計算からも消える）', 'why': '『母集団から全期間除いて（規則と相手の両方から）』の字面どおり', 'affects_grading': '無し'},
    {'what': '月次リターンは連続した月の調整後終値どうしだけで作り、間の月が抜けた系列は抜けた月を外した（0 で埋めない・つながない）', 'why': '絶対のルール7', 'affects_grading': '無し〜小さい'},
    {'what': 'C4（転がる20年窓）と20年積立は丸める前の差・比で勝ちを数えた（nx_common.rolling/dca は丸めた後に数える）', 'why': 'まとめ役の指示（丸めた差 0.00 を負けにしない）', 'affects_grading': 'grade_short は C4 を使わない。参考の C1〜C8 だけ'},
    {'what': '参考の長期の格付け（grade）の C5 は 2015-01〜・2017-01〜・2020-07〜 の3単位（重なっている）、C7 の Holm は保有期間の両側 p で族ごと', 'why': 'この角度の格付けは事前登録で grade_short と決まっている。C1〜C8 は参考に並べるだけ', 'affects_grading': '無し（参考）'},
    {'what': '会社の同定の既知の例のうち Google Inc. は 2006-04〜2014-10（事前登録の試しでは〜2016-01）。2014-11 以降は後継 Alphabet（A）が同じ記号 GOOGL を最初の年次報告（2016-02-11）で名乗り、L1 の取り合いで新しい名乗りが勝った',
     'why': 'nx_lazy_data.build_panel の約束どおりの結果（panel は再現で1か月の違いも無い）。株価は同じ GOOGL なので値動きは途切れない。その15か月は Alphabet に前年の 10-K が無く信号は無い（並べない）', 'affects_grading': '無し〜小さい'},
    {'what': 'X6 の IT7（MD&A）の規則は全期間と同じ 1997-07 から（事前登録が遅らせる約束を書いたのは IT1A だけ）。信号が50社に満たない月は U をそのまま持つ（該当 5 か月）', 'why': '事前登録 criteria.full の字面どおり', 'affects_grading': '無し'},
    {'what': 'X11（10-Q）・X12（S&P 500 の外）は未測定', 'why': 'out/_nx_cache/nx_lazy_manifest.json（2026-09-28T23:09:46Z・株価を読み込む前・成績を計算する前に記録）', 'affects_grading': '族に入らない（事前登録の total_graded 50 本は変わらない）'},
]


def write_out(P, results, log, starts, sanity_out, extra, pre, t_start):
    import subprocess
    try:
        pc = subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%h %cI', '--', 'out/nx_lazy_prereg.json'], capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        pc = None
    man = json.load(open(os.path.join(CACHE, 'nx_lazy_manifest.json'))) if os.path.exists(os.path.join(CACHE, 'nx_lazy_manifest.json')) else None
    fams = collections.defaultdict(list)
    for r in results:
        fams[r['family']].append(r)
    fam_out = {}
    for f, lst in fams.items():
        fam_out[f] = {'n': len(lst), 'grades': collections.Counter(r['grade'] for r in lst),
                      'holm_p_one_full': {r['rule']: r['family_holm_p_one_full'] for r in lst}}
    gc = collections.Counter(r['grade'] for r in results)
    order = {'S': 0, 'A': 1, 'B': 2, 'C': 3}
    ranked = sorted(results, key=lambda r: (order[r['grade']], -(r['full']['t'] if r['full'] and r['full']['t'] is not None else -99)))
    best = ranked[0]
    tested = []
    for r in results:
        r2 = {k: v for k, v in r.items() if k != '_series'}
        tested.append(r2)
    primary = [{'rule': r['rule'], 'grade': r['grade'], 'full_ex_ann': r['full']['ex_ann'], 'full_t': r['full']['t'], 'full_cagr_diff': r['full']['cagr_diff'],
                'train_cagr_diff': r['train']['cagr_diff'] if r['train'] else None, 'hold_cagr_diff': r['hold']['cagr_diff'] if r['hold'] else None,
                'cost_full_cagr_diff': r['cost_0.10pct']['full']['cagr_diff'] if r['cost_0.10pct']['full'] else None,
                'holm_p_one': r['family_holm_p_one_full']} for r in results if r['family'] == 'P']
    obj = {
        'generated': datetime.date.today().isoformat(),
        'angle': 'nx_lazy',
        'title': pre.get('title'),
        'prereg': 'out/nx_lazy_prereg.json', 'prereg_commit': pc, 'global_prereg': 'out/nx_prereg.json（criteria_short_sample）',
        'script': 'night/nx_lazy.py', 'data_script': 'night/nx_lazy_data.py',
        'run': {'started_utc': t_start, 'finished_utc': datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'elapsed_s': log.get('elapsed_s_rules')},
        'grading': 'nx_common.grade_short(full, first_half, second_half, drop_top, cost_full, lower_bound, 族の中の Holm 補正後の片側 p)。事前登録 criteria.which のとおり。C1〜C8（grade）は参考として各規則に並べた',
        'periods': {'full': [starts[0], END], 'train': [starts[0], N.TRAIN_END], 'hold': [N.HOLD_START, END], 'first_half': [starts[0], FIRST_HALF_END],
                    'second_half': [SECOND_HALF_START, END], 'it1a_start': starts[1], 'start_check': log.get('start')},
        'benchmark': '同じ母集団 U_t（月末 t−1 の構成の CIK のうち t−1 と t の株価がある会社）の時価加重（浮動株のある会社）／等分。買い−売り（X2）は s=Q5・b=Q1',
        'survivorship': '株価は Yahoo の今ある記号だけ＝上場廃止・買収で消えた会社は入らない（生き残りの偏りあり）。構成の記号のうち株価の取れる割合は 1997年6月 38.7%・2006年 56.5%・2016年 79.6%・2026年 98.6%（sanity_checks_before_results.coverage_june）',
        'deviations_from_prereg': DEVIATIONS,
        'x11_x12_decision': man,
        'overlap_with_q07leu_lmtext': {'what': 'q07leu（ratio-evaluation-q07leu 枝）の第10回 lmtext は 10-K の否定語の割合の変化が小さい五分位（dneg|q5・等分・選定 1995-04〜2000-12・保有 2001-01〜2026-08）を検定し不合格（保有 −0.72%/年 t−1.18・Holm p 0.88）',
                                       'which_rules_here': 'X4_DNEG_Q5_VW_12・X4_DNEG_XQ1_VW_12（同じ特徴量 DNEG）と X5（DNEG を使う組み合わせ）',
                                       'difference': 'ここは S&P 500 の時点の構成に限った時価加重・自前で 10-K の本文から数えた LM の2009年版の否定語・12か月の窓。q07leu は Loughran-McDonald の公開の 10-K 集計（全上場・等分）。同じ仮説の別の実装なので独立の追試ではなく、多重検定の数では同じ族に数えるべき'},
        'sanity_checks_before_results': sanity_out,
        'data_log': {k: v for k, v in log.items() if k not in ('start',)},
        'families': fam_out,
        'summary': {'n_tested': len(results), 'grade_counts': dict(gc), 'primary_family_P': primary,
                    'best_by_grade_then_full_t': {'rule': best['rule'], 'grade': best['grade'], 'full': best['full'], 'hold': best['hold']}},
        'tested': tested,
        'extra_report_not_in_prereg': extra,
        'post_hoc': {},
    }
    p = os.path.join(BASE, 'out', 'nx_lazy.json')
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o) if isinstance(o, np.floating) else str(o))
    return p


def post_hoc():
    """『事後』の診断（結果を見た後に足した・格付けに使わない）。out/nx_lazy.json の post_hoc に書く"""
    p = os.path.join(BASE, 'out', 'nx_lazy.json')
    obj = json.load(open(p))
    log = {}
    P = build(log)
    SIG, F = signal_mats(P)
    specs = {s['name']: s for s in rule_specs()}
    t_by = {r['rule']: r for r in obj['tested']}
    out = {'label': '事後（結果を見た後に足した分析・格付けに使わない・規則は1本も足していない）', 'run_utc': datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'}
    # (1) いちばん成績のよかった規則（B の中で全期間の t が最大）の中身: 寄与の集中
    best = obj['summary']['best_by_grade_then_full_t']['rule']
    sp = specs[best]
    st = t_by[best]['start']
    res = run(P, sp, SIG, F, st)
    order = np.argsort(-res['contrib'])
    top10 = [{'ticker': next((P.tick[ti][i] for ti in range(P.T - 1, -1, -1) if P.tick[ti][i]), None), 'cik': P.ciks[i],
              'contrib_sum': round(float(res['contrib'][i]), 4)} for i in order[:10]]
    bot5 = [{'ticker': next((P.tick[ti][i] for ti in range(P.T - 1, -1, -1) if P.tick[ti][i]), None), 'cik': P.ciks[i],
             'contrib_sum': round(float(res['contrib'][i]), 4)} for i in order[::-1][:5]]
    drops = {}
    for k in (1, 3, 5, 10):
        rd = run(P, sp, SIG, F, st, drop=list(order[:k]))
        drops[f'drop_top{k}'] = compact(N.excess_stats(rd['s'], rd['b'], st, END))
    out['best_rule_concentration'] = {'rule': best, 'contrib_sum_total': round(float(res['contrib'].sum()), 4),
                                      'top10_contributors': top10, 'bottom5': bot5, 'excess_after_dropping_top_k': drops,
                                      'reading': '寄与の合計（月次の (w規則−w相手)×r の総和）に対する上位の会社の割合と、上位 k 社を母集団から除いた全期間の超過'}
    # (2) 株価の無い構成の会社（生き残りの偏り）が五分位のどこに居たか（JAC・12か月の境目を当てる）
    tab = collections.defaultdict(lambda: np.zeros((6, 2)))
    for ti in range(P.mi[obj['periods']['full'][0]], P.mi[END] + 1):
        m = P.months[ti]
        r = P.R[ti]
        U = P.member[ti - 1] & ~np.isnan(r)
        v = SIG['JAC'][ti]
        ok = U & ~np.isnan(v)
        if ok.sum() < MIN_RANK:
            continue
        bps = np.percentile(v[ok], [20, 40, 60, 80])
        mem = P.member[ti - 1] & ~np.isnan(v)
        q = 1 + np.searchsorted(bps, v, side='left')
        per = 'A_1997_2006' if m <= 200612 else ('B_2007_2016' if m <= 201612 else 'C_2017_end')
        for k in range(1, 6):
            sel = mem & (q == k)
            tab[per][k, 0] += sel.sum()
            tab[per][k, 1] += (sel & ~U).sum()
    out['unpriced_members_by_JAC_quintile'] = {per: {f'Q{k}': round(float(a[k, 1] / a[k, 0]), 4) if a[k, 0] else None for k in range(1, 6)}
                                               for per, a in sorted(tab.items())}
    out['unpriced_reading'] = ('構成に居て 10-K の信号もあるのに株価が無い（上場廃止・買収で Yahoo に無い）会社の割合を、U の境目で五分位に当てたもの。'
                               'Q1 の割合が Q5 より高ければ、生き残りの偏りは Q1 の悪い結果を落としている向き（Q1 を外す規則の超過は真の値より小さく出る）')
    # (3) 仮説と逆向きの五分位の数字（extra の表から）
    ex_ = obj.get('extra_report_not_in_prereg') or {}
    dq = (ex_.get('quintiles_DNEG_VW_12') or {})
    out['opposite_sign_notes'] = {
        'DNEG_Q1_minus_U_vw_full': dq.get('Q1', {}).get('full'),
        'DNEG_Q5_minus_U_vw_full': dq.get('Q5', {}).get('full'),
        'reading': '否定語の割合が最も増えた五分位（DNEG の Q1・論文と LM の向きでは避ける側）が、同じ母集団の時価加重に全期間で年 +3% 前後勝っていた（t 2.1 前後）。仮説と逆向きで、事前登録に無い規則なので勝ちとしては数えない（五分位 5×信号 4 の表の中の1マスで、多重比較の補正もしていない）'}
    # (4) 論文との比較
    ls = {r['rule']: compact(r['full']) for r in obj['tested'] if r['family'] == 'X2'}
    out['paper_comparison'] = {'X2_long_short_full': ls,
                               'reading': 'CMN (2020) の時価加重の Q5−Q1 は月 最大 58bp（年 約 7%・t 3.59・1995〜2014・全上場・10-K と 10-Q）。ここ（S&P 500 の株価の取れる会社・10-K だけ・1997-07〜2026-08）の買い−売りは 8本とも全期間の t が 1 未満〜負で、論文の大きさは出なかった'}
    obj['post_hoc'] = out
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o) if isinstance(o, np.floating) else str(o))
    return out


if __name__ == '__main__' and '--post-hoc' in sys.argv:
    o = post_hoc()
    print(json.dumps(o, ensure_ascii=False, indent=1, default=str)[:6000])
    sys.exit(0)

if __name__ == '__main__':
    t_start = datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    P, SIG, F, results, log, starts, (rf, mkt, spy, rsp), pre = main()
    san, bv, be = sanity(P, SIG, F, starts[0], spy, mkt, log)
    extra = {'note': '事前登録の外（報告のみ・格付けに使わない）。五分位ごとの成績 − 同じ母集団の相手。単調かを見るため',
             'quintiles_JAC_VW_12': quintile_table(P, SIG, F, starts[0], 'JAC', True),
             'quintiles_COS_VW_12': quintile_table(P, SIG, F, starts[0], 'COS', True),
             'quintiles_JAC_EW_12': quintile_table(P, SIG, F, starts[0], 'JAC', False),
             'quintiles_DNEG_VW_12': quintile_table(P, SIG, F, starts[0], 'DNEG', True)}
    p = write_out(P, results, log, starts, san, extra, pre, t_start)
    print('→', p)
