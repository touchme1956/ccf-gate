#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_angleA.py — 角度A: 目的を **P(tr_cagr >= +10%)** にした単変量探索（**両方向**）。

事前登録: out/hist10_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル。特徴量の再実装をしない・v9.9.65）
参照    : out/hist_wd_win_uni.json（15%版の公表結果。**再現できるかを先に確かめる**）
出力    : out/hist10_angleA.json

────────────────────────────────────────────────────────────
なぜ 10% が新しい角度なのか（prereg の why_10pct_changes_everything）
────────────────────────────────────────────────────────────
基準率が 0.376〜0.428 へ倍増する。効くのは二つ:
 (1) **減らす向きが到達可能になる**。15%（基準率0.19〜0.24）では
     「lift <= -0.15」は P(群) <= 0.04〜0.09 を要求し、同時に分子>=20 を満たせない。
     実測: 15%で下向きが到達可能なセルは **13中1つだけ**（2016/P_full）。
     10%では P_full/P_quality の 11 セルで到達可能になる。
 (2) 分子が増えるので、同じ群サイズで推定が安定する。

⚠ ただし 10% は **指数（同期間 14.2〜15.2%）に負ける水準**。
   「勝つ」ではなく「複利が立つ」の線であることを、結論を読む人に必ず伝える。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定
────────────────────────────────────────────────────────────
1) **解析集合は has_outcome ∧ window_full**（15%版と同一）。短窓は年率換算で両裾を機械的に膨らませる。

2) **15%版を同じコードで再現してから比べる**。
   公表 JSON の数字をそのまま引用して並べるのではなく、**この道具の measure() を
   hurdle=0.15・MIN_NUM=5 で回して公表値と突き合わせる**。一致を確認して初めて
   「10%にして出てきた/消えた」と言える。基準の違う二つを並べない（この台帳が8回踏んだ型）。
   比較そのものは **MIN_NUM を 20 に揃えた**上で hurdle だけを変えて行う
   （prereg の線は 10% 側にしか無いので、15% 側は「同じ手続きを当てたらどうか」の診断）。

3) **両方向は「同じ4つの切り方の符号」で表す**。
   上位1/4 の lift が負なら、それは「値が高いほど 10%+ を出しにくい」＝減らす向き。
   切り方を増やすと検定数が増えて FPR が上がるので、**新しい切り方は作らない**。
   ただし到達可能性・検出力・陽性対照は **上下それぞれ独立に**出す（下向きは制約が違うため）。

4) **下向きには min_numerator が上限として効く**（15%版に無かった構造）。
   下向きは「群の中の 10%+ が少ない」ことなので、分子>=20 は
   **強い下向きほど落ちる**という向きに働く。検出できる最大の下向き幅は
   `base - 20/群サイズ` で頭打ちになる。実測 2018/P_quality では **-0.166 まで**
   ＝それより強く効く指標は「強すぎて判定不能」になる。**これは不合格ではない。**

5) **増分ゲート（prereg の incremental）は方向で当てるものが違う**。
   - 下向き（この群は複利しない）: 群の中の **10%未満だった社**のうち、
     門が既に持つ関門（質実証を通らない / 事業の収縮 / 薄い財務）で
     **既に落ちている**社の割合。7割超なら不合格（v2 の破壊側と同一の手続き）。
   - 上向き（この群は複利する）: 既存の関門を**通る社だけに絞って**測り直し、
     lift が 0.15 を保つか。既存の関門を再表現しているだけなら消える。
   両方を全セルで計算して出し、**方向に応じた側を合否に使う**。
   ⚠ P_quality 母集団では「質実証を通らない」は定義上ゼロ＝増分ゲートが甘くなる。印を付ける。

6) **タイ・低カーディナリティ・欠測の扱いは15%版と同一**（比較のため変えてはいけない）。

7) **FPR は会社単位で全ビンテージ同時に混ぜる**（prereg の must_report）。
   ビンテージ内で独立に混ぜると従属が壊れて FPR を 33 倍過小評価する、が既に実測されている。
"""
import json, os, math, random, bisect, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
V15 = os.path.join(OUT, "hist_wd_win_uni.json")
DEST = os.path.join(OUT, "hist10_angleA.json")

# ─── prereg の線（この道具は一つも作らない・読むだけ） ───
LIFT = 0.15
MIN_NUM = 20                      # prereg: 基準率が2倍なので v1 の5社より厳しくする
HURDLE = 0.10                     # 目的 y10
HURDLE15 = 0.15                   # 比較用（v1 の目的）
MIN_NUM_V1 = 5                    # v1 再現用
INCREMENTAL_MAX_CAUGHT = 0.70     # prereg: 7割超が既存関門で説明されるなら不合格

SIGN_VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]

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


# ────────────────────────────── 小道具 ──────────────────────────────
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
    num_ = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return num_ / (dx * dy)


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


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
rows_all = panel["rows"]

ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]

# 目的変数を行に焼く（win は 15% の既製フラグ。y10 はここで作る）
for r in ANA:
    tc = r.get("tr_cagr")
    r["_y10"] = (tc is not None and tc >= HURDLE)
    r["_y15"] = bool(r.get("win"))

by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)


def pop_rows(v, pop):
    return [r for r in by_v[v] if r.get(pop)]


# ── 既存の関門（増分ゲート用）。**新しい定数を作らない**——v2 の破壊側検証と同一の定義 ──
def g_shrink(r):
    """事業の収縮（v9.9.99・門に実装済み）: 売上5年CAGR<0 ∧ 営業利益率の5年変化<0"""
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def g_thin(r):
    """財務の薄さ。intcov<3＝門の nde>4 の歴史側の相当物（v2 と同じ代用）"""
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def g_notq(r):
    return not r.get("P_quality")


def g_blocked(r):
    return g_shrink(r) or g_thin(r) or g_notq(r)


# ─────────── 結果を見る前に(1): 変数ごとのゲート到達可能性 ───────────
var_vintage_cov = {}
for var in CANDIDATES:
    cov = {}
    for v in ALL_VINTAGES:
        R = by_v.get(v, [])
        k = sum(1 for r in R if num(r.get(var)) is not None)
        cov[v] = {"n_rows": len(R), "n_measurable": k, "share": r4(rate(k, len(R)))}
    have3 = all(cov[v]["n_measurable"] > 0 for v in SIGN_VINTAGES)
    var_vintage_cov[var] = {
        "coverage": cov,
        "sign_gate_evaluable": have3,
        "all5_vintages": all(cov[v]["n_measurable"] > 0 for v in ALL_VINTAGES),
        "gate_note": ("2016/2017/2018 すべてに在る＝符号不変ゲートを当てられる" if have3
                      else "2016/2017/2018 のどれかに存在しない＝符号不変ゲートは構造的に判定不能"),
    }
gate_reachable = [k for k, v in var_vintage_cov.items() if v["sign_gate_evaluable"]]
gate_unreachable = [k for k, v in var_vintage_cov.items() if not v["sign_gate_evaluable"]]


# ─────────── 結果を見る前に(2): セルの到達可能性を**上下それぞれ** ───────────
def reach_cell(v, pop, ykey, min_num):
    R = pop_rows(v, pop)
    n = len(R)
    ev = sum(1 for r in R if r.get(ykey))
    if n == 0:
        return {"n": 0, "verdict": "母集団が空＝判定不能"}
    base = ev / n
    g = max(1, n // 4)
    # 上向き: k >= max(ceil((base+LIFT)*g), min_num) かつ k <= min(g, ev)
    k_up = max(math.ceil((base + LIFT) * g), min_num)
    up_ok = k_up <= min(g, ev)
    # 下向き: k <= floor((base-LIFT)*g) かつ k >= min_num
    k_dn_max = math.floor((base - LIFT) * g)
    dn_ok = k_dn_max >= min_num
    return {
        "n": n, "events": ev, "base": r4(base), "quartile_group_n": g,
        "up": {
            "k_needed": k_up,
            "binding": ("LIFT" if math.ceil((base + LIFT) * g) >= min_num else "MIN_NUM"),
            "effective_lift_required": r4(k_up / g - base),
            "share_of_all_events_required": r4(k_up / ev) if ev else None,
            "possible": up_ok,
            "max_detectable_lift": r4(min(g, ev) / g - base),
        },
        "down": {
            "k_max_allowed_by_lift": k_dn_max,
            "k_min_required": min_num,
            "possible": dn_ok,
            # ⚠ 下向きは min_numerator が**上限**として効く。強すぎる下向きは判定不能になる
            "max_detectable_lift": r4(min_num / g - base) if dn_ok else None,
            "why_not": (None if dn_ok else
                        f"分子>={min_num} と lift<=-{LIFT} が同時に成立しない"
                        f"（群{g}社で lift<=-{LIFT} なら分子は最大 {k_dn_max} 社）"),
        },
    }


cell_reach10 = {f"{v}/{pop}": reach_cell(v, pop, "_y10", MIN_NUM)
                for v in ALL_VINTAGES for pop in POPS}


def reach_var(v, pop, var, ykey="_y10", min_num=MIN_NUM):
    """**被覆で調整した**到達可能性。四分位は母集団ではなく『その変数を測れた部分集合』で切るので、
       被覆が薄い変数ほど群が小さくなり、下向きの検出上限が母集団基準より厳しくなる。
       ⚠ セル単位の reach_cell（母集団の n/4 を仮定）はこれを見落とす——**同じ道具の中で二つの
       基準を持たないため、変数ごとの版を必ず併記する**（『基準の違う二つ』を作らない）。"""
    R = pop_rows(v, pop)
    n_pop = len(R)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in R if r.get(ykey))
    base = k_pop / n_pop
    n_m = sum(1 for r in R if num(r.get(var)) is not None)
    if n_m == 0:
        return None
    g = max(1, n_m // 4)
    up_max = min(g, k_pop) / g - base            # 群を全部 y=1 で埋めたときの lift
    dn_mag = base - min_num / g                  # 分子>=min_num を保てる最強の下向き幅（正の大きさ）
    return {
        "n_pop": n_pop, "n_measurable": n_m, "coverage": r4(n_m / n_pop),
        "quartile_group_n": g, "base": r4(base),
        "up_max_detectable_lift": r4(up_max),
        "up_certifiable": up_max >= LIFT,
        "down_max_detectable_lift": r4(-dn_mag),
        "down_certifiable": dn_mag >= LIFT,
        "down_why_not": (None if dn_mag >= LIFT else
                         f"群{g}社では分子>={min_num} を保てる下向きは最大 {-dn_mag:.4f} まで"
                         f"＝0.15 に届く前に分子で落ちる（どんなに強い下向きでも合格を出せない）"),
    }
cell_reach15 = {f"{v}/{pop}": reach_cell(v, pop, "_y15", MIN_NUM)
                for v in ALL_VINTAGES for pop in POPS}
cell_reach15_v1 = {f"{v}/{pop}": reach_cell(v, pop, "_y15", MIN_NUM_V1)
                   for v in ALL_VINTAGES for pop in POPS}


# ────────────────────────────── 中核: 1セルの測定 ──────────────────────────────
def measure(v, pop, var, ykey=("_y10",), min_num=MIN_NUM):
    ykey = ykey[0] if isinstance(ykey, tuple) else ykey
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
        gn = len(grp)
        gk = sum(w for _, w, _ in grp)
        gp = rate(gk, gn)
        lift = None if gp is None else gp - p_pop
        ent = {
            "cut": DESC[name], "n_group": gn, "numerator": gk, "p_group": r4(gp),
            "lift_vs_pop": r4(lift),
            "lift_vs_measurable": r4(None if gp is None else gp - p_m),
            "direction": (None if lift is None else ("増やす" if lift > 0 else ("減らす" if lift < 0 else "ゼロ"))),
        }
        if gn:
            share = gn / n_m
            ent["group_share_of_measurable"] = r4(share)
            if name in ("上位1/4", "下位1/4") and not (0.10 <= share <= 0.45):
                ent["tie_degenerate"] = True
            # 増分ゲートの材料（設計5）——両方向ぶん常に出す
            fails = [r for (_, w, r) in grp if not w]
            caught = sum(1 for r in fails if g_blocked(r))
            passers = [(x, w) for (x, w, r) in grp if not g_blocked(r)]
            base_pass = [(x, w) for (x, w, r) in M if not g_blocked(r)]
            # ⚠ 上向きの増分は「母集団側も関門通過に絞る」——群だけ絞ると分母が動いて偽の差が出る
            bp_n = len([1 for (_, _, r) in
                        [(x, w, r) for (x, w, r) in
                         [(a, b, c) for (a, b, c) in M]] if not g_blocked(r)])
            bp_k = sum(w for (_, w, r) in M if not g_blocked(r))
            ent["incremental"] = {
                "down_side": {
                    "n_failures_in_group": len(fails),
                    "already_caught_by_existing_gates": caught,
                    "caught_share": r4(rate(caught, len(fails))),
                    "breakdown": {
                        "not_quality": sum(1 for r in fails if g_notq(r)),
                        "shrink": sum(1 for r in fails if g_shrink(r)),
                        "thin_finance": sum(1 for r in fails if g_thin(r)),
                    },
                },
                "up_side": {
                    "n_group_passing_gates": len(passers),
                    "k_group_passing_gates": sum(w for _, w in passers),
                    "p_group_passing_gates": r4(rate(sum(w for _, w in passers), len(passers))),
                    "n_base_passing_gates": bp_n,
                    "p_base_passing_gates": r4(rate(bp_k, bp_n)),
                    "lift_within_gate_passers": r4(
                        None if not passers or not bp_n
                        else rate(sum(w for _, w in passers), len(passers)) - rate(bp_k, bp_n)),
                },
                "circular_note": ("P_quality 母集団では not_quality が定義上ゼロ＝増分ゲートが甘くなる"
                                  if pop == "P_quality" else None),
            }
        cuts[name] = ent

    # 五分位
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

    by_val = None
    if distinct <= 6:
        c = defaultdict(lambda: [0, 0])
        for (x, w, _) in M:
            c[x][0] += 1
            c[x][1] += w
        by_val = [{"value": k, "n": a, "k": b, "p": r4(rate(b, a))} for k, (a, b) in sorted(c.items())]

    rho = spearman([x for (x, _, _) in M], [float(w) for (_, w, _) in M])

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
        "distinct": distinct, "q25": q25, "q50": q50, "q75": q75,
        "cuts": cuts,
        "quintiles": quint or None,
        "quintile_spearman": r4(mono_rho),
        "quintile_strict_monotone_up": strict_up,
        "quintile_strict_monotone_down": strict_dn,
        "by_value": by_val,
        "rank_corr_value_vs_y": r4(rho),
    }


# ────────────────────────────── 全セルを測る（10% と 15%） ──────────────────────────────
cells10, cells15 = {}, {}
for var in CANDIDATES:
    for pop in POPS:
        for v in ALL_VINTAGES:
            m = measure(v, pop, var, "_y10", MIN_NUM)
            if m:
                cells10[f"{var}|{pop}|{v}"] = m
            m2 = measure(v, pop, var, "_y15", MIN_NUM)
            if m2:
                cells15[f"{var}|{pop}|{v}"] = m2


def summarize(var, pop, cells, min_num):
    per_v = {}
    for v in ALL_VINTAGES:
        m = cells.get(f"{var}|{pop}|{v}")
        per_v[v] = m if (m and m.get("n_measurable", 0) > 0) else None

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
                      "direction": c.get("direction"),
                      "tie_degenerate": c.get("tie_degenerate", False),
                      "incremental": c.get("incremental")}
        got3 = [row[v] for v in SIGN_VINTAGES if row.get(v) and row[v]["lift"] is not None]
        n_empty3 = sum(1 for v in SIGN_VINTAGES if row.get(v) and row[v]["lift"] is None)
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
            gate["min_num_all3"] = all(g["k"] >= min_num for g in got3)
            gate["min_abs_lift_3v"] = r4(min(abs(g["lift"]) for g in got3))
            gate["signed_lifts_3v"] = [g["lift"] for g in got3]
            gate["numerators_3v"] = [g["k"] for g in got3]
            gate["direction_3v"] = (list(signs)[0] if len(signs) == 1 else None)
        extra = [row[v] for v in (2013, 2015) if row.get(v) and row[v]["lift"] is not None]
        if extra and len(got3) == 3:
            s3 = 1 if got3[-1]["lift"] > 0 else -1
            gate["sign_agree_2013_2015"] = all((1 if g["lift"] > 0 else -1) == s3 for g in extra)
        else:
            gate["sign_agree_2013_2015"] = None
        row["gate"] = gate
        out["cuts"][cut] = row

    out["monotonicity"] = {v: (None if not per_v.get(v) else {
        "quintiles": per_v[v]["quintiles"], "spearman": per_v[v]["quintile_spearman"],
        "strict_up": per_v[v]["quintile_strict_monotone_up"],
        "strict_down": per_v[v]["quintile_strict_monotone_down"],
        "by_value": per_v[v]["by_value"], "rank_corr": per_v[v]["rank_corr_value_vs_y"],
    }) for v in ALL_VINTAGES}
    out["missingness"] = {v: (None if not per_v.get(v) else {
        "n_measurable": per_v[v]["n_measurable"], "n_missing": per_v[v]["n_missing"],
        "p_measurable": per_v[v]["p_measurable"], "p_missing": per_v[v]["p_missing"],
        "missingness_lift": per_v[v]["missingness_lift"],
    }) for v in ALL_VINTAGES}
    return out


summaries10, summaries15 = {}, {}
for var in CANDIDATES:
    for pop in POPS:
        s = summarize(var, pop, cells10, MIN_NUM)
        if any(s["cuts"][c].get(v) for c in CUTNAMES for v in ALL_VINTAGES):
            summaries10[f"{var}|{pop}"] = s
        s2 = summarize(var, pop, cells15, MIN_NUM)
        if any(s2["cuts"][c].get(v) for c in CUTNAMES for v in ALL_VINTAGES):
            summaries15[f"{var}|{pop}"] = s2


# ────────────────────────────── ゲート4: 業種(sic2)調整 ──────────────────────────────
def mh_risk_diff(v, pop, var, cut, ykey="_y10"):
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


def drop_one_sector(v, pop, var, cut, ykey="_y10"):
    """業種を1つずつ抜いたときの最悪 lift（prereg の sector_control の後半）。"""
    R = pop_rows(v, pop)
    M = [(num(r.get(var)), 1 if r.get(ykey) else 0, r.get("sic2")) for r in R]
    Mm = [t for t in M if t[0] is not None]
    if len(Mm) < 20:
        return None
    vals = sorted(x for (x, _, _) in Mm)
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    pred = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
            "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    secs = sorted({s for (_, _, s) in M if s})
    worst = None
    for drop in secs:
        RR = [r for r in R if r.get("sic2") != drop]
        nb = len(RR)
        if nb < 40:
            continue
        kb = sum(1 for r in RR if r.get(ykey))
        grp = [r for r in RR if num(r.get(var)) is not None and pred(num(r.get(var)))]
        if len(grp) < 10:
            continue
        kg = sum(1 for r in grp if r.get(ykey))
        lift = kg / len(grp) - kb / nb
        ent = {"dropped_sector": drop, "n_group": len(grp), "k": kg, "lift": r4(lift)}
        if worst is None or abs(lift) < abs(worst["lift"]):
            worst = ent
    return worst


# ────────────────────────────── ゲート5: irr の影でないか ──────────────────────────────
def irr_control(v, pop, var, cut, ykey="_y10"):
    R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
    if len(R) < 20:
        return {"status": f"irr の読解がこのビンテージ・母集団で {len(R)} 行しかなく判定不能"}
    M = [(num(r.get(var)), 1 if r.get(ykey) else 0, r["irr"]) for r in R]
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
        res["irr_ge70"] = {"status": f"irr>=70 が {len(hi)} 行で判定不能"}
    return res


# ────────────────────────────── 検出力（δ=0.10/0.15/0.20・両方向） ──────────────────────────────
rnd = random.Random(SEED)
_binom_cache = {}


def binom_sampler(n, p):
    """逆CDF法。n が大きいので毎回ベルヌーイを回さない（速度のためだけ・分布は厳密）。"""
    key = (n, round(p, 6))
    if key in _binom_cache:
        return _binom_cache[key]
    logp = math.log(p) if p > 0 else -1e18
    log1p_ = math.log(1 - p) if p < 1 else -1e18
    lg = math.lgamma
    cdf, acc = [], 0.0
    for k in range(n + 1):
        lpmf = lg(n + 1) - lg(k + 1) - lg(n - k + 1) + k * logp + (n - k) * log1p_
        acc += math.exp(lpmf)
        cdf.append(min(acc, 1.0))
    cdf[-1] = 1.0
    _binom_cache[key] = cdf
    return cdf


def rbinom(n, p):
    return bisect.bisect_left(binom_sampler(n, p), rnd.random())


def power_sim(n, base, true_lift, min_num, n_sims=N_POWER):
    """真の lift を仕込んだときに手続き（|観測lift|>=0.15 ∧ 分子>=min_num ∧ 符号一致）が拾う確率。"""
    g = max(1, n // 4)
    rest = n - g
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = min(0.999, max(0.001, (base * n - p_g * g) / rest))
    single = 0
    triple = 0
    want = 1 if true_lift > 0 else -1
    for _ in range(n_sims):
        ok = []
        for _v in range(3):
            kg = rbinom(g, p_g)
            kr = rbinom(rest, p_r)
            b = (kg + kr) / n
            lift = kg / g - b
            ok.append((abs(lift) >= LIFT and kg >= min_num and (1 if lift > 0 else -1) == want,
                       1 if lift > 0 else -1))
        if ok[0][0]:
            single += 1
        if all(o[0] for o in ok) and len({o[1] for o in ok}) == 1:
            triple += 1
    return {"single_vintage": r4(single / n_sims), "three_independent": r4(triple / n_sims)}


power = {}
for pop in ("P_full", "P_quality"):
    cr = cell_reach10[f"2016/{pop}"]
    n_ref, base_ref = cr["n"], cr["base"]
    ent = {"n_used": n_ref, "base_used": base_ref, "up": {}, "down": {}}
    for L in (0.10, 0.15, 0.20):
        ent["up"][str(L)] = power_sim(n_ref, base_ref, L, MIN_NUM)
        dn = cell_reach10[f"2016/{pop}"]["down"]
        if dn["possible"] and (base_ref - L) * max(1, n_ref // 4) >= MIN_NUM:
            ent["down"][str(-L)] = power_sim(n_ref, base_ref, -L, MIN_NUM)
        else:
            ent["down"][str(-L)] = {"status": "分子>=20 と両立しない＝この幅の下向きは構造的に検出不能"}
    power[pop] = ent
power["_how_to_read"] = (
    "three_independent が下限・single_vintage が上限（3ビンテージが完全に同じ実現なら1回引ければ3回引ける）。"
    "実際の outcome の Spearman は 0.845〜0.961 なので真の検出力はこの間。"
    "**下向きは分子>=20 が上限として効く**ので、強い下向きほど検出力が落ちる——"
    "これは効果が無いことではなく、手続きの構造的な限界。")


# ────────────────────────────── 偽陽性率 ──────────────────────────────
tick_idx = {}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        if r["ticker"] not in tick_idx:
            tick_idx[r["ticker"]] = len(tick_idx)
N_T = len(tick_idx)

A_bits = {v: [0] * N_T for v in SIGN_VINTAGES}
Y_bits = {v: [0] * N_T for v in SIGN_VINTAGES}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        i = tick_idx[r["ticker"]]
        A_bits[v][i] = 1
        if r.get("_y10"):
            Y_bits[v][i] = 1


def bits_to_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


fpr_masks = []
FPR_POPS = ["P_full", "P_quality"]
for var in gate_reachable:
    for pop in FPR_POPS:
        per_v, ok = {}, True
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


def run_procedure(Aint, Yint, thresh=LIFT, want_stat=False, direction=None):
    """置換後の outcome で、ゲート1-3（lift・分子・符号不変）を通る候補を数える。
       direction=+1/-1 を指定するとその向きだけ数える（両方向を別々に見るため）。"""
    hits, stats = [], []
    for (var, pop, cut, mv) in fpr_masks:
        ok, signs, mins = True, set(), []
        for v in SIGN_VINTAGES:
            pm, mm_, gm = mv[v]
            a = Aint[v]
            npop = (pm & a).bit_count()
            kpop = (pm & Yint[v]).bit_count()
            ng = (gm & a).bit_count()
            kg = (gm & Yint[v]).bit_count()
            if npop == 0 or ng == 0 or kg < MIN_NUM:
                ok = False
                break
            lift = kg / ng - kpop / npop
            mins.append(abs(lift))
            signs.add(1 if lift > 0 else -1)
        if ok and len(signs) == 1 and (direction is None or list(signs)[0] == direction):
            stats.append(min(mins))
            if min(mins) >= thresh:
                hits.append((var, pop, cut))
        else:
            stats.append(0.0)
    return (hits, stats) if want_stat else hits


A0 = {v: bits_to_int(A_bits[v]) for v in SIGN_VINTAGES}
Y0 = {v: bits_to_int(Y_bits[v]) for v in SIGN_VINTAGES}
observed_hits = run_procedure(A0, Y0)
observed_up = run_procedure(A0, Y0, direction=1)
observed_dn = run_procedure(A0, Y0, direction=-1)

RELAX = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
perm_hits, perm_maxstat, perm_max_up, perm_max_dn = [], [], [], []
relax_any = {t: 0 for t in RELAX}
sigma = list(range(N_T))
t0 = time.time()
for _ in range(N_PERM):
    rnd.shuffle(sigma)
    Ai = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Yi = {v: perm_int(Y_bits[v], sigma) for v in SIGN_VINTAGES}
    _h, st = run_procedure(Ai, Yi, want_stat=True)
    mx = max(st) if st else 0.0
    perm_maxstat.append(mx)
    perm_hits.append(sum(1 for s in st if s >= LIFT))
    for t in RELAX:
        if mx >= t:
            relax_any[t] += 1
    _hu, stu = run_procedure(Ai, Yi, want_stat=True, direction=1)
    _hd, std_ = run_procedure(Ai, Yi, want_stat=True, direction=-1)
    perm_max_up.append(max(stu) if stu else 0.0)
    perm_max_dn.append(max(std_) if std_ else 0.0)
perm_secs = round(time.time() - t0, 1)

n_any = sum(1 for h in perm_hits if h > 0)
srt = sorted(perm_maxstat)


def pct(p, arr=None):
    a = arr if arr is not None else srt
    return r4(a[min(len(a) - 1, max(0, int(p * len(a)) - 1))])


_, obs_stats = run_procedure(A0, Y0, want_stat=True)
obs_max = max(obs_stats) if obs_stats else 0.0
_, obs_up_stats = run_procedure(A0, Y0, want_stat=True, direction=1)
_, obs_dn_stats = run_procedure(A0, Y0, want_stat=True, direction=-1)
obs_max_up = max(obs_up_stats) if obs_up_stats else 0.0
obs_max_dn = max(obs_dn_stats) if obs_dn_stats else 0.0
srt_up, srt_dn = sorted(perm_max_up), sorted(perm_max_dn)

fpr = {
    "n_permutations": N_PERM,
    "seconds": perm_secs,
    "n_tests_in_procedure": len(fpr_masks),
    "null_construction": ("特徴量側（母集団・可測・群）は固定し、outcome の束"
                          "(has_outcome∧window_full, y10)をティッカーごとまとめて置換する。"
                          "ビンテージ間の outcome 相関・欠測構造・P_quality の定義を保ったまま、"
                          "特徴量↔outcome だけを壊す。ビンテージ内で独立に混ぜると従属が壊れて"
                          "FPR を 33 倍過小評価することが既に実測されている。"),
    "P_at_least_one_pass": r4(n_any / N_PERM),
    "mean_passes_per_permutation": r4(sum(perm_hits) / N_PERM),
    "max_passes_in_a_permutation": max(perm_hits),
    "observed_passes_gates123": len(observed_hits),
    "observed_passes_up": len(observed_up),
    "observed_passes_down": len(observed_dn),
    "observed_hits": [{"variable": a, "population": b, "cut": c} for a, b, c in observed_hits],
    "null_distribution_of_max_statistic": {
        "statistic": f"{len(fpr_masks)}検定のうち最大の『符号が揃ったうえでの3ビンテージ最小|lift|』",
        "p50": pct(0.50), "p90": pct(0.90), "p95": pct(0.95), "p99": pct(0.99),
        "max_over_permutations": r4(max(perm_maxstat)),
        "observed_in_real_data": r4(obs_max),
        "empirical_p_of_observed": r4(sum(1 for m in perm_maxstat if m >= obs_max) / N_PERM),
    },
    "by_direction": {
        "up": {"observed_max_stat": r4(obs_max_up), "null_p95": pct(0.95, srt_up),
               "null_p99": pct(0.99, srt_up), "null_max": r4(max(perm_max_up)),
               "empirical_p": r4(sum(1 for m in perm_max_up if m >= obs_max_up) / N_PERM)},
        "down": {"observed_max_stat": r4(obs_max_dn), "null_p95": pct(0.95, srt_dn),
                 "null_p99": pct(0.99, srt_dn), "null_max": r4(max(perm_max_dn)),
                 "empirical_p": r4(sum(1 for m in perm_max_dn if m >= obs_max_dn) / N_PERM)},
        "note": "上向きと下向きを別々の帰無分布で見る。片方だけ見ると、両方向を探した多重性を隠せてしまう。",
    },
    "fpr_at_relaxed_thresholds": {
        "note": "**事前登録の外・診断専用**。合否には数えない。線を緩めたときに FPR が立ち上がることを示し、"
                "『0』が手続きの厳しさであって道具の故障でないことを見せるためだけにある。",
        "P_at_least_one_pass_by_threshold": {str(t): r4(relax_any[t] / N_PERM) for t in RELAX},
    },
}


# ────────────────────────────── 判定（prereg の6条件） ──────────────────────────────
def verdict_for(var, pop, cut, summaries, cells, cell_reach, ykey="_y10", min_num=MIN_NUM):
    s = summaries.get(f"{var}|{pop}")
    if not s:
        return None
    row = s["cuts"][cut]
    g = row["gate"]

    circ = (cells.get(f"{var}|{pop}|2018") or cells.get(f"{var}|{pop}|2013")
            or {}).get("circularity_with_population")
    if circ and "定数化" in circ:
        return {"verdict": "判定不能", "reason": f"母集団の定義そのもの＝{circ}",
                "gate_failed_at": "circularity"}
    if not var_vintage_cov[var]["sign_gate_evaluable"]:
        return {"verdict": "判定不能",
                "reason": "2016/2017/2018 のどれかにこの変数が存在せず、必須ゲート（符号不変）を当てられない",
                "gate_failed_at": "sign_stability(構造的に評価不能)"}
    if g.get("empty_group_vintages"):
        return {"verdict": "判定不能",
                "reason": f"タイが重くこの切り方で群が空になるビンテージが {g['empty_group_vintages']} 件",
                "gate_failed_at": "empty_group"}
    if g.get("sign_stability") in (None,) or isinstance(g.get("sign_stability"), str):
        return {"verdict": "判定不能", "reason": str(g.get("sign_stability")),
                "gate_failed_at": "sign_stability"}

    d = g.get("direction_3v")
    # 到達可能性は**その方向で**見る（下向きは分子上限が効く）
    reach_bad = []
    for v in SIGN_VINTAGES:
        cr = cell_reach.get(f"{v}/{pop}", {})
        if cr.get("n", 0) == 0:
            reach_bad.append(v)
            continue
        side = cr.get("up" if (d == 1 or d is None) else "down", {})
        if side.get("possible") is False:
            reach_bad.append(v)
    if reach_bad:
        return {"verdict": "判定不能",
                "reason": (f"その方向（{'増やす' if d == 1 else '減らす'}）では "
                           f"lift>=0.15 と分子>={min_num} が同時に成立しないビンテージがある: {reach_bad}"),
                "gate_failed_at": "reachability", "direction": d}
    if g.get("sign_stability") is not True:
        return {"verdict": "不合格", "reason": "2016/2017/2018 で符号が反転する",
                "gate_failed_at": "sign_stability"}
    if g.get("min_num_all3") is False:
        return {"verdict": "不合格", "reason": f"分子>={min_num}社 を満たさないビンテージがある"
                                               f"（実測 {g.get('numerators_3v')}）",
                "gate_failed_at": "min_numerator"}
    if g.get("lift_all3") is False:
        return {"verdict": "不合格",
                "reason": f"|lift|>={LIFT} を3ビンテージで維持できない（最小 {g.get('min_abs_lift_3v')}）",
                "gate_failed_at": "lift"}

    # 費用の高いゲートはここまで通ったものだけ
    mh = {str(v): mh_risk_diff(v, pop, var, cut, ykey) for v in SIGN_VINTAGES}
    dos = {str(v): drop_one_sector(v, pop, var, cut, ykey) for v in SIGN_VINTAGES}
    mh_ok = all(m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT
                and (1 if m["mh_risk_diff"] > 0 else -1) == d for m in mh.values())
    dos_ok = all(w and w["lift"] is not None and abs(w["lift"]) >= LIFT
                 and (1 if w["lift"] > 0 else -1) == d for w in dos.values())
    if not (mh_ok and dos_ok):
        return {"verdict": "不合格",
                "reason": ("同一 sic2 内（MH重み付きリスク差）" if not mh_ok else "業種を1つ抜く")
                          + " で 0.15 を維持できない",
                "gate_failed_at": "sector_control", "mh": mh, "drop_one_sector": dos}

    ic = {str(v): irr_control(v, pop, var, cut, ykey) for v in (2018,)}
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

    # ゲート6: 既存の関門との増分（方向で当てるものが違う・設計5）
    inc_by_v = {}
    for v in SIGN_VINTAGES:
        c = (cells.get(f"{var}|{pop}|{v}") or {}).get("cuts", {}).get(cut, {})
        inc_by_v[str(v)] = c.get("incremental")
    if d == -1:
        tot = sum((inc_by_v[str(v)] or {}).get("down_side", {}).get("n_failures_in_group", 0)
                  for v in SIGN_VINTAGES)
        caught = sum((inc_by_v[str(v)] or {}).get("down_side", {}).get(
            "already_caught_by_existing_gates", 0) for v in SIGN_VINTAGES)
        share = (caught / tot) if tot else None
        inc_ok = (share is not None and share <= INCREMENTAL_MAX_CAUGHT)
        inc_detail = {"applied": "下向き＝群の10%未満だった社のうち既存関門で既に落ちている割合",
                      "n_failures": tot, "caught": caught, "caught_share": r4(share),
                      "line": INCREMENTAL_MAX_CAUGHT, "pass": inc_ok, "by_vintage": inc_by_v}
    else:
        ls = [(inc_by_v[str(v)] or {}).get("up_side", {}).get("lift_within_gate_passers")
              for v in SIGN_VINTAGES]
        inc_ok = all(x is not None and abs(x) >= LIFT and (1 if x > 0 else -1) == d for x in ls)
        inc_detail = {"applied": "上向き＝既存関門を通る社だけに絞って測り直した lift",
                      "lift_within_gate_passers_3v": ls, "line": LIFT, "pass": inc_ok,
                      "by_vintage": inc_by_v}
    if not inc_ok:
        return {"verdict": "不合格", "reason": "既存の関門で説明され、増分が無い",
                "gate_failed_at": "incremental", "mh": mh, "irr": ic, "incremental": inc_detail}

    return {"verdict": "合格", "reason": "prereg の6条件すべてを満たす",
            "direction": d, "mh": mh, "drop_one_sector": dos, "irr": ic, "incremental": inc_detail}


# ────────── 陽性対照（注入検査）: 上向き・下向きの両方で道具が本物を掴めるか ──────────
def inject_control(true_lift, key):
    for v in ALL_VINTAGES:
        R = pop_rows(v, "P_full")
        n = len(R)
        g = max(1, n // 4)
        ev = sum(1 for r in R if r.get("_y10"))
        base = ev / n
        k_want = int(round((base + true_lift) * g))
        k_want = max(0, min(k_want, ev, g))
        wins = [r for r in R if r.get("_y10")]
        loss = [r for r in R if not r.get("_y10")]
        rnd.shuffle(wins)
        rnd.shuffle(loss)
        grp = wins[:k_want] + loss[:g - k_want]
        gs = {id(r) for r in grp}
        for r in R:
            r[key] = (0.75 + rnd.random() * 0.25) if id(r) in gs else (rnd.random() * 0.74)
        for r in by_v[v]:
            if key not in r:
                r[key] = None


positive_control = {}
for L, key in ((0.25, "_ctrlUp25"), (0.15, "_ctrlUp15"),
               (-0.25, "_ctrlDn25"), (-0.15, "_ctrlDn15")):
    inject_control(L, key)
    var_vintage_cov[key] = {"coverage": {}, "sign_gate_evaluable": True, "all5_vintages": True,
                            "gate_note": "合成（陽性対照）"}
    tmp_cells, tmp_sum = {}, {}
    for pop in POPS:
        for v in ALL_VINTAGES:
            m = measure(v, pop, key, "_y10", MIN_NUM)
            if m:
                tmp_cells[f"{key}|{pop}|{v}"] = m
    tmp_sum[f"{key}|P_full"] = summarize(key, "P_full", tmp_cells, MIN_NUM)
    vd = verdict_for(key, "P_full", "上位1/4", tmp_sum, tmp_cells, cell_reach10)
    s3 = tmp_sum[f"{key}|P_full"]["cuts"]["上位1/4"]["gate"]
    positive_control[f"true_lift={L:+.2f}"] = {
        "verdict": vd["verdict"], "reason": vd["reason"], "gate_failed_at": vd.get("gate_failed_at"),
        "observed_lifts_161718": s3.get("signed_lifts_3v"),
        "numerators_161718": s3.get("numerators_3v"),
        "sign_stability": s3.get("sign_stability"),
    }
    var_vintage_cov.pop(key, None)
    for r in rows_all:
        r.pop(key, None)
positive_control["_how_to_read"] = (
    "真の lift ±0.25 で合格が出て、±0.15（線ぴったり）では出たり出なかったりするのが正しい挙動。"
    "**下向き -0.25 が『判定不能(min_numerator)』で落ちるなら、それは道具の故障ではなく設計4の構造**"
    "——強い下向きは分子>=20 と両立しない。合否の読み方がそこで変わるので必ず見ること。")


# ────────────────────────────── 判定を全セルへ ──────────────────────────────
verdicts10, verdicts15 = {}, {}
for var in CANDIDATES:
    for pop in POPS:
        for cut in CUTNAMES:
            if f"{var}|{pop}" in summaries10:
                vd = verdict_for(var, pop, cut, summaries10, cells10, cell_reach10, "_y10", MIN_NUM)
                if vd:
                    verdicts10[f"{var}|{pop}|{cut}"] = vd
            if f"{var}|{pop}" in summaries15:
                vd = verdict_for(var, pop, cut, summaries15, cells15, cell_reach15, "_y15", MIN_NUM)
                if vd:
                    verdicts15[f"{var}|{pop}|{cut}"] = vd


# ────────────────────────────── 序列 ──────────────────────────────
def rank_table(summaries, cells, verdicts):
    rows = []
    for key, s in summaries.items():
        var, pop = key.split("|")
        for cut in CUTNAMES:
            row = s["cuts"][cut]
            g = row["gate"]
            got = [(v, row[v]) for v in ALL_VINTAGES if row.get(v) and row[v]["lift"] is not None]
            if not got:
                continue
            if g.get("min_abs_lift_3v") is not None and g.get("sign_stability") is True:
                score = g["min_abs_lift_3v"]
                basis = "3ビンテージで符号が揃ったうえでの最小|lift|"
            elif g.get("min_abs_lift_3v") is not None:
                score = -1.0 + g["min_abs_lift_3v"]
                basis = "3ビンテージで符号が割れた（下位へ）"
            else:
                ls = sorted(abs(x[1]["lift"]) for x in got)
                score = ls[len(ls) // 2]
                basis = "3ビンテージそろわず＝測れたビンテージの|lift|の中央値（判定不能）"
            anchor_v = 2018 if (row.get(2018) and row[2018]["lift"] is not None) else got[-1][0]
            a = row[anchor_v]
            mi = s["missingness"].get(anchor_v) or {}
            gap = (None if a["lift"] is None or a["lift_meas"] is None
                   else round(abs(a["lift"]) - abs(a["lift_meas"]), 4))
            mono = s["monotonicity"].get(anchor_v) or {}
            rows.append({
                "variable": var, "population": pop, "cut": cut,
                "direction": ("増やす" if g.get("direction_3v") == 1 else
                              ("減らす" if g.get("direction_3v") == -1 else a.get("direction"))),
                "rank_score": r4(score), "rank_basis": basis,
                "anchor_vintage": anchor_v,
                "n_group": a["n_group"], "numerator": a["k"],
                "p_group": a["p_group"], "p_base": a["p_base"], "lift_anchor": a["lift"],
                "lift_by_vintage": {str(v): (row[v]["lift"] if row.get(v) else None) for v in ALL_VINTAGES},
                "numerator_by_vintage": {str(v): (row[v]["k"] if row.get(v) else None) for v in ALL_VINTAGES},
                "n_group_by_vintage": {str(v): (row[v]["n_group"] if row.get(v) else None) for v in ALL_VINTAGES},
                "sign_stable_161718": g.get("sign_stability"),
                "min_abs_lift_161718": g.get("min_abs_lift_3v"),
                "sign_agree_2013_2015": g.get("sign_agree_2013_2015"),
                "quintile_spearman_anchor": mono.get("spearman"),
                "quintile_strict_up_anchor": mono.get("strict_up"),
                "quintile_strict_down_anchor": mono.get("strict_down"),
                "quintiles_anchor": mono.get("quintiles"),
                "tie_degenerate_anchor": a.get("tie_degenerate", False),
                "coverage_anchor": (None if not mi else
                                    r4(rate(mi["n_measurable"], mi["n_measurable"] + mi["n_missing"]))),
                "n_missing_anchor": mi.get("n_missing"),
                "missingness_lift_anchor": mi.get("missingness_lift"),
                "missingness_lift_readable": (mi.get("n_missing", 0) >= 20),
                "lift_shrink_when_missingness_removed": gap,
                "missingness_confounded": (gap is not None and gap >= 0.03),
                "verdict": verdicts.get(f"{var}|{pop}|{cut}", {}).get("verdict"),
                "verdict_reason": verdicts.get(f"{var}|{pop}|{cut}", {}).get("reason"),
                "gate_failed_at": verdicts.get(f"{var}|{pop}|{cut}", {}).get("gate_failed_at"),
            })
    rows.sort(key=lambda r: -(r["rank_score"] if r["rank_score"] is not None else -9))
    return rows


rank10 = rank_table(summaries10, cells10, verdicts10)
rank15 = rank_table(summaries15, cells15, verdicts15)
top30 = rank10[:30]

gate_eval = [r for r in rank10 if r["sign_stable_161718"] is True
             and r["min_abs_lift_161718"] is not None]
gate_eval.sort(key=lambda r: -r["min_abs_lift_161718"])
top_gate_evaluable = gate_eval[:30]

# 方向別の上位
top_up = [r for r in gate_eval if r["direction"] == "増やす"][:15]
top_down = [r for r in gate_eval if r["direction"] == "減らす"][:15]

for r in top_gate_evaluable[:15]:
    r["diagnostics_sector_mh"] = {str(v): mh_risk_diff(v, r["population"], r["variable"], r["cut"])
                                  for v in SIGN_VINTAGES}
    r["diagnostics_drop_one_sector"] = {str(v): drop_one_sector(v, r["population"], r["variable"], r["cut"])
                                        for v in SIGN_VINTAGES}
    r["diagnostics_irr_control_2018"] = irr_control(2018, r["population"], r["variable"], r["cut"])


# ────────────── 15%版との突き合わせ（まず再現・つぎに比較） ──────────────
v15pub = None
if os.path.exists(V15):
    v15pub = json.load(open(V15, encoding="utf-8"))

reproduction = {"status": "参照ファイルが無い"}
if v15pub:
    # v1 と同じ MIN_NUM=5 で 15% を測り直し、公表 lift と突き合わせる
    pub = {}
    for r in v15pub.get("top_gate_evaluable", []) + v15pub.get("top30_by_lift", []):
        pub[f"{r['variable']}|{r['population']}|{r['cut']}"] = r
    diffs, checked, mism = [], 0, 0
    for k, pr in pub.items():
        var, pop, cut = k.split("|")
        m = cells15.get(f"{var}|{pop}|{pr['anchor_vintage']}")
        if not m:
            continue
        mine = m["cuts"][cut]["lift_vs_pop"]
        theirs = pr.get("lift_anchor")
        if mine is None or theirs is None:
            continue
        checked += 1
        d = round(abs(mine - theirs), 6)
        if d > 1e-9:
            mism += 1
            diffs.append({"key": k, "anchor": pr["anchor_vintage"], "mine": mine, "published": theirs})
    reproduction = {
        "what": "この道具の measure() を hurdle=0.15 で回し、公表 hist_wd_win_uni.json の lift_anchor と突合",
        "n_checked": checked, "n_mismatch": mism,
        "mismatches": diffs[:20],
        "verdict": ("完全一致＝同じものを測っている。以降の『10% vs 15%』は hurdle だけの差"
                    if mism == 0 else "食い違いあり＝比較の前にここを解くこと"),
    }

# 比較本体: MIN_NUM を 20 に揃え、hurdle だけを 0.10 / 0.15 で振る
idx10 = {f"{r['variable']}|{r['population']}|{r['cut']}": r for r in rank10}
idx15 = {f"{r['variable']}|{r['population']}|{r['cut']}": r for r in rank15}
comp_rows = []
for k in sorted(set(idx10) | set(idx15)):
    a, b = idx10.get(k), idx15.get(k)

    def qual(r):
        return bool(r and r["sign_stable_161718"] is True
                    and r["min_abs_lift_161718"] is not None
                    and r["min_abs_lift_161718"] >= LIFT)
    q10, q15 = qual(a), qual(b)
    comp_rows.append({
        "key": k,
        "variable": k.split("|")[0], "population": k.split("|")[1], "cut": k.split("|")[2],
        "direction_10": a["direction"] if a else None,
        "direction_15": b["direction"] if b else None,
        "maintained_lift_10": a["min_abs_lift_161718"] if a else None,
        "maintained_lift_15": b["min_abs_lift_161718"] if b else None,
        "sign_stable_10": a["sign_stable_161718"] if a else None,
        "sign_stable_15": b["sign_stable_161718"] if b else None,
        "verdict_10": a["verdict"] if a else None,
        "verdict_15": b["verdict"] if b else None,
        "gate_failed_10": a["gate_failed_at"] if a else None,
        "gate_failed_15": b["gate_failed_at"] if b else None,
        "class": ("10%で新出" if (q10 and not q15) else
                  ("15%にあって10%で消えた" if (q15 and not q10) else
                   ("両方" if (q10 and q15) else "どちらも線に届かない"))),
        "delta_maintained_lift": (r4(a["min_abs_lift_161718"] - b["min_abs_lift_161718"])
                                  if (a and b and a["min_abs_lift_161718"] is not None
                                      and b["min_abs_lift_161718"] is not None) else None),
    })
cls = Counter(r["class"] for r in comp_rows)
new_at_10 = sorted([r for r in comp_rows if r["class"] == "10%で新出"],
                   key=lambda r: -(r["maintained_lift_10"] or 0))
lost_at_10 = sorted([r for r in comp_rows if r["class"] == "15%にあって10%で消えた"],
                    key=lambda r: -(r["maintained_lift_15"] or 0))
both = sorted([r for r in comp_rows if r["class"] == "両方"],
              key=lambda r: -(r["maintained_lift_10"] or 0))
# 最も動いた（絶対差）上位
moved = sorted([r for r in comp_rows if r["delta_maintained_lift"] is not None],
               key=lambda r: -abs(r["delta_maintained_lift"]))[:25]

# 公表 v1（MIN_NUM=5）の上位を、そのまま名指しで並べる
published_side_by_side = []
if v15pub:
    for pr in v15pub.get("top_gate_evaluable", [])[:20]:
        k = f"{pr['variable']}|{pr['population']}|{pr['cut']}"
        a = idx10.get(k)
        published_side_by_side.append({
            "key": k, "variable": pr["variable"], "population": pr["population"], "cut": pr["cut"],
            "v1_published": {
                "maintained_lift_15pct": pr.get("min_abs_lift_161718"),
                "lift_by_vintage": pr.get("lift_by_vintage"),
                "numerator_anchor": pr.get("numerator"),
                "verdict_v1_minnum5": pr.get("verdict"),
                "gate_failed_v1": pr.get("gate_failed_at"),
            },
            "at_10pct_same_procedure": (None if not a else {
                "direction": a["direction"],
                "maintained_lift_10pct": a["min_abs_lift_161718"],
                "lift_by_vintage": a["lift_by_vintage"],
                "numerator_by_vintage": a["numerator_by_vintage"],
                "verdict": a["verdict"], "gate_failed_at": a["gate_failed_at"],
            }),
            "moved": (None if not a or a["min_abs_lift_161718"] is None
                      or pr.get("min_abs_lift_161718") is None
                      else r4(a["min_abs_lift_161718"] - pr["min_abs_lift_161718"])),
        })

# 線に最も近づいた2本は、落ちた先の**続き**まで測っておく
#   ——「線で落ちた」ことと「その先も落ちる」ことは別の情報で、次に線が動いたとき最初に効くのはここ。
near_miss = []
for k in [r["key"] for r in new_at_10]:
    var, pop, cut = k.split("|")
    a = idx10[k]
    inc_by_v = {}
    for v in SIGN_VINTAGES:
        c = (cells10.get(f"{var}|{pop}|{v}") or {}).get("cuts", {}).get(cut, {})
        inc_by_v[str(v)] = c.get("incremental")
    tot = sum((inc_by_v[str(v)] or {}).get("down_side", {}).get("n_failures_in_group", 0)
              for v in SIGN_VINTAGES)
    caught = sum((inc_by_v[str(v)] or {}).get("down_side", {}).get(
        "already_caught_by_existing_gates", 0) for v in SIGN_VINTAGES)
    near_miss.append({
        "key": k, "direction": a["direction"],
        "maintained_lift": a["min_abs_lift_161718"],
        "lift_by_vintage": a["lift_by_vintage"],
        "numerator_by_vintage": a["numerator_by_vintage"],
        "n_group_by_vintage": a["n_group_by_vintage"],
        "verdict": a["verdict"], "gate_failed_at": a["gate_failed_at"],
        "quintiles_2018": a.get("quintiles_anchor"),
        "quintile_spearman_2018": a.get("quintile_spearman_anchor"),
        "sign_agree_2013_2015": a.get("sign_agree_2013_2015"),
        "coverage_anchor": a.get("coverage_anchor"),
        "missingness_lift_anchor": a.get("missingness_lift_anchor"),
        "missingness_lift_readable": a.get("missingness_lift_readable"),
        # 落ちた先の残りのゲートも当てておく（診断・合否は変えない）
        "sector_mh": {str(v): mh_risk_diff(v, pop, var, cut, "_y10") for v in SIGN_VINTAGES},
        "drop_one_sector": {str(v): drop_one_sector(v, pop, var, cut, "_y10") for v in SIGN_VINTAGES},
        "irr_control_2018": irr_control(2018, pop, var, cut, "_y10"),
        "incremental_down_side": {
            "n_failures": tot, "already_caught_by_existing_gates": caught,
            "caught_share": r4(rate(caught, tot)),
            "line": INCREMENTAL_MAX_CAUGHT,
            "would_pass": (tot > 0 and rate(caught, tot) <= INCREMENTAL_MAX_CAUGHT),
            "by_vintage": inc_by_v,
        },
        "reachability_ceiling_down_population_basis": {
            str(v): cell_reach10[f"{v}/{pop}"]["down"]["max_detectable_lift"] for v in SIGN_VINTAGES},
        "reachability_coverage_adjusted": {str(v): reach_var(v, pop, var) for v in SIGN_VINTAGES},
    })


# ────────────────────────────── 出力 ──────────────────────────────
counts = Counter(v["verdict"] for v in verdicts10.values())
fail_at = Counter(v.get("gate_failed_at") for v in verdicts10.values() if v["verdict"] == "不合格")
undet_at = Counter(v.get("gate_failed_at") for v in verdicts10.values() if v["verdict"] == "判定不能")

doc = {
    "generated": "2026-08-12",
    "tool": "night/hist10_angleA.py",
    "prereg": "out/hist10_prereg.json",
    "panel": "out/hist_wd_panel.json",
    "objective": ("角度A_目的: P(実現年率 tr_cagr >= +10%)。**両方向**（増やす向き・減らす向き）。"
                  "⚠ 10% は同期間の指数(14.2〜15.2%)に負ける水準＝『勝つ』ではなく『複利が立つ』の線。"),
    "pass_line_used": {
        "lift": LIFT, "min_numerator": MIN_NUM,
        "sign_stability_vintages": SIGN_VINTAGES,
        "sector_control": "同一sic2内のMH重み付きリスク差 |RD|>=0.15 ∧ 業種を1つ抜いても |lift|>=0.15（符号も一致）",
        "not_irr_shadow": "irr>=70層内で |lift|>=0.15、または変数とirrが直交(|rho|<0.15)",
        "incremental": f"既存関門で説明される社が {INCREMENTAL_MAX_CAUGHT:.0%} を超えたら不合格"
                       "（下向き＝群の失敗社の被説明率／上向き＝関門通過者内での lift 維持）",
        "note": "prereg のまま。この道具は線を一つも作っていない。",
    },
    "design_decisions": {
        "analysis_set": "has_outcome ∧ window_full（15%版と同一）",
        "both_directions": "新しい切り方は作らず、既存4切りの lift の符号で表す。到達可能性・検出力・陽性対照は上下別々",
        "min_numerator_is_a_ceiling_downward": "下向きでは分子>=20 が**上限**として効く。検出可能な最大の下向き幅は base-20/群サイズ",
        "incremental_by_direction": "下向き＝群の失敗社の被説明率／上向き＝既存関門を通る社だけでの lift 維持",
        "existing_gates": "質実証(P_quality) / 事業の収縮(f2_cagr5<0 ∧ f2_opmD5<0) / 薄い財務(f2_intcov<3)。v2 の破壊側検証と同一定義＝新しい定数を作らない",
        "comparison_method": "公表15%版を同じコードで再現してから、MIN_NUM を 20 に揃えて hurdle だけを振る",
    },
    "analysis_set_size": {str(v): {
        "n": len(by_v[v]),
        "y10": sum(1 for r in by_v[v] if r.get("_y10")),
        "y15": sum(1 for r in by_v[v] if r.get("_y15")),
        "P10": r4(rate(sum(1 for r in by_v[v] if r.get("_y10")), len(by_v[v]))),
        "P15": r4(rate(sum(1 for r in by_v[v] if r.get("_y15")), len(by_v[v]))),
    } for v in ALL_VINTAGES},
    "must_report_before_verdict": {
        "reachability_10pct_both_directions": cell_reach10,
        "reachability_15pct_same_min_num": cell_reach15,
        "reachability_15pct_v1_min_num5": cell_reach15_v1,
        "reachability_coverage_adjusted_by_variable": {
            f"{var}|{pop}|{v}": reach_var(v, pop, var)
            for var in gate_reachable for pop in ("P_full", "P_quality") for v in SIGN_VINTAGES
            if reach_var(v, pop, var)},
        "reachability_coverage_adjusted_note": (
            "四分位は母集団ではなく**その変数を測れた部分集合**で切る。被覆が薄い変数ほど群が小さく、"
            "下向きの検出上限（base - 20/群サイズ）が母集団基準より厳しくなる。"
            "**セル単位の表はこれを見落とす**ので、変数ごとの版で読むこと。"),
        "down_uncertifiable_variables": None,   # 下で埋める
        "reachability_headline": None,   # 下で埋める
        "gate_reachability_by_variable": var_vintage_cov,
        "gate_reachable_variables": gate_reachable,
        "gate_unreachable_variables": gate_unreachable,
        "power": power,
        "false_positive_rate": fpr,
        "positive_control_injection": positive_control,
    },
    "verdict_counts": {"by_verdict": dict(counts),
                       "fail_gate_histogram": dict(fail_at),
                       "undetermined_gate_histogram": dict(undet_at),
                       "n_pass": counts.get("合格", 0)},
    "top30_by_lift": top30,
    "top30_by_lift_note": ("生の |lift| 順。上位は判定不能セル（P_moat の n=61〜63 など）が占めうる。"
                           "『大きい lift』と『確かな lift』は別物なので、答えは top_gate_evaluable で読むこと。"),
    "top_gate_evaluable": top_gate_evaluable,
    "top_up_15": top_up,
    "top_down_15": top_down,
    "comparison_with_15pct": {
        "reproduction_of_published_v1": reproduction,
        "method": "MIN_NUM=20 に揃え hurdle だけ 0.10/0.15 で振る（v1 公表は MIN_NUM=5 なので直接は比べない）",
        "class_counts": dict(cls),
        "new_at_10": new_at_10,
        "lost_at_10": lost_at_10,
        "both": both,
        "most_moved": moved,
        "published_v1_top_side_by_side": published_side_by_side,
        "published_v1_note": ("v1 の公表は MIN_NUM=5、こちらは prereg どおり 20。"
                              "**直接は比べられない**ので、v1 の公表値はそのまま引用し、"
                              "同じ (変数,母集団,切り方) を 10% で測り直した値を隣に置いてある。"),
    },
    "near_miss_full_diagnostics": near_miss,
    "near_miss_note": ("線に最も近づいた2本について、落ちた先の残りのゲートまで当てた結果。"
                       "**合否は変えていない**（どちらも prereg で不合格）。"
                       "次に線が動いたときに最初に効くのがここなので、記録として残す。"),
    "summaries_10pct": summaries10,
    "verdicts_10pct": verdicts10,
    "summaries_15pct": summaries15,
    "verdicts_15pct": verdicts15,
    "cells_10pct": cells10,
}

# 被覆調整後に「下向きが原理的に certify できない」変数を名指しする
rv = doc["must_report_before_verdict"]["reachability_coverage_adjusted_by_variable"]
bad_down = sorted({k.rsplit("|", 1)[0] for k, x in rv.items() if x and not x["down_certifiable"]})
doc["must_report_before_verdict"]["down_uncertifiable_variables"] = {
    "n": len(bad_down), "keys": bad_down,
    "meaning": ("被覆で調整すると、この (変数,母集団) は下向きの lift が 0.15 に届く前に"
                "分子>=20 を割る＝**どんなに強い下向きでも合格を出せない**。"
                "不合格ではなく構造的な判定不能。結果を見る前に数えるべきだった量。"),
}

# 到達可能性の見出し（両方向・10 vs 15）
dn10 = sum(1 for k, c in cell_reach10.items() if c.get("down", {}).get("possible"))
dn15 = sum(1 for k, c in cell_reach15.items() if c.get("down", {}).get("possible"))
dn15v1 = sum(1 for k, c in cell_reach15_v1.items() if c.get("down", {}).get("possible"))
up10 = sum(1 for k, c in cell_reach10.items() if c.get("up", {}).get("possible"))
up15 = sum(1 for k, c in cell_reach15.items() if c.get("up", {}).get("possible"))
ncell = sum(1 for c in cell_reach10.values() if c.get("n", 0) > 0)
doc["must_report_before_verdict"]["reachability_headline"] = {
    "n_cells": ncell,
    "up_possible_10pct": up10, "up_possible_15pct": up15,
    "down_possible_10pct": dn10, "down_possible_15pct_same_rule": dn15,
    "down_possible_15pct_v1_rule_minnum5": dn15v1,
    "note": ("prereg の『10%にすると減らす向きが到達可能になる』を実測で確認する欄。"
             "下向きは 15%（同じ分子>=20）では到達可能セルがごくわずかで、10% にして初めて開く。"
             "⚠ ただし開いた先も帯は狭い——P_quality では検出可能な下向き幅の上限が "
             "-0.166〜-0.244 しかなく、それより強い下向きは『強すぎて判定不能』になる。"),
}

json.dump(doc, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ────────────────────────────── 画面 ──────────────────────────────
print("解析集合: " + " / ".join(
    f"{v}:{len(by_v[v])}行(10%+ {sum(1 for r in by_v[v] if r.get('_y10'))} / 15%+ {sum(1 for r in by_v[v] if r.get('_y15'))})"
    for v in ALL_VINTAGES))

print("\n■ 到達可能性（結果の前に・両方向）")
h = doc["must_report_before_verdict"]["reachability_headline"]
print(f"  セル{h['n_cells']}: 上向き可 10%={h['up_possible_10pct']} / 15%={h['up_possible_15pct']}")
print(f"                 下向き可 10%={h['down_possible_10pct']} / 15%(同じ分子20)={h['down_possible_15pct_same_rule']}"
      f" / 15%(v1の分子5)={h['down_possible_15pct_v1_rule_minnum5']}")
for k in ["2016/P_full", "2016/P_quality", "2018/P_full", "2018/P_quality"]:
    c = cell_reach10[k]
    print(f"    {k:16s} n={c['n']:4d} base={c['base']} 上:必要{c['up']['k_needed']}社({c['up']['binding']}) "
          f"下:{'可' if c['down']['possible'] else '不可'} 最大下向き={c['down']['max_detectable_lift']}")

print("\n■ 検出力（3ビンテージ独立＝下限 / 単一＝上限）")
for pop in ("P_full", "P_quality"):
    d = power[pop]
    for L in ("0.1", "0.15", "0.2"):
        u = d["up"].get(L) or d["up"].get(str(float(L)))
        print(f"  {pop:10s} 上向き真lift=+{L}: 下限 {u['three_independent']} / 上限 {u['single_vintage']}")
    for L in ("-0.1", "-0.15", "-0.2"):
        dd = d["down"].get(L)
        if "status" in dd:
            print(f"  {pop:10s} 下向き真lift={L}: {dd['status']}")
        else:
            print(f"  {pop:10s} 下向き真lift={L}: 下限 {dd['three_independent']} / 上限 {dd['single_vintage']}")

print(f"\n■ 偽陽性率（置換{N_PERM}回・会社単位で全ビンテージ同時・{perm_secs}秒）")
print(f"  検定数 {fpr['n_tests_in_procedure']} / 偶然に1本以上通る確率 {fpr['P_at_least_one_pass']}")
print(f"  実データでゲート1-3を通ったのは {fpr['observed_passes_gates123']} 本"
      f"（上向き {fpr['observed_passes_up']} / 下向き {fpr['observed_passes_down']}）")
nd = fpr["null_distribution_of_max_statistic"]
print(f"  帰無の最大統計量: p50={nd['p50']} p95={nd['p95']} p99={nd['p99']} 最大={nd['max_over_permutations']}"
      f" ／ 実データ={nd['observed_in_real_data']} (経験p={nd['empirical_p_of_observed']})")
bd = fpr["by_direction"]
print(f"  方向別: 上 実測={bd['up']['observed_max_stat']} 帰無p95={bd['up']['null_p95']} p={bd['up']['empirical_p']}"
      f" ／ 下 実測={bd['down']['observed_max_stat']} 帰無p95={bd['down']['null_p95']} p={bd['down']['empirical_p']}")
print("  線を緩めたときの FPR: " + " ".join(
    f"{k}→{v}" for k, v in fpr["fpr_at_relaxed_thresholds"]["P_at_least_one_pass_by_threshold"].items()))

print("\n■ 陽性対照（注入検査）")
for k, v in positive_control.items():
    if k.startswith("_"):
        continue
    print(f"  {k} → {v['verdict']}({v.get('gate_failed_at') or ''}) lifts={v['observed_lifts_161718']} k={v['numerators_161718']}")

print("\n■ 15%版の再現")
print(f"  {reproduction.get('n_checked')}セル照合 / 食い違い {reproduction.get('n_mismatch')} → {reproduction.get('verdict')}")

print("\n■ 判定: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
print(f"  不合格の内訳: {dict(fail_at)}")
print(f"  判定不能の内訳: {dict(undet_at)}")

print("\n■ 判定を当てられるセルの中で維持できた |lift| 上位20  ← これが答え")
for r in top_gate_evaluable[:20]:
    ls = r["lift_by_vintage"]
    print(f"  {r['min_abs_lift_161718']:.3f} [{r['direction']}] {r['variable']:15s}{r['population']:10s}{r['cut']:6s} "
          f"16/17/18={ls['2016']}/{ls['2017']}/{ls['2018']} k={r['numerator']} → {r['verdict']}"
          f"({r['gate_failed_at'] or ''})")

print("\n■ 10% vs 15%（分子20で揃えて hurdle だけ振る）")
print("  " + " / ".join(f"{k} {v}" for k, v in cls.items()))
print(f"  10%で新出 {len(new_at_10)} 本:")
for r in new_at_10[:15]:
    print(f"    {r['maintained_lift_10']:.3f} [{r['direction_10']}] {r['variable']:15s}{r['population']:10s}"
          f"{r['cut']:6s} (15%では {r['maintained_lift_15']} / {r['gate_failed_15']}) → {r['verdict_10']}"
          f"({r['gate_failed_10'] or ''})")
print(f"  15%にあって10%で消えた {len(lost_at_10)} 本:")
for r in lost_at_10[:15]:
    print(f"    {r['maintained_lift_15']:.3f} [{r['direction_15']}] {r['variable']:15s}{r['population']:10s}"
          f"{r['cut']:6s} (10%では {r['maintained_lift_10']} / {r['gate_failed_10']})")
print(f"  両方 {len(both)} 本:")
for r in both[:15]:
    print(f"    10%={r['maintained_lift_10']:.3f} 15%={r['maintained_lift_15']:.3f} [{r['direction_10']}] "
          f"{r['variable']:15s}{r['population']:10s}{r['cut']:6s} → {r['verdict_10']}")

print("\n■ v1 公表(15%・分子5)の上位10 を、そのまま 10% で測り直す")
for r in published_side_by_side[:10]:
    b = r["at_10pct_same_procedure"]
    print(f"  {r['variable']:15s}{r['population']:10s}{r['cut']:6s} "
          f"15%公表={r['v1_published']['maintained_lift_15pct']} → "
          f"10%={None if not b else b['maintained_lift_10pct']} [{None if not b else b['direction']}] "
          f"{None if not b else b['verdict']}({None if not b else (b['gate_failed_at'] or '')})")

print("\n■ 線に最も近づいた2本の『その先』（診断・合否は変えない）")
for r in near_miss:
    inc = r["incremental_down_side"]
    print(f"  {r['key']}  維持lift={r['maintained_lift']} 分子={list(r['numerator_by_vintage'].values())[2:]}")
    print(f"    → {r['verdict']}({r['gate_failed_at']})")
    print(f"    業種MH: {[ (v, (m or {}).get('mh_risk_diff')) for v,m in r['sector_mh'].items() ]}")
    print(f"    業種1つ抜き最悪: {[ (v,(w or {}).get('lift')) for v,w in r['drop_one_sector'].items() ]}")
    print(f"    増分(下向き): 失敗{inc['n_failures']}社中 既存関門が{inc['already_caught_by_existing_gates']}社"
          f"={inc['caught_share']} → 線{inc['line']} で {'通る' if inc['would_pass'] else '落ちる'}")
    print(f"    下向きの検出上限(母集団基準): {r['reachability_ceiling_down_population_basis']}")
    ca = {v: (x or {}).get("down_max_detectable_lift") for v, x in r["reachability_coverage_adjusted"].items()}
    cc = {v: (x or {}).get("down_certifiable") for v, x in r["reachability_coverage_adjusted"].items()}
    print(f"    下向きの検出上限(被覆調整): {ca}  certify可={cc}")
    print(f"    2013/2015 でも符号一致: {r['sign_agree_2013_2015']}")
print(f"\n出力: {DEST}")
