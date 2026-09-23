#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_extract.py — **irr の機構文を原本から機械で抜く**（2026-08-07新設）

なぜ要るか:
  2026-08-05 の全数検算で確立した irr=85 の試験は「**顧客の側が再認定・再試験をやり直すか**」ただ一点。
  この判定は原本の**文そのもの**を見ないと下せない——値でも語の有無でもなく、**引用の向き**が決める。
  実際、台帳で85を取り消した42社の誤りは3種類とも「向き」の誤りだった:
    (1) 自社が取得する側の認証（RMDの自社特許・IRMDの自社510(k)・HEIのFAA PMA）
    (2) 逆向きの文（NVDAの『suppliers that are certified by ISO』＝当社のサプライヤ／
        MSIの『reduce barriers to entry』＝障壁が下がる／ASMLの『single-source key components』＝当社の供給リスク）
    (3) 願望形（CDNSの『We work closely with』・AEIS『depend on our products being designed into』）

  そこで**全銘柄に同じ抽出を掛ける**。読み手ごとに実装が割れると、v9.9.65の掟
  「同じ台帳を見る二つの検査器が違うことを言ってはいけない」を読解の側で破ることになる。

何をするか:
  1. SEC submissions API から**最新の年次報告**（10-K / 20-F / 40-F）を解決する
  2. 本文を取得してタグを剥がす
  3. 機構語（qualif / certif / design-in / sole source / switching / approved vendor …）を含む
     **文**を前後の文脈つきで抜く
  4. 向きの手がかり（主語が customer か we か）を機械で印付けする——**判定はしない**。
     判定は読み手（審査官）の仕事で、この道具は**同じ材料を全員に配る**のが役目

使い方:
  python3 night/irr85_extract.py NVDA              ティッカーで解決
  python3 night/irr85_extract.py NVDA 0001045810   CIKを直に渡す（速い）
  python3 night/irr85_extract.py --json NVDA       JSONで出す
"""
import html
import json
import re
import sys
import time
import urllib.request

UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com'}

# 機構語（この語を含む文だけを抜く）
CORE = re.compile(
    r'\b(re-?qualif\w*|qualif\w*|certif\w*|design(?:ed)?[- ]in|design win|switching cost\w*'
    r'|sole[- ]source|single[- ]source|sole provider|approved vendor|approved product'
    r'|qualified product|incumbent supplier|installed base|lock[- ]?in)\b', re.I)

# 向きの手がかり（顧客側が負担する側＝85の条件）
CUST = re.compile(
    r'\b(our customers?|the customers?|OEMs?|end users?|customers[’\']|purchasers?'
    r'|manufacturers?|utilit(?:y|ies)|airframe|semiconductor manufacturers?)\b', re.I)
# 逆向き（当社が取得する側・当社の調達先）
SELF = re.compile(
    r'\b(we (?:are|have been|must|need to|seek to|work|rely|select|source|purchase|obtain|maintain)'
    r'|our (?:suppliers?|vendors?|subcontractors?|foundr\w+|contract manufacturers?)'
    r'|we (?:qualify|certify)|our (?:ISO|FDA|FAA|510\(k\))|obtain and maintain)\b', re.I)
# 願望形（歴史で P=0.40 だった型）
WISH = re.compile(r'\b(we (?:work closely|strive|seek|endeavor|aim)|depend(?:s|ent)? on '
                  r'(?:our products?|being)|may be able to|we believe we (?:are|will))\b', re.I)


def get(u, tries=4):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:
            err = e
            time.sleep(1.5)
    raise SystemExit(f'取得失敗: {u} ({err})')


def cik_of(t):
    j = json.loads(get('https://www.sec.gov/files/company_tickers.json'))
    for v in j.values():
        if v['ticker'].upper() == t.upper():
            return str(v['cik_str']).zfill(10)
    raise SystemExit(f'CIK不明: {t}')


ANNUAL_FORMS = ('10-K', '20-F', '40-F')


def latest_annual(cik):
    """最新の年次報告を **SEC submissions API** で解決する（companyfacts は使わない）。

    ★2026-09-23（宿題 irr_tools_40f_gap の(2)）: companyfacts の「最新の 40-F」は submissions より
      遅れることがある（実測 CGI: 2024-12-18 vs 2025-12-17／CAE: 2025-06-20 vs 2026-06-22）。
      年次報告の特定は必ずこちらで行う。recent に年次報告が無い古い提出体は filings.files の
      続きのページも見る（黙って「年次報告が無い」にしない）。
    ★40-F は包み紙で、年次の中身は添付（EX-99.x の AIF・MD&A・財務諸表／EX-1 等）に在る。
      返り値の `docs` に**本体＋年次の添付**を並べる（10-K/20-F は本体1件だけ＝従来どおり）。
      `url` は従来どおり本体（primaryDocument）を指す。"""
    j = json.loads(get(f'https://data.sec.gov/submissions/CIK{cik}.json'))

    def pick(rec):
        best = None
        for i, f in enumerate(rec.get('form') or []):
            if f in ANNUAL_FORMS and (best is None or rec['filingDate'][i] > rec['filingDate'][best]):
                best = i
        return best

    rec = j['filings']['recent']
    i = pick(rec)
    if i is None:
        for fl in (j['filings'].get('files') or [])[:4]:
            try:
                rec = json.loads(get('https://data.sec.gov/submissions/' + fl['name']))
            except SystemExit:
                continue
            i = pick(rec)
            if i is not None:
                break
    if i is None:
        return None
    f = rec['form'][i]
    accn = rec['accessionNumber'][i]
    acc = accn.replace('-', '')
    doc = rec['primaryDocument'][i]
    url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}'
    out = dict(form=f, filed=rec['filingDate'][i], report=rec['reportDate'][i],
               url=url, accn=accn,
               name=j.get('name'), sic=str(j.get('sic') or ''),
               sicDesc=j.get('sicDescription'))
    out['docs'] = annual_docs(cik, accn, f, url)
    return out


# ── 40-F の年次の添付（宿題 irr_tools_40f_gap の(1)）──────────────────────────────
#   選び方は 2026-09-23 の窓広げの走査（40-F 247件・添付 1,001文書）で使ったものと同じ:
#   本体＋ EX-99.x / EX-1 / EX-2 / EX-13 / EX-15 の .htm。同意書・証明書・行動規範・XBRL は落とし、
#   25KB 未満の添付（同意書・短い証明書）と 9MB 超は読まない。
#   ⚠ 10-K/20-F には当てない——10-K の EX-99 は何でも入りうる（プレスリリース・契約）。無関係な添付の語で
#     「在る」を偽造しないため（irr85_mech_diff.sibling_body の頭注と同じ理由）。
ANNUAL_EX = re.compile(r'^EX-(99|1|2|13|15)(\.|$|[A-Z])', re.I)
SKIP_EX_DESC = re.compile(r'consent|certif|clawback|code of (?:ethics|conduct)|printer friendly|graphic'
                          r'|xbrl|by-?law|articles', re.I)
_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
_CELL = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)


def filing_index(cik, accn):
    """提出物の索引（-index.htm）から [{seq, desc, type, fn, size, url}] を返す"""
    acc = accn.replace('-', '')
    h = get(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{accn}-index.htm').decode('utf-8', 'ignore')
    docs = []
    for row in _ROW.findall(h):
        cells = [html.unescape(re.sub(r'<[^>]+>', '', c)).replace('\xa0', ' ').strip() for c in _CELL.findall(row)]
        href = re.search(r'href="([^"]+)"', row)
        if len(cells) < 5 or not href:
            continue
        link = href.group(1).replace('/ix?doc=', '')
        docs.append({'seq': cells[0], 'desc': cells[1], 'type': cells[3].upper(),
                     'fn': link.rsplit('/', 1)[-1],
                     'size': int(re.sub(r'\D', '', cells[4]) or 0),
                     'url': ('https://www.sec.gov' + link) if link.startswith('/') else link})
    return docs


def annual_docs(cik, accn, form, primary_url):
    """年次報告の中身を持つ文書の一覧。40-F は本体＋年次の添付、それ以外は本体だけ。

    40-F で索引が取れなかったときは本体だけを返し `index_error` を付ける（黙って包み紙だけにしない）。
    primary_url が None なら索引の本体の行（種類＝form）から取る（EFTS のヒットが添付だったとき用）。"""
    prim = ({'type': form, 'desc': 'primary', 'fn': primary_url.rsplit('/', 1)[-1], 'url': primary_url}
            if primary_url else None)
    if form != '40-F':
        return [prim] if prim else []
    try:
        idx = filing_index(cik, accn)
    except SystemExit as e:
        return [dict(prim, index_error=str(e)[:160])] if prim else []
    if prim is None:
        body = next((d for d in idx if d['type'] == form), None)
        prim = ({k: body[k] for k in ('type', 'desc', 'fn', 'url', 'size')} if body
                else {'type': form, 'desc': 'primary（索引に無い）', 'fn': '', 'url': ''})
    out = [prim] if prim.get('url') else []
    for d in idx:
        t = d['type']
        if t == form or not ANNUAL_EX.match(t) or re.match(r'^EX-(10|101|1\d\d)', t):
            continue
        if not d['fn'].lower().endswith(('.htm', '.html', '.txt')):
            continue
        if SKIP_EX_DESC.search(d['desc']):
            continue
        if d['size'] and (d['size'] < 25000 or d['size'] > 9_000_000):
            continue
        if d['fn'] == prim.get('fn'):
            continue
        out.append({k: d[k] for k in ('type', 'desc', 'fn', 'url', 'size')})
    return out


def text_of(url):
    s = get(url).decode('utf-8', 'ignore')
    s = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t\xa0]+', ' ', s)
    return s


def sentences(txt):
    # XBRL のコンテキスト羅列（末尾の巨大な機械可読ブロック）を落とす
    txt = re.sub(r'\b\d{10}\s+(?:us-gaap|dei|srt|ifrs-full):\S+', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt)
    return re.split(r'(?<=[.;])\s+(?=[A-Z(])', txt)


def annual_text(f):
    """latest_annual の返り値から、年次の中身を持つ全文書の本文をつないで返す（40-F は添付も）"""
    docs = f.get('docs') or [{'url': f['url']}]
    return '\n'.join(text_of(d['url']) for d in docs)


def extract(url, maxn=40):
    """url は1本の URL か、URL の並び（40-F の本体＋添付）"""
    urls = [url] if isinstance(url, str) else list(url)
    ss = sentences(' . '.join(text_of(u) for u in urls))
    out, seen = [], set()
    for i, s in enumerate(ss):
        if len(s) < 60 or len(s) > 900:
            continue
        if not CORE.search(s):
            continue
        if re.search(r'contextRef|Member\b|iso4217|xbrli', s):
            continue
        key = s[:90].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(
            s=s.strip(),
            cust=bool(CUST.search(s)),
            self=bool(SELF.search(s)),
            wish=bool(WISH.search(s)),
            hits=sorted({m.group(0).lower() for m in CORE.finditer(s)}),
        ))
        if len(out) >= maxn:
            break
    return out


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith('--')]
    as_json = '--json' in sys.argv[1:]
    if not argv:
        raise SystemExit(__doc__)
    t = argv[0].upper()
    cik = argv[1].zfill(10) if len(argv) > 1 else cik_of(t)
    f = latest_annual(cik)
    if not f:
        raise SystemExit(f'{t}: 年次報告が見つからない')
    rows = extract([d['url'] for d in f['docs']])
    if as_json:
        print(json.dumps(dict(ticker=t, cik=cik, **f, n=len(rows), rows=rows),
                         ensure_ascii=False))
        return 0
    print(f"# {t}  {f['name']}  SIC {f['sic']} {f['sicDesc']}")
    print(f"# {f['form']} 期末 {f['report']} 提出 {f['filed']}")
    print(f"# {f['url']}")
    for d in f['docs'][1:]:
        print(f"#   + {d['type']} {d['fn']}  ({d.get('desc') or ''})")
    print(f"# 機構語を含む文 {len(rows)} 本（印: [顧客側の主語あり] [当社側の主語あり] [願望形]）\n")
    for r in rows:
        mark = ('C' if r['cust'] else '-') + ('S' if r['self'] else '-') + ('W' if r['wish'] else '-')
        print(f"[{mark}] {r['s']}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
