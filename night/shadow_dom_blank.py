#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_dom_blank.py — **dom 空欄の扱いを変えたら誰がどう動くか**（2026-09-21新設）

★これは影の計測であって規約の変更ではない。`index.html` の ccfMoat に1行だけ足して
  score_all を回し、**必ず元へ戻す**（sha256 で検算）。正本の採点・合否は動かない。

■ なぜ測るか（2026-09-21・ユーザーの問い「空欄を50にするとどうなるの？」）
  dom 空欄は重みを残り4本へ再正規化する＝**その社では「dom＝他4本の加重幾何平均」を置いたのと
  数学的に同一**。BR では暗黙の dom が **74.4** で、規約の刻み 50/70/85/100 のどれでもない。
  ⇒ 「答えない」つもりの空欄が「高めに答える」形になっている（docs/CLAUDE_ARCHIVE.md:15494）。

■ 案
  now   : 現行（空欄は再正規化＝暗黙に他4本の平均）
  d50   : 空欄を **50**（規約の残余の刻み）として採点
  d70   : 空欄を **70**（v9.9.39 以前の SELECT 既定値。比較のための参照）

⚠ **d50 は一律には正しくない**——dom 規約(1)は「**刻みが散るときだけ空欄**」なので、
  空欄には (a)原本にシェア開示が無い (b)事業ごとに刻みが割れる の**2種類**が混在する。
  (b) を 50 に倒すのは「測れなかった」を「競争的だった」と言い換えることになる（ルール7の親戚）。
  この道具は**代償の大きさを数える**ためのもので、案の採否を決めるものではない。

実行: python3 night/shadow_dom_blank.py [--json]
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
H = "index.html"
ANCH = "  const legs=Object.keys(W).map(k=>[k,rung(k,num(d[k]))]).filter(l=>l[1]!=null&&l[1]>0);"
if ANCH not in open(H, encoding="utf-8").read():
    raise SystemExit("錨が見つからない——ccfMoat が変わった。**当てずに止める**")


def patch(v):
    return ("  {const _dm=num(d.dom); if(_dm==null) d=Object.assign({},d,{dom:%d});}\n" % v) + ANCH


CASES = [("now  現行（再正規化＝暗黙に他4本の平均）", None),
         ("d50  空欄を 50 として採点", 50),
         ("d70  空欄を 70 として採点（参照）", 70)]


def run():
    r = subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("score_all が失敗:\n" + r.stderr[-1200:])
    return {x["t"]: x for x in json.load(open("out/score_all.json", encoding="utf-8"))}


def main():
    src = open(H, encoding="utf-8").read()
    sha = lambda: hashlib.sha256(open(H, "rb").read()).hexdigest()
    b4 = sha()
    bak = tempfile.mktemp(suffix=".html")
    shutil.copy(H, bak)
    out = {}
    try:
        for name, v in CASES:
            open(H, "w", encoding="utf-8").write(src if v is None else src.replace(ANCH, patch(v)))
            rows = run()
            out[name] = {
                "buy": sorted([t for t, x in rows.items() if x["buy"]], key=lambda t: -rows[t]["s"]),
                "next": sorted([t for t, x in rows.items() if x["quali"] and not x["buy"]],
                               key=lambda t: -rows[t]["s"]),
                "m70": sum(1 for x in rows.values() if x["moat"] is not None and x["moat"] >= 70),
                "rows": {t: (x["s"], x["moat"]) for t, x in rows.items()},
            }
    finally:
        shutil.copy(bak, H)
        os.remove(bak)
        assert sha() == b4, "★復元に失敗——git checkout index.html せよ"
        subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)

    base = out[CASES[0][0]]
    for name, _ in CASES:
        o = out[name]
        print(f"■ {name}   堀70+ {o['m70']}社")
        print("   🟢", " ".join(f"{t}({o['rows'][t][0]})" for t in o["buy"]))
        print("   🔵", " ".join(f"{t}({o['rows'][t][0]})" for t in o["next"][:6]) or "—")
        if name != CASES[0][0]:
            gone = [t for t in base["buy"] if t not in o["buy"]]
            new = [t for t in o["buy"] if t not in base["buy"]]
            print("   出", " ".join(gone) or "—", " / 入", " ".join(new) or "—")
            mv = sorted(((o["rows"][t][0] - base["rows"][t][0], t) for t in o["rows"]),
                        key=lambda x: x[0])[:6]
            print("   Ωの下げ幅 上位:", " ".join("%s %+.1f" % (t, dd) for dd, t in mv))
        print()
    if "--json" in sys.argv:
        json.dump(out, open("out/shadow_dom_blank.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("→ out/shadow_dom_blank.json")


main()
