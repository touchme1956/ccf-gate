#!/usr/bin/env python3
"""night/ccf15.py — CCF15: 私（Claude）が中身を決めて運営する「15%の枠のETF」（読むだけ・門の判定に不使用）

ユーザー指示（2026-10-12）「あなた自身が作るETFが欲しい」→「moomoo証券を使った細かいポートフォリオ」→
「15％を細かくあなた自身が作るETFだよ？あなた自身運営するETFだよ？銘柄数は多くても構わない。」

役目（規則の正本は out/ccf15_rules.json。ここに数字を写さない）:
  あなたの資産の約7割（NASDAQ100＋SMH）が持っていない「テックの外の、壊れない複利の会社」を、
  多くの社に同じ重みで持つ。上乗せは約束しない——このリポジトリの検証で、個人が持てる形で
  2007年以降の S&P500 型の市場に確かに勝った規則は見つかっていない（docs/CLAUDE_ARCHIVE.md の mw・edge・nx）。
  役目は、コアの集中（ソフトウェア＋半導体＝100年で最大の比重）の外に、壊れにくい足場を作ること。

使い方:
  python3 night/ccf15.py fetch       # SEC frames・業種・株価をキャッシュへ（out/_ccf15_cache・gitignore）
  python3 night/ccf15.py census      # 母集団の形（業種・除外の理由の数）だけを見る（株価のリターンは見ない）
  python3 night/ccf15.py holdings    # 今日の中身（今年7月の組＝前の暦年の決算）→ out/ccf15.json
  python3 night/ccf15.py backtest    # 事前登録 out/ccf15_prereg.json どおりの過去の検証 → out/ccf15_backtest.json
  python3 night/ccf15.py nav         # 紙の上の値動き（立ち上げ日から・日次）→ out/ccf15_nav.json

約束（このリポジトリの絶対のルール7・8に従う）:
  - タグが無いことを0と読まない。測れない値は None（＝その項目は使わない／測れない理由で外す）。
  - 投下資本が自己資本の2割を切ったら ROIC は算出不能（門の規約7-b）。そのときは のれん込み（roicg）へ落ちる（門の ccfRoicJudge と同じ順）。
  - 株価は Yahoo の月足 adjclose（配当込み）。今ティッカーがある社だけ＝生き残りの偏り（倒産・買収で消えた社は入らない）。
"""
import datetime as dt
import itertools
import json
import math
import os
import statistics as S
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from industry_trends import HDRS          # SEC の User-Agent（門の採取器と同じ・ルール5）
import px_guard as PXG                    # 短い応答で長い系列を上書きしない検問
import mw_common as MW                    # 月次の統計（cagr・maxdd・excess_stats・corr）を二重実装しない

CACHE = os.path.join(BASE, 'out', '_ccf15_cache')
RULES = os.path.join(BASE, 'out', 'ccf15_rules.json')
OUT_HOLD = os.path.join(BASE, 'out', 'ccf15.json')
OUT_BT = os.path.join(BASE, 'out', 'ccf15_backtest.json')
OUT_NAV = os.path.join(BASE, 'out', 'ccf15_nav.json')
YUA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# ───────────────────────── タグ ─────────────────────────
# 流量（年次・CYyyyy）
DUR = ['OperatingIncomeLoss', 'NetIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities', 'IncomeTaxExpenseBenefit',
       'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
       'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments',
       'InterestExpense', 'InterestExpenseDebt', 'InterestExpenseNonoperating', 'InterestAndDebtExpense',
       'DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet',
       'GrossProfit', 'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
       'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet',
       'CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold']
SHARES = 'WeightedAverageNumberOfDilutedSharesOutstanding'
# 残高（年末の瞬間・CYyyyyQ4I）——gaps_sell と同じ候補（負債は『代替』と『構成要素』を分ける）
INS = ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
       'LongTermDebt', 'LongTermDebtNoncurrent', 'LongTermDebtCurrent', 'ShortTermBorrowings',
       'LongTermDebtAndCapitalLeaseObligations', 'LongTermDebtAndCapitalLeaseObligationsCurrent', 'DebtCurrent',
       'CommercialPaper', 'LongTermNotesPayable', 'UnsecuredLongTermDebt',
       'DebtAndCapitalLeaseObligations', 'DebtLongtermAndShorttermCombinedAmount',
       'Goodwill', 'IntangibleAssetsNetExcludingGoodwill', 'CashAndCashEquivalentsAtCarryingValue',
       'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents', 'Assets', 'Liabilities',
       'AssetsCurrent', 'LiabilitiesCurrent', 'RetainedEarningsAccumulatedDeficit']
EQ = ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']
PRETAX = ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
          'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments']
INTEREST = ['InterestExpense', 'InterestExpenseDebt', 'InterestExpenseNonoperating', 'InterestAndDebtExpense']
DA = ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet']
REV = ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
       'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet']
COGS = ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold']   # 代替（総額）。先に当たった一つ
CASH = ['CashAndCashEquivalentsAtCarryingValue', 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents']
YEARS = range(2008, dt.date.today().year)   # 決算の年（〜去年。frames は会計年度の終わりの暦年に寄せる＝実測 PG 2025-06-30 → CY2025）
FLOAT_YEARS = range(2010, dt.date.today().year + 1)


def rules():
    return json.load(open(RULES, encoding='utf-8'))


# ───────────────────────── 取得 ─────────────────────────
_lock = threading.Lock()
_last = [0.0]


def sec_json(url, tries=5):
    """SEC へ 1秒に8回まで。404 は None（無い＝0 と読まない）。取れなければ例外（黙って空にしない）"""
    for i in range(tries):
        with _lock:
            w = _last[0] + 0.125 - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (i + 1))
        except Exception:
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}')


def frame(tax, tag, unit, period, fetch=True):
    fn = os.path.join(CACHE, 'frames', f'{tax}_{tag}_{unit}_{period}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    if not fetch:
        return []
    j = sec_json(f'https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/{unit}/{period}.json')
    data = [[e['cik'], e['val'], e.get('start'), e.get('end'), e.get('accn')] for e in (j or {}).get('data', [])]
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    tmp = fn + '.tmp'
    json.dump(data, open(tmp, 'w'))
    os.replace(tmp, fn)
    return data


def frame_jobs():
    jobs = []
    for y in YEARS:
        for t in DUR:
            jobs.append(('us-gaap', t, 'USD', f'CY{y}'))
        jobs.append(('us-gaap', SHARES, 'shares', f'CY{y}'))
        for t in INS:
            jobs.append(('us-gaap', t, 'USD', f'CY{y}Q4I'))
    today = dt.date.today()
    for y in FLOAT_YEARS:
        for q in (1, 2, 3, 4):
            if dt.date(y, 3 * q, 1) > today:
                continue
            jobs.append(('dei', 'EntityPublicFloat', 'USD', f'CY{y}Q{q}I'))
    return jobs


def fetch_frames():
    jobs = [j for j in frame_jobs() if not os.path.exists(os.path.join(CACHE, 'frames', f'{j[0]}_{j[1]}_{j[2]}_{j[3]}.json'))]
    print(f'frames: 取得 {len(jobs)} 本（キャッシュ済みは飛ばす）', flush=True)
    done = [0]

    def one(j):
        frame(*j)
        with _lock:
            done[0] += 1
            if done[0] % 50 == 0:
                print(f'  {done[0]}/{len(jobs)}', flush=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, jobs))


def tickers(fetch=True):
    """SEC のティッカー表（時価の大きい順）。cik→最初のティッカー（株式の種類が複数なら先頭）"""
    fn = os.path.join(CACHE, 'company_tickers.json')
    if not os.path.exists(fn) and fetch:
        j = sec_json('https://www.sec.gov/files/company_tickers.json')
        os.makedirs(CACHE, exist_ok=True)
        json.dump(j, open(fn, 'w'))
    j = json.load(open(fn)) if os.path.exists(fn) else {}
    c2t, names = {}, {}
    for v in j.values():
        c = int(v['cik_str'])
        if c not in c2t:
            c2t[c] = str(v['ticker']).upper().replace('.', '-')
            names[c] = v.get('title', '')
    return c2t, names


def sic_map(ciks, fetch=True):
    """SIC（業種コード）。out/sic_by_cik.json（industry_trends が貯めたもの）＋足りない社は submissions から"""
    base = json.load(open(os.path.join(BASE, 'out', 'sic_by_cik.json')))
    fn = os.path.join(CACHE, 'sic_extra.json')
    extra = json.load(open(fn)) if os.path.exists(fn) else {}
    out, miss = {}, []
    for c in ciks:
        s = base.get(str(c)) or extra.get(str(c))
        if s not in (None, ''):
            try:
                out[c] = int(s)
                continue
            except ValueError:
                pass
        if str(c) not in extra:
            miss.append(c)
    if fetch and miss:
        print(f'SIC: submissions から {len(miss)} 社', flush=True)

        def one(c):
            j = sec_json(f'https://data.sec.gov/submissions/CIK{c:010d}.json')
            return c, (j or {}).get('sic') or ''
        with ThreadPoolExecutor(4) as ex:
            for c, s in ex.map(one, miss):
                extra[str(c)] = s
                if s:
                    try:
                        out[c] = int(s)
                    except ValueError:
                        pass
        os.makedirs(CACHE, exist_ok=True)
        json.dump(extra, open(fn, 'w'))
    return out


def yahoo_m(sym, fetch=True):
    """月足 adjclose（配当込み・yyyymm→値）と株式分割（[(yyyymmdd, 倍率)]）。取れなければ None"""
    fn = os.path.join(CACHE, 'px', f'{sym}.json')
    if os.path.exists(fn):
        j = json.load(open(fn))
        return None if j is None else {'m': {int(k): v for k, v in j['m'].items()}, 'splits': j['splits'], 'ccy': j.get('ccy')}
    if not fetch:
        return None
    t0 = int(dt.datetime(2007, 1, 1).timestamp())
    t1 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={t0}&period2={t1}&interval=1mo&events=split")
    res = None
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=YUA), timeout=40) as r:
                res = (json.loads(r.read()).get('chart', {}).get('result') or [None])[0]
            break
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                res = None
                break
            time.sleep(3 * (a + 1))
        except Exception:
            time.sleep(3 * (a + 1))
    out = None
    if res and res.get('timestamp'):
        ind = res['indicators']
        ser = (ind.get('adjclose') or [{}])[0].get('adjclose') or ind['quote'][0]['close']
        gmt = (res.get('meta') or {}).get('gmtoffset') or 0
        m = {}
        for t, v in zip(res['timestamp'], ser):
            if v is None:
                continue
            d = dt.datetime.utcfromtimestamp(t + gmt)
            m[f'{d.year:04d}-{d.month:02d}'] = float(v)
        m = PXG.vet(sym, m, 'ccf15.yahoo_m', req_start=t0, record=False) or {}
        sp = []
        for e in ((res.get('events') or {}).get('splits') or {}).values():
            if e.get('numerator') and e.get('denominator'):
                d = dt.datetime.utcfromtimestamp(e['date'])
                sp.append([d.year * 10000 + d.month * 100 + d.day, e['numerator'] / e['denominator']])
        if m:
            out = {'m': {int(k[:4]) * 100 + int(k[5:]): v for k, v in m.items()}, 'splits': sorted(sp),
                   'ccy': (res.get('meta') or {}).get('currency')}
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    json.dump(None if out is None else {'m': {str(k): v for k, v in out['m'].items()}, 'splits': out['splits'], 'ccy': out['ccy']},
              open(fn, 'w'))
    time.sleep(0.15)
    return out


def yahoo_d(sym, start):
    """日足 adjclose（yyyymmdd→値）。立ち上げ日からの紙の上の値動きにだけ使う（キャッシュしない＝毎日新しく）"""
    t0 = int(dt.datetime.strptime(start, '%Y-%m-%d').timestamp()) - 7 * 86400
    t1 = int(time.time()) + 86400
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={t0}&period2={t1}&interval=1d"
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=YUA), timeout=40) as r:
                res = (json.loads(r.read()).get('chart', {}).get('result') or [None])[0]
            if not res or not res.get('timestamp'):
                return None
            ind = res['indicators']
            ser = (ind.get('adjclose') or [{}])[0].get('adjclose') or ind['quote'][0]['close']
            gmt = (res.get('meta') or {}).get('gmtoffset') or 0
            out = {}
            for t, v in zip(res['timestamp'], ser):
                if v is None:
                    continue
                d = dt.datetime.utcfromtimestamp(t + gmt)
                out[d.year * 10000 + d.month * 100 + d.day] = float(v)
            return out
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(3 * (a + 1))
        except Exception:
            time.sleep(3 * (a + 1))
    return None


# ───────────────────────── 決算の表（会社×年） ─────────────────────────
def first(d, keys):
    """代替の候補: 先に当たった値（無ければ None）。0 は値として扱う"""
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def debt_of(d):
    """有利子負債（gaps_sell.debt_of と同じ読み方）。タグが一つも無ければ None（負債0と読まない）"""
    lnc = first(d, ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations', 'LongTermNotesPayable', 'UnsecuredLongTermDebt'])
    st = first(d, ['ShortTermBorrowings', 'CommercialPaper'])
    if d.get('DebtCurrent') is not None:
        cur = d['DebtCurrent']
    else:
        c = first(d, ['LongTermDebtCurrent', 'LongTermDebtAndCapitalLeaseObligationsCurrent'])
        cur = None if (c is None and st is None) else (c or 0) + (st or 0)
    if lnc is not None:
        return lnc + (cur or 0)
    if d.get('LongTermDebt') is not None:
        return d['LongTermDebt'] + (st or 0)
    if d.get('DebtLongtermAndShorttermCombinedAmount') is not None:
        return d['DebtLongtermAndShorttermCombinedAmount']
    if d.get('DebtAndCapitalLeaseObligations') is not None:
        return d['DebtAndCapitalLeaseObligations'] + (st or 0)
    return cur


def frame_cached(tax, tag, unit, period):
    fn = os.path.join(CACHE, 'frames', f'{tax}_{tag}_{unit}_{period}.json')
    if not os.path.exists(fn):
        raise FileNotFoundError(f'frames が無い: {fn}（先に python3 night/ccf15.py fetch）')
    return json.load(open(fn))


def load_panel():
    P = {}      # cik -> 年 -> {タグ: 値, '_end': 会計年度の終わり}
    for y in YEARS:
        for t in DUR:
            for cik, v, st, en, accn in frame_cached('us-gaap', t, 'USD', f'CY{y}'):
                d = P.setdefault(cik, {}).setdefault(y, {})
                d[t] = v
                if t == 'OperatingIncomeLoss' and en:
                    d['_end'] = en
        for cik, v, st, en, accn in frame_cached('us-gaap', SHARES, 'shares', f'CY{y}'):
            d = P.setdefault(cik, {}).setdefault(y, {})
            d['_sh'], d['_sh_end'] = v, en
        for t in INS:
            for cik, v, st, en, accn in frame_cached('us-gaap', t, 'USD', f'CY{y}Q4I'):
                P.setdefault(cik, {}).setdefault(y, {})[t] = v
    return P


def features(P):
    F = {}
    for cik, ys in P.items():
        out = {}
        for y, d in ys.items():
            oi = d.get('OperatingIncomeLoss')
            eq = first(d, EQ)
            A, L = d.get('Assets'), d.get('Liabilities')
            eq_fix = False
            if eq is not None and eq <= 0 and A and L is not None and (A - L) > 0.05 * A:
                eq, eq_fix = A - L, True      # 提出の XBRL の符号の誤り（gaps_sell.identity_fix と同じ・例 TDY 2014）
            pre = first(d, PRETAX)
            tax = d.get('IncomeTaxExpenseBenefit')
            t = min(0.5, max(0.0, tax / pre)) if (pre and pre > 0 and tax is not None) else (0.35 if y <= 2017 else 0.21)
            debt = debt_of(d)
            roic = roicg = None
            if oi is not None and eq is not None and debt is not None and eq > 0:
                nopat = oi * (1 - t)
                ic = eq + debt - (d.get('Goodwill') or 0) - (d.get('IntangibleAssetsNetExcludingGoodwill') or 0)
                if ic > 0 and ic >= 0.2 * eq:            # 規約7-b: 投下資本が自己資本の2割未満なら算出不能
                    roic = nopat / ic * 100
                if eq + debt > 0:
                    roicg = nopat / (eq + debt) * 100     # のれん込み（門の ccfRoicJudge が roic の次に落ちる先）
            da = first(d, DA)
            ebitda = (oi + da) if (oi is not None and da is not None) else None
            cash = first(d, CASH)
            nde = ((debt - cash) / ebitda) if (debt is not None and cash is not None and ebitda and ebitda > 0) else None
            ie = first(d, INTEREST)
            icov = (oi / ie) if (oi is not None and ie and ie > 0) else None
            ca, cl, re_ = d.get('AssetsCurrent'), d.get('LiabilitiesCurrent'), d.get('RetainedEarningsAccumulatedDeficit')
            z = None
            if A and L and A > 0 and L > 0 and None not in (ca, cl, re_, oi, eq):
                z = 6.56 * (ca - cl) / A + 3.26 * re_ / A + 6.72 * oi / A + 1.05 * eq / L
            gp = d.get('GrossProfit')
            if gp is None:
                rev, cg = first(d, REV), first(d, COGS)
                gp = (rev - cg) if (rev is not None and cg is not None) else None
            ocf = d.get('NetCashProvidedByUsedInOperatingActivities')
            out[y] = dict(oi=oi, eq=eq, eq_fix=eq_fix, roic=roic, roicg=roicg,
                          roic_used=roic if roic is not None else roicg,
                          nde=nde, icov=icov, z=z,
                          gpa=(gp / A) if (gp is not None and A and A > 0) else None,
                          cfoa=(ocf / A) if (ocf is not None and A and A > 0) else None,
                          sh=d.get('_sh'), sh_end=d.get('_sh_end'), end=d.get('_end'))
        F[cik] = out
    return F


def dilution(F, cik, D, splits, years):
    """years 年の株数（希薄化後の加重平均）の変化。株式分割は Yahoo の分割の記録で補正する。
    frames は『最後に出された値』を返す＝古い年は後の10-Kで分割を遡って直した値のことがあり、基準が揃わない。
    窓の中（古い年の会計年度の終わり〜今）に分割があれば、分割の組み合わせで割った候補のうち1に最も近いものを採る
    （3年の本当の株数の変化は分割の倍率よりずっと小さいので取り違えにくい）。それでも±60%を超えれば測れない（None）。
    分割が無いのに 0.5倍未満・2.5倍超なら、記録に無い分割・併合かタグの誤りを疑って測れない（大きな自社株買いに化けさせない）"""
    a, b = F.get(cik, {}).get(D - years), F.get(cik, {}).get(D)
    if not a or not b or not a.get('sh') or not b.get('sh') or a['sh'] <= 0 or b['sh'] <= 0:
        return None
    r = b['sh'] / a['sh']
    lo = int((a.get('sh_end') or a.get('end') or f'{D - years}-01-01').replace('-', ''))
    sp = [f for d8, f in (splits or []) if d8 > lo and f > 0 and abs(math.log(f)) > 0.05]
    if not sp:
        return None if (r < 0.5 or r > 2.5) else r - 1
    cand = min((r / math.prod(c) for k in range(len(sp) + 1) for c in itertools.combinations(sp, k)),
               key=lambda x: abs(math.log(x)))
    return None if abs(math.log(cand)) > math.log(1.6) else cand - 1


# ───────────────────────── 母集団・外す・並べる・選ぶ ─────────────────────────
def float_table():
    FL = {}
    for y in FLOAT_YEARS:
        for q in (1, 2, 3, 4):
            fn = os.path.join(CACHE, 'frames', f'dei_EntityPublicFloat_USD_CY{y}Q{q}I.json')
            if not os.path.exists(fn):
                continue
            for cik, v, st, en, accn in json.load(open(fn)):
                if en and v and v > 0:
                    FL.setdefault(cik, {})[en] = v
    return FL


def add_months(d, n):
    m = d.year * 12 + d.month - 1 + n
    y, mo = divmod(m, 12)
    mo += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    return dt.date(y, mo, min(d.day, last))


def universe(FL, asof, top):
    """公開浮動株時価（10-K の表紙）の上位 top 社。使えるのは asof の12か月前〜30か月前の値（10-K が出ていた値）"""
    lo, hi = add_months(asof, -30).isoformat(), add_months(asof, -12).isoformat()
    cand = {}
    for cik, ends in FL.items():
        es = [e for e in ends if lo <= e <= hi]
        if es:
            cand[cik] = ends[max(es)]
    return sorted(cand, key=lambda c: -cand[c])[:top], cand


def sic_excluded(sic, R):
    for lo, hi, why in R['universe']['exclude_sic']:
        if lo <= sic <= hi:
            return why
    return None


def kills(F, c, D, R):
    k = R['kills']
    f = F.get(c, {}).get(D)
    if not f or f['oi'] is None:
        return ['決算が無い（測れない）']
    why = []
    if f['oi'] <= 0:
        why.append('営業赤字')
    if f['eq'] is None:
        why.append('自己資本が測れない')
    elif f['eq'] <= 0:
        why.append('債務超過')
    if f['nde'] is not None and f['nde'] > k['nde_max']:
        why.append(f"純負債/EBITDA>{k['nde_max']}")
    if f['icov'] is not None and f['icov'] < k['intcov_min']:
        why.append(f"利払いの余裕<{k['intcov_min']}倍")
    if k.get('z2_min') is not None and f['z'] is not None and f['z'] < k['z2_min']:
        why.append(f"Z''<{k['z2_min']}")
    rs = [F[c][y]['roic_used'] for y in range(D - k['roic_years'] + 1, D + 1)
          if y in F[c] and F[c][y]['roic_used'] is not None]
    if len(rs) < k['roic_min_years']:
        why.append(f"ROICが{k['roic_min_years']}年分ない（測れない）")
    elif S.median(rs) <= k['wacc']:
        why.append(f"ROIC中央値≤{k['wacc']}%")
    return why


def pct(vals, higher=True):
    """順位を0〜1へ（同点は平均の順位）。higher=False なら小さいほど上"""
    items = sorted(vals.items(), key=lambda kv: kv[1])
    n, out, i = len(items), {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        for q in range(i, j + 1):
            out[items[q][0]] = r if higher else 1 - r
        i = j + 1
    return out


class Ctx:
    def __init__(self, fetch=False):
        self.F = features(load_panel())
        self.FL = float_table()
        self.c2t, self.names = tickers(fetch)
        self.SIC = {}
        self.PX = {}

    def need_sic(self, ciks, fetch):
        self.SIC.update(sic_map([c for c in ciks if c not in self.SIC], fetch))

    def px(self, t, fetch=False):
        if t not in self.PX:
            self.PX[t] = yahoo_m(t, fetch)
        return self.PX[t]


def cohort(ctx, Y, R, px_key=None, fetch=False):
    """Y 年7月の組（6月末の時点で使える決算＝Y−1 年の会計年度）。px_key: その月の株価がある社だけ（買える社だけ）"""
    asof = dt.date(Y, 6, 30)
    D = Y - 1
    ranked, fl = universe(ctx.FL, asof, R['universe']['float_top'])
    ctx.need_sic(ranked, fetch)
    log = {}

    def note(k):
        log[k] = log.get(k, 0) + 1
    U0 = []
    for c in ranked:
        sic = ctx.SIC.get(c)
        if sic is None:
            note('業種が分からない')
            continue
        w = sic_excluded(sic, R)
        if w:
            note(f'除く: {w}')
            continue
        t = ctx.c2t.get(c)
        if not t:
            note('今はティッカーが無い（買収・倒産などで消えた社＝生き残りの偏り）')
            continue
        p = ctx.px(t, fetch)
        if px_key is not None and (not p or px_key not in p['m']):
            note('その月の株価が無い')
            continue
        U0.append(c)
    E, why = [], {}
    for c in U0:
        w = kills(ctx.F, c, D, R)
        if w:
            why[c] = w
            note(f'外す: {w[0]}')
            continue
        E.append(c)
    k = R['rank']
    met = {'gpa': {}, 'cfoa': {}, 'dsh': {}}
    for c in E:
        f = ctx.F[c][D]
        if f['gpa'] is not None:
            met['gpa'][c] = f['gpa']
        if f['cfoa'] is not None:
            met['cfoa'][c] = f['cfoa']
        p = ctx.PX.get(ctx.c2t[c])
        d = dilution(ctx.F, c, D, (p or {}).get('splits'), k['dsh_years'])
        if d is not None:
            met['dsh'][c] = d
    rk = {'gpa': pct(met['gpa'], True), 'cfoa': pct(met['cfoa'], True), 'dsh': pct(met['dsh'], False)}
    comp = {}
    for c in E:
        v = [rk[m][c] for m in k['metrics'] if c in rk[m]]
        if len(v) >= k['min_metrics']:
            comp[c] = sum(v) / len(v)
        else:
            note('質の物差しが2つそろわない（測れない）')
    sel = R['select']
    order = sorted(comp, key=lambda c: (-comp[c], -fl.get(c, 0)))
    H, cnt = [], {}
    for c in order:
        s2 = ctx.SIC[c] // 100
        if cnt.get(s2, 0) >= sel['max_per_sic2']:
            continue
        H.append(c)
        cnt[s2] = cnt.get(s2, 0) + 1
        if len(H) == sel['n']:
            break
    return dict(Y=Y, D=D, asof=asof.isoformat(), ranked=ranked, fl=fl, U0=U0, E=E, H=H, comp=comp, met=met, why=why, log=log)


BENCH = ['ITA', 'SPY', 'RSP', 'QQQ', 'SMH', 'SPXT']     # SPXT = S&P500 からテック（情報技術）を除いた指数の ETF（2015-09〜）
COHORTS = range(2013, dt.date.today().year + 1)        # 7月の組（2013年7月〜今年。決算は前の暦年）


def prefetch_prices(ctx, R):
    """各年の母集団（金融・テックを除いた生き残り）と相手の ETF の月足を、まとめて取っておく"""
    need = set(BENCH)
    for Y in COHORTS:
        ranked, fl = universe(ctx.FL, dt.date(Y, 6, 30), R['universe']['float_top'])
        ctx.need_sic(ranked, True)
        for c in ranked:
            s = ctx.SIC.get(c)
            if s is None or sic_excluded(s, R):
                continue
            if ctx.c2t.get(c):
                need.add(ctx.c2t[c])
    todo = sorted(t for t in need if not os.path.exists(os.path.join(CACHE, 'px', f'{t}.json')))
    print(f'株価: {len(need)} 本（未取得 {len(todo)}）', flush=True)
    done = [0]

    def one(t):
        yahoo_m(t, True)
        with _lock:
            done[0] += 1
            if done[0] % 100 == 0:
                print(f'  {done[0]}/{len(todo)}', flush=True)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, todo))
    return need


# ───────────────────────── 業種の名前（表示だけ） ─────────────────────────
SIC3_JA = {283: '医薬品', 284: '日用品・化粧品', 384: '医療機器', 382: '計測・分析機器', 381: '防衛・航法機器', 372: '航空機・部品',
           371: '自動車・部品', 373: '造船', 374: '鉄道車両', 357: 'コンピュータ', 356: '産業機械', 353: '建設・鉱山機械',
           352: '農業機械', 354: '工作機械', 358: '空調・冷凍機器', 364: '照明・配線機器', 362: '電気機器', 363: '家電',
           201: '食肉', 202: '乳製品', 203: '加工食品', 204: '穀物加工', 206: '菓子', 208: '飲料', 209: '食品',
           291: '石油精製', 131: '石油・ガスの生産', 138: '石油・ガスのサービス', 492: 'ガス', 491: '電力', 495: '廃棄物処理',
           401: '鉄道', 421: 'トラック輸送', 451: '航空', 452: '航空', 473: '物流の手配', 481: '通信', 484: 'ケーブルテレビ',
           531: '総合小売', 533: '総合小売', 539: '総合小売', 541: '食品スーパー', 551: '自動車販売', 552: '自動車販売',
           561: '衣料品店', 565: '衣料品店', 566: '靴店', 571: '家具店', 573: '家電量販', 581: '外食', 591: '薬局',
           594: '専門店', 596: 'ネット・通販', 599: '専門店', 701: 'ホテル・カジノ', 734: '企業向けサービス', 735: '機器レンタル',
           736: '人材', 738: '企業向けサービス', 781: '映画・動画', 799: '娯楽', 801: '医療', 805: '介護', 806: '病院',
           807: '検査・医療サービス', 808: '在宅医療', 809: '医療サービス', 822: '教育', 871: '技術サービス', 873: '研究・検査',
           874: '経営・調査サービス'}
SIC2_JA = {1: '農業', 2: '農業', 10: '金属鉱業', 12: '石炭', 13: '石油・ガス', 14: '鉱物', 15: '建設', 16: '建設', 17: '設備工事',
           20: '食品', 21: 'たばこ', 22: '繊維', 23: '衣料', 24: '木材', 25: '家具', 26: '紙・包装', 27: '出版・印刷',
           28: '化学', 29: '石油精製', 30: 'ゴム・樹脂', 31: '皮革', 32: '窯業・ガラス', 33: '鉄鋼・非鉄', 34: '金属製品',
           35: '機械', 36: '電気機器', 37: '輸送機器', 38: '精密・医療機器', 39: 'その他の製造', 40: '鉄道', 42: 'トラック輸送',
           44: '海運', 45: '航空', 46: 'パイプライン', 47: '運輸サービス', 48: '通信', 49: '公益', 50: '卸売', 51: '卸売',
           52: '建材・園芸小売', 53: '総合小売', 54: '食品スーパー', 55: '自動車販売', 56: '衣料品店', 57: '家具・家電店',
           58: '外食', 59: '専門小売', 70: 'ホテル', 72: '個人向けサービス', 73: '企業向けサービス', 75: '自動車整備',
           78: '映画・動画', 79: '娯楽', 80: '医療サービス', 82: '教育', 87: '技術・経営サービス', 99: 'その他'}


def sector_ja(sic):
    if sic is None:
        return '不明'
    return SIC3_JA.get(sic // 10) or SIC2_JA.get(sic // 100) or f'SIC {sic}'


# ───────────────────────── 月次の値動き ─────────────────────────
def ym_add(k, n):
    y, m = divmod(k // 100 * 12 + k % 100 - 1 + n, 12)
    return y * 100 + m + 1


def basket_returns(ctx, by_year, last, mode='bh'):
    """年ごとに持ち替える同じ重みのかご（yyyymm→小数）。by_year: {Y: [ティッカー]}。
    bh＝7月に同じ重みで買って翌年6月まで持ったまま（本物の ETF の年1回の入れ替えに近い）／
    ew＝毎月同じ重みに戻す（新しいお金で足りない社を買う運用に近い）。
    月の株価が欠けた社はその月 0%（次に値がある月に、最後の値からの変化として数える）"""
    out, gaps = {}, 0
    for Y in sorted(by_year):
        base = Y * 100 + 6
        px = {t: ctx.PX[t]['m'] for t in by_year[Y] if ctx.PX.get(t) and base in ctx.PX[t]['m']}
        if not px:
            continue
        val = {t: 1.0 / len(px) for t in px}
        lastp = {t: px[t][base] for t in px}
        for i in range(1, 13):
            k = ym_add(base, i)
            if k > last:
                break
            rs = {}
            for t in px:
                p = px[t].get(k)
                if p is None:
                    rs[t] = 0.0
                    gaps += 1
                else:
                    rs[t] = p / lastp[t] - 1
                    lastp[t] = p
            if mode == 'bh':
                tot = sum(val.values())
                out[k] = sum(val[t] * rs[t] for t in px) / tot
                for t in px:
                    val[t] *= 1 + rs[t]
            else:
                out[k] = sum(rs.values()) / len(rs)
    return out, gaps


def etf_returns(ctx, t, a, z):
    m = (ctx.px(t) or {}).get('m') or {}
    return {k: m[k] / m[ym_add(k, -1)] - 1 for k in sorted(m) if a <= k <= z and ym_add(k, -1) in m}


def stats(r, q=None):
    ks = sorted(r)
    if len(ks) < 12:
        return None
    v = [r[k] for k in ks]
    o = {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / 12, 1), 'cagr': round(MW.cagr(v) * 100, 2),
         'vol': round(S.stdev(v) * math.sqrt(12) * 100, 1), 'maxdd': round(MW.maxdd(r) * 100, 1)}
    for y in (2020, 2022):
        ys = [r[k] for k in ks if k // 100 == y]
        if len(ys) == 12:
            o[f'y{y}'] = round((math.prod(1 + x for x in ys) - 1) * 100, 1)
    if q:
        c = [k for k in ks if k in q]
        if len(c) >= 24:
            a, b = [r[k] for k in c], [q[k] for k in c]
            o['corr_qqq'] = round(MW.corr(a, b), 2)
            vb = S.pvariance(b)
            o['beta_qqq'] = round(sum((x - S.mean(a)) * (y - S.mean(b)) for x, y in zip(a, b)) / len(c) / vb, 2) if vb else None
            worst = sorted(c, key=lambda k: q[k])[:12]
            o['qqq_worst12_avg'] = round(S.mean(r[k] for k in worst) * 100, 2)
            o['qqq_worst12_qqq'] = round(S.mean(q[k] for k in worst) * 100, 2)
    return o


def mix(parts):
    """毎月同じ比へ戻す組み合わせ。parts: [(重み, 系列)]。全部がそろう月だけ"""
    ks = sorted(set.intersection(*[set(s) for _, s in parts]))
    tw = sum(w for w, _ in parts)
    return {k: sum(w * s[k] for w, s in parts) / tw for k in ks}


def growth(series):
    """同じ月から始めた1ドルの推移（ページのグラフ用・月末の値）。全部がそろう月だけ"""
    ks = sorted(set.intersection(*[set(v) for v in series.values()]))
    out, lv = {'months': ks}, {}
    for name, r in series.items():
        v, path = 1.0, []
        for k in ks:
            v *= 1 + r[k]
            path.append(round(v, 4))
        out[name] = path
    return out


def dca(r, months):
    ks = sorted(r)
    out = []
    for i in range(len(ks) - months + 1):
        v = 0.0
        for k in ks[i:i + months]:
            v = (v + 1) * (1 + r[k])
        out.append(v / months)
    return out


# ───────────────────────── 過去の検証（事前登録 out/ccf15_prereg.json） ─────────────────────────
def variant(R, **kw):
    R2 = json.loads(json.dumps(R))
    for k, v in kw.items():
        sec, key = k.split('__')
        R2[sec][key] = v
    return R2


def run_backtest(ctx, R, last, mode='bh'):
    """各年7月の組を作り、かごの月次リターンを出す。H＝CCF15／U0＝同じ土俵の平均（金融・テックを除いた生き残り）／
    E＝壊れないの検問を通った社の平均"""
    H, U0, E, logs = {}, {}, {}, {}
    for Y in COHORTS:
        if Y * 100 + 6 > last:
            break
        co = cohort(ctx, Y, R, px_key=Y * 100 + 6)
        H[Y] = [ctx.c2t[c] for c in co['H']]
        U0[Y] = [ctx.c2t[c] for c in co['U0']]
        E[Y] = [ctx.c2t[c] for c in co['E']]
        logs[Y] = {'母集団（上位）': len(co['ranked']), '同じ土俵（生き残り）': len(co['U0']), '検問を通った': len(co['E']),
                   '選んだ': len(co['H']), '内訳': co['log'], '中身': H[Y]}
    rH, gH = basket_returns(ctx, H, last, mode)
    rU, gU = basket_returns(ctx, U0, last, mode)
    rE, gE = basket_returns(ctx, E, last, mode)
    return rH, rU, rE, logs, {'H': gH, 'U0': gU, 'E': gE}


def judge_selection(rH, rU, th):
    ex = MW.excess_stats(rH, rU)
    if not ex:
        return None, '測れない'
    if ex['ex_ann'] >= th['ex_ann'] and ex['t'] is not None and ex['t'] >= th['t']:
        v = '選び方に中身あり（同じ土俵の平均に勝った）'
    elif ex['ex_ann'] <= -th['ex_ann'] and ex['t'] is not None and ex['t'] <= -th['t']:
        v = '選び方で負けた（同じ土俵の平均に負けた）'
    else:
        v = '差は偶然と区別できない'
    return ex, v


def judge_slot(rCCF, rITA, q, smh, th, months):
    P1 = mix([(th['w_core'], q), (th['w_smh'], smh), (th['w_slot'], rCCF)])
    P0 = mix([(th['w_core'], q), (th['w_smh'], smh), (th['w_slot'], rITA)])
    ks = sorted(set(P1) & set(P0))
    P1 = {k: P1[k] for k in ks}
    P0 = {k: P0[k] for k in ks}
    s1, s0 = stats(P1), stats(P0)
    d1, d0 = dca(P1, months), dca(P0, months)
    dg = round(s1['cagr'] - s0['cagr'], 2)
    dd = round(s1['maxdd'] - s0['maxdd'], 1)
    if dg >= th['dcagr'] and dd >= -th['ddd_ok']:
        v = 'ITA より良い'
    elif dg <= -th['dcagr'] or dd <= -th['ddd_bad']:
        v = 'ITA より悪い'
    else:
        v = 'ITA とほぼ同じ'
    return {'with_ccf15': s1, 'with_ita': s0, 'dcagr': dg, 'dmaxdd': dd,
            'dca_months': months, 'dca_windows': len(d1),
            'dca_median_ccf15': round(S.median(d1), 3) if d1 else None, 'dca_median_ita': round(S.median(d0), 3) if d0 else None,
            'dca_min_ccf15': round(min(d1), 3) if d1 else None, 'dca_min_ita': round(min(d0), 3) if d0 else None}, v


def backtest():
    R = rules()
    PR = json.load(open(os.path.join(BASE, 'out', 'ccf15_prereg.json'), encoding='utf-8'))
    ev = PR['evaluation']
    ctx = Ctx(fetch=False)
    spy = (ctx.px('SPY') or {}).get('m') or {}
    last = max(k for k in spy if k < int(dt.date.today().strftime('%Y%m')))        # 終わった月まで
    a = COHORTS[0] * 100 + 7
    rH, rU, rE, logs, gaps = run_backtest(ctx, R, last)
    B = {t: etf_returns(ctx, t, a, last) for t in BENCH}
    q = B['QQQ']
    ser = {'CCF15': rH, '同じ土俵の平均（生き残り）': rU, '検問を通った社の平均': rE}
    ser.update({t: B[t] for t in BENCH})
    st = {k: stats(v, q) for k, v in ser.items()}
    sel_ex, sel_v = judge_selection(rH, rU, ev['J1'])
    kill_ex = MW.excess_stats(rE, rU)
    slot, slot_v = judge_slot(rH, B['ITA'], q, B['SMH'], ev['J2'], ev['J2']['dca_months'])
    vs = {t: MW.excess_stats(rH, B[t]) for t in ('ITA', 'SPY', 'RSP', 'SPXT', 'QQQ')}
    # 感度（事前登録どおり・判定には使わない）
    sens = {}
    for name, kw in ev['sensitivity'].items():
        R2 = variant(R, **kw) if kw and not kw.get('mode') else R
        mode = kw.get('mode', 'bh') if kw else 'bh'
        h2, u2, e2, _, _ = run_backtest(ctx, R2, last, mode)
        ex2, v2 = judge_selection(h2, u2, ev['J1'])
        sl2, sv2 = judge_slot(h2, B['ITA'], q, B['SMH'], ev['J2'], ev['J2']['dca_months'])
        sens[name] = {'stats': stats(h2, q), 'vs_same_pool': ex2, 'J1': v2, 'J2': sv2, 'dcagr': sl2['dcagr'], 'dmaxdd': sl2['dmaxdd']}
    gone = {Y: logs[Y]['内訳'].get('今はティッカーが無い（買収・倒産などで消えた社＝生き残りの偏り）', 0) for Y in logs}
    doc = {'generated': dt.date.today().isoformat(), 'tool': 'night/ccf15.py backtest',
           'prereg': 'out/ccf15_prereg.json（コミットは結果の前）', 'rules_version': R['version'],
           'window': [a, last], 'stats': st,
           'J1_選び方': {'verdict': sel_v, 'vs_same_pool': sel_ex},
           '検問の効き（参考）': kill_ex,
           'J2_ITAの代わり': {'verdict': slot_v, **slot},
           'CCF15と相手の差': vs, 'sensitivity': sens,
           '生き残りの偏り（消えた社の数・上位1000社のうち）': gone, 'gaps': gaps,
           'growth': growth({'CCF15': rH, 'ITA': B['ITA'], 'SPY': B['SPY'], 'RSP': B['RSP'], 'QQQ': B['QQQ']}),
           'cohorts': logs}
    json.dump(doc, open(OUT_BT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'J1': sel_v, 'J1_ex': sel_ex, 'J2': slot_v, 'dcagr': slot['dcagr'], 'dmaxdd': slot['dmaxdd'],
                      'CCF15': st['CCF15'], 'ITA': st['ITA'], 'SPY': st['SPY']}, ensure_ascii=False, indent=1))


# ───────────────────────── 今日の中身 ─────────────────────────
def holdings():
    R = rules()
    ctx = Ctx(fetch=True)
    today = dt.date.today()
    Y = today.year if today >= dt.date(today.year, 7, 1) else today.year - 1
    spy = (ctx.px('SPY', True) or {}).get('m') or {}
    now = max(spy)                                   # いちばん新しい月（今月の途中の足）＝今も売買されている社だけを選ぶ
    co = cohort(ctx, Y, R, px_key=now, fetch=True)
    rows, skipped = [], co['log'].get('その月の株価が無い', 0)          # 今は売買されていない社（選ぶ前に外した数）
    order = sorted(co['comp'], key=lambda c: (-co['comp'][c], -co['fl'].get(c, 0)))
    D = co['D']
    for i, c in enumerate(co['H']):
        f = ctx.F[c][D]
        rs = [ctx.F[c][y]['roic_used'] for y in range(D - 4, D + 1) if y in ctx.F[c] and ctx.F[c][y]['roic_used'] is not None]
        rows.append({'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'cik': c, 'sic': ctx.SIC[c], 'sector': sector_ja(ctx.SIC[c]),
                     'w': round(1 / len(co['H']), 6), 'rank': i + 1, 'score': round(co['comp'][c], 4),
                     'gpa': None if f['gpa'] is None else round(f['gpa'], 3), 'cfoa': None if f['cfoa'] is None else round(f['cfoa'], 3),
                     'dsh3': None if c not in co['met']['dsh'] else round(co['met']['dsh'][c] * 100, 1),
                     'roic5': round(S.median(rs), 1) if rs else None,
                     'nde': None if f['nde'] is None else round(f['nde'], 2), 'icov': None if f['icov'] is None else round(f['icov'], 1),
                     'float_b': round(co['fl'][c] / 1e9, 1)})
    nxt = [{'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'sector': sector_ja(ctx.SIC[c]), 'score': round(co['comp'][c], 4)}
           for c in order if c not in co['H']][:25]
    by_sector = {}
    for r in rows:
        by_sector[r['sector']] = by_sector.get(r['sector'], 0) + 1
    doc = {'name': R['name'], 'ja': R['ja'], 'version': R['version'], 'rules': 'out/ccf15_rules.json',
           'generated': today.isoformat(), 'cohort': f'{Y}年7月の組', 'data_year': D,
           'counts': {'母集団（公開浮動株時価の上位）': len(co['ranked']), '金融・テックを除いた': len(co['U0']),
                      '壊れないの検問を通った': len(co['E']), '選んだ': len(co['H'])},
           '外した理由': co['log'], 'by_sector': dict(sorted(by_sector.items(), key=lambda kv: -kv[1])),
           'holdings': rows, '次の候補（選ばれなかった上位）': nxt, '今の株価が無くて外した社の数': skipped}
    json.dump(doc, open(OUT_HOLD, 'w'), ensure_ascii=False, indent=1)
    print(f"{len(rows)} 社（{doc['cohort']}・{D}年の決算）")
    for r in rows:
        print(f"  {r['rank']:3d} {r['t']:6s} {r['sector']:10s} gpa {r['gpa']} cfoa {r['cfoa']} 株数3年 {r['dsh3']}% ROIC5 {r['roic5']} {r['nm'][:40]}")


# ───────────────────────── 紙の上の値動き（立ち上げ日から） ─────────────────────────
def _d8(s):
    return int(s.replace('-', ''))


def _ds(d):
    return f'{d // 10000:04d}-{d // 100 % 100:02d}-{d % 100:02d}'


def nav(today=None):
    """立ち上げ日の中身を同じ重みで持ったまま、毎営業日の終値で値をつける（配当込み・手数料・為替・税は引かない）。
    7月の入れ替えで中身（out/ccf15.json の cohort）が変わったら、新しい『期』を足して前の期の値につなぐ
    （期の境目の日は前の期の終値で閉じ、同じ日の終値から新しい中身で始める）"""
    R = rules()
    H = json.load(open(OUT_HOLD, encoding='utf-8'))
    old = json.load(open(OUT_NAV, encoding='utf-8')) if os.path.exists(OUT_NAV) else {}
    periods = old.get('periods') or []
    names_now = [r['t'] for r in H['holdings']]
    if not periods:
        periods = [{'from': R['launch'], 'cohort': H['cohort'], 'holdings': names_now}]
    elif periods[-1]['cohort'] != H['cohort']:
        periods.append({'from': None, 'cohort': H['cohort'], 'holdings': names_now})   # 境目の日は下で決める
    bench = ['ITA', 'SPY', 'QQQ', 'RSP']
    allt = sorted({t for p in periods for t in p['holdings']} | set(bench))
    px = {t: yahoo_d(t, R['launch']) for t in allt}
    days = sorted({d for t in allt if px.get(t) for d in px[t] if d >= _d8(R['launch'])})
    if today:
        days = [d for d in days if d <= today]
    if periods[-1]['from'] is None:
        if not days:
            print('入れ替えの境目の日が決まらない（終値が無い）')
            return
        periods[-1]['from'] = _ds(days[-1])

    def base_of(p):
        d0 = _d8(p['from'])
        for d in days:
            if d >= d0 and sum(1 for t in p['holdings'] if px.get(t) and d in px[t]) >= 0.95 * len(p['holdings']):
                return d
        return None
    lastp, rows, level = {}, [], 10000.0
    bases = [base_of(p) for p in periods]
    if bases[0] is None:
        print('まだ立ち上げ日の終値がそろっていない（米国の取引が終わったあとに回す）')
        return
    for i, p in enumerate(periods):
        b = bases[i]
        if b is None:
            break
        nxt = bases[i + 1] if i + 1 < len(bases) and bases[i + 1] is not None else None
        ref = {t: px[t][b] for t in p['holdings'] if px.get(t) and b in px[t]}
        p['base_day'], p['n'], p['missing'] = _ds(b), len(ref), [t for t in p['holdings'] if t not in ref]
        p['level_at_base'] = round(level, 2)
        start_level = level
        for d in [x for x in days if x >= b and (nxt is None or x <= nxt)]:
            for t in allt:
                if px.get(t) and d in px[t]:
                    lastp[t] = px[t][d]
            v = sum(lastp.get(t, ref[t]) / ref[t] for t in ref) / len(ref)
            level = start_level * v
            if rows and rows[-1]['d'] == _ds(d):
                continue        # 境目の日は前の期の終値で閉じたので重ねない
            rows.append({'d': _ds(d), 'nav': round(level, 2)})
    b0 = bases[0]
    for row in rows:
        d = _d8(row['d'])
        for t in bench:
            s = px.get(t) or {}
            if b0 in s:
                pv = max((x for x in s if x <= d), default=None)
                if pv is not None:
                    row[t] = round(10000 * s[pv] / s[b0], 2)
    doc = {'name': R['name'], 'launch': R['launch'], 'base_day': _ds(b0), 'start': 10000, 'periods': periods,
           'note': '紙の上の値動き（配当込みの終値で、期のはじめの中身を同じ重みで持ったまま）。手数料・為替・税は引いていない。7月の入れ替えで期が変わる',
           'generated': dt.date.today().isoformat(), 'series': rows}
    json.dump(doc, open(OUT_NAV, 'w'), ensure_ascii=False, indent=1)
    last = rows[-1]
    print(f"{last['d']}: CCF15 {last['nav']} / ITA {last.get('ITA')} / SPY {last.get('SPY')} / QQQ {last.get('QQQ')}（{rows[0]['d']}＝10,000）")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'fetch':
        R = rules()
        tickers(True)
        fetch_frames()
        ctx = Ctx(fetch=True)
        prefetch_prices(ctx, R)
    elif cmd == 'census':
        R = rules()
        ctx = Ctx(fetch=False)
        for Y in COHORTS:
            co = cohort(ctx, Y, R)
            print(Y, '上位', len(co['ranked']), '土俵', len(co['U0']), '検問を通った', len(co['E']), '選んだ', len(co['H']))
    elif cmd == 'holdings':
        holdings()
    elif cmd == 'backtest':
        backtest()
    elif cmd == 'nav':
        nav()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
