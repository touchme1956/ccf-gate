#!/usr/bin/env python3
# night/retro_pillars_docs.py — 2018ビンテージ等、readlist が無いビンテージの**原本URL**を解決する
# （2026-08-12新設）
#
# ⚠ look-ahead を構造で防ぐ: **filingDate <= {asof}-07-01** の最新の年次報告だけを採る
#   （決算期末ではなく提出日で切る＝retro_build_readlist と同じ作法。関数もそこから import して
#     二重実装を作らない）。
# ⚠ リターンは一切載せない（読解班に結末を渡さない）。
#
# 使い方: python3 night/retro_pillars_docs.py --asof 2018
import argparse, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))
import retro_build_readlist as RB      # pick() / all_filings() を再利用


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", type=int, default=2018)
    a = ap.parse_args()
    b = json.load(open(os.path.join(OUT, f"retro_pillars_batches_{a.asof}.json"), encoding="utf-8"))
    want = [r["ticker"] for r in b["rows"]]
    # CIK は SEC の company_tickers から引く（irr85_extract が既に持っている経路を使う）
    import irr85_extract as EX
    cutoff = f"{a.asof}-07-01"
    rows, miss = [], []
    for i, t in enumerate(want, 1):
        try:
            cik = EX.cik_of(t)
        except SystemExit:
            miss.append(dict(ticker=t, why="CIKが引けない"))
            continue
        try:
            f = RB.pick(int(cik), cutoff)
        except Exception as e:
            miss.append(dict(ticker=t, why=f"{type(e).__name__}"))
            continue
        if not f:
            miss.append(dict(ticker=t, why=f"filed<={cutoff} の年次報告が無い"))
            continue
        rows.append(dict(ticker=t, cik=int(cik), **f))
        if i % 25 == 0:
            print(f"  {i}/{len(want)} …", flush=True)
        time.sleep(0.12)
    doc = dict(generated="2026-08-12", asof=a.asof, cutoff=cutoff,
               note="filed<=cutoff の最新の年次報告のURL。**リターンは載せない**",
               n=len(rows), n_miss=len(miss), miss=miss, rows=rows)
    p = os.path.join(OUT, f"retro_pillars_docs_{a.asof}.json")
    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"asof={a.asof}  解決 {len(rows)}社 / 失敗 {len(miss)}社")
    for m in miss[:12]:
        print("   ⚠", m["ticker"], m["why"])
    print("→", p)


if __name__ == "__main__":
    main()
