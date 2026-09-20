#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/retro_mcap_test.py — 事前登録 out/retro_mcap_prereg.json を**一度だけ**当てる（2026-09-20）

判定も線も物差しも prereg に書いてあるものだけを使う。ここで新しい線を作らない。
出力 out/retro_mcap_test.json
"""
import json, os, sys, statistics as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "night"))
import audit_hist85_today as H

PRE = json.load(open("out/retro_mcap_prereg.json"))
LIFT, MINNUM = 0.15, 5
HURDLE = 0.15                      # 年率≥15%（既存ハードル）
TIER = [("T1", 1000, 9e9), ("T2", 300, 1000), ("T3", 100, 300), ("T4", 30, 100), ("T5", 0, 30)]


def rows(f):
    d = json.load(open(f"out/{f}.json"))
    return d.get("rows") if isinstance(d, dict) else d


def rung_map(only_vintage=None):
    """2018の中間刻み75と2013/2015の70を『中間(70)』へ束ねる（VINTAGESの欄名差も吸収）"""
    out = {}
    for v, f, key, fld in H.VINTAGES:
        if not os.path.exists(f) or (only_vintage and v != only_vintage):
            continue
        for r in H.rows_of(f):
            t, x = r.get(key), r.get(fld)
            if not t or x is None:
                continue
            b = 85 if x == 85 else (100 if x == 100 else (70 if x in (70, 75) else 50))
            out.setdefault(t, []).append(b)
    return {t: max(v) for t, v in out.items()}


def p15(ts, R):
    n = len(ts)
    w = sum(1 for t in ts if R[t] >= HURDLE)
    return (w / n if n else None), w, n


def split(ts, key, R):
    """中央値二分。lift と両側の分子を返す"""
    if len(ts) < 4:
        return None
    s = sorted(ts, key=key)
    h = len(s) // 2
    lo, hi = s[:h], s[h:]
    plo, wlo, nlo = p15(lo, R)
    phi, whi, nhi = p15(hi, R)
    return dict(lift=round(phi - plo, 4), p_hi=round(phi, 4), p_lo=round(plo, 4),
                w_hi=whi, w_lo=wlo, n_hi=nhi, n_lo=nlo,
                med_hi=round(st.median(R[t] for t in hi), 4),
                med_lo=round(st.median(R[t] for t in lo), 4))


def spearman(xs, ys):
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v); i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            m = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[o[k]] = m
            i = j + 1
        return r
    a, b = rk(xs), rk(ys)
    n = len(a); ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** .5
    db = sum((y - mb) ** 2 for y in b) ** .5
    return round(num / (da * db), 4) if da and db else None


def main():
    RUNG = rung_map()
    # ⚠ RUNG は3ビンテージの和集合の max（audit_hist85_today と同じ作法）なので、
    #   2013の窓に 2015/2018 で読まれた社が入る＝**look-ahead**。H4 は厳格版も併記する。
    RUNG_V = {"2013": rung_map("2013"), "2018": rung_map("2018")}
    out = {"generated": "2026-09-20", "prereg": "out/retro_mcap_prereg.json",
           "line": {"lift": LIFT, "min_numerator": MINNUM, "hurdle": HURDLE},
           "vintages": {}}

    for y, retf, f2 in ((2013, "retro_returns_2013_all", "retro_features2_2013"),
                        (2018, "retro_returns_2018", "retro_features2_2018")):
        MC = {x["ticker"]: x for x in rows(f"retro_mcap_{y}")}
        R = {x["ticker"]: x["tr_cagr"] for x in rows(retf) if x.get("tr_cagr") is not None}
        RV = {x["ticker"]: x["rev"] for x in rows(f2) if x.get("rev")}
        v = {"n_join": None, "base": None, "bases": {}}

        for basis, fld in (("eop_primary", "mcap_b"), ("wa", "mcap_wa_b"), ("eop", "mcap_eop_b")):
            J = [t for t in MC if t in R and MC[t].get(fld)]
            if not J:
                continue
            key = lambda t: MC[t][fld]
            b = {"n": len(J)}
            pb, wb, nb = p15(J, R)
            b["base_P15"] = round(pb, 4); b["winners"] = wb
            b["rho_mcap_vs_cagr"] = spearman([MC[t][fld] for t in J], [R[t] for t in J])
            # H1 中央値二分
            b["H1"] = split(J, key, R)
            # H3 五分位（相対）＋絶対Tier（記述）
            s = sorted(J, key=key); q = len(s) // 5
            quints = [s[i * q:(i + 1) * q] if i < 4 else s[4 * q:] for i in range(5)]
            b["H3_quintiles"] = []
            for i, g in enumerate(quints, 1):
                p, w, n = p15(g, R)
                b["H3_quintiles"].append({"Q": i, "n": n, "P15": round(p, 4), "w": w,
                                          "med_cagr": round(st.median(R[t] for t in g), 4),
                                          "mcap_min": round(MC[g[0]][fld], 3),
                                          "mcap_max": round(MC[g[-1]][fld], 3)})
            big = quints[3] + quints[4]; small = quints[0] + quints[1]
            pb2, wb2, _ = p15(big, R); ps2, ws2, _ = p15(small, R)
            b["H3_bigvssmall"] = {"lift": round(pb2 - ps2, 4), "P15_big": round(pb2, 4),
                                  "P15_small": round(ps2, 4), "w_big": wb2, "w_small": ws2,
                                  "monotone": all(b["H3_quintiles"][i]["P15"] <= b["H3_quintiles"][i + 1]["P15"]
                                                  for i in range(4))}
            b["H3_absolute_tier_descriptive"] = []
            for nm, lo, hi in TIER:
                g = [t for t in J if lo <= MC[t][fld] < hi]
                if not g:
                    b["H3_absolute_tier_descriptive"].append({"tier": nm, "n": 0}); continue
                p, w, n = p15(g, R)
                b["H3_absolute_tier_descriptive"].append(
                    {"tier": nm, "n": n, "P15": round(p, 4), "w": w,
                     "med_cagr": round(st.median(R[t] for t in g), 4)})
            # H2 売上3分位の中で
            JR = [t for t in J if t in RV]
            sr = sorted(JR, key=lambda t: RV[t]); k = len(sr) // 3
            ter = [sr[:k], sr[k:2 * k], sr[2 * k:]]
            b["H2_within_rev_tertile"] = []
            for i, g in enumerate(ter, 1):
                r2 = split(g, key, R)
                if r2:
                    r2["tertile"] = i; r2["rev_min_b"] = round(RV[g[0]] / 1e9, 3)
                    r2["rev_max_b"] = round(RV[g[-1]] / 1e9, 3)
                    b["H2_within_rev_tertile"].append(r2)
            b["H2_median_lift"] = (round(st.median(x["lift"] for x in b["H2_within_rev_tertile"]), 4)
                                   if b["H2_within_rev_tertile"] else None)
            # 対照: 売上そのものの中央値二分（この台帳が使ってきた物差し）
            b["ctrl_rev_split"] = split(JR, lambda t: RV[t], R)
            b["ctrl_rho_rev_vs_cagr"] = spearman([RV[t] for t in JR], [R[t] for t in JR])
            # H4 irr=85 の層の中で
            i85 = [t for t in J if RUNG.get(t) == 85]
            b["H4_irr85"] = {"n": len(i85)}
            if len(i85) >= 4:
                s4 = split(i85, key, R)
                b["H4_irr85"].update(s4 or {})
                b["H4_irr85"]["reachable"] = bool(s4 and min(s4["w_hi"], s4["w_lo"]) >= 0)
            # H4 厳格版: **そのビンテージで読まれた社だけ**（look-ahead を外す）
            rv = RUNG_V[str(y)]
            i85v = [t for t in J if rv.get(t) == 85]
            b["H4_irr85_same_vintage"] = {"n": len(i85v)}
            if len(i85v) >= 4:
                s5 = split(i85v, key, R)
                b["H4_irr85_same_vintage"].update(s5 or {})
            b["ref_by_rung_same_vintage"] = {}
            for rg in (100, 85, 70, 50):
                g = [t for t in J if rv.get(t) == rg]
                if g:
                    p, w, n = p15(g, R)
                    b["ref_by_rung_same_vintage"][str(rg)] = {
                        "n": n, "P15": round(p, 4),
                        "med_cagr": round(st.median(R[t] for t in g), 4),
                        "med_mcap_b": round(st.median(MC[t][fld] for t in g), 3)}
            # 参考: 刻み別（時価総額とは独立の対照）
            b["ref_by_rung"] = {}
            for rg in (100, 85, 70, 50):
                g = [t for t in J if RUNG.get(t) == rg]
                if g:
                    p, w, n = p15(g, R)
                    b["ref_by_rung"][str(rg)] = {"n": n, "P15": round(p, 4),
                                                 "med_cagr": round(st.median(R[t] for t in g), 4),
                                                 "med_mcap_b": round(st.median(MC[t][fld] for t in g), 3)}
            v["bases"][basis] = b
        v["n_join"] = v["bases"]["eop_primary"]["n"]
        v["base"] = v["bases"]["eop_primary"]["base_P15"]
        out["vintages"][str(y)] = v

    # ── 判定（線は prereg のまま）
    def both(path):
        got = {}
        for y in ("2013", "2018"):
            b = out["vintages"][y]["bases"]
            got[y] = {bn: path(b[bn]) for bn in ("wa", "eop") if bn in b}
        return got

    V = out["vintages"]
    def pass_h(getter, name):
        res = {"cells": {}, "verdict": None}
        ok_all = True; signs = []
        for y in ("2013", "2018"):
            for bn in ("wa", "eop"):
                b = V[y]["bases"].get(bn)
                if not b:
                    continue
                g = getter(b)
                if g is None:
                    res["cells"][f"{y}/{bn}"] = "判定不能"; ok_all = False; continue
                lift = g.get("lift"); num = min(g.get("w_hi", 0), g.get("w_lo", 0))
                res["cells"][f"{y}/{bn}"] = {"lift": lift, "numerator_min": num}
                signs.append(lift)
                if not (lift is not None and lift >= LIFT and num >= MINNUM):
                    ok_all = False
        res["sign_flip"] = bool(signs and (max(signs) > 0 > min(signs)))
        res["verdict"] = "合格" if (ok_all and not res["sign_flip"] and signs) else "不合格"
        return res

    out["verdict"] = {
        "H1": pass_h(lambda b: b["H1"], "H1"),
        "H2": pass_h(lambda b: ({"lift": b["H2_median_lift"],
                                 "w_hi": min((x["w_hi"] for x in b["H2_within_rev_tertile"]), default=0),
                                 "w_lo": min((x["w_lo"] for x in b["H2_within_rev_tertile"]), default=0)}
                                if b["H2_within_rev_tertile"] else None), "H2"),
        "H3": pass_h(lambda b: {"lift": b["H3_bigvssmall"]["lift"],
                                "w_hi": b["H3_bigvssmall"]["w_big"],
                                "w_lo": b["H3_bigvssmall"]["w_small"]}, "H3"),
        "H4": pass_h(lambda b: (b["H4_irr85"] if b["H4_irr85"].get("lift") is not None else None), "H4"),
        "H3_absolute_tier": "判定不能（事前登録どおり。T1が両ビンテージとも0社）",
    }
    json.dump(out, open("out/retro_mcap_test.json", "w"), ensure_ascii=False, indent=1)

    # ── 画面
    print("■ 事前登録 out/retro_mcap_prereg.json を一度だけ当てた（線: lift≥0.15 ∧ 分子≥5 ∧ 符号反転なし）\n")
    for y in ("2013", "2018"):
        v = V[y]
        print(f"── {y}アンカー  n={v['n_join']}  base P(年率≥15%)={v['base']}")
        for bn in ("wa", "eop"):
            b = v["bases"].get(bn)
            if not b:
                continue
            h1 = b["H1"]
            print(f"   [{bn:3}] n={b['n']:4}  ρ(mcap,年率)={b['rho_mcap_vs_cagr']:+.3f}   "
                  f"(対照 ρ(売上,年率)={b['ctrl_rho_rev_vs_cagr']:+.3f})")
            print(f"          H1 中央値二分  lift={h1['lift']:+.3f}  "
                  f"大 P15={h1['p_hi']:.3f}(勝{h1['w_hi']}) / 小 P15={h1['p_lo']:.3f}(勝{h1['w_lo']})  "
                  f"中央年率 {h1['med_hi']*100:+.1f}% / {h1['med_lo']*100:+.1f}%")
            q = b["H3_quintiles"]
            print("          H3 五分位 P15: " + " ".join(f"Q{x['Q']}={x['P15']:.3f}" for x in q)
                  + f"   単調={b['H3_bigvssmall']['monotone']}  大小lift={b['H3_bigvssmall']['lift']:+.3f}")
            print("             中央年率  : " + " ".join(f"Q{x['Q']}={x['med_cagr']*100:+.1f}%" for x in q))
            print("          H2 売上3分位の中: " + "  ".join(
                f"T{x['tertile']} lift={x['lift']:+.3f}(勝{x['w_hi']}/{x['w_lo']})" for x in b["H2_within_rev_tertile"])
                + f"   中央={b['H2_median_lift']:+.3f}")
            cr = b["ctrl_rev_split"]
            print(f"          対照 売上の中央値二分 lift={cr['lift']:+.3f}")
            h4 = b["H4_irr85"]
            print("          H4 irr=85 の中: n=%d %s" % (h4["n"],
                  (f"lift={h4['lift']:+.3f}(勝{h4['w_hi']}/{h4['w_lo']})" if h4.get("lift") is not None else "判定不能")))
            h4v = b["H4_irr85_same_vintage"]
            print("          H4厳格(同ビンテージのみ) n=%d %s" % (h4v["n"],
                  (f"lift={h4v['lift']:+.3f}(勝{h4v['w_hi']}/{h4v['w_lo']})" if h4v.get("lift") is not None else "判定不能")))
            print("          参考 刻み別(同ビンテージ) P15: " + " ".join(
                f"{k}:{x['P15']:.3f}(n{x['n']},中位mcap{x['med_mcap_b']:.1f})"
                for k, x in b["ref_by_rung_same_vintage"].items()))
            print("          参考 刻み別 P15: " + " ".join(
                f"{k}:{x['P15']:.3f}(n{x['n']},中位mcap{x['med_mcap_b']:.1f})" for k, x in b["ref_by_rung"].items()))
            print("          絶対Tier(記述): " + " ".join(
                f"{x['tier']}n{x['n']}" + (f"/P{x['P15']:.2f}" if x['n'] else "") for x in b["H3_absolute_tier_descriptive"]))
        print()
    print("■ 判定")
    for k, r in out["verdict"].items():
        if isinstance(r, str):
            print(f"   {k}: {r}"); continue
        print(f"   {k}: **{r['verdict']}**  符号反転={r['sign_flip']}  " +
              " ".join(f"{c}:{(v2 if isinstance(v2,str) else 'lift%+.3f/分子%d'%(v2['lift'],v2['numerator_min']))}"
                       for c, v2 in r["cells"].items()))
    print("\n  ⚠ 検出力（事前登録・結果の前に出した）: Δ=0.15 で 0.24〜0.49 ／ Δ≥0.20 で 0.90"
          "\n     ⇒ 不合格でも『Δ≤0.10 の効果は無い』とは書けない")
    print("■ 書き出し: out/retro_mcap_test.json")


if __name__ == "__main__":
    main()
