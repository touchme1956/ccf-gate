#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/make_chunks.py — 夜間バッチ審査のチャンク自動生成器(2026-07精査で新設)
背景: 投下パイプラインの歩留まりが構造的ボトルネック(審査済280→Ω75+は14社→今日買える新規1銘柄)。
質基準は不変のまま「審査スループット」を上げ、同時指値の本数(=投下頻度)を増やすのが目的。
供給源(優先順): gate1_queue(待ち行列155) → gate1_rescue_final/gw(椅子) → gate1_stalled(棚)
→ gate1_backlog(非優先low-pt)。既に out/{T}_gate_pack.json がある銘柄・SKIP銘柄は除外。
日本株(gate0_jp_queue)はSEC採取が効かない=EDINET経路のためチャンクに入れない。
使い方: python3 night/make_chunks.py   (既存chunkの連番の続きから10社/枚で生成)
"""
import json, glob, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SKIP = {"LLY", "MSFT", "ASML", "RMD"}   # hachimon_fetch.py の SKIP と同期

def tickers_of(path):
    if not os.path.exists(path):
        return []
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    rows = d if isinstance(d, list) else d.get("queue") or d.get("lines") or []
    out = []
    for r in rows:
        t = (r.get("ticker") or r.get("sec") or "") if isinstance(r, dict) else str(r)
        t = str(t).strip().upper()
        if t and re.fullmatch(r"[A-Z][A-Z.\-]{0,7}", t):
            out.append(t)
    return out

done = {os.path.basename(f).split("_gate_pack")[0].upper()
        for f in glob.glob("out/*_gate_pack.json")}
in_chunks = set()
for f in glob.glob("night/chunk*.txt"):
    in_chunks |= {t for t in open(f).read().split() if t}

seen, todo = set(), []
for src in ["gate1_queue.json", "gate1_rescue_final.json", "gate1_rescue_gw.json",
            "gate1_stalled.json", "gate1_backlog.json"]:
    for t in tickers_of(src):
        if t in seen or t in done or t in SKIP or t in in_chunks:
            continue
        seen.add(t); todo.append(t)

nums = [int(m.group(1)) for f in glob.glob("night/chunk*.txt")
        if (m := re.search(r"chunk(\d+)", f))]
start = max(nums) + 1 if nums else 1
made = 0
for i in range(0, len(todo), 10):
    with open(f"night/chunk{start + i // 10:02d}.txt", "w") as fp:
        fp.write(" ".join(todo[i:i + 10]) + "\n")
    made += 1
print(f"未審査 {len(todo)}社 → chunk{start:02d}〜{start + made - 1:02d}({made}枚)を生成")
print("進行はnight/progress.jsonへ。審査はagent_prompt_template.txt(正本はⅡ手順3と同期)で。")
