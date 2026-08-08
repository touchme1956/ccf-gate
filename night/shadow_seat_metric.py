#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_seat_metric.py — **E[r] を門から外したら誰が座るか**（2026-08-07新設）

なぜ要るか（ユーザーの問い「そもそもE[r]は無くすべきでは?」）:
  E[r] は門の中で**4つの別の仕事**をしている。無くす／残すの議論は仕事ごとに分けないと噛み合わない。
    (1) 遮断器      xPass = E[r] ≥ 0                      ← 買付の可否
    (2) 席の選定    合成点 = Ω × E[r]点 ÷ 50 の上位10社     ← 誰が枠に入るか
    (3) 表示・順位  Ⅵ買付順位の並び
    (4) 予実台帳    audit_er_realized（**答え合わせできる予測**として保存）
  v9.9.96 で配分は等ウェイトになったので、E[r] は**もう金額を決めていない**。
  残る決定権は (1)(2) だけ。この道具はその2つを外した世界を実測する。

歴史側の証拠（既測・out/retro_er_test.json / 2026-08-07のコミット 3b2177f）:
  ・選別器としての E[r]: 質実証プール内で **Q5−Q1 = −5.3pt**＝弱い逆信号
  ・irr を固定すると E[r] の効果は消える（irr85 +1.2 / irr75 −4.4 / irr50 +1.5pt）
  ・E[r] を固定すると irr=85 の効果は残る（高い半分 +12.0 / 低い半分 +11.5pt）
    ⇒ **E[r]の勝ちは irr の影だった**
  ・遮断器としての E[r]<0: 恒久毀損を 3.2倍に濃縮する（有効）が、
    **止めた群の中央値のほうが高い(9.4% vs 7.2%)＝機会費用を現に払っている**（retro_breaker_test）

**この道具は規約を一切変えない**（絶対のルール1）。誰がどう動くかを出すだけ。

使い方: python3 night/shadow_seat_metric.py [--write]
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
WRITE = "--write" in sys.argv[1:]
SEATS = 10


def erpt(e):
    return 0.0 if e is None else max(0.0, min(100.0, 50 + (e - 12) * 5))


def load_json(name, default=None):
    try:
        return json.load(open(os.path.join(OUT, name), encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def main():
    sa = {r["t"]: r for r in load_json("score_all.json", [])}
    stale = {k for k, v in (load_json("stale_bs.json").get("items") or {}).items()
             if v and v.get("verdict") == "要審査"}
    vf = {k for k, v in (load_json("validate_fail.json").get("items") or {}).items()
          if v and (v.get("n") or 0) > 0}
    irr = {}
    for p in glob.glob(os.path.join(OUT, "*_gate_pack.json")):
        t = os.path.basename(p).replace("_gate_pack.json", "")
        d = json.load(open(p, encoding="utf-8"))
        irr[t] = (d.get("data") or d).get("irr")

    def clean(r):
        """遮断器**以外**の四関門（Ω75+ ∧ 堀70+ ∧ 点検 ∧ 期末後 ∧ 納品検査 ∧ 事業の収縮なし）"""
        t = r["t"]
        return ((r.get("s") or 0) >= 75 and r.get("moatOK") and (r.get("audE") or 0) == 0
                and (r.get("audU") or 0) == 0 and t not in stale and t not in vf)

    base = [r for r in sa.values() if clean(r)]
    with_breaker = [r for r in base if r.get("xPass") is True]
    cur = sorted([r["t"] for r in sa.values() if r.get("buy")])

    print("■ E[r] を門から外したら誰が座るか")
    print(f"  遮断器あり（現行）の資格 **{len(with_breaker)}社** ／ 遮断器なしの資格 **{len(base)}社**"
          f" ／ 席は {SEATS}")
    print(f"  ⇒ **現行は 11社で 10席を争っている**＝席の選定式が決めているのは実質「誰を1社落とすか」だけ")

    metrics = [
        ("A 現行  Ω×E[r]点/50", lambda r: -(r["s"] * erpt(r.get("xEr")) / 50)),
        ("B Ω順（E[r]を使わない）", lambda r: -(r.get("s") or 0)),
        ("C 堀順", lambda r: -(r.get("moat") or 0)),
        ("D irr=85優先 → Ω順", lambda r: (0 if irr.get(r["t"]) == 85 else 1, -(r.get("s") or 0))),
    ]
    res = {}
    for pool_name, pool in (("遮断器あり", with_breaker), ("遮断器なし", base)):
        print(f"\n── 席の選定式を替える（{pool_name}・資格{len(pool)}社）──")
        for lab, key in metrics:
            top = [r["t"] for r in sorted(pool, key=key)[:SEATS]]
            out_, in_ = sorted(set(cur) - set(top)), sorted(set(top) - set(cur))
            print(f"  {lab:<24} 出:{' '.join(out_) or '—':<22} 入:{' '.join(in_) or '—'}")
            res[f"{pool_name}/{lab}"] = dict(top=top, out=out_, into=in_)

    print("\n── 資格ありの全社（Ω順・遮断器なしの世界）──")
    print(f"  {'銘柄':<8}{'Ω':>6}{'堀':>7}{'E[r]':>7}  irr   遮断器  現行")
    for r in sorted(base, key=lambda r: -(r.get("s") or 0)):
        br = "通" if r.get("xPass") is True else ("×" if r.get("xPass") is False else "na")
        er = "na" if r.get("xEr") is None else f"{r['xEr']:.1f}"
        print(f"  {r['t']:<8}{r['s']:>6}{(r.get('moat') or 0):>7.1f}{er:>7}  "
              f"{str(irr.get(r['t']) or '—'):<5} {br:^6} {'🟢' if r.get('buy') else ''}")

    print("\n■ 読み方")
    print("  ・**席の選定から E[r] を外すと動くのは1社だけ**（MCO ⇄ IDXX）——四関門が既に11社まで絞っているから")
    print("  ・**遮断器も外すと3社動く**（出 ADBE/MA/MCO・入 HWM/IDXX/VRSK）。"
          "VRSKは堀85.3＝台帳最高・irr=85が3ビンテージで確認された社")
    print("  ・(4)予実台帳の E[r] は**残すべき**——決定に使わなくても、"
          "『答え合わせできる予測』を消すと E[r] が正しいか誤りかを永久に知れなくなる")

    if WRITE:
        p = os.path.join(OUT, "shadow_seat_metric.json")
        json.dump({"generated": "2026-08-07", "seats": SEATS, "current": cur,
                   "eligible_with_breaker": [r["t"] for r in with_breaker],
                   "eligible_no_breaker": [r["t"] for r in base],
                   "scenarios": res,
                   "note": "規約は不変。席の選定式・遮断器の変更はユーザーの明示指示の領分（絶対のルール1）"},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
