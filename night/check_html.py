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
  1. 各タブ（#pg1..#pg12・既定タブ含む）の <div> と </div> の収支がゼロか
  2. スクリプトが参照する要素ID（$('xxx') / getElementById）が HTML に存在するか
  3. 各 <script> ブロックが構文として通るか
  4. **外部スクリプト（<script src=...>）が実在し・構文が通り・呼ばれている ccf* を定義しているか**
     （2026-08-17新設。icon.js を新設して ccfIcon を両ページの外へ出したので、
       **ファイルが欠けると全銘柄の行が描けなくなる**——inline のときには有り得なかった壊れ方。
       state.js も同じ危険を負っていたが検査が無かった。index.html と portfolio.html の両方を見る）
  5. **on… が「呼び出し」か**（2026-08-23新設・2026-08-24に対象と綴りを拡張）。onclick="save" は
     関数を評価するだけで押しても何も起きない。例外も出ないので pageerror にも現れない＝
     **一番静かな壊れ方**。index.html だけでなく portfolio.html・ami.html も見る
  6. **章のチップの data-g と JS の CCF_GROUP が一致しているか**（2026-08-24新設）。
     二箇所が同じ「どのタブがどの群か」を持つので、片方だけ直すと
     **チップは群Aに並ぶのに押すと群Bへ飛ぶ**（v9.9.65の破れ）
使い方: python3 night/check_html.py   （終了コード1で不合格）
"""
import re
import sys
import os
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
# ★検査5(ハンドラの呼び出し)を当てる先。**index.html だけを見ていて他を見ていなかった**ので広げた。
#   on* を実際に持つのはこの3枚（chomirai/saiten/v10 は0個）だが、増えても落ちないよう存在検査つきで回す。
PAGES = ("index.html", "portfolio.html", "ami.html", "chomirai.html", "saiten.html", "v10.html")


def main():
    s = open(HTML, encoding="utf-8").read()
    body = s[s.find("<body>"):]
    fails = []

    # --- 1. タブごとの div 収支 ---
    # ⚠ 旧実装は r'pg\d"' + class="pg" 完全一致だったので **pg10/11/12 と既定タブ(class="pg on")を
    #    一つも検査していなかった**（2026-08-23 に発見）。2桁と class の前方一致を許す。
    idx = [m.start() for m in re.finditer(r'<div id="pg\d+"[^>]*class="pg\b', body)]
    if not idx:
        fails.append("タブ（<div id=\"pgN\" class=\"pg\">）が見つからない")
    # 最後のタブは本文の <script> の手前で切る（JS の文字列に入った <div> の断片を静的HTMLとして数えない）
    tail = body.find("<script", idx[-1]) if idx else -1
    idx.append(tail if tail > 0 else len(body))
    for k in range(len(idx) - 1):
        seg = body[idx[k]:idx[k + 1]]
        nm = re.search(r'id="(pg\d+)"', seg).group(1)
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
        # ?v= はキャッシュ破り（GitHub Pages の max-age=600 対策）＝ファイル名ではないので外して見る
        srcs = [x.split("?")[0] for x in re.findall(r'<script[^>]*\bsrc="([^"]+)"', ps)]
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

    # --- 5. onclick が「呼び出し」になっているか（2026-08-23新設・2026-08-24 拡張） ---
    #  v9.9.134 の一括整形が onclick から () を「無駄な表記」として削り、
    #  **この銘柄を記録 / 全件書き出し / 依頼文を作る など11個のボタンが12日間 死んでいた**。
    #  onclick="save" は関数を*評価するだけ*で呼ばない——押しても何も起きず、
    #  例外も出ないので pageerror にも出ない。**副作用の無い経路は失敗しても静か**。
    #  既存の検査4は「その関数が存在するか」しか見ないので、これを素通りしていた。
    #  ★2026-08-24 拡張（新設時の網が狭すぎた）:
    #    (a) **index.html しか見ていなかった**——同じ一括整形は portfolio.html(29個) と
    #        ami.html(6個) にも当たりうるのに、そこは一度も検査していなかった
    #    (b) **click/change/input の3つ・二重引用符のみ**だった。onsubmit/onkeyup/onblur…や
    #        単引用符、`= ` の空白は素通りする＝同じ壊れ方が別の綴りで戻ってくる
    EVT = ("click|change|input|submit|keyup|keydown|keypress|blur|focus|"
           "mouseover|mouseout|mousedown|mouseup|dblclick|toggle|load|error")
    DEADPAT = re.compile(r'\bon(?:%s)\s*=\s*(["\'])\s*'
                         r'([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*\1' % EVT)
    for page in PAGES:
        if not os.path.exists(page):
            continue
        dead = sorted({m.group(2) for m in DEADPAT.finditer(open(page, encoding="utf-8").read())})
        if dead:
            fails.append(f"{page}: 押しても何も起きないハンドラ（() が無い＝関数を評価するだけ）: "
                         + ", ".join(dead) + '  → on…="fn()" にする')

    # --- 6. 章のチップの data-g と CCF_GROUP が食い違っていないか（2026-08-24新設） ---
    #  v9.9.171 でタブを6群へ畳んだとき、**同じ「どのタブがどの群か」を二箇所が持った**——
    #  HTML の `data-g`（章の帯にどう並べるか）と JS の `CCF_GROUP`（showPage が群をどう開くか）。
    #  片方だけ直すと、**チップは群Aに並ぶのに押すと群Bへ飛ぶ**（v9.9.65の破れ）。
    #  採点は1点も動かないので、この種の食い違いはここでしか捕まらない。
    dg = {int(a): int(b) for a, b in re.findall(r'id="tab(\d+)"[^>]*data-g="(\d+)"', s)}
    mg = re.search(r'const\s+CCF_GROUP\s*=\s*\{([^}]*)\}', s)
    if not dg:
        fails.append("章のチップに data-g が1つも無い（章の帯が組めない）")
    elif not mg:
        fails.append("CCF_GROUP の定義が見つからない（showPage が群を開けない）")
    else:
        js = {int(a): int(b) for a, b in re.findall(r'(\d+)\s*:\s*(\d+)', mg.group(1))}
        bad = sorted(set(dg) ^ set(js)) or [k for k in sorted(dg) if dg[k] != js.get(k)]
        if bad:
            fails.append("data-g と CCF_GROUP が食い違う tab: "
                         + ", ".join(f"tab{k}(HTML {dg.get(k, '無')} / JS {js.get(k, '無')})" for k in bad))
        mh = re.search(r'const\s+CCF_GROUP_HEAD\s*=\s*\{([^}]*)\}', s)
        if mh:
            head = {int(a): int(b) for a, b in re.findall(r'(\d+)\s*:\s*(\d+)', mh.group(1))}
            hb = [g for g, pg in sorted(head.items()) if js.get(pg) != g]
            if hb:
                fails.append("CCF_GROUP_HEAD の既定ページが自分の群に属していない: "
                             + ", ".join(f"群{g}→pg{head[g]}(その群は {js.get(head[g], '無')})" for g in hb))

    if fails:
        print("✗ 門のHTML構造検査に不合格")
        for f in fails:
            print("    FAIL " + f)
        print("\n※採点が合っていることは、門が動いていることを意味しない。"
              "表示だけが壊れる事故はここでしか捕まらない")
        return 1
    print("✓ 門のHTML構造検査: タブのdiv収支・参照IDの実在・スクリプト構文・外部スクリプト・"
          "ハンドラの呼び出し(index/portfolio/ami)・章と群の対応 すべて通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
