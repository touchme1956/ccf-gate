# night/hist_val_lookahead.py — 自己相対バリュエーション検定を「look-ahead と多重検定」の観点で壊しにかかる
# (2026-08-09新設)
#
# 立場: この器は候補を**守らない**。壊すために書いた。ただし壊した根拠は必ず実測で示す。
#
# この台帳は「検査器自身が壊れていた」事例を何度も記録している
# （recalc_roic が ADBE の負債タグを2009年で止まった系列から採って「算出不能」と誤判定した等）。
# だから **hist_valuation.py / hist_val_gate_test.py のコードを一行も import せず**、
# 出力（out/hist_val_{vintage}.json）と **SEC から取り直した一次データ**だけで再計算する。
# 同じ答えが出れば検査器は健全、違えばそれが最大の発見。
#
# ── 何を検定するか ───────────────────────────────────────────────────────────
# A look-ahead（採取器が本当に提出日で切っているか）
#   A1 構造スキャン: 全行で「使った決算期末 > asof」「価格の月 > asof」が無いか
#   A2 **SEC から取り直した一次データで**、asof 時点で使われた TTM 純利益が
#      本当に asof までに filed 済みかを実額で再現する（サンプル：無作為＋敵対的抽出）
#      * 敵対的抽出 = 分位が最も高い社（＝遮断器が「止める」側。汚染がいちばん効く場所）
#   A3 提出日を1つ、submissions インデックス（別のAPI）で二重確認する
#   A4 **遅延感度**: ファンダを更に +K ヶ月遅らせて分位を組み直しても結論が変わらないか
#      （look-ahead が結論を作っているなら、遅らせると消える）
#
# B 多重検定（実際にいくつの仮説を検定したか）
#   B1 事前登録の格子から検定数を数える
#   B2 「2ビンテージで同符号」が偶然に起きる確率を、実測の相関を使って見積もる
#   B3 **検出力の天井**: 基準1(分子>=5社)と基準4(<=15%)が同時に満たせる範囲が
#      そもそも存在するかを、各ビンテージの実数で計算する（存在しないなら
#      「不合格」は effect が無いことの証拠ではなく **検定できていない**ことの証拠）
#
# C 独立再現（検定agentの結論を再現できるか）
#   C1 事前登録の基準1〜4を、rows から**自前で**計算し直す
#   C2 合格セルがあれば、その分子を**社名で**出す（1〜2社なら規約にできない）
#
# 実行:
#   python3 night/hist_val_lookahead.py                 # 全部（A2 は SEC へ取りに行く）
#   python3 night/hist_val_lookahead.py --no-net        # 手元の出力だけで A1/A4/B/C
#   python3 night/hist_val_lookahead.py --sample 8
import argparse
import datetime as dt
import gzip
import json
import math
import os
import statistics
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hist_val_rev import load_vintage_checked, seen_revs   # 在庫の版の検問（単一実装）
CACHE = os.path.join(OUT, "_histval_lookahead_cache")
UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com", "Accept-Encoding": "gzip"}
VINTAGES = [(2018, "2018-07-01"), (2015, "2015-07-01"), (2013, "2013-07-01")]
PERM = -0.15          # 恒久毀損の線（台帳の定義）
GRID_PCT = [0.80, 0.85, 0.90, 0.95]
GRID_Z = [1.0, 1.5, 2.0]
GRID_SPX = [0.80, 0.90, 0.95]
PCT_IND = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct"]
Z_IND = ["pe_z", "ps_z"]
Z_MIN_MONTHS = 36     # 事前登録の caveat: z は8ヶ月で出るので 36ヶ月を併せて課す


def D(s):
    return dt.date.fromisoformat(s)


def load(v):
    # 版の検問だけを共有する（night/hist_val_rev.py は判定を一つも持たないので、
    # この器が掲げる「検定の計算を一行も import しない」独立性は保たれる）
    return load_vintage_checked(v)


def med(xs):
    return statistics.median(xs) if xs else None


# ═══════════════════════════════════════════════════════════════════════════
# A2  SEC 一次データでの再現
# ═══════════════════════════════════════════════════════════════════════════
def sec_concept(cik, tag, ns="us-gaap"):
    """companyconcept API（companyfacts より軽い・**採取器のキャッシュを使わない**）。"""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "CIK%010d_%s_%s.json.gz" % (cik, ns, tag))
    if os.path.exists(p):
        with gzip.open(p, "rt") as f:
            return json.load(f)
    url = ("https://data.sec.gov/api/xbrl/companyconcept/CIK%010d/%s/%s.json"
           % (cik, ns, tag))
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            j = json.loads(raw)
    except Exception as e:
        j = {"_error": str(e)}
    with gzip.open(p, "wt") as f:
        json.dump(j, f)
    return j


def sec_subs(cik):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "subs_CIK%010d.json.gz" % cik)
    if os.path.exists(p):
        with gzip.open(p, "rt") as f:
            return json.load(f)
    url = "https://data.sec.gov/submissions/CIK%010d.json" % cik
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            j = json.loads(raw)
    except Exception as e:
        j = {"_error": str(e)}
    with gzip.open(p, "wt") as f:
        json.dump(j, f)
    return j


def periods_from_concept(j, filed_le):
    """(start,end) -> (val, filed) を **filed が最も古い値**で。filed_le より後は見ない。"""
    acc = {}
    for unit, ents in ((j.get("units") or {})).items():
        if unit != "USD":
            continue
        for e in ents:
            st, en, fl = e.get("start"), e.get("end"), e.get("filed")
            if not (st and en and fl) or fl > filed_le:
                continue
            dur = (D(en) - D(st)).days
            if dur < 25 or dur > 400:
                continue
            k = (st, en)
            if k not in acc or fl < acc[k][1]:
                acc[k] = (float(e["val"]), fl, dur, e.get("accn"), e.get("form"))
    return acc


def ttm_at(acc, asof):
    """asof 時点で読めた中で最も新しい TTM 純利益を**独立に**組む。
    採取器と同じ量（A 年次 / C 通期+スタブ−前年同スタブ）だが実装は別。"""
    ann = {}
    ytd = []
    for (st, en), (v, fl, dur, accn, form) in acc.items():
        if 330 <= dur <= 400:
            if en not in ann or fl < ann[en][1]:
                ann[en] = (v, fl, st, accn, form)
        elif 25 <= dur <= 330:
            ytd.append((st, en, v, fl, dur, accn, form))
    cand = []
    for en, (v, fl, st, accn, form) in ann.items():
        cand.append({"end": en, "val": v, "known": fl, "how": "A_annual",
                     "parts": [{"accn": accn, "form": form, "filed": fl,
                                "period": "%s..%s" % (st, en)}]})
    for st, en, v, fl, dur, accn, form in ytd:
        prev = (D(st) - dt.timedelta(days=1)).isoformat()
        a = None
        for ce in (prev, (D(st) - dt.timedelta(days=2)).isoformat(), st):
            if ce in ann:
                a = (ce, ann[ce])
                break
        if not a:
            continue
        best = None
        for st2, en2, v2, fl2, d2, ac2, fo2 in ytd:
            if abs((D(st) - D(st2)).days - 365) > 20 or abs(dur - d2) > 12:
                continue
            if best is None or fl2 < best[3]:
                best = (st2, en2, v2, fl2, d2, ac2, fo2)
        if not best:
            continue
        val = a[1][0] + v - best[2]
        known = max(a[1][1], fl, best[3])
        cand.append({"end": en, "val": val, "known": known, "how": "C_fy_stub",
                     "parts": [
                         {"accn": a[1][3], "form": a[1][4], "filed": a[1][1],
                          "period": "%s..%s" % (a[1][2], a[0])},
                         {"accn": accn, "form": form, "filed": fl,
                          "period": "%s..%s" % (st, en)},
                         {"accn": best[5], "form": best[6], "filed": best[3],
                          "period": "%s..%s" % (best[0], best[1])}]})
    ok = [c for c in cand if c["known"] <= asof]
    if not ok:
        return None
    ok.sort(key=lambda c: (c["end"], -D(c["known"]).toordinal()))
    return ok[-1]


def audit_lookahead_sec(vint, asof, rows, tickers):
    res = []
    for t in tickers:
        r = next((x for x in rows if x["ticker"] == t), None)
        if not r:
            continue
        cik = r.get("cik")
        pe, mcap = r.get("pe"), r.get("mcap")
        rec = {"ticker": t, "cik": cik, "pe": pe,
               "pe_pct": r.get("pe_pct"),
               "collector_ttm_end": r["diag"].get("ni_ttm_end"),
               "collector_ttm_method": r["diag"].get("ni_ttm_method"),
               "implied_ni_ttm": (mcap / pe) if (pe and mcap) else None}
        if not cik:
            rec["verdict"] = "cik無し＝検算不能"
            res.append(rec)
            continue
        j = sec_concept(cik, "NetIncomeLoss")
        if "_error" in j:
            j2 = sec_concept(cik, "ProfitLoss")
            if "_error" in j2:
                rec["verdict"] = "SEC取得失敗＝検算不能"
                res.append(rec)
                continue
            j = j2
        acc = periods_from_concept(j, asof)
        rec["n_periods_filed_le_asof"] = len(acc)
        t12 = ttm_at(acc, asof)
        if not t12:
            rec["verdict"] = "独立側でTTMが組めない"
            res.append(rec)
            continue
        rec["indep_ttm_end"] = t12["end"]
        rec["indep_ttm_val"] = round(t12["val"], 0)
        rec["indep_known"] = t12["known"]
        rec["indep_how"] = t12["how"]
        rec["parts"] = t12["parts"]
        rec["max_filed_used"] = max(p["filed"] for p in t12["parts"])
        rec["filed_le_asof"] = rec["max_filed_used"] <= asof
        # 突合: 採取器の期末と一致するか／時価総額÷PER が独立TTMと一致するか
        rec["end_match"] = (rec["indep_ttm_end"] == rec["collector_ttm_end"])
        if rec["implied_ni_ttm"] and t12["val"]:
            rec["val_ratio"] = round(rec["implied_ni_ttm"] / t12["val"], 4)
            rec["val_match_1pct"] = abs(rec["val_ratio"] - 1) <= 0.01
        # 判定
        if not rec["filed_le_asof"]:
            rec["verdict"] = "★未来の申告を使っている"
        elif rec["end_match"] and rec.get("val_match_1pct"):
            rec["verdict"] = "OK（期末・実額とも一致・提出日はasof以前）"
        elif rec["end_match"]:
            rec["verdict"] = "期末一致・実額は不一致（要確認）"
        else:
            rec["verdict"] = "期末が不一致（要確認）"
        res.append(rec)
    return res


# ═══════════════════════════════════════════════════════════════════════════
# A5  分位そのものの独立再構成（asof の1点だけでなく**自己履歴の全月**を作り直す）
#     A2 は「asof で使った決算が asof までに filed 済みか」を見る。
#     しかし分位は **履歴の分布** に対する順位なので、履歴の側に未来が混ざっていれば
#     asof が正しくても分位は嘘になる。だから履歴を丸ごと作り直して突き合わせる。
# ═══════════════════════════════════════════════════════════════════════════
YF_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def yahoo_monthly(ticker):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "px_%s.json.gz" % ticker)
    if os.path.exists(p):
        with gzip.open(p, "rt") as f:
            return json.load(f)
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?period1=1104537600&period2=9999999999&interval=1mo&events=split"
           % ticker)
    req = urllib.request.Request(url, headers=YF_UA)
    raw = urllib.request.urlopen(req, timeout=45).read()
    res = json.loads(raw)["chart"]["result"][0]
    ts = res["timestamp"]
    cl = res["indicators"]["quote"][0]["close"]
    close = {}
    for t, c in zip(ts, cl):
        if c is None:
            continue
        d = dt.datetime.utcfromtimestamp(t).date()
        close["%04d-%02d" % (d.year, d.month)] = float(c)
    splits = []
    for _k, s in ((res.get("events") or {}).get("splits") or {}).items():
        d = dt.datetime.utcfromtimestamp(s["date"]).date()
        splits.append({"date": d.isoformat(),
                       "ratio": float(s["numerator"]) / float(s["denominator"])})
    out = {"close": close, "splits": sorted(splits, key=lambda x: x["date"])}
    # ★px_guard（2026-09-23）: 台帳より遅く始まる応答（Yahoo が過去の足を消した記号）はキャッシュに
    #   焼き付けない。「測れない」を返す（短い系列を全履歴として使わない）
    import px_guard as PXG
    if PXG.vet(ticker, close, "hist_val_lookahead.yahoo_monthly", req_start=1104537600) is None:
        return {"close": {}, "splits": [], "why": "px_guard_refused(台帳より短い)"}
    with gzip.open(p, "wt") as f:
        json.dump(out, f)
    return out


def _month_end(mk):
    y, m = int(mk[:4]), int(mk[5:7])
    return (dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)).isoformat()


def _sfa(splits, day):
    f = 1.0
    for s in splits:
        if s["date"] > day:
            f *= s["ratio"]
    return f


def rebuild_pe_series(ticker, cik, asof, xbrl_start="2009-01"):
    """PER の月次系列を**独立に**作る（採取器のコードを一行も使わない）。"""
    px = yahoo_monthly(ticker)
    # 純利益: as-reported・filed<=asof
    j = sec_concept(cik, "NetIncomeLoss")
    if "_error" in j:
        return None
    acc = periods_from_concept(j, asof)
    # 各月末で読めた TTM（月末を asof 扱いにして ttm_at をもう一度当てる）
    # 株数: dei（点時点値）
    js = sec_concept(cik, "EntityCommonStockSharesOutstanding", ns="dei")
    pts = []
    if "_error" not in js:
        for unit, ents in ((js.get("units") or {})).items():
            if unit != "shares":
                continue
            best = {}
            for e in ents:
                en, fl = e.get("end"), e.get("filed")
                if not (en and fl) or fl > asof:
                    continue
                if en not in best or fl < best[en][1]:
                    best[en] = (float(e["val"]), fl)
            for en, (v, fl) in best.items():
                pts.append((fl, en, v * _sfa(px["splits"], fl)))
    pts.sort()
    if not pts:
        return None
    months = [m for m in sorted(px["close"])
              if xbrl_start <= m <= asof[:7] and _month_end(m) <= asof]
    ser = {}
    for mk in months:
        me = _month_end(mk)
        t = ttm_at(acc, me)
        if not t or t["val"] <= 0:
            continue
        sh = None
        for fl, en, v in pts:
            if fl <= me:
                sh = v
            else:
                break
        if sh is None:
            continue
        ser[mk] = px["close"][mk] * sh / t["val"]
    return ser


def audit_percentile_rebuild(tickers, vint=2018, asof="2018-07-01"):
    d = load(vint)
    out = []
    for t in tickers:
        r = next((x for x in d["rows"] if x["ticker"] == t), None)
        if not r or not r.get("cik"):
            continue
        try:
            ser = rebuild_pe_series(t, r["cik"], asof)
        except Exception as e:
            out.append({"ticker": t, "verdict": "再構成に失敗: %s" % e})
            continue
        if not ser:
            out.append({"ticker": t, "verdict": "再構成できない（株数か利益が無い）"})
            continue
        now_mk = max(ser)
        now = ser[now_mk]
        hist = [v for k, v in ser.items() if k < now_mk]
        pct = ((sum(1 for h in hist if h < now) + 0.5 * sum(1 for h in hist if h == now))
               / len(hist)) if hist else None
        rec = {"ticker": t, "now_month": now_mk,
               "indep_pe": round(now, 4), "row_pe": r.get("pe"),
               "indep_pe_pct": round(pct, 4) if pct is not None else None,
               "row_pe_pct": r.get("pe_pct"),
               "indep_hist_months": len(hist), "row_hist_months": r.get("pe_hist_months"),
               "indep_median_hist": round(med(hist), 3) if hist else None,
               "row_median_hist": (r.get("extras") or {}).get("pe_median_hist")}
        ok_pe = (rec["row_pe"] and abs(rec["indep_pe"] / rec["row_pe"] - 1) <= 0.02)
        ok_pct = (rec["row_pe_pct"] is not None and pct is not None
                  and abs(pct - rec["row_pe_pct"]) <= 0.05)
        rec["verdict"] = ("OK（水準2%以内・分位0.05以内で一致）" if (ok_pe and ok_pct)
                          else "★食い違い（要調査）")
        rec["pe_ratio"] = (round(rec["indep_pe"] / rec["row_pe"], 4)
                           if rec["row_pe"] else None)
        out.append(rec)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# C  独立再現（事前登録の基準1〜4を自前で計算）
# ═══════════════════════════════════════════════════════════════════════════
def cell(rows, ind, thr, need_hist):
    """止める群／通す群に分け、基準1・2・4の材料を出す。"""
    pool = [r for r in rows if r.get(ind) is not None and r.get("tr_cagr") is not None]
    if need_hist:
        key = ind.replace("_z", "") + "_hist_months"
        pool = [r for r in pool if (r.get(key) or 0) >= Z_MIN_MONTHS]
    if not pool:
        return None
    stop = [r for r in pool if r[ind] >= thr]
    pas = [r for r in pool if r[ind] < thr]
    if not stop:
        return None
    base_n = sum(1 for r in pool if r["tr_cagr"] <= PERM)
    stop_n = sum(1 for r in stop if r["tr_cagr"] <= PERM)
    base = base_n / len(pool)
    prate = stop_n / len(stop)
    return {"ind": ind, "thr": thr, "n_pool": len(pool), "n_stop": len(stop),
            "stop_frac": stop_n and 0 or 0,
            "stopped_pct": len(stop) / len(pool),
            "base_perm": base, "stop_perm": prate,
            "ratio": (prate / base) if base > 0 else None,
            "numer": stop_n, "base_numer": base_n,
            "med_stop": med([r["tr_cagr"] for r in stop]),
            "med_pass": med([r["tr_cagr"] for r in pas]),
            "stopped_names": sorted(r["ticker"] for r in stop
                                    if r["tr_cagr"] <= PERM)}


def reproduce(pools_only=("quality", "full")):
    out = {}
    for v, asof in VINTAGES:
        d = load(v)
        rows = [r for r in d["rows"] if r.get("analysis_set")]
        for pool in pools_only:
            sub = [r for r in rows if r.get("quality")] if pool == "quality" else rows
            cells = []
            for ind in PCT_IND:
                for thr in GRID_PCT:
                    c = cell(sub, ind, thr, need_hist=False)
                    if c:
                        cells.append(c)
            for ind in Z_IND:
                for thr in GRID_Z:
                    c = cell(sub, ind, thr, need_hist=True)
                    if c:
                        cells.append(c)
            out["%d/%s" % (v, pool)] = {"n": len(sub), "cells": cells}
    return out


def judge(cells):
    """基準1(比>=2.0 かつ 分子>=5) / 基準2(止めた中央値<=通した中央値) / 基準4(<=15%)"""
    res = []
    for c in cells:
        c1 = (c["ratio"] is not None and c["ratio"] >= 2.0 and c["numer"] >= 5)
        c2 = (c["med_stop"] is not None and c["med_pass"] is not None
              and c["med_stop"] <= c["med_pass"])
        c4 = c["stopped_pct"] <= 0.15
        res.append(dict(c, c1=c1, c2=c2, c4=c4, all124=(c1 and c2 and c4)))
    return res


# ═══════════════════════════════════════════════════════════════════════════
# B3 検出力の天井
# ═══════════════════════════════════════════════════════════════════════════
def power_ceiling():
    """基準1(分子>=5) と 基準4(止めるのは<=15%) が**同時に**満たせるか。
    止められる最大人数 = floor(0.15*n)。その中に恒久毀損が5社以上いる必要がある
    ＝プール全体の恒久毀損の実数が5未満なら **どんな指標でも構造的に不合格**。"""
    out = {}
    for v, asof in VINTAGES:
        d = load(v)
        rows = [r for r in d["rows"] if r.get("analysis_set")]
        for pool in ("quality", "full"):
            sub = [r for r in rows if r.get("quality")] if pool == "quality" else rows
            sub = [r for r in sub if r.get("tr_cagr") is not None]
            n = len(sub)
            perm = [r for r in sub if r["tr_cagr"] <= PERM]
            cap = int(n * 0.15)
            base = len(perm) / n if n else 0
            # 比2.0 を満たすには 止めた群の毀損率 >= 2*base、分子>=5 なので
            # 止める人数 s は s <= cap かつ 分子 k>=5 かつ k/s >= 2*base → s <= k/(2*base)
            need_s_max = (len(perm) / (2 * base)) if base > 0 else None
            out["%d/%s" % (v, pool)] = {
                "n": n, "perm_n": len(perm), "base": round(base, 4),
                "cap_15pct": cap,
                "feasible_numer5": len(perm) >= 5 and cap >= 5,
                "max_stop_for_ratio2_if_all_perm_caught":
                    round(need_s_max, 1) if need_s_max else None,
                "note": ("止める上限%d社の中に恒久毀損が5社以上必要＝"
                         "プール全体の毀損%d社のうち %.0f%% 以上を"
                         "上位%.0f%%の高倍率だけで掴む必要がある"
                         % (cap, len(perm), 100 * 5 / max(len(perm), 1), 15))}
    return out


# ═══════════════════════════════════════════════════════════════════════════
# B1/B2 多重検定
# ═══════════════════════════════════════════════════════════════════════════
def multiplicity(rep):
    n_cells = sum(len(v["cells"]) for v in rep.values())
    per_vp = {k: len(v["cells"]) for k, v in rep.items()}
    # 1ビンテージ・1セルが基準1を満たす実測の頻度から、2ビンテージ同符号の偶然確率
    j = {k: judge(v["cells"]) for k, v in rep.items()}
    c1_hits = sum(sum(1 for c in v if c["c1"]) for v in j.values())
    c2_hits = sum(sum(1 for c in v if c["c2"]) for v in j.values())
    c124 = sum(sum(1 for c in v if c["all124"]) for v in j.values())
    p1 = c1_hits / n_cells if n_cells else 0
    p2 = c2_hits / n_cells if n_cells else 0
    # 指標×閾値の組（=「規則」）は 1ビンテージあたり len(cells)/1、規則数は指標×閾値
    n_rules = len(PCT_IND) * len(GRID_PCT) + len(Z_IND) * len(GRID_Z)
    return {
        "cells_total": n_cells, "cells_per_vintage_pool": per_vp,
        "rules_per_pool": n_rules,
        "rules_total_incl_pools": n_rules * 2,
        "spx_grid_note": ("spx_pe_pct は**ビンテージ内で定数**（買値時点の市場PERは1つ）"
                          "なので 3閾値×3ビンテージ = 全社を止めるか誰も止めないかの"
                          "9通りしかない＝独立な検定ではない"),
        "empirical_p_c1_per_cell": round(p1, 4),
        "empirical_p_c2_per_cell": round(p2, 4),
        "cells_passing_c1_and_c2_and_c4": c124,
        "chance_2vintage_same_rule_if_independent":
            round(1 - (1 - p1 ** 2) ** n_rules, 4) if p1 > 0 else 0.0,
        "note": ("基準3(2ビンテージ)が守っているのは『同じ規則が2回当たること』。"
                 "同じ指標の分位はビンテージ間で相関する（同じ会社が重複する）ので"
                 "独立仮定の見積もりは**下限**であり、実際の偶然確率はこれより高い"),
    }


def overlap_between_vintages():
    """基準3(2ビンテージで同符号)の独立性: 母集団がどれだけ重複しているか。"""
    sets = {}
    for v, _ in VINTAGES:
        d = load(v)
        sets[v] = {r["ticker"] for r in d["rows"] if r.get("analysis_set")}
        sets[str(v) + "q"] = {r["ticker"] for r in d["rows"]
                              if r.get("analysis_set") and r.get("quality")}
    def jac(a, b):
        A, B = sets[a], sets[b]
        return {"n_a": len(A), "n_b": len(B), "overlap": len(A & B),
                "overlap_frac_of_smaller": round(len(A & B) / min(len(A), len(B)), 3)}
    return {"2018_vs_2013": jac(2018, 2013), "2018_vs_2015": jac(2018, 2015),
            "2015_vs_2013": jac(2015, 2013),
            "quality_2018_vs_2013": jac("2018q", "2013q"),
            "quality_2018_vs_2015": jac("2018q", "2015q"),
            "quality_2015_vs_2013": jac("2015q", "2013q")}


# ═══════════════════════════════════════════════════════════════════════════
# B4 置換検定（多重検定の偽陽性率を仮定でなく実測で出す）
# ═══════════════════════════════════════════════════════════════════════════
def pool_rows(v, pool):
    d = load(v)
    rows = [r for r in d["rows"] if r.get("analysis_set")
            and r.get("tr_cagr") is not None]
    return [r for r in rows if r.get("quality")] if pool == "quality" else rows


def rules_matrix(rows):
    """各規則(指標×閾値)について『止める』真偽ベクトルを作る。順序は固定。"""
    out = []
    for ind in PCT_IND:
        for thr in GRID_PCT:
            idx = [i for i, r in enumerate(rows) if r.get(ind) is not None]
            if not idx:
                continue
            stop = {i for i in idx if rows[i][ind] >= thr}
            if stop:
                out.append(((ind, thr), idx, stop))
    for ind in Z_IND:
        key = ind.replace("_z", "") + "_hist_months"
        for thr in GRID_Z:
            idx = [i for i, r in enumerate(rows)
                   if r.get(ind) is not None and (r.get(key) or 0) >= Z_MIN_MONTHS]
            if not idx:
                continue
            stop = {i for i in idx if rows[i][ind] >= thr}
            if stop:
                out.append(((ind, thr), idx, stop))
    return out


def eval_rules(mat, ret):
    """基準1&2&4を満たした規則の集合を返す。ret は index -> tr_cagr。"""
    passed = set()
    for name, idx, stop in mat:
        n = len(idx)
        ns = len(stop)
        if ns / n > 0.15:                     # 基準4
            continue
        rs = [ret[i] for i in idx]
        base_k = sum(1 for x in rs if x <= PERM)
        if base_k == 0:
            continue
        base = base_k / n
        sk = sum(1 for i in stop if ret[i] <= PERM)
        if sk < 5:                            # 基準1（分子）
            continue
        if sk / ns < 2.0 * base:              # 基準1（比）
            continue
        ms = med([ret[i] for i in stop])
        mp = med([ret[i] for i in idx if i not in stop])
        if mp is None or ms > mp:             # 基準2
            continue
        passed.add(name)
    return passed


def permutation_fpr(n_perm=2000, seed=20260809):
    import random
    rnd = random.Random(seed)
    mats, rets = {}, {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            mats[(v, pool)] = rules_matrix(rows)
            rets[(v, pool)] = [r["tr_cagr"] for r in rows]
    out = {}
    for pool in ("quality", "full"):
        any_hit = {v: 0 for v, _ in VINTAGES}
        c3_hit = 0
        for _ in range(n_perm):
            got = {}
            for v, _ in VINTAGES:
                rs = list(rets[(v, pool)])
                rnd.shuffle(rs)
                p = eval_rules(mats[(v, pool)], rs)
                got[v] = p
                if p:
                    any_hit[v] += 1
            cnt = {}
            for v in got:
                for nm in got[v]:
                    cnt[nm] = cnt.get(nm, 0) + 1
            if any(c >= 2 for c in cnt.values()):
                c3_hit += 1
        out[pool] = {
            "n_perm": n_perm,
            "P_any_cell_passes_124_by_chance": {str(v): round(any_hit[v] / n_perm, 4)
                                                for v in any_hit},
            "P_criterion3_satisfied_by_chance": round(c3_hit / n_perm, 4),
            "n_rules_evaluated": {str(v): len(mats[(v, pool)]) for v, _ in VINTAGES},
        }
    return out


# ═══════════════════════════════════════════════════════════════════════════
# D 指標の作り方が効果を消していないか（構成概念妥当性）
# ═══════════════════════════════════════════════════════════════════════════
def coverage():
    out = {}
    for v, _ in VINTAGES:
        d = load(v)
        for pool in ("quality", "full"):
            rows = [r for r in d["rows"] if r.get("analysis_set")]
            rows = [r for r in rows if r.get("quality")] if pool == "quality" else rows
            n = len(rows)
            c = {"n_rows_total": len(d["rows"]), "n_analysis_pool": n}
            for ind in PCT_IND + Z_IND:
                k = sum(1 for r in rows if r.get(ind) is not None)
                if ind in Z_IND:
                    key = ind.replace("_z", "") + "_hist_months"
                    k = sum(1 for r in rows if r.get(ind) is not None
                            and (r.get(key) or 0) >= Z_MIN_MONTHS)
                c[ind] = {"n": k, "frac": round(k / n, 3) if n else None}
            out["%d/%s" % (v, pool)] = c
    return out


def quantiles_table(nq=5):
    out = {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            for ind in PCT_IND:
                sub = sorted((r for r in rows if r.get(ind) is not None),
                             key=lambda r: r[ind])
                if len(sub) < nq * 8:
                    continue
                bins = []
                for i in range(nq):
                    a = len(sub) * i // nq
                    b = len(sub) * (i + 1) // nq
                    g = sub[a:b]
                    rs = [r["tr_cagr"] for r in g]
                    bins.append({"q": i + 1, "n": len(g),
                                 "ind_range": [round(g[0][ind], 3),
                                               round(g[-1][ind], 3)],
                                 "median": round(med(rs), 4),
                                 "perm_rate": round(sum(1 for x in rs if x <= PERM)
                                                    / len(rs), 4),
                                 "win15_rate": round(sum(1 for x in rs if x >= 0.15)
                                                     / len(rs), 4)})
                out["%d/%s/%s" % (v, pool, ind)] = {
                    "bins": bins,
                    "Q5_minus_Q1_median": round(bins[-1]["median"] - bins[0]["median"], 4),
                    "Q5_minus_Q1_perm": round(bins[-1]["perm_rate"]
                                              - bins[0]["perm_rate"], 4)}
    return out


def sign_test():
    """基準2の向き（止めた群の中央値 − 通した群の中央値）の符号を数える。
    正なら『高い側のほうが儲かっていた』＝遮断器としては逆向き。"""
    rep = reproduce()
    out = {}
    for k, v in rep.items():
        gaps = [(c["ind"], c["thr"], round(c["med_stop"] - c["med_pass"], 4))
                for c in v["cells"]
                if c["med_stop"] is not None and c["med_pass"] is not None]
        pos = sum(1 for g in gaps if g[2] > 0)
        out[k] = {"n_cells": len(gaps), "positive_gap": pos,
                  "median_gap": round(med([g[2] for g in gaps]), 4) if gaps else None,
                  "worst_for_hypothesis": sorted(gaps, key=lambda g: -g[2])[:3]}
    return out


def construct_validity_2018():
    """pe_pct の高さが『価格が高い』ではなく『利益が一時的に低い』を測っていないか。
    TCJA(2017-12)の一時費用は 2018-06 時点の TTM 純利益に丸ごと乗る（join の caveat）。
    分解: pe/pe_median_hist（PERの押し上げ倍率） vs ps/ps_median_hist（価格側だけの押し上げ）。
    前者だけが大きい社は **分母の事故**であって『高い株価』ではない。"""
    d = load(2018)
    rows = [r for r in d["rows"] if r.get("analysis_set") and r.get("quality")]
    hi = [r for r in rows if (r.get("pe_pct") or 0) >= 0.90]
    det = []
    for r in hi:
        e = r.get("extras") or {}
        pem, psm = e.get("pe_median_hist"), e.get("ps_median_hist")
        pe_lift = (r["pe"] / pem) if (r.get("pe") and pem) else None
        ps_lift = (r["ps"] / psm) if (r.get("ps") and psm) else None
        det.append({"ticker": r["ticker"], "pe": r.get("pe"), "pe_pct": r.get("pe_pct"),
                    "ps_pct": r.get("ps_pct"), "pfcf_pct": r.get("pfcf_pct"),
                    "pe_lift": round(pe_lift, 3) if pe_lift else None,
                    "ps_lift": round(ps_lift, 3) if ps_lift else None,
                    "pe_over_ps_lift": round(pe_lift / ps_lift, 3)
                    if (pe_lift and ps_lift) else None,
                    "tr_cagr": r.get("tr_cagr")})
    ratios = [x["pe_over_ps_lift"] for x in det if x["pe_over_ps_lift"]]
    denom = [x for x in det if x["pe_over_ps_lift"] and x["pe_over_ps_lift"] >= 1.5]
    psq = [x for x in det if x["ps_pct"] is not None and x["ps_pct"] < 0.5]
    return {
        "n_pe_pct_ge_0.90_quality": len(hi),
        "median_pe_over_ps_lift": round(med(ratios), 3) if ratios else None,
        "n_denominator_artifact_ge1.5x": len(denom),
        "frac_denominator_artifact": round(len(denom) / len(det), 3) if det else None,
        "n_ps_pct_below_0.50": len(psq),
        "frac_ps_pct_below_0.50": round(len(psq) / len(det), 3) if det else None,
        "worst_10": sorted(det, key=lambda x: -(x["pe_over_ps_lift"] or 0))[:10],
        "reading": ("pe_over_ps_lift が大きい社は『株価が自己史上高い』のではなく"
                    "『TTM純利益が一時的に低い』。この検定が pe_pct で止めていたのは"
                    "その分だけ**別のもの**。ps_pct / pfcf_pct はこの事故を受けない"),
    }


def join_recheck():
    """rows の tr_cagr が retro_returns_*.json の実額そのままか（写しが化けていないか）。"""
    src = {2018: "retro_returns_2018.json", 2015: "retro_returns_2015.json",
           2013: "retro_returns_2013.json"}
    extra = {2015: ["retro_returns_2015_q.json"], 2013: ["retro_returns_2013_all.json"]}
    out = {}
    for v, _ in VINTAGES:
        ref = {}
        for fn in [src[v]] + extra.get(v, []):
            p = os.path.join(OUT, fn)
            if not os.path.exists(p):
                continue
            with open(p) as f:
                j = json.load(f)
            for r in j.get("rows", []):
                ref.setdefault(r["ticker"], []).append((fn, r.get("tr_cagr"),
                                                        r.get("start"), r.get("years")))
        d = load(v)
        miss, mism = [], []
        for r in d["rows"]:
            if r.get("tr_cagr") is None:
                continue
            got = ref.get(r["ticker"])
            if not got:
                miss.append(r["ticker"])
                continue
            if not any(abs((g[1] or -9) - r["tr_cagr"]) < 1e-9 for g in got):
                mism.append({"ticker": r["ticker"], "row": r["tr_cagr"],
                             "src": got})
        out[v] = {"n_with_return": sum(1 for r in d["rows"]
                                       if r.get("tr_cagr") is not None),
                  "not_found_in_source": miss[:10], "n_not_found": len(miss),
                  "value_mismatch": mism[:10], "n_mismatch": len(mism)}
    return out


# ═══════════════════════════════════════════════════════════════════════════
# E 検出力（この検定は、効果があったとして見つけられるのか）
# ═══════════════════════════════════════════════════════════════════════════
def oracle_power():
    """**神の遮断器**（恒久毀損した社を先に知っていて、それだけを止める）を当てる。
    これでも基準1〜4を通らないなら、その ビンテージ×プール は
    『効果が無い』ではなく **検定できていない**（検出力ゼロ）。"""
    out = {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            n = len(rows)
            cap = int(n * 0.15)
            perm = [r for r in rows if r["tr_cagr"] <= PERM]
            base = len(perm) / n if n else 0
            k = min(len(perm), cap)                 # 神が止められる毀損の数
            # 神は毀損だけを止める（止める人数 = k <= cap なので基準4は自動で通る）
            c1 = (k >= 5) and (base > 0) and ((1.0) >= 2.0 * base)
            rest = [r["tr_cagr"] for r in rows if r["tr_cagr"] > PERM] \
                if k == len(perm) else None
            ms = med([r["tr_cagr"] for r in perm[:k]])
            mp = med(rest) if rest is not None else None
            c2 = (ms is not None and mp is not None and ms <= mp)
            # 必要な捕捉率（毀損のうち何割を上位15%だけで掴む必要があるか）
            need_capture = (5 / len(perm)) if perm else None
            out["%d/%s" % (v, pool)] = {
                "n": n, "perm_total": len(perm), "base_perm": round(base, 4),
                "cap_15pct": cap,
                "oracle_numer": k,
                "oracle_passes_c1": bool(c1), "oracle_passes_c2": bool(c2),
                "oracle_passes_all": bool(c1 and c2),
                "required_capture_of_impairments_for_numer5":
                    round(need_capture, 3) if need_capture else None,
                "why": ("恒久毀損が%d社しか居ないので分子>=5 は**神でも作れない**"
                        % len(perm)) if len(perm) < 5 else
                       ("神なら通る（毀損%d社のうち5社を上位15%%で掴めばよい）" % len(perm)),
            }
    return out


def criterion3_feasibility(orc):
    """基準3（2ビンテージ以上）が、検出力のあるビンテージの組で満たせるか。"""
    out = {}
    for pool in ("quality", "full"):
        ok = [v for v, _ in VINTAGES if orc["%d/%s" % (v, pool)]["oracle_passes_all"]]
        out[pool] = {"vintages_with_any_power": ok,
                     "criterion3_satisfiable": len(ok) >= 2,
                     "verdict": ("基準3は**この プール では数学的に満たせない**"
                                 "（検出力のあるビンテージが%d個しかない）" % len(ok))
                     if len(ok) < 2 else "基準3は満たしうる"}
    return out


def min_detectable_effect():
    """止める割合 s ごとに、基準1を通すのに必要な『止めた群の毀損率』と
    『毀損全体の何割を掴む必要があるか』。効果の大きさの下限を実数で書く。"""
    out = {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            n = len(rows)
            perm = sum(1 for r in rows if r["tr_cagr"] <= PERM)
            base = perm / n if n else 0
            tab = []
            for s_frac in (0.05, 0.10, 0.15):
                s = int(n * s_frac)
                if s <= 0:
                    continue
                need_k = max(5, math.ceil(2.0 * base * s))
                tab.append({"stop_frac": s_frac, "stop_n": s,
                            "need_impairments_in_stopped": need_k,
                            "need_rate_in_stopped": round(need_k / s, 4),
                            "lift_vs_base": round((need_k / s) / base, 2)
                            if base > 0 else None,
                            "need_capture_of_all_impairments":
                                round(need_k / perm, 3) if perm else None,
                            "achievable": perm >= need_k})
            out["%d/%s" % (v, pool)] = {"n": n, "perm_total": perm,
                                        "base": round(base, 4), "grid": tab}
    return out


def lag_robustness():
    """A4 遅延感度: **年次更新だけ**で組んだ分位（pe_pct_ann / adj_pe_pct_ann）でも
    結論が同じか。年次版は読み取りが平均で半年ほど古い＝新鮮さ（や取り込みの速さ）が
    結論を作っているなら、ここで変わるはず。"""
    out = {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            cells = []
            for ind in ("pe_pct_ann", "adj_pe_pct_ann"):
                for thr in GRID_PCT:
                    c = cell(rows, ind, thr, need_hist=False)
                    if c:
                        cells.append(c)
            j = judge(cells)
            out["%d/%s" % (v, pool)] = {
                "n_cells": len(j),
                "all124_pass": sum(1 for c in j if c["all124"]),
                "c2_pass": sum(1 for c in j if c["c2"]),
                "median_gap_stop_minus_pass":
                    round(med([c["med_stop"] - c["med_pass"] for c in j
                               if c["med_stop"] is not None
                               and c["med_pass"] is not None]), 4) if j else None,
                "max_ratio": max([c["ratio"] for c in j
                                  if c["ratio"] is not None], default=None),
                "max_numer": max([c["numer"] for c in j], default=None)}
    return out


# ═══════════════════════════════════════════════════════════════════════════
# F 自己履歴を要求すること自体が左尾を削っていないか（検定の自己破壊）
# ═══════════════════════════════════════════════════════════════════════════
def attrition():
    """分析対象に入るには **36ヶ月以上の自己履歴** が要る。XBRL は段階適用
    （2009 大型加速／2010 加速／2011 その他）なので、asof が早いほど
    『2009年から申告している大型社』しか残らない。
    左尾（恒久毀損）は小型に多いので、**指標の要件そのものが事象を消す**恐れがある。
    ここでは 入った社 vs 落ちた社 を **同じ前方リターンの在庫**で比べる。"""
    out = {}
    for v, _ in VINTAGES:
        d = load(v)
        rows = d["rows"]
        ins = [r for r in rows if r.get("analysis_set") and r.get("tr_cagr") is not None]
        outs = [r for r in rows if not r.get("analysis_set")
                and r.get("tr_cagr") is not None]
        def stat(g):
            if not g:
                return None
            rs = [r["tr_cagr"] for r in g]
            mc = [r["mcap"] for r in g if r.get("mcap")]
            return {"n": len(g), "median_tr": round(med(rs), 4),
                    "perm_rate": round(sum(1 for x in rs if x <= PERM) / len(rs), 4),
                    "perm_n": sum(1 for x in rs if x <= PERM),
                    "median_mcap_musd": round(med(mc) / 1e6, 1) if mc else None,
                    "worst_tr": round(min(rs), 4)}
        # 在庫の全ユニバース（自己履歴の要件が無い側）
        univ = {}
        for fn in ("retro_returns_%d_all.json" % v, "retro_returns_%d.json" % v,
                   "retro_returns_%d_q.json" % v):
            p = os.path.join(OUT, fn)
            if not os.path.exists(p):
                continue
            with open(p) as f:
                j = json.load(f)
            for r in j.get("rows", []):
                if r.get("tr_cagr") is not None:
                    univ.setdefault(r["ticker"], r["tr_cagr"])
        urs = list(univ.values())
        out[v] = {
            "in_analysis_set": stat(ins),
            "excluded_no_self_history_or_return": stat(outs),
            "returns_inventory_universe": {
                "n": len(urs), "median_tr": round(med(urs), 4),
                "perm_rate": round(sum(1 for x in urs if x <= PERM) / len(urs), 4),
                "perm_n": sum(1 for x in urs if x <= PERM),
                "worst_tr": round(min(urs), 4)} if urs else None,
            "hist_months_of_included": {
                "median": med([r.get("hist_months") for r in ins
                               if r.get("hist_months")]),
                "min": min([r.get("hist_months") for r in ins
                            if r.get("hist_months")], default=None)},
        }
    return out


def sign_permutation(n_perm=2000, seed=7):
    """D3の『止めた群のほうが儲かっていた』は偶然か。置換で符号数の帰無分布を作る。
    セルは閾値の入れ子・ビンテージの重複で相関するので、二項検定ではなく置換で裁く。"""
    import random
    rnd = random.Random(seed)
    out = {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            mat = rules_matrix(rows)
            rs0 = [r["tr_cagr"] for r in rows]

            def npos(ret):
                k = 0
                for name, idx, stop in mat:
                    ms = med([ret[i] for i in stop])
                    mp = med([ret[i] for i in idx if i not in stop])
                    if ms is not None and mp is not None and ms > mp:
                        k += 1
                return k
            obs = npos(rs0)
            null = []
            for _ in range(n_perm):
                rs = list(rs0)
                rnd.shuffle(rs)
                null.append(npos(rs))
            ge = sum(1 for x in null if x >= obs)
            out["%d/%s" % (v, pool)] = {
                "n_cells": len(mat), "observed_positive": obs,
                "null_mean": round(sum(null) / len(null), 2),
                "p_one_sided": round((ge + 1) / (n_perm + 1), 4),
                "reading": ("『自己史上高い側のほうが前方リターンが高かった』が"
                            "偶然でこれほど揃う確率")}
    return out


def relaxed_grid():
    """H 『分子>=5』『比>=2.0』という線そのものを緩めたら候補は出るのか。
    出ないなら、不合格は**線の置き方の帰結ではない**（＝より強い否定）。
    出るなら、その分子を**社名で**出す（1〜2社なら規約にできない・台帳の一貫した基準）。"""
    rep = reproduce()
    out = []
    for rn in (5, 3, 1):
        for rr in (2.0, 1.5, 1.2):
            hits = []
            for k, v in rep.items():
                for c in v["cells"]:
                    if c["ratio"] is None:
                        continue
                    if (c["ratio"] >= rr and c["numer"] >= rn
                            and c["med_stop"] <= c["med_pass"]
                            and c["stopped_pct"] <= 0.15):
                        hits.append({"key": k, "ind": c["ind"], "thr": c["thr"],
                                     "ratio": round(c["ratio"], 2),
                                     "numer": c["numer"],
                                     "stop_n": c["n_stop"],
                                     "names": c["stopped_names"]})
            out.append({"min_numer": rn, "min_ratio": rr,
                        "n_pass": len(hits), "cells": hits})
    return out


def impairment_roster():
    """C2 の代わり: 合格候補が無いので、**止めるべきだった社**が実際に
    自己相対で高かったのかを一社ずつ出す（信号が存在しないことの直接の証拠）。"""
    out = {}
    for v, _ in VINTAGES:
        for pool in ("quality", "full"):
            rows = pool_rows(v, pool)
            perm = sorted((r for r in rows if r["tr_cagr"] <= PERM),
                          key=lambda r: r["tr_cagr"])
            if not perm:
                out["%d/%s" % (v, pool)] = {"n": 0, "note": "恒久毀損が1社も無い"}
                continue
            det = [{"ticker": r["ticker"], "tr_cagr": r["tr_cagr"],
                    "pe_pct": r.get("pe_pct"), "ps_pct": r.get("ps_pct"),
                    "pfcf_pct": r.get("pfcf_pct"), "adj_pe_pct": r.get("adj_pe_pct")}
                   for r in perm]
            got = [x for x in det
                   if max([y for y in (x["pe_pct"], x["ps_pct"], x["pfcf_pct"],
                                       x["adj_pe_pct"]) if y is not None],
                          default=0) >= 0.90]
            out["%d/%s" % (v, pool)] = {
                "n": len(det),
                "n_any_indicator_ge_0.90": len(got),
                "frac_flagged": round(len(got) / len(det), 3),
                "rows": det if pool == "quality" else det[:12]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true")
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--perm", type=int, default=2000)
    a = ap.parse_args()

    report = {"generated": "2026-08-09", "tool": "night/hist_val_lookahead.py",
              "lens": "look-ahead と多重検定の観点で事前登録の検定を壊しにかかる独立実装",
              "independence": ("hist_valuation.py / hist_val_gate_test.py を import しない。"
                               "SEC は companyconcept API から取り直す（採取器のキャッシュを使わない）")}

    # ── A1 構造スキャン
    a1 = {}
    for v, asof in VINTAGES:
        d = load(v)
        rows = d["rows"]
        ends = [r["diag"].get("ni_ttm_end") for r in rows if r.get("diag")]
        ages = [r["diag"].get("ni_ttm_age_days") for r in rows
                if r.get("diag", {}).get("ni_ttm_age_days") is not None]
        a1[v] = {
            "n_rows": len(rows),
            "ttm_end_after_asof": sorted(r["ticker"] for r in rows
                                         if (r["diag"].get("ni_ttm_end") or "") > asof),
            "px_month_after_asof": sorted(r["ticker"] for r in rows
                                          if (r.get("px_month") or "") > asof[:7]),
            "px_months_used": sorted({r["px_month"] for r in rows if r.get("px_month")}),
            "ttm_age_days": {"median": med(ages), "max": max(ages), "min": min(ages),
                             "n": len(ages)},
            "ret_start_set": sorted({r.get("ret_start") for r in rows
                                     if r.get("ret_start")})[:4],
        }
    report["A1_structural"] = a1

    # ── C 独立再現
    rep = reproduce()
    judged = {k: judge(v["cells"]) for k, v in rep.items()}
    report["C1_reproduce"] = {
        k: {"n_pool": rep[k]["n"],
            "n_cells": len(v),
            "c1_pass": sum(1 for c in v if c["c1"]),
            "c2_pass": sum(1 for c in v if c["c2"]),
            "c4_pass": sum(1 for c in v if c["c4"]),
            "all124_pass": sum(1 for c in v if c["all124"]),
            "best_by_ratio": sorted(
                [{"ind": c["ind"], "thr": c["thr"], "ratio": round(c["ratio"], 2)
                  if c["ratio"] else None, "numer": c["numer"],
                  "n_stop": c["n_stop"], "stopped_pct": round(c["stopped_pct"], 3),
                  "med_stop": c["med_stop"], "med_pass": c["med_pass"],
                  "c1": c["c1"], "c2": c["c2"], "c4": c["c4"]}
                 for c in v if c["ratio"] is not None],
                key=lambda x: -(x["ratio"] if x["ratio"] is not None else -1))[:5]}
        for k, v in judged.items()}
    report["C1_verdict"] = ("再現できた（合格セル0）"
                            if sum(sum(1 for c in v if c["all124"])
                                   for v in judged.values()) == 0
                            else "★再現できない（合格セルが出た）")
    report["C2_passing_cells_named"] = [
        {"key": k, "ind": c["ind"], "thr": c["thr"], "numer": c["numer"],
         "names": c["stopped_names"]}
        for k, v in judged.items() for c in v if c["all124"]]

    # ── B 多重検定
    report["B1_B2_multiplicity"] = multiplicity(rep)
    report["B_vintage_overlap"] = overlap_between_vintages()
    report["B3_power_ceiling"] = power_ceiling()
    report["B4_permutation_fpr"] = permutation_fpr(n_perm=a.perm)

    # ── D 指標の作り方（構成概念妥当性）
    report["D0_join_recheck"] = join_recheck()
    report["D1_coverage"] = coverage()
    report["D2_quantiles"] = quantiles_table()
    report["D3_sign_test"] = sign_test()
    report["D4_construct_validity_2018_pe"] = construct_validity_2018()

    # ── E 検出力
    orc = oracle_power()
    report["E1_oracle_power"] = orc
    report["E2_criterion3_feasibility"] = criterion3_feasibility(orc)
    report["E3_min_detectable_effect"] = min_detectable_effect()
    report["A4_lag_robustness"] = lag_robustness()
    report["F_attrition_selection"] = attrition()
    report["G_sign_permutation"] = sign_permutation(n_perm=a.perm)
    report["H_relaxed_grid"] = relaxed_grid()
    report["H_impairment_roster"] = impairment_roster()

    # ── A2/A3 SEC 一次データ
    if not a.no_net:
        d18 = load(2018)
        rows = d18["rows"]
        aset = [r for r in rows if r.get("analysis_set") and r.get("pe_pct") is not None]
        qual = [r for r in aset if r.get("quality")]
        # 無作為（seed固定＝再現可能）
        import random
        rnd = random.Random(20260809)
        rand_t = [r["ticker"] for r in rnd.sample(aset, min(a.sample, len(aset)))]
        # 敵対的: 分位が最も高い社（遮断器が止める側）
        adv = [r["ticker"] for r in sorted(qual, key=lambda r: -r["pe_pct"])[:a.sample]]
        picks = list(dict.fromkeys(rand_t + adv))
        report["A2_sample"] = {"random_seed": 20260809, "random": rand_t,
                               "adversarial_top_pe_pct_quality": adv}
        report["A2_sec_recheck"] = audit_lookahead_sec(2018, "2018-07-01", rows, picks)
        bad = [x for x in report["A2_sec_recheck"] if x.get("filed_le_asof") is False]
        report["A2_verdict"] = ("★未来の申告を使っている社がある: "
                                + ",".join(x["ticker"] for x in bad)) if bad else \
            "OK: 標本のすべてで、使われた決算は asof までに filed 済み"
        # A3 別APIでの二重確認
        chk = []
        for x in report["A2_sec_recheck"][:3]:
            if not x.get("parts"):
                continue
            s = sec_subs(x["cik"])
            recent = (s.get("filings") or {}).get("recent") or {}
            m = dict(zip(recent.get("accessionNumber", []), recent.get("filingDate", [])))
            for p in x["parts"]:
                chk.append({"ticker": x["ticker"], "accn": p["accn"],
                            "form": p["form"], "filed_in_facts": p["filed"],
                            "filed_in_submissions": m.get(p["accn"], "(古い年で索引外)"),
                            "match": m.get(p["accn"]) == p["filed"]
                            if p["accn"] in m else None})
        report["A3_submissions_crosscheck"] = chk
        # A5 分位そのものを独立に作り直す（履歴の側に未来が混ざっていないか）
        a5t = [x for x in ["ORCL", "CPRT", "BDX", "COLM", "BMI"] if x in picks] or picks[:3]
        report["A5_percentile_rebuild"] = audit_percentile_rebuild(a5t)
        badp = [x for x in report["A5_percentile_rebuild"]
                if x.get("verdict", "").startswith("★")]
        report["A5_verdict"] = ("★分位が再現できない: " + ",".join(x["ticker"] for x in badp)
                                if badp else
                                "OK: 自己履歴の分位を独立に作り直しても一致（履歴に未来は混ざっていない）")

    with open(os.path.join(OUT, "hist_val_lookahead.json"), "w") as f:
        report["src_tool_rev"] = seen_revs()   # 読み終えてから刻む
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items()
                      if k in ("A1_structural", "C1_verdict", "A2_verdict")},
                     ensure_ascii=False, indent=1)[:2500])
    print("→ out/hist_val_lookahead.json")


if __name__ == "__main__":
    main()
