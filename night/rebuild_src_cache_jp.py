#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rebuild_src_cache_jp.py — **日本株の原本キャッシュ out/_src_cache/{T}.txt を、パックに刻んだ docID から作り直す**（2026-09-23新設）

発端（todo `src_cache_ephemeral`）:
  逐語照合（`irr70_apply.py` の検問・`irr85_mech_diff.py` の機構文の照合・`irr85_screen_local.py`）は
  どれも `out/_src_cache/{T}.txt` を読む。ところがこのディレクトリは **.gitignore**（サイズが理由・正しい判断）
  ＝**容器が回収されるとキャッシュは消え、パックに刻んだ引用を誰も再検証できなくなる**。
  米国株は SEC から取り直せるが、**日本株には自動の取り直しが無かった**（EDINET API v2 は鍵が要る）。
  2026-09-23、**EDINET の有報PDFは鍵なしで docID から直接落とせる**と判った:
    https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf
  docID は審査のたびに `_meta.source`・evidence・kenshi に刻まれているので、**キャッシュは再構築できる**。

何をするか（判定はしない。材料を戻すだけ）:
  1. 日本株パック（nm が4〜5桁のコードで始まる）から docID（S100xxxx）を集める——
     `_meta.source` ／ `source_note` ／ `_meta.evidence`・`_meta.kenshi` の中の言及。
     evidence の《原本の出所》に書かれた docID（＝引用を照合した原本）を先に試す。
  2. docID の新しい順（docID の並び＝提出の順）に PDF を落とし、**表紙で確かめる**:
     【提出書類】が「有価証券報告書」そのもの（訂正・四半期・半期・臨時は採らない）／
     【事業年度】の末日がパックの会計年度（`_meta.reportDate` の年月）と一致／
     会社が同じ（パック名の一致、またはパックに唯一ある EDINET コード＝E+5桁 の一致）。
     一致する有報が無ければ、見つかった中で最新の有報を採り「会計年度不一致」と名指しする。
  3. pypdf でテキスト化し、**各ページの EDINET の帯（「EDINET提出書類／会社名(Eコード)／有価証券報告書／n/N」）を落として**
     `out/_src_cache/{T}.txt` へ。出所（docID・事業年度・ページの開始位置）は `out/_src_cache/{T}.src.json` へ。

踏まないようにした落とし穴:
  ・**キャッシュをコミットしない**——`out/_src_cache/` は .gitignore（369社ぶんで数百MB）。PDF はディスクに残さない
  ・**決算短信を有報と取り違えない**（2026-08-20 の実害: 3922/3939 のキャッシュが決算短信で、
    【事業等のリスク】が無く機構語が全項目0件になった）——表紙の【提出書類】で裁く。
    既存のキャッシュにこの道具の出所記録が無ければ「出所不明」と名指しし、【事業等のリスク】が無ければ短信の疑いを出す
  ・**取れなかったことを空で埋めない**（ルール7）——失敗は理由つきで一覧に出し、空のファイルを置かない
  ・**帯を落とすのは引用の照合のため**——ページをまたぐ引用が帯で割れて「消えた」に化けるのを防ぐ（表記の正規化であって内容の改変ではない）
  ・**表紙の事業年度の書き方は一つではない**——『至 2026年3月31日』のほか和暦『至 令和8年3月31日』（実測 3692）や
    『2026年3月期(第149期)』（実測 4063）がある。西暦の書式だけを読むと末日が取れず、会計年度の照合が「不一致」に化けて
    パックの docID を全部落とし、別の年度の有報を掴みかねない（初版で踏んだ）
  ・pypdf は `cryptography` の Rust 束縛が壊れた容器で import 時に panic する（BaseException なので pypdf 自身の
    except を突き抜ける）→ **`cryptography` を import 不能にしてから** pypdf を読む（暗号化されていない有報PDFには不要）
  ・礼儀: ダウンロードの間は **1秒以上**空ける。User-Agent にメールアドレスを載せない（SEC 向けの UA は使わない）

使い方:
  python3 night/rebuild_src_cache_jp.py                 # 日本株パック全部（既にあるキャッシュは飛ばす）
  python3 night/rebuild_src_cache_jp.py --only 3923,6146
  python3 night/rebuild_src_cache_jp.py --force         # 既にあっても作り直す
  python3 night/rebuild_src_cache_jp.py --dry           # 落とさずに、候補の docID だけ並べる
出力: out/_src_cache/{T}.txt ＋ {T}.src.json ＋ _rebuild_summary.json（いずれも .gitignore）
他の道具からは fetch_pdf / pdf_pages / cover_info / doc_ids を import して使える（二重実装を作らない）。
"""
import datetime
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'out', '_src_cache')
PDF_URL = 'https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{}.pdf'
VIEW_URL = 'https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{}'
UA = {'User-Agent': 'ccf-gate/1.0 (EDINET yuho PDF cache rebuild)'}
MIN_GAP = 1.2            # 秒。ダウンロードの間隔（1秒以上の礼儀）
TODAY = datetime.date.today().isoformat()
DOCID = re.compile(r'\bS100[0-9A-Z]{4}\b')
FOOTER = re.compile(r'\s*EDINET提出書類\s*\n([^\n]*?)\((E\d{5})\)\s*\n[^\n]*\n\s*(\d+)\s*/\s*(\d+)\s*$')

_last = [0.0]


def _pypdf():
    """容器の cryptography が壊れていても pypdf を読めるようにする（docstring の落とし穴を参照）。"""
    if 'pypdf' not in sys.modules:
        try:
            import _cffi_backend  # noqa: F401  ← これが無いと cryptography の Rust 束縛が panic する（実測）
            import cryptography.exceptions  # noqa: F401  ← 正常な環境ならそのまま使う
        except BaseException:               # pyo3 の PanicException は Exception ではない
            for k in [k for k in sys.modules if k == 'cryptography' or k.startswith('cryptography.')]:
                del sys.modules[k]
            sys.modules['cryptography'] = None
    import pypdf
    return pypdf


def fetch_pdf(doc_id, tries=3):
    """docID の PDF を bytes で返す。取れなければ (None, 理由)。**1秒以上の間隔**を守る。"""
    url = PDF_URL.format(doc_id)
    why = ''
    for i in range(tries):
        gap = time.monotonic() - _last[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last[0] = time.monotonic()
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)
            b = r.read()
            if b[:5] == b'%PDF-':
                return b, ''
            why = f'PDFではない応答（{r.headers.get("Content-Type")}・{len(b)}バイト）'
        except urllib.error.HTTPError as e:
            why = f'HTTP {e.code}'
            if e.code == 404:
                break
        except Exception as e:  # 一時的な失敗は間を置いて取り直す
            why = f'{type(e).__name__}: {e}'
        time.sleep(2 * (i + 1))
    return None, why


def pdf_pages(b, first_only=False):
    """PDF の bytes → ページごとのテキスト（帯つきの生テキスト）。"""
    r = _pypdf().PdfReader(io.BytesIO(b))
    pages = r.pages[:1] if first_only else r.pages
    return [(p.extract_text() or '') for p in pages], len(r.pages)


def strip_footer(t):
    """各ページ末尾の EDINET の帯を落とす。返り値 (本文, 帯から読んだ (会社名, Eコード) or None)。"""
    m = FOOTER.search(t)
    if not m:
        return t, None
    return t[:m.start()], (m.group(1).strip(), m.group(2))


def _nfkc(s):
    return unicodedata.normalize('NFKC', s or '')


def cover_info(page1):
    """表紙から 書類名・事業年度の末日・会社名・Eコード を読む。"""
    s = _nfkc(page1)
    g = lambda k: (re.search(r'【' + k + r'】\s*([^\n]*)', s) or [None, ''])[1].strip()
    kind = g('提出書類') or g('書類名')
    fy = g('事業年度')
    # ⚠ 和暦で書く社がある（実測 3692: 『至 令和8年3月31日』）——西暦だけを読むと末日が取れず、
    #   会計年度の照合が「不一致」に化けて別の年度の有報を掴む
    m = re.search(r'至\s*(令和|平成)?\s*(\d{1,4}|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', fy)
    fy_end = None
    if m:
        y = 1 if m.group(2) == '元' else int(m.group(2))
        y += {'令和': 2018, '平成': 1988}.get(m.group(1), 0)
        fy_end = f'{y:04d}-{int(m.group(3)):02d}-{int(m.group(4)):02d}'
    else:
        # 『2026年3月期(第149期)』と期だけを書く社もある（実測 4063）——末日は月末とみなす（照合は年月だけ）
        m = re.search(r'(令和|平成)?\s*(\d{1,4}|元)\s*年\s*(\d{1,2})\s*月\s*期', fy)
        if m:
            import calendar
            y = 1 if m.group(2) == '元' else int(m.group(2))
            y += {'令和': 2018, '平成': 1988}.get(m.group(1), 0)
            mo = int(m.group(3))
            fy_end = f'{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}'
    _, foot = strip_footer(page1)
    return {'kind': kind, 'fy': fy, 'fy_end': fy_end, 'company': g('会社名'),
            'ecode': foot[1] if foot else None}


def _name_key(s):
    s = _nfkc(s).lower()
    s = re.sub(r'株式会社|\(株\)|[\s・･,.]', '', s)
    return s


def is_jp(pack):
    return bool(re.match(r'^\d{4,5}(?:\s|$)', str(pack.get('nm') or '')))


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for w in v.values():
            yield from _strings(w)
    elif isinstance(v, list):
        for w in v:
            yield from _strings(w)


def doc_ids(pack):
    """パックに刻まれた docID を (優先, その他) に分けて返す。どちらも新しい順。
       優先 = evidence の《原本の出所》・source_note に書かれた docID（＝引用を照合した原本）。"""
    m = pack.get('_meta') or {}
    prio, allids = set(), set()
    for s in _strings([pack.get('source_note'), m.get('source_note')]):
        prio.update(DOCID.findall(s))
    for s in _strings(m.get('evidence') or {}):
        for seg in re.findall(r'《原本の出所》([^《]*)', s):
            prio.update(DOCID.findall(seg))
    for s in _strings([m.get('source'), pack.get('source_note'), m.get('source_note'),
                       m.get('evidence'), m.get('kenshi')]):
        allids.update(DOCID.findall(s))
    allids |= prio
    desc = lambda xs: sorted(xs, reverse=True)       # 英数の並び＝36進の並び＝提出の順
    return desc(prio), desc(allids - prio)


def same_company(pack, cov):
    """表紙の会社がパックの会社か。名前の一致、またはパックにEコードが1つだけあってそれと一致。"""
    nm = re.sub(r'^\d{4,5}\s*', '', str(pack.get('nm') or ''))
    a, b = _name_key(nm), _name_key(cov.get('company'))
    if a and b and (a in b or b in a):
        return True
    ecodes = set()
    for s in _strings(pack):
        ecodes.update(re.findall(r'\bE\d{5}\b', s))
    return len(ecodes) == 1 and cov.get('ecode') in ecodes


def report_ym(pack):
    m = pack.get('_meta') or {}
    rd = str(m.get('reportDate') or pack.get('reportDate') or '')
    return rd[:7] if re.match(r'^\d{4}-\d{2}', rd) else None


def is_yuho(kind):
    k = _nfkc(kind).replace(' ', '')
    return k == '有価証券報告書'


def build_one(t, pack, force=False, dry=False):
    """1社ぶん。返り値は一覧の1行（dict）。"""
    path = os.path.join(CACHE, f'{t}.txt')
    side = os.path.join(CACHE, f'{t}.src.json')
    prio, rest = doc_ids(pack)
    row = {'t': t, 'nm': pack.get('nm'), 'reportDate': report_ym(pack), 'ids': prio + rest}
    if os.path.exists(path) and os.path.getsize(path) > 5000 and not force:
        row['status'] = 'kept'
        if not os.path.exists(side):
            txt = open(path, encoding='utf-8', errors='ignore').read()
            row['note'] = '出所不明（この道具の出所記録が無い）' + (
                '・【事業等のリスク】が無い＝決算短信の疑い（--force で作り直せる）' if '事業等のリスク' not in txt else '')
        return row
    if not prio and not rest:
        row.update(status='miss', why='パックに docID（S100xxxx）が1つも無い＝EDINET経路の穴（source が短信・irbank・IR資料だけ）')
        return row
    if dry:
        row['status'] = 'dry'
        return row
    ym = report_ym(pack)
    tried, fallback = [], None
    for did in prio + rest:
        b, why = fetch_pdf(did)
        if b is None:
            tried.append(f'{did}: 取得失敗 {why}')
            continue
        try:
            first, npg = pdf_pages(b, first_only=True)
            cov = cover_info(first[0] if first else '')
        except BaseException as e:
            tried.append(f'{did}: PDFを読めない {type(e).__name__}')
            continue
        tag = f"{did}: {cov['kind'] or '?'} 至{cov['fy_end'] or '?'} {cov['company'] or '?'}"
        if not is_yuho(cov['kind']):
            tried.append(tag + '（有報ではない）')
            continue
        if not same_company(pack, cov):
            tried.append(tag + '（別の会社）')
            continue
        if ym and cov['fy_end'] and cov['fy_end'][:7] == ym:
            fallback = None
            chosen = (did, b, cov, npg)
            break
        tried.append(tag + f'（会計年度がパック {ym} と不一致）')
        if fallback is None or (cov['fy_end'] or '') > (fallback[2]['fy_end'] or ''):
            fallback = (did, b, cov, npg)
    else:
        chosen = fallback
    if not chosen:
        row.update(status='miss', why='パックの docID に、この社の有価証券報告書が見つからない', tried=tried)
        return row
    did, b, cov, npg = chosen
    try:
        raw, _ = pdf_pages(b)
    except BaseException as e:
        row.update(status='miss', why=f'本文の抽出に失敗 {type(e).__name__}: {e}', tried=tried)
        return row
    body, offs, pos = [], [], 0
    for pg in raw:
        s, _ = strip_footer(pg)
        offs.append(pos)
        body.append(s)
        pos += len(s) + 1
    txt = '\n'.join(body)
    if len(txt) < 5000:
        row.update(status='miss', why=f'本文が短すぎる（{len(txt)}字・画像PDFの疑い）', tried=tried)
        return row
    os.makedirs(CACHE, exist_ok=True)
    tmp = path + '.tmp'
    open(tmp, 'w', encoding='utf-8').write(txt)
    os.replace(tmp, path)
    meta = {'t': t, 'docID': did, 'url': PDF_URL.format(did), 'view': VIEW_URL.format(did),
            'kind': cov['kind'], 'fy': cov['fy'], 'fy_end': cov['fy_end'], 'company': cov['company'],
            'ecode': cov['ecode'], 'pages': npg, 'chars': len(txt), 'page_offsets': offs,
            'fy_match': bool(ym and cov['fy_end'] and cov['fy_end'][:7] == ym),
            'built': TODAY, 'tool': 'night/rebuild_src_cache_jp.py', 'tried': tried}
    json.dump(meta, open(side, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    row.update(status='built', docID=did, fy_end=cov['fy_end'], pages=npg, chars=len(txt),
               fy_match=meta['fy_match'], tried=tried)
    if not meta['fy_match']:
        row['note'] = f"会計年度不一致: パック {ym} ／ 採った有報 {cov['fy_end']}（パックの docID に同年度の有報が無い）"
    return row


def main():
    a = sys.argv[1:]
    only = set(a[a.index('--only') + 1].split(',')) if '--only' in a else None
    force, dry = '--force' in a, '--dry' in a
    import glob
    rows = []
    packs = sorted(glob.glob(os.path.join(ROOT, 'out', '*_gate_pack.json')))
    for p in packs:
        t = os.path.basename(p).split('_gate_pack')[0]
        if only and t not in only:
            continue
        pack = json.load(open(p, encoding='utf-8'))
        if not is_jp(pack):
            continue
        r = build_one(t, pack, force=force, dry=dry)
        rows.append(r)
        extra = r.get('docID') or r.get('why') or r.get('note') or ''
        print(f"  {t:6s} {r['status']:5s} {extra}", file=sys.stderr, flush=True)
    cnt = {}
    for r in rows:
        cnt[r['status']] = cnt.get(r['status'], 0) + 1
    print(f'■ 日本株の原本キャッシュ（out/_src_cache/・.gitignore）: 対象 {len(rows)}社 → ' +
          ' / '.join(f'{k} {v}' for k, v in sorted(cnt.items())))
    for r in rows:
        if r['status'] == 'built':
            print(f"  ✓ {r['t']:6s} {r['docID']} 至{r['fy_end']} {r['pages']}頁 {r['chars']:,}字"
                  + (f"  ⚠{r['note']}" if r.get('note') else ''))
    for r in rows:
        if r['status'] == 'kept' and r.get('note'):
            print(f"  … {r['t']:6s} 既存を保持: {r['note']}")
    for r in rows:
        if r['status'] == 'miss':
            print(f"  ✗ {r['t']:6s} {r['why']}")
            for s in (r.get('tried') or [])[:8]:
                print(f'        {s}')
    if dry:
        for r in rows:
            if r['status'] == 'dry':
                print(f"  ? {r['t']:6s} {' '.join(r['ids'])}")
        return 0
    if rows:
        os.makedirs(CACHE, exist_ok=True)
        json.dump({'generated': TODAY, 'only': sorted(only) if only else None, 'force': force,
                   'counts': cnt, 'rows': rows},
                  open(os.path.join(CACHE, '_rebuild_summary.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
