#!/usr/bin/env python3
"""night/nx_activist_data.py — 角度 nx_activist（物言う株主の 13D の後に対象会社を買う）のデータを作るだけの道具（成績は計算しない）

事前登録: out/nx_activist_prereg.json（測る前に書いた）。出典の論文: Brav, Jiang, Partnoy & Thomas (2008, JF) ほか。
**株価は取らない。平均・t・シャープ・累積・勝率は計算しない・表示しない。**

段（python3 night/nx_activist_data.py <段> [--interval 秒] [--workers 並列数（headers だけ）]）
  index    : EDGAR の full-index（master.gz・1993Q1〜今の四半期）を四半期ごとに読み、
             13D/13G・物言う株主の委任状の様式の行（CIK・名前・様式・提出日・受付番号）と、
             定期報告（事業会社: 10-K 系・10-Q 系・20-F・40-F／投資会社: N-CSR 系・N-Q・N-30D・NPORT-P）を出した CIK（登録会社）と、13F を出した CIK（機関投資家）の
             初出・最終の日付だけを out/_nx_cache/nx_activist/idx/{年}Q{n}.json.gz に残す（原本の索引はディスクに残さない）
  families : 物言う株主の名前の規則（FAMILIES・下に固定）を 13D の提出者の行の名前に当て、家ごとの CIK の一覧を作る
             → out/_nx_cache/nx_activist/families.json（形だけを表示: 家ごとの CIK・名前・13D の件数）
  headers  : 一覧（L_NOW・L_PRE）の家が提出者に入っている**初回の** 13D（SC 13D / SCHEDULE 13D）と、
             家が出した委任状の様式（PREN14A・DEFN14A・DFAN14A・PREC14A・DEFC14A）の受付番号ごとに、
             EDGAR の見出し（{受付番号}.hdr.sgml）を取り、対象会社（SUBJECT-COMPANY）の CIK・名前・SIC・受付の日時・
             提出者（FILED-BY）・グループの名前を残す → out/_nx_cache/nx_activist/hdr/{受付番号}.json
  mech     : 一覧に依らない機械の定義（L_MECH）: すべての初回 13D の受付番号について、同じ受付番号に並ぶ CIK を
             「登録会社（対象の候補）」と「それ以外（提出者の候補）」に分け、対象が1社に決まるものだけを残す
             （見出しは取らない。決まらないものは数えて捨てる）→ out/_nx_cache/nx_activist/mech_filings.json.gz
  events   : 事前登録の約束どおりに事象の一覧を作る（家→事象・除外・24か月の重複・対象会社→今のティッカー。
             今のティッカーが無い CIK は、名前が接尾語を除いて一致し定期報告が続く『後継の CIK』を保守的に1回だけ探す）
             → out/_nx_cache/nx_activist/events.json と、測る道具が照合する sha256
  status   : 作ったデータの形だけを表示する（件数・年ごとの件数・ティッカーが付いた割合）
  audit    : 欠けの抜き取り検査の標本（今のティッカーが無い L_NOW の事象から 2005〜2019 の40件・種 20260928）を固定して書く
             → out/_nx_cache/nx_activist/audit_sample.json（株価は取らない）

約束（事前登録と同じ）
- SEC の User-Agent は hachimon_fetch.py の HDRS と同じ形（中の EMAIL をそのまま読む）。既定 5 req/s（--interval で遅くできる。
  並走する他の道具と合わせて 10 req/s を超えないように）
- 欠測は 0 と読まない（絶対のルール7）。ティッカーが無い対象会社は「無い」と記録し、測る道具が被覆率と下限版で扱う
- 株価は取らない。成績（平均・t・シャープ・累積・勝率）は計算しない・表示しない
"""
import sys, os, re, io, json, gzip, time, datetime, hashlib, argparse, collections, random, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

BASE = N.BASE
CACHE = N.CACHE
D = os.path.join(CACHE, 'nx_activist')
VERSION = 'nx_activist_data v1 (2026-09-28)'
_EMAIL = re.search(r'^EMAIL\s*=\s*"([^"]+)"', open(os.path.join(BASE, 'hachimon_fetch.py'), encoding='utf-8').read(), re.M).group(1)
HDRS = {"User-Agent": f"hachimon-gate {_EMAIL}"}  # hachimon_fetch.py の HDRS と同じ形
INTERVAL = 0.2  # 既定 5 req/s

FORMS_13 = {'SC 13D', 'SC 13D/A', 'SC 13G', 'SC 13G/A', 'SCHEDULE 13D', 'SCHEDULE 13D/A', 'SCHEDULE 13G', 'SCHEDULE 13G/A'}
FORMS_13D_INITIAL = {'SC 13D', 'SCHEDULE 13D'}  # 2024-12-18 から様式名が SCHEDULE 13D（XML）に変わった
FORMS_CONTEST = {'PREN14A', 'DEFN14A', 'DFAN14A', 'PREC14A', 'DEFC14A'}
FORMS_KEEP = FORMS_13 | FORMS_CONTEST


def _nf(f):
    return f.upper().replace('-', '').replace(' ', '').split('/')[0]


REG_OP_FORMS = {'10K', '10K405', '10KSB', '10KSB40', '10KT', '10KT405', '10Q', '10QSB', '20F', '40F'}  # 事業会社の定期報告
REG_FUND_FORMS = {'NCSR', 'NCSRS', 'NQ', 'N30D', 'NPORTP'}  # 登録投資会社（クローズドエンド型の投信など）の定期報告
F13_FORMS = {'13FHR', '13FNT'}
IDX_VERSION = 'idx v2'  # v2: 事業会社と投資会社の定期報告を分けて持つ

# ───────────────────────── SEC への取得 ─────────────────────────
import threading
_last = [0.0]
_lock = threading.Lock()
STATS = collections.Counter()


def _wait_turn():
    with _lock:
        w = _last[0] + INTERVAL - time.time()
        if w > 0:
            time.sleep(w)
        _last[0] = time.time()


def sec_get(url, tries=6):
    """SEC から取る。INTERVAL 秒に1回まで（スレッドをまたいで共有）。429/5xx/通信失敗は間をあけて再試行・404 はそのまま上げる"""
    err = None
    for i in range(tries):
        _wait_turn()
        try:
            req = urllib.request.Request(url, headers={**HDRS, 'Accept-Encoding': 'gzip, deflate'})
            with urllib.request.urlopen(req, timeout=180) as r:
                b = r.read()
                enc = r.headers.get('Content-Encoding', '')
            STATS['requests'] += 1
            STATS['bytes_wire'] += len(b)
            if enc == 'gzip':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            err = e
            if e.code == 404:
                raise
            time.sleep(min(60, 2 ** (i + 1)) + random.random())
        except Exception as e:  # noqa
            err = e
            time.sleep(min(60, 2 ** (i + 1)) + random.random())
    raise RuntimeError(f'取得失敗 {url}: {err}')


def _save_json(p, obj, gz=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f'{p}.{os.getpid()}.tmp'
    if gz:
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    else:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _load_json(p):
    if p.endswith('.gz'):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            return json.load(f)
    return json.load(open(p, encoding='utf-8'))


# ───────────────────────── 1. full-index ─────────────────────────
def quarters(first=(1993, 1)):
    t = datetime.date.today()
    cur = (t.year, (t.month - 1) // 3 + 1)
    y, q = first
    while (y, q) <= cur:
        yield y, q, (y, q) == cur
        q += 1
        if q == 5:
            y, q = y + 1, 1


def index_quarter(y, q, current):
    p = os.path.join(D, 'idx', f'{y}Q{q}.json.gz')
    if os.path.exists(p) and (not current or time.time() - os.path.getmtime(p) < 86400):
        o = _load_json(p)
        if o.get('idx_version') == IDX_VERSION:
            return o
    b = sec_get(f'https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/master.gz')
    txt = gzip.decompress(b).decode('latin-1') if b[:2] == b'\x1f\x8b' else b.decode('latin-1')
    rows, reg, fund, f13 = [], {}, {}, {}
    started = False
    n_lines = 0
    for line in txt.splitlines():
        if not started:
            if line.startswith('-----'):
                started = True
            continue
        parts = line.split('|')
        if len(parts) != 5:
            continue
        n_lines += 1
        cik, name, form, date, fn = parts
        form = form.strip()
        if form in FORMS_KEEP:
            acc = fn.strip().rsplit('/', 1)[-1].replace('.txt', '')
            rows.append([int(cik), name.strip(), form, date.strip(), acc])
            continue
        nf = _nf(form)
        tgt = reg if nf in REG_OP_FORMS else fund if nf in REG_FUND_FORMS else f13 if nf in F13_FORMS else None
        if tgt is not None:
            c = int(cik)
            v = tgt.get(c)
            if v is None:
                tgt[c] = [date, date]
            else:
                if date < v[0]:
                    v[0] = date
                if date > v[1]:
                    v[1] = date
    obj = {'q': f'{y}Q{q}', 'lines': n_lines, 'rows': rows, 'reg': reg, 'fund': fund, 'f13': f13, 'version': VERSION, 'idx_version': IDX_VERSION,
           'fetched': datetime.datetime.utcnow().isoformat(timespec='seconds')}
    _save_json(p, obj, gz=True)
    return obj


def cmd_index(a):
    n = 0
    for y, q, cur in quarters():
        o = index_quarter(y, q, cur)
        n += 1
        c = collections.Counter(r[2] for r in o['rows'])
        print(f"{o['q']}: 索引の行 {o['lines']:,}  13D初回 {c['SC 13D'] + c['SCHEDULE 13D']:,}  13D/A {c['SC 13D/A'] + c['SCHEDULE 13D/A']:,}  "
              f"13G {c['SC 13G'] + c['SCHEDULE 13G']:,}  委任状(非経営側) {sum(c[f] for f in FORMS_CONTEST):,}  事業会社 {len(o['reg']):,}  投資会社 {len(o.get('fund', {})):,}  13F {len(o['f13']):,}", flush=True)
    print('四半期', n, '取得', dict(STATS))


def all_idx():
    out = []
    for y, q, cur in quarters():
        p = os.path.join(D, 'idx', f'{y}Q{q}.json.gz')
        if not os.path.exists(p):
            raise SystemExit(f'{p} が無い。先に index を回す')
        out.append(_load_json(p))
    return out


def registrant_spans(idx, with_fund=False):
    """{cik: [最初, 最後]}（事業会社の定期報告・13F）。with_fund=True なら投資会社の定期報告も別に返す"""
    reg, fund, f13 = {}, {}, {}
    for o in idx:
        for src, dst in ((o['reg'], reg), (o.get('fund', {}), fund), (o['f13'], f13)):
            for c, (a, z) in src.items():
                c = int(c)
                v = dst.get(c)
                if v is None:
                    dst[c] = [a, z]
                else:
                    v[0] = min(v[0], a); v[1] = max(v[1], z)
    if with_fund:
        return reg, fund, f13
    return reg, f13


# ───────────────────────── 2. 物言う株主の家（一覧は測る前に固定） ─────────────────────────
# L_NOW: 依頼に名前の挙がった物言う株主と、今（2026-09）広く知られた名前（＝今の知名度で選んだ＝後知恵の偏りあり。事前登録の contamination を見よ）
# L_PRE: Greenwood & Schor (2007 の working paper・JFE 2009『Investor activism and takeovers』p.11) が 1994〜2006 の 13D の
#        標本で「ヘッジファンドの事象の2/3超を占める」と名指しした11の家（2006年までの提出の多さで選ばれた＝2007年以降の知名度と独立）
# 名前の規則は EDGAR の提出者の行の名前（大文字）に当てる。誤って当たった CIK は exclude に CIK と理由で固定する
FAMILIES = {
    # ── L_NOW（依頼の一覧） ──
    'icahn':          {'lists': ['NOW', 'PRE'], 'pat': r'\bICAHN\b|HIGH RIVER|BARBERRY CORP|BECKTON CORP|\bIPH GP\b'},
    'elliott':        {'lists': ['NOW'], 'pat': r'ELLIOTT ASSOCIATES|ELLIOTT INTERNATIONAL|ELLIOTT INVESTMENT MANAGEMENT|ELLIOTT MANAGEMENT|ELLIOTT CAPITAL ADVISORS|ELLIOTT INTERNATIONAL CAPITAL ADVISORS|\bSINGER PAUL\b|\bPAUL E\.? SINGER\b|ELLIOTT ADVISORS'},
    'pershing':       {'lists': ['NOW'], 'pat': r'PERSHING SQUARE|\bACKMAN WILLIAM\b|\bWILLIAM A\.? ACKMAN\b|\bPS MANAGEMENT GP\b'},
    'trian':          {'lists': ['NOW'], 'pat': r'\bTRIAN FUND|\bTRIAN PARTNERS|\bTRIAN STAR|\bPELTZ NELSON\b|\bNELSON PELTZ\b'},
    'starboard':      {'lists': ['NOW'], 'pat': r'STARBOARD VALUE|RCG STARBOARD|STARBOARD LEADERS|\bRAMIUS\b'},
    'third_point':    {'lists': ['NOW', 'PRE'], 'pat': r'THIRD POINT|\bLOEB DANIEL\b|\bDANIEL S\.? LOEB\b'},
    'valueact':       {'lists': ['NOW', 'PRE'], 'pat': r'VALUEACT|\bVA PARTNERS\b|\bUBBEN JEFFREY\b|\bJEFFREY W\.? UBBEN\b'},
    'jana':           {'lists': ['NOW', 'PRE'], 'pat': r'\bJANA PARTNERS\b|\bJANA MASTER\b|\bJANA NIRVANA\b|\bROSENSTEIN BARRY\b|\bBARRY ROSENSTEIN\b'},
    'relational':     {'lists': ['NOW'], 'pat': r'RELATIONAL INVESTORS|\bWHITWORTH RALPH\b|\bRALPH V\.? WHITWORTH\b'},
    'sachem_head':    {'lists': ['NOW'], 'pat': r'SACHEM HEAD'},
    'corvex':         {'lists': ['NOW'], 'pat': r'\bCORVEX\b|\bMEISTER KEITH\b|\bKEITH A\.? MEISTER\b'},
    'engaged':        {'lists': ['NOW'], 'pat': r'ENGAGED CAPITAL|\bWELLING GLENN\b|\bGLENN W\.? WELLING\b'},
    'legion':         {'lists': ['NOW'], 'pat': r'LEGION PARTNERS'},
    'land_buildings': {'lists': ['NOW'], 'pat': r'LAND (&|AND) BUILDINGS|\bLITT JONATHAN\b|\bJONATHAN LITT\b'},
    'barington':      {'lists': ['NOW'], 'pat': r'\bBARINGTON\b|\bMITAROTONDA\b'},
    'clinton':        {'lists': ['NOW'], 'pat': r'CLINTON GROUP|CLINTON RELATIONAL|CLINTON SPECIAL OPPORTUNITIES|CLINTON MAGNOLIA'},
    'marcato':        {'lists': ['NOW'], 'pat': r'\bMARCATO\b|\bMCGUIRE RICHARD T\b'},
    'mantle_ridge':   {'lists': ['NOW'], 'pat': r'MANTLE RIDGE|\bHILAL PAUL\b|\bPAUL C\.? HILAL\b'},
    'de_shaw':        {'lists': ['NOW'], 'pat': r'\bD\.? ?E\.? SHAW\b|\bSHAW DAVID E\b|\bDAVID E\.? SHAW\b'},
    # ── L_NOW（「ほか」: 2026-09 に広く知られた米国の物言う株主。今の知名度で選んだ） ──
    'greenlight':     {'lists': ['NOW'], 'pat': r'GREENLIGHT CAPITAL|\bEINHORN DAVID\b|\bDAVID EINHORN\b'},
    'steel_partners': {'lists': ['NOW', 'PRE'], 'pat': r'STEEL PARTNERS|\bLICHTENSTEIN WARREN\b|\bWARREN G\.? LICHTENSTEIN\b'},
    'ancora':         {'lists': ['NOW'], 'pat': r'\bANCORA (ADVISORS|CAPITAL|GROUP|HOLDINGS|CATALYST|MERLIN|ALTERNATIVES)\b'},
    'blackwells':     {'lists': ['NOW'], 'pat': r'BLACKWELLS'},
    'politan':        {'lists': ['NOW'], 'pat': r'\bPOLITAN CAPITAL|\bPOLITAN INTERMEDIATE|\bKOFFEY QUENTIN\b'},
    'irenic':         {'lists': ['NOW'], 'pat': r'IRENIC CAPITAL'},
    'impactive':      {'lists': ['NOW'], 'pat': r'IMPACTIVE CAPITAL'},
    'engine':         {'lists': ['NOW'], 'pat': r'\bENGINE CAPITAL\b|\bENGINE JET CAPITAL\b|\bENGINE INVESTMENTS\b'},
    'macellum':       {'lists': ['NOW'], 'pat': r'MACELLUM'},
    'sarissa':        {'lists': ['NOW'], 'pat': r'SARISSA CAPITAL'},
    'voce':           {'lists': ['NOW'], 'pat': r'VOCE CAPITAL|VOCE CATALYST'},
    'glenview':       {'lists': ['NOW'], 'pat': r'GLENVIEW CAPITAL'},
    'harbinger':      {'lists': ['NOW'], 'pat': r'HARBINGER CAPITAL PARTNERS|HARBINGER GROUP|\bFALCONE PHILIP\b|\bPHILIP A\.? FALCONE\b'},
    'tci':            {'lists': ['NOW'], 'pat': r"CHILDREN'?S INVESTMENT FUND|\bTCI FUND MANAGEMENT\b"},
    'cevian':         {'lists': ['NOW'], 'pat': r'\bCEVIAN\b'},
    # ── L_PRE だけ（Greenwood & Schor 2007 の名指し。上の icahn・third_point・valueact・jana・steel_partners も L_PRE） ──
    'farallon':       {'lists': ['PRE'], 'pat': r'FARALLON'},
    'wynnefield':     {'lists': ['PRE'], 'pat': r'WYNNEFIELD|\bOBUS NELSON\b|\bNELSON OBUS\b'},
    'blum':           {'lists': ['PRE'], 'pat': r'BLUM CAPITAL|BLUM STRATEGIC|\bBLUM RICHARD C\b|\bRICHARD C\.? BLUM\b'},
    'chapman':        {'lists': ['PRE'], 'pat': r'CHAPMAN CAPITAL|\bCHAP CAP\b|\bCHAP-CAP\b|\bCHAPMAN ROBERT L\b|\bROBERT L\.? CHAPMAN\b'},
    'newcastle':      {'lists': ['PRE'], 'pat': r'NEWCASTLE PARTNERS|NEWCASTLE CAPITAL|\bSCHWARZ MARK E\b|\bMARK E\.? SCHWARZ\b'},
    'pirate':         {'lists': ['PRE'], 'pat': r'PIRATE CAPITAL|JOLLY ROGER|\bHUDSON THOMAS R\b|\bTHOMAS R\.? HUDSON\b'},
}
# 名前の規則が誤って当てた CIK（名前を見て決めた・成績は見ていない）。families 段の表示を見て埋める
EXCLUDE = {
    1883139: {'icahn': 'ICAHN SCHOOL OF MEDICINE AT MOUNT SINAI＝医科大学（寄付で株を受けた側）。Icahn の運用の主体ではない'},
    1059653: {'de_shaw': 'DE SHAW PAUL＝同じ綴りの別人（D. E. Shaw の運用の主体ではない）'},
    1641086: {'starboard': 'Ramius Archview Credit & Distressed Fund（2017・Starboard が 2011年に独立した後の Ramius の信用・破綻債の基金）'},
}
# 名前の規則の判断（名前だけで決めた・成績は見ていない）
#   starboard に RAMIUS を入れた: Starboard の活動家の班は 2011年の独立まで Ramius（RAMIUS CAPITAL GROUP / RAMIUS LLC）の中にいて、
#     その時期の 13D は Ramius の名で出ている（Starboard Value & Opportunity の基金は Ramius の基金だった）
#   trian は PELTZ NELSON だけ（PELTZ BENJAMIN・Triarc Companies〔事業会社・Peltz の会社〕は入れない）
#   chapman に CHAP CAP（Chap-Cap Partners・Chap-Cap Activist Partners＝Robert L. Chapman の基金）を入れた
#   ancora は ANCORA の運用の各社（Advisors・Capital・Group・Holdings ほか）


def _13d_rows(idx, initial_only=False):
    for o in idx:
        for r in o['rows']:
            f = r[2]
            if f in FORMS_13D_INITIAL or (not initial_only and f in ('SC 13D/A', 'SCHEDULE 13D/A')):
                yield r


def family_ciks(idx=None, show=False):
    idx = idx or all_idx()
    reg, f13 = registrant_spans(idx)
    pats = {k: re.compile(v['pat'], re.I) for k, v in FAMILIES.items()}
    hit = collections.defaultdict(lambda: collections.defaultdict(lambda: {'names': collections.Counter(), 'n13d': 0, 'n13d_init': 0, 'first': None, 'last': None}))
    for r in _13d_rows(idx):
        cik, name, form, date, acc = r
        for k, pt in pats.items():
            if pt.search(name):
                h = hit[k][cik]
                h['names'][name] += 1
                h['n13d'] += 1
                h['n13d_init'] += form in FORMS_13D_INITIAL
                h['first'] = min(h['first'] or date, date)
                h['last'] = max(h['last'] or date, date)
    out = {}
    for k in FAMILIES:
        rows = []
        for cik, h in sorted(hit[k].items(), key=lambda kv: -kv[1]['n13d']):
            ex = EXCLUDE.get(cik, {}).get(k) if isinstance(EXCLUDE.get(cik), dict) else None
            rows.append({'cik': cik, 'names': [n for n, _ in h['names'].most_common(3)], 'n13d': h['n13d'], 'n13d_init': h['n13d_init'],
                         'first': h['first'], 'last': h['last'], 'registrant': cik in reg, 'f13': cik in f13, 'excluded': ex})
        out[k] = {'lists': FAMILIES[k]['lists'], 'pat': FAMILIES[k]['pat'], 'ciks': rows}
    return out


def cmd_families(a):
    fam = family_ciks()
    _save_json(os.path.join(D, 'families.json'), {'version': VERSION, 'families': fam})
    for k, v in fam.items():
        use = [r for r in v['ciks'] if not r['excluded']]
        print(f"\n■ {k} {v['lists']}  CIK {len(use)}（除外 {len(v['ciks']) - len(use)}）  13D初回 {sum(r['n13d_init'] for r in use)}")
        for r in v['ciks']:
            flag = ('×除外:' + r['excluded']) if r['excluded'] else ''
            print(f"   {r['cik']:>8} {r['names'][0][:48]:<48} 13D {r['n13d']:>4} 初回 {r['n13d_init']:>4} {r['first']}〜{r['last']} "
                  f"{'登録会社' if r['registrant'] else ''} {'13F' if r['f13'] else ''} {flag}")


# ───────────────────────── 3. 見出し（対象会社の同定） ─────────────────────────
def used_family_ciks(fam=None):
    """{cik: set(家)}（除外を除く）"""
    fam = fam or _load_json(os.path.join(D, 'families.json'))['families']
    m = collections.defaultdict(set)
    for k, v in fam.items():
        for r in v['ciks']:
            if not r['excluded']:
                m[r['cik']].add(k)
    return m


def acc_rows(idx, forms):
    """{受付番号: [(cik, name, form, date)]}（forms の様式だけ）"""
    m = collections.defaultdict(list)
    for o in idx:
        for cik, name, form, date, acc in o['rows']:
            if form in forms:
                m[acc].append((cik, name, form, date))
    return m


def parse_hdr(txt):
    h = {'type': None, 'filing_date': None, 'acceptance': None, 'group_members': [], 'subject': [], 'filed_by': []}
    cur = None
    blk = None
    for line in txt.splitlines():
        line = line.strip()
        m = re.match(r'<([A-Z0-9-]+)>(.*)$', line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == 'TYPE' and h['type'] is None:
            h['type'] = val
        elif tag == 'FILING-DATE':
            h['filing_date'] = val
        elif tag == 'ACCEPTANCE-DATETIME':
            h['acceptance'] = val
        elif tag == 'GROUP-MEMBERS':
            h['group_members'].append(val)
        elif tag in ('SUBJECT-COMPANY', 'FILED-BY', 'FILER', 'REPORTING-OWNER'):
            cur = {'name': None, 'cik': None, 'sic': None, 'state_inc': None}
            blk = 'subject' if tag == 'SUBJECT-COMPANY' else 'filed_by'
            h[blk].append(cur)
        elif tag.startswith('/') and cur is not None:
            pass
        elif cur is not None:
            if tag == 'CONFORMED-NAME':
                cur['name'] = val
            elif tag == 'CIK':
                cur['cik'] = int(val)
            elif tag == 'ASSIGNED-SIC':
                cur['sic'] = int(val) if val.isdigit() else None
            elif tag == 'STATE-OF-INCORPORATION':
                cur['state_inc'] = val
    return h


def fetch_hdr(acc, ciks):
    p = os.path.join(D, 'hdr', acc + '.json')
    if os.path.exists(p):
        return _load_json(p)
    nd = acc.replace('-', '')
    err = None
    for c in ciks:
        for u in (f'https://www.sec.gov/Archives/edgar/data/{c}/{nd}/{acc}.hdr.sgml',
                  f'https://www.sec.gov/Archives/edgar/data/{c}/{nd}/{acc}-index-headers.html'):
            try:
                txt = sec_get(u).decode('latin-1')
            except urllib.error.HTTPError as e:
                err = e
                continue
            if u.endswith('.html'):
                txt = txt.split('-->')[0]
            h = parse_hdr(txt)
            h['acc'] = acc
            h['url'] = u
            _save_json(p, h)
            return h
    h = {'acc': acc, 'error': str(err)}
    _save_json(p, h)
    return h


def cmd_headers(a):
    idx = all_idx()
    fm = used_family_ciks()
    want = FORMS_13D_INITIAL | FORMS_CONTEST
    am = acc_rows(idx, want)
    todo = []
    for acc, rows in am.items():
        fams = set()
        for cik, name, form, date in rows:
            fams |= fm.get(cik, set())
        if fams:
            todo.append((rows[0][3], acc, [c for c, *_ in rows if c in fm] + [c for c, *_ in rows if c not in fm]))
    todo.sort()
    have = sum(os.path.exists(os.path.join(D, 'hdr', acc + '.json')) for _, acc, _ in todo)
    print(f'見出しを取る受付番号 {len(todo):,}（取得済み {have:,}）', flush=True)
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(fetch_hdr, acc, ciks) for _, acc, ciks in todo]
        for i, f in enumerate(cf.as_completed(futs)):
            f.result()
            if i % 250 == 0:
                print(f'  {i:,}/{len(todo):,} 取得 {dict(STATS)}', flush=True)
    err = sum(1 for _, acc, _ in todo if 'error' in _load_json(os.path.join(D, 'hdr', acc + '.json')))
    print('完了。取れなかった見出し', err, dict(STATS))


# ───────────────────────── 4. 機械の定義 L_MECH（見出しを取らない） ─────────────────────────
def _d(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def cmd_mech(a):
    idx = all_idx()
    reg_op, fund, f13 = registrant_spans(idx, with_fund=True)
    reg = dict(fund)
    for c, v in reg_op.items():
        reg[c] = [min(v[0], reg[c][0]), max(v[1], reg[c][1])] if c in reg else v
    am = acc_rows(idx, FORMS_13D_INITIAL)
    out, why = [], collections.Counter()
    for acc, rows in am.items():
        date = min(r[3] for r in rows)
        d = _d(date)
        ciks = sorted(set(r[0] for r in rows))
        names = {r[0]: r[1] for r in rows}

        def is_reg(c):
            v = reg.get(c)
            return bool(v and _d(v[0]) <= d + datetime.timedelta(days=400) and _d(v[1]) >= d - datetime.timedelta(days=400))
        subj = [c for c in ciks if is_reg(c)]
        if len(ciks) < 2:
            why['CIK が1つだけ（提出者か対象かが分からない）'] += 1
            continue
        if len(subj) != 1:
            why[f'登録会社の候補が {min(len(subj), 2)}{"以上" if len(subj) >= 2 else ""}'] += 1
            continue
        filers = [c for c in ciks if c != subj[0]]
        out.append([acc, date, subj[0], names[subj[0]], filers, [names[c] for c in filers]])
        why['対象が1社に決まった'] += 1
    out.sort(key=lambda r: r[1])
    _save_json(os.path.join(D, 'mech_filings.json.gz'), {'version': VERSION, 'rows': out,
               'f13': {str(k): v for k, v in f13.items()}, 'why': dict(why)}, gz=True)
    print('初回 13D の受付番号', len(am), dict(why))


# ───────────────────────── 5. 事象の一覧（事前登録の約束どおり） ─────────────────────────
EVENT_START = '1996-07-01'      # EDGAR の電子提出が全登録会社で義務になった 1996-05 の後（それより前の 13D は紙の提出が混じる）
MECH_START = '2000-07-01'       # 13F の電子提出が始まった 1999Q2 の1年後（機関投資家かどうかを当時の値で決めるため）
MECH_LOOKBACK_DAYS = 3 * 365    # L_MECH: 過去3年に
MECH_MIN_TARGETS = 3            #          3社以上の異なる会社に初回 13D を出した
REPEAT_DAYS = 730               # 同じ家が同じ会社に24か月以内に出した初回 13D は新しい事象にしない
EXCL_SIC = {6770, 6726}         # 白地小切手会社（SPAC）・投資会社（クローズドエンド型など）
BLANK_CHECK_NAME = re.compile(r'\bACQUISITION (CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|HOLDINGS|INC)\b\.?|\bSPAC\b', re.I)
EXCH_RANK = {'NYSE': 0, 'Nasdaq': 0, 'CBOE': 1, 'OTC': 2, None: 3}


def load_tickers():
    p = os.path.join(D, 'company_tickers_exchange.json')
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 7 * 86400:
        b = sec_get('https://www.sec.gov/files/company_tickers_exchange.json')
        open(p, 'wb').write(b)
    j = json.load(open(p))
    m = collections.defaultdict(list)
    for i, (cik, name, tk, ex) in enumerate(j['data']):
        m[int(cik)].append({'ticker': tk, 'exchange': ex, 'order': i, 'name': name})
    return m, time.strftime('%Y-%m-%d', time.gmtime(os.path.getmtime(p)))


def pick_ticker(cands):
    """事前登録の規則: 取引所の順（NYSE・Nasdaq → CBOE → OTC → 不明）、次に『-』の無い記号（優先株・ワラント・ユニットを避ける）、
    次に SEC の表の並び順。Yahoo の記号は SEC の記号の『.』を『-』に直したもの（SEC の表は既に『-』）"""
    if not cands:
        return None
    c = sorted(cands, key=lambda x: (EXCH_RANK.get(x['exchange'], 3), '-' in x['ticker'], x['order']))[0]
    return {'ticker': c['ticker'], 'exchange': c['exchange'], 'alternatives': [x['ticker'] for x in cands if x['ticker'] != c['ticker']]}


_SUF = re.compile(r'\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|GROUP|HOLDINGS?|HLDGS|THE|SA|NV|N V|AG|LLC|LP|L P|TRUST|REIT|INTERNATIONAL|INTL)\b')


def norm_name(n):
    n = (n or '').upper()
    n = re.sub(r'/[A-Z ]+/?$', '', n)
    n = re.sub(r'[^A-Z0-9 ]', ' ', n)
    n = _SUF.sub(' ', n)
    return ' '.join(n.split())


def successor_finder(tick, reg_op):
    """今のティッカーが無い対象会社の『後継の CIK』（持株会社への組み替え・本拠地の移転で CIK だけが変わった会社）を、保守的な規則で探す:
    (a) 会社の名前が接尾語（Inc・Corp・Group・Holdings・Ltd ほか）を除いて完全に一致し、(b) 新しい CIK の最初の事業会社の定期報告が、
    古い CIK の最後の定期報告の 180日前〜400日後に入り、(c) 新しい CIK に今のティッカーがある。候補が1つのときだけ使う"""
    by_name = collections.defaultdict(set)
    for c, lst in tick.items():
        for t in lst:
            by_name[norm_name(t['name'])].add(c)

    def find(cik, name):
        old = reg_op.get(cik)
        if not old:
            return None
        ok = []
        for c in by_name.get(norm_name(name), set()) - {cik}:
            v = reg_op.get(c)
            if v and _d(old[1]) - datetime.timedelta(days=180) <= _d(v[0]) <= _d(old[1]) + datetime.timedelta(days=400):
                ok.append(c)
        return ok[0] if len(ok) == 1 else None
    return find


def subject_kind(cik, d, reg_op, fund):
    """事業会社 / 投資会社 / 不明（事象の日の前後400日の定期報告の様式で決める）"""
    def near(v):
        return bool(v and _d(v[0]) <= d + datetime.timedelta(days=400) and _d(v[1]) >= d - datetime.timedelta(days=400))
    op, fu = near(reg_op.get(cik)), near(fund.get(cik))
    return 'operating' if op else 'fund' if fu else 'unknown'


def _exclusion(sic, name, kind):
    if sic in EXCL_SIC:
        return f'SIC {sic}'
    if name and BLANK_CHECK_NAME.search(name):
        return '名前が白地小切手会社（… Acquisition Corp）'
    if kind == 'fund':
        return '投資会社（N-CSR 等だけを出す）'
    return None


def _mark_repeats(evs, key):
    """同じ key（家・対象）で REPEAT_DAYS 以内の後続を repeat にする（最初の事象だけを残す）"""
    last = {}
    for e in sorted(evs, key=lambda e: (e['date'], e['acc'])):
        ks = key(e)
        rep = False
        for k in ks:
            if k in last and (_d(e['date']) - _d(last[k])).days <= REPEAT_DAYS:
                rep = True
        e['repeat_24m'] = rep
        for k in ks:
            last[k] = e['date']


def cmd_events(a):
    idx = all_idx()
    fam = _load_json(os.path.join(D, 'families.json'))['families']
    fm = used_family_ciks(fam)
    fam_ciks = set(fm)
    reg_op, fund, f13 = registrant_spans(idx, with_fund=True)
    tick, tick_date = load_tickers()
    succ = successor_finder(tick, reg_op)
    stat = collections.Counter()

    def ticker_for(cik, name):
        tk = pick_ticker(tick.get(cik, []))
        if tk:
            return tk, None
        c2 = succ(cik, name)
        if c2:
            stat['後継の CIK でティッカーを付けた'] += 1
            return pick_ticker(tick.get(c2, [])), c2
        return None, None

    def build(forms, kind_label):
        am = acc_rows(idx, forms)
        out = []
        for acc, rows in am.items():
            if not any(c in fm for c, *_ in rows):
                continue
            hp = os.path.join(D, 'hdr', acc + '.json')
            if not os.path.exists(hp):
                stat[f'{kind_label}: 見出しが未取得'] += 1
                continue
            h = _load_json(hp)
            if h.get('error') or not h.get('subject'):
                stat[f'{kind_label}: 見出しに対象会社が無い'] += 1
                continue
            sj = h['subject'][0]
            sc = sj['cik']
            filers = (set(c for c, *_ in rows) | set(x['cik'] for x in h['filed_by'] if x.get('cik'))) - {sc}
            fams = sorted(set().union(*[fm[c] for c in filers if c in fm])) if any(c in fm for c in filers) else []
            if not fams:
                stat[f'{kind_label}: 家は対象会社の側にだけいた（事象ではない）'] += 1
                continue
            date = min(r[3] for r in rows)
            d = _d(date)
            kd = subject_kind(sc, d, reg_op, fund)
            lists = sorted(set(l for f in fams for l in FAMILIES[f]['lists']))
            tk, via = ticker_for(sc, sj['name'])
            e = {'acc': acc, 'form': rows[0][2], 'date': date, 'hdr_filing_date': h.get('filing_date'), 'acceptance': h.get('acceptance'),
                 'subject_cik': sc, 'subject_name': sj['name'], 'sic': sj.get('sic'), 'state_inc': sj.get('state_inc'),
                 'subject_kind': kd, 'families': fams, 'lists': lists, 'filer_ciks': sorted(filers),
                 'self_affiliated': sc in fam_ciks, 'group_members': h.get('group_members', [])[:12],
                 'exclusion': ('対象会社が家の CIK（自分の運用の器）' if sc in fam_ciks else _exclusion(sj.get('sic'), sj['name'], kd)),
                 'ticker': tk['ticker'] if tk else None, 'exchange_now': tk['exchange'] if tk else None,
                 'ticker_alternatives': tk['alternatives'] if tk else [], 'ticker_via_successor_cik': via}
            out.append(e)
        return out

    ev13 = build(FORMS_13D_INITIAL, '13D')
    _mark_repeats(ev13, lambda e: [(f, e['subject_cik']) for f in e['families']])
    evc = build(FORMS_CONTEST, '委任状')
    _mark_repeats(evc, lambda e: [(f, e['subject_cik']) for f in e['families']])

    # L_MECH（見出し無し・機械の定義）
    mp = os.path.join(D, 'mech_filings.json.gz')
    mech = []
    if os.path.exists(mp):
        mo = _load_json(mp)
        rows = mo['rows']
        by_filer = collections.defaultdict(list)
        for acc, date, sc, sname, filers, fnames in rows:
            for c in filers:
                by_filer[c].append((date, sc))
        for c in by_filer:
            by_filer[c].sort()
        for acc, date, sc, sname, filers, fnames in rows:
            if date < MECH_START:
                continue
            d = _d(date)
            serial = []
            for c in filers:
                v13 = f13.get(c)
                if not (v13 and v13[0] <= date):
                    continue
                vr = reg_op.get(c)
                if vr and vr[0] <= date and _d(vr[1]) >= d - datetime.timedelta(days=400):
                    continue  # 提出者が事業会社（事業上の買収・持ち合い）
                lo = (d - datetime.timedelta(days=MECH_LOOKBACK_DAYS)).isoformat()
                prev = set(s2 for (d2, s2) in by_filer[c] if lo <= d2 < date and s2 != sc)
                if len(prev) >= MECH_MIN_TARGETS:
                    serial.append(c)
            if not serial:
                continue
            kd = subject_kind(sc, d, reg_op, fund)
            tk, via = ticker_for(sc, sname)
            mech.append({'acc': acc, 'date': date, 'subject_cik': sc, 'subject_name': sname, 'subject_kind': kd,
                         'serial_filers': serial, 'serial_names': [fnames[filers.index(c)] for c in serial],
                         'in_L_NOW_or_L_PRE': bool(set(filers) & fam_ciks),
                         'exclusion': _exclusion(None, sname, kd), 'sic': None,
                         'ticker': tk['ticker'] if tk else None, 'exchange_now': tk['exchange'] if tk else None,
                         'ticker_alternatives': tk['alternatives'] if tk else [], 'ticker_via_successor_cik': via})
        _mark_repeats(mech, lambda e: [('mech', e['subject_cik'])])
    else:
        stat['L_MECH: mech_filings.json.gz が無い（mech を先に回す）'] += 1

    obj = {'version': VERSION, 'generated': datetime.date.today().isoformat(), 'tickers_file_date': tick_date,
           'rules': {'EVENT_START': EVENT_START, 'MECH_START': MECH_START, 'MECH_LOOKBACK_DAYS': MECH_LOOKBACK_DAYS,
                     'MECH_MIN_TARGETS': MECH_MIN_TARGETS, 'REPEAT_DAYS': REPEAT_DAYS, 'EXCL_SIC': sorted(EXCL_SIC),
                     'BLANK_CHECK_NAME': BLANK_CHECK_NAME.pattern},
           'families': {k: {'lists': v['lists'], 'pat': v['pat'], 'ciks': [r['cik'] for r in v['ciks'] if not r['excluded']]} for k, v in fam.items()},
           'exclude': {str(k): v for k, v in EXCLUDE.items()},
           'events_13d': sorted(ev13, key=lambda e: (e['date'], e['acc'])),
           'events_contest': sorted(evc, key=lambda e: (e['date'], e['acc'])),
           'events_mech': sorted(mech, key=lambda e: (e['date'], e['acc'])),
           'build_stats': dict(stat)}
    obj['sha256'] = events_sha(obj)
    obj['sha256_events_only'] = events_sha(obj, with_tickers=False)
    _save_json(os.path.join(D, 'events.json'), obj)
    print('事象の一覧を書いた', os.path.join(D, 'events.json'), 'sha256', obj['sha256'])
    print('作る途中で数えたもの', dict(stat))
    cmd_status(a)


def events_sha(obj, with_tickers=True):
    """測る道具が照合する sha256: 各事象の（受付番号・日付・対象 CIK・家・一覧・除外・24か月の重複・ティッカー）と規則と家の CIK を
    sort_keys・区切り詰めで直列化した sha256（一覧や対応表を結果を見てから作り直していないことの証明）"""
    keep = lambda es, ks: [{k: e.get(k) for k in ks} for e in es]
    ks = ['acc', 'date', 'subject_cik', 'families', 'lists', 'exclusion', 'repeat_24m', 'ticker', 'ticker_via_successor_cik', 'serial_filers']
    if not with_tickers:  # 今のティッカー表は日々変わる。事象・家・除外・重複だけの指紋（ティッカー表を取り直しても変わらない）
        ks = [k for k in ks if not k.startswith('ticker')]
    core = {'rules': obj['rules'], 'families': obj['families'],
            'e13': keep(obj['events_13d'], ks), 'ec': keep(obj['events_contest'], ks), 'em': keep(obj['events_mech'], ks)}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _usable(e, lst=None, start=EVENT_START):
    return (e['date'] >= start and not e.get('exclusion') and not e.get('repeat_24m')
            and (lst is None or lst in e.get('lists', [lst])))


def cmd_status(a):
    o = _load_json(os.path.join(D, 'events.json'))
    print(f"\n版 {o['version']}  作成 {o['generated']}  SEC のティッカー表 {o['tickers_file_date']}  sha256 {o['sha256'][:16]}…")
    groups = [('L_NOW', o['events_13d'], 'NOW', EVENT_START), ('L_PRE（全期間）', o['events_13d'], 'PRE', EVENT_START),
              ('L_PRE（2007-01〜）', o['events_13d'], 'PRE', '2007-01-01'), ('L_MECH', o['events_mech'], None, MECH_START),
              ('委任状（L_NOW の家）', o['events_contest'], 'NOW', EVENT_START)]
    for lab, es, lst, st in groups:
        allv = [e for e in es if (lst is None or lst in e.get('lists', [lst])) and e['date'] >= st]
        use = [e for e in allv if not e.get('exclusion') and not e.get('repeat_24m')]
        tk = [e for e in use if e['ticker']]
        tg = len(set(e['subject_cik'] for e in use))
        exc = collections.Counter((e['exclusion'] or '')[:24] for e in allv if e.get('exclusion'))
        print(f"\n■ {lab}: 事象 {len(allv):,}（除外 {sum(exc.values())}・24か月の重複 {sum(1 for e in allv if e.get('repeat_24m') and not e.get('exclusion'))}）"
              f" → 使う事象 {len(use):,}・対象会社 {tg:,}・今のティッカーあり {len(tk):,}（{len(tk) / max(1, len(use)):.0%}）")
        if exc:
            print('   除外の内訳', dict(exc))
        by = collections.defaultdict(lambda: [0, 0])
        for e in use:
            y = e['date'][:4]
            by[y][0] += 1
            by[y][1] += bool(e['ticker'])
        print('   年: ' + '  '.join(f"{y} {n}/{t}" for y, (n, t) in sorted(by.items())) + '  （事象/ティッカーあり）')
        ex = collections.Counter(e['exchange_now'] for e in tk)
        print('   今の取引所', dict(ex))
        if lst:
            fc = collections.Counter(f for e in use for f in e['families'] if lst in FAMILIES.get(f, {}).get('lists', []))
            print('   家ごとの事象', dict(fc.most_common()))
    print('\n作る途中で数えたもの', o.get('build_stats'))


# ───────────────────────── 6. 欠けの抜き取り検査の標本（事前登録で固定） ─────────────────────────
AUDIT_SEED, AUDIT_N, AUDIT_FROM, AUDIT_TO = 20260928, 40, '2005-01-01', '2019-12-31'


def audit_sample(o=None):
    """L_NOW の使う事象のうち今のティッカーが無いもの（base で落ちる）から、提出日 2005〜2019 の40件を種 20260928 で無作為に選ぶ。
    測る道具が上場廃止した銘柄の株価（Alpha Vantage・FMP など）を当たれるなら、この40件だけで欠けの向きを見積もる（報告のみ）"""
    import random
    o = o or _load_json(os.path.join(D, 'events.json'))
    pool = sorted((e for e in o['events_13d'] if 'NOW' in e['lists'] and _usable(e) and not e['ticker'] and AUDIT_FROM <= e['date'] <= AUDIT_TO),
                  key=lambda e: e['acc'])
    pick = random.Random(AUDIT_SEED).sample(pool, min(AUDIT_N, len(pool)))
    return len(pool), [{k: e[k] for k in ('acc', 'date', 'subject_cik', 'subject_name', 'families')} for e in sorted(pick, key=lambda e: e['date'])]


def cmd_audit(a):
    n, pick = audit_sample()
    _save_json(os.path.join(D, 'audit_sample.json'), {'seed': AUDIT_SEED, 'pool': n, 'sample': pick})
    print(f'母集団 {n} 件から {len(pick)} 件')
    for e in pick:
        print(' ', e['date'], e['acc'], e['subject_cik'], e['subject_name'][:40], e['families'])


# ───────────────────────── 入口 ─────────────────────────
def main():
    global INTERVAL
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['index', 'families', 'headers', 'mech', 'events', 'status', 'audit'])
    ap.add_argument('--interval', type=float, default=INTERVAL)
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    INTERVAL = max(0.1, a.interval)
    os.makedirs(D, exist_ok=True)
    globals()['cmd_' + a.cmd](a)


if __name__ == '__main__':
    main()
