#!/usr/bin/env python3
"""night/mw_congress_trades.py — 角度 congress_trades（読むだけ・門の判定には不使用）

問い: 米国の議員（上院・下院）が公開した株の売買を、公開日の翌月からまねて持つと、
      純粋な時価加重の米国株（French Mkt ≒ S&P500）に勝つか。
      Ziobrowski ほか (2004・上院 1993-98／2011・下院 1985-2001) は勝ったと報告し、
      Eggers & Hainmueller (2013・2004-08) は勝たなかった。STOCK Act (2012) で取引の開示が45日以内・電子公開になった
      ——ここで測るのは『公表後』『開示の後』のまね（論文の結果を知った後のデータ）。

事前登録: out/mw_congress_trades_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を
mw_common.grade でそのまま当てる。訓練期間（〜2006-12）のデータは存在しない（電子開示は2012年〜）＝
C1 は原理的に測れず不合格・C4（転がる20年）も測れず不合格＝格は構造的に C が上限。

データ
- 下院: kadoa-org/congress-trading-monitor（MIT・House Clerk の電子 PTR を構造化・commit を固定）
        ＋ Clerk の索引（{年}FD.zip）で電子 PTR（DocID 2xxxxxxx）のうち kadoa に無いものを PDF から自前で読む（pypdf）。
        紙の PTR（スキャン）は OCR が無いので読めない＝欠ける（年ごとに数える）
- 上院: efdsearch.senate.gov（公式）の PTR 一覧と各 PTR の表を自前で採る（電子のみ。紙＝スキャンは読めない）
        ＋ timothycarambat/senate-stock-watcher-data と kadoa の上院分で突き合わせ
- 株価: Yahoo の月次の調整後終値（配当込み）＝生き残りの偏りあり → 未観測を『持たない』(S)・−30%(L30)・−100%(L100) で囲む
- 相手: French Mkt（Mkt-RF + RF・総リターン）。SPY は報告のみ

段
  --fetch-kadoa : kadoa の filer 別 JSON（固定 commit）
  --fetch-senate: 上院 eFD の PTR 一覧と各 PTR の表
  --fetch-clerk : 下院 Clerk の索引と、kadoa に無い電子 PTR の PDF（＋照合用の見本）を読む
  --fetch-yh    : 事象の全記号と比較用 ETF の Yahoo 月次
  --coverage    : 年×院の件数だけを数える（リターンは見ない）→ 標準出力
  (既定)        : 計算して out/mw_congress_trades.json を書く
"""
import csv, datetime, glob, http.cookiejar, io, json, math, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error, zipfile
import statistics as S
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

CT = os.path.join(M.CACHE, 'ct')
PRE = 'mw_congress_trades_prereg.json'
OUT = 'mw_congress_trades.json'
END = 202608                       # French の終わり
KADOA_SHA = 'ef9e1cf70e694c790cb6580034ad357ca740b4b8'   # 2026-09-27 の Daily refresh（固定）
KADOA = f'https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/{KADOA_SHA}/public/data'
SSW = 'https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/aggregate/all_daily_summaries.json'
EFD = 'https://efdsearch.senate.gov'
CLERK_IDX = 'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip'
CLERK_PDF = 'https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{y}/{d}.pdf'
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research; public disclosure study)'}
LAG_DAYS = 5                       # 公開日＝提出日＋5日（掲示の遅れの安全幅）。その月の末に買い、翌月から持つ
SPIKE = 3.0                        # 月 +300% 超はデータの誤り → その前の月で打ち切り
MIN_HOLD = 10                      # 持つ社が10社未満の月は French Mkt を持つ（数える）
START = 201401                     # 計算の最初の月（事前登録で固定）
BENCH_ETF = ['SPY', 'QQQ', 'NANC', 'GOP']   # GOP = 旧 KRUZ（2025-03-21 に記号変更）
# 記号の変更（同じ会社が記号だけ変えた＝Yahoo は新しい記号に履歴を持つ）。結果を見る前に、未観測の記号の多い順に目で確かめて固定した。
# 買収・合併で消えた社（TWTR・ATVI・CELG など）はここに入れない（その社の値は Yahoo に無い＝未観測のまま L の囲みで扱う）
RENAME = {'FB': 'META', 'SQ': 'XYZ', 'UTX': 'RTX', 'ANTM': 'ELV', 'BLL': 'BALL', 'FI': 'FISV', 'DISCA': 'WBD', 'RDS-A': 'SHEL', 'RDS-B': 'SHEL',
          'TOT': 'TTE', 'PCLN': 'BKNG', 'SNE': 'SONY', 'CTL': 'LUMN', 'HHC': 'HHH', 'DWDP': 'DD', 'PKI': 'RVTY', 'FLT': 'CPAY', 'COH': 'TPR',
          'ETE': 'ET', 'KORS': 'CPRI', 'COG': 'CTRA', 'ADS': 'BFH', 'WLTW': 'WTW', 'DPS': 'KDP', 'HRS': 'LHX', 'BBT': 'TFC', 'SYMC': 'GEN',
          'NLOK': 'GEN', 'ABC': 'COR', 'HCN': 'WELL', 'GPS': 'GAP', 'LB': 'BBWI', 'RE': 'EG', 'TMK': 'GL', 'CBG': 'CBRE', 'JEC': 'J',
          'CHK': 'EXE', 'HCP': 'DOC', 'ABX': 'B', 'CBS': 'PSKY', 'VIAC': 'PSKY'}
# ★ 2026-09-28（再開した担当が、測る前に追加）: 記号の再利用。その期間の事象は『今その記号を持つ会社』とは別の会社。
#   (公開月の下限, 上限, 付け替え先 or None=未観測)。社名（書類の社名と Yahoo の今の社名・系列の始まり）だけで決めた。リターンは見ていない
#   GOLD: 〜2018 は Randgold（合併で消えた）/ 2019-01〜2025-04 は Barrick（今は B）/ 今の GOLD は Gold.com（旧 A-Mark・2014〜の系列）
#   WTW: 〜2021 は Weight Watchers（今の WTW は Willis Towers Watson の系列）。BBT: 〜2025-08 は BB&T→Truist（TFC）/ 今の BBT は Beacon Financial（2000〜の系列）
#   PARA: 〜2025-07 は Paramount Global（PSKY が CBS からの系列を持つ）/ 今の PARA は Banzai。COR: 〜2023-07 は CoreSite（今は Cencora）
#   DOC: 〜2024-02 は Physicians Realty（今は Healthpeak）。CCC: 〜2021-07 は Clarivate（今は CLVT・2018〜の系列）/ 今は CCC Intelligent Solutions
#   RPT: 〜2024-12 は RPT Realty（今は Rithm Property Trust）。CNR: 〜2024-12 は Cornerstone Building Brands（今は Core Natural Resources）
#   VIVO: 〜2023-12 は Meridian Bioscience（今は VivoPower）。NTRP: 〜2023-12 は Neurotrope（今は NextTrip）
#   SUNE: 〜2023-12 は SunEdison（今は SUNation Energy・1981〜の系列）。P: 〜2024-12 は Pandora Media（今は Everpure）
#   AMTD: 〜2020-11 は TD Ameritrade（今は AMTD IDEA）
REUSE = {'GOLD': [(0, 201812, None), (201901, 202504, 'B'), (202505, 999999, None)], 'WTW': [(0, 202112, None)],
         'BBT': [(0, 202508, 'TFC'), (202509, 999999, None)], 'PARA': [(0, 202507, 'PSKY'), (202508, 999999, None)],
         'COR': [(0, 202307, None)], 'DOC': [(0, 202402, None)], 'CCC': [(0, 202107, 'CLVT')], 'RPT': [(0, 202412, None)],
         'CNR': [(0, 202412, None)], 'VIVO': [(0, 202312, None)], 'NTRP': [(0, 202312, None)], 'SUNE': [(0, 202312, None)],
         'P': [(0, 202412, None)], 'AMTD': [(0, 202011, None)]}
# 自動の改名探し（ct/rename_auto.json）のうち、測る前に目で退けたもの:
#   SIX→FUN（今の FUN の系列は Cedar Fair の 1987〜＝別の会社の値）・NGD→GOLD（今の GOLD は Gold.com）・TWO→TWO-PC（優先株）
REJECT_AUTO = {'SIX', 'NGD', 'TWO'}
CLASS_SUFFIX = {'A', 'B', 'C'}     # 記号の '-' の後ろが株の種類（BRK-B 等）以外（優先株 -PA・新株予約権 -W・発行日取引 -WI 等）は普通株でない＝除く
STOP = set('onsored unsponsored inc incorporated corp corporation co company companies ltd limited plc the holdings holding group class common stock shares share sa nv ag llc lp trust new com ord adr ads sponsored of and international intl technologies technology plc. se spa oyj ab asa'.split())


def madd(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


def http_get(url, tries=3, opener=None, headers=None, data=None, timeout=120):
    """404 は即 None（再試行しない）。それ以外は 2,4 秒あけて再試行"""
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or UA, data=data)
            return (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # noqa
            err = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f'取得失敗 {url}: {err}')


def save_bytes(p, b):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f'{p}.{os.getpid()}.tmp'
    open(tmp, 'wb').write(b)
    os.replace(tmp, p)


# ───────────────────────── 取得: kadoa ─────────────────────────
def fetch_kadoa():
    d = os.path.join(CT, 'kadoa_filer')
    b = http_get(f'{KADOA}/filers.json')
    save_bytes(os.path.join(CT, 'kadoa_filers.json'), b)
    ids = [x['id'] for x in json.loads(b)]
    n = 0
    for i in ids:
        p = os.path.join(d, f'{i}.json')
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        x = http_get(f'{KADOA}/filer/{i}.json')
        if x is None:
            print('kadoa 404', i); continue
        save_bytes(p, x); n += 1
    b = http_get(SSW)
    save_bytes(os.path.join(CT, 'senate_daily.json'), b)
    print('kadoa filers', len(ids), '新規', n)


# ───────────────────────── 取得: 上院 eFD ─────────────────────────
def efd_session():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    h = http_get(f'{EFD}/search/home/', opener=op).decode()
    tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', h).group(1)
    http_get(f'{EFD}/search/home/', opener=op, data=urllib.parse.urlencode({'prohibition_agreement': '1', 'csrfmiddlewaretoken': tok}).encode(),
             headers={**UA, 'Referer': f'{EFD}/search/home/'})
    csrf = [c.value for c in cj if c.name == 'csrftoken'][0]
    return op, csrf


def efd_list(op, csrf, y):
    rows, start = [], 0
    while True:
        q = {'start': str(start), 'length': '100', 'report_types': '[11]', 'filer_types': '[]',
             'submitted_start_date': f'01/01/{y} 00:00:00', 'submitted_end_date': f'12/31/{y} 23:59:59',
             'candidate_state': '', 'senator_state': '', 'office_id': '', 'first_name': '', 'last_name': '', 'csrfmiddlewaretoken': csrf}
        j = json.loads(http_get(f'{EFD}/search/report/data/', opener=op, data=urllib.parse.urlencode(q).encode(),
                                headers={**UA, 'Referer': f'{EFD}/search/', 'X-CSRFToken': csrf}))
        rows += j['data']
        start += 100
        if start >= j['recordsTotal']:
            return rows
        time.sleep(0.5)


def efd_parse(h):
    i = h.find('<tbody>')
    if i < 0:
        return []
    body = h[i:h.find('</tbody>', i)]
    out = []
    for tr in re.findall(r'<tr>(.*?)</tr>', body, re.S):
        tds = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', x)).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(tds) >= 8:
            out.append({'n': tds[0], 'tdate': tds[1], 'owner': tds[2], 'ticker': tds[3], 'asset': tds[4], 'atype': tds[5], 'type': tds[6], 'amount': tds[7]})
    return out


def fetch_senate():
    d = os.path.join(CT, 'efd')
    os.makedirs(d, exist_ok=True)
    op, csrf = efd_session()
    lst = {}
    for y in range(2012, 2027):
        p = os.path.join(d, f'list_{y}.json')
        if os.path.exists(p) and y < 2026:
            lst[y] = json.load(open(p)); continue
        lst[y] = efd_list(op, csrf, y)
        json.dump(lst[y], open(p, 'w'))
        print('eFD 一覧', y, len(lst[y]))
        time.sleep(0.5)
    n = 0
    todo = [r for y in sorted(lst) for r in lst[y]]
    if os.environ.get('MW_REVERSE'):
        todo = todo[::-1]
    if os.environ.get('MW_MIDDLE'):
        todo = todo[len(todo) // 2:] + todo[:len(todo) // 2]
    for r in todo:
        if True:
            m = re.search(r'/search/view/(ptr|paper)/([0-9a-fA-F-]+)/', r[3])
            if not m or m.group(1) != 'ptr':
                continue
            p = os.path.join(d, f'{m.group(2).lower()}.json')
            if os.path.exists(p):
                continue
            for k in range(3):
                try:
                    h = http_get(f'{EFD}/search/view/ptr/{m.group(2)}/', opener=op, headers={**UA, 'Referer': f'{EFD}/search/'}).decode()
                    if 'csrfmiddlewaretoken' in h and 'prohibition_agreement' in h:   # セッション切れ
                        op, csrf = efd_session(); continue
                    break
                except Exception as e:  # noqa
                    print('eFD 失敗', m.group(2), e); time.sleep(5); op, csrf = efd_session(); h = None
            if h is None:
                continue
            json.dump({'uuid': m.group(2).lower(), 'first': r[0], 'last': r[1], 'office': r[2], 'filed': r[4], 'rows': efd_parse(h)}, open(p, 'w'))
            n += 1
            time.sleep(0.35)
    print('eFD PTR 新規', n)


# ───────────────────────── 取得: 下院 Clerk ─────────────────────────
def clerk_index():
    import xml.etree.ElementTree as ET
    out = {}
    for y in range(2012, 2027):
        p = os.path.join(CT, 'clerk', f'{y}FD.zip')
        if not os.path.exists(p) or y == 2026:
            b = http_get(CLERK_IDX.format(y=y))
            if b is None:
                continue
            save_bytes(p, b)
        z = zipfile.ZipFile(p)
        x = [n for n in z.namelist() if n.endswith('.xml')][0]
        for mm in ET.fromstring(z.read(x)):
            r = {c.tag: (c.text or '') for c in mm}
            if r.get('FilingType') == 'P':
                out[r['DocID']] = {'year': y, 'filed': r['FilingDate'], 'last': r.get('Last', ''), 'first': r.get('First', ''), 'dst': r.get('StateDst', '')}
    return out


def _pypdf():
    sys.modules.setdefault('cryptography', None)   # 環境の cryptography が壊れているので読み込ませない（pypdf は自前の実装へ落ちる）
    for p in [os.environ.get('MW_PYLIB', ''), '/tmp/claude-0/-home-user-ccf-gate/51469f69-a26b-5af3-955c-7af574d178fa/scratchpad/pylib']:
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    import pypdf  # noqa
    return pypdf


PDF_ROW = re.compile(r'\(([A-Za-z][A-Za-z.\-]{0,6})\)\s*(?:\[([A-Za-z]{2})\])?\s*([PSEpse])(?:\s*\((?:partial|PARTIAL|Partial)\))?\s*(\d{1,2}/\d{1,2}/\d{4})\s*(\d{1,2}/\d{1,2}/\d{4})\s*((?:\$[\d,]+(?:\.\d+)?)(?:\s*-\s*\$[\d,]+)?|[Oo]ver\s*\$[\d,]+|[Ss]pouse/[Dd][Cc]\s*[Oo]ver\s*\$[\d,]+)')


def pdf_rows(text):
    t = re.sub(r'\s+', ' ', text)
    out = []
    for m in PDF_ROW.finditer(t):
        tk, code, ty, td, nd, amt = m.groups()
        lo = re.findall(r'\$([\d,]+)', amt)
        lo = [int(x.replace(',', '')) for x in lo]
        out.append({'ticker': tk.upper(), 'code': (code or '').upper() or None, 'type': ty.upper(), 'tdate': td,
                    'amount_low': lo[0] if lo else None, 'amount_high': lo[1] if len(lo) > 1 else None, 'amount': amt})
    return out


def fetch_clerk():
    idx = clerk_index()
    json.dump(idx, open(os.path.join(CT, 'clerk_index.json'), 'w'))
    kd = kadoa_house_docs()
    pypdf = _pypdf()
    d = os.path.join(CT, 'clerk_pdf')
    os.makedirs(d, exist_ok=True)
    elec = sorted(k for k in idx if k.startswith('2'))
    miss = [k for k in elec if k not in kd]
    # 照合用: kadoa が持つ電子 PTR から年ごとに 12 件ずつ（決まった順＝DocID 昇順の等間隔）
    byy = defaultdict(list)
    for k in elec:
        if k in kd:
            byy[idx[k]['year']].append(k)
    val = []
    for y, ks in byy.items():
        step = max(1, len(ks) // 12)
        val += ks[::step][:12]
    out = {}
    for k in miss + val:
        pj = os.path.join(d, f'{k}.json')
        if os.path.exists(pj):
            out[k] = json.load(open(pj)); continue
        pp = os.path.join(d, f'{k}.pdf')
        if not os.path.exists(pp):
            b = http_get(CLERK_PDF.format(y=idx[k]['year'], d=k))
            if b is None:
                json.dump({'doc': k, 'http': 404}, open(pj, 'w')); continue
            save_bytes(pp, b)
            time.sleep(0.25)
        try:
            r = pypdf.PdfReader(pp)
            txt = '\n'.join((p.extract_text() or '') for p in r.pages)
        except Exception as e:  # noqa
            txt = ''; print('PDF 読めない', k, e)
        rec = {'doc': k, 'role': 'fill' if k in miss else 'validate', 'chars': len(txt), 'rows': pdf_rows(txt)}
        json.dump(rec, open(pj, 'w'))
        out[k] = rec
    print('Clerk 電子 PTR', len(elec), 'kadoa に無い', len(miss), '照合見本', len(val))


# ───────────────────────── 事象の組み立て ─────────────────────────
def kadoa_rows():
    rows = []
    for f in sorted(glob.glob(os.path.join(CT, 'kadoa_filer', '*.json'))):
        d = json.load(open(f)); fl = d['filer']
        if fl.get('branch') != 'congress':
            continue
        for t in d['trades']:
            t = {k: v for k, v in t.items() if k not in ('ret_since', 'excess_since', 'ret_30d', 'ret_1y')}   # kadoa の成績欄は読まない
            t['_chamber'] = fl.get('chamber'); t['_party'] = fl.get('party'); t['_name'] = fl.get('full_name')
            rows.append(t)
    return rows


def kadoa_house_docs():
    s = set()
    for t in kadoa_rows():
        if t['_chamber'] == 'house':
            m = re.search(r'ptr-pdfs/(\d{4})/(\d+)\.pdf', t.get('doc_url') or '')
            if m:
                s.add(m.group(2))
    return s


def norm_ticker(t):
    if not t:
        return None
    t = t.strip().upper().replace('.', '-').replace(' ', '')
    t = re.sub(r'^\$', '', t)
    if not re.fullmatch(r'[A-Z]{1,5}(-[A-Z]{1,2})?', t):
        return None
    return t


def pdate(s):
    s = (s or '').strip()
    for f in ('%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def ptype(s):
    s = (s or '').lower()
    if s.startswith('purchase') or s == 'p':
        return 'P'
    if s.startswith('sale') or s == 's':
        return 'S'
    return None


def kadoa_stock_kind(t):
    """'stock'=株と明記 / 'other'=株以外と明記 / 'unknown'=種類の記載なし（Yahoo の種類で決める）"""
    a = t.get('asset_type')
    if a in ('ST', 'Stock'):
        return 'stock'
    if a is None:
        m = re.search(r'\[([A-Za-z]{2})\]', t.get('asset_name') or '')
        if m:
            return 'stock' if m.group(1).upper() == 'ST' else 'other'
        return 'unknown'
    return 'other'


def build_events():
    """議員の株の売買の事象（重複を落とす）→ list[dict]。リターンは一切見ない"""
    ev, cov = [], {'house': Counter(), 'senate': Counter()}
    # 下院: kadoa ＋ 自前の PDF（kadoa に無い電子 PTR だけ）
    idx = json.load(open(os.path.join(CT, 'clerk_index.json')))
    for t in kadoa_rows():
        if t['_chamber'] != 'house':
            continue
        f = pdate(t['filing_date']); ty = ptype(t['transaction_type'])
        m = re.search(r'ptr-pdfs/(\d{4})/(\d+)\.pdf', t.get('doc_url') or '')
        ev.append({'ch': 'house', 'member': t['filer_id'], 'party': t['_party'], 'doc': m.group(2) if m else t['id'], 'filed': f,
                   'tdate': pdate(t['transaction_date']), 'ticker': norm_ticker(t['ticker']), 'type': ty, 'kind': kadoa_stock_kind(t),
                   'lo': t.get('amount_range_low'), 'hi': t.get('amount_range_high'), 'owner': t.get('owner'),
                   'name': (t.get('asset_name') or '') if t.get('asset_type') else '', 'src': 'kadoa'})   # 種類欄の無い古い行は社名が化けている＝社名の照合に使わない
    for f in sorted(glob.glob(os.path.join(CT, 'clerk_pdf', '*.json'))):
        r = json.load(open(f))
        if r.get('role') != 'fill':
            continue
        meta = idx.get(r['doc'])
        if not meta:
            continue
        mem = 'house_clerk_' + re.sub(r'[^a-z]', '', (meta['first'] + meta['last']).lower())
        for x in r['rows']:
            ev.append({'ch': 'house', 'member': mem, 'party': None, 'doc': r['doc'], 'filed': pdate(meta['filed']), 'tdate': pdate(x['tdate']),
                       'ticker': norm_ticker(x['ticker']), 'type': {'P': 'P', 'S': 'S'}.get(x['type']),
                       'kind': 'stock' if x['code'] == 'ST' else ('other' if x['code'] else 'unknown'),
                       'lo': x['amount_low'], 'hi': x['amount_high'], 'owner': None, 'name': '', 'src': 'clerk_pdf'})
    # 上院: eFD（公式）を主に、eFD に無い PTR だけ kadoa → senate-stock-watcher で補う
    seen = set()
    for f in sorted(glob.glob(os.path.join(CT, 'efd', '*.json'))):
        if os.path.basename(f).startswith('list_'):
            continue
        r = json.load(open(f))
        seen.add(r['uuid'])
        mem = 'senate_' + lastkey(r['last']) + '_' + re.sub(r'[^a-z]', '', r['first'].lower())
        for x in r['rows']:
            ev.append({'ch': 'senate', 'member': mem, 'party': None, 'doc': r['uuid'], 'filed': pdate(r['filed']), 'tdate': pdate(x['tdate']),
                       'ticker': norm_ticker(x['ticker']), 'type': ptype(x['type']),
                       'kind': 'stock' if x['atype'] == 'Stock' else ('unknown' if x['atype'] in ('', '--') else 'other'),
                       'lo': _amt(x['amount'])[0], 'hi': _amt(x['amount'])[1], 'owner': x['owner'], 'name': x['asset'], 'src': 'efd'})
    extra = Counter()
    for t in kadoa_rows():
        if t['_chamber'] != 'senate':
            continue
        m = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})', t.get('doc_url') or '')
        u = m.group(1).lower() if m else None
        if u in seen:
            continue
        extra['kadoa'] += 1
        ev.append({'ch': 'senate', 'member': 'senate_' + re.sub(r'[^a-z]', '', (t['_name'] or '').lower()), 'party': t['_party'], 'doc': u or t['id'],
                   'filed': pdate(t['filing_date']), 'tdate': pdate(t['transaction_date']), 'ticker': norm_ticker(t['ticker']), 'type': ptype(t['transaction_type']),
                   'kind': kadoa_stock_kind(t), 'lo': t.get('amount_range_low'), 'hi': t.get('amount_range_high'), 'owner': t.get('owner'),
                   'name': (t.get('asset_name') or '') if t.get('asset_type') else '', 'src': 'kadoa', 'member_last': lastkey(t['_name'])})
    ksen = {e['doc'] for e in ev if e['ch'] == 'senate'}
    for x in json.load(open(os.path.join(CT, 'senate_daily.json'))):
        m = re.search(r'/ptr/([0-9a-fA-F-]{36})/', x['ptr_link'])
        if not m or m.group(1).lower() in ksen:
            continue
        extra['ssw'] += 1
        for t in x['transactions']:
            lo, hi = _amt(t['amount'])
            ev.append({'ch': 'senate', 'member': 'senate_' + re.sub(r'[^a-z]', '', (x['first_name'] + x['last_name']).lower()), 'party': None,
                       'doc': m.group(1).lower(), 'filed': pdate(x['date_recieved']), 'tdate': pdate(t['transaction_date']),
                       'ticker': norm_ticker(t['ticker']), 'type': ptype(t['type']),
                       'kind': 'stock' if t['asset_type'] == 'Stock' else ('unknown' if t['asset_type'] in ('', '--') else 'other'),
                       'lo': lo, 'hi': hi, 'owner': t['owner'], 'name': t['asset_description'], 'src': 'ssw', 'member_last': lastkey(x['last_name'])})
    # 重複: 同じ書類・記号・取引日・種類・金額の行は、書類の中で本当に別の行でありうる（同じ日に2回買う）ので落とさない。
    # ただし同じ書類が二つの元から入ることは上の seen で防いだ。修正の再提出（Amendment）は別の書類として残る＝下の『同じ議員×記号×公開月』で1件に畳む
    return ev, extra


def _amt(s):
    lo = re.findall(r'\$([\d,]+)', s or '')
    lo = [int(x.replace(',', '')) for x in lo]
    return (lo[0] if lo else None, lo[1] if len(lo) > 1 else None)


def signal_month(filed):
    d = filed + datetime.timedelta(days=LAG_DAYS)
    return d.year * 100 + d.month


def coverage(ev):
    c = defaultdict(Counter)
    for e in ev:
        if e['filed'] is None:
            c['nofiled'][e['ch']] += 1; continue
        k = e['kind']
        c[(e['ch'], e['filed'].year)][f"{e['type']}_{k}"] += 1
    return c


def cmd_coverage():
    ev, extra = build_events()
    print('事象', len(ev), '補い', dict(extra))
    c = coverage(ev)
    for ch in ('house', 'senate'):
        print(ch)
        for y in range(2012, 2027):
            x = c[(ch, y)]
            print(' ', y, 'P株', x['P_stock'], 'P不明', x['P_unknown'], 'S株', x['S_stock'], 'S不明', x['S_unknown'], '他', sum(v for k, v in x.items() if k.endswith('other') or k.startswith('None')))
    tk = {e['ticker'] for e in ev if e['ticker'] and e['type'] in ('P', 'S') and e['kind'] in ('stock', 'unknown')}
    print('記号', len(tk))


# ───────────────────────── 取得: Yahoo ─────────────────────────
def yh_name(t):
    return os.path.join(M.CACHE, f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json')


def fetch_yh(tickers, force=()):
    """mw_common.yahoo と同じ URL・同じキャッシュ名で置く（404 は ct/yh404.json に記録して再試行しない）"""
    from concurrent.futures import ThreadPoolExecutor
    p404 = os.path.join(CT, 'yh404.json')
    miss = set(json.load(open(p404))) if os.path.exists(p404) else set()
    todo = [t for t in sorted(tickers) if t in force or (t not in miss and not (os.path.exists(yh_name(t)) and time.time() - os.path.getmtime(yh_name(t)) < 3 * 86400))]

    def one(t):
        u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
        time.sleep(0.3)
        try:
            b = http_get(u, tries=4)
        except Exception as e:  # noqa
            return t, 'err'
        if b is None:
            return t, 404
        try:
            j = json.loads(b)
            if not j['chart']['result']:
                return t, 404
        except Exception:  # noqa
            return t, 404
        save_bytes(yh_name(t), b)
        return t, 200
    res = Counter()
    with ThreadPoolExecutor(3) as ex:
        for t, st in ex.map(one, todo):
            res[st] += 1
            if st == 404:
                miss.add(t)
    json.dump(sorted(miss), open(p404, 'w'))
    print('Yahoo 取得', dict(res), '404 累計', len(miss))


def yh_parse(j):
    """mw_common.yahoo と同じ読み方（調整後終値・今月の途中の本を落とす）を、キャッシュの JSON に直接当てる。
    ★ M.yahoo はキャッシュが3日より古いと取り直し、失敗すると例外＝旧 yh_load はそれを『系列なし（未観測）』に黙って化けさせていた。
      計算の途中でネットにつながないよう、キャッシュを直接読む（取得は --fetch-yh の段だけ）"""
    r = j['chart']['result'][0]
    ts = r.get('timestamp') or []
    adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    px = {}
    for t, a in zip(ts, adj):
        if a is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        px[d.year * 100 + d.month] = a
    # 調整後終値が 0 以下の本は壊れている（大きな特別配当で調整の係数が負になる: VHI・SAFE・AOZOF・AEXAY 等）。
    # 0 以下が1本だけ（AEM 2021-05 の 0.0 等）→ その本だけ欠けとして飛ばす。2本以上 → 最後の壊れた本までを捨てる（その後だけ使う）
    bad = sorted(k for k, v in px.items() if v <= 0)
    if len(bad) == 1:
        px.pop(bad[0])
    elif bad:
        px = {k: v for k, v in px.items() if k > bad[-1]}
    now = datetime.datetime.utcnow()
    px = {k: v for k, v in px.items() if k < now.year * 100 + now.month}
    ks = sorted(px)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:])}


def yh_load(t):
    """→ (月次リターン {yyyymm: r}, meta)。無ければ (None, None)。読めない JSON は大声で止める（黙って未観測にしない）"""
    p = yh_name(t)
    if not os.path.exists(p):
        return None, None
    j = json.load(open(p))
    res = j['chart']['result']
    if not res:
        return None, None
    meta = res[0]['meta']
    if not res[0].get('timestamp'):
        return None, meta
    r = yh_parse(j)
    return (r or None), meta


def name_match(a, b):
    def toks(s):
        s = re.sub(r'\[[A-Z]{2}\]|\([^)]*\)', ' ', (s or '').lower())
        return [w for w in re.findall(r'[a-z0-9]+', s) if w not in STOP]
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return None
    if set(w for w in ta if len(w) >= 3) & set(w for w in tb if len(w) >= 3):
        return True
    return ta[0][:4] == tb[0][:4]




# ───────────────────────── 議員の名寄せ ─────────────────────────
SUFFIX = re.compile(r'\b(jr|sr|ii|iii|iv|md|dds|phd|hon)\b\.?', re.I)


def lastkey(s):
    s = SUFFIX.sub(' ', (s or '').lower())
    w = re.findall(r'[a-z]+', s)
    return w[-1] if w else ''


def member_maps():
    """下院: 自前 PDF の提出者（Clerk の Last・区）→ kadoa の filer_id。上院: kadoa/ssw の名前 → eFD の名前（姓が一意なら）"""
    fl = json.load(open(os.path.join(CT, 'kadoa_filers.json')))
    house = {}
    for x in fl:
        if x.get('chamber') != 'house':
            continue
        m = re.search(r'([A-Z]{2})-(\d+|AL)', x.get('office') or '')
        if m:
            house[(m.group(1) + m.group(2).lstrip('0').zfill(2) if m.group(2) != 'AL' else m.group(1) + 'AL', lastkey(x['full_name']))] = x['id']
    return house


def normalize_members(ev):
    house = member_maps()
    idx = json.load(open(os.path.join(CT, 'clerk_index.json')))
    hit = Counter()
    efd_by_last = defaultdict(set)
    for e in ev:
        if e['ch'] == 'senate' and e['src'] == 'efd':
            efd_by_last[e['member'].split('_')[1]].add(e['member'])
    for e in ev:
        if e['ch'] == 'house' and e['src'] == 'clerk_pdf':
            meta = idx.get(e['doc'], {})
            dst = meta.get('dst', '')
            m = re.fullmatch(r'([A-Z]{2})(\d+|AL)', dst)
            key = (m.group(1) + (m.group(2).lstrip('0').zfill(2) if m.group(2) != 'AL' else 'AL'), lastkey(meta.get('last'))) if m else None
            if key in house:
                e['member'] = house[key]; hit['house_mapped'] += 1
            else:
                hit['house_unmapped'] += 1
        if e['ch'] == 'senate' and e['src'] != 'efd':
            cands = efd_by_last.get(e['member_last'], set()) if e.get('member_last') else set()
            if len(cands) == 1:
                e['member'] = next(iter(cands)); hit['senate_mapped'] += 1
            else:
                hit['senate_unmapped'] += 1
    return hit


LEG = 'https://unitedstates.github.io/congress-legislators/{}'


def assign_party(ev):
    """事象に政党（'D'/'R'/'I'/None）を付ける。unitedstates/congress-legislators（current＋historical）の任期で、
    上院は姓（＋名の頭文字）、下院は州・区・姓で合わせる。kadoa の下院の事象は kadoa の党を使う。合わなければ None（数える）"""
    d = []
    for f in ('legislators-current.json', 'legislators-historical.json'):
        p = os.path.join(CT, f)
        if not os.path.exists(p):
            save_bytes(p, http_get(LEG.format(f)))
        d += json.load(open(p))
    P = {'Democrat': 'D', 'Republican': 'R', 'Independent': 'I'}
    sen, rep = defaultdict(list), defaultdict(list)
    for x in d:
        last = lastkey(x['name'].get('last')); first = (x['name'].get('first') or ' ')[0].lower()
        for t in x['terms']:
            if t['end'] < '2012-01-01':
                continue
            rec = (t['start'], t['end'], P.get(t.get('party'), None), first)
            if t['type'] == 'sen':
                sen[last].append(rec)
            else:
                dst = f"{t['state']}{'AL' if not t.get('district') else str(t['district']).zfill(2)}"
                rep[(dst, last)].append(rec)
    idx = json.load(open(os.path.join(CT, 'clerk_index.json')))
    fl = {x['id']: x for x in json.load(open(os.path.join(CT, 'kadoa_filers.json')))}
    hit = Counter()

    def pick(recs, day, first=None):
        ds = day.isoformat()
        c = {r[2] for r in recs if r[0] <= ds <= (datetime.date.fromisoformat(r[1]) + datetime.timedelta(days=120)).isoformat() and (first is None or r[3] == first)}
        return c.pop() if len(c) == 1 else None
    for e in ev:
        p = None
        if e['ch'] == 'house':
            if e['member'] in fl and fl[e['member']].get('party'):
                p = fl[e['member']]['party']
            elif e['src'] == 'clerk_pdf':
                meta = idx.get(e['doc'], {})
                m = re.fullmatch(r'([A-Z]{2})(\d+|AL)', meta.get('dst', ''))
                if m and e['filed']:
                    dst = m.group(1) + ('AL' if m.group(2) == 'AL' else m.group(2).lstrip('0').zfill(2))
                    p = pick(rep.get((dst, lastkey(meta.get('last'))), []), e['filed'])
        else:
            parts = e['member'].split('_')          # senate_<姓>_<名>
            if len(parts) >= 3 and e['filed']:
                recs = sen.get(parts[1], [])
                p = pick(recs, e['filed']) or pick(recs, e['filed'], (parts[2] or ' ')[0])
        e['party2'] = p if p in ('D', 'R', 'I') else None
        hit[e['ch'] + '_' + (e['party2'] or 'none')] += 1
    return hit


# ───────────────────────── 事象 → 持ち高 ─────────────────────────
def load_universe():
    """事象を読み、株かどうか・観測できるかを決める（リターンの値は使わない＝種類・系列の最初と最後・名前だけ）"""
    ev, extra = build_events()
    hit = normalize_members(ev)
    hit.update(assign_party(ev))
    keep, drop = [], Counter()
    for e in ev:
        if e['type'] not in ('P', 'S'):
            drop['type'] += 1; continue
        if e['filed'] is None:
            drop['nofiled'] += 1; continue
        if e['kind'] == 'other':
            drop['not_stock'] += 1; continue
        if not e['ticker']:
            drop['noticker'] += 1; continue
        if '-' in e['ticker'] and e['ticker'].split('-', 1)[1] not in CLASS_SUFFIX:
            drop['not_common_suffix'] += 1; continue      # 優先株（-PA 等）・新株予約権・発行日取引
        e['s'] = signal_month(e['filed'])
        e['tm'] = e['tdate'].year * 100 + e['tdate'].month if e['tdate'] else None
        if e['s'] > END - 1:
            drop['after_end'] += 1; continue
        keep.append(e)
    # 同じ議員×記号×種類×取引日×金額の下限＝同じ取引（修正の再提出・二つの元）→ 公開の早いほうだけ
    best = {}
    for e in keep:
        k = (e['ch'], e['member'], e['ticker'], e['type'], e['tdate'], e['lo'])
        if k not in best or e['filed'] < best[k]['filed']:
            best[k] = e
    dups = len(keep) - len(best)
    keep = list(best.values())
    # Yahoo（記号の変更: 手の RENAME ＋ 社名の完全一致で採った ct/rename_auto.json）
    REN = dict(RENAME)
    pa = os.path.join(CT, 'rename_auto.json')
    if os.path.exists(pa):
        for k, v in json.load(open(pa)).items():
            if v.get('accepted') and k not in REN and k not in REJECT_AUTO:
                REN[k] = v['accepted']
    yh, meta = {}, {}
    reuse_to = {to for v in REUSE.values() for _, _, to in v if to}
    for t in sorted({e['ticker'] for e in keep} | set(REN.values()) | reuse_to):
        r, mt = yh_load(t)
        yh[t], meta[t] = r, mt
    out, cls = [], Counter()
    for e in keep:
        s1 = madd(e['s'], 1)
        # (1) 記号の再利用（期間で決める・社名の有無に関係なく全事象に当てる）
        rz = [to for lo, hi, to in REUSE.get(e['ticker'], []) if lo <= e['s'] <= hi]
        if rz:
            to = rz[0]
            r2, mt2 = (yh.get(to), meta.get(to)) if to else (None, None)
            if to and r2 and (mt2 or {}).get('instrumentType') == 'EQUITY' and min(r2) <= s1 <= max(r2):
                e['renamed_from'] = e['ticker']; e['ticker'] = to; e['name'] = ''
                e['obs'] = e['obs2'] = True; e['why'] = 'reuse_remapped'
            else:
                e['obs'] = e['obs2'] = False; e['why'] = 'reused_ticker'
            cls[(e['type'], e['why'])] += 1
            out.append(e)
            continue
        # (2) 記号の変更（同じ会社）: 新しい記号の系列が公開月の翌月を含むなら、いつでも新しい記号を使う
        #     （旧 BBT のように『古い記号が今は別の会社の長い系列を持つ』例があるので、古い記号の系列の有無では決めない）
        if e['ticker'] in REN:
            nt = REN[e['ticker']]
            r2, mt2 = yh.get(nt), meta.get(nt)
            if r2 and (mt2 or {}).get('instrumentType') == 'EQUITY' and min(r2) <= s1 <= max(r2):
                e['renamed_from'] = e['ticker']; e['ticker'] = nt; e['name'] = ''     # 社名も変わっているので照合しない
        r, mt = yh[e['ticker']], meta[e['ticker']]
        it = (mt or {}).get('instrumentType')
        e['obs'] = e['obs2'] = False
        if not r:
            e['why'] = 'yahoo_none_' + e['kind']              # Yahoo に無い（上場廃止・記号の変更）＝未観測
        else:
            later = min(r) > madd(e['s'], 1)                  # 公開の月末の値が無い＝記号の再利用か、公開より後に上場
            ended = max(r) < madd(e['s'], 1)
            nm = (mt or {}).get('longName') or (mt or {}).get('shortName')
            ok = name_match(e['name'], nm) if e['name'] else None
            if it and it != 'EQUITY':
                if later or ok is False:
                    e['why'] = 'reused_by_fund'               # 今の記号は ETF/投信だが、当時は別の証券（未観測）
                else:
                    cls[(e['type'], 'not_equity_on_yahoo')] += 1   # ETF・投信＝株の選択ではない（事象から外す）
                    continue
            elif later:
                e['why'] = 'series_starts_later'
            elif ended:
                cls[(e['type'], 'ended_before_signal')] += 1   # 公開の時点で値が無い＝買えない（事象から外す・未観測にも数えない）
                continue
            elif ok is False:
                e['why'] = 'name_mismatch'; e['obs'] = True   # 主: 社名の照合はしない（改名の誤検出が多い: GE・SLB・RTX・WMT）。obs2 = 照合する版（報告のみ）
            else:
                e['obs'] = e['obs2'] = True; e['why'] = ('renamed' if e.get('renamed_from') else ('ok' if ok else 'ok_noname'))
        cls[(e['type'], e['why'])] += 1
        out.append(e)
    return out, yh, {'drop': dict(drop), 'dups': dups, 'extra_docs': dict(extra), 'member_map': dict(hit),
                     'classes': {f'{k[0]}_{k[1]}' if isinstance(k, tuple) else k: v for k, v in cls.items()}}


def clean_series(r):
    """月 +300% 超を誤りとみなし、その月以降を捨てる（その前の月で打ち切り）"""
    if r is None:
        return None, False
    ks = sorted(r)
    for k in ks:
        if r[k] > SPIKE:
            return {kk: r[kk] for kk in ks if kk < k}, True
    return r, False


def calendar_pf(events, H, yh, mkt, bound='S', weight='ew', loss=None, drop_tickers=()):
    """暦月のポートフォリオ（Jaffe/Mandelker）。events は選ばれた事象（公開月 s）。月 s+1〜s+H に持つ。
    bound: 'S'=観測できる社だけ / 'L'=未観測の事象と途中で消えた社に loss（−0.3 / −1.0）を一度だけ当てて外す。
    weight: 'ew'=記号ごとに等加重 / 'amt'=有効な事象の金額の中央値の合計で加重。持つ社が MIN_HOLD 未満の月は French Mkt"""
    ms = months(START, END)
    act = defaultdict(dict)       # 月 → {記号: 重みの素}
    phantom = defaultdict(Counter)
    cleaned = {}
    for e in events:
        if e['ticker'] in drop_tickers:
            continue
        w = 1.0
        if weight == 'amt':
            w = ((e['lo'] or 0) + (e['hi'] or e['lo'] or 0)) / 2 or 1000.0
        if e['obs']:
            t = e['ticker']
            if t not in cleaned:
                cleaned[t] = clean_series(yh[t])[0]
            r = cleaned[t]
            last = max(r) if r else None
            for k in range(1, H + 1):
                m = madd(e['s'], k)
                if m > END:
                    break
                if r and m in r:
                    act[m][t] = act[m].get(t, 0) + w
                elif bound == 'L' and last is not None and m > last:
                    pm = max(madd(last, 1), madd(e['s'], 1))
                    phantom[pm][t] = max(phantom[pm][t], w)   # 消えた翌月に一度だけ（公開より前には置かない）
                    break
                elif bound == 'M' and last is not None and m > last:
                    for k2 in range(k, H + 1):                  # 消えた後の残りの月を市場のリターンで持つ（中立の埋め・報告のみ）
                        m2 = madd(e['s'], k2)
                        if m2 <= END:
                            phantom[m2][t] = max(phantom[m2][t], w)
                    break
                else:
                    break
        elif bound == 'L':
            m = madd(e['s'], 1)
            if m <= END:
                phantom[m][('U', e['ticker'])] = max(phantom[m][('U', e['ticker'])], w)
        elif bound == 'M':
            for k in range(1, H + 1):
                m = madd(e['s'], k)
                if m <= END:
                    phantom[m][('U', e['ticker'])] = max(phantom[m][('U', e['ticker'])], w)
    out, n_hold, fallback = {}, {}, 0
    for m in ms:
        if m not in mkt:
            continue
        a = act.get(m, {})
        ph = {k: v for k, v in phantom.get(m, {}).items() if not (isinstance(k, str) and k in a)}
        wt = sum(a.values()) + sum(ph.values())
        n_hold[m] = len(a)
        if len(a) < MIN_HOLD or wt <= 0:
            out[m] = mkt[m]; fallback += 1
            continue
        lv = mkt[m] if bound == 'M' else loss
        if weight == 'ew':
            s = sum(cleaned[t][m] for t in a) + sum(lv for _ in ph)
            out[m] = s / (len(a) + len(ph))
        else:
            s = sum(w * cleaned[t][m] for t, w in a.items()) + sum(w * lv for w in ph.values())
            out[m] = s / wt
    return out, {'months': len(out), 'fallback_mkt_months': fallback, 'median_holdings': (S.median(n_hold.values()) if n_hold else None),
                 'min_holdings': min(n_hold.values()) if n_hold else None, 'max_holdings': max(n_hold.values()) if n_hold else None}


def cap_shares(w, cap):
    """{鍵: 重み} を比率にして、各比率を cap 以下に抑え、あふれた分を残りへ比例で配り直す（反復）"""
    tot = sum(w.values())
    if tot <= 0:
        return {}
    sh = {k: v / tot for k, v in w.items()}
    if cap is None or cap * len(sh) < 1:
        return sh                          # 名が少なすぎて上限を守れない月は上限なし（数える側で報告）
    fixed = {}
    while True:
        over = {k for k, v in sh.items() if k not in fixed and v > cap + 1e-12}
        if not over:
            return {**sh, **fixed}
        for k in over:
            fixed[k] = cap
        rest = {k: v for k, v in sh.items() if k not in fixed}
        left = 1 - cap * len(fixed)
        rt = sum(rest.values())
        sh = {k: v / rt * left for k, v in rest.items()} if rt > 0 else {}
        sh.update(fixed)


def calendar_pf2(events, H, yh, mkt, bound='S', weight='ew', loss=None, drop_tickers=(), cap_ticker=None, cap_member=None, min_hold=None, shares_out=None):
    """calendar_pf の一般化（事前登録2・2026-09-28）: 事象ごとの保有月数 e['H']、金額の重みの記号ごとの上限 cap_ticker、
    議員ごとの上限 cap_member（その月の重みの合計に対する比率）。それ以外は calendar_pf と同じ（同じ入力で同じ答えになることを検算する）"""
    ms = months(START, END)
    act = defaultdict(lambda: defaultdict(float))     # 月 → {(議員鍵, 記号): 重みの素}
    phantom = defaultdict(dict)                       # 月 → {(議員鍵, 記号 or ('U', 記号)): 重みの素}
    cleaned = {}
    for e in events:
        if e['ticker'] in drop_tickers:
            continue
        HH = e.get('H', H)
        w = ev_weight(e, weight)
        mk = e['member'] if cap_member else None
        if e['obs']:
            t = e['ticker']
            if t not in cleaned:
                cleaned[t] = clean_series(yh[t])[0]
            r = cleaned[t]
            last = max(r) if r else None
            for k in range(1, HH + 1):
                m = madd(e['s'], k)
                if m > END:
                    break
                if r and m in r:
                    act[m][(mk, t)] += w
                elif bound == 'L' and last is not None and m > last:
                    pm = max(madd(last, 1), madd(e['s'], 1))
                    phantom[pm][(mk, t)] = max(phantom[pm].get((mk, t), 0), w)
                    break
                elif bound == 'M' and last is not None and m > last:
                    for k2 in range(k, HH + 1):
                        m2 = madd(e['s'], k2)
                        if m2 <= END:
                            phantom[m2][(mk, t)] = max(phantom[m2].get((mk, t), 0), w)
                    break
                else:
                    break
        elif bound == 'L':
            m = madd(e['s'], 1)
            if m <= END:
                kk = (mk, ('U', e['ticker']))
                phantom[m][kk] = max(phantom[m].get(kk, 0), w)
        elif bound == 'M':
            for k in range(1, HH + 1):
                m = madd(e['s'], k)
                if m <= END:
                    kk = (mk, ('U', e['ticker']))
                    phantom[m][kk] = max(phantom[m].get(kk, 0), w)
    out, n_hold, fallback, capfail = {}, {}, 0, 0
    for m in ms:
        if m not in mkt:
            continue
        a = act.get(m, {})
        held = {t for _, t in a}
        # 消えた記号の空の持ち高は、同じ記号を別の事象でまだ持っていれば数えない（calendar_pf と同じ）。
        # 議員の鍵なし（cap_member=None）では calendar_pf と同じく記号ごとに1つ（重みは最大）に畳む
        ph = {}
        for (mk, t), w in phantom.get(m, {}).items():
            if isinstance(t, str) and t in held:
                continue
            key = (mk if cap_member else None, t)
            ph[key] = max(ph.get(key, 0), w)
        n_hold[m] = len(held)
        if len(held) < (MIN_HOLD if min_hold is None else min_hold) or (sum(a.values()) + sum(ph.values())) <= 0:
            out[m] = mkt[m]; fallback += 1
            continue
        lv = mkt[m] if bound == 'M' else loss
        val = lambda t: cleaned[t][m] if isinstance(t, str) and t in held else lv   # 空の持ち高（消えた記号・未観測）は loss / Mkt
        if weight == 'ew':
            names = list(held) + [k for k in ph]
            out[m] = (sum(cleaned[t][m] for t in held) + sum(lv for _ in ph)) / len(names)
            if shares_out is not None:
                shares_out[m] = {t: 1 / len(names) for t in held}
            continue
        items = defaultdict(float)
        for (mk, t), w in a.items():
            items[(mk, t)] += w
        for (mk, t), w in ph.items():
            items[(mk, ('P', t))] += w                # 空の持ち高は持っている記号とは別の名として数える
        if cap_member:
            memw = defaultdict(float)
            for (mk, _), w in items.items():
                memw[mk] += w
            msh = cap_shares(memw, cap_member)
            if cap_member * len(memw) < 1:
                capfail += 1
            items = {k: w / memw[k[0]] * msh[k[0]] for k, w in items.items() if memw[k[0]] > 0}
        tw = defaultdict(float)
        for (mk, t), w in items.items():
            tw[t] += w
        tsh = cap_shares(tw, cap_ticker)
        if cap_ticker and cap_ticker * len(tw) < 1:
            capfail += 1
        out[m] = sum(sh * (val(t[1]) if isinstance(t, tuple) and t and t[0] == 'P' else val(t)) for t, sh in tsh.items())
        if shares_out is not None:
            shares_out[m] = {t: sh for t, sh in tsh.items() if isinstance(t, str) and t in held}
    if shares_out is not None:
        shares_out['_cleaned'] = cleaned
    return out, {'months': len(out), 'fallback_mkt_months': fallback, 'cap_unenforceable_months': capfail,
                 'median_holdings': (S.median(n_hold.values()) if n_hold else None),
                 'min_holdings': min(n_hold.values()) if n_hold else None, 'max_holdings': max(n_hold.values()) if n_hold else None}


def dollar_concentration(P, k=10):
    """X5 の金額の重みの出どころ（観測済みの買いの金額の中点の合計に占める割合・議員別と記号別）。リターンは使わない（報告のみ）"""
    Po = [e for e in P if e['obs']]
    tot = sum(ev_weight(e, 'amt') for e in Po)
    bm, bt = Counter(), Counter()
    for e in Po:
        bm[e['member']] += ev_weight(e, 'amt'); bt[e['ticker']] += ev_weight(e, 'amt')
    return {'total_midpoint_usd_millions': round(tot / 1e6, 1),
            'top_members_pct': [(m, round(v / tot * 100, 1)) for m, v in bm.most_common(k)],
            'top_tickers_pct': [(t, round(v / tot * 100, 1)) for t, v in bt.most_common(k)],
            'largest_events': [{'member': e['member'], 'ticker': e['ticker'], 'filed': e['filed'].isoformat(), 'lo': e['lo'], 'hi': e['hi'], 'owner': e['owner']}
                               for e in sorted(Po, key=lambda e: -ev_weight(e, 'amt'))[:12]]}


def contributions2(shares, mkt, a, z):
    """calendar_pf2 の shares_out（S の囲み）から、記号ごとの超過への寄与（%/年）"""
    cl = shares['_cleaned']
    c = Counter()
    nmon = max(1, len([m for m in months(max(a, START), z) if m in mkt]))
    for m, sh in shares.items():
        if m == '_cleaned' or m < a or m > z or m not in mkt:
            continue
        for t, x in sh.items():
            c[t] += x * (cl[t][m] - mkt[m]) * 12 * 100 / nmon
    return c


def dollar_topn(P, SL, n=20, window=6, net=False, exclude=()):
    """事前登録2 Y1/Y2: 月 s の末に、公開月が s−window+1〜s の買いの金額（下限と上限の中点・上限なしは下限）を記号ごとに足し
    （net=True なら売りの金額を引いて正のものだけ）、上位 n 記号を選ぶ。続けて選ばれた月は1つの事象（保有月数 H=続いた月数）に畳む。
    観測は、窓の中の事象のどれかが観測済みならその記号を観測とする（consensus と同じ）"""
    by_s = defaultdict(list)
    for e in P:
        by_s[e['s']].append((e, 1))
    if net:
        for e in SL:
            by_s[e['s']].append((e, -1))
    ms = months(START - 100, END - 1)
    sel = {}
    for s in ms:
        amt, rep = defaultdict(float), {}
        for k in range(window):
            for e, sg in by_s.get(madd(s, -k), []):
                amt[e['ticker']] += sg * ev_weight(e, 'amt')
                if sg > 0 and (e['ticker'] not in rep or (e['obs'] and not rep[e['ticker']]['obs'])):
                    rep[e['ticker']] = e
        cand = sorted((t for t, v in amt.items() if v > 0 and t in rep and t not in exclude), key=lambda t: (-amt[t], t))[:n]
        sel[s] = {t: rep[t] for t in cand}
    out, run = [], {}
    for s in ms:
        cur = sel[s]
        for t in list(run):
            if t not in cur:
                out.append(run.pop(t))
        for t, e in cur.items():
            if t in run:
                run[t]['H'] += 1
            else:
                run[t] = {**e, 's': s, 'H': 1}
    out += list(run.values())
    # 実際の片道の回転率（名の入れ替わり×12 ＋ 等加重のつけ直し30%）
    ch = [len(set(sel[s]) - set(sel[madd(s, -1)])) / max(1, len(sel[s])) for s in ms[1:] if sel[s] and sel.get(madd(s, -1))]
    turn = round((S.mean(ch) * 12 if ch else 0) + 0.3, 2)
    return out, turn, sel


def track_filter(P, yh, mkt, top_frac=1 / 3, lookback=36, min_n=5, h=6):
    """月 s の末に分かる議員の実績（過去の買いの h か月の買って持つ超過の平均）で上位 top_frac の議員の、月 s の買いだけを残す"""
    recs = defaultdict(list)       # 議員 → [(s′, g)]
    cl = {}
    for e in P:
        if not e['obs']:
            continue
        t = e['ticker']
        if t not in cl:
            cl[t] = clean_series(yh[t])[0]
        r = cl[t]
        ms = [madd(e['s'], k) for k in range(1, h + 1)]
        if r and all(m in r and m in mkt and m <= END for m in ms):
            gs = math.prod(1 + r[m] for m in ms) - math.prod(1 + mkt[m] for m in ms)
            recs[e['member']].append((e['s'], gs))
    out, info = [], Counter()
    for s in sorted({e['s'] for e in P}):
        sc = {}
        for mem, xs in recs.items():
            v = [g for s2, g in xs if madd(s, -lookback) <= s2 and madd(s2, h) <= s]   # ★ 旧: s - lookback（yyyymm の整数から36を引いていた＝実質 数か月しか見ていなかった）
            if len(v) >= min_n:
                sc[mem] = S.mean(v)
        if not sc:
            continue
        top = set(sorted(sc, key=lambda k: -sc[k])[:max(1, math.ceil(len(sc) * top_frac))])
        sel = [e for e in P if e['s'] == s and e['member'] in top]
        info['months'] += 1; info['events'] += len(sel)
        out += sel
    return out


def consensus(events, members=2, days=90):
    """公開月 s の末に、直近 days 日（公開日＝提出日＋LAG_DAYS）に買いを公開した議員が members 人以上いる記号 → 月 s の事象"""
    by_t = defaultdict(list)
    for e in events:
        by_t[e['ticker']].append(e)
    out = []
    for t, es in by_t.items():
        es.sort(key=lambda e: e['filed'])
        for s in sorted({e['s'] for e in es}):
            y, mo = divmod(s, 100)
            me = datetime.date(y + (mo == 12), mo % 12 + 1, 1) - datetime.timedelta(days=1)
            win = [e for e in es if me - datetime.timedelta(days=days) < e['filed'] + datetime.timedelta(days=LAG_DAYS) <= me]
            mem = {e['member'] for e in win}
            if len(mem) >= members:
                obs = any(e['obs'] for e in win)
                rep = next(e for e in win if e['obs']) if obs else win[0]
                out.append({**rep, 's': s})
    return out


# ───────────────────────── 統計の追加部品 ─────────────────────────
def ols_nw(y, X, lag=12):
    """y = a + X b。Newey-West の t。→ {'alpha_ann_pct', 't_alpha', 'betas', 't_betas', 'n', 'r2'}"""
    import numpy as np
    y = np.asarray(y, float); X = np.column_stack([np.ones(len(y))] + [np.asarray(c, float) for c in X])
    n, k = X.shape
    if n < 24:
        return None
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    Sg = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        Sg += w * (G + G.T)
    V = XtXi @ Sg @ XtXi
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / (((y - y.mean()) ** 2).sum())
    return {'alpha_ann_pct': round(float(b[0]) * 1200, 2), 't_alpha': round(float(b[0] / se[0]), 2),
            'betas': [round(float(x), 3) for x in b[1:]], 't_betas': [round(float(x), 2) for x in (b[1:] / se[1:])], 'n': n, 'r2': round(float(r2), 3)}


def regressions(r, fac, a=None, z=None):
    ks = sorted(k for k in r if k in fac['mktrf'] and k in fac['rf'] and (a is None or k >= a) and (z is None or k <= z))
    ks5 = [k for k in ks if all(k in fac[c] for c in ('smb', 'hml', 'rmw', 'cma', 'mom'))]
    ksq = [k for k in ks if k in fac['qqq'] and k in fac['mkt']]
    y = lambda kk: [r[k] - fac['rf'][k] for k in kk]
    out = {'capm': ols_nw(y(ks), [[fac['mktrf'][k] for k in ks]]),
           'ff5_mom': ols_nw(y(ks5), [[fac[c][k] for k in ks5] for c in ('mktrf', 'smb', 'hml', 'rmw', 'cma', 'mom')]),
           'mkt_plus_qqq_minus_mkt': ols_nw(y(ksq), [[fac['mktrf'][k] for k in ksq], [fac['qqq'][k] - fac['mkt'][k] for k in ksq]])}
    if out['ff5_mom']:
        out['ff5_mom']['factors'] = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom']
    if out['mkt_plus_qqq_minus_mkt']:
        out['mkt_plus_qqq_minus_mkt']['factors'] = ['Mkt-RF', 'QQQ-Mkt']
    return out


def ev_weight(e, weight):
    if weight == 'amt':
        return ((e['lo'] or 0) + (e['hi'] or e['lo'] or 0)) / 2 or 1000.0
    return 1.0


def holdings_w(events, H, yh, weight='ew'):
    """S（観測のみ）の月ごとの持ち高 {月: {記号: 重みの素}}（calendar_pf の S と同じ積み方）と、打ち切り後の系列"""
    act = defaultdict(dict)
    cl = {}
    for e in events:
        if not e['obs']:
            continue
        t = e['ticker']
        if t not in cl:
            cl[t] = clean_series(yh[t])[0]
        w = ev_weight(e, weight)
        for k in range(1, H + 1):
            m = madd(e['s'], k)
            if m > END or not cl[t] or m not in cl[t]:
                break
            act[m][t] = act[m].get(t, 0) + w
    return act, cl


def contributions(events, H, yh, mkt, a, z, weight='ew'):
    """S（観測のみ）の、記号ごとの超過への寄与（Σ_月 w_i/W × (r_i − Mkt)・年率 %）。
    ★ 2026-09-28 事後の直し（報告のみ・格に不使用）: 旧版は X5（金額で加重）でも等加重の寄与を出していた→加重を合わせた"""
    act, cl = holdings_w(events, H, yh, weight)
    c = Counter()
    nmon = max(1, len([m for m in months(max(a, START), z) if m in mkt]))
    for m, ws in act.items():
        if m not in mkt or len(ws) < MIN_HOLD or m < a or m > z:
            continue
        W = sum(ws.values()) if weight == 'amt' else len(ws)
        for t, w in ws.items():
            c[t] += (cl[t][m] - mkt[m]) * ((w if weight == 'amt' else 1.0) / W) * 12 * 100 / nmon
    return c


MEGA = {'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'GOOG', 'META', 'FB', 'TSLA', 'AVGO'}


def mega_share(events, H, yh, weight='ew'):
    """巨大株が持ち高に占める割合（月の平均）。weight='amt' は金額の重みで（事後の直し・報告のみ）"""
    act, _ = holdings_w(events, H, yh, weight)
    sh = []
    for m, ws in act.items():
        if len(ws) < MIN_HOLD:
            continue
        W = sum(ws.values()) if weight == 'amt' else len(ws)
        sh.append(sum((ws[t] if weight == 'amt' else 1.0) for t in ws if t in MEGA) / W)
    return round(S.mean(sh), 3) if sh else None


def block(r, mkt, spy, qqq, turnover, cost):
    st = lambda b, a=None, z=None: M.excess_stats(r, b, a, z)
    hold = st(mkt, M.HOLD_START, END)
    return {'full': st(mkt, None, END), 'train': st(mkt, None, M.TRAIN_END), 'hold': hold, 'recent': st(mkt, M.RECENT_START, END),
            'net_cost_hold': M.excess_stats(M.apply_cost(r, turnover, cost), mkt, M.HOLD_START, END),
            'sub_2014_2019': st(mkt, 201401, 201912), 'sub_2020_2026': st(mkt, 202001, END),
            'vs_spy_hold': st(spy, M.HOLD_START, END), 'vs_qqq_hold': st(qqq, M.HOLD_START, END),
            'rolling20': M.rolling(r, mkt, 20), 'dca20': M.dca(r, mkt, 20),
            'rolling5_report_only': M.rolling(r, mkt, 5), 'dca5_report_only': M.dca(r, mkt, 5, step=6),
            'maxdd': round(M.maxdd({k: v for k, v in r.items() if k <= END}) * 100, 1), 'maxdd_mkt_same_months': round(M.maxdd({k: mkt[k] for k in r if k in mkt and k <= END}) * 100, 1)}


def measurable_only(c):
    """訓練期間と20年窓が原理的に測れない角度で、測れる線だけを並べる（格ではない・参考）"""
    return {k: c[k] for k in ('C2_hold_sign', 'C3_hold_t', 'C6_net_cost', 'C7_multi')}


GORDER = {'S': 0, 'A': 1, 'B': 2, 'C': 3}


def run():
    pre = json.load(open(os.path.join(M.BASE, 'out', PRE)))
    try:
        sha = subprocess.run(['git', 'log', '-1', '--format=%h', '--', f'out/{PRE}'], cwd=M.BASE, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        sha = None
    ff = M.ff_factors()
    mkt, rf = ff['mkt'], ff['rf']
    t5 = [v for k, v in M.french_tables('F-F_Research_Data_5_Factors_2x3').items() if v['freq'] == 'monthly'][0]
    tm = [v for k, v in M.french_tables('F-F_Momentum_Factor').items() if v['freq'] == 'monthly'][0]
    fac = {'mktrf': ff['mktrf'], 'rf': rf, 'mkt': mkt}
    for i, c in enumerate(t5['cols']):
        cc = c.lower().replace('-', '')
        if cc in ('smb', 'hml', 'rmw', 'cma'):
            fac[cc] = {d: row[i] / 100 for d, row in t5['data'].items() if row[i] is not None}
    fac['mom'] = {d: row[0] / 100 for d, row in tm['data'].items() if row[0] is not None}
    spy, qqq = M.yahoo('SPY'), M.yahoo('QQQ')
    fac['qqq'] = qqq
    ev, yh, info = load_universe()
    P = [e for e in ev if e['type'] == 'P']
    SL = [e for e in ev if e['type'] == 'S']
    spikes = sum(1 for t in {e['ticker'] for e in ev if e['obs']} if clean_series(yh[t])[1])
    # 戦略の定義（事前登録と同じ）
    Hp = lambda es, H: (es, H)
    strat = {
        'A6_all_buys_h6': ('primary', 'すべての買いの公開をまね、6か月持つ（等加重・暦月）', P, 6, 2.3),
        'A12_all_buys_h12': ('primary', 'すべての買いの公開をまね、12か月持つ（等加重・暦月）', P, 12, 1.3),
        'D6_consensus2_h6': ('primary', '直近90日に2人以上の議員が買いを公開した株を6か月持つ', consensus(P, 2, 90), 6, 2.3),
        'D12_consensus2_h12': ('primary', '直近90日に2人以上の議員が買いを公開した株を12か月持つ', consensus(P, 2, 90), 12, 1.3),
        'X1_house_buys_h12': ('exploratory', '下院の買いだけ・12か月', [e for e in P if e['ch'] == 'house'], 12, 1.3),
        'X2_senate_buys_h12': ('exploratory', '上院の買いだけ・12か月', [e for e in P if e['ch'] == 'senate'], 12, 1.3),
        'X3_large_buys_h12': ('exploratory', '金額の下限が 5万ドル超（$50,001〜）の買いだけ・12か月', [e for e in P if (e['lo'] or 0) >= 50001], 12, 1.3),
        'X4_prompt_buys_h12': ('exploratory', '取引から30日以内に公開された買いだけ・12か月', [e for e in P if e['tdate'] and (e['filed'] - e['tdate']).days <= 30], 12, 1.3),
        'X5_amount_weighted_h12': ('exploratory', 'すべての買い・12か月・金額の中央値で加重（毎月つけ直し）', P, 12, 1.3),
        'X6_consensus3_h12': ('exploratory', '直近90日に3人以上が買いを公開した株を12か月持つ', consensus(P, 3, 90), 12, 1.3),
        'X7_track_record_top_third_h12': ('exploratory', '過去36か月の買いの6か月超過の平均で上位1/3の議員の買いだけ・12か月', track_filter(P, yh, mkt), 12, 1.3),
        'X8_dem_buys_h12': ('exploratory', '民主党の議員の買いだけ・12か月（NANC の考え方を事象の単位で）', [e for e in P if e.get('party2') == 'D'], 12, 1.3),
        'X9_rep_buys_h12': ('exploratory', '共和党の議員の買いだけ・12か月（KRUZ/GOP の考え方を事象の単位で）', [e for e in P if e.get('party2') == 'R'], 12, 1.3),
        'X10_all_buys_h3': ('exploratory', 'すべての買いの公開をまね、3か月持つ（短い保有）', P, 3, 4.3),
        'B6_all_sales_h6': ('diagnostic', '売りの公開（売った株を6か月持つ＝空売りの診断・報告のみ）', SL, 6, 2.3),
        'B12_all_sales_h12': ('diagnostic', '売りの公開（売った株を12か月持つ＝空売りの診断・報告のみ）', SL, 12, 1.3),
        'T12_buys_trade_date_h12': ('diagnostic', '買いを取引月の末から12か月（公開前＝実行できない・情報の有無の診断のみ）',
                                    [{**e, 's': e['tm']} for e in P if e['tm'] and e['tm'] >= 201301], 12, 1.3),
    }
    tested, recs = [], {}
    series_out = {}
    for sid, (fam, desc, es, H, turn) in strat.items():
        wt = 'amt' if sid.startswith('X5') else 'ew'
        b = {}
        meta_pf = {}
        for bd, loss in (('S', None), ('L30', -0.30), ('L100', -1.0), ('M_neutral_report_only', None)):
            r, mp = calendar_pf(es, H, yh, mkt, bound={'S': 'S', 'M_neutral_report_only': 'M'}.get(bd, 'L'), weight=wt, loss=loss)
            b[bd] = block(r, mkt, spy, qqq, turn, 0.003)
            meta_pf[bd] = mp
            if bd == 'S':
                series_out[sid] = {k: round(v, 5) for k, v in sorted(r.items())}
                rS = r
        if fam == 'primary':
            rN, _ = calendar_pf([{**e, 'obs': e['obs2']} for e in es], H, yh, mkt, bound='S', weight=wt)
            b['S_namecheck_report_only'] = block(rN, mkt, spy, qqq, turn, 0.003)   # 社名が合わない事象も未観測にする版（報告のみ）
        rec = {'id': sid, 'family': fam, 'description': desc, 'hold_months': H, 'weighting': wt,
               'turnover_oneway_per_year': turn, 'cost_per_unit': 0.003,
               'n_events': len(es), 'n_events_observed': sum(1 for e in es if e['obs']),
               'observed_share': round(sum(1 for e in es if e['obs']) / len(es), 3) if es else None,
               'n_tickers': len({e['ticker'] for e in es}), 'portfolio': meta_pf, 'bounds': b,
               'mega7_share_of_holdings': mega_share(es, H, yh, wt),
               'regressions_S_hold': regressions(rS, fac, M.HOLD_START, END)}
        if sid in ('A6_all_buys_h6', 'A12_all_buys_h12', 'D6_consensus2_h6', 'D12_consensus2_h12') or fam == 'exploratory':
            c = contributions(es, H, yh, mkt, M.HOLD_START, END, weight=wt)
            top = [t for t, _ in c.most_common(5)]
            r5, _ = calendar_pf(es, H, yh, mkt, bound='S', weight=wt, drop_tickers=set(top))
            rec['top5_contributors'] = [{'ticker': t, 'contrib_pp_per_year': round(c[t], 2)} for t in top]
            rec['drop_top5_S_hold'] = M.excess_stats(r5, mkt, M.HOLD_START, END)
            rec['drop_top5_S_hold_net_cost'] = M.excess_stats(M.apply_cost(r5, turn, 0.003), mkt, M.HOLD_START, END)
        recs[sid] = rec
    # 買い−売り（診断）
    ra, _ = calendar_pf(P, 12, yh, mkt, 'S'); rb, _ = calendar_pf(SL, 12, yh, mkt, 'S')
    zero = {k: 0.0 for k in ra}
    ls = {k: ra[k] - rb[k] for k in ra if k in rb}
    recs['LS12_buys_minus_sales'] = {'id': 'LS12_buys_minus_sales', 'family': 'diagnostic', 'description': '買いの12か月 − 売りの12か月（S・差のポートフォリオ・相手は0）',
                                     'hold': M.excess_stats(ls, zero, M.HOLD_START, END)}
    # 実在の器
    for sid, tk in (('R1_NANC', 'NANC'), ('R2_KRUZ', 'GOP')):     # KRUZ は 2025-03-21 に GOP へ記号変更（Yahoo は GOP に履歴を持つ）
        r = M.yahoo(tk)
        r = {k: v for k, v in r.items() if k <= END}
        recs[sid] = {'id': sid, 'family': 'real', 'description': f'{tk}（Subversive/Unusual Whales の議員の売買をまねる ETF・2023-02 上場。GOP は旧 KRUZ）を買って持つ',
                     'bounds': {'S': block(r, mkt, spy, qqq, 0.0, 0.0)}, 'regressions_hold': regressions(r, fac, M.HOLD_START, END),
                     'first_month': min(r), 'n_months': len(r)}
        series_out[sid] = {k: round(v, 5) for k, v in sorted(r.items())}
    # ── 事前登録2（探索2・診断2）: 事前登録1の結果を見た後に作った族（out/mw_congress_trades_prereg2.json）──
    PRE2 = 'mw_congress_trades_prereg2.json'
    sha2 = None
    if os.path.exists(os.path.join(M.BASE, 'out', PRE2)):
        try:
            sha2 = subprocess.run(['git', 'log', '-1', '--format=%h', '--', f'out/{PRE2}'], cwd=M.BASE, capture_output=True, text=True).stdout.strip() or None
        except Exception:  # noqa
            sha2 = None
        y1, t1, _ = dollar_topn(P, SL, 20, 6, net=False)
        y2, t2, _ = dollar_topn(P, SL, 20, 6, net=True)
        strat2 = {
            'Y1_top20_dollar_buys_6m': ('exploratory2', '直近6か月に公開された買いの金額の上位20社を等加重（毎月選び直し）', y1, 1, 'ew', t1, {}),
            'Y2_top20_net_dollar_6m': ('exploratory2', '直近6か月の（買い−売り）の金額の上位20社を等加重（毎月選び直し）', y2, 1, 'ew', t2, {}),
            'Y3_X5_cap5pct': ('exploratory2', 'X5（買い全部・12か月・金額で加重）に1社5%の上限', P, 12, 'amt', 1.3, {'cap_ticker': 0.05}),
            'Y4_X5_ex_mega': ('exploratory2', 'X5 から巨大株10社を除く', [e for e in P if e['ticker'] not in MEGA], 12, 'amt', 1.3, {}),
            'Y5_X5_member_cap10pct': ('exploratory2', 'X5 に1議員10%の上限', P, 12, 'amt', 1.3, {'cap_member': 0.10}),
            'Y6_pelosi_buys_h12': ('diagnostic2', '★後知恵の名指し: Pelosi（配偶者）の株の買いを12か月・等加重（持つ社の最低数1）',
                                   [e for e in P if e['member'] == 'house_nancy_pelosi'], 12, 'ew', 1.3, {'min_hold': 1}),
        }
        for sid, (fam, desc, es, H, wt, turn, kw) in strat2.items():
            b, meta_pf = {}, {}
            for bd, loss in (('S', None), ('L30', -0.30), ('L100', -1.0), ('M_neutral_report_only', None)):
                sh = {} if bd == 'S' else None
                r, mp = calendar_pf2(es, H, yh, mkt, bound={'S': 'S', 'M_neutral_report_only': 'M'}.get(bd, 'L'), weight=wt, loss=loss, shares_out=sh, **kw)
                b[bd] = block(r, mkt, spy, qqq, turn, 0.003)
                meta_pf[bd] = mp
                if bd == 'S':
                    series_out[sid] = {k: round(v, 5) for k, v in sorted(r.items())}
                    rS, shS = r, sh
            c = contributions2(shS, mkt, M.HOLD_START, END)
            top = [t for t, _ in c.most_common(5)]
            r5, _ = calendar_pf2(es, H, yh, mkt, bound='S', weight=wt, drop_tickers=set(top), **kw)
            msh = [sum(x for t, x in v.items() if t in MEGA) for m, v in shS.items() if m != '_cleaned']
            recs[sid] = {'id': sid, 'family': fam, 'prereg': PRE2, 'description': desc, 'hold_months': H if not sid.startswith(('Y1', 'Y2')) else '毎月選び直し（続く限り持つ）',
                         'weighting': wt, 'caps': kw, 'turnover_oneway_per_year': turn, 'cost_per_unit': 0.003,
                         'n_events': len(es), 'n_events_observed': sum(1 for e in es if e['obs']),
                         'observed_share': round(sum(1 for e in es if e['obs']) / len(es), 3) if es else None,
                         'n_tickers': len({e['ticker'] for e in es}), 'portfolio': meta_pf, 'bounds': b,
                         'mega7_share_of_holdings': round(S.mean(msh), 3) if msh else None,
                         'regressions_S_hold': regressions(rS, fac, M.HOLD_START, END),
                         'top5_contributors': [{'ticker': t, 'contrib_pp_per_year': round(c[t], 2)} for t in top],
                         'drop_top5_S_hold': M.excess_stats(r5, mkt, M.HOLD_START, END),
                         'drop_top5_S_hold_net_cost': M.excess_stats(M.apply_cost(r5, turn, 0.003), mkt, M.HOLD_START, END)}
    # ── 事前登録3（探索3・頑丈さの格子）: 事前登録2の結果を見た後に作った族（out/mw_congress_trades_prereg3.json）──
    PRE3 = 'mw_congress_trades_prereg3.json'
    sha3, grid = None, None
    if os.path.exists(os.path.join(M.BASE, 'out', PRE3)):
        try:
            sha3 = subprocess.run(['git', 'log', '-1', '--format=%h', '--', f'out/{PRE3}'], cwd=M.BASE, capture_output=True, text=True).stdout.strip() or None
        except Exception:  # noqa
            sha3 = None
        strat3 = {}
        for N in (10, 20, 50):
            for W in (3, 6, 12):
                if (N, W) == (20, 6):
                    continue
                strat3[f'Z_N{N}_W{W}'] = (N, W, ())
        strat3['Z_N20_W6_ex_mega'] = (20, 6, MEGA)
        for sid, (N, W, exc) in strat3.items():
            es, turn, _ = dollar_topn(P, SL, N, W, net=False, exclude=exc)
            b, meta_pf = {}, {}
            for bd, loss in (('S', None), ('L30', -0.30), ('L100', -1.0), ('M_neutral_report_only', None)):
                sh = {} if bd == 'S' else None
                r, mp = calendar_pf2(es, 1, yh, mkt, bound={'S': 'S', 'M_neutral_report_only': 'M'}.get(bd, 'L'), weight='ew', loss=loss, shares_out=sh, min_hold=N // 2)
                b[bd] = block(r, mkt, spy, qqq, turn, 0.003)
                meta_pf[bd] = mp
                if bd == 'S':
                    series_out[sid] = {k: round(v, 5) for k, v in sorted(r.items())}
                    rS, shS = r, sh
            c = contributions2(shS, mkt, M.HOLD_START, END)
            top = [t for t, _ in c.most_common(5)]
            r5, _ = calendar_pf2(es, 1, yh, mkt, bound='S', weight='ew', drop_tickers=set(top), min_hold=N // 2)
            msh = [sum(x for t, x in v.items() if t in MEGA) for m, v in shS.items() if m != '_cleaned']
            recs[sid] = {'id': sid, 'family': 'exploratory3', 'prereg': PRE3, 'min_hold': N // 2,
                         'description': f'直近{W}か月に公開された買いの金額の上位{N}社を等加重（毎月選び直し）' + ('・巨大株10社を除く' if exc else ''),
                         'hold_months': '毎月選び直し（続く限り持つ）', 'weighting': 'ew', 'N': N, 'window_months': W,
                         'turnover_oneway_per_year': turn, 'cost_per_unit': 0.003,
                         'n_events': len(es), 'n_events_observed': sum(1 for e in es if e['obs']),
                         'observed_share': round(sum(1 for e in es if e['obs']) / len(es), 3) if es else None,
                         'n_tickers': len({e['ticker'] for e in es}), 'portfolio': meta_pf, 'bounds': b,
                         'mega7_share_of_holdings': round(S.mean(msh), 3) if msh else None,
                         'regressions_S_hold': regressions(rS, fac, M.HOLD_START, END),
                         'top5_contributors': [{'ticker': t, 'contrib_pp_per_year': round(c[t], 2)} for t in top],
                         'drop_top5_S_hold': M.excess_stats(r5, mkt, M.HOLD_START, END)}
        gids = [k for k in recs if k.startswith('Z_N') and not k.endswith('ex_mega')] + (['Y1_top20_dollar_buys_6m'] if 'Y1_top20_dollar_buys_6m' in recs else [])
        g = {bd: [recs[k]['bounds'][bd]['hold'] for k in gids] for bd in ('S', 'M_neutral_report_only', 'L30')}
        grid = {'members': gids,
                **{bd: {'n': len(v), 'n_positive': sum(1 for x in v if x['ex_ann'] > 0), 'median_ex_ann': S.median(x['ex_ann'] for x in v),
                        'median_t': S.median(x['t'] for x in v), 'min_ex_ann': min(x['ex_ann'] for x in v), 'max_ex_ann': max(x['ex_ann'] for x in v)} for bd, v in g.items()}}
        grid['robust_by_prereg3_rule'] = bool(grid['S']['n_positive'] == grid['S']['n'] and grid['M_neutral_report_only']['n_positive'] == grid['M_neutral_report_only']['n']
                                             and grid['S']['median_t'] >= 1.65)
    # 判定（Holm は族ごと・p は S と L30 の悪いほう）
    fams = defaultdict(dict)
    for sid, rec in recs.items():
        if rec['family'] in ('primary', 'exploratory', 'real', 'exploratory2', 'exploratory3'):
            ps = [rec['bounds'][bd]['hold']['p'] for bd in ('S', 'L30') if bd in rec['bounds'] and rec['bounds'][bd]['hold']]
            fams[rec['family']][sid] = max(ps) if ps else None
    holm = {f: M.holm(v) for f, v in fams.items()}
    for sid, rec in recs.items():
        if rec['family'] in ('diagnostic', 'diagnostic2'):
            rec['grade'] = '診断（格付けなし）'
            tested.append(rec); continue
        gs, cs = {}, {}
        for bd in ('S', 'L30'):
            if bd not in rec['bounds']:
                continue
            x = rec['bounds'][bd]
            g, c = M.grade(x['full'], x['train'], x['hold'], x['rolling20'], cost_hold=x['net_cost_hold'], repl=None,
                           family_holm_p=holm[rec['family']].get(sid))
            gs[bd], cs[bd] = g, c
        signs = {bd: (rec['bounds'][bd]['hold'] or {}).get('ex_ann', 0) > 0 for bd in gs}
        worst = max(gs.values(), key=lambda g: GORDER[g])
        rec['grade_by_bound'] = gs
        rec['criteria_by_bound'] = cs
        rec['holm_p_hold'] = holm[rec['family']].get(sid)
        rec['measurable_only_by_bound'] = {bd: measurable_only(c) for bd, c in cs.items()}
        if len(set(signs.values())) > 1:
            rec['grade'] = 'C'; rec['grade_note'] = '判定不能（S と L30 で保有期間の超過の符号が割れた）→ C'
        else:
            rec['grade'] = worst
        rec['grade_note'] = rec.get('grade_note', '') + ' 訓練期間（〜2006）のデータが無い＝C1 は原理的に不合格。20年窓も無い＝C4 も不合格。格は構造的に C が上限'
        if rec['family'] == 'exploratory':
            rec['grade_note'] += '（探索の族）'
        if rec['family'] == 'exploratory2':
            rec['grade_note'] += '（探索2＝事前登録1の結果を見た後に作った族。独立の確かめではない）'
        if rec['family'] == 'exploratory3':
            rec['grade_note'] += '（探索3＝事前登録2の結果を見た後に作った頑丈さの格子。独立の確かめではない）'
        tested.append(rec)
    # 検算
    sanity = {'french_mkt_cagr_full': round(M.cagr(mkt) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2),
              'spy_vs_mkt_2014_2026': M.excess_stats(spy, mkt, 201401, END), 'qqq_vs_mkt_2014_2026': M.excess_stats(qqq, mkt, 201401, END),
              'spike_truncated_tickers': spikes,
              'note': '総リターン（Yahoo 調整後終値）どうし・French Mkt も Mkt-RF + RF の総リターン。事象は公開月 s の末に買い s+1 から持つ（提出日＋5日で s を決める）'}
    cov = coverage_table(ev, info)
    out = {'angle': 'congress_trades', 'prereg': PRE, 'prereg_commit': sha, 'prereg2': PRE2 if sha2 else None, 'prereg2_commit': sha2,
           'prereg3': PRE3 if sha3 else None, 'prereg3_commit': sha3, 'grid_prereg3': grid,
           'x5_dollar_concentration_report_only': dollar_concentration(P),
           'generated': datetime.date.today().isoformat(),
           'question': pre.get('question'), 'data_end': END, 'start': START, 'n_tested': len([t for t in tested]),
           'tested': tested, 'universe': info, 'coverage': cov, 'sanity': sanity, 'series_S_monthly': series_out}
    p = M.save(OUT, out)
    print('書いた', p)
    for rec in tested:
        s = (rec.get('bounds') or {}).get('S', {}).get('hold') if 'bounds' in rec else rec.get('hold')
        l = (rec.get('bounds') or {}).get('L30', {}).get('hold') if 'bounds' in rec else None
        print(f"{rec['id']:28s} {str(rec.get('grade')):10s} S {s and (s['ex_ann'], s['t'], s['cagr_diff'])}  L30 {l and (l['ex_ann'], l['t'], l['cagr_diff'])}")


def coverage_table(ev, info):
    idx = json.load(open(os.path.join(CT, 'clerk_index.json')))
    kd = kadoa_house_docs()
    fill = {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(CT, 'clerk_pdf', '*.json')) if json.load(open(f)).get('role') == 'fill'}
    h = defaultdict(Counter)
    for k, v in idx.items():
        y = v['year']
        el = k.startswith('2')
        h[y]['ptr_filings'] += 1
        h[y]['electronic'] += el
        h[y]['paper_unreadable'] += (not el)
        h[y]['electronic_in_kadoa'] += (el and k in kd)
        h[y]['electronic_read_by_us'] += (el and k in fill)
    s = defaultdict(Counter)
    for f in glob.glob(os.path.join(CT, 'efd', 'list_*.json')):
        for r in json.load(open(f)):
            y = int(r[4][-4:])
            s[y]['ptr_filings'] += 1
            s[y]['electronic' if '/ptr/' in r[3] else 'paper_unreadable'] += 1
    e = defaultdict(Counter)
    for x in ev:
        y = x['filed'].year
        e[(x['ch'], y)][f"{x['type']}_{'obs' if x['obs'] else 'unobs'}"] += 1
    return {'house_filings_by_year': {y: dict(v) for y, v in sorted(h.items())}, 'senate_filings_by_year': {y: dict(v) for y, v in sorted(s.items())},
            'stock_events_by_chamber_year': {f'{k[0]}_{k[1]}': dict(v) for k, v in sorted(e.items())},
            'note': '下院の紙の PTR（スキャン）と上院の紙の PTR は読めない（OCR なし）。2012-13 は上院が全部紙・下院の電子 PTR は 2014 年から。Alpha Vantage の CONGRESS_TRADES は1日25回の上限に達しており、FMP の senate/house 取引は今の契約で拒否＝突き合わせに使えなかった'}


def main_cli():
    a = sys.argv[1:]
    if '--fetch-kadoa' in a:
        fetch_kadoa()
    if '--fetch-senate' in a:
        fetch_senate()
    if '--fetch-clerk' in a:
        fetch_clerk()
    if '--coverage' in a:
        cmd_coverage()
    if '--search-renames' in a:
        search_renames()
    if '--fetch-yh' in a:
        ev, _ = build_events()
        tk = {e['ticker'] for e in ev if e['ticker'] and e['type'] in ('P', 'S') and e['kind'] in ('stock', 'unknown')}
        force = set()
        if '--recheck' in a:     # 404 と、途中で切れた疑いの系列（2026年に始まる12本以下）をもう一度だけ取り直す
            for f in ('yh404.json', 'yh_suspect.json'):
                p = os.path.join(CT, f)
                if os.path.exists(p):
                    force |= set(json.load(open(p)))
            json.dump([], open(os.path.join(CT, 'yh404.json'), 'w'))
        fetch_yh(tk | set(BENCH_ETF) | set(RENAME.values()), force=force)
    if not any(x.startswith('--') for x in a):
        run()



def ntoks(s):
    s = re.sub(r'\[[A-Za-z]{2}\]|\([^)]*\)', ' ', (s or '').lower()).replace('&#x27;', "'")
    return frozenset(w for w in re.findall(r'[a-z0-9]+', s) if w not in STOP and w not in ('nyse', 'nasdaq', 'a', 'b', 'c', 'series', 'ordinary', 'units', 'representing', 'limited', 'partnership', 'interests', 'l', 'p'))


def search_renames(top=300):
    """未観測の記号（手の RENAME の後）を、書類の社名で Yahoo の検索にかけ、社名の語の集合が完全に一致し、
    系列がその記号の最初の公開月より前から続いている EQUITY の記号だけを『記号の変更』として採る → ct/rename_auto.json。
    リターンの値は見ない（系列の最初の月・種類・社名だけ）"""
    ev, yh, info = load_universe()
    un = [e for e in ev if not e['obs'] and not e.get('renamed_from')]
    cnt = Counter(e['ticker'] for e in un)
    names = defaultdict(Counter)
    first = {}
    for e in un:
        if e['name'] and e['src'] in ('efd', 'kadoa', 'ssw'):
            names[e['ticker']][e['name']] += 1
        first[e['ticker']] = min(first.get(e['ticker'], 999999), e['s'])
    p = os.path.join(CT, 'rename_auto.json')
    done = json.load(open(p)) if os.path.exists(p) else {}
    US = {'NYQ', 'NMS', 'NGM', 'NCM', 'ASE', 'PCX', 'BTS', 'NAS', 'NYS'}
    for t, n in cnt.most_common(top):
        if t in done or not names[t]:
            continue
        nm = names[t].most_common(1)[0][0]
        want = ntoks(nm)
        rec = {'name': nm, 'n_events': n, 'accepted': None, 'candidates': []}
        qs = [' '.join(sorted(want, key=lambda w: nm.lower().find(w))),
              re.sub(r'\s+', ' ', re.sub(r'\([^)]*\)|\[[^\]]*\]|-?\s*(Class [A-C]\s*)?Common Stock.*$|Common Units.*$|Ordinary Shares.*$|,', ' ', nm, flags=re.I)).strip()]
        for qq in (qs if len(want) >= 1 else []):
            if rec['accepted']:
                break
            u = 'https://query1.finance.yahoo.com/v1/finance/search?' + urllib.parse.urlencode({'q': qq, 'quotesCount': 6, 'newsCount': 0})
            try:
                j = json.loads(http_get(u, tries=3) or b'{}')
            except Exception as ex:  # noqa
                print('検索失敗', t, ex); continue
            for q in j.get('quotes', []):
                sym = q.get('symbol'); qt = q.get('quoteType'); exch = q.get('exchange')
                cand = {'symbol': sym, 'type': qt, 'exch': exch, 'name': q.get('longname') or q.get('shortname')}
                rec['candidates'].append(cand)
                if qt != 'EQUITY' or exch not in US or not sym or sym == t or ntoks(cand['name']) != want:
                    continue
                if not os.path.exists(yh_name(sym)):
                    fetch_yh({sym})
                r2, mt2 = yh_load(sym)
                if r2 and min(r2) <= madd(first[t], 1):
                    rec['accepted'] = sym
                    break
            time.sleep(0.5)
        done[t] = rec
        json.dump(done, open(p, 'w'), ensure_ascii=False, indent=0)
        if rec['accepted']:
            print('改名', t, '→', rec['accepted'], nm)
    print('採った', sum(1 for v in done.values() if v['accepted']), '/', len(done))


if __name__ == '__main__':
    main_cli()
