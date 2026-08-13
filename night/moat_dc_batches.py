#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/moat_dc_batches.py — 二重計上の読解ワークフローへ渡す作業単位を作る（2026-08-13）

audit_moat_double_count.py の目録（機械）を、**読み手が判定できる形**へ組み直す。
・1件＝(銘柄, 柱の対)。共有された引用と、**両方の欄の evidence 全文**を同梱する
・**リターン・株価・門の合否は渡さない**（判定を汚さないため）。Ωも渡さない
・班はティッカー昇順の**等間隔抽出**でA〜Zの全域に散らす（2018年の打ち切り偏りの反省）

使い方: python3 night/moat_dc_batches.py [--batches 8]  → out/moat_dc_batches.json
"""
import json, os, sys, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")


def main():
    nb = int(sys.argv[sys.argv.index("--batches") + 1]) if "--batches" in sys.argv else 8
    d = json.load(open(os.path.join(OUT, "moat_double_count.json"), encoding="utf-8"))
    packs = {}
    for f in glob.glob(os.path.join(OUT, "*_gate_pack.json")):
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        packs[(p.get("nm") or "?").split(" ")[0]] = p

    items = []
    for r in d["rows"]:
        p = packs.get(r["t"])
        if not p:
            continue
        m = p.get("_meta") or {}
        ev, nu = (m.get("evidence") or {}), (m.get("nulls") or {})
        for pr in r["pairs"]:
            if not pr["shared_quote"]:
                continue        # 引用共有だけを読解に回す（機構語だけは弱い証拠＝別枠で記録）
            items.append({
                "id": f"{r['t']}:{pr['a']}x{pr['b']}",
                "ticker": r["t"], "name": r.get("nm"),
                "a": pr["a"], "b": pr["b"],
                "val_a": pr["va"], "val_b": pr["vb"],
                "weight_sum": pr["weight"],
                "shared_quote": pr["shared_quote"],
                "shared_len": pr["shared_quote_len"],
                "evidence_a": str(ev.get(pr["a"]) or ""),
                "nulls_a": str(nu.get(pr["a"]) or ""),
                "evidence_b": str(ev.get(pr["b"]) or ""),
                "nulls_b": str(nu.get(pr["b"]) or ""),
                "source": (m.get("source") or m.get("src") or ""),
            })

    items.sort(key=lambda x: x["id"])
    batches = [[] for _ in range(nb)]
    for i, it in enumerate(items):          # 等間隔＝A〜Zの全域が各班に入る
        batches[i % nb].append(it)
    out = {"tool": "moat_dc_batches", "n_items": len(items), "n_batches": nb,
           "batches": [{"i": i, "items": b} for i, b in enumerate(batches) if b]}
    with open(os.path.join(OUT, "moat_dc_batches.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"→ out/moat_dc_batches.json  {len(items)}件 / {len([b for b in batches if b])}班")
    for i, b in enumerate(batches):
        if b:
            print(f"   班{i}: {len(b)}件  {' '.join(sorted({x['ticker'] for x in b}))}")


if __name__ == "__main__":
    main()
