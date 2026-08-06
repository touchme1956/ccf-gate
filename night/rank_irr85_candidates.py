# night/rank_irr85_candidates.py — 全上場の機構語スキャンを「質」と突き合わせて候補を出す（2026-08-05新設）
#
# 入力: out/irr85_universe.json（EDGAR全文検索で機構語を持つ全企業）
#       gate0_all.csv（門0の機械値・全上場2,902社）
#       out/*_gate_pack.json（既に門にいる350社）
# 出力: out/irr85_candidates.json
#
# 仕分けの思想:
#   歴史が示したのは「機構語がある ∧ 質の実証がある」＝価格×質の実証を通った社の中で
#   irr=85 が P=0.71 を出した、という条件付きの話。だから機構語だけで拾うと大量の
#   低品質社が混ざる。門0の機械値（ROIC・利益率・FCF転換・営業黒字継続）で先に絞る。
#   **門0の一次ふるいと同じ数字を使う＝新しい基準を発明しない。**
# 実行: python3 night/rank_irr85_candidates.py [--min-roic 12] [--min-opm 10]
import json, os, sys, csv, glob, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_ROIC, MIN_OPM = 12.0, 10.0
for i, a in enumerate(sys.argv):
    if a == "--min-roic" and i + 1 < len(sys.argv):
        MIN_ROIC = float(sys.argv[i + 1])
    if a == "--min-opm" and i + 1 < len(sys.argv):
        MIN_OPM = float(sys.argv[i + 1])

U = json.load(open(os.path.join(BASE, "out", "irr85_universe.json")))
have = {os.path.basename(p).replace("_gate_pack.json", "")
        for p in glob.glob(os.path.join(BASE, "out", "*_gate_pack.json"))}

Q = {}
with open(os.path.join(BASE, "gate0_all.csv"), encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        t = (r.get("ticker") or "").strip()
        if t:
            Q[t] = r


def f(r, k):
    try:
        return float(r.get(k) or "")
    except Exception:
        return None


rows = []
for d in U["rows"]:
    t = d.get("ticker")
    if not t:
        continue
    q = Q.get(t)
    strong = d.get("strong") or []
    rows.append({
        "ticker": t, "cik": d["cik"], "name": (d.get("name") or "").split("  (")[0],
        "score_lang": d.get("score", 0), "strong": strong, "n_phrase": len(d.get("ph") or {}),
        "in_gate": t in have,
        "q_score": f(q, "score") if q else None,
        "roic": f(q, "roic_latest") if q else None,
        "roic_w5": f(q, "roic_worst5") if q else None,
        "opm": f(q, "opm") if q else None,
        "cagr5": f(q, "sales_cagr5") if q else None,
        "conv": f(q, "fcf_conv_5y") if q else None,
        "op_pos": (q or {}).get("op_all_pos") == "True",
        "in_gate0": q is not None,
    })

# 質の門: 門0の数字で絞る（roicは単年なので甘めに取り、後段の審査でthrough-cycle化する）
def pct(v):
    """gate0_all.csv は小数(0.1479)と%の両方がありうる——帯で判定して%へ揃える"""
    if v is None:
        return None
    return v * 100 if -1.5 < v < 1.5 else v


for r in rows:
    r["roic"] = pct(r["roic"])
    r["opm"] = pct(r["opm"])
    r["cagr5"] = pct(r["cagr5"])
    r["roic_w5"] = pct(r["roic_w5"])

cand = [r for r in rows if r["strong"] and r["in_gate0"]
        and (r["roic"] or -9) >= MIN_ROIC and (r["opm"] or -9) >= MIN_OPM and r["op_pos"]]
cand.sort(key=lambda r: (-r["score_lang"], -(r["roic"] or 0)))

print(f"=== 全上場からの『顧客側の再認定型』候補 ===")
print(f"  機構語スキャンの企業数: {U['n']:,}社（10-K/20-F・{U['window']}）")
print(f"  うち機構語(STRONG)あり: {sum(1 for r in rows if r['strong']):,}社")
print(f"  うち門0の母集団(2,902社)に居る: {sum(1 for r in rows if r['strong'] and r['in_gate0']):,}社")
print(f"  質の門(roic≥{MIN_ROIC} ∧ opm≥{MIN_OPM} ∧ 営業黒字5年)通過: **{len(cand)}社**")
print(f"  うち門に未収載(新顔): {sum(1 for r in cand if not r['in_gate'])}社\n")
print(f"  {'銘柄':8s}{'語':3s} {'roic':>6s}{'opm':>6s}{'cagr':>6s}{'conv':>6s}  門  機構語")
for r in cand[:60]:
    print(f"  {r['ticker']:8s}{r['score_lang']:3d} {r['roic'] or 0:6.1f}{r['opm'] or 0:6.1f}"
          f"{r['cagr5'] or 0:6.1f}{r['conv'] or 0:6.2f}  {'既' if r['in_gate'] else '新'}  "
          f"{','.join(r['strong'])[:52]}")

json.dump({"generated": datetime.date.today().isoformat(),
           "filter": {"min_roic": MIN_ROIC, "min_opm": MIN_OPM},
           "n_lang": sum(1 for r in rows if r["strong"]), "n_cand": len(cand),
           "candidates": cand, "all_lang": [r for r in rows if r["strong"]]},
          open(os.path.join(BASE, "out", "irr85_candidates.json"), "w"),
          ensure_ascii=False, indent=1)
print(f"\n■ out/irr85_candidates.json へ記録")
