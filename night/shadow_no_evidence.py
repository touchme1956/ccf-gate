#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_no_evidence.py — 「根拠の無い値を門が null 扱いにしたら誰がどう動くか」を実測する（2026-07-29新設）

なぜ道具にしたか:
  根拠なき値を null 扱いにするのは、dom/moatW で既に実装した再正規化パターン（v9.9.39）の一般化で、
  筋は通っている。しかし**これは採点そのものを動かす**——多数の社のΩが変わり、投下可の顔ぶれが変わる。
  絶対のルール1により、採点基準の変更はユーザーの明示指示がいる。だから先に「変えたら何が起きるか」を
  実測する。**基準を変えたら誰がどう動くかは、推測でなく実測で出す**（門の既定の作法）。

やること:
  1. 全パックを退避
  2. 判断項目・機械項目のうち **_meta.evidence にも provenance にも裏付けが無い欄を null 化**
  3. `node night/score_all.js` を回して Ω と四関門を実測
  4. 必ずパックを元へ戻す（finally）
  ※これは影の計測であって、正本の採点・台帳は一切変えない。

使い方: python3 night/shadow_no_evidence.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "night"))

import audit_evidence as AE      # noqa: E402  項目リストと根拠判定はここが正本

OUT = os.path.join(BASE, "out")
SCORE = os.path.join(OUT, "score_all.json")


def run_score():
    subprocess.run(["node", "night/score_all.js"], check=True,
                   capture_output=True, text=True)
    return json.load(open(SCORE, encoding="utf-8"))


def summary(rows, label):
    q75 = [r for r in rows if (r.get("s") or 0) >= 75]
    buy = [r for r in rows if r.get("buy")]
    print(f"{label:12s} Ω75+ {len(q75):3d}社 / 🟢投下可 {len(buy):2d}社"
          f"  ({' '.join(sorted(r['t'] for r in buy)) or 'なし'})")
    return {r["t"]: (r.get("s") or 0) for r in rows}, {r["t"] for r in buy}


def main():
    packs = [f for f in sorted(os.listdir(OUT)) if f.endswith("_gate_pack.json")]
    bak = tempfile.mkdtemp(prefix="ccf_packs_")
    try:
        for f in packs:
            shutil.copy2(os.path.join(OUT, f), os.path.join(bak, f))
        base_score, base_buy = summary(run_score(), "現行")

        stripped = 0
        fields = AE.JUDGE + AE.MACHINE
        for f in packs:
            p = os.path.join(OUT, f)
            d = json.load(open(p, encoding="utf-8"))
            meta = d.get("_meta") or {}
            ev = meta.get("evidence") or {}
            pv = meta.get("provenance") or {}
            hit = False
            for k in fields:
                if AE.has_val(d.get(k)) and not AE.has_ev(ev, k) and not pv.get(k):
                    d[k] = None
                    stripped += 1
                    hit = True
            if hit:
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n根拠の無い値 {stripped} 個を null 化して再採点\n")
        new_score, new_buy = summary(run_score(), "根拠なきnull")

        gone = sorted(base_buy - new_buy)
        added = sorted(new_buy - base_buy)
        print(f"\n投下可から落ちる: {' '.join(gone) or 'なし'}")
        print(f"投下可に上がる:   {' '.join(added) or 'なし'}")
        moves = sorted(((abs(new_score.get(t, 0) - v), t, v, new_score.get(t, 0))
                        for t, v in base_score.items()), reverse=True)[:15]
        print("\nΩの動きが大きい順（上位15）:")
        for dlt, t, a, b in moves:
            if dlt < 0.05:
                break
            print(f"  {t:6s} Ω{a:5.1f} → {b:5.1f}  ({b-a:+.1f})")
    finally:
        for f in packs:
            shutil.copy2(os.path.join(bak, f), os.path.join(OUT, f))
        shutil.rmtree(bak, ignore_errors=True)
        run_score()          # score_all.json を現行の値へ戻す
        print("\n※パックと score_all.json は元へ戻した（影の計測であって正本は変えていない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
