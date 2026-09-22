#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_disrupt_ft.py — 未検定の崖 ②『disrupt=unsettled → f5 の段差』を歴史で測る（2026-09-21新設）

**読むだけ。採点・規約・合否には一切触れない。** 事前登録は `out/retro_cliffs_prereg.json`。

■ ⚠ 先に書いておく限界（事前登録どおり）
  `disrupt` は**読解項目**で、歴史側に読解が無い（台帳が ARCHIVE:5371 で明記）。
  よってここで測れるのは**機械の代理**——10-K 本文に事前登録のフレーズが有るか、だけ。
  さらに窓が2つ（2018/2013）しか作れないので、**この台帳の採用基準（3ビンテージで符号が
  反転しない）を原理的に満たせない**。最良でも「棄却できない」までで、**採用の根拠にはならない**。

■ look-ahead の排除は retro_fulltext.py と同じ構造
  efts の**提出日窓**で切る（年ラベルではなく filed 基準）。2018乗車は 2016-07-01〜2018-06-30、
  2013乗車は 2011-07-01〜2013-06-30。器（ペーサー・再試行・query_total）はそのまま借りる
  ＝v9.9.65「二重に持たない」。

使い方: python3 night/retro_disrupt_ft.py [--vintage 2018|2013|both]
出力  : out/retro_disrupt_ft.json（社ごとのヒット有無）
"""
import json, os, sys, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("rft", os.path.join(BASE, "night", "retro_fulltext.py"))
RFT = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(RFT)   # main() は走らない

# 事前登録のフレーズ（結果を見る前に固定・out/retro_cliffs_prereg.json と同一）
PHRASES = [
    ("dz_disrupt", ['"disruptive technologies"', '"disruptive technology"']),
    ("dz_rapid",   ['"rapid technological change"']),
    ("dz_obsolete", ['"render our products obsolete"']),
    ("dz_ai",      ['"artificial intelligence"']),
    ("dz_entrant", ['"new entrants"']),
]
WIN = {2018: ("2016-07-01", "2018-06-30", "retro_returns_2018.json"),
       2013: ("2011-07-01", "2013-06-30", "retro_returns_2013_all.json")}
OUT = os.path.join(BASE, "out", "retro_disrupt_ft.json")


def ciks():
    coh = json.load(open(os.path.join(BASE, "out", "retro_cohort_2013.json")))
    m = {r["ticker"]: r.get("cik") for r in coh["rows"] if r.get("ticker") and r.get("cik")}
    return m


def run(vint, tickers, cikmap):
    s, e, _ = WIN[vint]
    res = {}

    def one(t):
        c = cikmap.get(t)
        if not c:
            return t, None
        cz = str(c).zfill(10)
        base = {"forms": "10-K", "startdt": s, "enddt": e, "ciks": cz}
        n10k = RFT.query_total(dict(base))
        if not n10k:                       # 窓内に 10-K が無い社は**全欄欠測**（0ではない・ルール7）
            return t, {"no10k": True}
        row = {"no10k": False}
        for key, qs in PHRASES:
            hit = 0
            for q in qs:
                v = RFT.query_total(dict(base, q=q))
                if v is None:
                    hit = None; break
                hit = max(hit, 1 if v >= 1 else 0)
            row[key] = hit
        return t, row

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(one, t): t for t in tickers}
        for i, f in enumerate(as_completed(futs), 1):
            t, row = f.result()
            if row is not None:
                res[t] = row
            if i % 100 == 0:
                print("  %d / %d" % (i, len(tickers)), flush=True)
    return res


def main():
    which = sys.argv[sys.argv.index("--vintage") + 1] if "--vintage" in sys.argv else "both"
    vints = [2018, 2013] if which == "both" else [int(which)]
    cikmap = ciks()
    out = {"generated": datetime.date.today().isoformat(),
           "prereg": "out/retro_cliffs_prereg.json",
           "note": "10-K本文の破壊まわりの定型言語の有無。提出日窓でlook-ahead無し。器は retro_fulltext.py",
           "phrases": {k: v for k, v in PHRASES}, "windows": {str(k): WIN[k][:2] for k in WIN},
           "rows": {}}
    if os.path.exists(OUT):
        try: out["rows"] = json.load(open(OUT)).get("rows", {})
        except Exception: pass
    for v in vints:
        ret = json.load(open(os.path.join(BASE, "out", WIN[v][2])))
        tickers = [r["ticker"] for r in (ret["rows"] if isinstance(ret, dict) else ret)]
        print("■ %d年ビンテージ: %d社 × フレーズ%d本（窓 %s〜%s）" % (v, len(tickers), len(PHRASES), *WIN[v][:2]), flush=True)
        out["rows"][str(v)] = run(v, tickers, cikmap)
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("  → 採取 %d社" % len(out["rows"][str(v)]), flush=True)
    print("→", OUT)


if __name__ == "__main__":
    main()
