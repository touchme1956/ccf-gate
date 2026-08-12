#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_rnd_sga_medq.py — 候補
  「f2_rnd_r[中央値超] ∧ f2_sga_r[中央値以下] / **勝者側** / **P_quality**」
を **潰しにかかる** 検証。

⚠ 姉妹の道具と混同しないこと（同じ変数の組でも切り方・母集団が違えば別の候補）:
  night/hist_wd_verify_rnd_sga.py       … P_full   ∧ rnd[上位1/4] ∧ sga[中央値以下]
  night/hist_wd_verify_rnd_sga_indep.py … 同上の独立実装
  night/hist_wd_verify_rnd_sga_q.py     … P_quality ∧ rnd[**上位1/4**] ∧ sga[中央値以下]
  この道具                              … P_quality ∧ rnd[**中央値超**]  ∧ sga[中央値以下]
                                          （2018で n=55 / 分子25 / lift 0.2599）

事前登録: out/hist_winner_destroyer_prereg.json
  **合否の線はそこにある。この道具は線を一つも作らない。**
入力    : out/hist_wd_panel.json        … 5ビンテージ統合パネル（唯一の真実）
          out/hist_wd_win_pair.json     … 探索側の答え（**信じる前に検算する相手**／探索空間の列挙のみ借用）
出力    : out/hist_wd_verify_rnd_sga_medq.json

────────────────────────────────────────────────────────────
立場
────────────────────────────────────────────────────────────
**反証が仕事であって確認ではない。** 候補に有利な数字を探さない。
prereg の5条件（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を一つも緩めない。
線の外の数字を出すときは `事前登録の外・診断専用` と明記し、合否には数えない。
「測れない」と「不合格」を区別する（f2_ は 2013/2015 に構造的に存在しない＝判定不能）。

当てる6つ（1つでも落ちたら不合格）
 1 ビンテージ符号   2016/2017/2018 で符号が反転しないか。**3つが独立な3証拠かも実測する**
 2 業種調整         同一 sic2 内で残るか（MH＋層内置換＋業種1つずつ除去＋間接標準化）
 3 irr の影         irr>=70 層内で残るか / irr と直交か / irr=85 を抜いても残るか
 4 1社の影響        ティッカーを1社ずつ**パネルごと**抜いて、閾値から全部作り直す
 5 置換             outcome をティッカー束で置換（ビンテージ間相関を保つ帰無）2000回。
                    単体の p と、**探索空間1420組の族単位**の値札の両方
 6 既存の関門との重複 事業の収縮 / 利払カバー（財務キルの歴史側代理）/ 質実証 の増分
"""
import json, os, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
SEARCH = os.path.join(OUT, "hist_wd_win_pair.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
DST = os.path.join(OUT, "hist_wd_verify_rnd_sga_medq.json")

VINT = [2016, 2017, 2018]
POP = "P_quality"
SIDE = "win"
VAR_A, CUT_A = "f2_rnd_r", "中央値超"
VAR_B, CUT_B = "f2_sga_r", "中央値以下"
LABEL = f"{VAR_A}[{CUT_A}] ∧ {VAR_B}[{CUT_B}]"

LIFT_LINE = 0.15
MIN_NUM = 5
NPERM = 2000
SEED = 20260811


# ────────────────────────────── 基本部品 ──────────────────────────────
def nearest_rank(xs, q):
    """nearest-rank 分位（探索側の design_decisions と同じ作法）。xs はソート済み。"""
    n = len(xs)
    if n == 0:
        return None
    k = max(1, math.ceil(q * n))
    return xs[k - 1]


def cut_mask(vals, cut):
    """cut に対応する (threshold, operator, predicate) を返す。閾値は可測行のみで作る。"""
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None, None, None
    if cut == "上位1/4":
        thr = nearest_rank(xs, 0.75)
        return thr, ">=", (lambda v: v >= thr)
    if cut == "中央値超":
        thr = nearest_rank(xs, 0.50)
        return thr, ">", (lambda v: v > thr)
    if cut == "中央値以下":
        thr = nearest_rank(xs, 0.50)
        return thr, "<=", (lambda v: v <= thr)
    if cut == "下位1/4":
        thr = nearest_rank(xs, 0.25)
        return thr, "<=", (lambda v: v <= thr)
    raise ValueError(cut)


def rate(rows, key="win"):
    n = len(rows)
    k = sum(1 for r in rows if r[key])
    return n, k, (k / n if n else None)


def r4(x):
    return None if x is None else round(x, 4)


def wilson(k, n, z=1.96):
    """二項の95%CI（Wilson）。分子が小さい群を『点』で語らないため。"""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def fisher_p(a, b, c, d):
    """2x2 の Fisher 両側（片側×2ではなく、確率の小さい表を全部足す厳密版）。"""
    n = a + b + c + d
    if n == 0:
        return None
    def lch(n, k):
        return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    r1, r2 = a + b, c + d
    c1 = a + c
    denom = lch(n, c1)
    def prob(x):
        return math.exp(lch(r1, x) + lch(r2, c1 - x) - denom)
    p0 = prob(a)
    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    tot = 0.0
    for x in range(lo, hi + 1):
        p = prob(x)
        if p <= p0 * (1 + 1e-9):
            tot += p
    return round(min(1.0, tot), 5)


# ────────────────────────────── パネル読み込み ──────────────────────────────
def load():
    panel = json.load(open(PANEL, encoding="utf-8"))
    rows = panel["rows"]
    # 分析集合: 探索側と同一（has_outcome ∧ window_full）
    pops = {}
    for v in VINT:
        pops[v] = [r for r in rows
                   if r["vintage"] == v and r.get(POP) and r["has_outcome"] and r["window_full"]]
    return panel, rows, pops


def build_cell(pop_rows, var_a=VAR_A, cut_a=CUT_A, var_b=VAR_B, cut_b=CUT_B):
    """母集団 → 閾値 → 群 → lift。閾値は outcome を一切見ないので置換で不変。"""
    ta, opa, pa = cut_mask([r[var_a] for r in pop_rows], cut_a)
    tb, opb, pb = cut_mask([r[var_b] for r in pop_rows], cut_b)
    if pa is None or pb is None:
        return None
    grp, meas_both = [], []
    for r in pop_rows:
        if r[var_a] is None or r[var_b] is None:
            continue
        meas_both.append(r)
        if pa(r[var_a]) and pb(r[var_b]):
            grp.append(r)
    n_pop, k_pop, p_pop = rate(pop_rows)
    n_g, k_g, p_g = rate(grp)
    n_m, k_m, p_m = rate(meas_both)
    return {
        "n_pop": n_pop, "k_pop": k_pop, "p_base": r4(p_pop),
        "thr_a": r4(ta), "op_a": opa, "n_meas_a": sum(1 for r in pop_rows if r[var_a] is not None),
        "thr_b": r4(tb), "op_b": opb, "n_meas_b": sum(1 for r in pop_rows if r[var_b] is not None),
        "n_measurable_both": n_m, "p_base_measurable": r4(p_m),
        "n_group": n_g, "numerator": k_g, "p_group": r4(p_g),
        "p_group_ci95": wilson(k_g, n_g),
        "lift": r4(p_g - p_pop) if n_g else None,
        "lift_vs_measurable_both": r4(p_g - p_m) if (n_g and n_m) else None,
        "fisher_p_vs_rest_of_pop": fisher_p(k_g, n_g - k_g, k_pop - k_g, (n_pop - n_g) - (k_pop - k_g)),
        "_rows": grp, "_pop": pop_rows, "_meas": meas_both,
    }


def verdict_of(cells):
    """prereg の 1(lift) 2(分子) 3(符号不変) だけの機械判定。業種/irr は別枠で当てる。"""
    lifts = [c["lift"] for c in cells if c]
    nums = [c["numerator"] for c in cells if c]
    if len(lifts) != len(VINT) or any(l is None for l in lifts):
        return {"pass_core": None, "reason": "判定不能（セル欠損）"}
    signs = {1 if l > 0 else (-1 if l < 0 else 0) for l in lifts}
    ok_sign = len(signs) == 1 and 0 not in signs
    maintained = min(abs(l) for l in lifts) if ok_sign else 0.0
    ok_lift = maintained >= LIFT_LINE
    ok_num = min(nums) >= MIN_NUM
    return {
        "pass_core": bool(ok_sign and ok_lift and ok_num),
        "maintained_lift": r4(maintained),
        "min_numerator": min(nums),
        "sign_stable": ok_sign,
        "gate_failed_at": (None if (ok_sign and ok_lift and ok_num)
                           else ("sign" if not ok_sign else ("lift" if not ok_lift else "min_numerator"))),
    }


# ────────────────────────────── 実行 ──────────────────────────────
def main():
    t0 = time.time()
    random.seed(SEED)
    panel, rows, pops = load()
    prereg = json.load(open(PREREG, encoding="utf-8"))
    search = json.load(open(SEARCH, encoding="utf-8"))

    O = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_verify_rnd_sga_medq.py",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "candidate": {
            "label": LABEL, "population": POP, "side": SIDE,
            "search_side_claim": "2018 n=55 / 分子25 / lift 0.2599 / maintained 0.2424（探索側の弁: 合格）",
            "why_verify": "探索側自身が『業種内lift +0.005〜+0.056＝ほぼゼロ（SIC36単独 +0.2284）』と書いている。"
                          "潰せるはずの候補を潰しにいく。",
        },
        "stance": "反証が仕事。線は prereg にあり、この道具は一つも作らない。線の外の数字は『事前登録の外・診断専用』と明記する。",
        "pass_line": {"lift": LIFT_LINE, "min_numerator": MIN_NUM,
                      "sign_stability": VINT, "sector_control": "同一sic2内でも残る",
                      "not_irr_shadow": "irr>=70層内でも残る、またはirrと直交", "all_required": True},
    }

    # ── 0 再現（探索側を信じる前に検算する） ─────────────────────────
    cells = {v: build_cell(pops[v]) for v in VINT}
    core = verdict_of([cells[v] for v in VINT])
    src = {}
    for p in search["passing_pairs_detail"]:
        if p["label"] == LABEL and p["population"] == POP:
            src = p
            break
    rep = {}
    for v in VINT:
        c, s = cells[v], (src.get("by_vintage") or {}).get(str(v)) or {}
        rep[v] = {
            "mine": {"n_pop": c["n_pop"], "n_group": c["n_group"], "numerator": c["numerator"], "lift": c["lift"]},
            "search": {"n_pop": s.get("n_pop"), "n_group": s.get("n_group"),
                       "numerator": s.get("numerator"), "lift": s.get("lift")},
            "identical": (c["n_pop"] == s.get("n_pop") and c["n_group"] == s.get("n_group")
                          and c["numerator"] == s.get("numerator")),
        }
    O["step0_replication"] = {
        "note": "同じ台帳を見る二つの検査器が違うことを言ってはいけない(v9.9.65)。まず探索側を検算する。",
        "by_vintage": rep,
        "all_identical": all(rep[v]["identical"] for v in VINT),
        "threshold_check": {
            "note": "分位の作法（nearest-rank）まで揃えると閾値も一致した。"
                    "⚠ 途中で statistics 流の中央値（偶数個なら2つの平均）を使うと 2018 の rnd 閾値が 0.0097 になる"
                    "——群・分子・lift はどちらでも同じだったが、**閾値の作法が違えば別の群になりうる**。",
            "mine_2018_thr_rnd": cells[2018]["thr_a"], "search_2018_thr_rnd": 0.0094,
            "mine_2018_thr_sga": cells[2018]["thr_b"], "search_2018_thr_sga": 0.1841,
            "identical": (cells[2018]["thr_a"] == 0.0094 and cells[2018]["thr_b"] == 0.1841),
        },
        "core_gates_1_2_3": core,
    }

    # ── 到達可能性と実効の線（v2の教訓: MIN_NUM が LIFT より強く縛っていないか） ──
    reach = {}
    for v in VINT:
        c = cells[v]
        n_g, base, events = c["n_group"], c["p_base"], c["k_pop"]
        k_by_lift = math.ceil((base + LIFT_LINE) * n_g)
        reach[v] = {
            "n_group": n_g, "events_in_pop": events, "base": base,
            "k_required_by_lift": k_by_lift, "k_required_by_min_num": MIN_NUM,
            "binding": "LIFT" if k_by_lift >= MIN_NUM else "MIN_NUM",
            "effective_lift_required": r4(max(k_by_lift, MIN_NUM) / n_g - base),
            "reachable": (max(k_by_lift, MIN_NUM) <= n_g and max(k_by_lift, MIN_NUM) <= events),
        }
    O["step0b_reachability"] = {
        "note": "この候補は群が50-55と大きいので MIN_NUM は縛っていない＝『lift 0.15 を割った』と『5社に届かなかった』の取り違えは起きない。",
        "by_vintage": reach,
    }

    # ── 1 ビンテージ符号 ────────────────────────────────────────────
    grp_t = {v: {r["ticker"] for r in cells[v]["_rows"]} for v in VINT}
    win_t = {v: {r["ticker"] for r in cells[v]["_rows"] if r["win"]} for v in VINT}
    def jac(a, b):
        return r4(len(a & b) / len(a | b)) if (a | b) else None
    dep = panel["diagnostics"]["outcome_dependence"]["pairs"]
    ov = panel["diagnostics"]["vintage_overlap"]
    O["test1_vintage_sign"] = {
        "verdict": "通過" if core["sign_stable"] and core["pass_core"] else "不合格",
        "by_vintage": {v: {k: cells[v][k] for k in
                           ("n_pop", "p_base", "n_group", "numerator", "p_group", "p_group_ci95",
                            "lift", "lift_vs_measurable_both", "n_measurable_both", "fisher_p_vs_rest_of_pop")}
                       for v in VINT},
        "maintained_lift": core["maintained_lift"],
        "maintained_lift_measurable_base": r4(min(cells[v]["lift_vs_measurable_both"] for v in VINT)),
        "sign_stable": core["sign_stable"],
        "is_three_vintages_three_evidences": {
            "answer": "いいえ。ほぼ1つの証拠。",
            "ticker_universe_overlap_2016_2018": ov["2016-2018"],
            "group_ticker_jaccard": {"2016-2017": jac(grp_t[2016], grp_t[2017]),
                                     "2017-2018": jac(grp_t[2017], grp_t[2018]),
                                     "2016-2018": jac(grp_t[2016], grp_t[2018])},
            "group_winner_jaccard": {"2016-2017": jac(win_t[2016], win_t[2017]),
                                     "2017-2018": jac(win_t[2017], win_t[2018]),
                                     "2016-2018": jac(win_t[2016], win_t[2018])},
            "outcome_spearman_2016_2018": dep["2016-2018"]["spearman_tr_cagr"],
            "outcome_win_jaccard_2016_2018": dep["2016-2018"]["win"]["jaccard"],
            "window_nesting": "窓はすべて2026-08終わり。2018窓(8.09年)は2016窓(10.09年)の末尾そのもの。",
            "how_to_read": "『3ビンテージで符号一致』は独立な3証拠ではない。この候補では群の顔ぶれも勝者も大半が同じ社。",
        },
        "vintages_2013_2015": {
            "status": "判定不能（不合格ではない）",
            "why": "f2_rnd_r / f2_sga_r は retro_features2 由来で 2013/2015 のパネル行に構造的に存在しない",
            "coverage": {str(y): panel["diagnostics"]["coverage"][str(y)]["feature_coverage_over_has_outcome"]["f2_rnd_r"]["p"]
                         for y in (2013, 2015)},
            "consequence": "prereg の out_of_sample『可能なら2013/2015でも符号一致』は当てられない＝"
                           "**この候補には真の外部検証が一つも無い**。判定不能を合格の材料にしない。",
        },
    }

    # ── 2 業種調整 ─────────────────────────────────────────────────
    def sector_block(v):
        c = cells[v]
        pop = c["_pop"]
        gset = {id(r) for r in c["_rows"]}
        by = defaultdict(lambda: {"g": [], "o": []})
        for r in pop:
            (by[r["sic2"] or "??"]["g" if id(r) in gset else "o"]).append(r)
        num = den = 0.0
        used, dropped, covered = [], [], 0
        for s, d in sorted(by.items()):
            n1, n0 = len(d["g"]), len(d["o"])
            if n1 == 0 or n0 == 0:
                dropped.append({"sic2": s, "n_group": n1, "n_other": n0})
                continue
            k1 = sum(1 for r in d["g"] if r["win"]); k0 = sum(1 for r in d["o"] if r["win"])
            w = n1 * n0 / (n1 + n0)
            num += w * (k1 / n1 - k0 / n0); den += w
            covered += n1
            used.append({"sic2": s, "n_group": n1, "n_other": n0,
                         "p_group": r4(k1 / n1), "p_other": r4(k0 / n0), "diff": r4(k1 / n1 - k0 / n0),
                         "weight": r4(w)})
        mh = (num / den) if den else None
        # 間接標準化: 層を落とさない。群の期待勝者数を層別の全体率で作る
        exp = 0.0
        for s, d in by.items():
            n1, n0 = len(d["g"]), len(d["o"])
            k1 = sum(1 for r in d["g"] if r["win"]); k0 = sum(1 for r in d["o"] if r["win"])
            p_all = (k1 + k0) / (n1 + n0)
            exp += n1 * p_all
        obs = c["numerator"]
        return {
            "mh_risk_diff": r4(mh),
            "strata_used": len(used), "strata_dropped": len(dropped),
            "group_covered_by_used_strata": covered, "group_total": c["n_group"],
            "group_coverage_share": r4(covered / c["n_group"]) if c["n_group"] else None,
            "strata_detail_used": sorted(used, key=lambda x: -x["n_group"]),
            "indirect_standardized": {
                "observed_winners": obs, "expected_winners_at_sector_rates": r4(exp),
                "diff_per_member": r4((obs - exp) / c["n_group"]) if c["n_group"] else None,
                "note": "層を1つも落とさない業種調整。MHが群の一部しか覆えないときの補助。",
            },
        }

    sect = {v: sector_block(v) for v in VINT}

    # 業種を1つずつ抜く（母集団ごと抜いて閾値から作り直す）
    loso = {}
    for v in VINT:
        c = cells[v]
        cnt = Counter(r["sic2"] for r in c["_rows"])
        res = []
        for s, n in cnt.most_common():
            sub = [r for r in pops[v] if r["sic2"] != s]
            cc = build_cell(sub)
            res.append({"dropped_sic2": s, "n_group_dropped": n,
                        "lift_after": cc["lift"] if cc else None,
                        "n_group_after": cc["n_group"] if cc else None,
                        "numerator_after": cc["numerator"] if cc else None,
                        "passes_line": bool(cc and cc["lift"] is not None
                                            and cc["lift"] >= LIFT_LINE and cc["numerator"] >= MIN_NUM)})
        loso[v] = res

    # 支配業種そのものの lift（＝この群は業種の代理か）
    dominant = {}
    for v in VINT:
        c = cells[v]
        cnt = Counter(r["sic2"] for r in c["_rows"])
        s, ng = cnt.most_common(1)[0]
        pop = c["_pop"]
        sec = [r for r in pop if r["sic2"] == s]
        n_s, k_s, p_s = rate(sec)
        gin = [r for r in c["_rows"] if r["sic2"] == s]
        n_i, k_i, p_i = rate(gin)
        dominant[v] = {
            "sic2": s, "n_sector_in_pop": n_s, "p_sector": r4(p_s),
            "lift_of_sector_alone": r4(p_s - c["p_base"]),
            "n_group_in_sector": n_i, "p_group_in_sector": r4(p_i),
            "lift_of_pair_within_that_sector": r4(p_i - p_s) if n_i else None,
            "share_of_group_in_that_sector": r4(n_i / c["n_group"]),
        }

    # 層内置換（業種内で win を並べ替え）
    def sector_perm_p(v, nperm=NPERM):
        c = cells[v]
        pop = c["_pop"]
        gset = {id(r) for r in c["_rows"]}
        by = defaultdict(list)
        for r in pop:
            by[r["sic2"] or "??"].append((id(r) in gset, r["win"]))
        obs = c["p_group"] - c["p_base"]
        ge = 0
        rng = random.Random(SEED + v)
        strata = [(list(x[0] for x in d), [x[1] for x in d]) for d in by.values()]
        n_g = c["n_group"]; n_p = c["n_pop"]
        for _ in range(nperm):
            kg = kp = 0
            for gflags, wins in strata:
                w = wins[:]; rng.shuffle(w)
                for isg, ww in zip(gflags, w):
                    if ww:
                        kp += 1
                        if isg:
                            kg += 1
            if (kg / n_g - kp / n_p) >= obs - 1e-12:
                ge += 1
        return round((ge + 1) / (nperm + 1), 4)

    O["test2_sector"] = {
        "verdict": None,
        "mantel_haenszel": {v: {k: sect[v][k] for k in
                                ("mh_risk_diff", "strata_used", "strata_dropped",
                                 "group_covered_by_used_strata", "group_total", "group_coverage_share")}
                            for v in VINT},
        "mh_caveat": "MH は群 or 対照が空の層を落とす。落とした層のぶん『調整した』の意味が薄れるので"
                     "群の被覆率を必ず併記する。",
        "indirect_standardization_no_strata_dropped": {v: sect[v]["indirect_standardized"] for v in VINT},
        "dominant_sector_benchmark": dominant,
        "leave_one_sector_out": loso,
        "within_sector_permutation_p": {v: sector_perm_p(v) for v in VINT},
        "strata_detail_2018": sect[2018]["strata_detail_used"],
    }

    # 業種そのものを規則にした場合（＝この候補は業種の代理か）: 事前登録の外・診断専用
    RND_SIC = {"28", "35", "36", "37", "38"}
    sec_rule = {}
    for v in VINT:
        pop = pops[v]
        g = [r for r in pop if (r["sic2"] or "") in RND_SIC]
        n, k, p = rate(g)
        nb, kb, pb = rate(pop)
        sec_rule[v] = {"n_group": n, "numerator": k, "p_group": r4(p), "lift": r4(p - pb)}
    O["diag_sector_only_rule"] = {
        "status": "事前登録の外・診断専用（合否には数えない）",
        "rule": "sic2 ∈ {28 化学, 35 産業機械, 36 電子, 37 輸送機器, 38 計測} ＝『R&Dを持つ製造業』",
        "by_vintage": sec_rule,
        "why": "候補の群が『R&Dが中央値超 ∧ 販管費が中央値以下』＝実質この業種束なら、"
               "業種を直接書いた規則と同じかそれ以上の lift が、より大きな n で出るはず。",
    }

    # ── 3 irr の影 ─────────────────────────────────────────────────
    irr_block = {}
    for v in VINT:
        c = cells[v]
        pop_irr = [r for r in c["_pop"] if r["irr"] is not None]
        g_irr = [r for r in c["_rows"] if r["irr"] is not None]
        if not pop_irr:
            irr_block[v] = {"status": "判定不能（このビンテージに irr の読解が無い）",
                            "n_with_irr": 0}
            continue
        # 相関（群フラグ × irr）
        gset = {id(r) for r in c["_rows"]}
        xs = [1.0 if id(r) in gset else 0.0 for r in pop_irr]
        ys = [float(r["irr"]) for r in pop_irr]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        corr = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)) if sx and sy else None
        out = {"n_pop_with_irr": len(pop_irr), "share_of_pop_with_irr": r4(len(pop_irr) / c["n_pop"]),
               "n_group_with_irr": len(g_irr), "share_of_group_with_irr": r4(len(g_irr) / c["n_group"]),
               "corr_group_vs_irr": r4(corr),
               "group_irr_distribution": dict(Counter(r["irr"] for r in g_irr)),
               "pop_irr_distribution": dict(Counter(r["irr"] for r in pop_irr))}
        for lab, pred in (("irr>=70", lambda x: x >= 70), ("irr<70", lambda x: x < 70)):
            sub = [r for r in pop_irr if pred(r["irr"])]
            gsub = [r for r in g_irr if pred(r["irr"])]
            nb, kb, pb = rate(sub); ng, kg, pg = rate(gsub)
            out[lab] = {"n_pop": nb, "base": r4(pb), "n_group": ng, "numerator": kg,
                        "p_group": r4(pg), "p_group_ci95": wilson(kg, ng),
                        "lift": r4(pg - pb) if ng else None,
                        "reaches_min_numerator": kg >= MIN_NUM,
                        "fisher_p": fisher_p(kg, ng - kg, kb - kg, (nb - ng) - (kb - kg)) if ng else None}
        # irr=85 を母集団ごと抜いて作り直す
        sub_rows = [r for r in pops[v] if r["irr"] != 85]
        cc = build_cell(sub_rows)
        out["drop_irr85_from_population"] = {
            "n_pop": cc["n_pop"], "n_group": cc["n_group"], "numerator": cc["numerator"],
            "lift": cc["lift"], "passes_line": bool(cc["lift"] >= LIFT_LINE and cc["numerator"] >= MIN_NUM)}
        # 群の勝者のうち irr=85 は何社か
        w85 = [r["ticker"] for r in c["_rows"] if r["win"] and r["irr"] == 85]
        out["group_winners_with_irr85"] = {"n": len(w85), "tickers": sorted(w85),
                                           "share_of_group_winners": r4(len(w85) / c["numerator"]) if c["numerator"] else None}
        irr_block[v] = out
    O["test3_irr_shadow"] = {
        "verdict": None,
        "by_vintage": irr_block,
        "caveat": "irr の読解は 2016/2017 のパネル行に無い（2018/2013/2015 のみ）。"
                  "2018 でも読解済みは母集団の一部＝**この検定は母集団の3-4割でしか当てられない**。"
                  "しかも読解対象は『質実証×価格実証』寄りに選ばれた集合なので、無作為抽出ではない。",
    }

    # ── 4 1社の影響 ────────────────────────────────────────────────
    tickers = sorted({r["ticker"] for v in VINT for r in cells[v]["_rows"]})
    loo = []
    for t in tickers:
        cs = []
        for v in VINT:
            cs.append(build_cell([r for r in pops[v] if r["ticker"] != t]))
        vd = verdict_of(cs)
        loo.append({"ticker": t, "maintained_lift": vd.get("maintained_lift"),
                    "min_numerator": vd.get("min_numerator"), "pass_core": vd.get("pass_core"),
                    "lifts": [c["lift"] for c in cs]})
    loo_sorted = sorted(loo, key=lambda x: (x["maintained_lift"] if x["maintained_lift"] is not None else 9))
    O["test4_leave_one_ticker_out"] = {
        "verdict": None,
        "method": "群に一度でも入った社を、**パネルから丸ごと**（3ビンテージとも）抜いて閾値・母集団・群・判定を作り直す",
        "n_tickers_tested": len(tickers),
        "maintained_lift_min": loo_sorted[0]["maintained_lift"] if loo_sorted else None,
        "maintained_lift_max": loo_sorted[-1]["maintained_lift"] if loo_sorted else None,
        "n_that_break_the_line": sum(1 for x in loo if not x["pass_core"]),
        "worst10": loo_sorted[:10],
        "note": "1社で消えるなら不合格。ここは『消えないこと』を確かめる検定であって、合格の証拠ではない。",
    }

    # ── 5 置換（単体 + 族） ────────────────────────────────────────
    # 5-a 探索空間（P_quality の1420組）を自前で組み直し、マスク化する
    all_pairs = [p for p in search["all_pairs"] if p["population"] == POP]
    masks = {}      # v -> {(var,cut): int bitmask}
    idx = {}        # v -> {ticker: bit}
    poplist = {}
    for v in VINT:
        pop = pops[v]
        poplist[v] = pop
        idx[v] = {r["ticker"]: i for i, r in enumerate(pop)}
        m = {}
        need = {(p["var_a"], p["cut_a"]) for p in all_pairs} | {(p["var_b"], p["cut_b"]) for p in all_pairs}
        for (var, cut) in need:
            thr, op, pred = cut_mask([r[var] for r in pop], cut)
            if pred is None:
                m[(var, cut)] = 0
                continue
            bits = 0
            for i, r in enumerate(pop):
                val = r[var]
                if val is not None and pred(val):
                    bits |= (1 << i)
            m[(var, cut)] = bits
        masks[v] = m
    pair_masks = []
    for p in all_pairs:
        gm = {v: masks[v][(p["var_a"], p["cut_a"])] & masks[v][(p["var_b"], p["cut_b"])] for v in VINT}
        pair_masks.append((p["label"], gm, {v: bin(gm[v]).count("1") for v in VINT}))
    my_i = next((i for i, (lab, _, _) in enumerate(pair_masks) if lab == LABEL), None)

    # 帰無: outcome の束をティッカーごと置換（ビンテージ間相関・欠測構造を保つ）
    universe = sorted({r["ticker"] for v in VINT for r in pops[v]})
    winmap = {v: {r["ticker"]: bool(r["win"]) for r in pops[v]} for v in VINT}

    def eval_all(winmask):
        """(単体のlift, 族で合格が1つでも出たか) を返す"""
        pops_k = {v: bin(winmask[v]).count("1") for v in VINT}
        base = {v: pops_k[v] / len(poplist[v]) for v in VINT}
        single = None
        any_pass = False
        for i, (lab, gm, ng) in enumerate(pair_masks):
            lifts, nums, ok = [], [], True
            for v in VINT:
                n = ng[v]
                if n == 0:
                    ok = False; break
                k = bin(gm[v] & winmask[v]).count("1")
                lifts.append(k / n - base[v]); nums.append(k)
            if i == my_i and ok:
                single = min(lifts)
            if not ok or any_pass:
                continue
            signs = {1 if l > 0 else (-1 if l < 0 else 0) for l in lifts}
            if len(signs) == 1 and 0 not in signs and min(abs(l) for l in lifts) >= LIFT_LINE and min(nums) >= MIN_NUM:
                any_pass = True
        return single, any_pass

    # 家族をもう一方の母集団（P_full・勝者側）へも広げる。探索は両方を回している。
    panel_rows_all = json.load(open(PANEL, encoding="utf-8"))["rows"]
    pops_full = {v: [r for r in panel_rows_all
                     if r["vintage"] == v and r["P_full"] and r["has_outcome"] and r["window_full"]]
                 for v in VINT}
    all_pairs_full = [p for p in search["all_pairs"] if p["population"] == "P_full"]
    pair_masks_full, idxf, poplist_full = [], {}, {}
    masks_full = {}
    for v in VINT:
        pop = pops_full[v]; poplist_full[v] = pop
        need = {(p["var_a"], p["cut_a"]) for p in all_pairs_full} | {(p["var_b"], p["cut_b"]) for p in all_pairs_full}
        m = {}
        for (var, cut) in need:
            thr, op, pred = cut_mask([r[var] for r in pop], cut)
            bits = 0
            if pred is not None:
                for i, r in enumerate(pop):
                    val = r[var]
                    if val is not None and pred(val):
                        bits |= (1 << i)
            m[(var, cut)] = bits
        masks_full[v] = m
    for p in all_pairs_full:
        gm = {v: masks_full[v][(p["var_a"], p["cut_a"])] & masks_full[v][(p["var_b"], p["cut_b"])] for v in VINT}
        pair_masks_full.append((p["label"], gm, {v: bin(gm[v]).count("1") for v in VINT}))

    def eval_family(pairs, popl, winmask):
        """族の (max maintained lift, 合格が1つでも出たか) を返す。"""
        base = {v: bin(winmask[v]).count("1") / len(popl[v]) for v in VINT}
        best = -9.0; any_pass = False
        for lab, gm, ng in pairs:
            lifts, nums, ok = [], [], True
            for v in VINT:
                n = ng[v]
                if n == 0:
                    ok = False; break
                k = bin(gm[v] & winmask[v]).count("1")
                lifts.append(k / n - base[v]); nums.append(k)
            if not ok:
                continue
            signs = {1 if l > 0 else (-1 if l < 0 else 0) for l in lifts}
            if len(signs) == 1 and 0 not in signs:
                m = min(abs(l) for l in lifts)
                if min(nums) >= MIN_NUM:
                    if m > best:
                        best = m
                    if m >= LIFT_LINE:
                        any_pass = True
        return best, any_pass

    obs_single = core["maintained_lift"]
    # 自己検算: 置換に使うビットマスクの経路が、行を数える経路と同じ答えを出すか
    # （同じものを見る二つの経路が違うことを言ってはいけない・v9.9.65 のミニチュア）
    true_wm = {}
    for v in VINT:
        bits = 0
        for i, r in enumerate(poplist[v]):
            if r["win"]:
                bits |= (1 << i)
        true_wm[v] = bits
    bitmask_single, _ = eval_all(true_wm)
    # 行経路の**丸めていない**値と比べる（丸めた値と比べると常に食い違って見える＝偽の警報）
    exact_row = min(abs(c["numerator"] / c["n_group"] - c["k_pop"] / c["n_pop"])
                    for c in (cells[v] for v in VINT))
    selfcheck = {
        "row_path_maintained_lift": r4(exact_row),
        "bitmask_path_maintained_lift": r4(bitmask_single),
        "abs_diff": (abs((bitmask_single if bitmask_single is not None else -9) - exact_row)),
        "agree": abs((bitmask_single if bitmask_single is not None else -9) - exact_row) < 1e-12,
        "why": "置換の結論はビットマスク経路の正しさに全部乗っている。先に検算する。"
               "⚠ 比べるのは丸める前の値。丸めた値と比べると必ず食い違って見える（初版で踏んだ）。",
    }

    universe_full = sorted({r["ticker"] for v in VINT for r in pops_full[v]})
    winmap_full = {v: {r["ticker"]: bool(r["win"]) for r in pops_full[v]} for v in VINT}

    rng = random.Random(SEED)
    ge_single = 0; fam_pass = 0; fam_max = []
    t_perm = time.time()
    for _ in range(NPERM):
        # P_quality の帰無（母集団内でティッカー束を置換＝基準率を保つ）
        perm = universe[:]; rng.shuffle(perm)
        mp = dict(zip(universe, perm))
        wm = {}
        for v in VINT:
            bits = 0; wmv = winmap[v]
            for i, r in enumerate(poplist[v]):
                if wmv.get(mp[r["ticker"]], False):
                    bits |= (1 << i)
            wm[v] = bits
        s, _ = eval_all(wm)
        if s is not None and s >= obs_single - 1e-12:
            ge_single += 1
        bq, apq = eval_family(pair_masks, poplist, wm)
        # P_full 側も同じ置換の思想で（母集団が違うので universe も別）
        permf = universe_full[:]; rng.shuffle(permf)
        mpf = dict(zip(universe_full, permf))
        wmf = {}
        for v in VINT:
            bits = 0; wmv = winmap_full[v]
            for i, r in enumerate(poplist_full[v]):
                if wmv.get(mpf[r["ticker"]], False):
                    bits |= (1 << i)
            wmf[v] = bits
        bf, apf = eval_family(pair_masks_full, poplist_full, wmf)
        fam_max.append(max(bq, bf))
        if apq or apf:
            fam_pass += 1
    perm_sec = round(time.time() - t_perm, 1)
    fam_max_sorted = sorted(fam_max)
    ge_max = sum(1 for x in fam_max if x >= obs_single - 1e-12)

    O["test5_permutation"] = {
        "verdict": None,
        "null": "特徴量側（母集団・可測・閾値・群）を固定し、outcome をティッカー単位で置換する。"
                "ビンテージ間の outcome 相関と欠測構造を保ったまま特徴量↔outcome だけを壊す。"
                "置換は母集団の中で行うので基準率は保たれる。",
        "n_permutations": NPERM,
        "selfcheck_two_code_paths": selfcheck,
        "single_candidate": {"observed_maintained_lift": obs_single,
                             "n_ge_observed": ge_single,
                             "p": round((ge_single + 1) / (NPERM + 1), 4),
                             "note": "この候補『だけ』を最初から狙っていたなら、この p が答え。"
                                     "だが実際は1420組を眺めた後に選ばれている。"},
        "family_wise": {
            "family": f"勝者側の探索空間 {len(all_pairs) + len(all_pairs_full)} 組"
                      f"（P_quality {len(all_pairs)} ＋ P_full {len(all_pairs_full)}）",
            "n_perm_with_at_least_one_pass": fam_pass,
            "p_family_any_pass": round(fam_pass / NPERM, 4),
            "max_maintained_lift_under_null": {
                "p50": r4(fam_max_sorted[NPERM // 2]),
                "p90": r4(fam_max_sorted[int(NPERM * 0.90)]),
                "p95": r4(fam_max_sorted[int(NPERM * 0.95)]),
                "p99": r4(fam_max_sorted[int(NPERM * 0.99)]),
                "max": r4(fam_max_sorted[-1]),
            },
            "p_familywise_for_this_candidate": round((ge_max + 1) / (NPERM + 1), 4),
            "how_to_read": "『族の最大 maintained lift が、この候補の観測値以上になる確率』＝"
                           "選択を織り込んだ p。単体の p はこれより必ず小さく出る。"
                           "⚠ 破壊側の探索（hist_wd_dst_pair）と単変量168検定は家族に入っていないので、"
                           "本当の値札はこれより高い。",
        },
        "runtime_sec": perm_sec,
    }

    # ── 6 既存の関門との重複 ──────────────────────────────────────
    def gate_flags(r):
        shrink = (r["f2_cagr5"] is not None and r["f2_opmD5"] is not None
                  and r["f2_cagr5"] < 0 and r["f2_opmD5"] < 0)
        ic = r["f2_intcov"]
        return shrink, ic

    gates = {}
    for v in VINT:
        c = cells[v]
        pop = c["_pop"]; grp = c["_rows"]
        n_sh = sum(1 for r in pop if gate_flags(r)[0])
        n_sh_g = sum(1 for r in grp if gate_flags(r)[0])
        blocks = {}
        for lab, keep in (
            ("収縮を除く", lambda r: not gate_flags(r)[0]),
            ("収縮を除く ∧ intcov>=3", lambda r: (not gate_flags(r)[0]) and (r["f2_intcov"] is not None and r["f2_intcov"] >= 3)),
            ("収縮を除く ∧ intcov>=5", lambda r: (not gate_flags(r)[0]) and (r["f2_intcov"] is not None and r["f2_intcov"] >= 5)),
        ):
            sub = [r for r in pops[v] if keep(r)]
            cc = build_cell(sub)
            blocks[lab] = {"n_pop": cc["n_pop"], "base": cc["p_base"], "n_group": cc["n_group"],
                           "numerator": cc["numerator"], "p_group": cc["p_group"], "lift": cc["lift"],
                           "passes_line": bool(cc["lift"] is not None and cc["lift"] >= LIFT_LINE
                                               and cc["numerator"] >= MIN_NUM)}
        gates[v] = {"n_pop": c["n_pop"], "n_shrink_in_pop": n_sh, "n_shrink_in_group": n_sh_g,
                    "survivors": blocks}
    # 単脚との増分
    legs = {}
    for v in VINT:
        pop = pops[v]
        out = {}
        for var, cut in ((VAR_A, CUT_A), (VAR_B, CUT_B)):
            thr, op, pred = cut_mask([r[var] for r in pop], cut)
            g = [r for r in pop if r[var] is not None and pred(r[var])]
            n, k, p = rate(g); nb, kb, pb = rate(pop)
            out[f"{var}[{cut}]"] = {"n_group": n, "numerator": k, "p_group": r4(p), "lift": r4(p - pb)}
        out["pair"] = {"n_group": cells[v]["n_group"], "numerator": cells[v]["numerator"],
                       "lift": cells[v]["lift"]}
        best_leg = max(out[k]["lift"] for k in out if k != "pair")
        out["increment_vs_best_leg"] = r4(cells[v]["lift"] - best_leg)
        legs[v] = out
    O["test6_overlap_with_existing_gates"] = {
        "verdict": None,
        "note": "母集団が既に P_quality（質実証）なので、質実証の増分はここでは測れない＝定義上ゼロ。"
                "残る2本（事業の収縮 / 利払カバー）で当てる。**intcov は財務キル(nde>4)の歴史側の代理**であって同一ではない。",
        "by_vintage": gates,
        "increment_over_single_legs": legs,
    }

    # ── 診断（事前登録の外） ──────────────────────────────────────
    meas = {}
    for v in VINT:
        pop = pops[v]
        a = [r for r in pop if r[VAR_B] is not None]
        b = [r for r in pop if r[VAR_B] is None]
        na, ka, pa_ = rate(a); nb, kb, pb_ = rate(b)
        meas[v] = {"sga_measurable": {"n": na, "k": ka, "p": r4(pa_)},
                   "sga_missing": {"n": nb, "k": kb, "p": r4(pb_)},
                   "diff": r4(pa_ - pb_) if (na and nb) else None}
    O["diag_measurability_confound"] = {
        "status": "事前登録の外・診断専用",
        "why": "f2_sga_r は母集団の6割弱しか可測。『販管費を単独で開示しているか』自体が勝者を予言していると、"
               "群の lift はその写しになる。",
        "by_vintage": meas,
    }

    # 破壊側・分布・ハードル感度（同じ群を別の物差しで見る）
    def quart(xs):
        xs = sorted(xs)
        if not xs:
            return None
        def q(p):
            return xs[min(len(xs) - 1, max(0, math.ceil(p * len(xs)) - 1))]
        return {"p10": r4(q(.10)), "p25": r4(q(.25)), "median": r4(q(.50)),
                "p75": r4(q(.75)), "p90": r4(q(.90)), "mean": r4(sum(xs) / len(xs))}

    shape = {}
    for v in VINT:
        c = cells[v]
        g = c["_rows"]; pop = c["_pop"]
        ng, kd, pd_ = rate(g, "destroy"); nb, kdb, pdb = rate(pop, "destroy")
        shape[v] = {
            "destroy": {"n_group": ng, "numerator": kd, "p_group": r4(pd_),
                        "p_base": r4(pdb), "lift": r4(pd_ - pdb)},
            "tr_cagr_group": quart([r["tr_cagr"] for r in g if r["tr_cagr"] is not None]),
            "tr_cagr_pop": quart([r["tr_cagr"] for r in pop if r["tr_cagr"] is not None]),
            "mdd_group_median": r4(sorted(r["mdd"] for r in g if r["mdd"] is not None)[len(g) // 2]) if g else None,
            "mdd_pop_median": r4(sorted(r["mdd"] for r in pop if r["mdd"] is not None)[len(pop) // 2]) if pop else None,
            "hurdle_sensitivity": {
                f"{int(h*100)}%": {
                    "p_group": r4(sum(1 for r in g if (r["tr_cagr"] or -9) >= h) / len(g)),
                    "p_base": r4(sum(1 for r in pop if (r["tr_cagr"] or -9) >= h) / len(pop)),
                    "lift": r4(sum(1 for r in g if (r["tr_cagr"] or -9) >= h) / len(g)
                               - sum(1 for r in pop if (r["tr_cagr"] or -9) >= h) / len(pop)),
                } for h in (0.10, 0.12, 0.15, 0.18, 0.20, 0.25)
            },
        }
    O["diag_shape_and_hurdle"] = {
        "status": "事前登録の外・診断専用（ハードル15%だけが登録された線）",
        "why": "同じ群を『破壊側』『分布』『別のハードル』で見る。勝者率だけ上がって破壊率も上がるなら"
               "『質』ではなく『分散』を拾っているだけ。15%ちょうどでしか出ないなら線の上に載っているだけ。",
        "by_vintage": shape,
    }

    # 規模の交絡
    size = {}
    for v in VINT:
        c = cells[v]
        gs = sorted(r["size_rev"] for r in c["_rows"] if r["size_rev"])
        ps = sorted(r["size_rev"] for r in c["_pop"] if r["size_rev"])
        size[v] = {"group_median_rev": r4(gs[len(gs) // 2] / 1e6) if gs else None,
                   "pop_median_rev": r4(ps[len(ps) // 2] / 1e6) if ps else None,
                   "unit": "百万$"}
    O["diag_size"] = {"status": "事前登録の外・診断専用", "by_vintage": size,
                      "why": "2016-2026 は大型に有利な窓。群が大型に偏っているだけなら規模の写し。"}

    # 業種を2つ同時に抜く（登録は1つずつ。これは診断）
    two = {}
    for v in VINT:
        for combo in (("35", "38"), ("35", "38", "37"), ("36", "35", "38")):
            sub = [r for r in pops[v] if r["sic2"] not in combo]
            cc = build_cell(sub)
            two.setdefault("+".join(combo), {})[v] = {
                "n_pop": cc["n_pop"], "n_group": cc["n_group"], "numerator": cc["numerator"],
                "lift": cc["lift"],
                "passes_line": bool(cc["lift"] is not None and cc["lift"] >= LIFT_LINE and cc["numerator"] >= MIN_NUM)}
    O["diag_drop_two_sectors"] = {
        "status": "事前登録の外・診断専用（登録された検定は『1業種ずつ』）",
        "why": "2018の層別で効果が出ているのは SIC35(9社中7勝) と SIC38(6社中5勝) で、"
               "最大の2層 SIC36(14社)・SIC28(11社) では ±0。効果が2層に集まっていないかを見る。",
        "by_combo": two,
    }

    # レジーム分割（2018-07→2022-07 / 2022-07→2026-08）
    try:
        mon = json.load(open(os.path.join(OUT, "retro_monthly_2018_2026.json"), encoding="utf-8"))
    except Exception:
        mon = None
    if mon:
        SPLIT = 1656633600  # 2022-07-01
        def seg_cagr(t):
            s = mon.get(t)
            if not s or len(s) < 12:
                return None, None
            a = s[0]; z = s[-1]
            mid = min(s, key=lambda x: abs(x[0] - SPLIT))
            def cagr(p0, p1, yrs):
                if not p0 or not p1 or p0 <= 0 or p1 <= 0 or yrs <= 0:
                    return None
                return (p1 / p0) ** (1 / yrs) - 1
            y1 = (mid[0] - a[0]) / (365.25 * 86400)
            y2 = (z[0] - mid[0]) / (365.25 * 86400)
            return cagr(a[1], mid[1], y1), cagr(mid[1], z[1], y2)
        reg = {}
        c = cells[2018]
        for lab, rows_ in (("group", c["_rows"]), ("population", c["_pop"])):
            e = {"early": [], "late": []}
            for r in rows_:
                a, b = seg_cagr(r["ticker"])
                if a is not None:
                    e["early"].append(a)
                if b is not None:
                    e["late"].append(b)
            reg[lab] = {k: {"n": len(v_), "median": r4(sorted(v_)[len(v_) // 2]) if v_ else None,
                            "p_ge_15": r4(sum(1 for x in v_ if x >= 0.15) / len(v_)) if v_ else None}
                        for k, v_ in e.items()}
        reg["lift_by_regime"] = {
            k: r4(reg["group"][k]["p_ge_15"] - reg["population"][k]["p_ge_15"])
            for k in ("early", "late")
            if reg["group"][k]["p_ge_15"] is not None and reg["population"][k]["p_ge_15"] is not None}

        # レジーム × 業種調整（間接標準化・層を落とさない）
        gset18 = {id(r) for r in c["_rows"]}
        seg_cache = {r["ticker"]: seg_cagr(r["ticker"]) for r in c["_pop"]}
        reg_sect = {}
        for wi, wname in ((0, "early"), (1, "late")):
            by = defaultdict(lambda: {"g": [], "o": []})
            for r in c["_pop"]:
                val = seg_cache.get(r["ticker"], (None, None))[wi]
                if val is None:
                    continue
                by[r["sic2"] or "??"]["g" if id(r) in gset18 else "o"].append(val >= 0.15)
            obs = exp = ng_ = 0
            for s, dd in by.items():
                n1, n0 = len(dd["g"]), len(dd["o"])
                if n1 == 0:
                    continue
                k1 = sum(dd["g"]); k0 = sum(dd["o"])
                p_all = (k1 + k0) / (n1 + n0)
                obs += k1; exp += n1 * p_all; ng_ += n1
            reg_sect[wname] = {"n_group": ng_, "observed": obs, "expected_at_sector_rates": r4(exp),
                               "sector_adjusted_lift": r4((obs - exp) / ng_) if ng_ else None}
        reg["sector_adjusted_by_regime"] = reg_sect
        O["diag_regime_split_2018"] = {
            "status": "事前登録の外・診断専用",
            "windows": {"early": "2018-07 → 2022-07", "late": "2022-07 → 2026-08"},
            "why": "この台帳は『irr=85 の超過はほぼAI期に出た（前期 lift+0.13 / 後期 +0.38）』と記録している。"
                   "同じ形なら、この候補も窓の産物かもしれない。",
            "detail": reg,
            "prior_finding_same_variable_pair": {
                "file": "out/retro_regime_test.json（2026-08-05・別セッションの独立実測）",
                "note": "R&D単独は両レジームでリフト維持=頑健。in-sample最良複合(**販管費低∧R&D高**)は"
                        "前期リフトゼロ・後期のみP=0.70=**AI相場の産物と確定**",
                "their_numbers": {"early": {"base": 0.249, "combo_p": 0.259, "lift": 0.010},
                                  "late": {"base": 0.282, "combo_p": 0.704, "lift": 0.422}},
                "their_population": "demoQ 177社（価格実証×質実証プール）・切り方は上下1/4",
                "mine": "P_quality 339社・切り方は中央値。母集団も切り方も違うのに**同じ形**が出た",
                "consequence": "この候補は『新しい発見』ではなく、**既に潰されている結果の再発見**。"
                               "prereg の novelty_of_this_run は満たさない。",
            },
        }

    O["diag_group_2018"] = {
        "status": "事前登録の外・診断専用",
        "n": cells[2018]["n_group"], "numerator": cells[2018]["numerator"],
        "sic2_counts": dict(Counter(r["sic2"] for r in cells[2018]["_rows"]).most_common()),
        "winners": sorted(r["ticker"] for r in cells[2018]["_rows"] if r["win"]),
        "non_winners": sorted(r["ticker"] for r in cells[2018]["_rows"] if not r["win"]),
    }

    # ── 総合判定 ──────────────────────────────────────────────────
    def mk(v):
        return sect[v]["mh_risk_diff"], dominant[v]["lift_of_pair_within_that_sector"]
    sector_pass = all((sect[v]["mh_risk_diff"] is not None and sect[v]["mh_risk_diff"] >= LIFT_LINE)
                      for v in VINT)
    sector_pass_dominant = all((dominant[v]["lift_of_pair_within_that_sector"] is not None
                                and dominant[v]["lift_of_pair_within_that_sector"] >= LIFT_LINE) for v in VINT)
    irr_pass = None
    b = irr_block.get(2018, {})
    if isinstance(b, dict) and "irr>=70" in b:
        s = b["irr>=70"]
        irr_pass = bool(s["lift"] is not None and s["lift"] >= LIFT_LINE and s["reaches_min_numerator"])
    loo_pass = all(x["pass_core"] for x in loo)

    O["test2_sector"]["verdict"] = "通過" if sector_pass else "不合格"
    O["test2_sector"]["verdict_detail"] = {
        "mh_pass": sector_pass,
        "dominant_sector_internal_pass": sector_pass_dominant,
        "reason": "MH は層を落として計算されている一方、支配業種(SIC36)の内側では lift がほぼゼロ。"
                  "二つが食い違うときは『どの社が調整の対象から外れたか』を見る。",
    }
    O["test3_irr_shadow"]["verdict"] = ("通過" if irr_pass else ("不合格" if irr_pass is False else "判定不能"))
    O["test4_leave_one_ticker_out"]["verdict"] = "通過" if loo_pass else "不合格"
    O["test5_permutation"]["verdict"] = "通過" if (ge_single + 1) / (NPERM + 1) < 0.05 else "不合格"
    inc_pass = all(gates[v]["survivors"]["収縮を除く ∧ intcov>=3"]["passes_line"] for v in VINT)
    O["test6_overlap_with_existing_gates"]["verdict"] = "通過" if inc_pass else "不合格"

    checks = {
        "1_vintage_sign": O["test1_vintage_sign"]["verdict"],
        "2_sector": O["test2_sector"]["verdict"],
        "3_irr": O["test3_irr_shadow"]["verdict"],
        "4_one_ticker": O["test4_leave_one_ticker_out"]["verdict"],
        "5_permutation": O["test5_permutation"]["verdict"],
        "6_increment": O["test6_overlap_with_existing_gates"]["verdict"],
    }
    fw = O["test5_permutation"]["family_wise"]
    reg = (O.get("diag_regime_split_2018") or {}).get("detail", {}).get("lift_by_regime", {})
    O["verdict"] = {
        "checks": checks,
        "registered_six": "不合格" if any(v == "不合格" for v in checks.values()) else
                          ("判定不能" if any(v == "判定不能" for v in checks.values()) else "落とせなかった"),
        "rule": "6つのうち1つでも落ちたら不合格。『落とせなかった』は『正しい』ではない。",
        "but_three_things_the_six_gates_do_not_see": {
            "A_selection": {
                "what": "登録の置換は『この候補だけ』の p（0.0005）。だが候補は1420組を眺めた後で選ばれている。",
                "family_max_p95_under_null": fw["max_maintained_lift_under_null"]["p95"],
                "observed_maintained_lift": O["test1_vintage_sign"]["maintained_lift"],
                "p_familywise": fw["p_familywise_for_this_candidate"],
                "reading": "観測値は帰無の族最大の95%点とほぼ同じ位置。**選択を織り込むと線上**。"
                           "しかも家族は勝者側2840組だけで、破壊側の探索と単変量168検定を数えていない＝"
                           "本当の値札はこれより高い。",
            },
            "B_regime": {
                "lift_early_2018_2022": reg.get("early"),
                "lift_late_2022_2026": reg.get("late"),
                "reading": "効果はほぼ全部がAI期。**同じ変数の組が2026-08-05に別セッションで既に"
                           "『AI相場の産物と確定』と記録されている**（out/retro_regime_test.json）。",
            },
            "C_no_true_out_of_sample": {
                "reading": "2016/2017/2018 はティッカー宇宙が同一（jaccard 1.0）・outcome の Spearman 0.92-0.96・"
                           "窓は入れ子。f2_ が無い 2013/2015 は判定不能。"
                           "＝**この候補には外部標本が一つも無い**。",
            },
        },
        "final": "登録6条件では落とせなかった。ただし (A)選択調整後 p=0.053 で線上 "
                 "(B)効果はほぼ全部AI期で、同じ変数の組は既に『AI相場の産物』と確定済み "
                 "(C)外部標本ゼロ ——よって **prereg の novelty（新しい発見）は満たさない**。"
                 "規約に足す材料ではない。",
    }
    O["runtime_sec"] = round(time.time() - t0, 1)

    def strip(o):
        if isinstance(o, dict):
            return {str(k): strip(v) for k, v in o.items()
                    if not (isinstance(k, str) and k.startswith("_"))}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o

    json.dump(strip(O), open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(strip(O["verdict"]), ensure_ascii=False, indent=1))
    print("wrote", DST, O["runtime_sec"], "sec")


if __name__ == "__main__":
    main()
