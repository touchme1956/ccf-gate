#!/usr/bin/env python3
# night/retro_collect_moat.py — 追試の読解ワークフローの返り値を out/retro_moat_{asof}.json へまとめる（2026-08-05新設）
#
# ワークフローの journal.jsonl（各班の返り値がそのまま入っている）を読み、
# 読解リストの全社ぶんの行に整える。**読解リストにいて返って来なかった社は
# 欠測として明示**する（黙って落とすと脱落の偏りが見えなくなる）。
#
# 使い方: python3 night/retro_collect_moat.py --asof 2013 --dir <workflow transcript dir>
import json, os, sys, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
VALID = {100, 85, 70, 50, None}


def harvest(d):
    rows, seen = [], set()
    for p in [os.path.join(d, "journal.jsonl")] + sorted(glob.glob(os.path.join(d, "agent-*.jsonl"))):
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            for cand in (o, o.get("result"), o.get("value"), o.get("output")):
                if isinstance(cand, dict) and isinstance(cand.get("rows"), list):
                    for r in cand["rows"]:
                        t = (r or {}).get("ticker")
                        if t and t not in seen:
                            seen.add(t)
                            rows.append(r)
    return rows


def main():
    a = sys.argv
    asof = (a[a.index("--asof") + 1] if "--asof" in a else "2013")
    d = a[a.index("--dir") + 1] if "--dir" in a else None
    if not d:
        sys.exit("--dir にワークフローの transcript dir を渡す")
    rows = harvest(d)
    for r in rows:
        v = r.get("irr")
        if isinstance(v, str):
            r["irr"] = int(v) if v.strip().isdigit() else None
        if r.get("irr") not in VALID:
            r["irr_raw"] = r.get("irr")
            r["irr"] = min(VALID - {None}, key=lambda g: abs(g - r["irr"])) if isinstance(r.get("irr"), (int, float)) else None
    rl = json.load(open(os.path.join(OUT, f"retro_readlist_{asof}.json"), encoding="utf-8"))
    want = [r["ticker"] for r in rl["rows"]]
    got = {r["ticker"] for r in rows}
    missing = [t for t in want if t not in got]
    extra = [t for t in got if t not in want]
    o = {"generated": "2026-08-05", "asof": asof, "source_dir": d,
         "n": len(rows), "requested": len(want), "missing": missing, "extra": extra,
         "note": f"{asof}-07-01以前に提出された10-K/20-Fのみを盲検で読み、門のirr規約で採点。引用必須。リターンは読解班に渡していない。",
         "rows": [r for r in rows if r["ticker"] in want]}
    p = os.path.join(OUT, f"retro_moat_{asof}.json")
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {p}（回収 {len(o['rows'])}/{len(want)}社・未回収 {len(missing)}社{'：' + ','.join(missing[:12]) if missing else ''}）")


if __name__ == "__main__":
    main()
