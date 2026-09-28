#!/usr/bin/env python3
"""night/mw_sec_replication.py — 角度 sec_replication（読むだけ・門の判定には不使用）

問い: 『質（収益性）で選んだ米国大型株』を、原本（SEC XBRL）と実際の値動き（Yahoo 配当込み）から
      個人が実際に組める形で作り直すと、2010-07〜2026-08 に市場（SPY・同じ母集団の時価加重）に勝つか。
      JKP 論文の 2007年以降の上乗せ（上限なし時価加重で約 +1.5〜2.9%/年）が、実装できる形でも出るか。
      投資家の集中した形（5社）と、上位1/3から無作為に5社を引いたときのばらつきも出す。

事前登録: out/mw_sec_replication_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を
mw_common.grade でそのまま当てる（ただし XBRL は2009年から＝訓練期間が無いので C1・C4 は構造的に不合格＝格は C に上限）。

段
  extract  : SEC companyfacts.zip（一括・提出日つき）から必要なタグだけ抜き出す → out/_mw_cache/sec_extract.json.gz
  build    : 毎年7月の母集団（浮動株時価の上位500）と信号を作る
  run      : 戦略の月次リターン・統計・判定 → out/mw_sec_replication.json
"""
import sys, os, json, gzip, math, time, datetime, zipfile, random, statistics as S, subprocess, urllib.request, urllib.parse
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

CACHE = M.CACHE
ZIP = os.path.join(CACHE, 'sec_companyfacts.zip')
EXTRACT = os.path.join(CACHE, 'sec_extract.jsonl.gz')
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com'}

DEI_TAGS = {'EntityPublicFloat': 'USD', 'EntityCommonStockSharesOutstanding': 'shares'}
GAAP_TAGS = [
    # 貸借対照表（時点）
    'Assets', 'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
    # 売上
    'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax',
    'SalesRevenueNet', 'SalesRevenueGoodsNet', 'SalesRevenueServicesNet',
    # 粗利・原価
    'GrossProfit', 'CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold', 'CostOfServices',
    'CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization', 'CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization',
    # 営業利益・研究開発・償却・利払い
    'OperatingIncomeLoss', 'ResearchAndDevelopmentExpense', 'ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost',
    'DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet',
    'Depreciation', 'AmortizationOfIntangibleAssets',
    'InterestExpense', 'InterestExpenseDebt', 'InterestExpenseNonoperating', 'InterestAndDebtExpense',
    # 運転資本の増減（キャッシュフロー計算書）
    'IncreaseDecreaseInAccountsReceivable', 'IncreaseDecreaseInReceivables', 'IncreaseDecreaseInAccountsAndNotesReceivable',
    'IncreaseDecreaseInInventories',
    'IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets', 'IncreaseDecreaseInPrepaidExpense', 'IncreaseDecreaseInOtherCurrentAssets',
    'IncreaseDecreaseInDeferredRevenue', 'IncreaseDecreaseInContractWithCustomerLiability',
    'IncreaseDecreaseInAccountsPayable', 'IncreaseDecreaseInAccountsPayableTrade',
    'IncreaseDecreaseInAccruedLiabilities', 'IncreaseDecreaseInAccountsPayableAndAccruedLiabilities',
    'IncreaseDecreaseInOtherCurrentLiabilities', 'IncreaseDecreaseInEmployeeRelatedLiabilities',
    # 株数（発行の少なさ）・参考
    'WeightedAverageNumberOfSharesOutstandingBasic', 'WeightedAverageNumberOfDilutedSharesOutstanding',
    'NetCashProvidedByUsedInOperatingActivities', 'NetIncomeLoss',
    # 営業利益の行が無い社（JNJ・CVX・IBM 等）の代わり: 税引前利益＋利払い
    'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
    'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments',
]
KEEP_FORMS = ('10-K', '10-K/A', '10-KT', '10-KT/A', '10-K405')
INSTANT = {'Assets', 'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'}
FLOAT_MIN = 1.5e9   # 浮動株時価が一度でも15億ドル以上の社だけ残す（上位500の境目は2010年でも40億ドル超）


def _days(a, b):
    return (datetime.date(int(b[:4]), int(b[5:7]), int(b[8:10])) - datetime.date(int(a[:4]), int(a[5:7]), int(a[8:10]))).days


_Z = None


def _one(name):
    """zip の中の1社 → JSON 文字列 {cik, name, t: {tag: [[end, val, filed, amend(0/1)]…]}}。
    年次報告書（10-K 系）の値だけ・期間の項目は約1年（330〜400日）の期間だけ残す（四半期の値を年次と取り違えない）"""
    global _Z
    try:
        if _Z is None:
            _Z = zipfile.ZipFile(ZIP)   # 作業者ごとに1回だけ開く（中央ディレクトリ2万件を毎回読まない）
        d = json.loads(_Z.read(name))
    except Exception:  # noqa
        return None
    facts = d.get('facts') or {}
    dei = facts.get('dei') or {}
    pf = [r['val'] for r in (dei.get('EntityPublicFloat') or {}).get('units', {}).get('USD', []) if r.get('form') in KEEP_FORMS and isinstance(r.get('val'), (int, float))]
    if not pf or max(pf) < FLOAT_MIN:
        return None
    out = {}
    for tag, unit in DEI_TAGS.items():
        rows = (dei.get(tag) or {}).get('units', {}).get(unit) or []
        rr = [[r['end'], r['val'], r['filed'], 0 if r['form'] in ('10-K', '10-KT', '10-K405') else 1] for r in rows if r.get('form') in KEEP_FORMS]
        if rr:
            out['dei:' + tag] = rr
    g = facts.get('us-gaap') or {}
    for tag in GAAP_TAGS:
        u = (g.get(tag) or {}).get('units') or {}
        rows = u.get('shares' if tag.startswith('WeightedAverage') else 'USD') or []
        rr = []
        for r in rows:
            if r.get('form') not in KEEP_FORMS:
                continue
            if tag not in INSTANT:
                if not r.get('start') or not (330 <= _days(r['start'], r['end']) <= 400):
                    continue
            rr.append([r['end'], r['val'], r['filed'], 0 if r['form'] in ('10-K', '10-KT', '10-K405') else 1])
        if rr:
            out[tag] = rr
    return json.dumps({'cik': d.get('cik'), 'name': d.get('entityName'), 't': out}, separators=(',', ':'))


def extract(force=False):
    """一括 zip から JSONL（1行1社）へ。親は文字列を書くだけ＝メモリを食わない"""
    if os.path.exists(EXTRACT) and not force:
        return
    names = [n for n in zipfile.ZipFile(ZIP).namelist() if n.endswith('.json')]
    t0 = time.time(); kept = 0
    tmp = EXTRACT + '.tmp'
    with gzip.open(tmp, 'wt') as f, Pool(3) as p:
        for i, r in enumerate(p.imap_unordered(_one, names, chunksize=20)):
            if r:
                f.write(r + '\n'); kept += 1
            if i % 2000 == 0:
                print(f'  抜き出し {i}/{len(names)} 残した社 {kept} {time.time() - t0:.0f}s', flush=True)
    os.replace(tmp, EXTRACT)
    print(f'抜き出し完了: {kept}社 {time.time() - t0:.0f}s')


def load_extract():
    with gzip.open(EXTRACT, 'rt') as f:
        for line in f:
            yield json.loads(line)



# ───────────────────────── 年ごとの特性（6月30日までに提出された10-Kだけ） ─────────────────────────
YEARS = list(range(2010, 2027))          # 形成は各年7月（6月末の値で組み、7月から保有）
START, END = 201007, 202608
ANCHOR = ['OperatingIncomeLoss', 'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet',
          'NetIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities', 'GrossProfit']
REV_SUB = ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet']
COGS_SUB = ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization']
DA_SUB = ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet']
PRETAX_SUB = ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
              'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments']
RD_SUB = ['ResearchAndDevelopmentExpense', 'ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost']
INT_SUB = ['InterestExpense', 'InterestExpenseDebt', 'InterestAndDebtExpense', 'InterestExpenseNonoperating']
AR_SUB = ['IncreaseDecreaseInAccountsReceivable', 'IncreaseDecreaseInReceivables', 'IncreaseDecreaseInAccountsAndNotesReceivable']
PP_SUB = ['IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets', 'IncreaseDecreaseInPrepaidExpense', 'IncreaseDecreaseInOtherCurrentAssets']
DR_SUB = ['IncreaseDecreaseInContractWithCustomerLiability', 'IncreaseDecreaseInDeferredRevenue']
AP_SUB = ['IncreaseDecreaseInAccountsPayable', 'IncreaseDecreaseInAccountsPayableTrade']
ACC_SUB = ['IncreaseDecreaseInAccruedLiabilities', 'IncreaseDecreaseInOtherCurrentLiabilities']
FEAT_VERSION = 'v4'   # 特性の作り方を変えたら上げる（パネルのキャッシュ名）
BOUNDS = {'cop_at': (-1.0, 2.0), 'gp_at': (-0.5, 3.0), 'nsi': (-2.0, 2.0)}   # 外は採取の誤り（桁違い等）として欠測（事前登録）


def _d(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def year_features(rec, t):
    """会社 rec の t 年7月の形成に使う値。**6月30日（t年）までに提出された 10-K 系だけ**・決算期末は t−1 年の暦年内（Fama-French の作法）。
    無い値は None（0 で埋めない）。例外は事前登録どおり: 研究開発費・運転資本の増減・利払いは『行が無い＝0』（原論文の作法）"""
    T = rec['t']
    cutoff = f'{t}-06-30'
    f = {}
    # 浮動株時価（最新の10-Kの表紙。基準日は第2四半期末）
    fl = [r for r in T.get('dei:EntityPublicFloat', []) if r[2] <= cutoff and _num(r[1]) is not None]
    if fl:
        r = max(fl, key=lambda r: (r[2], r[0]))
        age = (_d(cutoff) - _d(r[0])).days
        filed_age = (_d(cutoff) - _d(r[2])).days
        if r[1] > 0 and age <= 30 * 31 and filed_age <= 16 * 31:   # 表紙の基準日は30か月以内・提出は16か月以内（提出をやめた社を残さない）
            f['float'] = float(r[1]); f['float_date'] = r[0]; f['float_filed'] = r[2]
            sh = [q for q in T.get('dei:EntityCommonStockSharesOutstanding', []) if q[2] == r[2] and _num(q[1]) is not None and q[1] > 0]
            if sh:   # 同じ10-Kの表紙の発行済株数（浮動株の検算用）。複数の値（株式クラス）なら合計せず最大を使い、印を付ける
                f['shares_cover'] = float(max(q[1] for q in sh)); f['shares_date'] = max(q[0] for q in sh)
                if len({q[1] for q in sh}) > 1:
                    f['shares_multi'] = True
    # 決算期末 E（t−1 年の暦年内・提出は cutoff まで）
    lo_e, hi_e = f'{t - 1}-01-08', f'{t}-01-07'     # t−1 年の決算（52/53週決算で1月初めに終わる年も t−1 年として拾う）
    ends = [r[0] for tag in ANCHOR for r in T.get(tag, []) if r[2] <= cutoff and lo_e <= r[0] <= hi_e]
    if not ends:
        return f
    E = max(ends); dE = _d(E)
    f['fy_end'] = E

    def pick(tag):
        rows = [r for r in T.get(tag, []) if r[2] <= cutoff and abs((_d(r[0]) - dE).days) <= 3 and _num(r[1]) is not None]
        if not rows:
            return None
        return float(max(rows, key=lambda r: (r[2], r[3]))[1])

    def first(tags):
        for tg in tags:
            v = pick(tg)
            if v is not None:
                return v
        return None

    A = pick('Assets')
    SE = pick('StockholdersEquity')
    if SE is None:
        SE = pick('StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest')
    revs = [v for v in (pick(tg) for tg in REV_SUB) if v is not None]
    rev = max(revs) if revs else None
    if rev is None:
        g_, s_ = pick('SalesRevenueGoodsNet'), pick('SalesRevenueServicesNet')
        if g_ is not None or s_ is not None:
            rev = (g_ or 0.0) + (s_ or 0.0)
    gp = pick('GrossProfit')
    if gp is None and rev is not None:
        cogs = first(COGS_SUB)
        if cogs is None:
            base = first(['CostOfGoodsSold', 'CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization'])
            sv = pick('CostOfServices')
            if base is not None or sv is not None:
                cogs = (base or 0.0) + (sv or 0.0)
        if cogs is not None:
            gp = rev - cogs
    if gp is not None and rev is not None and rev > 0 and gp > rev * 1.01:
        gp = None
    oi = pick('OperatingIncomeLoss')
    it = first(INT_SUB)
    if oi is None:
        pt = first(PRETAX_SUB)
        if pt is not None:
            oi = pt + (it or 0.0); f['oi_from_pretax'] = True
    da = first(DA_SUB)
    if da is None:
        dep = pick('Depreciation')
        if dep is not None:
            da = dep + (pick('AmortizationOfIntangibleAssets') or 0.0)
    rd = first(RD_SUB)
    f['has'] = {'A': A is not None, 'SE': SE is not None, 'rev': rev is not None, 'gp': gp is not None, 'oi': oi is not None,
                'da': da is not None, 'rd': rd is not None, 'int': it is not None}
    if A is not None and A > 0:
        f['assets'] = A
        if gp is not None:
            f['gp_at'] = gp / A
        if oi is not None and da is not None:
            op = oi + da + (rd or 0.0)                       # Ball et al. の OP ≈ 営業利益＋償却＋研究開発費
            dar = first(AR_SUB) or 0.0
            dinv = pick('IncreaseDecreaseInInventories') or 0.0
            dpp = first(PP_SUB) or 0.0
            ddr = first(DR_SUB) or 0.0
            apacc = pick('IncreaseDecreaseInAccountsPayableAndAccruedLiabilities')
            if apacc is None:
                apacc = (first(AP_SUB) or 0.0) + (first(ACC_SUB) or 0.0)
            cop = op - dar - dinv - dpp + ddr + apacc
            f['cop_at'] = cop / A
            f['op_at'] = op / A
    if SE is not None and SE > 0:
        f['be'] = SE                                         # 簿価時価比（探索の族 qv）用
    if SE is not None and SE > 0 and oi is not None and da is not None:
        f['ope_be'] = (oi + da - (it or 0.0)) / SE          # Fama-French 2015 の OP ≈ 営業利益＋償却−利払い（研究開発費は引いたまま）
    # 発行の少なさ: 同じ10-Kの中の加重平均株数（基本）の今期÷前期（分割は同じ提出書類の中で遡って調整済み）
    rows = [r for r in T.get('WeightedAverageNumberOfSharesOutstandingBasic', []) if r[2] <= cutoff and _num(r[1]) is not None]
    cur = [r for r in rows if abs((_d(r[0]) - dE).days) <= 3]
    if cur:
        rc = max(cur, key=lambda r: (r[2], r[3]))
        prev = [r for r in rows if r[2] == rc[2] and r[3] == rc[3] and 350 <= (dE - _d(r[0])).days <= 380]
        if prev and rc[1] > 0 and prev[0][1] > 0:
            f['nsi'] = math.log(rc[1] / prev[0][1])
        if rc[1] > 0:
            f['ws_basic'] = float(rc[1]); f['ws_filed'] = rc[2]   # 浮動株と表紙の株数が食い違ったときの裁定用
    for k, (lo, hi) in BOUNDS.items():
        if k in f and not (lo <= f[k] <= hi):
            f.setdefault('bad', []).append(k); del f[k]
    return f


def build_panel():
    """抜き出し → {cik: {'name', 'y': {t: 特性}}}（キャッシュ）"""
    pth = os.path.join(CACHE, f'mw_sec_panel_{FEAT_VERSION}.json.gz')
    if os.path.exists(pth) and os.path.getmtime(pth) > os.path.getmtime(EXTRACT):
        return json.load(gzip.open(pth, 'rt'))
    panel = {}
    for rec in load_extract():
        y = {}
        for t in YEARS:
            f = year_features(rec, t)
            if f.get('float'):
                y[str(t)] = f
        if y:
            panel[str(int(rec['cik']))] = {'name': rec['name'], 'y': y}
    with gzip.open(pth + '.tmp', 'wt') as fo:
        json.dump(panel, fo)
    os.replace(pth + '.tmp', pth)
    return panel


# ───────────────────────── ティッカー・業種 ─────────────────────────
STOP = {'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'LIMITED', 'PLC', 'HOLDINGS', 'HOLDING', 'GROUP', 'THE', 'NV', 'SA', 'AG',
        'LP', 'LLC', 'INCORPORATED', 'AND', 'N', 'V', 'L', 'P', 'DE', 'NEW'}


def norm_name(s):
    s = (s or '').upper()
    if '/' in s:
        s = s.split('/')[0]
    s = ''.join(ch if ch.isalnum() else ' ' for ch in s.replace('&', ' AND '))
    return ' '.join(w for w in s.split() if w not in STOP)


def ticker_map():
    """現在の SEC 一覧（ファイルの並び順で CIK ごとに最初のティッカー）"""
    d = json.load(open(os.path.join(CACHE, 'sec_company_tickers.json')))
    tk, title = {}, {}
    for v in d.values():
        c = str(v['cik_str'])
        if c not in tk:
            tk[c] = v['ticker']; title[c] = v['title']
    return tk, title


def sic_codes(ciks):
    pth = os.path.join(CACHE, 'mw_sec_sic.json')
    m = json.load(open(pth)) if os.path.exists(pth) else {}
    for src in (os.path.join(M.BASE, 'out', 'sic_by_cik.json'),):
        if os.path.exists(src):
            for c, v in json.load(open(src)).items():
                if v:
                    m.setdefault(str(int(c)), str(v))
    old = os.path.join(M.BASE, 'out', '_sic_cache.json')
    if os.path.exists(old):
        for v in json.load(open(old)).values():
            if v.get('cik') and v.get('sic'):
                m.setdefault(str(int(v['cik'])), str(v['sic']))
    miss = [c for c in ciks if c not in m]
    print(f'SIC: 既知 {len(ciks) - len(miss)} / 取得 {len(miss)}', flush=True)
    for i, c in enumerate(miss):
        for k in range(4):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(f'https://data.sec.gov/submissions/CIK{int(c):010d}.json', headers=SEC_UA), timeout=60).read()
                m[c] = str(json.loads(raw).get('sic') or '')
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    m[c] = ''; break
                time.sleep(2 ** k)
            except Exception:  # noqa
                time.sleep(2 ** k)
        time.sleep(0.12)
        if i % 200 == 199:
            json.dump(m, open(pth, 'w'))
    json.dump(m, open(pth, 'w'))
    return m


def ff12_fn():
    import io
    b = M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes12.zip', name='fr_Siccodes12_map.zip', max_age_days=3650)
    z = zipfile.ZipFile(io.BytesIO(b))
    rng, cur = [], None
    for l in z.read(z.namelist()[0]).decode('latin-1').split('\n'):
        p = l.split()
        if not p:
            continue
        if p[0].isdigit() and len(p) >= 2:
            cur = p[1]
        elif '-' in p[0] and cur:
            a, b_ = p[0].split('-')
            rng.append((int(a), int(b_), cur))

    def f(sic):
        try:
            x = int(sic)
        except (TypeError, ValueError):
            return None
        for a, b_, k in rng:
            if a <= x <= b_:
                return k
        return 'Other'
    return f


TOPRAW = 1100   # 浮動株そのままの上位1100社から価格で換算して上位500を選ぶ（換算で順位が入れ替わる余地）
EXCL_SIC = {'6221', '6189', '6722', '6726', '6770', '6792', '6795'}   # 商品信託・資産担保・投信・SPAC・ロイヤルティ信託＝事業会社でない


# ───────────────────────── Yahoo（月次・配当込み／分割調整の終値） ─────────────────────────
def yahoo_raw(ticker):
    """mw_common.yahoo と同じ URL・同じキャッシュ名。404 は印を残して即座に諦める（価格なし＝欠測）"""
    miss = os.path.join(CACHE, f'yhmiss_{ticker}.txt')
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 14 * 86400:
        return None
    name = f'yh_{ticker.replace("^", "IDX_").replace("=", "_")}_1mo.json'
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 20 * 86400 and os.path.getsize(p) > 0:
        return json.load(open(p))
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    for k in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
            tmp = f'{p}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, p)
            return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                open(miss, 'w').write(str(e.code)); return None
            time.sleep(3 * 2 ** k)
        except Exception:  # noqa
            time.sleep(2 ** k)
    open(miss, 'w').write('err')
    return None


def yahoo_series(ticker):
    """→ (月次総リターン {yyyymm: r}（隣り合う月だけ）, 分割調整終値 {yyyymm: close}, 最初の月)。無ければ None"""
    j = yahoo_raw(ticker)
    try:
        r = j['chart']['result'][0]
        ts = r['timestamp']; q = r['indicators']['quote'][0]['close']
        adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q
    except Exception:  # noqa
        return None
    cl, ad = {}, {}
    for t_, c, a in zip(ts, q, adj):
        d = datetime.datetime.utcfromtimestamp(t_)
        k = d.year * 100 + d.month
        if k > END:
            continue
        if c is not None and c > 0:
            cl[k] = c
        if a is not None and a > 0:
            ad[k] = a
    ks = sorted(ad)
    ret = {}
    for a_, b_ in zip(ks, ks[1:]):
        if _nextm(a_) == b_:
            ret[b_] = ad[b_] / ad[a_] - 1
    splits = []
    for e in ((r.get('events') or {}).get('splits') or {}).values():
        try:
            d = datetime.datetime.utcfromtimestamp(e['date'])
            if e['denominator'] and e['numerator']:
                splits.append((d.year * 100 + d.month, e['numerator'] / e['denominator']))
        except Exception:  # noqa
            pass
    return ret, cl, (ks[0] if ks else None), splits


def split_after(splits, k):
    """月 k の月末より後の分割の比の積（分割調整済みの終値 × これ = その月の生の株価）"""
    x = 1.0
    for m, r in splits:
        if m > k:
            x *= r
    return x


def _nextm(k):
    y, m = divmod(k, 100)
    return (y + 1) * 100 + 1 if m == 12 else k + 1


def _addm(k, n):
    y, m = divmod(k, 100)
    m0 = y * 12 + (m - 1) + n
    return (m0 // 12) * 100 + m0 % 12 + 1



def _float_month(dstr):
    d = _d(dstr)
    k = d.year * 100 + d.month
    return k if d.day >= 15 else _addm(k, -1)     # 月末の終値に寄せる（第2四半期末は月末）


def _prev_ok(panel, c, t, fl):
    """同じ社の前年の浮動株と比べて桁違いでないか（20倍以内）。前年が無ければ None（検算できない）"""
    pv = panel[c]['y'].get(str(t - 1))
    if not pv or not pv.get('float'):
        return None
    r = fl / pv['float']
    return 1 / 20 <= r <= 20


def _sane(fl, f):
    """桁違いの検問（事前登録）: 6兆ドル以下 かつ 総資産の200倍以下（総資産が分かるとき）"""
    if fl > 6e12:
        return False
    a = f.get('assets')
    return not (a and fl > 200 * a)


def raw_candidates(panel, t, tk):
    """浮動株そのままの候補（大きい順）。同じ値・同じ基準日を持つ別 CIK（共同提出者の写し）は1社にまとめ（一覧に載る CIK を残す）、
    前年と20倍を超えて違う浮動株と、桁違いの検問に落ちる浮動株は除く"""
    cand = [(c, v['y'][str(t)]) for c, v in panel.items() if str(t) in v['y']]
    cand.sort(key=lambda x: (x[0] not in tk, int(x[0])))
    seen, out = set(), []
    for c, f in cand:
        key = (round(f['float']), f['float_date'])
        if key in seen:
            continue
        seen.add(key)
        if _prev_ok(panel, c, t, f['float']) is False or not _sane(f['float'], f):
            continue
        out.append((c, f['float']))
    return sorted(out, key=lambda x: -x[1])


def build_universe(panel, fetch=True, verbose=True, N=500, topraw=None):
    """毎年6月末の母集団。返り値: (uni {t: {cik: {...}}}, price {ticker: (ret, close, first, splits)}, diag, sic, tick)
    浮動株の値の検算（事前登録）: 同じ10-Kの表紙の株数×生の株価（分割を戻す）で出した時価 cap と比べ、浮動株÷cap が
    0.02〜4 の外なら浮動株の誤り（桁違い）として cap を大きさに使う。株数が無ければ前年の浮動株と比べ、20倍を超える違いは除く"""
    tk, title = ticker_map()
    by_norm = {}
    for c, ttl in title.items():
        by_norm.setdefault(norm_name(ttl).replace(' ', ''), set()).add(c)
    ff12 = ff12_fn()
    top = {}
    for t in YEARS:
        top[t] = raw_candidates(panel, t, tk)[:(topraw or TOPRAW)]
    need = sorted({c for t in YEARS for c, _ in top[t]}, key=int)
    sic = sic_codes(need) if fetch else json.load(open(os.path.join(CACHE, 'mw_sec_sic.json')))
    # ティッカー（名前の一致による後継の当て方は事前登録どおり: 正規化した社名（空白も除く）が現在の一覧の1社とだけ一致する場合）
    tick, via = {}, {}
    for c in need:
        if c in tk:
            tick[c] = tk[c]; via[c] = 'cik'
        else:
            nm = norm_name(panel[c]['name']).replace(' ', '')
            hit = [x for x in by_norm.get(nm, set()) if x != c] if nm else []
            if len(hit) == 1:
                tick[c] = tk[hit[0]]; via[c] = 'name'
    tickers = sorted(set(tick.values()))
    from concurrent.futures import ThreadPoolExecutor
    price = {}
    with ThreadPoolExecutor(3) as ex:
        for i, (x, v) in enumerate(zip(tickers, ex.map(yahoo_series, tickers))):
            price[x] = v
            if verbose and i % 300 == 0:
                print(f'  Yahoo {i}/{len(tickers)}', flush=True)
    uni, diag = {}, {}
    for t in YEARS:
        jm = t * 100 + 6
        rows = []
        miss = {'n': 0, 'no_ticker': 0, 'no_yahoo': 0, 'no_price_at_t': 0, 'float_invalid': 0, 'ok': 0,
                'float_share_missing': 0.0, 'ticker_via_name': 0}
        val = {'checked_shares': 0, 'conflict_use_cap': 0, 'conflict_keep_float': 0, 'excluded_conflict': 0, 'checked_prev': 0, 'excluded_prev': 0, 'checked_ws': 0, 'excluded_ws': 0, 'unchecked': 0, 'excluded_sanity': 0}
        tot_float = 0.0; miss_float = 0.0
        ranked = [(c, fl) for c, fl in top[t] if sic.get(c, '') not in EXCL_SIC]
        for pos, (c, fl) in enumerate(ranked):
            f = panel[c]['y'][str(t)]
            x = tick.get(c)
            st = None; fcap = None; how = None
            if x is None:
                st = 'no_ticker'
            elif price.get(x) is None:
                st = 'no_yahoo'
            else:
                ret, cl, first, spl = price[x]
                fm = _float_month(f['float_date'])
                if not (jm in cl and fm in cl and _nextm(jm) in ret):
                    st = 'no_price_at_t'
                else:
                    fcap = f['float'] * cl[jm] / cl[fm]
                    cm = _float_month(f['shares_date']) if f.get('shares_cover') else None
                    pk = _prev_ok(panel, c, t, f['float'])
                    if cm and cm in cl:
                        cap_c = f['shares_cover'] * cl[cm] * split_after(spl, cm)
                        q = (f['float'] * cl[cm] / cl[fm]) / cap_c
                        if 0.02 <= q <= 4:
                            how = 'checked_shares'
                        else:
                            # 食い違い → 第三の値（損益計算書の加重平均株数×提出月の生の株価）で裁く
                            cap_cov = cap_c * cl[jm] / cl[cm]
                            wm = _float_month(f['ws_filed']) if f.get('ws_basic') else None
                            cap_ws = f['ws_basic'] * cl[wm] * split_after(spl, wm) * cl[jm] / cl[wm] if (wm and wm in cl) else None
                            if cap_ws and 0.5 <= cap_ws / cap_cov <= 2:
                                fcap = cap_cov; how = 'conflict_use_cap'        # 株数どうしが合う＝浮動株の側の誤り
                            elif cap_ws and 0.3 <= fcap / cap_ws <= 2.5:
                                how = 'conflict_keep_float'                     # 浮動株と加重平均株数が合う＝表紙の株数の側の誤り
                            else:
                                fcap = None; how = 'excluded_conflict'          # 決められない → 欠測（0 でも代わりの値でもない）
                    else:
                        wm = _float_month(f['ws_filed']) if f.get('ws_basic') else None
                        if pk is None and wm and wm in cl:   # 前年も表紙の株数も無い → 加重平均株数×生の株価で桁だけ確かめる
                            q = fcap / (f['ws_basic'] * cl[wm] * split_after(spl, wm) * cl[jm] / cl[wm])
                            if 0.02 <= q <= 4:
                                how = 'checked_ws'
                            else:
                                fcap = None; how = 'excluded_ws'
                        elif pk is None:
                            how = 'unchecked'
                        elif pk:
                            how = 'checked_prev'
                        else:
                            fcap = None; how = 'excluded_prev'
                    if fcap and not _sane(fcap, f):
                        fcap = None; how = 'excluded_sanity'
                    st = 'ok' if fcap else 'float_invalid'
            if pos < 500:
                miss['n'] += 1; miss[st] += 1; tot_float += fl
                if st != 'ok':
                    miss_float += fl
                if via.get(c) == 'name' and st == 'ok':
                    miss['ticker_via_name'] += 1
            if how:
                val[how] += 1
            if fcap:
                sc = sic.get(c, '')
                dup = [q for q in rows if q['ticker'] == x]
                if dup:   # 同じティッカーに2つの CIK → CIK が一覧に載っている方、次に新しい10-Kを出した方を残す
                    old = dup[0]
                    if (old['via'] == 'cik', old['float_filed']) >= (via.get(c) == 'cik', f['float_filed']):
                        continue
                    rows.remove(old)
                rows.append({'cik': c, 'ticker': x, 'fcap': fcap, 'sic': sc, 'ff12': ff12(sc) if sc else None, 'rawpos': pos,
                             'via': via.get(c), 'float_filed': f['float_filed'], 'size_how': how})
        miss['float_share_missing'] = round(miss_float / tot_float, 4) if tot_float else None
        rows.sort(key=lambda r: -r['fcap'])
        u = {}
        for r in rows[:N]:
            f = panel[r['cik']]['y'][str(t)]
            r.update({k: f.get(k) for k in ('cop_at', 'gp_at', 'ope_be', 'nsi', 'op_at', 'fy_end', 'float_date', 'oi_from_pretax', 'be')})
            r['name'] = panel[r['cik']]['name']
            u[r['cik']] = r
        uni[t] = u
        diag[t] = {'top500_by_raw_float': miss, 'universe_n': len(u), 'fcap_500th': round(rows[N - 1]['fcap'] / 1e9, 2) if len(rows) >= N else None,
                   'size_validation_all_priced': val,
                   'size_how_in_universe': {k: sum(1 for r in u.values() if r['size_how'] == k) for k in val}}
        diag[t]['priced'] = [r['cik'] for r in rows]
        pr = set(diag[t]['priced'])
        diag[t]['_missing_ciks'] = [c for c, _ in ranked[:500] if c not in pr]
    return uni, price, diag, sic, tick


# ───────────────────────── 信号・銘柄選び ─────────────────────────
SIGS = ['cop_at', 'gp_at', 'ope_be']
COMP_PARTS = ['cop_at', 'gp_at', 'ope_be', 'lowiss']


def rank_z(vals):
    """{key: 値} → 順位の z（同順位は平均順位）。大きいほど良い"""
    ks = sorted(vals, key=lambda k: vals[k])
    n = len(ks)
    if n < 3:
        return {}
    rk = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[ks[j + 1]] == vals[ks[i]]:
            j += 1
        for q in range(i, j + 1):
            rk[ks[q]] = (i + j) / 2 + 1
        i = j + 1
    mu = (n + 1) / 2
    sd = math.sqrt(sum((r - mu) ** 2 for r in rk.values()) / n)
    return {k: (r - mu) / sd for k, r in rk.items()}


def scores(u):
    """母集団 u（1年分）→ 金融を除いた順位づけの対象と各信号の得点 {sig: {cik: score}}"""
    R = {c: r for c, r in u.items() if r.get('ff12') and r['ff12'] != 'Money'}
    out = {}
    z = {}
    for k in SIGS:
        vals = {c: r[k] for c, r in R.items() if r.get(k) is not None}
        out[k] = vals
        z[k] = rank_z(vals)
    z['lowiss'] = rank_z({c: -r['nsi'] for c, r in R.items() if r.get('nsi') is not None})
    comp = {}
    for c in R:
        parts = [z[k][c] for k in COMP_PARTS if c in z[k]]
        if len(parts) >= 3:
            comp[c] = sum(parts) / len(parts)
    out['comp'] = comp
    out['_z'] = z
    return R, out


def neutral(score, R):
    """業種で中立化: 得点 − 業種平均（SIC 2桁の群に5社以上いればその群、足りなければ FF12 の残りでまとめた群）"""
    g2 = {}
    for c in score:
        g2.setdefault(R[c]['sic'][:2], []).append(c)
    grp = {}
    for k, cs in g2.items():
        for c in cs:
            grp[c] = ('s2', k) if len(cs) >= 5 else ('ff', R[c]['ff12'])
    mem = {}
    for c, g in grp.items():
        mem.setdefault(g, []).append(c)
    return {c: score[c] - sum(score[x] for x in mem[grp[c]]) / len(mem[grp[c]]) for c in score}


def top_by(score, u, n=None, frac=None):
    ks = sorted(score, key=lambda c: (-score[c], -u[c]['fcap']))
    if frac:
        return ks[:int(len(ks) * frac)]
    return ks[:n]


def cohorts_for(uni):
    """年ごとの組入れ重み {戦略: {t: {ticker: w}}}（形成時の重み）＋記録"""
    C = {}
    info = {'n_rankable': {}, 'n_signal': {}, 'top5': {}, 'tech_share': {}}
    for t in YEARS:
        u = uni[t]
        R, sc = scores(u)
        info['n_rankable'][t] = len(R)
        info['n_signal'][t] = {k: len(sc[k]) for k in SIGS + ['comp']} | {'lowiss': len(sc['_z']['lowiss'])}
        tkr = lambda c: u[c]['ticker']
        def put(name, sel, vw):
            if not sel:
                return
            w = {tkr(c): (u[c]['fcap'] if vw else 1.0) for c in sel}
            C.setdefault(name, {})[t] = w
        for k in SIGS + ['comp']:
            put(f'{k}_T3VW', top_by(sc[k], u, frac=1 / 3), True)
            put(f'{k}_T50EW', top_by(sc[k], u, n=50), False)
            put(f'{k}_T20EW', top_by(sc[k], u, n=20), False)
            put(f'{k}_T5EW', top_by(sc[k], u, n=5), False)
        info['top5'][t] = {k: [tkr(c) for c in top_by(sc[k], u, n=5)] for k in ('comp', 'cop_at')}
        # 業種中立（comp と cop_at）
        exf = [c for c in R]
        indw = {}
        for c in exf:
            indw[R[c]['ff12']] = indw.get(R[c]['ff12'], 0.0) + u[c]['fcap']
        for k in ('comp', 'cop_at'):
            base = sc['comp'] if k == 'comp' else sc['_z']['cop_at']
            ne = neutral(base, R)
            put(f'{k}_IN_T20EW', top_by(ne, u, n=20), False)
            w = {}
            sel_ind = {}
            for c in ne:
                sel_ind.setdefault(R[c]['ff12'], []).append(c)
            wsum = sum(indw[g] for g in sel_ind)
            for g, cs in sel_ind.items():
                cs = sorted(cs, key=lambda c: (-ne[c], -u[c]['fcap']))
                pick = cs[:max(1, math.ceil(len(cs) / 3))]
                tot = sum(u[c]['fcap'] for c in pick)
                for c in pick:
                    w[tkr(c)] = indw[g] / wsum * u[c]['fcap'] / tot
            if w:
                C.setdefault(f'{k}_IN_T3SM', {})[t] = w
        # 相手（同じ母集団）
        C.setdefault('U_all', {})[t] = {tkr(c): r['fcap'] for c, r in u.items()}
        C.setdefault('U_exfin', {})[t] = {tkr(c): u[c]['fcap'] for c in R}
        C.setdefault('U_exfin_EW', {})[t] = {tkr(c): 1.0 for c in R}
        # 技術（FF12 BusEq）の比重（形成時）
        def share(wmap):
            tot = sum(wmap.values()); byt = {u[c]['ticker']: c for c in u}
            return round(sum(v for x, v in wmap.items() if u[byt[x]].get('ff12') == 'BusEq') / tot, 3) if tot else None
        info['tech_share'][t] = {k: share(C[k][t]) for k in ('comp_T3VW', 'cop_at_T3VW', 'gp_at_T3VW', 'ope_be_T3VW', 'comp_IN_T3SM', 'U_exfin', 'U_all', 'comp_T5EW', 'comp_T20EW') if t in C.get(k, {})}
    return C, info


def hold_months(t):
    ms = []
    k = t * 100 + 7
    while k <= min((t + 1) * 100 + 6, END):
        ms.append(k); k = _nextm(k)
    return ms


def simulate(coh, rets):
    """年1回7月に組み直し、年の中は買って持つ（重みは値動きで漂う）。月の値が無い銘柄はその月から外し残りで按分（0で埋めない）"""
    out, turns, drops = {}, [], 0
    prev = None
    for t in sorted(coh):
        w0 = coh[t]; tot = sum(w0.values())
        w = {k: v / tot for k, v in w0.items()}
        if prev is not None:
            turns.append(0.5 * sum(abs(w.get(k, 0) - prev.get(k, 0)) for k in set(w) | set(prev)))
        cur = dict(w)
        for m in hold_months(t):
            av = {k: v for k, v in cur.items() if m in rets.get(k, {})}
            drops += len(cur) - len(av)
            if not av:
                break
            tv = sum(av.values())
            out[m] = sum(v * rets[k][m] for k, v in av.items()) / tv
            cur = {k: v * (1 + rets[k][m]) for k, v in av.items()}
        s_ = sum(cur.values())
        prev = {k: v / s_ for k, v in cur.items()} if s_ else None
    return out, (sum(turns) / len(turns) if turns else None), drops


def random_draws(sets, rets, bench, R=2000, k=5, seed=20260928):
    """sets {t: [ticker…]} から毎年 k 社を無作為に引き等分・年の中は買って持つ → 全期間の CAGR 差の分布"""
    rng = random.Random(seed)
    res = {nm: [] for nm in bench}
    ks = sorted(sets)
    for _ in range(R):
        coh = {t: {x: 1.0 for x in rng.sample(sets[t], min(k, len(sets[t])))} for t in ks}
        s_, _t, _d = simulate(coh, rets)
        for nm, b in bench.items():
            mm = sorted(set(s_) & set(b))
            res[nm].append((M.cagr([s_[m] for m in mm]) - M.cagr([b[m] for m in mm])) * 100)
    out = {}
    for nm, v in res.items():
        v.sort()
        q = lambda p: round(v[min(len(v) - 1, int(p * len(v)))], 2)
        out[nm] = {'draws': len(v), 'win_rate': round(sum(1 for x in v if x > 0) / len(v), 3), 'p05': q(0.05), 'p25': q(0.25),
                   'median': q(0.5), 'p75': q(0.75), 'p95': q(0.95), 'mean': round(sum(v) / len(v), 2)}
    return out



# ───────────────────────── 集計 ─────────────────────────
PRE_NAME = 'mw_sec_replication_prereg.json'
OUT_NAME = 'mw_sec_replication.json'
FORMS = ['T3VW', 'T50EW', 'T20EW', 'T5EW']
PRIMARY = [f'{k}_{f}' for k in ['cop_at', 'gp_at', 'ope_be', 'comp'] for f in FORMS] + \
          ['comp_IN_T3SM', 'comp_IN_T20EW', 'cop_at_IN_T3SM', 'cop_at_IN_T20EW']
DESC = {'cop_at': '現金ベースの営業収益性÷総資産（Ball et al. 2016）', 'gp_at': '粗利÷総資産（Novy-Marx 2013）',
        'ope_be': '営業利益（利払い後）÷自己資本（Fama-French 2015）', 'comp': '合成（3つの収益性＋発行の少なさの順位z の平均）',
        'T3VW': '上位1/3・浮動株時価加重', 'T50EW': '上位50社・等分', 'T20EW': '上位20社・等分', 'T5EW': '上位5社・等分',
        'IN_T3SM': '業種中立: FF12業種ごとに上位1/3（SIC2桁で中立化した得点）・業種の重みは母集団（金融除く）と同じ',
        'IN_T20EW': '業種中立: SIC2桁で中立化した得点の上位20社・等分'}
COST = 0.001     # 片道100%あたり0.10%（大型株・mw_prereg の既定）


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def desc(nm):
    for k in ('cop_at', 'gp_at', 'ope_be', 'comp'):
        if nm.startswith(k + '_'):
            return DESC[k] + '／' + DESC[nm[len(k) + 1:]]
    return nm


def stats_block(sr, b, turn=None):
    d = {'full': M.excess_stats(sr, b, START, END), 'recent': M.excess_stats(sr, b, M.RECENT_START, END),
         'to_2025_12': M.excess_stats(sr, b, START, 202512),
         'first_half_2010_2017': M.excess_stats(sr, b, START, 201806), 'second_half_2018_2026': M.excess_stats(sr, b, 201807, END),
         'roll10': M.rolling(sr, b, 10), 'dca10': M.dca(sr, b, 10), 'roll20': M.rolling(sr, b, 20), 'dca20': M.dca(sr, b, 20)}
    if turn is not None:
        d['net_cost_full'] = M.excess_stats(M.apply_cost(sr, turn, COST), b, START, END)
    return d


def run():
    t0 = time.time()
    panel = build_panel()
    uni, price, diag, sic, tick = build_universe(panel)
    rets = {x: v[0] for x, v in price.items() if v}
    C, info = cohorts_for(uni)
    ser, turn, drops = {}, {}, {}
    for nm, coh in C.items():
        ser[nm], turn[nm], drops[nm] = simulate(coh, rets)
    spy = yahoo_series('SPY')[0]
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if START <= k <= END}
    B = {'U_all': ser['U_all'], 'SPY': spy, 'FF_Mkt': mkt, 'U_exfin': ser['U_exfin']}
    # 判定（主の相手 = 同じ母集団の浮動株時価加重 U_all）
    res = {}
    pv = {bn: {} for bn in B}
    for nm in PRIMARY:
        if nm not in ser:
            continue
        r = {'name': nm, 'primary': True, 'description': desc(nm), 'turnover_oneway_ann': round(turn[nm], 3) if turn[nm] else None,
             'n_months': len(ser[nm]), 'dropped_stock_months': drops[nm], 'cagr': round(M.cagr(ser[nm]) * 100, 2),
             'maxdd': round(M.maxdd(ser[nm]) * 100, 1), 'vs': {}}
        for bn, b in B.items():
            r['vs'][bn] = stats_block(ser[nm], b, turn[nm] or 0.0)
            h = r['vs'][bn]['full']
            pv[bn][nm] = h['p'] if h else None
        res[nm] = r
    holm = {bn: M.holm(pv[bn]) for bn in B}
    for nm, r in res.items():
        for bn in B:
            v = r['vs'][bn]
            g, c = M.grade(v['full'], None, v['full'], v['roll20'], cost_hold=v['net_cost_full'], repl=None,
                           family_holm_p=holm[bn].get(nm))
            v['holm_p'] = holm[bn].get(nm)
            v['grade'] = g; v['criteria'] = c
        r['grade'] = r['vs']['U_all']['grade']; r['criteria'] = r['vs']['U_all']['criteria']; r['holm_p'] = r['vs']['U_all']['holm_p']
    # 相手どうし（生き残りの偏りと作り方の差）
    refs = {'U_all_vs_SPY': stats_block(ser['U_all'], spy), 'U_all_vs_FF_Mkt': stats_block(ser['U_all'], mkt),
            'SPY_vs_FF_Mkt': stats_block(spy, mkt), 'U_exfin_vs_U_all': stats_block(ser['U_exfin'], ser['U_all']),
            'U_exfin_EW_vs_U_exfin': stats_block(ser['U_exfin_EW'], ser['U_exfin'])}
    ks = sorted(set(ser['U_all']) & set(spy))
    refs['corr_U_all_SPY'] = round(M.corr([ser['U_all'][k] for k in ks], [spy[k] for k in ks]), 4)
    # 等分の戦略は等分の母集団とも比べる（報告のみ）
    for nm in PRIMARY:
        if nm.endswith('EW') and nm in ser:
            res[nm]['vs_U_exfin_EW_full'] = M.excess_stats(ser[nm], ser['U_exfin_EW'], START, END)
    # 無作為の5社
    sets = {}
    for t in YEARS:
        R, sc = scores(uni[t])
        sets.setdefault('top_third_comp', {})[t] = [uni[t][c]['ticker'] for c in top_by(sc['comp'], uni[t], frac=1 / 3)]
        sets.setdefault('top_third_cop_at', {})[t] = [uni[t][c]['ticker'] for c in top_by(sc['cop_at'], uni[t], frac=1 / 3)]
        sets.setdefault('universe_exfin', {})[t] = [uni[t][c]['ticker'] for c in R]
    rnd = {k: random_draws(v, rets, {'U_all': ser['U_all'], 'SPY': spy}) for k, v in sets.items()}
    # JKP（同じ特性・CRSP/Compustat・上限なし時価加重の良い側1/3）との照合
    jk = {}
    jmkt = M.jkp_mkt('usa', 'vw')
    mine = {'cop_at': 'cop_at_T3VW', 'gp_at': 'gp_at_T3VW', 'ope_be': 'ope_be_T3VW', 'chcsho_12m': None}
    for key, mn in mine.items():
        try:
            side, pp = M.jkp_good_side('usa', key, 'vw', upto=M.TRAIN_END)
            js = pp[side]
        except Exception as e:  # noqa
            jk[key] = {'error': str(e)}; continue
        d = {'good_side': side, 'post2007': M.excess_stats(js, jmkt, M.HOLD_START, 202512),
             'same_window_2010_07_2025_12': M.excess_stats(js, jmkt, START, 202512)}
        if mn:
            a1 = {k: js[k] - jmkt[k] for k in js if k in jmkt}
            a2 = {k: ser[mn][k] - ser['U_all'][k] for k in ser[mn] if k in ser['U_all']}
            kk = sorted(set(a1) & set(a2))
            d['corr_active_with_mine'] = round(M.corr([a1[k] for k in kk], [a2[k] for k in kk]), 3)
            d['mine_same_window'] = M.excess_stats(ser[mn], ser['U_all'], START, 202512)
        jk[key] = d
    # 生き残りの偏り: 浮動株そのままの上位500で価格が取れない社の割合（年ごと）と、その社の質の三分位
    surv = {}
    tri = {'high': [0, 0], 'mid': [0, 0], 'low': [0, 0]}
    ff12 = ff12_fn()
    tkmap, _ttl = ticker_map()
    for t in YEARS:
        surv[t] = diag[t]['top500_by_raw_float'] | {'universe_n': diag[t]['universe_n'], 'fcap_500th_bn': diag[t]['fcap_500th']}
        cand = [(c, fl) for c, fl in raw_candidates(panel, t, tkmap) if sic.get(c, '') not in EXCL_SIC][:500]
        pu = {}
        for c, fl in cand:
            f = panel[c]['y'][str(t)]; scd = sic.get(c, '')
            pu[c] = {'ff12': ff12(scd) if scd else None, 'sic': scd, 'fcap': fl, **{k: f.get(k) for k in ('cop_at', 'gp_at', 'ope_be', 'nsi')}}
        R, sc = scores(pu)
        order = top_by(sc['comp'], pu)
        n = len(order)
        okset = set(diag[t]['priced'])
        for i, c in enumerate(order):
            b = 'high' if i < n // 3 else ('mid' if i < 2 * n // 3 else 'low')
            tri[b][0] += 1
            if c not in okset:
                tri[b][1] += 1
    surv_tri = {b: {'n': v[0], 'missing': v[1], 'rate': round(v[1] / v[0], 3) if v[0] else None} for b, v in tri.items()}
    # 点検
    ffa = ff['mkt']
    chk = {'french_mkt_cagr_all': round(M.cagr(ffa) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(ffa, M.HOLD_START)) * 100, 2),
           'french_last_month': max(ffa), 'spy_cagr_window': round(M.cagr(M.window(spy, START, END)) * 100, 2),
           'french_mkt_cagr_window': round(M.cagr(M.window(ffa, START, END)) * 100, 2),
           'U_all_cagr_window': round(M.cagr(ser['U_all']) * 100, 2), 'months': [min(ser['U_all']), max(ser['U_all'])]}
    samp = {}
    for t in (2010, 2012, 2016, 2020, 2025):
        u = uni[t]; top10 = sorted(u.values(), key=lambda r: -r['fcap'])[:10]
        samp[t] = [(r['ticker'], round(r['fcap'] / 1e9, 1)) for r in top10]
    chk['largest_by_float_cap_bn'] = samp
    chk['ticker_via_name_in_universe'] = {t: sum(1 for r in uni[t].values() if r['via'] == 'name') for t in YEARS}
    chk['feature_coverage_in_universe'] = {t: {k: sum(1 for r in uni[t].values() if r.get(k) is not None) for k in ('cop_at', 'gp_at', 'ope_be', 'nsi')} for t in YEARS}
    tech = {}
    for k in ('comp_T3VW', 'cop_at_T3VW', 'gp_at_T3VW', 'ope_be_T3VW', 'comp_IN_T3SM', 'U_exfin', 'U_all', 'comp_T5EW', 'comp_T20EW'):
        v = [info['tech_share'][t].get(k) for t in YEARS if info['tech_share'][t].get(k) is not None]
        tech[k] = round(sum(v) / len(v), 3) if v else None
    # 年ごとのリターン（7月〜翌6月・報告）
    ann = {}
    for nm in ('comp_T3VW', 'comp_T20EW', 'comp_T5EW', 'cop_at_T3VW', 'comp_IN_T3SM', 'U_all', 'U_exfin'):
        ann[nm] = {t: round((math.prod(1 + ser[nm][m] for m in hold_months(t) if m in ser[nm]) - 1) * 100, 1) for t in YEARS}
    ann['SPY'] = {t: round((math.prod(1 + spy[m] for m in hold_months(t) if m in spy) - 1) * 100, 1) for t in YEARS}
    tested = []
    for nm in PRIMARY:
        if nm in res:
            tested.append({'name': nm, 'role': 'primary', 'grade': res[nm]['grade']})
    for k in rnd:
        tested.append({'name': f'random5_{k}', 'role': 'report_distribution', 'grade': None})
    for k in jk:
        tested.append({'name': f'JKP_{k}_vw_T3', 'role': 'reference_replication', 'grade': None})
    out = {'angle': 'sec_replication', 'prereg': PRE_NAME, 'prereg_commit': sha_of(f'out/{PRE_NAME}'),
           'period': [START, END], 'train': None, 'train_note': 'XBRL は2009年から＝2006年以前の訓練期間は作れない（C1・C4 は構造的に不合格＝格は最高でも C）',
           'primary_benchmark': 'U_all（同じ母集団・浮動株時価加重・生き残りの偏りをおおむね相殺）',
           'tested': tested, 'n_tested': len(tested), 'strategies': res, 'benchmark_refs': refs, 'random5': rnd, 'jkp_replication': jk,
           'survivorship': {'by_year': surv, 'missing_by_quality_tercile': surv_tri}, 'checks': chk, 'tech_share_avg': tech,
           'top5_holdings': info['top5'], 'annual_returns_jul_jun': ann, 'n_rankable': info['n_rankable'], 'n_signal': info['n_signal'],
           'runtime_s': round(time.time() - t0)}
    p = M.save(OUT_NAME, out)
    print('→', p)
    return out



def check():
    """測る前の点検（データの有無・範囲・件数だけ。戦略と市場の比較は一切しない）"""
    panel = build_panel()
    print('panel 社数', len(panel))
    uni, price, diag, sic, tick = build_universe(panel)
    for t in YEARS:
        u = uni[t]
        cov = {k: sum(1 for r in u.values() if r.get(k) is not None) for k in ('cop_at', 'gp_at', 'ope_be', 'nsi')}
        nf = sum(1 for r in u.values() if r.get('ff12') == 'Money'); nn = sum(1 for r in u.values() if not r.get('ff12'))
        d = diag[t]['top500_by_raw_float']
        print(t, 'U', len(u), '500th', diag[t]['fcap_500th'], 'fin', nf, 'nosic', nn, cov, 'pretaxOI', sum(1 for r in u.values() if r.get('oi_from_pretax')),
              '| raw500', {k: d[k] for k in ('no_ticker', 'no_yahoo', 'no_price_at_t', 'float_invalid', 'ok')}, 'fl_share_miss', d['float_share_missing'],
              'via_name', d['ticker_via_name'], '| size', diag[t]['size_how_in_universe'])
    for t in (2010, 2015, 2020, 2025):
        top = sorted(uni[t].values(), key=lambda r: -r['fcap'])[:12]
        print(t, [(r['ticker'], round(r['fcap'] / 1e9), r.get('ff12'), r['size_how'], None if r.get('cop_at') is None else round(r['cop_at'], 3)) for r in top])
    for t in (2012, 2020, 2025):
        print(t, 'conflict/unchecked', [(r['ticker'], r['size_how'], round(r['fcap'] / 1e9, 1)) for r in uni[t].values() if r['size_how'] in ('conflict_use_cap', 'conflict_keep_float', 'unchecked')][:30])
    print('fcap/assets>15', sorted(((round(r['fcap'] / (panel[r['cik']]['y'][str(t)].get('assets') or 1e30), 1), t, r['ticker'], r['size_how'], round(r['fcap'] / 1e9, 1)) for t in YEARS for r in uni[t].values() if r['fcap'] > 15 * (panel[r['cik']]['y'][str(t)].get('assets') or 1e30)), reverse=True))
    print('fcap/assets 上位', sorted(((round(r['fcap'] / (panel[r['cik']]['y'][str(t)].get('assets') or 1e30), 1), t, r['ticker']) for t in YEARS for r in uni[t].values()), reverse=True)[:15])
    want = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'XOM', 'JNJ', 'WMT', 'GE', 'JPM', 'BRK-B', 'DIS', 'AVGO', 'META', 'NVDA', 'V']
    for t in (2010, 2014, 2018, 2022):
        have = {r['ticker'] for r in uni[t].values()}
        print(t, 'missing known:', [w for w in want if w not in have])
    ex = [(t, r['ticker'], r['name']) for t in YEARS for r in uni[t].values() if r['via'] == 'name']
    print('名前で当てたティッカー', len(ex), sorted({(x[1], x[2]) for x in ex})[:60])
    # 価格が無い上位（浮動株そのまま）の例
    tk, _ = ticker_map()
    for t in (2010, 2016):
        ms = diag[t]['_missing_ciks'][:40]
        print(t, 'missing examples', [(panel[c]['name'][:28], round(panel[c]['y'][str(t)]['float'] / 1e9)) for c in ms[:25]])



# ───────────────────────── 探索の族（prereg2） ─────────────────────────
PRE2_NAME = 'mw_sec_replication_prereg2.json'
FAM2 = ['cop_at_T10EW', 'comp_T10EW', 'cop_at_M100_T3VW', 'cop_at_M100_T10EW', 'comp_M100_T3VW', 'cop_at_T3VW_exBusEq',
        'comp_T3VW_exBusEq', 'lowiss_T3VW', 'lowiss_T50EW', 'copiss_T3VW', 'qv_T3VW', 'cop_at_U1000_T3VW', 'comp_U1000_T3VW']
PRIM_B2 = {'cop_at_M100_T3VW': 'M100', 'cop_at_M100_T10EW': 'M100', 'comp_M100_T3VW': 'M100', 'cop_at_T3VW_exBusEq': 'U_exfin_exBusEq',
           'comp_T3VW_exBusEq': 'U_exfin_exBusEq', 'cop_at_U1000_T3VW': 'U1000', 'comp_U1000_T3VW': 'U1000'}


def _w(u, sel, vw):
    return {u[c]['ticker']: (u[c]['fcap'] if vw else 1.0) for c in sel}


def _pair_score(za, zb):
    return {c: (za[c] + zb[c]) / 2 for c in za if c in zb}


def simulate_detail(coh, rets):
    """simulate と同じ動き。月ごとの月初の重み {m: {ticker: w}} も返す（事後の分解用）"""
    out, wts = {}, {}
    for t in sorted(coh):
        w0 = coh[t]; tot = sum(w0.values())
        cur = {k: v / tot for k, v in w0.items()}
        for m in hold_months(t):
            av = {k: v for k, v in cur.items() if m in rets.get(k, {})}
            if not av:
                break
            tv = sum(av.values())
            wts[m] = {k: v / tv for k, v in av.items()}
            out[m] = sum(v * rets[k][m] for k, v in av.items()) / tv
            cur = {k: v * (1 + rets[k][m]) for k, v in av.items()}
    return out, wts


def brinson(pw, bw, rets, ind):
    """配分効果・選択効果（月ごとの算術・年率）。ind(m, ticker) → 業種"""
    alloc = sel = 0.0; n = 0; by = {}
    for m in sorted(set(pw) & set(bw)):
        P, B = pw[m], bw[m]
        rb = sum(v * rets[k][m] for k, v in B.items())
        agg = {}
        for side, W in (('p', P), ('b', B)):
            for k, v in W.items():
                g = ind(m, k)
                a = agg.setdefault(g, {'p': [0.0, 0.0], 'b': [0.0, 0.0]})
                a[side][0] += v; a[side][1] += v * rets[k][m]
        for g, a in agg.items():
            wp, wb = a['p'][0], a['b'][0]
            Rb = a['b'][1] / wb if wb else rb
            Rp = a['p'][1] / wp if wp else 0.0
            al = (wp - wb) * (Rb - rb)
            se = wp * (Rp - Rb) if wp else 0.0
            alloc += al; sel += se
            d = by.setdefault(g, [0.0, 0.0, 0.0, 0.0]); d[0] += al; d[1] += se; d[2] += wp; d[3] += wb
        n += 1
    k = 12 / n * 100
    return {'months': n, 'allocation_ann': round(alloc * k, 2), 'selection_ann': round(sel * k, 2),
            'by_industry': {g: {'alloc': round(v[0] * k, 2), 'select': round(v[1] * k, 2), 'avg_w_port': round(v[2] / n, 3), 'avg_w_bench': round(v[3] / n, 3)}
                            for g, v in sorted(by.items(), key=lambda x: -abs(x[1][0] + x[1][1]))}}


def run2():
    t0 = time.time()
    out_p = os.path.join(M.BASE, 'out', OUT_NAME)
    main = json.load(open(out_p))
    panel = build_panel()
    uni, price, diag, sic, tick = build_universe(panel)
    uni1k, price1k, diag1k, _s, _t = build_universe(panel, N=1000, topraw=2200)
    rets = {x: v[0] for x, v in list(price.items()) + list(price1k.items()) if v}
    C = {}
    for t in YEARS:
        u = uni[t]
        R, sc = scores(u)
        z = sc['_z']
        C.setdefault('cop_at_T10EW', {})[t] = _w(u, top_by(sc['cop_at'], u, n=10), False)
        C.setdefault('comp_T10EW', {})[t] = _w(u, top_by(sc['comp'], u, n=10), False)
        C.setdefault('lowiss_T3VW', {})[t] = _w(u, top_by(z['lowiss'], u, frac=1 / 3), True)
        C.setdefault('lowiss_T50EW', {})[t] = _w(u, top_by(z['lowiss'], u, n=50), False)
        C.setdefault('copiss_T3VW', {})[t] = _w(u, top_by(_pair_score(z['cop_at'], z['lowiss']), u, frac=1 / 3), True)
        bm = rank_z({c: R[c]['be'] / R[c]['fcap'] for c in R if R[c].get('be')})
        C.setdefault('qv_T3VW', {})[t] = _w(u, top_by(_pair_score(z['cop_at'], bm), u, frac=1 / 3), True)
        # 上位100社
        m100 = {c: u[c] for c in sorted(u, key=lambda c: -u[c]['fcap'])[:100]}
        Rm, scm = scores(m100)
        C.setdefault('cop_at_M100_T3VW', {})[t] = _w(m100, top_by(scm['cop_at'], m100, frac=1 / 3), True)
        C.setdefault('cop_at_M100_T10EW', {})[t] = _w(m100, top_by(scm['cop_at'], m100, n=10), False)
        C.setdefault('comp_M100_T3VW', {})[t] = _w(m100, top_by(scm['comp'], m100, frac=1 / 3), True)
        C.setdefault('M100', {})[t] = _w(m100, list(m100), True)
        # 技術を除く
        ux = {c: r for c, r in u.items() if r.get('ff12') and r['ff12'] not in ('Money', 'BusEq')}
        Rx, scx = scores(ux)
        C.setdefault('cop_at_T3VW_exBusEq', {})[t] = _w(ux, top_by(scx['cop_at'], ux, frac=1 / 3), True)
        C.setdefault('comp_T3VW_exBusEq', {})[t] = _w(ux, top_by(scx['comp'], ux, frac=1 / 3), True)
        C.setdefault('U_exfin_exBusEq', {})[t] = _w(ux, list(ux), True)
        # 上位1000社
        uk = uni1k[t]
        Rk, sck = scores(uk)
        C.setdefault('cop_at_U1000_T3VW', {})[t] = _w(uk, top_by(sck['cop_at'], uk, frac=1 / 3), True)
        C.setdefault('comp_U1000_T3VW', {})[t] = _w(uk, top_by(sck['comp'], uk, frac=1 / 3), True)
        C.setdefault('U1000', {})[t] = _w(uk, list(uk), True)
        C.setdefault('U_all', {})[t] = _w(u, list(u), True)
    ser, turn, drops = {}, {}, {}
    for nm, coh in C.items():
        ser[nm], turn[nm], drops[nm] = simulate(coh, rets)
    spy = yahoo_series('SPY')[0]
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if START <= k <= END}
    res, pv = {}, {}
    for nm in FAM2:
        pb = PRIM_B2.get(nm, 'U_all')
        B = {pb: ser[pb], 'U_all': ser['U_all'], 'SPY': spy, 'FF_Mkt': mkt}
        r = {'name': nm, 'primary': False, 'exploratory': 'prereg2', 'primary_benchmark': pb,
             'turnover_oneway_ann': round(turn[nm], 3) if turn[nm] else None, 'cagr': round(M.cagr(ser[nm]) * 100, 2),
             'maxdd': round(M.maxdd(ser[nm]) * 100, 1), 'dropped_stock_months': drops[nm], 'vs': {}}
        for bn, b in B.items():
            r['vs'][bn] = stats_block(ser[nm], b, turn[nm] or 0.0)
        pv[nm] = r['vs'][pb]['full']['p'] if r['vs'][pb]['full'] else None
        res[nm] = r
    hm = M.holm(pv)
    for nm, r in res.items():
        v = r['vs'][r['primary_benchmark']]
        g, c = M.grade(v['full'], None, v['full'], v['roll20'], cost_hold=v['net_cost_full'], repl=None, family_holm_p=hm.get(nm))
        r['grade'] = g; r['criteria'] = c; r['holm_p'] = hm.get(nm)
    refs = {'M100_vs_U_all': stats_block(ser['M100'], ser['U_all']), 'U1000_vs_U_all': stats_block(ser['U1000'], ser['U_all']),
            'U1000_vs_SPY': stats_block(ser['U1000'], spy), 'U_exfin_exBusEq_vs_U_all': stats_block(ser['U_exfin_exBusEq'], ser['U_all'])}
    # 報告: 無作為の5社
    sets_m, sets_10 = {}, {}
    for t in YEARS:
        u = uni[t]
        m100 = {c: u[c] for c in sorted(u, key=lambda c: -u[c]['fcap'])[:100]}
        Rm, scm = scores(m100)
        sets_m[t] = [m100[c]['ticker'] for c in top_by(scm['cop_at'], m100, frac=1 / 3)]
        R, sc = scores(u)
        sets_10[t] = [u[c]['ticker'] for c in top_by(sc['cop_at'], u, n=10)]
    rnd = {'random5_M100_top_third_cop_at': random_draws(sets_m, rets, {'M100': ser['M100'], 'SPY': spy}),
           'random5_top10_cop_at': random_draws(sets_10, rets, {'U_all': ser['U_all'], 'SPY': spy})}
    # 事後: 業種の配分と選択の分解（主の族の3本・相手 U_exfin）
    ind_map = {}
    for t in YEARS:
        for c, r in uni[t].items():
            ind_map[(t, r['ticker'])] = r.get('ff12') or '?'
    def ind(m, k):
        t = m // 100 if m % 100 >= 7 else m // 100 - 1
        return ind_map.get((t, k), '?')
    Cp = {}
    for t in YEARS:
        u = uni[t]; R, sc = scores(u)
        for k in ('cop_at', 'gp_at', 'comp'):
            Cp.setdefault(k + '_T3VW', {})[t] = _w(u, top_by(sc[k], u, frac=1 / 3), True)
        Cp.setdefault('U_exfin', {})[t] = _w(u, list(R), True)
    det = {nm: simulate_detail(coh, rets) for nm, coh in Cp.items()}
    post = {nm: brinson(det[nm][1], det['U_exfin'][1], rets, ind) for nm in ('cop_at_T3VW', 'gp_at_T3VW', 'comp_T3VW')}
    tested2 = [{'name': nm, 'role': 'exploratory_prereg2', 'grade': res[nm]['grade']} for nm in FAM2] + \
              [{'name': k, 'role': 'report_distribution_prereg2', 'grade': None} for k in rnd] + \
              [{'name': 'brinson_' + k, 'role': 'post_hoc_事後', 'grade': None} for k in post]
    main['exploratory_prereg2'] = {'prereg': PRE2_NAME, 'prereg_commit': sha_of(f'out/{PRE2_NAME}'), 'strategies': res, 'refs': refs,
                                   'random5': rnd, 'post_hoc_事後_brinson_vs_U_exfin': post, 'tested': tested2,
                                   'u1000_diag': {t: {'universe_n': diag1k[t]['universe_n'], 'fcap_1000th_bn': diag1k[t]['fcap_500th']} for t in YEARS},
                                   'runtime_s': round(time.time() - t0)}
    tn = [x for x in main['tested'] if x.get('role') not in ('exploratory_prereg2', 'report_distribution_prereg2', 'post_hoc_事後')]
    main['tested'] = tn + tested2
    main['n_tested'] = len(main['tested'])
    p = M.save(OUT_NAME, main)
    print('→', p)


if __name__ == '__main__':
    stage = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if stage == 'extract':
        extract(force='--force' in sys.argv)
    elif stage == 'check':
        check()
    elif stage == 'run':
        run()
    elif stage == 'run2':
        run2()
