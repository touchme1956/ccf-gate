#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_angleC.py — 角度C: 目的を **P(事業由来の複利 >= +10%/年)** にする。

事前登録: out/hist10_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json          （5ビンテージ統合パネル。特徴量を再実装しない・v9.9.65）
          out/hist_val_decompose_{2013,2015,2018}.json （分解の在庫。分解も再実装しない）
参照    : out/hist10_angleA.json          （同じ手続きの y10 版。**まず再現してから比べる**）
出力    : out/hist10_angleC.json

────────────────────────────────────────────────────────────
なぜ分解を目的変数にするのか（prereg の five_new_angles.C）
────────────────────────────────────────────────────────────
    ln(総リターン) = 倍率の寄与 + 事業の寄与 + 分配
**再評価（倍率）は繰り返さないが、事業は繰り返す。** 20-30年の複利に効くのは事業側なので、
「総リターンが10%+だったか」ではなく「**事業だけで10%+だったか**」を目的に置く。
この台帳は分解を *説明* には使ってきたが、**目的変数にするのは初めて**。

────────────────────────────────────────────────────────────
★ 結果を見る前に判っている構造上の限界（合否より先に読むこと）
────────────────────────────────────────────────────────────
(1) **分解の在庫は 2013/2015/2018 にしかない。2016/2017 は存在しない。**
    prereg の sign_stability は「2016/2017/2018 すべてで維持」なので、
    **角度Cのどのセルもこのゲートを構造的に当てられない＝全セル判定不能**。
    これは「効果が無い」ではなく「**登録した手続きをこの目的には当てられない**」。
    v1 が残した検問「合否基準が母集団の稀少事象の実数で到達可能かを結果の前に数える」の
    **一段手前**——そもそも必要なビンテージが在庫に無い、という到達可能性の失敗。
    緩めた版（2013/2015/2018 で符号不変）は **事前登録の外**として別建てで出し、合否に数えない。

(2) **特徴量の被覆と分解の被覆が直交している。**
    f2_*（厳密 filed<=asof）は 2016/2017/2018 のみ、co_* は 2013/2015 のみ、pa_* は 2018 のみ。
    分解のある3ビンテージと重ねると、**f2_* は 2018 だけ・co_* は 2013/2015 だけ**しか残らない。
    3ビンテージ全部で測れるのは hv_*（自己相対分位）と per と size_rev **だけ**。

(3) **分解の母集団は質実証プールの部分集合**（opm>=10% ∧ 5年FCF全年黒字 ∧ 自己相対36ヶ月 ∧
    **両端で PER が作れる**）。だから角度Cに『P_full』は存在しない。
    母集団の名前を P_full にすると「全社を見ている」という嘘になるので **C_all / C_moat** と呼ぶ。

(4) **出口の純利益が正でない社は分解できないので落ちている＝左裾が構造的に抜けている。**
    落ちた社の実現年率の中央値は残った社より低い（在庫 dropout が実測済み）。
    ⚠ 落ちた社を 0 で埋めない（絶対のルール7）。**除外し、その事実と大きさを必ず出す。**
    ゆえに角度Cで測れるのは「**profitable なまま生き残った社の中で**、事業が10%+複利したか」であって、
    「10%+複利する会社を当てられるか」ではない。**この差を結論で必ず言うこと。**

(5) 目的が変わると**同じ変数でも母集団が変わる**（C-set は ANA の 9.8〜63.6%）。
    y10 と y_biz を比べるときは **同じ C-set の上で両方測る**。母集団が違う二つの lift を
    並べたら、それは目的の差ではなく標本の差になる（この台帳が9回踏んだ「基準の違う二つ」型）。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定
────────────────────────────────────────────────────────────
A) **基準（signal / window）を混ぜない。**
   在庫は2通りの分解を持つ:
     signal : 入口 = ビンテージの asof 月（6月末）＝分位を測ったのと同じ時点。主表。
     window : 入口 = 7月末＝前方リターンの起点と同じ足。**恒等式が厳密に閉じる**
              （実測: tr − (mult_w + biz_w + div + resid_w) の最大 1.6e-06）。
   → **目的変数（y_biz / y_mult）は signal 基準**（在庫の主表と同じ）。
     **共分散の厳密分解は window 基準**（閉じる側でしか分解は成立しない）。
     y_biz は window 基準でも作って**判定が動くかを必ず出す**（biz と biz_w は
     最大 0.19 も食い違う行がある＝入口の TTM 純利益が6月末と7月末で入れ替わる社）。

B) **手続きは角度Aと1文字も変えない。**
   同じ四分位の切り方・同じ lift の定義・同じ MIN_NUM。
   そのうえで **hist10_angleA.json の公表 lift を、この道具の measure() で再現できるかを先に検算する**。
   一致して初めて「目的を変えたら出てきた/消えた」と言える。

C) **閾値を使わない対比も必ず出す。** n が 92〜320 と小さいので四分位＋分子>=20 は
   検出力が乏しい。**Spearman と、総リターンとの共分散の厳密な4分割**（倍率/事業/分配/残差）を
   本体に置く。こちらは閾値を一つも導入しないので、prereg の線と衝突しない（合否には使わない・診断）。

D) **y_mult（倍率だけを目的にした場合）の線は新しい定数を作らない。**
   `mult > 0`（恒等式そのものの中立点）と `mult >= ln(1.10)`（prereg と同じ 10%）の2つだけ。

E) 既存関門（増分ゲート）は **入力が無い行を「関門を通った」と読まない**。
   C-set では質実証は定義上ゼロ（母集団の定義）、収縮・薄い財務は 2018 でしか入力が無い。
   → 関門の状態は「該当/非該当/**入力なし=不明**」の3値で数える（欠測を0と読まない）。

────────────────────────────────────────────────────────────
正直に記録する（完全な事前登録ではない点）
────────────────────────────────────────────────────────────
この道具を書く前に、2018ビンテージについて ρ(変数, tr/mult/biz) を一度だけ探索的に眺めた。
**合否の線（prereg）は一つも変えていない**が、「先に見た」事実は結果の読み方に効くので
出力の limits に明記する。上の設計 A〜E は在庫の構造（在庫の有無・恒等式が閉じるか・被覆）から
決めたもので、相関の値からは決めていない。
"""
import bisect
import json
import math
import os
import random
import statistics as st
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
ANGLE_A = os.path.join(OUT, "hist10_angleA.json")
DEST = os.path.join(OUT, "hist10_angleC.json")

# ─── prereg の線（この道具は一つも作らない・読むだけ） ───
LIFT = 0.15
MIN_NUM = 20
HURDLE = 0.10
LN110 = math.log(1.0 + HURDLE)
INCREMENTAL_MAX_CAUGHT = 0.70

SIGN_VINTAGES = [2016, 2017, 2018]          # prereg の符号不変ゲートが要求するビンテージ
DECOMP_VINTAGES = [2013, 2015, 2018]        # 分解の在庫が実在するビンテージ
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]
POPS = ["C_all", "C_moat"]

SEED = 20260812
N_PERM = 2000
N_POWER = 5000

F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r", "gw_r",
      "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5", "conv5", "netiss_r",
      "payout5", "rev"]
CO = ["roic_med5", "roic_latest", "roic_worst5", "opm", "sales_cagr5", "fcf_conv_5y",
      "op_all_pos", "fcf_all_pos", "equity_neg", "score", "rev_asof"]
PA = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
HV = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_z", "ps_z"]
CANDIDATES = (["f2_" + f for f in F2] + ["co_" + f for f in CO] + ["pa_" + f for f in PA]
              + ["hv_" + f for f in HV] + ["per", "size_rev"])

# 目的変数（signal 基準が主・window 基準は頑健性）
TARGETS = ["y10", "y_biz", "y_mult_pos", "y_mult10", "y_biz_w"]
TARGET_DEF = {
    "y10": "実現年率（配当込み総リターン）>= +10%/年。**角度Aと同じ目的**を C-set の上で測り直したもの",
    "y_biz": "**事業の寄与** >= +10%/年（signal基準・在庫の主表）。exp(biz)-1 >= 0.10",
    "y_mult_pos": "倍率の寄与 > 0（＝再評価が正だった）。恒等式の中立点で切る＝新しい定数を作らない",
    "y_mult10": "倍率の寄与 >= +10%/年。prereg と同じ 10% を倍率側へ当てただけ",
    "y_biz_w": "事業の寄与 >= +10%/年（**window基準**）。y_biz の頑健性検査であって別の目的ではない",
}


# ────────────────────────────── 小道具 ──────────────────────────────
def ranks_of(v):
    n = len(v)
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


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    return pearson(ranks_of(xs), ranks_of(ys))


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


def r6(x):
    return None if x is None else round(x, 6)


def ann_pct(logv):
    """年率対数 → 年率%（読む人のため）"""
    return None if logv is None else round((math.exp(logv) - 1.0) * 100.0, 2)


# ────────────────────────────── 読み込み・結合 ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
rows_all = panel["rows"]
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]
pan_idx = {(r["ticker"], r["vintage"]): r for r in ANA}

ana_by_v = defaultdict(list)
for r in ANA:
    ana_by_v[r["vintage"]].append(r)

decomp = {}
join_report = {}
for v in DECOMP_VINTAGES:
    path = os.path.join(OUT, f"hist_val_decompose_{v}.json")
    d = json.load(open(path, encoding="utf-8"))
    inv = d["rows"]
    hit, miss = [], []
    for dr in inv:
        key = (dr["ticker"], v)
        if key in pan_idx:
            hit.append(dr)
        else:
            miss.append(dr["ticker"])
    decomp[v] = {"meta": d, "rows": hit, "unmatched": miss}
    join_report[str(v)] = {
        "decompose_rows": len(inv),
        "joined_to_analysis_set": len(hit),
        "unmatched_tickers": len(miss),
        "unmatched_sample": miss[:10],
        "decompose_pool_def": d.get("pool_def"),
        "decompose_n": d.get("n"),
    }

# C-set の行を作る（パネル行に分解の値を焼く。**パネル側は書き換えない**＝アンダースコアの一時キー）
C_rows = defaultdict(list)
consistency = {}
for v in DECOMP_VINTAGES:
    max_tr_gap, n_gap = 0.0, 0
    max_hv_gap, n_hv = 0.0, 0
    for dr in decomp[v]["rows"]:
        pr = pan_idx[(dr["ticker"], v)]
        # 突合せ: 同じ社の同じ窓を指しているか（別々に組んだ二つの系列の照合）
        if pr.get("tr_cagr") is not None and dr.get("tr_cagr") is not None:
            g = abs(pr["tr_cagr"] - dr["tr_cagr"])
            max_tr_gap = max(max_tr_gap, g)
            if g > 0.005:
                n_gap += 1
        if pr.get("hv_pe_pct") is not None and dr.get("pe_pct") is not None:
            g = abs(pr["hv_pe_pct"] - dr["pe_pct"])
            max_hv_gap = max(max_hv_gap, g)
            if g > 0.02:
                n_hv += 1
        row = dict(pr)
        row["_mult"] = dr["mult"]
        row["_biz"] = dr["biz"]
        row["_tr"] = dr["tr"]
        row["_mult_w"] = dr.get("mult_w")
        row["_biz_w"] = dr.get("biz_w")
        row["_div"] = dr.get("div")
        row["_resid_w"] = dr.get("resid_w")
        row["_years"] = dr.get("years")
        row["_pe_in"] = dr.get("pe_in")
        row["_pe_out"] = dr.get("pe_out")
        row["_g_eps3_pre"] = dr.get("g_eps3_pre")
        row["_g_rev3_pre"] = dr.get("g_rev3_pre")
        row["_sh_chg"] = dr.get("sh_chg")
        # 目的変数
        row["y10"] = (pr.get("tr_cagr") is not None and pr["tr_cagr"] >= HURDLE)
        row["y_biz"] = (dr["biz"] >= LN110)
        row["y_mult_pos"] = (dr["mult"] > 0)
        row["y_mult10"] = (dr["mult"] >= LN110)
        row["y_biz_w"] = (dr.get("biz_w") is not None and dr["biz_w"] >= LN110)
        row["_has_biz_w"] = dr.get("biz_w") is not None
        C_rows[v].append(row)
    consistency[str(v)] = {
        "tr_cagr_panel_vs_decompose_max_abs_diff": r6(max_tr_gap),
        "tr_cagr_rows_over_0.005": n_gap,
        "pe_pct_panel_vs_decompose_max_abs_diff": r6(max_hv_gap),
        "pe_pct_rows_over_0.02": n_hv,
        "verdict": ("同じ社の同じ窓を指している（独立に組んだ二系列が一致）"
                    if n_gap == 0 and n_hv == 0 else "食い違いあり——比較の前にここを解くこと"),
    }

C_ALL = [r for v in DECOMP_VINTAGES for r in C_rows[v]]


def pop_rows(v, pop):
    if pop == "C_all":
        return C_rows[v]
    if pop == "C_moat":
        return [r for r in C_rows[v] if r.get("P_moat")]
    return []


# ── 恒等式の再検算（在庫を信じる前に自分で閉じるか確かめる） ──
ident = {}
for v in DECOMP_VINTAGES:
    sig_err, win_err = [], []
    for r in C_rows[v]:
        if r["_div"] is not None and r["_mult_w"] is not None and r["_resid_w"] is not None \
                and r["_biz_w"] is not None:
            win_err.append(abs(r["_tr"] - (r["_mult_w"] + r["_biz_w"] + r["_div"] + r["_resid_w"])))
        if r["_div"] is not None:
            sig_err.append(abs(r["_tr"] - (r["_mult"] + r["_biz"] + r["_div"])))
    ident[str(v)] = {
        "window_basis_max_abs_error": r6(max(win_err)) if win_err else None,
        "window_basis_n": len(win_err),
        "window_closes": (max(win_err) < 1e-5) if win_err else None,
        "signal_basis_max_abs_error": r6(max(sig_err)) if sig_err else None,
        "signal_basis_note": ("signal基準は入口の株価が1ヶ月ずれるので tr とは閉じない（設計どおり）。"
                             "**共分散の厳密分解は window 基準でしか成立しない**"),
    }


# ────────────────────────────── 被覆と選択（合否より先に読むこと） ──────────────────────────────
coverage = {}
for v in DECOMP_VINTAGES:
    ana_v = ana_by_v[v]
    pq = [r for r in ana_v if r.get("P_quality")]
    pm = [r for r in ana_v if r.get("P_moat")]
    C = C_rows[v]
    all_quality = all(r.get("P_quality") for r in C)
    d = decomp[v]["meta"]
    dr = d["dropout"]
    # 落ちた社の outcome（左裾がどれだけ抜けたか）
    dropped_rows = dr.get("rows") or []
    dtr = [x.get("tr_cagr") for x in dropped_rows if x.get("tr_cagr") is not None]
    ktr = [r["tr_cagr"] for r in C if r.get("tr_cagr") is not None]
    coverage[str(v)] = {
        "analysis_set_n": len(ana_v),
        "P_quality_n": len(pq),
        "P_moat_n": len(pm),
        "C_set_n": len(C),
        "C_moat_n": len(pop_rows(v, "C_moat")),
        "coverage_vs_analysis_set": r4(rate(len(C), len(ana_v))),
        "coverage_vs_P_quality": r4(rate(len(C), len(pq))),
        "C_set_is_subset_of_P_quality": all_quality,
        "why_not_full": ("分解には (a)質実証プール (b)入口の自己相対36ヶ月 (c)**両端で PER が作れる** "
                         "の3つが要る。(b)(c) が効いて母集団がさらに痩せる"),
        "dropped_by_decomposition": {
            "n": dr.get("dropped_n"),
            "reasons": dr.get("reasons"),
            "kept_tr_cagr_median": dr.get("kept_tr_med"),
            "dropped_tr_cagr_median": dr.get("dropped_tr_med"),
            "gap": (r4(dr["kept_tr_med"] - dr["dropped_tr_med"])
                    if dr.get("kept_tr_med") is not None and dr.get("dropped_tr_med") is not None
                    else None),
            "reading": ("**落ちた社は残った社より実現年率が低い＝左裾が構造的に抜けている。**"
                        "落ちた社を0で埋めていない（ルール7）——除外している。"
                        "ゆえに角度Cが測るのは『profitable なまま生き残った社の中で事業が10%+複利したか』"),
            "dropped_n_with_tr": len(dtr),
            "dropped_P_y10": r4(rate(sum(1 for x in dtr if x >= HURDLE), len(dtr))) if dtr else None,
            "kept_P_y10": r4(rate(sum(1 for x in ktr if x >= HURDLE), len(ktr))) if ktr else None,
        },
        "base_rate_distortion": {
            "P_y10_on_analysis_set": r4(rate(sum(1 for r in ana_v if r["tr_cagr"] >= HURDLE), len(ana_v))),
            "P_y10_on_P_quality": r4(rate(sum(1 for r in pq if r["tr_cagr"] >= HURDLE), len(pq))),
            "P_y10_on_C_set": r4(rate(sum(1 for r in C if r["y10"]), len(C))),
            "reading": "C-set の P(y10) が母集団より高いなら、それは選択の結果であって目的の性質ではない",
        },
    }

# 変数の被覆（3ビンテージそろうか）
var_cov = {}
for var in CANDIDATES:
    cov, ok3 = {}, 0
    for v in DECOMP_VINTAGES:
        C = C_rows[v]
        k = sum(1 for r in C if num(r.get(var)) is not None)
        cov[str(v)] = {"n_rows": len(C), "n_measurable": k, "share": r4(rate(k, len(C)))}
        if k >= MIN_NUM:
            ok3 += 1
    var_cov[var] = {
        "coverage": cov,
        "n_decomp_vintages_measurable": ok3,
        "prereg_sign_gate_evaluable": False,   # 2016/2017 に分解が無いので構造的に不可
        "relaxed_3v_gate_evaluable": (ok3 == 3),
    }
relaxed_evaluable = [k for k, v in var_cov.items() if v["relaxed_3v_gate_evaluable"]]

# size_rev の出所がビンテージで違う（基準の違う二つを黙って並べない）
size_src = {str(v): dict(Counter(r.get("size_src") for r in C_rows[v])) for v in DECOMP_VINTAGES}


# ────────────────────────────── 到達可能性（両方向・目的別） ──────────────────────────────
def reach_cell(v, pop, ykey, min_num=MIN_NUM):
    R = pop_rows(v, pop)
    n = len(R)
    if n == 0:
        return {"n": 0, "verdict": "母集団が空＝判定不能"}
    ev = sum(1 for r in R if r.get(ykey))
    base = ev / n
    g = max(1, n // 4)
    k_up = max(math.ceil((base + LIFT) * g), min_num)
    up_ok = k_up <= min(g, ev)
    k_dn_max = math.floor((base - LIFT) * g)
    dn_ok = k_dn_max >= min_num
    return {
        "n": n, "events": ev, "base": r4(base), "quartile_group_n": g,
        "up": {
            "k_needed": k_up,
            "binding": ("LIFT" if math.ceil((base + LIFT) * g) >= min_num else "MIN_NUM"),
            "effective_lift_required": r4(k_up / g - base),
            "possible": up_ok,
            "max_detectable_lift": r4(min(g, ev) / g - base),
        },
        "down": {
            "k_max_allowed_by_lift": k_dn_max, "k_min_required": min_num,
            "possible": dn_ok,
            "max_detectable_lift": r4(min_num / g - base) if dn_ok else None,
            "why_not": (None if dn_ok else
                        f"群{g}社で lift<=-{LIFT} なら分子は最大 {k_dn_max} 社＝分子>={min_num} と両立しない"),
        },
    }


reach = {t: {f"{v}/{pop}": reach_cell(v, pop, t)
             for v in DECOMP_VINTAGES for pop in POPS} for t in TARGETS}


# ────────────────────────────── 中核: 1セルの測定（角度Aと同一手続き） ──────────────────────────────
def g_shrink(r):
    """事業の収縮（v9.9.99）。入力が無ければ None（**欠測を『非該当』と読まない**）"""
    a, b = r.get("f2_cagr5"), r.get("f2_opmD5")
    if a is None or b is None:
        return None
    return (a < 0) and (b < 0)


def g_thin(r):
    v = r.get("f2_intcov")
    return None if v is None else (v < 3)


def g_notq(r):
    # C-set は定義上すべて P_quality。ここは常に False（＝関門にかからない）になる
    return not r.get("P_quality")


def g_blocked(r):
    """3値: True(既存関門で落ちる) / False(通る) / None(入力が無く不明)"""
    parts = [g_notq(r), g_shrink(r), g_thin(r)]
    if any(p is True for p in parts):
        return True
    if any(p is None for p in parts):
        return None
    return False


def measure(v, pop, var, ykey, min_num=MIN_NUM):
    R = pop_rows(v, pop)
    n_pop = len(R)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in R if r.get(ykey))
    p_pop = rate(k_pop, n_pop)

    M = [(num(r.get(var)), 1 if r.get(ykey) else 0, r) for r in R]
    M = [(x, w, r) for (x, w, r) in M if x is not None]
    n_m = len(M)
    if n_m == 0:
        return {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": 0,
                "status": "この母集団でこの変数は一つも測れない＝判定不能"}
    k_m = sum(w for (_, w, _) in M)
    p_m = rate(k_m, n_m)
    n_miss = n_pop - n_m
    k_miss = k_pop - k_m
    p_miss = rate(k_miss, n_miss) if n_miss else None

    vals = sorted(x for (x, _, _) in M)
    distinct = len(set(vals))
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    PRED = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
            "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}
    DESC = {"上位1/4": f"値 >= {q75!r}(75%点)", "下位1/4": f"値 <= {q25!r}(25%点)",
            "中央値超": f"値 > {q50!r}(中央値)", "中央値以下": f"値 <= {q50!r}(中央値)"}

    cuts = {}
    for name in CUTNAMES:
        pred = PRED[name]
        grp = [(x, w, r) for (x, w, r) in M if pred(x)]
        gn, gk = len(grp), sum(w for _, w, _ in grp)
        gp = rate(gk, gn)
        lift = None if gp is None else gp - p_pop
        ent = {"cut": DESC[name], "n_group": gn, "numerator": gk, "p_group": r4(gp),
               "lift_vs_pop": r4(lift),
               "lift_vs_measurable": r4(None if gp is None else gp - p_m),
               "direction": (None if lift is None else
                             ("増やす" if lift > 0 else ("減らす" if lift < 0 else "ゼロ")))}
        if gn:
            share = gn / n_m
            ent["group_share_of_measurable"] = r4(share)
            if name in ("上位1/4", "下位1/4") and not (0.10 <= share <= 0.45):
                ent["tie_degenerate"] = True
            fails = [r for (_, w, r) in grp if not w]
            st_f = [g_blocked(r) for r in fails]
            caught = sum(1 for s in st_f if s is True)
            unknown = sum(1 for s in st_f if s is None)
            known = len(st_f) - unknown
            passers = [(x, w) for (x, w, r) in grp if g_blocked(r) is False]
            bp = [(x, w) for (x, w, r) in M if g_blocked(r) is False]
            ent["incremental"] = {
                "down_side": {
                    "n_failures_in_group": len(fails),
                    "already_caught_by_existing_gates": caught,
                    "unknown_gate_status": unknown,
                    "caught_share_over_known": r4(rate(caught, known)),
                    "note": ("**入力の無い行は『通った』と数えない**（ルール7）。"
                             "C-set では質実証は定義上ゼロ、収縮・薄い財務は 2018 でしか入力が無い"),
                },
                "up_side": {
                    "n_group_passing_gates": len(passers),
                    "p_group_passing_gates": r4(rate(sum(w for _, w in passers), len(passers))),
                    "n_base_passing_gates": len(bp),
                    "p_base_passing_gates": r4(rate(sum(w for _, w in bp), len(bp))),
                    "lift_within_gate_passers": r4(
                        None if not passers or not bp else
                        rate(sum(w for _, w in passers), len(passers)) - rate(sum(w for _, w in bp), len(bp))),
                },
                "circular_note": "C-set は定義上すべて質実証プール＝増分ゲートの『質実証』側は常に空",
            }
        cuts[name] = ent

    quint = []
    if distinct >= 5:
        qs = [q_at(vals, x) for x in (0.2, 0.4, 0.6, 0.8)]
        buckets = [[] for _ in range(5)]
        for (x, w, _) in M:
            b = 0
            for i, t in enumerate(qs):
                if x > t:
                    b = i + 1
            buckets[b].append(w)
        for i, b in enumerate(buckets):
            quint.append({"q": i + 1, "n": len(b), "k": sum(b), "p": r4(rate(sum(b), len(b)))})
        pts = [(i, q["p"]) for i, q in enumerate(quint) if q["p"] is not None and q["n"] >= 10]
        mono = spearman([a for a, _ in pts], [b for _, b in pts]) if len(pts) >= 3 else None
    else:
        mono = None

    by_val = None
    if distinct <= 6:
        c = defaultdict(lambda: [0, 0])
        for (x, w, _) in M:
            c[x][0] += 1
            c[x][1] += w
        by_val = [{"value": k, "n": a, "k": b, "p": r4(rate(b, a))} for k, (a, b) in sorted(c.items())]

    return {
        "n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop),
        "n_measurable": n_m, "k_measurable": k_m, "p_measurable": r4(p_m),
        "n_missing": n_miss, "p_missing": r4(p_miss),
        "missingness_lift": r4(None if p_miss is None else p_miss - p_m),
        "distinct": distinct, "q25": q25, "q50": q50, "q75": q75,
        "cuts": cuts, "quintiles": quint or None, "quintile_spearman": r4(mono),
        "by_value": by_val,
        "rank_corr_value_vs_y": r4(spearman([x for (x, _, _) in M], [float(w) for (_, w, _) in M])),
    }


cells = {}
for t in TARGETS:
    for var in CANDIDATES:
        for pop in POPS:
            for v in DECOMP_VINTAGES:
                m = measure(v, pop, var, t)
                if m:
                    cells[f"{t}|{var}|{pop}|{v}"] = m


# ────────── 検算(1): 角度Aの公表 lift を、この道具の measure() で再現できるか ──────────
reproduction = {"status": "参照ファイルが無い"}
if os.path.exists(ANGLE_A):
    A = json.load(open(ANGLE_A, encoding="utf-8"))

    def measure_on(rows, var, ykey):
        """角度Aの母集団（P_full / P_quality の全 ANA 行）で同じ手続きを回す"""
        n_pop = len(rows)
        k_pop = sum(1 for r in rows if r.get(ykey))
        M = [(num(r.get(var)), 1 if r.get(ykey) else 0) for r in rows]
        M = [(x, w) for (x, w) in M if x is not None]
        if not M:
            return None
        vals = sorted(x for x, _ in M)
        q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
        PRED = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}
        out = {}
        for name, pred in PRED.items():
            g = [w for x, w in M if pred(x)]
            out[name] = (None if not g else round(sum(g) / len(g) - k_pop / n_pop, 4))
        return out

    for r in ANA:
        r["_y10"] = (r.get("tr_cagr") is not None and r["tr_cagr"] >= HURDLE)
    checked, mism, diffs = 0, 0, []
    for row in (A.get("top_gate_evaluable", []) + A.get("top30_by_lift", [])):
        var, pop, cut, av = row["variable"], row["population"], row["cut"], row["anchor_vintage"]
        base = [r for r in ana_by_v.get(av, []) if (r.get(pop) if pop != "P_full" else r.get("P_full"))]
        got = measure_on(base, var, "_y10")
        if not got or got.get(cut) is None or row.get("lift_anchor") is None:
            continue
        checked += 1
        d = abs(got[cut] - row["lift_anchor"])
        if d > 1e-9:
            mism += 1
            diffs.append({"key": f"{var}|{pop}|{cut}@{av}", "mine": got[cut],
                          "published": row["lift_anchor"]})
    for r in ANA:
        r.pop("_y10", None)
    reproduction = {
        "what": "角度Aの母集団（ANA全行）で、この道具の切り方・lift の定義をそのまま当てて公表値と突合",
        "n_checked": checked, "n_mismatch": mism, "mismatches": diffs[:20],
        "verdict": ("完全一致＝**手続きは角度Aと同一**。以降の差は目的（と標本）の差であって手続きの差ではない"
                    if mism == 0 else "食い違いあり＝比較の前にここを解くこと"),
    }


# ────────────────────────────── 判定（prereg の6条件） ──────────────────────────────
def summarize(t, var, pop):
    per_v = {}
    for v in DECOMP_VINTAGES:
        m = cells.get(f"{t}|{var}|{pop}|{v}")
        per_v[v] = m if (m and m.get("n_measurable", 0) > 0) else None
    out = {"target": t, "variable": var, "population": pop, "cuts": {}}
    for cut in CUTNAMES:
        row = {}
        for v in DECOMP_VINTAGES:
            m = per_v.get(v)
            if not m:
                row[str(v)] = None
                continue
            c = m["cuts"][cut]
            row[str(v)] = {"n_group": c["n_group"], "k": c["numerator"], "p_group": c["p_group"],
                           "p_base": m["p_pop"], "lift": c["lift_vs_pop"],
                           "direction": c.get("direction"),
                           "tie_degenerate": c.get("tie_degenerate", False),
                           "incremental": c.get("incremental")}
        got = [row[str(v)] for v in DECOMP_VINTAGES
               if row.get(str(v)) and row[str(v)]["lift"] is not None]
        gate = {"n_vintages_with_lift": len(got)}
        if len(got) == 3:
            signs = {(1 if g["lift"] > 0 else (-1 if g["lift"] < 0 else 0)) for g in got}
            gate["relaxed_sign_stability_3v"] = (len(signs) == 1 and 0 not in signs)
            gate["relaxed_lift_all3"] = all(abs(g["lift"]) >= LIFT for g in got)
            gate["relaxed_min_num_all3"] = all(g["k"] >= MIN_NUM for g in got)
            gate["min_abs_lift_3v"] = r4(min(abs(g["lift"]) for g in got))
            gate["signed_lifts_3v"] = [g["lift"] for g in got]
            gate["numerators_3v"] = [g["k"] for g in got]
            gate["direction_3v"] = (list(signs)[0] if len(signs) == 1 else None)
        else:
            gate["relaxed_sign_stability_3v"] = None
            gate["min_abs_lift_3v"] = None
        row["gate"] = gate
        out["cuts"][cut] = row
    out["monotonicity"] = {str(v): (None if not per_v.get(v) else {
        "quintiles": per_v[v]["quintiles"], "spearman": per_v[v]["quintile_spearman"],
        "by_value": per_v[v]["by_value"], "rank_corr": per_v[v]["rank_corr_value_vs_y"]}) for v in DECOMP_VINTAGES}
    return out


summaries = {}
for t in TARGETS:
    for var in CANDIDATES:
        for pop in POPS:
            s = summarize(t, var, pop)
            if any(s["cuts"][c].get(str(v)) for c in CUTNAMES for v in DECOMP_VINTAGES):
                summaries[f"{t}|{var}|{pop}"] = s


def mh_risk_diff(v, pop, var, cut, ykey):
    R = pop_rows(v, pop)
    M = [(num(r.get(var)), 1 if r.get(ykey) else 0, r.get("sic2")) for r in R]
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
            d[0] += 1
            d[1] += w
        else:
            d[2] += 1
            d[3] += w
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


def verdict_for(t, var, pop, cut):
    """prereg の6条件。**sign_stability は 2016/2017/2018 を要求する**ので、
       分解の無い角度Cでは全セルがここで判定不能になる（設計上の限界であって効果の不在ではない）。"""
    s = summaries.get(f"{t}|{var}|{pop}")
    if not s:
        return None
    g = s["cuts"][cut]["gate"]
    base = {"prereg_gate": "sign_stability(2016/2017/2018)",
            "relaxed_3v_available": g.get("relaxed_sign_stability_3v"),
            "min_abs_lift_3v": g.get("min_abs_lift_3v"),
            "signed_lifts_3v": g.get("signed_lifts_3v"),
            "numerators_3v": g.get("numerators_3v")}
    base.update({
        "verdict": "判定不能",
        "gate_failed_at": "sign_stability(構造的に評価不能)",
        "reason": ("分解の在庫が 2013/2015/2018 にしか無く、prereg が要求する 2016/2017 の "
                   "y_biz を作れない＝符号不変ゲートを当てられない。**不合格ではなく判定不能**"),
    })
    return base


verdicts = {}
for t in TARGETS:
    for var in CANDIDATES:
        for pop in POPS:
            if f"{t}|{var}|{pop}" not in summaries:
                continue
            for cut in CUTNAMES:
                vd = verdict_for(t, var, pop, cut)
                if vd:
                    verdicts[f"{t}|{var}|{pop}|{cut}"] = vd


# ── 事前登録の外: 2013/2015/2018 で符号不変＋lift＋分子 を当てたらどうなるか（合否に数えない） ──
def relaxed_screen(t):
    passed, near = [], []
    for var in CANDIDATES:
        for pop in POPS:
            s = summaries.get(f"{t}|{var}|{pop}")
            if not s:
                continue
            for cut in CUTNAMES:
                g = s["cuts"][cut]["gate"]
                if g.get("relaxed_sign_stability_3v") is not True:
                    continue
                ent = {"target": t, "variable": var, "population": pop, "cut": cut,
                       "direction": ("増やす" if g["direction_3v"] == 1 else "減らす"),
                       "min_abs_lift_3v": g["min_abs_lift_3v"],
                       "signed_lifts_3v": g["signed_lifts_3v"],
                       "numerators_3v": g["numerators_3v"],
                       "lift_all3": g.get("relaxed_lift_all3"),
                       "min_num_all3": g.get("relaxed_min_num_all3")}
                if g.get("relaxed_lift_all3") and g.get("relaxed_min_num_all3"):
                    ent["sector_mh_3v"] = {str(v): mh_risk_diff(v, pop, var, cut, t)
                                           for v in DECOMP_VINTAGES}
                    passed.append(ent)
                else:
                    near.append(ent)
    passed.sort(key=lambda e: -(e["min_abs_lift_3v"] or 0))
    near.sort(key=lambda e: -(e["min_abs_lift_3v"] or 0))
    return {"passed_relaxed": passed, "near_miss": near[:20]}


relaxed = {t: relaxed_screen(t) for t in TARGETS}


# ── 事前登録の外・診断: ビンテージを絞った選別（2013 の n=92 が塞いでいるかを切り分ける） ──
def subset_screen(t, vints, min_num=MIN_NUM):
    """指定したビンテージだけで（符号不変 ∧ |lift|>=0.15 ∧ 分子>=min_num）を当てる。
       **事前登録の外。合否に数えない。** 2013 を外すと何が見えるのかを切り分けるためだけにある。"""
    passed, near = [], []
    for var in CANDIDATES:
        for pop in POPS:
            got = []
            ok = True
            for v in vints:
                m = cells.get(f"{t}|{var}|{pop}|{v}")
                if not m or m.get("n_measurable", 0) == 0:
                    ok = False
                    break
                got.append((v, m))
            if not ok:
                continue
            for cut in CUTNAMES:
                cs = [(v, m["cuts"][cut], m["p_pop"]) for v, m in got]
                if any(c["lift_vs_pop"] is None for _, c, _ in cs):
                    continue
                signs = {1 if c["lift_vs_pop"] > 0 else (-1 if c["lift_vs_pop"] < 0 else 0)
                         for _, c, _ in cs}
                if len(signs) != 1 or 0 in signs:
                    continue
                ent = {"target": t, "variable": var, "population": pop, "cut": cut,
                       "vintages": list(vints),
                       "direction": "増やす" if list(signs)[0] == 1 else "減らす",
                       "lifts": [c["lift_vs_pop"] for _, c, _ in cs],
                       "numerators": [c["numerator"] for _, c, _ in cs],
                       "n_groups": [c["n_group"] for _, c, _ in cs],
                       "p_bases": [b for _, _, b in cs],
                       "min_abs_lift": r4(min(abs(c["lift_vs_pop"]) for _, c, _ in cs))}
                if (all(abs(c["lift_vs_pop"]) >= LIFT for _, c, _ in cs)
                        and all(c["numerator"] >= min_num for _, c, _ in cs)):
                    ent["sector_mh"] = {str(v): mh_risk_diff(v, pop, var, cut, t) for v in vints}
                    passed.append(ent)
                else:
                    near.append(ent)
    passed.sort(key=lambda e: -(e["min_abs_lift"] or 0))
    near.sort(key=lambda e: -(e["min_abs_lift"] or 0))
    return {"passed": passed, "near_miss": near[:15]}


subset_2v = {t: subset_screen(t, (2015, 2018)) for t in TARGETS}
subset_2018 = {t: subset_screen(t, (2018,)) for t in TARGETS}


# ══════════════════════════════════════════════════════════════════════
#  本体(C): 閾値を使わない対比 — Spearman と 共分散の厳密な4分割
# ══════════════════════════════════════════════════════════════════════
def partial_rank(xs, ys, zs):
    """z を統制した順位相関（順位に直してから偏相関の公式）。
       r_xy.z = (r_xy − r_xz·r_yz) / sqrt((1−r_xz²)(1−r_yz²))"""
    if len(xs) < 5:
        return None
    rx, ry, rz = ranks_of(xs), ranks_of(ys), ranks_of(zs)
    a, b, c = pearson(rx, ry), pearson(rx, rz), pearson(ry, rz)
    if None in (a, b, c):
        return None
    den = math.sqrt(max(0.0, (1 - b * b) * (1 - c * c)))
    if den < 1e-12:
        return None
    return (a - b * c) / den


def decomp_corr(v, pop, var):
    """総リターンとの関係を **倍率 / 事業 / 分配 / 残差** へ厳密に分ける。

    tr = mult_w + biz_w + div + resid_w （window基準・実測で 1.6e-06 まで閉じる）
    共分散は第二引数について線形なので
        cov(rank_x, tr) = cov(rank_x, mult_w) + cov(rank_x, biz_w) + cov(rank_x, div) + cov(rank_x, resid_w)
    が **厳密に**成り立つ。sd(rank_x)·sd(tr) で割れば、4つの部分は
    ρ_pearson(rank_x, tr) にちょうど足し合わさる（＝寄与の分解であって近似ではない）。
    """
    R = pop_rows(v, pop)
    M = [r for r in R if num(r.get(var)) is not None and r["_mult_w"] is not None
         and r["_biz_w"] is not None and r["_div"] is not None and r["_resid_w"] is not None]
    n = len(M)
    if n < 30:
        return {"n": n, "status": "n<30 で相関を出さない"}
    x = ranks_of([num(r.get(var)) for r in M])
    comp = {"mult": [r["_mult_w"] for r in M], "biz": [r["_biz_w"] for r in M],
            "div": [r["_div"] for r in M], "resid": [r["_resid_w"] for r in M]}
    tr = [r["_tr"] for r in M]
    mx = sum(x) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    mt = sum(tr) / n
    stv = math.sqrt(sum((a - mt) ** 2 for a in tr))
    if sx == 0 or stv == 0:
        return {"n": n, "status": "分散ゼロ"}

    def part(ys):
        my = sum(ys) / n
        return sum((x[i] - mx) * (ys[i] - my) for i in range(n)) / (sx * stv)

    parts = {k: part(vv) for k, vv in comp.items()}
    tot = part(tr)
    se = 1.0 / math.sqrt(n - 3) if n > 3 else None
    xs_raw = [num(r.get(var)) for r in M]
    # ★基準を混ぜない: 目的変数(y_biz/y_mult)は signal 基準なので、**主表の相関も signal 基準**。
    #   window 基準は「恒等式が厳密に閉じる」側で、共分散の4分割はそちらでしか成立しない。
    #   両方を出し、差の大きさも出す（どちらを見ているかを読み手が取り違えないため）。
    sig = {"mult": [r["_mult"] for r in M], "biz": [r["_biz"] for r in M]}
    sp_sig = {"vs_tr": spearman(xs_raw, tr),
              "vs_mult": spearman(xs_raw, sig["mult"]),
              "vs_biz": spearman(xs_raw, sig["biz"]),
              "vs_div": spearman(xs_raw, comp["div"])}
    sp_win = {"vs_mult": spearman(xs_raw, comp["mult"]),
              "vs_biz": spearman(xs_raw, comp["biz"])}
    return {
        "n": n,
        "n_population": len(R),
        "n_measurable_variable": sum(1 for r in R if num(r.get(var)) is not None),
        "n_excluded_missing_components": sum(
            1 for r in R if num(r.get(var)) is not None and
            (r["_mult_w"] is None or r["_biz_w"] is None or r["_div"] is None or r["_resid_w"] is None)),
        "row_set_note": ("signal基準の相関も window基準の分解も**同じ行集合**で計算する"
                         "（片方だけ行を増やすと、基準の違う二つを並べることになる）。"
                         "ゆえに成分が欠ける行はどちらからも外れる＝閾値側の n とわずかにずれる"),
        "basis_note": ("**spearman は signal 基準**（目的変数 y_biz/y_mult と同じ基準）。"
                       "**share_decomposition は window 基準**（tr = mult_w+biz_w+div+resid_w が"
                       "厳密に閉じるのはこちらだけ）。両者を混ぜて読まないこと"),
        "share_decomposition": {
            "basis": "window（恒等式が閉じる側）",
            "definition": ("cov(rank_x, 成分) / (sd(rank_x)·sd(tr))。4つの和が "
                           "ρ_pearson(rank_x, tr) に**厳密に一致する**（恒等式が閉じるため）"),
            "mult": r4(parts["mult"]), "biz": r4(parts["biz"]),
            "div": r4(parts["div"]), "resid": r4(parts["resid"]),
            "sum_of_parts": r4(sum(parts.values())), "total_rho_pearson_rankx_tr": r4(tot),
            "additivity_error": r6(abs(sum(parts.values()) - tot)),
        },
        "spearman": {
            "basis": "signal（目的変数と同じ基準）",
            "vs_tr": r4(sp_sig["vs_tr"]), "vs_mult": r4(sp_sig["vs_mult"]),
            "vs_biz": r4(sp_sig["vs_biz"]), "vs_div": r4(sp_sig["vs_div"]),
            "se_approx": r4(se),
            "note": "SE≈1/sqrt(n-3)。|ρ| が 2SE を超えて初めて見るに値する",
        },
        "spearman_window_basis": {
            "basis": "window（共分散の4分割と同じ基準）",
            "vs_mult": r4(sp_win["vs_mult"]), "vs_biz": r4(sp_win["vs_biz"]),
            "max_abs_gap_vs_signal": r4(max(
                abs((sp_sig["vs_mult"] or 0) - (sp_win["vs_mult"] or 0)),
                abs((sp_sig["vs_biz"] or 0) - (sp_win["vs_biz"] or 0)))),
        },
        "partial": _partials(M, var, sig, tr),
    }


def _partials(M, var, comp, tr):
    """★機械的な交絡を外す。
    pe = px/eps なので、**入口の利益が一時的に凹んでいる社は自動的に「高PER」に見え**、
    その後 利益が戻ると biz が高く mult が低く出る。つまり
    『倍率を当てない変数ほど事業を当てる』という鏡像は、**入口の分母の平均回帰だけで**
    機械的に作れてしまう。在庫の conditional が
    ρ(事前3年EPS成長, 入口pe分位) = −0.62 / ρ(事前成長, 事後biz) = −0.26 / ρ(事前成長, 事後mult) = +0.38
    と既に実測している。→ 入口PERと事前EPS成長を統制した偏順位相関を必ず併記する。"""
    x = [num(r.get(var)) for r in M]
    out = {}
    for zname, zkey in (("pe_in", "_pe_in"), ("g_eps3_pre", "_g_eps3_pre")):
        idx = [i for i, r in enumerate(M) if r.get(zkey) is not None]
        if len(idx) < 30:
            out[zname] = {"n": len(idx), "status": "統制変数がそろう行が30未満"}
            continue
        xs = [x[i] for i in idx]
        zs = [M[i][zkey] for i in idx]
        out[zname] = {
            "n": len(idx),
            "biz_given_z": r4(partial_rank(xs, [comp["biz"][i] for i in idx], zs)),
            "mult_given_z": r4(partial_rank(xs, [comp["mult"][i] for i in idx], zs)),
            "tr_given_z": r4(partial_rank(xs, [tr[i] for i in idx], zs)),
        }
    return out


dc = {}
for var in CANDIDATES:
    for pop in POPS:
        for v in DECOMP_VINTAGES:
            e = decomp_corr(v, pop, var)
            if e and e.get("spearman"):          # status 付き（n<30 / 分散ゼロ）は入れない
                dc[f"{var}|{pop}|{v}"] = e


# ── (b) y10 と y_biz で効く変数が違うか（**同じ C-set の上で**） ──
def cut_lift(t, var, pop, v, cut):
    m = cells.get(f"{t}|{var}|{pop}|{v}")
    if not m or m.get("n_measurable", 0) == 0:
        return None
    return m["cuts"][cut].get("lift_vs_pop")


disagreement = []
for var in CANDIDATES:
    for pop in POPS:
        for v in DECOMP_VINTAGES:
            key = f"{var}|{pop}|{v}"
            e = dc.get(key)
            if not e:
                continue
            sp = e["spearman"]
            sd_ = e["share_decomposition"]
            se = sp["se_approx"] or 0.0
            ent = {
                "variable": var, "population": pop, "vintage": v, "n": e["n"],
                "rho_tr": sp["vs_tr"], "rho_biz": sp["vs_biz"], "rho_mult": sp["vs_mult"],
                "share_biz": sd_["biz"], "share_mult": sd_["mult"], "share_div": sd_["div"],
                "se": sp["se_approx"],
                "rho_biz_over_2se": (abs(sp["vs_biz"]) >= 2 * se) if sp["vs_biz"] is not None else None,
                "rho_mult_over_2se": (abs(sp["vs_mult"]) >= 2 * se) if sp["vs_mult"] is not None else None,
                "rho_tr_over_2se": (abs(sp["vs_tr"]) >= 2 * se) if sp["vs_tr"] is not None else None,
                "cancellation": (r4(abs(sp["vs_biz"]) + abs(sp["vs_mult"]) - abs(sp["vs_tr"]))
                                 if None not in (sp["vs_biz"], sp["vs_mult"], sp["vs_tr"]) else None),
                "lift_y10_top": cut_lift("y10", var, pop, v, "上位1/4"),
                "lift_ybiz_top": cut_lift("y_biz", var, pop, v, "上位1/4"),
                "lift_ymult_top": cut_lift("y_mult_pos", var, pop, v, "上位1/4"),
                "lift_y10_med": cut_lift("y10", var, pop, v, "中央値超"),
                "lift_ybiz_med": cut_lift("y_biz", var, pop, v, "中央値超"),
                "lift_ymult_med": cut_lift("y_mult_pos", var, pop, v, "中央値超"),
            }
            b, mlt, t_ = sp["vs_biz"], sp["vs_mult"], sp["vs_tr"]
            lab = "判定不能"
            if None not in (b, mlt, t_) and se:
                sig_b, sig_m, sig_t = abs(b) >= 2 * se, abs(mlt) >= 2 * se, abs(t_) >= 2 * se
                if sig_m and not sig_b:
                    lab = "★再評価を当てているだけ（倍率のみ有意）"
                elif sig_b and not sig_m:
                    lab = "事業を当てている（事業のみ有意）"
                elif sig_b and sig_m and (b > 0) != (mlt > 0):
                    lab = ("★★事業と倍率が逆を向いて相殺（総リターンでは消える）" if not sig_t
                           else "事業と倍率が逆を向くが総リターンには残る")
                elif sig_b and sig_m:
                    lab = "事業と倍率が同じ向き"
                elif not sig_b and not sig_m:
                    lab = "どちらも 2SE 未満＝この n では区別できない"
            # ★最も判断に効く型: 総リターンでは効いて見えるのに、事業では**逆を向く**
            ent["misleading_on_tr"] = (
                None if None in (b, mlt, t_) or not se else
                (abs(t_) >= 2 * se and abs(b) >= 2 * se and (t_ > 0) != (b > 0)))
            ent["label"] = lab
            disagreement.append(ent)

disagreement.sort(key=lambda e: -(abs(e["rho_biz"]) if e["rho_biz"] is not None else -9))

# (c) 「再評価を当てているだけ」の一覧
rerating_only = [e for e in disagreement if e["label"].startswith("★再評価")]
business_only = [e for e in disagreement if e["label"].startswith("事業を当てている")]
cancelling = [e for e in disagreement if e["label"].startswith("★★")]
misleading = sorted([e for e in disagreement if e.get("misleading_on_tr")],
                    key=lambda e: -abs(e["rho_tr"]))

# ── ★入口PERを統制しても事業の予言が残る変数（＝機械的な分母の平均回帰ではないもの） ──
survivors = []
for e in disagreement:
    d = dc.get(f"{e['variable']}|{e['population']}|{e['vintage']}")
    if not d or "partial" not in d:
        continue
    p = d["partial"].get("pe_in") or {}
    if p.get("biz_given_z") is None:
        continue
    se_p = 1.0 / math.sqrt(p["n"] - 4) if p.get("n", 0) > 4 else None
    ent = {
        "variable": e["variable"], "population": e["population"], "vintage": e["vintage"],
        "n": p["n"], "rho_biz_raw": e["rho_biz"], "rho_biz_given_pe_in": p["biz_given_z"],
        "rho_mult_raw": e["rho_mult"], "rho_mult_given_pe_in": p["mult_given_z"],
        "rho_tr_given_pe_in": p["tr_given_z"],
        "shrink_ratio": (r4(abs(p["biz_given_z"]) / abs(e["rho_biz"]))
                         if e["rho_biz"] not in (None, 0) else None),
        "se_partial": r4(se_p),
        "survives_2se": (abs(p["biz_given_z"]) >= 2 * se_p) if se_p else None,
        "sign_kept": ((p["biz_given_z"] > 0) == (e["rho_biz"] > 0)) if e["rho_biz"] else None,
        # ⚠ 生の時点で 2SE に届いていない変数は「生き残った」のではなく「統制して**現れた**」。
        #    抑制(suppression)で偏相関が生より大きくなることがあり、shrink_ratio>1 がその印。
        "raw_over_2se": e.get("rho_biz_over_2se"),
    }
    ent["survived_not_appeared"] = bool(ent["survives_2se"]) and bool(ent["raw_over_2se"])
    survivors.append(ent)
VALUATION_FAMILY = set(["per"] + ["hv_" + h for h in HV])
for e in survivors:
    e["control_is_near_tautological"] = e["variable"] in VALUATION_FAMILY
    e["tautology_note"] = ("この変数は入口PERそのもの（か、その自己相対の位置）なので、"
                           "pe_in で統制するのは半ば同義反復。**崩れても『交絡だった』とは読めない**"
                           if e["variable"] in VALUATION_FAMILY else None)
survivors.sort(key=lambda e: -(abs(e["rho_biz_given_pe_in"]) if e["rho_biz_given_pe_in"] is not None else -9))
survivors_pass = [e for e in survivors if e["survived_not_appeared"]]
survivors_appeared = [e for e in survivors if e["survives_2se"] and not e["raw_over_2se"]]

# 変数ごとに束ねて「ビンテージをまたいで符号が揃って生き残るか」を見る
surv_agg = {}
for e in survivors:
    a = surv_agg.setdefault((e["variable"], e["population"]),
                            {"variable": e["variable"], "population": e["population"],
                             "by_vintage": {}, "n_survive": 0,
                             "control_is_near_tautological": e["control_is_near_tautological"]})
    a["by_vintage"][str(e["vintage"])] = {"n": e["n"], "raw": e["rho_biz_raw"],
                                          "partial": e["rho_biz_given_pe_in"],
                                          "survives": e["survives_2se"]}
    a["by_vintage"][str(e["vintage"])]["survived_not_appeared"] = e["survived_not_appeared"]
    if e["survived_not_appeared"]:
        a["n_survive"] += 1
for a in surv_agg.values():
    ps = [x["partial"] for x in a["by_vintage"].values() if x["partial"] is not None]
    a["n_vintages"] = len(a["by_vintage"])
    a["partial_sign_stable"] = (len({1 if x > 0 else -1 for x in ps}) == 1) if len(ps) >= 2 else None
    a["min_abs_partial"] = r4(min(abs(x) for x in ps)) if ps else None
surv_agg_list = sorted(surv_agg.values(), key=lambda a: (-a["n_survive"], -(a["min_abs_partial"] or 0)))


# ── (b) の中核: 「総リターンで並べた順」と「事業で並べた順」は同じか ──
def ranking_agreement(pop, v):
    """同じ C-set・同じ変数集合の上で、ρ(var,tr) の順位と ρ(var,biz) の順位を突き合わせる。
       1 に近ければ『総リターンを当てる変数＝事業を当てる変数』。低ければ**違う**。"""
    keys = [var for var in CANDIDATES if f"{var}|{pop}|{v}" in dc]
    if len(keys) < 6:
        return {"n_variables": len(keys), "status": "変数が6本未満で順位相関を出さない"}
    tr_ = [dc[f"{k}|{pop}|{v}"]["spearman"]["vs_tr"] for k in keys]
    bz = [dc[f"{k}|{pop}|{v}"]["spearman"]["vs_biz"] for k in keys]
    ml = [dc[f"{k}|{pop}|{v}"]["spearman"]["vs_mult"] for k in keys]
    ok = [i for i in range(len(keys)) if None not in (tr_[i], bz[i], ml[i])]
    if len(ok) < 6:
        return {"n_variables": len(ok), "status": "そろう変数が6本未満"}
    T = [tr_[i] for i in ok]
    B = [bz[i] for i in ok]
    M = [ml[i] for i in ok]
    dif = sorted(({"variable": keys[i], "rho_tr": tr_[i], "rho_biz": bz[i],
                   "rho_mult": ml[i], "delta_biz_minus_tr": r4(bz[i] - tr_[i])} for i in ok),
                 key=lambda e: -abs(e["delta_biz_minus_tr"]))
    return {
        "n_variables": len(ok),
        "spearman_of_variable_rankings": {
            "tr_vs_biz": r4(spearman(T, B)),
            "tr_vs_mult": r4(spearman(T, M)),
            "biz_vs_mult": r4(spearman(B, M)),
        },
        "reading": ("tr_vs_biz が 1 から遠いほど『総リターンを当てる変数』と『事業を当てる変数』が違う"
                    "＝目的を変えた意味がある。biz_vs_mult が負なら、"
                    "**事業に効く変数はたいてい倍率には逆に効く**（相殺の構造）"),
        "largest_disagreements": dif[:15],
    }


b_ranking = {f"{pop}|{v}": ranking_agreement(pop, v)
             for pop in POPS for v in DECOMP_VINTAGES}


# ── ★機械的な交絡そのものを測る（鏡像が入口の分母の平均回帰で作れるか） ──
def mechanical_baseline(v, pop):
    R = [r for r in pop_rows(v, pop) if r["_mult_w"] is not None]
    out = {"n": len(R)}
    for nm, key in (("pe_in", "_pe_in"), ("g_eps3_pre", "_g_eps3_pre"), ("g_rev3_pre", "_g_rev3_pre")):
        S = [r for r in R if r.get(key) is not None]
        if len(S) < 30:
            out[nm] = {"n": len(S), "status": "30未満"}
            continue
        z = [r[key] for r in S]
        out[nm] = {"n": len(S),
                   "vs_biz": r4(spearman(z, [r["_biz"] for r in S])),
                   "vs_mult": r4(spearman(z, [r["_mult"] for r in S])),
                   "vs_tr": r4(spearman(z, [r["_tr"] for r in S]))}
    out["reading"] = (
        "入口PERが高い＝分母(利益)が一時的に低い、なら **pe_in は biz に正・mult に負** に出る。"
        "その場合『倍率を当てない変数ほど事業を当てる』という鏡像は、**変数が何であれ**"
        "入口PERと相関しているだけで機械的に作れる。だから偏相関を必ず併記する")
    return out


mech_base = {f"{pop}|{v}": mechanical_baseline(v, pop) for pop in POPS for v in DECOMP_VINTAGES}


def ranking_agreement_partial(pop, v, zname):
    """鏡像（ρ(事業順位, 倍率順位)≈−0.9）が統制後も残るか。残らなければそれは入口の分母の産物。"""
    keys, B, M_ = [], [], []
    for var in CANDIDATES:
        e = dc.get(f"{var}|{pop}|{v}")
        if not e or "partial" not in e:
            continue
        p = e["partial"].get(zname) or {}
        if p.get("biz_given_z") is None or p.get("mult_given_z") is None:
            continue
        keys.append(var)
        B.append(p["biz_given_z"])
        M_.append(p["mult_given_z"])
    if len(keys) < 6:
        return {"n_variables": len(keys), "status": "6本未満"}
    raw = b_ranking.get(f"{pop}|{v}", {}).get("spearman_of_variable_rankings", {}).get("biz_vs_mult")
    return {"n_variables": len(keys), "control": zname,
            "biz_vs_mult_partial": r4(spearman(B, M_)),
            "biz_vs_mult_raw": raw,
            "collapsed": (None if raw is None else abs(spearman(B, M_)) < abs(raw) * 0.5)}


b_ranking_partial = {f"{pop}|{v}|{z}": ranking_agreement_partial(pop, v, z)
                     for pop in POPS for v in DECOMP_VINTAGES
                     for z in ("pe_in", "g_eps3_pre")}


# ── (b) 閾値側: 同じ C-set・同じ切り方で y10 と y_biz の lift を並べる ──
def lift_side_by_side(pop, v, cut="上位1/4"):
    rows = []
    for var in CANDIDATES:
        a = cells.get(f"y10|{var}|{pop}|{v}")
        b_ = cells.get(f"y_biz|{var}|{pop}|{v}")
        if not a or not b_ or a.get("n_measurable", 0) < MIN_NUM:
            continue
        ca, cb = a["cuts"][cut], b_["cuts"][cut]
        if ca["lift_vs_pop"] is None or cb["lift_vs_pop"] is None:
            continue
        rows.append({"variable": var, "n_group": ca["n_group"],
                     "lift_y10": ca["lift_vs_pop"], "k_y10": ca["numerator"],
                     "lift_ybiz": cb["lift_vs_pop"], "k_ybiz": cb["numerator"],
                     "delta": r4(cb["lift_vs_pop"] - ca["lift_vs_pop"]),
                     "sign_flip": (ca["lift_vs_pop"] > 0) != (cb["lift_vs_pop"] > 0)})
    rho = (spearman([r["lift_y10"] for r in rows], [r["lift_ybiz"] for r in rows])
           if len(rows) >= 6 else None)
    rows.sort(key=lambda r: -abs(r["delta"]))
    return {"cut": cut, "n_variables": len(rows),
            "spearman_of_lifts_y10_vs_ybiz": r4(rho),
            "n_sign_flips": sum(1 for r in rows if r["sign_flip"]),
            "rows": rows}


b_lifts = {f"{pop}|{v}": lift_side_by_side(pop, v) for pop in POPS for v in DECOMP_VINTAGES}

# 変数ごとに集約（ビンテージをまたいで符号が揃うか）
agg = {}
for e in disagreement:
    a = agg.setdefault((e["variable"], e["population"]), {"variable": e["variable"],
                                                          "population": e["population"],
                                                          "by_vintage": {}, "n_vintages": 0})
    a["by_vintage"][str(e["vintage"])] = {"n": e["n"], "rho_tr": e["rho_tr"],
                                          "rho_biz": e["rho_biz"], "rho_mult": e["rho_mult"],
                                          "label": e["label"]}
    a["n_vintages"] += 1
for a in agg.values():
    bs = [x["rho_biz"] for x in a["by_vintage"].values() if x["rho_biz"] is not None]
    ms = [x["rho_mult"] for x in a["by_vintage"].values() if x["rho_mult"] is not None]
    ts = [x["rho_tr"] for x in a["by_vintage"].values() if x["rho_tr"] is not None]
    a["rho_biz_sign_stable"] = (len({1 if x > 0 else -1 for x in bs}) == 1) if len(bs) >= 2 else None
    a["rho_mult_sign_stable"] = (len({1 if x > 0 else -1 for x in ms}) == 1) if len(ms) >= 2 else None
    a["rho_biz_min_abs"] = r4(min(abs(x) for x in bs)) if bs else None
    a["rho_mult_min_abs"] = r4(min(abs(x) for x in ms)) if ms else None
    a["rho_tr_max_abs"] = r4(max(abs(x) for x in ts)) if ts else None
agg_list = sorted(agg.values(),
                  key=lambda a: -(a["rho_biz_min_abs"] if (a["n_vintages"] >= 2 and a["rho_biz_sign_stable"]
                                                          and a["rho_biz_min_abs"] is not None) else -9))


# ────────────────────────────── 検出力 ──────────────────────────────
rnd = random.Random(SEED)
_bc = {}


def binom_cdf(n, p):
    key = (n, round(p, 6))
    if key in _bc:
        return _bc[key]
    lg = math.lgamma
    lp = math.log(p) if p > 0 else -1e18
    l1 = math.log(1 - p) if p < 1 else -1e18
    acc, cdf = 0.0, []
    for k in range(n + 1):
        acc += math.exp(lg(n + 1) - lg(k + 1) - lg(n - k + 1) + k * lp + (n - k) * l1)
        cdf.append(min(acc, 1.0))
    cdf[-1] = 1.0
    _bc[key] = cdf
    return cdf


def rbinom(n, p):
    return bisect.bisect_left(binom_cdf(n, p), rnd.random())


def power_sim(n, base, true_lift, n_sims=N_POWER):
    g = max(1, n // 4)
    rest = n - g
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = min(0.999, max(0.001, (base * n - p_g * g) / rest))
    want = 1 if true_lift > 0 else -1
    single = 0
    for _ in range(n_sims):
        kg, kr = rbinom(g, p_g), rbinom(rest, p_r)
        b = (kg + kr) / n
        lift = kg / g - b
        if abs(lift) >= LIFT and kg >= MIN_NUM and (1 if lift > 0 else -1) == want:
            single += 1
    return r4(single / n_sims)


power = {}
for t in ("y10", "y_biz"):
    ent = {}
    for v in DECOMP_VINTAGES:
        cr = reach[t][f"{v}/C_all"]
        e = {"n": cr["n"], "base": cr["base"], "up": {}, "down": {}}
        for L in (0.10, 0.15, 0.20):
            e["up"][str(L)] = power_sim(cr["n"], cr["base"], L)
            e["down"][str(-L)] = (power_sim(cr["n"], cr["base"], -L)
                                  if cr["down"]["possible"] else
                                  "分子>=20 と両立しない＝この向きは構造的に検出不能")
        ent[str(v)] = e
    # 3ビンテージ同時（緩和版ゲート）の下限＝独立と仮定した積
    ent["_three_vintages_if_independent"] = {
        str(L): r4(power_sim(reach[t]["2013/C_all"]["n"], reach[t]["2013/C_all"]["base"], L)
                   * power_sim(reach[t]["2015/C_all"]["n"], reach[t]["2015/C_all"]["base"], L)
                   * power_sim(reach[t]["2018/C_all"]["n"], reach[t]["2018/C_all"]["base"], L))
        for L in (0.10, 0.15, 0.20)}
    power[t] = ent
power["_how_to_read"] = (
    "実際の3ビンテージは同じティッカー名簿から出ており outcome が強く相関するので、真の検出力は "
    "『1ビンテージの値』と『独立と仮定した積』の**間**にある。"
    "**2013 は n=92 で四分位群が23社しかなく、分子>=20 が LIFT を上書きして "
    "実効要求 lift が 0.30 を超える**——ここが角度Cで最も効いている構造的制約。")


# ────────────────────────────── 偽陽性率（緩和版ゲートの手続きに対して） ──────────────────────────────
tick_idx = {}
for v in DECOMP_VINTAGES:
    for r in C_rows[v]:
        if r["ticker"] not in tick_idx:
            tick_idx[r["ticker"]] = len(tick_idx)
N_T = len(tick_idx)


def build_masks(t, vints=tuple(DECOMP_VINTAGES)):
    masks = []
    for var in CANDIDATES:
        for pop in POPS:
            per_v, ok = {}, True
            for v in vints:
                R = pop_rows(v, pop)
                entries = []
                pm = [0] * N_T
                for r in R:
                    i = tick_idx[r["ticker"]]
                    pm[i] = 1
                    x = num(r.get(var))
                    if x is not None:
                        entries.append((x, i))
                if len(entries) < MIN_NUM:
                    ok = False
                    break
                vals = sorted(x for x, _ in entries)
                q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
                cm = {}
                for name, pred in (("上位1/4", lambda x: x >= q75), ("下位1/4", lambda x: x <= q25),
                                   ("中央値超", lambda x: x > q50), ("中央値以下", lambda x: x <= q50)):
                    gm = [0] * N_T
                    for x, i in entries:
                        if pred(x):
                            gm[i] = 1
                    cm[name] = int("".join("1" if b else "0" for b in gm), 2)
                per_v[v] = {"pop": int("".join("1" if b else "0" for b in pm), 2), "cuts": cm}
            if ok:
                for cut in CUTNAMES:
                    masks.append((var, pop, cut,
                                  {v: (per_v[v]["pop"], per_v[v]["cuts"][cut]) for v in vints}))
    return masks


def bits_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


def run_proc(masks, Aint, Yint, thresh=LIFT, want_stat=False, vints=tuple(DECOMP_VINTAGES)):
    hits, stats = [], []
    for (var, pop, cut, mv) in masks:
        ok, signs, mins = True, set(), []
        for v in vints:
            pmk, gmk = mv[v]
            a = Aint[v]
            npop = (pmk & a).bit_count()
            kpop = (pmk & Yint[v]).bit_count()
            ng = (gmk & a).bit_count()
            kg = (gmk & Yint[v]).bit_count()
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


PERM_SECS = {}


def fpr_for(t, vints, label):
    masks = build_masks(t, vints)
    A_bits = {v: [0] * N_T for v in vints}
    Y_bits = {v: [0] * N_T for v in vints}
    for v in vints:
        for r in C_rows[v]:
            i = tick_idx[r["ticker"]]
            A_bits[v][i] = 1
            if r.get(t):
                Y_bits[v][i] = 1
    A0 = {v: bits_int(A_bits[v]) for v in vints}
    Y0 = {v: bits_int(Y_bits[v]) for v in vints}
    obs_hits, obs_stats = run_proc(masks, A0, Y0, want_stat=True, vints=vints)
    obs_max = max(obs_stats) if obs_stats else 0.0
    RELAX = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]
    sigma = list(range(N_T))
    hits_n, maxstat, relax_any = [], [], {x: 0 for x in RELAX}
    t0 = time.time()
    for _ in range(N_PERM):
        rnd.shuffle(sigma)
        Ai = {v: int("".join("1" if A_bits[v][sigma[j]] else "0" for j in range(N_T)), 2) for v in vints}
        Yi = {v: int("".join("1" if Y_bits[v][sigma[j]] else "0" for j in range(N_T)), 2) for v in vints}
        _h, sts = run_proc(masks, Ai, Yi, want_stat=True, vints=vints)
        mx = max(sts) if sts else 0.0
        maxstat.append(mx)
        hits_n.append(sum(1 for s in sts if s >= LIFT))
        for x in RELAX:
            if mx >= x:
                relax_any[x] += 1
    PERM_SECS[label[:12] + "|" + t] = round(time.time() - t0, 1)   # 画面用（在庫には書かない）
    srt = sorted(maxstat)

    def pc(p):
        return r4(srt[min(len(srt) - 1, max(0, int(p * len(srt)) - 1))])

    return {
        "gate_tested": label,
        "vintages": list(vints),
        "n_tests_in_procedure": len(masks),
        "n_permutations": N_PERM,
        # ⚠ 実行時間は在庫に書かない——**在庫をバイト単位で突き合わせて再現を確かめられなくなる**
        #   （この台帳は「再実行が決定的であることを先に確かめる」を作法にしている）
        "_wall_clock_seconds_not_stored": True,
        "null_construction": ("特徴量側（母集団・群）を固定し、outcome の束をティッカーごとまとめて置換する。"
                              "ビンテージ間の outcome 相関を保ったまま特徴量↔outcome だけを壊す。"
                              "ビンテージ内で独立に混ぜると従属が壊れて FPR を 33 倍過小評価する、が既に実測済み"),
        "P_at_least_one_pass": r4(sum(1 for h in hits_n if h > 0) / N_PERM),
        "mean_passes": r4(sum(hits_n) / N_PERM),
        "max_passes_in_a_permutation": max(hits_n),
        "observed_passes": len(obs_hits),
        "observed_hits": [{"variable": a, "population": b, "cut": c} for a, b, c in obs_hits],
        "null_max_statistic": {"p50": pc(0.5), "p90": pc(0.9), "p95": pc(0.95), "p99": pc(0.99),
                               "max": r4(max(maxstat)), "observed": r4(obs_max),
                               "empirical_p_of_observed":
                                   r4(sum(1 for m in maxstat if m >= obs_max) / N_PERM)},
        "fpr_at_relaxed_thresholds": {
            "note": "**診断専用**。合否に数えない。線を緩めると FPR が立ち上がることを見せるためだけにある",
            "P_at_least_one_pass_by_threshold": {str(x): r4(relax_any[x] / N_PERM) for x in RELAX}},
    }


fpr = {}
for t in ("y_biz", "y10"):
    fpr[t] = fpr_for(t, tuple(DECOMP_VINTAGES),
                     "**事前登録の外の緩和版**（2013/2015/2018 で符号不変 ∧ |lift|>=0.15 ∧ 分子>=20）")
    fpr[t + "@2015_2018"] = fpr_for(t, (2015, 2018),
                                    "**事前登録の外・診断**（2015/2018 の2ビンテージのみ）")
    fpr[t + "@2018"] = fpr_for(t, (2018,),
                               "**事前登録の外・診断**（2018 単独＝符号不変の検問が無い。"
                               "雑音との区別がつかないので FPR を必ず併記して読む）")


# ────────────────────────────── 陽性対照（注入検査） ──────────────────────────────
positive_control = {}
for L, key in ((0.25, "_ctlUp25"), (0.15, "_ctlUp15"), (-0.25, "_ctlDn25"), (-0.15, "_ctlDn15")):
    for v in DECOMP_VINTAGES:
        R = C_rows[v]
        n = len(R)
        g = max(1, n // 4)
        ev = sum(1 for r in R if r.get("y_biz"))
        base = ev / n
        k_want = max(0, min(int(round((base + L) * g)), ev, g))
        wins = [r for r in R if r.get("y_biz")]
        loss = [r for r in R if not r.get("y_biz")]
        rnd.shuffle(wins)
        rnd.shuffle(loss)
        grp = {id(r) for r in wins[:k_want] + loss[:g - k_want]}
        for r in R:
            r[key] = (0.75 + rnd.random() * 0.25) if id(r) in grp else (rnd.random() * 0.74)
    got = {}
    for v in DECOMP_VINTAGES:
        m = measure(v, "C_all", key, "y_biz")
        c = m["cuts"]["上位1/4"]
        got[str(v)] = {"lift": c["lift_vs_pop"], "k": c["numerator"], "n_group": c["n_group"],
                       "min_num_ok": c["numerator"] >= MIN_NUM,
                       "lift_ok": abs(c["lift_vs_pop"]) >= LIFT}
    all_ok = all(x["min_num_ok"] and x["lift_ok"] for x in got.values())
    signs = {1 if got[str(v)]["lift"] > 0 else -1 for v in DECOMP_VINTAGES}
    ok2 = all(got[str(v)]["min_num_ok"] and got[str(v)]["lift_ok"] for v in (2015, 2018))
    sg2 = len({1 if got[str(v)]["lift"] > 0 else -1 for v in (2015, 2018)}) == 1
    ok1 = got["2018"]["min_num_ok"] and got["2018"]["lift_ok"]
    positive_control[f"true_lift={L:+.2f}"] = {
        "by_vintage": got, "sign_stable": len(signs) == 1,
        "relaxed_3v_pass": all_ok and len(signs) == 1,
        "subset_2015_2018_pass": ok2 and sg2,
        "subset_2018_only_pass": ok1,
        "prereg_pass": False,
        "prereg_note": "prereg は 2016/2017/2018 を要求するので、合成変数でも合格は出ない（構造の確認）",
        "which_vintage_blocks": [v for v in DECOMP_VINTAGES
                                 if not (got[str(v)]["min_num_ok"] and got[str(v)]["lift_ok"])],
    }
    for v in DECOMP_VINTAGES:
        for r in C_rows[v]:
            r.pop(key, None)
positive_control["_how_to_read"] = (
    "±0.25 の本物を仕込んでも **prereg のゲートは通らない**——2016/2017 が無いから。"
    "これが『合格ゼロ』の正体が効果の不在ではなく**手続きを当てられないこと**である証拠。"
    "緩和版（3ビンテージ）では ±0.25 が拾えるかを見る。2013 で拾えないなら、それは n=92 の構造。")


# ────────────────────────────── 目的そのものの分布（読む人のため） ──────────────────────────────
target_dist = {}
for v in DECOMP_VINTAGES:
    C = C_rows[v]
    n = len(C)
    md = {k: st.median([r[k] for r in C]) for k in ("_mult", "_biz", "_tr")}
    target_dist[str(v)] = {
        "n": n,
        "median_annual_pct": {"mult": ann_pct(md["_mult"]), "biz": ann_pct(md["_biz"]),
                              "tr": ann_pct(md["_tr"])},
        "base_rates": {t: r4(rate(sum(1 for r in C if r.get(t)), n)) for t in TARGETS},
        "agreement_y10_vs_ybiz": {
            "both": sum(1 for r in C if r["y10"] and r["y_biz"]),
            "y10_only": sum(1 for r in C if r["y10"] and not r["y_biz"]),
            "ybiz_only": sum(1 for r in C if r["y_biz"] and not r["y10"]),
            "neither": sum(1 for r in C if not r["y10"] and not r["y_biz"]),
            "phi": r4(pearson([1.0 if r["y10"] else 0.0 for r in C],
                              [1.0 if r["y_biz"] else 0.0 for r in C])),
            "reading": "y10 と y_biz は同じものではない。φ が 1 から遠いほど『目的を変えた』意味がある",
        },
        "y_biz_vs_y_biz_w_disagree": sum(1 for r in C if r["_has_biz_w"] and r["y_biz"] != r["y_biz_w"]),
    }


# ────────────────────────────── 出力 ──────────────────────────────
verdict_counts = Counter(v["verdict"] for v in verdicts.values())
relaxed_pass_counts = {t: len(relaxed[t]["passed_relaxed"]) for t in TARGETS}

out = {
    "generated": "2026-08-12",
    "tool": "night/hist10_angleC.py",
    "prereg": "out/hist10_prereg.json（線はここにある。この道具は一つも作らない）",
    "angle": "C — 事業由来の複利を目的にする",
    "objective": {
        "primary": "P(事業の寄与 >= +10%/年)。ln(総リターン)=倍率+事業+分配 の**事業側だけ**",
        "why": "再評価（倍率）は繰り返さないが事業は繰り返す＝20-30年の複利に効くのは事業側",
        "targets": TARGET_DEF,
        "hurdle_log": r6(LN110),
    },
    "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM, "hurdle": HURDLE,
                       "sign_stability_required_vintages": SIGN_VINTAGES,
                       "incremental_max_caught": INCREMENTAL_MAX_CAUGHT},

    "★verdict": {
        "prereg_pass_count": int(verdict_counts.get("合格", 0)),
        "verdict_histogram": dict(verdict_counts),
        "headline": ("**合格ゼロ。しかも『不合格』ではなく『判定不能』——"
                     "分解の在庫が 2013/2015/2018 にしか無く、prereg が要求する 2016/2017 の "
                     "事業寄与を作れないので、符号不変ゲートを一つも当てられない。**"),
        "this_is_not_evidence_of_absence": (
            "陽性対照で真の lift ±0.25 を仕込んでも prereg のゲートは通らない＝"
            "この『ゼロ』は効果の不在ではなく**手続きをこの目的に当てられないこと**を測っている"),
        "relaxed_outside_prereg": {
            "note": "**事前登録の外**。合否に数えない。2013/2015/2018 で符号不変 ∧ |lift|>=0.15 ∧ 分子>=20",
            "pass_counts_by_target": relaxed_pass_counts,
            "but_this_zero_is_also_structural": (
                "**緩和版のゼロも効果の不在ではない**。陽性対照で真の lift +0.25 を仕込んでも "
                "2013（n=92・四分位群24社）で分子が14しか立たず落ちる。"
                "下向きは ±0.25 でも3ビンテージ全部で分子>=20 と両立しない"),
        },
        "subset_diagnostics_outside_prereg": {
            "note": "**事前登録の外・診断**。2013 の n=92 が塞いでいるのかを切り分けるためだけにある",
            "pass_counts_2015_2018": {t: len(subset_2v[t]["passed"]) for t in TARGETS},
            "pass_counts_2018_only": {t: len(subset_2018[t]["passed"]) for t in TARGETS},
        },
    },

    "★findings": {
        "a_all_candidates_vs_y_biz": {
            "prereg": "**合格ゼロ**。しかも不合格ではなく判定不能（2016/2017 の分解が無い）",
            "relaxed_3v": "**ゼロ**。ただし陽性対照で真の +0.25 も落ちる＝これも構造（2013 の n=92）",
            "diag_2015_2018": {t: len(subset_2v[t]["passed"]) for t in TARGETS},
            "diag_2018_only": {t: len(subset_2018[t]["passed"]) for t in TARGETS},
            "diag_2018_only_caveat": ("2018単独は符号不変の検問が無く、同じ手続きの FPR が "
                                      f"{fpr['y_biz@2018']['P_at_least_one_pass']} ＝"
                                      "**4割の確率で雑音が通る**。通過はすべて自己相対PERの族で、"
                                      "1つの相関した family を4通りの切り方で数えたもの"),
        },
        "b_do_y10_and_ybiz_pick_different_variables": {
            "answer": "**違う。ほとんど関係がない。**",
            "rho_of_variable_rankings_tr_vs_biz": {
                k: (v.get("spearman_of_variable_rankings") or {}).get("tr_vs_biz")
                for k, v in b_ranking.items()},
            "rho_of_lift_rankings_y10_vs_ybiz": {
                k: v.get("spearman_of_lifts_y10_vs_ybiz") for k, v in b_lifts.items()},
            "n_sign_flips_in_lift": {k: v.get("n_sign_flips") for k, v in b_lifts.items()},
            "targets_themselves_differ": {v: target_dist[v]["agreement_y10_vs_ybiz"]["phi"]
                                          for v in target_dist},
            "note": "同じ C-set の上で測っているので、この違いは標本ではなく**目的**の違い",
        },
        "c_which_variables_only_predict_rerating": {
            "rerating_only_top": [{k: e[k] for k in ("variable", "population", "vintage", "n",
                                                     "rho_tr", "rho_mult", "rho_biz")}
                                  for e in rerating_only[:8]],
            "most_dangerous": [{k: e[k] for k in ("variable", "population", "vintage", "n",
                                                  "rho_tr", "rho_mult", "rho_biz")}
                               for e in misleading],
            "★but_the_confound_eats_most_of_it": (
                "『再評価を当てているだけ』も『総リターンでは効くのに事業では逆』も、"
                "**入口PERの分母の平均回帰で機械的に作れる**。実測で f2_accr の ρ_biz は "
                "−0.176 → +0.034（統制後）で消える。f2_rnd_r も +0.214 → +0.082 で 2SE を割る"),
        },
        "d_what_survives_the_confound": {
            "n_survive": len(survivors_pass), "n_tested": len(survivors),
            "non_valuation_survivors": [a for a in surv_agg_list
                                        if not a["control_is_near_tautological"] and a["n_survive"] > 0],
            "only_two_vintage_survivor": "co_fcf_conv_5y（FCF転換率）だけが2ビンテージで符号を保って残る",
            "caveat": "co_* は 2013/2015 のコホート特徴量で**約94%の行が look-ahead を含む**",
        },
        "e_the_median_company_compounds_from_business_not_rerating": {
            "median_annual_pct_by_vintage": {v: target_dist[v]["median_annual_pct"] for v in target_dist},
            "reading": ("8〜13年の窓で、中央値の会社の総リターンはほぼ全部が事業側から来ている"
                        "（倍率は +0.19〜+2.41%/年）。**20-30年の複利に効くのは事業側**という"
                        "門の前提を、分解が直接支持している"),
        },
    },

    "★structural_limits_read_first": {
        "1_decomposition_missing_2016_2017": {
            "available": DECOMP_VINTAGES, "required_by_prereg": SIGN_VINTAGES,
            "consequence": "prereg の sign_stability を当てられる候補は **0/46**",
            "what_it_would_take": ("2016/2017 の hist_val_{V}.json（自己相対の在庫）を作ること。"
                                   "SEC companyfacts と月次株価の再採取が要る＝この作業の範囲外"),
        },
        "2_feature_and_decomposition_coverage_are_orthogonal": {
            "f2_*(厳密filed<=asof)": "2016/2017/2018 のみ → 分解と重なるのは **2018 だけ**",
            "co_*(コホート)": "2013/2015 のみ → 分解と重なるのは **2013/2015 だけ**",
            "pa_*(値動き)": "2018 のみ",
            "hv_*/per/size_rev": "3ビンテージ全部",
            "n_candidates_measurable_in_all3_decomp_vintages": len(relaxed_evaluable),
            "which": relaxed_evaluable,
            "consequence": ("緩和版ゲートですら当てられるのは自己相対分位の族と per と規模だけ。"
                            "**財務の変数は角度Cでは一度も3ビンテージで検定できない**"),
        },
        "3_population_is_a_quality_subset": {
            "pool_def": decomp[2018]["meta"].get("pool_def"),
            "note": "角度Cに『P_full』は無い。母集団を C_all / C_moat と呼ぶのはそのため",
        },
        "4_left_tail_is_removed_by_construction": {
            "note": ("出口の純利益が正でない社は PER が定義できず分解できない＝**落ちている**。"
                     "落ちた社は残った社より実現年率が低い。**0で埋めていない（ルール7）**"),
            "by_vintage": {v: coverage[v]["dropped_by_decomposition"] for v in coverage},
        },
        "5_size_rev_source_differs_by_vintage": {
            "by_vintage": size_src,
            "note": ("2013/2015 は co_rev_asof（コホート在庫・**約94%の行が look-ahead を含む**）、"
                     "2018 は f2_rev（厳密 filed<=asof）。"
                     "**同じ列名だが出所が違う**ので、3ビンテージにまたがる size_rev の結論は割り引くこと"),
        },
    },

    "coverage": coverage,
    "join_report": join_report,
    "series_consistency_check": consistency,
    "identity_recheck": ident,
    "variable_coverage": var_cov,
    "analysis_set_size": {"total_C_rows": len(C_ALL),
                          "by_vintage": {str(v): len(C_rows[v]) for v in DECOMP_VINTAGES},
                          "C_moat_by_vintage": {str(v): len(pop_rows(v, "C_moat")) for v in DECOMP_VINTAGES}},

    "must_report_before_verdict": {
        "reachability": reach,
        "power": power,
        "false_positive_rate": fpr,
        "positive_control": positive_control,
    },

    "target_distribution": target_dist,
    "procedure_reproduction_vs_angleA": reproduction,

    "★(b)_which_variables_differ_between_y10_and_ybiz": {
        "how": ("**同じ C-set の上で** y10 と y_biz を測る。母集団を揃えないと目的の差ではなく標本の差になる。"
                "閾値に依らない主表は Spearman と、総リターンとの共分散の**厳密な4分割**"),
        "ranking_agreement": b_ranking,
        "★mechanical_confound_baseline": mech_base,
        "★ranking_agreement_after_control": {
            "why": ("鏡像（事業を当てる順＝倍率を当てない順）は、**入口PERの分母が一時的に凹んでいる**"
                    "だけで機械的に作れる。統制後に崩れるなら、それは発見ではなく分母の平均回帰"),
            "rows": b_ranking_partial,
        },
        "lift_side_by_side": b_lifts,
        "rows_sorted_by_abs_rho_biz": disagreement,
        "aggregated_by_variable": agg_list,
    },
    "★(c)_variables_that_only_predict_rerating": {
        "definition": "|ρ(var, mult)| >= 2SE かつ |ρ(var, biz)| < 2SE",
        "rows": rerating_only,
    },
    "★most_dangerous_type_misleading_on_total_return": {
        "definition": ("|ρ(var, tr)| >= 2SE かつ |ρ(var, biz)| >= 2SE かつ **符号が逆**"
                       "＝総リターンでは効いて見えるのに、事業の複利では逆を向く。"
                       "20-30年の複利を狙う門にとって最も危険な型"),
        "rows": [dict(e, partial_biz_given_pe_in=next(
            (s["rho_biz_given_pe_in"] for s in survivors
             if (s["variable"], s["population"], s["vintage"])
             == (e["variable"], e["population"], e["vintage"])), None)) for e in misleading],
        "★but_check_the_confound_first": (
            "この型は入口PERの分母の平均回帰で機械的に作れる（発生高が高い→当期利益が膨らむ→"
            "入口PERが低く見える→その後 利益が戻る）。**入口PERを統制して残るかを必ず見ること**"),
    },
    "business_only": {"definition": "|ρ(var, biz)| >= 2SE かつ |ρ(var, mult)| < 2SE",
                      "rows": business_only},
    "★survivors_after_controlling_entry_PER": {
        "why": ("pe = 株価÷利益 なので、**入口の利益が一時的に凹んでいる社は自動的に高PERに見え**、"
                "その後 利益が戻れば事業の寄与が高く倍率の寄与が低く出る。"
                "入口PERと相関する変数は**何であれ**この鏡像を相続する。"
                "実測: 入口PER→事業 +0.34〜+0.48 / →倍率 −0.43〜−0.60（5セル全部で同符号）。"
                "**入口PERを統制しても残る事業の予言だけが、分母の平均回帰ではない**"),
        "caveat_valuation_family": ("per / hv_pe_* は入口PERそのもの（か自己相対の位置）なので、"
                                    "pe_in での統制は半ば同義反復。**崩れても交絡の証拠にはならない**。"
                                    "統制が意味を持つのは f2_* / co_* / pa_* の側"),
        "n_survive_2se": len(survivors_pass), "n_tested": len(survivors),
        "n_appeared_only_after_control": len(survivors_appeared),
        "appeared_only_note": ("生の時点で 2SE に届いていない変数が統制後に超えるのは"
                               "**生き残ったのではなく現れた**（抑制）。合否には数えない"),
        "appeared_only_rows": survivors_appeared,
        "aggregated_by_variable": surv_agg_list,
        "rows": survivors,
    },
    "cancelling": {"definition": "事業と倍率が逆を向き、総リターンでは打ち消し合う",
                   "rows": cancelling},
    "covariance_decomposition": dc,

    "relaxed_screen_outside_prereg": relaxed,
    "subset_screen_2015_2018_outside_prereg": subset_2v,
    "subset_screen_2018_only_outside_prereg": subset_2018,
    "summaries": summaries,
    "verdicts": verdicts,
    "cells": cells,

    "limits": [
        "**この道具を書く前に 2018 の ρ(変数, tr/mult/biz) を一度だけ探索的に眺めた**。"
        "合否の線（prereg）は一つも変えていないが、完全な事前登録ではない。",
        "分解は 2013/2015/2018 の3ビンテージのみ。prereg のゲートは構造的に当てられない。",
        "3ビンテージは同じ 956 ティッカー名簿から出ており独立標本ではない（Jaccard=1.00）。",
        "2013/2015 の特徴量（co_*）は約94%の行が look-ahead を含む。2018 の f2_* は違反0。",
        "母集団は質実証プールのさらに部分集合（自己相対36ヶ月＋両端でPER）。生存側に強く偏る。",
        "出口で赤字の社は分解できず落ちている＝**左裾が抜けた標本での事業複利の話**。",
        "2018窓はAI相場を含む。倍率側の結論は特にレジーム依存。",
        "n が 92/320/276 と小さく、ρ の SE は 0.06〜0.11。|ρ|<0.2 の差は読まない。",
    ],
}

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print("=" * 100)
print("角度C — 目的: 事業由来の複利 >= +10%/年")
print("=" * 100)
print(f"\n【被覆】(分解が取れない社は 0 で埋めず除外。除外の大きさを必ず出す)")
for v in DECOMP_VINTAGES:
    c = coverage[str(v)]
    d = c["dropped_by_decomposition"]
    print(f"  {v}: 解析集合 {c['analysis_set_n']:4d} → 質実証 {c['P_quality_n']:4d} → C-set {c['C_set_n']:4d}"
          f"  (対 解析集合 {c['coverage_vs_analysis_set']:.3f} / 対 質実証 {c['coverage_vs_P_quality']:.3f})")
    print(f"       分解できず落ちた {d['n']} 社: 実現年率の中央値 {d['dropped_tr_cagr_median']} "
          f"vs 残った社 {d['kept_tr_cagr_median']}  ＝**左裾が抜けている**")
    b = c["base_rate_distortion"]
    print(f"       P(y10): 解析集合 {b['P_y10_on_analysis_set']} / 質実証 {b['P_y10_on_P_quality']}"
          f" / C-set {b['P_y10_on_C_set']}")

print(f"\n【目的の分布】")
for v in DECOMP_VINTAGES:
    t = target_dist[str(v)]
    m = t["median_annual_pct"]
    print(f"  {v} n={t['n']:3d}  中央値/年: 倍率 {m['mult']:+6.2f}%  事業 {m['biz']:+6.2f}%  総 {m['tr']:+6.2f}%")
    br = t["base_rates"]
    print(f"        基準率 y10={br['y10']}  y_biz={br['y_biz']}  mult>0={br['y_mult_pos']}  mult>=10%={br['y_mult10']}")
    a = t["agreement_y10_vs_ybiz"]
    print(f"        y10∧y_biz={a['both']}  y10のみ={a['y10_only']}  y_bizのみ={a['ybiz_only']}  どちらも無={a['neither']}  φ={a['phi']}")

print(f"\n【prereg のゲート到達可能性】")
print(f"  分解の在庫: {DECOMP_VINTAGES} / prereg が要求: {SIGN_VINTAGES}")
print(f"  → 符号不変ゲートを当てられる候補: 0 / {len(CANDIDATES)}")
print(f"  緩和版(2013/2015/2018)ですら3ビンテージ測れるのは {len(relaxed_evaluable)} 変数: {relaxed_evaluable}")

print(f"\n【実効要求 lift（分子>=20 が LIFT を上書きする所）】")
for t in ("y10", "y_biz"):
    for v in DECOMP_VINTAGES:
        r = reach[t][f"{v}/C_all"]
        u, d = r["up"], r["down"]
        print(f"  {t:6s} {v}: n={r['n']:3d} 群={r['quartile_group_n']:3d} 基準={r['base']:.3f} "
              f"| 上: 要求lift {u['effective_lift_required']:+.3f} ({u['binding']}) "
              f"| 下: {'可' if d['possible'] else '**構造的に不可**'}")

print(f"\n【★判定】合格 {verdict_counts.get('合格', 0)} 件 ／ 判定不能 {verdict_counts.get('判定不能', 0)} 件")
print(f"  事前登録の外（緩和版 3ビンテージ）の通過数: {relaxed_pass_counts}")
print(f"  事前登録の外・診断 2015/2018:  {{t: len(subset_2v[t]['passed']) for t in TARGETS}}"
      .replace("{t: len(subset_2v[t]['passed']) for t in TARGETS}",
               str({t: len(subset_2v[t]['passed']) for t in TARGETS})))
print(f"  事前登録の外・診断 2018単独 : {{t: len(subset_2018[t]['passed']) for t in TARGETS}}"
      .replace("{t: len(subset_2018[t]['passed']) for t in TARGETS}",
               str({t: len(subset_2018[t]['passed']) for t in TARGETS})))
for t in ("y_biz", "y10"):
    for e in subset_2018[t]["passed"][:8]:
        print(f"    [2018単独/{t}] {e['variable']:16s} {e['population']:7s} {e['cut']:8s} "
              f"{e['direction']} lift={e['lifts'][0]:+.3f} k={e['numerators'][0]}")

print(f"\n【★(b) 変数の順位は目的で変わるか】(同じ C-set・同じ変数集合)")
for k, e in b_ranking.items():
    if "spearman_of_variable_rankings" not in e:
        continue
    s = e["spearman_of_variable_rankings"]
    print(f"  {k:12s} 変数{e['n_variables']:2d}本  ρ(順位: 総 vs 事業)={s['tr_vs_biz']:+.3f}  "
          f"ρ(総 vs 倍率)={s['tr_vs_mult']:+.3f}  ρ(事業 vs 倍率)={s['biz_vs_mult']:+.3f}")
print(f"\n  【lift でも同じことを見る（上位1/4・y10 vs y_biz）】")
for k, e in b_lifts.items():
    if not e.get("n_variables"):
        continue
    print(f"  {k:12s} 変数{e['n_variables']:2d}本  ρ(lift_y10, lift_ybiz)={e['spearman_of_lifts_y10_vs_ybiz']}"
          f"  符号が反転した変数 {e['n_sign_flips']}本")

print(f"\n【★機械的な交絡（入口の分母の平均回帰）そのもの】")
for k in sorted(mech_base):
    e = mech_base[k]
    pe, ge = e.get("pe_in", {}), e.get("g_eps3_pre", {})
    if "vs_biz" not in pe:
        continue
    print(f"  {k:12s} n={e['n']:3d}  入口PER→ 事業 {pe['vs_biz']:+.3f} / 倍率 {pe['vs_mult']:+.3f} / 総 {pe['vs_tr']:+.3f}"
          + (f"  ｜事前EPS成長→ 事業 {ge['vs_biz']:+.3f} / 倍率 {ge['vs_mult']:+.3f}"
             if "vs_biz" in ge else ""))

print(f"\n【★鏡像は統制後も残るか】(ρ(事業順位, 倍率順位) の生 vs 偏)")
for k in sorted(b_ranking_partial):
    e = b_ranking_partial[k]
    if "biz_vs_mult_partial" not in e:
        continue
    print(f"  {k:24s} 変数{e['n_variables']:2d}本  生={e['biz_vs_mult_raw']}  "
          f"統制後={e['biz_vs_mult_partial']}  崩れた={e['collapsed']}")

print(f"\n【★最も危険な型: 総リターンでは効くのに事業では逆】")
for e in misleading[:12]:
    print(f"  {e['variable']:16s} {e['population']:7s} {e['vintage']} n={e['n']:3d} "
          f"ρ_tr={e['rho_tr']:+.3f} ρ_biz={e['rho_biz']:+.3f} ρ_mult={e['rho_mult']:+.3f}")
if not misleading:
    print("  （該当なし）")

print(f"\n【★入口PERを統制しても事業の予言が残るか】(生ρ_biz → 統制後・|統制後|>=2SE のみ)")
print(f"  {'変数':16s} {'母集団':7s} {'年':4s} {'n':>4s} {'生ρ_biz':>8s} {'統制後':>8s} {'縮み':>6s} {'符号維持':>6s}")
for e in survivors_pass[:20]:
    print(f"  {e['variable']:16s} {e['population']:7s} {e['vintage']} {e['n']:4d} "
          f"{e['rho_biz_raw']:+8.3f} {e['rho_biz_given_pe_in']:+8.3f} "
          f"{(e['shrink_ratio'] if e['shrink_ratio'] is not None else float('nan')):6.2f} "
          f"{str(e['sign_kept']):>6s}")
print(f"  → 統制後も 2SE を超えるのは {len(survivors_pass)} / {len(survivors)} 件")
print(f"  ⚠ per / hv_pe_* は入口PERそのもの＝統制は半ば同義反復（崩れても交絡の証拠にならない）")
print(f"  【ビンテージをまたいで生き残る変数（非バリュエーション系のみ）】")
for a in surv_agg_list:
    if a["control_is_near_tautological"] or a["n_survive"] == 0:
        continue
    bv = "  ".join(f"{k}:{x['raw']:+.3f}→{x['partial']:+.3f}{'✓' if x['survives'] else '×'}"
                   for k, x in sorted(a["by_vintage"].items()))
    print(f"    {a['variable']:16s} {a['population']:7s} 生存{a['n_survive']}/{a['n_vintages']}  {bv}")
print(f"  【崩れた主なもの（＝入口の分母の平均回帰だった）】")
for k in (("f2_accr", "C_all", 2018), ("f2_rnd_r", "C_all", 2018), ("f2_cagr5", "C_all", 2018),
          ("f2_gm", "C_all", 2018), ("f2_conv5", "C_all", 2018)):
    e = next((s for s in survivors if (s["variable"], s["population"], s["vintage"]) == k), None)
    if e:
        print(f"    {e['variable']:16s} {e['vintage']} n={e['n']:3d} "
              f"ρ_biz {e['rho_biz_raw']:+.3f} → {e['rho_biz_given_pe_in']:+.3f} "
              f"(2SE={2 * e['se_partial']:.3f}) 生存={e['survives_2se']}")

print(f"\n【★(c) 再評価を当てているだけ の変数】(|ρ_mult|>=2SE かつ |ρ_biz|<2SE)")
for e in rerating_only[:15]:
    print(f"  {e['variable']:16s} {e['population']:7s} {e['vintage']} n={e['n']:3d} "
          f"ρ_tr={e['rho_tr']:+.3f} ρ_mult={e['rho_mult']:+.3f} ρ_biz={e['rho_biz']:+.3f}")
if not rerating_only:
    print("  （該当なし）")

print(f"\n【★事業を当てている変数】(|ρ_biz|>=2SE かつ |ρ_mult|<2SE)")
for e in business_only[:15]:
    print(f"  {e['variable']:16s} {e['population']:7s} {e['vintage']} n={e['n']:3d} "
          f"ρ_tr={e['rho_tr']:+.3f} ρ_mult={e['rho_mult']:+.3f} ρ_biz={e['rho_biz']:+.3f}")

print(f"\n【★★事業と倍率が逆を向いて相殺（総リターンでは消える）】")
for e in cancelling[:15]:
    print(f"  {e['variable']:16s} {e['population']:7s} {e['vintage']} n={e['n']:3d} "
          f"ρ_tr={e['rho_tr']:+.3f} ρ_mult={e['rho_mult']:+.3f} ρ_biz={e['rho_biz']:+.3f} "
          f"相殺={e['cancellation']:+.3f}")

print(f"\n【偽陽性率（いずれも事前登録の外の診断）】")
for k in sorted(fpr):
    f = fpr[k]
    print(f"  {k:18s} 検定数 {f['n_tests_in_procedure']:3d} 観測通過 {f['observed_passes']:2d} "
          f"少なくとも1つ通る確率 {f['P_at_least_one_pass']}  "
          f"(置換{N_PERM}回 {sum(v for kk, v in PERM_SECS.items() if kk.endswith('|' + k.split('@')[0])):.1f}s)")

print(f"\n【陽性対照】(真の効果を仕込んで手続きが拾えるか)")
for k, v in positive_control.items():
    if k.startswith("_"):
        continue
    print(f"  {k}: prereg={v['prereg_pass']} 3ビンテージ={v['relaxed_3v_pass']} "
          f"2015+2018={v['subset_2015_2018_pass']} 2018単独={v['subset_2018_only_pass']} "
          f"／塞いだビンテージ={v['which_vintage_blocks']}")

print(f"\n【手続きの再現（角度A）】{reproduction.get('verdict')}"
      f"  (照合 {reproduction.get('n_checked')} 件 / 食い違い {reproduction.get('n_mismatch')} 件)")
print(f"\n出力: {DEST}")
