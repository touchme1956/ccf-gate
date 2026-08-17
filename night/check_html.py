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
  4. **外部スクリプト（<script src=...>）が実在し・構文が通り・呼ばれている ccf* を定義しているか**
     （2026-08-17新設。icon.js を新設して ccfIcon を両ページの外へ出したので、
       **ファイルが欠けると全銘柄の行が描けなくなる**——inline のときには有り得なかった壊れ方。
       state.js も同じ危険を負っていたが検査が無かった。index.html と portfolio.html の両方を見る）
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

    # --- 4. 外部スクリプトの実在・構文・ccf* の解決（両ページ） ---
    #   inline を外へ出した瞬間に「ファイルが無ければ全行が描けない」という壊れ方が生まれる。
    #   呼んでいる ccf*() が inline にも外部にも無ければ、それは**その形の事故**そのもの。
    for page in ("index.html", "portfolio.html"):
        if not os.path.exists(page):
            continue
        ps = open(page, encoding="utf-8").read()
        srcs = re.findall(r'<script[^>]*\bsrc="([^"]+)"', ps)
        pool = "".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", ps))
        for src in srcs:
            if not os.path.exists(src):
                fails.append(f"{page}: <script src=\"{src}\"> が実在しない"
                             f"（読み込めないと、その中の関数を呼ぶ行が全部描けない）")
                continue
            r = subprocess.run(["node", "--check", src], capture_output=True, text=True)
            if r.returncode:
                fails.append(f"{src}: 構文エラー {(r.stderr or r.stdout).strip()[:160]}")
            pool += "\n" + open(src, encoding="utf-8").read()
        defined = set(re.findall(r"function\s+(ccf\w+)", pool)) | \
            set(re.findall(r"(?:const|let|var)\s+(ccf\w+)\s*=", pool)) | \
            set(re.findall(r"window\.(ccf\w+)\s*=", pool))
        # 呼び出しだけを拾う（`obj.ccfFoo(` のようなメンバ呼び出しは別物なので除く）
        called = set(re.findall(r"(?<![.\w])(ccf\w+)\s*\(", pool))
        miss = sorted(called - defined)
        if miss:
            fails.append(f"{page}: 呼ばれているのにどこにも定義が無い関数 {miss}"
                         f"（外部スクリプトの取りこぼし＝ブラウザで初めて落ちる）")

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
