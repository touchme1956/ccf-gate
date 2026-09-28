#!/usr/bin/env python3
"""night/nx_lazy_data.py — 角度 nx_lazy（10-K の本文が前年とどれだけ変わったか）のデータを作るだけの道具（成績は計算しない）

事前登録: out/nx_lazy_prereg.json（測る前に書いた）。出典の論文: Cohen, Malloy & Nguyen (2020, JF)『Lazy Prices』。
この道具がすること
  universe  : 時点の S&P 500 構成銘柄（fja05680/sp500 の日々の構成表・1996-01-02〜）と、現在の構成表（CIK つき）と
              SEC の現在のティッカー表・名前の一覧（cik-lookup-data.txt）・EDGAR の全文検索（efts・2001年〜・キャッシュつき）から、
              10-K を取りに行く会社（CIK）の候補（A 今の構成銘柄／B 記号が今もある過去の構成銘柄／C A の前身／D 名前を変えた生き残り）と取得の窓を作る
              → out/_nx_cache/nx_lazy_universe.json（形だけを表示: 候補の数・窓・ティッカーの対応の種類）
  build     : 候補の CIK ごとに EDGAR の提出一覧（submissions JSON）から 10-K を並べ、本文の主文書（と EX-13）を取り、
              **本文は保存せず**、次の特徴量だけを out/_nx_cache/nx_lazy/{cik}.json に残す:
                語数・異なり語数・LM（Loughran-McDonald 2011 の2009年版の一覧）の語の数・前年の 10-K との類似度
                （コサイン・Jaccard・語の差分〔最小編集距離の近似〕・文の差分〔Simple〕）・差分の中の LM の語の数・
                Item 1A（リスク要因）と Item 7（MD&A）の類似度・EX-13 を足した類似度・表紙の浮動株の時価（public float）・
                本文が名乗る株式の記号（ティッカー。会社の同定だけに使う）
              差分を取るための一時ファイルは作ってすぐ消す（本文をディスクに残さない）
  trial     : 動作確認（20社ほど）。所要時間・転送量・抜き出しの成功率だけを表示する
  status    : 作ったデータの形だけを表示する（件数・欠け・抜き出しの成功率）
  panel     : 事前登録の約束どおりに、月末ごとの構成銘柄（CIK）と、10-K ごとの「並べる月」の表を作る
              → out/_nx_cache/nx_lazy_members.json / nx_lazy_signals.csv（**株価は取らない・成績は計算しない**）

約束（事前登録と同じ）
- SEC の User-Agent は hachimon_fetch.py の HDRS と同じ形（中の EMAIL をそのまま読む）。全体で 8 req/s 以下（10 req/s の制限を守る）
- 欠測は 0 と読まない（絶対のルール7）。取れなかった欄は None、理由は flags へ
- 平均・t・シャープ・累積・勝率は計算しない・表示しない
"""
import sys, os, re, io, csv, json, gzip, time, html, math, datetime, hashlib, subprocess, tempfile, argparse, collections, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

BASE = N.BASE
CACHE = N.CACHE
OUTDIR = os.path.join(CACHE, 'nx_lazy')
VERSION = 'nx_lazy_data v3 (2026-09-28)'
_EMAIL = re.search(r'^EMAIL\s*=\s*"([^"]+)"', open(os.path.join(BASE, 'hachimon_fetch.py'), encoding='utf-8').read(), re.M).group(1)
HDRS = {"User-Agent": f"hachimon-gate {_EMAIL}"}  # hachimon_fetch.py の HDRS と同じ形
MIN_INTERVAL = 0.125  # 全プロセス合計で 8 req/s
FORMS_ANNUAL = {'10-K', '10-K405', '10-KSB', '10-KSB40', '10-KT', '10-KT405'}  # 前年の文書として使える様式
FORMS_SIGNAL = {'10-K', '10-K405', '10-KSB', '10-KSB40'}  # 信号を作る様式（移行期間の 10-KT は信号にしない）
MAX_DOC_BYTES = 80_000_000
FJA = 'https://raw.githubusercontent.com/fja05680/sp500/master/'
FJA_HIST = FJA + 'S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv'
FJA_CUR = FJA + 'sp500.csv'
LM_URL = 'https://drive.usercontent.google.com/download?id=1iq2RUf8qGFEAk1g8wQntP3habOnR3fXF&export=download&confirm=t'
# LM の StopWords_Generic（121語・sraf.nd.edu/textual-analysis/stopwords/）
STOP_URL = 'https://drive.usercontent.google.com/download?id=0B4niqV00F3mseWZrUk1YMGxpVzQ&export=download&confirm=t&resourcekey=0-wJUCRexl9jHUFpzQjTfcEQ'
LM_CATS = ['Negative', 'Positive', 'Uncertainty', 'Litigious', 'Constraining', 'Strong_Modal', 'Weak_Modal']
LM_KEY = {'Negative': 'lm_neg', 'Positive': 'lm_pos', 'Uncertainty': 'lm_unc', 'Litigious': 'lm_lit',
          'Constraining': 'lm_con', 'Strong_Modal': 'lm_strong', 'Weak_Modal': 'lm_weak'}
EDGAR_START = '1995-01-01'

# ───────────────────────── SEC への取得（全プロセスで速度を共有） ─────────────────────────
_LOCK = None
_LAST = None


def _init_limiter(lock, last):
    global _LOCK, _LAST
    _LOCK, _LAST = lock, last


def _wait_turn():
    if _LOCK is None:
        time.sleep(MIN_INTERVAL)
        return
    with _LOCK:
        now = time.time()
        wait = _LAST.value + MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        _LAST.value = time.time()


STATS = collections.Counter()


class TooLarge(Exception):
    pass


def sec_get(url, tries=6, max_bytes=MAX_DOC_BYTES):
    """SEC から取る（gzip で受け取り、展開した bytes を返す）。429/5xx/通信失敗は間をあけて再試行"""
    import urllib.request, urllib.error
    err = None
    for i in range(tries):
        _wait_turn()
        try:
            req = urllib.request.Request(url, headers={**HDRS, 'Accept-Encoding': 'gzip, deflate'})
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read(max_bytes + 1)
                enc = r.headers.get('Content-Encoding', '')
            STATS['requests'] += 1
            STATS['bytes_wire'] += len(b)
            if enc == 'gzip':
                b = gzip.decompress(b)
            if len(b) > max_bytes:
                raise TooLarge(f'too large {len(b)}')
            STATS['bytes'] += len(b)
            return b
        except TooLarge:
            raise  # 大きすぎる文書は取り直さない（flags に残る）
        except urllib.error.HTTPError as e:
            err = e
            if e.code == 404:
                raise
            time.sleep(min(60, 2 ** (i + 1)) + random.random())
        except Exception as e:  # noqa
            err = e
            time.sleep(min(60, 2 ** (i + 1)) + random.random())
    raise RuntimeError(f'取得失敗 {url}: {err}')


def sec_cached(url, name, max_age_days=7):
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400 and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    b = sec_get(url)
    tmp = f'{p}.{os.getpid()}.tmp'
    open(tmp, 'wb').write(b)
    os.replace(tmp, p)
    return b


# ───────────────────────── 構成銘柄と候補 ─────────────────────────
def norm_tk(t):
    return t.strip().upper().replace('.', '-').replace('/', '-')


def sp_history():
    """[(日付str, set(ticker))] を日付順に（fja05680/sp500 の日々の構成表）"""
    b = N.get(FJA_HIST, name='sp500_SandP_500_Historical_Components_and_Changes_(Updated).csv', max_age_days=60)
    rows = list(csv.DictReader(io.StringIO(b.decode('utf-8', 'ignore'))))
    return [(r['date'], set(norm_tk(x) for x in r['tickers'].split(',') if x.strip())) for r in rows]


def sp_current():
    b = N.get(FJA_CUR, name='sp500_sp500.csv', max_age_days=60)
    return list(csv.DictReader(io.StringIO(b.decode('utf-8', 'ignore'))))


def sec_tickers():
    j = json.loads(sec_cached('https://www.sec.gov/files/company_tickers.json', 'sec_company_tickers.json', 30))
    t2c, c2t = {}, collections.defaultdict(list)
    for v in j.values():
        t = norm_tk(v['ticker'])
        t2c[t] = (int(v['cik_str']), v['title'])
        c2t[int(v['cik_str'])].append(t)
    return t2c, c2t


def ticker_spans(hist):
    spans = collections.defaultdict(list)
    prev = set()
    last_date = hist[-1][0]
    for d, s in hist:
        for t in s - prev:
            spans[t].append([d, None])
        for t in prev - s:
            spans[t][-1][1] = d  # この日には居ない（前の行の日まで居た）
        prev = s
    for t in spans:
        for sp in spans[t]:
            if sp[1] is None:
                sp[1] = '9999-12-31'
    return spans, last_date


def _minus_months(d, m):
    y, mo = int(d[:4]), int(d[5:7])
    k = y * 12 + (mo - 1) - m
    return f'{k // 12:04d}-{k % 12 + 1:02d}-01'


def fts_claimants(tk, a, z):
    """EDGAR の全文検索（2001年以降の索引）で、期間 [a, z] の 10-K に『symbol {tk}』と書いた会社（CIK → 当たりの数）。
    会社の同定の候補を探すだけ（構成に入れるかは本文の記号で決める）"""
    a = max(a, '2001-01-01')
    if z < a:
        return {}
    z = min(z, datetime.date.today().isoformat())
    import urllib.parse

    def q(term):
        u = ('https://efts.sec.gov/LATEST/search-index?q=' + urllib.parse.quote(term) +
             f'&forms=10-K,10-K405&dateRange=custom&startdt={a}&enddt={z}')
        os.makedirs(os.path.join(CACHE, 'sec_fts'), exist_ok=True)
        j = json.loads(sec_cached(u, 'sec_fts/' + hashlib.sha1(u.encode()).hexdigest()[:20] + '.json', 60))
        cnt = collections.Counter()
        for h in (j.get('hits') or {}).get('hits', []):
            for c in (h.get('_source') or {}).get('ciks') or []:
                cnt[int(c)] += 1
        return dict(cnt)
    try:
        r = q(f'"symbol {tk}"')
        # 『symbol XOM』と書かない会社がある（ExxonMobil は『common stock (XOM)』）。記号が英語の語でなく3字以上なら記号だけで引き直す
        if not r and len(tk) >= 3 and tk.lower() not in lm_words():
            r = q(tk)
        return r
    except Exception:  # noqa
        return None


_LMW = None


def lm_words():
    """LM の辞書の全語（英語の語か否かの判定だけに使う）"""
    global _LMW
    if _LMW is None:
        b = N.get(LM_URL, name='lm_master_1993-2025.csv', max_age_days=3650)
        _LMW = {r['Word'].lower() for r in csv.DictReader(io.StringIO(b.decode('utf-8', 'ignore')))}
    return _LMW


def build_universe(use_fts=True):
    """候補の CIK（10-K を取りに行く会社）と、株価を引く記号の候補を作る。構成に入れるかは後で本文の記号で決める（panel）。
    A = 今の構成銘柄（fja の sp500.csv の CIK）／B = 過去の構成銘柄のうち、その記号が今も SEC の記号表にある会社／
    C = A のうち CIK の年次報告が構成の時期より遅く始まる会社の前身（名前が同じ別の CIK、または全文検索でその記号を名乗った CIK）／
    D = 今の記号表に無い過去の構成銘柄の記号を、全文検索で名乗った会社のうち、今の記号表に CIK がある会社（名前を変えて生き残った会社）。
    取る 10-K は A・B・D は 1995 年以降の全部、C は後継の最初の年次報告まで"""
    hist = sp_history()
    spans, last_date = ticker_spans(hist)
    cur = sp_current()
    t2c, c2t = sec_tickers()
    cand = {}

    def add(cik, tk, via, name, window=None, price=None, extra=None):
        c = cand.setdefault(str(cik), {'cik': int(cik), 'name': name, 'tickers': [], 'via': [], 'windows': [],
                                       'price_tickers': []})
        if tk and tk not in c['tickers']:
            c['tickers'].append(tk)
        if via not in c['via']:
            c['via'].append(via)
        c['windows'].append(window or [EDGAR_START, '9999-12-31'])
        for t in (price or []):
            if t not in c['price_tickers']:
                c['price_tickers'].append(t)
        if extra:
            c.update(extra)
        return c

    cur_syms = set()
    for r in cur:
        tk = norm_tk(r['Symbol'])
        cur_syms.add(tk)
        cik = int(r['CIK'].strip().lstrip('0') or 0)
        da = (r.get('Date added') or '').strip() or EDGAR_START
        first = spans[tk][0][0] if tk in spans else da
        c = add(cik, tk, 'A_current_member', r['Security'], price=[tk] + c2t.get(cik, []))
        c['date_added'] = min(c.get('date_added', '9999'), da, first)
        c.setdefault('wiki_date_added', {})[tk] = da
    for tk, sps in spans.items():
        if tk in cur_syms or tk not in t2c:
            continue
        cik, title = t2c[tk]
        c = add(cik, tk, 'B_former_member_same_ticker_now', title, price=c2t.get(cik, []))
        # 記号を名乗る文が無い年の代わり: その期間（2001年以降）の全文検索で当たりが最も多い会社か（panel で5件以上なら構成とみなす）
        if use_fts:
            for a, z in sps:
                if z < '2001-06-01':
                    continue
                res = fts_claimants(tk, _minus_months(a, 13), z) or {}
                if res:
                    top = max(res.values())
                    n = res.get(cik, 0)
                    c.setdefault('fts_for_own_ticker', []).append([tk, n, n == top and n > 0, a, z])
    stats = {'sp_rows': len(hist), 'sp_first': hist[0][0], 'sp_last': last_date, 'distinct_sp_tickers': len(spans),
             'current_members_rows': len(cur),
             'A': sum(1 for c in cand.values() if 'A_current_member' in c['via']),
             'B_only': sum(1 for c in cand.values() if c['via'] == ['B_former_member_same_ticker_now'])}
    obj = {'generated': datetime.date.today().isoformat(), 'version': VERSION, 'stats': stats,
           'known_tickers': sorted(set(spans) | set(t2c)), 'candidates': cand}
    add_predecessors(obj, use_fts)
    # D: 今の記号表に無い過去の構成銘柄の記号（2001年以降の期間）→ 全文検索で名乗った会社のうち、今の記号表に CIK がある会社
    unm = sorted(t for t in spans if t not in t2c and t not in cur_syms)
    stats['sp_tickers_unmapped_by_current_symbol'] = len(unm)
    fts_log = {}
    if use_fts:
        for tk in unm:
            for a, z in spans[tk]:
                if z < '2001-06-01':
                    continue
                res = fts_claimants(tk, _minus_months(a, 13), z)
                fts_log[f'{tk}|{a}|{z}'] = res
                if not res:
                    continue
                top = max(res.values())
                for cik, n in res.items():
                    if cik not in c2t or n < max(2, 0.5 * top):
                        continue  # 今の記号表に無い会社は株価が引けない（生き残っていない）ので取らない
                    prev = cand.get(str(cik), {}).get('fts_tickers', [])
                    add(cik, None, 'D_fts_renamed_survivor', t2c[c2t[cik][0]][1], price=c2t.get(cik, []),
                        extra={'fts_tickers': sorted(set(prev) | {tk})})
    obj['fts_log'] = fts_log
    for c in cand.values():
        ws = sorted(c['windows'])
        out = []
        for a, z in ws:
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], z)
            else:
                out.append([a, z])
        c['windows'] = out
        c['sec_tickers'] = c2t.get(c['cik'], [])
    stats['candidates'] = len(cand)
    stats['C'] = sum(1 for c in cand.values() if 'C_predecessor_of_current' in c['via'])
    stats['D'] = sum(1 for c in cand.values() if 'D_fts_renamed_survivor' in c['via'])
    stats['fts_queries'] = len(fts_log)
    stats['fts_failed'] = sum(1 for v in fts_log.values() if v is None)
    p = os.path.join(CACHE, 'nx_lazy_universe.json')
    json.dump(obj, open(p, 'w'), ensure_ascii=False)
    return obj, p


_SUFFIX = {'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'PLC', 'NEW', 'DE', 'THE', 'HOLDINGS', 'HOLDING', 'GROUP', 'LP',
           'LLC', 'NV', 'SA', 'AG', 'INCORPORATED', 'LIMITED', 'MD', 'NY', 'NJ', 'PA', 'OH', 'VA', 'TX', 'CA', 'DEL', 'NC'}


def norm_name(nm):
    t = re.sub(r'/[A-Z]{2,3}/?', ' ', (nm or '').upper())
    t = re.sub(r'[^A-Z0-9 ]', ' ', t.replace('&', ' AND '))
    ws = [w for w in t.split() if w]
    while ws and ws[-1] in _SUFFIX:
        ws.pop()
    while ws and ws[0] == 'THE':
        ws.pop(0)
    return ' '.join(ws)


def add_predecessors(uni, use_fts=True):
    """A のうち、CIK の最初の年次報告が構成に入った時期（date_added と記号の初出の早い方、1995年より前なら 1995-01）より
    19か月以上あとの会社（持株会社化・分割・合併で CIK が新しい）について、前身の候補を足す:
      (1) SEC の名前の一覧（cik-lookup-data.txt）で、語尾の INC/CORP/HOLDINGS 等を除いた名前が今の名前か旧名と一致する別の CIK
      (2) 全文検索（2001年以降）で、後継の今の記号を [構成の始まり−13か月, 後継の最初の年次報告] の 10-K で名乗った CIK（当たり2件以上）
    前身の候補の構成は、本文が名乗る記号でしか認めない（tier C）。株価は後継の記号で引く"""
    b = sec_cached('https://www.sec.gov/Archives/edgar/cik-lookup-data.txt', 'sec_cik_lookup.txt', 60)
    lookup = collections.defaultdict(set)
    for ln in b.decode('latin-1').splitlines():
        parts = ln.rsplit(':', 2)
        if len(parts) == 3 and parts[1].strip().isdigit():
            lookup[norm_name(parts[0]).replace(' ', '')].add(int(parts[1]))  # 空白の違い（ExxonMobil / Exxon Mobil）を無視
    added = []
    for c in list(uni['candidates'].values()):
        if 'A_current_member' not in c['via']:
            continue
        fl, meta = list_annual_filings(c['cik'])
        first = fl[0]['filed'] if fl else None
        w0 = max(EDGAR_START, _minus_months(c.get('date_added') or EDGAR_START, 13))
        if first is not None and first <= _minus_months(w0, -19):
            continue
        end = first or '9999-12-31'
        names = [meta.get('name')] + [x.get('name') for x in (meta.get('formerNames') or [])] + [c.get('name')]
        pcs = {}
        for nm in names:
            k = norm_name(nm).replace(' ', '')
            if k:
                for pc in lookup.get(k, set()):
                    pcs[pc] = 'name'
        fts_for = collections.defaultdict(list)
        if use_fts:
            for tk in c['tickers']:
                res = fts_claimants(tk, w0, end) or {}
                top = max(res.values()) if res else 0
                for pc, n in res.items():
                    if n >= max(2, 0.5 * top):  # 当たりが最も多い会社の半分以上だけ（他社の 10-K が記号に触れただけの会社を除く）
                        fts_for[pc].append([tk, n, n == top])
                        if pc not in pcs:
                            pcs[pc] = f'fts:{tk}:{n}'
        pcs.pop(c['cik'], None)
        for pc, how in sorted(pcs.items()):
            try:
                pfl, pmeta = list_annual_filings(pc)
            except Exception:  # noqa
                continue
            use = [f for f in pfl if f['filed'] <= end]
            if len(use) < 2:
                continue
            key = str(pc)
            rec = uni['candidates'].setdefault(key, {'cik': pc, 'name': pmeta.get('name'), 'tickers': [], 'via': [],
                                                     'windows': [], 'price_tickers': []})
            if 'C_predecessor_of_current' not in rec['via']:
                rec['via'].append('C_predecessor_of_current')
            rec['windows'].append([EDGAR_START, end])
            rec.setdefault('successors', []).append(c['cik'])
            if fts_for.get(pc):
                rec['fts_for_successor_tickers'] = rec.get('fts_for_successor_tickers', []) + fts_for[pc]  # [記号, 当たり, 最多か]
            for t in c.get('price_tickers') or c['tickers']:
                if t not in rec['price_tickers']:
                    rec['price_tickers'].append(t)
            added.append({'successor': c['cik'], 'successor_name': c['name'], 'predecessor': pc, 'predecessor_name': pmeta.get('name'),
                          'how': how, 'n_annual_before_successor': len(use), 'successor_first_annual': first})
    uni['stats']['predecessors_added'] = len(added)
    uni['predecessors'] = added
    return added


def load_universe():
    p = os.path.join(CACHE, 'nx_lazy_universe.json')
    if not os.path.exists(p):
        return build_universe()[0]
    return json.load(open(p))


# ───────────────────────── LM の一覧 ─────────────────────────
_LM = None


def lm_lists():
    """LM 2011 の感情の一覧のうち、旗が 2009（原本の一覧）の語だけ（後から足された語は使わない＝後知恵を避ける）"""
    global _LM
    if _LM is None:
        b = N.get(LM_URL, name='lm_master_1993-2025.csv', max_age_days=3650)
        rows = csv.DictReader(io.StringIO(b.decode('utf-8', 'ignore')))
        _LM = {c: set() for c in LM_CATS}
        for r in rows:
            for c in LM_CATS:
                if (r.get(c) or '').strip() == '2009':
                    _LM[c].add(r['Word'].lower())
    return _LM


_STOP = None


def stopwords():
    global _STOP
    if _STOP is None:
        b = N.get(STOP_URL, name='lm_stop_ZVUQzQjTfcEQ_generic.txt', max_age_days=3650)
        _STOP = {w.strip().lower() for w in b.decode('latin-1').splitlines() if w.strip()}
        assert 100 <= len(_STOP) <= 200, len(_STOP)
    return _STOP


def drop_stop(cnt):
    st = stopwords()
    return collections.Counter({k: v for k, v in cnt.items() if k not in st})


# ───────────────────────── 本文の取り出し ─────────────────────────
_RE_IXHDR = re.compile(r'<ix:header>.*?</ix:header>', re.S | re.I)
_RE_DROP = re.compile(r'<(script|style|head|title)\b[^>]*>.*?</\1\s*>', re.S | re.I)
_RE_COMMENT = re.compile(r'<!--.*?-->', re.S)
_RE_TABLE = re.compile(r'<table\b[^>]*>.*?</table\s*>', re.S | re.I)
_RE_BLOCK = re.compile(r'<\s*/?\s*(p|div|br|tr|li|ul|ol|h[1-6]|center|blockquote|pre|hr|dd|dt|dl|td|th|page)\b[^>]*>', re.I)
_RE_TAG = re.compile(r'<[^>]+>')
_RE_UU = re.compile(r'^begin \d{3} .*?^end\s*$', re.S | re.M)
_RE_SGML = re.compile(r'<\s*/?\s*(S|C|F\d+|FN|CAPTION|PAGE|R\d*)\s*>', re.I)


def _num_share(s):
    d = sum(ch.isdigit() for ch in s)
    a = sum(ch.isalpha() for ch in s)
    return d / (d + a) if d + a else 0.0


def _strip_tags(s):
    s = _RE_BLOCK.sub('\n', s)
    s = _RE_TAG.sub('', s)
    s = html.unescape(s).replace('\xa0', ' ').replace('​', '')
    return s


def to_text(raw, drop_numeric_tables=True):
    """HTML でも SGML の文字列でも、本文の文字列にする。数字の割合が 15% を超える表は落とす（LM の stage one と論文の約束）"""
    s = raw
    s = _RE_UU.sub(' ', s)
    s = _RE_IXHDR.sub(' ', s)
    s = _RE_COMMENT.sub(' ', s)
    s = _RE_DROP.sub(' ', s)
    s = _RE_SGML.sub('\n', s)
    n_tab = n_drop = 0

    def tab(m):
        nonlocal n_tab, n_drop
        n_tab += 1
        t = _strip_tags(m.group(0))
        if drop_numeric_tables and _num_share(t) > 0.15:
            n_drop += 1
            return '\n'
        return '\n' + t + '\n'
    s = _RE_TABLE.sub(tab, s)
    s = _strip_tags(s)
    lines = [re.sub(r'[ \t\r\f\v]+', ' ', ln).strip() for ln in s.split('\n')]
    s = '\n'.join(ln for ln in lines if ln)
    return s, n_tab, n_drop


_RE_WORD = re.compile(r'[a-z]+')


def words(text):
    return _RE_WORD.findall(text.lower())


_RE_SENT = re.compile(r'(?<=[.!?;])\s+(?=[A-Z0-9("“])')


def sentences(text):
    """文に分ける。改行は無視する（古い .txt は80字で折り返してあり、HTML も年によって改行の位置が変わるため）"""
    flat = re.sub(r'\s+', ' ', text)
    out = []
    for s in _RE_SENT.split(flat):
        w = words(s)
        if w:
            out.append(' '.join(w))
    return out


# ───────────────────────── 節（Item 1A・Item 7） ─────────────────────────
_SEC = {
    'item1a': (re.compile(r'(?im)^\s*item[\s.]*1a\b'), re.compile(r'(?im)^\s*item[\s.]*(1b|2)\b')),
    'item7': (re.compile(r'(?im)^\s*item[\s.]*7(?![0-9a-z])'), re.compile(r'(?im)^\s*item[\s.]*(7a|8)\b')),
}


def section(text, key):
    """見出しの行から次の見出しの行まで。目次の行を避けるため、最も長い区間を取る。200語未満は無いものとする"""
    st, en = _SEC[key]
    starts = [m.start() for m in st.finditer(text)]
    ends = [m.start() for m in en.finditer(text)]
    best = None
    for a in starts:
        z = next((e for e in ends if e > a), None)
        if z is None:
            continue
        if best is None or z - a > best[1] - best[0]:
            best = (a, z)
    if not best:
        return None
    sec = text[best[0]:best[1]]
    return sec if len(words(sec)) >= 200 else None


# ───────────────────────── 類似度 ─────────────────────────
def cos_sim(c1, c2):
    if not c1 or not c2:
        return None
    dot = sum(v * c2.get(k, 0) for k, v in c1.items())
    n1 = math.sqrt(sum(v * v for v in c1.values()))
    n2 = math.sqrt(sum(v * v for v in c2.values()))
    return dot / (n1 * n2) if n1 and n2 else None


def jac_sim(c1, c2):
    if not c1 or not c2:
        return None
    s1, s2 = set(c1), set(c2)
    u = len(s1 | s2)
    return len(s1 & s2) / u if u else None


def _diff_lines(a_lines, b_lines, tmpdir):
    """GNU diff の通常出力から、消えた行と足された行を返す（一時ファイルはこの関数の中で消す）"""
    fa, fb = os.path.join(tmpdir, 'a.txt'), os.path.join(tmpdir, 'b.txt')
    try:
        with open(fa, 'w') as f:
            f.write('\n'.join(a_lines) + '\n')
        with open(fb, 'w') as f:
            f.write('\n'.join(b_lines) + '\n')
        r = subprocess.run(['diff', fa, fb], capture_output=True, text=True, timeout=600)
        dels, adds = [], []
        for ln in r.stdout.split('\n'):
            if ln.startswith('< '):
                dels.append(ln[2:])
            elif ln.startswith('> '):
                adds.append(ln[2:])
        return dels, adds
    finally:
        for f in (fa, fb):
            try:
                os.remove(f)
            except OSError:
                pass


def diff_features(prev_doc, cur_doc, tmpdir, lm):
    """語の差分（最小編集距離の近似＝挿入と削除だけの距離）と文の差分（Simple）と、差分の中の LM の語"""
    out = {}
    n1, n2 = len(prev_doc['tokens']), len(cur_doc['tokens'])
    d, a = _diff_lines(prev_doc['tokens'], cur_doc['tokens'], tmpdir)
    out['minedit'] = 1 - (len(d) + len(a)) / (n1 + n2) if n1 + n2 else None
    ds, as_ = _diff_lines(prev_doc['sents'], cur_doc['sents'], tmpdir)
    wd = [w for s in ds for w in s.split(' ')]
    wa = [w for s in as_ for w in s.split(' ')]
    avg = (n1 + n2) / 2
    out['simple'] = 1 - (len(wd) + len(wa)) / avg / 2 if avg else None  # 変わった語 ÷ 平均の長さ を [0,1] の類似度へ（単調な変換＝順位は論文と同じ）
    out['chg_words_added'] = len(wa)
    out['chg_words_deleted'] = len(wd)
    ca, cd = collections.Counter(wa), collections.Counter(wd)
    for cat in ('Negative', 'Positive', 'Uncertainty', 'Litigious'):
        out[f'chg_{cat[:3].lower()}_added'] = sum(v for k, v in ca.items() if k in lm[cat])
        out[f'chg_{cat[:3].lower()}_deleted'] = sum(v for k, v in cd.items() if k in lm[cat])
    return out


# ───────────────────────── 表紙（浮動株の時価）と記号 ─────────────────────────
_MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'
_RE_DATE = re.compile(rf'({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})', re.I)
_RE_MONEY = re.compile(r'\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(trillion|billion|million|thousand)?', re.I)
_MULT = {'trillion': 1e12, 'billion': 1e9, 'million': 1e6, 'thousand': 1e3}


def cover_float(text):
    """表紙の『非関係者が持つ議決権株式の時価の合計』（public float）。句の最初の出現の後ろ 900 字で、単位をかけて100万ドル以上の最初の金額"""
    low = text[:60000]
    m = re.search(r'aggregate\s+market\s+value', low, re.I)
    if not m:
        return None, None, 'no_phrase'
    win = low[max(0, m.start() - 400): m.start() + 900]
    after = low[m.start(): m.start() + 900]
    # 句の後ろの金額のうち、単位をかけて 100万ドル以上の最初のもの（1株の終値 $69.91 や額面 $0.0001 を飛ばす）
    v = None
    seen = 0
    for mm in _RE_MONEY.finditer(after):
        seen += 1
        try:
            x = float(mm.group(1).replace(',', ''))
        except ValueError:
            continue
        unit = (mm.group(2) or '').lower()
        x *= _MULT.get(unit, 1.0)
        if not unit and x < 1e5 and re.search(r'in\s+(millions|thousands)', after[:mm.start() + 60], re.I):
            x *= 1e6 if 'million' in after[:mm.start() + 60].lower() else 1e3
        if x >= 1e6:
            v = x
            break
    if v is None:
        return None, None, 'no_amount' if not seen else 'only_small_amounts'
    dm = None
    best = None
    for d in _RE_DATE.finditer(win):
        dist = abs(d.start() - (m.start() - max(0, m.start() - 400)))
        if best is None or dist < best:
            best, dm = dist, d
    asof = None
    if dm:
        try:
            asof = datetime.datetime.strptime(f'{dm.group(1)} {dm.group(2)} {dm.group(3)}', '%B %d %Y').date().isoformat()
        except ValueError:
            asof = None
    if not (1e6 <= v <= 1e13):
        return None, asof, f'out_of_range:{v:.3g}'
    return v, asof, 'ok'


_RE_AMV_RAW = re.compile(r'aggregate(?:\s|&nbsp;|&#160;|&#xa0;|<[^>]{0,300}>)+market(?:\s|&nbsp;|&#160;|&#xa0;|<[^>]{0,300}>)+value', re.I)
_RE_IXFLOAT = re.compile(r'<ix:nonFraction\b([^>]*name="dei:EntityPublicFloat"[^>]*)>(.*?)</ix:nonFraction>', re.S | re.I)


def ix_float(raw):
    m = _RE_IXFLOAT.search(raw)
    if not m:
        return None
    attrs, inner = m.group(1), _RE_TAG.sub('', m.group(2))
    try:
        v = float(html.unescape(inner).replace(',', '').strip())
    except ValueError:
        return None
    sc = re.search(r'scale="(-?\d+)"', attrs)
    if sc:
        v *= 10 ** int(sc.group(1))
    return v


_SYM_PATTERNS = [
    re.compile(r'(?i:under\s+the\s+(?:trading\s+|ticker\s+|stock\s+)?symbols?)\s*[:\-–]?\s*["“”\'‘’(]?\s*([A-Z][A-Za-z.\-]{0,6})'),
    re.compile(r'(?i:(?:ticker|trading|stock)\s+symbols?)\s*(?:is|of|:|was)?\s*["“”\'‘’(]?\s*([A-Z][A-Z.\-]{0,6})\b'),
    re.compile(r'\((?:NYSE|Nasdaq|NASDAQ|AMEX|NYSE\s+American|NYSE\s+Amex|NASDAQ-NMS|Nasdaq\s+NMS)\s*[:\-]\s*([A-Z][A-Z.\-]{0,6})\)'),
    re.compile(r'(?i:symbols?)\s+["“”\'‘’]([A-Z][A-Z.\-]{0,6})["“”\'‘’]'),
    re.compile(r'(?i:common\s+(?:stock|shares))\s*\(\s*["“]?([A-Z][A-Z.\-]{0,6})["”]?\s*\)'),
    re.compile(r'(?i:NYSE|New\s+York\s+Stock\s+Exchange|Nasdaq[A-Za-z ]{0,30}?Market)\s+(?i:under|as|with)\s+(?i:the\s+)?(?i:ticker\s+|trading\s+)?["“]([A-Z][A-Z.\-]{0,6})["”]'),
]
_RE_IXSYM = re.compile(r'name="dei:TradingSymbol"[^>]*>\s*(?:<[^>]+>\s*)*([A-Za-z.\-]{1,8})', re.I)


def claimed_symbols(raw, text, known):
    """本文が名乗る記号のうち、S&P の過去の記号か SEC の現在の記号に一致するものだけ（会社の同定だけに使う）。
    → (iXBRL の dei:TradingSymbol の記号の集合, 文の型に当たった記号の回数 Counter)"""
    ix = set()
    for m in _RE_IXSYM.finditer(raw[:3_000_000]):
        g = norm_tk(m.group(1)).rstrip('-')
        if g in known:
            ix.add(g)
    cnt = collections.Counter()
    for p in _SYM_PATTERNS:
        for m in p.finditer(text):
            g = norm_tk(m.group(1)).rstrip('-')
            if g in known:
                cnt[g] += 1
    return ix, cnt


# ───────────────────────── 1件の 10-K ─────────────────────────
def acc_path(cik, acc):
    return f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-", "")}'


def filing_docs(cik, acc):
    """提出の目録（-index.htm）から [(type, url, size)]。古い提出（個別の文書が無い）は []"""
    b = sec_get(f'{acc_path(cik, acc)}/{acc}-index.htm')
    t = b.decode('utf-8', 'ignore')
    out = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S | re.I):
        cells = [html.unescape(_RE_TAG.sub('', x)).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)]
        hrefs = re.findall(r'href="([^"]+)"', row)
        if len(cells) >= 5 and hrefs:
            href = hrefs[0]
            if href.startswith('/ix?doc='):
                href = href[len('/ix?doc='):]
            if not href.startswith('/Archives/') or href.endswith('/'):
                continue  # 古い提出の目録は文書名が無く、ディレクトリへのリンクになっている
            typ = cells[3].strip().upper()
            try:
                size = int(re.sub(r'\D', '', cells[4]) or 0)
            except ValueError:
                size = 0
            out.append((typ, 'https://www.sec.gov' + href, size))
    return out


_RE_DOCBLK = re.compile(r'<DOCUMENT>(.*?)</DOCUMENT>', re.S | re.I)


def split_full_txt(b):
    """完全提出の .txt を [(type, 本文)] に分ける"""
    t = b.decode('latin-1', 'ignore')
    out = []
    for blk in _RE_DOCBLK.findall(t):
        m = re.search(r'<TYPE>\s*([^\s<]+)', blk, re.I)
        typ = m.group(1).upper() if m else ''
        tm = re.search(r'<TEXT>(.*?)(?:</TEXT>|$)', blk, re.S | re.I)
        out.append((typ, tm.group(1) if tm else blk))
    return out


def fetch_filing(cik, f):
    """主文書と EX-13 の生の文字列を返す: (main_raw, [ex13_raw...], flags)"""
    flags = []
    docs = []
    try:
        docs = filing_docs(cik, f['acc'])
    except Exception as e:  # noqa
        flags.append(f'index_err:{type(e).__name__}')
    mains = [d for d in docs if d[0] in FORMS_ANNUAL]
    ex13 = [d for d in docs if re.match(r'EX-13(\b|\.|$)', d[0])]
    if mains:
        main_raw = sec_get(mains[0][1]).decode('utf-8', 'ignore')
        if mains[0][1].lower().endswith(('.pdf', '.jpg', '.gif')):
            flags.append('main_not_text')
        ex_raw = []
        for d in ex13[:4]:
            if d[1].lower().endswith(('.htm', '.html', '.txt')):
                try:
                    ex_raw.append(sec_get(d[1]).decode('utf-8', 'ignore'))
                except Exception as e:  # noqa
                    flags.append(f'ex13_err:{type(e).__name__}')
        return main_raw, ex_raw, flags
    # 個別の文書が無い古い提出 → 完全提出の .txt を分ける
    b = sec_get(f'https://www.sec.gov/Archives/edgar/data/{cik}/{f["acc"]}.txt')
    parts = split_full_txt(b)
    flags.append('full_txt')
    main = [p for p in parts if p[0] in FORMS_ANNUAL]
    exs = [p[1] for p in parts if re.match(r'EX-13(\b|\.|$)', p[0])]
    if not main:
        flags.append('no_main_in_txt')
        return None, exs, flags
    return main[0][1], exs, flags


def doc_features(raw, known, lm):
    text, n_tab, n_drop = to_text(raw, True)
    toks = words(text)
    cnt = collections.Counter(toks)
    feat = {'n_words': len(toks), 'n_unique': len(cnt), 'n_tables': n_tab, 'n_tables_dropped': n_drop,
            'raw_bytes': len(raw)}
    for cat in LM_CATS:
        feat[LM_KEY[cat]] = sum(v for k, v in cnt.items() if k in lm[cat])
    return text, toks, cnt, feat


def submissions(cik):
    """EDGAR の提出一覧（キャッシュ out/_nx_cache/sec_sub/・30日）→ (本体の JSON, [recent と古い分の表])"""
    os.makedirs(os.path.join(CACHE, 'sec_sub'), exist_ok=True)
    j = json.loads(sec_cached(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json', f'sec_sub/CIK{int(cik):010d}.json', 30))
    blocks = [j['filings']['recent']]
    for fi in j['filings'].get('files', []):
        blocks.append(json.loads(sec_cached('https://data.sec.gov/submissions/' + fi['name'], 'sec_sub/' + fi['name'], 30)))
    return j, blocks


def list_annual_filings(cik):
    j, blocks = submissions(cik)
    out = []
    for r in blocks:
        for i, form in enumerate(r['form']):
            if form in FORMS_ANNUAL:
                out.append({'acc': r['accessionNumber'][i], 'form': form, 'filed': r['filingDate'][i],
                            'period': r['reportDate'][i] or None, 'accepted': r['acceptanceDateTime'][i],
                            'primary': r['primaryDocument'][i] or None, 'size': r['size'][i]})
    out.sort(key=lambda x: (x['filed'], x['acc']))
    meta = {'name': j.get('name'), 'tickers': j.get('tickers'), 'exchanges': j.get('exchanges'), 'sic': j.get('sic'),
            'sicDescription': j.get('sicDescription'), 'fiscalYearEnd': j.get('fiscalYearEnd'),
            'formerNames': j.get('formerNames')}
    return out, meta


def xbrl_float(cik):
    """companyconcept の dei:EntityPublicFloat（2009年以降の XBRL）→ {accn: (値, end)}"""
    try:
        j = json.loads(sec_get(f'https://data.sec.gov/api/xbrl/companyconcept/CIK{int(cik):010d}/dei/EntityPublicFloat.json'))
    except Exception:  # noqa  404 = タグが無い
        return {}
    out = {}
    for unit, vals in j.get('units', {}).items():
        if unit != 'USD':
            continue
        for v in vals:
            out.setdefault(v['accn'], (v['val'], v.get('end')))
    return out


def in_windows(d, windows):
    return any(a <= d <= z for a, z in windows)


def build_cik(cand, known, force=False):
    cik = cand['cik']
    p = os.path.join(OUTDIR, f'{cik}.json')
    if os.path.exists(p) and not force:
        return p, 'skip'
    lm = lm_lists()
    t0 = time.time()
    s0 = dict(STATS)
    filings, meta = list_annual_filings(cik)
    fl = [f for f in filings if in_windows(f['filed'], cand['windows'])]
    # 窓の最初の 10-K の前年の文書（比較の相手）も取る
    if fl:
        firsts = [f for f in filings if f['filed'] < fl[0]['filed']]
        if firsts:
            fl = [firsts[-1]] + fl
    xf = xbrl_float(cik)
    recs = []
    prev = None  # {'acc','filed','cnt','tokens','sents','sec':{..},'cnt_ex':..}
    with tempfile.TemporaryDirectory(dir=CACHE, prefix='nx_lazy_tmp_') as tmpdir:
        for f in fl:
            rec = {k: f[k] for k in ('acc', 'form', 'filed', 'period', 'accepted')}
            rec['flags'] = []
            try:
                main_raw, ex_raws, flags = fetch_filing(cik, f)
                rec['flags'] += flags
            except Exception as e:  # noqa
                rec['flags'].append(f'fetch_err:{type(e).__name__}:{str(e)[:80]}')
                recs.append(rec)
                prev = None  # 比較の相手を失う（次の 10-K は前年との比較をしない）
                continue
            if main_raw is None:
                recs.append(rec)
                prev = None
                continue
            text, toks, cnt, feat = doc_features(main_raw, known, lm)
            rec.update(feat)
            rec['is_html'] = bool(re.search(r'<(html|body|div|p)\b', main_raw[:20000], re.I))
            rec['is_ixbrl'] = bool(re.search(r'<ix:(header|nonfraction|nonnumeric)\b', main_raw[:5_000_000], re.I))
            if prev is not None:
                rec['format_switch'] = (prev['is_html'], prev['is_ixbrl']) != (rec['is_html'], rec['is_ixbrl'])
            # 表紙（表を落とす前の文字列で探す）。iXBRL は表紙の前に数百万字の飾りがあるので、句の位置の前後だけを文字にする
            mpos = _RE_AMV_RAW.search(main_raw)
            if mpos:
                cover_text, _, _ = to_text(main_raw[max(0, mpos.start() - 30000): mpos.start() + 30000], drop_numeric_tables=False)
            else:
                cover_text, _, _ = to_text(main_raw[:400000], drop_numeric_tables=False)
            v, asof, why = cover_float(cover_text)
            rec['float_text'], rec['float_text_asof'], rec['float_text_why'] = v, asof, why
            rec['float_ix'] = ix_float(main_raw)
            xv = xf.get(f['acc'])
            rec['float_xbrl'], rec['float_xbrl_end'] = (xv[0], xv[1]) if xv else (None, None)
            # 記号（主文書＋EX-13）
            six, scnt = claimed_symbols(main_raw, cover_text + '\n' + text, known)
            ex_text_all = ''
            ex_cnt = collections.Counter()
            rec['n_ex13'] = len(ex_raws)
            for er in ex_raws:
                et, _, _ = to_text(er, True)
                ex_cnt.update(words(et))
                ex_text_all += '\n' + et
                a_ix, a_cnt = claimed_symbols(er, et, known)
                six |= a_ix
                scnt.update(a_cnt)
            rec['ex13_words'] = sum(ex_cnt.values()) if ex_raws else 0
            rec['symbols_ix'] = sorted(six)
            rec['symbols'] = dict(scnt)
            sents = sentences(text)
            rec['n_sents'] = len(sents)
            secs = {}
            for key in ('item1a', 'item7'):
                s = section(text, key)
                if s is None and key == 'item7' and ex_text_all:
                    s = None  # EX-13 の MD&A は節として扱わない（主文書だけ＝論文の約束）
                secs[key] = drop_stop(collections.Counter(words(s))) if s else None
                rec[f'{key}_words'] = len(words(s)) if s else None
            cur = {'acc': f['acc'], 'filed': f['filed'], 'cnt': cnt, 'cnt_ns': drop_stop(cnt), 'tokens': toks, 'sents': sents,
                   'sec': secs, 'cnt_ex': drop_stop(cnt + ex_cnt), 'has_ex': bool(ex_raws),
                   'is_html': rec['is_html'], 'is_ixbrl': rec['is_ixbrl']}
            if prev is not None:
                rec['prev_acc'] = prev['acc']
                rec['gap_days'] = (datetime.date.fromisoformat(f['filed']) - datetime.date.fromisoformat(prev['filed'])).days
                rec['sim_cos'] = cos_sim(prev['cnt_ns'], cur['cnt_ns'])  # 主: LM の一般的な stop word を除いた語の数
                rec['sim_jac'] = jac_sim(prev['cnt_ns'], cur['cnt_ns'])
                rec['sim_cos_all'] = cos_sim(prev['cnt'], cnt)  # 参考: すべての語（論文の字面どおり）
                rec['sim_jac_all'] = jac_sim(prev['cnt'], cnt)
                try:
                    rec.update({('sim_' + k if k in ('minedit', 'simple') else k): v2 for k, v2 in diff_features(prev, cur, tmpdir, lm).items()})
                except Exception as e:  # noqa
                    rec['flags'].append(f'diff_err:{type(e).__name__}')
                for key in ('item1a', 'item7'):
                    a, b2 = prev['sec'].get(key), secs.get(key)
                    rec[f'{key}_cos'] = cos_sim(a, b2) if a and b2 else None
                    rec[f'{key}_jac'] = jac_sim(a, b2) if a and b2 else None
                if prev['has_ex'] or cur['has_ex']:
                    rec['ex13_cos'] = cos_sim(prev['cnt_ex'], cur['cnt_ex'])
                    rec['ex13_jac'] = jac_sim(prev['cnt_ex'], cur['cnt_ex'])
            recs.append(rec)
            prev = cur
    obj = {'cik': cik, 'version': VERSION, 'built_at': datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z',
           'candidate': {k: cand.get(k) for k in ('tickers', 'via', 'windows', 'sec_tickers', 'price_tickers', 'successors',
                                                  'fts_tickers', 'name')}, 'edgar': meta,
           'n_annual_all': len(filings), 'n_in_window': len(fl), 'filings': recs,
           'cost': {'seconds': round(time.time() - t0, 1), 'requests': STATS['requests'] - s0.get('requests', 0),
                    'bytes': STATS['bytes'] - s0.get('bytes', 0), 'bytes_wire': STATS['bytes_wire'] - s0.get('bytes_wire', 0)}}
    os.makedirs(OUTDIR, exist_ok=True)
    tmp = f'{p}.{os.getpid()}.tmp'
    json.dump(obj, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, p)
    return p, 'built'


def _worker(args):
    cand, known, force = args
    try:
        p, how = build_cik(cand, known, force)
        o = json.load(open(p))
        return cand['cik'], how, o.get('cost'), len(o.get('filings', [])), None
    except Exception as e:  # noqa
        return cand['cik'], 'error', None, 0, f'{type(e).__name__}: {str(e)[:200]}'


def run_build(ciks, workers=4, force=False, log_every=10):
    import multiprocessing as mp
    uni = load_universe()
    known = set(uni['known_tickers'])
    cands = [uni['candidates'][str(c)] for c in ciks if str(c) in uni['candidates']]
    missing = [c for c in ciks if str(c) not in uni['candidates']]
    if missing:
        print('候補に無い CIK:', missing)
    lm_lists()  # 先に一度取っておく（子プロセスはキャッシュを読む）
    stopwords()
    lock, last = mp.Lock(), mp.Value('d', 0.0)
    t0 = time.time()
    done = []
    with mp.Pool(workers, initializer=_init_limiter, initargs=(lock, last)) as pool:
        for i, r in enumerate(pool.imap_unordered(_worker, [(c, known, force) for c in cands]), 1):
            done.append(r)
            if i % log_every == 0 or i == len(cands):
                el = time.time() - t0
                print(f'  {i}/{len(cands)}  経過 {el / 60:.1f} 分  見込みの残り {el / i * (len(cands) - i) / 60:.1f} 分', flush=True)
    log = {'finished_at': datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'n': len(done),
           'errors': [d for d in done if d[1] == 'error'], 'wall_seconds': round(time.time() - t0, 1)}
    return done, log


# ───────────────────────── 形だけの表示 ─────────────────────────
def shape(paths):
    fl = []
    costs = []
    for p in paths:
        o = json.load(open(p))
        costs.append(o.get('cost') or {})
        for r in o['filings']:
            r['_cik'] = o['cik']
            fl.append(r)
    n = len(fl)
    sig = [r for r in fl if r['form'] in FORMS_SIGNAL]
    have = lambda k: sum(1 for r in fl if r.get(k) is not None)  # noqa
    fl_by = collections.Counter(x.split(':')[0] for r in fl for x in r.get('flags', []))
    out = {
        'companies': len(paths), 'filings': n, 'signal_forms': len(sig),
        'with_prev_pair': sum(1 for r in sig if r.get('sim_cos') is not None),
        'pair_gap_9_15m': sum(1 for r in sig if r.get('gap_days') is not None and 270 <= r['gap_days'] <= 456),
        'words_ge_1000': sum(1 for r in fl if (r.get('n_words') or 0) >= 1000),
        'words_median': sorted(r.get('n_words') or 0 for r in fl)[n // 2] if n else None,
        'float_text_ok': sum(1 for r in fl if r.get('float_text') is not None),
        'float_ix': have('float_ix'), 'float_xbrl': have('float_xbrl'),
        'float_any': sum(1 for r in fl if any(r.get(k) is not None for k in ('float_xbrl', 'float_ix', 'float_text'))),
        'float_text_why': dict(collections.Counter(r.get('float_text_why') for r in fl)),
        'symbols_nonempty': sum(1 for r in fl if r.get('symbols') or r.get('symbols_ix')),
        'symbols_ix_nonempty': sum(1 for r in fl if r.get('symbols_ix')),
        'item1a_found': have('item1a_words'), 'item7_found': have('item7_words'),
        'has_ex13': sum(1 for r in fl if (r.get('n_ex13') or 0) > 0),
        'flags': dict(fl_by),
        'by_year_filings': dict(sorted(collections.Counter(r['filed'][:4] for r in fl).items())),
        'cost': {'seconds': round(sum(c.get('seconds', 0) for c in costs), 1), 'requests': sum(c.get('requests', 0) for c in costs),
                 'MB': round(sum(c.get('bytes', 0) for c in costs) / 1e6, 1), 'MB_wire': round(sum(c.get('bytes_wire', 0) for c in costs) / 1e6, 1)},
    }
    # 浮動株の出どころの食い違い（形の点検。株価は使わない）
    dis = []
    for r in fl:
        a, b = r.get('float_text'), r.get('float_xbrl') or r.get('float_ix')
        if a and b:
            dis.append(max(a, b) / min(a, b))
    out['float_text_vs_xbrl_ratio_gt_1.5'] = sum(1 for x in dis if x > 1.5)
    out['float_text_vs_xbrl_pairs'] = len(dis)
    return out


# ───────────────────────── 月末ごとの構成と「並べる月」 ─────────────────────────
def formation_ym(filed):
    """提出日の翌平日が同じ月なら、その月末に並べる（翌月から持つ）。提出日がその月の最後の平日なら翌月末に並べる"""
    d = datetime.date.fromisoformat(filed)
    nxt = d + datetime.timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += datetime.timedelta(days=1)
    ym = d.year * 100 + d.month
    if nxt.month != d.month:
        ym = nxt.year * 100 + nxt.month
    return ym


def month_ends(a=199601, z=None):
    today = datetime.date.today()
    z = z or today.year * 100 + today.month
    out = []
    y, m = a // 100, a % 100
    while y * 100 + m <= z:
        nm = datetime.date(y + (m == 12), m % 12 + 1, 1)
        out.append((y * 100 + m, (nm - datetime.timedelta(days=1)).isoformat()))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_panel():
    """事前登録の約束どおりの構成の判定（会社の同定）。成績は計算しない。
    月末 me のその日の構成表の記号 k と CIK c を結ぶ道（優先の高い順）:
      L1 近い名乗り: me 以前15か月以内の最新の 10-K（無ければ me の後15か月以内の最初の 10-K）が名乗る自分の記号に k がある
      L2 同じ期間の名乗り: k の連続した構成の期間 S（me を含む）の中に提出された c の 10-K のどれかが k を名乗った
         （構成表は Norgate 流に『後の記号』で過去を書くことがある: Anthem は 2002 年から ANTM、Google は 2006 年から GOOGL）
      L3 今の構成銘柄の今の記号: k が c の今の記号で、S が今の構成に入った日（Date added）以後まで続く（前に同じ記号を別の会社が使った期間を拾わない）
      L4 tier B: 全文検索（2001年以降）で S の中で k を最も多く・5件以上名乗った
      L5 tier C: 後継の記号の全文検索で最も多く・5件以上名乗った前身
    自分の記号 = iXBRL の dei:TradingSymbol があればそれ、無ければ文の型に当たった回数の最も多い記号（同数ならすべて）。
    自分の記号が c の株式の記号（今の記号・前身なら後継の記号）のどれかなら、その会社の他の種類株の記号も自分の記号とみなす（GOOG と GOOGL）。
    tier C（前身）は後継の最初の年次報告の日より前の月だけ。
    同じ記号に複数の CIK が結ばれたら、優先の高い道を採り、同じ道なら名乗った 10-K の提出日が新しいほうを採る。それでも同じなら全部外す"""
    uni = load_universe()
    hist = sp_history()
    dates = [d for d, _ in hist]
    import bisect
    recs = {}
    for fn in os.listdir(OUTDIR):
        if fn.endswith('.json'):
            o = json.load(open(os.path.join(OUTDIR, fn)))
            recs[o['cik']] = o
    cand = {int(k): v for k, v in uni['candidates'].items()}
    known_sp = set(t for _, st in hist for t in st)
    spans_all, _ = ticker_spans(hist)
    cur_tk = {c['cik']: c['tickers'][0] for c in cand.values() if 'A_current_member' in c['via']}
    c_end = {c['cik']: max(z for a0, z in c['windows']) for c in cand.values()
             if 'C_predecessor_of_current' in c['via'] and 'A_current_member' not in c['via']
             and 'B_former_member_same_ticker_now' not in c['via'] and 'D_fts_renamed_survivor' not in c['via']}

    def siblings(cik):
        c = cand.get(cik) or {}
        return {t for t in (c.get('price_tickers') or []) + (c.get('sec_tickers') or []) + (c.get('tickers') or []) if t in known_sp}

    def own(r, cik):
        if r.get('symbols_ix'):
            got = set(r['symbols_ix'])
        else:
            cc = r.get('symbols') or {}
            if not cc:
                return set()
            mx = max(cc.values())
            got = {k for k, v in cc.items() if v == mx}
        sib = siblings(cik)
        if got & sib:
            got |= sib
        return got
    claims = {cik: [(r['filed'], own(r, cik)) for r in o['filings'] if 'fetch_err' not in ' '.join(r.get('flags', []))]
              for cik, o in recs.items()}

    def a_ok(cik, tk, me):
        da = (cand[cik].get('wiki_date_added') or {}).get(tk)
        if not da:
            return True
        for a0, z0 in spans_all.get(tk, []):
            if a0 <= me < z0:
                return da <= z0
        return False
    b_fts = {}
    for c in cand.values():
        ok = [(t, a0, z0) for t, n, top, a0, z0 in (c.get('fts_for_own_ticker') or []) if top and n >= 5]
        if ok:
            b_fts[c['cik']] = ok
    c_fts = {}
    for c in cand.values():
        if 'C_predecessor_of_current' in c['via']:
            ok = {t for t, n, top in (c.get('fts_for_successor_tickers') or []) if top and n >= 5}
            if ok:
                c_fts[c['cik']] = ok

    def span_of(tk, me):
        for a0, z0 in spans_all.get(tk, []):
            if a0 <= me < z0:
                return a0, z0
        return None
    months = [(ym, me) for ym, me in month_ends(199601) if me >= dates[0]]
    members, how_by_month = {}, {}
    tiers = collections.Counter()
    conflicts = collections.Counter()
    for ym, me in months:
        i = bisect.bisect_right(dates, me) - 1
        if i < 0:
            continue
        sp = hist[i][1]
        lo = (datetime.date.fromisoformat(me) - datetime.timedelta(days=456)).isoformat()
        hi = (datetime.date.fromisoformat(me) + datetime.timedelta(days=456)).isoformat()
        cands_for = collections.defaultdict(list)  # 記号 → [(優先, 名乗った日, cik, 道)]
        for cik, cl in claims.items():
            if cik in c_end and me >= c_end[cik]:
                continue
            before = [(d, st) for d, st in cl if lo <= d <= me]
            after = [(d, st) for d, st in cl if me < d <= hi]
            near_d, near = (before[-1] if before else (after[0] if after else (None, set())))
            for k in near & sp:
                cands_for[k].append((1, near_d, cik, 'L1_claim_near'))
            for k in (set().union(*[st for _, st in cl]) & sp) - near:
                S = span_of(k, me)
                if S:
                    ds = [d for d, st in cl if k in st and S[0] <= d < S[1]]
                    if ds:
                        cands_for[k].append((2, max(ds), cik, 'L2_claim_same_span'))
            if cik in cur_tk and cur_tk[cik] in sp and a_ok(cik, cur_tk[cik], me):
                cands_for[cur_tk[cik]].append((3, '', cik, 'L3_current_ticker'))
            if before and cik in b_fts:
                for tk, a0, z0 in b_fts[cik]:
                    if tk in sp and a0 <= me < z0:
                        cands_for[tk].append((4, '', cik, 'L4_B_fts'))
            if before and cik in c_fts:
                for tk in c_fts[cik] & sp:
                    cands_for[tk].append((4, '', cik, 'L5_C_fts'))
        mem, how = set(), {}
        for k, lst in cands_for.items():
            best = min(x[0] for x in lst)
            top = [x for x in lst if x[0] == best]
            if len({x[2] for x in top}) > 1:
                newest = max(x[1] for x in top)
                top2 = [x for x in top if x[1] == newest]
                if len({x[2] for x in top2}) > 1 or newest == '':
                    conflicts[best] += 1
                    continue
                top = top2
            cik = top[0][2]
            mem.add(cik)
            how.setdefault(cik, top[0][3])
        members[ym] = sorted(mem)
        how_by_month[ym] = how
        for c, h in how.items():
            tiers[h] += 1
    # 10-K ごとの行
    rows = []
    for cik, o in recs.items():
        for r in o['filings']:
            row = {k: r.get(k) for k in ('acc', 'prev_acc', 'form', 'filed', 'period', 'n_words', 'n_unique', 'gap_days', 'sim_cos', 'sim_jac',
                                         'sim_cos_all', 'sim_jac_all', 'lm_con', 'lm_strong', 'lm_weak', 'ex13_words',
                                         'chg_unc_added', 'chg_unc_deleted', 'chg_lit_added', 'chg_lit_deleted', 'float_xbrl_end',
                                         'float_text_why', 'is_html', 'is_ixbrl', 'format_switch',
                                         'sim_minedit', 'sim_simple', 'item1a_words', 'item1a_cos', 'item1a_jac', 'item7_words',
                                         'item7_cos', 'item7_jac', 'ex13_cos', 'ex13_jac', 'n_ex13', 'lm_neg', 'lm_pos', 'lm_unc',
                                         'lm_lit', 'chg_words_added', 'chg_words_deleted', 'chg_neg_added', 'chg_neg_deleted',
                                         'chg_pos_added', 'chg_pos_deleted', 'float_xbrl', 'float_ix', 'float_text', 'float_text_asof')}
            row['cik'] = cik
            row['flags'] = '|'.join(r.get('flags') or [])
            row['formation_ym'] = formation_ym(r['filed'])
            row['sic'] = (o.get('edgar') or {}).get('sic')
            row['price_ticker_candidates'] = '|'.join(o['candidate'].get('price_tickers') or o['candidate'].get('sec_tickers') or [])
            row['tier'] = '|'.join(o['candidate'].get('via') or [])
            rows.append(row)
    p1 = os.path.join(CACHE, 'nx_lazy_members.json')
    json.dump({'generated': datetime.date.today().isoformat(), 'version': VERSION, 'members': members, 'how': how_by_month,
               'link_counts': dict(tiers), 'ticker_conflicts_dropped': dict(conflicts)}, open(p1, 'w'))
    p2 = os.path.join(CACHE, 'nx_lazy_signals.csv')
    if rows:
        with open(p2, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    cov = {}
    for ym, me in months:
        if ym % 100 == 6 and ym in members:
            i = bisect.bisect_right(dates, me) - 1
            cov[ym] = {'sp_members': len(hist[i][1]), 'linked_ciks': len(members[ym])}
    return {'members_file': p1, 'signals_file': p2, 'link_counts': dict(tiers), 'conflicts': dict(conflicts), 'coverage_june': cov}


# 動作確認の20社（会社の同定の難しい型を混ぜた: 名前を変えた会社・持株会社化・記号の再利用・EX-13 を使う古い会社）
TRIAL = [320193, 1326801, 21344, 34088, 732717, 350698, 1800, 19617, 92122, 72971, 51143, 1288776,
         93410, 40545, 18926, 1403161, 1037949, 1156039, 109563, 18230]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['universe', 'build', 'trial', 'status', 'panel'])
    ap.add_argument('--ciks', default='')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'universe':
        obj, p = build_universe()
        print(json.dumps(obj['stats'], ensure_ascii=False, indent=1))
        ws = [w for c in obj['candidates'].values() for w in c['windows']]
        print('窓の数', len(ws), '→', p)
        for x in obj.get('predecessors', []):
            print('  前身の候補', x)
        print('D:', [(c['cik'], c['name'], c.get('fts_tickers')) for c in obj['candidates'].values() if 'D_fts_renamed_survivor' in c['via']][:80])
        return
    if a.cmd in ('build', 'trial'):
        uni = load_universe()
        if a.cmd == 'trial':
            ciks = TRIAL
        elif a.ciks:
            ciks = [int(x) for x in a.ciks.split(',')]
        else:
            ciks = sorted(int(c) for c in uni['candidates'])
        if a.limit:
            ciks = ciks[:a.limit]
        done, log = run_build(ciks, a.workers, a.force)
        print(json.dumps({k: v for k, v in log.items()}, ensure_ascii=False, indent=1)[:3000])
        paths = [os.path.join(OUTDIR, f'{c}.json') for c in ciks if os.path.exists(os.path.join(OUTDIR, f'{c}.json'))]
        print(json.dumps(shape(paths), ensure_ascii=False, indent=1))
        return
    if a.cmd == 'status':
        paths = [os.path.join(OUTDIR, f) for f in os.listdir(OUTDIR) if f.endswith('.json')] if os.path.isdir(OUTDIR) else []
        print(json.dumps(shape(paths), ensure_ascii=False, indent=1))
        return
    if a.cmd == 'panel':
        print(json.dumps(build_panel(), ensure_ascii=False, indent=1)[:6000])


if __name__ == '__main__':
    main()
