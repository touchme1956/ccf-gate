# night/retro_profitability.py — 「複利を達成した銘柄は全部黒字だったのか」の実測（2026-08-05新設）
#
# 問い（ユーザー）: 門0は一次ふるいで「営業黒字5年継続」を要求している。
#   もし歴史の勝者に赤字組がいたなら、門は構造的に取り逃していることになる。
#
# 測り方: 2013年入口→13.1年の実現リターン(配当込み)と、入口時点(2009-2013)の営業利益の
#   赤字年数を突き合わせる。**勝者の特徴ではなく母集団の基礎率で裁く**
#   （retro_winner_profile.py の教訓——勝者だけ見ると入口の特徴を予測力と混同する）。
# 実行: python3 night/retro_profitability.py
import json, os, zipfile, datetime, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = {r["ticker"]: r for r in json.load(open(os.path.join(BASE, "out", "retro_cohort_2013.json")))["rows"] if r.get("ticker")}
R = {r["ticker"]: r for r in json.load(open(os.path.join(BASE, "out", "retro_returns_2013_all.json")))["rows"] if r.get("tr_cagr") is not None}
z = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip"))
N = set(z.namelist())


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def loss_years(cik, lo=2009, hi=2013):
    fn = f"CIK{cik:010d}.json"
    if fn not in N:
        return None
    g = json.loads(z.read(fn)).get("facts", {}).get("us-gaap", {})
    n = g.get("OperatingIncomeLoss")
    if not n:
        return None
    s = {}
    for e in n.get("units", {}).get("USD", []):
        en, st = e.get("end", ""), e.get("start", "")
        if not en or not st:
            continue
        try:
            if not (330 <= (d2(en) - d2(st)).days <= 400):
                continue
        except Exception:
            continue
        y = int(en[:4])
        if lo <= y <= hi and (y not in s or e.get("filed", "") > s[y][1]):
            s[y] = (e["val"], e.get("filed", ""))
    return sum(1 for v in s.values() if v[0] < 0) if len(s) >= 4 else None


rows = []
for t in R:
    if t not in C:
        continue
    k = loss_years(C[t]["cik"])
    if k is None:
        continue
    rows.append({"t": t, "r": R[t]["tr_cagr"], "nl": k})

print(f"=== 2013年入口→13.1年（n={len(rows)}社・営業赤字年数別の基礎率）===")
print(f"  {'赤字年数':14s}{'社数':>6s}{'P(年率15%+)':>12s}{'年率中央値':>11s}{'P(マイナス)':>11s}")
out = {}
for lab, f in (("0年(全期黒字)", lambda r: r["nl"] == 0), ("1年だけ", lambda r: r["nl"] == 1),
               ("2年", lambda r: r["nl"] == 2), ("3年以上", lambda r: r["nl"] >= 3)):
    g = [r for r in rows if f(r)]
    if len(g) < 10:
        continue
    p = sum(1 for r in g if r["r"] >= 0.15) / len(g)
    neg = sum(1 for r in g if r["r"] < 0) / len(g)
    med = statistics.median(r["r"] for r in g)
    out[lab] = {"n": len(g), "p15": round(p, 3), "med": round(med, 4), "pneg": round(neg, 3)}
    print(f"  {lab:14s}{len(g):6d}{p:12.2f}{med*100:10.1f}%{neg:11.2f}")

win = [r for r in rows if r["r"] >= 0.15]
nb = [r for r in win if r["nl"] > 0]
print(f"\n  勝者{len(win)}社のうち入口で赤字年ありは {len(nb)}社 ({len(nb)/len(win)*100:.0f}%)")
one = [r for r in win if r["nl"] == 1]
print(f"  うち赤字1年だけ {len(one)}社（循環の谷を1回踏んだ組）: "
      + " ".join(sorted(r["t"] for r in one)[:14]))

json.dump({"generated": datetime.date.today().isoformat(), "n": len(rows),
           "note": "門0の『営業黒字5年継続』が歴史の勝者を取り逃していないかの検証。母集団の基礎率で裁く",
           "buckets": out, "winners": len(win), "winners_with_loss_year": len(nb)},
          open(os.path.join(BASE, "out", "retro_profitability.json"), "w"), ensure_ascii=False, indent=1)
print("■ out/retro_profitability.json へ記録")
