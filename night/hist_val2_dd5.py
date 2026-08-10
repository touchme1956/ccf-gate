#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# night/hist_val2_dd5.py — 事前登録v2の**主指標 dd5（自己の5年高値からの下落）の検定**（2026-08-10）
#
# ── これは何か ───────────────────────────────────────────────────────────────
#   事前登録v2（out/hist_valuation_prereg_v2.json・コミット 1fc86dd で結果を見る前に固定）を
#   **一度だけ**当てる器。閾値の追加・方向の反転・プールの差し替えはしない。
#
#   仮説:  dd5 = adjclose[px_month] / max(adjclose[px_month-59..px_month]) − 1
#          が閾値以下（＝自分の5年高値から大きく落ちている）社を**止める**。
#   **向きが直感と逆である点に注意**——止めるのは高値圏ではなく「負けが実証されている側」。
#   台帳の既存実測 retro_midway『負け実証の回避が途中乗りの本体』と同じ向きで、
#   新しい思想は持ち込んでいない。
#
# ── 二重実装を作らない（v9.9.65の掟）─────────────────────────────────────────
#   指標(dd5/dd3/mom5)の定義   … night/hist_val_prereg_v2_reach.py から import
#                                （事前登録の到達可能性を数えたのと**同じ関数**を当てる）
#   群の統計・等ウェイト・最悪 … night/hist_val_gate_test.py の stats/ew_cagr/worst を import
#   基準5の『事業の収縮』フラグ … 同 shrink_flags を import（retro_breaker_test と同式）
#   在庫の版の検問             … night/hist_val_rev.py の load_vintage_checked
#   **この器が自前で持つのは「主・結果指標を元本割れに替えた judge_v2」だけ**。
#   gate_test.judge は恒久毀損で裁くので v2 には使えない（同じ関数を二つの意味で使わない）。
#
# ── 主・結果指標を元本割れ P(tr_cagr<0) にした理由（事前登録より）──────────────
#   v1は恒久毀損(≤−15%/年)で裁いたが、判定プールの実数が 2013年 0社 / 2015年 3社 で、
#   **毀損社を先に知って止める『神の遮断器』でも基準1（分子≥5）に到達できなかった**。
#   元本割れはベース 15.9/18.1/24.8%（P_wide）＝左尾でありながら分子が足りる。
#   恒久毀損・最悪値・中央値・等ウェイトは**記述として必ず併記**する。
#
# ── 判定可能なセルは6つだけ（事前登録の reachability で確定済み）───────────────
#   dd5 ≤ −0.30 と ≤ −0.40 の2閾値 × 3ビンテージ。
#   −0.20 は2015/2018で止率が15%を超え（基準4に落ちる）、−0.50 は2013で止まるのが4社
#   （全社が元本割れでも分子5に届かない）＝**結果を見る前から合格しえない**。
#   よって良い数字が出ても合格とは呼ばず、記述として残す。
#
# 実行:
#   python3 night/hist_val2_dd5.py                 # out/hist_val2_dd5.json
#   python3 night/hist_val2_dd5.py --quiet
#   python3 night/hist_val2_dd5.py --perm 2000     # 置換検定の回数
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

import hist_valuation as HV                      # noqa: E402  価格の取得（採取器のもの）
import hist_val_prereg_v2_reach as R             # noqa: E402  **指標の定義はここが単一実装**
import hist_val_gate_test as GT                  # noqa: E402  群の統計・基準5のフラグ
from hist_val_rev import load_vintage_checked, require_same_rev, seen_revs   # noqa: E402

VINTAGES = (2013, 2015, 2018)
PREREG = os.path.join(OUT, "hist_valuation_prereg_v2.json")

# 事前登録の値。**ここを直したら prereg も直す。照合(check_prereg_v2)で落ちる。**
GRID_DD = R.GRID_DD            # (-0.20, -0.30, -0.40, -0.50)
GRID_MOM = R.GRID_MOM          # (0.00, -0.05)
JUDGEABLE = (-0.30, -0.40)     # reachability が事前に確定させた判定可能セル
STOP_CAP = R.STOP_CAP          # 基準4: 止率 ≤ 15%
LIFT = R.LIFT                  # 基準1: 止めた群の事象率 ÷ ベース ≥ 2.0
MIN_NUM = R.MIN_NUM            # 基準1: 分子 ≥ 5社
PERM_LINE = GT.PERM            # 恒久毀損 −15%/年（記述用）


# ── 事前登録との照合（結果を見てから基準を動かすを機構で防ぐ）────────────────────
def check_prereg_v2():
    j = json.load(open(PREREG, encoding="utf-8"))
    blob = json.dumps(j, ensure_ascii=False)
    need = [("格子 dd5 = -0.20/-0.30/-0.40/-0.50", ["-0.2", "-0.3", "-0.4", "-0.5"]),
            ("基準1: 2.0倍", ["ベースの2.0倍"]),
            ("基準1: 分子>=5社", ["分子 ≥ 5社"]),
            ("基準4: 止率15%以下", ["止率 ≤ 15%"]),
            ("主・結果指標は元本割れ", ["元本割れ率 P(tr_cagr < 0)"]),
            ("方向は片側（落ちた側）", ["落ちた側を止める"])]
    bad = []
    for nm, subs in need:
        if not all(s in blob for s in subs):
            bad.append(nm)
    # 格子そのものがコードと一致するか（数値で照合）
    g = j["grid_fixed_in_advance"]["dd5"]
    if [round(x, 4) for x in g] != [round(x, 4) for x in GRID_DD]:
        bad.append(f"格子の数値が違う: prereg={g} / code={list(GRID_DD)}")
    if bad:
        raise SystemExit("■ 事前登録v2が当時と違う。検定を中止する（基準を動かして走らせない）:\n  "
                         + "\n  ".join(bad))
    return {"path": "out/hist_valuation_prereg_v2.json", "registered": j.get("registered"),
            "commit": "1fc86ddb3e25df372808d881bd0be5d55315ea75",
            "judgeable_cells": j["reachability_precomputed_BEFORE_looking"]
                                ["verdict_capable_cells"]["list"],
            "grid_verified": True}


# ── 統計（stats は gate_test のものをそのまま使い、主指標だけ足す）────────────────
def stat2(rows, years):
    """gate_test.stats に **元本割れ** を足す。

    stats を書き換えないのは、あちらが v1（恒久毀損が主）の判定器で現に動いているから。
    ここで足すのは新しい指標であって、群の統計の再実装ではない。
    """
    s = GT.stats(rows, years)
    rs = [r["tr_cagr"] for r in rows if r.get("tr_cagr") is not None]
    if rs:
        nl = sum(1 for x in rs if x < 0)
        s["p_loss"] = round(nl / len(rs), 4)
        s["n_loss"] = nl
        s["worst"] = round(min(rs), 4)
    else:
        s["p_loss"], s["n_loss"], s["worst"] = None, 0, None
    return s


def judge_v2(ev):
    """事前登録v2の基準1・2・4を機械的に当てる（3と5は横断・後段）。

    v1の judge との違いは**主・結果指標が元本割れ**であること。
    ベースが0件なら「不合格」ではなく「判定不能」と書き分ける（0で割った答えを
    0や False と読まない・ルール7の同族）。
    """
    st, pa, ba = ev["stopped"], ev["passed"], ev["base"]
    if not st.get("n_ret") or not pa.get("n_ret"):
        return {"c1": None, "c2": None, "c4": None,
                "status": "判定不能（止めた群または通過群が空）"}
    if not ba.get("p_loss"):
        c1, ratio, c1s = False, None, "判定不能（ベースの元本割れが0件＝倍率が定義できない）"
    else:
        ratio = round(st["p_loss"] / ba["p_loss"], 2)
        c1 = (st["p_loss"] >= LIFT * ba["p_loss"] and st["n_loss"] >= MIN_NUM)
        c1s = "合格" if c1 else f"不合格（濃縮 {ratio}倍 / 分子 {st['n_loss']}社）"
    c2 = st["median"] <= pa["median"]
    c4 = (ev["stop_rate_pool"] is not None and ev["stop_rate_pool"] <= STOP_CAP)
    return {"c1": bool(c1), "c1_status": c1s, "c1_ratio": ratio, "c1_numer": st["n_loss"],
            "c2": bool(c2), "c2_gap": round(st["median"] - pa["median"], 4),
            "c4": bool(c4), "c4_stop_rate": ev["stop_rate_pool"],
            # 従（判定に使わない・記述）
            "perm_ratio": (round(st["p_perm"] / ba["p_perm"], 2) if ba.get("p_perm") else None),
            "perm_numer": st["n_perm"]}


def split(pool, vals, thr, years, drop=None):
    """止めた/通過/判定不能に分ける。**欠測をゼロと読まない**（na を別に数える）。"""
    rows = [r for r in pool if not (drop and drop.get(r["ticker"]))]
    stop, pas, na = [], [], []
    for r in rows:
        v = vals.get(r["ticker"])
        if v is None:
            na.append(r)
        elif v <= thr:                 # **片側固定**（落ちた側を止める）
            stop.append(r)
        else:
            pas.append(r)
    n = len(rows)
    return {"n_pool": n, "n_measurable": len(stop) + len(pas),
            "coverage": round((len(stop) + len(pas)) / n, 4) if n else None,
            "n_stop": len(stop),
            "stop_rate_pool": round(len(stop) / n, 4) if n else None,
            "stop_rate_measurable": (round(len(stop) / (len(stop) + len(pas)), 4)
                                     if (stop or pas) else None),
            "stopped": stat2(stop, years), "passed": stat2(pas, years),
            "passed_incl_na": stat2(pas + na, years), "na": stat2(na, years),
            "base": stat2(rows, years),
            "stopped_worst": GT.worst(stop),
            "stopped_loss_tickers": sorted(r["ticker"] for r in stop
                                           if r.get("tr_cagr") is not None and r["tr_cagr"] < 0),
            "_stop_rows": stop, "_pass_rows": pas}


def indicators_for(pool, anchor="px_month"):
    """プールの各社の dd5 / dd3 / mom5 を出す。**定義は R（reach器）の関数をそのまま呼ぶ。**"""
    dd, dd3, mo, why = {}, {}, {}, {}
    for r in pool:
        t = r["ticker"]
        px = HV.fetch_px(t, offline=True) or {}
        adj = px.get("adj") or {}
        m0 = r.get(anchor if anchor != "px_next_month" else "px_month")
        if anchor == "px_next_month" and m0:
            m0 = R.month_sub(m0, -1)          # 1ヶ月後ろへ（負のシフト）
        if not m0:
            why["no_px_month"] = why.get("no_px_month", 0) + 1
            continue
        x, w = R.drawdown(adj, m0, R.DD_WIN, R.DD_MIN_OBS)
        if x is None:
            why[(w or "?").split("(")[0]] = why.get((w or "?").split("(")[0], 0) + 1
        else:
            dd[t] = x
        x3, _ = R.drawdown(adj, m0, R.DD3_WIN, R.DD3_MIN_OBS)
        if x3 is not None:
            dd3[t] = x3
        m = R.mom(adj, m0)
        if m is not None:
            mo[t] = m
    return dd, dd3, mo, why


def permutation(pool, k, years, n_iter, seed, drop=None):
    """**多重検定の値札**。指標を無作為な k 社の割り当てに置き換え、基準1と2が
    同時に立つ確率を出す。指標に情報が無くても、たまたま基準が立つ頻度がこれ。
    """
    rows = [r for r in pool if not (drop and drop.get(r["ticker"]))
            and r.get("tr_cagr") is not None]
    if k <= 0 or k >= len(rows):
        return None
    rnd = random.Random(seed)
    base = stat2(rows, years)
    hit1 = hit12 = 0
    idx = list(range(len(rows)))
    for _ in range(n_iter):
        rnd.shuffle(idx)
        st = [rows[i] for i in idx[:k]]
        pa = [rows[i] for i in idx[k:]]
        s, p = stat2(st, years), stat2(pa, years)
        c1 = (base["p_loss"] and s["p_loss"] >= LIFT * base["p_loss"] and s["n_loss"] >= MIN_NUM)
        c2 = s["median"] <= p["median"]
        hit1 += bool(c1)
        hit12 += bool(c1 and c2)
    return {"n_iter": n_iter, "seed": seed, "k": k,
            "p_c1": round(hit1 / n_iter, 4), "p_c1_and_c2": round(hit12 / n_iter, 4)}


def family_permutation(pools_by_y, ks_by_y, years_by_y, n_iter, seed):
    """**登録した手続きそのもの**の偽陽性率（多重検定の値札）。

    各ビンテージで「実際に止まったのと同じ社数 k を無作為に選ぶ」だけに置き換え、
    基準1∧2∧4 をビンテージごとに当て、そのうえで基準3（2013で成立 ∧ 2015/2018のどちらか）
    まで通す。**セル単位ではなく、判定可能な2閾値のどれかが通る確率**も出す
    ——事前登録が『6セルを一度だけ』と決めている以上、値札もその単位で付けるのが正しい。
    """
    rnd = random.Random(seed)
    rows = {y: [r for r in p if r.get("tr_cagr") is not None] for y, p in pools_by_y.items()}
    base = {y: stat2(rows[y], years_by_y[y]) for y in rows}
    hit = {t: 0 for t in ks_by_y}
    hit_any = 0
    for _ in range(n_iter):
        ok = {}
        for t, ks in ks_by_y.items():
            per = {}
            for y in rows:
                k = ks[y]
                idx = list(range(len(rows[y])))
                rnd.shuffle(idx)
                st = [rows[y][i] for i in idx[:k]]
                pa = [rows[y][i] for i in idx[k:]]
                s, p, b = stat2(st, years_by_y[y]), stat2(pa, years_by_y[y]), base[y]
                c1 = bool(b["p_loss"] and s["n_ret"] and
                          s["p_loss"] >= LIFT * b["p_loss"] and s["n_loss"] >= MIN_NUM)
                c2 = bool(s.get("median") is not None and p.get("median") is not None
                          and s["median"] <= p["median"])
                c4 = (k / len(rows[y])) <= STOP_CAP
                per[y] = c1 and c2 and c4
            ok[t] = bool(per[2013] and (per[2015] or per[2018]))
            hit[t] += ok[t]
        hit_any += any(ok[t] for t in ks_by_y)
    return {"n_iter": n_iter, "seed": seed,
            "per_threshold": {f"{t:+.2f}": round(hit[t] / n_iter, 4) for t in ks_by_y},
            "any_judgeable_threshold": round(hit_any / n_iter, 4),
            "note": "指標を『同じ社数の無作為な割り当て』に置き換えたときに、登録した手続きが"
                    "合格を出す確率。多重検定の値札であって、合格の証拠ではない"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val2_dd5.json"))
    ap.add_argument("--perm", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260810)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    res = {"generated": "2026-08-10", "tool": "night/hist_val2_dd5.py",
           "prereg": check_prereg_v2(),
           "indicator_impl": "night/hist_val_prereg_v2_reach.py の drawdown()/mom() を import"
                             "（到達可能性を数えたのと同じ関数＝二重実装なし）",
           "stats_impl": "night/hist_val_gate_test.py の stats/ew_cagr/worst を import。"
                         "**主・結果指標(元本割れ)だけ stat2 で足す**",
           "judgeable_cells": [f"dd5<={t:+.2f}" for t in JUDGEABLE],
           "vintages": {}}

    invs = {}
    for y in VINTAGES:
        d = load_vintage_checked(y)
        invs[y] = d
    require_same_rev(invs)                 # **版の混在は読んだ瞬間に止める**
    res["src_tool_rev"] = seen_revs()

    for y in VINTAGES:
        d = invs[y]
        rows = d["rows"]
        years = d["join"]["modal_years"]
        P = R.pools_for(rows)              # P_wide / P_set（**プールの定義も単一実装**）
        pools = {"P_wide": P["P_wide"], "P_set": P["P_set"],
                 # 参考: 質実証を課さない full（合否には使わない・事前登録 pools は質実証が本命）
                 "full": [r for r in rows if r.get("tr_cagr") is not None and r.get("window_full")]}

        # 窓の長さが揃っているかを毎回確かめる（DBDの教訓＝富を合成する統計は years を揃える）
        yrs = sorted({round(r.get("years") or 0, 2) for r in pools["P_wide"]})
        drop_flags, drop_note, exact = GT.shrink_flags(y)

        v = {"asof": d["asof"], "years": years, "years_in_pool": yrs,
             "benchmark_tr_cagr": (d.get("join") or {}).get("benchmark", {}).get("tr_cagr"),
             "shrink_gate_src": drop_note, "shrink_gate_exact": exact, "pools": {}}

        for pname, pool in pools.items():
            dd, dd3, mo, why = indicators_for(pool)
            ddn, _, _, _ = indicators_for(pool, anchor="px_next_month")
            nodist = {r["ticker"] for r in pool if r.get("distrib_break")}
            base = stat2(pool, years)
            pv = {"N": len(pool), "base": base,
                  "coverage_dd5": round(len(dd) / len(pool), 4) if pool else None,
                  "missing_why": why, "cells": {}}

            for t in GRID_DD:
                ev = split(pool, dd, t, years)
                j = judge_v2(ev)
                cell = {"judgeable": (round(t, 2) in [round(x, 2) for x in JUDGEABLE]),
                        "stop": ev["n_stop"], "stop_rate": ev["stop_rate_pool"],
                        "coverage": ev["coverage"],
                        "stopped": ev["stopped"], "passed": ev["passed"],
                        "na": ev["na"], "judge": j,
                        "stopped_worst": ev["stopped_worst"],
                        "stopped_loss_tickers": ev["stopped_loss_tickers"],
                        "stopped_tickers": sorted(r["ticker"] for r in ev["_stop_rows"])}
                # 基準5（既存の四関門で既に落ちる社を除いても1と2が保つか）
                if drop_flags:
                    ev5 = split(pool, dd, t, years, drop=drop_flags)
                    j5 = judge_v2(ev5)
                    cell["c5_excl_shrink"] = {
                        "n_pool": ev5["n_pool"], "stop": ev5["n_stop"],
                        "stop_rate": ev5["stop_rate_pool"],
                        "stopped": ev5["stopped"], "passed": ev5["passed"], "judge": j5,
                        "c5": bool(j5.get("c1") and j5.get("c2")),
                        "overlap_with_shrink": sum(1 for r in ev["_stop_rows"]
                                                   if drop_flags.get(r["ticker"]))}
                if pname == "P_wide":
                    cell["permutation"] = permutation(pool, ev["n_stop"], years,
                                                      a.perm, a.seed + int(abs(t) * 100))
                    # 感度（判定には使わない）
                    s = {}
                    e2 = split(pool, ddn, t, years)
                    s["anchor_px_next_month"] = {"stop": e2["n_stop"], "judge": judge_v2(e2)}
                    e3 = split([r for r in pool if r["ticker"] not in nodist], dd, t, years)
                    s["excl_distrib_break"] = {"n_pool": e3["n_pool"], "stop": e3["n_stop"],
                                               "judge": judge_v2(e3)}
                    e4 = split(pool, dd3, t, years)
                    s["dd3_36m_window"] = {"stop": e4["n_stop"], "judge": judge_v2(e4)}
                    cell["sensitivity"] = s
                for k in ("_stop_rows", "_pass_rows"):
                    ev.pop(k, None)
                pv["cells"][f"{t:+.2f}"] = cell

            # 従指標 mom5（判定に使わない）
            pv["mom5_cells"] = {}
            for t in GRID_MOM:
                ev = split(pool, mo, t, years)
                pv["mom5_cells"][f"{t:+.2f}"] = {"stop": ev["n_stop"],
                                                 "stop_rate": ev["stop_rate_pool"],
                                                 "stopped": ev["stopped"], "passed": ev["passed"],
                                                 "judge": judge_v2(ev)}
            v["pools"][pname] = pv
        res["vintages"][str(y)] = v

    # ── 基準3（2013で1と2が成立 ∧ 2015/2018のどちらかで同符号）と最終判定 ────────
    verdict = {}
    for t in GRID_DD:
        key = f"{t:+.2f}"
        per = {}
        for y in VINTAGES:
            c = res["vintages"][str(y)]["pools"]["P_wide"]["cells"][key]
            j = c["judge"]
            per[str(y)] = {"c1": j.get("c1"), "c2": j.get("c2"), "c4": j.get("c4"),
                           "c1_ratio": j.get("c1_ratio"), "c1_numer": j.get("c1_numer"),
                           "c5": (c.get("c5_excl_shrink") or {}).get("c5")}
        y13 = per["2013"]
        c3 = bool(y13["c1"] and y13["c2"] and y13["c4"]
                  and any(per[str(y)]["c1"] and per[str(y)]["c2"] and per[str(y)]["c4"]
                          for y in (2015, 2018)))
        judgeable = round(t, 2) in [round(x, 2) for x in JUDGEABLE]
        allpass = bool(judgeable and c3 and all(per[str(y)].get("c5") is not False
                                                for y in VINTAGES if per[str(y)]["c1"]))
        verdict[key] = {"judgeable": judgeable, "per_vintage": per, "c3": c3,
                        "PASS": allpass,
                        "note": ("" if judgeable else
                                 "**判定不可セル**（事前登録の reachability で合格しえないと"
                                 "確定済み）。良い数字が出ても合格とは呼ばない")}
    res["verdict"] = verdict
    res["PASS_ANY"] = any(v["PASS"] for v in verdict.values())

    # 多重検定の値札（登録した手続きそのものの偽陽性率）
    pools_by_y = {y: R.pools_for(invs[y]["rows"])["P_wide"] for y in VINTAGES}
    years_by_y = {y: invs[y]["join"]["modal_years"] for y in VINTAGES}
    ks_by_y = {t: {y: res["vintages"][str(y)]["pools"]["P_wide"]["cells"][f"{t:+.2f}"]["stop"]
                   for y in VINTAGES} for t in JUDGEABLE}
    res["family_permutation"] = family_permutation(pools_by_y, ks_by_y, years_by_y,
                                                   a.perm, a.seed)
    res["conclusion"] = ("合格セルあり＝ユーザーの明示指示があれば wire を検討できる"
                         if res["PASS_ANY"] else
                         "**不合格。遮断器は wire しない。**値・規約・採点式・刻み・重み・"
                         "関門・売却規律・配分はいっさい触らない")

    json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if not a.quiet:
        for y in VINTAGES:
            v = res["vintages"][str(y)]
            for pname in ("P_wide", "P_set", "full"):
                pv = v["pools"][pname]
                b = pv["base"]
                print(f"\n{'='*104}\n■ {y}年  {pname}  N={pv['N']}  窓={v['years']}年  "
                      f"被覆 dd5={pv['coverage_dd5']}")
                print(f"   ベース: 中央 {b['median']:+.4f} / 等ｳｪｲﾄ {b['ew_cagr']:+.4f} / "
                      f"元本割れ {b['n_loss']}社 {b['p_loss']:.1%} / "
                      f"恒久毀損 {b['n_perm']}社 {b['p_perm']:.1%} / 最悪 {b['worst']:+.4f}")
                print(f"   {'閾値':>7} {'判定可':>4} {'止':>4} {'止率':>7} | "
                      f"{'止:中央':>8} {'止:等W':>8} {'止:割れ':>10} {'止:毀損':>8} {'最悪':>8} | "
                      f"{'通:中央':>8} {'通:割れ':>8} | {'基1':>4} {'倍':>5} {'基2':>4} {'基4':>4}")
                for t in GRID_DD:
                    c = pv["cells"][f"{t:+.2f}"]
                    s, p, j = c["stopped"], c["passed"], c["judge"]
                    if not s.get("n_ret"):
                        print(f"   {t:+7.2f} {'✓' if c['judgeable'] else '—':>4} "
                              f"{c['stop']:>4} — 止めた群が空")
                        continue
                    print(f"   {t:+7.2f} {'✓' if c['judgeable'] else '—':>4} {c['stop']:>4} "
                          f"{c['stop_rate']:>7.1%} | {s['median']:>+8.4f} "
                          f"{(s['ew_cagr'] if s['ew_cagr'] is not None else 0):>+8.4f} "
                          f"{s['n_loss']:>4}/{s['n_ret']:<5} {s['n_perm']:>8} "
                          f"{s['worst']:>+8.4f} | {p['median']:>+8.4f} "
                          f"{p['p_loss']:>8.1%} | {str(j.get('c1')):>4} "
                          f"{str(j.get('c1_ratio')):>5} {str(j.get('c2')):>4} {str(j.get('c4')):>4}")
        print(f"\n{'='*104}\n■ 事前登録v2の判定（基準3＝2013で1と2が成立 ∧ 2015/2018のどちらかで同符号）")
        for k, vv in res["verdict"].items():
            mark = "✓判定可" if vv["judgeable"] else "—判定不可"
            print(f"   dd5<={k} {mark}  c3={vv['c3']}  PASS={vv['PASS']}   " +
                  " ".join(f"{y}:c1={vv['per_vintage'][y]['c1']}"
                           f"({vv['per_vintage'][y]['c1_ratio']}x/"
                           f"{vv['per_vintage'][y]['c1_numer']}社),c2={vv['per_vintage'][y]['c2']}"
                           f",c4={vv['per_vintage'][y]['c4']}" for y in ("2013", "2015", "2018")))
        print(f"\n■ 結論: {res['conclusion']}")
        print(f"→ {a.json}")


if __name__ == "__main__":
    main()
