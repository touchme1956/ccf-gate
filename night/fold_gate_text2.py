#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fold_gate_text2.py — **既定でたたむ・第二弾**（2026-08-21）

ユーザー指示「文字が多すぎる。もっとコンパクトにして文字は必要最小限にして」（3度目）→
「他のタブもすべてコンパクトにして」。

★当てずっぽうで畳まない。**画面に流れる字**（折り畳みの外・スクロール枠の外）を実測してから当てる。
  ⚠ 素朴に「タブの中の文字数」を数えると本命を間違える——
    Ⅱ実行手順は 9,580字あるが 6,000字近くは審査プロトコル全文＝`max-height:340px` の枠の中で、
    画面の高さを取っていない（v9.9.136 が既に記録している事実を、数え方に組み込んだ）。

  静的HTMLで字が多いのは **Ⅰ解説 / Ⅱ実行手順 / Ⅲ採点機 の3つだけ**。
  他の9タブは中身がJS描画のデータ（銘柄の行・数字）で、**文章ではない**ので畳む対象が無い。

区間ごとに印を分けてある（部分適用でも二重適用にならない）:
  data-fold="3" … ① Ⅰ解説(pg1) の `.panel`（採点ルーブリックの表）6本・`.cut`（補足）2本
  data-fold="4" … ② Ⅱ実行手順(pg8) の STEPカード5枚・`.block` 2本

**消さない**——たたむのは「読む順」の問題で、記録を捨てる話ではない（v9.9.134/136と同じ立場）。
本文テキストは1字も減らない（増えるのは summary に足した見出しの分だけ）。

安全装置は **fold_gate_text.py の実装をそのまま import する**（v9.9.65: 二重に持たない）:
  ・要素は開きタグと閉じタグを数えて取り出す（正規表現の最短一致に頼らない）
  ・たたむ中身が**タグ収支ゼロ**でなければ中止＝要素をまたいで切らない
  ・既に details の中にあるものは二重にたたまない
  ・**そのタブの範囲だけ**に当てる（`.panel` は他ページにも1本ある＝クラス名だけで当てると巻き込む）

⚠ `<p>` の中に `<details>` は置けない（HTMLの規則）。入れるとブラウザが p を割り、
   対の `</p>` が**空の段落**として残る（v9.9.137 の実害）。畳む先が p なら div へ書き換える。

使い方: python3 night/fold_gate_text2.py [--check]
  適用済みの区間は飛ばす。やり直すなら git checkout index.html してから回す。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fold_gate_text as F                    # 安全装置は借りる（再実装しない）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
CHECK = '--check' in sys.argv

MARK1 = 'data-fold="3"'      # Ⅰ解説
MARK2 = 'data-fold="4"'      # Ⅱ実行手順

problems = []
stats = {}


# ── 走査（F.find_elements はクラス指定の特殊形。開きタグの正規表現で一般化する）──────
def find_open(s, tag, open_re):
    """<tag …> … </tag> の範囲を、入れ子を数えて列挙する（開きタグを正規表現で指定）"""
    out = []
    pat = re.compile(open_re)
    step = re.compile(r'<(/?)%s\b[^>]*>' % tag)
    for m in pat.finditer(s):
        d, i = 1, m.end()
        while d:
            n = step.search(s, i)
            if not n:
                problems.append('閉じタグが見つからない: %s @%d' % (tag, m.start()))
                break
            d += -1 if n.group(1) else 1
            i = n.end()
            if d == 0:
                out.append((m.start(), m.end(), n.start(), n.end()))
    return out


def selftest():
    """find_open が F.find_elements と同じ答えを出すことを毎回証明する。
       走査を二つ持つこと自体は避けられない（片方はクラス・片方は style 指定）が、
       **食い違ったら止める**なら v9.9.65 の掟は守れる。"""
    s = open(HTML, encoding='utf-8').read()
    for cls in ('panel', 'cut', 'lens', 'block'):
        a = F.find_elements(s, 'div', cls)
        b = find_open(s, 'div', r'<div\b[^>]*class="%s"[^>]*>' % re.escape(cls))
        if a != b:
            problems.append('走査が食い違う（%s）: %d vs %d' % (cls, len(a), len(b)))
    return not problems


def page_span(s, pid):
    """<div id="pgN" …> の範囲を div 深さで切る"""
    m = re.search(r'<div[^>]*id="%s"[^>]*>' % pid, s)
    if not m:
        problems.append('%s が見つからない' % pid)
        return None
    d, i = 1, m.end()
    step = re.compile(r'<(/?)div\b[^>]*>')
    while d:
        n = step.search(s, i)
        if not n:
            problems.append('%s の閉じタグが見つからない' % pid)
            return None
        d += -1 if n.group(1) else 1
        i = n.end()
        if d == 0:
            return (m.end(), n.start())


def wrap(mark, summary, body, cl='why'):
    return ('<details class="%s" %s><summary>%s</summary><div class="why-body">'
            % (cl, mark, summary) + body + '</div></details>')


def fold_after(s, spans, label, head_re, mark, minlen=120, fallback=None):
    """要素の**中身**のうち、頭（見出し行）を summary に出して残りをたたむ。

    head_re が中身の先頭に一致すればそれを summary に、しなければ fallback(s, pos) を使う。
    fallback が None を返したら**その要素は触らない**（憶測で見出しを作らない）。
    """
    n = saved = 0
    for (a, ia, ib, b) in reversed(spans):
        body = s[ia:ib]
        if F.textlen(body) < minlen or F.in_details(s, a):
            continue
        if not F.balanced(body):
            problems.append('タグ収支が合わないので中止: %s @%d' % (label, a))
            continue
        m = re.match(head_re, body, flags=re.S)
        if m:
            summary, rest = m.group(1), body[m.end():]
        else:
            summary = fallback(s, a) if fallback else None
            if not summary:
                problems.append('summary に使える見出しが無い: %s @%d' % (label, a))
                continue
            rest = body
        if not (F.balanced(summary) and F.balanced(rest)) or F.textlen(rest) < 60:
            continue
        s = s[:ia] + wrap(mark, summary, rest) + s[ib:]
        n += 1
        saved += F.textlen(rest)
    stats[label] = (n, saved)
    return s


def nearest_h2(s, pos):
    best = None
    for m in re.finditer(r'<div class="h2"[^>]*>(.*?)</div>', s[:pos], flags=re.S):
        best = m.group(1)
    if not best:
        return None
    t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', best)).strip()
    return '<span class="lbl">%s</span>' % t if t else None


# ── ① Ⅰ解説（pg1）────────────────────────────────────────────────
def section_pg1(seg):
    """`.panel`（採点ルーブリックの表）と `.cut`（補足）。
       panel は `.panel-h`（表題）を summary に出したまま中身だけ畳む
       ——ラベルごと畳むと「詳しく」だけの空箱になる（v9.9.136 の fold_fm の教訓）。"""
    seg = fold_after(seg, F.find_elements(seg, 'div', 'panel'),
                     'Ⅰ解説 div.panel（表題を summary に）',
                     r'\s*(<div class="panel-h"[^>]*>.*?</div>)', MARK1,
                     fallback=nearest_h2)
    F.problems, F.MARK, F.stats = problems, MARK1, {}
    seg = F.fold_inner(seg, 'div', 'cut', '詳しく', 160, 'Ⅰ解説 div.cut（補足）')
    stats.update(F.stats)
    return seg


# ── ② Ⅱ実行手順（pg8）──────────────────────────────────────────────
STEP_HEAD = r'\s*(<div style="display:flex;gap:12px;align-items:baseline;margin-bottom:8px">.*?</div>\s*</div>)'
STEP_CARD = r'<div style="padding:14px 16px;background:rgba\((?:255,255,255,\.02|84,184,138,\.06)\);[^>]*>'
BLOCK_HEAD = (r'\s*(<div class="tag"[^>]*>.*?</div>\s*'
              r'<div class="h2"[^>]*>.*?</div>\s*'
              r'<p class="intro"[^>]*>.*?</p>)')


def section_pg8(seg):
    """STEPカード5枚は**番号と表題の行を summary に出したまま**中身だけ畳む。
       `.block` 2本（年次チェックリスト・コード保管庫）は tag+h2+intro を残して本体を畳む。
       ⚠ 実践ガイドの block は**丸ごとは畳まない**——中のSTEPを個別に畳んでおり、
         外側も畳むと二重になって「詳しく」の中に「詳しく」が並ぶ。"""
    cards = find_open(seg, 'div', STEP_CARD)
    seg = fold_after(seg, cards, 'Ⅱ手順 STEPカード（番号と表題を summary に）',
                     STEP_HEAD, MARK2, minlen=100)
    blocks = [x for x in F.find_elements(seg, 'div', 'block')
              if 'class="tag"' in seg[x[1]:x[2]][:200]]
    # 実践ガイド（STEPを内包する block）は除く
    blocks = [x for x in blocks if 'display:grid;gap:10px' not in seg[x[1]:x[2]]]
    seg = fold_after(seg, blocks, 'Ⅱ手順 div.block（tag+h2+導入を残して）',
                     BLOCK_HEAD, MARK2, minlen=200)
    return seg


def main():
    s = open(HTML, encoding='utf-8').read()
    before = len(s)
    if not selftest():
        print('✗ 自己検査で中止:')
        for p in problems:
            print('   -', p)
        return 1

    for pid, mark, fn in (('pg1', MARK1, section_pg1), ('pg8', MARK2, section_pg8)):
        sp = page_span(s, pid)
        if not sp:
            break
        a, b = sp
        if mark in s[a:b]:
            print('  %s は適用済み（飛ばす）' % pid)
            continue
        s = s[:a] + fn(s[a:b]) + s[b:]

    if problems:
        print('✗ %d 件の問題' % len(problems))
        for p in problems:
            print('   -', p)
        return 1

    for k, (cnt, sv) in stats.items():
        print('  %-38s %2d件  %6d字をたたむ' % (k, cnt, sv))
    if CHECK:
        print('✓ 当てられる（--check なので書き込んでいない）')
        return 0
    open(HTML, 'w', encoding='utf-8').write(s)
    print('index.html %d → %d 文字' % (before, len(s)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
