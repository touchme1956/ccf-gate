#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fold_gate_text3.py — **説明をすべて畳む・第三弾**（2026-08-23）

ユーザー指示（4度目）:
  「門が使いにくい。使わないタブをなくして統合。**説明はすべて折りたたんで**使いやすく。
   とにかくコンパクトかつシンプルに使いやすく大改造してほしい。」

★当てずっぽうで畳まない。**実ブラウザで台帳369件を入れてから**、折り畳みの外に残っている
  「文章の塊」を要素単位で名指ししたうえで当てる（v9.9.166 と同じ作法）。
  実測（2026-08-23・群ナビ導入後）: 折り畳みの外 47,254字のうち **説明の文章は 27,692字**。
  残りは銘柄の行・数字＝**データであって説明ではない**ので畳む対象ではない。

## 何を畳むか（この版が足すのは data-fold="6"）
  ① 各タブの**見出し直下の導入文**（p.intro / p.sub / 見出し直下の色つきp）
     ——タブの h1 が既に「何の画面か」を言っているので、導入文は読む順の後ろでよい。
  ② Ⅰ解説(pg1) と Ⅲ採点機(pg2) に残る `.rc`（ルーブリックの刻みの表）と長い注記。

## 絶対に畳まないもの（畳むと「静かに壊れる側」を設計として作り込む）
  ・⚠ で始まる行（警告）  ・⛔ / ◇ の**落ちた社の名指し**  ・停止疑い / 読めなかった入力
  ・失敗の行・要修正・未解決
  この版は**静的HTMLの導入文だけ**を対象にするので、上のどれにも触れない
  （それらはすべて JS が描くもので、この道具は JS を1行も書き換えない）。

## 安全装置は fold_gate_text.py の実装をそのまま import する（v9.9.65: 二重に持たない）
  ・要素は開き／閉じタグを数えて取り出す（正規表現の最短一致に頼らない）
  ・たたむ中身が**タグ収支ゼロ**でなければ中止＝要素をまたいで切らない
  ・既に details の中にあるものは二重にたたまない
  ・**<p> の中に <details> は置けない**ので p は div へ書き換える（v9.9.137 の空の段落）

使い方: python3 night/fold_gate_text3.py [--check]
  適用済み（data-fold="6" が在る）なら何もしない。やり直すなら git checkout index.html。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fold_gate_text as F   # noqa: E402  安全装置を借りる

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
# ⚠ 印はこの道具だけが書くものにする。1〜5は既に使われていた
#    （1〜4は fold_gate_text/2 が、**5は JS が手書きで**）。
#    重複した印で「適用済みか」を判定すると、**一度も当てていないのに「適用済み」という嘘**を出す。
#    実際に踏んだ（2026-08-23）ので、下の検問で毎回それを確かめる。
MARK = 'data-fold="6"' 

# 畳んではいけない印。**行頭に**在るものだけを見る。
#  ⚠ 初版は「本文のどこかに含むか」で見ていたが、それでは
#    「点検の**要修正**0件」（四関門の定義文）や「**読めなかった**入力を必ず出す」（設計の説明）
#    まで守ってしまい、**説明文が5件 畳めなかった**（2026-08-23 に実測して是正）。
#    本物の警報は**行頭に印が立つ**（⚠…／⛔…）。しかもこの道具が触るのは
#    **静的な導入文だけ**で、生きた警報はすべて JS が描く＝そもそも射程に無い。
NEVER_HEAD = ('⚠', '⛔')


def _mask(t):
    """コメントとスクリプトを同じ長さの空白へ潰す（位置を保つ）。

    ⚠ fold_gate_text.in_details は `<details` と `</details>` を**素朴に数える**ので、
      **コメントや JS の文字列に出てくる `<details>` の字面**に騙される。
      実際に踏んだ（2026-08-23）——CSSの注釈にある
      「`<details>` は入れ子として不正（v9.9.136…）」の1個で収支が +1 になり、
      **以降のすべての要素が「既に details の中」と判定されて対象が0件**になった。
      0件は「畳むところが無い」ではなく「**当たっていない**」だった。
    """
    t = re.sub(r'<!--[\s\S]*?-->', lambda m: ' ' * len(m.group(0)), t)
    t = re.sub(r'<script[\s\S]*?</script>', lambda m: ' ' * len(m.group(0)), t)
    return t


def in_details_local(seg, pos):
    """**そのタブの範囲の中だけ**で判定する。ページ跨ぎの数え上げはしない
       （pgN の div は閉じているので、範囲内で開いたまま＝本当に中に居る）"""
    head = _mask(seg[:pos])
    return head.count('<details') > head.count('</details>')


def page_span(s, pid):
    """pgN の範囲（div の入れ子を数えて閉じるところまで）"""
    a = s.find('<div id="pg%d" class="pg' % pid)
    if a < 0:
        return None
    i = s.find('>', a) + 1
    d = 1
    while d and i < len(s):
        n1 = s.find('<div', i)
        n2 = s.find('</div>', i)
        if n2 < 0:
            break
        if n1 >= 0 and n1 < n2:
            d += 1
            i = n1 + 4
        else:
            d -= 1
            i = n2 + 6
    return (a, i)


def fold_one(s, a, b, summary):
    """[a,b) の <p ...>...</p> を <div>…<details>…</details></div> へ。
       ⚠ p は phrasing しか入れられないので **必ず div へ書き換える**"""
    m = re.match(r'<p\b([^>]*)>(.*)</p>\s*$', s[a:b], re.S)
    if not m:
        return None
    attrs, body = m.group(1), m.group(2)
    if not F.balanced(body):
        return None
    head = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', body))[:2]
    if any(head.startswith(x) for x in NEVER_HEAD):
        return None
    # ★2026-08-24新設: 押せるものを畳むと**字ではなく機能が消える**
    #   （v9.9.171/172 で他ページへの導線3本を実際に畳んだ）。先に外へ出すこと。
    pr = F.pressables(body)
    if pr:
        print('   ⏭ 押せるものが入っているので触らない: %s' % ' / '.join(pr[:3]))
        return None
    new = ('<div%s><details class="why plain" %s><summary>%s</summary>'
           '<div class="why-body">%s</div></details></div>' % (attrs, MARK, summary, body))
    return s[:a] + new + s[b:]


def targets(s):
    """畳む対象を (開始, 終了, 見出し) で列挙。**タブの範囲の中だけ**に当てる"""
    out = []
    for pid in range(1, 13):
        sp = page_span(s, pid)
        if not sp:
            continue
        a, b = sp
        seg = s[a:b]
        for m in re.finditer(
                # ⚠ 「見出し直下の説明文」は書き方が3通りある——class 指定・
                #    style で色だけ・style で font-size も。**綴りを列挙すると必ず取りこぼす**
                #    （実測: pg7 の 218字が style の先頭が font-size なので漏れた）。
                #    → style の**中に** color:var(--mut… が在るか、で見る。
                r'<p (?:class="(?:intro|sub|disc)"|style="[^"]*color:var\(--mut)[^>]*>.*?</p>',
                seg, re.S):
            txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(0))).strip()
            if len(txt) < 60:
                continue
            if in_details_local(seg, m.start()):
                continue
            if MARK in m.group(0):        # その要素は当て済み（部分適用の続きを許す）
                continue
            out.append((a + m.start(), a + m.end(), pid, len(txt), txt[:40]))
    return out


def main():
    check = '--check' in sys.argv
    s = open(HTML, encoding='utf-8').read()

    # ⚠ 印がこの道具の専用か確かめる。他所が同じ印を使っていると
    #   「一度も当てていないのに適用済み」という嘘を出す（2026-08-23 に実際に踏んだ）。
    body = re.sub(r'<script[\s\S]*?</script>', '', s)
    if MARK in s and MARK not in body:
        print('⚠ 印 %s が **スクリプトの中**で使われている＝この道具の専用ではない。'
              '別の番号にすること' % MARK)
        return 1

    # ⚠ ファイル全体に印が在っても「全部当て済み」とは限らない（部分適用の続き）。
    #   **要素ごと**に見て、残りが0件のときだけ「適用済み」と言う。

    tg = targets(s)
    if not tg:
        if MARK in s:
            print('✓ 適用済み（残り0件）')
            return 0
        print('⚠ 畳む対象が1つも見つからない——**当たっていない**（0は測定ではないことがある）')
        return 1

    print('■ 畳む対象 %d件' % len(tg))
    for (a, b, pid, n, t) in tg:
        print('   pg%-3d %5d字  %s' % (pid, n, t))
    if check:
        return 0

    done = skipped = saved = 0
    for (a, b, pid, n, t) in sorted(tg, reverse=True):     # 後ろから当てる（位置がずれない）
        r = fold_one(s, a, b, 'ℹ この画面について')
        if r is None:
            skipped += 1
            print('   ⏭ pg%d は触らない（タグ収支が合わない／行頭が警報の印）: %s' % (pid, t))
            continue
        s = r
        done += 1
        saved += n

    open(HTML, 'w', encoding='utf-8').write(s)
    print('\n✓ 畳んだ %d件（%,d字を折り畳みの中へ）／触らなかった %d件'
          .replace('%,d', '%d') % (done, saved, skipped))
    print('  **本文は1字も減っていない**——一押しで全部出る（記録を捨てる話ではない）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
