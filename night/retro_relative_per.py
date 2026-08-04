# night/retro_relative_per.py — 「PER ≤ S&P500実績PER×k」の相対線を過去に当てる検証（2026-08-04新設）
#
# 問い: 提案中の門X改定案「堀の確度 ∧ PER ≤ 市場×1.2」を asofビンテージに当てていたら、
#   13年の実現トータルリターンはどうなっていたか。線の倍率 k の感度も出す。
# 錨: out/sp500_pe_monthly.json（multpl・実績GAAP・過去も今も同じ定義＝基準を割らない）
# 限界（正直に）:
#   - 質の代理は score7（機械の背骨）。本物の門は堀の定性審査を重ねるので、これは下界の検証
#   - リターンは Yahoo に系列が残る社のみ＝生存者条件付き。未測数は必ず並記する
# 実行: python3 night/retro_relative_per.py --asof 2013
import json, os, sys, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASOF = 2013
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])

cohort = json.load(open(os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")))["rows"]
pe = json.load(open(os.path.join(BASE, "out", "sp500_pe_monthly.json")))["series"]
ANCHOR = pe[f"{ASOF}-07"]


def load(name):
    p = os.path.join(BASE, "out", name)
    return json.load(open(p)) if os.path.exists(p) else None


pers = load(f"retro_per_{ASOF}_all.json") or load(f"retro_per_{ASOF}.json")
rets = load(f"retro_returns_{ASOF}_all.json") or load(f"retro_returns_{ASOF}.json")
PER = {r["ticker"]: r["per"] for r in pers["rows"]}
TR = {r["ticker"]: r for r in rets["rows"]}
C = {r["ticker"]: r for r in cohort if r.get("ticker")}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def stats(tk, label):
    xs = sorted(TR[t]["tr_cagr"] for t in tk if t in TR and TR[t].get("tr_cagr") is not None)
    unmeasured = sum(1 for t in tk if t not in TR or TR[t].get("tr_cagr") is None)
    if not xs:
        print(f"  {label}: 実測0（未測 {unmeasured}）")
        return
    mean = round(statistics.mean(xs), 4)
    mdd = med([TR[t].get("mdd") for t in tk if t in TR and TR[t].get("tr_cagr") is not None])
    print(f"  {label}: n={len(xs)} 未測={unmeasured}"
          f" | 中央値 {med(xs)*100:.1f}%/年 · 等加重平均 {mean*100:.1f}%"
          f" | P(≥15%) {sum(1 for x in xs if x >= .15)/len(xs):.2f}"
          f" | P(<0) {sum(1 for x in xs if x < 0)/len(xs):.2f}"
          f" | P(≤−15%) {sum(1 for x in xs if x <= -.15)/len(xs):.2f}"
          f" | DD中央値 {mdd*100:.0f}%")


print(f"=== asof={ASOF}  S&P500実績PER錨 = {ANCHOR}  "
      f"(線: ×1.2={ANCHOR*1.2:.1f} / ×1.4={ANCHOR*1.4:.1f})  "
      f"SPY実測14.2%/RSP11.6%（2013→2026・配当込み） ===")

q = [t for t, r in C.items() if r["score"] == 7 and t in PER]
print(f"\n--- 質(score7・PER測定済み n={len(q)}) を相対線で割る")
for lo, hi, label in [(0, 1.2, "rel≤1.2（提案の線）"), (1.2, 1.4, "1.2<rel≤1.4"),
                      (1.4, 99, "rel>1.4（法外側）")]:
    tk = [t for t in q if lo < PER[t] / ANCHOR <= hi]
    stats(tk, label)
stats([t for t in q if PER[t] / ANCHOR <= 1.4], "（参考）rel≤1.4 合算")

print(f"\n--- 対照(score≤4・売上5億$+・PER測定済み) 同じ線")
ctl = [t for t, r in C.items() if r["score"] <= 4 and r["rev_asof"] >= 500e6 and t in PER]
for lo, hi, label in [(0, 1.2, "rel≤1.2"), (1.2, 99, "rel>1.2")]:
    tk = [t for t in ctl if lo < PER[t] / ANCHOR <= hi]
    stats(tk, label)

print(f"\n--- 全社(スコア不問・PER測定済み n={len([t for t in PER if t in C])}) 線だけの力")
allt = [t for t in PER if t in C]
for lo, hi, label in [(0, 1.2, "rel≤1.2"), (1.2, 99, "rel>1.2")]:
    tk = [t for t in allt if lo < PER[t] / ANCHOR <= hi]
    stats(tk, label)

port = sorted([t for t in q if PER[t] / ANCHOR <= 1.2],
              key=lambda t: -(TR.get(t, {}).get("tr_cagr") or -9))
print(f"\n--- 「{ASOF}年のポートフォリオ」(score7∧rel≤1.2) 全{len(port)}社の中身（実現CAGR順）")
for t in port:
    r = TR.get(t, {})
    print(f"  {t:6s} per{PER[t]:6.1f} (rel{PER[t]/ANCHOR:.2f}) "
          + (f"実現 {r['tr_cagr']*100:+6.1f}%/年  DD{r['mdd']*100:4.0f}%"
         if r.get("tr_cagr") is not None else "実現 未測(退場等)"))
