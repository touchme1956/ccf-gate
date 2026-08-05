# night/audit_irr85.py — irr=85 の根拠を歴史で効いた機構に照らす監査（2026-08-05新設）
#
# なぜこの監査が要るか:
#   2026-08-05の歴史検証で、継続組（途中乗りで後半も年率15%+）を事前に分けた唯一の変数が
#   irr=85（顧客側の再認定が要る型）だと判った（P=0.68・等加重年率+25.1% vs SPY15.0%）。
#   ということは **irr欄の測定精度がそのまま門の精度になる**。値は動かさず、
#   「その根拠は歴史で効いた機構を示しているか」だけを仕分けて作業リストにする。
#
# 歴史で効いた機構（勝った14社の引用から抽出・確立形 P=0.79）:
#   A 顧客工程への認定組込   … "once ... qualified it, the manufacturer generally maintains
#                              that selection" / "qualification requirements in customers'
#                              fabrication processes" / "high customer re-qualification costs"
#   B 顧客の設計への組込     … "designed into our customers' products or systems" /
#                              "design win" / "significant barriers to subsequent supplier changes"
#   C 第三者機関が用途を認定 … "qualified for the application by the OEM, the U.S. DoD, the FAA"
#   D 顧客の認定業者名簿     … "consolidate their lists of qualified suppliers"
#   E 長期の認定期間         … "lengthy/stringent qualification periods prior to volume orders"
#
# 歴史で効かなかった型（願望形 P=0.40）:
#   "strive to" / "ability to achieve qualification" / "we work closely with" /
#   "customers evaluating and qualifying"（＝まだ固着していない）
#
# 規約が明示的に除外している型（CLAUDE.md v9.9.49）:
#   「自社が取得する側の認証（ISO27001・政府調達・自社のFDA認可）は当たらない」
#   ——85は*顧客側*の再認定が要ることを示さねばならない。
#
# 出力は作業リストであって有罪判決ではない（引用が短いだけの社が多数含まれる）。
# 実行: python3 night/audit_irr85.py [--all]
import json, os, glob, re, sys, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = "--all" in sys.argv

MECH = {  # 歴史で効いた機構（顧客側が動かねばならないことを示す語）
    "A_工程認定": [r"qualif\w* (?:requirements? )?in (?:our )?customers?['’]? (?:fab|manufactur|produc)",
                r"once .{0,60}qualif", r"customer re-?(?:formulation|qualification)",
                r"maintains that selection", r"再認定", r"顧客.{0,20}工程.{0,10}認定"],
    "B_設計組込": [r"design(?:ed)? into (?:our )?customers?", r"design[- ]win",
                r"barriers to subsequent supplier change", r"integrat\w+ into .{0,30}production line"],
    "C_第三者認定": [r"qualified for the application by", r"approved by the (?:FAA|U\.S\. Department)",
                 r"certification under customer", r"regulatory standards required to meet"],
    "D_認定業者名簿": [r"lists? of qualified suppliers", r"qualified supplier"],
    "E_長期認定期間": [r"(?:lengthy|long|stringent) .{0,20}qualification (?:period|process)",
                 r"qualification periods? prior to volume"],
}
ASP = [r"\bstrive\b", r"ability to achieve", r"we work closely with", r"assist customers",
       r"seek to\b", r"aim to\b", r"evaluating and qualifying", r"continued to work",
       r"depends on our (?:ability|products being)"]
SELF = [r"we (?:must )?(?:obtain|receive|maintain).{0,40}(?:clearance|approval|patent)",
        r"our ability to obtain and maintain .{0,20}patent", r"510\(k\)", r"premarket notification",
        r"ISO ?\d{4,5}", r"当社.{0,10}(?:取得|認可|承認)"]


def hits(text, pats):
    t = text.lower()
    return [p for p in pats if re.search(p, t, re.I)]


S = {r["t"]: r for r in json.load(open(os.path.join(BASE, "out", "score_all.json")))}
rows = []
for p in glob.glob(os.path.join(BASE, "out", "*_gate_pack.json")):
    t = os.path.basename(p).replace("_gate_pack.json", "")
    try:
        j = json.load(open(p))
    except Exception:
        continue
    d = j.get("data", j)
    if d.get("irr") != 85:
        continue
    ev = str(((j.get("_meta") or {}).get("evidence") or {}).get("irr") or "")
    m = {k: hits(ev, v) for k, v in MECH.items()}
    mech = [k for k, v in m.items() if v]
    s = S.get(t, {})
    rows.append({"t": t, "s": s.get("s", 0), "moat": s.get("moat", 0), "buy": s.get("buy"),
                 "mech": mech, "asp": bool(hits(ev, ASP)), "self_only": bool(hits(ev, SELF)) and not mech,
                 "evlen": len(ev), "ev": ev})

j_zone = [r for r in rows if r["s"] >= 72]
print(f"=== irr=85 の根拠監査（全{len(rows)}社／判定圏Ω72+ {len(j_zone)}社） ===")
print("  歴史で効いた機構(A-E)を根拠が示しているか。値は一切変えない＝作業リスト")


def verdict(r):
    if r["mech"]:
        return "✓機構あり" + ("（願望形の語も混在）" if r["asp"] else "")
    if r["self_only"]:
        return "⚠自社取得の認証のみ（規約が明示除外）"
    if r["asp"]:
        return "⚠願望形のみ（歴史ではP=0.40）"
    return "△機構を示す語なし（引用が短い/要約のみ）"


for r in sorted(j_zone, key=lambda r: -r["s"]):
    b = "🟢" if r["buy"] else "  "
    print(f"\n  {b}{r['t']:6s} Ω{r['s']:5.1f} 堀{r['moat']:5.1f}  {verdict(r)}"
          + (f"  機構={','.join(r['mech'])}" if r["mech"] else ""))
    print(f"      根拠({r['evlen']}字): {r['ev'][:150]}")

if ALL:
    print(f"\n--- Ω72未満の{len(rows)-len(j_zone)}社（参考） ---")
    for r in sorted([x for x in rows if x["s"] < 72], key=lambda r: -r["s"]):
        print(f"  {r['t']:6s} Ω{r['s']:5.1f} {verdict(r)}")

cnt = {}
for r in j_zone:
    k = verdict(r).split("（")[0]
    cnt[k] = cnt.get(k, 0) + 1
print(f"\n判定圏の集計: {cnt}")
print("※△は『根拠が短い』ことの検出であって誤りの証明ではない。原本を読み直す先を絞る道具")
json.dump({"generated": datetime.date.today().isoformat(),
           "note": "irr=85の根拠を歴史で効いた機構(A-E)に照らす監査。値は変更しない",
           "n_total": len(rows), "n_judgment_zone": len(j_zone),
           "rows": [{k: v for k, v in r.items() if k != "ev"} | {"verdict": verdict(r)}
                    for r in sorted(rows, key=lambda r: -r["s"])]},
          open(os.path.join(BASE, "out", "audit_irr85.json"), "w"), ensure_ascii=False, indent=1)
print("■ out/audit_irr85.json へ記録")
