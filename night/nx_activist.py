#!/usr/bin/env python3
"""night/nx_activist.py — 角度 nx_activist の測る道具（物言う株主の 13D の後に対象会社を買う）。読むだけ・門の判定には不使用

事前登録: out/nx_activist_prereg.json（測る前に書いてコミット済み。この道具はそれをそのまま実装する）
全体の事前登録: out/nx_prereg.json（criteria_short_sample）。統計と格付けは night/nx_common.py をそのまま使う
事象の一覧: out/_nx_cache/nx_activist/events.json（night/nx_activist_data.py が作る）。最初に sha256 を事前登録と照合し、違えば止まる

段
  prices : Yahoo の月次（事象の対象・SPY・IWM・QQQ・実在の器・SURV_EW の母集団）と日次（L_NOW の対象・SPY・E10 と外れ値の確認）を
           取ってキャッシュする（out/_nx_cache/yh_*.json・nx_common.yahoo と同じ URL・同じ名前）。SEC へは取りに行かない
  run    : 全規則を測って out/nx_activist.json へ（tested に主6・探索13・報告11 を1本残らず）

約束
- 株価は今の記号だけ（生き残りの偏りあり）。欠けは base・下限版（−30%）・中立版（超過0）と SURV_EW（同じ偏りを持つ相手）で挟む
- 欠測を 0 と読まない（ルール7）。Yahoo の系列が買う月の終値を持たない事象は base に入れない（被覆率を報告）
- 結果を見た後に足した分析は『事後』と明記し、格付けに使わない
"""
import sys, os, re, io, json, gzip, time, math, datetime, hashlib, argparse, collections, statistics as S, urllib.request, urllib.parse, urllib.error
import random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

BASE = N.BASE
CACHE = N.CACHE
D = os.path.join(CACHE, 'nx_activist')
PRE_PATH = os.path.join(BASE, 'out', 'nx_activist_prereg.json')
OUT_NAME = 'nx_activist.json'
VERSION = 'nx_activist v1.1 (2026-09-28・検査役の指摘3件〔E10 の費用・報告の単位の評価の終わり・会社ごとの重複の境界〕を是正）'

EVENT_END = '2026-07-31'
EVAL_END = 202608            # 最後の完全な月
IWM_START = 200007
EVENT_START = '1996-07-01'
MECH_START = '2000-07-01'
PRE2007_START = '2007-01-01'
COST_PRIMARY, COST_SENS = 0.003, (0.005, 0.010)
LOWER_HIT = -0.30
OUTLIER_UP, OUTLIER_DN = 3.0, -0.90


# ───────────────────────── Yahoo（nx_common.yahoo と同じ URL・同じキャッシュ名） ─────────────────────────
class NoData(Exception):
    pass


def _yh_name(ticker, interval):
    return f'yh_{ticker.replace("^", "IDX_").replace("=", "_")}_{interval}.json'


def yh_raw(ticker, interval='1mo', max_age_days=7, tries=5):
    """Yahoo の chart JSON（bytes→dict）。404（記号が無い）は NoData をすぐ上げる（再試行しない）。キャッシュは nx_common.get と同じ場所・名前"""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, _yh_name(ticker, interval))
    miss = p + '.404'
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < max_age_days * 86400:
        raise NoData(ticker)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400 and os.path.getsize(p) > 0:
        return json.loads(open(p, 'rb').read())
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1=0&period2={int(time.time())}&interval={interval}&events=div%2Csplit'
    err = None
    for i in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=N.UA), timeout=120).read()
            j = json.loads(b)
            if not (j.get('chart') or {}).get('result'):
                open(miss, 'w').write('no result')
                raise NoData(ticker)
            tmp = f'{p}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b)
            os.replace(tmp, p)
            return j
        except NoData:
            raise
        except urllib.error.HTTPError as e:
            err = e
            if e.code == 404:
                open(miss, 'w').write('404')
                raise NoData(ticker)
            time.sleep(2 ** (i + 1))
        except Exception as e:  # noqa
            err = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'Yahoo 取得失敗 {ticker} {interval}: {err}')


def yh_prices(ticker, interval='1mo'):
    """調整後終値 {yyyymm or yyyymmdd: 値}・分割の記録 [(日付int, 倍率)]。日付は取引所の現地時刻（gmtoffset）で決める。
    米国の記号では nx_common.yahoo と同じ日付の鍵になる"""
    j = yh_raw(ticker, interval)
    r = j['chart']['result'][0]
    ts = r.get('timestamp') or []
    off = (r.get('meta') or {}).get('gmtoffset') or 0
    ind = r.get('indicators', {})
    adj = (ind.get('adjclose') or [{}])[0].get('adjclose') or (ind.get('quote') or [{}])[0].get('close') or []
    px = {}
    for t, a in zip(ts, adj):
        if a is None or a <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(t + off)
        k = d.year * 100 + d.month if interval == '1mo' else d.year * 10000 + d.month * 100 + d.day
        px[k] = a
    spl = []
    for v in ((r.get('events') or {}).get('splits') or {}).values():
        d = datetime.datetime.utcfromtimestamp(v['date'] + off)
        try:
            spl.append((d.year * 10000 + d.month * 100 + d.day, float(v['numerator']) / float(v['denominator'])))
        except (KeyError, ZeroDivisionError, TypeError, ValueError):
            pass
    return px, sorted(spl)


def ym_add(ym, k):
    y, m = divmod(ym, 100)
    m0 = y * 12 + (m - 1) + k
    return (m0 // 12) * 100 + m0 % 12 + 1


def ym_range(a, z):
    out = []
    while a <= z:
        out.append(a)
        a = ym_add(a, 1)
    return out


def monthly_returns(px, upto=EVAL_END):
    """{yyyymm: 値} → {yyyymm: 前の暦月からのリターン}（前の暦月に値が無い月は入れない＝飛んだ月をまたいで繋がない）"""
    out = {}
    for k in sorted(px):
        if k > upto:
            continue
        p = ym_add(k, -1)
        if p in px:
            out[k] = px[k] / px[p] - 1
    return out


# ───────────────────────── 事象 ─────────────────────────
def load_prereg():
    return json.load(open(PRE_PATH, encoding='utf-8'))


def load_events(pre):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nx_activist_data as A
    o = A._load_json(os.path.join(D, 'events.json'))
    sha, sha_ev = A.events_sha(o), A.events_sha(o, with_tickers=False)
    want, want_ev = pre['tools']['events_sha256'], pre['tools']['events_sha256_events_only']
    if sha_ev != want_ev:
        raise SystemExit(f'事象の指紋（ティッカー抜き）が事前登録と違う: {sha_ev} ≠ {want_ev}。止まる')
    check = {'events_sha256': sha, 'matches_prereg': sha == want, 'events_sha256_events_only': sha_ev, 'events_only_matches_prereg': True,
             'stored_sha256_in_file': o.get('sha256'), 'tickers_file_date': o.get('tickers_file_date')}
    if sha != want:
        # ティッカー表を取り直した場合: 事前登録どおり、事象の指紋が一致することを確かめて進め、ティッカーが変わった数を記録する
        check['note'] = 'ティッカー込みの指紋が違う（ティッカー表の取り直し）。事象だけの指紋は一致したので進める'
    return o, check, A


def usable(e, lst, start, end=EVENT_END, pred=None):
    return (start <= e['date'] <= end and not e.get('exclusion') and not e.get('repeat_24m')
            and (lst is None or lst in e.get('lists', [lst])) and (pred is None or pred(e)))


def dstar(e, use_accept=True):
    d = e['date']
    if use_accept and e.get('acceptance'):
        a = e['acceptance'][:8]
        a = f'{a[:4]}-{a[4:6]}-{a[6:8]}'
        d = max(d, a)
    return int(d.replace('-', ''))


class Cal:
    """NYSE の取引日（SPY の日次の日付）"""
    def __init__(self, spy_daily_px):
        self.days = sorted(spy_daily_px)
        import bisect
        self._b = bisect

    def next_after(self, dint):
        i = self._b.bisect_right(self.days, dint)
        return self.days[i] if i < len(self.days) else None

    def index(self, dint):
        return self._b.bisect_left(self.days, dint)


# ───────────────────────── 段: prices ─────────────────────────
def surv_universe(A):
    """SURV_EW の母集団（事前登録 benchmark.SURV_EW）: 今の上場会社のうち NYSE・Nasdaq で、事業会社の定期報告を最後の400日に出した CIK（1 CIK に pick_ticker で1記号）"""
    idx = A.all_idx()
    reg_op, fund, f13 = A.registrant_spans(idx, with_fund=True)
    tick, td = A.load_tickers()
    cut = (datetime.date.fromisoformat(td) - datetime.timedelta(days=400)).isoformat()
    sel, why = [], collections.Counter()
    for cik, lst in tick.items():
        c = [x for x in lst if x['exchange'] in ('NYSE', 'Nasdaq')]
        if not c:
            why['NYSE・Nasdaq の記号が無い'] += 1
            continue
        v = reg_op.get(cik)
        if not v or v[1] < cut:
            why['最後の400日に事業会社の定期報告が無い'] += 1
            continue
        sel.append((cik, A.pick_ticker(c)['ticker']))
    return sorted(sel), dict(why), cut, td


def event_tickers(o):
    s = set()
    for key in ('events_13d', 'events_contest', 'events_mech'):
        for e in o[key]:
            if e.get('ticker') and not e.get('exclusion') and not e.get('repeat_24m') and e['date'] <= EVENT_END:
                s.add(e['ticker'])
    return s


def now_tickers(o):
    return sorted(set(e['ticker'] for e in o['events_13d'] if e.get('ticker') and usable(e, 'NOW', EVENT_START)))


def cmd_prices(a):
    pre = load_prereg()
    o, chk, A = load_events(pre)
    print('指紋', chk)
    univ, why, cut, td = surv_universe(A)
    mon = sorted(event_tickers(o) | set(t for _, t in univ) | {'SPY', 'IWM', 'QQQ', 'IEP', 'ACTX', 'PSH.L', 'PSH.AS', 'PSHZF'})
    day = sorted(set(now_tickers(o)) | {'SPY'})
    jobs = [(t, '1mo') for t in mon] + [(t, '1d') for t in day]
    print(f'月次 {len(mon)}・日次 {len(day)}・SURV_EW の母集団 {len(univ)}（{why}）', flush=True)
    import concurrent.futures as cf
    st = collections.Counter()

    def one(j):
        try:
            yh_raw(*j)
            return 'ok'
        except NoData:
            return 'nodata'
        except Exception as e:  # noqa
            return 'error'
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(one, jobs)):
            st[r] += 1
            if i % 250 == 0:
                print(f'  {i}/{len(jobs)} {dict(st)} {time.time() - t0:.0f}s', flush=True)
    print('完了', dict(st))


# ───────────────────────── 段: run ─────────────────────────
BENCH = object()   # その月のその会社のリターン = 相手のリターン（超過 0）
HIT = 'hit'


class Data:
    """株価・相手・暦をまとめて持つ（run の中で1回だけ読む）"""
    def __init__(self, o, A, log):
        self.o, self.A, self.log = o, A, log
        self.pxm, self.nodata, self.err = {}, set(), set()
        spy_d, _ = yh_prices('SPY', '1d')
        self.spy_daily = {k: v for k, v in spy_d.items() if k <= EVAL_END * 100 + 31}
        self.cal = Cal(self.spy_daily)
        self.bench = {}
        for t in ('SPY', 'IWM', 'QQQ'):
            px, _ = yh_prices(t, '1mo')
            self.bench[t] = monthly_returns(px)
        self.bench['IWM'] = {k: v for k, v in self.bench['IWM'].items() if k >= IWM_START}
        ff = N.ff_factors()
        self.rf = ff['rf']
        self.bench['FF_MKT'] = ff['mkt']
        sm = N.french_series('Portfolios_Formed_on_ME', want='Value Weight Returns -- Monthly')
        self.bench['FF_SMALL_LO30_VW'] = sm['Lo 30']
        self.splits = {}

    def px(self, tk):
        if tk in self.pxm:
            return self.pxm[tk]
        if tk in self.nodata:
            return None
        try:
            p, spl = yh_prices(tk, '1mo')
            p = {k: v for k, v in p.items() if k <= EVAL_END}
            self.pxm[tk], self.splits[tk] = p, spl
            return p
        except NoData:
            self.nodata.add(tk)
            return None
        except Exception as e:  # noqa
            self.err.add(tk)
            self.log.append(f'Yahoo 取得失敗 {tk}: {e}')
            return None


# ── 外れ値（+300% 超・−90% 未満の月）の確認: 日次と Yahoo の分割の記録で「データの誤り」と確かめられたときだけ値の無い月にする ──
OUTLIER_RULE = ('月次リターンが +300% 超か −90% 未満の月（対象会社の保有に入り得る月）を一覧にし、次のどれかで「データの誤り」と確かめられたときだけ'
                'その月（と、すぐ戻した翌月）を値の無い月として扱う（その月のその会社の超過は 0＝相手と同じ）。'
                '(a) Yahoo の分割の記録がその月（前後5日を含む）にあり、倍率で割る・掛けると動きが 1.5倍以内に収まる（分割の取り違え）、'
                '(b) 日次の調整後終値で同じ月を複利にした値と月次の値が 1.5倍を超えて食い違う。'
                'どれにも当たらなければ本物の動きとして残す。実装の中で決めた規則（事前登録は「日次と突き合わせ、データの誤りと確かめられたとき」までを決めていた）。'
                '★初めの案には (c)「日次で1日に3倍超・1/10未満の動きが10取引日以内に戻る」もあったが、外れ値の一覧（規則の成績は未計算）で '
                'AMC 2021-01（ミーム株の本物の急騰と反落・出来高1億株超）を誤りと判定したので、(c) は誤りを確かめる規則にならないとして外した')


def check_outliers(dat, tk_months):
    """tk_months: {記号: 保有に入り得る月の集合}。戻り値: 誤りの月 {記号: set(月)}・一覧"""
    errs, rows = collections.defaultdict(set), []
    for tk, months in sorted(tk_months.items()):
        px = dat.px(tk)
        if not px:
            continue
        mr = monthly_returns(px)
        for t in sorted(months):
            r = mr.get(t)
            if r is None or OUTLIER_DN <= r <= OUTLIER_UP:
                continue
            row = {'ticker': tk, 'month': t, 'r_monthly': round(r, 4)}
            why = None
            # (a) 分割
            lo, hi = (ym_add(t, -1) * 100) + 25, (ym_add(t, 1) * 100) + 5
            for d, s in dat.splits.get(tk, []):
                if lo <= d <= hi and s > 0:
                    for f in (s, 1 / s):
                        if 1 / 1.5 <= (1 + r) * f <= 1.5:
                            why = f'(a) 分割 {d} 倍率 {s:g}'
            # 日次
            try:
                dpx, _ = yh_prices(tk, '1d')
            except Exception as e:  # noqa
                dpx = {}
                row['daily'] = f'日次なし: {e.__class__.__name__}'
            if why is None and dpx:
                ks = sorted(dpx)
                prev = [k for k in ks if k // 100 < t]
                cur = [k for k in ks if k // 100 == t]
                if prev and cur:
                    rd = dpx[cur[-1]] / dpx[prev[-1]] - 1
                    row['r_daily_compounded'] = round(rd, 4)
                    if abs(math.log((1 + r) / (1 + rd))) > math.log(1.5):
                        why = f'(b) 日次の複利 {rd:+.3f} と月次 {r:+.3f} が食い違う'
            row['error'] = why
            if why:
                errs[tk].add(t)
                # すぐ戻した翌月も値の無い月にする（誤値の山の反対側）
                t2 = ym_add(t, 1)
                r2 = mr.get(t2)
                if r2 is not None and 1 / 1.5 <= (1 + r) * (1 + r2) <= 1.5:
                    errs[tk].add(t2)
                    row['reversal_month_also_dropped'] = t2
            rows.append(row)
    return errs, rows


# ── 規則の定義（事前登録 families） ──
def rule_specs():
    NOW = dict(src='events_13d', lst='NOW', start=EVENT_START, accept=True)
    PRE07 = dict(src='events_13d', lst='PRE', start=PRE2007_START, accept=True)
    MECH = dict(src='events_mech', lst=None, start=MECH_START, accept=False)
    P = {
        'P1_NOW_H12_SPY': dict(NOW, H=12, bench='SPY'),
        'P2_NOW_H24_SPY': dict(NOW, H=24, bench='SPY'),
        'P3_NOW_H12_IWM': dict(NOW, H=12, bench='IWM'),
        'P4_PRE2007_H12_SPY': dict(PRE07, H=12, bench='SPY'),
        'P5_MECH_H12_SPY': dict(MECH, H=12, bench='SPY'),
        'P6_NOW_H12_SURV': dict(NOW, H=12, bench='SURV_EW'),
    }
    E = {
        'E1_NOW_H6_SPY': dict(NOW, H=6, bench='SPY'),
        'E2_NOW_H36_SPY': dict(NOW, H=36, bench='SPY'),
        'E3_NOW_H24_IWM': dict(NOW, H=24, bench='IWM'),
        'E4_NOW_H12_recent10_SPY': dict(NOW, H=12, bench='SPY', select='recent10'),
        'E5_PRE_all_H12_SPY': dict(src='events_13d', lst='PRE', start=EVENT_START, accept=True, H=12, bench='SPY'),
        'E6_PRE2007_H12_IWM': dict(PRE07, H=12, bench='IWM'),
        'E7_PRE2007_H24_SPY': dict(PRE07, H=24, bench='SPY'),
        'E8_MECH_H12_IWM': dict(MECH, H=12, bench='IWM'),
        'E9_MECH_H12_SURV': dict(MECH, H=12, bench='SURV_EW'),
        'E10_NOW_daily_T1_H252_SPY': dict(NOW, H=252, bench='SPY', mode='daily'),
        'E11_NOW_contest_H12_SPY': dict(src='events_contest', lst='NOW', start=EVENT_START, accept=True, H=12, bench='SPY'),
        'E12_NOWonly_H12_SPY': dict(NOW, H=12, bench='SPY', pred='now_only'),
        'E13_MECH_anonymous_H12_SPY': dict(MECH, H=12, bench='SPY', pred='anonymous'),
    }
    return P, E


PREDS = {None: None, 'now_only': lambda e: 'PRE' not in e.get('lists', []),
         'anonymous': lambda e: not e.get('in_L_NOW_or_L_PRE')}


def rule_events(o, spec, extra_pred=None):
    pr = PREDS[spec.get('pred')]
    pred = (lambda e: (pr is None or pr(e)) and (extra_pred is None or extra_pred(e)))
    return [e for e in o[spec['src']] if usable(e, spec['lst'], spec['start'], pred=pred)]


# ── 月次の保有と規則のリターン ──
def build_positions(dat, events, H, accept, version, errs):
    """version: base / lower / neutral。戻り値: 保有のリスト（会社単位で重ねない）"""
    cand = []
    for e in events:
        t1 = dat.cal.next_after(dstar(e, accept))
        if t1 is None:
            continue
        M = t1 // 100
        if M >= EVAL_END:
            continue  # 保有の月が無い
        tk = e.get('ticker')
        px = dat.px(tk) if tk else None
        priced = bool(px and M in px)
        cand.append((M, e['date'], e['acc'], e, tk, px, priced))
    cand.sort(key=lambda x: (x[0], x[1], x[2]))
    held_until, pos = {}, []
    for M, date, acc, e, tk, px, priced in cand:
        if version == 'base' and not priced:
            continue
        cik = e['subject_cik']
        if cik in held_until and M <= held_until[cik]:
            # 持っている間に来た事象は無視（保有を延ばさない・二重に持たない・事前登録 event_rules.target_unit）。
            # held_until = 最後に持つ月（その月末に売る）。買う月 M がそれ以下＝翌取引日 t1 が売る月末以前＝持っている間に来た。
            # v1 は `M < held_until` で、最後の保有の月に来た事象が売ると同時に新しい保有を開き、保有を延ばしていた（検査役の指摘・FIXES F3）
            continue
        end = ym_add(M, H)
        held_until[cik] = end
        rets = {}
        broken = False
        broken_at = None
        for t in ym_range(ym_add(M, 1), min(end, EVAL_END)):
            if not priced:
                rets[t] = BENCH if version == 'neutral' else (LOWER_HIT if t == ym_add(M, 1) else 0.0)
                continue
            if broken:
                rets[t] = BENCH if version == 'neutral' else 0.0
                continue
            if t in px and ym_add(t, -1) in px:
                rets[t] = BENCH if t in errs.get(tk, ()) else px[t] / px[ym_add(t, -1)] - 1
            else:
                broken, broken_at = True, t
                rets[t] = BENCH if version == 'neutral' else (LOWER_HIT if version == 'lower' else 0.0)
        pos.append({'cik': cik, 'ticker': tk, 'M': M, 'end': end, 'acc': acc, 'date': date, 'families': e.get('families') or e.get('serial_names'),
                    'priced': priced, 'rets': rets, 'broken_at': broken_at})
    return pos


def select_recent10(held):
    return sorted(held, key=lambda p: (-p['M'], p['acc']))[:10]


def run_portfolio(pos, bench, select=None, exclude_cik=None):
    """毎月末に等分へ戻す。1社 = 1/max(n,10)、残りは相手。戻り値: 規則の月次リターン・保有数・回転・会社ごとの寄与"""
    active = collections.defaultdict(list)
    for p in pos:
        if exclude_cik is not None and p['cik'] == exclude_cik:
            continue
        for t in p['rets']:
            active[t].append(p)
    if not active:
        return None
    months = ym_range(min(active), EVAL_END)
    R, nh, turn, contrib, wmap = {}, {}, {}, collections.defaultdict(lambda: collections.defaultdict(float)), {}
    drift = {}
    for t in months:
        rb = bench.get(t)
        held = active.get(t, [])
        if select:
            held = select(held)
        if rb is None:
            drift = {}
            continue
        n = len(held)
        nh[t] = n
        w = 1.0 / max(n, 10)
        new_w = {}
        tot = 0.0
        rs = {}
        for p in held:
            r = p['rets'][t]
            r = rb if r is BENCH else r
            rs[id(p)] = r
            tot += w * r
            contrib[p['cik']][t] += w * (r - rb)
            if p['priced'] and (p['broken_at'] is None or t < p['broken_at']):
                new_w[id(p)] = w
        Rt = tot + (1 - n * w) * rb
        R[t] = Rt
        keys = set(new_w) | set(drift)
        turn[t] = 0.5 * sum(abs(new_w.get(k, 0.0) - drift.get(k, 0.0)) for k in keys)
        drift = {k: v * (1 + rs[k]) / (1 + Rt) for k, v in new_w.items()}
    return {'R': R, 'n': nh, 'turn': turn, 'contrib': contrib}


def eval_start(nh, floor=None):
    ms = sorted(m for m in nh if floor is None or m >= floor)
    for m in ms:
        if nh[m] >= 10:
            return m, 'n>=10'
    for m in ms:
        if nh[m] >= 1:
            return m, 'fallback: n が10社に届かない＝最初に1社以上を持った月'
    return None, 'no holdings'


def net_of_cost(R, turn, c):
    return {t: r - c * turn.get(t, 0.0) for t, r in R.items()}


def halves(months):
    k = len(months) // 2
    return months[:k], months[k:]


def rs_stats(s, b, months, a=None, z=None):
    ms = [m for m in months if (a is None or m >= a) and (z is None or m <= z)]
    if not ms:
        return None
    return N.excess_stats({m: s[m] for m in ms if m in s}, {m: b[m] for m in ms if m in b})


def summarize_series(s, b, rf, months):
    """格付けの材料をまとめる（規則 s・相手 b は同じ月だけ）"""
    first, second = halves(months)
    ss = {m: s[m] for m in months}
    bb = {m: b[m] for m in months}
    out = {
        'full': N.excess_stats(ss, bb),
        'first_half': rs_stats(s, b, first),
        'second_half': rs_stats(s, b, second),
        'train_to_2006': rs_stats(s, b, months, z=N.TRAIN_END),
        'hold_2007_on': rs_stats(s, b, months, a=N.HOLD_START),
        'post_pub_2009_on': rs_stats(s, b, months, a=200901),
        'recent_2013_07_on': rs_stats(s, b, months, a=N.RECENT_START),
        'roll20': N.rolling(ss, bb, 20),
        'dca20': N.dca(ss, bb, 20),
        'maxdd': {'rule': round(N.maxdd(ss), 4), 'bench': round(N.maxdd(bb), 4)},
        'sharpe': {'full': (N.sharpe(ss, rf), N.sharpe(bb, rf)),
                   'train_to_2006': (N.sharpe(ss, rf, z=N.TRAIN_END), N.sharpe(bb, rf, z=N.TRAIN_END)),
                   'hold_2007_on': (N.sharpe(ss, rf, a=N.HOLD_START), N.sharpe(bb, rf, a=N.HOLD_START))},
        'halves_split': {'first': [first[0], first[-1]] if first else None, 'second': [second[0], second[-1]] if second else None},
    }
    return out


def eval_monthly(dat, o, spec, errs, surv, extra_pred=None, events=None, end_at_last_holding=False):
    """end_at_last_holding: 報告だけの単位（R1 の家ごと・R2 の時代ごと・R_C5_2 の PRE だけの家）で True。
    評価の終わりを、その単位が base・下限版・中立版のどれかで最後に会社を持っていた月にする（その後は保有が無く超過 0 の月が続くだけで、
    年率の大きさを薄める・FIXES F2）。主・探索の規則は事前登録どおり 2026-08 まで（False）"""
    events = events if events is not None else rule_events(o, spec, extra_pred)
    bench = surv if spec['bench'] == 'SURV_EW' else dat.bench[spec['bench']]
    sel = select_recent10 if spec.get('select') == 'recent10' else None
    pos = {v: build_positions(dat, events, spec['H'], spec['accept'], v, errs) for v in ('base', 'lower', 'neutral')}
    runs = {v: run_portfolio(pos[v], bench, sel) for v in pos}
    cov = coverage(dat, events, spec, pos)
    base = runs['base']
    if base is None:
        return {'coverage': cov, 'error': 'base に保有が無い'}
    st, how = eval_start(base['n'], IWM_START if spec['bench'] == 'IWM' else None)
    if st is None:
        return {'coverage': cov, 'error': 'base に保有が無い'}
    months_to_eval_end = [m for m in sorted(base['R']) if m >= st]
    end_rule = '2026-08（事前登録 portfolio.eval_window）'
    if end_at_last_holding:
        last_held = max(m for v in ('base', 'lower', 'neutral') if runs.get(v) for m, k in runs[v]['n'].items() if k >= 1)
        months = [m for m in months_to_eval_end if m <= last_held]
        end_rule = ('その単位が base・下限版・中立版のどれかで最後に会社を持っていた月（報告だけの単位・FIXES F2）'
                    if last_held < months_to_eval_end[-1] else '最後に会社を持っていた月＝2026-08')
    else:
        months = months_to_eval_end
    R = base['R']
    res = {'coverage': cov, 'eval': {'from': months[0], 'to': months[-1], 'months': len(months), 'rule': how,
                                     'end_rule': end_rule, 'bench': spec['bench']}}
    if end_at_last_holding:
        # 参考: v1 の読み（2026-08 まで・保有が無い月は超過 0）。幾何の超過の符号は同じ（保有の無い月は両方が同じ値で伸びる）で、大きさだけ薄まる
        res['full_to_2026_08_with_trailing_zero_excess'] = rs_stats(R, bench, months_to_eval_end)
        # 保有の窓の幾何の年率差（最短の月数なし）。excess_stats は24か月未満の窓に統計を出さない（full = null）ので、
        # 家・時代の「幾何の超過が正か」（C5 の代わり）はこれで数える＝v1 の数え方（末尾に超過0の月を付けた窓の cagr_diff）と符号が必ず一致する
        dh = N.cagr([R[m] for m in months]) - N.cagr([bench[m] for m in months])
        res['cagr_diff_holding_window'] = round(dh * 100, 2)
        res['holding_window_positive'] = dh > 0
    nlist = [base['n'][m] for m in months]
    res['held'] = {'mean': round(S.mean(nlist), 1), 'min': min(nlist), 'max': max(nlist), 'months_n_lt_10': sum(1 for x in nlist if x < 10),
                   'positions_base': len(pos['base']), 'positions_with_missing': len(pos['lower']),
                   'positions_base_broken_mid_hold': sum(1 for p in pos['base'] if p['broken_at'])}
    res.update(summarize_series(R, bench, dat.rf, months))
    # 費用
    tv = [base['turn'].get(m, 0.0) for m in months]
    res['turnover_oneway_annual'] = round(S.mean(tv) * 12, 3)
    res['cost'] = {}
    for c in (COST_PRIMARY,) + COST_SENS:
        Rc = net_of_cost(R, base['turn'], c)
        res['cost'][f'{c * 100:.2f}%'] = {'full': rs_stats(Rc, bench, months), 'hold_2007_on': rs_stats(Rc, bench, months, a=N.HOLD_START),
                                          'train_to_2006': rs_stats(Rc, bench, months, z=N.TRAIN_END)}
    # 欠けの下限版・中立版（同じ評価の月）
    for v in ('lower', 'neutral'):
        Rv = runs[v]['R']
        ms = [m for m in months if m in Rv]
        res[f'missing_{v}'] = {'full': rs_stats(Rv, bench, ms), 'hold_2007_on': rs_stats(Rv, bench, ms, a=N.HOLD_START)}
    # 最大寄与の1社を抜く
    tot = {cik: sum(v for m, v in d.items() if m >= st) for cik, d in base['contrib'].items()}
    top = max(tot, key=tot.get)
    tk = next((p['ticker'] for p in pos['base'] if p['cik'] == top), None)
    dr = run_portfolio(pos['base'], bench, sel, exclude_cik=top)
    res['drop_top'] = {'cik': top, 'ticker': tk, 'contribution_sum': round(tot[top], 4),
                       'n_positions_of_top': sum(1 for p in pos['base'] if p['cik'] == top),
                       'full': rs_stats(dr['R'], bench, [m for m in months if m in dr['R']])}
    top5 = sorted(tot.items(), key=lambda kv: -kv[1])[:5]
    bot5 = sorted(tot.items(), key=lambda kv: kv[1])[:5]
    tkmap = {p['cik']: p['ticker'] for p in pos['base']}
    res['contribution_top5'] = [(tkmap.get(c), c, round(v, 4)) for c, v in top5]
    res['contribution_bottom5'] = [(tkmap.get(c), c, round(v, 4)) for c, v in bot5]
    res['_series'] = {'R': R, 'bench': bench, 'months': months, 'turn': base['turn'], 'pos_base': pos['base']}
    return res


def coverage(dat, events, spec, pos=None):
    by = collections.defaultdict(lambda: collections.Counter())
    for e in events:
        y = e['date'][:4]
        by[y]['events'] += 1
        tk = e.get('ticker')
        if not tk:
            by[y]['no_ticker'] += 1
            continue
        by[y]['ticker'] += 1
        px = dat.px(tk)
        if px is None:
            by[y]['yahoo_no_series' if tk in dat.nodata else 'yahoo_error'] += 1
            continue
        t1 = dat.cal.next_after(dstar(e, spec['accept']))
        M = t1 // 100 if t1 else None
        if M is None or M >= EVAL_END:
            by[y]['buy_month_after_eval_end'] += 1
        elif M in px:
            by[y]['priced_buy_month'] += 1
        else:
            by[y]['yahoo_series_lacks_buy_month'] += 1
    tot = collections.Counter()
    for c in by.values():
        tot.update(c)
    out = {'total': dict(tot), 'priced_share': round(tot['priced_buy_month'] / max(1, tot['events']), 3),
           'by_year': {y: dict(c) for y, c in sorted(by.items())}}
    if pos:
        out['positions'] = {v: len(p) for v, p in pos.items()}
    return out


# ── E10: 日次（翌取引日の終値で買い、252取引日後に売る） ──
def eval_daily(dat, o, spec, events=None):
    events = events if events is not None else rule_events(o, spec)
    days = dat.cal.days
    spy = dat.spy_daily
    dix = {d: i for i, d in enumerate(days)}
    last_day = max(d for d in days if d // 100 <= EVAL_END)
    dcache = {}

    def dpx(tk):
        if tk not in dcache:
            try:
                p, _ = yh_prices(tk, '1d')
                dcache[tk] = p
            except Exception:  # noqa
                dcache[tk] = None
        return dcache[tk]

    def build(version, exclude=None):
        cand = []
        for e in events:
            t1 = dat.cal.next_after(dstar(e, spec['accept']))
            if t1 is None or t1 >= last_day:
                continue
            tk = e.get('ticker')
            p = dpx(tk) if tk else None
            priced = bool(p and t1 in p)
            cand.append((t1, e['date'], e['acc'], e, tk, p, priced))
        cand.sort(key=lambda x: (x[0], x[1], x[2]))
        held_until, pos = {}, []
        for t1, date, acc, e, tk, p, priced in cand:
            if version == 'base' and not priced:
                continue
            cik = e['subject_cik']
            if exclude is not None and cik == exclude:
                continue
            if cik in held_until and t1 <= held_until[cik]:
                continue  # 売る日（その日の終値で売る）以前に来た事象は持っている間に来た＝無視（月次と同じ・FIXES F3）
            i1 = dix[t1]
            iend = min(i1 + spec['H'], len(days) - 1)
            end = days[iend]
            held_until[cik] = end
            pos.append({'cik': cik, 'ticker': tk, 'i1': i1, 'iend': iend, 'sold': i1 + spec['H'] <= len(days) - 1, 'priced': priced, 'p': p, 'acc': acc,
                        'last': max(p) if p else None, 'keys': sorted(p) if p else None})
        return pos

    import bisect

    def P(pp, d):
        ks = pp['keys']
        j = bisect.bisect_right(ks, d) - 1
        return pp['p'][ks[j]] if j >= 0 else None

    def run(pos, version):
        # 月ごとに: 各社の保有日の複利 − 同じ日の SPY の複利 を 1/max(n,10) で
        per_m = collections.defaultdict(list)   # m -> [(pos, a_idx, z_idx)]
        for pp in pos:
            i = pp['i1'] + 1
            while i <= pp['iend'] and days[i] <= last_day:
                m = days[i] // 100
                j = i
                while j + 1 <= pp['iend'] and days[j + 1] // 100 == m and days[j + 1] <= last_day:
                    j += 1
                per_m[m].append((pp, i - 1, j))
                i = j + 1
        ex, nh, cost_w, contrib = {}, {}, collections.defaultdict(float), collections.defaultdict(lambda: collections.defaultdict(float))
        for m in sorted(per_m):
            lst = per_m[m]
            n = len(lst)
            nh[m] = n
            w = 1.0 / max(n, 10)
            tot = 0.0
            for pp, ia, iz in lst:
                a, z = days[ia], days[iz]
                rs = spy[z] / spy[a] - 1
                first_month = (ia == pp['i1'])
                if not pp['priced']:
                    r = rs if version == 'neutral' else ((1 + LOWER_HIT) - 1 if first_month else 0.0)
                else:
                    L = pp['last']
                    if a >= L:  # 途切れた後
                        r = rs if version == 'neutral' else 0.0
                    elif z <= L:
                        r = P(pp, z) / P(pp, a) - 1
                    else:  # この月の途中で途切れた
                        r0 = P(pp, L) / P(pp, a) - 1
                        if version == 'neutral':
                            r = (1 + r0) * (spy[z] / spy[max(d for d in days[ia:iz + 1] if d <= L)]) - 1
                        elif version == 'lower':
                            r = (1 + r0) * (1 + LOWER_HIT) - 1
                        else:
                            r = r0
                tot += w * (r - rs)
                contrib[pp['cik']][m] += w * (r - rs)
                if pp['priced']:
                    # 片道の回転 = ½Σ|Δw|（相手の枠は数えない）＝事前登録 costs.turnover・月次の run_portfolio と同じ定義。
                    # 入る 0→w で ½w、出る w→0 で ½w。v1 は w を足していた（Σ|Δw| の両側＝2倍・検査役の指摘・FIXES F1）
                    if first_month:
                        cost_w[m] += 0.5 * w
                    if iz == pp['iend'] and pp['sold']:
                        # 252取引日後に本当に売ったときだけ。評価の終わり（2026-08）で打ち切った保有は売っていない
                        # ＝月次の規則が評価の終わりに持っている会社へ売りの費用を掛けないのと同じ（FIXES F1b）
                        cost_w[m] += 0.5 * w
            ex[m] = tot
        return ex, nh, cost_w, contrib

    # SPY の月次（日次から）
    spym = {}
    lastc = {}
    for d in days:
        if d // 100 <= EVAL_END:
            lastc[d // 100] = d
    ms_all = sorted(lastc)
    for pm, m in zip(ms_all, ms_all[1:]):
        spym[m] = spy[lastc[m]] / spy[lastc[pm]] - 1
    pos = {v: build(v) for v in ('base', 'lower', 'neutral')}
    runs = {v: run(pos[v], v) for v in pos}
    ex, nh, cost_w, contrib = runs['base']
    st, how = eval_start(nh)
    months = [m for m in sorted(ex) if m >= st and m in spym]

    def to_s(exd):
        return {m: spym[m] + exd.get(m, 0.0) for m in months}
    R = to_s(ex)
    res = {'coverage': {'events': len(events), 'positions': {v: len(p) for v, p in pos.items()},
                        'priced_share': round(len(pos['base']) / max(1, len(pos['lower'])), 3)},
           'eval': {'from': months[0], 'to': months[-1], 'months': len(months), 'rule': how, 'bench': 'SPY（日次から作った月次）'}}
    nlist = [nh.get(m, 0) for m in months]
    res['held'] = {'mean': round(S.mean(nlist), 1), 'min': min(nlist), 'max': max(nlist), 'months_n_lt_10': sum(1 for x in nlist if x < 10)}
    b = {m: spym[m] for m in months}
    res.update(summarize_series(R, b, dat.rf, months))
    res['turnover_oneway_annual'] = round(S.mean([cost_w.get(m, 0.0) for m in months]) * 12, 3)
    res['turnover_note'] = ('片道の回転 ½Σ|Δw|（相手の枠は数えない）のうち、入る（½w）と 252取引日後に売る（½w）だけ。'
                            '等分への戻しは入れない（月次の規則はそれも数える）＝その分だけ小さい')
    res['cost'] = {}
    for c in (COST_PRIMARY,) + COST_SENS:
        Rc = {m: R[m] - c * cost_w.get(m, 0.0) for m in months}
        res['cost'][f'{c * 100:.2f}%'] = {'full': rs_stats(Rc, b, months), 'hold_2007_on': rs_stats(Rc, b, months, a=N.HOLD_START),
                                          'train_to_2006': rs_stats(Rc, b, months, z=N.TRAIN_END),
                                          'note': '片道の回転（½Σ|Δw|）のうち入る・出るの売買だけ（等分への戻しを入れない近似・その分だけ甘い）'}
    for v in ('lower', 'neutral'):
        Rv = to_s(runs[v][0])
        res[f'missing_{v}'] = {'full': rs_stats(Rv, b, months), 'hold_2007_on': rs_stats(Rv, b, months, a=N.HOLD_START)}
    tot = {cik: sum(v for m, v in d.items() if m >= st) for cik, d in contrib.items()}
    top = max(tot, key=tot.get)
    exd, _, _, _ = run(build('base', exclude=top), 'base')
    tkmap = {p['cik']: p['ticker'] for p in pos['base']}
    res['drop_top'] = {'cik': top, 'ticker': tkmap.get(top), 'contribution_sum': round(tot[top], 4), 'full': rs_stats(to_s(exd), b, months)}
    res['contribution_top5'] = [(tkmap.get(c), c, round(v, 4)) for c, v in sorted(tot.items(), key=lambda kv: -kv[1])[:5]]
    res['contribution_bottom5'] = [(tkmap.get(c), c, round(v, 4)) for c, v in sorted(tot.items(), key=lambda kv: kv[1])[:5]]
    res['_series'] = {'R': R, 'bench': b, 'months': months}
    return res


# ── SURV_EW（今も上場している会社の等分の平均） ──
def build_surv(dat, univ):
    by = collections.defaultdict(list)
    dropped, nodata, have = 0, 0, 0
    for cik, tk in univ:
        px = dat.px(tk)
        if not px:
            nodata += 1
            continue
        have += 1
        for m, r in monthly_returns(px).items():
            if r > OUTLIER_UP:
                dropped += 1
                continue
            by[m].append(r)
    surv = {m: sum(v) / len(v) for m, v in by.items() if v}
    info = {'universe': len(univ), 'with_yahoo_series': have, 'no_yahoo_series': nodata, 'monthly_values_dropped_gt_300pct': dropped,
            'n_by_year_jan': {str(m // 100): len(by[m]) for m in sorted(by) if m % 100 == 1 and m >= 199001}}
    return surv, info


# ── R3: 因子への回帰（OLS・Newey-West ラグ12） ──
def ols_nw(y, X, lag=12):
    import numpy as np
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(y))] + [np.asarray(x, float) for x in X])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    n, k = X.shape
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:-L]
        Sm += w * (G + G.T)
    V = XtX_inv @ Sm @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return b, se, r2, n


def factor_alpha(R, b, months, rf):
    t5 = [v for k, v in N.french_tables('F-F_Research_Data_5_Factors_2x3').items() if v['freq'] == 'monthly'][0]
    mom = [v for k, v in N.french_tables('F-F_Momentum_Factor').items() if v['freq'] == 'monthly'][0]
    cols = t5['cols']
    fac = {}
    for m, row in t5['data'].items():
        if None in row or m not in mom['data'] or mom['data'][m][0] is None:
            continue
        d = dict(zip(cols, [x / 100 for x in row]))
        d['Mom'] = mom['data'][m][0] / 100
        fac[m] = d
    ms = [m for m in months if m in fac and m in R and m in b]
    names = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom']
    out = {}
    for lab, y in (('excess_vs_bench', [R[m] - b[m] for m in ms]), ('rule_minus_rf', [R[m] - fac[m]['RF'] for m in ms])):
        coef, se, r2, n = ols_nw(y, [[fac[m][f] for m in ms] for f in names])
        out[lab] = {'alpha_ann_pct': round(coef[0] * 1200, 2), 't_alpha': round(coef[0] / se[0], 2),
                    'loadings': {f: (round(coef[i + 1], 3), round(coef[i + 1] / se[i + 1], 2)) for i, f in enumerate(names)},
                    'r2': round(r2, 3), 'months': n, 'from': ms[0], 'to': ms[-1]}
    return out


def strip(res):
    return {k: v for k, v in res.items() if not k.startswith('_')}


def grade_family(results):
    """主（または探索）の族の中の Holm（片側）と grade_short。長い歴史の線 grade() は参考だけ"""
    p1 = {k: (N.p_one(r['full']['t']) if r.get('full') and r['full'].get('t') is not None else None) for k, r in results.items()}
    h1 = N.holm({k: v for k, v in p1.items() if v is not None})
    ph = {k: (r['hold_2007_on']['p'] if r.get('hold_2007_on') and r['hold_2007_on'].get('p') is not None else None) for k, r in results.items()}
    hh = N.holm({k: v for k, v in ph.items() if v is not None})
    for k, r in results.items():
        if r.get('error'):
            r['grade'] = 'C'
            r['criteria'] = {'error': r['error']}
            continue
        g, c = N.grade_short(r['full'], r['first_half'], r['second_half'], r['drop_top']['full'], r['cost']['0.30%']['full'],
                             r['missing_lower']['full'], h1.get(k))
        r['p_one'] = round(p1[k], 4) if p1[k] is not None else None
        r['holm_p_one'] = h1.get(k)
        r['grade'] = g
        r['criteria'] = c
        gl, cl = N.grade(r['full'], r['train_to_2006'], r['hold_2007_on'], r['roll20'], cost_hold=r['cost']['0.30%']['hold_2007_on'],
                         repl=None, family_holm_p=hh.get(k), leveraged_or_timing=False)
        r['long_history_reference'] = {'grade_reference_only': gl, 'C1_C8': cl, 'holm_p_hold_two_sided': hh.get(k),
                                       'note': '参考だけ。事前登録の格付けは criteria_short_sample（grade_short）。訓練は1998頃〜2006で15年に満たない。C5 は短い標本の格付けに無いので N/A、C8 は重ねる・借入・時期選びの型でないので N/A'}


# ── R6: 実在の器 ──
def real_instruments(dat):
    out = {}
    spy = dat.bench['SPY']
    for tk, note in (('IEP', 'Icahn Enterprises（Nasdaq・米国上場の LP）'),):
        px = dat.px(tk)
        if px:
            r = monthly_returns(px)
            out[tk] = {'note': note, 'vs_SPY': N.excess_stats(r, spy), 'maxdd': round(N.maxdd(r), 4)}
        else:
            out[tk] = {'note': note, 'error': 'Yahoo に系列が無い'}
    # Pershing Square Holdings: 米ドルの系列（PSHZF・OTC）を先に、無ければ PSH.L（ポンド）を GBPUSD で米ドルへ
    psh = None
    for tk in ('PSHZF', 'PSH.L', 'PSH.AS'):
        px = dat.px(tk)
        if not px:
            continue
        j = yh_raw(tk, '1mo')
        cur = j['chart']['result'][0]['meta'].get('currency')
        r = monthly_returns(px)
        if cur in ('GBp', 'GBP'):
            fx, _ = yh_prices('GBPUSD=X', '1mo')
            fr = monthly_returns(fx)
            r = {m: (1 + v) * (1 + fr[m]) - 1 for m, v in r.items() if m in fr}
            conv = f'{cur} を GBPUSD=X で米ドルへ（ペンス・ポンドは比なので単位は消える）'
        elif cur == 'USD':
            conv = 'USD'
        else:
            conv = f'{cur}（換算していない）'
        psh = {'ticker': tk, 'currency': cur, 'conversion': conv, 'first_month': min(r) if r else None,
               'vs_SPY': N.excess_stats(r, spy), 'maxdd': round(N.maxdd(r), 4) if r else None}
        break
    out['PSH'] = psh or {'error': 'Yahoo に PSHZF・PSH.L・PSH.AS の系列が無い'}
    px = dat.px('ACTX')
    if px:
        first, last = min(px), max(px)
        ok = first // 100 == 2015 and 3 <= first % 100 <= 5
        out['ACTX'] = {'first_month': first, 'last_month': last, 'months': len(px), 'used': ok,
                       'why': ('系列が 2015-04 前後に始まる' if ok else '系列が 2015-04 に始まらない＝記号が別のファンドに再利用されたか、系列が別物（事前登録どおり使わない）')}
        if ok:
            r = monthly_returns(px)
            out['ACTX']['vs_SPY'] = N.excess_stats(r, spy)
    else:
        out['ACTX'] = {'used': False, 'why': 'Yahoo に系列が無い'}
    return out


# ── R9: 提出から買う日までの日数と、規則が取らない部分 ──
def lag_report(dat, res_p1):
    pos = res_p1['_series']['pos_base']
    spy = dat.bench['SPY']
    spx = {}
    acc = 1.0
    for m in sorted(spy):
        acc *= 1 + spy[m]
        spx[m] = acc
    days, missed = [], []
    ev = {e['acc']: e for e in dat.o['events_13d']}
    for p in pos:
        e = ev.get(p['acc'])
        if not e:
            continue
        fd = datetime.date.fromisoformat(e['date'])
        lastday = max(d for d in dat.cal.days if d // 100 == p['M'])
        ld = datetime.date(lastday // 10000, lastday // 100 % 100, lastday % 100)
        days.append((ld - fd).days)
        F = int(e['date'][:4]) * 100 + int(e['date'][5:7])
        px = dat.px(p['ticker'])
        a = ym_add(F, -1)
        if a in px and p['M'] in px and a in spx and p['M'] in spx:
            missed.append((px[p['M']] / px[a] - 1) - (spx[p['M']] / spx[a] - 1))
    days.sort()
    missed.sort()
    q = lambda v, f: v[min(len(v) - 1, int(f * len(v)))] if v else None
    return {'rule': 'P1 の base の保有', 'n': len(days),
            'days_filing_to_buy': {'min': days[0], 'median': q(days, .5), 'mean': round(S.mean(days), 1), 'p90': q(days, .9), 'max': days[-1]},
            'missed_part_vs_SPY': {'what': '提出の月の月初（前の月末）〜買う月末の、会社のリターン − SPY のリターン（規則が取らない部分・単純差）',
                                   'n': len(missed), 'mean': round(S.mean(missed), 4), 'median': round(q(missed, .5), 4),
                                   'share_positive': round(sum(1 for x in missed if x > 0) / len(missed), 3)},
            'note': '形の報告・格付けに使わない'}


# ── R11: 欠けの運命（SEC へは取りに行かない run なので、手元のキャッシュだけで） ──
def fate_report(dat, events_now):
    import nx_activist_data as A
    idx = A.all_idx()
    reg_op, fund, f13 = A.registrant_spans(idx, with_fund=True)
    miss = [e for e in events_now if not e.get('ticker')]
    timing = collections.Counter()
    for e in miss:
        v = reg_op.get(e['subject_cik'])
        if not v:
            timing['事業会社の定期報告の記録が無い'] += 1
            continue
        gap = (datetime.date.fromisoformat(v[1]) - datetime.date.fromisoformat(e['date'])).days
        timing['最後の定期報告が事象の前' if gap < 0 else '最後の定期報告が事象から1年以内' if gap <= 365 else
               '最後の定期報告が1〜2年後' if gap <= 730 else '最後の定期報告が2年より後'] += 1
    sub = os.path.join(CACHE, 'sec_sub')
    have = [e for e in miss if os.path.exists(os.path.join(sub, f"CIK{e['subject_cik']:010d}.json"))]
    fate = collections.Counter()
    for e in have:
        j = json.load(open(os.path.join(sub, f"CIK{e['subject_cik']:010d}.json")))
        rc = j['filings']['recent']
        forms = [(d, f) for d, f in zip(rc['filingDate'], rc['form']) if d >= e['date']]
        fs = set(f for d, f in forms)
        if fs & {'DEFM14A', 'PREM14A', 'SC 14D9', 'SC TO-T', 'SC 13E3', '25-NSE'}:
            fate['買収・非公開化'] += 1
        elif fs & {'15-12B', '15-12G', '15-15D'}:
            fate['届け出の終了'] += 1
        else:
            fate['その他・判別できず'] += 1
    return {'what': '今のティッカーが無い L_NOW の事象の対象会社が、いつ定期報告をやめたか（手元の EDGAR 索引のキャッシュから）',
            'missing_events': len(miss), 'last_periodic_report_timing': dict(timing),
            'form_based_fate': {'done_for': len(have), 'of': len(miss), 'counts': dict(fate),
                                'status': ('部分実施: この run は SEC へ取りに行かない約束なので、他の道具が手元にキャッシュした submissions JSON がある会社だけ'
                                           if have else '未実施: この run は SEC へ取りに行かない約束で、手元のキャッシュに該当する submissions JSON が無い')},
            'note': '運命は事象の後に分かる情報なので、事象の選び方・重みには使わない（報告のみ）'}


DEVIATIONS = [
    '会社ごとの重複の除き方（event_rules.target_unit「持っている間に来た事象は無視する」）: 「来た」を買う月（D* の翌取引日 t1 が入る月）で読み、買う月が最後の保有の月以下なら無視する（v1.1・FIXES F3）。'
    'D* が最後の保有の月の中なのに翌取引日が翌月になる事象（月の最終取引日の提出など）は「保有が終わった後に来た」になる（timing の「翌取引日から使える」と同じ読み）。この読みの分かれ目（D* ≤ 最後の保有の月末〔日次は売る日〕なのに t1 がその後）に当たる事象は、主・探索の19本と報告の単位（R1 の家ごと・R2 の時代ごと・PRE だけの家）の base・下限版のどれにも0件（2026-09-28 に数えた）＝2つの読みは今のデータで同じ結果',
    '外れ値の確認の規則: 事前登録は「+300% 超・−90% 未満の月を日次と突き合わせ、データの誤りと確かめられたときだけ値の無い月」までを決めていた。実装で (a) Yahoo の分割の記録で動きが説明できる、(b) 日次の複利と月次が1.5倍を超えて食い違う、の2つを「確かめられた」とした。'
    '初めの案の (c)「1日の3倍超の動きが10取引日以内に戻る」は、外れ値の一覧（規則の成績は未計算の段階）で AMC 2021-01（本物のミーム株の急騰）を誤りと判定したので外した。結果として12件の外れ値はどれも誤りと確かめられず、値を落とした月は0＝格付けへの影響なし',
    'R1（家ごと）・R2（時代ごと）・C5 の代わり(2) の PRE だけの家: 事象が少なく、同時に持つ会社が10社に届かない（評価の最初の月の規則「前の月末に10社以上」が一度も満たされない）単位がある。その単位は評価の最初の月を「最初に1社以上を持った月」に落とした（重み 1/max(n,10) と残りを SPY に置く規則はそのまま）。'
    '評価の終わりは、その単位が base・下限版・中立版のどれかで最後に会社を持っていた月にした（v1.1・FIXES F2。事前登録の「終わりは 2026-08」は規則の評価の窓で、事象を時代・家で切った単位にそのまま当てると保有の無い超過 0 の月が何年も末尾に付き、年率の大きさが薄まる。幾何の超過の符号は変わらない）。報告だけの単位なので格付けへの影響なし',
    'R1 の「使える事象が20以上の家」: 最初の実行では「買う月の株価がある事象が20以上」と読んで4家だけを測った。事前登録の coverage の用語（events_used＝除外と重複を除いた事象・ティッカーの有無を問わない）に合わせて「使える事象が20以上」に直した。両方を JSON に残した（報告のみ・格付けに影響なし）',
    'E10（日次）: 買う日を「提出日の翌取引日」ではなく、主の規則と同じ D* = max(提出日, 受付の日) の翌取引日にした（L_NOW で受付の日が提出日より後なのは1件だけ）。評価の最初の月は「その月に1日でも持っていた会社が10社以上」の最初の月。SPY の月次は日次の調整後終値から作った（Yahoo の月次と一致することを 2008-10・2020-03・2020-04・2013-12・2026-08 で確かめた）。保有の途中で系列が途切れた月の下限版・中立版は、途切れる前の日までの値に −30%（下限）・SPY（中立）を掛ける近似。'
    '費用は事前登録どおり入る・出るの売買だけで、回転は月次と同じ片道 ½Σ|Δw|（入る ½w・出る ½w・相手の枠は数えない）。等分への戻しを入れないので、月次の規則の回転（戻しを含む）より小さい＝その分だけ甘い。'
    '評価の終わり（2026-08）で 252取引日に届かず打ち切った保有には売りの費用を掛けない（月次の規則と同じ）。v1 は入る・出るに w を足して 2倍の費用を掛け、打ち切った保有にも売りの費用を掛けていた（FIXES F1・F1b）',
    '回転と費用: 保有の途中で系列が途切れて現金になった分は回転に数えない（売買ではない）。主・探索のどの規則でも base で途中で途切れた保有は0件だったので影響なし。相手が IWM の規則は IWM の値が無い 2000-06 以前の月に規則のリターンが作れないので、2000-07 に持ち高を作り直したものとして最初の月の回転に全部を数えた（評価は 2007 年以降に始まるので影響なし）',
    'E4（新しい順の10社）: 同じ買う月の中の順は受付番号の昇順にした（事前登録は「受付番号の順」だけを書いていた）',
    'SURV_EW の「最後の400日」: SEC のティッカー表の取得日（2026-09-28）から400日＝2025-08-24 以後に事業会社の定期報告を出した CIK とした',
    'R6: PSH.AS は Yahoo に無い（404）ので、米ドル建ての PSHZF（OTC・2015-07〜）を使った。ACTX は Yahoo の系列が 2000-01 から始まる（記号が別のファンドに再利用されている）ので事前登録どおり使わなかった',
    'R10（欠けの抜き取り40件）: 未実施。Alpha Vantage の MCP は1日25回の上限に達していて値が取れず、FMP の MCP は上場廃止した銘柄の株価を「上のプランが要る」で拒否、Yahoo は上場廃止した記号がすべて 404',
    'R11（欠けの運命）: この run は SEC へ取りに行かない約束なので、様式での分類は他の道具が手元にキャッシュした submissions JSON がある6社（668件中）だけの部分実施。代わりに手元の EDGAR 索引のキャッシュから「最後の定期報告が事象からいつか」を全668件で数えた',
    '長い歴史の線 grade()（C1〜C8）は、依頼に従い参考として各規則に並べた（事前登録の格付けは criteria_short_sample）。C7 の Holm は保有期間の両側 p で族ごとに、C5 は N/A、C8 は該当しない（N/A）。どの主の規則も評価の最初の月が 2001〜2007 で、訓練（〜2006）は最長でも P5 の5.8年、多くは0か月（train_to_2006 が null）',
    '結果を見た後に足した分析（reports.post_hoc: 時代ごと・相手ごとの分解、イベント時間の平均の超過）は「事後」と明記し格付けに使っていない',
]


# 検査役（2026-09-28）の指摘の是正と前後の数字（v1 → v1.1）。前の値は v1 の実装をそのまま（是正を1つずつ戻して）同じキャッシュで再実行して測った。
# 後の値は是正した時点（2026-09-28）の run の値。再実行でデータが更新されると results の値はずれうるが、これは是正の記録として固定する
FIXES = json.loads(r'''[
 {
  "id": "F1",
  "reported": "E10（日次）の費用が事前登録の回転の定義の2倍（入った月に w・出た月に w を足して 0.30% を掛けていた＝Σ|Δw|）",
  "verdict": "誤り（確かめた）。事前登録 costs.turnover は片道 ½Σ|新しい重み − 流した重み|（相手の枠は数えない）で、月次の run_portfolio もその定義（0.5 × Σ）。E10 は入る 0→w・出る w→0 にそれぞれ w を足しており、同じ定義の2倍だった。docstring と DEVIATIONS の「甘い」は逆で、実際は厳しい側にずれていた",
  "fix": "eval_daily の cost_w に入る ½w・出る ½w を足す（v1.1）。E10 の回転（turnover_oneway_annual）を結果に出した。DEVIATIONS の説明を直した",
  "before_v1": {
   "grade": "C",
   "full_cagr_diff_before_cost": -7.09,
   "turnover_charged_per_year": 1.808,
   "cost_0.30%_full_cagr_diff": -7.66,
   "cost_0.30%_full_ex_ann": -5.08,
   "cost_0.30%_hold_2007_on_cagr_diff": -7.7,
   "cost_0.50%_full_cagr_diff": -8.03,
   "cost_1.00%_full_cagr_diff": -8.96
  },
  "after_v1_1": {
   "grade": "C",
   "full_cagr_diff_before_cost": -7.09,
   "turnover_charged_per_year": 0.884,
   "cost_0.30%_full_cagr_diff": -7.37,
   "cost_0.30%_full_ex_ann": -4.8,
   "cost_0.30%_hold_2007_on_cagr_diff": -7.41,
   "cost_0.50%_full_cagr_diff": -7.55,
   "cost_1.00%_full_cagr_diff": -8.01
  },
  "effect_of_F1_alone": {
   "grade": "C",
   "full_cagr_diff_before_cost": -7.09,
   "turnover_charged_per_year": 0.904,
   "cost_0.30%_full_cagr_diff": -7.37,
   "cost_0.30%_full_ex_ann": -4.8,
   "cost_0.30%_hold_2007_on_cagr_diff": -7.42,
   "cost_0.50%_full_cagr_diff": -7.56,
   "cost_1.00%_full_cagr_diff": -8.03
  },
  "grade": "C → C（費用前の −7.09 は不変・費用後も負）",
  "note": "before の回転 1.808 は v1 の run には出していなかった値で、v1 の実装をそのまま再実行して測った（検査役の別の実装の 1.808・0.543pt/年と一致）。P1（等分への戻しも含む月次）の片道の回転は 1.531/年"
 },
 {
  "id": "F1b",
  "reported": "（検査役の指摘ではない。F1 を直す中で見つけた同じ費用の行の不一致）",
  "verdict": "誤り（小さい）。評価の終わり（2026-08）で 252取引日に届かず打ち切った保有にも「出る」の費用を掛けていた。月次の規則は評価の終わりに持っている会社へ売りの費用を掛けない＝定義が違っていた",
  "fix": "出るの費用は 252取引日後に本当に売った保有（i1 + 252 ≤ 最後の取引日の番号）だけにする（pos['sold']）",
  "before_F1_only": {
   "grade": "C",
   "full_cagr_diff_before_cost": -7.09,
   "turnover_charged_per_year": 0.904,
   "cost_0.30%_full_cagr_diff": -7.37,
   "cost_0.30%_full_ex_ann": -4.8,
   "cost_0.30%_hold_2007_on_cagr_diff": -7.42,
   "cost_0.50%_full_cagr_diff": -7.56,
   "cost_1.00%_full_cagr_diff": -8.03
  },
  "after_v1_1": {
   "grade": "C",
   "full_cagr_diff_before_cost": -7.09,
   "turnover_charged_per_year": 0.884,
   "cost_0.30%_full_cagr_diff": -7.37,
   "cost_0.30%_full_ex_ann": -4.8,
   "cost_0.30%_hold_2007_on_cagr_diff": -7.41,
   "cost_0.50%_full_cagr_diff": -7.55,
   "cost_1.00%_full_cagr_diff": -8.01
  },
  "grade": "C → C"
 },
 {
  "id": "F2",
  "reported": "報告だけの単位（R1 の家ごと・R2 の時代ごと・R_C5_2 の PRE だけの家）を、その単位の最後の保有の後も 2026-08 まで評価し、超過 0 の月が末尾に何年も付いて ex_ann・cagr_diff・years が薄まっていた",
  "verdict": "誤り（確かめた・大きさだけ）。run_portfolio は最初の保有の月から 2026-08 までを作り、保有の無い月は規則＝相手（超過 0）。事象を時代・家で切った単位では、活動をやめた家や 1996-2006・2007-2016 の時代に数年〜二十年の超過 0 の月が付いていた。幾何の超過の符号は変わらない（保有の無い月は両方が同じ値で伸びる）ので、C5 の代わりの判定と格付けは変わらない",
  "fix": "eval_monthly に end_at_last_holding を足し、報告だけの単位では評価の終わりを「その単位が base・下限版・中立版のどれかで最後に会社を持っていた月」にした（下限版・中立版を base と同じ月で測る約束を守り、どの版の保有も切らないため。base だけの最後の月より0〜2か月長い）。v1 の読みの値は full_to_2026_08_with_trailing_zero_excess に残した。保有の窓が24か月に満たない家（chapman 16か月・pirate 22か月）は excess_stats が統計を出さない（full = null）ので、家・時代・PRE だけの家の「正か」は保有の窓の幾何の年率差 cagr_diff_holding_window（最短の月数なし）の符号で数える＝v1 と同じ家が同じ側に入る。主・探索の規則は事前登録どおり 2026-08 まで（変更なし）",
  "R2_by_era": {
   "P1_NOW_H12_SPY 1996-2006": {
    "v1": {
     "eval_to": 202608,
     "years": 28.7,
     "ex_ann": 1.38,
     "t": 1.09,
     "cagr_diff": 1.35,
     "lower_cagr_diff": -11.23
    },
    "before_F2_with_F3_applied": {
     "eval_to": 202608,
     "years": 28.7,
     "ex_ann": 1.38,
     "t": 1.09,
     "cagr_diff": 1.35,
     "lower_cagr_diff": -11.22
    },
    "after_v1_1": {
     "eval_to": 200801,
     "years": 10.1,
     "ex_ann": 3.92,
     "t": 1.15,
     "cagr_diff": 3.72,
     "lower_cagr_diff": -27.83
    },
    "reference_window_end_at_base_last_holding": {
     "eval_to": 200801,
     "cagr_diff": 3.72
    }
   },
   "P1_NOW_H12_SPY 2007-2016": {
    "v1": {
     "eval_to": 202608,
     "years": 19.1,
     "ex_ann": -0.68,
     "t": -0.21,
     "cagr_diff": -2.38,
     "lower_cagr_diff": -13.87
    },
    "before_F2_with_F3_applied": {
     "eval_to": 202608,
     "years": 19.1,
     "ex_ann": -0.84,
     "t": -0.26,
     "cagr_diff": -2.56,
     "lower_cagr_diff": -13.94
    },
    "after_v1_1": {
     "eval_to": 201712,
     "years": 10.4,
     "ex_ann": -1.55,
     "t": -0.25,
     "cagr_diff": -4.52,
     "lower_cagr_diff": -23.56
    },
    "reference_window_end_at_base_last_holding": {
     "eval_to": 201711,
     "cagr_diff": -4.56
    }
   },
   "P4_PRE2007_H12_SPY 2007-2016": {
    "v1": {
     "eval_to": 202608,
     "years": 18.8,
     "ex_ann": 2.42,
     "t": 0.93,
     "cagr_diff": 1.42,
     "lower_cagr_diff": -9.84
    },
    "before_F2_with_F3_applied": {
     "eval_to": 202608,
     "years": 18.8,
     "ex_ann": 2.42,
     "t": 0.93,
     "cagr_diff": 1.42,
     "lower_cagr_diff": -9.84
    },
    "after_v1_1": {
     "eval_to": 201710,
     "years": 10.0,
     "ex_ann": 4.55,
     "t": 0.96,
     "cagr_diff": 2.6,
     "lower_cagr_diff": -17.25
    },
    "reference_window_end_at_base_last_holding": {
     "eval_to": 201708,
     "cagr_diff": 2.64
    }
   },
   "P5_MECH_H12_SPY 1996-2006": {
    "v1": {
     "eval_to": 202608,
     "years": 25.4,
     "ex_ann": 3.23,
     "t": 1.33,
     "cagr_diff": 3.26,
     "lower_cagr_diff": -7.44
    },
    "before_F2_with_F3_applied": {
     "eval_to": 202608,
     "years": 25.4,
     "ex_ann": 3.23,
     "t": 1.33,
     "cagr_diff": 3.26,
     "lower_cagr_diff": -7.44
    },
    "after_v1_1": {
     "eval_to": 200801,
     "years": 6.8,
     "ex_ann": 12.0,
     "t": 1.53,
     "cagr_diff": 11.99,
     "lower_cagr_diff": -23.95
    },
    "reference_window_end_at_base_last_holding": {
     "eval_to": 200712,
     "cagr_diff": 12.26
    }
   },
   "P5_MECH_H12_SPY 2007-2016": {
    "v1": {
     "eval_to": 202608,
     "years": 19.2,
     "ex_ann": 2.22,
     "t": 0.73,
     "cagr_diff": 1.23,
     "lower_cagr_diff": -14.35
    },
    "before_F2_with_F3_applied": {
     "eval_to": 202608,
     "years": 19.2,
     "ex_ann": 2.22,
     "t": 0.73,
     "cagr_diff": 1.23,
     "lower_cagr_diff": -14.35
    },
    "after_v1_1": {
     "eval_to": 201801,
     "years": 10.6,
     "ex_ann": 4.01,
     "t": 0.74,
     "cagr_diff": 2.18,
     "lower_cagr_diff": -24.04
    },
    "reference_window_end_at_base_last_holding": {
     "eval_to": 201801,
     "cagr_diff": 2.18
    }
   }
  },
  "R1_by_family_changed": {
   "wynnefield": {
    "before_v1": {
     "eval_to": 202608,
     "years": 30.0,
     "ex_ann": -0.29,
     "t": -0.37,
     "cagr_diff": -0.48,
     "lower_cagr_diff": -8.56
    },
    "after_v1_1": {
     "eval_to": 202605,
     "years": 29.8,
     "ex_ann": -0.29,
     "t": -0.37,
     "cagr_diff": -0.48,
     "lower_cagr_diff": -8.63
    },
    "cagr_diff_holding_window": -0.48
   },
   "third_point": {
    "before_v1": {
     "eval_to": 202608,
     "years": 22.5,
     "ex_ann": -0.77,
     "t": -0.79,
     "cagr_diff": -1.0,
     "lower_cagr_diff": -5.68
    },
    "after_v1_1": {
     "eval_to": 202601,
     "years": 21.9,
     "ex_ann": -0.79,
     "t": -0.79,
     "cagr_diff": -1.03,
     "lower_cagr_diff": -5.81
    },
    "cagr_diff_holding_window": -1.03
   },
   "blum": {
    "before_v1": {
     "eval_to": 202608,
     "years": 29.0,
     "ex_ann": 0.62,
     "t": 1.43,
     "cagr_diff": 0.65,
     "lower_cagr_diff": -4.07
    },
    "after_v1_1": {
     "eval_to": 201009,
     "years": 13.1,
     "ex_ann": 1.38,
     "t": 1.52,
     "cagr_diff": 1.37,
     "lower_cagr_diff": -8.34
    },
    "cagr_diff_holding_window": 1.37
   },
   "ancora": {
    "before_v1": {
     "eval_to": 202608,
     "years": 13.8,
     "ex_ann": 0.51,
     "t": 1.23,
     "cagr_diff": 0.55,
     "lower_cagr_diff": -4.24
    },
    "after_v1_1": {
     "eval_to": 202301,
     "years": 10.2,
     "ex_ann": 0.69,
     "t": 1.26,
     "cagr_diff": 0.73,
     "lower_cagr_diff": -5.6
    },
    "cagr_diff_holding_window": 0.73
   },
   "harbinger": {
    "before_v1": {
     "eval_to": 202608,
     "years": 18.5,
     "ex_ann": -1.2,
     "t": -1.49,
     "cagr_diff": -1.49,
     "lower_cagr_diff": -2.3
    },
    "after_v1_1": {
     "eval_to": 201501,
     "years": 6.9,
     "ex_ann": -3.2,
     "t": -1.67,
     "cagr_diff": -3.8,
     "lower_cagr_diff": -5.85
    },
    "cagr_diff_holding_window": -3.8
   },
   "pershing": {
    "before_v1": {
     "eval_to": 202608,
     "years": 19.1,
     "ex_ann": -1.31,
     "t": -1.06,
     "cagr_diff": -1.56,
     "lower_cagr_diff": -3.37
    },
    "after_v1_1": {
     "eval_to": 202508,
     "years": 18.1,
     "ex_ann": -1.39,
     "t": -1.06,
     "cagr_diff": -1.64,
     "lower_cagr_diff": -3.53
    },
    "cagr_diff_holding_window": -1.64
   },
   "chapman": {
    "before_v1": {
     "eval_to": 202608,
     "years": 19.4,
     "ex_ann": 0.16,
     "t": 0.65,
     "cagr_diff": 0.18,
     "lower_cagr_diff": -0.45
    },
    "after_v1_1": {
     "eval_to": 200807,
     "years": null,
     "ex_ann": null,
     "t": null,
     "cagr_diff": null,
     "lower_cagr_diff": null
    },
    "cagr_diff_holding_window": 2.27
   },
   "clinton": {
    "before_v1": {
     "eval_to": 202608,
     "years": 19.7,
     "ex_ann": 0.54,
     "t": 0.44,
     "cagr_diff": 0.18,
     "lower_cagr_diff": -3.78
    },
    "after_v1_1": {
     "eval_to": 201712,
     "years": 11.0,
     "ex_ann": 0.97,
     "t": 0.44,
     "cagr_diff": 0.32,
     "lower_cagr_diff": -6.5
    },
    "cagr_diff_holding_window": 0.32
   },
   "relational": {
    "before_v1": {
     "eval_to": 202608,
     "years": 21.8,
     "ex_ann": -0.76,
     "t": -1.38,
     "cagr_diff": -0.89,
     "lower_cagr_diff": -3.15
    },
    "after_v1_1": {
     "eval_to": 201507,
     "years": 10.7,
     "ex_ann": -1.55,
     "t": -1.42,
     "cagr_diff": -1.76,
     "lower_cagr_diff": -6.15
    },
    "cagr_diff_holding_window": -1.76
   },
   "engaged": {
    "before_v1": {
     "eval_to": 202608,
     "years": 13.1,
     "ex_ann": -0.26,
     "t": -0.22,
     "cagr_diff": -0.59,
     "lower_cagr_diff": -4.91
    },
    "after_v1_1": {
     "eval_to": 202508,
     "years": 12.1,
     "ex_ann": -0.29,
     "t": -0.21,
     "cagr_diff": -0.63,
     "lower_cagr_diff": -5.28
    },
    "cagr_diff_holding_window": -0.63
   },
   "barington": {
    "before_v1": {
     "eval_to": 202608,
     "years": 22.0,
     "ex_ann": -0.52,
     "t": -1.05,
     "cagr_diff": -0.66,
     "lower_cagr_diff": -2.85
    },
    "after_v1_1": {
     "eval_to": 201904,
     "years": 14.7,
     "ex_ann": -0.78,
     "t": -1.06,
     "cagr_diff": -0.97,
     "lower_cagr_diff": -4.17
    },
    "cagr_diff_holding_window": -0.97
   },
   "greenlight": {
    "before_v1": {
     "eval_to": 202608,
     "years": 28.7,
     "ex_ann": -0.62,
     "t": -1.28,
     "cagr_diff": -0.75,
     "lower_cagr_diff": -2.94
    },
    "after_v1_1": {
     "eval_to": 201701,
     "years": 19.1,
     "ex_ann": -0.93,
     "t": -1.3,
     "cagr_diff": -1.09,
     "lower_cagr_diff": -4.27
    },
    "cagr_diff_holding_window": -1.09
   },
   "pirate": {
    "before_v1": {
     "eval_to": 202608,
     "years": 20.5,
     "ex_ann": -0.17,
     "t": -0.78,
     "cagr_diff": -0.19,
     "lower_cagr_diff": -2.14
    },
    "after_v1_1": {
     "eval_to": 200712,
     "years": null,
     "ex_ann": null,
     "t": null,
     "cagr_diff": null,
     "lower_cagr_diff": null
    },
    "cagr_diff_holding_window": -2.09
   },
   "legion": {
    "before_v1": {
     "eval_to": 202608,
     "years": 12.2,
     "ex_ann": 1.32,
     "t": 1.6,
     "cagr_diff": 1.23,
     "lower_cagr_diff": -1.7
    },
    "after_v1_1": {
     "eval_to": 202405,
     "years": 9.9,
     "ex_ann": 1.62,
     "t": 1.67,
     "cagr_diff": 1.49,
     "lower_cagr_diff": -2.06
    },
    "cagr_diff_holding_window": 1.49
   }
  },
  "R_C5_2_PRE_only": "変更なし（PRE だけの家は 2026-08 まで持っている）",
  "C5_substitute_before_after": {
   "v1": {
    "(1)_families_positive_share": 0.318,
    "(1)_families_positive": "7/22",
    "(2)_NOW_only_and_PRE_only_both_positive": false,
    "(3)_P1_eras_positive": "1/3",
    "note": "短い標本の格付けに C5 は無い。事前登録どおり報告だけ（格付けに使わない）",
    "R2_eras_positive": {
     "P1_NOW_H12_SPY": "1/3",
     "P4_PRE2007_H12_SPY": "1/2",
     "P5_MECH_H12_SPY": "2/3"
    }
   },
   "v1_1": {
    "(1)_families_positive_share": 0.318,
    "(1)_families_positive": "7/22",
    "(2)_NOW_only_and_PRE_only_both_positive": false,
    "(3)_P1_eras_positive": "1/3",
    "note": "短い標本の格付けに C5 は無い。事前登録どおり報告だけ（格付けに使わない）",
    "R2_eras_positive": {
     "P1_NOW_H12_SPY": "1/3",
     "P4_PRE2007_H12_SPY": "1/2",
     "P5_MECH_H12_SPY": "2/3"
    }
   }
  },
  "grade": "格付けは報告だけの単位に無い。主・探索の格付けは不変",
  "note": "検査役の数字（R2 P5 1996-2006 +12.26・P4 2007-2016 +2.64・P1 1996-2006 +3.72）は base の最後の保有の月で切った値で、reference_window_end_at_base_last_holding と一致する。P1 2007-2016 の検査役の −4.24 は F3 の前の値（F3 の後は base の窓で −4.56・この道具の窓で −4.52）"
 },
 {
  "id": "F3",
  "reported": "会社ごとの重複の除き方の境界: held_until = M0+H（最後に持つ月）に対し `M < held_until` で、最後の保有の月に来た事象が売ると同時に新しい保有を開き、同じ会社を切れ目なく持ち続けていた",
  "verdict": "誤り（確かめた・事前登録 event_rules.target_unit の誤読）。事前登録は「持っている間に来た事象は無視する（保有を延ばさない）」。買う月 M'（翌取引日 t1 の月）が最後の保有の月 M0+H と同じなら、t1 は売る月末以前＝持っている間に来た事象で、無視すべきだった。実例 MTW: 2014-06 末に買い 2015-06 末まで持つ保有の途中、2015-06-01 に Glenview の 13D → v1 は 2015-06 末に新しい12か月の保有を開き、2014-07〜2016-06 を連続で持っていた",
  "fix": "build_positions を `M <= held_until[cik]`、E10（日次）の build も同じ読みで `t1 <= 売る日` にした（v1.1）。読みの分かれ目（D* が最後の保有の月の中なのに t1 が翌月）に当たる事象は、主・探索の19本と報告の単位の base・下限版のどれにも0件",
  "boundary_events_base_v1": {
   "P1・P3・P6・E4・E12": "MTW 2015-06（Glenview 2015-06-01）",
   "P2・E3": "BHC 2017-03（2017-03-16）",
   "E1": "CRL 2010-12（2010-12-09）・MTW 2014-12（2014-12-29）・MTW 2015-06（2015-06-01）",
   "E11": "DIS 2024-01（2024-01-03）",
   "E2・E5": "base には無し（下限版・中立版の保有が1件ずつ減っただけ）",
   "P4・P5・E6〜E10・E13": "無し（値は不変）"
  },
  "rules": {
   "P1_NOW_H12_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -5.4,
     "t": -1.3,
     "p_one": 0.9032,
     "cagr_diff": -8.34,
     "cost030_cagr_diff": -8.81,
     "lower_cagr_diff": -22.76,
     "neutral_cagr_diff": -5.01,
     "drop_top_cagr_diff": -9.05,
     "halves_cagr_diff": [
      -4.34,
      -12.5
     ],
     "positions_base": 320,
     "positions_lower": 978
    },
    "after": {
     "grade": "C",
     "ex_ann": -5.56,
     "t": -1.33,
     "p_one": 0.9082,
     "cagr_diff": -8.51,
     "cost030_cagr_diff": -8.98,
     "lower_cagr_diff": -22.82,
     "neutral_cagr_diff": -5.06,
     "drop_top_cagr_diff": -9.22,
     "halves_cagr_diff": [
      -4.67,
      -12.5
     ],
     "positions_base": 319,
     "positions_lower": 976
    }
   },
   "P2_NOW_H24_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -0.96,
     "t": -0.24,
     "p_one": 0.5948,
     "cagr_diff": -3.04,
     "cost030_cagr_diff": -3.38,
     "lower_cagr_diff": -14.57,
     "neutral_cagr_diff": -2.42,
     "drop_top_cagr_diff": -3.54,
     "halves_cagr_diff": [
      1.48,
      -7.69
     ],
     "positions_base": 317,
     "positions_lower": 964
    },
    "after": {
     "grade": "C",
     "ex_ann": -1.1,
     "t": -0.28,
     "p_one": 0.6103,
     "cagr_diff": -3.19,
     "cost030_cagr_diff": -3.53,
     "lower_cagr_diff": -14.64,
     "neutral_cagr_diff": -2.48,
     "drop_top_cagr_diff": -3.69,
     "halves_cagr_diff": [
      1.48,
      -7.98
     ],
     "positions_base": 316,
     "positions_lower": 963
    }
   },
   "P3_NOW_H12_IWM": {
    "before": {
     "grade": "C",
     "ex_ann": -3.62,
     "t": -0.97,
     "p_one": 0.834,
     "cagr_diff": -5.46,
     "cost030_cagr_diff": -5.94,
     "lower_cagr_diff": -20.08,
     "neutral_cagr_diff": -3.47,
     "drop_top_cagr_diff": -6.17,
     "halves_cagr_diff": [
      -3.94,
      -7.01
     ],
     "positions_base": 320,
     "positions_lower": 978
    },
    "after": {
     "grade": "C",
     "ex_ann": -3.78,
     "t": -1.01,
     "p_one": 0.8438,
     "cagr_diff": -5.63,
     "cost030_cagr_diff": -6.1,
     "lower_cagr_diff": -20.14,
     "neutral_cagr_diff": -3.52,
     "drop_top_cagr_diff": -6.33,
     "halves_cagr_diff": [
      -4.27,
      -7.01
     ],
     "positions_base": 319,
     "positions_lower": 976
    }
   },
   "P6_NOW_H12_SURV": {
    "before": {
     "grade": "C",
     "ex_ann": -4.16,
     "t": -1.39,
     "p_one": 0.9177,
     "cagr_diff": -6.28,
     "cost030_cagr_diff": -6.75,
     "lower_cagr_diff": -21.26,
     "neutral_cagr_diff": -2.98,
     "drop_top_cagr_diff": -6.88,
     "halves_cagr_diff": [
      -7.71,
      -4.87
     ],
     "positions_base": 320,
     "positions_lower": 978
    },
    "after": {
     "grade": "C",
     "ex_ann": -4.32,
     "t": -1.43,
     "p_one": 0.9236,
     "cagr_diff": -6.44,
     "cost030_cagr_diff": -6.92,
     "lower_cagr_diff": -21.32,
     "neutral_cagr_diff": -3.02,
     "drop_top_cagr_diff": -7.05,
     "halves_cagr_diff": [
      -8.04,
      -4.87
     ],
     "positions_base": 319,
     "positions_lower": 976
    }
   },
   "E1_NOW_H6_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -2.82,
     "t": -0.8,
     "p_one": 0.7881,
     "cagr_diff": -5.4,
     "cost030_cagr_diff": -5.98,
     "lower_cagr_diff": -31.54,
     "neutral_cagr_diff": -3.03,
     "drop_top_cagr_diff": -6.03,
     "halves_cagr_diff": [
      -2.18,
      -8.74
     ],
     "positions_base": 324,
     "positions_lower": 987
    },
    "after": {
     "grade": "C",
     "ex_ann": -2.81,
     "t": -0.81,
     "p_one": 0.791,
     "cagr_diff": -5.38,
     "cost030_cagr_diff": -5.95,
     "lower_cagr_diff": -31.63,
     "neutral_cagr_diff": -3.01,
     "drop_top_cagr_diff": -6.02,
     "halves_cagr_diff": [
      -2.14,
      -8.74
     ],
     "positions_base": 322,
     "positions_lower": 984
    }
   },
   "E2_NOW_H36_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": 1.48,
     "t": 0.39,
     "p_one": 0.3483,
     "cagr_diff": -0.34,
     "cost030_cagr_diff": -0.62,
     "lower_cagr_diff": -11.47,
     "neutral_cagr_diff": -1.39,
     "drop_top_cagr_diff": -0.74,
     "halves_cagr_diff": [
      4.11,
      -4.95
     ],
     "positions_base": 313,
     "positions_lower": 949
    },
    "after": {
     "grade": "C",
     "ex_ann": 1.48,
     "t": 0.39,
     "p_one": 0.3483,
     "cagr_diff": -0.34,
     "cost030_cagr_diff": -0.62,
     "lower_cagr_diff": -11.47,
     "neutral_cagr_diff": -1.39,
     "drop_top_cagr_diff": -0.74,
     "halves_cagr_diff": [
      4.11,
      -4.95
     ],
     "positions_base": 313,
     "positions_lower": 948
    }
   },
   "E3_NOW_H24_IWM": {
    "before": {
     "grade": "C",
     "ex_ann": 0.62,
     "t": 0.18,
     "p_one": 0.4286,
     "cagr_diff": -0.37,
     "cost030_cagr_diff": -0.71,
     "lower_cagr_diff": -11.91,
     "neutral_cagr_diff": -0.96,
     "drop_top_cagr_diff": -0.87,
     "halves_cagr_diff": [
      2.66,
      -3.44
     ],
     "positions_base": 317,
     "positions_lower": 964
    },
    "after": {
     "grade": "C",
     "ex_ann": 0.47,
     "t": 0.14,
     "p_one": 0.4443,
     "cagr_diff": -0.52,
     "cost030_cagr_diff": -0.86,
     "lower_cagr_diff": -11.99,
     "neutral_cagr_diff": -1.02,
     "drop_top_cagr_diff": -1.02,
     "halves_cagr_diff": [
      2.66,
      -3.73
     ],
     "positions_base": 316,
     "positions_lower": 963
    }
   },
   "E4_NOW_H12_recent10_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -3.87,
     "t": -0.9,
     "p_one": 0.8159,
     "cagr_diff": -7.31,
     "cost030_cagr_diff": -7.9,
     "lower_cagr_diff": -53.46,
     "neutral_cagr_diff": -3.92,
     "drop_top_cagr_diff": -8.08,
     "halves_cagr_diff": [
      -2.69,
      -12.09
     ],
     "positions_base": 320,
     "positions_lower": 978
    },
    "after": {
     "grade": "C",
     "ex_ann": -3.98,
     "t": -0.92,
     "p_one": 0.8212,
     "cagr_diff": -7.43,
     "cost030_cagr_diff": -8.02,
     "lower_cagr_diff": -53.38,
     "neutral_cagr_diff": -3.78,
     "drop_top_cagr_diff": -8.21,
     "halves_cagr_diff": [
      -2.94,
      -12.09
     ],
     "positions_base": 319,
     "positions_lower": 976
    }
   },
   "E5_PRE_all_H12_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -2.74,
     "t": -0.78,
     "p_one": 0.7823,
     "cagr_diff": -4.83,
     "cost030_cagr_diff": -5.09,
     "lower_cagr_diff": -20.77,
     "neutral_cagr_diff": -3.57,
     "drop_top_cagr_diff": -5.43,
     "halves_cagr_diff": [
      0.91,
      -10.71
     ],
     "positions_base": 150,
     "positions_lower": 673
    },
    "after": {
     "grade": "C",
     "ex_ann": -2.74,
     "t": -0.78,
     "p_one": 0.7823,
     "cagr_diff": -4.83,
     "cost030_cagr_diff": -5.09,
     "lower_cagr_diff": -20.77,
     "neutral_cagr_diff": -3.57,
     "drop_top_cagr_diff": -5.43,
     "halves_cagr_diff": [
      0.91,
      -10.71
     ],
     "positions_base": 150,
     "positions_lower": 672
    }
   },
   "E11_NOW_contest_H12_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -8.11,
     "t": -2.59,
     "p_one": 0.9952,
     "cagr_diff": -10.43,
     "cost030_cagr_diff": -10.8,
     "lower_cagr_diff": -20.19,
     "neutral_cagr_diff": -8.85,
     "drop_top_cagr_diff": -11.13,
     "halves_cagr_diff": [
      -9.63,
      -11.21
     ],
     "positions_base": 129,
     "positions_lower": 287
    },
    "after": {
     "grade": "C",
     "ex_ann": -8.09,
     "t": -2.56,
     "p_one": 0.9948,
     "cagr_diff": -10.39,
     "cost030_cagr_diff": -10.75,
     "lower_cagr_diff": -20.09,
     "neutral_cagr_diff": -8.86,
     "drop_top_cagr_diff": -11.09,
     "halves_cagr_diff": [
      -9.63,
      -11.13
     ],
     "positions_base": 128,
     "positions_lower": 285
    }
   },
   "E12_NOWonly_H12_SPY": {
    "before": {
     "grade": "C",
     "ex_ann": -5.7,
     "t": -1.66,
     "p_one": 0.9515,
     "cagr_diff": -8.42,
     "cost030_cagr_diff": -8.83,
     "lower_cagr_diff": -22.66,
     "neutral_cagr_diff": -4.75,
     "drop_top_cagr_diff": -8.96,
     "halves_cagr_diff": [
      -7.14,
      -9.74
     ],
     "positions_base": 209,
     "positions_lower": 588
    },
    "after": {
     "grade": "C",
     "ex_ann": -5.97,
     "t": -1.69,
     "p_one": 0.9545,
     "cagr_diff": -8.69,
     "cost030_cagr_diff": -9.1,
     "lower_cagr_diff": -22.75,
     "neutral_cagr_diff": -4.82,
     "drop_top_cagr_diff": -9.23,
     "halves_cagr_diff": [
      -7.68,
      -9.74
     ],
     "positions_base": 208,
     "positions_lower": 587
    }
   }
  },
  "report_units": {
   "R2 P1 2007-2016（F2 の後）": {
    "before": {
     "eval_to": 201712,
     "years": 10.4,
     "ex_ann": -1.25,
     "t": -0.21,
     "cagr_diff": -4.21,
     "lower_cagr_diff": -23.46
    },
    "after": {
     "eval_to": 201712,
     "years": 10.4,
     "ex_ann": -1.55,
     "t": -0.25,
     "cagr_diff": -4.52,
     "lower_cagr_diff": -23.56
    }
   },
   "R_C5_2 NOW_only（=E12）": {
    "before": -8.42,
    "after": -8.69
   },
   "R3 P1 alpha (excess_vs_bench) 年率%・t": {
    "before": [
     -5.34,
     -1.87
    ],
    "after": [
     -5.55,
     -1.91
    ]
   },
   "R9 P1 の保有の数": {
    "before": 320,
    "after": 319
   }
  },
  "grade": "全部 C → C（主の B は P5 だけで、境界の事象が無く不変）"
 }
]''')


def cmd_run(a):
    t0 = time.time()
    pre = load_prereg()
    o, chk, A = load_events(pre)
    log = []
    dat = Data(o, A, log)
    P, E = rule_specs()
    # SURV_EW
    univ, why_u, cut, td = surv_universe(A)
    surv, surv_info = build_surv(dat, univ)
    surv_info.update({'exclusions': why_u, 'recent_filing_cut': cut, 'tickers_file_date': td})
    print('SURV_EW', surv_info['with_yahoo_series'], '社', flush=True)
    # 外れ値の確認（保有に入り得る月）
    tk_months = collections.defaultdict(set)
    for spec in list(P.values()) + list(E.values()):
        if spec.get('mode') == 'daily':
            continue
        for e in rule_events(o, spec):
            if not e.get('ticker'):
                continue
            t1 = dat.cal.next_after(dstar(e, spec['accept']))
            if t1:
                for t in ym_range(ym_add(t1 // 100, 1), min(ym_add(t1 // 100, 36), EVAL_END)):
                    tk_months[e['ticker']].add(t)
    # R1 の家ごと・PRE だけの家も同じ集合（L_NOW・L_PRE の全事象）に入っている
    for e in o['events_13d']:
        if e.get('ticker') and usable(e, None, EVENT_START):
            t1 = dat.cal.next_after(dstar(e, True))
            if t1:
                for t in ym_range(ym_add(t1 // 100, 1), min(ym_add(t1 // 100, 12), EVAL_END)):
                    tk_months[e['ticker']].add(t)
    errs, outlier_rows = check_outliers(dat, tk_months)
    print('外れ値', len(outlier_rows), '誤り', sum(1 for r in outlier_rows if r['error']), flush=True)

    results = {}
    for fam, specs in (('primary', P), ('exploratory', E)):
        rr = {}
        for k, spec in specs.items():
            print('測る', k, flush=True)
            rr[k] = eval_daily(dat, o, spec) if spec.get('mode') == 'daily' else eval_monthly(dat, o, spec, errs, surv)
            rr[k]['spec'] = {kk: vv for kk, vv in spec.items()}
            rr[k]['family'] = fam
            rr[k]['prereg_text'] = pre['families'][fam].get(k) if isinstance(pre['families'][fam].get(k), str) else pre['families'][fam].get(k)
        grade_family(rr)
        results.update(rr)

    # 報告だけの相手（主の族）
    for k in P:
        r = results[k]
        s = r['_series']
        r['vs_report_only_benchmarks'] = {bn: rs_stats(s['R'], dat.bench[bn], [m for m in s['months'] if m in dat.bench[bn]])
                                          for bn in ('FF_MKT', 'FF_SMALL_LO30_VW', 'QQQ')}
        r['vs_report_only_benchmarks']['note'] = '規則のリターン（n<10 の月の残りはその規則の相手）をそのまま報告だけの相手と比べた'

    reports = {}
    # R1 家ごと（P1 の規則・相手 SPY・使える事象 20 以上）
    fams, famp = collections.Counter(), collections.Counter()
    for e in o['events_13d']:
        if usable(e, None, EVENT_START):
            for f in e['families']:
                fams[f] += 1
            if e.get('ticker'):
                px = dat.px(e['ticker'])
                t1 = dat.cal.next_after(dstar(e, True))
                if px and t1 and t1 // 100 in px and t1 // 100 < EVAL_END:
                    for f in e['families']:
                        famp[f] += 1
    specP1 = P['P1_NOW_H12_SPY']

    def by_family(count):
        r1 = {}
        for f, n in sorted(count.items(), key=lambda kv: -kv[1]):
            if n < 20:
                continue
            evs = [e for e in o['events_13d'] if usable(e, None, EVENT_START) and f in e['families']]
            rr = eval_monthly(dat, o, specP1, errs, surv, events=evs, end_at_last_holding=True)
            r1[f] = {'usable_events': fams[f], 'priced_events': famp[f], 'lists': A.FAMILIES[f]['lists'], 'eval': rr.get('eval'),
                     'held_mean': (rr.get('held') or {}).get('mean'), 'full': rr.get('full'),
                     'cagr_diff_holding_window': rr.get('cagr_diff_holding_window'), 'holding_window_positive': rr.get('holding_window_positive'),
                     'full_to_2026_08_with_trailing_zero_excess': rr.get('full_to_2026_08_with_trailing_zero_excess'),
                     'lower': (rr.get('missing_lower') or {}).get('full'), 'cost_0.30%': ((rr.get('cost') or {}).get('0.30%') or {}).get('full')}
        meas = [f for f, v in r1.items() if v.get('holding_window_positive') is not None]
        pos_f = [f for f in meas if r1[f]['holding_window_positive']]
        return {'families': r1, 'n_families': len(r1), 'n_measured': len(meas), 'positive_cagr_diff': len(pos_f), 'positive_families': pos_f,
                'share_positive': round(len(pos_f) / max(1, len(meas)), 3), 'replicates_across_families_2of3': len(pos_f) / max(1, len(meas)) >= 2 / 3}
    reports['R1_by_family'] = by_family(fams)
    reports['R1_by_family']['note'] = ('「使える事象が20以上」を事前登録の coverage の用語（events_used＝除外と24か月の重複を除いた事象・ティッカーの有無を問わない）で読んだ。'
                                       '一覧を問わず、家が提出者にいる初回 13D（1996-07〜）。家の事象は少ないので n が10に届かない家が多い＝評価の最初の月は「最初に1社以上を持った月」に落とした'
                                       '（重み 1/max(n,10) と残りを SPY に置くことはそのまま＝超過は薄まるが符号は読める）。株価のある事象が0の家は測れない（n_measured に入れない）。'
                                       '評価の終わりはその家が最後に会社を持っていた月（v1 は 2026-08 までで、活動をやめた家は超過 0 の月が末尾に何年も付いて年率が薄まっていた・FIXES F2）。'
                                       'v1 の読みの値は full_to_2026_08_with_trailing_zero_excess に並べた（幾何の超過の符号は同じ）。'
                                       '保有の窓が24か月に満たない家（excess_stats の最短）は full が null になるので、家の数え方（positive_families）は保有の窓の幾何の年率差'
                                       'cagr_diff_holding_window（最短の月数なし）の符号で数える＝v1 と同じ家が同じ側に数えられる')
    reports['R1_by_family_priced20_first_run'] = by_family(famp)
    reports['R1_by_family_priced20_first_run']['note'] = '最初の実行では「使える事象」を「買う月の株価がある事象」と読んで20以上の家だけにしていた（4家）。事前登録の用語に合わせて上の R1 に直した。両方を残す（報告のみ）'
    # C5 の代わりの (2): 互いに重ならない家の集合
    pre_only = [e for e in o['events_13d'] if usable(e, 'PRE', EVENT_START) and 'NOW' not in e['lists']]
    rpo = eval_monthly(dat, o, specP1, errs, surv, events=pre_only, end_at_last_holding=True)
    reports['R_C5_2_disjoint_family_sets'] = {
        'NOW_only_E12': {'full': results['E12_NOWonly_H12_SPY'].get('full')},
        'PRE_only_1996_on': {'events': len(pre_only), 'eval': rpo.get('eval'), 'full': rpo.get('full'), 'lower': (rpo.get('missing_lower') or {}).get('full'),
                             'cagr_diff_holding_window': rpo.get('cagr_diff_holding_window'),
                             'full_to_2026_08_with_trailing_zero_excess': rpo.get('full_to_2026_08_with_trailing_zero_excess')},
        'both_positive': bool(results['E12_NOWonly_H12_SPY'].get('full') and results['E12_NOWonly_H12_SPY']['full']['cagr_diff'] > 0 and rpo.get('holding_window_positive'))}
    # R2 時代ごと
    eras = (('1996-2006', '1996-07-01', '2006-12-31'), ('2007-2016', '2007-01-01', '2016-12-31'), ('2017-2026', '2017-01-01', EVENT_END))
    r2 = {}
    for k in ('P1_NOW_H12_SPY', 'P4_PRE2007_H12_SPY', 'P5_MECH_H12_SPY'):
        spec = P[k]
        r2[k] = {}
        for lab, a0, z0 in eras:
            evs = [e for e in rule_events(o, spec) if a0 <= e['date'] <= z0]
            if not evs:
                continue
            rr = eval_monthly(dat, o, spec, errs, surv, events=evs, end_at_last_holding=True)
            r2[k][lab] = {'events': len(evs), 'eval': rr.get('eval'), 'held_mean': rr.get('held', {}).get('mean'), 'full': rr.get('full'),
                          'cagr_diff_holding_window': rr.get('cagr_diff_holding_window'), 'holding_window_positive': rr.get('holding_window_positive'),
                          'full_to_2026_08_with_trailing_zero_excess': rr.get('full_to_2026_08_with_trailing_zero_excess'),
                          'lower': (rr.get('missing_lower') or {}).get('full'), 'cost_0.30%': (rr.get('cost') or {}).get('0.30%', {}).get('full')}
        pe = [v for v in r2[k].values() if v.get('holding_window_positive') is not None]
        r2[k]['eras_positive'] = f"{sum(1 for v in pe if v['holding_window_positive'])}/{len(pe)}"
    reports['R2_by_era'] = r2
    reports['R2_by_era_note'] = ('時代の単位の評価の終わりは、その単位が最後に会社を持っていた月（v1 は 2026-08 までで、1996-2006・2007-2016 の単位には'
                                 '超過 0 の月が末尾に何年も付いて年率が薄まっていた・FIXES F2）。v1 の読みの値は各単位の full_to_2026_08_with_trailing_zero_excess。'
                                 '幾何の超過の符号（C5 の代わりの (3) が使うもの）は同じ')
    # R3 因子
    reports['R3_factor_alpha'] = {k: factor_alpha(results[k]['_series']['R'], results[k]['_series']['bench'], results[k]['_series']['months'], dat.rf)
                                  for k in ('P1_NOW_H12_SPY', 'P4_PRE2007_H12_SPY', 'P5_MECH_H12_SPY')}
    reports['R3_factor_alpha']['note'] = 'French の5因子（2x3）＋勢い（Mom）。excess_vs_bench = 規則 − SPY、rule_minus_rf = 規則 − RF。切片は年率%・t は Newey-West ラグ12'
    # R4 中立版
    reports['R4_neutral'] = {k: {'full': results[k]['missing_neutral']['full'], 'hold_2007_on': results[k]['missing_neutral']['hold_2007_on']} for k in P}
    # R5 被覆
    reports['R5_coverage'] = {k: results[k]['coverage'] for k in list(P) + list(E)}
    # R6 実在の器
    reports['R6_real_instruments'] = real_instruments(dat)
    # R7 窓
    reports['R7_windows'] = {k: {'post_pub_2009_on': results[k]['post_pub_2009_on'], 'recent_2013_07_on': results[k]['recent_2013_07_on']} for k in P}
    # R8 費用
    reports['R8_costs'] = {k: {c: v['full'] for c, v in results[k]['cost'].items()} for k in P}
    # R9 遅れ
    reports['R9_lag'] = lag_report(dat, results['P1_NOW_H12_SPY'])
    # R10 欠けの抜き取り
    reports['R10_missing_audit'] = {
        'status': '未実施',
        'why': ['Alpha Vantage の MCP（TIME_SERIES_MONTHLY_ADJUSTED）: 2026-09-28 の実行時に「standard API rate limit is 25 requests per day」で止まった（1回も値が取れない）',
                'FMP の MCP: CIK の検索（search-CIK）は使えた（CIK 701811 → MENT）が、上場廃止した銘柄の株価（historical-price-eod-dividend-adjusted）は「requires a higher plan」で拒否された',
                'Yahoo: 上場廃止した記号（MENT・JCP・ATML・MCRL・ATHN・DRC・GDI・JNPR ほか16記号を試した）はすべて 404'],
        'sample_file': 'out/_nx_cache/nx_activist/audit_sample.json（事前登録で固定した40件・pool 449・種 20260928）'}
    # R11 運命
    reports['R11_missing_fate'] = fate_report(dat, rule_events(o, P['P1_NOW_H12_SPY']))

    # C5 の代わり（報告のみ）
    p1e = r2['P1_NOW_H12_SPY']
    reports['C5_substitute_summary'] = {
        '(1)_families_positive_share': reports['R1_by_family']['share_positive'],
        '(1)_families_positive': f"{reports['R1_by_family']['positive_cagr_diff']}/{reports['R1_by_family']['n_measured']}",
        '(2)_NOW_only_and_PRE_only_both_positive': reports['R_C5_2_disjoint_family_sets']['both_positive'],
        '(3)_P1_eras_positive': p1e['eras_positive'],
        'note': '短い標本の格付けに C5 は無い。事前登録どおり報告だけ（格付けに使わない）'}

    # ── 事後（結果を見た後に足した診断・格付けに使わない） ──
    post = {'label': '事後（結果を見た後に足した診断）。格付けには使わない'}
    eras_m = (('2001-2006', 200101, 200612), ('2007-2016', 200701, 201612), ('2017-2026', 201701, EVAL_END))
    diag = {}
    for k in ('P5_MECH_H12_SPY', 'E13_MECH_anonymous_H12_SPY', 'E8_MECH_H12_IWM', 'P1_NOW_H12_SPY'):
        sr = results[k]['_series']
        ms = sr['months']
        d0 = {}
        for bn, bser in (('SPY', dat.bench['SPY']), ('IWM', dat.bench['IWM']), ('SURV_EW', surv), ('FF_SMALL_LO30_VW', dat.bench['FF_SMALL_LO30_VW'])):
            d0[bn] = {lab: rs_stats(sr['R'], bser, [m for m in ms if a0 <= m <= z0 and m in bser]) for lab, a0, z0 in eras_m}
            d0[bn]['full'] = rs_stats(sr['R'], bser, [m for m in ms if m in bser])
        cov = results[k]['coverage']['by_year']
        pr = {}
        for lab, a0, z0 in (('2000-2006', 2000, 2006), ('2007-2016', 2007, 2016), ('2017-2026', 2017, 2026)):
            ev = sum(v.get('events', 0) for y, v in cov.items() if a0 <= int(y) <= z0)
            pc = sum(v.get('priced_buy_month', 0) for y, v in cov.items() if a0 <= int(y) <= z0)
            pr[lab] = {'events': ev, 'priced': pc, 'share': round(pc / max(1, ev), 3)}
        diag[k] = {'vs_benchmarks_by_era': d0, 'priced_share_by_event_era': pr,
                   'note': '規則のリターン（n<10 の月の残りはその規則の相手）をそのまま別の相手と時代ごとに比べた'}
    post['where_the_MECH_win_comes_from'] = diag
    # 事象の後の月ごとの平均の超過（イベント時間）: P1 と P5 の base の保有で、保有の k か月目の（会社 − SPY）の平均
    evt = {}
    for k in ('P1_NOW_H12_SPY', 'P5_MECH_H12_SPY', 'E2_NOW_H36_SPY'):
        acc_k = collections.defaultdict(list)
        for p in results[k]['_series']['pos_base']:
            for i, (t, r) in enumerate(sorted(p['rets'].items()), 1):
                if r is BENCH or t not in dat.bench['SPY']:
                    continue
                acc_k[i].append(r - dat.bench['SPY'][t])
        evt[k] = {i: {'n': len(v), 'mean': round(S.mean(v), 4), 'median': round(sorted(v)[len(v) // 2], 4)} for i, v in sorted(acc_k.items())}
    post['event_time_mean_excess_vs_SPY'] = {'what': '保有の k か月目の（会社 − SPY）の単純平均（全保有・等分・重みなし）', 'rules': evt}
    reports['post_hoc'] = post

    tested = []
    for k, r in results.items():
        f = r.get('full') or {}
        tested.append({'rule': k, 'family': r['family'], 'grade': r.get('grade'), 'ex_ann': f.get('ex_ann'), 't': f.get('t'), 'p_one': r.get('p_one'),
                       'holm_p_one': r.get('holm_p_one'), 'cagr_diff': f.get('cagr_diff'),
                       'cost030_cagr_diff': ((r.get('cost') or {}).get('0.30%', {}).get('full') or {}).get('cagr_diff'),
                       'lower_cagr_diff': ((r.get('missing_lower') or {}).get('full') or {}).get('cagr_diff'),
                       'neutral_cagr_diff': ((r.get('missing_neutral') or {}).get('full') or {}).get('cagr_diff'),
                       'drop_top_cagr_diff': ((r.get('drop_top') or {}).get('full') or {}).get('cagr_diff'),
                       'halves_cagr_diff': [(r.get('first_half') or {}).get('cagr_diff'), (r.get('second_half') or {}).get('cagr_diff')],
                       'eval': r.get('eval')})
    # 報告だけの11本（格付けしない）も tested に残す
    for rk, desc in (('R1_by_family', '家ごと'), ('R2_by_era', '時代ごと'), ('R3_factor_alpha', '因子への回帰'), ('R4_neutral', '欠けの中立版'),
                     ('R5_coverage', '被覆'), ('R6_real_instruments', '実在の器'), ('R7_windows', '2009〜・2013-07〜'), ('R8_costs', '費用 0.50%・1.00%'),
                     ('R9_lag', '遅れ'), ('R10_missing_audit', '欠けの抜き取り'), ('R11_missing_fate', '欠けの運命')):
        tested.append({'rule': rk, 'family': 'report_only', 'grade': None, 'what': desc,
                       'status': reports[rk].get('status', '実施') if isinstance(reports[rk], dict) else '実施'})
    for rk, pref in (('R1_by_family', 'R1_family_'), ('R1_by_family_priced20_first_run', 'R1_priced20_family_')):
        for f, v in reports[rk]['families'].items():
            tested.append({'rule': f'{pref}{f}', 'family': 'report_only', 'grade': None, 'cagr_diff': (v['full'] or {}).get('cagr_diff'),
                           'cagr_diff_holding_window': v.get('cagr_diff_holding_window'),
                           't': (v['full'] or {}).get('t'), 'lower_cagr_diff': (v['lower'] or {}).get('cagr_diff'), 'eval': v['eval']})
    for k, d in reports['R2_by_era'].items():
        for lab, v in d.items():
            if isinstance(v, dict):
                tested.append({'rule': f'R2_{k}_{lab}', 'family': 'report_only', 'grade': None, 'cagr_diff': (v['full'] or {}).get('cagr_diff'),
                               'cagr_diff_holding_window': v.get('cagr_diff_holding_window'),
                               't': (v['full'] or {}).get('t'), 'lower_cagr_diff': (v['lower'] or {}).get('cagr_diff'), 'eval': v['eval']})
    v = reports['R_C5_2_disjoint_family_sets']['PRE_only_1996_on']
    tested.append({'rule': 'R_C5_2_PRE_only_1996_on', 'family': 'report_only', 'grade': None, 'cagr_diff': (v['full'] or {}).get('cagr_diff'),
                   'cagr_diff_holding_window': v.get('cagr_diff_holding_window'),
                   't': (v['full'] or {}).get('t'), 'lower_cagr_diff': (v['lower'] or {}).get('cagr_diff'), 'eval': v['eval']})
    out = {
        'angle': 'nx_activist', 'version': VERSION, 'generated': datetime.date.today().isoformat(),
        'prereg': 'out/nx_activist_prereg.json', 'global_prereg': 'out/nx_prereg.json',
        'events_check': chk,
        'grading': 'criteria_short_sample（nx_common.grade_short）。主の族6本で Holm（片側）、探索の族13本は探索の中で別に Holm（格付けはするが探索）',
        'tested': tested,
        'results': {k: strip(v) for k, v in results.items()},
        'reports': reports,
        'benchmarks_info': {'SURV_EW': surv_info, 'SPY': 'Yahoo SPY 月次の調整後終値', 'IWM': f'Yahoo IWM・{IWM_START}〜',
                            'report_only': 'French の Mkt（ff_factors）・French の Portfolios_Formed_on_ME の Lo 30（時価加重）・QQQ（Yahoo）'},
        'outliers': {'rule': OUTLIER_RULE, 'rows': outlier_rows, 'n_flagged': len(outlier_rows), 'n_confirmed_errors': sum(1 for r in outlier_rows if r['error'])},
        'yahoo': {'series_loaded': len(dat.pxm), 'no_series': len(dat.nodata), 'errors': sorted(dat.err)},
        'deviations_from_prereg': DEVIATIONS,
        'fixes': FIXES,
        'log': log,
        'runtime_sec': round(time.time() - t0, 1),
    }
    p = N.save(OUT_NAME, out)
    print('書いた', p)
    for t in tested:
        if t['family'] == 'report_only':
            continue
        print(f"{t['rule']:<30} {t['grade']}  ex {t['ex_ann']}  t {t['t']}  p1 {t['p_one']}  holm {t['holm_p_one']}  cagrΔ {t['cagr_diff']}  "
              f"cost {t['cost030_cagr_diff']}  lower {t['lower_cagr_diff']}  neutral {t['neutral_cagr_diff']}  drop {t['drop_top_cagr_diff']}  halves {t['halves_cagr_diff']}")


# ───────────────────────── 入口 ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['prices', 'run'])
    ap.add_argument('--workers', type=int, default=3)
    a = ap.parse_args()
    globals()['cmd_' + a.cmd](a)


if __name__ == '__main__':
    main()
