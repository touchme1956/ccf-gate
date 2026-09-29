#!/usr/bin/env python3
"""night/mw_moat_text_pre2007.py — 角度 moat_text_pre2007（読むだけ・門の判定には不使用）

問い: 自社の 10-K が『顧客の側の再認定・認証のロック』（門の irr=85 の機構＝顧客の工程・製品が当社の部品・仕様で
      認定・認証されていて、乗り換えるには顧客が再認定をやり直す）を述べている S&P500 の会社は、
      1997-2006（訓練・AI と半導体の相場より前＝irr85 の既存の証拠が全部生まれた時代と独立で逆風の時代）と
      2007年以降（新しく読んだビンテージ）に、純粋な時価加重の米国市場（French Mkt）に勝ったか。

段（第1段＝準備だけ。株価もリターンもこの段では一切読まない・計算しない）
  universe : 時点の S&P500 名簿（ie_sp500_components.csv）→ CIK 対応づけ・被覆の数え上げ
  fetch    : 各社・各ビンテージの 10-K（形成月の前15か月で最新）の本体から Item 1 / 1A / 7 を切り出す
  extract  : 事前登録で凍結した正規表現で候補段落を拾う・F1（機械の族）の旗・自動 no85 の数え上げ
  mask     : 社名・旧社名・子会社名・ティッカー・固有の製品名を伏せる → 順番を無作為化・不透明な id
  batches  : 読み手への束（約60件ずつ）と指示書 READER_INSTRUCTIONS.md
  labels   : 第3段（読みの後）。鍵を開け、A・B（割れた単位だけ C）の読みから最終ラベル（irr≥85 の多数決・rep/dur・F1）→ labels.json（gitignore）
  prices   : 第3段。記号の選び方（事前登録の returns の a/b/c）→ Yahoo の月次（mw_common.yahoo）
  run      : 第3段。H1〜H7（S/L・Holm）と報告のみの対照 → out/mw_moat_text_pre2007.json

事前登録: out/mw_moat_text_pre2007_prereg.json（抽出の前にコミット）。線は out/mw_prereg.json（C1〜C8）。
キャッシュ: out/_mw_cache/moat_text/（gitignore）。ex27 のキャッシュは読むだけ（書かない・消さない）。
SEC: User-Agent は retro_delisted.SEC_UA（連絡先つき・絶対のルール5）、毎秒6件以下。
"""
import csv, datetime, gzip, html, json, os, random, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
CACHE = M.CACHE
MT = os.path.join(CACHE, 'moat_text')
IDX = os.path.join(MT, 'idx')
EFTS = os.path.join(MT, 'efts')
DOCS = os.path.join(MT, 'docs')
SUBS = os.path.join(MT, 'subs')
EX27 = os.path.join(CACHE, 'ex27')          # 読むだけ（別の道具が使っている）
EX27_RAW = os.path.join(EX27, 'raw')
MEMB = os.path.join(CACHE, 'ie_sp500_components.csv')
PREREG = os.path.join(BASE, 'out', 'mw_moat_text_pre2007_prereg.json')
UNIV = os.path.join(MT, 'universe.json')
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}   # = retro_delisted.SEC_UA

VINTAGES_TRAIN = [1997, 2000, 2003, 2006]
VINTAGES_HOLD = [2009, 2012]
VINTAGES = VINTAGES_TRAIN + VINTAGES_HOLD
FORMS_10K = ('10-K', '10-K405', '10-KT', '10-KT405')
BUDGET = 1400


# ───────────────────────── SEC（毎秒6件以下） ─────────────────────────
class Rate:
    def __init__(self, per_s):
        self.gap = 1.0 / per_s; self.lock = threading.Lock(); self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.time(); t = max(now, self.next); self.next = t + self.gap
        d = t - time.time()
        if d > 0:
            time.sleep(d)


RATE = Rate(6.0)


def sec_fetch(url, tries=6):
    """bytes（gzip は展開）。404 は None"""
    for k in range(tries):
        RATE.wait()
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=180)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip' or b[:2] == b'\x1f\x8b':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (k + 1) + random.random())
        except Exception:  # noqa
            time.sleep(2 ** (k + 1) + random.random())
    raise RuntimeError(f'SEC 取得失敗 {url}')


# ───────────────────────── 月・日付 ─────────────────────────
def window(v):
    """ビンテージ v の本文の窓: 形成月（v年7月1日）の前15か月 → [v-1 年 4月1日, v 年 6月30日]"""
    return f'{v - 1}-04-01', f'{v}-06-30'


def quarters(a, z):
    ya, qa = int(a[:4]), (int(a[5:7]) - 1) // 3 + 1
    yz, qz = int(z[:4]), (int(z[5:7]) - 1) // 3 + 1
    out, y, q = [], ya, qa
    while (y, q) <= (yz, qz):
        out.append((y, q)); q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


# ───────────────────────── EDGAR full-index ─────────────────────────
LINE = re.compile(r'^(\S+(?: \S+)?)\s{2,}(.*?)\s{2,}(\d+)\s+(\d{4}-?\d{2}-?\d{2})\s+(\S+)\s*$')


def idx_path(y, q):
    p = os.path.join(EX27, f'form_{y}Q{q}.idx')      # 1994〜2002 は ex27 の置き場（読むだけ）
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p
    os.makedirs(IDX, exist_ok=True)
    p = os.path.join(IDX, f'form_{y}Q{q}.idx')
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        b = sec_fetch(f'https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz')
        if b is None:
            raise RuntimeError(f'form.gz が無い {y}Q{q}')
        tmp = p + '.tmp'; open(tmp, 'wb').write(b); os.replace(tmp, p)
    return p


def filings_in(a, z, forms=FORMS_10K):
    """窓 [a, z] の提出（forms のみ）→ {cik: [(filed, form, path, name)]}（提出日の昇順）"""
    out = defaultdict(list)
    for y, q in quarters(a, z):
        for line in open(idx_path(y, q), encoding='latin-1'):
            m = LINE.match(line.rstrip('\n'))
            if not m or m.group(1) not in forms:
                continue
            form, name, cik, filed, path = m.groups()
            if len(filed) == 8:
                filed = f'{filed[:4]}-{filed[4:6]}-{filed[6:]}'
            if a <= filed <= z:
                out[str(int(cik))].append((filed, form, path, name.strip()))
    for c in out:
        out[c].sort()
    return out


# ───────────────────────── 名簿 ─────────────────────────
def membership(v):
    """v年6月30日以前で最後の名簿の日付と記号の集合（形成は7月・後から分かる情報を使わない）"""
    rows = sorted((r['date'], r['tickers'].split(',')) for r in csv.DictReader(open(MEMB)))
    d, s = [x for x in rows if x[0] <= f'{v}-06-30'][-1]
    return d, sorted(set(s))


# ───────────────────────── 記号 → CIK の候補 ─────────────────────────
def sec_current():
    d = json.load(open(os.path.join(CACHE, 'sec_company_tickers.json')))
    m = defaultdict(set)
    for v in d.values():
        m[v['ticker'].upper()].add(str(v['cik_str']))
    return m


def tvariants(t):
    t = t.upper()
    return list(dict.fromkeys([t, t.replace('.', '-'), t.replace('.', ''), t.split('.')[0]]))


def ex27_symbols():
    """ex27 の解析済み（1995〜2001 の 10-K）→ {記号: Counter(cik)}（本文の『under the symbol X』）"""
    p = os.path.join(EX27, 'parsed_v2.jsonl.gz')
    m = defaultdict(Counter)
    if not os.path.exists(p):
        return m
    for line in gzip.open(p, 'rt'):
        d = json.loads(line)
        for s in d.get('symbols') or []:
            m[s.upper()][str(d['cik'])] += 1
    return m


def efts_symbol(t):
    """EDGAR 全文検索（2001〜）で 10-K の本文（添付を含む）の『symbol T』→ [(cik, 提出日, 表示名)]。キャッシュ efts/{t}.v2.json"""
    os.makedirs(EFTS, exist_ok=True)
    p = os.path.join(EFTS, f'{t}.v2.json')
    if os.path.exists(p):
        return json.load(open(p))
    hits_all, frm = [], 0
    while True:
        q = urllib.parse.quote(f'"symbol {t}"')
        u = f'https://efts.sec.gov/LATEST/search-index?q={q}&forms=10-K,10-K405&from={frm}'
        b = sec_fetch(u)
        if b is None:
            break
        j = json.loads(b)
        hits = j.get('hits', {}).get('hits', [])
        for h in hits:
            s = h['_source']
            for c, nm in zip(s.get('ciks', []), s.get('display_names', []) or [''] * len(s.get('ciks', []))):
                hits_all.append([str(int(c)), s.get('file_date'), re.sub(r'\s*\(CIK \d+\)$', '', nm or '')])
        frm += len(hits)
        tot = j.get('hits', {}).get('total', {}).get('value', 0)
        if not hits or frm >= min(tot, 400):     # 400件で打ち切り
            break
    json.dump(hits_all, open(p, 'w'))
    return hits_all


NAME_DROP = {'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'COMPANIES', 'LTD', 'LIMITED', 'PLC', 'THE', 'HOLDINGS', 'HOLDING',
             'GROUP', 'INCORPORATED', 'NEW', 'LLC', 'LP', 'NV', 'SA', 'AG', 'TRUST', 'AND', 'OF', 'INTERNATIONAL', 'INTL'}
NAME_GENERIC = {'GENERAL', 'AMERICAN', 'UNITED', 'FIRST', 'NATIONAL', 'SOUTHERN', 'NORTHERN', 'WESTERN', 'EASTERN', 'CENTRAL',
                'PACIFIC', 'ATLANTIC', 'CONTINENTAL', 'STANDARD', 'UNION', 'US', 'USA', 'ALLIED', 'CONSOLIDATED', 'FEDERAL',
                'SECURITY', 'NORTH', 'SOUTH', 'WEST', 'EAST', 'NEW', 'GREAT', 'ADVANCED', 'APPLIED', 'DIGITAL', 'INTEGRATED',
                'PUBLIC', 'CITIZENS', 'PEOPLES', 'COMMERCIAL', 'BANK', 'ENERGY', 'HEALTH', 'MEDICAL', 'DATA', 'TECHNOLOGIES',
                'INDUSTRIES', 'SYSTEMS', 'FINANCIAL', 'CAPITAL', 'INVESTORS', 'PROPERTIES', 'REALTY', 'RESOURCES', 'MORGAN',
                'STATE', 'CITY', 'HOME', 'TEXAS', 'CALIFORNIA', 'NEW', 'MID', 'TRANS', 'INTER', 'UNIVERSAL', 'NATURAL', 'ROYAL'}


def nname(s):
    s = re.sub(r'/[A-Z]{2,3}/?', ' ', (s or '').upper())
    s = re.sub(r'\([^)]*\)', ' ', s).replace('&', ' AND ')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return [w for w in s.split() if w not in NAME_DROP]


def name_match(a, b):
    """a, b = 社名。正規化して一致 or 語境界の前方一致（先頭語が5字以上で一般語でない）"""
    x, y = nname(a), nname(b)
    if not x or not y:
        return False
    if x == y:
        return True
    k = min(len(x), len(y))
    if x[:k] == y[:k] and (k >= 2 or (len(x[0]) >= 5 and x[0] not in NAME_GENERIC)):
        return True
    return False


def ex27_declared(cik_filings):
    """ex27 の raw（1995-01〜2001-06・読むだけ）の『symbol』抜粋 → {年: Counter(記号)}"""
    out = {}
    for filed, form, path, name in cik_filings:
        acc = path.rsplit('/', 1)[-1].replace('.txt', '')
        rp = os.path.join(EX27_RAW, acc[:10], acc + '.json.gz')
        if not os.path.exists(rp):
            continue
        try:
            r = json.loads(gzip.open(rp).read())
        except Exception:  # noqa
            continue
        c = Counter()
        for sn in r.get('symbol') or []:
            c.update(self_symbols(sn))
        out.setdefault(int(filed[:4]), Counter()).update(c)
    return out


def cover_float(txt):
    """表紙の『aggregate market value ... held by non-affiliates』→ ドル（見つからなければ None）"""
    m = re.search(r'(?is)aggregate\s+market\s+value.{0,500}?\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|thousand)?', txt[:40000])
    if not m:
        return None
    try:
        v = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    mult = {'billion': 1e9, 'million': 1e6, 'thousand': 1e3}.get((m.group(2) or '').lower(), 1.0)
    return v * mult


# ───────────────────────── 提出書類の本文 ─────────────────────────
SYM_NEAR = re.compile(r'(?i)\b(?:ticker\s+|trading\s+)?symbols?\b(.{0,90})', re.S)
SYM_TOK = re.compile(r'["\'`“‘]\s*([A-Z][A-Z0-9]{0,5}(?:[.\-/ ]?[A-Z])?)\s*[,.]?\s*["\'”’]|\b([A-Z]{2,5}(?:[.\-/][A-Z])?)\b')
SYM_STOP = {'THE', 'NYSE', 'AND', 'OR', 'ON', 'OF', 'FOR', 'IN', 'AS', 'IS', 'NASDAQ', 'AMEX', 'CBOE', 'PSE', 'CSE', 'TSE', 'LSE',
            'ITEM', 'PART', 'INC', 'CORP', 'CO', 'US', 'USA', 'NMS', 'NNM', 'OTC', 'BB', 'ADR', 'ADS', 'NEW', 'YORK', 'STOCK',
            'EXCHANGE', 'COMMON', 'CLASS', 'SERIES', 'PREFERRED', 'SHARES', 'UNDER', 'TRADING', 'TICKER', 'LISTED', 'MARKET',
            'PACIFIC', 'CHICAGO', 'BOSTON', 'PHILADELPHIA', 'MIDWEST', 'TORONTO', 'LONDON', 'SWISS', 'GLOBAL', 'SELECT', 'NATIONAL',
            'CAPITAL', 'SMALLCAP', 'DE', 'NA', 'NOTE', 'SEE', 'TABLE', 'ANNUAL', 'REPORT', 'EPS', 'PER', 'SHARE', 'III', 'II', 'IV'}


SYM_CTX = re.compile(r'(?i)exchange|traded|trades|listed|nyse|nasdaq|amex|ticker|quoted|stock\s+market|trading')


def self_symbols(txt):
    """本文が自分で名乗る銘柄コード（取引所の文脈の『symbol "XX"』）→ 出現回数の Counter"""
    c = Counter()
    for m in SYM_NEAR.finditer(txt):
        ctx = txt[max(0, m.start() - 250):m.start() + 60]
        if not SYM_CTX.search(ctx):
            continue
        seg = m.group(1)
        seg = re.split(r'(?<=[.;])\s+[A-Z][a-z]', seg)[0]   # 次の文へ流れない
        for q, b in SYM_TOK.findall(seg):
            s = (q or b).strip().replace(' ', '.').replace('/', '.').replace('-', '.')
            if s and s not in SYM_STOP and not (len(s) == 1 and not q):
                c[s] += 1
    return c


def symbols_fast(txt):
    """『symbol』の周りだけタグを外して読む（全文にタグ外しを掛けない）。回数は窓の重なりで目安、有無だけを使う"""
    c = Counter()
    for m in re.finditer(r'(?i)symbol', txt):
        c.update(self_symbols(plain(txt[max(0, m.start() - 700):m.start() + 500])))
    return c


def plain(txt):
    return html.unescape(re.sub(r'(?s)<[^>]{0,400}>', ' ', txt)).replace('\xa0', ' ')


def hv(h, key, all_=False):
    xs = [x.strip() for x in re.findall(key + r':\s*(.+)', h)]
    return xs if all_ else (xs[0] if xs else None)


def split_docs(txt):
    """全文 .txt → [(type, text)]"""
    out = []
    for m in re.finditer(r'<DOCUMENT>(.*?)(?:</DOCUMENT>|\Z)', txt, re.S):
        d = m.group(1)
        t = re.search(r'<TYPE>\s*([^\s<]+)', d)
        body = re.search(r'<TEXT>(.*?)(?:</TEXT>|\Z)', d, re.S)
        out.append(((t.group(1).upper() if t else ''), body.group(1) if body else d))
    return out


BLOCK = re.compile(r'(?i)</?(?:p|div|br|tr|li|ul|ol|h[1-6]|table|center|blockquote|pre|hr|title)\b[^>]*>')


def to_text(s):
    """HTML でも平文でも → 段落を空行で区切った平文"""
    if re.search(r'(?i)<(?:html|p|div|table|font|br)\b', s[:200000]):
        s = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', s)
        s = re.sub(r'(?i)</?t[dh]\b[^>]*>', ' ', s)
        s = BLOCK.sub('\n\n', s)
        s = re.sub(r'(?s)<[^>]+>', ' ', s)
        s = html.unescape(s)
        s = s.replace('\xa0', ' ')
        s = re.sub(r'[ \t\r\f\v]+', ' ', s)
        s = re.sub(r'\n[ ]+', '\n', s)
        s = re.sub(r'\n{3,}', '\n\n', s)
    else:
        s = html.unescape(re.sub(r'(?i)</?(?:page|s|c|f\d+|fn|caption)>', ' ', s)).replace('\xa0', ' ').replace('\r', '')
        s = re.sub(r'[ \t\f\v]+\n', '\n', s)
    return s


ITEM_RE = re.compile(r'(?im)^[ \t>*]*(?:PART\s+I{1,3}\s*[,.\-–—:]?\s*)?I\s{0,2}TEMS?\s+(\d{1,2})\s*(\(?[AaBbCc]\)?(?![A-Za-z]))?\s*(?:(?:AND|&|,)\s*(\d{1,2})\s*)?[.:\-–—]?\s*([^\n]{0,80})')


def items(t):
    """見出しの位置 → [(pos, '1'|'1A'|'2'...)]（『Items 1 and 2』は '1+2'）"""
    out = []
    for m in ITEM_RE.finditer(t):
        n = m.group(1).lstrip('0') or '0'
        suf = (m.group(2) or '').strip('()').upper()
        key = n + suf
        if m.group(3):
            key = f'{key}+{m.group(3)}'
        out.append((m.start(), key, m.group(4) or ''))
    return out


def section(t, its, starts, ends):
    """starts の見出しから、それより後で最初の ends の見出しまで。目次を避けるため最長のものを取る"""
    best = None
    for i, (p, k, _) in enumerate(its):
        if k.split('+')[0] not in starts:
            continue
        stop_keys = set(ends)
        if '+' in k:   # 『Items 1 and 2』→ 3 まで
            stop_keys = {x for x in ends if x not in ('2',)} | {'3'}
        q = next((pp for pp, kk, _ in its[i + 1:] if kk.split('+')[0] in stop_keys), None)
        if q is None:
            q = min(len(t), p + 400000)
        if best is None or q - p > best[1] - best[0]:
            best = (p, q)
    return t[best[0]:best[1]].strip() if best and best[1] - best[0] > 400 else ''


def sections_of(mt):
    its = items(mt)
    sec = {'item1': section(mt, its, {'1'}, {'1A', '1B', '2', '3', '4'}),
           'item1a': section(mt, its, {'1A'}, {'1B', '2', '3'}),
           'item7': section(mt, its, {'7'}, {'7A', '8', '9'})}
    if not sec['item1'] and not its:
        sec['item1_fallback'] = mt[:150000]
    return sec, its


def parse_filing(txt, main_only_text=None):
    """全文（または本体だけ）→ {header, name, former, sic, period, symbols, sections, ex21, main_len, headings}"""
    h = txt[:txt.find('</SEC-HEADER>') + 13] if '</SEC-HEADER>' in txt else txt[:8000]
    docs = split_docs(txt)
    main = main_only_text
    if main is None:
        main = next((b for ty, b in docs if ty.startswith('10-K')), docs[0][1] if docs else txt)
    mt = to_text(main)
    sec, its = sections_of(mt)
    ex21 = []
    for ty, b in docs:
        if ty.startswith('EX-21'):
            for line in to_text(b).splitlines():
                line = re.sub(r'\s{2,}.*$', '', line.strip())
                if 4 <= len(line) <= 90 and re.search(r'[A-Za-z]{3}', line) and not re.match(r'(?i)(name|exhibit|subsidiar|jurisdiction|state|country|page|\d)', line):
                    ex21.append(line)
    sic = re.search(r'STANDARD INDUSTRIAL CLASSIFICATION:\s*(.*?)\[(\d{3,4})\]', h)
    return {'name': hv(h, 'COMPANY CONFORMED NAME'), 'names_all': hv(h, 'COMPANY CONFORMED NAME', True),
            'former': sorted(set(hv(h, 'FORMER CONFORMED NAME', True))), 'sic': sic.group(2) if sic else None,
            'sic_desc': sic.group(1).strip() if sic else None, 'period': hv(h, 'CONFORMED PERIOD OF REPORT'),
            'symbols': dict(symbols_fast(txt).most_common(12)), 'sections': sec, 'ex21': ex21[:400],
            'float': cover_float(mt), 'main_len': len(main), 'headings': [k for _, k, _ in its][:80], 'main_text': mt}


def cmd_reparse():
    """保存した本体の平文（main_text）から節を切り直す（取り直さない）。2026-09-28: 『ITEM 1 BUSINESS』を 1B と読む見出しの不具合の是正"""
    import glob
    n = 0
    for f in glob.glob(os.path.join(DOCS, '*', '*.json.gz')):
        d = json.loads(gzip.open(f).read())
        if d.get('missing') or not d.get('main_text'):
            continue
        sec, its = sections_of(d['main_text'])
        d['sections'] = sec
        d['headings'] = [k for _, k, _ in its][:80]
        tmp = f + '.tmp'
        with gzip.open(tmp, 'wt', compresslevel=3) as g:
            json.dump(d, g)
        os.replace(tmp, f)
        n += 1
    print('切り直した', n)


def doc_path(acc):
    return os.path.join(DOCS, acc[:10], acc + '.json.gz')


def get_doc(path):
    """edgar/data/{cik}/{acc}.txt → 解析済みの dict（キャッシュ）。1995-01〜2001-06 は ex27 の表紙を先に見る（読むだけ）"""
    acc = path.rsplit('/', 1)[-1].replace('.txt', '')
    p = doc_path(acc)
    if os.path.exists(p):
        try:
            return json.loads(gzip.open(p).read())
        except Exception:  # noqa
            pass
    src, d = None, None
    rp = os.path.join(EX27_RAW, acc[:10], acc + '.json.gz')
    if os.path.exists(rp):
        try:
            r = json.loads(gzip.open(rp).read())
            cov = r.get('cover') or ''
            if '</DOCUMENT>' in cov or '</TEXT>' in cov:      # 本体が 60,000 字に収まっている
                d = parse_filing(r.get('header', '') + '\n' + cov)
                sy = Counter()
                for s in r.get('symbol') or []:
                    sy.update(self_symbols(s))
                d['symbols'] = dict((Counter(d['symbols']) + sy).most_common(12))
                d['ex21'] = []
                src = 'ex27_cover'
        except Exception:  # noqa
            d = None
    if d is None:
        b = sec_fetch('https://www.sec.gov/Archives/' + path)
        if b is None:
            d = {'missing': True}
        else:
            d = parse_filing(b.decode('latin-1'))
        src = 'full'
    d['src'] = src; d['acc'] = acc; d['path'] = path
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + f'.{os.getpid()}.{threading.get_ident()}.tmp'
    with gzip.open(tmp, 'wt', compresslevel=3) as g:
        json.dump(d, g)
    os.replace(tmp, p)
    return d


def sec_titles():
    d = json.load(open(os.path.join(CACHE, 'sec_company_tickers.json')))
    m = defaultdict(set)
    for v in d.values():
        m[v['ticker'].upper()].add(v['title'])
    return m


def wiki_names():
    """ウィキペディアの S&P500 入れ替え表（mw_index_events のキャッシュ・2000年以降が主）→ {記号: {社名}}"""
    try:
        import mw_index_events as E
        w, _ = E.load_wiki()
    except Exception:  # noqa
        return {}
    m = defaultdict(set)
    for x in w:
        if x.get('rem'):
            m[x['rem'].upper()].add(x['rem_name'])
        if x.get('add'):
            m[x['add'].upper()].add(x['add_name'])
    return m


EX27_DECL = os.path.join(MT, 'ex27_declared.json')


def ex27_declared_all():
    """ex27 の raw（1995-01〜2001-06 の 10-K・読むだけ）すべての『symbol』抜粋を厳しめに読み直す → {記号: {cik: [年…]}}"""
    if os.path.exists(EX27_DECL):
        return json.load(open(EX27_DECL))
    F = filings_in('1995-01-01', '2001-06-30')
    m = defaultdict(lambda: defaultdict(set))
    n = 0
    for c, fl in F.items():
        for y, cnt in ex27_declared(fl).items():
            for s_ in cnt:
                m[s_][c].add(y)
        n += 1
        if n % 5000 == 0:
            print('  ex27 declared', n, flush=True)
    out = {s_: {c: sorted(ys) for c, ys in d.items()} for s_, d in m.items()}
    json.dump(out, open(EX27_DECL, 'w'))
    return out


CAND = os.path.join(MT, 'candidates.json')


def cmd_candidates():
    """記号・ビンテージごとに CIK の候補と証拠（今日の保有者・EDGAR 全文検索の年・社名の一致）を集める"""
    cur, titles, wiki = sec_current(), sec_titles(), wiki_names()
    X27 = ex27_declared_all()
    out = {}
    tick_all = sorted({t for v in VINTAGES for t in membership(v)[1]})
    import concurrent.futures as cf
    qs = sorted({q for t in tick_all for q in dict.fromkeys([t, t.replace('.', ' '), t.split('.')[0]])})
    with cf.ThreadPoolExecutor(4) as ex:
        E = dict(zip(qs, ex.map(efts_symbol, qs)))
    print('efts 済み', len(E), flush=True)
    for v in VINTAGES:
        a, z = window(v)
        F = filings_in(a, z)
        first = defaultdict(list)
        for c, fl in F.items():
            nm = nname(fl[-1][3])
            if nm:
                first[nm[0]].append((c, fl[-1][3]))
        d, tick = membership(v)
        rows = {}
        for t in tick:
            cands = defaultdict(lambda: {'cur': False, 'efts': [], 'name': [], 'ex27': []})
            names = set()
            for tv in tvariants(t):
                for c in cur.get(tv, ()):
                    cands[c]['cur'] = True
                names |= titles.get(tv, set())
                for c, ys in X27.get(tv.replace('-', '.'), {}).items():
                    cands[c]['ex27'] += ys
            names |= wiki.get(t, set())
            for q in dict.fromkeys([t, t.replace('.', ' '), t.split('.')[0]]):
                if '.' not in t and q != t:
                    continue
                for c, fd, nm in E.get(q, []):
                    cands[c]['efts'].append(int(fd[:4]))
                    if nm:
                        names.add(nm)
            for nm in names:
                x = nname(nm)
                if not x:
                    continue
                for c, wn in first.get(x[0], []):
                    if name_match(nm, wn):
                        cands[c]['name'].append(nm)
            valid = {c: {'cur': e['cur'], 'efts': sorted(set(e['efts'])), 'ex27': sorted(set(e['ex27'])), 'name': sorted(set(e['name']))[:3],
                         'path': F[c][-1][2], 'filed': F[c][-1][0], 'form': F[c][-1][1], 'wname': F[c][-1][3]}
                     for c, e in cands.items() if c in F}
            rows[t] = {'valid': valid, 'n_cands': len(cands), 'names': sorted(names)[:6],
                       'invalid': sorted(c for c in cands if c not in F)[:8]}
        out[str(v)] = {'membership_date': d, 'window': [a, z], 'rows': rows}
        print(v, 'members', len(tick), 'with≥1 valid', sum(1 for r in rows.values() if r['valid']),
              'multi', sum(1 for r in rows.values() if len(r['valid']) > 1), flush=True)
    json.dump(out, open(CAND, 'w'))


def cmd_fetch_cands(max_per=4, part=0, nparts=1):
    """候補の CIK の窓の 10-K を全部取って解析する（本文のキャッシュ docs/）"""
    C = json.load(open(CAND))
    paths = []
    for v, V in C.items():
        for t, r in V['rows'].items():
            ks = sorted(r['valid'].items(), key=lambda kv: (-kv[1]['cur'], -len(kv[1]['efts']) - len(kv[1].get('ex27', [])), -len(kv[1]['name'])))
            paths += [x['path'] for _, x in ks[:max_per]]
    paths = sorted(set(paths))
    todo = [p for i, p in enumerate(paths) if i % nparts == part and not os.path.exists(doc_path(p.rsplit('/', 1)[-1].replace('.txt', '')))]
    RATE.gap = nparts / 6.0     # 全体で毎秒6件以下
    print('文書', len(paths), '未取得', len(todo), flush=True)
    import concurrent.futures as cf
    t0 = time.time(); n = 0
    with cf.ThreadPoolExecutor(6) as ex:
        for _ in ex.map(get_doc, todo):
            n += 1
            if n % 200 == 0:
                print(f'  {n}/{len(todo)}  {(time.time() - t0) / 60:.1f}分', flush=True)
    print('完了', n, flush=True)


def declared_years(c, t, doc, v, ex27_by_cik):
    """候補 c が 1995〜2001 の 10-K（ex27 の抜粋）で記号 t を自分の記号として名乗った年の集合"""
    tv = set(x.replace('-', '.') for x in tvariants(t))
    return {int(y) for y, cnt in (ex27_by_cik.get(c) or {}).items() if tv & set(cnt)}


EX27F = {}


def ex27_floats():
    """ex27 の解析済み（読むだけ）の表紙の時価 → {受付番号: ドル}"""
    if not EX27F:
        p = os.path.join(EX27, 'parsed_v2.jsonl.gz')
        if os.path.exists(p):
            for line in gzip.open(p, 'rt'):
                d = json.loads(line)
                f = (d.get('cover') or {}).get('float')
                if f:
                    EX27F[d['acc']] = f
    return EX27F


def decide(ev, p10, floor, exclude=()):
    """候補の証拠 ev → (cik, via, note)。exclude＝同じビンテージで別の記号に既に割り当てた CIK"""
    ev = {c: e for c, e in ev.items() if c not in exclude}
    # 大きさの検問: 5倍以上大きい別の候補がいる小さな候補は外す（他社の記号を本文に書いただけの小型株を拾わない）
    fl = {c: e['float'] for c, e in ev.items() if e['float']}
    if fl:
        big = max(fl.values())
        ev = {c: e for c, e in ev.items() if not (e['float'] and e['float'] * 5 <= big)}
    dd = sorted(((e['dist'], -(e['float'] or 0), c) for c, e in ev.items() if e['dist'] is not None))
    pick, via, note = None, None, ''

    def tie(cs):
        """同点の候補の決め方: 同じ提出書類（合同の 10-K）→ 今日の保有者 → 表紙の時価が分かる社が一つ → 最大が2番手の2倍以上"""
        accs = {ev[c]['path'].rsplit('/', 1)[-1] for c in cs}
        cu = [c for c in cs if ev[c]['cur']]
        if len(accs) == 1:
            return (cu or sorted(cs, key=lambda c: -(ev[c]['float'] or 0)))[0], 'joint_filing'
        if len(cu) == 1:
            return cu[0], 'current_holder'
        kf = sorted(((ev[c]['float'], c) for c in cs if ev[c]['float']), reverse=True)
        if len(kf) == 1:
            return kf[0][1], 'only_known_float'
        if len(kf) >= 2 and kf[0][0] >= 2 * kf[1][0]:
            return kf[0][1], 'largest_float'
        return None, None

    if dd and dd[0][0] <= 1:
        near = [c for d_, _, c in dd if d_ <= 1]
        if len(near) == 1:
            pick, via = near[0], 'declared_at_time'
        else:
            iw = [c for c in near if ev[c]['in_window_decl']]
            if len(iw) == 1:
                pick, via = iw[0], 'declared_at_time_inwindow'
            else:
                pick, how = tie(iw or near)
                if pick:
                    via = 'declared_at_time_tie_' + how
                else:
                    via, note = 'ambiguous', f'当時に名乗った候補が複数 {near[:5]}'
    elif dd:
        if len(dd) == 1 or dd[1][0] - dd[0][0] >= 3:
            pick, via = dd[0][2], 'declared_nearest'
        else:
            close = [c for d_, _, c in dd if d_ - dd[0][0] < 3]
            pick, how = tie(close)
            if pick:
                via = 'declared_nearest_tie_' + how
            else:
                via, note = 'ambiguous', f'名乗りの近さが拮抗 {[(d_, c) for d_, _, c in dd[:4]]}'
    if pick is None and via is None:
        nm = [c for c, e in ev.items() if e['name']]
        if len(nm) == 1:
            pick, via = nm[0], 'name_match'
        elif len(nm) > 1:
            via, note = 'ambiguous', f'社名の一致が複数 {nm[:5]}'
        else:
            via = 'unmapped'
    if pick and via.startswith('declared_nearest') and ev[pick]['dist'] > 5:
        f_ = ev[pick]['float']
        if p10 and f_ is not None and f_ < p10 / 3:
            return None, 'rejected_late_ticker_small', f"名乗りが{ev[pick]['dist']}年離れ・浮動株時価 {f_ / 1e6:.0f}M < 下位10%点の1/3 {p10 / 3e6:.0f}M"
        via = via.replace('declared_nearest', 'declared_nearest_late')
    return pick, via, note


def evidence_strength(e):
    """同じ CIK が二つの記号に割り当たったとき、どちらを残すか: 窓の本文での名乗り > 名乗りの近さ"""
    return (1 if e['in_window_decl'] else 0, -(e['dist'] if e['dist'] is not None else 99))


def cmd_universe():
    C = json.load(open(CAND))
    manual = load_manual()
    out = {'generated': datetime.date.today().isoformat(), 'vintages': {},
           'rules': ('候補＝今日の SEC 一覧の保有者 ∪ EDGAR 全文検索（2001〜）で『symbol T』を名乗った 10-K の提出者 ∪ 1995〜2001 の 10-K で T を名乗った提出者 ∪ 社名の一致。'
                     '検問＝窓の中で 10-K を出していること。大きさの検問＝表紙の時価が5倍以上大きい別の候補がいる候補は外す。'
                     '決め方＝T を自分の記号として名乗った年（窓の本文・1995〜2001・全文検索の年・今日の保有者は2026年）がビンテージに最も近い候補。'
                     '1年以内が複数なら窓の本文で名乗った方→今日の保有者。2番手との差が3年未満なら曖昧。名乗りの証拠が無ければ社名の一致が一意なら採る。'
                     '名乗りがビンテージから6年以上離れる候補は表紙の時価が当時に名乗った社の下位10%点未満なら棄てる。'
                     '採った社の表紙の時価が床（今日の保有者かつ窓の本文で名乗った社の2%点）未満なら棄てる。同じ CIK が二つの記号に当たったら、窓の本文で名乗った方→名乗りの近い方に残し、'
                     'もう一方は その CIK を除いて決め直す。手の対応（manual_map.json）は理由つきで優先')}
    for v in VINTAGES:
        V = C[str(v)]
        pre = []
        for t, r in sorted(V['rows'].items()):
            ev = {}
            tv = set(q.replace('-', '.') for q in tvariants(t))
            for c, x in r['valid'].items():
                has = os.path.exists(doc_path(x['path'].rsplit('/', 1)[-1].replace('.txt', '')))
                doc = get_doc(x['path']) if has else None
                ys = set(x['efts']) | set(x.get('ex27') or [])
                iw = bool(doc and not doc.get('missing') and tv & set(doc.get('symbols') or {}))
                if iw:
                    ys.add(int(x['filed'][:4]))
                if x['cur']:
                    ys.add(2026)
                fl = (doc or {}).get('float')
                if fl is None or not (5e7 <= fl <= 1e12):
                    fl = ex27_floats().get(x['path'].rsplit('/', 1)[-1].replace('.txt', ''))
                if fl is not None and not (5e7 <= fl <= 1e12):
                    fl = None
                ev[c] = {'dist': min((abs(y - v) for y in ys), default=None), 'years': sorted(ys), 'cur': x['cur'], 'name': bool(x['name']),
                         'in_window_decl': iw, 'float': fl, 'doc_symbols': list((doc or {}).get('symbols') or {})[:5],
                         'wname': x['wname'], 'path': x['path'], 'filed': x['filed'], 'form': x['form'], 'have_doc': has}
            pre.append((t, ev))
        fl1 = sorted(e['float'] for _, ev in pre for e in ev.values() if e['dist'] is not None and e['dist'] <= 1 and e['float'])
        p10 = fl1[len(fl1) // 10] if fl1 else None
        flc = sorted(e['float'] for _, ev in pre for e in ev.values() if e['cur'] and e['in_window_decl'] and e['float'])
        floor = flc[len(flc) // 50] if flc else None
        res = {}
        F = filings_in(*window(v))
        for t, ev in pre:
            key = (str(v), t) if (str(v), t) in manual else (('*', t) if ('*', t) in manual else None)
            if key:
                pick, note = manual[key]
                via = 'manual' if pick else 'unmapped_manual'
                if pick and pick not in F:
                    via, note, pick = 'manual_no10k', note + '（窓に 10-K 無し）', None
                if pick and pick not in ev:
                    f = F[pick][-1]
                    d_ = get_doc(f[2])
                    fl = d_.get('float')
                    if fl is None or not (5e7 <= fl <= 1e12):
                        fl = ex27_floats().get(f[2].rsplit('/', 1)[-1].replace('.txt', ''))
                    ev[pick] = {'dist': None, 'years': [], 'cur': False, 'name': False, 'in_window_decl': False,
                                'float': fl if fl and 5e7 <= fl <= 1e12 else None, 'doc_symbols': list((d_.get('symbols') or {}))[:5],
                                'wname': f[3], 'path': f[2], 'filed': f[0], 'form': f[1], 'have_doc': True}
                res[t] = (pick, via, note)
            else:
                res[t] = decide(ev, p10, floor)
        # 同じ CIK が二つ以上の記号に当たったら解く（最大3回まわす）
        evs = dict(pre)
        for _ in range(3):
            byc = defaultdict(list)
            for t, (c, via, _) in res.items():
                if c:
                    byc[c].append(t)
            dup = {c: ts for c, ts in byc.items() if len(ts) > 1}
            if not dup:
                break
            for c, ts in dup.items():
                man = [t for t in ts if res[t][1] == 'manual']
                keep = man[0] if man else max(ts, key=lambda t: evidence_strength(evs[t][c]))
                for t in ts:
                    if t == keep or res[t][1] == 'manual':
                        continue
                    taken = {cc for tt, (cc, _, _) in res.items() if cc and tt != t}
                    p_, via_, note_ = decide(evs[t], p10, floor, exclude=taken)
                    res[t] = (p_, via_ if p_ else 'dup_cik_lost', (note_ + f' 同じ CIK {c} は {keep} に残した').strip())
        rows, cnt = [], Counter()
        for t, ev in pre:
            pick, via, note = res[t]
            row = {'t': t, 'cik': pick, 'via': via, 'note': note, 'n_valid': len(ev),
                   'cands': {c: {k: e[k] for k in ('dist', 'years', 'cur', 'name', 'in_window_decl', 'float', 'wname', 'doc_symbols')}
                             for c, e in list(ev.items())[:6]}}
            if pick:
                e = ev[pick]
                row.update(filed=e['filed'], form=e['form'], path=e['path'], name=e['wname'], float=e['float'])
            cnt[via] += 1
            rows.append(row)
        n = len(rows); mp = sum(1 for r in rows if r.get('path'))
        out['vintages'][str(v)] = {'membership_date': V['membership_date'], 'window': V['window'], 'n_members': n,
                                   'n_mapped_with_10k': mp, 'mapping_rate': round(mp / n, 3), 'via': dict(cnt),
                                   'float_p10_declared_at_time': p10, 'float_floor': floor, 'rows': rows}
        print(v, 'members', n, 'mapped', mp, f'{mp / n:.1%}', dict(cnt), 'p10', p10 and round(p10 / 1e6), 'floor', floor and round(floor / 1e6), flush=True)
    json.dump(out, open(UNIV, 'w'), ensure_ascii=False, indent=0)


# ───────────────────────── 事前登録（抽出の前に凍結） ─────────────────────────
RX = {
    'qual': [
        {'name': 'qualif*（requalif・re-qualif を含む）', 're': r'\b(?:re-?)?qualif\w*'},
        {'name': 'certif*（recertif・re-certif・type certificate を含む）', 're': r'\b(?:re-?)?certif\w*'},
        {'name': 'validat*（revalidat を含む）', 're': r'\b(?:re-?)?validat\w*'},
        {'name': 'approved supplier/vendor/source/manufacturer', 're': r'\bapproved\s+(?:suppliers?|vendors?|sources?|manufacturers?)\b'},
        {'name': 'supplier/vendor/source approval', 're': r'\b(?:supplier|vendor|source)\s+approvals?\b'},
        {'name': 'design-in / designed in', 're': r'\bdesign(?:ed)?[- ]ins?\b'},
        {'name': 'design win', 're': r'\bdesign[- ]wins?\b'},
        {'name': 'sole source / single source', 're': r'\b(?:sole|single)[- ]sourc\w*'},
        {'name': 'specified by', 're': r'\bspecified\s+by\b'},
        {'name': 'spec-in', 're': r'\bspec[- ]in\b'},
        {'name': 'type certificate', 're': r'\btype\s+certificat\w*'},
        {'name': 'PMA（大文字）', 're': r'\bPMAs?\b', 'case': True},
        {'name': 'STC（大文字）', 're': r'\bSTCs?\b', 'case': True},
        {'name': '510(k)', 're': r'\b510\s?\(k\)'},
        {'name': 'MIL-SPEC / military specification', 're': r'\bMIL[- ]?SPEC\w*|\bmilitary\s+specifications?\b'},
        {'name': 'AS9100（大文字）', 're': r'\bAS\s?9100\w*', 'case': True},
        {'name': 'QPL / QML（大文字）', 're': r'\bQ[PM]Ls?\b', 'case': True},
    ],
    'exclude': [
        {'name': '公認会計士', 're': r'certified\s+public\s+account\w*'},
        {'name': '証書・許認可の定型（certificate of deposit/incorporation/need/public convenience …）',
         're': r'certificates?\s+of\s+(?:deposit|incorporation|designation|need|public\s+convenience|authority|occupancy|participation|beneficial|insurance|title|formation|amendment|limited\s+partnership|good\s+standing|compliance|registration)'},
        {'name': '証券としての certificate', 're': r'(?:pass[- ]through|trust|equipment\s+trust|participation|mortgage|stock|share|gift|tax|interest|receivable|lease)\s+certificates?'},
        {'name': 'certificate holder', 're': r'certificate\s*-?holders?'},
        {'name': '人・制度・税務の qualified', 're': r'(?:non-?)?qualified\s+(?:retirement|pension|benefit|defined|savings|profit|stock|employee|deferred|plans?|dividends?|opinion|institutional|buyers?|personnel|employees|people|staff|individuals|candidates|engineers|technical|management|professionals|workers|labor|drivers|pilots|nurses|physicians|teachers|applicants|scientists|sales|managers|executives|special\s+purpose|hedg\w+|affordable|small\s+business|reit|subsidiar\w+|investors?|purchasers?|residential|mortgage)'},
        {'name': '税・会計の qualify as/for', 're': r'qualif(?:y|ies|ied|ying|ication)\s+(?:as|for)\s+(?:an?\s+|the\s+)?(?:reit|real\s+estate\s+investment|hedg\w+|tax|capital|investment|pooling|purchase|sale|special|exemption|well[- ]capitalized|treatment|accounting|deduction|listing)'},
        {'name': '法律の定型（qualified in its entirety / by reference）', 're': r'qualifi\w*\s+(?:in\s+(?:its|their)\s+entirety|by\s+reference)'},
        {'name': 'Sarbanes-Oxley の証明', 're': r'(?:sarbanes[- ]oxley|section\s+(?:302|906)|chief\s+(?:executive|financial)\s+officer)\W+(?:\w+\W+){0,8}?certif\w*|certif\w*\W+(?:\w+\W+){0,8}?(?:section\s+(?:302|906)|sarbanes)'},
        {'name': '資格者（board-certified 等）', 're': r'board[- ]certified|certified\s+(?:nurse|financial|pilots?|mail|teachers?|technicians?|registered|management\s+accountants?)'},
        {'name': 'モデル・前提の検証', 're': r'validat\w*\s+(?:(?:of|the|our|its)\s+)?(?:assumptions?|models?|estimates?|valuations?)'},
    ],
    'counterparty': [
        {'name': 'customer*', 're': r'\bcustomers?\w*'},
        {'name': 'OEM* / original equipment manufacturer', 're': r'\bOEMs?\b|\boriginal\s+equipment\s+manufacturers?\b'},
        {'name': 'airframer* / airframe manufacturer', 're': r'\bairframers?\b|\bairframe\s+manufacturers?\b'},
        {'name': 'FAA（大文字）', 're': r'\bFAA\b|Federal\s+Aviation\s+Administration', 'case': True},
        {'name': 'FDA（大文字）', 're': r'\bFDA\b|Food\s+and\s+Drug\s+Administration', 'case': True},
        {'name': 'DoD / Department of Defense', 're': r'\bDoD\b|\bDOD\b|Department\s+of\s+Defense', 'case': True},
        {'name': 'NRC / Nuclear Regulatory Commission', 're': r'\bNRC\b|Nuclear\s+Regulatory\s+Commission', 'case': True},
        {'name': 'government*', 're': r'\bgovernments?\w*'},
        {'name': 'fab / fabs / wafer fab / fabrication facility（fabric 等は含めない）', 're': r'\bfabs?\b|\bwafer\s+fab\w*|\bfabrication\s+(?:facilit\w*|plants?|lines?|sites?)'},
        {'name': 'foundry / foundries', 're': r'\bfoundr(?:y|ies)\b'},
    ],
    'switch_any': [
        {'name': 'lengthy', 're': r'\blengthy\b'},
        {'name': 'costly', 're': r'\bcostly\b'},
        {'name': 'months', 're': r'\bmonths\b'},
        {'name': 'years', 're': r'\byears\b'},
        {'name': 're- で始まる語（re-qualify 等）', 're': r'\bre-[a-z]\w+'},
        {'name': 'requalif* / recertif* / revalidat*', 're': r'\bre(?:qualif|certif|validat)\w*'},
        {'name': 'switching cost / time-consuming', 're': r'\bswitching\s+costs?\b|\btime[- ]consuming\b'},
    ],
    'f1_switch': [
        {'name': 'lengthy', 're': r'\blengthy\b'},
        {'name': 'costly', 're': r'\bcostly\b'},
        {'name': 'months', 're': r'\bmonths\b'},
        {'name': 'years', 're': r'\byears\b'},
        {'name': 're-qualif* / requalif*', 're': r'\bre-?qualif\w*'},
        {'name': 're-certif* / recertif*', 're': r'\bre-?certif\w*'},
    ],
    'requal_bonus': [{'name': '再認定・再認証・再検証の語', 're': r'\bre-?(?:qualif|certif|validat)\w*'}],
}
F1_WINDOW = 40
PARA_MIN_WORDS, PARA_MAX_WORDS, UNIT_MAX_WORDS, TOP_K = 12, 350, 1800, 8
SEMI_NAMED = ['KLAC', 'TER', 'ENTG', 'CCMP', 'MKSI', 'AEIS', 'BRKS', 'CYMI', 'VECO', 'NVLS', 'LRCX', 'AMAT', 'ASML', 'UCTT',
              'ICHR', 'ONTO', 'NANO', 'FORM', 'COHU', 'KLIC', 'ACLS', 'PLAB', 'CAMT', 'AMKR', 'ATMI', 'CMOS', 'NVMI', 'RTEC', 'PKE']
SEED = 20260928


def prereg_dict():
    return {
        'angle': 'moat_text_pre2007',
        'title_ja': 'irr=85（顧客側の再認定ロック）を2007年より前の10-K本文で初めて検定する——堀の読みは逆風の時代にも純粋な時価加重の市場に勝つか',
        'stage': '第1段（準備）で凍結。本文を抽出する前・読み手に渡す前・株価を一度も取得・参照していない時点',
        'global_prereg': 'out/mw_prereg.json（線 C1〜C8・格 S/A/B/C は mw_common.grade をそのまま当てる。線は結果を見て動かさない）',
        'question': ('自社の 10-K が『顧客の側の再認定・認証のロック』（門の irr=85 の機構＝顧客自身の工程・製品が当社の部品・仕様で認定・認証されていて、'
                     '乗り換えるには顧客が再認定をやり直す——FAA/OEM 承認の航空部品・FDA 下の医療機器の部材・ファブに認定された半導体の材料と装置・'
                     '国防総省の単独調達）を述べている S&P500 の会社は、訓練期間 1997-07〜2006-12（irr85 の既存の証拠がすべて生まれた AI・半導体の相場より前で、'
                     'ハードウェアと半導体に逆風だった独立の時代）と、新しく読んだビンテージでの 2007-01 以降に、純粋な時価加重の米国市場（French Mkt）に勝ったか'),
        'universe': {
            'membership': 'out/_mw_cache/ie_sp500_components.csv（fja05680/sp500・mw_index_events と同じ）。各ビンテージ v の形成は v年7月1日、名簿は v年6月30日以前で最後の日付のもの（後から分かる情報を使わない）',
            'ticker_note': '名簿の記号は CRSP 流の『その会社の最後の記号』であることが多い（例: 1997年のアルコアが ARNC・マグロウヒルが SPGI）。同じ記号の文字列に二社がつぶれている箇所もある（例: 1997年の T）',
            'cik_mapping': ('候補＝今日の SEC 一覧（company_tickers.json）でその記号を持つ CIK ∪ EDGAR 全文検索（2001〜）で『symbol T』を 10-K（添付を含む）で名乗った提出者 ∪ '
                            '1995-01〜2001-06 の 10-K（ex27 のキャッシュの『symbol』抜粋を取引所の文脈つきで読み直したもの）で T を名乗った提出者 ∪ 社名の一致'
                            '（今日の SEC 名・全文検索の表示名・ウィキペディアの入れ替え表の名 と 窓の 10-K 提出者名）。検問＝その CIK が窓の中で 10-K を出していること。'
                            '大きさの検問＝表紙の非関係者の時価（float）が5倍以上大きい別の候補がいる候補は外す（他社の記号を本文に書いただけの小型株を拾わないため）。'
                            '決め方＝T を自分の記号として名乗った年（窓の本文・1995〜2001・全文検索の提出年・今日の保有者は 2026年）がビンテージに最も近い候補。'
                            '同点・拮抗（2番手との差が3年未満）のときは 合同の 10-K（同じ本文）→ 今日の保有者 → 時価の分かる社が一つ → 最大の時価が2番手の2倍以上 の順で決め、決まらなければ曖昧。'
                            '名乗りの証拠が無ければ社名の一致が一意のときだけ採る。名乗りが6年以上離れる候補は時価が当時に名乗った社の下位10%点の1/3未満なら使い回しとして棄てる。'
                            '同じ CIK が二つの記号に当たったら 手の対応 → 窓の本文で名乗った方 → 名乗りの近い方 に残し、他方はその CIK を除いて決め直す。'
                            'そのうえで全ビンテージの対応結果の社名を一件ずつ目で見て、明らかな誤り（小型株・子会社・資金調達の信託を拾ったもの）と付かなかった社を、'
                            '窓の 10-K 提出者名で CIK を確かめて手で直した（MANUAL_MAP・このファイルに理由つきで全件。株価は一度も見ていない）。'
                            '外国の提出者（20-F/40-F）・当時 10-K を出していなかった社（Fannie Mae/Freddie Mac の一部の年）・10-K が訂正で窓の後にずれた社は対応なしとして一覧に残す'),
            'coverage_reporting': '各ビンテージの名簿の社数・対応できた社数・窓に 10-K がある社数・本文が取れた社数・候補段落がある社数を数え、未対応の記号は全部列挙する',
        },
        'vintages': {
            'train': VINTAGES_TRAIN, 'holdout_fresh': VINTAGES_HOLD,
            'labels': '各ビンテージのラベルは3年持ち越す（1997→1997-07〜2000-06、2000→2000-07〜2003-06、2003→2003-07〜2006-06、2006→2006-07〜2009-06、2009→2009-07〜2012-06、2012→2012-07〜2015-06）',
            'train_returns': '訓練に数えるのは 1997-07〜2006-12 の月だけ（2006 ビンテージの 2007-01〜2009-06 は保有期間に入る＝報告で分けて出す）',
            'report_only': 'out/irr_regrade 等にある既存の 2013/2015/2018 の読みは報告のみ（新しいビンテージとして使わない・判定に使わない）',
        },
        'budget': {
            'max_reading_units': BUDGET,
            'unit': '読み手に実際に渡す社×ビンテージ（候補段落が1つ以上ある単位）。候補段落が0の単位は読まずに no85 とする（下の自動ラベル）',
            'cascade': ['合計が1,400を超えたら、まず最も新しい保有期間のビンテージ 2012 を丸ごと読まない（2012 の社は無ラベル）',
                        'それでも超えたら、残りの各ビンテージの中から同じ割合で無作為に抜く（種 20260928）。抜いた単位は無ラベル（lock にも非 lock にも入れない）。2009 は落とさない＝新しく読む保有期間のビンテージを最低1つ残す'],
            'scope': ('予算が効くのは読みの族（F2・rep・dur）だけ。F1（機械）は全ビンテージ・全単位で数える。2012 を読まない場合、F2・rep・dur の 2012 ビンテージは丸ごと無ラベル（自動 no85 も含めて作らない）で、'
                      '2009 ビンテージの持ち物が 2012-07 以降も買って持たれる（portfolios.after_last_vintage）'),
        },
        'text_rules': {
            'filing': '窓＝形成の前15か月（v-1 年4月1日〜v 年6月30日）に提出された 10-K / 10-K405 / 10-KT / 10-KT405 のうち最新の1件（訂正 /A は使わない・10-KSB は対象外）。EDGAR full-index の form.idx から',
            'source': ('1995-01〜2001-06 の提出は ex27 のキャッシュ（本体の先頭 60,000 字・読むだけ）を先に見て、本体が 60,000 字に収まっていればそれを使い、切れていれば全文 .txt を取り直す。'
                       'それ以外は https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}.txt（SEC の User-Agent は連絡先つき・毎秒6件以下）'),
            'sections': ('本体（最初の 10-K 型の文書）だけから Item 1（Business。『Items 1 and 2』は Item 3 まで）・Item 1A（Risk Factors）・Item 7（MD&A）を見出しで切り出す。'
                         '目次の見出しを避けるため、同じ見出しの候補のうち次の見出しまでが最も長いものを採る。本体が Item 7 を年次報告書（EX-13）へ委ねている場合は Item 7 は無し'
                         '（EX-13 は読まない＝1990年代は Item 7 が本体に無いことが多い。これは時代の非対称として記録する）。見出しが一つも無い本体は先頭 150,000 字を Item 1 の代わりにする'),
            'paragraphs': f'空行で段落に分け、改行をつなぐ。{PARA_MIN_WORDS}語未満・数字の語が4割以上（表）・大文字だけの見出しは捨てる。600語を超える塊は文の区切りで約300語ずつに分ける',
        },
        'regex': {k: v for k, v in RX.items()},
        'regex_notes': ('大文字小文字を区別しないのが既定、case=true の式だけ区別する。exclude に当たった区間に重なる qual の当たりは数えない（公認会計士・証書・税務の qualified などの定型を除くため）。'
                        '指示書の語から変えた点: fab* は fabric/fabricate を拾うので fab/fabs/wafer fab/fabrication facility に限った。switch_any に switching cost と time-consuming を足した。'
                        'counterparty に NRC（提案の F1 の語）を足した。client は足していない'),
        'candidate_rule': '候補段落＝qual の当たりが1つ以上 かつ（counterparty または switch_any の当たりが1つ以上）',
        'ranking_rule': ('段落の点＝2×（当たった qual の式の種類数）＋1×（counterparty の式の種類数）＋2×（switch_any の式の種類数）＋4×［F1 の条件を段落の中で満たす］＋3×［requal_bonus の語がある］。'
                         f'点の高い順に最大 {TOP_K} 段落（同点は文書の前から）。各段落は最大 {PARA_MAX_WORDS} 語（長ければ最初の qual の当たりの120語前から切り出す）。'
                         f'単位の合計は最大 {UNIT_MAX_WORDS} 語（点の順に足し、超える段落は残りが80語以上なら残りの語数に切り、80語未満なら打ち切る）。読み手には文書の順に並べて渡す'),
        'auto_label': '候補段落が0の単位は読まずに irr=no85（非 lock）とする。これは事前に決めた既定で、限界として数を報告する（本文に機構があっても語の網に掛からなければ非 lock になる）',
        'F1': {
            'definition': (f'機械の族・漏れなし（人も LLM も読まない）: 抽出した Item 1/1A/7 のどれかの段落の中に、qual の当たり q・counterparty の当たり c・f1_switch の当たり s があり、'
                           f'|q−c| ≤ {F1_WINDOW} 語 かつ |q−s| ≤ {F1_WINDOW} 語（語の位置は空白で区切った語の番号）なら、その社×ビンテージを F1 の旗とする。exclude は同じく効かせる。候補の上位8段落ではなく全段落で数える'),
            'portfolio': 'F1 の旗の社を lock と同じ作り方で持つ（副の族）',
        },
        'F2': {
            'protocol': ('伏せた段落だけを読む。独立の読み手2人（別々のセッション・互いの答えを見ない）が全単位を読む。irr≥85（100 も 85 と数える）かどうかで2人が割れた単位だけを3人目が読み、'
                         '最終のラベルは3人の多数決（85以上か否か）。irr の刻みそのものは報告用（2人一致ならその値・割れたら3人目の値）'),
            'reader_instructions': 'out/_mw_cache/moat_text/READER_INSTRUCTIONS.md（門の irr の規約・85 の二重読みの検問①〜⑥・out/irr_regrade/RUBRIC.md を逐語で写し、rep/dur の刻みも門のまま）',
            'reader_output': 'irr ∈ {100,85,70,50,null}＋一文の理由＋85/100 を支える原文の逐語の引用（無ければ null）、rep ∈ {100,80,60,35,null}、dur ∈ {100,85,75,55,null}、recognised（どの会社か分かったと思うか・社名は書かない）、confidence 1〜3',
            'reader_limits': '渡された束のファイルと指示書だけを読む（Web・リポジトリの他のファイル・鍵のファイル KEY_do_not_open.json は開かない）',
            'subsets_report': ['2人が一致した単位だけの lock', 'どちらの読み手も recognised=false の単位だけの lock', '読み手どうしの一致率（κ）'],
        },
        'masking': ('社名（ヘッダの COMPANY CONFORMED NAME・FORMER CONFORMED NAME・今日の SEC 名）と、本文の定義の中の別名（("XYZ" or the "Company") の類）、'
                    'EX-21 の子会社名（本文に現れるもの）、記号（名簿の記号・本文が名乗る記号）→ [COMPANY]。'
                    '固有の製品・ブランド・相手先の名＝その社の抽出本文（Item 1/1A/7 全体）の中で大文字で始まる語のうち、3回以上現れ（文頭を含む）・文頭でない所に一度は現れ・小文字の形では一度も現れず・同じビンテージの文書の3%未満にしか現れず・'
                    '保持語（規制当局・相手先の略語・月・地名の一般語など）でないもの → [PRODUCT_n]（単位ごとに初出順の番号）。業種の語は残す。'
                    '単位の順番は種 20260928 で無作為に並べ、不透明な id（u0001…）を振る。id → CIK・記号・ビンテージ・SIC の鍵は out/_mw_cache/moat_text/KEY_do_not_open.json（読み手は開かない）'),
        'batches': '約60単位ずつ out/_mw_cache/moat_text/batches/batch_XX.json。各単位は {id, vintage_year, passages:[...]}（時代の文脈のため年は渡す。SIC・社名は渡さない）',
        'labels_to_portfolios': {
            'lock': '最終ラベル irr ∈ {85, 100}（門と同じく 100 も 85 と数える）',
            'nonlock': '最終ラベル irr ∈ {70, 50, null} と自動 no85',
            'unlabelled': '記号→CIK が対応できない・窓に 10-K が無い・本文が取れない・予算で読まなかった単位（lock にも非 lock にも入れない。数を報告する）',
        },
        'portfolios': {
            'formation': '各ビンテージ v の7月（最初のリターン月は v年7月）に作り、次のビンテージまで3年持つ（年の途中で入れ替えない・S&P500 から外れても持ち続ける）',
            'vw_primary': ('時価加重（主）: 重み＝本文に使った 10-K の表紙の非関係者の時価（形成の時点で分かっている値）。表紙から読めない社はそのビンテージの中央値を置く（数を報告）。'
                           '重みは持っている間リターンで漂わせる（買って持つ）'),
            'ew': '等加重: 形成時に等分し、毎月等分に戻す（観測できる社の平均）',
            'after_last_vintage': ('最後に読んだビンテージの持ち物は、3年を過ぎても 2026-08 まで買って持ち続ける（ラベルは古いまま・入れ替えない）。'
                                   '保有期間の判定はこれを含めた 2007-01〜2026-08 で行い、新しいラベルだけの窓（2007-01〜最後のビンテージ＋36か月）も並べて報告する'),
            'cohort_report': '報告のみ: 各ビンテージの lock を5年と2026-08まで買って持つ（NISA 型の手を触れない持ち方）',
        },
        'returns': ('Yahoo の月次の調整後終値（配当込み・mw_common.yahoo と同じ）。系列の選び方（CIK と同じ会社の系列だけを使う）: '
                    '(a) 対応した CIK が今日の SEC 一覧に記号を持てばその記号。(b) 持たなければ名簿の記号 T——ただし T の今日の保有者が別の CIK なら、'
                    'その保有者が当時（そのビンテージの窓）に 10-K を出しておらず、かつ社名が続いている（正規化した社名の先頭語が一致するか一方が他方の前方一致で5字以上・一般語でない）'
                    'ときだけ同じ会社の続き（持株会社への組み替え・改名）として T を使い、それ以外は別の会社の系列なので観測なしにする。(c) T を今日だれも持たなければ T を試す。'
                    'どの場合も系列の最初の月が形成月より後なら観測なし（記号の使い回しを踏まない＝mw_index_events.obs と同じ検問）。月 +300% 超はデータの誤りとしてその月から先を捨てる'),
        'float_sanity': '表紙の時価が 5,000万ドル未満または 1兆ドル超なら読み違いとして欠測扱い（そのビンテージの中央値を置く）',
        'survivorship': ('観測できない月の扱いを二通りで囲む（mw_index_events と同じ）: S＝その月から外す（最後の値で売り、残りへ按分）／L＝その月 −100% として外す。'
                         '格は S と L の両方で付け、保有期間の超過の符号が S と L で一致したときだけ格を付ける（割れたら C）。付ける格は S と L の低い方'),
        'benchmarks': {
            'primary': 'French Mkt（Mkt-RF + RF・上限なしの時価加重・CRSP 全上場）',
            'secondary': '同じビンテージの対応済み・ラベル付きの全社（lock＋非 lock＋自動 no85）を同じ作り方（同じ Yahoo・同じ S/L・同じ重み）で持った時価加重＝生き残りの偏りを一次で打ち消す相手',
        },
        'controls': {
            'within_sic2': '業種をそろえる: lock の各社のリターン − 同じビンテージ・同じ SIC 上2桁の非 lock の時価加重、を lock の重みで平均（同じ SIC2 に非 lock が居ない社はこの対照から外し数を報告）',
            'ex_semis_chain': f'半導体の連鎖を除く: SIC 3674・3559、および名指しの装置・材料 {SEMI_NAMED}',
            'ex_aero_defence': '航空・防衛を除く: SIC 3720-3729・3760-3769・3812',
            'sic_source': 'SIC は本文に使った 10-K のヘッダ（当時の値）。無ければ今日の SEC の値（印を付ける）',
        },
        'secondary_families': {
            'F1': 'F1 の旗（機械）',
            'rep_top': '最終 rep ∈ {100, 80}（2人の読みの一致・割れは3人目・3人目が読んでいない単位は2人の低い方）',
            'dur_top': '最終 dur ∈ {100, 85}（門と同じく 100 を 85 と数える。決め方は rep と同じ）',
        },
        'periods': {'train': '1997-07〜2006-12（訓練のビンテージ 1997/2000/2003/2006 のラベルだけ）', 'holdout': '2007-01〜2026-08（2006 ビンテージの 2007-01〜2009-06 を含む＝報告で分ける）',
                    'full': '1997-07〜2026-08', 'recent': '2013-07〜（報告のみ）'},
        'tests_holm': {
            'family': ['H1 F2 lock 時価加重 − French Mkt（主）', 'H2 F2 lock 等加重 − French Mkt', 'H3 F2 lock 時価加重 − 同じ母集団の時価加重',
                       'H4 F1 時価加重 − French Mkt', 'H5 F1 時価加重 − 同じ母集団の時価加重', 'H6 rep 上位 時価加重 − French Mkt', 'H7 dur 上位 時価加重 − French Mkt'],
            'rule': '保有期間の NW t（ラグ12）から両側 p、この7本で Holm（S と L で別々に）。C7 は全期間 t≥3.0 または Holm 後 p<0.05',
            'report_only': ['業種そろえ（SIC2）', '半導体の連鎖を除く', '航空・防衛を除く', '2人一致の部分集合', '誰も会社を分からなかった部分集合', '新しいラベルだけの保有期間', '2006 ビンテージのはみ出し 2007-01〜2009-06',
                            '2013-07〜', '5年の手を触れない持ち方']},
        'grading': ('mw_common.grade(full, train, hold, roll20, cost_hold, repl=None, family_holm_p, leveraged_or_timing=False)。C4 は全期間の転がる20年窓（毎年7月起点・一括）。'
                    'C5 は米国外の本文が無いので N/A。C8 は該当なし'),
        'costs': '片道の売買 100% あたり 0.10%（大型株）。売買は各ビンテージの作り替え（漂った重み→新しい重み の差の半分の合計）と最初の買い。年あたりの平均回転率で月割りに引く（mw_common.apply_cost）',
        'reachability': ('株価を見る前に数えて記録する: 各ビンテージの F1 の旗の社数（第1段で数える）と F2 の lock の社数（第2段の読みの後）。'
                         'lock が10社未満のビンテージは『薄い』と印を付けて報告する（格は変えない）'),
        'knowledge_leak_note': [
            '台帳の既存の結果を知っている: 2013/2015/2018 の3ビンテージで irr=85 の社単位 lift +0.404（置換 p≈0・n=627）・半導体を除いて +0.315・『半導体の連鎖』のラベル単体は +0.436（irr=85 より大きい）・irr=100 は負（docs/CLAUDE_ARCHIVE.md L12717）',
            '2007年以降の歴史を知っている: 巨大テックと半導体（特に 2016〜 と AI 相場の 2023〜）が米国の勝ちの大半を説明した・質や収益性の因子は 2007年以降の純粋な時価加重の市場に対してほぼ0（mw の既存の結果）',
            '業種の時代を知っている: 半導体は 1998〜2000 のバブル・2000〜2002 の崩壊・2000年代は出遅れ・2016〜 に大勝ち。航空・防衛は 2001年の同時多発テロの後に民間航空が崩れ、防衛は 2002〜2007 に強く、2020年の感染症で民間航空が再び崩れた。医療機器は 1990〜2000年代に強かった',
            '読み手（LLM）は会社の歴史を知っている。社名を伏せても言い当てうる（angles4 では 92% を言い当てた）ので recognised を記録し、誰も分からなかった部分集合を報告する',
            '設計者（私）は今日の門の irr=85 の顔ぶれ（CW・LRCX・WST・COHR・BWXT など）を知っている。語の網と規約は門の既存の文言から写し、結果を見て変えない',
        ],
        'known_limits': [
            '名簿の記号は後の記号で、同じ記号に二社がつぶれた箇所がある（対応の誤りは数えて報告し、抜き取りで点検する）',
            '1990年代の 10-K は本体が短く年次報告書（EX-13）に委ねる社が多い。Item 7 は時代で有無が違う（ビンテージの中の比較なので水準の差は打ち消される）',
            '語の網に掛からない機構は自動で非 lock になる（取りこぼしは lock を薄める向き）',
            'Yahoo は上場廃止した社の履歴を持たない。S/L で囲むが、囲みが広いと格が付かない',
            '最後のビンテージの後は古いラベルのまま持ち続ける（2012 を読まなければ 2009 のラベルで 2026 まで）',
            '株価で重みを付けない（表紙の時価は数か月〜1年古い）',
        ],
    }


def universe_summary():
    U = json.load(open(UNIV))
    out = {}
    for v, V in U['vintages'].items():
        un = [f"{r['t']}（{r['via']}{'：' + r['note'][:60] if r.get('note') else ''}）" for r in V['rows'] if not r.get('path')]
        out[v] = {'membership_date': V['membership_date'], 'window': V['window'], 'members': V['n_members'],
                  'mapped_with_10k_in_window': V['n_mapped_with_10k'], 'mapping_rate': V['mapping_rate'],
                  'n_manual': sum(1 for r in V['rows'] if r['via'] == 'manual'), 'via': V['via'], 'not_mapped': un}
    return out


def cmd_prereg(stage='freeze'):
    """stage='freeze' ＝ 抽出の前（第1コミット）。stage='coverage' ＝ 抽出・予算・伏せの後に数を足す（第2コミット・株価は見ていない）"""
    P = prereg_dict()
    old = json.load(open(PREREG)) if os.path.exists(PREREG) else {}
    P['generated'] = old.get('generated') or datetime.date.today().isoformat()
    P['frozen_before_extraction'] = True
    P['coverage_mapping_at_freeze'] = old.get('coverage_mapping_at_freeze') or universe_summary()
    P['manual_map_entries'] = len(MANUAL_MAP)
    P['deviations_from_task_text'] = [
        'night/irr85_criteria.py は読みの規約の文を持たない（別枠85 の下限を歴史で調べる道具）。指示書には index.html の刻み・審査プロトコル（ccfAskText）の irr/rep/dur の節と out/irr_regrade/RUBRIC.md を逐語で写した',
        'ex27 のキャッシュは raw/{受付番号の先頭10桁}/{受付番号}.json.gz の形（raw/{CIK}/ ではない）。読むだけ',
        '語の網: fab* を fab/fabs/wafer fab/fabrication facility に限った（fabric を拾わないため）。switch_any に switching cost と time-consuming、counterparty に NRC を足した',
        '記号→CIK の対応は機械の規則だけでは小型株・子会社を拾う誤りが残ったので、全ビンテージを目で見て手で直した（MANUAL_MAP・理由つき）',
    ]
    if stage == 'coverage':
        P['deviations_from_task_text'] += [
            '【第1コミットの後・読む前・株価を見る前の是正 1】見出しの正規表現が『ITEM 1 BUSINESS』（句点なし）を Item 1B と読み、Item 1 を取り損ねていた。'
            '接尾の A/B/C の後に英字が続かないことを条件に加え、保存した本体の平文から節を切り直した（取り直しなし）。本文の取れた単位 +16（候補段落のある単位 1,453→1,460）。語の網・順位・上限は一字も変えていない',
            '【是正 2】別名の検出が括弧の中の引用語をすべて拾い、一般の略語（HTML・ERISA・HMOs）や競合の社名（Oracle・Microsoft）まで [COMPANY] にしていた。'
            '事前登録の文言どおり、会社自身の定義の括弧（Company/Registrant/we/us/our/subsidiaries/collectively の語を含む括弧）の中の引用語だけに絞った',
            '【是正 3】社名の固有の語は小文字の形が本文に一度でもあると伏せなかったため、URL（cisco.com 等）や一般語（southwest）のせいで社名が残っていた。'
            'URL を除いて判定し、小文字の形がある語も大文字始まり・全大文字の形だけは伏せるようにした。是正後、社名の固有の語が残る単位は 1,138 中 0（機械の点検）',
        ]
    if stage == 'coverage':
        P['coverage_after_extraction'] = json.load(open(COVER))
        k = json.load(open(KEYF))
        P['budget_applied'] = k['budget']
        P['reading_units'] = len(k['units'])
        P['auto_no85'] = {'all_vintages': len(k['auto_no85']), 'f2_labelled_vintages': sum(1 for x in k['auto_no85'] if x.get('f2_labelled')),
                          'by_vintage': dict(Counter(str(x['vintage']) for x in k['auto_no85']))}
        P['f2_labelled_firm_vintages'] = len(k['units']) + P['auto_no85']['f2_labelled_vintages']
        P['f1_counts'] = {v: c.get('f1') for v, c in P['coverage_after_extraction'].items()}
        P['units_by_vintage'] = dict(Counter(str(x['vintage']) for x in k['units'].values()))
        P['batches'] = sorted(os.path.relpath(os.path.join(BATCH, f), BASE) for f in os.listdir(BATCH))
        P['stage'] = P['stage'] + '。第2コミットで被覆・予算の適用・F1 の数を足した（株価はまだ取得も参照もしていない）'
    json.dump(P, open(PREREG, 'w'), ensure_ascii=False, indent=1)
    for kk in ('qual', 'exclude', 'counterparty', 'switch_any', 'f1_switch', 'requal_bonus'):
        for x in RX[kk]:
            re.compile(x['re'])
    print('書いた', PREREG)


# ───────────────────────── 抽出（凍結した式を事前登録の JSON から読む） ─────────────────────────
import bisect
UNITS = os.path.join(MT, 'units_private.jsonl.gz')       # 伏せる前の抽出（読み手は開かない）
KEYF = os.path.join(MT, 'KEY_do_not_open.json')
BATCH = os.path.join(MT, 'batches')
INSTR = os.path.join(MT, 'READER_INSTRUCTIONS.md')
COVER = os.path.join(MT, 'coverage.json')
NUMTOK = re.compile(r'\d')


def load_rx():
    R = json.load(open(PREREG))['regex']
    return {k: [(x['name'], re.compile(x['re'], 0 if x.get('case') else re.I)) for x in v] for k, v in R.items()}


def split_paras(text):
    raw = []
    for b in re.split(r'\n\s*\n', text or ''):
        p = re.sub(r'\s+', ' ', b).strip()
        if not p:
            continue
        if len(p.split()) > 600:
            cur = []
            for s_ in re.split(r'(?<=[.;:])\s+(?=[A-Z(“"])', p):
                cur.append(s_)
                if sum(len(x.split()) for x in cur) >= 300:
                    raw.append(' '.join(cur)); cur = []
            if cur:
                raw.append(' '.join(cur))
        else:
            raw.append(p)
    out = []
    for p in raw:
        w = p.split()
        if len(w) < PARA_MIN_WORDS:
            continue
        if sum(1 for x in w if NUMTOK.search(x)) / len(w) >= 0.4:
            continue
        L = [ch for ch in p if ch.isalpha()]
        if L and sum(ch.isupper() for ch in L) / len(L) > 0.8:
            continue
        out.append(p)
    return out


def analyze(p, RXC):
    ex = [m.span() for _, r in RXC['exclude'] for m in r.finditer(p)]

    def hits(key, excl=False):
        o = []
        for n, r in RXC[key]:
            for m in r.finditer(p):
                if excl and any(a < m.end() and m.start() < b for a, b in ex):
                    continue
                o.append((n, m.start()))
        return o
    q = hits('qual', True)
    c = hits('counterparty'); sw = hits('switch_any'); f = hits('f1_switch'); rb = hits('requal_bonus', True)
    cand = bool(q) and bool(c or sw)
    starts = [m.start() for m in re.finditer(r'\S+', p)]
    wi = lambda pos: bisect.bisect_right(starts, pos) - 1
    f1 = False
    if q and c and f:
        cw = [wi(x[1]) for x in c]; fw = [wi(x[1]) for x in f]
        f1 = any(any(abs(wi(x[1]) - b) <= F1_WINDOW for b in cw) and any(abs(wi(x[1]) - d) <= F1_WINDOW for d in fw) for x in q)
    score = 2 * len({n for n, _ in q}) + len({n for n, _ in c}) + 2 * len({n for n, _ in sw}) + 4 * f1 + 3 * bool(rb)
    return {'cand': cand, 'f1': f1, 'score': score, 'q0': wi(min(x[1] for x in q)) if q else 0,
            'qn': sorted({n for n, _ in q}), 'cn': sorted({n for n, _ in c}), 'sn': sorted({n for n, _ in sw})}


SECS = (('item1', 'Item 1'), ('item1_fallback', 'Item 1（見出しなし・本体の先頭）'), ('item1a', 'Item 1A'), ('item7', 'Item 7'))


def build_unit(doc, RXC):
    paras = []
    for k, lab in SECS:
        for i, p in enumerate(split_paras((doc.get('sections') or {}).get(k) or '')):
            paras.append((len(paras), lab, p))
    an = [analyze(p, RXC) for _, _, p in paras]
    f1 = any(a['f1'] for a in an)
    cands = [(a['score'], i) for i, a in enumerate(an) if a['cand']]
    top = sorted(cands, key=lambda x: (-x[0], x[1]))[:TOP_K]
    sel, total = [], 0
    for sc, i in top:
        w = paras[i][2].split(); q0 = an[i]['q0']
        if len(w) > PARA_MAX_WORDS:
            st = max(0, min(q0 - 120, len(w) - PARA_MAX_WORDS))
            seg, pre, post = w[st:st + PARA_MAX_WORDS], st > 0, st + PARA_MAX_WORDS < len(w)
            q0 -= st
        else:
            seg, pre, post = w, False, False
        rem = UNIT_MAX_WORDS - total
        if len(seg) > rem:
            if rem < 80:
                break
            st = max(0, min(q0 - min(120, rem // 3), len(seg) - rem))
            pre, post = pre or st > 0, True
            seg = seg[st:st + rem]
        total += len(seg)
        sel.append({'order': i, 'section': paras[i][1], 'text': ('… ' if pre else '') + ' '.join(seg) + (' …' if post else ''),
                    'score': sc, 'qual': an[i]['qn'], 'cp': an[i]['cn'], 'sw': an[i]['sn'], 'f1': an[i]['f1']})
    sel.sort(key=lambda x: x['order'])
    return {'n_paras': len(paras), 'n_cand': len(cands), 'f1': f1, 'passages': sel, 'words': total,
            'secs_present': [lab for k, lab in SECS if (doc.get('sections') or {}).get(k)]}


def cik_titles():
    d = json.load(open(os.path.join(CACHE, 'sec_company_tickers.json')))
    m = defaultdict(list)
    for v in d.values():
        m[str(v['cik_str'])].append((v['ticker'], v['title']))
    return m


def sic_fallback():
    m = {}
    for p in (os.path.join(BASE, 'out', 'sic_by_cik.json'), os.path.join(CACHE, 'mw_sec_sic.json')):   # 読むだけ
        if os.path.exists(p):
            try:
                for c, v in json.load(open(p)).items():
                    if v:
                        m.setdefault(str(int(c)), str(v))
            except Exception:  # noqa
                pass
    return m


def cmd_extract():
    RXC = load_rx()
    U = json.load(open(UNIV))
    ct, sicf = cik_titles(), sic_fallback()
    cov = {}
    n = 0
    with gzip.open(UNITS + '.tmp', 'wt') as g:
        for v in VINTAGES:
            V = U['vintages'][str(v)]
            c = Counter()
            for r in V['rows']:
                c['members'] += 1
                if not r.get('path'):
                    c['unmapped_or_no10k'] += 1; continue
                c['mapped_10k'] += 1
                doc = get_doc(r['path'])
                if doc.get('missing'):
                    c['doc_missing'] += 1; continue
                sec = doc.get('sections') or {}
                if not any(sec.get(k) for k, _ in SECS):
                    c['no_sections'] += 1; continue
                c['text_ok'] += 1
                u = build_unit(doc, RXC)
                c['f1'] += u['f1']
                c['cand'] += u['n_cand'] > 0
                c['auto_no85'] += u['n_cand'] == 0
                sic, sic_src = doc.get('sic'), 'header'
                if not sic:
                    sic, sic_src = sicf.get(r['cik']), 'current'
                rec = {'vintage': v, 't': r['t'], 'cik': r['cik'], 'via': r['via'], 'acc': doc['acc'], 'path': r['path'], 'filed': r['filed'],
                       'form': r['form'], 'name': doc.get('name') or r.get('name'), 'former': doc.get('former'), 'sec_now': ct.get(r['cik'], []),
                       'sic': sic, 'sic_src': sic_src if sic else None, 'float': doc.get('float'), 'symbols': list((doc.get('symbols') or {}).keys()),
                       'src': doc.get('src'), **u}
                g.write(json.dumps(rec) + '\n'); n += 1
            cov[str(v)] = dict(c)
            print(v, dict(c), flush=True)
    os.replace(UNITS + '.tmp', UNITS)
    json.dump(cov, open(COVER, 'w'), ensure_ascii=False, indent=1)
    print('単位', n)


# ───────────────────────── 伏せる ─────────────────────────
KEEP = set("""FAA FDA DoD DOD OEM OEMs NRC NASA EPA SEC FCC FTC DOE DOT ISO PMA PMAs STC STCs QPL QML AS9100 MIL SPEC GAAP IRS ERISA EU
U.S. US USA UK CEO CFO IT IP LCD LED LEDs RF IC ICs ASIC ASICs DRAM SRAM CMOS MEMS MRI CT PET PC PCs CPU CPUs GPU HMO HMOs PPO LNG CNG HVAC
OTC NYSE Nasdaq NASDAQ AMEX CMS Medicare Medicaid Congress Department Defense Navy Army Air Force Marine Corps Federal Government Commission
Administration Agency Office Bureau National International American Americas America North South East West Europe European Asia Asian Pacific
Japan Japanese China Chinese Canada Canadian Mexico Latin Germany German France French Korea Korean Taiwan India Brazil Russia Middle Africa
United States Kingdom January February March April May June July August September October November December Monday Friday Company Corporation
Item Items Part Business Risk Factors Management Discussion Analysis Results Operations Financial Condition Note Notes Annual Report Form
Internet Web World Wide Year Years Fiscal Board Directors Chief Executive Officer Officers President Vice Inc Corp Ltd LLC Co The This These
Those Our We In On At For As Of To By With From Such Any All Each Other New General Industry Industries Customer Customers Products Product
Services Service Market Markets Segment Segments Group Division Divisions System Systems Technology Technologies Research Development Act Rule
Rules Regulation Regulations Law Laws State States Court Courts Supreme Tax Code Treasury Reserve Bank Banks Insurance Exchange Securities
Commercial Industrial Aerospace Medical Health Healthcare Energy Electric Power Gas Oil Chemical Chemicals Semiconductor Semiconductors
Engineering Manufacturing Aviation Space Defense Military Nuclear Regulatory Food Drug Drugs Device Devices Clinical Laboratory Laboratories
Environmental Protection Patent Patents Trademark Trademarks Office Standards Standard Quality Assurance Certification Qualification""".split())
TOKC = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[-'&][A-Za-z0-9]+)*\b")
GEN_ALIAS = {'COMPANY', 'CORPORATION', 'REGISTRANT', 'WE', 'US', 'OUR', 'GROUP', 'BANK', 'PARTNERSHIP', 'TRUST', 'PARENT', 'ISSUER',
             'CORP', 'HOLDING', 'HOLDINGS', 'SUBSIDIARIES', 'SUBSIDIARY', 'AGREEMENT', 'PLAN', 'NOTES', 'SHARES', 'COMMON STOCK',
             'OFFERING', 'MERGER', 'ACQUISITION', 'BUSINESS', 'FUND', 'COMPANIES', 'OPERATING PARTNERSHIP', 'BOARD', 'ACT'}


def sent_initial(txt, pos):
    k = pos - 1
    while k >= 0 and txt[k] in ' \t\n"“(\'':
        k -= 1
    return k < 0 or txt[k] in '.!?:;•'


def cap_tokens(txt):
    """大文字始まりの語 → (全出現の Counter, 文頭でない所に一度でも現れた語の集合)"""
    c, mid = Counter(), set()
    for m in TOKC.finditer(txt):
        w = m.group(0)
        c[w] += 1
        if w not in mid and not sent_initial(txt, m.start()):
            mid.add(w)
    return c, mid


def doc_fulltext(doc):
    return '\n\n'.join((doc.get('sections') or {}).get(k) or '' for k, _ in SECS)


def name_regexes(names, fulltxt):
    """社名 → 句の正規表現・大小を問わず伏せる語（小文字の形が本文に無い）・大文字の形だけ伏せる語（社名の固有の語すべて）"""
    low = set(re.findall(r'\b[a-z][a-z0-9]+\b', re.sub(r'\S*(?:www\.|\.com|\.net|\.org|@)\S*', ' ', fulltxt)))
    pats, words, cs = [], set(), set()
    for nm in names:
        ws = nname(nm)
        if not ws:
            continue
        pats.append(r'[\s\-&.,\']*'.join(re.escape(w) for w in ws))
        if len(ws) > 1:
            pats.append(re.escape(''.join(ws)))
        for w in ws:
            if len(w) >= 4 and w not in NAME_GENERIC and not w.isdigit():
                (words if w.lower() not in low else cs).add(w)
    return pats, words, cs


ALIAS_RE = re.compile(r'\(\s*(?:(?:collectively|together)\s+with\s+its\s+(?:consolidated\s+)?subsidiaries[,;]?\s*)?(?:the\s+|or\s+|and\s+)?["“]([^"”]{1,40})["”]'
                      r'|(?:hereinafter|herein)\s+(?:referred\s+to\s+as\s+|called\s+)?(?:the\s+)?["“]([^"”]{1,40})["”]', re.I)


PAREN = re.compile(r'\(([^()]{2,240})\)')
SELF_WORDS = re.compile(r'(?i)\b(?:company|registrant|corporation|we|us|our|subsidiaries|collectively|hereinafter)\b')


def company_aliases(full):
    """会社自身の定義の括弧（『("XYZ" or the "Company")』『(together with its subsidiaries, "XYZ")』の類）の中の引用語だけを別名にする。
    括弧に Company/Registrant/we/us/our/subsidiaries/collectively の語が無い引用（"OEMs" や他社名）は別名にしない"""
    out = set()
    for m in PAREN.finditer(full[:60000]):
        inner = m.group(1)
        if not SELF_WORDS.search(inner) or not re.search(r'["“]', inner):
            continue
        for q in re.findall(r'["“]([^"”]{1,40})["”]', inner):
            q = q.strip().strip(',').strip()
            if len(q) >= 2 and q[:1].isupper() and q.upper() not in GEN_ALIAS and q.lower() not in ('we', 'us', 'our', 'the company'):
                out.add(q)
    return out


def mask_unit(rec, doc, df_share):
    full = doc_fulltext(doc)
    names = [rec.get('name') or ''] + list(rec.get('former') or []) + [t for _, t in rec.get('sec_now') or []]
    pats, words, cs = name_regexes([x for x in names if x], full)
    aliases = company_aliases(full)
    ticks = {rec['t']} | set(rec.get('symbols') or []) | {t for t, _ in rec.get('sec_now') or []}
    ex21 = []
    for sname in doc.get('ex21') or []:
        ws = nname(sname)
        if ws and any(len(w) >= 4 and w not in NAME_GENERIC for w in ws):
            ex21.append(r'[\s\-&.,\']*'.join(re.escape(w) for w in ws))
    suffix = r"(?:[\s,]+(?:Inc|Corp|Corporation|Co|Company|Ltd|Limited|plc|PLC|Incorporated|N\.V|S\.A|AG|L\.P|LLC)\b\.?)*(?:'s|’s)?"
    comp = [re.compile(r'\b(?:' + '|'.join(sorted(set(pats + ex21), key=len, reverse=True)) + r')' + suffix, re.I)] if (pats or ex21) else []
    if words:
        comp.append(re.compile(r'\b(?:' + '|'.join(sorted((re.escape(w) for w in words), key=len, reverse=True)) + r")\b(?:'s|’s)?", re.I))
    if cs:       # 社名の固有の語で小文字の形も本文にあるもの（例: Southwest・Countrywide）は大文字始まり・全大文字の形だけ伏せる
        forms = sorted({f for w in cs for f in (w.title(), w)}, key=len, reverse=True)
        comp.append(re.compile(r'\b(?:' + '|'.join(re.escape(f) for f in forms) + r")\b(?:'s|’s)?"))
    if aliases:
        comp.append(re.compile(r'(?<![A-Za-z])(?:' + '|'.join(sorted((re.escape(a_) for a_ in aliases), key=len, reverse=True)) + r")(?![A-Za-z])(?:'s|’s)?"))
    tk = [t for t in ticks if t and len(t) >= 2]
    if tk:
        comp.append(re.compile(r'(?<![A-Za-z])(?:' + '|'.join(sorted((re.escape(t) for t in tk), key=len, reverse=True)) + r')(?![A-Za-z])'))
    one = [t for t in ticks if t and len(t) == 1]
    if one:
        comp.append(re.compile(r'["“](?:' + '|'.join(re.escape(t) for t in one) + r')["”]'))
    # 固有の製品・相手先の名: 抽出本文で3回以上・小文字の形が無い・同じビンテージの文書の3%未満・保持語でない
    low = set(re.findall(r'\b[a-z][a-z0-9\-]+\b', full))
    capc, mid = cap_tokens(full)
    prod = {w for w, n_ in capc.items() if n_ >= 3 and w in mid and w.lower() not in low and w not in KEEP and df_share.get(w, 0) < 0.03
            and not w.isdigit() and len(w) >= 2}
    out, pmap = [], {}
    for p in rec['passages']:
        t = p['text']
        for rx in comp:
            t = rx.sub('[COMPANY]', t)

        def rep(m):
            w = m.group(0)
            if w not in prod:
                return w
            if w not in pmap:
                pmap[w] = f'[PRODUCT_{len(pmap) + 1}]'
            return pmap[w]
        t = re.sub(r'\[COMPANY\]|\[PRODUCT_\d+\]|' + TOKC.pattern, lambda m: m.group(0) if m.group(0).startswith('[') else rep(m), t)
        t = re.sub(r'(\[COMPANY\][\s,]*){2,}', '[COMPANY] ', t)
        out.append({'section': p['section'], 'text': t})
    return out, {'n_names': len(pats), 'n_words': len(words), 'n_alias': len(aliases), 'n_ticks': len(ticks), 'n_prod': len(pmap)}


def apply_budget(recs):
    """事前登録の順: 合計 > 1,400 なら 2012 を落とす → まだ超えるなら残りの各ビンテージから同じ割合で無作為に抜く（種 20260928）"""
    rd = [r for r in recs if r['n_cand'] > 0]
    log = {'units_with_candidates': len(rd), 'by_vintage': dict(Counter(r['vintage'] for r in rd))}
    dropped_v, sampled_out = [], set()
    if len(rd) > BUDGET:
        dropped_v.append(2012)
        rd = [r for r in rd if r['vintage'] != 2012]
    if len(rd) > BUDGET:
        rng = random.Random(SEED)
        frac = BUDGET / len(rd)
        keep = []
        for v in sorted({r['vintage'] for r in rd}):
            g_ = sorted((r for r in rd if r['vintage'] == v), key=lambda r: (r['cik'], r['t']))
            k = int(round(len(g_) * frac))
            pick = set(rng.sample(range(len(g_)), k))
            for i, r in enumerate(g_):
                (keep.append(r) if i in pick else sampled_out.add((r['vintage'], r['cik'], r['t'])))
        while len(keep) > BUDGET:
            r = keep.pop(rng.randrange(len(keep))); sampled_out.add((r['vintage'], r['cik'], r['t']))
        rd = keep
    log.update(dropped_vintages=dropped_v, n_sampled_out=len(sampled_out), n_read=len(rd), read_by_vintage=dict(Counter(r['vintage'] for r in rd)))
    return rd, log, sampled_out


def cmd_mask():
    recs = [json.loads(l_) for l_ in gzip.open(UNITS, 'rt')]
    read, blog, sampled_out = apply_budget(recs)
    dfs = {}
    for v in VINTAGES:                      # 同じビンテージの文書頻度（大文字始まりの語が何割の文書に現れるか）
        cnt, nd = Counter(), 0
        for r in recs:
            if r['vintage'] != v:
                continue
            cnt.update(set(cap_tokens(doc_fulltext(get_doc(r['path'])))[0]))
            nd += 1
        dfs[v] = {w: c / nd for w, c in cnt.items()} if nd else {}
    rng = random.Random(SEED)
    order = list(range(len(read)))
    rng.shuffle(order)
    key, units, mstat = {}, [], Counter()
    for j, i in enumerate(order):
        r = read[i]
        uid = f'u{j + 1:04d}'
        ps, st = mask_unit(r, get_doc(r['path']), dfs[r['vintage']])
        for k_, x in st.items():
            mstat[k_] += x
        units.append({'id': uid, 'vintage_year': r['vintage'], 'passages': ps})
        key[uid] = {'cik': r['cik'], 'ticker': r['t'], 'vintage': r['vintage'], 'sic': r['sic'], 'sic_src': r['sic_src'], 'name': r['name'],
                    'acc': r['acc'], 'filed': r['filed'], 'form': r['form'], 'via': r['via'], 'f1': r['f1'], 'n_cand': r['n_cand'],
                    'float': r['float'], 'words': r['words']}
    auto = [{'vintage': r['vintage'], 'ticker': r['t'], 'cik': r['cik'], 'sic': r['sic'], 'sic_src': r['sic_src'], 'name': r['name'],
             'acc': r['acc'], 'f1': r['f1'], 'float': r['float'], 'label': 'no85_auto',
             'f2_labelled': r['vintage'] not in blog['dropped_vintages']} for r in recs if r['n_cand'] == 0]
    notread = [{'vintage': r['vintage'], 'ticker': r['t'], 'cik': r['cik'], 'sic': r['sic'], 'name': r['name'], 'acc': r['acc'], 'f1': r['f1'],
                'float': r['float'], 'reason': ('budget_vintage_dropped' if r['vintage'] in blog['dropped_vintages'] else 'budget_sampled_out')}
               for r in recs if r['n_cand'] > 0 and (r['vintage'] in blog['dropped_vintages'] or (r['vintage'], r['cik'], r['t']) in sampled_out)]
    json.dump({'_warning': '読み手はこのファイルを開かない（id → 会社の鍵）', 'seed': SEED, 'units': key, 'auto_no85': auto, 'not_read_budget': notread,
               'budget': blog}, open(KEYF, 'w'), ensure_ascii=False, indent=0)
    os.makedirs(BATCH, exist_ok=True)
    for f in os.listdir(BATCH):
        os.remove(os.path.join(BATCH, f))
    nb = max(1, round(len(units) / 60))
    size = -(-len(units) // nb)
    for b in range(nb):
        chunk = units[b * size:(b + 1) * size]
        if chunk:
            json.dump(chunk, open(os.path.join(BATCH, f'batch_{b + 1:02d}.json'), 'w'), ensure_ascii=False, indent=1)
    print('読む単位', len(units), '束', nb, '自動 no85', len(auto), '予算で読まない', len(notread), dict(mstat), blog)
    return blog


# ───────────────────────── 読み手への指示書（門の規約を逐語で写す） ─────────────────────────
def gate_rubric_texts():
    """index.html と out/irr_regrade/RUBRIC.md から規約を逐語で抜く（写さずに読む＝規約が変われば指示書も変わる）"""
    s = open(os.path.join(BASE, 'index.html'), encoding='utf-8').read()
    opts = {}
    for k in ('irr', 'rep', 'dur'):
        m = re.search(r'<select id="' + k + r'">(.*?)</select>', s, re.S)
        opts[k] = [html.unescape(re.sub(r'<[^>]+>', '', o)).strip() for o in re.findall(r'<option[^>]*>(.*?)</option>', m.group(1), re.S)]
        lab = re.search(r'<div class="rl">([^<]*)<span class="h">([^<]*)</span></div><div class="rc"><select id="' + k + '"', s)
        opts[k + '_label'] = (lab.group(1) + '（' + lab.group(2) + '）') if lab else k
    i = s.index('function ccfAskText(t){return `')
    body = s[i:s.index('`;}', i)]
    seg = body[body.index('   irr 代替不能性:'):body.index('   moatW 堀の広さ')].replace('\\n', '\n')
    rub = open(os.path.join(BASE, 'out', 'irr_regrade', 'RUBRIC.md'), encoding='utf-8').read()
    return opts, seg, rub


def cmd_instructions():
    opts, seg, rub = gate_rubric_texts()
    L = []
    L.append('# 伏せた段落の読解の指示書（角度 moat_text_pre2007・門の irr / rep / dur）\n')
    L.append('事前登録: `out/mw_moat_text_pre2007_prereg.json`（この指示書の規約は門の本文を逐語で写したもの。刻みを変えてはいけない）\n')
    L.append('## あなたの仕事\n')
    L.append('- 渡された束 `out/_mw_cache/moat_text/batches/batch_XX.json` の各単位（`id`・`vintage_year`・`passages`）を読み、門の **irr（代替不能性）**・**rep（複製障壁）**・**dur（堀の型）** の刻みを付ける。')
    L.append('- `passages` は、`vintage_year` 年7月より前の15か月に提出された**米国上場企業の 10-K（年次報告書）の Item 1（事業）/ Item 1A（リスク要因）/ Item 7（経営者による分析）**から、'
             '認定・認証・承認などの語を含む段落を**機械で**抜いたもの（1社につき最大8段落・約1,800語。長い段落は途中を `…` で切ってある）。')
    L.append('- 会社名・旧社名・子会社名・銘柄コードは `[COMPANY]`、固有の製品名・ブランド名・相手先の名は `[PRODUCT_n]` に置き換えてある（番号は単位ごと）。業種の語は残してある。')
    L.append('- `vintage_year` は時代の文脈のために渡している。**その年の7月の時点で、段落に書いてあることだけ**から読む。')
    L.append('- 段落は語の網で機械的に選んだので、**irr の機構が一つも書かれていない単位も多い**。何も支えていなければ irr は `null`（または一般的な競争の記述だけなら 50）。\n')
    L.append('## 絶対に守ること\n')
    L.append('- **読んでよいのは、渡された束のファイルとこの指示書だけ**。Web を検索しない。リポジトリの他のファイル（`out/` の JSON・株価・リターン・台帳・`CLAUDE.md`・`index.html`・`docs/` など）を開かない。'
             '**`out/_mw_cache/moat_text/KEY_do_not_open.json`（id → 会社の鍵）と `units_private.jsonl.gz`（伏せる前の本文）は絶対に開かない。**')
    L.append('- **会社を推測して、その会社について知っていることで採点しない。** その年より後に起きたこと（株価・成長・買収・倒産など）を使わない。段落に書いてあることだけで裁く。')
    L.append('- 会社が分かったと思っても**社名を出力に書かない**。分かったと思うかどうかだけを `recognised` に true/false で書く（判定には使わない。漏れの検査に使う）。')
    L.append('- **迷ったら下の刻みへ倒す**（85 は特権を伴うので、顧客が再認定の費用と時間を負うという**断定の引用**が無ければ 70 以下）。')
    L.append('- 引用は段落の文を**一字一句そのまま**。途中を省くときは必ず `…` を置く。`[COMPANY]` `[PRODUCT_n]` はそのまま写してよい。\n')
    L.append('## 門の規約（逐語の写し）\n')
    L.append('### 1. 門の採点機の選択肢（index.html の `<select id="irr">` / `"rep"` / `"dur"` をそのまま）\n')
    for k in ('irr', 'rep', 'dur'):
        L.append(f'**{opts[k + "_label"]}**\n')
        for o in opts[k]:
            L.append(f'- {o}')
        L.append('')
    L.append('### 2. 門2審査プロトコルの irr・rep・dur の節（index.html の審査プロトコル全文〔ccfAskText〕から逐語）\n')
    L.append('（`_meta` や「台帳」「堀指数」「二重読み」の記録の話は門の運用の文脈。この作業では刻みの定義と、85 の検問①〜⑥・70 の要件をそのまま使う。①の機械照合は後で私たちが行う）\n')
    L.append('```text')
    L.append(seg.rstrip())
    L.append('```\n')
    L.append('### 3. 再採点の規約（out/irr_regrade/RUBRIC.md を逐語で）\n')
    L.append('（この節の「出す欄」は別の作業の形式。今回の出力は下の「出力」に従う。「禁じること」はそのまま守る）\n')
    L.append('```markdown')
    L.append(rub.rstrip())
    L.append('```\n')
    L.append('## この作業での補足（規約を変えない範囲の注記）\n')
    L.append('- **irr=85**: 段落が「**顧客の側が**（自社の工程・製品・機体・装置で）当社の部品・材料・仕様を認定・認証・承認しており、乗り換えるには顧客が再認定・再試験・再承認を**やり直す**（費用と時間を負う）」と**断定**しているときだけ。'
             '典型は FAA/OEM の承認を受けた航空部品・FDA の承認の中に組み込まれた医療機器の部材・ファブの工程に認定された半導体の材料と装置・国防総省の仕様で単独調達される部品。')
    L.append('- **向きが逆の例（85 にしない）**: 当社自身が取る FAA/FDA/ISO の認証・承認／当社が自分の仕入先を認定する話／当社が仕入先から sole source で買っているという供給リスク／'
             '当社が新しい顧客に認定してもらうのに時間がかかる（当社が外側にいる）／当社が認定を失うと当社の売上が減る。')
    L.append('- **irr=100**: 当社が顧客にとって**唯一の供給者で代替が無い**と段落が断定しているとき（例: 政府の唯一の供給者）。自社が買う側の sole source は当たらない。')
    L.append('- **irr=70**: 顧客側の再認定までは言っていないが、摩擦の機構を名指しして引用できるとき（上の RUBRIC の 70 の一覧）。引用できなければ 50。')
    L.append('- **null**: 段落が irr のどの刻みについても手がかりを与えないとき（例: 段落が当社の従業員の資格・会計・税務・自社の許認可の話だけ）。')
    L.append('- **rep**（複製障壁＝時間×資本で追随できるか）と **dur**（堀の型）も同じ段落から、上の門の刻みのとおり付ける。段落に手がかりが無ければ `null`。規約に無い中間値（90・75 の rep など）は作らない。')
    L.append('- **confidence**: irr の判定についての自信。1＝弱い / 2＝中 / 3＝強い。\n')
    L.append('## 出力\n')
    L.append('- 束1つにつき1ファイル: `out/_mw_cache/moat_text/reads/batch_XX_{読み手の記号}.json`（読み手の記号は呼び出し側が指定する A / B / C）。')
    L.append('- JSON の配列。**束の全 id を1つずつ**入れる（読めなかった単位も irr を null にして入れる）:')
    L.append('```json')
    L.append('[{"id": "u0001", "irr": 85, "irr_reason": "一文（日本語・段落の語を挙げる）", "irr_quote": "段落からの逐語の引用（85/100 なら必須。無ければ null）",'
             ' "rep": 60, "dur": 75, "recognised": false, "confidence": 2}]')
    L.append('```')
    L.append('- `irr` ∈ {100, 85, 70, 50, null}、`rep` ∈ {100, 80, 60, 35, null}、`dur` ∈ {100, 85, 75, 55, null}、`recognised` ∈ {true, false}、`confidence` ∈ {1, 2, 3}。')
    L.append('- `irr_quote` は 85/100 のときは必須（付けられないなら 85/100 にしない）。70/50 では任意（付けるなら逐語）。null のときは null。')
    L.append('- 書き終えたら件数だけ報告する。\n')
    open(INSTR, 'w', encoding='utf-8').write('\n'.join(L))
    print('書いた', INSTR, len('\n'.join(L)), '字')


# ───────────────────────── 手で調べた対応（理由つき・株価を見る前・窓の 10-K 提出者名で確かめた） ─────────────────────────
# 形: 'ビンテージ|記号': (CIK or None, 理由)。機械の対応が誤っている／付かないものだけを置く。
MANUAL_MAP = {
    # 1997: 機械が小型株を拾った（本文に他社の記号が書いてあった）ものの訂正
    '1997|AIT': ('732715', 'Ameritech（1997 の AIT）。機械は Bearings Inc（後に AIT を名乗った小型株）を拾った'),
    '1997|AN': ('350698', 'Republic Industries（後の AutoNation）。機械は Bankers Trust を拾った'),
    '1997|BT': ('9749', 'Bankers Trust New York'),
    '1997|AT': ('65873', 'ALLTEL'),
    '1997|BEAM': ('789073', 'American Brands（→Fortune Brands→Beam）'),
    '1997|BFI': ('14827', 'Browning-Ferris Industries'),
    '1997|CBS': ('106413', 'Westinghouse Electric（→CBS）'),
    '1997|CCI': ('20405', 'Citicorp（1997 の CCI）'),
    '1997|COP': ('78214', 'Phillips Petroleum（→ConocoPhillips）'),
    '1997|COST': ('909832', 'Price/Costco'),
    '1997|F': ('37996', 'Ford Motor'),
    '1997|HI': ('354964', 'Household International'),
    '1997|HRS': ('202058', 'Harris Corp'),
    '1997|JCP': ('77182', 'J C Penney Co Inc（機械は資金調達子会社を拾った）'),
    '1997|L': ('60086', 'Loews'),
    '1997|MAY': ('63416', 'May Department Stores'),
    '1997|MCO': ('30419', 'Dun & Bradstreet（1997 の法人。Moody\'s の前身）'),
    '1997|MSI': ('68505', 'Motorola'),
    '1997|PAS': ('49573', 'Whitman Corp（→PepsiAmericas）'),
    '1997|PH': ('76334', 'Parker Hannifin'),
    '1997|PNU': ('949573', 'Pharmacia & Upjohn'),
    '1997|PTC': ('857005', 'Parametric Technology'),
    '1997|RYI': ('790528', 'Inland Steel Industries（→Ryerson Tull）'),
    '1997|TRW': ('100030', 'TRW Inc'),
    '1997|TRV': ('86312', 'St. Paul Companies（→Travelers）。Travelers Group は C として別にいる'),
    '1997|TAP': ('24545', 'Adolph Coors（→Molson Coors）。Travelers Property Casualty は当時 TAP だが S&P500 の外'),
    '1997|ABI': ('77551', 'Perkin-Elmer（→PE Corp→Applera）'),
    '1997|AMH': ('4427', 'Amdahl'),
    '1997|UN': (None, 'Unilever N.V.（外国の提出者・10-K なし）'),
    '1997|ETS': (None, '当時の会社が特定できない（機械は ETS International を拾った）'),
    # 1997: 機械で付かなかった／曖昧だったもの
    '1997|AAMRQ': ('6201', 'AMR Corp'),
    '1997|ACKH': ('7431', 'Armstrong World Industries'),
    '1997|AEE': ('100826', 'Union Electric（→Ameren・1997-12）'),
    '1997|AEP': ('4904', 'American Electric Power（合同の 10-K の親会社）'),
    '1997|AGC': ('5103', 'American General'),
    '1997|AHM': ('771667', 'H.F. Ahmanson'),
    '1997|AL': ('4285', 'Alcan Aluminium（10-K を出していた）'),
    '1997|AM': ('5133', 'American Greetings'),
    '1997|ARC': ('775483', 'Atlantic Richfield'),
    '1997|AS': ('7383', 'Armco'),
    '1997|BAY': ('876516', 'Bay Networks'),
    '1997|BDK': ('12355', 'Black & Decker'),
    '1997|BHMSQ': ('11860', 'Bethlehem Steel'),
    '1997|BKB': ('36672', 'Bank of Boston（→BankBoston）'),
    '1997|BNL': ('8960', 'Beneficial Corp'),
    '1997|BR': ('833320', 'Burlington Resources'),
    '1997|C': ('831001', 'Travelers Group（→Citigroup）'),
    '1997|CAT': ('18230', 'Caterpillar'),
    '1997|CCK': ('25890', 'Crown Cork & Seal'),
    '1997|CCTYQ': ('104599', 'Circuit City Stores'),
    '1997|CGP': ('21267', 'Coastal Corp'),
    '1997|CHA': ('19150', 'Champion International'),
    '1997|CIN': ('899652', 'Cinergy'),
    '1997|CNG': ('23738', 'Consolidated Natural Gas'),
    '1997|CSE': ('922321', 'Case Corp'),
    '1997|CSR': ('18540', 'Central & South West'),
    '1997|CTX': ('18532', 'Centex'),
    '1997|D': ('715957', 'Dominion Resources'),
    '1997|DE': ('315189', 'Deere'),
    '1997|DTE': ('936340', 'DTE Energy'),
    '1997|DUK': ('30371', 'Duke Power（→Duke Energy・1997-06）'),
    '1997|EC': ('352947', 'Engelhard'),
    '1997|ECH': ('31348', 'Echlin'),
    '1997|ECO': ('722080', 'Echo Bay Mines（10-K405 を出していた）'),
    '1997|EKDKQ': ('31235', 'Eastman Kodak'),
    '1997|EMC': ('790070', 'EMC Corp'),
    '1997|ENRNQ': ('72859', 'Enron Corp'),
    '1997|ENS': ('33015', 'Enserch'),
    '1997|ETN': ('31277', 'Eaton'),
    '1997|ETR': ('65984', 'Entergy（合同の 10-K の親会社）'),
    '1997|EXC': ('78100', 'PECO Energy（→Exelon。同じ名簿に Unicom は UCM として別にいる）'),
    '1997|FCN': ('70040', 'First Chicago NBD'),
    '1997|FE': ('73960', 'Ohio Edison（→FirstEnergy・1997-11）'),
    '1997|FG': ('354396', 'USF&G'),
    '1997|FJ': ('53117', 'James River Corp of Virginia（→Fort James）'),
    '1997|FLMIQ': ('352949', 'Fleming Companies'),
    '1997|FLTWQ': ('314132', 'Fleetwood Enterprises'),
    '1997|FMCC': (None, 'Freddie Mac（当時は SEC に 10-K を出していない）'),
    '1997|FNMA': (None, 'Fannie Mae（当時は SEC に 10-K を出していない）'),
    '1997|FTL.A': ('771298', 'Fruit of the Loom'),
    '1997|GFS.A': ('41289', 'Giant Food'),
    '1997|GPU': ('40779', 'General Public Utilities'),
    '1997|GR': ('42542', 'B.F. Goodrich'),
    '1997|GWF': ('43512', 'Great Western Financial'),
    '1997|H': ('40493', 'Harcourt General'),
    '1997|HAS': ('46080', 'Hasbro'),
    '1997|INCLF': (None, 'Inco（窓に 10-K なし・外国の提出者）'),
    '1997|LDW.B': (None, 'Laidlaw（窓に 10-K なし・外国の提出者）'),
    '1997|LLX': ('60512', 'Louisiana Land & Exploration'),
    '1997|MCIC': ('64079', 'MCI Communications'),
    '1997|MKG': ('51396', 'Mallinckrodt Group'),
    '1997|MTLQQ': ('40730', 'General Motors'),
    '1997|MWV': ('106498', 'Westvaco（→MeadWestvaco）'),
    '1997|NEE': ('753308', 'FPL Group'),
    '1997|NRTLQ': (None, 'Northern Telecom（窓に 10-K なし・外国の提出者）'),
    '1997|NSI': ('70538', 'National Service Industries'),
    '1997|PCG': ('1004980', 'PG&E Corp'),
    '1997|PCH': ('79716', 'Potlatch'),
    '1997|PD': ('78066', 'Phelps Dodge'),
    '1997|PDG': (None, 'Placer Dome（窓に 10-K なし・外国の提出者）'),
    '1997|PEG': ('788784', 'Public Service Enterprise Group'),
    '1997|PGN': ('17797', 'Carolina Power & Light（→Progress Energy）'),
    '1997|PHB': ('78716', 'Pioneer Hi-Bred'),
    '1997|PRD': ('79326', 'Polaroid'),
    '1997|PZE': ('77320', 'Pennzoil'),
    '1997|RAL': ('81870', 'Ralston Purina'),
    '1997|RDS.A': (None, 'Royal Dutch Petroleum（20-F）'),
    '1997|RLM': ('83604', 'Reynolds Metals'),
    '1997|RSHCQ': ('96289', 'Tandy Corp（→RadioShack）'),
    '1997|RX': ('1019876', 'Cognizant Corp（→IMS Health）'),
    '1997|RYC': ('82206', 'Raychem'),
    '1997|S': ('319256', 'Sears Roebuck'),
    '1997|SGID': ('802301', 'Silicon Graphics'),
    '1997|SMI': ('93102', 'Springs Industries'),
    '1997|SMS': ('89415', 'Shared Medical Systems'),
    '1997|SNT': ('92236', 'Sonat'),
    '1997|SO': ('92122', 'Southern Co（合同の 10-K の親会社）'),
    '1997|STO': ('94610', 'Stone Container'),
    '1997|TIN': ('731939', 'Temple-Inland'),
    '1997|TMK': ('320335', 'Torchmark'),
    '1997|TWX': ('1021387', 'Time Warner Inc'),
    '1997|TXU': ('97561', 'Texas Utilities'),
    '1997|UCC': ('100783', 'Union Camp'),
    '1997|UCL': ('716039', 'Unocal'),
    '1997|UCM': ('918040', 'Unicom'),
    '1997|WBA': ('104207', 'Walgreen'),
    '1997|WCOEQ': ('723527', 'WorldCom'),
    '1997|XOM': ('34088', 'Exxon'),
    '1997|X': (None, 'USX-U.S. Steel Group は USX Corp（MRO と同じ CIK 101778）の追跡株。一社一記号の規則で MRO に残す'),
    '1997|ABX': (None, 'Barrick Gold（外国の提出者・10-K なし）'),
    # 2000: 機械の誤りの訂正（1997 と同じ型: 他社の記号を本文に書いた小型株・子会社）と、付かなかったもの
    '2000|A': ('1090872', 'Agilent Technologies。機械は Motorola を拾った'),
    '2000|MSI': ('68505', 'Motorola'),
    '2000|ABI': ('77551', 'PE Corp（→Applera）'),
    '2000|AL': ('4285', 'Alcan Aluminium'),
    '2000|AT': ('65873', 'ALLTEL（T は SBC として別にいる）'),
    '2000|CBS': ('106413', 'CBS Corp'),
    '2000|COP': ('78214', 'Phillips Petroleum'),
    '2000|D': ('715957', 'Dominion Resources'),
    '2000|ED': ('1047862', 'Consolidated Edison Inc'),
    '2000|ETS': (None, '当時の会社が特定できない'),
    '2000|F': ('37996', 'Ford Motor'),
    '2000|HI': ('354964', 'Household International'),
    '2000|JCI': ('53669', 'Johnson Controls（機械は Tyco を拾った）'),
    '2000|JCP': ('77182', 'J C Penney Co Inc'),
    '2000|KM': ('56824', 'Kmart'),
    '2000|L': ('60086', 'Loews'),
    '2000|LB': ('701985', 'Limited Inc'),
    '2000|MAR': ('1048286', 'Marriott International'),
    '2000|MAY': ('63416', 'May Department Stores'),
    '2000|ONE': ('1067092', 'Bank One'),
    '2000|PGL': ('77385', 'Peoples Energy（機械は子会社 North Shore Gas を拾った）'),
    '2000|PGN': ('17797', 'Carolina Power & Light'),
    '2000|PH': ('76334', 'Parker Hannifin'),
    '2000|PTC': ('857005', 'Parametric Technology'),
    '2000|R': ('85961', 'Ryder System'),
    '2000|S': ('319256', 'Sears Roebuck'),
    '2000|SMI': ('93102', 'Springs Industries'),
    '2000|TAP': ('24545', 'Adolph Coors'),
    '2000|TRV': ('86312', 'St. Paul Companies（→St. Paul Travelers→Travelers）'),
    '2000|TRW': ('100030', 'TRW Inc'),
    '2000|TWX': ('1021387', 'Time Warner Inc'),
    '2000|UCM': ('918040', 'Unicom（合同の 10-K の親会社）'),
    '2000|UN': (None, 'Unilever N.V.（外国の提出者）'),
    '2000|USW': ('1054522', 'U S West Inc（1998 の分割後の通信会社。MediaOne Group は旧法人）'),
    '2000|XEL': ('72903', 'Northern States Power（→Xcel・2000-08）'),
    '2000|NGH': ('847903', 'Nabisco Group Holdings'),
    '2000|PCS': (None, 'Sprint PCS の追跡株（Sprint の 10-K と同じ本文・一社一記号の規則で持たない）。機械は Potash を拾った'),
    '2000|UPC': ('100893', 'Union Planters'),
    '2000|NCE': ('1004858', 'New Century Energies'),
    '2000|FPC': ('357261', 'Florida Progress'),
    '2000|TOS': ('74091', 'Tosco'),
    '2000|LEHMQ': ('806085', 'Lehman Brothers Holdings'),
    '2000|DPHIQ': ('1072342', 'Delphi Automotive Systems'),
    '2000|VSTNQ': (None, 'Visteon（最初の 10-K は 2001年＝窓に無い）'),
    '2000|AABA': ('1011006', 'Yahoo'),
    '2000|ACKH': ('7431', 'Armstrong World Industries'),
    '2000|AGC': ('5103', 'American General'),
    '2000|BDK': ('12355', 'Black & Decker'),
    '2000|BHMSQ': ('11860', 'Bethlehem Steel'),
    '2000|CCK': ('25890', 'Crown Cork & Seal'),
    '2000|CCTYQ': ('104599', 'Circuit City Stores'),
    '2000|CGP': ('21267', 'Coastal Corp'),
    '2000|CIN': ('899652', 'Cinergy'),
    '2000|CNP': ('48732', 'Reliant Energy（→CenterPoint）'),
    '2000|DE': ('315189', 'Deere'),
    '2000|EC': ('352947', 'Engelhard'),
    '2000|EKDKQ': ('31235', 'Eastman Kodak'),
    '2000|ENRNQ': ('1024401', 'Enron Corp'),
    '2000|EXC': ('78100', 'PECO Energy（→Exelon・2000-10。Unicom は UCM）'),
    '2000|FJ': ('53117', 'Fort James'),
    '2000|GPU': ('40779', 'GPU Inc'),
    '2000|H': ('40493', 'Harcourt General'),
    '2000|HAS': ('46080', 'Hasbro'),
    '2000|MKG': ('51396', 'Mallinckrodt'),
    '2000|MTLQQ': ('40730', 'General Motors'),
    '2000|MWV': ('106498', 'Westvaco'),
    '2000|PCH': ('79716', 'Potlatch'),
    '2000|PD': ('78066', 'Phelps Dodge'),
    '2000|PRD': ('79326', 'Polaroid'),
    '2000|RAL': ('81870', 'Ralston Purina'),
    '2000|RSHCQ': ('96289', 'Tandy Corp（→RadioShack）'),
    '2000|TIN': ('731939', 'Temple-Inland'),
    '2000|TMK': ('320335', 'Torchmark'),
    '2000|UCL': ('716039', 'Unocal'),
    '2000|WBA': ('104207', 'Walgreen'),
    '2000|WCOEQ': ('723527', 'MCI WorldCom'),
    '2000|XOM': ('34088', 'Exxon Mobil'),
    '2000|FMCC': (None, 'Freddie Mac（10-K なし）'),
    '2000|FNMA': (None, 'Fannie Mae（10-K なし）'),
    '2000|RDS.A': (None, 'Royal Dutch（20-F）'),
    '2000|ABX': (None, 'Barrick（外国）'),
    '2000|INCLF': (None, 'Inco（外国）'),
    '2000|NRTLQ': (None, 'Nortel（外国）'),
    '2000|PDG': (None, 'Placer Dome（外国）'),
    '2000|WAMUQ': (None, 'WM と同じ Washington Mutual（名簿の文字列の重複）'),
    '2000|X': (None, 'USX-U.S. Steel Group は USX Corp（MRO）の追跡株'),
    # 2003
    '2003|MDR': ('708819', 'McDermott International（子会社の破産で時価が小さかったが S&P500 の構成社。機械の使い回しの検問が棄てた）'),
    '2003|AN': ('350698', 'AutoNation。機械は Metrologic を拾った'),
    '2003|BEAM': ('789073', 'Fortune Brands'),
    '2003|CAT': ('18230', 'Caterpillar。機械は Catuity を拾った'),
    '2003|ED': ('1047862', 'Consolidated Edison Inc'),
    '2003|F': ('37996', 'Ford Motor'),
    '2003|HON': ('773840', 'Honeywell International。機械は Turbodyne を拾った'),
    '2003|IBM': ('51143', 'IBM。機械は Mobility Electronics を拾った'),
    '2003|LB': ('701985', 'Limited Brands'),
    '2003|MAR': ('1048286', 'Marriott International'),
    '2003|MAY': ('63416', 'May Department Stores'),
    '2003|MON': ('1110783', 'Monsanto Co（新・2000 分離）。機械は Pharmacia を拾った'),
    '2003|MSI': ('68505', 'Motorola'),
    '2003|ONE': ('1067092', 'Bank One'),
    '2003|PCG': ('1004980', 'PG&E Corp。機械は Valero を拾った'),
    '2003|PCS': (None, 'Sprint PCS の追跡株'),
    '2003|PGL': ('77385', 'Peoples Energy'),
    '2003|PTC': ('857005', 'Parametric Technology'),
    '2003|S': ('319256', 'Sears Roebuck'),
    '2003|SNV': ('18349', 'Synovus（機械は子会社 TSYS を拾った）'),
    '2003|TE': ('350563', 'TECO Energy（機械は資金調達の信託を拾った）'),
    '2003|TEK': ('96879', 'Tektronix'),
    '2003|TRV': ('86312', 'St. Paul Companies'),
    '2003|TT': ('836102', 'American Standard（→Trane）'),
    '2003|AYE': ('3673', 'Allegheny Energy'),
    '2003|ALL': ('899051', 'Allstate'),
    '2003|CBS': ('813828', 'Viacom（旧 Viacom→CBS Corp）'),
    '2003|CMI': (None, 'Cummins（2002 年度の 10-K は訂正で遅れ、窓に無い）'),
    '2003|CPNLQ': ('916457', 'Calpine'),
    '2003|D': ('715957', 'Dominion Resources'),
    '2003|DUK': ('30371', 'Duke Energy'),
    '2003|ETN': ('31277', 'Eaton'),
    '2003|HAS': ('46080', 'Hasbro'),
    '2003|KMI': ('54502', 'Kinder Morgan Inc'),
    '2003|L': ('60086', 'Loews'),
    '2003|LSI': ('703360', 'LSI Logic'),
    '2003|MRO': ('101778', 'Marathon Oil'),
    '2003|MTLQQ': ('40730', 'General Motors'),
    '2003|PGN': ('1094093', 'Progress Energy'),
    '2003|R': ('85961', 'Ryder System'),
    '2003|RAI': ('83612', 'RJ Reynolds Tobacco Holdings（→Reynolds American）'),
    '2003|SBL': (None, 'Symbol Technologies（訂正で 10-K が遅れ、窓に無い）'),
    '2003|TWX': ('1105705', 'AOL Time Warner'),
    '2003|TIN': ('731939', 'Temple-Inland'),
    '2003|TMK': ('320335', 'Torchmark'),
    '2003|UCL': ('716039', 'Unocal'),
    '2003|WBA': ('104207', 'Walgreen'),
    '2003|XOM': ('34088', 'Exxon Mobil'),
    '2003|PD': ('78066', 'Phelps Dodge'),
    '2003|RSHCQ': ('96289', 'RadioShack'),
    '2003|LEHMQ': ('806085', 'Lehman Brothers Holdings'),
    '2003|EKDKQ': ('31235', 'Eastman Kodak'),
    '2003|DPHIQ': ('1072342', 'Delphi Corp'),
    '2003|CIN': ('899652', 'Cinergy'),
    '2003|CCTYQ': ('104599', 'Circuit City Stores'),
    '2003|BDK': ('12355', 'Black & Decker'),
    '2003|AABA': ('1011006', 'Yahoo'),
    '2003|WAMUQ': (None, 'WM と同じ Washington Mutual（名簿の文字列の重複）'),
    '2003|FMCC': (None, 'Freddie Mac（10-K なし）'),
    # 2006
    '2006|AMP': ('820027', 'Ameriprise Financial。機械は American Express を拾った'),
    '2006|AXP': ('4962', 'American Express'),
    '2006|AN': ('350698', 'AutoNation。機械は Motorola を拾った'),
    '2006|D': ('715957', 'Dominion Resources'),
    '2006|ED': ('1047862', 'Consolidated Edison Inc'),
    '2006|EQ': (None, 'Embarq（2006-05 分離・最初の 10-K は窓の後）'),
    '2006|F': ('37996', 'Ford Motor'),
    '2006|FOXA': ('1308161', 'News Corp'),
    '2006|JCI': ('53669', 'Johnson Controls'),
    '2006|L': ('60086', 'Loews'),
    '2006|MSI': ('68505', 'Motorola'),
    '2006|PGL': ('77385', 'Peoples Energy'),
    '2006|S': ('101830', 'Sprint Nextel（2006 の S）'),
    '2006|T': ('732717', 'AT&T Inc'),
    '2006|TEK': ('96879', 'Tektronix'),
    '2006|TPR': ('1116132', 'Coach（→Tapestry）'),
    '2006|TWX': ('1105705', 'Time Warner Inc'),
    '2006|LLL': ('1056239', 'L-3 Communications Holdings'),
    '2006|A': ('1090872', 'Agilent Technologies'),
    '2006|AYE': ('3673', 'Allegheny Energy'),
    '2006|ETN': ('31277', 'Eaton'),
    '2006|KMI': ('54502', 'Kinder Morgan Inc'),
    '2006|MRO': ('101778', 'Marathon Oil'),
    '2006|MTLQQ': ('40730', 'General Motors'),
    '2006|TE': ('350563', 'TECO Energy'),
    '2006|AABA': ('1011006', 'Yahoo'),
    '2006|BDK': ('12355', 'Black & Decker'),
    '2006|BOL': (None, 'Bausch & Lomb（訂正で 10-K が遅れ、窓に無い）'),
    '2006|CCTYQ': ('104599', 'Circuit City Stores'),
    '2006|EKDKQ': ('31235', 'Eastman Kodak'),
    '2006|FMCC': (None, 'Freddie Mac（窓に 10-K なし）'),
    '2006|FNMA': (None, 'Fannie Mae（訂正で 10-K が遅れ、窓に無い）'),
    '2006|LEHMQ': ('806085', 'Lehman Brothers Holdings'),
    '2006|NAV': (None, 'Navistar（訂正で 10-K が遅れ、窓に無い）'),
    '2006|PD': ('78066', 'Phelps Dodge'),
    '2006|RSHCQ': ('96289', 'RadioShack'),
    '2006|TIN': ('731939', 'Temple-Inland'),
    '2006|TMK': ('320335', 'Torchmark'),
    '2006|WBA': ('104207', 'Walgreen'),
    '2006|XOM': ('34088', 'Exxon Mobil'),
    '2006|WAMUQ': (None, 'WM と同じ Washington Mutual（名簿の文字列の重複）'),
    # 2009
    '2009|A': ('1090872', 'Agilent Technologies。機械は Motorola を拾った'),
    '2009|ALL': ('899051', 'Allstate。機械は Advanced ID を拾った'),
    '2009|CEG': ('1004440', 'Constellation Energy Group（機械は Exelon Generation を拾った）'),
    '2009|ES': ('72741', 'Northeast Utilities（→Eversource）。機械は EnergySolutions を拾った'),
    '2009|EXPE': ('1324424', 'Expedia'),
    '2009|FOXA': ('1308161', 'News Corp'),
    '2009|FRX': ('38074', 'Forest Laboratories'),
    '2009|IBM': ('51143', 'IBM。機械は iGo を拾った'),
    '2009|SHLD': ('1310067', 'Sears Holdings'),
    '2009|TWX': ('1105705', 'Time Warner Inc'),
    '2009|WELL': ('766704', 'Health Care REIT（→Welltower）'),
    '2009|DYN': ('1379895', 'Dynegy Inc（機械は子会社 Dynegy Holdings を拾った）'),
    '2009|CBE': ('1141982', 'Cooper Industries'),
    '2009|ETN': ('31277', 'Eaton'),
    '2009|F': ('37996', 'Ford Motor'),
    '2009|HAS': ('46080', 'Hasbro'),
    '2009|LLL': ('1056239', 'L-3 Communications Holdings'),
    '2009|MRO': ('101778', 'Marathon Oil'),
    '2009|MSI': ('68505', 'Motorola'),
    '2009|SUNEQ': ('945436', 'MEMC Electronic Materials（→SunEdison）'),
    '2009|AABA': ('1011006', 'Yahoo'),
    '2009|BDK': ('12355', 'Black & Decker'),
    '2009|EKDKQ': ('31235', 'Eastman Kodak'),
    '2009|RSHCQ': ('96289', 'RadioShack'),
    '2009|TMK': ('320335', 'Torchmark'),
    '2009|WBA': ('104207', 'Walgreen'),
    '2009|XOM': ('34088', 'Exxon Mobil'),
    # 2012
    '2012|AN': ('350698', 'AutoNation。機械は Motorola Solutions を拾った'),
    '2012|ES': ('72741', 'Northeast Utilities'),
    '2012|FOXA': ('1308161', 'News Corp'),
    '2012|FRX': ('38074', 'Forest Laboratories'),
    '2012|NE': ('1458891', 'Noble Corp（スイス・上場している親会社）。機械は Western Massachusetts Electric を拾った'),
    '2012|S': ('101830', 'Sprint Nextel'),
    '2012|SHLD': ('1310067', 'Sears Holdings'),
    '2012|WELL': ('766704', 'Health Care REIT'),
    '2012|A': ('1090872', 'Agilent Technologies'),
    '2012|ETN': ('31277', 'Eaton'),
    '2012|F': ('37996', 'Ford Motor'),
    '2012|HAS': ('46080', 'Hasbro'),
    '2012|LLL': ('1056239', 'L-3 Communications Holdings'),
    '2012|MRO': ('101778', 'Marathon Oil'),
    '2012|MSI': ('68505', 'Motorola Solutions'),
    '2012|TWC': ('1377013', 'Time Warner Cable'),
    '2012|TWX': ('1105705', 'Time Warner Inc'),
    '2012|AABA': ('1011006', 'Yahoo'),
    '2012|ANRZQ': ('1301063', 'Alpha Natural Resources'),
    '2012|PSX': (None, 'Phillips 66（2012-05 分離・最初の 10-K は窓の後）'),
    '2012|TMK': ('320335', 'Torchmark'),
    '2012|WBA': ('104207', 'Walgreen'),
    '2012|XOM': ('34088', 'Exxon Mobil'),
}


MANUAL = os.path.join(MT, 'manual_map.json')


def load_manual():
    """手で調べた対応（理由つき）。MANUAL_MAP（このファイル＝コミットされる）＋ 任意の manual_map.json。v は '*' で全ビンテージ"""
    d = dict(MANUAL_MAP)
    if os.path.exists(MANUAL):
        d.update({k: tuple(x) for k, x in json.load(open(MANUAL)).items()})
    return {tuple(k.split('|')): tuple(x) for k, x in d.items()}


# ═════════════════════════ 第3段（読みの後）: ラベル・株価・判定 ═════════════════════════
# 2026-09-28 第3段。読み手（A・B・割れた単位だけ C）が読み終えた後に、鍵（KEY_do_not_open.json）を初めて開いてラベルを付け、
# 株価を初めて取得してリターン・判定を出す。規則は事前登録（out/mw_moat_text_pre2007_prereg.json・905a0d2＋追記 21fa7a5）のまま。
# 事前登録に無い扱いは『事後』と印を付け、判定には使わない。
READS = os.path.join(MT, 'reads')
LABELS = os.path.join(MT, 'labels.json')            # gitignore（鍵を含む）
YH404 = os.path.join(MT, 'yh404')
RESULT = 'mw_moat_text_pre2007.json'
FIRST_M, END_M, TRAIN_Z, HOLD_A, RECENT_A = 199707, 202608, 200612, 200701, 201307
SPIKE = 3.0
F2_VINTAGES = [1997, 2000, 2003, 2006, 2009]        # 2012 は予算で読まなかった（事前登録の予算の段の1）
F1_VINTAGES = VINTAGES                              # F1 は全ビンテージ（予算は効かない）
AERO = lambda s: s is not None and (3720 <= s <= 3729 or 3760 <= s <= 3769 or s == 3812)
SEMI_SIC = {3674, 3559}


def ge85(v):
    return v is not None and v >= 85


def load_reads():
    R = {'A': {}, 'B': {}, 'C': {}}
    for f in sorted(os.listdir(READS)):
        m = re.match(r'batch_(\d+)_([ABC])\.json$', f)
        if m:
            for x in json.load(open(os.path.join(READS, f))):
                R[m.group(2)][x['id']] = x
    return R


def kappa(pairs):
    """Cohen の κ（重みなし）。null も一つの刻みとして数える → (κ, 一致率, n)"""
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / n / n
    return (round((po - pe) / (1 - pe), 3) if pe < 1 else None), round(po, 3), n


def lower(a, b):
    """2人の低い方（null は最も低い＝手がかりなし）"""
    return None if a is None or b is None else min(a, b)


def final_scale(a, b, c, c_read):
    """刻みの最終値: 2人一致ならその値・割れて3人目が読んだら3人目・3人目が読んでいなければ2人の低い方"""
    if a == b:
        return a, 'agree'
    if c_read:
        return c, 'third'
    return lower(a, b), 'lower_of_two'


def cmd_labels():
    """最終ラベル（F2＝irr≥85 の多数決・rep/dur の上位・F1）を社×ビンテージの表にする → labels.json（gitignore）と要約"""
    K = json.load(open(KEYF))
    R = load_reads()
    rows, bad = [], []
    for uid, u in K['units'].items():
        a, b, c = R['A'].get(uid), R['B'].get(uid), R['C'].get(uid)
        if a is None or b is None:
            bad.append(uid); continue
        votes = [ge85(a['irr']), ge85(b['irr'])] + ([ge85(c['irr'])] if c else [])
        if votes[0] != votes[1] and c is None:
            bad.append(uid); continue
        lock = sum(votes) * 2 > len(votes)
        irr_v, irr_how = final_scale(a['irr'], b['irr'], c['irr'] if c else None, c is not None)
        rep_v, rep_how = final_scale(a.get('rep'), b.get('rep'), c.get('rep') if c else None, c is not None)
        dur_v, dur_how = final_scale(a.get('dur'), b.get('dur'), c.get('dur') if c else None, c is not None)
        rows.append({'id': uid, 'vintage': u['vintage'], 'ticker': u['ticker'], 'cik': u['cik'], 'name': u['name'], 'sic': u['sic'],
                     'sic_src': u['sic_src'], 'float': u['float'], 'f1': bool(u['f1']), 'src': 'read', 'via': u['via'],
                     'irr_A': a['irr'], 'irr_B': b['irr'], 'irr_C': c['irr'] if c else None, 'third_read': c is not None,
                     'lock': lock, 'irr_final': irr_v, 'irr_final_how': irr_how, 'ab_agree85': votes[0] == votes[1],
                     'rec_A': a.get('recognised'), 'rec_B': b.get('recognised'), 'rec_C': c.get('recognised') if c else None,
                     'rec_neither': a.get('recognised') is False and b.get('recognised') is False,
                     'rep_A': a.get('rep'), 'rep_B': b.get('rep'), 'rep_final': rep_v, 'rep_how': rep_how, 'rep_top': rep_v in (100, 80),
                     'dur_A': a.get('dur'), 'dur_B': b.get('dur'), 'dur_final': dur_v, 'dur_how': dur_how, 'dur_top': dur_v in (100, 85),
                     'quote': (a.get('irr_quote') if ge85(a['irr']) else None) or (b.get('irr_quote') if ge85(b['irr']) else None)})
    if bad:
        raise SystemExit(f'読みの欠け・3人目の欠け: {bad[:20]}')
    for x in K['auto_no85']:
        lab = bool(x.get('f2_labelled'))
        rows.append({'id': None, 'vintage': x['vintage'], 'ticker': x['ticker'], 'cik': x['cik'], 'name': x['name'], 'sic': x['sic'],
                     'sic_src': x['sic_src'], 'float': x['float'], 'f1': bool(x['f1']), 'src': 'auto_no85' if lab else 'auto_no85_unlabelled_2012',
                     'lock': False if lab else None, 'rep_top': False if lab else None, 'dur_top': False if lab else None,
                     'ab_agree85': None, 'rec_neither': None})
    for x in K['not_read_budget']:
        rows.append({'id': None, 'vintage': x['vintage'], 'ticker': x['ticker'], 'cik': x['cik'], 'name': x['name'], 'sic': x['sic'],
                     'sic_src': None, 'float': x['float'], 'f1': bool(x['f1']), 'src': x['reason'],
                     'lock': None, 'rep_top': None, 'dur_top': None, 'ab_agree85': None, 'rec_neither': None})
    # 要約
    rd = [r for r in rows if r['src'] == 'read']
    ir = [(R['A'][r['id']]['irr'], R['B'][r['id']]['irr']) for r in rd]
    summ = {'n_read_units': len(rd), 'n_third_reads': sum(r['third_read'] for r in rd),
            'kappa_irr_full_scale': dict(zip(('kappa', 'agree_rate', 'n'), kappa(ir))),
            'kappa_irr_ge85': dict(zip(('kappa', 'agree_rate', 'n'), kappa([(ge85(a), ge85(b)) for a, b in ir]))),
            'kappa_rep': dict(zip(('kappa', 'agree_rate', 'n'), kappa([(r['rep_A'], r['rep_B']) for r in rd]))),
            'kappa_dur': dict(zip(('kappa', 'agree_rate', 'n'), kappa([(r['dur_A'], r['dur_B']) for r in rd]))),
            'kappa_rep_top': dict(zip(('kappa', 'agree_rate', 'n'), kappa([(r['rep_A'] in (100, 80), r['rep_B'] in (100, 80)) for r in rd]))),
            'kappa_dur_top': dict(zip(('kappa', 'agree_rate', 'n'), kappa([(r['dur_A'] in (100, 85), r['dur_B'] in (100, 85)) for r in rd]))),
            'irr_dist': {w: {str(k): v for k, v in sorted(Counter(str(R[w][r['id']]['irr']) for r in rd if r['id'] in R[w]).items())} for w in 'ABC'},
            'irr_ge85_by_reader': {w: sum(1 for r in rd if r['id'] in R[w] and ge85(R[w][r['id']]['irr'])) for w in 'ABC'},
            'third_reader_all_split_units_to': dict(Counter(str(r['irr_C']) for r in rd if r['third_read'])),
            'recognised_rate': {w: round(sum(1 for r in rd if R[w][r['id']].get('recognised') is True) / len(rd), 3) for w in 'AB'},
            'recognised_by_neither_units': sum(1 for r in rd if r['rec_neither']),
            'by_vintage': {}}
    for v in VINTAGES:
        g = [r for r in rows if r['vintage'] == v]
        lab = [r for r in g if r['lock'] is not None]
        lk = [r for r in lab if r['lock']]
        summ['by_vintage'][str(v)] = {
            'text_ok_units': len(g), 'f2_labelled': len(lab), 'read': sum(1 for r in g if r['src'] == 'read'),
            'auto_no85': sum(1 for r in g if r['src'] == 'auto_no85'), 'unlabelled_budget_or_2012_auto': len(g) - len(lab),
            'lock': len(lk), 'lock_names': [f"{r['ticker']}（{r['name']}・irr A{r['irr_A']}/B{r['irr_B']}"
                                            + (f"/C{r['irr_C']}" if r['third_read'] else '') + '）' for r in lk],
            'lock_both_readers_agree': sum(1 for r in lk if r['ab_agree85']),
            'lock_recognised_by_neither': sum(1 for r in lk if r['rec_neither']),
            'split_units_third_read': sum(1 for r in g if r.get('third_read')),
            'rep_top': sum(1 for r in lab if r['rep_top']), 'dur_top': sum(1 for r in lab if r['dur_top']),
            'f1': sum(1 for r in g if r['f1']),
            'thin_lt10': (len(lk) < 10) if lab else None}
    json.dump({'_warning': '鍵を含む（gitignore）。読み手はもう読み終えた', 'rows': rows, 'summary': summ}, open(LABELS, 'w'), ensure_ascii=False, indent=0)
    print(json.dumps(summ, ensure_ascii=False, indent=1)[:6000])
    return rows, summ


# ───────────────────────── 株価の系列（CIK と同じ会社の系列だけ） ─────────────────────────
def cont_name(a, b):
    """同じ会社の続き（持株会社への組み替え・改名）か: 正規化した社名の先頭語が一致 or 一方が他方の前方一致で5字以上・一般語でない"""
    x, y = nname(a), nname(b)
    if not x or not y:
        return False
    w1, w2 = x[0], y[0]
    if w1 in NAME_GENERIC or w2 in NAME_GENERIC:
        return False
    if w1 == w2:
        return True
    return min(len(w1), len(w2)) >= 5 and (w1.startswith(w2) or w2.startswith(w1))


def sec_maps():
    d = json.load(open(os.path.join(CACHE, 'sec_company_tickers.json')))
    by_cik, holder = defaultdict(list), {}
    for k in sorted(d, key=int):          # 一覧の順（時価の大きい順・普通株が先）
        v = d[k]
        c, t = str(v['cik_str']), v['ticker'].upper()
        by_cik[c].append((t, v['title']))
        holder.setdefault(t, (c, v['title']))
    return by_cik, holder


def resolve_ticker(rec, by_cik, holder, filers_in_window):
    """事前登録の returns の (a)(b)(c) → (Yahoo の記号 or None, 経路)"""
    T, c = rec['ticker'].upper(), str(rec['cik'])
    if by_cik.get(c):                                             # (a)
        ts = [t for t, _ in by_cik[c]]
        tv = [x for x in tvariants(T) if x in ts]
        return (tv[0] if tv else ts[0]), 'a_cik_has_ticker_today'
    h = holder.get(T) or holder.get(T.replace('.', '-'))
    if h:                                                         # (b)
        hc, ht = h
        if hc in filers_in_window:
            return None, 'b_holder_is_other_filer_in_window'
        if cont_name(rec.get('name') or '', ht):
            return T, 'b_continuation'
        return None, 'b_other_company'
    return T, 'c_nobody_holds_T'                                  # (c)


def ysym(t):
    return t.replace('.', '-').replace('/', '-').upper()


def yh_prefetch(y):
    """Yahoo の生 JSON を mw_common.yahoo と同じ置き場・名前に置く（3日以内なら取り直さない）。404 は印を置いて None"""
    os.makedirs(YH404, exist_ok=True)
    if os.path.exists(os.path.join(YH404, y)):
        return None
    p = os.path.join(CACHE, f'yh_{y.replace("^", "IDX_").replace("=", "_")}_1mo.json')
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 3 * 86400 and os.path.getsize(p) > 0:
        return y
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(y)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    for i in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
            tmp = f'{p}.{os.getpid()}.{threading.get_ident()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, p)
            return y
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(os.path.join(YH404, y), 'w').write('404'); return None
            time.sleep(2 * (i + 1) + random.random())
        except Exception:  # noqa
            time.sleep(2 * (i + 1) + random.random())
    return None


_SER = {}


def series(y):
    """{'ret','first','type','spike'} or None。リターンは mw_common.yahoo そのもの（取引所の現地時刻で月を切る・抜けた月をまたがない・今月を落とす）"""
    if y in _SER:
        return _SER[y]
    out = None
    p = os.path.join(CACHE, f'yh_{y.replace("^", "IDX_").replace("=", "_")}_1mo.json')
    if os.path.exists(p) and not os.path.exists(os.path.join(YH404, y)):
        try:
            j = json.load(open(p))
            res = (j.get('chart') or {}).get('result')
        except Exception:  # noqa
            res = None
        if res:
            r = res[0]
            ts = r.get('timestamp') or []
            adj = ((r['indicators'].get('adjclose') or [{}])[0].get('adjclose')) or ((r['indicators'].get('quote') or [{}])[0].get('close')) or []
            off = (r.get('meta') or {}).get('gmtoffset') or 0
            pm = [datetime.datetime.utcfromtimestamp(t + off) for t, a in zip(ts, adj) if a is not None]
            if pm:
                ret = M.yahoo(y)
                spike = next((k for k in sorted(ret) if ret[k] > SPIKE), None)
                out = {'ret': ret, 'first': min(d.year * 100 + d.month for d in pm), 'type': (r.get('meta') or {}).get('instrumentType'),
                       'spike': spike, 'name': (r.get('meta') or {}).get('longName') or (r.get('meta') or {}).get('shortName')}
    _SER[y] = out
    return out


def status(s, m, formed):
    """('ok', r) / ('missing', None) / ('spike', None)。系列の最初の月が形成月より後・株式でない → 観測なし（mw_index_events.obs と同じ検問）"""
    if s is None or s['first'] > formed or (s['type'] or 'EQUITY') != 'EQUITY':
        return 'missing', None
    if s['spike'] and m >= s['spike']:
        return 'spike', None
    r = s['ret'].get(m)
    return ('ok', r) if r is not None else ('missing', None)


def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def mrange(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


def cmd_prices(rows=None):
    """記号の選び方（a/b/c）→ Yahoo を取る。結果は labels.json の行に yahoo・経路・系列の情報を足す"""
    L = json.load(open(LABELS))
    rows = L['rows']
    by_cik, holder = sec_maps()
    filers = {v: set(filings_in(*window(v))) for v in VINTAGES}
    for r in rows:
        y, via = resolve_ticker(r, by_cik, holder, filers[r['vintage']])
        r['yahoo'], r['yahoo_via'] = (ysym(y) if y else None), via
    todo = sorted({r['yahoo'] for r in rows if r['yahoo']})
    print('Yahoo の記号', len(todo), flush=True)
    import concurrent.futures as cf
    lock_ = threading.Lock(); nxt = [0.0]

    def one(y):
        with lock_:
            t = max(time.time(), nxt[0]); nxt[0] = t + 0.25     # 毎秒4件以下
        d = t - time.time()
        if d > 0:
            time.sleep(d)
        return y, yh_prefetch(y)
    got = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for i, (y, ok) in enumerate(ex.map(one, todo)):
            got[y] = ok
            if (i + 1) % 200 == 0:
                print(' ', i + 1, '/', len(todo), flush=True)
    for r in rows:
        s = series(r['yahoo']) if r['yahoo'] and got.get(r['yahoo']) else None
        f = r['vintage'] * 100 + 7
        r['y_first'] = s['first'] if s else None
        r['y_type'] = s['type'] if s else None
        r['y_spike'] = s['spike'] if s else None
        r['y_name'] = s['name'] if s else None
        r['obs_at_formation'] = bool(s) and status(s, f, f)[0] == 'ok'
    L['rows'] = rows
    json.dump(L, open(LABELS, 'w'), ensure_ascii=False, indent=0)
    c = Counter((r['vintage'], r['yahoo_via'], r['obs_at_formation']) for r in rows)
    for k in sorted(c):
        print(k, c[k])


# ───────────────────────── ポートフォリオ ─────────────────────────
def book(names, w, a, z, bound, st, mkt, weighting='vw'):
    """一つのビンテージの持ち物を a〜z の月で持つ。
    vw＝本文の 10-K の表紙の時価の比で買い、リターンで漂わせる（買って持つ）／ew＝毎月等分に戻す（観測できる社の平均）。
    S＝観測できない月が来たらその社を外す（最後の値で売り、残りへ時価の比で按分）／L＝'missing' はその月 −100% として外す。
    'spike'（月 +300% 超の後）は両方で最後の値で売る。持ち物が空の月は French Mkt で埋める（mw_index_events.calendar_ew と同じ）。
    返り値: ({月: r}, 期末の重み（空なら {'__MKT__': 1}）, 形成時に買った重み, 統計)"""
    ms = mrange(a, z)
    unobs = [k for k in names if st(k, a)[0] != 'ok']
    obs0 = [k for k in names if k not in set(unobs)]
    stt = {'n': len(names), 'obs_start': len(obs0), 'unobs_start': sorted(unobs), 'dropped_later': [], 'spike_later': [],
           'empty_months': 0, 'lost_L_start_weight': 0.0, 'ew_rebal_turnover': 0.0}
    out = {}
    if not names:
        for m in ms:
            if m in mkt:
                out[m] = mkt[m]; stt['empty_months'] += 1
        return out, {'__MKT__': 1.0}, {'__MKT__': 1.0}, stt
    if weighting == 'vw':
        tot = sum(w[k] for k in names)
        pos = {k: w[k] / tot for k in obs0}
        lost0 = sum(w[k] for k in unobs) / tot if bound == 'L' else 0.0
        stt['lost_L_start_weight'] = round(lost0, 4)
        if bound == 'S' and pos:
            s_ = sum(pos.values()); pos = {k: v / s_ for k, v in pos.items()}
        bought = dict(pos)
        if bound == 'L':
            bought.update({k: w[k] / tot for k in unobs})
        for i, m in enumerate(ms):
            v0 = sum(pos.values()) + (lost0 if i == 0 else 0.0)
            if v0 <= 0:
                if m in mkt:
                    out[m] = mkt[m]; stt['empty_months'] += 1
                continue
            vo = v1 = cash = 0.0
            for k in list(pos):
                s_, r = st(k, m)
                if s_ == 'ok':
                    vo += pos[k]; pos[k] *= 1 + r; v1 += pos[k]
                else:
                    (stt['spike_later'] if s_ == 'spike' else stt['dropped_later']).append((k, m))
                    if bound == 'S' or s_ == 'spike':
                        cash += pos[k]
                    del pos[k]
            if vo > 0:
                kf = 1 + cash / vo
                for kk in pos:
                    pos[kk] *= kf
                out[m] = v1 * kf / v0 - 1
            else:            # 残る社が無い: 売った分（S・spike）はこの月から市場に置く
                out[m] = cash * (1 + mkt.get(m, 0.0)) / v0 - 1
                stt['empty_months'] += 1
        s_ = sum(pos.values())
        endw = {k: v / s_ for k, v in pos.items()} if s_ > 0 else {'__MKT__': 1.0}
        return out, endw, (bought or {'__MKT__': 1.0}), stt
    # 等加重
    live = list(obs0)
    bought = {k: 1 / len(names if bound == 'L' else (obs0 or names)) for k in (names if bound == 'L' else obs0)} or {'__MKT__': 1.0}
    for i, m in enumerate(ms):
        rs, ok = [], []
        if i == 0 and bound == 'L':
            rs += [-1.0] * len(unobs)
        for k in list(live):
            s_, r = st(k, m)
            if s_ == 'ok':
                rs.append(r); ok.append(r)
            else:
                live.remove(k)
                (stt['spike_later'] if s_ == 'spike' else stt['dropped_later']).append((k, m))
                if s_ == 'missing' and bound == 'L':
                    rs.append(-1.0)
        if rs and (ok or bound == 'L'):
            p = sum(rs) / len(rs)
            out[m] = p
            if ok and p > -1:            # 事後の報告だけ: 毎月等分に戻す売買の量
                n_ = len(ok)
                stt['ew_rebal_turnover'] += 0.5 * sum(abs((1 + x) / n_ / (1 + sum(ok) / n_) - 1 / n_) for x in ok)
        elif m in mkt:
            out[m] = mkt[m]; stt['empty_months'] += 1
    endw = {k: 1 / len(live) for k in live} if live else {'__MKT__': 1.0}
    return out, endw, bought, stt


def weights_for(recs, med):
    """表紙の時価（5,000万〜1兆ドルの外は読み違い＝欠測）。欠測はそのビンテージの中央値"""
    w, nfill = {}, 0
    for r in recs:
        f = r.get('float')
        if f is None or not (5e7 <= f <= 1e12):
            f = med; nfill += 1
        w[r['cik']] = f
    return w, nfill


class Panel:
    def __init__(self, rows, mkt):
        self.rows, self.mkt = rows, mkt
        self.med = {}
        for v in VINTAGES:
            fs = sorted(r['float'] for r in rows if r['vintage'] == v and r.get('float') and 5e7 <= r['float'] <= 1e12)
            self.med[v] = fs[len(fs) // 2] if len(fs) % 2 else (fs[len(fs) // 2 - 1] + fs[len(fs) // 2]) / 2
        self.yt = {(r['vintage'], r['cik']): r.get('yahoo') for r in rows}

    def st_fn(self, v):
        formed = v * 100 + 7

        def st(k, m):
            y = self.yt.get((v, k))
            return status(series(y) if y else None, m, formed)
        return st

    def chain(self, pick, vintages, weighting='vw', bound='S', end=END_M, a_first=None):
        """pick(r) → bool。各ビンテージの7月に作り、次のビンテージの6月まで（最後のビンテージは end まで）持つ。
        返り値: 系列, 年あたり片道回転率（形成と作り替えだけ・事前登録の費用の規則）, ビンテージごとの統計"""
        out, turn, prev, det = {}, 0.0, None, {}
        for i, v in enumerate(vintages):
            a = v * 100 + 7
            z = vintages[i + 1] * 100 + 6 if i + 1 < len(vintages) else end
            recs = [r for r in self.rows if r['vintage'] == v and pick(r)]
            w, nfill = weights_for(recs, self.med[v])
            r_, endw, bought, stt = book([r['cik'] for r in recs], w, a, z, bound, self.st_fn(v), self.mkt, weighting)
            turn += 1.0 if prev is None else 0.5 * sum(abs(bought.get(k, 0.0) - prev.get(k, 0.0)) for k in set(bought) | set(prev))
            prev = endw
            out.update(r_)
            nm = {r['cik']: r['ticker'] for r in recs}
            det[str(v)] = {'n': stt['n'], 'obs_at_formation': stt['obs_start'], 'float_filled_median': nfill,
                           'unobserved_at_formation': [nm[k] for k in stt['unobs_start']][:40],
                           'dropped_later': [f'{nm[k]}@{m}' for k, m in stt['dropped_later']][:40],
                           'spike_later': [f'{nm[k]}@{m}' for k, m in stt['spike_later']],
                           'months_filled_with_mkt': stt['empty_months'], 'L_weight_lost_at_formation': stt['lost_L_start_weight'],
                           'ew_monthly_rebal_turnover_posthoc': round(stt['ew_rebal_turnover'], 2) if weighting == 'ew' else None}
        yrs = len(out) / 12
        return out, (turn / yrs if yrs else None), det


def safe(s):
    """−100% の月（L で持ち物が全部消えた月）があると幾何の計算が log(0) で落ちる。その月だけ −99.9999% に置く（向きは変わらない・印を付ける）"""
    bad = [m for m, v in s.items() if v <= -1]
    return ({m: (max(v, -0.999999)) for m, v in s.items()}, bad) if bad else (s, [])


def ev(s, b, turnover=None, windows=()):
    s2, wiped = safe(s)
    b2, _ = safe(b)
    sub = lambda d, a, z: {k: v for k, v in d.items() if a <= k <= z}
    d = {'full': M.excess_stats(s2, b2, FIRST_M, END_M), 'train': M.excess_stats(s2, b2, FIRST_M, TRAIN_Z),
         'hold': M.excess_stats(s2, b2, HOLD_A, END_M), 'recent_2013_07': M.excess_stats(s2, b2, RECENT_A, END_M),
         'roll20': M.rolling(sub(s2, FIRST_M, END_M), sub(b2, FIRST_M, END_M), 20, 7),
         'dca20': M.dca(sub(s2, FIRST_M, END_M), sub(b2, FIRST_M, END_M), 20, 12),
         'maxdd_s': round(M.maxdd(sub(s2, FIRST_M, END_M)) * 100, 1), 'maxdd_b': round(M.maxdd(sub(b2, FIRST_M, END_M)) * 100, 1)}
    for nm, a, z in windows:
        d[nm] = M.excess_stats(s2, b2, a, z)
    if turnover is not None:
        d['annual_oneway_turnover'] = round(turnover, 3)
        d['cost_hold'] = M.excess_stats(safe(M.apply_cost(s, turnover, 0.001))[0], b2, HOLD_A, END_M)
    if wiped:
        d['wiped_months_L'] = wiped
    return d


GRADE_ORDER = {'S': 3, 'A': 2, 'B': 1, 'C': 0}


def sgn(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def cmd_run():
    t0 = time.time()
    L = json.load(open(LABELS))
    rows, summ = L['rows'], L['summary']
    if not any('yahoo_via' in r for r in rows):
        raise SystemExit('先に prices')
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if FIRST_M <= k <= END_M}
    P = Panel(rows, mkt)
    f2lab = lambda r: r['lock'] is not None
    fams = {
        'H1': ('F2 lock 時価加重 − French Mkt（主）', lambda r: r['lock'] is True, F2_VINTAGES, 'vw', 'mkt', None),
        'H2': ('F2 lock 等加重 − French Mkt', lambda r: r['lock'] is True, F2_VINTAGES, 'ew', 'mkt', None),
        'H3': ('F2 lock 時価加重 − 同じ母集団の時価加重', lambda r: r['lock'] is True, F2_VINTAGES, 'vw', 'pop', f2lab),
        'H4': ('F1 時価加重 − French Mkt', lambda r: r['f1'], F1_VINTAGES, 'vw', 'mkt', None),
        'H5': ('F1 時価加重 − 同じ母集団の時価加重', lambda r: r['f1'], F1_VINTAGES, 'vw', 'pop', lambda r: True),
        'H6': ('rep 上位 時価加重 − French Mkt', lambda r: r['rep_top'] is True, F2_VINTAGES, 'vw', 'mkt', None),
        'H7': ('dur 上位 時価加重 − French Mkt', lambda r: r['dur_top'] is True, F2_VINTAGES, 'vw', 'mkt', None),
    }
    fresh = {'F2': (HOLD_A, 201206), 'F1': (HOLD_A, 201506)}
    res, series_keep = {}, {}
    for H, (lab, pick, vins, wt, bench, popick) in fams.items():
        fam = 'F1' if H in ('H4', 'H5') else 'F2'
        wins = (('fresh_labels_2007_01_' + str(fresh[fam][1]), *fresh[fam]), ('spill_2006_vintage_2007_01_2009_06', HOLD_A, 200906),
                ('old_labels_carried_' + str(madd(fresh[fam][1], 1)) + '_2026_08', madd(fresh[fam][1], 1), END_M))
        res[H] = {'label': lab, 'family': fam, 'weighting': wt, 'benchmark': 'French Mkt' if bench == 'mkt' else '同じ母集団の時価加重（同じ S/L）',
                  'vintages': vins}
        for bd in ('S', 'L'):
            s, turn, det = P.chain(pick, vins, wt, bd)
            if bench == 'mkt':
                b = mkt; bdet = None
            else:
                b, _, bdet = P.chain(popick, vins, 'vw', bd)
            series_keep[(H, bd)] = (s, b)
            e = ev(s, b, turn, wins)
            res[H][bd] = {'stats': e, 'per_vintage': det, 'benchmark_per_vintage': ({v: {k: x[k] for k in ('n', 'obs_at_formation', 'months_filled_with_mkt')}
                                                                                      for v, x in bdet.items()} if bdet else None)}
            print(H, bd, 'hold', e['hold'] and e['hold']['ex_ann'], e['hold'] and e['hold']['t'], 'train', e['train'] and e['train']['ex_ann'],
                  e['train'] and e['train']['t'], flush=True)
    # Holm（保有期間の NW t の両側 p・S と L で別々）
    holm = {}
    for bd in ('S', 'L'):
        ps = {H: (res[H][bd]['stats']['hold'] or {}).get('p') for H in fams}
        holm[bd] = {'raw_p': ps, 'holm_p': M.holm(ps)}
    tested = []
    for H in fams:
        gb = {}
        for bd in ('S', 'L'):
            e = res[H][bd]['stats']
            g, crit = M.grade(e['full'], e['train'], e['hold'], e['roll20'], e.get('cost_hold'), None, holm[bd]['holm_p'].get(H), None, False)
            gb[bd] = (g, crit)
            res[H][bd]['grade'], res[H][bd]['criteria'] = g, crit
            res[H][bd]['holm_p_hold'] = holm[bd]['holm_p'].get(H)
        sS = sgn((res[H]['S']['stats']['hold'] or {}).get('ex_ann'))
        sL = sgn((res[H]['L']['stats']['hold'] or {}).get('ex_ann'))
        if sS != sL or sS == 0:
            g, why = 'C', 'S と L で保有期間の超過の符号が割れた（または測れない）→ C（事前登録）'
        else:
            g = min(gb['S'][0], gb['L'][0], key=lambda x: GRADE_ORDER[x])
            why = 'S と L の符号が一致 → 低い方'
        res[H]['grade'], res[H]['grade_rule'] = g, why
        hs, hl = res[H]['S']['stats']['hold'] or {}, res[H]['L']['stats']['hold'] or {}
        ts, tl = res[H]['S']['stats']['train'] or {}, res[H]['L']['stats']['train'] or {}
        tested.append({'name': H, 'label': lab if False else fams[H][0], 'family': 'registered_holm_H1_H7', 'graded': True, 'grade': g,
                       'grade_S': gb['S'][0], 'grade_L': gb['L'][0], 'grade_rule': why,
                       'train_ex_S': ts.get('ex_ann'), 'train_t_S': ts.get('t'), 'hold_ex_S': hs.get('ex_ann'), 'hold_t_S': hs.get('t'),
                       'train_ex_L': tl.get('ex_ann'), 'train_t_L': tl.get('t'), 'hold_ex_L': hl.get('ex_ann'), 'hold_t_L': hl.get('t'),
                       'holm_p_S': holm['S']['holm_p'].get(H), 'holm_p_L': holm['L']['holm_p'].get(H),
                       'criteria_S': gb['S'][1], 'criteria_L': gb['L'][1]})
    # ───── 報告のみ（事前登録の report_only）─────
    rep = {}

    def simple(name, pick, vins=F2_VINTAGES, wt='vw', bench='mkt', note=''):
        o = {'note': note}
        for bd in ('S', 'L'):
            s, turn, det = P.chain(pick, vins, wt, bd)
            b = mkt if bench == 'mkt' else P.chain(bench, vins, 'vw', bd)[0]
            e = ev(s, b, turn, (('fresh_labels_2007_01_2012_06', HOLD_A, 201206),))
            o[bd] = {'train': e['train'], 'hold': e['hold'], 'full': e['full'], 'recent_2013_07': e['recent_2013_07'],
                     'fresh_labels_2007_01_2012_06': e['fresh_labels_2007_01_2012_06'], 'roll20': e['roll20'], 'cost_hold': e.get('cost_hold'),
                     'per_vintage_n': {v: [x['n'], x['obs_at_formation']] for v, x in det.items()}}
        rep[name] = o
        tested.append({'name': name, 'family': 'report_only', 'graded': False, 'grade': None,
                       'hold_ex_S': (o['S']['hold'] or {}).get('ex_ann'), 'hold_t_S': (o['S']['hold'] or {}).get('t'),
                       'hold_ex_L': (o['L']['hold'] or {}).get('ex_ann'), 'hold_t_L': (o['L']['hold'] or {}).get('t'),
                       'train_ex_S': (o['S']['train'] or {}).get('ex_ann'), 'train_t_S': (o['S']['train'] or {}).get('t'),
                       'train_ex_L': (o['L']['train'] or {}).get('ex_ann'), 'train_t_L': (o['L']['train'] or {}).get('t')})
        print(name, 'S hold', (o['S']['hold'] or {}).get('ex_ann'), 'L hold', (o['L']['hold'] or {}).get('ex_ann'), flush=True)

    sic_i = lambda r: int(r['sic']) if r.get('sic') and str(r['sic']).isdigit() else None
    semi = lambda r: (sic_i(r) in SEMI_SIC) or r['ticker'].upper() in SEMI_NAMED or (r.get('yahoo') or '') in SEMI_NAMED
    simple('R_ex_semis_chain', lambda r: r['lock'] is True and not semi(r), note='半導体の連鎖（SIC 3674・3559・名指しの装置・材料）を除いた lock 時価加重 − French Mkt')
    simple('R_ex_aero_defence', lambda r: r['lock'] is True and not AERO(sic_i(r)), note='航空・防衛（SIC 3720-3729・3760-3769・3812）を除いた lock 時価加重 − French Mkt')
    simple('R_both_readers_agree', lambda r: r['lock'] is True and r['ab_agree85'] is True, note='A と B が irr≥85 で一致した lock だけ − French Mkt')
    simple('R_recognised_by_neither', lambda r: r['lock'] is True and r['rec_neither'] is True, note='A も B も会社が分からなかった（recognised=false）lock だけ − French Mkt')
    simple('R_F1_ew', lambda r: r['f1'], F1_VINTAGES, 'ew', note='F1 等加重 − French Mkt（副の族の参考）')
    simple('R_population_vw', lambda r: r['lock'] is not None, note='F2 の母集団（lock＋非 lock＋自動 no85）時価加重 − French Mkt（相手の生き残りの偏りの大きさ）')
    simple('R_nonlock_vw', lambda r: r['lock'] is False, note='F2 非 lock 時価加重 − French Mkt')
    # 業種そろえ（SIC2）: lock の各社 − 同じビンテージ・同じ SIC 上2桁の非 lock の時価加重、を lock の重みで平均
    ctl = {}
    for bd in ('S', 'L'):
        cs, excl = {}, {}
        for i, v in enumerate(F2_VINTAGES):
            a = v * 100 + 7
            z = F2_VINTAGES[i + 1] * 100 + 6 if i + 1 < len(F2_VINTAGES) else END_M
            lk = [r for r in rows if r['vintage'] == v and r['lock'] is True]
            nl = [r for r in rows if r['vintage'] == v and r['lock'] is False]
            groups = defaultdict(list)
            for r in lk:
                groups[str(r.get('sic') or '')[:2]].append(r)
            gser, ex_ = [], []
            for g2, lr in groups.items():
                nr = [r for r in nl if str(r.get('sic') or '')[:2] == g2 and g2]
                if not nr:
                    ex_ += [r['ticker'] for r in lr]; continue
                wl, _ = weights_for(lr, P.med[v]); wn, _ = weights_for(nr, P.med[v])
                sl, _, _, stl = book([r['cik'] for r in lr], wl, a, z, bd, P.st_fn(v), {}, 'vw')
                sn, _, _, stn = book([r['cik'] for r in nr], wn, a, z, bd, P.st_fn(v), {}, 'vw')
                if stl['obs_start'] == 0 and bd == 'S':
                    ex_ += [r['ticker'] for r in lr]; continue
                gser.append((sum(wl.values()), sl, sn, g2, [r['ticker'] for r in lr], len(nr)))
            V = {id(x): x[0] for x in gser}
            for m in mrange(a, z):
                num = den = 0.0
                for x in gser:
                    if m in x[1] and m in x[2] and V[id(x)] > 0:
                        num += V[id(x)] * (x[1][m] - x[2][m]); den += V[id(x)]
                for x in gser:
                    if m in x[1]:
                        V[id(x)] *= 1 + max(x[1][m], -1.0)
                if den > 0:
                    cs[m] = num / den
            excl[str(v)] = {'excluded_no_nonlock_same_sic2': ex_, 'groups': [(x[3], x[4], x[5]) for x in gser]}
        zero = {m: 0.0 for m in mkt}
        ctl[bd] = {'train': M.excess_stats(cs, zero, FIRST_M, TRAIN_Z), 'hold': M.excess_stats(cs, zero, HOLD_A, END_M),
                   'full': M.excess_stats(cs, zero, FIRST_M, END_M), 'months': len(cs), 'per_vintage': excl}
    rep['R_within_sic2'] = {'note': 'lock の各社 − 同じビンテージ・同じ SIC 上2桁の非 lock の時価加重（lock の重みで平均）。ex_ann・t は差の系列そのもの（0 と比べる）', **ctl}
    tested.append({'name': 'R_within_sic2', 'family': 'report_only', 'graded': False, 'grade': None,
                   'hold_ex_S': (ctl['S']['hold'] or {}).get('ex_ann'), 'hold_t_S': (ctl['S']['hold'] or {}).get('t'),
                   'hold_ex_L': (ctl['L']['hold'] or {}).get('ex_ann'), 'hold_t_L': (ctl['L']['hold'] or {}).get('t'),
                   'train_ex_S': (ctl['S']['train'] or {}).get('ex_ann'), 'train_t_S': (ctl['S']['train'] or {}).get('t'),
                   'train_ex_L': (ctl['L']['train'] or {}).get('ex_ann'), 'train_t_L': (ctl['L']['train'] or {}).get('t')})
    # 5年と 2026-08 までの手を触れない持ち方（各ビンテージの lock・時価加重）
    coh = {}
    for v in F2_VINTAGES:
        recs = [r for r in rows if r['vintage'] == v and r['lock'] is True]
        w, _ = weights_for(recs, P.med[v])
        o = {'names': [r['ticker'] for r in recs]}
        for bd in ('S', 'L'):
            for tag, z in (('5y', madd(v * 100 + 7, 59)), ('to_2026_08', END_M)):
                s, _, _, stt = book([r['cik'] for r in recs], w, v * 100 + 7, z, bd, P.st_fn(v), mkt, 'vw')
                ks = [k for k in sorted(s) if k in mkt]
                ws = wb = 1.0
                for k in ks:
                    ws *= 1 + max(s[k], -1.0); wb *= 1 + mkt[k]
                yrs = len(ks) / 12
                o[f'{bd}_{tag}'] = {'months': len(ks), 'wealth_ratio_vs_mkt': round(ws / wb, 3),
                                    'cagr_s': round((ws ** (1 / yrs) - 1) * 100, 2) if ws > 0 and yrs else -100.0,
                                    'cagr_mkt': round((wb ** (1 / yrs) - 1) * 100, 2) if yrs else None,
                                    'obs_at_formation': stt['obs_start'], 'n': stt['n'], 'months_filled_with_mkt': stt['empty_months']}
        coh[str(v)] = o
    rep['R_cohort_buy_and_hold'] = coh
    tested.append({'name': 'R_cohort_buy_and_hold', 'family': 'report_only', 'graded': False, 'grade': None,
                   'note': '各ビンテージの lock を5年・2026-08 まで（数値は report_only.R_cohort_buy_and_hold）'})
    # 門の今日の irr=85 の顔ぶれとの重なり（文脈だけ・主張なし）
    import glob
    g85, g100 = [], []
    for f in glob.glob(os.path.join(BASE, 'out', '*_gate_pack.json')):
        try:
            d = json.load(open(f))
        except Exception:  # noqa
            continue
        t = os.path.basename(f).replace('_gate_pack.json', '')
        if d.get('irr') in (85, '85'):
            g85.append(t)
        if d.get('irr') in (100, '100'):
            g100.append(t)
    lk_all = [r for r in rows if r['lock'] is True]
    ids = lambda r: {r['ticker'].upper(), (r.get('yahoo') or '').upper()} - {''}
    overlap = {'gate_irr85_today': sorted(g85), 'gate_irr100_today': sorted(g100),
               'pre2007_and_2009_lock_firms': sorted({f"{r['ticker']}（{r['name']}）" for r in lk_all}),
               'lock_in_gate_irr85': sorted({f"{r['vintage']}:{r['ticker']}" for r in lk_all if ids(r) & set(g85)}),
               'lock_in_gate_irr100': sorted({f"{r['vintage']}:{r['ticker']}" for r in lk_all if ids(r) & set(g100)}),
               'gate_irr85_in_universe_by_vintage': {str(v): sorted({r['ticker'] for r in rows if r['vintage'] == v and ids(r) & set(g85)}) for v in VINTAGES},
               'gate_irr85_labels_in_universe': sorted({f"{r['vintage']}:{r['ticker']}={'lock' if r['lock'] else ('nonlock' if r['lock'] is False else 'unlabelled')}"
                                                         f"{'' if r['src'] != 'read' else ' (A' + str(r.get('irr_A')) + '/B' + str(r.get('irr_B')) + ')'}"
                                                         for r in rows if ids(r) & set(g85)})}
    return res, holm, tested, rep, overlap, P, rows, summ, time.time() - t0


def cmd_result():
    """第3段の本体: 判定を出して out/mw_moat_text_pre2007.json に書く"""
    res, holm, tested, rep, overlap, P, rows, summ, secs = cmd_run()
    pre = json.load(open(os.path.join(BASE, 'out', 'mw_prereg.json')))
    bv = summ['by_vintage']
    # 窓の報告（事前登録の report_only のうち H1 の窓）を tested にも1行ずつ残す
    for key, lab in (('fresh_labels_2007_01_201206', '新しいラベルだけの保有期間 2007-01〜2012-06（H1 の窓）'),
                     ('spill_2006_vintage_2007_01_2009_06', '2006 ビンテージのはみ出し 2007-01〜2009-06（H1 の窓）'),
                     ('recent_2013_07', '2013-07〜（H1 の窓）'),
                     ('old_labels_carried_201207_2026_08', '2009 のラベルのまま持ち続けた 2012-07〜2026-08（H1 の窓）')):
        eS, eL = res['H1']['S']['stats'].get(key) or {}, res['H1']['L']['stats'].get(key) or {}
        tested.append({'name': 'R_H1_window_' + key, 'label': lab, 'family': 'report_only', 'graded': False, 'grade': None,
                       'ex_S': eS.get('ex_ann'), 't_S': eS.get('t'), 'cagr_diff_S': eS.get('cagr_diff'),
                       'ex_L': eL.get('ex_ann'), 't_L': eL.get('t'), 'cagr_diff_L': eL.get('cagr_diff')})
    posthoc = {'R_F1_ew', 'R_population_vw', 'R_nonlock_vw'}
    for t in tested:
        if t['name'] in posthoc:
            t['family'] = '事後_diagnostic'
        if t['name'] in rep and isinstance(rep[t['name']], dict) and rep[t['name']].get('note'):
            t['label'] = rep[t['name']]['note']
    # 観測できた lock（S の形成時）
    obs_lock = {v: [r['ticker'] for r in rows if r['vintage'] == v and r['lock'] is True and r.get('obs_at_formation')] for v in F2_VINTAGES}
    reach = {str(v): {'lock': bv[str(v)]['lock'], 'thin_lt10': bv[str(v)]['thin_lt10'], 'lock_observed_on_yahoo_at_formation': obs_lock[v],
                      'f1': bv[str(v)]['f1'], 'rep_top': bv[str(v)]['rep_top'], 'dur_top': bv[str(v)]['dur_top']} for v in F2_VINTAGES}
    reach['2012'] = {'lock': None, 'note': '予算で読まなかった（F2・rep・dur は無ラベル）', 'f1': bv['2012']['f1']}
    mapc = Counter((r['vintage'], r['yahoo_via'], bool(r.get('obs_at_formation'))) for r in rows)
    mapping = {str(v): {f'{via}|{"obs" if o else "unobs"}': n for (vv, via, o), n in sorted(mapc.items()) if vv == v} for v in VINTAGES}
    cov = {str(v): {'text_ok_units': sum(1 for r in rows if r['vintage'] == v),
                    'observed_at_formation': sum(1 for r in rows if r['vintage'] == v and r.get('obs_at_formation'))} for v in VINTAGES}
    for v in cov:
        cov[v]['rate'] = round(cov[v]['observed_at_formation'] / cov[v]['text_ok_units'], 3)
    g = {t['name']: t for t in tested}
    h1s, h1l = res['H1']['S']['stats'], res['H1']['L']['stats']
    h4s = res['H4']['S']['stats']
    n_lock = sum(bv[str(v)]['lock'] for v in F2_VINTAGES)
    n_obs = sum(len(obs_lock[v]) for v in F2_VINTAGES)
    f = lambda x, k='ex_ann': (x or {}).get(k)
    summary_ja = '\n'.join([
        f"1997〜2009 の5ビンテージの S&P500 の 10-K（候補段落のある {summ['n_read_units']} 単位）を2人が伏せたまま読み、irr≥85 で割れた {summ['n_third_reads']} 単位を3人目が読んだ（3人目は全部 70）。読み手の一致 κ は irr≥85 で {summ['kappa_irr_ge85']['kappa']}・刻み全体で {summ['kappa_irr_full_scale']['kappa']}。",
        f"最終の lock（irr≥85）は 1997 {bv['1997']['lock']}社・2000 {bv['2000']['lock']}社・2003 {bv['2003']['lock']}社・2006 {bv['2006']['lock']}社・2009 {bv['2009']['lock']}社（延べ {n_lock}）。全ビンテージが事前登録の『薄い（10社未満）』で、格は規則どおり変えていない。",
        f"lock は D・MDR／MIL／MIL・CNP／UTX・HON・VRSN・MIL・GD／VRSN・MIL・SIAL（公益の区域の独占＝D・CNP／国防の単独調達＝MDR・GD・UTX／機体に認証された部品＝HON／医薬品の承認に書き込まれた材料＝MIL・SIAL／.com の登録簿＝VRSN）。Yahoo で株価があったのは延べ {n_obs} 社だけ（MIL・SIAL・MDR は上場廃止で系列なし）。",
        f"主の H1（lock 時価加重 − French Mkt）: 訓練 1997-07〜2006-12 は S {f(h1s['train'])}%/年（t {f(h1s['train'], 't')}）・L {f(h1l['train'])}%、保有 2007-01〜2026-08 は S +{f(h1s['hold'])}%/年（t {f(h1s['hold'], 't')}）・L +{f(h1l['hold'])}%（t {f(h1l['hold'], 't')}）→ 格 C（訓練の t≥2 を満たさない）。",
        f"登録した7本（H1〜H7）はすべて C。いちばん強いのは機械の F1（H4）の保有 S +{f(h4s['hold'])}%/年（t {f(h4s['hold'], 't')}・Holm 後 p {holm['S']['holm_p'].get('H4')}）だが、訓練は t {f(h4s['train'], 't')} で、L（消えた社を −100%）では訓練 {f(res['H4']['L']['stats']['train'])}%/年。",
        f"業種をそろえた比較（同じ SIC 上2桁の非 lock との差）は保有 S {f(rep['R_within_sic2']['S']['hold'])}%/年（t {f(rep['R_within_sic2']['S']['hold'], 't')}）。2人一致の部分集合は主と同じ（lock は全部2人一致）、どちらも会社が分からなかった lock は SIAL 1社だけ（系列なし）。",
        f"門の今日の irr=85（{len(overlap['gate_irr85_today'])}社）と重なる lock はゼロ（今日の顔ぶれで当時の名簿に居たのは 2012 の LRCX だけで、予算で読まず無ラベル）。1997 の lock の D（Dominion）は今日の門で irr=100。",
        f"最大の注意は標本の小ささ: lock は延べ {n_lock} 社・株価が観測できたのは延べ {n_obs} 社で、保有期間の S の成績の大半は VeriSign 1社（2009-07〜2026-08）。S と L の囲みも広い。『2007年より前の本文でも irr≥85 が市場に勝った』という証拠にはならない（逆の証拠でもない）。",
        '門・採点・配分・売却規律は何も変えていない。',
    ])
    caveats = [
        f"lock は全ビンテージで10社未満（{', '.join(str(bv[str(v)]['lock']) for v in F2_VINTAGES)}）＝事前登録の『薄い』。株価が形成時に観測できた lock は延べ {n_obs} 社（2000 は0社→S では市場で埋めた36か月）",
        '保有期間の S の成績の大半は VeriSign 1社（2009 ビンテージは MIL・SIAL が系列なしで VRSN だけが残った）。1社の成績であって規則の成績ではない',
        'L（観測できない月を −100%）は買収で消えた社（MIL は 2010・SIAL は 2015 に Merck KGaA がプレミアムで買収）を全損に数えるので、極端な下限。S と L の幅が格を付けられないほど広い',
        '語の網は 1,138 単位のうち irr≥85 をほとんど拾わなかった（A・B とも17件）。網に掛からない機構は自動で非 lock（事前登録の限界）',
        '読み手は半数以上の単位で会社が分かったと答えた（A 52.5%・B 54.0%）。lock のうち誰も分からなかったのは SIAL だけ',
        'Yahoo は上場廃止の社を持たない: 形成時に観測できた社の割合は 1997 年で約4割（CRSP 由来の French Mkt と比べるので生き残りの偏りが残る）',
        '2012 ビンテージは予算で読まなかった（事前登録の段1）＝F2 は 2009 のラベルのまま 2026-08 まで',
    ]
    posthoc_notes = [
        '持ち物が空の月（S で lock が1社も観測できない 2000 ビンテージ等）は French Mkt で埋めた（mw_index_events.calendar_ew と同じ扱い・事前登録に明記なし）',
        'L で持ち物が全部消えた月（2000-07 の MIL だけの lock）は −100%。幾何の計算が log(0) で落ちるので、その月だけ −99.9999% に置いた（向きは変わらない・wiped_months_L に印）',
        'S と L の『保有期間の超過の符号』は算術平均の超過（ex_ann）で比べた。H1 の L は ex_ann +1.03 だが幾何の年率差は −3.16（どちらでも格は C で変わらない）',
        'CIK が今日の SEC 一覧で複数の記号を持つときは名簿の記号に一致するもの、無ければ一覧の先頭（普通株）を使った',
        '系列の検問は mw_index_events.obs と同じく instrumentType が EQUITY でないもの（記号の使い回しで ETF・投信になったもの）も観測なしにした',
        '月 +300% 超の検問は mw_index_events と同じく系列全体で最初の月から先を捨てた（NBR は 1985 年代の跳ねで全期間が観測なし）',
        '費用は戦略の側だけに引いた（H3・H5 の相手の母集団には引いていない＝戦略に厳しい向き）。等加重の毎月の戻しの売買は事前登録の費用の規則（作り替えと最初の買いだけ）の外なので引いていない（量は per_vintage に事後の報告）',
        'rep/dur の『2人の低い方』で null は最も低い（手がかりなし）と扱った',
        '『どちらの読み手も recognised=false』は A と B で判定した（3人目は8単位しか読んでいない）',
        '業種そろえの対照は SIC 上2桁の群ごとに lock と非 lock を別々に持ち（S の売りは群の中で按分）、lock の重みで平均した',
        'R_F1_ew・R_population_vw・R_nonlock_vw は事前登録に無い診断（判定に使わない）',
    ]
    obj = {
        'angle': 'moat_text_pre2007',
        'prereg': 'out/mw_moat_text_pre2007_prereg.json', 'prereg_commits': ['905a0d2', '21fa7a5'],
        'question': json.load(open(PREREG))['question'],
        'stage': '第3段（読みの後に鍵を開け、株価を初めて取得してリターン・判定）。規則は事前登録のまま',
        'periods': {'train': '1997-07〜2006-12', 'hold': '2007-01〜2026-08', 'full': '1997-07〜2026-08', 'fresh_F2': '2007-01〜2012-06', 'fresh_F1': '2007-01〜2015-06', 'recent': '2013-07〜'},
        'benchmark': 'French Mkt（Mkt-RF + RF）・H3/H5 は同じ母集団の時価加重（同じ Yahoo・同じ S/L・同じ重み）',
        'criteria': pre['criteria'], 'grades_def': pre['grades'],
        'grading_rule': 'mw_common.grade を S と L で別々に当て、保有期間の超過の符号が S と L で一致したときだけ低い方の格。割れたら C。C5 は N/A・C8 は該当なし',
        'labels': summ,
        'lock_counts': {str(v): {'lock': bv[str(v)]['lock'], 'names': bv[str(v)]['lock_names'], 'both_readers_agree': bv[str(v)]['lock_both_readers_agree'],
                                 'recognised_by_neither': bv[str(v)]['lock_recognised_by_neither'], 'thin_lt10': bv[str(v)]['thin_lt10']} for v in F2_VINTAGES},
        'reachability': reach,
        'reachability_rule': '事前登録: lock が10社未満のビンテージは『薄い』と印を付けて報告する（格は変えない）。全ビンテージが薄い',
        'price_coverage': cov, 'ticker_mapping_counts': mapping,
        'tests': res, 'holm': holm,
        'tested': tested, 'n_tested': len(tested),
        'n_graded': sum(1 for t in tested if t.get('graded')),
        'report_only': rep,
        'gate_overlap_context_only': overlap,
        'caveats': caveats, 'posthoc_implementation_notes': posthoc_notes,
        'summary_ja': summary_ja,
        'runtime_s': round(secs, 1),
    }
    p = M.save(RESULT, obj)
    print('書いた', p)
    print(summary_ja)
    for t in tested:
        print(t['name'], t.get('grade'), t.get('family'))


if __name__ == '__main__':
    os.makedirs(MT, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'prereg':
        cmd_prereg(sys.argv[2] if len(sys.argv) > 2 else 'freeze')
    elif cmd == 'candidates':
        cmd_candidates()
    elif cmd == 'fetch_cands':
        cmd_fetch_cands(part=int(sys.argv[2]) if len(sys.argv) > 2 else 0, nparts=int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    elif cmd == 'universe':
        cmd_universe()
    elif cmd == 'reparse':
        cmd_reparse()
    elif cmd == 'extract':
        cmd_extract()
    elif cmd == 'mask':
        cmd_mask()
    elif cmd == 'instructions':
        cmd_instructions()
    elif cmd == 'labels':
        cmd_labels()
    elif cmd == 'prices':
        cmd_prices()
    elif cmd == 'run':
        cmd_result()
    else:
        print(__doc__)
