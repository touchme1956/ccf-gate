#!/usr/bin/env python3
"""night/unx_assets.py — 未調査の候補の検定（unexplored）A・B が共有する部品: 新しい本の系列と世界・物差し・100年の代用（2026-10-14）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/unexplored_prereg.json（6f534c92・測る前に固定）の
common・groups.A_final_allocation・groups.B_diversifier_slices どおりに、A（night/unx_final.py）と B（night/unx_slices.py）が使う。

やり方（night/etf_forward_rank.py＝R も night/bestpf_ext.py＝X も**書き換えない**＝X と同じ作法）
  1. X.rank_result()（R の25本＋R7 の7本）をそのまま土台にする（night/bestpf_check.py と同じ）。X が書く写し（FAKE_BASE・SIC の写し）は
     この道具のキャッシュへ向ける（out/_bestpf_cache を作らない・書かない）。
  2. 新しい本（FBT・SHLD・SHLD_EU〔感度・後知恵〕・EDV・TLT・UST_HEDGED_2621・TIP・GDX・SLV・VNQ・EWY・YEN_CASH・MF_REF・GOLDPLUS_REF）を
     R.C・R.DATA・R.JPM_MAP・R.GMO_MAP・R.VG_MAP に**足して**（既存の値は1つも変えない）R.main(write=False) をもう一度回す。
     そのとき R.C・R.DATA は一時的に「R の25本＋新しい本」に差し替え（R7 の本は X の結果をそのまま使う）、終われば元へ戻す。
     代理・合成の系列は M.yahoo の前に一枚かませて渡す（X.patched_env と同じ作法）。ETF の中身の写しは、既存の
     out/etf_profiles.json・out/etf_forward_profiles.json を書き換えずに写しへ新しい本を足して R.BASE をそこへ向ける。
  3. 世界B・C は R.main の中で新しい本を入れられないので、R の式を写した X.world_fns を既存の本に、新しい本には事前登録の式
     （債券・金・現金・業種の上乗せ）を当てる関数で計算し直す。写しが正しいことは、R の25本で R.main の値と **1e-12 以内で一致**
     することで確かめる（回帰の検査）。2回目の R.main の25本が X の結果と1ビットも違わないことも確かめる。
  4. 円の枠: 月次のドル建ての値に FRED DEXJPUS の月末の比を掛ける（円の本＝YEN_CASH・UST_HEDGED_2621 はそのまま）。
     B・C・D は為替の期待変化0（ドル建ての本はドルの値のまま）。感度 FX18＝円の本以外の B・C・D から 1.8%/年を引く。
  5. 物差し＝night/bestpf_check.py の1本ずつの塊そのもの（5つの世界・π・20年の積立の表・崩れの置き場所・過去の転がる20年・超大型株の感度）。
  6. 100年の代用: 月次＝alloc_check.century と同じ（FBT＝Drugs・SHLD＝Aero＋Guns・GDX＝Gold・XLU＝Util を足す）／
     年次＝Damodaran（T-bond・T-bill・Gold）と French の年次（月次を暦年で複利）で年1回の積立の市場との比。

キャッシュ: 環境変数 UNX_AB_CACHE（既定 out/_nx_cache/unx/ab/・gitignore）。既存のキャッシュ（out/_mw_cache・out/_gaps_cache・out/_nx_cache）は
読むだけ（同じ鮮度の決まりで新しければ読み、古ければこの道具のキャッシュへ取り直す）。

使い方: python3 night/unx_assets.py   （データ・代理の門・回帰の検査だけを表示。結果の JSON は書かない）
"""
import copy, datetime, hashlib, io, json, math, os, re, shutil, statistics as S, sys, time, urllib.parse, urllib.request
from contextlib import contextmanager

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M              # noqa: E402
import gaps_common as G            # noqa: E402
import nx_common as N              # noqa: E402
import etf_forward_rank as R       # noqa: E402
import industry_exposure as IE     # noqa: E402
from industry_trends import ff49_map  # noqa: E402
import bestpf_ext as X             # noqa: E402

PREREG = 'out/unexplored_prereg.json（6f534c92）'
CDIR = os.environ.get('UNX_AB_CACHE') or os.path.join(BASE, 'out', '_nx_cache', 'unx', 'ab')
LAST = 202609                      # common.data_cutoff（途中の 2026-10 は使わない）
GATE, MIN_OVERLAP = 0.90, 24       # common.proxy_gate
INFL = R.INFL
YEN_ASSETS = {'UST_HEDGED_2621', 'YEN_CASH'}
GATE_FAILED_KEEP = {'SHLD', 'SHLD_EU'}   # 門を通らなくても F_now の代わりの形を作るために残す本（出力で必ず名指し）
REF_ASSETS = {'MF_REF', 'GOLDPLUS_REF'}
FX18 = 0.018                       # JPM 2026: JPY appreciation relative to USD 1.8%/年（common.frames.JPY）
JPM_NEW = {'COMMOD': 4.6, 'REITS': 8.8, 'USCASH': 3.1, 'JPCASH': 1.4}   # 事前登録に書かれた JPM 2026 LTCMA の値（%）


def log(*a):
    print(*a, flush=True)


# ───────────────────────── キャッシュ（既存は読むだけ・書くのはこの道具の置き場だけ） ─────────────────────────
_LAST_YH = [0.0]


def _name_of(url, name):
    return name or hashlib.sha1(url.encode()).hexdigest()[:16] + '_' + url.rstrip('/').split('/')[-1][-60:].replace('%', '_').replace('?', '_').replace('&', '_')


def _fresh(p, days):
    return os.path.exists(p) and time.time() - os.path.getmtime(p) < days * 86400 and os.path.getsize(p) > 0


def _make_get(orig_dir, sub, ua):
    mydir = os.path.join(CDIR, sub)

    def get(url, name=None, max_age_days=30, tries=5):
        nm = _name_of(url, name)
        for d in (orig_dir, mydir):
            p = os.path.join(d, nm)
            if _fresh(p, max_age_days):
                return open(p, 'rb').read()
        os.makedirs(mydir, exist_ok=True)
        p = os.path.join(mydir, nm)
        err = None
        for i in range(tries):
            try:
                if 'finance.yahoo.com' in url:          # 礼儀: Yahoo は 0.35 秒以上あける
                    dt = time.time() - _LAST_YH[0]
                    if dt < 0.35:
                        time.sleep(0.35 - dt)
                    _LAST_YH[0] = time.time()
                b = urllib.request.urlopen(urllib.request.Request(url, headers=ua), timeout=180).read()
                tmp = f'{p}.{os.getpid()}.tmp'
                open(tmp, 'wb').write(b)
                os.replace(tmp, p)
                return b
            except Exception as e:  # noqa
                err = e
                time.sleep(2 ** (i + 1))
        raise RuntimeError(f'取得失敗 {url}: {err}')
    return get


def _make_cached(orig_dir, sub):
    mydir = os.path.join(CDIR, sub)

    def cached(name, url, days=20):
        for d in (orig_dir, mydir):
            p = os.path.join(d, name)
            if _fresh(p, days) and os.path.getsize(p) > 100:
                return open(p, 'rb').read()
        os.makedirs(mydir, exist_ok=True)
        b = G._get(url)
        p = os.path.join(mydir, name)
        open(p + '.part', 'wb').write(b)
        os.replace(p + '.part', p)
        return b
    return cached


_INSTALLED = [False]


def install():
    """M.get・N.get・G._cached を『既存は読むだけ』の版へ。X の写しの置き場をこの道具のキャッシュへ。何度呼んでもよい"""
    if _INSTALLED[0]:
        return
    os.makedirs(CDIR, exist_ok=True)
    M.get = _make_get(M.CACHE, 'mw', M.UA)
    N.get = _make_get(N.CACHE, 'nx', N.UA)
    G._cached = _make_cached(G.CACHE, 'gaps')
    X.CDIR = os.path.join(CDIR, 'R7')
    X.FAKE_BASE = os.path.join(CDIR, 'R7', 'base')
    X.SICF_COPY = os.path.join(CDIR, 'sic_by_cik_copy.json')
    os.makedirs(X.CDIR, exist_ok=True)
    if not os.path.exists(X.SICF_COPY):
        shutil.copyfile(IE.SICF, X.SICF_COPY)
    _INSTALLED[0] = True


def fred_fresh(sid, days=2):
    """FRED の生の CSV（この道具のキャッシュ・2日で取り直す）→ [(日付文字列, 値)]。既存の out/_gaps_cache の古い版は使わない"""
    p = os.path.join(CDIR, 'fred', f'{sid}.csv')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not _fresh(p, days):
        b = G._get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}')
        open(p + '.part', 'wb').write(b)
        os.replace(p + '.part', p)
    out = []
    for line in open(p).read().splitlines()[1:]:
        a = line.split(',')
        if len(a) >= 2 and a[1] not in ('.', ''):
            try:
                out.append((a[0], float(a[1])))
            except ValueError:
                pass
    return out, f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}'


def fred_monthly_last(sid):
    """{yyyymm: 月の最後の観測値}（gaps_common.fred と同じ読み方）"""
    rows, url = fred_fresh(sid)
    out = {}
    for d, v in rows:
        out[int(d[:4]) * 100 + int(d[5:7])] = v
    return out, url


def fred_month_avg(sid, ym):
    rows, url = fred_fresh(sid)
    xs = [v for d, v in rows if int(d[:4]) * 100 + int(d[5:7]) == ym]
    return (sum(xs) / len(xs) if xs else None), len(xs), url


def months_add(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + mo - 1 + k
    return (t // 12) * 100 + t % 12 + 1


def mdiff(a, b):
    return (a // 100 * 12 + a % 100) - (b // 100 * 12 + b % 100)


def yahoo(t):
    """M.yahoo（配当込み・今月を落とす）を 2026-09 で切る"""
    return {k: v for k, v in M.yahoo(t).items() if k <= LAST}


def yahoo_daily_monthend(t):
    """R.gold_futures_monthly と同じ作り（日足の月末の終値・抜けた月をまたがない）。先物の期近（SI=F）用"""
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=946684800&period2={int(time.time())}&interval=1d'
    j = json.loads(M.get(u, name=f'yh_{t.replace("=", "_")}_1d_raw.json', max_age_days=3))
    r = j['chart']['result'][0]
    mon = {}
    for ts, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(ts)
        mon[d.year * 100 + d.month] = c
    now = datetime.datetime.utcnow()
    mon = {k: v for k, v in mon.items() if k < now.year * 100 + now.month}
    ks = sorted(mon)
    return {k: mon[k] / mon[p] - 1 for p, k in zip(ks, ks[1:]) if mdiff(k, p) == 1 and k <= LAST}


def yahoo_divs_ttm(t, end=LAST):
    """直近12か月（end まで）の1株あたりの分配金の合計 ÷ end の月末の終値（M.yahoo と同じ取得の JSON の events から）"""
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    j = json.loads(M.get(u, name=f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json', max_age_days=3))
    r = j['chart']['result'][0]
    off = r.get('meta', {}).get('gmtoffset') or 0
    divs = (r.get('events') or {}).get('dividends') or {}
    lo = months_add(end, -11)
    tot = 0.0
    for d in divs.values():
        dt = datetime.datetime.utcfromtimestamp(d['date'] + off)
        if lo <= dt.year * 100 + dt.month <= end:
            tot += d['amount']
    px = None
    for ts, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
        dt = datetime.datetime.utcfromtimestamp(ts + off)
        if dt.year * 100 + dt.month == end and c:
            px = c
    return (tot / px if px else None), tot, px


# ───────────────────────── 新しい本（R.C と同じ形）─────────────────────────
# kind: sector＝保有を French 49 へ（R の業種の作法）／sector_hand＝米国外を手で（X の HAND と同じ作法）／tbond30／tips／gold_ind／
#       silver／reit／region／ust_hedged／yen_cash／ref_mf／ref_goldplus
NEW = {
    'FBT': dict(ja='米国バイオテクノロジー（NYSE Arca Biotech・30社等分）', veh='FBT', us=True, k=0.10, jpm='USL', kind='sector'),
    'SHLD': dict(ja='防衛テック（世界・Global X）', veh='SHLD', us=True, k=None, jpm='SHLD_MIX', kind='sector_hand'),
    'SHLD_EU': dict(ja='防衛テック（感度 SHLD_EU: 2023-09 以前を ITA 63%＋米国外上位 37%・後知恵）', veh='SHLD', us=True, k=None,
                    jpm='SHLD_MIX', kind='sector_hand', hindsight=True),
    'EDV': dict(ja='米国超長期国債（STRIPS 20〜30年）', veh='EDV', us=False, k=0.10, jpm='USL', kind='tbond30'),
    'TLT': dict(ja='米国長期国債（20年超）', veh='TLT', us=False, k=0.10, jpm='USL', kind='tbond30'),
    'TIP': dict(ja='米国物価連動国債', veh='TIP', us=False, k=0.10, jpm='USL', kind='tips'),
    'GDX': dict(ja='金鉱株', veh='GDX', us=False, k=0.20, jpm='USL', kind='gold_ind'),
    'SLV': dict(ja='銀', veh='SLV', us=False, k=0.0, jpm='COMMOD', kind='silver'),
    'VNQ': dict(ja='米国 REIT', veh='VNQ（楽天の取扱一覧には無い）', us=False, k=0.10, jpm='REITS', kind='reit'),
    'EWY': dict(ja='韓国株', veh='EWY', us=False, k=0.20, jpm='EM', kind='region'),
    'UST_HEDGED_2621': dict(ja='円ヘッジの米国債20年超（東証 2621）', veh='2621（iシェアーズ 米国債20年超 ETF 為替ヘッジあり）', us=False, k=0.0,
                            jpm='USL', kind='ust_hedged', yen=True),
    'YEN_CASH': dict(ja='円の現金（日本の3か月の金利）', veh='普通預金・MMF・個人向け国債の代わり', us=False, k=0.0, jpm='JPCASH', kind='yen_cash', yen=True),
    'MF_REF': dict(ja='参考: 管理先物の代わり（AQR TSMOM＋米国3か月国債）', veh='（楽天で買えない）', us=False, k=0.0, jpm='USCASH', kind='ref_mf', ref=True),
    'GOLDPLUS_REF': dict(ja='参考: NASDAQ100＋金の先物の重ね（Tracers NASDAQ100ゴールドプラスの写し）', veh='（NISA の対象外）', us=False, k=0.10,
                         jpm='USL', kind='ref_goldplus', ref=True),
}
# (主のティッカー, 代理の名前, 代理を使う最後の月)。UNX_SYN_* は合成（M.yahoo の前の一枚が渡す）
NEW_DATA = {
    'FBT': ('FBT', 'UNX_PX_FBT', 200606), 'SHLD': ('SHLD', 'UNX_PX_SHLD', 202309), 'SHLD_EU': ('SHLD', 'UNX_PX_SHLD_EU', 202309),
    'EDV': ('EDV', 'VUSTX', 200712), 'TLT': ('TLT', 'VUSTX', 200207), 'TIP': ('TIP', 'VIPSX', 200312),
    'GDX': ('GDX', 'FSAGX', 200605), 'SLV': ('SLV', 'UNX_PX_SIF', 200604), 'VNQ': ('VNQ', 'VGSIX', 200409), 'EWY': ('EWY', None, None),
    'UST_HEDGED_2621': ('UNX_SYN_UST_HEDGED', None, None), 'YEN_CASH': ('UNX_SYN_YEN_CASH', None, None),
    'MF_REF': ('UNX_SYN_MF', None, None), 'GOLDPLUS_REF': ('UNX_SYN_GOLDPLUS', None, None),
}
PROXY_FORM = {
    'FBT': '^BTK（NYSE Arca Biotechnology の価格指数・配当ほぼ無し）− FBT の経費率/12。^BTK が取れなければ FBIOX（Fidelity Select Biotechnology）',
    'SHLD': 'ITA の系列（R の ITA＝2006-05 以前は FSDAX）',
    'SHLD_EU': 'ITA 63%＋SHLD の今の保有の米国外上位10社（Yahoo で取れる社をその月ごとに等ウェイト・FRED の為替でドル換算）37%（後知恵）',
    'EDV': 'VUSTX（Vanguard Long-Term Treasury・デュレーションが短い＝控えめ）', 'TLT': 'VUSTX', 'TIP': 'VIPSX（Vanguard Inflation-Protected Securities）',
    'GDX': 'FSAGX（Fidelity Select Gold）', 'SLV': 'SI=F（銀の先物の期近・Yahoo の日足の月末の終値＝R の金と同じ作り）',
    'VNQ': 'VGSIX（Vanguard REIT Index）',
}
# SHLD の米国外の保有（out/etf_profiles.json の名前の行）→ French 49業種（会社名から手で・測る前に固定）。None＝割り当てない
HAND_SHLD = {
    'BAE SYSTEMS PLC': 'Aero', 'RHEINMETALL AG': 'Guns', 'THALES': 'Chips', 'LEONARDO SPA': 'Aero', 'SAAB AB': 'Aero',
    'HANWHA AEROSPACE': 'Guns', 'ELBIT SYSTEMS': 'Chips', 'KONGSBERG': 'Guns', 'BABCOCK INTL': 'Ships', 'LIG DEFENSE': 'Guns',
    'HENSOLDT AG': 'Chips', 'KOREA AEROSPACE': 'Aero', 'DASSAULT AVIATION': 'Aero', 'ASELSAN': 'Chips', 'HANWHA SYSTEMS': 'Chips',
    'CSG NV': 'Guns', 'TKMS': 'Ships', 'QINETIQ': 'BusSv', 'CHEMRING': 'Guns', 'BITTIUM': 'Chips', 'EXAIL': 'Chips',
    'KRAKEN ROBOTICS': 'Chips', 'DRONESHIELD': 'Chips', 'ELECTRO OPTIC': 'Guns', 'AUSTAL': 'Ships',
}
SHLD_NONCO = {'CASH', 'EQUITY LONG/SHORT'}           # 会社でない行（現金・スワップ）＝割り当てず、米国／米国外の比からも外す
# SHLD_EU の米国外上位10社（今の保有の重みの順・測る前に固定）: (名前, Yahoo, 通貨, FRED の為替の系列, その系列が『通貨1単位のドル』なら True)
EU_TOP = [('BAE SYSTEMS PLC', 'BA.L', 'GBP', 'DEXUSUK', True), ('RHEINMETALL AG', 'RHM.DE', 'EUR', 'DEXUSEU', True),
          ('THALES', 'HO.PA', 'EUR', 'DEXUSEU', True), ('LEONARDO SPA', 'LDO.MI', 'EUR', 'DEXUSEU', True),
          ('SAAB AB', 'SAAB-B.ST', 'SEK', 'DEXSDUS', False), ('HANWHA AEROSPACE', '012450.KS', 'KRW', 'DEXKOUS', False),
          ('ELBIT SYSTEMS', 'ESLT', 'USD', None, None), ('KONGSBERG', 'KOG.OL', 'NOK', 'DEXNOUS', False),
          ('BABCOCK INTL', 'BAB.L', 'GBP', 'DEXUSUK', True), ('LIG DEFENSE', '079550.KS', 'KRW', 'DEXKOUS', False)]

# 経費率・配当利回りの出どころ（out/etf_forward_profiles.json に無い本）
RAKUTEN_ETFD = 'https://www.rakuten-sec.co.jp/web/market/search/etf_search/ETFD.csv'
VNQ_497K = 'https://www.sec.gov/Archives/edgar/data/734383/000073438326000136/f45323d1.htm'
JITA_TOP = 'https://toushin-lib.fwg.ne.jp/FdsWeb/FDST999900'
DAMODARAN = 'https://pages.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xls'
AQR_TSMOM = 'https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Time-Series-Momentum-Factors-Monthly.xlsx'


def rakuten_er():
    """楽天証券の海外ETF一覧（ETFD.csv）の経費率（%）と分配金利回り（%）。この道具のキャッシュに 2026-10-14 の写し"""
    import csv
    p = os.path.join(CDIR, 'dl', 'ETFD_20261014.csv')
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        b = urllib.request.urlopen(urllib.request.Request(RAKUTEN_ETFD, headers={'User-Agent': 'Mozilla/5.0 (ccf-gate research)'}), timeout=60).read()
        open(p, 'wb').write(b)
    s = open(p, 'rb').read().decode('utf-8-sig')
    out = {}
    for r in csv.reader(s.splitlines()):
        if len(r) > 21 and r[1]:
            try:
                out[r[1]] = dict(er=float(r[5]) / 100 if r[5] else None, dy=float(r[19]) / 100 if r[19] else None, name=r[2], index=r[4], asof=r[21])
            except ValueError:
                continue
    return out, p


# ───────────────────────── Damodaran（年次）─────────────────────────
def damodaran():
    """histretSP.xls の『Returns by year』→ {年: {sp, tbill, tbond, baa, re, gold, cpi}}（小数）。列は見出しの文字で探す（形が変われば止まる）"""
    import xlrd
    b = M.get(DAMODARAN, name='damodaran_histretSP.xls', max_age_days=60)
    wb = xlrd.open_workbook(file_contents=b)
    want = {'sp': ('S&P 500', 'includes dividends'), 'tbill': ('3-month T.Bill',), 'tbond': ('US T. Bond',), 'baa': ('Baa Corporate',),
            're': ('Real Estate',), 'gold': ('Gold',)}
    for sh in wb.sheets():
        for i in range(min(sh.nrows, 40)):
            row = [str(c).strip() for c in sh.row_values(i)]
            if row and row[0] == 'Year' and any('T. Bond' in c or 'T.Bond' in c for c in row):
                cols = {}
                for k, keys in want.items():
                    for j, c in enumerate(row):
                        if all(kk.lower() in c.lower() for kk in keys):
                            cols[k] = j
                            break
                cpi_j = next((j for j, c in enumerate(row) if 'inflation' in c.lower() or c.lower().startswith('cpi')), None)
                out = {}
                for r in range(i + 1, sh.nrows):
                    v = sh.row_values(r)
                    try:
                        y = int(float(v[0]))
                    except (TypeError, ValueError):
                        if out:
                            break
                        continue
                    if not 1900 < y < 2100:
                        if out:
                            break
                        continue
                    d = {}
                    for k, j in cols.items():
                        try:
                            d[k] = float(v[j])
                        except (TypeError, ValueError):
                            d[k] = None
                    if cpi_j is not None:
                        try:
                            d['cpi'] = float(v[cpi_j])
                        except (TypeError, ValueError):
                            d['cpi'] = None
                    out[y] = d
                if len(out) > 50 and {'tbill', 'tbond', 'gold'} <= set(cols):
                    return out, dict(sheet=sh.name, header_row=i, cols={k: row[j] for k, j in cols.items()},
                                     cpi_col=None if cpi_j is None else row[cpi_j], url=DAMODARAN)
    raise SystemExit('Damodaran の表（Year・T. Bond の見出し）が見つからない＝形が変わった')


def damodaran_cpi(d):
    """CPI が同じ表に無ければ、別の表の『Inflation Rate』を探す（無ければ FRED CPIAUCNS の12月どうし）"""
    if all(d[y].get('cpi') is not None for y in d):
        return {y: d[y]['cpi'] for y in d}, 'Damodaran の同じ表の列'
    cpi, url = fred_monthly_last('CPIAUCNS')
    out = {}
    for y in d:
        a, b = cpi.get((y - 1) * 100 + 12), cpi.get(y * 100 + 12)
        if a and b:
            out[y] = b / a - 1
    return out, f'FRED CPIAUCNS の12月どうし（{url}）'


def real_geo(nom, cpi, y0=1928, y1=2025):
    ys = [y for y in range(y0, y1 + 1) if nom.get(y) is not None and cpi.get(y) is not None]
    lg = sum(math.log((1 + nom[y]) / (1 + cpi[y])) for y in ys)
    return math.exp(lg / len(ys)) - 1, ys[0], ys[-1], len(ys)


# ───────────────────────── 2621 の基準価額（投資信託協会）─────────────────────────
def jita_2621():
    """投資信託協会 投信総合検索ライブラリーで 2621 を探し、基準価額（分配金は再投資）の月末 → 月次リターン。取れなければ None"""
    p = os.path.join(CDIR, 'jita_2621.json')
    if _fresh(p, 7):
        return json.load(open(p))
    try:
        from fetch_tsumitate_funds import Lib, BASE as TLB
        lib = Lib()
        hits = lib.search('米国債20年超')
        cand = [h for h in hits if '為替ヘッジあり' in (h.get('fundNm') or '') and 'iシェアーズ' in (h.get('fundNm') or '').replace('ｉ', 'i')]
        if not cand:
            cand = [h for h in hits if '為替ヘッジあり' in (h.get('fundNm') or '') and '20年超' in (h.get('fundNm') or '')]
        if len(cand) != 1:
            return dict(ok=False, reason=f'一意に定まらない（{[h.get("fundNm") for h in cand][:5]}）', hits=[h.get('fundNm') for h in hits][:10])
        h = cand[0]
        url = (TLB + '/FdsWeb/FDST030000/csv-file-download?' + urllib.parse.urlencode({'isinCd': h['isinCd'], 'associFundCd': h['associFundCd']}))
        time.sleep(0.5)
        b = lib.op.open(url, timeout=60).read()
        try:
            s = b.decode('utf-8')
        except UnicodeDecodeError:
            s = b.decode('cp932')
        import csv
        rows = list(csv.reader(io.StringIO(s)))
        hdr = rows[0]
        if len(hdr) < 4 or '年月日' not in hdr[0] or '基準価額' not in hdr[1] or '分配金' not in hdr[3]:
            return dict(ok=False, reason=f'CSV の見出しが想定と違う {hdr[:5]}')
        pts = []
        for r in rows[1:]:
            mm = re.match(r'\s*(\d{4})年(\d{1,2})月(\d{1,2})日', r[0]) if r else None
            if not mm:
                continue
            nav = float(r[1].replace(',', ''))
            dist = float(r[3].replace(',', '')) if len(r) > 3 and r[3].strip() else 0.0
            pts.append((int(mm.group(1)) * 10000 + int(mm.group(2)) * 100 + int(mm.group(3)), nav, dist))
        pts.sort()
        tr, prev, mon = None, None, {}
        for d, nav, dist in pts:
            tr = nav if tr is None else tr * (nav + dist) / prev
            prev = nav
            mon[d // 100] = tr
        ks = sorted(mon)
        ret = {str(k): mon[k] / mon[pq] - 1 for pq, k in zip(ks, ks[1:]) if mdiff(k, pq) == 1 and k <= LAST}
        out = dict(ok=True, fundNm=h.get('fundNm'), isinCd=h['isinCd'], associFundCd=h['associFundCd'],
                   trustReward=h.get('trustReward'), setDate=h.get('setDate') or h.get('establishedDate'), url=url,
                   first_day=pts[0][0], last_day=pts[-1][0], monthly=ret, dist_total=sum(x[2] for x in pts))
        json.dump(out, open(p, 'w'), ensure_ascii=False)
        return out
    except Exception as e:  # noqa
        return dict(ok=False, reason=f'取得失敗 {e}')


# ───────────────────────── AQR TSMOM ─────────────────────────
def aqr_tsmom():
    """nx_stack_data.aqr_generic と同じ読み方（N.get はこの道具のキャッシュへ）→ {yyyymm: TSMOM の月次（超過・小数）}"""
    import nx_stack_data as D
    d, h = D.aqr_generic('Time-Series-Momentum-Factors-Monthly', 'TSMOM Factors',
                         lambda r: r and len(r) > 1 and r[1] is not None and str(r[1]).strip() == 'TSMOM')
    return d['TSMOM'], h


# ───────────────────────── 日本の3か月の金利（穴は理由つきで埋める）─────────────────────────
def jp3m():
    """IR3TIB01JPM156N（%・月次）。無い月はコール（IRSTCI01JPM156N）・両方無い末尾の月は直前の値（理由を返す）"""
    a, ua = fred_monthly_last('IR3TIB01JPM156N')
    c, uc = fred_monthly_last('IRSTCI01JPM156N')
    tb, ut = fred_monthly_last('TB3MS')
    out, filled = {}, {'コール（IRSTCI01JPM156N）で代えた月': [], '直前の値を持ち越した月': []}
    last_v = None
    for m in R.months(199912, LAST):
        if m in a:
            out[m] = a[m]
        elif m in c:
            out[m] = c[m]; filled['コール（IRSTCI01JPM156N）で代えた月'].append(m)
        elif last_v is not None and m > max(a):
            out[m] = last_v; filled['直前の値を持ち越した月'].append(m)
        else:
            continue
        last_v = out[m]
    info = dict(IR3TIB01JPM156N=dict(url=ua, first=min(a), last=max(a)), IRSTCI01JPM156N=dict(url=uc, first=min(c), last=max(c)),
                TB3MS=dict(url=ut, first=min(tb), last=max(tb)), filled=filled)
    return out, tb, info


# ───────────────────────── 代理・合成の系列 ─────────────────────────
def splice(real, proxy, last):
    """R.build_chains と同じつなぎ（k≦last は代理・代理に無い k≦last の本物は捨てる）"""
    r = dict(real)
    for k, v in proxy.items():
        if k <= last:
            r[k] = v
    for k in [k for k in r if k <= last and k not in proxy]:
        del r[k]
    return {k: v for k, v in r.items() if k <= LAST}


def gate_one(c, real, proxy, last, form):
    """X.gate と同じ式（重なる月＝代理を使う最後の月より後・本物の最初の月が最後の月の翌月か）"""
    ov = sorted(k for k in real if k in proxy and k > last)
    first_main = min(real)
    cont = mdiff(first_main, last) == 1
    if len(ov) < MIN_OVERLAP:
        return dict(proxy_form=form, until=last, first_real_month=first_main, overlap_months=len(ov), corr=None, used=False,
                    reason='重なる月が24か月未満＝代理を使わない')
    cr = M.corr([real[k] for k in ov], [proxy[k] for k in ov])
    g_m, g_p = R.geo(real, ov), R.geo(proxy, ov)
    te = S.pstdev([real[k] - proxy[k] for k in ov]) * math.sqrt(12)
    return dict(proxy_form=form, until=last, first_real_month=first_main, continuous=cont, overlap=f'{ov[0]}〜{ov[-1]}',
                overlap_months=len(ov), corr=round(cr, 4), geo_main=round(100 * g_m, 2), geo_proxy=round(100 * g_p, 2),
                gap=round(100 * (g_m - g_p), 2), tracking_error=round(100 * te, 2), used=bool(cr >= GATE and cont),
                reason=('相関 ≥ 0.90＝代理を使う' if cr >= GATE else f'相関 {cr:.3f} < 0.90＝代理を使わない（common.proxy_gate）')
                + ('' if cont else '・本物の最初の月が代理の最後の月の翌月でない'))


def eu_basket():
    """SHLD_EU の米国外上位10社: その月に値のある社の等ウェイト（ドル換算）→ ({月: リターン}, 社ごとの最初の月)"""
    fx = {}
    rets, first = {}, {}
    for nm, yt, cur, sid, usd_per in EU_TOP:
        try:
            loc = yahoo(yt)
        except Exception as e:  # noqa
            first[nm] = dict(yahoo=yt, error=str(e)[:120])
            continue
        if not loc:
            first[nm] = dict(yahoo=yt, error='値なし')
            continue
        if sid:
            if sid not in fx:
                fx[sid], _ = fred_monthly_last(sid)
            f = fx[sid]
            rr = {}
            for m, v in loc.items():
                p = months_add(m, -1)
                if m in f and p in f:
                    ratio = (f[m] / f[p]) if usd_per else (f[p] / f[m])
                    rr[m] = (1 + v) * ratio - 1
        else:
            rr = dict(loc)
        rets[nm] = rr
        first[nm] = dict(yahoo=yt, currency=cur, fred=sid, first=min(rr) if rr else None, months=len(rr))
    out = {}
    for m in R.months(199001, LAST):
        xs = [r[m] for r in rets.values() if m in r]
        if xs:
            out[m] = sum(xs) / len(xs)
    return out, first


# ───────────────────────── 世界B・C（新しい本）─────────────────────────
def hold_t_new():
    """FBT・SHLD の保有（out/etf_profiles.json）。SHLD の米国外の名前の行は '*名前' に（X の作法）、現金・スワップは外す"""
    prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']
    out, s_us = {}, None
    out['FBT'] = [(h[0], h[1]) for h in prof_old['FBT']['h']]
    hs, us_w, fo_w = [], 0.0, 0.0
    for t, w in prof_old['SHLD']['h']:
        if t in SHLD_NONCO:
            continue
        if t in HAND_SHLD:
            hs.append(('*' + t, w)); fo_w += w
        else:
            hs.append((t, w)); us_w += w
    out['SHLD'] = hs
    out['SHLD_EU'] = hs
    s_us = us_w / (us_w + fo_w)
    return out, s_us, us_w, fo_w


def mapper(tickers):
    """X.mapper の写し（手の割り当ては SHLD の米国外）"""
    with X.sec_env():
        sic = IE.sic_lookup(tickers)
    f49 = ff49_map()

    def ind_of(t, c=None):
        if t.startswith('*'):
            return HAND_SHLD.get(t[1:]) if c in ('SHLD', 'SHLD_EU') else X.HAND.get(t[1:]) if c == 'GRID' else None
        s = sic.get(t.upper(), (None,))[0]
        if s is None:
            return None
        k = f49(s)
        return IE.FRENCH_LIKE.get(t.upper(), (k,))[0]
    return ind_of, sic


def world_fns_new(bi, expo, xb, xjpm, tb, consts):
    """新しい本の世界B・C（費用・税の前）。既存の本は X.world_fns（R の写し）をそのまま返す。
    consts: tbond_B（T-bond の100年の実質⊗インフレ）・y30・dfii10・tbill_B（参考の現金）"""
    X_ind, X_raw = bi['X_ind'], bi['X_ind_raw']

    def world_b(c, shrink=R.SHRINK, raw=False):
        if c not in NEW:
            return xb(c, shrink, raw)
        k = NEW[c]['kind']
        if k in ('sector', 'sector_hand'):
            x = (expo.get(c) or {}).get('X_ind_raw' if raw else 'X_ind') or 0.0
            e = (expo.get(c) or {}).get('e')
            if e is None:
                e = R.E_MKT
            rec = R.REC_A - R.REC_B * e
            return R.R_EQ + shrink * x + rec, x, rec, '49業種の長い歴史の上乗せを保有で重み付け' + ('（米国外は手で業種）' if k == 'sector_hand' else '')
        if k == 'gold_ind':
            src = X_raw if raw else X_ind
            x = src['Gold']['x'] if 'Gold' in src else 0.0
            return R.R_EQ + shrink * x, x, 0.0, 'R株＋French 49 の Gold 業種の上乗せ（R の業種の作法・米国外の保有が大半＝REC なし）' + ('' if 'Gold' in src else '（Gold は時価総額の下限を満たす月が240に届かず上乗せ0＝R の作法）')
        if k in ('tbond30', 'tips'):
            return consts['tbond_B'], 0.0, 0.0, 'Damodaran の T-bond（10年）1928〜2025 の実質の幾何平均＋インフレ2.5%'
        if k == 'ust_hedged':
            return consts['tbond_B'] - consts['hedge_gap'], 0.0, 0.0, 'T-bond の B −（JPM U.S. Cash 3.1 − JPM 日本短期金利 1.4）＝円'
        if k == 'silver':
            return R.R_GOLD, 0.0, 0.0, 'R_GOLD（貴金属の長期実質1.3%＋インフレ）'
        if k in ('reit', 'region'):
            return R.R_EQ, 0.0, 0.0, 'R株（上乗せなし）'
        if k == 'yen_cash':
            return JPM_NEW['JPCASH'] / 100, 0.0, 0.0, 'JPM 日本短期金利 1.4（100年の値は持たない）'
        if k == 'ref_mf':
            return consts['tbill_B'], 0.0, 0.0, '参考（事前登録に世界の式が無い）: 上乗せ0＝Damodaran の T-bill の実質＋インフレ2.5%'
        if k == 'ref_goldplus':
            q = xb('QQQM', shrink, raw)[0]
            return q + (R.R_GOLD - consts['tbill_B']), 0.0, 0.0, '参考: QQQM の B＋(金の B − T-bill の B)'
        raise KeyError(c)

    def jpm_c(c, b, h=R.H):
        if c not in NEW:
            return xjpm(c, b, h)
        k = NEW[c]['kind']
        if k == 'tbond30':
            return (15 * consts['y30'] / 100 + (h - 15) * b) / h
        if k == 'tips':
            return (15 * (consts['dfii10'] + 2.5) / 100 + (h - 15) * b) / h
        if k == 'ust_hedged':
            return (15 * consts['y30'] / 100 + (h - 15) * consts['tbond_B']) / h - consts['hedge_gap']
        if k == 'yen_cash':
            return JPM_NEW['JPCASH'] / 100
        if k == 'ref_mf':
            return JPM_NEW['USCASH'] / 100
        if k == 'ref_goldplus':
            qb = xb('QQQM')[0]
            return xjpm('QQQM', qb, h) + (xjpm('GLDM', R.R_GOLD, h) - JPM_NEW['USCASH'] / 100)
        return (R.H_JPM * R.JPM[R.JPM_MAP[c]] / 100 + (h - R.H_JPM) * b) / h
    return world_b, jpm_c


# ───────────────────────── 組み立て ─────────────────────────
@contextmanager
def swap_R(cands):
    """R.C・R.DATA を一時的に『R の25本＋新しい本』へ（R7 の本を外す）。終われば元へ戻す"""
    oc, od, ob, oo, oy = R.C, R.DATA, R.BASE, R.OUT, M.yahoo
    try:
        yield oc, od, ob, oy
    finally:
        R.C, R.DATA, R.BASE, R.OUT, M.yahoo = oc, od, ob, oo, oy


_STATE = {}


def build():
    """→ dict(rows, chains, info)。rows・chains は X の32本＋新しい本（代理の門を通らない本は入れない）"""
    if 'res' in _STATE:
        return _STATE['res']
    install()
    t0 = time.time()
    log('① X.rank_result()（R の25本＋R7）')
    base = X.rank_result()
    rows0, chains0 = base['rows'], base['chains']
    r25 = [c for c in rows0 if not rows0[c].get('r7_new')]
    log('  ', len(rows0), '本（R の本', len(r25), '）', f'{time.time() - t0:.0f}秒')

    # ── 費用（新しい本）──
    rk, rk_path = rakuten_er()
    prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']
    pn = json.load(open(os.path.join(BASE, 'out', 'etf_forward_profiles.json')))
    costs, add = {}, {}
    for c in ('EDV', 'TLT', 'TIP', 'GDX', 'SLV', 'VNQ', 'EWY'):
        dy, dtot, px = yahoo_divs_ttm(c)
        er = (rk.get(c) or {}).get('er')
        src = f'楽天証券 ETFD.csv（{RAKUTEN_ETFD}・{(rk.get(c) or {}).get("asof")}）の経費率'
        if c == 'VNQ':
            er, src = 0.0013, f'Vanguard Real Estate ETF Summary Prospectus（497K・2026-05-28）Total Annual Fund Operating Expenses 0.13%（{VNQ_497K}）'
        if er is None:
            raise SystemExit(f'{c}: 経費率が取れない')
        costs[c] = dict(er=er, er_src=src, dy=dy, dy_src=f'Yahoo の分配金（2025-10〜2026-09 の合計 {dtot:.4f}）÷ 2026-09 末の終値 {px}',
                        dy_rakuten=(rk.get(c) or {}).get('dy'), er_rakuten=(rk.get(c) or {}).get('er'))
        add[c] = dict(er=er, dy=dy or 0.0, holdings=[], src='unx: ' + src)
    j2621 = jita_2621()
    er2621 = None
    if j2621.get('ok') and j2621.get('trustReward') not in (None, ''):
        er2621 = round(float(j2621['trustReward']) * 1.1 / 100, 6)       # 投信ライブラリーの信託報酬は税抜 → 税込
    if er2621 is None:
        er2621 = 0.00154
        costs['UST_HEDGED_2621'] = dict(er=er2621, er_src='JPX の ETF 一覧の 0.14%（税抜）×1.1（投信ライブラリーから取れなかった）')
    else:
        costs['UST_HEDGED_2621'] = dict(er=er2621, er_src=f'投資信託協会 投信総合検索ライブラリー trustReward {j2621["trustReward"]}%（税抜）×1.1')
    tlt_er = costs['TLT']['er']
    add['UNX_SYN_UST_HEDGED'] = dict(er=tlt_er, dy=0.0, holdings=[], src='unx: 合成（データの器は TLT＝TLT の経費率）')
    add['UST_HEDGED_2621'] = dict(er=er2621, dy=0.0, holdings=[], src='unx: ' + costs['UST_HEDGED_2621']['er_src'])
    for nm in ('UNX_SYN_YEN_CASH', 'YEN_CASH', 'UNX_SYN_MF', 'MF_REF'):
        add[nm] = dict(er=0.0, dy=0.0, holdings=[], src='unx: 費用0（現金・紙の上の参考）')
    qer = (pn['etfs'].get('QQQ') or prof_old.get('QQQ') or {}).get('er') or 0.0018
    qdy = (pn['etfs'].get('QQQ') or prof_old.get('QQQ') or {}).get('dy') or 0.0044
    for nm in ('UNX_SYN_GOLDPLUS', 'GOLDPLUS_REF'):
        add[nm] = dict(er=qer, dy=qdy, holdings=[], src='unx: 参考＝データの器 QQQ の経費率・配当利回りのまま（実物の信託報酬は確かめていない）')
    for c in ('FBT', 'SHLD'):
        costs[c] = dict(er=prof_old[c]['er'], dy=prof_old[c]['dy'], er_src=f'out/etf_profiles.json（{prof_old[c].get("asof")}）',
                        er_rakuten=(rk.get(c) or {}).get('er'))
    costs['SHLD_EU'] = dict(costs['SHLD'])
    add['SHLD_EU'] = dict(er=prof_old['SHLD']['er'], dy=prof_old['SHLD']['dy'], holdings=[[t, w] for t, w in prof_old['SHLD']['h']],
                          src='unx: out/etf_profiles.json の SHLD の写し')

    # ── 系列 ──
    log('② 系列を集める')
    raw = {}
    for t in ('FBT', 'SHLD', 'EDV', 'TLT', 'TIP', 'GDX', 'SLV', 'VNQ', 'EWY', 'VUSTX', 'VIPSX', 'FSAGX', 'VGSIX', 'FBIOX'):
        raw[t] = yahoo(t)
    btk_note = None
    try:
        raw['^BTK'] = yahoo('^BTK')
    except Exception as e:  # noqa
        raw['^BTK'] = {}
        btk_note = f'^BTK 取得失敗 {str(e)[:100]}'
    raw['SI=F'] = yahoo_daily_monthend('SI=F')
    jp, tb, jp_info = jp3m()
    tsm, tsm_sha = aqr_tsmom()
    eu, eu_first = eu_basket()
    fer = costs['FBT']['er']
    px = {}
    if raw['^BTK'] and min(raw['^BTK']) <= R.A1[0] and max(raw['^BTK']) >= 200901:
        px['UNX_PX_FBT'] = {k: v - fer / 12 for k, v in raw['^BTK'].items()}
        fbt_proxy = '^BTK − FBT の経費率/12'
    else:
        px['UNX_PX_FBT'] = dict(raw['FBIOX'])
        fbt_proxy = 'FBIOX（^BTK が取れない・2000-09 まで届かない）' + (f'・{btk_note}' if btk_note else '')
    px['UNX_PX_SHLD'] = dict(chains0['ITA'])
    px['UNX_PX_SHLD_EU'] = {m: 0.63 * chains0['ITA'][m] + 0.37 * eu[m] for m in chains0['ITA'] if m in eu}
    for t in ('VUSTX', 'VIPSX', 'FSAGX', 'VGSIX'):
        px[t] = dict(raw[t])
    px['UNX_PX_SIF'] = dict(raw['SI=F'])

    # 代理の門（本物の最初の月が最後の月の翌月でなければ、代理の最後の月を本物の前の月まで延ばす＝記録する）
    gates, deviations, data, gate_failed_kept = {}, [], {}, {}
    for c, (main, proxy, last) in NEW_DATA.items():
        if not proxy:
            data[c] = (main, None, None)
            continue
        real = raw[main] if main in raw else yahoo(main)
        p = px[proxy]
        first = min(real)
        if mdiff(first, last) > 1:
            deviations.append(f'{c}: 事前登録の代理の最後の月 {last} の翌月に本物の値が無い（本物の最初の月 {first}）＝代理を {months_add(first, -1)} まで延ばした')
            last = months_add(first, -1)
        g = gate_one(c, real, p, last, PROXY_FORM[c] if c != 'FBT' else fbt_proxy)
        gates[c] = g
        if g['used']:
            data[c] = (main, proxy, last)
        elif c in GATE_FAILED_KEEP:
            data[c] = (main, proxy, last)          # 門を通らないが、今の配分（F_now）の形を作る代わりとして残す（出力で名指し）
            gate_failed_kept[c] = g['reason']
    excluded = {c: gates[c]['reason'] for c in gates if not gates[c]['used'] and c not in GATE_FAILED_KEEP}
    log('  代理の門', {c: (g['corr'], g['used']) for c, g in gates.items()})

    # 合成の系列（TLT のつなぎを使う本は TLT の門に従う）
    tlt_ok = 'TLT' in data
    tlt_chain = splice(raw['TLT'], px['VUSTX'], data['TLT'][2]) if tlt_ok else None
    syn = {}
    if tlt_ok:
        syn['UNX_SYN_UST_HEDGED'] = {m: tlt_chain[m] - (tb[m] - jp[m]) / 1200 for m in tlt_chain if m in tb and m in jp}
    syn['UNX_SYN_YEN_CASH'] = {m: jp[m] / 1200 for m in jp if m <= LAST}
    syn['UNX_SYN_MF'] = {m: tsm[m] + tb[m] / 1200 for m in tsm if m in tb and m <= LAST}
    syn['UNX_SYN_GOLDPLUS'] = {m: chains0['QQQM'][m] + (chains0['GLDM'][m] - tb[m] / 1200) for m in chains0['QQQM']
                               if m in chains0['GLDM'] and m in tb and m <= LAST}
    if not tlt_ok:
        excluded['UST_HEDGED_2621'] = 'TLT の代理（VUSTX）が門を通らない＝合成できない'
        data.pop('UST_HEDGED_2621', None)
    # 2621 の門（合成 対 実物の基準価額）
    g2621 = None
    if tlt_ok:
        if j2621.get('ok'):
            realj = {int(k): v for k, v in j2621['monthly'].items()}
            synj = syn['UNX_SYN_UST_HEDGED']
            ov = sorted(k for k in realj if k in synj)
            if len(ov) >= MIN_OVERLAP:
                cr = M.corr([realj[k] for k in ov], [synj[k] for k in ov])
                g2621 = dict(real=f'2621 の基準価額（分配金を再投資）{j2621["fundNm"]}', overlap=f'{ov[0]}〜{ov[-1]}', overlap_months=len(ov),
                             corr=round(cr, 4), geo_real=round(100 * R.geo(realj, ov), 2), geo_synthetic=round(100 * R.geo(synj, ov), 2),
                             used=bool(cr >= GATE), reason='相関 ≥ 0.90＝合成を使う' if cr >= GATE else f'相関 {cr:.3f} < 0.90＝合成を使わない')
            else:
                g2621 = dict(used=False, reason=f'重なる月が {len(ov)}（24未満）')
        else:
            g2621 = dict(used=False, reason='実物の基準価額が取れない: ' + str(j2621.get('reason')))
        gates['UST_HEDGED_2621'] = g2621
        if not g2621['used']:
            excluded['UST_HEDGED_2621'] = g2621['reason']
            data.pop('UST_HEDGED_2621', None)
    # 合成の本が A1 の窓をそろえるか
    k1 = R.months(*R.A1)
    syn_cover, ref_trunc = {}, {}
    for c in ('UST_HEDGED_2621', 'YEN_CASH', 'MF_REF', 'GOLDPLUS_REF'):
        if c not in data:
            continue
        s = syn[data[c][0]]
        miss = [m for m in k1 if m not in s]
        syn_cover[c] = dict(first=min(s), last=max(s), A1_missing=len(miss), first_missing=miss[:5], last_missing=miss[-5:])
        if miss and c not in REF_ASSETS:
            excluded[c] = f'A1 の毎月の値が {len(miss)} か月欠ける'
            data.pop(c)
        elif miss:
            ref_trunc[c] = max(s)                  # 参考の本: 末尾が欠ける＝R へ入れず、窓を最後の月までに縮めて別に測る（0 で埋めない）
            data.pop(c)

    # ── 中身の写し（新しい本を足す）・R へ足して回す ──
    log('③ R.main（R の25本＋新しい本）')
    fake = os.path.join(CDIR, 'base')
    od = os.path.join(fake, 'out')
    os.makedirs(od, exist_ok=True)
    shutil.copyfile(os.path.join(BASE, 'out', 'etf_profiles.json'), os.path.join(od, 'etf_profiles.json'))
    pn2 = copy.deepcopy(pn)
    clash = [t for t in add if t in pn2['etfs']]
    assert not clash, f'既存の中身と名前がぶつかる: {clash}'
    pn2['etfs'].update(add)
    pn2['note_unx'] = 'unx（night/unx_assets.py）の写し。新しい本を足しただけ。正本は out/etf_forward_profiles.json'
    json.dump(pn2, open(os.path.join(od, 'etf_forward_profiles.json'), 'w'), ensure_ascii=False, indent=1)
    hold, s_us, us_w, fo_w = hold_t_new()
    meta = {c: copy.deepcopy(NEW[c]) for c in data}
    for c in ('SHLD', 'SHLD_EU'):
        if c in meta:
            meta[c]['k'] = s_us * 0.10 + (1 - s_us) * 0.20
    new_keys = list(data)
    for c in new_keys:
        assert c not in rows0, f'{c} は既に X の結果にある'
    jpm_add = dict(JPM_NEW)
    jpm_add['SHLD_MIX'] = s_us * R.JPM['USL'] + (1 - s_us) * R.JPM['EAFE']
    for k, v in jpm_add.items():
        assert R.JPM.get(k, v) == v, f'R.JPM[{k}] が既にあり値が違う'
        R.JPM[k] = v
    with swap_R(new_keys) as (oc, odd, ob, oy):
        R.C = {c: oc[c] for c in r25}
        R.DATA = {c: odd[c] for c in r25}
        for c in new_keys:
            m = meta[c]
            R.C[c] = dict(ja=m['ja'], veh=m['veh'], us=m['us'], k=m['k'])
            R.DATA[c] = data[c]
            R.JPM_MAP[c] = m['jpm']
            R.GMO_MAP[c] = None
            R.VG_MAP[c] = None
        allpx = dict(px, **syn)

        def yh(t, *a, **k):
            if t in allpx:
                return dict(allpx[t])
            return oy(t, *a, **k)
        R.BASE, R.OUT, M.yahoo = fake, os.path.join(CDIR, 'etf_forward_rank_SHOULD_NOT_BE_WRITTEN.json'), yh
        with X.sec_env():
            ext = R.main(write=False)
    rows2, chains2 = ext['rows'], ext['chains']
    log('  ', f'{time.time() - t0:.0f}秒')

    # ── 回帰①: 2回目の R.main の25本が X の結果と1ビットも違わないか ──
    rank_keys = {'rank', 'score', 'worst', 'top10_in_worlds'}
    bad = []
    for c in r25:
        for k, v in X.numeric_fields(rows0[c]).items():
            if k in rank_keys:
                continue
            if rows2[c].get(k) != v:
                bad.append((c, k, v, rows2[c].get(k)))
        if chains2[c] != chains0[c]:
            bad.append((c, 'chain'))
    reg1 = dict(rows=len(r25), mismatches=len(bad), first=bad[:10], ok=not bad)
    if bad:
        raise SystemExit(f'回帰①に失敗: 2回目の R.main の既存の本が X と違う {bad[:5]}')

    # ── 世界B・C（写し）＋回帰②（既存25本で 1e-12）──
    log('④ 世界B・C（写し）')
    bi = X.b_inputs()
    prof_n2 = pn2['etfs']
    hold_all = {}
    for c in r25:
        if not oc[c]['us'] or c == 'VOO':
            continue
        h = R.holdings_of(c, prof_old, prof_n2)
        if c == 'QQQM':
            h = R.holdings_of('QQQM', prof_old, prof_n2) or R.holdings_of('QQQ', prof_old, prof_n2)
        hold_all[c] = h
    for c in ('FBT', 'SHLD', 'SHLD_EU'):
        if c in data:
            hold_all[c] = hold[c]
    tickers = {t.upper() for h in hold_all.values() for t, _ in h if not t.startswith('*')}
    ind_of, sic = mapper(tickers)
    expo = X.expo_of(list(hold_all), hold_all, ind_of, bi)
    xb, xjpm, _, _ = X.world_fns(bi, expo)
    dmd, dmd_info = damodaran()
    cpi, cpi_src = damodaran_cpi(dmd)
    tb_real, y0, y1, ny = real_geo({y: dmd[y]['tbond'] for y in dmd}, cpi)
    bill_real, _, _, _ = real_geo({y: dmd[y]['tbill'] for y in dmd}, cpi)
    y30, n30, u30 = fred_month_avg('DGS30', 202609)
    dfii, ndf, udf = fred_month_avg('DFII10', 202609)
    consts = dict(tbond_B=(1 + tb_real) * (1 + INFL) - 1, tbill_B=(1 + bill_real) * (1 + INFL) - 1, y30=y30, dfii10=dfii,
                  hedge_gap=(JPM_NEW['USCASH'] - JPM_NEW['JPCASH']) / 100)
    world_b, jpm_c = world_fns_new(bi, expo, xb, xjpm, None, consts)
    _, _, xgmo, xvg = X.world_fns(bi, expo)
    rep = {}
    for c in r25:
        v = X.b_values(c, rows2[c], world_b, jpm_c, xgmo, xvg)
        rep[c] = max(abs(v[k] - rows2[c][k]) for k in X.BKEYS)
    rep_max = max(rep.values())
    reg2 = dict(keys=X.BKEYS, max_abs_diff=rep_max, tol=1e-12, ok=rep_max <= 1e-12)
    if rep_max > 1e-12:
        raise SystemExit(f'回帰②に失敗: 世界Bの写しが R と合わない（{rep_max}）')
    for c in new_keys:
        r = rows2[c]
        er_v, tax = r['er_vehicle'], r['tax_drag']
        b, x, rec, src = world_b(c)
        upd = dict(B_gross=b, B_X=x, B_rec=rec, B_src=src, C_gross=jpm_c(c, b), B=b - er_v - tax, C=jpm_c(c, b) - er_v - tax,
                   _b03=world_b(c, 0.3)[0] - er_v - tax, _b07=world_b(c, 0.7)[0] - er_v - tax,
                   _c03=jpm_c(c, world_b(c, 0.3)[0]) - er_v - tax, _c07=jpm_c(c, world_b(c, 0.7)[0]) - er_v - tax,
                   _c_h30=jpm_c(c, b, 30) - er_v - tax)
        braw = world_b(c, raw=True)[0]
        upd.update(_b_raw=braw - er_v - tax, _c_raw=jpm_c(c, braw) - er_v - tax, B_X_raw=world_b(c, raw=True)[1])
        upd['_c_gmo'] = upd['C']; upd['_c_vg'] = upd['C']
        r.update(upd)
        if c in expo:
            r['record_share_e'] = expo[c]['e']; r['holdings_coverage'] = expo[c]['coverage']; r['top_industries'] = expo[c]['top_industries']
        r['unx_new'] = True
        r['kind'] = NEW[c]['kind']
        r['yen'] = c in YEN_ASSETS
    # D: 参考の GOLDPLUS は QQQM の D＋(金の C − 現金)（金に D は無い＝C）。他の新しい本は load_D が C で代える
    if 'GOLDPLUS_REF' in rows2:
        import bestpf_eval as E
        Dq, _, _ = E.load_D(rows0, ['QQQM'])
        rows2['GOLDPLUS_REF']['D_override'] = Dq['QQQM'] + (xjpm('GLDM', R.R_GOLD) - JPM_NEW['USCASH'] / 100)
        # GOLDPLUS の B・C は QQQM の正味＋金の超過（費用は QQQM の器のまま）
        rows2['GOLDPLUS_REF']['B'] = rows0['QQQM']['B'] + (R.R_GOLD - consts['tbill_B'])
        rows2['GOLDPLUS_REF']['C'] = rows0['QQQM']['C'] + (xjpm('GLDM', R.R_GOLD) - JPM_NEW['USCASH'] / 100)

    rows = dict(rows0)
    chains = dict(chains0)
    for c in new_keys:
        rows[c] = rows2[c]
        chains[c] = chains2[c]
    for c, lastm in ref_trunc.items():             # 参考の本（末尾が欠ける）: 費用0・紙の上・B・C・D は world_fns_new の式
        b = world_b(c)[0]
        cc = jpm_c(c, b)
        rows[c] = dict(ja=NEW[c]['ja'], vehicle=NEW[c]['veh'], A1_gross=0.0, A1=0.0, A2_gross=0.0, A2=0.0, er_vehicle=0.0, er_data=0.0,
                       dy_vehicle=0.0, tax_drag=0.0, B=b, C=cc, B_gross=b, C_gross=cc, B_src=world_b(c)[3], D_override=cc,
                       unx_new=True, kind=NEW[c]['kind'], yen=False, trunc_to=lastm,
                       A1_note=f'系列が {lastm} で終わる＝A1・A2 の窓を {lastm} までに縮めて別に測る（A1・A2 の値は窓ごとに measure が出す）')
        chains[c] = dict(syn[NEW_DATA[c][0]])
        new_keys.append(c)
    info = dict(
        secs=round(time.time() - t0), gates=gates, excluded=excluded, gate_failed_kept=gate_failed_kept, ref_trunc=ref_trunc,
        deviations=deviations, data={c: list(v) for c, v in data.items()},
        fbt_proxy=fbt_proxy, costs=costs, rakuten_csv=rk_path, jita_2621={k: v for k, v in j2621.items() if k != 'monthly'},
        jp3m=jp_info, tsmom=dict(sha1=tsm_sha, first=min(tsm), last=max(tsm), url=AQR_TSMOM), syn_cover=syn_cover,
        shld=dict(us_share=round(s_us, 4), us_w=round(us_w, 4), foreign_w=round(fo_w, 4), hand=HAND_SHLD,
                  k=round(s_us * 0.10 + (1 - s_us) * 0.20, 4), jpm_c=round(jpm_add['SHLD_MIX'], 3)),
        eu_basket=eu_first,
        consts=dict(tbond_real_geo=round(100 * tb_real, 3), tbill_real_geo=round(100 * bill_real, 3), years=f'{y0}〜{y1}（{ny}年）',
                    tbond_B=round(100 * consts['tbond_B'], 3), tbill_B=round(100 * consts['tbill_B'], 3),
                    DGS30_2026_09_avg=round(y30, 4), DGS30_days=n30, DGS30_url=u30, DFII10_2026_09_avg=round(dfii, 4), DFII10_days=ndf, DFII10_url=udf,
                    hedge_gap=consts['hedge_gap'], damodaran=dmd_info, cpi_src=cpi_src),
        regression={'①_2回目のR.mainの25本_と_X.rank_result（1ビット）': reg1, '②_世界B・Cの写し_と_R.main（25本・1e-12）': reg2},
        expo_new={c: {k: expo[c][k] for k in ('e', 'X_ind', 'X_ind_raw', 'coverage', 'top_industries')} for c in ('FBT', 'SHLD', 'SHLD_EU') if c in expo},
        X_gold=bi['X_ind'].get('Gold'), X_gold_raw=bi['X_ind_raw'].get('Gold'),
        world_rows={c: {k: (round(100 * rows[c][k], 3) if isinstance(rows[c].get(k), float) else rows[c].get(k))
                        for k in ('A1', 'A2', 'B', 'C', 'B_gross', 'C_gross', 'B_X', 'B_rec', 'B_src', 'er_vehicle', 'dy_vehicle', 'tax_drag',
                                  'vol_A1', 'maxdd_A1')} for c in new_keys},
        dmd=dmd, consts_raw=consts, s_us=s_us)
    res = dict(rows=rows, chains=chains, info=info, rows0=rows0, chains0=chains0, raw=raw, syn=syn, px=px)
    _STATE['res'] = res
    log('  完了', f'{time.time() - t0:.0f}秒')
    return res


# ───────────────────────── 円の枠 ─────────────────────────
def jpy_chains(chains, yen=YEN_ASSETS):
    """ドル建ての月次 → 円: (1+r)×(DEXJPUS 月末の比) − 1。円の本はそのまま。為替が無い月は落とす（0 と読まない）"""
    fx, url = fred_monthly_last('DEXJPUS')
    out = {}
    for c, s in chains.items():
        if c in yen:
            out[c] = dict(s)
            continue
        d = {}
        for m, v in s.items():
            p = months_add(m, -1)
            if m in fx and p in fx:
                d[m] = (1 + v) * fx[m] / fx[p] - 1
        out[c] = d
    return out, url


def fx18_rows(rows, Dmap, yen=YEN_ASSETS):
    """感度 FX18: 円の本以外の B・C・D から 1.8%/年を引いた写し"""
    r2, d2 = {}, {}
    for c, r in rows.items():
        x = dict(r)
        if c not in yen:
            x['B'] = r['B'] - FX18
            x['C'] = r['C'] - FX18
        r2[c] = x
    for c, v in Dmap.items():
        d2[c] = v - (0 if c in yen else FX18)
    return r2, d2


# ───────────────────────── 物差し（night/bestpf_check.py の1本ずつの塊）─────────────────────────
_TABS = {}


def tables():
    """etf_p15.dca_tables(20, [0, .05, .10, .15]) と bestpf_eval.simulate_tables()（npz にキャッシュ）"""
    if _TABS:
        return _TABS['tabs'], _TABS['sim']
    import etf_p15 as P
    import bestpf_eval as E
    p = os.path.join(CDIR, f'dca_tables_20_{P.SEED}_{P.NPATH}.npz')
    taus = [0.0, 0.05, 0.10, 0.15]
    if os.path.exists(p):
        z = np.load(p)
        tabs = {t: z[f't{t}'] for t in taus}
    else:
        log('  積立の表を作る（初回だけ）')
        tabs = P.dca_tables(20, taus, log=False)
        np.savez_compressed(p, **{f't{t}': tabs[t] for t in taus})
    sim = E.simulate_tables()
    _TABS['tabs'], _TABS['sim'] = tabs, sim
    return tabs, sim


def measure(ports, rows, chains, Dmap=None, frame='USD', windows=None, mega=None, a2=None):
    """bestpf_check.main の1本ずつの塊（同じ式）。ports={名前: {本: 比}}・ETF 側だけを正規化。
    → {窓: {名前: 表示の値（bestpf_check と同じ鍵）＋ '_raw'（判定に使う丸める前の値）}}"""
    import etf_p15 as P
    import etf_forward_combo as CB
    import bestpf_eval as E
    import bestpf_check as BC
    windows = windows or BC.WINDOWS
    tabs, sim = tables()
    assets = sorted({a for w in ports.values() for a in w} | {'VOO'})
    k2 = R.months(*(a2 or R.A2))
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    if Dmap is None:
        Dmap, _, _ = E.load_D(rows, assets)
        for c in assets:
            if 'D_override' in rows[c]:
                Dmap[c] = rows[c]['D_override']
    mg = np.array([(mega or {}).get(c, 0.0) for c in assets])
    pi, _, _ = E.load_pi()
    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi.items()}
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets]); gD = np.array([Dmap[c] for c in assets])
    T = 240
    out = {}
    for wname, (a, b) in windows.items():
        k1 = R.months(a, b)
        G1 = np.array([[chains[c][m] for m in k1] for c in assets])
        S1 = np.cov(np.log1p(G1), bias=True) * 12
        s1 = np.diag(S1).copy()

        def pr(wv, sig, tau, p):
            tot = 0.0
            for k in E.WORLDS:
                if p.get(k, 0) <= 0:
                    continue
                v = float(P.interp(tabs[tau], np.array([math.log1p(wv[k])]), np.array([sig]))[0])
                tot += p[k] * (v if tau >= 0.10 else 1 - v)
            return tot / sum(p[k] for k in E.WORLDS if p.get(k, 0) > 0)

        def placed(w, mB, crash, at):
            rets = [math.expm1(mB)] * T
            for t, m in enumerate(R.months(*crash)):
                rets[at + t] = float(w @ np.array([chains[c][m] for c in assets]))
            Wt = 0.0
            for x in rets:
                Wt = (Wt + 1) * (1 + x)
            return float(np.interp(Wt, sim['K'], sim['r_grid']))

        tab = {}
        for nm, wd in ports.items():
            tot = sum(wd.values())
            w = np.array([wd.get(c, 0) / tot for c in assets])
            ps = CB.path_stats((w @ G1)[None, :], len(k1))
            a2 = float(np.expm1(np.log1p(w @ G2).sum() * 12 / len(k2)))
            q = float(w @ S1 @ w); bonus = 0.5 * (float(w @ s1) - q); sig = math.sqrt(q)
            wv = dict(A1=float(ps[0][0]) + float(w @ adj), A2=a2 + float(w @ adj), B=math.expm1(float(w @ np.log1p(gB)) + bonus),
                      C=math.expm1(float(w @ np.log1p(gC)) + bonus), D=math.expm1(float(w @ np.log1p(gD)) + bonus))
            mB = math.log1p(wv['B']) / 12
            hs = P.hist_success(w[None, :], G1, adj, len(k1), tau=0.15)
            pen = BC.MEGA_PEN * float(w @ mg)
            wv_m = dict(wv, B=wv['B'] - pen, C=wv['C'] - pen, D=wv['D'] - pen)
            raw = dict(P15=pr(wv, sig, 0.15, pi), P15_noA2=pr(wv, sig, 0.15, noA2), P10=pr(wv, sig, 0.10, pi), P5=pr(wv, sig, 0.05, pi),
                       P0=pr(wv, sig, 0.0, pi), worst=min(wv.values()), mean_pi=sum(pi[k] * wv[k] for k in E.WORLDS) / sum(pi.values()),
                       vol=float(ps[1][0]), mdd=float(ps[2][0]), sig=sig, worlds=wv)
            tab[nm] = {'ETF側の比': {k: round(100 * v / tot, 1) for k, v in wd.items()},
                       'P15π': round(100 * raw['P15'], 1), 'P15π（A2を外す）': round(100 * raw['P15_noA2'], 1),
                       'P10π': round(100 * raw['P10'], 1), 'P5π（5%未満）': round(100 * raw['P5'], 1),
                       'P0π（元本割れ）': round(100 * raw['P0'], 1),
                       '世界ごとの年率': {k: round(100 * v, 2) for k, v in wv.items()}, '最悪の世界': round(100 * raw['worst'], 2),
                       'π加重の平均の年率': round(100 * raw['mean_pi'], 2),
                       'ぶれ': round(100 * raw['vol'], 1), '最大下落': round(100 * raw['mdd'], 1),
                       '積立20年の内部収益率': E.irr_quantiles(sim, {k: math.log1p(v) for k, v in wv.items()}, sig, pi),
                       '崩れ2000型_1〜3年目': round(100 * placed(w, mB, BC.CRASH00, 0), 2), '崩れ2000型_16〜18年目': round(100 * placed(w, mB, BC.CRASH00, 180), 2),
                       '下落2022型_16年目': round(100 * placed(w, mB, BC.CRASH22, 180), 2),
                       '過去の転がる20年で15%以上': round(100 * float(hs[240][0]), 1),
                       '超大型株の比率（ETF側）': round(100 * float(w @ mg), 1),
                       'P15π（超大型株の基礎率で B・C・D を割り引く）': round(100 * pr(wv_m, sig, 0.15, pi), 1),
                       'P5π（同）': round(100 * pr(wv_m, sig, 0.05, pi), 1),
                       '_raw': raw}
        out[wname] = tab
    return out


def mega_map(rows, assets):
    """bestpf_check.mega_share（新しい本は保有があれば同じ式・無ければ0・GOLDPLUS は QQQM と同じ）"""
    import bestpf_check as BC
    out = {}
    for c in assets:
        if c == 'GOLDPLUS_REF':
            out[c] = BC.mega_share('QQQM', rows)
        elif c in ('SHLD_EU',):
            out[c] = BC.mega_share('SHLD', rows)
        else:
            try:
                out[c] = BC.mega_share(c, rows)
            except Exception:  # noqa
                out[c] = 0.0
    return out


def strip_raw(d):
    """出力用: '_raw' を落とし、判定に使った丸める前の値を小さく残す"""
    if isinstance(d, dict):
        return {k: strip_raw(v) for k, v in d.items() if k != '_raw'}
    return d


# ───────────────────────── 100年の代用 ─────────────────────────
_CENT = {}


def century_parts():
    """月次の写し（alloc_check.century と同じ部品＋新しい写し）と年次の写し（Damodaran・月次を暦年で複利）"""
    if _CENT:
        return _CENT
    import future30 as F
    cols, ret, capm, me, be, share, mkt = F.load()
    tech = G.french_tech()
    allm = sorted(mkt)
    parts = {'QQQM': F.mix([(0.65, tech), (0.35, mkt)], allm), 'SMH': ret['Chips'],
             'ITA': F.capw(ret, capm, ['Aero', 'Guns'], allm), 'VOO': mkt,
             'XLV': F.capw(ret, capm, ['Drugs', 'MedEq', 'Hlth'], allm),
             'FBT': ret['Drugs'], 'SHLD': F.capw(ret, capm, ['Aero', 'Guns'], allm), 'GDX': ret['Gold'], 'XLU': ret['Util']}
    parts['SHLD_EU'] = parts['SHLD']
    dmd, _ = damodaran()
    ann = {}
    for k, s in parts.items():
        a = {}
        for y in range(1926, 2026):
            ms = [y * 100 + i for i in range(1, 13)]
            if all(m in s for m in ms):
                a[y] = math.prod(1 + s[m] for m in ms) - 1
        ann[k] = a
    ann_mkt = ann['VOO']
    for k, col in (('TBOND', 'tbond'), ('TBILL', 'tbill'), ('GOLD', 'gold')):
        ann[k] = {y: dmd[y][col] for y in dmd if dmd[y].get(col) is not None and y <= 2025}
    _CENT.update(dict(F=F, parts=parts, mkt=mkt, endm=max(mkt), ann=ann, ann_mkt=ann_mkt))
    return _CENT


DMD_Y0 = 1928                     # common.century: Damodaran の年次（1928〜2025）
ANNUAL_MAP = {'EDV': 'TBOND', 'TLT': 'TBOND', 'TIP': 'TBOND', 'UST_HEDGED_2621': 'TBOND', 'GLDM': 'GOLD', 'YEN_CASH': 'TBILL'}
MONTHLY_OK = {'QQQM', 'SMH', 'ITA', 'VOO', 'XLV', 'FBT', 'SHLD', 'SHLD_EU', 'GDX', 'XLU'}


def _q(xs, p):
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]


def century_monthly(f):
    """alloc_check.century の1つの形（30年 起点1965〜1995・20年 起点1965〜2005）。写しの無い本があれば None"""
    if any(k not in MONTHLY_OK for k, w in f.items() if w > 0):
        return None
    C = century_parts()
    F, parts, mkt, endm = C['F'], C['parts'], C['mkt'], C['endm']
    allm = sorted(mkt)
    tw = sum(f.values())
    s = F.mix([(w / tw, parts[k]) for k, w in f.items() if w > 0], allm)
    d = {}
    for n, lab, starts, half in ((360, '30年の積立（起点1965〜1995）', range(1965, 1996), 1979),
                                 (240, '20年の積立（起点1965〜2005）', range(1965, 2006), 1985)):
        v = []
        for y in starts:
            ms = F.months((y + 1) * 100 + 1, n)
            if ms[-1] > endm:
                continue
            a, b = F.dca_mult(s, ms), F.dca_mult(mkt, ms)
            if a and b:
                v.append((y, a / b))
        xs = sorted(x for _, x in v)
        d[lab] = {'窓': len(xs), '中央値': round(S.median(xs), 3), '下位10%点': round(_q(xs, 0.10), 3), '最悪': round(xs[0], 3),
                  '市場に勝った割合': round(sum(x > 1 for x in xs) / len(xs), 2), '_med': S.median(xs), '_p10': _q(xs, 0.10), '_v': dict(v)}
    return d


def century_annual(f):
    """年次の写し: 株の部品は月次の写しを暦年で複利・債券・金・現金は Damodaran・毎年組み直し・年1回の積立の市場との比（20年・30年）"""
    C = century_parts()
    ann, am = C['ann'], C['ann_mkt']
    keys = {}
    for k, w in f.items():
        if w <= 0:
            continue
        if k in ANNUAL_MAP:
            keys[k] = ANNUAL_MAP[k]
        elif k in MONTHLY_OK:
            keys[k] = k
        else:
            return None
    tw = sum(f.values())
    years = sorted(y for y in am if y >= DMD_Y0 and all(y in ann[keys[k]] for k in keys))   # Damodaran の年（1928〜）にそろえる
    r = {y: sum(f[k] / tw * ann[keys[k]][y] for k in keys) for y in years}
    d = {}
    for n, lab in ((30, '30年の積立（年次・年1回）'), (20, '20年の積立（年次・年1回）')):
        v = []
        for y in years:
            ys = list(range(y, y + n))
            if any(t not in r or t not in am for t in ys):
                continue
            Vp = Vm = 0.0
            for t in ys:
                Vp = (Vp + 1) * (1 + r[t]); Vm = (Vm + 1) * (1 + am[t])
            v.append((y, Vp / Vm))
        xs = sorted(x for _, x in v)
        if not xs:
            d[lab] = None
            continue
        d[lab] = {'窓': len(xs), '起点': f'{v[0][0]}〜{v[-1][0]}', '中央値': round(S.median(xs), 3), '下位10%点': round(_q(xs, 0.10), 3),
                  '最悪': round(xs[0], 3), '市場に勝った割合': round(sum(x > 1 for x in xs) / len(xs), 2), '_med': S.median(xs), '_p10': _q(xs, 0.10),
                  '_v': dict(v)}
    return d


def cond3(cf, cb):
    """(3) 20年・30年の中央値が下がらず、下位10%点が上がる。どちらかが None なら None（測れない）"""
    if cf is None or cb is None:
        return None
    ok = True
    for lab in cf:
        a, b = cf.get(lab), cb.get(lab)
        if a is None or b is None:
            return None
        common = sorted(set(a['_v']) & set(b['_v']))          # 同じ起点どうしで比べる（窓の数が違えば共通の起点だけ）
        xa = sorted(a['_v'][y] for y in common); xb = sorted(b['_v'][y] for y in common)
        if not common:
            return None
        ok = ok and S.median(xa) >= S.median(xb) and _q(xa, 0.10) > _q(xb, 0.10)
    return bool(ok)


def strip_century(d):
    if d is None:
        return None
    return {lab: (None if v is None else {k: x for k, x in v.items() if not k.startswith('_')}) for lab, v in d.items()}


def castle_copy():
    """個別株15%を今の席の業種の写しへ（alloc_check.seats と同じ: 書庫:19497 の (3) の『全体の形』）"""
    import alloc_check as AC
    order, prox_w, prox = AC.seats()
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    c = float(tg.get('shiro_castle_pct') or 15)
    return {k: c * v for k, v in prox.items()}, order, c


def whole(etf, cc):
    f = dict(etf)
    for k, v in cc.items():
        f[k] = f.get(k, 0) + v
    return f


if __name__ == '__main__':
    res = build()
    inf = res['info']
    print(json.dumps({k: inf[k] for k in ('gates', 'excluded', 'deviations', 'fbt_proxy', 'syn_cover', 'shld', 'consts', 'regression', 'expo_new',
                                          'X_gold', 'X_gold_raw', 'jp3m', 'tsmom', 'eu_basket')}, ensure_ascii=False, indent=1, default=str)[:20000])
    for c, r in inf['world_rows'].items():
        print(c, r)
