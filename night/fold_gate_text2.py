#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fold_gate_text2.py — **Ⅰ解説の参照表をたたむ**（2026-08-21新設）

ユーザー指示（3度目）「文字が多すぎる。もっとコンパクトにして文字は必要最小限にして」。

★まず数えた。**折り畳みの外・スクロール枠の外**にある字だけを、入れ子を数えて実測する:

    Ⅰ解説 9,052 ／ Ⅲ採点機 5,976 ／ Ⅱ実行手順 3,701 ／ 他は全部 800字未満（合計 20,979）

  ⚠ 素朴に数えると **Ⅱ実行手順が 9,580字で最大**に見える。だが 6,000字近くは
    **審査プロトコル全文＝ `max-height:340px;overflow:auto` のスクロール枠の中**で、
    画面の高さを取っていない（v9.9.136 が既に記録している）。
    **「文字数」と「画面に流れる量」は別物**なので、枠の中は数から外す。

  ⚠ Ⅲ採点機の 5,976字は **span.h（入力欄の注記）が 57件 3,389字**。
    **記入中に読む欄の説明**で、しかも `<span>` の中に `<details>` は入れ子として不正
    （v9.9.136 が同じ理由で見送っている）。残り 2,656字はラベル・見出し・ボタン＝削れない。

  ⇒ **手を入れる先は Ⅰ解説ただ一つ**。その 9,052字の内訳は
    `.panel`（採点ルーブリックの表）6本 4,728字 ＋ `.cut`（補足）2本 1,033字が主。

何をするか（**表示だけ**。採点・規則・閾値・売却規律・配分には一切触れない）:
  ① `.panel` の中身をたたむ。**`.panel-h`（表題）は summary に出したまま**
     ——ラベルごと畳むと「詳しく」だけの空箱になる（v9.9.136 の fold_fm の教訓）
  ② `.panel-h` を持たない表は、**直前の `.h2`（章見出し）を summary に借りる**
  ③ `.cut`（補足の囲み）の中身をたたむ

**消さない**——たたむのは「読む順」の問題で、記録を捨てる話ではない（v9.9.134/136と同じ立場）。
v9.9.134 は「11の要素パネルは採点ルーブリックそのものだから畳まない」と判断したが、
**畳んでも一押しで開く**ので参照性は失われない。3度の要望を受けての改定。

安全装置は **fold_gate_text.py の実装をそのまま import する**（v9.9.65: 二重に持たない）:
  ・要素は開きタグと閉じタグを数えて取り出す（正規表現の最短一致に頼らない）
  ・たたむ中身が**タグ収支ゼロ**でなければ中止＝要素をまたいで切らない
  ・既に details の中にあるものは二重にたたまない
  ・**Ⅰ解説(pg1)の範囲だけ**に当てる（`.panel` は他ページにも1本ある）

使い方: python3 night/fold_gate_text2.py [--check]
  適用済みなら何もしない。やり直すなら git checkout index.html してから回す。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fold_gate_text as F                    # 安全装置は借りる（再実装しない）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
CHECK = '--check' in sys.argv
MARK = 'data-fold="3"'

problems = []
stats = {}


def page_span(s, pid):
    """<div id="pgN" class="pg…"> の範囲を div 深さで切る"""
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


def nearest_h2(s, pos):
    """その位置より手前で最も近い <div class="h2"> の文字（表題を borrow する）"""
    best = None
    for m in re.finditer(r'<div class="h2"[^>]*>(.*?)</div>', s[:pos], flags=re.S):
        best = m.group(1)
    if not best:
        return None
    t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', best)).strip()
    return t or None


def fold_panels(s):
    """`.panel` の中身をたたむ。panel-h があればそれを summary に、無ければ直前の h2 を借りる"""
    n = saved = 0
    for (a, ia, ib, b) in reversed(F.find_elements(s, 'div', 'panel')):
        body = s[ia:ib]
        if F.textlen(body) < 120 or F.in_details(s, a):
            continue
        if not F.balanced(body):
            problems.append('タグ収支が合わないので中止: div.panel @%d' % a)
            continue
        m = re.match(r'\s*(<div class="panel-h"[^>]*>.*?</div>)(.*)$', body, flags=re.S)
        if m:
            summary, rest = m.group(1), m.group(2)
        else:
            h = nearest_h2(s, a)
            if not h:
                problems.append('summary に使える表題が無い: div.panel @%d' % a)
                continue
            summary, rest = '<span class="lbl">%s</span>' % h, body
        if not F.balanced(rest):
            problems.append('切り出した中身のタグ収支が合わない: div.panel @%d' % a)
            continue
        s = (s[:ia]
             + '<details class="why" %s><summary>%s</summary><div class="why-body">' % (MARK, summary)
             + rest + '</div></details>' + s[ib:])
        n += 1
        saved += F.textlen(rest)
    stats['div.panel（表題を summary に）'] = (n, saved)
    return s


def main():
    s = open(HTML, encoding='utf-8').read()
    before = len(s)
    if MARK in s:
        print('既に適用済み。やり直すなら git checkout index.html してから回すこと。')
        return 0

    sp = page_span(s, 'pg1')
    if not sp:
        print('✗ 中止:')
        for p in problems:
            print('   -', p)
        return 1
    a, b = sp
    seg = s[a:b]

    seg = fold_panels(seg)
    # ③ `.cut`（補足の囲み）は中身をそのままたたむ
    F.problems = problems
    F.MARK = MARK
    seg = F.fold_inner(seg, 'div', 'cut', '詳しく', 160, 'div.cut（補足）')
    stats.update(F.stats)

    if problems:
        print('✗ %d 件の問題' % len(problems))
        for p in problems:
            print('   -', p)
        return 1

    s = s[:a] + seg + s[b:]

    for k, (cnt, sv) in stats.items():
        print('  %-30s %2d件  %6d字をたたむ' % (k, cnt, sv))
    if CHECK:
        print('✓ 当てられる（--check なので書き込んでいない）')
        return 0
    open(HTML, 'w', encoding='utf-8').write(s)
    print('index.html %d → %d 文字' % (before, len(s)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
