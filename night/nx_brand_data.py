#!/usr/bin/env python3
"""night/nx_brand_data.py — nx 角度 brand（外部の格付けの一覧に載った会社を、一覧の公開の後に買う）の
**一覧の取得と対応表づくりだけ**（株価は取らない＝成績は計算しない・読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。
事前登録: out/nx_brand_prereg.json（測る前に固定）／全体の線: out/nx_prereg.json（criteria_short_sample）。

何をするか（すべて out/_nx_cache/ に置く・gitignore）
  1. Interbrand『Best Global Brands』（2000〜・毎年秋）
     - Interbrand 自身の API（interbrand.com/api/getBrandData/）: 2020〜2025 は100ブランドそろう。
       ★2019年以前は**今のデータベースに残っているブランドしか返さない**（2000年は41/100・2010年は74/100・2019年は96/100。
       Nokia・Marlboro・AT&T・Motorola は getBrandHistory でも空）＝そのまま使うと**生き残りの偏り（後知恵）**になる。
     - 抜けた順位は、その年の**原本**で埋める: Interbrand の報告書 PDF（原本。rankingthebrands.com の /PDF/ に置かれた写し）の本文、
       Interbrand の PR Newswire の発表（2010・2012 は100行の表つき）。
       報告書の表はロゴ（画像）で名前が文字になっていない年が多いので、抜けた順位の名前は rankingthebrands.com の一覧を
       **手がかり（finding aid）にだけ**使い、原本の本文にその名前（別名を含む）とブランド価値の数字がそろって出てくるか、
       または原本の表の数字（順位の並びとブランド価値）と一致するかで確かめる。行ごとに出所（provenance）を残す。
     - 完全な原本が無い年（2015・2017）と 2000〜2006（原本の PDF が手に入らない）は使わない（前の一覧を持ち続ける＝持ち越し）。
     - 公開日: PR Newswire の Interbrand の発表・掲載ブランドの会社の報道発表（Samsung・Toyota・Honda）の日付。
  2. Fortune『World's Most Admired Companies』（fortune.com/ranking/worlds-most-admired-companies/{年}/・2014〜2026）
     - All-Stars 50社（順位つき）と業種別の候補（honorable mentions・順位なし）。消えた会社（Starwood・EMC・DirecTV 等）も載っている。
     - 各社の Fortune の会社ページ（fortune.com/company/{slug}/）から Ticker・Company type・国。
     - 公開日: その年のページの dateGmt（Fortune 自身の公開時刻）。
  3. Forbes『World's Most Innovative Companies』（2011〜2018・forbes.com/forbesapi/org/innovative-companies/{年}/…）
     - 2011年は 69/100 しか返らない（抜け）＝使わない。2012〜2018 は 99〜100。公開日はリストの date 欄。
  4. Kantar BrandZ・ACSI は一次の完全な一覧が取れない（下の CHECKED に理由）＝使わない。

取れた一覧（2026-09-28 に実際に取った結果・形だけ）
  Interbrand: 完全な100ブランドの一覧 17年分（2007〜2014・2016・2018〜2025）。2015・2017 は持ち越し、2000〜2006 は使わない。
              行の出所: Interbrand の API（生き残り）・PR Newswire の表（2010・2012）・原本 PDF の本文に名前と価値（pdf_name_value）・
              原本 PDF の表の順位と価値が手がかりと一致（pdf_grid_value・名前はロゴ＝2016・2018・2019 の15行）。
  Fortune WMAC: 13年分（2014〜2026）の All-Stars（49〜51社）と候補（317〜355社）。
  Forbes: 7年分（2012〜2018）。

対応表（測る前に固定・この道具の中の表）
  ブランド → その月の親会社（BRAND_OWNER・買収/分離/上場/非公開化を月単位で）→ 親会社の株の記号（P・Yahoo の記号の候補・本社の国・
  米国版に入るか＝普通株の主な上場が NYSE/Nasdaq）。上場廃止して Yahoo に値の無い親会社は OLD_TICKER に当時の記号。
  分離（spin-off）の予定は EVENTS。Fortune は会社ページの Ticker（WMAC_MANUAL で上書き）、Forbes は米国の会社だけ SEC の
  company_tickers.json と名前で合わせる（SEC の User-Agent は hachimon_fetch.py の HDRS と同じ形）＋ FORBES_US_MANUAL。

いつ買うか: 公開日の月の月末（公開日がその月の最終日なら翌月末）に買い、次の一覧を買う月の月末まで持つ（purchase_month）。
  Interbrand で一次の公開日が見つからない年（2007・2008・2009・2013）は原本 PDF の作成月の翌月末（作成日 ≤ 公開日なので保守的）。

使い方: python3 night/nx_brand_data.py            → 全部作って out/_nx_cache/nx_brand_lists.json（sha256 を表示）
        python3 night/nx_brand_data.py --show     → 形だけ（年ごとの件数・出所の内訳・対応表の被覆）
"""
import sys, os, re, io, json, html, hashlib, datetime, time, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402

OUT = os.path.join(N.CACHE, 'nx_brand_lists.json')

# ───────────────────────── 取得の約束 ─────────────────────────
IB_API = 'https://interbrand.com/api/getBrandData/?region=global&first=100&url=%2Fbest-global-brands%2Fglobal%2F&year={y}'
IB_PDF = {  # Interbrand の原本 PDF（rankingthebrands.com の /PDF/ にある写し）。作成日（PDF の CreationDate）も記録する
    2007: 'Best%20Global%20Brands%202007.pdf',
    2008: 'Best%20Global%20Brands%202008.pdf',
    2009: 'Best%20Global%20Brands%202009.pdf',
    2010: 'Interbrand%20Best%20Global%20Brands%202010.pdf',
    2011: 'Best%20Global%20Brands%202011,%20Interbrand.pdf',
    2012: 'Interbrand%20Best%20Global%20Brands%202012.pdf',
    2013: 'Best%20Global%20Brands%202013,%20Interbrand.pdf',
    2014: 'Interbrand%20Best%20Global%20Brands%202014.pdf',
    2016: 'Best%20Global%20Brands%202016,%20Interbrand.pdf',
    2018: 'Interbrand%20Best%20Global%20Brands%202018.pdf',
    2019: 'Interbrand%20Best%20Global%20Brands%202019.pdf',
}
RTB = 'https://www.rankingthebrands.com/'
AID_YEAR_ID = {2007: 37, 2008: 38, 2009: 72, 2010: 214, 2011: 368, 2012: 523, 2013: 697, 2014: 857, 2015: 985,
               2016: 1096, 2017: 1176, 2018: 1231, 2019: 1273}
PRN = 'https://www.prnewswire.com/news-releases/{}.html'
IB_PRN_TABLE = {2010: 'interbrand-releases-11th-annual-ranking-of-the-100-best-global-brands-103006449',
                2012: 'interbrand-releases-13th-annual-best-global-brands-report-172256731'}
# 公開日の出所（一次: Interbrand 自身の発表か、掲載ブランドの会社自身の発表）。道具が取りに行って日付を読み直す
IB_DATE_SRC = {
    2010: ('prn', 'interbrand-releases-11th-annual-ranking-of-the-100-best-global-brands-103006449'),
    2011: ('prn', 'interbrand-releases-12th-annual-best-global-brands-report-131065533'),
    2012: ('prn', 'interbrand-releases-13th-annual-best-global-brands-report-172256731'),
    2014: ('url', 'https://global.honda/en/newsroom/news/2014/c141009eng.html'),
    2016: ('url', 'https://pressroom.toyota.com/toyota-interbrand-global-brands-2016/'),
    2018: ('samsung_tag', 'samsung-electronics-ranks-6th-in-interbrands-best-global-brands-2018'),
    2019: ('prn', 'interbrand-celebrates-20-years-of-best-global-brands-report-highlights-fastest-growing-sectors-300940156'),
    2020: ('prn', 'zoom-and-tesla-enter-the-ranks-of-interbrands-2020-best-global-brands-report-301153094'),
    2021: ('prn', 'tesla-leapfrogs-the-competition-in-interbrands-2021-best-global-brands-report-301401379'),
    2022: ('samsung_tag', 'samsung-electronics-brand-value-makes-double-digit-increase-taking-a-spot-in-the-list-of-top-five-best-global-brands-2022'),
    2023: ('prn', 'brand-growth-slows-finds-interbrands-best-global-brands-report-2023-301990979'),
    2024: ('prn', 'growth-at-what-cost-the-worlds-100-most-valuable-brands-have-missed-out-on-3-5-trillion-of-value-creation-since-2000--reveals-interbrands-best-global-brands-report-302271433'),
    2025: ('prn', 'brands-adapting-to-market-challenges-increases-the-total-value-of-interbrands-2025-best-global-brands-by-150-billion-302583746'),
}
WMAC = 'https://fortune.com/ranking/worlds-most-admired-companies/{}/'
FORBES = 'https://www.forbes.com/forbesapi/org/innovative-companies/{}/position/true.json?limit=200'

CHECKED = {  # 調べて使わないと決めたもの（理由つき・測る前）
    'kantar_brandz': 'kantar.com/campaigns/brandz/global のページに埋め込まれた履歴（brandHistory）は 2026年の上位100ブランドの過去だけ'
                     '（2006年は33/100・2015年は49/100）＝生き残りだけ。報告書のダウンロードはフォーム登録が要る。'
                     '原本 PDF の写しは 2008〜2012・2014・2015・2018・2019・2021 の10年分だけ（2006・2007・2013・2016・2017・2020・2022〜2025 が無い）＝使わない',
    'acsi': 'theacsi.org（→ theacsi.com）は 403（プロキシ・WebFetch とも）。二次の寄せ集めでは代えない＝使わない',
    'interbrand_2000_2006': 'Interbrand の API は生き残りだけ（2000年 41/100〜2006年 66/100）。当時の原本（BusinessWeek 掲載・Interbrand の PDF）は取れない＝使わない',
    'interbrand_2015_2017': '原本の PDF の写しが無く、Interbrand の API は 86/100・92/100 ＝その年は前の一覧を持ち続ける（持ち越し）',
    'wayback': 'web.archive.org は接続が切られる（プロキシ）・archive.org の available API は 429 ＝使えない',
    'businessweek': 'businessweek.com の旧 PDF は bloomberg.com へ飛ばされ 403',
    'forbes_2011': 'API が 69/100 しか返さない（抜けた31社が分からない）＝使わない',
}


def _txt(url, name, max_age_days=3650):
    return N.get(url, name=name, max_age_days=max_age_days).decode('utf-8', 'replace')


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]', '', s)


def _num(s):
    s = re.sub(r'[^\d]', '', s or '')
    return int(s) if s else None


# ───────────────────────── Interbrand ─────────────────────────
def ib_api(y):
    j = json.loads(_txt(IB_API.format(y=y), f'ib_api_{y}.json'))
    return [{'rank': x['rank'], 'name': x['brandName'], 'value': x['brandValue'], 'chg': x.get('percentageChange'),
             'industry': (x.get('industry') or [{}])[0].get('name')} for x in (j.get('data') or [])]


def ib_prn_table(y):
    t = _txt(PRN.format(IB_PRN_TABLE[y]), f'prn_ib_{y}.html')
    rows = []
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
        c = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', x))).strip() for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        if len(c) >= 5 and c[0].isdigit():
            rows.append({'rank': int(c[0]), 'prev': int(c[1]) if c[1].isdigit() else None, 'name': c[2], 'sector': c[3], 'value': _num(c[4])})
    return rows


def ib_pdf_text(y):
    """原本 PDF の本文（文字）と作成日。PDF は大きいので本文だけをキャッシュに残す"""
    p = os.path.join(N.CACHE, f'ib_pdf_{y}.txt.json')
    if os.path.exists(p):
        return json.load(open(p))
    import pypdf, logging
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    b = N.get(RTB + 'PDF/' + IB_PDF[y], name=f'ib_pdf_{y}.pdf', max_age_days=3650)
    r = pypdf.PdfReader(io.BytesIO(b))
    pages = []
    for pg in r.pages:
        try:
            pages.append(pg.extract_text() or '')
        except Exception:  # noqa
            pages.append('')
    md = r.metadata or {}
    o = {'year': y, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'pages': len(pages),
         'created': str(md.get('/CreationDate')), 'producer': str(md.get('/Producer')), 'creator': str(md.get('/Creator')),
         'text': pages}
    json.dump(o, open(p, 'w'))
    return o


def ib_aid(y):
    """rankingthebrands.com の一覧（二次＝手がかりにだけ使う）"""
    t = _txt(RTB + f'The-Brand-Rankings.aspx?rankingID=37&year={AID_YEAR_ID[y]}', f'rtb_ib_{y}.html')
    return [{'rank': int(a), 'name': html.unescape(b).strip(), 'value': _num(c)} for a, b, c in
            re.findall(r"<div class='pos'>(\d+)</div>.*?<div class='name'><a[^>]*>([^<]*)</a></div><div class='weighted'>([^<]*)</div>", t, re.S)]


ALIAS = {  # 手がかりの名前 → 原本の本文で探す別名（手がかりのサイトは今の社名に書き換えていることがある）
    'dellemc': ['dell'], 'delltechnologies': ['dell'], 'moetetchandon': ['moetchandon', 'moet'], 'kraftfoodsgroup': ['kraft'],
    'eastmankodak': ['kodak'], 'giorgioarmani': ['armani'], 'marriottinternational': ['marriott'], 'discoverychannel': ['discovery'],
    'thomsonreuters': ['thomsonreuters', 'reuters'], 'hewlettpackard': ['hp', 'hewlettpackard'], 'generalelectric': ['ge'],
    'jpmorgan': ['jpmorgan', 'morgan'], 'harleydavidson': ['harleydavidson', 'harley'], 'johnniewalker': ['johnniewalker'],
    'jackdaniels': ['jackdaniel'], 'kentuckyfriedchicken': ['kfc'], 'hermesparis': ['hermes'], 'vwvolkswagen': ['volkswagen'],
    'mercedesbenz': ['mercedes'], 'lancome': ['lancome'], 'blackberry': ['blackberry'], 'yahoo': ['yahoo'],
    'ralphlauren': ['ralphlauren', 'polorl'], 'discovery': ['discovery'],
}


VAL_RE = r'(\d{1,3}(?:\s*,\s*\d\s*\d\s*\d)+)\s*\$\s*m'


def ib_pdf_grid(y):
    """報告書の順位表（ロゴの格子）の頁から 順位→価値 を読む。価値は順位が下がるほど小さいので、
    表の頁（『1,234 $m』が20以上ある頁）の価値をちょうど100個集めて大きい順に並べれば順位そのもの。100個でなければ None"""
    o = ib_pdf_text(y)
    vals = []
    for pg in o['text']:
        v = [_num(x) for x in re.findall(VAL_RE, pg)]
        if len(v) >= 20:
            vals += v
    if len(vals) != 100:
        return None
    vals.sort(reverse=True)
    return {i + 1: v for i, v in enumerate(vals)}


def _value_in(v, Tval, tol=2):
    """原本の本文に価値の数字があるか（手がかりの転記の誤りを ±tol 百万ドルまで許す）→ 見つかった原本の値"""
    if not v:
        return None
    for d in sorted(range(-tol, tol + 1), key=abs):
        if f'{v + d:,}' in Tval:
            return v + d
    return None


SAMSUNG_TAG = 'https://news.samsung.com/global/tag/interbrand/'


def _samsung_tag():
    """Samsung の報道発表の一覧（Interbrand のタグ）。Samsung は研究用の UA を拒むので、ここだけ一般のブラウザ名で取る"""
    p = os.path.join(N.CACHE, 'samsung_tag_interbrand.html')
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        import urllib.request
        b = urllib.request.urlopen(urllib.request.Request(SAMSUNG_TAG, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read()
        open(p, 'wb').write(b)
    t = open(p, encoding='utf-8', errors='replace').read()
    return {u.rstrip('/').split('/')[-1]: d for u, d in re.findall(
        r'<a href="(https://news\.samsung\.com/global/[^"]+)" class="category_item">.*?<p class="category_data">([^<]+)</p>', t, re.S)}


def ib_release_date(y):
    """公開日（一次の出所から読み直す）。見つからなければ None"""
    if y not in IB_DATE_SRC:
        return None, None
    kind, ref = IB_DATE_SRC[y]
    if kind == 'samsung_tag':
        d = _samsung_tag().get(ref)
        if d:
            return datetime.datetime.strptime(d.strip(), '%B %d, %Y').date().isoformat(), SAMSUNG_TAG + ' → ' + ref
        return None, SAMSUNG_TAG
    url = PRN.format(ref) if kind == 'prn' else ref
    try:
        t = _txt(url, f'ib_date_{y}.html')
    except Exception as e:  # noqa
        return None, f'{url} 取得失敗 {e}'
    x = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S))))
    pats = [r'(?:NEW YORK|LONDON)\s*,\s*([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(\d{4})\s*/PRNewswire/',
            r'"datePublished"\s*:\s*"(\d{4})-(\d{2})-(\d{2})',
            r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s+(20\d\d)']
    m = re.search(r'"datePublished"\s*:\s*"(\d{4})-(\d{2})-(\d{2})', t)
    if m and int(m.group(1)) == y:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}', url
    for p in (pats[0], pats[2]):
        for m in re.finditer(p, x):
            mon, d, yy = m.groups()
            try:
                dt = datetime.datetime.strptime(f'{mon[:3]} {d} {yy}', '%b %d %Y').date()
            except ValueError:
                continue
            if dt.year == y:
                return dt.isoformat(), url
    if kind == 'url':  # 日付が URL に入っている（Honda: c141009）
        m = re.search(r'/c(\d{2})(\d{2})(\d{2})eng', url)
        if m:
            return f'20{m.group(1)}-{m.group(2)}-{m.group(3)}', url
    return None, url


def build_interbrand():
    years = {}
    for y in range(2000, 2026):
        api = ib_api(y)
        rec = {'year': y, 'api_n': len(api)}
        if y >= 2020:
            rows = [dict(r, src='api') for r in api]
            rec.update(status='complete_primary', rows=rows)
        elif y in IB_PRN_TABLE:
            prn = ib_prn_table(y)
            amap = {norm(r['name']): r for r in api}
            rows = []
            for r in prn:
                a = amap.get(norm(r['name']))
                rows.append(dict(r, src='prn', api_match=bool(a and a['rank'] == r['rank'])))
            rec.update(status='complete_primary' if len(rows) == 100 else 'incomplete', rows=rows)
            rec['pdf'] = {k: v for k, v in ib_pdf_text(y).items() if k != 'text'}
        elif y in IB_PDF:
            pdf = ib_pdf_text(y)
            T = norm(' '.join(pdf['text']))
            Tval = re.sub(r'\s', '', ' '.join(pdf['text']))
            grid = ib_pdf_grid(y)
            aid = {r['rank']: r for r in ib_aid(y)}
            have = {r['rank'] for r in api}
            api_names = {norm(r['name']) for r in api}
            rows = [dict(r, src='api') for r in api]
            conflicts = []
            for rk in sorted(set(range(1, 101)) - have):
                a = aid.get(rk)
                if not a:
                    rows.append({'rank': rk, 'name': None, 'value': (grid or {}).get(rk), 'src': 'missing'})
                    continue
                n = norm(a['name'])
                if n in api_names:   # API が同じブランドを別の順位で持っている（API 側の順位の誤り）
                    conflicts.append({'rank_missing': rk, 'aid': a, 'api': [r for r in api if norm(r['name']) == n]})
                    continue
                names = [n] + ALIAS.get(n, [])
                name_in = any(k and k in T for k in names)
                pv = _value_in(a['value'], Tval)
                grid_ok = bool(grid and grid.get(rk) == a['value'])
                if name_in and (pv or grid_ok):
                    src = 'pdf_name_value'
                elif grid_ok:
                    src = 'pdf_grid_value'      # 名前は原本でロゴ（画像）・順位と価値は原本の表と一致
                elif pv:
                    src = 'pdf_value_only'
                elif name_in:
                    src = 'pdf_name_only'
                else:
                    src = 'aid_unverified'
                rows.append({'rank': rk, 'name': a['name'], 'value': pv or a['value'], 'src': src, 'aid_value': a['value']})
            mism = [(r['rank'], r['name'], r['value'], grid.get(r['rank'])) for r in api if grid and grid.get(r['rank']) != r['value']]
            n_bad = sum(1 for r in rows if r['src'] in ('aid_unverified', 'missing', 'pdf_name_only'))
            rec.update(status='complete_primary_plus_aid' if (n_bad == 0 and len(rows) == 100) else 'has_unverified',
                       rows=sorted(rows, key=lambda r: r['rank']), rank_conflicts=conflicts,
                       pdf={k: v for k, v in pdf.items() if k != 'text'}, grid_parsed=bool(grid), api_vs_grid_mismatch=mism)
        else:
            rec.update(status='survivor_only_api', rows=[dict(r, src='api') for r in api])
        d, src = ib_release_date(y)
        rec['release_date'], rec['release_src'] = d, src
        rec['src_counts'] = {}
        for r in rec['rows']:
            rec['src_counts'][r['src']] = rec['src_counts'].get(r['src'], 0) + 1
        years[y] = rec
    return years


# ───────────────────────── Interbrand: ブランド → 親会社 → 株の記号（測る前に固定） ─────────────────────────
# 親会社は**その一覧を買う月（形成月）に**そのブランドを持っていた会社（買収・分離・上場・非公開化を月単位で）。
# yahoo = Yahoo の記号の候補（先に書いたものから、形成月の値がある最初のものを使う）。None = 値が無い（非上場・上場廃止で Yahoo に無い）。
# us = 普通株の主な上場が NYSE/Nasdaq（米国版の母集団）。hq = 本社の国（ISO2）。記号の末尾で通貨が決まる（CCY）。
P = {}


def _p(pid, name, yahoo, hq, us, note=''):
    P[pid] = {'name': name, 'yahoo': yahoo if isinstance(yahoo, list) or yahoo is None else [yahoo], 'hq': hq, 'us': us, 'note': note}


for _pid, _nm in [('MMM', '3M'), ('ADBE', 'Adobe'), ('AIG', 'AIG'), ('ABNB', 'Airbnb'), ('AMZN', 'Amazon'), ('AXP', 'American Express'),
                  ('AAPL', 'Apple'), ('BLK', 'BlackRock'), ('BKNG', 'Booking Holdings'), ('CPB', "Campbell's"), ('CAT', 'Caterpillar'),
                  ('GM', 'General Motors (2010-11 再上場後)'), ('CSCO', 'Cisco'), ('C', 'Citigroup'), ('KO', 'Coca-Cola'), ('CL', 'Colgate-Palmolive'),
                  ('DIS', 'Disney'), ('PG', 'Procter & Gamble'), ('EBAY', 'eBay'), ('FDX', 'FedEx'), ('F', 'Ford'), ('GE', 'General Electric'),
                  ('GS', 'Goldman Sachs'), ('GOOGL', 'Alphabet/Google'), ('HOG', 'Harley-Davidson'), ('HPQ', 'HP Inc/Hewlett-Packard'),
                  ('IBM', 'IBM'), ('INTC', 'Intel'), ('JPM', 'JPMorgan Chase'), ('BF-B', 'Brown-Forman'), ('DE', 'Deere'), ('JNJ', 'Johnson & Johnson'),
                  ('NKE', 'Nike'), ('K', "Kellogg/Kellanova"), ('YUM', 'Yum! Brands'), ('KMB', 'Kimberly-Clark'), ('MO', 'Altria'), ('PM', 'Philip Morris International'),
                  ('MAR', 'Marriott'), ('MA', 'Mastercard'), ('MCD', "McDonald's"), ('MSFT', 'Microsoft'), ('MNST', 'Monster Beverage'),
                  ('MS', 'Morgan Stanley'), ('NDAQ', 'Nasdaq Inc'), ('NFLX', 'Netflix'), ('NVDA', 'NVIDIA'), ('ORCL', 'Oracle'), ('PEP', 'PepsiCo'),
                  ('QCOM', 'Qualcomm'), ('RL', 'Ralph Lauren'), ('CRM', 'Salesforce'), ('SBUX', 'Starbucks'), ('TSLA', 'Tesla'), ('UPS', 'UPS'),
                  ('XRX', 'Xerox'), ('BRK-B', 'Berkshire Hathaway')]:
    _p(_pid, _nm, _pid, 'US', True)
_p('ACN', 'Accenture', 'ACN', 'IE', True, '本社はアイルランド・株は NYSE だけ')
_p('SPOT', 'Spotify', 'SPOT', 'LU', True, '本社はルクセンブルク/スウェーデン・株は NYSE だけ（2018-04 上場）')
_p('META', 'Meta/Facebook', 'META', 'US', True, '2012-05 上場')
_p('PYPL', 'PayPal', 'PYPL', 'US', True, '2015-07 eBay から分離上場')
_p('HPE', 'Hewlett Packard Enterprise', 'HPE', 'US', True, '2015-11 分離上場')
_p('V', 'Visa', 'V', 'US', True, '2008-03 上場')
_p('UBER', 'Uber', 'UBER', 'US', True, '2019-05 上場')
_p('ZM', 'Zoom', 'ZM', 'US', True, '2019-04 上場')
_p('DELL', 'Dell Technologies', 'DELL', 'US', True, '2018-12-28 再上場')
_p('WBD', 'Discovery → Warner Bros. Discovery', 'WBD', 'US', True, 'Discovery Communications の継承')
_p('MDLZ', 'Kraft Foods Inc → Mondelez', 'MDLZ', 'US', True, 'Kraft Foods Inc の法的な継承（2012-10 に Kraft Foods Group を分離）')
_p('MSI', 'Motorola Inc → Motorola Solutions', 'MSI', 'US', True, 'Motorola Inc の法的な継承（2011-01 に Motorola Mobility を分離）')
_p('GAP', 'Gap Inc', ['GAP', 'GPS'], 'US', True)
_p('AVP', 'Avon Products', ['AVP'], 'US', True, '2020-01 Natura が買収（上場廃止）')
_p('KHC', 'Kraft Heinz', 'KHC', 'US', True, '2015-07 上場')
_p('QSR', 'Restaurant Brands Intl', 'QSR', 'CA', False)
# 上場廃止して Yahoo に値が無い（または別会社が記号を使っている）米国の親会社
for _pid, _nm, _nt in [('BUD_OLD', 'Anheuser-Busch Cos', '2008-11-18 InBev が買収'), ('BKC_OLD', 'Burger King Holdings', '2010-10 3G が買収'),
                       ('DELL_INC', 'Dell Inc', '2013-10-29 非公開化'), ('EK_OLD', 'Eastman Kodak（旧）', '2012-01 破産・2013 再上場は別の株'),
                       ('HNZ_OLD', 'H.J. Heinz', '2013-06 Berkshire/3G が買収'), ('HTZ_OLD', 'Hertz Global Holdings（旧）', '2020 破産'),
                       ('MER_OLD', 'Merrill Lynch', '2009-01 Bank of America が買収'), ('TIF_OLD', 'Tiffany & Co', '2021-01 LVMH が買収'),
                       ('VIAB_OLD', 'Viacom Inc（2006-2019）', '2019-12 CBS と合併（記号の継承は CBS 側）'), ('WWY_OLD', 'Wrigley', '2008-10 Mars が買収'),
                       ('YHOO_OLD', 'Yahoo! Inc', '2017-06 本業を Verizon へ売却・Altaba へ'), ('LNKD_OLD', 'LinkedIn', '2016-12 Microsoft が買収')]:
    _p(_pid, _nm, None, 'US', True, _nt)
OLD_TICKER = {  # 上場廃止した親会社の当時の記号と最後の月（測る道具が Yahoo 以外の出所を当たるときの鍵。記号が別会社に再利用されたものは reused）
    'BUD_OLD': ('BUD', 200811, 'reused'), 'BKC_OLD': ('BKC', 201010, ''), 'DELL_INC': ('DELL', 201310, 'reused'), 'EK_OLD': ('EK', 201201, ''),
    'HNZ_OLD': ('HNZ', 201306, ''), 'HTZ_OLD': ('HTZ', 202005, 'reused'), 'MER_OLD': ('MER', 200812, ''), 'TIF_OLD': ('TIF', 202101, ''),
    'VIAB_OLD': ('VIAB', 201912, ''), 'WWY_OLD': ('WWY', 200810, ''), 'YHOO_OLD': ('YHOO', 201706, ''), 'LNKD_OLD': ('LNKD', 201612, ''),
    'REUTERS_OLD': ('RTR.L', 200804, ''), 'GMODELO': ('GMODELOC.MX', 201306, ''),
}
# 米国外
for _pid, _nm, _y, _hq in [('ADS', 'adidas', 'ADS.DE', 'DE'), ('ALV', 'Allianz', 'ALV.DE', 'DE'), ('VW', 'Volkswagen', 'VOW3.DE', 'DE'),
                          ('AXA', 'AXA', 'CS.PA', 'FR'), ('BARC', 'Barclays', 'BARC.L', 'GB'), ('BB', 'BlackBerry/RIM', ['BB.TO', 'BB'], 'CA'),
                          ('BMW', 'BMW', 'BMW.DE', 'DE'), ('BP', 'BP', 'BP.L', 'GB'), ('ABI', 'AB InBev', ['ABI.BR', 'BUD'], 'BE'),
                          ('BRBY', 'Burberry', 'BRBY.L', 'GB'), ('BYD', 'BYD', '1211.HK', 'CN'), ('CANON', 'Canon', '7751.T', 'JP'),
                          ('CFR', 'Richemont', 'CFR.SW', 'CH'), ('CSGN', 'Credit Suisse', ['CSGN.SW', 'CS'], 'CH'), ('BN', 'Danone', 'BN.PA', 'FR'),
                          ('DHL', 'Deutsche Post DHL', ['DHL.DE', 'DPW.DE'], 'DE'), ('CDI', 'Christian Dior SE', 'CDI.PA', 'FR'), ('LVMH', 'LVMH', 'MC.PA', 'FR'),
                          ('FIAT', 'Fiat / FCA', ['STLAM.MI', 'FCAU', 'F.MI'], 'IT'), ('RACE', 'Ferrari', ['RACE', 'RACE.MI'], 'IT'),
                          ('HM', 'H&M', 'HM-B.ST', 'SE'), ('HEIA', 'Heineken', 'HEIA.AS', 'NL'), ('RMS', 'Hermès', 'RMS.PA', 'FR'),
                          ('HONDA', 'Honda', '7267.T', 'JP'), ('HSBC', 'HSBC', ['HSBA.L', 'HSBC'], 'GB'), ('HTC', 'HTC', '2498.TW', 'TW'),
                          ('BOSS', 'Hugo Boss', 'BOSS.DE', 'DE'), ('HYUNDAI', 'Hyundai Motor', '005380.KS', 'KR'), ('ING', 'ING', ['INGA.AS', 'ING'], 'NL'),
                          ('DGE', 'Diageo', ['DGE.L', 'DEO'], 'GB'), ('KIA', 'Kia', '000270.KS', 'KR'), ('OR', "L'Oréal", 'OR.PA', 'FR'),
                          ('TATAMOTORS', 'Tata Motors', ['TATAMOTORS.NS', 'TTM'], 'IN'), ('TMPV', 'Tata Motors Passenger Vehicles（2025-10 分割後）', ['TMPV.NS', 'TATAMOTORS.NS'], 'IN'),
                          ('LENOVO', 'Lenovo', '0992.HK', 'CN'), ('LGE', 'LG Electronics', '066570.KS', 'KR'), ('TOYOTA', 'Toyota', '7203.T', 'JP'),
                          ('MBG', 'Daimler → Mercedes-Benz Group', ['MBG.DE', 'DAI.DE'], 'DE'), ('NESTLE', 'Nestlé', 'NESN.SW', 'CH'),
                          ('NINTENDO', 'Nintendo', '7974.T', 'JP'), ('NISSAN', 'Nissan', '7201.T', 'JP'), ('BEI', 'Beiersdorf', 'BEI.DE', 'DE'),
                          ('NOKIA', 'Nokia', ['NOKIA.HE', 'NOK'], 'FI'), ('PANASONIC', 'Panasonic', '6752.T', 'JP'), ('PANDORA', 'Pandora', 'PNDORA.CO', 'DK'),
                          ('PHILIPS', 'Philips', ['PHIA.AS', 'PHG'], 'NL'), ('PAH3', 'Porsche SE', 'PAH3.DE', 'DE'), ('P911', 'Porsche AG', 'P911.DE', 'DE'),
                          ('PRADA', 'Prada', '1913.HK', 'IT'), ('PUMA', 'Puma', 'PUM.DE', 'DE'), ('SAMSUNG', 'Samsung Electronics', '005930.KS', 'KR'),
                          ('SAN', 'Santander', ['SAN.MC', 'SAN'], 'ES'), ('SAP', 'SAP', ['SAP.DE', 'SAP'], 'DE'), ('SU', 'Schneider Electric', 'SU.PA', 'FR'),
                          ('SHELL', 'Shell', ['SHEL.L', 'SHEL', 'RDSA.AS'], 'GB'), ('SHOP', 'Shopify', ['SHOP.TO', 'SHOP'], 'CA'), ('SIE', 'Siemens', 'SIE.DE', 'DE'),
                          ('SONY', 'Sony', '6758.T', 'JP'), ('SUBARU', 'Subaru', '7270.T', 'JP'), ('TRI', 'Thomson Reuters', ['TRI.TO', 'TRI'], 'CA'),
                          ('UBS', 'UBS', ['UBSG.SW', 'UBS'], 'CH'), ('FASTRET', 'Fast Retailing', '9983.T', 'JP'), ('ITX', 'Inditex', 'ITX.MC', 'ES'),
                          ('XIAOMI', 'Xiaomi', '1810.HK', 'CN'), ('ZURN', 'Zurich Insurance', 'ZURN.SW', 'CH'), ('KERING', 'PPR → Kering', 'KER.PA', 'FR')]:
    _p(_pid, _nm, _y, _hq, False)
_p('GMODELO', 'Grupo Modelo', None, 'MX', False, '2013-06 AB InBev が残りを買収・Yahoo に値が無い見込み')
_p('REUTERS_OLD', 'Reuters Group plc', None, 'GB', False, '2008-04 Thomson が買収')
_p('PRIVATE', '非上場', None, None, False, '買えない＝母集団から外す')

BRAND_OWNER = {  # 正規化したブランド名 → [(自 yyyymm, 至 yyyymm, 親会社)]（None は端なし）
    'marlboro': [(None, 200802, 'MO'), (200803, None, 'PM')],
    'budweiser': [(None, 200811, 'BUD_OLD'), (200812, None, 'ABI')],
    'corona': [(None, 201305, 'GMODELO'), (201306, None, 'ABI')],
    'dell': [(None, 201310, 'DELL_INC'), (201311, 201812, 'PRIVATE'), (201901, None, 'DELL')],
    'dior': [(None, 201706, 'CDI'), (201707, None, 'LVMH')],
    'tiffanyco': [(None, 202012, 'TIF_OLD'), (202101, None, 'LVMH')],
    'ferrari': [(None, 201512, 'FIAT'), (201601, None, 'RACE')],
    'porsche': [(None, 201207, 'PAH3'), (201208, 202209, 'VW'), (202210, None, 'P911')],
    'prada': [(None, 201105, 'PRIVATE'), (201106, None, 'PRADA')],
    'wrigley': [(None, 200809, 'WWY_OLD'), (200810, None, 'PRIVATE')],
    'burgerking': [(None, 201009, 'BKC_OLD'), (201010, 201205, 'PRIVATE'), (201206, None, 'QSR')],
    'heinz': [(None, 201305, 'HNZ_OLD'), (201306, 201506, 'PRIVATE'), (201507, None, 'KHC')],
    'linkedin': [(None, 201105, 'PRIVATE'), (201106, 201611, 'LNKD_OLD'), (201612, None, 'MSFT')],
    'paypal': [(None, 201506, 'EBAY'), (201507, None, 'PYPL')],
    'duracell': [(None, 201602, 'PG'), (201603, None, 'BRK-B')],
    'thomsonreuters': [(None, 200803, 'REUTERS_OLD'), (200804, None, 'TRI')],
    'landrover': [(None, 202509, 'TATAMOTORS'), (202510, None, 'TMPV')],
    'chevrolet': [(None, 201010, 'PRIVATE'), (201011, None, 'GM')],   # 旧 GM は 2009-06 破産（一覧は 2013・2014 だけ）
    'mtv': [(None, 201911, 'VIAB_OLD')],
}
BRAND_OWNER['rangerover'] = BRAND_OWNER['landrover']
for _k in ('dellemc', 'delltechnologies'):
    BRAND_OWNER[_k] = BRAND_OWNER['dell']
for _pid, _brands in {
    'MMM': ['3m'], 'ACN': ['accenture'], 'ADS': ['adidas'], 'ADBE': ['adobe'], 'AIG': ['aig'], 'ABNB': ['airbnb'], 'ALV': ['allianz'],
    'AMZN': ['amazon', 'amazoncom'], 'AXP': ['americanexpress'], 'AAPL': ['apple'], 'PRIVATE': ['armani', 'giorgioarmani', 'chanel', 'ikea', 'lego', 'redbull', 'rolex', 'huawei'],
    'VW': ['audi', 'volkswagen'], 'AVP': ['avon'], 'AXA': ['axa'], 'BARC': ['barclays'], 'BB': ['blackberry'], 'BLK': ['blackrock'], 'BMW': ['bmw', 'mini'],
    'BKNG': ['bookingcom'], 'BP': ['bp'], 'BRBY': ['burberry'], 'BYD': ['byd'], 'CPB': ['campbells'], 'CANON': ['canon'], 'CFR': ['cartier'],
    'CAT': ['caterpillar'], 'CSCO': ['cisco'], 'C': ['citi'], 'KO': ['cocacola', 'sprite'], 'CL': ['colgate'], 'CSGN': ['creditsuisse'], 'BN': ['danone'],
    'DHL': ['dhl'], 'WBD': ['discovery', 'discoverychannel'], 'DIS': ['disney'], 'EK_OLD': ['eastmankodak'], 'EBAY': ['ebay'], 'META': ['facebook', 'instagram'],
    'FDX': ['fedex'], 'F': ['ford'], 'GAP': ['gap'], 'GE': ['ge', 'geaerospace'], 'PG': ['gillette', 'pampers'], 'GS': ['goldmansachs'],
    'GOOGL': ['google', 'youtube'], 'KERING': ['gucci'], 'HOG': ['harleydavidson'], 'HEIA': ['heineken'], 'LVMH': ['hennessy', 'louisvuitton', 'moetchandon', 'moetetchandon', 'sephora'],
    'RMS': ['hermes'], 'HTZ_OLD': ['hertz'], 'HPE': ['hewlettpackardenterprise'], 'HM': ['hm'], 'HONDA': ['honda'], 'HPQ': ['hp'], 'HSBC': ['hsbc'],
    'HTC': ['htc'], 'BOSS': ['hugoboss'], 'HYUNDAI': ['hyundai'], 'IBM': ['ibm'], 'ING': ['ing'], 'INTC': ['intel'], 'BF-B': ['jackdaniels'], 'DE': ['johndeere'],
    'DGE': ['johnniewalker', 'smirnoff'], 'JNJ': ['johnsonjohnson'], 'NKE': ['jordan', 'nike'], 'JPM': ['jpmorgan'], 'K': ['kelloggs'], 'YUM': ['kfc', 'pizzahut'],
    'KIA': ['kia'], 'KMB': ['kleenex'], 'MDLZ': ['kraftfoodsgroup'], 'OR': ['lancome', 'loreal', 'lorealparis'], 'LENOVO': ['lenovo'], 'TOYOTA': ['lexus', 'toyota'],
    'LGE': ['lg'], 'MAR': ['marriottinternational'], 'MA': ['mastercard'], 'MCD': ['mcdonalds'], 'MBG': ['mercedesbenz'], 'MER_OLD': ['merrilllynch'],
    'MSFT': ['microsoft'], 'MNST': ['monster'], 'MS': ['morganstanley'], 'MSI': ['motorola'], 'NDAQ': ['nasdaq'], 'NESTLE': ['nescafe', 'nespresso', 'nestle'],
    'NFLX': ['netflix'], 'NINTENDO': ['nintendo'], 'NISSAN': ['nissan'], 'BEI': ['nivea'], 'NOKIA': ['nokia'], 'NVDA': ['nvidia'], 'ORCL': ['oracle'],
    'PANASONIC': ['panasonic'], 'PANDORA': ['pandora'], 'PEP': ['pepsi'], 'PHILIPS': ['philips'], 'PUMA': ['puma'], 'QCOM': ['qualcomm'], 'RL': ['ralphlauren'],
    'CRM': ['salesforce'], 'SAMSUNG': ['samsung'], 'SAN': ['santander'], 'SAP': ['sap'], 'SU': ['schneiderelectric'], 'SHELL': ['shell'], 'SHOP': ['shopify'],
    'SIE': ['siemens'], 'SONY': ['sony'], 'SPOT': ['spotify'], 'SBUX': ['starbucks'], 'SUBARU': ['subaru'], 'TSLA': ['tesla'], 'UBER': ['uber'], 'UBS': ['ubs'],
    'FASTRET': ['uniqlo'], 'UPS': ['ups'], 'V': ['visa'], 'XRX': ['xerox'], 'XIAOMI': ['xiaomi'], 'YHOO_OLD': ['yahoo'], 'ITX': ['zara'], 'ZM': ['zoom'], 'ZURN': ['zurich'],
}.items():
    for _b in _brands:
        BRAND_OWNER.setdefault(_b, [(None, None, _pid)])
EVENTS = [  # 持っている間に起きうる分離（spin-off）。Yahoo の調整後終値が分離を反映していなければ、測る道具が分離の比率を一次の出所（8-K 等）で確かめて合算する
    ('MO', 200803, 'PM を分離'), ('MSI', 201101, 'Motorola Mobility を分離'), ('MDLZ', 201210, 'Kraft Foods Group を分離'), ('EBAY', 201507, 'PayPal を分離'),
    ('HPQ', 201511, 'HPE を分離'), ('FIAT', 201601, 'Ferrari を分離'), ('YUM', 201611, 'Yum China を分離'), ('KERING', 201805, 'Puma 株を配当'),
    ('SIE', 202009, 'Siemens Energy を分離'), ('IBM', 202111, 'Kyndryl を分離'), ('DELL', 202111, 'VMware を分離'), ('MBG', 202112, 'Daimler Truck を分離'),
    ('GE', 202301, 'GE HealthCare を分離'), ('GE', 202404, 'GE Vernova を分離'), ('K', 202310, 'WK Kellogg を分離'), ('JNJ', 202308, 'Kenvue の交換買付'),
    ('MMM', 202404, 'Solventum を分離'), ('TATAMOTORS', 202510, '商用車を分割'), ('CFR', 200810, 'Reinet・BAT 株を分離'),
]


def ib_owner(brand, yyyymm):
    n = norm(brand)
    for a, z, pid in BRAND_OWNER.get(n, []):
        if (a is None or yyyymm >= a) and (z is None or yyyymm <= z):
            return pid
    return None


# ───────────────────────── Fortune World's Most Admired Companies ─────────────────────────
def _next_data(t):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    return json.loads(m.group(1)) if m else None


def build_wmac():
    years = {}
    for y in range(2014, 2027):
        t = _txt(WMAC.format(y), f'wmac_{y}.html')
        fs = _next_data(t)['props']['pageProps']['franchiseSearch']
        if str(fs.get('year')) != str(y):
            raise SystemExit(f'WMAC {y}: ページの年が {fs.get("year")}')
        rows = []
        for x in fs['items']:
            d = x.get('data') or {}
            rk = x.get('rank')
            rows.append({'name': x['name'], 'slug': x['slug'], 'allstar_rank': rk if rk and rk < 1000 else None,
                         'industry': d.get('Industry'), 'industry_rank': int(d['Industry Rank']) if str(d.get('Industry Rank', '')).isdigit() else None,
                         'country': d.get('Country') or d.get('HQ Country') or d.get('Region')})
        pub = datetime.datetime.utcfromtimestamp(int(fs['dateGmt'])).date().isoformat()
        years[y] = {'year': y, 'published_gmt': pub, 'n_items': len(rows), 'n_allstars': sum(1 for r in rows if r['allstar_rank']), 'rows': rows,
                    'source': WMAC.format(y)}
    return years


def fortune_company(slug):
    """Fortune の会社ページ → Ticker・取引所・会社の種類・国・脚注（買収された日など）"""
    try:
        t = _txt('https://fortune.com' + slug, 'fco_' + slug.strip('/').split('/')[-1] + '.html')
    except Exception as e:  # noqa
        return {'error': str(e)[:120]}
    d = _next_data(t)
    c = ((d or {}).get('props', {}).get('pageProps', {}) or {}).get('company') or {}
    ci = c.get('companyInfo') or {}
    return {'ticker': ci.get('Ticker'), 'exchange': ci.get('StockQuote'), 'type': ci.get('Company type'),
            'country': ci.get('Country/Territory'), 'footnote': ci.get('Footnote'), 'title': c.get('title')}


# ───────────────────────── Forbes World's Most Innovative Companies ─────────────────────────
def build_forbes():
    years = {}
    for y in range(2011, 2019):
        j = json.loads(_txt(FORBES.format(y), f'forbes_innov_{y}.json'))
        L = (j.get('organizationList') or {}).get('organizationsLists') or []
        rows = [{'rank': x.get('rank'), 'name': x.get('organizationName') or (x.get('organization') or {}).get('name'), 'uri': x.get('uri'),
                 'country': x.get('country'), 'industry': x.get('industry'), 'innovation_premium': x.get('innovationPremium')} for x in L]
        ds = sorted({x.get('date') for x in L if x.get('date')})
        pub = datetime.datetime.utcfromtimestamp(ds[-1] / 1000).date().isoformat() if ds else None
        ranks = [r['rank'] for r in rows if r['rank']]
        years[y] = {'year': y, 'published': pub, 'n': len(rows), 'missing_ranks': [k for k in range(1, 101) if k not in ranks],
                    'usable': len(rows) >= 99, 'rows': rows, 'source': FORBES.format(y)}
    return years


# ───────────────────────── Forbes（米国の会社だけ）: 名前 → 記号 ─────────────────────────
# SEC の company_tickers.json（今の上場会社）と名前で合わせ、合わないものは下の手の表（None＝上場廃止で Yahoo に値が無い見込み）
FORBES_US_MANUAL = {
    'Activision Blizzard': None, 'Acuity Brands': 'AYI', 'Adobe Systems': 'ADBE', 'Alexion Pharmaceuticals': None, 'Allergan': None,
    'Altera': None, 'Amazon.com': 'AMZN', 'AmerisourceBergen': 'COR', 'Amphenol': 'APH', 'Anadarko Petroleum': None, 'Bard': None, 'CR Bard': None,
    'Beam': None, 'Cameron International': None, 'Campbell Soup': 'CPB', 'Catamaran': None, 'Celgene': None, 'Cerner': None,
    'Church & Dwight': 'CHD', 'Citrix Systems': None, 'Clorox': 'CLX', 'Danaher': 'DHR', 'Estee Lauder Cos': 'EL', 'Estée Lauder Cos': 'EL',
    'The Estée Lauder Companies': 'EL', 'Express Scripts': None, 'FMC Technologies': None, 'Facebook': 'META', 'FleetCor Technologies': 'CPAY',
    'FleetCor Technologies ': 'CPAY', 'Google': 'GOOGL', 'IDEXX Laboratories': 'IDXX', 'Kellogg': 'K', 'Keurig Green Mountain': None,
    'Marriott International': 'MAR', 'McCormick': 'MKC', 'Mead Johnson Nutrition': None, 'Molson Coors Brewing': 'TAP', 'Mondelēz International': 'MDLZ',
    'Monsanto': None, 'Mylan': None, 'Nielsen': None, 'Praxair': None, 'Precision Castparts': None, 'Red Hat': None, 'Roper Industries': 'ROP',
    'Sirius XM Radio': 'SIRI', 'Starwood Hotels': None, 'Stericycle': 'SRCL', 'Teradata': 'TDC', 'Tesla Motors': 'TSLA', 'The Priceline Group': 'BKNG',
    'Tractor Supply': 'TSCO', 'Ulta Salon Cosmetcs & Fragrance': 'ULTA', 'VMware': None, 'Vertex Pharmaceuticals': 'VRTX', 'Whole Foods Market': None,
}


def _sec_hdrs():
    """SEC の User-Agent はリポジトリの hachimon_fetch.py の HDRS と同じ形（中の EMAIL をそのまま使う）"""
    src = open(os.path.join(N.BASE, 'hachimon_fetch.py'), encoding='utf-8').read()
    email = re.search(r'^EMAIL\s*=\s*"([^"]+)"', src, re.M).group(1)
    return {'User-Agent': f'hachimon-gate {email}'}


def sec_tickers():
    p = os.path.join(N.CACHE, 'sec_company_tickers.json')
    if not os.path.exists(p):
        import urllib.request
        b = urllib.request.urlopen(urllib.request.Request('https://www.sec.gov/files/company_tickers.json', headers=_sec_hdrs()), timeout=60).read()
        open(p, 'wb').write(b)
        time.sleep(0.2)
    return json.load(open(p))


def _cnorm(s):
    s = (s or '').lower().replace('&', ' and ')
    s = re.sub(r'\.com\b', '', s)
    s = re.sub(r'\b(inc|incorporated|corp|corporation|co|company|ltd|plc|holdings?|group|the|n\.?v|s\.?a|ag|se|lp|llc|class [a-z]|international|intl)\b', '', s)
    return re.sub(r'[^a-z0-9]', '', s)


def forbes_us_symbol(name, idx):
    if name in FORBES_US_MANUAL:
        return FORBES_US_MANUAL[name], 'manual'
    t = idx.get(_cnorm(name))
    return (t.replace('.', '-'), 'sec_name') if t else (None, 'unmatched')


# ───────────────────────── いつ買うか（測る前に固定） ─────────────────────────
def purchase_month(date_iso):
    """公開日 d → 買う月 M（M の月末の終値で買い、M+1 月から持つ）。d がその月の最終日なら翌月"""
    d = datetime.date.fromisoformat(date_iso)
    nxt = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    last = nxt - datetime.timedelta(days=1)
    m = d if d < last else nxt
    return m.year * 100 + m.month


def _ym_add(ym, k):
    y, m = divmod(ym // 100 * 12 + ym % 100 - 1 + k, 12)
    return y * 100 + m + 1


def ib_schedule(ib):
    """Interbrand の買う月の表。完全な原本の一覧がある年だけ買い直し、無い年（2015・2017）は前の一覧を持ち続ける。
    一次の公開日が無い年（2007・2008・2009・2013）は、原本 PDF の作成月の翌月（作成＝公開より前か同じ、を使った保守的な代わり）"""
    out = []
    for y in range(2007, 2026):
        r = ib[y]
        if not r['status'].startswith('complete'):
            out.append({'list_year': y, 'used': False, 'why': r['status']})
            continue
        if r.get('release_date'):
            m, how = purchase_month(r['release_date']), f"公開日 {r['release_date']}（{r['release_src']}）の後の最初の月末"
        else:
            c = (r.get('pdf') or {}).get('created', '')
            mm = re.search(r'D:(\d{4})(\d{2})', c)
            m, how = _ym_add(int(mm.group(1)) * 100 + int(mm.group(2)), 1), f'一次の公開日が見つからない＝原本 PDF の作成日 {c} の翌月の月末（保守的）'
        out.append({'list_year': y, 'used': True, 'buy_month': m, 'how': how})
    used = [x for x in out if x['used']]
    for a, b in zip(used, used[1:]):
        a['hold_last_month'] = b['buy_month']        # 次の一覧を買う月の月末まで持つ（その月のリターンまで）
    used[-1]['hold_last_month'] = None               # 最後の一覧はデータの終わりまで
    return out


WMAC_MANUAL = {  # Fortune の会社ページに記号が無い All-Stars（上場廃止・非公開・米国外の原株）と、記号の置き換え（測る前に固定）
    '/company/samsung-electronics/': '005930.KS', '/company/nordstrom/': 'JWN', '/company/st-jude-medical/': None,
    '/company/whole-foods-market/': None, '/company/dupont/': None, '/company/berkshire-hathaway/': 'BRK-B',
    '/company/publix-super-markets/': None, '/company/usaa/': None,
}
WMAC_OLD_TICKER = {'/company/whole-foods-market/': ('WFM', 201708, ''), '/company/st-jude-medical/': ('STJ', 201701, ''),
                   '/company/dupont/': ('DD', 201708, 'reused'), '/company/nordstrom/': ('JWN', 202505, '')}
WMAC_US_PRIMARY_FOREIGN = {'/company/accenture/'}   # 本社は米国外だが普通株の上場が NYSE だけ（Interbrand 側と同じ基準）


def wmac_yahoo(ci, country, slug=None):
    """Fortune の会社ページの Ticker → Yahoo の記号。米国の会社は記号そのまま（'.'→'-'）。米国外は Fortune の記号（多くは米国の ADR・OTC）"""
    if slug in WMAC_MANUAL:
        return WMAC_MANUAL[slug]
    t = (ci or {}).get('ticker')
    if not t:
        return None
    t = t.strip().split(',')[0].split(' ')[0]
    return t.replace('.', '-') if t else None


def _is_us(c):
    return (c or '').strip().lower() in ('u.s.', 'usa', 'united states', 'us')


def build_all():
    ib = build_interbrand()
    sched = ib_schedule(ib)
    for x in sched:
        if not x['used']:
            continue
        r = ib[x['list_year']]
        for row in r['rows']:
            pid = ib_owner(row['name'], x['buy_month'])
            pp = P.get(pid, {})
            row.update(owner=pid, owner_name=pp.get('name'), yahoo=pp.get('yahoo'), us=pp.get('us'), hq=pp.get('hq'))
    wm = build_wmac()
    info = {}
    for y in wm.values():
        for row in y['rows']:
            if row['slug'] not in info:
                info[row['slug']] = fortune_company(row['slug'])
            ci = info[row['slug']]
            ctry = row['country'] if row['country'] not in (None, '', 'Asia/Pacific', 'Europe') else (ci.get('country') or row['country'])
            row.update(ticker=ci.get('ticker'), exchange=ci.get('exchange'), ctype=ci.get('type'), footnote=ci.get('footnote'),
                       yahoo=wmac_yahoo(ci, ctry, row['slug']), us=_is_us(ctry) or row['slug'] in WMAC_US_PRIMARY_FOREIGN)
        y['buy_month'] = purchase_month(y['published_gmt'])
    wy = sorted(wm)
    for a, b in zip(wy, wy[1:]):
        wm[a]['hold_last_month'] = wm[b]['buy_month']
    wm[wy[-1]]['hold_last_month'] = None
    fb = build_forbes()
    idx = {}
    for v in sec_tickers().values():
        idx.setdefault(_cnorm(v['title']), v['ticker'])
    for y in fb.values():
        for row in y['rows']:
            row['us'] = _is_us(row['country'])
            row['yahoo'], row['map_how'] = forbes_us_symbol(row['name'], idx) if row['us'] else (None, 'non_us_not_mapped')
    fy = [y for y in sorted(fb) if fb[y]['usable']]
    for y in fy:
        fb[y]['buy_month'] = purchase_month(fb[y]['published'])
    for a, b in zip(fy, fy[1:]):
        fb[a]['hold_last_month'] = fb[b]['buy_month']
    fb[fy[-1]]['hold_last_month'] = _ym_add(fb[fy[-1]]['buy_month'], 12)   # 2018 年で終わった一覧＝最後は12か月持つ
    return {'generated': datetime.date.today().isoformat(), 'checked_not_used': CHECKED,
            'interbrand': {'years': ib, 'schedule': sched}, 'wmac': wm, 'forbes': fb,
            'parents': P, 'old_ticker': OLD_TICKER, 'wmac_old_ticker': WMAC_OLD_TICKER, 'brand_owner': {k: v for k, v in BRAND_OWNER.items()}, 'events': EVENTS}


def lists_sha(o):
    core = {'ib': [(x['list_year'], x.get('buy_month'), x.get('hold_last_month'),
                    [(r['rank'], r['name'], r.get('owner')) for r in o['interbrand']['years'][x['list_year']]['rows']] if x['used'] else None)
                   for x in o['interbrand']['schedule']],
            'wmac': [(y, v['buy_month'], [(r['name'], r['allstar_rank'], r['industry_rank'], r['yahoo'], r['us']) for r in v['rows']]) for y, v in sorted(o['wmac'].items())],
            'forbes': [(y, v.get('buy_month'), [(r['rank'], r['name'], r['country']) for r in v['rows']]) for y, v in sorted(o['forbes'].items())]}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def show(o):
    print('== Interbrand')
    for x in o['interbrand']['schedule']:
        r = o['interbrand']['years'][x['list_year']]
        if not x['used']:
            print(x['list_year'], '使わない（持ち越し）', x['why'], 'API', r['api_n'])
            continue
        rows = r['rows']
        own = {}
        for row in rows:
            k = 'private' if row['owner'] == 'PRIVATE' else ('no_yahoo' if not row.get('yahoo') else ('us' if row.get('us') else 'nonus'))
            own[k] = own.get(k, 0) + 1
        par_us = len({row['owner'] for row in rows if row.get('us') and row.get('yahoo')})
        par_all = len({row['owner'] for row in rows if row.get('yahoo')})
        print(x['list_year'], x['buy_month'], '→', x['hold_last_month'], r['src_counts'], own, '米国の親会社', par_us, '全体', par_all)
    print('== Fortune WMAC')
    for y, v in sorted(o['wmac'].items()):
        st = [r for r in v['rows'] if r['allstar_rank']]
        print(y, v['buy_month'], '→', v['hold_last_month'], 'All-Stars', len(st), '米国', sum(1 for r in st if r['us']),
              '記号あり', sum(1 for r in st if r['yahoo']), '候補全体', len(v['rows']), '記号あり', sum(1 for r in v['rows'] if r['yahoo']))
    print('== Forbes')
    for y, v in sorted(o['forbes'].items()):
        print(y, v['published'], v['n'], 'usable' if v['usable'] else 'NOT USED', v.get('buy_month'), '→', v.get('hold_last_month'),
              '米国', sum(1 for r in v['rows'] if _is_us(r['country'])))


if __name__ == '__main__' and '--ib-only' not in sys.argv:
    if '--show' in sys.argv and os.path.exists(OUT):
        o = json.load(open(OUT))
        o['interbrand']['years'] = {int(k): v for k, v in o['interbrand']['years'].items()}
        o['wmac'] = {int(k): v for k, v in o['wmac'].items()}
        o['forbes'] = {int(k): v for k, v in o['forbes'].items()}
    else:
        o = build_all()
        o['lists_sha256'] = lists_sha(o)
        json.dump(o, open(OUT, 'w'), ensure_ascii=False, indent=0, default=list)
    show(o)
    print('lists_sha256', o.get('lists_sha256'), OUT)


if __name__ == '__main__' and '--ib-only' in sys.argv:
    ib = build_interbrand()
    for y, r in ib.items():
        print(y, r['status'], len(r['rows']), r['src_counts'], r.get('release_date'), (r.get('pdf') or {}).get('created'), 'grid' if r.get('grid_parsed') else '',
              r.get('api_vs_grid_mismatch', [])[:3])
        for x in r['rows']:
            if x['src'] not in ('api', 'prn', 'pdf_name_value'):
                print('    ', x)
