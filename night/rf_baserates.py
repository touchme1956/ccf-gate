#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rf_baserates.py — Reformers の考え方（赤字→業績の改善）を、生き残りバイアスの無い長い歴史で見る（事前登録 base_rates_survivor_free）

  B1  Ken French『Portfolios_Formed_on_E-P』の『<= 0』群（益回りが0以下＝赤字企業・CRSP 全上場・倒産も含む）の、French の Mkt に対する超過
  B2  JKP（jkpfactors.com・米国・vw_cap）の利益の改善系4本: niq_su / ni_inc8q / niq_at_chg1 / niq_be_chg1

窓: 全期間・1990-01〜・2007-01〜・2013-01〜・2016-07〜。出力: out/reformers_baserates.json
読むだけ（採点・門に不使用）。B1 は『赤字であること』の効果で『改善』の効果ではない（事前登録に明記）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402

WINDOWS = {"full": (None, None), "1990-01~": (199001, None), "2007-01~": (200701, None), "2013-01~": (201301, None),
           "2016-07~": (201607, None)}


def stat(s, b, a, z):
    x = N.excess_stats(s, b, a, z)
    if not x:
        return None
    return {k: x[k] for k in ("from", "to", "years", "ex_ann", "t", "cagr_s", "cagr_b", "cagr_diff", "vol_s", "vol_b")}


def main():
    out = {"why": "Reformers の再現（Yahoo の生き残りだけ）を補う、上場廃止も含む長い歴史での基礎率", "B1": {}, "B2": {}}
    mkt = N.ff_factors()["mkt"]
    for kind in ("Value Weight", "Equal Weight"):
        ser = N.french_series("Portfolios_Formed_on_E-P", want=kind, freq="monthly")
        loss = ser["<= 0"]
        hi30 = ser["Hi 30"]
        prof_all = {m: sum(ser[c][m] for c in ("Lo 30", "Med 40", "Hi 30") if m in ser[c]) / 3 for m in loss}
        blk = {}
        for w, (a, z) in WINDOWS.items():
            blk[w] = {"loss_vs_Mkt": stat(loss, mkt, a, z), "loss_vs_profitable(3群の平均)": stat(loss, prof_all, a, z),
                      "loss_total_return": stat(loss, {m: 0.0 for m in loss}, a, z)}
        out["B1"][kind] = blk
        firms = N.french_tables("Portfolios_Formed_on_E-P")
        nf = firms["Number of Firms in Portfolios"]
        last = sorted(nf["data"])[-1]
        out["B1"][kind + "_firms_last"] = {"date": last, "loss_group": nf["data"][last][0]}
    for key in ("niq_su", "ni_inc8q", "niq_at_chg1", "niq_be_chg1"):
        f = N.jkp_factor("usa", key)
        zero = {m: 0.0 for m in f}
        out["B2"][key] = {w: stat(f, zero, a, z) for w, (a, z) in WINDOWS.items()}
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out", "reformers_baserates.json")
    import json
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    print("→", p)
    for kind in ("Value Weight", "Equal Weight"):
        print("B1", kind)
        for w in WINDOWS:
            x = out["B1"][kind][w]["loss_vs_Mkt"]
            print("  ", w.ljust(9), None if not x else f"超過 {x['ex_ann']:+.2f}%/年 t={x['t']}  赤字群 {x['cagr_s']}% vs 市場 {x['cagr_b']}%  ({x['from']}〜{x['to']})")
    for key, blk in out["B2"].items():
        print("B2", key, {w: (None if not x else f"{x['ex_ann']:+.2f}(t{x['t']})") for w, x in blk.items()})


if __name__ == "__main__":
    main()
