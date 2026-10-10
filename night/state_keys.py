#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/state_keys.py — state.json に入れてよい「人の決定」のキーの一覧を **state.js から読む**（v9.9.210・2026-10-10）

■ なぜ state.js から読むのか
  キーの集合は state.js が正本（`var EXACT = [...]`・`var PREFIX = [...]`・`var DERIVED_KEY = {...}`）。
  validate_state.py は「state.js と同じ集合（片方だけ増やすと静かに割れる）」と頭注に書きながら**手で写していた**ので、
  state.js が pf:net / pf:monthly_total / pf:monthly_net を足した（v9.9.160〜168）ときに写し忘れ、
  **それらを含む state.json を入れると CI が「想定外のキー」で落ちる**状態だった（実測: state.js 8個 / validate_state 5個）。
  新しい経路（Issue → Action が state.json を更新する・night/apply_state_issue.py）はこの3つを含むキーを書くので、
  写しを持たず**同じ場所から読む**（audit_moat_gap が index.html の `const W` を読むのと同じ作法・v9.9.65）。

読めなかったとき（state.js の書き方が変わった）は**例外を投げる**——静かに古い一覧へ倒れない。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_JS = os.path.join(ROOT, "state.js")


def _src():
    with open(STATE_JS, encoding="utf-8") as f:
        return f.read()


def _strings(block):
    return re.findall(r"'([^']+)'", block)


def exact_keys(src=None):
    """決定の正確なキー（`var EXACT = [...]`）"""
    src = src if src is not None else _src()
    m = re.search(r"var\s+EXACT\s*=\s*\[(.*?)\]\s*;", src, re.S)
    if not m:
        raise RuntimeError("state.js に `var EXACT = [...]` が見つからない（書き方が変わった？）")
    ks = _strings(m.group(1))
    if not ks:
        raise RuntimeError("state.js の EXACT が空に読めた")
    return ks


def prefixes(src=None):
    """前方一致のキー（`var PREFIX = [...]`・検証履歴 g7log: など）"""
    src = src if src is not None else _src()
    m = re.search(r"var\s+PREFIX\s*=\s*\[(.*?)\]\s*;", src, re.S)
    if not m:
        raise RuntimeError("state.js に `var PREFIX = [...]` が見つからない")
    return _strings(m.group(1))


def derived_keys(src=None):
    """機械しか書かないキー（`var DERIVED_KEY = {...}`・人の決定ではない）"""
    src = src if src is not None else _src()
    m = re.search(r"var\s+DERIVED_KEY\s*=\s*\{(.*?)\}\s*;", src, re.S)
    if not m:
        raise RuntimeError("state.js に `var DERIVED_KEY = {...}` が見つからない")
    return _strings(m.group(1))


def human_keys(src=None):
    """人の決定（EXACT のうち機械しか書かないものを除く）"""
    d = set(derived_keys(src))
    return [k for k in exact_keys(src) if k not in d]


# 値が JSON でなく**数字の文字列**で入るキー（今月の入金額など）。state.js にこの区別は無いので、ここが正本。
PLAIN_NUMBER_KEYS = ("pf:monthly_total", "pf:monthly", "pf:monthly_net")


if __name__ == "__main__":
    import json
    print(json.dumps({"exact": exact_keys(), "prefix": prefixes(), "derived": derived_keys(), "human": human_keys()},
                     ensure_ascii=False, indent=1))
