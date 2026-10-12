#!/usr/bin/env python3
"""night/bestpf_elite_clone.py — bestpf の R2（E1・E2・E3・E3b）（読むだけ・門の判定・採点・配分には不使用）

問い（事前登録 out/bestpf_prereg.json の modules.R2_elite_clone・コミット 7c4b672）:
  成績の良い投資家（Dataroma の Superinvestors 83件）の 13F を、提出が公開された翌月から写して持つと、
  その後 SPY（配当込み）・QQQ・French Mkt に勝ったか（2013Q2〜2026Q2 の提出・持つ期間は 2013-09〜2026-08）。

戦略（事前登録どおり）
  E1  全員の 13F の上位20（各人の中で比重を合計1に）を、人ごとに等しく足す
  E2  その時点で5人以上が持つ銘柄を等しく
  E3  2016年から毎年末、その時点までの過去3年の『写しの成績』の上位10人を選び、その10人の上位10銘柄を等しく持つ
      （翌年は同じ10人の新しい提出に合わせて四半期ごとに直す）＝その時点で分かることだけで選ぶ
  E3b 同じ作り方の下位10人（対照）
  各運用者の『写し』= その人の 13F の株の全保有を 13F の価額の比で持ち、新しい提出が出たら翌月の初めに入れ替える

データ
  13F: EDGAR の各提出の information table XML（R0 の out/_bestpf_cache/ciks.json が四半期ごとの受付番号を決めている）。
       同じ期間の訂正（13F-HR/A）は primary_doc.xml の amendmentType が RESTATEMENT なら置き換え、NEW HOLDINGS なら足す
       （どちらも『その訂正の提出日の翌月』から。前の期間への訂正が次の期間の原本より後に出たら使わない＝古い）。
  価額の単位: 2023-01-03 より前の提出は千ドル・以後はドル（SEC の決まり）。ただし決まりに従わない提出者がいる
       （R0 が 2026Q2 に千ドルのまま4件を見つけた）ので、提出ごとに 13F の合意の株価（R2b の qpx・FTD の終値）と
       暗黙の株価（価額÷株数）を突き合わせて 10 のべきを決める（比重には効かない。訂正を原本に足すときだけ効く）。
  株だけ: プット/コールの行・SH でない行（社債など PRN）・優先株/社債/ワラント/権利の題名・ETF/投信の名前・
       OpenFIGI の種類が ETP/投信/優先株など、を除く。同じ発行体の複数の種類（GOOG/GOOGL 等）は CUSIP の頭6桁で1銘柄にまとめる。
  記号: night/mw_best_ideas_13f.resolve（FTD の当時の記号と OpenFIGI の記号の候補を、13F の当時の株価と ±15% で照合）。
  株価: Yahoo の月次（配当込み）。価格の取れない銘柄は O（観測できる分で按分＝残りの株と同じ成績と置く・上限ではない）と
       P30（最初の欠けた月に −30%・以後は現金＝悲観の下限）。2026-10-12（検証役の指摘）に中立の N（その月の SPY の配当込みのリターンを置く）と、
       SPY＋x%/年 を置く感度・10人も N で選び直す感度（E3_rank_by_N）・『月 +300% 超＝誤り』の切りを使わない感度（spike_rule）を足した。
       組む前に取引が終わった銘柄（gone_before）は買えないので分母から除く（R2b と同じ）。
  費用: 片道 0.2% を、入れ替えの月の片道の回転（0.5×Σ|目標−漂った比重|）に掛ける（最初に買う費用は掛けない）。
  P30 の −30% は同じ株を持ち続ける間は1回だけ（四半期ごとに買い直すたびに重ねない）。
  記号の照合の足し: 名前を変えた会社の今の記号（ALIAS・当時の終値 ±15% で確かめる）・共有の Yahoo キャッシュの短いファイルの取り直し。
  提出が止まった運用者: 報告期間の末から STALE_MONTHS（9か月）を過ぎた提出は使わない。
  検算: night/bestpf_elite_clone_verify.py（別の書き方の写しと突き合わせ）を --calc の後に回し、もう一度 --calc で要約を JSON に入れる。

段
  --fetch  : submissions と各提出の XML を取る → out/_bestpf_cache/elite_clone/filings/*.json と manifest.json
  --map    : CUSIP → 記号（FTD → OpenFIGI → Yahoo 照合） → resolved.json
  --calc   : 計算して out/bestpf_elite_clone.json を書く（既定）
キャッシュは out/_bestpf_cache/elite_clone/（gitignore）。取ったファイルはデータとして読むだけ（実行しない）。
"""
import datetime, gzip, json, math, os, re, sys, threading, time, urllib.error, urllib.request
import statistics as S
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import mw_best_ideas_13f as B  # noqa: E402

BASE = M.BASE
C = os.path.join(BASE, 'out', '_bestpf_cache', 'elite_clone')
FILD = os.path.join(C, 'filings')
R0SUB = os.path.join(BASE, 'out', '_bestpf_cache', 'R0', 'sub')
R0DOC = os.path.join(BASE, 'out', '_bestpf_cache', 'R0', 'doc')
R2B = os.path.join(BASE, 'out', '_bestpf_cache', 'persistence13f')
CIKS = os.path.join(BASE, 'out', '_bestpf_cache', 'ciks.json')
OUT = os.path.join(BASE, 'out', 'bestpf_elite_clone.json')
PREREG_COMMIT = '7c4b672'
SEC_UA = B.SEC_UA                       # night/mw_best_ideas_13f.py の SEC_UA と同じ
SUB_URL = 'https://data.sec.gov/submissions/{}'
DOLLAR_FROM = 20230103                  # この日以後の提出は価額がドル単位（SEC の決まり）

# ── 事前登録した定数 ──
TOP_E1 = 20                             # E1: 各人の上位20
MIN_E2 = 5                              # E2: 5人以上
TOP_E3_MGR, TOP_E3_STK = 10, 10         # E3: 上位10人・その10人の上位10銘柄
LOOK_E3 = 36                            # 過去3年
COST_ONEWAY = 0.002                     # 片道 0.2%
MISS_P30 = -0.30
VERS = ('O', 'N', 'P30')                # O＝価格の取れない株は残りの株と同じ成績と置く／N＝市場並み（SPY）と置く・中立（2026-10-12 追加）／P30＝悲観の下限
FILL_SWEEP = (5, 10, 20, 30, 50)        # 感度: 価格の取れない株に SPY＋x%/年 を置いたら E3 は合格線に届くか（2026-10-12 追加）
E3_FIRST_SEL = 2015                     # 2015年末に初めて選び 2016-01 から持つ（下の deviations を見よ）
STALE_MONTHS = 9                        # 報告期間の末から9か月を過ぎた提出は使わない（提出が止まった運用者を残さない）
START, END = 201309, B.END              # 持つ期間（最初の提出 2013-08 の翌月〜French の終わり）


# ───────────────────────── 月の算術 ─────────────────────────
def ym_of(date_s):                      # 'YYYY-MM-DD' → yyyymm
    return int(date_s[:4]) * 100 + int(date_s[5:7])


def eff_month(date_s):                  # 提出日の翌月（その月の初めから持つ＝その月のリターンが最初）
    return B.madd(ym_of(date_s), 1)


def per_ym(period_s):                   # '2013-06-30' → 201306
    return ym_of(period_s)


def mdiff(a, b):                        # a − b（月数）
    return (a // 100 - b // 100) * 12 + a % 100 - b % 100


# ───────────────────────── SEC 取得（毎秒10件以下） ─────────────────────────
_lock = threading.Lock()
_last = [0.0]
MIN_GAP = 0.13                          # 約7.7件/秒


def sec_get(url, path, tries=5):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return open(path, 'rb').read()
    err = None
    for i in range(tries):
        with _lock:
            w = _last[0] + MIN_GAP - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, path)
            return b
        except urllib.error.HTTPError as e:
            err = e
            if e.code == 404:
                raise RuntimeError(f'404 {url}')
            time.sleep(3 * (i + 1) if e.code in (403, 429) else 2 * (i + 1))
        except Exception as e:  # noqa
            err = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}: {err}')


def submissions(cik):
    """R0 のキャッシュ（読むだけ）→ 無ければ自分のキャッシュへ取る。→ [{form, reportDate, filingDate, acceptanceDateTime, acc}]"""
    def load(name):
        p0 = os.path.join(R0SUB, name)
        if os.path.exists(p0):
            return json.load(open(p0))
        return json.loads(sec_get(SUB_URL.format(name), os.path.join(C, 'sub', name)))
    j = load(f'CIK{cik}.json')
    recs = []

    def take(bk):
        for i in range(len(bk.get('form', []))):
            recs.append({'form': bk['form'][i], 'reportDate': bk.get('reportDate', [''] * (i + 1))[i],
                         'filingDate': bk['filingDate'][i], 'acceptance': (bk.get('acceptanceDateTime') or [''] * (i + 1))[i],
                         'acc': bk['accessionNumber'][i]})
    take(j['filings']['recent'])
    for f in j['filings'].get('files', []):
        take(load(f['name']))
    return recs


def filing_files(cik, acc):
    nd = acc.replace('-', '')
    base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nd}/'
    p0 = os.path.join(R0DOC, f'{nd}_index.json')
    idx = json.load(open(p0)) if os.path.exists(p0) else json.loads(sec_get(base + 'index.json', os.path.join(C, 'doc', f'{nd}_index.json')))
    return base, nd, [it['name'] for it in idx['directory']['item']]


def doc(cik, acc, name):
    base, nd, _ = filing_files(cik, acc)
    p0 = os.path.join(R0DOC, f'{nd}_{name}')
    if os.path.exists(p0):
        return open(p0, 'rb').read().decode('utf-8', 'ignore')
    return sec_get(base + name, os.path.join(C, 'doc', f'{nd}_{name}')).decode('utf-8', 'ignore')


def tag(blk, t):
    m = re.search(rf'<(?:\w+:)?{t}>\s*([^<]*?)\s*</(?:\w+:)?{t}>', blk, re.S)
    return m.group(1).strip() if m else ''


def parse_primary(t):
    return {'submissionType': tag(t, 'submissionType'), 'period': tag(t, 'periodOfReport'),
            'isAmendment': tag(t, 'isAmendment'), 'amendmentType': tag(t, 'amendmentType'),
            'amendmentNo': tag(t, 'amendmentNo'), 'reportType': tag(t, 'reportType'),
            'tableEntryTotal': tag(t, 'tableEntryTotal'), 'tableValueTotal': tag(t, 'tableValueTotal'),
            'name': tag(t, 'name')}


def parse_infotable(t):
    rows = []
    for blk in re.findall(r'<(?:\w+:)?infoTable>(.*?)</(?:\w+:)?infoTable>', t, re.S):
        rows.append({'name': tag(blk, 'nameOfIssuer'), 'title': tag(blk, 'titleOfClass'), 'cusip': tag(blk, 'cusip'),
                     'value': tag(blk, 'value'), 'sh': tag(blk, 'sshPrnamt'), 'shtype': tag(blk, 'sshPrnamtType'),
                     'putcall': tag(blk, 'putCall')})
    return rows


def get_filing(cik, acc, want_primary):
    """→ {'primary': {...} or None, 'rows': [...] or None, 'infotable_url', 'error'}（キャッシュ filings/{acc}.json）"""
    pth = os.path.join(FILD, acc + '.json')
    if os.path.exists(pth):
        return json.load(open(pth))
    out = {'cik': cik, 'acc': acc, 'primary': None, 'rows': None, 'infotable_url': None, 'error': None}
    try:
        base, nd, names = filing_files(cik, acc)
        if want_primary and 'primary_doc.xml' in names:
            out['primary'] = parse_primary(doc(cik, acc, 'primary_doc.xml'))
        for n in [n for n in names if n.lower().endswith('.xml') and n != 'primary_doc.xml']:
            t = doc(cik, acc, n)
            if re.search(r'<(?:\w+:)?infoTable>', t):
                out['rows'] = parse_infotable(t); out['infotable_url'] = base + n
                break
        if out['rows'] is None:
            out['error'] = 'information table の XML が見つからない'
    except Exception as e:  # noqa
        out['error'] = str(e)[:300]
    os.makedirs(FILD, exist_ok=True)
    json.dump(out, open(pth, 'w'))
    return out


# ───────────────────────── 段1: 取得 ─────────────────────────
def managers():
    return json.load(open(CIKS))['ciks']


def plan():
    """運用者ごとに: 原本（R0 が選んだ受付番号）と同じ CIK・同じ期間の訂正（13F-HR/A）"""
    P = []
    subc = {}
    for c in managers():
        h = c['history_2013q2_2026q2']
        for per, cik, acc in h['quarters']:
            if not cik:
                continue
            if cik not in subc:
                subc[cik] = submissions(cik)
            recs = subc[cik]
            org = next((r for r in recs if r['acc'] == acc), None)
            P.append({'code': c['code'], 'period': per, 'cik': cik, 'acc': acc, 'form': '13F-HR',
                      'filed': org['filingDate'] if org else None, 'acceptance': org['acceptance'] if org else None})
            for r in recs:
                if r['form'] == '13F-HR/A' and r['reportDate'] == per:
                    P.append({'code': c['code'], 'period': per, 'cik': cik, 'acc': r['acc'], 'form': '13F-HR/A',
                              'filed': r['filingDate'], 'acceptance': r['acceptance']})
    return P


def fetch():
    import concurrent.futures as cf
    P = plan()
    print('提出', len(P), '（原本', sum(1 for x in P if x['form'] == '13F-HR'), '・訂正', sum(1 for x in P if x['form'] != '13F-HR'), '）', flush=True)
    done = [0]

    def one(x):
        r = get_filing(x['cik'], x['acc'], want_primary=(x['form'] != '13F-HR'))
        done[0] += 1
        if done[0] % 200 == 0:
            print('  ', done[0], '/', len(P), flush=True)
        return r
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, P))
    errs = Counter((r.get('error') or 'ok')[:60] for r in res)
    print('結果', dict(errs), flush=True)
    json.dump({'made': datetime.date.today().isoformat(), 'filings': P}, open(os.path.join(C, 'manifest.json'), 'w'))


# ───────────────────────── 段2: 読む・株だけにする・単位 ─────────────────────────
YHD_MINE = os.path.join(C, 'yh')
_yh_path_orig = B.yh_path


def _yh_path(sym):
    """Yahoo のキャッシュ: 自分のキャッシュ → 既存の共有キャッシュ（読むだけ）→ 無ければ自分のキャッシュへ。
    ★共有キャッシュには期間の短いファイル（例: EA・AVB・DDS が2〜5か月分だけ）が混じっていた → refetch_short で自分のキャッシュへ取り直す"""
    mine = os.path.join(YHD_MINE, sym.replace('/', '_') + '.json')
    if os.path.exists(mine):
        return mine
    p0 = _yh_path_orig(sym)
    if os.path.exists(p0):
        return p0
    return mine


B.yh_path = _yh_path                    # 書き先だけを自分のキャッシュへ（読み方は B.yh_load のまま）
_yh_fetch_orig = B.yh_fetch


def _yh_fetch(sym):
    os.makedirs(YHD_MINE, exist_ok=True)
    return _yh_fetch_orig(sym)


B.yh_fetch = _yh_fetch


WARRANT_RE = re.compile(r'\bW\s*EXP\b|\bWT\s*EXP\b|\bEXP\s+\d{1,2}/|\bWARRANTS?\b|\bRIGHTS?\b', re.I)


def clean_rows(f, nonstock=None):
    """information table の行 → 株だけ {cusip: [価額（原本の単位）, 株数, 名前, 題名]} と除いた額の内訳（原本の単位）。
    nonstock(cusip) が理由を返す CUSIP（OpenFIGI の種類が ETP・投信・優先株・ワラント等／FTD の説明が投信）も除く"""
    out, drop = {}, Counter()
    for r in f.get('rows') or []:
        try:
            v = float(r['value'] or 0); sh = float(r['sh'] or 0)
        except ValueError:
            drop['bad_number'] += 1; continue
        if r['putcall']:
            drop['putcall_value'] += v; continue
        if (r['shtype'] or '').upper() != 'SH':
            drop['prn_value'] += v; continue
        cu = B.norm_cusip(r['cusip'])
        if not cu or v <= 0 or sh <= 0:
            drop['bad_row_value'] += v; continue
        nm, tt = r['name'], r['title']
        if B.NONCOMMON_RE.search(tt):
            drop['noncommon_title_value'] += v; continue
        if WARRANT_RE.search(tt) or re.search(r'\bWARRANTS?\b', nm, re.I):
            drop['warrant_right_unit_value'] += v; continue
        if B.ETF_RE.search(nm + ' ' + tt):
            drop['etf_fund_value'] += v; continue
        if nonstock and nonstock(cu):
            drop['figi_or_ftd_nonstock_value'] += v; continue
        x = out.setdefault(cu, [0.0, 0.0, nm, tt]); x[0] += v; x[1] += sh
    return out, drop


_ref = {}


def ref_prices(p):
    """報告期間 p（yyyymm）の 13F の合意の株価（$）: R2b の qpx（全提出者の中央値・2014-03〜）と h_201312（12月末）"""
    if p in _ref:
        return _ref[p]
    out = {}
    q = os.path.join(R2B, f'qpx_{p}.json')
    if os.path.exists(q):
        for cu, v in json.load(open(q)).items():
            out[cu] = (v[0], v[1])
    h = os.path.join(R2B, f'h_{p}.json')
    if os.path.exists(h):
        for cu, v in json.load(open(h))['sec'].items():
            if cu not in out and v.get('px_usd'):
                out[cu] = (v['px_usd'], v.get('holders_all') or 1)
    _ref[p] = out
    return out


def unit_mult(rows, p, filed, ftd):
    """提出ごとの価額の単位（×1 か ×1000）。合意の株価（持ち手3社以上）→ FTD の当時の終値 → 提出日の決まり、の順で決める"""
    refs = ref_prices(p)
    lr = []
    for cu, (v, sh, _, _) in rows.items():
        r = refs.get(cu)
        if r and r[1] >= 3 and r[0] > 0:
            lr.append(math.log10((v / sh) / r[0]))
    how = 'consensus'
    if len(lr) < 3:
        lr2 = []
        for cu, (v, sh, _, _) in rows.items():
            e = (ftd.get(cu) or {}).get(str(p))
            if e and e[1]:
                lr2.append(math.log10((v / sh) / e[1]))
        if len(lr2) >= max(1, len(lr)):
            lr, how = lr2, 'ftd'
    rule = 1 if int(filed.replace('-', '')) >= DOLLAR_FROM else 1000
    if not lr:
        return rule, 'date_rule', None
    med = S.median(lr)
    k = round(med)
    if k == 0 and abs(med) < 0.5:
        return 1, how, round(med, 3)
    if k == -3 and abs(med + 3) < 0.5:
        return 1000, how, round(med, 3)
    return rule, how + '_unclear_date_rule', round(med, 3)


def load_filings():
    """manifest と各提出 → 運用者ごとの提出の一覧（株だけ・ドル単位に直した価額）"""
    man = json.load(open(os.path.join(C, 'manifest.json')))['filings']
    return man


# ───────────────────────── 段3: CUSIP → 記号 ─────────────────────────
def build_ftd(cs):
    """FTD（決済の失敗の公表データ・半月ごと・2013-12〜）→ CUSIP ごと・月ごとの当時の記号・終値・名前（mw_best_ideas_13f.build_ftd と同じ読み方）"""
    import zipfile
    out = defaultdict(dict)
    fd = os.path.join(B.C, 'ftd')
    for fn in sorted(os.listdir(fd)):
        if not fn.endswith('.zip'):
            continue
        z = zipfile.ZipFile(os.path.join(fd, fn))
        txt = z.read(z.namelist()[0]).decode('latin-1')
        for line in txt.splitlines()[1:]:
            parts = line.split('|')
            if len(parts) < 6:
                continue
            cu = B.norm_cusip(parts[1])
            if cu not in cs:
                continue
            try:
                ym = int(parts[0][:6]); pxv = float(parts[5]) if parts[5].strip() not in ('', '.') else None
            except ValueError:
                continue
            sym = parts[2].strip().upper()
            e = out[cu].setdefault(ym, [Counter(), None, parts[4].strip()])
            if sym:
                e[0][sym] += 1
            if pxv:
                e[1] = pxv
    js = {cu: {str(ym): [dict(v[0]), v[1], v[2]] for ym, v in d.items()} for cu, d in out.items()}
    json.dump(js, open(os.path.join(C, 'ftd_index.json'), 'w'))
    print('FTD: CUSIP', len(cs), '→ FTD に出た', len(js), flush=True)
    return js


def load_ftd():
    return json.load(open(os.path.join(C, 'ftd_index.json')))


FIGI_MINE = os.path.join(C, 'figi_extra.json')


def load_figi():
    f = dict(B.load_figi())                 # 共有のキャッシュ（読むだけ）
    if os.path.exists(FIGI_MINE):
        f.update(json.load(open(FIGI_MINE)))
    return f


def figi_map(cs):
    """OpenFIGI（鍵なし: 1分25回・1回10件）→ 自分のキャッシュ figi_extra.json（mw_best_ideas_13f.figi_map と同じ読み方）"""
    have = json.load(open(FIGI_MINE)) if os.path.exists(FIGI_MINE) else {}
    known = B.load_figi()
    todo = [cu for cu in sorted(cs) if cu not in have and cu not in known]
    print('OpenFIGI: 未取得', len(todo), '件', flush=True)
    for i in range(0, len(todo), 10):
        batch = todo[i:i + 10]
        body = json.dumps([{'idType': 'ID_CUSIP', 'idValue': cu} for cu in batch]).encode()
        res = None
        for k in range(6):
            try:
                req = urllib.request.Request('https://api.openfigi.com/v3/mapping', data=body,
                                             headers={'Content-Type': 'application/json'})
                res = json.loads(urllib.request.urlopen(req, timeout=60).read())
                break
            except urllib.error.HTTPError as e:
                time.sleep(15 if e.code == 429 else 5 * (k + 1))
            except Exception:  # noqa
                time.sleep(5 * (k + 1))
        if res is None:
            print('  OpenFIGI 失敗', batch[0]); continue
        for cu, r in zip(batch, res):
            data = r.get('data') or []
            us = [x for x in data if x.get('exchCode') == 'US'] or data
            if us:
                x = us[0]
                have[cu] = {k2: x.get(k2) for k2 in ('ticker', 'name', 'securityType', 'securityType2', 'marketSector', 'exchCode')}
            else:
                have[cu] = {'none': r.get('warning') or r.get('error') or 'no data'}
        if (i // 10) % 30 == 0:
            json.dump(have, open(FIGI_MINE, 'w')); print('  OpenFIGI', i + len(batch), '/', len(todo), flush=True)
        time.sleep(2.45)
    json.dump(have, open(FIGI_MINE, 'w'))
    return load_figi()


# 名前を変えた会社（古い記号 → Yahoo が履歴を続けている今の記号）。照合は他と同じ『当時の終値 ±15%』で行い、
# 合わなければ使わない（結果を見る前・照合できなかった CUSIP の比重の大きい順に見て作った一覧）
ALIAS = {
    'PCLN': ['BKNG'], 'VRX': ['BHC'], 'BAM': ['BN'], 'UTX': ['RTX'], 'ETE': ['ET'], 'LB': ['BBWI'], 'LTD': ['BBWI'],
    'DPS': ['KDP'], 'NYCB': ['FLG'], 'CFX': ['ENOV'], 'HHC': ['HHH'], 'FLT': ['CPAY'], 'DISCK': ['WBD'],
    'DISCA': ['WBD'], 'COG': ['CTRA'], 'RDSA': ['SHEL'], 'RDSB': ['SHEL'], 'RDS/A': ['SHEL'], 'RDS/B': ['SHEL'],
    'MYL': ['VTRS'], 'DWDP': ['DD'], 'BBT': ['TFC'], 'MHFI': ['SPGI'], 'MHP': ['SPGI'], 'ANTM': ['ELV'],
    'FB': ['META'], 'IR': ['TT'], 'FCAU': ['STLA'], 'YNDX': ['NBIS'], 'CTL': ['LUMN'], 'SYMC': ['GEN'],
    'NLOK': ['GEN'], 'ABC': ['COR'], 'FISV': ['FI', 'FISV'], 'HCP': ['DOC'], 'PEAK': ['DOC'], 'WLTW': ['WTW'],
    'WSH': ['WTW'], 'GPS': ['GAP'], 'KORS': ['CPRI'], 'COH': ['TPR'], 'DLPH': ['APTV'], 'JEC': ['J'], 'ADS': ['BFH'],
    'PAH': ['ESI'], 'ECA': ['OVV'], 'LUK': ['JEF'], 'CMCSK': ['CMCSA'], 'THRX': ['INVA'], 'XON': ['PGEN'],
    'RLGY': ['HOUS'], 'QRTEA': ['QVCGA'], 'QVCA': ['QVCGA'], 'CBS': ['PARA'], 'VIAB': ['PARA'], 'VIAC': ['PARA'],
    'HRS': ['LHX'], 'WYN': ['WH', 'TNL'], 'BHI': ['BKR'], 'BHGE': ['BKR'], 'LMCA': ['FWONA'], 'LMCK': ['FWONK'],
}


def refetch_short(syms):
    """共有キャッシュの短いファイル（月が24未満）を自分のキャッシュへ全期間で取り直す"""
    os.makedirs(YHD_MINE, exist_ok=True)
    out = Counter()
    for sym in syms:
        mine = os.path.join(YHD_MINE, sym.replace('/', '_') + '.json')
        if os.path.exists(mine):
            out['already'] += 1; continue
        u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?period1=0&period2={int(time.time())}'
             f'&interval=1mo&events=div%2Csplit')
        for i in range(4):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
                open(mine + '.tmp', 'wb').write(b); os.replace(mine + '.tmp', mine)
                out['ok'] += 1; break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    open(mine, 'w').write('{"http":404}'); out['404'] += 1; break
                time.sleep(3 * (i + 1))
            except Exception:  # noqa
                time.sleep(2 * (i + 1))
        time.sleep(0.25)
        B._yh.pop(sym, None)
    return out


def short_cached(syms):
    bad = []
    for s_ in syms:
        p0 = _yh_path_orig(s_)
        mine = os.path.join(YHD_MINE, s_.replace('/', '_') + '.json')
        if os.path.exists(mine) or not os.path.exists(p0):
            continue
        try:
            j = json.load(open(p0))
            r = (j.get('chart') or {}).get('result')
            if r and len(r[0].get('timestamp') or []) < 24:
                bad.append(s_)
        except Exception:  # noqa
            pass
    return bad


def collect():
    """全提出を読む → filings（運用者の提出ごとに株だけの行・単位）と tasks（(CUSIP, 期間) → 照合の株価）"""
    man = load_filings()
    cs = set()
    raw = {}
    for x in man:
        f = json.load(open(os.path.join(FILD, x['acc'] + '.json')))
        rows, drop = clean_rows(f)
        raw[x['acc']] = (f, rows, drop)
        cs.update(rows)
    return man, raw, cs


def do_map():
    man, raw, cs = collect()
    print('提出', len(man), '・CUSIP', len(cs), flush=True)
    pth = os.path.join(C, 'ftd_index.json')
    ftd = load_ftd() if os.path.exists(pth) else build_ftd(cs)
    figi = load_figi()
    tasks, wsum, units = {}, defaultdict(float), {}
    for x in man:
        f, rows, drop = raw[x['acc']]
        if not rows:
            continue
        p = per_ym(x['period'])
        mult, how, med = unit_mult(rows, p, x['filed'], ftd)
        units[x['acc']] = [mult, how, med]
        refs = ref_prices(p)
        tot = sum(v for v, _, _, _ in rows.values())
        for cu, (v, sh, _, _) in rows.items():
            r = refs.get(cu)
            ref = r[0] if r and r[0] > 0 else v * mult / sh
            k = (cu, p)
            if k not in tasks or (r and r[0] > 0):
                tasks[k] = ref
            wsum[k] += v / tot
    json.dump(units, open(os.path.join(C, 'units.json'), 'w'))
    print('単位', Counter(u[1] for u in units.values()), Counter(u[0] for u in units.values()), flush=True)
    rp = os.path.join(C, 'resolved.json')
    done = {}
    if os.path.exists(rp):
        done = {(k.split('|')[0], int(k.split('|')[1])): v for k, v in json.load(open(rp)).items()}
    # R2b が同じ道具（B.resolve・同じ ±15%）で照合した 12月末の組を種にする
    r2b = os.path.join(R2B, 'resolved.json')
    if os.path.exists(r2b):
        for k, v in json.load(open(r2b)).items():
            cu, p = k.split('|'); kk = (cu, int(p))
            if kk in tasks and v and not done.get(kk):
                done[kk] = v
    todo = {k: v for k, v in tasks.items() if not done.get(k)}
    print('(CUSIP, 期間)', len(tasks), '・照合済み', sum(1 for k in tasks if done.get(k)), '・残り', len(todo), flush=True)
    # 共有キャッシュの短いファイルを取り直す（候補の記号の全部で調べる）
    cands = set()
    for (cu, p) in tasks:
        cands.update(B.candidates_for(cu, p, ftd, figi))
    for v in done.values():
        if v:
            cands.add(v)
    bad = short_cached(cands)
    print('短いキャッシュを取り直す', len(bad), dict(refetch_short(bad)), flush=True)
    # 短いファイルで照合した組は照合し直す（記号はそのままでも株価の確かめをやり直す）
    for k in [k for k, v in done.items() if v in set(bad)]:
        done.pop(k, None)
    todo = {k: v for k, v in tasks.items() if not done.get(k)}
    res = B.resolve(todo, None, ftd, figi, fetch=True, threads=6)
    done.update({k: v for k, v in res.items() if v})
    # 同じ CUSIP の別の期間に照合できた記号を候補にもう一度（当時の株価 ±15% で照合し直す）
    for rd in range(2):
        bycu = defaultdict(list)
        for (cu, p), v in done.items():
            if v:
                bycu[cu].append((p, v))
        left = {k: v for k, v in tasks.items() if not done.get(k) and k[0] in bycu}
        if not left:
            break
        hit = 0
        for (cu, p), ref in left.items():
            for _, s_ in sorted(bycu[cu], key=lambda t: abs(mdiff(t[0], p))):
                y = B.yh_load(s_)
                rc = B.raw_close(y, p) if y else None
                if rc and ref and abs(rc / ref - 1) <= B.PX_TOL:
                    done[(cu, p)] = s_; hit += 1; break
        print('  隣の期間の記号で照合', hit, '/', len(left), flush=True)
    json.dump({f'{k[0]}|{k[1]}': v for k, v in done.items()}, open(rp, 'w'))
    # 名前を変えた会社の今の記号（ALIAS）で照合
    left = {k: v for k, v in tasks.items() if not done.get(k)}
    al = defaultdict(list)
    for (cu, p), ref in left.items():
        syms, _ = B.ftd_symbols(ftd, cu, p)
        t_ = (figi.get(cu) or {}).get('ticker')
        for s0 in syms[:4] + ([t_] if t_ else []):
            for s1 in ALIAS.get(s0.replace('-', '').upper(), []) + ALIAS.get(s0.upper(), []):
                if s1 not in al[(cu, p)]:
                    al[(cu, p)].append(s1)
    need = sorted({s1 for v in al.values() for s1 in v if not os.path.exists(B.yh_path(s1))})
    for s1 in need:
        B.yh_fetch(s1)
    hit = Counter()
    for k, ss in al.items():
        for s1 in ss:
            y = B.yh_load(s1)
            rc = B.raw_close(y, k[1]) if y else None
            if rc and left[k] and abs(rc / left[k] - 1) <= B.PX_TOL:
                done[k] = s1; hit[s1] += 1; break
    print('ALIAS で照合', sum(hit.values()), '/', len(al), dict(hit.most_common(30)), flush=True)
    json.dump({f'{k[0]}|{k[1]}': v for k, v in done.items()}, open(rp, 'w'))
    # OpenFIGI（比重の大きい順）
    wcu = defaultdict(float)
    for (cu, p), w in wsum.items():
        if not done.get((cu, p)):
            wcu[cu] += w
    left = sorted(wcu, key=lambda c: -wcu[c])
    left = [cu for cu in left if cu not in figi]
    print('OpenFIGI へ', len(left), flush=True)
    if '--no-figi' not in sys.argv and left:
        figi = figi_map(set(left[:int(os.environ.get('FIGI_N', '4000'))]))
        todo = {k: v for k, v in tasks.items() if not done.get(k) and (figi.get(k[0]) or {}).get('ticker')}
        print('照合（OpenFIGI の記号）', len(todo), flush=True)
        B._ftd_memo.clear()
        res = B.resolve(todo, None, ftd, figi, fetch=True, threads=6)
        done.update({k: v for k, v in res.items() if v})
        json.dump({f'{k[0]}|{k[1]}': v for k, v in done.items()}, open(rp, 'w'))
    ok = sum(1 for k in tasks if done.get(k))
    wt = sum(wsum.values()); wok = sum(w for k, w in wsum.items() if done.get(k))
    print('照合できた', ok, '/', len(tasks), f'・比重で {wok / wt:.3f}', flush=True)


# ───────────────────────── 段4: 計算 ─────────────────────────
def load_resolved():
    j = json.load(open(os.path.join(C, 'resolved.json')))
    return {(k.split('|')[0], int(k.split('|')[1])): v for k, v in j.items()}


def norm_name(n):
    n = re.sub(r'[^A-Z0-9 ]', ' ', (n or '').upper())
    return re.sub(r'\s+', ' ', n).strip()


class Book:
    """運用者ごとの提出と、ある月に効いている保有（会社ごとにまとめた価額・記号）"""

    def __init__(self):
        man = load_filings()
        units = json.load(open(os.path.join(C, 'units.json')))
        self.res = load_resolved()
        figi, ftd = load_figi(), load_ftd()
        self.nonstock = {}

        def nonstock(cu):
            if cu not in self.nonstock:
                self.nonstock[cu] = B.is_nonstock(cu, figi, B.ftd_symbols(ftd, cu, 202001)[1], None)
            return self.nonstock[cu]
        only = os.environ.get('E_ONLY')
        if only:
            man = [x for x in man if x['code'] in only.split(',')]
        self.info = {c['code']: c for c in managers()}
        self.F = defaultdict(list)          # code → [filing]
        self.notes = Counter()
        for x in man:
            f = json.load(open(os.path.join(FILD, x['acc'] + '.json')))
            rows, drop = clean_rows(f, nonstock)
            p = per_ym(x['period'])
            mult = units.get(x['acc'], [1000 if int(x['filed'].replace('-', '')) < DOLLAR_FROM else 1])[0]
            if x['form'] == '13F-HR':
                kind = 'orig'
            else:
                at = ((f.get('primary') or {}).get('amendmentType') or '').upper().strip()
                kind = 'RESTATEMENT' if at.startswith('RESTATE') else ('NEW HOLDINGS' if at.startswith('NEW') else 'unknown:' + at)
            if f.get('error'):
                self.notes['filing_error'] += 1
            tot_raw = sum(v for v, _, _, _ in rows.values())
            self.F[x['code']].append({'period': p, 'acc': x['acc'], 'cik': x['cik'], 'form': x['form'], 'kind': kind,
                                      'filed': x['filed'], 'eff': eff_month(x['filed']), 'mult': mult,
                                      'pos': {cu: v * mult for cu, (v, sh, _, _) in rows.items()},
                                      'nm': {cu: r[2] for cu, r in rows.items()},
                                      'drop_usd': {k: v * mult for k, v in drop.items() if k.endswith('value')},
                                      'stock_usd': tot_raw * mult, 'error': f.get('error'),
                                      'url': f.get('infotable_url')})
        for code in self.F:
            self.F[code].sort(key=lambda r: (r['eff'], r['filed'], r['acc']))
        self._act = {}
        self._keys = {}

    def active(self, code, m):
        """月 m に効いている提出 → (署名, 期間, {cusip: 価額$}) or None。
        原本の中で m までに効く最新の期間 P（報告期間の末から STALE_MONTHS 以内）。P の訂正のうち m までに効くもの:
        RESTATEMENT は最後のものが置き換え、NEW HOLDINGS は足す。P より古い期間への訂正は使わない"""
        k = (code, m)
        if k in self._act:
            return self._act[k]
        fl = [r for r in self.F.get(code, []) if r['eff'] <= m]
        orig = [r for r in fl if r['kind'] == 'orig']
        out = None
        if orig:
            P = max(r['period'] for r in orig)
            if mdiff(m, P) <= STALE_MONTHS:
                o = max((r for r in orig if r['period'] == P), key=lambda r: (r['filed'], r['acc']))
                rs = [r for r in fl if r['period'] == P and r['kind'] == 'RESTATEMENT' and r['filed'] >= o['filed']]
                base = max(rs, key=lambda r: (r['filed'], r['acc'])) if rs else o
                pos = dict(base['pos'])
                used = [base['acc']]
                for r in fl:
                    if r['period'] == P and r['kind'] == 'NEW HOLDINGS' and r['filed'] >= base['filed']:
                        for cu, v in r['pos'].items():
                            pos[cu] = pos.get(cu, 0.0) + v
                        used.append(r['acc'])
                out = ((code, P, tuple(used)), P, pos)
        self._act[k] = out
        return out

    def keyed(self, sig, P, pos):
        """{cusip: 価額} → 会社ごと {key: [価額, 代表の記号, 代表の CUSIP]}（同じ会社の別の種類株は Yahoo の会社名でまとめる）"""
        if sig in self._keys:
            return self._keys[sig]
        g = {}
        for cu, v in pos.items():
            sym = self.res.get((cu, P))
            if sym:
                y = B.yh_load(sym)
                nm = norm_name(y['name']) if y and y.get('name') else None
                key = 'N:' + nm if nm else 'S:' + sym
            else:
                key = 'C:' + cu
            e = g.setdefault(key, [0.0, None, None, -1.0])
            e[0] += v
            if v > e[3]:
                e[1], e[2], e[3] = sym, cu, v
        out = {k: (e[0], e[1], e[2]) for k, e in g.items()}
        self._keys[sig] = out
        return out

    def holdings(self, code, m):
        a = self.active(code, m)
        if not a:
            return None
        sig, P, pos = a
        return sig, P, self.keyed(sig, P, pos)


KEEP_SPIKE = False                      # 感度だけ: True なら『月 +300% 超＝データの誤り』の切り（B.SPIKE）を使わない（2026-10-12 検証役の指摘）


def yret(y):
    """記号の月次リターン。既定は B.yh_load の ret（+300% 超の月から先は未観測）。
    KEEP_SPIKE のときは adj の連続した月からすべて作る（GME 2021-01 のような本物の急騰も、データの誤りも残る）"""
    if not KEEP_SPIKE or not y.get('spike'):
        return y['ret']
    if '_ret_full' not in y:
        ks = sorted(k for k in y['adj'] if k >= B.RET_FROM)
        y['_ret_full'] = {k: y['adj'][k] / y['adj'][a0] - 1 for a0, k in zip(ks, ks[1:]) if B.madd(a0, 1) == k}
    return y['_ret_full']


def sym_status(sym, f):
    """組む月 f（その月末に買う）での状態: ok / unmapped（記号なし・その月の値が欠けた）/ gone_before（その前に取引が終わった）"""
    if not sym:
        return 'unmapped', None
    y = B.yh_load(sym)
    if y is None:
        return 'unmapped', None
    if y['adj'].get(f) is None or (y['spike'] and y['spike'] <= f and not KEEP_SPIKE):
        later = [k for k in y['adj'] if f < k <= B.madd(f, 3)]
        return ('unmapped', None) if later else ('gone_before', None)
    return 'ok', y


def simulate(target_fn, months, L, fill=None):
    """target_fn(m) → (署名, {key: (比重, 記号)}) or None。署名が変わった月の初め（前の月末）に目標へ入れ替える。
    L=None, fill=None → O（観測できる分で按分・欠けた株は外して按分し直す＝『価格の取れない株は残りの株と同じ成績』と置く版）
    L=None, fill={m: r} → N（中立の置き方・2026-10-12 検証役の指摘で追加）: 価格の取れない株（記号なし・その月の値が欠けた）も
            比重どおり持ち、その月のリターンに fill[m]（主は SPY の配当込みの月次）を置く。上限でも下限でもない『市場並み』の仮定
    L=数値 → P30: 価格が欠けた株は『最初の欠けた月』に L（−30%）、以後はその株の値は動かない（0%）。
            同じ株を目標に持ち続ける間は二度目の −30% を掛けない（四半期ごとに買い直すたびに −30% を重ねない）。
            目標から外れたら売り（その値で）、後でまた入って価格が無ければ新しい −30%。＝悲観の下限（結果ではなく置き方で決まる）
    → {'gross': {m: r}, 'net': {m: r}, 'turn': [(m, 片道の回転)], 'cover': [...], 'n': {m: 銘柄数}, 'hits': 回数}"""
    if fill is not None and L is None:
        return _simulate_fill(target_fn, months, fill)
    v = {}
    dead = set()
    st = {}
    last_sig = None
    gross, net, turns, cover, nmap = {}, {}, [], [], {}
    hits = 0
    for m in months:
        t = target_fn(m)
        cost = 0.0
        if t is None:                   # 効いている提出が無い（提出が止まった）→ 写しはそこで止まる（次の提出から再開）
            v, dead, last_sig = {}, set(), None
            continue
        sig, W = t
        if sig != last_sig:
            f = B.madd(m, -1)
            st = {k: sym_status(sym, f) for k, (w, sym) in W.items()}
            live = {k: w for k, (w, _) in W.items() if st[k][0] != 'gone_before' and w > 0}
            tl = sum(live.values())
            nw = {k: w for k, w in live.items() if st[k][0] == 'ok'} if L is None else dict(live)
            tn = sum(nw.values())
            last_sig = sig
            if tn <= 0 or tl <= 0:
                v, dead = {}, set()
                continue
            nw = {k: w / tn for k, w in nw.items()}
            wall = sum(w for w, _ in W.values())
            cover.append({'m': m, 'n': len(W), 'n_ok': sum(1 for k in W if st[k][0] == 'ok'),
                          'w_unmapped': round(sum(w for k, w in live.items() if st[k][0] == 'unmapped') / tl, 4),
                          'w_gone_before': round(sum(w for k, (w, _) in W.items() if st[k][0] == 'gone_before') / wall, 4) if wall > 0 else None})
            V = sum(v.values())
            if V > 0:
                keys = set(v) | set(nw)
                tv = 0.5 * sum(abs(nw.get(k, 0.0) - v.get(k, 0.0) / V) for k in keys)
                turns.append((m, tv))
                cost = COST_ONEWAY * tv
            else:
                V = 1.0
            # P30: 持ち続けている『すでに −30% を受けた株』は続けて 0%。価格が戻った株は通常へ
            dead = {k for k in dead if k in nw and k in v and st[k][0] != 'ok'} if L is not None else set()
            v = {k: w * V for k, w in nw.items()}
        V0 = sum(v.values())
        if V0 <= 0:
            continue
        if L is None:
            obs = {k: yret(st[k][1])[m] for k in v if st.get(k, ('', None))[0] == 'ok' and m in yret(st[k][1])}
            base = sum(v[k] for k in obs)
            if base <= 0:
                v = {}
                continue
            R = sum(v[k] * r for k, r in obs.items()) / base
            newv = {k: v[k] * (1 + obs[k]) for k in obs}
            sc = V0 * (1 + R) / sum(newv.values()) if sum(newv.values()) > 0 else 0.0
            v = {k: x * sc for k, x in newv.items()}
        else:
            newv = {}
            for k, x in v.items():
                if k in dead:
                    newv[k] = x; continue
                r = yret(st[k][1]).get(m) if st.get(k, ('', None))[0] == 'ok' else None
                if r is None:
                    newv[k] = x * (1 + L); dead.add(k); hits += 1
                else:
                    newv[k] = x * (1 + r)
            v = newv
            R = sum(v.values()) / V0 - 1
        gross[m] = R
        net[m] = (1 - cost) * (1 + R) - 1
        nmap[m] = len(v) - len(dead)
    return {'gross': gross, 'net': net, 'turn': turns, 'cover': cover, 'n': nmap, 'hits': hits}


def _simulate_fill(target_fn, months, fill):
    """N（中立）: 入れ替えと回転・費用・組む前に終わった株の扱いは O・P30 と同じ。違いは、価格の取れない株を外さず比重どおり持ち、
    その月のリターンが観測できなければ fill[m] を置くことだけ（持ち続ける間、毎月 fill。−30% のような一度きりの罰は無い）。
    hits＝fill を置いた（株・月）の数"""
    v, st, last_sig = {}, {}, None
    gross, net, turns, cover, nmap = {}, {}, [], [], {}
    hits = 0
    for m in months:
        t = target_fn(m)
        cost = 0.0
        if t is None:
            v, last_sig = {}, None
            continue
        sig, W = t
        if sig != last_sig:
            f = B.madd(m, -1)
            st = {k: sym_status(sym, f) for k, (w, sym) in W.items()}
            live = {k: w for k, (w, _) in W.items() if st[k][0] != 'gone_before' and w > 0}
            tl = sum(live.values())
            last_sig = sig
            if tl <= 0:
                v = {}
                continue
            nw = {k: w / tl for k, w in live.items()}
            wall = sum(w for w, _ in W.values())
            cover.append({'m': m, 'n': len(W), 'n_ok': sum(1 for k in W if st[k][0] == 'ok'),
                          'w_unmapped': round(sum(w for k, w in live.items() if st[k][0] == 'unmapped') / tl, 4),
                          'w_gone_before': round(sum(w for k, (w, _) in W.items() if st[k][0] == 'gone_before') / wall, 4) if wall > 0 else None})
            V = sum(v.values())
            if V > 0:
                keys = set(v) | set(nw)
                tv = 0.5 * sum(abs(nw.get(k, 0.0) - v.get(k, 0.0) / V) for k in keys)
                turns.append((m, tv))
                cost = COST_ONEWAY * tv
            else:
                V = 1.0
            v = {k: w * V for k, w in nw.items()}
        V0 = sum(v.values())
        if V0 <= 0:
            continue
        fm = fill.get(m)
        if fm is None:
            raise RuntimeError(f'fill に {m} が無い（中立の置き方の相手の系列が欠けた）')
        newv = {}
        for k, x in v.items():
            r = yret(st[k][1]).get(m) if st.get(k, ('', None))[0] == 'ok' else None
            if r is None:
                r = fm; hits += 1
            newv[k] = x * (1 + r)
        v = newv
        R = sum(v.values()) / V0 - 1
        gross[m] = R
        net[m] = (1 - cost) * (1 + R) - 1
        nmap[m] = len(v)
    return {'gross': gross, 'net': net, 'turn': turns, 'cover': cover, 'n': nmap, 'hits': hits}


def months_all(a=START, z=END):
    return B.months(a, z)


def topn(keyed, n):
    xs = sorted(keyed.items(), key=lambda kv: -kv[1][0])[:n]
    tot = sum(x[1][0] for x in xs)
    return {k: (e[0] / tot, e[1]) for k, e in xs} if tot > 0 else {}


def mgr_target(bk, code):
    def f(m):
        h = bk.holdings(code, m)
        if not h:
            return None
        sig, P, kd = h
        tot = sum(e[0] for e in kd.values())
        if tot <= 0:
            return None
        return sig, {k: (e[0] / tot, e[1]) for k, e in kd.items()}
    return f


def e1_target(bk, codes):
    def f(m):
        hs = [(c, bk.holdings(c, m)) for c in codes]
        hs = [(c, h) for c, h in hs if h]
        if not hs:
            return None
        W, syms = defaultdict(float), {}
        for c, (sig, P, kd) in hs:
            for k, (w, sym) in topn(kd, TOP_E1).items():
                W[k] += w / len(hs)
                syms.setdefault(k, sym)
        return tuple(sorted(h[0] for _, h in hs)), {k: (w, syms[k]) for k, w in W.items()}
    return f


def e2_target(bk, codes):
    def f(m):
        hs = [(c, bk.holdings(c, m)) for c in codes]
        hs = [(c, h) for c, h in hs if h]
        if not hs:
            return None
        cnt, syms, val = Counter(), {}, defaultdict(float)
        for c, (sig, P, kd) in hs:
            for k, e in kd.items():
                cnt[k] += 1; val[k] += e[0]
                if k not in syms or e[1]:
                    syms[k] = syms.get(k) or e[1]
        ks = [k for k, n in cnt.items() if n >= MIN_E2]
        if not ks:
            return None
        return tuple(sorted(h[0] for _, h in hs)), {k: (1 / len(ks), syms[k]) for k in ks}
    return f


def e3_target(bk, sel_by_year, mode='union'):
    """sel_by_year: {保有の年: [運用者コード]}。mode='union' は10人の上位10銘柄の和集合を等しく（主）、
    'slot' は人ごとに等しく・各人の上位10を等しく（感度）"""
    def f(m):
        codes = sel_by_year.get(m // 100)
        if not codes:
            return None
        hs = [(c, bk.holdings(c, m)) for c in codes]
        hs = [(c, h) for c, h in hs if h]
        if not hs:
            return None
        W, syms = defaultdict(float), {}
        for c, (sig, P, kd) in hs:
            tp = topn(kd, TOP_E3_STK)
            for k, (w, sym) in tp.items():
                W[k] += (1 / len(tp)) / len(hs) if mode == 'slot' else 1.0
                syms.setdefault(k, sym)
        if mode == 'union':
            W = {k: 1 / len(W) for k in W}
        return (m // 100, tuple(sorted(h[0] for _, h in hs))), {k: (w, syms[k]) for k, w in W.items()}
    return f


def cum(series, ms):
    g = 1.0
    for m in ms:
        g *= 1 + series[m]
    return g - 1


def select_e3(copies, version='O', first=E3_FIRST_SEL, last=2025, top=True, n=TOP_E3_MGR):
    """毎年末 Y に、その時点までの過去3年（START より前は無い＝2015年末は 2013-09〜2015-12 の28か月）の写しの成績で選ぶ"""
    sel, detail = {}, {}
    for Y in range(first, last + 1):
        a = max(START, (Y - 2) * 100 + 1)
        ms = B.months(a, Y * 100 + 12)
        sc = {}
        for c, d in copies.items():
            s_ = d[version]['gross']
            if all(m in s_ for m in ms):
                sc[c] = cum(s_, ms)
        order = sorted(sc, key=lambda c: (-sc[c], c) if top else (sc[c], c))
        sel[Y + 1] = order[:n]
        detail[Y] = {'window': [ms[0], ms[-1]], 'months': len(ms), 'eligible': len(sc),
                     'picked': [[c, round(sc[c] * 100, 1)] for c in order[:n]]}
    return sel, detail, None


def spearman(a, b):
    def rk(x):
        idx = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and x[idx[j + 1]] == x[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    return M.corr(rk(a), rk(b)) if len(a) >= 10 else None


def stats_vs(s, benches, facs_pack, a=None, z=None):
    ff, facs = facs_pack
    ss = {k: v for k, v in s.items() if (a is None or k >= a) and (z is None or k <= z)}
    out = {'from': min(ss) if ss else None, 'to': max(ss) if ss else None, 'months': len(ss),
           'cagr': round(M.cagr(ss) * 100, 2) if ss else None,
           'vol': round(S.stdev(ss.values()) * math.sqrt(12) * 100, 1) if len(ss) > 2 else None,
           'max_dd': round(M.maxdd(ss) * 100, 1) if ss else None}
    for bn, b in benches.items():
        e = M.excess_stats(ss, b)
        if e:
            e['max_dd_bench_same_window'] = round(M.maxdd({k: b[k] for k in ss if k in b}) * 100, 1)
        out['vs_' + bn] = e
    out['ff5_umd_alpha'] = B.factor_alpha(ss, ff['rf'], facs) if len(ss) >= 36 else None
    return out


HALVES = [(201601, 202012), (202101, END)]


def report(name, desc, sim, benches, fp, a=None):
    out = {'name': name, 'description': desc}
    for ver in VERS:
        r = sim[ver]
        net = {k: v for k, v in r['net'].items() if a is None or k >= a}
        gross = {k: v for k, v in r['gross'].items() if a is None or k >= a}
        yrs = len(net) / 12 if net else None
        tv = [t for m, t in r['turn'] if a is None or m >= a]
        d = {'net': stats_vs(net, benches, fp), 'gross_cagr': round(M.cagr(gross) * 100, 2) if gross else None,
             'turnover_oneway_annual': round(sum(tv) / yrs, 2) if yrs else None,
             'rebalances': len(tv),
             'avg_positions': round(S.mean(r['n'][m] for m in net), 1) if net else None,
             'avg_w_unmapped': round(S.mean(c['w_unmapped'] for c in r['cover'] if a is None or c['m'] >= a), 4) if r['cover'] else None,
             'halves': {f'{h0}-{h1}': stats_vs(net, benches, fp, h0, h1) for h0, h1 in HALVES}}
        out[ver] = d
    return out


def judge(rep):
    """事前登録の pass_bar: E3 が SPY に 費用後 +1%/年以上・Newey-West t≥2.0・前半（2016-2020）と後半（2021-2026）の両方で正"""
    res = {}
    for ver in VERS:
        d = rep[ver]
        f = d['net']['vs_spy'] or {}
        h = [d['halves'][k]['vs_spy'] or {} for k in d['halves']]
        c1 = (f.get('ex_ann') or -9) >= 1.0
        c2 = (f.get('t') or -9) >= 2.0
        c3 = all((x.get('ex_ann') or -9) > 0 for x in h)
        res[ver] = {'ex_ge_1pct': c1, 't_ge_2': c2, 'both_halves_positive': c3, 'pass': c1 and c2 and c3,
                    'ex_ann': f.get('ex_ann'), 't': f.get('t'), 'cagr_diff': f.get('cagr_diff'),
                    'halves_ex_ann': [x.get('ex_ann') for x in h]}
    res['pass_both_bounds'] = res['O']['pass'] and res['P30']['pass']
    res['pass_any_version'] = any(res[v]['pass'] for v in VERS)
    res['note'] = ('O＝価格の取れない株は残りの株と同じ成績と置く版（上限ではない）・N＝市場並み（SPY）と置く中立の版・'
                   'P30＝悲観の下限（作り方から決まる下限で、負けの証拠ではない）。合否はどの版でも同じ')
    return res


def series_out(d):
    return {str(k): round(v, 6) for k, v in sorted(d.items())}


def spy_fill(spy, plus_ann=0.0):
    return {k: (1 + r) * (1 + plus_ann) ** (1 / 12) - 1 for k, r in spy.items()}


def run_vers(target_fn, ms, fill):
    return {'O': simulate(target_fn, ms, None), 'N': simulate(target_fn, ms, None, fill),
            'P30': simulate(target_fn, ms, MISS_P30)}


def calc():
    t0 = time.time()
    bk = Book()
    codes = sorted(bk.F)
    ms = months_all()
    print('運用者', len(codes), '・月', ms[0], '〜', ms[-1], flush=True)
    ff, facs = B.load_factors()
    fp = (ff, facs)
    spy, qqq = M.yahoo('SPY'), M.yahoo('QQQ')
    mkt = ff['mkt']
    win = lambda d: {k: v for k, v in d.items() if START <= k <= END}
    benches = {'spy': win(spy), 'qqq': win(qqq), 'french_mkt': win(mkt)}
    fillN = spy_fill(benches['spy'])
    # 各運用者の写し
    copies = {}
    for c in codes:
        copies[c] = run_vers(mgr_target(bk, c), ms, fillN)
    print('写し', len(copies), f'{time.time() - t0:.0f}s', flush=True)
    sims = {
        'E1': run_vers(e1_target(bk, codes), ms, fillN),
        'E2': run_vers(e2_target(bk, codes), ms, fillN),
    }
    print('E1 E2', f'{time.time() - t0:.0f}s', flush=True)
    selT, detT, _ = select_e3(copies, 'O', top=True)
    selB, detB, _ = select_e3(copies, 'O', top=False)
    selTp, detTp, _ = select_e3(copies, 'P30', top=True)
    sel17, det17, _ = select_e3(copies, 'O', first=2016, top=True)
    selTn, detTn, _ = select_e3(copies, 'N', top=True)      # 感度: 写しの成績も中立の N で順位づけ（2026-10-12・検証役の作り直しと同じ形）
    ms3 = B.months(201601, END)
    ms17 = B.months(201701, END)
    sims['E3'] = run_vers(e3_target(bk, selT), ms3, fillN)
    sims['E3b'] = run_vers(e3_target(bk, selB), ms3, fillN)
    sens = {
        'E3_slot': run_vers(e3_target(bk, selT, 'slot'), ms3, fillN),
        'E3_rank_by_P30': run_vers(e3_target(bk, selTp), ms3, fillN),
        'E3_from2017_full36m': run_vers(e3_target(bk, {y: v for y, v in sel17.items() if y >= 2017}), ms17, fillN),
        'E3b_slot': run_vers(e3_target(bk, selB, 'slot'), ms3, fillN),
        'E3_rank_by_N': run_vers(e3_target(bk, selTn), ms3, fillN),
    }
    print('E3', f'{time.time() - t0:.0f}s', flush=True)
    # 感度: 価格の取れない株に SPY＋x%/年（選んだ10人は主の E3 と同じ）
    sweep = {x: simulate(e3_target(bk, selT), ms3, None, spy_fill(benches['spy'], x / 100)) for x in FILL_SWEEP}
    sweep_resel = {}
    for x in FILL_SWEEP:                 # 同じ置き方で写しの成績も作り直して10人を選び直す版
        fx = spy_fill(benches['spy'], x / 100)
        cx = {c: {'N': simulate(mgr_target(bk, c), ms, None, fx)} for c in codes}
        sx, _, _ = select_e3(cx, 'N', top=True)
        sweep_resel[x] = simulate(e3_target(bk, sx), ms3, None, fx)
    print('E3 fill sweep', f'{time.time() - t0:.0f}s', flush=True)
    # 感度: 『月 +300% 超＝データの誤り』の切りを使わない（本物の急騰も誤りも残る）。写しを全部作り直し E3 も選び直す
    global KEEP_SPIKE
    KEEP_SPIKE = True
    try:
        copies_ks = {c: {'O': simulate(mgr_target(bk, c), ms, None)} for c in codes}
        selT_ks, _, _ = select_e3(copies_ks, 'O', top=True)
        spike_sens = {'copies': copies_ks,
                      'E1': {'O': simulate(e1_target(bk, codes), ms, None)},
                      'E3_same_selection': run_vers(e3_target(bk, selT), ms3, fillN),
                      'E3_reselected': {'O': simulate(e3_target(bk, selT_ks), ms3, None)},
                      'selection_changed_years': sorted(y for y in selT if set(selT[y]) != set(selT_ks.get(y, [])))}
    finally:
        KEEP_SPIKE = False
    print('spike sens', f'{time.time() - t0:.0f}s', flush=True)
    return (bk, codes, copies, sims, sens, (selT, detT, selB, detB, selTp, detTp, sel17, det17, selTn, detTn), benches, fp, spy, qqq, mkt,
            (sweep, sweep_resel), spike_sens)


def hindsight(copies, benches, fp):
    """後知恵の上限: 各運用者の写しの全期間（費用後）を同じ月の SPY と比べる。★83人の一覧そのものが『今日 Dataroma に載っている＝
    後から見て名の知れた運用者』という後知恵なので、ここの勝ち数は実際に前もって選べた数ではない"""
    rows = []
    for c, d in copies.items():
        r = {'code': c}
        for ver in VERS:
            s_ = d[ver]['net']
            if len(s_) < 24:
                r[ver] = None; continue
            e = M.excess_stats(s_, benches['spy'])
            r[ver] = {'from': min(s_), 'to': max(s_), 'months': len(s_), 'cagr': round(M.cagr(s_) * 100, 2),
                      'spy_cagr_same_months': e['cagr_b'] if e else None, 'cagr_diff_vs_spy': e['cagr_diff'] if e else None,
                      'ex_ann_vs_spy': e['ex_ann'] if e else None, 't_vs_spy': e['t'] if e else None}
        rows.append(r)
    def summ(ver, min_m=0):
        xs = [r[ver] for r in rows if r.get(ver) and r[ver]['months'] >= min_m and r[ver]['cagr_diff_vs_spy'] is not None]
        if not xs:
            return None
        d = sorted(x['cagr_diff_vs_spy'] for x in xs)
        return {'n': len(xs), 'beat_spy_cagr': sum(1 for x in xs if x['cagr_diff_vs_spy'] > 0),
                'beat_spy_t_ge_2': sum(1 for x in xs if (x['t_vs_spy'] or 0) >= 2.0),
                'median_cagr_diff': d[len(d) // 2], 'p10': d[len(d) // 10], 'p90': d[(len(d) * 9) // 10],
                'best': max(xs, key=lambda x: x['cagr_diff_vs_spy'])['cagr_diff_vs_spy']}
    return rows, {f'{ver}_all': summ(ver) for ver in VERS} | {f'{ver}_ge120m': summ(ver, 120) for ver in VERS}


def rank_persistence(copies, version='O'):
    out = []
    for Y in range(E3_FIRST_SEL, 2025):
        a = max(START, (Y - 2) * 100 + 1)
        past = B.months(a, Y * 100 + 12)
        nxt = B.months((Y + 1) * 100 + 1, (Y + 1) * 100 + 12)
        xs, ys = [], []
        for c, d in copies.items():
            s_ = d[version]['gross']
            if all(m in s_ for m in past) and all(m in s_ for m in nxt):
                xs.append(cum(s_, past)); ys.append(cum(s_, nxt))
        rho = spearman(xs, ys)
        if rho is None:
            continue
        order = sorted(range(len(xs)), key=lambda i: -xs[i])
        top = [ys[i] for i in order[:TOP_E3_MGR]]; bot = [ys[i] for i in order[-TOP_E3_MGR:]]
        out.append({'select_year_end': Y, 'next_year': Y + 1, 'n': len(xs), 'spearman': round(rho, 3),
                    'next_year_top10_mean': round(S.mean(top) * 100, 1), 'next_year_bottom10_mean': round(S.mean(bot) * 100, 1),
                    'next_year_all_mean': round(S.mean(ys) * 100, 1)})
    rhos = [r['spearman'] for r in out]
    return {'by_year': out, 'mean_spearman': round(S.mean(rhos), 3) if rhos else None,
            't_simple': round(S.mean(rhos) / (S.stdev(rhos) / math.sqrt(len(rhos))), 2) if len(rhos) > 2 and S.stdev(rhos) > 0 else None,
            'years_positive': sum(1 for x in rhos if x > 0), 'years': len(rhos)}


def current_basket(bk, target_fn, m, n=30):
    t = target_fn(m)
    if not t:
        return None
    sig, W = t
    xs = sorted(W.items(), key=lambda kv: -kv[1][0])
    return {'month': m, 'n': len(W), 'top': [[k.split(':', 1)[1], sym, round(w * 100, 2)] for k, (w, sym) in xs[:n]]}


def notes_ja(o):
    """やさしい日本語のまとめ・事前登録から外れた点・注意（数字は計算の結果から入れる）。
    2026-10-12 検証役の指摘で書き直し: O は上限ではない／中立の N を中心の参考に／P30 は悲観の下限で負けの証拠ではない／
    E3b の物差しを書き分け／割安の向かい風の説明を因子の数字と並べる／+300% の切りの注記"""
    S_ = o['strategies']
    g = lambda k, v, key: (S_[k][v]['net']['vs_spy'] or {}).get(key)
    h = lambda k, v: [x['vs_spy']['ex_ann'] for x in S_[k][v]['halves'].values()]
    hml = lambda k: ((S_[k]['O']['net'].get('ff5_umd_alpha') or {}).get('loadings') or {}).get('hml')
    al = lambda k, v, key: (S_[k][v]['net'].get('ff5_umd_alpha') or {}).get(key)
    hs = o['hindsight_upper_bound']['summary']
    rp = o['rank_persistence_83']
    swb = o['missing_price_fill_sweep_E3']
    sw, swr = swb['by_plus_pct'], swb['by_plus_pct_reselected']
    sw_pass = [x for x, r in sw.items() if r['pass_bar']] + [x + '（選び直し）' for x, r in swr.items() if r['pass_bar']]
    sw_top = max(sw, key=lambda x: float(x)); swr_t2 = [x for x, r in swr.items() if (r['t'] or -9) >= 2.0]
    sg = lambda k, v, key: (o['sensitivity'][k][v]['net']['vs_spy'] or {}).get(key)
    sp = o['spike_rule']; ks = sp['keep_spike_sensitivity']
    real = [r for r in sp['symbols'] if r['sym'] in ('GME', 'AMC', 'MDGL', 'KODK')]
    errs = [r for r in sp['symbols'] if r['sym'] in ('IGTA', 'CHRD', 'AMPY')]
    fm = lambda r: f"{r['sym']} {r['spike_month'] // 100}-{r['spike_month'] % 100:02d}（{r['ret_pct']:+,.0f}%）"
    sym3 = '・'.join(fm(r) for r in real)
    err3 = '・'.join(fm(r) for r in errs)
    sam = next((r for r in ks['copies_most_changed'] if 'Scion' in (r['name'] or '')), ks['copies_most_changed'][0] if ks['copies_most_changed'] else None)
    unm = lambda k: S_[k]['O']['avg_w_unmapped'] * 100
    summary = (
        f"成績の良い投資家83人（Dataroma の一覧）の 13F を、提出の翌月から写して持つ形を 2013-09〜2026-08 で測った。"
        f"価格の取れない株（平均で比重の約1割）の扱いで3つの版を出した: O＝残りの株と同じ成績と置く／N＝市場並み（SPY と同じ）と置く・中立／P30＝−30% と置く悲観の下限。"
        f"①全員の上位20を人ごとに等しく（E1）: 年{S_['E1']['O']['net']['cagr']}%（SPY {g('E1', 'O', 'cagr_b')}%）＝SPY に年{g('E1', 'O', 'ex_ann')}%（t {g('E1', 'O', 't')}）・N で{g('E1', 'N', 'ex_ann')}%（t {g('E1', 'N', 't')}）。"
        f"②5人以上が持つ株を等しく（E2）: SPY に年{g('E2', 'O', 'ex_ann')}%（t {g('E2', 'O', 't')}）・N で{g('E2', 'N', 'ex_ann')}%（t {g('E2', 'N', 't')}）。"
        f"③毎年末に『過去3年の写しの成績』の上位10人を選び、その10人の上位10銘柄を等しく（E3・2016-01〜）: "
        f"中立の N で年{S_['E3']['N']['net']['cagr']}%（SPY {g('E3', 'N', 'cagr_b')}%）＝費用後に SPY に年{g('E3', 'N', 'ex_ann')}%（t {g('E3', 'N', 't')}）・前半 {h('E3', 'N')[0]} / 後半 {h('E3', 'N')[1]}。"
        f"10人の選び方も中立の写しで作り直すと年{sg('E3_rank_by_N', 'N', 'ex_ann')}%（t {sg('E3_rank_by_N', 'N', 't')}）。"
        f"O の版では年{g('E3', 'O', 'ex_ann')}%（t {g('E3', 'O', 't')}）、悲観の下限 P30 では年{g('E3', 'P30', 'ex_ann')}%（作り方から決まる下限で、負けの証拠ではない）。"
        f"価格の取れない株に SPY＋{sw_top}%/年 という極端な置き方をしても、合格線（3つの条件）を満たす版は{'無かった' if not sw_pass else '＋' + '・'.join(sw_pass) + '%/年 だけ'}。"
        f"同じ作り方の下位10人（E3b）は、月ごとの差の平均で SPY に年{g('E3b', 'O', 'ex_ann'):+}%（t {g('E3b', 'O', 't')}・有意でない）・複利の年率では{g('E3b', 'O', 'cagr_diff'):+}pt で、上位を選ぶほうが悪かった。"
        f"過去3年の順位と翌年の順位の相関は平均 {rp['mean_spearman']}（{rp['years_positive']}/{rp['years']} 年で正）＝勝ち続ける人を前もって選べなかった。"
        f"事前登録の合格線（E3 が SPY に費用後 +1%/年以上・t≥2・両半分で正）は O・N・P30 のどれでも満たさない＝『写し』は候補に入れない。"
        f"後知恵の上限: 83人それぞれの写しの全期間で SPY に勝ったのは O で {hs['O_all']['beat_spy_cagr']}/{hs['O_all']['n']} 人・N で {hs['N_all']['beat_spy_cagr']} 人・P30 で {hs['P30_all']['beat_spy_cagr']} 人、"
        f"t≥2 で勝った人は O {hs['O_all']['beat_spy_t_ge_2']}・N {hs['N_all']['beat_spy_t_ge_2']} 人（この83人の一覧自体が今日から見た後知恵）。"
    )
    dev = [
        'E3 の最初の選び（2015年末）は過去3年ではなく 2013-09〜2015-12 の28か月で行った: 13F の XML は 2013Q2 の提出（2013-08）からしか無く、写しは 2013-09 からしか作れないため。'
        '事前登録の前半（2016-2020）を持つのに必要。感度として過去3年がそろう2016年末からの版（E3_from2017_full36m）も出した（同じく不合格）',
        '『その10人の上位10銘柄を等しく』は、10人の上位10銘柄の和集合を銘柄ごとに等しく、と読んだ（主）。人ごとに等しく・各人の上位10を等しく（重なりは足す）は感度 E3_slot',
        '『写しの成績』（E3 の順位づけ）は、その人の 13F の株の全保有を価額の比で持つ O 版の費用前の複利とした（事前登録に定めが無い）。P30 で順位づけた版は感度 E3_rank_by_P30',
        'P30 の −30% は『同じ株を持ち続ける間は1回だけ』とした: 四半期ごとに同じ価格の無い株を買い直すたびに −30% を重ねると1年で −76% になり『最初の欠けた月に −30%』の意味を超えるため（最初に組んだ試しでそうなっていたので結果を見る前に直した）',
        f'提出が止まった運用者を写し続けないよう、報告期間の末から {STALE_MONTHS} か月を過ぎた提出は使わない（事前登録に無い線）',
        '株だけにするために ETF・投信（名前と OpenFIGI の種類）とワラント（題名の W EXP 等）も除いた。同じ会社の別の種類株（GOOG/GOOGL・BRK-A/B 等）は Yahoo の会社名で1銘柄にまとめた',
        '記号の照合に、名前を変えた会社の今の記号の一覧（ALIAS・約60件・例 PCLN→BKNG・MHFI→SPGI・UTX→RTX）を足した（当時の終値 ±15% で確かめたものだけ・845組）。'
        'また共有の Yahoo キャッシュに2〜5か月分しか無い短いファイルが236件あったので自分のキャッシュへ取り直した。どちらも戦略の結果を見る前',
        '合否の『+1%/年』は月次の差の算術平均×12（mw_common.excess_stats の ex_ann）・t は Newey-West（12か月）。O と P30 の両方で満たすときだけ合格とした（事前登録は二本の扱いを定めていない）。'
        '2026-10-12 に中立の N も足した（下）が、合否は O・N・P30 のどれでも不合格で変わらない',
        '★事前登録に無い版 N（中立）を、検証役の指摘を受けて後から足した（2026-10-12・結果を見た後）: 価格の取れない株にその月の SPY の配当込みのリターンを置く。'
        'O を「上限」と書いていた誤りを正すためで、合否の線や選び方（E3 の順位づけは O のまま）は動かしていない。感度として SPY＋5〜50%/年 を置いた版も出した（missing_price_fill_sweep_E3）',
        '『月 +300% 超はデータの誤り』の切り（mw_best_ideas_13f.SPIKE）は主の計算では変えなかった: 本物の急騰（GME 2021-01 など）とデータの誤りを記号ごとに外の出どころで確かめないと分けられないため。'
        '代わりに、切りを使わない版を感度として出した（spike_rule.keep_spike_sensitivity）',
        '費用は入れ替えの月の片道の回転にだけ掛けた（最初に買う費用は掛けない）',
        f'持つ期間の終わりは {END}（French の月次の終わり・mw_best_ideas_13f.yh_load の END）。2026Q2 の提出（2026-08）は期間の外で、今日の姿（baskets_now）にだけ使った',
    ]
    cav = [
        '83人の一覧は今日（2026-10）の Dataroma の Superinvestors＝後から見て名の知れた人たち。それでも写しは SPY に勝てなかったので、結論の向きはこの偏りで甘くなる側（実際に前もって選べた人の集まりなら、もっと悪い見込み）',
        f"Yahoo には上場廃止した株の値が無い。価格の取れない比重は E1 で平均{unm('E1'):.1f}%・E2 {unm('E2'):.1f}%・E3 {unm('E3'):.1f}%。"
        f"★P30（−30%）は悲観の下限だが、O は上限ではない: O は『価格の取れない株は残りの株と同じ成績だった』と置く版にすぎない。"
        f"価格の取れない株の多くは、プレミアムつきで買収された会社（Activision・C.R. Bard・Discover・Pioneer Natural Resources など）か、"
        f"Yahoo の記号の履歴が欠けているだけで今も上場している会社（Liberty Broadband・Energy Transfer など）で、市場並みかそれ以上に動いていれば本当の成績は O より上になる。"
        f"市場並み（SPY と同じ）と置く中立の N では、E3 は SPY に年{g('E3', 'N', 'ex_ann')}%（t {g('E3', 'N', 't')}）・10人の選び方も N の写しで作り直すと年{sg('E3_rank_by_N', 'N', 'ex_ann')}%（t {sg('E3_rank_by_N', 'N', 't')}）"
        f"（検証役が自分の照合で作り直した中立の版 −3.47%・t −1.59 は後者と同じ形）。"
        f"SPY＋5〜{sw_top}%/年 と置く感度（missing_price_fill_sweep_E3）では、10人を主と同じにすると＋{sw_top}%/年 でも年{sw[sw_top]['ex_ann_vs_spy']}%（t {sw[sw_top]['t']}）。"
        + (f"10人も選び直すと＋{'・'.join(swr_t2)}%/年 で t は {'・'.join(str(swr[x]['t']) for x in swr_t2)} に届くが、後半（2021〜）が年{'・'.join(str(swr[x]['halves_ex_ann'][1]) for x in swr_t2)}% で両半分の条件を満たさない。" if swr_t2 else '')
        + f"合格線を満たす置き方は{'無かった' if not sw_pass else '＋' + '・'.join(sw_pass) + '%/年'}",
        'Yahoo の履歴が 2026-07-17 から始まり直していた記号が32あり（EA・AVB・EQR・ET・LBRDK・DDS・WBS など）、それより前は価格が無い扱いになった（O では外して按分・N では SPY・P30 では −30%）',
        f"『月 +300% 超はデータの誤り』の切り（mw_best_ideas_13f.SPIKE）で、83人が持った記号 {sp['held_symbols_total']} 個のうち {sp['held_symbols_cut']} 個の、その月から先が未観測になっている。"
        f"この中には本物の急騰（{sym3} など）も、データの誤りと見られるもの（{err3}。倒産からの再出発や合併の前後の値がつながったと見られるが、記号ごとには確かめていない）も入っている。切りを使わない版（本物も誤りも残す）では、E3 は O で SPY に年{ks['E3_O_same_selection']['ex_ann_vs_spy']}%"
        f"（主 {g('E3', 'O', 'ex_ann')}%）・N で{ks['E3_N_same_selection']['ex_ann_vs_spy']}%（主 {g('E3', 'N', 'ex_ann')}%）、"
        f"後知恵の勝ち数は O で {ks['hindsight_O_beat_spy']} 人（主 {hs['O_all']['beat_spy_cagr']} 人）・t≥2 は {ks['hindsight_O_t_ge_2']} 人。"
        + (f"いちばん動いた写しは {sam['name']}（{sam['code']}）で、年率 {sam['cagr_default']}% → {sam['cagr_keep_spike']}%"
           f"（SPY との差 {sam['cagr_diff_vs_spy_default']:+} → {sam['cagr_diff_vs_spy_keep_spike']:+}pt・t {sam['t_default']} → {sam['t_keep_spike']}）＝この写しの年率は主の計算では低めに出ている" if sam else ''),
        f"期間（2013〜2026）は巨大テックと成長株が強かった時代だが、E3 の負けを『割安株への向かい風』だけでは説明できない: "
        f"E3 は割安の因子（HML）への傾きがほぼ無く（{hml('E3')}。E1 {hml('E1')}・E2 {hml('E2')}）、"
        f"市場・規模・割安・収益性・投資・勢いの6つの因子を引いた後もアルファが年{al('E3', 'O', 'alpha_ann')}%（t {al('E3', 'O', 't')}・O の版）残る。"
        '別の時代では結果が違いうる（100年の基礎率は R6・R8 の領分）',
        '組む月に価格が欠けた株を「一時的な欠け（価格なしとして持つ）」と「取引が終わった（分母から外す）」に分ける判定（sym_status）は、組む月の後3か月に価格があるかを見ている（データの欠けを見分けるためで、先の値動きは使わない）。'
        'O の結果には効かず、N と P30 で価格の取れない株として数えるか外すかだけに効く（検証役の見立てでは影響は小さい）',
        '13F は米国上場の買いの持ち高だけ（空売り・オプションの多く・現金・米国外の株・債券は見えない）。四半期末の姿を45日遅れで見るので、実際の運用とは別物',
        f"前の期間への訂正が次の期間の原本より後に出たもの（{sum(v for k, v in o['counts']['amendments_used_or_not'].items() if 'not_used' in k)}件）は古いので使っていない。"
        '2023年より前は価額が千ドル単位・以後はドル単位だが、提出ごとに株価で単位を確かめた（比重には効かない）',
        f"検算: 別の書き方で作り直した写し（訂正なし・CUSIP ごと・Yahoo を自分で読む）と本体の写しの年率の差は中央値 {(o.get('verify_independent_copy') or {}).get('median_abs_diff_cagr')}pt・最大 {(o.get('verify_independent_copy') or {}).get('max_abs_diff')}pt（night/bestpf_elite_clone_verify.py）。"
        '別の検証役が 13F の XML から一から作り直した E3（O）は SPY に年 −4.67%（t −1.86）で本体の −4.90% とほぼ同じ。ただし記号の照合を検証役だけで行うと −3.71%（t −1.44）になり'
        '（名前を変えた会社の対応表が無く Valeant→BHC の 2015-10 の下げが抜けるなど）、記号の照合の違いで E3 は約1pt 動きうる（どの版でも合格線には届かない）',
    ]
    pred = (f"事前登録の予想『E3 は費用後に SPY に勝たない（−1〜+1%/年・t<2）。順位相関はほぼ0』→ 勝たないは当たり。"
            f"ただし差は予想の幅より悪い: 中立の N で年{g('E3', 'N', 'ex_ann')}%（t {g('E3', 'N', 't')}・10人も N で選び直すと{sg('E3_rank_by_N', 'N', 'ex_ann')}%・t {sg('E3_rank_by_N', 'N', 't')}）・O の版で年{g('E3', 'O', 'ex_ann')}%（t {g('E3', 'O', 't')}）"
            f"（どちらも1つの置き方の値で、本当の値の中心ではない）。P30 の年{g('E3', 'P30', 'ex_ann')}%（t {g('E3', 'P30', 't')}）は、価格の取れない株に毎年くり返し −30% を掛ける作り方から決まる悲観の下限で、はっきり負けたという証拠ではない。"
            f"t が −2 前後なので『負けた』とまでは言えず、『勝たなかった』が言えること。"
            f"順位相関は平均 {rp['mean_spearman']}（t {rp['t_simple']}）でほぼ0〜やや負＝当たり（R2b の部分は別の担当）")
    feeds = ("最終の選択（bestpf_eval）には『写し（E3）は事前登録の合格線を O・N・P30 のどれでも満たさない＝器の候補に入れない』を渡す。"
             f"E1（N で SPY に年{g('E1', 'N', 'ex_ann')}%・t {g('E1', 'N', 't')}）・E2（N で{g('E2', 'N', 'ex_ann')}%・t {g('E2', 'N', 't')}）も勝っていない。"
             f"E3b は月ごとの差の平均では SPY に年{g('E3b', 'O', 'ex_ann'):+}%（t {g('E3b', 'O', 't')}・有意でない）だが、複利の年率では{g('E3b', 'O', 'cagr_diff'):+}pt で、どちらの物差しでも勝ったとは言えない。"
             "参考として E1・E2・E3・E3b の月次の系列（O・N・P30・費用後）と、"
             f"個別株15%の部分の参考になる『今の超投資家の持ち株』（baskets_now: E1 の上位・E2 の5人以上が持つ{(o['baskets_now'].get('E2') or {}).get('n')}銘柄・E3 の2026年の10人の上位）を渡す。"
             "超投資家の多くは過去13年に SPY に負けており、"
             "重なりは『安心材料』ではあっても上乗せの証拠ではない")
    return {'summary_ja': summary, 'deviations': dev, 'caveats': cav, 'prediction_check': pred, 'feeds_final': feeds}


def fixes_applied(o):
    """2026-10-12 の検証役の指摘と、何をどう直したか（JSON の fixes_applied）"""
    S_ = o['strategies']
    g = lambda k, v, key: (S_[k][v]['net']['vs_spy'] or {}).get(key)
    sw = o['missing_price_fill_sweep_E3']['by_plus_pct']
    swr = o['missing_price_fill_sweep_E3']['by_plus_pct_reselected']
    sgN = o['sensitivity']['E3_rank_by_N']['N']['net']['vs_spy']
    ks = o['spike_rule']['keep_spike_sensitivity']
    return [
        {'severity': 'medium', 'issue': '「本当の成績は O と P30 の間」は言いすぎ（O は上限ではない）',
         'fix': f"simulate に中立の版 N（価格の取れない株にその月の SPY の配当込みのリターンを置く）を足し、E1・E2・E3・E3b・感度・83人の写しのすべてで O・N・P30 の3本を出した。"
                f"E3 の N は SPY に年{g('E3', 'N', 'ex_ann')}%（t {g('E3', 'N', 't')}・10人は O の写しで選んだまま）。10人も N の写しで選び直す感度 E3_rank_by_N も足した（N で年{sgN['ex_ann']}%・t {sgN['t']}。"
                "検証役の中立の版 −3.47%・t −1.59 はこの形で、主の N との差の大半は選ばれる10人が変わることによる）。SPY＋5〜50%/年 を置く感度も足した（missing_price_fill_sweep_E3・10人は主と同じ: "
                + '・'.join(f"+{x}%→{r['ex_ann_vs_spy']}（t {r['t']}）" for x, r in sw.items()) + '／10人も選び直す: '
                + '・'.join(f"+{x}%→{r['ex_ann_vs_spy']}（t {r['t']}・後半 {r['halves_ex_ann'][1]}）" for x, r in swr.items()) + '）。'
                '注意書き・まとめ・予想の答え合わせを「P30 は悲観の下限・O は上限ではない」へ書き換え、O の −4.90% は中心の値ではなく O の版の値だと明記した。合否は3本とも不合格で変わらない。'
                '検証役の「t が2に届く置き方は無かった」は、10人も選び直して SPY＋50%/年 と置く極端な版で t 2.09 に届いた（ただし後半が負けで合格線は満たさない）ので、そう書いた'},
        {'severity': 'low', 'issue': '『月 +300% 超はデータの誤り』の切りが本物の急騰（GME・AMC・MDGL など）も消している',
         'fix': f"主の計算の規則は変えず（本物と誤りを記号ごとに外の出どころで確かめないと分けられないため）、切りに当たった記号の一覧（spike_rule.symbols・{o['spike_rule']['held_symbols_cut']} 個）と、"
                f"切りを使わない版の感度（E3 の O で SPY に年{ks['E3_O_same_selection']['ex_ann_vs_spy']}%・後知恵の勝ち数 {ks['hindsight_O_beat_spy']} 人・t≥2 は {ks['hindsight_O_t_ge_2']} 人・いちばん動いた写し）を足し、注意書きに書いた"},
        {'severity': 'low', 'issue': 'feeds_final の「E3b も SPY に勝っていない」と summary の「E3b +0.41%/年」が食い違って読める',
         'fix': f"E3b は月ごとの差の平均で年{g('E3b', 'O', 'ex_ann'):+}%（t {g('E3b', 'O', 't')}・有意でない）・複利の年率で{g('E3b', 'O', 'cagr_diff'):+}pt、と物差しを書き分けた"},
        {'severity': 'low', 'issue': '「割安株寄りの一覧には向かい風」は数字の裏付けが無い',
         'fix': 'E3 の HML の係数（ほぼ0）と、6つの因子を引いた後のアルファ（年 −4.5% 前後・t −2.0 前後）を並べ、「時代の向かい風だけでは説明できない」と書き直した'},
        {'severity': 'low', 'issue': 'P30 の −9.76%（t −4.31）を「はっきり負け」と書いた',
         'fix': '「P30 は作り方から決まる悲観の下限で、負けの証拠ではない」と書き直し、結論の根拠を O と N に置いた。judgement_E3_vs_SPY_net にも note と N の判定を足した'},
        {'severity': 'note', 'issue': '組む月の後3か月の価格の有無で「一時的な欠け」と「取引が終わった」を分ける判定（sym_status）',
         'fix': '直していない（データの欠けを見分けるためで値動きは使わない・O には効かない）。注意書きに書いた'},
    ]


def e3_cagr(S_, k, v):
    return S_[k][v]['net']['cagr']


def spike_list(bk):
    """B.SPIKE（月 +300% 超）で『データの誤り』として切られた記号のうち、83人のどれかが持っていたもの（感度と注意書きの材料）"""
    held = defaultdict(set)
    for code, fl in bk.F.items():
        for r in fl:
            for cu in r['pos']:
                sym = bk.res.get((cu, r['period']))
                if sym:
                    held[sym].add(code)
    out = []
    for sym in sorted(held):
        y = B.yh_load(sym)
        if not y or not y.get('spike'):
            continue
        k = y['spike']; a0 = B.madd(k, -1); k1 = B.madd(k, 1)
        x = y['adj'][k] / y['adj'][a0] - 1 if a0 in y['adj'] else None
        nx = y['adj'][k1] / y['adj'][k] - 1 if k1 in y['adj'] else None
        out.append({'sym': sym, 'name': y.get('name'), 'spike_month': k, 'ret_pct': round(x * 100, 1) if x is not None else None,
                    'next_month_pct': round(nx * 100, 1) if nx is not None else None, 'holders': len(held[sym])})
    out.sort(key=lambda r: -(r['ret_pct'] or 0))
    return out, len(held)


def main_calc():
    (bk, codes, copies, sims, sens, sel, benches, fp, spy, qqq, mkt, sweep, spike_sens) = calc()
    selT, detT, selB, detB, selTp, detTp, sel17, det17, selTn, detTn = sel
    sweep, sweep_resel = sweep
    D = {'E1': '全員の 13F の上位20（各人の中で比重を合計1）を人ごとに等しく足す（提出日の翌月から・新しい提出で入れ替え）',
         'E2': 'その時点で5人以上が持つ銘柄（会社）を等しく',
         'E3': '2015年末から毎年末、その時点までの過去3年の写しの成績（O・費用前）の上位10人を選び、その10人の上位10銘柄の和集合を等しく（翌年は同じ10人の新しい提出で入れ替え）',
         'E3b': 'E3 と同じ作り方の下位10人（対照）'}
    reps = {k: report(k, D[k], sims[k], benches, fp) for k in ('E1', 'E2', 'E3', 'E3b')}
    SD = {'E3_slot': 'E3 の感度: 人ごとに等しく・各人の上位10を等しく（重なる銘柄は足す）',
          'E3_rank_by_P30': 'E3 の感度: 写しの成績を P30（価格の欠けに −30%）で順位づけ',
          'E3_from2017_full36m': 'E3 の感度: 最初の選びを2016年末（過去3年がそろう）にし 2017-01 から持つ',
          'E3b_slot': 'E3b の感度: 人ごとに等しく',
          'E3_rank_by_N': 'E3 の感度（2026-10-12）: 写しの成績も中立の N（価格の取れない株に SPY）で順位づけて10人を選ぶ（検証役の作り直しと同じ形）'}
    sreps = {k: report(k, SD[k], sens[k], benches, fp) for k in sens}
    jd = judge(reps['E3'])
    hrows, hsum = hindsight(copies, benches, fp)
    # 感度: 価格の取れない株に SPY＋x%/年
    def ex_line(sim_):
        st_ = stats_vs(sim_['net'], benches, fp)
        e_ = st_['vs_spy'] or {}
        hh = [(stats_vs(sim_['net'], benches, fp, h0, h1)['vs_spy'] or {}).get('ex_ann') for h0, h1 in HALVES]
        return {'cagr': st_['cagr'], 'ex_ann_vs_spy': e_.get('ex_ann'), 't': e_.get('t'), 'cagr_diff': e_.get('cagr_diff'),
                'halves_ex_ann': hh,
                'pass_bar': bool((e_.get('ex_ann') or -9) >= 1.0 and (e_.get('t') or -9) >= 2.0 and all((x or -9) > 0 for x in hh))}
    fill_sweep = {'note': 'E3（選んだ10人は主と同じ）で、価格の取れない株（記号なし・その月の値が欠けた）に SPY の配当込みの月次＋x%/年 を置いた版（費用後）。'
                          'x=0 が N（中立）。価格の取れない比重は平均約1割',
                  'by_plus_pct': {'0': ex_line(sims['E3']['N'])} | {str(x): ex_line(sweep[x]) for x in FILL_SWEEP},
                  'note_reselected': '同じ置き方で各運用者の写しの成績も作り直し、毎年末の10人も選び直した版（x=0 は感度 E3_rank_by_N の N）',
                  'by_plus_pct_reselected': {'0': ex_line(sens['E3_rank_by_N']['N'])} | {str(x): ex_line(sweep_resel[x]) for x in FILL_SWEEP}}
    sp_list, n_held_syms = spike_list(bk)
    sk_copies = spike_sens['copies']
    ks_rows = []
    for c in codes:
        a_, b_ = copies[c]['O']['net'], sk_copies[c]['O']['net']
        if len(a_) >= 24 and len(b_) >= 24:
            ea, eb = M.excess_stats(a_, benches['spy']), M.excess_stats(b_, benches['spy'])
            ks_rows.append({'code': c, 'name': bk.info[c]['name'], 'cagr_default': round(M.cagr(a_) * 100, 2),
                            'cagr_keep_spike': round(M.cagr(b_) * 100, 2),
                            'cagr_diff_vs_spy_default': ea['cagr_diff'] if ea else None,
                            'cagr_diff_vs_spy_keep_spike': eb['cagr_diff'] if eb else None,
                            't_default': ea['t'] if ea else None, 't_keep_spike': eb['t'] if eb else None})
    ks_rows.sort(key=lambda r: -abs(r['cagr_keep_spike'] - r['cagr_default']))
    spike_block = {
        'rule': 'night/mw_best_ideas_13f.SPIKE＝3.0: 月 +300% 超の月から先を未観測にする（データの誤り対策）。本物の急騰も同じく消える（2026-10-12 検証役の指摘）',
        'held_symbols_cut': len(sp_list), 'held_symbols_total': n_held_syms,
        'symbols': sp_list,
        'keep_spike_sensitivity': {
            'note': '切りを使わず adj の連続した月からすべてのリターンを作った版（本物の急騰も、データの誤りも残る＝上側の感度）',
            'E3_O_same_selection': ex_line(spike_sens['E3_same_selection']['O']),
            'E3_N_same_selection': ex_line(spike_sens['E3_same_selection']['N']),
            'E3_P30_same_selection': ex_line(spike_sens['E3_same_selection']['P30']),
            'E3_O_reselected': ex_line(spike_sens['E3_reselected']['O']),
            'E3_selection_changed_years': spike_sens['selection_changed_years'],
            'E1_O': ex_line(spike_sens['E1']['O']),
            'hindsight_O_beat_spy': sum(1 for r in ks_rows if (r['cagr_diff_vs_spy_keep_spike'] or 0) > 0),
            'hindsight_O_t_ge_2': sum(1 for r in ks_rows if (r['t_keep_spike'] or 0) >= 2.0),
            'copies_most_changed': ks_rows[:10]}}
    rp = rank_persistence(copies)
    # 今日の姿（2026Q2 の提出がすべて効く 2026-10 の目標）
    now = B.madd(END, 2)
    baskets = {'E1': current_basket(bk, e1_target(bk, codes), now),
               'E2': current_basket(bk, e2_target(bk, codes), now),
               'E3_2026_selection': current_basket(bk, e3_target(bk, {now // 100: selT.get(2026)}), now),
               'E3b_2026_selection': current_basket(bk, e3_target(bk, {now // 100: selB.get(2026)}), now)}
    # 提出の数え
    kinds = Counter(r['kind'] for fl in bk.F.values() for r in fl)
    used_amend = Counter()
    for c in codes:
        seen = set()
        for m in months_all():
            a = bk.active(c, m)
            if a:
                for acc in a[0][2]:
                    if acc not in seen:
                        seen.add(acc)
        for r in bk.F[c]:
            if r['kind'] != 'orig':
                used_amend[(r['kind'], r['acc'] in seen)] += 1
    names = {c: bk.info[c]['name'] for c in codes}
    for d in (detT, detB, detTp, det17, detTn):
        for Y, x in d.items():
            x['picked'] = [[c, names.get(c), r] for c, r in x['picked']]
    sn = lambda d: series_out(d)

    def yearly(d):
        out_ = {}
        for y in range(START // 100, END // 100 + 1):
            ks = [k for k in d if k // 100 == y]
            if ks:
                out_[str(y)] = round((math.prod(1 + d[k] for k in ks) - 1) * 100, 1)
        return out_
    annual = {'SPY': yearly(benches['spy']), 'QQQ': yearly(benches['qqq']), 'French_Mkt': yearly(benches['french_mkt'])}
    for k in sims:
        for ver in VERS:
            annual[f'{k}_{ver}_net'] = yearly(sims[k][ver]['net'])
    out = {
        'name': 'bestpf R2 elite_clone（成績の良い投資家の 13F を写すと市場に勝ったか）',
        'prereg': f'out/bestpf_prereg.json の modules.R2_elite_clone（コミット {PREREG_COMMIT}）',
        'code': 'night/bestpf_elite_clone.py（--fetch → --map → --calc）',
        'generated': datetime.date.today().isoformat(),
        'data': {
            'filers': 'out/_bestpf_cache/ciks.json（R0・Dataroma の83件・四半期ごとの 13F-HR の受付番号）',
            'sec': 'https://www.sec.gov/Archives/edgar/data/<cik>/<受付番号>/index.json と information table XML・primary_doc.xml（訂正の種類）・https://data.sec.gov/submissions/CIK##########.json',
            'prices': 'Yahoo の月次（配当込みの調整後終値）https://query1.finance.yahoo.com/v8/finance/chart/<記号>?interval=1mo（night/mw_best_ideas_13f.yh_load で読む）',
            'cusip_to_symbol': 'FTD（SEC の決済の失敗の公表データ・2013-12〜2026-09・当時の記号）と OpenFIGI（現在の記号）の候補を、13F の合意の株価（R2b の qpx・全提出者の中央値）か提出の暗黙の株価と Yahoo の当時の終値で ±15% 照合（night/mw_best_ideas_13f.resolve）＋同じ CUSIP の別の期間で照合できた記号',
            'benchmarks': 'SPY・QQQ（Yahoo・配当込み）・French Mkt（F-F_Research_Data_Factors の Mkt-RF＋RF）。因子: F-F_Research_Data_5_Factors_2x3 と F-F_Momentum_Factor',
            'window': f'{START}〜{END}（持つ月）。E3 は 201601〜',
        },
        'counts': {'managers': len(codes), 'filings_by_kind': dict(kinds),
                   'amendments_used_or_not': {f'{k[0]}|{"used" if k[1] else "not_used(古い期間・後から出た)"}': v for k, v in used_amend.items()},
                   'notes': dict(bk.notes)},
        'rules_as_run': {
            'timing': '各提出は提出日の翌月の初めから持つ（その月のリターンが最初）。訂正も同じ（RESTATEMENT は置き換え・NEW HOLDINGS は足す・その期間がまだ最新のときだけ）',
            'stale': f'報告期間の末から {STALE_MONTHS} か月を過ぎた提出は使わない（提出が止まった運用者を写し続けない）',
            'stocks_only': 'プット/コール・PRN・優先株/社債/ワラント/権利の題名・ETF/投信の名前を除く（night/mw_best_ideas_13f の NONCOMMON_RE・ETF_RE）。同じ会社の別の種類株は Yahoo の会社名で1銘柄にまとめる',
            'units': 'units.json: 提出ごとに合意の株価と暗黙の株価で ×1/×1000 を決める（比重には効かない・訂正を足すときに効く）',
            'missing': 'O＝観測できる分で按分（＝価格の取れない株は残りの株と同じ成績と置く・上限ではない）／N＝価格の取れない株にその月の SPY の配当込みのリターンを置く（中立・2026-10-12 追加）／'
                       'P30＝最初の欠けた月に −30%・以後は現金（悲観の下限）。組む前に取引が終わった株は分母から除く',
            'cost': f'片道 {COST_ONEWAY * 100:.1f}% を入れ替えの月の片道の回転に掛ける（最初に買う費用は掛けない）',
            'e3_ranking': '写しの成績＝その人の 13F の株の全保有を価額の比で持つ O 版の費用前の複利。過去3年の全月がそろう運用者だけ',
        },
        'judgement_E3_vs_SPY_net': jd,
        'missing_price_fill_sweep_E3': fill_sweep,
        'spike_rule': spike_block,
        'prediction': json.load(open(os.path.join(BASE, 'out', 'bestpf_prereg.json')))['modules']['R2_elite_clone']['prediction'],
        'strategies': reps,
        'sensitivity': sreps,
        'e3_selection': {'top_by_O': detT, 'bottom_by_O': detB, 'top_by_P30': detTp, 'top_from2016_end': det17, 'top_by_N': detTn},
        'rank_persistence_83': rp,
        'hindsight_upper_bound': {'note': '★後知恵: 83人の一覧そのものが今日（2026-10）の Dataroma の Superinvestors＝後から見て名の知れた人。'
                                          'ここの勝ち数は前もって選べた数ではない（上限の参考）',
                                  'summary': hsum, 'managers': [dict(r, name=names.get(r['code'])) for r in hrows]},
        'annual_returns_pct': annual,
        'baskets_now': baskets,
        'verify_independent_copy': (json.load(open(os.path.join(C, 'verify_summary.json')))['summary']
                                    if os.path.exists(os.path.join(C, 'verify_summary.json')) else None),
        'series': {
            'bench': {'spy': sn(benches['spy']), 'qqq': sn(benches['qqq']), 'french_mkt': sn(benches['french_mkt'])},
            'strategies': {k: {ver: {'net': sn(sims[k][ver]['net']), 'gross': sn(sims[k][ver]['gross'])} for ver in VERS} for k in sims},
            'sensitivity': {k: {ver: {'net': sn(sens[k][ver]['net'])} for ver in VERS} for k in sens},
            'copies': {c: {'O': sn(copies[c]['O']['net']), 'N': sn(copies[c]['N']['net']), 'P30': sn(copies[c]['P30']['net']),
                           'O_gross': sn(copies[c]['O']['gross'])} for c in copies},
        },
    }
    out.update(notes_ja(out))
    out['fixes_applied'] = fixes_applied(out)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('書いた', OUT, flush=True)
    print(json.dumps(jd, ensure_ascii=False))
    return out


if __name__ == '__main__':
    os.makedirs(C, exist_ok=True)
    if '--fetch' in sys.argv:
        fetch()
    elif '--map' in sys.argv:
        do_map()
    elif '--notes' in sys.argv:                 # 計算は回さず、JSON の数字から文章だけ作り直す
        o = json.load(open(OUT))
        o.update(notes_ja(o))
        o['fixes_applied'] = fixes_applied(o)
        json.dump(o, open(OUT, 'w'), ensure_ascii=False, indent=1)
        print('書いた', OUT)
    else:
        main_calc()
