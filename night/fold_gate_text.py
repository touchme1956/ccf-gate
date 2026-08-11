#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fold_gate_text.py — **既定でたたむ**（v9.9.136・2026-08-11新設）

ユーザー指示「文字が多すぎるので折りたたんだ状態にして」。
v9.9.134 で長い根拠を12箇所たたんだが、実測すると**まだ見えている字が多かった**——
実ブラウザで「折り畳みの外にある字」だけを数えた結果:

    🔔イベント 36,755字 ／ Ⅰ解説 17,400字 ／ Ⅱ実行手順 7,594 ／ Ⅲ採点機 6,055 ／ Ⅵ買付順位 4,914

  🔔イベントの内訳は **📌やるべきこと が 33,243字**（todo_list.json の note を全文表示していた。
  1件で16,401字のものがある）。Ⅰ解説は **p.ld（解説段落）14本で 6,939字**が最大の塊。

何をするか（**表示だけ**。採点・規則・閾値・売却規律・配分には一切触れない）:
  ① 📌やるべきこと の note を、**表題は出したまま**たたむ（長いものだけ）
  ② Ⅰ解説の各 lens の解説段落 <p class="ld"> をたたむ（lens の見出しは出たまま＝目次になる）
  ③ 長い <p class="intro"> は**最初の一文だけ残して**あとをたたむ（章の入口は読める）
  ④ Ⅵ買付順位・盤の長い説明もたたむ

**消さない**——たたむのは「読む順」の問題で、記録を捨てる話ではない（v9.9.134と同じ立場）。

安全装置（v9.9.134で DOM を壊した反省）:
  ・要素は**開きタグと閉じタグを数えて**取り出す（正規表現の最短一致に頼らない）
  ・たたむ中身が**タグ収支ゼロ**でなければ中止する＝要素をまたいで切らない
  ・既に details の中にあるものは二重にたたまない

使い方: python3 night/fold_gate_text.py [--check]
  適用済みなら何もしない。やり直すなら git checkout index.html してから回す。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
CHECK = '--check' in sys.argv
MARK = 'data-fold="2"'          # この版でたたんだ印（二重適用の防止）

problems = []
stats = {}


def textlen(html):
    return len(re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', html)))


def balanced(html):
    """中身のタグ収支がゼロか（要素をまたいで切っていないか）"""
    depth = {}
    for m in re.finditer(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>', html):
        closing, tag, rest = m.group(1), m.group(2).lower(), m.group(3)
        if tag in ('br', 'hr', 'img', 'input', 'meta', 'link', 'wbr', 'col', 'source'):
            continue
        if rest.rstrip().endswith('/'):
            continue
        depth[tag] = depth.get(tag, 0) + (-1 if closing else 1)
    return all(v == 0 for v in depth.values())


def find_elements(s, tag, cls):
    """<tag class="cls"> … </tag> の範囲を、入れ子を数えて列挙する。

    ⚠ 初版は閉じタグで**カーソルを進めていなかった**ので、入れ子のある要素で
      同じ </div> を何度も数えて**手前で切れていた**（div収支+2 で安全装置が拾った）。
      開き・閉じを1本の走査で順に見る形にして解消。
    """
    out = []
    pat = re.compile(r'<%s\b[^>]*class="%s"[^>]*>' % (tag, re.escape(cls)))
    step = re.compile(r'<(/?)%s\b[^>]*>' % tag)
    for m in pat.finditer(s):
        depth = 1
        i = m.end()
        while depth:
            n = step.search(s, i)
            if not n:
                problems.append('閉じタグが見つからない: %s.%s @%d' % (tag, cls, m.start()))
                break
            depth += -1 if n.group(1) else 1
            i = n.end()
            if depth == 0:
                out.append((m.start(), m.end(), n.start(), n.end()))
    return out


def in_details(s, pos):
    """その位置が既に details の中か（直前の <details と </details> の数で判定）"""
    head = s[:pos]
    return head.count('<details') > head.count('</details>')


def fold_inner(s, tag, cls, summary, minlen, label):
    """要素の**中身**をたたむ（開きタグ・閉じタグはそのまま残す＝レイアウトを壊さない）"""
    n = saved = 0
    for (a, inner_a, inner_b, b) in reversed(find_elements(s, tag, cls)):
        body = s[inner_a:inner_b]
        if textlen(body) < minlen:
            continue
        if in_details(s, a):
            continue
        if not balanced(body):
            problems.append('タグ収支が合わないので中止: %s.%s @%d' % (tag, cls, a))
            continue
        s = (s[:inner_a]
             + '<details class="why" %s><summary>%s</summary><div class="why-body">' % (MARK, summary)
             + body + '</div></details>' + s[inner_b:])
        n += 1
        saved += textlen(body)
    stats[label] = (n, saved)
    return s


def fold_intro(s, minlen=200):
    """長い intro は**最初の一文だけ残して**あとをたたむ（章の入口は読めるまま）"""
    n = saved = 0
    for (a, inner_a, inner_b, b) in reversed(find_elements(s, 'p', 'intro')):
        body = s[inner_a:inner_b]
        if textlen(body) < minlen or in_details(s, a):
            continue
        # 最初の「。」で切る。タグの途中で切らないよう、タグ外の「。」だけを探す
        cut = -1
        depth = 0
        for i, ch in enumerate(body):
            if ch == '<':
                depth += 1
            elif ch == '>':
                depth -= 1
            elif ch == '。' and depth <= 0 and textlen(body[:i]) >= 25:
                cut = i + 1
                break
        if cut < 0:
            continue
        lead, rest = body[:cut], body[cut:]
        if not (balanced(lead) and balanced(rest)) or textlen(rest) < 80:
            continue
        s = (s[:inner_a] + lead
             + '<details class="why" %s><summary>つづき</summary><div class="why-body">' % MARK
             + rest + '</div></details>' + s[inner_b:])
        n += 1
        saved += textlen(rest)
    stats['p.intro（最初の一文を残して）'] = (n, saved)
    return s


# ── 📌やるべきこと の note（JSのテンプレート文字列なので個別に当てる）──────────
TODO_OLD = ('''<div style="font-size:11px;color:var(--dim);margin-top:4px;line-height:1.7">${x.note||''}</div>''')
TODO_NEW = ('''<div style="font-size:11px;color:var(--dim);margin-top:4px;line-height:1.7">${
            !x.note ? '' :
            // 長い note は**表題を出したまま**たたむ（実測: 全75件で 33,243字＝画面の字の大半だった）
            (String(x.note).replace(/<[^>]+>/g,'').length <= 90 ? x.note
             : `<details class="why" ''' + MARK + '''><summary>詳しく</summary><div class="why-body">${x.note}</div></details>`)
          }</div>''')


def main():
    s = open(HTML, encoding='utf-8').read()
    before_len = len(s)

    if MARK in s:
        print('既に適用済み。やり直すなら git checkout index.html してから回すこと。')
        return 0

    # ① 📌やるべきこと の note
    if TODO_OLD in s:
        s = s.replace(TODO_OLD, TODO_NEW)
        stats['📌やるべきこと の note'] = (1, 0)
    else:
        problems.append('やるべきこと の note の描画箇所が見つからない')

    # ②③④ 静的な解説
    s = fold_inner(s, 'p', 'ld', '詳しく', 160, 'p.ld（lensの解説）')
    s = fold_inner(s, 'div', 'fm small', '詳しく', 260, 'div.fm small（式・補足）')
    s = fold_intro(s)

    if CHECK:
        if problems:
            print('✗ %d 件の問題' % len(problems))
            for p in problems:
                print('   -', p)
            return 1
        for k, (n, sv) in stats.items():
            print('  %-28s %2d件  %6d字をたたむ' % (k, n, sv))
        print('✓ 当てられる（--check なので書き込んでいない）')
        return 0

    if problems:
        print('✗ 中止:')
        for p in problems:
            print('   -', p)
        return 1

    open(HTML, 'w', encoding='utf-8').write(s)
    for k, (n, sv) in stats.items():
        print('  %-28s %2d件  %6d字をたたむ' % (k, n, sv))
    print('index.html %d → %d 文字' % (before_len, len(s)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
