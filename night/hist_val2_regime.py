#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# night/hist_val2_regime.py — 事前登録v2 の候補を **レジームと生存** で壊しにかかる器（2026-08-10）
#
# ── これは何か ───────────────────────────────────────────────────────────────
#   `night/hist_val2_dd5.py` が出した唯一の惜しい細胞
#       **dd5 ≤ −30% @2013・濃縮 2.79倍・分子12社・基準1/2/4/5 すべて成立**
#   （落ちたのは基準3＝2015 1.47倍 / 2018 1.79倍 が 2.0倍に届かない、の一点）を、
#   **期間で割って**壊せるかを実測する。壊せなければ「壊せなかった」と書く。
#
#   合否は動かさない。**この器は判定を持たない**——事前登録v2の判定は hist_val2_dd5.py が
#   一度だけ下しており（不合格・PASS_ANY=False）、ここでやるのは反証の試みだけである。
#   値・規約・採点式・刻み・重み・関門・売却規律・配分にはいっさい触らない（絶対のルール1/6）。
#
# ── 二重実装を作らない（v9.9.65の掟）─────────────────────────────────────────
#   指標 dd5 の定義        … night/hist_val_prereg_v2_reach.drawdown を import
#   プール P_wide/P_set    … 同 pools_for を import
#   群の統計・等ウェイト   … night/hist_val_gate_test.stats / ew_cagr / worst を import
#   在庫の版の検問         … night/hist_val_rev.load_vintage_checked
#   価格系列               … night/hist_valuation.fetch_px（offline・採取器のキャッシュ）
#   **自前で持つのは「窓を切って部分期間のリターンを作る」ことだけ。**
#
# ── 部分期間のリターンは月足 adjclose で作る（基準の違う二つを割らない）──────────
#   在庫の tr_cagr は **日次アンカー**（2013-07-01 → 2026-08-04）で作られている。
#   部分期間を日次で切り直す系列は在庫に無いので、**月足 adjclose**（指標 dd5 を作ったのと
#   同じ系列）で全部の窓を作る。したがってこの器の中では
#       部分期間の積 = 月足の全期間リターン
#   が恒等的に成り立ち、内部では一つの基準しか使わない。
#   月足の全期間 と 在庫の tr_cagr の食い違いは reconcile 節で毎回実測して出す
#   （median +0.27pt / p90 1.1pt / **符号が入れ替わるのは 358社中3社** ＝ここが後述の脆さ）。
#
# ── 何を測るか ───────────────────────────────────────────────────────────────
#   0 reconcile      登録セルの再現（検査器を信じる前に検査器を検算する）＋結果の基準の付け替え
#   1 calendar       暦のレジームで割る（pre-COVID / COVID暴落 / 回復 / de-rating / AI期）
#   2 decay          アンカーからの経過で割る（前半5年 / 残り）＋**ビンテージ間で重ならない区間**
#   3 vintages5      2016/2017 を足した5ビンテージ列（**判定には使わない**・プールは quality 非要求）
#   4 sector         SIC2 で層別（Mantel-Haenszel 調整比 ＋ 層内置換）
#   5 survival       退場社込みの母集団（退場の**時期**・挟み込み・兄弟器との照合）
#   6 mechanism      深さか、高値の古さか（**2013の窓だけが GFC の天井を含む**）
#   7 heterogeneity  ビンテージ間のばらつきは本物か（Clopper-Pearson と Fisher 正確検定）
#   8 dispersion     止めた群は「悪い群」か「ばらつく群」か／恒久毀損は誰が持っていたか
#   9 horizon        濃縮比の分母（コホートのベース）は窓の長さで決まるのか
#
# 実行:
#   python3 night/hist_val2_regime.py                # out/hist_val2_regime.json
#   python3 night/hist_val2_regime.py --perm 5000
#   python3 night/hist_val2_regime.py --quiet
import argparse
import json
import math
import os
import random
import statistics
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

import hist_valuation as HV                       # noqa: E402
import hist_val_prereg_v2_reach as R              # noqa: E402  指標とプールの単一実装
import hist_val_gate_test as GT                   # noqa: E402  群の統計
from hist_val_rev import load_vintage_checked, require_same_rev, seen_revs   # noqa: E402

VINTAGES = (2013, 2015, 2018)
EXTRA_VINTAGES = (2016, 2017)          # 参考のみ（hist_val 在庫が無く quality を課せない）
THR = -0.30                            # 惜しい細胞。−0.40 も併走で出す
THR2 = -0.40
END_M = "2026-07"                      # 直近の完成月（在庫の終端 2026-08-04 の直前）
LIFT, MIN_NUM, STOP_CAP = R.LIFT, R.MIN_NUM, R.STOP_CAP


# ── 月キーの算術（reach器の month_sub をそのまま使う）──────────────────────────
def mdiff(a, b):
    """b − a をヶ月で。"""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def yrs(a, b):
    return mdiff(a, b) / 12.0


def seg(adj, a, b, annualize=True):
    """月足 adjclose の区間リターン。**欠測はゼロと読まず None を返す**（ルール7）。"""
    x, y = adj.get(a), adj.get(b)
    if not x or not y or x <= 0 or y <= 0:
        return None
    n = yrs(a, b)
    if annualize and n >= 1.0:
        return (y / x) ** (1.0 / n) - 1.0
    return y / x - 1.0          # 1年未満は年率換算しない（audit_er_realized と同じ判断）


# ── 二項の正確な信頼区間（Clopper-Pearson）──────────────────────────────────
def _betainv_lo(k, n, alpha):
    if k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        m = (lo + hi) / 2
        # P(X >= k | p=m) = alpha/2 を解く
        s = sum(math.comb(n, i) * m ** i * (1 - m) ** (n - i) for i in range(k, n + 1))
        if s < alpha / 2:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def _betainv_hi(k, n, alpha):
    if k == n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        m = (lo + hi) / 2
        s = sum(math.comb(n, i) * m ** i * (1 - m) ** (n - i) for i in range(0, k + 1))
        if s > alpha / 2:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def ci(k, n, alpha=0.05):
    if not n:
        return None
    return [round(_betainv_lo(k, n, alpha), 4), round(_betainv_hi(k, n, alpha), 4)]


# ── 群の集計（部分期間用。gate_test.stats は年率前提なので符号と中央値だけ自前で数える）──
def grp(vals):
    """vals = [リターン] の集計。**主・結果指標は元本割れ（符号）**で v2 と揃える。"""
    v = [x for x in vals if x is not None]
    if not v:
        return {"n": 0, "p_loss": None, "n_loss": 0, "median": None}
    nl = sum(1 for x in v if x < 0)
    return {"n": len(v), "n_loss": nl, "p_loss": round(nl / len(v), 4),
            "median": round(statistics.median(v), 4)}


def cellstat(stop_v, pass_v, base_v, stop_rate):
    s, p, b = grp(stop_v), grp(pass_v), grp(base_v)
    ratio = (round(s["p_loss"] / b["p_loss"], 2)
             if (s["p_loss"] is not None and b["p_loss"]) else None)
    c1 = bool(ratio is not None and ratio >= LIFT and s["n_loss"] >= MIN_NUM)
    c2 = bool(s["median"] is not None and p["median"] is not None and s["median"] <= p["median"])
    c4 = bool(stop_rate is not None and stop_rate <= STOP_CAP)
    return {"base_p": b["p_loss"], "base_n": b["n"], "stop_n": s["n"], "stop_p": s["p_loss"],
            "stop_numer": s["n_loss"], "ratio": ratio,
            "stop_p_ci95": ci(s["n_loss"], s["n"]) if s["n"] else None,
            "med_stop": s["median"], "med_pass": p["median"],
            "c1": c1, "c2": c2, "c4": c4, "stop_rate": stop_rate}


# ── 入力（在庫の版を検問してから読む）────────────────────────────────────────
def load_all():
    invs = {}
    for y in VINTAGES:
        invs[y] = load_vintage_checked(y)
    require_same_rev(invs)
    return invs


def dd_for(pool, anchor_key="px_month"):
    """プールの dd5 を **reach器の drawdown をそのまま呼んで**作る。"""
    dd, why = {}, Counter()
    for r in pool:
        adj = (HV.fetch_px(r["ticker"], offline=True) or {}).get("adj") or {}
        m0 = r.get(anchor_key)
        if not m0:
            why["no_px_month"] += 1
            continue
        x, w = R.drawdown(adj, m0, R.DD_WIN, R.DD_MIN_OBS)
        if x is None:
            why[(w or "?").split("(")[0]] += 1
        else:
            dd[r["ticker"]] = x
    return dd, dict(why)


def adj_map(pool):
    return {r["ticker"]: ((HV.fetch_px(r["ticker"], offline=True) or {}).get("adj") or {})
            for r in pool}


def close_map(pool):
    return {r["ticker"]: ((HV.fetch_px(r["ticker"], offline=True) or {}).get("close") or {})
            for r in pool}


# ══════════════════════════════════════════════════════════════════════════════
# 0 reconcile — 検査器を信じる前に検査器を検算する
# ══════════════════════════════════════════════════════════════════════════════
def sec_reconcile(invs):
    out = {"note": "登録セルを在庫から独立に組み直し、hist_val2_dd5.json と突合せる。"
                   "**食い違いが1件でもあればこの器の結論は無効**"}
    ref = json.load(open(os.path.join(OUT, "hist_val2_dd5.json"), encoding="utf-8"))
    mism = []
    per = {}
    for y in VINTAGES:
        d = invs[y]
        pool = R.pools_for(d["rows"])["P_wide"]
        dd, why = dd_for(pool)
        row = {}
        for thr in (THR, THR2):
            st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= thr]
            pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > thr]
            c = cellstat([r["tr_cagr"] for r in st], [r["tr_cagr"] for r in pa],
                         [r["tr_cagr"] for r in pool], round(len(st) / len(pool), 4))
            row[f"{thr:+.2f}"] = c
            rv = ref["verdict"][f"{thr:.2f}"]["per_vintage"][str(y)]
            for k_mine, k_ref in (("ratio", "c1_ratio"), ("stop_numer", "c1_numer"),
                                  ("c1", "c1"), ("c2", "c2"), ("c4", "c4")):
                if c[k_mine] != rv[k_ref]:
                    mism.append(f"{y}/{thr}: {k_mine} mine={c[k_mine]} ref={rv[k_ref]}")
        row["coverage"] = round(len(dd) / len(pool), 4)
        row["missing_why"] = why
        per[y] = row
    out["per_vintage"] = per
    out["mismatches_vs_hist_val2_dd5"] = mism
    out["reproduced"] = (not mism)

    # 月足基準への付け替え（この器の内部基準）と、符号がひっくり返る社の実数
    y = 2013
    pool = R.pools_for(invs[y]["rows"])["P_wide"]
    A = adj_map(pool)
    diffs, flips = [], []
    for r in pool:
        m = seg(A[r["ticker"]], r["px_month"], END_M)
        if m is None:
            continue
        diffs.append(m - r["tr_cagr"])
        if (m < 0) != (r["tr_cagr"] < 0):
            flips.append({"ticker": r["ticker"], "inv": r["tr_cagr"], "monthly": round(m, 4)})
    ad = sorted(abs(x) for x in diffs)
    out["basis_monthly_vs_inventory_2013"] = {
        "n": len(diffs), "median_diff": round(statistics.median(diffs), 5),
        "abs_p50": round(ad[len(ad) // 2], 5), "abs_p90": round(ad[int(len(ad) * .9)], 5),
        "abs_max": round(ad[-1], 5), "sign_flips": len(flips), "flip_rows": flips,
        "why": "在庫は日次アンカー(2013-07-01→2026-08-04)、この器は月足(2013-06→2026-07)。"
               "**主・結果指標が符号の検定なので、この差は分子を直接動かす**"}

    # 結果の基準を替えたら細胞はどう動くか（配当込み ↔ 配当なし・同じ社・同じ dd5）
    C = close_map(pool)
    dd, _ = dd_for(pool)
    variants = {}
    for nm, S in (("adjclose(配当込み・登録どおり)", A), ("close(配当なし)", C)):
        f = (lambda rr, SS=S: seg(SS[rr["ticker"]], "2013-06", END_M))
        st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= THR]
        pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > THR]
        variants[nm] = cellstat([f(r) for r in st], [f(r) for r in pa],
                                [f(r) for r in pool], round(len(st) / len(pool), 4))
    out["outcome_basis_2013_-0.30"] = dict(
        variants,
        note="配当の有無で濃縮が動くのは、配当を足すと元本割れから外れる社が**通過群に偏る**から。"
             "登録は adjclose なのでこれは仕様違反ではないが、**線の上に載っている**ことの証拠")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 1 calendar — 暦のレジームで割る（3ビンテージ共通の暦区間）
# ══════════════════════════════════════════════════════════════════════════════
CAL = [
    ("pre_covid",   None,      "2020-01", "アンカー→2020-01（COVID前）"),
    ("covid_crash", "2020-01", "2020-03", "2020-01→2020-03（暴落・年率換算しない）"),
    ("covid_recov", "2020-03", "2021-12", "2020-03→2021-12（回復・金融緩和）"),
    ("derating",    "2021-12", "2022-09", "2021-12→2022-09（金利上昇の倍率圧縮・年率換算しない）"),
    ("ai",          "2022-09", END_M,     "2022-09→2026-07（AI期）"),
    ("full_monthly", None,     END_M,     "アンカー→2026-07（月足の全期間・この器の基準）"),
]


def sec_calendar(invs):
    per = {}
    for y in VINTAGES:
        d = invs[y]
        pool = R.pools_for(d["rows"])["P_wide"]
        A = adj_map(pool)
        dd, _ = dd_for(pool)
        anchor = Counter(r["px_month"] for r in pool).most_common(1)[0][0]
        rows = {}
        for thr in (THR, THR2):
            st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= thr]
            pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > thr]
            sr = round(len(st) / len(pool), 4)
            cells = {}
            for nm, a, b, note in CAL:
                aa = a or anchor
                if mdiff(aa, b) <= 0:
                    continue
                f = (lambda rr: seg(A[rr["ticker"]], aa, b))
                cells[nm] = dict(cellstat([f(r) for r in st], [f(r) for r in pa],
                                          [f(r) for r in pool], sr), window=f"{aa}→{b}", note=note)
            rows[f"{thr:+.2f}"] = cells
        per[y] = {"anchor": anchor, "cells": rows}
    return {"note": "**暦の区間は3ビンテージで共通**。dd5 は各ビンテージ自身のアンカーで測る。"
                    "区間が1年未満のもの(covid_crash/derating)は年率換算していないので、"
                    "他の区間と水準を比べないこと（符号＝元本割れの比較だけが意味を持つ）",
            "per_vintage": per}


# ══════════════════════════════════════════════════════════════════════════════
# 2 decay — アンカーからの経過で割る／ビンテージ間で重ならない区間
# ══════════════════════════════════════════════════════════════════════════════
def sec_decay(invs):
    per = {}
    for y in VINTAGES:
        d = invs[y]
        pool = R.pools_for(d["rows"])["P_wide"]
        A = adj_map(pool)
        dd, _ = dd_for(pool)
        anchor = Counter(r["px_month"] for r in pool).most_common(1)[0][0]
        mid5 = f"{int(anchor[:4]) + 5:04d}-{anchor[5:7]}"
        wins = [("y1_5", anchor, mid5, "アンカー→+5年"),
                ("y6_end", mid5, END_M, "+5年→2026-07")]
        rows = {}
        for thr in (THR, THR2):
            st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= thr]
            pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > thr]
            sr = round(len(st) / len(pool), 4)
            cells = {}
            for nm, a, b, note in wins:
                if mdiff(a, b) < 12:
                    continue
                f = (lambda rr: seg(A[rr["ticker"]], a, b))
                cells[nm] = dict(cellstat([f(r) for r in st], [f(r) for r in pa],
                                          [f(r) for r in pool], sr), window=f"{a}→{b}", note=note)
            rows[f"{thr:+.2f}"] = cells
        per[y] = {"anchor": anchor, "cells": rows}

    # ── 重ならない区間 ─────────────────────────────────────────────────────
    # 2013 の窓は 2013-06→2026-07。2015 は 2015-06→、2018 は 2018-06→。
    # **2013-06→2015-06 は 2013 だけが持ち、2015-06→2018-06 は 2013/2015 だけが持つ。**
    # 2018-06→2026-07 は3ビンテージが共有する（＝独立でない部分）。
    d13 = invs[2013]
    pool = R.pools_for(d13["rows"])["P_wide"]
    A = adj_map(pool)
    dd, _ = dd_for(pool)
    disj = {}
    for nm, a, b in (("exclusive_to_2013", "2013-06", "2015-06"),
                     ("shared_2013_2015", "2015-06", "2018-06"),
                     ("shared_all_three", "2018-06", END_M)):
        for thr in (THR,):
            st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= thr]
            pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > thr]
            f = (lambda rr: seg(A[rr["ticker"]], a, b))
            disj[nm] = dict(cellstat([f(r) for r in st], [f(r) for r in pa],
                                     [f(r) for r in pool], round(len(st) / len(pool), 4)),
                            window=f"{a}→{b}")
    return {"per_vintage": per,
            "disjoint_2013": disj,
            "note": "重ならない区間の切り分け。**2018-06→2026-07 は3ビンテージが共有する**ので、"
                    "そこで濃縮が 2.0 に届かないなら 2015/2018 の不合格は独立な反証ではなく"
                    "『同じ期間を見ているから同じ答えが出た』にすぎない"}


# ══════════════════════════════════════════════════════════════════════════════
# 3 vintages5 — 2016/2017 を足した5ビンテージ列（判定には使わない）
# ══════════════════════════════════════════════════════════════════════════════
def sec_vintages5():
    """**プールは quality を課さない**（2016/2017 は hist_val 在庫が無く質実証を再現できない）。
    比較を成立させるため 2013/2015/2018 も同じ無条件プールで並べる。
    ＝事前登録の判定プール(P_wide)とは別物なので、**合否には一切使わない**。
    """
    # **リターン在庫の選び方は hist_val の join と同じにする。**
    #   retro_returns_2013.json は70社の抽出で、_all が956社。片方だけ読むと
    #   『139社の標本』と『946社の母集団』を並べることになる＝基準の違う二つを並べる型。
    #   だから hist_val_{y}.json の join.returns_src をそのまま使い、
    #   hist_val 在庫が無い 2016/2017 だけ素の retro_returns_{y}.json を使う。
    SRC = {y: json.load(open(os.path.join(OUT, f"hist_val_{y}.json"),
                             encoding="utf-8"))["join"]["returns_src"] for y in VINTAGES}
    SRC[2016] = ["retro_returns_2016.json"]
    SRC[2017] = ["retro_returns_2017.json"]

    per = {}
    for y in (2013, 2015, 2016, 2017, 2018):
        merged, used = {}, []
        for fn in SRC[y]:
            fp = os.path.join(OUT, fn)
            if not os.path.exists(fp):
                continue
            used.append(fn)
            for r in json.load(open(fp, encoding="utf-8"))["rows"]:
                merged.setdefault(r["ticker"], r)        # 先に来たファイルを優先（join と同じ）
        if not merged:
            per[y] = {"skip": "returns 在庫なし"}
            continue
        p = ", ".join(used)
        allrows = list(merged.values())
        modal = Counter(round(r["years"], 2) for r in allrows
                        if r.get("years")).most_common(1)[0][0]
        anchor = f"{y:04d}-06"
        rows = [r for r in allrows
                if r.get("tr_cagr") is not None and not r.get("stale")
                and round(r.get("years") or 0, 2) == modal]
        dd, why = {}, Counter()
        for r in rows:
            adj = (HV.fetch_px(r["ticker"], offline=True) or {}).get("adj") or {}
            x, w = R.drawdown(adj, anchor, R.DD_WIN, R.DD_MIN_OBS)
            if x is None:
                why[(w or "?").split("(")[0]] += 1
            else:
                dd[r["ticker"]] = x
        cells = {}
        for thr in (THR, THR2):
            st = [r for r in rows if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= thr]
            pa = [r for r in rows if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > thr]
            cells[f"{thr:+.2f}"] = cellstat([r["tr_cagr"] for r in st],
                                            [r["tr_cagr"] for r in pa],
                                            [r["tr_cagr"] for r in rows],
                                            round(len(st) / len(rows), 4) if rows else None)
        per[y] = {"anchor": anchor, "N": len(rows), "years": modal,
                  "coverage": round(len(dd) / len(rows), 4) if rows else None,
                  "missing_why": dict(why), "cells": cells,
                  "src": p}
    return {"note": "**参考のみ・判定に使わない**。プールに質実証を課していない（2016/2017 は "
                    "hist_val 在庫が無く再現できないため）。5ビンテージを同じ無条件プールで並べ、"
                    "濃縮が窓の暦構成とともにどう動くかを見る",
            "per_vintage": per}


# ══════════════════════════════════════════════════════════════════════════════
# 4 sector — SIC2 で層別（Mantel-Haenszel 調整 ＋ 層内置換）
# ══════════════════════════════════════════════════════════════════════════════
def sec_sector(invs, n_perm, seed):
    sic = {r["ticker"]: r.get("sic2") for r in
           json.load(open(os.path.join(OUT, "retro_sic.json"), encoding="utf-8"))["rows"]}
    per = {}
    for y in VINTAGES:
        pool = R.pools_for(invs[y]["rows"])["P_wide"]
        dd, _ = dd_for(pool)
        rows = [r for r in pool if dd.get(r["ticker"]) is not None]
        cov = sum(1 for r in rows if sic.get(r["ticker"]))
        out = {}
        for thr in (THR, THR2):
            use = [r for r in rows if sic.get(r["ticker"])]
            byS = defaultdict(list)
            for r in use:
                byS[sic[r["ticker"]]].append(r)
            n_st = obs = exp = 0
            strata = {}
            for s, rs in byS.items():
                st = [r for r in rs if dd[r["ticker"]] <= thr]
                if not st:
                    continue
                pb = sum(1 for r in rs if r["tr_cagr"] < 0) / len(rs)
                o = sum(1 for r in st if r["tr_cagr"] < 0)
                n_st += len(st)
                obs += o
                exp += len(st) * pb
                strata[s] = {"n": len(rs), "n_stop": len(st), "p_base": round(pb, 4),
                             "obs_loss": o, "exp_loss": round(len(st) * pb, 2)}
            # 層内置換: 各層で同じ社数を無作為に選ぶ
            rnd = random.Random(seed)
            hits = 0
            crude_base = sum(1 for r in use if r["tr_cagr"] < 0) / len(use)
            for _ in range(n_perm):
                o2 = 0
                for s, rs in byS.items():
                    k = sum(1 for r in rs if dd[r["ticker"]] <= thr)
                    if not k:
                        continue
                    o2 += sum(1 for r in rnd.sample(rs, k) if r["tr_cagr"] < 0)
                if o2 >= obs:
                    hits += 1
            out[f"{thr:+.2f}"] = {
                "n_pool_with_sic": len(use), "n_stop": n_st,
                "obs_loss": obs, "exp_loss_sector_adj": round(exp, 2),
                "ratio_sector_adjusted": round(obs / exp, 2) if exp else None,
                "ratio_crude": round((obs / n_st) / crude_base, 2) if n_st and crude_base else None,
                "p_within_sector_permutation": round(hits / n_perm, 4),
                "n_strata_with_stop": len(strata),
                "strata": dict(sorted(strata.items(), key=lambda kv: -kv[1]["n_stop"])),
            }
        per[y] = {"sic_coverage": round(cov / len(rows), 4) if rows else None, "cells": out}
    return {"note": "SIC2 は SEC submissions の**現在の**登録分類（時点付きではない）＝粗い層別専用。"
                    "Mantel-Haenszel 型: 期待値 = Σ(層の止めた社数 × 層のベース元本割れ率)。"
                    "調整比が粗比とほぼ同じなら、濃縮は業種構成で説明できない",
            "per_vintage": per}


# ══════════════════════════════════════════════════════════════════════════════
# 5 survival — 退場社込みの母集団（時期・挟み込み・基準への効き）
# ══════════════════════════════════════════════════════════════════════════════
def _left_tail_read(s, r):
    """生存者と復元した退場社の元本割れを比べた読み（向きは数字で決める）。"""
    ps, pr = s.get("p_loss"), r.get("p_loss")
    if ps is None or pr is None:
        return "比べられない（どちらかが空）"
    head = (f"復元した退場{r.get('n')}社の元本割れ {pr:.1%} / 生存者{s.get('n')}社 {ps:.1%}。")
    if pr > ps:
        return head + ("退場社のほうが元本割れが**多い**＝生存者だけの母集団は左尾を**隠している**"
                       "（生存バイアスは素朴な向きに効いている）")
    if pr < ps:
        return head + ("退場社のほうが元本割れが**少ない**＝生存バイアスは"
                       "『左尾を隠している』という素朴な向きには効いていない")
    return head + "同じ＝向きは決まらない"


def survival_ledger_entry(sv):
    """反証の帳簿『退場社を戻しても判定は変わらない』を**数字から**組む（2026-09-23）。

    旧版は『1.96（下端）/ 1.31（上端）・退場45社の元本割れ 17.8% ＜ 生存者 25.4%』を固定文で持ち、
    退場日の是正（out/retro_exit_fix_2013.json）の後も古い数字を引用し続けた。
    """
    b = sv["bounding_price_only"]
    lo = b["na(72社)を全部通過させる(下端)"]
    hi = b["na(72社)を全部止める(上端)"]
    lt = sv["left_tail_survivor_vs_exit"]
    ok_lo, ok_hi = (lo.get("ratio") or 0) >= 2.0, (hi.get("ratio") or 0) >= 2.0
    verdict = ("どちらも不合格" if not (ok_lo or ok_hi) else
               "どちらも基準1（2.0倍）に届く" if (ok_lo and ok_hi) else "片側だけ 2.0倍 に届く")
    return {
        "fact": {k: {"ratio": v["ratio"], "stop_numer": v["stop_numer"],
                     "stop_rate": v["stop_rate"], "n_na": v.get("n_na")}
                 for k, v in b.items()},
        "read": (f"挟み込み {lo.get('ratio')}（下端・na {lo.get('n_na')}社は全部通過）/ "
                 f"{hi.get('ratio')}（上端・na は全部止める）で{verdict}。"
                 f"{lt['read']}"),
    }


def sec_survival(invs, n_perm, seed):
    p = os.path.join(OUT, "retro_delisted_secpx_2013.json")
    if not os.path.exists(p):
        return {"skip": "out/retro_delisted_secpx_2013.json が無い"}
    D = json.load(open(p, encoding="utf-8"))
    # **kind=='対象外'（上場株式が無い提出体）は母集団から外す**。
    # 兄弟器 hist_val2_selfrel_delisted.py が 549社 と数えているのと同じ定義に揃える
    # ——同じ台帳を見る二つの検査器が違うことを言ってはいけない(v9.9.65)。
    q = [r for r in D["rows"] if r.get("quality") and r.get("kind") != "対象外"]
    surv = [r for r in q if r.get("kind") == "survivor"]
    rest = [r for r in q if r.get("kind") == "退場(測定)"]
    cens = [r for r in q if r.get("kind") == "打ち切り"]

    # ── (a) 退場の時期 ─────────────────────────────────────────────────────
    def yr(r):
        e = r.get("exit_date_eff") or ""
        return e[:4] if len(e) >= 4 else None
    by_year = Counter(yr(r) for r in rest if yr(r))
    ex_all = [r for r in q if r.get("kind") in ("退場(測定)", "打ち切り")]
    by_year_all = Counter(yr(r) for r in ex_all if yr(r))
    early = sum(n for k, n in by_year_all.items() if k and k < "2019")
    late = sum(n for k, n in by_year_all.items() if k and k >= "2019")

    # ── (b) 退場社に dd5 は作れるか（原本で確かめる）────────────────────────
    dd_ok, dd_ng, why = 0, 0, Counter()
    for r in rest:
        adj = (HV.fetch_px(r.get("ticker") or "", offline=True) or {}).get("adj") or {}
        if not adj:
            why["no_px_cache(ticker不明 or Yahoo履歴なし)"] += 1
            dd_ng += 1
            continue
        x, w = R.drawdown(adj, "2013-06", R.DD_WIN, R.DD_MIN_OBS)
        if x is None:
            why[(w or "?").split("(")[0]] += 1
            dd_ng += 1
        else:
            dd_ok += 1

    # ── (c) 挟み込み ───────────────────────────────────────────────────────
    # **兄弟器 night/hist_val2_delisted.py とまったく同じプールの作り方**を使う
    # （ticker は retro_delisted_2013.json の ticker_hist / cands 先頭で解決）。
    # 同じ台帳を見る二つの検査器が違うことを言ってはいけない(v9.9.65)ので、
    # 独立に組み直したうえで**兄弟器の出力と数値照合する**。
    dl = json.load(open(os.path.join(OUT, "retro_delisted_2013.json"), encoding="utf-8"))
    info = {r["cik"]: r for r in dl["rows"]}
    pool_d = []
    for r in q:
        if r.get("px_cagr") is None:
            continue                      # 打ち切り＝リターンそのものが不明
        i = info.get(r["cik"], {})
        t = i.get("ticker_hist") or (i.get("cands") or [None])[0]
        dd = None
        if t:
            dd, _ = R.drawdown((HV.fetch_px(t, offline=True) or {}).get("adj") or {},
                               "2013-06", R.DD_WIN, R.DD_MIN_OBS)
        pool_d.append({"cik": r["cik"], "ticker": t, "ret": r["px_cagr"],
                       "dd": dd, "survivor": r.get("status") == "survivor"})

    def bound(na_stopped, thr=THR):
        """dd5 が作れない社(na)を**両極端**に振る。na は 退場社（2026-08-10 は45社・是正後は96社）だけでなく、
        survivor 側の欠測も含む——片方だけ振ると『測れない』の扱いが群で割れる。"""
        st = [x for x in pool_d if x["dd"] is not None and x["dd"] <= thr]
        pa = [x for x in pool_d if x["dd"] is not None and x["dd"] > thr]
        na = [x for x in pool_d if x["dd"] is None]
        stv = [x["ret"] for x in st] + ([x["ret"] for x in na] if na_stopped else [])
        pav = [x["ret"] for x in pa] + ([] if na_stopped else [x["ret"] for x in na])
        return dict(cellstat(stv, pav, [x["ret"] for x in pool_d],
                             round(len(stv) / len(pool_d), 4) if pool_d else None),
                    n_rows=len(pool_d), n_na=len(na),
                    n_na_restored=sum(1 for x in na if not x["survivor"]))

    bnd = {"na(72社)を全部通過させる(下端)": bound(False),
           "na(72社)を全部止める(上端)": bound(True),
           "-0.40_下端": bound(False, THR2), "-0.40_上端": bound(True, THR2)}

    # 兄弟器との照合（食い違えばそれ自体が報告事項）
    sib_path = os.path.join(OUT, "hist_val2_delisted.json")
    sib_check = {"checked": False}
    if os.path.exists(sib_path):
        S = json.load(open(sib_path, encoding="utf-8"))
        c = (S.get("cells") or {}).get("-0.30") or {}
        mism = []
        pairs = [("na(72社)を全部通過させる(下端)", "下端_naは全部通過"),
                 ("na(72社)を全部止める(上端)", "上端_naは全部止める")]
        for mine_k, sib_k in pairs:
            sv_ = c.get(sib_k) or {}
            j = sv_.get("judge") or {}
            if bnd[mine_k]["stop_n"] != sv_.get("stop"):
                mism.append(f"{sib_k}: stop mine={bnd[mine_k]['stop_n']} sib={sv_.get('stop')}")
            if bnd[mine_k]["ratio"] != j.get("c1_ratio"):
                mism.append(f"{sib_k}: ratio mine={bnd[mine_k]['ratio']} sib={j.get('c1_ratio')}")
            if bnd[mine_k]["stop_numer"] != j.get("c1_numer"):
                mism.append(f"{sib_k}: numer mine={bnd[mine_k]['stop_numer']} sib={j.get('c1_numer')}")
        sib_check = {"checked": True, "sibling": "out/hist_val2_delisted.json",
                     "mismatches": mism, "agree": not mism}

    # ── (d) 打ち切り130社の3通りの読み（左尾のベースがどこまで動くか）──────────
    nonma = sum(1 for r in cens if r.get("exit_kind") not in ("acquired", "going_private"))
    n_loss_meas = sum(1 for r in q if r.get("px_cagr") is not None and r["px_cagr"] < 0)
    N = len(q)
    readings = {
        "下限(打ち切りは元本割れしない)": {"n_loss": n_loss_meas, "N": N,
                                 "rate": round(n_loss_meas / N, 4)},
        "中間(非M&Aの打ち切りだけ元本割れ)": {"n_loss": n_loss_meas + nonma, "N": N,
                                    "rate": round((n_loss_meas + nonma) / N, 4),
                                    "n_nonma": nonma},
        "上限(打ち切りは全部元本割れ)": {"n_loss": n_loss_meas + len(cens), "N": N,
                                "rate": round((n_loss_meas + len(cens)) / N, 4)},
    }

    # ── (e) 生存者だけの母集団と、退場込みの母集団の左尾の差 ─────────────────
    sv = [r["px_cagr"] for r in surv if r.get("px_cagr") is not None]
    rv = [r["px_cagr"] for r in rest if r.get("px_cagr") is not None]
    return {
        "universe": {"n_quality": N, "survivor": len(surv), "restored_exits": len(rest),
                     "censored": len(cens),
                     "n_seen_by_prereg_P_wide": len(R.pools_for(invs[2013]["rows"])["P_wide"])},
        "exit_timing": {"restored_by_year": dict(sorted(by_year.items())),
                        "all_exits_by_year": dict(sorted((k, v) for k, v in by_year_all.items() if k)),
                        "before_2019": early, "from_2019": late,
                        "why_it_matters": "退場が窓の前半に偏っていれば、生存者だけの母集団は"
                                          "**前半の左尾を落としている**＝前半で効く指標ほど有利に見える"},
        "dd5_on_exits": {"computable": dd_ok, "not_computable": dd_ng, "why": dict(why),
                         "verdict": "退場社に dd5 は当てられない（Yahoo が pre-2013 の月足を"
                                    "持っていない）。だから点推定を出さず挟み込みで裁く"},
        "bounding_price_only": bnd,
        "sibling_agreement": sib_check,
        "base_readings_price_only": readings,
        "left_tail_survivor_vs_exit": {
            "survivor": grp(sv), "restored_exit": grp(rv),
            # ★2026-09-23: 読みを**数字から組む**（旧版は『退場社のほうが少ない』を前提にした固定文で、
            #   退場日の是正〔retro_exit_fix_2013〕で向きが反転しても古い読みが残った）
            "read": _left_tail_read(grp(sv), grp(rv))},
        "basis": D.get("basis"),
        "note": "この節は price-only（配当なし）。**adjclose の tr_cagr と割らないこと**",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6 mechanism — 「深さ」なのか「高値の古さ」なのか（dd5 が何を拾っているか）
# ══════════════════════════════════════════════════════════════════════════════
def peak_of(adj, m0):
    """dd5 と**同じ窓・同じ観測要件**で高値の月と経過月を返す。"""
    ms = [R.month_sub(m0, i) for i in range(R.DD_WIN - 1, -1, -1)]
    vals = [(m, adj[m]) for m in ms if m in adj and adj[m] and adj[m] > 0]
    if len(vals) < R.DD_MIN_OBS:
        return None, None
    pk = max(vals, key=lambda kv: kv[1])[0]
    return pk, mdiff(pk, m0)


def sec_mechanism(invs):
    """止めた群を『高値が古い(≥48ヶ月)』と『高値が新しい』に割る。

    **なぜこれを見るか**——dd5 の窓は60ヶ月。アンカーが 2013-06 なら窓は 2008-07..2013-06 で
    **GFCの天井が窓の中に入る**。つまり2013年の『5年高値から30%下』は
    『**5年たってもGFC前の高値に戻っていない**』とほぼ同義になりうる。
    2015(2010-07..2015-06)・2018(2013-07..2018-06)の窓には危機が入らないので、
    同じ状態が存在しない。**同じ式が、暦の位置によって違うものを測っている**かを確かめる。
    """
    per = {}
    for y in VINTAGES:
        pool = R.pools_for(invs[y]["rows"])["P_wide"]
        anchor = Counter(r["px_month"] for r in pool).most_common(1)[0][0]
        rows = []
        for r in pool:
            adj = (HV.fetch_px(r["ticker"], offline=True) or {}).get("adj") or {}
            x, _ = R.drawdown(adj, r["px_month"], R.DD_WIN, R.DD_MIN_OBS)
            if x is None:
                continue
            pk, age = peak_of(adj, r["px_month"])
            rows.append({"t": r["ticker"], "dd": x, "tr": r["tr_cagr"], "peak": pk, "age": age})
        base = sum(1 for r in rows if r["tr"] < 0) / len(rows)
        out = {}
        for thr in (THR, THR2):
            st = [r for r in rows if r["dd"] <= thr]
            old = [r for r in st if r["age"] is not None and r["age"] >= 48]
            fresh = [r for r in st if r["age"] is not None and r["age"] < 48]

            def blk(g):
                if not g:
                    return {"n": 0}
                nl = sum(1 for r in g if r["tr"] < 0)
                return {"n": len(g), "n_loss": nl, "p_loss": round(nl / len(g), 4),
                        "ratio": round((nl / len(g)) / base, 2) if base else None,
                        "ci95": ci(nl, len(g)),
                        "median": round(statistics.median([r["tr"] for r in g]), 4),
                        "tickers": [r["t"] for r in g]}
            out[f"{thr:+.2f}"] = {
                "base_p_loss": round(base, 4),
                "stopped_all": blk(st),
                "peak_age_ge_48m": blk(old),
                "peak_age_lt_48m": blk(fresh),
                "peak_year_hist_stopped": dict(sorted(Counter(
                    r["peak"][:4] for r in st if r["peak"]).items())),
            }
            # 「高値の古さ」だけを指標にしたらどうか（dd5 の代理仮説）
            for cut in (24, 36, 48):
                g = [r for r in rows if r["age"] is not None and r["age"] >= cut]
                nl = sum(1 for r in g if r["tr"] < 0)
                out[f"{thr:+.2f}"][f"peak_age_alone_ge_{cut}m"] = {
                    "n": len(g), "stop_rate": round(len(g) / len(rows), 4),
                    "n_loss": nl, "ratio": round((nl / len(g)) / base, 2) if g and base else None}
        per[y] = {"anchor": anchor, "window": f"{R.month_sub(anchor, R.DD_WIN - 1)}..{anchor}",
                  "n_measurable": len(rows), "cells": out}
    return {"note": "dd5 の窓は60ヶ月。**2013年のアンカーだけが窓の中にGFCの天井を含む**"
                    "（窓 2008-07..2013-06）。だから2013年の『5年高値から30%下』は"
                    "『5年たってもGFC前の高値に戻っていない』を拾いうる。"
                    "2015/2018 の窓には危機が入らない＝同じ状態が存在しない",
            "per_vintage": per}


# ══════════════════════════════════════════════════════════════════════════════
# 7 heterogeneity — ビンテージ間のばらつきは本物か（信頼区間と正確検定）
# ══════════════════════════════════════════════════════════════════════════════
def fisher_p(a, b, c, d):
    """2x2 の両側 Fisher 正確確率。a,b = 群1の(事象,非事象) / c,d = 群2。"""
    n = a + b + c + d
    r1, r2 = a + b, c + d
    c1 = a + c

    def pr(x):
        return (math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1))
    p0 = pr(a)
    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    return round(sum(pr(x) for x in range(lo, hi + 1) if pr(x) <= p0 + 1e-12), 4)


def sec_heterogeneity(invs):
    cells = {}
    for y in VINTAGES:
        pool = R.pools_for(invs[y]["rows"])["P_wide"]
        dd, _ = dd_for(pool)
        for thr in (THR, THR2):
            st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= thr]
            nl = sum(1 for r in st if r["tr_cagr"] < 0)
            nb = sum(1 for r in pool if r["tr_cagr"] < 0)
            cells.setdefault(f"{thr:+.2f}", {})[y] = {
                "n_stop": len(st), "n_loss": nl,
                "p_stop": round(nl / len(st), 4) if st else None,
                "ci95_p_stop": ci(nl, len(st)) if st else None,
                "base_n": len(pool), "base_loss": nb, "base_p": round(nb / len(pool), 4),
                "ratio": round((nl / len(st)) / (nb / len(pool)), 2) if st and nb else None,
                # ベースに対する片側 Fisher（この1セルだけを見たときの p 値）
                "fisher_p_vs_pool": fisher_p(nl, len(st) - nl, nb - nl,
                                             (len(pool) - len(st)) - (nb - nl)),
            }
    # 2013 の止めた群 vs 2015/2018 の止めた群（濃縮の差そのものが本物か）
    pair = {}
    for thr, per in cells.items():
        a = per[2013]
        for y in (2015, 2018):
            b = per[y]
            pair[f"{thr}_2013_vs_{y}"] = {
                "p_stop_2013": a["p_stop"], f"p_stop_{y}": b["p_stop"],
                "fisher_p": fisher_p(a["n_loss"], a["n_stop"] - a["n_loss"],
                                     b["n_loss"], b["n_stop"] - b["n_loss"]),
                "read": "p が大きい＝『2013だけ強い』は標本のばらつきで説明できてしまう"}
    return {"cells": cells, "vintage_pairs": pair,
            "note": "分子が4〜16社の世界なので、区間は必ず併記する。"
                    "**信頼区間が重なるなら『2013だけ効いた』も『どれも効かない』も同じデータと整合する**"}


# ══════════════════════════════════════════════════════════════════════════════
# 8 dispersion — 止めた群は「悪い群」か「ばらつく群」か／左尾は誰が持っていたか
# ══════════════════════════════════════════════════════════════════════════════
def sec_dispersion(invs):
    """遮断器の目的は**恒久毀損を踏まないこと**。だから
       (a) 止めた群は本当に『悪い』のか、それとも上下に広いだけか
       (b) 実際に恒久毀損した社は止めた群に居たのか
    を数える。(b) は事前登録v2が**従指標**に落とした量だが、
    『何のための遮断器か』を答えるのはこちらである。
    """
    per = {}
    for y in VINTAGES:
        d = invs[y]
        pool = R.pools_for(d["rows"])["P_wide"]
        years = d["join"]["modal_years"]
        dd, _ = dd_for(pool)
        st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= THR]
        pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > THR]
        na = [r for r in pool if dd.get(r["ticker"]) is None]

        def blk(g):
            v = sorted(r["tr_cagr"] for r in g)
            if not v:
                return {"n": 0}
            return {"n": len(v),
                    "p_loss": round(sum(1 for x in v if x < 0) / len(v), 4),
                    "p_win15": round(sum(1 for x in v if x >= 0.15) / len(v), 4),
                    "p_perm": round(sum(1 for x in v if x <= -0.15) / len(v), 4),
                    "n_perm": sum(1 for x in v if x <= -0.15),
                    "median": round(statistics.median(v), 4),
                    "p25": round(v[len(v) // 4], 4), "p75": round(v[3 * len(v) // 4], 4),
                    "sd": round(statistics.pstdev(v), 4),
                    # 等ウェイト買い持ちは gate_test の実装をそのまま呼ぶ（(値, 社数) を返す）
                    "ew_cagr": (lambda z: round(z[0], 4) if z[0] is not None else None)(
                        GT.ew_cagr(g, years)),
                    "worst": round(v[0], 4)}
        perm = sorted([r for r in pool if r["tr_cagr"] <= -0.15], key=lambda r: r["tr_cagr"])

        def where(r):
            t = r["ticker"]
            if dd.get(t) is None:
                return "na"
            return "stopped" if dd[t] <= THR else "passed"
        per[y] = {"stopped": blk(st), "passed": blk(pa), "na": blk(na),
                  "perm_impairments": {"total": len(perm),
                                       "by_group": dict(Counter(where(r) for r in perm)),
                                       "stop_rate_pool": round(len(st) / len(pool), 4),
                                       "worst5": [{"ticker": r["ticker"],
                                                   "tr_cagr": round(r["tr_cagr"], 4),
                                                   "group": where(r),
                                                   "dd5": (round(dd[r["ticker"]], 4)
                                                           if dd.get(r["ticker"]) is not None
                                                           else None)}
                                                  for r in perm[:5]]}}
    tot = Counter()
    for y in VINTAGES:
        for k, v in per[y]["perm_impairments"]["by_group"].items():
            tot[k] += v
        tot["total"] += per[y]["perm_impairments"]["total"]
    return {"per_vintage": per, "perm_totals_3vintages": dict(tot),
            "note": "p_win15 = 年15%+ の割合。**止めた群のほうが高い**なら、遮断器は"
                    "『悪い群』ではなく『ばらつく群』を切っている＝上側も一緒に切っている。"
                    "worst は各群の最悪。**最悪の社がどちらに居たか**が遮断器の値打ちを決める"}


# ══════════════════════════════════════════════════════════════════════════════
# 9 horizon — 濃縮比の分母（コホートのベース）は何で決まるか
# ══════════════════════════════════════════════════════════════════════════════
def sec_horizon(invs):
    """**基準1は比であり、分母はコホートのベース元本割れ率**。
    ビンテージごとに 15.9 / 18.1 / 24.8% と違うので、止めた群の成績が同じでも
    比は動く。ここでは 2013 の社と dd5 を固定して**終端だけ**を動かし、
    比が窓の長さでどう動くかを実測する（＝比の安定性そのものの検査）。
    """
    d = invs[2013]
    pool = R.pools_for(d["rows"])["P_wide"]
    A = adj_map(pool)
    dd, _ = dd_for(pool)
    ends = [("2016-06", 3.0), ("2018-06", 5.0), ("2019-06", 6.0), ("2020-06", 7.0),
            ("2021-07", 8.09), ("2022-06", 9.0), ("2023-06", 10.0), ("2024-07", 11.10),
            ("2025-06", 12.0), (END_M, 13.09)]
    rows = []
    for end, yy in ends:
        f = (lambda rr: seg(A[rr["ticker"]], "2013-06", end, annualize=False))
        st = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] <= THR]
        pa = [r for r in pool if dd.get(r["ticker"]) is not None and dd[r["ticker"]] > THR]
        c = cellstat([f(r) for r in st], [f(r) for r in pa], [f(r) for r in pool],
                     round(len(st) / len(pool), 4))
        c["end"], c["years"] = end, yy
        c["same_length_as"] = ("2018年ビンテージ(8.09年)" if abs(yy - 8.09) < .01 else
                               "2015年ビンテージ(11.10年)" if abs(yy - 11.10) < .01 else None)
        rows.append(c)
    return {"rows_2013_cohort": rows,
            "cross_vintage_bases": {y: {"base_p_loss": round(
                sum(1 for r in R.pools_for(invs[y]["rows"])["P_wide"] if r["tr_cagr"] < 0)
                / len(R.pools_for(invs[y]["rows"])["P_wide"]), 4),
                "years": invs[y]["join"]["modal_years"]} for y in VINTAGES},
            "note": "同じ社・同じ dd5 で終端だけを動かすと、2013コホートの比は 2.07〜3.06 で"
                    "**窓の長さでは説明できない**。よってビンテージ間の比の差(2.79/1.47/1.79)は"
                    "窓の長さではなく**入口の暦（コホートのベース）**が作っている"}


# ══════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val2_regime.json"))
    ap.add_argument("--perm", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260810)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--only-survival", action="store_true",
                    help="既存の出力を読み、5 survival 節と帳簿のその1項だけを作り直す"
                         "（退場の台帳 retro_delisted_*_2013.json を直したとき。他の節は退場と無関係で、"
                         "全部を回すと価格キャッシュの漂流まで混ざる）")
    a = ap.parse_args()

    invs = load_all()
    if a.only_survival:
        res = json.load(open(a.json, encoding="utf-8"))
        res["survival"] = sec_survival(invs, a.perm, a.seed)
        res["attack_ledger"]["survived"]["退場社を戻しても判定は変わらない"] = \
            survival_ledger_entry(res["survival"])
        res["survival_regenerated"] = {
            "at": __import__("datetime").date.today().isoformat(),
            "why": "退場日の是正（out/retro_exit_fix_2013.json・todo retro_citations_after_exit_fix）の後に "
                   "survival 節だけを作り直した。他の節は 2026-08-10 のまま",
            "px_cache": "dd5 の月足は 2026-09-23 の採取（2026-08-10 の採取とは Yahoo の漂流ぶん違う）。"
                        "EQR・QVCAQ・SALM・BBBY は Yahoo が 2026-07 より前の足を返さなくなったので "
                        "px_guard が採らず dd5 は na（挟み込みの両端に振られる）"}
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        sv = res["survival"]; b = sv["bounding_price_only"]
        print(f"→ {a.json}（survival 節だけ）")
        print(f"[5] 退場: 復元{sv['universe']['restored_exits']} / 挟み込み(-0.30) "
              f"下端{b['na(72社)を全部通過させる(下端)']['ratio']} "
              f"上端{b['na(72社)を全部止める(上端)']['ratio']} / 兄弟器と一致="
              f"{sv['sibling_agreement'].get('agree')}")
        print("   ", sv["left_tail_survivor_vs_exit"]["read"])
        return
    res = {"generated": "2026-08-10", "tool": "night/hist_val2_regime.py",
           "role": "**反証の器**。事前登録v2の判定は hist_val2_dd5.py が一度だけ下しており"
                   "（不合格）、ここでやるのは『惜しい細胞を期間と生存で壊せるか』だけ。"
                   "値・規約・関門・売却規律・配分はいっさい触らない",
           "target_cell": f"dd5 <= {THR} @2013（濃縮2.79倍・分子12社・基準1/2/4/5成立・基準3で不合格）",
           "src_tool_rev": seen_revs(),
           "reconcile": sec_reconcile(invs)}
    if not res["reconcile"]["reproduced"]:
        res["ABORT"] = "登録セルを再現できない。以降の結論は無効"
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        raise SystemExit("■ 再現に失敗した。検査器を先に直すこと:\n  "
                         + "\n  ".join(res["reconcile"]["mismatches_vs_hist_val2_dd5"]))
    res["calendar"] = sec_calendar(invs)
    res["decay"] = sec_decay(invs)
    res["vintages5"] = sec_vintages5()
    res["sector"] = sec_sector(invs, a.perm, a.seed)
    res["mechanism"] = sec_mechanism(invs)
    res["heterogeneity"] = sec_heterogeneity(invs)
    res["dispersion"] = sec_dispersion(invs)
    res["horizon"] = sec_horizon(invs)
    res["survival"] = sec_survival(invs, a.perm, a.seed)

    # ── 反証の帳簿（**壊せた攻撃と、壊せなかった攻撃を同じ場所に書く**）────────────
    hz = res["horizon"]["rows_2013_cohort"]
    v5 = res["vintages5"]["per_vintage"]
    mech = res["mechanism"]["per_vintage"]
    het = res["heterogeneity"]["cells"][f"{THR:+.2f}"]
    res["attack_ledger"] = {
        "broke": {
            "機構が暦に依存する": {
                "fact": {str(y): {"peak_age>=48m": mech[y]["cells"][f"{THR:+.2f}"]
                                  ["peak_age_ge_48m"].get("ratio"),
                                  "peak_age<48m": mech[y]["cells"][f"{THR:+.2f}"]
                                  ["peak_age_lt_48m"].get("ratio")} for y in VINTAGES},
                "read": "**高値が新しい社だけを見ると3ビンテージとも 2.0 に届かない**"
                        "(1.73/1.45/1.49)。超過は『高値が古い社』が持っており、その強さは "
                        "4.85/1.59/2.68 と暦で3倍動く。2013のアンカーの60ヶ月窓だけが "
                        "GFCの天井を含む（2008-07..2013-06）＝**同じ式が暦の位置で違うものを測る**"},
            "5アンカーに広げると2013は特別でなくなる": {
                "fact": {str(y): (v5[y]["cells"][f"{THR:+.2f}"]["ratio"] if "cells" in v5[y] else None)
                         for y in (2013, 2015, 2016, 2017, 2018)},
                "read": "**同じ無条件プール**で5つのアンカーに当てると 1.51〜1.84 の帯に収まり、"
                        "どれも 2.0 に届かない。2013 の 2.79 は『質実証プール ∧ 2013アンカー』の"
                        "**組合せ**でしか出ない"},
            "比の分母は入口の暦": {
                "fact": {"stopped_p_loss": {str(y): het[y]["p_stop"] for y in VINTAGES},
                         "base_p_loss": {str(y): het[y]["base_p"] for y in VINTAGES},
                         "fisher_2013_vs_2018": res["heterogeneity"]["vintage_pairs"]
                         [f"{THR:+.2f}_2013_vs_2018"]["fisher_p"],
                         "fisher_2013_vs_2015": res["heterogeneity"]["vintage_pairs"]
                         [f"{THR:+.2f}_2013_vs_2015"]["fisher_p"]},
                "read": "止めた群の元本割れは 44.4/26.7/44.4% で**統計的に見分けがつかない**"
                        "(2013 vs 2018 は Fisher p=1.00)。比が 2.79/1.47/1.79 と動くのは"
                        "**コホートのベース**が 15.9/18.1/24.8% と動くから。"
                        "基準1は『指標の性能』ではなく『残りの社がどれだけ負けたか』で決まる"},
            "止めているのは悪い群ではなく広い群": {
                "fact": {str(y): {"stop_p_win15": res["dispersion"]["per_vintage"][y]
                                  ["stopped"]["p_win15"],
                                  "pass_p_win15": res["dispersion"]["per_vintage"][y]
                                  ["passed"]["p_win15"],
                                  "stop_worst": res["dispersion"]["per_vintage"][y]
                                  ["stopped"]["worst"],
                                  "pass_worst": res["dispersion"]["per_vintage"][y]
                                  ["passed"]["worst"]} for y in VINTAGES},
                "read": "止めた群の年15%+ は 0.222/0.167/0.222 で通過群 0.190/0.197/0.192 と同等以上。"
                        "**各ビンテージの最悪の社は必ず通過群に居た**"},
            "遮断器の目的である恒久毀損を捕まえていない": {
                "fact": res["dispersion"]["perm_totals_3vintages"],
                "read": "3ビンテージ合計24件の恒久毀損(≤−15%/年)のうち**止めたのは4件**。"
                        "2015は5件中**0件**。止率は 7.5/7.1/10.6% なので偶然の期待は約2件＝"
                        "濃縮はあるが**捕捉率は17%**。台帳の典型例 ASPS は dd5 が"
                        "**原理的に作れない**(観測47ヶ月<48)"},
            "市場が実際に落ちた局面では守らない": {
                "fact": {str(y): {k: res["calendar"]["per_vintage"][y]["cells"]
                                  [f"{THR:+.2f}"][k]["ratio"]
                                  for k in ("covid_crash", "derating")} for y in VINTAGES},
                "read": "COVID暴落 1.05/1.03/0.88・de-rating 1.03/0.91/0.80＝止めた群は"
                        "他と同じだけ落ちた"},
        },
        "survived": {
            "業種の偏りではない": {
                "fact": {str(y): {k: res["sector"]["per_vintage"][y]["cells"][f"{THR:+.2f}"][k]
                                  for k in ("ratio_crude", "ratio_sector_adjusted",
                                            "p_within_sector_permutation")} for y in VINTAGES},
                "read": "2013は SIC2 で層別しても 2.77→2.49、層内置換 p=0.000（seed3通りで再現）。"
                        "**この攻撃は外れた**"},
            "終端日・起点の取り方でも壊れない": {
                "fact": [{"years": r["years"], "ratio": r["ratio"]} for r in hz],
                "read": "2013コホートの終端を3.0〜13.09年で動かしても 2.07〜3.06。"
                        "**窓の長さでは説明できない**＝ビンテージ差の原因は入口の暦のほう"},
            "退場社を戻しても判定は変わらない": survival_ledger_entry(res["survival"]),
        },
        "verdict": "**候補は壊れた（そもそも事前登録v2では不合格）。** 反証の中心は"
                   "『2013の 2.79倍 は GFC を窓に含むアンカーと質実証プールの組合せでしか出ず、"
                   "5アンカーの無条件プールでは 1.51〜1.84 に収まる』こと、および"
                   "『止めた群の絶対的な元本割れ率はビンテージ間で見分けがつかず、"
                   "比を動かしているのは分母＝入口の暦』であること。"
                   "業種と終端日の攻撃は外れた（＝2013の関連そのものは統計的に本物）。"
                   "値・規約・関門・売却規律・配分はいっさい触っていない",
    }

    json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        print(f"→ {a.json}")
        rc = res["reconcile"]
        print(f"[0] 再現: {'OK' if rc['reproduced'] else 'NG'} / 月足への付け替えで符号が入れ替わるのは "
              f"{rc['basis_monthly_vs_inventory_2013']['sign_flips']}社")
        for y in VINTAGES:
            c = res["calendar"]["per_vintage"][y]["cells"][f"{THR:+.2f}"]
            s = " ".join(f"{k}={v['ratio']}" for k, v in c.items())
            print(f"[1] {y} 暦: {s}")
        for y in VINTAGES:
            c = res["decay"]["per_vintage"][y]["cells"][f"{THR:+.2f}"]
            s = " ".join(f"{k}={v['ratio']}({v['stop_numer']})" for k, v in c.items())
            print(f"[2] {y} 経過: {s}")
        dj = res["decay"]["disjoint_2013"]
        print("[2] 2013の重ならない区間: " + " ".join(f"{k}={v['ratio']}({v['stop_numer']})"
                                              for k, v in dj.items()))
        v5 = res["vintages5"]["per_vintage"]
        print("[3] 5ビンテージ(無条件プール): " + " ".join(
            f"{y}={v['cells'][f'{THR:+.2f}']['ratio']}" for y, v in v5.items() if "cells" in v))
        for y in VINTAGES:
            c = res["sector"]["per_vintage"][y]["cells"][f"{THR:+.2f}"]
            print(f"[4] {y} 業種調整: 粗{c['ratio_crude']} → 調整{c['ratio_sector_adjusted']} "
                  f"(層内置換 p={c['p_within_sector_permutation']})")
        sv = res["survival"]
        for y in VINTAGES:
            m = res["mechanism"]["per_vintage"][y]["cells"][f"{THR:+.2f}"]
            print(f"[6] {y} 機構: 高値が古い(≥48m) {m['peak_age_ge_48m'].get('n')}社 "
                  f"ratio={m['peak_age_ge_48m'].get('ratio')} / 新しい "
                  f"{m['peak_age_lt_48m'].get('n')}社 ratio={m['peak_age_lt_48m'].get('ratio')}")
        h = res["heterogeneity"]["cells"][f"{THR:+.2f}"]
        for y in VINTAGES:
            print(f"[7] {y}: 止め p={h[y]['p_stop']} CI95={h[y]['ci95_p_stop']} "
                  f"ratio={h[y]['ratio']} fisher_vs_pool={h[y]['fisher_p_vs_pool']}")
        for k, v in res["heterogeneity"]["vintage_pairs"].items():
            if k.startswith(f"{THR:+.2f}"):
                print(f"[7] {k}: fisher_p={v['fisher_p']}")
        for y in VINTAGES:
            dz = res["dispersion"]["per_vintage"][y]
            print(f"[8] {y} 止め: P(loss)={dz['stopped']['p_loss']} P(15%+)={dz['stopped']['p_win15']} "
                  f"最悪={dz['stopped']['worst']} / 通過: {dz['passed']['p_loss']} "
                  f"{dz['passed']['p_win15']} 最悪={dz['passed']['worst']} | 恒久毀損 "
                  f"{dz['perm_impairments']['by_group']}")
        print(f"[8] 3ビンテージ合計の恒久毀損の行き先: {res['dispersion']['perm_totals_3vintages']}")
        print("[9] 2013コホートの終端を動かす: " + " ".join(
            f"{r['years']:.2f}y={r['ratio']}" for r in res["horizon"]["rows_2013_cohort"]))
        b = sv["bounding_price_only"]
        print(f"[5] 退場: 復元{sv['universe']['restored_exits']} / dd5算出可 "
              f"{sv['dd5_on_exits']['computable']} / 挟み込み(-0.30) "
              f"下端{b['na(72社)を全部通過させる(下端)']['ratio']} "
              f"上端{b['na(72社)を全部止める(上端)']['ratio']} / 兄弟器と一致="
              f"{sv['sibling_agreement'].get('agree')}")
        print(f"    退場社の元本割れ {sv['left_tail_survivor_vs_exit']['restored_exit']['p_loss']} "
              f"vs 生存者 {sv['left_tail_survivor_vs_exit']['survivor']['p_loss']}")


if __name__ == "__main__":
    main()
