#!/usr/bin/env python3
# night/retro_pillars_batches.py — 2015/2018 の rep/dur/dom/moatW 読解の**バッチ表**を作る（2026-08-12新設）
#
# ★この器は読解をしない。**誰が何を読むか**を決めるだけ。
#   事前登録 out/retro_moat_pillars_prereg_oos.json（読解を1社も始める前にコミット済）に従う。
#
# ⚠ **リターンを一切載せない**——読解班に結末を渡さないのが事前登録の核心。
#   載せるのは ticker / form / filed / url だけ。
# ⚠ 2013で読んだ社かどうかの印(`in2013`)は**集計用にここでだけ持ち**、班へ渡すプロンプトには入れない
#   （厳密OOS の H2 を後から切り出すため）。
#
# 使い方: python3 night/retro_pillars_batches.py --asof 2015 --size 20
import argparse, json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")


def L(p):
    with open(os.path.join(OUT, p), encoding="utf-8") as f:
        d = json.load(f)
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", type=int, default=2015)
    ap.add_argument("--size", type=int, default=20)
    a = ap.parse_args()

    p13 = {r["ticker"] for r in L("retro_moat_pillars_2013.json")}
    if a.asof == 2015:
        src, rows = "readlist", []
        for f in ("retro_readlist_2015.json", "retro_readlist_2015q.json",
                  "retro_readlist_2015qb.json"):
            rows += L(f)
        seen, uniq = set(), []
        for r in rows:
            t = r.get("ticker")
            if not t or t in seen:
                continue
            seen.add(t)
            uniq.append(dict(ticker=t, form=r.get("form"), filed=r.get("filed"),
                             url=r.get("url"), in2013=t in p13))
    else:
        src, uniq = "moat_2018", []
        for f in ("retro_moat_2018.json", "retro_moat_2018_rest.json"):
            for r in L(f):
                t = r.get("t")
                if t:
                    uniq.append(dict(ticker=t, form=r.get("form"), filed=r.get("filed"),
                                     url=None, in2013=t in p13))
    uniq.sort(key=lambda r: r["ticker"])
    # ★ティッカー昇順のまま**等間隔で**バッチへ配る（2018年読解が A〜E に偏った反省。
    #   連続で切ると1班がアルファベットの一区画だけを見ることになり、班の癖と業種が交絡する）
    nb = (len(uniq) + a.size - 1) // a.size
    batches = [[] for _ in range(nb)]
    for i, r in enumerate(uniq):
        batches[i % nb].append(r)
    doc = dict(generated="2026-08-12", asof=a.asof, source=src, n=len(uniq),
               n_in2013=sum(1 for r in uniq if r["in2013"]),
               n_fresh=sum(1 for r in uniq if not r["in2013"]),
               size=a.size, n_batches=nb,
               note="読解班へ渡すのは ticker/form/filed/url だけ。**リターンも in2013 も渡さない**",
               batches=[dict(batch=i + 1, tickers=[x["ticker"] for x in b]) for i, b in enumerate(batches)],
               rows=uniq)
    p = os.path.join(OUT, f"retro_pillars_batches_{a.asof}.json")
    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"asof={a.asof}  {len(uniq)}社 → {nb}班（{a.size}社/班）"
          f"  2013既読 {doc['n_in2013']} / 新規 {doc['n_fresh']}")
    print("→", p)


if __name__ == "__main__":
    main()
