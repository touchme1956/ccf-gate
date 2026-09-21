#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctx_guard.py — 1回の道具呼び出しが文脈の窓を食い潰すのを止める PreToolUse フック。

【なぜ要るか（2026-09-21 実測）】
autocompact が空回りしていた（compact 直後3ターンで窓が満杯・3回連続）。原因は会話の長さではなく
**1回の読みが大きすぎる**こと——
  index.html を Read の既定(2000行) で開く ＝ 概算 81,800 tok（窓のおよそ4割）
  index.html 全文                          ＝ 概算 288,715 tok（窓に入らない）
  out/hist10_angleC.json                   ＝ 概算 2,772,000 tok
CLAUDE.md の床が 32,000 tok あるので、既定 Read を2回やれば compact 直後でも窓は埋まる。

【何をするか】Read と Bash の「全文ぶちまけ」だけを止め、代わりの叩き方を名指しで返す。
判定に使うのはファイルの大きさだけ＝**中身も作業内容も見ない**。止めるのは読みだけで、
書き込み・実行・採点・パイプラインには一切触れない（絶対のルール1の領分に入らない）。

【逃げ道】CCF_CTX_GUARD=off で無効。本当に全文が要るなら `limit` を明示して刻むこと。
"""
import json, os, re, shlex, sys

LIMIT_TOK = 25_000          # 1回の読みの上限（窓のおよそ1/8）
PEEK = 'python3 night/peek.py'


def est_tok(s: str) -> int:
    a = sum(1 for c in s if ord(c) < 128)
    return int(a / 3.8 + (len(s) - a) * 0.95)


def file_tok(path, offset=None, limit=None):
    """その読みで実際に入る量を見積もる。offset/limit を指定した読みは、その範囲だけ数える。"""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.read().split('\n')
    except (OSError, UnicodeError):
        return None, 0
    n = len(lines)
    a = max(0, (offset or 1) - 1)
    b = n if limit is None else min(n, a + int(limit))
    if limit is None:                       # Read の既定は先頭2000行
        b = min(n, a + 2000)
    return est_tok('\n'.join(lines[a:b])), n


def deny(msg):
    sys.stderr.write(msg)
    sys.exit(2)                             # 2 = 呼び出しを止めて、この文面をモデルへ返す


def howto(path, nlines, tok):
    return (f'\n⛔ 文脈ガード: {path} をこの読み方で開くと概算 {tok:,} tok 入る'
            f'（{nlines:,}行・上限 {LIMIT_TOK:,} tok）。autocompact の空回りはこれが原因。\n'
            f'代わりに:\n'
            f'  {PEEK} map   {path}              # まず目次（行番号と区間の大きさ）\n'
            f'  {PEEK} find  {path} <名前>        # 関数・id の定義区間だけ\n'
            f'  {PEEK} grep  {path} <正規表現>     # 一致行だけ（長い行は切る）\n'
            f'  {PEEK} lines {path} <開始> <終了>  # 行範囲だけ\n'
            f'  sed -n "1200,1260p" {path}        # 同じことを sed でも可\n'
            f'JSON なら {PEEK} json {path} で形だけ見て、値は jq で絞る。\n'
            f'どうしても連続で読むなら Read に offset/limit を付けて 400行ずつに刻むこと。\n')


DUMP = re.compile(r'^\s*(sudo\s+)?(cat|bat|less|more|nl|od|xxd|strings|pr|fold)\b')
HEADTAIL = re.compile(r'^\s*(sudo\s+)?(head|tail)\b')
BOUNDED = re.compile(r'\|\s*(head|tail|wc|grep|rg|jq|sed|awk|cut|sort|uniq|python3?|node|tee|md5sum|sha\d+sum)\b|>\s*\S')


def check_bash(cmd):
    # パイプやリダイレクトで出力が絞られている＝窓には入らないので触らない
    for seg in re.split(r'&&|\|\||;', cmd):
        if BOUNDED.search(seg):
            continue
        if HEADTAIL.match(seg):
            m = re.search(r'-n\s*(\d+)', seg)
            if m and int(m.group(1)) <= 500:
                continue
        elif not DUMP.match(seg):
            continue
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        for w in words[1:]:
            if w.startswith('-') or not os.path.isfile(w):
                continue
            tok, n = file_tok(w, None, 10 ** 9)      # 全文が入る前提で数える
            if tok and tok > LIMIT_TOK:
                deny(howto(w, n, tok))


def main():
    if os.environ.get('CCF_CTX_GUARD', '').lower() in ('off', '0', 'false'):
        return
    try:
        ev = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    tool, inp = ev.get('tool_name', ''), ev.get('tool_input', {}) or {}
    if tool == 'Read':
        p = inp.get('file_path')
        if not p or not os.path.isfile(p):
            return
        tok, n = file_tok(p, inp.get('offset'), inp.get('limit'))
        if tok and tok > LIMIT_TOK:
            deny(howto(p, n, tok))
    elif tool == 'Bash':
        check_bash(inp.get('command', '') or '')


if __name__ == '__main__':
    main()
