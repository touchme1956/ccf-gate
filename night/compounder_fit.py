# night/compounder_fit.py — 長期複利株（年15%以上）に当てはまった原則の検定
#
# 事前登録: out/compounder_fit_prereg.json（コミット 06d101cc・この道具より前）
# 問い（2026-10-14 ユーザー）:「長期複利を達成した銘柄だけでもっと当てはまったPが、何か調べたら？」
# やること: 勝ち組（tr_cagr>=15%）だけを見ると負けた社も同じ特徴を持っていたかが分からないので、
#   原則ごとに『原則が名指しする群 S』と『それ以外』で勝ち組（または大損）の割合を比べる（Family A）。
#   勝ち組の中の事実（下落の深さ・右の裾）は Family B。
# 入力: out/hist_wd_panel.json（読むだけ）と out/retro_returns_*.json の benchmark.mdd（SPY）。
# 出力: out/compounder_fit.json。判定・合否の線は事前登録の文言どおりで、この道具は線を一つも足さない。
# 外部ライブラリなし（Fisher の正確検定・Newcombe の区間・Mantel-Haenszel・Holm を自前で書く）。
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(BASE, "out", "hist_wd_panel.json")
PREREG = os.path.join(BASE, "out", "compounder_fit_prereg.json")
OUT = os.path.join(BASE, "out", "compounder_fit.json")
RET = {2013: "retro_returns_2013_all.json", 2015: "retro_returns_2015_q.json",
       2016: "retro_returns_2016.json", 2017: "retro_returns_2017.json", 2018: "retro_returns_2018.json"}
WIN, DESTROY, WIN10 = 0.15, -0.15, 0.10
Z = 1.959963984540054


# ── 統計の部品 ─────────────────────────────────────────────────────────────
def quantile(vals, p):
    """線形補間の分位点（numpy の既定 'linear' と同じ定義）。"""
    s = sorted(vals)
    if not s:
        return None
    pos = (len(s) - 1) * p
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def fisher_two_sided(a, b, c, d):
    """2x2 [[a,b],[c,d]] の Fisher の正確検定（両側・観測以下の確率の和）。"""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d

    def lp(x):
        return (math.lgamma(r1 + 1) - math.lgamma(x + 1) - math.lgamma(r1 - x + 1)
                + math.lgamma(r2 + 1) - math.lgamma(c1 - x + 1) - math.lgamma(r2 - c1 + x + 1)
                - (math.lgamma(n + 1) - math.lgamma(c1 + 1) - math.lgamma(n - c1 + 1)))
    lo, hi = max(0, c1 - r2), min(r1, c1)
    p_obs = lp(a)
    tot = 0.0
    for x in range(lo, hi + 1):
        q = lp(x)
        if q <= p_obs + 1e-7:
            tot += math.exp(q)
    return min(1.0, tot)


def wilson(k, n):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + Z * Z / n
    mid = (p + Z * Z / (2 * n)) / den
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return (mid - half, mid + half)


def newcombe(k1, n1, k0, n0):
    """p1−p0 の95%区間（Newcombe のハイブリッド・スコア法）。"""
    p1, p0 = k1 / n1, k0 / n0
    l1, u1 = wilson(k1, n1)
    l0, u0 = wilson(k0, n0)
    d = p1 - p0
    return (d - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2))


def mh_rd(rows, in_s, ev):
    """sic2 で層にした Mantel-Haenszel のリスク差（両群がある層だけ）。"""
    strata = {}
    for r in rows:
        strata.setdefault(r.get("sic2"), []).append(r)
    num = den = 0.0
    used = 0
    for _, rs in strata.items():
        s1 = [r for r in rs if in_s(r)]
        s0 = [r for r in rs if not in_s(r)]
        if not s1 or not s0:
            continue
        n1, n0 = len(s1), len(s0)
        w = n1 * n0 / (n1 + n0)
        num += w * (sum(ev(r) for r in s1) / n1 - sum(ev(r) for r in s0) / n0)
        den += w
        used += 1
    return (num / den if den else None), used


def holm(ps):
    """Holm の調整 p（入力の順のまま返す）。None は飛ばす。"""
    idx = sorted([i for i, p in enumerate(ps) if p is not None], key=lambda i: ps[i])
    m = len(idx)
    adj = [None] * len(ps)
    run = 0.0
    for rank, i in enumerate(idx):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def spearman(x, y):
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    syy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return sxy / (sxx * syy) if sxx and syy else None


def median(v):
    return quantile(v, 0.5)


# ── 検定の定義（事前登録の文言をそのまま関数にした） ─────────────────────────
def g(r, k):
    v = r.get(k)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def cut_hi(rows, key, p):
    vals = [g(r, key) for r in rows if g(r, key) is not None]
    q = quantile(vals, p)
    return q, (lambda r: g(r, key) is not None and g(r, key) >= q)


def cut_lo(rows, key, p):
    vals = [g(r, key) for r in rows if g(r, key) is not None]
    q = quantile(vals, p)
    return q, (lambda r: g(r, key) is not None and g(r, key) <= q)


def has(key):
    return lambda r: g(r, key) is not None


def growth_key(v):
    return "co_sales_cagr5" if v in (2013, 2015) else "f2_cagr5"


def build(test_id, rows_v, v):
    """(母集団の行, S の判定, 切れ目の説明) を返す。測れなければ None。"""
    t = test_id
    if t == "A01":
        k = growth_key(v)
        pop = [r for r in rows_v if g(r, k) is not None]
        q, s = cut_hi(pop, k, 0.75)
        return pop, s, f"{k} >= {q} (上位1/4)"
    if t == "A02":
        pop = [r for r in rows_v if g(r, "f2_accel") is not None]
        return pop, (lambda r: g(r, "f2_accel") <= -0.10), "f2_accel <= -0.10"
    if t in ("A03", "A04"):
        pop = [r for r in rows_v if r.get("P_quality") in (True, False)]
        return pop, (lambda r: r.get("P_quality") is True), "P_quality = True"
    if t == "A05":
        pop = [r for r in rows_v if g(r, "co_roic_med5") is not None]
        return pop, (lambda r: g(r, "co_roic_med5") >= 0.15), "co_roic_med5 >= 0.15"
    if t == "A06":
        pop = [r for r in rows_v if g(r, "co_roic_med5") is not None]
        return pop, (lambda r: g(r, "co_roic_med5") <= 0.08), "co_roic_med5 <= 0.08"
    if t == "A07":
        pop = [r for r in rows_v if r.get("P_quality") is True and g(r, "hv_pe_z") is not None]
        return pop, (lambda r: g(r, "hv_pe_z") < 0), "P_quality かつ hv_pe_z < 0"
    if t == "A08":
        pop = [r for r in rows_v if g(r, "pa_prox_hi") is not None]
        return pop, (lambda r: g(r, "pa_prox_hi") <= 0.70), "pa_prox_hi <= 0.70"
    if t == "A09":
        pop = [r for r in rows_v if g(r, "pa_rf5") is not None]
        q, s = cut_hi(pop, "pa_rf5", 0.75)
        return pop, s, f"pa_rf5 >= {q} (上位1/4)"
    if t == "A10":
        pop = [r for r in rows_v if g(r, "pa_rf5") is not None]
        q, s = cut_lo(pop, "pa_rf5", 0.25)
        return pop, s, f"pa_rf5 <= {q} (下位1/4)"
    if t == "A11":
        pop = [r for r in rows_v if r.get("irr") in (50, 70, 75, 85)]
        return pop, (lambda r: r.get("irr") == 85), "irr = 85（母集団 irr∈{50,70,75,85}）"
    if t == "A12":
        pop = [r for r in rows_v if r.get("irr") is not None]
        return pop, (lambda r: r.get("irr") == 100), "irr = 100"
    if t == "A13":
        pop = [r for r in rows_v if r.get("moat5") is not None]
        return pop, (lambda r: r.get("moat5") >= 4), "moat5 >= 4"
    if t == "A14":
        pop = [r for r in rows_v if g(r, "f2_gm") is not None]
        q, s = cut_hi(pop, "f2_gm", 2 / 3)
        return pop, s, f"f2_gm >= {q} (上位1/3)"
    if t == "A15":
        pop = [r for r in rows_v if g(r, "co_roic_med5") is not None and g(r, "co_roic_med5") >= 0.15
               and g(r, "co_roic_worst5") is not None]
        return pop, (lambda r: g(r, "co_roic_worst5") >= 0.09), "co_roic_med5>=0.15 の中で co_roic_worst5 >= 0.09"
    if t in ("A16", "A17"):
        pop = [r for r in rows_v if g(r, "size_rev") is not None]
        q, s = cut_hi(pop, "size_rev", 2 / 3)
        return pop, s, f"size_rev >= {q} (上位1/3)"
    if t == "A18":
        pop = [r for r in rows_v if g(r, "f2_intcov") is not None]
        return pop, (lambda r: g(r, "f2_intcov") < 3), "f2_intcov < 3"
    if t == "A19":
        pop = [r for r in rows_v if g(r, "f2_opmD5") is not None]
        vals = [g(r, "f2_opmD5") for r in pop]
        lo, hi = quantile(vals, 0.10), quantile(vals, 0.90)
        return pop, (lambda r: g(r, "f2_opmD5") <= lo or g(r, "f2_opmD5") >= hi), f"f2_opmD5 <= {lo} または >= {hi}"
    if t == "A20":
        pop = [r for r in rows_v if g(r, "f2_payout5") is not None]
        q, s = cut_lo(pop, "f2_payout5", 1 / 3)
        return pop, s, f"f2_payout5 <= {q} (下位1/3)"
    if t == "A21":
        pop = [r for r in rows_v if g(r, "per") is not None]
        q, s = cut_hi(pop, "per", 2 / 3)
        return pop, s, f"per >= {q} (上位1/3)"
    if t == "A22":
        pop = [r for r in rows_v if g(r, "co_opm") is not None]
        q, s = cut_hi(pop, "co_opm", 2 / 3)
        return pop, s, f"co_opm >= {q} (上位1/3)"
    raise ValueError(t)


def ev_fn(metric, hurdle=WIN):
    if metric == "compounder":
        return lambda r: r["tr_cagr"] >= hurdle
    return lambda r: r["tr_cagr"] <= DESTROY


def measure(pop, in_s, ev):
    s1 = [r for r in pop if in_s(r)]
    s0 = [r for r in pop if not in_s(r)]
    n1, n0 = len(s1), len(s0)
    k1, k0 = sum(ev(r) for r in s1), sum(ev(r) for r in s0)
    out = {"n_S": n1, "n_notS": n0, "events_S": k1, "events_notS": k0}
    if n1 == 0 or n0 == 0:
        out["measurable"] = False
        return out
    p1, p0 = k1 / n1, k0 / n0
    lo, hi = newcombe(k1, n1, k0, n0)
    mh, used = mh_rd(pop, in_s, ev)
    out.update({"measurable": True, "p_S": round(p1, 4), "p_notS": round(p0, 4), "delta": round(p1 - p0, 4),
                "ci95": [round(lo, 4), round(hi, 4)], "fisher_p": fisher_two_sided(k1, n1 - k1, k0, n0 - k0),
                "mh_delta": (round(mh, 4) if mh is not None else None), "mh_strata": used,
                "small": (n1 < 10 or n0 < 10 or (k1 + k0) < 5)})
    return out


def sign(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def verdict(t, prim, reps, p_holm):
    if not prim.get("measurable") or prim.get("small"):
        return "判定できない（標本が足りない）"
    d = prim["delta"]
    if t["predict"] == "null":
        if p_holm is not None and p_holm < 0.05:
            return "当てはまらない（差がある）"
        lo, hi = prim["ci95"]
        if prim["fisher_p"] >= 0.05 and lo >= -0.10 and hi <= 0.10:
            return "当てはまった（差が見えない）"
        return "判定できない（差は見えないが区間が広い）"
    want = 1 if t["predict"] == "positive" else -1
    rep_signs = [sign(r["delta"]) for r in reps if r.get("measurable") and not r.get("small")]
    reps_agree = all(sg == want for sg in rep_signs)
    if sign(d) == -want and p_holm is not None and p_holm < 0.05:
        return "逆"
    if (sign(d) == want and abs(d) >= 0.05 and p_holm is not None and p_holm < 0.05
            and sign(prim.get("mh_delta")) == want and reps_agree):
        return "当てはまった"
    if sign(d) == want and reps_agree:
        return "向きは合う（弱い）"
    return "当てはまらない"


def main():
    prereg = json.load(open(PREREG))
    panel = json.load(open(PANEL))
    rows = [r for r in panel["rows"] if r.get("has_outcome") and r.get("window_full") and r.get("tr_cagr") is not None]
    by_v = {v: [r for r in rows if r["vintage"] == v] for v in (2013, 2015, 2016, 2017, 2018)}
    bench = {}
    for v, f in RET.items():
        b = json.load(open(os.path.join(BASE, "out", f))).get("benchmark", {})
        bench[v] = {"tr_cagr": b.get("tr_cagr"), "mdd": b.get("mdd"), "years": b.get("years")}

    tests = prereg["family_A_entry_signal_vs_compounder"]
    res = []
    for t in tests:
        ev = ev_fn(t["metric"])
        entry = {"id": t["id"], "principle": t["principle"], "metric": t["metric"], "predict": t["predict"],
                 "primary": t["primary"], "by_vintage": {}}
        for v in [t["primary"]] + t["replicate"]:
            pop, in_s, how = build(t["id"], by_v[v], v)
            m = measure(pop, in_s, ev)
            m["S_def"] = how
            m["n_pop"] = len(pop)
            if t["metric"] == "compounder":       # 年10% の線（判定に使わない）
                m10 = measure(pop, in_s, ev_fn("compounder", WIN10))
                m["at_10pct"] = {k: m10.get(k) for k in ("p_S", "p_notS", "delta", "ci95", "fisher_p")}
            entry["by_vintage"][str(v)] = m
        res.append(entry)

    ps = [e["by_vintage"][str(e["primary"])].get("fisher_p") for e in res]
    adj = holm(ps)
    for e, t, pa in zip(res, tests, adj):
        prim = e["by_vintage"][str(e["primary"])]
        prim["holm_p"] = pa
        reps = [e["by_vintage"][str(v)] for v in t["replicate"]]
        e["rep_signs"] = {str(v): sign(e["by_vintage"][str(v)].get("delta")) if e["by_vintage"][str(v)].get("measurable") else None
                          for v in t["replicate"]}
        e["verdict"] = verdict(t, prim, reps, pa)

    # ── Family B ──────────────────────────────────────────────────────────
    fb = {}
    r13 = by_v[2013]
    comp = [r for r in r13 if r["tr_cagr"] >= WIN]
    rest = [r for r in r13 if r["tr_cagr"] < WIN]
    bm = bench[2013]["mdd"]
    sh = [r for r in comp if g(r, "mdd") is not None and r["mdd"] > bm]
    md_c = median([r["mdd"] for r in comp if g(r, "mdd") is not None])
    md_r = median([r["mdd"] for r in rest if g(r, "mdd") is not None])
    share = len(sh) / len(comp)
    fb["B1"] = {"n_compounders": len(comp), "spy_mdd": bm, "share_shallower_than_spy": round(share, 4),
                "n_shallower": len(sh), "tickers_shallower": sorted(r["ticker"] for r in sh),
                "median_mdd_compounders": md_c, "median_mdd_rest": md_r,
                "share_mdd_le_-0.30": round(sum(r["mdd"] <= -0.30 for r in comp) / len(comp), 4),
                "share_mdd_le_-0.50": round(sum(r["mdd"] <= -0.50 for r in comp) / len(comp), 4),
                "verdict": "当てはまった" if (share < 0.10 and md_c <= -0.40) else "当てはまらない"}
    mdds = [r["mdd"] for r in comp]
    iqr = quantile(mdds, 0.75) - quantile(mdds, 0.25)
    rho = spearman([r["tr_cagr"] for r in comp], mdds)
    fb["B2"] = {"iqr_mdd": round(iqr, 4), "q25": quantile(mdds, 0.25), "q75": quantile(mdds, 0.75),
                "spearman_cagr_mdd": round(rho, 4),
                "iqr_tr_cagr": round(quantile([r["tr_cagr"] for r in comp], 0.75) - quantile([r["tr_cagr"] for r in comp], 0.25), 4),
                "verdict": "当てはまった" if (iqr >= 0.15 and abs(rho) < 0.30) else "当てはまらない"}
    tt = sorted([r["tr_total"] for r in r13 if g(r, "tr_total") is not None], reverse=True)
    k10 = max(1, round(0.10 * len(tt)))
    top_share = sum(tt[:k10]) / sum(tt)
    ct = sorted([r["tr_total"] for r in comp], reverse=True)
    kc = max(1, round(0.10 * len(ct)))
    top_tick = sorted(r13, key=lambda r: -r["tr_total"])[:5]
    fb["B3"] = {"n": len(tt), "top10pct_n": k10, "top10pct_share_of_terminal_wealth": round(top_share, 4),
                "within_compounders_top10pct_share": round(sum(ct[:kc]) / sum(ct), 4),
                "largest5": [{"ticker": r["ticker"], "tr_total": r["tr_total"], "tr_cagr": r["tr_cagr"]} for r in top_tick],
                "verdict": "当てはまった" if top_share >= 0.40 else "当てはまらない"}
    b4 = {}
    for v in (2013, 2015, 2018):
        rr = [r for r in by_v[v] if r.get("moat5") is not None and g(r, "mdd") is not None]
        hi = [r["mdd"] for r in rr if r["moat5"] >= 4]
        lo = [r["mdd"] for r in rr if r["moat5"] < 4]
        b4[str(v)] = {"n_hi": len(hi), "n_lo": len(lo), "median_mdd_hi": median(hi), "median_mdd_lo": median(lo),
                      "diff": (round(median(hi) - median(lo), 4) if hi and lo else None)}
    fb["B4"] = {"by_vintage": b4, "verdict": "当てはまった" if (b4["2013"]["diff"] is not None and b4["2013"]["diff"] >= 0.05) else "当てはまらない"}
    sig = {"compounder": 0, "destroy": 0}
    tot = {"compounder": 0, "destroy": 0}
    for e in res:
        tot[e["metric"]] += 1
        hp = e["by_vintage"][str(e["primary"])].get("holm_p")
        if hp is not None and hp < 0.05:
            sig[e["metric"]] += 1
    fb["B5"] = {"significant_after_holm": sig, "tests": tot,
                "verdict": "当てはまった" if sig["destroy"] > sig["compounder"] else "当てはまらない"}

    base = {str(v): {"n": len(by_v[v]), "compounders": sum(r["tr_cagr"] >= WIN for r in by_v[v]),
                     "destroy": sum(r["tr_cagr"] <= DESTROY for r in by_v[v]),
                     "compounders_10pct": sum(r["tr_cagr"] >= WIN10 for r in by_v[v]), "spy": bench[v]} for v in by_v}
    out = {"generated": "2026-10-14", "tool": "night/compounder_fit.py", "prereg": "out/compounder_fit_prereg.json",
           "prereg_commit": "06d101cc",
           "implementation_notes": [
               "分位点は線形補間（numpy 既定と同じ）。上の群は切れ目以上（>=）、下の群は切れ目以下（<=）。事前登録の定義欄の『同値は大きい側に入れない』と『>= で上の群』が同じ文の中で食い違っていたので、後半の >= で実装した（連続値なので同値の影響は小さい）。",
               "行は has_outcome かつ window_full のみ（事前登録どおり）。"],
           "base_rates": base, "family_A": res, "family_B": fb}
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)

    # 画面への要約
    print("base:", {v: (b["compounders"], b["n"]) for v, b in base.items()})
    for e in res:
        p = e["by_vintage"][str(e["primary"])]
        print(f'{e["id"]} {e["metric"][:4]} pred={e["predict"]:8s} v{e["primary"]} '
              f'n={p.get("n_S")}/{p.get("n_notS")} pS={p.get("p_S")} p0={p.get("p_notS")} Δ={p.get("delta")} '
              f'ci={p.get("ci95")} p={p.get("fisher_p") and round(p["fisher_p"], 4)} holm={p.get("holm_p") and round(p["holm_p"], 4)} '
              f'mh={p.get("mh_delta")} reps={e["rep_signs"]} → {e["verdict"]}')
    for k, v in fb.items():
        print(k, json.dumps({kk: vv for kk, vv in v.items() if kk not in ("tickers_shallower", "largest5", "by_vintage")}, ensure_ascii=False), "→", v["verdict"])


if __name__ == "__main__":
    sys.exit(main())
