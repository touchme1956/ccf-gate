# night/retro_v4_conditional.py — 条件付きの問い（★事後の探索・事前登録に無い）
#
# ⚠ **これは合格・不合格を出す器ではない。** 事前登録 v4（out/retro_v4_prereg.json）の判定は
#    night/retro_v4_test.py が一度だけ済ませてあり、主判定3本・探索204通りとも**不合格**。
#    ここはその後に立てた**事後の問い**で、結論にはしない（別の事前登録で未見のデータに当て直す対象）。
#
# 問い: 「**年率15%+を出した社の中で**、浅い谷で済んだ社と深い谷を掘った社を、入口の指標は分けられるか」
#   理由: v4 の主判定で robust が deep の**完全な部分集合**（重なり＝robust の全数）と判り、
#         deep 201社のうち robust は129社。両群の**年率の中央値はほぼ同じ（0.216 vs 0.221）**で、
#         違うのは**最大DDだけ（−0.41 vs −0.63）**。つまり結果変数の作り直しは
#         「谷の深さ」という次元を確かに分離した。ならばその次元だけを直接問うべき。
#
# ⚠ 解釈上の最大の注意: robust の条件に「最大DDが浅い」が入っており、
#   ボラティリティ（ivol/vol/dsd）や過去DD（mdd5/worst12）は**将来のボラを予言する自己相関**を持つ。
#   だからこれらの lift は「事業の性質を当てた」のではなく**同じ量の過去と未来を突き合わせている**
#   に近い。事業の性質を見たいなら会計側（conv5 / netiss_r / intcov / NT）のほうを読むこと。
#
# 実行: python3 night/retro_v4_conditional.py  → out/retro_v4_conditional.json

import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
from retro_v4_test import (  # noqa: E402
    load, ANCHORS, FUND, SHAPE, FEAT2, PATH, FILING, groups, LIFT, MIN_NUM,
)

FAMS = [("新:会計", FUND), ("新:分布の形", SHAPE), ("既:財務比率", FEAT2),
        ("既:値動き", PATH), ("既:提出behavior", FILING)]
MIN_N = 20


def main():
    data = {a: load(a) for a in ANCHORS}
    acc, bases = {}, {}
    for a in ANCHORS:
        rows = [r for r in data[a] if r["deep"]]        # 高リターン組だけ
        base = sum(1 for r in rows if r["robust"]) / len(rows)
        bases[a] = {"n_deep": len(rows), "p_shallow_given_deep": round(base, 3)}
        for fam, keys in FAMS:
            for k in keys:
                gs, cut, _m = groups(rows, k)
                if not gs:
                    continue
                for side, sub in gs.items():
                    n = len(sub)
                    if n < MIN_N:
                        continue
                    num = sum(1 for r in sub if r["robust"])
                    acc.setdefault(f"{fam}|{k}|{side}", []).append(
                        {"asof": a, "n": n, "num": num, "p": round(num / n, 3),
                         "lift": round(num / n - base, 3), "base": round(base, 3)})
    rows_out = []
    for key, v in acc.items():
        if len(v) < len(ANCHORS):
            continue
        lifts = [x["lift"] for x in v]
        fam, k, side = key.split("|")
        rows_out.append({
            "family": fam, "indicator": k, "side": side, "per_vintage": v,
            "min_lift": min(lifts), "max_lift": max(lifts),
            "all_positive": all(x > 0 for x in lifts),
            "all_negative": all(x < 0 for x in lifts),
            # 事前登録の線をそのまま当てたらどうなるか（**合格の意味は持たない**）
            "would_pass_if_registered": bool(all(x >= LIFT for x in lifts)
                                             and all(y["num"] >= MIN_NUM for y in v)),
        })
    rows_out.sort(key=lambda r: -r["min_lift"])
    out = {"generated": "2026-08-12",
           "status": "★事後の探索。合格ではない。結論にしない",
           "question": "年率15%+を出した社の中で、浅い谷で済んだ社と深い谷を掘った社を入口の指標は分けられるか",
           "caveat": "robust は『最大DDが浅い』を含むので、ボラ・過去DD系の lift は自己相関に近い。"
                     "事業の性質を読むなら会計側を見ること",
           "base": bases, "n_cells": len(rows_out), "rows": rows_out}
    json.dump(out, open(os.path.join(BASE, "out", "retro_v4_conditional.json"), "w"),
              ensure_ascii=False, indent=1)

    print("★事後の探索（合格ではない）: 年率15%+の中で、谷の深さを分けるもの")
    for a in ANCHORS:
        b = bases[a]
        print(f"  {a}: 年率15%+ は {b['n_deep']}社、そのうち浅い谷で済んだのは {b['p_shallow_given_deep']}")
    print("\n  3ビンテージすべて正の lift（上位10）  ※参考: 事前登録の線は +0.15")
    for r in [x for x in rows_out if x["all_positive"]][:10]:
        mark = "◇線を満たす" if r["would_pass_if_registered"] else ""
        print(f"    {r['family']:<14}{r['indicator']:<11}{r['side']}  "
              f"lift={[x['lift'] for x in r['per_vintage']]} n={[x['n'] for x in r['per_vintage']]} {mark}")
    print("\n  3ビンテージすべて負の lift（逆向きに強い・上位5）")
    for r in sorted([x for x in rows_out if x["all_negative"]], key=lambda r: r["max_lift"])[:5]:
        print(f"    {r['family']:<14}{r['indicator']:<11}{r['side']}  "
              f"lift={[x['lift'] for x in r['per_vintage']]} n={[x['n'] for x in r['per_vintage']]}")


if __name__ == "__main__":
    main()
