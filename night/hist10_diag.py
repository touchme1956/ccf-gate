#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_diag.py — 合否を出す前に、事前登録 v3（複利10%）の手続きそのものの性能を測る。

事前登録: out/hist10_prereg.json（結果を見る前に固定・commit a081edf）
入力    : out/hist10_targets.json（目的変数 y10/y_persist/y_biz）＋ out/hist_wd_panel.json（候補列）
出力    : out/hist10_diag.json

**この道具は合否を一つも出さない。** 出すのは「この事前登録は、そもそも何を判定できる形になっているか」だけ。
どの変数が勝ったかには一切触れない（探索本体は別の道具）。

────────────────────────────────────────────────────────────
なぜ結果より先にこれを測るのか
────────────────────────────────────────────────────────────
v1: 「合格ゼロ」と報告したが、後から数えたら 2013/2015 は恒久毀損が 0社/3社しか無く、
    分子>=5 は**結果を見る前から成立しえなかった**＝指標の性能を一度も測っていなかった。
v2: MIN_NUM が LIFT より強く縛るセルがあり、登録した線より高い線がこっそり課されていた。
    検出力は δ=0.15 ちょうどで **0.49＝コイン投げ**。
v3(本件): 目的を 15%→10% にしたので基準率が約2倍になった。その代わり MIN_NUM を 5→20 にした。
    **二つ同時に動かしている**ので、検出力の改善を「10%にしたおかげ」と読むのは
    『基準の違う二つを割る』型。よって本器は 2×2（ハードル15/10 × MIN_NUM 5/20）で分解する。

────────────────────────────────────────────────────────────
測り方の決定と、その理由
────────────────────────────────────────────────────────────
A) 行は has_outcome かつ window_full のみ。年率を比べるので窓長を揃える。

B) 基準率は「その変数が非欠測の行」で取る。被覆率は 58%〜100% と大きく違い、
   群を非欠測から作りながら基準率を全行で取ると被覆の偏りがそのまま lift に化ける。
   その差（被覆交絡）も別に測って出す。

C) 群の刻み（上位何%を群と呼ぶか）は事前登録に書かれていない＝研究者の自由度。
   10/20/25/33/50% × 上下2方向 を「探索空間の仮定」として明示し、その仮定のもとで数える。
   **線を足したのではなく、書かれていない自由度を数えている。**

D) **両方向**（lift>0 の up と lift<0 の down）を最初から別に数える。
   事前登録は |lift|>=0.15 と絶対値で書いてあるので、up と down は同じ関門の2つの向き。
   ただし到達可能性は向きで**まったく違う**（下の (1) を見よ）。

E) MIN_NUM の読み方は二つありうる。**主は字義どおり k（群の中の事象社数）>=20**。
   参考として min(k, m−k)>=20（両側の精度で見る読み）も出すが、**事前登録の外**と明示する。

F) 検出力は超母集団モデルで解析計算し、モンテカルロで検算する（両方出して一致を見る）。
   群の真の率 p1 = base ± δ、残り p0 は母集団平均が観測 base に一致するように置く。

G) 偽陽性率は**会社単位で全ビンテージ同時に**結果を並べ替える（sic2 の層内）。
   ビンテージ内で独立に混ぜると従属が壊れ、v2 の実測で 33倍の過小評価になる。
   角度A(単変量)・角度D(加法スコア)・角度E(木) は**探索の自由度が桁で違う**ので別々に測る。
"""
import bisect
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")
PANEL = os.path.join(OUT, "hist_wd_panel.json")
TARGETS = os.path.join(OUT, "hist10_targets.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")

LIFT = 0.15        # 事前登録の線（動かさない）
MIN_NUM = 20       # 事前登録の線（動かさない）
LEGACY_MIN_NUM = 5     # v1/v2 の線（比較のためだけに使う）
TRIO = [2016, 2017, 2018]
DISCOVERY = 2018
VINTAGES = [2013, 2015, 2016, 2017, 2018]

FRACS = [0.10, 0.20, 0.25, 1.0 / 3.0, 0.50]
FRAC_NAMES = {0.10: "decile", 0.20: "quintile", 0.25: "quartile",
              round(1.0 / 3.0, 4): "tertile", 0.50: "median"}
DIRS = ["top", "bottom"]

N_PERM = 2000
SEED = 20260812

F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r",
      "gw_r", "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5",
      "conv5", "netiss_r", "payout5", "rev"]
F2C = ["f2_" + k for k in F2]
POPS = ["P_full", "P_quality"]

# 角度D/E で使う特徴量の部分集合（被覆で決める。complete-case の大きさが変わる）
COV90 = ["aturn", "cagr5", "rev", "capex_r", "accel", "streak_rev", "rnd_r", "cash_r",
         "accr", "fcfpos5", "gw_r", "opm", "streak_opm", "opmD5"]   # 3ビンテージとも被覆>=0.90
SUBSETS = {"cov90_14": ["f2_" + k for k in COV90], "all20": F2C}

CUT_QS = [0.25, 0.50, 0.75]     # 角度E の分割点
N_FOLDS = 5                     # 角度E の外側 fold


# ─────────────────────── 小道具 ───────────────────────
def r4(x):
    return None if x is None else round(x, 4)


def logC(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binom_pmf(n, p):
    if n < 0:
        return []
    if p <= 0:
        a = [0.0] * (n + 1); a[0] = 1.0; return a
    if p >= 1:
        a = [0.0] * (n + 1); a[n] = 1.0; return a
    lp, lq = math.log(p), math.log(1 - p)
    return [math.exp(logC(n, k) + k * lp + (n - k) * lq) for k in range(n + 1)]


def binom_cdf(pmf):
    """cdf[k] = P(K <= k)。長さ n+1。"""
    out, s = [], 0.0
    for x in pmf:
        s += x
        out.append(s)
    return out


def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = q * (len(xs) - 1)
    lo = int(math.floor(i)); hi = int(math.ceil(i))
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def make_sampler(m, p, rnd):
    cdf = binom_cdf(binom_pmf(m, p))
    def draw():
        return min(bisect.bisect_left(cdf, rnd.random()), m)
    return draw


# ─────────────────────── 読み込み ───────────────────────
def load():
    with open(PANEL, encoding="utf-8") as f:
        panel = json.load(f)
    with open(TARGETS, encoding="utf-8") as f:
        tg = json.load(f)
    with open(PREREG, encoding="utf-8") as f:
        prereg = json.load(f)
    tmap = {(r["ticker"], r["vintage"]): r for r in tg["rows"]}
    rows = []
    for r in panel["rows"]:
        if not (r["has_outcome"] and r["window_full"]):
            continue
        t = tmap.get((r["ticker"], r["vintage"]))
        if t is None:
            continue
        q = dict(r)
        for k in ("y10", "y_persist", "y_biz", "y_biz_strict", "biz_rate", "mult_rate"):
            q[k] = t.get(k)
        rows.append(q)
    return panel, tg, prereg, rows


def pop_rows(rows, v, pop):
    rs = [r for r in rows if r["vintage"] == v]
    if pop == "P_full":
        return rs
    if pop == "P_quality":
        return [r for r in rs if r.get("P_quality") is True]
    if pop == "P_moat":
        return [r for r in rs if r.get("P_moat") is True]
    raise ValueError(pop)


# ─────────────────────── (0) 目的変数ごとの判定可能性 ───────────────────────
def target_judgeability(rows):
    """事前登録の pass_line を字義どおり当てられる目的変数はどれか（結果を見る前に確定する）。"""
    out = {}
    for y in ("y10", "y_persist", "y_biz"):
        per_v = {}
        for v in VINTAGES:
            rs = [r for r in pop_rows(rows, v, "P_full") if r.get(y) is not None]
            per_v[v] = {"n_defined": len(rs),
                        "events": sum(1 for r in rs if r[y]),
                        "base": r4(sum(1 for r in rs if r[y]) / len(rs)) if rs else None}
        trio_ok = all(per_v[v]["n_defined"] >= 30 for v in TRIO)
        # 候補列のうち TRIO 3つすべてに存在するのは f2_ だけ（構造的制約）
        cand_ok = {}
        for grp, cols in (("features2_20", F2C), ("cohort", ["co_roic_med5"]),
                          ("path_2018only", ["pa_rf5"]), ("valuation", ["hv_pe_pct", "per"])):
            ok = True
            for v in TRIO:
                rs = pop_rows(rows, v, "P_full")
                if not rs or all(sum(1 for r in rs if r.get(c) is not None) < 60 for c in cols):
                    ok = False
            cand_ok[grp] = ok
        out[y] = {
            "by_vintage": per_v,
            "vintages_defined": [v for v in VINTAGES if per_v[v]["n_defined"] >= 30],
            "sign_stability_2016_17_18_applicable": trio_ok,
            "candidate_groups_applicable_on_trio": cand_ok,
            "verdict": ("字義どおりの合否を出せる" if trio_ok
                        else "**事前登録の sign_stability(2016/2017/2018) を構造的に満たせない＝合否を出せない**"),
        }
    return {
        "why": "当てられない関門を『不合格』と書いてはいけない（v1の敗因）。結果の前に数える。",
        "by_target": out,
        "summary": {
            "judgeable": [y for y, x in out.items() if x["sign_stability_2016_17_18_applicable"]],
            "not_judgeable": [y for y, x in out.items() if not x["sign_stability_2016_17_18_applicable"]],
            "note": "y_persist は 2013 の入口でしか作れず（前半窓が2013起点でしか復元できない）、"
                    "y_biz は分解の在庫が 2013/2015/2018 にしか無い。"
                    "**角度B・角度C は事前登録の字義どおりでは判定できない**。"
                    "別の年で見るなら『事前登録の外』と明示すること（stopping_rule）。",
            "candidate_note": "TRIO 3つすべてに存在する候補列は features2 の20本だけ。"
                              "cohort(2013/2015)・path(2018のみ)・valuation(2016/2017に無し) は"
                              "候補に挙がっているが符号安定性を当てられない。",
        },
    }


# ─────────────────────── (1) 両方向の到達可能性 ───────────────────────
def reach_cell(n, k_tot, m, base, min_num):
    """観測された (n, k_tot, m) のもとで up/down それぞれ『合格しうるか』を厳密に数える。

    lift = k/m − base（base は観測された母集団の率で固定）。
    up  : k >= ceil((base+L)*m) かつ k >= min_num かつ k <= min(m, k_tot)
    down: k <= floor((base−L)*m) かつ k >= min_num かつ k >= m−(n−k_tot)（非事象で埋めきれるか）
    """
    need_up = max(math.ceil((base + LIFT) * m - 1e-12), min_num)
    up_cap = min(m, k_tot)
    up_ok = need_up <= up_cap
    # down
    k_max = math.floor((base - LIFT) * m + 1e-12)
    k_floor_fill = max(0, m - (n - k_tot))     # 群を非事象だけでは埋めきれない場合の下限
    need_down = max(min_num, k_floor_fill)
    down_ok = (k_max >= need_down) and (base - LIFT) >= 0
    # 実効要求
    eff_up = need_up / m - base
    up_binding = "MIN_NUM" if min_num > math.ceil((base + LIFT) * m - 1e-12) else "LIFT"
    m_min_down = math.ceil(min_num / (base - LIFT)) if base - LIFT > 0 else None
    return {
        "group_n": m,
        "up": {
            "k_needed": need_up, "k_available": up_cap, "possible": up_ok,
            "binding": up_binding,
            "effective_lift_required": r4(eff_up),
            "effective_over_registered": r4(eff_up / LIFT),
            "required_share_of_all_events": r4(need_up / k_tot) if k_tot else None,
        },
        "down": {
            "k_allowed_max": k_max, "k_needed_min": need_down, "possible": down_ok,
            # down では MIN_NUM は「線を上げる」のではなく「群を小さくできない」形で効く
            "binding": ("MIN_NUM_infeasible" if (not down_ok and (base - LIFT) >= 0
                                                 and k_max < min_num)
                        else ("LIFT" if down_ok else "BASE_TOO_LOW")),
            "effective_lift_required": r4(-LIFT) if down_ok else None,
            "min_group_n_for_min_num": m_min_down,
        },
    }


def reachability(rows):
    cells = []
    labels = [("y10", "y10"), ("win15", "win"), ("destroy15", "destroy")]
    for lab_name, col in labels:
        for v in VINTAGES:
            for pop in POPS + ["P_moat"]:
                rs = [r for r in pop_rows(rows, v, pop) if r.get(col) is not None]
                if len(rs) < 30:
                    cells.append({"label": lab_name, "vintage": v, "pop": pop,
                                  "n": len(rs), "status": "population_too_small"})
                    continue
                n = len(rs)
                k_tot = sum(1 for r in rs if r[col])
                base = k_tot / n
                grid = {}
                for f in FRACS:
                    m = max(1, int(round(f * n)))
                    if m >= n:
                        continue
                    grid[FRAC_NAMES[round(f, 4)]] = reach_cell(n, k_tot, m, base, MIN_NUM)
                cells.append({"label": lab_name, "vintage": v, "pop": pop, "n": n,
                              "events": k_tot, "base": r4(base), "status": "ok", "grid": grid})

    def tally(lab_name, side, pops=None):
        got = tot = 0
        for c in cells:
            if c["label"] != lab_name or c["status"] != "ok":
                continue
            if pops is not None and c["pop"] not in pops:
                continue
            for g in c["grid"].values():
                tot += 1
                if g[side]["possible"]:
                    got += 1
        return {"possible": got, "tests": tot, "share": r4(got / tot) if tot else None}

    summary = {}
    for lab_name, _ in labels:
        summary[lab_name] = {
            "up": tally(lab_name, "up"), "down": tally(lab_name, "down"),
            # P_moat は 2016/2017 に無く n=61-63 と極小＝構造的に判定できない母集団。
            # headline がここに支配されないよう、除いた版も必ず出す。
            "up_excl_P_moat": tally(lab_name, "up", POPS),
            "down_excl_P_moat": tally(lab_name, "down", POPS),
        }

    # 「down が到達可能な最小の群の大きさ」を主要セルで名指し
    min_group = []
    for c in cells:
        if c["status"] != "ok" or c["label"] != "y10" or c["vintage"] not in TRIO:
            continue
        mm = c["grid"]["quartile"]["down"]["min_group_n_for_min_num"]
        min_group.append({"vintage": c["vintage"], "pop": c["pop"], "n": c["n"],
                          "base": c["base"], "min_group_n_for_down": mm,
                          "min_fraction_for_down": r4(mm / c["n"]) if mm else None,
                          "grids_that_fail_down": [g for g, x in c["grid"].items()
                                                   if not x["down"]["possible"]]})

    # MIN_NUM の別読み（事前登録の外）: min(k, m−k) >= 20
    alt = []
    for c in cells:
        if c["status"] != "ok" or c["label"] != "y10":
            continue
        for gname, g in c["grid"].items():
            m = g["group_n"]
            # down 側で min(k, m−k)>=20 を課すと m−k>=20 も要る＝群がさらに大きくないと不可
            need = max(MIN_NUM, m - (c["n"] - c["events"]))
            kmax = math.floor((c["base"] - LIFT) * m + 1e-12)
            ok_lit = g["down"]["possible"]
            ok_alt = ok_lit and (m - kmax) >= MIN_NUM
            if ok_lit != ok_alt:
                alt.append({"vintage": c["vintage"], "pop": c["pop"], "grid": gname})
    return {
        "definition": "セル = (目的ラベル × 母集団 × ビンテージ)。検定単位 = セル × 刻み。"
                      "possible = 観測された n・事象数・群の大きさのもとで、その向きの合格が算術的に起こりうるか。",
        "min_num_reading": "主 = 字義どおり k（群の中の事象社数）>=20。"
                           "参考の別読み min(k,m−k)>=20 は**事前登録の外**（下の alt_reading）。",
        "cells": cells,
        "summary_by_label": summary,
        "down_direction_min_group": min_group,
        "alt_reading_changes": {"n_tests_flipped": len(alt), "tests": alt[:40],
                                "note": "別読みにすると down 側の可否が変わる検定。合否には使わない。"},
    }


# ─────────────────────── (2) 実効要求倍率 ───────────────────────
def effective_requirement(reach):
    up_bind, down_infeasible = [], []
    for c in reach["cells"]:
        if c.get("status") != "ok":
            continue
        for gname, g in c["grid"].items():
            if g["up"]["binding"] == "MIN_NUM":
                up_bind.append({"label": c["label"], "vintage": c["vintage"], "pop": c["pop"],
                                "grid": gname, "group_n": g["group_n"], "base": c["base"],
                                "effective_lift_required": g["up"]["effective_lift_required"],
                                "effective_over_registered": g["up"]["effective_over_registered"]})
            if g["down"]["binding"] == "MIN_NUM_infeasible":
                down_infeasible.append({"label": c["label"], "vintage": c["vintage"], "pop": c["pop"],
                                        "grid": gname, "group_n": g["group_n"], "base": c["base"],
                                        "k_allowed_max": g["down"]["k_allowed_max"],
                                        "min_group_n_for_min_num": g["down"]["min_group_n_for_min_num"]})
    tot = sum(len(c["grid"]) for c in reach["cells"] if c.get("status") == "ok")

    # headline が『登録の対象でない目的ラベル』や『構造的に判定できない母集団』に
    # 支配されないよう、v3 が実際に登録した組み合わせ(y10 × P_full/P_quality)だけの数も出す
    def narrow(label=None, excl_moat=True):
        t = ub = di = dp = 0
        for c in reach["cells"]:
            if c.get("status") != "ok":
                continue
            if label and c["label"] != label:
                continue
            if excl_moat and c["pop"] == "P_moat":
                continue
            for g in c["grid"].values():
                t += 1
                ub += 1 if g["up"]["binding"] == "MIN_NUM" else 0
                di += 1 if g["down"]["binding"] == "MIN_NUM_infeasible" else 0
                dp += 1 if g["down"]["possible"] else 0
        return {"tests": t, "up_min_num_binding": ub, "down_infeasible_by_min_num": di,
                "down_possible": dp}

    return {
        "why": "v2 では MIN_NUM(5社) が LIFT(0.15) より強く縛るセルがあり、"
               "登録した線より高い線がこっそり課されていた。v3 は MIN_NUM を 20 にしたので"
               "**同じことが起きていないかを結果の前に数える**。",
        "registered_scope_only": {
            "definition": "v3 が実際に登録した組み合わせ ＝ 目的 y10 × 母集団(P_full/P_quality)。"
                          "win15/destroy15 は比較用のラベル、P_moat は 2016/2017 に irr の読解が無く"
                          "n=61-63 で構造的に判定できない母集団なので、**headline はこちらで読む**。",
            "y10_excl_P_moat": narrow("y10"),
            "all_labels_excl_P_moat": narrow(None),
        },
        "up_direction": {
            "n_binding": len(up_bind), "of_tests": tot,
            "share": r4(len(up_bind) / tot) if tot else None,
            "max_effective_over_registered": max([x["effective_over_registered"] for x in up_bind],
                                                 default=None),
            "cells": sorted(up_bind, key=lambda x: -x["effective_over_registered"])[:40],
            "read": "up 側では MIN_NUM は『線を上げる』形で効く。実効/登録 が 1.0 を超えるセルは"
                    "登録した 0.15 より高い線を実際には課されている。",
        },
        "down_direction": {
            "n_infeasible_by_min_num": len(down_infeasible), "of_tests": tot,
            "share": r4(len(down_infeasible) / tot) if tot else None,
            "cells": down_infeasible[:60],
            "read": "**down 側では MIN_NUM は線を上げない。群を小さくできない形で効く**——"
                    "群の率が base−0.15 以下でなければならないのに、その群の中に事象が20社要る。"
                    "よって群は最低 20/(base−0.15) 社ないと、効果がどれだけ強くても合格できない。"
                    "up と down で MIN_NUM の効き方が構造的に違う（v2 では気づけなかった非対称）。",
        },
    }


# ─────────────────────── (3) 検出力 ───────────────────────
def power_cell(n, m, base, delta, direction, min_num, lift=LIFT, num_rule="events"):
    """真の効果 δ（群 vs 木集団）のとき、そのビンテージ単独で
    『その向きに lift>=線 かつ 分子>=min_num』を満たす確率。厳密計算。

    num_rule="events"  … 字義どおり k（群の中の事象社数）>=min_num【事前登録】
    num_rule="support" … 主張を支える側の数 >=min_num（down では m−k）【事前登録の外・感度】
    """
    f = m / n
    if direction == "up":
        p1 = base + delta
        p0 = base - f * delta / (1 - f)
    else:
        p1 = base - delta
        p0 = base + f * delta / (1 - f)
    if not (0 <= p1 <= 1) or not (0 <= p0 <= 1):
        return {"feasible": False, "p1": r4(p1), "p0": r4(p0), "power": None,
                "why": "母集団平均を観測値に保ったままこの真値を置くと群外の率が[0,1]を出る"
                       "（＝この base では算術的に存在しえない真値）"}
    nr = n - m
    pmf0 = binom_pmf(nr, p0)
    pmf1 = binom_pmf(m, p1)
    cdf1 = binom_cdf(pmf1)
    sf1 = [0.0] * (m + 2)
    for k in range(m, -1, -1):
        sf1[k] = sf1[k + 1] + pmf1[k]
    c = m * n / (n - m)
    tot = 0.0
    for k0, w in enumerate(pmf0):
        if w < 1e-15:
            continue
        if direction == "up":
            t = math.ceil((lift + k0 / n) * c - 1e-12)
            need = max(t, min_num)
            if need > m:
                continue
            tot += w * sf1[need]
        else:
            t = math.floor((k0 / n - lift) * c + 1e-12)
            if num_rule == "events":
                hi = min(t, m); lo = min_num
            else:                       # support: m−k >= min_num
                hi = min(t, m - min_num); lo = 0
            if hi < lo:
                continue
            tot += w * (cdf1[hi] - (cdf1[lo - 1] if lo > 0 else 0.0))
    return {"feasible": True, "p1": r4(p1), "p0": r4(p0), "power": r4(tot)}


def power_mc(n, m, base, delta, direction, min_num, rnd, reps=20000, lift=LIFT):
    f = m / n
    p1 = base + delta if direction == "up" else base - delta
    p0 = base - f * delta / (1 - f) if direction == "up" else base + f * delta / (1 - f)
    if not (0 <= p1 <= 1) or not (0 <= p0 <= 1):
        return None
    d1 = make_sampler(m, p1, rnd)
    d0 = make_sampler(n - m, p0, rnd)
    hit = 0
    for _ in range(reps):
        k1 = d1(); k0 = d0()
        lf = k1 / m - (k1 + k0) / n
        if k1 >= min_num and ((lf >= lift) if direction == "up" else (lf <= -lift)):
            hit += 1
    return r4(hit / reps)


def power(rows, rnd):
    deltas = [0.10, 0.15, 0.20]
    res, comp = {}, {}
    for pop in POPS:
        for f in (0.10, 0.25):
            for direction in ("up", "down"):
                key = "%s/%s/%s" % (pop, FRAC_NAMES[round(f, 4)], direction)
                per_v, ok = {}, True
                for v in TRIO:
                    rs = [r for r in pop_rows(rows, v, pop) if r.get("y10") is not None]
                    if not rs:
                        ok = False; break
                    n = len(rs); m = max(1, int(round(f * n)))
                    base = sum(1 for r in rs if r["y10"]) / n
                    per_v[v] = {"n": n, "m": m, "base": r4(base),
                                "by_delta": {str(d): power_cell(n, m, base, d, direction, MIN_NUM)
                                             for d in deltas}}
                if not ok:
                    continue
                all3 = {}
                for d in deltas:
                    ps = [per_v[v]["by_delta"][str(d)] for v in TRIO]
                    if any(not x["feasible"] for x in ps):
                        all3[str(d)] = {"feasible": False}
                        continue
                    vals = [x["power"] for x in ps]
                    prod = 1.0
                    for x in vals:
                        prod *= x
                    all3[str(d)] = {"feasible": True,
                                    "single_vintage_2018": per_v[2018]["by_delta"][str(d)]["power"],
                                    "all3_independent_lower_bound": r4(prod),
                                    "all3_fully_dependent_upper_bound": r4(min(vals))}
                res[key] = {"per_vintage": per_v, "all3_strict": all3}

    # ---- 2×2 分解: ハードル(15/10) × MIN_NUM(5/20) ----
    grid_d = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    for pop in POPS:
        for direction in ("up", "down"):
            for lab, col, mn, tag in (("hurdle15/min5", "win", LEGACY_MIN_NUM, "v1/v2の設定"),
                                      ("hurdle15/min20", "win", MIN_NUM, "MIN_NUMだけ動かす"),
                                      ("hurdle10/min5", "y10", LEGACY_MIN_NUM, "ハードルだけ動かす"),
                                      ("hurdle10/min20", "y10", MIN_NUM, "v3の登録")):
                rs = [r for r in pop_rows(rows, DISCOVERY, pop) if r.get(col) is not None]
                n = len(rs); m = max(1, int(round(0.25 * n)))
                base = sum(1 for r in rs if r[col]) / n
                cell = power_cell(n, m, base, 0.15, direction, mn)
                mc = power_mc(n, m, base, 0.15, direction, mn, rnd)
                by_d = {}
                for dd in grid_d:
                    by_d[str(dd)] = power_cell(n, m, base, dd, direction, mn).get("power")
                sd = math.sqrt(base * (1 - base) / m)
                comp["%s/%s/%s" % (pop, direction, lab)] = {
                    "meaning": tag, "n": n, "group_n": m, "base": r4(base),
                    "power_analytic_delta_0.15": cell.get("power"),
                    "power_mc_delta_0.15": mc,
                    "feasible": cell["feasible"],
                    "mc_vs_analytic_diff": (r4(abs(mc - cell["power"]))
                                            if (mc is not None and cell.get("power") is not None) else None),
                    "power_by_delta": by_d,
                    "group_rate_sd": r4(sd),
                    "sigma_from_line_at_delta_0.20": r4(0.05 / sd),
                    "discrimination_0.20_over_0.10": (r4(by_d["0.2"] / by_d["0.1"])
                                                      if (by_d.get("0.2") is not None
                                                          and by_d.get("0.1")) else None),
                }

    # ---- down 方向の検出力の非単調性（MIN_NUM が強い効果ほど落とす）----
    nonmono = {}
    fine = [0.05 * i for i in range(1, 9)]
    for pop in POPS:
        for mn, lab in ((MIN_NUM, "min20"), (LEGACY_MIN_NUM, "min5")):
            rs = [r for r in pop_rows(rows, DISCOVERY, pop) if r.get("y10") is not None]
            n = len(rs); m = max(1, int(round(0.25 * n)))
            base = sum(1 for r in rs if r["y10"]) / n
            curve, curve_alt = {}, {}
            for d in fine:
                curve[round(d, 2)] = power_cell(n, m, base, d, "down", mn).get("power")
                curve_alt[round(d, 2)] = power_cell(n, m, base, d, "down", mn,
                                                    num_rule="support").get("power")
            vals = [(d, p) for d, p in curve.items() if p is not None]
            peak = max(vals, key=lambda x: x[1]) if vals else (None, None)
            mono = all((curve[a] is None or curve[b] is None or curve[a] <= curve[b] + 1e-12)
                       for a, b in zip(sorted(curve)[:-1], sorted(curve)[1:]))
            vals_a = [(d, p) for d, p in curve_alt.items() if p is not None]
            mono_alt = all((curve_alt[a] is None or curve_alt[b] is None
                            or curve_alt[a] <= curve_alt[b] + 1e-12)
                           for a, b in zip(sorted(curve_alt)[:-1], sorted(curve_alt)[1:]))
            # 期待事象数が MIN_NUM を割る δ
            d_break = None
            for d in fine:
                if (base - d) * m < mn:
                    d_break = round(d, 2); break
            nonmono["%s/%s" % (pop, lab)] = {
                "base": r4(base), "group_n": m, "min_num": mn,
                "power_curve_down": {str(k): v for k, v in curve.items()},
                "peak_delta": peak[0], "peak_power": peak[1],
                "power_at_delta_0.30": curve.get(0.3),
                "monotone_in_effect_size": mono,
                "delta_where_expected_events_fall_below_min_num": d_break,
                "alt_reading_support_count": {
                    "curve": {str(k): v for k, v in curve_alt.items()},
                    "monotone_in_effect_size": mono_alt,
                    "peak_power": (max(p for _, p in vals_a) if vals_a else None),
                    "note": "**事前登録の外**。『分子』を"
                            "『主張を支える側の数』(down なら群の中の非事象社数 m−k)と読んだ版。"
                            "この読みなら非単調は消える＝**非単調はデータではなく"
                            "MIN_NUM の読み方が作っている**ことの証明。合否には使わない。",
                },
            }
    # ---- MC 検算（主要セル）----
    checks = []
    for pop in POPS:
        for direction in ("up", "down"):
            for d in deltas:
                rs = [r for r in pop_rows(rows, DISCOVERY, pop) if r.get("y10") is not None]
                n = len(rs); m = max(1, int(round(0.25 * n)))
                base = sum(1 for r in rs if r["y10"]) / n
                a = power_cell(n, m, base, d, direction, MIN_NUM)
                b = power_mc(n, m, base, d, direction, MIN_NUM, rnd)
                checks.append({"pop": pop, "dir": direction, "delta": d,
                               "analytic": a.get("power"), "mc": b,
                               "abs_diff": (r4(abs(a["power"] - b)) if (a.get("power") is not None
                                                                        and b is not None) else None)})
    return {
        "model": "超母集団モデル。群の真の率 p1=base±δ、残り p0 は母集団平均が観測 base に一致する置き方。"
                 "判定は lift を母集団に対して測る定義どおり厳密に解く（近似なし）。MC で検算。",
        "by_cell": res,
        "hurdle_x_minnum_2x2": {
            "why": "v3 は**ハードルと MIN_NUM を同時に動かしている**ので、検出力の改善を"
                   "『10%にしたおかげ』と読むのは基準の違う二つを割る型。分解して測る。",
            "setting": "発見ビンテージ2018・quartile群",
            "⚠δ=0.15 で約0.50 になるのは構造であってデータの性質ではない":
                "真の効果が登録した線とちょうど等しいとき、標本分布は線の上に半分・下に半分に割れるので"
                "検出力は必ず約0.5になる。**v2 が『0.49＝コイン投げ』と記録したのはこの構造の帰結**で、"
                "設計の良し悪しを表す数字ではない。設計の差は δ≠線 のところにしか出ないので"
                " power_by_delta を必ず見ること。",
            "cells": comp,
        },
        "non_monotone_power_down": {
            "why": "down 方向では『群の率が低い』ことが合格条件なのに、同じ群の中に事象が"
                   "MIN_NUM 社要る。**効果が強いほど群の事象は減る**ので、"
                   "ある δ を超えると検出力が下がりはじめる＝"
                   "**強い真の発見ほど落とす**という向きの誤り。up 方向には存在しない非対称。",
            "cells": nonmono,
        },
        "mc_verification": {"reps": 20000, "cells": checks,
                            "note": "解析計算と MC の差。MC の標準誤差は最大 sqrt(0.25/20000)=0.0035。"
                                    "この範囲に収まっていれば解析計算の実装は正しい。"},
    }


# ─────────────────────── (4) 偽陽性率 ───────────────────────
def build_universes(rows):
    """各 (universe名, vintage) の行リストと、そこに載る検定用の群 bitmask を precompute。"""
    U = {}
    for v in TRIO:
        for pop in POPS:
            U[("A", pop, v)] = sorted(pop_rows(rows, v, pop), key=lambda r: r["ticker"])
            for sname, cols in SUBSETS.items():
                U[(sname, pop, v)] = sorted(
                    [r for r in pop_rows(rows, v, pop)
                     if all(r.get(c) is not None for c in cols) and r.get("y10") is not None],
                    key=lambda r: r["ticker"])
    return U


def masks_single(U):
    """角度A: 単変量 × 刻み × 上下。群は結果ラベルに依存しないので置換で不変。"""
    tests = []
    for pop in POPS:
        for var in F2C:
            per_v, ok = {}, True
            for v in TRIO:
                rs = U[("A", pop, v)]
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
                        mask = 0
                        for _, _, i in s[:m]:
                            mask |= (1 << i)
                        g[(FRAC_NAMES[round(f, 4)], dr)] = (mask, m)
                per_v[v] = {"nn_mask": nn_mask, "nn": nn, "g": g}
            if not ok:
                continue
            keys = set(per_v[2016]["g"]) & set(per_v[2017]["g"]) & set(per_v[2018]["g"])
            for gk in sorted(keys):
                tests.append({"pop": pop, "var": var, "grid": gk[0], "dir": gk[1],
                              "per_v": {v: {"mask": per_v[v]["g"][gk][0], "m": per_v[v]["g"][gk][1],
                                            "nn_mask": per_v[v]["nn_mask"], "nn": per_v[v]["nn"]}
                                        for v in TRIO}})
    return tests


def masks_conjunction(U, sname):
    """角度E: 深さ2の木 ＝ 条件1つ（深さ1）と条件2つの積（深さ2）の全列挙。"""
    cols = SUBSETS[sname]
    per_pop = {}
    for pop in POPS:
        conds = {}       # v -> list of (mask, m)
        names = None
        for v in TRIO:
            rs = U[(sname, pop, v)]
            n = len(rs)
            lst, nm = [], []
            for c in cols:
                xs = [r[c] for r in rs]
                for q in CUT_QS:
                    cut = quantile(xs, q)
                    hi = 0
                    for i, r in enumerate(rs):
                        if r[c] >= cut:
                            hi |= (1 << i)
                    full = (1 << n) - 1
                    lo = full & ~hi
                    lst.append((hi, hi.bit_count())); nm.append("%s>=q%d" % (c, int(q * 100)))
                    lst.append((lo, lo.bit_count())); nm.append("%s<q%d" % (c, int(q * 100)))
            conds[v] = lst
            names = nm
        per_pop[pop] = {"conds": conds, "names": names,
                        "n": {v: len(U[(sname, pop, v)]) for v in TRIO}}
    return per_pop


def perm_engine(rows, U, seed=SEED):
    """会社単位で全ビンテージ同時に y10 を並べ替える（sic2 の層内）。"""
    rnd = random.Random(seed)
    full = {v: sorted(pop_rows(rows, v, "P_full"), key=lambda r: r["ticker"]) for v in TRIO}
    lab_true = {v: {r["ticker"]: (1 if r["y10"] else 0) for r in full[v] if r.get("y10") is not None}
                for v in TRIO}
    sic_of = {}
    for v in TRIO:
        for r in full[v]:
            sic_of[r["ticker"]] = r.get("sic2")
    common = set(lab_true[2016]) & set(lab_true[2017]) & set(lab_true[2018])
    by_sic = defaultdict(list)
    for t in sorted(common):
        by_sic[sic_of[t]].append(t)
    solo = {v: defaultdict(list) for v in TRIO}
    for v in TRIO:
        for t in lab_true[v]:
            if t not in common:
                solo[v][sic_of[t]].append(t)

    def draw(shuffle=True):
        if not shuffle:
            return {v: dict(lab_true[v]) for v in TRIO}
        mapping = {}
        for _, ts in by_sic.items():
            sh = list(ts); rnd.shuffle(sh)
            for a, b in zip(ts, sh):
                mapping[a] = b
        out = {}
        for v in TRIO:
            cur = {}
            for t in common:
                cur[t] = lab_true[v][mapping[t]]
            for _, ts in solo[v].items():
                vals = [lab_true[v][t] for t in ts]
                rnd.shuffle(vals)
                for t, x in zip(ts, vals):
                    cur[t] = x
            out[v] = cur
        return out

    def to_masks(labs):
        """(universe, pop, v) -> (label bitmask, n_defined, k_defined)"""
        mm = {}
        for key, rs in U.items():
            v = key[2]
            lm = 0; nd = 0; kd = 0
            lv = labs[v]
            for i, r in enumerate(rs):
                x = lv.get(r["ticker"])
                if x is None:
                    continue
                nd += 1
                if x:
                    lm |= (1 << i); kd += 1
            mm[key] = (lm, nd, kd)
        return mm
    return draw, to_masks, {"n_common_tickers": len(common),
                            "n_strata": len(by_sic),
                            "n_solo_by_vintage": {str(v): sum(len(x) for x in solo[v].values())
                                                  for v in TRIO}}


def mh_diff(lab_mask, group_mask, strata, nn_mask):
    """Mantel-Haenszel 風の業種調整差: Σ w_k (p1k−p0k) / Σ w_k, w_k = n1k·n0k/nk。"""
    num = den = 0.0
    for idxs in strata.values():
        n1 = n0 = k1 = k0 = 0
        for i in idxs:
            b = 1 << i
            if not (nn_mask & b):
                continue
            lab = lab_mask & b
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


def eval_single(tests, mm, strata=None):
    """角度A の評価。戻り: レベル別の合格検定数（up/down 別）。

    L4 は業種(sic2)調整（発見ビンテージで判定・prereg の sector_control）。
    """
    cnt = {"L1_up": 0, "L1_down": 0, "L3_up": 0, "L3_down": 0, "L3_any": 0, "L4_any": 0}
    hits = []
    for t in tests:
        pop = t["pop"]
        lm, _, _ = mm[("A", pop, DISCOVERY)]
        d = t["per_v"][DISCOVERY]
        k = (lm & d["mask"]).bit_count()
        base = (lm & d["nn_mask"]).bit_count() / d["nn"]
        lf = k / d["m"] - base
        if abs(lf) < LIFT or k < MIN_NUM:
            continue
        up = lf > 0
        cnt["L1_up" if up else "L1_down"] += 1
        ok = True
        lifts = {DISCOVERY: (r4(lf), k)}
        for v in (2016, 2017):
            lmv, _, _ = mm[("A", pop, v)]
            dv = t["per_v"][v]
            kv = (lmv & dv["mask"]).bit_count()
            bv = (lmv & dv["nn_mask"]).bit_count() / dv["nn"]
            lfv = kv / dv["m"] - bv
            lifts[v] = (r4(lfv), kv)
            if (lfv > 0) != up or abs(lfv) < LIFT or kv < MIN_NUM:
                ok = False
        if ok:
            cnt["L3_up" if up else "L3_down"] += 1
            cnt["L3_any"] += 1
            adj = None
            if strata is not None:
                adj = mh_diff(lm, d["mask"], strata[pop], d["nn_mask"])
                if adj is not None and abs(adj) >= LIFT and ((adj > 0) == up):
                    cnt["L4_any"] += 1
            hits.append({"pop": pop, "var": t["var"], "grid": t["grid"], "dir": t["dir"],
                         "direction": "up" if up else "down", "sector_adjusted_2018": r4(adj),
                         "lifts": {str(k2): v2 for k2, v2 in lifts.items()}})
    return cnt, hits


def score_masks(rs, cols, lm, nd_mask_ignore=None):
    """角度D: 中央値分割の向きをデータから決め、加法スコアの群 bitmask を作る。"""
    n = len(rs)
    full = (1 << n) - 1
    base_k = lm.bit_count()
    base = base_k / n if n else 0
    feats = []
    for c in cols:
        xs = [r[c] for r in rs]
        med = quantile(xs, 0.5)
        hi = 0
        for i, r in enumerate(rs):
            if r[c] >= med:
                hi |= (1 << i)
        mhi = hi.bit_count()
        if mhi == 0 or mhi == n:
            continue
        khi = (lm & hi).bit_count()
        lf = khi / mhi - base
        good = hi if lf >= 0 else (full & ~hi)
        feats.append({"col": c, "good": good, "abs_lift": abs(lf), "side": "hi" if lf >= 0 else "lo"})
    feats.sort(key=lambda x: (-x["abs_lift"], x["col"]))
    return feats, full, base


def add_planes(planes, mask, full):
    carry = mask
    for j in range(len(planes)):
        new = planes[j] ^ carry
        carry = planes[j] & carry
        planes[j] = new
        if carry == 0:
            break
    return planes


def count_masks(masks, n_bits, full):
    """複数の bitmask について『いくつに含まれるか』の bit-plane を作る。"""
    planes = [0] * (n_bits.bit_length() + 1)
    for m in masks:
        add_planes(planes, m, full)
    return planes


def exact_mask(planes, val, full):
    out = full
    for j, p in enumerate(planes):
        out &= p if (val >> j) & 1 else (full & ~p)
    return out


def ge_mask(planes, s, jmax, full):
    out = 0
    for v in range(s, jmax + 1):
        out |= exact_mask(planes, v, full)
    return out


def eval_additive(U, sname, mm):
    """角度D の評価。向きは発見ビンテージのデータから決める（＝探索の自由度に含める）。"""
    cols = SUBSETS[sname]
    n_pass = 0
    hits = []
    for pop in POPS:
        rs18 = U[(sname, pop, DISCOVERY)]
        if len(rs18) < 100:
            continue
        lm18, nd18, _ = mm[(sname, pop, DISCOVERY)]
        feats, full18, base18 = score_masks(rs18, cols, lm18)
        if not feats:
            continue
        Js = sorted({j for j in (3, 5, 8, 10, len(feats)) if 1 <= j <= len(feats)})
        # 各ビンテージで、同じ列・同じ向きの群を作る（cut は各年の中央値＝コホート内の相対）
        per_v = {}
        for v in TRIO:
            rs = U[(sname, pop, v)]
            n = len(rs); full = (1 << n) - 1
            good = {}
            for ft in feats:
                c = ft["col"]
                xs = [r[c] for r in rs]
                med = quantile(xs, 0.5)
                hi = 0
                for i, r in enumerate(rs):
                    if r[c] >= med:
                        hi |= (1 << i)
                good[c] = hi if ft["side"] == "hi" else (full & ~hi)
            per_v[v] = {"rs": rs, "n": n, "full": full, "good": good}
        for J in Js:
            sel = [ft["col"] for ft in feats[:J]]
            planes = {v: count_masks([per_v[v]["good"][c] for c in sel], J, per_v[v]["full"])
                      for v in TRIO}
            for s in range(1, J + 1):
                for mode in ("ge", "le"):
                    ok = True; up = None; rec = {}
                    for v in TRIO:
                        if mode == "ge":
                            g = ge_mask(planes[v], s, J, per_v[v]["full"])
                        else:
                            g = per_v[v]["full"] & ~ge_mask(planes[v], s + 1, J, per_v[v]["full"])
                        m = g.bit_count()
                        if m < MIN_NUM or m >= per_v[v]["n"]:
                            ok = False; break
                        lmv, ndv, kdv = mm[(sname, pop, v)]
                        k = (lmv & g).bit_count()
                        base = kdv / ndv if ndv else 0
                        lf = k / m - base
                        if up is None:
                            up = lf > 0
                        if k < MIN_NUM or abs(lf) < LIFT or ((lf > 0) != up):
                            ok = False; break
                        rec[v] = (r4(lf), k, m)
                    if ok:
                        n_pass += 1
                        hits.append({"pop": pop, "subset": sname, "J": J, "s": s, "mode": mode,
                                     "direction": "up" if up else "down",
                                     "per_v": {str(v): rec[v] for v in TRIO}})
    return n_pass, hits


def eval_conjunction(cj, mm, sname):
    """角度E の評価（in-sample選択→3ビンテージ維持）。cj は masks_conjunction の出力。"""
    n_pass = 0
    hits = []
    for pop in POPS:
        P = cj[pop]
        n18 = P["n"][DISCOVERY]
        if n18 < 100:
            continue
        lm18, nd18, kd18 = mm[(sname, pop, DISCOVERY)]
        base18 = kd18 / nd18 if nd18 else 0
        conds18 = P["conds"][DISCOVERY]
        nc = len(conds18)
        # 深さ1
        cand = []
        for i in range(nc):
            g, m = conds18[i]
            if m < MIN_NUM or m >= n18:
                continue
            k = (lm18 & g).bit_count()
            lf = k / m - base18
            if abs(lf) >= LIFT and k >= MIN_NUM:
                cand.append((i, None, lf > 0))
        # 深さ2（条件の積・全列挙）
        for i in range(nc):
            gi, mi = conds18[i]
            if mi < MIN_NUM:
                continue
            for j in range(i + 1, nc):
                gj, _ = conds18[j]
                g = gi & gj
                m = g.bit_count()
                if m < MIN_NUM or m >= n18:
                    continue
                k = (lm18 & g).bit_count()
                lf = k / m - base18
                if abs(lf) >= LIFT and k >= MIN_NUM:
                    cand.append((i, j, lf > 0))
        for (i, j, up) in cand:
            ok = True; rec = {}
            for v in TRIO:
                cs = P["conds"][v]
                g = cs[i][0] if j is None else (cs[i][0] & cs[j][0])
                m = g.bit_count()
                if m < MIN_NUM or m >= P["n"][v]:
                    ok = False; break
                lmv, ndv, kdv = mm[(sname, pop, v)]
                k = (lmv & g).bit_count()
                base = kdv / ndv if ndv else 0
                lf = k / m - base
                if k < MIN_NUM or abs(lf) < LIFT or ((lf > 0) != up):
                    ok = False; break
                rec[v] = (r4(lf), k, m)
            if ok:
                n_pass += 1
                hits.append({"pop": pop, "subset": sname,
                             "rule": (P["names"][i] if j is None
                                      else P["names"][i] + " ∧ " + P["names"][j]),
                             "direction": "up" if up else "down",
                             "per_v": {str(v): rec[v] for v in TRIO}})
    return n_pass, hits


def eval_conjunction_cv(cj, mm, sname, fold_idx):
    """角度E の外側fold版。**選択は train、評価は held-out**。事前登録の『外側foldの性能のみ』。

    合格 = 5つの fold の held-out 群を合併したときの |lift| >= 0.15 かつ 分子>=20。
    """
    n_pass = 0
    detail = {}
    for pop in POPS:
        P = cj[pop]
        n18 = P["n"][DISCOVERY]
        if n18 < 100:
            continue
        lm18, nd18, kd18 = mm[(sname, pop, DISCOVERY)]
        base18 = kd18 / nd18 if nd18 else 0
        conds = P["conds"][DISCOVERY]
        nc = len(conds)
        folds = fold_idx[(sname, pop)]
        oof_group = 0
        for fi, (tr_mask, te_mask) in enumerate(folds):
            ntr = tr_mask.bit_count()
            lm_tr = lm18 & tr_mask
            k_tr_all = lm_tr.bit_count()
            b_tr = k_tr_all / ntr if ntr else 0
            best = None
            min_tr = max(3, int(round(MIN_NUM * ntr / n18)))
            for i in range(nc):
                gi = conds[i][0] & tr_mask
                mi = gi.bit_count()
                if mi < min_tr:
                    # 条件iの train 内の大きさが下限未満なら、iを含む積はすべて下限未満（部分集合）
                    continue
                if mi < ntr:
                    lf = (lm_tr & gi).bit_count() / mi - b_tr
                    if best is None or abs(lf) > abs(best[0]):
                        best = (lf, i, None)
                for j in range(i + 1, nc):
                    g = gi & conds[j][0]
                    m = g.bit_count()
                    if m < min_tr or m >= ntr:
                        continue
                    lf = (lm_tr & g).bit_count() / m - b_tr
                    if best is None or abs(lf) > abs(best[0]):
                        best = (lf, i, j)
            if best is None:
                continue
            _, i, j = best
            g = conds[i][0] if j is None else (conds[i][0] & conds[j][0])
            oof_group |= (g & te_mask)
        m = oof_group.bit_count()
        k = (lm18 & oof_group).bit_count()
        lf = (k / m - base18) if m else 0.0
        passed = m > 0 and k >= MIN_NUM and abs(lf) >= LIFT
        detail[pop] = {"oof_group_n": m, "oof_k": k, "oof_lift": r4(lf), "passed": passed}
        if passed:
            n_pass += 1
    return n_pass, detail


def make_folds(U, sname, rnd):
    out = {}
    for pop in POPS:
        rs = U[(sname, pop, DISCOVERY)]
        n = len(rs)
        idx = list(range(n))
        rnd.shuffle(idx)
        folds = []
        for f in range(N_FOLDS):
            te = [i for kk, i in enumerate(idx) if kk % N_FOLDS == f]
            te_mask = 0
            for i in te:
                te_mask |= (1 << i)
            full = (1 << n) - 1
            folds.append((full & ~te_mask, te_mask))
        out[(sname, pop)] = folds
    return out


def false_positive(rows, n_perm=N_PERM, seed=SEED, e_perm=None):
    U = build_universes(rows)
    tests_A = masks_single(U)
    cj = {s: masks_conjunction(U, s) for s in SUBSETS}
    rnd = random.Random(seed + 7)
    folds = {}
    for s in SUBSETS:
        folds.update(make_folds(U, s, rnd))
    draw, to_masks, pinfo = perm_engine(rows, U, seed)

    # 業種調整用の層（発見ビンテージ・母集団ごと）
    strata = {}
    for pop in POPS:
        st = defaultdict(list)
        for i, r in enumerate(U[("A", pop, DISCOVERY)]):
            st[r.get("sic2")].append(i)
        strata[pop] = dict(st)

    e_perm = e_perm or n_perm

    # ---- 実データ（参考。合否ではない）----
    mm_real = to_masks(draw(shuffle=False))
    realA, realA_hits = eval_single(tests_A, mm_real, strata)
    realD = {s: eval_additive(U, s, mm_real) for s in SUBSETS}
    realE = {s: eval_conjunction(cj[s], mm_real, s) for s in SUBSETS}
    realEcv = {s: eval_conjunction_cv(cj[s], mm_real, s, folds) for s in SUBSETS}

    # ---- 置換 ----
    hitA = {"L1": 0, "L3": 0, "L3_up": 0, "L3_down": 0, "L4": 0}
    distA = []
    attribA = Counter()
    hitD = {s: 0 for s in SUBSETS}; distD = {s: [] for s in SUBSETS}
    hitE = {s: 0 for s in SUBSETS}; distE = {s: [] for s in SUBSETS}
    hitEcv = {s: 0 for s in SUBSETS}
    hitD_any = hitE_any = 0
    hit_union = hit_union_cv = 0
    for it in range(n_perm):
        labs = draw()
        mm = to_masks(labs)
        cA, hA = eval_single(tests_A, mm, strata)
        distA.append(cA["L3_any"])
        if cA["L1_up"] + cA["L1_down"] > 0:
            hitA["L1"] += 1
        if cA["L3_any"] > 0:
            hitA["L3"] += 1
            for h in hA:
                attribA["%s/%s/%s/%s" % (h["pop"], h["var"], h["grid"], h["dir"])] += 1
        if cA["L3_up"] > 0:
            hitA["L3_up"] += 1
        if cA["L3_down"] > 0:
            hitA["L3_down"] += 1
        if cA["L4_any"] > 0:
            hitA["L4"] += 1
        anyD = anyE = anyEcv = False
        for s in SUBSETS:
            nD, _ = eval_additive(U, s, mm)
            distD[s].append(nD)
            if nD > 0:
                hitD[s] += 1; anyD = True
            if it < e_perm:
                nE, _ = eval_conjunction(cj[s], mm, s)
                distE[s].append(nE)
                if nE > 0:
                    hitE[s] += 1; anyE = True
                nEcv, _ = eval_conjunction_cv(cj[s], mm, s, folds)
                if nEcv > 0:
                    hitEcv[s] += 1; anyEcv = True
        if anyD:
            hitD_any += 1
        if anyE:
            hitE_any += 1
        # 探索者が3つの角度を全部試すなら、実際の偽陽性率は和集合
        if cA["L4_any"] > 0 or anyD or (it < e_perm and anyE):
            hit_union += 1
        if cA["L4_any"] > 0 or anyD or (it < e_perm and anyEcv):
            hit_union_cv += 1

    n_tests_A = len(tests_A)
    return {
        "permutation_scheme": "y10 を**会社単位で全ビンテージ同時に**（結果ベクトルを丸ごと）"
                              "sic2 の層内で並べ替える。群の定義（特徴量）は不変なので帰無は"
                              "『候補は結果と無関係』。ビンテージ内で独立に混ぜると従属が壊れ、"
                              "v2 の実測で 33倍の過小評価になった。",
        "permutation_info": pinfo,
        "n_perm": n_perm, "n_perm_angleE": e_perm, "seed": seed,
        "angle_A_single_variable": {
            "search_space": {"features": len(F2C), "grids": len(FRACS), "dirs": len(DIRS),
                             "pops": len(POPS), "n_tests": n_tests_A},
            "false_positive_rate": {"L1_discovery_only": r4(hitA["L1"] / n_perm),
                                    "L3_all3_vintages": r4(hitA["L3"] / n_perm),
                                    "L3_up_only": r4(hitA["L3_up"] / n_perm),
                                    "L3_down_only": r4(hitA["L3_down"] / n_perm),
                                    "L4_plus_sector_control": r4(hitA["L4"] / n_perm)},
            "levels": {"L1": "発見ビンテージ2018で |lift|>=0.15 かつ 分子>=20",
                       "L3": "L1 + 2016/2017/2018 すべてで |lift|>=0.15 ∧ 分子>=20 ∧ 同符号",
                       "L4": "L3 + 業種(sic2)調整後も |差|>=0.15 で同符号（Mantel-Haenszel・2018で判定）"},
            "expected_false_passes_per_run": r4(sum(distA) / n_perm),
            "max_observed": max(distA) if distA else 0,
            "where_from_top10": dict(attribA.most_common(10)),
            "real_data_counts": {k: v for k, v in realA.items()},
        },
        "angle_D_additive_score": {
            "procedure": "①発見ビンテージ2018の complete-case で各列の中央値分割の向きを"
                         "データから決める ②|lift| 上位 J 本（J=3/5/8/10/全）を選ぶ "
                         "③スコア>=s と スコア<=s の両方を群にする（s=1..J）"
                         "④3ビンテージすべてで |lift|>=0.15 ∧ 分子>=20 ∧ 同符号。"
                         "**向きも本数も閾値もデータから選ぶ＝この自由度が偽陽性率に出る。**",
            "by_subset": {s: {"n_2018": len(U[(s, "P_full", DISCOVERY)]),
                              "n_2018_quality": len(U[(s, "P_quality", DISCOVERY)]),
                              "false_positive_rate": r4(hitD[s] / n_perm),
                              "expected_false_passes_per_run": r4(sum(distD[s]) / n_perm),
                              "max_observed": max(distD[s]) if distD[s] else 0,
                              "real_data_pass_count": realD[s][0]} for s in SUBSETS},
            "false_positive_rate_union_of_subsets": r4(hitD_any / n_perm),
        },
        "angle_E_tree": {
            "procedure": "深さ2の木＝『特徴量×分割点(q25/q50/q75)×上下』の条件を全列挙し、"
                         "1条件（深さ1）と2条件の積（深さ2）をすべて群として試す。"
                         "in_sample = 2018で見つけたものが3ビンテージ維持するか。"
                         "nested_cv = 事前登録どおり**外側foldの性能のみ**"
                         "（各foldのtrainで最良の規則を選び、held-out でだけ測り、5fold分を合併）。",
            "by_subset": {s: {"n_conditions": len(cj[s]["P_full"]["conds"][DISCOVERY]),
                              "n_rules_enumerated": (len(cj[s]["P_full"]["conds"][DISCOVERY])
                                                     * (len(cj[s]["P_full"]["conds"][DISCOVERY]) + 1) // 2),
                              "false_positive_rate_in_sample_then_3vintage": r4(hitE[s] / e_perm),
                              "expected_false_passes_per_run": (r4(sum(distE[s]) / e_perm)
                                                                if distE[s] else None),
                              "max_observed": max(distE[s]) if distE[s] else 0,
                              "false_positive_rate_nested_cv": r4(hitEcv[s] / e_perm),
                              "real_data_pass_count_in_sample": realE[s][0],
                              "real_data_nested_cv": realEcv[s][1]} for s in SUBSETS},
            "false_positive_rate_union_of_subsets_in_sample": r4(hitE_any / e_perm),
        },
        "union_across_angles": {
            "why": "探索者は角度A・D・Eを**全部試す**。実際の家族単位の偽陽性率は和集合。"
                   "角度ごとの数字だけを見ると、実際に払っている値札を過小に見積もる。",
            "with_tree_in_sample": r4(hit_union / min(n_perm, e_perm) if e_perm else None),
            "with_tree_nested_cv": r4(hit_union_cv / min(n_perm, e_perm) if e_perm else None),
            "components": "A は L4（業種調整まで）／D と E は業種調整なし＝**Dと E の側は上限**",
        },
        "real_data_reference": {
            "note": "⚠ 合否ではない。手続きが動くことの確認と、置換分布に対する位置の把握のみ。",
            "angle_A_L3_hits": realA_hits[:20],
            "angle_A_L3_n": len(realA_hits),
        },
    }


# ─────────────────────── 被覆交絡 ───────────────────────
def independent_fpr(rows, reps=300, seed=4242):
    """角度A の偽陽性率を **bitset を一切使わない素朴な実装・別シード**で独立に再現する。

    強い結論（偽陽性率）ほど先に道具を疑う。同じ帰無・同じ検定空間を、
    ticker のリスト操作だけで組み直して突き合わせる。MC の標本誤差の範囲で一致すべき。
    """
    rnd = random.Random(seed)

    def pop(v, q):
        rs = [r for r in rows if r["vintage"] == v and r.get("y10") is not None]
        return [r for r in rs if r.get("P_quality")] if q else rs

    U = {(v, q): pop(v, q) for v in TRIO for q in (0, 1)}
    groups = {}
    for q in (0, 1):
        for var in F2C:
            ok, g = True, {}
            for v in TRIO:
                rs = [r for r in U[(v, q)] if r.get(var) is not None]
                if len(rs) < 60:
                    ok = False; break
                for nm, f in ((FRAC_NAMES[round(x, 4)], x) for x in FRACS):
                    m = max(1, int(round(f * len(rs))))
                    if m >= len(rs):
                        continue
                    for d in DIRS:
                        s = (sorted(rs, key=lambda r: (-r[var], r["ticker"])) if d == "top"
                             else sorted(rs, key=lambda r: (r[var], r["ticker"])))
                        g[(v, nm, d)] = ([r["ticker"] for r in s[:m]], [r["ticker"] for r in rs])
            if ok:
                groups[(q, var)] = g
    sic = {}
    for v in TRIO:
        for r in U[(v, 0)]:
            sic[r["ticker"]] = r.get("sic2")
    lab = {v: {r["ticker"]: (1 if r["y10"] else 0) for r in U[(v, 0)]} for v in TRIO}
    common = set(lab[2016]) & set(lab[2017]) & set(lab[2018])
    bysic = defaultdict(list)
    for x in sorted(common):
        bysic[sic[x]].append(x)
    solo = {v: defaultdict(list) for v in TRIO}
    for v in TRIO:
        for x in lab[v]:
            if x not in common:
                solo[v][sic[x]].append(x)
    h1 = h3 = 0
    for _ in range(reps):
        mp = {}
        for _s, ts in bysic.items():
            sh = list(ts); rnd.shuffle(sh)
            for a, b in zip(ts, sh):
                mp[a] = b
        cur = {}
        for v in TRIO:
            c = {x: lab[v][mp[x]] for x in common}
            for _s, ts in solo[v].items():
                vals = [lab[v][x] for x in ts]; rnd.shuffle(vals)
                for x, y in zip(ts, vals):
                    c[x] = y
            cur[v] = c
        l1 = l3 = 0
        for (q, var), g in groups.items():
            for nm in (FRAC_NAMES[round(x, 4)] for x in FRACS):
                for d in DIRS:
                    if (DISCOVERY, nm, d) not in g:
                        continue
                    grp, uni = g[(DISCOVERY, nm, d)]
                    m = len(grp)
                    if not m:
                        continue
                    k = sum(cur[DISCOVERY][x] for x in grp)
                    base = sum(cur[DISCOVERY][x] for x in uni) / len(uni)
                    lf = k / m - base
                    if abs(lf) < LIFT or k < MIN_NUM:
                        continue
                    l1 += 1; up = lf > 0; ok = True
                    for v in (2016, 2017):
                        gv, uv = g[(v, nm, d)]
                        if not gv:
                            ok = False; break
                        kv = sum(cur[v][x] for x in gv)
                        bv = sum(cur[v][x] for x in uv) / len(uv)
                        lv = kv / len(gv) - bv
                        if (lv > 0) != up or abs(lv) < LIFT or kv < MIN_NUM:
                            ok = False; break
                    if ok:
                        l3 += 1
        h1 += 1 if l1 else 0
        h3 += 1 if l3 else 0
    return {"reps": reps, "seed": seed, "L1": r4(h1 / reps), "L3": r4(h3 / reps),
            "mc_se_at_L3": r4(math.sqrt(max(h3 / reps, 1e-9) * (1 - h3 / reps) / reps)),
            "note": "bitset を使わない別実装・別シード。本体の偽陽性率と MC の標本誤差の範囲で"
                    "一致するべき。ずれたらどちらかの実装が壊れている。"}


def self_checks(rows, seed=SEED):
    """道具そのものの検算。**強い結論ほど先に道具を疑う**（recalc_roic の ADBE 事故の作法）。

    1) 置換がラベルの周辺度数を保つか（ビンテージ別・層別とも厳密一致するはず）
    2) bitset の評価が、素朴な再計算と一致するか（別実装で突き合わせ）
    3) y10 の定義が tr_cagr>=0.10 と一致するか（目的変数の join の検算）
    """
    U = build_universes(rows)
    draw, to_masks, _ = perm_engine(rows, U, seed + 99)
    labs_true = draw(shuffle=False)
    labs_perm = draw()

    marg = []
    for v in TRIO:
        a = sum(labs_true[v].values()); b = sum(labs_perm[v].values())
        marg.append({"vintage": v, "events_true": a, "events_perm": b, "equal": a == b})
    # 層別
    sic = {}
    for v in TRIO:
        for r in pop_rows(rows, v, "P_full"):
            sic[r["ticker"]] = r.get("sic2")
    strat_bad = 0
    for v in TRIO:
        ca, cb = Counter(), Counter()
        for t, x in labs_true[v].items():
            ca[sic[t]] += x
        for t, x in labs_perm[v].items():
            cb[sic[t]] += x
        for k in set(ca) | set(cb):
            if ca[k] != cb[k]:
                strat_bad += 1

    # bitset 評価 vs 素朴な再計算（実データ・角度Aの先頭20検定）
    tests = masks_single(U)
    mm = to_masks(labs_true)
    naive_bad = 0
    checked = 0
    for t in tests[:20]:
        pop = t["pop"]
        rs = U[("A", pop, DISCOVERY)]
        var = t["var"]
        vals = [(r[var], r["ticker"], r) for r in rs if r.get(var) is not None]
        s = sorted(vals, key=lambda x: ((-x[0], x[1]) if t["dir"] == "top" else (x[0], x[1])))
        m = t["per_v"][DISCOVERY]["m"]
        grp = [x[2] for x in s[:m]]
        k_naive = sum(1 for r in grp if r["y10"])
        base_naive = sum(1 for x in vals if x[2]["y10"]) / len(vals)
        lm, _, _ = mm[("A", pop, DISCOVERY)]
        d = t["per_v"][DISCOVERY]
        k_bits = (lm & d["mask"]).bit_count()
        base_bits = (lm & d["nn_mask"]).bit_count() / d["nn"]
        checked += 1
        if k_naive != k_bits or abs(base_naive - base_bits) > 1e-12:
            naive_bad += 1

    # y10 の定義
    ydef_bad = sum(1 for r in rows if r.get("y10") is not None and r.get("tr_cagr") is not None
                   and r["y10"] != (r["tr_cagr"] >= 0.10))
    indep = independent_fpr(rows, reps=int(os.environ.get("HIST10_INDEP", 300)), seed=4242)
    return {
        "permutation_preserves_marginals": {"by_vintage": marg,
                                            "all_equal": all(x["equal"] for x in marg),
                                            "strata_mismatches": strat_bad,
                                            "note": "層内でしか入れ替えないので、ビンテージ別も"
                                                    "(ビンテージ×sic2)別も事象数は厳密に保たれるはず。"
                                                    "破れていたら置換の実装が壊れている。"},
        "bitset_vs_naive": {"checked": checked, "mismatch": naive_bad},
        "independent_fpr_reimplementation": indep,
        "y10_definition": {"rows_checked": sum(1 for r in rows if r.get("y10") is not None),
                           "mismatch_vs_tr_cagr_ge_0.10": ydef_bad},
    }


def coverage_confound(rows):
    out = {}
    for v in TRIO:
        for pop in POPS:
            rs = [r for r in pop_rows(rows, v, pop) if r.get("y10") is not None]
            n = len(rs)
            if not n:
                continue
            base_all = sum(1 for r in rs if r["y10"]) / n
            for var in F2C:
                sub = [r for r in rs if r.get(var) is not None]
                if len(sub) < 60:
                    continue
                b = sum(1 for r in sub if r["y10"]) / len(sub)
                out["%d/%s/%s" % (v, pop, var)] = {"coverage": r4(len(sub) / n),
                                                   "base_all": r4(base_all),
                                                   "base_nonnull": r4(b), "shift": r4(b - base_all)}
    worst = sorted(out.items(), key=lambda kv: -abs(kv[1]["shift"]))[:12]
    # complete-case（角度D/E）の選択も測る
    cc = {}
    for s, cols in SUBSETS.items():
        for v in TRIO:
            rs = [r for r in pop_rows(rows, v, "P_full") if r.get("y10") is not None]
            sub = [r for r in rs if all(r.get(c) is not None for c in cols)]
            base_all = sum(1 for r in rs if r["y10"]) / len(rs)
            b = sum(1 for r in sub if r["y10"]) / len(sub) if sub else None
            sz_all = sorted(r["size_rev"] for r in rs if r.get("size_rev") is not None)
            sz_sub = sorted(r["size_rev"] for r in sub if r.get("size_rev") is not None)
            cc["%s/%d" % (s, v)] = {
                "n_all": len(rs), "n_complete_case": len(sub),
                "share": r4(len(sub) / len(rs)),
                "base_all": r4(base_all), "base_complete_case": r4(b),
                "shift": r4(b - base_all) if b is not None else None,
                "median_size_rev_all": (sz_all[len(sz_all) // 2] if sz_all else None),
                "median_size_rev_cc": (sz_sub[len(sz_sub) // 2] if sz_sub else None),
            }
    return {
        "why": "群は非欠測の中からしか作れない。基準率を全行で取ると被覆の偏りが lift に化ける。",
        "max_abs_shift": r4(max(abs(x["shift"]) for x in out.values())),
        "worst12": [{"cell": k, **v} for k, v in worst],
        "complete_case_selection_for_D_and_E": cc,
    }


# ─────────────────────── main ───────────────────────
def main():
    panel, tg, prereg, rows = load()
    rnd = random.Random(SEED)

    tj = target_judgeability(rows)
    rc = reachability(rows)
    er = effective_requirement(rc)
    pw = power(rows, rnd)
    sc = self_checks(rows)
    cc = coverage_confound(rows)
    n_perm = int(os.environ.get("HIST10_NPERM", N_PERM))
    e_perm = int(os.environ.get("HIST10_NPERM_E", n_perm))
    fp = false_positive(rows, n_perm=n_perm, e_perm=e_perm)

    # ---- 要約用の抜き出し ----
    s10 = rc["summary_by_label"]["y10"]
    s15 = rc["summary_by_label"]["win15"]
    sd = rc["summary_by_label"]["destroy15"]
    comp = pw["hurdle_x_minnum_2x2"]["cells"]

    def g(key, d="0.15"):
        c = comp.get(key)
        if c is None:
            return None
        return c["power_analytic_delta_0.15"] if d == "0.15" else c["power_by_delta"].get(d)

    can = [
        "**下向き（10%%+を減らす向き）が到達可能なのは本当**——y10 の検定単位のうち"
        " down が可能なのは %d/%d（%.0f%%）。15%%ハードルだと %d/%d（%.0f%%）、"
        "恒久毀損(destroy)だと %d/%d（%.0f%%）＝**v1/v2 が『下向きは数学的に到達不能』と"
        "書いたのは destroy 側の話で、10%% にすると両方向が測れるようになる**。" % (
            s10["down"]["possible"], s10["down"]["tests"], 100 * s10["down"]["share"],
            s15["down"]["possible"], s15["down"]["tests"], 100 * s15["down"]["share"],
            sd["down"]["possible"], sd["down"]["tests"], 100 * sd["down"]["share"]),
        "**MIN_NUM(20社) の効き方が向きで構造的に違う**と名指しできる。"
        "登録の対象（y10 × P_full/P_quality）では up で線を上げるのは %d/%d 検定だけだが、"
        "down は %d/%d 検定が**効果の大きさに関係なく不可能**（すべて P_quality の decile/quintile"
        "＝群が小さいほど down が作れない）。全ラベル込みなら up %d/%d・down %d/%d。" % (
            er["registered_scope_only"]["y10_excl_P_moat"]["up_min_num_binding"],
            er["registered_scope_only"]["y10_excl_P_moat"]["tests"],
            er["registered_scope_only"]["y10_excl_P_moat"]["down_infeasible_by_min_num"],
            er["registered_scope_only"]["y10_excl_P_moat"]["tests"],
            er["up_direction"]["n_binding"], er["up_direction"]["of_tests"],
            er["down_direction"]["n_infeasible_by_min_num"], er["down_direction"]["of_tests"]),
        "**δ=0.15 の検出力が約0.50 なのは構造であってデータの性質ではない**と言える——"
        "真の効果が線とちょうど等しければ標本分布は線の上下に半分ずつ割れる。"
        "v2 が『0.49＝コイン投げ』と記録したのはこの帰結で、設計の良し悪しの証拠ではない。"
        "実測: 15%%/5社=%s → v3登録(10%%/20社)=%s（up・quartile・2018・P_full）。" % (
            g("P_full/up/hurdle15/min5"), g("P_full/up/hurdle10/min20")),
        "**そして10%%への変更は、線から離れた効果に対しては検出力を下げている**——"
        "δ=0.20 で 15%%ハードル %s → 10%%ハードル %s、δ=0.10（＝線に届かない偽の効果）で "
        "%s → %s と誤合格が増える。基準率が0.5に近づくほど率の分散が最大になるためで、"
        "**10%%の利得は『検出力』ではなく『到達可能性（両方向が測れる・事象が足りる）』の側にある。**" % (
            g("P_full/up/hurdle15/min5", "0.2"), g("P_full/up/hurdle10/min20", "0.2"),
            g("P_full/up/hurdle15/min5", "0.1"), g("P_full/up/hurdle10/min20", "0.1")),
        "**down 方向の検出力が効果の大きさに対して非単調**だと名指しできる——"
        "P_full/quartile では δ=0.25 で %s なのに δ=0.30 で %s、δ=0.35 で %s まで落ちる。"
        "P_quality/quartile に至ってはピークが δ=0.15 の %s で、それ以上強い効果ほど落ちる。"
        "原因は『群の率が低いこと』が合格条件なのに『その群に事象が20社』も要る点で、"
        "**MIN_NUM を『主張を支える側の数』と読み替えると非単調は消える**"
        "（＝データではなく読み方が作っている）。" % (
            pw["non_monotone_power_down"]["cells"]["P_full/min20"]["power_curve_down"]["0.25"],
            pw["non_monotone_power_down"]["cells"]["P_full/min20"]["power_curve_down"]["0.3"],
            pw["non_monotone_power_down"]["cells"]["P_full/min20"]["power_curve_down"]["0.35"],
            pw["non_monotone_power_down"]["cells"]["P_quality/min20"]["peak_power"]),
        "この手続きが偶然に合格を出す確率を**角度別に**言える: 単変量 %s（業種調整まで入れて %s）／ "
        "加法スコア %s ／ 木(in-sample) %s ／ 木(外側fold) %s。"
        "**3つの角度を全部試すなら和集合 %s**。" % (
            fp["angle_A_single_variable"]["false_positive_rate"]["L3_all3_vintages"],
            fp["angle_A_single_variable"]["false_positive_rate"]["L4_plus_sector_control"],
            fp["angle_D_additive_score"]["false_positive_rate_union_of_subsets"],
            fp["angle_E_tree"]["false_positive_rate_union_of_subsets_in_sample"],
            fp["angle_E_tree"]["by_subset"]["cov90_14"]["false_positive_rate_nested_cv"],
            fp["union_across_angles"]["with_tree_in_sample"]),
        "**角度B(持続)と角度C(分解)は事前登録の字義どおりでは合否を出せない**と結果の前に確定できる"
        "（y_persist は2013の入口だけ・y_biz は2013/2015/2018だけで、必須の2016/2017/2018が揃わない）。",
    ]
    cannot = [
        "**解析検出力は上限**である。業種調整(Mantel-Haenszel)と irr層の関門を解析に入れていない"
        "（この2つは合格を減らすことしかしない）。",
        "**3ビンテージは独立標本ではない**（同じ956ティッカー・返り値の相関が高い）。"
        "『3つで維持』を独立な3証拠と読んではいけない。偽陽性率がそれを実測で示す。",
        "**刻み・スコアの本数・分割点は事前登録に書かれていない**。ここの偽陽性率は"
        "『5刻み×上下』『J=3/5/8/10/全』『q25/q50/q75』という仮定のもとの値。"
        "実際の探索がこれより広く試せば偽陽性率は上がる。",
        "角度D・Eは **complete-case** でしか作れない（欠測を0と読まないため）。"
        "cov90_14 で約 %s、all20 で約 %s しか残らず、残った側は規模が大きい方へ偏る"
        "（下の coverage_confound.complete_case_selection_for_D_and_E）。"
        "**この偏りは母集団を変えるので、単変量の結果と直接比べられない。**" % (
            cc["complete_case_selection_for_D_and_E"]["cov90_14/2018"]["share"],
            cc["complete_case_selection_for_D_and_E"]["all20/2018"]["share"]),
        "y10 の下向きは『10%%+を減らす指標』であって『恒久毀損を増やす指標』ではない。"
        "destroy(−15%%) は base が 0.15 未満なので、**下向きは依然として到達不能**"
        "（%d/%d）＝守りの指標を絶対差 lift で測る限界は 10%% にしても解けていない。" % (
            sd["down"]["possible"], sd["down"]["tests"]),
        "この道具は**合否を一つも出していない**。実データの数字は手続きが動くことの確認と"
        "置換分布に対する位置の把握のためだけに載せてある。",
    ]

    out = {
        "generated": "2026-08-12",
        "tool": "night/hist10_diag.py",
        "prereg": "out/hist10_prereg.json",
        "inputs": {"panel": "out/hist_wd_panel.json", "targets": "out/hist10_targets.json",
                   "panel_generated": panel.get("generated"), "targets_generated": tg.get("generated"),
                   "prereg_generated": prereg.get("generated"), "prereg_version": prereg.get("version")},
        "scope": "**合否を一つも出さない。** 事前登録 v3 の手続き自体の性能だけを測る。",
        "row_filter": "has_outcome かつ window_full。全 %d 行。" % len(rows),
        "constants_used": {"LIFT": LIFT, "MIN_NUM": MIN_NUM, "hurdle": 0.10,
                           "legacy_MIN_NUM_for_comparison": LEGACY_MIN_NUM,
                           "note": "事前登録の値。動かしていない。legacy は v1/v2 との比較のためだけ。"},
        "what_can_be_said": can,
        "what_cannot_be_said": cannot,
        "self_checks": sc,
        "target_judgeability": tj,
        "reachability_two_way": rc,
        "effective_requirement": er,
        "power": pw,
        "coverage_confound": cc,
        "false_positive": fp,
    }
    p = os.path.join(OUT, "hist10_diag.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", p)

    # ────────── 端末要約 ──────────
    print("\n== (自) 道具の検算 ==")
    print("  置換がラベルの周辺度数を保つ: %s（層別の食い違い %d件）"
          % (sc["permutation_preserves_marginals"]["all_equal"],
             sc["permutation_preserves_marginals"]["strata_mismatches"]))
    print("  bitset評価 vs 素朴な再計算: %d件中 食い違い %d件"
          % (sc["bitset_vs_naive"]["checked"], sc["bitset_vs_naive"]["mismatch"]))
    print("  y10 == (tr_cagr>=0.10): %d行中 食い違い %d件"
          % (sc["y10_definition"]["rows_checked"], sc["y10_definition"]["mismatch_vs_tr_cagr_ge_0.10"]))
    ind = sc["independent_fpr_reimplementation"]
    print("  角度Aの偽陽性率を素朴な別実装・別シードで再現(%d回): L1=%s L3=%s（本体は下の(4)）"
          % (ind["reps"], ind["L1"], ind["L3"]))

    print("\n== (0) 目的変数ごとの判定可能性 ==")
    for y, x in tj["by_target"].items():
        print("  %-10s 定義できるビンテージ=%s  2016/17/18 揃う=%s  → %s"
              % (y, x["vintages_defined"], x["sign_stability_2016_17_18_applicable"], x["verdict"]))

    print("\n== (1) 両方向の到達可能性（検定単位＝セル×刻み）==")
    print("  %-10s %-22s %-22s" % ("", "全母集団", "P_moat を除く"))
    for lab in ("y10", "win15", "destroy15"):
        s = rc["summary_by_label"][lab]
        print("  %-10s up %3d/%3d down %3d/%3d   up %3d/%3d (%.0f%%) down %3d/%3d (%.0f%%)"
              % (lab, s["up"]["possible"], s["up"]["tests"],
                 s["down"]["possible"], s["down"]["tests"],
                 s["up_excl_P_moat"]["possible"], s["up_excl_P_moat"]["tests"],
                 100 * s["up_excl_P_moat"]["share"],
                 s["down_excl_P_moat"]["possible"], s["down_excl_P_moat"]["tests"],
                 100 * s["down_excl_P_moat"]["share"]))
    print("  ↑ P_moat は 2016/2017 に irr の読解が無く n=61-63＝構造的に判定できない母集団なので"
          "除いた版が実質の数字")
    print("  down に要る最小の群（y10・2016-18）:")
    for x in rc["down_direction_min_group"]:
        print("    %d %-10s n=%3d base=%.3f → 群は最低%3s社(%.1f%%)以上  down不能な刻み=%s"
              % (x["vintage"], x["pop"], x["n"], x["base"], x["min_group_n_for_down"],
                 100 * (x["min_fraction_for_down"] or 0), x["grids_that_fail_down"]))

    print("\n== (2) 実効要求倍率 ==")
    ns = er["registered_scope_only"]
    print("  【登録の対象だけ（y10 × P_full/P_quality）】検定単位=%d  up で線が上がる=%d  "
          "down が MIN_NUM で不能=%d  down 可能=%d"
          % (ns["y10_excl_P_moat"]["tests"], ns["y10_excl_P_moat"]["up_min_num_binding"],
             ns["y10_excl_P_moat"]["down_infeasible_by_min_num"],
             ns["y10_excl_P_moat"]["down_possible"]))
    u = er["up_direction"]; d = er["down_direction"]
    print("  【比較用ラベル・P_moat 込みの全体】")
    print("  up  : MIN_NUM が binding = %d/%d 検定 (最大 実効/登録 = %s)"
          % (u["n_binding"], u["of_tests"], u["max_effective_over_registered"]))
    for x in u["cells"][:6]:
        print("      %-9s %d %-9s %-8s 群%3d 実効lift=%.3f (登録の%.2f倍)"
              % (x["label"], x["vintage"], x["pop"], x["grid"], x["group_n"],
                 x["effective_lift_required"], x["effective_over_registered"]))
    print("  down: MIN_NUM で**到達不能**になる = %d/%d 検定" % (d["n_infeasible_by_min_num"], d["of_tests"]))
    for x in d["cells"][:6]:
        print("      %-9s %d %-9s %-8s 群%3d 許される最大分子=%d < 20 → 効果が何であれ不合格"
              % (x["label"], x["vintage"], x["pop"], x["grid"], x["group_n"], x["k_allowed_max"]))

    print("\n== (3) 検出力 ==")
    print("  [2×2 分解] 発見ビンテージ2018・quartile群・P_full・up 方向")
    print("  %-18s %8s %8s %8s %8s %8s   識別(0.20/0.10)" % ("設定", "δ0.05", "δ0.10", "δ0.15", "δ0.20", "δ0.30"))
    for lab in ("hurdle15/min5", "hurdle15/min20", "hurdle10/min5", "hurdle10/min20"):
        c = comp.get("P_full/up/" + lab)
        print("  %-18s %8s %8s %8s %8s %8s   %s"
              % (lab, c["power_by_delta"]["0.05"], c["power_by_delta"]["0.1"],
                 c["power_by_delta"]["0.15"], c["power_by_delta"]["0.2"],
                 c["power_by_delta"]["0.3"], c["discrimination_0.20_over_0.10"]))
    print("  ↑ **δ=0.15 で約0.50 は構造**（真の効果＝線なら標本分布が半分に割れる）。")
    print("     v1/v2 の『0.49＝コイン投げ』はこの帰結で、設計の良し悪しではない。")
    print("     **10%化は δ≠線 では検出力を下げる**（基準率が0.5に近いほど率の分散が最大）。")
    print("  [down 方向・同じ設定]")
    for lab in ("hurdle15/min5", "hurdle15/min20", "hurdle10/min5", "hurdle10/min20"):
        c = comp.get("P_full/down/" + lab)
        print("  %-18s %8s %8s %8s %8s %8s"
              % (lab, c["power_by_delta"]["0.05"], c["power_by_delta"]["0.1"],
                 c["power_by_delta"]["0.15"], c["power_by_delta"]["0.2"], c["power_by_delta"]["0.3"]))
    print("  ↑ hurdle15/min20 の down が全滅するのが v3 が MIN_NUM を 20 にした代金"
          "（base 0.21 では群の率を 0.06 以下にしつつ事象20社は作れない）")
    print("  [3ビンテージ厳格・独立の下限〜完全従属の上限]")
    for k, cell in pw["by_cell"].items():
        row = []
        for dd in ("0.1", "0.15", "0.2"):
            c = cell["all3_strict"].get(dd)
            if c is None or not c.get("feasible"):
                row.append("%s:不能" % dd)
            else:
                row.append("%s:%.3f-%.3f" % (dd, c["all3_independent_lower_bound"],
                                             c["all3_fully_dependent_upper_bound"]))
        print("    %-26s %s" % (k, "  ".join(row)))
    print("  [down 方向の非単調性] MIN_NUM が『強い真の発見ほど落とす』向きに働く")
    for k, x in pw["non_monotone_power_down"]["cells"].items():
        cur = x["power_curve_down"]
        print("    %-16s base=%.3f 群=%d min_num=%2d  ピーク δ=%s(%s) → δ=0.30 で %s"
              % (k, x["base"], x["group_n"], x["min_num"], x["peak_delta"], x["peak_power"],
                 x["power_at_delta_0.30"]))
        ks = ("0.1", "0.15", "0.2", "0.25", "0.3", "0.35", "0.4")
        print("        字義どおり(単調=%s): %s" % (x["monotone_in_effect_size"],
                                                " ".join("%s:%s" % (d, cur[d]) for d in ks)))
        alt = x["alt_reading_support_count"]
        print("        別読み(登録外・単調=%s): %s" % (alt["monotone_in_effect_size"],
                                                   " ".join("%s:%s" % (d, alt["curve"][d]) for d in ks)))
    mx = max((x["abs_diff"] or 0) for x in pw["mc_verification"]["cells"])
    print("  MC検算（20000回）と解析計算の最大差 = %.4f（MCの標準誤差 最大0.0035）" % mx)

    print("\n== (4) 偽陽性率（置換 %d回・会社単位で全ビンテージ同時・sic2層内）==" % fp["n_perm"])
    A = fp["angle_A_single_variable"]
    print("  角度A 単変量  検定数=%d  L1(2018のみ)=%s  **L3(3年維持)=%s**  (up %s / down %s)  L4(業種調整)=%s"
          % (A["search_space"]["n_tests"], A["false_positive_rate"]["L1_discovery_only"],
             A["false_positive_rate"]["L3_all3_vintages"], A["false_positive_rate"]["L3_up_only"],
             A["false_positive_rate"]["L3_down_only"],
             A["false_positive_rate"]["L4_plus_sector_control"]))
    for s in SUBSETS:
        D = fp["angle_D_additive_score"]["by_subset"][s]
        print("  角度D %-9s n(2018)=%3d  **偽陽性率=%s**  期待誤合格/回=%s"
              % (s, D["n_2018"], D["false_positive_rate"], D["expected_false_passes_per_run"]))
    print("  角度D 部分集合の和集合 = %s" % fp["angle_D_additive_score"]["false_positive_rate_union_of_subsets"])
    for s in SUBSETS:
        E = fp["angle_E_tree"]["by_subset"][s]
        print("  角度E %-9s 規則数=%d  **in-sample→3年維持=%s**  **外側fold=%s**"
              % (s, E["n_rules_enumerated"], E["false_positive_rate_in_sample_then_3vintage"],
                 E["false_positive_rate_nested_cv"]))
    UN = fp["union_across_angles"]
    print("  **和集合（探索者がA・D・Eを全部試す場合）= %s（木=in-sample）／ %s（木=外側fold）**"
          % (UN["with_tree_in_sample"], UN["with_tree_nested_cv"]))
    print("  被覆交絡の最大 |base(非欠測)−base(全行)| = %s" % cc["max_abs_shift"])

    print("\n== (5) この検証で何が言えて何が言えないか ==")
    for x in can:
        print("  ○ " + x.replace("\n", ""))
    for x in cannot:
        print("  ✗ " + x.replace("\n", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
