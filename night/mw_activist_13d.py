#!/usr/bin/env python3
"""night/mw_activist_13d.py — 角度 activist_13d（読むだけ・門の判定には不使用）

問い: S&P500 の会社にアクティビスト（投資組合・運用会社）の Schedule 13D が出た翌月に買って 12/24 か月持つと、
      純粋な時価加重の米国株（French Mkt）に勝つか。

事前登録: out/mw_activist_13d_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を
mw_common.grade でそのまま当てる。株価は Yahoo（上場廃止の履歴が消える）なので、未観測の社を
『持たない』(S) と『−100%』(L) の二本で囲み、符号が一致したときだけ格を付ける。中間（M: 最後の観測値で売る）も出す。

段（上から順に回す。どれも取り直さずキャッシュを使う）
  --fetch-idx   : EDGAR form.idx（1994Q1〜2026Q3）から SC 13D 系と 10-K 系の行だけを抜いて貯める → out/_mw_cache/activist_13d/idx/
                  （ex27 / moat_text の form.idx キャッシュは読むだけ。無い四半期は form.gz を取る・4 req/s 以下）
  --map         : S&P500 の名簿（ie_sp500_components.csv）の各記号の期間 → CIK（Wikipedia の版の CIK 列・SEC の今の一覧・
                  社名の一致）→ out/_mw_cache/activist_13d/spell_cik.json
  --fetch-docs  : 対象（S&P500 の会社が当事者の最初の SC 13D）の本文を取る → out/_mw_cache/activist_13d/docs/
  --parse       : 本文 → 対象会社 CIK・提出者・Item 4 の文 → out/_mw_cache/activist_13d/events_parsed.json
  --count       : 年ごとの件数（リターンを見る前に数える）
  (既定)        : 計算して out/mw_activist_13d.json を書く
"""
import csv, datetime, gzip, json, math, os, re, sys, time, urllib.request, urllib.error
import statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
C = os.path.join(M.CACHE, 'activist_13d')
IDX = os.path.join(C, 'idx')
DOCS = os.path.join(C, 'docs')
IE_YH = os.path.join(M.CACHE, 'ie_yh')          # index_events の Yahoo 月次（読むだけ）
YHD = os.path.join(C, 'yh')                      # ie_yh に無い記号だけここへ取る
MEMB = os.path.join(M.CACHE, 'ie_sp500_components.csv')   # index_events の名簿（読むだけ）
SRC_IDX = [os.path.join(M.CACHE, 'ex27'), os.path.join(M.CACHE, 'moat_text', 'idx'), os.path.join(M.CACHE, 'ie_sec')]
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}   # retro_delisted と同じ（ルール5）
SEC_SLEEP = 0.26                  # 4 req/s 以下（並行して EDGAR を読む角度がいるので 8 の半分）
PREREG = 'mw_activist_13d_prereg.json'
OUT = 'mw_activist_13d.json'
END = 202608                      # French の終わり
SPIKE = 3.0                       # 月 +300% 超はデータの誤り → その月から未観測
Q0, Q1 = (1994, 1), (2026, 3)

F13D = ('SC 13D', 'SC 13D/A', 'SCHEDULE 13D', 'SCHEDULE 13D/A')
F10K = ('10-K', '10-K405', '10-KT', '10-K/A', '10-K405/A')
ROW = re.compile(r'^(\S+(?: \S+)*?)\s{2,}(.*?)\s{2,}(\d{1,10})\s+(\d{4}-\d{2}-\d{2}|\d{8})\s+(edgar/\S+)\s*$')


# ───────────────────────── 月の算術 ─────────────────────────
def madd(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def ym(d):
    return int(d[:4]) * 100 + int(d[5:7])


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


def quarters():
    y, q = Q0
    while (y, q) <= Q1:
        yield y, q
        q += 1
        if q == 5:
            y, q = y + 1, 1


# ───────────────────────── SEC ─────────────────────────
_last = [0.0]


def sec_raw(url, tries=5):
    """SEC から取る（4 req/s 以下・gzip を解く）。404 は None"""
    err = None
    for i in range(tries):
        dt = time.time() - _last[0]
        if dt < SEC_SLEEP:
            time.sleep(SEC_SLEEP - dt)
        _last[0] = time.time()
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=180).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e; time.sleep(5 * (i + 1))
        except Exception as e:  # noqa
            err = e; time.sleep(5 * (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}: {err}')


def parse_idx_text(txt):
    """form.idx の本文 → (13D 系の行, 10-K 系の行)。行 = (form, name, cik, date, path)"""
    r13, r10 = [], []
    for line in txt.splitlines():
        if not (line.startswith('SC 13D') or line.startswith('SCHEDULE 13D') or line.startswith('10-K')):
            continue
        m = ROW.match(line)
        if not m:
            continue
        form, name, cik, date, path = m.groups()
        if len(date) == 8:
            date = f'{date[:4]}-{date[4:6]}-{date[6:]}'
        row = (form, name.strip(), str(int(cik)), date, path)
        if form in F13D:
            r13.append(row)
        elif form in F10K:
            r10.append(row)
    return r13, r10


def idx_done(y, q):
    return os.path.exists(os.path.join(IDX, f'{y}Q{q}.json'))


def fetch_idx():
    os.makedirs(IDX, exist_ok=True)
    log = []
    for y, q in quarters():
        if idx_done(y, q):
            continue
        txt, src = None, None
        for d in SRC_IDX:
            p = os.path.join(d, f'form_{y}Q{q}.idx')
            if os.path.exists(p) and os.path.getsize(p) > 100000:
                t = open(p, 'rb').read().decode('latin-1')
                # 書きかけを掴まない: 最後の行が完全な行であること
                last = [x for x in t.splitlines() if x.strip()][-1]
                if ROW.match(last):
                    txt, src = t, p
                    break
        if txt is None:
            b = sec_raw(f'https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz')
            if b is None:
                log.append((y, q, 'missing')); continue
            txt, src = b.decode('latin-1'), 'sec:form.gz'
        r13, r10 = parse_idx_text(txt)
        json.dump({'src': src, 'n13': len(r13), 'n10': len(r10), 'r13': r13, 'r10': r10}, open(os.path.join(IDX, f'{y}Q{q}.json.tmp'), 'w'))
        os.replace(os.path.join(IDX, f'{y}Q{q}.json.tmp'), os.path.join(IDX, f'{y}Q{q}.json'))
        print(y, q, src.split('/')[-2] if '/' in src else src, '13D系', len(r13), '10-K系', len(r10), flush=True)
    print('完了', log)


def load_idx():
    r13, r10 = [], []
    for y, q in quarters():
        p = os.path.join(IDX, f'{y}Q{q}.json')
        if os.path.exists(p):
            j = json.load(open(p))
            r13 += j['r13']; r10 += j['r10']
    return r13, r10


# ───────────────────────── 名簿 → CIK ─────────────────────────
SUF = (r'\b(INC|INCORPORATED|CORP|CORPORATION|CO|COS|COMPANY|COMPANIES|LTD|LIMITED|PLC|LP|LLC|L P|'
       r'HOLDING|HOLDINGS|HLDGS|HLDG|GROUP|GRP|THE|OF|COM|SA|NV|N V|AG|NEW|DEL|DE|INTL|INTERNATIONAL|CL A|CL B|CLASS A|CLASS B)\b')


def norm(s):
    s = (s or '').upper()
    s = re.sub(r'/[A-Z]{2,3}/?', ' ', s)
    s = re.sub(r'\([^)]*\)', ' ', s)
    s = s.replace('&', ' AND ')
    s = re.sub(r"[^A-Z0-9 ]", ' ', s.replace("'", '').replace('.', ''))
    s = re.sub(SUF, ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def load_membership():
    rows = [(r['date'], set(r['tickers'].split(','))) for r in csv.DictReader(open(MEMB))]
    rows.sort()
    return rows


def spells(rows):
    sp, prev, last = {}, set(), None
    for d, s in rows:
        for t in s - prev:
            sp.setdefault(t, []).append([d, None])
        for t in prev - s:
            sp[t][-1][1] = last
        prev, last = s, d
    for t in prev:
        sp[t][-1][1] = last
    return sp


WIKI_API = ('https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=List_of_S%26P_500_companies&rvlimit=1'
            '&rvstart={d}T00:00:00Z&rvdir=older&rvprop=ids%7Ctimestamp%7Ccontent&rvslots=main&format=json')


def wiki_snapshots():
    """2007-07〜2026-07 の半年ごとの版の構成銘柄表 → [(版の日付, 記号, 社名, CIK or None)]"""
    out, srcs = [], []
    for y in range(2007, 2027):
        for mo in (1, 7):
            d = f'{y}-{mo:02d}-01'
            if d < '2007-07-01' or d > '2026-07-01':
                continue
            nm_c = f'activist_13d/wiki_rev_{d}.json'
            if not os.path.exists(os.path.join(M.CACHE, nm_c)):
                time.sleep(6)          # Wikipedia の 429 を避ける
                try:
                    M.get(WIKI_API.format(d=d), name=nm_c, max_age_days=36500, tries=2)
                except RuntimeError as e:
                    print('  Wikipedia 版を取れず（飛ばす）', d, str(e)[-60:], flush=True)
                    continue
            srcs.append(os.path.join(M.CACHE, nm_c))
    # index_events が取った版（読むだけ）も足す
    for f in sorted(os.listdir(M.CACHE)):
        if f.startswith('ie_wiki_rev_') and f.endswith('.json'):
            srcs.append(os.path.join(M.CACHE, f))
    for pth in srcs:
            j = json.loads(open(pth, 'rb').read())
            rev = list(j['query']['pages'].values())[0]['revisions'][0]
            c = rev['slots']['main']['*']
            i = c.find('{|'); z = c.find('\n|}', i)
            tab = c[i:z]
            ts = rev['timestamp'][:10]
            for blk in tab.split('\n|-')[1:]:
                b = blk.strip()
                if not b or b.startswith('!'):
                    continue
                cells = [x.strip() for x in re.split(r'\n\||\|\|', '\n' + b) if x.strip()]
                tk = nm = ck = None
                for x in cells:
                    m = re.search(r'\{\{\s*(?:Nyse|Nasdaq|NYSE|NASDAQ)\w*\s*\|\s*([A-Z0-9.\-]+)', x)
                    if m and tk is None:
                        tk = m.group(1); continue
                    if tk is None and re.fullmatch(r'[A-Z]{1,5}(?:[.\-][A-Z])?', x):
                        tk = x; continue
                    m = re.fullmatch(r'0*(\d{3,10})', x)
                    if m and ck is None and len(x) >= 7:
                        ck = str(int(m.group(1))); continue
                    if nm is None and '[[' in x and 'Symbol' not in x and 'sec.gov' not in x:
                        m = re.search(r'\[\[([^\]|]*)(?:\|([^\]]*))?\]\]', x)
                        if m:
                            nm = (m.group(2) or m.group(1)).strip()
                if tk:
                    out.append((ts, tk.replace('-', '.'), nm, ck))
    return out


def wiki_changes():
    """最新版の変更表 → [(日付, 記号, 社名)]（追加と除外の両方）"""
    import mw_index_events as IE
    w, _ = IE.load_wiki()
    out = []
    for x in w:
        d = x['date'].isoformat()
        if x['add']:
            out.append((d, x['add'].replace('-', '.'), x['add_name']))
        if x['rem']:
            out.append((d, x['rem'].replace('-', '.'), x['rem_name']))
    return out


EX27_MIN_FLOAT = 1e9               # ex27 の記号の証拠は浮動株時価 10 億ドル以上の社だけ（小型株の本文の雑音を除く）


def ex27_symbols():
    """ex27 の 10-K 本文から拾った銘柄コード（1995〜2002）→ [(提出日, 記号, CIK, 社名)]。
    本文の記号は雑音が多い（例: T を THQ・TR Financial が名乗る）ので、(1) 表紙の浮動株時価が 10 億ドル以上の提出だけ、
    (2) 同じ記号を ±2 年以内に別の大型の CIK も名乗っていれば両方とも捨てる"""
    p = os.path.join(M.CACHE, 'ex27', 'parsed_v2.jsonl.gz')
    raw = []
    if not os.path.exists(p):
        return raw
    for line in gzip.open(p, 'rt'):
        x = json.loads(line)
        fl = (x.get('cover') or {}).get('float')
        if not fl or fl < EX27_MIN_FLOAT:
            continue
        for s in x.get('symbols') or []:
            raw.append((x['filed'], s.upper().replace('-', '.'), x['cik'], x['name']))
    by = {}
    for d, t, c, n in raw:
        by.setdefault(t, []).append((d, c))
    out = []
    for d, t, c, n in raw:
        y = int(d[:4])
        others = {c2 for d2, c2 in by[t] if c2 != c and abs(int(d2[:4]) - y) <= 2}
        if not others:
            out.append((d, t, c, n))
    return out


def build_map(verbose=True):
    """名簿の記号の期間ごとに、証拠（日付・CIK・出所）を集め、期間の各日を最も近い証拠の CIK へ割り当てる。
    どの CIK も、その会社の 10-K が出ている期間（最初の 10-K の 1 年前〜最後の 10-K の 1.5 年後）にしか当てない。"""
    rows = load_membership()
    sp = spells(rows)
    r13, r10 = load_idx()
    tenk = {}           # cik → [日付]
    names10 = {}        # norm 名 → {cik}
    cikname = {}
    for f, n, c, d, p in r10:
        tenk.setdefault(c, []).append(d)
        names10.setdefault(norm(n), set()).add(c)
        cikname.setdefault(c, set()).add(n)
    for c in tenk:
        tenk[c].sort()

    win = {c: ((datetime.date.fromisoformat(v[0]) - datetime.timedelta(days=365)).isoformat(),
               (datetime.date.fromisoformat(v[-1]) + datetime.timedelta(days=548)).isoformat()) for c, v in tenk.items()}

    def active(c, d):
        w = win.get(c)
        return bool(w) and w[0] <= d <= w[1]

    def by_name(nm, d):
        k = norm(nm)
        if not k:
            return None
        cs = {c for c in names10.get(k, set()) if active(c, d)}
        return next(iter(cs)) if len(cs) == 1 else None

    ev = {}             # 記号 → [(日付, cik, 出所)]
    stats = {}

    def add(t, d, c, src):
        if c and active(c, d):
            ev.setdefault(t, []).append((d, c, src)); stats[src] = stats.get(src, 0) + 1
    for d, t, nm, ck in wiki_snapshots():
        if ck:
            add(t, d, ck, 'wiki_cik')
        elif nm:
            add(t, d, by_name(nm, d), 'wiki_name')
    for d, t, nm in wiki_changes():
        if nm:
            add(t, d, by_name(nm, d), 'wiki_change_name')
    ct = json.load(open(os.path.join(M.CACHE, 'sec_company_tickers.json')))
    now_t, now_c = {}, {}
    for x in ct.values():
        now_t.setdefault(str(x['cik_str']), set()).add(x['ticker'].upper().replace('-', '.'))
        now_c[x['ticker'].upper().replace('-', '.')] = str(x['cik_str'])
    n_conf = 0
    for d, t, c, nm in ex27_symbols():
        if t not in sp:
            continue
        # 今その記号を使う別の会社が、その当時も 10-K を出していた（生きていた）なら、本文の記号は他社のもの（例: D＝Dominion を Genentech の本文が名乗る）→ 捨てる
        c2 = now_c.get(t)
        if c2 and c2 != c and active(c2, d):
            n_conf += 1
            continue
        add(t, d, c, 'ex27_symbol')
    stats['ex27_dropped_conflict_with_current_holder'] = n_conf
    for x in ct.values():
        t = x['ticker'].upper().replace('-', '.')
        c = str(x['cik_str'])
        for a, z in sp.get(t, []):
            v = [q for q in tenk.get(c, []) if a <= q <= (datetime.date.fromisoformat(z) + datetime.timedelta(days=548)).isoformat()]
            if v:
                add(t, v[-1], c, 'sec_tickers_now')
    # 期間ごとに割り当て
    out, unmapped = {}, []
    for t, lst in sp.items():
        for a, z in lst:
            e = sorted(x for x in ev.get(t, []) if (datetime.date.fromisoformat(a) - datetime.timedelta(days=548)).isoformat() <= x[0] <= (datetime.date.fromisoformat(z) + datetime.timedelta(days=548)).isoformat())
            seg = []
            eo = [(datetime.date.fromisoformat(x[0]).toordinal(), x[1]) for x in e]
            for r in rows:
                d = r[0]
                if not (a <= d <= z):
                    continue
                dd = datetime.date.fromisoformat(d).toordinal()
                # 証拠から 3 年を超えて伸ばすのは、その CIK が今も同じ記号を使っている（記号の連続）ときだけ
                cand = [(abs(o - dd), c) for o, c in eo if active(c, d) and (abs(o - dd) <= 1096 or t in now_t.get(c, ()))]
                if not cand:
                    seg.append((d, None)); continue
                seg.append((d, min(cand)[1]))
            # 連続する同じ CIK をまとめる
            runs = []
            for d, c in seg:
                if runs and runs[-1][2] == c:
                    runs[-1][1] = d
                else:
                    runs.append([d, d, c])
            for r0, r1, c in runs:
                if c is None:
                    unmapped.append((t, r0, r1))
                else:
                    out.setdefault(t, []).append({'from': r0, 'to': r1, 'cik': c, 'n_ev': sum(1 for x in e if x[1] == c),
                                                  'srcs': sorted({x[2] for x in e if x[1] == c})})
    # 名簿の月ごとの被覆
    tot = cov = 0
    for d, s in rows:
        for t in s:
            tot += 1
            if any(x['from'] <= d <= x['to'] for x in out.get(t, [])):
                cov += 1
    res = {'spells': out, 'unmapped': unmapped, 'evidence_counts': stats, 'coverage_member_dates': round(cov / tot, 4),
           'cik_names': {c: sorted(v)[:3] for c, v in cikname.items() if any(c == x['cik'] for l in out.values() for x in l)}}
    json.dump(res, open(os.path.join(C, 'spell_cik.json'), 'w'), ensure_ascii=False)
    if verbose:
        print('証拠', stats, '被覆（名簿の日×銘柄）', res['coverage_member_dates'], '割り当てなしの区間', len(unmapped))
    return res


# ───────────────────────── 出来事の候補と本文 ─────────────────────────
def accessions(r13):
    """受付番号ごと → {'form','date','ciks':{cik: name},'paths':[...]}"""
    acc = {}
    for f, n, c, d, p in r13:
        a = p.split('/')[-1].replace('.txt', '')
        x = acc.setdefault(a, {'form': f, 'date': d, 'ciks': {}, 'paths': []})
        x['ciks'][c] = n
        x['paths'].append(p)
    return acc


def member_cik_at(mp, d):
    """その日に S&P500 の名簿にいる CIK → 記号（名簿の記号）"""
    out = {}
    for t, lst in mp['spells'].items():
        for x in lst:
            if x['from'] <= d <= x['to']:
                out[x['cik']] = t
    return out


def spells_by_cik(mp):
    by = {}
    for t, lst in mp['spells'].items():
        for x in lst:
            by.setdefault(x['cik'], []).append((x['from'], x['to'], t))
    return by


def is_member(by, c, d):
    for a, z, t in by.get(c, []):
        if a <= d <= z:
            return t
    return None


def candidates(mp=None):
    """最初の SC 13D（修正でない）で、当事者の CIK のどれかが提出日に S&P500 の名簿にいるもの"""
    mp = mp or json.load(open(os.path.join(C, 'spell_cik.json')))
    by = spells_by_cik(mp)
    r13, _ = load_idx()
    acc = accessions(r13)
    out = []
    for a, x in acc.items():
        if x['form'] not in ('SC 13D', 'SCHEDULE 13D'):
            continue
        hit = {c: is_member(by, c, x['date']) for c in x['ciks']}
        hit = {c: t for c, t in hit.items() if t}
        if hit:
            out.append({'acc': a, 'date': x['date'], 'form': x['form'], 'ciks': x['ciks'], 'member_ciks': hit, 'path': x['paths'][0]})
    out.sort(key=lambda z: z['date'])
    return out, acc


def doc_path(a):
    return os.path.join(DOCS, a[:10], a + '.txt.gz')


def fetch_docs():
    cand, _ = candidates()
    os.makedirs(DOCS, exist_ok=True)
    todo = [x for x in cand if not os.path.exists(doc_path(x['acc']))]
    print('候補', len(cand), '未取得', len(todo), flush=True)
    for i, x in enumerate(todo):
        b = sec_raw('https://www.sec.gov/Archives/' + x['path'])
        os.makedirs(os.path.dirname(doc_path(x['acc'])), exist_ok=True)
        tmp = doc_path(x['acc']) + '.tmp'
        with gzip.open(tmp, 'wb') as f:
            f.write(b if b is not None else b'<<HTTP404>>')
        os.replace(tmp, doc_path(x['acc']))
        if i % 200 == 0:
            print(' 本文', i, '/', len(todo), x['date'], flush=True)
    print('完了')


# ───────────────────────── 本文を読む ─────────────────────────
KW_ALL = re.compile(r'\bboard\b|director\s+nominat|strategic\s+alternative|sale\s+of\s+the\s+company|maximi[sz]e\s+(?:share(?:holder|owner)|stockholder)\s+value|\bproxy\b|spin[\s\-]*off|buy[\s\-]*back', re.I)
KW_STRONG = re.compile(r'director\s+nominat|nominat\w*\s+(?:\w+\s+){0,4}(?:director|candidate|individual|person)|strategic\s+alternative|sale\s+of\s+the\s+company|maximi[sz]e\s+(?:share(?:holder|owner)|stockholder)\s+value|proxy\s+(?:contest|fight|solicitation)|solicit\w*\s+(?:\w+\s+){0,3}prox|spin[\s\-]*off|buy[\s\-]*back|share\s+repurchase|representation\s+on\s+the\s+board|board\s+representation|seats?\s+on\s+the\s+board', re.I)
ENTITY = re.compile(r'\b(PARTNERS|PARTNERSHIP|L\s?\.?\s?P\.?|CAPITAL|MANAGEMENT|MGMT|ADVIS[OE]RS?|ADVISORY|FUNDS?|INVESTMENTS?|INVESTORS|ASSET|OPPORTUNIT(?:Y|IES)|MASTER|OFFSHORE|GP)\b')


RP_NAME = re.compile(r'names?\s+of\s+reporting\s+persons?[^A-Za-z]{0,40}(?:(?:s\.?s\.?|i\.?r\.?s\.?)\s+(?:or\s+)?(?:i\.?r\.?s\.?\s+)?identification\s+nos?\.?\s+of\s+(?:the\s+)?above\s+persons?(?:\s*\(entities\s+only\))?[^A-Za-z]{0,20})?(.{3,120}?)(?=\s+(?:I\.?R\.?S\.?|S\.?S\.?|\(?2\)?\s*\.?\s*check|2\s*\.|\(2\)|tax\s+id|ein\b|identification))', re.I | re.S)


def _hv(block, key):
    m = re.search(key + r':\s*([^\n]+)', block)
    return m.group(1).strip() if m else None


def parse_doc(raw):
    """→ {'subject': (cik, name), 'filers': [(cik, name)], 'item4': 文 or None, 'item4_how'}"""
    t = raw.decode('latin-1', 'replace')
    hz = t.find('</SEC-HEADER>')
    hdr = t[:hz if hz > 0 else 5000]
    subj, filers = None, []
    for part in re.split(r'\n(?=(?:SUBJECT COMPANY|FILED BY|FILER):)', hdr):
        head = part.split(':', 1)[0].strip()
        cik = _hv(part, 'CENTRAL INDEX KEY'); nm = _hv(part, 'COMPANY CONFORMED NAME')
        if cik:
            cik = str(int(re.sub(r'\D', '', cik) or 0))
        if head == 'SUBJECT COMPANY' and cik:
            subj = (cik, nm)
        elif head in ('FILED BY', 'FILER') and cik:
            filers.append((cik, nm))
    body = t[hz:] if hz > 0 else t
    # 本文は最初の文書だけ（添付の書簡・契約は Item 4 ではない）
    d2 = body.find('<DOCUMENT>', body.find('<DOCUMENT>') + 10)
    main = body[:d2] if d2 > 0 else body
    xml = '<XML>' in main[:5000] or '<edgarSubmission' in main
    txt = re.sub(r'<[^>]+>', ' ', main)
    txt = re.sub(r'&nbsp;|&#160;|&#xa0;', ' ', txt, flags=re.I)
    txt = re.sub(r'&amp;', '&', txt)
    txt = re.sub(r'&#\d+;|&\w+;', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt)
    item4, how = None, None
    if xml:
        m = re.search(r'<item4>(.*?)</item4>', main, re.S | re.I) or re.search(r'<transactionPurpose>(.*?)</transactionPurpose>', main, re.S | re.I)
        if m:
            item4 = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', m.group(1))); how = 'xml'
    if item4 is None:
        ms = list(re.finditer(r'item\s*4\s*[\.\-:\u2014\u2013]?\s*(?:\(?\w\)?\s*)?purpose\s+of\s+(?:the\s+)?transaction', txt, re.I))
        if not ms:
            ms = list(re.finditer(r'item\s*(?:no\.?\s*)?(?:4|iv|four)\b\s*[\.\-:\u2014\u2013]?', txt, re.I))
            ms = [m for m in ms if re.match(r'.{0,40}purpose', txt[m.end():m.end() + 60], re.I | re.S)] or ms
            how = 'item4_loose' if ms else None
        else:
            how = 'item4_title'
        if ms:
            # 最後ではなく、後ろに Item 5 が来る最初の出現（目次を避ける）
            for m in ms:
                rest = txt[m.end():]
                e = re.search(r'item\s*(?:no\.?\s*)?(?:5|v|five)\b\s*[\.\-:\u2014\u2013]?\s*(?:\(?\w\)?\s*)?interest', rest, re.I)
                if e is None:
                    e = re.search(r'item\s*(?:no\.?\s*)?(?:5|v|five)\b', rest, re.I)
                seg = rest[:e.start()] if e else rest[:20000]
                if len(seg.strip()) > 5:
                    item4 = seg[:60000]; break
    # 対象会社の SIC（ヘッダ）
    sic = None
    for part in re.split(r'\n(?=(?:SUBJECT COMPANY|FILED BY|FILER):)', hdr):
        if part.startswith('SUBJECT COMPANY'):
            m = re.search(r'STANDARD INDUSTRIAL CLASSIFICATION:[^\n]*?\[?(\d{4})\]?\s*$', part, re.M)
            if m:
                sic = int(m.group(1))
    # 発行済株式数（時価加重の重みにだけ使う）: Item 5 の『X 株が発行済み』を優先、無ければ表紙の 保有株数÷保有比率 の中央値
    so, so_how = None, None
    mm = [int(x.replace(',', '')) for x in re.findall(r'(?:based|calculated|computed)\s+(?:up)?on\s+(?:a\s+total\s+of\s+|an?\s+aggregate\s+of\s+|the\s+)?([\d,]{7,})\s+(?:outstanding\s+)?shares', txt, re.I)]
    mm += [int(x.replace(',', '')) for x in re.findall(r'([\d,]{7,})\s+shares\s+of\s+(?:the\s+)?(?:issuer.?s\s+|company.?s\s+)?(?:class\s+\w\s+)?common\s+stock[^.]{0,80}?outstanding', txt, re.I)]
    mm = [x for x in mm if 5e6 <= x <= 5e10]
    if mm:
        so, so_how = sorted(mm)[len(mm) // 2], 'item5_outstanding'
    else:
        am = [int(x.replace(',', '')) for x in re.findall(r'aggregate\s+amount\s+beneficially\s+owned\s+by\s+each\s+(?:reporting\s+)?person\W{0,20}?(?:\(?\w{0,6}\)?\s*)?([\d,]{5,})', txt, re.I)]
        pc = [float(x) for x in re.findall(r'percent\s+of\s+class\s+represented\s+by\s+amount\s+in\s+row\s*\(?\s*(?:11|\(11\))\s*\)?\W{0,20}?(?:\(?\w{0,6}\)?\s*)?(\d{1,2}(?:\.\d+)?)\s*%', txt, re.I)]
        if xml:
            am += [int(float(x)) for x in re.findall(r'<aggregateAmountOwned>\s*([\d.]+)', main)]
            pc += [float(x) for x in re.findall(r'<percentOfClass>\s*([\d.]+)', main)]
        imp = [a / (p / 100) for a, p in zip(am, pc) if a > 0 and 0.5 <= p <= 60]
        if imp:
            so, so_how = sorted(imp)[len(imp) // 2], 'cover_amount_over_pct'
    # 表紙の『報告者の名前』（グループの全員。ヘッダの FILED BY は代表の1人だけのことがある＝例 ICAHN CARL C ET AL）
    rp = [m.group(1).strip(' -_') for m in RP_NAME.finditer(txt)]
    if xml:
        rp += [re.sub(r'\s+', ' ', x).strip() for x in re.findall(r'<reportingPersonName>(.*?)</reportingPersonName>', main, re.S | re.I)]
    rp = [x for x in dict.fromkeys(rp) if len(x) >= 3 and not re.match(r'(?i)s\.?s\.?\s*or|i\.?r\.?s', x)]
    return {'subject': subj, 'filers': filers, 'item4': item4, 'item4_how': how if item4 else None, 'xml': xml,
            'sic': sic, 'shares_out': so, 'shares_out_how': so_how, 'reporting_persons': rp[:40]}


def natural_person(name):
    return not ENTITY.search((name or '').upper()) and not re.search(r'\b(INC|CORP|CO|COMPANY|LTD|LLC|TRUST|BANK|GROUP|HOLDINGS?|PLC|AG|SA|NV|FOUNDATION|ASSOCIATION|SOCIETY|UNIVERSITY|FUND)\b', (name or '').upper())


def parse_all():
    cand, acc = candidates()
    out = []
    n404 = 0
    for x in cand:
        p = doc_path(x['acc'])
        if not os.path.exists(p):
            continue
        raw = gzip.open(p).read()
        if raw == b'<<HTTP404>>':
            n404 += 1; out.append({**x, 'missing_doc': True}); continue
        d = parse_doc(raw)
        subj = d['subject']
        # 対象会社: ヘッダの SUBJECT COMPANY。無ければ（古い様式）名簿にいる側
        if subj is None:
            mc = list(x['member_ciks'])
            subj = (mc[0], x['ciks'][mc[0]]) if len(mc) == 1 else None
        filers = d['filers'] or [(c, n) for c, n in x['ciks'].items() if not subj or c != subj[0]]
        filers = [f for f in filers if not subj or f[0] != subj[0]]
        i4 = d['item4'] or ''
        out.append({'acc': x['acc'], 'date': x['date'], 'form': x['form'],
                    'subject_cik': subj[0] if subj else None, 'subject_name': subj[1] if subj else None,
                    'subject_member': (x['member_ciks'].get(subj[0]) if subj else None),
                    'filers': filers, 'index_ciks': x['ciks'],
                    'item4_found': bool(d['item4']), 'item4_how': d['item4_how'], 'item4_len': len(i4), 'xml': d['xml'],
                    'kw_all': sorted({m.group(0).lower() for m in KW_ALL.finditer(i4)}),
                    'kw_strong': sorted({re.sub(r'\s+', ' ', m.group(0).lower()) for m in KW_STRONG.finditer(i4)}),
                    'sic': d['sic'], 'shares_out': d['shares_out'], 'shares_out_how': d['shares_out_how'],
                    'reporting_persons': d['reporting_persons'],
                    'item4_head': i4[:400]})
    json.dump({'n_candidates': len(cand), 'n_404': n404, 'events': out}, open(os.path.join(C, 'events_parsed.json'), 'w'), ensure_ascii=False)
    print('読んだ', len(out), '404', n404)
    return out


# ───────────────────────── 株価（Yahoo 月次）─────────────────────────
_yh = {}


def yh_fetch(t):
    """ie_yh に無い記号だけ activist_13d/yh/ へ取る（404 は {"http":404}）"""
    os.makedirs(YHD, exist_ok=True)
    p = os.path.join(YHD, f'{t}.json')
    if os.path.exists(p):
        return 'cached'
    y = t.replace('.', '-')
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{y}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    for i in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
            open(p, 'wb').write(b); time.sleep(0.4); return 'ok'
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(p, 'w').write('{"http":404}'); return '404'
            time.sleep(3 * (i + 1))
        except Exception:  # noqa
            time.sleep(3 * (i + 1))
    return 'fail'


def yh(t):
    """{'type','first','last','ret':{yyyymm:r},'close':{yyyymm: 分割調整後の終値},'splits':[(yyyymm, 倍率)],'spike','name'} or None"""
    if t in _yh:
        return _yh[t]
    out = None
    for d in (IE_YH, YHD):
        p = os.path.join(d, f'{t}.json')
        if not os.path.exists(p):
            continue
        j = json.load(open(p))
        res = (j.get('chart') or {}).get('result') if isinstance(j, dict) else None
        if not res:
            continue
        r = res[0]; ts = r.get('timestamp') or []
        off = r.get('meta', {}).get('gmtoffset') or 0
        adj = ((r['indicators'].get('adjclose') or [{}])[0].get('adjclose')) or []
        cl = ((r['indicators'].get('quote') or [{}])[0].get('close')) or []
        px, cx = {}, {}
        for i, a in enumerate(ts):
            k = datetime.datetime.utcfromtimestamp(a + off)
            k = k.year * 100 + k.month
            v = adj[i] if i < len(adj) else None
            if v is not None and v > 0:
                px[k] = v
            c = cl[i] if i < len(cl) else None
            if c is not None and c > 0:
                cx[k] = c
        splits = []
        for x in ((r.get('events') or {}).get('splits') or {}).values():
            k = datetime.datetime.utcfromtimestamp(x['date'] + off)
            if x.get('denominator'):
                splits.append((k.year * 100 + k.month, x['numerator'] / x['denominator']))
        ks = sorted(px)
        if not ks:
            continue
        ret, spike = {}, None
        for p0, k in zip(ks, ks[1:]):
            if k > END:
                break
            if madd(p0, 1) != k:        # 欠けた月をまたぐ変化はリターンにしない（ルール7）
                continue
            x = px[k] / px[p0] - 1
            if x > SPIKE:
                spike = k; break
            ret[k] = x
        out = {'type': r['meta'].get('instrumentType'), 'first': ks[0], 'last': ks[-1], 'ret': ret, 'close': cx,
               'splits': sorted(splits), 'spike': spike, 'name': r['meta'].get('longName') or r['meta'].get('shortName')}
        break
    _yh[t] = out
    return out


def obs(t, m):
    """('ok', r) / ('missing', None) / ('spike', None)"""
    d = yh(t) if t else None
    if not d or d['type'] != 'EQUITY':
        return 'missing', None
    if d['spike'] and m >= d['spike']:
        return 'spike', None
    r = d['ret'].get(m)
    return ('ok', r) if r is not None else ('missing', None)


def fetch_yh():
    """出来事の対象会社と名簿の全 CIK の『今の記号』の Yahoo 月次を揃える（ie_yh に無いものだけ取る）"""
    tn = ticker_now()
    mp = json.load(open(os.path.join(C, 'spell_cik.json')))
    ciks = {x['cik'] for l in mp['spells'].values() for x in l}
    p = os.path.join(C, 'events_parsed.json')
    if os.path.exists(p):
        ciks |= {e['subject_cik'] for e in json.load(open(p))['events'] if e.get('subject_cik')}
    ts = sorted({t for c in ciks for t in tn.get(c, [])[:3]})
    todo = [t for t in ts if not os.path.exists(os.path.join(IE_YH, f'{t}.json')) and not os.path.exists(os.path.join(YHD, f'{t}.json'))]
    print('記号', len(ts), '未取得', len(todo), flush=True)
    from collections import Counter
    print(Counter(yh_fetch(t) for t in todo))


# ───────────────────────── 出来事の旗 ─────────────────────────
KNOWN_ACTIVISTS = re.compile(r'ICAHN|HIGH RIVER|ELLIOTT (?:ASSOCIATES|MANAGEMENT|INTERNATIONAL|INVESTMENT)|PERSHING SQUARE|TRIAN|VALUEACT|'
                             r'THIRD POINT|STARBOARD|RAMIUS|JANA PARTNERS|RELATIONAL INVESTORS|CORVEX|SANDELL|GREENLIGHT|BARINGTON|'
                             r'STEEL PARTNERS|HARBINGER|MANTLE RIDGE|ENGAGED CAPITAL|LAND (?:AND|&) BUILDINGS|SACHEM HEAD|MARCATO|'
                             r'BLUE HARBOUR|GAMCO|GABELLI|LEGION PARTNERS|CEVIAN|ANCORA|IRENIC|ENGINE NO|CLINTON GROUP|BREEDEN|'
                             r'GLENVIEW|TRACINDA|ATLANTIC INVESTMENT MANAGEMENT|WYNNEFIELD|FRONTFOUR|BULLDOG INVESTORS|SCOPIA|KNIGHT VINKE', re.I)


def entity_filers(e):
    """投資組合・運用会社の語を持つ提出者（ヘッダの FILED BY・索引の相手・表紙の報告者。対象会社自身は除く）"""
    fl = [(c, n) for c, n in e['filers'] if c != e['subject_cik']]
    fl += [(c, n) for c, n in e['index_ciks'].items() if c != e['subject_cik'] and c not in {x for x, _ in fl}]
    subj = norm(e.get('subject_name') or '')
    fl += [(None, n) for n in e.get('reporting_persons') or [] if norm(n) != subj]
    return [(c, n) for c, n in fl if ENTITY.search((n or '').upper())]


def flag_events(parsed, acc_all):
    """F1（アクティビスト）・F2（初回）・X0（全 13D）・X1（強い語）・X2（名の知れたアクティビスト）の旗を付ける"""
    # 同じ (対象, 提出者) の組の 13D/13D-A の提出日（初回の判定用・索引だけで作る）
    pair_dates = {}
    for a, x in acc_all.items():
        cs = list(x['ciks'])
        for i in range(len(cs)):
            for j in range(len(cs)):
                if i != j:
                    pair_dates.setdefault((cs[i], cs[j]), []).append((x['date'], a))
    out = []
    for e in parsed:
        if e.get('missing_doc') or not e.get('subject_cik') or not e.get('subject_member'):
            continue
        ef = entity_filers(e)
        allf = [(c, n) for c, n in e['filers'] if c != e['subject_cik']] + [(c, n) for c, n in e['index_ciks'].items() if c != e['subject_cik']]
        allf_n = allf + [(None, n) for n in e.get('reporting_persons') or []]
        e = dict(e)
        e['X0_any'] = True
        e['F1_activist'] = bool(ef) and bool(e['kw_all'])
        e['X1_strong'] = bool(ef) and bool(e['kw_strong'])
        e['X2_known'] = any(KNOWN_ACTIVISTS.search(n or '') for _, n in allf_n) and bool(e['kw_all'])
        d0 = (datetime.date.fromisoformat(e['date']) - datetime.timedelta(days=36 * 30.44)).isoformat()
        prior = False
        for c, _ in allf:
            if c is None:
                continue
            for d, a in pair_dates.get((e['subject_cik'], c), []):
                if d0 <= d < e['date'] and a != e['acc']:
                    prior = True
        e['F2_first'] = e['F1_activist'] and not prior
        e['entity_filers'] = ef
        out.append(e)
    return out


NONCOMMON = re.compile(r'\.(P[A-Z]?|WS|W|WT|U|UN|R|RT)$|^[A-Z]+\.P[A-Z]$')


def ticker_now():
    """CIK → 今の記号（普通株だけ。優先株・ワラント・ユニット・権利の記号は除く＝例 Santander Holdings USA の SNUS-PI）"""
    ct = json.load(open(os.path.join(M.CACHE, 'sec_company_tickers.json')))
    by = {}
    for x in ct.values():
        t = x['ticker'].upper().replace('-', '.')
        if NONCOMMON.search(t):
            continue
        by.setdefault(str(x['cik_str']), []).append(t)
    return by


_ctt = {}


def _cur_titles():
    if not _ctt:
        for x in json.load(open(os.path.join(M.CACHE, 'sec_company_tickers.json'))).values():
            _ctt[x['ticker'].upper().replace('-', '.')] = (str(x['cik_str']), x['title'])
    return _ctt


def pick_ticker(tn, cik, member_t=None, name=None):
    """CIK の今の普通株の記号（名簿の記号が中にあればそれ）。CIK に今の記号が無いときだけ、名簿の記号を今使っている別の CIK の
    社名の最初の語が対象会社の名前の最初の語と同じなら（持株会社への組み替え＝例 Xerox Corp → Xerox Holdings）その記号を使う"""
    ts = tn.get(cik, [])
    pref = [t for t in ts if t == (member_t or '')]
    if pref or ts:
        return (pref or ts)[0]
    if member_t and name:
        c2 = _cur_titles().get(member_t)
        if c2 and c2[0] != cik:
            a, b = norm(name).split(), norm(c2[1]).split()
            if a and b and a[0] == b[0] and len(a[0]) >= 3:
                return member_t
    return None


# ───────────────────────── ポートフォリオ ─────────────────────────
def ff49():
    """(SIC → 49業種の略号, 49業種の時価加重の月次総リターン {略号: {yyyymm: r}})"""
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes49.zip', name='fr_Siccodes49_map.zip', max_age_days=3650)))
    L = z.read(z.namelist()[0]).decode('latin-1').split('\n')
    rng, cur = [], None
    for l in L:
        s_ = l.strip()
        if not s_:
            continue
        p = s_.split()
        if p[0].isdigit() and len(p) >= 2 and '-' not in p[0]:
            cur = p[1]
        elif '-' in p[0] and cur:
            a, b = p[0].split('-')
            if a.isdigit() and b.isdigit():
                rng.append((int(a), int(b), cur))

    def f(sic):
        if sic is None:
            return None
        for a, b, k in rng:
            if a <= sic <= b:
                return k
        return 'Other'
    ind = M.french_series('49_Industry_Portfolios', 'Value Weight')
    ind = {k.strip(): v for k, v in ind.items()}
    return f, ind


def unadj_close(d, m):
    """その月末の分割調整前の終値（Yahoo の close は分割調整済み → m より後の分割の倍率を掛け戻す）"""
    c = d['close'].get(m)
    if c is None:
        return None
    f = 1.0
    for k, r in d['splits']:
        if k > m:
            f *= r
    return c * f


def build_positions(events, H, tick_now):
    """出来事 → 会社ごとの保有区間（重なる区間はつなぐ）。各区間: {'cik','t','entry','exit','events':[...],'mcap','sic'}"""
    by = {}
    for e in sorted(events, key=lambda z: z['date']):
        c = e['subject_cik']
        ent = madd(ym(e['date']), 1)
        ext = madd(ent, H - 1)
        lst = by.setdefault(c, [])
        if lst and ent <= madd(lst[-1]['exit'], 1):
            lst[-1]['exit'] = max(lst[-1]['exit'], ext); lst[-1]['events'].append(e['acc'])
        else:
            t = pick_ticker(tick_now, c, e.get('subject_member'), e.get('subject_name'))
            lst.append({'cik': c, 't': t, 'entry': ent, 'exit': ext, 'events': [e['acc']], 'sic': e.get('sic'),
                        'shares_out': e.get('shares_out'), 'filed_m': ym(e['date']), 'name': e.get('subject_name')})
    pos = [x for v in by.values() for x in v]
    for x in pos:
        d = yh(x['t']) if x['t'] else None
        px = unadj_close(d, x['filed_m']) if d and d['type'] == 'EQUITY' else None
        mc = x['shares_out'] * px if (px and x['shares_out']) else None
        x['mcap'] = mc if (mc and 3e8 <= mc <= 6e12) else None
        x['observed_entry'] = obs(x['t'], x['entry'])[0] == 'ok'
    return pos


def portfolio(pos, bound, weighting, mkt, ind=None, indf=None, a=199607, z=END):
    """暦月のポートフォリオ。bound: 'S'（観測できない社は持たない・途中で消えたら最後の値で売る）/
    'M'（観測できない月は 0%＝最後の値のまま据え置く）/ 'L'（観測できない社は −100%）。
    weighting: 'EW'（毎月等加重）/ 'VW'（入った月の時価 × その後の値動き＝買って持つ時価加重。時価が取れない社はその年の中央値の時価）。
    ind があれば同じ重みで各社の49業種のリターンも返す（F3 の相手）。持つ社が0の月は French Mkt（相手も Mkt）"""
    # VW の既定時価（時価が取れない社）: 入った年の中央値
    med = {}
    for x in pos:
        if x['mcap']:
            med.setdefault(x['entry'] // 100, []).append(x['mcap'])
    allm = sorted(v for l in med.values() for v in l)
    gmed = allm[len(allm) // 2] if allm else 1.0
    med = {y: sorted(v)[len(v) // 2] for y, v in med.items()}
    val, dead, frozen = {}, set(), set()
    s_out, b_out, st = {}, {}, {'months_empty': 0, 'pos_months': 0, 'pos_months_obs': 0, 'lost_L': 0, 'spike': 0, 'frozen_M': 0, 'n_active': []}
    for m in months(a, z):
        if m not in mkt:
            continue
        act = [x for x in pos if x['entry'] <= m <= x['exit'] and id(x) not in dead]
        num = den = nb = 0.0
        n_act = 0
        for x in act:
            k = id(x)
            if k not in val:
                val[k] = (x['mcap'] or med.get(x['entry'] // 100, gmed)) if weighting == 'VW' else 1.0
            w = val[k] if weighting == 'VW' else 1.0
            stt, r = obs(x['t'], m)
            st['pos_months'] += 1
            if k in frozen:
                stt, r = 'frozen', 0.0
            if stt == 'ok':
                st['pos_months_obs'] += 1
            elif stt == 'spike':
                st['spike'] += 1; dead.add(k); continue          # データの誤り → 両方の上下限で最後の値で売る
            elif bound == 'S':
                dead.add(k); continue
            elif bound == 'L':
                r = -1.0; dead.add(k); st['lost_L'] += 1
            elif bound == 'N':                                   # N: 観測できない月は相手（市場か業種）と同じ＝超過0（報告のみ）
                r = None; st['neutral_N'] = st.get('neutral_N', 0) + 1
            else:                                                # M: 最後の値のまま据え置く（0%）
                r = 0.0; frozen.add(k); st['frozen_M'] += 1
            rb_ = mkt[m]
            if ind is not None:
                g = indf(x['sic']) if x['sic'] else None
                rb = ind.get(g, {}).get(m) if g else None
                rb_ = rb if rb is not None else mkt[m]
                nb += w * rb_
            if r is None:
                r = rb_
            num += w * r; den += w; n_act += 1
            if weighting == 'VW':
                val[k] = w * (1 + r)
        if den > 0:
            s_out[m] = num / den
            b_out[m] = nb / den if ind is not None else mkt[m]
        else:
            s_out[m] = mkt[m]; b_out[m] = mkt[m]; st['months_empty'] += 1
        st['n_active'].append(n_act)
    na = st.pop('n_active')
    st['avg_active'] = round(sum(na) / len(na), 1) if na else 0
    st['median_active'] = sorted(na)[len(na) // 2] if na else 0
    return s_out, b_out, st


# ───────────────────────── 計算と判定 ─────────────────────────
GORD = {'S': 0, 'A': 1, 'B': 2, 'C': 3}
FRESH_START = 200901               # Brav-Jiang-Partnoy-Thomas (2008) の公表の翌年
PRIMARY = {  # 名前: (旗, 保有月数, 重み, F3 か)
    'F1_EW_H12': ('F1_activist', 12, 'EW', False), 'F1_EW_H24': ('F1_activist', 24, 'EW', False),
    'F1_VW_H12': ('F1_activist', 12, 'VW', False), 'F1_VW_H24': ('F1_activist', 24, 'VW', False),
    'F2_EW_H12': ('F2_first', 12, 'EW', False), 'F2_EW_H24': ('F2_first', 24, 'EW', False),
    'F2_VW_H12': ('F2_first', 12, 'VW', False), 'F2_VW_H24': ('F2_first', 24, 'VW', False),
    'F3_EW_H12': ('F1_activist', 12, 'EW', True), 'F3_EW_H24': ('F1_activist', 24, 'EW', True),
    'F3_VW_H12': ('F1_activist', 12, 'VW', True), 'F3_VW_H24': ('F1_activist', 24, 'VW', True)}
EXPLORATORY = {
    'X0_all13D_EW_H12': ('X0_any', 12, 'EW', False), 'X0_all13D_EW_H24': ('X0_any', 24, 'EW', False),
    'X1_strong_EW_H12': ('X1_strong', 12, 'EW', False), 'X1_strong_EW_H24': ('X1_strong', 24, 'EW', False),
    'X1_strong_VW_H12': ('X1_strong', 12, 'VW', False), 'X1_strong_VW_H24': ('X1_strong', 24, 'VW', False),
    'X2_known_EW_H12': ('X2_known', 12, 'EW', False), 'X2_known_EW_H24': ('X2_known', 24, 'EW', False),
    'X3_F1_EW_H36': ('F1_activist', 36, 'EW', False), 'X3_F1_VW_H36': ('F1_activist', 36, 'VW', False)}
# 片道の年間回転率（事前登録）: EW は区間の出入り＋毎月の等加重の戻し、VW は出入りだけ
TURN = {('EW', 12): 1.5, ('EW', 24): 1.0, ('EW', 36): 0.8, ('VW', 12): 1.0, ('VW', 24): 0.5, ('VW', 36): 0.35}
COST = 0.001                       # 片道 100% あたり 0.10%（大型株・ブリーフどおり）


def sgn(x):
    return None if x is None else (1 if x > 0 else -1 if x < 0 else 0)


def stats_block(s, b, turn):
    # L の下限で持っている社が全部 −100% の月＝累積で全損。対数が取れないので −99.99% で止める（index_events と同じ・月を記録）
    wipe = sorted(k for k, v in s.items() if v <= -0.9999)
    s = {k: max(v, -0.9999) for k, v in s.items()}
    blk = {'wipeout_months': wipe[:24], 'n_wipeout_months': len(wipe),
           'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END),
           'hold': M.excess_stats(s, b, a=M.HOLD_START), 'recent': M.excess_stats(s, b, a=M.RECENT_START),
           'fresh2009': M.excess_stats(s, b, a=FRESH_START)}
    net = {k: max(v, -0.9999) for k, v in M.apply_cost(s, turn, COST).items()}
    blk['net_hold'] = M.excess_stats(net, b, a=M.HOLD_START)
    blk['net_train'] = M.excess_stats(net, b, z=M.TRAIN_END)
    blk['rolling20'] = M.rolling(s, b, 20)
    blk['dca20'] = M.dca(s, b, 20)
    blk['maxdd'] = round(M.maxdd(s) * 100, 1)
    blk['maxdd_bench'] = round(M.maxdd(b) * 100, 1)
    blk['cost'] = {'turnover_oneway_per_year': turn, 'cost_per_100pct': COST}
    return blk


def counts_by_year(ev, tick_now):
    out = {}
    for e in ev:
        y = e['date'][:4]
        c = out.setdefault(y, {'S&P500_13D': 0, 'F1_activist': 0, 'F2_first': 0, 'X1_strong': 0, 'X2_known': 0,
                               'F1_observed_at_entry': 0, 'item4_found': 0})
        c['S&P500_13D'] += 1
        c['item4_found'] += bool(e['item4_found'])
        for k in ('F1_activist', 'F2_first', 'X1_strong', 'X2_known'):
            c[k] += bool(e[k])
        if e['F1_activist']:
            t = pick_ticker(tick_now, e['subject_cik'], e.get('subject_member'), e.get('subject_name'))
            c['F1_observed_at_entry'] += obs(t, madd(ym(e['date']), 1))[0] == 'ok'
    return out


def load_events():
    par = json.load(open(os.path.join(C, 'events_parsed.json')))
    r13, _ = load_idx()
    acc = accessions(r13)
    return flag_events(par['events'], acc), par


def count():
    ev, par = load_events()
    tn = ticker_now()
    cy = counts_by_year(ev, tn)
    for y in sorted(cy):
        print(y, cy[y])
    tr = [cy[y]['F1_activist'] for y in cy if '1996' <= y <= '2006']
    print('訓練期間の F1 件数/年: 最小', min(tr), '平均', round(sum(tr) / len(tr), 1))
    return cy


def run():
    t0 = time.time()
    pre_sha = os.popen(f'git -C {BASE} log -n1 --format=%h -- out/{PREREG}').read().strip()
    ev, par = load_events()
    tn = ticker_now()
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if k <= END}
    indf, ind = ff49()
    sanity = {'french_mkt_cagr_full': round(M.cagr(mkt) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)}
    tested, series, info = [], {}, {}
    allspec = [(n, v, True) for n, v in PRIMARY.items()] + [(n, v, False) for n, v in EXPLORATORY.items()]
    for name, (flag, H, W, is_f3), prim in allspec:
        evs = [e for e in ev if e[flag]]
        pos = build_positions(evs, H, tn)
        info[name] = {'events': len(evs), 'positions': len(pos), 'observed_at_entry': sum(x['observed_entry'] for x in pos),
                      'with_mcap': sum(1 for x in pos if x['mcap'])}
        per = {}
        for bnd in ('S', 'M', 'L', 'N'):
            s_, b_, st = portfolio(pos, bnd, W, mkt, ind if is_f3 else None, indf)
            bench = b_ if is_f3 else mkt
            blk = stats_block(s_, bench, TURN[(W, H)])
            blk.update({'name': f'{name}__{bnd}', 'base': name, 'bound': bnd, 'family': ('primary_' + name[:2]) if prim else 'exploratory_' + name[:2],
                        'primary': prim, 'flag': flag, 'H': H, 'weighting': W, 'benchmark': 'industry49_same_weights' if is_f3 else 'French_Mkt',
                        'coverage': st, 'counts': info[name]})
            if not is_f3:
                # 報告のみ: 同じ Yahoo で観測できる S&P500 の等加重（同じ観測の規則）
                pass
            per[bnd] = blk
            series[f'{name}__{bnd}'] = s_
            if is_f3:
                series[f'{name}__{bnd}__bench'] = b_
            tested.append(blk)
    # Holm（主の族・保有期間の p は S と L の大きい方）
    pv = {}
    for t in tested:
        if t['primary'] and t['bound'] in ('S', 'L'):
            p = (t['hold'] or {}).get('p')
            if p is not None:
                pv[t['base']] = max(pv.get(t['base'], 0), p)
    hp = M.holm(pv)
    for t in tested:
        fam_p = hp.get(t['base']) if t['primary'] else None
        g, c = M.grade(t['full'], t['train'], t['hold'], t['rolling20'], t['net_hold'], repl=None, family_holm_p=fam_p)
        t['grade'], t['criteria'], t['family_holm_p'] = g, c, fam_p
    cands = []
    for name in list(PRIMARY) + list(EXPLORATORY):
        S_ = next(t for t in tested if t['name'] == f'{name}__S')
        L_ = next(t for t in tested if t['name'] == f'{name}__L')
        M_ = next(t for t in tested if t['name'] == f'{name}__M')
        N_ = next(t for t in tested if t['name'] == f'{name}__N')
        agree_h = S_['hold'] and L_['hold'] and sgn(S_['hold']['ex_ann']) == sgn(L_['hold']['ex_ann'])
        agree_t = S_['train'] and L_['train'] and sgn(S_['train']['ex_ann']) == sgn(L_['train']['ex_ann'])
        fg = max(S_['grade'], L_['grade'], key=lambda x: GORD[x]) if (agree_h and agree_t) else '判定不能'
        g = lambda t, k, f='ex_ann': (t.get(k) or {}).get(f)
        cands.append({'name': name, 'primary': name in PRIMARY, 'final_grade': fg, 'grade_S': S_['grade'], 'grade_M': M_['grade'], 'grade_L': L_['grade'],
                      'hold_ex_S': g(S_, 'hold'), 'hold_ex_M': g(M_, 'hold'), 'hold_ex_L': g(L_, 'hold'), 'hold_ex_N': g(N_, 'hold'),
                      'hold_t_N': g(N_, 'hold', 't'), 'train_ex_N': g(N_, 'train'), 'full_ex_N': g(N_, 'full'), 'full_t_N': g(N_, 'full', 't'),
                      'hold_t_S': g(S_, 'hold', 't'), 'hold_t_L': g(L_, 'hold', 't'),
                      'train_ex_S': g(S_, 'train'), 'train_ex_M': g(M_, 'train'), 'train_ex_L': g(L_, 'train'),
                      'train_t_S': g(S_, 'train', 't'), 'train_t_L': g(L_, 'train', 't'),
                      'full_ex_S': g(S_, 'full'), 'full_t_S': g(S_, 'full', 't'),
                      'recent_ex_S': g(S_, 'recent'), 'fresh2009_ex_S': g(S_, 'fresh2009'), 'fresh2009_ex_L': g(L_, 'fresh2009'),
                      'net_hold_ex_S': g(S_, 'net_hold'), 'hold_cagr_diff_S': g(S_, 'hold', 'cagr_diff'), 'hold_cagr_diff_L': g(L_, 'hold', 'cagr_diff'),
                      'roll20_win_S': (S_['rolling20'] or {}).get('win_rate'), 'dca20_win_S': (S_['dca20'] or {}).get('win_rate'),
                      'dca20_median_S': (S_['dca20'] or {}).get('median_ratio'), 'family_holm_p': hp.get(name), 'counts': info[name]})
    # 報告のみ: 同じ観測の規則で作った Yahoo の S&P500 等加重（生き残りの偏りの物差し）
    mp = json.load(open(os.path.join(C, 'spell_cik.json')))
    rows = load_membership()
    snaps = [(ym(d), d) for d, _ in rows]
    ctrl = {}
    for m in months(199608, END):
        prev = [d for k, d in snaps if k < m]
        if not prev:
            continue
        d = prev[-1]
        mc = member_cik_at(mp, d)
        rs = []
        for c, mt in mc.items():
            t = pick_ticker(tn, c, mt, (mp['cik_names'].get(c) or [None])[0])
            if t:
                stt, r = obs(t, m)
                if stt == 'ok':
                    rs.append(r)
        if rs:
            ctrl[m] = sum(rs) / len(rs)
    diag = {'control_EW_SP500_observed_vs_mkt': {k: M.excess_stats(ctrl, mkt, a=a, z=z) for k, (a, z) in
                                                 {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None)}.items()}}
    for name in ('F1_EW_H12', 'F1_EW_H24', 'F2_EW_H12', 'F2_EW_H24', 'X1_strong_EW_H12', 'X0_all13D_EW_H12'):
        s_ = series[f'{name}__S']
        diag[f'{name}__S_vs_control'] = {k: M.excess_stats(s_, ctrl, a=a, z=z) for k, (a, z) in
                                         {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None), 'fresh2009': (FRESH_START, None)}.items()}
    out = {'angle': 'activist_13d', 'prereg': PREREG, 'prereg_commit': pre_sha, 'sanity': sanity,
           'event_counts_by_year': counts_by_year(ev, tn), 'holm_primary': hp, 'candidates': cands, 'diagnostics': diag,
           'n_tested': len(tested), 'tested': tested,
           'series': {k: {str(m): round(v, 5) for m, v in sorted(s_.items())} for k, s_ in series.items()
                      if k.split('__')[0] in ('F1_EW_H12', 'F1_VW_H12', 'F2_EW_H12', 'F3_EW_H12')},
           'runtime_s': round(time.time() - t0, 1)}
    M.save(OUT, out)
    print('書いた', OUT, round(time.time() - t0, 1), '秒')
    for c in cands:
        print(c['name'], c['final_grade'], 'S/M/L hold', c['hold_ex_S'], c['hold_ex_M'], c['hold_ex_L'], 'train', c['train_ex_S'], c['train_ex_L'])
    return out


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--fetch-idx' in a:
        fetch_idx()
    if '--map' in a:
        build_map()
    if '--fetch-docs' in a:
        fetch_docs()
    if '--parse' in a:
        parse_all()
    if '--fetch-yh' in a:
        fetch_yh()
    if '--count' in a:
        count()
    if not a:
        run()
