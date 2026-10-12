#!/usr/bin/env python3
"""night/bestpf_superinvestors_now.py — bestpf R1: 成績の良い投資家たちは今なにを持っているか（読むだけ）

事前登録: out/bestpf_prereg.json（コミット 7c4b672）の modules.R1_superinvestors_now。
  q       : 成績の良い投資家たちは今なにを持っているか（2026年6月末の 13F・2026年8月提出）
  universe: Dataroma の Superinvestors の一覧（2026-10-12 時点の83件・dataroma_list）。
            13F を出していない・米国株の保有が無いものは名指しして外す
  out     : 各人の上位保有と比重・何人が持っているか（合意）・門の投下可/次点/台帳との重なり・
            各人の公表された長期の成績（出典つき・確かめられないものは確かめられないと書く）
門・採点・配分（portfolio.json）には触れない＝判断の材料。

入力
  out/_bestpf_cache/ciks.json   … R0（night/bestpf_ciks.py）が作った code→CIK と、Dataroma と突き合わせた受付番号
  EDGAR の各提出の情報表 XML    … https://www.sec.gov/Archives/edgar/data/<cik>/<受付番号>/index.json から XML を探して取る
  SEC 13F データセット          … out/_bestpf_cache/R0/01jun2026-31aug2026_form13f.zip（R0 が取った・読むだけ）
                                   ① 同じ受付番号の行数・合計額で XML を検算 ② 全提出者の CUSIP ごとの株価の中央値で
                                   「千ドル単位」の申告を見つける ③ 修正（13F-HR/A）の種類を読む
  OpenFIGI                      … CUSIP→ティッカー（鍵なし・1分25回・1回10件）。既存の out/_mw_cache/bi13f/figi.json を
                                   読むだけで種に使い、足りない分を out/_bestpf_cache/R1/figi.json に貯める
  SEC company_tickers.json      … OpenFIGI で引けない CUSIP の名前の照合（最後の手段・出所を印す）
  out/score_all.json            … 門の Ω・四関門・投下可・次点（読むだけ）

株だけにする規則（作業指示どおり・mw_best_ideas_13f と同じ正規表現）
  - putCall のある行（オプション）を除く／sshPrnamtType=PRN（社債など元本額の行）を除く
  - titleOfClass が優先株・社債・ワラント・権利（NONCOMMON_RE）なら除く。OpenFIGI の種類が Preference/Warrant/Right なども除く
  - ETF・投資信託の持分（OpenFIGI の種類が ETP・Fund など）は株の器なので残し、kind='fund' と印す（合意の順位は個別株だけで作る）
  - 同じ発行体（CUSIP の先頭6桁）の株の種類（例 GOOGL と GOOG・BRK-A と BRK-B）はまとめる

段
  --fetch : 各人の情報表 XML を EDGAR から取る（毎秒10件以下）
  --figi  : CUSIP→ティッカーを OpenFIGI で引く
  (既定)  : 計算して out/bestpf_superinvestors_now.json を書く
"""
import csv, gzip, io, json, math, os, re, statistics as S, sys, time, urllib.error, urllib.request, zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mw_best_ideas_13f import SEC_UA, NONCOMMON_RE, NONSTOCK_TYPES, ETF_RE  # noqa: E402  （同じ User-Agent・同じ正規表現）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, 'out', '_bestpf_cache', 'R1')
XMLD = os.path.join(CACHE, 'xml')
CIKS = os.path.join(BASE, 'out', '_bestpf_cache', 'ciks.json')
DS_ZIP = os.path.join(BASE, 'out', '_bestpf_cache', 'R0', '01jun2026-31aug2026_form13f.zip')
DS_URL = 'https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip'
FIGI_SEED = os.path.join(BASE, 'out', '_mw_cache', 'bi13f', 'figi.json')   # 読むだけ
FIGI_OWN = os.path.join(CACHE, 'figi.json')
TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
PREREG = os.path.join(BASE, 'out', 'bestpf_prereg.json')
SCORE_ALL = os.path.join(BASE, 'out', 'score_all.json')
OUT = os.path.join(BASE, 'out', 'bestpf_superinvestors_now.json')
TARGET_PERIOD = '30-JUN-2026'
TOPN = 10
CONS_N = 30
# 優先株・転換優先株の見分けの補い（発行体名に PFD/PREF/CONV と書かれ、題名が普通株でない行）
PREF_NAME_RE = re.compile(r'\b(PFD|PREF|PREFERRED|CONV PFD|CNV PFD)\b', re.I)
FUND_TYPES = {'ETP', 'Closed-End Fund', 'Open-End Fund', 'Mutual Fund', 'Fund of Funds', 'Unit Inv Tr'}
NONEQ_TYPES = NONSTOCK_TYPES - FUND_TYPES          # Preference・Warrant・Right・Unit・Structured Product など
# 株でない器（金・銀などの現物・商品・国債/社債/地方債・暗号資産）の ETF。株だけにするので比重から外す（OpenFIGI の名前＋題名で判定）
NONSTOCK_FUND_RE = re.compile(r'GOLD (SHARES|SHS|TRUST|TR\b|MINISHARES)|SPDR GLD|PHYSICAL|PHYSCL|SILVER (TRUST|SHARES)|T-BILL|TREASURY|TREASRY|'
                              r'\bTREAS\b|BOND|\bBD\b|MUNI|TEUCRIUM|BITCOIN|ETHEREUM|SHORT DURATION GOVT|SHT DURA GOV|CORN FD|WHEAT FD', re.I)
os.makedirs(XMLD, exist_ok=True)
csv.field_size_limit(1 << 30)


# ───────────────────────── 取得 ─────────────────────────
_last = [0.0]


def sec_get(url, path, tries=5):
    """SEC から取ってキャッシュする（毎秒10件以下＝最短0.12秒あける）。取ったファイルはデータとして読むだけ"""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return open(path, 'rb').read()
    err = None
    for i in range(tries):
        try:
            wait = 0.12 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            tmp = f'{path}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, path)
            return b
        except Exception as e:  # noqa
            err = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}: {err}')


def load_ciks():
    return json.load(open(CIKS))


def ds_tsv(z, name):
    n = next(x for x in z.namelist() if x.rsplit('/', 1)[-1] == name)
    with z.open(n) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='ignore'), delimiter='\t', quoting=csv.QUOTE_NONE)


def ds_filings(ciks_int):
    """データセットから、対象の CIK の 2026-06-30 の 13F-HR と 13F-HR/A を全部（種類・修正の型・提出日・合計額つき）"""
    z = zipfile.ZipFile(DS_ZIP)
    cov = {r['ACCESSION_NUMBER']: r for r in ds_tsv(z, 'COVERPAGE.tsv')}
    summ = {r['ACCESSION_NUMBER']: r for r in ds_tsv(z, 'SUMMARYPAGE.tsv')}
    out = defaultdict(list)
    for r in ds_tsv(z, 'SUBMISSION.tsv'):
        try:
            c = int(r['CIK'])
        except Exception:  # noqa
            continue
        if c not in ciks_int or r['PERIODOFREPORT'] != TARGET_PERIOD:
            continue
        a = r['ACCESSION_NUMBER']; cv = cov.get(a, {}); sm = summ.get(a, {})
        out[c].append({'acc': a, 'type': r['SUBMISSIONTYPE'], 'filed': r['FILING_DATE'],
                       'is_amend': (cv.get('ISAMENDMENT') or '').upper() == 'Y', 'amend_type': cv.get('AMENDMENTTYPE') or '',
                       'report_type': cv.get('REPORTTYPE') or '',
                       'entries': float(sm.get('TABLEENTRYTOTAL') or 0), 'value_total': float(sm.get('TABLEVALUETOTAL') or 0)})
    return out


MONS = {m: i + 1 for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'])}


def d8(s):
    d, mo, y = s.split('-')
    return int(y) * 10000 + MONS[mo.upper()] * 100 + int(d)


def choose_filing(c, fl):
    """その人の 2026-06-30 の提出のうち、どれを使うか（理由つき）。
    規則: ① 修正の RESTATEMENT（全部の差し替え）があれば最後のもの ② NEW HOLDINGS（追加）の修正が後にあり、
    その表が原本の額の 90%以上を同じ CUSIP で覆う（＝実は全表）なら、その修正を全表として使う（実例 FE）
    ③ そうでない NEW HOLDINGS は原本に足す ④ 修正が無ければ原本。決まらないときは R0 が Dataroma と合わせた受付番号"""
    orig = sorted([f for f in fl if f['type'] == '13F-HR'], key=lambda f: d8(f['filed']))
    amd = sorted([f for f in fl if f['type'] == '13F-HR/A'], key=lambda f: d8(f['filed']))
    rest = [f for f in amd if f['amend_type'].upper().startswith('RESTATE')]
    if rest:
        return {'mode': 'single', 'accs': [rest[-1]['acc']], 'why': f"修正（RESTATEMENT）{rest[-1]['acc']}（{rest[-1]['filed']} 提出）で原本を差し替え"}
    newh = [f for f in amd if 'NEW HOLDING' in f['amend_type'].upper()]
    if orig and newh:
        return {'mode': 'newholdings', 'orig': orig[-1]['acc'], 'amends': [f['acc'] for f in newh],
                'why': '原本＋NEW HOLDINGS の修正（覆い率で全表か追加かを判定）'}
    if orig:
        return {'mode': 'single', 'accs': [orig[-1]['acc']], 'why': f"原本 {orig[-1]['acc']}（{orig[-1]['filed']} 提出）・修正なし"}
    a = (c.get('match') or {}).get('acc')
    return {'mode': 'single', 'accs': [a] if a else [], 'why': 'データセットに 2026-06-30 の提出なし → R0 が Dataroma と合わせた受付番号'}


def acc_dir(cik, acc):
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-", "")}/'


def fetch_infotable(cik, acc):
    """index.json から情報表の XML を探して取る（primary_doc.xml 以外で infoTable を含むもの）"""
    idx = json.loads(sec_get(acc_dir(cik, acc) + 'index.json', os.path.join(XMLD, f'{acc}_index.json')))
    items = [it['name'] for it in idx.get('directory', {}).get('item', []) if it['name'].lower().endswith('.xml')]
    cands = [n for n in items if n.lower() != 'primary_doc.xml']
    for n in sorted(cands, key=lambda s: (0 if 'info' in s.lower() or 'table' in s.lower() else 1, s)):
        b = sec_get(acc_dir(cik, acc) + n, os.path.join(XMLD, f'{acc}__{n}'))
        if b'infoTable' in b or b'infotable' in b.lower():
            return n, acc_dir(cik, acc) + n
    return None, None


def strip_ns(tag):
    return tag.rsplit('}', 1)[-1]


def parse_infotable(path):
    """情報表 XML → 行のリスト（素の値・単位は直さない）"""
    root = ET.parse(path).getroot()
    rows = []
    for el in root.iter():
        if strip_ns(el.tag) != 'infoTable':
            continue
        d = {}
        for ch in el.iter():
            t = strip_ns(ch.tag)
            if t in ('nameOfIssuer', 'titleOfClass', 'cusip', 'figi', 'value', 'sshPrnamt', 'sshPrnamtType', 'putCall',
                     'investmentDiscretion'):
                d[t] = (ch.text or '').strip()
        rows.append(d)
    return rows


def fetch():
    cj = load_ciks()
    ciks_int = {int(c['cik']) for c in cj['ciks']}
    dsf = ds_filings(ciks_int)
    plan = {}
    for c in cj['ciks']:
        code, cik = c['code'], c['cik']
        if c['has_2026_06_30_13f_hr']:
            ch = choose_filing(c, dsf.get(int(cik), []))
            accs = ch['accs'] if ch['mode'] == 'single' else [ch['orig']] + ch['amends']
        else:
            ch = {'mode': 'latest', 'accs': [c['match']['acc']]}
            accs = ch['accs']
        got = {}
        for a in accs:
            n, url = fetch_infotable(cik, a)
            got[a] = {'file': n, 'url': url}
            print(code, a, n, flush=True)
        plan[code] = {'choice': ch, 'files': got, 'ds_filings': dsf.get(int(cik), [])}
    json.dump(plan, open(os.path.join(CACHE, 'plan.json'), 'w'), ensure_ascii=False, indent=1)
    print('取得の計画を保存', len(plan))


# ───────────────────────── CUSIP → 記号 ─────────────────────────
def norm_cusip(s):
    s = re.sub(r'[^0-9A-Za-z]', '', s or '').upper()
    return s if len(s) == 9 else None


def load_figi():
    seed = json.load(open(FIGI_SEED)) if os.path.exists(FIGI_SEED) else {}
    own = json.load(open(FIGI_OWN)) if os.path.exists(FIGI_OWN) else {}
    m = dict(seed)
    m.update(own)       # 自分で引いたもの（CINS で引き直したもの）を優先
    return m, own


def figi_query(batch, idtype):
    body = json.dumps([{'idType': idtype, 'idValue': cu} for cu in batch]).encode()
    for k in range(6):
        try:
            req = urllib.request.Request('https://api.openfigi.com/v3/mapping', data=body,
                                         headers={'Content-Type': 'application/json'})
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as e:
            time.sleep(20 if e.code == 429 else 5 * (k + 1))
        except Exception:  # noqa
            time.sleep(5 * (k + 1))
    return None


def pick_figi(data):
    us = [x for x in data if x.get('exchCode') == 'US'] or [x for x in data if x.get('exchCode') in ('UN', 'UW', 'UQ', 'UA', 'UR', 'UP', 'UV')] or data
    x = us[0]
    return {k2: x.get(k2) for k2 in ('ticker', 'name', 'securityType', 'securityType2', 'marketSector', 'exchCode')}


def figi_map(cs):
    m, own = load_figi()
    todo = [cu for cu in sorted(cs) if cu not in m]
    # 種（mw の figi.json）で『見つからない』だった外国の CINS（先頭が英字）は ID_CINS で引き直す
    retry = [cu for cu in sorted(cs) if cu in m and 'none' in m[cu] and cu[0].isalpha() and cu not in own]
    print('OpenFIGI: 未取得', len(todo), '件・CINS で引き直し', len(retry), '件', flush=True)
    for idtype, lst in (('ID_CUSIP', todo), ('ID_CINS', retry)):
        for i in range(0, len(lst), 10):
            batch = lst[i:i + 10]
            res = figi_query(batch, idtype)
            if res is None:
                print('  OpenFIGI 失敗', batch[0]); continue
            for cu, r in zip(batch, res):
                data = r.get('data') or []
                own[cu] = dict(pick_figi(data), via=idtype) if data else {'none': r.get('warning') or r.get('error') or 'no data', 'via': idtype}
            json.dump(own, open(FIGI_OWN, 'w'))
            time.sleep(2.5)
    # ID_CUSIP で見つからなかった英字始まりは ID_CINS でもう一度
    again = [cu for cu in sorted(cs) if cu in own and 'none' in own[cu] and cu[0].isalpha() and own[cu].get('via') == 'ID_CUSIP']
    for i in range(0, len(again), 10):
        batch = again[i:i + 10]
        res = figi_query(batch, 'ID_CINS')
        if res is None:
            continue
        for cu, r in zip(batch, res):
            data = r.get('data') or []
            if data:
                own[cu] = dict(pick_figi(data), via='ID_CINS')
        json.dump(own, open(FIGI_OWN, 'w'))
        time.sleep(2.5)
    json.dump(own, open(FIGI_OWN, 'w'))
    return load_figi()[0]


# ───────────────────────── 読む・揃える ─────────────────────────
def consensus_prices():
    """データセットの全提出（2026-06-30・SH・オプションでない）の CUSIP ごとの株価（値÷株数）の中央値（素の単位）"""
    path = os.path.join(CACHE, 'cons_px.json')
    if os.path.exists(path):
        return json.load(open(path))
    z = zipfile.ZipFile(DS_ZIP)
    acc_ok = {r['ACCESSION_NUMBER'] for r in ds_tsv(z, 'SUBMISSION.tsv')
              if r['PERIODOFREPORT'] == TARGET_PERIOD and r['SUBMISSIONTYPE'] in ('13F-HR', '13F-HR/A')}
    px = defaultdict(list)
    for r in ds_tsv(z, 'INFOTABLE.tsv'):
        if r['ACCESSION_NUMBER'] not in acc_ok:
            continue
        if (r.get('SSHPRNAMTTYPE') or '').upper() != 'SH' or (r.get('PUTCALL') or '').strip():
            continue
        cu = norm_cusip(r.get('CUSIP'))
        try:
            v, sh = float(r['VALUE']), float(r['SSHPRNAMT'])
        except Exception:  # noqa
            continue
        if cu and v > 0 and sh > 0:
            px[cu].append(v / sh)
    cons = {cu: [S.median(v), len(v)] for cu, v in px.items() if len(v) >= 3}
    json.dump(cons, open(path, 'w'))
    return cons


def ds_rows_for(accs):
    """検算用: データセットの同じ受付番号の行数と合計額"""
    path = os.path.join(CACHE, 'ds_check.json')
    have = json.load(open(path)) if os.path.exists(path) else {}
    need = [a for a in accs if a not in have]
    if need:
        z = zipfile.ZipFile(DS_ZIP)
        tot = defaultdict(lambda: [0, 0.0])
        ns = set(need)
        for r in ds_tsv(z, 'INFOTABLE.tsv'):
            a = r['ACCESSION_NUMBER']
            if a in ns:
                tot[a][0] += 1
                try:
                    tot[a][1] += float(r['VALUE'])
                except Exception:  # noqa
                    pass
        for a in need:
            have[a] = tot.get(a, [0, 0.0]) if a in tot else None
        json.dump(have, open(path, 'w'))
    return have


def table_of(acc, f):
    return parse_infotable(os.path.join(XMLD, f'{acc}__{f["file"]}'))


def resolve_tables(code, pl):
    """選んだ提出の表（行のリスト）と、使った受付番号・理由を返す"""
    ch = pl['choice']
    if ch['mode'] in ('single', 'latest'):
        a = ch['accs'][0]
        return table_of(a, pl['files'][a]), [a], ch.get('why') or '最新の 13F-HR（2026-06-30 の提出なし）'
    # NEW HOLDINGS: 最後の修正が原本の額の90%以上を同じ CUSIP で覆えば全表として使う。でなければ原本に足す
    o = table_of(ch['orig'], pl['files'][ch['orig']])
    last = ch['amends'][-1]
    t = table_of(last, pl['files'][last])
    ov = defaultdict(float)
    for r in o:
        ov[(r.get('cusip') or '').upper()] += float(r.get('value') or 0)
    tc = {(r.get('cusip') or '').upper() for r in t}
    tot = sum(ov.values())
    cover = sum(v for k, v in ov.items() if k in tc) / tot if tot > 0 else 0
    if cover >= 0.90:
        return t, [last], (f'NEW HOLDINGS と印された修正 {last} が原本 {ch["orig"]} の額の {cover:.1%} を同じ CUSIP で覆う'
                           f'＝実は全表 → この修正だけを使う（足すと二重に数える）')
    rows = list(o)
    for a in ch['amends']:
        rows += table_of(a, pl['files'][a])
    return rows, [ch['orig']] + ch['amends'], f'原本 {ch["orig"]} に NEW HOLDINGS の修正 {ch["amends"]} を足す（覆い率 {cover:.1%}）'


def raw_holdings():
    """各人の素の行（選んだ表）と使った受付番号"""
    cj = load_ciks()
    plan = json.load(open(os.path.join(CACHE, 'plan.json')))
    out = {}
    for c in cj['ciks']:
        code = c['code']
        pl = plan[code]
        rows, accs, why = resolve_tables(code, pl)
        out[code] = {'rows': rows, 'accs': accs, 'why': why}
    return out



# ───────────────────────── 名前の照合（OpenFIGI で引けない CUSIP の最後の手段） ─────────────────────────
SUFFIX_RE = re.compile(r'\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|NV|N V|SA|S A|AG|SE|LLC|LP|L P|'
                       r'HLDGS|HOLDINGS|HLDG|HOLDING|GROUP|GRP|THE|NEW|DEL|COM|CL A|CL B|CLASS A|CLASS B)\b')


def norm_name(s):
    s = re.sub(r'[^A-Z0-9 ]', ' ', (s or '').upper().replace('&', ' AND '))
    s = SUFFIX_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def sec_tickers():
    b = sec_get(TICKERS_URL, os.path.join(CACHE, 'company_tickers.json'))
    d = json.loads(b)
    by = defaultdict(list)
    for v in d.values():
        by[norm_name(v['title'])].append(v['ticker'])
    return by


def norm_ticker(t):
    return (t or '').replace('/', '-').replace(' ', '-').upper() or None


# ───────────────────────── 門 ─────────────────────────
def gate_rows():
    rows = json.load(open(SCORE_ALL))
    return {r['t'].upper(): r for r in rows}


def blockers(r):
    """score_all.js の blockers() と同じ並び（表示だけ・判定はしない）＋ Ω75 未満"""
    b = []
    if r.get('s') is not None and r['s'] < 75:
        b.append('Ω75未満')
    if r.get('moatNA'):
        b.append('堀が算出不能')
    elif not r.get('moatOK'):
        b.append('堀不足(70未満)')
    if not r.get('audOK'):
        b.append('点検要修正')
    if r.get('shrink'):
        b.append('事業の収縮')
    if r.get('staleBS') is not None:
        b.append('期末後の重大事象')
    if r.get('vFail'):
        b.append('納品検査FAIL')
    if r.get('pending'):
        b.append('未完了の重大事象')
    if r.get('veto'):
        b.append('人の判断で見送り（拒否権）')
    return b


def gate_info(tickers, G):
    """発行体の記号の集合 → 門の台帳の行（あれば）。GOOG/GOOGL のような株の種類は発行体でまとめて当てる"""
    alias = {'GOOG': 'GOOGL', 'BRK-A': 'BRK-B', 'FOX': 'FOXA', 'NWS': 'NWSA'}
    for t in list(tickers) + [alias.get(t) for t in tickers if alias.get(t)]:
        if t and t.upper() in G:
            r = G[t.upper()]
            st = '投下可' if r.get('buy') else ('次点' if r.get('quali') else '台帳（関門で落ちる）')
            return {'gate_ticker': r['t'], 'status': st, 'omega': r.get('s'), 'tier': r.get('tier'), 'moat': r.get('moat'),
                    'moatOK': r.get('moatOK'), 'irr': r.get('irr'), 'kills': r.get('kills'), 'exit': r.get('exit'),
                    'blockers': [] if r.get('buy') or r.get('quali') else blockers(r)}
    return {'status': '台帳に無い'}


# ───────────────────────── 各人の保有を作る ─────────────────────────
DEP_FRAC_RE = re.compile(r'\bDEP(OSITARY)?\s*SH[A-Z]*\b.*\b(RP|REP|REPSTG|REPR)\w*\s*1/\d+', re.I)


def classify(r, figi):
    """1行 → ('option'|'prn'|'noncommon'|'equity', 理由)"""
    if (r.get('putCall') or '').strip():
        return 'option', 'putCall=' + r['putCall']
    if (r.get('sshPrnamtType') or '').upper() == 'PRN':
        return 'prn', 'sshPrnamtType=PRN（元本額＝社債など）'
    tt = r.get('titleOfClass') or ''
    if NONCOMMON_RE.search(tt):
        return 'noncommon', 'titleOfClass=' + tt
    if DEP_FRAC_RE.search(tt):
        return 'noncommon', 'titleOfClass=' + tt + '（1株の何分の1を表す預託株式＝優先株の預託）'
    f = figi.get(norm_cusip(r.get('cusip')) or '') or {}
    if f.get('securityType') in NONEQ_TYPES:
        return 'noncommon', 'OpenFIGI securityType=' + str(f.get('securityType'))
    if f.get('securityType2') in ('Preferred Stock', 'Warrant', 'Right') or f.get('marketSector') in ('Pfd', 'Corp', 'Govt', 'Mtge', 'Muni'):
        return 'noncommon', f"OpenFIGI securityType2={f.get('securityType2')} marketSector={f.get('marketSector')}（題名は {tt}）"
    if PREF_NAME_RE.search(r.get('nameOfIssuer') or '') and not re.search(r'\b(COM|ORD|SHS|ADR|ADS)\b', tt, re.I):
        return 'noncommon', 'nameOfIssuer に優先株の語・titleOfClass=' + tt
    return 'equity', ''


def is_fund(r, figi):
    f = figi.get(norm_cusip(r.get('cusip')) or '') or {}
    if f and 'none' not in f:
        return f.get('securityType') in FUND_TYPES or f.get('securityType2') in ('Mutual Fund', 'ETP')
    return bool(ETF_RE.search((r.get('nameOfIssuer') or '') + ' ' + (r.get('titleOfClass') or '')))


def build_people():
    cj = load_ciks()
    rh = raw_holdings()
    cons = consensus_prices()
    figi, _ = load_figi()
    names = sec_tickers()
    plan = json.load(open(os.path.join(CACHE, 'plan.json')))
    dsck = ds_rows_for([a for v in rh.values() for a in v['accs']])
    people = {}
    cusip_ticker = {}
    for c in cj['ciks']:
        code = c['code']
        v = rh[code]
        pl = plan[code]
        files = [{'acc': a, 'url': (pl['files'].get(a) or {}).get('url')} for a in v['accs']]
        # 検算: XML とデータセットの行数・合計額（同じ受付番号）
        xml_n = len(v['rows']); xml_v = sum(float(r.get('value') or 0) for r in v['rows'])
        ds = [dsck.get(a) for a in v['accs']]
        if all(d is not None for d in ds) and ds:
            ds_n = sum(d[0] for d in ds); ds_v = sum(d[1] for d in ds)
            check = {'xml_rows': xml_n, 'dataset_rows': ds_n, 'xml_value_raw': xml_v, 'dataset_value_raw': ds_v,
                     'match': ds_n == xml_n and abs(ds_v - xml_v) <= 1}
        else:
            check = {'xml_rows': xml_n, 'xml_value_raw': xml_v, 'dataset': '同じ受付番号がデータセットに無い（期間外の提出）'}
        kinds = Counter(); kval = defaultdict(float)
        eq = []; nsf = []
        for r in v['rows']:
            k, why = classify(r, figi)
            try:
                val = float(r.get('value') or 0); sh = float(r.get('sshPrnamt') or 0)
            except Exception:  # noqa
                val, sh = 0.0, 0.0
            if k == 'equity' and is_fund(r, figi):
                f = figi.get(norm_cusip(r.get('cusip')) or '') or {}
                if NONSTOCK_FUND_RE.search(f"{f.get('name') or ''} {r.get('titleOfClass') or ''} {r.get('nameOfIssuer') or ''}"):
                    k = 'nonstock_fund'
                    nsf.append({'ticker': norm_ticker(f.get('ticker')), 'name': f.get('name') or r.get('nameOfIssuer'), 'title': r.get('titleOfClass'), 'value_raw': val})
            kinds[k] += 1; kval[k] += val
            if k == 'equity' and val > 0:
                eq.append((r, val, sh))
        # 単位: 全提出者の CUSIP ごとの株価の中央値と比べ、10 のべきで揃える（千ドル単位の申告は ×1000）
        lr = []
        for r, val, sh in eq:
            cu = norm_cusip(r.get('cusip'))
            if cu in cons and sh > 0 and cons[cu][0] > 0:
                lr.append(math.log10((val / sh) / cons[cu][0]))
        kpow = round(S.median(lr)) if lr else 0
        scale = 10 ** (-kpow)
        iss = {}
        for r, val, sh in eq:
            cu = norm_cusip(r.get('cusip')) or ('X' + (r.get('cusip') or '?'))
            fund = is_fund(r, figi)
            # ETF は同じ信託（例 iShares Trust 464287）の中に別のファンドが並ぶので、発行体でまとめず CUSIP ごとに分ける
            i6 = cu if fund else cu[:6]
            x = iss.setdefault(i6, {'issuer6': i6, 'value': 0.0, 'classes': {}, 'fund': False})
            x['value'] += val * scale
            cl = x['classes'].setdefault(cu, {'cusip': cu, 'title': r.get('titleOfClass'), 'name': r.get('nameOfIssuer'),
                                             'value': 0.0, 'shares': 0.0})
            cl['value'] += val * scale; cl['shares'] += sh
            if fund:
                x['fund'] = True
        tot = sum(x['value'] for x in iss.values())
        for x in iss.values():
            cls = sorted(x['classes'].values(), key=lambda q: -q['value'])
            tks = []
            src = None
            for q in cls:
                f = figi.get(q['cusip']) or {}
                t = norm_ticker(f.get('ticker')) if f and 'none' not in f else None
                if t:
                    tks.append(t); src = src or 'OpenFIGI'
                cusip_ticker[q['cusip']] = t
            if not tks:
                nm0 = cls[0]['name'] or ''
                cand = names.get(norm_name(re.sub(r'\(.*?\)', ' ', nm0))) or names.get(norm_name(nm0)) or []
                if len(cand) >= 1:
                    tks = [cand[0]]; src = 'SEC company_tickers の名前照合（OpenFIGI で引けない CUSIP）'
            x['name'] = cls[0]['name']
            x['ticker'] = tks[0] if tks else None
            x['tickers'] = sorted(set(tks))
            x['ticker_src'] = src
            x['classes'] = [{k2: (round(v2) if k2 in ('value', 'shares') else v2) for k2, v2 in q.items()} for q in cls]
            x['w'] = x['value'] / tot if tot > 0 else None
        hold = sorted(iss.values(), key=lambda q: -q['value'])
        for rk, x in enumerate(hold, 1):
            x['rank'] = rk
        period = 'Q2 2026（2026-06-30）' if c['has_2026_06_30_13f_hr'] else (c.get('last_period') or '?') + '（最新の 13F-HR）'
        people[code] = {
            'code': code, 'name': c['name'], 'filer_name': c['filer_name'], 'cik': c['cik'],
            'period': period, 'filings': files, 'filing_choice': v['why'], 'xml_vs_dataset': check,
            'row_kinds': {k: {'rows': kinds[k], 'value_raw': kval[k]} for k in kinds},
            'nonstock_funds_excluded': nsf,
            'unit_power': kpow, 'unit_note': ('申告は千ドル単位 → ×1000' if kpow == -3 else ('ドル単位' if kpow == 0 else f'10^{kpow} ずれ → 補正')),
            'unit_rows_compared': len(lr),
            'equity_total_usd': round(tot), 'n_issuers': len(hold),
            'n_funds': sum(1 for x in hold if x['fund']), 'fund_weight': round(sum(x['w'] for x in hold if x['fund']), 6) if tot else None,
            'unmapped_weight': round(sum(x['w'] for x in hold if not x['ticker']), 6) if tot else None,
            'unmapped': [{'name': x['name'], 'issuer6': x['issuer6'], 'w': round(x['w'], 6)} for x in hold if not x['ticker']],
            'dataroma': {'n_stocks': c['dataroma'].get('dr_n_stocks'), 'value_usd': c['dataroma'].get('dr_value_usd'),
                         'period': c['dataroma'].get('dr_period'), 'url': c['dataroma'].get('url')},
            'holdings': hold,
        }
    return people, cusip_ticker



# ───────────────────────── 公表された長期の成績（出典つき・手で読んで写した） ─────────────────────────
# status: primary=運用者自身の手紙・報告書・ファンドのページで数字を確かめた / secondary=報道・ポッドキャストの紹介文だけ
#         （一次資料は取れなかった）/ unverifiable=公表された年率が見つからない（非公開のファンド・家族の資産）
# ann は年率（%）。bench は同じ期間の比べる指数（運用者が自分で載せたもの。'calc' の印は同じ出典の年ごとの表から計算）
TRACK = [
    {'code': 'BRK', 'person': 'Warren Buffett', 'vehicle': 'Berkshire Hathaway の1株あたり株価（市場価格）', 'from': '1965', 'to': '2025-12-31',
     'ann': 19.7, 'bench_name': 'S&P 500（配当込み）', 'bench_ann': 10.5,
     'sub': [{'from': '2006', 'to': '2025', 'ann': 11.3, 'bench_ann': 11.0, 'how': 'calc: 同じ手紙の年ごとの表から複利で計算'},
             {'from': '2016', 'to': '2025', 'ann': 14.3, 'bench_ann': 14.8, 'how': 'calc: 同上', 'recent': True}],
     'status': 'primary', 'url': 'https://www.berkshirehathaway.com/letters/2025ltr.pdf',
     'quote': 'Compounded Annual Gain – 1965-2025 … 19.7% / 10.5%（Berkshire\'s Performance vs. the S&P 500 の表）'},
    {'code': 'FS', 'person': 'Terry Smith', 'vehicle': 'Fundsmith Equity Fund T Class Acc（英ポンド・手数料後）', 'from': '2010-11-01', 'to': '2025-12-31',
     'ann': 13.8, 'bench_name': 'MSCI World（英ポンド・配当込み）', 'bench_ann': 12.1,
     'sub': [{'from': '2025', 'to': '2025', 'ann': 0.8, 'bench_ann': 12.8, 'how': '暦年 2025'}],
     'status': 'primary', 'url': 'https://www.fundsmith.co.uk/media/4hcfd1pg/2025-fef-annual-letter-web.pdf',
     'quote': 'Inception to 31st Dec 2025 Annualised +13.8（Equities +12.1）・2025 年 +0.8（+12.8）', 'note': '通貨は英ポンド（S&P 500 とは直接比べられない）'},
    {'code': 'AC', 'person': 'Chuck Akre（現在は Chris Cerrone ほか）', 'vehicle': 'Akre Focus ETF の基準価額（2025-10-24 より前は前身の Akre Focus Fund）', 'from': '2009-08-31', 'to': '2026-06-30',
     'ann': 12.61, 'bench_name': 'S&P 500 TR', 'bench_ann': 14.69,
     'sub': [{'from': '10年', 'to': '2026-06-30', 'ann': 11.07, 'bench_ann': 15.51, 'how': '同じ表の 10 YR', 'recent': True}],
     'status': 'primary', 'url': 'https://www.akrefund.com/semi-annual-investor-call-replay-may-2026/',
     'quote': 'Average Annual Returns % as of 06/30/26 … SINCE INCEPT. NAV 12.61% / S&P 500 TR 14.69%'},
    {'code': 'psc', 'person': 'Bill Ackman', 'vehicle': 'Pershing Square, L.P.→Pershing Square Holdings（手数料後の基準価額）', 'from': '2004-01-01', 'to': '2026-02-10',
     'ann': 15.9, 'bench_name': 'S&P 500', 'bench_ann': 10.7,
     'sub': [{'from': '2012-12-31', 'to': '2026-02-10', 'ann': 12.9, 'bench_ann': 14.9, 'how': 'PSH の上場から（同じ報告書）・約13年', 'recent': True}],
     'status': 'primary', 'url': 'https://assets.pershingsquareholdings.com/wp-content/uploads/2026/02/18175039/Pershing-Square-Holdings-Ltd.-2025-Annual-Report.pdf',
     'quote': 'January 1, 2004–February 10, 2026 Compound Annual Return 15.9 %（S&P 500 10.7 %）・December 31, 2012–February 10, 2026 12.9 %（14.9 %）'},
    {'code': 'pcm', 'person': 'Polen Capital（Focus Growth）', 'vehicle': 'Polen Focus Growth コンポジット（手数料後）', 'from': '1989-01-01', 'to': '2026-06-30',
     'ann': 12.76, 'bench_name': 'S&P 500', 'bench_ann': 11.43,
     'sub': [{'from': '10年', 'to': '2026-06-30', 'ann': 11.66, 'bench_ann': 15.50, 'how': '同じ表の 10 Yr（Net）', 'recent': True}],
     'status': 'primary', 'url': 'https://www.polencapital.com/strategies/growth-sma',
     'quote': 'Polen Focus Growth (Net) … 10 Yr 11.66 Inception 12.76 / S&P 500 Index 15.50 / 11.43（As of 06-30-2026・Inception Date 01-01-1989）'},
    {'code': 'LT', 'person': 'Nick Train・Michael Lindsell', 'vehicle': 'Lindsell Train Global Equity Fund A（英ポンド・手数料後）', 'from': '2011-03-16', 'to': '2026-06-30',
     'ann': 10.4, 'bench_name': 'MSCI World（英ポンド）', 'bench_ann': 12.5,
     'sub': [{'from': '10年', 'to': '2026-06-30', 'ann': 7.5, 'bench_ann': 13.2, 'how': '同じ表の 10 Yrs（英ポンド・MSCI World）', 'recent': True}],
     'status': 'primary', 'url': 'https://www.prescient.co.za/media/n5ffzwip/mdd_lt-global-equity-fund-class-a-gbp_30_jun_2026.pdf',
     'quote': 'A Class (£), Dist. … 10 Yrs 7.5 / Since Inception 10.4・MSCI World Index (£) 13.2 / 12.5', 'note': '通貨は英ポンド'},
    {'code': 'MKL', 'person': 'Thomas Gayner', 'vehicle': 'Markel の株式の運用（equity securities の総合リターン）', 'from': '2006', 'to': '2025-12-31',
     'ann': 11.0, 'bench_name': 'S&P 500（配当込み・同じ暦年を Berkshire の表から計算）', 'bench_ann': 11.0,
     'sub': [{'from': '2016', 'to': '2025', 'ann': 13.5, 'bench_ann': 14.8, 'how': '10年（Markel の発表）・比べる指数は calc', 'recent': True}],
     'status': 'primary', 'url': 'https://s202.q4cdn.com/749045284/files/doc_news/Markel-Group-reports-2025-financial-results-2026.pdf',
     'quote': 'Return on equity securities … Ten-year annual return 13.5 % / Twenty-year annual return 11.0 %', 'note': 'Markel 自身は指数との比較を載せていない（比べる指数は私の計算）'},
    {'code': 'GC', 'person': 'François Rochon', 'vehicle': 'Rochon US Portfolio（米ドル）', 'from': '1993-07-01', 'to': '2025-12-31',
     'ann': 13.9, 'bench_name': 'S&P 500', 'bench_ann': 10.8,
     'sub': [{'from': '1993-07-01', 'to': '2025-12-31', 'ann': 14.7, 'bench_ann': 9.9, 'how': 'Rochon Global Portfolio（加ドル・混合指数）'},
             {'from': '2025', 'to': '2025', 'ann': 7.6, 'bench_ann': 17.9, 'how': '暦年 2025（US Portfolio）'}],
     'status': 'primary', 'url': 'https://givernycapital.com/wp-content/uploads/2026/03/giverny-capital-annual-letter-2025-1.pdf',
     'quote': 'Since its inception in 1993, the Rochon US Portfolio has returned 6839%, or 13.9% on an annualized basis. … S&P 500 … 10.8%',
     'note': '手数料の前か後かは手紙の付録で未確認。ポッドキャスト（TIP800）は『手数料後 13.4%・S&P 500 10.8%』と紹介'},
    {'code': 'HA', 'person': 'Bill Nygren', 'vehicle': 'Oakmark Fund（OAKMX・手数料後）', 'from': '1991-08-05', 'to': '2026-09-30',
     'ann': 12.67, 'bench_name': 'S&P 500', 'bench_ann': 11.01,
     'sub': [{'from': '10年', 'to': '2026-09-30', 'ann': 13.08, 'bench_ann': 15.33, 'how': '同じ表の 10YR', 'recent': True}],
     'status': 'primary', 'url': 'https://oakmark.com/our-funds/oakmark-fund/',
     'quote': 'Returns % as of 09/30/2026 … 10YR 13.08% Since Inception 12.67% / S&P 500 Index 15.33% 11.01%'},
    {'code': 'RC', 'person': 'Ruane Cunniff（Sequoia Fund）', 'vehicle': 'Sequoia Fund（手数料後）', 'from': '1970-07-15', 'to': '2026-09-30',
     'ann': 13.28, 'bench_name': 'S&P 500', 'bench_ann': 11.55,
     'sub': [{'from': '10年', 'to': '2026-09-30', 'ann': 12.24, 'bench_ann': 15.32, 'how': '同じ表の 10 YEARS', 'recent': True}],
     'status': 'primary', 'url': 'https://www.sequoiafund.com/performance/',
     'quote': 'Net Returns as of September 30, 2026 … 10 YEARS 12.24% SINCE INCEPTION 13.28% / S&P 500 15.32% 11.55%'},
    {'code': 'SA', 'person': 'Christopher Bloomstran', 'vehicle': 'Semper Augustus の株式（コンポジット）', 'from': '1999-02-28', 'to': '2023 年末ごろ（紹介文に明記なし）',
     'ann': 11.5, 'bench_name': 'S&P 500', 'bench_ann': 7.6, 'status': 'secondary',
     'url': 'https://www.theinvestorspodcast.com/episodes/berkshire-hathaway-w-chris-bloomstran',
     'quote': 'a compounded annual growth rate of 11.5% on equities since his fund\'s inception on 2/28/1999 … compared to 7.6% for the S&P500（2024-04-20 の回の紹介文）',
     'note': '会社の手紙（semperaugustus.com）は取得できなかった（403）'},
    {'code': 'GR', 'person': 'Thomas Russo', 'vehicle': 'Semper Vic Partners, L.P.', 'from': '1990-07-16', 'to': '2023 年末（2023 年の通年の手紙）',
     'ann': 11.3, 'bench_name': 'S&P 500', 'bench_ann': 10.2, 'status': 'secondary',
     'url': 'https://hedgefundalpha.com/strategies/secrets-to-tom-russo-decades-long-success-lessons/',
     'quote': 'cumulatively returned 3,444.8% since July 16, 1990 … compound annual growth rate of 11.3% … S&P 500 … 10.2%',
     'note': '手数料の前か後かは書かれていない。一次資料（投資家への手紙）は取れなかった'},
    {'code': 'PI', 'person': 'Mohnish Pabrai', 'vehicle': 'Pabrai Investment Funds の旗艦ファンド', 'from': '1999（2000 とする資料もある）', 'to': '2024 年春',
     'ann': 11.7, 'bench_name': 'S&P 500', 'bench_ann': None, 'status': 'secondary',
     'url': 'https://www.theinvestorspodcast.com/the-inner-scorecard-w-mohnish-pabrai/',
     'quote': 'returned 11.7% annualized since inception in 1999 … 4 percentage point more than S&P 500 … $12.51 compared to $4.72（2024-05-04 の回）',
     'note': 'S&P 500 の年率は『約4ポイント下』としか書かれていない'},
    {'code': 'aq', 'person': 'Guy Spier', 'vehicle': 'Aquamarine Fund', 'from': '1997-09', 'to': '2025-12-31',
     'ann': 9.4, 'bench_name': 'S&P 500', 'bench_ann': 9.2, 'status': 'secondary',
     'url': 'https://www.opalesque.com/713551/Guy_Spier_winds_down_Aquamarine_Fund_after_28355.html',
     'quote': 'has compounded at 9.4% annually … edging out the S&P 500\'s 9.2% … For 2025, Aquamarine returned 11.3% versus 17.9%（2026-02-16 の記事）',
     'note': '外部の投資家向けのファンドを閉じて家族の資産へ（同じ記事）'},
    {'code': 'HC', 'person': 'Li Lu', 'status': 'unverifiable', 'note': 'Himalaya Capital は成績を公表していない（報道の数字はあるが一次資料なし）'},
    {'code': 'tci', 'person': 'Chris Hohn', 'status': 'unverifiable', 'note': 'TCI Fund Management は成績を公表していない（報道の数字・LCH の運用益の順位はあるが、年率の一次資料なし）'},
    {'code': 'BAUPOST', 'person': 'Seth Klarman', 'status': 'unverifiable', 'note': 'Baupost は非公開のファンドで成績を公表していない'},
    {'code': 'VFC', 'person': 'Dev Kantesaria', 'status': 'unverifiable', 'note': 'Valley Forge は成績を公表していない'},
    {'code': 'GLC', 'person': 'Josh Tarasoff', 'status': 'unverifiable', 'note': 'Greenlea Lane は成績を公表していない'},
    {'code': 'CCM', 'person': 'Glenn Greenberg', 'status': 'unverifiable', 'note': 'Brave Warrior Advisors は成績を公表していない'},
    {'code': 'SAM', 'person': 'Michael Burry', 'status': 'unverifiable', 'note': 'Scion は成績を公表しておらず、2025-09-30 の 13F を最後に提出が止まっている'},
    {'code': 'HH', 'person': 'Duan Yongping', 'status': 'unverifiable', 'note': 'H&H は個人の資産の運用で成績を公表していない'},
]
NOT_IN_LIST = [{'person': 'Stanley Druckenmiller', 'why': 'Dataroma の一覧（事前登録の83件）に無いので書かない（作業指示どおり）'}]


# ───────────────────────── まとめる ─────────────────────────
def r6(x):
    return None if x is None else round(x, 6)


def consensus(people, main_codes, G):
    agg = {}
    N = len(main_codes)
    # 記号 → 発行体の鍵（OpenFIGI で引けた行の多数決）。CUSIP の打ち間違い（実例 GA の General Motors 35045V）でも
    # 名前の照合で記号が分かれば、同じ会社として数える
    t2k = defaultdict(Counter)
    for code in main_codes:
        for x in people[code]['holdings']:
            if x['ticker'] and x['ticker_src'] == 'OpenFIGI':
                t2k[x['ticker']][x['issuer6']] += 1
    for code in main_codes:
        P = people[code]
        for x in P['holdings']:
            key = x['issuer6']
            if x['ticker'] and x['ticker_src'] != 'OpenFIGI' and t2k.get(x['ticker']):
                key = t2k[x['ticker']].most_common(1)[0][0]
            a = agg.setdefault(key, {'issuer6': key, 'name': x['name'], 'tickers': set(), 'fund': x['fund'],
                                     'holders': [], 'top10': [], 'w_sum': 0.0, 'value_usd': 0.0})
            a['tickers'].update(x['tickers'])
            if not a.get('ticker') and x['ticker']:
                a['ticker'] = x['ticker']
            a['holders'].append({'code': code, 'w': r6(x['w']), 'rank': x['rank']})
            if x['rank'] <= TOPN:
                a['top10'].append(code)
            a['w_sum'] += x['w']; a['value_usd'] += x['value']
    out = []
    for a in agg.values():
        ws = [h['w'] for h in a['holders']]
        out.append({'issuer6': a['issuer6'], 'name': a['name'], 'ticker': a.get('ticker'), 'tickers': sorted(a['tickers']),
                    'fund': a['fund'], 'n_holders': len(a['holders']), 'n_top10': len(a['top10']),
                    'mean_w_holders': r6(S.mean(ws)), 'median_w_holders': r6(S.median(ws)),
                    'mean_w_all': r6(a['w_sum'] / N), 'value_usd_sum': round(a['value_usd']),
                    'top10_of': sorted(a['top10']),
                    'holders': sorted(a['holders'], key=lambda h: -h['w'])})
    stocks = [x for x in out if not x['fund']]
    by_holders = sorted(stocks, key=lambda x: (-x['n_holders'], -x['n_top10'], -x['mean_w_holders']))
    by_top10 = sorted(stocks, key=lambda x: (-x['n_top10'], -x['n_holders'], -x['mean_w_holders']))
    by_meanw_all = sorted(stocks, key=lambda x: -x['mean_w_all'])
    for lst in (by_holders, by_top10, by_meanw_all):
        for x in lst[:CONS_N]:
            if 'gate' not in x:
                x['gate'] = gate_info(x['tickers'] or ([x['ticker']] if x['ticker'] else []), G)
    funds = sorted([x for x in out if x['fund']], key=lambda x: -x['n_holders'])
    return out, by_holders, by_top10, by_meanw_all, funds


def slim(x, keep_holders=True):
    d = {k: x[k] for k in ('name', 'ticker', 'tickers', 'n_holders', 'n_top10', 'mean_w_holders', 'median_w_holders', 'mean_w_all',
                           'value_usd_sum', 'top10_of') if k in x}
    if 'gate' in x:
        d['gate'] = x['gate']
    if keep_holders:
        d['holders'] = x['holders'][:40]
    return d


def main():
    pre = json.load(open(PREREG))
    G = gate_rows()
    people, _ = build_people()
    cj = load_ciks()
    # 外す人（名指し・理由つき）
    excluded, stale, main_codes = [], [], []
    for c in cj['ciks']:
        code = c['code']; P = people[code]
        if code == 'MP':
            excluded.append({'code': code, 'name': c['name'], 'why': '最後の 13F-HR（2026-03-31・受付 0001540866-26-000002）は保有0行・0ドル＝米国株の保有を報告していない。'
                             '2026-06-30 の 13F も無い（保有のある最後は 2025-12-31 の11行・約1.28億ドル）'})
            continue
        if not c['has_2026_06_30_13f_hr']:
            stale.append(code)
            continue
        if P['equity_total_usd'] <= 0:
            excluded.append({'code': code, 'name': c['name'], 'why': '株の保有が0'})
            continue
        main_codes.append(code)
    allc, by_h, by_t, by_w, funds = consensus(people, main_codes, G)
    # 各人の上位10＋門
    per = []
    for code in [c['code'] for c in cj['ciks']]:
        P = people[code]
        if any(e['code'] == code for e in excluded):
            continue
        top = []
        for x in P['holdings'][:TOPN]:
            top.append({'rank': x['rank'], 'name': x['name'], 'ticker': x['ticker'], 'w': r6(x['w']), 'value_usd': round(x['value']),
                        'fund': x['fund'], 'classes': [q['cusip'] for q in x['classes']],
                        'gate': gate_info(x['tickers'] or ([x['ticker']] if x['ticker'] else []), G)})
        ws = [x['w'] for x in P['holdings']]
        per.append({k: P[k] for k in ('code', 'name', 'filer_name', 'cik', 'period', 'filings', 'filing_choice', 'xml_vs_dataset',
                                      'row_kinds', 'nonstock_funds_excluded', 'unit_power', 'unit_note', 'equity_total_usd', 'n_issuers', 'n_funds',
                                      'fund_weight', 'unmapped_weight', 'unmapped', 'dataroma')}
                   | {'in_consensus': code in main_codes,
                      'period_note': None if code in main_codes else '2026-06-30 の 13F が無い → 最新（2025-09-30）を使った。合意の数には入れない（今の保有ではないため）',
                      'top10_weight': r6(sum(sorted(ws, reverse=True)[:TOPN])), 'top1_weight': r6(max(ws)) if ws else None,
                      'top10': top})
    # 門の投下可・次点の社を何人が持っているか（逆向き）
    idx = {}
    for x in allc:
        for t in x['tickers']:
            idx[t] = x
    alias = {'GOOGL': ['GOOGL', 'GOOG']}
    rev = []
    for r in sorted(G.values(), key=lambda r: -(r.get('s') or 0)):
        if not (r.get('buy') or r.get('quali')):
            continue
        x = None
        for t in alias.get(r['t'], [r['t']]):
            x = x or idx.get(t)
        rev.append({'gate_ticker': r['t'], 'status': '投下可' if r.get('buy') else '次点', 'omega': r.get('s'), 'moat': r.get('moat'),
                    'n_holders': x['n_holders'] if x else 0, 'n_top10': x['n_top10'] if x else 0,
                    'mean_w_holders': x['mean_w_holders'] if x else None,
                    'holders': [h for h in x['holders']][:15] if x else []})
    # 合意の上位30と門の重なりの数え
    def gate_count(lst):
        c = Counter((x.get('gate') or {}).get('status', '?') for x in lst[:CONS_N])
        return dict(c)
    top10_gate = Counter()
    for p_ in per:
        if not p_['in_consensus']:
            continue
        for x in p_['top10']:
            top10_gate[x['gate']['status']] += 1
    # 全体の数え
    inc = [people[c] for c in main_codes]
    unm = [p_['unmapped_weight'] for p_ in inc if p_['unmapped_weight'] is not None]
    tot_all = sum(p_['equity_total_usd'] for p_ in inc)
    unm_val = sum(p_['unmapped_weight'] * p_['equity_total_usd'] for p_ in inc if p_['unmapped_weight'] is not None)
    dr_cmp = []
    for p_ in inc:
        dn, dv = p_['dataroma']['n_stocks'], p_['dataroma']['value_usd']
        dr_cmp.append({'code': p_['code'], 'n_issuers': p_['n_issuers'], 'dataroma_n': dn,
                       'value_usd': p_['equity_total_usd'], 'dataroma_value_usd': dv,
                       'value_ratio': round(p_['equity_total_usd'] / dv, 4) if dv else None})
    xml_ok = sum(1 for p_ in people.values() if p_['xml_vs_dataset'].get('match'))
    stats = {
        'n_list': len(cj['ciks']), 'n_in_consensus': len(main_codes), 'n_excluded': len(excluded), 'n_stale_latest_used': len(stale),
        'equity_total_usd_all': round(tot_all),
        'unmapped_value_share_all': round(unm_val / tot_all, 6) if tot_all else None,
        'unmapped_weight_median_person': r6(S.median(unm)) if unm else None,
        'unmapped_weight_max_person': max(((p_['code'], p_['unmapped_weight']) for p_ in inc), key=lambda q: q[1]) if inc else None,
        'n_issuers_median': S.median([p_['n_issuers'] for p_ in inc]),
        'top10_weight_median': r6(S.median([sum(sorted([x['w'] for x in p_['holdings']], reverse=True)[:TOPN]) for p_ in inc])),
        'n_people_with_funds': sum(1 for p_ in inc if p_['n_funds']),
        'xml_vs_dataset_exact_match': f'{xml_ok}/{len(people)}',
        'unit_thousand_filers': sorted(p_['code'] for p_ in people.values() if p_['unit_power'] == -3),
        'dataroma_n_exact': sum(1 for d in dr_cmp if d['n_issuers'] == d['dataroma_n']),
        'dataroma_value_within_1pct': sum(1 for d in dr_cmp if d['value_ratio'] and abs(d['value_ratio'] - 1) <= 0.01),
        'consensus_top30_gate_by_holders': gate_count(by_h),
        'consensus_top30_gate_by_top10': gate_count(by_t),
        'per_person_top10_gate': dict(top10_gate),
        'n_distinct_stocks': sum(1 for x in allc if not x['fund']),
    }
    # 公表された成績のまとめ（一次資料で確かめたものだけ）
    prim = [t for t in TRACK if t['status'] == 'primary']
    full_beat = [t['code'] for t in prim if t.get('bench_ann') is not None and t['ann'] > t['bench_ann'] + 0.05]
    full_tie = [t['code'] for t in prim if t.get('bench_ann') is not None and abs(t['ann'] - t['bench_ann']) <= 0.05]
    full_lose = [t['code'] for t in prim if t.get('bench_ann') is not None and t['ann'] < t['bench_ann'] - 0.05]
    rec = [(t['code'], q) for t in prim for q in t.get('sub', []) if q.get('recent')]
    track_summary = {
        'n_primary': len(prim), 'n_secondary': sum(1 for t in TRACK if t['status'] == 'secondary'),
        'n_unverifiable': sum(1 for t in TRACK if t['status'] == 'unverifiable'),
        'full_period_beat': full_beat, 'full_period_tie': full_tie, 'full_period_lose': full_lose,
        'recent_about_10y': [{'code': c_, 'ann': q['ann'], 'bench_ann': q['bench_ann'], 'diff': round(q['ann'] - q['bench_ann'], 2), 'how': q['how']} for c_, q in rec],
        'recent_beat': sum(1 for _, q in rec if q['ann'] > q['bench_ann']), 'recent_n': len(rec),
        'recent_median_diff': round(S.median([q['ann'] - q['bench_ann'] for _, q in rec]), 2) if rec else None,
        'note': '一次資料で確かめた運用の多くは、始めてからの通算では指数に勝っているが、直近およそ10年（Pershing Square は PSH 上場からの約13年）では全部が指数に負けている。'
                '通算の勝ちは、有名になる前の早い時期の大きな勝ちに支えられている（R6 の持続性の問いと同じ向き）',
    }
    out = {
        'meta': {'name': 'bestpf R1: 成績の良い投資家たちは今なにを持っているか（2026-06-30 の 13F）',
                 'made': time.strftime('%Y-%m-%d'),
                 'prereg': 'out/bestpf_prereg.json（コミット 7c4b672）modules.R1_superinvestors_now',
                 'prereg_q': pre['modules']['R1_superinvestors_now'],
                 'code': 'night/bestpf_superinvestors_now.py（--fetch → --figi → 既定）',
                 'inputs': {'ciks': 'out/_bestpf_cache/ciks.json（R0・night/bestpf_ciks.py）',
                            'edgar_infotable': 'https://www.sec.gov/Archives/edgar/data/<cik>/<受付番号>/<情報表>.xml（各人の filings[].url）',
                            'sec_13f_dataset': DS_URL + '（検算・単位・修正の種類だけに使う）',
                            'openfigi': 'https://api.openfigi.com/v3/mapping（ID_CUSIP・外国の CINS は ID_CINS）',
                            'sec_company_tickers': TICKERS_URL, 'gate': 'out/score_all.json（読むだけ）'},
                 'rules': {
                     'stock_only': 'putCall のある行・sshPrnamtType=PRN・titleOfClass が優先株/社債/ワラント/権利（mw_best_ideas_13f.NONCOMMON_RE）・'
                                   '1株の何分の1を表す預託株式（優先株の預託）・OpenFIGI の種類が Preference/Warrant/Right 等を除く',
                     'funds': '株の ETF・投資信託の持分は比重に残し fund=true と印す（合意の順位〔上位30〕は個別株だけで作る）。'
                              '株でない器の ETF（金・銀の現物・商品・国債/社債/地方債・暗号資産＝NONSTOCK_FUND_RE）は比重から外し nonstock_funds_excluded に名指し',
                     'issuer': '同じ発行体（CUSIP の先頭6桁）の株の種類はまとめる（GOOGL+GOOG・BRK-A+BRK-B 等）',
                     'weight': '比重＝その発行体の評価額 ÷ その人の 13F の株の評価額の合計（オプション・社債・優先株を除いた後）',
                     'units': 'データセットの全提出者の CUSIP ごとの株価（値÷株数）の中央値と比べ、各人の申告の単位を 10 のべきで揃える（千ドル単位の申告は ×1000）',
                     'consensus_set': '2026-06-30 の 13F-HR があり、株の保有がある人だけ（Scion は 2025-09-30 が最後なので数に入れず、各人の表には載せる）',
                     'consensus_rank': '主＝持っている人数→上位10に入れている人数→持っている人の中の平均比重。副＝上位10に入れている人数の順・全員の平均比重（持っていない人は0）の順',
                     'gate': 'score_all.json の buy=投下可・quali かつ buy でない=次点・それ以外で台帳にある=台帳（関門で落ちる・落ちる理由は score_all.js の blockers と同じ並び＋Ω75未満）',
                 },
                 'limits': [
                     '13F は米国に上場する株（と ADR・ETF）の買いの持ち高だけ。空売り・米国外の株・現金・債券・非上場は見えない＝その人の資産の全部ではない',
                     '2026-06-30 時点の保有で、提出は 2026-07〜08 月。今日（2026-10-12）までに売買している可能性がある',
                     '一覧（Dataroma）はサイトの運営者が後から選んだ『有名な運用者』＝成績の良かった人に偏る（生き残りの偏り）',
                     '大きく分散した運用会社（First Eagle 421 銘柄・Mairs & Power・Dodge & Cox・Polen 等）は『持っている』の数を増やす。上位10の数え（n_top10）も並べた',
                     'Berkshire など保険会社・財団の 13F には運用者本人の判断でない持分（子会社の運用・寄付された株）が混じることがある'],
                 },
        'summary_stats': stats,
        'excluded': excluded,
        'stale_latest_used': [{'code': c, 'name': people[c]['name'], 'period': '2025-09-30（Q3 2025）',
                               'filing': people[c]['filings'], 'why': '2026-06-30 の 13F-HR が無い（最後の提出は 2025-11-03）。作業指示どおり最新を使い期間を明記。合意の数には入れない'}
                              for c in stale],
        'consensus_top30_by_holders': [slim(x) for x in by_h[:CONS_N]],
        'consensus_top30_by_top10': [slim(x) for x in by_t[:CONS_N]],
        'consensus_top30_by_mean_weight_all': [slim(x, False) for x in by_w[:CONS_N]],
        'funds_held': [slim(x) for x in funds[:20]],
        'gate_buy_next_held_by': rev,
        'people': per,
        'track_records': TRACK,
        'track_summary': track_summary,
        'track_records_not_in_list': NOT_IN_LIST,
        'dataroma_compare': dr_cmp,
    }
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    for x in by_h[:CONS_N]:
        g = x.get('gate', {})
        print(f"{x['ticker'] or '?':<7} {x['name'][:28]:<28} 人数{x['n_holders']:>3} 上位10{x['n_top10']:>3} 平均比重{x['mean_w_holders']*100:5.1f}% 門:{g.get('status')} Ω{g.get('omega')}")


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--fetch' in a:
        fetch()
    if '--figi' in a:
        rh = raw_holdings()
        cs = set()
        for v in rh.values():
            for r in v['rows']:
                cu = norm_cusip(r.get('cusip'))
                if cu and not (r.get('putCall') or '').strip():
                    cs.add(cu)
        print('CUSIP', len(cs))
        figi_map(cs)
    if not a:
        main()
