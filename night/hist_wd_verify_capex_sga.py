#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_capex_sga.py — 候補「f2_capex_r[下位1/4] ∧ f2_sga_r[中央値以下]（勝者側・P_quality）」を**潰しにかかる**検証。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json          … 5ビンテージ統合パネル（唯一の真実）
          out/hist_wd_win_pair.json       … 探索側の答え（**再現の突合せ相手**。信じる前に検算する）
          out/retro_returns_{2016,2017,2018}.json … 部分窓リターンの導出用（同じ終端日）
          out/retro_monthly_2018_2026.json … レジーム分割（あれば）
          out/retro_sic.json              … 業種の記述（層が同質かを見るため）
出力    : out/hist_wd_verify_capex_sga.json

────────────────────────────────────────────────────────────
この道具の立場
────────────────────────────────────────────────────────────
**反証が仕事であって確認ではない。** 候補に有利な数字を探さない。
prereg の5条件（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を**一つも緩めない**。
線を緩めた数字を出すときは必ず `事前登録の外・診断専用` と明記し、合否には数えない。
「測れない」と「不合格」を区別する。f2_ 特徴量は 2013/2015 に構造的に存在しない＝**判定不能**。

────────────────────────────────────────────────────────────
候補の中身（依頼で名指しされたもの。ここは動かさない）
────────────────────────────────────────────────────────────
  母集団 P_quality（opm>=10% ∧ 5年FCF全年黒字 ∧ 営業利益全年黒字）
  設備投資比 capex/売上 が下位1/4（2018: <=0.0200）∧ 販管費比 SG&A/売上 が中央値以下（2018: <=0.1841）
  ＝**資産が軽く、かつ販管費も薄い**社。探索側の弁は「不合格（業種調整でMHが0.15を維持できない）」。

────────────────────────────────────────────────────────────
当てる6つ（依頼どおり。1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 ビンテージ符号  : 2016/2017/2018 で符号が反転しないか。**群の重なりと窓の重なり**も出す
                    （『3ビンテージ一致』が3つの証拠なのか、同じ社の同じ8年を3回数えただけなのか）。
2 業種調整        : 同一 sic2 内で残るか。MH＋間接標準化＋層内置換＋業種1つずつ除去＋MHの層分解。
3 irr の影        : irr>=70 層内で残るか・irr と直交か。**通した試験に検出力があるか**も測る。
4 1社の影響       : ティッカーを1社ずつ**パネルごと**抜いて、閾値・母集団・群・条件を全部作り直す。
5 置換            : outcome の束をティッカーごと置換（ビンテージ間相関を保つ帰無）2000回＋多重検定の値札。
6 既存の関門との重複: 事業の収縮 / 利払カバー の生存者の中でも残るか（＝増分）。脚単独との増分も出す。

この候補に固有の追加検証（**候補に不利な側にしか働かない検査だけを足す**）:
  X1 交互作用       : 2×2 表。積の効果は2本の脚の足し算で説明できるか（＝組にする意味があるか）。
  X2 capex_r=0 問題 : 設備投資比の下位1/4が**「資産が軽い」なのか「capexタグが無い」なのか**（ルール7）。
  X3 業態の混入     : 群に金融・REIT・カジノ等、capex/SG&A の意味が製造業と違う業態が混じっていないか。
  X4 母集団の依存   : P_quality でしか働かないのか（P_full でも同じ向きに出るか）。
"""
import json, os, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
PAIR = os.path.join(OUT, "hist_wd_win_pair.json")
DEST = os.path.join(OUT, "hist_wd_verify_capex_sga.json")

# ─── prereg の線（読むだけ・作らない） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
N_PERM = 2000
SEED = 20260811

# ─── 候補（依頼で名指しされたもの。ここは動かさない） ───
CAND = {
    "population": "P_quality",
    "side": "winner",
    "legs": [("f2_capex_r", "下位1/4"), ("f2_sga_r", "中央値以下")],
    "label": "f2_capex_r[下位1/4] ∧ f2_sga_r[中央値以下]",
}

t0 = time.time()


# ────────────────────────────── 数学だけ（判定を含まない） ──────────────────────────────
def q_at(sorted_vals, q):
    """nearest-rank 分位（外挿しない）。探索側 hist_wd_win_pair.q_at と同一定義。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))
    return sorted_vals[k - 1]


def r4(x):
    return None if x is None else round(x, 4)


def rate(k, n):
    return (k / n) if n else None


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


def binom_tail_ge(n, k, p):
    """P(X>=k) for X~Bin(n,p)。検出力の解析計算に使う。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    tot = 0.0
    for i in range(k, n + 1):
        tot += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return tot


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
pair_out = json.load(open(PAIR, encoding="utf-8"))

rows_all = panel["rows"]
# 解析集合は探索側と同一（has_outcome ∧ window_full）。短窓は年率換算で両裾を膨らませるため。
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]

by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)
for v in by_v:
    tk = [r["ticker"] for r in by_v[v]]
    assert len(tk) == len(set(tk)), f"vintage {v} にティッカー重複"


def pop_rows(v, pop, rows_src=None):
    src = rows_src if rows_src is not None else by_v[v]
    return [r for r in src if r.get(pop) is True]


def cut_pred(cut, thr):
    if cut == "上位1/4":
        return lambda x: x >= thr
    if cut == "下位1/4":
        return lambda x: x <= thr
    if cut == "中央値超":
        return lambda x: x > thr
    if cut == "中央値以下":
        return lambda x: x <= thr
    raise ValueError(cut)


def cut_q(cut):
    return {"上位1/4": 0.75, "下位1/4": 0.25, "中央値超": 0.5, "中央値以下": 0.5}[cut]


def threshold(rows, var, cut):
    vals = sorted(r[var] for r in rows if r.get(var) is not None)
    return q_at(vals, cut_q(cut)), len(vals)


def build_group(v, pop, legs, rows_src=None):
    """群・可測集合・母集団を作る。分位は各変数が自分の分布（母集団内・可測行のみ）で切る。"""
    P = pop_rows(v, pop, rows_src)
    thrs = {}
    for var, cut in legs:
        thr, nm = threshold(P, var, cut)
        thrs[var] = {"cut": cut, "threshold": r4(thr), "_thr": thr, "n_measurable": nm}
    if any(t["_thr"] is None for t in thrs.values()):
        return None
    preds = {var: cut_pred(cut, thrs[var]["_thr"]) for var, cut in legs}
    meas, grp = [], []
    for r in P:
        if all(r.get(var) is not None for var, _ in legs):
            meas.append(r)
            if all(preds[var](r[var]) for var, _ in legs):
                grp.append(r)
    return {"pop": P, "meas": meas, "group": grp, "thresholds": thrs}


def cell(v, pop, legs, rows_src=None, win_of=None):
    """1ビンテージの実測。win_of は置換用に outcome を差し替えるフック（既定は行の win）。"""
    b = build_group(v, pop, legs, rows_src)
    if b is None:
        return None
    W = win_of if win_of else (lambda r: bool(r.get("win")))
    n_pop = len(b["pop"])
    k_pop = sum(1 for r in b["pop"] if W(r))
    n_g = len(b["group"])
    k_g = sum(1 for r in b["group"] if W(r))
    n_m = len(b["meas"])
    k_m = sum(1 for r in b["meas"] if W(r))
    p_base = rate(k_pop, n_pop)
    p_g = rate(k_g, n_g)
    p_m = rate(k_m, n_m)
    return {
        "n_pop": n_pop, "k_pop": k_pop, "p_base": r4(p_base),
        "n_group": n_g, "numerator": k_g, "p_group": r4(p_g),
        "lift": (None if p_g is None else r4(p_g - p_base)),
        "n_measurable_both": n_m,
        "lift_meas": (None if (p_g is None or p_m is None) else r4(p_g - p_m)),
        "thresholds": {k: {kk: vv for kk, vv in t.items() if not kk.startswith("_")}
                       for k, t in b["thresholds"].items()},
        "_group_rows": b["group"], "_pop_rows": b["pop"], "_meas_rows": b["meas"],
    }


def strip(c):
    return {k: v for k, v in c.items() if not k.startswith("_")} if c else None


# ────────────────────────────── 0. 再現と突合せ（信じる前に検算する） ──────────────────────────────
cells = {v: cell(v, CAND["population"], CAND["legs"]) for v in SIGN_VINTAGES}

ref = None
for e in pair_out.get("all_pairs", []):
    if e.get("label") == CAND["label"] and e.get("population") == CAND["population"]:
        ref = e
        break

_lifts = [cells[v]["lift"] for v in SIGN_VINTAGES]
_nums = [cells[v]["numerator"] for v in SIGN_VINTAGES]
_ml = r4(min(abs(x) for x in _lifts))
_mn = min(_nums)
_ml_meas = r4(min(abs(cells[v]["lift_meas"]) for v in SIGN_VINTAGES))

cross = {"found_in_explorer_output": ref is not None, "compared": 0, "mismatches": 0, "detail": []}
if ref:
    mine = {"maintained_lift": _ml, "min_numerator_161718": _mn,
            "maintained_lift_meas": _ml_meas,
            "sign": 1 if all(x > 0 for x in _lifts) else -1}
    for k, mv in mine.items():
        cross["compared"] += 1
        ev = ref.get(k)
        if ev != mv:
            cross["mismatches"] += 1
            cross["detail"].append({"key": k, "mine": mv, "explorer": ev})
    cross["explorer_entry"] = ref
cross["verdict"] = ("一致（探索側の数字は再現できる。以降の検証はこれが通ったうえでの話）"
                    if cross["mismatches"] == 0 else "**不一致＝結論を書いてはいけない**")

# 行を直接数えるスポット検算（関数に頼らないことの証明）
spot = {}
for v in SIGN_VINTAGES:
    _c = cells[v]
    _tc = None
    _ts = None
    P = pop_rows(v, CAND["population"])
    vc = sorted(r["f2_capex_r"] for r in P if r.get("f2_capex_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    _tc, _ts = q_at(vc, 0.25), q_at(vs, 0.5)
    _direct = [r for r in P
               if r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None
               and r["f2_capex_r"] <= _tc and r["f2_sga_r"] <= _ts]
    spot[str(v)] = {"n_direct": len(_direct), "n_cell": _c["n_group"],
                    "k_direct": sum(1 for r in _direct if r.get("win")), "k_cell": _c["numerator"],
                    "mismatch": 0 if (len(_direct) == _c["n_group"]
                                      and sum(1 for r in _direct if r.get("win")) == _c["numerator"]) else 1,
                    "tickers": sorted(r["ticker"] for r in _direct)}
spot["total_mismatch"] = sum(spot[str(v)]["mismatch"] for v in SIGN_VINTAGES)


# ────────────────────────────── 事前に出す（prereg の must_report_before_verdict） ──────────────────────────────
pre = {}
# 到達可能性 & 実効の線（MIN_NUM が LIFT より強く縛っていないか）
reach = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    n_g, base = c["n_group"], c["p_base"]
    k_by_lift = math.ceil((base + LIFT) * n_g - 1e-12)
    k_need = max(k_by_lift, MIN_NUM)
    reach[str(v)] = {
        "n_group": n_g, "base": base,
        "k_needed_by_lift": k_by_lift, "k_needed_by_min_num": MIN_NUM,
        "binding": ("MIN_NUM" if MIN_NUM > k_by_lift else "LIFT"),
        "effective_lift_required": r4(k_need / n_g - base) if n_g else None,
        "events_total_in_population": c["k_pop"],
        "reachable": k_need <= n_g,
    }
pre["reachability_and_effective_line"] = reach
pre["reachability_note"] = ("群が n/8 前後まで縮むので、MIN_NUM(5社) が LIFT(0.15) より強く縛る場合がある。"
                            "その場合『不合格』と書いたら誤り——0.15 を割ったのではなく5社に届かなかっただけ。")

# 検出力（登録した手続きが真の lift をどの確率で掴むか）
pw = {}
for true_lift in (0.15, 0.20, 0.30):
    per_v = {}
    for v in SIGN_VINTAGES:
        c = cells[v]
        n_g, base = c["n_group"], c["p_base"]
        p_true = min(1.0, base + true_lift)
        k_by_lift = math.ceil((base + LIFT) * n_g - 1e-12)
        k_need = max(k_by_lift, MIN_NUM)
        per_v[str(v)] = r4(binom_tail_ge(n_g, k_need, p_true))
    prod = 1.0
    for x in per_v.values():
        prod *= x
    pw[str(true_lift)] = {"single_vintage": per_v,
                          "three_independent(下限)": r4(prod),
                          "single_2018(上限)": per_v["2018"]}
pre["power"] = pw
pre["power_note"] = ("outcome のビンテージ間 Spearman は 0.845〜0.961（パネル診断）なので、"
                     "真の検出力は three_independent（完全独立の下限）と single（完全同一の上限）の間。")


# ────────────────────────────── 1. ビンテージ符号 ──────────────────────────────
g1 = {"per_vintage": {str(v): strip(cells[v]) for v in SIGN_VINTAGES}}
g1["signs_all_positive"] = all(x is not None and x > 0 for x in _lifts)
g1["maintained_lift"] = _ml
g1["maintained_lift_vs_measurable_base"] = _ml_meas
g1["min_numerator"] = _mn
g1["gate_sign_stability"] = g1["signs_all_positive"]
g1["gate_lift"] = _ml >= LIFT
g1["gate_min_numerator"] = _mn >= MIN_NUM

# 1b 群のティッカーの重なり（3ビンテージは3つの証拠か）
gsets = {v: set(r["ticker"] for r in cells[v]["_group_rows"]) for v in SIGN_VINTAGES}
inter = gsets[2016] & gsets[2017] & gsets[2018]
union = gsets[2016] | gsets[2017] | gsets[2018]


def jac(a, b):
    return r4(len(a & b) / len(a | b)) if (a | b) else None


g1["group_membership_overlap"] = {
    "n_by_vintage": {str(v): len(gsets[v]) for v in SIGN_VINTAGES},
    "n_intersection_all3": len(inter),
    "n_union": len(union),
    "intersection_tickers": sorted(inter),
    "jaccard": {"2016vs2017": jac(gsets[2016], gsets[2017]),
                "2016vs2018": jac(gsets[2016], gsets[2018]),
                "2017vs2018": jac(gsets[2017], gsets[2018])},
    "how_to_read": ("3ビンテージの群がほぼ同じ社なら『3回一致した』は3つの証拠ではなく"
                    "**同じ社を3回数えただけ**。prereg の independence_warning がまさにこれ。"),
}

# 1c outcome の窓の重なり
ret_years = {2013: 13.09, 2015: 11.10, 2016: 10.09, 2017: 9.09, 2018: 8.09}
g1["outcome_window_overlap"] = {
    "years": {str(v): ret_years[v] for v in SIGN_VINTAGES},
    "shared_tail_years": 8.09,
    "share_of_2016_window_shared_with_2018": r4(8.09 / 10.09),
    "share_of_2017_window_shared_with_2018": r4(8.09 / 9.09),
    "how_to_read": "窓は全部 2026-08 で終わる。2016 の 10.09 年のうち 8.09 年は 2018 の窓そのもの。",
}

# 1d 2013/2015 の到達可能性
g1["vintages_2013_2015"] = {}
for v in (2013, 2015):
    P = pop_rows(v, CAND["population"])
    cov = {var: sum(1 for r in P if r.get(var) is not None) for var, _ in CAND["legs"]}
    g1["vintages_2013_2015"][str(v)] = {
        "n_pop": len(P), "coverage": cov,
        "verdict": ("判定不能（f2_ 特徴量が構造的に存在しない＝『不合格』ではない）"
                    if all(c == 0 for c in cov.values()) else "測れる"),
    }
g1["out_of_sample_2013_2015"] = "判定不能"
g1["out_of_sample_note"] = ("retro_cohort_{2013,2015} は capex/売上 も 販管費/売上 も持たない"
                            "（列は sales_cagr5/opm/roic_*/fcf_conv_5y/op_all_pos/fcf_all_pos/equity_neg/score のみ）。"
                            "**代理を作って当てることはしない**——別の定義の変数で符号一致を主張したら"
                            "『基準の違う二つを割る』型そのもの。")

# 1e 延べと実体（勝者は何社か）
_win_union = {}
for v in SIGN_VINTAGES:
    for r in cells[v]["_group_rows"]:
        if r.get("win"):
            _win_union.setdefault(r["ticker"], set()).add(v)
g1["distinct_winning_companies_carrying_the_finding"] = {
    "n_events_total": sum(_nums),
    "n_distinct_companies": len(_win_union),
    "detail": sorted([{"ticker": t, "vintages": sorted(vs)} for t, vs in _win_union.items()],
                     key=lambda x: x["ticker"]),
}


# ────────────────────────────── 2. 業種調整 ──────────────────────────────
def mh(v, pop, legs, rows_src=None, win_of=None, drop_sic=None, min_stratum=3):
    """MH重み付きリスク差。探索側と同一規則（各層 n>=3 の両側が要る）。"""
    b = build_group(v, pop, legs, rows_src)
    if b is None:
        return None
    W = win_of if win_of else (lambda r: bool(r.get("win")))
    gset = set(id(r) for r in b["group"])
    st = defaultdict(lambda: [0, 0, 0, 0])
    for r in b["pop"]:
        s = r.get("sic2")
        if not s or (drop_sic is not None and s == drop_sic):
            continue
        w = 1 if W(r) else 0
        d = st[s]
        if id(r) in gset:
            d[0] += 1; d[1] += w
        else:
            d[2] += 1; d[3] += w
    nu = den = 0.0
    used = drop = 0
    covered = 0
    for s, (n1, k1, n0, k0) in st.items():
        if n1 < min_stratum or n0 < min_stratum:
            drop += 1
            continue
        covered += n1
        wgt = n1 * n0 / (n1 + n0)
        nu += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    if den == 0:
        return {"mh_risk_diff": None, "strata_used": used, "strata_dropped": drop,
                "group_covered": covered, "group_total": len(b["group"]),
                "group_coverage_share": r4(covered / len(b["group"])) if b["group"] else None}
    return {"mh_risk_diff": r4(nu / den), "strata_used": used, "strata_dropped": drop,
            "group_covered": covered, "group_total": len(b["group"]),
            "group_coverage_share": r4(covered / len(b["group"])) if b["group"] else None}


g2 = {"mh": {str(v): mh(v, CAND["population"], CAND["legs"]) for v in SIGN_VINTAGES}}
g2["gate_sector_mh"] = all(
    (m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT) for m in g2["mh"].values())


# 2a-2 間接標準化（層を1つも落とさない・群の全社を使う）
def indirect_std(v, pop, legs):
    b = build_group(v, pop, legs)
    if b is None:
        return None
    gset = set(id(r) for r in b["group"])
    bysic = defaultdict(lambda: [0, 0])
    for r in b["pop"]:
        s = r.get("sic2")
        if not s:
            continue
        bysic[s][0] += 1
        if r.get("win"):
            bysic[s][1] += 1
    obs = exp_self = exp_ext = 0.0
    used = 0
    no_sic = 0
    for r in b["group"]:
        s = r.get("sic2")
        if not s or s not in bysic:
            no_sic += 1
            continue
        n, k = bysic[s]
        w = 1 if r.get("win") else 0
        obs += w
        used += 1
        exp_self += k / n
        exp_ext += ((k - w) / (n - 1)) if n > 1 else 0.0
    if used == 0:
        return None
    return {"n_group_with_sic2": used, "n_group_without_sic2": no_sic,
            "observed_wins": int(obs),
            "expected_wins_sector": r4(exp_self),
            "expected_wins_sector_leave_self_out": r4(exp_ext),
            "risk_diff_vs_sector": r4((obs - exp_ext) / used),
            "smr": r4(obs / exp_ext) if exp_ext > 0 else None}


g2["indirect_standardization"] = {str(v): indirect_std(v, CAND["population"], CAND["legs"])
                                  for v in SIGN_VINTAGES}
g2["indirect_standardization_note"] = (
    "MHは各層 n>=3 の両側を要求するので層を落とす。間接標準化は**群の全社**を使い、"
    "各社を『同じ sic2 の他社の勝率』と比べる（自分は分母から抜く）。層を落とさない業種調整。")

# 2b 置換の土台
tick_sic = {}
for r in ANA:
    if r.get("sic2"):
        tick_sic.setdefault(r["ticker"], r["sic2"])

tickers_sign = sorted({r["ticker"] for v in SIGN_VINTAGES for r in by_v[v]})
outcome_bundle = {t: {v: None for v in SIGN_VINTAGES} for t in tickers_sign}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        outcome_bundle[r["ticker"]][v] = bool(r.get("win"))


def maintained_lift_under(winmap):
    """winmap[(ticker,vintage)]->bool のもとで (符号揃い, 最小|lift|, 最小分子) を返す。"""
    ls, ns = [], []
    for v in SIGN_VINTAGES:
        c = cells[v]
        n_pop = c["n_pop"]
        k_pop = sum(1 for r in c["_pop_rows"] if winmap.get((r["ticker"], v), False))
        n_g = c["n_group"]
        k_g = sum(1 for r in c["_group_rows"] if winmap.get((r["ticker"], v), False))
        if n_g == 0:
            return (False, 0.0, 0)
        ls.append(k_g / n_g - k_pop / n_pop)
        ns.append(k_g)
    same = all(x > 0 for x in ls) or all(x < 0 for x in ls)
    return (same, min(abs(x) for x in ls), min(ns))


rng = random.Random(SEED)


def permute(within_sector):
    if within_sector:
        buckets = defaultdict(list)
        for t in tickers_sign:
            buckets[tick_sic.get(t, "__none__")].append(t)
        mapping = {}
        for s, ts in buckets.items():
            sh = ts[:]
            rng.shuffle(sh)
            for a, b in zip(ts, sh):
                mapping[a] = b
    else:
        sh = tickers_sign[:]
        rng.shuffle(sh)
        mapping = dict(zip(tickers_sign, sh))
    wm = {}
    for t in tickers_sign:
        src = outcome_bundle[mapping[t]]
        for v in SIGN_VINTAGES:
            if src[v] is not None:
                wm[(t, v)] = src[v]
    return wm


obs_same, obs_ml, obs_mn = maintained_lift_under({(r["ticker"], v): bool(r.get("win"))
                                                  for v in SIGN_VINTAGES for r in by_v[v]})
perm_res = {}
for tag, within in (("within_sic2", True), ("unrestricted", False)):
    ge = 0
    pass_all = 0
    vals = []
    for _ in range(N_PERM):
        wm = permute(within)
        same, ml, mn = maintained_lift_under(wm)
        stat = ml if same else 0.0
        vals.append(stat)
        if stat >= obs_ml:
            ge += 1
        if same and ml >= LIFT and mn >= MIN_NUM:
            pass_all += 1
    vals.sort()
    perm_res[tag] = {
        "n_perm": N_PERM,
        "observed_statistic": r4(obs_ml),
        "p_ge_observed": r4((ge + 1) / (N_PERM + 1)),
        "null_p50": r4(vals[N_PERM // 2]),
        "null_p90": r4(vals[int(N_PERM * 0.90)]),
        "null_p95": r4(vals[int(N_PERM * 0.95)]),
        "null_p99": r4(vals[int(N_PERM * 0.99)]),
        "P_this_single_cell_passes_gates123_by_chance": r4(pass_all / N_PERM),
    }
g2["within_sector_permutation"] = perm_res["within_sic2"]


# 2c 業種を1つずつ抜く
def loo_sector():
    sics = sorted({r.get("sic2") for v in SIGN_VINTAGES for r in pop_rows(v, CAND["population"])
                   if r.get("sic2")})
    out = []
    for s in sics:
        keep = {v: [r for r in by_v[v] if r.get("sic2") != s] for v in SIGN_VINTAGES}
        cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        if any(c is None or c["n_group"] == 0 for c in cs.values()):
            out.append({"sic2_dropped": s, "verdict": "群が空＝測れない"})
            continue
        ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
        ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
        same = all(x > 0 for x in ls)
        out.append({"sic2_dropped": s,
                    "n_group_2018": cs[2018]["n_group"],
                    "maintained_lift": r4(min(abs(x) for x in ls)),
                    "min_numerator": min(ns),
                    "gates123_hold": bool(same and min(abs(x) for x in ls) >= LIFT and min(ns) >= MIN_NUM)})
    return out


_loo_sec = loo_sector()
g2["leave_one_sector_out"] = sorted(
    [x for x in _loo_sec if x.get("maintained_lift") is not None],
    key=lambda x: (x["maintained_lift"] if x["maintained_lift"] is not None else 9))[:12]
g2["leave_one_sector_out_all_hold"] = all(
    x.get("gates123_hold", False) for x in _loo_sec if "gates123_hold" in x)
g2["leave_one_sector_out_breakers"] = [x["sic2_dropped"] for x in _loo_sec
                                       if x.get("gates123_hold") is False]


# 2d 業種そのものの説明力
def sector_profile(v):
    c = cells[v]
    cnt = Counter(r.get("sic2") for r in c["_group_rows"])
    top = cnt.most_common(6)
    P = c["_pop_rows"]
    base = c["p_base"]
    out = {"n_group": c["n_group"], "sic2_top": top,
           "top3_share": r4(sum(n for _, n in top[:3]) / c["n_group"]) if c["n_group"] else None,
           "sectors": []}
    for s, n in top[:4]:
        sec = [r for r in P if r.get("sic2") == s]
        ks = sum(1 for r in sec if r.get("win"))
        gin = [r for r in c["_group_rows"] if r.get("sic2") == s]
        kg = sum(1 for r in gin if r.get("win"))
        out["sectors"].append({
            "sic2": s, "n_sector": len(sec), "p_sector": r4(rate(ks, len(sec))),
            "lift_of_sector_alone": r4(rate(ks, len(sec)) - base),
            "n_group_in_sector": len(gin), "p_group_in_sector": r4(rate(kg, len(gin))),
            "lift_of_pair_within_sector": (None if not gin else r4(rate(kg, len(gin)) - rate(ks, len(sec)))),
        })
    return out


g2["sector_profile"] = {str(v): sector_profile(v) for v in SIGN_VINTAGES}


# 2e MH を層ごとに分解する
def mh_decompose(v):
    c = cells[v]
    gset = set(id(r) for r in c["_group_rows"])
    st = defaultdict(lambda: [0, 0, 0, 0])
    for r in c["_pop_rows"]:
        s = r.get("sic2")
        if not s:
            continue
        w = 1 if r.get("win") else 0
        d = st[s]
        if id(r) in gset:
            d[0] += 1; d[1] += w
        else:
            d[2] += 1; d[3] += w
    terms, den = [], 0.0
    for s, (n1, k1, n0, k0) in st.items():
        if n1 < 3 or n0 < 3:
            continue
        wgt = n1 * n0 / (n1 + n0)
        diff = k1 / n1 - k0 / n0
        den += wgt
        terms.append({"sic2": s, "n_group": n1, "k_group": k1, "n_rest": n0,
                      "p_group": r4(k1 / n1), "p_rest": r4(k0 / n0),
                      "risk_diff": r4(diff), "mh_weight": r4(wgt), "_w": wgt, "_d": diff})
    tot = sum(t["_w"] * t["_d"] for t in terms)
    for t in terms:
        t["share_of_MH"] = r4((t["_w"] * t["_d"]) / tot) if tot else None
        del t["_w"], t["_d"]
    return {"strata_entering_MH": sorted(terms, key=lambda x: -(x["share_of_MH"] or 0)),
            "mh_total": r4(tot / den) if den else None,
            "n_strata_entering": len(terms),
            "how_to_read": "MHが『業種調整後も残る』と言うとき、その値が**どの層から来ているか**。"}


g2["mh_decomposition"] = {str(v): mh_decompose(v) for v in SIGN_VINTAGES}

# 2f MHから層を1つ外す
_ent = {v: [t["sic2"] for t in g2["mh_decomposition"][str(v)]["strata_entering_MH"]] for v in SIGN_VINTAGES}
_all_ent = sorted({s for v in SIGN_VINTAGES for s in _ent[v]})
g2["mh_excluding_each_entering_stratum"] = {
    s: {str(v): mh(v, CAND["population"], CAND["legs"], drop_sic=s) for v in SIGN_VINTAGES}
    for s in _all_ent}
g2["mh_gate_survives_excluding_each_stratum"] = {
    s: all((m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT)
           for m in g2["mh_excluding_each_entering_stratum"][s].values())
    for s in _all_ent}


# 2g MH の最小層サイズ規則への感度（事前登録の外・診断専用）
g2["mh_min_stratum_size_sensitivity"] = {
    "note": "**事前登録の外・診断専用**。探索側の規則は各層 n>=3。",
    **{f"min_n={k}": {str(v): (mh(v, CAND["population"], CAND["legs"], min_stratum=k) or {}).get("mh_risk_diff")
                      for v in SIGN_VINTAGES} for k in (2, 3, 4, 5)},
}

# 2h 群のメンバーの業種記述
_sicdesc = {}
try:
    for r in json.load(open(os.path.join(OUT, "retro_sic.json"), encoding="utf-8"))["rows"]:
        _sicdesc[r["ticker"]] = {"sic": r.get("sic"), "sicDesc": r.get("sicDesc"), "sic2": r.get("sic2")}
except Exception:
    pass
g2["group_members_with_industry"] = {
    str(v): sorted(
        [{"ticker": r["ticker"], "sic2": r.get("sic2"),
          "sicDesc": _sicdesc.get(r["ticker"], {}).get("sicDesc"),
          "capex_r": r4(r.get("f2_capex_r")), "sga_r": r4(r.get("f2_sga_r")),
          "tr_cagr": r.get("tr_cagr"), "win": bool(r.get("win"))}
         for r in cells[v]["_group_rows"]],
        key=lambda x: (x["sic2"] or "", x["ticker"]))
    for v in SIGN_VINTAGES}


# ────────────────────────────── 3. irr の影 ──────────────────────────────
def irr_control(v):
    c = cells[v]
    R = [r for r in c["_pop_rows"] if r.get("irr") is not None]
    res = {"n_with_irr": len(R)}
    if len(R) < 20:
        res["status"] = "irr の読解が薄く判定不能"
        return res
    gset = set(id(r) for r in c["_group_rows"])
    sel = [r for r in R if r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None]
    xs = [1.0 if id(r) in gset else 0.0 for r in sel]
    ys = [float(r["irr"]) for r in sel]
    rho = spearman(xs, ys) if len(xs) >= 20 else None
    res["n_measurable_with_irr"] = len(xs)
    res["n_group_within_irr_read"] = int(sum(xs))
    res["corr_group_vs_irr"] = r4(rho)
    res["orthogonal_hint"] = (None if rho is None else abs(rho) < LIFT)
    hi = [r for r in R if r["irr"] >= 70]
    res["n_irr_ge70"] = len(hi)
    if len(hi) >= 20:
        base = rate(sum(1 for r in hi if r.get("win")), len(hi))
        g = [r for r in hi if id(r) in gset]
        kg = sum(1 for r in g if r.get("win"))
        res["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g), "k": kg,
                           "p_group": r4(rate(kg, len(g))),
                           "lift": (None if not g else r4(rate(kg, len(g)) - base))}
    return res


g3 = {"per_vintage": {str(v): irr_control(v) for v in SIGN_VINTAGES}}


def orthogonality_null(v, n_draw=2000):
    c = cells[v]
    R = [r for r in c["_pop_rows"] if r.get("irr") is not None
         and r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None]
    if len(R) < 20:
        return None
    gset = set(id(r) for r in c["_group_rows"])
    k = sum(1 for r in R if id(r) in gset)
    if k == 0:
        return None
    ys = [float(r["irr"]) for r in R]
    rg = random.Random(SEED + v)
    below = 0
    obs = abs(spearman([1.0 if id(r) in gset else 0.0 for r in R], ys) or 0.0)
    for _ in range(n_draw):
        idx = set(rg.sample(range(len(R)), k))
        xs = [1.0 if i in idx else 0.0 for i in range(len(R))]
        rho = spearman(xs, ys)
        if rho is not None and abs(rho) < LIFT:
            below += 1
    return {"n_rows_with_irr_and_measurable": len(R), "n_group_in_that_set": k,
            "observed_abs_rho": r4(obs),
            "P_random_group_of_same_size_is_called_orthogonal": r4(below / n_draw),
            "how_to_read": ("同じ大きさの群を無作為に作っても『直交』と呼ばれる確率。"
                            "これが高いなら、直交ヒットは独立性の証拠ではなく**群の小ささの産物**。")}


g3["orthogonality_is_it_just_small_n"] = {str(v): orthogonality_null(v) for v in SIGN_VINTAGES}
_ic18 = g3["per_vintage"]["2018"]
g3["gate_irr_literal"] = bool(_ic18.get("orthogonal_hint") is True
                              or (_ic18.get("irr_ge70", {}).get("lift") is not None
                                  and abs(_ic18["irr_ge70"]["lift"]) >= LIFT))
_o18 = g3["orthogonality_is_it_just_small_n"].get("2018") or {}
_layer = _ic18.get("irr_ge70", {})
_layer_underpowered = (_layer.get("k") is None or _layer.get("k") < MIN_NUM)
_orth_underpowered = ((_o18.get("P_random_group_of_same_size_is_called_orthogonal") or 0) >= 0.5)
g3["gate_irr_passed_by"] = ("直交ヒント" if _ic18.get("orthogonal_hint") is True else "層内リフト")
g3["gate_irr_power_audit"] = {
    "irr>=70層": {"n_group": _layer.get("n_group"), "numerator": _layer.get("k"),
                  "prereg の分子>=5 を満たすか": (None if _layer.get("k") is None else _layer["k"] >= MIN_NUM),
                  "判定": ("検出力なし（prereg 自身が課す分子>=5 に届かない群で『差が残った』と言っている）"
                           if _layer_underpowered else "検定できる")},
    "直交ヒント": {"P_random_group_same_size_called_orthogonal":
                   _o18.get("P_random_group_of_same_size_is_called_orthogonal"),
                   "判定": ("検出力なし（同サイズの無作為群でも同じ確率で『直交』と呼ばれる）"
                            if _orth_underpowered else "検定できる")},
}
g3["gate_irr_honest"] = ("判定不能（gate5 を通した二つの試験がどちらも検出力を持たない）"
                         if (_layer_underpowered and _orth_underpowered)
                         else ("合格" if g3["gate_irr_literal"] else "不合格"))
g3["gate_irr"] = g3["gate_irr_literal"]


# ────────────────────────────── 4. 1社の影響 ──────────────────────────────
def loo_ticker():
    cand_tickers = sorted(union)
    res = []
    for t in cand_tickers:
        keep = {v: [r for r in by_v[v] if r["ticker"] != t] for v in SIGN_VINTAGES}
        cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        if any(c is None or c["n_group"] == 0 for c in cs.values()):
            res.append({"ticker": t, "verdict": "測れない"})
            continue
        ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
        ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
        m = {str(v): mh(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        gsec = all((x and x["mh_risk_diff"] is not None and abs(x["mh_risk_diff"]) >= LIFT) for x in m.values())
        same = all(x > 0 for x in ls)
        ml = min(abs(x) for x in ls)
        mn = min(ns)
        res.append({"ticker": t, "maintained_lift": r4(ml), "min_numerator": mn,
                    "delta_vs_full": r4(ml - g1["maintained_lift"]),
                    "mh_by_vintage": {k: (x or {}).get("mh_risk_diff") for k, x in m.items()},
                    "gate_lift": ml >= LIFT, "gate_min_num": mn >= MIN_NUM,
                    "gate_sign": same, "gate_sector": gsec,
                    "gates_1_to_3_hold": bool(same and ml >= LIFT and mn >= MIN_NUM),
                    "all_gates_1_to_4_hold": bool(same and ml >= LIFT and mn >= MIN_NUM and gsec)})
    return res


loo = loo_ticker()
meas = [x for x in loo if "maintained_lift" in x]
g4 = {
    "n_tickers_tested": len(loo),
    "worst_maintained_lift": r4(min(x["maintained_lift"] for x in meas)) if meas else None,
    "best_maintained_lift": r4(max(x["maintained_lift"] for x in meas)) if meas else None,
    "max_abs_delta_from_one_company": r4(max(abs(x["delta_vs_full"]) for x in meas)) if meas else None,
    "n_breaking_gates_1_to_3": sum(1 for x in meas if not x["gates_1_to_3_hold"]),
    "breakers_gates_1_to_3": [x for x in meas if not x["gates_1_to_3_hold"]],
    "top10_most_influential": sorted(meas, key=lambda x: x["maintained_lift"])[:10],
    "how_to_read": ("1社をパネルごと抜いて閾値・母集団・群・条件を全部作り直す。"
                    "1社で条件が崩れるなら、それは発見ではなく1社の話。"
                    "**この候補は gate4(業種) が元から落ちているので、"
                    "『1社抜きで業種条件が崩れるか』は測っても意味が無い**——"
                    "崩れる前から崩れている。だから gates_1_to_3 で見る。"),
}


def sequential_drop():
    out = []
    for v in SIGN_VINTAGES:
        c = cells[v]
        n_g, k_g, base = c["n_group"], c["numerator"], c["p_base"]
        need = None
        for d in range(0, k_g + 1):
            k, n = k_g - d, n_g - d
            if n == 0:
                need = d
                break
            lf = k / n - base
            if lf < LIFT or k < MIN_NUM:
                need = d
                break
        out.append({"vintage": v, "n_group": n_g, "numerator": k_g,
                    "n_winners_to_remove_to_break": need,
                    "which_gate_breaks_first": (
                        "min_numerator" if (need is not None and k_g - need < MIN_NUM
                                            and (n_g - need) > 0
                                            and (k_g - need) / (n_g - need) - base >= LIFT) else "lift")})
    return out


g4["sequential_winner_removal"] = sequential_drop()


# ────────────────────────────── 5. 置換 ──────────────────────────────
_fpr = pair_out["must_report_before_verdict"]["false_positive_rate"]
_nullmax = _fpr["null_distribution_of_max_statistic"]
g5 = {
    "unrestricted_ticker_bundle": perm_res["unrestricted"],
    "within_sic2": perm_res["within_sic2"],
    "family_wise_from_explorer": {
        "n_tests_in_search": _fpr["n_tests_in_procedure"],
        "P_at_least_one_pass_under_null_L3": _fpr["P_at_least_one_pass_by_level"]["L3"],
        "P_at_least_one_pass_under_null_L4": _fpr["P_at_least_one_pass_by_level"]["L4"],
        "P_at_least_one_pass_under_null_L5": _fpr["P_at_least_one_pass_by_level"]["L5"],
        "null_max_statistic_p95": _nullmax["p95"],
        "null_max_statistic_p99": _nullmax["p99"],
        "note": ("探索側が同じ帰無で測った値札。**単体のp値は『この1本だけを検定したなら』の話**で、"
                 "実際は2840本から選ばれている。"),
    },
}
g5["observed_vs_null_max_distribution"] = {
    "observed_maintained_lift": g1["maintained_lift"],
    "null_max_p50": _nullmax["p50"], "null_max_p90": _nullmax["p90"],
    "null_max_p95": _nullmax["p95"], "null_max_p99": _nullmax["p99"],
    "position": ("p99 以上" if g1["maintained_lift"] >= _nullmax["p99"] else
                 "p95 と p99 の間" if g1["maintained_lift"] >= _nullmax["p95"] else
                 "p90 と p95 の間" if g1["maintained_lift"] >= _nullmax["p90"] else "p90 未満"),
}


# ────────────────────────────── 6. 既存の関門との重複 ──────────────────────────────
def gate_flags(r):
    """門が既に持つ関門の歴史側の相当物。**nde はパネルに無いので intcov を代理に使う（正直に代理と書く）**。"""
    shrink = (r.get("f2_cagr5") is not None and r.get("f2_opmD5") is not None
              and r["f2_cagr5"] < 0 and r["f2_opmD5"] < 0)
    ic = r.get("f2_intcov")
    fin_bad = (ic is not None and ic < 5)
    return {"shrink": shrink, "fin_bad": fin_bad, "quality": bool(r.get("P_quality"))}


def survivors_analysis(v):
    c = cells[v]
    P = c["_pop_rows"]
    gset = set(id(r) for r in c["_group_rows"])
    out = {}
    defs = {
        "no_shrink": lambda r: not gate_flags(r)["shrink"],
        "intcov_ok": lambda r: not gate_flags(r)["fin_bad"],
        "both": lambda r: (not gate_flags(r)["shrink"]) and (not gate_flags(r)["fin_bad"]),
    }
    for tag, f in defs.items():
        sub = [r for r in P if f(r)]
        g = [r for r in sub if id(r) in gset]
        b = rate(sum(1 for r in sub if r.get("win")), len(sub))
        kg = sum(1 for r in g if r.get("win"))
        out[tag] = {"n_survivors": len(sub), "p_survivors": r4(b),
                    "n_group_among_survivors": len(g), "k": kg,
                    "p_group": r4(rate(kg, len(g))),
                    "incremental_lift": (None if not g else r4(rate(kg, len(g)) - b))}
    ex = [r for r in c["_group_rows"] if gate_flags(r)["shrink"] or gate_flags(r)["fin_bad"]]
    out["group_members_already_excluded_by_gates"] = {
        "n": len(ex), "tickers": sorted(r["ticker"] for r in ex), "n_group": c["n_group"]}
    return out


g6 = {"survivors": {str(v): survivors_analysis(v) for v in SIGN_VINTAGES}}
g6["population_note"] = ("この候補の母集団は既に P_quality（質実証）＝門の関門の一つを通った集合。"
                         "したがって増分として残るのは『事業の収縮なし』と『利払カバー』の2つ。")
g6["proxy_warning"] = ("財務キルは nde>4 だが nde はパネルに無い。**intcov<5 は代理であって同じ線ではない**。"
                       "intcov が null の社は『利息がない＝負担なし』として落とさない（欠測を不合格と読まない）。")


def leg_alone(var, cut):
    res = {}
    for v in SIGN_VINTAGES:
        c = cell(v, CAND["population"], [(var, cut)])
        res[str(v)] = strip(c)
    ls = [res[str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [res[str(v)]["numerator"] for v in SIGN_VINTAGES]
    same = all(x is not None and x > 0 for x in ls)
    return {"by_vintage": res,
            "maintained_lift": (r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None),
            "min_numerator": min(ns), "sign_stable": same}


g6["legs_alone"] = {f"{var}[{cut}]": leg_alone(var, cut) for var, cut in CAND["legs"]}
_best_leg = max((x["maintained_lift"] or 0) for x in g6["legs_alone"].values())
g6["best_leg_maintained_lift"] = r4(_best_leg)
g6["increment_over_best_leg"] = r4(g1["maintained_lift"] - _best_leg)

_inc = {v: g6["survivors"][str(v)]["both"] for v in SIGN_VINTAGES}
_incl = [_inc[v]["incremental_lift"] for v in SIGN_VINTAGES]
_incn = [_inc[v]["k"] for v in SIGN_VINTAGES]
g6["prereg_line_applied_to_the_increment"] = {
    "by_vintage": {str(v): {"n_group": _inc[v]["n_group_among_survivors"], "numerator": _inc[v]["k"],
                            "incremental_lift": _inc[v]["incremental_lift"]} for v in SIGN_VINTAGES},
    "maintained_incremental_lift": (r4(min(abs(x) for x in _incl)) if all(x is not None for x in _incl) else None),
    "min_numerator": min(_incn),
    "gate_lift_holds": bool(all(x is not None and abs(x) >= LIFT for x in _incl)),
    "gate_min_numerator_holds": bool(min(_incn) >= MIN_NUM),
    "how_to_read": ("勝者側の候補が実務で使われるのは『既存の関門を通った社の中で選ぶ』とき。"
                    "そこで prereg の線（0.15・分子5）をそのまま当てる。"),
}


# ────────────────────────────── X1 交互作用（組にする意味があるか） ──────────────────────────────
def two_by_two(v):
    P = pop_rows(v, CAND["population"])
    vc = sorted(r["f2_capex_r"] for r in P if r.get("f2_capex_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    tc, ts = q_at(vc, 0.25), q_at(vs, 0.5)
    M = [r for r in P if r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None]
    cellsx = {}
    for ca in (True, False):
        for sa in (True, False):
            sub = [r for r in M if (r["f2_capex_r"] <= tc) == ca and (r["f2_sga_r"] <= ts) == sa]
            k = sum(1 for r in sub if r.get("win"))
            cellsx[f"capex{'低' if ca else '高'}_sga{'低' if sa else '高'}"] = {
                "n": len(sub), "k": k, "p": r4(rate(k, len(sub)))}
    a = cellsx["capex低_sga低"]["p"]
    b = cellsx["capex低_sga高"]["p"]
    c_ = cellsx["capex高_sga低"]["p"]
    d = cellsx["capex高_sga高"]["p"]
    return {"cells": cellsx,
            "sga効果_capex低の中": (None if (a is None or b is None) else r4(a - b)),
            "sga効果_capex高の中": (None if (c_ is None or d is None) else r4(c_ - d)),
            "capex効果_sga低の中": (None if (a is None or c_ is None) else r4(a - c_)),
            "capex効果_sga高の中": (None if (b is None or d is None) else r4(b - d)),
            "交互作用(差の差)": (None if any(x is None for x in (a, b, c_, d)) else r4((a - b) - (c_ - d)))}


X1 = {str(v): two_by_two(v) for v in SIGN_VINTAGES}
X1["how_to_read"] = ("差の差が0に近ければ、積の効果は2本の脚の足し算で説明でき**組にする意味は薄い**。"
                     "『組が効いた』のか『片方が効いていて、もう片方が偶然を絞り込んだ』のかを分ける。")


# ────────────────────────────── X2 capex_r=0 問題（ルール7） ──────────────────────────────
X2 = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    vc = [r["f2_capex_r"] for r in P if r.get("f2_capex_r") is not None]
    vcs = sorted(vc)
    tc = q_at(vcs, 0.25)
    grp = cells[v]["_group_rows"]
    X2[str(v)] = {
        "n_pop": len(P),
        "capex_r_coverage": r4(len(vc) / len(P)),
        "n_null_capex_r": len(P) - len(vc),
        "share_exactly_zero_in_pop": r4(sum(1 for x in vc if x == 0.0) / len(vc)) if vc else None,
        "n_exactly_zero_in_group": sum(1 for r in grp if r.get("f2_capex_r") == 0.0),
        "threshold_q25": r4(tc),
        "group_capex_r_min": r4(min((r["f2_capex_r"] for r in grp), default=None)),
        "group_capex_r_median": r4(sorted(r["f2_capex_r"] for r in grp)[len(grp) // 2]) if grp else None,
        "quantiles_pop": {"q05": r4(q_at(vcs, .05)), "q10": r4(q_at(vcs, .10)),
                          "q25": r4(q_at(vcs, .25)), "q50": r4(q_at(vcs, .50)),
                          "q75": r4(q_at(vcs, .75))},
    }
X2["how_to_read"] = ("設備投資比の下位1/4が『資産が軽い』なのか『capexタグが無くて0と読まれた』なのかを分ける。"
                     "0がごく少数なら前者。**欠測(null)は群にも母集団の可測集合にも入らない**ので、"
                     "0の実数が要点。")
X2["sga_r_shape"] = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    grp = cells[v]["_group_rows"]
    X2["sga_r_shape"][str(v)] = {
        "coverage": r4(len(vs) / len(P)),
        "share_exactly_zero_in_pop": r4(sum(1 for x in vs if x == 0.0) / len(vs)) if vs else None,
        "n_exactly_zero_in_group": sum(1 for r in grp if r.get("f2_sga_r") == 0.0),
        "quantiles_pop": {"q25": r4(q_at(vs, .25)), "q50": r4(q_at(vs, .50)), "q75": r4(q_at(vs, .75))},
    }
# 可測性そのものが勝敗と相関していないか（欠測の非ランダム性）
X2["measurability_vs_outcome"] = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    m = [r for r in P if r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None]
    nm = [r for r in P if not (r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None)]
    X2["measurability_vs_outcome"][str(v)] = {
        "n_measurable": len(m), "p_win_measurable": r4(rate(sum(1 for r in m if r.get("win")), len(m))),
        "n_not_measurable": len(nm),
        "p_win_not_measurable": r4(rate(sum(1 for r in nm if r.get("win")), len(nm))),
        "gap": (None if not nm or not m else
                r4(rate(sum(1 for r in m if r.get("win")), len(m))
                   - rate(sum(1 for r in nm if r.get("win")), len(nm)))),
    }
X2["measurability_note"] = ("可測集合と非可測集合で勝率が違うなら、lift の一部は"
                            "**『測れる会社かどうか』**という別の変数を測っている。"
                            "だから探索側も lift_vs_measurable_both を併記している。")


# ────────────────────────────── X3 業態の混入 ──────────────────────────────
def sic_bucket(s):
    if not s:
        return "不明"
    try:
        n = int(s)
    except Exception:
        return "不明"
    if 60 <= n <= 67:
        return "金融・保険・不動産"
    if 70 <= n <= 89:
        return "サービス"
    if 20 <= n <= 39:
        return "製造"
    if 40 <= n <= 49:
        return "運輸・公益"
    if 50 <= n <= 59:
        return "卸小売"
    if 1 <= n <= 14:
        return "農林・鉱業"
    if 15 <= n <= 17:
        return "建設"
    return "その他"


X3 = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    gb = Counter(sic_bucket(r.get("sic2")) for r in c["_group_rows"])
    pb = Counter(sic_bucket(r.get("sic2")) for r in c["_pop_rows"])
    X3[str(v)] = {
        "group_buckets": dict(gb), "pop_buckets": dict(pb),
        "group_share": {k: r4(n / c["n_group"]) for k, n in gb.items()},
        "pop_share": {k: r4(n / c["n_pop"]) for k, n in pb.items()},
        "non_manufacturing_share_in_group": r4(sum(n for k, n in gb.items() if k != "製造") / c["n_group"]),
        "non_manufacturing_share_in_pop": r4(sum(n for k, n in pb.items() if k != "製造") / c["n_pop"]),
    }
X3["how_to_read"] = ("capex/売上 と SG&A/売上 は業態で意味が違う（保険・REIT・持株会社は"
                     "そもそも設備を持たず費用の載る場所も違う）。群が特定の業態に偏っているなら、"
                     "この2本は事業の経済性ではなく**損益計算書の形**を測っている疑いがある。")
X3["financial_members"] = {
    str(v): sorted([{"ticker": r["ticker"], "sic2": r.get("sic2"),
                     "sicDesc": _sicdesc.get(r["ticker"], {}).get("sicDesc"),
                     "win": bool(r.get("win"))}
                    for r in cells[v]["_group_rows"] if sic_bucket(r.get("sic2")) == "金融・保険・不動産"],
                   key=lambda x: x["ticker"])
    for v in SIGN_VINTAGES}


# ────────────────────────────── X4 母集団の依存（P_full でも出るか） ──────────────────────────────
X4 = {"P_full": {}}
_cf = {v: cell(v, "P_full", CAND["legs"]) for v in SIGN_VINTAGES}
X4["P_full"]["per_vintage"] = {str(v): strip(_cf[v]) for v in SIGN_VINTAGES}
_lf = [_cf[v]["lift"] for v in SIGN_VINTAGES]
_nf = [_cf[v]["numerator"] for v in SIGN_VINTAGES]
X4["P_full"]["maintained_lift"] = r4(min(abs(x) for x in _lf))
X4["P_full"]["min_numerator"] = min(_nf)
X4["P_full"]["sign_stable"] = all(x > 0 for x in _lf)
X4["P_full"]["mh"] = {str(v): mh(v, "P_full", CAND["legs"]) for v in SIGN_VINTAGES}
X4["how_to_read"] = ("同じ2本を P_full（質実証を課さない全上場）に当てる。"
                     "P_quality でしか出ないなら、効いているのは2本ではなく"
                     "**質実証との交互作用**かもしれない。逆に P_full でも同じ向きなら、"
                     "少なくとも母集団の定義に依存した見せかけではない。")


# ────────────────────────────── X5 irr=85 / 半導体連鎖 を群から抜く ──────────────────────────────
# gate3 の形式的な試験（相関・層内リフト）は 2018 の12社でしか当てられず検出力が無い。
# **名指しで抜いて作り直す**ほうが強い反証になる（CLAUDE.md が irr85 の追試で使った作法）。
def drop_set_and_rebuild(drop_tickers, tag):
    keep = {v: [r for r in by_v[v] if r["ticker"] not in drop_tickers] for v in SIGN_VINTAGES}
    cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
    if any(c is None or c["n_group"] == 0 for c in cs.values()):
        return {"tag": tag, "verdict": "群が空＝測れない"}
    ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
    ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
    same = all(x > 0 for x in ls)
    ml = min(abs(x) for x in ls)
    return {"tag": tag, "n_dropped_from_panel": len(drop_tickers),
            "dropped": sorted(drop_tickers),
            "per_vintage": {str(v): strip(cs[v]) for v in SIGN_VINTAGES},
            "maintained_lift": r4(ml), "min_numerator": min(ns), "sign_stable": same,
            "gates123_hold": bool(same and ml >= LIFT and min(ns) >= MIN_NUM),
            "delta_vs_full": r4(ml - g1["maintained_lift"])}


# 群に現れた社のうち、2018 で irr が読まれている社の刻み
_irr_in_group = {}
for v in SIGN_VINTAGES:
    for r in cells[v]["_group_rows"]:
        if r.get("irr") is not None:
            _irr_in_group.setdefault(r["ticker"], {})[str(v)] = {"irr": r["irr"], "win": bool(r.get("win"))}
IRR85 = sorted({t for t, d_ in _irr_in_group.items() if any(x["irr"] >= 85 for x in d_.values())})
# 半導体連鎖（実体で選ぶ。sicDesc を根拠に列挙し、境界例は別に測る）
SEMI_CORE = ["AEIS", "MKSI", "LRCX", "MCHP", "STM"]      # 半導体製造装置・部材・デバイス
SEMI_EDGE = ["GLW"]                                       # 光学・ディスプレイ材料（境界例）
X5 = {
    "irr_coverage_in_group": {
        str(v): {"n_group": cells[v]["n_group"],
                 "n_with_irr": sum(1 for r in cells[v]["_group_rows"] if r.get("irr") is not None),
                 "share": r4(sum(1 for r in cells[v]["_group_rows"] if r.get("irr") is not None)
                             / cells[v]["n_group"])}
        for v in SIGN_VINTAGES},
    "irr_read_only_for_2018": ("retro_moat は 2013/2015/2018 しか無い。**2016/2017 は群の irr が全社 null**"
                               "＝gate5 は3ビンテージのうち1つ、しかも群の約半分でしか当てられない。"),
    "group_members_with_irr": {t: d_ for t, d_ in sorted(_irr_in_group.items())},
    "irr85_members": IRR85,
    "win_rate_by_irr_2018": None,
    "drop_irr85": drop_set_and_rebuild(set(IRR85), "irr=85 の社をパネルごと除外"),
    "drop_semi_core": drop_set_and_rebuild(set(SEMI_CORE), "半導体連鎖（中核）をパネルごと除外"),
    "drop_semi_core_plus_edge": drop_set_and_rebuild(set(SEMI_CORE + SEMI_EDGE),
                                                     "半導体連鎖（中核＋境界GLW）をパネルごと除外"),
    "drop_irr85_and_semi": drop_set_and_rebuild(set(IRR85) | set(SEMI_CORE),
                                                "irr=85 ∪ 半導体連鎖 をパネルごと除外"),
    "how_to_read": ("形式的な gate5 は検出力が無いので、**名指しで抜いて全部作り直す**。"
                    "抜いて条件が崩れるなら、この候補は irr=85／半導体連鎖の言い換えでしかない。"),
}
_g18 = cells[2018]["_group_rows"]
_by85 = [r for r in _g18 if r.get("irr") is not None and r["irr"] >= 85]
_bylo = [r for r in _g18 if r.get("irr") is not None and r["irr"] < 85]
X5["win_rate_by_irr_2018"] = {
    "irr>=85": {"n": len(_by85), "k": sum(1 for r in _by85 if r.get("win")),
                "p": r4(rate(sum(1 for r in _by85 if r.get("win")), len(_by85)))},
    "irr<85(読解あり)": {"n": len(_bylo), "k": sum(1 for r in _bylo if r.get("win")),
                          "p": r4(rate(sum(1 for r in _bylo if r.get("win")), len(_bylo)))},
    "irr未読解": {"n": cells[2018]["n_group"] - len(_by85) - len(_bylo),
                  "k": sum(1 for r in _g18 if r.get("irr") is None and r.get("win"))},
    "base_P_quality_2018": cells[2018]["p_base"],
}

# 群の実体（延べと社数）と、勝者の顔ぶれ
X5["distinct_group_companies"] = {
    "n_cells_total": sum(cells[v]["n_group"] for v in SIGN_VINTAGES),
    "n_distinct_companies": len(union),
    "n_distinct_winners": len(_win_union),
    "companies_in_all_3_vintages": sorted(inter),
    "winners_in_all_3_vintages": sorted([t for t, vs in _win_union.items() if len(vs) == 3]),
}


# ────────────────────────────── X6 業種調整の別の当て方・単ビンテージの有意性 ──────────────────────────────
# MH は各層 n>=3 を要求するため群の 17-43% しか見ない。**同じ「業種を揃える」を、層を粗くして当てる**。
# 粗い層（製造/非製造など）なら群のほぼ全社が残る＝MH の弱点を持たない。
X6 = {"bucket_level_sector_control": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    gset = set(id(r) for r in c["_group_rows"])
    res = {}
    for bk in sorted({sic_bucket(r.get("sic2")) for r in c["_pop_rows"]}):
        sub = [r for r in c["_pop_rows"] if sic_bucket(r.get("sic2")) == bk]
        g = [r for r in sub if id(r) in gset]
        if not g:
            continue
        b = rate(sum(1 for r in sub if r.get("win")), len(sub))
        kg = sum(1 for r in g if r.get("win"))
        k_rest = sum(1 for r in sub if r.get("win")) - kg
        res[bk] = {"n_bucket": len(sub), "p_bucket": r4(b), "n_group": len(g), "k": kg,
                   "n_rest": len(sub) - len(g), "k_rest": k_rest,
                   "p_rest": r4(rate(k_rest, len(sub) - len(g))),
                   "p_group": r4(rate(kg, len(g))), "lift_within_bucket": r4(rate(kg, len(g)) - b)}
    # バケット重み付き（MHと同じ重み式・ただし層が粗いので落ちない）。**実数から直接数える**
    nu = den = 0.0
    cov = 0
    for bk, x in res.items():
        n1, n0 = x["n_group"], x["n_rest"]
        if n1 < 1 or n0 < 1:
            continue
        wgt = n1 * n0 / (n1 + n0)
        nu += wgt * (x["k"] / n1 - x["k_rest"] / n0)
        den += wgt
        cov += n1
    X6["bucket_level_sector_control"][str(v)] = {
        "by_bucket": res,
        "weighted_risk_diff": r4(nu / den) if den else None,
        "group_covered": cov, "group_total": c["n_group"],
        "group_coverage_share": r4(cov / c["n_group"]) if c["n_group"] else None,
    }
X6["bucket_note"] = ("prereg は業種調整の道具に MH を名指ししている。MH は各層 n>=3 を要求するので"
                     "**群の 17-43% しか見ない**（実測）。ここでは同じ考え方を粗い層（製造/サービス/金融…）で当て、"
                     "群のほぼ全社を残したまま業種を揃える。**どちらが正しいかを決めるのは私ではない**——"
                     "二つが違うことを言っている、という事実を出す。")

# 単ビンテージの有意性（3ビンテージは独立でないので、1本だけ取り出したときの p）
X6["single_vintage_binomial"] = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    X6["single_vintage_binomial"][str(v)] = {
        "n_group": c["n_group"], "k": c["numerator"], "base": c["p_base"],
        "p_one_sided": r4(binom_tail_ge(c["n_group"], c["numerator"], c["p_base"])),
        "note": "母集団の勝率を真として、群でこれ以上の勝者が出る確率（1本だけを検定したなら）",
    }
X6["single_vintage_note"] = ("outcome のビンテージ間 Spearman は 0.845〜0.961・群の 58セルは実体30社なので、"
                             "**3ビンテージを3つの独立な検定として掛け算してはいけない**。"
                             "最も情報が多い1本（群が最大の2018）を単独で見るのが下限の読み方。")

# ─────────────── 補助R（事前登録の外・診断専用）: レジーム分割 ───────────────
regime = {"status": "未実施（out/retro_monthly_2018_2026.json が無い）"}
MON = os.path.join(OUT, "retro_monthly_2018_2026.json")
if os.path.exists(MON):
    mon = json.load(open(MON, encoding="utf-8"))
    SPLIT = 1656648000  # 2022-07-01

    def sub_cagr(series, t_from, t_to):
        if not series or len(series) < 4:
            return None

        def nearest(t):
            return min(series, key=lambda p: abs(p[0] - t))

        a, b = nearest(t_from), nearest(t_to)
        if a[1] is None or b[1] is None or a[1] <= 0 or b[1] <= 0 or b[0] <= a[0]:
            return None
        yrs = (b[0] - a[0]) / (365.25 * 24 * 3600)
        if yrs < 1.0:
            return None
        return (b[1] / a[1]) ** (1 / yrs) - 1

    t_start = min(min(p[0] for p in s) for s in mon.values() if s)
    t_end = max(max(p[0] for p in s) for s in mon.values() if s)
    regime = {"note": "**事前登録の外・診断専用**。合否には数えない。",
              "split_at": "2022-07-01",
              "windows": {"A": "2018-07 → 2022-07", "B": "2022-07 → 2026-08"},
              "per_vintage": {}}
    c18 = cells[2018]
    gset18 = set(r["ticker"] for r in c18["_group_rows"])
    for tag, (tf, tt) in (("A_2018_2022", (t_start, SPLIT)), ("B_2022_2026", (SPLIT, t_end))):
        pop_v, grp_v = [], []
        for r in c18["_pop_rows"]:
            s = mon.get(r["ticker"])
            g = sub_cagr(s, tf, tt) if s else None
            if g is None:
                continue
            pop_v.append((r["ticker"], g))
            if r["ticker"] in gset18:
                grp_v.append((r["ticker"], g))
        b = rate(sum(1 for _, g in pop_v if g >= 0.15), len(pop_v))
        kg = sum(1 for _, g in grp_v if g >= 0.15)
        regime["per_vintage"][tag] = {
            "n_pop_measurable": len(pop_v), "p_base": r4(b),
            "n_group": len(grp_v), "k_group": kg,
            "p_group": r4(rate(kg, len(grp_v))),
            "lift": (None if not grp_v else r4(rate(kg, len(grp_v)) - b)),
            "median_cagr_group": r4(sorted(g for _, g in grp_v)[len(grp_v) // 2]) if grp_v else None,
            "median_cagr_pop": r4(sorted(g for _, g in pop_v)[len(pop_v) // 2]) if pop_v else None,
        }
    # 2016/2017 の群でも同じ2窓を測る（メンバーが違うので独立な確認になる）
    regime["other_vintage_groups"] = {}
    for vv in (2016, 2017):
        cvv = cells[vv]
        gs = set(r["ticker"] for r in cvv["_group_rows"])
        blk = {}
        for tag, (tf, tt) in (("A_2018_2022", (t_start, SPLIT)), ("B_2022_2026", (SPLIT, t_end))):
            pv, gv = [], []
            for r in cvv["_pop_rows"]:
                s = mon.get(r["ticker"])
                g = sub_cagr(s, tf, tt) if s else None
                if g is None:
                    continue
                pv.append(g)
                if r["ticker"] in gs:
                    gv.append(g)
            b = rate(sum(1 for g in pv if g >= 0.15), len(pv))
            kg = sum(1 for g in gv if g >= 0.15)
            blk[tag] = {"n_pop_measurable": len(pv), "p_base": r4(b), "n_group": len(gv), "k_group": kg,
                        "p_group": r4(rate(kg, len(gv))),
                        "lift": (None if not gv else r4(rate(kg, len(gv)) - b))}
        regime["other_vintage_groups"][str(vv)] = blk
    # 窓Bで勝った群のメンバー（何が後半を作っているか）
    cB = []
    for r in c18["_pop_rows"]:
        if r["ticker"] not in gset18:
            continue
        s = mon.get(r["ticker"])
        g = sub_cagr(s, SPLIT, t_end) if s else None
        ga = sub_cagr(s, t_start, SPLIT) if s else None
        cB.append({"ticker": r["ticker"], "sic2": r.get("sic2"),
                   "cagr_A_2018_2022": r4(ga), "cagr_B_2022_2026": r4(g),
                   "win_A": (None if ga is None else ga >= 0.15),
                   "win_B": (None if g is None else g >= 0.15)})
    regime["group_2018_members_by_regime"] = sorted(cB, key=lambda x: -(x["cagr_B_2022_2026"] or -9))
    regime["how_to_read"] = ("2018年群の8年を前半4年と後半4年に割る。前半でリフトが消え後半だけに出るなら、"
                             "それは指標ではなく相場の記録。**2016/2017 の群でも同じ2窓を当てる**"
                             "（メンバーが違うので独立な確認になる）。")

# ─────────────── 補助S（事前登録の外・診断専用）: 重ならない部分窓 ───────────────
sub = {"note": "**事前登録の外・診断専用**。同じ終端日ゆえ tr_total の比で部分窓が厳密に出る。"}
try:
    R = {}
    for tag, f in (("2016", "retro_returns_2016"), ("2017", "retro_returns_2017"),
                   ("2018", "retro_returns_2018")):
        d = json.load(open(os.path.join(OUT, f + ".json"), encoding="utf-8"))
        R[tag] = {r["ticker"]: r for r in d["rows"] if r.get("tr_total") is not None}

    def win_sub(t, a, b, yrs):
        ra, rb = R[a].get(t), R[b].get(t)
        if not ra or not rb or rb["tr_total"] <= 0:
            return None
        m = ra["tr_total"] / rb["tr_total"]
        if m <= 0:
            return None
        return m ** (1 / yrs) - 1

    for vint, (a, b, yrs, name) in {
        2016: ("2016", "2018", 2.0, "2016-07 → 2018-07 (2.0年・2018窓と重ならない部分)"),
        2017: ("2017", "2018", 1.0, "2017-07 → 2018-07 (1.0年・同上)"),
    }.items():
        c = cells[vint]
        gs = set(r["ticker"] for r in c["_group_rows"])
        pv = [(r["ticker"], win_sub(r["ticker"], a, b, yrs)) for r in c["_pop_rows"]]
        pv = [(t, g) for t, g in pv if g is not None]
        gv = [(t, g) for t, g in pv if t in gs]
        bs = rate(sum(1 for _, g in pv if g >= 0.15), len(pv))
        kg = sum(1 for _, g in gv if g >= 0.15)
        sub[str(vint)] = {
            "window": name, "n_pop": len(pv), "p_base": r4(bs),
            "n_group": len(gv), "k": kg, "p_group": r4(rate(kg, len(gv))),
            "lift_in_disjoint_subwindow": (None if not gv else r4(rate(kg, len(gv)) - bs)),
            "caveat": "短い窓を年率で裁くので雑音が大きい。方向を見るだけの補助。",
        }
except Exception as e:  # noqa
    sub["error"] = str(e)

# ─────────────── 補助T（事前登録の外・診断専用）: 閾値感度 ───────────────
thr_sens = {"note": "**事前登録の外・診断専用**。prereg は『中央値または上下1/4』しか許していない。"}


def cut_at(v, qc, qs):
    P = pop_rows(v, CAND["population"])
    vc = sorted(r["f2_capex_r"] for r in P if r.get("f2_capex_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    tc, ts = q_at(vc, qc), q_at(vs, qs)
    g = [r for r in P if r.get("f2_capex_r") is not None and r.get("f2_sga_r") is not None
         and r["f2_capex_r"] <= tc and r["f2_sga_r"] <= ts]
    n_pop, k_pop = len(P), sum(1 for r in P if r.get("win"))
    kg = sum(1 for r in g if r.get("win"))
    return {"thr_capex": r4(tc), "thr_sga": r4(ts), "n_group": len(g), "k": kg,
            "lift": (None if not g else r4(kg / len(g) - k_pop / n_pop))}


for qc, qs in ((0.20, 0.50), (0.25, 0.50), (0.30, 0.50), (0.25, 0.40), (0.25, 0.60),
               (0.20, 0.40), (0.30, 0.60), (0.25, 0.25)):
    key = f"capex_bottom{int(qc*100)}%_sga_bottom{int(qs*100)}%"
    thr_sens[key] = {str(v): cut_at(v, qc, qs) for v in SIGN_VINTAGES}
    ls = [thr_sens[key][str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [thr_sens[key][str(v)]["k"] for v in SIGN_VINTAGES]
    thr_sens[key]["maintained_lift"] = (r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None)
    thr_sens[key]["min_numerator"] = min(ns)
    thr_sens[key]["gates123_hold"] = bool(
        all(x is not None and x > 0 for x in ls) and all(abs(x) >= LIFT for x in ls) and min(ns) >= MIN_NUM)


# ────────────────────────────── 判定（prereg の5条件・一つも緩めない） ──────────────────────────────
gates = {
    "1_lift>=0.15_3vintages": g1["gate_lift"],
    "2_min_numerator>=5": g1["gate_min_numerator"],
    "3_sign_stability": g1["gate_sign_stability"],
    "4_sector_MH>=0.15": g2["gate_sector_mh"],
    "5_not_irr_shadow": g3["gate_irr"],
}
survived_prereg = all(gates.values())

six = {}
six["1_vintage_sign"] = {
    "落とせたか": ("落とせなかった（符号は3ビンテージとも正）" if g1["gate_sign_stability"]
                   else "**落とせた**（符号が反転する）"),
    "ただし": (f"群の和集合は {g1['group_membership_overlap']['n_union']} 社・"
               f"3ビンテージ共通が {g1['group_membership_overlap']['n_intersection_all3']} 社"
               f"（jaccard {g1['group_membership_overlap']['jaccard']}）。"
               f"窓は同じ終端日で 2016 の {g1['outcome_window_overlap']['share_of_2016_window_shared_with_2018']}・"
               f"2017 の {g1['outcome_window_overlap']['share_of_2017_window_shared_with_2018']} が 2018 と共通"
               "＝**3つの証拠ではなく同じ社の同じ8年を3回数えている**。"
               f"勝者は延べ {g1['distinct_winning_companies_carrying_the_finding']['n_events_total']} 件だが"
               f"実体は {g1['distinct_winning_companies_carrying_the_finding']['n_distinct_companies']} 社。"),
    "2013/2015": g1["out_of_sample_2013_2015"] + "（" + g1["out_of_sample_note"] + "）",
}
six["2_sector"] = {
    "落とせたか": ("**落とせた**" if not g2["gate_sector_mh"] else "落とせなかった"),
    "MH": {str(v): g2["mh"][str(v)] for v in SIGN_VINTAGES},
    "間接標準化": {str(v): g2["indirect_standardization"][str(v)] for v in SIGN_VINTAGES},
    "業種を1つ抜くと崩れる業種": g2["leave_one_sector_out_breakers"],
    "MHの中身": {str(v): g2["mh_decomposition"][str(v)]["strata_entering_MH"] for v in SIGN_VINTAGES},
}
_x5_break = [k for k in ("drop_irr85", "drop_semi_core", "drop_semi_core_plus_edge", "drop_irr85_and_semi")
             if X5[k].get("gates123_hold") is False]
six["3_irr_shadow"] = {
    "落とせたか": ("**落とせた**（名指しで抜くと条件1-3が崩れる: " + "・".join(_x5_break) + "）"
                   if _x5_break else
                   ("落とせなかった（文言どおりも通り、名指しで抜いても条件1-3は保たれる）"
                    if g3["gate_irr_literal"] else "**落とせた**（文言どおり落ちる）")),
    "honest_verdict": g3["gate_irr_honest"],
    "power_audit": g3["gate_irr_power_audit"],
    "irr_coverage": X5["irr_coverage_in_group"],
    "irr_read_only_for_2018": X5["irr_read_only_for_2018"],
    "drop_tests": {k: {kk: vv for kk, vv in X5[k].items() if kk != "per_vintage"}
                   for k in ("drop_irr85", "drop_semi_core", "drop_semi_core_plus_edge", "drop_irr85_and_semi")},
}
six["4_one_company"] = {
    "落とせたか": (f"**落とせた**（{g4['n_breaking_gates_1_to_3']}社を1社抜くだけで条件1-3が崩れる: "
                   f"{[x['ticker'] for x in g4['breakers_gates_1_to_3']]}）"
                   if g4["n_breaking_gates_1_to_3"] > 0
                   else "落とせなかった（どの1社を抜いても条件1-3は保たれる）"),
    "worst_maintained_lift": g4["worst_maintained_lift"],
    "max_abs_delta": g4["max_abs_delta_from_one_company"],
    "note": "gate4(業種)は元から落ちているので、1社抜きの判定は条件1-3で見る。",
}
six["5_permutation"] = {
    "この1本だけを検定したなら": (f"p={g5['unrestricted_ticker_bundle']['p_ge_observed']}"
                                  f"（層内 p={g5['within_sic2']['p_ge_observed']}）"),
    "実際は2840本から選ばれている": (
        f"帰無でも L3 {g5['family_wise_from_explorer']['P_at_least_one_pass_under_null_L3']} / "
        f"L4 {g5['family_wise_from_explorer']['P_at_least_one_pass_under_null_L4']} の確率で"
        f"1本以上『合格』が出る。帰無の最大統計量 p95={_nullmax['p95']} / p99={_nullmax['p99']} "
        f"に対し観測 {g1['maintained_lift']}＝**{g5['observed_vs_null_max_distribution']['position']}**"),
    "落とせたか": None,
}
six["6_increment"] = {
    "落とせたか": ("**落とせた**（既存の関門の生存者の中では prereg の線を維持できない）"
                   if not (g6["prereg_line_applied_to_the_increment"]["gate_lift_holds"]
                           and g6["prereg_line_applied_to_the_increment"]["gate_min_numerator_holds"])
                   else "落とせなかった"),
    "既存関門の生存者内": g6["prereg_line_applied_to_the_increment"],
    "脚単独との増分": {"best_leg": g6["best_leg_maintained_lift"],
                       "increment": g6["increment_over_best_leg"]},
}
six["5_permutation"]["落とせたか"] = (
    "**落とせた**（多重検定を織り込むと帰無の最大値と見分けがつかない）"
    if g1["maintained_lift"] < _nullmax["p95"] else
    "落とせなかった（単体p値も多重検定の値札も超えている）")

_broke = [k for k, v in six.items()
          if isinstance(v.get("落とせたか"), str) and v["落とせたか"].startswith("**落とせた**")]

verdict = {
    "候補": CAND["label"] + " / " + CAND["population"] + " / 勝者側",
    "探索側の弁": (f"不合格（gate_failed_at={ref.get('gate_failed_at')}）" if ref else "見つからず"),
    "再現": ("できた" if cross["mismatches"] == 0 else "**できていない**"),
    "6検証のうち落ちた数": len(_broke),
    "落ちた検証": _broke,
    "prereg_gates_literal": gates,
    "結論": None,
}
verdict["結論"] = (("**不合格**——6検証のうち " + "・".join(_broke) + " が落ちた。"
                    + ("prereg の gate4(業種調整) が文言どおりに落ちる。" if not g2["gate_sector_mh"] else ""))
                   if _broke else "落とせなかった")

# ── 落とし方の強さを正直に格付けする（『落ちた』と『強く落ちた』は別） ──
verdict["落とし方の強さ"] = {
    "2_sector": {
        "強さ": "**弱い**",
        "なぜ": ("MHは3ビンテージで層を1/1/3しか使わず、群の 16.7%/23.5%/43.5% しか見ていない"
                 "（P_quality は約330社が47のsic2に散るので、群も残りも n>=3 を満たす層がほとんど無い）。"
                 "しかも**最小層サイズという実装の選び方だけで答えが反転する**——"
                 f"min_n=2 なら {g2['mh_min_stratum_size_sensitivity']['min_n=2']}（ほぼ通る）／"
                 f"min_n=3(規約) なら {g2['mh_min_stratum_size_sensitivity']['min_n=3']}／"
                 f"min_n=4 なら {g2['mh_min_stratum_size_sensitivity']['min_n=4']}。"
                 "層を1つも落とさない間接標準化は "
                 f"{[g2['indirect_standardization'][str(v)]['risk_diff_vs_sector'] for v in SIGN_VINTAGES]}"
                 "＝3ビンテージとも 0.15 を超える。業種を1つ抜いても条件1-3は崩れない。"),
        "本当の構造": ("業種で符号が割れている。粗い層（群の100%が残る）で見ると "
                       "**製造 +0.42/+0.55/+0.40 ／ サービス −0.16/−0.17/−0.11 ／ 卸小売 −0.30/−0.35/−0.30**。"
                       "サービスの群は3ビンテージ合計で **0勝/12社**、卸小売は 0勝/3社。"
                       "MH が負に振れたのは、入った層がたまたま sic2=73(サービス) だったから。"
                       "＝『業種調整で消える』のではなく『**製造業でしか働かない**』。"),
    },
    "5_permutation": {
        "強さ": "**中**",
        "なぜ": (f"この1本だけなら p={g5['unrestricted_ticker_bundle']['p_ge_observed']}（層内も同じ）で、"
                 "単ビンテージの二項pも "
                 f"{[X6['single_vintage_binomial'][str(v)]['p_one_sided'] for v in SIGN_VINTAGES]} と小さい。"
                 "落ちるのは**2840検定から選ばれている**ことを織り込んだとき——"
                 f"帰無の最大統計量は p90={_nullmax['p90']} / p95={_nullmax['p95']} で、観測 {g1['maintained_lift']} は"
                 "その間＝**多重検定込みの p は概ね 0.05〜0.10**。5%は通らないが、帰無の奥深くにあるわけでもない。"),
    },
    "落とせなかった検証": {
        "1_vintage_sign": "符号は3ビンテージとも正。ただし58セル＝実体30社、5社(AEIS/AFL/AME/MKSI/PH)が3回とも勝者。",
        "3_irr_shadow": (f"名指しで抜いても崩れない（irr=85除外で維持lift {X5['drop_irr85']['maintained_lift']}／"
                         f"半導体連鎖除外で {X5['drop_semi_core']['maintained_lift']}／両方で "
                         f"{X5['drop_irr85_and_semi']['maintained_lift']}）。"
                         "**ただし irr が読まれているのは2018だけ・群の52%だけ**なので、"
                         "『irrの影ではない』と強くは言えない。"),
        "4_one_company": f"どの1社を抜いても条件1-3は保たれる（最大変化 {g4['max_abs_delta_from_one_company']}）。",
        "6_increment": ("既存の関門（事業の収縮なし ∧ 利払カバー）の生存者の中でも "
                        f"増分lift {[g6['survivors'][str(v)]['both']['incremental_lift'] for v in SIGN_VINTAGES]}・"
                        f"分子 {[g6['survivors'][str(v)]['both']['k'] for v in SIGN_VINTAGES]} で線を保つ。"
                        f"脚単独の最良は {g6['best_leg_maintained_lift']}（sga単独）で、"
                        f"積の増分は {g6['increment_over_best_leg']}＝**組にする意味はある**"
                        f"（2×2の差の差 {[X1[str(v)]['交互作用(差の差)'] for v in SIGN_VINTAGES]}）。"),
    },
    "事前登録の外で最も強い反証": {
        "何": "レジーム分割（合否には数えない）",
        "実測": ("**3つの群すべてが同じことを言う**——"
                 "2018-07→2022-07 の4年で lift は "
                 f"{regime.get('per_vintage', {}).get('A_2018_2022', {}).get('lift')}(2018群) / "
                 f"{regime.get('other_vintage_groups', {}).get('2016', {}).get('A_2018_2022', {}).get('lift')}(2016群) / "
                 f"{regime.get('other_vintage_groups', {}).get('2017', {}).get('A_2018_2022', {}).get('lift')}(2017群)"
                 "＝ゼロか負。2022-07→2026-08 の4年で "
                 f"{regime.get('per_vintage', {}).get('B_2022_2026', {}).get('lift')} / "
                 f"{regime.get('other_vintage_groups', {}).get('2016', {}).get('B_2022_2026', {}).get('lift')} / "
                 f"{regime.get('other_vintage_groups', {}).get('2017', {}).get('B_2022_2026', {}).get('lift')}"
                 "＝大きく正。**8年の効果は全部が後半4年から来ている**。"),
        "限界": ("3つの群はメンバーが違う（18/17/23社・共通8社）ので群としては独立に近いが、"
                 "**窓は同じ暦の4年**なので『どの期間が効果を作ったか』の観測は1回きり。"
                 "CLAUDE.md が irr=85 で記録した『超過はほぼAI期に出た（前期lift+0.13 / 後期+0.38）』と同型。"),
    },
    "実務的な読み替え": ("この候補を規則にするなら、正直な形は「**質実証を通った製造業の中で、"
                        "設備投資比が下位1/4かつ販管費比が中央値以下の社**」。"
                        "サービス・小売では 0勝/15社 で、むしろ負の信号。"
                        "そして効果の実測はすべて 2022-2026 に載っている。"),
}

out = {
    "generated": time.strftime("%Y-%m-%d"),
    "tool": "night/hist_wd_verify_capex_sga.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "candidate": CAND,
    "stance": "反証が仕事。prereg の線は一つも動かしていない（lift>=0.15 / 分子>=5 / 符号不変 / 業種 / irr）。",
    "explorer_claim": ref,
    "reproduction_crosscheck": cross,
    "spot_check_row_level": spot,
    "must_report_before_verdict": pre,
    "test1_vintage_sign": g1,
    "test2_sector": g2,
    "test3_irr_shadow": g3,
    "test4_leave_one_company_out": g4,
    "test5_permutation": g5,
    "test6_increment_over_existing_gates": g6,
    "X1_interaction": X1,
    "X2_capex_zero_and_measurability": X2,
    "X3_industry_mix": X3,
    "X4_population_dependence": X4,
    "X5_drop_irr85_and_semiconductor": X5,
    "X6_bucket_sector_and_single_vintage": X6,
    "aux_R_regime_split": regime,
    "aux_S_disjoint_subwindow": sub,
    "aux_T_threshold_sensitivity": thr_sens,
    "prereg_gates_literal": gates,
    "survived_all_prereg_gates_literal": survived_prereg,
    "six_verification_outcomes": six,
    "verdict": verdict,
    "runtime_sec": round(time.time() - t0, 1),
}

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print(f"[候補] {CAND['label']} / {CAND['population']} / 勝者側")
print(f"[再現] 比較 {cross['compared']} 件 / 不一致 {cross['mismatches']} 件 → {cross['verdict']}")
print(f"[行検算] 不一致 {spot['total_mismatch']} 件")
print()
for v in SIGN_VINTAGES:
    c = cells[v]
    print(f"  {v}: n_pop={c['n_pop']} base={c['p_base']} n_group={c['n_group']} k={c['numerator']} "
          f"p={c['p_group']} lift={c['lift']}  (閾値 capex<={c['thresholds']['f2_capex_r']['threshold']}"
          f" / sga<={c['thresholds']['f2_sga_r']['threshold']})")
print(f"  維持lift={g1['maintained_lift']}  最小分子={g1['min_numerator']}")
print()
print("[事前] 実効の線:", {k: v["effective_lift_required"] for k, v in pre["reachability_and_effective_line"].items()},
      " 縛り:", {k: v["binding"] for k, v in pre["reachability_and_effective_line"].items()})
print("[事前] 検出力(真lift 0.15/0.20/0.30 の下限〜上限):",
      {k: (v["three_independent(下限)"], v["single_2018(上限)"]) for k, v in pre["power"].items()})
print()
print(f"[1 ビンテージ] 符号={g1['gate_sign_stability']} lift={g1['gate_lift']} 分子={g1['gate_min_numerator']}")
print(f"    群: {g1['group_membership_overlap']['n_by_vintage']} 共通{g1['group_membership_overlap']['n_intersection_all3']}社"
      f" 和集合{g1['group_membership_overlap']['n_union']}社 jaccard={g1['group_membership_overlap']['jaccard']}")
print(f"    勝者 延べ{g1['distinct_winning_companies_carrying_the_finding']['n_events_total']}件 → 実体"
      f"{g1['distinct_winning_companies_carrying_the_finding']['n_distinct_companies']}社")
print(f"    2013/2015: {g1['out_of_sample_2013_2015']}")
print()
for v in SIGN_VINTAGES:
    m = g2["mh"][str(v)]
    print(f"[2 業種] {v}: MH={m['mh_risk_diff']} 層{m['strata_used']}使用/{m['strata_dropped']}破棄 "
          f"群の被覆={m.get('group_coverage_share')}")
for v in SIGN_VINTAGES:
    i = g2["indirect_standardization"][str(v)]
    if i:
        print(f"    間接標準化 {v}: 観測{i['observed_wins']} vs 業種期待{i['expected_wins_sector_leave_self_out']}"
              f" → 差={i['risk_diff_vs_sector']} (SMR={i['smr']})")
print(f"    層内置換 p={g2['within_sector_permutation']['p_ge_observed']}")
print(f"    業種を1つ抜くと崩れる: {g2['leave_one_sector_out_breakers']}")
print(f"    gate4(業種MH>=0.15) = {g2['gate_sector_mh']}")
print()
print(f"[3 irr] 2018: rho={_ic18.get('corr_group_vs_irr')} 直交ヒント={_ic18.get('orthogonal_hint')} "
      f"群のうちirr読解あり={_ic18.get('n_group_within_irr_read')}")
if _o18:
    print(f"    同サイズの無作為群が『直交』と呼ばれる確率={_o18.get('P_random_group_of_same_size_is_called_orthogonal')}")
print(f"    正直な判定: {g3['gate_irr_honest']}")
print()
print(f"[4 1社] 最悪の維持lift={g4['worst_maintained_lift']} 最大変化={g4['max_abs_delta_from_one_company']} "
      f"条件1-3が崩れる社={g4['n_breaking_gates_1_to_3']} {[x['ticker'] for x in g4['breakers_gates_1_to_3']]}")
print(f"    群から勝者を何社抜くと崩れるか: {[(x['vintage'], x['n_winners_to_remove_to_break'], x['which_gate_breaks_first']) for x in g4['sequential_winner_removal']]}")
print()
print(f"[5 置換] 単体p(無制約)={g5['unrestricted_ticker_bundle']['p_ge_observed']} / 層内p={g5['within_sic2']['p_ge_observed']}")
print(f"    探索全体 {g5['family_wise_from_explorer']['n_tests_in_search']}検定・帰無で1本以上合格 L3="
      f"{g5['family_wise_from_explorer']['P_at_least_one_pass_under_null_L3']} L4="
      f"{g5['family_wise_from_explorer']['P_at_least_one_pass_under_null_L4']}")
print(f"    帰無の最大統計量 p95={_nullmax['p95']} p99={_nullmax['p99']} ← 観測 {g1['maintained_lift']}"
      f"（{g5['observed_vs_null_max_distribution']['position']}）")
print()
print(f"[6 増分] 脚単独の最良={g6['best_leg_maintained_lift']} 積の増分={g6['increment_over_best_leg']}")
for v in SIGN_VINTAGES:
    s = g6["survivors"][str(v)]["both"]
    print(f"    {v} 既存関門の生存者内: n群={s['n_group_among_survivors']} 分子={s['k']} 増分lift={s['incremental_lift']}")
print(f"    prereg の線を増分に当てる: lift={g6['prereg_line_applied_to_the_increment']['maintained_incremental_lift']}"
      f" 分子={g6['prereg_line_applied_to_the_increment']['min_numerator']}")
print()
print("── X1 交互作用（2×2） ──")
for v in SIGN_VINTAGES:
    x = X1[str(v)]
    print(f"  {v}: " + " ".join(f"{k}={vv['p']}(n{vv['n']})" for k, vv in x["cells"].items())
          + f"  差の差={x['交互作用(差の差)']}")
print("── X2 capex_r の形 ──")
for v in SIGN_VINTAGES:
    x = X2[str(v)]
    print(f"  {v}: 被覆={x['capex_r_coverage']} 母集団の0割合={x['share_exactly_zero_in_pop']} "
          f"群の0社数={x['n_exactly_zero_in_group']} q25={x['threshold_q25']} 群のcapex中央値={x['group_capex_r_median']}")
    m = X2["measurability_vs_outcome"][str(v)]
    print(f"      可測{m['n_measurable']}社 p={m['p_win_measurable']} vs 非可測{m['n_not_measurable']}社 "
          f"p={m['p_win_not_measurable']} 差={m['gap']}")
print("── X3 業態 ──")
for v in SIGN_VINTAGES:
    x = X3[str(v)]
    print(f"  {v}: 群={x['group_buckets']} / 群の非製造比={x['non_manufacturing_share_in_group']} "
          f"vs 母集団{x['non_manufacturing_share_in_pop']}")
print("── X5 irr=85 / 半導体連鎖 を名指しで抜く ──")
print(f"  群のirr被覆: {{{', '.join(str(v)+':'+str(X5['irr_coverage_in_group'][str(v)]['share']) for v in SIGN_VINTAGES)}}}"
      f"  （2016/2017 は irr の読解が無い）")
print(f"  2018 群の内訳: irr>=85 {X5['win_rate_by_irr_2018']['irr>=85']['k']}/{X5['win_rate_by_irr_2018']['irr>=85']['n']}勝 "
      f"／ irr<85 {X5['win_rate_by_irr_2018']['irr<85(読解あり)']['k']}/{X5['win_rate_by_irr_2018']['irr<85(読解あり)']['n']}勝 "
      f"／ 未読解 {X5['win_rate_by_irr_2018']['irr未読解']['k']}/{X5['win_rate_by_irr_2018']['irr未読解']['n']}勝")
for k in ("drop_irr85", "drop_semi_core", "drop_semi_core_plus_edge", "drop_irr85_and_semi"):
    x = X5[k]
    print(f"  {x['tag']}: 維持lift={x.get('maintained_lift')} 分子={x.get('min_numerator')} "
          f"符号={x.get('sign_stable')} → 条件1-3={x.get('gates123_hold')} (Δ={x.get('delta_vs_full')})")
print(f"  群の実体: 延べ{X5['distinct_group_companies']['n_cells_total']}セル → "
      f"{X5['distinct_group_companies']['n_distinct_companies']}社 / 勝者{X5['distinct_group_companies']['n_distinct_winners']}社 "
      f"／ 3ビンテージ全部で勝った社={X5['distinct_group_companies']['winners_in_all_3_vintages']}")
print("── X4 P_full でも出るか ──")
print(f"  維持lift={X4['P_full']['maintained_lift']} 分子={X4['P_full']['min_numerator']} "
      f"符号={X4['P_full']['sign_stable']} MH={{{', '.join(str(v)+':'+str((X4['P_full']['mh'][str(v)] or {}).get('mh_risk_diff')) for v in SIGN_VINTAGES)}}}")
print("── X6 粗い層での業種調整（群のほぼ全社が残る） ──")
for v in SIGN_VINTAGES:
    x = X6["bucket_level_sector_control"][str(v)]
    print(f"  {v}: 加重リスク差={x['weighted_risk_diff']} 群の被覆={x['group_coverage_share']}"
          f"  内訳=" + " ".join(f"{k}:{vv['lift_within_bucket']}(n{vv['n_group']})" for k, vv in x["by_bucket"].items()))
print("── X6 単ビンテージの二項p ──")
for v in SIGN_VINTAGES:
    x = X6["single_vintage_binomial"][str(v)]
    print(f"  {v}: {x['k']}/{x['n_group']} vs base {x['base']} → p={x['p_one_sided']}")
if "per_vintage" in regime:
    print("── R レジーム ──")
    for k, r_ in regime["per_vintage"].items():
        print(f"  2018群 {k}: base={r_['p_base']} 群={r_['p_group']} lift={r_['lift']} (n群={r_['n_group']})")
    for vv, blk in regime.get("other_vintage_groups", {}).items():
        for k, r_ in blk.items():
            print(f"  {vv}群 {k}: base={r_['p_base']} 群={r_['p_group']} lift={r_['lift']} (n群={r_['n_group']})")
print()
print("【判定】", verdict["結論"])
print("prereg 5条件:", gates)
print(f"→ {DEST}  ({out['runtime_sec']}s)")
