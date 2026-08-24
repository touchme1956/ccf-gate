#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fold_gate_js.py — **JS描画側の説明をたたむ**（v9.9.172・2026-08-23新設）

ユーザー指示「説明はすべて折りたたんで使いやすく」。
v9.9.171（fold_gate_text3.py）は**静的な導入文14本**をたたんだが、実測すると
それは 3,100字しかなく、**説明の本体は JS が描いている側**だった——

    Ⅵ買付順位 9,912字 ／ 📊盤 3,066 ／ ✎採点機 3,781 ／ 📖解説 3,357 ／ ⚙自動化 2,758 ／ 📈成績 2,721

その大半が **renderPlan() の中の「なぜ落ちるのか」の説明**（⛔各節の前置き）と
**Ⅵの凡例**。ここをたたむ。

★**たたまないもの**（v9.9.52 / fail-loud）:
   ⚠警告 ／ ⛔◇で**名指しされた銘柄の行** ／ 停止疑い ／ 読めなかった入力 ／
   「今月は城へ配らない」等の**状態の通知** ／ ✋手で決めた重み ／ ◆重ねている記録。
   ——**落ちた社を名指しで出す**のがこの門の作法で、隠すのは*説明*だけ。

安全装置:
  ・**たたむ範囲は明示の表で持つ**（広い正規表現で一括りにしない）。
    表に無いものは触らない＝どのブロックをたたんだかが後から読める
  ・鍵(key)がちょうど1つのブロックにしか当たらないことを検査する（0件でも2件でも中止）
  ・たたむ中身の**タグ収支がゼロ**か（要素をまたいで切らない・fold_gate_text の balanced を再利用）
  ・**${...} の中で切らない**——JSのテンプレート式の途中に挿すと構文が壊れる
  ・既に data-fold="7" があれば何もしない（再適用しても安全）

使い方: python3 night/fold_gate_js.py [--check]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fold_gate_text as F            # balanced() を再実装しない（v9.9.65）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
CHECK = '--check' in sys.argv
MARK = 'data-fold="7"'

# ── ① ブロックまるごとたたむ（純粋な説明だけ。表の順に処理する）──────────────
#    key = そのブロックにしか無い文字列 / summary = 畳んだときに出る見出し
WHOLE = [
    ('の不足分で按分（不足の大きい銘柄に厚い）',      'ℹ この一覧の読み方（按分と番号）'),
    ('指値は階段で置く——',                          'ℹ 指値の置き方・目標ウェイトの決め方'),
    ('＝規約違反・内部矛盾・ありえない値',            'ℹ 要修正／警告／測定漏れ の意味'),
    ('=終値ベース（証券口座の含み損益と一致',        'ℹ 価格ベースと配当込みの違い'),
    ('すべて表示専用——Ω・採点式・四関門',            'ℹ この画面について（表示専用）'),
    ('これは判定ではありません</b>——門の採点',       'ℹ この節について（門は⛔のまま）'),
    ('この行は古い手動審査の残骸です',                'ℹ なぜ落ちるのか・直し方'),
    ('縮んでいる会社は買わない',                      'ℹ なぜ落ちるのか（事業の収縮）'),
    ('または存続級依存≥40%（ベト）',                 'ℹ なぜ落ちるのか（堀不足）'),
    ('値が壊れている銘柄は買わない',                  'ℹ なぜ落ちるのか（データの破損）'),
    ('採点しているのが「今の会社」ではない',          'ℹ なぜ落ちるのか（期末後の重大事象）'),
    ('採点しているのが「これからの会社」ではない',    'ℹ なぜ落ちるのか（未完了の重大事象）'),
    ('納品検査（validate_packs）がFAILした組',        'ℹ なぜ落ちるのか（納品検査FAIL）'),
    ('四関門</b>：<b>🟢投下可＝格75+',                'ℹ 四関門と各群の凡例'),
]

# ── ② 一部だけたたむ（⚠や名指しが同じブロックに同居しているもの）──────────────
#    (start, end, summary) — start の頭から end の末尾までを畳む
PARTS = [
    # 🟢投下可: 凡例だけ畳む（城内合計と「全て目標充足」の通知は出したまま）
    ('<b style="color:var(--gold-bright)">目標%</b>＝総資産に対する',
     'gap按分＝金額。<br>',
     'ℹ 目標%／今月% の意味'),
    # ◇参考E[r]: 銘柄名つきの内訳は出したまま、思想の説明だけ畳む
    ('<span style="color:var(--dim)">門は価格を合否に使わない',
     '深段＝fair線。</span>',
     'ℹ なぜ価格を合否に使わないのか'),
    # ◈網: 冒頭の説明だけ畳む（⚠重みの食い違い・◆重ねている記録は出したまま）
    ('網は<b>指数なので門Ωにかけない</b>',
     "（<code>out/net_plan.json</code>${N.asof?'・'+N.asof:''}）。",
     'ℹ この節が出すもの・出さないもの'),
    ('——2026-08-23 のユーザー指示「保有に入れてほしい」',
     '<b>state.json へ書き出して初めて repo に残る</b>。',
     'ℹ 経緯'),
    # ⚙自動化: 凡例（回転盤のカードは別に畳んである）
    ('「自動」＝CIが回す（market.yml=毎営業日',
     '門0発掘=companyfacts 1.4GB）。判定には不使用',
     'ℹ 自動／鍵で自動／手動 の意味'),
    ('2026-08-17: **各作業が何をしているかは',
     'ので手順は要らない',
     'ℹ この一覧について'),
]

# ── ③ ステップカードの中身（<b>表題</b> — 本文 の形。**表題は出したまま**中身だけ畳む）──
AFTER_B = [
    ('漏斗（年1回）',                          'ℹ やること'),
    ('SEC採取器（月次・上位5社）',              'ℹ やること'),
    ('Claudeが定性を仕上げる',                  'ℹ やること'),
    ('採点機に貼る → 質スコア・ティア・間（価格）', 'ℹ やること'),
]

# ── ④ <p> の中身を畳む（**p には details を入れられない**ので div へ書き換える）──
#    v9.9.137 の実害: <p> の中に <details> を入れるとブラウザが p をその場で閉じ、
#    対の </p> が**空の段落**として残って margin だけを取る。
PCONV = [
    ('これは「選択基準」ではなく「高値づかみ防止」', 'ℹ なぜPERで銘柄を選ばないのか'),
    ('① 銘柄名を入れて「依頼文を作る」を押す',      'ℹ 手順（3ステップ）'),
]

# ── ⑤ .fm small はラベルを summary にして中身だけ畳む（ラベルごと畳むと空箱に見える）──
FM = ['補助 — 上限超過時だけ使う「目標株価」']

DIV_OPEN = re.compile(r'<div\b[^>]*style="[^"]*color:var\(--(?:dim|muted)\)[^"]*"[^>]*>')
STEP = re.compile(r'<(/?)div\b[^>]*>')
problems = []
stats = []


def in_script(s, p):
    for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?</script>', s):
        if m.start() <= p < m.end():
            return True
    return False


def textlen(h):
    """**今 画面に出ている字**だけ数える（既に details の中にある字は数えない）。
       全部を数えると「7,307字たたむ」のような**過大な報告**になる——実際に隠れるのは
       details の外にある字だけ。数字を大きく見せない。"""
    depth = 0
    buf = ''
    for mm in re.finditer(r'<(/?)details\b[^>]*>|[^<]+|<[^>]+>', h):
        t = mm.group(0)
        if t.startswith('<details'):
            depth += 1
        elif t.startswith('</details'):
            depth -= 1
        elif depth == 0:
            buf += t
    buf = re.sub(r'\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', buf)
    return len(re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', buf)))


def brace_ok(s, a, b):
    """[a,b) を切っても ${...} を割らないか（テンプレート式の途中に挿すと構文が壊れる）"""
    d = 0
    i = a
    while i < b:
        if s.startswith('${', i):
            d += 1
            i += 2
            continue
        if s[i] == '}' and d > 0:
            d -= 1
        i += 1
    return d == 0


def fold_span(s, a, b, summary, label):
    """s[a:b) を details でくるむ"""
    body = s[a:b]
    if not F.balanced(body):
        problems.append('タグ収支が合わない: %s' % label)
        return s
    if not brace_ok(s, a, b):
        problems.append('${...} の途中で切ろうとした: %s' % label)
        return s
    pr = F.pressables(body)
    if pr:
        # ★2026-08-24新設: 押せるものを畳むと**字ではなく機能が消える**（導線3本を実際に畳んだ）
        problems.append('押せるものが入っている（先に外へ出す）: %s ← %s' % (label, ' / '.join(pr[:3])))
        return s
    stats.append((label, textlen(body)))
    return (s[:a]
            + '<details class="why plain" %s><summary>%s</summary><div class="why-body">' % (MARK, summary)
            + body + '</div></details>' + s[b:])


def find_block(s, key):
    """key を含む「説明の div」をちょうど1つ見つけて (中身の開始, 中身の終わり) を返す"""
    hits = []
    for m in DIV_OPEN.finditer(s):
        if not in_script(s, m.start()):
            continue
        d = 1
        i = m.end()
        ea = -1
        while d:
            n = STEP.search(s, i)
            if not n:
                break
            d += -1 if n.group(1) else 1
            i = n.end()
            if d == 0:
                ea = n.start()
        if ea < 0:
            continue
        if key in s[m.end():ea]:
            hits.append((m.end(), ea))
    if len(hits) != 1:
        problems.append('鍵が %d 箇所に当たった（1箇所でなければ触らない）: %r' % (len(hits), key))
        return None
    return hits[0]


def main():
    s = open(HTML, encoding='utf-8').read()
    before = len(s)
    # ★**目標ごとに**判定する（全体で1回きりにすると、あとから表を足せなくなる）
    # ★**適用済みかの見方は種類で逆になる**（一度これで二重に包んだ・実測4箇所）——
    #   ブロックまるごと(WHOLE/step/fm/p→div)は範囲の**先頭に** <details> が入るので前を見る。
    #   一部たたみ(PARTS)は目印の**手前に** <details> が入るので後ろを見る。
    #   片方だけで済ませると、もう片方が毎回「未適用」に見えて再実行で二重に包む。
    def done_f(a):
        return MARK in s[a:a + 140]

    def done_b(a):
        return MARK in s[max(0, a - 140):a]

    # 後ろから当てる（前を書き換えると後ろの位置がずれるため）
    todo = []
    for key, summary in WHOLE:
        r = find_block(s, key)
        if r and not done_f(r[0]):
            todo.append((r[0], r[1], summary, 'whole: ' + key[:22]))  # noqa
    for start, end, summary in PARTS:
        if s.count(start) != 1 or s.count(end) != 1:
            problems.append('部分たたみの目印が1箇所でない: %r (%d) / %r (%d)'
                            % (start[:24], s.count(start), end[:24], s.count(end)))
            continue
        a = s.index(start)
        b = s.index(end) + len(end)
        if done_b(a):
            continue
        if b <= a:
            problems.append('部分たたみの前後が逆: %r' % start[:24])
            continue
        todo.append((a, b, summary, 'part : ' + start[:22]))

    # ③ ステップカード: <b ...>表題</b> — から、その div の終わりまで
    for title, summary in AFTER_B:
        m = re.search(r'<b[^>]*>%s</b>\s*—\s*' % re.escape(title), s)
        if not m:
            problems.append('ステップカードの表題が見つからない: %r' % title)
            continue
        if done_f(m.end()):
            continue
        d, i, ea = 1, m.end(), -1
        while d:
            n = STEP.search(s, i)
            if not n:
                break
            d += -1 if n.group(1) else 1
            i = n.end()
            if d == 0:
                ea = n.start()
        if ea < 0:
            problems.append('ステップカードの閉じが見つからない: %r' % title)
            continue
        todo.append((m.end(), ea, summary, 'step : ' + title[:22]))

    # ④ <p> は div へ書き換えてから畳む
    for key, summary in PCONV:
        hits = [m for m in re.finditer(r'<p\b[^>]*>', s)
                if key in s[m.end():s.find('</p>', m.end())]]
        if not hits:
            # 既に <div> へ書き換え済みなら <p> では見つからない。MARK が直前にあれば適用済み
            k = s.find(key)
            if k >= 0 and MARK in s[max(0, k - 300):k]:
                continue
            problems.append('<p> の鍵が見つからない: %r' % key[:22])
            continue
        if len(hits) != 1:
            problems.append('<p> の鍵が %d 箇所: %r' % (len(hits), key[:22]))
            continue
        m = hits[0]
        e = s.find('</p>', m.end())
        # ★2026-08-24 是正: ここに `done(m.end())` という**定義されていない関数**の呼び出しが在った。
        #   PCONV の鍵が <p> として1回だけ見つかるとき＝**クリーンな index.html に当てるとき**にだけ通る枝なので、
        #   一度当てた後の再実行では `not hits` で先に continue して**永久に踏まない**＝
        #   「動いているから正しい」に見えていた。判定は下の done_f が正しく持っている。
        # ★todo と**同じ列**に入れる（別々に当てると、先に当てた分だけ位置がずれて
        #   「タグ収支が合わない」という嘘の中止になる。実際に一度そうなった）
        if done_f(m.end()):
            continue
        todo.append((m.end(), e, summary, 'p→div: ' + key[:18], m.start(), e + 4))

    # ⑤ .fm small はラベルを summary に
    for key in FM:
        m = re.search(r'<span class="lbl"[^>]*>%s</span>' % re.escape(key), s)
        if not m:
            # ★2026-08-24 是正: 適用すると `<span class="lbl">` は `<summary class="lbl">` になるので、
            #   **当てた後は「ラベルが見つからない」という嘘の中止**になっていた（再実行できない＝
            #   クリーンから作り直すと途中で止まる）。summary になっていれば適用済みとして黙って飛ばす。
            if re.search(r'<summary class="lbl"[^>]*>%s</summary>' % re.escape(key), s):
                continue
            problems.append('.fm small のラベルが見つからない: %r' % key)
            continue
        if done_f(m.end()):
            continue
        d, i, ea = 1, m.end(), -1
        while d:
            n = STEP.search(s, i)
            if not n:
                break
            d += -1 if n.group(1) else 1
            i = n.end()
            if d == 0:
                ea = n.start()
        if ea < 0:
            problems.append('.fm small の閉じが見つからない: %r' % key)
            continue
        todo.append((m.end(), ea, key, 'fm   : ' + key[:22]))

    todo = [(t + (None, None))[:6] for t in todo]
    todo.sort(key=lambda x: -x[0])
    # 範囲が重なっていないか（重なると入れ子が壊れる）
    for i in range(len(todo) - 1):
        if todo[i][0] < todo[i + 1][1]:
            problems.append('たたむ範囲が重なっている: %s / %s' % (todo[i][3], todo[i + 1][3]))

    if problems:
        print('✗ 中止:')
        for p in problems:
            print('   -', p)
        return 1

    for a, b, summary, label, oa, cb in todo:
        if oa is None:
            s = fold_span(s, a, b, summary, label)
            continue
        body = s[a:b]
        if not F.balanced(body):
            problems.append('タグ収支が合わない: %s' % label)
            continue
        pr = F.pressables(body)
        if pr:
            problems.append('押せるものが入っている（先に外へ出す）: %s ← %s' % (label, ' / '.join(pr[:3])))
            continue
        stats.append((label, textlen(body)))
        s = (s[:oa] + s[oa:a].replace('<p', '<div', 1)
             + '<details class="why plain" %s><summary>%s</summary><div class="why-body">' % (MARK, summary)
             + body + '</div></details></div>' + s[cb:])

    if problems:
        print('✗ 中止:')
        for p in problems:
            print('   -', p)
        return 1

    # ★最後の砦——**同じ折り畳みで二重に包んでいないか**。
    #   適用済みの判定を間違えると必ずここに出る（実測で一度作った）。
    dbl = re.findall(r'(<details class="why plain" %s><summary>(?:(?!</summary>).)*</summary>'
                     r'<div class="why-body">)\1' % re.escape(MARK), s)
    if dbl:
        print('✗ 中止: 同じ折り畳みで**二重に包んで**しまう %d 箇所（適用済みの判定が誤り）' % len(dbl))
        return 1

    tot = sum(n for _, n in stats)
    for label, n in sorted(stats, key=lambda x: -x[1]):
        print('  %-34s %5d字' % (label, n))
    print('  ---- %d件 合計 %d字をたたむ' % (len(stats), tot))
    if CHECK:
        print('✓ 当てられる（--check なので書き込んでいない）')
        return 0
    open(HTML, 'w', encoding='utf-8').write(s)
    print('index.html %d → %d 文字' % (before, len(s)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
