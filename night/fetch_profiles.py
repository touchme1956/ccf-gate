#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fetch_profiles.py — **銘柄ごとの企業説明を作る**（v9.9.125・2026-08-09新設）

発端（ユーザー要望「銘柄ごとに企業説明が見れるようにしたい」）:
  門はΩ・堀・E[r]という**評価**は全部出すのに、「**この会社は何をしている会社か**」を
  一言も出していなかった。台帳を開いて `VRSK` と書いてあっても事業が判らない。

【どこから採るか——原本と、台帳が既に持っている事実の二本立て】
  (a) **原本の事業説明**: パックの `_meta.source`（審査で実際に読んだ 10-K/20-F）から
      **Item 1 Business**（20-Fは Item 4 Information on the Company）の冒頭を抜く。
      *その社の審査に使ったのと同じ紙*なので、出典が一意に定まる（別の会社の説明が混ざらない）
  (b) **台帳が持つ日本語の事業の事実**: `_meta.evidence` の **moatW（セグメント構成・実額つき）**・
      **dom（競争上の位置）**・**dep（依存先）**。審査官が原本から測って日本語で書いたもの。
      **ブラウザは _meta を読めない**ので、この情報は台帳に取り込んだ瞬間に見えなくなっていた——
      つまりこの道具は新しい情報を作るのではなく、**既に払ったコストを見えるようにする**
  (c) **業種**: SEC submissions の `sicDescription`（CIKはソースURLから採る・鍵不要）

【なぜ外部の企業DBを使わないか】FMP等のプロフィールは読みやすいが (1)CIに鍵が無く自動化できない
  (2)第三者の要約なので**原本と食い違っても気づけない**。ロゴ(v9.9.103)と同じで、
  **CIで取り込んで門は同一オリジンで読む**——ただしロゴと違い、中身は原本そのものにする。

【取れないものは「未取得」と理由つきで出す（絶対のルール7）】日本株のEDINET/短信PDFは
  pypdf が要り、しかも短信には事業の内容が載らない。**穴として明示する**——
  ただし(b)は全社にあるので、日本株でも「何を売っているか」は出る。

**表示専用・判定には一切使わない。**

使い方: python3 night/fetch_profiles.py [--only T,...] [--limit N] [--force]
出力: out/profiles.json
"""
import glob
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}
OUT = 'out/profiles.json'
ONLY = (sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None)
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
FORCE = '--force' in sys.argv
MAXLEN = 1600          # 保存する抜粋の上限（門は先頭を出し、続きは展開で見せる）

# ⚠見出しは**ドロップキャップで1文字目が分離する**ことがある（実測 MSFT の本文見出しは
#   『ITEM 1. B USINESS』＝Bだけ別要素）。語中に1つまで空白を許す形にしないと本文を掴めず、
#   目次のほうだけ拾って「切り出せなかった」になる。
def _sp(w):
    return r'\s?'.join(w)


I1 = re.compile(r'(?i)item\s*1\s*[\.\:\-–—]?\s*' + _sp('business'))
I1A = re.compile(r'(?i)item\s*1a\s*[\.\:\-–—]?\s*' + _sp('risk') + r'\s*' + _sp('factors'))
I4 = re.compile(r'(?i)item\s*4\s*[\.\:\-–—]?\s*' + _sp('information') + r'\s+on\s+the\s+'
                + _sp('company'))
I4E = re.compile(r'(?i)item\s*(4a\s*[\.\:\-–—]?\s*unresolved|5\s*[\.\:\-–—]?\s*operating)')
# 抜粋が「会社の説明」らしいかの軽い検問（誤った節を掴んだときに黙って通さない）
LOOKS = re.compile(r'(?i)\b(we|our|the company|inc\.|plc|corporation|company is|group is)\b')
# 二の矢は見出し名だけで拾うので、**事業の話であること**も要求する。無いと ESG・気候の章を
#   掴んで「もっともらしい誤り」を作る（実測 ASML で気候戦略の節を掴んだ）
BIZ = re.compile(r'(?i)\b(products?|services?|customers?|clients?|revenue|segments?|markets?|'
                 r'manufactur\w*|solutions?|sells?|selling|business|operations|technolog\w*)\b')
NOTBIZ = re.compile(r'(?i)\b(climate change|greenhouse|sustainab\w*|net zero|decarbon\w*|'
                    r'diversity|audit committee|forward-looking statements)\b')
# ⚠**文の途中から始まる断片**を弾く。10-Kは『… see "Item 1. Business—Competition" of this Form 10-K
#   for a discussion of …』という**相互参照**を多用し、そこを掴むと「正しい会社の・意味のない文」が出る
#   ——未取得より悪い（もっともらしいので誤りに見えない）。実測 ADP/AFYA/AM/BUD/CPRX/GCT が該当した。
#   ⚠ (?i) を全体に掛けると `[a-z]` が大文字にも当たる（初版はこれで277社中271社を弾いた）。
#      大小の区別が要るのは「小文字で始まる＝文の途中」の判定なので、(?i) は第一の枝だけに掛ける
FRAG = re.compile(r'^((?i:.{0,70}?["”][^"”]{0,40}(for further information|for a discussion|'
                  r'for additional|of this (form|annual report)))|[a-z"”“]|[A-E]\.\s|—)')


def is_fragment(body):
    """**文の途中・目次から始まっていないか**を見る。FRAG（小文字始まり等）で拾えない型が2つ残った——
    (1)**閉じ引用符から始まる**: 『… Intellectual Property." D. Trend Information …』＝
       相互参照の途中。開き引用符が先に無いのに閉じが来たら、引用の中から始まっている
    (2)**目次**: 『60 A. History and Development 60 B. Business Overview 61 …』
    どちらも**正しい会社の・意味のない文**になるので、未取得より悪い（誤りに見えない）。"""
    head = body[:150]
    i = head.find('"')
    # 開き引用符は**後ろ**が非空白（例 ("AI")）、閉じ引用符は**前**が非空白で**後ろ**が空白。
    #   前だけを見ると ("AI") を閉じと誤判定して正しい抜粋を弾く（初版はこれで53社を弾いた）
    if i > 0 and not head[i - 1].isspace() and (i + 1 >= len(head) or head[i + 1].isspace()):
        return True                       # 開きの無い閉じ引用符＝引用の途中から始まっている
    h2 = body[:200]
    if len(re.findall(r'\b\d{1,3}\b', h2)) >= 3 and len(re.findall(r'\b[A-E]\.\s', h2)) >= 2:
        return True                       # 目次
    return False


def http(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def totext(h):
    h = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', h)
    h = re.sub(r'(?i)<br[^>]*>|</p>|</div>|</tr>|</h\d>', '\n', h)
    h = re.sub(r'(?s)<[^>]+>', ' ', h)
    for a, b in [('&nbsp;', ' '), ('&amp;', '&'), ('&#8217;', "'"), ('&#8220;', '"'),
                 ('&#8221;', '"'), ('&#8212;', '—'), ('&#151;', '—'), ('&rsquo;', "'"),
                 ('&ldquo;', '"'), ('&rdquo;', '"'), ('&#39;', "'"), ('&#8226;', '・')]:
        h = h.replace(a, b)
    h = re.sub(r'&[a-zA-Z#0-9]+;', ' ', h)
    h = re.sub(r'[ \t\xa0]+', ' ', h)
    return re.sub(r'\n\s*\n+', '\n', h)


def section(txt, form):
    """Item1(Business) / Item4(20-F) の本体を、**目次ではなく本文**として掴む。
    目次は見出しどうしが隣接するので、開始と終了の距離が最大の組を採る（TOCは自動的に落ちる）。"""
    A, B = (I4, I4E) if str(form or '').startswith('20-F') else (I1, I1A)
    starts = [m.end() for m in A.finditer(txt)]
    ends = [m.start() for m in B.finditer(txt)]
    best = None
    for e in ends:
        prev = [s for s in starts if s < e]
        if not prev:
            continue
        s = max(prev)
        if e - s > 2500 and (best is None or (e - s) > (best[1] - best[0])):
            best = (s, e)
    if not best:
        return None
    body = txt[best[0]:best[1]]
    body = re.sub(r'(?im)^\s*(general|general information|overview|business|our business|'
                  r'part i|table of contents|item 4\.?)\s*$', '', body)
    body = re.sub(r'(?i)\btable of contents\b', ' ', body)
    body = re.sub(r'\n+', ' ', body)
    body = re.sub(r'\s{2,}', ' ', body).strip(' .·—-')
    if (len(body) < 300 or not LOOKS.search(body[:400]) or FRAG.match(body)
            or is_fragment(body)):
        return None            # 誤った節・文の途中の断片＝黙って通さない（ルール7）
    return body[:MAXLEN]


# 二の矢: Item の見出しが機械で辿れない体裁のとき、Item1 冒頭に置かれる定番の小見出しから拾う
#   （実測 MSFT は『Item 1.』と『Business』が別セルで、目次の1件しかヒットしない）
H2 = re.compile(r'(?im)^\s*(our company|company overview|about us|about the company|'
                r'business overview|overview of (?:our )?business|introduction|'
                r'general development of business|who we are)\s*$')


def section2(txt):
    n = len(txt)
    for m in H2.finditer(txt):
        if not (n * 0.02 < m.start() < n * 0.55):
            continue          # 表紙・目次と、末尾の別章は除く
        body = txt[m.end():m.end() + 4200]
        body = re.sub(r'(?i)\bitem\s*1a\s*[\.\:]?\s*risk\s*factors[\s\S]*$', '', body)
        body = re.sub(r'(?i)\btable of contents\b', ' ', body)
        body = re.sub(r'\n+', ' ', body)
        body = re.sub(r'\s{2,}', ' ', body).strip(' .·—-')
        head = body[:600]
        if (len(body) >= 300 and LOOKS.search(head) and BIZ.search(head)
                and not NOTBIZ.search(head) and not FRAG.match(body)
                and not is_fragment(body)):
            return body[:MAXLEN]
    return None


def latest_filing(t2c, t):
    """パックの source がURLでない社（実測 LRCX は accession だけの文章）向けに、
    SEC submissions から**最新の10-K/20-F**の主要文書URLを組む。使ったことは記録に残す。"""
    cik = t2c.get(str(t).upper())
    if not cik:
        return None, None
    j = http(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
    if not j:
        return None, None
    try:
        d = json.loads(j)
        r = d['filings']['recent']
        for i, f in enumerate(r['form']):
            if f in ('10-K', '20-F'):
                acc = r['accessionNumber'][i].replace('-', '')
                return (f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/'
                        f'{r["primaryDocument"][i]}', f)
    except Exception:
        pass
    return None, None


def sic(cik):
    j = http(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json')
    if not j:
        return None, None
    try:
        d = json.loads(j)
        return (d.get('sicDescription') or None), (d.get('name') or None)
    except Exception:
        return None, None


def clean_ev(s):
    """審査の evidence から**事業の事実**だけを残す。先頭の【…】は監査の見出しなので落とす。"""
    if not isinstance(s, str):
        return None
    s = re.sub(r'^\s*(（[^）]*）\s*)?【[^】]*】\s*', '', s).strip()
    s = re.sub(r'^\s*（旧[^）]*）\s*', '', s).strip()
    return s[:900] or None


def main():
    # ⚠**既存の在庫は常に読む**。初版は --force で old={} にしていたため
    #   `--force --only A,B` を打つと**残り346社が消えた**（正本を部分実行で潰す型＝
    #   CLAUDE.md が score_all の --jp/--us で記録した事故と同じ）。
    #   --force が意味するのは「その社の biz を作り直す」であって「在庫を捨てる」ではない。
    old = {}
    if os.path.exists(OUT):
        try:
            old = (json.load(open(OUT, encoding='utf-8')).get('items') or {})
        except Exception:
            old = {}
    items = dict(old)
    packs = []
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        if ONLY and t not in ONLY:
            continue
        packs.append((t, p))
    if LIMIT:
        packs = packs[:LIMIT]
    # ティッカー→CIK（パックの source がURLでない社の救済に使う）
    t2c = {}
    tk = http('https://www.sec.gov/files/company_tickers.json')
    if tk:
        try:
            for r in json.loads(tk).values():
                t2c.setdefault(str(r['ticker']).upper(), int(r['cik_str']))
        except Exception:
            pass
    n_new = n_sec = 0
    for i, (t, p) in enumerate(packs, 1):
        x = json.load(open(p, encoding='utf-8'))
        d = x.get('data') or x
        m = d.get('_meta') or {}
        src = m.get('source')
        if isinstance(src, list):
            src = src[0] if src else None
        form = m.get('form')
        ev = m.get('evidence') or {}
        rec = dict(nm=d.get('nm') or t, form=form, rdate=m.get('reportDate'), src=src,
                   seg=clean_ev(ev.get('moatW')), pos=clean_ev(ev.get('dom')),
                   dep=clean_ev(ev.get('dep')), nulls={})
        prev = old.get(t) or {}
        url = src if (isinstance(src, str) and 'sec.gov' in src) else None
        jp = not isinstance(src, str) or ('edinet' in str(src).lower() or 'yahoo' in str(src).lower())
        if url is None and not jp:
            # 実測 LRCX: source が「SEC EDGAR 10-K FY2026（… accession …）」という**文章**でURLでない。
            #   ティッカーから最新の10-K/20-Fを引いて救済し、**救済したことを記録に残す**（黙って代用しない）
            url, ff = latest_filing(t2c, t)
            time.sleep(0.12)
            if url:
                form = form or ff
                rec['src_used'] = url
                rec['nulls']['src'] = ('パックの source がURLでなかったので、SEC submissions から'
                                       'その社の最新の年次報告を引いて代用した（審査で読んだ紙と同一とは限らない）')
        if url:
            if prev.get('biz') and not FORCE and prev.get('src') == src:
                rec['biz'], rec['sic'], rec['legal'] = prev.get('biz'), prev.get('sic'), prev.get('legal')
            else:
                cikm = re.search(r'/data/(\d+)/', url)
                if cikm:
                    rec['sic'], rec['legal'] = sic(cikm.group(1))
                    time.sleep(0.12)
                h = http(url)
                time.sleep(0.12)
                if h:
                    tx = totext(h.decode('utf-8', 'ignore'))
                    b = section(tx, form) or section2(tx)
                    if b:
                        rec['biz'] = b
                        n_sec += 1
                    else:
                        rec['nulls']['biz'] = ('原本から Item1(Business) の本文を切り出せなかった'
                                               '（節の見出しが機械で辿れない体裁）。出典リンクから直接読める')
                else:
                    rec['nulls']['biz'] = '原本の取得に失敗（SECの一時的な応答不良の可能性）'
        else:
            rec['nulls']['biz'] = ('原本がEDINET/短信のPDFで、テキスト抽出に pypdf が要る＝**穴として明示**。'
                                   '短信には事業の内容が載らないため、有報PDF経路の実装が別途要る')
            rec['nulls']['sic'] = 'SEC submissions は米国提出体のみ（日本株は対象外）'
        items[t] = rec
        n_new += 1
        if i % 40 == 0:
            print(f'  … {i}/{len(packs)}  原本の説明 {n_sec}件', file=sys.stderr)
    have = sum(1 for v in items.values() if v.get('biz'))
    seg = sum(1 for v in items.values() if v.get('seg'))
    json.dump({'generated': time.strftime('%Y-%m-%d'), 'n': len(items),
               'note': '表示専用・判定には一切使わない。biz=原本(10-K/20-F)のItem1冒頭／'
                       'seg・pos・dep=台帳の_meta.evidence（審査官が原本から日本語で書いた事業の事実）。'
                       'ブラウザは_metaを読めないので、この道具が無いとこの情報は台帳では見えない',
               'items': items}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'■ out/profiles.json  {len(items)}社')
    print(f'   原本の事業説明     {have}社（{have/max(1,len(items)):.0%}）')
    print(f'   セグメント構成     {seg}社（台帳のmoatW根拠・日本株を含む）')
    print(f'   未取得の理由つき   {sum(1 for v in items.values() if v.get("nulls"))}社')
    return 0


if __name__ == '__main__':
    sys.exit(main())
