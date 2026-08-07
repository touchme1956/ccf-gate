#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_alloc_moat.py — 配分式(合成点)に堀を入れたら総合リターンがどうなるかの影の計測（2026-08-06新設）

なぜ要るか:
  2026-08-06の測定で、門には**価格の関門が二重**にあると分かった——
    ①遮断器 E[r]≥0（v9.9.84で「価格は質の中で選別しない」を根拠に緩めた）
    ②配分式 ccfAllocTop の `合成点=(Ω−70)×E[r]点÷50`（E[r]点は12%=50の錨・**E[r]≤2%で0**）
  遮断器①をどう緩めても投下可が動かないのは②が崖で効いているから（CW/VRSKは合成点0.00）。
  一方 irr=85 の追試は両ビンテージで合格し、**堀の実証は投下可の選別に一切使われていない**。
  そこで「②に堀を入れたら総合リターンがどうなるか」を門そのもので測る。

やること:
  index.html の ccfAllocTop の2行だけを差し替えて `node night/score_all.js` を回し、**必ず元へ戻す**。
  四関門（Ω75+・堀70+・点検0件・事業の収縮なし）※v9.9.98で遮断器を撤去は全変種で共通＝変えるのは**席の並べ方だけ**。
  各案について DCA規約どおりの配分を組んで比べる:
    目標ウェイト = 城60% × 合成点÷Σ合成点(上位10社)、1銘柄上限8%
    加重E[r] = Σ(w×E[r])÷Σw ／ 城の実効 = Σw ／ **総合 = 城実効×加重E[r] + (1−城実効)×9%（網）**

  **採用はルール1/6（ユーザー明示指示）の領分。この道具は測るだけで、正本は一切変えない。**
使い方: python3 night/shadow_alloc_moat.py
"""
import json
import os
import shutil
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
NET = 0.09      # 網(ETF)の想定年率。CLAUDE.mdの算術と同じ
CASTLE = 0.60   # 城の目標比率（v9.9.68）
CAP = 0.08      # 1銘柄の上限（¼ケリー）

ANCHOR = ("  const erP=x=>Math.max(0,Math.min(100,50+((x==null?2:x)-12)*5));\n"
          "  const sc=c=>Math.max(0,(c.s||0)-70)*erP(c.xEr)/50;")

# 堀点の目盛りは E[r]点と同じ作法（錨を50点に置き±10ptで0-100）。堀の判定帯は70-88なので錨は78。
MOATP = "  const mP=c=>Math.max(0,Math.min(100,50+(((c.moat==null?70:c.moat))-78)*5));\n"

CANDS = [
    ("A 現行 (Ω−70)×E[r]点/50", None),
    ("B 堀を第三因子 (Ω−70)×E[r]点/50×堀点/50", MOATP + "  const sc=c=>Math.max(0,(c.s||0)-70)*erP(c.xEr)/50*mP(c)/50;"),
    ("C E[r]の崖を外す（下限10点）", "  const erP=x=>Math.max(10,Math.min(100,50+((x==null?2:x)-12)*5));\n"
                             "  const sc=c=>Math.max(0,(c.s||0)-70)*erP(c.xEr)/50;"),
    ("D 崖を外し堀も入れる", MOATP + "  const erP2=x=>Math.max(10,Math.min(100,50+((x==null?2:x)-12)*5));\n"
                        "  const sc=c=>Math.max(0,(c.s||0)-70)*erP2(c.xEr)/50*mP(c)/50;"),
    ("E 堀のみ (Ω−70)×堀点/50", MOATP + "  const sc=c=>Math.max(0,(c.s||0)-70)*mP(c)/50;"),
]


def erp(x):
    x = 2 if x is None else x
    return max(0, min(100, 50 + (x - 12) * 5))


def portfolio(buy, scfn):
    """DCA規約どおりに配分して 加重E[r]・城の実効・総合 を出す"""
    sc = {r["t"]: scfn(r) for r in buy}
    tot = sum(sc.values())
    if tot <= 0:
        return None
    w = {t: min(CAP, CASTLE * s / tot) for t, s in sc.items()}
    castle = sum(w.values())
    if castle <= 0:
        return None
    wer = sum(w[r["t"]] * (r["xEr"] or 0) for r in buy) / castle
    total = castle * wer / 100 + (1 - castle) * NET
    return {"castle": castle, "wer": wer, "total": total * 100}


def run():
    subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True, check=False)
    rows = json.load(open("out/score_all.json", encoding="utf-8"))
    return [r for r in rows if r.get("buy")]


def main():
    src = open(HTML, encoding="utf-8").read()
    if ANCHOR not in src:
        raise SystemExit("錨が見つからない（ccfAllocTop が変わった？）")
    shutil.copy(HTML, HTML + ".shadowbak")
    base = None
    try:
        for label, repl in CANDS:
            open(HTML, "w", encoding="utf-8").write(src if repl is None else src.replace(ANCHOR, repl))
            buy = run()
            # 配分は「その案の合成点」で組む（席順と配分は同じ式）
            if repl is None or "mP(c)" not in repl:
                lo = 10 if "Math.max(10," in (repl or "") else 0
                scfn = (lambda r, lo=lo: max(0, (r["s"] or 0) - 70) * max(lo, erp(r["xEr"])) / 50)
            elif "erP2" in repl:
                scfn = (lambda r: max(0, (r["s"] or 0) - 70) * max(10, erp(r["xEr"])) / 50
                        * max(0, min(100, 50 + ((r["moat"] or 70) - 78) * 5)) / 50)
            elif "erP(c.xEr)" in repl:
                scfn = (lambda r: max(0, (r["s"] or 0) - 70) * erp(r["xEr"]) / 50
                        * max(0, min(100, 50 + ((r["moat"] or 70) - 78) * 5)) / 50)
            else:
                scfn = (lambda r: max(0, (r["s"] or 0) - 70)
                        * max(0, min(100, 50 + ((r["moat"] or 70) - 78) * 5)) / 50)
            p = portfolio(buy, scfn)
            names = [r["nm"].split()[0] for r in buy]
            if base is None:
                base = set(r["t"] for r in buy)
                diff = ""
            else:
                now = set(r["t"] for r in buy)
                diff = f"  ＋{','.join(sorted(now - base)) or 'なし'} ／ −{','.join(sorted(base - now)) or 'なし'}"
            if p:
                print(f"\n【{label}】{len(buy)}社{diff}")
                print(f"   城の実効 {p['castle']:.1%} / 加重E[r] {p['wer']:.2f}% / **総合 {p['total']:.2f}%**（網{NET:.0%}）")
                print(f"   {' '.join(names)}")
            else:
                print(f"\n【{label}】{len(buy)}社 — 配分不能{diff}")
    finally:
        shutil.move(HTML + ".shadowbak", HTML)
        subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True, check=False)
        print("\n（index.html と out/score_all.json を元へ戻した）")


if __name__ == "__main__":
    main()
