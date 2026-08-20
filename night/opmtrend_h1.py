#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H1（選別器）——opmD5<0 は前方リターンを当てるか。

  lift = P(前方年率>=15% | opmD5>=0) - P(... | opmD5<0)
  線（事前登録 out/opm_trend_prereg.json の H1_selector）:
      lift >= 0.15 かつ **8ビンテージすべてで符号が同じ**
  プール: 全社 / 質実証（opm>=10% ∧ fcfpos5>=5）

★この器は**判定しか持たない**。データの結合・単位・到達可能性は
  night/opmtrend_base.py の load_base() が作った out/opmtrend_base.json を読むだけで、
  一行も再実装しない（v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」）。

★値・規約・採点式・刻み・重み・関門・売却規律・配分は1バイトも触らない。
  書くのは out/opmtrend_h1.json だけ。

★「線」の読み方を結果の前に3通り全部出す（後から都合のよい読みを選ばないため）:
   (i) 厳格   : 8ビンテージ**すべて**で lift>=0.15
   (ii) プール : 全ビンテージの行を束ねた lift>=0.15
   (iii) 中央値: 8つの lift の中央値>=0.15
  符号の一致は (i)(ii)(iii) と独立に課す。
  → どの読みでも同じ答えなら、読み方の選択は合否に効いていない。

★0件は測定ではないことがある。プール・群・分子が0/極小なら名指しで警告し、
  そのセルを判定から外す（単位・欄名・照合の失敗を先に疑う）。
"""
import json, os, random, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")
sys.path.insert(0, HERE)

from opmtrend_base import load_base, VINTAGES, HURDLE, IMPAIR, MIN_NUM  # noqa: E402

LINE_LIFT = 0.15          # 事前登録 H1_selector の線。ここで動かさない
N_PERM = 2000             # 置換検定（会社単位・全ビンテージ同時）
N_POWER = 2000            # 検出力のモンテカルロ
SEED = 20260818


# ---------- 小道具 ----------
def share(rows, pred):
    if not rows:
        return None
    return sum(1 for r in rows if pred(r)) / len(rows)


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def r4(x):
    return None if x is None else round(x, 4)


def spearman(xs, ys):
    """順位相関（同順位は平均順位）。"""
    n = len(xs)
    if n < 3:
        return None

    def rank(v):
        idx = sorted(range(n), key=lambda i: v[i])
        rk = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                rk[idx[k]] = avg
            i = j + 1
        return rk

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return None if dx == 0 or dy == 0 else num / (dx * dy)


# ---------- 本体 ----------
def build():
    base = load_base()
    rows_all = base["rows"]
    vmeta = base["vintage_meta"]
    reach = base["reachability"]
    warns = []
    checks = {}

    # ===== 自己検算 0: 土台と同じ母集団を見ているか =====
    #   （基準の違う二つを割らないため、まず土台の数と突き合わせる）
    pool_match = {}
    for y in VINTAGES:
        vr = [r for r in rows_all if r["vintage"] == y]
        for pool in ("all", "qual"):
            sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            want = reach[f"{y}/{pool}"]["n"]
            pool_match[f"{y}/{pool}"] = {"mine": len(sel), "base": want,
                                         "same": len(sel) == want}
            if len(sel) != want:
                warns.append(f"★{y}/{pool}: 母集団が土台と食い違う（自分 {len(sel)} / 土台 {want}）"
                             f"——照合の失敗を疑うこと。判定に進んではいけない")
    checks["pool_matches_base"] = pool_match
    checks["pool_all_match"] = all(v["same"] for v in pool_match.values())

    # ===== 自己検算 1: 単位（opmD5 は比率pt か） =====
    unit = {}
    for y in VINTAGES:
        d5 = [r["opmD5"] for r in rows_all if r["vintage"] == y and r["opmD5"] is not None]
        if not d5:
            warns.append(f"★{y}: opmD5 が1件も無い——欄名の取り違えを疑うこと")
            continue
        m = med([abs(x) for x in d5])
        neg = sum(1 for x in d5 if x < 0) / len(d5)
        unit[str(y)] = {
            "n": len(d5), "median_abs": r4(m), "max_abs": round(max(abs(x) for x in d5), 3),
            "neg_share": r4(neg), "exact_zero": sum(1 for x in d5 if x == 0),
            "looks_ratio": (m is not None and m < 1.0),
        }
        if m is not None and m >= 1.0:
            warns.append(f"★{y}: opmD5 の中央値|{m:.3f}|が1.0以上——%pt が混ざっている疑い。"
                         f"事前登録の閾値は比率pt")
        if not (0.35 <= neg <= 0.65):
            warns.append(f"{y}: opmD5<0 の割合 {neg:.1%} が 35〜65% の外——"
                         f"単位ではなく窓の中身（危機からの回復期など）か照合の失敗を疑う")
    checks["unit_opmD5"] = unit
    # opm(水準)の帯検問も念のため（この台帳は比率と%を2度取り違えている）
    opm_pct = [r["opm"] for r in rows_all if r["opm"] is not None]
    checks["opm_pct_median_all"] = r4(med(opm_pct))
    checks["opm_pct_looks_percent"] = (med(opm_pct) is not None and 1.0 < med(opm_pct) < 100.0)
    if not checks["opm_pct_looks_percent"]:
        warns.append("★opm(%)の中央値が 1〜100 の外——帯検問が効いていない疑い")

    # ===== H1 本体 =====
    per = []
    for y in VINTAGES:
        vm = vmeta[str(y)]
        bench = vm.get("benchmark_tr_cagr")
        is_spy = bool(vm.get("benchmark_is_spy"))
        ymed = vm.get("years_median")
        vr = [r for r in rows_all if r["vintage"] == y]
        for pool in ("all", "qual"):
            sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            n_pool = len(sel)
            use = [r for r in sel if r["opmD5"] is not None]
            A = [r for r in use if r["opmD5"] >= 0]      # トレンドが非負
            B = [r for r in use if r["opmD5"] < 0]       # トレンドが負
            hit = lambda r: r["tr_cagr"] >= HURDLE       # noqa: E731
            imp = lambda r: r["tr_cagr"] <= IMPAIR       # noqa: E731
            beat = (lambda r: bench is not None and r["tr_cagr"] >= bench)  # noqa: E731

            pA, pB = share(A, hit), share(B, hit)
            bA, bB = share(A, beat), share(B, beat)
            # 短い窓の行を外した頑健版（CAGRの窓がベンチと違う行を除く）
            長 = [r for r in use if not (ymed and r.get("years") and r["years"] < ymed * 0.9)]
            A2 = [r for r in 長 if r["opmD5"] >= 0]
            B2 = [r for r in 長 if r["opmD5"] < 0]
            pA2, pB2 = share(A2, hit), share(B2, hit)

            rec = {
                "vintage": y, "pool": pool,
                "n_pool": n_pool, "n_opmD5": len(use),
                "n_dropped_no_opmD5": n_pool - len(use),
                "coverage": r4(len(use) / n_pool) if n_pool else None,
                "n_nonneg": len(A), "n_neg": len(B),
                "n_exact_zero": sum(1 for r in use if r["opmD5"] == 0),
                "base_hit": r4(share(use, hit)),
                "p_hit_nonneg": r4(pA), "p_hit_neg": r4(pB),
                "lift_hit": r4(pA - pB) if (pA is not None and pB is not None) else None,
                "med_tr_nonneg": r4(med([r["tr_cagr"] for r in A])),
                "med_tr_neg": r4(med([r["tr_cagr"] for r in B])),
                "p_impair_nonneg": r4(share(A, imp)), "p_impair_neg": r4(share(B, imp)),
                "benchmark_is_spy": is_spy,
                "benchmark_symbol": vm.get("benchmark_symbol"),
                "benchmark_tr_cagr": bench,
                "base_beat": r4(share(use, beat)),
                "p_beat_nonneg": r4(bA), "p_beat_neg": r4(bB),
                "lift_beat": r4(bA - bB) if (bA is not None and bB is not None) else None,
                "lift_hit_longwin_only": (r4(pA2 - pB2)
                                          if (pA2 is not None and pB2 is not None) else None),
                "n_longwin": len(長),
                "years_median": ymed,
                "usable": None, "why_not": None,
            }
            # 判定に使えるか（0件は測定ではない）
            if n_pool == 0:
                rec["usable"] = False
                rec["why_not"] = "プールが0社——単位・欄名・照合の失敗を疑うこと"
                warns.append(f"★{y}/{pool}: プールが0社。測定ではなく照合の失敗の疑い")
            elif len(use) == 0:
                rec["usable"] = False
                rec["why_not"] = "opmD5 が1件も無い"
                warns.append(f"★{y}/{pool}: opmD5 が0件")
            elif len(A) < 20 or len(B) < 20:
                rec["usable"] = False
                rec["why_not"] = f"群が薄い（非負{len(A)} / 負{len(B)}・下限20）"
                warns.append(f"{y}/{pool}: 群が薄い（非負{len(A)}/負{len(B)}）——判定から外す")
            else:
                rec["usable"] = True
            per.append(rec)

    # ===== 線に照らす =====
    summary = {}
    for pool in ("all", "qual"):
        cells = [c for c in per if c["pool"] == pool]
        ok = [c for c in cells if c["usable"]]
        lifts = [c["lift_hit"] for c in ok]
        pos = sum(1 for v in lifts if v > 0)
        neg = sum(1 for v in lifts if v < 0)
        zero = sum(1 for v in lifts if v == 0)
        same_sign = (len(ok) == len(cells)) and (pos == len(ok) or neg == len(ok))
        # プール読み（全ビンテージの行を束ねる）
        allrows = []
        for y in VINTAGES:
            vr = [r for r in rows_all if r["vintage"] == y]
            s = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            allrows += [r for r in s if r["opmD5"] is not None]
        A = [r for r in allrows if r["opmD5"] >= 0]
        B = [r for r in allrows if r["opmD5"] < 0]
        hit = lambda r: r["tr_cagr"] >= HURDLE   # noqa: E731
        pooled = (share(A, hit) - share(B, hit)) if (A and B) else None
        wmean = (sum(c["lift_hit"] * c["n_opmD5"] for c in ok) /
                 sum(c["n_opmD5"] for c in ok)) if ok else None

        reads = {
            "i_strict_all_vintages_ge_line": (len(ok) == len(cells) and
                                              all(v >= LINE_LIFT for v in lifts)),
            "ii_pooled_ge_line": (pooled is not None and pooled >= LINE_LIFT),
            "iii_median_ge_line": (bool(lifts) and st.median(lifts) >= LINE_LIFT),
        }
        verdict = ("合格" if same_sign and any(reads.values())
                   else ("判定不能" if len(ok) < len(cells) and not lifts else "不合格"))
        # 判定不能は「使えるセルが足りない」ときだけ。使えるセルで線に届かないなら不合格。
        if len(ok) == 0:
            verdict = "判定不能"
        elif not (same_sign and any(reads.values())):
            verdict = "不合格"
        summary[pool] = {
            "cells": len(cells), "usable_cells": len(ok),
            "lifts": lifts,
            "n_lift_ge_line": sum(1 for v in lifts if v >= LINE_LIFT),
            "sign_pos": pos, "sign_neg": neg, "sign_zero": zero,
            "all_same_sign": same_sign,
            "pooled_lift": r4(pooled),
            "median_lift": r4(st.median(lifts)) if lifts else None,
            "mean_lift_weighted": r4(wmean),
            "min_lift": r4(min(lifts)) if lifts else None,
            "max_lift": r4(max(lifts)) if lifts else None,
            "readings": reads,
            "verdict": verdict,
            "why": ("符号が8ビンテージで揃わず、かつ lift がどの読み方でも線 %.2f に届かない"
                    % LINE_LIFT) if verdict == "不合格" else None,
        }
        # ベンチ超版（同じ形・ただし SPY と EW が混ざる）
        bl = [c["lift_beat"] for c in ok if c["lift_beat"] is not None]
        bl_spy = [c["lift_beat"] for c in ok
                  if c["lift_beat"] is not None and c["benchmark_is_spy"]]
        summary[pool]["beat"] = {
            "lifts": bl,
            "median_lift": r4(st.median(bl)) if bl else None,
            "n_ge_line": sum(1 for v in bl if v >= LINE_LIFT),
            "sign_pos": sum(1 for v in bl if v > 0), "sign_neg": sum(1 for v in bl if v < 0),
            "all_same_sign": (bool(bl) and (all(v > 0 for v in bl) or all(v < 0 for v in bl))),
            "spy_only_lifts": bl_spy,
            "spy_only_median": r4(st.median(bl_spy)) if bl_spy else None,
            "spy_only_all_same_sign": (bool(bl_spy) and
                                       (all(v > 0 for v in bl_spy) or all(v < 0 for v in bl_spy))),
            "note": ("2019〜2022 のベンチは SPY ではなくパネル自身の等ウェイト指数(EW)。"
                     "混ぜて『SPY超』と呼ぶと『基準の違う二つ』を自分で作るので、"
                     "SPY だけの4ビンテージ(2013/2016/2017/2018)を別に出す"),
        }
    return base, rows_all, per, summary, warns, checks


# ---------- 十分位 ----------
def deciles(rows_all, vmeta):
    """★十分位は**ビンテージの中で**切ってから束ねる。

    ビンテージごとに基礎率が 19.7%〜33.1% と違う（窓の長さが 4.08〜13.09年で違うため）ので、
    全行を一括で十分位に切ると『どのビンテージが多く入ったか』が中身に化ける。
    中で切れば各十分位にどのビンテージも約10%ずつ入り、その差が相殺される。
    """
    out = {"method": "ビンテージ内で十分位に切ってから束ねる（基礎率の差を相殺するため）",
           "pools": {}}
    for pool in ("all", "qual"):
        buckets = {i: [] for i in range(1, 11)}
        per_v = {}
        for y in VINTAGES:
            vm = vmeta[str(y)]
            bench = vm.get("benchmark_tr_cagr")
            vr = [r for r in rows_all if r["vintage"] == y]
            sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            use = sorted([r for r in sel if r["opmD5"] is not None], key=lambda r: r["opmD5"])
            n = len(use)
            if n < 30:
                per_v[str(y)] = {"n": n, "skipped": "n<30——十分位に切れない"}
                continue
            rowsv = []
            for i, r in enumerate(use):
                dec = min(10, int(i * 10 / n) + 1)
                r2 = dict(r)
                r2["_dec"] = dec
                r2["_beat"] = (bench is not None and r["tr_cagr"] >= bench)
                buckets[dec].append(r2)
                rowsv.append(r2)
            tab = []
            for dcl in range(1, 11):
                g = [r for r in rowsv if r["_dec"] == dcl]
                tab.append({"decile": dcl, "n": len(g),
                            "p_hit": r4(share(g, lambda r: r["tr_cagr"] >= HURDLE)),
                            "med_tr": r4(med([r["tr_cagr"] for r in g])),
                            "p_impair": r4(share(g, lambda r: r["tr_cagr"] <= IMPAIR)),
                            "p_beat": r4(share(g, lambda r: r["_beat"])),
                            "opmD5_lo": r4(min(r["opmD5"] for r in g)),
                            "opmD5_hi": r4(max(r["opmD5"] for r in g))})
            ph = [t["p_hit"] for t in tab]
            per_v[str(y)] = {"n": n, "table": tab,
                             "spearman_dec_vs_hit": r4(spearman(list(range(1, 11)), ph)),
                             "ascending_steps": sum(1 for a, b in zip(ph, ph[1:]) if b > a)}
        tab = []
        for dcl in range(1, 11):
            g = buckets[dcl]
            tab.append({"decile": dcl, "n": len(g),
                        "p_hit": r4(share(g, lambda r: r["tr_cagr"] >= HURDLE)),
                        "med_tr": r4(med([r["tr_cagr"] for r in g])),
                        "p_impair": r4(share(g, lambda r: r["tr_cagr"] <= IMPAIR)),
                        "p_beat": r4(share(g, lambda r: r["_beat"])),
                        "med_opmD5": r4(med([r["opmD5"] for r in g]))})
        ph = [t["p_hit"] for t in tab]
        pb = [t["p_beat"] for t in tab]
        pi = [t["p_impair"] for t in tab]
        mt = [t["med_tr"] for t in tab]
        out["pools"][pool] = {
            "pooled_table": tab,
            "spearman_dec_vs_hit": r4(spearman(list(range(1, 11)), ph)),
            "spearman_dec_vs_beat": r4(spearman(list(range(1, 11)), pb)),
            "spearman_dec_vs_impair": r4(spearman(list(range(1, 11)), pi)),
            "spearman_dec_vs_medtr": r4(spearman(list(range(1, 11)), mt)),
            "ascending_steps_hit": sum(1 for a, b in zip(ph, ph[1:]) if b > a),
            "monotone_increasing_hit": all(b >= a for a, b in zip(ph, ph[1:])),
            "spread_hit_D10_minus_D1": r4(ph[-1] - ph[0]),
            "spread_hit_max_minus_min": r4(max(ph) - min(ph)),
            "per_vintage": per_v,
        }
    return out


# ---------- 検出力（この不合格の意味を測る） ----------
def power(per, pool, rng):
    """真の lift が線ちょうど(0.15)なら、この手続きは何回に1回 合格を出すか。

    ★結果の前に出すべき数字（v2 の教訓）。事後だが、無いと『不合格』の意味が定まらない。
    """
    cells = [c for c in per if c["pool"] == pool and c["usable"]]
    if not cells:
        return None
    res = {}
    for true_lift in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        passes = 0
        for _ in range(N_POWER):
            lifts = []
            for c in cells:
                nA, nB, p = c["n_nonneg"], c["n_neg"], c["base_hit"]
                pB = p - true_lift * nA / (nA + nB)
                pA = pB + true_lift
                pA, pB = min(max(pA, 0.0), 1.0), min(max(pB, 0.0), 1.0)
                hA = sum(1 for _ in range(nA) if rng.random() < pA)
                hB = sum(1 for _ in range(nB) if rng.random() < pB)
                lifts.append(hA / nA - hB / nB)
            same = all(v > 0 for v in lifts) or all(v < 0 for v in lifts)
            reads = (all(v >= LINE_LIFT for v in lifts) or
                     st.median(lifts) >= LINE_LIFT)
            if same and reads:
                passes += 1
        res[f"{true_lift:.2f}"] = round(passes / N_POWER, 4)
    return res


# ---------- 偽陽性率（会社単位・全ビンテージ同時に混ぜる） ----------
def permutation(rows_all, per, pool, rng):
    """★ビンテージ内で独立に混ぜると従属が壊れ偽陽性率を桁で過小評価する（既記録）。

    会社単位の**一つの**並べ替えを全ビンテージへ同時に当てる。
    各ビンテージの結果の多重集合は不変なので基礎率は保たれる。
    """
    cells = [c for c in per if c["pool"] == pool and c["usable"]]
    if not cells:
        return None
    years = [c["vintage"] for c in cells]
    data = {}
    for y in years:
        vr = [r for r in rows_all if r["vintage"] == y]
        sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
        use = [r for r in sel if r["opmD5"] is not None]
        use.sort(key=lambda r: r["ticker"])
        data[y] = {"tick": [r["ticker"] for r in use],
                   "neg": [r["opmD5"] < 0 for r in use],
                   "hit": [r["tr_cagr"] >= HURDLE for r in use]}
    universe = sorted({t for y in years for t in data[y]["tick"]})
    passes = 0
    lifts_null = []
    for _ in range(N_PERM):
        order = universe[:]
        rng.shuffle(order)
        rank = {t: i for i, t in enumerate(order)}
        ls = []
        for y in years:
            d = data[y]
            n = len(d["tick"])
            # 会社の並べ替え順で結果を付け替える（ビンテージ内の多重集合は不変）
            idx = sorted(range(n), key=lambda i: rank[d["tick"][i]])
            hits = [d["hit"][i] for i in idx]
            nA = sum(1 for v in d["neg"] if not v)
            hA = sum(1 for v, h in zip(d["neg"], hits) if not v and h)
            hB = sum(1 for v, h in zip(d["neg"], hits) if v and h)
            nB = n - nA
            ls.append(hA / nA - hB / nB)
        lifts_null.append(st.median(ls))
        same = all(v > 0 for v in ls) or all(v < 0 for v in ls)
        if same and (all(v >= LINE_LIFT for v in ls) or st.median(ls) >= LINE_LIFT):
            passes += 1
    lifts_null.sort()
    obs = st.median([c["lift_hit"] for c in cells])
    ge = sum(1 for v in lifts_null if v >= obs)
    return {
        "n_perm": N_PERM,
        "false_positive_rate": round(passes / N_PERM, 4),
        "null_median_lift_p50": r4(lifts_null[N_PERM // 2]),
        "null_median_lift_p95": r4(lifts_null[int(N_PERM * 0.95)]),
        "observed_median_lift": r4(obs),
        "p_value_median_lift": round((ge + 1) / (N_PERM + 1), 4),
        "note": "会社単位の一つの並べ替えを全ビンテージへ同時に当てる（従属を壊さない）",
    }


# ---------- 事後の探索（★事前登録に無い。合否には一切使わない） ----------
def exploratory(rows_all, vmeta):
    """十分位が単調でなかったので、形を測る。

    ★これは**事前登録の外**の切り方。合否には使わないし、ここから線を引かない
      （結果を見てから線を引けば、この台帳が繰り返し戒めてきた curve-fitting になる）。
      出す理由は「不合格」の中身を正確に書くため——
      『符号が当てない』と『大きさが当てない』は別のことだから。
    """
    out = {"caveat": "事前登録に無い事後の切り方。合否・線の根拠にしない。記述のみ",
           "pools": {}}
    for pool in ("all", "qual"):
        # (a) 連続量としての順位相関（ビンテージ内で測ってから束ねる）
        rhos, rhos_abs = [], []
        for y in VINTAGES:
            vr = [r for r in rows_all if r["vintage"] == y]
            sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            use = [r for r in sel if r["opmD5"] is not None]
            if len(use) < 30:
                continue
            rhos.append(spearman([r["opmD5"] for r in use], [r["tr_cagr"] for r in use]))
            rhos_abs.append(spearman([abs(r["opmD5"]) for r in use],
                                     [r["tr_cagr"] for r in use]))
        # (b) 大きさ（符号を捨てた |opmD5|）の十分位——U字かを直接見る
        buckets = {i: [] for i in range(1, 11)}
        for y in VINTAGES:
            vm = vmeta[str(y)]
            bench = vm.get("benchmark_tr_cagr")
            vr = [r for r in rows_all if r["vintage"] == y]
            sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            use = sorted([r for r in sel if r["opmD5"] is not None],
                         key=lambda r: abs(r["opmD5"]))
            n = len(use)
            if n < 30:
                continue
            for i, r in enumerate(use):
                d2 = dict(r)
                d2["_beat"] = (bench is not None and r["tr_cagr"] >= bench)
                buckets[min(10, int(i * 10 / n) + 1)].append(d2)
        tab = []
        for dcl in range(1, 11):
            g = buckets[dcl]
            rv = [r["rev"] for r in g if r.get("rev")]
            tab.append({"decile_abs": dcl, "n": len(g),
                        "med_abs_opmD5": r4(med([abs(r["opmD5"]) for r in g])),
                        "p_hit": r4(share(g, lambda r: r["tr_cagr"] >= HURDLE)),
                        "med_tr": r4(med([r["tr_cagr"] for r in g])),
                        "p_impair": r4(share(g, lambda r: r["tr_cagr"] <= IMPAIR)),
                        "med_rev_musd": (round(st.median(rv) / 1e6, 1) if rv else None)})
        pi = [t["p_impair"] for t in tab]
        mt = [t["med_tr"] for t in tab]
        # (c) 符号つき十分位の売上（極端値が微小売上の社かを確かめる）
        rev_by_dec = []
        for y in VINTAGES:
            vr = [r for r in rows_all if r["vintage"] == y]
            sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
            use = sorted([r for r in sel if r["opmD5"] is not None], key=lambda r: r["opmD5"])
            n = len(use)
            if n < 30:
                continue
            for i, r in enumerate(use):
                rev_by_dec.append((min(10, int(i * 10 / n) + 1), r.get("rev")))
        revtab = []
        for dcl in range(1, 11):
            rv = [v for dd, v in rev_by_dec if dd == dcl and v]
            revtab.append({"decile": dcl,
                           "med_rev_musd": round(st.median(rv) / 1e6, 1) if rv else None,
                           "n_with_rev": len(rv)})
        out["pools"][pool] = {
            "spearman_signed_per_vintage": [r4(x) for x in rhos],
            "spearman_signed_median": r4(st.median([x for x in rhos if x is not None]))
                                      if rhos else None,
            "spearman_abs_per_vintage": [r4(x) for x in rhos_abs],
            "spearman_abs_median": r4(st.median([x for x in rhos_abs if x is not None]))
                                   if rhos_abs else None,
            "abs_decile_table": tab,
            "spearman_absdec_vs_impair": r4(spearman(list(range(1, 11)), pi)),
            "spearman_absdec_vs_medtr": r4(spearman(list(range(1, 11)), mt)),
            "signed_decile_median_revenue": revtab,
        }
        # (d) 規模を統制した lift（★全社プールの弱い残差が「小型株の言い換え」かを見る）
        #     ビンテージ内で売上の三分位に切り、その中で H1 と同じ lift を測る
        size_tab = []
        for k in (1, 2, 3):
            cells = []
            for y in VINTAGES:
                vr = [r for r in rows_all if r["vintage"] == y]
                sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
                use = [r for r in sel if r["opmD5"] is not None and r.get("rev")]
                if len(use) < 30:
                    continue
                use.sort(key=lambda r: r["rev"])
                n = len(use)
                g = [r for i, r in enumerate(use) if min(3, int(i * 3 / n) + 1) == k]
                A = [r for r in g if r["opmD5"] >= 0]
                B = [r for r in g if r["opmD5"] < 0]
                if len(A) < 20 or len(B) < 20:
                    continue
                cells.append(share(A, lambda r: r["tr_cagr"] >= HURDLE)
                             - share(B, lambda r: r["tr_cagr"] >= HURDLE))
            size_tab.append({"rev_tercile": k, "n_vintages": len(cells),
                             "lifts": [r4(x) for x in cells],
                             "median_lift": r4(st.median(cells)) if cells else None,
                             "n_positive": sum(1 for x in cells if x > 0)})
        out["pools"][pool]["lift_within_revenue_tercile"] = size_tab
    return out


def main():
    rng = random.Random(SEED)
    base, rows_all, per, summary, warns, checks = build()
    dec = deciles(rows_all, base["vintage_meta"])
    exp = exploratory(rows_all, base["vintage_meta"])

    pw = {p: power(per, p, random.Random(SEED + 1)) for p in ("all", "qual")}
    pm = {p: permutation(rows_all, per, p, random.Random(SEED + 2)) for p in ("all", "qual")}

    verdict = {
        "line_from_prereg": "lift >= 0.15 かつ 8ビンテージすべてで符号が同じ",
        "line_value": LINE_LIFT,
        "by_pool": {p: summary[p]["verdict"] for p in ("all", "qual")},
        "overall": ("合格" if all(summary[p]["verdict"] == "合格" for p in ("all", "qual"))
                    else ("判定不能" if any(summary[p]["verdict"] == "判定不能"
                                            for p in ("all", "qual"))
                          and not any(summary[p]["verdict"] == "不合格"
                                      for p in ("all", "qual"))
                          else "不合格")),
        "readings_all_agree": (len(set(tuple(sorted(summary[p]["readings"].items()))
                                       for p in ("all", "qual"))) >= 1),
    }

    o = {
        "generated": "2026-08-18",
        "tool": "night/opmtrend_h1.py",
        "role": "H1（選別器）の判定だけ。結合・単位・到達可能性は opmtrend_base.json を読む（再実装なし）",
        "reads": ["out/opmtrend_base.json", "out/opm_trend_prereg.json"],
        "writes_nothing_else": "値・規約・採点式・関門・売却規律・配分には1バイトも触っていない",
        "seed": SEED,
        "self_checks": checks,
        "h1_per_cell": per,
        "h1_summary": summary,
        "deciles": dec,
        "exploratory_not_preregistered": exp,
        "power": pw,
        "permutation": pm,
        "verdict": verdict,
        "warnings": warns,
        "limits": [
            "8ビンテージは同じ956社で窓が重なる＝**真の out-of-sample はゼロ**",
            "窓の長さが 4.08〜13.09年と違うので基礎率をビンテージ間で直接比べない",
            "2013 は opmD5 の被覆が48%・欠測が小型に偏る（売上中央が5.91倍）＝別の母集団の疑い",
            "2019〜2022 のベンチは SPY ではなく等ウェイト指数(EW)。『SPY超』と混ぜて呼ばない",
            "opmD5 は会計上の営業利益率の差で、一過性費用を調整しない",
            "生存バイアスは既記録のまま（左尾は 2.00〜25.68% の幅）",
            "十分位は順位で切るので極端値に頑健だが、opmD5 の最大|値|は 2687（微小売上の社）",
        ],
    }
    fp = os.path.join(OUT, "opmtrend_h1.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    print("wrote", fp)
    for w in warns:
        print("WARN:", w)
    print("verdict:", json.dumps(verdict, ensure_ascii=False))
    return o


if __name__ == "__main__":
    main()
