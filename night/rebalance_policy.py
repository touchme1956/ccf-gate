#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rebalance_policy.py — 積立のとき、比率の戻し方で成績は変わるか（2026-10-01・ユーザーの問い
「積み立てした場合の比率の調整をどうするべきか。また値上がりした場合の調整もいるのか」）

ETF側の中（QQQ 75 : SMH 25 ＝ iFreeNEXT NASDAQ100 60 : SMH 20 を80へ広げた比）を、毎月同額で積み立てるとき、
4つの戻し方を同じ月次リターン（配当込み・ドル・QQQ と SMH の共通の月 2000-07→）で比べる:
  fixed    固定比率積立 … 毎月 75:25 に分けて買うだけ。保有は放置（値上がりでずれても何もしない）
  newmoney 不足から買う … 毎月の入金を、目標比より足りないほうへ先に回す（売らない）＝門の買付順位の割り方（name/gap）と同じ考え方
  monthly  毎月リバランス … 毎月 75:25 へ売買して戻す（売却あり）
  annual   年1回リバランス … 毎年1月に 75:25 へ売買して戻す（売却あり）
出すもの: 転がる10/15/20年窓での「最終資産÷fixed の最終資産」（中央・最悪・最良）と、終わりの SMH 比率、全期間の最大下落。
⚠ 売却ありの2本は課税・手数料・NISA枠の損を引いていない（引けば不利になる）。2000-2026 は SMH が勝った一つの時代で、
  負ける資産を持つと結論の向きは変わりうる。読むだけ（門・配分に不使用）。出力: out/rebalance_policy.json
"""
import json
import os
import statistics as S
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
import nx_common as N  # noqa: E402

W = {"Q": 0.75, "S": 0.25}
POLICIES = ["fixed", "newmoney", "monthly", "annual"]


def run(policy, months, R, c=1.0):
    hold = {"Q": 0.0, "S": 0.0}
    path, contrib = [], 0.0
    for m in months:
        if policy == "fixed":
            for a in hold:
                hold[a] += c * W[a]
        elif policy == "newmoney":
            V = sum(hold.values()) + c
            need = {a: max(0.0, W[a] * V - hold[a]) for a in hold}
            s = sum(need.values())
            for a in hold:
                hold[a] += c * need[a] / s if s > 0 else c * W[a]
        else:                                            # monthly / annual: 買ってから目標へ売買して戻す
            for a in hold:
                hold[a] += c * W[a]
            if policy == "monthly" or m % 100 == 1:
                V = sum(hold.values())
                for a in hold:
                    hold[a] = W[a] * V
        contrib += c
        for a in hold:
            hold[a] *= 1 + R[a][m]
        path.append((sum(hold.values()), contrib, dict(hold)))
    return path


def mdd(path):
    pk, dd = 0.0, 0.0
    for v, _c, _h in path:
        pk = max(pk, v)
        dd = min(dd, v / pk - 1)
    return dd


def selftest():
    """両方の資産が同じ値動きなら、4つの戻し方は同じ最終資産になる（実装の検算）"""
    months = [200001 + i + (i // 12) * 88 for i in range(60)]
    r = {m: 0.01 * ((i % 5) - 2) for i, m in enumerate(months)}
    R = {"Q": r, "S": r}
    fin = [run(p, months, R)[-1][0] for p in POLICIES]
    assert max(fin) - min(fin) < 1e-9, fin
    # 投入額は全方針で同じ
    assert len({run(p, months, R)[-1][1] for p in POLICIES}) == 1


def main():
    selftest()
    q, h = N.yahoo("QQQ"), N.yahoo("SMH")
    R = {"Q": q, "S": h}
    ks = sorted(set(q) & set(h))
    out = {"why": "積立の比率の戻し方で成績は変わるか（ETF側の中 QQQ75:SMH25・毎月同額・配当込みドル）", "months": [ks[0], ks[-1], len(ks)],
           "policies": {"fixed": "固定比率積立（放置）", "newmoney": "不足から買う（売らない）", "monthly": "毎月リバランス（売却あり・課税前）",
                        "annual": "年1回リバランス（売却あり・課税前）"}, "windows": {}, "full": {}}
    for yrs in (10, 15, 20):
        n = yrs * 12
        ratio = {p: [] for p in POLICIES}
        smh = {p: [] for p in POLICIES}
        for i in range(0, len(ks) - n + 1, 6):
            w = ks[i:i + n]
            res = {p: run(p, w, R) for p in POLICIES}
            for p in POLICIES:
                ratio[p].append(res[p][-1][0] / res["fixed"][-1][0])
                fin = res[p][-1][2]
                smh[p].append(fin["S"] / sum(fin.values()))
        out["windows"][f"{yrs}y"] = {"n": len(ratio["fixed"]), **{
            p: {"median": round(S.median(ratio[p]), 4), "worst": round(min(ratio[p]), 4), "best": round(max(ratio[p]), 4),
                "smh_share_median": round(S.median(smh[p]), 3), "smh_share_max": round(max(smh[p]), 3)} for p in POLICIES}}
    for p in POLICIES:
        pa = run(p, ks, R)
        v, c, hh = pa[-1]
        out["full"][p] = {"final_over_contrib": round(v / c, 2), "max_drawdown": round(mdd(pa), 4), "smh_share_end": round(hh["S"] / v, 3)}
    p = os.path.join(BASE, "out", "rebalance_policy.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    print("→", p)
    for y, blk in out["windows"].items():
        print(y, blk["n"], {k: (v["median"], v["worst"], v["smh_share_max"]) for k, v in blk.items() if k != "n"})
    print("全期間", out["full"])


if __name__ == "__main__":
    main()
