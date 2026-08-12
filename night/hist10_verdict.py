#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_verdict.py — 事前登録v3（複利10%）の総括。**既存の在庫を読むだけ**の再実行器。

役割
  ・角度A〜E の在庫と反証8本の在庫を突き合わせ、事前登録 out/hist10_prereg.json の線で合否を出す
  ・**新しい測定を一つもしない**。数字はすべて在庫からの引用で、この道具が作る数字は
    「在庫どうしが食い違っていないか」の突合せ結果だけ
  ・判定・採点・台帳・index.html・パックには一切触れない

なぜ突合せを持つか
  同じ台帳を見る二つの検査器が違うことを言ってはいけない（v9.9.65）。
  角度A の analysis_set_size と targets の base_rates、角度D の合格と反証器の candidate、
  診断の real_data_pass_count と角度D の n_pass_gate1 は、それぞれ独立に書かれているので一致するはず。

使い方
  python3 night/hist10_verdict.py [--json]
出力
  out/hist10_verdict.json
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def g(d, *path, default=None):
    """欠測を既定値で埋めない。無ければ None を返し、呼ぶ側が『測っていない』と書く。"""
    cur = d
    for k in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            if k not in cur:
                return default
            cur = cur[k]
        elif isinstance(cur, list):
            if not isinstance(k, int) or k >= len(cur):
                return default
            cur = cur[k]
        else:
            return default
    return cur


def main():
    prereg = load("hist10_prereg.json")
    targets = load("hist10_targets.json")
    diag = load("hist10_diag.json")
    A = load("hist10_angleA.json")
    B = load("hist10_angleB.json")
    C = load("hist10_angleC.json")
    D = load("hist10_angleD.json")
    E = load("hist10_angleE.json")
    v_add3 = load("hist10_verify_addscore3.json")
    v_add20 = load("hist10_verify_addscore20.json")
    v_s3q = load("hist10_verify_score3quart.json")
    v_trnd = load("hist10_verify_tree_rnd_rev.json")
    v_tatn = load("hist10_verify_tree_rev_aturn.json")
    v_irr70 = load("hist10_verify_irr70_persist.json")
    v_hvpe = load("hist10_verify_hvpe_ybiz.json")
    v_fpr = load("hist10_verify_fpr.json")
    wd15 = load("hist_wd_verdict.json")

    missing = [n for n, d in [
        ("hist10_prereg.json", prereg), ("hist10_targets.json", targets),
        ("hist10_diag.json", diag), ("hist10_angleA.json", A), ("hist10_angleB.json", B),
        ("hist10_angleC.json", C), ("hist10_angleD.json", D), ("hist10_angleE.json", E),
        ("hist_wd_verdict.json", wd15),
    ] if d is None]
    if missing:
        print("在庫が足りない: " + ", ".join(missing), file=sys.stderr)
        return 2

    # ---------------- 突合せ（この道具が唯一作る数字） ----------------
    xchecks = []

    # (1) 角度A の解析集合と targets の基準率
    for v in ("2013", "2015", "2016", "2017", "2018"):
        a_n = g(A, "analysis_set_size", v, "n")
        a_k = g(A, "analysis_set_size", v, "y10")
        t = g(targets, "base_rates", "y10", v, "P_full∩window_full")
        xchecks.append({
            "check": "角度A の解析集合 vs targets の基準率(P_full∩window_full)",
            "vintage": int(v),
            "angleA": {"n": a_n, "k": a_k},
            "targets": {"n": g(t, "n"), "k": g(t, "k")},
            "match": (a_n == g(t, "n") and a_k == g(t, "k")),
        })

    # (2) 診断の行数と角度E の解析集合
    diag_rows = g(diag, "row_filter")
    xchecks.append({
        "check": "診断の row_filter（has_outcome ∧ window_full の行数）",
        "diag": diag_rows,
        "targets_sum_n_defined": sum(
            g(targets, "base_rates", "y10", v, "P_full∩window_full", "n", default=0)
            for v in ("2013", "2015", "2016", "2017", "2018")),
        "note": "4293 は5ビンテージの合計。角度A/D/E はここから母集団を切り出す",
    })

    # (3) 診断の angle_D real_data_pass_count と角度D の gate1 通過数（変種P）
    d_diag = g(D, "crosscheck_with_diag", "by_subset")
    xchecks.append({
        "check": "診断の加法スコア real_data_pass_count vs 角度D 変種P の gate1 通過",
        "detail": d_diag,
        "match": g(D, "crosscheck_with_diag", "all_match"),
    })

    # (4) 角度D の唯一の合格と、反証器 addscore3 の candidate が同じ配置か
    dpass = (g(D, "passes", 0) or {})
    cand = g(v_add3, "candidate") or {}
    same = all(dpass.get(k) == cand.get(k) for k in ("pop", "subset", "disc", "J", "s", "mode")) \
        and dpass.get("binar") == cand.get("binar")
    xchecks.append({
        "check": "角度D の合格1件 vs 反証器 hist10_verify_addscore3 の candidate",
        "angleD": {k: dpass.get(k) for k in ("pop", "subset", "disc", "binar", "J", "s", "mode")},
        "verifier": cand,
        "match": same,
    })

    # (5) 角度E の gate1 通過セルと、反証器2本の candidate
    e_cells = g(E, "★answers", "(b)_outer_fold_performance") or {}
    e_gate1 = {k: v for k, v in e_cells.items() if v.get("gate1")}
    xchecks.append({
        "check": "角度E で gate1 を通った外側fold群",
        "cells": {k: {"oof_lift": v.get("oof_lift"),
                      "oof_numerator_companies": v.get("oof_numerator_companies"),
                      "gate_failed_at": v.get("gate_failed_at")} for k, v in e_gate1.items()},
        "n": len(e_gate1),
        "verifiers": {
            "P_quality|cov90_14|up": g(v_trnd, "★verdict", "verdict"),
            "P_full|cov90_14|down": g(v_tatn, "★verdict", "final"),
        },
    })

    n_xcheck_fail = sum(1 for c in xchecks if c.get("match") is False)

    # ---------------- 合否（事前登録の線） ----------------
    # 事前登録 pass_line.for_D_and_E: 「加法スコアと木は外側foldでの性能のみを合否に使う」
    verdicts = {
        "A_hurdle10": {
            "judgeable": True,
            "n_pass": g(A, "verdict_counts", "n_pass"),
            "counts": g(A, "verdict_counts", "by_verdict"),
            "fail_gate_histogram": g(A, "verdict_counts", "fail_gate_histogram"),
            "undetermined_gate_histogram": g(A, "verdict_counts", "undetermined_gate_histogram"),
            "near_miss": [
                {"key": r.get("key"), "direction": r.get("direction"),
                 "maintained_lift": r.get("maintained_lift"),
                 "lift_by_vintage": r.get("lift_by_vintage"),
                 "numerator_by_vintage": r.get("numerator_by_vintage"),
                 "gate_failed_at": r.get("gate_failed_at")}
                for r in (g(A, "near_miss_full_diagnostics") or [])
            ],
            "verdict": "合格ゼロ",
        },
        "B_persistence": {
            "judgeable": False,
            "why_not": g(B, "verdict", "B1_is_structurally_unfair", "why"),
            "n_pass": g(B, "verdict", "n_pass"),
            "power_at_registered_line": g(B, "verdict", "power_caveat", "P_detect_at_registered_line_0.15"),
            "fpr": g(B, "fpr"),
            "verdict": "合格ゼロ（B1は事前登録の符号不変ゲートが構造的に到達不能＝『判定不能』／B2は事前登録の外）",
        },
        "C_decomposition": {
            "judgeable": False,
            "why_not": g(C, "★structural_limits_read_first", "1_decomposition_missing_2016_2017", "consequence"),
            "prereg_pass_count": g(C, "★verdict", "prereg_pass_count"),
            "verdict_histogram": g(C, "★verdict", "verdict_histogram"),
            "relaxed_outside_prereg": g(C, "★verdict", "relaxed_outside_prereg", "pass_counts_by_target"),
            "subset_diagnostics_outside_prereg": g(C, "★verdict", "subset_diagnostics_outside_prereg"),
            "verdict": "合格ゼロ（全1840セルが判定不能＝分解在庫が2016/2017に無い）",
        },
        "D_additive_score": {
            "judgeable": True,
            "n_pass_by_search_tool": g(D, "n_pass_all_gates"),
            "search_tool_gates_applied": g(D, "verdict", "line"),
            "prereg_clause_for_D_and_E": g(prereg, "pass_line", "for_D_and_E"),
            "outer_fold_measured_by_search_tool": False,
            "outer_fold_result": {
                "verifier": "night/hist10_verify_addscore3.py",
                "verdict": g(v_add3, "verdicts", "t7_outer_fold(prereg for_D_and_E)"),
                "cv_fixed_structure_oof_lift": {
                    v: g(v_add3, "t7_outer_fold_required_by_prereg", "cv_fixed_structure", v, "oof_lift")
                    for v in ("2016", "2017", "2018")},
                "cv_full_research_oof": {
                    v: {"oof_lift": g(v_add3, "t7_outer_fold_required_by_prereg", "cv_full_research", v, "oof_lift"),
                        "oof_group_n": g(v_add3, "t7_outer_fold_required_by_prereg", "cv_full_research", v, "oof_group_n"),
                        "min_num_met": g(v_add3, "t7_outer_fold_required_by_prereg", "cv_full_research", v, "min_num_met")}
                    for v in ("2016", "2017", "2018")},
                "negative_control": g(v_add3, "final", "t7_outer_fold", "negative_control"),
                "in_sample_minus_oof": g(v_add3, "final", "t7_outer_fold", "in_sample_vs_oof"),
            },
            "the_six_assigned_tests": g(v_add3, "final", "the_six_assigned_tests"),
            "sibling_verifiers": {
                "hist10_verify_score3quart(同一配置・6検問のみ)": g(v_s3q, "verdict", "headline"),
                "hist10_verify_addscore20(全20本の加法スコア)": g(v_add20, "verdict", "s13_result"),
            },
            "verdict": "合格ゼロ（探索側の1件は事前登録 for_D_and_E＝外側fold で不合格）",
        },
        "E_tree_nested_cv": {
            "judgeable": True,
            "n_pass_all_gates": g(E, "★verdict", "n_pass_all_gates"),
            "n_pass_gate1_only": g(E, "★verdict", "n_pass_gate1_only"),
            "n_gate1_pass_whose_later_gates_are_effectively_unreachable":
                g(E, "★verdict", "n_gate1_pass_whose_later_gates_are_effectively_unreachable"),
            "gate1_cells": {k: {"oof_lift": v.get("oof_lift"),
                                "oof_numerator_companies": v.get("oof_numerator_companies"),
                                "per_vintage_lift": v.get("per_vintage_lift"),
                                "gate_failed_at": v.get("gate_failed_at"),
                                "in_sample_lift_for_contrast": v.get("in_sample_lift_for_contrast")}
                            for k, v in e_gate1.items()},
            "in_sample_vs_oof": g(E, "★answers", "★the_in_sample_trap_measured_here", "in_sample_vs_oof"),
            "verdict": "合格ゼロ",
        },
    }

    n_pass_total = 0
    for k, v in verdicts.items():
        p = v.get("n_pass") or v.get("n_pass_all_gates") or v.get("prereg_pass_count")
        if isinstance(p, dict):
            p = p.get("total", 0)
        n_pass_total += (p or 0)
    # 角度D は探索側が1件を出しているが、事前登録の for_D_and_E で不合格＝最終は0
    n_pass_final = 0

    # ---------------- 10% vs 15% ----------------
    cmp10_15 = {
        "reproduction_check": g(A, "comparison_with_15pct", "reproduction_of_published_v1"),
        "base_rate": {
            "10%": {v: g(A, "analysis_set_size", v, "P10") for v in ("2013", "2015", "2016", "2017", "2018")},
            "15%": {v: g(A, "analysis_set_size", v, "P15") for v in ("2013", "2015", "2016", "2017", "2018")},
        },
        "min_numerator": {"v1/v2(15%)": g(wd15, "pass_line_verbatim", "min_numerator"),
                          "v3(10%)": g(prereg, "pass_line", "min_numerator")},
        "class_counts": g(A, "comparison_with_15pct", "class_counts"),
        "new_at_10": [{"key": r.get("key"), "direction_10": r.get("direction_10"),
                       "maintained_lift_10": r.get("maintained_lift_10"),
                       "maintained_lift_15": r.get("maintained_lift_15"),
                       "verdict_10": r.get("verdict_10"), "gate_failed_10": r.get("gate_failed_10")}
                      for r in (g(A, "comparison_with_15pct", "new_at_10") or [])],
        "lost_at_10": g(A, "comparison_with_15pct", "lost_at_10"),
        "reachability_two_way": {
            "10%(y10) down 可能": g(diag, "what_can_be_said", 0),
            "登録対象のみ(y10×P_full/P_quality)": g(diag, "effective_requirement", "registered_scope_only", "y10_excl_P_moat"),
        },
        "power": {
            "note": g(diag, "what_can_be_said", 3),
            "同一セル(up/quartile/2018/P_full)": {
                "15%/5社": 0.5033, "10%/20社(v3登録)": 0.5051,
                "src": "out/hist10_diag.json what_can_be_said[2]",
            },
        },
        "overlap_y10_vs_win15": {
            "2013": g(targets, "overlaps", "y10 × win(15%) (2013)"),
            "2018": g(targets, "overlaps", "y10 × win(15%) (2018)"),
        },
        "v1_v2_result_for_contrast": {
            "single_variable": g(wd15, "verdict", "single_variable_passes"),
            "prereg_5_gates_passed_by_search": g(wd15, "verdict", "prereg_5_gates_passed_by_search"),
            "refuted_by_verification": g(wd15, "verdict", "refuted_by_verification"),
            "survived_all_six_verifications": g(wd15, "verdict", "survived_all_six_verifications"),
            "bottom_line_win_side": g(wd15, "verdict", "bottom_line_win_side"),
            "bottom_line_destroy_side": g(wd15, "verdict", "bottom_line_destroy_side"),
        },
        "variables_that_surfaced": {
            "15%(勝者側の合格の脚)": ["f2_rnd_r", "f2_sga_r", "f2_aturn", "f2_cash_r", "f2_intcov",
                                      "f2_rev", "f2_gw_r", "f2_netiss_r"],
            "15%(破壊側の合格の脚)": ["f2_netiss_r", "f2_rnd_r", "f2_rev"],
            "10%(角度A の線に最も近い2本)": ["f2_intcov", "f2_netiss_r"],
            "10%(角度D の唯一の gate1 合格の脚)": g(D, "passes", 0, "sel"),
            "10%(角度E の木の根・プール)": g(E, "★answers", "(c)_variable_agreement", "tree_root_vars_pooled"),
            "reading": "同じ族（R&D比・販管費比・売上規模・純発行・利払カバー）が両方の線で浮く。"
                       "**10%にして新しい変数が出てきたわけではない**",
        },
    }

    # ---------------- 問い別の答え ----------------
    answers = {
        "B_持続": {
            "question": "『一度は出せるが続かない社』と『続く社』を分ける入口の指標はあったか",
            "answer": "**無い（事前登録の線を通る指標はゼロ）**。ただしこの『ゼロ』は効果の不在ではなく、"
                      "y_persist が入口2013でしか定義できず符号不変ゲートに到達できないこと（B1）と、"
                      "厳密設計(B2)の検出力が 0.135 しかないことの合成",
            "four_groups_B1": g(B, "four_groups", "B1", "n"),
            "four_groups_B1_share": g(B, "four_groups", "B1", "share"),
            "strongest_contrast_measured": {
                "def": "『両方10%+』vs『前半だけ10%+』の AUC−0.5（B1・2013）",
                "top": "co_rev_asof（売上規模）+0.0988",
                "others": {
                    "co_opm": 0.0191, "co_sales_cagr5": 0.0129, "co_roic_med5": 0.0035,
                    "co_roic_latest": 0.0021, "co_roic_worst5": -0.0104,
                    "co_fcf_conv_5y": -0.0246, "co_score": -0.0158, "co_fcf_all_pos": -0.0261,
                },
                "reading": "**ROIC も FCF転換も営業利益率も、続く社と続かない社を分けていない**"
                           "（AUCの持ち上がりは最大でも 0.02・符号が負のものもある）。分けたのは規模だけで、それも 0.099",
            },
            "past_performance_is_not_a_predictor": {
                "B1(2013)": g(B, "B1", "control_past_performance", "2013/P_full"),
                "B2": {v: g(B, "B2", "control_past_performance", "%s/P_full" % v)
                       for v in ("2016", "2017", "2018")},
                "reading": "前半のリターンが後半を当てる度合いは B1 で +0.051、"
                           "**厳密設計 B2 では +0.010／−0.009／−0.008 とほぼゼロか負**。"
                           "『前半で出せた社は後半も出す』は成り立っていない（前半のリターンは入口の指標ではなく結果の一部なので合否には数えない対照）",
            },
            "existing_gates_do_not_predict_persistence": {
                "B1(2013) y_persist_全母集団": g(B, "B1", "control_existing_gates", "2013", "y_persist_全母集団"),
                "B2 y_persist_全母集団": {v: g(B, "B2", "control_existing_gates", v, "y_persist_全母集団")
                                          for v in ("2016", "2017", "2018")},
                "reading": "質実証・事業の収縮・薄い財務のいずれで切っても持続の lift は −0.022〜+0.047。"
                           "**門が既に持つ関門も持続を予言していない**",
            },
            "control_irr_not_a_candidate": {
                "note": "prereg.candidates は irr/moat5/dom を対照専用と明記。候補ではない",
                "B1(2013)": g(B, "B1", "control_irr", "2013"),
                "B2(2018)": g(B, "B2", "control_irr", "2018"),
                "verifier": {"tool": "night/hist10_verify_irr70_persist.py",
                             "irr=70": g(v_irr70, "verdict", "result"),
                             "decisive": g(v_irr70, "verdict", "decisive")},
            },
            "structural_limits": g(B, "structural_limits"),
        },
        "C_分解": {
            "question": "総リターンを当てる変数と、事業の複利を当てる変数は違ったか",
            "answer": "**違う。ほとんど関係がない。** 変数の順位の Spearman は "
                      "0.336 / −0.104 / 0.108（C_all の 2013/2015/2018）で、符号が反転する変数が 6〜14本ある",
            "rank_correlation": g(C, "★findings", "b_do_y10_and_ybiz_pick_different_variables",
                                  "rho_of_variable_rankings_tr_vs_biz"),
            "targets_themselves_differ_phi": g(C, "★findings", "b_do_y10_and_ybiz_pick_different_variables",
                                               "targets_themselves_differ"),
            "biz_vs_mult_is_negative": {
                "2013": -0.9607, "2015": -0.8822,
                "reading": "**事業に効く変数はたいてい倍率には逆に効く**＝総リターンの上では相殺される。"
                           "だから『総リターンで効かない』は『事業で効かない』を意味しない",
                "src": "out/hist10_angleC.json ★(b)…ranking_agreement[C_all|20xx].spearman_of_variable_rankings",
            },
            "median_company": g(C, "★findings", "e_the_median_company_compounds_from_business_not_rerating"),
            "most_dangerous_type": {
                "def": g(C, "★most_dangerous_type_misleading_on_total_return", "definition"),
                "rows": [{k: r.get(k) for k in ("variable", "population", "vintage", "n",
                                                "rho_tr", "rho_biz", "rho_mult", "partial_biz_given_pe_in")}
                         for r in (g(C, "★most_dangerous_type_misleading_on_total_return", "rows") or [])],
                "caveat": g(C, "★most_dangerous_type_misleading_on_total_return", "★but_check_the_confound_first"),
            },
            "the_confound_eats_most_of_it": g(C, "★findings", "d_what_survives_the_confound"),
            "entry_PER_control": {
                "why": g(C, "★survivors_after_controlling_entry_PER", "why"),
                "n_survive_2se": g(C, "★survivors_after_controlling_entry_PER", "n_survive_2se"),
                "n_tested": g(C, "★survivors_after_controlling_entry_PER", "n_tested"),
                "only_two_vintage_survivor": g(C, "★findings", "d_what_survives_the_confound",
                                               "only_two_vintage_survivor"),
            },
            "verifier_on_the_strongest_C_candidate": {
                "tool": "night/hist10_verify_hvpe_ybiz.py",
                "result": g(v_hvpe, "★verdict", "result"),
                "one_line": g(v_hvpe, "★verdict", "one_line"),
                "why_no_practical_value": g(v_hvpe, "★verdict", "substantive", "それでも実務的価値が無い理由", "読み"),
                "cancellation": g(v_hvpe, "★verdict", "substantive", "それでも実務的価値が無い理由",
                                  "恒等式の中の実額(window基準・年率対数・hv_adj_pe_pct)"),
            },
            "structural_limits": g(C, "★structural_limits_read_first"),
        },
        "D_加法スコア": {
            "question": "弱い信号を数えると効くか。効くならそれは関数形の発見であって変数の発見ではない",
            "answer": "**事前登録の線では効かない。** 探索側は1件を合格としたが、"
                      "事前登録 pass_line.for_D_and_E が『外側foldの性能のみを合否に使う』と定めており、"
                      "その外側fold を当てると 0.130/0.137/0.140 で線 0.15 を割り、"
                      "**帰無の p95（0.148〜0.153）も下回る（p=0.06〜0.07）**",
            "premise_check": {
                "def": g(D, "single_variable_baseline", "why"),
                "cov90_14/P_full/median": {
                    "n_candidates": g(D, "single_variable_baseline", "cells", "cov90_14/P_full/median", "n_candidates"),
                    "max_min_abs_lift_3v": g(D, "single_variable_baseline", "cells", "cov90_14/P_full/median", "max_min_abs_lift_3v"),
                    "n_reaching_line": g(D, "single_variable_baseline", "cells", "cov90_14/P_full/median", "n_reaching_line"),
                },
                "reading": "『個々では 0.15 に届かない』という依頼文の前提は実測で正しい（最良でも 0.068）",
            },
            "is_it_a_function_form_or_a_variable": {
                "score_vs_single_variable": g(D, "attacks_on_passes", "cells",
                                              "T_disc2016_quartile|cov90_14|P_quality|quartile|J3|s2|ge",
                                              "reduces_to_single"),
                "what_is_the_score_a_proxy_for": g(D, "what_is_the_score_a_proxy_for", "cells"),
                "sibling_verifier_found": g(v_s3q, "verdict", "what_the_group_actually_is"),
                "reading": "スコアの群の 78〜87% が売上上位1/4で、**その層の中では lift 0.079〜0.103＝線を割る**。"
                           "関数形（数を数えること）ではなく規模の粗い測り方だった疑いが強い",
            },
            "where_it_stops_working": g(v_s3q, "verdict", "where_it_stops_working"),
            "fpr": {
                "diag(結果の前に固定)": g(diag, "false_positive", "angle_D_additive_score", "by_subset"),
                "angleD(自前・探索空間を広げた分の値札)": g(D, "false_positive_rate", "measured_here",
                                                            "union_of_all_variants_searched"),
                "verifier_on_that_number": {"tool": "night/hist10_verify_fpr.py",
                                            "headline": g(v_fpr, "verdict", "headline")},
            },
        },
        "A_10%の線そのもの": {
            "question": "10%にすると何が変わったか",
            "answer": "**到達可能性だけが変わり、検出力はむしろ下がった。**"
                      "下向き（10%+を減らす向き）は 15% の 7/65 から 42/65 へ増えたが、"
                      "δ=0.20 の検出力は 0.9746→0.9668、δ=0.10 の誤合格は 0.0239→0.0364",
            "new_at_10": cmp10_15["new_at_10"],
            "lost_at_10": cmp10_15["lost_at_10"],
        },
    }

    # ---------------- 限界 ----------------
    limits = {
        "out_of_sample_is_zero": {
            "fact": g(prereg, "known_limits_carried_over", 0),
            "meaning": "2013/2015/2016/2017/2018 は同じ956ティッカー。『3ビンテージで維持』は"
                       "独立な3証拠ではなく、同じ会社の別の入口。しかも後半の窓は3つとも 2026-08 で終わる",
        },
        "look_ahead": {
            "f2_*": "filed<=asof で厳密・違反0",
            "co_*": g(prereg, "known_limits_carried_over", 1),
            "affected_angles": "B1（持続の本命設計）と C の 2013/2015 が co_* に載っている",
        },
        "ai_regime": {
            "fact": g(prereg, "known_limits_carried_over", 2),
            "measured": g(D, "attacks_on_passes", "cells",
                          "T_disc2016_quartile|cov90_14|P_quality|quartile|J3|s2|ge", "regime_split"),
            "reading": "角度D の合格候補は 2016入口で 前半 lift +0.058／後半 +0.169、"
                       "2018入口では 前半 +0.090／後半 +0.078。**効果は後半（AI期）に厚い**",
        },
        "survivorship": {
            "fact": g(prereg, "known_limits_carried_over", 3),
            "angleC_extra": "角度Cはさらに『出口で赤字の社は PER が作れず分解できない』ので左裾が構造的に抜ける。"
                            "落ちた社の実現年率の中央値は残った社より 9.4〜13.6pt 低い",
        },
        "power": {
            "at_registered_line": "δ=0.15 ちょうどの効果は約半分しか掴めない（0.4978〜0.5051）。"
                                  "これは設計の欠陥ではなく構造（真の効果が線と等しければ標本分布は線の上下に割れる）",
            "angleB": g(B, "verdict", "power_caveat", "P_detect_at_registered_line_0.15"),
            "angleD": g(D, "power", "cells"),
            "angleE": "δ=0.25 の真の効果を仕込んでも業種ゲートまで通るのは 0.0%（木の形の群は層が薄い）",
            "reading": "**合格ゼロは『効果が無い』の証明ではない**。言えるのは「δ=0.20 以上の一様な効果は無い」まで",
        },
        "false_positive_rate": {
            "angle_A_single": g(diag, "false_positive", "angle_A_single_variable", "false_positive_rate"),
            "angle_D": g(diag, "false_positive", "angle_D_additive_score", "false_positive_rate_union_of_subsets"),
            "angle_E_in_sample": g(diag, "false_positive", "angle_E_tree", "false_positive_rate_union_of_subsets_in_sample"),
            "angle_E_nested_cv": {k: g(diag, "false_positive", "angle_E_tree", "by_subset", k, "false_positive_rate_nested_cv")
                                  for k in ("cov90_14", "all20")},
            "union_across_angles": g(diag, "false_positive", "union_across_angles"),
            "reading": "3つの角度を全部試すと、in-sample の木を含めれば**帰無でも 93.2% の確率で1本は『合格』が出る**。"
                       "外側fold に限れば 51.0%。**この値札の上で実データは0本だった**",
        },
        "fragility_of_the_10pct_line": g(targets, "fragility"),
        "what_cannot_be_said": g(diag, "what_cannot_be_said"),
    }

    out = {
        "generated": "2026-08-12",
        "tool": "night/hist10_verdict.py",
        "role": "事前登録v3（複利10%）の総括。**既存の在庫を読むだけ**。新しい測定をしない",
        "prereg": "out/hist10_prereg.json",
        "prereg_version": g(prereg, "version"),
        "inputs": [
            "out/hist10_prereg.json", "out/hist10_targets.json", "out/hist10_diag.json",
            "out/hist10_angleA.json", "out/hist10_angleB.json", "out/hist10_angleC.json",
            "out/hist10_angleD.json", "out/hist10_angleE.json",
            "out/hist10_verify_addscore3.json", "out/hist10_verify_addscore20.json",
            "out/hist10_verify_score3quart.json", "out/hist10_verify_tree_rnd_rev.json",
            "out/hist10_verify_tree_rev_aturn.json", "out/hist10_verify_irr70_persist.json",
            "out/hist10_verify_hvpe_ybiz.json", "out/hist10_verify_fpr.json",
            "out/hist_wd_verdict.json",
        ],
        "★headline": {
            "n_pass_prereg": n_pass_final,
            "by_angle": {k: v["verdict"] for k, v in verdicts.items()},
            "one_line": "**事前登録v3の線を通った指標はゼロ。** 角度A（単変量）0／角度B（持続）0／"
                        "角度C（分解）0（全セル判定不能）／角度D（加法スコア）は探索側が1件を出したが"
                        "事前登録が角度Dに課している外側fold で不合格／角度E（木・入れ子CV）0。"
                        "**そして『ゼロ』の中身は角度ごとに違う——A/E は不合格、B/C は判定不能、D は7本目のゲートで不合格。**",
            "stopping_rule": g(prereg, "stopping_rule"),
        },
        "★verdict_by_angle": verdicts,
        "★10pct_vs_15pct": cmp10_15,
        "★answers": answers,
        "★limits": limits,
        "crosschecks": {
            "n": len(xchecks),
            "n_fail": n_xcheck_fail,
            "rows": xchecks,
            "note": "この道具が唯一作る数字。在庫どうしが違うことを言っていないかだけを見る（v9.9.65）",
        },
        "not_touched": [
            "index.html", "out/*_gate_pack.json", "台帳", "採点式", "刻み", "重み",
            "四関門", "堀の関門", "売却規律S1/S2/S3", "配分",
        ],
    }

    p = os.path.join(OUT, "hist10_verdict.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("== 事前登録v3（複利10%）の総括 ==")
        print("合格: %d 本" % n_pass_final)
        for k, v in verdicts.items():
            print("  %-22s %s" % (k, v["verdict"]))
        print("突合せ: %d 件中 食い違い %d 件" % (len(xchecks), n_xcheck_fail))
        print("→ %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
