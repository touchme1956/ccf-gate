# night/retro_moat_holdout.py — irr=85規則のホールドアウト検定（2026-08-05新設）
#
# なぜこれが本物の検定か:
#   140社の読解で irr18=85 → P(継続)=0.68 という規則を見つけた。残り37社は
#   **その発見を見た後に、同一プロンプトで結末を知らない別の読解班が採点した**。
#   規則（P>=0.50 ∧ 捕捉>=継続組の1/3）は37社を見る前に確定している＝
#   探索側(140社)と検定側(37社)が分離した、この調査で唯一の真の out-of-sample。
#
# 限界（正直に）:
#   - 37社という小標本。P の信頼区間は広い（Wilson区間を併記する）。
#   - 打ち切りはティッカーのアルファベット順（R〜Z）なので結果に対しては概ね無作為だが、
#     業種構成は偏りうる（分析で確認する）。
# 実行: python3 night/retro_moat_holdout.py
import json, os, math, statistics, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(n):
    p = os.path.join(BASE, "out", n)
    return json.load(open(p)) if os.path.exists(p) else None


M = {r["t"]: r for r in load("retro_moat_2018.json")["rows"]}
H = load("retro_moat_2018_rest.json")
if not H:
    raise SystemExit("out/retro_moat_2018_rest.json が無い（残り37社の読解が未着）")
HM = {r["t"]: r for r in H["rows"]}
FR = {r["t"]: r for r in load("retro_frame_2018.json")["rows"]}
SIC = {r["ticker"]: r for r in load("retro_sic.json")["rows"]}

demoQ = [r for r in FR.values() if r["rf5"] >= 0.15
         and (r.get("fcfpos5") or 0) >= 4 and (r.get("opm") or -9) >= 0.10]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def build(src):
    return [{**r, "irr18": src[r["t"]].get("irr18"), "moat5": src[r["t"]].get("moat5"),
             "irr_quote": src[r["t"]].get("irr_quote"),
             "sic2": SIC.get(r["t"], {}).get("sic2")}
            for r in demoQ if r["t"] in src]


expl = build(M)      # 探索側 140社
hold = build(HM)     # 検定側 37社


def report(rows, label):
    base_k = sum(1 for r in rows if r["r18"] >= 0.15)
    base = base_k / len(rows)
    g = [r for r in rows if r["irr18"] == 85]
    if not g:
        print(f"\n=== {label}（n={len(rows)}・ベース {base:.2f}） ===")
        print("  irr85 該当0社 → 規則は発火しない")
        return {"n": len(rows), "base": round(base, 3), "n85": 0}
    k = sum(1 for r in g if r["r18"] >= 0.15)
    p = k / len(g)
    lo, hi = wilson(k, len(g))
    cap_need = base_k / 3
    ok = p >= 0.50 and k >= cap_need
    print(f"\n=== {label}（n={len(rows)}・継続{base_k}社・ベース {base:.2f}） ===")
    print(f"  irr85: n={len(g)}  P={p:.2f} [95%CI {lo:.2f}-{hi:.2f}]  捕捉{k}/{base_k}"
          f"  中央値{statistics.median(r['r18'] for r in g)*100:+.1f}%/年  lift{p-base:+.2f}")
    print(f"  事前登録基準（P>=0.50 ∧ 捕捉>={cap_need:.1f}社）: {'★合格' if ok else '不合格'}")
    for r in sorted(g, key=lambda r: -r["r18"]):
        mark = "○" if r["r18"] >= 0.15 else "×"
        print(f"    {mark} {r['t']:6s} {r['r18']*100:+6.1f}%/年  "
              f"SIC{r['sic2']} {SIC.get(r['t'], {}).get('sicDesc', '')[:30]}")
    return {"n": len(rows), "base": round(base, 3), "n85": len(g), "p": round(p, 3),
            "ci": [round(lo, 3), round(hi, 3)], "capture": k, "continuers": base_k,
            "pass": bool(ok), "firms": [r["t"] for r in g]}


e = report(expl, "探索側 140社（規則を見つけた側）")
h = report(hold, "検定側 37社（規則確定後に盲検で採点＝真のホールドアウト）")

allr = expl + hold
a = report(allr, "統合 177社")

# 参考: 他の欄が同じ検定を通るか（irr85だけが特別かの確認）
print("\n--- 対照: 他の定性欄は検定側で立つか ---")
for lab, f in (("moat5>=4", lambda r: (r.get("moat5") or 0) >= 4),
               ("moat5=5", lambda r: r.get("moat5") == 5),
               ("irr18>=75", lambda r: (r.get("irr18") or 0) >= 75)):
    g = [r for r in hold if f(r)]
    if len(g) < 5:
        print(f"  {lab:12s} n={len(g)} （少数）")
        continue
    p = sum(1 for r in g if r["r18"] >= 0.15) / len(g)
    print(f"  {lab:12s} n={len(g):3d}  P={p:.2f}  lift{p-h['base']:+.2f}")

json.dump({"generated": datetime.date.today().isoformat(),
           "note": "irr18=85規則のホールドアウト検定。探索140社→規則確定→検定37社は盲検採点",
           "explore": e, "holdout": h, "combined": a},
          open(os.path.join(BASE, "out", "retro_moat_holdout.json"), "w"),
          ensure_ascii=False, indent=1)
print("\n■ out/retro_moat_holdout.json へ記録")
