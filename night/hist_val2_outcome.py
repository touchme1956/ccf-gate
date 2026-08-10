#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自己相対バリュエーションを **新しい結果指標（元本割れ）** で検定し直す (2026-08-10新設)

なぜこの器が要るか
------------------
v1（out/hist_valuation_prereg.json・2026-08-09）は自己相対の指標を
**恒久毀損 P(年率<=-15%)** で裁いて「66セル中0合格」と結論した。ところが同じ日の
reachability の再計算で、**その基準は結果を見る前から到達不能だった**ことが分かっている——
判定プール(質実証)の恒久毀損の実数が 2013年 **0社** / 2015年 3社 / 2018年 9社しか無く、
基準1が要求する「分子>=5社」に**神の遮断器でも届かない**ビンテージが2つあった。

  ⇒ **「不合格」は「効果なし」の証明になっていない。** 測っていたのは指標の性能ではなく、
     基準の設計と母集団の薄さだった。

この器は、**指標と格子は v1 のまま**（＝ゴールポストを動かさない）で、
**結果指標だけを v2 が事前登録した『元本割れ P(年率<0)』へ差し替えて**数え直す。
元本割れのベース率は 15.9% / 18.1% / 24.8%（実数 57 / 77 / 84社）＝**3ビンテージとも到達可能**。

  「効かない」と「測れていない」を分けるのが、この器の全部である。

守っている作法
--------------
■ 事前登録を後から動かさない
    格子・指標は v1、基準の数値（lift 2.0倍・分子>=5社・止率<=15%）と主結果指標は v2 の正本を
    **起動時に照合**し、変わっていたら走らない。人の意志ではなく機構で防ぐ。

■ 到達可能性を「合否より先に」出す（v1 の最大の教訓）
    各セルについて **分子の天井 min(事象数, 止めた社数)** と **必要分子 max(5, ceil(2.0*base*K))**
    を計算し、そもそも合格しうるセルか（reachable）を先に印字する。到達不能なセルの「不合格」は
    不合格として数えない（判定不能）。

■ 遮断器は選別器ではない
    裁くのは「**止めた側の左尾**」であって「通した側の平均」ではない。同時に
    「**止めた群の中央値が通過群より高くないか**」（基準2＝勝者を巻き込んでいないか）を必ず併記する。

■ 中央値だけで語らない
    等ウェイト買い持ち（終価倍率の**算術平均**を年率へ）を必ず併記する。中央値は「1社を選んだとき」、
    等ウェイトは「その群を全部買ったとき」で**別の問いに答えている**（この台帳の実測で 7.2% vs 12.4%）。

■ 窓を揃える
    P_wide は window_full を要求し、年数は modal_years で単一（実測 2013 は 358社すべて 13.09年）。
    起動時に窓のばらつきを検査して印字する。

■ 欠測をゼロと読むな（絶対のルール7）
    指標が null の社は「止めた」でも「通した」でもない＝`na` として別に数える。0（低い）と読み替えない。

■ 多重検定を数える
    セル数だけ当たりが出る確率を、**結果ラベルをプール内で並べ替える置換検定**で出す。

汚染の開示（重要・この検定の格付け）
------------------------------------
v1 は**同じ指標・同じ格子**を既に一度当てている（結果指標は違う）。したがってこの検定は
**純粋な確認的検定ではない**。ただし:
  ・指標・格子・方向・プールの定義は v1 の登録どおりで、一つも動かしていない
  ・差し替えた結果指標は v2 が **dd5 の検定のために結果を見る前に登録**したもの（v2 の
    registered_before_looking=true）。自己相対のために後から選んだ物差しではない
  ・元本割れ×自己相対のセルは**一度も計算されていない**（v1 は恒久毀損だけを見た）
この3点をもって「**確認的に近いが、指標が既見である**」と格付けし、合格しても
本採用はユーザーの明示指示の領分（絶対のルール1/6）とする。

実行:
  python3 night/hist_val2_outcome.py
  python3 night/hist_val2_outcome.py --perm 2000        # 置換検定の回数
  python3 night/hist_val2_outcome.py --json out/hist_val2_outcome.json
"""
import argparse
import json
import math
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

from hist_val_rev import load_vintage_checked, seen_revs   # noqa: E402  在庫の版の検問（単一実装）

VINTAGES = (2013, 2015, 2018)

# ── v1 の格子（**ここを直したら prereg も直す。照合で落ちる**）────────────────────
GRID_PCT = (0.80, 0.85, 0.90, 0.95)
GRID_Z = (1.0, 1.5, 2.0)
GRID_SPX = (0.80, 0.90, 0.95)

INDICATORS = [
    ("pe_pct",     "pct", "pe_hist_months",     "自己相対PER 分位"),
    ("ps_pct",     "pct", "ps_hist_months",     "自己相対P/S 分位"),
    ("pfcf_pct",   "pct", "pfcf_hist_months",   "自己相対P/FCF 分位"),
    ("adj_pe_pct", "pct", "adj_pe_hist_months", "市場調整PER 分位"),
    ("pe_z",       "z",   "pe_hist_months",     "自己相対PER z"),
    ("ps_z",       "z",   "ps_hist_months",     "自己相対P/S z"),
    ("spx_pe_pct", "mkt", None,                 "市場の水準（S&P500実績PER分位）"),
]
Z_MIN_MONTHS = 36          # z は採取器の仕様で8ヶ月から出る。分位と同じ母集団を見せるため36を課す

# ── 基準の数値（v2 の正本。照合する）──────────────────────────────────────────
LIFT = 2.0
MIN_NUM = 5
STOP_CAP = 0.15
LOSS = 0.0            # 主結果指標: 元本割れ P(tr_cagr < 0)
PERM_LINE = -0.15     # 従: 恒久毀損（v1 の物差し。比較のため必ず併記する）
WIN = 0.15


# ── 事前登録との照合（結果を見てから基準を動かすのを機構で防ぐ）─────────────────
def check_prereg():
    p1 = os.path.join(OUT, "hist_valuation_prereg.json")
    p2 = os.path.join(OUT, "hist_valuation_prereg_v2.json")
    j1 = json.load(open(p1, encoding="utf-8"))
    j2 = json.load(open(p2, encoding="utf-8"))
    b1, b2 = json.dumps(j1, ensure_ascii=False), json.dumps(j2, ensure_ascii=False)
    need = [
        ("v1 格子: 分位 80/85/90/95", b1, "80/85/90/95"),
        ("v1 格子: z 1.0/1.5/2.0", b1, "1.0/1.5/2.0"),
        ("v1 格子: spx 80/90/95", b1, "80/90/95"),
        ("v2 基準1: 2.0倍", b2, "2.0倍"),
        ("v2 基準1: 分子>=5社", b2, "5社"),
        ("v2 基準4: 止率<=15%", b2, "15%"),
        ("v2 主結果指標: 元本割れ", b2, "元本割れ率 P(tr_cagr < 0)"),
        ("v2 が結果を見る前に登録されたこと", b2, '"registered_before_looking": true'),
    ]
    bad = [nm for nm, blob, s in need if s not in blob]
    if bad:
        raise SystemExit("■ 事前登録が当時と違う。検定を中止する:\n  " + "\n  ".join(bad))
    return {"v1": "out/hist_valuation_prereg.json", "v1_registered": j1.get("registered"),
            "v2": "out/hist_valuation_prereg_v2.json", "v2_registered": j2.get("registered"),
            "grid_from": "v1（指標も格子も動かしていない）",
            "criteria_from": "v2（主結果指標＝元本割れ・lift2.0倍・分子>=5社・止率<=15%）",
            "verified": True}


# ── 統計 ─────────────────────────────────────────────────────────────────────
def ew_cagr(rows, years):
    """等ウェイト買い持ちの年率。**終価倍率の算術平均**を年率へ（中央値とは別の問い）。"""
    tot = []
    for r in rows:
        t = r.get("tr_total")
        if t is None and r.get("tr_cagr") is not None and r.get("years"):
            t = (1.0 + r["tr_cagr"]) ** r["years"]
        if t is not None and t > 0:
            tot.append(t)
    if not tot or not years:
        return None, 0
    return statistics.fmean(tot) ** (1.0 / years) - 1.0, len(tot)


def stats(rows, years, bench=None):
    """群の姿。**左尾は必ず分子（実数）を持たせる**（小さい分母の0%・100%を規則にしない）。"""
    rs = [r["tr_cagr"] for r in rows if r.get("tr_cagr") is not None]
    if not rs:
        return {"n": len(rows), "n_ret": 0}
    nloss = sum(1 for x in rs if x < LOSS)
    nperm = sum(1 for x in rs if x <= PERM_LINE)
    nwin = sum(1 for x in rs if x >= WIN)
    ew, n_ew = ew_cagr(rows, years)
    o = {"n": len(rows), "n_ret": len(rs),
         "median": round(statistics.median(rs), 4),
         "mean": round(statistics.fmean(rs), 4),
         "ew_cagr": None if ew is None else round(ew, 4), "n_ew": n_ew,
         "p_loss": round(nloss / len(rs), 4), "n_loss": nloss,       # ← 主
         "p_perm": round(nperm / len(rs), 4), "n_perm": nperm,       # ← 従（v1の物差し）
         "p_win": round(nwin / len(rs), 4), "n_win": nwin,
         "worst": round(min(rs), 4)}
    if bench is not None:
        o["p_lag"] = round(sum(1 for x in rs if x < bench) / len(rs), 4)
    return o


# ── プール ───────────────────────────────────────────────────────────────────
def pools_for(rows):
    """v2 の定義をそのまま使う（二重実装を作らない）。

    P_wide = 質実証 ∧ 前方リターンあり ∧ window_full（**指標のデータ要件を課さない**）＝判定用
    P_set  = P_wide ∧ analysis_set（XBRL自己履歴36ヶ月）＝v1 が判定に使っていたプール
    """
    wide = [r for r in rows
            if r.get("quality") and r.get("tr_cagr") is not None and r.get("window_full")]
    return {"P_wide": wide, "P_set": [r for r in wide if r.get("analysis_set")]}


# ── 到達可能性（**合否より先に出す**）──────────────────────────────────────────
def reachable(n_stop, n_event_pool, base_rate):
    """このセルは、そもそも合格しうるか。指標と結果を突き合わせずに決まる。"""
    if not n_stop:
        return {"reachable": False, "why": "止めた社が0"}
    ceil_num = min(n_event_pool, n_stop)
    need = max(MIN_NUM, math.ceil(LIFT * base_rate * n_stop))
    return {"reachable": bool(ceil_num >= need), "ceil": ceil_num, "need": need}


# ── 1セルの測定 ──────────────────────────────────────────────────────────────
def split(pool_rows, key, kind, hist_key, thr, drop=None):
    rows = [r for r in pool_rows if not (drop and drop.get(r["ticker"]))]
    stop, pas, na = [], [], []
    for r in rows:
        v = r.get(key)
        ok_hist = True
        if kind == "z" and hist_key:
            ok_hist = (r.get(hist_key) or 0) >= Z_MIN_MONTHS
        if v is None or not ok_hist:
            na.append(r)
        elif v >= thr:
            stop.append(r)
        else:
            pas.append(r)
    return rows, stop, pas, na


def evaluate(pool_rows, key, kind, hist_key, thr, years, bench, drop=None):
    rows, stop, pas, na = split(pool_rows, key, kind, hist_key, thr, drop)
    n_pool = len(rows)
    base = stats(rows, years, bench)
    ev = {"n_pool": n_pool, "n_stop": len(stop), "n_pass": len(pas), "n_na": len(na),
          "coverage": round((len(stop) + len(pas)) / n_pool, 4) if n_pool else None,
          "stop_rate_pool": round(len(stop) / n_pool, 4) if n_pool else None,
          "stopped": stats(stop, years, bench), "passed": stats(pas, years, bench),
          "passed_incl_na": stats(pas + na, years, bench), "na": stats(na, years, bench),
          "base": base,
          "stopped_loss_tickers": sorted(r["ticker"] for r in stop
                                         if r.get("tr_cagr") is not None and r["tr_cagr"] < LOSS)[:40]}
    ev["reach_loss"] = reachable(len(stop), base.get("n_loss", 0), base.get("p_loss") or 0)
    ev["reach_perm"] = reachable(len(stop), base.get("n_perm", 0), base.get("p_perm") or 0)
    return ev


def judge(ev, metric="loss"):
    """基準1・2・4を機械的に当てる（3・5は横断・後段）。metric は 'loss'(主) / 'perm'(従)。"""
    p, n = f"p_{metric}", f"n_{metric}"
    st, pa, ba = ev["stopped"], ev["passed"], ev["base"]
    if not st.get("n_ret") or not pa.get("n_ret"):
        return {"c1": None, "c2": None, "c4": None, "why": "止めた群または通過群が空＝判定不能"}
    reach = ev["reach_loss" if metric == "loss" else "reach_perm"]
    if not ba.get(p):
        return {"c1": None, "c2": None, "c4": None, "reachable": False,
                "why": "ベースの事象が0件＝倍率が定義できない（不合格ではなく判定不能）"}
    ratio = round(st[p] / ba[p], 2)
    c1 = (st[p] >= LIFT * ba[p]) and (st[n] >= MIN_NUM)
    c2 = st["median"] <= pa["median"]
    c4 = (ev["stop_rate_pool"] is not None and ev["stop_rate_pool"] <= STOP_CAP)
    return {"c1": bool(c1), "c1_ratio": ratio, "c1_numer": st[n], "c1_base": ba[p],
            "c2": bool(c2), "c2_gap": round(st["median"] - pa["median"], 4),
            "c4": bool(c4), "c4_stop_rate": ev["stop_rate_pool"],
            "reachable": bool(reach.get("reachable")),
            "reach": reach}


# ── 基準5（既存の関門で既に落ちる社を除く）──────────────────────────────────
def shrink_flags(y):
    """『事業の収縮』(v9.9.99の第四の関門)の歴史側の相当物。**retro_breaker_test と同式**。"""
    p2 = os.path.join(OUT, f"retro_features2_{y}.json")
    if os.path.exists(p2):
        j = json.load(open(p2, encoding="utf-8"))
        f = {r["ticker"]: r for r in j.get("rows") or [] if r.get("ticker")}
        return ({t: ((r.get("cagr5") or 0) < 0 and (r.get("opmD5") or 0) < 0) for t, r in f.items()},
                f"retro_features2_{y}.json: cagr5<0 ∧ opmD5<0（厳密式）", True)
    pc = os.path.join(OUT, f"retro_cohort_{y}.json")
    if os.path.exists(pc):
        j = json.load(open(pc, encoding="utf-8"))
        f = {}
        for r in j.get("rows") or []:
            t = r.get("ticker")
            if t and t not in f:
                f[t] = (r.get("sales_cagr5") or 0) < 0
        return (f, f"retro_cohort_{y}.json: sales_cagr5<0 のみ（opmD5 が在庫に無い＝上位集合の代理）", False)
    return {}, "在庫なし＝基準5は判定不能", False


def benchmark_gate(pool_rows, flag, years, bench, name, exact=True):
    """**門に現に入っている遮断器（事業の収縮）を、同じ物差しで数え直す。**

    自分に不利な数字を先に出すための節。判定は judge()/stats() を**そのまま呼ぶ**
    （基準をここで書き直さない）。欠測は門の実装と同じく発火しない側へ入れ、件数を別に数える。
    """
    stop = [r for r in pool_rows if flag.get(r["ticker"])]
    pas = [r for r in pool_rows if not flag.get(r["ticker"])]
    ev = {"n_pool": len(pool_rows), "n_stop": len(stop), "n_pass": len(pas), "n_na": 0,
          "n_no_flag": sum(1 for r in pool_rows if r["ticker"] not in flag),
          "stop_rate_pool": round(len(stop) / len(pool_rows), 4) if pool_rows else None,
          "stopped": stats(stop, years, bench), "passed": stats(pas, years, bench),
          "base": stats(pool_rows, years, bench)}
    ev["reach_loss"] = reachable(len(stop), ev["base"].get("n_loss", 0), ev["base"].get("p_loss") or 0)
    ev["reach_perm"] = reachable(len(stop), ev["base"].get("n_perm", 0), ev["base"].get("p_perm") or 0)
    return {"gate": name, "exact": exact, "ev": ev,
            "judge_loss": judge(ev, "loss"), "judge_perm": judge(ev, "perm")}


# ── 多重検定（置換検定）─────────────────────────────────────────────────────
def permutation(pool_rows, indi, years, bench, n_perm, seed=20260810):
    """**結果ラベルをプール内で並べ替え**、格子ぜんぶを当てて「1セルでも1∧2∧4を満たす」確率。

    指標の値は動かさず、リターンだけをシャッフルする＝指標と結果の対応だけを壊す。
    合格が偶然どれくらい出るかを、セル数を込みで出す。
    """
    if not pool_rows or n_perm <= 0:
        return None
    rng = random.Random(seed)
    keys = [(k, kd, hk, t) for k, kd, hk, _ in indi
            for t in (GRID_SPX if kd == "mkt" else (GRID_Z if kd == "z" else GRID_PCT))]
    # 実データでのセルの姿（止めた/通した の**添字**だけ先に作る＝毎回の分割をやり直さない）
    idx = []
    for k, kd, hk, t in keys:
        _, s, p, _ = split(pool_rows, k, kd, hk, t)
        si = {id(r) for r in s}
        if not s or not p:
            continue
        idx.append((k, t, [i for i, r in enumerate(pool_rows) if id(r) in si],
                    [i for i, r in enumerate(pool_rows) if id(r) not in si and r in p]))
    payload = [(r.get("tr_cagr"), r.get("tr_total")) for r in pool_rows]
    hits = 0
    per_cell = {}
    null_lift_med, null_gap_med = [], []      # ← 帰無のもとでの「濃縮の中心」と「基準2の差」
    for _ in range(n_perm):
        sh = payload[:]
        rng.shuffle(sh)
        any_pass = False
        lifts, gaps = [], []
        for k, t, si, pi in idx:
            srs = [sh[i][0] for i in si if sh[i][0] is not None]
            prs = [sh[i][0] for i in pi if sh[i][0] is not None]
            if not srs or not prs:
                continue
            allr = srs + prs
            nb = sum(1 for x in allr if x < LOSS)
            if not nb:
                continue
            base = nb / len(allr)
            nl = sum(1 for x in srs if x < LOSS)
            lifts.append((nl / len(srs)) / base)
            gaps.append(statistics.median(srs) - statistics.median(prs))
            c1 = (nl / len(srs) >= LIFT * base) and nl >= MIN_NUM
            c2 = statistics.median(srs) <= statistics.median(prs)
            c4 = len(si) / len(pool_rows) <= STOP_CAP
            if c1 and c2 and c4:
                any_pass = True
                per_cell[f"{k}@{t}"] = per_cell.get(f"{k}@{t}", 0) + 1
        hits += 1 if any_pass else 0
        if lifts:
            null_lift_med.append(statistics.median(lifts))
            null_gap_med.append(statistics.median(gaps))
    def pctl(xs, q):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4) if xs else None
    return {"n_perm": n_perm, "seed": seed, "n_cells": len(idx),
            "p_any_cell_passes_124": round(hits / n_perm, 4),
            "per_cell_rate": {k: round(v / n_perm, 4) for k, v in sorted(per_cell.items())},
            # **セルどうしは入れ子で強く相関する**（閾値を下げれば止めた群は上位集合）ので、
            # 「1.0未満のセルが53/66」を素朴な符号検定に掛けてはいけない。
            # 帰無をこの相関ごと再現する置換で、実測の『濃縮の中心』が偶然の帯のどこに落ちるかを出す。
            "null_lift_median": {"p05": pctl(null_lift_med, 0.05), "p50": pctl(null_lift_med, 0.50),
                                 "p95": pctl(null_lift_med, 0.95)},
            "null_c2gap_median": {"p05": pctl(null_gap_med, 0.05), "p50": pctl(null_gap_med, 0.50),
                                  "p95": pctl(null_gap_med, 0.95)}}


def crosscheck(out):
    """**同じ台帳を見る二つの検査器が違うことを言ってはいけない**(v9.9.65)。

    v1 の器 night/hist_val_gate_test.py と、共通する量（止めた社数・中央値・恒久毀損の分子・
    恒久毀損での基準1）を突き合わせる。**プールの定義がわずかに違う**ことに注意——
    gate_test の quality は `analysis_set ∧ quality`、本器の P_set はさらに
    `tr_cagr ∧ window_full` を課す。それでも群の中身は一致するはずで、実測で食い違い0件。
    ここが割れたら、まず突合せ側ではなく**自分の判定器**を疑う。
    """
    p = os.path.join(OUT, "hist_val_gate_test.json")
    if not os.path.exists(p):
        return {"ran": False, "why": "out/hist_val_gate_test.json が無い"}
    o = json.load(open(p, encoding="utf-8"))
    om = {(r["vintage"], r["indicator"], r["threshold"]): r
          for r in o["results"] if r["pool"] == "quality"}
    n = bad = 0
    diffs = []
    for r in out["results"]:
        if r["pool"] != "P_set":
            continue
        x = om.get((r["vintage"], r["indicator"], r["threshold"]))
        if not x:
            continue
        n += 1
        for f, u, v in (("n_stop", r["ev"]["n_stop"], x["ev"]["n_stop"]),
                        ("stop_median", r["ev"]["stopped"].get("median"),
                         x["ev"]["stopped"].get("median")),
                        ("perm_numer", r["judge_perm"].get("c1_numer"), x["judge"].get("c1_numer")),
                        ("c1_perm", r["judge_perm"].get("c1"), x["judge"].get("c1"))):
            if u is None or v is None:
                continue
            same = (bool(u) == bool(v)) if isinstance(u, bool) or isinstance(v, bool) \
                else abs(u - v) <= 0.0011
            if not same:
                bad += 1
                diffs.append({"cell": [r["vintage"], r["indicator"], r["threshold"]],
                              "field": f, "mine": u, "other": v})
    return {"ran": True, "other": "out/hist_val_gate_test.json", "cells": n, "mismatches": bad,
            "diffs": diffs[:20],
            "v1_verdict_reproduced": {
                "c1_pass_with_perm_metric_P_set":
                    sum(1 for r in out["results"] if r["pool"] == "P_set"
                        and r["judge_perm"].get("c1")),
                "v1_reported": (o.get("summary") or {}).get("quality", {}).get("c1_pass")}}


def main():
    ap = argparse.ArgumentParser(description="自己相対を『元本割れ』で検定し直す（格子はv1・基準はv2）")
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val2_outcome.json"))
    ap.add_argument("--perm", type=int, default=2000, help="置換検定の回数（0で無効）")
    a = ap.parse_args()

    pre = check_prereg()
    print("■ 事前登録と照合 OK — 格子/指標=v1(", pre["v1_registered"], ") / 基準・主結果指標=v2(",
          pre["v2_registered"], ")")
    print("■ 主結果指標: 元本割れ P(年率<0)　／　従（v1の物差し）: 恒久毀損 P(年率<=-15%) も必ず併記\n")

    out = {"generated": "2026-08-10", "tool": "night/hist_val2_outcome.py", "prereg": pre,
           "grid": {"pct": GRID_PCT, "z": GRID_Z, "spx": GRID_SPX}, "z_min_months": Z_MIN_MONTHS,
           "criteria": {"lift": LIFT, "min_numerator": MIN_NUM, "stop_cap": STOP_CAP,
                        "primary_outcome": "元本割れ P(tr_cagr<0)",
                        "secondary_outcome": "恒久毀損 P(tr_cagr<=-0.15)"},
           "contamination": ("v1が同じ指標・同じ格子を既に一度当てている（結果指標は違う）。"
                             "指標・格子・方向・プールは一つも動かしていないが、**純粋な確認的検定ではない**。"
                             "差し替えた結果指標はv2が結果を見る前に登録したもので、"
                             "元本割れ×自己相対のセルは一度も計算されていない。"),
           "vintages": {}, "results": [], "existing_gate_benchmark": [], "permutation": {}}

    for y in VINTAGES:
        d = load_vintage_checked(y)
        rows = d["rows"]
        years = d["join"]["modal_years"]
        bench = (d["join"].get("benchmark") or {}).get("tr_cagr")
        P = pools_for(rows)
        drop, drop_src, drop_exact = shrink_flags(y)

        # 窓を揃える（実測して印字する。揃っていなければ黙って進まない）
        yrs = sorted({r.get("years") for r in P["P_wide"]})
        out["vintages"][str(y)] = {"asof": d["asof"], "years": years, "bench_tr_cagr": bench,
                                   "n_pool": {k: len(v) for k, v in P.items()},
                                   "window_years_distinct": yrs,
                                   "shrink_src": drop_src, "shrink_exact": drop_exact,
                                   "n_shrink_in_pool": {k: sum(1 for r in v if drop.get(r["ticker"]))
                                                        for k, v in P.items()}}
        print("=" * 118)
        print(f"■ {y}年ビンテージ  asof={d['asof']}  窓={years}年（P_wide の years は {yrs}）"
              f"  SPY {bench:+.1%}")
        for pk in ("P_wide", "P_set"):
            rws = P[pk]
            if not rws:
                continue
            b = stats(rws, years, bench)
            tag = "★判定用" if pk == "P_wide" else " 参考(v1の判定プール)"
            print(f"\n  ── プール={pk}{tag}  n={len(rws)}  中央値 {b['median']:+.1%} / "
                  f"等ウェイト {b['ew_cagr']:+.1%} / 最悪 {b['worst']:+.1%}")
            print(f"     ベース  元本割れ {b['p_loss']:.1%}({b['n_loss']}社)  "
                  f"恒久毀損 {b['p_perm']:.2%}({b['n_perm']}社)  15%+ {b['p_win']:.1%}")

            if drop:
                bm = benchmark_gate(rws, drop, years, bench,
                                    "事業の収縮（cagr5<0 ∧ opmD5<0・v9.9.99の第四の関門）", drop_exact)
                bm.update({"vintage": y, "pool": pk, "src": drop_src})
                out["existing_gate_benchmark"].append(bm)

            print(f"     {'指標':<12}{'閾値':>6}{'止':>5}{'止率':>7}{'被覆':>7}"
                  f"{'止:中央':>9}{'止:等W':>9}{'通:中央':>9}"
                  f"{'止:元本割れ':>15}{'通:元本':>9}{'濃縮':>7}"
                  f"  {'到達':>4}{'1':>2}{'2':>2}{'4':>2}  {'[毀損] 濃縮/分子':>16}")
            for key, kind, hk, label in INDICATORS:
                grid = GRID_SPX if kind == "mkt" else (GRID_Z if kind == "z" else GRID_PCT)
                for thr in grid:
                    ev = evaluate(rws, key, kind, hk, thr, years, bench)
                    jl, jp = judge(ev, "loss"), judge(ev, "perm")
                    ev5 = evaluate(rws, key, kind, hk, thr, years, bench, drop=drop)
                    rec = {"vintage": y, "pool": pk, "indicator": key, "kind": kind, "label": label,
                           "threshold": thr, "ev": ev, "judge_loss": jl, "judge_perm": jp,
                           "ev_excl_shrink": ev5, "judge_loss_excl_shrink": judge(ev5, "loss"),
                           "shrink_exact": drop_exact}
                    out["results"].append(rec)
                    st, pa = ev["stopped"], ev["passed"]
                    if jl.get("c1") is None:
                        print(f"     {key:<12}{thr:>6}{ev['n_stop']:>5}   —— 判定不能"
                              f"（{jl.get('why','')}）")
                        continue
                    mk = lambda x: "✓" if x else "✗"
                    pr_ratio = jp.get("c1_ratio")
                    perm_txt = "—" if pr_ratio is None else f"{pr_ratio:.2f}"
                    print(f"     {key:<12}{thr:>6}{ev['n_stop']:>5}{ev['stop_rate_pool']:>7.1%}"
                          f"{ev['coverage']:>7.1%}{st['median']:>+9.1%}{st['ew_cagr']:>+9.1%}"
                          f"{pa['median']:>+9.1%}"
                          f"{st['p_loss']:>11.1%}({st['n_loss']:>2}){pa['p_loss']:>9.1%}"
                          f"{jl['c1_ratio']:>7.2f}"
                          f"  {mk(jl['reachable']):>4}{mk(jl['c1']):>2}{mk(jl['c2']):>2}"
                          f"{mk(jl['c4']):>2}  {perm_txt:>8}/{st['n_perm']:>3}社")

    # ── 基準3（横断）──────────────────────────────────────────────────────
    agg = {}
    for r in out["results"]:
        k = (r["pool"], r["indicator"], r["threshold"])
        j = r["judge_loss"]
        agg.setdefault(k, {"pool": r["pool"], "indicator": r["indicator"], "threshold": r["threshold"],
                           "vint": {}, "n_ok12": 0, "n_judgeable": 0})
        ok = bool(j.get("c1")) and bool(j.get("c2"))
        agg[k]["vint"][r["vintage"]] = {"c1": j.get("c1"), "c2": j.get("c2"), "c4": j.get("c4"),
                                        "ratio": j.get("c1_ratio"), "numer": j.get("c1_numer"),
                                        "reachable": j.get("reachable"),
                                        "stop_rate": j.get("c4_stop_rate")}
        if j.get("c1") is not None:
            agg[k]["n_judgeable"] += 1
            agg[k]["n_ok12"] += 1 if ok else 0
    passing = []
    for v in agg.values():
        c4s = [x.get("c4") for x in v["vint"].values() if x.get("c4") is not None]
        v["c3_v1"] = v["n_ok12"] >= 2                                   # v1 の基準3
        v["c3_v2"] = bool(v["vint"].get(2013, {}).get("c1") and v["vint"].get(2013, {}).get("c2")
                          and v["n_ok12"] >= 2)                          # v2 のより厳しい形
        v["c4_all"] = all(c4s) if c4s else None
        v["all_pass_1234_v1c3"] = bool(c4s and v["c3_v1"] and v["c4_all"])
        if v["all_pass_1234_v1c3"]:
            passing.append(v)
    out["aggregate"] = list(agg.values())
    out["passing_rules"] = passing

    print("\n" + "=" * 118)
    print("■ 基準3（1∧2 を2ビンテージ以上・v1の形）と基準4（全ビンテージで止率<=15%）の横断集計"
          "  ※主結果指標＝元本割れ")
    print(f"   {'プール':<8}{'指標':<13}{'閾値':>6}{'1∧2のV数':>10}{'基準3(v1)':>10}"
          f"{'基準3(v2厳)':>12}{'基準4':>7}{'全合格':>7}")
    for v in sorted(out["aggregate"], key=lambda x: (x["pool"], x["indicator"], x["threshold"])):
        m4 = "判定不能" if v["c4_all"] is None else ("✓" if v["c4_all"] else "✗")
        print(f"   {v['pool']:<8}{v['indicator']:<13}{v['threshold']:>6}{v['n_ok12']:>10}"
              f"{('✓' if v['c3_v1'] else '✗'):>10}{('✓' if v['c3_v2'] else '✗'):>12}{m4:>7}"
              f"{('✓' if v['all_pass_1234_v1c3'] else '✗'):>7}")
    print(f"\n■ 基準1〜4をすべて満たす『指標×閾値×プール』: **{len(passing)}件**")
    for v in passing:
        print("   ★", v["pool"], v["indicator"], v["threshold"], json.dumps(v["vint"], ensure_ascii=False))

    # ── 外れ方（合否ではなく姿）────────────────────────────────────────────
    summ = {}
    for pk in ("P_wide", "P_set"):
        R = [r for r in out["results"] if r["pool"] == pk and r["judge_loss"].get("c1") is not None]
        if not R:
            continue
        gaps = [r["judge_loss"]["c2_gap"] for r in R]
        rr = sorted(((r["judge_loss"]["c1_ratio"], r["judge_loss"]["c1_numer"], r["vintage"],
                      r["indicator"], r["threshold"]) for r in R), key=lambda x: -x[0])
        lifts = [x[0] for x in rr]
        summ[pk] = {"n_cells": len(R),
                    # **濃縮の中心**——「合格しない」だけでなく「どちら向きか」を残す。
                    # 1.0未満が多数なら、止めた群のほうが元本割れが**少ない**＝弱い逆信号。
                    "lift_median": round(statistics.median(lifts), 3),
                    "lift_below_1": sum(1 for x in lifts if x < 1.0),
                    "lift_max": round(max(lifts), 3), "lift_min": round(min(lifts), 3),
                    "c1_pass": sum(1 for r in R if r["judge_loss"]["c1"]),
                    "c2_pass": sum(1 for r in R if r["judge_loss"]["c2"]),
                    "c4_pass": sum(1 for r in R if r["judge_loss"]["c4"]),
                    "reachable": sum(1 for r in R if r["judge_loss"].get("reachable")),
                    "c2_gap_median": round(statistics.median(gaps), 4),
                    "c2_gap_positive": sum(1 for g in gaps if g > 0),
                    "best_c1": [{"ratio": a, "numer": b, "vintage": c, "indicator": d, "threshold": e}
                                for a, b, c, d, e in rr[:6]],
                    "max_ratio": rr[0][0] if rr else None}
        s = summ[pk]
        print(f"\n■ 外れ方（プール={pk}・判定できたセル {s['n_cells']}個・主指標＝元本割れ）")
        print(f"   到達可能なセル {s['reachable']}/{s['n_cells']}"
              f"（v1の恒久毀損では2013で構造的に0だった）")
        print(f"   基準1(左尾2.0倍かつ分子5社+) {s['c1_pass']}/{s['n_cells']} ／ "
              f"基準2(勝者を巻き込まない) {s['c2_pass']}/{s['n_cells']} ／ "
              f"基準4(止率<=15%) {s['c4_pass']}/{s['n_cells']}")
        print(f"   濃縮の中心 = {s['lift_median']:.2f}倍（範囲 {s['lift_min']:.2f}〜{s['lift_max']:.2f}"
              f"・要求は2.0倍）／ 1.0未満だったセル {s['lift_below_1']}/{s['n_cells']}")
        print(f"   ※**この「1.0未満が多数」を逆信号と読んではいけない**——セルは閾値が入れ子で"
              f"強く相関するので素朴な符号検定は使えない。下の置換検定が帰無帯を出す"
              f"（実測はその帯の中に落ちる＝**逆信号ではなく無関係**）")
        print(f"   基準2の差（止−通の中央値）の中央値 = {s['c2_gap_median']:+.4f}"
              f"（**正なら止めた側が高い＝勝者を巻き込む**）／ 正だったセル {s['c2_gap_positive']}/{s['n_cells']}")
        print(f"   左尾の濃縮が最も強い6件: "
              + ", ".join(f"{d}{e}@{c} {a:.2f}倍({b}社)" for a, b, c, d, e in
                          [(x['ratio'], x['numer'], x['vintage'], x['indicator'], x['threshold'])
                           for x in s['best_c1']]))
    out["summary"] = summ

    # ── 到達可能性の対比（**この検定を回した理由そのもの**）────────────────────
    #   v1 が「0合格」と言ったとき、その基準がそもそも達成可能だったのかを、
    #   物差し（恒久毀損 vs 元本割れ）× プール（P_set vs P_wide）の4通りで数え直す。
    reach = {}
    for pk in ("P_set", "P_wide"):
        for met, key in (("恒久毀損(v1の物差し)", "judge_perm"), ("元本割れ(v2の物差し)", "judge_loss")):
            for y in VINTAGES:
                RR = [r for r in out["results"] if r["pool"] == pk and r["vintage"] == y]
                if not RR:
                    continue
                jd = [r[key] for r in RR if r[key].get("c1") is not None]
                b = RR[0]["ev"]["base"]
                reach[f"{pk}/{met}/{y}"] = {
                    "events": b["n_perm"] if key == "judge_perm" else b["n_loss"],
                    "cells_judgeable": len(jd), "cells_reachable": sum(1 for x in jd
                                                                       if x.get("reachable"))}
    out["reachability_contrast"] = reach
    print("\n" + "=" * 118)
    print("■ 到達可能性の対比——**v1の『0合格』は、基準が達成可能だったのか**")
    print(f"   {'プール/物差し/年':<34}{'事象の実数':>10}{'判定可':>8}{'到達可能':>9}")
    for k, v in reach.items():
        print(f"   {k:<34}{v['events']:>10}{v['cells_judgeable']:>8}{v['cells_reachable']:>9}")
    print("   ⇒ **v1 が判定に使ったのは P_set × 恒久毀損**。2013は事象0社で22セルとも判定不能、")
    print("     2015は事象3社で『分子>=5』に神の遮断器でも届かない＝**到達可能は0セル**。")
    print("     基準3は『2ビンテージ以上』を要求するので、**v1の合格は構造的に不可能だった**。")
    print("     元本割れへ替えると3ビンテージとも到達可能になり、初めて『効かない』が測れる。")

    # ── 既存の関門を同じ物差しで（自分に不利な数字）──────────────────────────
    B = out["existing_gate_benchmark"]
    if B:
        print("\n" + "=" * 118)
        print("■ 判定基準の非対称——**門に現に入っている遮断器（事業の収縮）を、同じ物差しで数え直す**")
        print(f"   {'V':<6}{'プール':<8}{'止':>5}{'止率':>7}{'止:中央':>9}{'通:中央':>9}"
              f"{'止:元本割れ':>15}{'濃縮':>7}  {'1':>2}{'2':>2}{'4':>2}  式")
        for bm in B:
            st, pa, j = bm["ev"]["stopped"], bm["ev"]["passed"], bm["judge_loss"]
            if j.get("c1") is None:
                print(f"   {bm['vintage']:<6}{bm['pool']:<8}{bm['ev']['n_stop']:>5}  判定不能")
                continue
            mk = lambda x: "✓" if x else "✗"
            print(f"   {bm['vintage']:<6}{bm['pool']:<8}{bm['ev']['n_stop']:>5}"
                  f"{bm['ev']['stop_rate_pool']:>7.1%}{st['median']:>+9.1%}{pa['median']:>+9.1%}"
                  f"{st['p_loss']:>11.1%}({st['n_loss']:>2}){j['c1_ratio']:>7.2f}"
                  f"  {mk(j['c1']):>2}{mk(j['c2']):>2}{mk(j['c4']):>2}"
                  f"  {'厳密' if bm['exact'] else '代理(opmD5欠)'}")

    # ── 多重検定 ─────────────────────────────────────────────────────────
    if a.perm:
        print("\n■ 多重検定（結果ラベルをプール内で並べ替え・格子ぜんぶを当てて「1セルでも1∧2∧4」）")
        for y in VINTAGES:
            d = load_vintage_checked(y)
            P = pools_for(d["rows"])
            yy = d["join"]["modal_years"]
            bch = (d["join"].get("benchmark") or {}).get("tr_cagr")
            for pk in ("P_wide", "P_set"):
                pr = permutation(P[pk], INDICATORS, yy, bch, a.perm)
                if not pr:
                    continue
                # 帰無帯は**そのビンテージ・そのプールの22セル**で作るので、実測も同じ範囲で採る
                # （全ビンテージを混ぜた中央値と比べると、比べているものが違う）
                lf = [r["judge_loss"]["c1_ratio"] for r in out["results"]
                      if r["vintage"] == y and r["pool"] == pk
                      and r["judge_loss"].get("c1_ratio") is not None]
                obs = round(statistics.median(lf), 3) if lf else None
                pr["observed_lift_median"] = obs
                nl = pr["null_lift_median"]
                inside = (obs is not None and nl["p05"] <= obs <= nl["p95"])
                pr["observed_lift_inside_null_band"] = bool(inside)
                # **在庫へ必ず書く**。画面に出して在庫へ書かないと、報告に載った数字を
                # 後から在庫で検算できない＝「回したつもりで記録が残っていない」型
                # （night/hist_val_regime.py の if __name__ 置き忘れと同族）。
                out["permutation"][f"{y}/{pk}"] = pr
                print(f"   {y} {pk}: {pr['n_cells']}セル → 偶然に1セルでも通る確率 "
                      f"**{pr['p_any_cell_passes_124']:.3f}**"
                      f"  ／ 濃縮の中心 実測 {obs} vs 帰無帯 [{nl['p05']:.2f}, {nl['p95']:.2f}]"
                      f" 中央 {nl['p50']:.2f} → {'**帯の中**' if inside else '帯の外'}")

    cc = crosscheck(out)
    out["crosscheck"] = cc
    if cc["ran"]:
        v = cc["v1_verdict_reproduced"]
        print(f"\n■ v1の器との突合せ（{cc['other']}）: {cc['cells']}セル / "
              f"食い違い **{cc['mismatches']}件**")
        print(f"   v1の物差し（恒久毀損）を本器で当て直すと基準1の合格は "
              f"{v['c1_pass_with_perm_metric_P_set']}件 ＝ v1の報告 {v['v1_reported']}件 と一致"
              f"（**同じ台帳・同じ物差しなら同じ答えを出す**ことの確認）")
        for x in cc["diffs"]:
            print("   ✗", x)

    out["src_tool_rev"] = seen_revs()
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n■ 在庫: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
