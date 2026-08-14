#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro_test.py — 事前登録どおりに Ω̂ を一度だけ裁く（2026-08-14新設）

■ 事前登録は out/omega_retro_prereg.json（**Ω̂ と結果を一度も突き合わせる前に**コミット済み）
  この器は**そこに書いた判定をそのまま実行するだけ**。基準をここで書き足さない。

■ H1（主判定・これが不合格なら H2/H3 はやらない＝停止規則）
  現行の重みの Ω̂ は durable を当てるか。
  判定: Ω̂ 上半分と下半分の P(durable) の差 lift >= 0.15 ∧ 置換p < 0.05 を **両ビンテージで**満たす

■ 当てる先（新しい定数を作っていない）
  durable = (実現年率 tr_cagr > -0.15) AND (前方ROIC中央値 >= 0.15)
  ⚠ 事前登録に書いたとおり **合成は事実上「持続」に縮退している**（2013: 48/48・2015: 101/102）。
    この検定が測るのは「Ω̂ が持続を当てるか」だけ。「両方が効いた」と読んではならない。

■ 置換の作り方（2026-08-12 に33倍の過小評価を踏んだ型を再演しない）
  結果ラベルを**会社単位で**並べ替え、**両ビンテージに同じ置換を当てる**
  ——アンカー間の相関を壊さないため。ビンテージ内で独立に混ぜると帰無が緩くなる。

使い方: python3 night/omega_retro_test.py
出力: out/omega_retro_test.json
"""
import json
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")

BREAK, FWD = -0.15, 0.15       # 既存の定数（事前登録どおり）
LIFT_LINE, ALPHA = 0.15, 0.05  # 事前登録どおり
NPERM, SEED = 2000, 20260814

RET = {2013: "out/retro_returns_2013_all.json", 2015: "out/retro_returns_2015_q.json"}
COH = {2013: "out/retro_cohort_2013.json", 2015: "out/retro_cohort_2015.json"}


def load(f):
    d = json.load(open(f, encoding="utf-8"))
    r = d.get("items") or d.get("rows") or d
    return list(r.values()) if isinstance(r, dict) else r


def key(x):
    return x.get("ticker") or x.get("t")


def split_lift(pairs):
    """Ω̂ 上半分 vs 下半分の P(durable) 差。pairs=[(omega, durable)]"""
    s = sorted(pairs, key=lambda x: -x[0])
    h = len(s) // 2
    hi, lo = s[:h], s[h:]
    if not hi or not lo:
        return None, None, None
    a = sum(1 for _, d in hi if d) / len(hi)
    b = sum(1 for _, d in lo if d) / len(lo)
    return a - b, a, b


def main():
    data, missing = {}, {}
    for yr in (2013, 2015):
        p = os.path.join(OUT, f"omega_retro_omega_{yr}.json")
        if not os.path.exists(p):
            sys.exit(f"{p} が無い（先に node night/omega_retro_build.js）")
        O = json.load(open(p, encoding="utf-8"))["items"]
        R = {key(x): x for x in load(RET[yr])}
        C = {key(x): x for x in load(COH[yr])}
        rows, ng = [], 0
        for t, o in O.items():
            tr = (R.get(t) or {}).get("tr_cagr")
            fw = (C.get(t) or {}).get("fwd_roic_med5_a1")
            if tr is None or fw is None or o.get("omega") is None:
                ng += 1
                continue
            rows.append((t, o["omega"], bool(tr > BREAK and fw >= FWD)))
        data[yr] = rows
        missing[yr] = ng

    # --- H1 ---
    res = {}
    for yr, rows in data.items():
        lift, hi, lo = split_lift([(o, d) for _, o, d in rows])
        res[yr] = dict(n=len(rows), dropped=missing[yr],
                       base=round(sum(1 for _, _, d in rows if d) / len(rows), 4) if rows else None,
                       lift=None if lift is None else round(lift, 4),
                       p_hi=None if hi is None else round(hi, 4),
                       p_lo=None if lo is None else round(lo, 4))

    # --- 置換（会社単位・両ビンテージに同じ置換） ---
    rnd = random.Random(SEED)
    allt = sorted({t for rows in data.values() for t, _, _ in rows})
    lab = {}
    for rows in data.values():
        for t, _, d in rows:
            lab.setdefault(t, d)
    obs = min((res[y]["lift"] if res[y]["lift"] is not None else -9) for y in data)
    hit = 0
    for _ in range(NPERM):
        vals = [lab[t] for t in allt]
        rnd.shuffle(vals)
        perm = dict(zip(allt, vals))
        worst = 9
        for yr, rows in data.items():
            l, _, _ = split_lift([(o, perm[t]) for t, o, _ in rows])
            worst = min(worst, l if l is not None else -9)
        if worst >= obs:
            hit += 1
    pval = (hit + 1) / (NPERM + 1)

    passed = all(res[y]["lift"] is not None and res[y]["lift"] >= LIFT_LINE for y in data) and pval < ALPHA
    out = dict(generated=__import__("time").strftime("%Y-%m-%d"),
               prereg="out/omega_retro_prereg.json",
               target="(tr_cagr > -0.15) and (fwd_roic_med5 >= 0.15)",
               WARN="合成は持続に縮退している（事前登録に明記）。『両方が効いた』と読まない",
               line=dict(lift=LIFT_LINE, alpha=ALPHA, perm=NPERM),
               H1=res, perm_p=round(pval, 4), H1_passed=bool(passed),
               stopping_rule="H1 が不合格なら H2/H3 はやらない（事前登録どおり）")
    json.dump(out, open(os.path.join(OUT, "omega_retro_test.json"), "w"),
              ensure_ascii=False, indent=1)

    print("=== H1: 現行の重みの Ω̂ は durable を当てるか（事前登録どおり一度だけ）===")
    for yr in sorted(res):
        r = res[yr]
        print(f"  {yr}: n={r['n']}（落ちた {r['dropped']}）  基礎率 {r['base']}"
              f"  上半分 {r['p_hi']} / 下半分 {r['p_lo']}  **lift {r['lift']}**")
    print(f"  置換p（会社単位・両ビンテージ同一置換・{NPERM}回）= {pval:.4f}")
    print(f"\n  判定: lift>={LIFT_LINE} を両ビンテージ ∧ p<{ALPHA}  → "
          + ("**合格**" if passed else "**不合格**"))
    if not passed:
        print("  ⇒ 停止規則により H2（重みの候補比較）・H3（ablation）は行わない。")
        print("  ⚠ 検出力は lift=0.15 で 0.672/0.853、**0.10 では 0.396/0.555**"
              "（事前登録に記録済み）＝『0.10 の効果は無い』とは書けない。")
    print("\n→ out/omega_retro_test.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
