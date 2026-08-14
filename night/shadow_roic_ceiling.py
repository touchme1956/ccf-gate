#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_roic_ceiling.py — ROICの目盛りの天井を外したら誰がどう動くか（2026-08-14新設）

■ なぜこれを測るのか（配分の診断の結論）
  `node night/audit_weights.js --q75` の実測:
    ・roic を 10%→40% に振ると実効 **38.4%＝単独最大**
    ・**だが判定圏の各社を実値から ±25% 動かすと 局所実効 0.00%・逆向き7社**
    ・原因は飽和 —— **roicPt が 18/31社**（roic≥40 で96点頭打ち）／
      **F7のROIC項が 29/31社**（roic≥25 で100点満点）で天井に張り付いている
    ・判定圏の roic 中央値は **42.8%** ＝ どちらの天井よりも上
  ⇒「Ωの38%を占める」と書いてある入力が、**買付を判断する帯では動かない**。
     これは重みの問題ではなく**目盛りの天井が判定圏より下にある**問題。

■ ★新しい定数を作らない
  A: roicPt の [40,96],[200,96] を、直前の傾き(0.6/pt)のまま**目盛りの天井100**まで伸ばす
     （96→100 は 6.67pt ＝ roic 46.67 で 100）。任意の数字を置いていない。
  B: F7 の満点 `rc/25*100` を `rc/40*100` へ——**40 は roicPt が既に使っている数字**
     （roicPt の最終節点 [40,96]）。新設ではなく既存の目盛りに揃える。
  C: A と B の両方。

■ 型は shadow_gmpt.py と同じ: index.html の1行だけ差し替え→score_all→**必ず元へ戻す**（sha256で検算）

使い方: python3 night/shadow_roic_ceiling.py
出力: out/shadow_roic_ceiling.json
"""
import hashlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
IDX = os.path.join(BASE, "index.html")
OUT = os.path.join(BASE, "out")

R0 = "const P=[[0,40],[8,50],[12,62],[16,72],[22,82],[30,90],[40,96],[200,96]];"
R1 = "const P=[[0,40],[8,50],[12,62],[16,72],[22,82],[30,90],[40,96],[46.6667,100],[200,100]];"
RET0, RET1 = "return 96;}", "return 100;}"
F0 = "const rcScore=Math.min(100,rc/25*100);    // ROIC25%で満点"
F1 = "const rcScore=Math.min(100,rc/40*100);    // ROIC40%で満点"

CASES = {
    "A roicPt の天井を外す": [(R0, R1), (RET0, RET1)],
    "B F7の満点を 25→40": [(F0, F1)],
    "C A＋B": [(R0, R1), (RET0, RET1), (F0, F1)],
}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run():
    r = subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("items")
    return {(x.get("t") or x.get("nm")): x for x in rows}


def main():
    src = open(IDX, encoding="utf-8").read()
    before = sha(IDX)
    base = run()
    bset = {t for t, x in base.items() if x.get("buy")}
    print(f"■ 現行: 投下可 {len(bset)}社  {' '.join(sorted(bset))}\n")

    res = {}
    try:
        for name, pats in CASES.items():
            s = src
            for old, new in pats:
                if old not in s:
                    raise RuntimeError(f"{name}: 錨が無い → {old[:40]}")
                s = s.replace(old, new, 1)
            open(IDX, "w", encoding="utf-8").write(s)
            cur = run()
            cset = {t for t, x in cur.items() if x.get("buy")}
            moved = [(t, round(float(cur[t]["s"]) - float(base[t]["s"]), 1))
                     for t in base if t in cur
                     and abs(float(cur[t]["s"]) - float(base[t]["s"])) > 0.049]
            moved.sort(key=lambda x: -abs(x[1]))
            q75b = {t for t, x in base.items() if float(x["s"]) >= 75}
            q75c = {t for t, x in cur.items() if float(x["s"]) >= 75}
            res[name] = dict(
                buy_n=len(cset), buy_in=sorted(cset - bset), buy_out=sorted(bset - cset),
                omega_moved=len(moved), omega_max=moved[0][1] if moved else 0.0,
                top5=[[t, d] for t, d in moved[:5]],
                q75_n=len(q75c), q75_in=sorted(q75c - q75b), q75_out=sorted(q75b - q75c))
            r = res[name]
            print(f"■ {name}")
            print(f"   投下可 {len(bset)}→{r['buy_n']}社"
                  + (f"（入 {' '.join(r['buy_in'])} ／ 出 {' '.join(r['buy_out'])}）"
                     if r["buy_in"] or r["buy_out"] else "＝**顔ぶれ不変**"))
            print(f"   Ωが動く {r['omega_moved']}社・最大 {r['omega_max']:+.1f}pt"
                  f"   例: {' '.join(f'{t}{d:+.1f}' for t, d in r['top5'])}")
            print(f"   Ω75+ {len(q75b)}→{r['q75_n']}社"
                  + (f"（入 {' '.join(r['q75_in'])} ／ 出 {' '.join(r['q75_out'])}）" if r["q75_in"] or r["q75_out"] else "")
                  + "\n")
    finally:
        open(IDX, "w", encoding="utf-8").write(src)
        run()
    assert sha(IDX) == before, "★index.html の復元に失敗した"
    print(f"✓ index.html 復元を検算（sha256 {before[:12]}…）")

    json.dump(dict(generated=__import__("time").strftime("%Y-%m-%d"),
                   why="判定圏で roic が飽和して局所実効0%になっている問題（audit_weights --q75）の是正候補",
                   no_new_constants="A=直前の傾きを目盛りの天井100まで／B=roicPt が既に使う40へ揃える",
                   base_buy=sorted(bset), cases=res),
              open(os.path.join(OUT, "shadow_roic_ceiling.json"), "w"),
              ensure_ascii=False, indent=1)
    print("→ out/shadow_roic_ceiling.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
