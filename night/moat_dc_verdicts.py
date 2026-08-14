#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/moat_dc_verdicts.py — 二重計上の読解の結果を在庫へ落とし、機械の当てと突き合わせる（2026-08-13）

■ やること
  1. ワークフローの返り値（判定 + 反証）を out/moat_dc_verdicts.json へ
  2. **読み手とは独立の粗い符号判定**（共有引用に肯定語/否定語のどちらが多いか）と突き合わせ、
     食い違いを名指しで出す。⚠これは正誤の判定ではなく**二つの目が違うことを言った場所**の一覧
  3. 確定した「上向き二重計上」を、影の計測(shadow_moat_dedup / shadow_moat_merge)が読める形で出す

■ ⚠ 判定を作らない
  読み手の verdict と反証の refuted をそのまま記録する。ここで多数決や書き換えをしない。
  （二つの検査器が違うことを言ったら、**どちらかに寄せずに両方見せる**のがこの台帳の作法）

使い方:
  python3 night/moat_dc_verdicts.py --in <workflow_result.json>
  python3 night/moat_dc_verdicts.py --journal <workflows/wf_xxx/journal.jsonl>
      ← ワークフローの返り値の形に依存せず journal から直接組む（返り値が取れないときの経路）
"""
import json, os, re, sys, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

NEG = [r"low barrier", r"limited barrier", r"barriers to entry .{0,20}(are |is )?(low|limited)",
       r"highly competitive", r"intense competition", r"many competitors", r"numerous competitors",
       r"new competitors", r"rapidly? (chang|evolv)", r"price erosion", r"substantial competition",
       r"competitors .{0,30}greater", r"cannot specify", r"no single competitor",
       r"激しい競争", r"参入障壁が低", r"競合"]
POS = [r"only manufacturer", r"sole ", r"exclusive", r"no competition", r"free from .{0,20}competition",
       r"must be certified", r"qualified by", r"requalif", r"re-qualif", r"switching cost",
       r"network effect", r"installed base", r"economies of scale", r"multi-year", r"long-term",
       r"cannot be duplicated", r"proprietary", r"patent"]


def sign(q):
    q = (q or "").lower()
    n = sum(1 for p in NEG if re.search(p, q))
    p = sum(1 for p_ in POS if re.search(p_, q))
    return "neg" if n > p else ("pos" if p > n else "mixed")


def main():
    if "--journal" in sys.argv:
        jp = sys.argv[sys.argv.index("--journal") + 1]
        if not os.path.exists(jp):
            sys.exit(f"journal が無い: {jp}")
        v, c = [], []
        for line in open(jp, encoding="utf-8"):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "result":
                continue
            r = e.get("result")
            if not isinstance(r, dict):
                continue
            # ⚠ 段の判別は**返り値の形**で行う（ラベルに依存しない＝スクリプトを書き換えても壊れない）
            if isinstance(r.get("verdicts"), list):
                v += r["verdicts"]
            if isinstance(r.get("results"), list):
                c += r["results"]
        # 同じ班が再実行されると重複しうるので id で一意化（**後勝ち**にしない＝最初の判定を残す）
        seen = set(); v2 = []
        for x in v:
            if x.get("id") in seen:
                continue
            seen.add(x.get("id")); v2.append(x)
        seen = set(); c2 = []
        for x in c:
            if x.get("id") in seen:
                continue
            seen.add(x.get("id")); c2.append(x)
        wf = {"verdicts": v2, "checks": c2}
    else:
        src = sys.argv[sys.argv.index("--in") + 1] if "--in" in sys.argv else None
        if not src or not os.path.exists(src):
            sys.exit("--in か --journal を渡すこと")
        wf = json.load(open(src, encoding="utf-8"))
    verdicts = wf.get("verdicts") or []
    checks = wf.get("checks") or []
    refuted = {c["id"]: c for c in checks if c.get("refuted")}
    kept = {c["id"]: c for c in checks if not c.get("refuted")}

    b = json.load(open(os.path.join(OUT, "moat_dc_batches.json"), encoding="utf-8"))
    items = {x["id"]: x for bb in b["batches"] for x in bb["items"]}
    sc = {}
    p = os.path.join(OUT, "score_all.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        sc = {r["t"]: r for r in (d if isinstance(d, list) else d.get("rows", []))}

    rows = []
    for v in verdicts:
        it = items.get(v["id"]) or {}
        final = v["verdict"]
        if v["verdict"] == "up" and v["id"] in refuted:
            final = (refuted[v["id"]].get("revised_verdict") or "different")
        r = dict(v)
        r["final"] = final
        r["refuted"] = v["id"] in refuted
        r["refute_reason"] = (refuted.get(v["id"]) or kept.get(v["id"]) or {}).get("reason")
        r["shared_quote"] = it.get("shared_quote")
        r["weight_sum"] = it.get("weight_sum")
        r["machine_sign"] = sign(it.get("shared_quote"))
        s = sc.get(v.get("ticker")) or {}
        r["omega"], r["buy"], r["moat"] = s.get("s"), bool(s.get("buy")), s.get("moat")
        rows.append(r)

    missing = sorted(set(items) - {v["id"] for v in verdicts})
    # ★2026-08-13 是正: 初版は「反証で潰れなかった up」を確定として数えたが、
    #   **反証をまだ受けていない up まで確定に入れていた**＝この台帳が繰り返し戒める
    #   「『測っていない』と『測って問題なし』の取り違え」を、自分の器の中で作っていた。
    #   → 反証を**実際に受けた**ものだけを確定とし、未検証は別の袋へ入れて名指しで出す。
    checked = {c["id"] for c in checks}
    confirmed = [r for r in rows if r["final"] == "up" and r["id"] in checked]
    unverified = [r for r in rows if r["verdict"] == "up" and r["id"] not in checked]

    cnt = collections.Counter(r["final"] for r in rows)
    print(f"■ 読解 {len(rows)}件 / 渡した対 {len(items)}件"
          + (f"  ⚠**返ってこなかった {len(missing)}件**: {' '.join(missing)}" if missing else ""))
    print(f"  最終判定: {dict(cnt)}")
    print(f"  up の主張 {sum(1 for r in rows if r['verdict']=='up')}件 → 反証を受けた "
          f"{sum(1 for r in rows if r['verdict']=='up' and r['id'] in checked)}件"
          f"（潰れた {sum(1 for r in rows if r['verdict']=='up' and r['refuted'])}件 / "
          f"**残った {len(confirmed)}件**）")
    if unverified:
        print(f"  ⏳**まだ反証を受けていない up が {len(unverified)}件**"
              "——確定ではない（『測っていない』を『測って問題なし』にしない）:")
        for r in unverified:
            print(f"     {r['ticker']:<7} {r['a']}×{r['b']}  Ω{(r.get('omega') or 0):.1f}"
                  + ("  🟢投下可" if r["buy"] else ""))
    print()

    # ★読み手 vs 機械の粗い符号（食い違いを名指しで出す＝どちらかが誤っている場所）
    cross = collections.Counter((r["machine_sign"], r["final"]) for r in rows)
    print("── 読み手の判定 × 機械の粗い符号（独立な二つの目）──")
    print(f"  {'':8}" + "".join(f"{k:>11}" for k in ("up", "down", "different", "unclear")))
    for s in ("pos", "neg", "mixed"):
        print(f"  {s:<8}" + "".join(f"{cross.get((s,k),0):>11}" for k in ("up", "down", "different", "unclear")))
    odd = [r for r in rows if (r["machine_sign"] == "neg" and r["final"] == "up")
           or (r["machine_sign"] == "pos" and r["final"] == "down")]
    if odd:
        print(f"  ⚠符号が逆に見える {len(odd)}件（読み手が正しいことも多いが、必ず中身を見る）:")
        for r in odd[:10]:
            print(f"     {r['ticker']:<7} {r['a']}×{r['b']}  機械={r['machine_sign']} / 読み手={r['final']}")
    print()

    if confirmed:
        print("── ★反証を通った「上向き二重計上」──")
        for r in sorted(confirmed, key=lambda x: -(x.get("omega") or 0)):
            mark = "🟢" if r["buy"] else "  "
            print(f"  {mark}{r['ticker']:<7} Ω{(r.get('omega') or 0):>5.1f}  {r['a']}×{r['b']}"
                  f"  重み計 {r['weight_sum']:.2f}  残すべき柱={r.get('keep') or '—'}")
            print(f"        {(r.get('reason') or '')[:190]}")
    else:
        print("── 反証を通った「上向き二重計上」は **0件** ──")

    out = {"tool": "moat_dc_verdicts", "rev": "r2",
           "n_items_sent": len(items), "n_verdicts": len(rows), "n_missing": len(missing),
           "missing": missing, "counts": dict(cnt),
           "cross_machine_reader": {f"{k[0]}/{k[1]}": v for k, v in cross.items()},
           "n_unverified_up": len(unverified),
           "confirmed_up": [{"ticker": r["ticker"], "a": r["a"], "b": r["b"], "id": r["id"],
                             "keep": r.get("keep"), "reason": r.get("reason")} for r in confirmed],
           "unverified_up": [{"ticker": r["ticker"], "a": r["a"], "b": r["b"], "id": r["id"]}
                             for r in unverified],
           "rows": rows}
    with open(os.path.join(OUT, "moat_dc_verdicts.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n→ out/moat_dc_verdicts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
