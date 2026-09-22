#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""out/tsumitate_funds.json を「信託報酬」と「実際に残った額」の二軸で並べる。

同じ指数を追う群の中では、基準価額の騰落率の差は**そのまま手取りの差**になる。
だから読む順は (1)同じ窓・同じ基準日で年率換算し (2)群の最良からの差を出し
(3)その差のうち**信託報酬で説明できる分と、できない分**を分ける。

⚠ 群の切り方: 金融庁の一覧は「MSCI ACWI Index」の一語に
  **オール・カントリー(日本含む)** と **除く日本** を混ぜている。別の指数なので必ず分ける。
⚠ 窓は None を埋めない。設定が新しい社は長い窓を持たない（＝比較に出さない・絶対のルール7）。
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "out", "tsumitate_funds.json")

WIN = [("standardPriceRa1y", 1), ("standardPriceRa3y", 3), ("standardPriceRa5y", 5), ("standardPriceRa10y", 10)]


def F(v):
    if v in (None, "", "-", "-/-"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ann(total_pct, years):
    """騰落率(%)→年率(%)。"""
    if total_pct is None:
        return None
    return ((1.0 + total_pct / 100.0) ** (1.0 / years) - 1.0) * 100.0


def group_of(r):
    if r["idx"] == "S&P500":
        return "S&P500"
    exj = ("除く日本" in r["届出名"]) or ("外国株" in r["届出名"]) or ("全海外株" in r["届出名"])
    return "MSCI ACWI (除く日本)" if exj else "MSCI ACWI (オール・カントリー)"


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    for r in rows:
        r["group"] = group_of(r)
        r["信託報酬_税込"] = round(F(r["trustReward"]) * 1.1, 4) if F(r["trustReward"]) is not None else None
        r["年率"] = {f"{y}y": (None if ann(F(r[k]), y) is None else round(ann(F(r[k]), y), 3)) for k, y in WIN}

    analysis = {}
    for g in ["S&P500", "MSCI ACWI (オール・カントリー)", "MSCI ACWI (除く日本)"]:
        sub = [r for r in rows if r["group"] == g]
        ga = {"n": len(sub), "窓": {}}
        for _, y in WIN:
            w = f"{y}y"
            have = [r for r in sub if r["年率"][w] is not None]
            if len(have) < 2:
                ga["窓"][w] = {"n": len(have), "note": "比較に足りない（この窓を持つ社が2本未満）"}
                continue
            best = max(have, key=lambda r: r["年率"][w])
            recs = []
            for r in sorted(have, key=lambda r: -r["年率"][w]):
                drag = round(best["年率"][w] - r["年率"][w], 3)           # 実際に減った分(pt/年)
                fee = round(r["信託報酬_税込"] - best["信託報酬_税込"], 4)  # 費用の差(pt/年)
                recs.append({"nm": r["届出名"], "信託報酬_税込": r["信託報酬_税込"],
                             "年率": r["年率"][w], "最良との差": drag,
                             "うち信託報酬で説明": fee, "説明できない差": round(drag - fee, 3),
                             "純資産_億円": round(F(r["totalNetAssets"]) / 100),
                             "設定": r["establishedDate"][:7]})
            # 1pt の信託報酬が年率を何pt削ったか（最小二乗の傾き）
            xs = [r["信託報酬_税込"] for r in have]
            ys = [r["年率"][w] for r in have]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx) if sxx else None
            ga["窓"][w] = {"n": len(have), "最良": best["届出名"],
                           "信託報酬1ptあたりの年率の変化": (None if slope is None else round(slope, 3)),
                           "行": recs}
        analysis[g] = ga

    # 純資産の規模と「説明できない差」の関係（1y・全群を合わせて）
    import math
    pairs = []
    for ga in analysis.values():
        wa = ga["窓"].get("1y") or {}
        for r in wa.get("行", []):
            pairs.append((max(r["純資産_億円"], 1), r["説明できない差"]))
    size = None
    if len(pairs) > 3:
        xs = [math.log10(a) for a, _ in pairs]
        ys = [b for _, b in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in ys)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        med = lambda v: sorted(v)[len(v) // 2] if v else None
        size = {"n": len(pairs),
                "傾き(log10純資産→説明できない差)": round(sxy / sxx, 4) if sxx else None,
                "r": round(sxy / math.sqrt(sxx * syy), 3) if sxx and syy else None,
                "説明できない差の中央値": {
                    "純資産100億未満": med([b for a, b in pairs if a < 100]),
                    "100〜1000億": med([b for a, b in pairs if 100 <= a < 1000]),
                    "1000億以上": med([b for a, b in pairs if a >= 1000])},
                "⚠": "r=-0.3台＝弱い相関。規模は保証ではない（2152億でも0.186pt/年の社がある）"}

    d["★分析"] = {
        "generated": time.strftime("%Y-%m-%d"),
        "tool": "night/rank_tsumitate.py",
        "規模と連動": size,
        "読み方": [
            "「最良との差」は群の最良からの年率の差(pt/年)＝20年の複利に毎年効く。",
            "「うち信託報酬で説明」は名目の費用差。「説明できない差」は連動のズレ・売買コスト・二重構造などの残り。",
            "窓ごとに母数が違う（設定が新しい社は長い窓を持たない）。窓をまたいで順位を比べない。",
        ],
        "群": analysis,
    }
    json.dump(d, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for g, ga in analysis.items():
        print(f"\n════ {g}  n={ga['n']}")
        for w, wa in ga["窓"].items():
            if "行" not in wa:
                continue
            print(f"  ── {w}（{wa['n']}本）最良={wa['最良']}  傾き={wa['信託報酬1ptあたりの年率の変化']}")
            print(f"     {'税込%':>7} {'年率%':>7} {'差':>6} {'=費用':>7} {'+説明不能':>8}  {'純億':>6}  名前")
            for r in wa["行"]:
                print(f"     {r['信託報酬_税込']:7.4f} {r['年率']:7.3f} {r['最良との差']:6.3f} {r['うち信託報酬で説明']:7.4f} {r['説明できない差']:8.3f}  {r['純資産_億円']:6d}  {r['nm']}")
    print(f"\n→ {SRC} の ★分析 を更新", file=sys.stderr)


if __name__ == "__main__":
    main()
