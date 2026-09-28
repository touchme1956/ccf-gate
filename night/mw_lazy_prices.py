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


EFTS = os.path.join(LP, 'efts')
MOAT_EFTS = os.path.join(CACHE, 'moat_text', 'efts')      # 読むだけ


def efts_symbol(t):
    """EDGAR 全文検索（2001〜）で 10-K の本文の『symbol T』→ [[cik, 提出日, 表示名]]（moat_text の efts_symbol と同じ問い合わせ・400件で打ち切り）"""
    for d in (MOAT_EFTS, EFTS):
        p = os.path.join(d, f'{t}.v2.json')
        if os.path.exists(p):
            return json.load(open(p))
    os.makedirs(EFTS, exist_ok=True)
    hits_all, frm = [], 0
    while True:
        q = urllib.parse.quote(f'"symbol {t}"')
        b = sec_fetch(f'https://efts.sec.gov/LATEST/search-index?q={q}&forms=10-K,10-K405&from={frm}')
        if b is None:
            break
        j = json.loads(b)
        hits = j.get('hits', {}).get('hits', [])
        for h in hits:
            s_ = h['_source']
            for c, nm in zip(s_.get('ciks', []), s_.get('display_names', []) or [''] * len(s_.get('ciks', []))):
                hits_all.append([str(int(c)), s_.get('file_date'), re.sub(r'\s*\(CIK \d+\)$', '', nm or '')])
        frm += len(hits)
        tot = j.get('hits', {}).get('total', {}).get('value', 0)
        if not hits or frm >= min(tot, 400):
            break
    json.dump(hits_all, open(os.path.join(EFTS, f'{t}.v2.json'), 'w'))
    return hits_all


efts_used = []
# 全文検索が別の社を拾ったもの（社名で確かめた・リターンを見る前・2026-09-28）: 記号の本当の持ち主は名前が違う
EFTS_REJECT = {('GGP', '314712'): 'Boomerang Systems（GGP は General Growth Properties）',
               ('PCS', '1108727'): 'iPCS（PCS は Sprint PCS の追跡株＝Sprint）', ('PCS', '1082114'): 'Liberty Media（同上）',
               ('PALM', '895021'): 'Centura Software（PALM は Palm Inc）', ('FI', '1575828'): 'Expro Group（FI は Fiserv）',
               ('H', '1355001'): 'Anywhere Real Estate（H は Harcourt General）'}


def _map_month(mem, cands, S, m):
    y = m // 100
    got, via, unm = {}, Counter(), []
    for t in mem:
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
        if pick is None and cd.get('efts'):
            # 全文検索の候補: その年の前後1年に『symbol T』を書いた 10-K の数が多い順（提出が生きている CIK だけ）
            sc = Counter(c for c, fdte, _ in cd['efts'] if fdte and abs(int(fdte[:4]) - y) <= 1)
            act = [c for c, _ in sc.most_common() if c in S and active(S[c], m) and (t, c) not in EFTS_REJECT]
            if act:
                pick, how = act[0], 'efts'
                efts_used.append((m, act[0]))
        if pick is None:
            unm.append(t); via['unmapped'] += 1
            continue
        if pick in got:
            via['dup_cik_merged'] += 1
            continue
        got[pick] = t; via[how] += 1
    return got, via, unm


def cmd_universe():
    """月ごとの CIK。規則（事前登録＋リターンを見る前の追補）:
    候補＝moat_text の6ビンテージでその記号に付いた CIK ∪ 今日の SEC 一覧でその記号（表記ゆれ込み）を持つ CIK。
    (1) 最も近いビンテージ（同じ近さなら早い方）の CIK が m−1 月末から見て過去15か月に 10-K を出していればそれ
    (2) だめなら候補のうち 10-K を出している CIK。1つならそれ・複数なら moat の近いビンテージの CIK → 今日の保有者
    (2b)【追補・2026-09-28 リターンを見る前】(1)(2) で付かない記号だけ、EDGAR 全文検索で 10-K に『symbol T』を書いた CIK を候補に足し、
        その年の前後1年の件数が多い順に、提出が生きている CIK を採る（改名・買収で今日の一覧に無い社: FB→META・ATVI・WBA 等）
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
        list(ex.map(get_subs, allc))
    S = {c: get_subs(c) for c in allc}
    need = set()
    for m, ts in mem.items():
        _, _, unm = _map_month(ts, cands, S, m)
        need |= set(unm)
    print('全文検索に回す記号', len(need), flush=True)
    for t in sorted(need):
        cands[t]['efts'] = efts_symbol(t)
    ex_c = sorted({c for t in need for c, _, _ in cands[t]['efts']} - set(S), key=int)
    # 全文検索の候補は多いので、名簿の期間の前後1年に書いた上位5社だけ提出一覧を取る
    want = set()
    for t in need:
        ms = [m for m, ts in mem.items() if t in ts]
        y0, y1 = min(ms) // 100 - 1, max(ms) // 100 + 1
        sc = Counter(c for c, fdte, _ in cands[t]['efts'] if fdte and y0 <= int(fdte[:4]) <= y1)
        want |= {c for c, _ in sc.most_common(5)}
    ex_c = [c for c in ex_c if c in want]
    print('全文検索の候補 CIK', len(ex_c), flush=True)
    with cf.ThreadPoolExecutor(6) as ex:
        list(ex.map(get_subs, ex_c))
    for c in ex_c:
        S[c] = get_subs(c)
    months, via = {}, Counter()
    unm_all = defaultdict(list)
    efts_used.clear()
    for m, ts in sorted(mem.items()):
        got, v, unm = _map_month(ts, cands, S, m)
        months[m] = got; via.update(v)
        for t in unm:
            unm_all[t].append(m)
    ciks = sorted({c for g in months.values() for c in g}, key=int)
    span = {}
    for c in ciks:
        ms = [m for m, g in months.items() if c in g]
        span[c] = [min(ms), max(ms)]
    rate = {str(y): round(sum(len(months[m]) for m in months if m // 100 == y) / max(1, sum(len(mem[m]) for m in mem if m // 100 == y)), 3)
            for y in range(FIRST_M // 100, END_M // 100 + 1)}
    efts_pick = sorted({(t, c) for m, g in months.items() for c, t in g.items() if t in need})
    out = {'rule': cmd_universe.__doc__, 'months': {str(m): g for m, g in months.items()}, 'span': span, 'via': dict(via),
           'mapped_share_by_year': rate, 'unmapped': {t: [min(v), max(v), len(v)] for t, v in sorted(unm_all.items())},
           'efts_picks': [[t, c, S[c].get('name')] for t, c in efts_pick],
           'efts_months': sorted({(m, c) for m, c in efts_used if c in months[m]}),
           'n_cik': len(ciks), 'sic': {c: S[c].get('sic') for c in ciks}, 'names': {c: S[c].get('name') for c in ciks}}
    os.makedirs(LP, exist_ok=True)
    json.dump(out, open(UNIV, 'w'), ensure_ascii=False)
    print('CIK', len(ciks), dict(via))
    print('対応の割合（年）', rate)
    print('対応なしの記号', len(unm_all))


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
    """見出しの位置 → [(pos, '1'|'1A'|'7'..., 見出しから300字)]。本文中の参照（『Item 7 of this Form 10-K』のように行の残りが
    小文字で始まる）は見出しとして数えない（2026-09-28・リターンを見る前の修正: moat_text の規則は参照を見出しと読み、
    節が文書の大半に伸びていた＝Apple FY2008 の Item 7 が Item 1 の中の参照から始まっていた）"""
    out = []
    for m in ITEM_RE.finditer(t):
        rest = (m.group(4) or '').strip()
        if rest and not re.match(r'[A-Z"“\'(]', rest):
            continue
        n = m.group(1).lstrip('0') or '0'
        suf = (m.group(2) or '').strip('()').upper()
        key = n + suf
        if m.group(3):
            key = f'{key}+{m.group(3)}'
        out.append((m.start(), key, t[m.start():m.start() + 300]))
    return out


TITLE = {'item7': re.compile(r'(?i)management'), 'item1a': re.compile(r'(?i)risk'), 'item1': re.compile(r'(?i)business')}


def section_span(t, its, starts, ends, title=None):
    """見出し（題の語を含むものだけ）から次の終わりの見出しまで・目次を避けて最長（moat_text の section と同じ選び方）→ (始, 終) or None"""
    best = None
    for i, (p, k, head) in enumerate(its):
        if k.split('+')[0] not in starts:
            continue
        if title is not None and not title.search(head):
            continue
        stop_keys = set(ends)
        if '+' in k:
            stop_keys = {x for x in ends if x not in ('2',)} | {'3'}
        q = next((pp for pp, kk, _ in its[i + 1:] if kk.split('+')[0] in stop_keys), None)
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
        sp = section_span(mt, its, st, en, TITLE[nm])
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
    idx = np.concatenate([np.zeros(1, dtype=np.int64), np.cumsum(slen.astype(np.int64))])
    return [seq[int(idx[i]):int(idx[i + 1])] for i in range(len(slen))]


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
    idx = np.concatenate([np.zeros(1, dtype=np.int64), np.cumsum(slen.astype(np.int64))])
    return seq[int(idx[sp[0]]):int(idx[sp[1]])]


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


# ═════════════════════════ 事前登録（72b0978）の後に足した段: 株価・判定 ═════════════════════════
YH = os.path.join(LP, 'yh')
SPIKE = 3.0
RESULT = 'mw_lazy_prices.json'
NAME_DROP = {'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'COMPANIES', 'LTD', 'LIMITED', 'PLC', 'THE', 'HOLDINGS', 'HOLDING',
             'GROUP', 'INCORPORATED', 'NEW', 'LLC', 'LP', 'NV', 'SA', 'AG', 'TRUST', 'AND', 'OF', 'INTERNATIONAL', 'INTL'}
NAME_GENERIC = {'GENERAL', 'AMERICAN', 'UNITED', 'FIRST', 'NATIONAL', 'SOUTHERN', 'NORTHERN', 'WESTERN', 'EASTERN', 'CENTRAL',
                'PACIFIC', 'ATLANTIC', 'CONTINENTAL', 'STANDARD', 'UNION', 'US', 'USA', 'ALLIED', 'CONSOLIDATED', 'FEDERAL',
                'SECURITY', 'NORTH', 'SOUTH', 'WEST', 'EAST', 'NEW', 'GREAT', 'ADVANCED', 'APPLIED', 'DIGITAL', 'INTEGRATED',
                'PUBLIC', 'CITIZENS', 'PEOPLES', 'COMMERCIAL', 'BANK', 'ENERGY', 'HEALTH', 'MEDICAL', 'DATA', 'TECHNOLOGIES',
                'INDUSTRIES', 'SYSTEMS', 'FINANCIAL', 'CAPITAL', 'INVESTORS', 'PROPERTIES', 'REALTY', 'RESOURCES', 'MORGAN',
                'STATE', 'CITY', 'HOME', 'TEXAS', 'CALIFORNIA', 'MID', 'TRANS', 'INTER', 'UNIVERSAL', 'NATURAL', 'ROYAL'}


def nname(s):
    s = re.sub(r'/[A-Z]{2,3}/?', ' ', (s or '').upper())
    s = re.sub(r'\([^)]*\)', ' ', s).replace('&', ' AND ')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return [w for w in s.split() if w not in NAME_DROP]


def cont_name(a, b):
    """同じ会社の続きか（moat_text の cont_name と同じ式）"""
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
    d = json.load(open(SEC_TICKERS))
    by_cik, holder = defaultdict(list), {}
    for k in sorted(d, key=int):
        v = d[k]
        c, t = str(v['cik_str']), v['ticker'].upper()
        by_cik[c].append((t, v['title']))
        holder.setdefault(t, (c, v['title']))
    return by_cik, holder


def ysym(t):
    return t.replace('.', '-').replace('/', '-').upper()


def yahoo_symbols(U):
    """CIK → (Yahoo の記号 or None, 経路)。moat_text の resolve_ticker と同じ (a)(b)(c)（(b) は社名の続きのときだけ）"""
    by_cik, holder = sec_maps()
    last_t = {}
    for ms in sorted(U['months'], key=int):
        for c, t in U['months'][ms].items():
            last_t[c] = t
    out = {}
    for c, T in last_t.items():
        T = T.upper()
        nm = U['names'].get(c) or ''
        if by_cik.get(c):
            ts = [t for t, _ in by_cik[c]]
            tv = [x for x in tvariants(T) if x in ts]
            out[c] = (ysym(tv[0] if tv else ts[0]), 'a_cik_has_ticker_today')
            continue
        h = holder.get(T) or holder.get(T.replace('.', '-'))
        if h:
            hc, ht = h
            out[c] = (ysym(T), 'b_continuation') if cont_name(nm, ht) else (None, 'b_other_company')
            continue
        out[c] = (ysym(T), 'c_nobody_holds_T')
    return out


def yh_fetch(sym):
    os.makedirs(YH, exist_ok=True)
    p = os.path.join(YH, sym + '.json')
    if os.path.exists(p) or os.path.exists(p + '.404'):
        return
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    for i in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
            tmp = p + f'.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, p)
            return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(p + '.404', 'w').write('404'); return
            time.sleep(2 * (i + 1) + random.random())
        except Exception:  # noqa
            time.sleep(2 * (i + 1) + random.random())


_SER = {}


def yh_series(sym):
    """{'ret': {yyyymm: r}, 'first', 'type', 'spike', 'name'} or None。切り方は mw_common.yahoo と同じ
    （取引所の現地時刻で月を切る・今月以降を落とす・抜けた月をまたがない）"""
    if sym in _SER:
        return _SER[sym]
    out = None
    p = os.path.join(YH, sym + '.json')
    if sym and os.path.exists(p):
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
            px = {}
            for t, a in zip(ts, adj):
                if a is None:
                    continue
                d = datetime.datetime.utcfromtimestamp(t + off)
                px[d.year * 100 + d.month] = a
            now = datetime.datetime.utcfromtimestamp(time.time() + off)
            px = {k: v for k, v in px.items() if k < now.year * 100 + now.month}
            ks = sorted(px)
            ret = {k: px[k] / px[q] - 1 for q, k in zip(ks, ks[1:]) if (k // 100 * 12 + k % 100) - (q // 100 * 12 + q % 100) == 1 and px[q] > 0}
            if ret:
                spike = next((k for k in sorted(ret) if ret[k] > SPIKE), None)
                out = {'ret': ret, 'first': min(ret), 'type': (r.get('meta') or {}).get('instrumentType'), 'spike': spike,
                       'name': (r.get('meta') or {}).get('longName') or (r.get('meta') or {}).get('shortName')}
    _SER[sym] = out
    return out


def cmd_prices():
    U = json.load(open(UNIV))
    ys = yahoo_symbols(U)
    todo = sorted({s for s, _ in ys.values() if s})
    print('Yahoo の記号', len(todo), Counter(v for _, v in ys.values()), flush=True)
    import concurrent.futures as cf
    import threading
    lock_ = threading.Lock(); nxt = [0.0]

    def one(y):
        with lock_:
            t = max(time.time(), nxt[0]); nxt[0] = t + 0.25
        d = t - time.time()
        if d > 0:
            time.sleep(d)
        yh_fetch(y)
    with cf.ThreadPoolExecutor(4) as ex:
        for i, _ in enumerate(ex.map(one, todo)):
            if (i + 1) % 200 == 0:
                print(' ', i + 1, '/', len(todo), flush=True)
    json.dump({c: list(v) for c, v in ys.items()}, open(os.path.join(LP, 'yahoo_symbols.json'), 'w'))
    got = sum(1 for s in todo if yh_series(s))
    print('系列あり', got, '/', len(todo))


# ───────────────────────── 業種（French 49） ─────────────────────────
def ff49():
    import zipfile
    z = zipfile.ZipFile(os.path.join(CACHE, 'fr_Siccodes49_map.zip'))
    txt = z.read(z.namelist()[0]).decode('latin-1')
    rng, cur = [], None
    for line in txt.splitlines():
        m = re.match(r'^\s*(\d+)\s+(\S+)\s+', line)
        if m and not re.match(r'^\s*\d{4}-\d{4}', line):
            cur = m.group(2); continue
        m2 = re.match(r'^\s*(\d{4})-(\d{4})', line)
        if m2 and cur:
            rng.append((int(m2.group(1)), int(m2.group(2)), cur))

    def f(sic):
        try:
            x = int(sic)
        except (TypeError, ValueError):
            return 'Other'
        for a, b, nm in rng:
            if a <= x <= b:
                return nm
        return 'Other'
    return f


# ───────────────────────── 質（P2 用） ─────────────────────────
def quality_sets(U):
    """{形成年 t: set(cik)}（名簿の社のうち cop_at（2010〜）・op_at 代理（1997〜2001）の上位1/3・ceil）と記録"""
    import math as _m
    info, sets = {}, {}
    # 2010〜: mw_sec_replication のパネル（読むだけ）
    pn = json.load(gzip.open(os.path.join(CACHE, 'mw_sec_panel_v4.json.gz'), 'rt'))
    for t in range(2010, END_M // 100 + 1):
        mem = U['months'].get(str(t * 100 + 7)) or {}
        vals = {c: pn[c]['y'][str(t)]['cop_at'] for c in mem if c in pn and str(t) in pn[c]['y'] and pn[c]['y'][str(t)].get('cop_at') is not None}
        k = _m.ceil(len(vals) / 3)
        sets[t] = set(sorted(vals, key=lambda c: (-vals[c], int(c)))[:k])
        info[t] = {'src': 'sec_panel_v4_cop_at', 'members': len(mem), 'with_value': len(vals), 'top_third': k}
    # 1997〜2001: EX-27 の代理（mw_ex27 の formation/signals を読むだけで使う）
    import mw_ex27 as X
    panel, _ = X.build_panel_ex27()
    for t in range(1997, 2002):
        mem = U['months'].get(str(t * 100 + 7)) or {}
        vals = {}
        for c in mem:
            fil = panel.get(c) or panel.get(str(int(c)))
            if not fil:
                continue
            fo = X.formation(fil, t)
            if fo and (fo.get('sig') or {}).get('op_at') is not None:
                vals[c] = fo['sig']['op_at']
        k = _m.ceil(len(vals) / 3)
        sets[t] = set(sorted(vals, key=lambda c: (-vals[c], int(c)))[:k])
        info[t] = {'src': 'ex27_op_at_proxy', 'members': len(mem), 'with_value': len(vals), 'top_third': k}
    return sets, info


def quality_at(sets, m):
    """月 m の質の良い側（t 年7月〜t+1 年6月）。定義の無い月は None"""
    t = m // 100 if m % 100 >= 7 else m // 100 - 1
    if 1997 <= t <= 2001 or t >= 2010:
        return sets.get(t)
    return None


# ───────────────────────── 組み立て ─────────────────────────
MEASURES = ['cos', 'jac', 'minedit', 'simple', 'cos_item7', 'cos_item1a']


class Book:
    """ひとつの系列の持ち物を毎月作り替える。S・L・M の3つの生き残りの扱いを同時に出す"""
    def __init__(self, name):
        self.name = name
        self.r = {'S': {}, 'L': {}, 'M': {}}
        self.dead = set()
        self.prev = None          # 前月の漂った後の重み（S）
        self.turn = []
        self.nobs = {}
        self.mkt_months = 0
        self.wsum = {'train': defaultdict(float), 'hold': defaultdict(float)}
        self.wcnt = {'train': 0, 'hold': 0}

    def step(self, m, w, st, mkt_m):
        """w = {cik: 重み（正規化前）} or None（到達しない月＝市場を持つ）。st(c, m) → ('ok', r) / ('missing', None) / ('spike', None)"""
        if not w:
            for b in ('S', 'L', 'M'):
                self.r[b][m] = mkt_m
            cur = {'__MKT__': 1.0}
            self.turn.append(0.5 * sum(abs(cur.get(k, 0.0) - (self.prev or {}).get(k, 0.0)) for k in set(cur) | set(self.prev or {})) if self.prev is not None else 1.0)
            self.prev = cur
            self.mkt_months += 1
            return
        tot = sum(w.values())
        obs = {}
        num_L = den_L = 0.0
        num_M = 0.0
        for c, x in w.items():
            s, r = st(c, m)
            if s == 'ok':
                obs[c] = (x, r)
            if c in self.dead:
                continue
            if s == 'ok':
                num_L += x * r; den_L += x
            elif s == 'missing':
                num_L += x * -1.0; den_L += x; self.dead.add(c)
            num_M += x * (r if s == 'ok' else (mkt_m if s == 'missing' else 0.0))
        so = sum(x for x, _ in obs.values())
        self.nobs[m] = (len(w), len(obs), round(so / tot, 4) if tot else 0.0)
        if so > 0:
            self.r['S'][m] = sum(x * r for x, r in obs.values()) / so
            cur = {c: x / so for c, (x, _) in obs.items()}
        else:
            self.r['S'][m] = mkt_m; cur = {'__MKT__': 1.0}; self.mkt_months += 1
        self.r['L'][m] = num_L / den_L if den_L > 0 else mkt_m
        spk = sum(x for c, x in w.items() if st(c, m)[0] == 'spike')
        self.r['M'][m] = num_M / (tot - spk) if tot - spk > 0 else mkt_m
        if self.prev is not None:
            self.turn.append(0.5 * sum(abs(cur.get(k, 0.0) - self.prev.get(k, 0.0)) for k in set(cur) | set(self.prev)))
        else:
            self.turn.append(1.0)
        R = self.r['S'][m]
        self.prev = {c: v * (1 + (obs[c][1] if c in obs else (mkt_m if c == '__MKT__' else 0.0))) / (1 + R) for c, v in cur.items()}
        per = 'train' if m <= TRAIN_Z else 'hold'
        for c, v in cur.items():
            self.wsum[per][c] += v
        self.wcnt[per] += 1

    def turnover(self):
        return 12 * sum(self.turn[1:]) / max(1, len(self.turn) - 1)


def load_all():
    U = json.load(open(UNIV)); P = json.load(open(PAIRS))
    ysy = json.load(open(os.path.join(LP, 'yahoo_symbols.json')))
    return U, P, ysy


def cmd_run():
    t0 = time.time()
    import math as _m
    U, P, ysy = load_all()
    ff = M.ff_factors()
    mkt = ff['mkt']
    months = [m for m in mrange(FIRST_M, END_M) if m in mkt]
    ser = {c: yh_series(v[0]) if v[0] else None for c, v in ysy.items()}

    def st(c, m):
        s = ser.get(c)
        if s is None or (s['type'] or 'EQUITY') != 'EQUITY':
            return 'missing', None
        if s['spike'] and m >= s['spike']:
            return 'spike', None
        r = s['ret'].get(m)
        return ('ok', r) if r is not None else ('missing', None)

    ind = ff49()
    indc = {c: ind(U['sic'].get(c)) for c in U['span']}
    # 提出（類似度の記録）を CIK ごとに提出日の順
    rows = {c: sorted(v, key=lambda r: r['filed']) for c, v in P.items()}
    # 先読みの検査のための記録
    look_viol = 0

    def latest(c, m):
        lo, hi = madd(m, -LOOKBACK_M), madd(m, -1)
        best = None
        for r in rows.get(c, []):
            fm = ym(r['filed'])
            if lo <= fm <= hi:
                best = r
            elif fm > hi:
                break
        return best

    def growth(c, a, z):
        g = 1.0
        s = ser.get(c)
        if not s:
            return g
        for k in mrange(madd(a, 1), z):
            r = s['ret'].get(k)
            if r is not None and (not s['spike'] or k < s['spike']):
                g *= 1 + r
        return g

    fill_med = Counter()

    def caps(cs, m):
        out, miss = {}, []
        for c in cs:
            cand = [r for r in rows.get(c, []) if ym(r['filed']) <= madd(m, -1) and r.get('float') and 5e7 <= r['float'] <= 5e12]
            cand = [r for r in cand if (dd(month_end(madd(m, -1))) - dd(r['filed'])).days <= 3 * 366]
            if cand:
                r = cand[-1]
                out[c] = r['float'] * growth(c, ym(r['filed']), madd(m, -1))
            else:
                miss.append(c)
        if miss:
            med = sorted(out.values())[len(out) // 2] if out else 1.0
            for c in miss:
                out[c] = med
            fill_med[m] += len(miss)
        return out

    qsets, qinfo = quality_sets(U)
    books = {}

    def B(name):
        if name not in books:
            books[name] = Book(name)
        return books[name]

    reach = {}
    elig_n = defaultdict(dict)
    tech = defaultdict(lambda: defaultdict(list))
    TECH = {'Hardw', 'Softw', 'Chips'}
    avg_sim = defaultdict(list)
    for m in months:
        mem = U['months'].get(str(m)) or {}
        L_ = {c: latest(c, m) for c in mem}
        for c, r in L_.items():
            if r and ym(r['filed']) > madd(m, -1):
                look_viol += 1
        cap_all = caps([c for c, r in L_.items() if r], m)
        mm = mkt[m]
        for x in MEASURES:
            el = {c: r[x] for c, r in L_.items() if r and r.get(x) is not None}
            elig_n[x][m] = len(el)
            ok = len(el) // 5 >= MIN_PER_Q
            if x == 'cos':
                reach[m] = {'members': len(mem), 'eligible': len(el), 'ok': ok}
                if el:
                    avg_sim[m // 100].append(sorted(el.values())[len(el) // 2])
            if not ok:
                for nm in [f'Q5_{x}', f'U_{x}'] + ([f'Q1_{x}', 'Q5_cos_ew', 'Q45_cos', 'Q5_cos_ex6', 'Q5_cos_ind', 'U_cos_ind', 'U_cos_ex6'] if x == 'cos' else []):
                    B(nm).step(m, None, st, mm)
                if x == 'cos':
                    qs = quality_at(qsets, m)
                    if qs is not None:
                        qm = {c: cap_all.get(c) for c in qs if c in mem}
                        qm = {c: v for c, v in qm.items() if v}
                        B('P2_cos').step(m, qm or None, st, mm); B('QUAL').step(m, qm or None, st, mm)
                continue
            order = sorted(el, key=lambda c: (el[c], int(c)))
            n = len(order)
            q = {c: 5 * i // n + 1 for i, c in enumerate(order)}
            w5 = {c: cap_all[c] for c in order if q[c] == 5}
            B(f'Q5_{x}').step(m, w5, st, mm)
            B(f'U_{x}').step(m, {c: cap_all[c] for c in order}, st, mm)
            if x != 'cos':
                continue
            B('Q1_cos').step(m, {c: cap_all[c] for c in order if q[c] == 1}, st, mm)
            B('Q5_cos_ew').step(m, {c: 1.0 for c in order if q[c] == 5}, st, mm)
            B('Q45_cos').step(m, {c: cap_all[c] for c in order if q[c] >= 4}, st, mm)
            tw = sum(w5.values())
            tech['Q5_cos'][m // 100].append(sum(v for c, v in w5.items() if indc.get(c) in TECH) / tw)
            tu = sum(cap_all[c] for c in order)
            tech['U_cos'][m // 100].append(sum(cap_all[c] for c in order if indc.get(c) in TECH) / tu)
            # 上位6社を外す
            top6 = set(sorted(order, key=lambda c: -cap_all[c])[:6])
            o6 = [c for c in order if c not in top6]
            q6 = {c: 5 * i // len(o6) + 1 for i, c in enumerate(o6)}
            B('Q5_cos_ex6').step(m, {c: cap_all[c] for c in o6 if q6[c] == 5}, st, mm)
            B('U_cos_ex6').step(m, {c: cap_all[c] for c in o6}, st, mm)
            # 業種中立
            byi = defaultdict(list)
            for c in order:
                byi[indc.get(c, 'Other')].append(c)
            pct = {}
            for i_, cs in byi.items():
                if len(cs) < 5:
                    continue
                cs2 = sorted(cs, key=lambda c: (el[c], int(c)))
                for k, c in enumerate(cs2):
                    pct[c] = (k + 0.5) / len(cs2)
            if len(pct) // 5 >= MIN_PER_Q:
                oi = sorted(pct, key=lambda c: (pct[c], int(c)))
                qi = {c: 5 * i // len(oi) + 1 for i, c in enumerate(oi)}
                B('Q5_cos_ind').step(m, {c: cap_all[c] for c in oi if qi[c] == 5}, st, mm)
                B('U_cos_ind').step(m, {c: cap_all[c] for c in oi}, st, mm)
            else:
                B('Q5_cos_ind').step(m, None, st, mm); B('U_cos_ind').step(m, None, st, mm)
            elig_n['cos_ind'][m] = len(pct)
            # 質の良い側から Q1 を外す
            qs = quality_at(qsets, m)
            if qs is not None:
                qm = {c: cap_all.get(c) for c in qs if c in mem and cap_all.get(c)}
                q1 = {c for c in order if q[c] == 1}
                if len(qm) >= MIN_PER_Q:
                    B('P2_cos').step(m, {c: v for c, v in qm.items() if c not in q1}, st, mm)
                    B('QUAL').step(m, qm, st, mm)
                else:
                    B('P2_cos').step(m, qm or None, st, mm); B('QUAL').step(m, qm or None, st, mm)
    print('組み立て', round(time.time() - t0), '秒', flush=True)
    return dict(U=U, P=P, ser=ser, st=st, books=books, mkt=mkt, months=months, reach=reach, elig_n=elig_n, tech=tech, avg_sim=avg_sim,
                qinfo=qinfo, fill_med=fill_med, look_viol=look_viol, indc=indc, ysy=ysy, t0=t0)


# ───────────────────────── 統計と判定 ─────────────────────────
def ev(s, b, turnover=None, a=FIRST_M, z=END_M):
    def safe(d):
        return {k: max(v, -0.999999) for k, v in d.items()}
    s2, b2 = safe(s), safe(b)
    sub = lambda d: {k: v for k, v in d.items() if a <= k <= z}
    d = {'full': M.excess_stats(s2, b2, a, z), 'train': M.excess_stats(s2, b2, a, TRAIN_Z),
         'hold': M.excess_stats(s2, b2, max(a, HOLD_A), z), 'recent_2013_07': M.excess_stats(s2, b2, max(a, RECENT_A), z),
         'roll20': M.rolling(sub(s2), sub(b2), 20, 7), 'dca20': M.dca(sub(s2), sub(b2), 20, 12),
         'maxdd_s': round(M.maxdd(sub(s2)) * 100, 1), 'maxdd_b': round(M.maxdd(sub(b2)) * 100, 1)}
    for nm, st_ in POST_WINDOWS:
        d[nm] = M.excess_stats(s2, b2, max(a, st_), z)
    if turnover is not None:
        d['annual_oneway_turnover'] = round(turnover, 3)
        d['cost_hold'] = M.excess_stats(safe(M.apply_cost(s, turnover, 0.001)), b2, max(a, HOLD_A), z)
    d['wiped_months'] = sorted(k for k, v in s.items() if v <= -1)
    return d


GRADE_ORDER = {'S': 3, 'A': 2, 'B': 1, 'C': 0}


def sgn(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def cmd_result():
    D = cmd_run()
    books, mkt = D['books'], D['mkt']
    spec = [
        # (名前, 系列, 相手, 族, 説明)
        ('P1_cos', 'Q5_cos', 'MKT', 'primary', '最も似ている五分位（余弦・全文）の時価加重 − French Mkt'),
        ('P2_cos', 'P2_cos', 'QUAL', 'primary', '質の良い側（cop_at 上位1/3）から最も似ていない五分位を外した時価加重 − 外さない質の良い側'),
        ('P3_cos', 'Q5_cos_ind', 'MKT', 'primary', '業種中立（49業種の中の百分位）の最も似ている五分位の時価加重 − French Mkt'),
        ('P1_jac', 'Q5_jac', 'MKT', 'secondary', 'Jaccard の最も似ている五分位 − French Mkt'),
        ('P1_minedit', 'Q5_minedit', 'MKT', 'secondary', '最小編集の最も似ている五分位 − French Mkt'),
        ('P1_simple', 'Q5_simple', 'MKT', 'secondary', '単純（文の並べ比べ）の最も似ている五分位 − French Mkt'),
        ('P1_cos_item7', 'Q5_cos_item7', 'MKT', 'secondary', 'Item 7（MD&A）の余弦の最も似ている五分位 − French Mkt'),
        ('P1_cos_item1a', 'Q5_cos_item1a', 'MKT', 'secondary', 'Item 1A（危険要因）の余弦の最も似ている五分位 − French Mkt'),
        ('P1_cos_ew', 'Q5_cos_ew', 'MKT', 'exploratory', 'P1 の等加重 − French Mkt'),
        ('P1_cos_ex6', 'Q5_cos_ex6', 'MKT', 'exploratory', '上位6社を外してから作った P1 − French Mkt'),
        ('P1_cos_top2', 'Q45_cos', 'MKT', 'exploratory', '上位2五分位（Q4+Q5）の時価加重 − French Mkt'),
    ]
    diag = [('Q5_minus_Q1_cos', 'Q5_cos', 'Q1_cos'), ('Q1_cos_vs_U', 'Q1_cos', 'U_cos'), ('U_cos_vs_MKT', 'U_cos', 'MKT'),
            ('P2_cos_vs_MKT', 'P2_cos', 'MKT'), ('QUAL_vs_MKT', 'QUAL', 'MKT')]
    rel = {'P1_cos': 'U_cos', 'P3_cos': 'U_cos_ind', 'P1_jac': 'U_jac', 'P1_minedit': 'U_minedit', 'P1_simple': 'U_simple',
           'P1_cos_item7': 'U_cos_item7', 'P1_cos_item1a': 'U_cos_item1a', 'P1_cos_ew': 'U_cos', 'P1_cos_ex6': 'U_cos_ex6', 'P1_cos_top2': 'U_cos'}

    def span(bk):
        ks = sorted(k for k in books[bk].r['S'])
        return (ks[0], ks[-1]) if ks else (None, None)

    res = {}
    for nm, sr, bm, fam, desc in spec:
        bk = books[sr]
        res[nm] = {'family': fam, 'description': desc, 'series': sr, 'benchmark': 'French Mkt（総リターン）' if bm == 'MKT' else '外さない質の良い側（同じ扱い）',
                   'months_holding_market_unreachable': bk.mkt_months, 'bounds': {}}
        a, z = span(sr)
        for b in ('S', 'L', 'M'):
            s = bk.r[b]
            bench = mkt if bm == 'MKT' else books[bm].r[b]
            res[nm]['bounds'][b] = ev(s, bench, bk.turnover(), a, z)
            if nm in rel and rel[nm] in books:
                rr = books[rel[nm]].r[b]
                res[nm]['bounds'][b]['vs_same_universe'] = {k: M.excess_stats(s, rr, lo, hi) for k, lo, hi in
                                                            (('full', a, z), ('train', a, TRAIN_Z), ('hold', HOLD_A, z), ('post_ssrn_2017', 201701, z))}
    # 観測できた社の割合（年ごと・S の組み立ての記録）
    for nm, sr, *_ in spec:
        bk = books[sr]
        nv = list(bk.nobs.values())
        res[nm]['avg_names_held'] = round(sum(a for a, _, _ in nv) / max(1, len(nv)), 1)
        res[nm]['avg_names_observed'] = round(sum(b for _, b, _ in nv) / max(1, len(nv)), 1)
        for per, lo, hi in (('train', 0, TRAIN_Z), ('hold', HOLD_A, 999999)):
            xs = [w for m, (_, _, w) in bk.nobs.items() if lo <= m <= hi]
            res[nm][f'observed_weight_share_{per}'] = round(sum(xs) / len(xs), 3) if xs else None
    # 族ごとの Holm（生き残りの扱いごと）
    fams = {'primary': ['P1_cos', 'P2_cos', 'P3_cos'], 'secondary': ['P1_jac', 'P1_minedit', 'P1_simple', 'P1_cos_item7', 'P1_cos_item1a']}
    holm = {}
    for b in ('S', 'L'):
        for f, names in fams.items():
            hp = M.holm({n: (res[n]['bounds'][b]['hold'] or {}).get('p') for n in names})
            for n in names:
                holm[(n, b)] = hp.get(n)
    for nm in res:
        g = {}
        for b in ('S', 'L'):
            x = res[nm]['bounds'][b]
            gr, cr = M.grade(x['full'], x['train'], x['hold'], x['roll20'], cost_hold=x.get('cost_hold'), repl=None,
                             family_holm_p=holm.get((nm, b)))
            g[b] = {'grade': gr, 'criteria': cr, 'holm_p_hold': holm.get((nm, b))}
        tS, tL = (res[nm]['bounds']['S']['train'] or {}).get('ex_ann'), (res[nm]['bounds']['L']['train'] or {}).get('ex_ann')
        hS, hL = (res[nm]['bounds']['S']['hold'] or {}).get('ex_ann'), (res[nm]['bounds']['L']['hold'] or {}).get('ex_ann')
        agree = sgn(tS) == sgn(tL) and sgn(hS) == sgn(hL) and sgn(tS) != 0 and sgn(hS) != 0
        if agree:
            off = min(g['S']['grade'], g['L']['grade'], key=lambda k: GRADE_ORDER[k])
            why = 'S と L の符号がそろう→悪い方'
        else:
            off = 'C'
            why = f'判定不能（S と L で符号が割れる: 訓練 S {tS} / L {tL}・保有 S {hS} / L {hL}）→C 扱い'
        res[nm]['grade_by_bound'] = g
        res[nm]['grade'] = off
        res[nm]['grade_note'] = why
    dg = {}
    for nm, a_, b_ in diag:
        dg[nm] = {}
        for b in ('S', 'L', 'M'):
            s = books[a_].r[b]
            bb = mkt if b_ == 'MKT' else books[b_].r[b]
            ks = sorted(s)
            dg[nm][b] = {k: M.excess_stats(s, bb, lo, hi) for k, lo, hi in (('full', ks[0], ks[-1]), ('train', ks[0], TRAIN_Z), ('hold', HOLD_A, ks[-1]),
                                                                             ('post_ssrn_2017', 201701, ks[-1]))}
    return D, res, dg, holm


def git_sha(path):
    import subprocess
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%h', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return None


def compact(x):
    """出力を小さく: 系列そのものは入れない"""
    return x


def cmd_write():
    D, res, dg, holm = cmd_result()
    books, mkt, U = D['books'], D['mkt'], D['U']
    ff = M.ff_factors(); mk = ff['mkt']
    us = books['U_cos'].r['S']
    ks = sorted(k for k in us if k in mk)
    san = {'french_mkt_cagr_1926': round(M.cagr(mk) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(mk, HOLD_A)) * 100, 2),
           'french_mkt_last_month': max(mk),
           'U_cos_S_vs_mkt_monthly_corr': round(M.corr([us[k] for k in ks], [mk[k] for k in ks]), 3),
           'U_cos_S_vs_mkt': M.excess_stats(us, mk, FIRST_M, END_M),
           'lookahead_violations': D['look_viol'],
           'returns_zero_filled': 0,
           'note': 'S は観測できない社・月を外し、L は −100%、M は French Mkt を置く。0 で埋める経路は無い（Book.step）'}
    # 到達
    reach_y = {}
    for m, v in D['reach'].items():
        reach_y.setdefault(str(m // 100), []).append(v)
    reach_s = {y: {'members_min': min(x['members'] for x in v), 'eligible_min': min(x['eligible'] for x in v), 'eligible_max': max(x['eligible'] for x in v),
                   'months_ok': sum(x['ok'] for x in v), 'months': len(v)} for y, v in sorted(reach_y.items())}
    elig = {x: {y: min(n for m, n in D['elig_n'][x].items() if m // 100 == int(y)) for y in reach_y} for x in D['elig_n']}
    # 観測できた重みの割合（U_cos・年）
    obs_y = defaultdict(list)
    for m, (_, _, w) in books['U_cos'].nobs.items():
        obs_y[m // 100].append(w)
    obs_s = {str(y): round(sum(v) / len(v), 3) for y, v in sorted(obs_y.items())}
    # 業種（テック）の割合
    tech = {k: {per: round(sum(sum(v) / len(v) for y, v in d.items() if lo <= y <= hi) / max(1, sum(1 for y in d if lo <= y <= hi)), 3)
                for per, lo, hi in (('train', 1997, 2006), ('hold', 2007, 2026), ('post_2017', 2017, 2026))} for k, d in D['tech'].items()}
    # よく持った社
    def top(bk, per, n=15):
        b = books[bk]
        tot = b.wcnt[per] or 1
        xs = sorted(b.wsum[per].items(), key=lambda kv: -kv[1])[:n]
        return [(U['names'].get(c, c) if c != '__MKT__' else '(市場)', round(v / tot, 4)) for c, v in xs]
    tops = {bk: {per: top(bk, per) for per in ('train', 'hold')} for bk in ('Q5_cos', 'Q1_cos', 'Q5_cos_ind')}
    sim_med = {str(y): round(sorted(v)[len(v) // 2], 4) for y, v in sorted(D['avg_sim'].items())}
    # 格の一覧
    tested = []
    for nm, r in res.items():
        tested.append({'name': nm, 'family': r['family'], 'grade': r['grade'], 'graded': True})
    for nm in dg:
        tested.append({'name': nm, 'family': 'diagnostic', 'grade': None, 'graded': False})
    Uu = json.load(open(UNIV))
    ysy = D['ysy']
    obj = {
        'angle': 'lazy_prices',
        'prereg': 'out/mw_lazy_prices_prereg.json',
        'prereg_commit': git_sha('out/mw_lazy_prices_prereg.json'),
        'question': json.load(open(PREREG))['question'],
        'periods': {'full': f'{FIRST_M}〜{END_M}', 'train': f'〜{TRAIN_Z}', 'hold': f'{HOLD_A}〜', 'recent': f'{RECENT_A}〜',
                    'post': {k: v for k, v in POST_WINDOWS}},
        'benchmark': 'French Mkt（Mkt-RF + RF・総リターン）。P2 は外さない質の良い側（同じ生き残りの扱い）',
        'grading_rule': 'S と L のそれぞれで mw_common.grade。訓練と保有の超過の符号が S と L でそろうときだけ悪い方の格、割れたら判定不能＝C（課題文の規則）',
        'tested': tested,
        'n_tested': len(tested),
        'n_graded': sum(1 for t in tested if t['graded']),
        'strategies': res,
        'diagnostics': dg,
        'sanity': san,
        'reachability_by_year': reach_s,
        'eligible_min_by_measure_year': elig,
        'observed_weight_share_U_cos_S_by_year': obs_s,
        'median_cos_similarity_by_year': sim_med,
        'tech_share_Hardw_Softw_Chips': tech,
        'top_holdings_avg_weight': tops,
        'universe': {'n_cik': Uu['n_cik'], 'via': Uu['via'], 'mapped_share_by_year': Uu['mapped_share_by_year'],
                     'n_unmapped_tickers': len(Uu['unmapped'])},
        'yahoo_symbol_paths': dict(Counter(v[1] for v in ysy.values())),
        'yahoo_series_found': sum(1 for c in ysy if D['ser'].get(c)),
        'cap_filled_with_median_member_months': sum(D['fill_med'].values()),
        'quality_sets_P2': {str(k): v for k, v in sorted(D['qinfo'].items())},
        'runtime_s': round(time.time() - D['t0']),
    }
    p = M.save(RESULT, obj)
    print('書いた', p)
    for nm, r in res.items():
        b = r['bounds']
        print(f"{nm:14s} {r['grade']}  S: 訓練 {fmt(b['S']['train'])} 保有 {fmt(b['S']['hold'])}  L: 訓練 {fmt(b['L']['train'])} 保有 {fmt(b['L']['hold'])}  {r['grade_note'][:40]}")
    for nm, d in dg.items():
        print(f"  診断 {nm:18s} S 全 {fmt(d['S']['full'])} 訓練 {fmt(d['S']['train'])} 保有 {fmt(d['S']['hold'])} 2017〜 {fmt(d['S']['post_ssrn_2017'])}")


def fmt(x):
    return f"{x['ex_ann']:+.2f}(t{x['t']})" if x else '—'


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
    elif cmd == 'prices':
        cmd_prices()
    elif cmd == 'run':
        cmd_write()
    else:
        print(__doc__)
