#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/check_html.py — index.html の構造検査（2026-07-29新設）

なぜ要るか（実害が出たので作った）:
  v9.9.45 で教義ブロックを書き換えたとき、**`</div>` を1個多く書いた**。
  結果 pg1（Ⅰ解説）が途中で閉じ、**11,993文字・8ブロックがタブの外へ漏れ出して
  どのタブでも表示され続けた**——ユーザーからの報告は「門が壊れてる。タブを変えても同じまま」。

  なぜ既存の検査を素通りしたか:
   ・`new Function(script)` の構文検査は**HTMLの入れ子を見ない**
   ・`node night/score_all.js` は DOM シムが**存在しない要素を自動生成する**ので、
     要素を消してもエラーにならない（ブラウザなら $() が null を返して落ちる）
   ・採点結果は1点も変わらなかった（表示だけが壊れる種類の事故）
  ＝**採点が合っていることは、門が動いていることを意味しない。**

検査項目:
  1. 各タブ（#pg1..#pg8）の <div> と </div> の収支がゼロか
  2. スクリプトが参照する要素ID（$('xxx') / getElementById）が HTML に存在するか
  3. 各 <script> ブロックが構文として通るか
使い方: python3 night/check_html.py   （終了コード1で不合格）
"""
import re
import sys
import os
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"


def main():
    s = open(HTML, encoding="utf-8").read()
    body = s[s.find("<body>"):]
    fails = []

    # --- 1. タブごとの div 収支 ---
    idx = [m.start() for m in re.finditer(r'<div id="pg\d"[^>]*class="pg"', body)]
    if not idx:
        fails.append("タブ（<div id=\"pgN\" class=\"pg\">）が見つからない")
    idx.append(len(body))
    for k in range(len(idx) - 1):
        seg = body[idx[k]:idx[k + 1]]
        nm = re.search(r'id="(pg\d)"', seg).group(1)
        o, c = len(re.findall(r"<div\b", seg)), len(re.findall(r"</div>", seg))
        if o != c:
            fails.append(f"{nm}: <div>{o} / </div>{c} = 収支 {o-c}"
                         f"（マイナスなら**タブが途中で閉じて中身が外へ漏れる**＝"
                         f"どのタブでも同じ内容が残り続ける）")

    # --- 2. スクリプトが参照する要素IDの実在 ---
    scripts = "".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", s))
    ids = set(re.findall(r'id="(\w+)"', s))
    refs = set(re.findall(r"""\$\(['"](\w+)['"]\)""", scripts))
    refs |= set(re.findall(r"""getElementById\(['"](\w+)['"]\)""", scripts))
    # 動的生成される要素はHTMLに無くてよいので、代入側（innerHTML等）に現れるIDは除く
    made = set(re.findall(r"""id=\\?['"](\w+)\\?['"]""", scripts))
    miss = sorted(refs - ids - made)
    if miss:
        fails.append(f"スクリプトが参照するのにHTMLに無いID: {miss}"
                     f"（ブラウザでは $() が null を返して落ちる。"
                     f"score_all.js のDOMシムは自動生成するので検知できない）")

    # --- 3. スクリプトの構文 ---
    js = ("const fs=require('fs');const s=fs.readFileSync('index.html','utf8');let n=0;"
          "for(const b of (s.match(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)||[])){"
          "const c=b.replace(/^<script[^>]*>/,'').replace(/<\\/script>$/,'');"
          "try{new Function(c);}catch(e){n++;console.log('SyntaxError: '+e.message.slice(0,120));}}"
          "process.exit(n?1:0);")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    if r.returncode:
        fails.append("スクリプトの構文エラー: " + r.stdout.strip()[:200])

    if fails:
        print("✗ index.html の構造検査に不合格")
        for f in fails:
            print("    FAIL " + f)
        print("\n※採点が合っていることは、門が動いていることを意味しない。"
              "表示だけが壊れる事故はここでしか捕まらない")
        return 1
    print("✓ index.html 構造検査: タブのdiv収支・参照IDの実在・スクリプト構文 すべて通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
