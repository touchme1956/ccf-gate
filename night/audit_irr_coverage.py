#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_irr_coverage.py — irr の被覆の穴を測って作業リストにする（2026-08-14新設・ユーザー指示の①）

■ なぜ irr なのか
  13年・5系統・204通り・7アンカーの検証を**生き延びた唯一の指標**が irr（移行障壁の型）。
  効く機構まで分かっている——`ρ(irr, 事業の「驚き」) = +0.077〜+0.294`。
  「驚き」＝実現した事業のうち**入口の財務からは読めなかった部分**で、構造上 入口の財務と直交する。
  ⇒ **irr は財務諸表に無い情報を運んでいる**。だから価格の線が5回とも空振りする中で irr だけが残った。

■ ★その欄が、母集団の 12.3% にしか付いていない（実測）
  門0の母集団 2,902社 ／ パックがある 369社 ／ irr が測られている 357社。

■ ★そして詰まっているのは読解ではなく**門0のキューの幅**だった
  実測: **2,605社が門2審査に一度も載っていない**。うち門0スコア5点以上（質のふるいを概ね通る群）が
  **297社**で、その中には **AAPL(6点)** すら居る。
  原因は門0の構造——キューは `TOP_N100 ＋ 審査優先レーン` で、レーンは
  **「6点＝単一fail」の社にしか病名を付けない**（gate0_v8_5.py:353）。fails が2〜6個ある社は
  pt上位100にも入らなければ backlog へ落ちる。
  **歴史で irr=85 だった12社が門0で落ちていた**のと同じ構造（2026-08-07の記録）。

■ この道具がすること（判定には一切触れない）
  (1) 被覆を数える（母集団／パック／irr あり／刻み別）
  (2) **一度も審査されていない社**を門0スコア順に出す＝読む先の作業リスト
  (3) パックはあるが irr が空の社を名指しする
  ⚠ キューの幅を広げること自体は**門0の選別基準の改定＝絶対のルール1の領分**。
    この道具は「何が漏れているか」を見せるだけで、規約は一つも変えない。

使い方: python3 night/audit_irr_coverage.py [--json] [--top N]
出力: out/irr_coverage.json
"""
import csv
import glob
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")


def load_queue():
    p = os.path.join(BASE, "gate1_queue.json")
    if not os.path.exists(p):
        return set()
    q = json.load(open(p, encoding="utf-8"))
    q = q if isinstance(q, list) else (q.get("items") or q.get("queue") or [])
    s = set()
    for x in q:
        t = (x.get("ticker") or x.get("t")) if isinstance(x, dict) else x
        if t:
            s.add(str(t).upper())
    return s


def main():
    top = 40
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])

    # ⚠ gate0_all.csv は BOM 付き。utf-8 で開くと 'ticker' が '﻿ticker' になり
    #   **全社のティッカーが空** になって「漏れ0社」というもっともらしい嘘が出る（実際に踏んだ）。
    csvp = os.path.join(BASE, "gate0_all.csv")
    rows = list(csv.DictReader(open(csvp, encoding="utf-8-sig"))) if os.path.exists(csvp) else []
    if rows and not (rows[0].get("ticker") or "").strip():
        sys.exit("★gate0_all.csv の ticker が読めない（BOM？）——測らずに終わる")

    packs, irr_have, irr_blank, rung = {}, 0, [], Counter()
    for p in glob.glob(os.path.join(OUT, "*_gate_pack.json")):
        t = os.path.basename(p).split("_gate_pack")[0]
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        packs[t.upper()] = d
        v = d.get("irr")
        if v is None:
            irr_blank.append(t)
        else:
            irr_have += 1
            rung[str(v)] += 1

    qt = load_queue()
    seen = set(packs) | qt
    never, by_score = [], Counter()
    for r in rows:
        t = (r.get("ticker") or "").upper()
        try:
            s = int(float(r.get("score") or 0))
        except Exception:
            continue
        by_score[s] += 1
        if t and t not in seen:
            never.append((s, t, r.get("name") or "", r.get("roic_latest"), r.get("opm")))
    never.sort(key=lambda x: (-x[0], x[1]))
    hi = [x for x in never if x[0] >= 5]

    n_uni = len(rows)
    print("■ irr の被覆（13年の検証を生き延びた唯一の指標が、どれだけ測られているか）")
    print(f"   門0の母集団      {n_uni:5d} 社")
    print(f"   パックがある     {len(packs):5d} 社  = {len(packs)/n_uni*100:4.1f}%")
    print(f"   irr が測られた   {irr_have:5d} 社  = {irr_have/n_uni*100:4.1f}%   ← ここが門の精度の上限")
    print(f"   刻み別: " + " / ".join(f"{k}:{v}" for k, v in sorted(rung.items(), key=lambda x: -float(x[0]))))
    print(f"\n■ パックはあるが irr が空: {len(irr_blank)}社")
    print(f"   {' '.join(sorted(irr_blank))}")
    jp = [t for t in irr_blank if t[:1].isdigit()]
    if jp:
        print(f"   ⚠ うち日本株 {len(jp)}社——有報に代替可能性の記述が無く"
              f"**掘り尽くして確定した空欄**（キーエンス型）。規約を変えない限り埋まらない")

    print(f"\n■ ★門2審査に一度も載っていない社: {len(never)}社 / {n_uni}社")
    print(f"   うち門0スコア5点以上（質のふるいを概ね通る群）: **{len(hi)}社**")
    print(f"   {'点':>3s} {'社数':>5s}  {'未審査':>6s}")
    for s in sorted(by_score, reverse=True):
        m = sum(1 for x in never if x[0] == s)
        print(f"   {s:>3d} {by_score[s]:>5d}  {m:>6d}" + ("  ← 読む価値のある帯" if s >= 5 else ""))

    print(f"\n■ 読む先の作業リスト（門0スコア順・上位{top}社）")
    for s, t, nm, roic, opm in hi[:top]:
        print(f"   {s}点 {t:8s} {str(nm)[:34]:34s} roic {str(roic)[:6]:>6s} opm {str(opm)[:6]:>6s}")

    doc = dict(generated=__import__("time").strftime("%Y-%m-%d"),
               universe=n_uni, packs=len(packs), irr_measured=irr_have,
               irr_pct=round(irr_have / n_uni * 100, 1), rungs=dict(rung),
               irr_blank=sorted(irr_blank),
               never_reviewed=len(never), never_reviewed_score5plus=len(hi),
               worklist=[dict(score=s, ticker=t, name=nm) for s, t, nm, _, _ in hi[:200]],
               NOTE="キューの幅を広げるのは門0の選別基準の改定＝絶対のルール1の領分。"
                    "この道具は漏れを見せるだけで規約は一つも変えない。")
    json.dump(doc, open(os.path.join(OUT, "irr_coverage.json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n→ out/irr_coverage.json")
    print("⚠ キューの幅を広げること自体は門0の選別基準の改定＝ユーザーの明示指示の領分。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
