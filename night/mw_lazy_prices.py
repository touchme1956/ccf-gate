#!/usr/bin/env python3
"""night/mw_lazy_prices.py — 角度 lazy_prices（読むだけ・門の判定には不使用）

問い: 年次報告書（10-K）の本文を前年からほとんど書き換えなかった S&P500 の会社（Cohen-Malloy-Nguyen『Lazy Prices』）は、
      買いだけで純粋な時価加重の米国市場（French Mkt）に勝つか。書き換えの大きい社を『質の良い側』から外すと良くなるか。

段（事前登録 out/mw_lazy_prices_prereg.json の前に作った第1版は universe / crawl / pairs / reach だけ＝リターンは一切読まない）
  universe : 時点の S&P500 名簿（ie_sp500_components.csv）→ 月ごとの CIK（moat_text の対応＋今日の SEC 一覧＋提出の検問）
  crawl    : 各 CIK の 10-K / 10-K405 の本体（添付を除く）→ 語の列（小文字の英字・停止語を除く・crc32）と文の区切り・節の範囲だけを保存
  pairs    : 同じ CIK の連続する 10-K（提出日の差 270〜455 日）の類似度 4 種（余弦・Jaccard・最小編集・単純）＋節（Item 7・Item 1A）の余弦
  reach    : 月ごとの到達数（リターンを読まない）
  （事前登録の後に prices・run を足す）

キャッシュ: out/_mw_cache/lazy_prices/（gitignore）。他の角度のキャッシュ（moat_text・ex27）は読むだけ。
SEC: User-Agent は連絡先つき（絶対のルール5）、全体で毎秒6件以下。
"""
import csv, datetime, gzip, html, io, json, os, random, re, sys, time, urllib.error, urllib.parse, urllib.request, zlib
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
CACHE = M.CACHE
LP = os.path.join(CACHE, 'lazy_prices')
SUBS = os.path.join(LP, 'subs')
DOCS = os.path.join(LP, 'docs')
UNIV = os.path.join(LP, 'universe.json')
PAIRS = os.path.join(LP, 'pairs.json')
MEMB = os.path.join(CACHE, 'ie_sp500_components.csv')                 # 読むだけ
MOAT_UNIV = os.path.join(CACHE, 'moat_text', 'universe.json')          # 読むだけ（他の角度の対応）
MOAT_DOCS = os.path.join(CACHE, 'moat_text', 'docs')                   # 読むだけ（同じ本体の平文があれば取り直さない）
SEC_TICKERS = os.path.join(CACHE, 'sec_company_tickers.json')          # 読むだけ
PREREG = os.path.join(BASE, 'out', 'mw_lazy_prices_prereg.json')
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}   # 絶対のルール5（連絡先つき）

FIRST_M, END_M = 199701, 202608
TRAIN_Z, HOLD_A, RECENT_A = 200612, 200701, 201307
POST_WINDOWS = [('post_sample_2015', 201501), ('post_ssrn_2017', 201701), ('post_jf_2021', 202101)]
FORMS = ('10-K', '10-K405')           # 訂正（/A）と移行期間（10-KT）は使わない（事前登録）
GAP_MIN, GAP_MAX = 270, 455           # 前年の 10-K との提出日の差（日）
LOOKBACK_M = 12                       # 提出の翌月から12か月持つ
MIN_PER_Q = 30                        # 五分位ごとに最低30社（到達の検問）
SEC_RATE = 5.6                        # 全体で毎秒の上限（6件未満）
SECTION_MIN_TOK = 200                 # 節の余弦は両年とも200語以上のときだけ
EDIT_BLOCK_CAP = 2000                 # 最小編集: 変わった塊の語数がどちらかで2000を超えたら語単位の比較をせず max(語数) を編集数とする

# 停止語（英語の標準的な一覧・NLTK の english 179語を固定で写したもの・事前登録）
STOP = set('''i me my myself we our ours ourselves you you're you've you'll you'd your yours yourself yourselves he him his himself she
she's her hers herself it it's its itself they them their theirs themselves what which who whom this that that'll these those am is are
was were be been being have has had having do does did doing a an the and but if or because as until while of at by for with about against
between into through during before after above below to from up down in out on off over under again further then once here there when where
why how all any both each few more most other some such no nor not only own same so than too very s t can will just don don't should
should've now d ll m o re ve y ain aren aren't couldn couldn't didn didn't doesn doesn't hadn hadn't hasn hasn't haven haven't isn isn't ma
mightn mightn't mustn mustn't needn needn't shan shan't shouldn shouldn't wasn wasn't weren weren't won won't wouldn wouldn't'''.split())


# ───────────────────────── 月 ─────────────────────────
def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def mrange(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


def ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


def month_end(m):
    y, mo = divmod(m, 100)
    nx = datetime.date(y + (mo == 12), mo % 12 + 1, 1)
    return (nx - datetime.timedelta(days=1)).isoformat()


def dd(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


# ───────────────────────── SEC（毎秒の上限・プロセスをまたいで守る） ─────────────────────────
class Rate:
    """ファイルの鍵で複数プロセスの間でも間隔を守る（fcntl）"""
    def __init__(self, per_s, path):
        self.gap = 1.0 / per_s; self.path = path

    def wait(self):
        import fcntl
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'a+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                nxt = float(f.read() or 0)
            except ValueError:
                nxt = 0.0
            now = time.time(); t = max(now, nxt)
            f.seek(0); f.truncate(); f.write(repr(t + self.gap)); f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
        d = t - time.time()
        if d > 0:
            time.sleep(d)


RATE = Rate(SEC_RATE, os.path.join(LP, 'rate.lock'))


def sec_fetch(url, tries=6, stop_after=None):
    """bytes（gzip は展開）。404 は None。stop_after（bytes の正規表現）が見えたらそこで読むのをやめる（本体だけ欲しいとき）"""
    for k in range(tries):
        RATE.wait()
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=180)
            gz = r.headers.get('Content-Encoding') == 'gzip'
            dec = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz else None
            buf = io.BytesIO()
            while True:
                ch = r.read(1 << 16)
                if not ch:
                    break
                buf.write(dec.decompress(ch) if dec else ch)
                if stop_after is not None and buf.tell() > 20000 and re.search(stop_after, buf.getbuffer()[-(1 << 17) - 64:].tobytes()):
                    break
            b = buf.getvalue()
            if not gz and b[:2] == b'\x1f\x8b':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (k + 1) + random.random())
        except Exception:  # noqa
            time.sleep(2 ** (k + 1) + random.random())
    raise RuntimeError(f'SEC 取得失敗 {url}')


# ───────────────────────── 名簿と CIK ─────────────────────────
def membership_by_month():
    """{月 m: 月 m−1 の月末までで最後の名簿の記号の集合}（m の持ち物を決める名簿＝後から分かる情報を使わない）"""
    rows = sorted((r['date'], r['tickers'].split(',')) for r in csv.DictReader(open(MEMB)))
    out = {}
    for m in mrange(FIRST_M, END_M):
        cut = month_end(madd(m, -1))
        xs = [x for x in rows if x[0] <= cut]
        out[m] = sorted(set(xs[-1][1])) if xs else []
    return out


def tvariants(t):
    t = t.upper()
    return list(dict.fromkeys([t, t.replace('.', '-'), t.replace('.', ''), t.split('.')[0]]))


def sec_current():
    d = json.load(open(SEC_TICKERS))
    m = defaultdict(set)
    for v in d.values():
        m[v['ticker'].upper()].add(str(v['cik_str']))
    return m


def moat_map():
    """moat_text の6ビンテージ（1997/2000/2003/2006/2009/2012）の記号→CIK（手の対応を含む最終形）→ {記号: {cik: [年]}}"""
    u = json.load(open(MOAT_UNIV))
    out = defaultdict(lambda: defaultdict(list))
    for v, d in u['vintages'].items():
        for r in d['rows']:
            if r.get('cik'):
                out[r['t']][str(r['cik'])].append(int(v))
    return out


def subs_path(cik):
    return os.path.join(SUBS, f'{int(cik):010d}.json')


def get_subs(cik):
    """submissions API → {'name','sic','tickers','former','f': [(form, filed, acc, primaryDoc, reportDate)]}（10-K 系だけ・キャッシュ）"""
    p = subs_path(cik)
    if os.path.exists(p):
        return json.load(open(p))
    b = sec_fetch(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json')
    if b is None:
        d = {'missing': True, 'f': []}
    else:
        j = json.loads(b)
        rows = []

        def take(k):
            for i in range(len(k['form'])):
                if k['form'][i].startswith('10-K'):
                    rows.append((k['form'][i], k['filingDate'][i], k['accessionNumber'][i], k.get('primaryDocument', [''] * len(k['form']))[i],
                                 k.get('reportDate', [''] * len(k['form']))[i]))
        take(j['filings']['recent'])
        for fl in j['filings'].get('files', []):
            if fl.get('filingTo', '9999') < '1994-01-01':
                continue
            b2 = sec_fetch('https://data.sec.gov/submissions/' + fl['name'])
            if b2:
                take(json.loads(b2))
        rows = sorted(set(tuple(r) for r in rows), key=lambda r: (r[1], r[2]))
        d = {'name': j.get('name'), 'sic': j.get('sic'), 'tickers': j.get('tickers'), 'exchanges': j.get('exchanges'),
             'former': [x.get('name') for x in j.get('formerNames', [])], 'f': rows}
    os.makedirs(SUBS, exist_ok=True)
    tmp = p + f'.{os.getpid()}.tmp'
    json.dump(d, open(tmp, 'w')); os.replace(tmp, p)
    return d


def tenk_dates(s):
    return [f[1] for f in s['f'] if f[0] in FORMS]


def active(s, m):
    """月 m の持ち物を決める時点（m−1 月末）から見て、過去15か月に 10-K / 10-K405 を出しているか"""
    z = month_end(madd(m, -1)); a = month_end(madd(m, -16))
    return any(a < d <= z for d in tenk_dates(s))


def cmd_universe():
    """月ごとの CIK。規則（事前登録）:
    候補＝moat_text の6ビンテージでその記号に付いた CIK ∪ 今日の SEC 一覧でその記号（表記ゆれ込み）を持つ CIK。
    (1) 最も近いビンテージ（同じ近さなら早い方）の CIK が m−1 月末から見て過去15か月に 10-K を出していればそれ
    (2) だめなら候補のうち 10-K を出している CIK。1つならそれ・複数なら moat の近いビンテージの CIK → 今日の保有者
    (3) それでも無ければ対応なし（数える）。同じ月に同じ CIK が二つの記号に当たったら（株式の種類違い等）1つにまとめる"""
    mem = membership_by_month()
    mm, cur = moat_map(), sec_current()
    cands = {}
    for t in sorted({t for v in mem.values() for t in v}):
        c = dict((k, sorted(v)) for k, v in mm.get(t, {}).items())
        cc = sorted({x for tv in tvariants(t) for x in cur.get(tv, ())})
        cands[t] = {'moat': c, 'cur': cc}
    allc = sorted({c for v in cands.values() for c in list(v['moat']) + v['cur']}, key=int)
    print('候補 CIK', len(allc), flush=True)
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(6) as ex:
        for i, _ in enumerate(ex.map(get_subs, allc)):
            if (i + 1) % 200 == 0:
                print(' subs', i + 1, '/', len(allc), flush=True)
    S = {c: get_subs(c) for c in allc}
    months, via = {}, Counter()
    unm = defaultdict(list)
    for m, ts in sorted(mem.items()):
        y = m // 100
        got = {}
        for t in ts:
            cd = cands[t]
            pick, how = None, None
            if cd['moat']:
                near = sorted(cd['moat'].items(), key=lambda kv: min((abs(v - y), v) for v in kv[1]))
                c0 = near[0][0]
                if active(S[c0], m):
                    pick, how = c0, 'moat_nearest'
            if pick is None:
                act = [c for c in list(cd['moat']) + cd['cur'] if active(S[c], m)]
                act = list(dict.fromkeys(act))
                if len(act) == 1:
                    pick, how = act[0], ('moat_other' if act[0] in cd['moat'] else 'current')
                elif len(act) > 1:
                    am = [c for c in act if c in cd['moat']]
                    if am:
                        am.sort(key=lambda c: min(abs(v - y) for v in cd['moat'][c]))
                        pick, how = am[0], 'moat_other_multi'
                    else:
                        pick, how = act[0], 'current_multi'
            if pick is None:
                unm[t].append(m); via['unmapped'] += 1
                continue
            if pick in got:          # 同じ CIK に二つの記号（株式の種類違い等）→ 1つ
                via['dup_cik_merged'] += 1
                continue
            got[pick] = t; via[how] += 1
        months[m] = got
    ciks = sorted({c for g in months.values() for c in g}, key=int)
    span = {}
    for c in ciks:
        ms = [m for m, g in months.items() if c in g]
        span[c] = [min(ms), max(ms)]
    rate = {str(y): round(sum(len(months[m]) for m in months if m // 100 == y) / max(1, sum(len(mem[m]) for m in mem if m // 100 == y)), 3)
            for y in range(FIRST_M // 100, END_M // 100 + 1)}
    out = {'rule': cmd_universe.__doc__, 'months': {str(m): g for m, g in months.items()}, 'span': span, 'via': dict(via),
           'mapped_share_by_year': rate, 'unmapped': {t: [min(v), max(v), len(v)] for t, v in sorted(unm.items())},
           'n_cik': len(ciks), 'sic': {c: S[c].get('sic') for c in ciks}, 'names': {c: S[c].get('name') for c in ciks}}
    os.makedirs(LP, exist_ok=True)
    json.dump(out, open(UNIV, 'w'), ensure_ascii=False)
    print('CIK', len(ciks), dict(via))
    print('対応の割合（年）', rate)
    print('対応なしの記号', len(unm))


# ───────────────────────── 本文 → 語の列 ─────────────────────────
def split_docs(txt):
    out = []
    for m in re.finditer(r'<DOCUMENT>(.*?)(?:</DOCUMENT>|\Z)', txt, re.S):
        d = m.group(1)
        t = re.search(r'<TYPE>\s*([^\s<]+)', d)
        body = re.search(r'<TEXT>(.*?)(?:</TEXT>|\Z)', d, re.S)
        out.append(((t.group(1).upper() if t else ''), body.group(1) if body else d))
    return out


BLOCK = re.compile(r'(?i)</?(?:p|div|br|tr|li|ul|ol|h[1-6]|table|center|blockquote|pre|hr|title)\b[^>]*>')


def to_text(s):
    """HTML でも平文でも → 段落を空行で区切った平文（moat_text の to_text を逐語で写したもの）"""
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
    out = []
    for m in ITEM_RE.finditer(t):
        n = m.group(1).lstrip('0') or '0'
        suf = (m.group(2) or '').strip('()').upper()
        key = n + suf
        if m.group(3):
            key = f'{key}+{m.group(3)}'
        out.append((m.start(), key))
    return out


def section_span(t, its, starts, ends):
    """moat_text の section と同じ規則（見出しから次の終わりの見出しまで・目次を避けて最長）→ (始, 終) or None"""
    best = None
    for i, (p, k) in enumerate(its):
        if k.split('+')[0] not in starts:
            continue
        stop_keys = set(ends)
        if '+' in k:
            stop_keys = {x for x in ends if x not in ('2',)} | {'3'}
        q = next((pp for pp, kk in its[i + 1:] if kk.split('+')[0] in stop_keys), None)
        if q is None:
            q = min(len(t), p + 400000)
        if best is None or q - p > best[1] - best[0]:
            best = (p, q)
    return best if best and best[1] - best[0] > 400 else None


def cover_float(txt):
    """表紙の『aggregate market value ... held by non-affiliates』→ ドル（無ければ None）（moat_text と同じ式）"""
    m = re.search(r'(?is)aggregate\s+market\s+value.{0,500}?\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|thousand)?', txt[:40000])
    if not m:
        return None
    try:
        v = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    return v * {'billion': 1e9, 'million': 1e6, 'thousand': 1e3}.get((m.group(2) or '').lower(), 1.0)


SENT = re.compile(r'(?<=[.!?])\s+|\n\s*\n')
TOK = re.compile(r'[a-z]+')


def encode(mt):
    """平文 → (語の列 uint32, 文ごとの語数, 文の開始位置(文字), 全語数)。語＝小文字の英字の連なり（2字以上）・停止語を除く・crc32"""
    import numpy as np
    seq, slen, sst = [], [], []
    n_all = 0
    pos = 0
    for piece in SENT.split(mt):
        st = mt.find(piece, pos) if piece else pos
        if st < 0:
            st = pos
        pos = st + len(piece)
        ws = TOK.findall(piece.lower())
        n_all += len(ws)
        ws = [w for w in ws if len(w) >= 2 and w not in STOP]
        if not ws:
            continue
        seq.extend(zlib.crc32(w.encode()) for w in ws)
        slen.append(len(ws)); sst.append(st)
    return np.array(seq, dtype=np.uint32), np.array(slen, dtype=np.uint32), np.array(sst, dtype=np.int64), n_all


def doc_features(mt):
    import numpy as np
    seq, slen, sst, n_all = encode(mt)
    its = items(mt)
    sec = {}
    for nm, st, en in (('item7', {'7'}, {'7A', '8', '9'}), ('item1a', {'1A'}, {'1B', '2', '3'}), ('item1', {'1'}, {'1A', '1B', '2', '3', '4'})):
        sp = section_span(mt, its, st, en)
        if sp:
            a = int(np.searchsorted(sst, sp[0], 'left')); z = int(np.searchsorted(sst, sp[1], 'left'))
            if z > a:
                sec[nm] = [a, z]
    return seq, slen, sec, n_all


def main_doc_from_txt(txt):
    docs = split_docs(txt)
    return next((b for ty, b in docs if ty.startswith('10-K')), docs[0][1] if docs else txt)


def moat_main_text(cik, acc):
    p = os.path.join(MOAT_DOCS, f'{int(cik):010d}', acc + '.json.gz')
    if not os.path.exists(p):
        return None
    try:
        d = json.loads(gzip.open(p).read())
    except Exception:  # noqa
        return None
    return d.get('main_text') if not d.get('missing') else None


def fetch_main(cik, acc, prim):
    """本体の平文と取得経路"""
    mt = moat_main_text(cik, acc)
    if mt:
        return mt, 'moat_cache'
    nod = acc.replace('-', '')
    if prim and re.search(r'(?i)\.(htm|html|txt)$', prim):
        b = sec_fetch(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nod}/{prim}')
        if b is not None:
            s = b.decode('latin-1')
            if '<DOCUMENT>' in s[:5000]:
                s = main_doc_from_txt(s)
            return to_text(s), 'primary'
    b = sec_fetch(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}.txt', stop_after=rb'</DOCUMENT>')
    if b is None:
        return None, 'missing'
    return to_text(main_doc_from_txt(b.decode('latin-1'))), 'full_txt'


def doc_file(cik, acc):
    return os.path.join(DOCS, f'{int(cik):010d}', acc + '.npz')


def crawl_one(cik, filings):
    """1社の 10-K を古い順に。保存は語の列・文の語数・節の範囲・メタ（本文そのものは保存しない）"""
    import numpy as np
    d0 = os.path.join(DOCS, f'{int(cik):010d}')
    os.makedirs(d0, exist_ok=True)
    mp = os.path.join(d0, 'meta.json')
    meta = json.load(open(mp)) if os.path.exists(mp) else {}
    n = 0
    for form, filed, acc, prim, rep in filings:
        if acc in meta and (meta[acc].get('ok') or meta[acc].get('src') == 'missing'):
            continue
        try:
            mt, src = fetch_main(cik, acc, prim)
        except RuntimeError as e:
            meta[acc] = {'form': form, 'filed': filed, 'src': 'error', 'err': str(e)[:200]}
            continue
        if mt is None:
            meta[acc] = {'form': form, 'filed': filed, 'src': 'missing', 'ok': False}
        else:
            seq, slen, sec, n_all = doc_features(mt)
            np.savez_compressed(doc_file(cik, acc), seq=seq, slen=slen)
            meta[acc] = {'form': form, 'filed': filed, 'report': rep, 'src': src, 'ok': len(seq) >= 500, 'n_tok': int(len(seq)),
                         'n_all': int(n_all), 'n_sent': int(len(slen)), 'n_char': len(mt), 'sec': sec, 'float': cover_float(mt)}
        n += 1
        tmp = mp + f'.{os.getpid()}.tmp'
        json.dump(meta, open(tmp, 'w')); os.replace(tmp, mp)
    return cik, n


def crawl_list():
    U = json.load(open(UNIV))
    todo = []
    for c, (a, z) in U['span'].items():
        s = get_subs(c)
        lo = month_end(madd(a, -28))           # 最初に使う月の前の12か月の提出＋その前年の提出（差は最大455日）
        hi = month_end(madd(z, -1))
        fl = [tuple(f) for f in s['f'] if f[0] in FORMS and lo < f[1] <= hi]
        if fl:
            todo.append((c, fl))
    return todo


def _crawl_worker(args):
    part, nparts = args
    todo = [x for i, x in enumerate(crawl_list()) if i % nparts == part]
    done = 0
    for c, fl in todo:
        try:
            crawl_one(c, fl)
        except Exception as e:  # noqa
            print('ERR', c, e, flush=True)
        done += 1
        if done % 25 == 0:
            print(f'[{part}] {done}/{len(todo)}', flush=True)
    return part, done


def cmd_crawl(nparts=4):
    from multiprocessing import Pool
    todo = crawl_list()
    print('会社', len(todo), '提出', sum(len(f) for _, f in todo), flush=True)
    with Pool(nparts) as p:
        for r in p.imap_unordered(_crawl_worker, [(i, nparts) for i in range(nparts)]):
            print('終わり', r, flush=True)


# ───────────────────────── 類似度 ─────────────────────────
def _tf(seq):
    import numpy as np
    u, c = np.unique(seq, return_counts=True)
    return u, c.astype(np.float64)


def cosine(a, b):
    import numpy as np
    ua, ca = _tf(a); ub, cb = _tf(b)
    common, ia, ib = np.intersect1d(ua, ub, assume_unique=True, return_indices=True)
    den = float(np.sqrt((ca ** 2).sum()) * np.sqrt((cb ** 2).sum()))
    return float((ca[ia] * cb[ib]).sum() / den) if den > 0 else None


def jaccard(a, b):
    import numpy as np
    ua = np.unique(a); ub = np.unique(b)
    inter = len(np.intersect1d(ua, ub, assume_unique=True))
    uni = len(ua) + len(ub) - inter
    return inter / uni if uni else None


def sentences(seq, slen):
    import numpy as np
    idx = np.concatenate([[0], np.cumsum(slen)])
    return [seq[idx[i]:idx[i + 1]] for i in range(len(slen))]


def diff_measures(sa, sb):
    """文を単位にした比較（difflib・autojunk なし）→ (単純, 最小編集)。
    単純 = 1 − (消えた文の語数 + 増えた文の語数) ÷ (両年の語数の和)
    最小編集 = 1 − 編集数 ÷ max(両年の語数)。編集数＝変わった塊の中で語単位の差分（置換は長い方の語数・削除・挿入はその語数）。
               塊の語数がどちらかで EDIT_BLOCK_CAP を超えたら語単位の比較をせず max(語数)"""
    import difflib
    ha = [hash(s.tobytes()) for s in sa]; hb = [hash(s.tobytes()) for s in sb]
    na = sum(len(s) for s in sa); nb = sum(len(s) for s in sb)
    if not na or not nb:
        return None, None
    sm = difflib.SequenceMatcher(None, ha, hb, autojunk=False)
    changed, edits = 0, 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        wa = [int(x) for s in sa[i1:i2] for x in s]; wb = [int(x) for s in sb[j1:j2] for x in s]
        changed += len(wa) + len(wb)
        if not wa or not wb:
            edits += len(wa) + len(wb)
        elif len(wa) > EDIT_BLOCK_CAP or len(wb) > EDIT_BLOCK_CAP:
            edits += max(len(wa), len(wb))
        else:
            sm2 = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
            for op2, a1, a2, b1, b2 in sm2.get_opcodes():
                if op2 == 'replace':
                    edits += max(a2 - a1, b2 - b1)
                elif op2 == 'delete':
                    edits += a2 - a1
                elif op2 == 'insert':
                    edits += b2 - b1
    return 1 - changed / (na + nb), 1 - edits / max(na, nb)


def load_doc(cik, acc):
    import numpy as np
    z = np.load(doc_file(cik, acc))
    return z['seq'], z['slen']


def sect(seq, slen, sp):
    import numpy as np
    idx = np.concatenate([[0], np.cumsum(slen)])
    return seq[idx[sp[0]]:idx[sp[1]]]


def pairs_one(cik):
    """1社の連続する 10-K の類似度 → [{acc, filed, prev_acc, prev_filed, cos, jac, simple, minedit, cos_item7, cos_item1a, ...}]"""
    mp = os.path.join(DOCS, f'{int(cik):010d}', 'meta.json')
    if not os.path.exists(mp):
        return cik, []
    meta = json.load(open(mp))
    fs = sorted(((v['filed'], acc) for acc, v in meta.items() if v.get('ok')), key=lambda x: x)
    out = []
    cache = {}
    for i, (filed, acc) in enumerate(fs):
        prev = [(f, a) for f, a in fs[:i] if GAP_MIN <= (dd(filed) - dd(f)).days <= GAP_MAX]
        rec = {'acc': acc, 'filed': filed, 'form': meta[acc]['form'], 'float': meta[acc].get('float'), 'n_tok': meta[acc]['n_tok'],
               'report': meta[acc].get('report')}
        if not prev:
            rec['why'] = 'no_prev_in_window'
            out.append(rec); continue
        pf, pa = prev[-1]
        rec['prev_acc'], rec['prev_filed'] = pa, pf
        for k in (acc, pa):
            if k not in cache:
                cache[k] = load_doc(cik, k)
        (sb, lb), (sa, la) = cache[acc], cache[pa]
        rec['cos'] = cosine(sa, sb)
        rec['jac'] = jaccard(sa, sb)
        rec['simple'], rec['minedit'] = diff_measures(sentences(sa, la), sentences(sb, lb))
        for nm in ('item7', 'item1a'):
            spa, spb = meta[pa]['sec'].get(nm), meta[acc]['sec'].get(nm)
            if spa and spb:
                xa, xb = sect(sa, la, spa), sect(sb, lb, spb)
                if len(xa) >= SECTION_MIN_TOK and len(xb) >= SECTION_MIN_TOK:
                    rec[f'cos_{nm}'] = cosine(xa, xb)
        for k in list(cache):
            if k not in (acc,):
                del cache[k]
        out.append(rec)
    return cik, out


def cmd_pairs(nproc=4):
    from multiprocessing import Pool
    U = json.load(open(UNIV))
    ciks = sorted(U['span'], key=int)
    res = {}
    with Pool(nproc) as p:
        for i, (c, rows) in enumerate(p.imap_unordered(pairs_one, ciks, chunksize=4)):
            res[c] = rows
            if (i + 1) % 100 == 0:
                print(' pairs', i + 1, '/', len(ciks), flush=True)
    json.dump(res, open(PAIRS, 'w'))
    n = sum(1 for v in res.values() for r in v if r.get('cos') is not None)
    print('対', n, '（類似度あり）／提出', sum(len(v) for v in res.values()))


# ───────────────────────── 到達（リターンを読まない） ─────────────────────────
def signal_at(P, U):
    """{月 m: {cik: 直近の 10-K（提出月 ≤ m−1・12か月以内）の類似度の記録}}（名簿に居る社だけ）"""
    by = {c: sorted([r for r in rows if r.get('cos') is not None], key=lambda r: r['filed']) for c, rows in P.items()}
    out = {}
    for ms, g in U['months'].items():
        m = int(ms)
        lo, hi = madd(m, -LOOKBACK_M), madd(m, -1)
        cur = {}
        for c in g:
            rs = [r for r in by.get(c, []) if lo <= ym(r['filed']) <= hi]
            if rs:
                cur[c] = rs[-1]
        out[m] = cur
    return out


def cmd_reach():
    U = json.load(open(UNIV)); P = json.load(open(PAIRS))
    sig = signal_at(P, U)
    rep = {}
    for m in sorted(sig):
        n = len(sig[m]); nm = len(U['months'][str(m)])
        rep[m] = {'members_mapped': nm, 'with_signal': n, 'per_quintile': n // 5, 'ok': n // 5 >= MIN_PER_Q,
                  'item7': sum(1 for r in sig[m].values() if r.get('cos_item7') is not None),
                  'item1a': sum(1 for r in sig[m].values() if r.get('cos_item1a') is not None)}
    ys = {}
    for m, v in rep.items():
        ys.setdefault(m // 100, []).append(v)
    for y, vs in sorted(ys.items()):
        print(y, 'mapped', min(v['members_mapped'] for v in vs), 'signal min/max', min(v['with_signal'] for v in vs), max(v['with_signal'] for v in vs),
              'item7 min', min(v['item7'] for v in vs), 'item1a min', min(v['item1a'] for v in vs), 'ok', sum(v['ok'] for v in vs), '/', len(vs))
    json.dump({str(k): v for k, v in rep.items()}, open(os.path.join(LP, 'reach.json'), 'w'))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'universe':
        cmd_universe()
    elif cmd == 'crawl':
        cmd_crawl(int(sys.argv[2]) if len(sys.argv) > 2 else 4)
    elif cmd == 'pairs':
        cmd_pairs()
    elif cmd == 'reach':
        cmd_reach()
    else:
        print(__doc__)
