#!/usr/bin/env python3
"""night/ccf15.py — CCF15: 私（Claude）が中身を決めて運営する「15%の枠のETF」（読むだけ・門の判定に不使用）

ユーザー指示（2026-10-12）「あなた自身が作るETFが欲しい」→「moomoo証券を使った細かいポートフォリオ」→
「15％を細かくあなた自身が作るETFだよ？あなた自身運営するETFだよ？銘柄数は多くても構わない。」→（v2）
「中身の決め方はすべての銘柄対象であなたが出せる最高のETFそして見直し基準にして。」→（v3）
「ではなくリスクをとってNASDAQ超えを狙うETFにして」「もちろん質の高さは残して」

役目（規則の正本は out/ccf15_rules.json。ここに数字を写さない）:
  v3: 米国の金融を除く浮動株上位1000社から、門の検問を通った（壊れない）会社のうち、質の総合と勢い（12-1か月）の両方が
  上位半分の社を時価の大きい順に30社・時価の重み・1社10%まで持つ。NASDAQ100（QQQ）に勝つことを狙い、ぶれと下落が大きいことを受け入れる。
  上乗せは約束しない——このリポジトリの検証で、2009年以降に NASDAQ100 に勝った規則は見つかっていない（docs/CLAUDE_ARCHIVE.md の nx）。
  v1（テックの外・同じ重み・75社）は out/ccf15_rules_v1.json と holdings_v1・backtest_v1、
  v2（全銘柄・時価×質の傾き・100社）は out/ccf15_rules_v2.json と holdings_v2・backtest_v2 で再現できる。

使い方:
  python3 night/ccf15.py fetch       # SEC frames・業種・株価をキャッシュへ（out/_ccf15_cache・gitignore）
  python3 night/ccf15.py census      # 母集団の形（v1 の作り方の数）だけを見る（株価のリターンは見ない）
  python3 night/ccf15.py holdings    # 今日の中身（今年7月の組＝会社ごとに6月末に出ていた決算）→ out/ccf15.json（規則の method で v1／v2／v3）
  python3 night/ccf15.py backtest    # 事前登録どおりの過去の検証 → out/ccf15_backtest.json（v3: out/ccf15_prereg_v3.json）
  python3 night/ccf15.py backtest_v2 # v2 の検証の再現 → out/ccf15_backtest_v2.json（holdings_v2 は今日の中身を v2 の作り方で出すだけ）
  python3 night/ccf15.py backtest_v1 # v1（テックの外・同じ重み・out/ccf15_prereg.json）の検証の再現 → out/ccf15_backtest_v1.json
  python3 night/ccf15.py nav         # 紙の上の値動き（立ち上げ日から・日次）→ out/ccf15_nav.json

約束（このリポジトリの絶対のルール7・8に従う）:
  - タグが無いことを0と読まない。測れない値は None（＝その項目は使わない／測れない理由で外す）。
  - 投下資本が自己資本の2割を切ったら ROIC は算出不能（門の規約7-b）。そのときは のれん込み（roicg）へ落ちる（門の ccfRoicJudge と同じ順）。
  - 株価は Yahoo の月足 adjclose（配当込み）でリターン、分割だけ戻した close で時価。今ティッカーがある社だけ＝生き残りの偏り
    （倒産・買収で消えた社は入らない。持株会社への組み替えで番号が変わった社は SUCCESSORS で今のティッカーへつなぐ）。
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
OUT_BT1 = os.path.join(BASE, 'out', 'ccf15_backtest_v1.json')     # v1（テックの外・同じ重み）の検証の記録
RULES_V1 = os.path.join(BASE, 'out', 'ccf15_rules_v1.json')        # v1 の規則書（事前登録 23d1aed の sha256 と同じ中身）
RULES_V2 = os.path.join(BASE, 'out', 'ccf15_rules_v2.json')        # v2 の規則書（事前登録 dfcd740・結果の後の文言の直しを含む＝選び方は同じ）
OUT_BT2 = os.path.join(BASE, 'out', 'ccf15_backtest_v2.json')     # v2（全銘柄・時価×質の傾き・100社）の検証の記録
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
       'CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold',
       'ResearchAndDevelopmentExpense', 'SellingGeneralAndAdministrativeExpense',
       'GeneralAndAdministrativeExpense', 'SellingAndMarketingExpense',
       'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic']
NI = ['NetIncomeLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic', 'ProfitLoss']   # 代替（先に当たった一つ。実測: PNC・Truist・AMT・旧 Cigna）
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


def sec_names(ciks, fetch=True):
    """SEC submissions の社名・旧社名・最後の届け出（ティッカーの無い社を名指しするため）。CACHE/sub_names.json に貯める"""
    fn = os.path.join(CACHE, 'sub_names.json')
    sn = json.load(open(fn)) if os.path.exists(fn) else {}
    miss = [c for c in ciks if str(c) not in sn]
    if fetch and miss:
        def one(c):
            j = sec_json(f'https://data.sec.gov/submissions/CIK{c:010d}.json') or {}
            rec = j.get('filings', {}).get('recent', {})
            return c, {'name': j.get('name', ''), 'tickers': j.get('tickers', []), 'former': [f.get('name') for f in j.get('formerNames', [])],
                       'last': (rec.get('filingDate') or [''])[0], 'last_forms': (rec.get('form') or [])[:3], 'sic': j.get('sic', '')}
        with ThreadPoolExecutor(4) as ex:
            for c, v in ex.map(one, miss):
                sn[str(c)] = v
        os.makedirs(CACHE, exist_ok=True)
        json.dump(sn, open(fn, 'w'))
    return {c: sn.get(str(c)) for c in ciks}


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
    """月足。m＝adjclose（配当込み・リターンに使う）／c＝close（分割だけ戻した終値・時価に使う）と株式分割（[(yyyymmdd, 倍率)]）。
    取れなければ None。c の無い古いキャッシュは fetch なら取り直す（取らないなら c を持たないまま返す＝呼び出し側が m で代える）"""
    fn = os.path.join(CACHE, 'px', f'{sym}.json')
    if os.path.exists(fn):
        j = json.load(open(fn))
        if j is None:
            return None
        if 'c' in j or not fetch:
            return {'m': {int(k): v for k, v in j['m'].items()}, 'c': {int(k): v for k, v in (j.get('c') or {}).items()},
                    'splits': j['splits'], 'ccy': j.get('ccy')}
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
        close = ind['quote'][0].get('close') or []
        ser = (ind.get('adjclose') or [{}])[0].get('adjclose') or close
        gmt = (res.get('meta') or {}).get('gmtoffset') or 0
        m, c = {}, {}
        for i, t in enumerate(res['timestamp']):
            d = dt.datetime.utcfromtimestamp(t + gmt)
            k = f'{d.year:04d}-{d.month:02d}'
            if i < len(ser) and ser[i] is not None:
                m[k] = float(ser[i])
            if i < len(close) and close[i] is not None:
                c[k] = float(close[i])
        m = PXG.vet(sym, m, 'ccf15.yahoo_m', req_start=t0, record=False) or {}
        c = {k: v for k, v in c.items() if k in m}
        sp = []
        for e in ((res.get('events') or {}).get('splits') or {}).values():
            if e.get('numerator') and e.get('denominator'):
                d = dt.datetime.utcfromtimestamp(e['date'])
                sp.append([d.year * 10000 + d.month * 100 + d.day, e['numerator'] / e['denominator']])
        if m:
            out = {'m': {int(k[:4]) * 100 + int(k[5:]): v for k, v in m.items()},
                   'c': {int(k[:4]) * 100 + int(k[5:]): v for k, v in c.items()},
                   'splits': sorted(sp), 'ccy': (res.get('meta') or {}).get('currency')}
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    tmp = fn + '.tmp'
    json.dump(None if out is None else {'m': {str(k): v for k, v in out['m'].items()}, 'c': {str(k): v for k, v in out['c'].items()},
                                        'splits': out['splits'], 'ccy': out['ccy']}, open(tmp, 'w'))
    os.replace(tmp, fn)
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


# 番号（CIK）が変わった会社: 持株会社への組み替え・本社の国の移転で、同じ株（1株＝1株）が今のティッカーで続いている社だけ。
# 古い番号の決算と浮動株を今の番号へつなぐ。つながないと古い番号の年は『今はティッカーが無い』で母集団から消える
# （実測: Exxon は2026年に持株会社へ移って全年が抜けていた・Alphabet 2013〜2015・Disney 2013〜2019・BlackRock 2013〜2024・
#  Cigna 2013〜2018・Praxair(Linde) 2013〜2018・Avago(Broadcom) 2013〜2018・Medtronic 2013〜2015）。
# 決め方: SEC の社名・旧社名で組み替えと確かめ、かつ 古い番号の浮動株 ÷（株数×今のティッカーの株価）が年をまたいで
# 滑らかに 0.3〜3倍に収まる（配当込みの株価なので古い年ほど少し大きく出る）。
# つながない: 合併で相手の株になった社（Chubb Corp→ACE・Broadcom Corp→Avago・Cooper Industries→Eaton）、
# 今のティッカーの株価の履歴が別の会社のもの（JCI＝Tyco の履歴・KHC は2015年7月から）、交換が1株＝1株でない社
SUCCESSORS = {
    34088: 2115436,     # Exxon Mobil Corp → ExxonMobil Holdings（XOM）
    1288776: 1652044,   # Google Inc → Alphabet（GOOGL・2015）
    1001039: 1744489,   # Walt Disney（旧・今は TWDC Enterprises 18）→ Walt Disney（DIS・2019）
    64670: 1613103,     # Medtronic Inc → Medtronic plc（MDT・2015）
    1364742: 2012383,   # BlackRock（旧・今は BlackRock Finance）→ BlackRock（BLK・2024）
    701221: 1739940,    # Cigna Corp（旧・今は Cigna Holding）→ Cigna Group（CI・2018）
    1441634: 1730168,   # Avago Technologies → Broadcom Ltd（2016）→ Broadcom Inc（AVGO・2018）
    1649338: 1730168,
    6769: 1841666,      # Apache Corp → APA Corp（APA・2021）
    884905: 1707925,    # Praxair（今は Linde Inc）→ Linde plc（LIN・2018）
    108772: 1770450,    # Xerox Corp → Xerox Holdings（XRX・2019）
    1058057: 1835632,   # Marvell Technology Group → Marvell Technology Inc（MRVL・2021）
    1144519: 1996862,   # Bunge Ltd → Bunge Global（BG・2023）
    820096: 1585364,    # Perrigo Co → Perrigo plc（PRGO・2013）
    1174746: 1571949,   # IntercontinentalExchange Inc → ICE Group（ICE・2013）
    1772757: 1883685,   # DraftKings Holdings → DraftKings Inc（DKNG・2022）
    1832433: 2011641,   # Ferguson plc → Ferguson Enterprises（FERG・2024）
    815065: 1757898,    # STERIS Corp → STERIS plc（英国 2015）→ STERIS plc（アイルランド・STE・2019）
    1624899: 1757898,
    92416: 1692115,     # Southwest Gas Corp → Southwest Gas Holdings（SWX・2017）
    73088: 1993004,     # NorthWestern Corp → NorthWestern Energy Group（NWE・2023）
    912752: 1971213,    # Sinclair Broadcast Group → Sinclair Inc（SBGI・2023）
    31277: 1551182,     # Eaton Corp → Eaton plc（ETN・2012）
    69499: 1792044,     # Mylan Inc → Mylan NV（2015）→ Viatris（VTRS・2020）
    1623613: 1792044,
    808362: 1701605,    # Baker Hughes Inc → BHGE（2017・1株＋現金の配当）→ Baker Hughes Co（BKR）
}


def merge_successors(P):
    """古い番号の決算を今の番号へ寄せる（同じ年は タグごとに 今の番号の値が先・無いタグだけ古い番号の値で埋める）。古い番号は消す"""
    for new in sorted(set(SUCCESSORS.values())):
        olds = sorted((o for o, n in SUCCESSORS.items() if n == new), key=lambda o: max(P.get(o) or {0: None}))
        merged = {}
        for o in olds:
            for y, d in (P.pop(o, None) or {}).items():
                merged.setdefault(y, {}).update(d)
        for y, d in (P.get(new) or {}).items():
            merged.setdefault(y, {}).update(d)
        if merged:
            P[new] = merged
    return P


def load_panel():
    P = {}      # cik -> 年 -> {タグ: 値, '_end': 会計年度の終わり}
    for y in YEARS:
        for t in DUR:
            for cik, v, st, en, accn in frame_cached('us-gaap', t, 'USD', f'CY{y}'):
                d = P.setdefault(cik, {}).setdefault(y, {})
                d[t] = v
                if t == 'OperatingIncomeLoss' and en:
                    d['_end'] = en
                elif en and '_end_any' not in d:
                    d['_end_any'] = en
        for cik, v, st, en, accn in frame_cached('us-gaap', SHARES, 'shares', f'CY{y}'):
            d = P.setdefault(cik, {}).setdefault(y, {})
            d['_sh'], d['_sh_end'], d['_sh_accn'] = v, en, accn
        for t in INS:
            for cik, v, st, en, accn in frame_cached('us-gaap', t, 'USD', f'CY{y}Q4I'):
                P.setdefault(cik, {}).setdefault(y, {})[t] = v
    return merge_successors(P)


def op_income_derived(d):
    """営業利益のタグ（OperatingIncomeLoss）を出していない会社（LLY・JNJ・PFE・MRK など）の代わりの道。
    (1) 粗利 − 研究開発費 − 販管費（gate0_v8_5.derive_opinc と同じ組み立て。販管費は 一般管理費＋販売費 でもよい）
    (2) 税引前利益 ＋ 支払利息（営業外の損益を含む近い値。石油など粗利を出さない会社）
    (3) 税引前利益だけ（支払利息のタグも無い会社。利息のぶん低く出る＝検問に厳しい側）
    どれも無ければ None（測れない）"""
    gp = d.get('GrossProfit')
    if gp is None:
        rev, cg = first(d, REV), first(d, COGS)
        gp = (rev - cg) if (rev is not None and cg is not None) else None
    sga = d.get('SellingGeneralAndAdministrativeExpense')
    if sga is None and d.get('GeneralAndAdministrativeExpense') is not None and d.get('SellingAndMarketingExpense') is not None:
        sga = d['GeneralAndAdministrativeExpense'] + d['SellingAndMarketingExpense']
    if gp is not None and sga is not None:
        return gp - (d.get('ResearchAndDevelopmentExpense') or 0) - sga, 'derived_gp'
    pre = first(d, PRETAX)
    ie = first(d, INTEREST)
    if pre is not None and ie is not None:
        return pre + ie, 'derived_ebit'
    if pre is not None:
        return pre, 'derived_pretax'      # 支払利息のタグが無い（GE・Newmont・PACCAR など）: 税引前利益で代える＝低く出る側
    return None, None


def no_debt_plausible(d, A):
    """借金のタグが一つも無いとき、借金0と読んでよいか。支払利息のタグが無いか、あっても総資産の0.2%以下なら借金は無いと読む。
    利息を払っているのにタグが無い会社は『測れない』のまま（0と読むと投下資本が縮んで ROIC が発散する＝ルール7）"""
    ie = first(d, INTEREST)
    return ie is None or (A > 0 and ie <= 0.002 * A)


def features(P):
    F = {}
    for cik, ys in P.items():
        out = {}
        for y, d in ys.items():
            oi, op_src = d.get('OperatingIncomeLoss'), 'reported'
            if oi is None:
                oi, op_src = op_income_derived(d)
            eq = first(d, EQ)
            A, L = d.get('Assets'), d.get('Liabilities')
            eq_fix = False
            if eq is not None and eq <= 0 and A and L is not None and (A - L) > 0.05 * A:
                eq, eq_fix = A - L, True      # 提出の XBRL の符号の誤り（gaps_sell.identity_fix と同じ・例 TDY 2014）
            pre = first(d, PRETAX)
            tax = d.get('IncomeTaxExpenseBenefit')
            t = min(0.5, max(0.0, tax / pre)) if (pre and pre > 0 and tax is not None) else (0.35 if y <= 2017 else 0.21)
            debt = debt_of(d)
            debt_src = 'tags'
            if debt is None and A and no_debt_plausible(d, A):
                debt, debt_src = 0.0, 'none'     # 借金のタグが一つも無く、支払利息も無い（総資産の0.2%以下）＝借金の無い会社（AAPL 2012・META 2017 など）
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
                          sh=d.get('_sh'), sh_end=d.get('_sh_end'), sh_accn=d.get('_sh_accn'),
                          end=d.get('_end') or d.get('_end_any'), ni=first(d, NI),
                          assets=A, classified=d.get('AssetsCurrent') is not None,
                          op_src=op_src if oi is not None else None, debt_src=debt_src if debt is not None else None)
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
FLOAT_FIX = {'hi': 200.0, 'hi_unclassified': 5.0, 'lo': 0.0005}   # 浮動株÷総資産 がこの外なら 1000倍ずつ直す（最大2回）


def fix_float(v, assets, classified=True):
    """10-K の表紙の浮動株時価は、提出の XBRL で単位が1000倍・100万倍ずれていることがある
    （実測: Advance Auto Parts 2012 が 4.1兆ドル・Cabot 2025 が 4,429兆ドル・Enova・Champion Homes・Novanta・CoreCivic・Fresenius が1000倍）。
    総資産と比べて、浮動株÷総資産 が上の線を超えれば1000で割り、0.0005 を下回れば1000を掛ける（最大2回）。
    上の線は、流動資産を出す会社（ふつうの事業会社）で 200、出さない会社（銀行・保険など＝総資産が大きく時価は総資産を超えにくい）で 5
    （実測: German American Bancorp・Great Southern・Trustmark の1000倍の誤りは 200 の線では素通りした）。
    直しても帯の外なら None（測れない）。総資産が無ければ確かめられないので None"""
    if not assets or assets <= 0 or not v or v <= 0:
        return None, None
    hi = FLOAT_FIX['hi'] if classified else FLOAT_FIX['hi_unclassified']
    n = 0
    while v / assets > hi and n < 2:
        v, n = v / 1000, n + 1
    while v / assets < FLOAT_FIX['lo'] and n > -2:
        v, n = v * 1000, n - 1
    if not (FLOAT_FIX['lo'] <= v / assets <= hi):
        return None, n
    return v, n


def float_table(F=None):
    """浮動株時価の表（cik → {日付: 値}）。F（決算の表）を渡すと、総資産と比べて単位の誤りを直し、確かめられない値は捨てる"""
    FL, fixed, dropped = {}, 0, 0
    by_old = set()      # 番号が変わった会社: 同じ日付の値が両方にあれば、その時に出された古い番号の値を採る
    for y in FLOAT_YEARS:
        for q in (1, 2, 3, 4):
            fn = os.path.join(CACHE, 'frames', f'dei_EntityPublicFloat_USD_CY{y}Q{q}I.json')
            if not os.path.exists(fn):
                continue
            for cik0, v, st, en, accn in json.load(open(fn)):
                if not (en and v and v > 0):
                    continue
                cik = SUCCESSORS.get(cik0, cik0)
                if cik0 == cik and (cik, en) in by_old:
                    continue
                if F is not None:
                    ys = F.get(cik) or {}
                    fy = [yy for yy in ys if ys[yy].get('assets') and yy <= int(en[:4])]
                    a = ys[max(fy)]['assets'] if fy else None
                    v2, n = fix_float(v, a, ys[max(fy)].get('classified', True) if fy else True)
                    if v2 is None:
                        dropped += 1
                        continue
                    fixed += (n != 0)
                    v = v2
                FL.setdefault(cik, {})[en] = v
                if cik0 != cik:
                    by_old.add((cik, en))
    float_table.stats = {'単位を直した': fixed, '確かめられず捨てた': dropped}
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


def universe2(FL, asof, top):
    """universe と同じ窓・同じ順。値に加えて浮動株の日付も返す（株価の変化で今の時価へ直すため）"""
    lo, hi = add_months(asof, -30).isoformat(), add_months(asof, -12).isoformat()
    cand = {}
    for cik, ends in FL.items():
        es = [e for e in ends if lo <= e <= hi]
        if es:
            e = max(es)
            cand[cik] = (ends[e], e)
    return sorted(cand, key=lambda c: -cand[c][0])[:top], cand


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
        self.FL = float_table(self.F)
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
    need |= {'VOO', 'QUAL', 'SPHQ', 'SPMO'} | set(BENCH3)
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
           874: '経営・調査サービス',
           367: '半導体・電子部品', 366: '通信機器', 365: '音響・映像機器', 355: '特殊な産業機械（半導体装置など）', 737: 'ソフトウェア・ネット',
           602: '銀行', 603: '銀行', 609: '金融サービス', 611: '政府系の金融', 614: 'カード・消費者金融', 615: '事業向け金融',
           616: '住宅ローン', 619: 'カード・金融サービス', 620: '証券・取引所', 621: '証券会社', 622: '商品取引', 628: '資産運用・取引所',
           631: '生命保険', 632: '医療保険', 633: '損害保険', 635: '保証保険', 636: '権原保険', 637: '年金', 639: '保険', 641: '保険仲介',
           651: '不動産', 653: '不動産仲介', 655: '不動産開発', 671: '持株会社', 672: '投資会社', 679: 'REIT・投資'}
SIC2_JA = {60: '銀行', 61: '金融（貸金・カード）', 62: '証券・取引所', 63: '保険', 64: '保険仲介', 65: '不動産', 67: '持株・投資',
           1: '農業', 2: '農業', 10: '金属鉱業', 12: '石炭', 13: '石油・ガス', 14: '鉱物', 15: '建設', 16: '建設', 17: '設備工事',
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
    out = {'months': ks}
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


def backtest_v1():
    """v1（テックの外・同じ重み・事前登録 out/ccf15_prereg.json）の検証を、v1 の規則書のまま作り直す（記録の再現用）"""
    R = json.load(open(RULES_V1, encoding='utf-8'))
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
    json.dump(doc, open(OUT_BT1, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'J1': sel_v, 'J1_ex': sel_ex, 'J2': slot_v, 'dcagr': slot['dcagr'], 'dmaxdd': slot['dmaxdd'],
                      'CCF15': st['CCF15'], 'ITA': st['ITA'], 'SPY': st['SPY']}, ensure_ascii=False, indent=1))


# ───────────────────────── v2: 全銘柄・時価の重み・質で傾ける・1社の上限 ─────────────────────────
TECH_SIC = [(3570, 3579), (3661, 3679), (3559, 3559), (3825, 3825), (3827, 3827), (5065, 5065), (7370, 7379)]


def is_fin(sic):
    return sic is not None and 6000 <= sic <= 6799


def is_tech(sic):
    return sic is not None and any(lo <= sic <= hi for lo, hi in TECH_SIC)


def fin_kills(F, c, D, R):
    """金融（銀行・保険・不動産・証券・取引所など）は ROIC・純負債・Z'' が意味を持たない（借金や預かり金が原材料）。
    代わりに 金融以外と同じ形で: 直近の年が赤字なら外す（金融以外の『営業赤字』）・自己資本>0（『債務超過』）・
    直近 years 年の ROE（純利益÷自己資本）の中央値 > roe_min（『ROIC≦WACC』）。測れない（純利益が min_years 年分ない）社は外す"""
    k = R['kills_fin']
    f = F.get(c, {}).get(D)
    if not f or f.get('ni') is None:
        return ['決算が無い（測れない）']
    why = []
    if f['eq'] is None:
        why.append('自己資本が測れない')
    elif f['eq'] <= 0:
        why.append('債務超過')
    ys = [y for y in range(D - k['years'] + 1, D + 1) if y in F[c] and F[c][y].get('ni') is not None]
    if len(ys) < k['min_years']:
        why.append(f"純利益が{k['min_years']}年分ない（測れない）")
        return why
    if f['ni'] <= 0:
        why.append('赤字')
    roe = [F[c][y]['ni'] / F[c][y]['eq'] * 100 for y in ys if F[c][y].get('eq') and F[c][y]['eq'] > 0]
    if len(roe) < k['min_years']:
        why.append('ROEが測れない')
    elif S.median(roe) <= k['roe_min']:
        why.append(f"ROE中央値≤{k['roe_min']}%")
    return why


def cap_weights(w, cap):
    """比で配り、1社 cap を超えた分を残りの社へ比で配り直す（超える社が無くなるまで）。
    cap×社数<1（上限を守れない）なら上限を掛けない"""
    tot = sum(w.values())
    if tot <= 0:
        return {}
    w = {k: v / tot for k, v in w.items()}
    if not cap or cap * len(w) < 1:
        return w
    fixed = set()
    for _ in range(len(w) + 1):
        over = [k for k, v in w.items() if k not in fixed and v > cap + 1e-12]
        if not over:
            break
        fixed.update(over)
        free = [k for k in w if k not in fixed]
        rest = 1 - cap * len(fixed)
        fs = sum(w[k] for k in free)
        for k in fixed:
            w[k] = cap
        for k in free:
            w[k] = w[k] / fs * rest if fs > 0 else rest / len(free)
    return w


FLOAT_SHARES_MAX = 2e11   # 浮動株の株数（浮動株時価÷その月の株価）の上限。どの会社もこの1/8に届いたことがない（最大は NVDA・AAPL の約250億株）


def verify_float(ctx, c, val, end):
    """浮動株の桁の誤りの二つ目の検問（株価のある社だけ）。どちらかに当たれば1000で割る（最大2回）:
    (1) 浮動株÷その月の株価（分割を戻した値）＝浮動株の株数 が 2,000億株を超える。株数のタグを使わない
        （実測: Fannie Mae・Freddie Mac は毎年1000倍で届け出ていて、総資産が大きいので総資産の検問も素通りした）。
    (2) 浮動株が 株数（希薄化後の加重平均・その年）×株価 の50倍を超え、かつ 総資産と比べても大きすぎる
        （流動資産を出す会社で10倍・出さない会社〔銀行・保険・REIT〕で1倍超）。
        片方だけなら直さない——株数の側の誤り（実測: W.R. Berkley・Garmin・Repligen は株数を1000分の1で届けている）や
        配当込みの株価の歪み（実測: SITE Centers は分社の調整で配当込みの株価が実際の約1/70）でも比は大きく出るため。
    戻り値: (値, 直した回数)"""
    t = ctx.c2t.get(c)
    p = ctx.PX.get(t) if t else None
    ys = ctx.F.get(c) or {}
    if not p:
        return val, 0
    k0 = int(end[:4]) * 100 + int(end[5:7])
    m = p.get('c') or p['m']          # 分割だけ戻した終値（配当込みの値は古い年ほど小さく出る＝SITE Centers は約1/70）
    if k0 not in m or m[k0] <= 0:
        return val, 0
    split_after = math.prod(f for d8, f in (p.get('splits') or []) if d8 > k0 * 100 + 31)
    px0 = m[k0] * split_after
    n = 0
    while val / px0 > FLOAT_SHARES_MAX and n < 2:
        val, n = val / 1000, n + 1
    y0 = int(end[:4])
    yy = [y for y in (y0, y0 - 1, y0 + 1) if y in ys and ys[y].get('sh') and ys[y]['sh'] > 0]
    fa = [y for y in ys if ys[y].get('assets') and y <= y0]
    if not yy or not fa:
        return val, n
    implied = ys[yy[0]]['sh'] * px0
    a = ys[max(fa)]
    lim = 10.0 if a.get('classified', True) else 1.0
    while implied > 0 and val / implied > 50 and val / a['assets'] > lim and n < 2:
        val, n = val / 1000, n + 1
    return val, n


FILE_LAG_DAYS = 90     # 10-K は会計年度の終わりから60〜90日で出る。6月末の組は、4月1日までに終わった会計年度だけを使う


def decision_year(F, c, asof, Y):
    """asof（6月末）の時点で出ていた最新の年次決算の年（frames の暦年）。会計年度の終わりが asof の90日前より後の年は使わない
    （frames は6月決算の会計年度をその前の暦年に入れることがある＝そのままだと7月に出る決算を6月末の組で使ってしまう。
    実測: Seagate の2025年6月期は CY2024 に入る）。2年より古い年しか無ければ None（決算が止まっている）"""
    lim = (asof - dt.timedelta(days=FILE_LAG_DAYS)).isoformat()
    ys = F.get(c) or {}
    for y in (Y - 1, Y - 2):
        f = ys.get(y)
        if f and f.get('end') and f['end'] <= lim and (f.get('oi') is not None or f.get('ni') is not None):
            return y
    return None


def sh_basis_date(f):
    """株数（frames＝最後に出された値）がいつの分割までを戻した値か: その値を出した提出の年（accn の真ん中の2桁）と
    会計年度の終わりの月から、提出日をおよそ『会計年度の終わり＋60日』と置く。分からなければ None"""
    try:
        yy = 2000 + int((f.get('sh_accn') or '').split('-')[1])
    except (IndexError, ValueError):
        return None
    e = f.get('sh_end') or f.get('end')
    if not e:
        return None
    mo, dd = int(e[5:7]), min(int(e[8:10]), 28)
    for cy in (yy - 1, yy):
        d = dt.date(cy, mo, dd) + dt.timedelta(days=60)
        if d.year == yy:
            return d
    return dt.date(yy, 6, 30)


MV_RATIO = (0.15, 2.0, 50.0)   # 浮動株の時価 ÷ 全株の時価 の帯（下は親会社などが大半を持つ社・上は届け出の誤り・50超は株数の側の誤り）


def mv_value(ctx, c, asof, key, D):
    """時価（key の月の株価で）の推定。独立な二つの道を突き合わせる:
    E_fl＝浮動株（10-K の表紙・asof の12〜42か月前・新しい順に最大3つ・verify_float で桁を確かめる）× その日から key までの
         株価の変化（分割だけ戻した終値の比＝配当や分社で膨らまない）の中央値＝株価指数と同じ『浮動株の時価』。
    E_sh＝株数（D 年の希薄化後の加重平均）× key の終値 ×（その数字が出された後の分割）＝全株の時価。
    r＝E_fl÷E_sh が 0.15〜2 なら E_fl。2〜50 なら浮動株が全株より大きい＝届け出の誤りなので E_sh
    （実測: Seagate は2022年と2024年の届け出が全株の1.6倍・3.5倍）。50 超は株数の側の誤り（Berkshire は A 株換算の株数・
    株数を1000分の1で届ける社）なので E_fl。0.15 未満は親会社や政府が大半を持つ社＝買えるのは浮動株だけなので E_fl。
    片方しか無ければその値。戻り値: (時価, 道)。どちらも無ければ (None, None)"""
    p = ctx.PX.get(ctx.c2t.get(c)) or {}
    cl = p.get('c') or p.get('m') or {}
    if key not in cl or cl[key] <= 0:
        return None, None
    lo, hi = add_months(asof, -42).isoformat(), add_months(asof, -12).isoformat()
    obs = sorted(((e, v) for e, v in (ctx.FL.get(c) or {}).items() if lo <= e <= hi), reverse=True)[:3]
    fl = []
    for e, v in obs:
        v, _ = verify_float(ctx, c, v, e)
        k0 = int(e[:4]) * 100 + int(e[5:7])
        if k0 in cl and cl[k0] > 0:
            fl.append(v * cl[key] / cl[k0])
    e_fl = S.median(fl) if fl else None
    f = (ctx.F.get(c) or {}).get(D) if D is not None else None
    e_sh = None
    if f and f.get('sh') and f['sh'] > 0:
        b = sh_basis_date(f)
        mult = 1.0
        if b:
            b8 = b.year * 10000 + b.month * 100 + b.day
            mult = math.prod(x for d8, x in (p.get('splits') or []) if d8 > b8)
        e_sh = f['sh'] * cl[key] * mult
    lo_r, hi_r, broken = MV_RATIO
    if e_fl and e_sh:
        r = e_fl / e_sh
        if hi_r < r <= broken:
            return e_sh, 'sh'
        return e_fl, 'fl'
    if e_fl:
        return e_fl, 'fl_only'
    if e_sh:
        return e_sh, 'sh_only'
    return None, None


def quality_comp(ctx, elig, Dc, k):
    """質の総合: 粗利÷総資産・営業CF÷総資産・k['dsh_years'] 年の株数の変化（少ないほど上）の elig の中の順位の平均。
    物差しが k['min_metrics'] 個そろわない社は入れない（質を測れない）。Dc: 会社ごとの決算の年。戻り値: (総合, 物差しの生の値)"""
    met = {'gpa': {}, 'cfoa': {}, 'dsh': {}}
    for c in elig:
        D = Dc.get(c)
        f = (ctx.F.get(c) or {}).get(D) if D is not None else None
        if f is None:
            continue
        if f['gpa'] is not None:
            met['gpa'][c] = f['gpa']
        if f['cfoa'] is not None:
            met['cfoa'][c] = f['cfoa']
        d = dilution(ctx.F, c, D, ((ctx.PX.get(ctx.c2t[c]) or {}).get('splits')), k['dsh_years'])
        if d is not None:
            met['dsh'][c] = d
    rk = {'gpa': pct(met['gpa'], True), 'cfoa': pct(met['cfoa'], True), 'dsh': pct(met['dsh'], False)}
    comp = {}
    for c in elig:
        v = [rk[m][c] for m in k['metrics'] if c in rk[m]]
        if len(v) >= k['min_metrics']:
            comp[c] = sum(v) / len(v)
    return comp, met


def tilt_of(ctx, elig_nf, Dc, R):
    """質で傾ける（v2・金融を除く、検問を通った社の中で）: 質の総合（quality_comp）→ 三分位 → 倍率。
    物差しが min_metrics 個そろわない社は入れない（呼び出し側で1倍＝傾けない）。Dc: 会社ごとの決算の年"""
    comp, met = quality_comp(ctx, elig_nf, Dc, R['rank'])
    tl = R['tilt']
    order = sorted(comp, key=lambda c: (comp[c], c))
    n = len(order)
    tilt = {}
    for i, c in enumerate(order):
        q = i / n
        tilt[c] = tl['bottom'] if q < 1 / 3 else (tl['middle'] if q < 2 / 3 else tl['top'])
    return tilt, comp, met


def _pool_mv(ctx, Y, R, key, fetch):
    """Y 年7月の組の土俵（v2・v3 共通）: 浮動株の上位 → 業種・ティッカー・key の月の株価がある社 → 時価（mv_value）と決算の年（decision_year）"""
    asof = dt.date(Y, 6, 30)
    U, SL = R['universe'], R['select']
    ranked, fl = universe2(ctx.FL, asof, U['float_top'])
    ctx.need_sic(ranked, fetch)
    log = {}

    def note(k):
        log[k] = log.get(k, 0) + 1
    pool = []
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
        if not p or key not in p['m']:
            note('その月の株価が無い')
            continue
        pool.append(c)
    mv, scaled, Dc = {}, 0, {}
    for c in list(pool):
        Dc[c] = decision_year(ctx.F, c, asof, Y)
        if SL.get('scale', True):
            v, how = mv_value(ctx, c, asof, key, Dc[c])
            if v is None or v <= 0:
                pool.remove(c)
                note('時価が測れない（浮動株も株数も無い）')
                continue
            mv[c] = v
            scaled += how in ('fl', 'fl_only')
            if how == 'sh':
                note('時価: 浮動株の届け出が全株より大きすぎる→株数×株価')
            elif how == 'sh_only':
                note('時価: 浮動株が無い→株数×株価')
        else:
            mv[c] = fl[c][0]
    return asof, ranked, fl, pool, mv, Dc, scaled, log


def cohort_v2(ctx, Y, R, prev=None, px_key=None, fetch=False, prev_pool=None):
    """Y 年7月の組（6月末の時点で使える決算＝会社ごとに4月1日までに終わった最新の会計年度）。
    prev: 前の年の顔ぶれ（CIK）＝緩衝帯で残す候補。prev_pool: 比べる相手（同じ土俵の時価の重み）の前の年の顔ぶれ＝同じ緩衝帯"""
    D = Y - 1
    key = px_key or Y * 100 + 6
    SL = R['select']
    asof, ranked, fl, pool, mv, Dc, scaled, log = _pool_mv(ctx, Y, R, key, fetch)

    def note(k):
        log[k] = log.get(k, 0) + 1
    elig, why = [], {}
    for c in pool:
        if R['kills'].get('off'):
            w = []                                  # 感度『検問なし（傾きだけ）』
        elif Dc[c] is None:
            w = ['決算が無い（6月末に出ていた年次決算が無い・測れない）']
        else:
            w = fin_kills(ctx.F, c, Dc[c], R) if is_fin(ctx.SIC[c]) else kills(ctx.F, c, Dc[c], R)
        if w:
            why[c] = w
            note(f'外す: {w[0]}')
            continue
        elig.append(c)
    nf = [c for c in elig if not is_fin(ctx.SIC[c])]
    tilt, comp, met = tilt_of(ctx, nf, Dc, R)
    base = {c: mv[c] * tilt.get(c, 1.0) for c in elig}
    order = sorted(elig, key=lambda c: (-base[c], c))
    rank = {c: i + 1 for i, c in enumerate(order)}
    members = order[:SL['n']]
    kept = [c for c in (prev or []) if c in rank and rank[c] <= SL['buffer_rank'] and c not in members]
    members = members + kept
    if SL.get('weighting') == 'equal':
        w = {c: 1 / len(members) for c in members}
    else:
        w = cap_weights({c: base[c] for c in members}, SL['cap'])
    porder = sorted(pool, key=lambda c: (-mv[c], c))
    prank = {c: i + 1 for i, c in enumerate(porder)}
    pmem = porder[:SL['n']]
    pmem += [c for c in (prev_pool or []) if c in prank and prank[c] <= SL['buffer_rank'] and c not in pmem]
    pw = cap_weights({c: mv[c] for c in pmem}, SL['cap'])            # 同じ土俵の時価の重み（検問なし・傾けなし・同じ社数と緩衝帯と上限）
    return dict(Y=Y, D=D, Dc=Dc, key=key, ranked=ranked, fl=fl, pool=pool, elig=elig, members=members, kept=kept, w=w, pw=pw, pmem=pmem,
                tilt=tilt, comp=comp, met=met, mv=mv, base=base, rank=rank, why=why, log=log, scaled=scaled)


def basket_returns_w(ctx, by_year, last):
    """年ごとの重み {Y: {ティッカー: 重み}} で7月の頭に買い、翌年6月まで持ったまま（月の株価が欠けた社はその月 0%）。
    戻り値: 月次リターン・各年の終わりの重み（入れ替えの売買の量を出すため）・欠けた月の数"""
    out, ends, gaps = {}, {}, 0
    for Y in sorted(by_year):
        base = Y * 100 + 6
        W = {t: w for t, w in by_year[Y].items() if ctx.PX.get(t) and base in ctx.PX[t]['m'] and w > 0}
        tot = sum(W.values())
        if not W or tot <= 0:
            continue
        val = {t: w / tot for t, w in W.items()}
        lastp = {t: ctx.PX[t]['m'][base] for t in W}
        for i in range(1, 13):
            k = ym_add(base, i)
            if k > last:
                break
            rs = {}
            for t in W:
                p = ctx.PX[t]['m'].get(k)
                if p is None:
                    rs[t] = 0.0
                    gaps += 1
                else:
                    rs[t] = p / lastp[t] - 1
                    lastp[t] = p
            tv = sum(val.values())
            out[k] = sum(val[t] * rs[t] for t in W) / tv
            for t in W:
                val[t] *= 1 + rs[t]
        tv = sum(val.values())
        ends[Y] = {t: v / tv for t, v in val.items()}
    return out, ends, gaps


def turnover(by_year, ends):
    """入れ替えの売買の量（片道）＝0.5×Σ|新しい重み − 前の年の終わりの重み|。最初の年（立ち上げ）は数えない"""
    out = {}
    ys = sorted(by_year)
    for a, b in zip(ys, ys[1:]):
        if a not in ends:
            continue
        tot = sum(by_year[b].values())
        new = {t: w / tot for t, w in by_year[b].items()}
        old = ends[a]
        out[b] = round(0.5 * sum(abs(new.get(t, 0) - old.get(t, 0)) for t in set(old) | set(new)), 4)
    return out


def run_backtest_v2(ctx, R, last):
    H, P, logs, prev, prevP = {}, {}, {}, None, None
    for Y in COHORTS:
        if Y * 100 + 6 > last:
            break
        co = cohort_v2(ctx, Y, R, prev=prev, prev_pool=prevP)
        H[Y] = {ctx.c2t[c]: w for c, w in co['w'].items()}
        P[Y] = {ctx.c2t[c]: w for c, w in co['pw'].items()}
        prev, prevP = co['members'], co['pmem']
        top10 = sorted(co['w'].items(), key=lambda kv: -kv[1])[:10]
        logs[Y] = {'母集団（上位）': len(co['ranked']), '同じ土俵（生き残り）': len(co['pool']), '検問を通った': len(co['elig']),
                   '持つ': len(co['members']), '緩衝帯で残した': len(co['kept']),
                   'テックの比重': round(sum(w for c, w in co['w'].items() if is_tech(ctx.SIC[c])), 3),
                   '金融の比重': round(sum(w for c, w in co['w'].items() if is_fin(ctx.SIC[c])), 3),
                   '上位10社の比重': round(sum(w for _, w in top10), 3),
                   '上位10社': [ctx.c2t[c] for c, _ in top10], '内訳': co['log'], '時価を株価で直せた社': co['scaled']}
    rH, eH, gH = basket_returns_w(ctx, H, last)
    rP, eP, gP = basket_returns_w(ctx, P, last)
    return rH, rP, logs, {'H': gH, 'P': gP}, turnover(H, eH), turnover(P, eP)


def v1_returns():
    """v1 の検証の1ドルの推移から月次リターンを戻す（v1 と並べるため）"""
    if not os.path.exists(OUT_BT1):
        return {}
    g = json.load(open(OUT_BT1, encoding='utf-8')).get('growth') or {}
    ks, v = g.get('months') or [], g.get('CCF15') or []
    out, prev = {}, 1.0
    for k, x in zip(ks, v):
        out[k] = x / prev - 1
        prev = x
    return out


def backtest_v2():
    """v2（全銘柄・時価×質の傾き・100社・事前登録 out/ccf15_prereg_v2.json）の検証を、v2 の規則書のまま作り直す（記録の再現用）"""
    R = json.load(open(RULES_V2, encoding='utf-8'))
    PR = json.load(open(os.path.join(BASE, 'out', 'ccf15_prereg_v2.json'), encoding='utf-8'))
    ev = PR['evaluation']
    ctx = Ctx(fetch=False)
    spy = (ctx.px('SPY') or {}).get('m') or {}
    last = max(k for k in spy if k < int(dt.date.today().strftime('%Y%m')))
    a = COHORTS[0] * 100 + 7
    rH, rP, logs, gaps, toH, toP = run_backtest_v2(ctx, R, last)
    B = {t: etf_returns(ctx, t, a, last) for t in BENCH + ['VOO', 'QUAL', 'SPHQ']}
    q = B['QQQ']
    ser = {'CCF15': rH, '同じ土俵の時価の重み（検問なし）': rP, 'CCF15 v1（テックの外・同じ重み）': v1_returns()}
    ser.update({t: B[t] for t in ('SPY', 'QQQ', 'RSP', 'ITA', 'SMH', 'SPXT', 'QUAL', 'SPHQ')})
    st = {k: stats(v, q) for k, v in ser.items() if v}
    j1 = ev['J1']
    ex1 = MW.excess_stats(rH, rP)
    if ex1 and ex1['ex_ann'] >= j1['ex_ann'] and ex1['t'] is not None and ex1['t'] >= j1['t']:
        v1v = '規則に中身あり（同じ土俵の時価の重みに勝った）'
    elif ex1 and ex1['ex_ann'] <= -j1['ex_ann'] and ex1['t'] is not None and ex1['t'] <= -j1['t']:
        v1v = '規則で負けた（同じ土俵の時価の重みに負けた）'
    else:
        v1v = '差は偶然と区別できない'
    j2 = ev['J2']
    sH, sS = stats(rH, q), stats(B['SPY'], q)
    dg, dd = round(sH['cagr'] - sS['cagr'], 2), round(sH['maxdd'] - sS['maxdd'], 1)
    ex2 = MW.excess_stats(rH, B['SPY'])
    if ex2 and ex2['ex_ann'] >= j2['win_ex'] and ex2['t'] is not None and ex2['t'] >= j2['win_t'] and dd >= -j2['ddd_bad']:
        v2v = 'S&P500 に勝った'
    elif dg <= -j2['lose_dcagr'] or dd <= -j2['ddd_bad']:
        v2v = 'S&P500 より悪い'
    else:
        v2v = 'S&P500 並み'
    slot, slot_v = judge_slot(rH, B['ITA'], q, B['SMH'], ev['J3_slot'], ev['J3_slot']['dca_months'])
    vs = {t: MW.excess_stats(rH, B[t]) for t in ('SPY', 'QQQ', 'RSP', 'ITA', 'QUAL', 'SPHQ')}
    sens = {}
    for name, kw in ev['sensitivity'].items():
        R2 = variant(R, **kw)
        h2, p2, _, _, t2, _ = run_backtest_v2(ctx, R2, last)
        e2 = MW.excess_stats(h2, rP)
        s2 = stats(h2, q)
        sens[name] = {'stats': s2, 'vs_same_pool': e2, 'vs_spy_cagr': round(s2['cagr'] - sS['cagr'], 2),
                      'vs_spy_maxdd': round(s2['maxdd'] - sS['maxdd'], 1),
                      'turnover_mean': round(S.mean(t2.values()), 3) if t2 else None}
    gone = {Y: logs[Y]['内訳'].get('今はティッカーが無い（買収・倒産などで消えた社＝生き残りの偏り）', 0) for Y in logs}
    doc = {'generated': dt.date.today().isoformat(), 'tool': 'night/ccf15.py backtest', 'method': 'v2',
           'prereg': 'out/ccf15_prereg_v2.json（コミットは結果の前）', 'rules_version': R['version'],
           'window': [a, last], 'stats': st,
           'J1_規則の効き': {'verdict': v1v, 'vs_same_pool': ex1},
           'J2_SP500と比べて': {'verdict': v2v, 'dcagr': dg, 'dmaxdd': dd, 'excess': vs['SPY']},
           '参考_その他15%でITAの代わり': {'verdict': slot_v, **slot},
           'CCF15と相手の差': vs, 'turnover': toH, 'turnover_same_pool': toP,
           'turnover_mean': round(S.mean(toH.values()), 3) if toH else None,
           'sensitivity': sens, '生き残りの偏り（消えた社の数・上位1000社のうち）': gone, 'gaps': gaps,
           'growth': growth({'CCF15': rH, 'SPY': B['SPY'], 'QQQ': B['QQQ'], 'ITA': B['ITA'], 'RSP': B['RSP']}),
           'cohorts': logs}
    json.dump(doc, open(OUT_BT2, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'J1': v1v, 'J1_ex': ex1, 'J2': v2v, 'dcagr': dg, 'dmaxdd': dd, 'turnover_mean': doc['turnover_mean'],
                      'CCF15': st['CCF15'], 'SPY': st['SPY'], 'QQQ': st['QQQ']}, ensure_ascii=False, indent=1))


# ───────────────────────── v3: 質を残して、いま勝っている大型株へ集中（NASDAQ100 超えを狙う） ─────────────────────────
BENCH3 = ['QQQ', 'SPY', 'SMH', 'MTUM', 'MGK', 'QUAL', 'SPHQ', 'RSP', 'ITA']   # MTUM＝米国の勢い（2013-04〜）・MGK＝米国の巨大成長株
PREREG_V3 = os.path.join(BASE, 'out', 'ccf15_prereg_v3.json')
TAX_JP = 0.20315          # 特定口座の売却益の税（所得税15.315%＋住民税5%）


def momentum(ctx, c, key, months=12, skip=1):
    """勢い: key の月（7月の組なら6月）の skip か月前の終値 ÷ months か月前の終値 − 1（配当込みの adjclose）。
    12-1 なら前の年の6月末 → その年の5月末。どちらかの月の値が無ければ None（測れない・上場から1年未満など）"""
    p = (ctx.PX.get(ctx.c2t.get(c)) or {}).get('m') or {}
    k1, k0 = ym_add(key, -skip), ym_add(key, -months)
    if k1 in p and k0 in p and p[k0] > 0:
        return p[k1] / p[k0] - 1
    return None


def top_set(vals, frac):
    """vals（会社→値・大きいほど上）の上位 frac に入る社の集合（同点は平均の順位）。frac が無いか1以上なら線なし＝None"""
    if frac is None or frac >= 1:
        return None
    p = pct(vals, True)
    return {c for c, v in p.items() if v >= 1 - frac - 1e-9}


def weights_v3(members, mv, SL):
    """時価の比（1社 cap まで）。感度で 同じ重み（equal）・時価の平方根（sqrt）"""
    if not members:
        return {}
    if SL.get('weighting') == 'equal':
        return {c: 1 / len(members) for c in members}
    if SL.get('weighting') == 'sqrt':
        return cap_weights({c: math.sqrt(mv[c]) for c in members}, SL['cap'])
    return cap_weights({c: mv[c] for c in members}, SL['cap'])


def substantive(ws):
    """検問の理由のうち、測った結果として落ちた（壊れた）もの。『測れない』だけなら壊れたとは読まない（ルール7）"""
    return [w for w in (ws or []) if '測れない' not in w]


def cohort_v3(ctx, Y, R, prev=None, px_key=None, fetch=False, prev_pool=None):
    """Y 年7月の組（v3）。土俵と時価は v2 と同じ（_pool_mv）。検問 → 質の総合と勢い（どちらも検問を通った社の中の順位）→
    入る＝両方が上位 enter_top で、時価の上位 n 社／残る＝前の年から持っている社で、両方が上位 stay_top、
    時価の順位（入る線の内の社と並べて）が buffer_rank 以内。
    比べる相手（同じ土俵）＝検問・質・勢いなしの時価の上位 n 社（土俵の中の順位で同じ緩衝帯・同じ上限）"""
    key = px_key or Y * 100 + 6
    mkey = Y * 100 + 6                   # 勢いはいつも6月末で測る（7月の組。10月に作っても同じ組なら同じ値）
    SL, QK, MK = R['select'], R['quality'], R['momentum']
    asof, ranked, fl, pool, mv, Dc, scaled, log = _pool_mv(ctx, Y, R, key, fetch)

    def note(k):
        log[k] = log.get(k, 0) + 1
    elig, why = [], {}
    for c in pool:
        if R['kills'].get('off'):
            w = []                                  # 感度『検問なし』
        elif Dc[c] is None:
            w = ['決算が無い（6月末に出ていた年次決算が無い・測れない）']
        elif is_fin(ctx.SIC[c]):
            w = fin_kills(ctx.F, c, Dc[c], R) if R.get('kills_fin') else ['金融（持たない）']
        else:
            w = kills(ctx.F, c, Dc[c], R)
        if w:
            why[c] = w
            note(f'外す: {w[0]}')
            continue
        elig.append(c)
    comp, met = quality_comp(ctx, elig, Dc, QK)
    mom = {}
    for c in elig:
        m = momentum(ctx, c, mkey, MK['months'], MK['skip'])
        if m is not None:
            mom[c] = m
    qE, qS = top_set(comp, QK['enter_top']), top_set(comp, QK['stay_top'])
    mE, mS = top_set(mom, MK['enter_top']), top_set(mom, MK['stay_top'])

    def passes(c, qs, ms):
        return (qs is None or c in qs) and (ms is None or c in ms)
    E1 = [c for c in elig if passes(c, qE, mE)]
    E2 = {c for c in elig if passes(c, qS, mS)}
    e1 = sorted(E1, key=lambda c: (-mv[c], c))

    def pos(c):                                     # 時価の順位（入る線の内の社と並べて）
        return 1 + sum(1 for e in e1 if e != c and (-mv[e], e) < (-mv[c], c))
    members = e1[:SL['n']]
    kept = [c for c in (prev or []) if c in E2 and c not in members and pos(c) <= SL['buffer_rank']]
    members = members + kept
    w = weights_v3(members, mv, SL)
    porder = sorted(pool, key=lambda c: (-mv[c], c))
    prank = {c: i + 1 for i, c in enumerate(porder)}
    pmem = porder[:SL['n']]
    pmem += [c for c in (prev_pool or []) if c in prank and prank[c] <= SL['buffer_rank'] and c not in pmem]
    pw = cap_weights({c: mv[c] for c in pmem}, SL['cap'])     # 同じ土俵の時価の上位 n 社（検問・質・勢いなし・同じ社数と上限）
    for c in elig:
        if c in members:
            continue
        if qE is not None and c not in comp:
            note('目標の外: 質が測れない')
        elif qE is not None and c not in qE:
            note('目標の外: 質が入る線の外')
        elif mE is not None and c not in mom:
            note('目標の外: 勢いが測れない（株価が12か月分ない）')
        elif mE is not None and c not in mE:
            note('目標の外: 勢いが入る線の外')
        else:
            note('目標の外: 両方の線の内だが時価の順位が外')
    return dict(Y=Y, Dc=Dc, key=key, mkey=mkey, ranked=ranked, fl=fl, pool=pool, elig=elig, comp=comp, met=met, mom=mom,
                qE=qE, mE=mE, qS=qS, mS=mS, E1=e1, E2=E2, members=members, kept=kept, w=w, pw=pw, pmem=pmem,
                mv=mv, rank={c: pos(c) for c in members}, prank=prank, why=why, log=log, scaled=scaled)


def paper_path(ctx, by_year, last):
    """紙の上の ETF（7月の頭に目標の重みで買い、翌年6月まで持ったまま・月の株価が欠けた社はその月0%）の
    月次リターン・各月のはじめの重み・各年の終わりの重み・欠けた月の数（basket_returns_w と同じ持ち方）"""
    out, at, ends, gaps = {}, {}, {}, 0
    for Y in sorted(by_year):
        base = Y * 100 + 6
        W = {t: w for t, w in by_year[Y].items() if ctx.PX.get(t) and base in ctx.PX[t]['m'] and w > 0}
        tot = sum(W.values())
        if not W or tot <= 0:
            continue
        val = {t: w / tot for t, w in W.items()}
        lastp = {t: ctx.PX[t]['m'][base] for t in W}
        for i in range(1, 13):
            k = ym_add(base, i)
            if k > last:
                break
            tv = sum(val.values())
            at[k] = {t: v / tv for t, v in val.items()}
            rs = {}
            for t in W:
                p = ctx.PX[t]['m'].get(k)
                if p is None:
                    rs[t] = 0.0
                    gaps += 1
                else:
                    rs[t] = p / lastp[t] - 1
                    lastp[t] = p
            out[k] = sum(val[t] * rs[t] for t in W) / tv
            for t in W:
                val[t] *= 1 + rs[t]
        tv = sum(val.values())
        ends[Y] = {t: v / tv for t, v in val.items()}
    return out, at, ends, gaps


def run_backtest_v3(ctx, R, last):
    H, P, logs, broke, prev, prevP = {}, {}, {}, {}, None, None
    for Y in COHORTS:
        if Y * 100 + 6 > last:
            break
        co = cohort_v3(ctx, Y, R, prev=prev, prev_pool=prevP)
        H[Y] = {ctx.c2t[c]: w for c, w in co['w'].items()}
        P[Y] = {ctx.c2t[c]: w for c, w in co['pw'].items()}
        broke[Y] = {ctx.c2t[c] for c, ws in co['why'].items() if substantive(ws)}
        prev, prevP = co['members'], co['pmem']
        top10 = sorted(co['w'].items(), key=lambda kv: -kv[1])[:10]
        logs[Y] = {'母集団（上位）': len(co['ranked']), '同じ土俵（金融を除く・株価のある社）': len(co['pool']), '検問を通った': len(co['elig']),
                   '質も勢いも入る線の内': len(co['E1']), '持つ': len(co['members']), '緩衝帯で残した': len(co['kept']),
                   'テックの比重': round(sum(w for c, w in co['w'].items() if is_tech(ctx.SIC[c])), 3),
                   '上位10社の比重': round(sum(w for _, w in top10), 3), '上位10社': [ctx.c2t[c] for c, _ in top10],
                   '中身': sorted(H[Y], key=lambda t: -H[Y][t]), '内訳': co['log'], '時価を株価で直せた社': co['scaled']}
    rH, atH, eH, gH = paper_path(ctx, H, last)
    rP, _, eP, gP = paper_path(ctx, P, last)
    return dict(rH=rH, rP=rP, atH=atH, H=H, P=P, broke=broke, logs=logs, gaps={'H': gH, 'P': gP},
                toH=turnover(H, eH), toP=turnover(P, eP))


def monthly_rets(ctx, t):
    """ティッカーの月次リターン（{yyyymm: r}）。欠けた月は入れない＝その月0%で、次に値のある月に最後の値からの変化として数える"""
    p = (ctx.PX.get(t) or {}).get('m') or {}
    ks = sorted(p)
    return {k: p[k] / p[a] - 1 for a, k in zip(ks, ks[1:]) if p[a] > 0}


def irr_m(n, final):
    """毎月はじめに1を n か月入れて、n か月目の終わりに final になったときの年率（お金の重みつき・%）"""
    if n <= 0 or not final or final <= 0:
        return None
    lo, hi = -0.5, 0.5
    for _ in range(200):
        mid = (lo + hi) / 2
        if sum((1 + mid) ** i for i in range(1, n + 1)) > final:
            hi = mid
        else:
            lo = mid
    return round(((1 + (lo + hi) / 2) ** 12 - 1) * 100, 2)


def dca_operational(ctx, at, broke, tax=TAX_JP, rets=None):
    """実際の運用の近似（J5）: 毎月はじめに1ドルを、紙の上の ETF のその月のはじめの重みから足りない社へ（足りない分の比で）入れる。
    7月のはじめ（6月末の値）に、測った結果として検問に落ちた社だけ売る。売却益に tax（同じ暦年の損と通算・売った時に引く＝
    特定口座の源泉徴収あり）。それ以外は売らない（目標から外れた社は持ったまま・買い足さない）。最後に全部売った場合の税も出す。
    rets: {ティッカー: {yyyymm: r}}（検査用。無ければ株価から作る）"""
    R_ = dict(rets or {})

    def r_of(t, k):
        if t not in R_:
            R_[t] = monthly_rets(ctx, t)
        return R_[t].get(k, 0.0)
    hold, basis = {}, {}
    cash, n, sells, realized = 0.0, 0, 0, 0.0
    yr, gain, withheld, paid = None, 0.0, 0.0, 0.0
    drift = {}
    for k in sorted(at):
        if k // 100 != yr:
            yr, gain, withheld = k // 100, 0.0, 0.0
        if k % 100 == 7:
            for t in sorted(t for t in hold if t in broke.get(k // 100, ())):
                v, b = hold.pop(t), basis.pop(t)
                cash += v
                gain += v - b
                realized += v - b
                sells += 1
                due = tax * max(0.0, gain) - withheld      # 同じ年の損と通算（足りなければ戻る）
                cash -= due
                withheld += due
                paid += due
        cash += 1.0
        n += 1
        tw = at[k]
        V = sum(hold.values()) + cash
        d = {t: max(0.0, w * V - hold.get(t, 0.0)) for t, w in tw.items()}
        sd = sum(d.values())
        if sd >= cash:
            buys = {t: cash * x / sd for t, x in d.items() if x > 0}
        else:
            buys = {t: d[t] + (cash - sd) * w for t, w in tw.items()}
        for t, b in buys.items():
            hold[t] = hold.get(t, 0.0) + b
            basis[t] = basis.get(t, 0.0) + b
        cash = 0.0
        if k % 100 == 6:                                  # 7月の入れ替えの直前に、紙の上の ETF からどれだけずれたか（片道）
            V = sum(hold.values())
            drift[k // 100] = round(0.5 * sum(abs(hold.get(t, 0.0) / V - tw.get(t, 0.0)) for t in set(hold) | set(tw)), 3)
        for t in hold:
            hold[t] *= 1 + r_of(t, k)
    V = sum(hold.values())
    unreal = sum(hold[t] - basis[t] for t in hold)
    final_tax = tax * max(0.0, gain + unreal) - withheld
    after = V - final_tax
    return {'months': n, 'final': round(V, 3), 'multiple': round(V / n, 4) if n else None, 'irr': irr_m(n, V),
            'after_tax': round(after, 3), 'after_multiple': round(after / n, 4) if n else None, 'irr_after_tax': irr_m(n, after),
            'taxes_paid_during': round(paid, 4), 'final_tax': round(final_tax, 4), 'sells_broken': sells,
            'realized_gain': round(realized, 4), 'names_held_end': len(hold), 'drift_before_july': drift}


def dca_plain(r, months, tax=TAX_JP):
    """同じ積立（毎月はじめに1ドル）を売らずに持ち続けた場合（QQQ・SPY・紙の上の ETF＝中で入れ替えても税がかからない形）。最後に全部売った場合の税も"""
    v = 0.0
    for k in months:
        v = (v + 1) * (1 + r.get(k, 0.0))
    n = len(months)
    after = v - tax * max(0.0, v - n)
    return {'months': n, 'final': round(v, 3), 'multiple': round(v / n, 4) if n else None, 'irr': irr_m(n, v),
            'after_tax': round(after, 3), 'after_multiple': round(after / n, 4) if n else None, 'irr_after_tax': irr_m(n, after)}


def by_cohort_year(series, last):
    """各年の組（7月〜翌6月）のリターン（%）。全部の月がそろう系列だけ"""
    out = []
    for Y in COHORTS:
        ks = [k for k in (ym_add(Y * 100 + 6, i) for i in range(1, 13)) if k <= last]
        if not ks:
            break
        row = {'組': Y, '月数': len(ks)}
        for name, r in series.items():
            if all(k in r for k in ks):
                row[name] = round((math.prod(1 + r[k] for k in ks) - 1) * 100, 1)
        out.append(row)
    return out


def growth_returns(path):
    """過去の版の検証の1ドルの推移から月次リターンを戻す（並べるため）"""
    if not os.path.exists(path):
        return {}
    g = json.load(open(path, encoding='utf-8')).get('growth') or {}
    ks, v = g.get('months') or [], g.get('CCF15') or []
    out, prev = {}, 1.0
    for k, x in zip(ks, v):
        out[k] = x / prev - 1
        prev = x
    return out


def backtest_v3():
    R = rules()
    PR = json.load(open(PREREG_V3, encoding='utf-8'))
    ev = PR['evaluation']
    ctx = Ctx(fetch=False)
    spy = (ctx.px('SPY') or {}).get('m') or {}
    last = max(k for k in spy if k < int(dt.date.today().strftime('%Y%m')))
    a = COHORTS[0] * 100 + 7
    run = run_backtest_v3(ctx, R, last)
    rH, rP = run['rH'], run['rP']
    B = {t: etf_returns(ctx, t, a, last) for t in BENCH3 + ['SPMO']}
    q = B['QQQ']
    ser = {'CCF15': rH, '同じ土俵の時価の上位30社（検問・質・勢いなし）': rP, 'CCF15 v2（全銘柄・時価×質の傾き・100社）': growth_returns(OUT_BT2)}
    ser.update({t: B[t] for t in BENCH3 + ['SPMO']})
    st = {k: stats(v, q) for k, v in ser.items() if v}
    j1 = ev['J1']
    sH, sQ = stats(rH, q), stats(q, q)
    dg, dd = round(sH['cagr'] - sQ['cagr'], 2), round(sH['maxdd'] - sQ['maxdd'], 1)
    ex1 = MW.excess_stats(rH, q)
    if ex1 and ex1['ex_ann'] >= j1['win_ex'] and ex1['t'] is not None and ex1['t'] >= j1['win_t']:
        v1v = 'NASDAQ100 に勝った'
    elif dg <= -j1['lose_dcagr']:
        v1v = 'NASDAQ100 より悪い'
    else:
        v1v = 'NASDAQ100 並み（差は偶然と区別できない）'
    j2 = ev['J2']
    ex2 = MW.excess_stats(rH, rP)
    if ex2 and ex2['ex_ann'] >= j2['ex_ann'] and ex2['t'] is not None and ex2['t'] >= j2['t']:
        v2v = '規則に中身あり（同じ土俵の時価の上位30社に勝った）'
    elif ex2 and ex2['ex_ann'] <= -j2['ex_ann'] and ex2['t'] is not None and ex2['t'] <= -j2['t']:
        v2v = '規則で負けた（同じ土俵の時価の上位30社に負けた）'
    else:
        v2v = '差は偶然と区別できない'
    slot, slot_v = judge_slot(rH, B['ITA'], q, B['SMH'], ev['J3_slot'], ev['J3_slot']['dca_months'])
    vs = {t: MW.excess_stats(rH, B[t]) for t in ('QQQ', 'SPY', 'SMH', 'MTUM', 'MGK', 'QUAL', 'RSP', 'ITA')}
    months = sorted(run['atH'])
    j5 = {'CCF15（運用の近似: 積立・壊れた社だけ売る・売却益の税）': dca_operational(ctx, run['atH'], run['broke']),
          'CCF15（紙の上の ETF をそのまま積立・中の入れ替えに税なし）': dca_plain(rH, months),
          'QQQ': dca_plain(q, months), 'SPY': dca_plain(B['SPY'], months)}
    sens = {}
    for name, kw in ev['sensitivity'].items():
        r2 = run_backtest_v3(ctx, variant(R, **kw), last)
        h2 = r2['rH']
        s2 = stats(h2, q)
        sens[name] = {'stats': s2, 'vs_qqq': MW.excess_stats(h2, q), 'vs_same_pool': MW.excess_stats(h2, rP),
                      'vs_qqq_cagr': round(s2['cagr'] - sQ['cagr'], 2), 'vs_qqq_maxdd': round(s2['maxdd'] - sQ['maxdd'], 1),
                      'turnover_mean': round(S.mean(r2['toH'].values()), 3) if r2['toH'] else None,
                      'names_mean': round(S.mean(len(v) for v in r2['H'].values()), 1)}
        print(f"  感度 {name}: 年率 {s2['cagr']}（QQQ との差 {sens[name]['vs_qqq_cagr']:+.2f}pt）", flush=True)
    gone = {Y: run['logs'][Y]['内訳'].get('今はティッカーが無い（買収・倒産などで消えた社＝生き残りの偏り）', 0) for Y in run['logs']}
    doc = {'generated': dt.date.today().isoformat(), 'tool': 'night/ccf15.py backtest', 'method': 'v3',
           'prereg': 'out/ccf15_prereg_v3.json（コミットは結果の前）', 'rules_version': R['version'],
           'window': [a, last], 'stats': st,
           'J1_NASDAQ100と比べて': {'verdict': v1v, 'dcagr': dg, 'dmaxdd': dd, 'excess': ex1},
           'J2_規則の効き': {'verdict': v2v, 'vs_same_pool': ex2},
           '参考_その他15%でITAの代わり': {'verdict': slot_v, **slot},
           'CCF15と相手の差': vs,
           '各年（7月〜翌6月）': by_cohort_year({'CCF15': rH, 'QQQ': q, '同じ土俵': rP, 'SPY': B['SPY'], 'SMH': B['SMH']}, last),
           'J5_運用の近似（毎月1ドルの積立）': j5,
           'turnover': run['toH'], 'turnover_same_pool': run['toP'],
           'turnover_mean': round(S.mean(run['toH'].values()), 3) if run['toH'] else None,
           'sensitivity': sens, '生き残りの偏り（今ティッカーが無い社の数・金融を除く上位1000社のうち）': gone, 'gaps': run['gaps'],
           'growth': growth({'CCF15': rH, 'QQQ': q, 'SPY': B['SPY'], 'SMH': B['SMH']}),
           'cohorts': run['logs']}
    json.dump(doc, open(OUT_BT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'J1': v1v, 'J1_ex': ex1, 'dcagr': dg, 'dmaxdd': dd, 'J2': v2v, 'J2_ex': ex2, 'J3': slot_v,
                      'turnover_mean': doc['turnover_mean'], 'CCF15': st['CCF15'], 'QQQ': st['QQQ'], 'SPY': st['SPY'],
                      'J5': {k: {x: v[x] for x in ('multiple', 'after_multiple', 'irr', 'irr_after_tax')} for k, v in j5.items()}},
                     ensure_ascii=False, indent=1))


def holdings_v3():
    R = rules()
    ctx = Ctx(fetch=True)
    today = dt.date.today()
    Y = today.year if today >= dt.date(today.year, 7, 1) else today.year - 1
    spy = (ctx.px('SPY', True) or {}).get('m') or {}
    now = max(spy)                                   # いちばん新しい月（今月の途中の足）＝今も売買されている社だけ・今の株価で時価を直す
    old = json.load(open(OUT_HOLD, encoding='utf-8')) if os.path.exists(OUT_HOLD) else {}
    prev = None
    if old.get('method') == 'v3' and old.get('cohort') != f'{Y}年7月の組':
        prev = [r['cik'] for r in old.get('holdings', [])]          # 前の年の顔ぶれ＝緩衝帯で残す候補
    co = cohort_v3(ctx, Y, R, prev=prev, px_key=now, fetch=True)
    qp = pct(co['comp'], True) if co['comp'] else {}
    mp = pct(co['mom'], True) if co['mom'] else {}
    QK, MK = R['quality'], R['momentum']

    def r1(x, k=1):
        return None if x is None else round(x, k)
    rows = []
    for c, w in sorted(co['w'].items(), key=lambda kv: -kv[1]):
        D = co['Dc'][c]
        f = ctx.F[c][D]
        rs = [ctx.F[c][y]['roic_used'] for y in range(D - 4, D + 1) if y in ctx.F[c] and ctx.F[c][y]['roic_used'] is not None]
        rows.append({'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'cik': c, 'sic': ctx.SIC[c], 'sector': sector_ja(ctx.SIC[c]),
                     'w': round(w, 6), 'rank': co['rank'][c], 'kept': c in co['kept'], 'tech': is_tech(ctx.SIC[c]),
                     'mv_b': round(co['mv'][c] / 1e9, 1), 'fy_end': f.get('end'),
                     'q_pct': r1(qp.get(c), 3), 'mom12': r1(co['mom'][c] * 100) if c in co['mom'] else None, 'm_pct': r1(mp.get(c), 3),
                     'gpa': r1(f['gpa'], 3), 'cfoa': r1(f['cfoa'], 3),
                     'dsh3': None if c not in co['met']['dsh'] else round(co['met']['dsh'][c] * 100, 1),
                     'roic5': round(S.median(rs), 1) if rs else None, 'nde': r1(f['nde'], 2)})
    nxt = [{'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'sector': sector_ja(ctx.SIC[c]), 'rank': i + 1,
            'mv_b': round(co['mv'][c] / 1e9, 1)}
           for i, c in enumerate(co['E1']) if c not in co['w']][:25]
    by_sector = {}
    for r in rows:
        by_sector[r['sector']] = round(by_sector.get(r['sector'], 0) + r['w'], 6)

    def reason(c):
        if c in co['why']:
            return co['why'][c][0]
        if c not in co['comp']:
            return '質が測れない（物差しが2つそろわない）'
        if co['qE'] is not None and c not in co['qE']:
            return f"質が上位{QK['enter_top']:.0%}の外（上位{1 - qp[c]:.0%}）"
        if c not in co['mom']:
            return '勢いが測れない（株価が12か月分ない）'
        if co['mE'] is not None and c not in co['mE']:
            return f"勢いが上位{MK['enter_top']:.0%}の外（12-1か月 {co['mom'][c]:+.0%}）"
        return '両方の線の内だが時価の順位が外'
    big = [{'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'mv_b': round(co['mv'][c] / 1e9, 1), 'why': reason(c)}
           for c in sorted(co['pool'], key=lambda c: -co['mv'][c]) if c not in co['w']][:25]
    lost = [c for c in co['ranked'][:300] if not ctx.c2t.get(c)]
    sn = sec_names(lost, True)
    gone = []
    for c in lost:
        x = sn.get(c) or {}
        recent = (x.get('last') or '') >= (today - dt.timedelta(days=400)).isoformat()
        exited = any(f in ('15-12B', '15-12G', '15-15D', '25-NSE') for f in (x.get('last_forms') or []))
        gone.append({'cik': c, 'rank': co['ranked'].index(c) + 1, 'float_b': round(co['fl'][c][0] / 1e9, 1), 'name': x.get('name', ''),
                     'former': (x.get('former') or [])[:2], 'last': x.get('last'), 'last_forms': x.get('last_forms'),
                     'read': '上場をやめた（買収・倒産など）' if exited or not recent else 'まだ届け出がある＝番号が変わった疑い（SUCCESSORS を確かめる）'})
    mk = co['mkey']
    doc = {'name': R['name'], 'ja': R['ja'], 'version': R['version'], 'method': 'v3', 'rules': 'out/ccf15_rules.json',
           'generated': today.isoformat(), 'cohort': f'{Y}年7月の組', 'price_month': now,
           'momentum_window': f'{ym_add(mk, -MK["months"]) // 100}年{ym_add(mk, -MK["months"]) % 100}月末→{ym_add(mk, -MK["skip"]) // 100}年{ym_add(mk, -MK["skip"]) % 100}月末',
           'data_note': f"決算は会社ごとに、{Y}年4月1日までに終わった最新の会計年度（6月末に出ていた10-K）。重みは今の株価で直した時価",
           'counts': {'母集団（公開浮動株時価の上位）': len(co['ranked']), '金融を除き株価のある社': len(co['pool']),
                      '壊れないの検問を通った': len(co['elig']),
                      '質が入る線の内': len(co['elig'] if co['qE'] is None else co['qE']),
                      '勢いが入る線の内': len(co['elig'] if co['mE'] is None else co['mE']), '両方': len(co['E1']), '持つ': len(co['members']),
                      '緩衝帯で残した': len(co['kept'])},
           'テックの比重': round(sum(r['w'] for r in rows if r['tech']), 4), '上位10社の比重': round(sum(r['w'] for r in rows[:10]), 4),
           '外した理由': co['log'], '大きいのに持たない社（時価の大きい順）': big,
           'ティッカーの無い大きな社（浮動株の上位300社のうち）': gone,
           'by_sector': dict(sorted(by_sector.items(), key=lambda kv: -kv[1])),
           'holdings': rows, '次の候補（両方の線の内で持たなかった上位）': nxt}
    json.dump(doc, open(OUT_HOLD, 'w'), ensure_ascii=False, indent=1)
    print(f"{len(rows)} 社（{doc['cohort']}・勢い {doc['momentum_window']}）・テック {doc['テックの比重']:.1%}・上位10社 {doc['上位10社の比重']:.1%}")
    for r in rows:
        print(f"  {r['rank']:3d} {r['t']:6s} {r['w']*100:5.2f}% 質{r['q_pct']} 勢い{r['mom12']}% {r['sector']:10s} {r['nm'][:34]}")
    print('大きいのに持たない社:', [(b['t'], b['why']) for b in big[:15]])
    sus = [g for g in gone if g['read'].startswith('まだ')]
    print(f'ティッカーの無い大きな社 {len(gone)} 社（番号が変わった疑い {len(sus)} 社）:', [(g['rank'], g['name'][:28], g['last']) for g in sus[:10]])


def backtest():
    m = rules().get('method')
    if m == 'v3':
        backtest_v3()
    elif m == 'v2':
        backtest_v2()
    else:
        backtest_v1()


def holdings():
    m = rules().get('method')
    if m == 'v3':
        return holdings_v3()
    if m == 'v2':
        return holdings_v2()
    return holdings_v1()


def holdings_v2():
    """今日の中身を v2 の作り方（規則書 out/ccf15_rules_v2.json）で出す（記録の再現用・書き出さない）"""
    R = json.load(open(RULES_V2, encoding='utf-8'))
    ctx = Ctx(fetch=True)
    today = dt.date.today()
    Y = today.year if today >= dt.date(today.year, 7, 1) else today.year - 1
    spy = (ctx.px('SPY', True) or {}).get('m') or {}
    now = max(spy)                                   # いちばん新しい月（今月の途中の足）＝今も売買されている社だけ・今の株価で時価を直す
    old = json.load(open(OUT_HOLD, encoding='utf-8')) if os.path.exists(OUT_HOLD) else {}
    prev = None
    if old.get('method') == 'v2' and old.get('cohort') != f'{Y}年7月の組':
        prev = [r['cik'] for r in old.get('holdings', [])]          # 前の年の顔ぶれ＝緩衝帯で残す候補
    co = cohort_v2(ctx, Y, R, prev=prev, px_key=now, fetch=True)
    rows = []
    for c, w in sorted(co['w'].items(), key=lambda kv: -kv[1]):
        D = co['Dc'][c]                                  # その社の、6月末に出ていた最新の年次決算の年
        f = ctx.F[c][D]
        fin = is_fin(ctx.SIC[c])
        rs = [ctx.F[c][y]['roic_used'] for y in range(D - 4, D + 1) if y in ctx.F[c] and ctx.F[c][y]['roic_used'] is not None]
        roe = [ctx.F[c][y]['ni'] / ctx.F[c][y]['eq'] * 100 for y in range(D - 4, D + 1)
               if y in ctx.F[c] and ctx.F[c][y].get('ni') is not None and ctx.F[c][y].get('eq') and ctx.F[c][y]['eq'] > 0]
        rows.append({'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'cik': c, 'sic': ctx.SIC[c], 'sector': sector_ja(ctx.SIC[c]),
                     'w': round(w, 6), 'rank': co['rank'][c], 'kept': c in co['kept'], 'fin': fin, 'tech': is_tech(ctx.SIC[c]),
                     'tilt': co['tilt'].get(c, 1.0), 'score': None if c not in co['comp'] else round(co['comp'][c], 4),
                     'mv_b': round(co['mv'][c] / 1e9, 1), 'fy_end': f.get('end'),
                     'gpa': None if f['gpa'] is None else round(f['gpa'], 3), 'cfoa': None if f['cfoa'] is None else round(f['cfoa'], 3),
                     'dsh3': None if c not in co['met']['dsh'] else round(co['met']['dsh'][c] * 100, 1),
                     'roic5': None if fin or not rs else round(S.median(rs), 1),
                     'roe5': round(S.median(roe), 1) if fin and roe else None,
                     'nde': None if fin or f['nde'] is None else round(f['nde'], 2)})
    nxt = [{'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'sector': sector_ja(ctx.SIC[c]), 'rank': co['rank'][c]}
           for c in sorted(co['elig'], key=lambda c: co['rank'][c]) if c not in co['w']][:25]
    by_sector = {}
    for r in rows:
        by_sector[r['sector']] = round(by_sector.get(r['sector'], 0) + r['w'], 6)
    big = [{'t': ctx.c2t[c], 'nm': ctx.names.get(c, ''), 'why': co['why'][c][0]}
           for c in sorted(co['why'], key=lambda c: -co['mv'].get(c, 0))[:20]]
    # 番号（CIK）が変わった疑い: 浮動株の上位300社で、今のティッカーが無い社を名指しする（7月の点検で SUCCESSORS に足すか決める）
    lost = [c for c in co['ranked'][:300] if not ctx.c2t.get(c)]
    sn = sec_names(lost, True)
    gone = []
    for c in lost:
        x = sn.get(c) or {}
        recent = (x.get('last') or '') >= (today - dt.timedelta(days=400)).isoformat()
        exited = any(f in ('15-12B', '15-12G', '15-15D', '25-NSE') for f in (x.get('last_forms') or []))
        gone.append({'cik': c, 'rank': co['ranked'].index(c) + 1, 'float_b': round(co['fl'][c][0] / 1e9, 1), 'name': x.get('name', ''),
                     'former': (x.get('former') or [])[:2], 'last': x.get('last'), 'last_forms': x.get('last_forms'),
                     'read': '上場をやめた（買収・倒産など）' if exited or not recent else 'まだ届け出がある＝番号が変わった疑い（SUCCESSORS を確かめる）'})
    doc = {'name': R['name'], 'ja': R['ja'], 'version': R['version'], 'method': 'v2', 'rules': 'out/ccf15_rules.json',
           'generated': today.isoformat(), 'cohort': f'{Y}年7月の組', 'data_year': co['D'], 'price_month': now,
           'data_note': f"決算は会社ごとに、{Y}年4月1日までに終わった最新の会計年度（6月末に出ていた10-K）",
           'counts': {'母集団（公開浮動株時価の上位）': len(co['ranked']), '株価のある社': len(co['pool']),
                      '壊れないの検問を通った': len(co['elig']), '持つ': len(co['members']), '緩衝帯で残した': len(co['kept'])},
           'テックの比重': round(sum(r['w'] for r in rows if r['tech']), 4), '金融の比重': round(sum(r['w'] for r in rows if r['fin']), 4),
           '上位10社の比重': round(sum(r['w'] for r in rows[:10]), 4),
           '外した理由': co['log'], '大きいのに外した社（時価の大きい順）': big,
           'ティッカーの無い大きな社（浮動株の上位300社のうち）': gone,
           'by_sector': dict(sorted(by_sector.items(), key=lambda kv: -kv[1])),
           'holdings': rows, '次の候補（持たなかった上位）': nxt}
    print(f"{len(rows)} 社（{doc['cohort']}・v2 の作り方・書き出さない）・テック {doc['テックの比重']:.1%}・金融 {doc['金融の比重']:.1%}・上位10社 {doc['上位10社の比重']:.1%}")
    for r in rows[:30]:
        print(f"  {r['rank']:4d} {r['t']:6s} {r['w']*100:5.2f}% 傾き{r['tilt']} {r['sector']:10s} {r['nm'][:36]}")
    print('大きいのに外した社:', [(b['t'], b['why']) for b in big[:12]])
    sus = [g for g in gone if g['read'].startswith('まだ')]
    print(f'ティッカーの無い大きな社 {len(gone)} 社（番号が変わった疑い {len(sus)} 社）:', [(g['rank'], g['name'][:28], g['last']) for g in sus[:10]])


# ───────────────────────── 今日の中身（v1 の作り方・記録の再現用） ─────────────────────────
def holdings_v1():
    R = json.load(open(RULES_V1, encoding='utf-8'))
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
    print(f"{len(rows)} 社（{doc['cohort']}・{D}年の決算・v1 の作り方・書き出さない）")
    for r in rows:
        print(f"  {r['rank']:3d} {r['t']:6s} {r['sector']:10s} gpa {r['gpa']} cfoa {r['cfoa']} 株数3年 {r['dsh3']}% ROIC5 {r['roic5']} {r['nm'][:40]}")
    return doc


# ───────────────────────── 紙の上の値動き（立ち上げ日から） ─────────────────────────
def _d8(s):
    return int(s.replace('-', ''))


def _ds(d):
    return f'{d // 10000:04d}-{d // 100 % 100:02d}-{d % 100:02d}'


def nav(today=None):
    """立ち上げ日の中身をその重みのまま持ったまま、毎営業日の終値で値をつける（配当込み・手数料・為替・税は引かない）。
    7月の入れ替えで中身（out/ccf15.json の cohort）が変わったら、新しい『期』を足して前の期の値につなぐ
    （期の境目の日は前の期の終値で閉じ、同じ日の終値から新しい中身で始める）"""
    R = rules()
    H = json.load(open(OUT_HOLD, encoding='utf-8'))
    old = json.load(open(OUT_NAV, encoding='utf-8')) if os.path.exists(OUT_NAV) else {}
    periods = old.get('periods') or []
    names_now = [[r['t'], r['w']] for r in H['holdings']]          # [ティッカー, 重み]
    if not periods:
        periods = [{'from': R['launch'], 'cohort': H['cohort'], 'holdings': names_now}]
    elif periods[-1]['cohort'] != H['cohort']:
        periods.append({'from': None, 'cohort': H['cohort'], 'holdings': names_now})   # 境目の日は下で決める
    bench = ['ITA', 'SPY', 'QQQ', 'RSP']
    for p in periods:                                            # 古い形（ティッカーだけ＝同じ重み）も読む
        p['holdings'] = [h if isinstance(h, list) else [h, 1.0] for h in p['holdings']]
    allt = sorted({t for p in periods for t, _ in p['holdings']} | set(bench))
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
            if d >= d0 and sum(w for t, w in p['holdings'] if px.get(t) and d in px[t]) >= 0.95 * sum(w for _, w in p['holdings']):
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
        ref = {t: px[t][b] for t, _ in p['holdings'] if px.get(t) and b in px[t]}
        wt = {t: w for t, w in p['holdings'] if t in ref}
        wsum = sum(wt.values())
        p['base_day'], p['n'], p['missing'] = _ds(b), len(ref), [t for t, _ in p['holdings'] if t not in ref]
        p['level_at_base'] = round(level, 2)
        start_level = level
        for d in [x for x in days if x >= b and (nxt is None or x <= nxt)]:
            for t in allt:
                if px.get(t) and d in px[t]:
                    lastp[t] = px[t][d]
            v = sum(wt[t] * lastp.get(t, ref[t]) / ref[t] for t in ref) / wsum
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
           'note': '紙の上の値動き（配当込みの終値で、期のはじめの中身をその重みのまま持ったまま）。手数料・為替・税は引いていない。7月の入れ替えで期が変わる',
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
    elif cmd == 'holdings_v1':
        holdings_v1()
    elif cmd == 'holdings_v2':
        holdings_v2()
    elif cmd == 'backtest':
        backtest()
    elif cmd == 'backtest_v1':
        backtest_v1()
    elif cmd == 'backtest_v2':
        backtest_v2()
    elif cmd == 'nav':
        nav()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
