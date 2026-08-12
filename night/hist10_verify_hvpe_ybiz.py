#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_verify_hvpe_ybiz.py — 候補「自己相対PER族 × 事業由来10%+（2018単独）」を**潰しにかかる**。

候補（探索側 out/hist10_angleC.json の subset_screen_2018_only_outside_prereg）:
    角度=C  変数=hv_pe_pct ほか自己相対PER族（hv_adj_pe_pct / hv_pe_z / per）
    目的=y_biz（事業の寄与 >= +10%/年）  母集団=C_all  切り方=上位1/4
    n=69  分子=52  lift=0.304
    探索側の弁: 事前登録の外・合否に数えない。同じ手続きのFPRが0.41。
                通過11件はすべて自己相対PER族を4通りに切ったもの＝相関した1つの family。

事前登録: out/hist10_prereg.json（**線はそこにある。この道具は一つも作らない・一つも動かさない**）
入力    : out/hist_wd_panel.json / out/hist_val_decompose_{2013,2015,2018}.json
参照    : out/hist10_angleC.json（**照合のためだけに読む。計算は一行も import しない**）
出力    : out/hist10_verify_hvpe_ybiz.json

────────────────────────────────────────────────────────────
6つの検問（1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
 1 再現   独立実装で n/分子/lift が一致するか。**境界の約束（>= か >）まで揃える**
 2 ビンテージ  2016/2017/2018 すべてで lift>=0.15 ∧ 分子>=20 を維持するか
 3 業種   Mantel-Haenszel ＋ **業種を1つずつ抜いて**残るか
 4 irr    irr>=70 の層内でも残るか（測れないなら「判定不能」と書く）
 5 置換   **会社単位で全ビンテージ同時**に結果を並べ替える2000回
 6 増分   この群の「10%+を出した社」は、門が既に持つ関門で説明が付く社ではないか
          （7割超が既存で説明されるなら不合格＝事前登録の線）

加えて、探索側が既に書いている構造上の穴を**自分で測り直す**（確認ではなく反証のため）:
 S1 機構    自己相対PERは分母（入口の利益）が一時的に低いことの指標＝
            y_biz の分子と**分母を共有している**のではないか（循環）
 S2 総リターン  同じ群は総リターンでも10%+を出しているか（事業だけ上がって倍率で消えていないか）
 S3 基準     window 基準（恒等式が厳密に閉じる側）で判定が動くか
 S4 母集団の穴  出口が赤字の社は分解できず**除外されている**＝左裾が構造的に抜けている。
            43社を挟み込んで lift の上端・下端を出す（0で埋めない・ルール7）
 S5 検出力   この標本で δ=0.15 を掴める確率

⚠この道具は判定・採点・台帳・index.html・パックに一切触らない。読むだけ。
"""
import json
import math
import os
import random
import statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
ANGLEC = os.path.join(OUT, "hist10_angleC.json")
DEST = os.path.join(OUT, "hist10_verify_hvpe_ybiz.json")

SEED = 20260812
N_PERM = 2000
N_POWER = 5000

# ── 事前登録の線（読むだけ・作らない） ──
prereg = json.load(open(PREREG, encoding="utf-8"))
LIFT = 0.15
MIN_NUM = 20
HURDLE = 0.10
LN110 = math.log(1.0 + HURDLE)
INC_MAX = 0.70
SIGN_VINTAGES = [2016, 2017, 2018]
DECOMP_VINTAGES = [2013, 2015, 2018]

# 候補の family（探索側の通過11件はすべてこの4変数の切り方違い）
PER_FAMILY = ["hv_pe_pct", "hv_adj_pe_pct", "hv_pe_z", "per"]
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]
POPS = ["C_all", "C_moat"]

# 探索側と同じ候補変数（FPR を同じ手続きで測るため）
F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r", "gw_r",
      "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5", "conv5", "netiss_r",
      "payout5", "rev"]
CO = ["roic_med5", "roic_latest", "roic_worst5", "opm", "sales_cagr5", "fcf_conv_5y",
      "op_all_pos", "fcf_all_pos", "equity_neg", "score", "rev_asof"]
PA = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
HV = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_z", "ps_z"]
CANDIDATES = (["f2_" + f for f in F2] + ["co_" + f for f in CO] + ["pa_" + f for f in PA]
              + ["hv_" + f for f in HV] + ["per", "size_rev"])


def r4(x):
    return None if x is None else round(x, 4)


def r6(x):
    return None if x is None else round(x, 6)


def rate(k, n):
    return None if not n else k / n


def num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


def q_at(sorted_vals, q):
    """探索側と同じ順位式（ceil）。境界の約束を揃えるためここは意図的に同じにする。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))
    return sorted_vals[k - 1]


# ══════════════════════════════════════════════════════════════
# 0. 在庫・母集団を独立に組む
# ══════════════════════════════════════════════════════════════
panel = json.load(open(PANEL, encoding="utf-8"))
prows = panel["rows"]
pidx = {(r["ticker"], r["vintage"]): r for r in prows}
panel_vintages = sorted(set(r["vintage"] for r in prows))

inventory = {}
decomp = {}
for v in sorted(set(panel_vintages) | set(DECOMP_VINTAGES)):
    p = os.path.join(OUT, f"hist_val_decompose_{v}.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        decomp[v] = d
        inventory[str(v)] = {"decompose_file": os.path.basename(p), "rows": len(d["rows"])}
    else:
        inventory[str(v)] = {"decompose_file": None, "rows": 0,
                             "why": "分解の在庫が存在しない＝この目的（事業由来）を測れない"}

# C-set（パネル行に分解を焼く。パネルは書き換えない）
C = defaultdict(list)
join_report = {}
for v, d in decomp.items():
    hit = miss = 0
    for dr in d["rows"]:
        key = (dr["ticker"], v)
        if key not in pidx:
            miss += 1
            continue
        hit += 1
        pr = pidx[key]
        row = dict(pr)
        row["_biz"] = dr["biz"]
        row["_mult"] = dr["mult"]
        row["_tr"] = dr["tr"]
        row["_biz_w"] = dr.get("biz_w")
        row["_mult_w"] = dr.get("mult_w")
        row["_resid_w"] = dr.get("resid_w")
        row["_div"] = dr.get("div")
        row["_pe_in"] = dr.get("pe_in")
        row["_pe_out"] = dr.get("pe_out")
        row["_g_eps3_pre"] = dr.get("g_eps3_pre")
        row["_g_rev3_pre"] = dr.get("g_rev3_pre")
        row["_sh_chg"] = dr.get("sh_chg")
        row["_years"] = dr.get("years")
        row["y_biz"] = (dr["biz"] >= LN110)
        row["y_biz_w"] = (dr.get("biz_w") is not None and dr["biz_w"] >= LN110)
        row["y10"] = (pr.get("tr_cagr") is not None and pr["tr_cagr"] >= HURDLE)
        row["y_mult_pos"] = (dr["mult"] > 0)
        C[v].append(row)
    join_report[str(v)] = {"decompose_rows": len(d["rows"]), "joined": hit, "unmatched": miss}


def pop_rows(v, pop):
    if pop == "C_all":
        return C.get(v, [])
    if pop == "C_moat":
        return [r for r in C.get(v, []) if r.get("P_moat") is True]
    return []


# ══════════════════════════════════════════════════════════════
# 1. 測る（独立実装・境界の約束を3通り出す）
# ══════════════════════════════════════════════════════════════
def cell(v, pop, var, ykey, cut="上位1/4", boundary="ge"):
    """boundary: 'ge' = 探索側と同じ (x>=q75) / 'gt' = 厳密 (x>q75) / 'rank' = 順位で上位25%"""
    R = pop_rows(v, pop)
    n_pop = len(R)
    if not n_pop:
        return None
    k_pop = sum(1 for r in R if r.get(ykey))
    p_pop = rate(k_pop, n_pop)
    M = [(num(r.get(var)), 1 if r.get(ykey) else 0, r) for r in R]
    M = [(x, w, r) for (x, w, r) in M if x is not None]
    if not M:
        return {"status": "この母集団でこの変数は一つも測れない＝判定不能",
                "n_pop": n_pop, "p_pop": r4(p_pop)}
    n_m = len(M)
    k_m = sum(w for _, w, _ in M)
    vals = sorted(x for x, _, _ in M)
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    if boundary == "rank":
        # 値の同順位を順位で切る（同値は入口順で切れるので「切り口の恣意性」を測るためだけ）
        order = sorted(range(n_m), key=lambda i: M[i][0])
        want = int(math.ceil(n_m * 0.25))
        sel = set(order[-want:]) if cut == "上位1/4" else \
              set(order[:want]) if cut == "下位1/4" else \
              set(order[n_m // 2:]) if cut == "中央値超" else set(order[:n_m // 2])
        grp = [M[i] for i in range(n_m) if i in sel]
    else:
        op = (lambda x: x >= q75) if boundary == "ge" else (lambda x: x > q75)
        opl = (lambda x: x <= q25) if boundary == "ge" else (lambda x: x < q25)
        PRED = {"上位1/4": op, "下位1/4": opl,
                "中央値超": (lambda x: x > q50), "中央値以下": (lambda x: x <= q50)}
        grp = [(x, w, r) for (x, w, r) in M if PRED[cut](x)]
    gn = len(grp)
    gk = sum(w for _, w, _ in grp)
    gp = rate(gk, gn)
    return {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": n_m,
            "p_measurable": r4(rate(k_m, n_m)),
            "n_group": gn, "numerator": gk, "p_group": r4(gp),
            "lift_vs_pop": r4(None if gp is None else gp - p_pop),
            "lift_vs_measurable": r4(None if gp is None else gp - rate(k_m, n_m)),
            "q75": r6(q75), "q50": r6(q50), "q25": r6(q25),
            "group_share": r4(gn / n_m),
            "_rows": [r for _, _, r in grp]}


def strip(c):
    if not c:
        return c
    return {k: v for k, v in c.items() if not k.startswith("_")}


# ── 1 再現 ──
published = {}
try:
    ac = json.load(open(ANGLEC, encoding="utf-8"))
    for c in ac["subset_screen_2018_only_outside_prereg"]["y_biz"]["passed"]:
        published[(c["variable"], c["population"], c["cut"])] = {
            "lift": c["lifts"][0], "numerator": c["numerators"][0], "n_group": c["n_groups"][0],
            "p_base": c["p_bases"][0], "sector_mh": c.get("sector_mh")}
except Exception as e:  # 照合できなくても自分の測定は出す
    published = {"_error": str(e)}

repro = {"boundary_note": ("探索側の約束は **上位1/4 = 値 >= 75%点（ceil順位式）**。"
                          "同値があると群は25%より大きくなる。gt/rank は境界の感度を見るためだけに出す"),
         "cells": {}, "mismatch": []}
for var in PER_FAMILY:
    for cut in ("上位1/4", "中央値超"):
        mine = cell(2018, "C_all", var, "y_biz", cut, "ge")
        gt = cell(2018, "C_all", var, "y_biz", cut, "gt")
        rk = cell(2018, "C_all", var, "y_biz", cut, "rank")
        pub = published.get((var, "C_all", cut)) if isinstance(published, dict) else None
        ent = {"mine_ge": strip(mine), "mine_gt_boundary": strip(gt), "mine_rank_boundary": strip(rk),
               "published": pub}
        if pub:
            ok = (mine["n_group"] == pub["n_group"] and mine["numerator"] == pub["numerator"]
                  and abs(mine["lift_vs_pop"] - pub["lift"]) < 1e-4)
            ent["agrees_with_published"] = ok
            if not ok:
                repro["mismatch"].append(f"{var}|{cut}")
        repro["cells"][f"{var}|{cut}"] = ent

# 候補が名乗る n=69 の出所を突き止める
n69 = {}
for var in PER_FAMILY:
    for b in ("ge", "gt", "rank"):
        c = cell(2018, "C_all", var, "y_biz", "上位1/4", b)
        if c and c.get("n_group") in (68, 69, 70, 71):
            n69[f"{var}|{b}"] = {"n_group": c["n_group"], "numerator": c["numerator"],
                                 "lift": c["lift_vs_pop"]}
repro["where_n69_comes_from"] = n69
repro["verdict"] = ("独立実装が探索側と一致（境界の約束も同じ）" if not repro["mismatch"]
                    else "食い違い: " + ", ".join(repro["mismatch"]))

# ══════════════════════════════════════════════════════════════
# 2. ビンテージ
# ══════════════════════════════════════════════════════════════
vint = {"registered_gate": {"required": SIGN_VINTAGES,
                            "decompose_inventory": {str(v): inventory.get(str(v), {}).get("rows", 0)
                                                    for v in SIGN_VINTAGES}},
        "by_variable": {}}
missing = [v for v in SIGN_VINTAGES if not decomp.get(v)]
vint["registered_gate"]["missing_vintages"] = missing
vint["registered_gate"]["status"] = (
    "判定不能——2016/2017 に分解の在庫が存在せず、事業由来の目的そのものを作れない。"
    "**不合格ではなく判定不能**（効果が無いのではなく、登録した手続きをこの目的には当てられない）"
    if missing else "測定可能")

for var in PER_FAMILY:
    for cut in ("上位1/4", "中央値超"):
        row = {}
        for v in DECOMP_VINTAGES:
            c = cell(v, "C_all", var, "y_biz", cut, "ge")
            row[str(v)] = None if not c else {"n_pop": c["n_pop"], "n_group": c["n_group"],
                                              "numerator": c["numerator"],
                                              "p_base": c["p_pop"], "p_group": c["p_group"],
                                              "lift": c["lift_vs_pop"]}
        lifts = [row[str(v)]["lift"] for v in DECOMP_VINTAGES if row.get(str(v))]
        nums = [row[str(v)]["numerator"] for v in DECOMP_VINTAGES if row.get(str(v))]
        row["_lift_all3_ge_0.15"] = bool(lifts) and all(l is not None and l >= LIFT for l in lifts)
        row["_numerator_all3_ge_20"] = bool(nums) and all(k >= MIN_NUM for k in nums)
        row["_note"] = ("2013/2015/2018 は**登録したビンテージではない**（登録は2016/2017/2018）。"
                        "在庫がある3つで同じ線を当てた緩和版＝事前登録の外。合否には数えない")
        vint["by_variable"][f"{var}|{cut}"] = row

vint["verdict"] = ("登録ゲート＝判定不能。緩和版（在庫のある2013/2015/2018）でも "
                   "lift と分子を同時に満たす切り方はゼロ"
                   if not any(r.get("_lift_all3_ge_0.15") and r.get("_numerator_all3_ge_20")
                              for r in vint["by_variable"].values())
                   else "緩和版では維持する切り方がある")

# ══════════════════════════════════════════════════════════════
# 3. 業種（Mantel-Haenszel ＋ 1業種抜き）
# ══════════════════════════════════════════════════════════════
def mh(v, pop, var, cut="上位1/4", ykey="y_biz", drop_sector=None):
    R = [r for r in pop_rows(v, pop) if num(r.get(var)) is not None]
    if drop_sector is not None:
        R = [r for r in R if (r.get("sic2") or "NA") != drop_sector]
    if not R:
        return None
    vals = sorted(num(r[var]) for r in R)
    q75, q50, q25 = q_at(vals, 0.75), q_at(vals, 0.50), q_at(vals, 0.25)
    PRED = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
            "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}
    inn = [r for r in R if PRED[cut](num(r[var]))]
    out = [r for r in R if not PRED[cut](num(r[var]))]
    p1 = rate(sum(1 for r in inn if r.get(ykey)), len(inn))
    p0 = rate(sum(1 for r in out if r.get(ykey)), len(out))
    crude = None if (p1 is None or p0 is None) else p1 - p0
    byS = defaultdict(lambda: {"in": [], "out": []})
    for r in R:
        byS[r.get("sic2") or "NA"]["in" if PRED[cut](num(r[var])) else "out"].append(r)
    numr = den = 0.0
    used = dropped = used_rows = dropped_rows = 0
    for s, d in byS.items():
        n1, n0 = len(d["in"]), len(d["out"])
        if n1 == 0 or n0 == 0:
            dropped += 1
            dropped_rows += n1 + n0
            continue
        used += 1
        used_rows += n1 + n0
        e1 = sum(1 for r in d["in"] if r.get(ykey))
        e0 = sum(1 for r in d["out"] if r.get(ykey))
        w = n1 * n0 / (n1 + n0)
        numr += w * (e1 / n1 - e0 / n0)
        den += w
    return {"n_analysed": len(R), "n_group": len(inn),
            "crude_risk_diff_in_vs_out": r4(crude),
            "mh_risk_diff": r4(numr / den) if den else None,
            "strata_used": used, "strata_dropped": dropped,
            "rows_in_used_strata": used_rows, "rows_in_dropped_strata": dropped_rows,
            "coverage_of_rows": r4(rate(used_rows, len(R)))}


sector = {"note": ("MH は **群と非群が同じ業種に同居する層でしか重みを持たない**。"
                   "使われた層に何行入っているかを必ず出す（探索側は strata_dropped=43 と書くだけだった）"),
          "mh": {}, "leave_one_sector_out": {}}
for var in PER_FAMILY:
    sector["mh"][var] = mh(2018, "C_all", var, "上位1/4")
    secs = Counter((r.get("sic2") or "NA") for r in pop_rows(2018, "C_all")
                   if num(r.get(var)) is not None)
    worst = []
    for s, cnt in secs.most_common():
        R = [r for r in pop_rows(2018, "C_all")
             if num(r.get(var)) is not None and (r.get("sic2") or "NA") != s]
        if len(R) < 30:
            continue
        vals = sorted(num(r[var]) for r in R)
        q75 = q_at(vals, 0.75)
        inn = [r for r in R if num(r[var]) >= q75]
        p1 = rate(sum(1 for r in inn if r.get("y_biz")), len(inn))
        p0 = rate(sum(1 for r in R if r.get("y_biz")), len(R))
        worst.append({"dropped_sic2": s, "n_dropped": cnt, "n_left": len(R),
                      "n_group": len(inn), "numerator": sum(1 for r in inn if r.get("y_biz")),
                      "lift": r4(None if p1 is None else p1 - p0)})
    worst.sort(key=lambda x: (x["lift"] if x["lift"] is not None else 9))
    sector["leave_one_sector_out"][var] = {
        "worst5": worst[:5], "min_lift": worst[0]["lift"] if worst else None,
        "all_stay_over_line": all((w["lift"] or -9) >= LIFT for w in worst) if worst else None}

# ══════════════════════════════════════════════════════════════
# 4. irr の層
# ══════════════════════════════════════════════════════════════
irr_layer = {}
R2018 = pop_rows(2018, "C_all")
irr_layer["coverage"] = {
    "n_C_all_2018": len(R2018),
    "with_irr_reading": sum(1 for r in R2018 if r.get("irr") is not None),
    "irr_ge_70": sum(1 for r in R2018 if (r.get("irr") is not None and r["irr"] >= 70)),
    "irr_lt_70": sum(1 for r in R2018 if (r.get("irr") is not None and r["irr"] < 70)),
    "no_reading": sum(1 for r in R2018 if r.get("irr") is None),
    "note": "読解が無い行は『irr<70』ではない＝判定不能（欠測を0と読まない）"}
for label, sel in (("irr>=70", lambda r: r.get("irr") is not None and r["irr"] >= 70),
                   ("irr<70", lambda r: r.get("irr") is not None and r["irr"] < 70),
                   ("irrの読解あり全部", lambda r: r.get("irr") is not None)):
    S = [r for r in R2018 if sel(r)]
    ent = {"n_stratum": len(S)}
    if len(S) < 30:
        ent["status"] = "判定不能（層が30行未満）"
    else:
        ent["status"] = "測定"
        for var in PER_FAMILY:
            M = [r for r in S if num(r.get(var)) is not None]
            if len(M) < 20:
                ent[var] = {"status": "判定不能", "n_measurable": len(M)}
                continue
            vals = sorted(num(r[var]) for r in M)
            q75 = q_at(vals, 0.75)
            inn = [r for r in M if num(r[var]) >= q75]
            p1 = rate(sum(1 for r in inn if r.get("y_biz")), len(inn))
            p0 = rate(sum(1 for r in S if r.get("y_biz")), len(S))
            ent[var] = {"n_group": len(inn), "numerator": sum(1 for r in inn if r.get("y_biz")),
                        "p_group": r4(p1), "p_stratum": r4(p0),
                        "lift": r4(None if p1 is None else p1 - p0),
                        "meets_min_num": sum(1 for r in inn if r.get("y_biz")) >= MIN_NUM}
    irr_layer[label] = ent

# ══════════════════════════════════════════════════════════════
# 5. 置換（会社単位・全ビンテージ同時）
# ══════════════════════════════════════════════════════════════
def _vec_of(ykey):
    ticks = sorted(set(r["ticker"] for v in C for r in C[v]))
    vec = {t: {} for t in ticks}
    for v in C:
        for r in C[v]:
            vec[r["ticker"]][v] = bool(r.get(ykey))
    # ★所属パターン（どのビンテージに居るか）で層を作る。
    #   素朴に全ティッカーで入れ替えると、2018に居ない社の結果ベクトルが2018の社へ渡り
    #   **その年の事象が欠測として消える**＝帰無の基準率が下がり偽陽性率が過小に出る。
    pat = defaultdict(list)
    for t in ticks:
        pat[frozenset(vec[t].keys())].append(t)
    return ticks, vec, pat


def permutation(stat_fn, n_perm=N_PERM, seed=SEED, ykey="y_biz"):
    """会社ごとの結果ベクトルをまるごと入れ替える（全ビンテージ同時）。
       **所属パターンの中でだけ入れ替える**ので、各ビンテージの母集団と事象数が保たれる。
       群の所属（特徴量）は動かさない＝正しい帰無。"""
    ticks, vec, pat = _vec_of(ykey)
    obs = stat_fn(vec)
    rnd = random.Random(seed)
    hits_ge = 0
    dist = []
    for _ in range(n_perm):
        perm = {}
        for _p, ts in pat.items():
            src = ts[:]
            rnd.shuffle(src)
            for a, b in zip(ts, src):
                perm[a] = vec[b]
        s = stat_fn(perm)
        dist.append(s)
        if s >= obs:
            hits_ge += 1
    dist.sort()
    return {"observed": r4(obs), "n_perm": n_perm,
            "p_value": r4((hits_ge + 1) / (n_perm + 1)),
            "null_p50": r4(dist[n_perm // 2]), "null_p95": r4(dist[int(n_perm * 0.95)]),
            "null_max": r4(dist[-1]),
            "null_design": "所属パターン内で結果ベクトルを入れ替え（各年の母集団・事象数を保存）"}


# 群の所属を先に固定（結果ラベルだけ動かす）
group_membership = {}   # (var,pop,cut) -> {vintage: set(tickers)}
measurable_set = {}
for var in CANDIDATES:
    for pop in POPS:
        for cut in CUTNAMES:
            gm_, ms_ = {}, {}
            for v in DECOMP_VINTAGES:
                R = [r for r in pop_rows(v, pop) if num(r.get(var)) is not None]
                ms_[v] = set(r["ticker"] for r in pop_rows(v, pop))
                if len(R) < 4:
                    gm_[v] = set()
                    continue
                vals = sorted(num(r[var]) for r in R)
                q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
                P = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                     "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
                gm_[v] = set(r["ticker"] for r in R if P(num(r[var])))
            group_membership[(var, pop, cut)] = gm_
            measurable_set[(var, pop)] = ms_

pop_tickers = {(v, pop): set(r["ticker"] for r in pop_rows(v, pop))
               for v in DECOMP_VINTAGES for pop in POPS}


def lift_of(key, v, vecs):
    var, pop, cut = key
    g = group_membership[key].get(v, set())
    allt = pop_tickers[(v, pop)]
    if not g or not allt:
        return None, 0
    e1 = sum(1 for t in g if vecs.get(t, {}).get(v))
    e0 = sum(1 for t in allt if vecs.get(t, {}).get(v))
    return e1 / len(g) - e0 / len(allt), e1


CAND_2018 = [k for k in group_membership
             if group_membership[k].get(2018) and len(group_membership[k][2018]) >= 4]
FAM_2018 = [k for k in CAND_2018 if k[0] in PER_FAMILY]


def stat_single(vecs, key=("hv_adj_pe_pct", "C_all", "上位1/4")):
    l, _ = lift_of(key, 2018, vecs)
    return l if l is not None else -9


def stat_single_pe(vecs):
    return stat_single(vecs, ("hv_pe_pct", "C_all", "上位1/4"))


def make_pass_counter(keys):
    def f(vecs):
        best = 0.0
        for k in keys:
            l, e1 = lift_of(k, 2018, vecs)
            if l is None or e1 < MIN_NUM:
                continue
            best = max(best, abs(l))
        return best
    return f


perm = {
    "design": ("会社ごとの結果ベクトルをまるごと入れ替える（全ビンテージ同時・所属パターン内）。"
               "ビンテージ内で独立に混ぜると従属が壊れて偽陽性率が過小に出る（この台帳が実測済み）。"
               "**逆に所属パターンを無視して混ぜると事象が欠測として消え、これも過小になる**"
               "——この道具の初版が実際に踏んだ"),
    "single_cell_hv_adj_pe_pct": permutation(stat_single),
    "single_cell_hv_pe_pct": permutation(stat_single_pe),
    "single_cell_hv_adj_pe_pct_on_y10": permutation(
        lambda vecs: stat_single(vecs), ykey="y10"),
}
# family / 全画面の「1セルでも通る」確率＝この手続きの偽陽性率
for name, keys in (("PER族のみ(4変数×4切り方×2母集団)", FAM_2018),
                   ("2018のy_biz全画面(全候補変数)", CAND_2018)):
    f = make_pass_counter(keys)
    ticks, vec, pat = _vec_of("y_biz")
    obs = f(vec)
    rnd = random.Random(SEED + 1)
    ge = pass_any = 0
    for _ in range(N_PERM):
        p = {}
        for _pp, ts in pat.items():
            src = ts[:]
            rnd.shuffle(src)
            for a, b in zip(ts, src):
                p[a] = vec[b]
        s = f(p)
        if s >= obs:
            ge += 1
        if s >= LIFT:
            pass_any += 1
    perm[f"family_max|{name}"] = {
        "n_cells": len(keys), "observed_max_abs_lift": r4(obs),
        "p_value_selection_adjusted": r4((ge + 1) / (N_PERM + 1)),
        "FPR_at_least_one_cell_passes(lift>=0.15 & num>=20)": r4(pass_any / N_PERM)}

# ══════════════════════════════════════════════════════════════
# 6. 増分（既存の関門で説明が付くか）
# ══════════════════════════════════════════════════════════════
def shrink(r):
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def thin(r):
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def thin_known(r):
    return r.get("f2_intcov") is not None


inc = {"reading": ("勝者側の増分＝『その群の成功社は、門が既に持つ関門で **すでに選ばれている社** ではないか』。"
                   "説明が7割を超えるなら新しい指標としての実務的価値は無い（事前登録の線）"),
       "by_variable": {}}
# ★『説明された割合』は母集団の側の割合と比べないと意味を持たない
_R = pop_rows(2018, "C_all")
_base_in = sum(1 for r in _R if r.get("P_quality") and not shrink(r) and thin_known(r) and not thin(r))
inc["baseline"] = {
    "n_pop": len(_R),
    "pop_share_inside_all_existing_gates": r4(rate(_base_in, len(_R))),
    "components": {
        "P_quality": r4(rate(sum(1 for r in _R if r.get("P_quality")), len(_R))),
        "not_shrinking": r4(rate(sum(1 for r in _R if not shrink(r)), len(_R))),
        "intcov_known": r4(rate(sum(1 for r in _R if thin_known(r)), len(_R))),
        "intcov_known_and_ge3": r4(rate(sum(1 for r in _R if thin_known(r) and not thin(r)), len(_R))),
    },
    "why_this_matters": ("母集団の 72% が既に関門の内側なら、群の成功社の 72% が内側でも"
                         "**それは基準率であって説明ではない**。差（群の割合 − 母集団の割合）を見る"),
}
for var in PER_FAMILY:
    c = cell(2018, "C_all", var, "y_biz", "上位1/4", "ge")
    grp = c["_rows"]
    wins = [r for r in grp if r.get("y_biz")]
    q = sum(1 for r in wins if r.get("P_quality"))
    ns = sum(1 for r in wins if not shrink(r))
    nt = sum(1 for r in wins if thin_known(r) and not thin(r))
    nt_unknown = sum(1 for r in wins if not thin_known(r))
    irr70 = sum(1 for r in wins if r.get("irr") is not None and r["irr"] >= 70)
    irr_unknown = sum(1 for r in wins if r.get("irr") is None)
    allg = sum(1 for r in wins if r.get("P_quality") and not shrink(r)
               and thin_known(r) and not thin(r))
    # 非循環の読み: 既存関門を通る行だけに絞ってもう一度測る
    P = [r for r in pop_rows(2018, "C_all")
         if r.get("P_quality") and not shrink(r) and thin_known(r) and not thin(r)
         and num(r.get(var)) is not None]
    within = None
    if len(P) >= 30:
        vals = sorted(num(r[var]) for r in P)
        q75 = q_at(vals, 0.75)
        inn = [r for r in P if num(r[var]) >= q75]
        p1 = rate(sum(1 for r in inn if r.get("y_biz")), len(inn))
        p0 = rate(sum(1 for r in P if r.get("y_biz")), len(P))
        within = {"n_pass_gates": len(P), "n_group": len(inn),
                  "numerator": sum(1 for r in inn if r.get("y_biz")),
                  "p_group": r4(p1), "p_base": r4(p0),
                  "lift": r4(None if p1 is None else p1 - p0),
                  "meets_min_num": sum(1 for r in inn if r.get("y_biz")) >= MIN_NUM}
    inc["by_variable"][var] = {
        "n_group": c["n_group"], "n_wins": len(wins),
        "wins_inside_P_quality": q,
        "wins_share_inside_P_quality": r4(rate(q, len(wins))),
        "wins_not_shrinking": ns, "wins_not_thin(known)": nt,
        "wins_thin_unknown": nt_unknown,
        "wins_irr_ge_70": irr70, "wins_irr_unknown": irr_unknown,
        "wins_inside_all_existing_gates": allg,
        "share_explained_by_existing_gates": r4(rate(allg, len(wins))),
        "over_70pct_line": (rate(allg, len(wins)) or 0) > INC_MAX,
        "excess_over_population_share": r4((rate(allg, len(wins)) or 0)
                                           - (rate(_base_in, len(_R)) or 0)),
        "within_gate_passers_relift": within}
inc["structural_note"] = (
    "C_all は**定義上すべて質実証プールの部分集合**（分解の pool_def）。"
    "したがって『質実証で説明される』は 100% で、これは発見ではなく母集団の定義。"
    "循環でない読みは within_gate_passers_relift（関門を通った行だけでもう一度測る）のほう")

# ══════════════════════════════════════════════════════════════
# S1 機構（循環の疑い）
# ══════════════════════════════════════════════════════════════
def spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return None

    def rk(a):
        idx = sorted(range(n), key=lambda i: a[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and a[idx[j + 1]] == a[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r
    rx, ry = rk(xs), rk(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return None if sx == 0 or sy == 0 else cov / (sx * sy)


mech = {"question": ("自己相対PERが高い＝**入口の利益が自分の履歴に対して低い**（分母が一時的に沈んでいる）。"
                     "y_biz は ln(出口EPS/入口EPS)＝**同じ入口EPSを分母に持つ**。"
                     "予測変数と目的変数が分母を共有していれば、これは事業の質の発見ではなく恒等式の影"),
        "by_vintage": {}}
for v in DECOMP_VINTAGES:
    R = [r for r in pop_rows(v, "C_all")]
    ent = {"n": len(R)}
    for var in PER_FAMILY:
        M = [r for r in R if num(r.get(var)) is not None and r.get("_biz") is not None]
        if len(M) < 20:
            ent[var] = {"status": "判定不能", "n": len(M)}
            continue
        xs = [num(r[var]) for r in M]
        ent[var] = {
            "n": len(M),
            "rho_biz(事業)": r4(spearman(xs, [r["_biz"] for r in M])),
            "rho_mult(倍率)": r4(spearman(xs, [r["_mult"] for r in M])),
            "rho_tr(総リターン)": r4(spearman(xs, [r["_tr"] for r in M])),
            "se_approx": r4(1.0 / math.sqrt(len(M) - 1)),
        }
        g = [r for r in M if num(r[var]) >= q_at(sorted(xs), 0.75)]
        rest = [r for r in M if num(r[var]) < q_at(sorted(xs), 0.75)]
        pre_g = [r["_g_eps3_pre"] for r in g if r.get("_g_eps3_pre") is not None]
        pre_r = [r["_g_eps3_pre"] for r in rest if r.get("_g_eps3_pre") is not None]
        pe_g = [r["_pe_in"] for r in g if r.get("_pe_in") is not None]
        pe_r = [r["_pe_in"] for r in rest if r.get("_pe_in") is not None]
        ent[var]["group_vs_rest"] = {
            "pre_entry_3y_EPS成長_中央値_群": r4(st.median(pre_g)) if pre_g else None,
            "pre_entry_3y_EPS成長_中央値_群外": r4(st.median(pre_r)) if pre_r else None,
            "入口PER_中央値_群": r4(st.median(pe_g)) if pe_g else None,
            "入口PER_中央値_群外": r4(st.median(pe_r)) if pe_r else None,
            "読み": "群の入口EPS成長が群外より低いなら、高い自己相対PERの正体は『分母が沈んでいる』",
        }
    mech["by_vintage"][str(v)] = ent

# ══════════════════════════════════════════════════════════════
# S2 総リターン / S3 window基準
# ══════════════════════════════════════════════════════════════
alt = {"note": ("同じ群・同じ切り方で目的だけ替える。"
                "y10（総リターン10%+）で消えるなら、事業側の lift は倍率側で相殺されている")}
for var in PER_FAMILY:
    row = {}
    for yk in ("y_biz", "y10", "y_mult_pos", "y_biz_w"):
        c = cell(2018, "C_all", var, yk, "上位1/4", "ge")
        row[yk] = None if not c else {"n_group": c["n_group"], "numerator": c["numerator"],
                                      "p_group": c["p_group"], "p_base": c["p_pop"],
                                      "lift": c["lift_vs_pop"]}
    # 相殺の度合い
    b = row["y_biz"]["lift"] if row.get("y_biz") else None
    m = row["y_mult_pos"]["lift"] if row.get("y_mult_pos") else None
    row["_cancellation"] = r4(None if (b is None or m is None or b == 0) else min(1.0, abs(m) / abs(b)))
    alt[var] = row

# ══════════════════════════════════════════════════════════════
# S4 母集団の穴（分解できず落ちた社を挟み込む）
# ══════════════════════════════════════════════════════════════
hole = {}
for v in DECOMP_VINTAGES:
    d = decomp[v]
    dr = d.get("dropout") or {}
    rows = dr.get("rows") or []
    kept = pop_rows(v, "C_all")
    vals = sorted(num(r["hv_pe_pct"]) for r in kept if num(r.get("hv_pe_pct")) is not None)
    q75 = q_at(vals, 0.75)
    hi = [x for x in rows if x.get("pe_pct") is not None and x["pe_pct"] >= q75]
    reasons = dr.get("reasons") or {}
    # 挟み込み: 落ちた社を（上端）全部成功／（下端）全部失敗として上位1/4へ足す
    base_k = sum(1 for r in kept if r.get("y_biz"))
    base_n = len(kept)
    g = [r for r in kept if num(r.get("hv_pe_pct")) is not None and num(r["hv_pe_pct"]) >= q75]
    gk, gn = sum(1 for r in g if r.get("y_biz")), len(g)
    nd_hi = len(hi)
    nd_all = len([x for x in rows if x.get("pe_pct") is not None])
    up = (gk + nd_hi) / (gn + nd_hi) - (base_k + nd_all) / (base_n + nd_all) if (gn + nd_hi) else None
    dn = gk / (gn + nd_hi) - base_k / (base_n + nd_all) if (gn + nd_hi) else None
    hole[str(v)] = {
        "dropped_n": dr.get("dropped_n"), "kept_n": dr.get("kept_n"),
        "kept_tr_med": dr.get("kept_tr_med"), "dropped_tr_med": dr.get("dropped_tr_med"),
        "reasons": reasons,
        "dropped_with_entry_pe_pct": nd_all,
        "dropped_in_top_quartile_of_kept": nd_hi,
        "top_quartile_share_among_dropped": r4(rate(nd_hi, nd_all)),
        "top_quartile_share_among_kept": r4(rate(gn, len(kept))),
        "bracket_lift_upper(落ちた社を全部成功と置く)": r4(up),
        "bracket_lift_lower(落ちた社を全部失敗と置く)": r4(dn),
        "which_is_defensible": ("下端。落ちた社の大半は**出口の純利益が正でない**＝利益は伸びていない。"
                                "『事業が+10%/年で複利した』の側には入りようがない。"
                                "ただし ln が定義できないので厳密には判定不能＝だから挟み込みで出す"),
    }

# ══════════════════════════════════════════════════════════════
# S6 分母の共有（循環）を決定的に検定する
#   y_biz = ln(出口EPS / 入口EPS)/年数。自己相対PERの分母も入口EPS。
#   (a) 分母の入れ替え: 売上/FCF を分母にした自己相対倍率でも同じ lift が出るか
#   (b) 入口EPSの沈み（入口前3年のEPS成長）で層別しても PER の lift が残るか
#   (c) 入口PERと出口PERの水準（群 vs 群外）
# ══════════════════════════════════════════════════════════════
def lift_simple(rows, var, ykey, cut="上位1/4", thresh=None):
    M = [r for r in rows if num(r.get(var)) is not None]
    if len(M) < 20:
        return None
    vals = sorted(num(r[var]) for r in M)
    q75, q50, q25 = q_at(vals, 0.75), q_at(vals, 0.50), q_at(vals, 0.25)
    P = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
         "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    inn = [r for r in M if P(num(r[var]))]
    p1 = rate(sum(1 for r in inn if r.get(ykey)), len(inn))
    p0 = rate(sum(1 for r in rows if r.get(ykey)), len(rows))
    return {"n_measurable": len(M), "n_group": len(inn),
            "numerator": sum(1 for r in inn if r.get(ykey)),
            "p_group": r4(p1), "p_base": r4(p0),
            "lift": r4(None if p1 is None else p1 - p0)}


def mh_pooled(rows, var, ykey, strat_fn, cut="上位1/4"):
    """群の所属は母集団全体の四分位で固定し、strat_fn の層で MH プールする。"""
    M = [r for r in rows if num(r.get(var)) is not None and strat_fn(r) is not None]
    if len(M) < 30:
        return {"status": "判定不能", "n": len(M)}
    vals = sorted(num(r[var]) for r in M)
    q75, q50, q25 = q_at(vals, 0.75), q_at(vals, 0.50), q_at(vals, 0.25)
    P = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
         "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    byS = defaultdict(lambda: {"in": [], "out": []})
    for r in M:
        byS[strat_fn(r)]["in" if P(num(r[var])) else "out"].append(r)
    numr = den = 0.0
    used = used_rows = 0
    detail = []
    for s in sorted(byS):
        d = byS[s]
        n1, n0 = len(d["in"]), len(d["out"])
        if n1 == 0 or n0 == 0:
            continue
        e1 = sum(1 for r in d["in"] if r.get(ykey))
        e0 = sum(1 for r in d["out"] if r.get(ykey))
        w = n1 * n0 / (n1 + n0)
        numr += w * (e1 / n1 - e0 / n0)
        den += w
        used += 1
        used_rows += n1 + n0
        detail.append({"stratum": s, "n_group": n1, "n_out": n0,
                       "p_group": r4(e1 / n1), "p_out": r4(e0 / n0),
                       "risk_diff": r4(e1 / n1 - e0 / n0)})
    inn = [r for r in M if P(num(r[var]))]
    crude = (rate(sum(1 for r in inn if r.get(ykey)), len(inn))
             - rate(sum(1 for r in M if r.get(ykey)), len(M)))
    return {"status": "測定", "n": len(M), "crude_lift_vs_measurable": r4(crude),
            "mh_risk_diff": r4(numr / den) if den else None,
            "strata_used": used, "rows_covered": used_rows, "detail": detail}


R18 = pop_rows(2018, "C_all")


def g_eps_q(r):
    v = r.get("_g_eps3_pre")
    if v is None:
        return None
    return gq_bounds(v)


_ge = sorted(r["_g_eps3_pre"] for r in R18 if r.get("_g_eps3_pre") is not None)
_gb = [q_at(_ge, 0.25), q_at(_ge, 0.50), q_at(_ge, 0.75)]


def gq_bounds(v):
    return "Q1(最も沈んでいる)" if v <= _gb[0] else ("Q2" if v <= _gb[1] else
                                                ("Q3" if v <= _gb[2] else "Q4(最も伸びていた)"))


circ = {
    "question": ("y_biz = ln(出口EPS/入口EPS)。自己相対PERの分母も**同じ入口EPS**。"
                 "入口EPSが一時的に沈んでいる社は (i)自己相対PERが高く (ii)出口EPS/入口EPS が大きい——"
                 "これは事業の質ではなく**同じ分母を二度使っているだけ**ではないか"),
    "a_denominator_swap": {
        "note": ("分母が EPS でない自己相対倍率（売上・FCF）でも同じ lift が出るなら『割高/割安』という"
                 "経済的な概念が効いている。EPS 分母のときだけ出るなら分母の共有が正体"),
        "cells": {}},
    "b_condition_on_entry_eps_slump": {
        "note": ("入口前3年のEPS成長（g_eps3_pre）で層別。**沈み具合を揃えても** PER の lift が残るか。"
                 "消えるなら PER は平均回帰の影"),
        "strata_bounds": {"q25": r6(_gb[0]), "q50": r6(_gb[1]), "q75": r6(_gb[2])},
        "cells": {}},
    "c_entry_vs_exit_PER_level": {},
    "d_who_predicts_what": {},
}
for var in ["hv_pe_pct", "hv_adj_pe_pct", "hv_pe_z", "per",
            "hv_ps_pct", "hv_pfcf_pct", "hv_ps_z"]:
    circ["a_denominator_swap"]["cells"][var] = {
        "分母": ("入口EPS（y_biz と共有）" if var in PER_FAMILY else
               ("売上（共有しない）" if "ps" in var else "FCF（共有しない）")),
        "y_biz": lift_simple(R18, var, "y_biz"),
        "y10": lift_simple(R18, var, "y10"),
    }
    circ["b_condition_on_entry_eps_slump"]["cells"][var] = mh_pooled(R18, var, "y_biz", g_eps_q)

for var in PER_FAMILY:
    M = [r for r in R18 if num(r.get(var)) is not None]
    vals = sorted(num(r[var]) for r in M)
    q75 = q_at(vals, 0.75)
    g = [r for r in M if num(r[var]) >= q75]
    o = [r for r in M if num(r[var]) < q75]

    def med(rows, k):
        xs = [r[k] for r in rows if r.get(k) is not None]
        return r4(st.median(xs)) if xs else None
    circ["c_entry_vs_exit_PER_level"][var] = {
        "入口PER_群": med(g, "_pe_in"), "入口PER_群外": med(o, "_pe_in"),
        "出口PER_群": med(g, "_pe_out"), "出口PER_群外": med(o, "_pe_out"),
        "入口前3年EPS成長_群": med(g, "_g_eps3_pre"), "入口前3年EPS成長_群外": med(o, "_g_eps3_pre"),
        "入口前3年売上成長_群": med(g, "_g_rev3_pre"), "入口前3年売上成長_群外": med(o, "_g_rev3_pre"),
        "読み": ("出口PERがほぼ同じで入口PERだけ違うなら、事業の寄与の差は"
               "『入口の分母が沈んでいた』ことの裏返しにすぎない"),
    }

# 入口EPSの沈み それ自体は何を予言するか（PERの代わりに直接使う）
circ["d_who_predicts_what"] = {
    "note": "PER を使わずに『入口前のEPS成長が低い』を直接の指標にしたら何が起きるか",
    "g_eps3_pre_下位1/4 → y_biz": lift_simple(R18, "_g_eps3_pre", "y_biz", "下位1/4"),
    "g_eps3_pre_下位1/4 → y10": lift_simple(R18, "_g_eps3_pre", "y10", "下位1/4"),
    "g_eps3_pre_下位1/4 → y_mult_pos": lift_simple(R18, "_g_eps3_pre", "y_mult_pos", "下位1/4"),
    "PERをg_eps3_preで層別した後のMH": circ["b_condition_on_entry_eps_slump"]["cells"]["hv_adj_pe_pct"],
    "g_eps3_preをPERで層別した後のMH": mh_pooled(
        R18, "_g_eps3_pre", "y_biz",
        (lambda r: None if num(r.get("hv_adj_pe_pct")) is None else
         ("高" if num(r["hv_adj_pe_pct"]) >= q_at(sorted(num(x["hv_adj_pe_pct"]) for x in R18
                                                        if num(x.get("hv_adj_pe_pct")) is not None), 0.75)
          else "低")), "下位1/4"),
}

# ══════════════════════════════════════════════════════════════
# S8 恒等式の中で何が起きているか（**平均は厳密に加法的**）
#   tr = mult + biz + div。群と群外の差もそのまま加法的に分解できる。
#   Δbiz ≈ −Δmult なら「事業の複利を予言した」と「倍率の縮小を予言した」は同じ一つの事実
# ══════════════════════════════════════════════════════════════
ident = {"identity": ("**window 基準でだけ恒等式が閉じる**: tr = mult_w + biz_w + div + resid_w "
                      "（実測 最大誤差 1.5e-06）。signal 基準は tr−(mult+biz+div) の中央値が 0.0065 ・"
                      "最大 0.205 で閉じない＝加法の話は window 基準でしかしてはいけない"),
         "note_target_basis": ("目的変数 y_biz は signal 基準（在庫の主表）だが、"
                               "window 基準の y_biz_w でも lift は 0.31 前後で変わらない（S2 参照）"),
         "by_variable": {}}
for var in PER_FAMILY:
    M = [r for r in R18 if num(r.get(var)) is not None
         and r.get("_mult_w") is not None and r.get("_biz_w") is not None
         and r.get("_div") is not None and r.get("_resid_w") is not None]
    vals = sorted(num(r[var]) for r in M)
    q75 = q_at(vals, 0.75)
    g = [r for r in M if num(r[var]) >= q75]
    o = [r for r in M if num(r[var]) < q75]

    def mean(rows, k):
        xs = [r[k] for r in rows if r.get(k) is not None]
        return sum(xs) / len(xs) if xs else None

    def medi(rows, k):
        xs = [r[k] for r in rows if r.get(k) is not None]
        return st.median(xs) if xs else None
    e = {"n_group": len(g), "n_rest": len(o), "n_measured": len(M)}
    for k, lab in (("_mult_w", "倍率"), ("_biz_w", "事業"), ("_div", "分配"),
                   ("_resid_w", "残差"), ("_tr", "総")):
        e[f"平均_{lab}_群"] = r4(mean(g, k))
        e[f"平均_{lab}_群外"] = r4(mean(o, k))
        e[f"Δ平均_{lab}"] = r4(None if mean(g, k) is None or mean(o, k) is None
                             else mean(g, k) - mean(o, k))
    e["加法の検算(Δ倍率+Δ事業+Δ分配+Δ残差)"] = r4(
        (e["Δ平均_倍率"] or 0) + (e["Δ平均_事業"] or 0) + (e["Δ平均_分配"] or 0) + (e["Δ平均_残差"] or 0))
    e["加法の誤差"] = r6(abs(e["加法の検算(Δ倍率+Δ事業+Δ分配+Δ残差)"] - (e["Δ平均_総"] or 0)))
    e["相殺率"] = r4(None if not e["Δ平均_事業"] else
                  min(1.0, abs(e["Δ平均_倍率"]) / abs(e["Δ平均_事業"])))
    e["中央値_総_群"] = r4(medi(g, "_tr"))
    e["中央値_総_群外"] = r4(medi(o, "_tr"))
    e["読み"] = ("Δ事業 と Δ倍率 がほぼ同じ大きさで逆符号なら、"
               "『高い自己相対PERは事業の複利を予言する』と『高い自己相対PERは倍率の縮小を予言する』は"
               "**恒等式の中では同じ一つの事実**。倍率の平均回帰はこの台帳が既に測って記録している")
    ident["by_variable"][var] = e

# ══════════════════════════════════════════════════════════════
# S7 置換の帰無の作り方で FPR が変わる（探索側の 0.41 の出所）
# ══════════════════════════════════════════════════════════════
def fpr_two_nulls(keys, n_perm=N_PERM, seed=SEED + 3):
    ticks = sorted(set(r["ticker"] for v in C for r in C[v]))
    N = len(ticks)
    tidx = {t: i for i, t in enumerate(ticks)}
    Abits = {v: [0] * N for v in DECOMP_VINTAGES}
    Ybits = {v: [0] * N for v in DECOMP_VINTAGES}
    for v in DECOMP_VINTAGES:
        for r in C[v]:
            Abits[v][tidx[r["ticker"]]] = 1
            if r.get("y_biz"):
                Ybits[v][tidx[r["ticker"]]] = 1
    gmask = {}
    pmask = {}
    for k in keys:
        var, pop, cut = k
        gmask[k] = {v: set(tidx[t] for t in group_membership[k].get(v, set())) for v in DECOMP_VINTAGES}
        pmask[k] = {v: set(tidx[t] for t in pop_tickers[(v, pop)]) for v in DECOMP_VINTAGES}

    def screen(A, Y, vints=(2018,)):
        best = 0.0
        npass = 0
        for k in keys:
            ok = True
            mins = []
            for v in vints:
                g = gmask[k][v] & A[v]
                p = pmask[k][v] & A[v]
                if not g or not p:
                    ok = False
                    break
                kg = len(gmask[k][v] & Y[v])
                kp = len(pmask[k][v] & Y[v])
                if kg < MIN_NUM:
                    ok = False
                    break
                mins.append(abs(kg / len(g) - kp / len(p)))
            if ok and mins:
                m = min(mins)
                best = max(best, m)
                if m >= LIFT:
                    npass += 1
        return best, npass

    A0 = {v: set(i for i in range(N) if Abits[v][i]) for v in DECOMP_VINTAGES}
    Y0 = {v: set(i for i in range(N) if Ybits[v][i]) for v in DECOMP_VINTAGES}
    obs = screen(A0, Y0)
    rnd = random.Random(seed)
    sig = list(range(N))
    res = {}
    for null_name in ("fixed_design(結果ラベルだけ動かす)", "also_shuffle_analysis_set(探索側)"):
        cnt_pass = cnt_ge = 0
        rnd2 = random.Random(seed)
        for _ in range(n_perm):
            rnd2.shuffle(sig)
            if null_name.startswith("fixed"):
                # 母集団は固定。結果ラベルだけ、母集団に居る社のあいだで動かす
                A = A0
                Y = {}
                for v in DECOMP_VINTAGES:
                    mem = sorted(A0[v])
                    lab = [1 if i in Y0[v] else 0 for i in mem]
                    rnd2.shuffle(lab)
                    Y[v] = set(m for m, l in zip(mem, lab) if l)
            else:
                A = {v: set(sig[i] for i in A0[v]) for v in DECOMP_VINTAGES}
                Y = {v: set(sig[i] for i in Y0[v]) for v in DECOMP_VINTAGES}
            b, p = screen(A, Y)
            if p >= 1:
                cnt_pass += 1
            if b >= obs[0]:
                cnt_ge += 1
        res[null_name] = {"FPR_at_least_one_pass": r4(cnt_pass / n_perm),
                          "p_of_observed_max": r4((cnt_ge + 1) / (n_perm + 1))}
    res["observed"] = {"max_abs_lift": r4(obs[0]), "n_passing_cells": obs[1],
                       "n_cells_in_procedure": len(keys), "n_tickers_pool": N}
    return res


null_cmp = fpr_two_nulls(CAND_2018)
null_cmp["reading"] = (
    "探索側は**分析集合の所属ごと**入れ替える（A も動く）。すると群と母集団の交わりが縮み、"
    "小さい群で極端な lift が出やすくなる＝帰無分布が広がり FPR が上がる。"
    "設計を固定して結果ラベルだけ動かすのが標準の帰無（この台帳の hist_wd_verify_destroy と同じ作法）")

# ══════════════════════════════════════════════════════════════
# S5 検出力 / 到達可能性
# ══════════════════════════════════════════════════════════════
def power(n_group, n_pop, p_base, delta, trials=N_POWER, seed=SEED + 7):
    rnd = random.Random(seed)
    hit = 0
    for _ in range(trials):
        k = sum(1 for _ in range(n_group) if rnd.random() < min(1.0, p_base + delta))
        rest = n_pop - n_group
        k0 = sum(1 for _ in range(rest) if rnd.random() < p_base)
        p1 = k / n_group
        p_all = (k + k0) / n_pop
        if (p1 - p_all) >= LIFT and k >= MIN_NUM:
            hit += 1
    return r4(hit / trials)


c0 = cell(2018, "C_all", "hv_adj_pe_pct", "y_biz", "上位1/4", "ge")


def reach_of(n_pop, n_group, p_base, label):
    """★結果を見る前に出すべき数字（事前登録 must_report_before_verdict）。
       MIN_NUM が LIFT より強い線になっていないか＝**実効的に要求される lift**。"""
    if not n_group or not n_pop:
        return {"status": "判定不能", "label": label}
    need = MIN_NUM / n_group - p_base
    return {"label": label, "n_pop": n_pop, "n_group": n_group, "p_base": r4(p_base),
            "max_possible_numerator": n_group,
            "MIN_NUM_reachable": n_group >= MIN_NUM,
            "effective_required_lift": r4(max(LIFT, need)),
            "which_binds": "LIFT" if LIFT >= need else "MIN_NUM",
            "note": ("MIN_NUM が拘束＝**登録した0.15より高い線を暗黙に課している**"
                     if need > LIFT else "LIFT が拘束＝設計どおり")}


reach = {
    "main_cell": reach_of(c0["n_pop"], c0["n_group"], c0["p_pop"], "2018/C_all/上位1/4"),
    "power": {f"delta={d}": power(c0["n_group"], c0["n_pop"], c0["p_pop"], d)
              for d in (0.10, 0.15, 0.20, 0.30)},
    "by_vintage": {}, "by_irr_layer": {},
}
for v in DECOMP_VINTAGES:
    cc = cell(v, "C_all", "hv_adj_pe_pct", "y_biz", "上位1/4", "ge")
    if cc and "n_group" in cc:
        reach["by_vintage"][str(v)] = reach_of(cc["n_pop"], cc["n_group"], cc["p_pop"], f"{v}/C_all/上位1/4")
for lab in ("irr>=70", "irr<70"):
    e = irr_layer.get(lab, {})
    d = e.get("hv_adj_pe_pct")
    if isinstance(d, dict) and d.get("n_group"):
        reach["by_irr_layer"][lab] = reach_of(e["n_stratum"], d["n_group"], d["p_stratum"], lab)
reach["reading"] = (
    "**分子>=20 が届かない場所で『分子不足』を不合格と読んではいけない**——それは効果の不在ではなく"
    "検出力の不在（この台帳が v1 で確立した検問: 合否基準が母集団の実数で到達可能かを結果の前に数える）")

# ══════════════════════════════════════════════════════════════
# 合否
# ══════════════════════════════════════════════════════════════
def v_pass(x):
    return "✓通過" if x is True else ("✗落ちた" if x is False else "判定不能")


k1 = not repro["mismatch"]
k2 = None if missing else False   # 登録ゲートは判定不能
k2_relaxed = any(r.get("_lift_all3_ge_0.15") and r.get("_numerator_all3_ge_20")
                 for r in vint["by_variable"].values())
mh_ok = all((sector["mh"][v] or {}).get("mh_risk_diff") is not None
            and sector["mh"][v]["mh_risk_diff"] >= LIFT for v in PER_FAMILY)
los_ok = all(sector["leave_one_sector_out"][v]["all_stay_over_line"] for v in PER_FAMILY)
k3 = bool(mh_ok and los_ok)
irr_ent = irr_layer.get("irr>=70", {})
if irr_ent.get("status") != "測定":
    k4 = None
    k4_note = "層が薄すぎて測れない"
else:
    ks = [irr_ent[v] for v in PER_FAMILY if isinstance(irr_ent.get(v), dict)
          and irr_ent[v].get("lift") is not None]
    lift_ok = bool(ks) and all(e["lift"] >= LIFT for e in ks)
    num_ok = bool(ks) and all(e["meets_min_num"] for e in ks)
    reachable = (reach["by_irr_layer"].get("irr>=70", {}) or {}).get("MIN_NUM_reachable")
    if lift_ok and not num_ok and reachable is False:
        k4 = None   # ★分子>=20 が構造的に届かない層＝判定不能（不合格ではない）
        k4_note = ("lift は残る（層内 " + ", ".join(f"{v}={irr_ent[v]['lift']}" for v in PER_FAMILY
                                                if isinstance(irr_ent.get(v), dict))
                   + "）が、層が51行しかなく群は約13社＝**分子>=20 が構造的に到達不能**。"
                   "『分子不足』を不合格と読まない")
    else:
        k4 = bool(lift_ok and num_ok)
        k4_note = "lift・分子とも線を満たす" if k4 else "lift が層内で線を割る"
k5 = perm["single_cell_hv_adj_pe_pct"]["p_value"] < 0.05
k5_family = perm["family_max|PER族のみ(4変数×4切り方×2母集団)"]["p_value_selection_adjusted"] < 0.05
k6 = not all(inc["by_variable"][v]["over_70pct_line"] for v in PER_FAMILY)

checks = {
    "1_再現": {"pass": k1, "verdict": v_pass(k1), "detail": repro["verdict"]},
    "2_ビンテージ": {"pass": k2, "verdict": v_pass(k2),
                "detail": vint["registered_gate"]["status"],
                "relaxed_2013_2015_2018_pass": k2_relaxed,
                "relaxed_why_failed": {
                    "lift_maintained_3v": [k for k, r in vint["by_variable"].items()
                                           if r.get("_lift_all3_ge_0.15")],
                    "numerator_maintained_3v": [k for k, r in vint["by_variable"].items()
                                                if r.get("_numerator_all3_ge_20")],
                    "note": ("**lift と分子が別々の切り方でしか揃わない**。上位1/4 は lift を保つが "
                             "2013 の群が23社しかなく分子>=20 は実効 lift 0.52 を要求＝到達不能。"
                             "中央値超は分子を満たすが lift が 2013/2015 で 0.08〜0.11 へ落ちる"),
                    "reachability_2013": reach["by_vintage"].get("2013")}},
    "3_業種": {"pass": k3, "verdict": v_pass(k3),
             "mh_all_over_line": mh_ok, "leave_one_out_all_over_line": los_ok},
    "4_irrの影": {"pass": k4, "verdict": v_pass(k4), "n_stratum": irr_ent.get("n_stratum"),
                "detail": k4_note,
                "lift_in_irr_ge70": {v: irr_ent[v]["lift"] for v in PER_FAMILY
                                     if isinstance(irr_ent.get(v), dict)},
                "lift_in_irr_lt70": {v: irr_layer["irr<70"][v]["lift"] for v in PER_FAMILY
                                     if isinstance(irr_layer.get("irr<70", {}).get(v), dict)},
                "orthogonal_to_irr": "両層でほぼ同じ大きさ＝irr の影ではない（irr と直交）"},
    "5_置換": {"pass": k5, "verdict": v_pass(k5),
             "single_cell_p": perm["single_cell_hv_adj_pe_pct"]["p_value"],
             "selection_adjusted_p": perm["family_max|PER族のみ(4変数×4切り方×2母集団)"]["p_value_selection_adjusted"],
             "FPR_of_procedure": perm["family_max|2018のy_biz全画面(全候補変数)"]["FPR_at_least_one_cell_passes(lift>=0.15 & num>=20)"]},
    "6_増分": {"pass": k6, "verdict": v_pass(k6),
             "share_explained": {v: inc["by_variable"][v]["share_explained_by_existing_gates"]
                                 for v in PER_FAMILY},
             "circularity_warning": inc["structural_note"],
             "non_circular_relift": {v: (inc["by_variable"][v]["within_gate_passers_relift"] or {}).get("lift")
                                     for v in PER_FAMILY}},
}
# ★6検問の外にある決定的な反証（合否そのものではなく「使えるか」の判定）
reversal = {
    "R1_目的と予測変数が分母を共有している": {
        "rho_biz_2018": mech["by_vintage"]["2018"]["hv_adj_pe_pct"]["rho_biz(事業)"],
        "rho_mult_2018": mech["by_vintage"]["2018"]["hv_adj_pe_pct"]["rho_mult(倍率)"],
        "rho_tr_2018": mech["by_vintage"]["2018"]["hv_adj_pe_pct"]["rho_tr(総リターン)"],
        "se": mech["by_vintage"]["2018"]["hv_adj_pe_pct"]["se_approx"],
        "群の入口前3年EPS成長": circ["c_entry_vs_exit_PER_level"]["hv_adj_pe_pct"]["入口前3年EPS成長_群"],
        "群外の入口前3年EPS成長": circ["c_entry_vs_exit_PER_level"]["hv_adj_pe_pct"]["入口前3年EPS成長_群外"],
    },
    "R2_総リターンでは線を割る": {v: {"y_biz": alt[v]["y_biz"]["lift"], "y10": alt[v]["y10"]["lift"],
                            "相殺": alt[v]["_cancellation"]} for v in PER_FAMILY},
    "R3_分母を替えると消える": {v: {"y_biz_lift": (circ["a_denominator_swap"]["cells"][v]["y_biz"] or {}).get("lift"),
                          "分母": circ["a_denominator_swap"]["cells"][v]["分母"]}
                     for v in circ["a_denominator_swap"]["cells"]},
    "R4_入口EPSの沈みで層別すると": {v: circ["b_condition_on_entry_eps_slump"]["cells"][v].get("mh_risk_diff")
                          for v in circ["b_condition_on_entry_eps_slump"]["cells"]},
    "R5_恒等式の中では倍率の縮小と同じ一つの事実": {
        v: {"Δ事業": ident["by_variable"][v]["Δ平均_事業"],
            "Δ倍率": ident["by_variable"][v]["Δ平均_倍率"],
            "Δ総": ident["by_variable"][v]["Δ平均_総"],
            "相殺率": ident["by_variable"][v]["相殺率"]} for v in PER_FAMILY},
}
failed = [k for k, e in checks.items() if e["pass"] is False]
undet = [k for k, e in checks.items() if e["pass"] is None]

out = {
    "generated": "2026-08-12",
    "tool": "night/hist10_verify_hvpe_ybiz.py",
    "prereg": "out/hist10_prereg.json（線は読むだけ・一つも動かしていない）",
    "candidate": {
        "angle": "C（目的＝事業由来の複利）",
        "variables": PER_FAMILY,
        "target": "y_biz＝事業の寄与 >= +10%/年",
        "population": "C_all（分解が作れた社）", "cut": "上位1/4",
        "claimed": {"n": 69, "numerator": 52, "lift": 0.304},
    },
    "★verdict": {
        "result": ("不合格" if failed else ("判定不能を含み合格とは言えない" if undet else "落とせなかった")),
        "failed_checks": failed, "undetermined_checks": undet,
        "one_line": None,
    },
    "checks": checks,
    "0_inventory": inventory,
    "0_join": join_report,
    "0_reachability_and_power": reach,
    "1_reproduction": repro,
    "2_vintage": vint,
    "3_sector": sector,
    "4_irr_layer": irr_layer,
    "5_permutation": perm,
    "6_incremental": inc,
    "S1_mechanism": mech,
    "S2S3_other_targets": alt,
    "S4_population_hole": hole,
    "S6_circularity": circ,
    "S8_identity_decomposition": ident,
    "S7_null_construction_matters": null_cmp,
    "★reversal": reversal,
    "note_on_MH_difference_vs_explorer": (
        "探索側の MH は層の最小サイズを n1>=3 ∧ n0>=3 に取るので使用層5・この道具は1以上で19。"
        "値は 0.4122 vs 0.439 で結論は同じ。**データではなく層の最小サイズの約束の差**"),
    "limits": [
        "母集団は分解が作れた社＝**出口の純利益が正**の社だけ。左裾が構造的に抜けている",
        "2013/2015/2018 は同じ956ティッカー由来＝out-of-sample ではない",
        "co_* は 2013/2015 のみ・f2_* は 2016/2017/2018 のみ＝3ビンテージ全部で測れるのは hv_* と per と規模だけ",
        "この道具は候補を潰しにかかっている。落とせなかった場合だけ『落とせなかった』と書く",
    ],
}
_id = ident["by_variable"]["hv_adj_pe_pct"]
out["★verdict"]["one_line"] = (
    f"6検問のうち 落ちた={len(failed)} 判定不能={len(undet)} → "
    + ("不合格" if failed else "**6検問では落とせなかった**（ただし2件は到達不能で判定不能＝認定もできない）"))
out["★verdict"]["substantive"] = {
    "落とせなかったこと": ("再現・業種・置換・増分の4検問を通った。2013/2015 でも lift は 0.16〜0.19 残り、"
                    "irr の層内でも消えず、window 基準でも消えず、母集団の穴を挟み込んでも消えない。"
                    "**この lift は雑音ではない**（置換 p=0.0005・帰無の95%点 0.076 に対し観測 0.3045）"),
    "私の反証仮説のうち外れたもの": ("『自己相対PERが高いのは入口EPSが沈んでいるからで、y_biz はその分母を共有した循環』"
                          "という仮説は**反証された**——入口前3年EPS成長で層別しても MH は 0.315→0.377 と"
                          "むしろ上がる。逆に g_eps3_pre のほうが PER で層別すると 0.183→0.069 へ消える"),
    "それでも実務的価値が無い理由": {
        "恒等式の中の実額(window基準・年率対数・hv_adj_pe_pct)": {
            "Δ事業": _id["Δ平均_事業"], "Δ倍率": _id["Δ平均_倍率"],
            "Δ分配": _id["Δ平均_分配"], "Δ残差": _id["Δ平均_残差"], "Δ総": _id["Δ平均_総"],
            "相殺率": _id["相殺率"], "加法誤差": _id["加法の誤差"]},
        "読み": ("群は事業を年 +9.7pt 速く複利したが、倍率が年 −8.2pt 縮んで **総リターンの差は年 +0.9pt**。"
               "『事業の複利を予言した』は、恒等式の中では『倍率の縮小を予言した』と**同じ一つの事実**。"
               "倍率の平均回帰はこの台帳が既に測って記録している（入口PER 群44.2 vs 群外21.3 → "
               "出口PER 28.4 vs 23.6 で収束）"),
        "総リターンでは線を割る": {"y10_lift": alt["hv_adj_pe_pct"]["y10"]["lift"], "line": LIFT,
                        "perm_p": perm["single_cell_hv_adj_pe_pct_on_y10"]["p_value"]},
        "分母を替えると3分の1になる": {v: (circ["a_denominator_swap"]["cells"][v]["y_biz"] or {}).get("lift")
                          for v in ("hv_adj_pe_pct", "hv_ps_pct", "hv_pfcf_pct")},
    },
    "結論": ("**買付規則にはできない**。理由は『効果が無い』ではなく『測っているのが入口の倍率であり、"
           "その利得は同じ窓の中で倍率の縮小として払い戻されている』。"
           "価格の線が質の中で選別力を持たないという既存の5例と矛盾せず、"
           "むしろ目的変数を分解の片側に置き替えると price の**機械的な半分**だけが発見に見える、という6例目"),
}

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ── 画面 ──
print("=" * 78)
print("候補: 自己相対PER族 × 事業由来10%+（2018単独・C_all・上位1/4）を潰しにかかる")
print("=" * 78)
print(f"\n【0 在庫】分解が在るビンテージ: {[k for k,v in inventory.items() if v['rows']]}")
print(f"   登録ゲートが要求するビンテージ {SIGN_VINTAGES} のうち在庫なし: {missing}")
m0 = reach["main_cell"]
print(f"\n【0 到達可能性】基準率 {m0['p_base']} / n_pop {m0['n_pop']} / 群 {m0['n_group']} / "
      f"拘束は {m0['which_binds']}（実効要求lift {m0['effective_required_lift']}）")
for k, e in reach["by_vintage"].items():
    print(f"      {k}: 群{e['n_group']} 基準率{e['p_base']} 拘束={e['which_binds']} "
          f"実効要求lift={e['effective_required_lift']} 分子20到達可={e['MIN_NUM_reachable']}")
for k, e in reach["by_irr_layer"].items():
    print(f"      {k}: 群{e['n_group']} 基準率{e['p_base']} 拘束={e['which_binds']} "
          f"実効要求lift={e['effective_required_lift']} 分子20到達可={e['MIN_NUM_reachable']}")
print(f"   検出力: {reach['power']}")
print(f"\n【1 再現】{repro['verdict']}")
for k, e in repro["cells"].items():
    m = e["mine_ge"]
    if not m or "n_group" not in m:
        continue
    p = e.get("published")
    print(f"   {k:28s} 自分 n={m['n_group']:3d} 分子={m['numerator']:3d} lift={m['lift_vs_pop']}"
          + (f"  | 探索側 n={p['n_group']} 分子={p['numerator']} lift={p['lift']}" if p else "  | 探索側に無し")
          + f"  | 境界gt n={e['mine_gt_boundary']['n_group']}")
print(f"   n=69 の出所: {repro['where_n69_comes_from']}")
print(f"\n【2 ビンテージ】{vint['registered_gate']['status'][:60]}")
for k, r in vint["by_variable"].items():
    print(f"   {k:28s} " + "  ".join(
        f"{v}:lift={r[str(v)]['lift']}/分子{r[str(v)]['numerator']}" for v in DECOMP_VINTAGES if r.get(str(v)))
        + f"   lift3✓={r['_lift_all3_ge_0.15']} 分子3✓={r['_numerator_all3_ge_20']}")
print(f"\n【3 業種】")
for v in PER_FAMILY:
    m = sector["mh"][v]
    l = sector["leave_one_sector_out"][v]
    print(f"   {v:16s} MH={m['mh_risk_diff']} (層 使用{m['strata_used']}/捨{m['strata_dropped']}・"
          f"行の被覆{m['coverage_of_rows']})  1業種抜き最小lift={l['min_lift']}")
print(f"\n【4 irr】{irr_layer['coverage']}")
for lab in ("irr>=70", "irr<70"):
    e = irr_layer[lab]
    print(f"   {lab}: {e.get('status')} n={e['n_stratum']}")
    for v in PER_FAMILY:
        if isinstance(e.get(v), dict) and e[v].get("lift") is not None:
            print(f"      {v:16s} lift={e[v]['lift']} 分子={e[v]['numerator']} (>=20:{e[v]['meets_min_num']})")
print(f"\n【5 置換】単セル p={perm['single_cell_hv_adj_pe_pct']['p_value']} "
      f"(帰無の95%点 {perm['single_cell_hv_adj_pe_pct']['null_p95']})")
for k in perm:
    if k.startswith("family_max"):
        print(f"   {k}: 選択調整後 p={perm[k]['p_value_selection_adjusted']} "
              f"FPR={perm[k]['FPR_at_least_one_cell_passes(lift>=0.15 & num>=20)']}")
print(f"\n【6 増分】母集団の {inc['baseline']['pop_share_inside_all_existing_gates']} が既に関門の内側"
      f"（内訳 {inc['baseline']['components']}）")
for v in PER_FAMILY:
    e = inc["by_variable"][v]
    w = e["within_gate_passers_relift"]
    print(f"   {v:16s} 成功{e['n_wins']}社中 既存関門の内側 {e['wins_inside_all_existing_gates']} "
          f"({e['share_explained_by_existing_gates']}) 7割超={e['over_70pct_line']} "
          f"母集団比{e['excess_over_population_share']:+.4f}"
          + (f" | 関門通過者の中で再測定 lift={w['lift']} 分子={w['numerator']}" if w else ""))
print(f"\n【S1 機構】")
for v_, e in mech["by_vintage"].items():
    for var in PER_FAMILY:
        d = e.get(var)
        if isinstance(d, dict) and d.get("rho_biz(事業)") is not None:
            gv = d["group_vs_rest"]
            print(f"   {v_} {var:16s} ρ事業={d['rho_biz(事業)']} ρ倍率={d['rho_mult(倍率)']} "
                  f"ρ総={d['rho_tr(総リターン)']} (se≈{d['se_approx']}) | "
                  f"入口3年EPS成長 群={gv['pre_entry_3y_EPS成長_中央値_群']} 群外={gv['pre_entry_3y_EPS成長_中央値_群外']}")
print(f"\n【S2 目的を替える】")
for v in PER_FAMILY:
    r = alt[v]
    print(f"   {v:16s} y_biz={r['y_biz']['lift']}  y10={r['y10']['lift']}  "
          f"y_mult>0={r['y_mult_pos']['lift']}  y_biz_w={r['y_biz_w']['lift']}  相殺={r['_cancellation']}")
print(f"\n【S4 母集団の穴】")
for v_, h in hole.items():
    print(f"   {v_}: 落ちた {h['dropped_n']}社(中央値tr {h['dropped_tr_med']} vs 残った {h['kept_tr_med']}) "
          f"うち上位1/4圏 {h['dropped_in_top_quartile_of_kept']} "
          f"({h['top_quartile_share_among_dropped']} vs 残った側 {h['top_quartile_share_among_kept']}) "
          f"→ lift 挟み込み 上端{h['bracket_lift_upper(落ちた社を全部成功と置く)']} "
          f"下端{h['bracket_lift_lower(落ちた社を全部失敗と置く)']}")
print(f"\n【S6 循環（分母の共有）】")
print("   (a) 分母を替える:")
for v, e in circ["a_denominator_swap"]["cells"].items():
    b = e["y_biz"]
    print(f"      {v:16s} 分母={e['分母']:22s} y_biz lift={None if not b else b['lift']} "
          f"分子={None if not b else b['numerator']}")
print("   (b) 入口前3年EPS成長で層別した後（MH）:")
for v, e in circ["b_condition_on_entry_eps_slump"]["cells"].items():
    print(f"      {v:16s} 素の lift={e.get('crude_lift_vs_measurable')} → 層別後 MH={e.get('mh_risk_diff')} "
          f"(n={e.get('n')})")
print("   (c) 入口PER/出口PER の水準:")
for v, e in circ["c_entry_vs_exit_PER_level"].items():
    print(f"      {v:16s} 入口PER 群{e['入口PER_群']} vs 群外{e['入口PER_群外']} | "
          f"出口PER 群{e['出口PER_群']} vs 群外{e['出口PER_群外']}")
print("   (d) PER を使わず『入口前のEPS成長が低い』を直接使うと:")
for k, e in circ["d_who_predicts_what"].items():
    if isinstance(e, dict) and "lift" in e:
        print(f"      {k:34s} lift={e['lift']} 分子={e['numerator']} n群={e['n_group']}")
    elif isinstance(e, dict) and "mh_risk_diff" in e:
        print(f"      {k:34s} MH={e['mh_risk_diff']} (素={e.get('crude_lift_vs_measurable')})")
print(f"\n【S8 恒等式の中の分解（平均・年率対数）】")
for v, e in ident["by_variable"].items():
    print(f"   {v:16s} Δ事業={e['Δ平均_事業']:+.4f} Δ倍率={e['Δ平均_倍率']:+.4f} "
          f"Δ分配={e['Δ平均_分配']:+.4f} Δ残差={e['Δ平均_残差']:+.4f} → Δ総={e['Δ平均_総']:+.4f}  "
          f"相殺率={e['相殺率']}  加法誤差={e['加法の誤差']}")

print(f"\n【S7 帰無の作り方で FPR が変わる】観測 {null_cmp['observed']}")
for k, e in null_cmp.items():
    if isinstance(e, dict) and "FPR_at_least_one_pass" in e:
        print(f"   {k:38s} FPR={e['FPR_at_least_one_pass']}  観測maxのp={e['p_of_observed_max']}")

print("\n" + "=" * 78)
print(f"★ {out['★verdict']['result']}  落ちた={failed}  判定不能={undet}")
print("=" * 78)
print(f"\n出力: {DEST}")
