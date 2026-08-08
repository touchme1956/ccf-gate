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


def latest_annual(cik):
    j = json.loads(get(f'https://data.sec.gov/submissions/CIK{cik}.json'))
    rec = j['filings']['recent']
    for i, f in enumerate(rec['form']):
        if f in ('10-K', '20-F', '40-F'):
            acc = rec['accessionNumber'][i].replace('-', '')
            doc = rec['primaryDocument'][i]
            return dict(form=f, filed=rec['filingDate'][i], report=rec['reportDate'][i],
                        url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}',
                        name=j.get('name'), sic=str(j.get('sic') or ''),
                        sicDesc=j.get('sicDescription'))
    return None


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


def extract(url, maxn=40):
    ss = sentences(text_of(url))
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
    rows = extract(f['url'])
    if as_json:
        print(json.dumps(dict(ticker=t, cik=cik, **f, n=len(rows), rows=rows),
                         ensure_ascii=False))
        return 0
    print(f"# {t}  {f['name']}  SIC {f['sic']} {f['sicDesc']}")
    print(f"# {f['form']} 期末 {f['report']} 提出 {f['filed']}")
    print(f"# {f['url']}")
    print(f"# 機構語を含む文 {len(rows)} 本（印: [顧客側の主語あり] [当社側の主語あり] [願望形]）\n")
    for r in rows:
        mark = ('C' if r['cust'] else '-') + ('S' if r['self'] else '-') + ('W' if r['wish'] else '-')
        print(f"[{mark}] {r['s']}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
