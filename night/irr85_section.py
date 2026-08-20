#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_section.py — **機構文が「どこに置かれているか」を機械で出す**（2026-08-19新設）

■ なぜ要るか（第一次の狩りが22社とも落ちた原因が、ここ一点だった）
  2026-08-08 の狩りは403社を読んで85を22社提案し、**反証で22社とも潰れた**。
  22件の反証理由を読むと、誤りの型は文の中身ではなく**文の置き場所**だった:
    ・ACMR「we may experience difficulty in selling to a given manufacturer if that manufacturer
      has qualified a competitor's equipment」= 同じ一文が、据わっている側には堀の証明、
      **外側にいる側には自分が入れない証明**になる。どちら側かは**見出し**が教える
    ・SPR/TGI「機構語の段落が Risk Factors の "If ..." 見出しの下にある」＝当社が負う側
    ・複数社「Competitive Strengths の自社宣伝の箇条書き」＝断定ではなく主張
  そして台帳自身が 2026-08-11 に **CW の射程 12.29%** を見つけたのも同じ話——
  決定的な一文は**全文で1回だけ・Item 1A の「航空」のリスク要因の中**にあり、全社の記述ではなかった。

  ⇒ **文だけを配ると読み手は必ず間違える。** 置き場所（Item・直前の見出し・出現回数）を一緒に配る。
  これは v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」を読解の側で守る作法でもある
  ——全員に**同じ材料**を配る。

■ 何を出すか（判定は一切しない。判定は原本を読む審査官の仕事＝絶対のルール2）
  ヒットした文ごとに:
    ・その文（前後1文つき）
    ・**enclosing item**（Item 1 Business / Item 1A Risk Factors / Item 7 MD&A / …）
    ・**nearest heading**（直前の見出し行。Risk Factors では "If our customers do not …" 等がそのまま出る）
    ・向きの印（顧客が主語 / 当社が主語 / 願望形）——`night/irr85_extract.py` の正規表現を**import して共有**する
    ・全文での出現回数（1回しか出ない語は射程が狭い疑い＝CW型）

■ 使い方
  python3 night/irr85_section.py CW                       ティッカーで最新の年次報告
  python3 night/irr85_section.py --cik 0000026324
  python3 night/irr85_section.py --doc 0000026324-26-000012:cw-20251231.htm --cik 0000026324
  python3 night/irr85_section.py CW --json
  オプション: --vocab night/irr85_vocab2.json（既定）／--max 60
"""
import argparse
import html
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ★向きの正規表現と取得・解決は irr85_extract.py の**単一実装**を借りる（書き写さない）
_spec = importlib.util.spec_from_file_location('_ix', os.path.join(HERE, 'irr85_extract.py'))
_ix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ix)
CUST, SELF, WISH = _ix.CUST, _ix.SELF, _ix.WISH

# Item の見出し。⚠ドロップキャップで語が割れる（実測: MSFT の 10-K は『ITEM 1. B USINESS』）
ITEM = re.compile(
    r'^\s*item\s*(1a|1b|1c|1|2|3|5|6|7a|7|8|9a|9|10|11|12|13|14|15)\s*[.:\-–—]?\s*'
    r'([a-z][a-z \-\'’&/,()]{2,90})?\s*[.]?\s*$', re.I)
ITEM_NAME = {'1': 'Business', '1a': 'Risk Factors', '1b': 'Unresolved Staff Comments',
             '1c': 'Cybersecurity', '2': 'Properties', '3': 'Legal Proceedings',
             '5': 'Market for Common Equity', '6': 'Selected Financial Data',
             '7': "MD&A", '7a': 'Market Risk', '8': 'Financial Statements'}
BLOCK = re.compile(r'(?is)</?(p|div|tr|br|li|h[1-6]|table|td|section)[^>]*>')


def fetch_text(url):
    raw = _ix.get(url).decode('utf-8', 'ignore')
    raw = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', raw)
    raw = BLOCK.sub('\n', raw)          # ★行の構造を先に残す——見出しは自分の行に居る
    raw = re.sub(r'<[^>]+>', ' ', raw)
    raw = html.unescape(raw)
    raw = re.sub(r'[ \t\xa0]+', ' ', raw)
    raw = re.sub(r'\n\s*\n+', '\n', raw)
    # XBRL の機械可読ブロックを落とす
    raw = re.sub(r'\b\d{10}\s+(?:us-gaap|dei|srt|ifrs-full):\S+', ' ', raw)
    return [ln.strip() for ln in raw.split('\n')]


def dropcap_fix(s):
    """『B USINESS』のように語頭1字が別要素で割れる版を1語へ戻す"""
    return re.sub(r'\b([A-Z]) ([A-Z]{3,})\b', r'\1\2', s)


def is_heading(ln):
    """構造上の見出し行か。判定は緩く——材料として出すだけで、合否には使わない"""
    if not (8 <= len(ln) <= 220):
        return False
    if ln.endswith((',', ';', ':')):
        return False
    if ln[0] in '•·-–—*◦':          # 箇条書きは見出しではない（実測CWで拾っていた）
        return False
    if re.match(r'(?i)^table of c\s?ontents$', ln):   # ドロップキャップで割れた頁ヘッダ（実測ACMR）
        return False
    words = ln.split()
    if len(words) < 2 or len(words) > 30:
        return False
    if ln.endswith('.') and len(words) > 14:      # 普通の文
        return False
    return True


def scan(lines, phrases, maxn=60):
    # Item の境目を先に取る
    raw = []
    for i, ln in enumerate(lines):
        m = ITEM.match(dropcap_fix(ln))
        if m:
            num = m.group(1).lower()
            nm = (m.group(2) or ITEM_NAME.get(num, '')).strip().rstrip('.')
            raw.append((i, num, f'Item {num.upper()} {nm}'.strip()))

    # ★目次を落とす——目次は「短い行間に多数の Item が並ぶ」ので密度で判る（実測 CW: 行76〜142に19本）。
    #   落とさないと**本文の全部が最後の目次行(Item 15)の中**に見える（この検算で実際にそうなった）
    body = [r for r in raw if sum(1 for q in raw if abs(q[0] - r[0]) <= 40) < 5]
    toc_dropped = len(raw) - len(body)
    if not body:                      # 目次しか無い＝落とすと何も残らないなら全部使う（黙って空にしない）
        body, toc_dropped = raw, 0

    def item_at(i):
        cur = None
        for j, _n, nm in body:
            if j <= i:
                cur = nm
            else:
                break
        # 最初の本文見出しより前は Item 1 Business とみなす（10-K は Business が先頭。推定と明示する）
        if cur is None and body:
            return 'Item 1 Business（推定・本文の見出しが取れず）'
        return cur

    full = '\n'.join(lines).lower()
    counts = {p: full.count(p.lower()) for p in phrases}

    out = []
    for i, ln in enumerate(lines):
        low = ln.lower()
        hit = [p for p in phrases if p.lower() in low]
        if not hit:
            continue
        if len(ln) < 40 or len(ln) > 2400:
            continue
        if re.search(r'contextRef|iso4217|xbrli|Member\b', ln):
            continue
        # ★直前の見出しは**3つまで遡って全部出す**——1つだけ出すと外したときに読み手を誤らせる。
        #   実測(CW): FAAの段落に対し最近傍は「Our nuclear business …」で、正しい航空の見出しは
        #   もう一段上にあった。判定しないのだから、材料は多いほうが安全
        heads = []
        for k in range(i - 1, max(-1, i - 80), -1):
            if is_heading(lines[k]) and not ITEM.match(dropcap_fix(lines[k])):
                heads.append(lines[k])
                if len(heads) >= 3:
                    break
        head = heads[0] if heads else None
        out.append({
            'phrases': hit,
            'n_in_doc': {p: counts[p] for p in hit},
            'item': item_at(i),
            'heading': head,
            'heading_chain': heads,
            'text': ln[:1400],
            'before': (lines[i - 1][:300] if i else None),
            'after': (lines[i + 1][:300] if i + 1 < len(lines) else None),
            'cust': bool(CUST.search(ln)), 'self': bool(SELF.search(ln)), 'wish': bool(WISH.search(ln)),
        })
        if len(out) >= maxn:
            break
    return out, counts, [m[2] for m in body], toc_dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ticker', nargs='?')
    ap.add_argument('--cik')
    ap.add_argument('--doc', help='EDGAR全文検索の _id（adsh:filename）')
    ap.add_argument('--vocab', default=os.path.join(HERE, 'irr85_vocab2.json'))
    ap.add_argument('--max', type=int, default=60)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    v = json.load(open(a.vocab, encoding='utf-8'))
    phrases = sorted({p['p'].strip().lower() for p in v['phrases'] if p.get('p')})
    dirs = {p['p'].strip().lower(): p.get('dir', 'neutral') for p in v['phrases']}
    anti = sorted({x['p'].strip().lower() for x in (v.get('anti') or []) if x.get('p')})

    cik = (a.cik or '').zfill(10) if a.cik else (_ix.cik_of(a.ticker) if a.ticker else None)
    if not cik:
        raise SystemExit('ティッカーか --cik が要る')
    if a.doc:
        adsh, fn = a.doc.split(':', 1)
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{fn}"
        meta = {'url': url, 'form': None, 'filed': None, 'name': None, 'sic': None}
    else:
        f = _ix.latest_annual(cik)
        if not f:
            raise SystemExit(f'{a.ticker or cik}: 年次報告が無い')
        meta, url = f, f['url']

    lines = fetch_text(url)
    rows, counts, items, toc_dropped = scan(lines, phrases + anti, a.max)
    for r in rows:
        r['dir'] = sorted({dirs.get(p, 'ANTI' if p in anti else 'neutral') for p in r['phrases']})

    res = {'ticker': a.ticker, 'cik': cik, 'url': url, 'n_lines': len(lines),
           'items_found': items[:40], 'toc_marks_dropped': toc_dropped, 'n_hits': len(rows),
           'hit_phrases': {p: c for p, c in counts.items() if c},
           'rows': rows, **{k: v2 for k, v2 in meta.items() if k != 'url'}}
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    print(f"# {a.ticker or ''} {meta.get('name') or ''} CIK {cik}  SIC {meta.get('sic') or ''}")
    print(f"# {url}")
    print(f"# 行 {len(lines)} / Item境界 {len(items)} / ヒット文 {len(rows)}")
    print(f"# 当たった語: " + ', '.join(f'{p}×{c}' for p, c in sorted(res['hit_phrases'].items(), key=lambda kv: -kv[1])[:20]))
    print()
    for r in rows:
        mark = ('C' if r['cust'] else '-') + ('S' if r['self'] else '-') + ('W' if r['wish'] else '-')
        n1 = ' '.join(f"{p}×{c}" for p, c in r['n_in_doc'].items())
        print(f"[{mark}] 〔{r['item'] or '?'}〕 {'/'.join(r['dir'])}  ({n1})")
        for h in (r.get('heading_chain') or []):
            print(f"    ↑見出し: 「{h}」")
        print(f"    {r['text'][:700]}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
