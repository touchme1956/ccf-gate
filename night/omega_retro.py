#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro.py — Ω を歴史のビンテージで再構成して重みを検定する（2026-08-14新設）

■ 何のための器か
  ユーザー指示「Ωの採点を変えたい。本当に歴史的に最もよいスコアをつけれるように修正できない？」。
  **この台帳は Ω を一度も歴史で検証していない**——v12 の条件5 が「検定不能（歴史に dom/dur/moatW/Ω が無い）」
  で落ちたのはそのため。だが 2026-08-12 の rep/dur 読解（2013 249社 / 2015 505社）で**堀5本が歴史側に揃った**ので、
  機械項目と合わせれば **Ω̂（近似Ω）を歴史のビンテージで組める**。これはその最初の一歩。

■ ★当てる先（ユーザーが選択: 「両方の合成（壊れない ∧ 持続）」）
  `durable = (実現年率 > −15%) ∧ (前方ROIC中央値 ≥ 15%)`
  **新しい定数を一つも作っていない**——−15% は既存の恒久毀損の線、15% は既存のハードル兼 門0の一次ふるい。

  ⚠⚠ **測る前に判った縮退。結果を見る前にここへ書く**——
  実測で **持続を満たす社は、ほぼ全部が壊れない側**（2013: 48/48・2015: 101/102）。
  つまり **合成は事実上 `持続` 単独に縮退する**。よってこの検定が測るのは
  「Ω̂ が**持続**を当てるか」であって、「壊れない側も当てるか」は**この標本では測れない**。
  後から「合成が効いた」を「両方が効いた」と読まないこと。
  ⚠ 逆に言えば **『事業の質が持続した社は株価でも壊れなかった』（150社中149社）** 自体が実測の発見で、
  門の思想（壊れない複利）と整合する。だが**それは仮説の検証ではなく、標本の性質**である。

■ なぜリターンを当てる先にしないか（結果を見る前の決定）
  `out/retro_persistence.json` の実測: 4つの重ならない窓の当選分布は**独立抽選と一致**（比 0.99〜1.05）、
  ICC **0.054**、前半勝ち→後半勝ちの lift **−0.039**。そして決定的に——
  **他の3窓の「実現リターンそのもの」で選んでも当たらない（×0.84〜1.12）**。
  どんな指標より強い情報で当たらない以上、**指標の重みで当てることは原理的にできない**。
  ここを目標にすると見つかる重みは必ず雑音（in-sample 最良が out-of-sample で崩れた実例が6回）。

■ 使い方
  python3 night/omega_retro.py --reach      到達可能性と検出力（**仮説を覗かずに測れる部分だけ**）
出力: out/omega_retro_reach.json
"""
import itertools
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")

# --- 当てる先の定数（どちらも既存・新設していない） ---
BREAK = -0.15      # 恒久毀損の線（既存）
FWD_ROIC = 0.15    # 持続の線（既存のハードル＝門0の一次ふるいと同じ数）
MOAT_MIN_LEGS = 4  # 門の堀指数が要求する下限（5本中4本）

VINTAGES = {
    2013: dict(irr=["out/retro_moat_2013.json", "out/retro_moat_2013q.json"],
               pil="out/retro_moat_pillars_2013.json",
               coh="out/retro_cohort_2013.json",
               ret="out/retro_returns_2013_all.json"),
    2015: dict(irr=["out/retro_moat_2015.json", "out/retro_moat_2015q.json",
                    "out/retro_moat_2015qb.json"],
               pil="out/retro_moat_pillars_2015.json",
               coh="out/retro_cohort_2015.json",
               ret="out/retro_returns_2015_q.json"),
}


def load(f):
    d = json.load(open(f, encoding="utf-8"))
    r = d.get("items") or d.get("rows") or d
    return list(r.values()) if isinstance(r, dict) else r


def key(x):
    return x.get("ticker") or x.get("t")


def gather(year):
    """その年のビンテージで Ω̂ を組める社と、その結果を集める。**判定は作らない**。"""
    v = VINTAGES[year]
    irr = {}
    for f in v["irr"]:
        for x in load(f):
            if x.get("irr") is not None:
                irr[key(x)] = x["irr"]
    P = {key(x): x for x in load(v["pil"])}
    C = {key(x): x for x in load(v["coh"])}
    R = {key(x): x for x in load(v["ret"])}
    rows = []
    for t, p in P.items():
        legs = {k: p.get(k) for k in ("dom", "rep", "dur", "moatW")}
        legs["irr"] = irr.get(t)
        n_legs = sum(1 for x in legs.values() if x is not None)
        tr = (R.get(t) or {}).get("tr_cagr")
        fw = (C.get(t) or {}).get("fwd_roic_med5_a1")
        rows.append(dict(t=t, legs=legs, n_legs=n_legs, tr=tr, fwd_roic=fw,
                         mach=bool(C.get(t))))
    return rows


def power(n, base, lift, alpha=0.05, cut=0.5):
    """止める側 K=n*cut として、lift を検出できる確率（片側・正規近似）。
    ⚠ 検出力は**結果を見る前に**出す（v3 の教訓——出していれば設計し直せた）。"""
    k = max(1, int(round(n * cut)))
    m = n - k
    if m < 1:
        return None
    p1, p0 = min(0.999, base + lift * (m / n)), max(0.001, base - lift * (k / n))
    se = math.sqrt(p1 * (1 - p1) / k + p0 * (1 - p0) / m)
    if se <= 0:
        return None
    z = (p1 - p0 - 0.0) / se
    # 片側 alpha の臨界値 1.645 を超える確率
    return 0.5 * (1 + math.erf((z - 1.645) / math.sqrt(2)))


def main():
    if "--reach" not in sys.argv:
        print(__doc__)
        return 0
    out = {
        "generated": __import__("time").strftime("%Y-%m-%d"),
        "target": {"formula": "(tr_cagr > -0.15) and (fwd_roic_med5 >= 0.15)",
                   "why_no_returns": "retro_persistence: 実現リターンそのもので選んでも×0.84〜1.12＝上限が無い",
                   "constants_are_existing": True},
        "vintages": {},
    }
    for yr in sorted(VINTAGES):
        rows = gather(yr)
        ok = [r for r in rows if r["n_legs"] >= MOAT_MIN_LEGS]
        jd = [r for r in ok if r["tr"] is not None and r["fwd_roic"] is not None]
        nb = sum(1 for r in jd if r["tr"] > BREAK)
        nd = sum(1 for r in jd if r["fwd_roic"] >= FWD_ROIC)
        both = sum(1 for r in jd if r["tr"] > BREAK and r["fwd_roic"] >= FWD_ROIC)
        n = len(jd)
        base = both / n if n else None
        pw = {f"lift={l:.2f}": (None if not n else round(power(n, base, l), 3))
              for l in (0.05, 0.10, 0.15, 0.20, 0.25)}
        out["vintages"][yr] = dict(
            read=len(rows), moat_ok=len(ok), judgeable=n,
            n_not_broken=nb, n_durable=nd, n_both=both,
            base_not_broken=round(nb / n, 4) if n else None,
            base_durable=round(nd / n, 4) if n else None,
            base_both=round(base, 4) if n else None,
            degenerate_durable_minus_both=nd - both,
            power=pw)
        print(f"■ {yr} ビンテージ")
        print(f"  読解 {len(rows)}社 → 堀{MOAT_MIN_LEGS}本以上 {len(ok)}社 → 結果もそろう {n}社")
        print(f"  壊れない(>{BREAK:+.0%}/年) {nb} ({nb/n:.3f}) ／ 持続(前方ROIC≥{FWD_ROIC:.0%}) {nd} ({nd/n:.3f})")
        print(f"  ★合成（当てる先） {both} ({base:.3f})　⚠縮退: 持続かつ壊れた社 = {nd-both}社")
        print(f"  検出力: " + " / ".join(f"{k} {v}" for k, v in pw.items()))
    json.dump(out, open(os.path.join(OUT, "omega_retro_reach.json"), "w"),
              ensure_ascii=False, indent=1)
    print("\n→ out/omega_retro_reach.json")
    print("⚠ ここまでは**仮説を覗いていない**（Ω̂ と結果をまだ突き合わせていない）。"
          "事前登録をコミットしてから初めて突き合わせる。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
