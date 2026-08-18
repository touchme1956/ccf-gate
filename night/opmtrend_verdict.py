#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/opmtrend_verdict.py — 利益率トレンド検証の**統合**。

役割: 6仮説の測定(out/opmtrend_h{1..6}.json)と反証(out/opmtrend_ref_h{1..6}.json)を読み、
      事前登録(out/opm_trend_prereg.json)の線に照らして合否を一覧にし、
      測定と反証の食い違いを列挙して採否を決める。

★この器は**新しい測定を一切しない**。既存JSONの値を読み、突き合わせ、
  既に公表されている値の並べ替え（中央値）だけを derived_by_ordering=true の印つきで行う。
★値・規約・採点式・刻み・重み・関門・売却規律・配分には1バイトも触れない（絶対のルール1）。
  index.html / night/score_all.js / out/*_gate_pack.json は開いてすらいない。

出力: out/opmtrend_verdict.json
"""
import json, os, statistics, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "out")

def rd(name):
    p = os.path.join(OUT, name)
    with open(p, encoding="utf-8") as f:
        return json.load(f)

PREREG = rd("opm_trend_prereg.json")
BASE   = rd("opmtrend_base.json")
H  = {i: rd(f"opmtrend_h{i}.json")     for i in range(1, 7)}
R  = {i: rd(f"opmtrend_ref_h{i}.json") for i in range(1, 7)}

def src(f, path):  # 出典を必ず添える
    return {"file": f, "path": path}

# ───────────────────────────────────────────────────────────────
# 0) 読んだファイルの指紋（後から「同じものを読んだか」を確かめられるように）
# ───────────────────────────────────────────────────────────────
def md5(name):
    with open(os.path.join(OUT, name), "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

INPUTS = {n: md5(n) for n in
          ["opm_trend_prereg.json", "opmtrend_base.json"]
          + [f"opmtrend_h{i}.json" for i in range(1, 7)]
          + [f"opmtrend_ref_h{i}.json" for i in range(1, 7)]}

# ───────────────────────────────────────────────────────────────
# 1) 合否の一覧（合格 / 不合格 / 判定不能 を混ぜない）
# ───────────────────────────────────────────────────────────────
h1, h2, h3, h4, h5, h6 = (H[i] for i in range(1, 7))
r1, r2, r3, r4, r5, r6 = (R[i] for i in range(1, 7))

VERDICTS = {}

# --- H1 ---
VERDICTS["H1_selector"] = {
  "q": PREREG["hypotheses"]["H1_selector"]["q"],
  "line": PREREG["hypotheses"]["H1_selector"]["line"],
  "verdict": "不合格",
  "undecidable": {"n": 0, "why": "16セル(8ビンテージ×2プール)すべてで両腕が下限を満たす＝測れたうえでの不合格"},
  "measurement": {"all": h1["verdict"]["by_pool"]["all"], "qual": h1["verdict"]["by_pool"]["qual"],
                  "src": src("opmtrend_h1.json", "verdict.by_pool")},
  "refutation":  {"all": "不合格" if not r1["my_verdict"]["all"]["pass"] else "合格",
                  "qual": "不合格" if not r1["my_verdict"]["qual"]["pass"] else "合格",
                  "src": src("opmtrend_ref_h1.json", "my_verdict")},
  "agree": True,
  "numbers": {
    "all": {"lifts": h1["h1_summary"]["all"]["lifts"], "median": h1["h1_summary"]["all"]["median_lift"],
            "pooled": h1["h1_summary"]["all"]["pooled_lift"], "n_ge_line": h1["h1_summary"]["all"]["n_lift_ge_line"],
            "sign_pos": h1["h1_summary"]["all"]["sign_pos"], "sign_neg": h1["h1_summary"]["all"]["sign_neg"]},
    "qual": {"lifts": h1["h1_summary"]["qual"]["lifts"], "median": h1["h1_summary"]["qual"]["median_lift"],
             "pooled": h1["h1_summary"]["qual"]["pooled_lift"], "n_ge_line": h1["h1_summary"]["qual"]["n_lift_ge_line"],
             "sign_pos": h1["h1_summary"]["qual"]["sign_pos"], "sign_neg": h1["h1_summary"]["qual"]["sign_neg"]},
    "src": src("opmtrend_h1.json", "h1_summary"),
  },
  "why_fail": "8ビンテージのうち2年(2016・2017)で符号が逆。かつ lift がどの読み方(厳格/プール/中央値)でも線 0.15 に届かない（最大 all +0.0769 / qual +0.0723）",
  "power": {"at_line_0.15": {"all": h1["power"]["all"]["0.15"], "qual": h1["power"]["qual"]["0.15"]},
            "at_0.20": {"all": h1["power"]["all"]["0.20"], "qual": h1["power"]["qual"]["0.20"]},
            "at_0.10": {"all": h1["power"]["all"]["0.10"], "qual": h1["power"]["qual"]["0.10"]},
            "false_positive_rate": {"all": h1["permutation"]["all"]["false_positive_rate"],
                                    "qual": h1["permutation"]["qual"]["false_positive_rate"]},
            "src": src("opmtrend_h1.json", "power / permutation")},
  "meaning": "偽陽性率 0.000＝雑音ではまず通らない試験を実データも通らなかった。0.20以上の一様な効果は確実に検出できた（検出力1.00/0.999）。⚠ 0.10 の効果は検出力 0.000/0.0055 ＝『0.10 の効果は無い』とは書けない",
}

# --- H2 ---
VERDICTS["H2_breaker"] = {
  "q": PREREG["hypotheses"]["H2_breaker"]["q"],
  "line": PREREG["hypotheses"]["H2_breaker"]["line"],
  "verdict": "不合格",
  "cell_counts": {"合格": h2["summary"]["n_pass"], "不合格": h2["summary"]["n_fail"],
                  "判定不能": h2["summary"]["n_undecided"], "全": h2["summary"]["n_cells"],
                  "src": src("opmtrend_h2.json", "summary")},
  "pass_cell": h2["summary"]["pass_cells"],
  "undecidable": {
     "cells": h2["summary"]["undecided_cells"],
     "why": "母集団の恒久毀損の実数が分子の下限5に構造的に届かない（2013/qual: 毀損 3社／2017/qual: 4社）＝**神の遮断器でも合格できない**セル。事前登録の reachability_check_before_results どおり合否から外した",
     "src": src("opmtrend_base.json", "reachability['2013/qual'].n_impair=3 / ['2017/qual'].n_impair=4"),
  },
  "measurement": {"verdict": h2["verdict_H2"]["verdict"],
                  "reading_A": h2["verdict_H2"]["reading_A_literal_cell"],
                  "reading_B": h2["verdict_H2"]["reading_B_family"],
                  "aggregation_rule_not_in_prereg": True,
                  "src": src("opmtrend_h2.json", "verdict_H2")},
  "refutation":  {"agrees": r2["verdict_refutation"]["agrees_with_measurement_verdict"],
                  "headline": r2["verdict_refutation"]["headline"],
                  "independent_recompute": r2["independent_reconciliation"]["agree"],
                  "src": src("opmtrend_ref_h2.json", "verdict_refutation / independent_reconciliation")},
  "agree": True,
  "why_fail": "唯一の合格セル 2018/all/-0.10（濃縮2.257・分子20・止率11.5%）は、家族42セルの置換で偶然1つ以上通る確率 0.2175 の中にあり、かつ事前登録の反証で割れる",
  "the_one_pass_cell_broken_by": {
     "業種SIC2で層別(MH)": {"v": 1.9401, "src": src("opmtrend_ref_h2.json", "verdict_refutation.broke[0]")},
     "1業種抜き(SIC28 化学・医薬)": {"v": 1.9726, "n_dropped": 82,
                                    "src": src("opmtrend_h2.json", "adversarial[0].drop_one_sic2")},
     "規模三分位": {"小": 1.6454, "中": 0.6928, "大": 0.0,
                    "src": src("opmtrend_ref_h2.json", "verdict_refutation.broke[2]")},
     "利益率の水準で層別": {"opm<0": 1.0113, "opm>=0": 1.9897, "opm>=5": 1.9168, "opm>=10": 1.4474,
                            "src": src("opmtrend_ref_h2.json", "verdict_refutation.broke[4]")},
     "規模×利益率 3x3 同時": {"v": 1.2017, "src": src("opmtrend_ref_h2.json", "verdict_refutation.broke[5]")},
     "ブートストラップ": {"ci90": [1.6228, 2.9102], "p_conc_lt_2": 0.271,
                          "src": src("opmtrend_ref_h2.json", "verdict_refutation.broke[6]")},
     "隣接ビンテージのぶれ(同じ閾値)": {"min": 1.0703, "max": 2.2574,
                                        "src": src("opmtrend_ref_h2.json", "same_threshold_across_vintages")},
  },
  "predetermined_before_results": {
     "n_stop_rate_fail_before_seeing_results": h2["predetermined_before_results"]["n_stop_rate_predetermined_fail"],
     "effective_family": h2["predetermined_before_results"]["effective_family"],
     "required_conc_where_num_binds_median": h2["predetermined_before_results"]["required_conc_median_where_num_binds"],
     "required_conc_where_num_binds_max": h2["predetermined_before_results"]["required_conc_max_where_num_binds"],
     "note": "★MIN_NUM=5 が濃縮の線 2.0倍を静かに上書きしていた。分子が拘束する15セルでの実効的な要求倍率は中央 4.20倍・最大 14.17倍",
     "src": src("opmtrend_h2.json", "predetermined_before_results"),
  },
}

# --- H3 ---
VERDICTS["H3_level_interaction"] = {
  "q": PREREG["hypotheses"]["H3_level_interaction"]["q"],
  "line": PREREG["hypotheses"]["H3_level_interaction"]["line"],
  "verdict": "不合格",
  "undecidable": {"n": 0, "why": "全16セル(4分割×…)で両腕が下限20を満たす。判定不能はゼロ"},
  "measurement": {"by_cell": h3["verdict"]["by_cell"], "overall": h3["verdict"]["overall"],
                  "src": src("opmtrend_h3.json", "verdict")},
  "refutation":  {"by_cell": r3["verdict"]["by_cell_mine"], "overall": r3["verdict"]["overall"],
                  "independent_recompute_mismatches": r3["verdict"]["independent_recompute_mismatches"],
                  "src": src("opmtrend_ref_h3.json", "verdict")},
  "agree": True,
  "numbers": {
     "median_lift": {k: v["median_lift"] for k, v in h3["h3_summary"].items()},
     "max_lift_any_cell": r3["verdict"]["max_lift_any_cell_any_vintage"],
     "interaction_median_diff": {"all": h3["interaction"]["pools"]["all"]["median_diff"],
                                 "qual": h3["interaction"]["pools"]["qual"]["median_diff"]},
     "interaction_sign": {"all": [h3["interaction"]["pools"]["all"]["sign_pos"], h3["interaction"]["pools"]["all"]["sign_neg"]],
                          "qual": [h3["interaction"]["pools"]["qual"]["sign_pos"], h3["interaction"]["pools"]["qual"]["sign_neg"]]},
     "src": src("opmtrend_h3.json", "h3_summary / interaction.pools"),
  },
  "why_fail": "16セル中 線0.15 に届いたセルはゼロ（最大 0.1278）。かつ符号が揃わない。交互作用そのものは 4勝4敗・中央 -0.0027/-0.0131 で両プールとも実質ゼロ",
}

# --- H4 ---
VERDICTS["H4_shrink_gate"] = {
  "q": PREREG["hypotheses"]["H4_shrink_gate"]["q"],
  "line": PREREG["hypotheses"]["H4_shrink_gate"]["line"] + "（H2 と同じ）",
  "verdict": "不合格",
  "by_pool": {
     "all": {"judged": h4["verdict"]["by_pool"]["all"]["n_judged"], "pass": h4["verdict"]["by_pool"]["all"]["n_pass"],
             "undecidable": h4["verdict"]["by_pool"]["all"]["n_undecidable"],
             "fail_kinds": h4["verdict"]["by_pool"]["all"]["fail_kinds"]},
     "qual": {"judged": h4["verdict"]["by_pool"]["qual"]["n_judged"], "pass": h4["verdict"]["by_pool"]["qual"]["n_pass"],
              "undecidable": h4["verdict"]["by_pool"]["qual"]["n_undecidable"],
              "fail_kinds": h4["verdict"]["by_pool"]["qual"]["fail_kinds"]},
     "src": src("opmtrend_h4.json", "verdict.by_pool"),
  },
  "undecidable": {
     "cells": ["2013/qual", "2017/qual"],
     "why": "H2 と同じ理由——毀損の実数が 3社・4社で分子の下限5に構造的に届かない。★『効かない』ではなく『測れない』",
     "src": src("opmtrend_base.json", "reachability"),
  },
  "concentration": {"and": h4["concentration_summary"]["and"],
                    "cagr_only": h4["concentration_summary"]["cagr_only"],
                    "opm_only": h4["concentration_summary"]["opm_only"],
                    "src": src("opmtrend_h4.json", "concentration_summary")},
  "measurement": {"overall": h4["verdict"]["overall"], "rank_of_2018": h4["rank_of_2018_in_and"],
                  "src": src("opmtrend_h4.json", "verdict.overall / rank_of_2018_in_and")},
  "refutation": {"agreed": r4["refutation_verdict"]["h4_verdict_agreed"],
                 "bottom_line": r4["refutation_verdict"]["bottom_line"],
                 "src": src("opmtrend_ref_h4.json", "refutation_verdict")},
  "agree": True,
  "why_fail": "8ビンテージすべてで濃縮が線 2.0 に届かない（0.47〜1.837・中央1.393）。★2018 が8年で1位＝規則が見つかった当のビンテージが最良＝過剰適合の署名",
  "the_3_2x_claim": {
     "what": "CLAUDE.md が引用し続けてきた『事業の収縮は恒久毀損を3.2倍に濃縮』",
     "reproduced_on_581_pool": h4["replication"]["got"]["concentration"],
     "same_year_on_956_pool": h4["replication_pool_warning"]["all956"]["concentration"],
     "decomposition": {"止めた群の毀損率": [0.1429, 0.1479], "母集団の毀損率": [0.0448, 0.0805],
                       "note": "止めた群はほぼ不変(1.035倍)、母集団が1.797倍になった＝3.19倍は分子ではなく**分母**の産物"},
     "src": [src("opmtrend_h4.json", "replication / replication_pool_warning"),
             src("opmtrend_ref_h4.json", "refutation_verdict.broken[3]")],
  },
}

# --- H5 ---
VERDICTS["H5_persistence"] = {
  "q": PREREG["hypotheses"]["H5_persistence"]["q"],
  "line": {"prereg_has_no_line": True,
           "borrowed": h5["line_declaration"]["line"],
           "borrowed_from": h5["line_declaration"]["borrowed_from"],
           "note": "★事前登録の H5 には line が無い（stat しか無い）。測定側が H1 の線をそのまま借り、実行前にコードへ固定した。反証側も同じ線を使った"},
  "verdict": "不合格",
  "undecidable": {"n": 0, "why": "lift_base の到達可能な上限は 0.456〜0.582 で線 0.15 の3倍以上・n(今<0)=73〜441＝判定不能はゼロ"},
  "measurement": {"all": {k: v["verdict"] for k, v in h5["verdicts"]["all"].items() if k != "undecidable"},
                  "qual": {k: v["verdict"] for k, v in h5["verdicts"]["qual"].items() if k != "undecidable"},
                  "src": src("opmtrend_h5.json", "verdicts")},
  "refutation": {"A_fail_not_broken": r5["final_verdict"]["3_A_fail_not_broken"],
                 "independent_recompute": r5["final_verdict"]["1_independent_recompute"],
                 "src": src("opmtrend_ref_h5.json", "final_verdict")},
  "agree": True,
  "numbers": {
     "lift_base": {"all": [h5["results"]["all"][p]["lift_base"] for p in h5["results"]["all"]],
                   "qual": [h5["results"]["qual"][p]["lift_base"] for p in h5["results"]["qual"]]},
     "lift_contrast": {"all": [h5["results"]["all"][p]["lift_contrast"] for p in h5["results"]["all"]],
                       "qual": [h5["results"]["qual"][p]["lift_contrast"] for p in h5["results"]["qual"]]},
     "pairs": h5["pairs"],
     "src": src("opmtrend_h5.json", "results"),
  },
  "why_fail": "6セルすべて**負**＝持続しないどころか符号は仮説の逆。最大でも -0.0019。★これは『測れなかった』ではなく『測って、持続が無い』",
  "contrast_that_works": {
     "what": "同じ器・同じ対・同じ会社で**水準**を当てると持続する",
     "rho_opm_level": [row["rho_opm(水準)"] for row in h5["level_vs_change"]],
     "lift_base_level": [row["lift_base_opm水準"] for row in h5["level_vs_change"]],
     "rho_rev_instrument": [row["rho_rev(計測器)"] for row in h5["level_vs_change"]],
     "note": "ρ(rev)=0.936〜0.969＝同じ会社を突き合わせている（結合は壊れていない）。この計測器が無ければ『持続ゼロ』は実装バグと区別できない",
     "src": src("opmtrend_h5.json", "level_vs_change"),
  },
}

# --- H6 ---
VERDICTS["H6_nonoverlap"] = {
  "q": PREREG["hypotheses"]["H6_nonoverlap"]["q"],
  "line": h6["line_from_prereg"],
  "verdict": "不合格",
  "undecidable": {"n": 0, "why": "8セルすべて usable（最小の群は W1/qual の73社・下限20）"},
  "measurement": {c: h6["summary"][p][o]["verdict"] for p in h6["summary"] for o in h6["summary"][p] for c in [f"{p}/{o}"]},
  "refutation": {"independent_recalc": r6["verdict"]["independent_recalc"],
                 "my_headline": r6["verdict"]["my_headline"],
                 "n_fields_diff": r6["independent_recalc_vs_h6"]["n_fields_diff_total"],
                 "src": src("opmtrend_ref_h6.json", "verdict / independent_recalc_vs_h6")},
  "agree": True,
  "numbers": {p: {o: {"lifts": h6["summary"][p][o]["lifts"], "median": h6["summary"][p][o]["median_lift"],
                      "n_ge_line": h6["summary"][p][o]["n_lift_ge_line"]}
                  for o in h6["summary"][p]} for p in h6["summary"]},
  "why_fail": "4通り(プール2×結果2)すべてで符号が揃わず、線 0.15 に届いたセルもゼロ。最大 0.1497（W1/qual/SPY超）",
  "the_closest_cell_broken_by": {
     "cell": "W1(2013-07→2016-10)/qual/SPY超", "lift": 0.1497, "gap_to_line": 0.0003,
     "置換 family-wise p": r6["attack_d_permutation"]["p_familywise_max"]["lift_beat"],
     "帰無でも16セルのどれかが線に届く確率": r6["attack_d_permutation"]["null_prob_some_cell_reaches_line"]["lift_beat"],
     "1業種抜き(SIC67 REIT・18社)": 0.12,
     "src": src("opmtrend_ref_h6.json", "attack_d_permutation / attack_a_sector"),
  },
  "key_finding": {
     "what": "H1 の不合格の原因は『終点が全部2026で共有されていること』ではなかった",
     "h1_vs_h6_median_lift": h6["vs_h1_same_procedure_different_windows"]["rows"],
     "note": "手続きを固定して窓だけ重ならないものへ替えても lift は同じ帯（0.008〜0.038）に留まる",
     "src": src("opmtrend_h6.json", "vs_h1_same_procedure_different_windows"),
  },
}

# ───────────────────────────────────────────────────────────────
# 2) 測定と反証の食い違い（全部列挙し、どちらを採るか決める）
# ───────────────────────────────────────────────────────────────
DISCREPANCIES = [
 {
  "id": "D1_H1_beat_tie",
  "where": "H1 / 2018 のベンチ超 4欄（lift_beat・base_beat × all・qual）",
  "measurement": {"lift_beat_all": 0.0367, "base_beat_all": 0.2118, "lift_beat_qual": 0.038, "base_beat_qual": 0.2},
  "refutation":   {"lift_beat_all": 0.0390, "base_beat_all": 0.2107, "lift_beat_qual": 0.0460, "base_beat_qual": 0.1971},
  "cause": "QCOM 2018 の tr_cagr = 0.1499 が SPY のベンチと**完全に同値**。測定側は `>=`（同値を「超えた」に数える）、反証側は `>`。この1社だけ",
  "adopt": "反証（厳密不等号 `>`）",
  "why": "『ベンチを超えた』は厳密不等号が正しい。ただしこれは慣行の違いであって誤りではない",
  "affects_verdict": False,
  "affects_by": "差 0.002〜0.008・線は 0.15・しかもベンチ超は事前登録の主判定ではない",
  "src": src("opmtrend_ref_h1.json", "compare_to_measured.mismatches"),
 },
 {
  "id": "D2_H1_weak_signal",
  "where": "H1 の残り所見『全社プールに弱いが本物の信号がある（中央値lift +0.0277・p=0.0185）』",
  "measurement": "雑音とは区別できる（p=0.018）と記録",
  "refutation": {"family_wise_any_p05": r1["multiple_testing_price"]["_family_wise_any_p05"],
                 "bonferroni_of_median_lift": "0.0185 × 8 = 0.148（線0.05を通らない）",
                 "only_bonferroni_survivor": {"stat": "median_spearman", "p": r1["multiple_testing_price"]["all/median_spearman"]["p"]},
                 "and_that_survivor_flips": {"attack": "崩壊組を外す（opmD5 >= -0.05）",
                                             "median_rho": r1["spearman_attacks"]["all"]["drop_collapse_opmD5_ge_-0.05"]["median"],
                                             "sign": [r1["spearman_attacks"]["all"]["drop_collapse_opmD5_ge_-0.05"]["pos"],
                                                      r1["spearman_attacks"]["all"]["drop_collapse_opmD5_ge_-0.05"]["neg"]]}},
  "adopt": "反証",
  "why": "★4統計量×2プールの族として当てると値札は 0.2015。唯一 Bonferroni を通る順位相関は、崩壊組（opmD5 < -0.05）を外すと **+0.0683 → -0.0324・2正/6負** と符号が反転する。関係の形は単調ではなく**逆U字**（十分位の中央年率は D5/D6 が最高、恒久毀損は D1 15.81% と D10 17.23% の両端が最大）＝測っているのは『上がると良い』ではなく『崩壊すると悪い』で、それは H2 の領分",
  "affects_verdict": False,
  "affects_by": "合否はどちらでも不合格。変わるのは『残った所見をどう読むか』",
  "src": [src("opmtrend_ref_h1.json", "multiple_testing_price / spearman_attacks.all"),
          src("opmtrend_ref_h1.json", "deciles.all")],
 },
 {
  "id": "D3_H1_spearman_scope",
  "where": "H1 の報告文『連続の順位相関も8ビンテージすべてで正』",
  "measurement": "JSON には両プールが在り、all は 8正/0負（中央 +0.0682）・qual は **5正/3負**（中央 +0.0425）",
  "refutation": "『全社プールだけ』と scope を訂正",
  "adopt": "反証（scope の訂正）。★ただし**データの食い違いではない**——両者のJSONの数字は一致しており、報告文の書き方の問題",
  "why": "単独で引用されると誤読を生む。qual は 2016/2017/2022 が負",
  "affects_verdict": False,
  "src": src("opmtrend_h1.json", "exploratory_not_preregistered.pools.qual.spearman_signed_per_vintage"),
 },
 {
  "id": "D4_H1_left_tail_size",
  "where": "H1 の記述『恒久毀損を作っているのは大きさだが、それは**主に小型株の言い換え**』",
  "measurement": "小型株の言い換え、と記述",
  "refutation": "opm>=10% に絞っても残ると主張（報告文では 2.13倍→1.52倍→1.85倍のはしご）",
  "adopt": "反証の**向き**を採る。ただし数字は反証の報告文のものを使わない（下の traceability_gaps 参照）",
  "verifiable_numbers_instead": {
     "within_size_tertile_ratio(|opmD5|上半分の毀損 ÷ 下半分)": {
        "all": {"小": 1.70, "中": 1.12, "大": 1.36},
        "qual": {"小": 1.10, "中": 1.21, "大": 1.99}},
     "read": "★規模三分位の**6セルすべてで比 > 1.0**＝規模を統制しても左尾は残る。よって『主に小型株の言い換え』は言い過ぎ。ただし全社プールの |opmD5| 十分位 D10 は売上中央値 186.8百万$ で、規模との交絡が強いことも同時に事実",
     "src": src("opmtrend_ref_h1.json", "abs_move_vs_size.*.within_size_tertile"),
  },
  "affects_verdict": False,
 },
 {
  "id": "D5_H2_cell_permutation_p",
  "where": "H2 の合格セル 2018/all/-0.10 のセル単独の置換 p",
  "measurement": 0.003,
  "refutation": 0.0,
  "cause": "乱数の種と実装の違い",
  "adopt": "どちらも『単独では極小』で同じ。採否を決める必要が無い",
  "why": "★合否を決めているのは**家族の値札 0.2175**と交絡であって、単独の p ではない",
  "affects_verdict": False,
  "src": [src("opmtrend_h2.json", "adversarial[0].p_cell_permutation"),
          src("opmtrend_ref_h2.json", "verdict_refutation.not_broken[5]")],
 },
 {
  "id": "D6_H2_size_split",
  "where": "H2 の合格セルの規模統制",
  "measurement": {"方式": "売上中央値で二分", "小": 1.788, "大": 0.0,
                  "src": src("opmtrend_h2.json", "adversarial[0].size_split")},
  "refutation":  {"方式": "三分位（事前登録 (b) の読み）", "小": 1.6454, "中": 0.6928, "大": 0.0,
                  "src": src("opmtrend_ref_h2.json", "verdict_refutation.broke[2]")},
  "adopt": "両方（結論が同じ）",
  "why": "どちらの切り方でも合格セルは線 2.0 を割る。三分位のほうが事前登録の文言に忠実",
  "affects_verdict": False,
 },
 {
  "id": "D7_H2_direction_survives",
  "where": "★H2 の探索的所見『方向は実在する（プールMH 1.233 / 1.460 / 1.627）』",
  "measurement": "『向きは実在する。だが 1.2〜1.6倍で線 2.0 に届かない』",
  "refutation": {"reproduced_the_same_numbers": True,
                 "size_x_opm_controlled": {"-0.02": 0.9781, "-0.05": 1.0196, "-0.10": 1.0132},
                 "p_within_stratum": {"-0.02": 0.7095, "-0.05": 0.361, "-0.10": 0.4165},
                 "null_q95": {"-0.02": 1.0648, "-0.05": 1.082, "-0.10": 1.1026}},
  "adopt": "**反証**",
  "why": "★測定側のプールMHは**ビンテージ層だけ**で、社の性質を統制していない。規模×利益率を同時に統制すると 0.978 / 1.020 / 1.013 ＝**方向すら残らない**。帰無の q95 が 1.06〜1.10 なので『6〜10%の超過があれば検出できた』上で何も出なかった。『深いほど強い』という単調性も同時に消える",
  "affects_verdict": False,
  "affects_by": "合否は元から不合格。変わるのは『何が残ったか』——測定側は『弱い信号が残る』、反証後は『残らない』",
  "src": [src("opmtrend_h2.json", "exploratory_pooled_mh"),
          src("opmtrend_ref_h2.json", "pooled_controlled / pooled_controlled_null")],
 },
 {
  "id": "D8_H3_tie_convention",
  "where": "H3 の中央値二分で、中央値ちょうどの行をどちらへ入れるか",
  "measurement": "`>` で低側",
  "refutation": "初版 `>=` で高側 → 19セルがずれた",
  "cause": "★事前登録は境界を書いていない（どちらも誤りではない）",
  "adopt": "どちらでもよい。ただし**必ず明記する**",
  "why": "該当は7636行中 **6行**、per-vintage lift の最大シフト 0.0045、qual/high の最大 lift が 0.1278 ↔ 0.1317。**どちらの規約でも線 0.15 に届くセルはゼロ**",
  "affects_verdict": False,
  "src": src("opmtrend_ref_h3.json", "tie_sensitivity"),
 },
 {
  "id": "D9_H3_posthoc_band",
  "where": "★H3 の事後の帯『qual/opm>=50 の lift 0.1487＝線に迫る』",
  "measurement": "『のべで読むと線 0.15 に迫って見えるが、社単位で数えると 0.047 まで崩れる』と自分で注記",
  "refutation": {"per_cut_permutation_p": {"qual/opm>=50": 0.1644, "qual/opm>=40": 0.0895, "all/opm>=50": 0.2243},
                 "family_wise_p": 0.2727,
                 "null_p95_of_that_band": 0.2218,
                 "leave_one_company_out": "MA を抜くと 0.1487→0.0842／24社中4社は抜くと腕が20を割って評価不能",
                 "leave_one_sector_out": "qual/opm>=40 は SIC73 を抜くと 0.1385→0.0749"},
  "adopt": "**反証**",
  "why": "★n=62 の帯の帰無は p95=0.2218 で、観測 0.1487 はその**内側**＝『線に迫った』のではなく『雑音の幅がそこまで広い』。測定側の社単位の注記は正しいが、単独でも有意でないことまでは示していなかった",
  "affects_verdict": False,
  "src": src("opmtrend_ref_h3.json", "attacks.d2_posthoc_permutation"),
 },
 {
  "id": "D10_H3_level_reversion",
  "where": "★H3 の記述『高マージンほど margin が上がっている（素朴な平均回帰の予想と逆）』",
  "measurement": {"rho(opm_END, opmD5)": {"all": 0.373, "qual": 0.185}},
  "refutation":  {"rho(opm_START, opmD5)": {"all": -0.306, "qual": -0.507},
                  "cause": "opm(終点) = opm_start + opmD5 なので、終点で条件づけて opmD5 の符号で割るのは**同じ量で二度切っている**"},
  "adopt": "**反証**",
  "why": "終点条件づけの産物であって事業の性質ではない。開始時の利益率で切り直すと平均回帰の向き（負）に戻る",
  "affects_verdict": False,
  "consequence": "★これが効いて、唯一生き残っていた all/high の lift が 0.0558 → **-0.0009**（置換 p=0.50・符号 4勝4敗）",
  "src": src("opmtrend_ref_h3.json", "attacks.g_split_on_starting_margin / g_correlations / g_permutation_on_start_split"),
 },
 {
  "id": "D11_H3_permutation_null",
  "where": "H3 の置換の帰無の作り方",
  "measurement": {"null": "会社単位の写像を全ビンテージへ同時（と記述）", "p_all_high": 0.0010},
  "refutation": {"reconstructed_theirs": {"sd": 0.0177, "p95": 0.0282},
                 "naive_within_vintage": {"sd": 0.0174, "p95": 0.0287},
                 "true_company_block": {"sd": 0.0217, "p95": 0.0352},
                 "p_all_high_corrected": 0.0054},
  "adopt": "**反証**（真の会社ブロック null）",
  "why": "★測定側の帰無は素朴な『ビンテージ内で独立に混ぜる』とほぼ同一で、真の会社ブロックより **23% 狭い**。単一の全体順位を使っても、グループ構成がビンテージごとに違うので1社の8つの結果が一緒には動かない",
  "affects_verdict": False,
  "affects_by": "p が 0.0010 → 0.0054 と5倍緩む。それでも 0.05 は下回るので『ゼロと区別できる』は生き残る",
  "src": src("opmtrend_ref_h3.json", "attacks.d_permutation_three_nulls"),
 },
 {
  "id": "D12_H4_strict_definition",
  "where": "H4 の厳格読み（strict）で欠測をどう外すか。**cagr_only/strict の14セルのみ**",
  "measurement": "その規則が使う欄の欠測だけ外す（cagr_only なら cagr5 のみ）",
  "refutation": "cagr5・opmD5 の**どちらか**が欠測なら外す（積と片脚を同じ母集団で比べるため）",
  "example": {"cell": "2013/all/cagr_only/strict", "measurement": {"n": 942, "conc": 1.633},
              "refutation": {"n": 449, "conc": 0.746}},
  "adopt": "**反証**（厳格読みで積と片脚を比べるなら母集団を揃える）",
  "why": "測定側の定義だと『厳格読みの積』と『厳格読みの片脚』が別の母集団になる＝この台帳が11回踏んだ『基準の違う二つを割る』型",
  "affects_verdict": False,
  "affects_by": "★H4 の合否は `and` の main 読みで決まっており、and と opm_only は完全一致。報告の③表も main 読み＝報告そのものは無傷",
  "src": src("opmtrend_ref_h4.json", "definitional_gap"),
 },
 {
  "id": "D13_H4_direction_consistency",
  "where": "★H4 の残り所見『厳格読みの向きは8ビンテージすべて一致（濃縮 1.0超 8/8）』",
  "measurement": "8/8一致・中央 1.393（main）／1.393（strict は 1.821〜1.091 で 8/8）",
  "refutation": {"共通430社に固定": {"1超": "8/8 → 4/8", "median": [1.401, 1.127], "p": 0.2744},
                 "規模三分位で層別(MH)": {"median": [1.393, 1.094], "1超": [7, 5],
                                          "規模層内置換 p(median)": 0.2164, "帰無の中央値": 1.27},
                 "業種×規模": {"median": 0.995, "1超": 4, "min_stratum感度": {"5": 0.988, "8": 0.995, "12": 1.014, "20": 1.012}},
                 "無層別の置換 p(median)": 0.0065},
  "adopt": "**反証**",
  "why": "★『8/8一致』は8つの**別々の母集団**の並記で、母集団を固定すると 4/8。素の 1.39 は雑音ではない(p=0.0065)が、**業種×規模で層別すると 0.995 で消える**。機構: 止めた群は小型に偏り(母集団の小型33.3% vs 止めた群46.5〜57.1%)、小型の毀損率は大型の10〜20倍",
  "affects_verdict": False,
  "affects_by": "合否は元から不合格。変わるのは『規則の性能を測れている(効果量の不合格)』という読み——反証後は『測っていたのは規模だった』",
  "src": src("opmtrend_ref_h4.json", "refutation_verdict.broken / attacks.b3_composition / attacks.a3_min_stratum"),
 },
 {
  "id": "D14_H5_deep_line",
  "where": "★H5 で反証側だけが見つけた1セル『qual × 対称に深い線(-0.10) は3対とも lift>=0.15』",
  "measurement": "測定していない（測定側は『今<th → 次<0』の非対称のみ）",
  "refutation": {"lifts": [0.163, 0.1701, 0.1651], "family_p": 0.0095,
                 "P_at_least_one_family_passes_under_null": 0.001,
                 "numerators": [2, 8, 4], "n_now_below": [7, 21, 14],
                 "level_matched_control_lift": [0.1872, 0.1983, 0.213]},
  "adopt": "**どちらも採らない＝未検証の候補として登録する**",
  "why": "★反証側自身が6つの理由で『発見として扱ってはいけない』と書いている——(1)事前登録に無い後知恵 (2)分子が 2/8/4 で prereg H2 の『分子>=5』を3対中2対で満たさない (3)42行のうち実社数32・10社が重複 (4)**全社プール(n=35/134/126)では 0.131/0.027/0.091 ＝通らない**＝qual に絞って n を 7/21/14 にして初めて出る (5)機構は方向ではなく振れ幅（rho_abs 0.20〜0.40 vs rho_signed -0.14〜+0.02） (6)深い群の next の最頻ビンが3対中2対で『中くらいの上昇』",
  "affects_verdict": False,
  "next": "事前登録して**未見の 2019/2020 ビンテージ**で一度だけ当てる",
  "src": src("opmtrend_ref_h5.json", "A2_symmetric_depth / A2c_family_permutation / A2d_overlap_and_loo / A2e_level_matched_control"),
 },
 {
  "id": "D15_H5_neg_share_range",
  "where": "H5 の記述『opmD5<0 の割合はビンテージで 40.1%〜54.5%（幅14.4pt）動く』",
  "measurement": "40.1%〜54.5%・幅 14.43pt",
  "refutation": "★下端の 40.1% は被覆48%の2013で**別標本**。2013を外すと 41.3%〜54.5%（幅 13.22pt）",
  "adopt": "反証（2013を外した幅を併記する）",
  "why": "向き（窓が十数pt動かす vs 会社自身の前回の符号は -4.66/-4.56/-2.09pt で逆向き）は不変",
  "affects_verdict": False,
  "src": src("opmtrend_ref_h5.json", "macro_vs_company"),
 },
 {
  "id": "D16_H6_false_positive_rate",
  "where": "H6 の手続きの偽陽性率",
  "measurement": 0.0,
  "refutation": 0.0005,
  "cause": "合否条件の書き方が僅かに違う（測定側は pooled の読みも含む＝**より緩い**のに 0）",
  "adopt": "どちらでも同じ（実質0）。反証側自身が『食い違いとして数えない』と書いている",
  "affects_verdict": False,
  "src": src("opmtrend_ref_h6.json", "independent_recalc_vs_h6.note_fp_rate"),
 },
 {
  "id": "D17_H6_closest_cell",
  "where": "★H6 の『線まであと 0.0003』（W1/qual/SPY超 = 0.1497）",
  "measurement": "『唯一の惜しいセル』として報告（合否には使わない）",
  "refutation": {"family_wise_p": 0.1745,
                 "null_prob_some_cell_reaches_line": 0.1725,
                 "drop_SIC67_REIT_18社": 0.12,
                 "pool_definition_sensitivity": {"opm>=10%のみ": 0.1394, "opm>=15%": 0.1777, "全社": 0.0648}},
  "adopt": "**反証**",
  "why": "帰無でも16セルのどれかが線に届く確率が 17.25%＝『あと0.0003』は雑音がふつうに出す大きさ。1業種（REIT 18社・層内 lift +0.525）で ±0.03 動き、プール定義でも線を跨ぐ",
  "affects_verdict": False,
  "src": src("opmtrend_ref_h6.json", "attack_d_permutation / attack_a_sector / attack_i_pool_definition_POST_HOC"),
 },
 {
  "id": "D18_H6_sector_attack_reading",
  "where": "H6 の反証『(a)業種で壊れない』の読み方",
  "measurement": "（H6 は業種攻撃を実施していない）",
  "refutation": "★『業種で壊れない』は支持の証拠ではない——43群・中央値3社・最大31社で、MHに使える層は8群だけ、層ごとの lift は -1.0〜+1.0 に散る。調整後が生と同じなのは**層別が情報を持たないから**＝空振り",
  "adopt": "反証",
  "why": "空振りの検定を『支持』と読むのは、この台帳が繰り返し戒めた『測っていない』と『測って問題なし』の取り違え",
  "affects_verdict": False,
  "src": src("opmtrend_ref_h6.json", "attack_a_sector"),
 },
]

# ───────────────────────────────────────────────────────────────
# 3) ユーザーの実務的な問い: V のような社は歴史で何が期待されたか
# ───────────────────────────────────────────────────────────────
vq   = h3["v_question"]
band = vq["names_in_top_band"]["qual/opm_ge_40"]
comp_means = sorted([c["mean_tr"] for c in band["companies"]])
V_ANSWER = {
 "the_question": "今日の門の V（opm 60%・gmt=down・成長 12.9%）のような社は、歴史の基礎率で何が期待されるか",
 "★層の選び方": "V に最も近い層は『質実証プール ∧ opm>=40% ∧ opmD5<0』。⚠ opm>=40/50% の帯は**事前登録に無い事後の切り方**で、合否には一切使われていない（記述）",

 "layer_1_high_margin_decliners(事前登録の中央値二分・高マージン側で opmD5<0)": {
   "qual": {"n_rows": vq["decliners_high_vs_low"]["qual"]["n_high_decliners"],
            "P(前方年率>=15%)": vq["decliners_high_vs_low"]["qual"]["p_hit_high"],
            "中央年率": vq["decliners_high_vs_low"]["qual"]["med_tr_high"],
            "恒久毀損": vq["decliners_high_vs_low"]["qual"]["p_impair_high"]},
   "対照(低マージン側で opmD5<0)": {"n_rows": vq["decliners_high_vs_low"]["qual"]["n_low_decliners"],
            "P(>=15%)": vq["decliners_high_vs_low"]["qual"]["p_hit_low"],
            "中央年率": vq["decliners_high_vs_low"]["qual"]["med_tr_low"],
            "恒久毀損": vq["decliners_high_vs_low"]["qual"]["p_impair_low"]},
   "read": "★高マージンの下落組の恒久毀損は 1.43%（低マージン側は 5.57%）＝**『壊れる』印ではない**。だが P(15%+) は 23.3% でプールの基礎率と変わらず、中央年率は +8.5%/年＝**『15%で複利する』印でもない**",
   "src": src("opmtrend_h3.json", "v_question.decliners_high_vs_low.qual"),
 },

 "layer_2_the_closest(質実証 ∧ opm>=40% ∧ opmD5<0)": {
   "n_rows": band["n_rows"], "n_companies": band["n_companies"],
   "P(>=15%)_rows": band["p_hit_rows"], "P(>=15%)_companies": band["p_hit_companies"],
   "中央年率(のべ行)": vq["cuts"]["qual/opm_ge_40"]["med_tr_neg"],
   "会社別 mean_tr の中央値": round(statistics.median(comp_means), 4),
   "derived_by_ordering_published_values": True,
   "恒久毀損": {"rows": 0, "companies": band["n_companies_impaired"]},
   "最悪の社": {"mean_tr": band["worst_company_mean_tr"], "ticker": "ANIK"},
   "業種構成(社数)": band["sector_counts_companies"],
   "companies": [{"t": c["t"], "times": c["times"], "opm_lo": c["opm_lo"], "opm_hi": c["opm_hi"],
                  "mean_tr": c["mean_tr"], "hits": c["hits"], "sicDesc": c["sicDesc"]} for c in band["companies"]],
   "src": src("opmtrend_h3.json", "v_question.names_in_top_band['qual/opm_ge_40'] / v_question.cuts"),
 },

 "★この層の中身が答えの半分": {
   "what": "19社のうち **REIT 5社 (SPG/OLP/NNN/FRT/MPT)・海運2社 (DAC/SFL)** で、門が狙う型ではない。門の型に近いのは MA / CME / MCO / SPGI / CHKP / V 自身",
   "門の型の実績(mean_tr)": {"MA": 0.1462, "V": 0.1362, "CME": 0.1248, "MCO": 0.1167, "SPGI": 0.0134, "CHKP": 0.005},
   "read": "★門の型に近い6社（MA/V/CME/MCO/SPGI/CHKP）が出した 15%+ の行は **V の1行だけ**（MA/CME/MCO/SPGI/CHKP は5社とも hits=0）。層の中央値を押し上げているのは REIT (SPG +25.2%・hits 3/3) と航空部品 (TDG +23.5%) と資源 (SM +19.8%)",
 },

 "★V 自身の歴史(8ビンテージ)": {
   "rows": vq["V_actual"],
   "opmD5<0 だったのは": ["2020 (opmD5 -0.0002 → tr 12.12%)", "2022 (opmD5 -0.0059 → tr 15.13%)"],
   "その2回の平均": 0.13625, "hit(>=15%)": "1/2",
   "read": "★V は8ビンテージ中6つで opmD5 が**正**。今日の gmt=down は歴史側の V とは別の局面で、n=2 は基礎率ではなく逸話",
   "src": src("opmtrend_h3.json", "v_question.V_actual"),
 },

 "★測っていないこと（ここが重要）": [
   "**成長は一度も条件に入っていない**。事前登録の6仮説はどれも cagr を単独の条件にしていない。V の成長 12.9% に対応する歴史の層は、この検証には存在しない",
   "門の『事業の収縮』の関門は `cagr<0 ∧ gmt=down` の**積**で、V は cagr 12.9% > 0 なので**そもそも当たらない**。H4 が測ったのはその積であって、V の形（成長 ∧ 利益率低下）ではない",
   "opmD5 は一過性費用を調整しない。V の gmt=down が何由来かはこの検証では区別できない",
 ],

 "answer": "★歴史の基礎率が返す答えは『**壊れないが、速くもない**』。最も近い層（質実証 ∧ opm>=40% ∧ opmD5<0・19社/48行）で恒久毀損は **0社/19社**、しかし P(前方年率>=15%) は **14.6%（社単位 21.1%）**でプールの基礎率 24.0% を上回らず、中央年率は **+7.5%/年**、会社別 mean_tr の中央値は **+7.9%/年**。事前登録の分割（高マージンの下落組・qual n=420）でも 恒久毀損 1.43% / 中央 +8.5%/年。⚠そして**この層で P(>=15%) を作っているのは REIT・航空部品・資源で、門の型に近い6社（MA/V/CME/MCO/SPGI/CHKP）が出した 15%+ の行は V の1行だけ**（MA/CME/MCO/SPGI/CHKP は5社とも 0回）。⚠⚠ ただしこの帯は事後の切り方で、単独の置換 p=0.0895〜0.1644・family-wise p=0.2727・MA 1社を抜くと lift が 0.1487→0.0842 ＝**規則の根拠にはできない**",
}

# ───────────────────────────────────────────────────────────────
# 4) 限界（事前登録のもの + この検証で新たに判ったもの）
# ───────────────────────────────────────────────────────────────
LIMITS = {
 "from_prereg": PREREG["limits_stated_now"],
 "newly_found_in_this_verification": [
  {"id": "L1", "what": "★2013 ビンテージは opmD5 の被覆が 47.56%（他7年は 90.2〜91.8%）で、欠測が**小型に偏る**（opmD5 が有る社の売上中央値は欠測社の 5.91倍・opm 12.64% vs 7.73%）",
   "consequence": "2013 は他の7年と**同じ母集団ではない**。全社プールの 2013 の濃縮（H2 0.63〜1.07・H4 0.47）は指標の性能ではなく被覆を測っている。⚠ 質実証プールでは 2013 の被覆は 93.6% なので、qual では他年と並べてよい公算が高い",
   "src": src("opmtrend_base.json", "opmD5_coverage.2013 / warnings")},
  {"id": "L2", "what": "★窓の長さが 13.09 / 10.09 / 9.09 / 8.09 / 7.17 / 6.17 / 5.17 / 4.17 年と違い、恒久毀損の基礎率が **1.22%〜15.06%** と桁で違う",
   "consequence": "濃縮は比なので水準は正規化されるが、**分子の数＝検出力は窓長に強く依存する**。短い窓の質実証プールは構造的に不利で、H4 の qual 6セルはこれで落ちた",
   "src": src("opmtrend_base.json", "vintage_meta / reachability")},
  {"id": "L3", "what": "★2019〜2022 のベンチマークは SPY ではなく**パネル自身の等ウェイト指数(EW)**（SPY の月次が在庫に無い）",
   "consequence": "『ベンチ超』を8ビンテージで束ねると『基準の違う二つ』になる。H1 は SPY だけの4年を別に出しており（all 中央 +0.0114 / qual **-0.0105**）、**SPY基準だけで見ると qual の中央値は負**。⚠ H2・H4 はベンチマークを一度も使わないのでこの限界は効かない",
   "src": src("opmtrend_base.json", "decisions.benchmark / vintage_meta")},
  {"id": "L4", "what": "★疑似反復——行は『社×ビンテージ』で、全社プールは 6546行＝**実912社**（1社平均 7.18回・430社が8年すべてに登場）、質実証は 2465行＝519社",
   "consequence": "のべ読みは同じ社を何度も数える。H3 の事後の帯では **lift 0.1487 → 社単位 0.0473** と崩れた。H2 の分子は のべ136件＝**実62社**（33社が2ビンテージ以上）",
   "src": [src("opmtrend_h3.json", "pseudo_replication"), src("opmtrend_ref_h2.json", "numerator_overlap")]},
  {"id": "L5", "what": "★『分子>=5社』が『濃縮>=2.0倍』を静かに上書きしていた",
   "consequence": "分子が拘束する15セルでの**実効的な要求倍率は中央 4.20倍・最大 14.17倍**。事前登録は『2.0倍』と書いたが、質実証プールの深い閾値は 2.0倍で試験されていない。次の事前登録は**各セルで実効的に要求される倍率**を結果の前に出すこと",
   "src": src("opmtrend_h2.json", "predetermined_before_results")},
  {"id": "L6", "what": "★到達可能性（神の遮断器でも分子5に届くか）は**必要条件であって十分条件ではなかった**",
   "consequence": "質実証プールは8ビンテージ中6つで reachable=true だったのに、H4 で**実際の規則が止めた群**の毀損は 0〜3社で一度も5に届かなかった＝その6セルは『規則の性能を測れていない』。次の事前登録は『**その規則が現に止める群**で分子が足りるか』も結果の前に数えること",
   "src": src("opmtrend_h4.json", "lesson_reachability")},
  {"id": "L7", "what": "★opm(水準) と opmD5(変化) は独立ではない。しかも**終点で条件づけると符号が反転する**",
   "consequence": "rho(opm_END, opmD5) = +0.373/+0.185 だが rho(opm_START, opmD5) = **-0.306/-0.507**。H3 の分割は終点条件づけなので、そこで見えた『高マージンほど margin が上がる』は産物。★開始時で切り直すと all/high の lift は 0.0558 → -0.0009",
   "src": src("opmtrend_ref_h3.json", "attacks.g_correlations / g_split_on_starting_margin")},
  {"id": "L8", "what": "★H5 には**機械的な負のバイアス**が消せない形で残る",
   "consequence": "opmD5_now = opm[a]-opm[a-4]、opmD5_next = opm[b]-opm[b-4] で **b-4 = a+1 は a の隣年**。端点の一過性の揺れは now を上げ next を下げる向きに入るので、真の持続がゼロでも rho はやや負へ引かれる。⇒ 『**持続は高々ゼロ**』までが安全な読みで、『トレンドは反転する』は書けない",
   "src": src("opmtrend_h5.json", "limits[2]")},
  {"id": "L9", "what": "★事前登録に**集約規則が無い**（H2/H4: 何セル合格すれば仮説が成立するか。H5: 線そのもの。H3: 中央値ちょうどの行の扱い）",
   "consequence": "測定側が実行前に自分で決めて明記したが、これは事前登録の空白。H2 は読み方A（セル単位）なら合格1・読み方B（家族＋反証）なら不合格で、**採ったのは B**。次は集約規則まで結果の前に書くこと",
   "src": src("opmtrend_h2.json", "verdict_H2.aggregation_rule_note")},
  {"id": "L10", "what": "★H6 の4窓は信号と窓の開始のあいだに **0/3/6/9ヶ月** の隙間があり、W1 だけ被覆48%（他は90%超）",
   "consequence": "look-ahead を避けると必然だが、隙間が長いほど信号は薄まる＝**不合格に有利な側へ偏りうる**。W1 が唯一はっきり正なのは『窓の側の特異』とも『別の母集団』とも読める",
   "src": src("opmtrend_h6.json", "per_window / limits")},
  {"id": "L11", "what": "★真の out-of-sample は**ゼロ**。8ビンテージも H6 の4窓も同じ 956社のパネルで、窓はすべて 2026 年で終わる",
   "consequence": "『8ビンテージで符号が揃う/揃わない』は8つの独立な観測ではない。H4 の止めた社は のべ1,047件＝**実445社**（2016以降の隣接ビンテージの Jaccard 0.319〜0.453。⚠2013×2016 だけは 0.052＝2013 が別母集団であることの現れ）",
   "src": src("opmtrend_ref_h4.json", "attacks.h_overlap")},
  {"id": "L12", "what": "★『成長』を一度も条件に入れていない",
   "consequence": "V の形（成長は正のまま利益率だけ下がる）に対応する層がこの検証には存在しない。H4 が測ったのは `cagr<0 ∧ opmD5<0` の**積**で、V はその外側",
   "src": src("opm_trend_prereg.json", "hypotheses（cagr 単独の仮説が無い）")},
 ],
}

# ───────────────────────────────────────────────────────────────
# 5) 出典を辿れない数字（報告文にはあるがどのJSONにも無い）
# ───────────────────────────────────────────────────────────────
TRACEABILITY_GAPS = [
 {"where": "H1 の反証の報告文", "claim": "左尾（|opmD5|大→毀損）は 全社 2.13倍 → 黒字限定 1.52倍 → opm>=10% 1.85倍",
  "status": "★13個のJSONのどれにも該当する数値が無い（grep 済）",
  "action": "この数字は報告に使わない。代わりに検証可能な `abs_move_vs_size.*.within_size_tertile.ratio`（all 1.70/1.12/1.36 ・ qual 1.10/1.21/1.99）を使う。向き（規模を統制しても左尾は残る）は同じ"},
 {"where": "H4 の反証の報告文", "claim": "小型の毀損率 10.8〜26.4% / 大型 0.9〜6.3%",
  "status": "JSON に**散在する形**で在る（attacks.b3_composition の各ビンテージ×三分位の impair_rate）。範囲としては集計されていない",
  "action": "使ってよいが、出典は『各ビンテージの三分位別 impair_rate』と書く"},
]

# ───────────────────────────────────────────────────────────────
# 6) 門への含意（★規約は変えない。絶対のルール1）
# ───────────────────────────────────────────────────────────────
IMPLICATIONS = {
 "★大前提": "この検証は**何も変えない**。事前登録の stopping_rule どおり、合格しても不合格でも値・規約・採点式・関門・売却規律・配分はいっさい変えない（絶対のルール1）。以下は『測った結果こうだった』であって『変えるべき』ではない",
 "門が gmt を使っている4箇所への当てはめ": [
  {"place": "(a) gmPt の採点", "measured": "opmD5 は前方リターンの選別器として不合格（H1・H6）。判定圏で意味を持つ大きさの効果は見つからなかった",
   "read": "『測ったが効かなかった』であって『測っていない』ではない。ただし検出力は lift=0.10 でほぼ0＝**小さい効果の不在は言えない**"},
  {"place": "(b) 事業の収縮の関門 (cagr<0 ∧ gmt=down)", "measured": "8ビンテージで濃縮 0.47〜1.837（中央1.393）＝線 2.0 に一度も届かない。★2018 が8年で1位＝規則が見つかった当のビンテージが最良",
   "read": "★そしてCLAUDE.md が引用し続けてきた『3.2倍』は**分母の産物**（581社プール 3.19倍 → 同じ年の956社プール 1.837倍。止めた群の毀損率は 14.29%→14.79% とほぼ不変で、母集団のほうが 4.48%→8.05% と1.797倍になった）。さらに規模×業種で層別すると中央 0.995 で消える",
   "note": "⚠ v9.9.99 は**この積を『単独では弱い』という理由で**採用しており、今回の8ビンテージはその『単独では弱い』を独立に再現している（opm_only 単独の濃縮は中央 1.022・8年中4年で 1.0 を割る）。積が両脚を上回るのは **5/8**（derived_by_ordering: and と cagr_only/opm_only の published 濃縮を並べただけ）で、上回る主な効き方は**止率を絞ること**——opm_only の止率 37.2〜49.2% に対し積は 11.4〜18.4%",
   "stop_rates_src": src("opmtrend_h4.json", "cells[*/all/{and,cagr_only,opm_only}/main].stop_rate"),
   "numerator_profile_src": src("opmtrend_ref_h2.json", "attack_pass_and_near['2018/all/-0.1'].attacks.opm_level / size_tertiles")},
  {"place": "(c) Intel警報 (gmt=down ∧ sht=down)", "measured": "この検証では測っていない（sht の歴史側の相当物が無い）",
   "read": "★『測っていない』——効かないと読んではいけない"},
  {"place": "(d) S2 売却規律", "measured": "測っていない（この検証は買付側の選別器・遮断器としてのみ当てた）",
   "read": "同上"},
 ],
 "★最も重い所見": {
  "what": "H5——**opmD5 の符号は5年後の自分の符号をまったく予言しない（6セルすべて負）。一方、利益率の水準は強く持続する（rho 0.556〜0.680・lift +0.224〜+0.300）**",
  "why_it_matters": "門の `gmt` は『趨勢』を名乗っている。少なくともこの5年窓・この母集団では、その名前を支える持続が見つからなかった",
  "caveat": "⚠ L8 の機械的な負のバイアスがあるので『持続は高々ゼロ』までが安全な読み。『反転する』とは書けない。⚠ gmt(門の3値・審査官の判断) と opmD5(機械の連続量) は同じものではない（事前登録の限界）",
 },
 "★もし将来この領域を触るなら": [
  "『opmD5 単独』は選別器としても遮断器としても採ってはいけない——粗の関連は本物だが、中身は**赤字の零細企業**の言い換え（H2 の合格セル 2018/all/-0.10 の分子20社は **opm<0 が15社・opm>=0 が5社**、規模三分位では **小19社 / 中1社 / 大0社**。赤字の中では濃縮 1.0113＝完全にゼロ）",
  "★未検証の候補が1つだけ残った: **qual × 対称に深い線(opmD5 < -0.10 → 次も < -0.10)**（3対とも lift 0.163〜0.170）。事前登録して**未見の 2019/2020 ビンテージ**で一度だけ当てること。今日の数字を根拠にしてはいけない（分子 2/8/4・全社プールでは通らない）",
  "『振れ幅は持続する』（rho_abs 0.20〜0.40）は測定側が測っていない本物の所見。ただし方向の情報は持たない（振れる群の同符号率 0.28〜0.55＝コイン投げ以下）",
 ],
}

# ───────────────────────────────────────────────────────────────
OUTDOC = {
 "generated": "2026-08-18",
 "tool": "night/opmtrend_verdict.py",
 "role": "統合。★新しい測定は一切していない（既存の out/opmtrend_*.json を読んで突き合わせるだけ）。値・規約・採点式・刻み・重み・関門・売却規律・配分には1バイトも触れていない",
 "prereg": "out/opm_trend_prereg.json",
 "inputs_md5": INPUTS,
 "headline": "★6仮説すべて不合格。合格したものはゼロ。判定不能は H2 の6セル・H4 の2セル（いずれも恒久毀損の実数が分子の下限5に構造的に届かないため＝『効かない』ではなく『測れない』）。そして測定側が残した肯定的な所見は、反証で**5件中4件が壊れた**",
 "verdict_table": {k: v["verdict"] for k, v in VERDICTS.items()},
 "verdicts": VERDICTS,
 "discrepancies": DISCREPANCIES,
 "discrepancy_summary": {
   "n": len(DISCREPANCIES),
   "affecting_verdict": [d["id"] for d in DISCREPANCIES if d.get("affects_verdict")],
   "adopted_refutation": [d["id"] for d in DISCREPANCIES if "反証" in str(d.get("adopt", ""))],
   "note": "★合否を動かした食い違いは**ゼロ**。すべて『残った所見をどう読むか』の側で効いた",
 },
 "v_question": V_ANSWER,
 "limits": LIMITS,
 "traceability_gaps": TRACEABILITY_GAPS,
 "implications": IMPLICATIONS,
 "stopping_rule_honored": PREREG["stopping_rule"],
}

with open(os.path.join(OUT, "opmtrend_verdict.json"), "w", encoding="utf-8") as f:
    json.dump(OUTDOC, f, ensure_ascii=False, indent=1)
print("wrote out/opmtrend_verdict.json")
print("verdicts:", json.dumps(OUTDOC["verdict_table"], ensure_ascii=False))
