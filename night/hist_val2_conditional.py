#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**条件付き**（自己相対が高い ∧ 事前に見えていた成長が付いてこない）を検定する（2026-08-10新設）

なぜこの器が要るか
------------------
night/hist_val_decompose.py が、自己相対が「効かない」理由を分解で説明した——
**倍率の平均回帰は実在する**（ρ(分位,倍率) は 3ビンテージ×4指標＝12組すべて負・
2018年 Q1 +5.27%/年 → Q5 −5.97%/年）のに、**事業の寄与がちょうど相殺している**
（ρ(分位,事業) は 12/12 が正）。入口で3.4倍あった倍率の差は出口で1.2倍まで縮み、
高倍率の社は倍率で損をするが、1株利益はその分だけ速く伸びた。

  ⇒ ならば「**倍率が高くて、しかも成長が付いてこない社**」だけを止めれば効くのでは？
     という条件付きの仮説が立つ。この器はそれを、v2 の主結果指標（元本割れ）で裁く。

格付け（正直に）——**これは確認的検定ではない**
----------------------------------------------
・分解の器は既にこの条件付けを**探索的に**見ており、「分位×事前成長という素朴な掛け合わせは
  **基準2を全セルで落とす**」と報告している。指標も閾値も既見である。
・事前登録v2 は、この条件付けを **『検定しないと決めたもの』** に明記して外した。
  理由は「既に反証済みの仮説を確認的検定として再登録しない」。
・したがってこの器の結果は **探索的**であり、合格しても遮断器の採用根拠にはしない。
  それでも回すのは、**分解が使った物差し（恒久毀損・中央値）では左尾の事象が薄すぎて
  『反証』が確定していなかった**からで、元本割れなら分子が足りる（下の reachability）。

格子は増やさない（多重検定を自分から増やさない）
------------------------------------------------
主判定は **分解が使ったのと同じ形**だけ:
    指標 = pe_pct（分解の conditional はこれ）
    倍率の閾値 = v1 の格子 0.80/0.85/0.90/0.95（**動かさない**）
    成長の側 = 事前に決まる3点だけ（EPS成長<プール中央 / EPS成長<0 / 売上成長<プール中央）
  ＝ **12セル/ビンテージ**。ps/pfcf/adj_pe は `--sensitivity` でのみ出し、**判定に数えない**。

成長は必ず ex-ante（look-ahead を構造で防ぐ）
--------------------------------------------
「成長が付いてこない」には二つの読みがある——
  (a) **asof の3年前→asof の実績成長が低い**（asof で知りうる＝遮断器にできる）… これを検定する
  (b) asof より後の成長が低い（**事後**＝遮断器にできない）… 検定しない
snapshot は `filed_le=asof` で切ってあるので、(a) は構造的に look-ahead を含まない。
そして分解は既に **ρ(事前3年EPS成長, 事後の事業の寄与) = +0.054 / −0.057 / −0.263** と実測している
——**事前の成長は事後の成長の代理にならない**。だから (a) が効かなくても (b) の否定にはならない。

欠測をゼロと読むな（絶対のルール7）
----------------------------------
成長が測れない社で条件は**発火しない**（＝通過側）。門の実装と同じ向きだが、件数を必ず別に数える。

実行:
  python3 night/hist_val2_conditional.py
  python3 night/hist_val2_conditional.py --sensitivity      # ps/pfcf/adj_pe も出す（判定外）
"""
import argparse
import json
import math
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

import hist_val_decompose as DEC                                          # noqa: E402
from hist_val_rev import load_vintage_checked, seen_revs                  # noqa: E402
from hist_val2_outcome import (GRID_PCT, LIFT, MIN_NUM, STOP_CAP,         # noqa: E402
                               check_prereg, stats, pools_for, reachable, judge)

VINTAGES = (2013, 2015, 2018)
LOOKBACK = {2013: "2010-08-01", 2015: "2012-08-01", 2018: "2015-08-01"}   # 分解と同じ（3年前）
PRIMARY_IND = "pe_pct"                     # 分解の conditional が使った指標。主判定はこれだけ
SENS_IND = ("ps_pct", "pfcf_pct", "adj_pe_pct")


def growth_map(vintage, offline=True):
    """{ticker: (g_eps3, g_rev3)}。**分解と同じスナップショット・同じ level()** を使う。

    二重実装を作らない——ここで成長を作り直すと、分解の報告と食い違ったときに
    どちらが正しいか決められなくなる（v9.9.65）。
    """
    items = DEC.universe()
    S0 = DEC.snapshot(f"{vintage}-07-01", "le_asof", items, offline, False, min_months=36)
    Sk = DEC.snapshot(LOOKBACK[vintage], "le_asof", items, offline, False)
    g = {}
    for t in {r["ticker"] for r in items}:
        L0, Lk = DEC.level(S0.get(t)), DEC.level(Sk.get(t))
        ge = gr = None
        if L0 and Lk and L0["eps"] > 0 and Lk["eps"] > 0:
            ge = math.log(L0["eps"] / Lk["eps"]) / 3.0
        if L0 and Lk and L0.get("rev") and Lk.get("rev"):
            gr = math.log(L0["rev"] / Lk["rev"]) / 3.0
        g[t] = (ge, gr)
    return g


def cell(pool, years, bench, key, thr, gsel, gname):
    """条件付きセル。**成長が測れない社では条件が発火しない**（通過側・件数を別に数える）。"""
    stop, pas, na_g = [], [], 0
    for r in pool:
        v = r.get(key)
        if v is None or v < thr:
            pas.append(r)
            continue
        # 倍率の条件は満たした。成長の側を見る
        ok, measurable = gsel(r)
        if not measurable:
            na_g += 1
            pas.append(r)          # 未測定は発火しない側（門の実装と同じ向き）
        elif ok:
            stop.append(r)
        else:
            pas.append(r)
    base = stats(pool, years, bench)
    ev = {"n_pool": len(pool), "n_stop": len(stop), "n_pass": len(pas), "n_na": 0,
          "n_growth_unmeasurable_among_high_multiple": na_g,
          "stop_rate_pool": round(len(stop) / len(pool), 4) if pool else None,
          "coverage": 1.0,
          "stopped": stats(stop, years, bench), "passed": stats(pas, years, bench),
          "base": base, "condition": f"{key}>={thr} ∧ {gname}"}
    ev["reach_loss"] = reachable(len(stop), base.get("n_loss", 0), base.get("p_loss") or 0)
    ev["reach_perm"] = reachable(len(stop), base.get("n_perm", 0), base.get("p_perm") or 0)
    return ev


def permutation(pool, years, bench, cells_def, n_perm, seed=20260810):
    """結果ラベルをプール内で並べ替え、**同じ格子ぜんぶ**を当てて偶然の当たりを数える。"""
    if not pool or n_perm <= 0:
        return None
    rng = random.Random(seed)
    idx = []
    for key, thr, gsel, gname in cells_def:
        si = []
        for i, r in enumerate(pool):
            v = r.get(key)
            if v is None or v < thr:
                continue
            ok, meas = gsel(r)
            if meas and ok:
                si.append(i)
        if si and len(si) < len(pool):
            idx.append(si)
    trs = [r.get("tr_cagr") for r in pool]
    hits = 0
    null_lift_med = []          # 帰無のもとでの「濃縮の中心」（セルの相関ごと再現する）
    for _ in range(n_perm):
        sh = trs[:]
        rng.shuffle(sh)
        nb = sum(1 for x in sh if x is not None and x < 0)
        base = nb / len(sh)
        got = False
        lifts = []
        for si in idx:
            ss = set(si)
            srs = [sh[i] for i in si if sh[i] is not None]
            prs = [sh[i] for i in range(len(sh)) if i not in ss and sh[i] is not None]
            if not srs or not prs or not base:
                continue
            nl = sum(1 for x in srs if x < 0)
            lifts.append((nl / len(srs)) / base)
            if (nl / len(srs) >= LIFT * base and nl >= MIN_NUM
                    and statistics.median(srs) <= statistics.median(prs)
                    and len(si) / len(pool) <= STOP_CAP):
                got = True
        hits += 1 if got else 0
        if lifts:
            null_lift_med.append(statistics.median(lifts))
    def pctl(xs, q):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4) if xs else None
    return {"n_perm": n_perm, "seed": seed, "n_cells": len(idx),
            "p_any_cell_passes_124": round(hits / n_perm, 4),
            # **セルは入れ子で強く相関する**ので「1.0未満が何セル」を符号検定に掛けてはいけない。
            # 帰無帯を置換で作り、実測がその中に落ちるかで「逆信号か・無関係か」を分ける。
            "null_lift_median": {"p05": pctl(null_lift_med, 0.05), "p50": pctl(null_lift_med, 0.50),
                                 "p95": pctl(null_lift_med, 0.95)}}


def main():
    ap = argparse.ArgumentParser(description="条件付き（高倍率 ∧ 成長が付いてこない）を元本割れで検定")
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val2_conditional.json"))
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--perm", type=int, default=2000)
    a = ap.parse_args()

    pre = check_prereg()
    print("■ 事前登録と照合 OK（倍率の格子=v1 ／ 基準・主結果指標=v2）")
    print("■ ★格付け: **探索的**。分解が既に同じ条件付けを見ており、v2 は『検定しない』と明記した。"
          "\n   合格しても遮断器の採用根拠にはしない（絶対のルール1/6）\n")

    out = {"generated": "2026-08-10", "tool": "night/hist_val2_conditional.py", "prereg": pre,
           "grade": ("探索的（confirmatory ではない）。指標・閾値ともに hist_val_decompose が既見。"
                     "事前登録v2 は本仮説を『検定しないと決めたもの』に明記して外している"),
           "growth_is_ex_ante": ("成長は asof の3年前→asof。スナップショットは filed_le=asof で切ってあるので"
                                 "look-ahead を構造で防ぐ。事後の成長は遮断器にできないので検定しない"),
           "primary_grid": {"indicator": PRIMARY_IND, "thresholds": list(GRID_PCT),
                            "growth_conditions": 3, "cells_per_vintage": len(GRID_PCT) * 3},
           "vintages": {}, "results": [], "permutation": {}}

    for y in VINTAGES:
        d = load_vintage_checked(y)
        years = d["join"]["modal_years"]
        bench = (d["join"].get("benchmark") or {}).get("tr_cagr")
        P = pools_for(d["rows"])
        G = growth_map(y)
        for r in d["rows"]:
            r["_g"] = G.get(r["ticker"], (None, None))

        pool = P["P_wide"]
        ge = [r["_g"][0] for r in pool if r["_g"][0] is not None]
        gr = [r["_g"][1] for r in pool if r["_g"][1] is not None]
        med_e = statistics.median(ge) if ge else None
        med_r = statistics.median(gr) if gr else None
        b = stats(pool, years, bench)
        out["vintages"][str(y)] = {
            "asof": d["asof"], "years": years, "n_pool": len(pool),
            "lookback_asof": LOOKBACK[y],
            "growth_coverage_eps": f"{len(ge)}/{len(pool)}",
            "growth_coverage_rev": f"{len(gr)}/{len(pool)}",
            "median_g_eps3_pct": round(100 * (math.exp(med_e) - 1), 2) if med_e is not None else None,
            "median_g_rev3_pct": round(100 * (math.exp(med_r) - 1), 2) if med_r is not None else None,
            "base": b}
        print("=" * 116)
        print(f"■ {y}年ビンテージ  n={len(pool)}（P_wide）  窓={years}年  "
              f"成長の被覆 EPS {len(ge)}/{len(pool)} / 売上 {len(gr)}/{len(pool)}")
        print(f"   ベース: 中央値 {b['median']:+.1%} / 等ウェイト {b['ew_cagr']:+.1%} / "
              f"元本割れ {b['p_loss']:.1%}({b['n_loss']}社) / 恒久毀損 {b['p_perm']:.2%}({b['n_perm']}社)")
        print(f"   事前3年成長の中央値: EPS {100*(math.exp(med_e)-1):+.1f}% / "
              f"売上 {100*(math.exp(med_r)-1):+.1f}%")

        # **欠測を先に見る**（None と数値を比べない・ルール7の実装上の形）。
        # 返すのは (条件を満たすか, そもそも測れたか) の2つ組。
        def g_lt(r, i, m):
            v = r["_g"][i]
            return (False, False) if v is None else (v < m, True)

        conds = [
            ("成長条件なし", lambda r: (True, True)),
            (f"∧ 事前3年EPS成長<中央({100*(math.exp(med_e)-1):.1f}%)",
             lambda r, m=med_e: g_lt(r, 0, m)),
            ("∧ 事前3年EPS成長<0", lambda r: g_lt(r, 0, 0.0)),
            (f"∧ 事前3年売上成長<中央({100*(math.exp(med_r)-1):.1f}%)",
             lambda r, m=med_r: g_lt(r, 1, m)),
        ]
        keys = [PRIMARY_IND] + (list(SENS_IND) if a.sensitivity else [])
        print(f"     {'指標':<11}{'閾値':>5}  {'成長条件':<34}{'止':>5}{'止率':>7}"
              f"{'止:中央':>9}{'止:等W':>9}{'通:中央':>9}{'止:元本割れ':>14}{'濃縮':>7}"
              f"  {'到達':>4}{'1':>2}{'2':>2}{'4':>2}")
        cdefs = []
        for key in keys:
            for thr in GRID_PCT:
                for gname, gsel in conds:
                    ev = cell(pool, years, bench, key, thr, gsel, gname)
                    jl = judge(ev, "loss")
                    prim = (key == PRIMARY_IND and gname != "成長条件なし")
                    rec = {"vintage": y, "pool": "P_wide", "indicator": key, "threshold": thr,
                           "growth_condition": gname, "primary": prim,
                           "unconditional_reference": gname == "成長条件なし",
                           "ev": ev, "judge_loss": jl, "judge_perm": judge(ev, "perm")}
                    out["results"].append(rec)
                    if prim:
                        cdefs.append((key, thr, gsel, gname))
                    st, pa = ev["stopped"], ev["passed"]
                    if jl.get("c1") is None:
                        print(f"     {key:<11}{thr:>5}  {gname:<34}{ev['n_stop']:>5}"
                              f"   —— 判定不能")
                        continue
                    mk = lambda x: "✓" if x else "✗"
                    star = "★" if prim else " "
                    print(f"    {star}{key:<11}{thr:>5}  {gname:<34}{ev['n_stop']:>5}"
                          f"{ev['stop_rate_pool']:>7.1%}{st['median']:>+9.1%}"
                          f"{st['ew_cagr']:>+9.1%}{pa['median']:>+9.1%}"
                          f"{st['p_loss']:>10.1%}({st['n_loss']:>2}){jl['c1_ratio']:>7.2f}"
                          f"  {mk(jl['reachable']):>4}{mk(jl['c1']):>2}{mk(jl['c2']):>2}"
                          f"{mk(jl['c4']):>2}")
        pr = permutation(pool, years, bench, cdefs, a.perm)
        if pr:
            out["permutation"][str(y)] = pr

    # ── 横断（基準3）── 主判定セルだけ
    agg = {}
    for r in out["results"]:
        if not r["primary"]:
            continue
        k = (r["indicator"], r["threshold"], r["growth_condition"].split("(")[0])
        j = r["judge_loss"]
        agg.setdefault(k, {"indicator": k[0], "threshold": k[1], "growth_condition": k[2],
                           "vint": {}, "n_ok12": 0})
        agg[k]["vint"][r["vintage"]] = {"c1": j.get("c1"), "c2": j.get("c2"), "c4": j.get("c4"),
                                        "ratio": j.get("c1_ratio"), "numer": j.get("c1_numer")}
        if j.get("c1") and j.get("c2"):
            agg[k]["n_ok12"] += 1
    passing = []
    for v in agg.values():
        c4s = [x["c4"] for x in v["vint"].values() if x["c4"] is not None]
        v["c3"] = v["n_ok12"] >= 2
        v["c4_all"] = all(c4s) if c4s else None
        v["all_pass"] = bool(c4s and v["c3"] and v["c4_all"])
        if v["all_pass"]:
            passing.append(v)
    out["aggregate"] = list(agg.values())
    out["passing_rules"] = passing

    print("\n" + "=" * 116)
    print("■ 横断（主判定セルのみ・pe_pct × 4閾値 × 3成長条件）")
    print(f"   {'閾値':>5}  {'成長条件':<34}{'1∧2のV数':>10}{'基準3':>7}{'基準4':>7}{'全合格':>7}")
    for v in sorted(out["aggregate"], key=lambda x: (x["threshold"], x["growth_condition"])):
        m4 = "判定不能" if v["c4_all"] is None else ("✓" if v["c4_all"] else "✗")
        print(f"   {v['threshold']:>5}  {v['growth_condition']:<34}{v['n_ok12']:>10}"
              f"{('✓' if v['c3'] else '✗'):>7}{m4:>7}{('✓' if v['all_pass'] else '✗'):>7}")
    print(f"\n■ 基準1〜4をすべて満たす条件付きの規則: **{len(passing)}件**")

    R = [r for r in out["results"] if r["primary"] and r["judge_loss"].get("c1") is not None]
    if R:
        lifts = [r["judge_loss"]["c1_ratio"] for r in R]
        gaps = [r["judge_loss"]["c2_gap"] for r in R]
        out["summary"] = {
            "n_primary_cells": len(R),
            "c1_pass": sum(1 for r in R if r["judge_loss"]["c1"]),
            "c2_pass": sum(1 for r in R if r["judge_loss"]["c2"]),
            "c4_pass": sum(1 for r in R if r["judge_loss"]["c4"]),
            "reachable": sum(1 for r in R if r["judge_loss"].get("reachable")),
            "lift_median": round(statistics.median(lifts), 3),
            "lift_max": round(max(lifts), 3), "lift_below_1": sum(1 for x in lifts if x < 1.0),
            "c2_gap_median": round(statistics.median(gaps), 4),
            "c2_gap_positive": sum(1 for g in gaps if g > 0)}
        s = out["summary"]
        print(f"\n■ 外れ方（主判定セル {s['n_primary_cells']}個）")
        print(f"   到達可能 {s['reachable']}/{s['n_primary_cells']} ／ "
              f"基準1 {s['c1_pass']} ／ 基準2 {s['c2_pass']} ／ 基準4 {s['c4_pass']}")
        print(f"   濃縮の中心 {s['lift_median']:.2f}倍（最大 {s['lift_max']:.2f}・要求2.0倍）／ "
              f"1.0未満 {s['lift_below_1']}/{s['n_primary_cells']}"
              f"  ※逆信号と読まないこと（下の帰無帯を見よ）")
        print(f"   基準2の差の中央 {s['c2_gap_median']:+.4f}／正だったセル "
              f"{s['c2_gap_positive']}/{s['n_primary_cells']}（正＝勝者を巻き込む）")

    if out["permutation"]:
        print("\n■ 多重検定（結果ラベルを並べ替え・主判定の12セル）")
        for y, p in out["permutation"].items():
            lf = [r["judge_loss"]["c1_ratio"] for r in out["results"]
                  if r["primary"] and str(r["vintage"]) == str(y)
                  and r["judge_loss"].get("c1_ratio") is not None]
            obs = round(statistics.median(lf), 3) if lf else None
            nl = p["null_lift_median"]
            inside = obs is not None and nl["p05"] <= obs <= nl["p95"]
            p["observed_lift_median"] = obs
            p["observed_lift_inside_null_band"] = bool(inside)
            print(f"   {y}: {p['n_cells']}セル → 偶然に1セルでも通る確率 "
                  f"**{p['p_any_cell_passes_124']:.3f}**  ／ 濃縮の中心 実測 {obs} vs "
                  f"帰無帯 [{nl['p05']:.2f}, {nl['p95']:.2f}] → "
                  f"{'**帯の中**' if inside else '帯の外'}")

    out["src_tool_rev"] = seen_revs()
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n■ 在庫: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
