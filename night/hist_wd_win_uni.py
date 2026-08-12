#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_win_uni.py — 勝者側（目的A: P(tr_cagr >= +15%)）の単変量探索。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル。特徴量の再実装をしない・v9.9.65）
出力    : out/hist_wd_win_uni.json

────────────────────────────────────────────────────────────
この道具が測るもの（prereg の指示どおり3通り）
────────────────────────────────────────────────────────────
 (a) 五分位の単調性     … 5群の P(win) と、群番号との順位相関・厳密単調かどうか
 (b) 上下1/4の lift     … P(上位1/4) - P(母集団) ／ P(下位1/4) - P(母集団)
 (c) 中央値切り         … P(中央値超) - P(母集団) ／ P(中央値以下) - P(母集団)

合否は prereg の5条件すべて:
  lift>=0.15 ∧ 分子>=5社 ∧ 2016/2017/2018で符号不変 ∧ 業種(sic2)調整後も残る ∧ irr>=70層内でも残る

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定（後から読む人へ）
────────────────────────────────────────────────────────────
1) **解析集合は has_outcome ∧ window_full**。
   パネルの診断が「短窓は年率換算で両裾を機械的に膨らませる」と実測しており
   （2013: DBD 3.01年で tr_cagr 62.5%＝win 判定）、prereg の reachability も window_full で数えてある。
   全行版も base_rates に出すが、判定はしない。

2) **lift の分母（母集団）は prereg の literal どおり「その population 全体」**。
   ただし欠測は population 全体には居るのに群には入りえないので、
   `lift_vs_measurable`（欠測を除いた可測部分集合を分母にした版）も必ず併記し、
   二つが大きく食い違うセルには印を付ける。
   **食い違うとき、それは「変数が分けた」のではなく「その変数を報告している社が違う」ことを見ている。**
   実測で f2_sga_r は被覆58%・f2_intcov 72%・f2_conv5 78%＝この確認なしに読めない。
   ⚠ 線は動かしていない（判定は prereg どおり vs population で行う）。可測版は診断。

3) **同名でも出所が違えば別の変数として扱う**（パネルの名前空間 f2_/co_/pa_/hv_ をそのまま守る）。
   したがって「5ビンテージ並べる」は、co_（2013/2015）と f2_（2016/2017/2018）を
   **概念の対として並べるだけ**で、一つの変数として繋がない。
   パネル自身の crosscheck（co_opm vs f2_opm: spearman 0.971・1pt以内 87.3%）は
   「近い」であって「同じ」ではない。繋いだ瞬間に『基準の違う二つを割る』型になる。

4) **prereg の必須ゲート（2016/2017/2018 の符号不変）は、その3ビンテージ全部に在る変数にしか当てられない。**
   実測で co_*（2013/2015のみ）・pa_*（2018のみ）・hv_*/per（2016/2017に無い）は
   **合否を出す前から構造的に判定不能**。これは「不合格」ではない。
   hist_valuation v1 の教訓（『合否基準が母集団の稀少事象の実数で到達可能か先に数える』）の
   ゲート版で、**結果を見る前に数える**。

5) **タイの扱い**: 四分位は「値 >= 75%点」「値 <= 25%点」で切る（順位で無理に等分しない）。
   低カーディナリティ（distinct<=6: f2_streak_rev/f2_fcfpos5/co_score/bool 群）は
   四分位が潰れるので、実現した群サイズを必ず出し、n/4 から大きく外れたら印を付ける。
   値ごとの P(win) も別に出す（潰れた四分位より情報が多い）。

6) **FPR（偽陽性率）は実データの相関構造を保った置換で測る**。
   2016/2017/2018 は同じ956ティッカーで、outcome の Spearman は 0.845〜0.961＝独立ではない。
   そこで「特徴量側は固定し、**outcome の束（has_outcome/window_full/win の3ビンテージ分）を
   ティッカーごとまとめて置換する**」——これで ①ビンテージ間の outcome 相関 ②特徴量の欠測構造
   ③母集団の定義（P_quality は特徴量側なので不動）をすべて保ったまま、特徴量↔outcome だけを壊せる。

7) **検出力は上下で挟む**。ビンテージが独立という仮定（下限）と、完全に同じ実現という仮定（上限）。
   真の相関はこの間にある。片方だけ出すと、検出力を過小にも過大にも見せられる。
"""
import json, os, sys, math, random
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
DEST = os.path.join(OUT, "hist_wd_win_uni.json")

# ─── prereg の線（この道具は一つも作らない・読むだけ） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]     # prereg: 符号不変は必須・この3つ
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]

SEED = 20260811
N_PERM = 2000
N_POWER = 5000

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

# 概念の対（5ビンテージ横断で「並べる」ため。**繋がない**）
CONCEPT_PAIRS = [
    ("営業利益率",        {2013: "co_opm", 2015: "co_opm", 2016: "f2_opm", 2017: "f2_opm", 2018: "f2_opm"}),
    ("売上5年CAGR",       {2013: "co_sales_cagr5", 2015: "co_sales_cagr5", 2016: "f2_cagr5", 2017: "f2_cagr5", 2018: "f2_cagr5"}),
    ("FCF転換(5年)",      {2013: "co_fcf_conv_5y", 2015: "co_fcf_conv_5y", 2016: "f2_conv5", 2017: "f2_conv5", 2018: "f2_conv5"}),
    ("FCF全年黒字",       {2013: "co_fcf_all_pos", 2015: "co_fcf_all_pos", 2016: "f2_fcfpos5", 2017: "f2_fcfpos5", 2018: "f2_fcfpos5"}),
    ("規模(売上)",        {2013: "size_rev", 2015: "size_rev", 2016: "size_rev", 2017: "size_rev", 2018: "size_rev"}),
]
CONCEPT_PAIR_WARNING = ("co_(2013/2015) と f2_(2016/2017/2018) は別のパイプラインの別の量。"
                        "パネルの crosscheck は co_opm vs f2_opm で spearman 0.971・1pt以内 87.3%＝"
                        "『近い』であって『同じ』ではない。符号の向きを見るためだけに並べてあり、"
                        "一つの変数として lift を通時比較してはいけない。"
                        "FCF全年黒字だけは定義も違う（co_ は bool・f2_fcfpos5 は 0-5 の年数）。")


# ────────────────────────────── 小道具 ──────────────────────────────
def spearman(xs, ys):
    """タイ平均順位のスピアマン。scipy が無いので自前。"""
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
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def q_at(sorted_vals, q):
    """nearest-rank 分位（外挿しない・実在する値だけを閾値にする）。"""
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

# 解析集合（設計1）
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]

by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)

# 各 (vintage, pop) の母集団
def pop_rows(v, pop):
    if pop == "P_full":
        return [r for r in by_v[v] if r.get("P_full")]
    if pop == "P_quality":
        return [r for r in by_v[v] if r.get("P_quality")]
    if pop == "P_moat":
        return [r for r in by_v[v] if r.get("P_moat")]
    raise ValueError(pop)


# ─────────── 結果を見る前に出す(1): ゲート自体の到達可能性 ───────────
var_vintage_cov = {}
for var in CANDIDATES:
    cov = {}
    for v in ALL_VINTAGES:
        R = by_v.get(v, [])
        k = sum(1 for r in R if num(r.get(var)) is not None)
        cov[v] = {"n_rows": len(R), "n_measurable": k, "share": r4(rate(k, len(R)))}
    have3 = all(cov[v]["n_measurable"] > 0 for v in SIGN_VINTAGES)
    have5 = all(cov[v]["n_measurable"] > 0 for v in ALL_VINTAGES)
    var_vintage_cov[var] = {
        "coverage": cov,
        "sign_gate_evaluable": have3,
        "all5_vintages": have5,
        "gate_note": ("2016/2017/2018 すべてに在る＝符号不変ゲートを当てられる" if have3
                      else "2016/2017/2018 のどれかに存在しない＝符号不変ゲートは構造的に判定不能"),
    }

gate_reachable = [k for k, v in var_vintage_cov.items() if v["sign_gate_evaluable"]]
gate_unreachable = [k for k, v in var_vintage_cov.items() if not v["sign_gate_evaluable"]]

# ─────────── 結果を見る前に出す(2): セルの事象数（分子5に届くか） ───────────
cell_reach = {}
for v in ALL_VINTAGES:
    for pop in POPS:
        R = pop_rows(v, pop)
        n = len(R)
        ev = sum(1 for r in R if r.get("win"))
        base = rate(ev, n)
        ent = {"n": n, "events_win": ev, "base": r4(base)}
        if n == 0:
            ent["verdict"] = "母集団が空＝判定不能"
        elif ev < MIN_NUM:
            ent["verdict"] = "事象<5＝どの部分群でも分子5に届かない＝判定不能"
        else:
            # 四分位(n/4)で lift 0.15 を出すのに必要な分子と、MIN_NUM のどちらが縛るか
            g = max(1, n // 4)
            k_lift = math.ceil((base + LIFT) * g)
            binding = "LIFT" if k_lift >= MIN_NUM else "MIN_NUM"
            need = max(k_lift, MIN_NUM)
            ent.update({
                "quartile_group_n": g,
                "k_needed_by_lift": k_lift,
                "k_needed_by_min_num": MIN_NUM,
                "binding": binding,
                "effective_lift_required": r4(need / g - base),
                "share_of_all_events_required": r4(need / ev),
                "possible": need <= ev,
                "verdict": ("到達可能" if need <= ev else "上位1/4に全事象を集めても届かない＝判定不能"),
            })
        cell_reach[f"{v}/{pop}"] = ent


# ────────────────────────────── 中核: 1セルの測定 ──────────────────────────────
def measure(v, pop, var):
    """(vintage, population, variable) を測る。判定はしない（数字だけ返す）。"""
    R = pop_rows(v, pop)
    n_pop = len(R)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in R if r.get("win"))
    p_pop = rate(k_pop, n_pop)

    M = [(num(r.get(var)), 1 if r.get("win") else 0, r) for r in R]
    M = [(x, w, r) for (x, w, r) in M if x is not None]
    n_m = len(M)
    if n_m == 0:
        return {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": 0,
                "status": "この母集団でこの変数は一つも測れない＝判定不能"}
    k_m = sum(w for (_, w, _) in M)
    p_m = rate(k_m, n_m)

    # 欠測側（変数を報告していない社）の勝率 ＝ 欠測そのものの信号
    n_miss = n_pop - n_m
    k_miss = k_pop - k_m
    p_miss = rate(k_miss, n_miss) if n_miss else None

    vals = sorted(x for (x, _, _) in M)
    distinct = len(set(vals))
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)

    def grp(pred):
        g = [(x, w) for (x, w, _) in M if pred(x)]
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
        }
        if gn:
            share = gn / n_m
            ent["group_share_of_measurable"] = r4(share)
            # タイで四分位が潰れていないか（設計5）
            if name in ("上位1/4", "下位1/4") and not (0.10 <= share <= 0.45):
                ent["tie_degenerate"] = True
        cuts[name] = ent

    # (a) 五分位
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
        mono_rho = spearman([a for a, _ in pts], [b for _, b in pts]) if len(pts) >= 3 else None
        ps = [q["p"] for q in quint if q["p"] is not None and q["n"] >= 10]
        strict_up = len(ps) >= 4 and all(ps[i] < ps[i + 1] for i in range(len(ps) - 1))
        strict_dn = len(ps) >= 4 and all(ps[i] > ps[i + 1] for i in range(len(ps) - 1))
    else:
        mono_rho, strict_up, strict_dn = None, False, False

    # 低カーディナリティは値ごとの P(win)（潰れた五分位より情報が多い）
    by_val = None
    if distinct <= 6:
        c = defaultdict(lambda: [0, 0])
        for (x, w, _) in M:
            c[x][0] += 1
            c[x][1] += w
        by_val = [{"value": k, "n": a, "k": b, "p": r4(rate(b, a))} for k, (a, b) in sorted(c.items())]

    # 連続の向き（四分位の切り方に依存しない第二の物差し）
    rho = spearman([x for (x, _, _) in M], [float(w) for (_, w, _) in M])

    # **母集団の定義に使われている変数を、その母集団の中で検定してはいけない。**
    # P_quality は opm>=10% ∧ FCF全年黒字（2013/2015 は営業利益全年黒字も）で作られているので、
    # そこで opm / fcf_all_pos / fcfpos5 / op_all_pos を測ると、
    # 定数（lift が構造的に 0）か、切り詰められた範囲を見ていることになる。
    # 実測: co_fcf_all_pos|P_quality は distinct=1・群=母集団そのもの・lift=0.0000＝
    # 「測ってゼロ」ではなく「定義上ゼロ」。この二つを取り違えると、
    # 『測っていない』を『測って効果なし』と読む型（この台帳が何度も潰してきた型）になる。
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
        "distinct": distinct,
        "q25": q25, "q50": q50, "q75": q75,
        "cuts": cuts,
        "quintiles": quint or None,
        "quintile_spearman": r4(mono_rho),
        "quintile_strict_monotone_up": strict_up,
        "quintile_strict_monotone_down": strict_dn,
        "by_value": by_val,
        "rank_corr_value_vs_win": r4(rho),
    }


# ────────────────────────────── 全セルを測る ──────────────────────────────
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
        if not m or m.get("n_measurable", 0) == 0:
            per_v[v] = None
            continue
        per_v[v] = m

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
                      "lift_meas": c["lift_vs_measurable"],
                      "tie_degenerate": c.get("tie_degenerate", False)}
        # ── prereg のゲートを順に当てる ──
        # ⚠ タイが重い変数では群が空になることがある（例: f2_fcfpos5 は中央値=最大値=5 なので
        #    「中央値超」が0行）。空群は「不合格」ではなく「その切り方が成立しない＝判定不能」。
        got3 = [row[v] for v in SIGN_VINTAGES if row.get(v) and row[v]["lift"] is not None]
        n_empty3 = sum(1 for v in SIGN_VINTAGES
                       if row.get(v) and row[v]["lift"] is None)
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
        # 2013/2015 は「可能なら符号一致」（prereg の out_of_sample の後半）
        extra = [row[v] for v in (2013, 2015) if row.get(v) and row[v]["lift"] is not None]
        if extra and len(got3) == 3:
            s3 = 1 if got3[-1]["lift"] > 0 else -1
            gate["sign_agree_2013_2015"] = all((1 if g["lift"] > 0 else -1) == s3 for g in extra)
        else:
            gate["sign_agree_2013_2015"] = None
        row["gate"] = gate
        out["cuts"][cut] = row

    # 単調性と欠測は cut に依らない性質なので別枠
    out["monotonicity"] = {v: (None if not per_v.get(v) else {
        "quintiles": per_v[v]["quintiles"],
        "spearman": per_v[v]["quintile_spearman"],
        "strict_up": per_v[v]["quintile_strict_monotone_up"],
        "strict_down": per_v[v]["quintile_strict_monotone_down"],
        "by_value": per_v[v]["by_value"],
        "rank_corr": per_v[v]["rank_corr_value_vs_win"],
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
def mh_risk_diff(v, pop, var, cut):
    """層別リスク差（Cochran-Mantel-Haenszel 重み）。sic2 を層に使う。"""
    R = pop_rows(v, pop)
    M = [(num(r.get(var)), 1 if r.get("win") else 0, r.get("sic2")) for r in R]
    M = [(x, w, s) for (x, w, s) in M if x is not None and s]
    if len(M) < 20:
        return None
    vals = sorted(x for (x, _, _) in M)
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    pred = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
            "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    strata = defaultdict(lambda: [0, 0, 0, 0])   # n1,k1,n0,k0
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
    """(i) irr>=70 の層内で差が残るか (ii) 変数と irr が直交か。"""
    R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
    if len(R) < 20:
        return {"status": f"irr の読解がこのビンテージ・母集団で {len(R)} 行しかなく判定不能"}
    M = [(num(r.get(var)), 1 if r.get("win") else 0, r["irr"]) for r in R]
    M = [t for t in M if t[0] is not None]
    if len(M) < 20:
        return {"status": f"変数×irr がそろう行が {len(M)} で判定不能"}
    rho = spearman([x for x, _, _ in M], [float(i) for _, _, i in M])
    hi = [(x, w) for (x, w, i) in M if i >= 70]
    res = {"n_with_irr": len(M), "corr_var_vs_irr": r4(rho),
           "orthogonal_hint": (None if rho is None else abs(rho) < 0.15)}
    if len(hi) >= 20:
        vals = sorted(x for x, _ in hi)
        q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
        pred = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
        g = [w for x, w in hi if pred(x)]
        base = rate(sum(w for _, w in hi), len(hi))
        res["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g), "k": sum(g),
                           "p_group": r4(rate(sum(g), len(g))),
                           "lift": r4(None if not g else rate(sum(g), len(g)) - base)}
    else:
        res["irr_ge70"] = {"status": f"irr>=70 が {len(hi)} 行で判定不能（分子5に届かない）"}
    return res


# ────────────────────────────── 検出力（結果の前に出す） ──────────────────────────────
rnd = random.Random(SEED)


def binom(n, p):
    # n<=1000 なので素朴で十分
    return sum(1 for _ in range(n) if rnd.random() < p)


def power_sim(n, base, true_lift, n_sims=N_POWER):
    """1ビンテージの検出（|観測lift|>=0.15 ∧ k>=5）と、3ビンテージ独立での同時成立。"""
    g = max(1, n // 4)
    rest = n - g
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = min(0.999, max(0.001, (base * n - p_g * g) / rest))
    single = 0
    triple = 0
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
    return {"single_vintage": r4(single / n_sims), "three_independent": r4(triple / n_sims)}


power = {}
for pop, (n_ref, base_ref) in {
    "P_full": (946, cell_reach["2016/P_full"]["base"]),
    "P_quality": (329, cell_reach["2016/P_quality"]["base"]),
}.items():
    power[pop] = {"n_used": n_ref, "base_used": base_ref,
                  "by_true_lift": {str(L): power_sim(n_ref, base_ref, L) for L in (0.15, 0.20, 0.30)}}
power["_how_to_read"] = ("three_independent が下限・single_vintage が上限（3ビンテージが完全に同じ実現なら"
                         "1回引ければ3回引ける）。実際の outcome の Spearman は 0.845〜0.961 なので真の検出力はこの間。"
                         "真の lift がちょうど 0.15 のとき観測 lift が 0.15 以上になるのは約半分＝"
                         "『線ぴったりの効果』は原理的に半分しか掴めない。")


# ────────────────────────────── 偽陽性率（実データの相関を保った置換） ──────────────────────────────
# 索引空間 = 2016/2017/2018 に現れる全ティッカー（3ビンテージで同一の956）
tick_idx = {}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        if r["ticker"] not in tick_idx:
            tick_idx[r["ticker"]] = len(tick_idx)
N_T = len(tick_idx)

# outcome 側の束（ティッカーごと・3ビンテージまとめて動かす）
A_bits = {v: [0] * N_T for v in SIGN_VINTAGES}   # 解析集合（has_outcome ∧ window_full）
W_bits = {v: [0] * N_T for v in SIGN_VINTAGES}   # win
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        i = tick_idx[r["ticker"]]
        A_bits[v][i] = 1
        if r.get("win"):
            W_bits[v][i] = 1

# 特徴量側のマスク（母集団 ∧ 可測 ∧ 群）— 置換では動かない
def bits_to_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


fpr_masks = []   # [(var,pop,cut, {v: (mask_pop, mask_measurable, mask_group)})]
FPR_POPS = ["P_full", "P_quality"]     # P_moat は 2016/2017 に無く3ビンテージ手続きに乗らない
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
            # 母集団マスク（可測でない行も母集団には居る＝lift の分母は母集団）
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


def run_procedure(Aint, Wint, thresh=LIFT, want_stat=False, base="pop"):
    """置換後の outcome で、prereg のゲート1-3（lift・分子・符号不変）を通る候補を数える。

    want_stat=True なら、各検定の統計量（符号が揃ったうえでの最小|lift|。揃わなければ0）も返す。
    ——**0件という結論ほど道具を先に疑う**ので、帰無分布そのものを見られるようにしてある。
    base="meas" は分母を可測部分集合にした版（**事前登録の外・診断専用**）。
    欠測の交絡を外しても信号が残るかを、同じ帰無で測るためだけにある。
    """
    hits, stats = [], []
    for (var, pop, cut, mv) in fpr_masks:
        ok, signs, mins = True, set(), []
        for v in SIGN_VINTAGES:
            pm, mm_, gm = mv[v]
            bm = pm if base == "pop" else mm_
            a = Aint[v]
            npop = (bm & a).bit_count()
            kpop = (bm & Wint[v]).bit_count()
            ng = (gm & a).bit_count()
            kg = (gm & Wint[v]).bit_count()
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
W0 = {v: bits_to_int(W_bits[v]) for v in SIGN_VINTAGES}
observed_hits = run_procedure(A0, W0)

RELAX = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
perm_hits = []
perm_maxstat = []
perm_maxstat_meas = []
relax_any = {t: 0 for t in RELAX}
sigma = list(range(N_T))
for _ in range(N_PERM):
    rnd.shuffle(sigma)
    Ai = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Wi = {v: perm_int(W_bits[v], sigma) for v in SIGN_VINTAGES}
    _h, st = run_procedure(Ai, Wi, want_stat=True)
    mx = max(st) if st else 0.0
    perm_maxstat.append(mx)
    perm_hits.append(sum(1 for s in st if s >= LIFT))
    for t in RELAX:
        if mx >= t:
            relax_any[t] += 1
    _h2, st2 = run_procedure(Ai, Wi, want_stat=True, base="meas")
    perm_maxstat_meas.append(max(st2) if st2 else 0.0)

n_any = sum(1 for h in perm_hits if h > 0)
srt = sorted(perm_maxstat)


def pct(p):
    return r4(srt[min(len(srt) - 1, max(0, int(p * len(srt)) - 1))])


_, obs_stats = run_procedure(A0, W0, want_stat=True)
obs_max = max(obs_stats) if obs_stats else 0.0
_, obs_stats_meas = run_procedure(A0, W0, want_stat=True, base="meas")

fpr = {
    "n_permutations": N_PERM,
    "n_tests_in_procedure": len(fpr_masks),
    "null_construction": ("特徴量側（母集団・可測・群）は固定し、outcome の束"
                          "(has_outcome∧window_full, win)をティッカーごとまとめて置換する。"
                          "これでビンテージ間の outcome 相関・欠測構造・P_quality の定義を保ったまま、"
                          "特徴量↔outcome だけを壊せる。"),
    "P_at_least_one_pass": r4(n_any / N_PERM),
    "mean_passes_per_permutation": r4(sum(perm_hits) / N_PERM),
    "max_passes_in_a_permutation": max(perm_hits),
    "observed_passes_gates123": len(observed_hits),
    "observed_hits": [{"variable": a, "population": b, "cut": c} for a, b, c in observed_hits],
    # ── 0件という結論を、道具が動いている証拠つきで出す ──
    "null_distribution_of_max_statistic": {
        "statistic": "168検定のうち最大の『符号が揃ったうえでの3ビンテージ最小|lift|』",
        "p50": pct(0.50), "p90": pct(0.90), "p95": pct(0.95), "p99": pct(0.99),
        "max_over_permutations": r4(max(perm_maxstat)),
        "observed_in_real_data": r4(obs_max),
        "empirical_p_of_observed": r4(sum(1 for m in perm_maxstat if m >= obs_max) / N_PERM),
    },
    "fpr_at_relaxed_thresholds": {
        "note": "**事前登録の外・診断専用**。合否には数えない。線を緩めたときに FPR が立ち上がることを"
                "示して、『0.0』が手続きの厳しさであって道具の故障でないことを見せるためだけにある。",
        "P_at_least_one_pass_by_threshold": {str(t): r4(relax_any[t] / N_PERM) for t in RELAX},
    },
    "supplementary_null_measurable_base": {
        "note": "**事前登録の外・診断専用**。lift の分母を可測部分集合にした版（＝欠測の交絡を外した版）を"
                "同じ帰無で測る。『その変数を報告している社かどうか』ではなく『その変数の値』が"
                "分けているのか、を切り分けるためだけにある。",
        "statistic": "168検定のうち最大の『符号が揃ったうえでの3ビンテージ最小|lift_vs_measurable|』",
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

    # 到達可能性を先に見る（判定不能を不合格と書かないため）
    reach_bad = []
    for v in SIGN_VINTAGES:
        cr = cell_reach.get(f"{v}/{pop}", {})
        if cr.get("n", 0) == 0 or cr.get("events_win", 0) < MIN_NUM or cr.get("possible") is False:
            reach_bad.append(v)

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
                "reason": f"タイが重くこの切り方で群が空になるビンテージが {g['empty_group_vintages']} 件（切り方が成立しない）",
                "gate_failed_at": "empty_group"}
    if reach_bad:
        return {"verdict": "判定不能",
                "reason": f"母集団の事象数が足りず分子5に届かないビンテージがある: {reach_bad}",
                "gate_failed_at": "reachability"}
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
    # ここまで通ったものだけ、費用の高いゲート4・5を当てる
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


# ────────────── 陽性対照（注入検査）: 本物の効果なら手続きが掴めることを実証する ──────────────
# 「合格ゼロ」という強い結論ほど、先に道具を疑う（recalc_roic の ADBE 事故と同型の予防）。
# 真の lift を仕込んだ合成変数を作り、**同じ measure()/verdict_for() を通して**合格が出るか見る。
def inject_control(true_lift, key):
    """全ビンテージで上位1/4の勝率が base+true_lift になるよう作った合成変数を各行へ書く。"""
    for v in ALL_VINTAGES:
        R = pop_rows(v, "P_full")
        n = len(R)
        g = max(1, n // 4)
        base = rate(sum(1 for r in R if r.get("win")), n)
        k_want = min(sum(1 for r in R if r.get("win")), max(MIN_NUM, int(round((base + true_lift) * g))))
        wins = [r for r in R if r.get("win")]
        loss = [r for r in R if not r.get("win")]
        rnd.shuffle(wins)
        rnd.shuffle(loss)
        grp = wins[:k_want] + loss[:g - k_want]
        gs = {id(r) for r in grp}
        # 上位1/4 が群、それ以外は下側に散らす（値の大小だけで四分位が決まるように）
        for r in R:
            r[key] = (0.75 + rnd.random() * 0.25) if id(r) in gs else (rnd.random() * 0.74)
        for r in by_v[v]:
            if key not in r:
                r[key] = None


def drop_control(key):
    for r in rows_all:
        r.pop(key, None)


positive_control = {}
for L, key in ((0.25, "_ctrl25"), (0.15, "_ctrl15")):
    inject_control(L, key)
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
    }
    for pop in POPS:
        for v in ALL_VINTAGES:
            cells.pop(f"{key}|{pop}|{v}", None)
    summaries.pop(f"{key}|P_full", None)
    CANDIDATES.remove(key)
    var_vintage_cov.pop(key, None)
    drop_control(key)
positive_control["_how_to_read"] = (
    "真の lift 0.25 を仕込んだら合格が出て、0.15（線ぴったり）では出たり出なかったりする——"
    "これが正しい挙動。0.15 で必ず合格するなら線が甘く、0.25 で合格しないなら道具が壊れている。"
    "検出力の実測（真lift0.15 で下限0.12）とも整合する。")


verdicts = {}
for var in CANDIDATES:
    for pop in POPS:
        if f"{var}|{pop}" not in summaries:
            continue
        for cut in CUTNAMES:
            vd = verdict_for(var, pop, cut)
            if vd:
                verdicts[f"{var}|{pop}|{cut}"] = vd


# ────────────────────────────── 上位30本（lift の大きい順） ──────────────────────────────
rank_rows = []
for key, s in summaries.items():
    var, pop = key.split("|")
    for cut in CUTNAMES:
        row = s["cuts"][cut]
        g = row["gate"]
        got = [(v, row[v]) for v in ALL_VINTAGES if row.get(v) and row[v]["lift"] is not None]
        if not got:
            continue
        # 並べ替えの物差し: 3ビンテージそろうものは「符号が揃った上での最小|lift|」＝維持できた幅。
        # そろわないものは測れたビンテージの中央値の|lift|（判定不能である事実は verdict が言う）
        if g.get("min_abs_lift_3v") is not None and g.get("sign_stability") is True:
            score = g["min_abs_lift_3v"]
            basis = "3ビンテージで符号が揃ったうえでの最小|lift|"
        elif g.get("min_abs_lift_3v") is not None:
            score = -1.0 + g["min_abs_lift_3v"]   # 符号が割れたものは必ず下へ
            basis = "3ビンテージで符号が割れた（最小|lift|から1.0引いて下位へ）"
        else:
            ls = sorted(abs(x[1]["lift"]) for x in got)
            score = ls[len(ls) // 2]
            basis = "3ビンテージそろわず＝測れたビンテージの|lift|の中央値（判定不能）"
        anchor_v = 2018 if (row.get(2018) and row[2018]["lift"] is not None) else got[-1][0]
        a = row[anchor_v]
        # 欠測の交絡（設計2）: population 基準の lift と可測基準の lift が大きく食い違うなら、
        # 見ているのは「その変数の値」ではなく「その変数を報告している社かどうか」の側かもしれない
        mi = s["missingness"].get(anchor_v) or {}
        gap = (None if a["lift"] is None or a["lift_meas"] is None
               else round(abs(a["lift"]) - abs(a["lift_meas"]), 4))
        rank_rows.append({
            "variable": var, "population": pop, "cut": cut,
            "rank_score": r4(score), "rank_basis": basis,
            "anchor_vintage": anchor_v,
            "n_group": a["n_group"], "numerator": a["k"],
            "p_group": a["p_group"], "p_base": a["p_base"],
            "lift_anchor": a["lift"],
            "lift_by_vintage": {str(v): (row[v]["lift"] if row.get(v) else None) for v in ALL_VINTAGES},
            "numerator_by_vintage": {str(v): (row[v]["k"] if row.get(v) else None) for v in ALL_VINTAGES},
            "n_group_by_vintage": {str(v): (row[v]["n_group"] if row.get(v) else None) for v in ALL_VINTAGES},
            "lift_meas_by_vintage": {str(v): (row[v]["lift_meas"] if row.get(v) else None) for v in ALL_VINTAGES},
            "sign_stable_161718": g.get("sign_stability"),
            "min_abs_lift_161718": g.get("min_abs_lift_3v"),
            "sign_agree_2013_2015": g.get("sign_agree_2013_2015"),
            "tie_degenerate_anchor": a.get("tie_degenerate", False),
            "coverage_anchor": (None if not mi else r4(rate(mi["n_measurable"],
                                                           mi["n_measurable"] + mi["n_missing"]))),
            # ⚠ 欠測が数行しか無いときの missingness_lift は1社で 0.2 動く＝読んではいけない。
            #   n_missing を必ず添える（実測 f2_aturn は欠測1行で -0.2103 と出る）
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

# 判定を出せるセルだけの序列（＝問いに対する本当の答え。
# 上の top30 は生の |lift| 順なので、n=16 の判定不能セルが上位を占める）
gate_eval = [r for r in rank_rows if r["sign_stable_161718"] is True
             and r["min_abs_lift_161718"] is not None]
gate_eval.sort(key=lambda r: -r["min_abs_lift_161718"])
top_gate_evaluable = gate_eval[:30]

# ゲート4・5は lift で落ちた候補にも当てておく（診断）。
# 「線に届かなかった」ことと「業種や irr の影だった」ことは別の情報で、
# 後から線が動いたときに最初に効くのはここだから。
for r in top_gate_evaluable[:15]:
    r["diagnostics_sector_mh"] = {str(v): mh_risk_diff(v, r["population"], r["variable"], r["cut"])
                                  for v in SIGN_VINTAGES}
    r["diagnostics_irr_control_2018"] = irr_control(2018, r["population"], r["variable"], r["cut"])


# ────────────────────────────── 概念の対（5ビンテージ並べ） ──────────────────────────────
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
                "variable": mp[v],
                "n_pop": m["n_pop"], "p_base": m["p_pop"],
                "上位1/4": {"n": m["cuts"]["上位1/4"]["n_group"], "k": m["cuts"]["上位1/4"]["numerator"],
                            "p": m["cuts"]["上位1/4"]["p_group"], "lift": m["cuts"]["上位1/4"]["lift_vs_pop"]},
                "下位1/4": {"n": m["cuts"]["下位1/4"]["n_group"], "k": m["cuts"]["下位1/4"]["numerator"],
                            "p": m["cuts"]["下位1/4"]["p_group"], "lift": m["cuts"]["下位1/4"]["lift_vs_pop"]},
                "quintile_spearman": m["quintile_spearman"],
                "rank_corr": m["rank_corr_value_vs_win"],
            }
        # 5ビンテージで上位1/4 lift の符号がそろうか（**繋いだのではなく並べただけ**）
        ls = [tbl[str(v)]["上位1/4"]["lift"] for v in ALL_VINTAGES if tbl.get(str(v))]
        ent["by_population"][pop] = {
            "table": tbl,
            "n_vintages_measured": len(ls),
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
    "tool": "night/hist_wd_win_uni.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "panel": "out/hist_wd_panel.json",
    "objective": "A_勝者: P(実現年率 tr_cagr >= +15%)。破壊側(目的B)はこの道具の範囲外。",
    "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM,
                       "sign_stability_vintages": SIGN_VINTAGES,
                       "sector_control": "同一sic2内のMH重み付きリスク差でも |RD|>=0.15",
                       "not_irr_shadow": "irr>=70層内で |lift|>=0.15、または変数とirrが直交(|rho|<0.15)",
                       "note": "prereg のまま。この道具は線を一つも作っていない。"},
    "design_decisions": {
        "analysis_set": "has_outcome ∧ window_full（短窓は年率換算で両裾を機械的に膨らませるため）",
        "lift_denominator": "prereg literal＝その population 全体。可測部分集合を分母にした版も併記（診断）",
        "namespaces": "f2_/co_/pa_/hv_/per を混ぜない。概念の対は『並べる』だけで繋がない",
        "ties": "四分位は値の閾値で切る。実現群サイズを必ず出し、n/4 から外れたら tie_degenerate を立てる",
        "low_cardinality": "distinct<=6 は値ごとの P(win) も出す（潰れた四分位より情報が多い）",
    },
    "analysis_set_size": {str(v): {"n": len(by_v[v]),
                                   "wins": sum(1 for r in by_v[v] if r.get("win"))}
                          for v in ALL_VINTAGES},
    "must_report_before_verdict": {
        "gate_reachability_by_variable": var_vintage_cov,
        "gate_reachable_variables": gate_reachable,
        "gate_unreachable_variables": gate_unreachable,
        "gate_reachability_summary": (
            f"候補{len(CANDIDATES)}本のうち、prereg の必須ゲート（2016/2017/2018 の符号不変）を"
            f"当てられるのは {len(gate_reachable)} 本だけ。残り {len(gate_unreachable)} 本は"
            "結果を見る前から構造的に判定不能（co_は2013/2015のみ・pa_は2018のみ・hv_/perは2016/2017に無い）。"),
        "cell_reachability": cell_reach,
        "power": power,
        "false_positive_rate": fpr,
        "positive_control_injection": positive_control,
    },
    "verdict_counts": {"by_verdict": dict(counts),
                       "fail_gate_histogram": dict(fail_at),
                       "undetermined_gate_histogram": dict(undet_at),
                       "n_pass": counts.get("合格", 0)},
    "top30_by_lift": top30,
    "top30_by_lift_note": ("生の |lift| 順。**上位は判定不能セルが占める**——P_moat の 2018 は n=63 で"
                           "四分位群が16行しかなく、1社の増減が lift を 0.06 動かす。"
                           "『大きい lift』と『確かな lift』は別物なので、答えは次の "
                           "top_gate_evaluable のほうで読むこと。"),
    "top_gate_evaluable": top_gate_evaluable,
    "top_gate_evaluable_note": ("prereg の必須ゲート（2016/2017/2018 の符号不変）を当てられ、かつ実際に"
                                "符号が揃ったセルだけを『3ビンテージで維持できた最小|lift|』の順に並べたもの。"
                                "**これがこの探索の答え**。"),
    "concept_pairs_5vintage": concept,
    "summaries": summaries,
    "verdicts": verdicts,
    "cells": cells,
}

json.dump(doc, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print(f"解析集合: " + " / ".join(f"{v}:{len(by_v[v])}行({sum(1 for r in by_v[v] if r.get('win'))}勝)"
                                  for v in ALL_VINTAGES))
print(f"\n■ ゲート到達可能性（結果の前に）")
print(f"  候補 {len(CANDIDATES)} 本 → 符号不変ゲートを当てられるのは {len(gate_reachable)} 本 / "
      f"構造的に判定不能 {len(gate_unreachable)} 本")
print(f"  判定不能の内訳: " + ", ".join(gate_unreachable[:40]))
print(f"\n■ 検出力（3ビンテージ独立＝下限 / 単一ビンテージ＝上限）")
for pop, d in power.items():
    if pop.startswith("_"):
        continue
    for L, r in d["by_true_lift"].items():
        print(f"  {pop} 真のlift={L}: 下限 {r['three_independent']} / 上限 {r['single_vintage']}")
print(f"\n■ 偽陽性率（置換{N_PERM}回・実データの相関を保った帰無）")
print(f"  検定数 {fpr['n_tests_in_procedure']} / 偶然に1本以上通る確率 {fpr['P_at_least_one_pass']}")
print(f"  実データでゲート1-3を通ったのは {fpr['observed_passes_gates123']} 本")
nd = fpr["null_distribution_of_max_statistic"]
print(f"  帰無での最大統計量: p50={nd['p50']} p95={nd['p95']} p99={nd['p99']} 最大={nd['max_over_permutations']}"
      f" ／ 実データ={nd['observed_in_real_data']} (経験p={nd['empirical_p_of_observed']})")
print("  線を緩めたときの FPR: " + " ".join(
    f"{k}→{v}" for k, v in fpr["fpr_at_relaxed_thresholds"]["P_at_least_one_pass_by_threshold"].items()))
sm = fpr["supplementary_null_measurable_base"]
print(f"  【補】欠測を外した版（分母=可測部分集合）: 実データ={sm['observed_in_real_data']} "
      f"帰無p95={sm['null_p95']} 経験p={sm['empirical_p_of_observed']}")
print(f"\n■ 陽性対照（注入検査・道具が本物の効果を掴めるか）")
for k, v in positive_control.items():
    if k.startswith("_"):
        continue
    print(f"  {k} → {v['verdict']}（lifts {v['observed_lifts_161718']}）")
print(f"\n■ 判定: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
print(f"  不合格の内訳: {dict(fail_at)}")
print(f"  判定不能の内訳: {dict(undet_at)}")
print(f"\n■ 生の |lift| 上位10（※上位は判定不能セルが占める＝答えではない）")
for r in top30[:10]:
    print(f"  {r['rank_score']:+.3f} {r['variable']:15s}{r['population']:10s}{r['cut']:6s} "
          f"anchor{r['anchor_vintage']} n={r['n_group']} k={r['numerator']} → {r['verdict']}")
print(f"\n■ 判定を当てられるセルの中で維持できた |lift| 上位15  ← これが答え")
for r in top_gate_evaluable[:15]:
    ls = r["lift_by_vintage"]
    print(f"  {r['min_abs_lift_161718']:.3f} {r['variable']:15s}{r['population']:10s}{r['cut']:6s} "
          f"16/17/18={ls['2016']}/{ls['2017']}/{ls['2018']} "
          f"欠測交絡={'あり' if r['missingness_confounded'] else '—'} → {r['verdict']}")
print(f"\n→ {DEST}")
