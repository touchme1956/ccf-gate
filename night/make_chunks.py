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
import json, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SKIP = {"LLY", "MSFT", "ASML", "RMD"}   # hachimon_fetch.py の SKIP と同期

# ── 再審査モード（2026-08-10新設）────────────────────────────────────────────
# 【なぜ要るか】下の本体は `if t in done` で**既にパックのある社を除外する**。
#   これは「未審査の社を漏らさない」ためには正しいが、裏返すと
#   **再審査は構造的にキューへ載らない**——新しい10-Kが出ても、期末後にBSが激変しても、
#   納品検査でFAILしても、検出器が見つけたものが待ち行列に入らない。
#   ＝今日の監査が見つけた「検出は自動・作業は手動」の断絶の正体。
#   night/enqueue_reaudit.py が検出器6本の出力を優先度つきの待ち行列にするので、
#   ここはそれを rechunkNN.txt へ落とすだけ（**新規審査の chunkNN.txt とは別系列**にして
#   「まだ見ていない社」と「見たがもう一度見る社」を混ぜない）。
if "--reaudit" in sys.argv:
    q = json.load(open("night/reaudit_queue.json", encoding="utf-8"))
    rows = q.get("rows") or []
    lim = None
    if "--top" in sys.argv:
        i = sys.argv.index("--top")
        if i + 1 < len(sys.argv):
            lim = int(sys.argv[i + 1])
    already = set()
    for f in glob.glob("night/rechunk*.txt"):
        already |= {t for t in open(f).read().split() if t}
    todo_r = [r["t"] for r in rows if r["t"] not in already]
    if lim:
        todo_r = todo_r[:lim]
    ns = [int(m.group(1)) for f in glob.glob("night/rechunk*.txt")
          if (m := re.search(r"rechunk(\d+)", f))]
    s0 = max(ns) + 1 if ns else 1
    n = 0
    for i in range(0, len(todo_r), 10):
        with open(f"night/rechunk{s0 + i // 10:02d}.txt", "w") as fp:
            fp.write(" ".join(todo_r[i:i + 10]) + "\n")
        n += 1
    print(f"再審査 {len(todo_r)}社 → rechunk{s0:02d}〜{s0 + n - 1:02d}({n}枚)を生成"
          if n else "再審査: 新規チャンクなし（待ち行列は既に rechunk に載っている）")
    print("審査は night/agent_prompt_template.txt（日本株は _jp）。"
          "**理由は night/reaudit_queue.json の reasons に書いてある**——"
          "何を直すために再審査するのかを読んでから原本へ当たること。")
    sys.exit(0)

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
print(f"未審査 {len(todo)}社 → chunk{start:02d}〜{start + made - 1:02d}({made}枚)を生成" if made else "米国: 新規チャンクなし")

# --- 日本株チャンク(2026-07): gate0_jp_queueから未審査分を jp_chunkNN.txt へ。コード貼り不要の一括再審査用 ---
jp_todo = []
try:
    dq = json.load(open("gate0_jp_queue.json", encoding="utf-8"))
    rows = dq.get("queue") if isinstance(dq, dict) else dq
    for r in rows or []:
        c = str(r.get("sec") or r.get("ticker") or "").strip()
        if c and re.fullmatch(r"\d{4,5}", c) and c not in done:
            jp_todo.append(c)
except Exception as e:
    print(f"▲ JPキュー読込不可: {e}")
for f in glob.glob("night/jp_chunk*.txt"):
    jp_todo = [t for t in jp_todo if t not in open(f).read().split()]
jn = [int(m.group(1)) for f in glob.glob("night/jp_chunk*.txt") if (m := re.search(r"jp_chunk(\d+)", f))]
js0 = max(jn) + 1 if jn else 1
jm = 0
for i in range(0, len(jp_todo), 10):
    with open(f"night/jp_chunk{js0 + i // 10:02d}.txt", "w") as fp:
        fp.write(" ".join(jp_todo[i:i + 10]) + "\n")
    jm += 1
print(f"日本株: 未審査{len(jp_todo)}社 → jp_chunk{js0:02d}〜{js0 + jm - 1:02d}({jm}枚)。審査はagent_prompt_template_jp.txtで" if jm else "日本株: 新規チャンクなし")

# --- パック索引(門の一括取込ボタン用): 門がGitHub Pages経由でfetchできる目録 ---
idx = sorted(os.path.basename(f) for f in glob.glob("out/*_gate_pack.json"))
json.dump({"packs": idx}, open("out/packs_index.json", "w"), ensure_ascii=False, indent=0)
print(f"→ out/packs_index.json 更新({len(idx)}パック)")
print("進行はnight/progress.jsonへ。審査はagent_prompt_template.txt(正本はⅡ手順3と同期)で。")
