#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_gmpt.py — gmPt（priceConfirm の目盛り）を営業利益率基準に直したら誰がどう動くかの影の計測

なぜ要るか:
  gm 欄は 2026-07-20 の全数監査で**営業利益率に統一**された（粗利混入32社を検出した再発防止）。
  ところが pm を作る gmPt の刻みだけが**粗利率の目盛りのまま**残っている:
      現行 gmPt: ≥80%→95 / ≥65%→88 / ≥50%→78 / ≥35%→66 / ≥22%→52 / 未満→40
  同じファイルの他の場所は営業利益率として較正されている:
      F7 収益性 : gmScore = min(100, opm/35*100)  … **35%で満点**
      F9 粘着性 : opm≥30%→+5 / opm<10%→−5
      roicAdj  : opm<15%→+5 / 15-25%→+3 / 25%+→+1
  実測（台帳314社）: 営業利益率の中央値 22.8% / 上位10%でも 42.2% / 最大 73.6%。
  結果 **83%（262社）が gmPt 52点以下**に張り付き、pm=0.70×moatIdx+0.30×gmPt が一律に押し下げられ、
  さらに pm≥70 の柱不足ペナルティの合否線をまたぐ。
  決定的な傍証: pm の式のすぐ上のコメントが今も「粗利は確認材料に降格」と書いてある
  ——欄を営業利益率へ切り替えたときに gmPt の較正だけ直し忘れた痕跡。

やること:
  index.html の gmPt の1行だけを差し替えて `node night/score_all.js` を回し、**必ず元へ戻す**。
  採点式そのものは変更しない（絶対のルール1）。これは「変えたら誰がどう動くか」を出すための計測器。

候補:
  A 現行（粗利率の目盛り）           ≥80/65/50/35/22
  B F7準拠（35%満点に合わせる）      ≥35/28/22/15/8
  C 中間（AとBの間・保守側）          ≥50/40/30/22/15
使い方: python3 night/shadow_gmpt.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
CUR = ("const gmPt=(g,t)=>Math.max(0,Math.min(100,(g>=80?95:g>=65?88:g>=50?78:"
       "g>=35?66:g>=22?52:40)+({up:4,flat:0,down:-12}[t])));")

CANDS = [
    ("A 現行（粗利率の目盛り）", [80, 65, 50, 35, 22]),
    ("B F7準拠（35%満点）", [35, 28, 22, 15, 8]),
    ("C 中間（保守側）", [50, 40, 30, 22, 15]),
]
PTS = [95, 88, 78, 66, 52, 40]


def line_for(th):
    a, b, c, d, e = th
    return ("const gmPt=(g,t)=>Math.max(0,Math.min(100,"
            f"(g>={a}?95:g>={b}?88:g>={c}?78:g>={d}?66:g>={e}?52:40)"
            "+({up:4,flat:0,down:-12}[t])));")


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    return json.load(open("out/score_all.json", encoding="utf-8"))


def main():
    src = open(HTML, encoding="utf-8").read()
    if CUR not in src:
        print("index.html の gmPt が想定と違う。式が変わっているので手で確認すること")
        return 1
    bak = tempfile.mkdtemp(prefix="ccf_html_")
    shutil.copy2(HTML, os.path.join(bak, "index.html"))
    results = {}
    try:
        for label, th in CANDS:
            open(HTML, "w", encoding="utf-8").write(src.replace(CUR, line_for(th)))
            rows = run()
            results[label] = {r["t"]: r for r in rows}
            q75 = [r for r in rows if (r.get("s") or 0) >= 75]
            buy = sorted(r["t"] for r in rows if r.get("buy"))
            print(f"{label:26s} Ω75+ {len(q75):3d}社 / 🟢投下可 {len(buy):2d}社  "
                  f"({' '.join(buy) or 'なし'})")
    finally:
        shutil.copy2(os.path.join(bak, "index.html"), HTML)
        shutil.rmtree(bak, ignore_errors=True)
        run()
        print("\n※index.html と score_all.json は元へ戻した（影の計測であって正本は変えていない）")

    base = results[CANDS[0][0]]
    for label, _ in CANDS[1:]:
        cur = results[label]
        d = [(cur[t]["s"] - base[t]["s"], t) for t in base if t in cur]
        d.sort(reverse=True)
        up = [x for x in d if x[0] > 0.05]
        print(f"\n=== {label} — 現行との差")
        print(f"  Ωが上がる {len(up)}社 / 変わらない {len(d)-len(up)}社 "
              f"/ 中央値の変化 {sorted(x[0] for x in d)[len(d)//2]:+.1f}pt / 最大 {d[0][0]:+.1f}pt")
        print("  上がり幅の大きい順（上位10）:")
        for dl, t in d[:10]:
            print(f"    {t:6s} Ω{base[t]['s']:5.1f} → {cur[t]['s']:5.1f} ({dl:+.1f})"
                  + ("  ← 投下可に入る" if cur[t].get("buy") and not base[t].get("buy") else "")
                  + ("  ← 投下可から外れる" if base[t].get("buy") and not cur[t].get("buy") else ""))
        nb = sorted(t for t in cur if cur[t].get("buy") and not base[t].get("buy"))
        gone = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        print(f"  投下可に入る: {' '.join(nb) or 'なし'} / 外れる: {' '.join(gone) or 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
