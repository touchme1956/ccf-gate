#!/usr/bin/env python3
"""night/mw_ex27.py — 角度 ex27（読むだけ・門の判定には不使用）

問い: 『質（収益性）で選んだ米国大型株』は、XBRL より前・巨大テックの時代と逆向きの窓
      （1996-07〜2002-06: IT バブルの膨張と崩壊）でも、同じ母集団の時価加重に勝ったか。
      2010-2026（mw_sec_replication）と重ならない2つ目の窓で、同じ形を同じ規則で測る。

原本: SEC EDGAR の 10-K / 10-K405 の提出書類（全文 .txt）に付いた Financial Data Schedule（EX-27・Article 5）と
      表紙の『非関係者が持つ議決権株の時価総額（aggregate market value … held by non-affiliates）』。
      EX-27 は 2001年に廃止されたので、XBRL（2009〜）までの間を埋める唯一の無料の機械可読の決算の原本で、
      後に上場廃止した会社も入っている。

事前登録: out/mw_ex27_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を mw_common.grade でそのまま当てる。

段
  idx      : EDGAR full-index（form.idx）から 10-K / 10-K405 の一覧を作る
  pilot    : 20件の提出書類でタグの有無を見る（リターンは計算しない）
  crawl    : 全件を取得して必要な部分だけ残す（out/_mw_cache/ex27/raw/）→ 解析して out/_mw_cache/ex27/parsed.jsonl.gz
  coverage : 母集団の被覆（ティッカー・Yahoo の価格の有無）を数える（リターンは計算しない）
  run      : 戦略の月次リターン・統計・判定 → out/mw_ex27.json
"""
import sys, os, re, io, json, gzip, math, time, glob, datetime, threading, random, statistics as S, subprocess, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

CACHE = M.CACHE
EXD = os.path.join(CACHE, 'ex27')
RAW = os.path.join(EXD, 'raw')
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}
IDX_YEARS = range(1994, 2003)
FORMS10K = ('10-K', '10-K405')


# ───────────────────────── 一覧 ─────────────────────────
def _get_idx(y, q):
    os.makedirs(EXD, exist_ok=True)
    p = os.path.join(EXD, f'form_{y}Q{q}.idx')
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        for k in range(5):
            try:
                req = urllib.request.Request(f'https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx', headers={'User-Agent': SEC_UA['User-Agent']})
                b = urllib.request.urlopen(req, timeout=120).read()
                open(p, 'wb').write(b)
                break
            except Exception:  # noqa
                time.sleep(2 ** (k + 1))
        time.sleep(0.2)
    return p


LINE = re.compile(r'^(\S+(?: \S+)?)\s{2,}(.*?)\s{2,}(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s*$')


def filing_list():
    """10-K / 10-K405 の提出（1994Q1〜2001Q4）→ [{form, name, cik, filed, path, acc}]（同じ受付番号は1件）"""
    out, seen = [], {}
    for y in IDX_YEARS:
        for q in (1, 2, 3, 4):
            if y == 2002 and q > 2:
                continue
            for line in open(_get_idx(y, q), encoding='latin-1'):
                m = LINE.match(line)
                if not m or m.group(1) not in FORMS10K:
                    continue
                form, name, cik, filed, path = m.groups()
                acc = path.rsplit('/', 1)[-1].replace('.txt', '')
                if acc in seen:   # 同じ提出を複数の登録者が出す（持株会社と子会社の合同 10-K）→ 1件にまとめ、CIK を全部持つ
                    seen[acc]['ciks'].append(str(int(cik))); seen[acc]['names'].append(name.strip())
                    continue
                f = {'form': form, 'name': name.strip(), 'cik': str(int(cik)), 'filed': filed, 'path': path, 'acc': acc,
                     'ciks': [str(int(cik))], 'names': [name.strip()]}
                seen[acc] = f
                out.append(f)
    return out


# ───────────────────────── 取得（SEC: 10 req/s 以下） ─────────────────────────
class Rate:
    def __init__(self, per_s):
        self.gap = 1.0 / per_s; self.lock = threading.Lock(); self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next)
            self.next = t + self.gap
        d = t - time.time()
        if d > 0:
            time.sleep(d)


RATE = Rate(7.0)


def fetch_text(path):
    """EDGAR の全文 .txt（gzip で受けて展開）→ str。404 は None"""
    url = 'https://www.sec.gov/Archives/' + path
    for k in range(6):
        RATE.wait()
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip' or b[:2] == b'\x1f\x8b':
                b = gzip.decompress(b)
            return b.decode('latin-1')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (k + 1) + random.random())
        except Exception:  # noqa
            time.sleep(2 ** (k + 1) + random.random())
    raise RuntimeError(f'取得失敗 {url}')


def trim(txt):
    """全文から必要な部分だけ残す: SEC ヘッダ・本体の先頭 40,000 字（表紙）・EX-27 の文書すべて・『symbol』の前後"""
    parts = {}
    h = txt.find('</SEC-HEADER>')
    parts['header'] = txt[:h + 13] if h > 0 else txt[:6000]
    d0 = txt.find('<DOCUMENT>')
    parts['cover'] = txt[d0:d0 + 60000] if d0 >= 0 else txt[:60000]
    ex = []
    for m in re.finditer(r'<DOCUMENT>\s*<TYPE>\s*EX-27[^\n]*\n', txt):
        e = txt.find('</DOCUMENT>', m.start())
        ex.append(txt[m.start():(e if e > 0 else m.start() + 20000)][:30000])
    if not ex:   # 本体の中に埋め込まれた財務データ表（<TYPE> が別でない）を拾う
        for m in re.finditer(r'<ARTICLE>\s*[0-9A-Z]+', txt):
            ex.append(txt[max(0, m.start() - 200):m.start() + 8000])
            if len(ex) >= 4:
                break
    parts['ex27'] = ex
    sy = []
    for m in re.finditer(r'(?i)\bsymbols?\b', txt):
        sy.append(txt[max(0, m.start() - 250):m.start() + 120])
        if len(sy) >= 8:
            break
    parts['symbol'] = sy
    parts['len'] = len(txt)
    return parts


def raw_path(acc):
    return os.path.join(RAW, acc[:10], acc + '.json.gz')


def get_trimmed(f):
    p = raw_path(f['acc'])
    if os.path.exists(p):
        try:
            return json.loads(gzip.open(p).read())
        except Exception:  # noqa
            pass
    txt = fetch_text(f['path'])
    if txt is None:
        d = {'missing': True}
    else:
        d = trim(txt)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + f'.{os.getpid()}.{threading.get_ident()}.tmp'
    with gzip.open(tmp, 'wt') as g:
        json.dump(d, g)
    os.replace(tmp, p)
    return d


# ───────────────────────── 解析 ─────────────────────────
def _hv(header, key):
    m = re.search(key + r':\s*(.+)', header)
    return m.group(1).strip() if m else None


def parse_header(h):
    sic = None
    m = re.search(r'STANDARD INDUSTRIAL CLASSIFICATION:\s*(.*?)\[(\d{3,4})\]', h)
    if m:
        sic = m.group(2)
    return {'type': _hv(h, 'CONFORMED SUBMISSION TYPE'), 'period': _hv(h, 'CONFORMED PERIOD OF REPORT'),
            'filed': _hv(h, 'FILED AS OF DATE'), 'name': _hv(h, 'COMPANY CONFORMED NAME'),
            'cik': (str(int(_hv(h, 'CENTRAL INDEX KEY'))) if _hv(h, 'CENTRAL INDEX KEY') else None),
            'sic': sic, 'fye': _hv(h, 'FISCAL YEAR END'), 'sros': re.findall(r'SROS:\s*(\S+)', h)}


MON = {m: i + 1 for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'])}


def _fds_date(s):
    """'DEC-31-1996' / '12-31-1996' / '1996-12-31' → 'YYYY-MM-DD'"""
    if not s:
        return None
    s = s.strip().upper()
    m = re.match(r'([A-Z]{3})-(\d{1,2})-(\d{4})', s)
    if m and m.group(1) in MON:
        return f'{m.group(3)}-{MON[m.group(1)]:02d}-{int(m.group(2)):02d}'
    m = re.match(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', s)
    if m:
        return f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        return m.group(0)
    return None


def _fds_num(s):
    """'4,191' / '(1,234)' / '0<F1>' / '-1,234' → float（数字が無ければ None）"""
    s = re.sub(r'<F\d+>', '', s).strip()
    s = s.split()[0] if s.split() else ''
    neg = s.startswith('(') or s.startswith('-')
    s2 = s.strip('()').replace(',', '').replace('$', '').lstrip('-')
    try:
        v = float(s2)
    except ValueError:
        return None
    return -v if neg else v


FDS_TAGS = ['CASH', 'SECURITIES', 'RECEIVABLES', 'ALLOWANCES', 'INVENTORY', 'CURRENT-ASSETS', 'PP&E', 'DEPRECIATION', 'TOTAL-ASSETS',
            'CURRENT-LIABILITIES', 'BONDS', 'PREFERRED-MANDATORY', 'PREFERRED', 'COMMON', 'OTHER-SE', 'TOTAL-LIABILITY-AND-EQUITY',
            'SALES', 'TOTAL-REVENUES', 'CGS', 'TOTAL-COSTS', 'OTHER-EXPENSES', 'LOSS-PROVISION', 'INTEREST-EXPENSE', 'INCOME-PRETAX',
            'INCOME-TAX', 'INCOME-CONTINUING', 'DISCONTINUED', 'EXTRAORDINARY', 'CHANGES', 'NET-INCOME', 'EPS-PRIMARY', 'EPS-DILUTED',
            'EPS-BASIC']
NOSCALE = {'EPS-PRIMARY', 'EPS-DILUTED', 'EPS-BASIC'}


def parse_fds(doc):
    """EX-27 の1文書 → {article, mult, ptype, fye, pstart, pend, cik, name, v: {tag: 値(ドル・倍率を掛け済み)}}"""
    g = lambda t: (re.search(r'<' + re.escape(t) + r'>\s*([^\n<]*)', doc) or [None, None])[1]
    art = g('ARTICLE')
    mult_s = g('MULTIPLIER')
    mult = _fds_num(mult_s) if mult_s else 1.0
    if not mult:
        mult = 1.0
    v = {}
    for t in FDS_TAGS:
        m = re.search(r'<' + re.escape(t) + r'>\s*([^\n]*)', doc)
        if m:
            x = _fds_num(m.group(1))
            if x is not None:
                v[t] = x if t in NOSCALE else x * mult
    ck = g('CIK')
    return {'article': (art or '').strip().upper(), 'mult': mult, 'ptype': (g('PERIOD-TYPE') or '').strip().upper(),
            'fye': _fds_date(g('FISCAL-YEAR-END')), 'pstart': _fds_date(g('PERIOD-START')), 'pend': _fds_date(g('PERIOD-END')),
            'cik': (str(int(re.sub(r'\D', '', ck))) if ck and re.sub(r'\D', '', ck) else None), 'name': (g('NAME') or '').strip(), 'v': v}


MONTHS = '(January|February|March|April|May|June|July|August|September|October|November|December|Jan\\.?|Feb\\.?|Mar\\.?|Apr\\.?|Jun\\.?|Jul\\.?|Aug\\.?|Sept?\\.?|Oct\\.?|Nov\\.?|Dec\\.?)'
DATE_RE = re.compile(MONTHS + r'\s+(\d{1,2}),?\s+(\d{4})', re.I)
NUMDATE_RE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b')
AMT_RE = re.compile(r'\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(\s+\d{1,2}/\d{1,2})?(?:\s*(million|billion|thousand|mil\.?|bil\.?)\b)?', re.I)
MNUM = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def _valid_date(x):
    try:
        datetime.date.fromisoformat(x)
        return True
    except (ValueError, TypeError):
        return False


def _dates_in(s):
    return [(p, d) for p, d in _dates_in0(s) if _valid_date(d)]


def _dates_in0(s):
    out = []
    for m in DATE_RE.finditer(s):
        try:
            mo = MNUM[m.group(1)[:3].lower()]
            out.append((m.start(), f'{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}'))
        except (KeyError, ValueError):
            pass
    for m in NUMDATE_RE.finditer(s):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 1900 if y < 100 and y > 50 else (y + 2000 if y < 100 else y)
        if 1 <= a <= 12 and 1 <= b <= 31 and 1990 <= y <= 2002:
            out.append((m.start(), f'{y:04d}-{a:02d}-{b:02d}'))
    return out


def _amt(m):
    x = float(m.group(1).replace(',', ''))
    if m.group(2):
        a, b = m.group(2).split('/')
        x += float(a) / float(b)
    u = (m.group(3) or '').lower()
    if u.startswith('b'):
        x *= 1e9
    elif u.startswith('mil'):
        x *= 1e6
    elif u.startswith('th'):
        x *= 1e3
    return x


PRICE_CTX = re.compile(r'(?i)\bprices?\b')


def _first_price_after(win, pos, span=90):
    """位置 pos の後ろ span 字の中で最初の株価らしい額（単位語なし・2万ドル未満・額面でない）"""
    seg = win[pos:pos + span]
    for a in AMT_RE.finditer(seg):
        if a.group(3):
            continue
        tail = seg[a.end():a.end() + 12].lower()
        if 'par' in tail:
            continue
        v = _amt(a)
        if 0.05 <= v < 20000:
            return v, pos + a.end()
    return None, None


def parse_cover(cover, filed):
    """表紙 → {float, float_date, price, price_date, shares, shares_all, how}。見つからなければ float=None（欠測・0にしない）"""
    t = re.sub(r'<[^>]{1,80}>', ' ', cover)            # HTML のタグを除く（2000年前後の一部）
    t = t.replace('&nbsp;', ' ').replace('&#160;', ' ').replace('&amp;', '&').replace('&#151;', '-')
    t = re.sub(r'[ \t\r\n]+', ' ', t)
    res = {'float': None, 'float_date': None, 'price': None, 'price_date': None, 'shares': None, 'shares_all': [], 'how': None}
    for m in re.finditer(r'(?i)aggregate\s+market\s+value', t):
        w0, w1 = max(0, m.start() - 350), min(len(t), m.end() + 900)
        win = t[w0:w1]
        amts = [(_amt(a), a.start() + w0) for a in AMT_RE.finditer(win)]
        big = [a for a in amts if a[0] >= 1e6 and m.start() - 250 <= a[1] <= m.end() + 600]
        pre = t[max(0, m.start() - 45):m.start()].lower()
        if re.search(r'(there\s+is\s+no|there\s+was\s+no|not\s+have\s+an?|\bno)\s*$', pre):
            res['how'] = 'negated'; break                        # 『there is no aggregate market value』＝浮動株なし
        if not big:
            continue
        after = [a for a in big if a[1] >= m.start()]          # 句の後ろで最初に出る 100万ドル以上の額（無ければ句の前 250 字以内の最後）
        fl = after[0] if after else big[-1]
        between = t[m.end():fl[1]].lower() if fl[1] > m.end() else ''
        if re.search(r'not\s+applicable|\bnone\b|no\s+(?:established\s+)?(?:public\s+)?(?:trading\s+)?market|not\s+publicly\s+traded|no\s+market', between):
            res['how'] = 'negated'; break
        dates = [(p + w0, d) for p, d in _dates_in(win)]
        # 株価の日付: 『price』の後ろ 70 字以内の日付を優先（例: held … on Dec 31 based on closing price on Feb 26 → Feb 26）
        pdates = []
        for pm in PRICE_CTX.finditer(win):
            for p_, d_ in dates:
                if 0 <= p_ - (pm.end() + w0) <= 70:
                    pdates.append((p_ - (pm.end() + w0), d_))
        if pdates:
            dt = min(pdates)[1]
        elif dates:
            dt = min((abs(p_ - m.start()), d_) for p_, d_ in dates)[1]
        else:
            dt = None
        pr = None
        for pm in PRICE_CTX.finditer(win):
            v, _e = _first_price_after(win, pm.end())
            if v is not None:
                pr = v; break
        if pr is None:
            pm = re.search(r'\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(\s+\d{1,2}/\d{1,2})?\s*per\s+share', win, re.I)
            if pm:
                v = float(pm.group(1).replace(',', ''))
                if pm.group(2):
                    a_, b_ = pm.group(2).split('/'); v += float(a_) / float(b_)
                if 0.05 <= v < 20000:
                    pr = v
        res.update({'float': fl[0], 'float_date': dt, 'price': pr, 'price_date': dt if pr else None, 'how': 'cover'})
        break
    # 発行済株数: 表紙の先頭 15,000 字で『outstanding』の前後 160 字にある 10万以上の数（$ の付いた額・議決権数・株主数・授権株数は除く）
    head = t[:15000]
    sh = []
    for om in re.finditer(r'(?i)outstanding', head):
        a0 = max(0, om.start() - 160); seg = head[a0:om.end() + 160]
        for nm in re.finditer(r'(?<![\$\d,.])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(million|billion)?', seg):
            x = float(nm.group(1).replace(',', ''))
            u = (nm.group(2) or '').lower()
            if u == 'million':
                x *= 1e6
            elif u == 'billion':
                x *= 1e9
            if x < 1e5 or x > 5e10:
                continue
            tail = seg[nm.end():nm.end() + 40].lower()
            pre = seg[max(0, nm.start() - 3):nm.start()]
            if '$' in pre or any(w in tail for w in ('vote', 'holder', 'record', 'authoriz')):
                continue
            if x.is_integer() and 1900 <= x <= 2100:
                continue
            sh.append(x)
    res['shares_all'] = sorted(set(sh))[-6:]
    res['shares'] = max(sh) if sh else None
    return res


SYM_RE = re.compile(r'(?:under|using|with)\s+the\s+(?:(?:ticker|trading|stock|common\s+stock)\s+)?symbols?\s*[:"\'`“”‘’\(]*\s*["\'`“‘]?([A-Z][A-Z0-9]{0,4}(?:[.\-/][A-Z])?)\b')


def parse_symbols(snips):
    out = []
    for s in snips:
        t = re.sub(r'\s+', ' ', s)
        for m in SYM_RE.finditer(t):
            x = m.group(1).upper()
            if x not in out and x not in ('THE', 'A', 'AND', 'OF', 'ON', 'IN', 'NYSE', 'NASDAQ', 'AMEX'):
                out.append(x)
    return out[:4]


ANNUAL_PT = ('12-MOS', 'YEAR', '12-MOS.', '12MOS', '52-WKS', '53-WKS', '52-WEEKS', '53-WEEKS', '12-MONTHS', '12 MOS', 'YEAR-END')


def _is_annual(x):
    if x['ptype'] in ANNUAL_PT:
        return True
    if x['pstart'] and x['pend']:
        try:
            return 330 <= (datetime.date.fromisoformat(x['pend']) - datetime.date.fromisoformat(x['pstart'])).days <= 400
        except ValueError:
            return False
    return False


FY_COVER = re.compile(r'(?i)(?:fiscal\s+)?year\s+ended\s*:?\s*' + MONTHS + r'\s+(\d{1,2}),?\s+(\d{4})')


def _period_from_cover(cover):
    t = re.sub(r'\s+', ' ', re.sub(r'<[^>]{1,80}>', ' ', cover[:8000]))
    m = FY_COVER.search(t)
    if not m:
        return None
    try:
        return f'{int(m.group(3)):04d}-{MNUM[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}'
    except (KeyError, ValueError):
        return None


def parse_filing(f, d):
    """1件 → 解析結果。EX-27 は報告期間（SEC ヘッダ → 無ければ表紙の『year ended』→ 無ければ最も新しい年次の表）の期末と
    10日以内で合う 12か月の表を選ぶ。前年の表（同じ提出の中の修正再表示）も拾う"""
    if d.get('missing'):
        return {'acc': f['acc'], 'missing': True}
    h = parse_header(d['header'])
    if len(f.get('ciks', [])) > 1:   # 合同 10-K: SEC ヘッダの最初の登録者（主たる登録者＝上場している親）に付ける
        f = dict(f)
        if h['cik'] in f['ciks']:
            f['name'] = f['names'][f['ciks'].index(h['cik'])]; f['cik'] = h['cik']
    fds = [parse_fds(x) for x in d['ex27']]
    per = h['period']
    per_d = f'{per[:4]}-{per[4:6]}-{per[6:8]}' if per and len(per) == 8 else None
    per_src = 'header' if per_d else None
    if not per_d:
        per_d = _period_from_cover(d['cover'])
        per_src = 'cover' if per_d else None
    ann = [x for x in fds if x['pend'] and _is_annual(x)]
    if not per_d and ann:
        per_d = max(x['pend'] for x in ann); per_src = 'fds'

    def gap(x):
        try:
            return abs((datetime.date.fromisoformat(x['pend']) - datetime.date.fromisoformat(per_d)).days)
        except (ValueError, TypeError):
            return 9999
    cand = [x for x in ann if per_d and gap(x) <= 10]
    same = [x for x in cand if x['cik'] in (None, h['cik'], f['cik'])]
    pick = (same or cand or [None])[0]
    prev = None
    if per_d:
        for x in ann:
            if x is pick:
                continue
            try:
                dd = (datetime.date.fromisoformat(per_d) - datetime.date.fromisoformat(x['pend'])).days
            except ValueError:
                continue
            if 350 <= dd <= 380 and x['cik'] in (None, h['cik'], f['cik']):
                prev = x; break
    cv = parse_cover(d['cover'], f['filed'])
    return {'acc': f['acc'], 'form': f['form'], 'cik': f['cik'], 'hcik': h['cik'], 'n_registrants': len(f.get('ciks', [1])), 'name': f['name'], 'filed': f['filed'], 'period': per_d,
            'period_src': per_src, 'sic': h['sic'], 'sros': h['sros'], 'n_fds': len(fds), 'fds_articles': sorted({x['article'] for x in fds}),
            'fds': pick, 'fds_prev_restated': prev, 'cover': cv, 'symbols': parse_symbols(d.get('symbol', [])), 'len': d.get('len')}


# ───────────────────────── 試験（20件） ─────────────────────────
def pilot():
    fl = filing_list()
    print('10-K/10-K405 の件数（年ごと・提出日）:', {y: sum(1 for f in fl if f['filed'][:4] == str(y)) for y in IDX_YEARS})
    rng = random.Random(20260928)
    big = ['GENERAL ELECTRIC CO', 'INTEL CORP', 'MERCK & CO INC', 'WAL MART STORES INC', 'MICROSOFT CORP', 'COCA COLA CO', 'EXXON CORP',
           'INTERNATIONAL BUSINESS MACHINES CORP', 'MOBIL CORP', 'COMPAQ COMPUTER CORP']
    pick = []
    for nm in big:
        c = [f for f in fl if f['name'] == nm and f['filed'][:4] in ('1997', '1999', '2001')]
        if c:
            pick.append(rng.choice(c))
    rest = [f for f in fl if '1996-01-01' <= f['filed'] <= '2001-06-30']
    pick += rng.sample(rest, 20 - len(pick))
    out = []
    for f in pick:
        d = get_trimmed(f)
        p = parse_filing(f, d)
        out.append(p)
        fd = p.get('fds') or {}
        v = fd.get('v', {})
        print(f"{p['filed']} {p['form']:7s} {p['name'][:30]:30s} sic={p.get('sic')} art={fd.get('article')} n_fds={p.get('n_fds')} "
              f"TA={v.get('TOTAL-ASSETS')} REV={v.get('TOTAL-REVENUES')} CGS={v.get('CGS')} TC={v.get('TOTAL-COSTS')} PT={v.get('INCOME-PRETAX')} "
              f"INT={v.get('INTEREST-EXPENSE')} AR={v.get('RECEIVABLES')} INV={v.get('INVENTORY')} CL={v.get('CURRENT-LIABILITIES')} "
              f"| float={p['cover']['float']} fdate={p['cover']['float_date']} px={p['cover']['price']} sh={p['cover']['shares']} sym={p['symbols']}")
    json.dump(out, open(os.path.join(EXD, 'pilot.json'), 'w'), indent=1)


CRAWL_FROM, CRAWL_TO = '1995-01-01', '2001-06-30'
NEXT_TO = '2002-06-30'     # 2001年の形成の『翌年の表紙』（生き残りを含む近似の診断だけに使う）


def crawl_next():
    """2001年の形成の浮動株そのままの上位 2,500 社について、FY2001 の 10-K（提出 2001-07〜2002-06）の表紙だけ取る（診断用）"""
    panel, _ = build_panel_ex27()
    F = []
    for c, fil in panel.items():
        r = formation(fil, 2001)
        if r and float_sane(r):
            F.append((r['float'], c))
    F.sort(reverse=True)
    want = {c for _, c in F[:TOPRAW_X]}
    fl = [f for f in filing_list() if CRAWL_TO < f['filed'] <= NEXT_TO and f['cik'] in want and not os.path.exists(raw_path(f['acc']))]
    print('翌年の表紙', len(fl), '件', flush=True)
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(get_trimmed, fl))


def crawl():
    """全件取得（再開できる: 既に取れた受付番号は飛ばす）。SEC の上限 10 req/s に対し 7 req/s"""
    fl = [f for f in filing_list() if CRAWL_FROM <= f['filed'] <= CRAWL_TO]
    todo = [f for f in fl if not os.path.exists(raw_path(f['acc']))]
    print(f'対象 {len(fl)} 件・未取得 {len(todo)} 件', flush=True)
    t0 = time.time(); done = [0]; errs = []
    lock = threading.Lock()
    def one(f):
        try:
            get_trimmed(f)
        except Exception as e:  # noqa
            with lock:
                errs.append((f['acc'], str(e)[:120]))
        with lock:
            done[0] += 1
            if done[0] % 500 == 0:
                el = time.time() - t0
                print(f'{done[0]}/{len(todo)}  {el/60:.1f}分  残り約{(len(todo)-done[0])*el/done[0]/60:.0f}分  失敗{len(errs)}', flush=True)
    with ThreadPoolExecutor(24) as ex:
        list(ex.map(one, todo))
    print('完了', len(todo), '失敗', len(errs), errs[:10], flush=True)


# ───────────────────────── 解析の一括・会社ごとの台帳 ─────────────────────────
PARSED = os.path.join(EXD, 'parsed_v2.jsonl.gz')


def _parse_path(f):
    p = raw_path(f['acc'])
    if not os.path.exists(p):
        return None
    try:
        d = json.loads(gzip.open(p).read())
    except Exception:  # noqa
        return {'acc': f['acc'], 'broken': True}
    try:
        return parse_filing(f, d)
    except Exception as e:  # noqa
        return {'acc': f['acc'], 'parse_error': str(e)[:200]}


def parse_all(force=False):
    if os.path.exists(PARSED) and not force:
        return
    from multiprocessing import Pool
    fl = [f for f in filing_list() if CRAWL_FROM <= f['filed'] <= CRAWL_TO or (CRAWL_TO < f['filed'] <= NEXT_TO and os.path.exists(raw_path(f['acc'])))]
    n = 0
    with Pool(4) as pool, gzip.open(PARSED + '.tmp', 'wt') as g:
        for r in pool.imap(_parse_path, fl, chunksize=64):
            if r is not None:
                g.write(json.dumps(r) + '\n'); n += 1
    os.replace(PARSED + '.tmp', PARSED)
    print('解析', n, '件', flush=True)


def load_parsed():
    parse_all()
    return [json.loads(l) for l in gzip.open(PARSED, 'rt')]


def fy_label(e):
    """期末 → 会計年度（Fama-French: 1月8日より前に終わる52/53週決算は前年の年度）"""
    d = datetime.date.fromisoformat(e)
    return d.year if (d.month, d.day) >= (1, 8) else d.year - 1


def build_panel_ex27():
    recs = load_parsed()
    panel = {}
    for r in recs:
        if r.get('missing') or r.get('broken') or r.get('parse_error') or not r.get('period'):
            continue
        try:
            r['fy'] = fy_label(r['period'])
        except ValueError:
            continue
        panel.setdefault(r['cik'], []).append(r)
    for c in panel:
        panel[c].sort(key=lambda r: (r['filed'], r['acc']))
    return panel, recs


# ───────────────────────── 信号（EX-27 Article 5） ─────────────────────────
BOUNDS_X = {'gp_at': (-0.5, 3.0), 'op_at': (-1.0, 2.0)}


def cogs_rule(v, REV):
    """売上原価（Compustat の COGS に当たるもの）。FDS の定義では TOTAL-COSTS＝売上・収益に対応する原価（物品＋役務）、
    CGS＝有形の物品の原価。提出者の一部は TOTAL-COSTS に販管費まで入れている（『全費用』）ので、その時だけ CGS を使う。
    どちらも 0/欠測なら欠測（原価 0 と読まない）"""
    TC, CGS, OE, INT, PT = v.get('TOTAL-COSTS'), v.get('CGS'), v.get('OTHER-EXPENSES'), v.get('INTEREST-EXPENSE'), v.get('INCOME-PRETAX')
    tc_pos = TC is not None and TC > 0
    cgs_pos = CGS is not None and CGS > 0
    all_exp = bool(tc_pos and PT is not None and abs(REV - TC - (INT or 0.0) - PT) <= 0.03 * REV and (OE is None or OE <= 0.01 * REV))
    if tc_pos and not all_exp:
        return max(TC, CGS or 0.0), 'TC'
    if all_exp and cgs_pos:
        return CGS, 'CGS(TCは全費用)'
    if not tc_pos and cgs_pos:
        return CGS, 'CGS'
    return None, ('全費用でCGSなし' if all_exp else '原価なし')


def _align(prev_ta, ta):
    """前年の表の単位を今年に合わせる倍率（倍率の表記の欠けで 1000倍ずれることがある）。合わなければ None"""
    if not prev_ta or prev_ta <= 0:
        return None
    for k in (1.0, 1e3, 1e-3, 1e6, 1e-6):
        if 0.25 <= prev_ta * k / ta <= 4:
            return k
    return None


def signals(fd, prev):
    out = {'article': fd['article'] if fd else None}
    if not fd or fd['article'] != '5':
        return out
    v = fd['v']
    TA = v.get('TOTAL-ASSETS')
    if not TA or TA <= 0:
        out['why'] = 'TAなし'
        return out
    REV = v.get('TOTAL-REVENUES')
    if REV is None or REV <= 0:
        s_ = v.get('SALES')
        REV = s_ if (s_ is not None and s_ > 0) else None
    if REV is not None:
        cg, how = cogs_rule(v, REV)
        out['cogs_how'] = how
        if cg is not None:
            x = (REV - cg) / TA
            lo, hi = BOUNDS_X['gp_at']
            if lo <= x <= hi:
                out['gp_at'] = x
            else:
                out['gp_bad'] = x
    PT = v.get('INCOME-PRETAX')
    if PT is not None:
        INT = v.get('INTEREST-EXPENSE') or 0.0
        dar = dinv = dcl = 0.0
        out['prev'] = 'none'
        if prev and prev.get('article') == '5':
            pv = prev['v']
            k = _align(pv.get('TOTAL-ASSETS'), TA)
            if k is not None:
                g = lambda tag: (v.get(tag) if v.get(tag) is not None else None, pv.get(tag) * k if pv.get(tag) is not None else None)
                a1, a0 = g('RECEIVABLES'); i1, i0 = g('INVENTORY'); c1, c0 = g('CURRENT-LIABILITIES')
                dar = (a1 - a0) if (a1 is not None and a0 is not None) else 0.0      # 欠けた増減は 0（Ball et al. の作法・事前登録）
                dinv = (i1 - i0) if (i1 is not None and i0 is not None) else 0.0
                dcl = (c1 - c0) if (c1 is not None and c0 is not None) else 0.0
                out['prev'] = 'ok' if k == 1.0 else 'ok_rescaled'
            else:
                out['prev'] = 'unit_mismatch'
        x = (PT + INT - dar - dinv + dcl) / TA
        lo, hi = BOUNDS_X['op_at']
        if lo <= x <= hi:
            out['op_at'] = x
        else:
            out['op_bad'] = x
    return out


def ta_dollars(fd, cover):
    """総資産のドル額（倍率の表記が無い表は 1株利益×表紙の株数 ≈ 純利益 で桁を決める）。決まらなければ None"""
    if not fd or not fd['v'].get('TOTAL-ASSETS'):
        return None
    v = fd['v']
    TA = v['TOTAL-ASSETS']
    if fd['mult'] and fd['mult'] != 1.0:
        return TA
    ni = v.get('NET-INCOME')
    eps = v.get('EPS-PRIMARY') or v.get('EPS-BASIC') or v.get('EPS-DILUTED')
    sh = cover.get('shares')
    if ni and eps and sh and abs(eps) >= 0.02:
        best = min((abs(math.log(abs(ni * s_) / abs(eps * sh))), s_) for s_ in (1.0, 1e3, 1e6))
        if best[0] <= math.log(3):
            return TA * best[1]
    return None


# ───────────────────────── 形成（t 年7月）に使う値 ─────────────────────────
YEARS_X = list(range(1996, 2002))
LAST_FDS_YEAR = 2001      # EX-27 は 2001年に廃止: 2001年の形成だけ、信号は6月末までに出た最新の年次の表（FY1999 か FY2000）


def _fdate(d, filed):
    """表紙の日付（浮動株の基準日）。無い・壊れている・提出日の400日前〜10日後の外なら提出日"""
    if d and _valid_date(d):
        dd = (datetime.date.fromisoformat(filed) - datetime.date.fromisoformat(d)).days
        if -10 <= dd <= 400:
            return d
    return filed


def formation(fil, t):
    """会社の提出一覧 fil → t 年7月の形成に使う値（無ければ None）"""
    cutoff = f'{t}-06-30'
    ks = [r for r in fil if r['fy'] == t - 1 and r['filed'] <= cutoff]
    if not ks:
        return None
    withf = [r for r in ks if r['cover'].get('float')]
    r = (withf or ks)[-1]
    out = {'acc': r['acc'], 'filed': r['filed'], 'period': r['period'], 'name': r['name'], 'sic_hdr': r.get('sic'),
           'float': r['cover'].get('float'), 'float_date': _fdate(r['cover'].get('float_date'), r['filed']),
           'shares': r['cover'].get('shares'), 'price_cover': r['cover'].get('price'),
           'symbols': list(dict.fromkeys(sum([x.get('symbols') or [] for x in ks], []))), 'sros': r.get('sros')}
    # 信号の表
    sig_r = r if r.get('fds') else None
    if sig_r is None:
        alt = [x for x in ks if x.get('fds')]
        sig_r = alt[-1] if alt else None
    if sig_r is None and t == LAST_FDS_YEAR:
        alt = [x for x in fil if x.get('fds') and x['fy'] in (t - 1, t - 2) and x['filed'] <= cutoff]
        sig_r = alt[-1] if alt else None
        out['sig_stale'] = bool(sig_r)
    out['fds'] = sig_r['fds'] if sig_r else None
    out['sig_fy'] = sig_r['fy'] if sig_r else None
    out['sig_acc'] = sig_r['acc'] if sig_r else None
    prev = None
    if sig_r:
        pk = [x for x in fil if x['fy'] == sig_r['fy'] - 1 and x.get('fds') and x['filed'] <= sig_r['filed']]
        if pk:
            prev = pk[-1]['fds']
        elif sig_r.get('fds_prev_restated'):
            prev = sig_r['fds_prev_restated']
    out['sig'] = signals(out['fds'], prev)
    out['ta_d'] = ta_dollars(out['fds'], r['cover']) if out['fds'] else None
    # 翌年の表紙（生き残りを含む年次の近似リターン用）
    nx = [x for x in fil if x['fy'] == t and x['cover'].get('float') and x['filed'] > r['filed']]
    if nx:
        n1 = nx[0]
        out['next'] = {'float': n1['cover']['float'], 'float_date': _fdate(n1['cover'].get('float_date'), n1['filed']),
                       'shares': n1['cover'].get('shares'), 'filed': n1['filed'], 'acc': n1['acc']}
    out['prev_float'] = None
    pf = [x for x in fil if x['fy'] == t - 2 and x['cover'].get('float')]
    if pf:
        out['prev_float'] = pf[-1]['cover']['float']
    return out


# ───────────────────────── 母集団（価格・ティッカーの当て方と検算） ─────────────────────────
import mw_sec_replication as SR      # 同じ形（T3VW・T20EW・T5EW・IN_T3SM・M100）を同じ実装で作るために読むだけ（書き換えない）

TOPRAW_X = 2500     # 価格のある社が500社に届くまで下る（事前登録: 『価格のある社の中の浮動株の上位500』）
N_UNI = 500


def _ysym(s):
    return s.replace('.', '-').replace('/', '-').upper()


def _yahoo(x):
    try:
        return SR.yahoo_series(x)
    except Exception:  # noqa
        return None


def link_price(rec, cik, t, cands, price):
    """ティッカーの候補を順に試し、表紙の浮動株と Yahoo の生の株価×表紙の株数で検算して最初に通ったものを返す。
    q = 浮動株 ÷（表紙の発行済株数 × 浮動株の基準月の生の株価）。
    整合（CIK が今の一覧に載り、社名か本文の銘柄コードが一致）: 0.2 ≤ q ≤ 1.1。それ以外（社名で当てた・本文のコードで当てた・
    CIK は同じだが社名もコードも違う）: 0.75 ≤ q ≤ 1.1（別の会社の株価を当てる誤りを避ける）。株数が無ければ整合のときだけ検算なしで使う"""
    jm = t * 100 + 6
    fm = SR._float_month(rec['float_date'])
    tried = []
    for x, via, consistent in cands:
        v = price.get(x)
        if v is None:
            tried.append((x, via, 'no_yahoo')); continue
        ret, cl, first, spl = v
        if not (jm in cl and fm in cl and SR._nextm(jm) in ret):
            tried.append((x, via, 'no_price_at_t')); continue
        S_ = rec.get('shares')
        if S_:
            q = rec['float'] / (S_ * cl[fm] * SR.split_after(spl, fm))
            lo, hi = (0.2, 1.25) if (via == 'cik' and consistent) else (0.75, 1.1)
            if lo <= q <= hi:
                return {'ticker': x, 'via': via, 'q': round(q, 3), 'check': 'q', 'fcap': rec['float'] * cl[jm] / cl[fm]}, tried
            tried.append((x, via, f'q={q:.2f}'))
        else:
            if via == 'cik' and consistent:
                return {'ticker': x, 'via': via, 'q': None, 'check': 'unchecked', 'fcap': rec['float'] * cl[jm] / cl[fm]}, tried
            tried.append((x, via, 'no_shares'))
    return None, tried


def float_sane(rec):
    fl = rec.get('float')
    if not fl or fl <= 0 or fl > 1.5e12:
        return False
    if rec.get('shares') and not (0.05 <= fl / rec['shares'] <= 2000):
        return False                                           # 浮動株÷発行済株数（≒株価）が 5セント〜2,000ドルの外は桁違い
    if rec.get('ta_d') and fl > 200 * rec['ta_d']:
        return False
    pf = rec.get('prev_float')
    if pf and not (1 / 20 <= fl / pf <= 20):
        return False
    return True


def _nkey(name):
    """社名の比較用の鍵: SR.norm_name の語を並べ替えて空白なしで連結（WALT DISNEY ↔ DISNEY WALT）"""
    return ''.join(sorted(SR.norm_name(name).split()))


def _name_close(a, b):
    """同じ CIK の昔の名前と今の名前が近いか: 語の並べ替えで一致・片方が他方の頭（WALMARTSTORES ↔ WALMART）・4字以上の最初の語が同じ"""
    na, nb = SR.norm_name(a), SR.norm_name(b)
    if not na or not nb:
        return False
    ka, kb = na.replace(' ', ''), nb.replace(' ', '')
    if _nkey(a) == _nkey(b) or (min(len(ka), len(kb)) >= 4 and (ka.startswith(kb) or kb.startswith(ka))):
        return True
    fa, fb = na.split()[0], nb.split()[0]
    return len(fa) >= 4 and fa == fb


def build_universe_x(panel, verbose=True):
    tk, title = SR.ticker_map()
    tk_cik = {}
    for c, x in tk.items():
        tk_cik.setdefault(_ysym(x), c)
    by_norm = {}
    for c, ttl in title.items():
        by_norm.setdefault(_nkey(ttl), set()).add(c)
    in_panel = set(panel)
    ff12 = SR.ff12_fn()
    F = {t: {} for t in YEARS_X}
    for c, fil in panel.items():
        for t in YEARS_X:
            r = formation(fil, t)
            if r and r.get('float'):
                F[t][c] = r
    # SIC: その年の SEC ヘッダ → 同じ社の他の提出のヘッダ → 今の SIC（SEC submissions）
    hdr_sic = {}
    for c, fil in panel.items():
        ss = [x['sic'] for x in fil if x.get('sic')]
        if ss:
            hdr_sic[c] = ss[-1]
    top = {}
    for t in YEARS_X:
        el = [(c, r) for c, r in F[t].items() if float_sane(r)]
        el.sort(key=lambda z: -z[1]['float'])
        top[t] = el[:TOPRAW_X]
    need = sorted({c for t in YEARS_X for c, _ in top[t] if not (F[t][c].get('sic_hdr') or hdr_sic.get(c))}, key=int)
    cur_sic = SR.sic_codes(need) if need else {}
    def sic_of(c, r):
        return r.get('sic_hdr') or hdr_sic.get(c) or cur_sic.get(c) or ''
    # 候補ティッカー
    names = {c: sorted({x['name'] for x in fil}) for c, fil in panel.items()}
    syms_all = {c: [_ysym(y) for x in fil for y in (x.get('symbols') or [])] for c, fil in panel.items()}
    cands = {}
    for t in YEARS_X:
        for c, r in top[t]:
            syms = list(dict.fromkeys([_ysym(x) for x in r.get('symbols') or []] + syms_all.get(c, [])))
            out = []
            if c in tk:
                cons = any(_name_close(nm, title[c]) for nm in names.get(c, [r['name']])) or (_ysym(tk[c]) in syms)
                out.append((_ysym(tk[c]), 'cik', bool(cons)))
            # 社名（この社が 1995〜2001 に使った名前のどれか）で今の一覧の1社とだけ一致し、その社が 1995〜2001 に別の会社として提出していない
            hits = set()
            for nm in names.get(c, [r['name']]):
                hits |= {x for x in by_norm.get(_nkey(nm), set()) if x != c}
            if len(hits) == 1:
                y = _ysym(tk[next(iter(hits))])
                if y not in [o[0] for o in out]:
                    out.append((y, 'name', False))
            # 本文の銘柄コード（『under the symbol』）だけで当てる道は使わない（他社のコードを拾う誤りがある: 例 Signet の本文の COF）。
            # コードは CIK で当てた候補の『整合』の判定にだけ使う
            cands[(c, t)] = out
    tickers = sorted({x for v in cands.values() for x, _, _ in v})
    price = {}
    with ThreadPoolExecutor(3) as ex:
        for i, (x, v) in enumerate(zip(tickers, ex.map(_yahoo, tickers))):
            price[x] = v
            if verbose and i % 500 == 0:
                print(f'  Yahoo {i}/{len(tickers)}', flush=True)
    uni, diag = {}, {}
    for t in YEARS_X:
        rows, st = [], {}
        for pos, (c, r) in enumerate(top[t]):
            sc = sic_of(c, r)
            r['_sic'] = sc
            if sc in SR.EXCL_SIC:
                r['_status'] = 'excluded_sic'
                continue
            got, tried = link_price(r, c, t, cands[(c, t)], price)
            r['_status'] = 'ok' if got else ('no_ticker' if not cands[(c, t)] else (tried[-1][2] if tried else 'no_ticker'))
            r['_tried'] = tried; r['_sic'] = sc; r['_rawpos'] = pos
            if not got:
                continue
            fc = got['fcap']
            if fc > 6e12 or (r.get('ta_d') and fc > 200 * r['ta_d']):
                r['_status'] = 'fcap_insane'; continue
            dup = [q for q in rows if q['ticker'] == got['ticker']]
            if dup:   # 同じティッカーを2社が名乗る（例: 1996年の Merck〔名前で MRK〕と Schering-Plough〔CIK で MRK〕）→ 株価の水準が合う方（|log q| が小さい方）
                old = dup[0]
                key = lambda z: abs(math.log(z['q'])) if z.get('q') else 9.0
                if key(old) <= key(got):
                    r['_status'] = 'dup_ticker'; continue
                rows.remove(old)
                for c0, r0 in top[t]:
                    if c0 == old['cik']:
                        r0['_status'] = 'dup_ticker'; r0.pop('_ticker', None)
            sg = r['sig']
            r['_ticker'] = got['ticker']
            rows.append({'cik': c, 'ticker': got['ticker'], 'via': got['via'], 'q': got['q'], 'check': got['check'], 'fcap': fc,
                         'sic': sc, 'ff12': ff12(sc) if sc else None, 'rawpos': pos, 'filed': r['filed'], 'name': r['name'],
                         'gp_at': sg.get('gp_at'), 'op_at': sg.get('op_at'), 'article': sg.get('article'), 'prev': sg.get('prev'),
                         'cogs_how': sg.get('cogs_how'), 'sig_fy': r.get('sig_fy'), 'sig_stale': r.get('sig_stale', False)})
        rows.sort(key=lambda z: -z['fcap'])
        uni[t] = {z['cik']: z for z in rows[:N_UNI]}
        diag[t] = {'n_formation_with_float': len(F[t]), 'n_sane': sum(1 for r in F[t].values() if float_sane(r)),
                   'priced_ok': len(rows), 'universe_n': len(uni[t]),
                   'fcap_500th_bn': round(rows[N_UNI - 1]['fcap'] / 1e9, 2) if len(rows) >= N_UNI else None,
                   'rawpos_max_in_universe': max(z['rawpos'] for z in uni[t].values()) if uni[t] else None}
    return uni, diag, F, top, price, cands


def raw500_status(top, t):
    """浮動株そのままの上位500（除外 SIC を除く）の状態の内訳（価格を問わない）"""
    rows = [(c, r) for c, r in top[t] if r.get('_sic', '') not in SR.EXCL_SIC][:500]
    st = {}
    fl_tot = sum(r['float'] for _, r in rows); fl_ok = sum(r['float'] for _, r in rows if r.get('_status') == 'ok')
    for _, r in rows:
        k = r.get('_status', '?')
        k = 'q_fail' if k.startswith('q=') else k
        st[k] = st.get(k, 0) + 1
    return {'n': len(rows), 'status': st, 'float_share_ok': round(fl_ok / fl_tot, 3) if fl_tot else None}


def coverage():
    """被覆だけを数える（リターンは計算しない）"""
    panel, recs = build_panel_ex27()
    print('解析した提出', len(recs), '・会社', len(panel))
    from collections import Counter
    uni, diag, F, top, price, cands = build_universe_x(panel)
    for t in YEARS_X:
        u = uni[t]
        R = {c: z for c, z in u.items() if z.get('ff12') and z['ff12'] != 'Money'}
        print(t, diag[t], raw500_status(top, t))
        print('   rankable', len(R), 'gp_at', sum(1 for z in R.values() if z['gp_at'] is not None), 'op_at', sum(1 for z in R.values() if z['op_at'] is not None),
              'article', Counter(z['article'] for z in R.values()).most_common(6), 'prev', Counter(z['prev'] for z in R.values()).most_common(5),
              'cogs', Counter(z['cogs_how'] for z in R.values()).most_common(5), 'stale', sum(1 for z in R.values() if z['sig_stale']),
              'via', Counter(z['via'] for z in u.values()), 'check', Counter(z['check'] for z in u.values()))
        big = [(c, r) for c, r in top[t]][:40]
        print('   上位40（浮動株そのまま）:', '; '.join(f"{r['name'][:18]}={r.get('_status')}" for c, r in big))


# ───────────────────────── 銘柄選び（mw_sec_replication と同じ形） ─────────────────────────
SIGX = ['gp_at', 'op_at']
PAIR = {'gp_at': 'gp_at', 'op_at': 'cop_at'}     # 2010-2026 の対（op_at は cop_at の代理）
FORMS_X = ['T3VW', 'M100_T3VW', 'T20EW', 'T5EW', 'IN_T3SM']
PRIMARY_X = [f'{k}_{f}' for k in SIGX for f in FORMS_X]
SECONDARY_X = ['gp_at_T3VW_exBusEq', 'op_at_T3VW_exBusEq']
EXPLORE_X = ['gp_at_T50EW', 'op_at_T50EW', 'op_at_T10EW', 'op_at_M50_T3VW', 'op_at_M200_T3VW', 'op_at_M100_IN_T3SM']   # 探索の族（同時に登録・測る前）
PRIM_B = {nm: ('U_exfin_exBusEq' if 'exBusEq' in nm else 'M100_exfin' if 'M100_IN' in nm else 'M100' if 'M100' in nm else 'M50' if 'M50_' in nm
               else 'M200' if 'M200' in nm else 'U_all') for nm in PRIMARY_X + SECONDARY_X + EXPLORE_X}
TESTED_2010 = {'gp_at_T3VW', 'gp_at_M100_T3VW', 'gp_at_T20EW', 'gp_at_T5EW', 'cop_at_T3VW', 'cop_at_M100_T3VW', 'cop_at_T20EW',
               'cop_at_T5EW', 'cop_at_IN_T3SM', 'cop_at_T3VW_exBusEq',
               'gp_at_T50EW', 'cop_at_T50EW', 'cop_at_T10EW', 'cop_at_M50_T3VW', 'cop_at_M200_T3VW', 'cop_at_M100_IN_T3SM'}   # 2010-2026 で既に測った形（out/mw_sec_replication.json）
START_X, END_X = 199607, 200206


def pair_name(nm):
    k = nm.split('_')[0] + '_' + nm.split('_')[1]
    return PAIR[k] + nm[len(k):]


def scores_x(u):
    R = {c: r for c, r in u.items() if r.get('ff12') and r['ff12'] != 'Money'}
    out, z = {}, {}
    for k in SIGX:
        vals = {c: r[k] for c, r in R.items() if r.get(k) is not None}
        out[k] = vals; z[k] = SR.rank_z(vals)
    out['_z'] = z
    return R, out


def in_t3sm(u, R, base):
    """業種中立（SR.cohorts_for と同じ）: SIC2桁（5社以上）か FF12 の群で得点を中立化 → FF12 業種ごとに上位 ⌈n/3⌉・業種の中は時価加重・
    業種の重みは順位づけの対象（金融以外）の浮動株時価の業種比（選ばれた業種で按分し直す）"""
    ne = SR.neutral(base, R)
    indw = {}
    for c in R:
        indw[R[c]['ff12']] = indw.get(R[c]['ff12'], 0.0) + u[c]['fcap']
    sel = {}
    for c in ne:
        sel.setdefault(R[c]['ff12'], []).append(c)
    wsum = sum(indw[g] for g in sel)
    w = {}
    for g, cs in sel.items():
        cs = sorted(cs, key=lambda c: (-ne[c], -u[c]['fcap']))
        pick = cs[:max(1, math.ceil(len(cs) / 3))]
        tot = sum(u[c]['fcap'] for c in pick)
        for c in pick:
            w[u[c]['ticker']] = indw[g] / wsum * u[c]['fcap'] / tot
    return w


def m100_in(m100, R, sig):
    """上位100社の中の業種中立（mw_sec_replication run3 の cop_at_M100_IN_T3SM と同じ: 信号の値そのもので FF12 業種ごとに上位 ⌈n/3⌉・
    業種の中は時価加重・業種の重みは上位100社の金融以外の業種比）"""
    indw, grp = {}, {}
    for c in R:
        indw[R[c]['ff12']] = indw.get(R[c]['ff12'], 0.0) + m100[c]['fcap']
    for c in sig:
        grp.setdefault(R[c]['ff12'], []).append(c)
    wsum = sum(indw[g] for g in grp)
    w = {}
    for g, cs in grp.items():
        cs = sorted(cs, key=lambda c: (-sig[c], -m100[c]['fcap']))
        pick = cs[:max(1, math.ceil(len(cs) / 3))]
        tot = sum(m100[c]['fcap'] for c in pick)
        for c in pick:
            w[m100[c]['ticker']] = indw[g] / wsum * m100[c]['fcap'] / tot
    return w


def cohorts_x(uni):
    C, info = {}, {'n_rankable': {}, 'n_signal': {}, 'tech_share': {}, 'top5': {}}
    for t in YEARS_X:
        u = uni[t]
        R, sc = scores_x(u)
        info['n_rankable'][t] = len(R)
        info['n_signal'][t] = {k: len(sc[k]) for k in SIGX}
        put = lambda nm, w: C.setdefault(nm, {}).__setitem__(t, w) if w else None
        m100 = SR.mk(u, 100)
        Rm, scm = scores_x(m100)
        ux = {c: r for c, r in u.items() if r.get('ff12') and r['ff12'] not in ('Money', 'BusEq')}
        Rx, scx = scores_x(ux)
        for k in SIGX:
            put(f'{k}_T3VW', SR._w(u, SR.top_by(sc[k], u, frac=1 / 3), True))
            put(f'{k}_T20EW', SR._w(u, SR.top_by(sc[k], u, n=20), False))
            put(f'{k}_T5EW', SR._w(u, SR.top_by(sc[k], u, n=5), False))
            put(f'{k}_IN_T3SM', in_t3sm(u, R, sc['_z'][k]))
            put(f'{k}_M100_T3VW', SR._w(m100, SR.top_by(scm[k], m100, frac=1 / 3), True))
            put(f'{k}_T3VW_exBusEq', SR._w(ux, SR.top_by(scx[k], ux, frac=1 / 3), True))
        # 探索の族（mw_sec_replication の prereg2・prereg3 と同じ形）
        m50, m200 = SR.mk(u, 50), SR.mk(u, 200)
        R50, sc50 = scores_x(m50); R200, sc200 = scores_x(m200)
        for k in SIGX:
            put(f'{k}_T50EW', SR._w(u, SR.top_by(sc[k], u, n=50), False))
            put(f'{k}_T10EW', SR._w(u, SR.top_by(sc[k], u, n=10), False))
            put(f'{k}_M50_T3VW', SR._w(m50, SR.top_by(sc50[k], m50, frac=1 / 3), True))
            put(f'{k}_M200_T3VW', SR._w(m200, SR.top_by(sc200[k], m200, frac=1 / 3), True))
            put(f'{k}_M100_IN_T3SM', m100_in(m100, Rm, scm[k]))
        put('M50', SR._w(m50, list(m50), True))
        put('M200', SR._w(m200, list(m200), True))
        put('M100_exfin', SR._w(m100, list(Rm), True))
        info['top5'][t] = {k: [u[c]['ticker'] for c in SR.top_by(sc[k], u, n=5)] for k in SIGX}
        put('U_all', SR._w(u, list(u), True))
        put('U_exfin', SR._w(u, list(R), True))
        put('U_exfin_EW', SR._w(u, list(R), False))
        put('M100', SR._w(m100, list(m100), True))
        put('U_exfin_exBusEq', SR._w(ux, list(ux), True))
        byt = {u[c]['ticker']: c for c in u}
        def share(w):
            tot = sum(w.values())
            return round(sum(v for x, v in w.items() if u[byt[x]].get('ff12') == 'BusEq') / tot, 3) if tot else None
        info['tech_share'][t] = {nm: share(C[nm][t]) for nm in ('gp_at_T3VW', 'op_at_T3VW', 'gp_at_M100_T3VW', 'op_at_M100_T3VW', 'U_all', 'U_exfin', 'M100') if t in C.get(nm, {})}
    return C, info


# ───────────────────────── 2010-2026 の対（mw_sec_replication を同じ実装で作り直す・書き換えない） ─────────────────────────
def sec_series():
    panel = SR.build_panel()
    uni, price, diag, sic, tick = SR.build_universe(panel, fetch=False, verbose=False)
    rets = {x: v[0] for x, v in price.items() if v}
    C, _info = SR.cohorts_for(uni)
    keep = {k: C[k] for k in ('gp_at_T3VW', 'gp_at_T20EW', 'gp_at_T5EW', 'cop_at_T3VW', 'cop_at_T20EW', 'cop_at_T5EW', 'cop_at_IN_T3SM', 'U_all',
                              'gp_at_T50EW', 'cop_at_T50EW')}
    for t in SR.YEARS:
        u = uni[t]
        m100 = SR.mk(u, 100)
        Rm, scm = SR.scores(m100)
        keep.setdefault('gp_at_M100_T3VW', {})[t] = SR._w(m100, SR.top_by(scm['gp_at'], m100, frac=1 / 3), True)
        keep.setdefault('cop_at_M100_T3VW', {})[t] = SR._w(m100, SR.top_by(scm['cop_at'], m100, frac=1 / 3), True)
        keep.setdefault('M100', {})[t] = SR._w(m100, list(m100), True)
        ux = {c: r for c, r in u.items() if r.get('ff12') and r['ff12'] not in ('Money', 'BusEq')}
        Rx, scx = SR.scores(ux)
        keep.setdefault('cop_at_T3VW_exBusEq', {})[t] = SR._w(ux, SR.top_by(scx['cop_at'], ux, frac=1 / 3), True)
        keep.setdefault('U_exfin_exBusEq', {})[t] = SR._w(ux, list(ux), True)
        R, sc = SR.scores(u)
        keep.setdefault('cop_at_T10EW', {})[t] = SR._w(u, SR.top_by(sc['cop_at'], u, n=10), False)
        for kk in (50, 200):
            mm = SR.mk(u, kk)
            Rk, sck = SR.scores(mm)
            keep.setdefault(f'cop_at_M{kk}_T3VW', {})[t] = SR._w(mm, SR.top_by(sck['cop_at'], mm, frac=1 / 3), True)
            keep.setdefault(f'M{kk}', {})[t] = SR._w(mm, list(mm), True)
        keep.setdefault('cop_at_M100_IN_T3SM', {})[t] = m100_in(m100, Rm, scm['cop_at'])
        keep.setdefault('M100_exfin', {})[t] = SR._w(m100, list(Rm), True)
    ser, turn = {}, {}
    for nm, coh in keep.items():
        ser[nm], turn[nm], _d = SR.simulate(coh, rets)
    return ser, turn


# ───────────────────────── 生き残りの偏りの診断 ─────────────────────────
SPLITS = (1.25, 4 / 3, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


def proxy_return(r):
    """表紙の（浮動株 ÷ 発行済株数）の翌年の表紙までの変化＝配当を含まない株価の近似（生き残らなかった会社も翌年の10-Kを出していれば入る）。
    株数が分割の比（±3%）で増えていれば分割として戻す。期間は 300〜430日だけ"""
    n = r.get('next')
    if not n or not r.get('shares') or not n.get('shares'):
        return None, None
    d0, d1 = r['float_date'], n['float_date']
    try:
        span = (datetime.date.fromisoformat(d1) - datetime.date.fromisoformat(d0)).days
    except (ValueError, TypeError):
        return None, None
    if not 300 <= span <= 430:
        return None, None
    p0 = r['float'] / r['shares']; p1 = n['float'] / n['shares']
    k = n['shares'] / r['shares']
    adj = 1.0
    for sp in SPLITS:
        if abs(k / sp - 1) <= 0.03:
            adj = sp; break
    g = p1 * adj / p0 - 1
    if not -0.95 <= g <= 10:
        return None, None
    return g, (d0, d1)


def survivorship(F, top, uni, price):
    out = {'by_year': {}, 'missing_by_tercile': {}, 'proxy_test': {}}
    for t in YEARS_X:
        rows = [(c, r) for c, r in top[t] if r.get('_sic', '') not in SR.EXCL_SIC][:500]
        out['by_year'][t] = raw500_status(top, t)
        ff12 = SR.ff12_fn()
        nonfin = [(c, r) for c, r in rows if r.get('_sic') and ff12(r['_sic']) != 'Money']
        for k in SIGX:
            sc = [(c, r) for c, r in nonfin if r['sig'].get(k) is not None]
            sc.sort(key=lambda z: z[1]['sig'][k])
            n = len(sc)
            ters = {'low': sc[:n // 3], 'mid': sc[n // 3:2 * n // 3], 'high': sc[2 * n // 3:]}
            d = {}
            for nm, grp in ters.items():
                ft = sum(r['float'] for _, r in grp)
                d[nm] = {'n': len(grp), 'missing_n': sum(1 for _, r in grp if r.get('_status') != 'ok'),
                         'missing_float_share': round(sum(r['float'] for _, r in grp if r.get('_status') != 'ok') / ft, 3) if ft else None,
                         'no_next_10k': sum(1 for _, r in grp if not r.get('next'))}
            out['missing_by_tercile'].setdefault(k, {})[t] = d
    return out


def proxy_spreads(F, top, price, uni):
    """生き残りを含む年次の近似の検定（報告・格付けしない）: 浮動株そのままの上位500（価格を問わない）で、信号の上位1/3（浮動株加重）−
    全体（浮動株加重）の『表紙の株価の近似』の変化の差。価格のある社だけで同じことをした版・Yahoo の株価／総リターンで測った版と並べる。
    翌年の10-Kが無い（1年以内に消えた）社は上下の境界で埋める"""
    ff12 = SR.ff12_fn()
    res = {}
    for k in SIGX:
        per = {}
        for t in YEARS_X:
            rows = [(c, r) for c, r in top[t] if r.get('_sic', '') not in SR.EXCL_SIC][:500]
            tick = {}
            for c, r in rows:
                if r.get('_status') == 'ok':
                    tick[c] = uni_ticker(r, c, t, price)
            nonfin = [(c, r) for c, r in rows if r.get('_sic') and ff12(r['_sic']) != 'Money' and r['sig'].get(k) is not None]
            nonfin.sort(key=lambda z: (-z[1]['sig'][k], -z[1]['float']))
            topset = {c for c, _ in nonfin[:len(nonfin) // 3]}
            def gy(c, r, kind):
                x = tick.get(c)
                g, span = proxy_return(r)
                if x is None or span is None or price.get(x) is None:
                    return None
                ret, cl, first, spl = price[x]
                m0, m1 = SR._float_month(span[0]), SR._float_month(span[1])
                if kind == 'px':
                    return cl[m1] / cl[m0] - 1 if (m0 in cl and m1 in cl) else None
                ms, m = [], SR._nextm(m0)
                while m <= m1:
                    if m not in ret:
                        return None
                    ms.append(ret[m]); m = SR._nextm(m)
                return math.prod(1 + v for v in ms) - 1 if ms else None
            def spread(sel_rows, val):
                num_t = den_t = num_u = den_u = 0.0
                for c, r in sel_rows:
                    v = val(c, r)
                    if v is None:
                        continue
                    num_u += r['float'] * v; den_u += r['float']
                    if c in topset:
                        num_t += r['float'] * v; den_t += r['float']
                if not den_t or not den_u:
                    return None
                return num_t / den_t - num_u / den_u
            priced = [(c, r) for c, r in rows if c in tick]
            d = {'all_proxy': spread(rows, lambda c, r: proxy_return(r)[0]),
                 'priced_proxy': spread(priced, lambda c, r: proxy_return(r)[0] if proxy_return(r)[0] is not None and gy(c, r, 'px') is not None else None),
                 'priced_yahoo_price': spread(priced, lambda c, r: gy(c, r, 'px') if proxy_return(r)[0] is not None else None),
                 'priced_yahoo_total': spread(priced, lambda c, r: gy(c, r, 'tr') if proxy_return(r)[0] is not None else None)}
            gone = [(c, r) for c, r in rows if not r.get('next')]
            base = [(c, r) for c, r in rows if proxy_return(r)[0] is not None]
            def bound(lo_top, hi_other):
                return spread(base + gone, lambda c, r: proxy_return(r)[0] if r.get('next') else (lo_top if c in topset else hi_other))
            d['bound_low'] = bound(-1.0, 0.5)
            d['bound_high'] = bound(0.5, -1.0)
            d['n'] = {'rows': len(rows), 'with_proxy': len(base), 'gone_no_next_10k': len(gone), 'priced': len(priced),
                      'gone_float_share': round(sum(r['float'] for _, r in gone) / sum(r['float'] for _, r in rows), 3) if rows else None}
            # 近似と Yahoo の株価の一致（価格のある社）
            pairs = [(proxy_return(r)[0], gy(c, r, 'px')) for c, r in priced]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if len(pairs) >= 20:
                d['proxy_vs_yahoo_price'] = {'n': len(pairs), 'corr': round(M.corr([a for a, _ in pairs], [b for _, b in pairs]), 3),
                                             'median_abs_diff': round(sorted(abs(a - b) for a, b in pairs)[len(pairs) // 2], 3)}
            per[t] = {kk: (round(v * 100, 2) if isinstance(v, float) else v) for kk, v in d.items()}
        summ = {}
        for kk in ('all_proxy', 'priced_proxy', 'priced_yahoo_price', 'priced_yahoo_total', 'bound_low', 'bound_high'):
            xs = [per[t][kk] for t in YEARS_X if per[t].get(kk) is not None]
            if xs:
                m_ = S.mean(xs); sd = S.stdev(xs) if len(xs) > 1 else None
                summ[kk] = {'mean_pct_per_year': round(m_, 2), 't_across_years': round(m_ / (sd / math.sqrt(len(xs))), 2) if sd else None, 'years': len(xs)}
        res[k] = {'per_year': per, 'summary': summ}
    return res


def uni_ticker(r, c, t, price):
    return r.get('_ticker')


# ───────────────────────── 集計・判定 ─────────────────────────
PRE_NAME = 'mw_ex27_prereg.json'
OUT_NAME = 'mw_ex27.json'
COST = 0.001
WINDOWS = {'full': (199607, 200206), 'clean_1996_2000_formations': (199607, 200106), 'runup_1996_07_2000_06': (199607, 200006),
           'bust_2000_07_2002_06': (200007, 200206)}
DESC_X = {'gp_at': '粗利÷総資産（Novy-Marx 2013・EX-27: 売上−原価〔TOTAL-COSTS、全費用なら CGS〕）', 'op_at': '営業収益性の代理（税引前利益＋利払い−Δ売掛金−Δ棚卸資産＋Δ流動負債）÷総資産〔償却・研究開発費の足し戻しは EX-27 に無い＝代理〕',
          'T3VW': '上位1/3・浮動株時価加重', 'M100_T3VW': '浮動株時価の上位100社の中の上位1/3・時価加重（相手 M100）', 'T20EW': '上位20社・等分',
          'T5EW': '上位5社・等分', 'IN_T3SM': '業種中立: FF12業種ごとに上位1/3（SIC2桁で中立化）・業種の重みは母集団（金融除く）と同じ',
          'T3VW_exBusEq': '技術（FF12 BusEq）と金融を除いた上位1/3・時価加重（相手 U_exfin_exBusEq）',
          'T50EW': '上位50社・等分', 'T10EW': '上位10社・等分', 'M50_T3VW': '上位50社の中の上位1/3・時価加重（相手 M50）',
          'M200_T3VW': '上位200社の中の上位1/3・時価加重（相手 M200）', 'M100_IN_T3SM': '上位100社の中の業種中立（FF12ごとに上位1/3・相手 M100_exfin）'}


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def desc_x(nm):
    k = nm.split('_')[0] + '_' + nm.split('_')[1]
    return DESC_X[k] + '／' + DESC_X[nm[len(k) + 1:]]


def stats_x(sr, b, turn=None):
    d = {w: M.excess_stats(sr, b, a, z) for w, (a, z) in WINDOWS.items()}
    if turn is not None:
        d['net_cost_full'] = M.excess_stats(M.apply_cost(sr, turn, COST), b, START_X, END_X)
    d['roll20'] = None; d['dca20'] = None       # 6年しかない（転がる20年窓・20年積立は作れない）
    return d


def annual(sr, t):
    ms = [m for m in SR.hold_months(t) if m in sr]
    return round((math.prod(1 + sr[m] for m in ms) - 1) * 100, 2) if ms else None


def run():
    t0 = time.time()
    pre = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
    panel, recs = build_panel_ex27()
    uni, diag, F, top, price, cands = build_universe_x(panel, verbose=False)
    rets = {x: v[0] for x, v in price.items() if v}
    C, info = cohorts_x(uni)
    ser, turn, drops = {}, {}, {}
    for nm, coh in C.items():
        ser[nm], turn[nm], drops[nm] = SR.simulate(coh, rets)
    spy = SR.yahoo_series('SPY')[0]
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if START_X <= k <= END_X}
    # 2010-2026 の対
    ser10, turn10 = sec_series()
    res, pv_window = {}, {}
    for nm in PRIMARY_X + SECONDARY_X + EXPLORE_X:
        pb = PRIM_B[nm]
        B = {pb: ser[pb], 'U_all': ser['U_all'], 'U_exfin': ser['U_exfin'], 'SPY': spy, 'FF_Mkt': mkt}
        r = {'name': nm, 'primary': nm in PRIMARY_X, 'family': 'primary' if nm in PRIMARY_X else ('secondary_exBusEq' if nm in SECONDARY_X else 'exploratory_X'),
             'description': desc_x(nm), 'primary_benchmark': pb,
             'turnover_oneway_ann': round(turn[nm], 3) if turn[nm] else None, 'n_months': len(ser[nm]), 'dropped_stock_months': drops[nm],
             'cagr': round(M.cagr(ser[nm]) * 100, 2), 'maxdd': round(M.maxdd(ser[nm]) * 100, 1), 'vs': {},
             'annual_jul_jun': {t: annual(ser[nm], t) for t in YEARS_X}}
        for bn, b in B.items():
            r['vs'][bn] = stats_x(ser[nm], b, turn[nm] or 0.0)
        st = r['vs'][pb]['full']
        pv_window[nm] = st['p'] if st else None
        # (1) この窓だけの格（2007年以降が無い＝C2 は構造的に不合格）
        g1, c1 = M.grade(st, st, None, None, cost_hold=None, repl=None, family_holm_p=None)
        r['grade_window_only'] = g1; r['criteria_window_only'] = c1
        # (2) つないだ格と合わせた検定（2010-2026 に同じ形がある時だけ）
        pn = pair_name(nm)
        if pn in TESTED_2010:
            s10, b10 = ser10[pn], ser10[pb]
            h = M.excess_stats(s10, b10, SR.START, SR.END)
            hn = M.excess_stats(M.apply_cost(s10, turn10[pn] or 0.0, COST), b10, SR.START, SR.END)
            cat_s = dict(ser[nm]); cat_s.update(s10)
            cat_b = {k: v for k, v in ser[pb].items() if START_X <= k <= END_X}; cat_b.update({k: v for k, v in b10.items() if SR.START <= k <= SR.END})
            cat = M.excess_stats({k: v for k, v in cat_s.items() if k in cat_b}, cat_b)
            stou = (st['t'] + h['t']) / math.sqrt(2) if (st['t'] is not None and h['t'] is not None) else None
            passed = bool(st['ex_ann'] > 0 and h['ex_ann'] > 0 and cat['t'] is not None and cat['t'] >= 1.65)
            r['pooled'] = {'pair_2010_2026': pn, 'benchmark': pb, 'ex27_window': st, 'xbrl_2010_2026': h, 'xbrl_net_cost': hn,
                           'concatenated': cat, 'stouffer_z_equal_weight': round(stou, 2) if stou is not None else None,
                           'sign_agree_positive': bool(st['ex_ann'] > 0 and h['ex_ann'] > 0), 'pass_prereg': passed}
        res[nm] = r
    # 家族の Holm（この窓の p・主の族10本）と、つないだ格（主の族のうち対がある9本の 2010-2026 の p で Holm）
    hm_w, hm_h, hm_cat = {}, {}, {}
    for fam in (PRIMARY_X, SECONDARY_X, EXPLORE_X):
        hm_w.update(M.holm({k: v for k, v in pv_window.items() if k in fam}))
        pf = [nm for nm in fam if 'pooled' in res[nm]]
        hm_h.update(M.holm({nm: res[nm]['pooled']['xbrl_2010_2026']['p'] for nm in pf}))
        hm_cat.update(M.holm({nm: res[nm]['pooled']['concatenated']['p'] for nm in pf}))
    for nm, r in res.items():
        r['holm_p_window'] = hm_w.get(nm)
        if 'pooled' in r:
            P = r['pooled']
            g2, c2 = M.grade(P['concatenated'], P['ex27_window'], P['xbrl_2010_2026'], None, cost_hold=P['xbrl_net_cost'], repl=None,
                             family_holm_p=hm_h.get(nm))
            r['grade_stitched'] = g2; r['criteria_stitched'] = c2
            P['holm_p_concatenated'] = hm_cat.get(nm)
        r['grade'] = r.get('grade_stitched', r['grade_window_only'])
    # 相手どうし・検算
    refs = {'U_all_vs_FF_Mkt': stats_x(ser['U_all'], mkt), 'U_all_vs_SPY': stats_x(ser['U_all'], spy), 'SPY_vs_FF_Mkt': stats_x(spy, mkt),
            'M100_vs_U_all': stats_x(ser['M100'], ser['U_all']), 'U_exfin_vs_U_all': stats_x(ser['U_exfin'], ser['U_all']),
            'U_exfin_EW_vs_U_exfin': stats_x(ser['U_exfin_EW'], ser['U_exfin']), 'U_exfin_exBusEq_vs_U_all': stats_x(ser['U_exfin_exBusEq'], ser['U_all'])}
    checks = {'french_mkt_cagr_all': round(M.cagr(ff['mkt']) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(ff['mkt'], M.HOLD_START)) * 100, 2),
              'french_mkt_cagr_window': round(M.cagr(mkt) * 100, 2), 'spy_cagr_window': round(M.cagr({k: v for k, v in spy.items() if START_X <= k <= END_X}) * 100, 2),
              'U_all_cagr_window': round(M.cagr(ser['U_all']) * 100, 2), 'months': len(ser['U_all']), 'first': min(ser['U_all']), 'last': max(ser['U_all']),
              'sec_replication_reproduced': {nm: M.excess_stats(ser10[nm], ser10[PRIM_B.get(nm.replace('cop_at', 'op_at'), 'U_all')], SR.START, SR.END)['ex_ann'] for nm in ('gp_at_T3VW', 'cop_at_T3VW')}}
    surv = survivorship(F, top, uni, price)
    prox = proxy_spreads(F, top, price, uni)
    # JKP の同じ窓（CRSP 由来・上場廃止も入る）
    jkp = {}
    mk = M.jkp_mkt('usa', 'vw')
    for key in ('gp_at', 'cop_at', 'op_at'):
        side, p = M.jkp_good_side('usa', key, 'vw', upto=200612)
        jkp[key] = {'good_side': side, **{w: M.excess_stats(p[side], mk, a, z) for w, (a, z) in WINDOWS.items()}}
        mine = res.get(f"{'gp_at' if key == 'gp_at' else 'op_at'}_T3VW")
        if mine:
            act = {m: ser[mine['name']][m] - ser['U_all'][m] for m in ser['U_all'] if m in ser[mine['name']]}
            jact = {m: p[side][m] - mk[m] for m in act if m in p[side] and m in mk}
            ms = sorted(set(act) & set(jact))
            jkp[key]['corr_active_with_mine_T3VW'] = round(M.corr([act[m] for m in ms], [jact[m] for m in ms]), 3) if len(ms) > 24 else None
    tested = []
    for nm, r in res.items():
        tested.append({'name': nm, 'family': r['family'], 'graded': True, 'grade': r['grade']})
    for nm in ('U_exfin', 'U_exfin_EW', 'M100', 'U_exfin_exBusEq'):
        tested.append({'name': nm, 'family': 'benchmark_ref', 'graded': False})
    out = {'angle': 'ex27', 'prereg': PRE_NAME, 'prereg_commit': sha_of('out/' + PRE_NAME),
           'question': pre.get('question'), 'period': [START_X, END_X],
           'train_note': 'この窓（1996-07〜2002-06）は訓練期間（〜2006-12）の中。2007年以降の保有期間は XBRL の窓（mw_sec_replication・2010-07〜2026-08）で、つないだ格はそれを保有期間に使う',
           'tested': tested, 'n_tested': len(tested), 'strategies': res, 'benchmark_refs': refs, 'checks': checks,
           'survivorship': surv, 'survivor_inclusive_proxy': prox, 'jkp_same_window': jkp,
           'coverage': {t: diag[t] for t in YEARS_X}, 'n_rankable': info['n_rankable'], 'n_signal': info['n_signal'],
           'tech_share': info['tech_share'], 'top5': info['top5'],
           'annual_benchmarks': {nm: {t: annual(ser[nm], t) for t in YEARS_X} for nm in ('U_all', 'U_exfin', 'M100', 'U_exfin_exBusEq')} | {'SPY': {t: annual(spy, t) for t in YEARS_X}, 'FF_Mkt': {t: annual(mkt, t) for t in YEARS_X}},
           'runtime_s': round(time.time() - t0)}
    M.save(OUT_NAME, out)
    for nm in PRIMARY_X + SECONDARY_X + EXPLORE_X:
        r = res[nm]; st = r['vs'][r['primary_benchmark']]['full']; P = r.get('pooled') or {}
        print(f"{nm:22s} vs {r['primary_benchmark']:16s} {st['ex_ann']:+6.2f} t{st['t']:+5.2f} cagr差{st['cagr_diff']:+6.2f} | "
              f"2010-26 {(P.get('xbrl_2010_2026') or {}).get('ex_ann')} 連結t {(P.get('concatenated') or {}).get('t')} 合格 {P.get('pass_prereg')} | 格 {r['grade']}", flush=True)
    return out


# ───────────────────────── 探索の族 Y（事前登録2: 生き残りを含む年次の近似で M100・等分の形） ─────────────────────────
PRE2_NAME = 'mw_ex27_prereg2.json'
FAMILY_Y = ['gp_at_M100_T3_proxy', 'op_at_M100_T3_proxy', 'gp_at_T20EW_proxy', 'op_at_T20EW_proxy', 'gp_at_T5EW_proxy', 'op_at_T5EW_proxy']


def _yahoo_span(x, span, price, kind):
    """価格のある社の、近似と同じ期間（表紙の基準月の間）の Yahoo の株価（px）か総リターン（tr）の変化。無ければ None"""
    if x is None or span is None or price.get(x) is None:
        return None
    ret, cl, first, spl = price[x]
    m0, m1 = SR._float_month(span[0]), SR._float_month(span[1])
    if kind == 'px':
        return cl[m1] / cl[m0] - 1 if (m0 in cl and m1 in cl) else None
    ms, m = [], SR._nextm(m0)
    while m <= m1:
        if m not in ret:
            return None
        ms.append(ret[m]); m = SR._nextm(m)
    return math.prod(1 + v for v in ms) - 1 if ms else None


def _select_y(form, k, rows, ff12):
    """rows（浮動株の大きい順）→ (選んだ社 {cik: 重み}, 相手の社 {cik: 重み})。重みは按分前（浮動株か1）"""
    if form == 'M100_T3':
        base = rows[:100]
        nonfin = [(c, r) for c, r in base if r.get('_sic') and ff12(r['_sic']) != 'Money' and r['sig'].get(k) is not None]
        nonfin.sort(key=lambda z: (-z[1]['sig'][k], -z[1]['float']))
        sel = {c: r['float'] for c, r in nonfin[:len(nonfin) // 3]}
        return sel, {c: r['float'] for c, r in base}
    n = {'T20EW': 20, 'T5EW': 5}[form]
    nonfin = [(c, r) for c, r in rows if r.get('_sic') and ff12(r['_sic']) != 'Money' and r['sig'].get(k) is not None]
    nonfin.sort(key=lambda z: (-z[1]['sig'][k], -z[1]['float']))
    return {c: 1.0 for c, _ in nonfin[:n]}, {c: r['float'] for c, r in rows}


def _spread_y(sel, bench, val):
    """選んだ側 − 相手（それぞれ測れる社だけで重みを按分し直す）。どちらかが空なら None"""
    def avg(w):
        num = den = 0.0
        for c, x in w.items():
            v = val(c)
            if v is None:
                continue
            num += x * v; den += x
        return num / den if den else None
    a, b = avg(sel), avg(bench)
    return (a - b) if (a is not None and b is not None) else None


def family_y(top, price):
    ff12 = SR.ff12_fn()
    res = {}
    for nm in FAMILY_Y:
        k = nm.split('_')[0] + '_' + nm.split('_')[1]
        form = nm[len(k) + 1:].replace('_proxy', '')
        per = {}
        for t in YEARS_X:
            rows = [(c, r) for c, r in top[t] if r.get('_sic', '') not in SR.EXCL_SIC][:500]
            R = dict(rows)
            pr = {c: proxy_return(r) for c, r in rows}
            sel, bench = _select_y(form, k, rows, ff12)
            gone = {c for c, r in rows if not r.get('next')}
            d = {'main': _spread_y(sel, bench, lambda c: pr[c][0])}
            # 下限: 選んだ側の消えた社 −100%・相手側だけの消えた社 +50%（選んだ社は相手にも入るので、相手の中の選んだ社も −100%）
            def bound(v_sel, v_other):
                val = lambda c: (v_sel if c in sel else v_other) if c in gone else pr[c][0]
                return _spread_y(sel, bench, val)
            d['bound_low'] = bound(-1.0, 0.5)
            d['bound_high'] = bound(0.5, -1.0)
            # 価格のある社だけで同じ形を作り直す（生き残りの偏り）・同じ社を Yahoo の株価／総リターンで（近似の誤差）
            prow = [(c, r) for c, r in rows if r.get('_status') == 'ok' and r.get('_ticker')]
            psel, pbench = _select_y(form, k, prow, ff12)
            tick = {c: r['_ticker'] for c, r in prow}
            both = lambda c: pr[c][0] is not None and _yahoo_span(tick.get(c), pr[c][1], price, 'px') is not None
            d['priced_proxy'] = _spread_y(psel, pbench, lambda c: pr[c][0] if both(c) else None)
            d['priced_yahoo_price'] = _spread_y(psel, pbench, lambda c: _yahoo_span(tick.get(c), pr[c][1], price, 'px') if both(c) else None)
            d['priced_yahoo_total'] = _spread_y(psel, pbench, lambda c: _yahoo_span(tick.get(c), pr[c][1], price, 'tr') if both(c) else None)
            d['n'] = {'selected': len(sel), 'selected_with_proxy': sum(1 for c in sel if pr[c][0] is not None),
                      'selected_gone_no_next_10k': sum(1 for c in sel if c in gone), 'selected_priced': sum(1 for c in sel if R[c].get('_status') == 'ok'),
                      'bench': len(bench), 'bench_with_proxy': sum(1 for c in bench if pr[c][0] is not None), 'priced_selected': len(psel)}
            d['selected_names'] = [R[c]['name'][:28] for c in sorted(sel, key=lambda c: -sel[c])][:8] if form != 'M100_T3' else None
            per[t] = {kk: (round(v * 100, 2) if isinstance(v, float) else v) for kk, v in d.items()}
        summ = {}
        for kk in ('main', 'bound_low', 'bound_high', 'priced_proxy', 'priced_yahoo_price', 'priced_yahoo_total'):
            xs = [per[t][kk] for t in YEARS_X if per[t].get(kk) is not None]
            if xs:
                m_ = S.mean(xs); sd = S.stdev(xs) if len(xs) > 1 else None
                summ[kk] = {'mean_pct_per_year': round(m_, 2), 't_across_years': round(m_ / (sd / math.sqrt(len(xs))), 2) if sd else None,
                            'years': len(xs), 'positive_years': sum(1 for x in xs if x > 0)}
        res[nm] = {'family': 'exploratory_Y（事前登録2・格付けしない）', 'per_year': per, 'summary': summ}
    return res


def run2():
    t0 = time.time()
    out_p = os.path.join(M.BASE, 'out', OUT_NAME)
    main = json.load(open(out_p))
    panel, recs = build_panel_ex27()
    uni, diag, F, top, price, cands = build_universe_x(panel, verbose=False)
    y = family_y(top, price)
    main['exploratory_prereg2'] = {'prereg': PRE2_NAME, 'prereg_commit': sha_of('out/' + PRE2_NAME), 'graded': False,
                                   'strategies': y, 'runtime_s': round(time.time() - t0)}
    for nm in FAMILY_Y:
        main['tested'].append({'name': nm, 'family': 'exploratory_Y', 'graded': False})
    main['n_tested'] = len(main['tested'])
    M.save(OUT_NAME, main)
    for nm, v in y.items():
        print(nm, json.dumps(v['summary'], ensure_ascii=False))
    return y


# ───────────────────────── 事後の感度（格付けしない）と見出し ─────────────────────────
def summarize():
    """結果を見た後の『事後』の感度（XOM・エネルギーの寄与・EX-27 の原価の定義の注意書きの大きさ）と、見出し・逸脱を JSON に足す"""
    out_p = os.path.join(M.BASE, 'out', OUT_NAME)
    d = json.load(open(out_p))
    panel, recs = build_panel_ex27()
    uni, diag, F, top, price, cands = build_universe_x(panel, verbose=False)
    rets = {x: v[0] for x, v in price.items() if v}
    C, info = cohorts_x(uni)
    bser = {nm: SR.simulate(C[nm], rets)[0] for nm in ('M100', 'U_all')}
    post = {}
    for nm, pb in (('gp_at_M100_T3VW', 'M100'), ('gp_at_T3VW', 'U_all'), ('gp_at_IN_T3SM', 'U_all')):
        for tag, drop in (('ex_XOM', lambda x, t: x == 'XOM'),
                          ('ex_energy', lambda x, t: (lambda z: z and z.get('ff12') == 'Enrgy')(next((u for u in uni[t].values() if u['ticker'] == x), None)))):
            coh = {t: {x: v for x, v in w.items() if not drop(x, t)} for t, w in C[nm].items()}
            sr = SR.simulate(coh, rets)[0]
            post[f'{nm}_{tag}'] = {'vs': pb, 'full': M.excess_stats(sr, bser[pb], START_X, END_X)}
    d['post_hoc_sensitivity'] = {'label': '事後（結果を見た後に足した・格付けしない）',
                                 'why': 'gp_at の M100 形で XOM が最大の保有（12〜19%）。EX-27 の TOTAL-COSTS が石油大手では仕入れ原価だけらしく gp_at が高く出る（事前登録の known_limits に書いた注意）。その注意がどれだけ結果を動かすかを見る（相手はそのまま）',
                                 'results': post}
    S_ = d['strategies']
    pooled = {nm: {'pair': r['pooled']['pair_2010_2026'], 'ex27_ex_ann': r['pooled']['ex27_window']['ex_ann'], 'ex27_t': r['pooled']['ex27_window']['t'],
                   'xbrl_ex_ann': r['pooled']['xbrl_2010_2026']['ex_ann'], 'xbrl_t': r['pooled']['xbrl_2010_2026']['t'],
                   'concat_t': r['pooled']['concatenated']['t'], 'stouffer': r['pooled']['stouffer_z_equal_weight'],
                   'holm_p_concat': r['pooled'].get('holm_p_concatenated'), 'pass': r['pooled']['pass_prereg'], 'family': r['family']}
              for nm, r in S_.items() if 'pooled' in r}
    Y = d.get('exploratory_prereg2', {}).get('strategies', {})
    d['headline'] = {
        'grades': {nm: r['grade'] for nm, r in S_.items()},
        'grade_counts': {g: sum(1 for r in S_.values() if r['grade'] == g) for g in 'SABC'},
        'window_vs_primary_benchmark': {nm: {'bench': r['primary_benchmark'], 'ex_ann': r['vs'][r['primary_benchmark']]['full']['ex_ann'],
                                             't': r['vs'][r['primary_benchmark']]['full']['t'], 'cagr_diff': r['vs'][r['primary_benchmark']]['full']['cagr_diff'],
                                             'holm_p_window': r['holm_p_window']} for nm, r in S_.items()},
        'pooled_test_fixed_in_advance': pooled,
        'pooled_pass_primary': [nm for nm, v in pooled.items() if v['pass'] and v['family'] == 'primary'],
        'pooled_pass_exploratory': [nm for nm, v in pooled.items() if v['pass'] and v['family'] != 'primary'],
        'survivorship_U_all_vs_FF_Mkt': d['benchmark_refs']['U_all_vs_FF_Mkt']['full'],
        'survivor_inclusive_proxy_T3': {k: v['summary'] for k, v in d['survivor_inclusive_proxy'].items()},
        'family_Y_summary': {k: v['summary'] for k, v in Y.items()},
        'jkp_same_window': {k: {'ex_ann': v['full']['ex_ann'], 't': v['full']['t'], 'corr_active_with_mine_T3VW': v.get('corr_active_with_mine_T3VW')} for k, v in d['jkp_same_window'].items()},
        'post_hoc': {k: (v['full']['ex_ann'], v['full']['t']) for k, v in post.items()}}
    d['deviations'] = [
        '前の担当が利用上限で止まり（2026-09-28 18時ごろ UTC）、事前登録はコミット前だった。記録を読み、この窓のリターンが1つも計算されていないことを確かめてから被覆の数え上げを足してコミットした（be70b34）。JKP の同じ窓の数字は課題文の求めで事前に見ている（leak に記載）',
        'EX-27 は FY2000 の 10-K に付いていない（2001年に廃止）ので、2001年7月の形成の信号は多くの社で FY1999（約18か月古い）。事前登録どおり',
        '母集団は『価格のある社の上位500』のため浮動株の順位 2,000〜2,500位まで下る（最小 2〜6億ドル）。mw_sec_replication の上位500より小型寄り',
        'この窓は訓練期間の中で、2007年以降の保有期間は XBRL の窓（2010-07〜2026-08）を使う。2002-07〜2010-06 が空くので転がる20年窓・20年積立は作れない（C4 は構造的に不合格＝つないでも最高 B）',
        '上場廃止した会社の月次株価は取れなかった（stooq は接続が切られる・Alpha Vantage は1日25回・FMP は契約外・Nasdaq Data Link は 403）。代わりに表紙の株価の近似（年次・配当なし）で生き残りを含む版を作った（survivor_inclusive_proxy と探索の族 Y・格付けしない）',
        'mw_sec_replication.yahoo_raw は一時的な失敗が5回続くと『欠測』の印を14日残す（404 と同じ扱い）。今回の取得で失敗は無かったが、再実行で価格が欠ける原因になりうる（mw_common ではなく mw_sec_replication の性質・書き換えていない）',
        '探索の族 Y（事前登録2・0128efe）は主の族・探索の族 X・生き残りの診断を見た後の登録。格付けしない',
        'post_hoc_sensitivity（XOM・エネルギーを除く）は事後で格付けしない']
    M.save(OUT_NAME, d)
    print(json.dumps(d['headline']['post_hoc'], ensure_ascii=False))
    print(json.dumps(d['headline']['grade_counts'], ensure_ascii=False), d['headline']['pooled_pass_primary'], d['headline']['pooled_pass_exploratory'])


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'pilot'
    globals()[cmd]()
