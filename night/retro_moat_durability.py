#!/usr/bin/env python3
# night/retro_moat_durability.py — 「壊れない複利」の軸で堀のラベルを測る（2026-08-06新設）
#
# 発端: ユーザーの指示「最大の勝者はいらないので壊れない高い複利を目指す」。
#       それまでの集計は**平均リターン**（外れ値が支配する）で見ていたが、この目的なら
#       見るべきは **中央値・元本割れ率・恒久毀損率・最悪値** である。軸を変えると結論が変わる。
#
# 実測でわかったこと（2013+2015ビンテージ・542件）:
#   ・**質実証（営業利益率10%+ ∧ 5年FCF全年黒字 ∧ 営業利益全年黒字）は単独で無力**
#       P(年率15%+)=0.213 vs ベース0.221。リフトはゼロ。
#   ・**irr=85 に質実証を足すと恒久毀損が増える**（0.10 → 0.14）。
#       質のふるいは最大の勝者 LRCX（当時 営利率3.3%・ROIC3.7%・門0スコア2/7、その後13年で75倍）を
#       落とす一方、**壊れた CMTL（元本0.08倍）は素通りさせる**（当時 営利率10.8%・FCF全年黒字）。
#   ・唯一 CMTL を止めたのは **「認定するのが第三者か（mech≠B設計組込）」**。
#       この群は n=9 で元本割れ0・恒久毀損0・最悪でも+6.0%/年。ただし n=9 の0件＝真のゼロではない。
#   ・全542件では **irr=70 の恒久毀損率が 2%**（全体8%・irr=50は9%）＝
#       「上を狙う」なら85だが、「下を防ぐ」なら**70で足り、標本は10倍厚い**。
#
# **規約は何も変えていない**——これは較正の記録であり、刻み・重み・関門は不変。
# 実行: python3 night/retro_moat_durability.py
# 出力: out/retro_moat_durability.json
import json, os, statistics, math

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
HURDLE = 0.15


def L(n):
    return json.load(open(os.path.join(OUT, n), encoding="utf-8"))["rows"]


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)


def build():
    R13 = {r["ticker"]: r for r in L("retro_returns_2013_all.json")}
    R15 = {r["ticker"]: r for r in L("retro_returns_2015_q.json")}
    C13 = {r["ticker"]: r for r in L("retro_cohort_2013.json") if r.get("ticker")}
    C15 = {r["ticker"]: r for r in L("retro_cohort_2015.json") if r.get("ticker")}
    m13 = {r["ticker"]: r for r in L("retro_moat_2013.json") + L("retro_moat_2013q.json")}
    # ⚠2026-08-12是正: `retro_moat_2015qb.json`(212社・うち irr=85 が9社) が読まれていなかった。
    #   この器は 2026-08-06 に作られ、同じ日に「2015を検出力に到達するまで読み切る」で足された
    #   qb が配線されないまま残っていた＝**作った答えを捨てていた**（この repo の常習の型）。
    #   実害: irr=85 の n が 10 のままで、base_rate_check が引く基礎率がその上に載っていた
    m15 = {r["ticker"]: r for r in
           L("retro_moat_2015.json") + L("retro_moat_2015q.json") + L("retro_moat_2015qb.json")}
    A = []
    for mm, RR, CC, v in ((m13, R13, C13, 2013), (m15, R15, C15, 2015)):
        for t, r in mm.items():
            x = RR.get(t)
            if not x or x.get("tr_cagr") is None:
                continue
            A.append({**r, "tr": x["tr_cagr"], "mdd": x.get("mdd"), "tot": x.get("tr_total"),
                      "v": v, "c": CC.get(t, {})})
    return A


def Q(r):
    c = r["c"]
    return (c.get("opm") or -9) >= 0.10 and c.get("fcf_all_pos") and c.get("op_all_pos")


def stat(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    tr = [r["tr"] for r in rows]
    k = sum(1 for x in tr if x >= HURDLE)
    lo, hi = wilson(k, n)
    return {"n": n, "P15": round(k / n, 3), "CI": [lo, hi],
            "median": round(statistics.median(tr), 4),
            "mean": round(statistics.mean(tr), 4),
            "worst": round(min(tr), 4),
            "元本割れ": round(sum(1 for r in rows if (r["tot"] or 9) < 1.0) / n, 3),
            "恒久毀損": round(sum(1 for r in rows if (r["tot"] or 9) < 0.5) / n, 3),
            "平均DD": round(statistics.mean(r["mdd"] for r in rows if r.get("mdd") is not None), 3)}


THIRD = ("A工程認定", "C第三者が用途を認定", "D認定業者名簿", "E長期認定期間")


def main():
    A = build()
    g = [r for r in A if r.get("irr") == 85]
    cuts = {
        "全体": A,
        "質実証のみ": [r for r in A if Q(r)],
        "irr=50": [r for r in A if r.get("irr") == 50],
        "irr=70": [r for r in A if r.get("irr") == 70],
        "irr=85": g,
        "irr=85 ∧ 質実証": [r for r in g if Q(r)],
        "irr=85 ∧ 第三者が認定": [r for r in g if r.get("mech") in THIRD],
        "irr=85 ∧ moat5>=4": [r for r in g if (r.get("moat5") or 0) >= 4],
        "irr=70+85 ∧ 第三者が認定": [r for r in A if r.get("irr") in (70, 85) and r.get("mech") in THIRD],
    }
    o = {"generated": "2026-08-06", "hurdle": HURDLE, "n_total": len(A),
         "note": "『壊れない複利』の軸＝中央値・元本割れ・恒久毀損・最悪値。平均は外れ値が支配するので主役にしない",
         "groups": {k: stat(v) for k, v in cuts.items()}}
    print(f"{'群':26}{'n':>5}{'中央値':>9}{'勝率':>7}{'元本割れ':>9}{'恒久毀損':>9}{'最悪':>9}")
    for k, v in o["groups"].items():
        if v["n"]:
            print(f"{k:26}{v['n']:>5}{v['median']:>+9.1%}{v['P15']:>7.2f}"
                  f"{v['元本割れ']:>9.2f}{v['恒久毀損']:>9.2f}{v['worst']:>+9.1%}")
    # 壊れた社が、どのふるいで止まったか
    broken = [r for r in A if (r["tot"] or 9) < 0.5 and r.get("irr") == 85]
    o["broken_in_85"] = [{"v": r["v"], "t": r["ticker"], "tot": r["tot"], "tr": round(r["tr"], 4),
                          "mech": r.get("mech"), "moat5": r.get("moat5"),
                          "止まるふるい": {"質実証": not Q(r),
                                    "第三者が認定": r.get("mech") not in THIRD,
                                    "moat5>=4": (r.get("moat5") or 0) < 4,
                                    "売上5年CAGR>0": (r["c"].get("sales_cagr5") or -9) <= 0}} for r in broken]
    print("\n■ irr=85 で壊れた社と、それを止めたふるい")
    for b in o["broken_in_85"]:
        ok = [k for k, v in b["止まるふるい"].items() if v]
        print(f"  {b['v']} {b['t']:6} 元本{b['tot']:.2f}倍 mech={b['mech']} → 止まる: {ok or '（どのふるいでも止まらない）'}")
    p = os.path.join(OUT, "retro_moat_durability.json")
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {p}")


if __name__ == "__main__":
    main()
