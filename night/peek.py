#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peek.py — 大きいファイルを「文脈を溢れさせずに」読むための覗き窓。

autocompact の空回り（compact 直後3ターンで窓が満杯）の直接原因は、
巨大ファイルの全文読みが1回の道具呼び出しで数万〜数十万トークンを入れることだった。
実測: index.html を既定の Read(2000行) で開くと約 81,800 tok、全文なら約 288,700 tok。

この道具は「まず地図、次に必要な行だけ」を強制する。中身は一切書き換えない（読み取り専用）。

  python3 night/peek.py map  index.html              目次（行番号・区間の大きさ・概算tok）
  python3 night/peek.py find index.html ccfAllocTop  名前の定義位置と、その区間だけ
  python3 night/peek.py grep index.html 'moatIdx'    一致行だけ（長い行は切る）
  python3 night/peek.py lines index.html 1200 1260   行範囲（長い行は切る）
  python3 night/peek.py json out/score_all.json      JSONの「形」だけ（中身は出さない）
  python3 night/peek.py size index.html CLAUDE.md    文脈コストの見積り
"""
import json, os, re, signal, sys

MAXLINE = 400          # 1行あたりの上限（46,650字の行が実在する）
MAXOUT  = 60_000       # 1回の出力の上限バイト（概算 2万tok弱）


signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # `| head` で落ちないように


def est_tok(s: str) -> int:
    """概算トークン数。日本語は約0.95tok/字、ASCIIは約1/3.8字。厳密値ではない。"""
    a = sum(1 for c in s if ord(c) < 128)
    return int(a / 3.8 + (len(s) - a) * 0.95)


def read_lines(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read().split('\n')


def clip(line):
    if len(line) <= MAXLINE:
        return line
    return line[:MAXLINE] + f'  …〔{len(line):,}字のうち先頭{MAXLINE}字。全体は peek.py lines で範囲を絞るか、grep で当てる〕'


def emit(rows):
    """出力量そのものに上限を掛ける（道具が事故の発生源にならないように）。"""
    out, n = [], 0
    for r in rows:
        b = len(r.encode()) + 1
        if n + b > MAXOUT:
            out.append(f'…〔ここで打ち切り。残り {len(rows) - len(out)} 行。範囲を狭めて呼び直すこと〕')
            break
        out.append(r)
        n += b
    print('\n'.join(out))


# ---- 目次 ----------------------------------------------------------------
PATS = [
    # (正規表現, 種別) — HTML / JS / Python / Markdown を同じ地図に載せる
    (re.compile(r'^\s*<section\b[^>]*id="([^"]+)"'), 'section'),
    (re.compile(r'^\s*<(h[1-3])\b[^>]*>(.{0,60})'), 'heading'),
    (re.compile(r'^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)'), 'fn'),
    (re.compile(r'^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()'), 'fn'),
    (re.compile(r'^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)'), 'def'),
    (re.compile(r'^\s*class\s+([A-Za-z_][\w]*)'), 'class'),
    (re.compile(r'^\s*<(script|style)\b'), 'block'),
    (re.compile(r'^(#{1,3})\s+(.{0,70})'), 'md'),
    (re.compile(r'^\s*(?://|#)\s*=====+\s*(.{0,60})'), 'banner'),
]


def cmd_map(path):
    lines = read_lines(path)
    hits = []
    for i, l in enumerate(lines):
        for pat, kind in PATS:
            m = pat.match(l)
            if m:
                label = ' '.join(g for g in m.groups() if g).strip()
                hits.append((i + 1, kind, label[:70]))
                break
    total = sum(len(l) + 1 for l in lines)
    rows = [f'{path}  {len(lines):,}行 / {total:,}字 / 概算 {est_tok(chr(10).join(lines)):,} tok',
            '（全文読みは禁止。下の行番号で lines / find を使うこと）', '']
    for n, (ln, kind, label) in enumerate(hits):
        nxt = hits[n + 1][0] if n + 1 < len(hits) else len(lines) + 1
        span = sum(len(l) + 1 for l in lines[ln - 1:nxt - 1])
        rows.append(f'L{ln:<6} {kind:<8} {label:<70} {nxt - ln:>5}行 {span:>8,}字')
    if not hits:
        rows.append('（見出しが見つからない。grep か lines で当てること）')
    emit(rows)


# ---- 定義を引く ----------------------------------------------------------
def cmd_find(path, name):
    lines = read_lines(path)
    pats = [re.compile(r'\b(?:function|def|class)\s+' + re.escape(name) + r'\b'),
            re.compile(r'\b(?:const|let|var)\s+' + re.escape(name) + r'\s*='),
            re.compile(r'\bid="' + re.escape(name) + r'"')]
    starts = [i for i, l in enumerate(lines) if any(p.search(l) for p in pats)]
    if not starts:
        # 定義が無ければ参照箇所を出す（「無い」と「見つけられない」を区別する）
        refs = [i for i, l in enumerate(lines) if name in l]
        rows = [f'{path}: 「{name}」の定義は見つからない。参照 {len(refs)} 件:']
        rows += [f'L{i+1:<6} {clip(lines[i].strip())}' for i in refs[:40]]
        emit(rows)
        return
    rows = []
    for s in starts:
        end = _block_end(lines, s)
        body = lines[s:end]
        rows.append(f'--- {path} L{s+1}-{end}  {end-s}行 概算 {est_tok(chr(10).join(body)):,} tok ---')
        rows += [f'{s+1+k:<6} {clip(l)}' for k, l in enumerate(body)]
        rows.append('')
    emit(rows)


def _block_end(lines, s, limit=400):
    """波括弧かインデントで区間の終わりを当てる。当てられなければ limit 行で切る。"""
    if '{' in lines[s]:
        depth = 0
        for i in range(s, min(len(lines), s + limit)):
            depth += lines[i].count('{') - lines[i].count('}')
            if depth <= 0 and i > s:
                return i + 1
        return min(len(lines), s + limit)
    ind = len(lines[s]) - len(lines[s].lstrip())
    for i in range(s + 1, min(len(lines), s + limit)):
        if lines[i].strip() and (len(lines[i]) - len(lines[i].lstrip())) <= ind:
            return i
    return min(len(lines), s + limit)


# ---- 行範囲 / 一致行 ------------------------------------------------------
def cmd_lines(path, a, b):
    lines = read_lines(path)
    a, b = max(1, int(a)), min(len(lines), int(b))
    emit([f'{path} L{a}-{b}'] + [f'{i:<6} {clip(lines[i-1])}' for i in range(a, b + 1)])


def cmd_grep(path, pattern):
    lines = read_lines(path)
    rx = re.compile(pattern)
    hits = [(i + 1, l) for i, l in enumerate(lines) if rx.search(l)]
    emit([f'{path}: /{pattern}/ {len(hits)}件'] + [f'L{i:<6} {clip(l)}' for i, l in hits])


# ---- JSON の形だけ --------------------------------------------------------
def cmd_json(path, depth=3):
    size = os.path.getsize(path)
    with open(path, encoding='utf-8') as f:
        obj = json.load(f)
    rows = [f'{path}  {size:,}B（全文なら概算 {size//3:,} tok — 読まないこと）', '']
    rows += _shape(obj, depth)
    rows += ['', '値そのものが要るときは jq で絞る:',
             f"  jq -c '.[0]' {path}   /   jq 'keys' {path}   /   jq '.foo | length' {path}"]
    emit(rows)


def _shape(o, depth, prefix='', ind=0):
    pad = '  ' * ind
    if isinstance(o, dict):
        rows = [f'{pad}{prefix}dict({len(o)}キー)']
        if depth <= 0:
            return rows
        for k in list(o)[:12]:
            rows += _shape(o[k], depth - 1, f'{k}: ', ind + 1)
        if len(o) > 12:
            rows.append(f'{pad}  …他 {len(o)-12} キー')
        return rows
    if isinstance(o, list):
        rows = [f'{pad}{prefix}list({len(o)}件)']
        if o and depth > 0:
            rows += _shape(o[0], depth - 1, '[0] ', ind + 1)
        return rows
    s = repr(o)
    return [f'{pad}{prefix}{type(o).__name__} {s[:60]}']


# ---- 見積り ---------------------------------------------------------------
def cmd_size(paths):
    rows = [f'{"ファイル":<34}{"バイト":>12}{"概算tok":>10}  判定']
    for p in paths:
        try:
            t = open(p, encoding='utf-8', errors='replace').read()
        except (OSError, UnicodeError) as e:
            rows.append(f'{p:<34} 読めない: {e}')
            continue
        tok = est_tok(t)
        mark = '危険・全文読み禁止' if tok > 20000 else ('重い・範囲を絞る' if tok > 6000 else 'そのまま読んでよい')
        rows.append(f'{p:<34}{os.path.getsize(p):>12,}{tok:>10,}  {mark}')
    emit(rows)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    c = argv[1]
    try:
        if c == 'map':    cmd_map(argv[2])
        elif c == 'find': cmd_find(argv[2], argv[3])
        elif c == 'grep': cmd_grep(argv[2], argv[3])
        elif c == 'lines':cmd_lines(argv[2], argv[3], argv[4])
        elif c == 'json': cmd_json(argv[2], int(argv[5]) if len(argv) > 5 else 3)
        elif c == 'size': cmd_size(argv[2:])
        else:
            print(__doc__); return 1
    except IndexError:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
