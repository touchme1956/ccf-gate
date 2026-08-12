#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_dst_path.py — 破壊側（目的B: P(tr_cagr <= -15%)）を **値動きの質・資本構成・退場社込みの母集団** から探す。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル）
          out/retro_delisted_secpx_2013.json（退場社の復元・price-only）
          out/retro_cohort_2013.json（退場社に特徴量を join するため。cik で 1:1）
          out/retro_monthly_2013_2018.json（prox_hi の窓を変えて重複検査するため）
          out/hist_wd_dst_uni.json（**姉妹器。重なるセルは必ず一致させる**）
出力    : out/hist_wd_dst_path.json

この道具が受け持つのは3つ。姉妹器 D1(hist_wd_dst_uni) が全候補に同じ手続きを当てたのに対し、
こちらは「D1 の手続きでは構造的に扱えなかった3つの角」を測る。

 (a) **買う前の値動きの質**（pa_*・2018ビンテージのみ）
     ⚠ path は 2018 にしか無い＝**prereg の必須ゲート（2016/2017/2018 の符号不変）を当てられない**。
     したがって **合否は全セル『判定不能』**であり、これは結果ではなく設計から決まっている。
     この道具の仕事は「判定不能と書くこと」ではなく、**判定不能なりに何が測れるか**を出すこと:
       ・姉妹器との一致検査（同じ台帳を見る二つが違うことを言わない・v9.9.65）
       ・自然な線／既存の線での帯（四分位だけでは見えない絶対水準）
       ・size の影・fundamentals の影・irr の影の3つの層別
       ・**重複した変数の検査**（prox_hi は hist_val2 の dd5 の別窓版ではないか）
       ・単一ビンテージで「見つかった」ことが偶然である確率（置換）

 (b) **レバレッジと希薄化**（f2_intcov / f2_netiss_r / f2_cash_r・2016/2017/2018）
     こちらは3ビンテージそろう＝**本当に合否を当てられる唯一の部分**。
     四分位は姉妹器が既に測っているので、この道具の追加は
       ・**帯（絶対水準）** ——ただし線は一つも発明しない。使うのは
         (i) リポジトリに既にある線（night/retro_fin_gate_moat.py:204,213-215 の intcov 帯と線）
         (ii) 自然な零点（netiss_r>0＝純希薄化）
         のみ。cash_r には (i) も (ii) も無いので**帯を作らない**と明記する。
       ・**欠測が語ること** —— f2_intcov は「利息>0 の報告が無ければ欠測」なので、
         欠測群 ≈ 実質無借金／利息ゼロ。**これは四分位では原理的に見えない群**。
       ・**基準の照合** —— f2_intcov と retro_fin_gate_moat.py の intcov が同じ量か。
         同じ式でも錨(FY)の選び方が違えば「基準の違う二つ」になる。

 (c) **退場社を戻した母集団**（2013ビンテージ・price-only）
     ⚠ 基準が違う。panel の tr_cagr は**配当込み**、退場社の復元は**price-only**。
     この二つを割ると「基準の違う二つを割る」型そのもの。だから (c) は
     **最初から最後まで price-only の中だけで完結**させ、配当込みの数字とは並べるだけで割らない。
     出すのは点推定ではなく**挟み込み**（打ち切り762社の返り値は不明なので、
     下端＝全員が破壊でない／上端＝全員が破壊／中間＝非M&Aの打ち切りだけ破壊）。

────────────────────────────────────────────────────────────
★ 結果を見る前に固定したこと（後から動かしていないことの担保）
────────────────────────────────────────────────────────────
1) 解析集合は D1 と同一（has_outcome ∧ window_full）。**揃えることが目的**——
   揃えないと一致検査ができず、二つの検査器が違うことを言い始める。
2) 絶対水準の線は上の (i)(ii) だけ。**新しい定数を一つも導入しない。**
   線の出所（ファイル:行 または 自然な零点）を出力に必ず書く。
3) 四分位の切り方・lift の分母・attainability の式・MH・irr層別・検出力・置換は
   D1 と同じ形。式を書き写しているのは v9.9.65 の例外だが、
   **重なるセルの数字が姉妹器と1桁も違わないことを実測で示す**ことで無害を証明する。
4) path は単一ビンテージなので、**単一ビンテージ用の偽陽性率を別に出す**。
   3ビンテージの符号ゲートが無い手続きは偶然を通しやすい——その値札を先に出す。
5) (c) の群分けに使う変数は 2013 に在る co_* のうち **自然な真偽値**
   （equity_neg / op_all_pos / fcf_all_pos）と、連続量の四分位。
   ここでも新しい線は作らない。

────────────────────────────────────────────────────────────
限界（正直に・結果に関わらず先に書く）
────────────────────────────────────────────────────────────
・path は 2018 の1ビンテージ・窓8.09年の一つだけ。**符号安定性は測れない。**
・path の窓(2013-07→2018-07)と outcome の窓(2018-07→2026-08)は重ならないが、
  **同じ相場の連続した二区間**であり、独立ではない。
・(c) の打ち切り762社のうち非M&Aは限られ、**返り値そのものが不明**な社は挟み込みにしか入らない。
・破壊は稀事象。prereg の線は絶対リスク差0.15。**守る向き（破壊を避ける群）は
  base < 0.15 である限り数学的に到達不能**——D1 が既に記録した構造がここでも効く。
"""
import json, os, math, random
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
D1 = os.path.join(OUT, "hist_wd_dst_uni.json")          # 姉妹器（一致検査の相手）
DEL = os.path.join(OUT, "retro_delisted_secpx_2013.json")
COH13 = os.path.join(OUT, "retro_cohort_2013.json")
MONTHLY = os.path.join(OUT, "retro_monthly_2013_2018.json")
DEST = os.path.join(OUT, "hist_wd_dst_path.json")

# ─── prereg の線（読むだけ・作らない） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]
OUTCOME = "destroy"

SEED = 20260811
N_PERM = 2000
N_POWER = 5000

# ─── (a) 値動きの質 ───
PA = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
PA_VARS = ["pa_" + f for f in PA]
# ─── (b) レバレッジと希薄化 ───
FIN_VARS = ["f2_intcov", "f2_netiss_r", "f2_cash_r"]

MY_VARS = PA_VARS + FIN_VARS

# ══════════════════════════════════════════════════════════════════
# 絶対水準の線。**一つも発明していない。** 出所を必ず書く。
# ══════════════════════════════════════════════════════════════════
ABS_CUTS = {
    "pa_rf5": [
        ("前半CAGR<=0", (lambda x: x <= 0), "前半(2013-07→2018-07)の株価CAGR <= 0",
         "自然な零点。かつ night/retro_midway.py が既に使った線"
         "（CLAUDE.md『前半マイナスの社は後半0.4%/年・49%がマイナス』）"),
    ],
    "pa_worst12": [
        ("最悪12ヶ月<=0", (lambda x: x <= 0), "最悪の12ヶ月ローリングリターン <= 0",
         "自然な零点（一度も12ヶ月でマイナスにならなかったか）"),
    ],
    "pa_upmo_r": [
        ("上げ月<50%", (lambda x: x < 0.5), "月次リターンが正だった月の割合 < 0.5",
         "自然な線 0.5（上げた月が半分に満たない）"),
    ],
    "pa_prox_hi": [
        ("買う時点が5年高値", (lambda x: x >= 0.999), "prox_hi >= 0.999（末値=系列最高値）",
         "自然な線 1.0（高値そのもの）。prox_hi は小数第3位で丸められているので 0.999 で受ける"),
    ],
    # mdd5 / vol_m / r2_log は自然な線も既存の線も無い → **帯を作らない**（下の no_abs_line に理由）
    "f2_intcov": [
        ("intcov<1", (lambda x: x < 1), "営業利益 ÷ 支払利息 < 1（利息を営業利益で払えない）",
         "night/retro_fin_gate_moat.py:215 の既存の線"),
        ("intcov<3", (lambda x: x < 3), "営業利益 ÷ 支払利息 < 3",
         "night/retro_fin_gate_moat.py:214 の既存の線"),
        ("intcov<5", (lambda x: x < 5), "営業利益 ÷ 支払利息 < 5",
         "night/retro_fin_gate_moat.py:213 の既存の線（CLAUDE.md が『intcov<5 で切ると 0.07 vs 0.02』と記録）"),
    ],
    "f2_netiss_r": [
        ("純希薄化(netiss_r>0)", (lambda x: x > 0), "Σ(発行−買戻し)/売上 > 0",
         "自然な零点（発行が買戻しを上回る＝純希薄化）"),
    ],
    # cash_r は自然な線も既存の線も無い → **帯を作らない**
}
NO_ABS_LINE = {
    "pa_mdd5": "最大DDに自然な零点も既存の線も無い（−20%も−50%も発明した定数になる）",
    "pa_vol_m": "月次ボラティリティに自然な線も既存の線も無い",
    "pa_r2_log": "複利の滑らかさ(R²)に自然な線も既存の線も無い（0.5 も 0.8 も発明）",
    "f2_cash_r": "現金/総資産に自然な線も既存の線も無い。**門の nde<=0（純現金）は別の量**"
                 "（分子が純有利子負債・分母がEBITDA）＝借りてくると『基準の違う二つ』になる",
}

# 記述用の帯（合否には使わない。brief の『帯ごとの P(destroy)』はここ）
INTCOV_BANDS = [(-9e9, 1, "intcov<=1"), (1, 3, "1〜3"), (3, 5, "3〜5"),
                (5, 10, "5〜10"), (10, 25, "10〜25"), (25, 9e9, "25超")]
INTCOV_BANDS_SRC = "night/retro_fin_gate_moat.py:204 の帯をそのまま（同じ量・同じ式）"

QUANT_CUTS = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]


# ────────────────────────────── 小道具（D1 と同一式） ──────────────────────────────
def num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


def r4(x):
    return None if x is None else round(x, 4)


def rate(k, n):
    return (k / n) if n else None


def q_at(sorted_vals, q):
    n = len(sorted_vals)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))
    return sorted_vals[k - 1]


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
    nu = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return nu / (dx * dy)


def attainability(n, E, g):
    """群サイズ g のとき、絶対リスク差の線 0.15 に届きうるか（両方向）。D1 と同一式。"""
    if n == 0 or g == 0:
        return None
    base = E / n
    max_pos = min(g, E) / g - base
    need_k_lift = math.ceil((base + LIFT) * g)
    need_k = max(need_k_lift, MIN_NUM)
    pos_ok = need_k <= min(g, E)
    return {
        "group_n": g, "base": r4(base),
        "positive": {"max_attainable_lift": r4(max_pos), "k_needed": need_k,
                     "binding": ("LIFT" if need_k_lift >= MIN_NUM else "MIN_NUM"),
                     "events_total": E,
                     "share_of_all_events_required": (r4(need_k / E) if E else None),
                     "attainable": pos_ok},
        "protective": {"max_attainable_abs_lift": r4(base), "attainable": base >= LIFT,
                       "why": (None if base >= LIFT else
                               f"p_group>=0 ゆえ負のliftの絶対値は base({base:.4f}) を超えられない")},
    }


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
d1 = json.load(open(D1, encoding="utf-8")) if os.path.exists(D1) else None

rows_all = panel["rows"]
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]
by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)


def pop_rows(v, pop):
    return [r for r in by_v[v] if r.get(pop)]


# ─────────── 結果の前に(1): この道具の変数がゲートを当てられるか ───────────
var_cov = {}
for var in MY_VARS:
    cov = {}
    for v in ALL_VINTAGES:
        R = by_v.get(v, [])
        k = sum(1 for r in R if num(r.get(var)) is not None)
        cov[v] = {"n_rows": len(R), "n_measurable": k, "share": r4(rate(k, len(R)))}
    have3 = all(cov[v]["n_measurable"] > 0 for v in SIGN_VINTAGES)
    var_cov[var] = {
        "coverage": cov, "sign_gate_evaluable": have3,
        "note": ("2016/2017/2018 すべてに在る＝符号不変ゲートを当てられる" if have3
                 else "2016/2017/2018 のどれかに存在しない＝**符号不変ゲートは構造的に判定不能**"),
    }

# ─────────── 結果の前に(2): セルの到達可能性（稀事象 × 絶対リスク差） ───────────
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
        else:
            ent["quartile"] = attainability(n, E, max(1, n // 4))
            ok = (ent["quartile"]["positive"]["attainable"]
                  or ent["quartile"]["protective"]["attainable"])
            ent["verdict"] = ("到達可能（四分位・攻める向きのみ）" if ok
                              else "どの向きでも線に届かない＝判定不能")
        cell_reach[f"{v}/{pop}"] = ent


# ────────────────────────────── 中核: 1セル1切り方の測定 ──────────────────────────────
def cut_specs(var, vals):
    """その (var, セル) で当てる切り方。四分位（分布）＋絶対線（発明していない線）。"""
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    specs = [
        ("上位1/4", (lambda x, t=q75: x >= t), f"値 >= {q75!r}(75%点)", "分位"),
        ("下位1/4", (lambda x, t=q25: x <= t), f"値 <= {q25!r}(25%点)", "分位"),
        ("中央値超", (lambda x, t=q50: x > t), f"値 > {q50!r}(中央値)", "分位"),
        ("中央値以下", (lambda x, t=q50: x <= t), f"値 <= {q50!r}(中央値)", "分位"),
    ]
    for name, pred, desc, origin in ABS_CUTS.get(var, []):
        specs.append((name, pred, desc, "絶対線: " + origin))
    return specs


def measure(v, pop, var):
    R = pop_rows(v, pop)
    n_pop = len(R)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in R if r.get(OUTCOME))
    p_pop = rate(k_pop, n_pop)

    M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0) for r in R]
    M = [(x, w) for (x, w) in M if x is not None]
    n_m = len(M)
    if n_m == 0:
        return {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": 0,
                "status": "この母集団でこの変数は一つも測れない＝判定不能"}
    k_m = sum(w for (_, w) in M)
    n_miss, k_miss = n_pop - n_m, k_pop - k_m
    p_miss = rate(k_miss, n_miss) if n_miss else None

    vals = sorted(x for (x, _) in M)
    out = {
        "n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop),
        "n_measurable": n_m, "k_measurable": k_m, "p_measurable": r4(rate(k_m, n_m)),
        "n_missing": n_miss, "k_missing": k_miss, "p_missing": r4(p_miss),
        "missingness_lift": r4(None if p_miss is None else p_miss - rate(k_m, n_m)),
        "distinct": len(set(vals)),
        "q25": q_at(vals, 0.25), "q50": q_at(vals, 0.50), "q75": q_at(vals, 0.75),
        "cuts": {},
    }
    for name, pred, desc, origin in cut_specs(var, vals):
        g = [(x, w) for (x, w) in M if pred(x)]
        gn, gk = len(g), sum(w for _, w in g)
        gp = rate(gk, gn)
        ent = {"cut": desc, "cut_origin": origin, "n_group": gn, "numerator": gk,
               "p_group": r4(gp),
               "lift_vs_pop": r4(None if gp is None else gp - p_pop),
               "lift_vs_measurable": r4(None if gp is None else gp - rate(k_m, n_m)),
               "rr_vs_pop": (r4(gp / p_pop) if (gp is not None and p_pop) else None)}
        if gn:
            share = gn / n_m
            ent["group_share_of_measurable"] = r4(share)
            if origin == "分位" and name in ("上位1/4", "下位1/4") and not (0.10 <= share <= 0.45):
                ent["tie_degenerate"] = True
            at = attainability(n_pop, k_pop, gn)
            if at:
                ent["attainable_positive"] = at["positive"]["attainable"]
                ent["attainable_protective"] = at["protective"]["attainable"]
                ent["max_attainable_lift_positive"] = at["positive"]["max_attainable_lift"]
        out["cuts"][name] = ent

    # 五分位（帯の記述）
    quint = []
    if out["distinct"] >= 5:
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
    out["quintiles"] = quint or None
    out["rank_corr_value_vs_outcome"] = r4(spearman([x for (x, _) in M],
                                                    [float(w) for (_, w) in M]))
    return out


cells = {}
for var in MY_VARS:
    for pop in POPS:
        for v in ALL_VINTAGES:
            m = measure(v, pop, var)
            if m:
                cells[f"{var}|{pop}|{v}"] = m


# ─────────── 変数×母集団の要約（符号安定性が見える形） ───────────
def all_cut_names(var):
    return QUANT_CUTS + [c[0] for c in ABS_CUTS.get(var, [])]


def summarize(var, pop):
    per_v = {v: (cells.get(f"{var}|{pop}|{v}") if
                 (cells.get(f"{var}|{pop}|{v}") or {}).get("n_measurable") else None)
             for v in ALL_VINTAGES}
    out = {"variable": var, "population": pop, "cuts": {}}
    for cut in all_cut_names(var):
        row = {}
        for v in ALL_VINTAGES:
            m = per_v.get(v)
            c = (m or {}).get("cuts", {}).get(cut)
            row[v] = None if not c else {
                "n_group": c["n_group"], "k": c["numerator"], "p_group": c["p_group"],
                "p_base": m["p_pop"], "lift": c["lift_vs_pop"], "rr": c.get("rr_vs_pop"),
                "cut": c["cut"], "cut_origin": c["cut_origin"],
                "attainable_positive": c.get("attainable_positive"),
                "tie_degenerate": c.get("tie_degenerate", False)}
        got3 = [row[v] for v in SIGN_VINTAGES if row.get(v) and row[v]["lift"] is not None]
        gate = {"n_vintages_with_group": len(got3)}
        if len(got3) < 3:
            gate["sign_stability"] = "判定不能（2016/2017/2018 のどれかで測れない・群が空）"
            gate["lift_all3"] = gate["min_num_all3"] = None
        else:
            signs = {(1 if g["lift"] > 0 else (-1 if g["lift"] < 0 else 0)) for g in got3}
            gate["sign_stability"] = (len(signs) == 1 and 0 not in signs)
            gate["lift_all3"] = all(abs(g["lift"]) >= LIFT for g in got3)
            gate["min_num_all3"] = all(g["k"] >= MIN_NUM for g in got3)
            gate["min_abs_lift_3v"] = r4(min(abs(g["lift"]) for g in got3))
            gate["signed_lifts_3v"] = [g["lift"] for g in got3]
            rrs = [g["rr"] for g in got3 if g["rr"] is not None]
            if len(rrs) == 3:
                gate["rr_3v"] = rrs
                gate["min_rr_3v"] = r4(min(rrs))
        row["gate"] = gate
        out["cuts"][cut] = row
    return out


summaries = {}
for var in MY_VARS:
    for pop in POPS:
        s = summarize(var, pop)
        if any(s["cuts"][c].get(v) for c in all_cut_names(var) for v in ALL_VINTAGES):
            summaries[f"{var}|{pop}"] = s


# ────────────────────────────── 層別（ゲート4・5と、影の検査） ──────────────────────────────
def _q_bounds(v, pop, key):
    vals = sorted(x for x in (num(r.get(key)) for r in pop_rows(v, pop)) if x is not None)
    if len(vals) < 20:
        return None
    return [q_at(vals, q) for q in (0.25, 0.50, 0.75)]


def _pred_for(v, pop, var, cut):
    m = cells.get(f"{var}|{pop}|{v}")
    if not m or not m.get("n_measurable"):
        return None
    for name, pred, _d, _o in cut_specs(var, sorted(
            x for x in (num(r.get(var)) for r in pop_rows(v, pop)) if x is not None)):
        if name == cut:
            return pred
    return None


def mh_risk_diff(v, pop, var, cut, stratify="sic2"):
    """Mantel-Haenszel 重み付きリスク差（群 vs 群以外）。D1 と同一式。"""
    R = pop_rows(v, pop)
    if stratify == "sic2":
        skey = lambda r: r.get("sic2")                                    # noqa: E731
    elif stratify in ("size", "f2_opm"):
        key = "size_rev" if stratify == "size" else "f2_opm"
        qs = _q_bounds(v, pop, key)
        if not qs:
            return None

        def skey(r, qs=qs, key=key):
            x = num(r.get(key))
            if x is None:
                return None
            return "%s_q%d" % (stratify, 1 + sum(1 for t in qs if x > t))
    else:
        raise ValueError(stratify)
    pred = _pred_for(v, pop, var, cut)
    if pred is None:
        return None
    M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0, skey(r)) for r in R]
    M = [(x, w, s) for (x, w, s) in M if x is not None and s]
    if len(M) < 20:
        return None
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for (x, w, s) in M:
        d = strata[s]
        if pred(x):
            d[0] += 1; d[1] += w
        else:
            d[2] += 1; d[3] += w
    nu, den, used, drop = 0.0, 0.0, 0, 0
    for s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        w = n1 * n0 / (n1 + n0)
        nu += w * (k1 / n1 - k0 / n0)
        den += w
        used += 1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(nu / den), "strata_used": used, "strata_dropped": drop,
            "stratify": stratify}


def irr_control(v, pop, var, cut):
    R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
    if len(R) < 20:
        return {"status": f"irr の読解がこのビンテージ・母集団で {len(R)} 行しかなく判定不能"}
    pred = _pred_for(v, pop, var, cut)
    M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0, r["irr"]) for r in R]
    M = [t for t in M if t[0] is not None]
    if len(M) < 20 or pred is None:
        return {"status": f"変数×irr がそろう行が {len(M)} で判定不能"}
    rho = spearman([x for x, _, _ in M], [float(i) for _, _, i in M])
    hi = [(x, w) for (x, w, i) in M if i >= 70]
    res = {"n_with_irr": len(M), "corr_var_vs_irr": r4(rho),
           "orthogonal_hint": (None if rho is None else abs(rho) < 0.15)}
    n_ev = sum(w for _, w in hi)
    if len(hi) >= 20 and n_ev >= MIN_NUM:
        g = [w for x, w in hi if pred(x)]
        base = rate(n_ev, len(hi))
        res["irr_ge70"] = {"n": len(hi), "events": n_ev, "base": r4(base), "n_group": len(g),
                           "k": sum(g), "p_group": r4(rate(sum(g), len(g))),
                           "lift": r4(None if not g else rate(sum(g), len(g)) - base)}
    else:
        res["irr_ge70"] = {"status": f"irr>=70 が {len(hi)} 行・破壊事象 {n_ev} 件で判定不能"}
    return res


# ────────────────────────────── 判定（prereg の5条件） ──────────────────────────────
def verdict_for(var, pop, cut):
    s = summaries.get(f"{var}|{pop}")
    if not s:
        return None
    g = s["cuts"][cut]["gate"]
    if not var_cov[var]["sign_gate_evaluable"]:
        return {"verdict": "判定不能", "gate_failed_at": "sign_stability(構造的に評価不能)",
                "reason": "2016/2017/2018 のどれかにこの変数が存在せず、prereg の必須ゲートを当てられない"}
    reach_bad = []
    for v in SIGN_VINTAGES:
        cr = cell_reach.get(f"{v}/{pop}", {})
        if cr.get("n", 0) == 0:
            reach_bad.append(f"{v}:母集団が空"); continue
        if cr.get("events_destroy", 0) < MIN_NUM:
            reach_bad.append(f"{v}:破壊事象{cr.get('events_destroy')}件<5"); continue
        c = (cells.get(f"{var}|{pop}|{v}") or {}).get("cuts", {}).get(cut, {})
        if c.get("attainable_positive") is False and c.get("attainable_protective") is False:
            reach_bad.append(f"{v}:群n={c.get('n_group')}で攻める向きの上限"
                             f"{c.get('max_attainable_lift_positive')}・守る向きの上限{cr.get('base')}"
                             "＝どちらも0.15に届かない")
    if g.get("n_vintages_with_group", 0) < 3:
        return {"verdict": "判定不能", "gate_failed_at": "empty_group",
                "reason": "この切り方で群が空になる／測れないビンテージがある"}
    if reach_bad:
        return {"verdict": "判定不能", "gate_failed_at": "reachability(rare_event)",
                "reason": "破壊は稀事象で、この母集団・この切り方では線に構造的に届かない: "
                          + " / ".join(reach_bad)}
    if g.get("min_num_all3") is False:
        return {"verdict": "不合格", "gate_failed_at": "min_numerator",
                "reason": "分子>=5社 を満たさないビンテージがある"}
    if g.get("lift_all3") is False:
        return {"verdict": "不合格", "gate_failed_at": "lift",
                "reason": f"|lift|>=0.15 を3ビンテージで維持できない（最小 {g.get('min_abs_lift_3v')}）"}
    if g.get("sign_stability") is not True:
        return {"verdict": "不合格", "gate_failed_at": "sign_stability",
                "reason": "2016/2017/2018 で符号が反転する"}
    mh = {str(v): mh_risk_diff(v, pop, var, cut) for v in SIGN_VINTAGES}
    if not all(m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT
               for m in mh.values()):
        return {"verdict": "不合格", "gate_failed_at": "sector_control", "mh": mh,
                "reason": "同一 sic2 内（MH重み付きリスク差）で 0.15 を維持できない"}
    ic = {"2018": irr_control(2018, pop, var, cut)}
    e = ic["2018"]
    if e.get("irr_ge70", {}).get("lift") is None and not e.get("orthogonal_hint"):
        return {"verdict": "判定不能", "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic,
                "reason": "irr>=70 層が薄く層内検定ができず、かつ irr と直交とも言えない"}
    if not (e.get("orthogonal_hint") is True
            or (e.get("irr_ge70", {}).get("lift") is not None
                and abs(e["irr_ge70"]["lift"]) >= LIFT)):
        return {"verdict": "不合格", "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic,
                "reason": "irr>=70 層内で差が消え、かつ irr と直交でもない＝irr の影"}
    return {"verdict": "合格", "reason": "prereg の5条件すべてを満たす", "mh": mh, "irr": ic}


verdicts = {}
for var in MY_VARS:
    for pop in POPS:
        if f"{var}|{pop}" not in summaries:
            continue
        for cut in all_cut_names(var):
            vd = verdict_for(var, pop, cut)
            if vd:
                verdicts[f"{var}|{pop}|{cut}"] = vd
vcounts = Counter(v["verdict"] for v in verdicts.values())
fail_at = Counter(v.get("gate_failed_at") for v in verdicts.values() if v["verdict"] == "不合格")
undet_at = Counter(v.get("gate_failed_at") for v in verdicts.values() if v["verdict"] == "判定不能")


# ══════════════════════════════════════════════════════════════════
# (a) 値動きの質 — 姉妹器との一致検査
# ══════════════════════════════════════════════════════════════════
def cross_check_d1():
    if not d1:
        return {"status": "hist_wd_dst_uni.json が無く一致検査できない"}
    comp, mism = 0, []
    for var in MY_VARS:
        for pop in POPS:
            s_them = (d1.get("summaries") or {}).get(f"{var}|{pop}")
            s_mine = summaries.get(f"{var}|{pop}")
            if not s_them or not s_mine:
                continue
            for cut in QUANT_CUTS:          # 姉妹器が持つのは四分位だけ
                a = s_them["cuts"].get(cut, {})
                b = s_mine["cuts"].get(cut, {})
                for v in ALL_VINTAGES:
                    # ⚠ JSON から読んだ側は辞書キーが**文字列**になっている。
                    #   int で引くと全セルが None＝「不一致168/168」という偽の警報になる（実際に踏んだ）。
                    ra, rb = a.get(str(v)), b.get(v)
                    if ra is None and rb is None:
                        continue
                    comp += 1
                    if ra is None or rb is None:
                        mism.append({"cell": f"{var}|{pop}|{cut}|{v}", "them": ra, "mine": rb})
                        continue
                    for k in ("n_group", "k", "p_group", "p_base", "lift"):
                        if ra.get(k) != rb.get(k):
                            mism.append({"cell": f"{var}|{pop}|{cut}|{v}", "field": k,
                                         "them": ra.get(k), "mine": rb.get(k)})
                            break
    return {"role": "同じパネルを見る二つの検査器が違うことを言わない（v9.9.65）。"
                    "式を書き写している以上、**重なるセルで1桁も違わないこと**が唯一の担保。",
            "cells_compared": comp, "mismatch": len(mism), "examples": mism[:8],
            "status": ("一致" if not mism else "⚠不一致あり——先に道具を疑うこと")}


cross = cross_check_d1()


# ══════════════════════════════════════════════════════════════════
# (a) 重複した変数の検査: prox_hi は hist_val2 の dd5 の別窓版ではないか
# ══════════════════════════════════════════════════════════════════
def prox_window_check():
    """同じ月次系列から窓だけ変えて prox_hi を作り直し、pa_prox_hi との順位相関を出す。

    hist_val2 の dd5 は『asof 時点で自己の36ヶ月高値からどれだけ下か』＝ **1 + dd5 = prox_hi(36m)**。
    per-ticker の dd5 は在庫に無いので直接照合はできないが、同じ量を作り直せば
    「別の名前で同じ列を二度数えていないか」は測れる。
    """
    if not os.path.exists(MONTHLY):
        return {"status": "retro_monthly_2013_2018.json が無く検査不能"}
    mon = json.load(open(MONTHLY, encoding="utf-8"))
    p2018 = {r["ticker"]: r for r in by_v[2018]}
    pairs36, pairs60 = [], []
    made = 0
    for t, ser in mon.items():
        r = p2018.get(t)
        if not r or r.get("pa_prox_hi") is None:
            continue
        px = [p for _ts, p in ser if p and p > 0]
        if len(px) < 45:
            continue
        made += 1
        p36 = px[-36:]
        pairs36.append((r["pa_prox_hi"], p36[-1] / max(p36)))
        pairs60.append((r["pa_prox_hi"], px[-1] / max(px)))
    rho36 = spearman([a for a, _ in pairs36], [b for _, b in pairs36]) if len(pairs36) > 3 else None
    rho60 = spearman([a for a, _ in pairs60], [b for _, b in pairs60]) if len(pairs60) > 3 else None
    return {
        "n_rebuilt": made,
        "identity": "1 + dd5 = prox_hi。hist_val2 の dd5 は36ヶ月窓、pa_prox_hi は約60ヶ月窓。",
        "rank_corr_pa_prox_hi_vs_rebuilt_36m": r4(rho36),
        "rank_corr_pa_prox_hi_vs_rebuilt_60m_selfcheck": r4(rho60),
        "reading": ("60m の自己再現が 1.0 近傍なら再構成は正しい。36m との相関が高いほど "
                    "pa_prox_hi は hist_val2 の dd5 と実質同じ列＝**新しい変数ではない**。"
                    "dd5 は事前登録v2で不合格になっている（ただし結果指標が『元本割れ』で、"
                    "こちらは『恒久毀損』＝別の物差し）。"),
    }


prox_dup = prox_window_check()


# ══════════════════════════════════════════════════════════════════
# (a) 影の検査: size / fundamentals / irr
#     ★path は 2018 の1ビンテージしか無いので合否は判定不能。
#       だが「2018 だけで見れば何が出るのか」と「それが size の影か」は測れる。
# ══════════════════════════════════════════════════════════════════
def rd_unstratified(v, pop, var, cut):
    """群 vs 群以外 の素のリスク差。**MH と同じ土俵**（lift は群 vs 母集団なので土俵が違う）。

    四分位なら lift = (1-g/n)*(p_group - p_rest) ≒ 0.75*RD。
    RD を出さずに MH と lift を並べると『層別で効果が増えた』という誤読を必ず生む。
    """
    pred = _pred_for(v, pop, var, cut)
    if pred is None:
        return None
    M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0) for r in pop_rows(v, pop)]
    M = [(x, w) for x, w in M if x is not None]
    g = [w for x, w in M if pred(x)]
    o = [w for x, w in M if not pred(x)]
    if not g or not o:
        return None
    return r4(sum(g) / len(g) - sum(o) / len(o))


def path_2018_report():
    rep = {}
    for var in PA_VARS:
        for pop in ("P_full", "P_quality"):
            s = summaries.get(f"{var}|{pop}")
            if not s:
                continue
            m = cells.get(f"{var}|{pop}|2018") or {}
            for cut in all_cut_names(var):
                row = s["cuts"][cut].get(2018)
                if not row or row["lift"] is None:
                    continue
                share = (m.get("cuts", {}).get(cut, {}) or {}).get("group_share_of_measurable")
                ent = {"cut": row["cut"], "cut_origin": row["cut_origin"],
                       "n_group": row["n_group"], "k": row["k"], "p_group": row["p_group"],
                       "p_base": row["p_base"], "lift_vs_pop": row["lift"], "rr": row["rr"],
                       "group_share_of_measurable": share,
                       "attainable_positive": row["attainable_positive"]}
                if share is not None and (share > 0.80 or share < 0.02):
                    ent["degenerate_cut"] = ("群が母集団のほぼ全部／ほぼ皆無＝この切り方は情報を持たない"
                                             f"（可測の {share:.1%}）")
                # 影の検査は「分子が5に届く切り方」だけに絞る（届かない切り方の層別は読めない）
                if row["k"] and row["k"] >= MIN_NUM:
                    ent["rd_unstratified"] = rd_unstratified(2018, pop, var, cut)
                    ent["mh_sic2"] = mh_risk_diff(2018, pop, var, cut, "sic2")
                    ent["mh_size"] = mh_risk_diff(2018, pop, var, cut, "size")
                    ent["mh_opm"] = mh_risk_diff(2018, pop, var, cut, "f2_opm")
                    ent["irr"] = irr_control(2018, pop, var, cut)
                    rd = ent["rd_unstratified"]
                    if rd:
                        ent["shrink_vs_unstratified"] = {
                            k: (None if not ent.get(k) or ent[k].get("mh_risk_diff") is None
                                else r4(ent[k]["mh_risk_diff"] / rd))
                            for k in ("mh_sic2", "mh_size", "mh_opm")}
                        ent["shrink_note"] = ("MH ÷ 素のリスク差。1.0 なら層別で何も変わらない、"
                                              "1.0未満なら層が効果の一部を説明している（＝その影）")
                rep[f"{var}|{pop}|{cut}"] = ent
    return rep


path_2018 = path_2018_report()


def path_vs_size_headhead():
    """★D1 で最強だったのは f2_rev/size_rev の下位1/4（小型）。path はその影ではないか。

    ⚠ **ラベルに向きを書かない。** 初版は上位1/4を「値動きが荒い」と書いたが、
    mdd5/worst12/prox_hi/rf5/upmo_r は**値が大きいほど穏やか**なので mdd5 の表が
    正反対の意味に見えていた（自分で踏んだ）。切り方そのものをラベルにする。
    """
    out = {}
    for var in PA_VARS:
        pop = "P_full"
        R = pop_rows(2018, pop)
        M = [(num(r.get(var)), num(r.get("size_rev")), 1 if r.get(OUTCOME) else 0) for r in R]
        M = [t for t in M if t[0] is not None and t[1] is not None]
        if len(M) < 100:
            continue
        vs = sorted(x for x, _, _ in M)
        q25, q75 = q_at(vs, 0.25), q_at(vs, 0.75)
        sq = q_at(sorted(s for _, s, _ in M), 0.25)
        tbl = {}
        for band, pred in (("下位1/4", lambda x: x <= q25),
                           ("中間2/4", lambda x: q25 < x < q75),
                           ("上位1/4", lambda x: x >= q75)):
            for sm, slab in ((True, "小型(size下位1/4)"), (False, "小型でない")):
                g = [w for x, s, w in M if pred(x) and ((s <= sq) == sm)]
                tbl[f"{band}×{slab}"] = {"n": len(g), "k": sum(g), "p": r4(rate(sum(g), len(g)))}
        # 小型でない側だけで見た 上位1/4 vs 下位1/4 の比（size を固定した効果）
        a = tbl["上位1/4×小型でない"]; b = tbl["下位1/4×小型でない"]
        out[var] = {"cut_var_q25": q25, "cut_var_q75": q75, "cut_size_q25": sq,
                    "direction_note": "**この表は向きを解釈しない。**"
                                      f"{var} の値が大きい＝上位1/4 というだけ",
                    "cells": tbl,
                    "within_non_small_top_vs_bottom": {
                        "p_top": a["p"], "k_top": a["k"], "n_top": a["n"],
                        "p_bottom": b["p"], "k_bottom": b["k"], "n_bottom": b["n"],
                        "risk_diff": (None if (a["p"] is None or b["p"] is None)
                                      else r4(a["p"] - b["p"]))}}
    out["_how_to_read"] = (
        "**小型でない側で上位1/4 と下位1/4 の差が消えるなら size の影。残るなら独立した情報。**"
        "n が小さいセルの p は読まない（分子を必ず見る）。")
    return out


path_size_2x2 = path_vs_size_headhead()


def fin_diagnostics():
    """(b) の切り方は合否ゲート1-3で落ちるので verdict_for が MH まで進まない。
    だが**この道具の (b) の中身はそこにある**ので、診断として層別を必ず出す。"""
    rep = {}
    for var in FIN_VARS:
        for pop in ("P_full", "P_quality"):
            s = summaries.get(f"{var}|{pop}")
            if not s:
                continue
            for cut in all_cut_names(var):
                rows = {v: s["cuts"][cut].get(v) for v in SIGN_VINTAGES}
                if not all(rows.values()):
                    continue
                if min(r["k"] for r in rows.values()) < MIN_NUM:
                    continue          # 分子が5に届かない切り方の層別は読めない
                ent = {"lift_by_vintage": {str(v): rows[v]["lift"] for v in SIGN_VINTAGES},
                       "rr_by_vintage": {str(v): rows[v]["rr"] for v in SIGN_VINTAGES},
                       "k_by_vintage": {str(v): rows[v]["k"] for v in SIGN_VINTAGES},
                       "n_by_vintage": {str(v): rows[v]["n_group"] for v in SIGN_VINTAGES},
                       "rd_unstratified": {str(v): rd_unstratified(v, pop, var, cut)
                                           for v in SIGN_VINTAGES},
                       "mh_sic2": {str(v): mh_risk_diff(v, pop, var, cut, "sic2")
                                   for v in SIGN_VINTAGES},
                       "mh_size": {str(v): mh_risk_diff(v, pop, var, cut, "size")
                                   for v in SIGN_VINTAGES},
                       "mh_opm": {str(v): mh_risk_diff(v, pop, var, cut, "f2_opm")
                                  for v in SIGN_VINTAGES},
                       "irr_2018": irr_control(2018, pop, var, cut)}
                rep[f"{var}|{pop}|{cut}"] = ent
    return rep


fin_diag = fin_diagnostics()


def path_correlations():
    """path が size / 収益性 / 規模 とどれだけ同じことを言っているか（重複の検査）。"""
    R = pop_rows(2018, "P_full")
    out = {}
    for var in PA_VARS:
        e = {}
        for other in ("size_rev", "f2_opm", "f2_rev", "f2_cagr5", "f2_intcov", "f2_netiss_r"):
            pairs = [(num(r.get(var)), num(r.get(other))) for r in R]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if len(pairs) >= 50:
                e[other] = {"n": len(pairs),
                            "spearman": r4(spearman([a for a, _ in pairs], [b for _, b in pairs]))}
        out[var] = e
    out["_note"] = "順位相関。|ρ| が大きいほど『別の名前で同じことを測っている』疑いが強い"
    return out


path_corr = path_correlations()


# ══════════════════════════════════════════════════════════════════
# (b) 帯ごとの P(destroy)（記述・合否には使わない）
# ══════════════════════════════════════════════════════════════════
def band_table(var, bands, pops=("P_full", "P_quality"), vints=SIGN_VINTAGES):
    out = {}
    for pop in pops:
        for v in vints:
            R = pop_rows(v, pop)
            M = [(num(r.get(var)), 1 if r.get(OUTCOME) else 0) for r in R]
            M = [(x, w) for x, w in M if x is not None]
            if not M:
                continue
            base = rate(sum(w for _, w in M), len(M))
            rowo = []
            for lo, hi, lab in bands:
                g = [w for x, w in M if lo < x <= hi]
                rowo.append({"band": lab, "n": len(g), "k": sum(g), "p": r4(rate(sum(g), len(g))),
                             "rr_vs_measurable": (r4(rate(sum(g), len(g)) / base)
                                                  if (g and base) else None)})
            out[f"{pop}|{v}"] = {"n_measurable": len(M), "p_measurable": r4(base), "bands": rowo}
    return out


def quintile_table(var, pops=("P_full", "P_quality"), vints=SIGN_VINTAGES + [2018]):
    out = {}
    for pop in pops:
        for v in sorted(set(vints)):
            m = cells.get(f"{var}|{pop}|{v}")
            if not m or not m.get("quintiles"):
                continue
            out[f"{pop}|{v}"] = {"p_measurable": m["p_measurable"], "quintiles": m["quintiles"],
                                 "q25": m["q25"], "q50": m["q50"], "q75": m["q75"]}
    return out


bands_report = {
    "intcov": {"source_of_bands": INTCOV_BANDS_SRC, "table": band_table("f2_intcov", INTCOV_BANDS)},
    "netiss_r_sign": {"source_of_line": "自然な零点（発行>買戻し＝純希薄化）",
                      "table": band_table("f2_netiss_r",
                                          [(-9e9, 0, "netiss_r<=0（純還元）"),
                                           (0, 9e9, "netiss_r>0（純希薄化）")])},
    "cash_r": {"source_of_bands": "**絶対の帯は作らない**（" + NO_ABS_LINE["f2_cash_r"] + "）。"
                                  "分布の帯＝五分位だけを出す",
               "quintiles": quintile_table("f2_cash_r")},
    "path_quintiles": {v: quintile_table(v, vints=[2018]) for v in PA_VARS},
}

# 欠測が語ること（四分位では原理的に見えない群）
missing_report = {}
for var in FIN_VARS:
    ent = {}
    for pop in ("P_full", "P_quality"):
        for v in SIGN_VINTAGES:
            m = cells.get(f"{var}|{pop}|{v}")
            if not m or not m.get("n_measurable"):
                continue
            ent[f"{pop}|{v}"] = {"n_measurable": m["n_measurable"], "p_measurable": m["p_measurable"],
                                 "n_missing": m["n_missing"], "k_missing": m["k_missing"],
                                 "p_missing": m["p_missing"],
                                 "missingness_lift": m["missingness_lift"]}
    missing_report[var] = ent
missing_report["_what_missing_means"] = {
    "f2_intcov": "支払利息が>0 で報告されない年は欠測（retro_features2.py:247『利息ゼロ・タグ無しは欠測』）"
                 "＝欠測群は **実質無借金／利息ゼロ** に強く寄る。"
                 "四分位はこの群を最初から外すので、**欠測を見ないとレバレッジの話が半分になる**。",
    "f2_netiss_r": "窓5年のCF活動が1年でも欠測なら特徴量ごと欠測（retro_features2 の欠測規約）。"
                   "『活動が無い』は0として入るので、欠測群は**無借金の意味を持たない**。",
    "f2_cash_r": "総資産または現金の残高が採れない年＝報告様式の問題。意味のある群ではない。",
    "⚠": "**欠測群は『測れなかった集合』であって『ある性質を持つ集合』ではない。**"
         "intcov だけは規約上ほぼ一意に意味づけできるが、それでも断定はしない。",
}


# ══════════════════════════════════════════════════════════════════
# (b) 基準の照合: f2_intcov と retro_fin_gate_moat.py の intcov は同じ量か
# ══════════════════════════════════════════════════════════════════
def intcov_basis_check():
    """同じ式（営業利益÷支払利息・利息>0のみ）でも、錨(FY)の選び方が違えば別の量になる。

    retro_fin_gate_moat.py は irr>=70 プールに対して自前で採る。**在庫にその値が無い**ので
    照合できるのは『定義の文言』と『分布』まで。数値照合ができないことを、できないと書く。
    """
    src = os.path.join(HERE, "retro_fin_gate_moat.py")
    txt = open(src, encoding="utf-8").read() if os.path.exists(src) else ""
    same_formula = ("op[y] / ie" in txt) and ("ie and ie > 0" in txt)
    dist = {}
    for v in SIGN_VINTAGES:
        vals = sorted(x for x in (num(r.get("f2_intcov")) for r in pop_rows(v, "P_full"))
                      if x is not None)
        if vals:
            dist[v] = {"n": len(vals), "p10": r4(q_at(vals, 0.10)), "q25": r4(q_at(vals, 0.25)),
                       "median": r4(q_at(vals, 0.50)), "q75": r4(q_at(vals, 0.75)),
                       "p90": r4(q_at(vals, 0.90))}
    return {
        "formula_identical_by_source_read": same_formula,
        "formula": "営業利益 ÷ 支払利息（利息>0 の年のみ・∞のもっともらしい代値を作らない）",
        "f2_source": "night/retro_features2.py:247-251",
        "other_source": "night/retro_fin_gate_moat.py:136（同一式）",
        "anchor_difference": "どちらも『期限内の直近FY』を錨にするが、母集団と期限が違う"
                             "（f2 は956社・filed<=asof-07-01／fin_gate_moat は irr>=70 プール）。"
                             "**在庫に per-ticker の値が無いので数値照合はできない。**"
                             "できないことを『一致』と書かない。",
        "f2_intcov_distribution_P_full": dist,
        "verdict": ("式は同一と読めた。帯を借りてよい" if same_formula
                    else "⚠式が違う可能性——帯を借りてはいけない"),
    }


intcov_basis = intcov_basis_check()


# ══════════════════════════════════════════════════════════════════
# 検出力（結果の前に出す）
# ══════════════════════════════════════════════════════════════════
rnd = random.Random(SEED)


def binom(n, p):
    return sum(1 for _ in range(n) if rnd.random() < p)


def power_sim(n, base, true_lift, n_sims=N_POWER, three=True):
    g = max(1, n // 4)
    rest = n - g
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = (base * n - p_g * g) / rest
    if p_r < 0:
        return {"impossible": True,
                "why": (f"群の破壊率を {p_g:.3f} にすると残り {rest} 行の破壊率が負({p_r:.3f})になる＝"
                        "この真の効果はこの base では存在しえない")}
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
    return {"single_vintage": r4(single / n_sims),
            "three_independent": r4(triple / n_sims) if three else None,
            "impossible": False,
            "relative_risk_implied": r4(p_g / base) if base else None,
            "rest_rate_implied": r4(p_r)}


power = {}
for pop, v_ref in (("P_full", 2018), ("P_quality", 2018)):
    cr = cell_reach[f"{v_ref}/{pop}"]
    power[pop] = {"n_used": cr["n"], "base_used": cr["base"], "vintage_used": v_ref,
                  "by_true_lift": {str(L): power_sim(cr["n"], cr["base"], L) for L in (0.15, 0.20, 0.30)}}
power["_how_to_read"] = (
    "path は 2018 の1ビンテージだけなので、**path に効くのは single_vintage のほう**。"
    "three_independent は (b) の3ビンテージ手続き用。"
    "★数字より relative_risk_implied を読むこと——base 8.1% に lift 0.15 を足すのは相対リスク約2.9倍の要求。"
    "P_quality は base 3.0% なので要求 RR が6倍を超え、母集団によっては残り3/4の破壊率が負になり"
    "**そのような効果は存在しえない**（impossible=true）。")


# ══════════════════════════════════════════════════════════════════
# 偽陽性率（置換）— 2つの手続きを別々に測る
#   FPR-3v : (b) の3ビンテージ手続き（符号ゲートあり）
#   FPR-1v : (a) の単一ビンテージ手続き（符号ゲート無し＝**偶然を通しやすい**）
# ══════════════════════════════════════════════════════════════════
def build_masks(vints, vars_, pops):
    tick_idx = {}
    for v in vints:
        for r in by_v[v]:
            if r["ticker"] not in tick_idx:
                tick_idx[r["ticker"]] = len(tick_idx)
    N_T = len(tick_idx)
    A_bits = {v: [0] * N_T for v in vints}
    D_bits = {v: [0] * N_T for v in vints}
    for v in vints:
        for r in by_v[v]:
            i = tick_idx[r["ticker"]]
            A_bits[v][i] = 1
            if r.get(OUTCOME):
                D_bits[v][i] = 1

    def b2i(bits):
        return int("".join("1" if b else "0" for b in bits), 2)

    masks = []
    for var in vars_:
        for pop in pops:
            per_v, ok = {}, True
            for v in vints:
                R = pop_rows(v, pop)
                entries, pm = [], [0] * N_T
                for r in R:
                    i = tick_idx.get(r["ticker"])
                    if i is None:
                        ok = False; break
                    pm[i] = 1
                    x = num(r.get(var))
                    if x is not None:
                        entries.append((x, i))
                if not ok or len(entries) < 20:
                    ok = False; break
                vals = sorted(x for x, _ in entries)
                cm = {}
                for name, pred, _d, _o in cut_specs(var, vals):
                    gm = [0] * N_T
                    for x, i in entries:
                        if pred(x):
                            gm[i] = 1
                    cm[name] = b2i(gm)
                per_v[v] = {"pop": b2i(pm), "cuts": cm}
            if ok:
                for cut in all_cut_names(var):
                    masks.append((var, pop, cut,
                                  {v: (per_v[v]["pop"], per_v[v]["cuts"][cut]) for v in vints}))
    return tick_idx, N_T, A_bits, D_bits, masks, b2i


def fpr_procedure(vints, vars_, pops, label, require_sign):
    tick_idx, N_T, A_bits, D_bits, masks, b2i = build_masks(vints, vars_, pops)
    if not masks:
        return {"status": f"{label}: 検定が構成できない"}

    def run(Aint, Dint, want_stat=False):
        hits, stats = [], []
        for (var, pop, cut, mv) in masks:
            ok, signs, mins = True, set(), []
            for v in vints:
                pm, gm = mv[v]
                a = Aint[v]
                npop = (pm & a).bit_count()
                kpop = (pm & Dint[v]).bit_count()
                ng = (gm & a).bit_count()
                kg = (gm & Dint[v]).bit_count()
                if npop == 0 or ng == 0 or kg < MIN_NUM:
                    ok = False; break
                lift = kg / ng - kpop / npop
                mins.append(abs(lift))
                signs.add(1 if lift > 0 else -1)
            if ok and (not require_sign or len(signs) == 1):
                stats.append(min(mins))
                if min(mins) >= LIFT:
                    hits.append((var, pop, cut))
            else:
                stats.append(0.0)
        return (hits, stats) if want_stat else hits

    A0 = {v: b2i(A_bits[v]) for v in vints}
    D0 = {v: b2i(D_bits[v]) for v in vints}
    obs_hits, obs_stats = run(A0, D0, want_stat=True)
    sigma = list(range(N_T))
    maxstat, nhits = [], []
    for _ in range(N_PERM):
        rnd.shuffle(sigma)
        Ai = {v: int("".join("1" if A_bits[v][sigma[j]] else "0" for j in range(N_T)), 2) for v in vints}
        Di = {v: int("".join("1" if D_bits[v][sigma[j]] else "0" for j in range(N_T)), 2) for v in vints}
        _h, st = run(Ai, Di, want_stat=True)
        maxstat.append(max(st) if st else 0.0)
        nhits.append(sum(1 for s in st if s >= LIFT))
    srt = sorted(maxstat)

    def pc(p):
        return r4(srt[min(len(srt) - 1, max(0, int(p * len(srt)) - 1))])

    obs_max = max(obs_stats) if obs_stats else 0.0
    return {
        "label": label, "vintages": vints, "sign_gate_in_procedure": require_sign,
        "n_tests": len(masks), "n_permutations": N_PERM,
        "null_construction": "特徴量側（母集団・可測・群）は固定し、outcome の束をティッカーごと置換する。"
                             "ビンテージ間の相関・欠測構造を保ったまま特徴量↔outcome だけを壊す。",
        "P_at_least_one_pass": r4(sum(1 for h in nhits if h > 0) / N_PERM),
        "mean_passes_per_permutation": r4(sum(nhits) / N_PERM),
        "observed_passes_gates123": len(obs_hits),
        "observed_hits": [{"variable": a, "population": b, "cut": c} for a, b, c in obs_hits],
        "null_max_statistic": {"p50": pc(0.50), "p90": pc(0.90), "p95": pc(0.95), "p99": pc(0.99),
                               "max": r4(max(maxstat)),
                               "observed_in_real_data": r4(obs_max),
                               "empirical_p_of_observed":
                                   r4(sum(1 for m in maxstat if m >= obs_max) / N_PERM)},
    }


fpr3 = fpr_procedure(SIGN_VINTAGES, FIN_VARS, ["P_full", "P_quality"],
                     "(b) レバレッジ・希薄化 3ビンテージ手続き", True)
fpr1 = fpr_procedure([2018], PA_VARS, ["P_full", "P_quality"],
                     "(a) 値動きの質 単一ビンテージ手続き（符号ゲート無し）", False)


# ══════════════════════════════════════════════════════════════════
# 陽性対照（注入検査）: 「合格ゼロ」という強い結論ほど先に道具を疑う
# ══════════════════════════════════════════════════════════════════
def inject_control(true_lift, pop="P_full", vints=SIGN_VINTAGES):
    """人工の変数を作り、上位1/4 にちょうど true_lift の効果を仕込んで手続きが掴めるか見る。

    ⚠ **仕込む変数は連続でなければならない。**初版は 0/1 の二値を入れたので
    75%点が 0.0 になり『上位1/4』が全行に当たって群＝母集団になり、
    lift が構造的に 0 ＝ 注入が届かず「判定不能」と出た（自分で踏んだ）。
    連続一様乱数にして、その75%点より上を群にする。
    """
    key = "_inj"
    rng = random.Random(SEED + 7)
    for v in vints:
        R = pop_rows(v, pop)
        n = len(R)
        base = rate(sum(1 for r in R if r.get(OUTCOME)), n)
        xs = [rng.random() for _ in range(n)]
        thr = sorted(xs)[max(0, int(math.ceil(0.75 * n)) - 1)]
        g = sum(1 for x in xs if x >= thr)
        p_g = min(0.999, max(0.0, base + true_lift))
        p_r = max(0.0, (base * n - p_g * g) / max(1, n - g))
        for i, r in enumerate(R):
            r[key] = xs[i]
            r["_inj_out"] = 1 if rng.random() < (p_g if xs[i] >= thr else p_r) else 0
    # 一時的に outcome を差し替えて測る
    saved = [(r, r.get(OUTCOME)) for v in vints for r in pop_rows(v, pop)]
    for v in vints:
        for r in pop_rows(v, pop):
            r[OUTCOME] = bool(r.get("_inj_out"))
    ABS_CUTS[key] = []
    var_cov[key] = {"sign_gate_evaluable": True}
    try:
        for v in vints:
            cells[f"{key}|{pop}|{v}"] = measure(v, pop, key)
        summaries[f"{key}|{pop}"] = summarize(key, pop)
        # cell_reach は注入後の outcome で作り直す（同じ規則）
        saved_reach = {}
        for v in vints:
            R = pop_rows(v, pop)
            E = sum(1 for r in R if r.get(OUTCOME))
            saved_reach[f"{v}/{pop}"] = cell_reach[f"{v}/{pop}"]
            cell_reach[f"{v}/{pop}"] = {"n": len(R), "events_destroy": E,
                                        "base": r4(rate(E, len(R))),
                                        "quartile": attainability(len(R), E, max(1, len(R) // 4))}
        vd = verdict_for(key, pop, "上位1/4")
        for k, val in saved_reach.items():
            cell_reach[k] = val
    finally:
        for r, val in saved:
            r[OUTCOME] = val
        for v in vints:
            for r in pop_rows(v, pop):
                r.pop(key, None); r.pop("_inj_out", None)
        cells.pop(f"{key}|{pop}|2016", None); cells.pop(f"{key}|{pop}|2017", None)
        cells.pop(f"{key}|{pop}|2018", None)
        summaries.pop(f"{key}|{pop}", None)
        ABS_CUTS.pop(key, None); var_cov.pop(key, None)
    return {"true_lift_injected": true_lift, "verdict": (vd or {}).get("verdict"),
            "gate_failed_at": (vd or {}).get("gate_failed_at")}


injection = {"note": "人工変数の上位1/4 に真の効果を仕込む。掴めなければ道具の欠陥。",
             "runs": [inject_control(L) for L in (0.15, 0.20, 0.30)]}


# ══════════════════════════════════════════════════════════════════
# (c) 退場社を戻した母集団（2013・price-only）
# ══════════════════════════════════════════════════════════════════
def delisted_bracket():
    dl = json.load(open(DEL, encoding="utf-8"))
    co = json.load(open(COH13, encoding="utf-8"))
    feats = {r["cik"]: r for r in co["rows"]}
    rows = dl["rows"]

    # 対象外（上場株式が無い・既に退場扱い）は母集団から外す＝ファイル自身の扱いに合わせる
    univ = [r for r in rows if r.get("kind") != "対象外"]
    for r in univ:
        r["_f"] = feats.get(r["cik"])

    DEST_LINE = -0.15  # 既存の恒久毀損の定義（新しい定数ではない）

    def split(rs):
        meas = [r for r in rs if r.get("px_cagr") is not None]
        cens = [r for r in rs if r.get("px_cagr") is None]
        return meas, cens

    def readings(rs):
        meas, cens = split(rs)
        k = sum(1 for r in meas if r["px_cagr"] <= DEST_LINE)
        n_m, n_c = len(meas), len(cens)
        # 中間: 非M&Aの打ち切りだけが破壊だったら（CLAUDE.md が使った読み）
        non_ma = sum(1 for r in cens
                     if r.get("exit_kind") not in ("acquired", "going_private", None))
        surv = [r for r in meas if r.get("kind") == "survivor"]
        k_s = sum(1 for r in surv if r["px_cagr"] <= DEST_LINE)
        return {
            "n_measured": n_m, "k_measured": k, "n_censored": n_c,
            "n_censored_non_MA": non_ma,
            "A_survivorのみ": {"n": len(surv), "k": k_s, "p": r4(rate(k_s, len(surv)))},
            "B_退場を戻した(測れた分)": {"n": n_m, "k": k, "p": r4(rate(k, n_m))},
            "下端_打ち切りは全部無事": {"n": n_m + n_c, "k": k, "p": r4(rate(k, n_m + n_c))},
            "中間_非M&Aの打ち切りだけ破壊": {"n": n_m + n_c, "k": k + non_ma,
                                            "p": r4(rate(k + non_ma, n_m + n_c))},
            "上端_打ち切りは全部破壊": {"n": n_m + n_c, "k": k + n_c,
                                        "p": r4(rate(k + n_c, n_m + n_c))},
        }

    out = {
        "basis": dl.get("basis"),
        "⚠basis_warning": "**price-only（配当なし）**。panel の tr_cagr は配当込み。"
                          "この二つを割ると『基準の違う二つを割る』型そのもの。並べるだけで割らない。",
        "destroy_line": DEST_LINE,
        "universe": {"rows_in_file": len(rows), "excluded_対象外": len(rows) - len(univ),
                     "used": len(univ),
                     "kind": dict(Counter(r.get("kind") for r in univ)),
                     "exit_kind_of_censored": dict(Counter(
                         r.get("exit_kind") for r in univ if r.get("px_cagr") is None))},
        "base": {"全社": readings(univ),
                 "質実証": readings([r for r in univ if r.get("quality")])},
    }

    # ファイル自身の left_tail と突き合わせる（同じ台帳を見る二つが違うことを言わない）
    lt = dl.get("left_tail", {})
    chk = []
    for lab, key in (("全社", "全社"), ("質実証", "質実証")):
        them = lt.get(key, {})
        b = them.get("B_退場込み(測定できた分だけ)", {})
        mine = out["base"][lab]["B_退場を戻した(測れた分)"]
        chk.append({"pool": lab, "them_n": b.get("n"), "mine_n": mine["n"],
                    "them_k": b.get("恒久毀損"), "mine_k": mine["k"],
                    "them_p": b.get("恒久毀損率"), "mine_p": mine["p"],
                    "them_upper": them.get("上界(打ち切りが全部 恒久毀損だったら)"),
                    "mine_upper": out["base"][lab]["上端_打ち切りは全部破壊"]["p"],
                    "match": (b.get("n") == mine["n"] and b.get("恒久毀損") == mine["k"])})
    out["cross_check_with_source_file"] = {
        "role": "退場社の在庫が自分で出している left_tail を、独立に組み直して突き合わせる",
        "rows": chk, "status": ("一致" if all(c["match"] for c in chk) else "⚠不一致")}

    # 群ごとの挟み込み（自然な真偽値＋連続量の四分位。新しい線は作らない）
    def group_bracket(name, pred, pool_rows, origin, circular=None):
        G = [r for r in pool_rows if pred(r)]
        Rst = [r for r in pool_rows if not pred(r)]
        if circular:
            return {"name": name, "cut_origin": origin, "n_group_total": len(G),
                    "status": "判定不能（循環）: " + circular}
        if len(G) < 20:
            return {"name": name, "cut_origin": origin, "n_group_total": len(G),
                    "status": f"群が {len(G)} 行で判定不能"}
        rg, rr = readings(G), readings(Rst)
        gm, gc = rg["n_measured"], rg["n_censored"]
        rm, rc = rr["n_measured"], rr["n_censored"]
        # 群 vs 群以外 のリスク差の挟み込み（打ち切りを敵対的に割り当てる）
        lo = (rg["k_measured"] / (gm + gc)) - ((rr["k_measured"] + rc) / (rm + rc)) \
            if (gm + gc) and (rm + rc) else None
        hi = ((rg["k_measured"] + gc) / (gm + gc)) - (rr["k_measured"] / (rm + rc)) \
            if (gm + gc) and (rm + rc) else None
        # 打ち切りを無視した読み（＝生存バイアスが残る点推定）。挟み込みと必ず並べて出す
        naive = (None if not (gm and rm) else
                 r4(rg["k_measured"] / gm - rr["k_measured"] / rm))
        return {"name": name, "cut_origin": origin,
                "n_group_total": len(G), "n_rest_total": len(Rst),
                "group_readings": rg, "rest_readings": rr,
                "risk_diff_naive_measured_only": naive,
                "⚠naive": "打ち切りを母集団から落とした読み＝**生存バイアスが残る**。挟み込みと必ず並べて読む",
                "risk_diff_bracket_group_vs_rest": {"lower": r4(lo), "upper": r4(hi),
                                                    "note": "打ち切りを敵対的に割り当てた両端。"
                                                            "点推定は出さない"},
                "bracket_width": (None if (lo is None or hi is None) else r4(hi - lo)),
                "sign_determined": (None if (lo is None or hi is None)
                                    else (lo > 0 or hi < 0))}

    def qcut(rows_, key, which):
        vals = sorted(v for v in ((r["_f"] or {}).get(key) for r in rows_) if v is not None)
        if len(vals) < 40:
            return None
        q25, q75 = q_at(vals, 0.25), q_at(vals, 0.75)
        if which == "lo":
            return (lambda r: ((r["_f"] or {}).get(key) is not None
                               and (r["_f"] or {}).get(key) <= q25)), f"{key} <= {q25!r}(25%点)"
        return (lambda r: ((r["_f"] or {}).get(key) is not None
                           and (r["_f"] or {}).get(key) >= q75)), f"{key} >= {q75!r}(75%点)"

    groups = {}
    for pool_name, pool in (("全社", univ), ("質実証", [r for r in univ if r.get("quality")])):
        g = []
        for nm, key in (("債務超過(equity_neg)", "equity_neg"),
                        ("営業利益が全年黒字でない", "op_all_pos"),
                        ("FCFが全年黒字でない", "fcf_all_pos")):
            if key == "equity_neg":
                pred = lambda r: bool((r["_f"] or {}).get("equity_neg"))          # noqa: E731
                org = "自然な真偽値（cohort_2013 の equity_neg）"
            else:
                pred = (lambda r, k=key: (r["_f"] or {}).get(k) is False)
                org = f"自然な真偽値（cohort_2013 の {key} が False）"
            # 質実証プールは op_all_pos ∧ fcf_all_pos で定義されている＝この2つは母集団の定義そのもの
            circ = ("この母集団の定義そのもの（質実証＝営業利益全年黒字 ∧ FCF全年黒字）＝構造的に空"
                    if (pool_name == "質実証" and key in ("op_all_pos", "fcf_all_pos")) else None)
            g.append(group_bracket(nm, pred, pool, org, circular=circ))
        for key, lab in (("roic_med5", "ROIC(5年中央値)"), ("fcf_conv_5y", "FCF転換(5年)"),
                         ("opm", "営業利益率"), ("sales_cagr5", "売上5年CAGR")):
            qc = qcut(pool, key, "lo")
            if qc:
                g.append(group_bracket(f"{lab} 下位1/4", qc[0], pool, "分位: " + qc[1]))
        groups[pool_name] = g
    out["group_brackets"] = groups
    # 配当込み（panel）の同ビンテージ基準率を**並べるだけ**（割らない）
    out["side_by_side_with_dividend_inclusive_panel"] = {
        "panel_2013_P_full": {"n": cell_reach["2013/P_full"]["n"],
                              "base": cell_reach["2013/P_full"]["base"],
                              "basis": "配当込み(adjclose)・生存者のみ"},
        "panel_2013_P_quality": {"n": cell_reach["2013/P_quality"]["n"],
                                 "base": cell_reach["2013/P_quality"]["base"],
                                 "basis": "配当込み(adjclose)・生存者のみ"},
        "⚠": "**割らないこと。** 基準が違う（配当の有無）だけでなく母集団も違う"
             "（panel は returns が採れた956社、こちらは2013年の全提出体1806社）。"
             "並べる意味は『生存者のみの基準率どうしは近い』ことの確認だけ",
    }
    out["how_to_read"] = (
        "点推定を出していない。打ち切り(返り値そのものが不明)を敵対的に割り当てた両端だけを出す。"
        "**両端の符号が同じときにだけ『向きが決まった』と言える。**"
        "prereg の5条件はここには当てない——2013 の1ビンテージ・price-only・"
        "outcome の定義が panel と別基準なので、**合否ではなく生存バイアスの幅の記録**である。")
    return out


delisted = delisted_bracket()


# ══════════════════════════════════════════════════════════════════
# 出力
# ══════════════════════════════════════════════════════════════════
top_2018 = sorted(
    [dict(cell=k, **{kk: vv for kk, vv in v.items()
                     if kk in ("cut", "cut_origin", "n_group", "k", "p_group", "p_base",
                               "lift_vs_pop", "rr", "rd_unstratified", "attainable_positive",
                               "degenerate_cut", "shrink_vs_unstratified")})
     for k, v in path_2018.items() if v.get("lift_vs_pop") is not None],
    key=lambda d: -abs(d["lift_vs_pop"]))[:20]

doc = {
    "generated": "2026-08-11",
    "tool": "night/hist_wd_dst_path.py",
    "prereg": {"path": "out/hist_winner_destroyer_prereg.json",
               "objective": "B_破壊 P(実現年率 <= -15%)",
               "pass_line": prereg.get("pass_line"),
               "note": "**この道具は線を一つも作らない。** 絶対水準の切り方も"
                       "『既存の線』か『自然な零点』だけで、出所を各切り方に書いてある"},
    "panel": {"generated": panel.get("generated"), "n_rows": panel.get("n_rows"),
              "analysis_set": "has_outcome ∧ window_full（姉妹器 D1 と同一）"},
    "scope": {
        "(a)値動きの質": {"vars": PA_VARS, "vintages": [2018],
                          "⚠": "2018 のみ＝**prereg の必須ゲート（符号不変）を当てられない＝合否は全セル判定不能**。"
                               "これは結果ではなく設計から決まっている"},
        "(b)レバレッジと希薄化": {"vars": FIN_VARS, "vintages": SIGN_VINTAGES,
                                  "note": "3ビンテージそろう＝**この道具で唯一 合否を当てられる部分**"},
        "(c)退場社を戻した母集団": {"vintage": 2013, "basis": "price-only",
                                    "note": "合否は当てない。生存バイアスの幅（挟み込み）の記録"},
    },
    "analysis_set_size": {str(v): {p: len(pop_rows(v, p)) for p in POPS} for v in ALL_VINTAGES},

    "must_report_before_verdict": {
        "gate_evaluability_by_variable": var_cov,
        "cell_reachability": cell_reach,
        "power": power,
        "false_positive_rate_3vintage": fpr3,
        "false_positive_rate_single_vintage_2018": fpr1,
        "positive_control_injection": injection,
    },

    "cross_check_with_sibling_D1": cross,

    "a_path": {
        "verdict_note": "path の合否は全セル『判定不能（sign_stability 構造的に評価不能）』。"
                        "以下は**事前登録の外・診断専用**——2018 の1ビンテージだけで見た数字と、"
                        "それが size / 業種 / 収益性 / irr の影でないかの層別。",
        "top20_by_abs_lift_2018": top_2018,
        "cells": path_2018,
        "vs_size_2x2": path_size_2x2,
        "correlations_with_other_families": path_corr,
        "duplicate_variable_check_prox_hi_vs_dd5": prox_dup,
        "no_absolute_line": {k: v for k, v in NO_ABS_LINE.items() if k.startswith("pa_")},
        "mh_vs_lift_note": ("lift は群 vs 母集団（群を含む）、MH と rd_unstratified は群 vs 群以外。"
                            "四分位では lift ≒ 0.75×RD。**MH は RD と比べること**——"
                            "lift と比べると『層別で効果が増えた』という誤読を必ず生む。"),
    },

    "b_leverage_dilution": {
        "band_tables": bands_report,
        "missingness": missing_report,
        "stratified_diagnostics": {
            "role": "(b) の切り方はゲート1-3（lift）で落ちるので verdict_for が層別まで進まない。"
                    "だが **(b) の中身はそこにある**ので、事前登録の外・診断として必ず出す。",
            "cells": fin_diag},
        "basis_check_intcov": intcov_basis,
        "no_absolute_line": {k: v for k, v in NO_ABS_LINE.items() if k.startswith("f2_")},
    },

    "c_delisted_bracket_2013": delisted,

    "findings_summary": {
        "⚠これは要約であって新しい測定ではない": "数字はすべて上の節から引いている",
        "合格": vcounts.get("合格", 0),
        "(a)値動きの質": {
            "verdict": "全セル判定不能（path が 2018 にしか無く prereg の必須ゲートを当てられない）",
            "strongest_2018": {
                "cell": "pa_vol_m|P_full|上位1/4",
                "numbers": (path_2018.get("pa_vol_m|P_full|上位1/4") or {}),
                "line": LIFT,
                "reading": "lift は線に届かない。だが素のリスク差・業種調整・size 固定の"
                           "いずれでも残る。**判定不能であって『効果なし』ではない**",
            },
            "buying_at_the_5y_high": {
                "cell": "pa_prox_hi|P_full|買う時点が5年高値",
                "numbers": (path_2018.get("pa_prox_hi|P_full|買う時点が5年高値") or {}),
                "reading": "高値で買うほうが破壊率が**低い**側に出た（この台帳が価格の線について"
                           "5回記録してきた向きと整合）。ただし単一ビンテージ・lift は小さい",
            },
            "is_it_size": "小型でない側だけで見た『上位1/4 vs 下位1/4』の差を "
                          "a_path.vs_size_2x2.*.within_non_small_top_vs_bottom に実数で置いた",
            "is_it_new": "prox_hi は hist_val2 の dd5 の別窓版（順位相関 "
                         + str(prox_dup.get("rank_corr_pa_prox_hi_vs_rebuilt_36m")) + "）＝新しい変数ではない",
        },
        "(b)レバレッジと希薄化": {
            "verdict": "この道具で唯一 合否を当てられる部分。**合格ゼロ**",
            "why": "符号は安定し分子も足りるが、|lift| が 0.15 に届かない（不合格の8件は全て lift ゲート）",
            "strongest": {"cut": "f2_netiss_r|P_full|純希薄化(netiss_r>0)",
                          "lift_161718": (summaries.get("f2_netiss_r|P_full", {})
                                          .get("cuts", {}).get("純希薄化(netiss_r>0)", {})
                                          .get("gate", {}).get("signed_lifts_3v")),
                          "rr_161718": (summaries.get("f2_netiss_r|P_full", {})
                                        .get("cuts", {}).get("純希薄化(netiss_r>0)", {})
                                        .get("gate", {}).get("rr_3v"))},
            "cash_r": "何も分けない（符号すら安定しない）。かつ絶対の帯を作る線が無い",
            "missingness": "intcov の欠測群（≈利息ゼロ/実質無借金）は P_full で3ビンテージとも"
                           "**破壊率が高い側**。ただし P_quality では符号が反転するので断定しない",
        },
        "(c)退場社を戻した母集団": {
            "verdict": "合否は当てない（2013の1ビンテージ・price-only）。生存バイアスの幅の記録",
            "base_bracket_全社": [delisted["base"]["全社"]["下端_打ち切りは全部無事"]["p"],
                                  delisted["base"]["全社"]["上端_打ち切りは全部破壊"]["p"]],
            "base_bracket_質実証": [delisted["base"]["質実証"]["下端_打ち切りは全部無事"]["p"],
                                    delisted["base"]["質実証"]["上端_打ち切りは全部破壊"]["p"]],
            "groups_with_determined_sign": sum(
                1 for gs in delisted["group_brackets"].values() for g in gs
                if g.get("sign_determined")),
            "reading": "**群の差の符号が決まった群はゼロ。** 打ち切り762社の返り値が不明なので"
                       "挟み込みの幅（全社 0.82-1.01 / 質実証 0.46-0.50）が、"
                       "探している効果（lift 0.15）より大きい",
        },
    },

    "verdict_counts": {"by_verdict": dict(vcounts), "fail_gate_histogram": dict(fail_at),
                       "undetermined_gate_histogram": dict(undet_at),
                       "n_pass": vcounts.get("合格", 0)},
    "verdicts": verdicts,
    "summaries": summaries,
    "cells": cells,

    "limitations": [
        "path は 2018 の1ビンテージ・窓8.09年の一つだけ。**符号安定性は測れない＝合否は判定不能**。",
        "path の窓(2013-07→2018-07)と outcome の窓(2018-07→2026-08)は重ならないが、"
        "同じ相場の連続した二区間で独立ではない。",
        "破壊は稀事象（base 1.2-8.1%）。prereg の線は絶対リスク差 0.15 なので、"
        "**守る向き（破壊を避ける群）は base < 0.15 の全セルで数学的に到達不能**。"
        "『保護的な指標は見つからなかった』ではなく『この線では原理的に見つけられない』。",
        "(b) の帯は既存の線を借りているが、**per-ticker の照合はできない**"
        "（retro_fin_gate_moat は自前で採り在庫に残していない）＝式の一致までしか言えない。",
        "(c) は price-only・2013の1ビンテージ・打ち切り762社。"
        "**返り値そのものが不明な社は挟み込みにしか入らない**。",
        "2016/2017/2018 は同じ956ティッカーで窓が重なる＝独立標本ではない（prereg の警告）。",
        "この道具は姉妹器 D1 の式を書き写している（v9.9.65 の例外）。"
        "無害の担保は cross_check_with_sibling_D1 の実測のみ。",
    ],
}

json.dump(doc, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print("解析集合: " + " / ".join(
    f"{v}:{len(by_v[v])}" for v in ALL_VINTAGES))
print("\n■ 姉妹器 D1 との一致検査")
print(f"  {cross.get('status')}  比較セル {cross.get('cells_compared')} / 不一致 {cross.get('mismatch')}")

print("\n■ 結果の前に: ゲートを当てられるか")
for var in MY_VARS:
    c = var_cov[var]
    cov = " ".join(f"{v}:{c['coverage'][v]['n_measurable']}" for v in ALL_VINTAGES)
    print(f"  {var:<14} 符号ゲート {'○' if c['sign_gate_evaluable'] else '×構造的に不能'}  被覆 {cov}")

print("\n■ 結果の前に: セルの到達可能性（破壊は稀事象）")
for k in sorted(cell_reach):
    e = cell_reach[k]
    if e["n"] == 0:
        continue
    q = e.get("quartile") or {}
    print(f"  {k:<18} n={e['n']:<4} 破壊={e['events_destroy']:<3} base={e['base']} "
          f"四分位・攻め={'可' if q.get('positive', {}).get('attainable') else '不可'} "
          f"守り={'可' if q.get('protective', {}).get('attainable') else '不可'}")

print("\n■ 検出力（path は single_vintage を読む）")
for pop in ("P_full", "P_quality"):
    p = power[pop]
    for L, e in p["by_true_lift"].items():
        if e.get("impossible"):
            print(f"  {pop} lift={L}: 存在しえない（{e['why'][:60]}…）")
        else:
            print(f"  {pop} lift={L}: 単一={e['single_vintage']} 3独立={e['three_independent']} "
                  f"要求RR={e['relative_risk_implied']}")

print("\n■ 偽陽性率")
for f in (fpr3, fpr1):
    if f.get("status"):
        print("  " + f["status"]); continue
    nd = f["null_max_statistic"]
    print(f"  {f['label']}")
    print(f"    検定 {f['n_tests']} / 偶然に1本以上通る確率 {f['P_at_least_one_pass']} / "
          f"実データの通過 {f['observed_passes_gates123']}")
    print(f"    帰無の最大統計量 p50={nd['p50']} p95={nd['p95']} p99={nd['p99']} 最大={nd['max']} "
          f"／実データ {nd['observed_in_real_data']} (p={nd['empirical_p_of_observed']})")

print("\n■ 陽性対照（注入）")
for r in injection["runs"]:
    print(f"  真の lift {r['true_lift_injected']} → {r['verdict']} {r.get('gate_failed_at') or ''}")

print("\n■ 判定: " + ", ".join(f"{k} {v}" for k, v in vcounts.items()))
print(f"  不合格の内訳 {dict(fail_at)} / 判定不能の内訳 {dict(undet_at)}")

print("\n■【事前登録の外・診断】(a) 値動きの質・2018 の |lift| 上位10")
print(f"  {'cell':<38}{'n':>5}{'k':>4}{'p':>8}{'lift':>9}{'RD':>9} | MH÷RD  業種/規模/収益性")
for d in top_2018[:10]:
    sh = d.get("shrink_vs_unstratified") or {}
    f = lambda k: ("%.2f" % sh[k]) if sh.get(k) is not None else " -- "   # noqa: E731
    rdv = d.get("rd_unstratified")
    print(f"  {d['cell']:<38}{d['n_group']:>5}{d['k']:>4}{d['p_group']:>8}"
          f"{d['lift_vs_pop']:>+9.4f}"
          + (f"{rdv:>+9.4f}" if rdv is not None else f"{'--':>9}") + " | "
          f"{f('mh_sic2')} / {f('mh_size')} / {f('mh_opm')}"
          + ("   ⚠" + d["degenerate_cut"][:22] if d.get("degenerate_cut") else ""))

print("\n■【診断】(a) path は小型の影か（size 固定・P_full 2018。**ラベルに向きは無い**）")
for var in PA_VARS:
    e = path_size_2x2.get(var)
    if not e:
        continue
    w = e["within_non_small_top_vs_bottom"]
    print(f"  {var:<12} 小型でない側のみ: 上位1/4 {w['p_top']}({w['k_top']}/{w['n_top']}) vs "
          f"下位1/4 {w['p_bottom']}({w['k_bottom']}/{w['n_bottom']}) 差 {w['risk_diff']:+.4f}")
print("  （参考・全6セル）")
for var in ("pa_vol_m", "pa_rf5"):
    e = path_size_2x2.get(var)
    print(f"  {var}: " + "  ".join(f"{k}={v['p']}({v['k']}/{v['n']})" for k, v in e["cells"].items()))

print("\n■【診断】(a) path と他の系統の順位相関（重複の検査）")
for var in PA_VARS:
    e = path_corr[var]
    print(f"  {var:<12} " + " ".join(f"{k}:{v['spearman']:+.3f}" for k, v in e.items()))

print("\n■【診断】(b) 層別（素のリスク差 → MH業種/規模/収益性）")
for k, e in fin_diag.items():
    if "P_full" not in k:
        continue
    rd = e["rd_unstratified"]
    g = lambda d, v: (("%+.4f" % d[v]["mh_risk_diff"]) if d.get(v) and                    # noqa: E731
                      d[v].get("mh_risk_diff") is not None else "   --  ")
    print(f"  {k:<40} RD={' '.join(('%+.4f' % rd[str(v)]) for v in SIGN_VINTAGES)}")
    print(f"  {'':<40} 業種={' '.join(g(e['mh_sic2'], str(v)) for v in SIGN_VINTAGES)}"
          f"  規模={' '.join(g(e['mh_size'], str(v)) for v in SIGN_VINTAGES)}"
          f"  収益={' '.join(g(e['mh_opm'], str(v)) for v in SIGN_VINTAGES)}")

print("\n■ (a) 重複した変数の検査（prox_hi は dd5 の別窓版か）")
print("  " + json.dumps(prox_dup, ensure_ascii=False)[:300])

print("\n■ (b) intcov 帯ごとの P(destroy)  [P_full]")
for key, t in bands_report["intcov"]["table"].items():
    if not key.startswith("P_full"):
        continue
    print(f"  {key} 可測{t['n_measurable']} base={t['p_measurable']}: " +
          " ".join(f"{b['band']}={b['p']}({b['k']}/{b['n']})" for b in t["bands"]))

print("\n■ (b) 純希薄化(netiss_r>0) の P(destroy)")
for key, t in bands_report["netiss_r_sign"]["table"].items():
    print(f"  {key} base={t['p_measurable']}: " +
          " ".join(f"{b['band']}={b['p']}({b['k']}/{b['n']})" for b in t["bands"]))

print("\n■ (b) 欠測が語ること（intcov の欠測 ≈ 実質無借金/利息ゼロ）")
for key, e in missing_report["f2_intcov"].items():
    print(f"  {key} 可測 {e['p_measurable']}({e['n_measurable']}) / "
          f"欠測 {e['p_missing']}({e['k_missing']}/{e['n_missing']}) 差 {e['missingness_lift']:+}")

print("\n■ (c) 退場社を戻した母集団（2013・price-only・挟み込み）")
print(f"  母集団 {delisted['universe']['used']} = " +
      " ".join(f"{k}:{v}" for k, v in delisted["universe"]["kind"].items()))
print(f"  在庫との突合せ: {delisted['cross_check_with_source_file']['status']}")
for pool, e in delisted["base"].items():
    print(f"  {pool}: A survivorのみ {e['A_survivorのみ']['p']}({e['A_survivorのみ']['k']}/{e['A_survivorのみ']['n']})"
          f" → B 退場を戻す {e['B_退場を戻した(測れた分)']['p']}"
          f" → 挟み込み [{e['下端_打ち切りは全部無事']['p']}, {e['上端_打ち切りは全部破壊']['p']}]"
          f" 中間 {e['中間_非M&Aの打ち切りだけ破壊']['p']}")
for pool, gs in delisted["group_brackets"].items():
    print(f"  ── {pool} の群ごと")
    for g in gs:
        if g.get("status"):
            print(f"    {g['name']:<24}: {g['status']}")
            continue
        b = g["risk_diff_bracket_group_vs_rest"]
        print(f"    {g['name']:<24} n={g['n_group_total']:<4} "
              f"打切無視={g['risk_diff_naive_measured_only']:+.4f} "
              f"挟み込み[{b['lower']:+.4f},{b['upper']:+.4f}] 幅{g['bracket_width']:.3f} "
              f"符号確定={'○' if g['sign_determined'] else '×'}")

print(f"\n→ {DEST}")
