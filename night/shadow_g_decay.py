#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_g_decay.py — 門XのE[r]に成長減衰を入れたら誰がどう動くかの影の計測（2026-08-04新設）

なぜ要るか:
  ccfXJudge は g を20年間そのまま置く。v9.9.69 のコメント自身が「終端成長を置くと結論が
  総合9.4〜13.6%と4pt振れるが、**リポジトリにその数字を較正する材料が無い**ので入れない」と
  書いていた。歴史検証（night/retro_growth_persistence.py / retro_cohort.py・2026-08-04）が
  その較正材料を出した:
    - 3y CAGR 20-30%で入った社の前方実現: 5年で中央値8.9% / 10年で7.1% / 経路は+10年以降4-6%
    - **門Xのgrower条件相当（cagr≥15 ∧ roic_med5≥20）の前方10年は 6.6%**
      ——asof=2013(n=62)と2015(n=42)で完全一致。10年後も15%を維持したのは1割
    - 質・規模・FCF転換のどの機械指標でも成長持続は予言できない（2ビンテージで符号すら不安定）

やること:
  index.html の ccfXJudge に「g決定の直後・fairPER計算の直前」の1行を挿して
  `node night/score_all.js` を回し、**必ず元へ戻す**。正本は変えない（絶対のルール6）。

候補（いずれも歴史実測の帯から）:
  A 現行（減衰なし・g最大20%を20年据え置き）
  B 実証5年＋終端6%×15年   g_eff=((1+g)^5×1.06^15)^(1/20)−1  … 実測経路の上側(+5〜10年6-8%)
  C 実証5年＋終端4%×15年   同1.04                              … 実測経路の下側(+10年以降4-5%)
  D 基礎率直置き g=min(g,6.6%)  … grower相当の前方10年実測そのもの（最も厳しい・per-company情報を捨てる）
  ※ B/C は fairPER=8+g_eff にも波及する＝出口の倍率も減衰後の成長で置く（整合的に厳しくなる）

使い方: python3 night/shadow_g_decay.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
ANCHOR = "const fairPER=Math.max(16,Math.min(30,8+g));"

CANDS = [
    ("A 現行(減衰なし)", None),
    ("B 実証5y+終端6%", "g=(Math.pow(Math.pow(1+g/100,5)*Math.pow(1.06,15),1/20)-1)*100;"),
    ("C 実証5y+終端4%", "g=(Math.pow(Math.pow(1+g/100,5)*Math.pow(1.04,15),1/20)-1)*100;"),
    ("D 基礎率6.6%直置き", "g=Math.min(g,6.6);"),
]


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    return json.load(open("out/score_all.json", encoding="utf-8"))


def main():
    src = open(HTML, encoding="utf-8").read()
    if src.count(ANCHOR) != 1:
        print("index.html の fairPER 行が想定と違う（式が変わっている）。手で確認すること")
        return 1
    bak = tempfile.mkdtemp(prefix="ccf_html_")
    shutil.copy2(HTML, os.path.join(bak, "index.html"))
    results = {}
    try:
        for label, ins in CANDS:
            body = src if ins is None else src.replace(ANCHOR, ins + ANCHOR)
            open(HTML, "w", encoding="utf-8").write(body)
            rows = run()
            results[label] = rows
            buy = sorted(r["t"] for r in rows if r.get("buy"))
            ers = sorted([r["xEr"] for r in rows if r.get("buy") and r.get("xEr") is not None])
            wmed = ers[len(ers) // 2] if ers else None
            print(f"{label:20s} 🟢投下可 {len(buy):2d}社 (E[r]中央値 {wmed}) : {' '.join(buy) or 'なし'}")
    finally:
        shutil.copy2(os.path.join(bak, "index.html"), HTML)
        shutil.rmtree(bak, ignore_errors=True)
        run()
        print("\n※index.html と score_all.json は元へ戻した（影の計測であって正本は変えていない）")

    base = {r["t"]: r for r in results[CANDS[0][0]]}
    for label, _ in CANDS[1:]:
        cur = {r["t"]: r for r in results[label]}
        gone = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        stay = sorted(t for t in cur if base[t].get("buy") and cur[t].get("buy"))
        print(f"\n=== {label}")
        print(f"  投下可に残る: {' '.join(stay) or 'なし'}")
        print(f"  外れる: " + " / ".join(
            f"{t}(E[r] {base[t]['xEr']}→{cur[t]['xEr']})" for t in gone) if gone else "  外れる: なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
