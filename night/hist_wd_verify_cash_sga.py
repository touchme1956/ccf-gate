#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_cash_sga.py — 候補「f2_cash_r[上位1/4] ∧ f2_sga_r[中央値以下]（勝者側・P_full）」を**潰しにかかる**検証。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json          … 5ビンテージ統合パネル（唯一の真実）
          out/hist_wd_win_pair.json       … 探索側の答え（**再現の突合せ相手**。信じる前に検算する）
          out/retro_returns_{2013_all,2016,2017,2018}.json … 部分窓リターンの導出用（同じ終端日）
          out/retro_monthly_2018_2026.json … レジーム分割（2018-07→2022-07 / 2022-07→2026-08）
          out/retro_sic.json               … 業種の記述（層が同質か・記述を見ないと判らない）
出力    : out/hist_wd_verify_cash_sga.json

────────────────────────────────────────────────────────────
この道具の立場
────────────────────────────────────────────────────────────
**反証が仕事であって確認ではない。** 候補に有利な数字を探さない。
prereg の5条件（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を**一つも緩めない**。
線を緩めた数字を出すときは必ず `事前登録の外・診断専用` と明記し、合否には数えない。

「測れない」と「不合格」を区別する。f2_ 特徴量は 2013/2015 に構造的に存在しない＝**判定不能**であって
不合格ではない（ただし『判定不能を合格の材料にもしない』）。

変数の定義（retro_features2.py の実装そのもの。混同すると結論を誤る）:
  f2_cash_r = 現金及び現金同等物 ÷ **総資産**（売上比ではない）
  f2_sga_r  = 販管費 ÷ 売上。**合算タグ(SellingGeneralAndAdministrativeExpense)のみ**を読むので、
              販売費と一般管理費を**分けて報告する社は欠測**（CLAUDE.md が記録する ADSK/ABNB/MELI/PCTY 型）。
              ＝この脚は「販管費が低い」ではなく「**合算で報告していて、かつその値が中央値以下**」を意味する。

────────────────────────────────────────────────────────────
当てる6つ（依頼どおり。1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 ビンテージ符号  : 2016/2017/2018 で符号が反転しないか。**アンカー年の膨らみ**（2018=0.31 vs 2017=0.18）
                    を数字で出す。群のティッカーの重なりと outcome 窓の重なりも測る
                    （同じ終端日ゆえ 2016窓の8.09/10.09 は 2018窓そのもの＝3つの証拠ではない）。
                    2013/2015 は f2_ が無いので判定不能（理由を書く）。
2 業種調整        : 同一 sic2 内で残るか。MH＋層内置換＋業種1つずつ除去＋層ごとの分解。
                    **MHが群の何%を覆っているか**を必ず出す（層を落とすほど「調整した」の意味が薄れる）。
                    層を落とさない間接標準化も併せて出す。
3 irr の影        : irr>=70 層内で残るか・irr と直交か。**通した試験に検出力があるか**を別に測る。
4 1社の影響       : ティッカーを1社ずつ**パネルごと**抜いて、閾値・母集団・群・条件を全部作り直す。
5 置換            : outcome の束をティッカーごと置換（ビンテージ間相関を保つ帰無）2000回。
                    この候補単体の p と、探索全体の多重検定の値札の両方を出す。
6 既存の関門との重複: 事業の収縮 / 利払カバー / 質実証 の生存者の中でも残るか（＝増分）。
                    脚単独との増分も出す。

この候補に固有の追加検査（依頼の6つの上に置く。合否には prereg の線しか使わない）:
  M 可測性の偏り  : sga_r は分割報告社が構造的に欠測。**群は必ず可測集合の部分集合**なので、
                    母集団を分母にした lift は「形質を持つ」と「そもそも測れる」を混ぜている。
                    可測集合を分母にした lift（探索側の lift_meas）を並べる。
  Z 群の正体      : 現金/総資産が高く販管費/売上が低い社とは何か。業種記述・規模・粗利で見る。
"""
import json, os, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
PAIR = os.path.join(OUT, "hist_wd_win_pair.json")
DEST = os.path.join(OUT, "hist_wd_verify_cash_sga.json")

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
    "legs": [("f2_cash_r", "上位1/4"), ("f2_sga_r", "中央値以下")],
    "label": "f2_cash_r[上位1/4] ∧ f2_sga_r[中央値以下]",
    "brief_says": {"n_group_2018": 48, "numerator_2018": 25, "lift_2018": 0.3107,
                   "thr_cash_2018": 0.1622, "thr_sga_2018": 0.1756,
                   "explorer_verdict": "不合格（業種調整）"},
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


def med(vals):
    v = sorted(x for x in vals if x is not None)
    return None if not v else v[len(v) // 2]


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

_sicdesc = {}
try:
    for r in json.load(open(os.path.join(OUT, "retro_sic.json"), encoding="utf-8"))["rows"]:
        _sicdesc[r["ticker"]] = {"sic": r.get("sic"), "sicDesc": r.get("sicDesc"), "sic2": r.get("sic2")}
except Exception:
    pass


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
        thrs[var] = {"cut": cut, "threshold": r4(thr), "n_measurable": nm}
    if any(t["threshold"] is None for t in thrs.values()):
        return None
    preds = {}
    for var, cut in legs:
        thr_raw, _ = threshold(P, var, cut)
        preds[var] = cut_pred(cut, thr_raw)
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
        "n_measurable_both": n_m, "k_measurable_both": k_m, "p_measurable": r4(p_m),
        "lift_meas": (None if (p_g is None or p_m is None) else r4(p_g - p_m)),
        "_group_rows": b["group"], "_pop_rows": b["pop"], "_meas_rows": b["meas"],
        "_thresholds": b["thresholds"],
    }


def strip(c):
    return {k: v for k, v in c.items() if not k.startswith("_")} if c else None


# ────────────────────────────── 0. 再現と突合せ（信じる前に検算する） ──────────────────────────────
cells = {v: cell(v, CAND["population"], CAND["legs"]) for v in SIGN_VINTAGES}

ref = None
for e in pair_out["all_pairs"]:
    if e["label"] == CAND["label"] and e["population"] == CAND["population"]:
        ref = e
        break

_lifts = [cells[v]["lift"] for v in SIGN_VINTAGES]
_nums = [cells[v]["numerator"] for v in SIGN_VINTAGES]
_lifts_meas = [cells[v]["lift_meas"] for v in SIGN_VINTAGES]
mine_summary = {
    "maintained_lift": r4(min(abs(x) for x in _lifts)),
    "maintained_lift_meas": r4(min(abs(x) for x in _lifts_meas)),
    "min_numerator_161718": min(_nums),
    "sign": 1 if all(x > 0 for x in _lifts) else (-1 if all(x < 0 for x in _lifts) else 0),
}
cross = {"found_in_explorer_all_pairs": ref is not None, "compared": 0, "mismatches": 0, "detail": []}
if ref:
    for k in ("maintained_lift", "maintained_lift_meas", "min_numerator_161718", "sign"):
        cross["compared"] += 1
        if mine_summary[k] != ref.get(k):
            cross["mismatches"] += 1
            cross["detail"].append({"key": k, "mine": mine_summary[k], "explorer": ref.get(k)})
    cross["explorer_entry"] = ref
cross["mine"] = mine_summary
cross["verdict"] = ("一致（探索側の数字は再現できる。以降の検証はこれが通ったうえでの話）"
                    if cross["mismatches"] == 0 else "**不一致＝結論を書いてはいけない**")

# 依頼文が名指しした 2018 の数字との突合せ
_c18 = cells[2018]
cross["vs_brief"] = {
    "brief": CAND["brief_says"],
    "mine": {"n_group_2018": _c18["n_group"], "numerator_2018": _c18["numerator"],
             "lift_2018": _c18["lift"],
             "thr_cash_2018": _c18["_thresholds"]["f2_cash_r"]["threshold"],
             "thr_sga_2018": _c18["_thresholds"]["f2_sga_r"]["threshold"]},
}
cross["vs_brief"]["match"] = all(
    cross["vs_brief"]["mine"][k] == CAND["brief_says"][k]
    for k in ("n_group_2018", "numerator_2018", "lift_2018", "thr_cash_2018", "thr_sga_2018"))

# 行を直接数えるスポット検算（ビット演算に頼らないことの証明）
_thr_c = _c18["_thresholds"]["f2_cash_r"]["threshold"]
_thr_s = _c18["_thresholds"]["f2_sga_r"]["threshold"]
_direct = [r for r in pop_rows(2018, "P_full")
           if r.get("f2_cash_r") is not None and r.get("f2_sga_r") is not None
           and r["f2_cash_r"] >= _thr_c and r["f2_sga_r"] <= _thr_s]
spot = {"vintage": 2018, "n_direct": len(_direct), "n_cell": _c18["n_group"],
        "mismatch": 0 if len(_direct) == _c18["n_group"] else 1,
        "tickers": sorted(r["ticker"] for r in _direct)}


# ────────────────────────────── 1. ビンテージ符号 ──────────────────────────────
g1 = {"per_vintage": {str(v): strip(cells[v]) for v in SIGN_VINTAGES}}
g1["signs_all_positive"] = all(x is not None and x > 0 for x in _lifts)
g1["maintained_lift"] = mine_summary["maintained_lift"]
g1["min_numerator"] = mine_summary["min_numerator_161718"]
g1["gate_sign_stability"] = g1["signs_all_positive"]
g1["gate_lift"] = g1["maintained_lift"] >= LIFT
g1["gate_min_numerator"] = g1["min_numerator"] >= MIN_NUM

# 1a アンカー年の膨らみ（依頼が名指しした論点）
_l = {v: cells[v]["lift"] for v in SIGN_VINTAGES}
g1["anchor_year_inflation"] = {
    "lift_by_vintage": {str(v): _l[v] for v in SIGN_VINTAGES},
    "max_over_min_ratio": r4(max(_l.values()) / min(_l.values())),
    "argmax_vintage": max(_l, key=lambda v: _l[v]),
    "lift_2018_over_2017": r4(_l[2018] / _l[2017]),
    "base_rate_by_vintage": {str(v): cells[v]["p_base"] for v in SIGN_VINTAGES},
    "p_group_by_vintage": {str(v): cells[v]["p_group"] for v in SIGN_VINTAGES},
    "how_to_read": ("同じ社をほぼ同じ群として3回測っているのに lift が 0.21/0.18/0.31 と動く。"
                    "母集団の勝率(base)は窓が短くなるほど下がる(0.2431→0.2334→0.2101)ので、"
                    "**分母が縮むだけで lift は伸びる**。2018 の 0.31 は『指標が強い年』ではなく"
                    "『窓が短くて base が低い年』かもしれない——それを切り分けるのが下の disjoint subwindow。"),
}

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
                    "**同じ社を3回数えただけ**。prereg の independence_warning が指すのはこれ。"),
}

ret_years = {2013: 13.09, 2015: 11.10, 2016: 10.09, 2017: 9.09, 2018: 8.09}
g1["outcome_window_overlap"] = {
    "years": {str(v): ret_years[v] for v in SIGN_VINTAGES},
    "shared_tail_years": 8.09,
    "share_of_2016_window_shared_with_2018": r4(8.09 / 10.09),
    "share_of_2017_window_shared_with_2018": r4(8.09 / 9.09),
    "how_to_read": "窓は全部 2026 で終わる。2016 の 10.09 年のうち 8.09 年は 2018 の窓そのもの＝同じ8年を3回測っている。",
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


# ────────────────────────────── M. 可測性の偏り（この候補に固有・重い） ──────────────────────────────
def measurability(v):
    c = cells[v]
    P = c["_pop_rows"]
    meas_ids = set(id(r) for r in c["_meas_rows"])
    unmeas = [r for r in P if id(r) not in meas_ids]
    per_leg = {}
    for var, cut in CAND["legs"]:
        m = [r for r in P if r.get(var) is not None]
        u = [r for r in P if r.get(var) is None]
        per_leg[var] = {
            "n_measurable": len(m), "coverage": r4(len(m) / len(P)),
            "p_win_measurable": r4(rate(sum(1 for r in m if r.get("win")), len(m))),
            "n_unmeasurable": len(u),
            "p_win_unmeasurable": r4(rate(sum(1 for r in u if r.get("win")), len(u))),
        }
    return {
        "n_pop": len(P),
        "n_measurable_both": len(c["_meas_rows"]),
        "coverage_both": r4(len(c["_meas_rows"]) / len(P)),
        "p_win_measurable_both": c["p_measurable"],
        "n_unmeasurable": len(unmeas),
        "p_win_unmeasurable": r4(rate(sum(1 for r in unmeas if r.get("win")), len(unmeas))),
        "measurability_lift": r4((c["p_measurable"] or 0) - (rate(sum(1 for r in unmeas if r.get("win")), len(unmeas)) or 0)),
        "lift_vs_population": c["lift"],
        "lift_vs_measurable": c["lift_meas"],
        "share_of_lift_from_measurability": (
            None if not c["lift"] else r4(1 - (c["lift_meas"] / c["lift"]))),
        "per_leg": per_leg,
    }


gM = {"per_vintage": {str(v): measurability(v) for v in SIGN_VINTAGES}}
gM["maintained_lift_vs_measurable"] = mine_summary["maintained_lift_meas"]
gM["gate_lift_would_hold_on_measurable_baseline"] = mine_summary["maintained_lift_meas"] >= LIFT
gM["how_to_read"] = (
    "**群は必ず可測集合の部分集合**なので、母集団を分母にした lift は『形質を持つ』と『そもそも測れる』を混ぜている。"
    "f2_sga_r は**販管費を合算タグで報告する社しか読めない**（分割報告社は欠測）ので、可測であること自体が"
    "会社の型（開示習慣・業種）を選んでいる。prereg の文言は母集団を分母にすると読めるので"
    "**合否は母集団基準のまま**にするが、可測基準の lift を並べておく——"
    "この差が大きいなら、指標が分けたのではなく『測れる社の集合』が分けている。")

# 業種と可測性の関係（欠測が業種で決まるなら、可測性は業種の代理）
def meas_by_sector(v):
    c = cells[v]
    P = c["_pop_rows"]
    meas_ids = set(id(r) for r in c["_meas_rows"])
    st = defaultdict(lambda: [0, 0])
    for r in P:
        s = r.get("sic2")
        if not s:
            continue
        st[s][0] += 1
        if id(r) in meas_ids:
            st[s][1] += 1
    rows = [{"sic2": s, "n": n, "coverage": r4(k / n)} for s, (n, k) in st.items() if n >= 10]
    rows.sort(key=lambda x: x["coverage"])
    return {"lowest5": rows[:5], "highest5": rows[-5:],
            "coverage_spread": r4(rows[-1]["coverage"] - rows[0]["coverage"]) if rows else None}


gM["coverage_by_sector_2018"] = meas_by_sector(2018)


# ────────────────────────────── 2. 業種調整 ──────────────────────────────
def mh(v, pop, legs, rows_src=None, win_of=None, drop_sic=None, min_n=3):
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
    used = drop = covered = 0
    for s, (n1, k1, n0, k0) in st.items():
        if n1 < min_n or n0 < min_n:
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


def indirect_std(v, pop, legs, reference="pop"):
    """層を1つも落とさない業種調整。群の各社を『同じ sic2 の他社の勝率』と比べる（自分は分母から抜く）。

    reference='pop'  … 比較相手は母集団の同業（prereg の文言どおりの分母）
    reference='meas' … 比較相手は**両脚が可測な**同業のみ。群は必ず可測集合の部分集合なので、
                       こちらは『業種』と『そもそも測れるか』の**両方**を同時に外した見方になる。
    """
    b = build_group(v, pop, legs)
    if b is None:
        return None
    ref_rows = b["meas"] if reference == "meas" else b["pop"]
    bysic = defaultdict(lambda: [0, 0])
    for r in ref_rows:
        s = r.get("sic2")
        if not s:
            continue
        bysic[s][0] += 1
        if r.get("win"):
            bysic[s][1] += 1
    obs = exp_self = exp_ext = 0.0
    used = no_sic = 0
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
    return {"reference": reference, "n_group_with_sic2": used, "n_group_without_sic2": no_sic,
            "observed_wins": int(obs),
            "expected_wins_sector": r4(exp_self),
            "expected_wins_sector_leave_self_out": r4(exp_ext),
            "risk_diff_vs_sector": r4((obs - exp_ext) / used),
            "smr": r4(obs / exp_ext) if exp_ext > 0 else None}


g2["indirect_standardization"] = {str(v): indirect_std(v, CAND["population"], CAND["legs"])
                                  for v in SIGN_VINTAGES}
_ind = [g2["indirect_standardization"][str(v)]["risk_diff_vs_sector"] for v in SIGN_VINTAGES]
g2["indirect_standardization_maintained"] = r4(min(abs(x) for x in _ind))
g2["indirect_standardization_gate_holds"] = g2["indirect_standardization_maintained"] >= LIFT

# 2a-3 業種と可測性を**同時に**外す（この候補に固有の二重交絡）
g2["indirect_standardization_within_measurable"] = {
    str(v): indirect_std(v, CAND["population"], CAND["legs"], reference="meas") for v in SIGN_VINTAGES}
_ind2 = [g2["indirect_standardization_within_measurable"][str(v)]["risk_diff_vs_sector"] for v in SIGN_VINTAGES]
g2["indirect_standardization_within_measurable_maintained"] = r4(min(abs(x) for x in _ind2))
g2["indirect_standardization_within_measurable_gate_holds"] = (
    g2["indirect_standardization_within_measurable_maintained"] >= LIFT)
g2["two_confounders_removed_note"] = (
    "**事前登録の外・診断専用**（prereg の分母は母集団なので合否には数えない）。"
    "群は必ず可測集合の部分集合、かつ業種に偏っている。この二つを同時に外して"
    "『同じ業種の・同じく両脚が測れる社』とだけ比べたときに何が残るかを見る。"
    "ここでほぼゼロなら、分けていたのは形質ではなく**業種と開示習慣**。")
g2["indirect_standardization_note"] = (
    "MHは各層 n>=3 の両側を要求するので層を落とす。間接標準化は**群の全社**を使うので"
    "『MHが群の一部しか見ていない』問題が起きない。**層を落とさない業種調整**。")

# 2b 層内置換（ティッカー束・sic2 内でのみ入れ替える＝業種構成を保つ帰無）
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
        m = {str(v): mh(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        gsec = all((x and x["mh_risk_diff"] is not None and abs(x["mh_risk_diff"]) >= LIFT) for x in m.values())
        same = all(x > 0 for x in ls)
        out.append({"sic2_dropped": s, "sicDesc_example": None,
                    "n_group_2018": cs[2018]["n_group"],
                    "maintained_lift": r4(min(abs(x) for x in ls)),
                    "min_numerator": min(ns),
                    "mh_by_vintage": {k: (x["mh_risk_diff"] if x else None) for k, x in m.items()},
                    "gates123_hold": bool(same and min(abs(x) for x in ls) >= LIFT and min(ns) >= MIN_NUM),
                    "gate_sector_holds": gsec})
    return out


_loo_sec = loo_sector()
g2["leave_one_sector_out"] = sorted(
    [x for x in _loo_sec if x.get("maintained_lift") is not None],
    key=lambda x: (x["maintained_lift"] if x["maintained_lift"] is not None else 9))[:12]
g2["leave_one_sector_out_all_gates123_hold"] = all(
    x.get("gates123_hold", False) for x in _loo_sec if "gates123_hold" in x)
g2["leave_one_sector_out_breakers"] = [
    {"sic2": x["sic2_dropped"], "maintained_lift": x["maintained_lift"], "min_numerator": x["min_numerator"]}
    for x in _loo_sec if x.get("gates123_hold") is False]


def sector_profile(v):
    c = cells[v]
    cnt = Counter(r.get("sic2") for r in c["_group_rows"])
    top = cnt.most_common(6)
    P = c["_pop_rows"]
    base = c["p_base"]
    out = {"n_group": c["n_group"], "sic2_top6": top,
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
            "n_strata_entering": len(terms)}


g2["mh_decomposition"] = {str(v): mh_decompose(v) for v in SIGN_VINTAGES}

_ent = {v: [t["sic2"] for t in g2["mh_decomposition"][str(v)]["strata_entering_MH"]] for v in SIGN_VINTAGES}
_all_ent = sorted({s for v in SIGN_VINTAGES for s in _ent[v]})
g2["mh_excluding_each_entering_stratum"] = {
    s: {str(v): mh(v, CAND["population"], CAND["legs"], drop_sic=s) for v in SIGN_VINTAGES} for s in _all_ent}
g2["mh_gate_survives_excluding_each_stratum"] = {
    s: all((m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT)
           for m in g2["mh_excluding_each_entering_stratum"][s].values())
    for s in _all_ent}

g2["mh_min_stratum_size_sensitivity"] = {
    "note": "**事前登録の外・診断専用**。探索側の規則は各層 n>=3。層の最小サイズを動かすと MH がどう動くか。",
    **{f"min_n={k}": {str(v): mh(v, CAND["population"], CAND["legs"], min_n=k) for v in SIGN_VINTAGES}
       for k in (3, 4, 5, 6)},
}

# 2h MH を担いでいる層は同質か（層の中身を記述で見ないと『業種調整』の意味が判らない）
def stratum_members(v, s):
    return sorted(
        [{"ticker": r["ticker"], "sic": _sicdesc.get(r["ticker"], {}).get("sic"),
          "sicDesc": _sicdesc.get(r["ticker"], {}).get("sicDesc"),
          "tr_cagr": r.get("tr_cagr"), "win": bool(r.get("win"))}
         for r in cells[v]["_group_rows"] if r.get("sic2") == s], key=lambda x: x["ticker"])


_top_stratum = {v: (g2["mh_decomposition"][str(v)]["strata_entering_MH"][0]["sic2"]
                    if g2["mh_decomposition"][str(v)]["strata_entering_MH"] else None)
                for v in SIGN_VINTAGES}
g2["mh_top_stratum_is_heterogeneous"] = {
    "note": ("MH が最も重く依存している層の**中身**を並べる。2桁 sic2 は粗い括りなので、"
             "同じ層に別の事業が同居しているなら、そこでの『業種調整』は業種を調整していない。"),
    "top_stratum_by_vintage": {str(v): _top_stratum[v] for v in SIGN_VINTAGES},
    "members": {str(v): stratum_members(v, _top_stratum[v]) for v in SIGN_VINTAGES if _top_stratum[v]},
}

# 2i 群を支配する業種の中で、この組は何を足しているか（＝業種の言い換えでないか）
_dom = Counter(r.get("sic2") for r in cells[2018]["_group_rows"]).most_common(1)[0][0]


def within_dominant(v, s):
    c = cells[v]
    sec = [r for r in c["_pop_rows"] if r.get("sic2") == s]
    gin = [r for r in c["_group_rows"] if r.get("sic2") == s]
    if not sec or not gin:
        return None
    bs = rate(sum(1 for r in sec if r.get("win")), len(sec))
    kg = sum(1 for r in gin if r.get("win"))
    return {"sic2": s, "n_sector": len(sec), "p_sector": r4(bs),
            "share_of_group_in_this_sector": r4(len(gin) / c["n_group"]),
            "share_of_pop_in_this_sector": r4(len(sec) / c["n_pop"]),
            "lift_of_sector_alone_vs_population": r4(bs - c["p_base"]),
            "n_group_in_sector": len(gin), "k": kg, "p_group_in_sector": r4(rate(kg, len(gin))),
            "lift_of_pair_within_sector": r4(rate(kg, len(gin)) - bs)}


g2["within_dominant_sector"] = {"sic2": _dom,
                                "per_vintage": {str(v): within_dominant(v, _dom) for v in SIGN_VINTAGES}}
_wd = [g2["within_dominant_sector"]["per_vintage"][str(v)]["lift_of_pair_within_sector"]
       for v in SIGN_VINTAGES]
g2["within_dominant_sector"]["maintained_lift_within_sector"] = r4(min(abs(x) for x in _wd))
g2["within_dominant_sector"]["how_to_read"] = (
    "群を最も多く占める業種の中だけで、この組が何を足しているかを見る。"
    "**その業種そのものが母集団に対して大きく勝っている**のに、業種の中では組がほとんど足していないなら、"
    "この組は形質ではなく**業種の言い換え**。")

g2["group_members_with_industry"] = {
    str(v): sorted(
        [{"ticker": r["ticker"], "sic2": r.get("sic2"),
          "sicDesc": _sicdesc.get(r["ticker"], {}).get("sicDesc"),
          "cash_r": r.get("f2_cash_r"), "sga_r": r.get("f2_sga_r"),
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
    sel = [r for r in R if r.get("f2_cash_r") is not None and r.get("f2_sga_r") is not None]
    xs = [1.0 if id(r) in gset else 0.0 for r in sel]
    ys = [float(r["irr"]) for r in sel]
    rho = spearman(xs, ys) if len(xs) >= 20 else None
    res["n_measurable_with_irr"] = len(sel)
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
         and r.get("f2_cash_r") is not None and r.get("f2_sga_r") is not None]
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
g3["irr_enrichment"] = {
    "note": ("gate5 は『直交 or 層内で残る』の**or**なので、直交でなくても層内で残れば通る。"
             "だが『直交でない』ということは群が irr の高い社に偏っているということ＝"
             "**irr の影である可能性そのものは否定されていない**。偏りの大きさを実数で出す。"),
    "2018": {
        "n_pop_with_irr_read_and_measurable": _ic18.get("n_measurable_with_irr"),
        "n_group_with_irr_read": _ic18.get("n_group_within_irr_read"),
        "corr_group_vs_irr": _ic18.get("corr_group_vs_irr"),
        "share_irr_ge70_in_group": None, "share_irr_ge70_in_pop_with_irr": None,
    },
    "2016_2017": "irr の読解がゼロ＝**判定不能**（gate5 は 2018 の1ビンテージだけで決まっている）",
}
_c18g = cells[2018]["_group_rows"]
_g_irr = [r for r in _c18g if r.get("irr") is not None]
_p_irr = [r for r in cells[2018]["_pop_rows"] if r.get("irr") is not None]
if _g_irr:
    g3["irr_enrichment"]["2018"]["share_irr_ge70_in_group"] = r4(
        sum(1 for r in _g_irr if r["irr"] >= 70) / len(_g_irr))
if _p_irr:
    g3["irr_enrichment"]["2018"]["share_irr_ge70_in_pop_with_irr"] = r4(
        sum(1 for r in _p_irr if r["irr"] >= 70) / len(_p_irr))

SEMI_SIC2 = {"35", "36"}


def semi_split(v):
    c = cells[v]
    P = c["_pop_rows"]
    gset = set(id(r) for r in c["_group_rows"])
    out = {}
    for tag, sel in (("in_35_36", lambda r: r.get("sic2") in SEMI_SIC2),
                     ("outside_35_36", lambda r: r.get("sic2") not in SEMI_SIC2 and r.get("sic2"))):
        sub = [r for r in P if sel(r)]
        g = [r for r in sub if id(r) in gset]
        b = rate(sum(1 for r in sub if r.get("win")), len(sub))
        kg = sum(1 for r in g if r.get("win"))
        out[tag] = {"n_sub": len(sub), "p_sub": r4(b), "n_group": len(g), "k_group": kg,
                    "p_group": r4(rate(kg, len(g))),
                    "lift_within": (None if not g else r4(rate(kg, len(g)) - b))}
    return out


g3["semiconductor_complex_split"] = {str(v): semi_split(v) for v in SIGN_VINTAGES}

_win_union = {}
for v in SIGN_VINTAGES:
    for r in cells[v]["_group_rows"]:
        if r.get("win"):
            _win_union.setdefault(r["ticker"], set()).add(v)
g3["distinct_winning_companies_carrying_the_finding"] = {
    "n_distinct": len(_win_union),
    "n_person_times": sum(cells[v]["numerator"] for v in SIGN_VINTAGES),
    "detail": sorted([{"ticker": t, "vintages": sorted(vs),
                       "sicDesc": _sicdesc.get(t, {}).get("sicDesc"),
                       "sic2": _sicdesc.get(t, {}).get("sic2")} for t, vs in _win_union.items()],
                     key=lambda x: x["ticker"]),
}


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
                    "gate_lift": ml >= LIFT, "gate_min_num": mn >= MIN_NUM,
                    "gate_sign": same, "gate_sector": gsec,
                    "all_gates_1_to_4_hold": bool(same and ml >= LIFT and mn >= MIN_NUM and gsec)})
    return res


loo = loo_ticker()
meas_loo = [x for x in loo if "maintained_lift" in x]
g4 = {
    "n_tickers_tested": len(loo),
    "worst_maintained_lift": r4(min(x["maintained_lift"] for x in meas_loo)) if meas_loo else None,
    "best_maintained_lift": r4(max(x["maintained_lift"] for x in meas_loo)) if meas_loo else None,
    "max_abs_delta_from_one_company": r4(max(abs(x["delta_vs_full"]) for x in meas_loo)) if meas_loo else None,
    "n_breaking_gates_1_to_3": sum(1 for x in meas_loo
                                   if not (x["gate_sign"] and x["gate_lift"] and x["gate_min_num"])),
    "n_breaking_any_gate_incl_sector": sum(1 for x in meas_loo if not x["all_gates_1_to_4_hold"]),
    "breakers_gates_1_to_3": [x for x in meas_loo
                              if not (x["gate_sign"] and x["gate_lift"] and x["gate_min_num"])],
    "top10_most_influential": sorted(meas_loo, key=lambda x: x["maintained_lift"])[:10],
    "how_to_read": ("1社をパネルごと抜いて閾値・母集団・群・条件を全部作り直す。"
                    "1社で条件が崩れるなら、それは発見ではなく1社の話。"
                    "**この候補は業種調整に元から落ちているので、sector を含む列は全社で False になる**"
                    "——1社の影響として意味があるのは gates 1-3 の側。"),
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
                    "n_winners_to_remove_to_break": need})
    return out


g4["sequential_winner_removal"] = sequential_drop()


# ────────────────────────────── 5. 置換 ──────────────────────────────
_nullmax = pair_out["must_report_before_verdict"]["false_positive_rate"]["null_distribution_of_max_statistic"]
g5 = {
    "unrestricted_ticker_bundle": perm_res["unrestricted"],
    "within_sic2": perm_res["within_sic2"],
    "family_wise_from_explorer": {
        "n_tests_in_search": pair_out["must_report_before_verdict"]["false_positive_rate"]["n_tests_in_procedure"],
        "P_at_least_one_pass_under_null_L5":
            pair_out["must_report_before_verdict"]["false_positive_rate"]["P_at_least_one_pass_by_level"]["L5"],
        "null_max_statistic_p50": _nullmax["p50"],
        "null_max_statistic_p90": _nullmax["p90"],
        "null_max_statistic_p95": _nullmax["p95"],
        "null_max_statistic_p99": _nullmax["p99"],
        "note": ("探索側が同じ帰無で測った値札。この候補の維持lift をこの分布の中に置くのが正しい読み方"
                 "——**単体のp値は『この1本だけを検定したなら』の話**で、実際は数千本から選ばれている。"),
    },
}
g5["observed_vs_null_max_distribution"] = {
    "observed_maintained_lift": g1["maintained_lift"],
    "null_max_p50": _nullmax["p50"], "null_max_p90": _nullmax["p90"],
    "null_max_p95": _nullmax["p95"], "null_max_p99": _nullmax["p99"],
    "position": ("p99 以上" if g1["maintained_lift"] >= _nullmax["p99"] else
                 "p95 と p99 の間" if g1["maintained_lift"] >= _nullmax["p95"] else
                 "p90 と p95 の間" if g1["maintained_lift"] >= _nullmax["p90"] else
                 "p50 と p90 の間" if g1["maintained_lift"] >= _nullmax["p50"] else "p50 未満"),
    "family_wise_p_lower_bound": (
        ">0.5（観測 {} が帰無の最大統計量の中央値 {} を下回る）".format(g1["maintained_lift"], _nullmax["p50"])
        if g1["maintained_lift"] < _nullmax["p50"] else
        "<=0.5（観測が帰無の最大統計量の中央値以上）"),
    "how_to_read": ("探索は2840検定。帰無でも『符号が揃ったうえでの3ビンテージ最小|lift|』の**最大値**が"
                    f"中央 {_nullmax['p50']} まで出る。観測 {g1['maintained_lift']} がこの分布の"
                    "どこに座るかが、多重検定を織り込んだ本当の位置。"
                    "**単体p=0.0005 は『この1本だけを検定したなら』の話で、実際は2840本から選んでいる。**"),
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
    ex = [r for r in c["_group_rows"] if gate_flags(r)["shrink"] or gate_flags(r)["fin_bad"]]
    out["group_members_already_excluded_by_gates"] = {
        "n": len(ex), "share_of_group": r4(len(ex) / c["n_group"]) if c["n_group"] else None,
        "tickers": sorted(r["ticker"] for r in ex), "n_group": c["n_group"]}
    return out


g6 = {"survivors": {str(v): survivors_analysis(v) for v in SIGN_VINTAGES}}
g6["proxy_warning"] = ("財務キルは nde>4 だが nde はパネルに無い。**intcov<5 は代理であって同じ線ではない**"
                       "（CLAUDE.md の retro_breaker_test が使った線）。intcov が null の社は"
                       "『利息がない＝負担なし』として落とさない（欠測を不合格と読まない）。")


def leg_alone(var, cut):
    res = {}
    for v in SIGN_VINTAGES:
        res[str(v)] = strip(cell(v, CAND["population"], [(var, cut)]))
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
g6["best_leg_alone_would_pass_lift_gate"] = _best_leg >= LIFT

_inc = {v: g6["survivors"][str(v)]["all_three"] for v in SIGN_VINTAGES}
_incl = [_inc[v]["incremental_lift"] for v in SIGN_VINTAGES]
_incn = [_inc[v]["k"] for v in SIGN_VINTAGES]
g6["prereg_line_applied_to_the_increment"] = {
    "by_vintage": {str(v): {"n_group": _inc[v]["n_group_among_survivors"], "numerator": _inc[v]["k"],
                            "incremental_lift": _inc[v]["incremental_lift"]} for v in SIGN_VINTAGES},
    "maintained_incremental_lift": (r4(min(abs(x) for x in _incl)) if all(x is not None for x in _incl) else None),
    "min_numerator": min(_incn),
    "sign_stable": all(x is not None and x > 0 for x in _incl),
    "gate_lift_holds": bool(all(x is not None and abs(x) >= LIFT for x in _incl)),
    "gate_min_numerator_holds": bool(min(_incn) >= MIN_NUM),
    "how_to_read": ("勝者側の候補が実務で使われるのは『既存の関門を通った社の中で選ぶ』とき。"
                    "そこで prereg の線（0.15・分子5）をそのまま当てる。ここで落ちるなら、"
                    "**門の中では働かない**——母集団全体でしか働かない指標だということ。"),
}


# ────────────────────────────── Z. 群の正体 ──────────────────────────────
def profile_group(v):
    c = cells[v]
    G = c["_group_rows"]
    P = c["_pop_rows"]

    def stat(rows, key):
        vals = [r.get(key) for r in rows if r.get(key) is not None]
        return {"n": len(vals), "median": r4(med(vals))}

    keys = ["f2_cash_r", "f2_sga_r", "f2_gm", "f2_opm", "f2_rnd_r", "f2_cagr5",
            "f2_intcov", "f2_netiss_r", "f2_gw_r", "size_rev", "per", "hv_pe_pct"]
    return {
        "group": {k: stat(G, k) for k in keys},
        "population": {k: stat(P, k) for k in keys},
        "share_quality_in_group": r4(rate(sum(1 for r in G if r.get("P_quality")), len(G))),
        "share_quality_in_pop": r4(rate(sum(1 for r in P if r.get("P_quality")), len(P))),
        "median_tr_cagr_group": r4(med([r.get("tr_cagr") for r in G])),
        "median_tr_cagr_pop": r4(med([r.get("tr_cagr") for r in P])),
        "p_destroy_group": r4(rate(sum(1 for r in G if r.get("destroy")), len(G))),
        "p_destroy_pop": r4(rate(sum(1 for r in P if r.get("destroy")), len(P))),
    }


gZ = {"per_vintage": {str(v): profile_group(v) for v in SIGN_VINTAGES},
      "how_to_read": ("『現金/総資産が高く販管費/売上が低い』社とは何か。"
                      "R&D比・粗利・規模・PER分位を並べて、これが業種や事業モデルの言い換えでないかを見る。"
                      "**中央値リターンも出す**——勝者率(P(>=15%))が上がっても中央値が上がっていないなら、"
                      "分けているのは中心ではなく右裾。")}


# ─────────────── 補助R（事前登録の外・診断専用）: レジーム分割 ───────────────
regime = {"status": "未実施"}
MON = os.path.join(OUT, "retro_monthly_2018_2026.json")
if os.path.exists(MON):
    mon = json.load(open(MON, encoding="utf-8"))
    SPLIT = 1656648000  # 2022-07-01 前後の月末を選ぶための錨

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
            "median_cagr_group": r4(med([g for _, g in grp_v])),
            "median_cagr_pop": r4(med([g for _, g in pop_v])),
        }
    regime["how_to_read"] = ("2018年群を、その8年を前半4年と後半4年に割って測る。"
                             "前半でリフトが消え後半だけに出るなら、それは指標ではなく相場の記録。")

# ─────────────── 補助S（事前登録の外・診断専用）: 部分窓分解 ───────────────
sub = {"note": ("**事前登録の外・診断専用**。同じ終端日ゆえ tr_total の比で部分窓が厳密に出る。"
                "2016群を『2018窓と重ならない2年』だけで裁く＝ビンテージ間の重複を外した唯一の見方。")}
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


def cut_at(v, qc, qs):
    P = pop_rows(v, CAND["population"])
    vc = sorted(r["f2_cash_r"] for r in P if r.get("f2_cash_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    tc, ts = q_at(vc, qc), q_at(vs, qs)
    g = [r for r in P if r.get("f2_cash_r") is not None and r.get("f2_sga_r") is not None
         and r["f2_cash_r"] >= tc and r["f2_sga_r"] <= ts]
    n_pop, k_pop = len(P), sum(1 for r in P if r.get("win"))
    kg = sum(1 for r in g if r.get("win"))
    return {"thr_cash": r4(tc), "thr_sga": r4(ts), "n_group": len(g), "k": kg,
            "lift": (None if not g else r4(kg / len(g) - k_pop / n_pop))}


for qc, qs in ((0.70, 0.50), (0.75, 0.50), (0.80, 0.50), (0.75, 0.40),
               (0.75, 0.60), (0.70, 0.60), (0.80, 0.40)):
    key = f"cash_top{int((1-qc)*100)}%_sga_bottom{int(qs*100)}%"
    thr_sens[key] = {str(v): cut_at(v, qc, qs) for v in SIGN_VINTAGES}
    ls = [thr_sens[key][str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [thr_sens[key][str(v)]["k"] for v in SIGN_VINTAGES]
    thr_sens[key]["maintained_lift"] = (r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None)
    thr_sens[key]["min_numerator"] = min(ns)
    thr_sens[key]["gates123_hold"] = bool(
        all(x is not None and x > 0 for x in ls) and all(abs(x) >= LIFT for x in ls) and min(ns) >= MIN_NUM)

_grid = [(k, thr_sens[k]["maintained_lift"], thr_sens[k]["gates123_hold"])
         for k in thr_sens if k != "note"]
_grid_sorted = sorted(_grid, key=lambda x: -(x[1] or 0))
thr_sens["grid_summary"] = {
    "n_variants_tested": len(_grid),
    "n_variants_holding_gates123": sum(1 for _, _, h in _grid if h),
    "chosen_variant": "cash_top25%_sga_bottom50%",
    "chosen_maintained_lift": dict((k, ml) for k, ml, _ in _grid).get("cash_top25%_sga_bottom50%"),
    "rank_of_chosen": 1 + [k for k, _, _ in _grid_sorted].index("cash_top25%_sga_bottom50%"),
    "ranked": [{"variant": k, "maintained_lift": ml, "gates123": h} for k, ml, h in _grid_sorted],
    "how_to_read": ("**事前登録の外・診断専用**。prereg は刻みを『中央値または上下1/4』に限っているので"
                    "この格子は合否に使えない。だが**選ばれた刻みが格子の最大値に座っているか**は"
                    "過剰適合の指標になる——近傍を少し動かして崩れるなら、それは閾値の当たりくじ。"),
}

dist = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    vc = sorted(r["f2_cash_r"] for r in P if r.get("f2_cash_r") is not None)
    vs = sorted(r["f2_sga_r"] for r in P if r.get("f2_sga_r") is not None)
    dist[str(v)] = {
        "f2_cash_r": {"n_measurable": len(vc), "coverage": r4(len(vc) / len(P)),
                      "q25": r4(q_at(vc, .25)), "q50": r4(q_at(vc, .5)), "q75": r4(q_at(vc, .75)),
                      "q90": r4(q_at(vc, .90))},
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

six = {
    "1_vintage_sign": {},
    "2_sector": {},
    "3_irr_shadow": {},
    "4_one_company": {},
    "5_permutation": {},
    "6_increment": {},
}

six["1_vintage_sign"]["落とせたか"] = (
    "落とせなかった（符号は3ビンテージとも正）" if g1["gate_sign_stability"]
    else "**落とせた**（符号が反転する）")
six["1_vintage_sign"]["ただし"] = {
    "アンカー年の膨らみ": (f"lift は 2016 {_l[2016]} / 2017 {_l[2017]} / 2018 {_l[2018]}＝"
                          f"最大/最小 {g1['anchor_year_inflation']['max_over_min_ratio']}倍。"
                          f"母集団の勝率は {cells[2016]['p_base']}→{cells[2017]['p_base']}→{cells[2018]['p_base']} と"
                          "窓が短くなるほど下がるので、**分母が縮むだけで lift は伸びる**"),
    "3つの証拠ではない": (f"群は和集合 {len(union)} 社のうち {len(inter)} 社が3ビンテージ共通"
                          f"（jaccard {g1['group_membership_overlap']['jaccard']}）、"
                          "窓は同じ終端日で 8.09 年を共有"),
    "2013/2015": "判定不能（f2_ 特徴量が構造的に存在しない）",
}
six["2_sector"]["落とせたか"] = ("**落とせた**" if not g2["gate_sector_mh"] else "落とせなかった")
six["2_sector"]["根拠"] = {
    "MH（prereg の試験）": {str(v): g2["mh"][str(v)]["mh_risk_diff"] for v in SIGN_VINTAGES},
    "MHは層をほとんど落としている": {str(v): f"{g2['mh'][str(v)]['strata_used']}層使用/"
                                     f"{g2['mh'][str(v)]['strata_dropped']}層破棄・群の被覆"
                                     f"{g2['mh'][str(v)]['group_coverage_share']}" for v in SIGN_VINTAGES},
    "間接標準化（層を落とさない業種調整）": {str(v): g2["indirect_standardization"][str(v)]["risk_diff_vs_sector"]
                                            for v in SIGN_VINTAGES},
    "間接標準化の維持値": g2["indirect_standardization_maintained"],
    "業種＋可測性を同時に外すと": {str(v): g2["indirect_standardization_within_measurable"][str(v)]["risk_diff_vs_sector"]
                                   for v in SIGN_VINTAGES},
    "業種＋可測性を外した維持値": g2["indirect_standardization_within_measurable_maintained"],
    "業種を1つ抜くと崩れる業種": g2["leave_one_sector_out_breakers"],
    "層内置換": g2["within_sector_permutation"]["p_ge_observed"],
}
six["3_irr_shadow"]["落とせたか"] = ("落とせなかった（文言どおりなら通る）" if g3["gate_irr_literal"]
                                     else "**落とせた**")
six["3_irr_shadow"]["honest_verdict"] = g3["gate_irr_honest"]
six["4_one_company"]["落とせたか"] = (
    f"**落とせた**（gates1-3 が {g4['n_breaking_gates_1_to_3']} 社の1社抜きで崩れる: "
    f"{[x['ticker'] for x in g4['breakers_gates_1_to_3']][:10]}）"
    if g4["n_breaking_gates_1_to_3"] > 0
    else f"落とせなかった（gates1-3 は1社抜きで崩れない。最悪の維持lift {g4['worst_maintained_lift']}）")
six["5_permutation"]["落とせたか"] = {
    "この1本だけを検定したなら": (f"p={g5['unrestricted_ticker_bundle']['p_ge_observed']}"
                                  f"（層内 p={g5['within_sic2']['p_ge_observed']}）"),
    "実際は数千本から選ばれている": (
        f"探索は {g5['family_wise_from_explorer']['n_tests_in_search']} 検定。帰無でも "
        f"{g5['family_wise_from_explorer']['P_at_least_one_pass_under_null_L5']} の確率で1本以上『合格』が出る。"
        f"帰無の最大統計量は p50={_nullmax['p50']} / p90={_nullmax['p90']} / p95={_nullmax['p95']}"
        f" に対し観測 {g1['maintained_lift']}＝**{g5['observed_vs_null_max_distribution']['position']}**"),
}
six["6_increment"]["落とせたか"] = (
    "**落とせた**（既存の関門の生存者の中では prereg の線を維持できない）"
    if not (g6["prereg_line_applied_to_the_increment"]["gate_lift_holds"]
            and g6["prereg_line_applied_to_the_increment"]["gate_min_numerator_holds"])
    else "落とせなかった")

_broke = [k for k, v in six.items()
          if (isinstance(v.get("落とせたか"), str) and v["落とせたか"].startswith("**落とせた**"))]

verdict = {
    "候補": CAND["label"] + " / P_full / 勝者側",
    "探索側の弁": f"不合格（{ref['gate_failed_at'] if ref else '?'}）・維持lift {ref['maintained_lift'] if ref else '?'}",
    "再現": ("できた（探索側と不一致0・依頼文の2018の数字とも一致・行を直接数えても一致）"
             if (cross["mismatches"] == 0 and spot["mismatch"] == 0 and cross["vs_brief"]["match"])
             else "**できていない＝結論を書いてはいけない**"),
    "6検証のうち落ちた数": len(_broke),
    "落ちた検証": _broke,
    "prereg_gates_literal": gates,
    "結論": None,
}

out = {
    "generated": time.strftime("%Y-%m-%d"),
    "tool": "night/hist_wd_verify_cash_sga.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "candidate": CAND,
    "variable_definitions": {
        "f2_cash_r": "現金及び現金同等物 ÷ 総資産（retro_features2.py:262）",
        "f2_sga_r": ("販管費 ÷ 売上（retro_features2.py:234）。**合算タグのみ**を読むので"
                     "販売費と一般管理費を分けて報告する社は欠測＝この脚は開示習慣も選んでいる"),
    },
    "reproduction_crosscheck": cross,
    "spot_check_row_level": spot,
    "test1_vintage_sign": g1,
    "testM_measurability_bias": gM,
    "test2_sector": g2,
    "test3_irr_shadow": g3,
    "test4_leave_one_company_out": g4,
    "test5_permutation": g5,
    "test6_increment_over_existing_gates": g6,
    "testZ_what_is_this_group": gZ,
    "aux_R_regime_split": regime,
    "aux_S_disjoint_subwindow": sub,
    "aux_T_threshold_sensitivity": thr_sens,
    "aux_distribution_shape": dist,
    "prereg_gates_literal": gates,
    "survived_all_prereg_gates_literal": survived_prereg,
    "six_verification_outcomes": six,
    "verdict": verdict,
}

verdict["結論"] = (
    ("**不合格**——6検証のうち " + "・".join(_broke) + " が落ちた。"
     f"prereg の5条件のうち文言どおりでも {[k for k, v in gates.items() if not v]} が×。")
    if _broke or not survived_prereg else "落とせなかった")

out["verdict"] = verdict
out["runtime_sec"] = round(time.time() - t0, 1)

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print(f"[候補] {CAND['label']} / {CAND['population']} / 勝者側")
print(f"[再現] 探索側と比較 {cross['compared']} 件 / 不一致 {cross['mismatches']} 件 → {cross['verdict']}")
print(f"       依頼文の2018の数字と一致: {cross['vs_brief']['match']}  行検算: 直接{spot['n_direct']}社 vs セル{spot['n_cell']}社 不一致{spot['mismatch']}")
print()
for v in SIGN_VINTAGES:
    c = cells[v]
    print(f"  {v}: n_pop={c['n_pop']} base={c['p_base']} n_group={c['n_group']} k={c['numerator']} "
          f"p={c['p_group']} lift={c['lift']} | 可測基準 lift_meas={c['lift_meas']}")
print(f"  維持lift={g1['maintained_lift']}  最小分子={g1['min_numerator']}  可測基準の維持lift={gM['maintained_lift_vs_measurable']}")
print()
print(f"[1 ビンテージ] 符号={g1['gate_sign_stability']} lift={g1['gate_lift']} 分子={g1['gate_min_numerator']}")
print(f"    アンカー年の膨らみ: {g1['anchor_year_inflation']['lift_by_vintage']} → 最大/最小={g1['anchor_year_inflation']['max_over_min_ratio']}倍")
print(f"    母集団の勝率(base): {g1['anchor_year_inflation']['base_rate_by_vintage']}")
print(f"    群の重なり: 3ビンテージ共通 {len(inter)} 社 / 和集合 {len(union)} 社  jaccard={g1['group_membership_overlap']['jaccard']}")
print(f"    2013/2015: {g1['out_of_sample_2013_2015']}")
print()
print(f"[M 可測性] 両脚可測の被覆={gM['per_vintage']['2018']['coverage_both']}  "
      f"可測の勝率={gM['per_vintage']['2018']['p_win_measurable_both']} vs 不可測={gM['per_vintage']['2018']['p_win_unmeasurable']}")
print(f"    lift(母集団基準)={_c18['lift']} vs lift(可測基準)={_c18['lift_meas']} → "
      f"可測性由来の割合={gM['per_vintage']['2018']['share_of_lift_from_measurability']}")
print(f"    可測基準なら lift 条件は {'○' if gM['gate_lift_would_hold_on_measurable_baseline'] else '×'}")
print()
for v in SIGN_VINTAGES:
    m = g2["mh"][str(v)]
    i = g2["indirect_standardization"][str(v)]
    i2 = g2["indirect_standardization_within_measurable"][str(v)]
    print(f"[2 業種] {v}: MH={m['mh_risk_diff']} 層{m['strata_used']}使用/{m['strata_dropped']}破棄 "
          f"群の被覆={m.get('group_coverage_share')} | 間接標準化={i['risk_diff_vs_sector']} (SMR={i['smr']}) "
          f"| 業種＋可測性を同時に外すと={i2['risk_diff_vs_sector']} (SMR={i2['smr']})")
print(f"    維持値: 素={g1['maintained_lift']} → 業種調整={g2['indirect_standardization_maintained']} "
      f"→ 業種＋可測性={g2['indirect_standardization_within_measurable_maintained']}  (線は{LIFT})")
print(f"    層内置換: p={g2['within_sector_permutation']['p_ge_observed']}")
print(f"    業種を1つ抜くと崩れる: {[x['sic2'] for x in g2['leave_one_sector_out_breakers']]}")
_wdom = g2["within_dominant_sector"]
print(f"    群を支配する業種 sic2={_wdom['sic2']}: この業種は単独で母集団比 "
      f"{[_wdom['per_vintage'][str(v)]['lift_of_sector_alone_vs_population'] for v in SIGN_VINTAGES]} 勝つが、"
      f"**その中で組が足すのは** {[_wdom['per_vintage'][str(v)]['lift_of_pair_within_sector'] for v in SIGN_VINTAGES]}"
      f"（維持 {_wdom['maintained_lift_within_sector']}）")
print("    MHを担う層の中身:")
for v in SIGN_VINTAGES:
    ms = g2["mh_top_stratum_is_heterogeneous"]["members"].get(str(v), [])
    print(f"      {v} sic2={_top_stratum[v]}: " +
          " / ".join(f"{m['ticker']}({m['sicDesc']}){'○' if m['win'] else '×'}" for m in ms))
print()
print(f"[3 irr] 2018: rho={_ic18.get('corr_group_vs_irr')} 直交ヒント={_ic18.get('orthogonal_hint')} "
      f"irr>=70層={_ic18.get('irr_ge70')}")
o = g3["orthogonality_is_it_just_small_n"].get("2018")
if o:
    print(f"    同サイズの無作為群が『直交』と呼ばれる確率={o['P_random_group_of_same_size_is_called_orthogonal']}")
_en = g3["irr_enrichment"]["2018"]
print(f"    irr偏り: 群のうち irr>=70 は {_en['share_irr_ge70_in_group']} vs 母集団(irr読解あり) "
      f"{_en['share_irr_ge70_in_pop_with_irr']}  2016/2017 は irr 読解ゼロ＝判定不能")
print(f"    正直な結末: {g3['gate_irr_honest']}")
print()
print(f"[4 1社] 最悪の維持lift={g4['worst_maintained_lift']} 最大変化={g4['max_abs_delta_from_one_company']} "
      f"gates1-3が崩れる社={g4['n_breaking_gates_1_to_3']}")
print(f"    群から勝者を何社抜くと崩れるか: {g4['sequential_winner_removal']}")
print()
print(f"[5 置換] 単体p(無制約)={g5['unrestricted_ticker_bundle']['p_ge_observed']} "
      f"/ 層内p={g5['within_sic2']['p_ge_observed']}")
print(f"    探索全体: {g5['family_wise_from_explorer']['n_tests_in_search']}検定・帰無の最大統計量 "
      f"p50={_nullmax['p50']} p90={_nullmax['p90']} p95={_nullmax['p95']} ← 観測{g1['maintained_lift']}"
      f"（{g5['observed_vs_null_max_distribution']['position']}）")
print(f"    → family-wise p の下限: {g5['observed_vs_null_max_distribution']['family_wise_p_lower_bound']}")
print()
print(f"[6 増分] 脚単独の最良={g6['best_leg_maintained_lift']} 増分={g6['increment_over_best_leg']}")
for v in SIGN_VINTAGES:
    s = g6["survivors"][str(v)]["all_three"]
    print(f"    {v} 既存関門の生存者内: n群={s['n_group_among_survivors']} k={s['k']} 増分lift={s['incremental_lift']}")
pl = g6["prereg_line_applied_to_the_increment"]
print(f"    維持増分lift={pl['maintained_incremental_lift']} 最小分子={pl['min_numerator']} "
      f"→ lift:{'○' if pl['gate_lift_holds'] else '×'} 分子:{'○' if pl['gate_min_numerator_holds'] else '×'}")
print()
if "per_vintage" in regime:
    for k, r_ in regime["per_vintage"].items():
        print(f"[R レジーム] {k}: base={r_['p_base']} 群={r_['p_group']} lift={r_['lift']} (n群={r_['n_group']})")
for k in ("2016", "2017"):
    if k in sub:
        print(f"[S 重ならない窓] {k}: {sub[k]['window']} lift={sub[k]['lift_in_disjoint_subwindow']} "
              f"(n群={sub[k]['n_group']} k={sub[k]['k']})")
_gs = thr_sens["grid_summary"]
print(f"[T 閾値] 格子{_gs['n_variants_tested']}通りのうち gates1-3 を保つのは {_gs['n_variants_holding_gates123']} 通り。"
      f"選ばれた刻みの順位={_gs['rank_of_chosen']}位（維持lift {_gs['chosen_maintained_lift']}）")
for x in _gs["ranked"]:
    print(f"    {x['variant']:34s} 維持lift={x['maintained_lift']} gates123={x['gates123']}")
print()
print("── MH の中身（業種調整はどの層から来ているか） ──")
for v in SIGN_VINTAGES:
    for t in g2["mh_decomposition"][str(v)]["strata_entering_MH"]:
        print(f"  {v} sic2={t['sic2']}: 群{t['n_group']}社 p={t['p_group']} vs 他{t['n_rest']}社 p={t['p_rest']} "
              f"→ 差={t['risk_diff']} (MHの{t['share_of_MH']})")
print()
print("[事前登録の5条件・文言どおり] " + " / ".join(f"{k}:{'○' if v else '×'}" for k, v in gates.items()))
print()
print("[依頼された6検証の結末]")
for k, v in six.items():
    x = v["落とせたか"]
    print(f"  {k}: {x if isinstance(x, str) else x['この1本だけを検定したなら']}")
print()
print(f"[総括] {verdict['結論']}")
print(f"→ {DEST}  ({out['runtime_sec']}s)")
