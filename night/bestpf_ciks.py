#!/usr/bin/env python3
"""night/bestpf_ciks.py — bestpf R0: Dataroma の Superinvestors 83件の 13F-HR 提出者の CIK を解決する（読むだけ）

事前登録: out/bestpf_prereg.json（7c4b672）の dataroma_list（83件）。出力 out/_bestpf_cache/ciks.json
（他の担当 R1/R2 がこれを読む）。門・採点・配分には触れない。

やり方（3つの独立した手がかりを突き合わせる）
  1. Dataroma の各人のページ（https://www.dataroma.com/m/holdings.php?m=<code>）から
     名前・Period・Portfolio date・No. of stocks・Portfolio value を読む。
  2. SEC の Form 13F データセット（01jun2026-31aug2026_form13f.zip）の SUBMISSION / COVERPAGE / SUMMARYPAGE から、
     報告期間 2026-06-30 の 13F-HR の提出者（CIK・名前・表の合計額・行数）を全件並べ、
     Dataroma の Portfolio value と合計額が近く（|log 比| ≤ 0.02 を強い一致・≤ 0.15 を弱い一致）
     かつ 名前の手がかり語が合う提出者を候補にする。値が合わないもの・6月末の提出が無いものは
     名前の手がかり（HINTS）で EDGAR の会社名検索（efts）から候補を作る。
  3. data.sec.gov/submissions/CIK##########.json（古い提出は files の続きのページも）で
     13F-HR の最初と最後の報告期間・2026-06-30 の 13F-HR の有無・13F-NT の件数を確かめる。
  ※ 13F の合計額はオプション・債券・ETF を含み、Dataroma は株の保有だけを数えることがあるので、
    額の一致は「同じ提出者だ」という強い証拠だが、不一致は「違う」の証拠にはならない（理由を note に書く）。

絶対のルール7: 見つからないものは cik=null と理由。推測で埋めない。

段
  --dataroma : Dataroma の83ページを取る（ブラウザの UA・cookie humans_21909=1・1.5秒あけ）
  --dataset  : SEC 13F データセット（約100MB）を取る
  (既定)     : 突き合わせて submissions を確かめ、out/_bestpf_cache/ciks.json を書く
"""
import csv, gzip, io, json, math, os, re, sys, time, urllib.error, urllib.parse, urllib.request, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, 'out', '_bestpf_cache', 'R0')
OUT = os.path.join(BASE, 'out', '_bestpf_cache', 'ciks.json')
PREREG = os.path.join(BASE, 'out', 'bestpf_prereg.json')
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}   # mw_best_ideas_13f.SEC_UA と同じ
DR_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
         'Cookie': 'humans_21909=1'}
DR_URL = 'https://www.dataroma.com/m/holdings.php?m={}'
DS_URL = 'https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip'
SUB_URL = 'https://data.sec.gov/submissions/{}'
TARGET_PERIOD = '2026-06-30'
# 優先株・社債・ワラント等（普通株でない行）の見分けは mw_best_ideas_13f と同じ正規表現（Dataroma は普通株だけを数える）
NONCOMMON_RE = re.compile(r'\b(PFD|PREF|PREFERRED|PRFD|NOTE|NOTES|BOND|BONDS|DEBT|DEBENTURE|DEBENTURES|DBCV|SDCV|SR NT|'
                          r'WT|WTS|WARRANT|WARRANTS|RIGHT|RIGHTS|RTS|CALL|PUT|OPTION|OPTIONS)\b', re.I)
# さらに厳しい版（名前に Conv/Pfd が入る転換優先株・預託株式・*W EXP のワラント）。Dataroma が数えない行の見分けの第2案
STRICT_TITLE_RE = re.compile(r'(\bDEP SHS\b|\bDEPOSITARY\b|\*W\b)', re.I)
STRICT_ISSUER_RE = re.compile(r'\b(PFD|CONV|CONVERTIBLE|PREF|PREFERRED)\b', re.I)
csv.field_size_limit(1 << 30)

# 名前の手がかり語（Dataroma の表示名から人名を除いた運用会社の名前。SEC の提出者名に含まれるべき語・大文字）。
# 投信の名前のものは助言会社（13F の提出者）の名前にする（事前登録の作業指示どおり）。
HINTS = {
    'ABI': ['ABRAMS BISON'], 'AKO': ['AKO CAPITAL'], 'AIM': ['ATLANTIC INVESTMENT MANAGEMENT'],
    'AP': ['ALTAROCK'], 'VAN': ['VAN DEN BERG', 'CENTURY MANAGEMENT'], 'GFT': ['GATES FOUNDATION'],
    'psc': ['PERSHING SQUARE'], 'LMM': ['MILLER VALUE PARTNERS'], 'HA': ['HARRIS ASSOCIATES'],
    'fairx': ['FAIRHOLME'], 'OCL': ['OAKCLIFF'], 'ic': ['ICAHN'], 'TGM': ['TIGER GLOBAL'],
    'tci': ['TCI FUND'], 'SA': ['SEMPER AUGUSTUS'], 'DAV': ['DAVIS SELECTED', 'DAVIS ADVISORS'],
    'AC': ['AKRE'], 'CAS': ['CAS INVESTMENT'], 'tp': ['THIRD POINT'], 'abc': ['ABRAMS CAPITAL'],
    'GLRE': ['GREENLIGHT CAPITAL', 'DME CAPITAL'], 'MAVFX': ['MATRIX ASSET'], 'WP': ['WEDGEWOOD'],
    'AM': ['APPALOOSA'], 'SP': ['SHAWSPRING'], 'DAC': ['DODGE & COX', 'DODGE &AMP; COX'],
    'HH': ['H&H INTERNATIONAL', 'H&AMP;H INTERNATIONAL'], 'FE': ['FIRST EAGLE'], 'FPA': ['FIRST PACIFIC ADVISORS'],
    'ca': ['CHOU ASSOCIATES'], 'GC': ['GIVERNY'], 'CCM': ['BRAVE WARRIOR'], 'ENG': ['ENGAGED CAPITAL'],
    'GA': ['GREENHAVEN ASSOCIATES'], 'CM': ['CONIFER MANAGEMENT'], 'aq': ['AQUAMARINE'],
    'SSHFX': ['SOUND SHORE'], 'DCP': ['DURABLE CAPITAL'], 'HCM': ['HILLMAN'], 'oc': ['OAKTREE CAPITAL'],
    'JIM': ['JENSEN INVESTMENT'], 'EC': ['EGERTON'], 'AI': ['ARIEL INVESTMENTS'], 'GLC': ['GREENLEA LANE'],
    'KB': ['KAHN BROTHERS'], 'mc': ['MAVERICK CAPITAL'], 'oa': ['OMEGA ADVISORS', 'COOPERMAN'],
    'HC': ['HIMALAYA CAPITAL'], 'LT': ['LINDSELL TRAIN'], 'MPF': ['MAIRS & POWER', 'MAIRS &AMP; POWER'],
    'SE': ['SOUTHEASTERN ASSET'], 'SAM': ['SCION ASSET'], 'PI': ['DALAL STREET', 'PABRAI'],
    'MUHL': ['MUHLENKAMP'], 'TF': ['TRIAN FUND'], 'PC': ['PUNCH CARD'], 'DA': ['DORSEY ASSET'],
    'pcm': ['POLEN CAPITAL'], 'FFH': ['FAIRFAX FINANCIAL'], 'PIM': ['PZENA INVESTMENT'],
    'RVC': ['RV CAPITAL'], 'RC': ['RUANE', 'CUNNIFF'], 'PTNT': ['PATIENT CAPITAL'],
    'CAU': ['CAUSEWAY CAPITAL'], 'BAUPOST': ['BAUPOST'], 'LPC': ['LONE PINE'], 'CHE': ['CHECK CAPITAL'],
    'FS': ['FUNDSMITH'], 'TA': ['THIRD AVENUE'], 'MKL': ['MARKEL'], 'GR': ['GARDNER RUSSO'],
    'MP': ['MAKAIRA'], 'T': ['TORRAY'], 'TFP': ['TRIPLE FROND'], 'TB': ['TWEEDY'],
    'VFC': ['VALLEY FORGE CAPITAL'], 'VA': ['VALUEACT'], 'vg': ['VIKING GLOBAL'],
    'VVP': ['VULCAN VALUE'], 'WIM': ['WEITZ'], 'BRK': ['BERKSHIRE HATHAWAY'], 'cc': ['CANTILLON'],
    'YAM': ['YACKTMAN'],
}


# ───────────────────────── 取得 ─────────────────────────
def fetch(url, path, headers, sleep, tries=4, max_age_days=10):
    if os.path.exists(path) and os.path.getsize(path) > 0 and time.time() - os.path.getmtime(path) < max_age_days * 86400:
        return open(path, 'rb').read()
    err = None
    for i in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f'{path}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, path)
            time.sleep(sleep)
            return b
        except urllib.error.HTTPError as e:
            err = e
            if e.code == 404:
                break
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa
            err = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f'取得失敗 {url}: {err}')


def prereg_list():
    return json.load(open(PREREG))['dataroma_list']


# ───────────────────────── Dataroma ─────────────────────────
def parse_dataroma(html):
    t = html.decode('utf-8', 'ignore')
    def g(pat):
        m = re.search(pat, t, re.S)
        return re.sub(r'\s+', ' ', m.group(1)).strip() if m else None
    val = g(r'Portfolio value:\s*<span>\s*\$?([\d,\.]+)')
    nst = g(r'No\. of stocks:\s*<span>\s*([\d,]+)')
    return {
        'dr_name': (g(r'<div id="f_name">(.*?)(?:<span|</div>)') or '').strip() or None,
        'dr_period': g(r'Period:\s*<span>(.*?)</span>'),
        'dr_portfolio_date': g(r'Portfolio date:\s*<span>(.*?)</span>'),
        'dr_n_stocks': int(nst.replace(',', '')) if nst else None,
        'dr_value_usd': float(val.replace(',', '')) if val else None,
    }


def stage_dataroma():
    out = {}
    for x in prereg_list():
        code = x['code']
        p = os.path.join(CACHE, 'dr', f'{code}.html')
        b = fetch(DR_URL.format(code), p, DR_UA, sleep=1.5)
        d = parse_dataroma(b)
        if not d['dr_name']:
            os.remove(p)
            raise RuntimeError(f'Dataroma のページが読めない（cookie の関門？） {code}')
        out[code] = d
        print(code, d, flush=True)
    json.dump(out, open(os.path.join(CACHE, 'dataroma.json'), 'w'), ensure_ascii=False, indent=1)
    return out


# ───────────────────────── 13F データセット ─────────────────────────
def ds_path():
    return os.path.join(CACHE, os.path.basename(DS_URL))


def stage_dataset():
    p = ds_path()
    if not (os.path.exists(p) and os.path.getsize(p) > 50_000_000):
        b = urllib.request.urlopen(urllib.request.Request(DS_URL, headers={'User-Agent': SEC_UA['User-Agent']}), timeout=900).read()
        open(p + '.tmp', 'wb').write(b); os.replace(p + '.tmp', p)
    print('dataset', p, os.path.getsize(p))


def read_tsv(z, name):
    nm = [n for n in z.namelist() if n.upper().endswith(name)]
    if not nm:
        raise RuntimeError(f'データセットに {name} が無い')
    with z.open(nm[0]) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='ignore'), delimiter='\t'))


def load_dataset():
    """報告期間 30-JUN-2026 の 13F 提出（原本・修正とも）を CIK ごとに集める"""
    z = zipfile.ZipFile(ds_path())
    sub = {r['ACCESSION_NUMBER']: r for r in read_tsv(z, 'SUBMISSION.TSV')}
    cov = {r['ACCESSION_NUMBER']: r for r in read_tsv(z, 'COVERPAGE.TSV')}
    summ = {r['ACCESSION_NUMBER']: r for r in read_tsv(z, 'SUMMARYPAGE.TSV')}
    rows = []
    for acc, s in sub.items():
        if s.get('PERIODOFREPORT', '').upper() != '30-JUN-2026':
            continue
        c, m = cov.get(acc, {}), summ.get(acc, {})
        def f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        rows.append({'acc': acc, 'cik': s['CIK'].zfill(10), 'type': s.get('SUBMISSIONTYPE'), 'filed': s.get('FILING_DATE'),
                     'name': (c.get('FILINGMANAGER_NAME') or '').upper(), 'amend': c.get('ISAMENDMENT'),
                     'amend_type': c.get('AMENDMENTTYPE'), 'report_type': c.get('REPORTTYPE'),
                     'value': f(m.get('TABLEVALUETOTAL')), 'entries': f(m.get('TABLEENTRYTOTAL'))})
    return rows


# ───────────────────────── 突き合わせ ─────────────────────────
def norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9& ]', ' ', (s or '').upper().replace('&AMP;', '&'))).strip()


def name_hit(code, name):
    n = norm(name)
    return any(norm(h) in n for h in HINTS.get(code, []))


def candidates(code, dr, rows):
    """データセットの 6月末 13F-HR（原本・保有の表あり）から候補を作る"""
    out = []
    v = dr.get('dr_value_usd')
    for r in rows:
        if r['type'] not in ('13F-HR', '13F-HR/A'):
            continue
        nh = name_hit(code, r['name'])
        lr = None
        if v and r['value'] and r['value'] > 0:
            lr = abs(math.log(r['value'] / v))
        if nh or (lr is not None and lr <= 0.002):
            out.append(dict(r, name_hit=nh, log_ratio=None if lr is None else round(lr, 5)))
    out.sort(key=lambda r: (not r['name_hit'], r['log_ratio'] if r['log_ratio'] is not None else 9, r['type'] != '13F-HR'))
    return out


# ───────────────────────── submissions ─────────────────────────
def submissions(cik):
    j = json.loads(fetch(SUB_URL.format(f'CIK{cik}.json'), os.path.join(CACHE, 'sub', f'CIK{cik}.json'), SEC_UA, sleep=0.15))
    recs = []
    def take(block):
        n = len(block.get('form', []))
        for i in range(n):
            recs.append({k: block[k][i] for k in ('form', 'reportDate', 'filingDate', 'accessionNumber') if k in block})
    take(j['filings']['recent'])
    for f in j['filings'].get('files', []):
        jj = json.loads(fetch(SUB_URL.format(f['name']), os.path.join(CACHE, 'sub', f['name']), SEC_UA, sleep=0.15))
        take(jj)
    return j, recs


def summarize_13f(cik):
    j, recs = submissions(cik)
    hr = [r for r in recs if r['form'] == '13F-HR']
    hra = [r for r in recs if r['form'] == '13F-HR/A']
    nt = [r for r in recs if r['form'] in ('13F-NT', '13F-NT/A')]
    per = sorted(r['reportDate'] for r in hr if r.get('reportDate'))
    # 古い提出（2001年ごろ以前）は reportDate が空のことがある → 提出日で補い、そう書く
    no_rd = [r['filingDate'] for r in hr if not r.get('reportDate')]
    return {
        'filer_name': j.get('name'),
        'former_names': [x.get('name') for x in j.get('formerNames', [])],
        'n_13f_hr': len(hr), 'n_13f_hr_amend': len(hra), 'n_13f_nt': len(nt),
        'first_period': per[0] if per else None, 'last_period': per[-1] if per else None,
        'first_filing_date_13f_hr': min([r['filingDate'] for r in hr], default=None),
        'last_filing_date_13f_hr': max([r['filingDate'] for r in hr], default=None),
        'n_13f_hr_without_report_date': len(no_rd),
        'has_2026_06_30_13f_hr': any(r.get('reportDate') == TARGET_PERIOD for r in hr),
        'has_2026_06_30_13f_hr_amend': any(r.get('reportDate') == TARGET_PERIOD for r in hra),
        'has_2026_06_30_13f_nt': any(r.get('reportDate') == TARGET_PERIOD for r in nt),
        'acc_2026_06_30_13f_hr': [r['accessionNumber'] for r in hr if r.get('reportDate') == TARGET_PERIOD],
        'sic': j.get('sic'), 'state': (j.get('addresses', {}).get('business', {}) or {}).get('stateOrCountry'),
    }



# ───────────────────────── 突き合わせの本体 ─────────────────────────
def infotable_stats(accs):
    """データセットの INFOTABLE から、提出ごとに 株（SH・プット/コールでない）の合計額・銘柄数（CUSIP）・オプション額・PRN 額"""
    z = zipfile.ZipFile(ds_path())
    nm = [n for n in z.namelist() if n.upper().endswith('INFOTABLE.TSV')][0]
    st = {a: {'eq_value': 0.0, 'opt_value': 0.0, 'prn_value': 0.0, 'cusips': set(), 'cm_value': 0.0, 'cm_cusips': set(),
              'cs_value': 0.0, 'cs_cusips': set()} for a in accs}
    with z.open(nm) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='ignore'), delimiter='\t'):
            a = r['ACCESSION_NUMBER']
            if a not in st:
                continue
            try:
                v = float(r['VALUE'])
            except ValueError:
                continue
            if (r.get('PUTCALL') or '').strip():
                st[a]['opt_value'] += v
            elif (r.get('SSHPRNAMTTYPE') or '').strip().upper() == 'PRN':
                st[a]['prn_value'] += v
            else:
                st[a]['eq_value'] += v; st[a]['cusips'].add(r['CUSIP'])
                if not NONCOMMON_RE.search(r.get('TITLEOFCLASS') or ''):
                    st[a]['cm_value'] += v; st[a]['cm_cusips'].add(r['CUSIP'])
                    if not STRICT_TITLE_RE.search(r.get('TITLEOFCLASS') or '') and not STRICT_ISSUER_RE.search(r.get('NAMEOFISSUER') or ''):
                        st[a]['cs_value'] += v; st[a]['cs_cusips'].add(r['CUSIP'])
    return {a: {'eq_value': x['eq_value'], 'opt_value': x['opt_value'], 'prn_value': x['prn_value'],
                'n_cusip_eq': len(x['cusips']), 'cm_value': x['cm_value'], 'n_cusip_cm': len(x['cm_cusips']),
                'cs_value': x['cs_value'], 'n_cusip_cs': len(x['cs_cusips'])} for a, x in st.items()}


def lr(a, b):
    return abs(math.log(a / b)) if a and b and a > 0 and b > 0 else None


def grade_match(c, v):
    """Dataroma の額 v と 13F の合計（そのまま／千ドル単位の誤り×1000／株だけ）の最も近い組の |log 比|"""
    opts = []
    for lab, x in (('total', c['value']), ('total_x1000', (c['value'] or 0) * 1000), ('equity_only', c.get('eq_value')),
                   ('equity_only_x1000', (c.get('eq_value') or 0) * 1000), ('common_only', c.get('cm_value')),
                   ('common_only_x1000', (c.get('cm_value') or 0) * 1000), ('common_strict', c.get('cs_value')),
                   ('common_strict_x1000', (c.get('cs_value') or 0) * 1000)):
        r = lr(x, v)
        if r is not None:
            opts.append((r, lab))
    if not opts:
        return None, None
    r, lab = min(opts)
    return round(r, 5), lab


def efts(q):
    """EDGAR の会社名の検索（search-index）→ [(cik10, 名前)]"""
    url = 'https://efts.sec.gov/LATEST/search-index?keysTyped=' + urllib.parse.quote(q)
    key = re.sub(r'[^A-Za-z0-9]+', '_', q)[:60]
    j = json.loads(fetch(url, os.path.join(CACHE, 'efts', f'{key}.json'), SEC_UA, sleep=0.15))
    return [(str(h['_id']).zfill(10), h['_source'].get('entity', '')) for h in j.get('hits', {}).get('hits', [])]


def months_between(a, b):
    ya, ma = int(a[:4]), int(a[5:7]); yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def related_ciks(code, main_cik, main_sum):
    """同じ名前の手がかり語を持つ別の CIK で 13F-HR を出しているもの（前身の候補）"""
    seen, out = {main_cik}, []
    for h in HINTS.get(code, []):
        if '&AMP;' in h:
            continue
        for cik, ent in efts(h.title() if h.isupper() else h):
            if cik in seen or norm(h) not in norm(ent):
                continue
            seen.add(cik)
            try:
                s = summarize_13f(cik)
            except Exception as e:  # noqa
                out.append({'cik': cik, 'efts_name': ent, 'error': str(e)[:200]}); continue
            if s['n_13f_hr'] == 0:
                continue
            rel = 'same_name_other'
            if s['last_period'] and main_sum.get('first_period') and s['first_period'] and s['first_period'] < main_sum['first_period'] \
                    and months_between(s['last_period'], main_sum['first_period']) <= 6:
                rel = 'predecessor_candidate'
            out.append({'cik': cik, 'filer_name': s['filer_name'], 'relation': rel,
                        'first_period': s['first_period'], 'last_period': s['last_period'], 'n_13f_hr': s['n_13f_hr'],
                        'has_2026_06_30_13f_hr': s['has_2026_06_30_13f_hr'], 'n_13f_nt': s['n_13f_nt']})
    return out


def stage_resolve():
    dr = json.load(open(os.path.join(CACHE, 'dataroma.json')))
    rows = load_dataset()
    cands = {x['code']: [r for r in candidates(x['code'], dr[x['code']], rows) if r['name_hit']] for x in prereg_list()}
    st = infotable_stats({r['acc'] for cs in cands.values() for r in cs})
    out = []
    for x in prereg_list():
        code, d = x['code'], dr[x['code']]
        e = {'code': code, 'name': x['name'], 'dataroma': d, 'cik': None, 'filer_name': None}
        cs = []
        for r in cands[code]:
            r = dict(r, **st.get(r['acc'], {}))
            r['match_log_ratio'], r['match_on'] = grade_match(r, d['dr_value_usd']) if d['dr_value_usd'] else (None, None)
            cs.append(r)
        cs.sort(key=lambda r: (r['match_log_ratio'] if r['match_log_ratio'] is not None else 9, r['type'] != '13F-HR'))
        pick = None
        if cs and cs[0]['match_log_ratio'] is not None and cs[0]['match_log_ratio'] <= 0.10:
            pick = cs[0]
            e['how'] = 'SEC 13F データセット（2026-06-30 の提出）で 名前の手がかり語 ∧ Dataroma の Portfolio value と合計額の一致'
            g = pick['match_log_ratio']
            e['match_grade'] = 'exact' if g <= 0.002 else ('close' if g <= 0.05 else 'loose')
            e['dataset_match'] = {k: pick.get(k) for k in ('acc', 'type', 'filed', 'name', 'value', 'entries', 'eq_value',
                                                           'opt_value', 'prn_value', 'n_cusip_eq', 'cm_value', 'n_cusip_cm',
                                                           'cs_value', 'n_cusip_cs', 'match_log_ratio', 'match_on')}
            e['other_name_hits_in_dataset'] = [{k: r.get(k) for k in ('cik', 'type', 'name', 'value', 'match_log_ratio')}
                                               for r in cs[1:] if r['cik'] != pick['cik']]
            cik = pick['cik']
        else:
            # データセットで決まらない（6月末の提出が無い等）→ EDGAR の名前検索 → submissions で 13F-HR の有無を確かめる
            e['dataset_name_hits'] = [{k: r.get(k) for k in ('cik', 'type', 'name', 'value', 'match_log_ratio')} for r in cs]
            found = []
            for h in HINTS.get(code, []):
                if '&AMP;' in h:
                    continue
                for c2, ent in efts(h.title()):
                    if norm(h) in norm(ent) and c2 not in [f[0] for f in found]:
                        s = summarize_13f(c2)
                        if s['n_13f_hr']:
                            found.append((c2, ent, s))
            e['efts_candidates'] = [{'cik': c2, 'name': ent, 'n_13f_hr': s['n_13f_hr'], 'last_period': s['last_period']} for c2, ent, s in found]
            cik = None
            if len(found) == 1:
                cik = found[0][0]
                e['how'] = 'EDGAR の会社名検索（efts search-index）で 名前の手がかり語に合う 13F-HR 提出者が1件だけ'
                e['match_grade'] = 'name_only'
            elif len(found) > 1:
                e['how'] = '名前の手がかり語に合う 13F-HR 提出者が複数（下で選ぶ）'
        if cik:
            s = summarize_13f(cik)
            e['cik'] = cik
            e['filer_name'] = s['filer_name']
            e['sec'] = s
            e['related_ciks'] = related_ciks(code, cik, s)
        out.append(e)
        print(code, e.get('cik'), e.get('filer_name'), e.get('match_grade'), flush=True)
    json.dump(out, open(os.path.join(CACHE, 'resolve_raw.json'), 'w'), ensure_ascii=False, indent=1)
    return out


# 名前の手がかり語では出てこない前身（名前が変わった）を探す追加の検索語（検索語, 名前に含まれるべき語）
RELATED_EXTRA = {
    'psc': [('Pershing Square Capital Management', 'PERSHING SQUARE CAPITAL MANAGEMENT')],
    'tci': [('Childrens Investment Fund Management', 'CHILDRENS INVESTMENT FUND MANAGEMENT')],
}


def filing_doc(cik, acc):
    """13F 提出の primary_doc.xml から 表の合計額・行数・報告期間・提出者名（2013Q2 以降の XML 様式だけ）"""
    nd = acc.replace('-', '')
    base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nd}/'
    idx = json.loads(fetch(base + 'index.json', os.path.join(CACHE, 'doc', f'{nd}_index.json'), SEC_UA, sleep=0.15))
    names = [it['name'] for it in idx['directory']['item']]
    cand = ['primary_doc.xml'] if 'primary_doc.xml' in names else [n for n in names if n.lower().endswith('.xml')]
    for n in cand:
        t = fetch(base + n, os.path.join(CACHE, 'doc', f'{nd}_{n}'), SEC_UA, sleep=0.15).decode('utf-8', 'ignore')
        if 'tableValueTotal' not in t:
            continue
        def g(tag):
            m = re.search(rf'<(?:\w+:)?{tag}>\s*([^<]*?)\s*</', t)
            return m.group(1) if m else None
        v, ne = g('tableValueTotal'), g('tableEntryTotal')
        return {'acc': acc, 'url': base + n, 'period': g('periodOfReport'), 'name': g('name'),
                'value': float(v) if v else None, 'entries': int(ne) if ne else None,
                'n_other_included_managers': g('otherIncludedManagersCount')}
    return {'acc': acc, 'url': base, 'error': 'primary_doc に tableValueTotal が無い（XML 様式の前の提出か）'}


def quarters(a='2013-06-30', z=TARGET_PERIOD):
    out = []
    for y in range(int(a[:4]), int(z[:4]) + 1):
        for md in ('03-31', '06-30', '09-30', '12-31'):
            q = f'{y}-{md}'
            if a <= q <= z:
                out.append(q)
    return out


def hr_by_period(cik):
    """報告期間 → その期間の 13F-HR の原本（最も早い提出）の受付番号"""
    _, recs = submissions(cik)
    d = {}
    for r in sorted((r for r in recs if r['form'] == '13F-HR' and r.get('reportDate')), key=lambda r: r['filingDate']):
        d.setdefault(r['reportDate'], r['accessionNumber'])
    return d


def addr(cik):
    j, _ = submissions(cik)
    b = (j.get('addresses') or {}).get('business') or {}
    return {'city': b.get('city'), 'state': b.get('stateOrCountry')}

# 関係の判定（データで確かめた結果・理由つき）。'predecessor' だけを 2013Q2〜2026Q2 の履歴に使う。
# 確かめ方: 住所（submissions の business address）・同じ四半期の両方の提出の合計額と行数（primary_doc.xml）。
RELATION_OVERRIDE = {
    'psc': {'0001336528': ('predecessor', '2026-06-30 に Pershing Square Capital Management, L.P. は 13F-NT（保有は別の提出者が報告）を出し、'
                                          'Pershing Square Inc. が 13F-HR（15行・194.7億ドル）を出した。2025-06〜2026-03 は両方が 13F-HR を出したが、'
                                          'Inc.（当時の名前 PERSHING SQUARE HOLDCO, L.P.）の方は1行・約6億ドルの別の器で、運用の全体は L.P. の方（11行・約137億ドル）')},
    'tci': {'0001362598': ('predecessor', 'Childrens Investment Fund Management (UK) LLP（ロンドン）が 2015-03-31 まで保有を報告し、2015-06-30 から '
                                          'TCI Fund Management Ltd（ロンドン）が報告。2015-06〜2016-09 の UK LLP の提出は0行・0ドル')},
    'GLRE': {'0001079114': ('predecessor', 'Greenlight Capital Inc が 2023-12-31 まで 13F-HR、DME Capital Management, LP は 2023 年まで 13F-NT（55件）で '
                                           '2024-03-31 から 13F-HR。重なりなし')},
    'AM': {'0001006438': ('predecessor', 'Appaloosa Management LP が 2015-12-31 まで、Appaloosa LP が 2016-03-31 から。重なりなし')},
    'oa': {'0000898202': ('predecessor', 'Omega Advisors Inc. が 2014-09-30〜2018-12-31 を報告し、その間 COOPERMAN LEON G の 13F-HR は無い'
                                         '（ちょうど穴を埋める・重なりなし）。2018 年末に Omega Advisors は外部資金の運用をやめ家族の資産の運用へ移った')},
    'RC': {'0000728014': ('predecessor', 'Ruane, Cunniff & Goldfarb Inc が 2017-12-31 まで。2018-03-31 は両方が出したが Inc の方は1行・0ドル、L.P. が 59行')},
    'EC': {'0001083657': ('predecessor', 'Egerton Capital Ltd が 2013-06-30 まで、Egerton Capital (UK) LLP が 2013-09-30 から。重なりなし')},
    'aq': {'0001404599': ('predecessor', 'Aquamarine Capital Management, LLC が 2022-06-30 まで、Aquamarine Zurich AG が 2022-09-30 から。重なりなし'),
           '0002104187': ('different_firm_unverified', 'Aquamarine Financial (Cayman) Ltd（グランドケイマン）。2025-09-30 に 11行・9.7億ドルで、'
                                                       '同じ期の Aquamarine Zurich AG（14行・3.2億ドル〔千ドル単位の誤りを直した値〕）と保有の額が違う。'
                                                       'Guy Spier の会社との関係は確かめられない＝履歴に使わない')},
    'PC': {'0001419050': ('predecessor', 'Punch Card Capital, L.P. が 2014-09-30 まで、Punch Card Management L.P. が 2014-12-31 から。重なりなし')},
    'CCM': {'0000789920': ('predecessor', 'Brave Warrior Capital, Inc. が 2012-03-31 まで（2013Q2 より前）')},
    'abc': {'0001165407': ('predecessor', 'Abrams Capital Management, LLC が 2005-12-31 まで（2013Q2 より前）'),
            '0001426355': ('same_name_other', 'Abrams Capital Management, LLC（別 CIK）2007-12〜2010-09。2013Q2 より前')},
    'FPA': {'0000109501': ('predecessor', 'First Pacific Advisors Inc が 2006-09-30 まで（2013Q2 より前）')},
    'TA': {'0001002858': ('predecessor', 'Third Avenue Management LLC（別 CIK）が 2004-09-30 まで（2013Q2 より前）')},
    'PI': {'0001173334': ('predecessor', 'PABRAI MOHNISH が 2011-12-31 まで、Dalal Street, LLC が 2012-03-31 から（2013Q2 より前）')},
    'HCM': {'0001036288': ('different_firm', 'HILLMAN CO はピッツバーグ（PA）の別の会社。Hillman Capital Management, Inc. はベセスダ（MD）')},
    'VAN': {'0001753384': ('different_firm', 'Analog Century Management LP はニューヨークの別の会社（名前の語 CENTURY MANAGEMENT が偶然一致）。'
                                             'Century Management（Arnold Van Den Berg）の 13F の提出者はオースティン（TX）の VAN DEN BERG MANAGEMENT I, INC')},
    'GFT': {'0001663801': ('different_entity', 'Bill & Melinda Gates Foundation（財団そのもの・シアトル）。Dataroma が写すのは Trust（カークランド）')},
    'FS': {'0001868537': ('different_entity', 'FUNDSMITH INVESTMENT SERVICES LTD.（モーリシャス）。Dataroma が写すのは Fundsmith LLP（ロンドン）'),
           '0001520023': ('fund_vehicle', 'Fundsmith Equity Fund, L.P.（1回だけの提出）'),
           '0001813932': ('fund_vehicle', 'Fundsmith Long/Short Master Fund（2回だけの提出）')},
    'JIM': {'0002044851': ('different_firm', 'Nabity-Jensen Investment Management Inc は別の会社')},
    'GLC': {'0001413048': ('fund_vehicle', 'Greenlea Lane Capital Partners LP（2021-03-31 の1回だけ・同じ9行・同じ額の重複の提出）')},
    'VFC': {'0001364558': ('different_firm_unverified', 'Valley Forge Capital Advisors, Inc.（2006〜2011）は別の会社と見られる（確かめられない）')},
    'T': {'0000862696': ('pre_window_unverified', 'TORRAY FUND（投信）の 1999 年の2回だけ。2013Q2 の窓の外・関係は確かめていない'),
          '0000908378': ('pre_window_unverified', 'TORRAY ROBERT E（個人）の 1999 年の2回だけ。2013Q2 の窓の外・関係は確かめていない')},
}


def related_all(code, e):
    """resolve の関連 CIK ＋ 追加の検索語で見つけた前身。住所と関係（RELATION_OVERRIDE で上書き）を付ける"""
    rel = {r['cik']: dict(r) for r in e.get('related_ciks', []) if 'error' not in r}
    for q, must in RELATED_EXTRA.get(code, []):
        for cik, ent in efts(q):
            if cik == e['cik'] or cik in rel or norm(must) not in norm(ent):
                continue
            s = summarize_13f(cik)
            if s['n_13f_hr']:
                rel[cik] = {'cik': cik, 'filer_name': s['filer_name'], 'relation': 'predecessor_candidate',
                            'first_period': s['first_period'], 'last_period': s['last_period'], 'n_13f_hr': s['n_13f_hr'],
                            'has_2026_06_30_13f_hr': s['has_2026_06_30_13f_hr'], 'n_13f_nt': s['n_13f_nt']}
    out = []
    for cik, r in rel.items():
        r['address'] = addr(cik)
        ov = RELATION_OVERRIDE.get(code, {}).get(cik)
        r['relation_auto'] = r.get('relation')
        if ov:
            r['relation'], r['relation_reason'] = ov
        elif r.get('relation') == 'predecessor_candidate':
            r['relation_reason'] = '自動: 名前の語が同じ・最後の期間が本体の最初の期間の6か月以内（人の目で確かめていない）'
        else:
            r['relation_reason'] = '自動: 名前の語が同じだが期間がつながらない＝履歴に使わない'
        out.append(r)
    out.sort(key=lambda r: r.get('first_period') or '')
    return out


def doc_brief(cik, acc):
    d = filing_doc(cik, acc)
    return {k: d.get(k) for k in ('acc', 'name', 'value', 'entries', 'url', 'error') if d.get(k) is not None}


def history(e, rel):
    """2013-06-30〜2026-06-30 の各四半期に、どの CIK の 13F-HR を使えば運用の全体が取れるか"""
    main = e['cik']
    preds = [r['cik'] for r in rel if r.get('relation') == 'predecessor']
    hp = {c: hr_by_period(c) for c in [main] + preds}
    names = {main: e['filer_name']}
    names.update({r['cik']: r.get('filer_name') for r in rel})
    rows, checks = [], []
    for q in quarters():
        have = [c for c in [main] + preds if q in hp[c]]
        if not have:
            rows.append([q, None, None]); continue
        pick = have[0]
        if len(have) > 1:      # 同じ四半期に両方が出した → 表の合計額が大きい方（運用の全体）を採る
            briefs = {c: doc_brief(c, hp[c][q]) for c in have}
            pick = max(have, key=lambda c: briefs[c].get('value') or -1)
            checks.append({'period': q, 'kind': 'overlap', 'filings': briefs, 'picked': pick})
        rows.append([q, pick, hp[pick][q]])
    segs = []
    for q, c, acc in rows:
        if segs and segs[-1]['cik'] == c:
            segs[-1]['to'] = q; segs[-1]['n'] += 1
        else:
            segs.append({'cik': c, 'filer_name': names.get(c) if c else None, 'from': q, 'to': q, 'n': 1})
    # 前身から本体へ移った境目: 前の最後と次の最初の合計額・行数を並べる
    for a, b in zip(segs, segs[1:]):
        if a['cik'] and b['cik'] and a['cik'] != b['cik']:
            checks.append({'kind': 'handoff', 'from': {'cik': a['cik'], 'period': a['to'], **doc_brief(a['cik'], hp[a['cik']][a['to']])},
                           'to': {'cik': b['cik'], 'period': b['from'], **doc_brief(b['cik'], hp[b['cik']][b['from']])}})
    for sg in segs:
        if sg['cik'] is None:
            sg['filer_name'] = None
            sg['note'] = '13F-HR が無い四半期（この会社と前身のどれも出していない）'
    return {'segments': segs, 'quarters': rows, 'checks': checks,
            'n_quarters_covered': sum(1 for r in rows if r[1]), 'n_quarters_total': len(rows)}


def infotable_equity_xml(cik, acc):
    """古い提出（データセットの外）の infotable.xml から 株（プット/コールでない SH）の合計額と銘柄数"""
    nd = acc.replace('-', '')
    base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nd}/'
    idx = json.loads(fetch(base + 'index.json', os.path.join(CACHE, 'doc', f'{nd}_index.json'), SEC_UA, sleep=0.15))
    for n in [it['name'] for it in idx['directory']['item'] if it['name'].lower().endswith('.xml') and it['name'] != 'primary_doc.xml']:
        t = fetch(base + n, os.path.join(CACHE, 'doc', f'{nd}_{n}'), SEC_UA, sleep=0.15).decode('utf-8', 'ignore')
        if 'infoTable' not in t:
            continue
        eq, cus, tot, cm, cmc = 0.0, set(), 0.0, 0.0, set()
        for blk in re.findall(r'<(?:\w+:)?infoTable>(.*?)</(?:\w+:)?infoTable>', t, re.S):
            def g(tag):
                m = re.search(rf'<(?:\w+:)?{tag}>\s*([^<]*?)\s*</', blk)
                return m.group(1) if m else ''
            v = float(g('value') or 0); tot += v
            if not g('putCall') and g('sshPrnamtType').upper() == 'SH':
                eq += v; cus.add(g('cusip'))
                if not NONCOMMON_RE.search(g('titleOfClass')):
                    cm += v; cmc.add(g('cusip'))
        return {'url': base + n, 'eq_value': eq, 'n_cusip_eq': len(cus), 'common_value': cm, 'n_cusip_common': len(cmc), 'total_value': tot}
    return {'url': base, 'error': 'infotable の XML が見つからない'}


def write_out():
    R = json.load(open(os.path.join(CACHE, 'resolve_raw.json')))
    out = []
    for e in R:
        code = e['code']
        r = {'code': code, 'name': e['name'], 'cik': e['cik'], 'filer_name': e['filer_name'],
             'dataroma': {'url': DR_URL.format(code), **e['dataroma']}}
        if not e['cik']:
            r['reason'] = '13F-HR の提出者が見つからない'; out.append(r); continue
        s = e['sec']
        r.update({'former_names': s['former_names'], 'address': addr(e['cik']),
                  'first_period': s['first_period'], 'last_period': s['last_period'],
                  'n_13f_hr': s['n_13f_hr'], 'n_13f_hr_amend': s['n_13f_hr_amend'], 'n_13f_nt': s['n_13f_nt'],
                  'has_2026_06_30_13f_hr': s['has_2026_06_30_13f_hr'],
                  'has_2026_06_30_13f_hr_amend': s['has_2026_06_30_13f_hr_amend'],
                  'acc_2026_06_30_13f_hr': s['acc_2026_06_30_13f_hr'],
                  'submissions_url': SUB_URL.format(f'CIK{e["cik"]}.json'),
                  'match_grade': e.get('match_grade'), 'how': e.get('how')})
        if e.get('dataset_match'):
            m = e['dataset_match']
            r['match'] = {'source': f'{DS_URL} の SUBMISSION/COVERPAGE/SUMMARYPAGE/INFOTABLE（報告期間 30-JUN-2026）',
                          'acc': m['acc'], 'type': m['type'], 'filed': m['filed'],
                          'table_value_total': m['value'], 'table_entry_total': m['entries'],
                          'equity_value_sh_no_putcall': m['eq_value'], 'n_cusip_equity': m['n_cusip_eq'],
                          'common_value_excl_pref_notes_warrants': m.get('cm_value'), 'n_cusip_common': m.get('n_cusip_cm'),
                          'common_value_strict': m.get('cs_value'), 'n_cusip_common_strict': m.get('n_cusip_cs'),
                          'option_value': m['opt_value'], 'prn_value': m['prn_value'],
                          'dataroma_value': e['dataroma']['dr_value_usd'], 'dataroma_n_stocks': e['dataroma']['dr_n_stocks'],
                          'abs_log_ratio': m['match_log_ratio'], 'matched_on': m['match_on']}
            if m['match_on'] and m['match_on'].endswith('x1000'):
                r['match']['note'] = '提出者が金額を千ドル単位で書いている（2023年以降は1ドル単位の決まり）＝×1000 で Dataroma と一致'
        rel = related_all(code, e)
        r['related_ciks'] = rel
        r['history_2013q2_2026q2'] = history(r, rel)
        out.append(r)
        print(code, r['cik'], r['history_2013q2_2026q2']['n_quarters_covered'], flush=True)
    by = {r['code']: r for r in out}
    # 個別の確かめ
    sam = by.get('SAM')
    if sam and sam['cik']:
        acc = hr_by_period(sam['cik']).get('2025-09-30')
        if acc:
            v = infotable_equity_xml(sam['cik'], acc)
            sam['match'] = {'source': v.get('url'), 'acc': acc, 'period': '2025-09-30',
                            **{k: v.get(k) for k in ('eq_value', 'n_cusip_eq', 'common_value', 'n_cusip_common', 'total_value')},
                            'dataroma_value': sam['dataroma']['dr_value_usd'], 'dataroma_n_stocks': sam['dataroma']['dr_n_stocks'],
                            'abs_log_ratio': round(lr(v.get('common_value'), sam['dataroma']['dr_value_usd']) or 9, 5),
                            'matched_on': 'common_only（優先株 Bruker 6.375% PREF SER A を除く）'}
            g = sam['match']['abs_log_ratio']
            sam['match_grade'] = 'exact' if g <= 0.002 else ('close' if g <= 0.05 else 'loose')
            sam['how'] = 'EDGAR の会社名検索で1件 → Dataroma の Q3 2025 と 2025-09-30 の 13F の株（プット/コールを除く）の額・銘柄数を突き合わせ'
            sam['note'] = ('Scion Asset Management は 2025-09-30 の 13F-HR（2025-11-03 提出）が最後。2026-06-30 の 13F は無い'
                           '（Dataroma も Q3 2025 のまま）。13F の合計 13.8億ドルの大半はプット/コール（Palantir・Nvidia のプット、Halliburton・Pfizer のコール）で、'
                           '普通株だけだと3銘柄（LULU・MOH・SLM）・5500.1万ドル＝Dataroma と一致。2016-12〜2018-09 にも 13F-HR が無い')
    mp = by.get('MP')
    if mp and mp['cik']:
        h = hr_by_period(mp['cik'])
        mp['match'] = {'period': '2026-03-31', **doc_brief(mp['cik'], h['2026-03-31']),
                       'prev_2025_12_31': doc_brief(mp['cik'], h['2025-12-31']),
                       'dataroma_n_stocks': mp['dataroma']['dr_n_stocks'], 'dataroma_value': mp['dataroma']['dr_value_usd']}
        mp['match_grade'] = 'exact_zero'
        mp['how'] = 'EDGAR の会社名検索で1件 → Dataroma の Q1 2026（0銘柄）と 2026-03-31 の 13F-HR（0行・0ドル）が一致'
        mp['note'] = ('Makaira Partners LLC の最後の 13F-HR は 2026-03-31（0行・0ドル＝保有を報告しない）。保有のある最後は 2025-12-31（11行・約1.28億ドル）。'
                      '2026-06-30 の 13F は無い')
    notes = {
        'T': ('Torray Funds の 13F の提出者は TORRAY INVESTMENT PARTNERS LLC。13F の株は 7.41億ドル・91行で Dataroma（6.73億ドル・88銘柄）より'
              ' 6,793.7万ドル多いが、その差は題名が COM の転換優先株3行（Alphabet Convertible Pfd・Hewlett Packard Ent Ser C Conv・'
              'KKR Series D Conv 6.25）とほぼ同じ（差 111ドル）＝Dataroma はこの3行を数えていない'),
        'tp': ('Third Point LLC の 13F。普通株の額は 46.43億ドル・40銘柄で Dataroma（45.67億ドル・38銘柄）より 7,621.7万ドル多いが、'
               'その差は Alphabet の預託株式（DEP SHS A 6,615.7万ドル・B 1,006万ドル）の2行とちょうど同じ＝Dataroma はこの2行を数えていない'),
        'oc': '13F の合計 72.1億ドル・145行は社債（PRN）とオプションを含む。株だけ（SH・プット/コールでない）だと 51銘柄・37.8億ドルで Dataroma と一致',
        'psc': ('★ 2013Q2〜2026Q1 の保有は前身 Pershing Square Capital Management, L.P.（CIK 0001336528）の 13F-HR。'
                '本体 CIK 0002026053 の 2025-06〜2026-03 の提出は1行の別の器なので、写しの履歴は history_2013q2_2026q2 の quarters の CIK を使うこと'),
        'GLRE': 'Dataroma の名前は Greenlight Capital だが、2024-03-31 からの提出者は DME Capital Management, LP。2023-12-31 までは Greenlight Capital Inc（CIK 0001079114）',
        'oa': '2014-09-30〜2018-12-31 は Omega Advisors Inc.（CIK 0000898202）、それ以外は COOPERMAN LEON G',
        'HA': 'Oakmark Funds（投信）は助言会社 Harris Associates L P の 13F。株だけの額・銘柄数（161）が Dataroma と一致',
        'DAC': 'Dodge & Cox Funds（投信）は助言会社 DODGE & COX の 13F',
        'MPF': 'Mairs & Power Funds は助言会社 MAIRS & POWER INC の 13F',
        'SSHFX': 'Sound Shore（投信）は SOUND SHORE MANAGEMENT INC /CT/ の 13F',
        'MAVFX': 'Matrix Asset Advisors の 13F（投信 MAVFX の助言会社）',
        'YAM': 'Yacktman（投信）は YACKTMAN ASSET MANAGEMENT LP の 13F',
        'JIM': 'Jensen（投信）は JENSEN INVESTMENT MANAGEMENT INC の 13F',
        'T': None,
        'HCM': '2014-03-31〜2019-09-30 に 13F-HR が無い（名前の合う他の CIK も 13F-HR を出していない）＝この期間は保有が分からない',
        'HC': '2018-12-31〜2019-09-30 の4期に 13F-HR が無い（submissions に提出なし）',
        'MUHL': '2018-12-31・2020-03-31・2023-03-31 の3期に 13F-HR が無い（submissions に提出なし）',
        'AKO': '13F の額は千ドル単位で書かれている（4,292,009 → ×1000 で Dataroma と一致）。最初の 13F-HR は 2016-12-31',
        'BAUPOST': '13F の額は千ドル単位で書かれている（×1000 で Dataroma と一致）',
        'TFP': '13F の額は千ドル単位で書かれている（×1000 で Dataroma と一致）',
        'aq': '13F の額は千ドル単位で書かれている（×1000 で Dataroma と一致）。2022-06-30 までは前身 Aquamarine Capital Management, LLC',
        'FS': 'Fundsmith LLP（ロンドン）の 13F。別の CIK の FUNDSMITH INVESTMENT SERVICES LTD.（モーリシャス）は使わない',
        'LT': 'Lindsell Train Ltd（ロンドン）の 13F',
        'EC': '2013-06-30 までは前身 Egerton Capital Ltd',
        'RC': '2017-12-31 までは前身 Ruane, Cunniff & Goldfarb Inc（CIK 0000728014）',
        'AM': '2015-12-31 までは前身 Appaloosa Management LP（CIK 0001006438）',
        'tci': '2015-03-31 までは前身 Childrens Investment Fund Management (UK) LLP（CIK 0001362598）',
        'PC': '2014-09-30 までは前身 Punch Card Capital, L.P.（CIK 0001419050）',
        'GFT': 'Gates Foundation Trust（13F の提出者）。別の CIK の Bill & Melinda Gates Foundation（財団そのもの）は使わない',
        'VAN': 'Century Management（Arnold Van Den Berg）の 13F の提出者は VAN DEN BERG MANAGEMENT I, INC（オースティン）',
        'PI': 'Pabrai Investments の 13F の提出者は Dalal Street, LLC（2011-12-31 までは PABRAI MOHNISH）',
        'ic': 'Icahn の 13F の提出者は ICAHN CARL C（個人名の提出者）',
        'BRK': '13F の行は89（他の運用者との組み合わせで同じ銘柄が複数行）。株の銘柄数29・額は Dataroma と一致',
        'MKL': 'Markel Group の 13F。行205・株の銘柄数130（Dataroma と一致）',
        'FFH': 'Fairfax Financial Holdings の 13F（カナダの保険会社・米国上場株の保有だけ）',
        'RVC': 'RV Capital（Dataroma の名前は GmbH）の 13F の提出者は RV Capital AG',
    }
    for k, v in notes.items():
        if v and k in by and 'note' not in by[k]:
            by[k]['note'] = v
    res = [r for r in out if r['cik']]
    meta = {
        'name': 'bestpf R0: Dataroma Superinvestors 83件の 13F-HR 提出者の CIK',
        'made': time.strftime('%Y-%m-%d'),
        'prereg': 'out/bestpf_prereg.json（コミット 7c4b672）の dataroma_list（sha256_16 ' + json.load(open(PREREG))['dataroma_list_sha256_16'] + '）',
        'code': 'night/bestpf_ciks.py（--dataroma → --dataset → --resolve → 既定で書き出し）',
        'sources': {
            'dataroma': 'https://www.dataroma.com/m/holdings.php?m=<code>（2026-10-12 取得・Period/Portfolio date/No. of stocks/Portfolio value）',
            'sec_13f_dataset': DS_URL,
            'sec_submissions': 'https://data.sec.gov/submissions/CIK##########.json（files の続きのページも）',
            'sec_entity_search': 'https://efts.sec.gov/LATEST/search-index?keysTyped=<名前>',
            'sec_filing_docs': 'https://www.sec.gov/Archives/edgar/data/<cik>/<受付番号>/primary_doc.xml',
        },
        'method': ('Dataroma の Portfolio value・No. of stocks と、SEC 13F データセットの 2026-06-30 の提出の「合計額／株（SH・プット/コールでない）／'
                   '普通株（優先株・社債・ワラントの題名を除く）／普通株の厳しい版（転換優先株・預託株式も除く）」の額（千ドル単位の誤りの ×1000 も）のうち'
                   '最も近いものを、名前の手がかり語に合う提出者の中で突き合わせた。SAM と MP は 2026-06-30 の提出が無いので'
                   'Dataroma の最後の期（Q3 2025・Q1 2026）の提出で確かめた。一致の度合いは grade_counts と各件の match'),
        'grades': {'exact': '|log 比| ≤ 0.002（0.2% 以内）', 'close': '≤ 0.05', 'loose': '> 0.05（名前の一致で判断・理由は note）',
                   'exact_zero': '0銘柄どうしの一致'},
        'periods': ('first_period/last_period は submissions に載る 13F-HR（修正を除く原本）の報告期間の最初と最後。EDGAR の電子提出（1999年ごろから）だけで、'
                    'それより前の紙の提出は入らない'),
        'history_note': ('history_2013q2_2026q2 は R2 の窓（2013Q2〜2026Q2）の各四半期にどの CIK のどの受付番号の 13F-HR を使えば運用の全体が取れるか。'
                         '前身（relation=predecessor・理由つき）を含む。同じ四半期に複数が出したときは表の合計額が大きい方。None は 13F-HR が無い四半期'
                         '（新しい会社・$1億未満の時期・提出の停止）。修正（13F-HR/A）は選んでいない（R2 で扱う）'),
        'n_list': len(out), 'n_resolved': len(res),
        'n_with_2026_06_30_13f_hr': sum(1 for r in res if r.get('has_2026_06_30_13f_hr')),
        'without_2026_06_30': [{'code': r['code'], 'cik': r['cik'], 'last_period': r['last_period']} for r in res if not r.get('has_2026_06_30_13f_hr')],
        'not_13f_hr_holders': '（なし: 83件すべて 13F-HR の提出者が見つかった）',
        'thousand_unit_filers_2026q2': [r['code'] for r in res if (r.get('match') or {}).get('matched_on', '').endswith('x1000')],
        'grade_counts': {g: sum(1 for r in res if r.get('match_grade') == g) for g in ('exact', 'close', 'loose', 'name_only', 'exact_zero')},
    }
    meta['matched_on_counts'] = {}
    for r in res:
        k = str((r.get('match') or {}).get('matched_on')).split('（')[0]
        meta['matched_on_counts'][k] = meta['matched_on_counts'].get(k, 0) + 1
    cik_by_code = {r['code']: r['cik'] for r in out}
    json.dump({'meta': meta, 'cik_by_code': cik_by_code, 'ciks': out}, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('wrote', OUT, meta['n_resolved'], meta['grade_counts'])

def main():
    a = sys.argv[1:]
    if '--dataroma' in a:
        stage_dataroma(); return
    if '--dataset' in a:
        stage_dataset(); return
    if '--resolve' in a:
        stage_resolve(); return
    write_out()


if __name__ == '__main__':
    main()
