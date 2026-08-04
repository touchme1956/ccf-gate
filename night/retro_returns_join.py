# night/retro_returns_join.py — 歴史検証・案Cのリターン結合(2026-08-04新設)
#
# retro_cohort_{asof}.json（機械の背骨の合否）と retro_returns_{asof}.json（配当調整済み
# トータルリターン・FMP採取）を突き合わせ、通過群/対照群/指数の実現リターンを出す。
#
# リターンの規約（audit_er_realized の教訓をそのまま使う）:
#   - 価格は FMP historical-price-eod-dividend-adjusted の adjClose＝配当再投資込み。
#     現在値アンカーは検証済み（MSFT: adjClose(2026-08-03)=487.65＝生値と一致）。
#     価格のみのリターンで測ると配当利回りの分だけ構造的に低く出て
#     「自分で作った偏りを発見と誤認する」——それを避ける
#   - 年率は年ラベルでなく実日数/365.25 で割る
#   - 退場銘柄（今日のticker表に無い・quoteが返らない）は**測れない**。
#     黙って落とさず件数を出す——退場率そのものは cohort 側の last_year が既に持っている
#
# 実行: python3 night/retro_returns_join.py --asof 2013
import json, os, sys, datetime, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASOF = 2013
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])

cohort = json.load(open(os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")))
rets = json.load(open(os.path.join(BASE, "out", f"retro_returns_{ASOF}.json")))


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def stats(rows, label):
    xs = sorted(r["tr_cagr"] for r in rows if r.get("tr_cagr") is not None)
    stale = [r for r in rows if r.get("stale")]
    mdd = med([r.get("mdd") for r in rows if r.get("tr_cagr") is not None])
    if not xs:
        print(f"  {label}: 実測0件（stale {len(stale)}）")
        return
    print(f"  {label}: n={len(xs)} stale={len(stale)}"
          f" | 中央値 {med(xs)*100:.1f}%/年 | p25 {xs[len(xs)//4]*100:.1f}%"
          f" | p75 {xs[len(xs)*3//4]*100:.1f}%"
          f" | P(≥15%) {sum(1 for x in xs if x >= 0.15)/len(xs):.2f}"
          f" | P(<0) {sum(1 for x in xs if x < 0)/len(xs):.2f}"
          f" | P(恒久毀損:CAGR≤−15%) {sum(1 for x in xs if x <= -0.15)/len(xs):.2f}"
          f" | 最大DD中央値 {mdd*100:.0f}%")


rows = rets["rows"]
unm = rets.get("unmeasured", [])
print(f"=== asof={ASOF} 実現トータルリターン（{rets.get('asof_date')} → {rets.get('now_date')}・配当込み） ===")
stats([r for r in rows if r["group"] == "pass"], "門0通過(score7)")
stats([r for r in rows if r["group"] == "ctrl"], "対照(score≤4・大型)")
if unm:
    print(f"  未測（Yahooに系列なし＝退場等）: pass {sum(1 for u in unm if u['group']=='pass')} / "
          f"ctrl {sum(1 for u in unm if u['group']=='ctrl')}")
if rets.get("benchmark", {}).get("tr_cagr") is not None:
    print(f"  ベンチマーク SPY: {rets['benchmark']['tr_cagr']*100:.1f}%/年（配当込み・最大DD {rets['benchmark']['mdd']*100:.0f}%）")

# --- スコアとリターンの関係（cohort全rowsとの突合せ・サンプル内） ---------------
SC = {r["ticker"]: r["score"] for r in cohort["rows"] if r.get("ticker")}
print("\n  サンプル内の個別: 通過群の下位5・上位5（ticker/score/実現CAGR）")
ps = sorted([r for r in rows if r["group"] == "pass" and r.get("tr_cagr") is not None],
            key=lambda r: r["tr_cagr"])
for r in ps[:5] + ps[-5:]:
    print(f"    {r['ticker']:6s} score{SC.get(r['ticker'],'?')} {r['tr_cagr']*100:+.1f}%/年 (DD {r['mdd']*100:.0f}%)")
