#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_dst_uni.py — 破壊側（目的B: P(tr_cagr <= -15%)）の単変量探索。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル。特徴量も outcome も再実装しない・v9.9.65）
出力    : out/hist_wd_dst_uni.json

W1（night/hist_wd_win_uni.py・目的A）と**同じ手続き**を、結果ラベルだけ win→destroy に替えて当てる。
「勝者側で効かなかった変数が破壊側で効く可能性」を、先入観なしに測るための対称探索。

────────────────────────────────────────────────────────────
★ この道具でいちばん重要なのは、結果ではなく「結果を見る前に数えたこと」
────────────────────────────────────────────────────────────
破壊は**稀事象**（実測 base: P_full 1.8-8.1% / P_quality 1.2-3.0% / P_moat 0-1.6%）。
一方 prereg の線は **絶対リスク差** |P(群) - P(母集団)| >= 0.15。この二つを突き合わせると:

 (1) **守る向き（破壊を避ける群）は全セルで数学的に不可能。**
     p_group >= 0 なので負の lift の絶対値は base を超えられない。base の最大は 0.081 < 0.15。
     ＝「保護的な指標は見つからなかった」ではなく「**この線では原理的に見つけられない**」。

 (2) **中央値切りは全セルで不可能。** 群が n/2 なので、必要な分子が総事象数を超える。

 (3) 四分位×攻める向きだけが、**P_full の一部**でようやく到達可能。しかもその条件は
     「**全破壊事象の 71〜98% を、たった一つの四分位に集める**」こと。

これは hist_valuation v1 の教訓——『合否基準が母集団の稀少事象の実数で到達可能かを結果を見る前に数える』
——の破壊側での再演であり、prereg 自身が must_report_before_verdict に書いている項目そのもの。
**だから「合格ゼロ」を『効果が無い』と読んではいけない。**大半のセルは不合格ではなく判定不能。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定（W1 と揃えてある。揃えることが目的）
────────────────────────────────────────────────────────────
1) 解析集合は has_outcome ∧ window_full（短窓は年率換算で両裾を機械的に膨らませる。
   破壊側では**とくに効く**——短窓は destroy を過大に作るので、入れると事象数が水増しされる）。
2) lift の分母は prereg literal どおり population 全体。可測部分集合を分母にした版も併記（診断）。
3) 名前空間 f2_/co_/pa_/hv_/per を混ぜない。概念の対は「並べる」だけで繋がない。
4) 必須ゲート（2016/2017/2018 の符号不変）を当てられない変数は、結果の前から構造的に判定不能。
5) タイの扱い・低カーディナリティの値別集計は W1 と同一。
6) FPR は「特徴量側を固定し outcome の束をティッカーごと置換」＝ビンテージ間相関・欠測構造を保つ。
7) 検出力は上下で挟む（3ビンテージ独立＝下限／単一ビンテージ＝上限）。

★8) **W1 との一致検査を道具の中に入れてある**（cross_check_vs_win_tool）。
   同じパネルを読む二つの検査器が違うことを言ってはいけない(v9.9.65)——
   これは約束ではなく**検査**にしてある。この道具の measure() に outcome="win" を渡し、
   W1 の committed 出力 out/hist_wd_win_uni.json と数字が一致するかを毎回突き合わせる。

★9) **相対リスク(RR)は「事前登録の外・診断専用」として別に出す。**
   稀事象の自然な物差しは差ではなく比で、絶対差の線は(1)(2)(3)のとおり構造的に通らない。
   だが**線は動かさない**（prereg の stopping_rule）。RR は合否に一切数えず、
   「事前登録の外」と明示したうえで、次に線を引き直す人のための材料として残す。
"""
import json, os, math, random
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
WIN_JSON = os.path.join(OUT, "hist_wd_win_uni.json")     # 一致検査の相手
DEST = os.path.join(OUT, "hist_wd_dst_uni.json")

# ─── prereg の線（この道具は一つも作らない・読むだけ） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]

SEED = 20260811
N_PERM = 2000
N_POWER = 5000

OUTCOME = "destroy"        # ← W1 との唯一の違い

# ─── 候補（prereg の candidates をそのまま。irr/moat5/dom18/mech は対照専用＝除外） ───
F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r", "gw_r",
      "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5", "conv5", "netiss_r",
      "payout5", "rev"]
CO = ["roic_med5", "roic_latest", "roic_worst5", "opm", "sales_cagr5", "fcf_conv_5y",
      "op_all_pos", "fcf_all_pos", "equity_neg", "score", "rev_asof"]
PA = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
HV = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_z", "ps_z"]

CANDIDATES = (["f2_" + f for f in F2] + ["co_" + f for f in CO] + ["pa_" + f for f in PA]
              + ["hv_" + f for f in HV] + ["per", "size_rev"])

# 指示で「破壊側の仮説として筋が良い」と名指しされた群。
# ⚠ **筋の良さで結論を先取りしないため、測定は全候補に同じ手続きを当てる。**
# ここに挙げるのは「後から都合よく選んだのではない」ことを示すための事前の明示であって、
# 特別扱い（別の線・別の検定）は一切していない。
NAMED_HYPOTHESES = {
    "財務の脆さ": ["f2_intcov", "f2_cash_r", "f2_netiss_r"],
    "会計の質": ["f2_accr", "f2_conv5"],
    "利益率の崩れ": ["f2_opmD5", "f2_streak_opm"],
    "買収": ["f2_gw_r"],
}
NAMED_FLAT = [v for g in NAMED_HYPOTHESES.values() for v in g]

CONCEPT_PAIRS = [
    ("営業利益率",        {2013: "co_opm", 2015: "co_opm", 2016: "f2_opm", 2017: "f2_opm", 2018: "f2_opm"}),
    ("売上5年CAGR",       {2013: "co_sales_cagr5", 2015: "co_sales_cagr5", 2016: "f2_cagr5", 2017: "f2_cagr5", 2018: "f2_cagr5"}),
    ("FCF転換(5年)",      {2013: "co_fcf_conv_5y", 2015: "co_fcf_conv_5y", 2016: "f2_conv5", 2017: "f2_conv5", 2018: "f2_conv5"}),
    ("FCF全年黒字",       {2013: "co_fcf_all_pos", 2015: "co_fcf_all_pos", 2016: "f2_fcfpos5", 2017: "f2_fcfpos5", 2018: "f2_fcfpos5"}),
    ("規模(売上)",        {2013: "size_rev", 2015: "size_rev", 2016: "size_rev", 2017: "size_rev", 2018: "size_rev"}),
]
CONCEPT_PAIR_WARNING = ("co_(2013/2015) と f2_(2016/2017/2018) は別のパイプラインの別の量。"
                        "符号の向きを見るためだけに並べてあり、一つの変数として lift を通時比較してはいけない。"
                        "FCF全年黒字だけは定義も違う（co_ は bool・f2_fcfpos5 は 0-5 の年数）。")


# ────────────────────────────── 小道具（W1 と同一） ──────────────────────────────
def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        idx = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    numr = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return numr / (dx * dy)


def q_at(sorted_vals, q):
    n = len(sorted_vals)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))
    return sorted_vals[k - 1]


def num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


def rate(k, n):
    return (k / n) if n else None


def r4(x):
    return None if x is None else round(x, 4)


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
rows_all = panel["rows"]

ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]
by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)


def pop_rows(v, pop):
    return [r for r in by_v[v] if r.get(pop)]


# ─────────── 結果を見る前に出す(1): ゲート自体の到達可能性 ───────────
var_vintage_cov = {}
for var in CANDIDATES:
    cov = {}
    for v in ALL_VINTAGES:
        R = by_v.get(v, [])
        k = sum(1 for r in R if num(r.get(var)) is not None)
        cov[v] = {"n_rows": len(R), "n_measurable": k, "share": r4(rate(k, len(R)))}
    have3 = all(cov[v]["n_measurable"] > 0 for v in SIGN_VINTAGES)
    var_vintage_cov[var] = {
        "coverage": cov,
        "sign_gate_evaluable": have3,
        "all5_vintages": all(cov[v]["n_measurable"] > 0 for v in ALL_VINTAGES),
        "gate_note": ("2016/2017/2018 すべてに在る＝符号不変ゲートを当てられる" if have3
                      else "2016/2017/2018 のどれかに存在しない＝符号不変ゲートは構造的に判定不能"),
    }
gate_reachable = [k for k, v in var_vintage_cov.items() if v["sign_gate_evaluable"]]
gate_unreachable = [k for k, v in var_vintage_cov.items() if not v["sign_gate_evaluable"]]


# ─────────── 結果を見る前に出す(2): 破壊側の「線そのものの到達可能性」 ───────────
# ★ここがこの道具の核心。稀事象 × 絶対リスク差の線 は、群サイズごとに上限が決まる。
def attainability(n, E, g):
    """群サイズ g のとき、絶対リスク差の線 0.15 に届きうるか（両方向）。"""
    if n == 0 or g == 0:
        return None
    base = E / n
    # 攻める向き: 群へ集められる事象は最大 min(g, E)
    max_pos = min(g, E) / g - base
    need_k_lift = math.ceil((base + LIFT) * g)
    need_k = max(need_k_lift, MIN_NUM)
    pos_ok = need_k <= min(g, E)
    # 守る向き: p_group の下限は 0 なので、負の lift の絶対値は base を超えられない
    max_neg = base
    neg_ok = base >= LIFT
    return {
        "group_n": g,
        "base": r4(base),
        "positive_direction": {
            "max_attainable_lift": r4(max_pos),
            "k_needed_by_lift": need_k_lift,
            "k_needed_by_min_num": MIN_NUM,
            "binding": ("LIFT" if need_k_lift >= MIN_NUM else "MIN_NUM"),
            "k_needed": need_k,
            "events_total": E,
            "share_of_all_events_required": (r4(need_k / E) if E else None),
            "attainable": pos_ok,
            "why": (None if pos_ok else
                    (f"全{E}事象を群へ集めても lift は最大 {max_pos:.4f} で 0.15 に届かない"
                     if min(g, E) / g - base < LIFT else
                     f"必要な分子 {need_k} が総事象数 {E} を超える")),
        },
        "protective_direction": {
            "max_attainable_abs_lift": r4(max_neg),
            "attainable": neg_ok,
            "why": (None if neg_ok else
                    f"p_group>=0 ゆえ負のlift の絶対値は base({base:.4f}) を超えられない＝0.15 に構造的に届かない"),
        },
    }


cell_reach = {}
for v in ALL_VINTAGES:
    for pop in POPS:
        R = pop_rows(v, pop)
        n = len(R)
        E = sum(1 for r in R if r.get(OUTCOME))
        ent = {"n": n, "events_destroy": E, "base": r4(rate(E, n)),
               "events_win_for_reference": sum(1 for r in R if r.get("win"))}
        if n == 0:
            ent["verdict"] = "母集団が空＝判定不能"
        elif E < MIN_NUM:
            ent["verdict"] = f"事象{E}件<5＝どの部分群でも分子5に届かない＝判定不能"
            ent["quartile"] = attainability(n, E, max(1, n // 4))
            ent["median"] = attainability(n, E, max(1, n // 2))
        else:
            ent["quartile"] = attainability(n, E, max(1, n // 4))
            ent["median"] = attainability(n, E, max(1, n // 2))
            any_ok = (ent["quartile"]["positive_direction"]["attainable"]
                      or ent["quartile"]["protective_direction"]["attainable"]
                      or ent["median"]["positive_direction"]["attainable"]
                      or ent["median"]["protective_direction"]["attainable"])
            ent["verdict"] = ("到達可能（四分位・攻める向きのみ）" if any_ok
                              else "どの切り方・どの向きでも線に届かない＝判定不能")
        cell_reach[f"{v}/{pop}"] = ent

# 到達可能性の総括（結果の前に）
reach_summary = {
    "cells_total": len(cell_reach),
    "cells_population_empty": sum(1 for e in cell_reach.values() if e["n"] == 0),
    "cells_events_below_min_num": sum(1 for e in cell_reach.values()
                                      if e["n"] > 0 and e["events_destroy"] < MIN_NUM),
    "cells_quartile_positive_attainable": sorted(
        k for k, e in cell_reach.items()
        if e.get("quartile") and e["quartile"]["positive_direction"]["attainable"]),
    "cells_quartile_protective_attainable": sorted(
        k for k, e in cell_reach.items()
        if e.get("quartile") and e["quartile"]["protective_direction"]["attainable"]),
    "cells_median_any_attainable": sorted(
        k for k, e in cell_reach.items()
        if e.get("median") and (e["median"]["positive_direction"]["attainable"]
                                or e["median"]["protective_direction"]["attainable"])),
}
reach_summary["headline"] = (
    "破壊は稀事象（base 0.9-8.1%）で、prereg の線は絶対リスク差 0.15。"
    f"守る向きは全{reach_summary['cells_total']}セルで数学的に不可能（負のlift の上限が base 自身）。"
    "中央値切りも全セルで不可能。"
    f"到達可能なのは四分位×攻める向きの {len(reach_summary['cells_quartile_positive_attainable'])} セルのみ: "
    + ", ".join(reach_summary["cells_quartile_positive_attainable"])
    + "。しかもそれぞれ全破壊事象の 71-98% を一つの四分位へ集める必要がある。"
    "**したがって『合格ゼロ』は『効果が無い』ではなく、大半が『判定不能』である。**")


# ────────────────────────────── 中核: 1セルの測定 ──────────────────────────────
def measure(v, pop, var, outcome=OUTCOME):
    """(vintage, population, variable) を測る。判定はしない（数字だけ返す）。

    outcome を差し替えられるのは W1 との一致検査のためだけ（既定は destroy）。
    """
    R = pop_rows(v, pop)
    n_pop = len(R)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in R if r.get(outcome))
    p_pop = rate(k_pop, n_pop)

    M = [(num(r.get(var)), 1 if r.get(outcome) else 0) for r in R]
    M = [(x, w) for (x, w) in M if x is not None]
    n_m = len(M)
    if n_m == 0:
        return {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": 0,
                "status": "この母集団でこの変数は一つも測れない＝判定不能"}
    k_m = sum(w for (_, w) in M)
    p_m = rate(k_m, n_m)

    n_miss = n_pop - n_m
    k_miss = k_pop - k_m
    p_miss = rate(k_miss, n_miss) if n_miss else None

    vals = sorted(x for (x, _) in M)
    distinct = len(set(vals))
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)

    def grp(pred):
        g = [(x, w) for (x, w) in M if pred(x)]
        return len(g), sum(w for _, w in g)

    cuts = {}
    defs = [
        ("上位1/4", lambda x: x >= q75, f"値 >= {q75!r}(75%点)"),
        ("下位1/4", lambda x: x <= q25, f"値 <= {q25!r}(25%点)"),
        ("中央値超", lambda x: x > q50, f"値 > {q50!r}(中央値)"),
        ("中央値以下", lambda x: x <= q50, f"値 <= {q50!r}(中央値)"),
    ]
    for name, pred, desc in defs:
        gn, gk = grp(pred)
        gp = rate(gk, gn)
        ent = {
            "cut": desc, "n_group": gn, "numerator": gk, "p_group": r4(gp),
            "lift_vs_pop": r4(None if gp is None else gp - p_pop),
            "lift_vs_measurable": r4(None if gp is None else gp - p_m),
            # ── 事前登録の外・診断専用: 稀事象の自然な物差し ──
            "rr_vs_pop": (r4(gp / p_pop) if (gp is not None and p_pop) else None),
        }
        if gn:
            share = gn / n_m
            ent["group_share_of_measurable"] = r4(share)
            if name in ("上位1/4", "下位1/4") and not (0.10 <= share <= 0.45):
                ent["tie_degenerate"] = True
            # 実現した群サイズでの到達可能性（理想の n/4 ではなく実物で）
            at = attainability(n_pop, k_pop, gn)
            if at:
                ent["attainable_positive"] = at["positive_direction"]["attainable"]
                ent["attainable_protective"] = at["protective_direction"]["attainable"]
                ent["max_attainable_lift_positive"] = at["positive_direction"]["max_attainable_lift"]
        cuts[name] = ent

    quint = []
    if distinct >= 5:
        qs = [q_at(vals, x) for x in (0.2, 0.4, 0.6, 0.8)]
        buckets = [[] for _ in range(5)]
        for (x, w) in M:
            b = 0
            for i, t in enumerate(qs):
                if x > t:
                    b = i + 1
            buckets[b].append(w)
        for i, b in enumerate(buckets):
            quint.append({"q": i + 1, "n": len(b), "k": sum(b), "p": r4(rate(sum(b), len(b)))})
        pts = [(i, q["p"]) for i, q in enumerate(quint) if q["p"] is not None and q["n"] >= 10]
        mono_rho = spearman([a for a, _ in pts], [b for _, b in pts]) if len(pts) >= 3 else None
        ps = [q["p"] for q in quint if q["p"] is not None and q["n"] >= 10]
        strict_up = len(ps) >= 4 and all(ps[i] < ps[i + 1] for i in range(len(ps) - 1))
        strict_dn = len(ps) >= 4 and all(ps[i] > ps[i + 1] for i in range(len(ps) - 1))
    else:
        mono_rho, strict_up, strict_dn = None, False, False

    by_val = None
    if distinct <= 6:
        c = defaultdict(lambda: [0, 0])
        for (x, w) in M:
            c[x][0] += 1
            c[x][1] += w
        by_val = [{"value": k, "n": a, "k": b, "p": r4(rate(b, a))} for k, (a, b) in sorted(c.items())]

    rho = spearman([x for (x, _) in M], [float(w) for (_, w) in M])

    # 母集団の定義に使われている変数を、その母集団の中で検定してはいけない（W1 と同一）
    circ = None
    if pop == "P_quality":
        if var in ("co_fcf_all_pos", "co_op_all_pos", "f2_fcfpos5"):
            circ = "この母集団の定義そのもの（定数化・lift は構造的に0）"
        elif var in ("co_opm", "f2_opm"):
            circ = "この母集団の定義に使われている（opm>=10% で下側が切り落とされている＝範囲が切り詰められた検定）"
        elif var == "co_fcf_conv_5y":
            circ = "母集団が FCF 全年黒字に絞られているため転換率の下側が構造的に薄い"

    return {
        "circularity_with_population": circ,
        "n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop),
        "n_measurable": n_m, "k_measurable": k_m, "p_measurable": r4(p_m),
        "n_missing": n_miss, "p_missing": r4(p_miss),
        "missingness_lift": r4(None if p_miss is None else p_miss - p_m),
        "distinct": distinct, "q25": q25, "q50": q50, "q75": q75,
        "cuts": cuts,
        "quintiles": quint or None,
        "quintile_spearman": r4(mono_rho),
        "quintile_strict_monotone_up": strict_up,
        "quintile_strict_monotone_down": strict_dn,
        "by_value": by_val,
        "rank_corr_value_vs_outcome": r4(rho),
    }


cells = {}
for var in CANDIDATES:
    for pop in POPS:
        for v in ALL_VINTAGES:
            m = measure(v, pop, var)
            if m:
                cells[f"{var}|{pop}|{v}"] = m


# ─────────── 変数×母集団の要約（3ビンテージを並べる＝符号安定性が見える形） ───────────
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]


def summarize(var, pop):
    per_v = {}
    for v in ALL_VINTAGES:
        m = cells.get(f"{var}|{pop}|{v}")
        per_v[v] = m if (m and m.get("n_measurable", 0)) else None

    out = {"variable": var, "population": pop, "cuts": {}}
    for cut in CUTNAMES:
        row = {}
        for v in ALL_VINTAGES:
            m = per_v.get(v)
            if not m:
                row[v] = None
                continue
            c = m["cuts"][cut]
            row[v] = {"n_group": c["n_group"], "k": c["numerator"], "p_group": c["p_group"],
                      "p_base": m["p_pop"], "lift": c["lift_vs_pop"],
                      "lift_meas": c["lift_vs_measurable"], "rr": c.get("rr_vs_pop"),
                      "tie_degenerate": c.get("tie_degenerate", False),
                      "attainable_positive": c.get("attainable_positive"),
                      "attainable_protective": c.get("attainable_protective")}
        got3 = [row[v] for v in SIGN_VINTAGES if row.get(v) and row[v]["lift"] is not None]
        n_empty3 = sum(1 for v in SIGN_VINTAGES if row.get(v) and row[v]["lift"] is None)
        gate = {"empty_group_vintages": n_empty3}
        if len(got3) < 3:
            gate["sign_stability"] = ("判定不能（この切り方で群が空になるビンテージがある）" if n_empty3
                                      else "判定不能（2016/2017/2018 のどれかで測れない）")
            gate["lift_all3"] = None
            gate["min_num_all3"] = None
        else:
            signs = {(1 if g["lift"] > 0 else (-1 if g["lift"] < 0 else 0)) for g in got3}
            gate["sign_stability"] = (len(signs) == 1 and 0 not in signs)
            gate["lift_all3"] = all(abs(g["lift"]) >= LIFT for g in got3)
            gate["min_num_all3"] = all(g["k"] >= MIN_NUM for g in got3)
            gate["min_abs_lift_3v"] = r4(min(abs(g["lift"]) for g in got3))
            gate["signed_lifts_3v"] = [g["lift"] for g in got3]
            # 事前登録の外・診断: 3ビンテージで維持できた RR
            rrs = [g["rr"] for g in got3 if g["rr"] is not None]
            if len(rrs) == 3:
                gate["rr_3v"] = rrs
                gate["min_rr_3v"] = r4(min(rrs))
                gate["max_rr_3v"] = r4(max(rrs))
                gate["rr_sign_stable"] = (all(x > 1 for x in rrs) or all(x < 1 for x in rrs))
        extra = [row[v] for v in (2013, 2015) if row.get(v) and row[v]["lift"] is not None]
        if extra and len(got3) == 3:
            s3 = 1 if got3[-1]["lift"] > 0 else -1
            gate["sign_agree_2013_2015"] = all((1 if g["lift"] > 0 else -1) == s3 for g in extra)
        else:
            gate["sign_agree_2013_2015"] = None
        row["gate"] = gate
        out["cuts"][cut] = row

    out["monotonicity"] = {v: (None if not per_v.get(v) else {
        "quintiles": per_v[v]["quintiles"], "spearman": per_v[v]["quintile_spearman"],
        "strict_up": per_v[v]["quintile_strict_monotone_up"],
        "strict_down": per_v[v]["quintile_strict_monotone_down"],
        "by_value": per_v[v]["by_value"], "rank_corr": per_v[v]["rank_corr_value_vs_outcome"],
    }) for v in ALL_VINTAGES}
    out["missingness"] = {v: (None if not per_v.get(v) else {
        "n_measurable": per_v[v]["n_measurable"], "n_missing": per_v[v]["n_missing"],
        "p_measurable": per_v[v]["p_measurable"], "p_missing": per_v[v]["p_missing"],
        "missingness_lift": per_v[v]["missingness_lift"],
    }) for v in ALL_VINTAGES}
    return out


summaries = {}
for var in CANDIDATES:
    for pop in POPS:
        s = summarize(var, pop)
        if any(s["cuts"][c].get(v) for c in CUTNAMES for v in ALL_VINTAGES):
            summaries[f"{var}|{pop}"] = s


# ────────────────────────────── ゲート4: 業種(sic2)調整 ──────────────────────────────
# ⚠ 物差しの注意（prereg の線をそのまま使うが、読むときに要る知識）:
#   lift は「群 vs 母集団（群を含む）」、MH リスク差は「群 vs 群以外」。四分位(g=n/4)なら
#   lift = (1-g/n)*(p_group - p_rest) = 0.75 * MH。**つまり MH は構造的に lift の約1.33倍出る。**
#   同じ 0.15 をどちらにも当てる prereg のゲート4は、その分だけ lift のゲートより緩い。
#   線は動かさない（prereg）。読み違えないための注記としてだけ書く。
MH_CONTRAST_NOTE = ("lift は群 vs 母集団（群を含む）、MH は群 vs 群以外。四分位では MH ≈ lift/0.75 ＝ "
                    "MH のほうが約1.33倍大きく出る。ゲート4に同じ0.15を当てるのは、その分だけ"
                    "lift のゲートより緩い。実測 f2_rev|下位1/4 は lift 0.1022 に対し MH 0.1394 ＝ 1.36倍。")


def _size_q(v, pop):
    """その (vintage,pop) の size_rev 四分位境界（size 影の層別に使う）。"""
    vals = sorted(x for x in (num(r.get("size_rev")) for r in pop_rows(v, pop)) if x is not None)
    if len(vals) < 20:
        return None
    return [q_at(vals, q) for q in (0.25, 0.50, 0.75)]


def mh_risk_diff(v, pop, var, cut, stratify="sic2"):
    R = pop_rows(v, pop)
    if stratify == "sic2":
        def skey(r):
            return r.get("sic2")
    elif stratify == "size":
        qs = _size_q(v, pop)
        if not qs:
            return None

        def skey(r):
            x = num(r.get("size_rev"))
            if x is None:
                return None
            return "size_q%d" % (1 + sum(1 for t in qs if x > t))
    else:
        raise ValueError(stratify)
    M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0, skey(r)) for r in R]
    M = [(x, w, s) for (x, w, s) in M if x is not None and s]
    if len(M) < 20:
        return None
    vals = sorted(x for (x, _, _) in M)
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    pred = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
            "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for (x, w, s) in M:
        d = strata[s]
        if pred(x):
            d[0] += 1; d[1] += w
        else:
            d[2] += 1; d[3] += w
    numr, den, used, drop = 0.0, 0.0, 0, 0
    for s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        wgt = n1 * n0 / (n1 + n0)
        numr += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(numr / den), "strata_used": used, "strata_dropped": drop}


# ────────────────────────────── ゲート5: irr の影でないか ──────────────────────────────
def irr_control(v, pop, var, cut):
    R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
    if len(R) < 20:
        return {"status": f"irr の読解がこのビンテージ・母集団で {len(R)} 行しかなく判定不能"}
    M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0, r["irr"]) for r in R]
    M = [t for t in M if t[0] is not None]
    if len(M) < 20:
        return {"status": f"変数×irr がそろう行が {len(M)} で判定不能"}
    rho = spearman([x for x, _, _ in M], [float(i) for _, _, i in M])
    hi = [(x, w) for (x, w, i) in M if i >= 70]
    res = {"n_with_irr": len(M), "corr_var_vs_irr": r4(rho),
           "orthogonal_hint": (None if rho is None else abs(rho) < 0.15)}
    n_ev_hi = sum(w for _, w in hi)
    if len(hi) >= 20 and n_ev_hi >= MIN_NUM:
        vals = sorted(x for x, _ in hi)
        q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
        pred = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
        g = [w for x, w in hi if pred(x)]
        base = rate(n_ev_hi, len(hi))
        res["irr_ge70"] = {"n": len(hi), "events": n_ev_hi, "base": r4(base), "n_group": len(g),
                           "k": sum(g), "p_group": r4(rate(sum(g), len(g))),
                           "lift": r4(None if not g else rate(sum(g), len(g)) - base)}
    else:
        res["irr_ge70"] = {"status": f"irr>=70 が {len(hi)} 行・破壊事象 {n_ev_hi} 件で判定不能"}
    return res


# ────────────────────────────── 検出力（結果の前に出す） ──────────────────────────────
rnd = random.Random(SEED)


def binom(n, p):
    return sum(1 for _ in range(n) if rnd.random() < p)


def power_sim(n, base, true_lift, n_sims=N_POWER):
    g = max(1, n // 4)
    rest = n - g
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = (base * n - p_g * g) / rest
    if p_r < 0:
        return {"single_vintage": None, "three_independent": None,
                "impossible": True,
                "why": (f"群の破壊率を {p_g:.3f} にすると、残り {rest} 行の破壊率が負({p_r:.3f})になる＝"
                        "母集団の base をこの群だけで超えてしまう。この真の効果はこの base では存在しえない")}
    p_r = min(0.999, max(0.0, p_r))
    single = triple = 0
    for _ in range(n_sims):
        ok = []
        for _v in range(3):
            kg = binom(g, p_g)
            kr = binom(rest, p_r)
            b = (kg + kr) / n
            lift = kg / g - b
            ok.append((abs(lift) >= LIFT and kg >= MIN_NUM, 1 if lift > 0 else -1))
        if ok[0][0]:
            single += 1
        if all(o[0] for o in ok) and len({o[1] for o in ok}) == 1:
            triple += 1
    return {"single_vintage": r4(single / n_sims), "three_independent": r4(triple / n_sims),
            "impossible": False,
            "relative_risk_implied": r4(p_g / base) if base else None,
            "rest_rate_implied": r4(p_r)}


power = {}
for pop, n_ref in (("P_full", 946), ("P_quality", 329)):
    base_ref = cell_reach[f"2016/{pop}"]["base"]
    power[pop] = {"n_used": n_ref, "base_used": base_ref,
                  "by_true_lift": {str(L): power_sim(n_ref, base_ref, L) for L in (0.15, 0.20, 0.30)}}
power["_how_to_read"] = (
    "three_independent が下限・single_vintage が上限（3ビンテージが完全に同じ実現なら1回引ければ3回引ける）。"
    "★破壊側では検出力の数字より relative_risk_implied を読むこと——base 5.8% に lift 0.15 を足すのは "
    "**相対リスク 3.6倍**を要求する。検出力が高く出るのは効果が巨大だからで、"
    "『この線なら小さな効果も掴める』という意味ではない。"
    "P_quality では base 2.1% に対し要求 RR が 8倍を超え、残り3/4の破壊率が負になるため"
    "**そのような効果はこの母集団に存在しえない**（impossible=true）。")


# ────────────────────────────── 偽陽性率（実データの相関を保った置換） ──────────────────────────────
tick_idx = {}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        if r["ticker"] not in tick_idx:
            tick_idx[r["ticker"]] = len(tick_idx)
N_T = len(tick_idx)

A_bits = {v: [0] * N_T for v in SIGN_VINTAGES}
D_bits = {v: [0] * N_T for v in SIGN_VINTAGES}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        i = tick_idx[r["ticker"]]
        A_bits[v][i] = 1
        if r.get(OUTCOME):
            D_bits[v][i] = 1


def bits_to_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


fpr_masks = []
FPR_POPS = ["P_full", "P_quality"]
for var in gate_reachable:
    for pop in FPR_POPS:
        per_v = {}
        ok = True
        for v in SIGN_VINTAGES:
            R = pop_rows(v, pop)
            mm = [0] * N_T
            entries = []
            for r in R:
                x = num(r.get(var))
                if x is None:
                    continue
                i = tick_idx.get(r["ticker"])
                if i is None:
                    ok = False
                    break
                mm[i] = 1
                entries.append((x, i))
            if not ok or len(entries) < 20:
                ok = False
                break
            pm = [0] * N_T
            for r in R:
                i = tick_idx.get(r["ticker"])
                if i is not None:
                    pm[i] = 1
            vals = sorted(x for x, _ in entries)
            q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
            cutmasks = {}
            for name, pred in (("上位1/4", lambda x: x >= q75), ("下位1/4", lambda x: x <= q25),
                               ("中央値超", lambda x: x > q50), ("中央値以下", lambda x: x <= q50)):
                gm = [0] * N_T
                for x, i in entries:
                    if pred(x):
                        gm[i] = 1
                cutmasks[name] = bits_to_int(gm)
            per_v[v] = {"pop": bits_to_int(pm), "meas": bits_to_int(mm), "cuts": cutmasks}
        if ok:
            for cut in CUTNAMES:
                fpr_masks.append((var, pop, cut,
                                  {v: (per_v[v]["pop"], per_v[v]["meas"], per_v[v]["cuts"][cut])
                                   for v in SIGN_VINTAGES}))


def perm_int(bits, sigma):
    return int("".join("1" if bits[sigma[j]] else "0" for j in range(N_T)), 2)


def run_procedure(Aint, Dint, thresh=LIFT, want_stat=False, base="pop"):
    hits, stats = [], []
    for (var, pop, cut, mv) in fpr_masks:
        ok, signs, mins = True, set(), []
        for v in SIGN_VINTAGES:
            pm, mm_, gm = mv[v]
            bm = pm if base == "pop" else mm_
            a = Aint[v]
            npop = (bm & a).bit_count()
            kpop = (bm & Dint[v]).bit_count()
            ng = (gm & a).bit_count()
            kg = (gm & Dint[v]).bit_count()
            if npop == 0 or ng == 0 or kg < MIN_NUM:
                ok = False
                break
            lift = kg / ng - kpop / npop
            mins.append(abs(lift))
            signs.add(1 if lift > 0 else -1)
        if ok and len(signs) == 1:
            stats.append(min(mins))
            if min(mins) >= thresh:
                hits.append((var, pop, cut))
        else:
            stats.append(0.0)
    return (hits, stats) if want_stat else hits


A0 = {v: bits_to_int(A_bits[v]) for v in SIGN_VINTAGES}
D0 = {v: bits_to_int(D_bits[v]) for v in SIGN_VINTAGES}
observed_hits = run_procedure(A0, D0)

RELAX = [0.02, 0.03, 0.04, 0.06, 0.08, 0.10, 0.15]
perm_hits, perm_maxstat, perm_maxstat_meas = [], [], []
relax_any = {t: 0 for t in RELAX}
sigma = list(range(N_T))
for _ in range(N_PERM):
    rnd.shuffle(sigma)
    Ai = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Di = {v: perm_int(D_bits[v], sigma) for v in SIGN_VINTAGES}
    _h, st = run_procedure(Ai, Di, want_stat=True)
    mx = max(st) if st else 0.0
    perm_maxstat.append(mx)
    perm_hits.append(sum(1 for s in st if s >= LIFT))
    for t in RELAX:
        if mx >= t:
            relax_any[t] += 1
    _h2, st2 = run_procedure(Ai, Di, want_stat=True, base="meas")
    perm_maxstat_meas.append(max(st2) if st2 else 0.0)

n_any = sum(1 for h in perm_hits if h > 0)
srt = sorted(perm_maxstat)


def pct(p):
    return r4(srt[min(len(srt) - 1, max(0, int(p * len(srt)) - 1))])


_, obs_stats = run_procedure(A0, D0, want_stat=True)
obs_max = max(obs_stats) if obs_stats else 0.0
_, obs_stats_meas = run_procedure(A0, D0, want_stat=True, base="meas")

fpr = {
    "n_permutations": N_PERM,
    "n_tests_in_procedure": len(fpr_masks),
    "null_construction": ("特徴量側（母集団・可測・群）は固定し、outcome の束"
                          "(has_outcome∧window_full, destroy)をティッカーごとまとめて置換する。"
                          "ビンテージ間の outcome 相関・欠測構造・P_quality の定義を保ったまま、"
                          "特徴量↔outcome だけを壊せる。"),
    "P_at_least_one_pass": r4(n_any / N_PERM),
    "mean_passes_per_permutation": r4(sum(perm_hits) / N_PERM),
    "max_passes_in_a_permutation": max(perm_hits),
    "observed_passes_gates123": len(observed_hits),
    "observed_hits": [{"variable": a, "population": b, "cut": c} for a, b, c in observed_hits],
    "null_distribution_of_max_statistic": {
        "statistic": f"{len(fpr_masks)}検定のうち最大の『符号が揃ったうえでの3ビンテージ最小|lift|』",
        "p50": pct(0.50), "p90": pct(0.90), "p95": pct(0.95), "p99": pct(0.99),
        "max_over_permutations": r4(max(perm_maxstat)),
        "observed_in_real_data": r4(obs_max),
        "empirical_p_of_observed": r4(sum(1 for m in perm_maxstat if m >= obs_max) / N_PERM),
    },
    "fpr_at_relaxed_thresholds": {
        "note": "**事前登録の外・診断専用**。合否には数えない。破壊側は事象が稀なので、"
                "勝者側(W1)より低い閾値まで下げて帰無分布の立ち上がりを見る。"
                "『0.0』が手続きの厳しさであって道具の故障でないことを示すためだけにある。",
        "P_at_least_one_pass_by_threshold": {str(t): r4(relax_any[t] / N_PERM) for t in RELAX},
    },
    "supplementary_null_measurable_base": {
        "note": "**事前登録の外・診断専用**。lift の分母を可測部分集合にした版。",
        "observed_in_real_data": r4(max(obs_stats_meas) if obs_stats_meas else 0.0),
        "null_p50": r4(sorted(perm_maxstat_meas)[N_PERM // 2 - 1]),
        "null_p95": r4(sorted(perm_maxstat_meas)[int(0.95 * N_PERM) - 1]),
        "null_p99": r4(sorted(perm_maxstat_meas)[int(0.99 * N_PERM) - 1]),
        "null_max": r4(max(perm_maxstat_meas)),
        "empirical_p_of_observed": r4(
            sum(1 for m in perm_maxstat_meas if m >= (max(obs_stats_meas) if obs_stats_meas else 0.0))
            / N_PERM),
    },
}


# ────────────────────────────── 判定（prereg の5条件） ──────────────────────────────
def verdict_for(var, pop, cut):
    s = summaries.get(f"{var}|{pop}")
    if not s:
        return None
    row = s["cuts"][cut]
    g = row["gate"]

    reach_bad, reach_why = [], []
    for v in SIGN_VINTAGES:
        cr = cell_reach.get(f"{v}/{pop}", {})
        if cr.get("n", 0) == 0:
            reach_bad.append(v); reach_why.append(f"{v}:母集団が空")
            continue
        if cr.get("events_destroy", 0) < MIN_NUM:
            reach_bad.append(v); reach_why.append(f"{v}:破壊事象{cr.get('events_destroy')}件<5")
            continue
        # この切り方（実現群サイズ）で線に届きうるか
        c = (cells.get(f"{var}|{pop}|{v}") or {}).get("cuts", {}).get(cut, {})
        if c.get("attainable_positive") is False and c.get("attainable_protective") is False:
            reach_bad.append(v)
            reach_why.append(f"{v}:群n={c.get('n_group')}で攻める向きの上限"
                             f"{c.get('max_attainable_lift_positive')}・守る向きの上限"
                             f"{cr.get('base')}＝どちらも0.15に届かない")

    circ = (cells.get(f"{var}|{pop}|2018") or cells.get(f"{var}|{pop}|2013")
            or {}).get("circularity_with_population")
    if circ and "定数化" in circ:
        return {"verdict": "判定不能", "reason": f"母集団の定義そのもの＝{circ}",
                "gate_failed_at": "circularity"}
    if not var_vintage_cov[var]["sign_gate_evaluable"]:
        return {"verdict": "判定不能",
                "reason": "2016/2017/2018 のどれかにこの変数が存在せず、prereg の必須ゲート（符号不変）を当てられない",
                "gate_failed_at": "sign_stability(構造的に評価不能)"}
    if g.get("empty_group_vintages"):
        return {"verdict": "判定不能",
                "reason": f"タイが重くこの切り方で群が空になるビンテージが {g['empty_group_vintages']} 件",
                "gate_failed_at": "empty_group"}
    if reach_bad:
        return {"verdict": "判定不能",
                "reason": "破壊は稀事象で、この母集団・この切り方では線(|lift|>=0.15)に構造的に届かない: "
                          + " / ".join(reach_why),
                "gate_failed_at": "reachability(rare_event)"}
    if g.get("min_num_all3") is False:
        return {"verdict": "不合格", "reason": "分子>=5社 を満たさないビンテージがある",
                "gate_failed_at": "min_numerator"}
    if g.get("lift_all3") is False:
        return {"verdict": "不合格",
                "reason": f"|lift|>=0.15 を3ビンテージで維持できない（最小 {g.get('min_abs_lift_3v')}）",
                "gate_failed_at": "lift"}
    if g.get("sign_stability") is not True:
        return {"verdict": "不合格", "reason": "2016/2017/2018 で符号が反転する",
                "gate_failed_at": "sign_stability"}
    mh = {str(v): mh_risk_diff(v, pop, var, cut) for v in SIGN_VINTAGES}
    ic = {str(v): irr_control(v, pop, var, cut) for v in (2018,)}
    sector_ok = all(m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT
                    for m in mh.values())
    if not sector_ok:
        return {"verdict": "不合格", "reason": "同一 sic2 内（MH重み付きリスク差）で 0.15 を維持できない",
                "gate_failed_at": "sector_control", "mh": mh}
    e = ic["2018"]
    if e.get("irr_ge70", {}).get("lift") is None and not e.get("orthogonal_hint"):
        return {"verdict": "判定不能",
                "reason": "irr>=70 層が薄く層内検定ができず、かつ irr と直交とも言えない",
                "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic}
    shadow_ok = (e.get("orthogonal_hint") is True
                 or (e.get("irr_ge70", {}).get("lift") is not None
                     and abs(e["irr_ge70"]["lift"]) >= LIFT))
    if not shadow_ok:
        return {"verdict": "不合格", "reason": "irr>=70 層内で差が消え、かつ irr と直交でもない＝irr の影",
                "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic}
    return {"verdict": "合格", "reason": "prereg の5条件すべてを満たす", "mh": mh, "irr": ic}


# ────────────── 陽性対照（注入検査）──────────────
# 「合格ゼロ」という強い結論ほど先に道具を疑う。真の効果を仕込んで手続きが掴めるか見る。
# ★破壊側では **注入そのものが失敗する**ことがある——事象数が足りず、要求された群勝率を作れない。
#   その失敗こそが「線が到達不能」という主張の最も強い実証になるので、必ず記録する。
def inject_control(true_lift, key, pop="P_full"):
    report = {}
    for v in ALL_VINTAGES:
        R = pop_rows(v, pop)
        n = len(R)
        g = max(1, n // 4)
        E = sum(1 for r in R if r.get(OUTCOME))
        base = rate(E, n)
        k_want = max(MIN_NUM, int(round((base + true_lift) * g)))
        k_real = min(k_want, E)
        evs = [r for r in R if r.get(OUTCOME)]
        non = [r for r in R if not r.get(OUTCOME)]
        rnd.shuffle(evs); rnd.shuffle(non)
        grp = evs[:k_real] + non[:max(0, g - k_real)]
        gs = {id(r) for r in grp}
        for r in R:
            r[key] = (0.75 + rnd.random() * 0.25) if id(r) in gs else (rnd.random() * 0.74)
        for r in by_v[v]:
            if key not in r:
                r[key] = None
        report[v] = {"n": n, "group_n": g, "events_total": E, "base": r4(base),
                     "k_wanted": k_want, "k_achieved": k_real,
                     "lift_wanted": true_lift,
                     "lift_achievable": r4(k_real / g - base),
                     "injection_possible": k_real >= k_want,
                     "why": (None if k_real >= k_want else
                             f"要求 {k_want} 件に対し破壊事象は全部で {E} 件しかない＝"
                             f"この真の効果はこの母集団に存在しえない")}
    return report


def drop_control(key):
    for r in rows_all:
        r.pop(key, None)


positive_control = {}
for L, key in ((0.25, "_ctrl25"), (0.15, "_ctrl15"), (0.05, "_ctrl05")):
    inj = inject_control(L, key)
    CANDIDATES.append(key)
    var_vintage_cov[key] = {"coverage": {}, "sign_gate_evaluable": True, "all5_vintages": True,
                            "gate_note": "合成（陽性対照）"}
    for pop in POPS:
        for v in ALL_VINTAGES:
            m = measure(v, pop, key)
            if m:
                cells[f"{key}|{pop}|{v}"] = m
    summaries[f"{key}|P_full"] = summarize(key, "P_full")
    vd = verdict_for(key, "P_full", "上位1/4")
    s3 = summaries[f"{key}|P_full"]["cuts"]["上位1/4"]["gate"]
    positive_control[f"true_lift={L}"] = {
        "verdict": vd["verdict"], "reason": vd["reason"],
        "gate_failed_at": vd.get("gate_failed_at"),
        "observed_lifts_161718": s3.get("signed_lifts_3v"),
        "sign_stability": s3.get("sign_stability"),
        "injection_feasibility": inj,
        "injection_possible_all_vintages": all(x["injection_possible"] for x in inj.values()),
    }
    for pop in POPS:
        for v in ALL_VINTAGES:
            cells.pop(f"{key}|{pop}|{v}", None)
    summaries.pop(f"{key}|P_full", None)
    CANDIDATES.remove(key)
    var_vintage_cov.pop(key, None)
    drop_control(key)
positive_control["_how_to_read"] = (
    "★破壊側で最も重要なのは verdict ではなく injection_possible。"
    "真の lift 0.25/0.15 を仕込もうとしても、P_full ですら破壊事象が足りず"
    "**要求された群破壊率を作れないビンテージがある**＝その大きさの効果はこの母集団に存在しえない。"
    "つまり『合格ゼロ』は道具の失敗でも効果の不在でもなく、**線が事象数に対して大きすぎる**ということ。"
    "true_lift=0.05 は線(0.15)より小さいので合格しないのが正しい挙動（道具が線を守っている証拠）。")


verdicts = {}
for var in CANDIDATES:
    for pop in POPS:
        if f"{var}|{pop}" not in summaries:
            continue
        for cut in CUTNAMES:
            vd = verdict_for(var, pop, cut)
            if vd:
                verdicts[f"{var}|{pop}|{cut}"] = vd


# ────────────────────────────── 序列 ──────────────────────────────
rank_rows = []
for key, s in summaries.items():
    var, pop = key.split("|")
    for cut in CUTNAMES:
        row = s["cuts"][cut]
        g = row["gate"]
        got = [(v, row[v]) for v in ALL_VINTAGES if row.get(v) and row[v]["lift"] is not None]
        if not got:
            continue
        if g.get("min_abs_lift_3v") is not None and g.get("sign_stability") is True:
            score = g["min_abs_lift_3v"]
            basis = "3ビンテージで符号が揃ったうえでの最小|lift|"
        elif g.get("min_abs_lift_3v") is not None:
            score = -1.0 + g["min_abs_lift_3v"]
            basis = "3ビンテージで符号が割れた（最小|lift|から1.0引いて下位へ）"
        else:
            ls = sorted(abs(x[1]["lift"]) for x in got)
            score = ls[len(ls) // 2]
            basis = "3ビンテージそろわず＝測れたビンテージの|lift|の中央値（判定不能）"
        anchor_v = 2018 if (row.get(2018) and row[2018]["lift"] is not None) else got[-1][0]
        a = row[anchor_v]
        mi = s["missingness"].get(anchor_v) or {}
        gap = (None if a["lift"] is None or a["lift_meas"] is None
               else round(abs(a["lift"]) - abs(a["lift_meas"]), 4))
        rank_rows.append({
            "variable": var, "population": pop, "cut": cut,
            "rank_score": r4(score), "rank_basis": basis, "anchor_vintage": anchor_v,
            "n_group": a["n_group"], "numerator": a["k"],
            "p_group": a["p_group"], "p_base": a["p_base"], "lift_anchor": a["lift"],
            "rr_anchor": a.get("rr"),
            "lift_by_vintage": {str(v): (row[v]["lift"] if row.get(v) else None) for v in ALL_VINTAGES},
            "rr_by_vintage": {str(v): (row[v].get("rr") if row.get(v) else None) for v in ALL_VINTAGES},
            "numerator_by_vintage": {str(v): (row[v]["k"] if row.get(v) else None) for v in ALL_VINTAGES},
            "n_group_by_vintage": {str(v): (row[v]["n_group"] if row.get(v) else None) for v in ALL_VINTAGES},
            "p_group_by_vintage": {str(v): (row[v]["p_group"] if row.get(v) else None) for v in ALL_VINTAGES},
            "p_base_by_vintage": {str(v): (row[v]["p_base"] if row.get(v) else None) for v in ALL_VINTAGES},
            "sign_stable_161718": g.get("sign_stability"),
            "min_abs_lift_161718": g.get("min_abs_lift_3v"),
            "min_rr_161718": g.get("min_rr_3v"),
            "max_rr_161718": g.get("max_rr_3v"),
            "rr_sign_stable_161718": g.get("rr_sign_stable"),
            "sign_agree_2013_2015": g.get("sign_agree_2013_2015"),
            "tie_degenerate_anchor": a.get("tie_degenerate", False),
            "coverage_anchor": (None if not mi else r4(rate(mi["n_measurable"],
                                                           mi["n_measurable"] + mi["n_missing"]))),
            "n_missing_anchor": mi.get("n_missing"),
            "missingness_lift_anchor": mi.get("missingness_lift"),
            "missingness_lift_readable": (mi.get("n_missing", 0) >= 20),
            "lift_shrink_when_missingness_removed": gap,
            "missingness_confounded": (gap is not None and gap >= 0.03),
            "verdict": verdicts.get(f"{var}|{pop}|{cut}", {}).get("verdict"),
            "verdict_reason": verdicts.get(f"{var}|{pop}|{cut}", {}).get("reason"),
            "gate_failed_at": verdicts.get(f"{var}|{pop}|{cut}", {}).get("gate_failed_at"),
        })
rank_rows.sort(key=lambda r: -(r["rank_score"] if r["rank_score"] is not None else -9))
top30 = rank_rows[:30]

gate_eval = [r for r in rank_rows if r["sign_stable_161718"] is True
             and r["min_abs_lift_161718"] is not None]
gate_eval.sort(key=lambda r: -r["min_abs_lift_161718"])
top_gate_evaluable = gate_eval[:30]
for r in top_gate_evaluable[:15]:
    r["diagnostics_sector_mh"] = {str(v): mh_risk_diff(v, r["population"], r["variable"], r["cut"])
                                  for v in SIGN_VINTAGES}
    r["diagnostics_irr_control_2018"] = irr_control(2018, r["population"], r["variable"], r["cut"])


# ─────────── 【事前登録の外・診断専用】相対リスクの序列 ───────────
# 稀事象の自然な物差しは差でなく比。絶対差の線は上で見たとおり構造的に通らないので、
# 「何も分けていない」のか「分けているが差の線に届かないだけ」なのかを切り分けるために出す。
# ⚠ **合否には一切数えない。線は動かしていない。**
outside = []
for r in rank_rows:
    if r["min_rr_161718"] is None or not r["rr_sign_stable_161718"]:
        continue
    ks = [r["numerator_by_vintage"][str(v)] for v in SIGN_VINTAGES]
    if any(k is None for k in ks):
        continue
    risky = r["min_rr_161718"] > 1
    # 攻める向き: 3ビンテージすべてで分子>=5（prereg の分子条件をそのまま流用＝新しい線を作らない）
    # 守る向き: 分子は小さいのが当たり前なので、代わりに「母集団側の事象が十分か」で読む
    stat = r["min_rr_161718"] if risky else r["max_rr_161718"]
    outside.append({**{k: r[k] for k in ("variable", "population", "cut", "anchor_vintage",
                                         "n_group", "numerator", "p_group", "p_base",
                                         "rr_by_vintage", "numerator_by_vintage",
                                         "n_group_by_vintage", "lift_by_vintage",
                                         "coverage_anchor", "verdict", "gate_failed_at")},
                    "direction": ("破壊が集まる側" if risky else "破壊を避ける側"),
                    "rr_stat": r4(stat),
                    "min_numerator_161718": min(ks),
                    "min_numerator_ok": min(ks) >= MIN_NUM,
                    "sign_agree_2013_2015": r["sign_agree_2013_2015"]})
outside_risky = sorted([o for o in outside if o["direction"] == "破壊が集まる側"],
                       key=lambda o: -o["rr_stat"])
outside_prot = sorted([o for o in outside if o["direction"] == "破壊を避ける側"],
                      key=lambda o: o["rr_stat"])


# ─────────── 【診断】重複した変数（同じ列を二つの名前で数えていないか） ───────────
dup = []
for a, b in (("f2_rev", "size_rev"),):
    same = diff = 0
    for r in ANA:
        x, y = num(r.get(a)), num(r.get(b))
        if x is not None and y is not None:
            if abs(x - y) < 1e-9:
                same += 1
            else:
                diff += 1
    dup.append({"pair": [a, b], "rows_both_present": same + diff, "identical": same, "differing": diff,
                "verdict": ("**同一の列**（size_src が f2_rev）。2016/2017/2018 では同じものを"
                            "二つの名前で数えている＝独立な2件の発見として読んではいけない。"
                            "違いは 2013/2015 で size_rev だけが co_rev_asof から作られていること。"
                            if diff == 0 else "一部一致")})


# ─────────── 【診断】size の影でないか（size が最強の単変量なので必須） ───────────
# ゲート4(業種)・ゲート5(irr) と同じ形で、層を「size 四分位」にして当てる。
# ⚠ prereg のゲートではない（事前登録の外・診断専用）。合否には数えない。
# これを出さないと「低利益率・低カバレッジ・高希薄化が破壊を予言する」と読んでしまうが、
# それらは全部「小型であること」の言い換えかもしれない。
size_shadow = {"note": ("★事前登録の外・診断専用。size(売上) が単変量で最強だったので、"
                        "他の候補が『size の言い換え』でないかを、ゲート4と同じ MH の形で層別して測る。"
                        "層は size 四分位。size 自身は当てない（自明に消えるため）。"
                        "合否には一切数えない。"),
               "contrast_note": MH_CONTRAST_NOTE, "rows": []}
_seen = set()
for o in outside_risky[:20] + outside_prot[:20]:
    var, pop, cut = o["variable"], o["population"], o["cut"]
    if var in ("size_rev", "f2_rev") or (var, pop, cut) in _seen:
        continue
    _seen.add((var, pop, cut))
    raw = {str(v): mh_risk_diff(v, pop, var, cut, stratify="sic2") for v in SIGN_VINTAGES}
    szs = {str(v): mh_risk_diff(v, pop, var, cut, stratify="size") for v in SIGN_VINTAGES}
    plain = {}
    for v in SIGN_VINTAGES:
        c = (cells.get(f"{var}|{pop}|{v}") or {}).get("cuts", {}).get(cut)
        plain[str(v)] = (c or {}).get("lift_vs_pop")
    got = [szs[str(v)]["mh_risk_diff"] for v in SIGN_VINTAGES if szs.get(str(v))]
    size_shadow["rows"].append({
        "variable": var, "population": pop, "cut": cut,
        "lift_by_vintage": plain,
        "mh_sic2": {k: (x or {}).get("mh_risk_diff") for k, x in raw.items()},
        "mh_size_stratified": {k: (x or {}).get("mh_risk_diff") for k, x in szs.items()},
        "size_adjusted_sign_stable": (len({1 if x > 0 else -1 for x in got}) == 1 if len(got) == 3 else None),
        "min_abs_mh_size": (r4(min(abs(x) for x in got)) if len(got) == 3 else None),
        "survives_size_control": (len(got) == 3 and len({1 if x > 0 else -1 for x in got}) == 1
                                  and min(abs(x) for x in got) >= 0.03),
    })
size_shadow["rows"].sort(key=lambda r: -(r["min_abs_mh_size"] or 0))
size_shadow["how_to_read"] = (
    "mh_size_stratified が 0 に潰れるなら『その変数は size の言い換え』。"
    "0 から離れたまま符号が3ビンテージで揃うなら size とは別の情報を持っている。"
    "**0.03 という線は prereg には無い**——合否ではなく『潰れたか否か』を読むための目安として置いた。")


# ─────────── 【診断】堀を通った群(irr>=70)の破壊率 ───────────
def binom_cdf(k, n, p):
    s = 0.0
    for i in range(0, k + 1):
        s += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return s


def cp_upper(k, n, alpha=0.05):
    """Clopper-Pearson 上側（片側 1-alpha）。0件のときの『真のゼロではない』を数字で出すため。"""
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


moat_dx = {"note": ("★事前登録の外・診断専用。P_moat は事象が 0-1 件で prereg の判定には乗らないが、"
                    "『破壊を避ける側』の最大の候補なので実数だけ残す。"
                    "irr の読解がある 2013/2015/2018 のみ。"),
           "by_vintage": {}, }
tn = tk = 0
for v in (2013, 2015, 2018):
    R = pop_rows(v, "P_moat")
    F = pop_rows(v, "P_full")
    n, k = len(R), sum(1 for r in R if r.get(OUTCOME))
    nf, kf = len(F), sum(1 for r in F if r.get(OUTCOME))
    tn += n; tk += k
    moat_dx["by_vintage"][str(v)] = {"P_moat_n": n, "P_moat_destroys": k, "P_moat_rate": r4(rate(k, n)),
                                     "P_full_n": nf, "P_full_destroys": kf, "P_full_rate": r4(rate(kf, nf)),
                                     "rr": (r4((k / n) / (kf / nf)) if n and kf else None)}
moat_dx["pooled"] = {
    "n": tn, "destroys": tk, "rate": r4(rate(tk, tn)),
    "P_full_same_vintages_rate": r4(sum(1 for v in (2013, 2015, 2018) for r in pop_rows(v, "P_full")
                                        if r.get(OUTCOME))
                                    / sum(len(pop_rows(v, "P_full")) for v in (2013, 2015, 2018))),
    "clopper_pearson_upper95": r4(cp_upper(tk, tn)),
    "caveat": (f"分子は {tk} 件。0-2 件の観測から『壊れない』は言えない（95%上側 "
               f"{cp_upper(tk, tn):.4f}）。prereg の分子>=5 に届かず判定不能。"),
}


# ─────────── 名指しされた仮説8本の成績（都合よく選んでいないことの担保） ───────────
named_report = {}
for grp, vars_ in NAMED_HYPOTHESES.items():
    named_report[grp] = {}
    for var in vars_:
        ent = {}
        for pop in ("P_full", "P_quality"):
            s = summaries.get(f"{var}|{pop}")
            if not s:
                continue
            best = None
            for cut in CUTNAMES:
                g = s["cuts"][cut]["gate"]
                row = {"cut": cut,
                       "lift_161718": g.get("signed_lifts_3v"),
                       "min_abs_lift": g.get("min_abs_lift_3v"),
                       "sign_stable": g.get("sign_stability"),
                       "rr_161718": g.get("rr_3v"),
                       "min_rr": g.get("min_rr_3v"), "max_rr": g.get("max_rr_3v"),
                       "rr_sign_stable": g.get("rr_sign_stable"),
                       "numerators": [s["cuts"][cut][v]["k"] if s["cuts"][cut].get(v) else None
                                      for v in SIGN_VINTAGES],
                       "verdict": verdicts.get(f"{var}|{pop}|{cut}", {}).get("verdict"),
                       "gate_failed_at": verdicts.get(f"{var}|{pop}|{cut}", {}).get("gate_failed_at")}
                if best is None or ((row["min_abs_lift"] or 0) > (best["min_abs_lift"] or 0)):
                    best = row
                ent.setdefault("all_cuts", []).append(row)
            ent[pop] = {"best_cut_by_lift": best}
        named_report[grp][var] = ent


# ─────────── ★ W1 との一致検査（同じパネルを見る二つの検査器が違うことを言わない） ───────────
cross = {"status": None, "compared": 0, "mismatch": 0, "details": []}
try:
    wj = json.load(open(WIN_JSON, encoding="utf-8"))
    wcells = wj.get("cells", {})
    checked = 0
    bad = []
    for key, wc in wcells.items():
        if key.startswith("_ctrl"):
            continue
        var, pop, v = key.split("|")
        v = int(v)
        mine = measure(v, pop, var, outcome="win")
        if mine is None or wc.get("n_measurable", 0) == 0 or mine.get("n_measurable", 0) == 0:
            continue
        checked += 1
        for fld in ("n_pop", "k_pop", "p_pop", "n_measurable", "k_measurable", "p_measurable"):
            if wc.get(fld) != mine.get(fld):
                bad.append({"cell": key, "field": fld, "win_tool": wc.get(fld), "this_tool": mine.get(fld)})
        for cut in CUTNAMES:
            a, b = wc["cuts"][cut], mine["cuts"][cut]
            for fld in ("n_group", "numerator", "p_group", "lift_vs_pop"):
                if a.get(fld) != b.get(fld):
                    bad.append({"cell": key, "cut": cut, "field": fld,
                                "win_tool": a.get(fld), "this_tool": b.get(fld)})
    cross = {
        "what": ("この道具の measure() に outcome='win' を渡し、W1(night/hist_wd_win_uni.py) の "
                 "committed 出力 out/hist_wd_win_uni.json と全セル・全切り方で突き合わせる。"
                 "v9.9.65『同じ台帳を見る二つの検査器が違うことを言ってはいけない』を"
                 "約束ではなく検査にしたもの。"),
        "cells_compared": checked,
        "fields_compared_per_cell": "n_pop,k_pop,p_pop,n_measurable,k_measurable,p_measurable ＋ 4切り方×4欄",
        "mismatch": len(bad),
        "mismatch_details": bad[:20],
        "status": ("一致（この道具は W1 と同じ数字を出す）" if not bad
                   else "★不一致あり——どちらかが壊れている。結論を読む前にここを直すこと"),
    }
except FileNotFoundError:
    cross = {"status": "W1 の出力が無く一致検査ができない（判定不能）"}


# ─────────── ★ 勝者側との非対称（prereg の novelty #3「別の変数が効く可能性」） ───────────
# W1 の committed 出力から win 側の lift を読み、同じ (変数,母集団,切り方) で destroy 側と並べる。
# ⚠ 再計算しない——W1 の数字をそのまま読む（上の cross_check で一致を確認済み）。
asym = {"note": ("prereg の novelty #3『勝者と破壊で別の変数が効く可能性』への直接の答え。"
                 "同じ (変数,母集団,切り方) について、W1(win) と この道具(destroy) の "
                 "3ビンテージ最小|lift|と符号を並べる。**両側とも prereg の線には届いていない**ので、"
                 "ここで読むのは合否ではなく『どちらの結果ラベルに、より強く効いているか』の相対。"),
        "rows": []}
try:
    _w = json.load(open(WIN_JSON, encoding="utf-8"))
    wsum = _w.get("summaries", {})
    for key, s in summaries.items():
        var, pop = key.split("|")
        if var.startswith("_ctrl") or not var_vintage_cov.get(var, {}).get("sign_gate_evaluable"):
            continue
        for cut in CUTNAMES:
            dg = s["cuts"][cut]["gate"]
            wg = (wsum.get(key) or {}).get("cuts", {}).get(cut, {}).get("gate")
            if not wg or dg.get("min_abs_lift_3v") is None or wg.get("min_abs_lift_3v") is None:
                continue
            d_stable = dg.get("sign_stability") is True
            w_stable = wg.get("sign_stability") is True
            d_sgn = (1 if (dg.get("signed_lifts_3v") or [0])[-1] > 0 else -1) if d_stable else 0
            w_sgn = (1 if (wg.get("signed_lifts_3v") or [0])[-1] > 0 else -1) if w_stable else 0
            if d_stable and w_stable:
                cls = ("鏡像（同じ変数が、勝ちと破壊で逆向き）" if d_sgn != w_sgn
                       else "同じ向き（勝ちにも破壊にも同符号＝ばらつきの指標かもしれない）")
            elif d_stable and not w_stable:
                cls = "★破壊側だけ符号が安定（勝者側では割れる）"
            elif w_stable and not d_stable:
                cls = "勝者側だけ符号が安定（破壊側では割れる）"
            else:
                cls = "どちらも不安定"
            asym["rows"].append({
                "variable": var, "population": pop, "cut": cut,
                "destroy_min_abs_lift": dg.get("min_abs_lift_3v"),
                "destroy_sign_stable": d_stable, "destroy_lifts": dg.get("signed_lifts_3v"),
                "win_min_abs_lift": wg.get("min_abs_lift_3v"),
                "win_sign_stable": w_stable, "win_lifts": wg.get("signed_lifts_3v"),
                "classification": cls,
                "ratio_destroy_over_win": (r4(dg["min_abs_lift_3v"] / wg["min_abs_lift_3v"])
                                           if wg.get("min_abs_lift_3v") else None),
            })
    asym["rows"].sort(key=lambda r: -(r["destroy_min_abs_lift"] or 0))
    asym["counts"] = dict(Counter(r["classification"] for r in asym["rows"]))
    asym["destroy_only_stable"] = [r for r in asym["rows"]
                                   if r["classification"].startswith("★破壊側だけ")][:15]
except FileNotFoundError:
    asym["status"] = "W1 の出力が無く比較できない"


# ─────────── 保護的な向きが min_numerator と衝突する件（構造の記録） ───────────
prot_conflict = {
    "why": ("prereg の『事象の分子>=5社』は、**破壊を避ける側（保護的な指標）と構造的に衝突する**。"
            "保護が強いほど群の破壊件数は小さくなるので、強い保護ほど分子条件で落ちる。"
            "勝者側(W1)では win が常事象なのでこの衝突は起きない＝**これは破壊側に固有の非対称**。"),
    "cells_failed_on_min_numerator": [
        {"key": k, "reason": v["reason"]} for k, v in verdicts.items()
        if v.get("gate_failed_at") == "min_numerator"],
}
_strong_prot = [o for o in outside_prot if o["rr_stat"] is not None][:5]
prot_conflict["strongest_protective_effects_and_their_numerators"] = [
    {"variable": o["variable"], "population": o["population"], "cut": o["cut"],
     "rr_by_vintage": o["rr_by_vintage"], "numerator_by_vintage": o["numerator_by_vintage"],
     "min_numerator_ok": o["min_numerator_ok"], "verdict": o["verdict"],
     "gate_failed_at": o["gate_failed_at"]} for o in _strong_prot]


# ─────────── 限界（正直に） ───────────
limits = {
    "survivorship_delisting": {
        "issue": ("★破壊側で最大の限界。パネルの outcome は retro_returns_*（Yahoo adjclose）で、"
                  "**上場廃止した会社は母集団に最初から居ない**。破壊はまさに退場と結びつくので、"
                  "勝者側より深刻に効く。"),
        "measured_elsewhere": ("out/retro_delisted_secpx_2013.json（2013・price-only）の実測: "
                               "survivorのみ 恒久毀損 56/977=5.73% → 退場96社を復元して 70/1073=6.52%"
                               "（2026-09-23 退場日の是正後。是正前は 56/981=5.71% → 退場45社で 58/1026=5.65%）"
                               "＝**戻すと上がる**。ただし**まだ714社が打ち切り**。"
                               "質実証の退場178社のうち157社(88%)がM&A退場（acquired/going_private）"
                               "＝プレミアム付きで消えている（是正前の記録は175社中139社・79%）。"
                               "数字の出所は out/hist_wd_dst_path.json の c_delisted_bracket_2013 と "
                               "out/retro_exit_fix_2013.json。"),
        "why_not_merged_here": ("その在庫は **price-only**（配当なし）で、このパネルの tr_cagr は"
                                "**配当込み**。基準の違う二つを混ぜると、この台帳が7回踏んだ型そのものになる。"
                                "だから**併合していない**。"),
        "direction_of_bias": ("**この道具では決められない**。退場には (a)破綻して消える＝破壊率を過小に見せる "
                              "(b)プレミアム付きで買収されて消える＝破壊率を過大に見せる の両方があり、"
                              "実測は(b)が88%（是正前 79%）と多い。ただし測れた退場96社を戻すと"
                              "恒久毀損は 5.73%→6.52% と**上がった**＝(a)も無視できない。"
                              "よって size 効果が過大か過小かは断定できない。"),
    },
    "quartile_cuts_cannot_see_U_shapes": {
        "issue": ("prereg の切り方は四分位と中央値＝**単調な効果しか捉えられない**。"
                  "実測で f2_accr・f2_opmD5・f2_conv5 は**両端が高いU字**で、"
                  "四分位で切ると打ち消し合って小さく出る。"),
        "examples_2018_P_full_quintiles": {
            "f2_accr": [(q["q"], q["k"], q["n"], q["p"]) for q in
                        (cells.get("f2_accr|P_full|2018") or {}).get("quintiles") or []],
            "f2_opmD5": [(q["q"], q["k"], q["n"], q["p"]) for q in
                         (cells.get("f2_opmD5|P_full|2018") or {}).get("quintiles") or []],
        },
        "next_tool": "形（U字・閾値・折れ点）は shape 系の道具の領分。ここでは指摘だけ残す。",
    },
    "vintages_not_independent": ("2016/2017/2018 は同じ956ティッカーで窓が重なる。"
                                 "『3ビンテージで符号一致』を独立な3証拠と読んではいけない（prereg の警告どおり）。"
                                 "本当の外部検証は 2013/2015 だが、そちらは特徴量が co_ の10本しかなく、"
                                 "2015 は母集団が質実証寄り(506社)で破壊事象が9件しかない。"),
    "duplicate_columns": "size_rev は 2016/2017/2018 で f2_rev と同一列（実測 2848行すべて一致）。二重に数えない。",
    "mh_vs_lift_contrast": MH_CONTRAST_NOTE,
    "protective_direction_vs_min_numerator": prot_conflict["why"],
}


# ────────────────────────────── 概念の対 ──────────────────────────────
concept = []
for label, mp in CONCEPT_PAIRS:
    ent = {"concept": label, "variable_by_vintage": {str(k): v for k, v in mp.items()},
           "warning": CONCEPT_PAIR_WARNING, "by_population": {}}
    for pop in POPS:
        tbl = {}
        for v in ALL_VINTAGES:
            m = cells.get(f"{mp[v]}|{pop}|{v}")
            if not m or m.get("n_measurable", 0) == 0:
                tbl[str(v)] = None
                continue
            tbl[str(v)] = {
                "variable": mp[v], "n_pop": m["n_pop"], "p_base": m["p_pop"],
                "上位1/4": {"n": m["cuts"]["上位1/4"]["n_group"], "k": m["cuts"]["上位1/4"]["numerator"],
                            "p": m["cuts"]["上位1/4"]["p_group"], "lift": m["cuts"]["上位1/4"]["lift_vs_pop"],
                            "rr": m["cuts"]["上位1/4"].get("rr_vs_pop")},
                "下位1/4": {"n": m["cuts"]["下位1/4"]["n_group"], "k": m["cuts"]["下位1/4"]["numerator"],
                            "p": m["cuts"]["下位1/4"]["p_group"], "lift": m["cuts"]["下位1/4"]["lift_vs_pop"],
                            "rr": m["cuts"]["下位1/4"].get("rr_vs_pop")},
                "quintile_spearman": m["quintile_spearman"],
                "rank_corr": m["rank_corr_value_vs_outcome"],
            }
        ls = [tbl[str(v)]["上位1/4"]["lift"] for v in ALL_VINTAGES if tbl.get(str(v))]
        ent["by_population"][pop] = {
            "table": tbl, "n_vintages_measured": len(ls),
            "sign_agree_all_measured": (len({1 if x > 0 else (-1 if x < 0 else 0) for x in ls}) == 1
                                        if ls else None),
            "lifts_top_quartile": ls,
        }
    concept.append(ent)


# ────────────────────────────── 出力 ──────────────────────────────
counts = Counter(v["verdict"] for v in verdicts.values())
fail_at = Counter(v.get("gate_failed_at") for v in verdicts.values() if v["verdict"] == "不合格")
undet_at = Counter(v.get("gate_failed_at") for v in verdicts.values() if v["verdict"] == "判定不能")

doc = {
    "generated": "2026-08-11",
    "tool": "night/hist_wd_dst_uni.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "panel": "out/hist_wd_panel.json",
    "counterpart": "night/hist_wd_win_uni.py（目的A・勝者側。同じ手続きを win に当てたもの）",
    "objective": "B_破壊: P(実現年率 tr_cagr <= -15%)。勝者側(目的A)はこの道具の範囲外。",
    "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM,
                       "sign_stability_vintages": SIGN_VINTAGES,
                       "sector_control": "同一sic2内のMH重み付きリスク差でも |RD|>=0.15",
                       "not_irr_shadow": "irr>=70層内で |lift|>=0.15、または変数とirrが直交(|rho|<0.15)",
                       "note": "prereg のまま。この道具は線を一つも作っていない。"},
    "symmetry_with_win_tool": {
        "identical": "解析集合・母集団定義・切り方・タイの扱い・ゲート・置換の作り方・陽性対照の枠組み",
        "different": "結果ラベルのみ（win → destroy）",
        "cross_check_vs_win_tool": cross,
    },
    "analysis_set_size": {str(v): {"n": len(by_v[v]),
                                   "destroys": sum(1 for r in by_v[v] if r.get(OUTCOME)),
                                   "wins": sum(1 for r in by_v[v] if r.get("win"))}
                          for v in ALL_VINTAGES},
    "must_report_before_verdict": {
        "rare_event_attainability": reach_summary,
        "cell_reachability": cell_reach,
        "gate_reachability_by_variable": var_vintage_cov,
        "gate_reachable_variables": gate_reachable,
        "gate_unreachable_variables": gate_unreachable,
        "gate_reachability_summary": (
            f"候補{len(CANDIDATES)}本のうち、必須ゲート（2016/2017/2018 の符号不変）を当てられるのは "
            f"{len(gate_reachable)} 本。残り {len(gate_unreachable)} 本は結果を見る前から構造的に判定不能。"),
        "power": power,
        "false_positive_rate": fpr,
        "positive_control_injection": positive_control,
    },
    "verdict_counts": {"by_verdict": dict(counts),
                       "fail_gate_histogram": dict(fail_at),
                       "undetermined_gate_histogram": dict(undet_at),
                       "n_pass": counts.get("合格", 0)},
    "named_hypotheses_report": {
        "note": ("指示で『破壊側の仮説として筋が良い』と名指しされた8本の成績。"
                 "**測定は全候補に同じ手続きを当てており、この群に特別な線も特別な検定も使っていない。**"
                 "後から都合よく選んだのではないことを示すために、順位に関係なく必ず出す。"),
        "groups": named_report,
    },
    "top30_by_lift": top30,
    "top30_by_lift_note": ("生の |lift| 順。破壊側では**上位をほぼ判定不能セルが占める**——"
                           "稀事象なので小さな群の 1-2 件の増減が lift を大きく動かす。"
                           "答えは top_gate_evaluable と、下の outside_prereg_relative_risk で読むこと。"),
    "top_gate_evaluable": top_gate_evaluable,
    "top_gate_evaluable_note": ("必須ゲートを当てられ、かつ実際に符号が揃ったセルだけを"
                                "『3ビンテージで維持できた最小|lift|』の順に並べたもの。"),
    "outside_prereg_relative_risk": {
        "note": ("★**事前登録の外・診断専用。合否には一切数えない。線は動かしていない。**"
                 "稀事象の自然な物差しは絶対差ではなく比。上の rare_event_attainability のとおり"
                 "絶対差の線は構造的に通らないので、これを出さないと"
                 "『何も分けていない』と『分けているが差の線に届かないだけ』を区別できない。"
                 "prereg の分子>=5 と符号安定の条件はそのまま流用している（新しい線を作らないため）。"),
        "risky_side": outside_risky[:25],
        "protective_side": outside_prot[:25],
    },
    "duplicate_variables": dup,
    "size_shadow_diagnostic": size_shadow,
    "moat_stratum_destruction": moat_dx,
    "mh_vs_lift_contrast_note": MH_CONTRAST_NOTE,
    "win_vs_destroy_asymmetry": asym,
    "protective_direction_vs_min_numerator": prot_conflict,
    "limitations": limits,
    "concept_pairs_5vintage": concept,
    "summaries": summaries,
    "verdicts": verdicts,
    "cells": cells,
}

json.dump(doc, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print("解析集合: " + " / ".join(
    f"{v}:{len(by_v[v])}行(破壊{sum(1 for r in by_v[v] if r.get(OUTCOME))}件)" for v in ALL_VINTAGES))
print("\n■ W1 との一致検査")
print(f"  {cross.get('status')}  比較セル {cross.get('cells_compared')} / 不一致 {cross.get('mismatch')}")
print("\n■ ★線そのものの到達可能性（結果の前に・破壊は稀事象）")
print("  " + reach_summary["headline"].replace("。", "。\n  "))
print("\n■ ゲート到達可能性")
print(f"  候補 {len(CANDIDATES)} 本 → 符号不変ゲートを当てられるのは {len(gate_reachable)} 本 / "
      f"構造的に判定不能 {len(gate_unreachable)} 本")
print("\n■ 検出力（3ビンテージ独立＝下限 / 単一ビンテージ＝上限）")
for pop, d in power.items():
    if pop.startswith("_"):
        continue
    for L, r in d["by_true_lift"].items():
        if r.get("impossible"):
            print(f"  {pop} 真のlift={L}: **存在しえない** — {r['why']}")
        else:
            print(f"  {pop} 真のlift={L}: 下限 {r['three_independent']} / 上限 {r['single_vintage']}"
                  f"（要求される相対リスク {r['relative_risk_implied']}倍）")
print(f"\n■ 偽陽性率（置換{N_PERM}回・実データの相関を保った帰無）")
print(f"  検定数 {fpr['n_tests_in_procedure']} / 偶然に1本以上通る確率 {fpr['P_at_least_one_pass']}")
print(f"  実データでゲート1-3を通ったのは {fpr['observed_passes_gates123']} 本")
nd = fpr["null_distribution_of_max_statistic"]
print(f"  帰無での最大統計量: p50={nd['p50']} p95={nd['p95']} p99={nd['p99']} 最大={nd['max_over_permutations']}"
      f" ／ 実データ={nd['observed_in_real_data']} (経験p={nd['empirical_p_of_observed']})")
print("  線を緩めたときの FPR: " + " ".join(
    f"{k}→{v}" for k, v in fpr["fpr_at_relaxed_thresholds"]["P_at_least_one_pass_by_threshold"].items()))
print("\n■ 陽性対照（注入検査）")
for k, v in positive_control.items():
    if k.startswith("_"):
        continue
    print(f"  {k} → {v['verdict']} / 注入が全ビンテージで可能か: {v['injection_possible_all_vintages']}"
          f"（lifts {v['observed_lifts_161718']}）")
print("\n■ 判定: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
print(f"  不合格の内訳: {dict(fail_at)}")
print(f"  判定不能の内訳: {dict(undet_at)}")
print("\n■ 判定を当てられるセルの中で維持できた |lift| 上位10")
for r in top_gate_evaluable[:10]:
    ls = r["lift_by_vintage"]
    print(f"  {r['min_abs_lift_161718']:.3f} {r['variable']:15s}{r['population']:10s}{r['cut']:6s} "
          f"16/17/18={ls['2016']}/{ls['2017']}/{ls['2018']} → {r['verdict']}")
print("\n■【事前登録の外・診断】相対リスクで並べた「破壊が集まる側」上位12")
for o in outside_risky[:12]:
    rr = o["rr_by_vintage"]
    print(f"  RR>={o['rr_stat']:.2f} {o['variable']:15s}{o['population']:10s}{o['cut']:6s} "
          f"16/17/18={rr['2016']}/{rr['2017']}/{rr['2018']} k={o['numerator_by_vintage']} "
          f"分子5+{'✓' if o['min_numerator_ok'] else '×'}")
print("\n■【事前登録の外・診断】相対リスクで並べた「破壊を避ける側」上位12")
for o in outside_prot[:12]:
    rr = o["rr_by_vintage"]
    print(f"  RR<={o['rr_stat']:.2f} {o['variable']:15s}{o['population']:10s}{o['cut']:6s} "
          f"16/17/18={rr['2016']}/{rr['2017']}/{rr['2018']} k={o['numerator_by_vintage']}")
print("\n■【診断】重複した変数")
for x in dup:
    print(f"  {x['pair']}: 同値 {x['identical']} / 相違 {x['differing']} → {x['verdict'][:60]}")
print("\n■【事前登録の外・診断】size の影でないか（層=size四分位・MH）")
for r in size_shadow["rows"][:12]:
    print(f"  {r['variable']:15s}{r['population']:10s}{r['cut']:6s} "
          f"lift={list(r['lift_by_vintage'].values())} "
          f"→ size層別MH={list(r['mh_size_stratified'].values())} "
          f"{'残る' if r['survives_size_control'] else '潰れる/不安定'}")
print("\n■【事前登録の外・診断】堀を通った群(irr>=70)の破壊")
for v, x in moat_dx["by_vintage"].items():
    print(f"  {v}: {x['P_moat_destroys']}/{x['P_moat_n']}={x['P_moat_rate']} "
          f"vs P_full {x['P_full_rate']} (RR {x['rr']})")
print(f"  合計 {moat_dx['pooled']['destroys']}/{moat_dx['pooled']['n']}={moat_dx['pooled']['rate']} "
      f"vs {moat_dx['pooled']['P_full_same_vintages_rate']} / 95%上側 {moat_dx['pooled']['clopper_pearson_upper95']}")
print("\n■ 勝者側(W1)との非対称")
print(f"  分類: {asym.get('counts')}")
for r in asym.get("destroy_only_stable", [])[:8]:
    print(f"  ★破壊側だけ安定 {r['variable']:14s}{r['population']:10s}{r['cut']:6s} "
          f"destroy={r['destroy_min_abs_lift']} (win側は符号割れ {r['win_lifts']})")
print("\n■ 保護的な向き × 分子>=5 の衝突（破壊側に固有）")
print(f"  分子条件で落ちたセル: {len(prot_conflict['cells_failed_on_min_numerator'])}件")
for x in prot_conflict["strongest_protective_effects_and_their_numerators"][:4]:
    print(f"    {x['variable']:14s}{x['cut']:6s} RR={list(x['rr_by_vintage'].values())[2:]} "
          f"分子={list(x['numerator_by_vintage'].values())[2:]} → {x['verdict']}({x['gate_failed_at']})")
print(f"\n→ {DEST}")
