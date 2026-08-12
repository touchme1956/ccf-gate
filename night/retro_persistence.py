# night/retro_persistence.py — 「複利15%+」は会社の性質か、それとも抽選か（2026-08-12新設）
#
# ★この器は**予言子を探す器ではない**。**予言可能性の上限**そのものを測る。
#
#   この台帳は13年ぶん「入口の指標で年率15%+を当てられるか」を検証し、一度も当てられていない。
#   これまで疑ってきたのは**方法**（指標の選び方・分割の仕方・検出力）だった。
#   だが疑うべきものがもう一つある——**結果変数のほうが、そもそも会社の安定した性質なのか**。
#   もし「3年で年率15%+」がほぼ抽選なら、**どんな完璧な予言子でも当てられない**。
#   その上限を、指標を一つも使わずに測るのがこの器。
#
# 測るもの:
#   ① 重ならない4窓（各約3年）の勝敗分布を、**独立抽選（ポアソン二項）の期待値**と比べる
#   ② 連続する窓での持続 P(次も勝|勝) − ベース
#   ③ 分散分解と級内相関 ICC ＝ 1窓の観測から会社の真の実力をどれだけ推せるか
#   ④ **後知恵を除いた上限**: 他の窓の実績（どんな指標より強い情報）で選び、残り1窓で測る
#   ⑤ 窓の長さを変えたときに持続性が上がるか（12/24/36/48/60/78ヶ月）
#   ⑥ **対比**: 事業の実力（ROIC）の持続 vs 株価リターンの持続
#
# データ: out/retro_monthly_{2013_2018,2018_2026}.json を連結（952社・2013-07〜2026-08）＋
#         out/retro_cohort_2013.json（入口ROICと前方ROIC）＋ out/retro_returns_2013_all.json
#         ＝**追加取得ゼロ**
#
# ⚠ 限界: 母集団は今日ティッカーが引ける社（生存バイアス・既記録）／窓が長いほど独立な窓の数が減り
#   ICC・持続の推定が不安定になる（78ヶ月は2窓しかない＝実質ただの相関）／
#   adjclose は取得日基準の調整値だが、窓内の比は乗法調整で不変
#
# 実行: python3 night/retro_persistence.py [--json]

import datetime
import json
import os
import statistics
import sys
from itertools import product

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
HURDLE = 0.15


def ymk(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)


def panel():
    p = {}
    for f in ("retro_monthly_2013_2018.json", "retro_monthly_2018_2026.json"):
        for t, s in json.load(open(os.path.join(OUT, f))).items():
            m = p.setdefault(t, {})
            for ts, px in s:
                if px and px > 0:
                    k = ymk(ts)
                    if k not in m:      # 同一年月は最初のバー
                        m[k] = px
    return p


def cagr(m, k0, k1, minm=24):
    ks = [k for k in sorted(m) if k0 <= k <= k1]
    if len(ks) < minm:
        return None
    p0, p1 = m[ks[0]], m[ks[-1]]
    y = (ks[-1] - ks[0]) / 12
    return (p1 / p0) ** (1 / y) - 1 if p0 > 0 and y > 0 else None


def spearman(a, b):
    n = len(a)
    ra = sorted(range(n), key=lambda i: a[i])
    rb = sorted(range(n), key=lambda i: b[i])
    p = [0] * n
    q = [0] * n
    for r, i in enumerate(ra):
        p[i] = r
    for r, i in enumerate(rb):
        q[i] = r
    return statistics.correlation(p, q)


def icc_and_var(R, common):
    """R = [ {t: ret}, ... ] 窓ごと。分散分解と級内相関。"""
    nw = len(R)
    gm = statistics.mean(r[t] for r in R for t in common)
    cmean = {t: statistics.mean(r[t] for r in R) for t in common}
    wmean = [statistics.mean(r[t] for t in common) for r in R]
    ss_tot = sum((r[t] - gm) ** 2 for r in R for t in common)
    ss_c = sum(nw * (cmean[t] - gm) ** 2 for t in common)
    ss_w = sum(len(common) * (w - gm) ** 2 for w in wmean)
    ss_e = ss_tot - ss_c - ss_w
    ms_c = ss_c / (len(common) - 1)
    ms_e = ss_e / max(1, (len(common) - 1) * (nw - 1))
    den = ms_c + (nw - 1) * ms_e
    return {"share_company": ss_c / ss_tot, "share_window": ss_w / ss_tot,
            "share_resid": ss_e / ss_tot, "icc": (ms_c - ms_e) / den if den else 0.0}


def main():
    as_json = "--json" in sys.argv
    P = panel()
    K0 = 2013 * 12 + 6
    KEND = max(x for m in P.values() for x in m)
    rep = {"generated": "2026-08-12",
           "question": "『複利15%+』は会社の安定した性質か、それとも抽選か（予言可能性の上限）",
           "note": "予言子を探す器ではない。指標を一つも使わずに上限を測る"}

    # ---- ① 重ならない4窓 ----
    W = [(K0, 2016 * 12 + 5, "W1 2013-07→2016-06"), (2016 * 12 + 6, 2019 * 12 + 5, "W2 2016-07→2019-06"),
         (2019 * 12 + 6, 2022 * 12 + 5, "W3 2019-07→2022-06"), (2022 * 12 + 6, KEND, "W4 2022-07→2026-08")]
    R, labs = [], []
    for k0, k1, lab in W:
        d = {t: cagr(m, k0, k1) for t, m in P.items()}
        R.append({t: v for t, v in d.items() if v is not None})
        labs.append(lab)
    common = sorted(set.intersection(*[set(r) for r in R]))
    base = [sum(1 for t in common if r[t] >= HURDLE) / len(common) for r in R]
    exp = [0.0] * 5
    for bits in product([0, 1], repeat=4):
        pr = 1.0
        for i, b in enumerate(bits):
            pr *= base[i] if b else (1 - base[i])
        exp[sum(bits)] += pr * len(common)
    cnt = {}
    for t in common:
        w = sum(1 for r in R if r[t] >= HURDLE)
        cnt[w] = cnt.get(w, 0) + 1
    rep["four_windows"] = {
        "n": len(common), "labels": labs, "base": [round(b, 3) for b in base],
        "wins_observed": {str(w): cnt.get(w, 0) for w in range(5)},
        "wins_expected_if_independent": {str(w): round(exp[w], 1) for w in range(5)},
        "ratio": {str(w): round(cnt.get(w, 0) / exp[w], 2) if exp[w] else None for w in range(5)},
    }
    rep["persistence_pairs"] = []
    for i in range(3):
        win = [t for t in common if R[i][t] >= HURDLE]
        p = sum(1 for t in win if R[i + 1][t] >= HURDLE) / len(win)
        lose = [t for t in common if R[i][t] < HURDLE]
        pl = sum(1 for t in lose if R[i + 1][t] >= HURDLE) / len(lose)
        rep["persistence_pairs"].append({
            "from": labs[i], "to": labs[i + 1], "n_win": len(win),
            "p_next_given_win": round(p, 3), "p_next_given_lose": round(pl, 3),
            "base": round(base[i + 1], 3), "lift": round(p - base[i + 1], 3)})
    rep["variance"] = {k: round(v, 4) for k, v in icc_and_var(R, common).items()}

    # ---- ④ 後知恵を除いた上限 ----
    loo = []
    for i, lab in enumerate(labs):
        est = {t: statistics.mean(R[j][t] for j in range(4) if j != i) for t in common}
        rk = sorted(common, key=lambda t: -est[t])
        b = base[i]
        for frac in (0.1, 0.2):
            g = rk[:int(len(common) * frac)]
            p = sum(1 for t in g if R[i][t] >= HURDLE) / len(g)
            loo.append({"target": lab, "select_top": f"{int(frac*100)}%", "n": len(g),
                        "p": round(p, 3), "base": round(b, 3), "ratio": round(p / b, 2)})
    rep["leave_one_out_ceiling"] = loo

    # ---- ⑤ 窓の長さ ----
    by_len = []
    for months in (12, 24, 36, 48, 60, 78):
        edges, k = [], K0
        while k + months - 1 <= KEND:
            edges.append((k, k + months - 1))
            k += months
        if len(edges) < 2:
            continue
        Rm = []
        for k0, k1 in edges:
            d = {t: cagr(m, k0, k1, minm=max(6, months // 3)) for t, m in P.items()}
            Rm.append({t: v for t, v in d.items() if v is not None})
        cm = sorted(set.intersection(*[set(r) for r in Rm]))
        if len(cm) < 200:
            continue
        bs = [sum(1 for t in cm if r[t] >= HURDLE) / len(cm) for r in Rm]
        lifts = []
        for i in range(len(Rm) - 1):
            win = [t for t in cm if Rm[i][t] >= HURDLE]
            if win:
                lifts.append(sum(1 for t in win if Rm[i + 1][t] >= HURDLE) / len(win) - bs[i + 1])
        allwin = sum(1 for t in cm if all(r[t] >= HURDLE for r in Rm))
        e = len(cm)
        for b in bs:
            e *= b
        by_len.append({"months": months, "n_windows": len(edges), "n": len(cm),
                       "base_mean": round(statistics.mean(bs), 3),
                       "persistence_lift_mean": round(statistics.mean(lifts), 3) if lifts else None,
                       "icc": round(icc_and_var(Rm, cm)["icc"], 3),
                       "all_win_observed": allwin, "all_win_expected": round(e, 1)})
    rep["by_window_length"] = by_len

    # ---- 重ならない2つの長い窓 ----
    half = (KEND - K0) // 2
    ra = {t: v for t, v in ((t, cagr(m, K0, K0 + half, 40)) for t, m in P.items()) if v is not None}
    rb = {t: v for t, v in ((t, cagr(m, K0 + half + 1, KEND, 40)) for t, m in P.items()) if v is not None}
    c = sorted(set(ra) & set(rb))
    ba = sum(1 for t in c if ra[t] >= HURDLE) / len(c)
    bb = sum(1 for t in c if rb[t] >= HURDLE) / len(c)
    win = [t for t in c if ra[t] >= HURDLE]
    rep["two_long_halves"] = {
        "n": len(c), "years_each": round(half / 12, 2),
        "base_first": round(ba, 3), "base_second": round(bb, 3),
        "p_second_given_first_win": round(sum(1 for t in win if rb[t] >= HURDLE) / len(win), 3),
        "lift": round(sum(1 for t in win if rb[t] >= HURDLE) / len(win) - bb, 3),
        "spearman": round(spearman([ra[t] for t in c], [rb[t] for t in c]), 3)}

    # ---- ⑥ 事業の実力の持続との対比 ----
    coh = [r for r in json.load(open(os.path.join(OUT, "retro_cohort_2013.json")))["rows"]
           if r.get("roic_med5") is not None and r.get("fwd_roic_med5_a1") is not None]
    x = [r["roic_med5"] for r in coh]
    y = [r["fwd_roic_med5_a1"] for r in coh]
    hi = [r for r in coh if r["roic_med5"] >= 0.15]
    b0 = sum(1 for r in coh if r["fwd_roic_med5_a1"] >= 0.15) / len(coh)
    ph = sum(1 for r in hi if r["fwd_roic_med5_a1"] >= 0.15) / len(hi)
    ret = {r["ticker"]: r["tr_cagr"] for r in
           json.load(open(os.path.join(OUT, "retro_returns_2013_all.json")))["rows"]}
    m2 = [(r["roic_med5"], ret[r["ticker"]]) for r in coh if r.get("ticker") and r["ticker"] in ret]
    bb2 = sum(1 for _a, b in m2 if b >= HURDLE) / len(m2)
    hi2 = [b for a, b in m2 if a >= 0.15]
    rep["business_vs_price"] = {
        "roic_persistence": {"n": len(coh), "spearman": round(spearman(x, y), 3),
                             "p_fwd_roic15_given_entry_roic15": round(ph, 3), "base": round(b0, 3),
                             "lift": round(ph - b0, 3), "ratio": round(ph / b0, 2)},
        "same_input_predicts_price_return": {
            "n": len(m2), "spearman": round(spearman([a for a, _b in m2], [b for _a, b in m2]), 3),
            "p_ret15_given_entry_roic15": round(sum(1 for b in hi2 if b >= HURDLE) / len(hi2), 3),
            "base": round(bb2, 3),
            "lift": round(sum(1 for b in hi2 if b >= HURDLE) / len(hi2) - bb2, 3)},
        "reading": "事業の実力は強く持続し入口から予言できる。同じ入口情報で株価リターンを当てようとすると"
                   "力がほとんど残らない。差分が『価格が実力を織り込んでいる』分で、"
                   "hist_val_decompose の実測（ρ(分位,倍率)=−0.43 / ρ(分位,事業)=+0.49 / ρ(分位,総)=+0.065）"
                   "を結果側から見たものと一致する"}

    json.dump(rep, open(os.path.join(OUT, "retro_persistence.json"), "w"), ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return
    f = rep["four_windows"]
    print(f"■ 重ならない4窓（各約3年）・n={f['n']}  ベース {f['base']}")
    print(f"  勝数の分布: 実測 {f['wins_observed']}")
    print(f"              独立抽選 {f['wins_expected_if_independent']}")
    print(f"              比 {f['ratio']}  ← **1.0 なら『常に勝つ社』はコイン投げ以上に存在しない**")
    print("\n■ 連続する窓での持続")
    for p in rep["persistence_pairs"]:
        print(f"  {p['from'].split()[0]}→{p['to'].split()[0]}: P(次も勝|勝)={p['p_next_given_win']} "
              f"vs 負={p['p_next_given_lose']} ベース{p['base']} → lift {p['lift']:+.3f}")
    v = rep["variance"]
    print(f"\n■ 分散分解: 会社{v['share_company']:.1%} / 窓(相場){v['share_window']:.1%} / 残差{v['share_resid']:.1%}"
          f"  **ICC={v['icc']:.3f}**")
    print("\n■ 後知恵を除いた上限（他窓の実績で選び、残り1窓で測る）")
    for r in rep["leave_one_out_ceiling"]:
        print(f"  {r['target'].split()[0]} 上位{r['select_top']}: P={r['p']} vs ベース{r['base']} → ×{r['ratio']}")
    print("\n■ 窓の長さと持続性")
    print(f"  {'長さ':<8}{'窓数':>5}{'ベース':>8}{'持続lift':>10}{'ICC':>8}{'全勝 実測/期待':>18}")
    for b in rep["by_window_length"]:
        print(f"  {b['months']:>3}ヶ月{'':<2}{b['n_windows']:>5}{b['base_mean']:>8.3f}"
              f"{(b['persistence_lift_mean'] if b['persistence_lift_mean'] is not None else 0):>10.3f}"
              f"{b['icc']:>8.3f}{b['all_win_observed']:>10}/{b['all_win_expected']:>7.1f}")
    h = rep["two_long_halves"]
    print(f"\n■ 重ならない2つの長い窓（各{h['years_each']}年・n={h['n']}）")
    print(f"  P(後半勝|前半勝)={h['p_second_given_first_win']} ベース{h['base_second']} → lift {h['lift']:+.3f}"
          f" / 年率のSpearman {h['spearman']:+.3f}")
    bp = rep["business_vs_price"]
    print(f"\n■ ★対比")
    print(f"  事業の実力(ROIC)の持続: Spearman {bp['roic_persistence']['spearman']:+.3f} / "
          f"lift {bp['roic_persistence']['lift']:+.3f}（×{bp['roic_persistence']['ratio']}）")
    print(f"  同じ入口で株価リターン: Spearman {bp['same_input_predicts_price_return']['spearman']:+.3f} / "
          f"lift {bp['same_input_predicts_price_return']['lift']:+.3f}")


if __name__ == "__main__":
    main()
