#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/jp_yuho_lines.py — **有報の本文キャッシュから、財務諸表の行（当期の値）を読む**（2026-09-23 新設・読むだけ）

発端（todo `jp_nde_definition_mix`）:
  日本株の nde が社によって違う定義で入っていた——リース債務を負債に数える／CF計算書の「現金及び現金同等物」
  （預入3か月超の定期預金を除く）を現金に使う／流動の有価証券を落とす／EBITDA にのれん償却を足す／EBIT で割る。
  2026-09-23 に68社を揃えたときに使った作業用の道具（scratchpad の jpfin.py / nde_extract.py）をここへ昇格した。

材料:
  `night/rebuild_src_cache_jp.py` が作る `out/_src_cache/{T}.txt` ＋ `{T}.src.json`（有報PDFを鍵なしで落として
  pypdf でテキスト化したもの。gitignore。消えていたら作り直す）。EDINET_DB MCP には依存しない。

何をするか:
  1. 【連結貸借対照表】【連結財政状態計算書】【連結損益計算書】【連結キャッシュ・フロー計算書】の見出し
     （直後に「単位」がある＝本当の表）で頁の範囲を決める。連結が無ければ単体。
  2. 行頭のラベルで行を拾い、**当期の列**の値を返す。当期の列は表の見出しの順で決める
     （たいていは 前期・当期 の順＝最後の列。中外製薬(4519)のように 当期・前期 の順の表もある）。
     折り返した行（ラベルだけの行の次に「※5 41,628」のような数字の行）は最大3行まで継ぐ。
     「△」「▲」は負、「-」「―」は 0。注記番号（※1・注記の列の「17,30」）は落とす。
  3. 既定（`--nde`）は nde の部品（現金及び預金・流動の有価証券・有利子負債の各行・リース・営業利益・減価償却・のれん償却）を
     並べ、規約どおりの nde を出す。

nde の規約（採取器 hachimon_fetch と同じ。2026-09-23 に日本株68社をこれへ揃えた）:
  nde = (有利子負債 − (現金及び預金 ＋ 流動の有価証券)) ÷ (営業利益 ＋ 減価償却費)
  ・有利子負債＝短期借入金・1年内返済予定の長期借入金・長期借入金・社債（1年内償還予定を含む）・CP・新株予約権付社債。
    **リース債務／リース負債は入れない**
  ・現金は **BS の「現金及び預金」**（IFRS は BS の「現金及び現金同等物」）。CF計算書の期末残高は使わない
  ・減価償却はソフトウエア・顧客関連資産などの償却も入れる。**のれん償却は足さない**

⚠ これは材料を並べる道具で、判定はしない。次は機械では決まらないので、頁を目で確かめてから値を置くこと:
  ・IFRS の「その他の金融資産」（流動）の中の定期預金——注記に**流動分の金額**があるときだけ現金に足す
    （6532 は足した／3989・6806・6981・9552 は内訳が無いので足していない）
  ・IFRS で借入金が「その他の金融負債」の中にある社（6806）／リースが「有利子負債」に含まれる社（7741 は注記16で分けた）
  ・営業利益の行が無い社（7741 は 営業利益相当・8113 は コア営業利益＝パックの gm・roic と同じ定義）
  ・減価償却が CF 本表に無い社（4519 は注記25『営業活動による現金創出額』）
  出力の `warn` がこれらの手がかりを名指しする。

使い方:
  python3 night/jp_yuho_lines.py 6861 --nde            # nde の部品と規約どおりの値
  python3 night/jp_yuho_lines.py 6861,4063 --nde --json
  python3 night/jp_yuho_lines.py 6861 --find '有価証券' --st bs   # 任意の行（bs/pl/cf）
"""
import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fill_growth_trend_jp as G   # noqa: E402  _latest_from_cache（キャッシュをページに戻す）を再利用

HEAD = re.compile(r'【(連結貸借対照表|連結財政状態計算書|貸借対照表|財政状態計算書|'
                  r'連結損益計算書及び連結包括利益計算書|連結損益及び包括利益計算書|連結損益計算書|連結純損益計算書|'
                  r'損益計算書|連結包括利益計算書|連結株主資本等変動計算書|連結持分変動計算書|株主資本等変動計算書|'
                  r'連結キャッシュ・フロー計算書|キャッシュ・フロー計算書|連結附属明細表|附属明細表)】')
KINDS = {
    'bs': (['連結貸借対照表', '連結財政状態計算書'], ['貸借対照表', '財政状態計算書']),
    'pl': (['連結損益計算書及び連結包括利益計算書', '連結損益及び包括利益計算書', '連結損益計算書', '連結純損益計算書'],
           ['損益計算書']),
    'cf': (['連結キャッシュ・フロー計算書'], ['キャッシュ・フロー計算書']),
}
NOTE = re.compile(r'※\s*\d+(?:\s*[,、]\s*※?\s*\d+)*|\(注\s*\d*\)|注\s*\d+(?=\s)')
NUMTOK = re.compile(r'(△|▲)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|(?<![\d,\w])[-―—−](?![\d\w])')


def nf(s):
    return unicodedata.normalize('NFKC', s or '')


def load(t):
    """{'docID','cover','pages'}。キャッシュが無ければ None（night/rebuild_src_cache_jp.py --only T で作る）。"""
    return G._latest_from_cache(t)


def heads(pages):
    """(頁index, 見出し, 位置)。表の見出し＝直後に単位の記載があるものだけ（目次の見出しを拾わない）。"""
    out = []
    for i, pg in enumerate(pages):
        s = nf(pg)
        for m in HEAD.finditer(s):
            if re.search(r'単位', s[m.end():m.end() + 250]):
                out.append((i, m.group(1), m.start()))
    return out


def statements(pages):
    """{'cons': bool, 'bs': (i0, i1), 'pl': ..., 'cf': ...}（頁 index の範囲・両端含む・最大4頁）。連結が無ければ単体。"""
    hs = heads(pages)
    if not hs:
        return {}
    has_cons = any(h in ('連結貸借対照表', '連結財政状態計算書') for _, h, _ in hs)
    res = {'cons': has_cons}
    for k, (cn, sn) in KINDS.items():
        names = cn if has_cons else sn
        first = next(((i, pos) for i, h, pos in hs if h in names), None)
        if first is None:
            continue
        i0 = first[0]
        nxt = [i for i, h, pos in hs if (i > i0 or (i == i0 and pos > first[1])) and h not in names]
        i1 = min(nxt + [i0 + 3])
        if nxt and min(nxt) == i0:
            i1 = i0
        res[k] = (i0, max(i0, min(i1, i0 + 3)))
    return res


def nums(s):
    s = NOTE.sub(' ', s)
    out = []
    for m in NUMTOK.finditer(s):
        if m.group(2) is None:
            out.append(0.0)
        else:
            v = float(m.group(2).replace(',', ''))
            out.append(-v if m.group(1) else v)
    return out


def unit_of(text):
    m = re.search(r'単位\s*[:：]?\s*(百万円|千円|円)', text)
    return m.group(1) if m else None


def lines_of(pages, rng):
    """範囲の頁の行 [(頁番号1始まり, 行)]"""
    return [(i + 1, ln) for i in range(rng[0], rng[1] + 1) for ln in nf(pages[i]).split('\n')]


def col_order(pages, rng):
    """表の見出しで 当期 が 前期 より先なら 'first'（中外製薬型）、そうでなければ 'last'。"""
    s = nf(pages[rng[0]])
    a = re.search(r'当連結会計年度|当事業年度', s)
    b = re.search(r'前連結会計年度|前事業年度', s)
    return 'first' if (a and b and a.start() < b.start()) else 'last'


def find(lines, label_re, ncol=2, want='last'):
    """ラベルで始まる行の当期の値。[{'pg','line','vals','cur'}]。
       注記の列（IFRS の「17,30」）が数字として混ざるので、当期は want='last' なら最後・'first' なら
       注記を除いた先頭——先頭の判定は呼び手が col_order で決める。"""
    rx = re.compile(r'^\s*(?:' + label_re + r')\s*(?:\(.*?\))?\s*(?=[※△▲\d\-―—−]|$)')
    hits = []
    for k, (pg, ln) in enumerate(lines):
        m = rx.match(ln)
        if not m:
            continue
        seg = ln[m.end():]
        vs = nums(seg)
        j = k + 1
        while len(vs) < ncol and j < len(lines) and j <= k + 3 and \
                re.match(r'^\s*(?:※\s*\d+\s*)?(?:[△▲]\s*)?(?:\d|[-―—−]\s*$|[-―—−]\s+[※△▲\d])', lines[j][1]):
            seg += ' ' + lines[j][1]
            vs = nums(seg)
            j += 1
        if vs:
            cur = vs[-1] if want == 'last' else (vs[-2] if len(vs) >= 2 else vs[0])
            hits.append({'pg': pg, 'line': ln.strip(), 'vals': vs, 'cur': cur})
    return hits


def section(lines, start, stop):
    out, on = [], False
    for pg, ln in lines:
        if not on and re.search(start, ln):
            on = True
            continue
        if on and re.search(stop, ln):
            break
        if on:
            out.append((pg, ln))
    return out


DEBT = [('短期借入金', r'短期借入金'),
        ('1年内返済予定の長期借入金', r'(?:1|一)年(?:以)?内(?:に)?返済予定の長期借入金'),
        ('長期借入金', r'長期借入金'),
        ('1年内償還予定の社債', r'(?:1|一)年(?:以)?内(?:に)?償還予定の社債'),
        ('社債', r'社債'),
        ('新株予約権付社債', r'(?:転換社債型)?新株予約権付社債'),
        ('コマーシャル・ペーパー', r'コマーシャル・?ペーパー'),
        ('借入金', r'借入金'),
        ('社債及び借入金', r'社債及び借入金')]
LEASE = [('リース債務', r'リース債務'), ('リース負債', r'リース負債')]
DA = (r'減価償却費及び償却費|減価償却費及びその他の償却費|減価償却費|ソフトウエア償却費|ソフトウェア償却費|'
      r'顧客関連資産償却額|顧客関連資産償却費|無形資産償却費|技術資産償却額')


def nde_parts(t):
    """nde の部品を並べ、規約どおりの nde と、目で確かめるべき手がかり warn を返す。"""
    d = load(t)
    if not d:
        return {'t': t, 'err': 'キャッシュが無い（python3 night/rebuild_src_cache_jp.py --only %s）' % t}
    pages = d['pages']
    st = statements(pages)
    r = {'t': t, 'docID': d['docID'], 'fy_end': (d.get('cover') or {}).get('fy_end'), 'cons': st.get('cons'), 'warn': []}
    for k in ('bs', 'pl', 'cf'):
        if k not in st:
            r['warn'].append(f'{k} の表の見出しが見つからない（性質別表示・見出しの表記ゆれ）——頁を目で読むこと')
    if 'bs' not in st:
        return r
    want = 'first' if col_order(pages, st['bs']) == 'first' else 'last'
    if want == 'first':
        r['warn'].append('当期の列が先（当期・前期の順の表）')
    bsL = lines_of(pages, st['bs'])
    r['unit'] = unit_of('\n'.join(nf(pages[i]) for i in range(st['bs'][0], st['bs'][1] + 1)))
    cur = section(bsL, r'^\s*流動資産\s*$|^\s*流動資産\s', r'^\s*流動資産合計|^\s*固定資産\s*$|^\s*非流動資産\s*$')
    liab = section(bsL, r'^\s*\(?負債の部\)?|^\s*負債\s*$', r'^\s*負債合計|^\s*純資産の部|^\s*資本\s*$')
    if not cur:
        cur = bsL
    if not liab:
        liab = bsL
        r['warn'].append('負債の部の区切りが見つからない——BS 全体から拾った')

    def pick(lines, rx):
        return [(x['pg'], x['cur'], x['line'][:80]) for x in find(lines, rx, want=want)]

    r['cash'] = pick(cur, r'現金及び預金|現金及び現金同等物')
    r['sec'] = pick(cur, r'有価証券')
    r['debt'], seen = [], set()
    for nm, rx in DEBT:
        for x in find(liab, rx, want=want):
            key = (x['pg'], x['line'])
            if key in seen:
                continue
            seen.add(key)
            r['debt'].append((nm, x['pg'], x['cur'], x['line'][:80]))
    r['lease'] = [(nm, x['pg'], x['cur'], x['line'][:80]) for nm, rx in LEASE for x in find(liab, rx, want=want)]
    if any(re.search(r'有利子負債', ln) for _, ln in liab):
        r['warn'].append('BS に「有利子負債」の行がある——リースを含むことが多い。注記の内訳で借入金だけに分けること（7741）')
    if any(re.search(r'^\s*その他の(?:短期)?金融資産', ln) for _, ln in cur):
        r['warn'].append('流動の「その他の金融資産」がある——注記に流動分の定期預金の金額があるときだけ現金に足す')
    if any(re.search(r'^\s*その他の(?:短期)?金融負債', ln) for _, ln in liab) and not r['debt']:
        r['warn'].append('借入金の行が無く「その他の金融負債」がある——注記の金融商品の分類に借入金が無いか見ること（6806）')
    if 'pl' in st:
        plL = lines_of(pages, st['pl'])
        r['op'] = [(x['pg'], x['cur'], x['line'][:80]) for x in find(plL, r'営業利益|営業利益又は営業損失|営業損失', want=want)]
        if not r['op']:
            r['warn'].append('営業利益の行が無い——パックの gm・roic と同じ定義の営業利益（相当）を使うこと')
    if 'cf' in st:
        cfL = lines_of(pages, (st['cf'][0], min(st['cf'][0] + 1, len(pages) - 1)))
        opcf = section(cfL, r'営業活動によるキャッシュ', r'^\s*小計')
        r['da'] = [(x['pg'], x['cur'], x['line'][:80]) for x in find(opcf, DA, want=want)]
        r['gw_am'] = [(x['pg'], x['cur'], x['line'][:80]) for x in find(opcf, r'のれん償却額|のれん償却費', want=want)]
        if not r['da']:
            r['warn'].append('CF 本表に減価償却の行が無い——注記（営業活動による現金創出額 等）を読むこと（4519）')
    names = [n for n, *_ in r['debt']]
    if any(names.count(n) > 1 for n in names):
        r['warn'].append('同じ科目の行が2つ（IFRS の流動・非流動）——両方足している')
    try:
        debt = sum(v for _, _, v, _ in r['debt'])
        cash = sum(v for _, v, _ in r['cash']) + sum(v for _, v, _ in r['sec'])
        ebitda = r['op'][0][1] + sum(v for _, v, _ in r['da'])
        r['nde'] = round((debt - cash) / ebitda, 4)
        r['calc'] = {'debt': debt, 'cash': cash, 'ebitda': ebitda}
    except (KeyError, IndexError, ZeroDivisionError):
        r['nde'] = None
    return r


def _fmt(r):
    if r.get('err'):
        return f"{r['t']}: {r['err']}"
    out = [f"== {r['t']} {r.get('docID')} FY末 {r.get('fy_end')} {'連結' if r.get('cons') else '単体'} 単位 {r.get('unit')}"]
    for k, lab in (('cash', '現金'), ('sec', '流動の有価証券'), ('debt', '有利子負債'), ('lease', 'リース（入れない）'),
                   ('op', '営業利益'), ('da', '減価償却'), ('gw_am', 'のれん償却（足さない）')):
        for x in r.get(k, []):
            out.append(f"  {lab:14} p.{x[-3]:<4} {x[-2]:>16,.0f}   {x[-1]}")
    if r.get('nde') is not None:
        c = r['calc']
        out.append(f"  nde = ({c['debt']:,.0f} − {c['cash']:,.0f}) ÷ {c['ebitda']:,.0f} = {r['nde']}")
    for w in r.get('warn', []):
        out.append(f"  ⚠ {w}")
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('tickers', help='カンマ区切りのコード')
    ap.add_argument('--nde', action='store_true', help='nde の部品と規約どおりの値')
    ap.add_argument('--find', help='任意のラベル（正規表現）')
    ap.add_argument('--st', default='bs', choices=['bs', 'pl', 'cf'])
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    res = {}
    for t in a.tickers.split(','):
        if a.find:
            d = load(t)
            if not d:
                res[t] = {'err': 'キャッシュが無い'}
                continue
            st = statements(d['pages'])
            if a.st not in st:
                res[t] = {'err': f'{a.st} の表が見つからない'}
                continue
            want = col_order(d['pages'], st[a.st])
            res[t] = find(lines_of(d['pages'], st[a.st]), a.find, want=want)
            if not a.json:
                for x in res[t]:
                    print(t, f"p.{x['pg']}", x['cur'], '|', x['line'][:100])
        else:
            res[t] = nde_parts(t)
            if not a.json:
                print(_fmt(res[t]))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
