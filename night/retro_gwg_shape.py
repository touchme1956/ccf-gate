# night/retro_gwg_shape.py — 「買収の多寡 × 実現リターン」の逆U字が他のビンテージでも出るか（2026-09-21新設）
# 読み取りのみ。out/retro_gwg_vintages.json（SEC frames由来のgwg）× out/retro_returns_*.json。
# 実行: python3 night/retro_gwg_shape.py → out/retro_gwg_shape.json
import json, os, statistics as st, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RET = {2013: "retro_returns_2013_all.json", 2015: "retro_returns_2015_q.json",
       2016: "retro_returns_2016.json", 2017: "retro_returns_2017.json",
       2018: "retro_returns_2018.json", 2019: "retro_returns_2019.json",
       2020: "retro_returns_2020.json", 2021: "retro_returns_2021.json"}


def L(p):
    d = json.load(open(os.path.join(BASE, "out", p)))
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


def med(v):
    return st.median(v) if v else None


def main():
    G = json.load(open(os.path.join(BASE, "out/retro_gwg_vintages.json")))["gwg"]
    out = {}
    print("%-6s %5s  %-22s %-22s %-22s %-22s  %s" % ("年", "n", "Q1 買収しない", "Q2 控えめ", "Q3", "Q4 大きく買う", "順位"))
    for v in sorted(RET, key=int):
        g = G.get(str(v)) or {}
        if len(g) < 100:
            print("%-6d %5d  ← XBRLの被覆が薄く検定不能（基準年 %d）" % (v, len(g), v - 5))
            out[str(v)] = {"n": len(g), "skipped": "xbrl_coverage"}
            continue
        R = {r["ticker"]: r for r in L(RET[v]) if not r.get("stale") and r.get("tr_cagr") is not None}
        pr = sorted((gv, R[t]["tr_cagr"]) for t, gv in g.items() if t in R)
        n = len(pr)
        qs = [pr[i * n // 4:(i + 1) * n // 4] for i in range(4)]
        ms = [100 * med([x[1] for x in q]) for q in qs]
        rank = sorted(range(4), key=lambda i: -ms[i])
        out[str(v)] = {"n": n, "years": L(RET[v])[0].get("years"),
                       "cuts": [round(q[0][0], 4) for q in qs] + [round(qs[-1][-1][0], 4)],
                       "median_cagr_pct": [round(m, 1) for m in ms],
                       "best": rank[0] + 1, "worst": rank[3] + 1,
                       "q2_best": rank[0] == 1, "q1_worst": rank[3] == 0}
        print("%-6d %5d  %-22s %-22s %-22s %-22s  最良Q%d 最悪Q%d" % (
            v, n, *["%.2f..%.2f  %.1f%%" % (q[0][0], q[-1][0], m) for q, m in zip(qs, ms)],
            rank[0] + 1, rank[3] + 1))
    ok = [o for o in out.values() if "median_cagr_pct" in o]
    print("\nQ2(控えめ)が最良: %d / %d ビンテージ" % (sum(1 for o in ok if o["q2_best"]), len(ok)))
    print("Q1(買収しない)が最悪: %d / %d" % (sum(1 for o in ok if o["q1_worst"]), len(ok)))
    print("⚠ 2016-2021 は母集団も窓も重なる（独立ではない）。独立に近いのは 2015 と 2018/2021 の端だけ")
    p = os.path.join(BASE, "out/retro_gwg_shape.json")
    json.dump({"generated": datetime.date.today().isoformat(), "vintages": out},
              open(p, "w"), ensure_ascii=False, indent=1)
    print("→", p)


if __name__ == "__main__":
    main()
