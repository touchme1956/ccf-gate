#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# night/hist_val2_delisted.py — dd5 の検定を**退場社込みの母集団**に当てる（2013年・2026-08-10）
#
# ── なぜ別の器が要るか ───────────────────────────────────────────────────────
#   night/retro_delisted_secpx.py が、Yahooが消してしまう退場社の株価を**SEC原本**から
#   復元し、2013年の質実証プールを **374社（survivorのみ）→ 419社** へ戻した。
#   母集団としてはこちらが正しい——だが**そのまま主の判定プールにはできない。** 理由は2つ:
#
#   (1) **指標が計算できない。** dd5 は 2008-07〜2013-06 の月次価格を要る。復元した45社は
#       まさに Yahoo が履歴ごと消している社で、**45社とも pre-2013 の月足が0件**
#       （2026-08-10 に live で再確認: TGNA/SEM/HIBB/ATRI/SRDX/JNPR/PNRA/SIAL の8社を叩いて
#         取れたのは SEM の1ヶ月だけ）。10-K Item5 の四半期高安から作ることは原理的に可能だが、
#       **survivor は月次終値の最高値・退場社は四半期の高値**という**基準の違う二つ**になり、
#       四半期高値のほうが必ず高い＝退場社だけが機械的に深い dd5 を持ち、
#       **仮説に有利な向きへ偏る**。この台帳が7回踏んでいる型を、検定の中で自分から作ることになる。
#
#   (2) **結果の基準も違う。** 退場社の復元は price-only（配当なし）で、P_wide の tr_cagr は
#       adjclose（配当込み）。**割ってはいけない**ので、この器は survivor 側も price-only
#       （retro_delisted_secpx が --closes で採り直した px_cagr）で通す。**同じ土俵に降ろす。**
#
# ── だから何をするか＝**挟み込み（bounding）** ────────────────────────────────
#   45社の dd5 が判らないなら「判らない」と書き、**両極端**を計算して
#   **2013年の判定が引っくり返りうるか**だけを決める:
#       下端 = 45社を全部『通過』に入れる（欠測は発火しない側＝門の実装と同じ読み）
#       上端 = 45社を全部『止めた』に入れる（指標が最大限に効いた場合）
#   どちらでも判定が同じなら、**dd5 の判定は退場社の穴に依存していない**と言い切れる。
#   これは点推定を点推定で置き換えるより強い（幅を明示して、幅のどこでも結論が変わらないと示す）。
#
#   ★2026-09-23 追記（退場日の是正・out/retro_exit_fix_2013.json）: 上の「45社・419社・144社」は
#     2026-08-10 の台帳の数字。是正後は **survivor 370 ＋ 復元した退場 96 ＝ 466社**、打ち切り 97社で、
#     退場96社のうち dd5 が作れたのは1社だけ（95社が欠測）。挟み込みの設計はそのまま。
#     survivor のうち EQR・QVCAQ・SALM は Yahoo が 2026-07 より前の足を返さなくなり（px_guard が採らない）
#     dd5 が欠測＝na として両端へ振られる（2026-08-10 の採取では測れていた）。
#
#   さらに **144社は返り値そのものが打ち切り**（合併対価も採れない＝破産・登録抹消の類）。
#   ここは returns が無いので挟み込みにも入らない＝**この器で埋まらない穴**として実数で書く。
#
# 実行:  python3 night/hist_val2_delisted.py            # out/hist_val2_delisted.json
import argparse
import json
import math
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

import hist_valuation as HV                  # noqa: E402
import hist_val_prereg_v2_reach as R         # noqa: E402  **指標の定義は単一実装**
import hist_val2_dd5 as V2                   # noqa: E402  基準の判定も単一実装（judge_v2）

VINTAGE = 2013
ASOF_MONTH = "2013-06"       # P_wide の px_month（2013年ビンテージは全社これ）
GRID = R.GRID_DD
JUDGEABLE = V2.JUDGEABLE


def stat_px(rows, years, key="px_cagr"):
    """price-only の群の姿。**adjclose の tr_cagr と混ぜない**ので専用に数える。

    gate_test.stats は tr_cagr 固定なので使えない（同じ関数を二つの意味で使わない）。
    出す欄は stat2 と同じ名前に揃える——判定器 judge_v2 をそのまま呼ぶため。
    """
    rs = [r[key] for r in rows if r.get(key) is not None]
    if not rs:
        return {"n": len(rows), "n_ret": 0}
    nl = sum(1 for x in rs if x < 0)
    npm = sum(1 for x in rs if x <= V2.PERM_LINE)
    nw = sum(1 for x in rs if x >= 0.15)
    tot = [(1.0 + x) ** (r.get("years") or years)
           for x, r in ((r[key], r) for r in rows if r.get(key) is not None)]
    ew = (statistics.fmean(tot)) ** (1.0 / years) - 1.0 if tot else None
    return {"n": len(rows), "n_ret": len(rs),
            "median": round(statistics.median(rs), 4),
            "mean": round(statistics.fmean(rs), 4),
            "ew_cagr": None if ew is None else round(ew, 4),
            "p_loss": round(nl / len(rs), 4), "n_loss": nl,
            "p_perm": round(npm / len(rs), 4), "n_perm": npm,
            "p_win": round(nw / len(rs), 4), "n_win": nw,
            "worst": round(min(rs), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val2_delisted.json"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    sec = json.load(open(os.path.join(OUT, f"retro_delisted_secpx_{VINTAGE}.json"), encoding="utf-8"))
    dl = json.load(open(os.path.join(OUT, f"retro_delisted_{VINTAGE}.json"), encoding="utf-8"))
    info = {r["cik"]: r for r in dl["rows"]}
    years = 13.09

    pool, restored, censored = [], [], []
    for r in sec["rows"]:
        if not r.get("quality"):
            continue
        i = info.get(r["cik"], {})
        t = i.get("ticker_hist") or (i.get("cands") or [None])[0]
        row = {"cik": r["cik"], "name": r["name"], "ticker": t,
               "px_cagr": r.get("px_cagr"), "px_cagr_hi": r.get("px_cagr_hi"),
               "years": r.get("years") or years, "status": r.get("status"),
               "exit_kind": r.get("exit_kind"), "survivor": r.get("status") == "survivor"}
        if row["px_cagr"] is None:
            censored.append(row)
            continue
        # dd5（**登録どおり adjclose**。取れない社は None のまま＝欠測をゼロと読まない）
        dd = None
        if t:
            px = HV.fetch_px(t, offline=True) or {}
            dd, _ = R.drawdown(px.get("adj") or {}, ASOF_MONTH, R.DD_WIN, R.DD_MIN_OBS)
        row["dd5"] = dd
        pool.append(row)
        (restored if not row["survivor"] else []).append(row) if not row["survivor"] else None

    restored = [r for r in pool if not r["survivor"]]
    surv = [r for r in pool if r["survivor"]]
    n_dd = sum(1 for r in pool if r["dd5"] is not None)

    res = {"generated": "2026-08-10", "regenerated": __import__("datetime").date.today().isoformat(),
           "tool": "night/hist_val2_delisted.py",
           "vintage": VINTAGE, "years": years,
           "basis": "price-only（survivor=Yahoo close / 退場=10-K Item5 高安 ÷ SEC原本の合併対価）。"
                    "**adjclose の tr_cagr と割らないこと**",
           "src": {"universe": f"out/retro_delisted_secpx_{VINTAGE}.json",
                   "indicator": "dd5 は adjclose・登録どおり（night/hist_val_prereg_v2_reach.drawdown）"},
           "pool": {"N": len(pool), "survivor": len(surv), "restored_exits": len(restored),
                    "dd5_coverage": round(n_dd / len(pool), 4),
                    "dd5_missing_survivor": sum(1 for r in surv if r["dd5"] is None),
                    "dd5_missing_restored": sum(1 for r in restored if r["dd5"] is None)},
           "why_bounding": "復元した退場社は **pre-2013 の月足が存在しない**（Yahooが消している）ため "
                           "dd5 が原理的に作れない。10-K Item5 の四半期高値で代用すると "
                           "**survivor=月次終値の最高値 / 退場=四半期高値** という基準の違う二つになり、"
                           "四半期高値のほうが必ず高い＝退場社だけ機械的に深く出て仮説に有利へ偏る。"
                           "だから代用せず、両極端で挟む",
           "base": stat_px(pool, years),
           "restored_only": stat_px(restored, years),
           "survivor_only": stat_px(surv, years),
           "censored": {"n": len(censored),
                        "note": "合併対価も採れない＝**返り値そのものが不明**。挟み込みにも入らない",
                        "by_kind": {}},
           "cells": {}}
    for r in censored:
        k = r.get("exit_kind") or "?"
        res["censored"]["by_kind"][k] = res["censored"]["by_kind"].get(k, 0) + 1

    base = res["base"]
    for t in GRID:
        stop = [r for r in pool if r["dd5"] is not None and r["dd5"] <= t]
        na = [r for r in pool if r["dd5"] is None]
        pas = [r for r in pool if r["dd5"] is not None and r["dd5"] > t]
        cell = {"judgeable": round(t, 2) in [round(x, 2) for x in JUDGEABLE],
                "n_stop_known": len(stop), "n_na": len(na),
                "na_restored": sum(1 for r in na if not r["survivor"])}
        for nm, (S, P) in {"下端_naは全部通過": (stop, pas + na),
                           "上端_naは全部止める": (stop + na, pas)}.items():
            ev = {"n_pool": len(pool), "n_stop": len(S),
                  "stop_rate_pool": round(len(S) / len(pool), 4),
                  "stopped": stat_px(S, years), "passed": stat_px(P, years), "base": base}
            cell[nm] = {"stop": len(S), "stop_rate": ev["stop_rate_pool"],
                        "stopped": ev["stopped"], "passed": ev["passed"],
                        "judge": V2.judge_v2(ev)}      # **基準の判定は単一実装を呼ぶ**
        cell["bound_same_verdict"] = (
            (cell["下端_naは全部通過"]["judge"].get("c1"),
             cell["下端_naは全部通過"]["judge"].get("c2"),
             cell["下端_naは全部通過"]["judge"].get("c4"))
            == (cell["上端_naは全部止める"]["judge"].get("c1"),
                cell["上端_naは全部止める"]["judge"].get("c2"),
                cell["上端_naは全部止める"]["judge"].get("c4")))
        res["cells"][f"{t:+.2f}"] = cell

    # ── 基準の切り分け（**同じ社・同じ指標で、結果の基準だけを替える**）──────────────
    #   退場社込みの母集団は price-only を強いる。すると 2013年の判定が動く——動かしたのが
    #   「退場社を戻したこと」なのか「配当を外したこと」なのかは、**同じ集合**で測らないと判らない。
    #   （この台帳が7回踏んだ「基準の違う二つを割る」型を、切り分けの側で使う）
    hvp = os.path.join(OUT, f"hist_val_{VINTAGE}.json")
    if os.path.exists(hvp):
        hv = json.load(open(hvp, encoding="utf-8"))
        Pw = {r["ticker"]: r for r in R.pools_for(hv["rows"])["P_wide"]}
        byt = {r["ticker"]: r for r in pool if r["ticker"]}
        common = sorted(set(Pw) & set(byt))
        iso = {"n_common": len(common),
               "what": "P_wide(adjclose) と 退場込み(price-only) の**両方に居る社だけ**を取り、"
                       "指標(dd5)も社も固定して、結果の基準だけを替える",
               "bases": {}}
        for nm, get in (("adjclose_配当込み(登録どおりの tr_cagr)",
                         lambda t: Pw[t].get("tr_cagr")),
                        ("close_price_only(退場込みが強いる px_cagr)",
                         lambda t: byt[t].get("px_cagr"))):
            rows = [{"ticker": t, "v": get(t), "years": years,
                     "dd5": byt[t]["dd5"]} for t in common if get(t) is not None]
            b = stat_px(rows, years, key="v")
            cells = {}
            for th in JUDGEABLE:
                S = [r for r in rows if r["dd5"] is not None and r["dd5"] <= th]
                Pp = [r for r in rows if r["dd5"] is not None and r["dd5"] > th]
                ev = {"n_pool": len(rows), "n_stop": len(S),
                      "stop_rate_pool": round(len(S) / len(rows), 4),
                      "stopped": stat_px(S, years, key="v"),
                      "passed": stat_px(Pp, years, key="v"), "base": b}
                cells[f"{th:+.2f}"] = {"stop": len(S), "stopped": ev["stopped"],
                                       "judge": V2.judge_v2(ev)}
            iso["bases"][nm] = {"base": b, "cells": cells}
        # 配当が『元本割れ』から救った社（どちらの群に効いたか）
        sav = [t for t in common
               if (Pw[t].get("tr_cagr") or 0) >= 0 and (byt[t].get("px_cagr") or 0) < 0]
        iso["dividend_rescued"] = {
            "n": len(sav),
            "n_in_stopped_at_-0.30": sum(1 for t in sav
                                         if byt[t]["dd5"] is not None and byt[t]["dd5"] <= -0.30),
            "meaning": "配当を足すと元本割れから外れる社。**通過群にばかり効くと、"
                       "止めた群の濃縮率が配当の分だけ水増しされる**"}
        res["basis_isolation"] = iso

    json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if not a.quiet:
        p = res["pool"]
        print(f"■ {VINTAGE}年・退場社込み（質実証・price-only）  N={p['N']} "
              f"= survivor {p['survivor']} + 復元した退場 {p['restored_exits']}")
        print(f"   dd5 被覆 {p['dd5_coverage']:.1%}  欠測: survivor {p['dd5_missing_survivor']}社 / "
              f"**復元した退場 {p['dd5_missing_restored']}社（＝全部）**")
        for k in ("base", "survivor_only", "restored_only"):
            s = res[k]
            print(f"   {k:14s} n={s['n_ret']:4d} 中央{s['median']:+.4f} 等W"
                  f"{(s['ew_cagr'] if s['ew_cagr'] is not None else 0):+.4f} "
                  f"元本割れ {s['n_loss']}社 {s['p_loss']:.1%}  恒久毀損 {s['n_perm']}社  最悪{s['worst']:+.4f}")
        print(f"   打ち切り（返り値そのものが不明）: {res['censored']['n']}社 "
              f"{res['censored']['by_kind']}")
        print(f"\n   {'閾値':>7} {'判定可':>4} | "
              f"{'下端:止':>7} {'止率':>6} {'割れ':>9} {'倍':>5} {'基1':>5} {'基2':>5} {'基4':>5} | "
              f"{'上端:止':>7} {'止率':>6} {'割れ':>9} {'倍':>5} {'基1':>5} {'基2':>5} {'基4':>5} | 同判定")
        for t in GRID:
            c = res["cells"][f"{t:+.2f}"]
            cols = []
            for nm in ("下端_naは全部通過", "上端_naは全部止める"):
                b = c[nm]; s = b["stopped"]; j = b["judge"]
                cols.append(f"{b['stop']:>7} {b['stop_rate']:>6.1%} "
                            f"{s['n_loss']:>3}/{s['n_ret']:<5} {str(j.get('c1_ratio')):>5} "
                            f"{str(j.get('c1')):>5} {str(j.get('c2')):>5} {str(j.get('c4')):>5}")
            print(f"   {t:+7.2f} {'✓' if c['judgeable'] else '—':>4} | {cols[0]} | {cols[1]} | "
                  f"{c['bound_same_verdict']}")
        print(f"\n→ {a.json}")


if __name__ == "__main__":
    main()
