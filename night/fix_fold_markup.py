#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fix_fold_markup.py — **v9.9.136 の折り畳みが作った「空白と空の段落」を直す**（v9.9.137・2026-08-11）

ユーザー報告「なんかおかしいところが多い。文字がないところがあったり無駄なスペースを使ったり」。

■ 原因は1つ。**<details> は block、<p> は phrasing しか入れられない**（HTMLの規則）。
  v9.9.136 は `<p class="ld">` と `<p class="intro">` の**中**に <details> を入れた。
  ブラウザはこれを不正と見なし、**<p> をその場で閉じて <details> を外へ出す**。
  結果、対になる `</p>` が**空の段落**として残り、段落の margin（24px）だけを取る。
    実測: 空の <p> が **1個 → 13個**（+12）＝これが「文字がないところ」と「無駄なスペース」の正体。
  実測: `p.intro`/`p.ld` の中に details が残っているものは **0件**＝全部ブラウザに追い出されていた。

■ もう1つ: `.fm small` は**ラベルごと**たたんでいた。
  `<span class="lbl">共通記号と前提</span>` が中身側に入っていたので、
  箱の中身が「詳しく」だけになり、**72px の空箱**に見えていた。

■ 直し方（表示だけ。採点・規則・閾値・売却規律・配分には触れない）
  ① details を含む `<p class="ld">` / `<p class="intro">` は **<div> に変える**
     （CSSは `.intro{}` / `.lens .ld{}` とクラス指定なので見た目は変わらない＝実測で確認）
  ② `.fm small` の折り畳みは **ラベルを summary にする**（「詳しく」という無意味な語も消える）

使い方: python3 night/fix_fold_markup.py [--check]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
CHECK = '--check' in sys.argv


def find_elements(s, tag, cls):
    """<tag class="cls"> … </tag> を入れ子を数えて列挙"""
    out = []
    pat = re.compile(r'<%s\b[^>]*class="%s"[^>]*>' % (tag, re.escape(cls)))
    step = re.compile(r'<(/?)%s\b[^>]*>' % tag)
    for m in pat.finditer(s):
        depth, i = 1, m.end()
        while depth:
            n = step.search(s, i)
            if not n:
                break
            depth += -1 if n.group(1) else 1
            i = n.end()
            if depth == 0:
                out.append((m.start(), m.end(), n.start(), n.end()))
    return out


def main():
    s = open(HTML, encoding='utf-8').read()
    n_p = n_lbl = n_tag = 0

    # ① <p> の中の <details> は不正。<div> へ変える（後ろから当てて位置ずれを防ぐ）
    for cls in ('ld', 'intro'):
        for (a, oe, ce, cend) in reversed(find_elements(s, 'p', cls)):
            body = s[oe:ce]
            if '<details class="why"' not in body:
                continue
            open_tag = s[a:oe].replace('<p', '<div', 1)
            s = s[:a] + open_tag + body + '</div>' + s[cend:]
            n_p += 1

    # ② .fm small は**ラベルを summary に**（中身だけたたむ）。「詳しく」の語も要らなくなる
    pat = re.compile(
        r'(<div class="fm small"[^>]*>)\s*'
        r'<details class="why" data-fold="2"><summary>詳しく</summary>'
        r'<div class="why-body">\s*(<span class="lbl"[^>]*>.*?</span>)',
        flags=re.S)
    s, n_lbl = pat.subn(
        r'\1<details class="why" data-fold="2"><summary>\2</summary>'
        r'<div class="why-body">', s)

    # ③ v9.9.134 が要素をまたいで切ったせいで、開き/閉じタグが本体の外に
    #    取り残されていた3件（main には適用済みなので通常は0件）
    for a, b in [
        ('<u><details class="why"><summary>なぜ等ウェイトにしたか（旧式との実測比較・ケリー比率）</summary><div class="why-body">',
         '<details class="why"><summary>なぜ等ウェイトにしたか（旧式との実測比較・ケリー比率）</summary><div class="why-body"><u>'),
        ('が根拠の質を検査して再監査の作業リストを出す。</div></details></span></div>',
         'が根拠の質を検査して再監査の作業リストを出す。</span></div></details></div>'),
        ('であり検証された事実ではない。<b></div></details>門は失格を弾く番人であって',
         'であり検証された事実ではない。</div></details><b>門は失格を弾く番人であって'),
    ]:
        if a in s:
            s = s.replace(a, b)
            n_tag += 1

    if CHECK:
        print('  <p>→<div> に変える折り畳み : %d 件' % n_p)
        print('  ラベルを summary にする箱  : %d 件' % n_lbl)
        print('  取り残しタグの是正         : %d 件' % n_tag)
        return 0

    open(HTML, 'w', encoding='utf-8').write(s)
    print('  <p>→<div> に変えた折り畳み : %d 件' % n_p)
    print('  ラベルを summary にした箱  : %d 件' % n_lbl)
    print('  取り残しタグを是正         : %d 件' % n_tag)
    return 0


if __name__ == '__main__':
    sys.exit(main())
