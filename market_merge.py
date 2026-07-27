#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_merge.py — market_data.json の市場値を審査パックへ機械充填する(2026-07精査で新設)
背景: Ω75+14社中12社のパックが per/px/shy=null で、Ⅵ買付順位は素のrepoデータでは
投下可0・E[r]判定不能12——判断面がブラウザ手入力だけに支えられ、並走突合が不能だった。
市場値(px/per/perF/beta/shy/evebit)は客観データであり、定性項目(dom/irr/…)とは別物
=「定性を勝手に埋めない」(絶対のルール2)に抵触しない。null のフィールドのみ充填し、
手入力済みの値は上書きしない。充填履歴は _meta.market に記録する。
使い方: python market_fetch.py <TICKERS...> で market_data.json を更新してから
        python market_merge.py            … 全パックへnullのみ充填
        python market_merge.py NVDA MSFT  … 指定銘柄のみ
"""
import json, glob, os, sys
from datetime import date

FIELDS = ["px", "per", "perF", "beta", "shy", "evebit", "analysts", "instOwn"]
md = {}
if os.path.exists("market_data.json"):
    md = {k.upper(): v for k, v in json.load(open("market_data.json", encoding="utf-8")).items()}
if not md:
    raise SystemExit("market_data.json が空——先に python market_fetch.py を実行")

only = {a.upper() for a in sys.argv[1:]}
n_f = n_p = 0
for f in sorted(glob.glob("out/*_gate_pack.json")):
    t = os.path.basename(f).split("_gate_pack")[0].upper()
    if only and t not in only:
        continue
    if t not in md:
        continue
    try:
        o = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        print(f"▲ {f} 読込不能: {e}")
        continue
    filled = []
    for k in FIELDS:
        v = md[t].get(k)
        if v is not None and o.get(k) is None:
            o[k] = v
            filled.append(k)
    if filled:
        o.setdefault("_meta", {})["market"] = {"date": str(date.today()), "filled": filled,
                                               "src": "market_fetch/market_data.json"}
        json.dump(o, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n_p += 1
        n_f += len(filled)
        print(f"{t:<6} 充填: {','.join(filled)}")
print(f"→ {n_p}パックに{n_f}フィールド充填(nullのみ・手入力値は不変)。門で再取込すればⅥのE[r]判定が生きる")
