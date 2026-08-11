#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_rnd_sga.py — 候補「f2_rnd_r[上位1/4] ∧ f2_sga_r[下位1/4]（勝者側・P_full）」を**潰しにかかる**検証。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json          … 5ビンテージ統合パネル（唯一の真実）
          out/hist_wd_win_pair.json       … 探索側の答え（**再現の突合せ相手**。信じる前に検算する）
          out/retro_returns_{2013_all,2016,2017,2018}.json … 部分窓リターンの導出用（同じ終端日）
          out/retro_monthly_2018_2026.json … レジーム分割（2018-07→2022-07 / 2022-07→2026-08）
出力    : out/hist_wd_verify_rnd_sga.json

────────────────────────────────────────────────────────────
この道具の立場
────────────────────────────────────────────────────────────
**反証が仕事であって確認ではない。** 候補に有利な数字を探さない。
prereg の5条件（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を**一つも緩めない**。
線を緩めた数字を出すときは必ず `事前登録の外・診断専用` と明記し、合否には数えない。

「測れない」と「不合格」を区別する。f2_ 特徴量は 2013/2015 に構造的に存在しない＝**判定不能**であって
不合格ではない（ただし『判定不能を合格の材料にもしない』）。

────────────────────────────────────────────────────────────
当てる6つ（依頼どおり。1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 ビンテージ符号  : 2016/2017/2018 で符号が反転しないか。
                    **さらに「3ビンテージ＝3つの証拠か」を実測する**——群のティッカーの重なりと、
                    outcome の窓の重なり（同じ終端日ゆえ 2016窓の8.09/10.09 が 2018窓と共通）。
                    2013/2015 は f2_ が無いので判定不能（理由を書く）。
2 業種調整        : 同一 sic2 内で残るか。MH＋層内置換＋業種1つずつ除去。
                    **MHが群の何%を覆っているか**を必ず出す（層を落とすほど「調整した」の意味が薄れる）。
                    層を落とさない間接標準化（業種期待勝者数）も併せて出す。
3 irr の影        : irr>=70 層内で残るか・irr と直交か。
                    **直交ヒットが群の小ささの産物でないか**を確かめる（群4/136 なら相関は必ず小さい）。
4 1社の影響       : ティッカーを1社ずつ**パネルごと**抜いて、閾値・母集団・群・5条件を全部作り直す。
5 置換            : outcome の束をティッカーごと置換（ビンテージ間相関を保つ帰無）2000回。
                    この候補単体の p と、探索全体の多重検定の値札の両方を出す。
6 既存の関門との重複: 事業の収縮 / 利払カバー / 質実証 の生存者の中でも残るか（＝増分）。
                    脚単独との増分も出す。

補助（事前登録の外・診断専用。合否には数えない）:
  R レジーム分割 2018-07→2022-07 / 2022-07→2026-08（月次在庫から自前で計算）
  T 閾値感度（上位20/25/30% × 下位20/25/30%）
  S 部分窓分解（2013-2016 / 2016-2018 / 2018-2026）
"""
import json, os, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
PAIR = os.path.join(OUT, "hist_wd_win_pair.json")
DEST = os.path.join(OUT, "hist_wd_verify_rnd_sga.json")

# ─── prereg の線（読むだけ・作らない） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
N_PERM = 2000
SEED = 20260811

# ─── 候補（依頼で名指しされたもの。ここは動かさない） ───
CAND = {
    "population": "P_full",
    "side": "winner",
    "legs": [("f2_rnd_r", "上位1/4"), ("f2_sga_r", "下位1/4")],
    "label": "f2_rnd_r[上位1/4] ∧ f2_sga_r[下位1/4]",
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
        thrs[var] = {"cut": cut, "threshold": thr, "n_measurable": nm}
    if any(t["threshold"] is None for t in thrs.values()):
        return None
    preds = {var: cut_pred(cut, thrs[var]["threshold"]) for var, cut in legs}
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
        "_group_rows": b["group"], "_pop_rows": b["pop"], "_thresholds": b["thresholds"],
    }


def strip(c):
    return {k: v for k, v in c.items() if not k.startswith("_")} if c else None


# ────────────────────────────── 0. 再現と突合せ（信じる前に検算する） ──────────────────────────────
cells = {v: cell(v, CAND["population"], CAND["legs"]) for v in SIGN_VINTAGES}

ref = None
for e in pair_out["passing_pairs_detail"]:
    if e["label"] == CAND["label"] and e["population"] == CAND["population"]:
        ref = e
        break

cross = {"found_in_explorer_output": ref is not None, "compared": 0, "mismatches": 0, "detail": []}
if ref:
    for v in SIGN_VINTAGES:
        a, b = cells[v], ref["by_vintage"][str(v)]
        for k in ("n_pop", "p_base", "n_group", "numerator", "p_group", "lift", "n_measurable_both", "lift_meas"):
            cross["compared"] += 1
            if a.get(k) != b.get(k):
                cross["mismatches"] += 1
                cross["detail"].append({"vintage": v, "key": k, "mine": a.get(k), "explorer": b.get(k)})
cross["verdict"] = ("一致（探索側の数字は再現できる。以降の検証はこれが通ったうえでの話）"
                    if cross["mismatches"] == 0 else "**不一致＝結論を書いてはいけない**")

# 行を直接数えるスポット検算（ビット演算に頼らないことの証明）
spot = {"vintage": 2018, "mismatch": 0}
_c = cells[2018]
_thr_r = _c["_thresholds"]["f2_rnd_r"]["threshold"]
_thr_s = _c["_thresholds"]["f2_sga_r"]["threshold"]
_direct = [r for r in pop_rows(2018, "P_full")
           if r.get("f2_rnd_r") is not None and r.get("f2_sga_r") is not None
           and r["f2_rnd_r"] >= _thr_r and r["f2_sga_r"] <= _thr_s]
spot["n_direct"] = len(_direct)
spot["n_cell"] = _c["n_group"]
spot["mismatch"] = 0 if len(_direct) == _c["n_group"] else 1
spot["tickers"] = sorted(r["ticker"] for r in _direct)


# ────────────────────────────── 1. ビンテージ符号 ──────────────────────────────
g1 = {"per_vintage": {str(v): strip(cells[v]) for v in SIGN_VINTAGES}}
lifts = [cells[v]["lift"] for v in SIGN_VINTAGES]
nums = [cells[v]["numerator"] for v in SIGN_VINTAGES]
g1["signs_all_positive"] = all(x is not None and x > 0 for x in lifts)
g1["maintained_lift"] = r4(min(abs(x) for x in lifts))
g1["min_numerator"] = min(nums)
g1["gate_sign_stability"] = g1["signs_all_positive"]
g1["gate_lift"] = g1["maintained_lift"] >= LIFT
g1["gate_min_numerator"] = g1["min_numerator"] >= MIN_NUM

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
    "how_to_read": ("3ビンテージの群がほぼ同じ社なら、『3回一致した』は3つの証拠ではなく"
                    "**同じ社を3回数えただけ**。prereg の independence_warning がまさにこれ。"),
}

# 1c outcome の窓の重なり（同じ終端日なので算術で出る）
ret_years = {2013: 13.09, 2015: 11.10, 2016: 10.09, 2017: 9.09, 2018: 8.09}
g1["outcome_window_overlap"] = {
    "years": {str(v): ret_years[v] for v in SIGN_VINTAGES},
    "shared_tail_years": 8.09,
    "share_of_2016_window_shared_with_2018": r4(8.09 / 10.09),
    "share_of_2017_window_shared_with_2018": r4(8.09 / 9.09),
    "how_to_read": ("窓は全部 2026-08-04 で終わる。2016 の 10.09 年のうち 8.09 年は 2018 の窓そのもの＝"
                    "**同じ8年を3回測っている**。ビンテージ間の outcome 相関はパネルの診断で 0.845〜0.961。"),
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


# ────────────────────────────── 2. 業種調整 ──────────────────────────────
def mh(v, pop, legs, rows_src=None, win_of=None, drop_sic=None):
    """MH重み付きリスク差。探索側 mh_risk_diff_pair と同一規則（各層 n>=3 の両側が要る）。"""
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
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        covered += n1
        wgt = n1 * n0 / (n1 + n0)
        nu += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    if den == 0:
        return {"mh_risk_diff": None, "strata_used": used, "strata_dropped": drop,
                "group_covered": covered, "group_total": len(b["group"])}
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
        # 自分を抜いた同業の勝率（自己参照を外す）
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

# 2b 層内置換（ティッカー束・sic2 内でのみ入れ替える＝業種構成を保つ帰無）
tick_sic = {}
for r in ANA:
    if r.get("sic2"):
        tick_sic.setdefault(r["ticker"], r["sic2"])

# 置換の土台: 2016/2017/2018 に現れるティッカー
tickers_sign = sorted({r["ticker"] for v in SIGN_VINTAGES for r in by_v[v]})
outcome_bundle = {t: {v: None for v in SIGN_VINTAGES} for t in tickers_sign}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        outcome_bundle[r["ticker"]][v] = bool(r.get("win"))


def maintained_lift_under(winmap):
    """winmap[(ticker,vintage)]->bool のもとで3ビンテージの (符号揃い, 最小|lift|, 最小分子) を返す。"""
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
    sics = sorted({r.get("sic2") for r in pop_rows(2018, CAND["population"]) if r.get("sic2")})
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


g2["leave_one_sector_out"] = sorted(
    [x for x in loo_sector() if x.get("maintained_lift") is not None],
    key=lambda x: (x["maintained_lift"] if x["maintained_lift"] is not None else 9))[:12]
g2["leave_one_sector_out_all_hold"] = all(
    x.get("gates123_hold", False) for x in loo_sector() if "gates123_hold" in x)

# 業種そのものの説明力（群の集中度と、支配業種単独のリフト）
def sector_profile(v):
    c = cells[v]
    cnt = Counter(r.get("sic2") for r in c["_group_rows"])
    top = cnt.most_common(5)
    P = c["_pop_rows"]
    base = c["p_base"]
    out = {"n_group": c["n_group"], "sic2_top5": top,
           "top3_share": r4(sum(n for _, n in top[:3]) / c["n_group"]) if c["n_group"] else None,
           "sectors": []}
    for s, n in top[:3]:
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


# 2e MH を層ごとに分解する（「業種内でも残る」が**どの層から来ているか**）
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
            "how_to_read": "MHが『業種調整後も残る』と言うとき、その値が**どの層から来ているか**。"}


g2["mh_decomposition"] = {str(v): mh_decompose(v) for v in SIGN_VINTAGES}

# 2f MHに入る層を1つだけにしたらどうなるか（＝支配層を外した業種調整）
def mh_excluding_stratum(v, s_ex):
    return mh(v, CAND["population"], CAND["legs"], drop_sic=s_ex)


_ent = {v: [t["sic2"] for t in g2["mh_decomposition"][str(v)]["strata_entering_MH"]] for v in SIGN_VINTAGES}
_all_ent = sorted({s for v in SIGN_VINTAGES for s in _ent[v]})
g2["mh_excluding_each_entering_stratum"] = {
    s: {str(v): mh_excluding_stratum(v, s) for v in SIGN_VINTAGES} for s in _all_ent}
g2["mh_gate_survives_excluding_each_stratum"] = {
    s: all((m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT)
           for m in g2["mh_excluding_each_entering_stratum"][s].values())
    for s in _all_ent}

# 2g MH の最小層サイズ規則への感度（事前登録の外・診断専用）
def mh_minsize(v, minn):
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
    nu = den = 0.0
    used = 0
    for s, (n1, k1, n0, k0) in st.items():
        if n1 < minn or n0 < minn:
            continue
        wgt = n1 * n0 / (n1 + n0)
        nu += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    return {"strata_used": used, "mh_risk_diff": (r4(nu / den) if den else None)}


g2["mh_min_stratum_size_sensitivity"] = {
    "note": "**事前登録の外・診断専用**。探索側の規則は各層 n>=3。層の最小サイズを動かすと MH がどう動くか。",
    **{f"min_n={k}": {str(v): mh_minsize(v, k) for v in SIGN_VINTAGES} for k in (3, 4, 5, 6)},
}

# 2h 群のメンバーの業種記述（層が同質かどうかは記述を見ないと判らない）
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
    xs = [1.0 if id(r) in gset else 0.0 for r in R
          if r.get("f2_rnd_r") is not None and r.get("f2_sga_r") is not None]
    ys = [float(r["irr"]) for r in R
          if r.get("f2_rnd_r") is not None and r.get("f2_sga_r") is not None]
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
# 直交ヒットが「群が小さいから」でないかを測る: 群のサイズを保ったまま無作為に群を作ると相関はどうなるか
def orthogonality_null(v, n_draw=2000):
    c = cells[v]
    R = [r for r in c["_pop_rows"] if r.get("irr") is not None
         and r.get("f2_rnd_r") is not None and r.get("f2_sga_r") is not None]
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
# 文言どおりなら通るが、**通した試験に検出力があるか**を別に測る
_o18 = g3["orthogonality_is_it_just_small_n"].get("2018") or {}
g3["gate_irr_passed_by"] = ("直交ヒント" if _ic18.get("orthogonal_hint") is True else "層内リフト")
g3["gate_irr_honest"] = ("判定不能（irr>=70 層の群が薄く層内検定ができず、"
                         "直交ヒントは同サイズの無作為群でも "
                         f"{_o18.get('P_random_group_of_same_size_is_called_orthogonal')} の確率で立つ"
                         "＝独立性の証拠になっていない）"
                         if (_ic18.get("irr_ge70", {}).get("lift") is None
                             and (_o18.get("P_random_group_of_same_size_is_called_orthogonal") or 0) >= 0.5)
                         else ("合格" if g3["gate_irr_literal"] else "不合格"))
g3["gate_irr"] = g3["gate_irr_literal"]

# 3c 半導体連鎖という別の説明（irr ではなく業種の影ではないか）
SEMI_SIC2 = {"36", "35"}  # 電子機器・産業機械（群の8割が入る2業種）
def semi_split(v):
    c = cells[v]
    P = c["_pop_rows"]
    gset = set(id(r) for r in c["_group_rows"])
    out = {}
    for tag, sel in (("in_36_35", lambda r: r.get("sic2") in SEMI_SIC2),
                     ("outside_36_35", lambda r: r.get("sic2") not in SEMI_SIC2 and r.get("sic2"))):
        sub = [r for r in P if sel(r)]
        g = [r for r in sub if id(r) in gset]
        b = rate(sum(1 for r in sub if r.get("win")), len(sub))
        kg = sum(1 for r in g if r.get("win"))
        out[tag] = {"n_sub": len(sub), "p_sub": r4(b), "n_group": len(g), "k_group": kg,
                    "p_group": r4(rate(kg, len(g))),
                    "lift_within": (None if not g else r4(rate(kg, len(g)) - b))}
    return out


g3["semiconductor_complex_split"] = {str(v): semi_split(v) for v in SIGN_VINTAGES}


# ────────────────────────────── 4. 1社の影響 ──────────────────────────────
def loo_ticker():
    cand_tickers = sorted(union)  # 3ビンテージのどこかで群に入る社
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
                    "gate_lift": ml >= LIFT, "gate_min_num": mn >= MIN_NUM,
                    "gate_sign": same, "gate_sector": gsec,
                    "all_gates_1_to_4_hold": bool(same and ml >= LIFT and mn >= MIN_NUM and gsec)})
    return res


loo = loo_ticker()
meas = [x for x in loo if "maintained_lift" in x]
g4 = {
    "n_tickers_tested": len(loo),
    "worst_maintained_lift": r4(min(x["maintained_lift"] for x in meas)) if meas else None,
    "best_maintained_lift": r4(max(x["maintained_lift"] for x in meas)) if meas else None,
    "max_abs_delta_from_one_company": r4(max(abs(x["delta_vs_full"]) for x in meas)) if meas else None,
    "n_breaking_any_gate": sum(1 for x in meas if not x["all_gates_1_to_4_hold"]),
    "breakers": [x for x in meas if not x["all_gates_1_to_4_hold"]],
    "top10_most_influential": sorted(meas, key=lambda x: x["maintained_lift"])[:10],
    "how_to_read": ("1社をパネルごと抜いて閾値・母集団・群・条件を全部作り直す。"
                    "1社で条件が崩れるなら、それは発見ではなく1社の話。"),
}

# 群から勝者を順に抜いたら何社で崩れるか（分子が縛る側の感度）
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
                                            and (k_g - need) / (n_g - need) - base >= LIFT) else "lift")})
    return out


g4["sequential_winner_removal"] = sequential_drop()


# ────────────────────────────── 5. 置換 ──────────────────────────────
g5 = {
    "unrestricted_ticker_bundle": perm_res["unrestricted"],
    "within_sic2": perm_res["within_sic2"],
    "family_wise_from_explorer": {
        "n_tests_in_search": pair_out["must_report_before_verdict"]["false_positive_rate"]["n_tests_in_procedure"],
        "P_at_least_one_pass_under_null_L5": pair_out["must_report_before_verdict"]["false_positive_rate"]["P_at_least_one_pass_by_level"]["L5"],
        "null_max_statistic_p95": pair_out["must_report_before_verdict"]["false_positive_rate"]["null_distribution_of_max_statistic"]["p95"],
        "null_max_statistic_p99": pair_out["must_report_before_verdict"]["false_positive_rate"]["null_distribution_of_max_statistic"]["p99"],
        "note": ("探索側が同じ帰無で測った値札。この候補の維持lift をこの分布の中に置くのが正しい読み方"
                 "——**単体のp値は『この1本だけを検定したなら』の話**で、実際は数千本から選ばれている。"),
    },
}
_nullmax = pair_out["must_report_before_verdict"]["false_positive_rate"]["null_distribution_of_max_statistic"]
g5["observed_vs_null_max_distribution"] = {
    "observed_maintained_lift": g1["maintained_lift"],
    "null_max_p50": _nullmax["p50"], "null_max_p90": _nullmax["p90"],
    "null_max_p95": _nullmax["p95"], "null_max_p99": _nullmax["p99"],
    "position": ("p95 と p99 の間" if g1["maintained_lift"] >= _nullmax["p95"] else
                 "p90 と p95 の間" if g1["maintained_lift"] >= _nullmax["p90"] else "p90 未満"),
}


# ────────────────────────────── 6. 既存の関門との重複 ──────────────────────────────
def gate_flags(r):
    """門が既に持つ関門の歴史側の相当物。**nde はパネルに無いので intcov を代理に使う（正直に代理と書く）**。"""
    shrink = (r.get("f2_cagr5") is not None and r.get("f2_opmD5") is not None
              and r["f2_cagr5"] < 0 and r["f2_opmD5"] < 0)
    ic = r.get("f2_intcov")
    fin_bad = (ic is not None and ic < 5)   # 利息ゼロ・タグ無し(null)は「負担なし」＝落とさない
    return {"shrink": shrink, "fin_bad": fin_bad, "quality": bool(r.get("P_quality"))}


def survivors_analysis(v):
    c = cells[v]
    P = c["_pop_rows"]
    gset = set(id(r) for r in c["_group_rows"])
    out = {}
    defs = {
        "no_shrink": lambda r: not gate_flags(r)["shrink"],
        "intcov_ok": lambda r: not gate_flags(r)["fin_bad"],
        "quality": lambda r: gate_flags(r)["quality"],
        "all_three": lambda r: (not gate_flags(r)["shrink"]) and (not gate_flags(r)["fin_bad"]) and gate_flags(r)["quality"],
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
    # 群のうち既存の関門で落ちる社
    ex = [r for r in c["_group_rows"] if gate_flags(r)["shrink"] or gate_flags(r)["fin_bad"]]
    out["group_members_already_excluded_by_gates"] = {
        "n": len(ex), "tickers": sorted(r["ticker"] for r in ex),
        "n_group": c["n_group"]}
    return out


g6 = {"survivors": {str(v): survivors_analysis(v) for v in SIGN_VINTAGES}}
g6["proxy_warning"] = ("財務キルは nde>4 だが nde はパネルに無い。**intcov<5 は代理であって同じ線ではない**"
                       "（CLAUDE.md の retro_breaker_test が使った線）。intcov が null の社は"
                       "『利息がない＝負担なし』として落とさない（欠測を不合格と読まない）。")

# 6b 脚単独との増分
def leg_alone(var, cut):
    res = {}
    for v in SIGN_VINTAGES:
        c = cell(v, CAND["population"], [(var, cut)])
        res[str(v)] = strip(c)
    ls = [res[str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [res[str(v)]["numerator"] for v in SIGN_VINTAGES]
    same = all(x is not None and x > 0 for x in ls)
    return {"by_vintage": res,
            "maintained_lift": r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None,
            "min_numerator": min(ns), "sign_stable": same}


g6["legs_alone"] = {f"{var}[{cut}]": leg_alone(var, cut) for var, cut in CAND["legs"]}
_best_leg = max((x["maintained_lift"] or 0) for x in g6["legs_alone"].values())
g6["best_leg_maintained_lift"] = r4(_best_leg)
g6["increment_over_best_leg"] = r4(g1["maintained_lift"] - _best_leg)

# 6c 既存の関門の生存者の中で、**prereg の線をそのまま**当てたらどうなるか
_inc = {v: g6["survivors"][str(v)]["all_three"] for v in SIGN_VINTAGES}
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
                    "そこで prereg の線（0.15・分子5）をそのまま当てる。ここで落ちるなら、"
                    "**門の中では働かない**——母集団全体でしか働かない指標だということ。"),
}


# ─────────────── 補助R（事前登録の外・診断専用）: レジーム分割 ───────────────
regime = {"status": "未実施"}
MON = os.path.join(OUT, "retro_monthly_2018_2026.json")
if os.path.exists(MON):
    mon = json.load(open(MON, encoding="utf-8"))
    SPLIT = 1656648000  # 2022-07-01 前後の月末を選ぶための錨

    def sub_cagr(series, t_from, t_to):
        """[epoch, adjclose] の列から、境界に最も近い点どうしで年率を出す。"""
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
    regime["how_to_read"] = ("2018年群を、その8年を前半4年と後半4年に割って測る。"
                             "前半でリフトが消え後半だけに出るなら、それは指標ではなく相場の記録。"
                             "**既存の out/retro_regime_test.json が同じ変数の組で同じことを既に記録している**"
                             "（前期 combo 0.259 vs base 0.249／後期 0.704 vs 0.282）。ここでは母集団を"
                             "P_full(956社)に替えて独立に測り直す。")

# ─────────────── 補助S（事前登録の外・診断専用）: 部分窓分解 ───────────────
sub = {"note": "**事前登録の外・診断専用**。同じ終端日ゆえ tr_total の比で部分窓が厳密に出る。"}
try:
    R = {}
    for tag, f in (("2013", "retro_returns_2013_all"), ("2016", "retro_returns_2016"),
                   ("2017", "retro_returns_2017"), ("2018", "retro_returns_2018")):
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
def cut_at(v, qr, qs):
    P = pop_rows(v, CAND["population"])
    vr = sorted(r["f2_rnd_r"] for r in P if r.get("f2_rnd_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    tr, ts = q_at(vr, qr), q_at(vs, qs)
    g = [r for r in P if r.get("f2_rnd_r") is not None and r.get("f2_sga_r") is not None
         and r["f2_rnd_r"] >= tr and r["f2_sga_r"] <= ts]
    n_pop, k_pop = len(P), sum(1 for r in P if r.get("win"))
    kg = sum(1 for r in g if r.get("win"))
    return {"thr_rnd": r4(tr), "thr_sga": r4(ts), "n_group": len(g), "k": kg,
            "lift": (None if not g else r4(kg / len(g) - k_pop / n_pop))}
for qr, qs in ((0.70, 0.30), (0.75, 0.25), (0.80, 0.20), (0.70, 0.25), (0.80, 0.25), (0.75, 0.30), (0.75, 0.20)):
    key = f"rnd_top{int((1-qr)*100)}%_sga_bottom{int(qs*100)}%"
    thr_sens[key] = {str(v): cut_at(v, qr, qs) for v in SIGN_VINTAGES}
    ls = [thr_sens[key][str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [thr_sens[key][str(v)]["k"] for v in SIGN_VINTAGES]
    thr_sens[key]["maintained_lift"] = (r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None)
    thr_sens[key]["min_numerator"] = min(ns)
    thr_sens[key]["gates123_hold"] = bool(
        all(x is not None and x > 0 for x in ls) and all(abs(x) >= LIFT for x in ls) and min(ns) >= MIN_NUM)

# 分布の形（上位1/4が何を意味するか）
dist = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    vr = sorted(r["f2_rnd_r"] for r in P if r.get("f2_rnd_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    dist[str(v)] = {
        "f2_rnd_r": {"n_measurable": len(vr), "coverage": r4(len(vr) / len(P)),
                     "share_exactly_zero": r4(sum(1 for x in vr if x == 0.0) / len(vr)),
                     "q25": r4(q_at(vr, .25)), "q50": r4(q_at(vr, .5)), "q75": r4(q_at(vr, .75))},
        "f2_sga_r": {"n_measurable": len(vs), "coverage": r4(len(vs) / len(P)),
                     "q25": r4(q_at(vs, .25)), "q50": r4(q_at(vs, .5)), "q75": r4(q_at(vs, .75))},
    }


# ────────────────────────────── 判定（prereg の5条件・一つも緩めない） ──────────────────────────────
gates = {
    "1_lift>=0.15_3vintages": g1["gate_lift"],
    "2_min_numerator>=5": g1["gate_min_numerator"],
    "3_sign_stability": g1["gate_sign_stability"],
    "4_sector_MH>=0.15": g2["gate_sector_mh"],
    "5_not_irr_shadow": g3["gate_irr"],
}
survived_prereg = all(gates.values())

out = {
    "generated": time.strftime("%Y-%m-%d"),
    "tool": "night/hist_wd_verify_rnd_sga.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "candidate": CAND,
    "explorer_claim": {
        "maintained_lift": ref["maintained_lift"] if ref else None,
        "2018": (ref["by_vintage"]["2018"] if ref else None),
        "verdict_by_explorer": "合格",
    },
    "reproduction_crosscheck": cross,
    "spot_check_row_level": spot,
    "test1_vintage_sign": g1,
    "test2_sector": g2,
    "test3_irr_shadow": g3,
    "test4_leave_one_company_out": g4,
    "test5_permutation": g5,
    "test6_increment_over_existing_gates": g6,
    "aux_R_regime_split": regime,
    "aux_S_disjoint_subwindow": sub,
    "aux_T_threshold_sensitivity": thr_sens,
    "aux_distribution_shape": dist,
    "prereg_gates": gates,
    "survived_all_prereg_gates": survived_prereg,
    "runtime_sec": round(time.time() - t0, 1),
}

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print(f"[候補] {CAND['label']} / {CAND['population']} / 勝者側")
print(f"[再現] 比較 {cross['compared']} 件 / 不一致 {cross['mismatches']} 件 → {cross['verdict']}")
print(f"[行検算] 直接数え {spot['n_direct']} 社 vs セル {spot['n_cell']} 社 → 不一致 {spot['mismatch']}")
print()
for v in SIGN_VINTAGES:
    c = cells[v]
    print(f"  {v}: n_pop={c['n_pop']} base={c['p_base']} n_group={c['n_group']} k={c['numerator']} "
          f"p={c['p_group']} lift={c['lift']}")
print(f"  維持lift={g1['maintained_lift']}  最小分子={g1['min_numerator']}")
print()
print(f"[1 ビンテージ] 符号={g1['gate_sign_stability']} lift={g1['gate_lift']} 分子={g1['gate_min_numerator']}")
print(f"    群の重なり: 3ビンテージ共通 {g1['group_membership_overlap']['n_intersection_all3']} 社 "
      f"/ 和集合 {g1['group_membership_overlap']['n_union']} 社  jaccard={g1['group_membership_overlap']['jaccard']}")
print(f"    2013/2015: {g1['out_of_sample_2013_2015']}")
for v in SIGN_VINTAGES:
    m = g2["mh"][str(v)]
    print(f"[2 業種] {v}: MH={m['mh_risk_diff']} 層{m['strata_used']}使用/{m['strata_dropped']}破棄 "
          f"群の被覆={m.get('group_coverage_share')}")
for v in SIGN_VINTAGES:
    i = g2["indirect_standardization"][str(v)]
    if i:
        print(f"    間接標準化 {v}: 観測{i['observed_wins']} vs 業種期待{i['expected_wins_sector_leave_self_out']} "
              f"→ 差={i['risk_diff_vs_sector']}")
print(f"    層内置換: p={g2['within_sector_permutation']['p_ge_observed']}")
print(f"[3 irr] 2018: rho={_ic18.get('corr_group_vs_irr')} 直交ヒント={_ic18.get('orthogonal_hint')} "
      f"群のうちirr読解あり={_ic18.get('n_group_within_irr_read')}")
o = g3["orthogonality_is_it_just_small_n"]["2018"]
if o:
    print(f"    同サイズの無作為群が『直交』と呼ばれる確率={o['P_random_group_of_same_size_is_called_orthogonal']}")
print(f"[4 1社] 最悪の維持lift={g4['worst_maintained_lift']} 最大変化={g4['max_abs_delta_from_one_company']} "
      f"条件が崩れる社={g4['n_breaking_any_gate']}")
print(f"[5 置換] 単体p(無制約)={g5['unrestricted_ticker_bundle']['p_ge_observed']} "
      f"/ 層内p={g5['within_sic2']['p_ge_observed']}")
print(f"    探索全体: {g5['family_wise_from_explorer']['n_tests_in_search']}検定・"
      f"帰無で1本以上合格する確率={g5['family_wise_from_explorer']['P_at_least_one_pass_under_null_L5']}")
print(f"    帰無の最大統計量 p95={_nullmax['p95']} p99={_nullmax['p99']} ← 観測{g1['maintained_lift']}")
print(f"[6 増分] 脚単独の最良={g6['best_leg_maintained_lift']} 増分={g6['increment_over_best_leg']}")
for v in SIGN_VINTAGES:
    s = g6["survivors"][str(v)]["all_three"]
    print(f"    {v} 既存関門の生存者内: n群={s['n_group_among_survivors']} 増分lift={s['incremental_lift']}")
if "per_vintage" in regime:
    for k, r_ in regime["per_vintage"].items():
        print(f"[R レジーム] {k}: base={r_['p_base']} 群={r_['p_group']} lift={r_['lift']} (n群={r_['n_group']})")
print()
print("[事前登録の5条件] " + " / ".join(f"{k}:{'○' if v else '×'}" for k, v in gates.items()))
print(f"[判定] {'全条件を満たしたまま（落とせなかった）' if survived_prereg else '不合格＝落ちた'}")
print(f"→ {DEST}  ({out['runtime_sec']}s)")
