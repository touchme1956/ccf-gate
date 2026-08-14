#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro_test.py — 事前登録どおりに Ω̂ を一度だけ裁く（2026-08-14新設・同日 --src で一般化）

■ 事前登録は out/omega_retro_prereg.json（**Ω̂ と結果を一度も突き合わせる前に**コミット済み）
  この器は**そこに書いた判定をそのまま実行するだけ**。基準をここで書き足さない。

■ ★なぜ --src で一つの器にまとめたか（v9.9.65 の掟）
  案B は inline で撃った。案A を別の inline で撃つと、**同じ問いに二つの実装**ができて
  「同じ台帳を見る二つの検査器が違うことを言う」型を自分で作る。
  → 器を一つにし、**まず B を通して out/omega_retro_testB.json を再現できることを確かめてから** A を撃つ。

■ H1（主判定・これが不合格なら H2/H3 はやらない＝停止規則）
  Ω̂ は durable を当てるか。
  判定: Ω̂ 上半分と下半分の P(durable) の差 lift >= 0.15 ∧ 置換p < 0.05 を **両ビンテージで**満たす

■ 当てる先（新しい定数を作っていない）
  durable = (実現年率 tr_cagr > -0.15) AND (前方ROIC中央値 >= 0.15)
  ⚠ 事前登録に書いたとおり **合成は事実上「持続」に縮退している**（2013: 48/48・2015: 101/102）。
    この検定が測るのは「Ω̂ が持続を当てるか」だけ。「両方が効いた」と読んではならない。

■ 置換の作り方（2026-08-12 に33倍の過小評価を踏んだ型を再演しない）
  結果ラベルを**会社単位で**並べ替え、**両ビンテージに同じ置換を当てる**
  ——アンカー間の相関を壊さないため。ビンテージ内で独立に混ぜると帰無が緩くなる。

使い方: python3 night/omega_retro_test.py --src A|B|omega
出力:   out/omega_retro_test{A|B|}.json
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

# src → (Ω̂ の在庫, Ω̂ の欄名, 覆う範囲の注記)
SRC = {
    "A": ("out/omega_retro_A_{yr}.json", "omega",
          "案A: 門の compute() に p1/p2/p4 を機械導出で足した Ω̂。"
          "**Ω ではない**——f1/f2/f3/f4 と now の価格項を依然欠く"),
    "B": ("out/omega_retro_B_{yr}.json", "omegaB",
          "案B: Ω_B = gm([sustain, moat],[.30,.13]/.43)＝**Ωの名目重みの43%**。Ω ではない"),
    "omega": ("out/omega_retro_omega_{yr}.json", "omega",
              "★判断項目が全社空欄の壊れた instrument（AMENDMENT 参照）。撃ってはならない"),
}


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
    src = "A"
    if "--src" in sys.argv:
        src = sys.argv[sys.argv.index("--src") + 1]
    if src not in SRC:
        sys.exit(f"--src は {'/'.join(SRC)} のどれか")
    tmpl, fld, scope = SRC[src]

    data, missing = {}, {}
    for yr in (2013, 2015):
        p = os.path.join(BASE, tmpl.format(yr=yr))
        if not os.path.exists(p):
            sys.exit(f"{p} が無い")
        O = json.load(open(p, encoding="utf-8"))["items"]
        R = {key(x): x for x in load(RET[yr])}
        C = {key(x): x for x in load(COH[yr])}
        rows, ng = [], 0
        for t, o in O.items():
            tr = (R.get(t) or {}).get("tr_cagr")
            fw = (C.get(t) or {}).get("fwd_roic_med5_a1")
            om = o.get(fld)
            if tr is None or fw is None or om is None:
                ng += 1
                continue
            rows.append((t, float(om), bool(tr > BREAK and fw >= FWD)))
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
               prereg="out/omega_retro_prereg.json", src=src, scope=scope,
               target="(tr_cagr > -0.15) and (fwd_roic_med5 >= 0.15)",
               WARN="合成は持続に縮退している（事前登録に明記）。『両方が効いた』と読まない",
               line=dict(lift=LIFT_LINE, alpha=ALPHA, perm=NPERM),
               H1=res, perm_p=round(pval, 4), H1_passed=bool(passed),
               stopping_rule="H1 が不合格なら H2/H3 はやらない（事前登録どおり）")
    q = os.path.join(OUT, f"omega_retro_test{src if src != 'omega' else ''}.json")
    json.dump(out, open(q, "w"), ensure_ascii=False, indent=1)

    print(f"=== H1_{src}: Ω̂ は durable を当てるか（事前登録どおり一度だけ）===")
    print(f"  範囲: {scope}")
    for yr in sorted(res):
        r = res[yr]
        print(f"  {yr}: n={r['n']}（落ちた {r['dropped']}）  基礎率 {r['base']}"
              f"  上半分 {r['p_hi']} / 下半分 {r['p_lo']}  **lift {r['lift']}**")
    print(f"  置換p（会社単位・両ビンテージ同一置換・{NPERM}回）= {pval:.4f}")
    print(f"\n  判定: lift>={LIFT_LINE} を両ビンテージ ∧ p<{ALPHA}  → "
          + ("**合格**" if passed else "**不合格**"))
    if not passed:
        print("  ⇒ 停止規則により H2（重みの候補比較）・H3（ablation）は行わない。")
    print("  ⚠ 検出力は lift=0.15 で 0.67/0.85、**0.10 では 0.40/0.55**"
          "（事前登録に記録済み）＝『0.10 の効果は無い』とは書けない。")
    print(f"\n→ {os.path.relpath(q, BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
