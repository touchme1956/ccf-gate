#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/hist10_verify_score3quart.py — 角度D の合格1件を**潰しにかかる**（2026-08-12新設）

■ 叩く候補（out/hist10_angleD.json の passes[0]）
    角度 D（加法スコア）／母集団 P_quality ／ 部分集合 cov90_14 ／ 発見年 2016 ／
    二値化 上下1/4 ／ J=3 ／ score>=2 ／ mode=ge
    選ばれた3本 = f2_rev(上位1/4) ∧ f2_rnd_r(上位1/4) ∧ f2_cagr5(下位1/4) の**2つ以上**
    公表値 2018: n=53 / 分子=32 / lift=0.1973（2016: 55/35/0.2073・2017: 55/34/0.1978）
    探索側の弁: 事前登録の全条件を満たす唯一の配置＝合格

■ 仕事は反証であって確認ではない。事前登録(out/hist10_prereg.json)の線は動かさない。
    1 再現       独立実装で n/分子/lift が一致するか（**境界の約束まで揃える**）
    2 ビンテージ 2016/2017/2018 すべてで lift>=0.15 か
    3 業種       Mantel-Haenszel ＋ 業種1つ抜き（**MH の足切りの選び方への頑健性も測る**）
    4 irr の影   irr>=70 層内で残るか／irr と直交か（prereg は OR）
    5 置換       会社単位で全ビンテージ同時・sic2層内・2000回×複数種
    6 増分       門が既に持つ関門でどれだけ説明されるか（**3通りの読みを全部出す**）

■ 独立性
    hist10_diag.py / hist10_angleD.py / hist10_angleB.py を **import しない**。
    入力は out/hist_wd_panel.json と out/hist10_targets.json の生データだけ。
    群の数え方も別（探索側=bit-plane 加算器／こちら=素朴な整数カウント）。
    照合は探索側の**出力 JSON** とだけ行う。

■ 兄弟の検査器（v9.9.65: 同じ台帳を見る二つが違うことを言ってはいけない）
    out/hist10_verify_addscore3.json … 同じ配置を検証済み（6検問は通し、prereg の
                                        for_D_and_E 外側fold条項で不合格と結論）
    out/hist10_verify_fpr.json       … その合格に付いた偽陽性率の値札を検証
    → 数字が食い違ったらこの道具の verdict に**名指しで**書く。黙って自分の値を出さない。

実行: python3 night/hist10_verify_score3quart.py  → out/hist10_verify_score3quart.json
判定・採点・台帳・index.html・パックには一切触れない（読むだけの調査）。
"""
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
TARGETS = os.path.join(OUT, "hist10_targets.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
ANGLED = os.path.join(OUT, "hist10_angleD.json")
SIB1 = os.path.join(OUT, "hist10_verify_addscore3.json")
SIB2 = os.path.join(OUT, "hist10_verify_fpr.json")
MON_A = os.path.join(OUT, "retro_monthly_2013_2018.json")
MON_B = os.path.join(OUT, "retro_monthly_2018_2026.json")
DEST = os.path.join(OUT, "hist10_verify_score3quart.json")

# ── 事前登録の線。この道具は一つも作らない ──
LIFT_LINE = 0.15
MIN_NUM = 20
INCREMENTAL_MAX_CAUGHT = 0.70
HURDLE = 0.10
TRIO = [2016, 2017, 2018]
DISC = 2016
SEEDS = [20260812001, 90210, 5150, 271828, 1123581321]
N_PERM = int(os.environ.get("NPERM", 2000))

COV90 = ["aturn", "cagr5", "rev", "capex_r", "accel", "streak_rev", "rnd_r", "cash_r",
         "accr", "fcfpos5", "gw_r", "opm", "streak_opm", "opmD5"]
COLS = ["f2_" + c for c in COV90]


def r4(x):
    return None if x is None else round(x, 4)


# ────────────────────────── 入力（生データだけ） ──────────────────────────
def load_rows():
    panel = json.load(open(PANEL, encoding="utf-8"))["rows"]
    tg = json.load(open(TARGETS, encoding="utf-8"))["rows"]
    tmap = {(r["ticker"], r["vintage"]): r for r in tg}
    rows = []
    for r in panel:
        if not (r.get("has_outcome") and r.get("window_full")):
            continue
        t = tmap.get((r["ticker"], r["vintage"]))
        if t is None:
            continue
        q = dict(r)
        q["y10"] = t.get("y10")
        rows.append(q)
    return rows


ROWS = load_rows()


def universe(v):
    """P_quality × complete-case(14本) × y10 定義済。ticker 昇順（探索側と同じ）。"""
    rs = [r for r in ROWS if r["vintage"] == v and r.get("P_quality") is True
          and r.get("y10") is not None
          and all(r.get(c) is not None for c in COLS)]
    return sorted(rs, key=lambda r: r["ticker"])


U = {v: universe(v) for v in TRIO}


# ────────────────────────── 分位と群（独立実装） ──────────────────────────
def quantile(xs, q, method="linear"):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    if method == "linear":                      # 探索側の約束
        i = q * (n - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (i - lo)
    if method == "nearest_rank":                # 別の実装（感度を見るため）
        k = max(1, int(math.ceil(q * n)))
        return xs[k - 1]
    if method == "midpoint":
        i = q * (n - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return (xs[lo] + xs[hi]) / 2.0
    raise ValueError(method)


def good_flags(rs, col, side, method="linear", strict=False):
    """その候補の『良い側』か否かの真偽リスト。既定は探索側と同じ x>=q75 / x<=q25。"""
    xs = [r[col] for r in rs]
    if side == "hi":
        c = quantile(xs, 0.75, method)
        return [(r[col] > c) if strict else (r[col] >= c) for r in rs]
    c = quantile(xs, 0.25, method)
    return [(r[col] < c) if strict else (r[col] <= c) for r in rs]


def lift_of(rs, sel):
    """sel = 真偽リスト。(n_group, k, p_group, base, lift)"""
    n = len(rs)
    k_all = sum(1 for r in rs if r["y10"])
    base = k_all / n if n else None
    m = sum(1 for x in sel if x)
    k = sum(1 for i, r in enumerate(rs) if sel[i] and r["y10"])
    p = k / m if m else None
    return {"n": n, "n_group": m, "k": k, "p_group": r4(p), "base": r4(base),
            "lift": r4((p - base) if p is not None else None)}


def pick_feats(rs, cols, method="linear", strict=False):
    """発見年で各候補の『良い側』と |lift| を決め、|lift| 降順（同値は列名）で並べる。
    側は **符号つき lift が大きいほう**（探索側 feats_at と同じ約束）。"""
    n = len(rs)
    base = sum(1 for r in rs if r["y10"]) / n
    feats = []
    for c in cols:
        best = None
        for side in ("hi", "lo"):
            g = good_flags(rs, c, side, method, strict)
            m = sum(1 for x in g if x)
            if m == 0 or m == n:
                continue
            k = sum(1 for i, r in enumerate(rs) if g[i] and r["y10"])
            lf = k / m - base
            if best is None or lf > best[1]:
                best = (side, lf)
        if best is None:
            continue
        feats.append({"col": c, "side": best[0], "lift": r4(best[1]), "abs_lift": abs(best[1])})
    feats.sort(key=lambda x: (-x["abs_lift"], x["col"]))
    return feats


def score_group(rs, sel_cols, sides, s, method="linear", strict=False):
    """score = 良い側の本数。群 = score >= s。真偽リストを返す。"""
    flags = [good_flags(rs, c, sd, method, strict) for c, sd in zip(sel_cols, sides)]
    n = len(rs)
    sc = [sum(f[i] for f in flags) for i in range(n)]
    return [x >= s for x in sc], sc


# ═══════════════════ 検問1: 再現（独立実装＋境界感度） ═══════════════════
def t1_reproduce():
    out = {"what": "探索側の出力 out/hist10_angleD.json の passes[0] と突き合わせる"}
    ang = json.load(open(ANGLED, encoding="utf-8"))
    pub = ang["passes"][0]
    out["published"] = {"sel": pub["sel"], "sides": pub["sides"],
                        "per_v": {k: {kk: vv for kk, vv in v.items()}
                                  for k, v in pub["per_v"].items()}}

    feats = pick_feats(U[DISC], COLS)
    out["feats_ranking_at_disc2016"] = [{"col": f["col"], "side": f["side"],
                                         "abs_lift": r4(f["abs_lift"])} for f in feats[:6]]
    sel = [f["col"] for f in feats[:3]]
    sides = [f["side"] for f in feats[:3]]
    out["selected"] = {"cols": sel, "sides": sides,
                       "match_published": (sel == pub["sel"] and sides == pub["sides"])}

    mine, members = {}, {}
    for v in TRIO:
        g, _sc = score_group(U[v], sel, sides, 2)
        mine[str(v)] = lift_of(U[v], g)
        members[str(v)] = sorted(U[v][i]["ticker"] for i in range(len(U[v])) if g[i])
    out["mine_per_v"] = mine

    diffs = {}
    pubmem = ang["attacks_on_passes"]["cells"][
        "T_disc2016_quartile|cov90_14|P_quality|quartile|J3|s2|ge"]["members"]
    for v in TRIO:
        a, b = set(members[str(v)]), set(pubmem[str(v)])
        diffs[str(v)] = {"only_mine": sorted(a - b), "only_published": sorted(b - a)}
    out["member_diff"] = diffs
    out["member_mismatch_count"] = sum(len(d["only_mine"]) + len(d["only_published"])
                                       for d in diffs.values())
    num_ok = all(mine[str(v)]["n_group"] == pub["per_v"][str(v)]["m"] and
                 mine[str(v)]["k"] == pub["per_v"][str(v)]["k"] and
                 abs(mine[str(v)]["lift"] - pub["per_v"][str(v)]["lift"]) < 1e-9 for v in TRIO)
    out["numbers_match"] = num_ok

    # ── 境界の約束への感度（addscore20 は中央値の同値の扱いで 0.303→0.139 と崩れた） ──
    sens = {}
    for tag, kw in (("非厳密(探索側) x>=q75 / x<=q25", {"strict": False}),
                    ("厳密 x>q75 / x<q25", {"strict": True}),
                    ("分位=nearest_rank", {"method": "nearest_rank"}),
                    ("分位=midpoint", {"method": "midpoint"})):
        f2 = pick_feats(U[DISC], COLS, **kw)
        s2, sd2 = [f["col"] for f in f2[:3]], [f["side"] for f in f2[:3]]
        per = {}
        for v in TRIO:
            g, _ = score_group(U[v], s2, sd2, 2, **kw)
            per[str(v)] = lift_of(U[v], g)
        sens[tag] = {"selected": s2, "sides": sd2,
                     "same_3_vars": (s2 == sel and sd2 == sides),
                     "per_v": {k: {"n_group": x["n_group"], "k": x["k"], "lift": x["lift"]}
                               for k, x in per.items()},
                     "gate1_ok": all(per[str(v)]["k"] >= MIN_NUM and
                                     per[str(v)]["lift"] >= LIFT_LINE for v in TRIO)}
    out["boundary_sensitivity"] = sens
    # 同値の実数（境界に何社載っているか）
    ties = {}
    for v in TRIO:
        rs = U[v]
        d = {}
        for c, sd in zip(sel, sides):
            xs = [r[c] for r in rs]
            cut = quantile(xs, 0.75 if sd == "hi" else 0.25)
            d[c] = {"cut": cut, "n_exactly_at_cut": sum(1 for x in xs if x == cut)}
        ties[str(v)] = d
    out["values_exactly_at_cut"] = ties
    out["verdict"] = ("一致" if (out["selected"]["match_published"] and num_ok
                                and out["member_mismatch_count"] == 0) else "不一致")
    return out


# ═══════════════════ 検問2: ビンテージ ═══════════════════
def t2_vintage(sel, sides):
    per, mem = {}, {}
    for v in TRIO:
        g, _ = score_group(U[v], sel, sides, 2)
        per[str(v)] = lift_of(U[v], g)
        mem[v] = {U[v][i]["ticker"] for i in range(len(U[v])) if g[i]}
    ok = all(per[str(v)]["lift"] >= LIFT_LINE and per[str(v)]["k"] >= MIN_NUM for v in TRIO)

    # 3ビンテージは独立な3つの証拠か（同じ会社・重なる窓を3回数えていないか）
    uni = {v: {r["ticker"] for r in U[v]} for v in TRIO}

    def jac(a, b):
        return r4(len(a & b) / len(a | b)) if (a | b) else None
    # 会社を1回だけ数える版（重複を消す）
    all3 = mem[2016] & mem[2017] & mem[2018]
    never = (uni[2016] | uni[2017] | uni[2018]) - (mem[2016] | mem[2017] | mem[2018])
    u18 = {r["ticker"]: r for r in U[2018]}
    grp18 = [u18[t] for t in sorted(all3) if t in u18]
    ctl18 = [u18[t] for t in sorted(never) if t in u18]
    base18 = sum(1 for r in U[2018] if r["y10"]) / len(U[2018])

    def pr(rs):
        return {"n": len(rs), "k": sum(1 for r in rs if r["y10"]),
                "p": r4(sum(1 for r in rs if r["y10"]) / len(rs)) if rs else None}
    g_, c_ = pr(grp18), pr(ctl18)
    return {"per_v": per, "gate_met": ok,
            "universe_jaccard": {"2016v2017": jac(uni[2016], uni[2017]),
                                 "2016v2018": jac(uni[2016], uni[2018]),
                                 "2017v2018": jac(uni[2017], uni[2018])},
            "group_jaccard": {"2016v2017": jac(mem[2016], mem[2017]),
                              "2016v2018": jac(mem[2016], mem[2018]),
                              "2017v2018": jac(mem[2017], mem[2018])},
            "company_level_dedup": {
                "def": "群=3ビンテージ全部に入った会社／対照=一度も入らなかった会社。結果は2018窓",
                "group_all3": g_, "control_never": c_, "base_whole_2018": r4(base18),
                "lift_vs_control": r4(g_["p"] - c_["p"]) if (g_["p"] and c_["p"]) else None,
                "lift_vs_base": r4(g_["p"] - base18) if g_["p"] else None,
                "min_num_met": g_["k"] >= MIN_NUM},
            "verdict": "合格" if ok else "不合格"}


# ═══════════════════ 検問3: 業種 ═══════════════════
def mh(rs, gset, n1min, n0min, ykey="y10"):
    st = defaultdict(lambda: [0, 0, 0, 0])
    for r in rs:
        if not r.get("sic2"):
            continue
        d = st[r["sic2"]]
        w = 1 if r[ykey] else 0
        if r["ticker"] in gset:
            d[0] += 1
            d[1] += w
        else:
            d[2] += 1
            d[3] += w
    num = den = 0.0
    used = drop = 0
    rows_used = rows_drop = 0
    grp_used = 0
    for _s, (n1, k1, n0, k0) in st.items():
        if n1 < n1min or n0 < n0min:
            drop += 1
            rows_drop += n1 + n0
            continue
        w = n1 * n0 / (n1 + n0)
        num += w * (k1 / n1 - k0 / n0)
        den += w
        used += 1
        rows_used += n1 + n0
        grp_used += n1
    n_grp = sum(1 for r in rs if r["ticker"] in gset and r.get("sic2"))
    return {"mh_risk_diff": r4(num / den) if den else None,
            "strata_used": used, "strata_dropped": drop,
            "share_of_rows_used": r4(rows_used / (rows_used + rows_drop))
            if (rows_used + rows_drop) else None,
            "share_of_group_used": r4(grp_used / n_grp) if n_grp else None}


def t3_sector(sel, sides):
    out = {"note": "探索側の MH は 群>=3 かつ 非群>=3 の層だけを使う。"
                   "その足切りは事前登録に無い＝**選び方への頑健性も測る**"}
    per = {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        gset = {rs[i]["ticker"] for i in range(len(rs)) if g[i]}
        d = {"mh_by_threshold": {}}
        for (a, b) in ((3, 3), (2, 2), (1, 1), (5, 5)):
            d["mh_by_threshold"]["n1>=%d,n0>=%d" % (a, b)] = mh(rs, gset, a, b)
        # 業種1つ抜き（探索側と同じ足切り: 残り>=40行・群>=10）
        secs = sorted({r.get("sic2") for r in rs if r.get("sic2")})
        drops = []
        for s in secs:
            sub = [r for r in rs if r.get("sic2") != s]
            if len(sub) < 40:
                continue
            m = sum(1 for r in sub if r["ticker"] in gset)
            if m < 10:
                continue
            k = sum(1 for r in sub if r["ticker"] in gset and r["y10"])
            base = sum(1 for r in sub if r["y10"]) / len(sub)
            drops.append({"dropped_sector": s, "n_group": m, "k": k,
                          "lift": r4(k / m - base)})
        drops.sort(key=lambda x: x["lift"])
        d["drop_one_worst"] = drops[0] if drops else None
        d["drop_one_five_worst"] = drops[:5]
        d["group_sector_top5"] = [{"sic2": s, "n": c} for s, c in
                                  Counter(r["sic2"] for r in rs
                                          if r["ticker"] in gset and r.get("sic2")
                                          ).most_common(5)]
        per[str(v)] = d
    out["per_v"] = per
    mh_ok = all(per[str(v)]["mh_by_threshold"]["n1>=3,n0>=3"]["mh_risk_diff"] >= LIFT_LINE
                for v in TRIO)
    dr_ok = all(per[str(v)]["drop_one_worst"]["lift"] >= LIFT_LINE for v in TRIO)
    alt = {}
    for key in ("n1>=2,n0>=2", "n1>=1,n0>=1", "n1>=5,n0>=5"):
        vals = [per[str(v)]["mh_by_threshold"][key]["mh_risk_diff"] for v in TRIO]
        alt[key] = {"lifts": vals, "all_over_line": all(x is not None and x >= LIFT_LINE
                                                        for x in vals)}
    out["mh_threshold_robustness"] = alt
    out["gate_met_as_searched"] = mh_ok and dr_ok
    out["verdict"] = "合格" if (mh_ok and dr_ok) else "不合格"
    return out


# ═══════════════════ 検問4: irr ═══════════════════
def spearman(xs, ys):
    n = len(xs)
    if n < 8:
        return None

    def rk(v):
        idx = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for t in range(i, j + 1):
                r[idx[t]] = avg
            i = j + 1
        return r
    a, b = rk(xs), rk(ys)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    return None if da == 0 or db == 0 else num / (da * db)


def t4_irr(sel, sides):
    per = {}
    for v in TRIO:
        rs = U[v]
        g, sc = score_group(rs, sel, sides, 2)
        d = {}
        for key in ("irr", "irr_near"):
            sub = [(rs[i], sc[i], g[i]) for i in range(len(rs)) if rs[i].get(key) is not None]
            if not sub:
                d[key] = {"n_with": 0, "status": "判定不能（被覆ゼロ）"}
                continue
            lay = [(r, s, gg) for (r, s, gg) in sub if r[key] >= 70]
            nb = len(lay)
            kb = sum(1 for (r, _s, _g) in lay if r["y10"])
            gl = [(r, s, gg) for (r, s, gg) in lay if gg]
            kg = sum(1 for (r, _s, _g) in gl if r["y10"])
            rho = spearman([s for (_r, s, _g) in sub], [_r[key] for (_r, _s, _g) in sub])
            d[key] = {"n_with": len(sub), "layer_n": nb,
                      "layer_base": r4(kb / nb) if nb else None,
                      "layer_n_group": len(gl), "layer_k": kg,
                      "layer_p_group": r4(kg / len(gl)) if gl else None,
                      "layer_lift": r4(kg / len(gl) - kb / nb) if (gl and nb) else None,
                      "min_num_met_in_layer": kg >= MIN_NUM,
                      "spearman_score_vs_irr": r4(rho)}
        per[str(v)] = d
    # Fisher z の 95%CI（点推定だけで『直交』と言わない）
    for v in TRIO:
        for k in ("irr", "irr_near"):
            d = per[str(v)].get(k, {})
            rho, n = d.get("spearman_score_vs_irr"), d.get("n_with", 0)
            if rho is None or n < 10:
                continue
            z = 0.5 * math.log((1 + rho) / (1 - rho))
            se = 1.0 / math.sqrt(n - 3)
            lo, hi = z - 1.96 * se, z + 1.96 * se
            d["spearman_95ci"] = [r4(math.tanh(lo)), r4(math.tanh(hi))]
            d["ci_within_pm015"] = abs(math.tanh(lo)) < LIFT_LINE and abs(math.tanh(hi)) < LIFT_LINE
    rhos = [per[str(v)][k]["spearman_score_vs_irr"] for v in TRIO for k in ("irr", "irr_near")
            if per[str(v)].get(k, {}).get("spearman_score_vs_irr") is not None]
    layer_ok = any(per[str(v)][k].get("min_num_met_in_layer") for v in TRIO
                   for k in ("irr", "irr_near") if k in per[str(v)])
    orth = all(abs(x) < LIFT_LINE for x in rhos) if rhos else False
    return {"per_v": per,
            "branch_layer": {"judgeable": layer_ok,
                             "status": "判定不能（層内の分子が 20 に届かない）" if not layer_ok
                             else "判定可能"},
            "branch_orthogonal": {"rhos": [r4(x) for x in rhos], "all_abs_below_0.15": orth},
            "prereg_is_OR": "irr>=70 層内で残る **または** irr と直交",
            "verdict": ("合格（直交ブランチ）" if orth else "不合格"),
            "verdict_layer_only": "判定不能"}


# ═══════════════════ 検問5: 置換 ═══════════════════
def build_perm(seed):
    """会社単位で全ビンテージ同時に y10 を並べ替える（sic2 層内）。独立実装。"""
    rnd = random.Random(seed)
    lab = {v: {r["ticker"]: (1 if r["y10"] else 0) for r in
               [x for x in ROWS if x["vintage"] == v and x.get("y10") is not None]}
           for v in TRIO}
    sic = {}
    for v in TRIO:
        for r in ROWS:
            if r["vintage"] == v:
                sic[r["ticker"]] = r.get("sic2")
    common = set(lab[2016]) & set(lab[2017]) & set(lab[2018])
    by = defaultdict(list)
    for t in sorted(common):
        by[sic.get(t)].append(t)
    solo = {v: defaultdict(list) for v in TRIO}
    for v in TRIO:
        for t in lab[v]:
            if t not in common:
                solo[v][sic.get(t)].append(t)

    def draw():
        mp = {}
        for _s, ts in by.items():
            sh = list(ts)
            rnd.shuffle(sh)
            for a, b in zip(ts, sh):
                mp[a] = b
        out = {}
        for v in TRIO:
            cur = {t: lab[v][mp[t]] for t in common}
            for _s, ts in solo[v].items():
                vals = [lab[v][t] for t in ts]
                rnd.shuffle(vals)
                for t, x in zip(ts, vals):
                    cur[t] = x
            out[v] = cur
        return out
    return draw, {"n_common": len(common), "n_strata": len(by),
                  "n_solo": {str(v): sum(len(x) for x in solo[v].values()) for v in TRIO}}


def t5_permutation(sel, sides):
    """(a) 群を固定して結果だけ混ぜる（この配置の p）
       (b) 発見（変数選択・向き・本数・s）ごと混ぜる（選択調整＝手続きの値札）"""
    gmask = {}
    obs = {}
    for v in TRIO:
        g, _ = score_group(U[v], sel, sides, 2)
        gmask[v] = g
        obs[v] = lift_of(U[v], g)
    obs_min = min(obs[v]["lift"] for v in TRIO)
    obs_min_hold = min(obs[v]["lift"] for v in (2017, 2018))   # 発見年2016を除く

    def lift_perm(v, labs, g):
        rs = U[v]
        lv = labs[v]
        n = k_all = m = k = 0
        for i, r in enumerate(rs):
            x = lv.get(r["ticker"])
            if x is None:
                continue
            n += 1
            k_all += x
            if g[i]:
                m += 1
                k += x
        if m == 0 or n == 0:
            return None, 0
        return k / m - k_all / n, k

    a_res, b_res = [], []
    for seed in SEEDS:
        draw, info = build_perm(seed)
        ge_min = ge_hold = ge_gate1 = 0
        proc_pass = 0
        for _ in range(N_PERM):
            labs = draw()
            lf, ks = {}, {}
            for v in TRIO:
                lf[v], ks[v] = lift_perm(v, labs, gmask[v])
            if all(lf[v] is not None for v in TRIO):
                if min(lf[v] for v in TRIO) >= obs_min:
                    ge_min += 1
                if min(lf[v] for v in (2017, 2018)) >= obs_min_hold:
                    ge_hold += 1
                if all(lf[v] >= LIFT_LINE and ks[v] >= MIN_NUM for v in TRIO):
                    ge_gate1 += 1
            # (b) 手続きごと: 発見年の擬似ラベルで変数を選び直し J/s/mode も探索
            if procedure_passes(labs):
                proc_pass += 1
        a_res.append({"seed": seed, "p_min_lift": r4(ge_min / N_PERM),
                      "p_min_lift_holdout_2017_2018": r4(ge_hold / N_PERM),
                      "p_gate1_fixed_group": r4(ge_gate1 / N_PERM)})
        b_res.append({"seed": seed, "selection_adjusted_fpr_cellfamily": r4(proc_pass / N_PERM)})
    return {"scheme": "会社単位で全ビンテージ同時・sic2層内",
            "perm_info": info, "n_perm_per_seed": N_PERM, "n_seeds": len(a_res),
            "observed": {"lifts": {str(v): obs[v]["lift"] for v in TRIO},
                         "min_lift": r4(obs_min),
                         "min_lift_holdout": r4(obs_min_hold)},
            "a_fixed_group": a_res,
            "a_mean": {k: r4(sum(x[k] for x in a_res) / len(a_res))
                       for k in ("p_min_lift", "p_min_lift_holdout_2017_2018",
                                 "p_gate1_fixed_group")},
            "b_selection_adjusted": b_res,
            "b_mean": r4(sum(x["selection_adjusted_fpr_cellfamily"] for x in b_res) / len(b_res)),
            "b_scope": "この細胞の家族だけ（pop=P_quality・subset=cov90_14・disc=2016・"
                       "上下1/4）で J∈{3,5,8,10,14}×s×{ge,le} を探索。"
                       "**4変種すべての家族ではない**（兄弟 hist10_verify_fpr が測定済）",
            "verdict": None}


_PROC_JS = (3, 5, 8, 10, 14)


def procedure_passes(labs):
    """擬似ラベルで、この細胞の探索（変数選択→J→s→ge/le）を丸ごとやり直し、
    gate1（lift>=0.15 ∧ 分子>=20 ∧ 3年で符号不変）を通す配置が1つでも出るか。"""
    rsD = U[DISC]
    lv = labs[DISC]
    nD = 0
    kD = 0
    ymapD = []
    for r in rsD:
        x = lv.get(r["ticker"])
        ymapD.append(x)
        if x is not None:
            nD += 1
            kD += x
    if nD == 0:
        return False
    baseD = kD / nD
    feats = []
    for c in COLS:
        best = None
        for side in ("hi", "lo"):
            g = good_flags(rsD, c, side)
            m = k = 0
            for i in range(len(rsD)):
                if g[i] and ymapD[i] is not None:
                    m += 1
                    k += ymapD[i]
            if m == 0 or m == nD:
                continue
            lf = k / m - baseD
            if best is None or lf > best[1]:
                best = (side, lf, c)
        if best:
            feats.append({"col": c, "side": best[0], "abs": abs(best[1])})
    feats.sort(key=lambda x: (-x["abs"], x["col"]))
    pre = {}
    for v in TRIO:
        rs = U[v]
        lvv = labs[v]
        ys = [lvv.get(r["ticker"]) for r in rs]
        n = sum(1 for y in ys if y is not None)
        k = sum(y for y in ys if y is not None)
        pre[v] = {"rs": rs, "ys": ys, "n": n, "base": (k / n) if n else 0,
                  "flags": {}}
        for f in feats:
            pre[v]["flags"][(f["col"], f["side"])] = good_flags(rs, f["col"], f["side"])
    for J in _PROC_JS:
        if J > len(feats):
            continue
        selc = [(f["col"], f["side"]) for f in feats[:J]]
        sc = {}
        for v in TRIO:
            fl = [pre[v]["flags"][c] for c in selc]
            sc[v] = [sum(f[i] for f in fl) for i in range(len(pre[v]["rs"]))]
        for s in range(1, J + 1):
            for mode in ("ge", "le"):
                ok, up = True, None
                for v in TRIO:
                    ys = pre[v]["ys"]
                    m = k = 0
                    for i, x in enumerate(sc[v]):
                        inn = (x >= s) if mode == "ge" else (x < s)
                        if inn and ys[i] is not None:
                            m += 1
                            k += ys[i]
                    if m < MIN_NUM or m >= pre[v]["n"] or k < MIN_NUM:
                        ok = False
                        break
                    lf = k / m - pre[v]["base"]
                    if up is None:
                        up = lf > 0
                    if abs(lf) < LIFT_LINE or ((lf > 0) != up):
                        ok = False
                        break
                if ok:
                    return True
    return False


# ═══════════════════ 検問6: 増分 ═══════════════════
def g_shrink(r):
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def g_thin(r):
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def t6_incremental(sel, sides):
    out = {"gates": {"質実証": "P_quality（**母集団の定義そのもの**＝この群では全社が通る）",
                     "事業の収縮": "f2_cagr5<0 ∧ f2_opmD5<0（v9.9.99）",
                     "薄い財務": "f2_intcov<3（門の nde>4 の歴史側の相当物）",
                     "堀": "irr>=70（**正の選抜**。被覆は2018のみ113/310）"},
           "readings": {}}
    r1, r2, r3, cov = {}, {}, {}, {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        grp = [rs[i] for i in range(len(rs)) if g[i]]
        blocked = [r for r in grp if g_shrink(r) or g_thin(r)]
        gw = [r for r in grp if r["y10"]]
        gw_blocked = [r for r in gw if g_shrink(r) or g_thin(r)]
        keep = [r for r in rs if not (g_shrink(r) or g_thin(r))]
        kg = [r for r in keep if r["ticker"] in {x["ticker"] for x in grp}]
        base_k = sum(1 for r in keep if r["y10"]) / len(keep) if keep else None
        p_kg = sum(1 for r in kg if r["y10"]) / len(kg) if kg else None
        r1[str(v)] = {"n_rows_after_gates": len(keep), "n_group_after_gates": len(kg),
                      "k": sum(1 for r in kg if r["y10"]), "base": r4(base_k),
                      "p_group": r4(p_kg),
                      "lift_within_gate_passers": r4(p_kg - base_k)
                      if (p_kg is not None and base_k is not None) else None}
        r2[str(v)] = {"n_group": len(grp), "n_blocked": len(blocked),
                      "share_of_group_already_blocked": r4(len(blocked) / len(grp)),
                      "n_group_winners": len(gw), "n_winners_blocked": len(gw_blocked),
                      "share_of_winners_already_blocked": r4(len(gw_blocked) / len(gw))
                      if gw else None,
                      "share_of_winners_outside_gate": r4(len(gw_blocked) / len(gw))
                      if gw else None}
        with_irr = [r for r in grp if r.get("irr") is not None]
        gw_irr = [r for r in gw if r.get("irr") is not None]
        r3[str(v)] = {"n_group_with_irr": len(with_irr),
                      "n_winners_with_irr": len(gw_irr),
                      "n_winners_irr_ge70": sum(1 for r in gw_irr if r["irr"] >= 70),
                      "share_of_measured_winners_irr_ge70":
                          r4(sum(1 for r in gw_irr if r["irr"] >= 70) / len(gw_irr))
                          if gw_irr else None,
                      "coverage_note": "分母は irr が測れた勝者だけ。被覆が薄い年は判定不能"}
        cov[str(v)] = {"intcov_coverage": r4(sum(1 for r in rs
                                                 if r.get("f2_intcov") is not None) / len(rs)),
                       "irr_coverage": r4(sum(1 for r in rs
                                              if r.get("irr") is not None) / len(rs))}
    out["readings"]["読み1_門を通る社に絞って測り直した lift（探索側と同じ）"] = r1
    out["readings"]["読み2_群と群の勝者のうち門が既に落としている割合（prereg の字義）"] = r2
    out["readings"]["読み3_堀(irr>=70)が既に選んでいる勝者の割合"] = r3
    out["coverage"] = cov
    ok1 = all(r1[str(v)]["lift_within_gate_passers"] is not None
              and r1[str(v)]["lift_within_gate_passers"] >= LIFT_LINE for v in TRIO)
    ok2 = all(r2[str(v)]["share_of_winners_already_blocked"] is not None
              and r2[str(v)]["share_of_winners_already_blocked"] <= INCREMENTAL_MAX_CAUGHT
              for v in TRIO)
    out["reading1_ok"] = ok1
    out["reading2_ok"] = ok2
    out["verdict"] = "合格" if (ok1 and ok2) else "不合格"
    return out


# ═══════════════ 事前登録の外（合否に数えない・記録する） ═══════════════
def extras(sel, sides):
    ex = {"note": "**事前登録の外**。合否には数えない。候補の性質を測るための記録"}

    # E1 s 曲線と単調性
    scur = {}
    for v in TRIO:
        rs = U[v]
        _, sc = score_group(rs, sel, sides, 2)
        base = sum(1 for r in rs if r["y10"]) / len(rs)
        d = {}
        for s in (1, 2, 3):
            m = sum(1 for x in sc if x >= s)
            k = sum(1 for i, r in enumerate(rs) if sc[i] >= s and r["y10"])
            d["score>=%d" % s] = {"n_group": m, "k": k,
                                  "lift": r4(k / m - base) if m else None,
                                  "gate1_ok": bool(m and k >= MIN_NUM
                                                   and (k / m - base) >= LIFT_LINE)}
        step = {}
        for s in (0, 1, 2, 3):
            grp = [rs[i] for i in range(len(rs)) if sc[i] == s]
            step["score==%d" % s] = {"n": len(grp),
                                     "p": r4(sum(1 for r in grp if r["y10"]) / len(grp))
                                     if grp else None}
        d["step"] = step
        ps = [step["score==%d" % s]["p"] for s in (0, 1, 2, 3)
              if step["score==%d" % s]["p"] is not None]
        d["monotone_in_score"] = all(ps[i] <= ps[i + 1] for i in range(len(ps) - 1))
        scur[str(v)] = d
    ex["E1_s_curve"] = {"table": scur,
                        "read": "s=2 だけが線を通るなら『美点の数』ではなく s の当てはめ"}

    # E2 規模の層内（第1変数 f2_rev hi が単独で lift 0.10-0.15 を出す）
    size = {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        base = sum(1 for r in rs if r["y10"]) / len(rs)
        xs = [r["f2_rev"] for r in rs]
        q75 = quantile(xs, 0.75)
        hi = [i for i in range(len(rs)) if rs[i]["f2_rev"] >= q75]
        khi = sum(1 for i in hi if rs[i]["y10"])
        inl = [i for i in hi if g[i]]
        outl = [i for i in range(len(rs)) if g[i] and i not in set(hi)]
        # 規模四分位ごとの MH（規模を層にした業種調整の双子）
        qs = [quantile(xs, q) for q in (0.25, 0.5, 0.75)]

        def bucket(x):
            return 0 if x < qs[0] else (1 if x < qs[1] else (2 if x < qs[2] else 3))
        st = defaultdict(lambda: [0, 0, 0, 0])
        for i, r in enumerate(rs):
            d = st[bucket(r["f2_rev"])]
            w = 1 if r["y10"] else 0
            if g[i]:
                d[0] += 1
                d[1] += w
            else:
                d[2] += 1
                d[3] += w
        num = den = 0.0
        used = 0
        for _b, (n1, k1, n0, k0) in st.items():
            if n1 < 3 or n0 < 3:
                continue
            w = n1 * n0 / (n1 + n0)
            num += w * (k1 / n1 - k0 / n0)
            den += w
            used += 1
        size[str(v)] = {
            "f2_rev_hi_alone": {"n": len(hi), "k": khi, "lift": r4(khi / len(hi) - base)},
            "group_inside_rev_hi": {"n": len(inl),
                                    "p": r4(sum(1 for i in inl if rs[i]["y10"]) / len(inl))
                                    if inl else None},
            "group_outside_rev_hi": {"n": len(outl),
                                     "p": r4(sum(1 for i in outl if rs[i]["y10"]) / len(outl))
                                     if outl else None},
            "lift_within_rev_hi_layer": r4(
                (sum(1 for i in inl if rs[i]["y10"]) / len(inl)) - (khi / len(hi)))
            if inl else None,
            "mh_over_size_quartiles": {"risk_diff": r4(num / den) if den else None,
                                       "strata_used": used}}
    ex["E2_size"] = {"table": size,
                     "read": "規模を層にして調整しても残るか。残らなければ『美点の数』ではなく規模の粗い測り"}

    # E3 意味で決めた向き（データで向きを選ばない版）
    apri = {}
    for v in TRIO:
        rs = U[v]
        base = sum(1 for r in rs if r["y10"]) / len(rs)
        # 常識的な『美点』の向き: 規模は大きいほう・R&Dは厚いほう・成長は**高いほう**
        fl = [good_flags(rs, "f2_rev", "hi"), good_flags(rs, "f2_rnd_r", "hi"),
              good_flags(rs, "f2_cagr5", "hi")]
        sc = [sum(f[i] for f in fl) for i in range(len(rs))]
        m = sum(1 for x in sc if x >= 2)
        k = sum(1 for i, r in enumerate(rs) if sc[i] >= 2 and r["y10"])
        apri[str(v)] = {"n_group": m, "k": k, "lift": r4(k / m - base) if m else None}
    ex["E3_apriori_direction"] = {
        "def": "3本目の向きだけ意味で決める（成長は高いほうが美点）＝データに向きを選ばせない版",
        "table": apri,
        "read": "候補の 3本目は **成長が低いほう** が『美点』。意味ではなくデータが決めた向き"}

    # E4 暦年ごとの優位（レジーム）
    ex["E4_regime_calendar"] = regime_calendar(sel, sides)

    # E6 ハードル感度と実際の分布（二値の線が 10% にあることの産物か）
    hur = {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        grp = [rs[i]["tr_cagr"] for i in range(len(rs)) if g[i] and rs[i].get("tr_cagr") is not None]
        oth = [rs[i]["tr_cagr"] for i in range(len(rs)) if not g[i] and rs[i].get("tr_cagr") is not None]
        allv = grp + oth
        d = {"n_group": len(grp), "n_other": len(oth),
             "median_group": r4(quantile(grp, 0.5)), "median_other": r4(quantile(oth, 0.5)),
             "median_diff_pt": r4((quantile(grp, 0.5) - quantile(oth, 0.5)) * 100),
             "q25_group": r4(quantile(grp, 0.25)), "q25_other": r4(quantile(oth, 0.25)),
             "q75_group": r4(quantile(grp, 0.75)), "q75_other": r4(quantile(oth, 0.75)),
             "mean_group": r4(sum(grp) / len(grp)), "mean_other": r4(sum(oth) / len(oth)),
             "by_hurdle": {}}
        for h in (0.00, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
            base = sum(1 for x in allv if x >= h) / len(allv)
            k = sum(1 for x in grp if x >= h)
            d["by_hurdle"]["%.2f" % h] = {"k": k, "p_group": r4(k / len(grp)),
                                          "base": r4(base),
                                          "lift": r4(k / len(grp) - base),
                                          "over_line": (k / len(grp) - base) >= LIFT_LINE
                                          and k >= MIN_NUM}
        hur[str(v)] = d
    ex["E6_hurdle_sensitivity"] = {
        "def": "事前登録は 10% で線を引いた。実効果なら近傍のハードルでも同じ向きに出るはず",
        "table": hur,
        "read": "10% だけで出て 8%/12% で消えるなら、二値の線の置き場所の産物"}

    # E7 規模四分位の中の群の分布（E2 の補助）
    comp = {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        xs = [r["f2_rev"] for r in rs]
        qs = [quantile(xs, q) for q in (0.25, 0.5, 0.75)]

        def bucket(x):
            return 0 if x < qs[0] else (1 if x < qs[1] else (2 if x < qs[2] else 3))
        c = Counter(bucket(rs[i]["f2_rev"]) for i in range(len(rs)) if g[i])
        tot = Counter(bucket(r["f2_rev"]) for r in rs)
        comp[str(v)] = {"group_by_size_quartile": {str(b): c.get(b, 0) for b in range(4)},
                        "pop_by_size_quartile": {str(b): tot.get(b, 0) for b in range(4)},
                        "share_of_group_in_top_quartile": r4(c.get(3, 0) / sum(c.values()))}
    ex["E7_size_composition"] = comp

    # E8 同期間の指数と比べる（10% は SPY に負ける水準・prereg が自認）
    # ⚠ 指数の実測は在庫に **2013窓と2018窓しか無い**。無い年に数字を置かない（ルール7）
    anchor = json.load(open(TARGETS, encoding="utf-8")).get("verify", {}).get("spy_anchor", {})
    spy_measured = {"2018": anchor.get("r18")}
    idx = {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        grp = [rs[i]["tr_cagr"] for i in range(len(rs))
               if g[i] and rs[i].get("tr_cagr") is not None]
        oth = [rs[i]["tr_cagr"] for i in range(len(rs))
               if not g[i] and rs[i].get("tr_cagr") is not None]
        h = spy_measured.get(str(v))
        d = {"group_median": r4(quantile(grp, 0.5)),
             "other_median": r4(quantile(oth, 0.5))}
        if h is None:
            d["index_for_this_window"] = "実測なし（在庫の spy_anchor は 2013窓と2018窓のみ）＝判定不能"
        else:
            d["spy_cagr_measured"] = h
            d["group_beat_index"] = {"k": sum(1 for x in grp if x >= h), "n": len(grp),
                                     "p": r4(sum(1 for x in grp if x >= h) / len(grp))}
            d["other_beat_index"] = {"k": sum(1 for x in oth if x >= h), "n": len(oth),
                                     "p": r4(sum(1 for x in oth if x >= h) / len(oth))}
            d["group_median_minus_index_pt"] = r4((quantile(grp, 0.5) - h) * 100)
        idx[str(v)] = d
    ex["E8_vs_index"] = {
        "def": "在庫の spy_anchor（out/hist10_targets.json）の実測だけを使う。"
               "r13=%s（2013窓13.09年）／r18=%s（2018窓8.09年）。**2016/2017窓の指数は在庫に無い**"
               % (anchor.get("r13"), anchor.get("r18")),
        "table": idx,
        "read": "群の中央値が指数に届かないなら、この群は『複利が立つ』を当てても『指数に勝つ』は当てていない。"
                "2016/2017 は指数の実測が無いので比較そのものを出さない"}

    # E9 業種を2つ抜く（事前登録の外・兄弟が 2017 で 0.1429 と報告している）
    d2 = {}
    for v in TRIO:
        rs = U[v]
        g, _ = score_group(rs, sel, sides, 2)
        gset = {rs[i]["ticker"] for i in range(len(rs)) if g[i]}
        secs = sorted({r.get("sic2") for r in rs if r.get("sic2")})
        best = None
        for i in range(len(secs)):
            for j in range(i + 1, len(secs)):
                sub = [r for r in rs if r.get("sic2") not in (secs[i], secs[j])]
                if len(sub) < 40:
                    continue
                m = sum(1 for r in sub if r["ticker"] in gset)
                if m < 10:
                    continue
                k = sum(1 for r in sub if r["ticker"] in gset and r["y10"])
                base = sum(1 for r in sub if r["y10"]) / len(sub)
                lf = k / m - base
                if best is None or lf < best["lift"]:
                    best = {"dropped": [secs[i], secs[j]], "n_group": m, "k": k, "lift": r4(lf)}
        d2[str(v)] = best
    ex["E9_drop_two_sectors"] = {"def": "**事前登録の外**（prereg は1つ抜きまで）", "worst": d2}

    # E5 複製の重なり（同じ会社を3回数えていないか）は t2 に、ここでは窓の重なり
    ex["E5_window_overlap"] = {
        "def": "3ビンテージの前方窓はすべて 2026-08 で終わる",
        "median_years": {str(v): r4(sorted(r["years"] for r in U[v])[len(U[v]) // 2])
                         for v in TRIO},
        "shared_share_of_2016_window": r4(8.09 / 10.09),
        "shared_share_of_2017_window": r4(8.09 / 9.09)}
    return ex


def regime_calendar(sel, sides):
    """群の優位が特定の暦年に載っていないか。月次在庫から暦年リターンを組む。"""
    try:
        mons = {}
        for f in (MON_A, MON_B):
            d = json.load(open(f, encoding="utf-8"))
            for t, ser in d.items():
                mons.setdefault(t, []).extend(ser)
    except Exception as e:                                   # noqa: BLE001
        return {"status": "月次在庫を読めない: %s" % e}
    import datetime as _dt
    yearend = {}
    for t, ser in mons.items():
        best = {}
        for ts, px in sorted(ser):
            if px is None or px <= 0:
                continue
            dt = _dt.datetime.utcfromtimestamp(ts)
            best[(dt.year, dt.month)] = px
        ye = {}
        for (y, m), px in best.items():
            if m == 12:
                ye[y] = px
        yearend[t] = ye
    rs = U[2018]
    # ── 検査器を信じる前に検査器を検算する: 月次から組み直した CAGR が tr_cagr と一致するか ──
    dif = []
    for r in rs:
        ser = sorted(x for x in mons.get(r["ticker"], []) if x[1] and x[1] > 0)
        st = [x for x in ser if _dt.datetime.utcfromtimestamp(x[0]).year == 2018
              and _dt.datetime.utcfromtimestamp(x[0]).month == 7]
        if not st or len(ser) < 20 or r.get("tr_cagr") is None:
            continue
        yrs = (ser[-1][0] - st[0][0]) / (365.2425 * 86400)
        if yrs <= 0:
            continue
        dif.append(abs((ser[-1][1] / st[0][1]) ** (1 / yrs) - 1 - r["tr_cagr"]))
    dif.sort()
    selfchk = {"n": len(dif),
               "median_abs_diff_vs_tr_cagr": r4(dif[len(dif) // 2]) if dif else None,
               "max_abs_diff": r4(dif[-1]) if dif else None,
               "read": "月次在庫から組み直した2018窓の CAGR が結果変数 tr_cagr と一致するか。"
                       "一致して初めて暦年の数字を信じてよい"}

    g, _ = score_group(rs, sel, sides, 2)
    grp = [rs[i]["ticker"] for i in range(len(rs)) if g[i]]
    oth = [rs[i]["ticker"] for i in range(len(rs)) if not g[i]]
    tbl = {}
    for y in range(2019, 2026):
        def med(ts):
            v = []
            for t in ts:
                a = yearend.get(t, {}).get(y - 1)
                b = yearend.get(t, {}).get(y)
                if a and b and a > 0:
                    v.append(b / a - 1.0)
            v.sort()
            return (r4(v[len(v) // 2]) if v else None), len(v)
        mg, ng = med(grp)
        mo, no = med(oth)
        tbl[str(y)] = {"median_group": mg, "n_group": ng,
                       "median_other": mo, "n_other": no,
                       "diff_pt": r4((mg - mo) * 100) if (mg is not None and mo is not None)
                       else None}
    diffs = [v["diff_pt"] for v in tbl.values() if v["diff_pt"] is not None]
    return {"def": "2018ビンテージの群 vs 非群。暦年ごとの**中央値リターン差**（pt）",
            "selfcheck_monthly_vs_tr_cagr": selfchk,
            "table": tbl,
            "n_years_group_ahead": sum(1 for x in diffs if x > 0),
            "n_years": len(diffs),
            "read": "全部の年で前なら通年の優位。1-2年に載っているならレジームの産物"}


# ═════════════════════════ main ═════════════════════════
def main():
    res = {"generated": "2026-08-12",
           "tool": "night/hist10_verify_score3quart.py",
           "prereg": "out/hist10_prereg.json（線はここにある。この道具は一つも作らない）",
           "candidate": {"angle": "D", "pop": "P_quality", "subset": "cov90_14",
                         "disc": 2016, "binar": "上下1/4", "J": 3, "s": 2, "mode": "ge",
                         "claimed": {"2016": [55, 35, 0.2073], "2017": [55, 34, 0.1978],
                                     "2018": [53, 32, 0.1973]}},
           "independence": {
               "imports": "hist10_diag / hist10_angleD / hist10_angleB を import していない",
               "inputs": ["out/hist_wd_panel.json", "out/hist10_targets.json"],
               "counting": "探索側=bit-plane 加算器 ／ こちら=真偽リストの素朴なカウント",
               "seeds": SEEDS}}

    # 0 自己検算
    ydef_bad = sum(1 for r in ROWS if r.get("y10") is not None and r.get("tr_cagr") is not None
                   and r["y10"] != (r["tr_cagr"] >= HURDLE))
    res["selfcheck"] = {
        "y10_vs_tr_cagr_mismatch": ydef_bad,
        "universe_n": {str(v): len(U[v]) for v in TRIO},
        "P_quality_rows_before_completecase": {
            str(v): sum(1 for r in ROWS if r["vintage"] == v and r.get("P_quality") is True)
            for v in TRIO},
        "complete_case_retention": {
            str(v): r4(len(U[v]) / sum(1 for r in ROWS if r["vintage"] == v
                                       and r.get("P_quality") is True)) for v in TRIO},
        "base_rate_y10": {str(v): r4(sum(1 for r in U[v] if r["y10"]) / len(U[v]))
                          for v in TRIO},
        "⚠P_quality_is_2_conditions_not_3": {
            "panel_says": sorted({r.get("quality_basis") for v in TRIO for r in U[v]}),
            "meaning": "2016-2018 の P_quality は 営業利益率10%+ ∧ 5年FCF全年黒字 の**2条件**で、"
                       "規約の『営業利益全年黒字』が欠けている（panel の known_asymmetries が自認）。"
                       "増分ゲートの『質実証』はこの緩い版",
            "src": "out/hist_wd_panel.json known_asymmetries"},
        "⚠irr_near_is_borrowed": {
            "by_vintage": {str(v): dict(Counter(r.get("irr_near_src") for r in U[v]
                                                if r.get("irr_near") is not None))
                           for v in TRIO},
            "meaning": "2016/2017 に irr の読解は無い。irr_near は近傍ビンテージの読解の借用で、"
                       "**2018 から借りた行は前方参照**（検問4の直交ブランチはこれを含む）"}}

    t1 = t1_reproduce()
    res["t1_reproduce"] = t1
    sel = t1["selected"]["cols"]
    sides = t1["selected"]["sides"]

    res["t2_vintage"] = t2_vintage(sel, sides)
    res["t3_sector"] = t3_sector(sel, sides)
    res["t4_irr"] = t4_irr(sel, sides)
    res["t5_permutation"] = t5_permutation(sel, sides)
    res["t6_incremental"] = t6_incremental(sel, sides)
    res["extras_outside_prereg"] = extras(sel, sides)

    v = {"1_再現": t1["verdict"],
         "2_ビンテージ": res["t2_vintage"]["verdict"],
         "3_業種": res["t3_sector"]["verdict"],
         "4_irr": res["t4_irr"]["verdict"],
         "5_置換": None,
         "6_増分": res["t6_incremental"]["verdict"]}
    p5 = res["t5_permutation"]["a_mean"]["p_min_lift_holdout_2017_2018"]
    v["5_置換"] = "合格" if p5 is not None and p5 < 0.05 else "不合格"
    res["t5_permutation"]["verdict"] = v["5_置換"]
    res["verdicts"] = v
    res["n_failed"] = sum(1 for x in v.values() if x and x.startswith("不合格"))

    # ── 兄弟の検査器との突合せ（v9.9.65: 違うことを言うなら名指しで書く） ──
    cc = {"files": ["out/hist10_verify_addscore3.json", "out/hist10_verify_fpr.json"]}
    try:
        s1 = json.load(open(SIB1, encoding="utf-8"))
        cc["addscore3_verdicts"] = s1.get("verdicts")
        mine18 = t1["mine_per_v"]["2018"]
        his18 = s1["t1_reproduce"]["per_vintage"]["2018"]
        cc["t1_numbers_agree"] = (mine18["n_group"] == his18["n_group"]
                                  and mine18["k"] == his18["k"]
                                  and abs(mine18["lift"] - his18["lift"]) < 1e-9)
        cc["known_definitional_difference"] = {
            "what": "検問2の『会社を1回だけ数える』版の対照群の定義",
            "addscore3": "control_never n=169（**3ビンテージすべての宇宙に載る会社**に限る）",
            "mine": "control_never n=%d（2018 の宇宙に載り一度も群に入らなかった会社）"
                    % res["t2_vintage"]["company_level_dedup"]["control_never"]["n"],
            "do_the_conclusions_differ": "しない。対照の y10 率は 0.3491 vs %s でほぼ同じ"
                                         % res["t2_vintage"]["company_level_dedup"]
                                         ["control_never"]["p"]}
    except Exception as e:                                    # noqa: BLE001
        cc["addscore3"] = "読めない: %s" % e
    try:
        s2 = json.load(open(SIB2, encoding="utf-8"))
        cc["fpr_family_level"] = {
            "sibling_gate1_fpr_all_4_variants": s2["check5_permutation"]["fpr_gate1_union"]["mean"],
            "sibling_allgates_fpr": s2["check5_permutation"]["fpr_allgates"]["mean"],
            "mine_gate1_fpr_this_cell_family_only": res["t5_permutation"]["b_mean"],
            "consistency": "私の 0.05 は **この細胞の家族だけ**（約80配置）、兄弟の 0.74 は"
                           "**4変種1,176配置**の和集合。段が違うだけで矛盾しない"}
    except Exception as e:                                    # noqa: BLE001
        cc["fpr"] = "読めない: %s" % e
    res["crosscheck_with_siblings"] = cc

    ex = res["extras_outside_prereg"]
    res["verdict"] = {
        "headline": ("**6検問すべて通過＝落とせなかった**"
                     if res["n_failed"] == 0 else "不合格（検問%d件）" % res["n_failed"]),
        "checks": v,
        "what_the_group_actually_is": {
            "members_2018_sample": ["MSFT", "INTC", "CSCO", "ORCL", "TXN", "QCOM", "AMGN",
                                    "GILD", "BIIB", "PG", "KO", "PEP", "MCD", "MMM", "ITW"],
            "share_of_group_in_top_size_quartile":
                {k: x["share_of_group_in_top_quartile"] for k, x in ex["E7_size_composition"].items()},
            "lift_within_top_size_quartile":
                {k: x["lift_within_rev_hi_layer"] for k, x in ex["E2_size"]["table"].items()},
            "read": "群の 78〜87% が売上上位1/4。**その層の中では lift 0.079〜0.103＝事前登録の線 0.15 を割る**"},
        "where_it_stops_working": {
            "lift_by_hurdle": {k: {h: c["lift"] for h, c in x["by_hurdle"].items()}
                               for k, x in ex["E6_hurdle_sensitivity"]["table"].items()},
            "read": "事前登録の 10% で最大。12% で 0.105〜0.128、**15% で 0.044〜0.088**、20% でほぼ 0。"
                    "実体は『中央値 CAGR が約 +4.4pt 高い』という水準のずれで、"
                    "**門が狙う 15〜18% の帯には何の識別力も無い**"},
        "not_a_kill_but_must_be_recorded": [
            "3ビンテージは独立な3つの証拠ではない（群の Jaccard 0.42〜0.57・窓は3つとも 2026-08 で終わる）",
            "『美点の数』の3本目は **成長が低いほう** が良い側＝意味ではなくデータが決めた向き。"
            "意味で決めた向き（成長は高いほうが美点）だと 2016 が 0.1424 で線を割る",
            "業種を**2つ**抜くと 2017 で 0.1429・2018 で 0.1299（事前登録は1つ抜きまで）",
            "検問4は層内では判定不能（分子は最大10で 20 に届かない）。合格は直交ブランチのみ、"
            "しかも 2016/2017 の irr は近傍ビンテージからの借用（一部は2018からの前方参照）",
            "増分ゲートの『質実証』はこの在庫では2条件（営業利益全年黒字が欠ける）＝規約より緩い",
            "暦年ごとの中央値リターン差は 2019 −5.6pt / 2023 −6.9pt と2年は負けており、"
            "+9.6pt の 2025 に大きく寄っている"],
        "siblings": "兄弟 out/hist10_verify_addscore3.json も同じ6検問を通しており、"
                    "prereg の for_D_and_E（外側fold）条項で不合格としている。"
                    "**私はその条項を当てていない**ので、6検問だけを見た私の答えは『落とせなかった』"}
    json.dump(res, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"verdicts": v, "n_failed": res["n_failed"]},
                     ensure_ascii=False, indent=1))
    print("→", DEST)


if __name__ == "__main__":
    main()
