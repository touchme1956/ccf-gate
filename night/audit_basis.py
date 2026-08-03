#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_basis.py — 台帳の roic が**どの基準で作られているか**を数える（2026-08-03新設）

なぜ要るか:
  v9.9.72 で roic/roicg を through-cycle（5年中央値）へ移行したが、
  (a) 採取器とパックが15%以上食い違う社（審査官が原本で直した＝系列も信用できない）
  (b) 5年系列が3年未満の社 / 日本株・ADRでSEC対象外の社
  には当てていない。結果として**台帳に二つの基準が混在する**。
  さらに今後の審査は採取器が through-cycle を出すので、**放っておくと気づかないうちに混ざり続ける**。
  基準の違う二つを突き合わせるのは、この repo が繰り返し事故を起こしている型
  （KLACの分割・ADRのper・JP門0のpt）。だから**混在は消せなくても、見えるようにしておく**。

使い方: python3 night/audit_basis.py [--list]
"""
import json, glob, os, sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIST = "--list" in sys.argv
try:
    S = {r["t"]: r for r in (lambda d: d["rows"] if isinstance(d, dict) else d)(
        json.load(open("out/score_all.json", encoding="utf-8")))}
except Exception:
    S = {}
rows = []
for p in sorted(glob.glob("out/*_gate_pack.json")):
    t = os.path.basename(p).replace("_gate_pack.json","")
    d = json.load(open(p, encoding="utf-8"))
    b = ((d.get("_meta") or {}).get("basis") or {}).get("roic") or "**印なし**"
    r = S.get(t, {})
    rows.append((t, b, r.get("s"), bool(r.get("buy")), (r.get("s") or 0) >= 72))
from collections import Counter
def kind(b): return "through-cycle" if str(b).startswith("through-cycle") else b
for lab, sel in (("全318社", lambda x: True),
                 ("判定圏(Ω72+)", lambda x: x[4]),
                 ("投下可", lambda x: x[3])):
    g = [x for x in rows if sel(x)]
    c = Counter(kind(x[1]) for x in g)
    tot = len(g)
    parts = " / ".join(f"{k} {v}社({v/tot*100:.0f}%)" for k, v in c.most_common())
    print(f"{lab:14s} n={tot:3d}  {parts}")
mix = [x for x in rows if x[4] and kind(x[1]) == "single-year"]
print(f"\n判定圏で単年のまま残る {len(mix)}社"
      + ("——ここが混在の実体。原本から5年系列を作れば解消する" if mix else ""))
if LIST:
    for t, b, s, buy, _ in sorted(mix, key=lambda x: -(x[2] or 0)):
        print(f"   {t:8s} Ω{(s or 0):5.1f} {'🟢投下可' if buy else ''}")
