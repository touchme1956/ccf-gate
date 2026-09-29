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
# 是正（2026-09-29）の前後を並べるための切り替え（既定はすべて是正後。fixes 欄の段階ごとの数を作り直すときだけ使う）:
#   NX_LAZY_FIXES_OFF = 'float_pit'（浮動株の検問を旧版＝後の報告も使う）・'float_d'（(d) を外す＝検査役の案）・'price_errors'（JCI を直さない）・
#                       'siblings'（旧版の兄弟の記号）をカンマ区切り
#   NX_LAZY_SECTION_VARIANT = 'v3'（旧版の節）・'nearest'（検査役の字面の節）。既定は v4
#   NX_LAZY_OUT = 出力の置き場（既定 out/nx_lazy.json）
FIXES_OFF = {x for x in os.environ.get('NX_LAZY_FIXES_OFF', '').split(',') if x}
SECTION_VARIANT = os.environ.get('NX_LAZY_SECTION_VARIANT', 'v4')
OUT_PATH = os.environ.get('NX_LAZY_OUT') or os.path.join(BASE, 'out', 'nx_lazy.json')
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


# 株価の誤り（2026-09-29・検査役の指摘で確かめた）: Yahoo の調整後終値が会社の分離（スピンオフ）を調整していない株月。
# 株価が無い月と同じに扱う（U から外す・0 で埋めない・系列は続くので途切れの印は立てない）。
# 探し方: 事前登録の点検『−40% 未満か +100% 超の株月』（U の中の全株月）のうち、Yahoo の記録に同じ月の株式分割・大きな特別配当
# （前月末の終値の 5% 以上）がある株月を全部見た（3件: JCI 2007-07・AIV 2008-10・AIG 2009-07）。AIV（2008年10月の REIT の暴落）と
# AIG（1株を20株にまとめた月の後の本当の下げ）は本物の値動き。誤りは JCI だけ（sanity_checks_before_results.price_errors_scan）
PRICE_ERRORS = {
    ('JCI', 200707): ('Tyco International（CIK 833444・今の Johnson Controls International）の 2007-06-29 の Covidien と Tyco Electronics の分離'
                      '（1株を4株にまとめる株式併合つき）を Yahoo の調整後終値が調整していない（200706 adj 35.34 → 200707 adj 14.58＝−58.7%。'
                      '分離した2社の株を足した本当の月次は約 −4%＝検査役の再計算。分離した Covidien は Yahoo に無く直せないので欠測にする）'),
}
PRICE_FIX = collections.Counter()


def yahoo_events(ticker):
    """キャッシュの Yahoo の月足の記録から {yyyymm: [(種類, 値)]}（配当は金額・分割は比）。点検だけに使う"""
    p = os.path.join(CACHE, f'yh_{ticker.replace("^", "IDX_").replace("=", "_")}_1mo.json')
    try:
        r = json.load(open(p))['chart']['result'][0]
    except Exception:  # noqa
        return {}
    out = {}
    for kind in ('dividends', 'splits'):
        for k, v in ((r.get('events') or {}).get(kind) or {}).items():
            d = datetime.datetime.utcfromtimestamp(int(v.get('date', k)))
            out.setdefault(d.year * 100 + d.month, []).append((kind, v.get('amount') if kind == 'dividends' else v.get('splitRatio')))
    return out


def returns_of(px):
    """連続した月どうしだけでリターンを作る（間の月が抜けたら作らない＝0 で埋めない）"""
    ks = sorted(px)
    return {k: px[k][0] / px[p][0] - 1 for p, k in zip(ks, ks[1:]) if ym_add(p, 1) == k}


# ───────────────────────── 会社の同定の再現（記号 k を残す） ─────────────────────────
OWNER_FIRST_LOG = collections.Counter()


def sib_all(cand, cik):
    """その会社の株式の記号（今の記号・株価の記号・SEC の記号表の記号・種類株）"""
    c = cand.get(cik) or {}
    return set((c.get('price_tickers') or []) + (c.get('sec_tickers') or []) + (c.get('tickers') or []))


def relink(owner_first=False):
    """nx_lazy_data.build_panel と同じ約束で、月末ごとの (cik → (記号 k, 道)) を作り直す。
    build_panel は CIK と道だけを残すので、C（前身）の株価の記号を決める（k が後継の記号か）ためにここで k を残す。
    結果の CIK の集合と道が nx_lazy_members.json と一致することを確かめる（sanity に書く）。
    owner_first=True は『事後』の頑健性だけ（格付けに使わない）: 同じ記号 k に複数の CIK が候補になったとき、
    k を自分の株式の記号（sib_all）に持つ会社が候補に居れば、その会社だけで事前登録の順（道→提出日）を当てる。
    本文の記号の抜き出しが、保有株の一覧（Cincinnati Financial の XOM・JPM・AAPL…）や競合の名前（EPAM の CTSH）を
    自分の記号と読み、持ち主（株価の取れる大型株）を U から追い出していたことへの手当て（2026-09-29・結果を見た後に見つけた）"""
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
        """同じ発行体の種類株の記号の組（GOOG と GOOGL）: その会社の今の記号（SEC の記号表・構成表）の組と、前身（C）なら後継の会社それぞれの
        今の記号の組。2026-09-29 の是正: 旧版は price_tickers（前身が後継から受け継いだ記号で、後継の後継の記号まで連なる）を1つの組に混ぜていたため、
        Breeze-Eastern（旧 TransTechnology・自分の記号は TT だけ）が後継 Trane の後継と誤って結ばれた Ingersoll Rand Inc の IR を兄弟とみなし、
        S&P の IR の枠に結ばれていた（検査役の指摘）。事前登録『その会社の他の種類株の記号も自分の記号とみなす（GOOG と GOOGL）』の字面に戻した"""
        c = cand.get(cik) or {}
        if 'siblings' in FIXES_OFF:  # 旧版（前後の比較だけ）
            return [{t for t in (c.get('price_tickers') or []) + (c.get('sec_tickers') or []) + (c.get('tickers') or []) if t in known_sp}]
        groups = [set((c.get('sec_tickers') or []) + (c.get('tickers') or []))]
        if 'C_predecessor_of_current' in (c.get('via') or []):
            for sc in c.get('successors') or []:
                cs = cand.get(int(sc)) or {}
                groups.append(set((cs.get('sec_tickers') or []) + (cs.get('tickers') or [])))
        return [g & known_sp for g in groups if g & known_sp]

    def own(r, cik):
        if r.get('symbols_ix'):
            got = set(r['symbols_ix'])
        else:
            cc = r.get('symbols') or {}
            if not cc:
                return set()
            mx = max(cc.values())
            got = {k for k, v in cc.items() if v == mx}
        base = set(got)
        for sib in siblings(cik):
            if base & sib:
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
            for k in sorted(near & sp):  # 集合の並び（ハッシュの種）で結果が変わらないように並べる
                cands_for[k].append((1, near_d, cik, 'L1_claim_near'))
            for k in sorted((set().union(*[st for _, st in cl]) & sp) - near):
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
                for tk in sorted(c_fts[cik] & sp):
                    cands_for[tk].append((4, '', cik, 'L5_C_fts'))
        lk = {}
        for k, lst in sorted(cands_for.items()):
            if owner_first:
                own_ = [x for x in lst if k in sib_all(cand, x[2])]
                if own_ and len(own_) < len(lst):
                    OWNER_FIRST_LOG['ticker_months_resolved_to_owner'] += 1
                    lst = own_
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
            else:  # 同じ会社が二つの記号で結ばれた（種類株）: 記号を足しておく（道は優先の高いほう＝並びに依らない）
                lk[cik] = (lk[cik][0] + '|' + k, min(lk[cik][1], top[0][3]))
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
        sfx = '' if SECTION_VARIANT == 'v4' else '_' + SECTION_VARIANT
        if sfx and f'item1a_cos{sfx}' not in r:
            sfx = ''  # 節を取り直す前の signals.csv（item1a_cos がそのまま v3）
        v = {'JAC': fnum(r['sim_jac']), 'COS': fnum(r['sim_cos']), 'JAC_ALL': fnum(r['sim_jac_all']), 'COS_ALL': fnum(r['sim_cos_all']),
             'MINEDIT': fnum(r['sim_minedit']), 'SIMPLE': fnum(r['sim_simple']),
             'IT1A_COS': fnum(r[f'item1a_cos{sfx}']), 'IT7_COS': fnum(r[f'item7_cos{sfx}'])}
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


def build(log, owner_first=False):
    P = Panel()
    t0 = time.time()
    FLOAT_FIX.clear()
    PRICE_FIX.clear()
    log['fix_switches'] = {'fixes_off': sorted(FIXES_OFF), 'section_variant': SECTION_VARIANT}
    link, spsize, cand = relink(owner_first)
    P.link = link
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
            is_c[c] = list(pt)  # 順序つき（universe の price_tickers の順）
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
    need |= {'SPY', 'RSP', 'IVV'}
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
                kk = set(k.split('|'))
                ks = [x for x in is_c[c] if x in kk]  # 後継の記号が複数結ばれた月は universe の price_tickers の順で最初（走りごとに変わらない）
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
            if (t, m1) in PRICE_ERRORS and r is not None and 'price_errors' not in FIXES_OFF:
                PRICE_FIX[f'{t}_{m1}_set_missing'] += 1
                continue
            if r is not None:
                R[ti, i] = r
            elif lastm[t] == m0 and m0 < END:
                ended[ti, i] = True
    P.R, P.CLprev, P.ended = R, CLprev, ended
    log['price_errors_set_missing'] = {'applied_stock_months': dict(PRICE_FIX), 'list': {f'{k[0]} {k[1]}': v for k, v in PRICE_ERRORS.items()}}
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
    # (c)(d) 時系列の検問（2026-09-29 に先読みを是正）。株数に当たる値 = 浮動株 ÷ 基準日の終値（分割だけ調整）。
    #   (c) その報告より**前に**提出された同じ会社の報告（並べる年の差が3年以内）の株数に当たる値の中央値と、直前に採った値（3年以内）の
    #       両方から、1000 の整数乗から 2.5 倍以内だけずれていたら、単位の付け違い（本文が千ドル単位の表を $ で読んだ等）とみて欠測にする
    #   (d) 1年だけの飛び: **直前の2つ**の報告の株数に当たる値がたがいに2倍以内で一致しているのに、この報告だけ両方から5倍を超えて離れていたら欠測
    #       （元の値の直前の2つと、採った値の直前の2つの両方で同じ形のときだけ）。先読みをしないので、本当の段差（合併・分離・浮動株の定義の変更）も
    #       最初の1年は欠測になる（その年は前の報告の浮動株を値動きで転がす）。区別するには次の報告が要る＝旧版の先読みそのもの
    #   欠測は事前登録の『無ければその前の年次報告の値（24か月以内）』の道へ回す。
    #   基準日の終値の記号は、その値を使う月末 t−1 の記号（CAP を作るのと同じ記号）。旧版は (c) に後の報告も入れ、(d) に次の報告を使い、
    #   記号を全期間の最頻の記号で決めていた＝月末 t−1 にはまだ無い報告が重みを決めていた（検査役の指摘・事前登録 timing.weights に反する）
    ann_chk = {}
    dropped_c, dropped_d = set(), set()

    old_ver = None
    if 'float_pit' in FIXES_OFF:  # 旧版（前後の比較だけ）: 全期間の最頻の記号・前後3年の他の報告の中央値・次の報告
        old_ver = {}
        tk_of = {}
        for i in range(n):
            cnt = collections.Counter(tick[ti][i] for ti in range(T) if tick[ti][i])
            if cnt:
                tk_of[ciks[i]] = cnt.most_common(1)[0][0]
        for c, L in ann.items():
            t = tk_of.get(c)
            if not t or t not in px:
                old_ver[c] = L
                continue
            sh = []
            for f_, fo in L:
                pb = px[t].get(fo[1]) if fo else None
                sh.append(fo[0] / pb[1] if (fo and pb) else None)
            newL = list(L)
            for j, (f_, fo) in enumerate(L):
                if sh[j] is None:
                    continue
                ref = [sh[k] for k in range(len(L)) if k != j and sh[k] is not None and abs((L[k][0] // 100) - (f_ // 100)) <= 3]
                if not ref:
                    continue
                if _scale_error(sh[j], float(np.median(ref))):
                    dropped_c.add((c, j)); newL[j] = (f_, None)
                    continue
                pj = next((sh[k] for k in range(j - 1, -1, -1) if sh[k] is not None), None)
                nj = next((sh[k] for k in range(j + 1, len(L)) if sh[k] is not None), None)
                if pj and nj and max(pj, nj) / min(pj, nj) <= 2 and min(sh[j] / pj, pj / sh[j]) < 0.2 and min(sh[j] / nj, nj / sh[j]) < 0.2:
                    dropped_d.add((c, j)); newL[j] = (f_, None)
            old_ver[c] = newL

    def ann_checked(c, t):
        if old_ver is not None:
            return old_ver.get(c) or []
        key = (c, t)
        if key in ann_chk:
            return ann_chk[key]
        L = ann.get(c) or []
        if not t or t not in px:
            ann_chk[key] = L
            return L
        sh = []
        for f_, fo in L:
            pb = px[t].get(fo[1]) if fo else None
            sh.append(fo[0] / pb[1] if (fo and pb) else None)
        newL = list(L)
        last_kept, kept = None, []
        for j, (f_, fo) in enumerate(L):
            if sh[j] is None:
                continue
            ref = [sh[k] for k in range(j) if sh[k] is not None and (f_ // 100) - (L[k][0] // 100) <= 3]
            # (c) は、過去3年の値の中央値とも、直前に採った値（3年以内）とも 1000 の整数乗だけずれるときだけ（どちらか一方だけで決めると、
            #     過去の誤りの続き〔MAT・AJG の 2019〜2020〕の後の正しい値や、最初の報告の誤りの後の正しい値まで落とす）
            lk = last_kept if (last_kept and (f_ // 100) - (last_kept[0] // 100) <= 3) else None
            if ref and _scale_error(sh[j], float(np.median(ref))) and (lk is None or _scale_error(sh[j], lk[1])):
                dropped_c.add((c, j))
                newL[j] = (f_, None)
                continue
            # (d) は、直前の2報告（元の値）でも、直前に採った2報告でも同じ形（2つが2倍以内で一致し、この報告だけ両方から5倍を超えて離れる）のときだけ
            #     （元の値だけで決めると、過去の誤りが2年続いた後の正しい値〔MAT・AJG の 2021〕を落とす）
            spike = lambda prv: len(prv) == 2 and max(prv) / min(prv) <= 2 and all(min(sh[j] / q, q / sh[j]) < 0.2 for q in prv)  # noqa
            prv = [sh[k] for k in range(j - 1, -1, -1) if sh[k] is not None][:2]
            prk = [x[1] for x in kept[-2:]]
            if 'float_d' not in FIXES_OFF and spike(prv) and spike(prk):
                dropped_d.add((c, j))
                newL[j] = (f_, None)
                continue
            last_kept = (f_, sh[j])
            kept.append(last_kept)
        ann_chk[key] = newL
        return newL
    P.ann_checked = ann_checked
    for ti in range(1, T):
        m_prev = months[ti - 1]
        for i in range(n):
            if np.isnan(CLprev[ti, i]):
                continue
            c = ciks[i]
            t = tick[ti - 1][i]
            L = ann_checked(c, t)
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
    if old_ver is not None:  # 旧版（前後の比較だけ）は旧版の名前で数える
        FLOAT_FIX['time_series_scale_error_dropped'] = len(dropped_c)
        FLOAT_FIX['one_year_spike_dropped'] = len(dropped_d)
    else:
        FLOAT_FIX['time_series_scale_error_dropped_past_only'] = len(dropped_c)
        FLOAT_FIX['one_year_spike_dropped_past_two'] = len(dropped_d)
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
    add('X5a_JACQ1_or_DNEGQ1_excluded_VW_12', 'X5', ['JAC', 'DNEG'], 'COMBO_A', True, 12, note='DNEG を使う＝q07leu の lmtext（dneg の五分位・等分・2001〜）と一部重なる')
    add('X5b_JACQ5_not_DNEGQ1_VW_12', 'X5', ['JAC', 'DNEG'], 'COMBO_B', True, 12, note='DNEG を使う＝q07leu の lmtext（dneg の五分位・等分・2001〜）と一部重なる')
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


def grade_core(P, sp, SIG, F, st):
    """格付け（grade_short）に入る6つの数（全期間・前半・後半・最大寄与の1社を除く・費用後・下限版）を1本の規則について作る。
    本体（main）と事後の頑健性（post_hoc）が同じ手順を使う（二重実装を作らない）"""
    kind = sp['kind']
    res = run(P, sp, SIG, F, st)
    s, b = res['s'], res['b']
    sc, bc = cost_series(res, kind, COST)
    top = int(np.argmax(res['contrib']))
    res_d = run(P, sp, SIG, F, st, drop=top)
    res_lb = run(P, sp, SIG, F, st, lb=True)
    return {'res': res, 'res_lb': res_lb, 'top': top, 'sc': sc, 'bc': bc,
            'full': ex(s, b, st, END), 'first_half': ex(s, b, st, FIRST_HALF_END), 'second_half': ex(s, b, SECOND_HALF_START, END),
            'drop_top': ex(res_d['s'], res_d['b'], st, END), 'cost_full': ex(sc, bc, st, END), 'lower_bound': ex(res_lb['s'], res_lb['b'], st, END)}


def compact(e):
    return None if e is None else {k: e[k] for k in ('from', 'to', 'years', 'ex_ann', 't', 'p', 'cagr_diff', 'te', 'beta')}


_FF = {}


def ff_monthly():
    """French の5因子（Mkt-RF・SMB・HML・RMW・CMA）と勢い（Mom）の月次（小数）"""
    if not _FF:
        f5 = N.french_series('F-F_Research_Data_5_Factors_2x3', want='')
        mo = N.french_series('F-F_Momentum_Factor', want='')
        for c in ('Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA'):
            _FF[c] = f5[c]
        _FF['Mom'] = mo[[c for c in mo if c.strip().lower().startswith('mom')][0]]
    return _FF


def factor_loadings(s, b, a, z, lag=12):
    """報告のみ（事前登録 known_limits『β と因子への傾きは報告する』・格付けに使わない）。
    月次の超過 s−b を 5因子＋勢いに回帰（定数あり）。t は Newey-West（Bartlett・ラグ12）の HAC"""
    ff = ff_monthly()
    cols = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom']
    ks = sorted(k for k in set(s) & set(b) if a <= k <= z and all(k in ff[c] for c in cols))
    if len(ks) < 36:
        return None
    y = np.array([s[k] - b[k] for k in ks])
    X = np.column_stack([np.ones(len(ks))] + [[ff[c][k] for k in ks] for c in cols])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ beta
    n = len(y)
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe / n
    for L in range(1, lag + 1):
        G = Xe[L:].T @ Xe[:-L] / n
        Sm += (1 - L / (lag + 1)) * (G + G.T)
    Q = np.linalg.inv(X.T @ X / n)
    V = Q @ Sm @ Q / n
    se = np.sqrt(np.diag(V))
    r2 = 1 - float(e @ e) / float(((y - y.mean()) ** 2).sum()) if n > 1 else None
    out = {'from': ks[0], 'to': ks[-1], 'months': n, 'alpha_ann_pct': round(float(beta[0]) * 1200, 2), 'alpha_t': round(float(beta[0] / se[0]), 2),
           'r2': round(r2, 3) if r2 is not None else None}
    for j, c in enumerate(cols, 1):
        out[c] = [round(float(beta[j]), 3), round(float(beta[j] / se[j]), 2)]
    out['note'] = '超過（s−b）の因子への傾き [係数, t]。報告のみ・格付けに使わない（問いは『市場に勝つか』）'
    return out


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
    ivv = returns_of(P.px['IVV']) if 'IVV' in P.px else {}

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
        core = grade_core(P, sp, SIG, F, st)
        res, res_lb, top, sc, bc = core['res'], core['res_lb'], core['top'], core['sc'], core['bc']
        s, b = res['s'], res['b']
        ms = sorted(set(s) & set(b))
        e_full, e_h1, e_h2 = core['full'], core['first_half'], core['second_half']
        e_train = ex(s, b, st, N.TRAIN_END)
        e_hold = ex(s, b, N.HOLD_START, END)
        sc2, bc2 = cost_series(res, kind, COST_HI)
        e_cost_full, e_cost_train, e_cost_hold = core['cost_full'], ex(sc, bc, st, N.TRAIN_END), ex(sc, bc, N.HOLD_START, END)
        # 最大寄与の1社を除く・下限版（grade_core の中で作った）
        e_drop = core['drop_top']
        e_lb = core['lower_bound']
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
            sens['vs_IVV_2000_06'] = compact(ex(s, ivv, max(st, 200006), END))
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
             'factor_loadings_of_excess_report_only': {'full': factor_loadings(s, b, st, END), 'hold': factor_loadings(s, b, N.HOLD_START, END)},
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
            L = [x for x in P.ann_checked(P.ciks[i], P.tick[ti][i]) if x[0] <= m and x[1]]
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
    # 2b 記号の持ち主でない会社に結ばれた記号（同定の誤りの疑い・事前登録の点検『同定の既知の例』の延長・報告のみ）
    owners = collections.defaultdict(set)
    for c in P.cand:
        for t_ in sib_all(P.cand, c):
            owners[t_].add(c)
    by_y, pairs = collections.Counter(), collections.Counter()
    for ym, lk in P.link.items():
        for c, (k, h) in lk.items():
            for t_ in k.split('|'):
                if (owners.get(t_, set()) - {c}) and t_ not in sib_all(P.cand, c):
                    by_y[ym // 100] += 1
                    pairs[(c, P.cand[c].get('name'), t_, ','.join(str(o) for o in sorted(owners[t_] - {c})))] += 1
    out['identity_ticker_linked_to_non_owner'] = {
        'by_year_ticker_months': dict(sorted(by_y.items())),
        'pairs': [{'cik': c, 'name': n, 'ticker': t_, 'owner_ciks_now': o, 'months': v} for (c, n, t_, o), v in pairs.most_common()],
        'reading': ('月末の構成の記号 k が、k を今の自分の記号に持たない会社に結ばれた件数（k を今持つ会社が候補に別に居る）。'
                    '会社が昔の自分の記号を名乗った正しい例（Bath & Body Works の LB・Truist の BBT・Citigroup〔旧 Travelers Group〕の TRV）も入る。'
                    '誤りの型は、本文の記号の抜き出し（事前登録の linking_rule『回数が最も多い記号・同数ならすべて』）が保有株の一覧や競合の名前を自分の記号と読んだもの'
                    '（Cincinnati Financial の XOM・JPM・AAPL・PG・FITB ほか、Mirion〔SPAC の 10-K〕の XOM・WMT・JNJ ほか、Gen Digital の DE、Abbott の ABBV、EPAM の CTSH）。'
                    '同じ道なら提出日が新しいほうが勝つので、持ち主（株価の取れる大型株）がその月の U から外れた。規則と相手の両方から同じく外れる（片側に有利な誤りではない）が、U は S&P 500 から遠くなる。'
                    '格付けは事前登録の同定のまま（変えない）。持ち主を先に採る版を post_hoc の identity_owner_first に『事後』として並べた')}
    # 2c 記号の持ち主が候補に居ない記号に、その記号を今の自分の記号に持たない会社が結ばれた件数（2026-09-29 に足した・報告のみ）。
    #    会社が昔の自分の記号を名乗った正しい例（上場廃止した持ち主は候補に居ない）も入る。誤りの型の例: Novanta（GSI Group）の 10-K の本文の記号の抜き出しが
    #    LSI を名乗りと読み、1996〜2014 の S&P の LSI（LSI Logic）の枠に Novanta の株価と信号が入っていた
    pairs2 = collections.Counter()
    for ym, lk in P.link.items():
        for c, (k, h) in lk.items():
            for t_ in k.split('|'):
                if not owners.get(t_) and t_ not in sib_all(P.cand, c):
                    pairs2[(c, P.cand[c].get('name'), t_, h)] += 1
    out['identity_ticker_not_own_now_owner_not_candidate'] = {
        'pairs': [{'cik': c, 'name': n, 'ticker': t_, 'path': h, 'months': v} for (c, n, t_, h), v in pairs2.most_common()],
        'reading': ('月末の構成の記号 k が、k を今の自分の記号に持たない会社に結ばれ、k を今持つ会社も候補に居ない件数（報告のみ・格付けは事前登録の同定のまま）。'
                    '昔の自分の記号の正しい名乗りと、本文の記号の抜き出しの誤り（他社の記号を自分の記号と読んだもの）の両方が入る。'
                    '誤りの例: Novanta（CIK 1076930・旧 GSI Group）が LSI（1996〜2014 の LSI Logic）に結ばれ、Novanta の株価（NOVT）と信号が入っていた。'
                    'Albemarle（CIK 915913）は FY2009 の 10-K が MWV を ALB と同じ回数（2回）書いていたため、L2 で MeadWestvaco（MWV）の連続した構成の期間（1996〜2015）全体に結ばれていた')}
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
    # 5b 株価の誤りの探し方（2026-09-29・検査役の指摘〔JCI 2007-07〕の後に足した）: 構成の株月のうち、調整後終値の月次が −40% 未満か +100% 超で、
    #    Yahoo の記録に同じ月の分割か大きな特別配当（前月末の終値の 5% 以上）がある株月を全部並べる（直す前の値で）
    scan = []
    for ti in range(P.mi[start], P.mi[END] + 1):
        m = P.months[ti]
        for i in np.where(P.member[ti - 1])[0]:
            t = P.tick[ti - 1][i]
            if not t or t not in P.rets or np.isnan(P.CLprev[ti, i]):
                continue
            rv = P.rets[t].get(m)
            if rv is None or not (rv < -0.40 or rv > 1.00):
                continue
            ev = yahoo_events(t).get(m, [])
            pc = P.px[t][P.months[ti - 1]][1]
            big = [e for e in ev if (e[0] == 'dividends' and e[1] and e[1] / pc >= 0.05) or e[0] == 'splits']
            if big:
                scan.append({'ticker': t, 'cik': P.ciks[i], 'month': m, 'ret_yahoo_adj': round(float(rv), 4), 'events': big,
                             'set_missing': (t, m) in PRICE_ERRORS and 'price_errors' not in FIXES_OFF})
    out['price_errors_scan'] = {'rows': scan, 'reading': ('JCI 2007-07 は会社の分離の調整漏れ（欠測にした）。AIV 2008-10（REIT の暴落・前月末の終値が分割の調整で小さく、'
                                                        '通常の配当が 5% を超えて見えた）と AIG 2009-07（1株を20株にまとめた後の本当の下げ・月末 $13.1）は本物の値動き。'
                                                        '−40% に届かない分離の調整漏れはこの探し方では見つからない（事前登録 known_limits のとおり）')}
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
    {'what': '浮動株の検問を足した（(a) XBRL・iXBRL の値にも 100万〜10兆ドルの範囲 ／ (b) XBRL（無ければ iXBRL）と本文の比が 1000 の整数乗から 2.5 倍以内なら本文 ／ (c) 株数に当たる値（浮動株÷基準日の終値）が、その報告より前に提出された同じ会社の報告（並べる年の差3年以内）の中央値と、直前に採った値（3年以内）の両方から 1000 の整数乗だけずれたら欠測 ／ (d) 直前の2つの報告が2倍以内で一致しているのにこの報告だけ両方から5倍を超えて離れたら欠測（元の値の直前の2つと、採った値の直前の2つの両方で同じ形のときだけ）。(c)(d) の欠測は事前登録の『その前の年次報告（24か月以内）』の道へ回す。基準日の終値の記号はその値を使う月末 t−1 の記号）。2026-09-29 に (c)(d) の先読みを是正した: 旧版は (c) に後から提出される報告も入れ、(d) に次の報告を使い、記号を全期間の最頻の記号で決めていた＝月末 t−1 にはまだ無い報告が時価加重の重みを決めていた（事前登録 timing.weights に反する・検査役の指摘。前後の数は fixes）',
     'why': '事前登録の点検『U_t の時価加重と SPY の相関（0.97 未満なら浮動株か同定に誤り）』が 0.706 だった。原因は XBRL の dei:EntityPublicFloat の単位の付け違い（MTB・ZBH・HST・PKG・NEM・IQV・QCOM は ×100万、WAT・DPZ・GRMN・SHW・TKO・HBAN は ×1000、ALB は 1e18）で、1社が U の重みの 99% を持つ月があった。本文の値には取得器が 100万〜10兆ドルの範囲を掛けていたが XBRL・iXBRL の値には掛けていなかった。(c)(d) は本文の千ドル単位の表を $ として読んだ年（PEP・BAC・DUK ほか）と1年だけの飛び（EXC 2009 ほか）。検問は浮動株の値と相手の相関だけを見て決め、規則の成績は1つも計算する前。検問後の相関 0.9933',
     'affects_grading': '時価加重の規則すべて（主の族 P を含む）の重み。規則の中身・線は不変'},
    {'what': '株価の記号: 今の SEC の記号が優先株だけの会社（811830 Santander Holdings USA〔旧 Sovereign〕・1527469 Athene）は普通株の株価が無いとして外した。EIDP（旧 DuPont・C と D の両方）は C の約束（その月の記号 k が後継の記号なら k の株価）で扱った',
     'why': '事前登録は A・B・D に『今の SEC の記号』を当てるが、優先株の値動きを普通株の代わりに使うのは誤り', 'affects_grading': '小さい（3社）'},
    {'what': 'C（前身）の株価の記号は、その月に構成表と結んだ記号 k が後継の記号のどれかなら k そのもの（GOOGL/GOOG のような種類株を取り違えない）。k の中に後継の記号が複数ある月（IR|TT・GOOGL|GOOG・FOXA|FOX）は universe の price_tickers の順で最初のもの', 'why': '事前登録『C は後継の記号を、その月の前身の自分の記号が後継の記号と同じとき』の最も近い形', 'affects_grading': '無し〜小さい'},
    {'what': '走りごとの再現性の是正（2026-09-29）: 前の実装は、会社の同定の中で集合（set）を並べる順が Python のハッシュの種（走るたびに変わる）で決まり、C（前身）の株価の記号（上の IR か TT か など）が走りごとに変わっていた。記号を並べてから処理し、C の株価の記号は price_tickers の順で決めるようにした（同じ会社に二つの記号が結ばれた月の『道』は優先の高いほう）',
     'why': '同じコードとデータで結果が変わるのは測定の誤り。種 1 と 3 で走らせて、株価の記号・月次リターン・時価・規則の月次系列が完全に一致することを確かめた（data_log.determinism_check）',
     'affects_grading': '小さい（全期間の幾何の差が 13本で ±0.01〜0.03 動いた・主の族 P1 は −0.81 → −0.82）。前の実装者の途中の結果と比べて格付けの変わった規則は無い（data_log.determinism_check）'},
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
    {'what': '時価加重の規則を IVV と並べる比較（事前登録 real_instrument_check.comparisons）は 2000-06 から（IVV の設定は 2000-05）。SPY・French Mkt・RSP は事前登録どおり', 'why': 'IVV の月次は設定の後からしか無い', 'affects_grading': '無し（報告のみ）'},
    {'what': '超過（s−b）の因子への傾き（French の5因子＋勢い・定数あり・Newey-West ラグ12）を各規則に報告のみで足した（factor_loadings_of_excess_report_only）', 'why': '事前登録 known_limits『β と因子への傾きは報告する』の約束（前の実装に無かった）', 'affects_grading': '無し（報告のみ）'},
    {'what': 'X11（10-Q）・X12（S&P 500 の外）は未測定', 'why': 'out/_nx_cache/nx_lazy_manifest.json（2026-09-28T23:09:46Z・株価を読み込む前・成績を計算する前に記録）', 'affects_grading': '族に入らない（事前登録の total_graded 50 本は変わらない）'},
    {'what': '【2026-09-29 の是正・結果を見た後】節（Item 1A・Item 7）の取り出しを直した（night/nx_lazy_data.py の section_span の rule v4・全 17,914 件の主文書を取り直して作り直した）。見出しの行（行頭の Item の記号の直後が英大文字〔句読点・改行は飛ばす〕で、直前の行が『,』か機能語〔in・see・under・of …〕で終わっていない）だけを始まり・終わりにし、同じ終わりを共有する始まりの組の中で、最後の別の Item の見出し（壁）より後の最も早い始まりを採る。Item 1A の終わりに Item 1C（2023年12月以降の会計年度の新しい節）を足した',
     'why': '（点検: 300件の無作為の試し〔1997〜2026 の各年10件・600の節〕で v3 と違った 37件を1件ずつ見て、37件とも v4 が見出しから次の見出しまでを取り、v3 は相互参照の行から始まるか相互参照の行で終わっていた）旧版（v3）は行頭の記号をすべて始まり・終わりにして組の中で最も早い始まりを採ったため、本文の前の相互参照の行（Apple FY2006『Item 1A of this Form 10-K.』・『Item 7 for the fiscal years ended…』、Mastercard FY2009、Cigna FY2014 ほか）から始まる区間を選び、Item 1 などをまるごと節に数えていた（検査役の指摘・Apple FY2006 で 18,813語→8,299語を確かめた）。本文の中の相互参照の『Item 8…』を終わりにして節を途中で切る逆の誤りもあった（Ventas FY2011 の MD&A 1,024語→16,340語、Intel FY2009 1,157語→11,585語）。検査役の案（組の中で終わりの直前の始まり）は、頁ごとに見出しを繰り返す提出（Mastercard 2020〜・Cigna 2013〜・Microsoft・Ford ほか）で節を最後の1頁に縮める（Mastercard FY2019 10,603語→206語）ので採らず、感度に残した。事前登録の定義『見出しの行から次の見出しの行まで』に合わせる是正で、規則は変えていない',
     'affects_grading': 'X6 の4本（IT1A_COS・IT7_COS）の信号。ほかの規則の信号は不変（主文書の語数・類似度は変えていない）。前後の数は fixes'},
    {'what': '【2026-09-29 の是正・結果を見た後】会社の同定で、自分の記号を『同じ発行体の種類株』へ広げる約束（事前登録『その会社の他の種類株の記号も自分の記号とみなす（GOOG と GOOGL）』）を、その会社の今の記号の組と、前身なら後継の会社それぞれの今の記号の組に限った（night/nx_lazy.py の relink と night/nx_lazy_data.py の build_panel の両方）',
     'why': '旧版は price_tickers（前身が後継から受け継いだ記号で、後継の後継の記号まで連なる）を1つの組に混ぜていたため、Breeze-Eastern（CIK 99359・旧 TransTechnology・10-K が名乗る記号は TT だけ・S&P 500 に入ったことは無い）が、後継 Trane の後継と誤って結ばれた Ingersoll Rand Inc の IR を兄弟とみなし、1996〜2008 の S&P の IR の枠に結ばれ、2002-05〜2008-01 は Breeze の信号と小さい浮動株に Yahoo の TT（旧 Ingersoll-Rand plc）の株価が付いていた（検査役の指摘）。panel の同じ記号の取り合いの並びも集合の並び（ハッシュの種）に依らないように揃えた（relink と同じ）',
     'affects_grading': ('小さい。(1) Breeze は 1996-01〜2002-04 の IR の枠から外れた（その期間の Breeze の株価の記号 IR は Yahoo に 2017年からしか無く、U には入っていなかった）。'
                         '(2) 同じ誤りのもう一つの形: EIDP（旧 DuPont・C）が後継 DuPont の DD を兄弟とみなして DuPont と同じ道・同じ提出日で DD を取り合い、2020〜2026 の 24か月 DD の枠が両方外れていた→ DuPont（CIK 1666700）が戻った。'
                         '(3) Breeze は自分の記号 TT で 2002-05〜2008-05 の TT の枠に残る（記号の再利用・事前登録の約束どおり・known_issues_found_after_results）。前後の数は fixes')},
    {'what': '【2026-09-29 の是正・結果を見た後】株価の誤り: JCI（CIK 833444・当時 Tyco International）の 2007-07 の株月を欠測にした（U から外す・0 で埋めない）',
     'why': 'Yahoo の調整後終値が 2007-06-29 の Covidien と Tyco Electronics の分離（1株を4株にまとめる株式併合つき）を調整しておらず −58.7%（本当は約 −4%）。事前登録の点検『−40% 未満か +100% 超の株月の上位50件』に載っていたが直していなかった（検査役の指摘）。同じ月に Yahoo の記録に分割か大きな特別配当がある極端な株月を全部見て（3件）、誤りはこの1件だけと確かめた（sanity_checks_before_results.price_errors_scan）',
     'affects_grading': '小さい（1株月）。前後の数は fixes'},
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
        'survivorship': '株価は Yahoo の今ある記号だけ＝上場廃止・買収で消えた会社は入らない（生き残りの偏りあり）。構成の記号のうち株価の取れる割合は ' +
                        '・'.join(f"{m // 100}年6月 {sanity_out['coverage_june'][m]['priced_share_of_sp'] * 100:.1f}%" for m in (199706, 200606, 201606, 202606) if m in sanity_out['coverage_june']) +
                        '（sanity_checks_before_results.coverage_june）。下限版（途切れた次の月に −30%）は、株価のある会社の系列が標本の終わりより前に途切れた例が ' +
                        f"{sanity_out.get('series_ended_stock_months_in_sample')} 件で、全期間の結果と同じになった（生き残りの偏りを挟む役に立っていない）。偏りの向きは post_hoc.unpriced_members_by_JAC_quintile",
        'deviations_from_prereg': DEVIATIONS,
        'known_issues_found_after_results': [
            {'what': '会社の同定の誤り: 本文の記号の抜き出し（事前登録 linking_rule『回数が最も多い記号・同数ならすべて』）が、保有株の一覧や競合の名前を自分の記号と読み、同じ道（L1）で提出日が新しいほうが勝つ約束のために、記号の持ち主（株価の取れる大型株）がその月の U から外れていた（Cincinnati Financial が XOM・JPM・AAPL・MSFT・PG・FITB ほか、Mirion〔SPAC〕が XOM・WMT・JNJ ほか、Gen Digital が DE、Abbott が ABBV、EPAM が CTSH など）',
             'found': '2026-09-29・前の実装者の途中の結果（格付けまで出ていた）を読んだ後に、同定の既知の例（XOM が 2008-02〜2009-01・2012-02〜2015-01 に構成から消える／JPM が 2016-02〜2019-01 に消える）を点検して見つけた',
             'treatment': '格付けは事前登録の同定のまま（結果を見た後に同定を変えて格付けし直すことはしない）。件数は sanity_checks_before_results.identity_ticker_linked_to_non_owner、持ち主を先に採る版の全50本の grade_short は post_hoc.identity_owner_first（事後・格付けに使わない）',
             'direction': '外れた会社は規則と相手の両方から同じく外れるので、片側に有利な誤りではない。U が S&P 500 から少し遠くなる'},
            {'what': '同じ型の誤りのもう一つの形（2026-09-29 の点検で見つけた・直していない）: 記号の持ち主が候補に居ない記号（上場廃止した会社の記号）に、本文の記号の抜き出しが他社の記号を自分の記号と読んだ会社が結ばれる。例: Novanta（CIK 1076930・旧 GSI Group）の 10-K の抜き出しが LSI を名乗りと読み、1996〜2014 の S&P の LSI（LSI Logic）の枠に Novanta の株価（NOVT）と信号が入っていた。Albemarle（CIK 915913）は FY2009 の 10-K だけが MWV を ALB と同じ回数書いていたため、L2 で MeadWestvaco（MWV）の枠（1996〜2015 の連続した構成の期間全体・222か月）に結ばれていた',
             'treatment': '格付けは事前登録の同定のまま。件数は sanity_checks_before_results.identity_ticker_not_own_now_owner_not_candidate（昔の自分の記号の正しい名乗りも入る一覧）',
             'direction': '入った会社は規則と相手の両方に同じく入る（片側に有利な誤りではない）。U が S&P 500 から少し遠くなる'},
            {'what': '記号の再利用による同定の誤り（2026-09-29 の点検で確かめた・直していない）: Breeze-Eastern（CIK 99359・旧 TransTechnology・S&P 500 に入ったことは無い）は、後継の記号 TT の全文検索で Trane Technologies の前身（C）と誤って同定され、自分の記号 TT（TransTechnology の NYSE の記号）を名乗るので、2002-05〜2008-05 の S&P の TT の枠（構成表が後の記号 TT で書く American Standard／Trane Inc.）に L1 で結ばれ、株価は後継の記号 TT（Yahoo＝旧 Ingersoll-Rand plc）になる。兄弟の記号の是正（fixes の F3）で IR の枠からは外れたが、この枠は事前登録の同定の約束（L1・C の株価の記号）どおりの結果なので残した',
             'treatment': '格付けは変えない。99359 を全期間外した版の全50本の全期間の幾何の差は fixes.panel_diagnostics.F3_breeze_remaining_report_only（報告のみ）',
             'direction': '規則と相手の両方に同じく入る。時価加重の重みは Breeze の小さい浮動株で約 1e-5、等分では 1/500 前後'},
            {'what': '同じ記号の取り合いで枠ごと外れる例（2026-09-29 の点検で気づいた・直していない）: Corteva（CIK 1755672）と子会社 EIDP（CIK 30554・旧 DuPont）は同じ日に同じ内容の年次報告（合同の 10-K）を出し、どちらも CTVA を名乗るので、事前登録の約束（同じ道・同じ提出日なら全部外す）で 2020-02 以降の S&P の CTVA の枠が外れている（Corteva が U に居るのは 2019-06〜2020-01 の8か月だけ）',
             'treatment': '事前登録の同定の約束どおり（格付けは変えない）。取り合いで外した件数は sanity_checks_before_results.ticker_conflicts_dropped',
             'direction': '規則と相手の両方から同じく外れる（片側に有利な誤りではない）'}],
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
    p = OUT_PATH
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o) if isinstance(o, np.floating) else str(o))
    return p


def post_hoc():
    """『事後』の診断（結果を見た後に足した・格付けに使わない）。out/nx_lazy.json の post_hoc に書く"""
    p = OUT_PATH
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
    q1f, q5f = dq.get('Q1', {}).get('full'), dq.get('Q5', {}).get('full')
    out['opposite_sign_notes'] = {
        'DNEG_Q1_minus_U_vw_full': q1f,
        'DNEG_Q5_minus_U_vw_full': q5f,
        'reading': (f"否定語の割合が最も増えた五分位（DNEG の Q1・論文と LM の向きでは避ける側）の同じ母集団の時価加重との差は全期間で年 {q1f['ex_ann']:+.2f}%（t {q1f['t']}）、"
                    f"最も減った五分位（Q5）は年 {q5f['ex_ann']:+.2f}%（t {q5f['t']}）。Q1 が勝っていれば仮説と逆向き。事前登録に無い規則なので勝ちとしては数えない"
                    '（五分位 5×信号 4 の表の中の1マスで、多重比較の補正もしていない）') if (q1f and q5f) else None}
    # (4) 論文との比較
    ls = {r['rule']: compact(r['full']) for r in obj['tested'] if r['family'] == 'X2'}
    tmax = max((v['t'] for v in ls.values() if v and v['t'] is not None), default=None)
    out['paper_comparison'] = {'X2_long_short_full': ls,
                               'reading': ('CMN (2020) の時価加重の Q5−Q1 は月 最大 58bp（年 約 7%・t 3.59・1995〜2014・全上場・10-K と 10-Q）。'
                                           f'ここ（S&P 500 の株価の取れる会社・10-K だけ・{obj["periods"]["full"][0]}〜{END}）の買い−売り 8本の全期間の t の最大は {tmax}。論文の大きさは出なかった')}
    # (5) 同定の手当て: 記号の持ち主を先に採る（事後・格付けに使わない）
    log2 = {}
    OWNER_FIRST_LOG.clear()
    P2 = build(log2, owner_first=True)
    SIG2, F2 = signal_mats(P2)
    ff = N.ff_factors()
    spy = returns_of(P2.px['SPY'])
    st0 = obj['periods']['full'][0]
    it1a0 = obj['periods']['it1a_start']
    # U の違い（月ごと）
    added_n, removed_n, added_w, added_names = [], [], [], collections.Counter()
    for ti in range(P.mi[st0], P.mi[END] + 1):
        U1 = P.member[ti - 1] & ~np.isnan(P.R[ti])
        U2 = P2.member[ti - 1] & ~np.isnan(P2.R[ti])
        a_ = U2 & ~U1
        r_ = U1 & ~U2
        added_n.append(int(a_.sum())); removed_n.append(int(r_.sum()))
        cap2 = np.where(U2 & ~np.isnan(P2.CAP[ti]), P2.CAP[ti], 0.0)
        added_w.append(float(cap2[a_].sum() / cap2.sum()) if cap2.sum() > 0 else 0.0)
        for i in np.where(a_)[0]:
            added_names[next((P2.tick[tt][i] for tt in range(ti - 1, -1, -1) if P2.tick[tt][i]), str(P2.ciks[i]))] += 1
    bv2 = bench_series(P2, st0, True)
    ks = sorted(set(bv2) & set(spy))
    ident2 = {'ticker_months_resolved_to_owner': OWNER_FIRST_LOG.get('ticker_months_resolved_to_owner', 0),
              'months': len(added_n), 'avg_ciks_added_to_U': round(float(np.mean(added_n)), 2), 'avg_ciks_removed_from_U': round(float(np.mean(removed_n)), 2),
              'max_ciks_added': int(max(added_n)), 'avg_vw_share_added_pct': round(float(np.mean(added_w)) * 100, 2), 'max_vw_share_added_pct': round(float(max(added_w)) * 100, 2),
              'added_company_months_top': added_names.most_common(25),
              'U_vw_vs_SPY_corr_owner_first': round(N.corr([bv2[k] for k in ks], [spy[k] for k in ks]), 4),
              'U_vw_minus_SPY_owner_first': compact(N.excess_stats(bv2, spy, st0, END)),
              'U_vw_minus_SPY_prereg_identity': compact((obj['sanity_checks_before_results'].get('benchmark_vs_SPY') or {}).get('U_vw_minus_SPY'))}
    specs = rule_specs()
    rows = []
    for sp in specs:
        st = it1a0 if sp['start_rule'] == 'it1a' else st0
        core = grade_core(P2, sp, SIG2, F2, st)
        rows.append((sp, core))
    fams = collections.defaultdict(list)
    for sp, core in rows:
        fams[sp['family']].append((sp, core))
    tab, changed = [], []
    for fam, lst in fams.items():
        h = N.holm({sp['name']: N.p_one(core['full']['t']) if core['full'] and core['full']['t'] is not None else None for sp, core in lst})
        for sp, core in lst:
            g, c = N.grade_short(core['full'], core['first_half'], core['second_half'], core['drop_top'], core['cost_full'], core['lower_bound'], h.get(sp['name']))
            g0 = t_by[sp['name']]['grade']
            row = {'rule': sp['name'], 'family': fam, 'grade_owner_first_post_hoc': g, 'grade_prereg_identity': g0,
                   'full': compact(core['full']), 'first_half_cagr_diff': core['first_half']['cagr_diff'] if core['first_half'] else None,
                   'second_half_cagr_diff': core['second_half']['cagr_diff'] if core['second_half'] else None,
                   'drop_top_cagr_diff': core['drop_top']['cagr_diff'] if core['drop_top'] else None,
                   'drop_top_ticker': next((P2.tick[tt][core['top']] for tt in range(P2.T - 1, -1, -1) if P2.tick[tt][core['top']]), None),
                   'cost_full_cagr_diff': core['cost_full']['cagr_diff'] if core['cost_full'] else None,
                   'holm_p_one': h.get(sp['name']), 'criteria': c}
            tab.append(row)
            if g != g0:
                changed.append({'rule': sp['name'], 'prereg_identity': g0, 'owner_first': g})
    ident2['rules'] = tab
    ident2['grade_counts_owner_first'] = dict(collections.Counter(r['grade_owner_first_post_hoc'] for r in tab))
    ident2['grades_changed_vs_prereg_identity'] = changed
    ident2['label'] = '事後（結果を見た後に見つけた同定の誤りへの手当て・格付けに使わない）。同じ記号に複数の CIK が候補になったとき、記号を今の自分の株式の記号に持つ会社を先に採り、残りは事前登録の順（道→提出日）'
    ident2['caveat'] = ('持ち主を先に採る約束にも小さな誤りが残る: 1997-06〜1999-02 の TRV（当時は Travelers Group＝今の Citigroup）が、今 TRV を持つ Travelers Companies（当時の St. Paul）に結ばれ、'
                        'St. Paul の値動きで入る（21か月）。Motorola Solutions の MMI（2011・当時の Motorola Mobility）のように持ち主が候補に居ない記号は直らない（株価の取れない会社なので U への影響は無い）')
    out['identity_owner_first'] = ident2
    # (6) いちばん成績のよかった規則（IT1A の Q5）の中身: 等分・業種の中で並べた版・相手を SPY に（事後・格付けに使わない）
    sp_ew = {s_['name']: s_ for s_ in specs}['X6_IT1A_COS_Q5_VW_12']
    diag = {}
    for nm, mod in (('IT1A_COS_Q5_EW_12', {'vw': False}), ('IT1A_COS_IND_Q5_VW_12', {'industry': True}), ('IT1A_COS_XQ1_EW_12', {'vw': False, 'kind': 'XQ1'})):
        sp2 = dict(sp_ew); sp2.update(mod); sp2['name'] = nm
        r2 = run(P, sp2, SIG, F, it1a0)
        diag[nm] = {'full': compact(N.excess_stats(r2['s'], r2['b'], it1a0, END)),
                    'post_2015': compact(N.excess_stats(r2['s'], r2['b'], 201501, END))}
    rb = run(P, sp_ew, SIG, F, it1a0)
    by_year = {}
    for y in range(it1a0 // 100, END // 100 + 1):
        ms_ = [m for m in rb['s'] if m // 100 == y and m in rb['b']]
        if ms_:
            gs = math.prod(1 + rb['s'][m] for m in ms_); gb = math.prod(1 + rb['b'][m] for m in ms_)
            by_year[y] = round((gs - gb) * 100, 2)
    diag['X6_IT1A_COS_Q5_VW_12_calendar_year_excess_pct'] = by_year
    diag['X6_IT1A_COS_Q5_VW_12_vs_SPY'] = compact(N.excess_stats(rb['s'], spy, it1a0, END))
    diag['reading'] = '事後。Item 1A の類似度の Q5 の勝ちが、時価加重の巨大株（AAPL・AMZN）の持ち方によるのか、業種の偏りによるのかを見る。規則は1本も足していない（格付けに使わない）'
    out['best_rule_variants_post_hoc'] = diag
    obj['post_hoc'] = out
    # 結論（数はこの走りの結果から組み立てる）
    gc = obj['summary']['grade_counts']
    bst = t_by[best]
    bc_ = out['best_rule_concentration']['excess_after_dropping_top_k']
    pr = [r for r in obj['tested'] if r['family'] == 'P']
    obj['conclusion_ja'] = (
        f"事前登録どおりの {len(obj['tested'])} 本（主の族 P 8本・探索 42本）の格付け（grade_short）は " + '・'.join(f'{k} {v}本' for k, v in sorted(gc.items())) +
        '。S と A は0本＝市場（同じ母集団の時価加重・等分）に勝つ規則は出なかった。'
        f"主の族 P の全期間の超過は年 {min(r['full']['ex_ann'] for r in pr):+.2f}〜{max(r['full']['ex_ann'] for r in pr):+.2f}%（t {min(r['full']['t'] for r in pr)}〜{max(r['full']['t'] for r in pr)}・Holm 後の片側 p の最小 {min(r['family_holm_p_one_full'] for r in pr)}）。"
        f"最もよかった {best}（探索 X6・Item 1A の類似度の Q5・{bst['start']}〜）は年 {bst['full']['ex_ann']:+.2f}%（t {bst['full']['t']}・片側 p {bst['criteria_short_sample']['p_one']}・族の Holm 後 {bst['family_holm_p_one_full']}）で B。"
        f"最大寄与の {bst['drop_top']['ticker']} を除くと幾何の差 {bst['drop_top']['full']['cagr_diff']:+.2f}%、上位3社を除くと {bc_['drop_top3']['cagr_diff']:+.2f}%（事後）。"
        f"論文の買い−売り（X2）は8本とも t が {out['paper_comparison']['reading'].split('t の最大は ')[1].split('。')[0]} 以下。"
        f"同定の誤り（本文の記号の抜き出しが持ち主の大型株を追い出した）を持ち主を先に採る版で直しても（事後）S・A は0本（B {out['identity_owner_first']['grade_counts_owner_first'].get('B', 0)}・C {out['identity_owner_first']['grade_counts_owner_first'].get('C', 0)}）。"
        '株価は Yahoo の現存の記号だけ（生き残りの偏りあり・早い年ほど被覆が低い）。'
        '2026-09-29 に検査役が見つけた4件の誤り（浮動株の検問の先読み・JCI 2007-07 の分離の調整漏れ・兄弟の記号の広げすぎ・節〔Item 1A・Item 7〕の取り出し）を直して走らせ直した（前後の数は fixes）。')
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o) if isinstance(o, np.floating) else str(o))
    return out


def determinism_check(other_path, prev_impl_path=None):
    """再現性の点検: 別のハッシュの種で走らせた out/nx_lazy.json（other_path）と、tested の全規則の数（全期間・前半・後半・最大寄与を除く・費用後・下限版・格付け）が一致するか。
    prev_impl_path があれば、前の実装者の途中の結果（git の HEAD の out/nx_lazy.json）との格付けの差も並べる"""
    p = OUT_PATH
    obj = json.load(open(p))
    oth = json.load(open(other_path))
    ob = {r['rule']: r for r in oth['tested']}
    keys = lambda r: (r['full'], r['first_half'], r['second_half'], r['drop_top']['full'], r['cost_0.10pct']['full'], r['lower_bound_-30pct']['full'], r['grade'])  # noqa
    diff = [r['rule'] for r in obj['tested'] if r['rule'] not in ob or keys(r) != keys(ob[r['rule']])]
    out = {'other_run': {'file': os.path.basename(other_path), 'run': oth.get('run'), 'hash_seed_note': '別の PYTHONHASHSEED で走らせた版'},
           'this_run': obj.get('run'), 'rules_compared': len(obj['tested']), 'rules_with_any_difference': diff}
    if prev_impl_path and os.path.exists(prev_impl_path):
        pv = {r['rule']: r for r in json.load(open(prev_impl_path))['tested']}
        out['vs_previous_partial_implementation'] = {
            'grade_changes': [{'rule': r['rule'], 'previous': pv[r['rule']]['grade'], 'now': r['grade']} for r in obj['tested'] if r['rule'] in pv and pv[r['rule']]['grade'] != r['grade']],
            'full_cagr_diff_changes': [{'rule': r['rule'], 'previous': pv[r['rule']]['full']['cagr_diff'], 'now': r['full']['cagr_diff']}
                                       for r in obj['tested'] if r['rule'] in pv and pv[r['rule']]['full']['cagr_diff'] != r['full']['cagr_diff']],
            'note': '前の実装者の途中の結果（git の HEAD＝72431145 の out/nx_lazy.json）との差。差の原因は C（前身）の株価の記号の選び方の是正（再現性）だけ'}
    obj.setdefault('data_log', {})['determinism_check'] = out
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o) if isinstance(o, np.floating) else str(o))
    return out


def fix_diagnostics():
    """2026-09-29 の是正（fixes）の中間の数: 浮動株の検問の先読み（F1）・JCI（F2）・兄弟の記号（F3）・節（F4）がパネルの何を変えたか。
    成績は計算しない（どの株月・どの信号が変わったかだけ）。FIXES_OFF と SECTION_VARIANT を切り替えて作り直して比べる"""
    global FIXES_OFF, SECTION_VARIANT
    keep = (set(FIXES_OFF), SECTION_VARIANT)
    out = {}
    try:
        FIXES_OFF = {'float_pit', 'price_errors', 'siblings'}
        la = {}
        PA = build(la)
        FIXES_OFF = {'price_errors', 'siblings'}
        lb = {}
        PB = build(lb)
        FIXES_OFF = set()
        lc = {}
        PC = build(lc)
        # F1: 浮動株の検問（CAP が変わった株月・落とした報告の数）
        ca, cb = PA.CAP, PB.CAP
        both = ~np.isnan(ca) & ~np.isnan(cb)
        chg = both & ~np.isclose(ca, cb, rtol=1e-9, atol=0)
        out['F1_float_lookahead'] = {
            'reports_dropped_before': {k: v for k, v in la['float_checks_reports'].items() if k.startswith(('time_series', 'one_year'))},
            'reports_dropped_after': {k: v for k, v in lb['float_checks_reports'].items() if k.startswith(('time_series', 'one_year'))},
            'stock_months_cap_changed': int(chg.sum()), 'stock_months_cap_appeared': int((np.isnan(ca) & ~np.isnan(cb)).sum()),
            'stock_months_cap_disappeared': int((~np.isnan(ca) & np.isnan(cb)).sum()),
            'companies_with_cap_changes': sorted({PA.ciks[i] for i in np.where(chg.any(axis=0) | (np.isnan(ca) != np.isnan(cb)).any(axis=0))[0]})}
        # F2: JCI
        out['F2_price_error_JCI_200707'] = lc.get('price_errors_set_missing')
        # F3: 兄弟の記号（構成の CIK が変わった株月）
        ma, mc = PB.member, PC.member
        dif = ma != mc
        changes = collections.Counter()
        for ti, i in zip(*np.where(dif)):
            changes[(PA.ciks[i], PA.cand[PA.ciks[i]].get('name'), 'removed' if ma[ti, i] else 'added')] += 1
        out['F3_siblings'] = {'cik_months_changed': int(dif.sum()),
                              'by_company': [{'cik': c, 'name': n, 'change': h, 'months': v} for (c, n, h), v in changes.most_common()],
                              'U_stock_months_changed_incl_JCI_200707': int(((PB.member[:-1] & ~np.isnan(PB.R[1:])) != (PC.member[:-1] & ~np.isnan(PC.R[1:]))).sum())}
        # F4: 節（IT1A_COS・IT7_COS）
        stats = {}
        vals = {}
        for var in ('v3', 'v4', 'nearest'):
            SECTION_VARIANT = var
            per_cik, *_ = load_signals()
            vals[var] = {(c, x['acc']): (x['v'].get('IT1A_COS'), x['v'].get('IT7_COS')) for c, lst in per_cik.items() for x in lst}
        for j, nm in ((0, 'IT1A_COS'), (1, 'IT7_COS')):
            a = {k: v[j] for k, v in vals['v3'].items()}
            b = {k: v[j] for k, v in vals['v4'].items()}
            ks = set(a) | set(b)
            stats[nm] = {'valid_signals_v3': sum(1 for k in ks if a.get(k) is not None), 'valid_signals_v4': sum(1 for k in ks if b.get(k) is not None),
                         'changed': sum(1 for k in ks if a.get(k) is not None and b.get(k) is not None and abs(a[k] - b[k]) > 1e-12),
                         'v3_only': sum(1 for k in ks if a.get(k) is not None and b.get(k) is None),
                         'v4_only': sum(1 for k in ks if a.get(k) is None and b.get(k) is not None),
                         'median_v3': round(float(np.median([v for v in a.values() if v is not None])), 4),
                         'median_v4': round(float(np.median([v for v in b.values() if v is not None])), 4)}
        # 検査役の数え方: 節の語数が前年の半分未満か2倍超の組（取り出しの誤りの印）
        recs = {}
        for fn in os.listdir(D.OUTDIR):
            if fn.endswith('.json'):
                o = json.load(open(os.path.join(D.OUTDIR, fn)))
                for r in o['filings']:
                    recs[r['acc']] = r
        flag = {}
        for key in ('item1a', 'item7'):
            n = f3 = f4 = 0
            for acc, r in recs.items():
                pa = r.get('prev_acc')
                if not pa or pa not in recs or r.get('form') not in D.FORMS_SIGNAL:
                    continue
                p_ = recs[pa]
                w3, pw3 = (r.get('sec_v3') or {}).get(f'{key}_words', r.get(f'{key}_words')), (p_.get('sec_v3') or {}).get(f'{key}_words', p_.get(f'{key}_words'))
                w4, pw4 = r.get(f'{key}_words'), p_.get(f'{key}_words')
                if w3 and pw3 and (r.get('sec_v3') or {}).get(f'{key}_cos', r.get(f'{key}_cos')) is not None:
                    n += 1
                    f3 += not (0.5 <= w3 / pw3 <= 2)
                if w4 and pw4 and r.get(f'{key}_cos') is not None:
                    f4 += not (0.5 <= w4 / pw4 <= 2)
            flag[key] = {'pairs_v3': n, 'len_ratio_outside_0.5_2_v3': f3, 'len_ratio_outside_0.5_2_v4': f4}
        stats['section_length_jumps'] = flag
        out['F4_sections'] = stats
        # F3 の残り: Breeze-Eastern（99359）は兄弟の記号を直した後も、自分の記号 TT を名乗るので 2002-05〜2008-05 の S&P の TT
        # （American Standard／Trane Inc.・構成表は後の記号 TT で書く）の枠に L1 で結ばれ、株価は後継の記号 TT（Yahoo＝旧 Ingersoll-Rand plc）になる。
        # これは事前登録の同定の約束（L1・C の株価の記号）どおりの結果（記号の再利用）なので格付けは変えず、99359 を全期間外した版を報告だけする
        try:
            per = json.load(open(OUT_PATH)).get('periods') or {}
        except Exception:  # noqa
            per = {}
        st0, st1 = (per.get('full') or [FULL_START0])[0], per.get('it1a_start') or FULL_START0
        SIGc, Fc = signal_mats(PC)
        i_b = PC.idx.get(99359)
        bm = [PC.months[ti] for ti in range(1, PC.T) if i_b is not None and PC.member[ti - 1, i_b] and not np.isnan(PC.R[ti, i_b])] if i_b is not None else []
        rows_b = []
        for sp in rule_specs():
            st = st1 if sp['start_rule'] == 'it1a' else st0
            r0 = run(PC, sp, SIGc, Fc, st)
            r1 = run(PC, sp, SIGc, Fc, st, drop=i_b) if i_b is not None else r0
            e0, e1 = N.excess_stats(r0['s'], r0['b'], st, END), N.excess_stats(r1['s'], r1['b'], st, END)
            rows_b.append({'rule': sp['name'], 'full_cagr_diff': e0['cagr_diff'] if e0 else None, 'full_cagr_diff_without_99359': e1['cagr_diff'] if e1 else None,
                           'full_t': e0['t'] if e0 else None, 'full_t_without_99359': e1['t'] if e1 else None})
        out['F3_breeze_remaining_report_only'] = {'priced_months_in_U_after_fix': [bm[0], bm[-1], len(bm)] if bm else None, 'rules': rows_b,
                                                  'reading': ('兄弟の記号の是正の後も 99359 は自分の記号 TT で S&P の TT の枠（2002-05〜2008-05・American Standard／Trane Inc.）に結ばれる'
                                                              '（記号の再利用・事前登録の同定のまま）。全期間外した版は報告だけ（格付けに使わない）')}
    finally:
        FIXES_OFF, SECTION_VARIANT = keep
    return out


def record_fixes(stage_paths, diag_path=None, sens_paths=(), items=None):
    """out/nx_lazy.json（最終の走り）に fixes 欄を書く。stage_paths = [(名前, 走りの json か 'final', 説明)]（段階ごとに是正を1つずつ足した走り・
    最後が是正後）、sens_paths = 同じ形の感度の走り（検査役の案など・格付けに使わない）、items = 誤りごとの確かめと是正の記録"""
    p = OUT_PATH
    obj = json.load(open(p))
    st = []
    for nm, path, desc in list(stage_paths) + list(sens_paths):
        o = json.load(open(path)) if path != 'final' else obj
        st.append((nm, desc, {r['rule']: r for r in o['tested']}, o['summary']['grade_counts'], o.get('run')))
    rules = [r['rule'] for r in obj['tested']]
    by_rule = {}
    for rl in rules:
        row = {}
        for nm, desc, T_, gc, run_ in st:
            r = T_.get(rl)
            if not r:
                continue
            c = r.get('criteria_short_sample') or {}
            row[nm] = {'grade': r['grade'], 'full_ex_ann': r['full']['ex_ann'], 'full_cagr_diff': r['full']['cagr_diff'], 'full_t': r['full']['t'],
                       'p_one': c.get('p_one'), 'holm_p_one': r.get('family_holm_p_one_full'),
                       'drop_top_cagr_diff': (r['drop_top']['full'] or {}).get('cagr_diff'),
                       'cost_full_cagr_diff': (r['cost_0.10pct']['full'] or {}).get('cagr_diff'),
                       'first_half_cagr_diff': (r['first_half'] or {}).get('cagr_diff'), 'second_half_cagr_diff': (r['second_half'] or {}).get('cagr_diff')}
        by_rule[rl] = row
    first, last = stage_paths[0][0], stage_paths[-1][0]
    main_names = [x[0] for x in stage_paths]
    changed_grade = [{'rule': rl, **{nm: by_rule[rl][nm]['grade'] for nm in main_names if nm in by_rule[rl]}} for rl in rules
                     if len({by_rule[rl][nm]['grade'] for nm in main_names if nm in by_rule[rl]}) > 1]
    sens_grade_diff = [{'rule': rl, 'after': by_rule[rl][last]['grade'], **{nm: by_rule[rl][nm]['grade'] for nm, *_ in sens_paths if nm in by_rule[rl]}}
                       for rl in rules if any(nm in by_rule[rl] and by_rule[rl][nm]['grade'] != by_rule[rl][last]['grade'] for nm, *_ in sens_paths)]
    moved = sorted(((rl, by_rule[rl][first]['full_cagr_diff'], by_rule[rl][last]['full_cagr_diff']) for rl in rules
                    if by_rule[rl][first]['full_cagr_diff'] != by_rule[rl][last]['full_cagr_diff']), key=lambda x: -abs(x[2] - x[1]))
    diag = json.load(open(diag_path)) if diag_path else None
    obj['fixes'] = {
        'date': '2026-09-29',
        'what': '検査役の報告（4件）を1件ずつ確かめ、4件とも本当の誤りだったので直して走らせ直した。規則（事前登録）は1本も変えていない。段階ごとに是正を1つずつ足して走らせ、前後の数を並べた',
        'items': items,
        'stages': [{'stage': nm, 'what': desc, 'grade_counts': gc, 'run': run_} for nm, desc, T_, gc, run_ in st if nm in main_names],
        'sensitivities_not_graded': [{'stage': nm, 'what': desc, 'grade_counts': gc, 'run': run_} for nm, desc, T_, gc, run_ in st if nm not in main_names],
        'grade_changes_across_stages': changed_grade,
        'grade_differences_in_sensitivities_vs_after': sens_grade_diff,
        'full_cagr_diff_moved_before_to_after': [{'rule': rl, 'before': a, 'after': b} for rl, a, b in moved],
        'by_rule': by_rule,
        'panel_diagnostics': diag,
        'how_to_reproduce': ('段階の走りは環境変数で切り替える: NX_LAZY_FIXES_OFF=float_pit,price_errors,siblings NX_LAZY_SECTION_VARIANT=v3（S0＝是正前・公開していた数と全50本で一致）→ '
                             'NX_LAZY_FIXES_OFF=price_errors,siblings NX_LAZY_SECTION_VARIANT=v3（S1）→ NX_LAZY_FIXES_OFF=siblings NX_LAZY_SECTION_VARIANT=v3（S2）→ '
                             'NX_LAZY_SECTION_VARIANT=v3（S3）→ 既定（S4＝是正後）。NX_LAZY_OUT で出力の置き場を変える。panel_diagnostics は python3 night/nx_lazy.py --fix-diagnostics'),
    }
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1, default=lambda o: int(o) if isinstance(o, (np.integer,)) else float(o) if isinstance(o, np.floating) else str(o))
    return obj['fixes']


if __name__ == '__main__' and '--fix-diagnostics' in sys.argv:
    i = sys.argv.index('--fix-diagnostics')
    o = fix_diagnostics()
    json.dump(o, open(sys.argv[i + 1], 'w'), ensure_ascii=False, indent=1, default=lambda x: int(x) if isinstance(x, (np.integer,)) else float(x) if isinstance(x, np.floating) else str(x))
    print(json.dumps(o, ensure_ascii=False, indent=1, default=str)[:6000])
    sys.exit(0)

if __name__ == '__main__' and '--record-fixes' in sys.argv:
    i = sys.argv.index('--record-fixes')
    spec = json.load(open(sys.argv[i + 1]))
    o = record_fixes([tuple(x) for x in spec['stages']], spec.get('diag'), [tuple(x) for x in spec.get('sensitivities', [])], spec.get('items'))
    print(json.dumps({k: o[k] for k in ('stages', 'grade_changes_across_stages')}, ensure_ascii=False, indent=1, default=str)[:6000])
    sys.exit(0)

if __name__ == '__main__' and '--determinism' in sys.argv:
    i = sys.argv.index('--determinism')
    o = determinism_check(sys.argv[i + 1], sys.argv[i + 2] if len(sys.argv) > i + 2 else None)
    print(json.dumps(o, ensure_ascii=False, indent=1, default=str)[:4000])
    sys.exit(0)

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
