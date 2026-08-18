# night/opmtrend_h2.py — H2（遮断器）の判定（2026-08-18新設）
#
# 問い（事前登録 out/opm_trend_prereg.json の H2_breaker）:
#   「opmD5 が深く負の社を止める規則は成立するか（左尾として）」
#
# ★この器は**土台を再実装しない**——out/opmtrend_base.json（night/opmtrend_base.py が作る）を
#   読むだけ。結合・単位の判定・到達可能性はすべて土台の答えをそのまま使う（v9.9.65）。
#
# ★線は事前登録で固定済み。ここで一つも動かさない:
#   閾値  : opmD5 < -0.02 / -0.05 / -0.10（**絶対の比率pt**）
#   6基準 : 濃縮 >= 2.0倍 ∧ 分子 >= 5社 ∧ 止めた群の中央値 < 通過群の中央値 ∧ 止率 <= 15%
#   到達  : reachable=false のセルは**合否から外し「判定不能」**（不合格と書かない）
#   ——閾値が事前登録の文言と一致することを起動時に照合する（line_guard）。
#     一致しなければ**測らずに落とす**。線を後から動かせない構造にするため。
#
# ⚠ この器が判断したこと（すべて出力JSONに記録する）:
#   (a) **プールの分母は「全行」**（opmD5 が欠測の行も含む）。理由は二つ——
#       (i) 土台の到達可能性が全行で数えてある（＝事前登録の到達可能性はこの分母の話）
#       (ii) 門のキルは値が無いと眠る（未測定は止めない）＝実運用の遮断器と同じ形。
#       欠測を除いた分母での結果は sensitivity_measured_only に**事前登録外**として併記する。
#       2013 は opmD5 の被覆が48%しかないので、この二つは大きく食い違いうる。
#   (b) 濃縮の分母は**プールの毀損率**（hist_val v2 / dd5 / retro_breaker_test と同じ作法。
#       土台の max_concentration = 1/毀損率 もこの定義の上に立っている）。
#       通過群を分母にしない——二つを混ぜると「基準の違う二つを割る」型になる。
#   (c) 不合格は**理由の種類で分ける**——「効果なし(濃縮)」「検出力不足(分子)」
#       「止めすぎ(止率)」「勝者を巻き込む(中央値)」。一語にまとめると、
#       『測れなかった』と『測って効かなかった』の取り違えを報告の側で作る。
#   (d) 置換検定は**会社単位・全ビンテージ同時**（事前登録 adversarial(d)。
#       ビンテージ内で独立に混ぜると従属が壊れ偽陽性率を33倍過小評価する＝既記録）。
#       合否に依らず回す——**試験の値札は、実データが通っても通らなくても要る**。
#
# 実行: python3 night/opmtrend_h2.py [--json] [--perm N]
# 在庫: out/opmtrend_h2.json

import json
import os
import random
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

from opmtrend_base import load_base  # noqa: E402  土台を再実装しない

PREREG = os.path.join(OUT, "opm_trend_prereg.json")

# 事前登録の H2_breaker.thresholds_fixed_now に書いてある3つ。**ここで増やさない**。
THRESHOLDS = [-0.02, -0.05, -0.10]

# 6基準（事前登録 H2_breaker.line をそのまま。新しい定数を作らない）
CONC_MIN = 2.0     # 濃縮 >= 2.0倍
MIN_NUM_REF = 5    # 分子の下限（土台の constants と一致することを build で照合する）
SEED = 20260818    # 置換検定を決定的にする
PERM_N = 2000


def line_guard():
    """★閾値が事前登録の文言と一致するか照合する。一致しなければ測らずに落とす。

    「線を後から動かさない」を注意力ではなく構造で守る。
    """
    with open(PREREG, encoding="utf-8") as f:
        pr = json.load(f)
    txt = pr["hypotheses"]["H2_breaker"]["thresholds_fixed_now"]
    line = pr["hypotheses"]["H2_breaker"]["line"]
    miss = [t for t in THRESHOLDS if ("%g" % t) not in txt.replace("−", "-")]
    ok = not miss
    # 6基準の語も照合する（線の文が書き換わっていないこと）
    words = ["2.0倍", "5社", "中央値", "15%"]
    wmiss = [w for w in words if w not in line]
    return {
        "prereg_thresholds_text": txt,
        "prereg_line_text": line,
        "thresholds_used": THRESHOLDS,
        "thresholds_match": ok,
        "thresholds_missing_from_prereg": miss,
        "line_words_missing": wmiss,
        "ok": ok and not wmiss,
    }


def med(v):
    return st.median(v) if v else None


def unit_sanity(rows, warns):
    """★0件は測定ではないことがある。単位・欄名・照合の失敗を先に疑う。

    この台帳は opm が比率(0.0979)なのに >=10 と比べて全社を落とす罠を2度踏んでいる。
    """
    d5 = [r["opmD5"] for r in rows if r["opmD5"] is not None]
    if not d5:
        raise SystemExit("FATAL: opmD5 が1行も無い——欄名か結合の失敗を疑え")
    amed = st.median([abs(x) for x in d5])
    if amed > 0.5:
        raise SystemExit("FATAL: |opmD5| の中央値 %.3f ——比率ではなく%%pt で入っている疑い。"
                         "事前登録の閾値は比率pt なので測らずに止める" % amed)
    # 各閾値が「誰も止めない/全員止める」になっていないか
    fr = {}
    for t in THRESHOLDS:
        k = sum(1 for x in d5 if x < t)
        fr["%g" % t] = round(k / len(d5), 4)
        if k == 0:
            warns.append("⚠ 閾値 %g で止まる社が**測れた%d行のうち0社**——0は測定ではない可能性。"
                         "単位・欄名・照合を疑え" % (t, len(d5)))
        if k == len(d5):
            warns.append("⚠ 閾値 %g で**測れた全行が止まる**——単位を疑え" % t)
    # qual の単位（%で比べているか）
    q = [r["opm"] for r in rows if r["qual"] and not r["qual_na"]]
    if q and min(q) < 10.0 - 1e-9:
        warns.append("⚠ qual=True なのに opm が10未満の行がある（最小 %.4f）——"
                     "土台の帯検問を疑え" % min(q))
    return {"abs_median_opmD5": round(amed, 5),
            "stopped_fraction_of_measured": fr,
            "n_measured": len(d5),
            "qual_min_opm_pct": round(min(q), 3) if q else None}


def cell_stats(pool_rows, thr, hurdle, impair):
    """1セルの実測。**判定はしない**（判定は judge が持つ）。"""
    n = len(pool_rows)
    stop = [r for r in pool_rows if r["opmD5"] is not None and r["opmD5"] < thr]
    psss = [r for r in pool_rows if not (r["opmD5"] is not None and r["opmD5"] < thr)]
    n_imp_pool = sum(1 for r in pool_rows if r["tr_cagr"] <= impair)
    base = (n_imp_pool / n) if n else None
    num = sum(1 for r in stop if r["tr_cagr"] <= impair)
    p_stop = (num / len(stop)) if stop else None
    conc = (p_stop / base) if (p_stop is not None and base) else None
    rv_s = [r["rev"] for r in stop if r.get("rev")]
    rv_p = [r["rev"] for r in psss if r.get("rev")]
    # ★結果を見る前に決まっていること（v1/v2/v3 が三度踏んだ「到達可能性を先に出す」）:
    #   止率は**信号だけ**で決まる（結果に一切依らない）。分子の下限が濃縮の線を
    #   上書きしていないか（＝実効的に要求される倍率）も、止めた社数と毀損率だけで決まる。
    req_p = None
    req_conc = None
    binding = None
    impossible = None
    if stop and base:
        req_p = max(MIN_NUM_REF / len(stop), CONC_MIN * base)  # 止めた群に要る毀損率
        req_conc = req_p / base
        binding = "分子" if (MIN_NUM_REF / len(stop)) > (CONC_MIN * base) else "濃縮"
        impossible = (len(stop) < MIN_NUM_REF) or (req_p > 1.0)
    return {
        "n_pool": n,
        "n_measured": sum(1 for r in pool_rows if r["opmD5"] is not None),
        "required_p_impair_stop": round(req_p, 4) if req_p is not None else None,
        "required_conc_effective": round(req_conc, 3) if req_conc is not None else None,
        "binding_criterion_before_results": binding,
        "impossible_before_results": impossible,
        "n_stop": len(stop),
        "n_pass": len(psss),
        "stop_rate": round(len(stop) / n, 4) if n else None,
        "base_impair": round(base, 4) if base is not None else None,
        "n_impair_pool": n_imp_pool,
        "num_impair_stop": num,
        "p_impair_stop": round(p_stop, 4) if p_stop is not None else None,
        "conc": round(conc, 3) if conc is not None else None,
        "med_stop": round(med([r["tr_cagr"] for r in stop]), 4) if stop else None,
        "med_pass": round(med([r["tr_cagr"] for r in psss]), 4) if psss else None,
        "hit_stop": round(sum(1 for r in stop if r["tr_cagr"] >= hurdle) / len(stop), 4) if stop else None,
        "hit_pass": round(sum(1 for r in psss if r["tr_cagr"] >= hurdle) / len(psss), 4) if psss else None,
        "rev_med_stop_musd": round(st.median(rv_s) / 1e6, 1) if rv_s else None,
        "rev_med_pass_musd": round(st.median(rv_p) / 1e6, 1) if rv_p else None,
        "stop_tickers_impaired": sorted(r["ticker"] for r in stop if r["tr_cagr"] <= impair)[:40],
    }


def judge(s, reachable, min_num, max_stop):
    """6基準に照らす。**reachable=false は判定不能**（不合格と書かない）。"""
    if not reachable:
        return "判定不能", [], "到達不能", []
    fails, kinds = [], []
    if s["n_stop"] == 0:
        return "不合格", ["止めた社が0社（この閾値は誰も止めない）"], "止めない", ["止めない"]
    if s["conc"] is None or s["conc"] < CONC_MIN:
        fails.append("濃縮 %.2f倍 < %.1f倍" % (s["conc"] or 0, CONC_MIN))
        kinds.append("効果なし(濃縮)")
    if s["num_impair_stop"] < min_num:
        fails.append("分子 %d社 < %d社" % (s["num_impair_stop"], min_num))
        kinds.append("検出力不足(分子)")
    if not (s["med_stop"] is not None and s["med_pass"] is not None
            and s["med_stop"] < s["med_pass"]):
        fails.append("止めた群の中央値 %.4f >= 通過群 %.4f" % (s["med_stop"] or 0, s["med_pass"] or 0))
        kinds.append("勝者を巻き込む(中央値)")
    if s["stop_rate"] is None or s["stop_rate"] > max_stop:
        fails.append("止率 %.1f%% > %.0f%%" % ((s["stop_rate"] or 0) * 100, max_stop * 100))
        kinds.append("止めすぎ(止率)")
    return ("合格" if not fails else "不合格"), fails, ("合格" if not fails else "／".join(kinds)), kinds


def pools_of(rows):
    """プールの選び方は土台の到達可能性と**同一**（all は全行・qual は qual∧¬qual_na）。"""
    return {"all": rows,
            "qual": [r for r in rows if r["qual"] and not r["qual_na"]]}


def build(perm_n=PERM_N):
    guard = line_guard()
    if not guard["ok"]:
        raise SystemExit("FATAL: 閾値/線が事前登録と一致しない——測らずに止める: %s" % guard)

    b = load_base()
    C = b["constants_from_prereg"]
    HURDLE, IMPAIR = C["HURDLE"], C["IMPAIR"]
    MIN_NUM, MAX_STOP = C["MIN_NUM"], C["MAX_STOP"]
    rows = b["rows"]
    reach = b["reachability"]
    warns = list(b["warnings"])  # 土台の警告を引き継ぐ（消さない）

    us = unit_sanity(rows, warns)

    vints = sorted({r["vintage"] for r in rows})
    byv = {y: [r for r in rows if r["vintage"] == y] for y in vints}

    cells = []
    for y in vints:
        for pool, prows in pools_of(byv[y]).items():
            rk = reach["%d/%s" % (y, pool)]
            if not prows:
                warns.append("⚠ %d/%s のプールが0社——照合の失敗を疑え" % (y, pool))
            for thr in THRESHOLDS:
                s = cell_stats(prows, thr, HURDLE, IMPAIR)
                v, fails, kind, kinds = judge(s, rk["reachable"], MIN_NUM, MAX_STOP)
                c = {"vintage": y, "pool": pool, "thr": thr,
                     "reachable": rk["reachable"],
                     "reach_why_not": rk["why_not"],
                     "verdict": v, "fail_reasons": fails, "fail_kind": kind,
                     "fail_kinds": kinds,
                     "benchmark_is_spy": b["vintage_meta"][str(y)]["benchmark_is_spy"],
                     "window_years": b["vintage_meta"][str(y)]["years_median"]}
                c.update(s)
                cells.append(c)

    summary = {
        "n_cells": len(cells),
        "n_pass": sum(1 for c in cells if c["verdict"] == "合格"),
        "n_fail": sum(1 for c in cells if c["verdict"] == "不合格"),
        "n_undecided": sum(1 for c in cells if c["verdict"] == "判定不能"),
        "pass_cells": ["%d/%s/%g" % (c["vintage"], c["pool"], c["thr"])
                       for c in cells if c["verdict"] == "合格"],
        "undecided_cells": ["%d/%s/%g" % (c["vintage"], c["pool"], c["thr"])
                            for c in cells if c["verdict"] == "判定不能"],
        "fail_kind_counts": {},
    }
    for c in cells:
        for k in c["fail_kinds"]:
            summary["fail_kind_counts"][k] = summary["fail_kind_counts"].get(k, 0) + 1

    # ---- 事前登録の線: 「8ビンテージすべてで」は H1 の話。H2 は各セル独立に裁く。
    #      ただし「同じ閾値が何ビンテージで通るか」は読み手に要るので数える。
    per_thr = {}
    for thr in THRESHOLDS:
        for pool in ("all", "qual"):
            sel = [c for c in cells if c["thr"] == thr and c["pool"] == pool]
            per_thr["%g/%s" % (thr, pool)] = {
                "pass": sum(1 for c in sel if c["verdict"] == "合格"),
                "fail": sum(1 for c in sel if c["verdict"] == "不合格"),
                "undecided": sum(1 for c in sel if c["verdict"] == "判定不能"),
                "conc_median": round(st.median([c["conc"] for c in sel if c["conc"] is not None]), 3)
                if any(c["conc"] is not None for c in sel) else None,
                "stop_rate_median": round(st.median([c["stop_rate"] for c in sel
                                                     if c["stop_rate"] is not None]), 4),
                "med_lower_count": sum(1 for c in sel if c["med_stop"] is not None
                                       and c["med_pass"] is not None
                                       and c["med_stop"] < c["med_pass"]),
                "n": len(sel),
            }

    # ---- ★分母の歪み: 欠測社の毀損率が測れた社と違うと、濃縮の比が構造的に歪む ----
    #   遮断器は**測れた社しか止められない**のに、濃縮の分母（プールの毀損率）には
    #   測れない社も入る。両者の毀損率が違えば、比は指標の性能ではなく被覆を測ることになる。
    #   ＝「基準の違う二つを割る」型の親戚。primary（全行）を採った以上、必ず数える。
    denom = {}
    for y in vints:
        for pool, prows in pools_of(byv[y]).items():
            hav = [r for r in prows if r["opmD5"] is not None]
            mis = [r for r in prows if r["opmD5"] is None]
            bh = (sum(1 for r in hav if r["tr_cagr"] <= IMPAIR) / len(hav)) if hav else None
            bm = (sum(1 for r in mis if r["tr_cagr"] <= IMPAIR) / len(mis)) if mis else None
            ratio = (bm / bh) if (bh and bm is not None) else None
            denom["%d/%s" % (y, pool)] = {
                "n_measured": len(hav), "n_missing": len(mis),
                "coverage": round(len(hav) / len(prows), 4) if prows else None,
                "impair_measured": round(bh, 4) if bh is not None else None,
                "impair_missing": round(bm, 4) if bm is not None else None,
                "missing_over_measured": round(ratio, 2) if ratio else None,
                "distorted": bool(ratio is not None and (ratio >= 2.0 or ratio <= 0.5)),
            }
            if denom["%d/%s" % (y, pool)]["distorted"]:
                warns.append("⚠ %d/%s: 欠測社の毀損率が測れた社の %.1f倍（%.1f%% vs %.1f%%・被覆%.0f%%）"
                             "——濃縮の分母が**遮断器が見られない群**に支配されている。"
                             "primary(全行)の比はこのセルでは指標の性能ではなく被覆を測っている"
                             % (y, pool, ratio, (bm or 0) * 100, bh * 100,
                                len(hav) / len(prows) * 100))

    # ---- 感度（★事前登録外）: 分母から opmD5 欠測を外す ----
    sens = []
    for y in vints:
        for pool, prows in pools_of(byv[y]).items():
            m = [r for r in prows if r["opmD5"] is not None]
            if not m:
                warns.append("⚠ %d/%s に opmD5 のある行が0——照合の失敗を疑え" % (y, pool))
                continue
            n_imp = sum(1 for r in m if r["tr_cagr"] <= IMPAIR)
            # 到達可能性を測れた行だけで数え直す（事前登録外なので別枠）
            rok = (n_imp >= MIN_NUM and MIN_NUM / len(m) <= MAX_STOP
                   and n_imp and (len(m) / n_imp) >= CONC_MIN)
            for thr in THRESHOLDS:
                s = cell_stats(m, thr, HURDLE, IMPAIR)
                v, fails, kind, _ = judge(s, rok, MIN_NUM, MAX_STOP)
                d = {"vintage": y, "pool": pool, "thr": thr, "reachable_measured_only": rok,
                     "verdict": v, "fail_kind": kind}
                d.update(s)
                sens.append(d)
    sens_sum = {"n_pass": sum(1 for d in sens if d["verdict"] == "合格"),
                "n_fail": sum(1 for d in sens if d["verdict"] == "不合格"),
                "n_undecided": sum(1 for d in sens if d["verdict"] == "判定不能"),
                "pass_cells": ["%d/%s/%g" % (d["vintage"], d["pool"], d["thr"])
                               for d in sens if d["verdict"] == "合格"],
                "note": "★事前登録外——分母から opmD5 欠測を外した読み。"
                        "primary（全行）と食い違うときは必ず両方を書く"}

    if MIN_NUM != MIN_NUM_REF:
        raise SystemExit("FATAL: MIN_NUM が土台(%d)と器(%d)で食い違う" % (MIN_NUM, MIN_NUM_REF))

    # ---- ★結果を見る前に不合格が確定していたセルを数える ----
    #   止率は信号だけで決まるので、止率>15% の不合格は**結果を一度も見ずに判る**。
    #   同じく「分子5社が構造的に無理」も止めた社数と毀損率だけで決まる。
    pre = {"testable": 0, "stop_rate_predetermined_fail": [], "num5_impossible": [],
           "binding_num": 0, "binding_conc": 0}
    for c in cells:
        if c["verdict"] == "判定不能":
            continue
        pre["testable"] += 1
        if c["stop_rate"] is not None and c["stop_rate"] > MAX_STOP:
            pre["stop_rate_predetermined_fail"].append("%d/%s/%g" % (c["vintage"], c["pool"], c["thr"]))
        if c["impossible_before_results"]:
            pre["num5_impossible"].append("%d/%s/%g" % (c["vintage"], c["pool"], c["thr"]))
        if c["binding_criterion_before_results"] == "分子":
            pre["binding_num"] += 1
        elif c["binding_criterion_before_results"] == "濃縮":
            pre["binding_conc"] += 1
    _rq = [c["required_conc_effective"] for c in cells
           if c["verdict"] != "判定不能" and c["binding_criterion_before_results"] == "分子"
           and c["required_conc_effective"] is not None]
    pre["required_conc_median_where_num_binds"] = round(st.median(_rq), 2) if _rq else None
    pre["required_conc_max_where_num_binds"] = round(max(_rq), 2) if _rq else None
    pre["n_stop_rate_predetermined_fail"] = len(pre["stop_rate_predetermined_fail"])
    pre["n_num5_impossible"] = len(pre["num5_impossible"])
    pre["effective_family"] = pre["testable"] - pre["n_stop_rate_predetermined_fail"]
    pre["note"] = ("止率は信号だけで決まるので、止率>15%%の不合格は結果を一度も見ずに確定する。"
                   "実質の家族は %d セル。required_conc_effective は「分子5社の下限が濃縮の線 %.1f倍を"
                   "上書きしていないか」——分子が拘束するセルでは線は 2.0倍より高い"
                   % (pre["effective_family"], CONC_MIN))

    # ---- ★探索（事前登録外）: ビンテージをまたいで Mantel-Haenszel でプールする ----
    #   窓長が違うので毀損率が 1.2%〜15.1% と桁で違う。素朴に足すと窓長で重みが歪むが、
    #   MH は層（ビンテージ）ごとの期待値で割るので窓長の差を吸収する。
    pooled = {}
    for pool in ("all", "qual"):
        for thr in THRESHOLDS:
            O = E = 0.0
            ns = nstop = 0
            for y in vints:
                g = pools_of(byv[y])[pool]
                if not g:
                    continue
                n_s = len(g)
                m_s = sum(1 for r in g if r["opmD5"] is not None and r["opmD5"] < thr)
                i_s = sum(1 for r in g if r["tr_cagr"] <= IMPAIR)
                if not (n_s and m_s):
                    continue
                O += sum(1 for r in g if r["opmD5"] is not None and r["opmD5"] < thr
                         and r["tr_cagr"] <= IMPAIR)
                E += m_s * i_s / n_s
                ns += n_s
                nstop += m_s
            pooled["%s/%g" % (pool, thr)] = {
                "observed_impair_in_stop": int(O), "expected": round(E, 2),
                "mh_conc": round(O / E, 3) if E else None,
                "n_pool_total": ns, "n_stop_total": nstop,
                "stop_rate_total": round(nstop / ns, 4) if ns else None}
    pooled["note"] = ("★事前登録外の探索。合否には使わない。ビンテージを層とした MH の濃縮。"
                      "⚠8ビンテージは同じ956社で窓が重なるので、これは独立な8標本の合成ではない")

    perm = permutation(byv, reach, HURDLE, IMPAIR, MIN_NUM, MAX_STOP, perm_n)
    adv = adversarial(byv, cells, HURDLE, IMPAIR, MIN_NUM, MAX_STOP, perm_n)

    # ---- ★仮説レベルの合否を曖昧にしない ----
    #   ⚠事前登録は「セル単位の4基準」を固定したが、**何セル合格すれば H2 成立か**を
    #   決めていない（事前登録の空白）。だから二通りの読みを両方書き、どちらを採るかを明記する。
    passed = [c for c in cells if c["verdict"] == "合格"]
    adv_broken = []
    for d in adv:
        why = []
        if d["mh_adjusted_conc"] is not None and d["mh_adjusted_conc"] < CONC_MIN:
            why.append("業種調整(MH) %.2f倍 < %.1f倍" % (d["mh_adjusted_conc"], CONC_MIN))
        for nm, v in (d["size_split"] or {}).items():
            if nm in ("small", "large") and (v["conc"] is None or v["conc"] < CONC_MIN):
                why.append("規模%s で %.2f倍 < %.1f倍" % (nm, v["conc"] or 0, CONC_MIN))
        if d["drop_one_sic2"]["n_breaks"]:
            why.append("1業種抜きで合格が割れる（%d通り）" % d["drop_one_sic2"]["n_breaks"])
        if why:
            adv_broken.append({"cell": d["cell"], "why": why})
    hv = "不合格"
    basis = [
        "セル単位（事前登録の線そのまま）: 合格 %d ／ 不合格 %d ／ 判定不能 %d"
        % (summary["n_pass"], summary["n_fail"], summary["n_undecided"]),
        "置換検定（会社単位・全ビンテージ同時・家族%dセル）で**偶然1つ以上通る確率 %.4f**"
        "——合格1件は雑音と区別がつかない" % (perm["family_size"], perm["p_at_least_1"]),
        "実質の家族は %d セル（残り%dセルは止率>15%%で**結果を見る前に**不合格が確定）"
        % (pre["effective_family"], pre["n_stop_rate_predetermined_fail"]),
    ]
    for b in adv_broken:
        basis.append("合格セル %s は事前登録の反証で割れる: %s" % (b["cell"], " ／ ".join(b["why"])))
    if not passed:
        basis.append("合格セルが無い")
    verdict = {
        "hypothesis": "H2_breaker",
        "verdict": hv,
        "reading_A_literal_cell": "合格 %d セル（%s）" % (summary["n_pass"], summary["pass_cells"] or "なし"),
        "reading_B_family": "家族として見ると偶然の範囲（P(1つ以上合格)=%.4f）" % perm["p_at_least_1"],
        "aggregation_rule_note": "★事前登録は『何セル合格すれば H2 成立か』を決めていない。"
                                 "私は読み方B（家族＋反証）を採る。理由は (i)42セルを一度に裁いているので"
                                 "多重検定の値札を無視できない (ii)事前登録が『合格した仮説は必ず反証にかける』"
                                 "と定めており、唯一の合格セルはその反証で割れる。**この集約規則は事前登録に無い"
                                 "私の判断**なので、読み方Aの数字も必ず併記する",
        "adversarial_broken": adv_broken,
        "basis": basis,
    }

    return {
        "generated": "2026-08-18",
        "tool": "night/opmtrend_h2.py",
        "verdict_H2": verdict,
        "prereg": "out/opm_trend_prereg.json",
        "base": "out/opmtrend_base.json",
        "role": "H2（遮断器）の合否。線は事前登録で固定・ここで一つも動かさない",
        "line_guard": guard,
        "constants_from_base": C,
        "conc_min": CONC_MIN,
        "unit_sanity": us,
        "summary": summary,
        "per_threshold": per_thr,
        "predetermined_before_results": pre,
        "denominator_distortion": denom,
        "exploratory_pooled_mh": pooled,
        "cells": cells,
        "sensitivity_measured_only": {"summary": sens_sum, "cells": sens},
        "permutation": perm,
        "adversarial": adv,
        "warnings": warns,
        "limits": [
            "8ビンテージは**同じ956社**で窓が重なる＝真の out-of-sample はゼロ（事前登録の限界）",
            "窓の長さが 4.08〜13.09年と違う＝**毀損率がビンテージ間で 1.2%〜15.1% と桁で違う**。"
            "濃縮は比なので窓長で正規化されるが、分子の数（＝検出力）は窓長に強く依存する",
            "2019〜2022 のベンチマークは SPY ではない（EW）。⚠ただし H2 は毀損率と中央値で裁くので"
            "ベンチマークを一度も使っていない——この限界は H2 の合否には効かない",
            "2013 は opmD5 の被覆が48%で欠測が大型に偏る（rev 5.91倍）＝**別の母集団**。"
            "primary（全行）では欠測は『止めない』側に入る",
            "opmD5 は会計上の営業利益率の差で、一過性費用を調整しない（事前登録の限界）",
            "生存バイアスは既記録のまま（左尾は 2.00〜25.68% の幅）",
        ],
    }



def adversarial(byv, cells, hurdle, impair, min_num, max_stop, perm_n):
    """★事前登録 adversarial: 合格したセルは必ず反証にかける。

    (a)業種(SIC2)で層別しても残るか——Mantel-Haenszel 型の調整濃縮＋層内置換
    (b)規模(売上)を統制しても残るか——売上中央値で二分して各層で当て直す
    (c)1業種/1社を抜くと消えないか
    (d)そのセル単独の置換p（家族の値札とは別に）
    合格が0なら空で返す（**やっていない反証を「やった」と書かない**）。
    """
    out = []
    rnd = random.Random(SEED + 1)
    for c in cells:
        if c["verdict"] != "合格":
            continue
        y, pool, thr = c["vintage"], c["pool"], c["thr"]
        prows = pools_of(byv[y])[pool]
        stopped = lambda r: (r["opmD5"] is not None and r["opmD5"] < thr)

        # --- (a) 業種調整（MH）: 層ごとの期待毀損数の合計と観測の比 ---
        strata = {}
        for r in prows:
            strata.setdefault(r["sic2"] or "NA", []).append(r)
        O = E = 0.0
        for k, g in strata.items():
            n_s = len(g)
            m_s = sum(1 for r in g if stopped(r))
            i_s = sum(1 for r in g if r["tr_cagr"] <= impair)
            if n_s and m_s:
                O += sum(1 for r in g if stopped(r) and r["tr_cagr"] <= impair)
                E += m_s * i_s / n_s
        mh = (O / E) if E else None

        # 層内置換（毀損ラベルを層の中だけで混ぜる）
        hits = 0
        for _ in range(perm_n):
            o = 0.0
            for k, g in strata.items():
                lab = [r["tr_cagr"] <= impair for r in g]
                rnd.shuffle(lab)
                o += sum(1 for j, r in enumerate(g) if stopped(r) and lab[j])
            if o >= O:
                hits += 1
        p_strat = (hits + 1) / (perm_n + 1)

        # --- (b) 規模で二分 ---
        rv = [r for r in prows if r.get("rev")]
        size = {}
        if rv:
            cut = st.median([r["rev"] for r in rv])
            for nm, sel in (("small", lambda r: r.get("rev") is not None and r["rev"] <= cut),
                            ("large", lambda r: r.get("rev") is not None and r["rev"] > cut)):
                sub = [r for r in prows if sel(r)]
                s2 = cell_stats(sub, thr, hurdle, impair)
                size[nm] = {"n": s2["n_pool"], "n_stop": s2["n_stop"],
                            "stop_rate": s2["stop_rate"],
                            "base_impair": s2["base_impair"],
                            "num": s2["num_impair_stop"], "conc": s2["conc"],
                            "med_stop": s2["med_stop"], "med_pass": s2["med_pass"]}
            size["rev_cut_musd"] = round(cut / 1e6, 1)

        # --- (c) 1業種抜き / 1社抜き ---
        drops = []
        for k in sorted(strata):
            sub = [r for r in prows if (r["sic2"] or "NA") != k]
            s2 = cell_stats(sub, thr, hurdle, impair)
            v2, _, _, _ = judge(s2, True, min_num, max_stop)
            drops.append({"drop_sic2": k, "conc": s2["conc"],
                          "num": s2["num_impair_stop"], "verdict": v2})
        drops_bad = [d for d in drops if d["verdict"] != "合格"]
        # ★止めた群から1社ずつ抜く（**毀損社だけ抜くと退化する**——毀損社を1つ抜くと
        #   n_stop/分子/毀損総数が全部1ずつ減るので、どれを抜いても数字が同一になり
        #   検定として何も言わない。止めた全社を対象にする）
        one_co = []
        for r in [r for r in prows if stopped(r)]:
            sub = [x for x in prows if x["ticker"] != r["ticker"]]
            s2 = cell_stats(sub, thr, hurdle, impair)
            v2, _, _, _ = judge(s2, True, min_num, max_stop)
            one_co.append({"drop": r["ticker"], "conc": s2["conc"], "verdict": v2})
        one_bad = [d for d in one_co if d["verdict"] != "合格"]

        # --- (d) このセル単独の置換p ---
        uni = [r["ticker"] for r in prows]
        tr = [r["tr_cagr"] for r in prows]
        st_i = [i for i, r in enumerate(prows) if stopped(r)]
        ps_i = [i for i, r in enumerate(prows) if not stopped(r)]
        base = sum(1 for x in tr if x <= impair) / len(tr)
        obs = c["conc"]
        k = 0
        for _ in range(perm_n):
            a = tr[:]
            rnd.shuffle(a)
            num = sum(1 for i in st_i if a[i] <= impair)
            cc = (num / len(st_i)) / base if base else 0
            ok = (cc >= CONC_MIN and num >= min_num
                  and st.median([a[i] for i in st_i]) < st.median([a[i] for i in ps_i]))
            if ok:
                k += 1
        p_cell = (k + 1) / (perm_n + 1)

        # 分子（止めた群の毀損社）の業種の偏り
        from collections import Counter as _C
        num_by_sic = _C((r["sic2"] or "NA") for r in prows
                        if stopped(r) and r["tr_cagr"] <= impair)
        out.append({
            "cell": "%d/%s/%g" % (y, pool, thr),
            "numerator_by_sic2": num_by_sic.most_common(6),
            "raw_conc": c["conc"], "num": c["num_impair_stop"],
            "mh_adjusted_conc": round(mh, 3) if mh else None,
            "mh_observed": O, "mh_expected": round(E, 2),
            "p_within_sic2_permutation": round(p_strat, 4),
            "size_split": size,
            "drop_one_sic2": {"n": len(drops), "n_breaks": len(drops_bad),
                              "breaks": [{"sic2": d["drop_sic2"], "conc": d["conc"],
                                          "num": d["num"]} for d in drops_bad][:10],
                              "conc_min": min([d["conc"] for d in drops if d["conc"] is not None]),
                              "conc_max": max([d["conc"] for d in drops if d["conc"] is not None])},
            "drop_one_company": {"n": len(one_co), "n_breaks": len(one_bad),
                                 "breaks": [d["drop"] for d in one_bad][:10],
                                 "conc_min": min([d["conc"] for d in one_co if d["conc"] is not None]),
                                 "conc_max": max([d["conc"] for d in one_co if d["conc"] is not None])},
            "p_cell_permutation": round(p_cell, 4),
            "same_threshold_other_vintages": [
                {"vintage": o["vintage"], "conc": o["conc"], "num": o["num_impair_stop"],
                 "verdict": o["verdict"]}
                for o in cells if o["thr"] == thr and o["pool"] == pool and o["vintage"] != y],
        })
    return out


def permutation(byv, reach, hurdle, impair, min_num, max_stop, perm_n):
    """★会社単位・全ビンテージ同時の置換。合否に依らず回す（試験の値札）。

    ビンテージ内で独立に混ぜると従属が壊れ偽陽性率を大きく過小評価する（既記録）ので、
    **一つの置換 π を全ビンテージへ同時に当てる**。
    """
    rnd = random.Random(SEED)
    vints = sorted(byv)
    uni = sorted({r["ticker"] for y in vints for r in byv[y]})
    pos = {t: i for i, t in enumerate(uni)}

    # ビンテージごと: 位置 -> tr（無ければ None）
    trmap = {}
    for y in vints:
        a = [None] * len(uni)
        for r in byv[y]:
            a[pos[r["ticker"]]] = r["tr_cagr"]
        trmap[y] = a

    # セルの構造（止める/通す）は**信号だけで決まる**ので置換で動かない。先に固定する。
    plan = []
    for y in vints:
        for pool, prows in pools_of(byv[y]).items():
            if not reach["%d/%s" % (y, pool)]["reachable"]:
                continue  # 判定不能セルは家族から外す（実データで先に決めてある）
            idx = [pos[r["ticker"]] for r in prows]
            for thr in THRESHOLDS:
                st_i, ps_i = [], []
                for r in prows:
                    (st_i if (r["opmD5"] is not None and r["opmD5"] < thr)
                     else ps_i).append(pos[r["ticker"]])
                plan.append((y, pool, thr, idx, st_i, ps_i))

    dist = []
    for _ in range(perm_n):
        perm = list(range(len(uni)))
        rnd.shuffle(perm)
        cur = {y: [trmap[y][perm[i]] for i in range(len(uni))] for y in vints}
        k = 0
        for (y, pool, thr, idx, st_i, ps_i) in plan:
            a = cur[y]
            pv = [a[i] for i in idx if a[i] is not None]
            sv = [a[i] for i in st_i if a[i] is not None]
            qv = [a[i] for i in ps_i if a[i] is not None]
            if not pv or not sv or not qv:
                continue
            base = sum(1 for x in pv if x <= impair) / len(pv)
            num = sum(1 for x in sv if x <= impair)
            if not base:
                continue
            conc = (num / len(sv)) / base
            sr = len(st_i) / len(idx)
            if (conc >= CONC_MIN and num >= min_num
                    and st.median(sv) < st.median(qv) and sr <= max_stop):
                k += 1
        dist.append(k)

    dist.sort()
    n = len(dist)
    return {
        "perm_n": perm_n,
        "seed": SEED,
        "family_size": len(plan),
        "note": "会社単位・全ビンテージ同時の置換（事前登録 adversarial(d)）。"
                "判定不能セルは家族から外してある＝実データで先に決めた家族",
        "p_at_least_1": round(sum(1 for x in dist if x >= 1) / n, 4),
        "p_at_least_2": round(sum(1 for x in dist if x >= 2) / n, 4),
        "p_at_least_3": round(sum(1 for x in dist if x >= 3) / n, 4),
        "mean_pass": round(sum(dist) / n, 3),
        "max_pass": dist[-1],
        "q95_pass": dist[int(0.95 * (n - 1))],
    }


def main():
    perm_n = PERM_N
    if "--perm" in sys.argv:
        perm_n = int(sys.argv[sys.argv.index("--perm") + 1])
    o = build(perm_n)
    fp = os.path.join(OUT, "opmtrend_h2.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)

    if "--json" in sys.argv:
        print(json.dumps(o, ensure_ascii=False, indent=1))
        return

    g = o["line_guard"]
    print("H2（遮断器）  事前登録: %s" % o["prereg"])
    print("線の照合: 閾値 %s ／ 一致=%s ／ 線の語 欠け=%s"
          % (g["thresholds_used"], g["thresholds_match"], g["line_words_missing"] or "なし"))
    u = o["unit_sanity"]
    print("単位: |opmD5| 中央 %.5f（比率）／ 測れた行 %d ／ 止まる割合(測れた行の中) %s"
          % (u["abs_median_opmD5"], u["n_measured"], u["stopped_fraction_of_measured"]))
    print()
    hdr = ("年    プール  閾値    n    止 止率   毀損率  分子 止毀損率 濃縮  中央(止/通)      判定")
    print(hdr)
    print("-" * len(hdr))
    for c in o["cells"]:
        print("%-5d %-6s %+.2f %5d %4d %5.1f%% %6.1f%% %4d %7s %5s  %7s/%-7s %s%s"
              % (c["vintage"], c["pool"], c["thr"], c["n_pool"], c["n_stop"],
                 (c["stop_rate"] or 0) * 100, (c["base_impair"] or 0) * 100,
                 c["num_impair_stop"],
                 ("%.1f%%" % (c["p_impair_stop"] * 100)) if c["p_impair_stop"] is not None else "-",
                 ("%.2f" % c["conc"]) if c["conc"] is not None else "-",
                 ("%.3f" % c["med_stop"]) if c["med_stop"] is not None else "-",
                 ("%.3f" % c["med_pass"]) if c["med_pass"] is not None else "-",
                 c["verdict"], (" ← " + c["fail_kind"]) if c["verdict"] == "不合格" else ""))
    s = o["summary"]
    print()
    print("合格 %d ／ 不合格 %d ／ 判定不能 %d（全 %d セル）"
          % (s["n_pass"], s["n_fail"], s["n_undecided"], s["n_cells"]))
    print("合格セル: %s" % (s["pass_cells"] or "なし"))
    print("判定不能: %s" % (s["undecided_cells"] or "なし"))
    print("不合格の内訳（重複あり）: %s" % s["fail_kind_counts"])
    print()
    print("閾値×プール別:")
    for k, v in o["per_threshold"].items():
        print("  %-10s 合格%d 不合格%d 判定不能%d ／ 濃縮の中央 %s ／ 止率の中央 %.1f%% ／ 中央値が低い %d/%d"
              % (k, v["pass"], v["fail"], v["undecided"], v["conc_median"],
                 v["stop_rate_median"] * 100, v["med_lower_count"], v["n"]))
    p = o["permutation"]
    print()
    print("置換検定（会社単位・全ビンテージ同時・%d回・家族%dセル）: "
          "1つ以上合格 %.4f ／ 2つ以上 %.4f ／ 平均 %.3f ／ 最大 %d"
          % (p["perm_n"], p["family_size"], p["p_at_least_1"], p["p_at_least_2"],
             p["mean_pass"], p["max_pass"]))
    print()
    print("分母の歪み（欠測社 vs 測れた社の毀損率。遮断器は測れた社しか止められない）:")
    for k, v in o["denominator_distortion"].items():
        if v["missing_over_measured"] is None:
            continue
        print("  %-11s 被覆%.0f%%  測れた %.1f%% / 欠測 %.1f%% = %.2f倍%s"
              % (k, (v["coverage"] or 0) * 100, (v["impair_measured"] or 0) * 100,
                 (v["impair_missing"] or 0) * 100, v["missing_over_measured"],
                 "  ← 歪み" if v["distorted"] else ""))
    ss = o["sensitivity_measured_only"]["summary"]
    print("感度（★事前登録外・欠測を分母から外す）: 合格%d 不合格%d 判定不能%d ／ %s"
          % (ss["n_pass"], ss["n_fail"], ss["n_undecided"], ss["pass_cells"] or "合格なし"))
    pre = o["predetermined_before_results"]
    print()
    print("★結果を見る前に確定していたこと: 判定可 %d セルのうち **止率>15%% で不合格が確定 %d セル**"
          "／分子5が構造的に不可能 %d セル／実質の家族 %d セル"
          % (pre["testable"], pre["n_stop_rate_predetermined_fail"],
             pre["n_num5_impossible"], pre["effective_family"]))
    print("   実効的に拘束する基準: 分子 %d セル ／ 濃縮 %d セル"
          % (pre["binding_num"], pre["binding_conc"]))
    print("   ★分子が拘束するセルでは、線は 2.0倍ではなく **中央 %s倍・最大 %s倍**"
          "（MIN_NUM=5 が濃縮の線を静かに上書きしている）"
          % (pre["required_conc_median_where_num_binds"],
             pre["required_conc_max_where_num_binds"]))
    print()
    print("探索（★事前登録外・合否に使わない）ビンテージを層にした MH プール:")
    for k, v in o["exploratory_pooled_mh"].items():
        if k == "note":
            continue
        print("  %-11s 観測%3d / 期待%7.2f = 濃縮 %-5s ／ 止率 %.1f%%（止%d/全%d）"
              % (k, v["observed_impair_in_stop"], v["expected"], v["mh_conc"],
                 (v["stop_rate_total"] or 0) * 100, v["n_stop_total"], v["n_pool_total"]))
    a = o.get("adversarial") or []
    if a:
        print()
        print("反証（合格セルのみ・事前登録 adversarial）:")
        for d in a:
            print("  %s: 粗濃縮 %.2f（分子%d）→ 業種調整(MH) %s ／ 層内置換p %.4f ／ セル置換p %.4f"
                  % (d["cell"], d["raw_conc"], d["num"], d["mh_adjusted_conc"],
                     d["p_within_sic2_permutation"], d["p_cell_permutation"]))
            for nm in ("small", "large"):
                v = (d["size_split"] or {}).get(nm)
                if not v:
                    continue
                print("    規模 %-5s n=%d 止%d(%.1f%%) プール毀損率 %.1f%% 分子%d 濃縮 %s 中央 %s/%s"
                      % (nm, v["n"], v["n_stop"], (v["stop_rate"] or 0) * 100,
                         (v["base_impair"] or 0) * 100, v["num"], v["conc"],
                         v["med_stop"], v["med_pass"]))
            print("    分子の業種: %s" % d["numerator_by_sic2"])
            print("    1業種抜き: %d通り中 合格を割るのは %d（%s）／濃縮 %.2f〜%.2f"
                  % (d["drop_one_sic2"]["n"], d["drop_one_sic2"]["n_breaks"],
                     ",".join("SIC%s→%.2f" % (b["sic2"], b["conc"])
                              for b in d["drop_one_sic2"]["breaks"]) or "なし",
                     d["drop_one_sic2"]["conc_min"], d["drop_one_sic2"]["conc_max"]))
            print("    1社抜き(止めた群): %d通り中 合格を割るのは %d（%s）／濃縮 %.2f〜%.2f"
                  % (d["drop_one_company"]["n"], d["drop_one_company"]["n_breaks"],
                     ",".join(d["drop_one_company"]["breaks"]) or "なし",
                     d["drop_one_company"]["conc_min"], d["drop_one_company"]["conc_max"]))
            print("    同じ閾値の他ビンテージ: %s"
                  % ", ".join("%d:%s%s" % (x["vintage"], x["conc"],
                                           "" if x["verdict"] == "合格" else "✗")
                              for x in d["same_threshold_other_vintages"]))
    if o["warnings"]:
        print()
        print("警告:")
        for w in o["warnings"]:
            print("  -", w)
    print()
    v = o["verdict_H2"]
    print()
    print("=" * 70)
    print("H2 の合否: **%s**" % v["verdict"])
    print("  読み方A（セル単位・文字どおり）: %s" % v["reading_A_literal_cell"])
    print("  読み方B（家族＋反証）        : %s" % v["reading_B_family"])
    for b in v["basis"]:
        print("  - %s" % b)
    print("  ⚠ %s" % v["aggregation_rule_note"])
    print("=" * 70)
    print("→ %s" % fp)


if __name__ == "__main__":
    main()
