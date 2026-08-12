#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_win_shape.py — 勝者側（目的A: P(tr_cagr >= +15%)）の**形状と交互作用**。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル）＋ out/hist_wd_win_uni.json（単変量の兄弟器・突合せ用）
出力    : out/hist_wd_win_shape.json

────────────────────────────────────────────────────────────
この道具が答える問い（兄弟器 hist_wd_win_uni.py との違い）
────────────────────────────────────────────────────────────
単変量器は「効くか」を測った（答え: 合格ゼロ）。この道具は「**どこで効き、どこで消えるか**」を測る:

 (a) 非単調性 …… 五分位が U字／逆U字／上端反転になる変数。
     **この台帳は既に『ROIC最上位五分位が劣後』という非単調の実例を持っている**（backtest_core）。
     単調な物差し（中央値切り・上位1/4・順位相関）は、この形を**構造的に見落とす**——
     両端が高い変数は中央値切りで lift 0 になる。だから形を先に見る。
 (b) 規模との交互作用 …… 小型でだけ効く／大型でだけ効く変数
 (c) 業種との交互作用 …… 一つの sic2 が全体の lift を担いでいないか（＝業種の影）
 (d) 窓の長さ・相場との交互作用 …… 8年で効いて13年で消える変数（＝相場の影）

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定（後から読む人へ）
────────────────────────────────────────────────────────────
1) **解析集合は has_outcome ∧ window_full**（兄弟器と同じ。短窓は年率換算で両裾を機械的に膨らませる）。

2) **交互作用の切り方は「中央値切り」に固定する。** 層に分けると n が 1/3 になり、
   四分位の群は P_quality なら 27 行しか残らない＝1社で lift が 0.037 動く。
   中央値切りなら群は層の半分。**結果を見てから切り方を選ばない**ための事前固定。
   （形状(a)だけは五分位が本題なので五分位を使う。）

3) **曲率(curvature)は prereg に無い統計量＝事前登録の外**。合否には使わない。
   合否を出せるのは「両端1/5 vs 母集団」という**cut を1本足した**版で、
   これは prereg の5条件をそのまま当てられる。**cut を足した以上、検定数が増える**ので
   FPR は増えた家族の全体で測り直す（下の false_positive_rate）。

4) **交互作用の主張は2枚看板**——「層Xで prereg の5条件を通る」かつ「層Yでは通らない」。
   片方だけでは交互作用ではない。さらに **交互作用そのものの符号が 2016/2017/2018 で
   反転しないこと**を要求する（層ごとの lift が安定でも、差が安定とは限らない）。

5) **(d) は二つの交絡を分けて出す。** 窓の「長さ」と「相場（いつからいつまで）」は
   素朴に比べると分離できない。パネルの診断が既に (4b) で純粋な算術（年率換算の指数だけ）を
   分離しているので、この道具は **非重複の前半／後半** を復元して相場の側を測る:
       (1+r_full)^Y_full = (1+r_front)^(Y_full−Y_back) × (1+r_back)^Y_back
   終端日が5ファイルとも 2026-08-04 で共通なので、tr_total の比は**厳密に前半の実現**になる
   （終端の株価が約分される）。night/irr85_windows.py と同じ復元式・同じ在庫。
   ⚠ それでも残る交絡は本文に書く: 前半窓は特徴量が新しく、後半窓は古い（鮮度）／
     短い窓は個社ノイズが大きく lift を**機械的に縮める**（減衰）。

6) **兄弟器と違うことを言っていないか、実測で突き合わせる。**
   hist_wd_win_uni.py は import すると全解析が走る構造（module 直下に処理がある）ので import できない。
   よって五分位と中央値切りの式を**写している**——写した以上、
   **同じ入力で同じ数字が出ることを全セルで数える**（cross_check_vs_win_uni）。
   一致件数と不一致件数を必ず出す。v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」。

7) **0件という結論ほど道具を先に疑う**ので、陽性対照を注入する——
   U字の合成変数・小型でだけ効く合成変数を作り、**同じ経路**で検出できるか実測する。
"""
import json, os, sys, math, random
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
UNI = os.path.join(OUT, "hist_wd_win_uni.json")
DEST = os.path.join(OUT, "hist_wd_win_shape.json")

# ─── prereg の線（読むだけ・一つも作らない） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]
INTER_POPS = ["P_full", "P_quality"]        # 交互作用は3ビンテージそろう2つだけ

SEED = 20260811
N_PERM = 2000
N_POWER = 4000

F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r", "gw_r",
      "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5", "conv5", "netiss_r",
      "payout5", "rev"]
CO = ["roic_med5", "roic_latest", "roic_worst5", "opm", "sales_cagr5", "fcf_conv_5y",
      "op_all_pos", "fcf_all_pos", "equity_neg", "score", "rev_asof"]
PA = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
HV = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_z", "ps_z"]
CANDIDATES = (["f2_" + f for f in F2] + ["co_" + f for f in CO] + ["pa_" + f for f in PA]
              + ["hv_" + f for f in HV] + ["per", "size_rev"])
# 3ビンテージ(2016/2017/2018)そろう＝prereg の必須ゲートを当てられる変数だけが判定の対象
GATEABLE = ["f2_" + f for f in F2] + ["size_rev"]


# ────────────────────────────── 小道具 ──────────────────────────────
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


def q_at(sorted_vals, q):
    """nearest-rank 分位（外挿しない・実在する値だけを閾値にする）。兄弟器と同一。"""
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
    numr = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return numr / (dx * dy)


def bucket_of(x, qs):
    """兄弟器 hist_wd_win_uni.py と同一の五分位割り当て（超えた閾値の数）。"""
    b = 0
    for i, t in enumerate(qs):
        if x > t:
            b = i + 1
    return b


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
uni = json.load(open(UNI, encoding="utf-8")) if os.path.exists(UNI) else None

rows_all = panel["rows"]
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]
by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)


def pop_rows(v, pop):
    if pop == "P_full":
        return [r for r in by_v[v] if r.get("P_full")]
    if pop == "P_quality":
        return [r for r in by_v[v] if r.get("P_quality")]
    if pop == "P_moat":
        return [r for r in by_v[v] if r.get("P_moat")]
    raise ValueError(pop)


def meas(v, pop, var):
    """(値, win, 行) の可測リスト。"""
    out = []
    for r in pop_rows(v, pop):
        x = num(r.get(var))
        if x is not None:
            out.append((x, 1 if r.get("win") else 0, r))
    return out


def median_of(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def base_of(v, pop):
    R = pop_rows(v, pop)
    return len(R), sum(1 for r in R if r.get("win"))


# ══════════════════════════════════════════════════════════════════
# (a) 形状 —— 五分位・曲率・両端 cut
# ══════════════════════════════════════════════════════════════════
def shape_cell(v, pop, var):
    M = meas(v, pop, var)
    n_pop, k_pop = base_of(v, pop)
    if not M or n_pop == 0:
        return None
    p_pop = rate(k_pop, n_pop)
    vals = sorted(x for x, _, _ in M)
    distinct = len(set(vals))
    n_m = len(M)
    ent = {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": n_m, "distinct": distinct}
    if distinct < 5 or n_m < 50:
        ent["status"] = ("distinct<5＝五分位が作れない" if distinct < 5
                         else "可測 %d 行＝五分位の各群が薄すぎる" % n_m)
        return ent

    qs = [q_at(vals, x) for x in (0.2, 0.4, 0.6, 0.8)]
    buckets = [[] for _ in range(5)]
    brows = [[] for _ in range(5)]
    for x, w, r in M:
        b = bucket_of(x, qs)
        buckets[b].append(w)
        brows[b].append(r)
    # P(win) と **中央値リターン** を両方出す。
    # この台帳の既知の非単調（backtest_core: through-cycle ROIC 最上位五分位が劣後）は
    # **中央値リターン**の話で、P(win) の話ではない。二つは別の形をしうるので両方測る。
    q = [{"q": i + 1, "n": len(b), "k": sum(b), "p": r4(rate(sum(b), len(b))),
          "median_tr_cagr": r4(median_of([rr["tr_cagr"] for rr in brows[i]]))}
         for i, b in enumerate(buckets)]
    ent["quintiles"] = q
    meds = [x["median_tr_cagr"] for x in q]
    if all(m is not None for m in meds):
        ent["curvature_median_return"] = r4((meds[0] + meds[4]) / 2 - sum(meds[1:4]) / 3)
        ent["median_return_argmax_quintile"] = meds.index(max(meds)) + 1
        ent["median_return_top_reversal"] = r4(meds[3] - meds[4])
        ent["median_return_spearman"] = r4(spearman([1, 2, 3, 4, 5], meds))
    ent["quintile_thresholds"] = qs
    thin = [x["q"] for x in q if x["n"] < 10]
    ent["thin_buckets"] = thin

    ps = [x["p"] for x in q]
    if any(p is None for p in ps) or thin:
        ent["status"] = "五分位のどれかが薄い（タイで潰れた）＝形は読めない"
        ent["shape"] = None
        return ent

    # 曲率: 両端の平均 − 中3つの平均（>0 が U字・<0 が逆U字）**prereg に無い統計量**
    curv = (ps[0] + ps[4]) / 2 - sum(ps[1:4]) / 3
    ent["curvature"] = r4(curv)
    ent["top_reversal"] = r4(ps[3] - ps[4])      # >0 なら最上位が一つ下より低い
    ent["bottom_reversal"] = r4(ps[1] - ps[0])   # >0 なら最下位が一つ上より低い（＝普通の単調上昇）
    rho_q = spearman([1, 2, 3, 4, 5], ps)
    ent["quintile_spearman"] = r4(rho_q)
    strict_up = all(ps[i] < ps[i + 1] for i in range(4))
    strict_dn = all(ps[i] > ps[i + 1] for i in range(4))
    lo, hi = min(ps), max(ps)
    arg = ps.index(hi) + 1
    if strict_up:
        shape = "単調増"
    elif strict_dn:
        shape = "単調減"
    elif ps[0] > max(ps[1:4]) and ps[4] > max(ps[1:4]):
        shape = "U字（両端が高い）"
    elif ps[0] < min(ps[1:4]) and ps[4] < min(ps[1:4]):
        shape = "逆U字（中間が高い）"
    elif ps[3] > ps[4] and ps[0] == lo:
        shape = "上端反転（上げてきて最上位で落ちる）"
    elif ps[1] < ps[0] and ps[4] == hi:
        shape = "下端反転"
    else:
        shape = "不定形"
    ent["shape"] = shape
    ent["argmax_quintile"] = arg
    ent["range_p"] = r4(hi - lo)

    # 両端 cut（prereg の cut ではない・足したもの）: q1 ∪ q5
    ext = [(x, w) for x, w, _ in M if bucket_of(x, qs) in (0, 4)]
    mid = [(x, w) for x, w, _ in M if bucket_of(x, qs) in (1, 2, 3)]
    for name, g in (("両端1/5", ext), ("中間3/5", mid)):
        gn = len(g)
        gk = sum(w for _, w in g)
        gp = rate(gk, gn)
        ent[name] = {"n_group": gn, "numerator": gk, "p_group": r4(gp),
                     "lift_vs_pop": r4(None if gp is None else gp - p_pop)}
    return ent


shape_cells = {}
for var in CANDIDATES:
    for pop in POPS:
        for v in ALL_VINTAGES:
            c = shape_cell(v, pop, var)
            if c:
                shape_cells["%s|%s|%d" % (var, pop, v)] = c


# ══════════════════════════════════════════════════════════════════
# (b)(c) 層別の中央値切り（設計2で固定）
# ══════════════════════════════════════════════════════════════════
def median_cut(rows, var):
    """行の集合の中で var の中央値超を群にする。母集団＝渡された rows 全体（欠測も分母）。"""
    n_pop = len(rows)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in rows if r.get("win"))
    p_pop = rate(k_pop, n_pop)
    M = [(num(r.get(var)), 1 if r.get("win") else 0) for r in rows]
    M = [(x, w) for x, w in M if x is not None]
    if len(M) < 20:
        return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop), "n_measurable": len(M),
                "status": "可測20行未満＝判定不能"}
    vals = sorted(x for x, _ in M)
    q50 = q_at(vals, 0.50)
    g = [w for x, w in M if x > q50]
    gn, gk = len(g), sum(g)
    if gn == 0:
        return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop), "n_measurable": len(M),
                "status": "中央値=最大値でタイ＝この切り方が成立しない（判定不能）"}
    gp = rate(gk, gn)
    # ── 欠測の交絡（兄弟器の設計2と同じ問い）──
    # lift の分母は prereg literal どおり「母集団全体」。だが欠測社は母集団には居るのに群には入りえない。
    # **その変数を報告している社と報告していない社で勝率が違えば、lift は値ではなく報告の有無を見ている。**
    # 実測: f2_sga_r の可測率は小型 40-48% / 大型 62-69% で、欠測側の勝率が 10pt 以上低い。
    n_meas = len(M)
    k_meas = sum(w for _, w in M)
    p_meas = rate(k_meas, n_meas)
    n_miss = n_pop - n_meas
    p_miss = rate(k_pop - k_meas, n_miss) if n_miss else None
    return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop),
            "n_measurable": n_meas, "coverage": r4(rate(n_meas, n_pop)),
            "p_measurable": r4(p_meas), "n_missing": n_miss, "p_missing": r4(p_miss),
            "q50": q50,
            "n_group": gn, "numerator": gk, "p_group": r4(gp),
            "lift": r4(gp - p_pop),
            "lift_vs_measurable": r4(gp - p_meas),
            "events_total": k_pop,
            "min_num_ok": gk >= MIN_NUM,
            "reachable": k_pop >= MIN_NUM}


# ─── (b) 規模の三分位 ───
def size_strata(v, pop):
    R = [r for r in pop_rows(v, pop) if num(r.get("size_rev")) is not None]
    n_missing = len(pop_rows(v, pop)) - len(R)
    if len(R) < 60:
        return None, n_missing
    vals = sorted(num(r["size_rev"]) for r in R)
    t1, t2 = q_at(vals, 1 / 3), q_at(vals, 2 / 3)
    S = {"小": [], "中": [], "大": []}
    for r in R:
        x = num(r["size_rev"])
        S["小" if x <= t1 else ("中" if x <= t2 else "大")].append(r)
    return {"strata": S, "cuts": {"t1": t1, "t2": t2}}, n_missing


size_inter = {}
for var in GATEABLE:
    if var == "size_rev":
        continue                     # 規模そのものを規模で層別しない（定義上の循環）
    for pop in INTER_POPS:
        per_v = {}
        for v in ALL_VINTAGES:
            st, nm = size_strata(v, pop)
            if not st:
                per_v[str(v)] = None
                continue
            cell = {"missing_size_rows": nm, "size_cuts": st["cuts"], "strata": {}}
            for sname, rows in st["strata"].items():
                mc = median_cut(rows, var)
                if mc:
                    mc["stratum_n"] = len(rows)
                cell["strata"][sname] = mc
            a = cell["strata"].get("小") or {}
            b = cell["strata"].get("大") or {}
            cell["interaction_small_minus_large"] = (
                r4(a["lift"] - b["lift"]) if a.get("lift") is not None and b.get("lift") is not None else None)
            # 欠測を外した版（分母＝可測部分集合）。二つが食い違えば、見ているのは値ではなく報告の有無。
            cell["interaction_small_minus_large_measurable"] = (
                r4(a["lift_vs_measurable"] - b["lift_vs_measurable"])
                if a.get("lift_vs_measurable") is not None and b.get("lift_vs_measurable") is not None else None)
            cell["coverage_small_vs_large"] = [a.get("coverage"), b.get("coverage")]
            cell["p_missing_small_vs_large"] = [a.get("p_missing"), b.get("p_missing")]
            per_v[str(v)] = cell
        # 3ビンテージでの符号安定（層ごとの lift と、交互作用そのもの）
        stab = {}
        for sname in ("小", "中", "大"):
            ls = [per_v[str(v)]["strata"][sname]["lift"] for v in SIGN_VINTAGES
                  if per_v.get(str(v)) and per_v[str(v)]["strata"].get(sname)
                  and per_v[str(v)]["strata"][sname].get("lift") is not None]
            stab[sname] = {"lifts_161718": ls,
                           "sign_stable": (len({1 if x > 0 else (-1 if x < 0 else 0) for x in ls}) == 1
                                           and 0 not in {1 if x > 0 else (-1 if x < 0 else 0) for x in ls})
                           if len(ls) == 3 else None,
                           "min_abs_lift": r4(min(abs(x) for x in ls)) if len(ls) == 3 else None,
                           "min_numerator": min(
                               [per_v[str(v)]["strata"][sname]["numerator"] for v in SIGN_VINTAGES
                                if per_v.get(str(v)) and per_v[str(v)]["strata"].get(sname)
                                and per_v[str(v)]["strata"][sname].get("numerator") is not None] or [None])}
        ds = [per_v[str(v)]["interaction_small_minus_large"] for v in SIGN_VINTAGES
              if per_v.get(str(v)) and per_v[str(v)]["interaction_small_minus_large"] is not None]
        dm = [per_v[str(v)]["interaction_small_minus_large_measurable"] for v in SIGN_VINTAGES
              if per_v.get(str(v)) and per_v[str(v)]["interaction_small_minus_large_measurable"] is not None]
        stab["_interaction"] = {
            "diffs_161718": ds,
            "sign_stable": (len({1 if x > 0 else (-1 if x < 0 else 0) for x in ds}) == 1
                            and 0 not in {1 if x > 0 else (-1 if x < 0 else 0) for x in ds})
            if len(ds) == 3 else None,
            "min_abs_diff": r4(min(abs(x) for x in ds)) if len(ds) == 3 else None,
            "median_diff": r4(sorted(ds)[len(ds) // 2]) if ds else None,
            "diffs_measurable_161718": dm,
            "min_abs_diff_measurable": (r4(min(abs(x) for x in dm))
                                        if len(dm) == 3 and len({1 if x > 0 else -1 for x in dm}) == 1 else None),
            "shrink_when_missingness_removed": (
                r4(min(abs(x) for x in ds) - min(abs(x) for x in dm))
                if len(ds) == 3 and len(dm) == 3 else None)}
        size_inter["%s|%s" % (var, pop)] = {"by_vintage": per_v, "stability": stab}


# ─── (c) 業種(sic2) ───
MIN_SECTOR_N = 40


def mh_risk_diff(rows, var):
    """層別リスク差（CMH重み）。層 = sic2。兄弟器と同じ式（写した——下で突合せる）。"""
    M = [(num(r.get(var)), 1 if r.get("win") else 0, r.get("sic2")) for r in rows]
    M = [(x, w, s) for x, w, s in M if x is not None and s]
    if len(M) < 20:
        return None
    vals = sorted(x for x, _, _ in M)
    q50 = q_at(vals, 0.50)
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for x, w, s in M:
        d = strata[s]
        if x > q50:
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


sector_inter = {}
for var in GATEABLE:
    for pop in INTER_POPS:
        per_v = {}
        for v in SIGN_VINTAGES:
            R = pop_rows(v, pop)
            overall = median_cut(R, var)
            if not overall or overall.get("lift") is None:
                per_v[str(v)] = None
                continue
            bysic = defaultdict(list)
            for r in R:
                if r.get("sic2"):
                    bysic[r["sic2"]].append(r)
            sect = {}
            for s, rows in sorted(bysic.items()):
                if len(rows) < MIN_SECTOR_N:
                    continue
                mc = median_cut(rows, var)
                if mc and mc.get("lift") is not None:
                    sect[s] = {"n": len(rows), "n_group": mc["n_group"], "k": mc["numerator"],
                               "p_group": mc["p_group"], "p_base": mc["p_pop"],
                               "lift": mc["lift"], "events_total": mc["events_total"],
                               "reachable": mc["reachable"]}
            # 一つの業種が担いでいないか: その業種を落としたときの全体 lift
            loo = {}
            for s in sect:
                rest = [r for r in R if r.get("sic2") != s]
                mc = median_cut(rest, var)
                loo[s] = mc.get("lift") if mc else None
            mh = mh_risk_diff(R, var)
            ls = [d["lift"] for d in sect.values()]
            per_v[str(v)] = {
                "overall": {"n_pop": overall["n_pop"], "n_group": overall["n_group"],
                            "k": overall["numerator"], "p_group": overall["p_group"],
                            "p_base": overall["p_pop"], "lift": overall["lift"]},
                "mh_sector_adjusted": mh,
                "mh_minus_overall": (r4(mh["mh_risk_diff"] - overall["lift"]) if mh else None),
                "sectors": sect,
                "n_sectors_measured": len(sect),
                "sector_sign_same_as_overall": (
                    sum(1 for x in ls if (x > 0) == (overall["lift"] > 0)) if ls else None),
                "max_abs_sector_lift": (r4(max(abs(x) for x in ls)) if ls else None),
                "argmax_sector": (max(sect.items(), key=lambda kv: abs(kv[1]["lift"]))[0] if sect else None),
                "leave_one_sector_out_lift": {k: r4(x) for k, x in loo.items()},
                "loo_min_abs": (r4(min(abs(x) for x in loo.values() if x is not None))
                                if any(x is not None for x in loo.values()) else None),
            }
        ls3 = [per_v[str(v)]["overall"]["lift"] for v in SIGN_VINTAGES if per_v.get(str(v))]
        sector_inter["%s|%s" % (var, pop)] = {
            "by_vintage": per_v,
            "overall_lifts_161718": ls3,
            "overall_sign_stable": (len({1 if x > 0 else (-1 if x < 0 else 0) for x in ls3}) == 1
                                    and 0 not in {1 if x > 0 else (-1 if x < 0 else 0) for x in ls3})
            if len(ls3) == 3 else None,
        }


# ══════════════════════════════════════════════════════════════════
# (d) 窓の長さ・相場との交互作用
# ══════════════════════════════════════════════════════════════════
# 復元式（night/irr85_windows.py と同じ）:
#   (1+r_full)^Y_full = (1+r_front)^(Y_full−Y_back) × (1+r_back)^Y_back
# 5つの returns ファイルは終端日が 2026-08-04 で共通なので、tr_total の比が厳密に前半の実現になる。
idx_by_v = {v: {r["ticker"]: r for r in by_v[v]} for v in ALL_VINTAGES}
BACK_V = 2018

#
# ⚠ **どちらの欄から復元するかで精度が桁で違う**（この道具の検算で見つけた）:
#   returns ファイルは tr_total を**小数3桁**・tr_cagr を**小数4桁**に丸めて保存している。
#   tr_total の比から復元すると、ほぼ全損の行（CRIS tr_total=0.001）で丸め誤差が **±50%** になる。
#   tr_cagr から復元すれば誤差は Y·Δr/(1+r) ＝ 13.09×0.00005/0.57 ≒ **0.12%** に収まる。
#   → **tr_cagr を正本にする**（night/irr85_windows.py の pre() と同じ式・同じ作法）。
#   tr_total 版も並行して作り、**二つの差＝丸めがこの分析をどれだけ動かしうるか**を実測して残す。
alt_outcomes = {}      # (anchor) -> {ticker: {"full":cagr,"front":cagr,"back":cagr,...}}
window_meta = {}
rounding_probe = {}
for anchor in (2013, 2015, 2016, 2017):
    A, B = idx_by_v[anchor], idx_by_v[BACK_V]
    d = {}
    diffs, flips = [], 0
    for t, ra in A.items():
        rb = B.get(t)
        if not rb:
            continue
        ca, cb = ra.get("tr_cagr"), rb.get("tr_cagr")
        if ca is None or cb is None:
            continue
        ya, yb = ra["years"], rb["years"]
        yf = round(ya - yb, 2)
        if yf <= 0:
            continue
        ratio = (1 + ca) ** ya / (1 + cb) ** yb
        if ratio <= 0:
            continue
        front = ratio ** (1.0 / yf) - 1
        d[t] = {"full": ca, "back": cb, "front": front,
                "years_full": ya, "years_back": yb, "years_front": yf}
        # 丸めの影響の実測: tr_total 版と突き合わせる
        ta, tb = ra.get("tr_total"), rb.get("tr_total")
        if ta and tb and ta > 0 and tb > 0:
            front_t = (ta / tb) ** (1.0 / yf) - 1
            diffs.append(abs(front - front_t))
            if (front >= 0.15) != (front_t >= 0.15):
                flips += 1
    if d:
        any_row = next(iter(d.values()))
        alt_outcomes[anchor] = d
        window_meta[anchor] = {"n": len(d), "years_full": any_row["years_full"],
                               "years_front": any_row["years_front"],
                               "years_back": any_row["years_back"]}
        diffs.sort()
        rounding_probe[str(anchor)] = {
            "n_compared": len(diffs),
            "median_abs_diff_front_cagr_vs_total": r4(diffs[len(diffs) // 2]) if diffs else None,
            "p99_abs_diff": r4(diffs[int(0.99 * len(diffs))]) if diffs else None,
            "max_abs_diff": r4(diffs[-1]) if diffs else None,
            "n_win_flag_flips": flips,
            "share_flips": r4(rate(flips, len(diffs))) if diffs else None}
rounding_probe["_note"] = (
    "前半の年率を tr_cagr(4桁) から復元した値と tr_total(3桁) の比から復元した値の差。"
    "**n_win_flag_flips が『丸めだけで勝者判定が変わる行数』**＝この分析の下限のノイズ。"
    "tr_cagr 版を正本にしたのは、丸め誤差が tr_total 版の桁違いに小さいから。")


# 復元の検算: (1+full)^Y_full ≟ (1+front)^Y_front × (1+back)^Y_back を全行で当てる。
# tr_cagr から作った以上ここは恒等式で、通って当たり前——**通らなければ実装が壊れている**という側の検査。
# 丸めが結論をどれだけ動かしうるかは、これではなく rounding_probe（tr_total版との突合せ）が測る。
window_identity = {}
for anchor, d in alt_outcomes.items():
    worst, n_bad = 0.0, 0
    for t, e in d.items():
        lhs = (1 + e["full"]) ** e["years_full"]
        rhs = (1 + e["front"]) ** e["years_front"] * (1 + e["back"]) ** e["years_back"]
        rel = abs(lhs - rhs) / lhs
        worst = max(worst, rel)
        if rel > 1e-9:
            n_bad += 1
    window_identity[str(anchor)] = {"n": len(d), "max_relative_error": worst, "n_over_1e-9": n_bad,
                                    "ok": worst < 1e-9}
window_identity["_note"] = ("恒等式による実装の検査（tr_cagr から作ったので厳密に0のはず）。"
                            "**丸めの影響は別枠 window_rounding_probe で測る**——"
                            "そちらが『丸めだけで勝者判定が変わる行数』を出す。")


def win_flag(cagr):
    return cagr is not None and cagr >= 0.15


def window_measure(anchor, pop, var, seg):
    """anchor ビンテージの特徴量 × seg('full'/'front'/'back') の outcome で中央値切り。"""
    R = [r for r in pop_rows(anchor, pop) if r["ticker"] in alt_outcomes.get(anchor, {})]
    if len(R) < 40:
        return None
    out = alt_outcomes[anchor]
    n_pop = len(R)
    k_pop = sum(1 for r in R if win_flag(out[r["ticker"]][seg]))
    p_pop = rate(k_pop, n_pop)
    M = [(num(r.get(var)), 1 if win_flag(out[r["ticker"]][seg]) else 0) for r in R]
    M = [(x, w) for x, w in M if x is not None]
    if len(M) < 20:
        return None
    vals = sorted(x for x, _ in M)
    q50 = q_at(vals, 0.50)
    g = [w for x, w in M if x > q50]
    if not g:
        return None
    gp = rate(sum(g), len(g))
    return {"n_pop": n_pop, "events": k_pop, "p_base": r4(p_pop),
            "n_group": len(g), "k": sum(g), "p_group": r4(gp),
            "lift": r4(gp - p_pop),
            "risk_ratio": r4(gp / p_pop) if p_pop else None,
            "rank_corr": r4(spearman([x for x, _ in M], [float(w) for _, w in M]))}


window_inter = {}
for var in GATEABLE:
    for pop in INTER_POPS:
        ent = {}
        for anchor in (2016, 2017, 2013, 2015):
            if anchor not in alt_outcomes:
                continue
            if anchor in (2013, 2015) and var.startswith("f2_"):
                continue     # f2_ は 2013/2015 に存在しない
            segs = {}
            for seg in ("full", "front", "back"):
                m = window_measure(anchor, pop, var, seg)
                if m:
                    segs[seg] = m
            if len(segs) == 3:
                ent[str(anchor)] = {
                    "window": window_meta[anchor], "segments": segs,
                    "front_minus_back_lift": r4(segs["front"]["lift"] - segs["back"]["lift"]),
                }
        if ent:
            ds = [ent[str(a)]["front_minus_back_lift"] for a in (2016, 2017) if str(a) in ent]
            window_inter["%s|%s" % (var, pop)] = {
                "by_anchor": ent,
                "front_minus_back_1617": ds,
                "sign_stable_1617": (len({1 if x > 0 else (-1 if x < 0 else 0) for x in ds}) == 1
                                     and 0 not in {1 if x > 0 else (-1 if x < 0 else 0) for x in ds})
                if len(ds) == 2 else None,
            }

# co_ の概念（2013/2015 のみ）で「前半5.0年 vs 後半8.09年」——特徴量の鮮度差が最小の era 検定にはならないが、
# **AI相場の前だけを見た唯一の窓**なので必ず出す
window_inter_co = {}
for var in ["co_" + f for f in CO] + ["size_rev"]:
    for pop in INTER_POPS:
        ent = {}
        for anchor in (2013, 2015):
            if anchor not in alt_outcomes:
                continue
            segs = {}
            for seg in ("full", "front", "back"):
                m = window_measure(anchor, pop, var, seg)
                if m:
                    segs[seg] = m
            if len(segs) == 3:
                ent[str(anchor)] = {"window": window_meta[anchor], "segments": segs,
                                    "front_minus_back_lift": r4(segs["front"]["lift"] - segs["back"]["lift"])}
        if ent:
            ds = [ent[a]["front_minus_back_lift"] for a in ent]
            window_inter_co["%s|%s" % (var, pop)] = {
                "by_anchor": ent, "front_minus_back": ds,
                "sign_stable_2013_2015": (len({1 if x > 0 else -1 for x in ds}) == 1) if len(ds) == 2 else None}

# (d1) 純粋な長さ（年率換算の指数だけを動かす）——同じ実現・同じ母集団で勝者の顔ぶれがどう変わるか
pure_length = {}
for anchor in ALL_VINTAGES:
    R = [r for r in by_v[anchor] if r.get("tr_total") and r["tr_total"] > 0]
    if not R:
        continue
    yrs = R[0]["years"]
    ent = {"anchor_years": yrs, "n": len(R), "reannualized": {}}
    for T in (8.09, 10.09, 13.09):
        cg = [r["tr_total"] ** (1.0 / T) - 1 for r in R]
        k = sum(1 for x in cg if x >= 0.15)
        ent["reannualized"][str(T)] = {"win_k": k, "win_p": r4(rate(k, len(cg)))}
    pure_length[str(anchor)] = ent


# ══════════════════════════════════════════════════════════════════
# 兄弟器との突合せ（写した式が同じ数字を出すか・実測）
# ══════════════════════════════════════════════════════════════════
cross = {"checked": 0, "quintile_match": 0, "quintile_mismatch": [],
         "median_lift_match": 0, "median_lift_mismatch": []}
if uni:
    for key, mine in shape_cells.items():
        theirs = uni["cells"].get(key)
        if not theirs or not mine.get("quintiles") or not theirs.get("quintiles"):
            continue
        cross["checked"] += 1
        a = [(x["n"], x["k"]) for x in mine["quintiles"]]
        b = [(x["n"], x["k"]) for x in theirs["quintiles"]]
        if a == b:
            cross["quintile_match"] += 1
        elif len(cross["quintile_mismatch"]) < 10:
            cross["quintile_mismatch"].append({"cell": key, "mine": a, "theirs": b})
    # 中央値切りの lift（交互作用の全体版）も突き合わせる
    for var in GATEABLE:
        for pop in INTER_POPS:
            for v in SIGN_VINTAGES:
                t = (uni["cells"].get("%s|%s|%d" % (var, pop, v)) or {}).get("cuts", {}).get("中央値超")
                m = median_cut(pop_rows(v, pop), var)
                if not t or not m or m.get("lift") is None:
                    continue
                if abs(t["lift_vs_pop"] - m["lift"]) < 1e-9 and t["n_group"] == m["n_group"]:
                    cross["median_lift_match"] += 1
                elif len(cross["median_lift_mismatch"]) < 10:
                    cross["median_lift_mismatch"].append(
                        {"cell": "%s|%s|%d" % (var, pop, v), "mine": m["lift"], "theirs": t["lift_vs_pop"]})
cross["verdict"] = ("兄弟器と完全一致（写した式が同じ数字を出す）"
                    if not cross["quintile_mismatch"] and not cross["median_lift_mismatch"]
                    else "⚠ 不一致あり——どちらかが壊れている。読む前に直すこと")


# ══════════════════════════════════════════════════════════════════
# 結果を見る前に出す(1): 到達可能性（層に割ると事象が5に届くか）
# ══════════════════════════════════════════════════════════════════
reach = {}
for v in SIGN_VINTAGES:
    for pop in INTER_POPS:
        R = pop_rows(v, pop)
        ev = sum(1 for r in R if r.get("win"))
        cell = {"n": len(R), "events": ev, "base": r4(rate(ev, len(R)))}
        st, nm = size_strata(v, pop)
        if st:
            cell["size_terciles"] = {}
            for s, rows in st["strata"].items():
                e = sum(1 for r in rows if r.get("win"))
                g = max(1, len(rows) // 2)
                b = rate(e, len(rows))
                k_lift = math.ceil((b + LIFT) * g) if b is not None else None
                cell["size_terciles"][s] = {
                    "n": len(rows), "events": e, "base": r4(b),
                    "min_num_reachable": e >= MIN_NUM,
                    "k_needed_by_lift": k_lift,
                    "binding": ("MIN_NUM" if (k_lift or 0) < MIN_NUM else "LIFT"),
                    "possible": (max(k_lift or 0, MIN_NUM) <= e),
                    "share_of_events_required": r4(max(k_lift or 0, MIN_NUM) / e) if e else None}
        bysic = defaultdict(list)
        for r in R:
            if r.get("sic2"):
                bysic[r["sic2"]].append(r)
        sec = {}
        for s, rows in bysic.items():
            if len(rows) < MIN_SECTOR_N:
                continue
            e = sum(1 for r in rows if r.get("win"))
            sec[s] = {"n": len(rows), "events": e, "min_num_reachable": e >= MIN_NUM}
        cell["sectors_ge%d" % MIN_SECTOR_N] = sec
        cell["n_sectors_usable"] = sum(1 for d in sec.values() if d["min_num_reachable"])
        cell["n_rows_in_usable_sectors"] = sum(d["n"] for d in sec.values() if d["min_num_reachable"])
        cell["share_rows_in_usable_sectors"] = r4(rate(cell["n_rows_in_usable_sectors"], len(R)))
        reach["%d/%s" % (v, pop)] = cell

# 窓側の到達可能性（各セグメントの基準率＝ハードルの意味が窓ごとに変わる）
window_reach = {}
for anchor, out in alt_outcomes.items():
    for pop in INTER_POPS:
        R = [r for r in pop_rows(anchor, pop) if r["ticker"] in out]
        if len(R) < 40:
            continue
        e = {}
        for seg in ("full", "front", "back"):
            k = sum(1 for r in R if win_flag(out[r["ticker"]][seg]))
            e[seg] = {"events": k, "base": r4(rate(k, len(R))),
                      "years": window_meta[anchor]["years_" + ("full" if seg == "full" else seg)]}
        window_reach["%d/%s" % (anchor, pop)] = {"n": len(R), "by_segment": e}


# ══════════════════════════════════════════════════════════════════
# 結果を見る前に出す(2): 検出力（層に割ると何が起きるか）
# ══════════════════════════════════════════════════════════════════
rnd = random.Random(SEED)


def binom(n, p):
    return sum(1 for _ in range(n) if rnd.random() < p)


def power_sim(n, base, true_lift, frac=0.5, n_sims=N_POWER, three=True):
    """群サイズ frac*n（中央値切り=0.5・四分位=0.25）で |観測lift|>=0.15 ∧ k>=5 を掴む確率。"""
    g = max(1, int(n * frac))
    rest = n - g
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = min(0.999, max(0.001, (base * n - p_g * g) / rest)) if rest else 0.001
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
    return {"single_vintage": r4(single / n_sims),
            "three_independent": r4(triple / n_sims) if three else None}


power = {}
for label, (n_ref, base_ref, frac) in {
    "P_full 全体・中央値切り": (946, reach["2016/P_full"]["base"], 0.5),
    "P_full 規模三分位・中央値切り": (315, reach["2016/P_full"]["base"], 0.5),
    "P_quality 全体・中央値切り": (329, reach["2016/P_quality"]["base"], 0.5),
    "P_quality 規模三分位・中央値切り": (109, reach["2016/P_quality"]["base"], 0.5),
    "業種1つ(n=99・73番)・中央値切り": (99, reach["2016/P_full"]["base"], 0.5),
}.items():
    power[label] = {"n": n_ref, "base": base_ref,
                    "by_true_lift": {str(L): power_sim(n_ref, base_ref, L, frac) for L in (0.15, 0.20, 0.30)}}
power["_how_to_read"] = (
    "three_independent が下限（3ビンテージが独立という仮定）・single_vintage が上限（完全に同じ実現）。"
    "実測の outcome の Spearman は 0.845〜0.961 なので真の検出力はこの間。"
    "**層に割ると n が 1/3 になり、同じ真の効果でも掴める確率が落ちる**——"
    "交互作用の探索は、母集団を割った時点で構造的に検出力を失う。"
    "『層Xでだけ合格した』が出たときは、まずこの表を見ること。")


# ══════════════════════════════════════════════════════════════════
# 結果を見る前に出す(3): 偽陽性率（実データの相関を保った置換）
# ══════════════════════════════════════════════════════════════════
# 索引空間 = 2016/2017/2018 に現れる全ティッカー
tick_idx = {}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        tick_idx.setdefault(r["ticker"], len(tick_idx))
N_T = len(tick_idx)


def bits_to_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


A_bits = {v: [0] * N_T for v in SIGN_VINTAGES}
W_bits = {v: [0] * N_T for v in SIGN_VINTAGES}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        i = tick_idx[r["ticker"]]
        A_bits[v][i] = 1
        if r.get("win"):
            W_bits[v][i] = 1


def mask_of(rows):
    m = [0] * N_T
    for r in rows:
        i = tick_idx.get(r["ticker"])
        if i is not None:
            m[i] = 1
    return bits_to_int(m)


# 検定の家族: (a)両端cut + (b)規模三分位の中央値切り + (c)業種ごとの中央値切り
family = []          # [(label, {v: (pop_mask, group_mask)})]
fam_kind = []
for var in GATEABLE:
    for pop in INTER_POPS:
        # (a) 両端1/5
        per_v, ok = {}, True
        for v in SIGN_VINTAGES:
            R = pop_rows(v, pop)
            M = meas(v, pop, var)
            if len(M) < 50 or len(set(x for x, _, _ in M)) < 5:
                ok = False
                break
            vals = sorted(x for x, _, _ in M)
            qs = [q_at(vals, x) for x in (0.2, 0.4, 0.6, 0.8)]
            grp = [r for x, w, r in M if bucket_of(x, qs) in (0, 4)]
            per_v[v] = (mask_of(R), mask_of(grp))
        if ok:
            family.append(("両端1/5|%s|%s" % (var, pop), per_v))
            fam_kind.append("a_shape_extremes")
        # (b) 規模三分位 × 中央値切り
        for sname in ("小", "中", "大"):
            per_v, ok = {}, True
            for v in SIGN_VINTAGES:
                st, _ = size_strata(v, pop)
                if not st:
                    ok = False
                    break
                rows = st["strata"][sname]
                M = [(num(r.get(var)), r) for r in rows]
                M = [(x, r) for x, r in M if x is not None]
                if len(M) < 20:
                    ok = False
                    break
                q50 = q_at(sorted(x for x, _ in M), 0.50)
                grp = [r for x, r in M if x > q50]
                if not grp:
                    ok = False
                    break
                per_v[v] = (mask_of(rows), mask_of(grp))
            if ok:
                family.append(("規模%s|%s|%s" % (sname, var, pop), per_v))
                fam_kind.append("b_size_stratum")
        # (c) 業種ごと × 中央値切り（n>=40 の業種のみ・3ビンテージそろうもの）
        sec_common = None
        for v in SIGN_VINTAGES:
            R = pop_rows(v, pop)
            c = {s for s, rows in Counter(r.get("sic2") for r in R if r.get("sic2")).items() if rows >= MIN_SECTOR_N}
            sec_common = c if sec_common is None else (sec_common & c)
        for s in sorted(sec_common or []):
            per_v, ok = {}, True
            for v in SIGN_VINTAGES:
                rows = [r for r in pop_rows(v, pop) if r.get("sic2") == s]
                M = [(num(r.get(var)), r) for r in rows]
                M = [(x, r) for x, r in M if x is not None]
                if len(M) < 20:
                    ok = False
                    break
                q50 = q_at(sorted(x for x, _ in M), 0.50)
                grp = [r for x, r in M if x > q50]
                if not grp:
                    ok = False
                    break
                per_v[v] = (mask_of(rows), mask_of(grp))
            if ok:
                family.append(("業種%s|%s|%s" % (s, var, pop), per_v))
                fam_kind.append("c_sector_stratum")


# ── (b) 交互作用そのものの帰無分布 ──
# 家族の per-stratum lift には帰無を張ったが、**小−大の差**は別の統計量なので別に張る。
# これを張らずに『差 0.152』を報告すると、雑音の大きさを示さずに数字だけ出すことになる。
inter_masks = []
for var in GATEABLE:
    if var == "size_rev":
        continue
    for pop in INTER_POPS:
        per_v, ok = {}, True
        for v in SIGN_VINTAGES:
            st, _ = size_strata(v, pop)
            if not st:
                ok = False
                break
            got = {}
            for sname in ("小", "大"):
                rows = st["strata"][sname]
                M = [(num(r.get(var)), r) for r in rows]
                M = [(x, r) for x, r in M if x is not None]
                if len(M) < 20:
                    ok = False
                    break
                q50 = q_at(sorted(x for x, _ in M), 0.50)
                grp = [r for x, r in M if x > q50]
                if not grp:
                    ok = False
                    break
                got[sname] = (mask_of(rows), mask_of([r for _, r in M]), mask_of(grp))
            if not ok:
                break
            per_v[v] = got
        if ok:
            inter_masks.append(("%s|%s" % (var, pop), per_v))


def run_inter(Aint, Wint, base="pop"):
    """小−大 の差。符号が3ビンテージで揃ったものだけ min|差| を返す（揃わなければ0）。

    base="meas" は分母を可測部分集合にした版＝**欠測の交絡を外した差**。
    二つが大きく食い違うなら、その交互作用は『値』ではなく『その変数を報告している社が層で違う』ことを見ている。
    """
    out = []
    for label, per_v in inter_masks:
        ds = []
        for v in SIGN_VINTAGES:
            vals = {}
            for sname in ("小", "大"):
                pm, mm, gm = per_v[v][sname]
                bm = pm if base == "pop" else mm
                nbase = (bm & Aint[v]).bit_count()
                ng = (gm & Aint[v]).bit_count()
                if nbase == 0 or ng == 0:
                    vals = None
                    break
                vals[sname] = ((gm & Wint[v]).bit_count() / ng) - ((bm & Wint[v]).bit_count() / nbase)
            if vals is None:
                ds = []
                break
            ds.append(vals["小"] - vals["大"])
        if len(ds) == 3 and len({1 if x > 0 else -1 for x in ds}) == 1:
            out.append((label, min(abs(x) for x in ds)))
        else:
            out.append((label, 0.0))
    return out


# ── (d) 前半−後半 の差の帰無分布 ──
# outcome は ticker 単位の量（front/back）なので、ticker の置換で front と back の相関ごと保てる。
win_bits_seg = {}     # (anchor, seg) -> bits
pres_bits_seg = {}    # anchor -> bits（前半/後半を復元できた社）
for anchor in (2016, 2017):
    if anchor not in alt_outcomes:
        continue
    out = alt_outcomes[anchor]
    pres = [0] * N_T
    for seg in ("front", "back"):
        b = [0] * N_T
        for t, d in out.items():
            i = tick_idx.get(t)
            if i is None:
                continue
            pres[i] = 1
            if win_flag(d[seg]):
                b[i] = 1
        win_bits_seg[(anchor, seg)] = b
    pres_bits_seg[anchor] = pres

win_masks = []
for var in GATEABLE:
    for pop in INTER_POPS:
        per_a, ok = {}, True
        for anchor in (2016, 2017):
            if anchor not in alt_outcomes:
                ok = False
                break
            R = [r for r in pop_rows(anchor, pop) if r["ticker"] in alt_outcomes[anchor]]
            M = [(num(r.get(var)), r) for r in R]
            M = [(x, r) for x, r in M if x is not None]
            if len(M) < 20:
                ok = False
                break
            q50 = q_at(sorted(x for x, _ in M), 0.50)
            grp = [r for x, r in M if x > q50]
            if not grp:
                ok = False
                break
            per_a[anchor] = (mask_of(R), mask_of(grp))
        if ok:
            win_masks.append(("%s|%s" % (var, pop), per_a))


def run_window(Wseg):
    """(前半lift − 後半lift) が anchor2016/2017 で符号一致したものの min|差|。"""
    out = []
    for label, per_a in win_masks:
        ds = []
        for anchor in (2016, 2017):
            pm, gm = per_a[anchor]
            npop, ng = pm.bit_count(), gm.bit_count()
            if npop == 0 or ng == 0:
                ds = []
                break
            lf = {}
            for seg in ("front", "back"):
                W = Wseg[(anchor, seg)]
                lf[seg] = ((gm & W).bit_count() / ng) - ((pm & W).bit_count() / npop)
            ds.append(lf["front"] - lf["back"])
        if len(ds) == 2 and len({1 if x > 0 else -1 for x in ds}) == 1:
            out.append((label, min(abs(x) for x in ds)))
        else:
            out.append((label, 0.0))
    return out


Wseg0 = {k: bits_to_int(b) for k, b in win_bits_seg.items()}
obs_window = run_window(Wseg0)


def perm_int(bits, sigma):
    return int("".join("1" if bits[sigma[j]] else "0" for j in range(N_T)), 2)


def run_family(Aint, Wint, thresh=LIFT):
    """家族の各検定に prereg のゲート1-3（lift・分子・符号不変）を当て、通った数と統計量を返す。"""
    hits, stats = [], []
    for label, per_v in family:
        ok, signs, mins = True, set(), []
        for v in SIGN_VINTAGES:
            pm, gm = per_v[v]
            a = Aint[v]
            npop = (pm & a).bit_count()
            kpop = (pm & Wint[v]).bit_count()
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
                hits.append(label)
        else:
            stats.append(0.0)
    return hits, stats


A0 = {v: bits_to_int(A_bits[v]) for v in SIGN_VINTAGES}
W0 = {v: bits_to_int(W_bits[v]) for v in SIGN_VINTAGES}
obs_hits, obs_stats = run_family(A0, W0)
obs_inter = run_inter(A0, W0)
obs_inter_meas = run_inter(A0, W0, base="meas")

# 曲率の帰無分布（家族全体の最大|curvature|）——曲率は prereg に無いので線が無い。
# 「どこからが雑音でないか」を読み手が判断できるよう、帰無分布そのものを出す。
curv_masks = []       # [(label, {v: (pop_mask, [q1..q5 masks])})]
for var in GATEABLE:
    for pop in INTER_POPS:
        per_v, ok = {}, True
        for v in SIGN_VINTAGES:
            M = meas(v, pop, var)
            if len(M) < 50 or len(set(x for x, _, _ in M)) < 5:
                ok = False
                break
            vals = sorted(x for x, _, _ in M)
            qs = [q_at(vals, x) for x in (0.2, 0.4, 0.6, 0.8)]
            bm = [[] for _ in range(5)]
            for x, w, r in M:
                bm[bucket_of(x, qs)].append(r)
            if any(len(b) < 10 for b in bm):
                ok = False
                break
            per_v[v] = [mask_of(b) for b in bm]
        if ok:
            curv_masks.append(("%s|%s" % (var, pop), per_v))


def run_curv(Aint, Wint):
    out = []
    for label, per_v in curv_masks:
        cs = []
        for v in SIGN_VINTAGES:
            ps = []
            for m in per_v[v]:
                n = (m & Aint[v]).bit_count()
                k = (m & Wint[v]).bit_count()
                ps.append(k / n if n else None)
            if any(p is None for p in ps):
                cs = []
                break
            cs.append((ps[0] + ps[4]) / 2 - sum(ps[1:4]) / 3)
        if len(cs) == 3 and len({1 if c > 0 else -1 for c in cs}) == 1:
            out.append((label, min(abs(c) for c in cs)))
        else:
            out.append((label, 0.0))
    return out


obs_curv = run_curv(A0, W0)

perm_pass = []
perm_max = []
perm_curv_max = []
perm_inter_max = []
perm_inter_meas_max = []
perm_win_max = []
sigma = list(range(N_T))
for _ in range(N_PERM):
    rnd.shuffle(sigma)
    Ai = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Wi = {v: perm_int(W_bits[v], sigma) for v in SIGN_VINTAGES}
    h, st = run_family(Ai, Wi)
    perm_pass.append(len(h))
    perm_max.append(max(st) if st else 0.0)
    cv = run_curv(Ai, Wi)
    perm_curv_max.append(max(x for _, x in cv) if cv else 0.0)
    iv = run_inter(Ai, Wi)
    perm_inter_max.append(max(x for _, x in iv) if iv else 0.0)
    ivm = run_inter(Ai, Wi, base="meas")
    perm_inter_meas_max.append(max(x for _, x in ivm) if ivm else 0.0)
    # 窓側は同じ置換 sigma を front/back の束へ当てる（front と back の相関を保つ）
    Wsi = {k: perm_int(b, sigma) for k, b in win_bits_seg.items()}
    wv = run_window(Wsi)
    perm_win_max.append(max(x for _, x in wv) if wv else 0.0)


def pctl(arr, p):
    s = sorted(arr)
    return r4(s[min(len(s) - 1, max(0, int(p * len(s)) - 1))])


fpr = {
    "n_permutations": N_PERM,
    "n_tests_in_family": len(family),
    "family_composition": dict(Counter(fam_kind)),
    "null_construction": ("特徴量側（母集団マスク・群マスク）を固定し、outcome の束"
                          "(解析集合, win)をティッカーごとまとめて置換する。ビンテージ間の outcome 相関・"
                          "欠測構造・母集団の定義を保ったまま、特徴量↔outcome だけを壊す。兄弟器と同じ帰無。"),
    "P_at_least_one_pass": r4(sum(1 for x in perm_pass if x > 0) / N_PERM),
    "mean_passes_per_permutation": r4(sum(perm_pass) / N_PERM),
    "max_passes_in_a_permutation": max(perm_pass),
    "observed_passes_gates123": len(obs_hits),
    "observed_hits": obs_hits[:40],
    "null_max_statistic": {
        "statistic": "家族の中で最大の『符号が揃ったうえでの3ビンテージ最小|lift|』",
        "p50": pctl(perm_max, .50), "p90": pctl(perm_max, .90), "p95": pctl(perm_max, .95),
        "p99": pctl(perm_max, .99), "max": r4(max(perm_max)),
        "observed": r4(max(obs_stats) if obs_stats else 0.0),
        "empirical_p": r4(sum(1 for m in perm_max if m >= (max(obs_stats) if obs_stats else 0)) / N_PERM)},
    "null_max_curvature": {
        "statistic": "家族の中で最大の『符号が揃ったうえでの3ビンテージ最小|curvature|』（prereg に無い統計量）",
        "n_tests": len(curv_masks),
        "p50": pctl(perm_curv_max, .50), "p90": pctl(perm_curv_max, .90),
        "p95": pctl(perm_curv_max, .95), "p99": pctl(perm_curv_max, .99),
        "max": r4(max(perm_curv_max)),
        "observed": r4(max(x for _, x in obs_curv) if obs_curv else 0.0),
        "empirical_p": r4(sum(1 for m in perm_curv_max
                              if m >= (max(x for _, x in obs_curv) if obs_curv else 0)) / N_PERM),
        "how_to_read": "曲率には prereg の線が無い。ここの p95 を『これ以下は雑音』の目安に使う。"
                       "**目安であって合否ではない**"},
    "null_max_interaction_small_minus_large": {
        "statistic": "家族の中で最大の『符号が揃ったうえでの3ビンテージ最小|小の lift − 大の lift|』",
        "n_tests": len(inter_masks),
        "p50": pctl(perm_inter_max, .50), "p90": pctl(perm_inter_max, .90),
        "p95": pctl(perm_inter_max, .95), "p99": pctl(perm_inter_max, .99),
        "max": r4(max(perm_inter_max)),
        "observed": r4(max(x for _, x in obs_inter) if obs_inter else 0.0),
        "empirical_p": r4(sum(1 for m in perm_inter_max
                              if m >= (max(x for _, x in obs_inter) if obs_inter else 0)) / N_PERM),
        "why": "per-stratum の lift に張った帰無は、**差**の帰無ではない。"
               "差だけを見て『交互作用がある』と言う前に、雑音の中で差がどれだけ出るかを見る。"},
    "null_max_interaction_measurable_base": {
        "statistic": "同上だが分母を可測部分集合にした版（＝欠測の交絡を外した差）",
        "p50": pctl(perm_inter_meas_max, .50), "p95": pctl(perm_inter_meas_max, .95),
        "p99": pctl(perm_inter_meas_max, .99), "max": r4(max(perm_inter_meas_max)),
        "observed": r4(max(x for _, x in obs_inter_meas) if obs_inter_meas else 0.0),
        "empirical_p": r4(sum(1 for m in perm_inter_meas_max
                              if m >= (max(x for _, x in obs_inter_meas) if obs_inter_meas else 0)) / N_PERM),
        "why": "『その変数の値』が層で違う効き方をするのか、『その変数を報告している社』が層で違うのか、"
               "を切り分けるための同じ帰無。**二つの経験pが大きく違えば、後者を見ている。**"},
    "null_max_front_minus_back": {
        "statistic": "家族の中で最大の『anchor2016/2017 で符号が揃ったうえでの最小|前半lift − 後半lift|』",
        "n_tests": len(win_masks),
        "p50": pctl(perm_win_max, .50), "p90": pctl(perm_win_max, .90),
        "p95": pctl(perm_win_max, .95), "p99": pctl(perm_win_max, .99),
        "max": r4(max(perm_win_max)),
        "observed": r4(max(x for _, x in obs_window) if obs_window else 0.0),
        "empirical_p": r4(sum(1 for m in perm_win_max
                              if m >= (max(x for _, x in obs_window) if obs_window else 0)) / N_PERM),
        "why": "置換は ticker 単位なので front と back の相関ごと保たれる＝"
               "『同じ会社の前半と後半』という構造を壊さずに、特徴量との結びつきだけを壊した帰無。"},
    "why_this_matters": ("交互作用の探索は検定数を一気に増やす。単変量器の家族は168だったが、"
                         "この道具は %d。**線が同じでも家族が大きいほど偶然に通る確率は上がる**ので、"
                         "『層Xで合格した』を読む前に必ずこの数字を見ること。" % len(family)),
}


# ══════════════════════════════════════════════════════════════════
# 結果を見る前に出す(4): 陽性対照（注入検査）
# ══════════════════════════════════════════════════════════════════
def inject(key, kind, true_lift=0.25):
    """合成変数を全行に書く。kind='U'（両端が高い）／'small_only'（小型でだけ効く）。"""
    for v in ALL_VINTAGES:
        R = pop_rows(v, "P_full")
        n = len(R)
        wins = [r for r in R if r.get("win")]
        loss = [r for r in R if not r.get("win")]
        base = rate(len(wins), n)
        if kind == "U":
            g = max(1, int(n * 0.4))       # 両端1/5×2 = 40%
            k_want = min(len(wins), max(MIN_NUM, int(round((base + true_lift) * g))))
            rnd.shuffle(wins)
            rnd.shuffle(loss)
            grp = set(id(r) for r in wins[:k_want] + loss[:g - k_want])
            for r in R:
                # 群は両端（0-0.2 と 0.8-1.0）、非群は中間（0.2-0.8）へ置く
                r[key] = (rnd.choice([rnd.random() * 0.2, 0.8 + rnd.random() * 0.2])
                          if id(r) in grp else 0.2 + rnd.random() * 0.6)
        elif kind == "small_only":
            st, _ = size_strata(v, "P_full")
            small = set(id(r) for r in st["strata"]["小"]) if st else set()
            for r in R:
                r[key] = rnd.random()
            # 小型層の中でだけ「上半分の勝率 = base+true_lift」になるよう値を並べ替える
            srows = [r for r in R if id(r) in small]
            sw = [r for r in srows if r.get("win")]
            sl = [r for r in srows if not r.get("win")]
            b = rate(len(sw), len(srows)) if srows else 0
            g = max(1, len(srows) // 2)
            k_want = min(len(sw), max(MIN_NUM, int(round((b + true_lift) * g))))
            rnd.shuffle(sw)
            rnd.shuffle(sl)
            hi = set(id(r) for r in sw[:k_want] + sl[:g - k_want])
            for r in srows:
                r[key] = (0.5 + rnd.random() * 0.5) if id(r) in hi else rnd.random() * 0.5
        for r in by_v[v]:
            if key not in r:
                r[key] = None


def drop(key):
    for r in rows_all:
        r.pop(key, None)


positive_control = {}
# (a) U字の検出
inject("_ctrlU", "U")
cU = {v: shape_cell(v, "P_full", "_ctrlU") for v in SIGN_VINTAGES}
positive_control["U字_true_lift=0.25"] = {
    "shape_detected": {str(v): (cU[v] or {}).get("shape") for v in SIGN_VINTAGES},
    "curvature": {str(v): (cU[v] or {}).get("curvature") for v in SIGN_VINTAGES},
    "両端1/5_lift": {str(v): ((cU[v] or {}).get("両端1/5") or {}).get("lift_vs_pop") for v in SIGN_VINTAGES},
    "両端1/5_群と分子": {str(v): {"n_group": ((cU[v] or {}).get("両端1/5") or {}).get("n_group"),
                                  "numerator": ((cU[v] or {}).get("両端1/5") or {}).get("numerator"),
                                  "p_group": ((cU[v] or {}).get("両端1/5") or {}).get("p_group"),
                                  "p_base": (cU[v] or {}).get("p_pop")} for v in SIGN_VINTAGES},
    "中央値切り_lift（単変量器が見る側）": {
        str(v): (median_cut(pop_rows(v, "P_full"), "_ctrlU") or {}).get("lift") for v in SIGN_VINTAGES},
    "how_to_read": "**中央値切りの lift はほぼ0なのに両端 cut は 0.25 前後になる**のが正しい挙動。"
                   "これが『単調な物差しは U字を構造的に見落とす』ことの実証。"}
drop("_ctrlU")

# (b) 規模の交互作用の検出
inject("_ctrlS", "small_only")
ps = {}
for v in SIGN_VINTAGES:
    st, _ = size_strata(v, "P_full")
    ps[str(v)] = {s: (median_cut(st["strata"][s], "_ctrlS") or {}).get("lift") for s in ("小", "中", "大")}
    ps[str(v)]["全体"] = (median_cut(pop_rows(v, "P_full"), "_ctrlS") or {}).get("lift")
positive_control["規模の交互作用_true_lift=0.25(小型のみ)"] = {
    "lift_by_stratum": ps,
    "how_to_read": "小=0.25前後・中/大=0付近・全体は薄まって0.08前後、が正しい挙動。"
                   "**全体だけ見ていると見落とす**ことの実証。"}
drop("_ctrlS")
positive_control["_how_to_read"] = (
    "『非単調は見つからなかった』『交互作用は無かった』という結論ほど、先に道具を疑う。"
    "本物を仕込んだら同じ経路で検出できることを実測してある（recalc_roic の ADBE 事故と同型の予防）。")


# ══════════════════════════════════════════════════════════════════
# 判定と序列
# ══════════════════════════════════════════════════════════════════
def judge_family(label, per_v):
    """家族の1検定に prereg のゲート1-3を当てる（4,5は下で個別に）。"""
    lifts, ks = [], []
    for v in SIGN_VINTAGES:
        pm, gm = per_v[v]
        npop = (pm & A0[v]).bit_count()
        kpop = (pm & W0[v]).bit_count()
        ng = (gm & A0[v]).bit_count()
        kg = (gm & W0[v]).bit_count()
        if npop == 0 or ng == 0:
            return None
        lifts.append(kg / ng - kpop / npop)
        ks.append(kg)
    signs = {1 if x > 0 else (-1 if x < 0 else 0) for x in lifts}
    return {"lifts": [r4(x) for x in lifts], "numerators": ks,
            "sign_stable": len(signs) == 1 and 0 not in signs,
            "min_abs_lift": r4(min(abs(x) for x in lifts)),
            "min_numerator": min(ks),
            "gates123": (len(signs) == 1 and 0 not in signs
                         and min(abs(x) for x in lifts) >= LIFT and min(ks) >= MIN_NUM)}


family_judged = []
for label, per_v in family:
    j = judge_family(label, per_v)
    if j:
        j["test"] = label
        j["kind"] = label.split("|")[0]
        family_judged.append(j)
family_judged.sort(key=lambda x: -(x["min_abs_lift"] if x["sign_stable"] else -1))

# ── 分子ゲートの非対称性（結果の前に決めた線が、負の lift に不利に働く）──
# prereg は「事象の分子>=5社」を勝者側にも破壊側にも課す。ところが**目的Aの負の lift**は
# 「その群に勝者がほとんど居ない」ことが証拠なので、群の分子は構造的に小さくなる。
# 層に割ると群が 30-50 行になり、負の lift ほど分子5に届かない＝**線が符号に非対称に効く**。
# これは prereg の欠陥ではなく性質。ただし「不合格」と書く前に数えておく。
asym = {"n_tests": len(family_judged),
        "sign_stable_and_lift_ok_but_numerator_short": [],
        "by_sign": {"positive": 0, "negative": 0}}
for r in family_judged:
    if not r["sign_stable"]:
        continue
    neg = r["lifts"][0] < 0
    asym["by_sign"]["negative" if neg else "positive"] += 1
    if r["min_abs_lift"] >= LIFT and r["min_numerator"] < MIN_NUM:
        asym["sign_stable_and_lift_ok_but_numerator_short"].append(
            {"test": r["test"], "lifts": r["lifts"], "numerators": r["numerators"],
             "sign": "負" if neg else "正"})
asym["note"] = ("|lift|>=0.15 を3ビンテージで維持したのに分子5で落ちた検定の一覧。"
                "**この一覧が負の lift ばかりなら、線が符号に非対称**という読み方をする。"
                "実測ではここが空でも、負の lift の検定が家族に何本あるかは by_sign に出る。")

# ── (a) 形状の序列（曲率が帰無 p95 を超え、かつ3ビンテージで符号一致するもの）
curv_p95 = fpr["null_max_curvature"]["p95"]
shape_rank = []
for var in CANDIDATES:
    for pop in POPS:
        cs = {v: shape_cells.get("%s|%s|%d" % (var, pop, v)) for v in ALL_VINTAGES}
        got = [cs[v]["curvature"] for v in SIGN_VINTAGES
               if cs.get(v) and cs[v].get("curvature") is not None]
        if len(got) != 3:
            # 3ビンテージそろわない＝符号安定を当てられない（判定不能）。記録だけ残す
            any_c = [(v, cs[v]) for v in ALL_VINTAGES if cs.get(v) and cs[v].get("curvature") is not None]
            if any_c:
                v0, c0 = any_c[-1]
                shape_rank.append({
                    "variable": var, "population": pop, "vintages_with_shape": [v for v, _ in any_c],
                    "sign_stable_161718": None, "min_abs_curvature": None,
                    "curvature_anchor": c0["curvature"], "anchor_vintage": v0,
                    "shape_anchor": c0["shape"],
                    "extremes_lift_anchor": (c0.get("両端1/5") or {}).get("lift_vs_pop"),
                    "verdict": "判定不能",
                    "reason": "2016/2017/2018 の3つで形を測れない（prereg の必須ゲートを当てられない）"})
            continue
        signs = {1 if x > 0 else (-1 if x < 0 else 0) for x in got}
        stable = len(signs) == 1 and 0 not in signs
        shapes = [cs[v]["shape"] for v in SIGN_VINTAGES]
        ext = [(cs[v].get("両端1/5") or {}).get("lift_vs_pop") for v in SIGN_VINTAGES]
        med = [(median_cut(pop_rows(v, pop), var) or {}).get("lift") for v in SIGN_VINTAGES]
        shape_rank.append({
            "variable": var, "population": pop,
            "curvatures_161718": [r4(x) for x in got],
            "sign_stable_161718": stable,
            "min_abs_curvature": r4(min(abs(x) for x in got)) if stable else None,
            "beyond_null_p95": (stable and min(abs(x) for x in got) >= (curv_p95 or 9)),
            "shapes_161718": shapes,
            "shape_label_same_161718": len(set(shapes)) == 1,
            "extremes_lift_161718": ext,
            "median_cut_lift_161718": med,
            # 単調な物差しでは見えないのに形はある＝この道具の存在理由
            "hidden_from_monotone_tests": (
                stable and min(abs(x) for x in got) >= (curv_p95 or 9)
                and all(m is not None and abs(m) < 0.05 for m in med)),
            "quintiles_2018": (cs[2018] or {}).get("quintiles"),
        })
shape_rank.sort(key=lambda x: -(x["min_abs_curvature"] if x.get("min_abs_curvature") is not None else -1))

# ── (b) 規模の交互作用の序列
size_rank = []
for key, d in size_inter.items():
    var, pop = key.split("|")
    st = d["stability"]
    it = st["_interaction"]
    small, large = st["小"], st["大"]
    size_rank.append({
        "variable": var, "population": pop,
        "lift_small_161718": small["lifts_161718"], "lift_mid_161718": st["中"]["lifts_161718"],
        "lift_large_161718": large["lifts_161718"],
        "interaction_diffs_161718": it["diffs_161718"],
        "interaction_sign_stable": it["sign_stable"],
        "min_abs_interaction": it["min_abs_diff"],
        # 欠測の交絡（この道具でいちばん効いた検査）
        "interaction_diffs_measurable_161718": it["diffs_measurable_161718"],
        "min_abs_interaction_measurable": it["min_abs_diff_measurable"],
        "shrink_when_missingness_removed": it["shrink_when_missingness_removed"],
        "missingness_confounded": ((it["shrink_when_missingness_removed"] or 0) >= 0.03),
        "coverage_small_vs_large_2018": (d["by_vintage"].get("2018") or {}).get("coverage_small_vs_large"),
        "p_missing_small_vs_large_2018": (d["by_vintage"].get("2018") or {}).get("p_missing_small_vs_large"),
        "small_passes_gates123": (small["sign_stable"] is True
                                  and (small["min_abs_lift"] or 0) >= LIFT
                                  and (small["min_numerator"] or 0) >= MIN_NUM),
        "large_passes_gates123": (large["sign_stable"] is True
                                  and (large["min_abs_lift"] or 0) >= LIFT
                                  and (large["min_numerator"] or 0) >= MIN_NUM),
        "small_min_abs_lift": small["min_abs_lift"], "large_min_abs_lift": large["min_abs_lift"],
    })
    r = size_rank[-1]
    r["interaction_claim"] = (r["small_passes_gates123"] != r["large_passes_gates123"]
                              and r["interaction_sign_stable"] is True
                              and (r["min_abs_interaction"] or 0) >= LIFT)
size_rank.sort(key=lambda x: -(x["min_abs_interaction"] if x["interaction_sign_stable"] else -1))

# ── (c) 業種の交互作用の序列
sector_rank = []
for key, d in sector_inter.items():
    var, pop = key.split("|")
    per_v = d["by_vintage"]
    if not all(per_v.get(str(v)) for v in SIGN_VINTAGES):
        continue
    ov = [per_v[str(v)]["overall"]["lift"] for v in SIGN_VINTAGES]
    mh = [(per_v[str(v)]["mh_sector_adjusted"] or {}).get("mh_risk_diff") for v in SIGN_VINTAGES]
    # 業種の影の署名: 全体の lift が MH 調整でどれだけ縮むか／一業種を抜くとどうなるか
    shrink = [r4(abs(a) - abs(b)) if (a is not None and b is not None) else None for a, b in zip(ov, mh)]
    per_sector_pass, per_sector_k, per_sector_ng = {}, {}, {}
    for v in SIGN_VINTAGES:
        for s, dd in per_v[str(v)]["sectors"].items():
            per_sector_pass.setdefault(s, []).append(dd["lift"])
            per_sector_k.setdefault(s, []).append(dd["k"])
            per_sector_ng.setdefault(s, []).append(dd["n_group"])
    sect_stable = {}
    for s, ls in per_sector_pass.items():
        ks = per_sector_k[s]
        sect_stable[s] = {
            "lifts": ls, "numerators": ks, "n_group": per_sector_ng[s],
            "sign_stable": (len({1 if x > 0 else (-1 if x < 0 else 0) for x in ls}) == 1
                            and 0 not in {1 if x > 0 else (-1 if x < 0 else 0) for x in ls})
            if len(ls) == 3 else None,
            "min_abs": r4(min(abs(x) for x in ls)) if len(ls) == 3 else None,
            "min_numerator": min(ks) if len(ks) == 3 else None,
            # ⚠ prereg の分子>=5 を満たさない群の lift は、大きく見えても読んではいけない
            #   （実測: sic67 の 0.2857 は n_group=3・k=1・事象総数2 で作られていた）
            "min_num_ok": (min(ks) >= MIN_NUM) if len(ks) == 3 else None}
    # 「最良」は**分子>=5を満たすものの中から**選ぶ。満たさない最大値は別枠で警告つきに出す。
    ok_cells = {s: d for s, d in sect_stable.items() if d["sign_stable"] and d["min_num_ok"]}
    best_s, best = None, None
    if ok_cells:
        best_s = max(ok_cells, key=lambda s: ok_cells[s]["min_abs"])
        best = ok_cells[best_s]
    bad_cells = {s: d for s, d in sect_stable.items() if d["sign_stable"] and not d["min_num_ok"]}
    worst_s = max(bad_cells, key=lambda s: bad_cells[s]["min_abs"]) if bad_cells else None
    sector_rank.append({
        "variable": var, "population": pop,
        "overall_lift_161718": ov, "mh_adjusted_161718": mh,
        "abs_shrink_after_mh_161718": shrink,
        "sector_shadow_signature": (all(x is not None and x >= 0.03 for x in shrink)
                                    if all(x is not None for x in shrink) else None),
        "n_sectors_measured_2018": per_v["2018"]["n_sectors_measured"],
        "max_abs_sector_lift_2018": per_v["2018"]["max_abs_sector_lift"],
        "argmax_sector_2018": per_v["2018"]["argmax_sector"],
        "best_stable_sector": best_s,
        "best_stable_sector_min_abs_lift": (best or {}).get("min_abs"),
        "best_stable_sector_lifts": (best or {}).get("lifts"),
        "best_stable_sector_numerators": (best or {}).get("numerators"),
        # 分子<5 で読んではいけない側（大きく見えるが空証明）
        "largest_but_unreadable_sector": worst_s,
        "largest_but_unreadable_min_abs_lift": (bad_cells.get(worst_s) or {}).get("min_abs"),
        "largest_but_unreadable_numerators": (bad_cells.get(worst_s) or {}).get("numerators"),
        "sectors_stable": sect_stable,
    })
sector_rank.sort(key=lambda x: -(x["best_stable_sector_min_abs_lift"] or -1))

# ── (d) 窓の序列
window_rank = []
for key, d in window_inter.items():
    var, pop = key.split("|")
    a16 = d["by_anchor"].get("2016")
    if not a16:
        continue
    window_rank.append({
        "variable": var, "population": pop,
        "front_lift_2016_2018(2.0y)": a16["segments"]["front"]["lift"],
        "back_lift_2018_2026(8.09y)": a16["segments"]["back"]["lift"],
        "full_lift_2016_2026(10.09y)": a16["segments"]["full"]["lift"],
        "front_minus_back": a16["front_minus_back_lift"],
        "front_base": a16["segments"]["front"]["p_base"],
        "back_base": a16["segments"]["back"]["p_base"],
        "front_rank_corr": a16["segments"]["front"]["rank_corr"],
        "back_rank_corr": a16["segments"]["back"]["rank_corr"],
        "sign_stable_1617": d["sign_stable_1617"],
        "front_minus_back_1617": d["front_minus_back_1617"],
    })
window_rank.sort(key=lambda x: -abs(x["front_minus_back"] or 0))


# ══════════════════════════════════════════════════════════════════
# 出力
# ══════════════════════════════════════════════════════════════════
# ── 既知の非単調（backtest_core: through-cycle ROIC 最上位五分位が劣後）の突合せ ──
# ⚠ 同じ「ROIC」ではない: co_roic_* は gate0式（のれん・無形を控除しない・門式ROICではない）で、
#   backtest_core は門式 through-cycle。さらに outcome も違う（あちらは中央値リターン・こちらは P(win)）。
#   だから「再現しない」は矛盾ではなく**別の測定**。ただし同じ道具で両方の物差しを出して並べる。
known_nonmono = {}
for var in ("co_roic_med5", "co_roic_latest", "co_roic_worst5", "co_opm", "co_sales_cagr5"):
    for pop in ("P_full", "P_quality"):
        for v in (2013, 2015):
            c = shape_cells.get("%s|%s|%d" % (var, pop, v))
            if not c or not c.get("quintiles"):
                continue
            known_nonmono["%s|%s|%d" % (var, pop, v)] = {
                "shape_by_P_win": c.get("shape"),
                "curvature_P_win": c.get("curvature"),
                "quintiles_P_win": [x["p"] for x in c["quintiles"]],
                "quintiles_median_return": [x["median_tr_cagr"] for x in c["quintiles"]],
                "curvature_median_return": c.get("curvature_median_return"),
                "median_return_argmax_quintile": c.get("median_return_argmax_quintile"),
                "median_return_top_reversal": c.get("median_return_top_reversal"),
                "n_by_quintile": [x["n"] for x in c["quintiles"]],
            }
known_nonmono["_note"] = (
    "backtest_core の実測『through-cycle ROIC 五分位の実現リターン中央値: Q1 13.1 / Q4 15.6 / **Q5 10.4**』は "
    "(1)門式ROIC (2)中央値リターン、で測られている。ここの co_roic_* は gate0式・別パイプラインで、"
    "P(win) と中央値リターンの両方を出してある。**同じ名前でも同じ量ではない**ので"
    "『再現した/しなかった』ではなく『どの物差しで何が見えるか』として読むこと。")

# ── 「線を越えて見えるが、分子で読めない」セルの全数（4分析を横断） ──
# 合格ゼロと並べて必ず出す。**目を引く数字がどこにあり、なぜ読めないか**を示さないと、
# 次に見る人が同じ場所を掘って同じ 0.28 を『発見』する。
# 実測でここに並ぶのは sic67 の 0.2857(k=1) や co_equity_neg の 0.2353(k=3/7社) の型。
eye = []
for key, c in shape_cells.items():
    var, pop, v = key.split("|")
    e = c.get("両端1/5")
    if e and e.get("lift_vs_pop") is not None and abs(e["lift_vs_pop"]) >= LIFT and e["numerator"] < MIN_NUM:
        eye.append({"where": "a_shape 両端1/5", "cell": key, "lift": e["lift_vs_pop"],
                    "numerator": e["numerator"], "n_group": e["n_group"]})
for key, d in size_inter.items():
    for v, cell in d["by_vintage"].items():
        if not cell:
            continue
        for sname, mc in cell["strata"].items():
            if mc and mc.get("lift") is not None and abs(mc["lift"]) >= LIFT and mc["numerator"] < MIN_NUM:
                eye.append({"where": "b_size 規模" + sname, "cell": "%s|%s" % (key, v),
                            "lift": mc["lift"], "numerator": mc["numerator"], "n_group": mc["n_group"]})
for key, d in sector_inter.items():
    for v, cell in d["by_vintage"].items():
        if not cell:
            continue
        for s, dd in cell["sectors"].items():
            if abs(dd["lift"]) >= LIFT and dd["k"] < MIN_NUM:
                eye.append({"where": "c_sector 業種" + s, "cell": "%s|%s" % (key, v),
                            "lift": dd["lift"], "numerator": dd["k"], "n_group": dd["n_group"]})
for store, tag in ((window_inter, "d_window f2"), (window_inter_co, "d_window co")):
    for key, d in store.items():
        for anchor, a in d["by_anchor"].items():
            for seg, s in a["segments"].items():
                if abs(s["lift"]) >= LIFT and s["k"] < MIN_NUM:
                    eye.append({"where": "%s %s(%s)" % (tag, seg, anchor), "cell": key,
                                "lift": s["lift"], "numerator": s["k"], "n_group": s["n_group"]})
eye.sort(key=lambda x: -abs(x["lift"]))
eye_catching = {
    "n": len(eye),
    "note": ("|lift|>=0.15 を満たすのに prereg の『事象の分子>=5社』で読めないセル。"
             "**大きな lift と確かな lift は別物**。ここに並ぶ数字を引用してはいけない。"),
    "rows": eye[:40],
}

n_shape_pass = sum(1 for r in shape_rank if r.get("beyond_null_p95"))
n_size_claim = sum(1 for r in size_rank if r.get("interaction_claim"))
n_family_pass = sum(1 for r in family_judged if r["gates123"])

doc = {
    "generated": "2026-08-11",
    "tool": "night/hist_wd_win_shape.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "inputs": {"panel": "out/hist_wd_panel.json", "sibling_univariate": "out/hist_wd_win_uni.json"},
    "objective": "A_勝者: P(実現年率 >= +15%)。この道具は『効くか』ではなく『**どこで効き、どこで消えるか**』を測る。",
    "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM, "sign_vintages": SIGN_VINTAGES,
                       "note": "prereg のまま。この道具は線を一つも作っていない。"
                               "曲率(curvature)だけは prereg に無い統計量＝**事前登録の外**で、"
                               "合否には使わず帰無分布(p95)を目安として出すに留める。"},
    "design_decisions": {
        "analysis_set": "has_outcome ∧ window_full",
        "interaction_cut": "中央値切りに事前固定（層に割ると四分位の群が薄すぎる。結果を見てから切り方を選ばない）",
        "shape_cut": "五分位＋『両端1/5 vs 母集団』。後者は prereg に無い cut を1本足したもの＝家族が増えるので FPR を測り直した",
        "extra_cut_is_outside_prereg": "両端 cut と曲率は prereg の候補表に無い。増えた検定数は false_positive_rate に反映済み",
        "size_strata": "各(ビンテージ,母集団)の中の三分位。**絶対額の閾値をビンテージ間で共有しない**"
                       "（size_rev の出所が f2_rev と co_rev_asof で違う＝基準の違う二つを割らないため）",
        "sector_strata": "sic2・n>=%d のみ。retro_sic は『現在の』登録分類で時点付きではない＝粗い層別専用" % MIN_SECTOR_N,
        "window": "終端日が5ファイルとも 2026-08-04 で共通なので tr_total の比が厳密に前半の実現になる"
                  "（night/irr85_windows.py と同じ復元式）",
    },
    "known_confounds_stated_up_front": [
        "(d) 前半窓は特徴量が新しく、後半窓は古い（鮮度）。2016アンカーなら鮮度差は2年で最小になるが、ゼロではない。",
        "(d) 短い窓は個社ノイズが大きく lift を機械的に縮める（減衰）。front(2.0年) と back(8.09年) の"
        "lift を直接比べると、相場の差だけでなく減衰の差も混ざる。だから rank_corr も併記する。",
        "(d) lift は base に上から押さえられる（p<=1）。窓ごとに base が違うので risk_ratio も併記する。",
        "(b)(c) 層に割ると n が 1/3〜1/10 になり、検出力が構造的に落ちる（power の表）。"
        "『層Xでだけ合格』は、まず検出力と FPR を見てから読む。",
        "全体: 2016/2017/2018 は同じ956ティッカーで outcome の Spearman は 0.845〜0.961＝独立な3証拠ではない。",
    ],
    "cross_check_vs_win_uni": cross,
    "window_reconstruction_identity_check": window_identity,
    "window_rounding_probe": rounding_probe,
    "must_report_before_verdict": {
        "reachability": reach,
        "window_reachability": window_reach,
        "power": power,
        "false_positive_rate": fpr,
        "positive_control_injection": positive_control,
    },
    "answer": {
        "_how_to_read": ("各分析の答えは『何本合格したか』と『最大の統計量が帰無のどこに居るか』の対で読む。"
                         "件数だけだと、符号一致のように偶然50%で起きるものを発見と読んでしまう。"),
        "a_shape": {
            "n_beyond_null_p95": n_shape_pass,
            "n_hidden_from_monotone_tests": sum(1 for r in shape_rank
                                                if r.get("hidden_from_monotone_tests")),
            "max_stat_vs_null": {k: fpr["null_max_curvature"][k]
                                 for k in ("observed", "p50", "p95", "empirical_p")},
            "verdict": "非単調は見つからない。実データの最大曲率は帰無の中央値とほぼ同じ"},
        "b_size": {
            "n_interaction_claims": n_size_claim,
            "max_stat_vs_null": {k: fpr["null_max_interaction_small_minus_large"][k]
                                 for k in ("observed", "p50", "p95", "empirical_p")},
            "max_stat_vs_null_measurable_base": {k: fpr["null_max_interaction_measurable_base"][k]
                                                 for k in ("observed", "p50", "p95", "empirical_p")},
            "verdict": ("母集団基準では最大 %s（経験p %s）で家族全体の雑音を唯一超えたが、"
                        "**欠測の交絡を外すと %s（経験p %s）へ落ちる**＝"
                        "見ていたのは『値が層で違う効き方をする』ではなく"
                        "『その変数を報告している社が層で違う』ほう"
                        % (fpr["null_max_interaction_small_minus_large"]["observed"],
                           fpr["null_max_interaction_small_minus_large"]["empirical_p"],
                           fpr["null_max_interaction_measurable_base"]["observed"],
                           fpr["null_max_interaction_measurable_base"]["empirical_p"]))},
        "c_sector": {
            "n_with_shadow_signature": sum(1 for r in sector_rank if r.get("sector_shadow_signature")),
            "max_overall_abs_lift": r4(max((abs(x) for r in sector_rank
                                            for x in r["overall_lift_161718"]), default=None)),
            "max_stable_sector_lift_with_numerator_ge5": (sector_rank[0]["best_stable_sector_min_abs_lift"]
                                                          if sector_rank else None),
            "verdict": ("業種の影を疑う前提（全体の lift が大きい）が成立していない——"
                        "全体の lift は最大 %s。個別業種で大きく見えるセルは分子<5 で読めない"
                        % r4(max((abs(x) for r in sector_rank
                                  for x in r["overall_lift_161718"]), default=None))),
        },
        "d_window": {
            "n_sign_stable_front_vs_back": sum(1 for r in window_rank if r.get("sign_stable_1617")),
            "n_sign_stable_is_not_evidence": "符号一致は2アンカーなら偶然でも約50%起きる。下の帰無で読むこと",
            "max_stat_vs_null": {k: fpr["null_max_front_minus_back"][k]
                                 for k in ("observed", "p50", "p95", "empirical_p")},
            "verdict": "前半と後半で効き方が変わる変数は見つからない（最大差が帰無の中央値以下）",
        },
        "family_gates123_passes": n_family_pass,
        "eye_catching_but_unreadable": eye_catching["n"],
    },
    "eye_catching_but_unreadable": eye_catching,
    "numerator_gate_asymmetry": asym,
    "known_nonmonotone_crosscheck": known_nonmono,
    "a_shape_rank": shape_rank[:60],
    "b_size_rank": size_rank[:40],
    "c_sector_rank": sector_rank[:40],
    "d_window_rank": window_rank[:40],
    "d_window_co_2013_2015": window_inter_co,
    "d_pure_length_effect": {
        "method": "同じ実現(tr_total)・同じ母集団のまま、年率換算の指数 1/T だけを差し替える。"
                  "順位は動かないので、動くのは『何%が勝者に数えられるか』だけ＝純粋な長さの効果。",
        "by_anchor": pure_length},
    "family_judged": family_judged[:60],
    "detail": {
        "shape_cells": shape_cells,
        "size_interaction": size_inter,
        "sector_interaction": sector_inter,
        "window_interaction_f2": window_inter,
    },
}

json.dump(doc, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print("解析集合: " + " / ".join("%d:%d行(%d勝)" % (v, len(by_v[v]), sum(1 for r in by_v[v] if r.get("win")))
                                for v in ALL_VINTAGES))
print("\n■ 兄弟器との突合せ（写した式が同じ数字を出すか）")
print("  五分位 %d/%d 一致 ／ 中央値切りlift %d 一致 ／ 不一致 %d+%d → %s"
      % (cross["quintile_match"], cross["checked"], cross["median_lift_match"],
         len(cross["quintile_mismatch"]), len(cross["median_lift_mismatch"]), cross["verdict"]))

print("\n■ 結果の前に(1) 到達可能性（層に割ると事象が5に届くか）")
for k in ("2016/P_full", "2016/P_quality", "2018/P_full", "2018/P_quality"):
    c = reach[k]
    st = c.get("size_terciles", {})
    print("  %-18s n=%3d 事象=%3d base=%.3f ｜ 規模三分位の事象: %s ｜ 使える業種 %d個(%s%%の行)"
          % (k, c["n"], c["events"], c["base"],
             " ".join("%s%d" % (s, st[s]["events"]) for s in ("小", "中", "大") if s in st),
             c["n_sectors_usable"], round(100 * (c["share_rows_in_usable_sectors"] or 0))))

print("\n■ 結果の前に(2) 検出力（層に割ると何が起きるか・真lift=0.20）")
for k, d in power.items():
    if k.startswith("_"):
        continue
    r = d["by_true_lift"]["0.2"]
    print("  %-32s n=%4d 下限 %.3f / 上限 %.3f" % (k, d["n"], r["three_independent"], r["single_vintage"]))

print("\n■ 結果の前に(3) 偽陽性率（置換%d回・家族 %d検定 %s）"
      % (N_PERM, fpr["n_tests_in_family"], fpr["family_composition"]))
print("  偶然に1本以上通る確率 %s ／ 実データで通った本数 %s"
      % (fpr["P_at_least_one_pass"], fpr["observed_passes_gates123"]))
nm = fpr["null_max_statistic"]
print("  帰無の最大|lift|: p50=%s p95=%s p99=%s 最大=%s ／ 実データ=%s (経験p=%s)"
      % (nm["p50"], nm["p95"], nm["p99"], nm["max"], nm["observed"], nm["empirical_p"]))
nc = fpr["null_max_curvature"]
print("  帰無の最大|曲率|: p50=%s p95=%s p99=%s ／ 実データ=%s (経験p=%s)"
      % (nc["p50"], nc["p95"], nc["p99"], nc["observed"], nc["empirical_p"]))
ni = fpr["null_max_interaction_small_minus_large"]
print("  帰無の最大|小−大|: p50=%s p95=%s p99=%s ／ 実データ=%s (経験p=%s)"
      % (ni["p50"], ni["p95"], ni["p99"], ni["observed"], ni["empirical_p"]))
nw = fpr["null_max_front_minus_back"]
print("  帰無の最大|前半−後半|: p50=%s p95=%s p99=%s ／ 実データ=%s (経験p=%s)"
      % (nw["p50"], nw["p95"], nw["p99"], nw["observed"], nw["empirical_p"]))

print("\n■ 結果の前に(4) 陽性対照（本物を仕込んだら掴めるか）")
u = positive_control["U字_true_lift=0.25"]
print("  U字: 形=%s 曲率=%s 両端lift=%s ／ **中央値切りlift=%s（単調な物差しは見落とす）**"
      % (list(u["shape_detected"].values()), list(u["curvature"].values()),
         list(u["両端1/5_lift"].values()), list(u["中央値切り_lift（単変量器が見る側）"].values())))
s = positive_control["規模の交互作用_true_lift=0.25(小型のみ)"]["lift_by_stratum"]
print("  規模: " + " ".join("%s{小%s 中%s 大%s 全%s}" % (v, d["小"], d["中"], d["大"], d["全体"])
                            for v, d in s.items()))

print("\n■ (a) 形状 —— 曲率が3ビンテージで符号一致した上位12")
for r in shape_rank[:12]:
    if r.get("min_abs_curvature") is None:
        continue
    print("  曲率%.3f %-16s %-10s 形=%s 両端lift=%s 中央値lift=%s%s"
          % (r["min_abs_curvature"], r["variable"], r["population"],
             "/".join(str(x) for x in r["shapes_161718"]),
             r["extremes_lift_161718"], r["median_cut_lift_161718"],
             "  ← 単調な物差しでは見えない" if r.get("hidden_from_monotone_tests") else ""))
print("  帰無 p95 = %s を超えたもの: %d 本" % (curv_p95, n_shape_pass))

print("\n■ (b) 規模の交互作用 —— |小−大| が3ビンテージで符号一致した上位10")
for r in size_rank[:10]:
    print("  差%.3f(可測基準%s) %-16s %-10s 小=%s 大=%s 主張=%s%s"
          % (r["min_abs_interaction"] or 0, r["min_abs_interaction_measurable"],
             r["variable"], r["population"],
             r["lift_small_161718"], r["lift_large_161718"], r["interaction_claim"],
             "  ⚠欠測交絡" if r["missingness_confounded"] else ""))
mc = [r for r in size_rank[:10] if r["missingness_confounded"]]
if mc:
    r = mc[0]
    print("     ⚠ %s|%s の可測率(小/大)=%s・欠測側の勝率(小/大)=%s"
          % (r["variable"], r["population"], r["coverage_small_vs_large_2018"],
             r["p_missing_small_vs_large_2018"]))

print("\n■ (c) 業種の交互作用 —— 分子>=5 を満たす業種で3ビンテージ符号一致した上位10")
for r in sector_rank[:10]:
    print("  最良業種%s lift%s(分子%s) %-16s %-10s 全体lift=%s MH=%s"
          % (r["best_stable_sector"], r["best_stable_sector_min_abs_lift"],
             r["best_stable_sector_numerators"], r["variable"],
             r["population"], r["overall_lift_161718"], r["mh_adjusted_161718"]))
big = [r for r in sector_rank if r.get("largest_but_unreadable_min_abs_lift")]
big.sort(key=lambda r: -r["largest_but_unreadable_min_abs_lift"])
print("  ⚠ 分子<5 で読んではいけない『大きく見えるだけ』の上位3:")
for r in big[:3]:
    print("     業種%s lift%s 分子%s ← %s %s"
          % (r["largest_but_unreadable_sector"], r["largest_but_unreadable_min_abs_lift"],
             r["largest_but_unreadable_numerators"], r["variable"], r["population"]))

print("\n■ 既知の非単調（ROIC最上位が劣後）の突合せ —— P(win) と 中央値リターンの両方")
for k in ("co_roic_med5|P_full|2013", "co_roic_med5|P_full|2015",
          "co_roic_med5|P_quality|2013", "co_roic_med5|P_quality|2015"):
    e = known_nonmono.get(k)
    if e:
        print("  %-28s P(win)五分位=%s ／ 中央値リターン五分位=%s (最大はQ%s)"
              % (k, e["quintiles_P_win"], e["quintiles_median_return"],
                 e["median_return_argmax_quintile"]))

print("\n■ (d) 窓 —— 前半(2016-18・2.0年) と 後半(2018-26・8.09年) の lift 差 上位10")
for r in window_rank[:10]:
    print("  差%+.3f %-16s %-10s 前半=%s(base %s) 後半=%s(base %s) 符号安定(16/17)=%s"
          % (r["front_minus_back"] or 0, r["variable"], r["population"],
             r["front_lift_2016_2018(2.0y)"], r["front_base"],
             r["back_lift_2018_2026(8.09y)"], r["back_base"], r["sign_stable_1617"]))

co_rows = []
for k, v in window_inter_co.items():
    a = v["by_anchor"].get("2013")
    if a:
        co_rows.append((abs(a["front_minus_back_lift"]), k, a))
co_rows.sort(reverse=True)
print("\n■ (d補) AI相場の前だけを見た唯一の多年窓 —— anchor2013 前半(2013-18・5.0年) vs 後半(2018-26・8.09年)")
for _, k, a in co_rows[:6]:
    s = a["segments"]
    print("  差%+.3f %-26s 前半%+.4f(base %.3f) 後半%+.4f(base %.3f) 全%+.4f"
          % (a["front_minus_back_lift"], k, s["front"]["lift"], s["front"]["p_base"],
             s["back"]["lift"], s["back"]["p_base"], s["full"]["lift"]))
print("  ⚠ この窓は co_ 変数（2013/2015のみ）でしか作れない＝prereg の必須ゲート(2016/17/18)を当てられない＝判定不能")

print("  丸めの影響（tr_cagr版 vs tr_total版の前半）: " + " ".join(
    "%s→勝敗が変わる行 %d/%d(最大差%.3f)" % (k, v["n_win_flag_flips"], v["n_compared"], v["max_abs_diff"])
    for k, v in rounding_probe.items() if not k.startswith("_")))

print("\n■ 純粋な長さの効果（同じ実現・同じ母集団のまま指数 1/T だけ差し替え）")
for a in ("2013", "2018"):
    e = pure_length[a]
    print("  anchor%s(%.2f年 n=%d): 勝者率 %s"
          % (a, e["anchor_years"], e["n"],
             " ".join("T=%s→%.3f" % (k, v["win_p"]) for k, v in e["reannualized"].items())))
print("  ＝『勝者』の定義は窓の長さで2〜3倍動く。ビンテージ間で勝率の水準を直接比べてはいけない。")

print("\n■ 大きく見えるが分子<5 で読めないセル: %d 件（上位5）" % eye_catching["n"])
for r in eye_catching["rows"][:5]:
    print("  lift%+.4f 分子%d/%d  %s  %s" % (r["lift"], r["numerator"], r["n_group"],
                                             r["where"], r["cell"]))

print("\n■ 家族全体で prereg のゲート1-3を通ったもの: %d 本" % n_family_pass)
for r in family_judged[:10]:
    if r["gates123"]:
        print("  ★合格 %s lifts=%s k=%s" % (r["test"], r["lifts"], r["numerators"]))
print("\n■ 答え")
for k in ("a_shape", "b_size", "c_sector", "d_window"):
    print("  %-9s %s" % (k, doc["answer"][k]["verdict"]))
print("\n→ %s" % DEST)
