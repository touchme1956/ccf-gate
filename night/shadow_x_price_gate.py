#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_x_price_gate.py — 門Xを「非法外な倍率」型に替えたら誰がどう動くかの影の計測（2026-08-04新設）

なぜ要るか:
  歴史検証（2026-08-04・PR#105）の実測:
    - 勝者(13年で年率15%+)24社の買値はPER中央値22.2・PER15未満は6社だけ
      ＝**深い押し目を待つと勝者の3/4を逃す**
    - 3割高づかみの20年コストは年−1.3%、買い逃しのコストは年−19%（MAの枠）＝非対称
    - ただし質があってもPER30超は年7.3%に沈む＝**法外な倍率だけは避ける線が要る**
    - 価格は勝敗(恒久毀損)を分けない（敗者の買値PER24.2≒勝者22.2）＝守りは堀の審査
  この実測が示唆する設計は「E[r]の精密計算より、堀の確度＋非法外な倍率で早く入り20年持つ」。
  それを門の実データで測るのが本スクリプト。**採用はルール6（ユーザー明示指示）の領分**。

やること:
  ccfXJudge の xPass 行だけを差し替えて node night/score_all.js を回し、**必ず元へ戻す**。
  三関門のうち他の二つ（Ω75+・堀70+）と点検はそのまま＝堀のふるいは全変種で共通。

変種:
  A 現行:  E[r]≥12 ∧ earned≥10 ∧ 倍率寄与≤30% ∧ ストレス≥7
  B PER≤20（歴史で最も効いた線: 質∧PER≤20 → 11.2%/年）
  C PER≤25（勝者の中央値22.2のすぐ上）
  D PER≤30（法外の線ぎりぎり。30超は7.3%/年に沈む側）
  E PER≤30 ∧ earned≥10（非法外＋「倍率の助け無しで10%」の現行条件を残す折衷）

使い方: python3 night/shadow_x_price_gate.py

⚠ **錨は現行の門に存在しない**——v9.9.84（遮断器化） で該当行が変わったため、この道具は当時の設計を測る
  記録用であって今日の門には当たらない（実行すると錨が見つからない旨で止まる）。
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
ANCHOR = "out.xPass=(xEr>=12)&&(earned>=10)&&(mult<=0||mshare<=30)&&(erS>=7);"

CANDS = [
    ("A 現行(E[r]式4条件)", None),
    ("B PER≤20", "out.xPass=(per>0&&per<=20);"),
    ("C PER≤25", "out.xPass=(per>0&&per<=25);"),
    ("D PER≤30", "out.xPass=(per>0&&per<=30);"),
    ("E PER≤30∧earned≥10", "out.xPass=(per>0&&per<=30&&earned>=10);"),
]


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    return json.load(open("out/score_all.json", encoding="utf-8"))


def main():
    src = open(HTML, encoding="utf-8").read()
    if src.count(ANCHOR) != 1:
        print("index.html の xPass 行が想定と違う（式が変わっている）。手で確認すること")
        return 1
    bak = tempfile.mkdtemp(prefix="ccf_html_")
    shutil.copy2(HTML, os.path.join(bak, "index.html"))
    results = {}
    try:
        for label, repl in CANDS:
            body = src if repl is None else src.replace(ANCHOR, repl)
            open(HTML, "w", encoding="utf-8").write(body)
            rows = run()
            results[label] = {r["t"]: r for r in rows}
            buy = sorted(r["t"] for r in rows if r.get("buy"))
            print(f"{label:22s} 🟢投下可 {len(buy):2d}社 : {' '.join(buy) or 'なし'}")
    finally:
        shutil.copy2(os.path.join(bak, "index.html"), HTML)
        shutil.rmtree(bak, ignore_errors=True)
        run()
        print("\n※index.html と score_all.json は元へ戻した（影の計測であって正本は変えていない）")

    base = results[CANDS[0][0]]
    for label, _ in CANDS[1:]:
        cur = results[label]
        inn = sorted(t for t in cur if cur[t].get("buy") and not base[t].get("buy"))
        out_ = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        print(f"\n=== {label}")
        print("  入る: " + (" / ".join(
            f"{t}(E[r]{base[t].get('xEr')})" for t in inn) or "なし"))
        print("  外れる: " + (" / ".join(
            f"{t}(E[r]{base[t].get('xEr')})" for t in out_) or "なし"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
