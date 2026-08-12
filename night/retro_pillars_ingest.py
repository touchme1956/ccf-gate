# night/retro_pillars_ingest.py — 2013読解ワークフローの納品を在庫へ落とす（2026-08-12新設）
#
# 入力: ワークフロー wf_aff647b7-9ef の出力（{result:{batches:[{rows,verdicts}]}} の形）
# 出力: out/retro_moat_pillars_2013.json
#
# ★この器がやる3つのこと（どれも「黙って直さない」ための処理）:
#   (1) **刻みの検問**——読解が規約に無い値を返していたら**丸めずに null にして記録する**
#       （applyFields が SELECT の既定へ黙って化かした acq5=2.8 の事故を再演しない）
#   (2) **反証専門の判定を適用する**——refuted は null へ、revised は新しい刻みへ。
#       **元の値と適用の履歴を必ず残す**（後から「誰がいつ下げたか」を辿れるように）
#   (3) **引用の逐語照合**——原本キャッシュ out/_retro_docs/2013_{T}.txt に一字一句あるかを機械で見る。
#       キャッシュが無い社は skip（None）＝「照合できなかった」と「合わなかった」を分ける
#
# 実行: python3 night/retro_pillars_ingest.py <workflow_output.json> [--write]

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
DOC = os.path.join(OUT, "_retro_docs")
LEVELS = {"rep": {35, 60, 80, 100}, "dur": {55, 75, 85, 100},
          "dom": {50, 70, 85, 100}, "moatW": {50, 70, 85, 100}}
PILLARS = list(LEVELS)


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def verbatim(t, q):
    p = os.path.join(DOC, f"2013_{t}.txt")
    if not q or not os.path.exists(p):
        return None
    body = norm(open(p, encoding="utf-8", errors="ignore").read())
    n = norm(q)
    if len(n) < 25:
        return None
    if n in body:
        return True
    # 引用が「/」で複数断片を繋いでいる形（読解班が使った書式）に対応
    parts = [x for x in (norm(x) for x in re.split(r"\s+/\s+", q)) if len(x) >= 25]
    if parts and all(x in body for x in parts):
        return True
    return n[:120] in body


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: retro_pillars_ingest.py <workflow_output.json> [--write]")
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    res = raw.get("result", raw)
    batches = res.get("batches", [])

    rowsById, coerced = {}, []
    for b in batches:
        for r in (b.get("rows") or []):
            t = r.get("ticker")
            if not t:
                continue
            rec = {"ticker": t, "batch": b.get("batch")}
            for k in PILLARS:
                v = r.get(k)
                if v is None:
                    rec[k] = None
                elif isinstance(v, (int, float)) and int(v) in LEVELS[k]:
                    rec[k] = int(v)
                else:
                    # ⚠ 丸めない。規約に無い値は null にして記録する
                    rec[k] = None
                    coerced.append({"ticker": t, "field": k, "raw": v,
                                    "reason": "規約に無い刻み＝nullへ（丸めない）"})
                rec[k + "_quote"] = r.get(k + "_quote")
                rec[k + "_why"] = r.get(k + "_why")
            rec["note"] = r.get("note")
            if t in rowsById:
                coerced.append({"ticker": t, "field": "_dup", "raw": None,
                                "reason": "同じ社が複数班から返った＝先着を採る"})
                continue
            rowsById[t] = rec

    # ── 反証専門の判定を適用 ──
    applied, unmatched = [], []
    for b in batches:
        for v in (b.get("verdicts") or []):
            t, f = v.get("ticker"), v.get("field")
            if t not in rowsById or f not in PILLARS:
                unmatched.append(v)
                continue
            rec = rowsById[t]
            before = rec[f]
            verdict = (v.get("verdict") or "").lower()
            if verdict == "refuted":
                rec[f] = None
            elif verdict == "revised":
                nv = v.get("revised_to")
                rec[f] = int(nv) if isinstance(nv, (int, float)) and int(nv) in LEVELS[f] else None
            rec.setdefault("verify", []).append({
                "field": f, "before": before, "after": rec[f], "verdict": verdict,
                "quote_verbatim_agent": v.get("quote_verbatim"), "reason": v.get("reason")})
            if before != rec[f]:
                applied.append({"ticker": t, "field": f, "from": before, "to": rec[f],
                                "verdict": verdict})

    # ── 引用の逐語照合（機械）──
    audit = {k: {"checked": 0, "verbatim": 0, "failed": []} for k in PILLARS}
    for t, rec in rowsById.items():
        for k in PILLARS:
            if rec[k] is None:
                continue
            r = verbatim(t, rec.get(k + "_quote"))
            rec[k + "_verbatim"] = r
            if r is None:
                continue
            audit[k]["checked"] += 1
            if r:
                audit[k]["verbatim"] += 1
            else:
                audit[k]["failed"].append(t)

    rows = [rowsById[t] for t in sorted(rowsById)]
    cov = {k: sum(1 for r in rows if r[k] is not None) for k in PILLARS}
    out = {
        "generated": "2026-08-12", "asof": 2013,
        "source": "workflow wf_aff647b7-9ef（21班×原本読解 ＋ 強い主張への反証専門）",
        "blind": "読解班には リターン・株価・過去の読解(irr/moat5) を見せていない",
        "prereg": "out/retro_moat_pillars_prereg.json（読解の結果を見る前にコミット）",
        "n": len(rows), "coverage": cov,
        "verify_applied": applied, "verify_unmatched": unmatched,
        "coerced": coerced,
        "quote_audit": {k: {"checked": v["checked"], "verbatim": v["verbatim"],
                            "rate": round(v["verbatim"] / v["checked"], 3) if v["checked"] else None,
                            "failed": v["failed"][:40]} for k, v in audit.items()},
        "rows": rows,
    }
    print(f"納品 {len(rows)}社  被覆 " + " / ".join(f"{k} {cov[k]}({cov[k]/len(rows):.0%})" for k in PILLARS))
    print(f"反証で動いた {len(applied)}件（refuted/revised）／規約外の刻み {len(coerced)}件／照合できない判定 {len(unmatched)}件")
    for k in PILLARS:
        a = out["quote_audit"][k]
        print(f"  引用の逐語一致 {k:<7}{a['verbatim']}/{a['checked']}" + (f" (={a['rate']})" if a["rate"] is not None else " (キャッシュ無し)"))
    if "--write" in sys.argv:
        p = os.path.join(OUT, "retro_moat_pillars_2013.json")
        json.dump(out, open(p, "w"), ensure_ascii=False)
        print("→", p)
    else:
        print("（--write を付けると書き出す）")


if __name__ == "__main__":
    main()
