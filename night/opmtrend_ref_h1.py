# night/opmtrend_ref_h1.py — H1（選別器）の**反証専門**（2026-08-18新設）
#
# ★この器は測定側（night/opmtrend_h1.py）の報告を**壊しにいく**器である。迷ったら refuted に倒す。
#
#   役割は二つ:
#     ① **独立再計算** — opmtrend_base.py も opmtrend_h1.py も import せず、
#        out/retro_features2_*.json / out/retro_returns_*.json / out/retro_sic.json の**原本から**
#        結合・単位・lift を自分で組み直す。食い違ったら実データでどちらが正しいか決める。
#     ② **反証** — 測定側が「不合格だが弱い信号が残る」と主張した所見を、
#        業種 / 規模 / 1社抜き / 置換 / 単位 / look-ahead の6方向から壊す。
#
# ⚠ 値・規約・採点式・刻み・重み・関門・売却規律・配分には1バイトも触っていない（読むだけ）。
# ⚠ 事前登録 out/opm_trend_prereg.json の線は**後から動かさない**（lift>=0.15 かつ 8ビンテージ同符号）。
# ⚠ 0件は測定ではない。プール・分子が0になったら単位・欄名・照合の失敗を先に疑い名指しで警告する。
#
# 実行: python3 night/opmtrend_ref_h1.py [--json]

import json
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

PREREG = os.path.join(OUT, "opm_trend_prereg.json")
VINTAGES = [2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022]
SEED = 20260818

# ---- 事前登録から読む定数（ここで新しい線を作らない） -------------------------
_p = json.load(open(PREREG))
HURDLE = 0.15          # H1_selector: P(前方年率>=15%)
LINE = 0.15            # H1 の線
QUAL_OPM_PCT = 10.0    # 質実証: opm>=10%（%へ換算してから）
QUAL_FCFPOS = 5        # 質実証: 5年FCF全年黒字
MIN_GROUP = 20         # 薄い群の下限（警告用・合否には使わない）

WARN = []


def warn(s):
    WARN.append(s)


# ---- 原本の読み込み（測定側のコードを一行も使わない） -------------------------
def load_features(y):
    d = json.load(open(os.path.join(OUT, f"retro_features2_{y}.json")))
    return d, {r["ticker"]: r for r in d["rows"]}


def load_returns(y):
    """returns_priority: _all -> _q -> 素。**自分で優先順を当てる**（base を読まない）。"""
    for suf in ("_all", "_q", ""):
        p = os.path.join(OUT, f"retro_returns_{y}{suf}.json")
        if os.path.exists(p):
            d = json.load(open(p))
            return d, {r["ticker"]: r for r in d["rows"]}, os.path.basename(p)
    raise SystemExit(f"returns が無い: {y}")


def load_sic():
    d = json.load(open(os.path.join(OUT, "retro_sic.json")))
    return {r["ticker"]: r for r in d["rows"]}


def pct(x):
    """帯検問。比率で入っていれば%へ。(この台帳は opm=0.0979 を >=10 と比べて全社落とす罠を2度踏んでいる)"""
    if x is None:
        return None
    return x * 100.0 if abs(x) <= 3 else x


def med(v):
    return statistics.median(v) if v else None


def frac(v, f):
    return (sum(1 for x in v if f(x)) / len(v)) if v else None


# ---- 独立に組み直した結合 -----------------------------------------------------
def build():
    sic = load_sic()
    rows = []
    meta = {}
    for y in VINTAGES:
        fd, fmap = load_features(y)
        rd, rmap, rsrc = load_returns(y)
        bench = rd.get("benchmark") or {}
        bsym = bench.get("symbol")
        is_spy = (bsym == "SPY")

        # 単位: ファイル単位で opm の中央値の絶対値を見る
        ov = [abs(r["opm"]) for r in fd["rows"] if r.get("opm") is not None]
        opm_is_ratio = (med(ov) is not None and med(ov) <= 3)

        n_join = 0
        for t, f in fmap.items():
            r = rmap.get(t)
            if not r or r.get("tr_cagr") is None:
                continue
            n_join += 1
            o = f.get("opm")
            s = sic.get(t) or {}
            rows.append({
                "vintage": y, "ticker": t,
                "opmD5": f.get("opmD5"),           # 生の比率pt
                "opm_pct": pct(o) if o is not None else None,
                "fcfpos5": f.get("fcfpos5"),
                "rev": f.get("rev"),
                "cagr5": f.get("cagr5"),
                "streak_opm": f.get("streak_opm"),
                "tr_cagr": r.get("tr_cagr"),
                "years": r.get("years"),
                "mdd": r.get("mdd"),
                "sic2": s.get("sic2"),
                "sicDesc": s.get("sicDesc"),
                "bench_cagr": bench.get("tr_cagr"),
                "bench_is_spy": is_spy,
            })
        meta[str(y)] = {
            "features_src": f"retro_features2_{y}.json", "returns_src": rsrc,
            "features_n": len(fd["rows"]), "returns_n": len(rd["rows"]), "joined_n": n_join,
            "deadline": fd.get("deadline"), "asof_date": rd.get("asof_date"),
            "end_date": (rd["rows"][0].get("end") if rd["rows"] else None),
            "benchmark_symbol": bsym, "benchmark_is_spy": is_spy,
            "benchmark_tr_cagr": bench.get("tr_cagr"),
            "years_median": med([r["years"] for r in rd["rows"] if r.get("years")]),
            "opm_unit_ratio": opm_is_ratio,
            "opmD5_present": sum(1 for r in fd["rows"] if r.get("opmD5") is not None),
            "opmD5_median_abs": med([abs(r["opmD5"]) for r in fd["rows"] if r.get("opmD5") is not None]),
        }
        if not is_spy:
            warn(f"{y}: ベンチマークが SPY でない（{bsym}）——SPY超の割合を SPY と呼ばない")
        if not opm_is_ratio:
            warn(f"{y}: opm がファイル単位で%と判定された（中央 {med(ov)}）——他年と単位が違う疑い")
    return rows, meta


def pools(rows, y):
    """全社 / 質実証。**opmD5 が無い行はどちらのプールにも入れない**（H1 は opmD5 で切るため）。"""
    v = [r for r in rows if r["vintage"] == y and r["opmD5"] is not None]
    allp = v
    qual = [r for r in v
            if r["opm_pct"] is not None and r["opm_pct"] >= QUAL_OPM_PCT
            and r["fcfpos5"] is not None and r["fcfpos5"] >= QUAL_FCFPOS]
    return {"all": allp, "qual": qual}


def lift_of(rs, key="tr_cagr", hurdle=HURDLE):
    """lift = P(hurdle超 | opmD5>=0) - P(... | opmD5<0)。向きを固定する。"""
    a = [r for r in rs if r["opmD5"] >= 0]
    b = [r for r in rs if r["opmD5"] < 0]
    if not a or not b:
        return None
    pa = frac(a, lambda r: r[key] >= hurdle)
    pb = frac(b, lambda r: r[key] >= hurdle)
    bc = rs[0].get("bench_cagr")
    bt = (lambda r: (r["bench_cagr"] is not None and r[key] > r["bench_cagr"]))
    return {"n": len(rs), "n_pos": len(a), "n_neg": len(b),
            "base": frac(rs, lambda r: r[key] >= hurdle),
            "p_pos": pa, "p_neg": pb, "lift": pa - pb,
            "med_pos": med([r[key] for r in a]), "med_neg": med([r[key] for r in b]),
            "impair_pos": frac(a, lambda r: r[key] <= -0.15),
            "impair_neg": frac(b, lambda r: r[key] <= -0.15),
            "base_beat": frac(rs, bt), "beat_pos": frac(a, bt), "beat_neg": frac(b, bt),
            "lift_beat": (frac(a, bt) - frac(b, bt)) if bc is not None else None,
            "bench_cagr": bc, "bench_is_spy": rs[0].get("bench_is_spy")}


def spearman(a, b):
    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            r = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                rk[idx[k]] = r
            i = j + 1
        return rk
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else None


# ---- ① 独立再計算 vs 測定側 ---------------------------------------------------
def recompute(rows, meta):
    per = []
    for y in VINTAGES:
        P = pools(rows, y)
        for pk in ("all", "qual"):
            rs = P[pk]
            if len(rs) < MIN_GROUP:
                warn(f"{y}/{pk}: 群が薄い n={len(rs)}（<{MIN_GROUP}）——0件・薄い群は照合の失敗を先に疑うこと")
            L = lift_of(rs)
            if L is None:
                warn(f"{y}/{pk}: 片側が空でliftが作れない（n={len(rs)}）")
                continue
            sp = spearman([r["opmD5"] for r in rs], [r["tr_cagr"] for r in rs])
            L.update({"vintage": y, "pool": pk, "spearman_opmD5_tr": sp})
            per.append(L)
    return per


def compare_to_measured(per):
    """測定側 out/opmtrend_h1.json と突き合わせる。食い違いは名指し。"""
    p = os.path.join(OUT, "opmtrend_h1.json")
    if not os.path.exists(p):
        return {"status": "測定側の出力が無い", "mismatches": []}
    h = json.load(open(p))
    mine = {(c["vintage"], c["pool"]): c for c in per}
    mism, checked = [], 0
    for c in h.get("h1_per_cell", []):
        k = (c.get("vintage"), c.get("pool"))
        m = mine.get(k)
        if not m:
            mism.append({"cell": f"{k[0]}/{k[1]}", "what": "自分の側に無いセル"})
            continue
        # 測定側と自分の欄名は違う。**対応表を明示して全部当てる**（1欄だけ一致して「合った」と言わない）
        for fld, mine_k in (("n_opmD5", "n"), ("n_nonneg", "n_pos"), ("n_neg", "n_neg"),
                            ("lift_hit", "lift"), ("base_hit", "base"),
                            ("p_hit_nonneg", "p_pos"), ("p_hit_neg", "p_neg"),
                            ("med_tr_nonneg", "med_pos"), ("med_tr_neg", "med_neg"),
                            ("p_impair_nonneg", "impair_pos"), ("p_impair_neg", "impair_neg"),
                            ("lift_beat", "lift_beat"), ("base_beat", "base_beat")):
            if fld not in c:
                continue
            a, b = c[fld], m[mine_k]
            if a is None or b is None:
                continue
            checked += 1
            tol = 1e-9 if isinstance(a, int) and isinstance(b, int) else 5e-4
            if abs(a - b) > tol:
                mism.append({"cell": f"{k[0]}/{k[1]}", "field": fld, "measured": a, "mine": b,
                             "diff": round(b - a, 6)})
    return {"status": "突合せ済", "fields_checked": checked, "mismatches": mism,
            "agree": not mism}


# ---- ② 反証 -------------------------------------------------------------------
def strat_lift(rows_by_v, keyfn, labels=None):
    """層ごとに『ビンテージ内の lift』を出し、層内で束ねた中央値を返す。"""
    buckets = {}
    for y, rs in rows_by_v.items():
        groups = {}
        for r in rs:
            g = keyfn(r)
            if g is None:
                continue
            groups.setdefault(g, []).append(r)
        for g, gr in groups.items():
            L = lift_of(gr)
            if L and L["n_pos"] >= 10 and L["n_neg"] >= 10:
                buckets.setdefault(g, []).append({"vintage": y, **L})
    out = {}
    for g, cells in buckets.items():
        lf = [c["lift"] for c in cells]
        out[str(g)] = {
            "n_cells": len(cells), "n_total": sum(c["n"] for c in cells),
            "median_lift": round(med(lf), 4), "min": round(min(lf), 4), "max": round(max(lf), 4),
            "pos_cells": sum(1 for x in lf if x > 0), "neg_cells": sum(1 for x in lf if x < 0),
            "label": (labels or {}).get(str(g)),
        }
    return out


def perm_pvalue(rows_by_v, stat_fn, n=2000, seed=SEED, mode="rank"):
    """会社単位で**全ビンテージ同時に**混ぜる置換（ビンテージ内で独立に混ぜると従属が壊れる＝既記録）。

    mode="rank"（既定・正しい）: 会社の**一つの大域順序**を作り、各ビンテージの中で
      その順序に沿って結果を付け替える。ビンテージごとの行数と結果の多重集合が**不変**。
    mode="map"（自分が最初に書いた版・欠陥あり）: 会社→会社 の写像で結果を持ってくる。
      写像先がそのビンテージに居ないと行が落ちるので**標本が縮み帰無が太る**＝p が保守側へ歪む。
      欠陥を実証するために残してある。
    """
    rng = random.Random(seed)
    obs = stat_fn(rows_by_v)
    tickers = sorted({r["ticker"] for rs in rows_by_v.values() for r in rs})
    PRE = {y: sorted(rs, key=lambda r: r["ticker"]) for y, rs in rows_by_v.items()}
    ge = 0
    null = []
    sizes = []
    for _ in range(n):
        order = tickers[:]
        rng.shuffle(order)
        shuffled = {}
        if mode == "rank":
            rank = {t: i for i, t in enumerate(order)}
            for y, srt in PRE.items():
                idx = sorted(range(len(srt)), key=lambda i: rank[srt[i]["ticker"]])
                outs = [srt[i]["tr_cagr"] for i in idx]
                shuffled[y] = [{**srt[j], "tr_cagr": outs[j]} for j in range(len(srt))]
        else:
            mp = dict(zip(tickers, order))
            outcomes = {}
            for y, rs in rows_by_v.items():
                for r in rs:
                    outcomes.setdefault(r["ticker"], {})[y] = r["tr_cagr"]
            for y, rs in rows_by_v.items():
                nr = []
                for r in rs:
                    v = outcomes.get(mp[r["ticker"]], {}).get(y)
                    if v is None:
                        continue
                    nr.append({**r, "tr_cagr": v})
                shuffled[y] = nr
        sizes.append(sum(len(v) for v in shuffled.values()))
        s = stat_fn(shuffled)
        null.append(s)
        if s is not None and obs is not None and s >= obs:
            ge += 1
    null_s = sorted(x for x in null if x is not None)
    return {"mode": mode,
            "observed": round(obs, 5) if obs is not None else None,
            "p_one_sided": round((ge + 1) / (n + 1), 4), "n_perm": n,
            "null_median": round(med(null_s), 5) if null_s else None,
            "null_p95": round(null_s[int(0.95 * len(null_s))], 5) if null_s else None,
            "null_p99": round(null_s[int(0.99 * len(null_s))], 5) if null_s else None,
            "rows_observed": sum(len(v) for v in rows_by_v.values()),
            "rows_in_null_median": int(med(sizes)) if sizes else None}


def median_lift_stat(rows_by_v):
    lf = []
    for y, rs in rows_by_v.items():
        L = lift_of(rs)
        if L:
            lf.append(L["lift"])
    return med(lf) if lf else None


def by_vintage(rows, pool):
    return {y: pools(rows, y)[pool] for y in VINTAGES}


def tertile_key(rs, fld):
    """ビンテージ内で三分位に切る（層別は必ずビンテージ内で・基礎率の差を相殺）。"""
    v = sorted(r[fld] for r in rs if r.get(fld) is not None)
    if len(v) < 30:
        return None
    q1, q2 = v[len(v) // 3], v[2 * len(v) // 3]
    return q1, q2


def attack(rows):
    A = {}
    for pool in ("all", "qual"):
        RB = by_vintage(rows, pool)
        cells = {y: lift_of(rs) for y, rs in RB.items()}
        lf = [c["lift"] for c in cells.values() if c]
        base_summary = {
            "median_lift": round(med(lf), 4), "pooled_lift": None,
            "pos": sum(1 for x in lf if x > 0), "neg": sum(1 for x in lf if x < 0),
            "min": round(min(lf), 4), "max": round(max(lf), 4),
            "n_at_or_above_line": sum(1 for x in lf if x >= LINE),
        }
        allrows = [r for rs in RB.values() for r in rs]
        pl = lift_of(allrows)
        base_summary["pooled_lift"] = round(pl["lift"], 4) if pl else None

        # (a) 業種 SIC2
        sic_strat = strat_lift(RB, lambda r: r["sic2"])
        # 1業種抜き
        sics = sorted({r["sic2"] for r in allrows if r["sic2"]})
        drop1_sic = []
        for s in sics:
            RB2 = {y: [r for r in rs if r["sic2"] != s] for y, rs in RB.items()}
            m = median_lift_stat(RB2)
            if m is not None:
                drop1_sic.append({"drop_sic2": s, "median_lift": round(m, 4),
                                  "n_dropped": sum(1 for r in allrows if r["sic2"] == s)})
        drop1_sic.sort(key=lambda d: d["median_lift"])

        # ★エネルギー・資源を丸ごと抜く（2014-16の原油崩落が opmD5<0 と悪いリターンを同時に作る疑い）
        ENERGY = {"10", "12", "13", "29", "44", "46", "49"}
        RB_ne = {y: [r for r in rs if r["sic2"] not in ENERGY] for y, rs in RB.items()}
        no_energy = {"median_lift": round(median_lift_stat(RB_ne), 4),
                     "n_dropped": sum(1 for r in allrows if r["sic2"] in ENERGY),
                     "per_vintage": {str(y): (round(lift_of(rs)["lift"], 4) if lift_of(rs) else None)
                                     for y, rs in RB_ne.items()}}

        # (b) 規模 三分位
        size_strat = {}
        for lab, idx in (("小", 0), ("中", 1), ("大", 2)):
            cellsx = []
            for y, rs in RB.items():
                t = tertile_key(rs, "rev")
                if not t:
                    continue
                q1, q2 = t
                sub = [r for r in rs if r.get("rev") is not None and (
                    (idx == 0 and r["rev"] < q1) or (idx == 1 and q1 <= r["rev"] < q2) or (idx == 2 and r["rev"] >= q2))]
                L = lift_of(sub)
                if L and L["n_pos"] >= 10 and L["n_neg"] >= 10:
                    cellsx.append(L["lift"])
            if cellsx:
                size_strat[lab] = {"n_cells": len(cellsx), "median_lift": round(med(cellsx), 4),
                                   "pos": sum(1 for x in cellsx if x > 0), "neg": sum(1 for x in cellsx if x < 0),
                                   "min": round(min(cellsx), 4), "max": round(max(cellsx), 4)}

        # (g) ★opm 水準 三分位（この lift は『トレンド』ではなく『水準』の言い換えではないか）
        opm_strat = {}
        for lab, idx in ("低", 0), ("中", 1), ("高", 2):
            cellsx = []
            for y, rs in RB.items():
                t = tertile_key(rs, "opm_pct")
                if not t:
                    continue
                q1, q2 = t
                sub = [r for r in rs if r.get("opm_pct") is not None and (
                    (idx == 0 and r["opm_pct"] < q1) or (idx == 1 and q1 <= r["opm_pct"] < q2) or (idx == 2 and r["opm_pct"] >= q2))]
                L = lift_of(sub)
                if L and L["n_pos"] >= 10 and L["n_neg"] >= 10:
                    cellsx.append({"vintage": y, "lift": L["lift"], "n": L["n"]})
            if cellsx:
                v = [c["lift"] for c in cellsx]
                opm_strat[lab] = {"n_cells": len(cellsx), "median_lift": round(med(v), 4),
                                  "pos": sum(1 for x in v if x > 0), "neg": sum(1 for x in v if x < 0),
                                  "min": round(min(v), 4), "max": round(max(v), 4),
                                  "per_vintage": {str(c["vintage"]): round(c["lift"], 4) for c in cellsx}}

        # (c) 1社抜き（最も効いている社を抜くと消えるか）
        # 中央値liftへの寄与が最大の社を探す（全ビンテージから同一 ticker を抜く）
        tick = sorted({r["ticker"] for r in allrows})
        base_med = med(lf)
        d1 = []
        for t in tick:
            RB2 = {y: [r for r in rs if r["ticker"] != t] for y, rs in RB.items()}
            m = median_lift_stat(RB2)
            if m is not None:
                d1.append((round(m, 5), t))
        d1.sort()
        drop1_co = {"base_median_lift": round(base_med, 4),
                    "worst5_after_drop": [{"drop": t, "median_lift": v} for v, t in d1[:5]],
                    "best5_after_drop": [{"drop": t, "median_lift": v} for v, t in d1[-5:]],
                    "range": [d1[0][0], d1[-1][0]] if d1 else None}

        # (d) 置換（会社単位・全ビンテージ同時）
        perm = perm_pvalue(RB, median_lift_stat, n=2000, mode="rank")
        perm_bad = perm_pvalue(RB, median_lift_stat, n=2000, mode="map")

        # 1ビンテージ抜き（符号の割れがどれだけ脆いか）
        drop1_v = []
        for y in VINTAGES:
            RB2 = {k: v for k, v in RB.items() if k != y}
            lfs = [lift_of(v)["lift"] for v in RB2.values() if lift_of(v)]
            drop1_v.append({"drop_vintage": y, "median_lift": round(med(lfs), 4),
                            "same_sign": (all(x > 0 for x in lfs) or all(x < 0 for x in lfs)),
                            "n_at_line": sum(1 for x in lfs if abs(x) >= LINE)})

        # 会社の重複（実効の標本数）
        tk = {}
        for y, rs in RB.items():
            for r in rs:
                tk[r["ticker"]] = tk.get(r["ticker"], 0) + 1
        rep = {"unique_companies": len(tk),
               "rows": sum(tk.values()),
               "appear_in_all8": sum(1 for v in tk.values() if v == 8),
               "mean_appearances": round(sum(tk.values()) / len(tk), 2)}

        # ★多重検定の値札: 「どれか一つでも p<0.05 になる」確率
        A[pool] = {
            "base": base_summary,
            "a_sic2": sic_strat,
            "a_drop1_sic2_worst5": drop1_sic[:5],
            "a_drop1_sic2_best5": drop1_sic[-5:],
            "a_no_energy_resources": no_energy,
            "b_size_tertile": size_strat,
            "g_opm_tertile": opm_strat,
            "c_drop1_company": drop1_co,
            "c_drop1_vintage": drop1_v,
            "d_permutation_median_lift": perm,
            "d_permutation_my_buggy_version": perm_bad,
            "e_repeated_companies": rep,
        }
    return A


# ---- (e) 単位・欄名の検問 ------------------------------------------------------
def unit_checks(rows, meta):
    out = {}
    for y in VINTAGES:
        v = [r for r in rows if r["vintage"] == y]
        d5 = [r["opmD5"] for r in v if r["opmD5"] is not None]
        op = [r["opm_pct"] for r in v if r["opm_pct"] is not None]
        raw = json.load(open(os.path.join(OUT, f"retro_features2_{y}.json")))["rows"]
        rawopm = [r["opm"] for r in raw if r.get("opm") is not None]
        rawd5 = [r["opmD5"] for r in raw if r.get("opmD5") is not None]
        # per-row 帯検問との食い違い（ファイル単位判定が per-row と割れていないか）
        mixed = sum(1 for x in rawopm if abs(x) > 3)
        out[str(y)] = {
            "opmD5_median_abs": round(med([abs(x) for x in d5]), 5) if d5 else None,
            "opmD5_looks_ratio_pt": (med([abs(x) for x in d5]) < 0.5) if d5 else None,
            "opm_pct_median": round(med(op), 3) if op else None,
            "opm_raw_median": round(med(rawopm), 5) if rawopm else None,
            "opm_rows_gt3_absolute": mixed,
            "opmD5_zero_exactly": sum(1 for x in d5 if x == 0),
            "opmD5_extreme_gt1": sum(1 for x in d5 if abs(x) > 1.0),
            "opmD5_coverage": f"{len(d5)}/{len(raw)}",
            "opmD5_coverage_pct": round(100 * len(d5) / len(raw), 1) if raw else None,
        }
        if mixed:
            warn(f"{y}: opm に |x|>3 の行が {mixed} 件——ファイル単位の単位判定と per-row が割れている可能性")
    return out


# ---- (f) look-ahead ----------------------------------------------------------
def lookahead(meta):
    out = {}
    for y, m in meta.items():
        dl = m.get("deadline")
        st = m.get("asof_date")
        ok = (dl is not None and st is not None and dl <= st)
        out[y] = {"features_deadline": dl, "returns_window_start": st,
                  "signal_before_window": ok,
                  "end_date": m.get("end_date")}
        if not ok:
            warn(f"{y}: look-ahead の疑い（信号の締切 {dl} > 窓の開始 {st}）")
    # 実データで filed を直接確かめる
    ex = {}
    for y in VINTAGES:
        d = json.load(open(os.path.join(OUT, f"retro_features2_{y}.json")))
        fys = [r.get("fy_end") for r in d["rows"] if r.get("fy_end")]
        ex[str(y)] = {"note": d.get("note"), "fy_end_max": max(fys) if fys else None,
                      "deadline": d.get("deadline")}
    return {"per_vintage": out, "raw_note": ex}


# ---- 十分位（測定側の U字の主張を確かめる） -----------------------------------
def deciles(rows, pool):
    RB = by_vintage(rows, pool)
    bins = {i: [] for i in range(10)}
    for y, rs in RB.items():
        s = sorted(rs, key=lambda r: r["opmD5"])
        n = len(s)
        for i, r in enumerate(s):
            bins[min(9, i * 10 // n)].append(r)
    out = []
    for i in range(10):
        b = bins[i]
        if not b:
            continue
        out.append({
            "decile": i + 1, "n": len(b),
            "opmD5_median": round(med([r["opmD5"] for r in b]), 4),
            "p15": round(frac(b, lambda r: r["tr_cagr"] >= HURDLE), 4),
            "med_cagr": round(med([r["tr_cagr"] for r in b]), 4),
            "impair": round(frac(b, lambda r: r["tr_cagr"] <= -0.15), 4),
            "rev_median": med([r["rev"] for r in b if r.get("rev")]),
            "opm_pct_median": round(med([r["opm_pct"] for r in b if r.get("opm_pct") is not None]), 2),
        })
    return out


def abs_size_confound(rows, pool):
    """『大きく動いたことが左尾を作る』は規模の言い換えか——|opmD5| 十分位の売上と、規模統制後の左尾。"""
    RB = by_vintage(rows, pool)
    bins = {i: [] for i in range(10)}
    for y, rs in RB.items():
        s = sorted(rs, key=lambda r: abs(r["opmD5"]))
        n = len(s)
        for i, r in enumerate(s):
            bins[min(9, i * 10 // n)].append(r)
    rowsout = []
    for i in range(10):
        b = bins[i]
        if not b:
            continue
        rowsout.append({"decile": i + 1, "n": len(b),
                        "absD5_median": round(med([abs(r["opmD5"]) for r in b]), 4),
                        "impair": round(frac(b, lambda r: r["tr_cagr"] <= -0.15), 4),
                        "rev_median": med([r["rev"] for r in b if r.get("rev")]),
                        "opm_pct_median": round(med([r["opm_pct"] for r in b if r.get("opm_pct") is not None]), 2)})
    # 規模三分位の中で |opmD5| 上下半分の毀損を比べる
    within = {}
    for lab, idx in (("小", 0), ("中", 1), ("大", 2)):
        hi, lo = [], []
        for y, rs in RB.items():
            t = tertile_key(rs, "rev")
            if not t:
                continue
            q1, q2 = t
            sub = [r for r in rs if r.get("rev") is not None and (
                (idx == 0 and r["rev"] < q1) or (idx == 1 and q1 <= r["rev"] < q2) or (idx == 2 and r["rev"] >= q2))]
            if len(sub) < 20:
                continue
            m = med([abs(r["opmD5"]) for r in sub])
            hi += [r for r in sub if abs(r["opmD5"]) >= m]
            lo += [r for r in sub if abs(r["opmD5"]) < m]
        if hi and lo:
            within[lab] = {"n_hi": len(hi), "n_lo": len(lo),
                           "impair_hi": round(frac(hi, lambda r: r["tr_cagr"] <= -0.15), 4),
                           "impair_lo": round(frac(lo, lambda r: r["tr_cagr"] <= -0.15), 4),
                           "ratio": round(frac(hi, lambda r: r["tr_cagr"] <= -0.15) /
                                          max(frac(lo, lambda r: r["tr_cagr"] <= -0.15), 1e-9), 2)}
    return {"abs_decile": rowsout, "within_size_tertile": within}


# ---- 多重検定の値札（測定側が「弱い信号が残る」と言った統計量の族） -----------
def family_price(rows, n=2000, seed=SEED + 7):
    """★測定側の p=0.018 は**事前登録に無い事後の統計量**。
    同じデータから作れる統計量の族（中央値lift / プールlift / n加重lift / 順位相関の中央値 ×2プール）を
    同時に置換へ当て、『どれか一つでも p<0.05 になる』確率を出す。"""
    rng = random.Random(seed)
    RBs = {p: by_vintage(rows, p) for p in ("all", "qual")}

    # ★順位は先に作る。置換は結果の並べ替えなので rank(tr) は元の順位ベクトルの並べ替えで足りる
    def prep(RB):
        d = {}
        for y, rs in RB.items():
            srt = sorted(rs, key=lambda r: r["ticker"])
            d[y] = {"srt": srt,
                    "neg": [r["opmD5"] < 0 for r in srt],
                    "hit": [r["tr_cagr"] >= HURDLE for r in srt],
                    "rk_d5": rankvec([r["opmD5"] for r in srt]),
                    "rk_tr": rankvec([r["tr_cagr"] for r in srt])}
        return d

    def fast_sp(rk_a, rk_b):
        n = len(rk_a)
        ma = mb = (n + 1) / 2.0
        num = sum((x - ma) * (y - mb) for x, y in zip(rk_a, rk_b))
        da = sum((x - ma) ** 2 for x in rk_a) ** 0.5
        db = sum((y - mb) ** 2 for y in rk_b) ** 0.5
        return (num / (da * db)) if da and db else None

    def stats_fast(P, perm_idx=None):
        lf, sps, wsum, wn = [], [], 0.0, 0
        tA = tB = hA = hB = 0
        for y, d in P.items():
            n = len(d["srt"])
            idx = perm_idx[y] if perm_idx else list(range(n))
            hits = [d["hit"][i] for i in idx]
            rk_tr = [d["rk_tr"][i] for i in idx]
            nA = sum(1 for v in d["neg"] if not v)
            nB = n - nA
            if nA == 0 or nB == 0:
                continue
            a = sum(1 for v, h in zip(d["neg"], hits) if not v and h)
            b = sum(1 for v, h in zip(d["neg"], hits) if v and h)
            lf.append(a / nA - b / nB)
            wsum += (a / nA - b / nB) * n
            wn += n
            tA += nA; tB += nB; hA += a; hB += b
            sps.append(fast_sp(d["rk_d5"], rk_tr))
        pooled = (hA / tA - hB / tB) if tA and tB else None
        return {"median_lift": med(lf), "pooled_lift": pooled,
                "nweighted_lift": (wsum / wn if wn else None),
                "median_spearman": med([x for x in sps if x is not None])}

    def stats(RB):
        return stats_fast(prep(RB))

    obs = {p: stats(RBs[p]) for p in RBs}
    names = [(p, k) for p in RBs for k in obs[p]]
    ge = {k: 0 for k in names}
    tickers = sorted({r["ticker"] for RB in RBs.values() for rs in RB.values() for r in rs})
    # rank モード（行数と結果の多重集合が不変。map モードは標本が縮み帰無が太る＝自分が一度踏んだ欠陥）
    P = {p: prep(RB) for p, RB in RBs.items()}
    nulls = {k: [] for k in names}
    for _ in range(n):
        order = tickers[:]
        rng.shuffle(order)
        rank = {t: i for i, t in enumerate(order)}
        for p in RBs:
            perm_idx = {y: sorted(range(len(d["srt"])), key=lambda i: rank[d["srt"][i]["ticker"]])
                        for y, d in P[p].items()}
            st = stats_fast(P[p], perm_idx)
            for k, v in st.items():
                nulls[(p, k)].append(v)
                if v is not None and obs[p][k] is not None and v >= obs[p][k]:
                    ge[(p, k)] += 1
    res = {}
    for (p, k) in names:
        nl = sorted(x for x in nulls[(p, k)] if x is not None)
        pv = (ge[(p, k)] + 1) / (n + 1)
        res[f"{p}/{k}"] = {"observed": round(obs[p][k], 5) if obs[p][k] is not None else None,
                           "p": round(pv, 4),
                           "null_p95": round(nl[int(0.95 * len(nl))], 5) if nl else None}
    # family-wise: 帰無の下で「どれか一つでも p<0.05」= 各回で min over stats の順位
    fam = 0
    for i in range(n):
        hit = False
        for (p, k) in names:
            nl = sorted(x for x in nulls[(p, k)] if x is not None)
            if not nl:
                continue
            thr = nl[int(0.95 * len(nl))]
            v = nulls[(p, k)][i]
            if v is not None and v >= thr:
                hit = True
                break
        if hit:
            fam += 1
    res["_family_wise_any_p05"] = round(fam / n, 4)
    res["_note"] = ("★事前登録の線は lift>=0.15 かつ8ビンテージ同符号。中央値lift・プールlift・"
                    "n加重lift・順位相関はいずれも**事後に選んだ統計量**。族として当てるとこの値札になる")
    return res



# ---- ★追加の的を絞った検問 ---------------------------------------------------
def profitability_ladder(rows):
    """利益率の床だけを動かして lift を追う。『信号は赤字社の言い換えか』を直接見る。"""
    out = []
    floors = [("制限なし", None), ("opm>0", 0.0), ("opm>=5%", 5.0), ("opm>=10%", 10.0),
              ("opm>=10% ∧ FCF5", "qual")]
    for lab, f in floors:
        per, n = {}, 0
        for y in VINTAGES:
            rs = [r for r in rows if r["vintage"] == y and r["opmD5"] is not None]
            if f == "qual":
                rs = [r for r in rs if r["opm_pct"] is not None and r["opm_pct"] >= QUAL_OPM_PCT
                      and r["fcfpos5"] is not None and r["fcfpos5"] >= QUAL_FCFPOS]
            elif f is not None:
                rs = [r for r in rs if r["opm_pct"] is not None and r["opm_pct"] > f - 1e-9]
            n += len(rs)
            L = lift_of(rs)
            per[str(y)] = round(L["lift"], 4) if L else None
        v = [x for x in per.values() if x is not None]
        out.append({"floor": lab, "n": n, "median_lift": round(med(v), 4),
                    "pos": sum(1 for x in v if x > 0), "neg": sum(1 for x in v if x < 0),
                    "per_vintage": per})
    return out


def who_are_the_extremes(rows):
    """opmD5 の両端は何者か。『トレンド』を測っているのか『小型・赤字』を測っているのか。"""
    use = [r for r in rows if r["opmD5"] is not None]
    def prof(sub, lab):
        rv = [r["rev"] for r in sub if r.get("rev")]
        op = [r["opm_pct"] for r in sub if r.get("opm_pct") is not None]
        return {"group": lab, "n": len(sub),
                "rev_median_musd": round(med(rv) / 1e6, 0) if rv else None,
                "opm_pct_median": round(med(op), 1) if op else None,
                "loss_making_share": round(frac([r for r in sub if r.get("opm_pct") is not None],
                                                lambda r: r["opm_pct"] < 0), 3),
                "impair": round(frac(sub, lambda r: r["tr_cagr"] <= -0.15), 3),
                "p15": round(frac(sub, lambda r: r["tr_cagr"] >= HURDLE), 3)}
    return [prof([r for r in use if r["opmD5"] < -0.10], "深く負 (<-10pp)"),
            prof([r for r in use if -0.10 <= r["opmD5"] < -0.02], "やや負 (-10〜-2pp)"),
            prof([r for r in use if -0.02 <= r["opmD5"] <= 0.02], "ほぼ横這い (±2pp)"),
            prof([r for r in use if 0.02 < r["opmD5"] <= 0.10], "やや正 (+2〜+10pp)"),
            prof([r for r in use if r["opmD5"] > 0.10], "深く正 (>+10pp)")]


def window_and_coverage(rows):
    """(1) 窓の長さが opmD5 の符号で違わないか (2) opmD5 の欠測社は別の母集団か。"""
    out = {}
    for y in VINTAGES:
        raw = json.load(open(os.path.join(OUT, f"retro_features2_{y}.json")))["rows"]
        got = [r for r in raw if r.get("opmD5") is not None]
        miss = [r for r in raw if r.get("opmD5") is None]
        rs = [r for r in rows if r["vintage"] == y and r["opmD5"] is not None]
        a = [r["years"] for r in rs if r["opmD5"] >= 0 and r.get("years")]
        b = [r["years"] for r in rs if r["opmD5"] < 0 and r.get("years")]
        out[str(y)] = {
            "years_median_pos": med(a), "years_median_neg": med(b),
            "years_equal": (med(a) == med(b)) if a and b else None,
            "opmD5_coverage": f"{len(got)}/{len(raw)}",
            "coverage_pct": round(100 * len(got) / len(raw), 1) if raw else None,
            "missing_rev_median_musd": round(med([r["rev"] for r in miss if r.get("rev")]) / 1e6, 0) if miss else None,
            "present_rev_median_musd": round(med([r["rev"] for r in got if r.get("rev")]) / 1e6, 0) if got else None,
            "missing_opm_pct_median": round(med([pct(r["opm"]) for r in miss if r.get("opm") is not None]), 1) if miss else None,
            "present_opm_pct_median": round(med([pct(r["opm"]) for r in got if r.get("opm") is not None]), 1) if got else None,
        }
    return out


def main():
    rows, meta = build()
    per = recompute(rows, meta)
    cmpres = compare_to_measured(per)
    uc = unit_checks(rows, meta)
    la = lookahead(meta)
    atk = attack(rows)
    dec = {p: deciles(rows, p) for p in ("all", "qual")}
    absz = {p: abs_size_confound(rows, p) for p in ("all", "qual")}
    fam = family_price(rows)
    spa = spearman_attacks(rows)
    lad = profitability_ladder(rows)
    ext = who_are_the_extremes(rows)
    wcov = window_and_coverage(rows)

    # 事前登録の線での判定（自分で当て直す）
    verdict = {}
    for p in ("all", "qual"):
        cells = [c for c in per if c["pool"] == p]
        lf = [c["lift"] for c in cells]
        verdict[p] = {
            "n_vintages": len(lf),
            "same_sign": (all(x > 0 for x in lf) or all(x < 0 for x in lf)),
            "n_at_line": sum(1 for x in lf if abs(x) >= LINE),
            "median_lift": round(med(lf), 4),
            "min": round(min(lf), 4), "max": round(max(lf), 4),
            "pass": (all(x > 0 for x in lf) or all(x < 0 for x in lf)) and all(abs(x) >= LINE for x in lf),
        }

    out = {
        "generated": "2026-08-18",
        "tool": "night/opmtrend_ref_h1.py",
        "role": "H1（選別器）の**反証専門**。独立再計算＋6方向の攻撃。迷ったら refuted に倒す",
        "prereg": "out/opm_trend_prereg.json",
        "independence": ("opmtrend_base.py / opmtrend_h1.py を import していない。"
                         "retro_features2_*.json / retro_returns_*.json / retro_sic.json の原本から組み直した"),
        "seed": SEED,
        "line_from_prereg": "lift >= 0.15 かつ 8ビンテージすべてで符号が同じ",
        "my_verdict": verdict,
        "per_cell": per,
        "compare_to_measured": cmpres,
        "unit_checks": uc,
        "lookahead": la,
        "attacks": atk,
        "deciles": dec,
        "abs_move_vs_size": absz,
        "multiple_testing_price": fam,
        "spearman_attacks": spa,
        "profitability_ladder": lad,
        "who_are_the_extremes": ext,
        "window_and_coverage": wcov,
        "vintage_meta": meta,
        "warnings": WARN,
    }
    p = os.path.join(OUT, "opmtrend_ref_h1.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"書いた: {p}")
        print("独立再計算 vs 測定側:", cmpres["status"],
              "食い違い", len(cmpres["mismatches"]), "件 / 照合", cmpres.get("fields_checked"), "欄")
        for p2 in ("all", "qual"):
            v = verdict[p2]
            print(f"  {p2}: 中央値lift {v['median_lift']:+.4f} 同符号={v['same_sign']} 線到達 {v['n_at_line']}/8 → 合格={v['pass']}")
        print("警告", len(WARN), "件")
    return out



# ---- ★測定側が「弱いが本物」と言った所見への的を絞った攻撃 -------------------
def rankvec(v):
    idx = sorted(range(len(v)), key=lambda i: v[i])
    rk = [0.0] * len(v)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            rk[idx[k]] = r
        i = j + 1
    return rk


def resid_on(y, xs):
    """y を xs（複数）へ最小二乗回帰した残差。すべて順位に直してから使う＝偏順位相関。"""
    n = len(y)
    X = [[1.0] + [x[i] for x in xs] for i in range(n)]
    k = len(X[0])
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    # ガウス消去
    M = [XtX[a][:] + [Xty[a]] for a in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda rr: abs(M[rr][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        for rr in range(k):
            if rr == c:
                continue
            f = M[rr][c] / M[c][c]
            for cc in range(c, k + 1):
                M[rr][cc] -= f * M[c][cc]
    beta = [M[a][k] / M[a][a] for a in range(k)]
    return [y[i] - sum(beta[a] * X[i][a] for a in range(k)) for i in range(n)]


def partial_spearman(rs, ctrl_flds):
    """opmD5 と tr_cagr の**偏**順位相関（ctrl の順位を統制）。"""
    use = [r for r in rs if all(r.get(f) is not None for f in ctrl_flds)]
    if len(use) < 40:
        return None
    a = rankvec([r["opmD5"] for r in use])
    b = rankvec([r["tr_cagr"] for r in use])
    ctrls = [rankvec([r[f] for r in use]) for f in ctrl_flds]
    ra, rb = resid_on(a, ctrls), resid_on(b, ctrls)
    if ra is None or rb is None:
        return None
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return (num / (da * db)) if da and db else None


def spearman_attacks(rows):
    """★最も強く生き残った統計量（順位相関の中央値 +0.068・p=0.0005）を壊しにいく。"""
    out = {}
    for pool in ("all", "qual"):
        RB = by_vintage(rows, pool)
        raw = {}
        for y, rs in RB.items():
            raw[str(y)] = round(spearman([r["opmD5"] for r in rs], [r["tr_cagr"] for r in rs]), 4)
        base = med(list(raw.values()))

        # (i) 規模だけ統制
        p_rev = {str(y): (round(partial_spearman(rs, ["rev"]), 4) if partial_spearman(rs, ["rev"]) is not None else None)
                 for y, rs in RB.items()}
        # (ii) opm 水準だけ統制
        p_opm = {str(y): (round(partial_spearman(rs, ["opm_pct"]), 4) if partial_spearman(rs, ["opm_pct"]) is not None else None)
                 for y, rs in RB.items()}
        # (iii) 両方
        p_both = {str(y): (round(partial_spearman(rs, ["rev", "opm_pct"]), 4) if partial_spearman(rs, ["rev", "opm_pct"]) is not None else None)
                  for y, rs in RB.items()}

        # (iv) ★崩壊組を外す（opmD5 >= -0.05 だけ）——正の相関は左腕が作っているのでは
        trim = {}
        for y, rs in RB.items():
            sub = [r for r in rs if r["opmD5"] >= -0.05]
            trim[str(y)] = round(spearman([r["opmD5"] for r in sub], [r["tr_cagr"] for r in sub]), 4) if len(sub) > 40 else None
        # (v) 中央8割だけ（両端の十分位を落とす）
        mid = {}
        for y, rs in RB.items():
            s = sorted(rs, key=lambda r: r["opmD5"])
            n = len(s)
            sub = s[n // 10: n - n // 10]
            mid[str(y)] = round(spearman([r["opmD5"] for r in sub], [r["tr_cagr"] for r in sub]), 4) if len(sub) > 40 else None
        # (vi) 赤字社（opm<0）を外す
        prof = {}
        for y, rs in RB.items():
            sub = [r for r in rs if r.get("opm_pct") is not None and r["opm_pct"] > 0]
            prof[str(y)] = round(spearman([r["opmD5"] for r in sub], [r["tr_cagr"] for r in sub]), 4) if len(sub) > 40 else None
        # (vii) 業種内（SIC2×ビンテージの層内で順位に直してから束ねる）
        wsic = {}
        for y, rs in RB.items():
            A, B = [], []
            g = {}
            for r in rs:
                if r["sic2"]:
                    g.setdefault(r["sic2"], []).append(r)
            for s2, gr in g.items():
                if len(gr) < 15:
                    continue
                # ⚠層ごとに**[0,1]へ正規化**してから束ねる。生の順位を繋ぐと
                #   「小さい層は両方とも小さい順位」になり**層の大きさだけで正の相関が湧く**
                #   （自分が一度これで rho=0.40 という嘘を出した）
                n1 = len(gr)
                A += [(x - 0.5) / n1 for x in rankvec([r["opmD5"] for r in gr])]
                B += [(x - 0.5) / n1 for x in rankvec([r["tr_cagr"] for r in gr])]
            wsic[str(y)] = round(spearman(A, B), 4) if len(A) > 40 else None

        def m(d):
            v = [x for x in d.values() if x is not None]
            return {"median": round(med(v), 4) if v else None,
                    "pos": sum(1 for x in v if x > 0), "neg": sum(1 for x in v if x < 0),
                    "per_vintage": d}
        out[pool] = {
            "raw": m(raw),
            "partial_rev": m(p_rev),
            "partial_opm_level": m(p_opm),
            "partial_rev_and_opm": m(p_both),
            "drop_collapse_opmD5_ge_-0.05": m(trim),
            "middle_80pct_only": m(mid),
            "profitable_only_opm_gt0": m(prof),
            "within_sic2": m(wsic),
            "base_median": round(base, 4),
        }
    return out


if __name__ == "__main__":
    main()
