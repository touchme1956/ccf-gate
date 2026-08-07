#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_x_moat_exception.py — 遮断器(E[r]≥0)を堀の実証で緩めたら誰がどう動くかの影の計測（2026-08-06新設）

なぜ要るか（今日の実測が作った矛盾）:
  ・2026-08-04に門Xを遮断器方式(E[r]≥0)へ緩めた根拠は「価格の線は質の中で選別力を持たない」（歴史検証）。
  ・ところが 2026-08-06 に irr=85 の追試が**両ビンテージで合格**（2013 n=6 P=0.667／2015 n=13 P=0.538）した結果、
    **その機構が実証された最上位の2社が、価格だけで止まっている**ことが分かった:
      CW   Ω77.9 堀87.8(台帳最高) 機構3ビンテージ確認 → E[r]−4.6%（PER59.2）で不通過
      VRSK Ω80.7 堀85.3 機構実証   → E[r]−0.9%（PER28.8）で不通過
  ・歴史でirr=85の買値PERが取れた7件では **PER25以上が2/2継続(中央+29.2%)・25未満が2/5(中央+10.1%)**、
    唯一の全損CMTLは**PER21.7の安い側**だった。ただし n=2 vs 5 で、高倍率の実測は**36.5倍と40.5倍まで**しかない
    （**59倍の帯のデータは一件も無い**）。だからDとEの線は歴史に実測のある帯に置く。

やること:
  score_all.js の四関門の**価格条件の項だけ**を差し替えて回し、**必ず元へ戻す**。
  席順上位10社の枠（当時は合成点順）は門の ccfAllocTop（単一実装）をそのまま使う＝二つ目の検査器を作らない（v9.9.65の掟）。
  Ω75+・堀70+・点検0件の三段はどの変種でも共通。
  **採用はルール1/6（ユーザー明示指示）の領分。この道具は測るだけで、正本は一切変えない。**

使い方: python3 night/shadow_x_moat_exception.py
"""
import json
import os
import re
import shutil
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
JS = "night/score_all.js"
ANCHOR = "buy: s >= 75 && x.xPass === true && mg.pass === true && audE === 0 && audU === 0 });"


def cond(expr):
    return f"buy: s >= 75 && ({expr}) && mg.pass === true && audE === 0 && audU === 0 }});"


CANDS = [
    ("A 現行 E[r]≥0", None),
    ("B E[r]≥−2", "x.xEr != null && x.xEr >= -2"),
    ("C E[r]≥0 or 堀85+", "x.xPass === true || (mg.idx != null && mg.idx >= 85)"),
    ("D E[r]≥0 or (堀85+ ∧ PER≤35)", "x.xPass === true || (mg.idx != null && mg.idx >= 85 && x.per > 0 && x.per <= 35)"),
    ("E E[r]≥0 or (堀85+ ∧ PER≤30)", "x.xPass === true || (mg.idx != null && mg.idx >= 85 && x.per > 0 && x.per <= 30)"),
]


def run():
    subprocess.run(["node", JS], capture_output=True, text=True, check=False)
    rows = json.load(open("out/score_all.json", encoding="utf-8"))
    buy = [r for r in rows if r.get("buy")]
    quali = [r for r in rows if r.get("quali")]
    return buy, quali


def main():
    src = open(JS, encoding="utf-8").read()
    if ANCHOR not in src:
        raise SystemExit(
            "この道具は **v9.9.98 より前の設計（門X遮断器 E[r]≥0 が買付の関門だった頃）** を測るためのもの。\n"
            "遮断器は 2026-08-07 に関門から外れ、錨の行（buy: ... x.xPass === true ...）はもう存在しない。\n"
            "当時の測定は out/ と CLAUDE.md に残っている＝**記録用であって現行の門には当たらない**。")
    shutil.copy(JS, JS + ".shadowbak")
    base_buy = None
    try:
        for label, expr in CANDS:
            open(JS, "w", encoding="utf-8").write(src if expr is None else src.replace(ANCHOR, cond(expr)))
            buy, quali = run()
            names = [r["nm"].split()[0] for r in buy]
            if base_buy is None:
                base_buy = set(r["t"] for r in buy)
                diff = ""
            else:
                now = set(r["t"] for r in buy)
                inn = sorted(now - base_buy)
                out = sorted(base_buy - now)
                diff = f"  ＋{','.join(inn) or 'なし'} ／ −{','.join(out) or 'なし'}"
            print(f"\n【{label}】投下可 {len(buy)}社 / 四段通過 {len(quali)}社{diff}")
            print(f"   {' '.join(names)}")
            for r in buy:
                if base_buy and r["t"] not in base_buy:
                    print(f"     ＋{r['t']:6} Ω{r['s']:.1f} 堀{r['moat']} E[r]{r['xEr']}%")
    finally:
        shutil.move(JS + ".shadowbak", JS)
        subprocess.run(["node", JS], capture_output=True, text=True, check=False)
        print("\n（score_all.js と out/score_all.json を元へ戻した）")


if __name__ == "__main__":
    main()
