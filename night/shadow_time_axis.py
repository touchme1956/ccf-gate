#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_time_axis.py — 「時間軸の欄が薄い／レバレッジが実質無点」を直したら誰がどう動くかの影の計測

なぜ要るか（2026-08-03の実測）:
  node night/audit_weights.js --q75 で判定帯の実効ウェイトを測ると——
    単年の roic ................ 38.2%
    p1(ROIC5年の変動係数) ....... 3.7%
    p2(不況時の営利DD) .......... 4.8%
    f1(ROIIC＝次の1ドル) ........ 3.3%
    f5(disrupt連動) ............ 0.9%   → 時間を通して見る欄の合計 **12.7%**
    nde(0.5倍→2.5倍) ........... -0.3%  ＝ レバレッジ5倍差でΩ0.4pt
  さらに `sustain`（.30・名前は「持つか」）の中身は gm([pm, pr]) ＝ **堀の柱とROIC柱の現在値だけ**で、
  持続性の測定を一つも含まない。つまり門は「**今の水準が高ければ20年続く**」という仮説に30%を賭けている。
  20-30年の複利を狙う門としてこの配分が妥当かは、重みを振って「誰がどう動くか」を見ないと決められない。

  カバー率は先に確認済み（死因A/Bの切り分け）: Ω75+の30社で p1/p2/f1 とも **入力100%**。
  ＝データの穴ではなく重みの問題なので、重みを振れば実際に効く。

やること:
  index.html の**1行だけ**を差し替えて `node night/score_all.js` を回し、**必ず元へ戻す**。
  採点式そのものは変更しない（絶対のルール1）。これは計測器であって改定ではない。

軸1 Q内の P(持続の質) : now(現在の収益力)
  現行 [.5333,.4667]。Pを厚くすると p1/p2/p3/p4 が同時に持ち上がる＝①時間軸と②レバレッジの両方に効く。
軸2 P内の p1(ROIC安定性)・p2(不況DD) の比率
  現行 [.30,.25,.25,.20]（p1/p2/p3/p4）。時間軸だけを厚くしたい場合はこちら。

使い方: python3 night/shadow_time_axis.py
"""
import json, os, re, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"

Q_CUR = "let Q=gm([P,now],[.5333,.4667]);"
P_CUR = "const P=gm([p1eff,n('p2'),p3v,Math.max(0,p4eff)],[.30,.25,.25,.20]);"

CANDS = [
    ("現行", Q_CUR, P_CUR),
    ("D1 Q内 P:now = .60/.40", "let Q=gm([P,now],[.60,.40]);", P_CUR),
    ("D2 Q内 P:now = .65/.35", "let Q=gm([P,now],[.65,.35]);", P_CUR),
    ("D3 Q内 P:now = .70/.30", "let Q=gm([P,now],[.70,.30]);", P_CUR),
    ("E1 P内 p1/p2を厚く .35/.30/.20/.15", Q_CUR,
     "const P=gm([p1eff,n('p2'),p3v,Math.max(0,p4eff)],[.35,.30,.20,.15]);"),
    ("E2 P内 p3(財務)を厚く .25/.25/.35/.15", Q_CUR,
     "const P=gm([p1eff,n('p2'),p3v,Math.max(0,p4eff)],[.25,.25,.35,.15]);"),
    ("F1 D2+E1 併用", "let Q=gm([P,now],[.65,.35]);",
     "const P=gm([p1eff,n('p2'),p3v,Math.max(0,p4eff)],[.35,.30,.20,.15]);"),
]


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    d = json.load(open("out/score_all.json", encoding="utf-8"))
    return d["rows"] if isinstance(d, dict) else d


def main():
    src = open(HTML, encoding="utf-8").read()
    for cur in (Q_CUR, P_CUR):
        if src.count(cur) != 1:
            print(f"index.html の式が想定と違う（{src.count(cur)}件）: {cur[:50]}")
            return 1
    bak = tempfile.mkdtemp(prefix="ccf_html_")
    shutil.copy2(HTML, os.path.join(bak, "index.html"))
    res = {}
    try:
        for label, q, p in CANDS:
            open(HTML, "w", encoding="utf-8").write(src.replace(Q_CUR, q).replace(P_CUR, p))
            rows = run()
            res[label] = {r["t"]: r for r in rows}
            buy = sorted(r["t"] for r in rows if r.get("buy"))
            q75 = [r for r in rows if (r.get("s") or 0) >= 75]
            print(f"{label:34s} Ω75+ {len(q75):3d}社 / 🟢投下可 {len(buy):2d}社  {' '.join(buy) or 'なし'}")
    finally:
        shutil.copy2(os.path.join(bak, "index.html"), HTML)
        shutil.rmtree(bak, ignore_errors=True)
        run()
        print("\n※index.html と score_all.json は元へ戻した（影の計測であって正本は変えていない）")

    base = res["現行"]
    for label, _, _ in CANDS[1:]:
        cur = res[label]
        d = sorted(((cur[t]["s"] - base[t]["s"], t) for t in base if t in cur), reverse=True)
        mid = sorted(x[0] for x in d)[len(d) // 2]
        nb = sorted(t for t in cur if cur[t].get("buy") and not base[t].get("buy"))
        gone = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        print(f"\n=== {label}")
        print(f"  Ωの変化: 中央値 {mid:+.2f}pt / 最大 {d[0][0]:+.1f}pt ({d[0][1]}) / 最小 {d[-1][0]:+.1f}pt ({d[-1][1]})")
        print(f"  投下可に入る: {' '.join(nb) or 'なし'} / 外れる: {' '.join(gone) or 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
