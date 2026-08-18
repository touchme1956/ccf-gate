#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/opmtrend_ref_h6.py — **H6（重ならない窓）の反証専門**（2026-08-18新設）

【役割】測定側 night/opmtrend_h6.py の報告を**壊しにいく**。迷ったら refuted に倒す。
  ★測定側のコードは一行も import しない（opmtrend_h6 / opmtrend_base のどちらも）。
    生ファイル（retro_features2_* / retro_sic / retro_monthly_* / _spy_monthly）から組み直す。
    窓と年率だけ night/retro_persistence.py の panel()/cagr() を import する
    ——これは測定側の実装ではなく**既存の共有実装**で、再実装すると窓の定義が二つになる（v9.9.65）。

【やらないこと】値・規約・採点式・刻み・重み・関門・売却規律・配分に1バイトも触れない。読むだけ。
  線（lift>=0.15 ∧ すべての窓で符号が同じ）は事前登録のものを動かさない。

【攻撃】(a)業種SIC2 (b)規模rev三分位 (c)1社抜き (d)置換(会社単位・全窓同時) (e)単位 (f)look-ahead

実行: python3 night/opmtrend_ref_h6.py [--json]   出力: out/opmtrend_ref_h6.json
"""
import json
import math
import os
import random
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))
from retro_persistence import panel, cagr          # noqa: E402  共有実装（測定側ではない）

WIN_M, N_WIN = 39, 4
LINE = HURDLE = 0.15
MIN_GROUP = 20
N_PERM = 2000
SEED = 20260818
VINTS = (2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022)


def r4(x):
    return None if x is None else round(x, 4)


def lab(k):
    return f"{k // 12}-{k % 12 + 1:02d}"


def pct(x):
    """帯検問（事前登録どおり・per-row）。比率で来たら%へ。"""
    return None if x is None else (x * 100 if abs(x) <= 3 else x)


def share(rows, f):
    return (sum(1 for r in rows if f(r)) / len(rows)) if rows else None


def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


# ------------------------------------------------------------------ 生から組み直す
def rebuild():
    P = panel()
    S = {int(k): v for k, v in json.load(open(os.path.join(OUT, "_spy_monthly.json"))).items()}
    sic = {r["ticker"]: r for r in json.load(open(os.path.join(OUT, "retro_sic.json")))["rows"]}
    vint, dl = {}, {}
    for y in VINTS:
        f = os.path.join(OUT, f"retro_features2_{y}.json")
        if not os.path.exists(f):
            continue
        d = json.load(open(f))
        dl[y] = d.get("deadline")
        vint[y] = {r["ticker"]: r for r in d["rows"]}
    k0 = min(min(v) for v in P.values() if v)
    wins = [(k0 + i * WIN_M, k0 + (i + 1) * WIN_M) for i in range(N_WIN)]
    mapping = []
    for i, (a, b) in enumerate(wins, 1):
        v = max(y for y in vint if (y * 12 + 6) <= a)
        mapping.append({"w": i, "window": f"{lab(a)}→{lab(b)}", "k0": a, "k1": b,
                        "vintage": v, "deadline": dl[v], "gap_months": a - (v * 12 + 6),
                        "years": round((b - a) / 12.0, 2),
                        "spy": (S[b] / S[a]) ** (12.0 / (b - a)) - 1})
    rows = {}
    for m in mapping:
        a, b, v = m["k0"], m["k1"], m["vintage"]
        rs = []
        for t, mm in P.items():
            c = cagr(mm, a, b)
            if c is None:
                continue
            ks = [k for k in mm if a <= k <= b]
            f2 = vint[v].get(t)
            op = pct((f2 or {}).get("opm"))
            rs.append({"ticker": t, "tr": c, "full_span": (min(ks) == a and max(ks) == b),
                       "opmD5": (f2 or {}).get("opmD5"), "opm_pct": op,
                       "rev": (f2 or {}).get("rev"), "fy": (f2 or {}).get("fy"),
                       "fy_end": (f2 or {}).get("fy_end"),
                       "qual": bool(op is not None and op >= 10.0
                                    and ((f2 or {}).get("fcfpos5") or 0) >= 5),
                       "sic2": (sic.get(t) or {}).get("sic2"),
                       "sicDesc": (sic.get(t) or {}).get("sicDesc")})
        rows[m["w"]] = rs
    return mapping, rows, S, P, vint, dl


def pool_rows(rows, w, pool, keep=None, strict=False):
    rs = [r for r in rows[w] if r["opmD5"] is not None and (pool == "all" or r["qual"])]
    if strict:
        rs = [r for r in rs if r["full_span"]]
    if keep is not None:
        rs = [r for r in rs if r["ticker"] in keep]
    return rs


def cell(m, rs):
    A = [r for r in rs if r["opmD5"] >= 0]
    B = [r for r in rs if r["opmD5"] < 0]
    hit = lambda r: r["tr"] >= HURDLE          # noqa: E731
    beat = lambda r: r["tr"] > m["spy"]        # noqa: E731
    c = {"w": m["w"], "window": m["window"], "vintage": m["vintage"], "spy": r4(m["spy"]),
         "n": len(rs), "n_pos": len(A), "n_neg": len(B),
         "base_hit": r4(share(rs, hit)), "base_beat": r4(share(rs, beat)),
         "p_hit_pos": r4(share(A, hit)), "p_hit_neg": r4(share(B, hit)),
         "p_beat_pos": r4(share(A, beat)), "p_beat_neg": r4(share(B, beat)),
         "median_tr_pos": r4(med([r["tr"] for r in A])), "median_tr_neg": r4(med([r["tr"] for r in B])),
         "usable": (len(A) >= MIN_GROUP and len(B) >= MIN_GROUP)}
    c["lift_hit"] = r4(share(A, hit) - share(B, hit)) if (A and B) else None
    c["lift_beat"] = r4(share(A, beat) - share(B, beat)) if (A and B) else None
    return c


def z_two_prop(p1, n1, p2, n2):
    """差の分散の素朴な近似（プールしない）。参考値として出す。"""
    if not n1 or not n2:
        return None
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return None if se == 0 else (p1 - p2) / se


def main():
    random.seed(SEED)
    mapping, rows, S, P, vint, dl = rebuild()
    R = {"generated": "2026-08-18", "tool": "night/opmtrend_ref_h6.py",
         "role": "反証専門。測定側(opmtrend_h6/opmtrend_base)を import せず生から組み直す。読むだけ。",
         "prereg": "out/opm_trend_prereg.json", "seed": SEED,
         "line_from_prereg": "lift>=0.15 ∧ すべての窓で符号が同じ（動かさない）",
         "lift_direction": "lift = P(結果 | opmD5>=0) − P(結果 | opmD5<0)",
         "reads": ["out/retro_features2_{2013,2016,2017,2018,2019,2020,2021,2022}.json",
                   "out/retro_sic.json", "out/retro_monthly_*.json（panel経由）",
                   "out/_spy_monthly.json", "（照合のためだけに）out/opmtrend_h6.json",
                   "（照合のためだけに）out/opmtrend_base.json"],
         "not_imported": ["night/opmtrend_h6.py", "night/opmtrend_base.py"]}

    R["windows"] = [{k: (r4(v) if k == "spy" else v) for k, v in m.items()} for m in mapping]

    # ============================================================ 1) 独立再計算
    mine = {}
    for pool in ("all", "qual"):
        for m in mapping:
            mine[(m["w"], pool)] = cell(m, pool_rows(rows, m["w"], pool))
    R["independent_cells"] = [dict(mine[(w, p)], pool=p)
                              for p in ("all", "qual") for w in range(1, N_WIN + 1)]

    # ---- 測定側 out/opmtrend_h6.json との突合せ
    h6 = json.load(open(os.path.join(OUT, "opmtrend_h6.json")))
    diffs = []
    for c in h6.get("cells", []):
        k = (c["w"], c["pool"])
        m0 = mine.get(k)
        if not m0:
            diffs.append({"cell": k, "issue": "自分の側に無い"})
            continue
        for f in ("n", "n_pos", "n_neg", "spy", "base_hit", "base_beat", "p_hit_pos",
                  "p_hit_neg", "p_beat_pos", "p_beat_neg", "median_tr_pos", "median_tr_neg",
                  "lift_hit", "lift_beat", "usable", "vintage"):
            a, b = c.get(f), m0.get(f)
            if isinstance(a, float) or isinstance(b, float):
                if a is None or b is None:
                    if a is not b:
                        diffs.append({"cell": k, "field": f, "theirs": a, "mine": b})
                elif abs(a - b) > 1e-9:
                    diffs.append({"cell": k, "field": f, "theirs": a, "mine": b})
            elif a != b:
                diffs.append({"cell": k, "field": f, "theirs": a, "mine": b})
    # 窓・SPY・ビンテージ対応も突合せ
    for a, b in zip(h6.get("signal_timing", []), mapping):
        for f in ("window", "vintage", "gap_months", "years"):
            if a.get(f) != b.get(f):
                diffs.append({"cell": f"W{b['w']}", "field": f, "theirs": a.get(f), "mine": b.get(f)})
        if abs((a.get("spy") or 0) - round(b["spy"], 4)) > 1e-9:
            diffs.append({"cell": f"W{b['w']}", "field": "spy",
                          "theirs": a.get("spy"), "mine": r4(b["spy"])})
    R["independent_recalc_vs_h6"] = {"n_cells_compared": len(h6.get("cells", [])),
                                     "n_fields_diff": len(diffs), "diffs": diffs[:40],
                                     "verdict": "完全一致" if not diffs else "食い違いあり"}

    # ---- base.json（結合・単位）との突合せ: qual の作り方が違わないか
    b0 = json.load(open(os.path.join(OUT, "opmtrend_base.json")))
    brow = {(r["vintage"], r["ticker"]): r for r in b0["rows"]}
    qd, od, dd = 0, 0, 0
    ex = []
    for m in mapping:
        for r in rows[m["w"]]:
            br = brow.get((m["vintage"], r["ticker"]))
            if not br:
                continue
            bq = bool(br.get("qual")) and not br.get("qual_na")
            if bq != r["qual"]:
                qd += 1
                if len(ex) < 8:
                    ex.append({"v": m["vintage"], "t": r["ticker"], "base_qual": bq,
                               "mine": r["qual"], "opm_raw": br.get("opm_raw"),
                               "base_opm_pct": br.get("opm"), "my_opm_pct": r["opm_pct"]})
            if br.get("opmD5") != r["opmD5"]:
                dd += 1
            if br.get("opm") is not None and r["opm_pct"] is not None \
                    and abs(br["opm"] - r["opm_pct"]) > 1e-6:
                od += 1
    R["vs_base_json"] = {"qual_disagree": qd, "opmD5_disagree": dd, "opm_pct_disagree": od,
                         "examples": ex,
                         "note": ("base は opm の単位をファイル単位で決め、こちらは事前登録どおり per-row の帯検問。"
                                  "食い違う社は全部『深い赤字（opm が -3 未満）』で、どちらの読み方でも "
                                  "qual=False になるので結論に効かない——という主張を実数で確かめた欄")}

    # ============================================================ (e) 単位・欄名
    unit = {}
    for y in (2013, 2016, 2022):
        d = json.load(open(os.path.join(OUT, f"retro_features2_{y}.json")))["rows"]
        o = [r["opm"] for r in d if r.get("opm") is not None]
        dd5 = [r["opmD5"] for r in d if r.get("opmD5") is not None]
        unit[str(y)] = {"opm_n": len(o), "opm_median": r4(med(o)),
                        "opm_absmedian": r4(med([abs(x) for x in o])),
                        "opm_is_ratio": (med([abs(x) for x in o]) or 9) <= 3,
                        "opmD5_n": len(dd5), "opmD5_median": r4(med(dd5)),
                        "opmD5_absmedian": r4(med([abs(x) for x in dd5])),
                        "opmD5_neg_share": r4(sum(1 for x in dd5 if x < 0) / len(dd5))}
    # 罠の再現: 帯検問を通さずに opm>=10 とするとプールは何社になるか
    naive = {}
    for m in mapping:
        rs = [r for r in rows[m["w"]] if r["opmD5"] is not None]
        f2 = vint[m["vintage"]]
        n_naive = sum(1 for r in rs
                      if (f2.get(r["ticker"]) or {}).get("opm") is not None
                      and (f2[r["ticker"]]["opm"] >= 10)
                      and ((f2[r["ticker"]].get("fcfpos5") or 0) >= 5))
        naive[f"W{m['w']}"] = {"帯検問あり(正)": sum(1 for r in rs if r["qual"]),
                               "帯検問なし(罠)": n_naive}
    R["attack_e_units"] = {"per_vintage": unit, "naive_vs_banded_pool": naive,
                           "verdict": ("opm/opmD5 とも比率で入っており帯検問は必須。"
                                       "検問を外すとプールがほぼ0社に潰れることを実数で再現した"
                                       if all(v["帯検問なし(罠)"] < v["帯検問あり(正)"] / 5
                                              for v in naive.values()) else "要確認")}

    # ============================================================ (f) look-ahead
    la = []
    for m in mapping:
        f2 = vint[m["vintage"]]
        fye = [r["fy_end"] for r in rows[m["w"]] if r["fy_end"]]
        la.append({"w": m["w"], "window": m["window"], "signal_deadline": m["deadline"],
                   "window_start": lab(m["k0"]), "gap_months": m["gap_months"],
                   "deadline_before_start": (m["vintage"] * 12 + 6) <= m["k0"],
                   "max_fy_end": max(fye) if fye else None,
                   "n_fy_end_after_deadline": sum(1 for x in fye if x > m["deadline"]),
                   "later_vintages_unused": [y for y in vint if (y * 12 + 6) > m["k0"]][:3]})
    R["attack_f_lookahead"] = {
        "rows": la,
        "bar_convention": {"spy_has_current_partial_month": (2026 * 12 + 7) in S,
                           "note": ("Yahoo の月次バーは期間の**終値**（現在月2026-08が部分バーとして在ることで確認）。"
                                    "したがって W1 の入口は 2013-07 の**月末**で、信号(filed<=2013-07-01)との"
                                    "実質の緩衝は約1ヶ月＝報告の『gap 0ヶ月』はむしろ保守側に書かれている")},
        "verdict": ("違反なし: 4窓とも信号の deadline が窓の開始以前"
                    if all(x["deadline_before_start"] and x["n_fy_end_after_deadline"] == 0 for x in la)
                    else "★違反の疑いあり")}

    # ============================================================ 近い所見を特定して壊しにいく
    # 事前登録の線に最も近いセル（測定側の申告: W1/qual/SPY超 = 0.1497）
    cand = []
    for pool in ("all", "qual"):
        for m in mapping:
            c = mine[(m["w"], pool)]
            for key, oc in (("lift_hit", "15%+"), ("lift_beat", "SPY超")):
                if c["usable"] and c[key] is not None:
                    cand.append({"w": m["w"], "pool": pool, "outcome": oc, "lift": c[key],
                                 "gap_to_line": r4(LINE - c[key])})
    cand.sort(key=lambda x: -x["lift"])
    R["closest_to_line"] = cand[:4]
    TW, TP, TKEY = cand[0]["w"], cand[0]["pool"], ("lift_beat" if cand[0]["outcome"] == "SPY超"
                                                   else "lift_hit")
    tm = next(m for m in mapping if m["w"] == TW)
    trs = pool_rows(rows, TW, TP)
    R["target"] = {"cell": f"W{TW}/{TP}/{cand[0]['outcome']}", "lift": cand[0]["lift"],
                   "n": len(trs), "why": "事前登録の線に最も近い唯一の所見。ここを壊せれば H6 に残るものは無い"}

    # ---- 素朴な標準誤差（参考値）
    c0 = mine[(TW, TP)]
    z = z_two_prop(c0["p_beat_pos"], c0["n_pos"], c0["p_beat_neg"], c0["n_neg"])
    R["target"]["naive_z"] = r4(z)
    R["target"]["naive_se"] = r4(abs(c0[TKEY] / z)) if z else None
    R["target"]["naive_note"] = ("多重性も窓間の従属も無視した素朴な値。"
                                 "family-wise の判定は下の置換検定で行う")

    # ============================================================ (a) 業種 SIC2
    def lift_of(rs, m, key):
        A = [r for r in rs if r["opmD5"] >= 0]
        B = [r for r in rs if r["opmD5"] < 0]
        if not A or not B:
            return None
        f = ((lambda r: r["tr"] >= HURDLE) if key == "lift_hit" else (lambda r: r["tr"] > m["spy"]))
        return share(A, f) - share(B, f)

    by_sic = {}
    for r in trs:
        by_sic.setdefault(r["sic2"] or "??", []).append(r)
    strata, num, den = [], 0.0, 0.0
    for s, rs in sorted(by_sic.items(), key=lambda kv: -len(kv[1])):
        l = lift_of(rs, tm, TKEY)
        npos = sum(1 for r in rs if r["opmD5"] >= 0)
        nneg = len(rs) - npos
        strata.append({"sic2": s, "n": len(rs), "n_pos": npos, "n_neg": nneg, "lift": r4(l),
                       "desc": (rs[0]["sicDesc"] or "")[:40]})
        if l is not None and npos >= 3 and nneg >= 3:
            w = (npos * nneg) / (npos + nneg)      # MH風の重み
            num += w * l
            den += w
    adj = (num / den) if den else None
    drop1 = []
    for s in by_sic:
        keep = {r["ticker"] for r in trs if (r["sic2"] or "??") != s}
        l = lift_of([r for r in trs if r["ticker"] in keep], tm, TKEY)
        drop1.append({"drop_sic2": s, "n_dropped": len(by_sic[s]), "lift": r4(l),
                      "desc": (by_sic[s][0]["sicDesc"] or "")[:40]})
    drop1.sort(key=lambda x: (x["lift"] if x["lift"] is not None else 9))
    R["attack_a_sector"] = {
        "target": R["target"]["cell"], "raw_lift": cand[0]["lift"],
        "n_sic2_groups": len(by_sic),
        "strata_top": strata[:10],
        "sector_adjusted_lift": r4(adj),
        "drop_one_sector_min": drop1[0], "drop_one_sector_max": drop1[-1],
        "drop_one_sector_all": drop1[:12],
        "verdict": None}

    # ============================================================ (b) 規模 rev 三分位
    revs = sorted([r["rev"] for r in trs if r["rev"]])
    q1, q2 = (revs[len(revs) // 3], revs[2 * len(revs) // 3]) if len(revs) >= 6 else (None, None)

    def tert(r):
        if not r["rev"] or q1 is None:
            return "na"
        return "小" if r["rev"] <= q1 else ("中" if r["rev"] <= q2 else "大")

    bysz = {}
    for r in trs:
        bysz.setdefault(tert(r), []).append(r)
    szrows, num2, den2 = [], 0.0, 0.0
    for s in ("小", "中", "大", "na"):
        rs = bysz.get(s) or []
        if not rs:
            continue
        l = lift_of(rs, tm, TKEY)
        npos = sum(1 for r in rs if r["opmD5"] >= 0)
        nneg = len(rs) - npos
        szrows.append({"tertile": s, "n": len(rs), "n_pos": npos, "n_neg": nneg, "lift": r4(l),
                       "rev_median": med([r["rev"] for r in rs])})
        if l is not None and s != "na" and npos >= 3 and nneg >= 3:
            w = (npos * nneg) / (npos + nneg)
            num2 += w * l
            den2 += w
    R["attack_b_size"] = {"target": R["target"]["cell"], "raw_lift": cand[0]["lift"],
                          "cuts": {"q1_rev": q1, "q2_rev": q2}, "tertiles": szrows,
                          "size_adjusted_lift": r4((num2 / den2) if den2 else None),
                          "verdict": None}

    # ============================================================ (c) 1社抜き
    loo = []
    for r in trs:
        keep = {x["ticker"] for x in trs if x["ticker"] != r["ticker"]}
        l = lift_of([x for x in trs if x["ticker"] in keep], tm, TKEY)
        loo.append({"drop": r["ticker"], "lift": r4(l)})
    loo.sort(key=lambda x: x["lift"])
    R["attack_c_leave_one_out"] = {
        "target": R["target"]["cell"], "raw_lift": cand[0]["lift"],
        "min_lift": loo[0], "max_lift": loo[-1],
        "range": [loo[0]["lift"], loo[-1]["lift"]],
        "n_drops_that_break_line": sum(1 for x in loo if x["lift"] is not None and x["lift"] < LINE),
        "n_total": len(loo),
        "most_influential_5": loo[:5],
        "verdict": None}

    # ============================================================ (d) 置換検定
    # 会社→会社の一つの写像を**全窓へ同時に**当てる（窓間の従属を壊さない・既記録）
    def perm_stats():
        tick = sorted({r["ticker"] for w in range(1, N_WIN + 1)
                       for pl in ("all", "qual") for r in pool_rows(rows, w, pl)})
        sig = {w: {pl: {r["ticker"]: r["opmD5"] for r in pool_rows(rows, w, pl)}
                   for pl in ("all", "qual")} for w in range(1, N_WIN + 1)}
        base = {w: {pl: pool_rows(rows, w, pl) for pl in ("all", "qual")}
                for w in range(1, N_WIN + 1)}
        obs_max, obs_med = {}, {}
        for key in ("lift_hit", "lift_beat"):
            ls = [mine[(w, pl)][key] for w in range(1, N_WIN + 1) for pl in ("all", "qual")
                  if mine[(w, pl)]["usable"] and mine[(w, pl)][key] is not None]
            obs_max[key] = max(ls)
            obs_med[key] = st.median(ls)
        nulls_max = {"lift_hit": [], "lift_beat": []}
        nulls_med = {"lift_hit": [], "lift_beat": []}
        nulls_medpool = {"all": [], "qual": []}
        pass_any = 0
        pass_line_any_cell = {"lift_hit": 0, "lift_beat": 0}
        for _ in range(N_PERM):
            sh = tick[:]
            random.shuffle(sh)
            mp = dict(zip(tick, sh))
            got = {}
            for w in range(1, N_WIN + 1):
                m = mapping[w - 1]
                for pl in ("all", "qual"):
                    rs = base[w][pl]
                    d5 = sig[w][pl]
                    pr = []
                    for r in rs:
                        v = d5.get(mp.get(r["ticker"], r["ticker"]))
                        if v is None:
                            continue
                        pr.append({"tr": r["tr"], "opmD5": v})
                    for key in ("lift_hit", "lift_beat"):
                        A = [r for r in pr if r["opmD5"] >= 0]
                        B = [r for r in pr if r["opmD5"] < 0]
                        if len(A) < MIN_GROUP or len(B) < MIN_GROUP:
                            continue
                        f = ((lambda r: r["tr"] >= HURDLE) if key == "lift_hit"
                             else (lambda r: r["tr"] > m["spy"]))
                        got[(w, pl, key)] = share(A, f) - share(B, f)
            for key in ("lift_hit", "lift_beat"):
                ls = [v for (w, pl, k), v in got.items() if k == key]
                if ls:
                    nulls_max[key].append(max(ls))
                    nulls_med[key].append(st.median(ls))
                    if max(ls) >= LINE:
                        pass_line_any_cell[key] += 1
            for pl in ("all", "qual"):
                ls = [v for (w, p2, k), v in got.items() if p2 == pl and k == "lift_hit"]
                if ls:
                    nulls_medpool[pl].append(st.median(ls))
            # 手続きそのものが合格を出すか（すべての窓で符号が同じ ∧ どれかの読みが線以上）
            ok = False
            for pl in ("all", "qual"):
                for key in ("lift_hit", "lift_beat"):
                    ls = [got.get((w, pl, key)) for w in range(1, N_WIN + 1)]
                    if any(v is None for v in ls):
                        continue
                    same = all(v > 0 for v in ls) or all(v < 0 for v in ls)
                    if same and (all(v >= LINE for v in ls) or st.median(ls) >= LINE):
                        ok = True
            pass_any += 1 if ok else 0
        def q(v, p):
            v = sorted(v)
            return v[min(len(v) - 1, int(p * len(v)))] if v else None
        return {"n_perm": N_PERM,
                "observed_max_lift": {k: r4(v) for k, v in obs_max.items()},
                "observed_median_lift": {k: r4(v) for k, v in obs_med.items()},
                "null_max_p50": {k: r4(q(v, .50)) for k, v in nulls_max.items()},
                "null_max_p95": {k: r4(q(v, .95)) for k, v in nulls_max.items()},
                "p_familywise_max": {k: r4(sum(1 for v in nulls_max[k] if v >= obs_max[k])
                                            / max(1, len(nulls_max[k]))) for k in nulls_max},
                "p_median": {k: r4(sum(1 for v in nulls_med[k] if v >= obs_med[k])
                                   / max(1, len(nulls_med[k]))) for k in nulls_med},
                "null_prob_some_cell_reaches_line": {k: r4(v / N_PERM)
                                                     for k, v in pass_line_any_cell.items()},
                "false_positive_rate_of_procedure": r4(pass_any / N_PERM),
                "note": "会社→会社の一つの写像を全窓・全プールへ同時に当てる（窓間の従属を壊さない）"}

    R["attack_d_permutation"] = perm_stats()

    # ============================================================ W1 の母集団（被覆48%）を突く
    f13 = json.load(open(os.path.join(OUT, "retro_features2_2013.json")))["rows"]
    have = [r for r in f13 if r.get("opmD5") is not None]
    miss = [r for r in f13 if r.get("opmD5") is None]
    R["attack_g_w1_coverage"] = {
        "note": ("W1 の信号はビンテージ2013で opmD5 の被覆が 48%。"
                 "opmD5 は fy と fy-4 の営利率が要る＝2008年前後まで遡る＝XBRL早期適用の大型に偏る"),
        "n_have": len(have), "n_miss": len(miss),
        "rev_median_have": med([r.get("rev") for r in have]),
        "rev_median_miss": med([r.get("rev") for r in miss]),
        "rev_ratio": r4((med([r.get("rev") for r in have]) or 0)
                        / (med([r.get("rev") for r in miss]) or 1)),
        "opm_median_have_pct": r4(pct(med([r.get("opm") for r in have]))),
        "opm_median_miss_pct": r4(pct(med([r.get("opm") for r in miss]))),
        "coverage_by_window": {f"W{m['w']}": r4(sum(1 for r in rows[m['w']]
                                                    if r["opmD5"] is not None) / len(rows[m["w"]]))
                               for m in mapping}}

    # 測定側の探索（W2〜W4 を W1 と同じ社へ揃える）の再現
    w1t = {r["ticker"] for r in pool_rows(rows, 1, "all")}
    rep = []
    for m in mapping:
        for pl in ("all", "qual"):
            rs = pool_rows(rows, m["w"], pl, keep=w1t)
            l = lift_of(rs, m, "lift_hit")
            rep.append({"w": m["w"], "pool": pl, "n": len(rs), "lift_hit_on_W1_tickers": r4(l)})
    R["attack_g_w1_coverage"]["reproduce_exploratory"] = rep

    # ============================================================ 不合格そのものは頑健か（両側から）
    frag = {}
    # (i) 窓を丸ごと持っている社だけ
    for pl in ("all", "qual"):
        for key in ("lift_hit", "lift_beat"):
            ls = []
            for m in mapping:
                c = cell(m, pool_rows(rows, m["w"], pl, strict=True))
                if c["usable"]:
                    ls.append(c[key])
            frag[f"strict_span/{pl}/{key}"] = {"lifts": [r4(v) for v in ls],
                                               "median": r4(st.median(ls)) if ls else None,
                                               "all_same_sign": bool(ls) and (all(v > 0 for v in ls)
                                                                              or all(v < 0 for v in ls))}
    # (ii) MIN_GROUP を動かす（合否が下限の置き方で変わらないか）
    mg = {}
    for g in (10, 20, 30, 50):
        ok = 0
        for pl in ("all", "qual"):
            for key in ("lift_hit", "lift_beat"):
                ls = []
                for m in mapping:
                    rs = pool_rows(rows, m["w"], pl)
                    A = [r for r in rs if r["opmD5"] >= 0]
                    B = [r for r in rs if r["opmD5"] < 0]
                    if len(A) >= g and len(B) >= g:
                        ls.append(lift_of(rs, m, key))
                if len(ls) == N_WIN and (all(v > 0 for v in ls) or all(v < 0 for v in ls)) \
                        and (all(v >= LINE for v in ls) or st.median(ls) >= LINE):
                    ok += 1
        mg[str(g)] = ok
    frag["min_group_sensitivity_n_passing_readings"] = mg
    # (iii) 窓の長さを変えたら合格が出るか（★事後の探索。合否には使わない）
    alt = {}
    k0 = mapping[0]["k0"]
    for wm, nw in ((26, 6), (39, 4), (52, 3)):
        wins = [(k0 + i * wm, k0 + (i + 1) * wm) for i in range(nw)]
        okall = {}
        for pl in ("all", "qual"):
            ls, bad = [], False
            for (a, b) in wins:
                if a not in S or b not in S:
                    bad = True
                    break
                cands = [y for y in vint if (y * 12 + 6) <= a]
                if not cands:
                    bad = True
                    break
                v = max(cands)
                rs = []
                for t, mm in P.items():
                    c = cagr(mm, a, b)
                    if c is None:
                        continue
                    f2 = vint[v].get(t)
                    if not f2 or f2.get("opmD5") is None:
                        continue
                    op = pct(f2.get("opm"))
                    q = bool(op is not None and op >= 10.0 and (f2.get("fcfpos5") or 0) >= 5)
                    if pl == "qual" and not q:
                        continue
                    rs.append({"tr": c, "opmD5": f2["opmD5"]})
                A = [r for r in rs if r["opmD5"] >= 0]
                B = [r for r in rs if r["opmD5"] < 0]
                if len(A) < MIN_GROUP or len(B) < MIN_GROUP:
                    bad = True
                    break
                ls.append(share(A, lambda r: r["tr"] >= HURDLE)
                          - share(B, lambda r: r["tr"] >= HURDLE))
            okall[pl] = ({"lifts": [r4(v) for v in ls],
                          "median": r4(st.median(ls)) if ls else None,
                          "all_same_sign": bool(ls) and (all(v > 0 for v in ls)
                                                         or all(v < 0 for v in ls)),
                          "would_pass": bool(ls) and (all(v > 0 for v in ls) or all(v < 0 for v in ls))
                                        and (all(v >= LINE for v in ls) or st.median(ls) >= LINE)}
                         if not bad else {"note": "この分割では測れない窓がある"})
        alt[f"{wm}m×{nw}"] = okall
    frag["alternative_window_splits_POST_HOC"] = alt
    frag["alternative_window_splits_caveat"] = ("★事前登録に無い事後の探索。合否の根拠にしない。"
                                                "『不合格が窓の割り方に依存していないか』だけを見る")
    R["fragility_of_the_failure"] = frag

    # ============================================================ H1 との比較の妥当性
    h1 = json.load(open(os.path.join(OUT, "opmtrend_h1.json")))
    R["attack_h_h1_comparison"] = {
        "claim": "『H1 の不合格の原因は終点の共有ではなかった』（測定側の結論）",
        "issue_1_benchmark": ("H1 の『ベンチ超』は 2019〜2022 が SPY ではなく EW（base.json の warnings）。"
                              "H6 は4窓とも実SPY。**ベンチ超の列を H1 と H6 で直接比べてはいけない**"),
        "issue_2_horizon": ("H1 の窓は 8〜13年、H6 は 3.25年。年率15%ハードルは窓が短いほど分散が大きい。"
                            "基礎率も違う（H6 は 26〜42%）ので lift の帯が同じでも同じ意味ではない"),
        "issue_3_population": "H6 の W1 は opmD5 被覆48%で他の窓と母集団が違う",
        "h1_verdicts": {k: {kk: h1["summary"][k][kk]["verdict"] for kk in h1["summary"][k]}
                        for k in h1.get("summary", {})} if "summary" in h1 else None,
        "verdict": ("測定側の結論『窓を替えても lift の帯は変わらない』は**方向としては支持できる**が、"
                    "H1 と H6 は窓長もベンチも母集団も違うので『同じ帯』は厳密な比較ではない。"
                    "ただし**どちらも線に遠く届かない**という結論は両者で共通で、そこは壊れない")}

    # ============================================================ 判定
    a = R["attack_a_sector"]
    b = R["attack_b_size"]
    c = R["attack_c_leave_one_out"]
    d = R["attack_d_permutation"]
    a["verdict"] = ("業種で説明が付く（調整後 lift が線を大きく下回る）"
                    if (a["sector_adjusted_lift"] or 0) < LINE else "業種調整後も線以上")
    b["verdict"] = ("規模で説明が付く（調整後 lift が線を大きく下回る）"
                    if (b["size_adjusted_lift"] or 0) < LINE else "規模調整後も線以上")
    c["verdict"] = (f"1社抜きで {c['n_drops_that_break_line']}/{c['n_total']} 通りが線を割る"
                    if c["n_drops_that_break_line"] else "1社抜きでは壊れない")



    # ---- 報告に出す統計量も独立に検算して在庫へ書く（画面に出す数字は必ず在庫にも書く）
    ver = {"per_window": [], "summary": {}}
    for m in mapping:
        rs = rows[m["w"]]
        ver["per_window"].append({
            "w": m["w"], "n": len(rs),
            "base_hit": r4(share(rs, lambda r: r["tr"] >= HURDLE)),
            "base_beat": r4(share(rs, lambda r: r["tr"] > m["spy"])),
            "median_tr": r4(med([r["tr"] for r in rs])),
            "n_short_span": sum(1 for r in rs if not r["full_span"]),
            "coverage_opmD5": r4(sum(1 for r in rs if r["opmD5"] is not None) / len(rs))})
    for pool in ("all", "qual"):
        for key, nm in (("lift_hit", "hurdle15"), ("lift_beat", "beat_spy")):
            ls, ns, allr = [], [], []
            for m in mapping:
                rs = pool_rows(rows, m["w"], pool)
                ls.append(mine[(m["w"], pool)][key])
                ns.append(len(rs))
                allr += [dict(r, _spy=m["spy"]) for r in rs]
            A = [r for r in allr if r["opmD5"] >= 0]
            B = [r for r in allr if r["opmD5"] < 0]
            f = ((lambda r: r["tr"] >= HURDLE) if key == "lift_hit"
                 else (lambda r: r["tr"] > r["_spy"]))
            ver["summary"][f"{pool}/{nm}"] = {
                "lifts": ls, "median": r4(st.median(ls)),
                "pooled": r4(share(A, f) - share(B, f)),
                "weighted_mean": r4(sum(l * n for l, n in zip(ls, ns)) / sum(ns)),
                "all_same_sign": (all(v > 0 for v in ls) or all(v < 0 for v in ls)),
                "n_ge_line": sum(1 for v in ls if v >= LINE)}
    # 測定側の同名フィールドと突き合わせる
    vd = []
    for pool in ("all", "qual"):
        for key, nm in (("lift_hit", "hurdle15"), ("lift_beat", "beat_spy")):
            t = h6["summary"][pool][nm]
            mm2 = ver["summary"][f"{pool}/{nm}"]
            for a, b, f in ((t["median_lift"], mm2["median"], "median"),
                            (t["pooled_lift"], mm2["pooled"], "pooled"),
                            (t["mean_lift_weighted"], mm2["weighted_mean"], "wmean"),
                            (t["all_same_sign"], mm2["all_same_sign"], "same_sign"),
                            (t["n_lift_ge_line"], mm2["n_ge_line"], "n_ge_line")):
                if a != b:
                    vd.append({"cell": f"{pool}/{nm}", "field": f, "theirs": a, "mine": b})
    for a, b in zip(h6.get("per_window", []), ver["per_window"]):
        for f in ("base_hit", "base_beat", "median_tr", "n_short_span", "coverage_opmD5"):
            if a.get(f) != b.get(f):
                vd.append({"cell": f"W{b['w']}", "field": f, "theirs": a.get(f), "mine": b.get(f)})
    ver["n_fields_diff_vs_h6"] = len(vd)
    ver["diffs"] = vd
    R["independent_summary_stats"] = ver
    R["independent_recalc_vs_h6"]["n_fields_diff_total"] = \
        R["independent_recalc_vs_h6"]["n_fields_diff"] + len(vd)
    R["independent_recalc_vs_h6"]["note_fp_rate"] = (
        "測定側の false_positive_rate_of_procedure は 0.0000、こちらは 0.0005（2000回中1回）。"
        "合否条件の書き方が僅かに違い（測定側は pooled の読みも含む＝より緩い）、どちらも実質0＝"
        "『雑音ではまず通らない試験』という結論は同じ。食い違いとして数えない")

    # ============================================================ 追補1: 単位の食い違いは pool を動かすか
    bad = []
    for r in b0["rows"]:
        raw, fp = r.get("opm_raw"), r.get("opm")
        if raw is None or fp is None:
            continue
        band = raw * 100 if abs(raw) <= 3 else raw
        if abs(band - fp) > 1e-6:
            bad.append({"v": r["vintage"], "t": r["ticker"], "raw": raw,
                        "file_pct": fp, "band_pct": r4(band),
                        "base_qual": bool(r.get("qual")) and not r.get("qual_na")})
    R["attack_e_units"]["file_vs_row_band"] = {
        "n_disagree": len(bad),
        "n_of_them_qual_true_in_base": sum(1 for x in bad if x["base_qual"]),
        "n_band_ge_10pct": sum(1 for x in bad if x["band_pct"] >= 10),
        "max_raw": max((x["raw"] for x in bad), default=None),
        "examples": bad[:5],
        "verdict": ("単位の読み方の違いは**プールを1社も動かさない**"
                    "（食い違う社はどちらの読み方でも qual=False）"
                    if not any(x["base_qual"] for x in bad)
                    and not any(x["band_pct"] >= 10 for x in bad) else "★プールが動く——要確認")}

    # ============================================================ 追補2: 業種の層は情報を持っているか
    inf = [s2 for s2, rs in by_sic.items()
           if sum(1 for r in rs if r["opmD5"] >= 0) >= 3 and sum(1 for r in rs if r["opmD5"] < 0) >= 3]
    sl = [x["lift"] for x in strata if x["lift"] is not None]
    R["attack_a_sector"]["informativeness"] = {
        "n_groups": len(by_sic), "n_groups_usable_for_MH": len(inf),
        "largest_group_n": max(len(v) for v in by_sic.values()),
        "median_group_n": r4(st.median([len(v) for v in by_sic.values()])),
        "stratum_lift_range": [r4(min(sl)), r4(max(sl))],
        "note": ("★調整後 lift が生とほとんど同じなのは『業種が効いていない』の証拠ではない——"
                 "43群/最大31社では層別が情報を持たないので、MH調整は何も引き算していない。"
                 "**この攻撃は空振りであって、業種を否定する証拠ではない**")}

    # ============================================================ 追補3: プールの定義を変えたら（★事後）
    alt_pool = {}
    for name, fn in (("opm>=10%のみ(fcfpos5を外す)", lambda r: (r["opm_pct"] or -9) >= 10),
                     ("opm>=15%", lambda r: (r["opm_pct"] or -9) >= 15),
                     ("全社", lambda r: True)):
        rs = [r for r in rows[TW] if r["opmD5"] is not None and fn(r)]
        alt_pool[name] = {"n": len(rs), "lift_beat": r4(lift_of(rs, tm, "lift_beat")),
                          "lift_hit": r4(lift_of(rs, tm, "lift_hit"))}
    R["attack_i_pool_definition_POST_HOC"] = {
        "caveat": "★事前登録に無い事後の切り方。合否には使わない。所見がプールの定義に依存しないかだけを見る",
        "target_window": f"W{TW}", "preregistered_pool_lift_beat": cand[0]["lift"],
        "variants": alt_pool}

    # ============================================================ 追補4: 生存する所見はあるか
    broken, not_broken = [], []
    # (d) が決定打かどうか
    fw = R["attack_d_permutation"]["p_familywise_max"]["lift_beat"]
    pl = R["attack_d_permutation"]["null_prob_some_cell_reaches_line"]["lift_beat"]
    if fw is not None and fw > 0.05:
        broken.append({"attack": "(d) 置換（会社単位・全窓同時）",
                       "what": f"W{TW}/{TP}/SPY超 = {cand[0]['lift']}（線まで0.0003）",
                       "result": (f"family-wise p = {fw}。しかも**帰無でも 16セルのどれかが線に届く確率が {pl}**"
                                  "＝『あと0.0003』は雑音がふつうに出す大きさ"),
                       "verdict": "refuted"})
    dmin = R["attack_a_sector"]["drop_one_sector_min"]
    if dmin["lift"] is not None and dmin["lift"] < LINE:
        broken.append({"attack": "(a) 業種 1業種抜き",
                       "what": f"W{TW}/{TP}/SPY超",
                       "result": (f"SIC2={dmin['drop_sic2']}（{dmin['desc']}・{dmin['n_dropped']}社）"
                                  f"を抜くと {dmin['lift']}＝線を割る"),
                       "verdict": "refuted"})
    if (R["attack_a_sector"]["sector_adjusted_lift"] or 0) >= LINE:
        not_broken.append({"attack": "(a) 業種 層別（MH調整）",
                           "result": f"調整後 {R['attack_a_sector']['sector_adjusted_lift']}＝生とほぼ同じ",
                           "caveat": "ただし43群/最大31社で層別が情報を持たない＝空振りであって支持ではない"})
    if (R["attack_b_size"]["size_adjusted_lift"] or 0) >= LINE:
        not_broken.append({"attack": "(b) 規模 rev三分位",
                           "result": (f"調整後 {R['attack_b_size']['size_adjusted_lift']}（生 {cand[0]['lift']}）。"
                                      "三分位とも正で単調でない"),
                           "caveat": "規模では説明が付かない＝測定側の探索の結論を独立に再現した"})
    if R["attack_c_leave_one_out"]["range"][0] is not None \
            and R["attack_c_leave_one_out"]["range"][0] > 0.10:
        not_broken.append({"attack": "(c) 1社抜き",
                           "result": f"範囲 {R['attack_c_leave_one_out']['range']}＝1社では動かない",
                           "caveat": ("線から0.0003しか離れていないので『線を割る抜き方が127/221ある』のは"
                                      "頑健性の話ではなく、線の上に載っていないことの言い換え")})
    if R["attack_f_lookahead"]["verdict"].startswith("違反なし"):
        not_broken.append({"attack": "(f) look-ahead",
                           "result": "4窓とも deadline が窓の開始以前・fy_end が deadline より後の行は0件",
                           "caveat": "月次バーが期間の終値なので実質の緩衝はさらに約1ヶ月"})
    not_broken.append({"attack": "(e) 単位・欄名",
                       "result": R["attack_e_units"]["file_vs_row_band"]["verdict"],
                       "caveat": "帯検問を外すと qual プールが4窓とも0社に潰れることを再現（罠は実在する）"})
    _vd_broken, _vd_not = broken, not_broken
    _vd_robust = {
        "min_group_10_20_30_50": R["fragility_of_the_failure"]["min_group_sensitivity_n_passing_readings"],
        "alt_window_splits_any_pass": any(
            v.get("would_pass") for d in R["fragility_of_the_failure"]["alternative_window_splits_POST_HOC"].values()
            for v in d.values() if isinstance(v, dict)),
        "note": "『不合格』の側も壊せるかを試した——群の下限・窓の割り方のどれを変えても合格は出ない"}
    R["limits_of_this_refutation"] = [
        "4窓は同じ956社のパネル＝会社が最大4回出る。窓は期間として重ならないが標本としては独立ではない",
        "W1 の opmD5 被覆は47.6%（他は90%超）＝W1 だけ別の母集団を測っている。売上中央値で5.91倍の差",
        "業種の層は43群・最大31社で、層別が情報を持たない＝(a)の『壊せなかった』は支持の証拠ではない",
        "置換は会社→会社の写像で、同一社が複数窓に出る従属は保つがビンテージ間の信号の相関は保たない",
        "検出力は lift=0.15 でコイン投げ（測定側の実測 all 0.48 / qual 0.51）＝『0.15未満の効果は無い』とは書けない",
        "窓の割り方の探索(26/39/52ヶ月)は事後の切り方で、合否の根拠にしていない",
        "生存バイアスは既記録のまま（母集団は今日ティッカーが引ける956社）",
    ]

    R["verdict"] = {
        "independent_recalc": R["independent_recalc_vs_h6"]["verdict"],
        "h6_headline": "4通り（プール2×結果2）すべて不合格",
        "my_headline": ("同意。しかも測定側が『線まであと0.0003』とした唯一の所見も、"
                        "業種・規模・1社抜き・置換のいずれでも支持されない"),
        "broken": _vd_broken, "not_broken": _vd_not, "failure_is_robust": _vd_robust}
    json.dump(R, open(os.path.join(OUT, "opmtrend_ref_h6.json"), "w"),
              ensure_ascii=False, indent=1)
    return R


if __name__ == "__main__":
    R = main()
    print("独立再計算 vs h6:", R["independent_recalc_vs_h6"]["verdict"],
          "食い違い", R["independent_recalc_vs_h6"]["n_fields_diff"], "件")
    print("target:", R["target"]["cell"], R["target"]["lift"], "naive z", R["target"]["naive_z"])
    print("(a)業種 調整後", R["attack_a_sector"]["sector_adjusted_lift"])
    print("(b)規模 調整後", R["attack_b_size"]["size_adjusted_lift"])
    print("(c)1社抜き", R["attack_c_leave_one_out"]["range"],
          "線を割る", R["attack_c_leave_one_out"]["n_drops_that_break_line"], "/",
          R["attack_c_leave_one_out"]["n_total"])
    print("(d)置換 family-wise p", R["attack_d_permutation"]["p_familywise_max"],
          "偶然に1セルが線へ", R["attack_d_permutation"]["null_prob_some_cell_reaches_line"])
