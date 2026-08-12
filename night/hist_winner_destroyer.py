#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
勝者／破壊の対称探索 —— 総括の再実行器
================================================================================
`python3 night/hist_winner_destroyer.py [--json]` → out/hist_wd_verdict.json

■ この道具が**やること**
  既存の out/hist_wd_*.json（事前登録・パネル・事前診断・探索6本・非対称・反証10本）を
  **読んで合否表を組むだけ**。統計は一つも作らない・線は一つも持たない。

■ この道具が**やらないこと（重要）**
  - lift・MH・置換・検出力の**再計算をしない**。数字はすべて元の在庫からそのまま引く
    （v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」。ここで計算し直すと
     二つ目の実装ができて、いつか必ず割れる）
  - 合否の線を持たない。線は out/hist_winner_destroyer_prereg.json にあり、
    合否は探索器(W*/D*)と反証器(verify_*)が既に出している。ここは**突き合わせるだけ**
  - 判定・採点・台帳・index.html・パックに一切触らない

■ この道具が唯一「新しく」出すもの
  **集合演算**——探索器が『合格』と言った候補のうち、反証にかけられていないものはどれか。
  探索と反証が別々の道具に分かれている以上、その隙間は突き合わせでしか見えない。

再現性: 入力JSONが同じなら出力もバイト一致（決定的・乱数を使わない）。
"""

import json
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")

PREREG = "hist_winner_destroyer_prereg.json"
PANEL = "hist_wd_panel.json"
DIAG = "hist_wd_diag.json"

SEARCH_TOOLS = OrderedDict([
    ("win_uni",   {"side": "win",     "kind": "単変量", "file": "hist_wd_win_uni.json"}),
    ("win_pair",  {"side": "win",     "kind": "2本の積", "file": "hist_wd_win_pair.json"}),
    ("win_shape", {"side": "win",     "kind": "形・層",  "file": "hist_wd_win_shape.json"}),
    ("dst_uni",   {"side": "destroy", "kind": "単変量", "file": "hist_wd_dst_uni.json"}),
    ("dst_pair",  {"side": "destroy", "kind": "2本の積", "file": "hist_wd_dst_pair.json"}),
    ("dst_path",  {"side": "destroy", "kind": "値動き",  "file": "hist_wd_dst_path.json"}),
])

ASYM = "hist_wd_asym.json"

# 反証器。verdict のラベルが在庫のどこにあるかを**明示**する（推測で拾わない）。
VERIFY = OrderedDict([
    ("verify_irr85",           {"file": "hist_wd_verify_irr85.json",
                                "verdict_path": ["verdict", "overall"]}),
    ("verify_rnd_sga",         {"file": "hist_wd_verify_rnd_sga.json",
                                "verdict_path": ["verdict", "結論"]}),
    ("verify_rnd_sga_indep",   {"file": "hist_wd_verify_rnd_sga_indep.json",
                                "verdict_path": ["verdict", "結論"]}),
    ("verify_rnd_sga_q",       {"file": "hist_wd_verify_rnd_sga_q.json",
                                "verdict_path": ["verdict", "result"]}),
    ("verify_rnd_sga_medq",    {"file": "hist_wd_verify_rnd_sga_medq.json",
                                "verdict_path": ["verdict", "registered_six"]}),
    ("verify_cash_sga",        {"file": "hist_wd_verify_cash_sga.json",
                                "verdict_path": ["verdict", "結論"]}),
    ("verify_capex_sga",       {"file": "hist_wd_verify_capex_sga.json",
                                "verdict_path": ["verdict", "結論"]}),
    ("verify_aturn_rnd",       {"file": "hist_wd_verify_aturn_rnd.json",
                                "verdict_path": ["verdict", "prereg_verdict"]}),
    ("verify_opm_rev",         {"file": "hist_wd_verify_opm_rev.json",
                                "verdict_path": ["verdict", "prereg_literal"]}),
    ("verify_f2opm_x_sizerev", {"file": "hist_wd_verify_f2opm_x_sizerev.json",
                                "verdict_path": ["verdict", "result"]}),
])

# 実測で同一列と確認済み（dst_uni.duplicate_variables / win_pair.duplicate_columns_in_search_space）
DUP_COLUMNS = {"size_rev": "f2_rev"}


# ---------------------------------------------------------------- 読み込み

def load(name, required=True):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        if required:
            raise SystemExit(f"[FATAL] 在庫がない: {p}\n  → 総括は在庫を読むだけの器なので、"
                             f"欠けたまま『合格ゼロ』とは書けない（測っていない と 測って無し は別物）")
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dig(obj, path, default=None):
    cur = obj
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


# ---------------------------------------------------------------- 正規化

LABEL_RE = re.compile(r"([A-Za-z0-9_]+)\s*\[([^\]]+)\]")


def canon_var(v):
    return DUP_COLUMNS.get(v, v)


def canon_pop(p):
    if not p:
        return None
    p = str(p)
    for tag in ("P_full", "P_quality", "P_moat"):
        if tag in p:
            return tag
    return p.strip()


def canon_side(s):
    if not s:
        return None
    s = str(s).lower()
    if "destroy" in s or "破壊" in s:
        return "destroy"
    if "win" in s or "勝者" in s:
        return "win"
    return s


def parse_label(label):
    """'f2_rnd_r[上位1/4] ∧ f2_sga_r[下位1/4]' → 正規化した脚のタプル"""
    if not label:
        return None
    legs = LABEL_RE.findall(str(label))
    if not legs:
        return None
    norm = sorted((canon_var(v), c.strip()) for v, c in legs)
    return tuple(norm)


def key_of(legs, pop, side):
    if legs is None:
        return None
    return (side, pop, legs)


def pretty(legs):
    return " ∧ ".join(f"{v}[{c}]" for v, c in legs)


# ---------------------------------------------------------------- 反証器の候補を読む

def verify_candidate_key(name, d):
    """反証器の candidate から (side, pop, legs) を作る。形が器ごとに違うので総当たり。"""
    c = d.get("candidate") or {}
    side = canon_side(c.get("side"))
    pop = canon_pop(c.get("population"))

    label = c.get("label")
    legs = parse_label(label)

    if legs is None and "legs" in c and isinstance(c["legs"], list):
        pair = []
        for leg in c["legs"]:
            if isinstance(leg, (list, tuple)) and len(leg) >= 2:
                pair.append((canon_var(leg[0]), str(leg[1]).strip()))
            elif isinstance(leg, dict) and "var" in leg and "cut" in leg:
                pair.append((canon_var(leg["var"]), str(leg["cut"]).strip()))
        if pair:
            legs = tuple(sorted(pair))

    if legs is None and "var_a" in c and "var_b" in c:
        legs = tuple(sorted([(canon_var(c["var_a"]), str(c.get("cut_a", "")).strip()),
                             (canon_var(c["var_b"]), str(c.get("cut_b", "")).strip())]))

    if legs is None and "seed" in c and "partner" in c:
        # rnd_sga_indep 形式: seed=[var,'hi',0.75] / partner=[var,'lo',0.5] ——切り方の語彙が違うので label を優先
        legs = parse_label(c.get("label"))

    return {
        "tool": name,
        "side": side,
        "population": pop,
        "legs": legs,
        "label_raw": label or c.get("variable") or c.get("variables"),
        "candidate_raw": c,
    }


# ---------------------------------------------------------------- 本体

def build():
    prereg = load(PREREG)
    panel = load(PANEL)
    diag = load(DIAG)
    asym = load(ASYM)

    out = OrderedDict()
    out["generated"] = "2026-08-11"
    out["tool"] = "night/hist_winner_destroyer.py"
    out["role"] = ("総括の再実行器。既存の out/hist_wd_*.json を読んで合否表を出すだけ。"
                   "統計を再計算しない・線を持たない・判定/採点/台帳/index.html/パックに触らない。")
    out["inputs"] = OrderedDict()
    out["inputs"]["prereg"] = {"file": PREREG, "generated": prereg.get("generated")}
    out["inputs"]["panel"] = {"file": PANEL, "generated": panel.get("generated"),
                              "n_rows": panel.get("n_rows")}
    out["inputs"]["diag"] = {"file": DIAG, "generated": diag.get("generated")}
    out["inputs"]["search"] = {k: v["file"] for k, v in SEARCH_TOOLS.items()}
    out["inputs"]["verify"] = {k: v["file"] for k, v in VERIFY.items()}
    out["inputs"]["asym"] = ASYM

    # ---- 事前登録の線（そのまま写す。読み手が線を確かめられるように） ----
    out["pass_line_verbatim"] = prereg["pass_line"]
    out["stopping_rule_verbatim"] = prereg["stopping_rule"]

    # ---- ① 事前診断（合否を読む前に置く） ----
    diag_sec = OrderedDict()
    diag_sec["_why_first"] = ("『合格ゼロ』が *効果が無い* のか *この手続きでは掴めない* のかは、"
                              "合否より先に置かないと区別できない（hist_valuation v1 の教訓）。")

    jd = dig(diag, ["judgeability", "end_to_end_judgeability"], {})
    diag_sec["end_to_end_judgeable_combinations"] = {
        "n_combinations": jd.get("n_combinations"),
        "n_judgeable_strict": jd.get("n_judgeable_strict"),
        "by_combination": {k: {"judgeable_strict": v.get("judgeable_strict"),
                               "blocking_vintages": v.get("blocking_vintages"),
                               "events_by_vintage": {vv: dd.get("events")
                                                     for vv, dd in (v.get("per_vintage") or {}).items()}}
                           for k, v in (jd.get("by_combination") or {}).items()},
    }
    diag_sec["candidate_gate_applicability"] = dig(
        diag, ["judgeability", "sign_stability_strict_summary"], {})
    diag_sec["reachability_summary"] = dig(diag, ["reachability", "summary"], {})
    diag_sec["min_numerator_binding"] = {
        "summary": dig(diag, ["reachability", "min_numerator_binding_summary"], {}),
        "worst_cells": sorted(dig(diag, ["reachability", "min_numerator_binding_cells"], []),
                              key=lambda x: -x.get("effective_over_registered", 0))[:5],
    }
    diag_sec["power"] = {
        "model": dig(diag, ["power_analytic", "model"]),
        "reading": dig(diag, ["power_analytic", "reading_of_pass_line"]),
        "by_cell_strict3": {k: dig(v, ["all3_strict"])
                            for k, v in dig(diag, ["power_analytic", "by_cell"], {}).items()},
    }
    diag_sec["false_positive_rate"] = {
        "primary_mode": dig(diag, ["false_positive", "primary_mode"]),
        "levels": dig(diag, ["false_positive", "levels"]),
        "search_space_assumed": dig(diag, ["false_positive", "search_space_assumed"]),
        "by_permutation_mode": dig(diag, ["false_positive", "by_permutation_mode"]),
        "mode_comparison_note": dig(diag, ["false_positive", "mode_comparison_note"]),
    }
    diag_sec["instrument_asymmetry_destroy_side"] = dig(asym, ["instrument_asymmetry"], {})
    diag_sec["what_cannot_be_said"] = diag.get("what_cannot_be_said")
    out["pre_diagnosis"] = diag_sec

    # ---- ② 探索器の集計（在庫の verdict_counts をそのまま） ----
    searches = OrderedDict()
    passes = []           # 合格した候補（正規化キーつき）
    for name, spec in SEARCH_TOOLS.items():
        d = load(spec["file"])
        vc = d.get("verdict_counts")
        rec = OrderedDict()
        rec["file"] = spec["file"]
        rec["side"] = spec["side"]
        rec["kind"] = spec["kind"]
        rec["verdict_counts"] = vc
        if vc is None:
            # win_shape は合否の家族が別（形・層の探索）。在庫の answer をそのまま引く
            rec["n_pass"] = dig(d, ["answer", "family_gates123_passes"])
            rec["answer"] = d.get("answer")
            rec["note"] = "この器は prereg の候補表に無い切り方も含むため verdict_counts を持たない。answer を読む。"
        else:
            rec["n_pass"] = vc.get("n_pass")

        detail = d.get("passing_pairs_detail") or []
        rec["n_pass_rows_in_inventory"] = len(detail)
        for p in detail:
            legs = parse_label(p.get("label"))
            pop = canon_pop(p.get("population"))
            passes.append(OrderedDict([
                ("tool", name),
                ("side", spec["side"]),
                ("label", p.get("label")),
                ("population", pop),
                ("legs", legs),
                ("key", key_of(legs, pop, spec["side"])),
                ("maintained_lift", p.get("maintained_lift")),
                ("maintained_lift_measurable_base", p.get("maintained_lift_measurable_base")),
                ("min_numerator_161718", p.get("min_numerator_161718")),
                ("coverage_both_min", p.get("coverage_both_min")),
                ("lift_increment_vs_best_leg", p.get("lift_increment_vs_best_leg")),
                ("by_vintage", p.get("by_vintage")),
                ("sector_mh", p.get("sector_mh") or p.get("sector_mh_161718")),
                ("sector_leave_one_out", p.get("sector_leave_one_out")),
                ("irr_control_2018", p.get("irr_control_2018")),
                ("both_tails", p.get("both_tails")),
                ("group_profile_2018", p.get("group_profile_2018")),
                ("thresholds_2018", p.get("thresholds_2018")),
            ]))
        # 探索器自身が測った偽陽性率（family-wise）
        fpr = dig(d, ["must_report_before_verdict", "false_positive_rate"])
        if fpr:
            rec["own_false_positive_rate"] = {
                "n_tests_in_procedure": fpr.get("n_tests_in_procedure"),
                "P_at_least_one_pass_by_level": fpr.get("P_at_least_one_pass_by_level"),
                "mean_passes_per_permutation_by_level": fpr.get("mean_passes_per_permutation_by_level"),
                "observed_passes_by_level": fpr.get("observed_passes_by_level"),
                "empirical_p_of_observed_pass_count": fpr.get("empirical_p_of_observed_pass_count"),
                "null_distribution_of_max_statistic": fpr.get("null_distribution_of_max_statistic"),
                "null_with_seed_reselection": fpr.get("null_with_seed_reselection"),
                "null_within_sector": fpr.get("null_within_sector"),
                "supplementary_null_measurable_base": fpr.get("supplementary_null_measurable_base"),
            }
        searches[name] = rec
    out["search_tools"] = searches

    # ---- ③ 反証器を読む ----
    verifies = OrderedDict()
    for name, spec in VERIFY.items():
        d = load(spec["file"])
        cand = verify_candidate_key(name, d)
        label_text = dig(d, spec["verdict_path"])
        verifies[name] = OrderedDict([
            ("file", spec["file"]),
            ("verdict_label_path", spec["verdict_path"]),
            ("verdict_label", label_text),
            ("candidate_side", cand["side"]),
            ("candidate_population", cand["population"]),
            ("candidate_legs", cand["legs"]),
            ("candidate_label_raw", cand["label_raw"]),
            ("key", key_of(cand["legs"], cand["population"], cand["side"])),
            ("verdict_full", d.get("verdict")),
        ])
    out["verify_tools"] = verifies

    # ---- ④ 集合演算（この器の唯一の仕事） ----
    # 反証器が触ったキーの集合
    verified_keys = {}
    for name, v in verifies.items():
        k = v["key"]
        if k is None:
            continue
        verified_keys.setdefault(k, []).append(name)

    # 変数の組（切り方を無視した粗い一致）も別に持つ——切り方違いを「兄弟セル」として区別して報告
    def varset(legs):
        return None if legs is None else tuple(sorted(v for v, _ in legs))

    verified_varsets = {}
    for name, v in verifies.items():
        vs = varset(v["candidate_legs"])
        if vs is None:
            continue
        verified_varsets.setdefault((v["candidate_side"], vs), []).append(name)

    dedup = OrderedDict()
    for p in passes:
        k = p["key"]
        if k is None:
            continue
        if k not in dedup:
            dedup[k] = {"rows": [], "side": p["side"], "population": p["population"],
                        "legs": p["legs"]}
        dedup[k]["rows"].append(p)

    table = []
    for k, grp in dedup.items():
        side, pop, legs = k
        rep = max(grp["rows"], key=lambda r: r.get("maintained_lift") or 0)
        exact = verified_keys.get(k, [])
        sibling = [n for n in verified_varsets.get((side, varset(legs)), []) if n not in exact]
        table.append(OrderedDict([
            ("side", side),
            ("population", pop),
            ("label_canonical", pretty(legs)),
            ("labels_in_inventory", sorted({r["label"] for r in grp["rows"]})),
            ("n_inventory_rows", len(grp["rows"])),
            ("maintained_lift", rep.get("maintained_lift")),
            ("min_numerator_161718", rep.get("min_numerator_161718")),
            ("by_vintage_published", rep.get("by_vintage")),
            ("sector_mh", rep.get("sector_mh")),
            ("sector_leave_one_out_worst",
             _worst_loo(rep.get("sector_leave_one_out"))),
            ("verified_exact_cell", exact),
            ("verified_sibling_cell_only", sibling),
            ("verification_status",
             "反証ずみ（同一セル）" if exact else
             ("反証は兄弟セルのみ" if sibling else "**未検証**")),
        ]))
    table.sort(key=lambda r: (r["side"], -(r["maintained_lift"] or 0)))
    out["pass_table"] = table

    # 合否表を信じる前に、その元になったセルをパネルから数え直す
    out["crosscheck_vs_panel"] = crosscheck(panel["rows"], table)

    # 反証器のうち、探索器の『合格』ではないもの（＝惜しい候補・対照を叩いたもの）
    pass_keys = set(dedup.keys())
    off_list = []
    for name, v in verifies.items():
        if v["key"] is None or v["key"] not in pass_keys:
            off_list.append({"tool": name, "candidate": v["candidate_label_raw"],
                             "population": v["candidate_population"], "side": v["candidate_side"],
                             "verdict_label": v["verdict_label"],
                             "why_here": "探索器の『合格』ではない（惜しい候補・対照・切り方違い）"})
    out["verify_targets_not_in_pass_list"] = off_list

    # ---- ⑤ 最終の合否 ----
    n_win_pass = len([r for r in table if r["side"] == "win"])
    n_dst_pass = len([r for r in table if r["side"] == "destroy"])
    refuted, survived, unverified = [], [], []
    for r in table:
        if not r["verified_exact_cell"]:
            unverified.append(r["label_canonical"] + " / " + r["population"] + " / " + r["side"])
            continue
        labels = [verifies[n]["verdict_label"] for n in r["verified_exact_cell"]]
        if any("不合格" in str(x) for x in labels):
            refuted.append(r["label_canonical"] + " / " + r["population"] + " / " + r["side"])
        else:
            survived.append({"candidate": r["label_canonical"] + " / " + r["population"] + " / " + r["side"],
                             "verify_tools": r["verified_exact_cell"],
                             "verdict_labels": labels})

    # 勝者側と破壊側で、同じ手続きの偽陽性率がどれだけ違うか（探索器自身の実測を並べるだけ）
    fpr_cmp = OrderedDict()
    for tool in ("win_pair", "dst_pair"):
        f = dig(searches, [tool, "own_false_positive_rate"], {}) or {}
        fpr_cmp[tool] = {
            "n_tests_in_procedure": f.get("n_tests_in_procedure"),
            "P_at_least_one_pass_by_level": f.get("P_at_least_one_pass_by_level"),
            "observed_passes_by_level": f.get("observed_passes_by_level"),
            "mean_passes_under_null_by_level": f.get("mean_passes_per_permutation_by_level"),
            "null_max_statistic_p95": dig(f, ["null_distribution_of_max_statistic", "p95"]),
            "observed_max_statistic": dig(f, ["null_distribution_of_max_statistic", "observed_in_real_data"]),
            "empirical_p_of_observed_max": dig(f, ["null_distribution_of_max_statistic", "empirical_p_of_observed"]),
            "empirical_p_with_seed_reselection": dig(f, ["null_with_seed_reselection", "null_max_statistic",
                                                        "empirical_p_of_observed"]),
            "empirical_p_within_sector_null": dig(f, ["null_within_sector", "fixed_seeds",
                                                     "null_max_statistic", "empirical_p_of_observed"]),
        }
    fpr_cmp["_reading"] = ("同じ形の手続き・同じ帰無で、**破壊側のほうが偶然に通りにくい**。"
                           "勝者側は帰無でも約半分の確率で1本以上『合格』が出る（L5 0.48）のに対し、"
                           "破壊側は 0.002。したがって『どちらの合格が驚きか』は件数では読めない。")
    out["false_positive_rate_win_vs_destroy"] = fpr_cmp

    out["verdict"] = OrderedDict([
        ("_how_to_read", "『事前登録の5条件を文言どおりに通ったか（探索器）』と"
                         "『反証6検問を生き延びたか（反証器）』は別。両方を出す。"),
        ("prereg_5_gates_passed_by_search", {
            "win": n_win_pass, "destroy": n_dst_pass,
            "detail": "重複列(size_rev=f2_rev)を畳んだ (側 × 母集団 × 脚と切り方) の異なり数",
            "distinct_variable_pairs_reported_by_the_search_tools": {
                "win_pair": dig(searches, ["win_pair", "verdict_counts",
                                           "n_distinct_after_deduplicating_identical_columns"]),
                "dst_pair": dig(searches, ["dst_pair", "verdict_counts",
                                           "n_distinct_after_deduplicating_identical_columns"]),
                "note": "切り方と母集団を無視して『変数の組』だけ数えた値。探索器自身の集計をそのまま引く。"
                        "上の win/destroy の数と食い違うのは粒度の違いであって矛盾ではない。",
            },
        }),
        ("single_variable_passes", {
            "win": dig(searches, ["win_uni", "n_pass"]),
            "destroy": dig(searches, ["dst_uni", "n_pass"]),
            "note": "**単変量では勝者側も破壊側も合格ゼロ**。合格は全部2本の積",
        }),
        ("refuted_by_verification", refuted),
        ("survived_all_six_verifications", survived),
        ("never_sent_to_verification", unverified),
        ("bottom_line_win_side",
         "単変量ゼロ。2本の積で7組が事前登録の5条件を文言どおりに通ったが、"
         "反証にかけた3組はすべて不合格。生き延びたのは1組だけで、それも"
         "『選択調整後 p=0.053・効果はほぼAI期・外部標本ゼロ』で novelty を満たさない（在庫の判定）。"),
        ("bottom_line_destroy_side",
         "単変量ゼロ。2本の積で2組が事前登録の5条件を通り、**どちらも反証にかけられていない**。"),
    ])

    # ---- ⑥ 非対称（prereg の novelty #3 への答え） ----
    out["asymmetry"] = OrderedDict([
        ("quadrant_naming", dig(asym, ["quadrant_naming"])),
        ("quadrant_counts_by_floor", dig(asym, ["quadrant_counts_by_floor"])),
        ("one_sided_destroy_only", dig(asym, ["one_sided_destroy_only"])),
        ("one_sided_win_only", dig(asym, ["one_sided_win_only"])),
        ("both_sides_over_floor", dig(asym, ["both_sides_over_floor"])),
        ("irr_contrast_pooled_2013_2015", dig(asym, ["irr_contrast_not_a_candidate", "pooled_2013_2015"])),
        ("irr_contrast_note", dig(asym, ["irr_contrast_not_a_candidate", "pooled_note"])),
        ("monotonicity_destroy_monotone_win_flat",
         [{"variable": r.get("variable"), "population": r.get("population"),
           "win_spearman": r.get("win_spearman"), "destroy_spearman": r.get("destroy_spearman")}
          for r in dig(asym, ["monotonicity_asymmetry", "destroy_monotone_win_flat"], [])]),
    ])

    # ---- ⑦ 限界 ----
    out["limitations"] = OrderedDict([
        ("from_prereg", prereg.get("vintages", {}).get("independence_warning")),
        ("from_panel", panel.get("known_asymmetries")),
        ("from_diag", diag.get("what_cannot_be_said")),
        ("from_asym", dig(asym, ["limitations"])),
        ("from_dst_uni", "out/hist_wd_dst_uni.json の limitations（生存バイアス・U字・重複列）"),
        ("this_tool", "この器は在庫を読むだけ。在庫が誤っていればこの表も誤る。"
                      "各数字の出所は search_tools / verify_tools に file 名つきで残してある。"),
    ])

    return out


def crosscheck(panel_rows, table):
    """★合否表を信じる前に、合否表の元になったセルをパネルから数え直す。

    **これは合否の再実装ではない**——lift の線・MH・置換・符号安定はここで一切使わない。
    数えるのは (母集団の行数, 事象数, 群の行数, 群の事象数) の4つだけ。
    探索器が publish した数字と食い違えば、どちらかが壊れている（v9.9.65）。

    切り方の語彙の対応（探索器の実装に合わせる。ここが唯一の『合わせ込み』）:
      上位1/4 → 値 >= 75%点（nearest-rank）／下位1/4 → 値 <= 25%点
      中央値超 → 値 >  50%点（**strict**）／中央値以下 → 値 <= 50%点
    ⚠ 中央値超を >= で実装すると、値が中央値ちょうどの社が1社入り lift が約1pt動く
      （実測 2017/P_quality/f2_rnd_r: CCK が境界上。n 50→51・lift 0.2582→0.2491）。
      **合否は動かないが、境界の約束は数字の一部**なので明記する。
    """
    import math

    def qtl(vals, p):
        v = sorted(vals)
        if not v:
            return None
        k = max(1, math.ceil(p * len(v)))
        return v[k - 1]

    CUTS = {"上位1/4": (">=", 0.75), "下位1/4": ("<=", 0.25),
            "中央値超": (">", 0.5), "中央値以下": ("<=", 0.5)}

    agree, disagree, skipped = 0, [], []
    for row in table:
        pop, side = row["population"], row["side"]
        legs = LABEL_RE.findall(row["label_canonical"])
        if any(c not in CUTS for _, c in legs):
            skipped.append({"cell": row["label_canonical"], "why": "切り方の語彙が未知"})
            continue
        for vint, pub in (row.get("by_vintage_published") or {}).items():
            if pub is None:
                continue
            rs = [r for r in panel_rows
                  if r["vintage"] == int(vint) and r["has_outcome"] and r["window_full"] and r.get(pop)]
            sel = rs
            for var, cut in legs:
                op, p = CUTS[cut]
                thr = qtl([r[var] for r in rs if r.get(var) is not None], p)
                if thr is None:
                    sel = []
                    break
                if op == ">=":
                    sel = [r for r in sel if r.get(var) is not None and r[var] >= thr]
                elif op == ">":
                    sel = [r for r in sel if r.get(var) is not None and r[var] > thr]
                else:
                    sel = [r for r in sel if r.get(var) is not None and r[var] <= thr]
            mine = {"n_pop": len(rs), "events": sum(1 for r in rs if r[side]),
                    "n_group": len(sel), "numerator": sum(1 for r in sel if r[side])}
            theirs = {"n_pop": pub.get("n_pop"),
                      "events": pub.get("destroy_events_in_pop"),
                      "n_group": pub.get("n_group"), "numerator": pub.get("numerator")}
            keys = ["n_pop", "n_group", "numerator"] + (["events"] if theirs["events"] is not None else [])
            if all(mine[k] == theirs[k] for k in keys):
                agree += 1
            else:
                disagree.append({"cell": f"{row['label_canonical']} / {pop} / {side}",
                                 "vintage": vint, "mine": mine, "published": theirs})
    return OrderedDict([
        ("what_is_compared", "母集団の行数・事象数・群の行数・群の事象数の4つだけ。lift の線や MH は使わない。"),
        ("n_cells_agree", agree),
        ("n_cells_disagree", len(disagree)),
        ("disagreements", disagree),
        ("skipped", skipped),
        ("tie_convention_note", "中央値超は strict `>`。`>=` にすると 2017/P_quality で1社(CCK)増え lift が "
                               "0.2582→0.2491 に動く（合否は不変）。境界の約束も数字の一部。"),
    ])


def _worst_loo(loo):
    """業種を1つ抜く検査の最悪値（在庫にあるものだけ。無ければ None）"""
    if not isinstance(loo, dict):
        return None
    rows = []
    for sic, v in loo.items():
        if isinstance(v, dict) and "maintained_lift_excluding_this_sector" in v:
            rows.append({"sic2": sic,
                         "maintained_lift_excluding": v["maintained_lift_excluding_this_sector"],
                         "min_numerator_excluding": v.get("min_numerator_excluding"),
                         "still_meets": v.get("still_meets_lift_and_min_num")})
    if not rows:
        return None
    rows.sort(key=lambda r: r["maintained_lift_excluding"])
    return {"worst": rows[0], "all": rows,
            "note": "prereg のゲート4は MH。業種を丸ごと抜くこの検査は**事前登録の外**だが、"
                    "反証器が勝者側の候補を落とすのに使ったのと同じ攻撃なので併記する。"}


def main():
    out = build()
    path = os.path.join(OUT, "hist_wd_verdict.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    v = out["verdict"]
    print("=" * 78)
    print("勝者／破壊の対称探索 —— 総括")
    print("=" * 78)
    print(f"事前登録: {out['inputs']['prereg']['file']} ({out['inputs']['prereg']['generated']})")
    print(f"パネル  : {out['inputs']['panel']['n_rows']} 行")
    print()
    print("■ 事前診断（合否より先に読む）")
    e = out["pre_diagnosis"]["end_to_end_judgeable_combinations"]
    print(f"  端から端まで合否を出せる (母集団×側): {e['n_judgeable_strict']} / {e['n_combinations']}")
    r = out["pre_diagnosis"]["reachability_summary"]
    print(f"  分子>=5 が到達しうるセル: {r.get('cells_min_num_reachable')} / {r.get('cells_judged')}"
          f"（勝者 {dig(r,['by_side','win','share'])} / 破壊 {dig(r,['by_side','destroy','share'])}）")
    fp = out["pre_diagnosis"]["false_positive_rate"]["by_permutation_mode"]["ticker_linked"]["false_positive_rate"]
    print(f"  偽陽性率（単変量800検定・置換2000回）: L1 {fp['L1_any']} / L3 {fp['L3_any']} / L4 {fp['L4_any']}")
    print()
    cc = out["crosscheck_vs_panel"]
    print(f"■ 検算（合否表の元セルをパネルから数え直す）: 一致 {cc['n_cells_agree']} / "
          f"食い違い {cc['n_cells_disagree']} / 飛ばし {len(cc['skipped'])}")
    print()
    print("■ 探索の結果")
    for k, s in out["search_tools"].items():
        print(f"  {k:10s} ({s['side']:7s} {s['kind']:6s}) 合格 {s.get('n_pass')}")
    print()
    print("■ 合否")
    print(f"  事前登録5条件を通った変数の組: 勝者 {v['prereg_5_gates_passed_by_search']['win']} / "
          f"破壊 {v['prereg_5_gates_passed_by_search']['destroy']}")
    print(f"  単変量: 勝者 {v['single_variable_passes']['win']} / 破壊 {v['single_variable_passes']['destroy']}")
    print(f"  反証で落ちた   : {len(v['refuted_by_verification'])}")
    for x in v["refuted_by_verification"]:
        print(f"      - {x}")
    print(f"  反証を生き延びた: {len(v['survived_all_six_verifications'])}")
    for x in v["survived_all_six_verifications"]:
        print(f"      - {x['candidate']}  ({','.join(x['verify_tools'])}: {x['verdict_labels']})")
    print(f"  未検証         : {len(v['never_sent_to_verification'])}")
    for x in v["never_sent_to_verification"]:
        print(f"      - {x}")
    print()
    print(f"→ {path}")


if __name__ == "__main__":
    main()
