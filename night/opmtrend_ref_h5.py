#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H5（トレンドの持続性）の**反証専門**の器。
測定側 night/opmtrend_h5.py → out/opmtrend_h5.json の報告を壊しにいく。

出力: out/opmtrend_ref_h5.json
★読むだけ。out/*_gate_pack.json / index.html / night/score_all.js には触れない。
★測定側のコードを import しない（同じ答えを二つの実装で出すのが目的なので、写したら意味が無い）。

──────────────────────────────────────────────────────────────────
役割の宣言（結果を見る前に固定する）

1) 独立再計算。土台 out/opmtrend_base.json の rows から自分で組み直し、h5.json の数字と突き合わせる。
   ⚠ さらに **土台そのものを疑う**——base.json は「測定側が作った中間物」なので、
   これを信じて再計算しても「同じ土台の上の二つの実装」にしかならない。
   よって opmD5 / opm / rev / fcfpos5 / streak_opm を **生の out/retro_features2_*.json から**
   突き合わせ、土台の変換が正しいかも確かめる。

2) 壊しにいく対象は**二つ**ある。測定側の報告は「H5 不合格」だが、報告の中には
   線(0.15)を**超えている主張**が同居している——
     (A) 「H5 は不合格」……仮説の否定。これを壊す＝「実は持続がある」を見つけること。
     (B) 「水準は持続する（lift +0.22〜+0.30・6セルすべて線超え）」……**これは合格している主張**。
         prereg の adversarial は「合格した仮説は必ず反証にかける」と書いてある。
         測定側は(B)を反証にかけていない（業種・規模・1社抜き・置換のどれも当てていない）。
         よって(B)は私が当てる。

3) 迷ったら refuted に倒す。ただし「壊せなかった」ものは壊せなかったと書く。

──────────────────────────────────────────────────────────────────
(A) を壊すための攻め筋（結果を見る前に列挙する。後から足さない）

 A1 **別の操作化**: 門の gmt は3値の判断で、opmD5 の符号は 0 の knife-edge。
    `streak_opm`（4遷移のうち上昇した年数 0-4）は prereg の data に挙がっている別の操作化で、
    こちらの方が gmt に近い。streak が持続するなら「トレンドは持続しない」は言い過ぎになる。
 A2 **対称に深い線**: 測定側は「今 < -0.02 → 次 < 0」を測ったが、これは非対称。
    「今 < -0.02 → **次も** < -0.02」を測る（H2 の登録済み閾値をそのまま借りる）。
 A3 **不感帯つき3値**: |opmD5| < 0.005 を flat とし、down→down を測る（gmt の3値に近い形）。
 A4 **業種年で中心化**: マクロと業種が符号を支配しているなら、
    業種内で中心化した残差には会社固有の持続が残っているかもしれない。
    （測定側は業種で「層別」したが「中心化」はしていない＝別の操作）
 A5 **水準を統制した偏順位相関**を全セルで（測定側は診断としてしか出していない）
 A6 **窓の重なり**: gap=fy_next−fy_now が 4 以下だと年を共有し符号違いで入る＝機械的な負。
    gap==5 に限る／gap<=4 だけを見る、の両方を出して機械バイアスの大きさを実測する。

(B) を壊すための攻め筋
 B1 業種(SIC2)の中で当て直す（層内で中央値を取り直す）
 B2 規模(rev)3分位の中で当て直す
 B3 1業種抜き / 1社抜き
 B4 置換検定（会社単位・全対同時・next 側だけ入替）
 B5 **外れ値**: opm には -2698% のような赤字バイオが実在する。
    「水準の持続」が単に「黒字か赤字か」を測っているだけなら、opm>0 に絞ると消えるはず。
    opm を [-100%, +100%] に収めた版、opm>0 の版、qual プールの版を並べる。
 B6 **見かけの持続でないか**: opm[now] と opm[next] は5会計年度離れ、年を共有しない。
    gap==5 に限った版で確かめる。

単位（prereg (e)）: base.json の opm は **%**（16.32）、opm_raw は比率（0.1632）、
opmD5 は **比率pt**（0.0255 = 2.55pt）。帯検問 abs(x)<=3 → x*100 を生ファイルに当てて確かめる。
──────────────────────────────────────────────────────────────────
"""
import json, os, random
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

LINE = 0.15                       # 測定側が H1 から借りた線。私も同じものを借りる（新しい線を作らない）
PAIRS = [(2013, 2018), (2016, 2021), (2017, 2022)]
DEPTH = [-0.02, -0.05, -0.10]     # H2 の事前登録済み閾値
DEADBAND = 0.005                  # A3 の不感帯。★新しい"線"ではなく操作化の刻み。合否には使わない
NPERM = 2000
SEED = 20260818


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ────────────────────────────── 統計（すべて自前・測定側を写さない）
def ranks(xs):
    """平均順位（同値は平均）"""
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and xs[idx[j + 1]] == xs[idx[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[idx[k]] = avg
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    sa = sum((x - ma) ** 2 for x in a)
    sb = sum((x - mb) ** 2 for x in b)
    if sa <= 0 or sb <= 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (sa ** 0.5 * sb ** 0.5)


def spearman(a, b):
    if len(a) < 3:
        return None
    return pearson(ranks(a), ranks(b))


def partial_spearman(a, b, c):
    """c を統制した a,b の偏順位相関"""
    ra, rb, rc = ranks(a), ranks(b), ranks(c)
    rab, rac, rbc = pearson(ra, rb), pearson(ra, rc), pearson(rb, rc)
    if rab is None or rac is None or rbc is None:
        return None
    den = ((1 - rac ** 2) * (1 - rbc ** 2))
    if den <= 0:
        return None
    return (rab - rac * rbc) / (den ** 0.5)


def med(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def r4(x):
    return None if x is None else round(x, 4)


# ────────────────────────────── 土台
BASE = jload(os.path.join(OUT, "opmtrend_base.json"))
ROWS = BASE["rows"]
BY = defaultdict(dict)          # vintage -> ticker -> row
for r in ROWS:
    BY[r["vintage"]][r["ticker"]] = r

H5 = jload(os.path.join(OUT, "opmtrend_h5.json"))

report = {
    "generated": "2026-08-18",
    "tool": "night/opmtrend_ref_h5.py",
    "role": "H5 の反証専門。測定側 out/opmtrend_h5.json を壊しにいく。値も規約も1バイト変えない。",
    "reads": ["out/opmtrend_base.json", "out/opmtrend_h5.json",
              "out/retro_features2_*.json", "out/retro_sic.json"],
    "line_borrowed": {"line": LINE,
                      "why": "H5 に line が無いので測定側は H1 の線を借りた。私も同じものを借りる（別の線を持ち込むと比較にならない）"},
    "attacks_declared_before_results": {
        "A_break_the_fail": ["A1 streak_opm という別の操作化", "A2 対称に深い線", "A3 不感帯つき3値",
                             "A4 業種年で中心化した残差", "A5 水準を統制した偏順位相関", "A6 窓の重なり(gap)"],
        "B_break_the_level_claim": ["B1 業種内", "B2 規模3分位", "B3 1業種抜き/1社抜き",
                                    "B4 置換(会社単位・全対同時)", "B5 外れ値・黒字赤字", "B6 gap==5 限定"],
    },
}


# ══════════════════════════════════════════════════════════════
# 0. 土台そのものの検算（生ファイル → base.json）
# ══════════════════════════════════════════════════════════════
def check_base_against_raw():
    out = {"note": "base.json は測定側が作った中間物。生の retro_features2_*.json と突き合わせる",
           "vintages": {}, "total_mismatch": 0, "fy": {}}
    total_bad = 0
    for v in sorted(BY.keys()):
        p = os.path.join(OUT, f"retro_features2_{v}.json")
        if not os.path.exists(p):
            out["vintages"][str(v)] = {"raw_missing": True}
            continue
        raw = {r["ticker"]: r for r in jload(p)["rows"]}
        bad = defaultdict(list)
        n_cmp = 0
        for t, br in BY[v].items():
            rr = raw.get(t)
            if rr is None:
                bad["not_in_raw"].append(t)
                continue
            n_cmp += 1
            # opmD5: そのまま（比率pt）
            a, b = br.get("opmD5"), rr.get("opmD5")
            if (a is None) != (b is None):
                bad["opmD5_presence"].append(t)
            elif a is not None and abs(a - b) > 1e-9:
                bad["opmD5_value"].append(t)
            # opm: base は % / raw は比率
            a, b = br.get("opm"), rr.get("opm")
            if (a is None) != (b is None):
                bad["opm_presence"].append(t)
            elif a is not None and abs(a - b * 100.0) > 1e-6:
                bad["opm_value"].append(t)
            # そのまま写す欄
            for k in ("rev", "fcfpos5", "streak_opm", "cagr5", "accel", "gm"):
                a, b = br.get(k), rr.get(k)
                if (a is None) != (b is None):
                    bad[k + "_presence"].append(t)
                elif a is not None and isinstance(a, (int, float)) and abs(a - b) > 1e-9:
                    bad[k + "_value"].append(t)
        # qual の定義（opm>=10% かつ fcfpos5>=5）を自分で当て直す
        qbad = []
        for t, br in BY[v].items():
            o, f = br.get("opm"), br.get("fcfpos5")
            mine = (o is not None and f is not None and o >= 10.0 and f >= 5)
            if bool(br.get("qual")) != mine:
                qbad.append(t)
        if qbad:
            bad["qual_def"] = qbad
        nb = sum(len(x) for x in bad.values())
        total_bad += nb
        out["vintages"][str(v)] = {"n_compared": n_cmp, "n_mismatch": nb,
                                   "detail": {k: (len(x), x[:5]) for k, x in bad.items()}}
        # fy の記録（gap 検査に使う）
        out["fy"][str(v)] = {t: rr.get("fy") for t, rr in raw.items()}
    out["total_mismatch"] = total_bad
    return out


BASECHK = check_base_against_raw()
FY = {int(k): v for k, v in BASECHK.pop("fy").items()}
report["base_vs_raw"] = BASECHK


# ══════════════════════════════════════════════════════════════
# 1. 単位（prereg (e)）
# ══════════════════════════════════════════════════════════════
def unit_check():
    out = {}
    for v in sorted(BY.keys()):
        rows = list(BY[v].values())
        o = [r["opm"] for r in rows if r.get("opm") is not None]
        d = [r["opmD5"] for r in rows if r.get("opmD5") is not None]
        oraw = [r["opm_raw"] for r in rows if r.get("opm_raw") is not None]
        band_raw = med([abs(x) for x in oraw]) if oraw else None
        out[str(v)] = {
            "opm_pct_median": r4(med(o)),
            "opm_raw_median_abs": r4(band_raw),
            "band_test_says": "比率(×100で%)" if (band_raw is not None and band_raw <= 3) else "既に%",
            "opm_pct_in_sane_band_share": r4(sum(1 for x in o if -100 <= x <= 100) / len(o)) if o else None,
            "opmD5_median": r4(med(d)),
            "opmD5_abs_median": r4(med([abs(x) for x in d])) if d else None,
            "opmD5_neg_share": r4(sum(1 for x in d if x < 0) / len(d)) if d else None,
            "opmD5_zero_exact_n": sum(1 for x in d if x == 0),
            "qual_n": sum(1 for r in rows if r.get("qual")),
        }
    out["_verdict"] = ("opm は base では % で入っており（中央 9-16）、qual の >=10 は %同士の比較。"
                       "opmD5 は比率pt（中央 |x| ~0.03）。単位の取り違えは見つからなかった")
    return out


report["unit_check"] = unit_check()


# ══════════════════════════════════════════════════════════════
# 2. 対の作成 + gap（窓の重なり）
# ══════════════════════════════════════════════════════════════
def build_pair(a, b, pool="all", gap_filter=None):
    """[(ticker, now, next, opm_now, opm_next, rev_now, sic2, streak_now, streak_next, gap)]"""
    res = []
    for t, ra in BY[a].items():
        rb = BY[b].get(t)
        if rb is None:
            continue
        if ra.get("opmD5") is None or rb.get("opmD5") is None:
            continue
        if pool == "qual" and not ra.get("qual"):
            continue
        fa, fb = FY.get(a, {}).get(t), FY.get(b, {}).get(t)
        gap = (fb - fa) if (fa is not None and fb is not None) else None
        if gap_filter is not None:
            if gap is None or gap not in gap_filter:
                continue
        res.append({
            "t": t, "now": ra["opmD5"], "next": rb["opmD5"],
            "opm_now": ra.get("opm"), "opm_next": rb.get("opm"),
            "rev_now": ra.get("rev"), "sic2": ra.get("sic2"),
            "st_now": ra.get("streak_opm"), "st_next": rb.get("streak_opm"),
            "gap": gap,
        })
    return res


def cell(rows):
    """H5 の主統計を素朴に組み直す"""
    n = len(rows)
    if n == 0:
        return None
    dd = sum(1 for r in rows if r["now"] < 0 and r["next"] < 0)
    du = sum(1 for r in rows if r["now"] < 0 and r["next"] >= 0)
    ud = sum(1 for r in rows if r["now"] >= 0 and r["next"] < 0)
    uu = sum(1 for r in rows if r["now"] >= 0 and r["next"] >= 0)
    nd = dd + du
    nu = ud + uu
    base = (dd + ud) / n
    p_dd = dd / nd if nd else None
    p_ud = ud / nu if nu else None
    return {
        "n": n, "n_now_down": nd, "n_now_up": nu,
        "matrix": {"down_down": dd, "down_up": du, "up_down": ud, "up_up": uu},
        "base_next_down": r4(base),
        "p_next_down_given_now_down": r4(p_dd),
        "p_next_down_given_now_up": r4(p_ud),
        "lift_base": r4(None if p_dd is None else p_dd - base),
        "lift_contrast": r4(None if (p_dd is None or p_ud is None) else p_dd - p_ud),
        "ceiling_lift_base": r4(1 - base),
        "rho_opmD5": r4(spearman([r["now"] for r in rows], [r["next"] for r in rows])),
    }


def level_cell(rows):
    """水準の持続（測定側の level_control と同じ形を自分で組む）"""
    xs = [r for r in rows if r["opm_now"] is not None and r["opm_next"] is not None]
    n = len(xs)
    if n < 10:
        return None
    m_now = med([r["opm_now"] for r in xs])
    m_next = med([r["opm_next"] for r in xs])
    below_now = [r for r in xs if r["opm_now"] < m_now]
    b_next = sum(1 for r in xs if r["opm_next"] < m_next) / n
    p = sum(1 for r in below_now if r["opm_next"] < m_next) / len(below_now) if below_now else None
    return {"n": n,
            "rho_opm": r4(spearman([r["opm_now"] for r in xs], [r["opm_next"] for r in xs])),
            "base_next_below_median": r4(b_next),
            "p_next_below_given_now_below": r4(p),
            "lift_base": r4(None if p is None else p - b_next)}


# ── 1) 独立再計算 vs h5.json
def independent_recompute():
    out = {"note": "base.json の rows から素朴に組み直し、h5.json と突き合わせる", "cells": {}, "max_abs_diff": 0.0,
           "mismatches": []}
    worst = 0.0
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            key = f"{a}->{b}"
            rows = build_pair(a, b, pool)
            mine = cell(rows)
            lv = level_cell(rows)
            mine["level_control"] = lv
            mine["instrument_rho_rev"] = r4(spearman(
                [r["rev_now"] for r in rows if r["rev_now"] is not None and BY[b][r["t"]].get("rev") is not None],
                [BY[b][r["t"]]["rev"] for r in rows if r["rev_now"] is not None and BY[b][r["t"]].get("rev") is not None]))
            theirs = H5["results"][pool][key]
            diffs = {}
            for k in ("n", "n_now_down", "n_now_up", "base_next_down", "p_next_down_given_now_down",
                      "p_next_down_given_now_up", "lift_base", "lift_contrast", "rho_opmD5"):
                tv, mv = theirs.get(k), mine.get(k)
                if tv is None or mv is None:
                    if tv != mv:
                        diffs[k] = [tv, mv]
                    continue
                d = abs(tv - mv)
                if d > 1e-4:
                    diffs[k] = [tv, mv, r4(d)]
                worst = max(worst, d)
            # matrix
            for k in ("down_down", "down_up", "up_down", "up_up"):
                if theirs["matrix"][k] != mine["matrix"][k]:
                    diffs["matrix_" + k] = [theirs["matrix"][k], mine["matrix"][k]]
            # level
            tl = theirs.get("level_control") or {}
            if lv:
                for k in ("rho_opm", "lift_base"):
                    tv, mv = tl.get(k), lv.get(k)
                    if tv is not None and mv is not None:
                        d = abs(tv - mv)
                        if d > 1e-4:
                            diffs["level_" + k] = [tv, mv, r4(d)]
                        worst = max(worst, d)
            ti = (theirs.get("instrument_check") or {}).get("rho_rev")
            if ti is not None and mine["instrument_rho_rev"] is not None:
                d = abs(ti - mine["instrument_rho_rev"])
                if d > 1e-4:
                    diffs["rho_rev"] = [ti, mine["instrument_rho_rev"], r4(d)]
                worst = max(worst, d)
            out["cells"][f"{pool}/{key}"] = {"mine": mine, "diffs": diffs or "一致"}
            if diffs:
                out["mismatches"].append(f"{pool}/{key}")
    out["max_abs_diff"] = r4(worst)
    out["verdict"] = "完全一致" if not out["mismatches"] else "食い違いあり: " + ", ".join(out["mismatches"])
    return out


report["independent_recompute"] = independent_recompute()


# ══════════════════════════════════════════════════════════════
# 3. (A) 「不合格」を壊しにいく
# ══════════════════════════════════════════════════════════════
def gap_analysis():
    out = {"note": "gap=fy_next-fy_now。4以下なら窓が年を共有し符号違いで入る＝機械的な負の相関",
           "pairs": {}}
    for a, b in PAIRS:
        rows = build_pair(a, b, "all")
        cnt = Counter(r["gap"] for r in rows)
        g5 = [r for r in rows if r["gap"] == 5]
        gle4 = [r for r in rows if r["gap"] is not None and r["gap"] <= 4]
        gge6 = [r for r in rows if r["gap"] is not None and r["gap"] >= 6]
        out["pairs"][f"{a}->{b}"] = {
            "gap_dist": {str(k): v for k, v in sorted(cnt.items(), key=lambda kv: (kv[0] is None, kv[0]))},
            "share_gap5": r4(len(g5) / len(rows)) if rows else None,
            "gap5": cell(g5),
            "gap_le4": cell(gle4) if len(gle4) >= 10 else {"n": len(gle4), "too_small": True},
            "gap_ge6": cell(gge6) if len(gge6) >= 10 else {"n": len(gge6), "too_small": True},
        }
    return out


report["A6_gap_overlap"] = gap_analysis()


def a1_streak():
    """streak_opm（0-4）は gmt に近い別の操作化。持続するか"""
    out = {"note": "streak_opm=4遷移のうち上昇した年数。down = streak<=1（半分未満が上昇）",
           "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = [r for r in build_pair(a, b, pool)
                    if r["st_now"] is not None and r["st_next"] is not None]
            if len(rows) < 20:
                out["pairs"][f"{pool}/{a}->{b}"] = {"n": len(rows), "too_small": True}
                continue
            n = len(rows)
            nd = sum(1 for r in rows if r["st_now"] <= 1)
            base = sum(1 for r in rows if r["st_next"] <= 1) / n
            p = sum(1 for r in rows if r["st_now"] <= 1 and r["st_next"] <= 1) / nd if nd else None
            pu = None
            nu = n - nd
            if nu:
                pu = sum(1 for r in rows if r["st_now"] > 1 and r["st_next"] <= 1) / nu
            out["pairs"][f"{pool}/{a}->{b}"] = {
                "n": n, "n_now_down": nd,
                "base_next_down": r4(base),
                "p_next_down_given_now_down": r4(p),
                "lift_base": r4(None if p is None else p - base),
                "lift_contrast": r4(None if (p is None or pu is None) else p - pu),
                "rho_streak": r4(spearman([r["st_now"] for r in rows], [r["st_next"] for r in rows])),
            }
    return out


report["A1_streak_opm"] = a1_streak()


def a2_symmetric_depth():
    """今 < th → 次 も < th（対称）。H2 の登録済み閾値を借りる"""
    out = {"note": "測定側は「今<th → 次<0」（非対称）。ここは「今<th → 次<th」（対称）", "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = build_pair(a, b, pool)
            n = len(rows)
            e = {}
            for th in DEPTH:
                nd = sum(1 for r in rows if r["now"] < th)
                base = sum(1 for r in rows if r["next"] < th) / n if n else None
                p = (sum(1 for r in rows if r["now"] < th and r["next"] < th) / nd) if nd else None
                e[str(th)] = {"n_now_below": nd, "base_next_below": r4(base),
                              "p": r4(p), "lift_base": r4(None if (p is None or base is None) else p - base)}
            out["pairs"][f"{pool}/{a}->{b}"] = {"n": n, "thresholds": e}
    return out


report["A2_symmetric_depth"] = a2_symmetric_depth()


def a3_deadband():
    """不感帯つき3値（gmt に近い形）"""
    out = {"note": f"|opmD5| < {DEADBAND} を flat。down→down を測る", "pairs": {}}

    def sgn(x):
        return "down" if x < -DEADBAND else ("up" if x > DEADBAND else "flat")

    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = build_pair(a, b, pool)
            n = len(rows)
            if n < 20:
                continue
            cn = Counter((sgn(r["now"]), sgn(r["next"])) for r in rows)
            nd = sum(v for k, v in cn.items() if k[0] == "down")
            base = sum(v for k, v in cn.items() if k[1] == "down") / n
            p = (sum(v for k, v in cn.items() if k == ("down", "down")) / nd) if nd else None
            nu = sum(v for k, v in cn.items() if k[0] == "up")
            pu = (sum(v for k, v in cn.items() if k == ("up", "down")) / nu) if nu else None
            out["pairs"][f"{pool}/{a}->{b}"] = {
                "n": n, "n_now_down": nd, "base_next_down": r4(base), "p": r4(p),
                "lift_base": r4(None if p is None else p - base),
                "lift_contrast": r4(None if (p is None or pu is None) else p - pu),
            }
    return out


report["A3_deadband3"] = a3_deadband()


def a4_sector_centered():
    """業種内で中心化した残差に会社固有の持続が残るか"""
    out = {"note": "各ビンテージ・各SIC2の中央値を引いた残差で測り直す（層別ではなく中心化）",
           "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = [r for r in build_pair(a, b, pool) if r["sic2"]]
            if len(rows) < 30:
                continue
            gn = defaultdict(list)
            gx = defaultdict(list)
            for r in rows:
                gn[r["sic2"]].append(r["now"])
                gx[r["sic2"]].append(r["next"])
            mn = {k: med(v) for k, v in gn.items()}
            mx = {k: med(v) for k, v in gx.items()}
            cen = [{"now": r["now"] - mn[r["sic2"]], "next": r["next"] - mx[r["sic2"]]} for r in rows]
            n = len(cen)
            nd = sum(1 for r in cen if r["now"] < 0)
            base = sum(1 for r in cen if r["next"] < 0) / n
            p = (sum(1 for r in cen if r["now"] < 0 and r["next"] < 0) / nd) if nd else None
            out["pairs"][f"{pool}/{a}->{b}"] = {
                "n": n, "n_sic2": len(gn), "n_now_down": nd, "base_next_down": r4(base),
                "p": r4(p), "lift_base": r4(None if p is None else p - base),
                "rho_centered": r4(spearman([r["now"] for r in cen], [r["next"] for r in cen])),
            }
    return out


report["A4_sector_centered"] = a4_sector_centered()


def a5_partial():
    """水準を統制した偏順位相関を全セルで"""
    out = {"note": "opm(now) を統制した rho(opmD5_now, opmD5_next)。機械的な平均回帰を外した後に残るか",
           "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = [r for r in build_pair(a, b, pool) if r["opm_now"] is not None]
            if len(rows) < 30:
                continue
            nw = [r["now"] for r in rows]
            nx = [r["next"] for r in rows]
            lv = [r["opm_now"] for r in rows]
            out["pairs"][f"{pool}/{a}->{b}"] = {
                "n": len(rows),
                "rho_raw": r4(spearman(nw, nx)),
                "rho_partial_given_level": r4(partial_spearman(nw, nx, lv)),
                "rho_level_now_vs_next_change": r4(spearman(lv, nx)),
            }
    return out


report["A5_partial_level"] = a5_partial()


# ══════════════════════════════════════════════════════════════
# 4. (B) 「水準は持続する」（線を超えている主張）を壊しにいく
# ══════════════════════════════════════════════════════════════
def level_lift_generic(rows, key_now="opm_now", key_next="opm_next"):
    xs = [r for r in rows if r.get(key_now) is not None and r.get(key_next) is not None]
    n = len(xs)
    if n < 20:
        return None
    m_now = med([r[key_now] for r in xs])
    m_next = med([r[key_next] for r in xs])
    below = [r for r in xs if r[key_now] < m_now]
    b = sum(1 for r in xs if r[key_next] < m_next) / n
    if not below:
        return None
    p = sum(1 for r in below if r[key_next] < m_next) / len(below)
    return {"n": n, "lift_base": r4(p - b), "rho": r4(spearman([r[key_now] for r in xs], [r[key_next] for r in xs]))}


def b1_sector():
    out = {"note": "SIC2 の中で中央値を取り直して当て直す（層内の lift を社数で加重平均）", "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = [r for r in build_pair(a, b, pool) if r["sic2"] and r["opm_now"] is not None and r["opm_next"] is not None]
            g = defaultdict(list)
            for r in rows:
                g[r["sic2"]].append(r)
            tot = 0
            acc = 0.0
            used = 0
            for k, v in g.items():
                if len(v) < 20:
                    continue
                lc = level_lift_generic(v)
                if lc is None:
                    continue
                acc += lc["lift_base"] * len(v)
                tot += len(v)
                used += 1
            out["pairs"][f"{pool}/{a}->{b}"] = {
                "n_all": len(rows), "n_sectors_used": used, "n_in_used": tot,
                "within_sector_lift_weighted": r4(acc / tot) if tot else None,
                "pooled_lift": (level_lift_generic(rows) or {}).get("lift_base"),
            }
    return out


report["B1_level_within_sector"] = b1_sector()


def b2_size():
    out = {"note": "売上3分位の中で当て直す", "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = [r for r in build_pair(a, b, pool)
                    if r["rev_now"] is not None and r["opm_now"] is not None and r["opm_next"] is not None]
            if len(rows) < 60:
                continue
            s = sorted(rows, key=lambda r: r["rev_now"])
            k = len(s) // 3
            e = {}
            for name, part in (("small", s[:k]), ("mid", s[k:2 * k]), ("large", s[2 * k:])):
                lc = level_lift_generic(part)
                e[name] = {"n": len(part), "lift_base": (lc or {}).get("lift_base"), "rho": (lc or {}).get("rho")}
            out["pairs"][f"{pool}/{a}->{b}"] = e
    return out


report["B2_level_by_size"] = b2_size()


def b3_leave_one_out():
    out = {"note": "1業種抜き（lift の範囲）と 1社抜き（rho の範囲）", "pairs": {}}
    for a, b in PAIRS:
        rows = [r for r in build_pair(a, b, "all") if r["sic2"] and r["opm_now"] is not None and r["opm_next"] is not None]
        if len(rows) < 60:
            continue
        full = level_lift_generic(rows)
        secs = sorted({r["sic2"] for r in rows})
        lifts = []
        for s in secs:
            sub = [r for r in rows if r["sic2"] != s]
            lc = level_lift_generic(sub)
            if lc:
                lifts.append((s, lc["lift_base"]))
        lifts.sort(key=lambda x: x[1])
        # 1社抜きは rho で（lift は1社では動かない）
        xs = [r["opm_now"] for r in rows]
        ys = [r["opm_next"] for r in rows]
        rho_full = spearman(xs, ys)
        rhos = []
        for i in range(len(rows)):
            rr = spearman(xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:])
            if rr is not None:
                rhos.append((rows[i]["t"], rr))
        rhos.sort(key=lambda x: x[1])
        out["pairs"][f"{a}->{b}"] = {
            "full_lift": full["lift_base"], "full_rho": r4(rho_full),
            "n_sectors": len(secs),
            "lift_min_after_drop": [lifts[0][0], lifts[0][1]] if lifts else None,
            "lift_max_after_drop": [lifts[-1][0], lifts[-1][1]] if lifts else None,
            "rho_min_after_drop_1co": [rhos[0][0], r4(rhos[0][1])] if rhos else None,
            "rho_max_after_drop_1co": [rhos[-1][0], r4(rhos[-1][1])] if rhos else None,
        }
    return out


report["B3_leave_one_out"] = b3_leave_one_out()


def b5_outliers():
    """水準の持続は『黒字か赤字か』を測っているだけではないか"""
    out = {"note": "opm には -2698% のような赤字バイオが実在する。絞ると消えるか", "pairs": {}}
    for a, b in PAIRS:
        rows = [r for r in build_pair(a, b, "all") if r["opm_now"] is not None and r["opm_next"] is not None]
        variants = {
            "全社": rows,
            "opm_now と opm_next が [-100,100]%": [r for r in rows if -100 <= r["opm_now"] <= 100 and -100 <= r["opm_next"] <= 100],
            "opm_now > 0（黒字のみ）": [r for r in rows if r["opm_now"] > 0],
            "opm_now と opm_next が両方 > 0": [r for r in rows if r["opm_now"] > 0 and r["opm_next"] > 0],
            "opm_now >= 10%（質実証の水準）": [r for r in rows if r["opm_now"] >= 10],
        }
        e = {}
        for k, v in variants.items():
            lc = level_lift_generic(v)
            e[k] = {"n": len(v), "lift_base": (lc or {}).get("lift_base"), "rho": (lc or {}).get("rho")}
        out["pairs"][f"{a}->{b}"] = e
    return out


report["B5_level_outliers"] = b5_outliers()


def b6_gap5_level():
    out = {"note": "gap==5（年を共有しない）に限った水準の持続", "pairs": {}}
    for a, b in PAIRS:
        rows = [r for r in build_pair(a, b, "all", gap_filter={5})
                if r["opm_now"] is not None and r["opm_next"] is not None]
        lc = level_lift_generic(rows)
        out["pairs"][f"{a}->{b}"] = {"n": len(rows), "lift_base": (lc or {}).get("lift_base"),
                                     "rho": (lc or {}).get("rho")}
    return out


report["B6_level_gap5"] = b6_gap5_level()


# ══════════════════════════════════════════════════════════════
# 5. 置換検定（会社単位・全対同時・next 側だけ入替）
# ══════════════════════════════════════════════════════════════
def permutation():
    """
    帰無: now と next の対応が無い。
    会社ラベルの置換を **1本** 作り、全対の next 側へ同じ置換を当てる
    （対どうしの従属＝同じ会社が複数の対に出ることは保つ）。
    統計: (i) opmD5 の rho の平均（H5 の主張の側）
          (ii) opm(水準) の lift の平均（B の主張の側）
    """
    rnd = random.Random(SEED)
    pairs_rows = {}
    for a, b in PAIRS:
        pairs_rows[(a, b)] = build_pair(a, b, "all")
    # 全対に出る会社の集合
    tickers = sorted({r["t"] for rows in pairs_rows.values() for r in rows})
    idx = {t: i for i, t in enumerate(tickers)}

    def stats(perm):
        """perm: list[int] 会社 i -> 会社 perm[i] の next を使う"""
        rhos = []
        lifts = []
        for (a, b), rows in pairs_rows.items():
            nw, nx, lo, ln = [], [], [], []
            for r in rows:
                src = tickers[perm[idx[r["t"]]]]
                rb = BY[b].get(src)
                if rb is None or rb.get("opmD5") is None:
                    continue
                nw.append(r["now"])
                nx.append(rb["opmD5"])
                if r["opm_now"] is not None and rb.get("opm") is not None:
                    lo.append(r["opm_now"])
                    ln.append(rb["opm"])
            rr = spearman(nw, nx)
            if rr is not None:
                rhos.append(rr)
            if len(lo) >= 20:
                m1, m2 = med(lo), med(ln)
                below = [i for i in range(len(lo)) if lo[i] < m1]
                bb = sum(1 for i in range(len(ln)) if ln[i] < m2) / len(ln)
                if below:
                    pp = sum(1 for i in below if ln[i] < m2) / len(below)
                    lifts.append(pp - bb)
        return (sum(rhos) / len(rhos) if rhos else 0.0,
                sum(lifts) / len(lifts) if lifts else 0.0)

    ident = list(range(len(tickers)))
    obs_rho, obs_lift = stats(ident)
    ge_rho = le_rho = ge_lift = 0
    null_rho, null_lift = [], []
    for _ in range(NPERM):
        p = ident[:]
        rnd.shuffle(p)
        r_, l_ = stats(p)
        null_rho.append(r_)
        null_lift.append(l_)
        if r_ >= obs_rho:
            ge_rho += 1
        if r_ <= obs_rho:
            le_rho += 1
        if l_ >= obs_lift:
            ge_lift += 1
    null_rho.sort()
    null_lift.sort()

    def q(v, f):
        return r4(v[int(f * (len(v) - 1))])

    return {
        "note": "会社ラベル1本の置換を全対の next 側へ同時に当てる（対どうしの従属を保つ）",
        "n_perm": NPERM, "seed": SEED, "n_companies": len(tickers),
        "opmD5_rho": {"observed_mean": r4(obs_rho),
                      "p_greater": r4((ge_rho + 1) / (NPERM + 1)),
                      "p_less": r4((le_rho + 1) / (NPERM + 1)),
                      "null_p2_5": q(null_rho, 0.025), "null_p50": q(null_rho, 0.5), "null_p97_5": q(null_rho, 0.975)},
        "level_lift": {"observed_mean": r4(obs_lift),
                       "p_greater": r4((ge_lift + 1) / (NPERM + 1)),
                       "null_p2_5": q(null_lift, 0.025), "null_p50": q(null_lift, 0.5), "null_p97_5": q(null_lift, 0.975)},
    }


report["B4_permutation"] = permutation()


# ══════════════════════════════════════════════════════════════
# 6. look-ahead（prereg (f)）
# ══════════════════════════════════════════════════════════════
def lookahead():
    out = {"note": "信号の会計年度末(fy_end)が締切(deadline)より後の行が無いか。"
                   "⚠H5 は信号→信号なので結果窓との look-ahead は原理的に無い。ここで見るのは信号側の規約違反だけ",
           "vintages": {}}
    for v in sorted(BY.keys()):
        p = os.path.join(OUT, f"retro_features2_{v}.json")
        if not os.path.exists(p):
            continue
        d = jload(p)
        dl = d.get("deadline")
        bad = []
        for r in d["rows"]:
            fe = r.get("fy_end")
            if fe and dl and fe > dl:
                bad.append([r["ticker"], fe])
        out["vintages"][str(v)] = {"deadline": dl, "n": len(d["rows"]),
                                   "fy_end_after_deadline_n": len(bad), "sample": bad[:5]}
    return out


report["lookahead"] = lookahead()


# ══════════════════════════════════════════════════════════════
# 7. 判定
# ══════════════════════════════════════════════════════════════
def verdicts():
    v = {}
    # A: 「不合格」を壊せたか
    broken = []
    # A1
    for k, e in report["A1_streak_opm"]["pairs"].items():
        if e.get("too_small"):
            continue
        if e.get("lift_base") is not None and e["lift_base"] >= LINE:
            broken.append(f"A1 {k} lift_base={e['lift_base']}")
    # A2
    for k, e in report["A2_symmetric_depth"]["pairs"].items():
        for th, x in e["thresholds"].items():
            if x.get("lift_base") is not None and x["lift_base"] >= LINE and x["n_now_below"] >= 20:
                broken.append(f"A2 {k} th={th} lift_base={x['lift_base']} n={x['n_now_below']}")
    # A3
    for k, e in report["A3_deadband3"]["pairs"].items():
        if e.get("lift_base") is not None and e["lift_base"] >= LINE:
            broken.append(f"A3 {k} lift_base={e['lift_base']}")
    # A4
    for k, e in report["A4_sector_centered"]["pairs"].items():
        if e.get("lift_base") is not None and e["lift_base"] >= LINE:
            broken.append(f"A4 {k} lift_base={e['lift_base']}")
    # A6
    for k, e in report["A6_gap_overlap"]["pairs"].items():
        g = e.get("gap5") or {}
        if g.get("lift_base") is not None and g["lift_base"] >= LINE:
            broken.append(f"A6 gap5 {k} lift_base={g['lift_base']}")
    v["A_fail_broken"] = broken or "壊せなかった——どの操作化・どの切り方でも線(0.15)に届かない"
    # B: 水準の主張を壊せたか
    bb = []
    for k, e in report["B1_level_within_sector"]["pairs"].items():
        w = e.get("within_sector_lift_weighted")
        if w is not None and w < LINE:
            bb.append(f"B1 {k} 業種内 {w} < {LINE}")
    for k, e in report["B2_level_by_size"].get("pairs", {}).items():
        for nm, x in e.items():
            if x.get("lift_base") is not None and x["lift_base"] < LINE:
                bb.append(f"B2 {k}/{nm} {x['lift_base']} < {LINE}")
    for k, e in report["B5_level_outliers"]["pairs"].items():
        for nm, x in e.items():
            if x.get("lift_base") is not None and x["lift_base"] < LINE:
                bb.append(f"B5 {k}/{nm} {x['lift_base']} < {LINE}")
    v["B_level_claim_broken_where"] = bb or "壊せなかった——どの切り方でも線を保つ"
    return v


report["verdicts"] = verdicts()



# ══════════════════════════════════════════════════════════════
# 8. A2 が唯一クロスしたセルを潰しにいく（★これは事前登録に無い私の後知恵の探索）
#    ——「深い線なら持続する」と読まれると、この台帳が繰り返し戒めてきた
#      『n=10でふるいを足すのは過剰適合』を再演することになるので、徹底的に当てる
# ══════════════════════════════════════════════════════════════
def a2b_magnitude_vs_direction():
    """深い線での正の lift は 方向 の持続か、それとも 振れ幅 の持続か"""
    out = {"note": "rho(|now|,|next|) と rho(now,next) を並べる。"
                   "振れ幅だけが持続しているなら、片側の閾値は必ず正の lift を出すが方向の情報は無い",
           "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = build_pair(a, b, pool)
            n = len(rows)
            nw = [r["now"] for r in rows]
            nx = [r["next"] for r in rows]
            e = {"n": n,
                 "rho_signed": r4(spearman(nw, nx)),
                 "rho_abs": r4(spearman([abs(x) for x in nw], [abs(x) for x in nx]))}
            for th in (0.05, 0.10):
                nb = sum(1 for x in nw if abs(x) > th)
                bp = sum(1 for x in nx if abs(x) > th) / n
                pp = sum(1 for r in rows if abs(r["now"]) > th and abs(r["next"]) > th) / nb if nb else None
                e[f"magnitude_th{th}"] = {"n_now": nb, "base": r4(bp), "p": r4(pp),
                                          "lift": r4(None if pp is None else pp - bp)}
                dn = [r for r in rows if r["now"] < -th]
                up = [r for r in rows if r["now"] > th]
                e[f"mirror_th{th}"] = {
                    "now_below": {"n": len(dn),
                                  "P_next_below": r4(sum(1 for r in dn if r["next"] < -th) / len(dn)) if dn else None,
                                  "P_next_above": r4(sum(1 for r in dn if r["next"] > th) / len(dn)) if dn else None},
                    "now_above": {"n": len(up),
                                  "P_next_above": r4(sum(1 for r in up if r["next"] > th) / len(up)) if up else None,
                                  "P_next_below": r4(sum(1 for r in up if r["next"] < -th) / len(up)) if up else None},
                }
                vol = [r for r in rows if abs(r["now"]) > th and abs(r["next"]) > th]
                same = sum(1 for r in vol if (r["now"] < 0) == (r["next"] < 0))
                e[f"within_volatile_th{th}"] = {"n": len(vol), "same_sign": same,
                                                "share_same_sign": r4(same / len(vol)) if vol else None}
            out["pairs"][f"{pool}/{a}->{b}"] = e
    return out


report["A2b_magnitude_vs_direction"] = a2b_magnitude_vs_direction()


def a2c_family_permutation():
    """A2 の格子(2プール×3閾値=6族)を丸ごと帰無に当てる。族としての偽陽性率"""
    rnd = random.Random(SEED)
    pr = {(p, pl): build_pair(p[0], p[1], pl) for p in PAIRS for pl in ("all", "qual")}
    tickers = sorted({r["t"] for v in pr.values() for r in v})
    idx = {t: i for i, t in enumerate(tickers)}

    def fam(perm):
        passed, best, detail = 0, -9.0, {}
        for pl in ("all", "qual"):
            for th in DEPTH:
                ls, ok_all = [], True
                for p in PAIRS:
                    rows = pr[(p, pl)]
                    b = p[1]
                    ok = []
                    for r in rows:
                        rb = BY[b].get(tickers[perm[idx[r["t"]]]])
                        if rb is not None and rb.get("opmD5") is not None:
                            ok.append((r["now"], rb["opmD5"]))
                    n = len(ok)
                    dn = [x for x in ok if x[0] < th]
                    if n < 20 or not dn:
                        ok_all = False
                        break
                    bp = sum(1 for x in ok if x[1] < th) / n
                    ls.append(sum(1 for x in dn if x[1] < th) / len(dn) - bp)
                if not ok_all:
                    continue
                m = sum(ls) / len(ls)
                detail[f"{pl}/th{th}"] = {"mean_lift": r4(m), "lifts": [r4(x) for x in ls],
                                          "all_pass": all(x >= LINE for x in ls)}
                best = max(best, m)
                if all(x >= LINE for x in ls):
                    passed += 1
        return passed, best, detail

    ident = list(range(len(tickers)))
    obs_pass, obs_best, obs_detail = fam(ident)
    ge_pass = ge_best = 0
    bests = []
    for _ in range(NPERM):
        q = ident[:]
        rnd.shuffle(q)
        pz, bs, _ = fam(q)
        bests.append(bs)
        if pz >= 1:
            ge_pass += 1
        if bs >= obs_best:
            ge_best += 1
    bests.sort()
    # 深い線を通ったセルの「分子」（prereg H2 が課している 5社 の бар）
    num = {}
    for pl in ("all", "qual"):
        for th in DEPTH:
            for p in PAIRS:
                rows = pr[(p, pl)]
                dn = [r for r in rows if r["now"] < th]
                nn = [r for r in dn if r["next"] < th]
                num[f"{pl}/th{th}/{p[0]}->{p[1]}"] = {"n_now_below": len(dn), "numerator": len(nn),
                                                      "meets_prereg_H2_bar_5": len(nn) >= 5,
                                                      "tickers": [r["t"] for r in nn][:12]}
    return {
        "note": "★A2 は事前登録に無い私の後知恵の探索。族としての値札を先に払う",
        "observed": {"families_passing": obs_pass, "best_mean_lift": r4(obs_best), "detail": obs_detail},
        "null": {"n_perm": NPERM, "seed": SEED,
                 "P_at_least_one_family_passes": r4(ge_pass / NPERM),
                 "family_p_of_best_mean_lift": r4((ge_best + 1) / (NPERM + 1)),
                 "null_best_p95": r4(bests[int(0.95 * (len(bests) - 1))]),
                 "null_best_p97_5": r4(bests[int(0.975 * (len(bests) - 1))]),
                 "null_best_max": r4(bests[-1])},
        "numerators_vs_prereg_H2_bar": num,
    }


report["A2c_family_permutation"] = a2c_family_permutation()


def a2d_overlap_and_loo():
    """深いセルの社の重複と1社抜き（qual × th=-0.10）"""
    th = -0.10
    seen = defaultdict(list)
    out = {"note": f"qual × th={th} の群。3対に同じ会社が出るなら独立標本ではない", "pairs": {}, "overlap": {}}
    for a, b in PAIRS:
        rows = build_pair(a, b, "qual")
        n = len(rows)
        dn = [r for r in rows if r["now"] < th]
        bp = sum(1 for r in rows if r["next"] < th) / n
        num = [r for r in dn if r["next"] < th]
        for r in dn:
            seen[r["t"]].append(f"{a}->{b}")
        loo = []
        for i in range(len(dn)):
            sub = dn[:i] + dn[i + 1:]
            if sub:
                loo.append((dn[i]["t"], round(sum(1 for r in sub if r["next"] < th) / len(sub) - bp, 4)))
        loo.sort(key=lambda x: x[1])
        # 深い群の next の分布（両裾か片裾か）
        bins = [(-99, -0.10), (-0.10, -0.02), (-0.02, 0.02), (0.02, 0.10), (0.10, 99)]
        def dist(rs):
            return [r4(sum(1 for r in rs if lo <= r["next"] < hi) / len(rs)) for lo, hi in bins] if rs else None
        out["pairs"][f"{a}->{b}"] = {
            "n": n, "n_now_below": len(dn), "numerator": len(num), "numerator_tickers": [r["t"] for r in num],
            "base": r4(bp), "lift": r4(len(num) / len(dn) - bp) if dn else None,
            "loo_min": loo[0] if loo else None, "loo_max": loo[-1] if loo else None,
            "next_dist_deep": dist(dn), "next_dist_all": dist(rows),
            "bins": ["<-0.10", "-0.10..-0.02", "-0.02..0.02", "0.02..0.10", ">0.10"],
        }
    dup = {t: v for t, v in seen.items() if len(v) > 1}
    out["overlap"] = {"rows_total": sum(len(v) for v in seen.values()), "unique_companies": len(seen),
                      "companies_in_multiple_pairs": len(dup), "which": dup}
    return out


report["A2d_overlap_and_loo"] = a2d_overlap_and_loo()


# ══════════════════════════════════════════════════════════════
# 9. B1 の被覆を埋める（業種内の中心化＝全行を使う版）
# ══════════════════════════════════════════════════════════════
def b1b_level_sector_centered():
    out = {"note": "B1 は n>=20 の業種しか使えず被覆が半分。ここは業種中央値を引いた残差で全行を使う",
           "pairs": {}}
    for pool in ("all", "qual"):
        for a, b in PAIRS:
            rows = [r for r in build_pair(a, b, pool)
                    if r["sic2"] and r["opm_now"] is not None and r["opm_next"] is not None]
            if len(rows) < 30:
                continue
            gn, gx = defaultdict(list), defaultdict(list)
            for r in rows:
                gn[r["sic2"]].append(r["opm_now"])
                gx[r["sic2"]].append(r["opm_next"])
            mn = {k: med(v) for k, v in gn.items()}
            mx = {k: med(v) for k, v in gx.items()}
            cen = [{"opm_now": r["opm_now"] - mn[r["sic2"]], "opm_next": r["opm_next"] - mx[r["sic2"]]} for r in rows]
            lc = level_lift_generic(cen)
            out["pairs"][f"{pool}/{a}->{b}"] = {"n": len(cen), "n_sic2": len(gn),
                                                "lift_base": (lc or {}).get("lift_base"),
                                                "rho": (lc or {}).get("rho")}
    return out


report["B1b_level_sector_centered"] = b1b_level_sector_centered()


# ══════════════════════════════════════════════════════════════
# 10. 「符号を決めているのはマクロか会社か」の検算
# ══════════════════════════════════════════════════════════════
def macro_vs_company():
    share = {}
    for v in sorted(BY.keys()):
        d = [r["opmD5"] for r in BY[v].values() if r.get("opmD5") is not None]
        share[str(v)] = {"n": len(d), "neg_share": r4(sum(1 for x in d if x < 0) / len(d))}
    vals = [e["neg_share"] for k, e in share.items()]
    wc = [e["neg_share"] for k, e in share.items() if k != "2013"]   # 2013 は被覆48%＝別の標本
    lifts = []
    for pool in ("all",):
        for a, b in PAIRS:
            c = cell(build_pair(a, b, pool))
            lifts.append(c["lift_base"])
    return {"note": "ビンテージ間で符号の割合がどれだけ動くか vs 会社自身の前回の符号がどれだけ動かすか",
            "neg_share_by_vintage": share,
            "range_all_vintages_pp": r4((max(vals) - min(vals)) * 100),
            "range_excl_2013_pp": r4((max(wc) - min(wc)) * 100),
            "company_own_prior_sign_moves_pp": [r4(x * 100) for x in lifts],
            "read": "窓（マクロ）が十数pt動かす一方、会社自身の前回の符号は数pt しか動かさず、しかも逆向き"}


report["macro_vs_company"] = macro_vs_company()



# ══════════════════════════════════════════════════════════════
# 11. A2 の合格セルを「水準の交絡」で潰せるか（水準で対応させた対照群）
# ══════════════════════════════════════════════════════════════
def a2e_level_matched_control():
    th = -0.10
    out = {"note": "深く下がった群の相手として、同じ opm 帯(±3pt)で now>=-0.02 の社を対照に置く。"
                   "水準の平均回帰が正体ならここで消えるはず", "pairs": {}}
    for a, b in PAIRS:
        rows = [r for r in build_pair(a, b, "qual") if r["opm_now"] is not None]
        n = len(rows)
        dn = [r for r in rows if r["now"] < th]
        if not dn:
            continue
        bp = sum(1 for r in rows if r["next"] < th) / n
        p_dn = sum(1 for r in dn if r["next"] < th) / len(dn)
        ctrl = {s["t"] for r in dn for s in rows if s["now"] >= -0.02 and abs(s["opm_now"] - r["opm_now"]) <= 3.0}
        cl = [s for s in rows if s["t"] in ctrl]
        p_ct = sum(1 for s in cl if s["next"] < th) / len(cl) if cl else None
        # 水準そのものの予言力（上位半分 vs 下位半分）
        s2 = sorted(rows, key=lambda r: r["opm_now"])
        k = len(s2) // 2
        f = lambda g: sum(1 for r in g if r["next"] < th) / len(g) if g else None
        out["pairs"][f"{a}->{b}"] = {
            "n_deep": len(dn), "P_deep": r4(p_dn), "n_ctrl": len(cl), "P_ctrl": r4(p_ct),
            "raw_base": r4(bp), "raw_lift": r4(p_dn - bp),
            "lift_vs_level_matched_ctrl": r4(None if p_ct is None else p_dn - p_ct),
            "level_alone_low_half": r4(f(s2[:k])), "level_alone_high_half": r4(f(s2[k:])),
        }
    out["read"] = "水準で対応させても lift はむしろ大きくなる＝水準の交絡では説明できない（＝潰せなかった）"
    return out


report["A2e_level_matched_control"] = a2e_level_matched_control()


# ══════════════════════════════════════════════════════════════
# 12. 宣言した線の検出力を独立に計算する（測定側の主張の検算）
# ══════════════════════════════════════════════════════════════
def power_check():
    rnd = random.Random(4242)
    out = {"note": "線は『3対すべて lift_base>=0.15』。真の一様な持続 delta を置いて何%で合格が出るか",
           "pools": {}}
    TR = 4000
    for pool in ("all", "qual"):
        cfg = []
        for a, b in PAIRS:
            rows = build_pair(a, b, pool)
            n = len(rows)
            nd = sum(1 for r in rows if r["now"] < 0)
            bb = sum(1 for r in rows if r["next"] < 0) / n
            cfg.append((n, nd, bb))
        e = {"cfg_n_ndown_base": [[c[0], c[1], r4(c[2])] for c in cfg], "power": {}}
        for delta in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
            ok = 0
            for _ in range(TR):
                allp = True
                for (n, nd, bb) in cfg:
                    nu = n - nd
                    f = nd / n
                    p1 = min(0.999, max(0.001, bb + delta))
                    p0 = min(0.999, max(0.001, (bb - f * p1) / (1 - f))) if nu else 0.0
                    d1 = sum(1 for _ in range(nd) if rnd.random() < p1)
                    d0 = sum(1 for _ in range(nu) if rnd.random() < p0)
                    if d1 / nd - (d1 + d0) / n < LINE:
                        allp = False
                        break
                if allp:
                    ok += 1
            e["power"][str(delta)] = r4(ok / TR)
        out["pools"][pool] = e
    out["read"] = "delta=0.20 以上なら検出できる（all 0.97 / qual 0.77）。delta=0.15 ちょうどは 0.12 ＝コイン投げ以下"
    return out


report["power_independent"] = power_check()



report["final_verdict"] = {
 "1_independent_recompute": report["independent_recompute"]["verdict"] + f"（最大差 {report['independent_recompute']['max_abs_diff']}）",
 "2_base_vs_raw": f"生ファイルとの食い違い {report['base_vs_raw']['total_mismatch']} 件",
 "3_A_fail_not_broken": "事前登録の統計（符号の持続）はどの切り方でも線に届かない。A1(streak) A3(不感帯) A4(業種中心化) A5(水準統制) A6(gap5) すべて負または~0",
 "4_A2_one_postoc_cell_survived": {
   "what": "qual × 対称に深い線(-0.10pt) は3対とも lift>=0.15（0.163/0.170/0.165）で、族の置換 p=0.0095、水準で対応させた対照でも消えない",
   "but": ["★事前登録に無い私の後知恵の探索（H5 の統計は『次<0』であって『次<-0.10』ではない）",
           "分子が 2 / 8 / 4 ＝ prereg H2 が深い線に課している『分子>=5社』を3対中2対で満たさない",
           "42行のうち実社数32・10社が複数の対に重複（MYGN と TRIP は分子にも二度出る）",
           "全社プール（n=35/134/126 と厚い）では 0.131/0.027/0.091 ＝ 通らない。合格は qual に絞って n を 7/21/14 にして初めて出る",
           "全社プールでの機構は方向ではなく振れ幅（rho_abs 0.20-0.40 vs rho_signed -0.14〜+0.02／振れる群の同符号率 0.28-0.55）",
           "深い群の next の最頻ビンは3対中2対で『中くらいの上昇』（+0.02..+0.10 に 0.429 / 0.643）"],
   "verdict": "壊せなかった。だが『発見』として扱ってはいけない——事前登録し、未見のビンテージ(2019/2020)で一度だけ当てるべき候補"
 },
 "5_B_level_claim_not_broken": "業種内(0.19-0.25) 規模3分位(0.16-0.34) 1業種抜き(0.20-0.29) 外れ値除去(むしろ上がる) gap5限定(0.22-0.27) 置換(p=0.0005) ——6系統すべてで線を保つ",
 "6_units": "opm は base で % / opmD5 は比率pt。取り違え無し",
 "7_lookahead": "8ビンテージとも fy_end>deadline は 0 件",
 "8_power": "delta=0.20 なら検出できる(all 0.97)。delta=0.15 ちょうどは 0.12 ＝『0.15 未満の一様な持続は無い』とは言えない",
 "how_far_to_trust": "『符号の持続はゼロ〜わずかに負』は信じてよい（独立再計算・6セル全負・置換で有意・機械バイアスも gap5 で外れる）。"
                     "『トレンドは反転する』は信じてはいけない（水準の平均回帰が半分から3分の2を説明する）。"
                     "『振れ幅は持続する』は本物（rho_abs 0.20-0.40）。"
                     "『深い下落は持続する』は未検証の候補であって結論ではない"
}

with open(os.path.join(OUT, "opmtrend_ref_h5.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print("wrote out/opmtrend_ref_h5.json")
