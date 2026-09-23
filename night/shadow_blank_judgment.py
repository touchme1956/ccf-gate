#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_blank_judgment.py — 空欄の判断項目（p1/p2/p4/f1/f3/f4）を「0」ではなく「再正規化」で扱ったら
誰がどう動くかの影の計測（2026-09-23新設・todo gate_blank_p1_zero）。

■ なぜ要るか
  判断項目は数値の入力欄で、パックの null は空文字として入る → compute() の n(id) は parseFloat('')||0 ＝ **0**。
  幾何平均 gm() は max(x,1) なので、空欄は「1点」として効き、その重みぶん P / F を大きく削る
  （p1 の重み .30 なら P は約 1/4 に）。審査プロトコルは「系列3年未満なら p1 は空欄に」と指示しているので、
  **指示どおりに空欄にすると罰になる**。dom / moatW は空欄を残りの本数へ**再正規化**する（v9.9.39）——
  同じ作法を判断項目に当てたら誰が動くかを出す。

■ ⚠ 採点式は変えない（絶対のルール1）
  リポジトリの**一時コピー**の中で index.html の2か所（F の gm と P の gm）だけを差し替えて
  score_all を回す。**正本の index.html には一切触れない**——他のセッションが同時に score_all を
  回していても、差し替えた門を読ませない（旧来の shadow_* は正本を書き換えて戻す型で、同時実行に弱かった）。

使い方: python3 night/shadow_blank_judgment.py [--json]   （--json で out/shadow_blank_judgment.json）
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

F_OLD = ("  const F=(()=>{\n    let f=gm(\n      [n('f1'),F6, F11, f2eff,F9,F7,n('f3'),F10,F8,n('f4'),f5v],\n"
         "      [.14,   .12,.09, .06,  .09,.13,.09,   .12,.08,.04,   .04]\n    );")
F_NEW = ("  const _bk=id=>{const el=$(id);return !el||el.value===''||el.value==null;};\n"
         "  const _gmN=(v,w,skip)=>{const vv=[],ww=[];let S=0,T=0;w.forEach(x=>T+=x);"
         "v.forEach((x,i)=>{if(!skip[i]){vv.push(x);ww.push(w[i]);S+=w[i];}});"
         "return S>0?gm(vv,ww.map(x=>x*T/S)):gm(v,w);};\n"
         "  const F=(()=>{\n    let f=_gmN(\n      [n('f1'),F6, F11, f2eff,F9,F7,n('f3'),F10,F8,n('f4'),f5v],\n"
         "      [.14,   .12,.09, .06,  .09,.13,.09,   .12,.08,.04,   .04],\n"
         "      [_bk('f1'),false,false,false,false,false,_bk('f3'),false,false,_bk('f4'),false]\n    );")
P_OLD = ("  let p1eff=n('p1');\n  if(n('gm')>25 && roic>=20 && p1eff<75) p1eff=(p1eff+75)/2;\n"
         "  const P=gm([p1eff,n('p2'),p3v,Math.max(0,p4eff)],[.30,.25,.25,.20]);")
P_NEW = ("  let p1eff=n('p1');\n  if(!_bk('p1') && n('gm')>25 && roic>=20 && p1eff<75) p1eff=(p1eff+75)/2;\n"
         "  const P=_gmN([p1eff,n('p2'),p3v,Math.max(0,p4eff)],[.30,.25,.25,.20],"
         "[_bk('p1'),_bk('p2'),false,_bk('p4')]);")


def copy_repo(dst):
    def filt(ti):
        n = ti.name
        if n.startswith("./.git") or n == "./companyfacts.zip" or "/_" in n and "cache" in n:
            return None
        return ti
    tmp = os.path.join(dst, "x.tar")
    with tarfile.open(tmp, "w") as t:
        t.add(".", filter=filt)
    with tarfile.open(tmp) as t:
        t.extractall(os.path.join(dst, "repo"))
    os.remove(tmp)
    return os.path.join(dst, "repo")


def score(root):
    subprocess.run(["node", "night/score_all.js"], cwd=root, check=True, capture_output=True, text=True)
    return {r["t"]: r for r in json.load(open(os.path.join(root, "out", "score_all.json"), encoding="utf-8"))}


def main():
    os.chdir(BASE)
    with tempfile.TemporaryDirectory() as td:
        root = copy_repo(td)
        base = score(root)
        p = os.path.join(root, "index.html")
        s = open(p, encoding="utf-8").read()
        if s.count(F_OLD) != 1 or s.count(P_OLD) != 1:
            print("⚠ 錨が index.html と一致しない（F:%d / P:%d）——門の式が変わった。錨を現行へ直してから回すこと"
                  % (s.count(F_OLD), s.count(P_OLD)))
            return 1
        open(p, "w", encoding="utf-8").write(s.replace(F_OLD, F_NEW, 1).replace(P_OLD, P_NEW, 1))
        alt = score(root)
    rows = []
    for t in base:
        if t not in alt:
            continue
        a, b = float(base[t]["s"]), float(alt[t]["s"])
        if abs(a - b) > 0.05:
            rows.append({"t": t, "base": a, "renorm": b, "d": round(b - a, 1)})
    rows.sort(key=lambda r: -r["d"])
    buy_a = sorted(t for t in base if base[t].get("buy"))
    buy_b = sorted(t for t in alt if alt[t].get("buy"))
    cross = [r for r in rows if (r["base"] < 72) != (r["renorm"] < 72) or (r["base"] < 75) != (r["renorm"] < 75)]
    print("■ 空欄の判断項目を再正規化したら（影の計測・正本は不変）")
    print(f"  Ωが動く社 {len(rows)}（上がる {sum(1 for r in rows if r['d'] > 0)} / 下がる {sum(1 for r in rows if r['d'] < 0)}）")
    for r in rows[:30]:
        print(f"   {r['t']:6} {r['base']:5.1f} → {r['renorm']:5.1f}  ({r['d']:+.1f})")
    print(f"  投下可: 現行 {buy_a} ／ 再正規化 {buy_b}" + ("（不変）" if buy_a == buy_b else "（★変わる）"))
    print(f"  判定圏(72)・Ω75 の線をまたぐ社: {[(r['t'], r['base'], r['renorm']) for r in cross]}")
    if "--json" in sys.argv:
        json.dump({"generated": __import__("datetime").date.today().isoformat(),
                   "note": "空欄の p1/p2/p4/f1/f3/f4 を 0（max(x,1)=1点）ではなく残りの重みへ再正規化した影の計測。正本の採点は不変",
                   "rows": rows, "buy_base": buy_a, "buy_renorm": buy_b, "cross": cross},
                  open(os.path.join(BASE, "out", "shadow_blank_judgment.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("→ out/shadow_blank_judgment.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
