#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr_regrade_today.py — 再採点の器を**今日の台帳**に当てて較正する（2026-09-18新設）

★なぜ要るか: 歴史を今日の規約で採点し直すのはよいが、**その採点器が今日の規約を
  当てられているか**を確かめていなければ「歴史の70/85は今日の規約を満たさない」という
  強い結論を、採点器の欠陥から出しているかもしれない。
  ＝**未知を測る前に既知を掴む**（irr85_hunt2_selftest と同じ作法）。

何をするか: 今日のパックの `_meta.evidence.irr` から**英文の引用だけ**を取り出し
  （抽出は night/irr85_mech_diff.quotes_of を import＝二重に持たない）、
  歴史とまったく同じ盲検の形（ティッカーも今日の刻みも渡さない）で採点者へ渡す。
  採点器が今日の審査官と一致すれば較正済み。食い違えば**どちらが誤りかを名指しできる**。

⚠ 限界（先に書く）:
  ・今日の審査官は**原本の全文**を読んで刻みを決めた。採点器が見るのは
    審査官が引いた一文だけ＝**同じ作業ではない**。不一致は必ずしも採点器の誤りではない
  ・日本株は evidence が日本語なので英文の引用が取れない＝この較正の外（穴として明示）
出力: out/irr_regrade_today_items.json（採点者へ）／ out/irr_regrade_today_meta.json（答え合わせ用）
使い方: python3 night/irr_regrade_today.py
"""
import glob
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "night"))
from irr85_mech_diff import quotes_of  # noqa: E402  ★抽出は再実装しない


def main():
    items, meta, noq = [], [], []
    for f in sorted(glob.glob("out/*_gate_pack.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        t = os.path.basename(f).replace("_gate_pack.json", "")
        irr = d.get("irr")
        if irr not in (70, 85, 100):
            continue
        ev = ((d.get("_meta") or {}).get("evidence") or {}).get("irr")
        qs = quotes_of(ev)
        if not qs:
            noq.append({"t": t, "irr": irr,
                        "why": "英文の引用が取れない（日本株の日本語 evidence／引用なし）"})
            continue
        # 最も長い断片＝その審査官が最も強い証拠として引いた一文
        q = qs[0]
        iid = "T" + hashlib.sha1(t.encode()).hexdigest()[:8]
        items.append({"id": iid, "quote": q})
        meta.append({"id": iid, "t": t, "today": irr, "nfrag": len(qs)})
    json.dump({"generated": "2026-09-18", "n": len(items), "rows": items},
              open("out/irr_regrade_today_items.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"generated": "2026-09-18", "n": len(meta), "rows": meta,
               "引用が取れない": noq},
              open("out/irr_regrade_today_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("採点へ回せる:", len(items), Counter(m["today"] for m in meta))
    print("引用が取れない:", len(noq), Counter(x["irr"] for x in noq))


if __name__ == "__main__":
    main()
