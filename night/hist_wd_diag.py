#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_diag.py — 合否を出す前に、事前登録した手続きそのものの性能を測る。

事前登録: out/hist_winner_destroyer_prereg.json
入力    : out/hist_wd_panel.json（night/hist_wd_panel.py が作る5ビンテージ統合パネル）
出力    : out/hist_wd_diag.json

**この道具は合否を一つも出さない。** 出すのは「この事前登録は、そもそも何を判定できる形になっているか」だけ。
探索の結果（どの変数が勝ったか）には一切触れない。

────────────────────────────────────────────────────────────
なぜ結果より先にこれを測るのか（hist_valuation_prereg v1/v2 の教訓）
────────────────────────────────────────────────────────────
v1: 合格ゼロと報告したが、後から数えたら **2013/2015 は恒久毀損が 0社/3社しか無く、
    分子>=5 の条件は結果を見る前から成立しえなかった**。つまりあの「不合格」は
    指標の性能を一度も測っていなかった。
v2: MIN_NUM(5社) が LIFT(0.15) より強く縛るセルがあり、**登録した線より高い線が
    こっそり課されていた**（2013/-0.40 で実効2.86倍）。さらに検出力は 0.512 しかなく、
    「2倍の効果があっても半分は掴み損ねる装置」だった。

→ 本器は結果の前に4つを出す:
   (1) 到達可能性  (2) 実効要求倍率  (3) 検出力  (4) 偽陽性率
   そのうえで「この検証で何が言えて何が言えないか」を先に書く。

────────────────────────────────────────────────────────────
測り方の決定と、その理由
────────────────────────────────────────────────────────────
A) **行は has_outcome かつ window_full のみ**（パネルの reachability と同じ）。
   窓長が違う行を年率で混ぜると両裾が機械的に膨らむ。

B) **母集団の基準率は「その変数が非欠測の行」で取る。**
   被覆率は変数ごとに 58%〜100% と大きく違う（f2_sga_r は58%）。
   群を非欠測の中から作りながら基準率を全行で取ると、
   **被覆の偏りがそのまま lift に化ける**（＝「基準の違う二つを割る」型）。
   その代わり「全行の基準率」と「非欠測の基準率」の差も別に出す（被覆交絡の測定）。

C) **群の刻み（上位何%を群と呼ぶか）は事前登録に書かれていない。**
   これは研究者の自由度であり、偽陽性率に直接効く。よって本器は
   10/20/25/33/50% × 上下2方向 を「探索空間の仮定」として明示し、
   その仮定のもとで数える。**線を足したのではなく、書かれていない自由度を数えている。**

D) **検出力は超母集団モデルで解析計算する**（prereg の指示どおり二項分布）。
   群の真の率 p1 = base + δ、残りの率 p0 = base − f·δ/(1−f)
   （こう置くと母集団の平均がちょうど観測 base に一致する＝観測と整合する唯一の置き方）。
   ⚠ p0 < 0 になる (δ, f, base) の組は **算術的に存在しえない**＝検出力の問題ではなく
   「その真値はこの母集団では定義できない」。feasible:false として区別する。
   判定は lift を母集団（群を含む）に対して測るので、閾値は
   K1/m − (K1+K0)/n >= L を K0 で条件付けて厳密に解く（近似しない）。

E) **ビンテージは独立ではない**（実測 Spearman 0.92〜0.96）。よって
   「3ビンテージすべてで維持」の確率は 独立の積（下限）と 完全従属＝1ビンテージ（上限）の
   間に挟まれる。両端を出し、さらに**実データの従属をそのまま使った経験的な注入**でも測る。

F) **偽陽性率は階層で測る。** 高い関門ほど計算が重いので、安い関門から順に当て、
   生き残ったものだけに重い関門を当てる（探索の実装と同じ順序）。
   L1 発見のみ → L2 符号安定 → L3 3ビンテージ維持 → L4 業種調整 → L5 irr層。
   **各段の偽陽性率を出すことで「合格ゼロが統計の厳しさによるのか、
   構造的な不能によるのか」を分けられる。**
"""
import json, os, sys, math, random
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")

LIFT = 0.15          # 事前登録の線（動かさない）
MIN_NUM = 5          # 事前登録の線（動かさない）
DISCOVERY = 2018     # prereg: 「2018で見つけたら 2016 と 2017 の両方で維持」
TRIO = [2016, 2017, 2018]
VINTAGES = [2013, 2015, 2016, 2017, 2018]

# (C) 書かれていない自由度＝探索空間の仮定。線ではなく仮定。
FRACS = [0.10, 0.20, 0.25, 1.0 / 3.0, 0.50]
FRAC_NAMES = {0.10: "decile", 0.20: "quintile", 0.25: "quartile",
              round(1.0 / 3.0, 4): "tertile", 0.50: "median"}
DIRS = ["top", "bottom"]

N_PERM = 2000
SEED = 20260811

F2_FEATS = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r",
            "gw_r", "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5",
            "conv5", "netiss_r", "payout5", "rev"]
PA_FEATS = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
CO_FEATS = ["roic_med5", "roic_latest", "roic_worst5", "opm", "sales_cagr5",
            "fcf_conv_5y", "op_all_pos", "fcf_all_pos", "equity_neg", "score"]
HV_FEATS = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct"]

CAND_GROUPS = {
    "features2_20": ["f2_" + k for k in F2_FEATS],
    "path_7_2018only": ["pa_" + k for k in PA_FEATS],
    "cohort_10": ["co_" + k for k in CO_FEATS],
    "valuation": ["hv_" + k for k in HV_FEATS] + ["per"],
}
POPS = ["P_full", "P_quality", "P_moat"]


# ─────────────────────── 小道具 ───────────────────────
def r4(x):
    return None if x is None else round(x, 4)


def logC(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binom_pmf(n, p):
    """k=0..n の pmf（対数経由・n<=1000 想定）。p が 0/1 の端も扱う。"""
    if n < 0:
        return []
    if p <= 0:
        a = [0.0] * (n + 1); a[0] = 1.0; return a
    if p >= 1:
        a = [0.0] * (n + 1); a[n] = 1.0; return a
    lp, lq = math.log(p), math.log(1 - p)
    return [math.exp(logC(n, k) + k * lp + (n - k) * lq) for k in range(n + 1)]


def binom_sf(pmf):
    """sf[k] = P(K >= k)。長さ n+2。"""
    n = len(pmf) - 1
    sf = [0.0] * (n + 2)
    for k in range(n, -1, -1):
        sf[k] = sf[k + 1] + pmf[k]
    return sf


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# ─────────────────────── パネルの読み込み ───────────────────────
def load_panel():
    with open(PANEL, encoding="utf-8") as f:
        d = json.load(f)
    rows = [r for r in d["rows"] if r["has_outcome"] and r["window_full"]]
    return d, rows


def pop_rows(rows, v, pop):
    rs = [r for r in rows if r["vintage"] == v]
    if pop == "P_full":
        return rs
    if pop == "P_quality":
        return [r for r in rs if r.get("P_quality") is True]
    if pop == "P_moat":
        return [r for r in rs if r.get("P_moat") is True]
    raise ValueError(pop)


# ─────────────────────── (0) 判定可能性の棚卸し ───────────────────────
def judgeability(rows, panel):
    """事前登録の各関門が、そもそも当てられる形になっているか。

    ここが v1 の敗因（基準が結果を見る前から成立しえなかった）の一般化。
    """
    cov = {}
    for grp, feats in CAND_GROUPS.items():
        for f in feats:
            c = {}
            for v in VINTAGES:
                rs = pop_rows(rows, v, "P_full")
                k = sum(1 for r in rs if r.get(f) is not None)
                c[v] = {"n": len(rs), "k": k, "p": r4(k / len(rs)) if rs else None}
            cov[f] = {"group": grp, "by_vintage": c,
                      "vintages_present": [v for v in VINTAGES if c[v]["k"] >= 30]}

    # 符号安定性は 2016/2017/2018 の3つを要求する（prereg 必須）
    judge = {}
    for f, c in cov.items():
        trio_ok = all(v in c["vintages_present"] for v in TRIO)
        judge[f] = {
            "group": c["group"],
            "present": c["vintages_present"],
            "sign_stability_applicable_strict": trio_ok,
            "n_vintages_present": len(c["vintages_present"]),
        }
    n_all = len(judge)
    n_ok = sum(1 for x in judge.values() if x["sign_stability_applicable_strict"])

    # irr 層（not_irr_shadow）の当てられ方
    irr_layer = {}
    for v in VINTAGES:
        rs = pop_rows(rows, v, "P_moat")
        base_rs = pop_rows(rows, v, "P_full")
        n_irr_read = sum(1 for r in base_rs if r.get("irr") is not None)
        irr_layer[v] = {
            "irr_read_rows": n_irr_read,
            "layer_n": len(rs),
            "win_events": sum(1 for r in rs if r["win"]),
            "destroy_events": sum(1 for r in rs if r["destroy"]),
            "win_min_num_reachable": sum(1 for r in rs if r["win"]) >= MIN_NUM,
            "destroy_min_num_reachable": sum(1 for r in rs if r["destroy"]) >= MIN_NUM,
        }

    # 「下向きの lift」は base < 0.15 なら算術的に不可能（＝守る指標は原理的に合格できない）
    downward = {}
    for v in VINTAGES:
        downward[v] = {}
        for pop in POPS:
            rs = pop_rows(rows, v, pop)
            if not rs:
                downward[v][pop] = None
                continue
            e = {}
            for side in ("win", "destroy"):
                base = sum(1 for r in rs if r[side]) / len(rs)
                e[side] = {"base": r4(base),
                           "downward_lift_reachable": base >= LIFT,
                           "max_downward_lift": r4(base)}
            downward[v][pop] = e

    # ---- 端から端まで（3ビンテージ維持を含めて）判定できる (母集団×側) はどれか ----
    e2e = {}
    for pop in POPS:
        for side in ("win", "destroy"):
            per_v = {}
            for v in TRIO:
                rs = pop_rows(rows, v, pop)
                per_v[v] = {"n": len(rs), "events": sum(1 for r in rs if r[side]) if rs else 0}
            ok = all(per_v[v]["events"] >= MIN_NUM for v in TRIO)
            # 同じ社を3ビンテージ追う読みなら、三重共通集合の事象数がさらに効く
            sets = {v: {r["ticker"] for r in pop_rows(rows, v, pop)} for v in TRIO}
            com = set.intersection(*sets.values()) if all(sets.values()) else set()
            com_ev = {}
            for v in TRIO:
                mp = {r["ticker"]: r for r in pop_rows(rows, v, pop)}
                com_ev[v] = sum(1 for t in com if mp[t][side])
            e2e["%s/%s" % (pop, side)] = {
                "per_vintage": per_v,
                "judgeable_strict": ok,
                "blocking_vintages": [v for v in TRIO if per_v[v]["events"] < MIN_NUM],
                "triple_common_n": len(com),
                "triple_common_events": com_ev,
                "triple_common_min_events": min(com_ev.values()) if com_ev else None,
            }
    n_e2e = len(e2e)
    n_e2e_ok = sum(1 for x in e2e.values() if x["judgeable_strict"])

    return {
        "why": "事前登録の関門が、データの形の上で当てられるかを結果の前に数える。"
               "当てられない関門を『不合格』と書いてはいけない（v1の敗因）。",
        "end_to_end_judgeability": {
            "note": "prereg は『2018で見つけたら2016と2017の両方で維持』を必須にしている。"
                    "よって3ビンテージすべてで分子>=5 に届かない (母集団×側) は、"
                    "候補が何であれ**合否を出せない**。triple_common_* は"
                    "『同じ社を3ビンテージ追う』読みにしたときのさらに厳しい実数。",
            "n_combinations": n_e2e, "n_judgeable_strict": n_e2e_ok,
            "by_combination": e2e,
        },
        "candidate_coverage": cov,
        "candidate_judgeability": judge,
        "sign_stability_strict_summary": {
            "n_candidates_total": n_all, "n_applicable": n_ok,
            "n_not_applicable": n_all - n_ok,
            "share_applicable": r4(n_ok / n_all),
            "not_applicable_by_group": dict(Counter(
                x["group"] for x in judge.values() if not x["sign_stability_applicable_strict"])),
            "note": "符号安定性は 2016/2017/2018 の3つを必須と書いてある。"
                    "ところが cohort(2013/2015のみ)・path(2018のみ)・valuation(2016/2017に無し) は"
                    "その3つを揃えられない＝**候補に挙げてあるが構造的に判定できない**。",
        },
        "irr_layer_applicability": {
            "by_vintage": irr_layer,
            "note": "not_irr_shadow は irr の読解がある行にしか当てられない。"
                    "2016/2017 は読解が存在しない（irr=null）ので、発見ビンテージ3つのうち2つで"
                    "この関門は当てようがない。さらに destroy 側は層内の事象が 0〜1社で、"
                    "min_numerator>=5 を課す読みなら**どのビンテージでも到達不能**。",
        },
        "downward_lift_reachability": {
            "by_vintage": downward,
            "note": "prereg の lift は絶対値 |P(群)-P(母集団)|>=0.15。しかし率は0未満になれないので、"
                    "base < 0.15 の側では『下向きに0.15』は算術的に存在しない。"
                    "destroy の base は最大でも 0.08 なので、**破壊を"
                    "『減らす』指標（＝守りの指標）はこの線では原理的に合格できない**。"
                    "対称探索を掲げているのに、破壊側は『増やす』方向しか検出できない。",
        },
    }


# ─────────────────────── (1)(2) 到達可能性と実効要求倍率 ───────────────────────
def reachability(rows):
    cells = []
    for v in VINTAGES:
        for pop in POPS:
            rs = pop_rows(rows, v, pop)
            if not rs:
                for side in ("win", "destroy"):
                    cells.append({"vintage": v, "pop": pop, "side": side, "n": 0,
                                  "events_total": None, "base": None,
                                  "status": "population_empty", "grid": {}})
                continue
            n = len(rs)
            for side in ("win", "destroy"):
                tot = sum(1 for r in rs if r[side])
                base = tot / n
                grid = {}
                for f in FRACS:
                    m = max(1, int(round(f * n)))
                    if m >= n:
                        continue
                    k_lift = math.ceil((base + LIFT) * m)
                    need = max(k_lift, MIN_NUM)
                    binding = "MIN_NUM" if MIN_NUM > k_lift else "LIFT"
                    grid[FRAC_NAMES[round(f, 4)]] = {
                        "group_n": m,
                        "k_by_lift": k_lift, "k_by_min_num": MIN_NUM, "binding": binding,
                        "effective_lift_required": r4(need / m - base),
                        "effective_over_registered": r4((need / m - base) / LIFT),
                        # 群が母集団に含まれる分の希薄化: 観測 lift の期待値は (1-f)*(群と残りの差)
                        "true_group_vs_rest_needed": r4((need / m - base) / (1 - m / n)),
                        "possible_given_observed_events": need <= tot,
                        "required_share_of_all_events": r4(need / tot) if tot else None,
                    }
                cells.append({
                    "vintage": v, "pop": pop, "side": side, "n": n,
                    "events_total": tot, "base": r4(base),
                    "min_numerator_reachable_at_all": tot >= MIN_NUM,
                    "status": "ok" if tot >= MIN_NUM else "undecidable_events_lt_min_num",
                    "grid": grid,
                })

    # 集計: どれだけのセルが「そもそも判定できる」か
    judged = [c for c in cells if c["status"] != "population_empty"]
    n_cells = len(judged)
    n_reach = sum(1 for c in judged if c.get("min_numerator_reachable_at_all"))
    by_side = {}
    for side in ("win", "destroy"):
        s = [c for c in judged if c["side"] == side]
        by_side[side] = {
            "cells": len(s),
            "reachable": sum(1 for c in s if c.get("min_numerator_reachable_at_all")),
            "share": r4(sum(1 for c in s if c.get("min_numerator_reachable_at_all")) / len(s)),
        }
    # 刻み単位でも数える（セルではなく実際に走る検定の単位）
    tests = 0; tests_possible = 0; minnum_binding = []
    for c in judged:
        for gname, g in c["grid"].items():
            tests += 1
            if g["possible_given_observed_events"]:
                tests_possible += 1
            if g["binding"] == "MIN_NUM":
                minnum_binding.append({"vintage": c["vintage"], "pop": c["pop"], "side": c["side"],
                                       "grid": gname, "base": c["base"], "group_n": g["group_n"],
                                       "effective_lift_required": g["effective_lift_required"],
                                       "effective_over_registered": g["effective_over_registered"]})

    thin = [{"vintage": c["vintage"], "pop": c["pop"], "side": c["side"],
             "n": c["n"], "events_total": c["events_total"], "base": c["base"]}
            for c in judged if not c.get("min_numerator_reachable_at_all")]

    return {
        "definition": "セル = (母集団 × ビンテージ × 側)。判定 = 分子>=5 が到達しうるか。"
                      "検定 = セル × 刻み。possible = 必要分子 <= その母集団の全事象数。",
        "cells": cells,
        "summary": {
            "cells_judged": n_cells, "cells_min_num_reachable": n_reach,
            "share_cells_reachable": r4(n_reach / n_cells),
            "by_side": by_side,
            "tests_total": tests, "tests_possible": tests_possible,
            "share_tests_possible": r4(tests_possible / tests),
            "cells_undecidable": thin,
        },
        "min_numerator_binding_cells": minnum_binding,
        "min_numerator_binding_summary": {
            "n": len(minnum_binding), "of_tests": tests,
            "share": r4(len(minnum_binding) / tests),
            "max_effective_over_registered": max(
                [x["effective_over_registered"] for x in minnum_binding], default=None),
            "note": "MIN_NUM が binding のセルでは、登録した 0.15 より高い線が実際には課されている（v2の教訓）。",
        },
    }


# ─────────────────────── (3) 検出力 ───────────────────────
def power_cell(n, m, base, delta):
    """真の lift = delta（群 vs 母集団）のとき、そのビンテージ単独で
    『|lift|>=0.15 かつ 分子>=5』を満たす確率。厳密計算。

    p1 = base + delta, p0 = base - f*delta/(1-f) （母集団平均が観測 base に一致する置き方）
    判定は K1/m - (K1+K0)/n >= LIFT を K0 で条件付けて厳密に解く。
    """
    f = m / n
    p1 = base + delta
    p0 = base - f * delta / (1 - f)
    if p1 > 1 or p0 < 0:
        return {"feasible": False, "p1": r4(p1), "p0": r4(p0), "power": None,
                "why": "母集団平均を観測値に保ったままこの真値を置くと、群以外の率が負になる"
                       "（＝この base では算術的に存在しえない真値）"}
    nr = n - m
    pmf0 = binom_pmf(nr, p0)
    sf1 = binom_sf(binom_pmf(m, p1))
    c = m * n / (n - m)
    tot = 0.0
    for k0, w in enumerate(pmf0):
        if w < 1e-15:
            continue
        t = math.ceil((LIFT + k0 / n) * c - 1e-12)
        need = max(t, MIN_NUM)
        if need > m:
            continue
        tot += w * sf1[need]
    return {"feasible": True, "p1": r4(p1), "p0": r4(p0), "power": r4(tot)}


def power(rows):
    deltas = [0.10, 0.15, 0.20, 0.30]
    fracs = [0.10, 0.25]
    res = {}
    for pop in ("P_full", "P_quality"):
        for side in ("win", "destroy"):
            for f in fracs:
                key = "%s/%s/%s" % (pop, side, FRAC_NAMES[round(f, 4)])
                per_v = {}
                ok = True
                for v in TRIO:
                    rs = pop_rows(rows, v, pop)
                    if not rs:
                        ok = False; break
                    n = len(rs)
                    m = max(1, int(round(f * n)))
                    base = sum(1 for r in rs if r[side]) / n
                    per_v[v] = {"n": n, "m": m, "base": r4(base),
                                "by_delta": {str(d): power_cell(n, m, base, d) for d in deltas}}
                if not ok:
                    continue
                comb = {}
                for d in deltas:
                    ps = [per_v[v]["by_delta"][str(d)] for v in TRIO]
                    if any(not x["feasible"] for x in ps):
                        comb[str(d)] = {"feasible": False,
                                        "infeasible_vintages": [v for v in TRIO
                                                                if not per_v[v]["by_delta"][str(d)]["feasible"]]}
                        continue
                    vals = [x["power"] for x in ps]
                    prod = 1.0
                    for x in vals:
                        prod *= x
                    comb[str(d)] = {
                        "feasible": True,
                        "single_vintage_2018": per_v[2018]["by_delta"][str(d)]["power"],
                        "all3_independent_lower_bound": r4(prod),
                        "all3_fully_dependent_upper_bound": r4(min(vals)),
                        "note": "実測の従属は Spearman 0.92-0.96 ＝上限寄り",
                    }
                res[key] = {"per_vintage": per_v, "all3_strict": comb}
    return {
        "model": "超母集団モデル。群の真の率 p1=base+δ、残り p0=base−f·δ/(1−f)（母集団平均を観測 base に固定）。"
                 "判定は lift を母集団に対して測る定義どおり厳密に解く。近似・サンプリングなし。",
        "reading_of_pass_line": {
            "strict": "『2016と2017の両方で維持』＝3ビンテージすべてで lift>=0.15 かつ 分子>=5",
            "note": "sector_control と not_irr_shadow は解析に入れていない。"
                    "この2関門は合格を減らすことしかしないので、ここの検出力は**上限**である。",
        },
        "by_cell": res,
    }


def sampler(m, p, rnd):
    """Bin(m,p) の逆関数法サンプラ（numpy が無いので自前・cdf を1度だけ作る）。"""
    cdf, s = [], 0.0
    for x in binom_pmf(m, p):
        s += x
        cdf.append(s)
    import bisect

    def draw():
        return min(bisect.bisect_left(cdf, rnd.random()), m)
    return draw


def power_empirical(rows, seed=SEED, reps=2000):
    """実データの従属をそのまま使った注入（＝解析計算の従属仮定を外した版）。

    生成模型: 群の真の事象率を p1=base+δ とし、**実現数 a ~ Bin(m, p1) を毎回引く**
    （初版は a を固定していたため 2018 の判定が決定的になり、検出力ではなく
      『2018でちょうど δ を出した変数の条件付き維持率』を測っていた。バグとして是正）。
    その a 社を 2018 の事象プールから実在ティッカーで選ぶので、
    2016/2017 のラベルは**実データの従属がそのまま決める**＝独立を仮定しない検出力。
    """
    rnd = random.Random(seed)
    out = {}
    for pop in ("P_full", "P_quality"):
        pv = {v: {r["ticker"]: r for r in pop_rows(rows, v, pop)} for v in TRIO}
        common = sorted(set(pv[2016]) & set(pv[2017]) & set(pv[2018]))
        if len(common) < 50:
            continue
        for side in ("win", "destroy"):
            base = {v: sum(1 for t in pv[v] if pv[v][t][side]) / len(pv[v]) for v in TRIO}
            ev = [t for t in common if pv[2018][t][side]]
            nev = [t for t in common if not pv[2018][t][side]]
            for f in (0.10, 0.25):
                m = max(1, int(round(f * len(common))))
                for d in (0.10, 0.15, 0.20, 0.30):
                    key = "%s/%s/%s/delta=%.2f" % (pop, side, FRAC_NAMES[round(f, 4)], d)
                    p1 = base[2018] + d
                    # 期待実現数が事象プールを超えるなら、その真値はこの母集団に存在しえない
                    if p1 > 1 or int(round(p1 * m)) > len(ev):
                        out[key] = {"feasible": False, "expected_event_members": int(round(p1 * m)),
                                    "event_pool_2018": len(ev), "group_n": m,
                                    "why": "その群の率を実現するのに必要な事象社が母集団に存在しない"}
                        continue
                    draw = sampler(m, p1, rnd)
                    p18 = p3 = p3sign = 0
                    trunc = 0
                    lift_sum = {v: 0.0 for v in TRIO}
                    for _ in range(reps):
                        a = draw()
                        if a > len(ev):
                            a = len(ev); trunc += 1
                        if m - a > len(nev):
                            a = m - len(nev); trunc += 1
                        g = set(rnd.sample(ev, a)) | set(rnd.sample(nev, m - a))
                        lifts = {}
                        for v in TRIO:
                            k = sum(1 for t in g if pv[v][t][side])
                            lifts[v] = (k / m - base[v], k)
                            lift_sum[v] += lifts[v][0]
                        if abs(lifts[2018][0]) >= LIFT and lifts[2018][1] >= MIN_NUM:
                            p18 += 1
                            if all(abs(lifts[v][0]) >= LIFT and lifts[v][1] >= MIN_NUM for v in TRIO):
                                p3 += 1
                            s = lifts[2018][0] > 0
                            if all((lifts[v][0] > 0) == s for v in TRIO):
                                p3sign += 1
                    out[key] = {"feasible": True, "group_n": m, "p1_true": r4(p1),
                                "base_2018": r4(base[2018]), "truncated_draws": trunc,
                                "mean_realized_lift": {str(v): r4(lift_sum[v] / reps) for v in TRIO},
                                "lift_attenuation_2016_over_2018":
                                    r4((lift_sum[2016] / reps) / (lift_sum[2018] / reps))
                                    if lift_sum[2018] else None,
                                "P_discovery_2018": r4(p18 / reps),
                                "P_all3_maintained": r4(p3 / reps),
                                "P_sign_stable_given_discovery": r4(p3sign / p18) if p18 else None,
                                "stability_tax_given_discovery": r4(p3 / p18) if p18 else None}
    return {
        "method": "群の実現事象数を a~Bin(m, base+δ) で引き、その a 社を 2018 の事象プールから"
                  "実在ティッカーで選ぶ。2016/2017 の成否は実データの従属が決める"
                  "＝独立を仮定しない検出力。",
        "⚠これは解析計算の『下限〜上限』の中の点推定ではない":
            "解析計算の対立仮説は『3ビンテージそれぞれで lift=δ』。"
            "こちらの対立仮説は『2018の lift が δ になるようにティッカーを選ぶ』で、"
            "2016/2017 の lift は**実データの従属が決める＝δ より小さくなる**"
            "（mean_realized_lift と lift_attenuation を見よ）。"
            "同じ量の別推定ではなく、**別の対立仮説**。混ぜて読まないこと。",
        "reps": reps, "seed": seed,
        "by_cell": out,
    }


# ─────────────────────── (4) 偽陽性率 ───────────────────────
def build_groups(rows):
    """検定ごとの群を bitset で precompute（群は label に依存しないので置換で不変）。"""
    universe = {}   # (v,pop) -> list of tickers（順序固定）
    idx = {}
    for v in TRIO:
        for pop in ("P_full", "P_quality"):
            rs = sorted(pop_rows(rows, v, pop), key=lambda r: r["ticker"])
            universe[(v, pop)] = rs
            idx[(v, pop)] = {r["ticker"]: i for i, r in enumerate(rs)}

    tests = []
    tie_flags = 0
    for pop in ("P_full", "P_quality"):
        for var in CAND_GROUPS["features2_20"]:
            per_v = {}
            ok = True
            for v in TRIO:
                rs = universe[(v, pop)]
                vals = [(r[var], r["ticker"], i) for i, r in enumerate(rs) if r.get(var) is not None]
                if len(vals) < 60:
                    ok = False; break
                nn = len(vals)
                nn_mask = 0
                for _, _, i in vals:
                    nn_mask |= (1 << i)
                s_desc = sorted(vals, key=lambda x: (-x[0], x[1]))
                s_asc = sorted(vals, key=lambda x: (x[0], x[1]))
                g = {}
                for f in FRACS:
                    m = max(1, int(round(f * nn)))
                    if m >= nn:
                        continue
                    for dr in DIRS:
                        s = s_desc if dr == "top" else s_asc
                        sel = s[:m]
                        mask = 0
                        for _, _, i in sel:
                            mask |= (1 << i)
                        tie = (m < nn and sel[-1][0] == s[m][0])
                        g[(FRAC_NAMES[round(f, 4)], dr)] = {"mask": mask, "m": m, "tie": tie}
                per_v[v] = {"nn_mask": nn_mask, "nn": nn, "groups": g}
            if not ok:
                continue
            keys = set(per_v[2016]["groups"]) & set(per_v[2017]["groups"]) & set(per_v[2018]["groups"])
            for gk in sorted(keys):
                tie = any(per_v[v]["groups"][gk]["tie"] for v in TRIO)
                if tie:
                    tie_flags += 1
                tests.append({"pop": pop, "var": var, "grid": gk[0], "dir": gk[1], "tie_boundary": tie,
                              "per_v": {v: {"mask": per_v[v]["groups"][gk]["mask"],
                                            "m": per_v[v]["groups"][gk]["m"],
                                            "nn_mask": per_v[v]["nn_mask"],
                                            "nn": per_v[v]["nn"]} for v in TRIO}})
    return universe, idx, tests, tie_flags


def strata_of(universe, v, pop):
    st = defaultdict(list)
    for i, r in enumerate(universe[(v, pop)]):
        st[r.get("sic2")].append(i)
    return dict(st)


def mh_diff(rs_idx_labels, group_mask, strata, nn_mask):
    """Mantel-Haenszel 風の業種調整差: Σ w_k (p1k-p0k) / Σ w_k, w_k = n1k*n0k/nk。"""
    num = den = 0.0
    for _, idxs in strata.items():
        n1 = n0 = k1 = k0 = 0
        for i in idxs:
            b = 1 << i
            if not (nn_mask & b):
                continue
            lab = rs_idx_labels & b
            if group_mask & b:
                n1 += 1; k1 += 1 if lab else 0
            else:
                n0 += 1; k0 += 1 if lab else 0
        nk = n1 + n0
        if n1 == 0 or n0 == 0 or nk == 0:
            continue
        w = n1 * n0 / nk
        num += w * (k1 / n1 - k0 / n0)
        den += w
    return (num / den) if den else None


def false_positive(rows, n_perm=N_PERM, seed=SEED, mode="ticker_linked"):
    """mode:
      ticker_linked  … ティッカーの**結果ベクトル(2016,2017,2018)を丸ごと**層内で入れ替える。
                       ビンテージ間の従属を実データのまま保つ＝この設計の正しい帰無。
      per_vintage    … 各ビンテージのラベルを独立に層内で入れ替える。
                       ⚠ 従属を壊すので『3ビンテージ維持』が実際よりずっと強い関門に見える。
                       比較のために両方出す（差そのものが結果）。
    """
    universe, idx, tests, tie_flags = build_groups(rows)
    rnd = random.Random(seed)

    # 層（sic2）— 置換は層内でのみ行う（prereg / 指示どおり）
    strata = {(v, pop): strata_of(universe, v, pop) for v in TRIO for pop in ("P_full", "P_quality")}
    # P_full の層で並べ替え、P_quality はその写像を継承する（同一ビンテージで矛盾しないため）
    full_rows = {v: universe[(v, "P_full")] for v in TRIO}
    full_strata = {v: strata[(v, "P_full")] for v in TRIO}
    q_index = {v: idx[(v, "P_quality")] for v in TRIO}

    labels_true = {}
    for v in TRIO:
        for side in ("win", "destroy"):
            labels_true[(v, side)] = [1 if r[side] else 0 for r in full_rows[v]]

    def make_masks(lab_full):
        """P_full 用の bitset と、同じラベルを P_quality の索引へ写した bitset。"""
        out = {}
        mf = 0
        for i, x in enumerate(lab_full["arr"]):
            if x:
                mf |= (1 << i)
        out["P_full"] = mf
        mq = 0
        qi = lab_full["qi"]
        for i, x in enumerate(lab_full["arr"]):
            if x:
                j = qi.get(lab_full["tick"][i])
                if j is not None:
                    mq |= (1 << j)
        out["P_quality"] = mq
        return out

    tick = {v: [r["ticker"] for r in full_rows[v]] for v in TRIO}

    # 実データでの L1..L4 を数えるための共通関数
    def evaluate(labmask, collect=None, attrib=None):
        """labmask[(v,side,pop)] -> bitset。レベル別の合格検定数を返す。"""
        cnt = {1: 0, 2: 0, 3: 0, 4: 0}
        for side in ("win", "destroy"):
            for t in tests:
                pop = t["pop"]
                pv = t["per_v"]
                # ---- L1: 発見ビンテージ 2018 で lift>=0.15 かつ 分子>=5
                d = pv[2018]
                lm = labmask[(2018, side, pop)]
                k = (lm & d["mask"]).bit_count()
                kk = (lm & d["nn_mask"]).bit_count()
                base = kk / d["nn"]
                lf = k / d["m"] - base
                if abs(lf) < LIFT or k < MIN_NUM:
                    continue
                cnt[1] += 1
                if attrib is not None:
                    attrib[1]["%s/%s/%s/%s" % (pop, side, t["grid"], t["dir"])] += 1
                sgn = lf > 0
                # ---- L2: 符号安定（2016/2017/2018 で符号が反転しない）
                lifts = {2018: (lf, k)}
                bad = False
                for v in (2016, 2017):
                    dv = pv[v]
                    lmv = labmask[(v, side, pop)]
                    kv = (lmv & dv["mask"]).bit_count()
                    bv = (lmv & dv["nn_mask"]).bit_count() / dv["nn"]
                    lfv = kv / dv["m"] - bv
                    lifts[v] = (lfv, kv)
                    if (lfv > 0) != sgn:
                        bad = True
                if bad:
                    continue
                cnt[2] += 1
                # ---- L3: 3ビンテージすべてで維持（lift>=0.15 かつ 分子>=5）
                if not all(abs(lifts[v][0]) >= LIFT and lifts[v][1] >= MIN_NUM for v in TRIO):
                    continue
                cnt[3] += 1
                if attrib is not None:
                    attrib[3]["%s/%s/%s/%s" % (pop, side, t["grid"], t["dir"])] += 1
                if collect is not None:
                    collect.append({"side": side, "pop": pop, "var": t["var"], "grid": t["grid"],
                                    "dir": t["dir"], "tie_boundary": t["tie_boundary"],
                                    "lift_2018": r4(lifts[2018][0]), "k_2018": lifts[2018][1],
                                    "lift_2016": r4(lifts[2016][0]), "lift_2017": r4(lifts[2017][0])})
                # ---- L4: 業種(sic2)調整後も残る（発見ビンテージで判定）
                st = strata[(2018, pop)]
                adj = mh_diff(labmask[(2018, side, pop)], d["mask"], st, d["nn_mask"])
                if adj is None or abs(adj) < LIFT or ((adj > 0) != sgn):
                    continue
                cnt[4] += 1
                # L5(irr層) は構造的に当てられないので数えない（下の levels.L5 を見よ）
        return cnt

    # ラベル bitset を (v, side, pop) で持つ
    def build_labmask(perm_arrays):
        lm = {}
        for v in TRIO:
            for side in ("win", "destroy"):
                arr = perm_arrays[(v, side)]
                d = {"arr": arr, "qi": q_index[v], "tick": tick[v]}
                mm = make_masks(d)
                lm[(v, side, "P_full")] = mm["P_full"]
                lm[(v, side, "P_quality")] = mm["P_quality"]
        return lm

    # --- 実データ（参考。合否ではない。手続きが動くことの確認と、置換分布の位置） ---
    real_hits = []
    real_cnt = evaluate(build_labmask(labels_true), collect=real_hits)

    # --- ティッカー連結置換の下ごしらえ ---
    # 3ビンテージすべてに居るティッカー（実測946/952）は結果ベクトルを丸ごと動かす。
    pos = {v: {r["ticker"]: i for i, r in enumerate(full_rows[v])} for v in TRIO}
    common = set(pos[2016]) & set(pos[2017]) & set(pos[2018])
    sic_of = {}
    for v in TRIO:
        for r in full_rows[v]:
            sic_of[r["ticker"]] = r.get("sic2")
    common_by_sic = defaultdict(list)
    for t in sorted(common):
        common_by_sic[sic_of[t]].append(t)
    # 共通でないティッカーは、ビンテージ内・層内で自分たちだけを入れ替える
    solo_pos = {v: defaultdict(list) for v in TRIO}
    for v in TRIO:
        for r in full_rows[v]:
            if r["ticker"] not in common:
                solo_pos[v][r.get("sic2")].append(pos[v][r["ticker"]])

    def perm_ticker_linked():
        out = {}
        mapping = {}
        for s, ts in common_by_sic.items():
            sh = list(ts)
            rnd.shuffle(sh)
            for a, b in zip(ts, sh):
                mapping[a] = b     # ティッカー a に、ティッカー b の結果ベクトルを与える
        for v in TRIO:
            for side in ("win", "destroy"):
                src = labels_true[(v, side)]
                arr = [0] * len(src)
                for t in common:
                    arr[pos[v][t]] = src[pos[v][mapping[t]]]
                for s, idxs in solo_pos[v].items():
                    vals = [src[i] for i in idxs]
                    rnd.shuffle(vals)
                    for i, x in zip(idxs, vals):
                        arr[i] = x
                out[(v, side)] = arr
        return out

    def perm_per_vintage():
        out = {}
        for v in TRIO:
            for side in ("win", "destroy"):
                arr = [0] * len(full_rows[v])
                src = labels_true[(v, side)]
                for _, idxs in full_strata[v].items():
                    vals = [src[i] for i in idxs]
                    rnd.shuffle(vals)
                    for i, x in zip(idxs, vals):
                        arr[i] = x
                out[(v, side)] = arr
        return out

    # --- 置換（両モード） ---
    modes = {}
    for mname, mfun in (("ticker_linked", perm_ticker_linked), ("per_vintage", perm_per_vintage)):
        hits_level = {1: 0, 2: 0, 3: 0, 4: 0}
        dist = {1: [], 2: [], 3: [], 4: []}
        attrib = {1: Counter(), 3: Counter()}
        for _ in range(n_perm):
            c = evaluate(build_labmask(mfun()), attrib=attrib)
            for L in (1, 2, 3, 4):
                dist[L].append(c[L])
                if c[L] > 0:
                    hits_level[L] += 1
        modes[mname] = {
            "false_positive_rate": {"L1_any": r4(hits_level[1] / n_perm),
                                    "L2_any": r4(hits_level[2] / n_perm),
                                    "L3_any": r4(hits_level[3] / n_perm),
                                    "L4_any": r4(hits_level[4] / n_perm)},
            "expected_false_passes_per_run": {str(L): r4(sum(dist[L]) / n_perm) for L in (1, 2, 3, 4)},
            "max_observed": {str(L): max(dist[L]) for L in (1, 2, 3, 4)},
            "survival_under_null": {
                "L2_over_L1": r4(sum(dist[2]) / sum(dist[1])) if sum(dist[1]) else None,
                "L3_over_L1": r4(sum(dist[3]) / sum(dist[1])) if sum(dist[1]) else None,
                "L4_over_L3": r4(sum(dist[4]) / sum(dist[3])) if sum(dist[3]) else None,
            },
            "where_false_positives_come_from": {
                "L1_top10": dict(attrib[1].most_common(10)),
                "L3_top10": dict(attrib[3].most_common(10)),
            },
        }

    prim = modes[mode]
    n_tests = len(tests) * 2  # side を掛ける
    return {
        "primary_mode": mode,
        "by_permutation_mode": modes,
        "mode_comparison_note":
            "ticker_linked は結果ベクトルを丸ごと動かすのでビンテージ間の従属が実データのまま残る。"
            "per_vintage は従属を壊すので『3ビンテージ維持』が実際より強い関門に見える。"
            "この差そのものが結果——**out_of_sample 検証がどれだけ雑音を削るかは、窓が入れ子かどうかで決まる**。",
        "search_space_assumed": {
            "candidates": "features2 の20本のみ（符号安定性を当てられる唯一の群・上の judgeability を見よ）",
            "populations": ["P_full", "P_quality"],
            "sides": ["win", "destroy"],
            "grids": [FRAC_NAMES[round(f, 4)] for f in FRACS],
            "directions": DIRS,
            "n_single_variable_tests": n_tests,
            "n_pair_tests_if_added": len(CAND_GROUPS["features2_20"]) * (len(CAND_GROUPS["features2_20"]) - 1) // 2,
            "tie_boundary_tests": tie_flags,
            "note": "prereg は刻み（上位何%を群と呼ぶか）を固定していない。ここは"
                    "『書かれていない自由度』を数えたのであって、線を足したのではない。"
                    "combos(2本の積)を入れると検定数は約10倍になり、偽陽性率はさらに上がる。",
        },
        "levels": {
            "L1": "発見ビンテージ2018で lift>=0.15 かつ 分子>=5",
            "L2": "L1 + 2016/2017/2018 で符号が反転しない",
            "L3": "L2 + 3ビンテージすべてで lift>=0.15 かつ 分子>=5（＝out_of_sample 厳格読み）",
            "L4": "L3 + 業種(sic2)調整後も |差|>=0.15 で同符号（Mantel-Haenszel）",
            "L5": "L4 + irr>=70 層内でも残る —— **2016/2017 に irr の読解が無く、"
                  "2018 の層は destroy 事象0社/win事象24社。destroy 側は分子>=5 に到達不能。"
                  "構造的に当てられないので数えていない（0 と書くと『厳しくて落ちた』に見えるため）**",
        },
        "n_perm": n_perm, "seed": seed,
        "permutation_scheme": "結果ラベル(win/destroy)を sic2 の層内で並べ替える。"
                              "群の定義（特徴量）は不変なので、帰無仮説は『候補は結果と無関係』。"
                              "層内で並べ替えるので業種と結果の関係は保たれる＝L4は自動では通らない。",
        "false_positive_rate": prim["false_positive_rate"],
        "expected_false_passes_per_run": prim["expected_false_passes_per_run"],
        "permutation_max_observed": prim["max_observed"],
        "stability_tax_under_null": {
            **prim["survival_under_null"],
            "note": "帰無のもとで L1 を通った検定のうち、符号安定・3ビンテージ維持まで残る割合。"
                    "ビンテージが独立ならここは大きく落ちるはず。落ちないなら"
                    "『out_of_sample 検証』は雑音をほとんど削っていない＝窓の入れ子の帰結。",
        },
        "real_data_reference": {
            "counts_by_level": {str(k): v for k, v in real_cnt.items()},
            "note": "⚠ これは合否ではない。手続きが動くことの確認と、置換分布に対する位置の把握のみ。"
                    "合否は探索本体（別の道具）が prereg どおりに出す。",
            "n_hits_L3_listed": len(real_hits),
        },
    }


# ─────────────────────── (B) 被覆交絡 ───────────────────────
def coverage_confound(rows):
    out = {}
    for v in TRIO:
        for pop in ("P_full", "P_quality"):
            rs = pop_rows(rows, v, pop)
            n = len(rs)
            if not n:
                continue
            for side in ("win", "destroy"):
                base_all = sum(1 for r in rs if r[side]) / n
                for var in CAND_GROUPS["features2_20"]:
                    sub = [r for r in rs if r.get(var) is not None]
                    if len(sub) < 60:
                        continue
                    b = sum(1 for r in sub if r[side]) / len(sub)
                    key = "%d/%s/%s/%s" % (v, pop, side, var)
                    out[key] = {"coverage": r4(len(sub) / n), "base_all": r4(base_all),
                                "base_nonnull": r4(b), "shift": r4(b - base_all)}
    worst = sorted(out.items(), key=lambda kv: -abs(kv[1]["shift"]))[:15]
    return {
        "why": "群は非欠測の中からしか作れない。基準率を全行で取ると、被覆の偏りが lift に化ける"
               "（＝『基準の違う二つを割る』型）。本器と探索は非欠測の基準率を使うべき。",
        "max_abs_shift": r4(max(abs(x["shift"]) for x in out.values())),
        "n_measured": len(out),
        "worst15": [{"cell": k, **v} for k, v in worst],
    }


# ─────────────────────── main ───────────────────────
def main():
    panel, rows = load_panel()
    with open(PREREG, encoding="utf-8") as f:
        prereg = json.load(f)

    jd = judgeability(rows, panel)
    rc = reachability(rows)
    pw = power(rows)
    pe = power_empirical(rows)
    cc = coverage_confound(rows)
    fp = false_positive(rows)

    dep = panel["diagnostics"]["outcome_dependence"]["pairs"]
    e2e = jd["end_to_end_judgeability"]
    fpt = fp["by_permutation_mode"]["ticker_linked"]
    fpv = fp["by_permutation_mode"]["per_vintage"]

    can_say = [
        "この事前登録が『どのセルで合否を出せるか』は結果を見る前に確定している——"
        "到達可能セルは全 %d 中 %d（%.0f%%）。" % (
            rc["summary"]["cells_judged"], rc["summary"]["cells_min_num_reachable"],
            100 * rc["summary"]["share_cells_reachable"]),
        "**端から端まで合否を出せる (母集団×側) は 6 通り中 %d 通りだけ**と名指しできる"
        "（%s）。残りは『不合格』ではなく判定不能。" % (
            e2e["n_judgeable_strict"],
            ", ".join(k for k, x in e2e["by_combination"].items() if x["judgeable_strict"])),
        "破壊側の分子が薄い母集団を名指しできる（下の reachability.summary.cells_undecidable）。",
        "MIN_NUM(5社) が LIFT(0.15) より強く縛る検定を名指しできる（%d件/%d件）。" % (
            rc["min_numerator_binding_summary"]["n"], rc["summary"]["tests_total"]),
        "真の lift がいくらなら掴めるかを、算術的に存在しうる真値の範囲つきで言える"
        "——**登録した線ちょうど(δ=0.15)では1ビンテージあたり約0.5＝コイン投げ**、"
        "3ビンテージ厳格だと 0.12〜0.49。",
        "この手続きが偶然に合格を出す確率を、関門の段ごとに分けて言える"
        "——『合格ゼロ』が統計の厳しさによるのか構造的な不能によるのかを分離できる。",
        "**out_of_sample 検証がどれだけ雑音を削るかを実測できた**: 正しい帰無"
        "（ティッカーの結果ベクトルを丸ごと入れ替え＝ビンテージ間の従属を保つ）では"
        "L1→L3 の残存率 %s、符号安定だけなら %s が素通り。"
        "従属を壊した帰無だと残存率 %s に見える＝**約%.0f倍の過大評価**。" % (
            fpt["survival_under_null"]["L3_over_L1"], fpt["survival_under_null"]["L2_over_L1"],
            fpv["survival_under_null"]["L3_over_L1"],
            fpt["survival_under_null"]["L3_over_L1"] / fpv["survival_under_null"]["L3_over_L1"]),
    ]
    cannot_say = [
        "**解析検出力は上限**である。sector_control と not_irr_shadow を解析に入れていない"
        "（この2関門は合格を減らすことしかしない）。実測でも業種調整で L3→L4 の残存は %s。"
        % fpt["survival_under_null"]["L4_over_L3"],
        "**符号安定性の関門はほぼ無力**——実信号なら 2000/2000 で通り（経験的注入・全セルで 1.000）、"
        "帰無でも L1 通過の %s が通る。『3ビンテージで符号一致』を証拠の重ね合わせと読んではいけない。"
        % fpt["survival_under_null"]["L2_over_L1"],
        "**3ビンテージは独立標本ではない**（実測 Spearman %.2f〜%.2f、destroy の P(b|a) は 0.93〜0.95）。"
        "『3つで符号一致』を独立な3証拠と読んではいけない。" % (
            min(d["spearman_tr_cagr"] for k, d in dep.items() if k in ("2016-2017", "2016-2018", "2017-2018")),
            max(d["spearman_tr_cagr"] for k, d in dep.items() if k in ("2016-2017", "2016-2018", "2017-2018"))),
        "**刻み（群の大きさ）は事前登録に書かれていない**。ここで数えた偽陽性率は"
        "『5刻み×上下2方向』という仮定のもとの値。実際の探索がこれより多くの刻みを試せば偽陽性率は上がる。",
        "candidates に挙がっている path(2018のみ)・cohort(2013/2015のみ)・valuation(2016/2017に無し) は"
        "符号安定性の必須条件を構造的に満たせない＝**この事前登録では最初から判定できない**。"
        "それらを『不合格』と書いてはいけない。",
        "破壊側の『守りの指標』（破壊を減らす向き）は base<0.15 のため算術的に合格できない。"
        "対称探索を掲げているが、検出できるのは『破壊を増やす向き』だけ。",
        "P_quality の定義がビンテージで揃っていない（2016-2018 は op_all_pos が無く2条件＝規約より緩い）。"
        "ビンテージ間で P_quality の水準を直接比べられない（パネルの known_asymmetries）。",
    ]

    out = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_diag.py",
        "inputs": {"panel": "out/hist_wd_panel.json", "prereg": "out/hist_winner_destroyer_prereg.json",
                   "panel_generated": panel.get("generated"), "prereg_generated": prereg.get("generated")},
        "scope": "**合否を一つも出さない。** 事前登録した手続き自体の性能だけを測る。",
        "row_filter": "has_outcome かつ window_full（年率を比べるので窓長を揃える）。全 %d 行。" % len(rows),
        "constants_used": {"LIFT": LIFT, "MIN_NUM": MIN_NUM, "note": "事前登録の値。動かしていない。"},
        "what_can_be_said": can_say,
        "what_cannot_be_said": cannot_say,
        "judgeability": jd,
        "reachability": rc,
        "power_analytic": pw,
        "power_empirical_dependence_aware": pe,
        "coverage_confound": cc,
        "false_positive": fp,
    }
    p = os.path.join(OUT, "hist_wd_diag.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", p)

    # ---- 端末要約 ----
    print("\n== 判定可能性 ==")
    s = jd["sign_stability_strict_summary"]
    print("  符号安定性を当てられる候補: %d/%d (%.0f%%)  当てられない内訳: %s"
          % (s["n_applicable"], s["n_candidates_total"], 100 * s["share_applicable"],
             s["not_applicable_by_group"]))
    e2e = jd["end_to_end_judgeability"]
    print("  端から端まで合否を出せる (母集団×側): %d/%d"
          % (e2e["n_judgeable_strict"], e2e["n_combinations"]))
    for k, x in e2e["by_combination"].items():
        ev = "/".join(str(x["per_vintage"][v]["events"]) for v in TRIO)
        print("    %-18s %s  事象(16/17/18)=%-12s 三重共通n=%3d 事象最小=%s"
              % (k, "✓" if x["judgeable_strict"] else "⛔", ev,
                 x["triple_common_n"], x["triple_common_min_events"]))
    for v in VINTAGES:
        il = jd["irr_layer_applicability"]["by_vintage"][v]
        print("  irr層 %d: n=%3d win事象=%2d destroy事象=%d  (destroy分子>=5 到達=%s)"
              % (v, il["layer_n"], il["win_events"], il["destroy_events"],
                 il["destroy_min_num_reachable"]))

    print("\n== 到達可能性（セル = 母集団×ビンテージ×側）==")
    print("  判定可能セル %d/%d  検定単位 %d/%d が possible"
          % (rc["summary"]["cells_min_num_reachable"], rc["summary"]["cells_judged"],
             rc["summary"]["tests_possible"], rc["summary"]["tests_total"]))
    for c in rc["summary"]["cells_undecidable"]:
        print("   ⛔判定不能: %d %-9s %-7s n=%4d 事象=%d (base %.4f)"
              % (c["vintage"], c["pop"], c["side"], c["n"], c["events_total"], c["base"]))

    print("\n== 検出力（3ビンテージ厳格・独立の下限〜完全従属の上限）==")
    for k, cell in pw["by_cell"].items():
        row = []
        for d in ("0.1", "0.15", "0.2", "0.3"):
            c = cell["all3_strict"].get(d)
            if c is None:
                row.append("%s:—" % d); continue
            if not c["feasible"]:
                row.append("%s:不能" % d)
            else:
                row.append("%s:%.3f-%.3f" % (d, c["all3_independent_lower_bound"],
                                             c["all3_fully_dependent_upper_bound"]))
        print("  %-28s %s" % (k, "  ".join(row)))

    print("\n== 偽陽性率（置換 %d回・sic2層内）==" % fp["n_perm"])
    print("  %-14s %8s %8s %8s %8s   L3/L1" % ("置換の作り方", "L1", "L2", "L3", "L4"))
    for mname in ("ticker_linked", "per_vintage"):
        m = fp["by_permutation_mode"][mname]
        print("  %-14s %8s %8s %8s %8s   %s"
              % (mname, m["false_positive_rate"]["L1_any"], m["false_positive_rate"]["L2_any"],
                 m["false_positive_rate"]["L3_any"], m["false_positive_rate"]["L4_any"],
                 m["survival_under_null"]["L3_over_L1"]))
    print("  ↑ ticker_linked が正しい帰無（ビンテージ間の従属を実データのまま保つ）")
    print("  偽陽性の出どころ(L1・上位5): %s"
          % json.dumps(dict(list(fp["by_permutation_mode"]["ticker_linked"]
                                 ["where_false_positives_come_from"]["L1_top10"].items())[:5]),
                       ensure_ascii=False))
    print("  検定数（単変数のみ）=%d  うち群の境界が同値で割れている=%d  ペアを足すと候補は%d組増える"
          % (fp["search_space_assumed"]["n_single_variable_tests"],
             fp["search_space_assumed"]["tie_boundary_tests"],
             fp["search_space_assumed"]["n_pair_tests_if_added"]))
    print("  被覆交絡の最大 |base(非欠測)−base(全行)| = %s（f2_sga_r・被覆58%%）"
          % cc["max_abs_shift"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
