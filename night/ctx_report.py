#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctx_report.py — 文脈（コンテキスト窓）の使われ方を実測する。

autocompact の空回りは「会話が長い」からではなく「1回の読みが大きい」から起きる。
床（毎ターン必ず入るもの）と、1回で窓を食い潰しうるファイルを数え、ガードの有無まで出す。
判定にも採点にも一切使わない。`python3 night/ctx_report.py [--all]`
"""
import json, os, signal, sys

WINDOW = 200_000          # 窓の目安
LIMIT_TOK = 25_000        # ctx_guard の上限と揃える


signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # `| head` で落ちないように


def est_tok(path):
    try:
        t = open(path, encoding='utf-8', errors='replace').read()
    except (OSError, UnicodeError):
        return 0
    a = sum(1 for c in t if ord(c) < 128)
    return int(a / 3.8 + (len(t) - a) * 0.95)


def walk(root='.'):
    skip = {'.git', 'node_modules', '__pycache__', 'out/logos', 'assets'}
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        dirs[:] = [x for x in dirs if x not in skip and os.path.join(rel, x).lstrip('./') not in skip]
        for f in files:
            p = os.path.normpath(os.path.join(rel, f))
            if os.path.splitext(f)[1].lower() in ('.png', '.jpg', '.svg', '.ico', '.zip', '.gz', '.woff2'):
                continue
            yield p


def main():
    show_all = '--all' in sys.argv
    floor = [p for p in ('CLAUDE.md', '.claude/settings.json') if os.path.exists(p)]
    ft = sum(est_tok(p) for p in floor)
    print(f'■ 床（毎ターン必ず入る） 概算 {ft:,} tok ＝ 窓 {WINDOW:,} の {ft/WINDOW*100:.0f}%')
    for p in floor:
        print(f'    {p:<28} {est_tok(p):>9,} tok')
    print(f'  残り作業に使える: 概算 {WINDOW-ft:,} tok（道具定義・要約ぶんを除くと実際はこれより少ない）')

    rows = sorted(((est_tok(p), p) for p in walk()), reverse=True)
    danger = [r for r in rows if r[0] > LIMIT_TOK]
    print(f'\n■ 1回の全文読みで {LIMIT_TOK:,} tok を超えるファイル: {len(danger)}件'
          f'（ctx_guard が Read と cat を止める）')
    for tok, p in (danger if show_all else danger[:12]):
        print(f'    {p:<40} {tok:>10,} tok  窓の {tok/WINDOW*100:5.1f}%')
    if not show_all and len(danger) > 12:
        print(f'    …他 {len(danger)-12}件（--all で全部）')

    print('\n■ ガードの設置')
    hook = os.path.exists('.claude/hooks/ctx_guard.py')
    wired = False
    if os.path.exists('.claude/settings.json'):
        s = json.load(open('.claude/settings.json', encoding='utf-8'))
        wired = 'ctx_guard.py' in json.dumps(s)
    print(f'    .claude/hooks/ctx_guard.py : {"あり" if hook else "無い"}')
    print(f'    settings.json の PreToolUse : {"結線ずみ" if wired else "未結線"}')
    print(f'    night/peek.py              : {"あり" if os.path.exists("night/peek.py") else "無い"}')
    if not (hook and wired):
        print('    ⚠ ガードが効いていない。この状態で index.html を Read すると 1回で窓の4割が埋まる')


if __name__ == '__main__':
    main()
