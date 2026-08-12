# night/filing_behavior_lefttail.py — 左尾の記述と、交絡（規模）の切り分け（2026-08-12新設）
#
# ⚠ この器は判定を下さない。主判定は night/filing_behavior_test.py（事前登録・
#    out/filing_behavior_prereg.json）で一度だけ済んでいる。
#
# ここでやること:
#   (1) 事前登録の **副次指標（左尾）** の記述。物差しはこの台帳が既に使っているもの
#       ——元本割れ率 P(tr_cagr<0) を主・恒久毀損 P(tr_cagr<=-0.15) を従
#       （out/hist_valuation_prereg_v2.json の primary_outcome_metric と同じ。ここで新しい物差しを発明しない）
#   (2) **交絡の切り分け**: 提出ラグは規模の代理ではないか。売上3分位の中で二分し直す。
#       規模（売上50億$+ → 生存 +20.8pt）は retro_capture が既に測っており、
#       規模の言い換えなら『新しい角度』ではない
#   (3) 既存4系統との相関（直交しているかの実測）
#
# **閾値の格子探索はしない。** 遮断器にするなら別の事前登録（v3）が要る＝
#   同じデータで線を探してから登録するのは、この台帳が繰り返し戒めてきた型。
#
# 実行: python3 night/filing_behavior_lefttail.py

import json
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
import sys

sys.path.insert(0, os.path.join(BASE, "night"))
from filing_behavior_test import ALL, LABEL, load, split  # noqa: E402


def tail(sub):
    n = len(sub)
    if not n:
        return None
    return {
        "n": n,
        "med": round(statistics.median(r["y"] for r in sub) * 100, 1),
        "p_neg": round(sum(1 for r in sub if r["y"] < 0) / n, 3),
        "num_neg": sum(1 for r in sub if r["y"] < 0),
        "p_imp": round(sum(1 for r in sub if r["y"] <= -0.15) / n, 3),
        "num_imp": sum(1 for r in sub if r["y"] <= -0.15),
        "p15": round(sum(1 for r in sub if r["y"] >= 0.15) / n, 3),
    }


def revmap(vint):
    if vint == 2018:
        rows = json.load(open(os.path.join(OUT, "retro_features2_2018.json")))["rows"]
        return {r["ticker"]: r.get("rev") for r in rows if r.get("rev")}
    rows = json.load(open(os.path.join(OUT, "retro_cohort_2013.json")))["rows"]
    return {r["ticker"]: r.get("rev_asof") for r in rows if r.get("ticker") and r.get("rev_asof")}


def main():
    rep = {"generated": "2026-08-12",
           "note": "判定はしない。事前登録の副次指標（左尾）の記述と、規模との切り分け。",
           "metric": "主=元本割れ率 P(tr_cagr<0)／従=恒久毀損 P(tr_cagr<=-0.15)（hist_val v2 と同じ物差し）",
           "vintages": {}}

    for vint in (2018, 2013):
        p = os.path.join(OUT, f"filing_behavior_{vint}.json")
        if not os.path.exists(p):
            continue
        _fb, rows = load(vint)
        rv = revmap(vint)
        v = {"pools": {}}
        for pname, prows in (("full", rows), ("quality", [r for r in rows if r.get("q")])):
            if len(prows) < 30:
                continue
            base = tail(prows)
            ind = {}
            for k in ALL:
                gs, miss, cut = split(prows, k)
                if not gs:
                    continue
                out = []
                for gname, sub in gs:
                    t = tail(sub)
                    if not t:
                        continue
                    t["group"] = gname
                    t["neg_ratio"] = round(t["p_neg"] / base["p_neg"], 2) if base["p_neg"] else None
                    t["imp_ratio"] = round(t["p_imp"] / base["p_imp"], 2) if base["p_imp"] else None
                    out.append(t)
                ind[k] = {"label": LABEL[k], "cut": cut, "missing": miss, "groups": out}
            v["pools"][pname] = {"base": base, "indicators": ind}

        # (2) 交絡の切り分け: 提出ラグを売上3分位の中で二分し直す
        have = [r for r in rows if r.get("lag10k") is not None and rv.get(r["t"])]
        have.sort(key=lambda r: rv[r["t"]])
        n = len(have)
        strata = {"小(下位1/3)": have[: n // 3], "中": have[n // 3: 2 * n // 3], "大(上位1/3)": have[2 * n // 3:]}
        strat = {}
        for sname, sub in strata.items():
            med = statistics.median(r["lag10k"] for r in sub)
            fast = [r for r in sub if r["lag10k"] < med]
            slow = [r for r in sub if r["lag10k"] >= med]
            strat[sname] = {"n": len(sub), "rev_range_musd": [round(rv[sub[0]["t"]] / 1e6), round(rv[sub[-1]["t"]] / 1e6)],
                            "lag_median": med, "fast": tail(fast), "slow": tail(slow)}
        v["size_stratified_lag"] = strat

        # 逆向き: ラグの半分の中で規模を二分（どちらが効いているか）
        med_lag = statistics.median(r["lag10k"] for r in have)
        inv = {}
        for lname, sub in (("速い", [r for r in have if r["lag10k"] < med_lag]),
                           ("遅い", [r for r in have if r["lag10k"] >= med_lag])):
            sub = sorted(sub, key=lambda r: rv[r["t"]])
            h = len(sub) // 2
            inv[lname] = {"n": len(sub), "小さい側": tail(sub[:h]), "大きい側": tail(sub[h:])}
        v["lag_stratified_size"] = inv

        # 規模そのものの左尾（比較用の錨）
        allrev = sorted([r for r in rows if rv.get(r["t"])], key=lambda r: rv[r["t"]])
        h = len(allrev) // 2
        v["size_alone"] = {"小さい側": tail(allrev[:h]), "大きい側": tail(allrev[h:])}

        rep["vintages"][vint] = v

    json.dump(rep, open(os.path.join(OUT, "filing_behavior_lefttail.json"), "w"), ensure_ascii=False, indent=1)

    for vint, v in rep["vintages"].items():
        print(f"\n===== {vint}年ビンテージ =====")
        for pname, p in v["pools"].items():
            b = p["base"]
            print(f"\n-- {pname}: n={b['n']} 中央値{b['med']}% 元本割れ{b['p_neg']} 恒久毀損{b['p_imp']}")
            rowsout = []
            for k in ALL:
                d = p["indicators"].get(k)
                if not d:
                    continue
                for g in d["groups"]:
                    rowsout.append((g["p_neg"], k, g))
            rowsout.sort(key=lambda x: x[0], reverse=True)
            print("   [元本割れの高い順・上位8群]")
            for pn, k, g in rowsout[:8]:
                print(f"     {LABEL[k]:<28}{g['group']:<10} n={g['n']:<4} 中央値{g['med']:>6}% "
                      f"元本割れ{g['p_neg']:.3f}({g['num_neg']}) ×{g['neg_ratio']}  毀損{g['p_imp']:.3f}({g['num_imp']})")
            print("   [元本割れの低い順・上位5群]")
            for pn, k, g in rowsout[-5:]:
                print(f"     {LABEL[k]:<28}{g['group']:<10} n={g['n']:<4} 中央値{g['med']:>6}% "
                      f"元本割れ{g['p_neg']:.3f}({g['num_neg']}) ×{g['neg_ratio']}  毀損{g['p_imp']:.3f}({g['num_imp']})")

        print("\n  [交絡の切り分け] 売上3分位の中で提出ラグを二分")
        for sname, s in v["size_stratified_lag"].items():
            f, sl = s["fast"], s["slow"]
            print(f"    {sname:<10} n={s['n']:<4} 売上{s['rev_range_musd'][0]}〜{s['rev_range_musd'][1]}百万$ ラグ中央{s['lag_median']:.0f}日")
            print(f"        速い n={f['n']:<4} 元本割れ{f['p_neg']:.3f} 毀損{f['p_imp']:.3f}({f['num_imp']}) 中央値{f['med']}%")
            print(f"        遅い n={sl['n']:<4} 元本割れ{sl['p_neg']:.3f} 毀損{sl['p_imp']:.3f}({sl['num_imp']}) 中央値{sl['med']}%")
        print("  [逆向き] ラグの半分の中で規模を二分")
        for lname, s in v["lag_stratified_size"].items():
            a, b2 = s["小さい側"], s["大きい側"]
            print(f"    {lname:<6} n={s['n']:<4} 小さい側 元本割れ{a['p_neg']:.3f} 毀損{a['p_imp']:.3f} ／ 大きい側 元本割れ{b2['p_neg']:.3f} 毀損{b2['p_imp']:.3f}")
        sa = v["size_alone"]
        print(f"  [規模そのもの] 小さい側 元本割れ{sa['小さい側']['p_neg']:.3f} 毀損{sa['小さい側']['p_imp']:.3f} ／ "
              f"大きい側 元本割れ{sa['大きい側']['p_neg']:.3f} 毀損{sa['大きい側']['p_imp']:.3f}")


if __name__ == "__main__":
    main()
