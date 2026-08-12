# night/retro_robust.py — 結果変数を「壊れない複利」へ作り直す（2026-08-12新設）
#
# ★この器の要点は指標ではなく **結果変数** の側にある。
#   この台帳の歴史検証は、2013年から今日まで一貫して結果を**スカラー2種**でしか測っていない——
#     ・前方リターン年率 >= 15%（複利）
#     ・恒久毀損 P(y <= -15%) / 元本割れ P(y < 0)（左尾）
#   ところが門の目的は「**壊れない**複利」で、**壊れなさは経路（path）の性質**である。
#   終点だけを見る年率は、途中で −80% を経由して戻った社と、一度も −30% を割らずに積んだ社を
#   **同じ数字**として扱う。20-30年その株を持ち続けられるかは、後者かどうかで決まる。
#   in-stock の158ヶ月パネル（retro_monthly 2本・952社）で、この経路つきの結果を初めて定義できる。
#
# 定義（**新しい定数を一つも導入しない**——ここが設計の要）:
#   robust = (年率 >= 0.15)                     … 既存のハードル
#          ∧ (最大DD >= SPYの同期間の最大DD)      … 「市場より浅い」＝定数ではなく市場が決める線
#          ∧ (窓の終わりまでに最大DDから回復済み)   … 定数不要の構造的な条件
#   併記する部分条件: deep(年率>=15%のみ) / shallow(DDのみ) / recovered(回復のみ)
#
# SPYの最大DDは各 out/retro_returns_{asof}.json の benchmark.mdd（実測 −0.239）を使う。
# 月次パネルは2本を連結する（偵察が接合部を実測: 952社の 2018-07÷2018-06 は中央値1.0218・
# 0.5〜2.0の外0件）。同一年月に複数バーがあるときは**最初のバー**を採る（末尾の部分バー対策）。
#
# ⚠ 限界: adjclose は取得日(2026-08)基準の調整値なので**水準は当時の板の値ではない**が、
#   窓内の比（リターン・DD・回復）は乗法調整で不変（この台帳が retro_per_asof の是正で確認済み）。
#
# 実行: python3 night/retro_robust.py  → out/retro_robust_{2016,2017,2018}.json

import datetime
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
ANCHORS = {2016: "2016-07-01", 2017: "2017-07-01", 2018: "2018-07-01"}
HURDLE = 0.15


def ym(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)


def panel():
    """2本を連結した {ticker: {ym: px}}。同一年月は最初のバーを採る。"""
    p = {}
    for f in ("retro_monthly_2013_2018.json", "retro_monthly_2018_2026.json"):
        raw = json.load(open(os.path.join(OUT, f)))
        for t, series in raw.items():
            m = p.setdefault(t, {})
            for ts, px in series:
                if px is None or px <= 0:
                    continue
                k = ym(ts)
                if k not in m:
                    m[k] = px
    return p


def path_stats(seq):
    """[(ym, px)] 昇順 → 年率・最大DD・回復したか・回復月数・水中月数の割合。"""
    n = len(seq)
    if n < 24:
        return None
    px0, px1 = seq[0][1], seq[-1][1]
    yrs = (seq[-1][0] - seq[0][0]) / 12.0
    if px0 <= 0 or yrs <= 0:
        return None
    cagr = (px1 / px0) ** (1 / yrs) - 1
    peak = seq[0][1]
    mdd, trough_i, peak_i = 0.0, 0, 0
    cur_peak_i = 0
    under = 0
    for i, (_k, px) in enumerate(seq):
        if px > peak:
            peak = px
            cur_peak_i = i
        else:
            under += 1
        dd = px / peak - 1.0
        if dd < mdd:
            mdd, trough_i, peak_i = dd, i, cur_peak_i
    # 谷のあと、従前ピークを回復したか
    ppx = seq[peak_i][1]
    rec_i = None
    for i in range(trough_i + 1, n):
        if seq[i][1] >= ppx:
            rec_i = i
            break
    return {
        "years": round(yrs, 2), "cagr": round(cagr, 4), "mdd": round(mdd, 4),
        "recovered": rec_i is not None,
        "rec_months": (rec_i - trough_i) if rec_i is not None else None,
        "underwater_r": round(under / n, 3),
        "months": n,
    }


def main():
    P = panel()
    for anchor, ad in ANCHORS.items():
        rets = json.load(open(os.path.join(OUT, f"retro_returns_{anchor}.json")))
        spy_mdd = rets["benchmark"]["mdd"]
        a = datetime.date.fromisoformat(ad)
        k0 = a.year * 12 + (a.month - 1)
        kend = max(k for m in P.values() for k in m)
        rows, holes = [], []
        for t, m in P.items():
            seq = [(k, m[k]) for k in sorted(m) if k0 <= k <= kend]
            st = path_stats(seq)
            if not st:
                holes.append({"t": t, "months": len(seq)})
                continue
            st["t"] = t
            st["deep"] = st["cagr"] >= HURDLE
            st["shallow_spy"] = st["mdd"] >= spy_mdd
            st["recov"] = st["recovered"]
            rows.append(st)
        # ★プール相対の線（定数を導入しない）: 最大DDが**この母集団の中央値より浅い**
        mdds = sorted(r["mdd"] for r in rows)
        med_mdd = mdds[len(mdds) // 2]
        for r in rows:
            r["shallow_med"] = r["mdd"] >= med_mdd
            r["robust_spy"] = bool(r["deep"] and r["shallow_spy"] and r["recov"])
            r["robust"] = bool(r["deep"] and r["shallow_med"] and r["recov"])   # 主・到達可能な版
            r["deep_rec"] = bool(r["deep"] and r["recov"])
        n = len(rows)
        base = {
            "n": n, "median_mdd": round(med_mdd, 4),
            "p_deep": round(sum(r["deep"] for r in rows) / n, 3),
            "p_shallow_spy": round(sum(r["shallow_spy"] for r in rows) / n, 3),
            "p_shallow_med": round(sum(r["shallow_med"] for r in rows) / n, 3),
            "p_recovered": round(sum(r["recov"] for r in rows) / n, 3),
            "p_deep_rec": round(sum(r["deep_rec"] for r in rows) / n, 3),
            "n_deep_rec": sum(r["deep_rec"] for r in rows),
            "p_robust": round(sum(r["robust"] for r in rows) / n, 3),
            "n_robust": sum(r["robust"] for r in rows),
            "p_robust_spy": round(sum(r["robust_spy"] for r in rows) / n, 3),
            "n_robust_spy": sum(r["robust_spy"] for r in rows),
        }
        out = {"generated": datetime.date.today().isoformat(), "asof": anchor, "asof_date": ad,
               "spy_mdd": spy_mdd, "hurdle": HURDLE,
               "definition": {
                   "robust": "年率>=15% ∧ 最大DDが母集団中央値より浅い ∧ 最大DDから回復済み（主・プール相対＝定数なし）",
                   "robust_spy": "年率>=15% ∧ 最大DD>=SPYの最大DD ∧ 回復済み（従・実測で到達不能）",
                   "deep_rec": "年率>=15% ∧ 回復済み（従）"},
               "base": base, "n_hole": len(holes), "rows": rows}
        json.dump(out, open(os.path.join(OUT, f"retro_robust_{anchor}.json"), "w"), ensure_ascii=False)
        print(f"{anchor}: n={base['n']} SPY_mdd={spy_mdd} 母集団中央DD={base['median_mdd']}")
        print(f"   deep(15%+)={base['p_deep']} / 回復済み={base['p_recovered']} / "
              f"SPYより浅い={base['p_shallow_spy']} / 中央値より浅い={base['p_shallow_med']}")
        print(f"   → deep_rec={base['p_deep_rec']}({base['n_deep_rec']}社) / "
              f"**robust={base['p_robust']}({base['n_robust']}社)** / robust_spy={base['p_robust_spy']}({base['n_robust_spy']}社)")


if __name__ == "__main__":
    main()
