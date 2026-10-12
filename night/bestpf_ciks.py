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
     名前の手がかり（HINTS）と手で確かめた CIK（KNOWN・出典はコメント）で候補を作る。
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
import csv, gzip, io, json, math, os, re, sys, time, urllib.request, zipfile

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
csv.field_size_limit(1 << 30)

# 名前の手がかり語（Dataroma の表示名から人名を除いた運用会社の名前。SEC の提出者名に含まれるべき語・大文字）。
# 投信の名前のものは助言会社（13F の提出者）の名前にする（事前登録の作業指示どおり）。
HINTS = {
    'ABI': ['ABRAMS BISON'], 'AKO': ['AKO CAPITAL'], 'AIM': ['ATLANTIC INVESTMENT MANAGEMENT'],
    'AP': ['ALTAROCK'], 'VAN': ['CENTURY MANAGEMENT'], 'GFT': ['GATES FOUNDATION'],
    'psc': ['PERSHING SQUARE'], 'LMM': ['MILLER VALUE PARTNERS'], 'HA': ['HARRIS ASSOCIATES'],
    'fairx': ['FAIRHOLME'], 'OCL': ['OAKCLIFF'], 'ic': ['ICAHN'], 'TGM': ['TIGER GLOBAL'],
    'tci': ['TCI FUND'], 'SA': ['SEMPER AUGUSTUS'], 'DAV': ['DAVIS SELECTED', 'DAVIS ADVISORS'],
    'AC': ['AKRE'], 'CAS': ['CAS INVESTMENT'], 'tp': ['THIRD POINT'], 'abc': ['ABRAMS CAPITAL'],
    'GLRE': ['GREENLIGHT CAPITAL'], 'MAVFX': ['MATRIX ASSET'], 'WP': ['WEDGEWOOD'],
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

# 手で選んだ候補（データセットの突き合わせで決まらないときの補い）。各行に「なぜこの CIK か」を残す。
# ここに置いた CIK も submissions で 13F-HR の提出を確かめ、提出者名が HINTS に合うことを機械で検める。
KNOWN = {}


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


def main():
    a = sys.argv[1:]
    if '--dataroma' in a:
        stage_dataroma(); return
    if '--dataset' in a:
        stage_dataset(); return
    raise SystemExit('段を指定（--dataroma / --dataset）。突き合わせは bestpf_ciks_resolve.py')


if __name__ == '__main__':
    main()
