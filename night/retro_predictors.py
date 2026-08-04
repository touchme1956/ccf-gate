# night/retro_predictors.py — 歴史検証・追補「欠けている測りは何か」(2026-08-04新設)
#
# 問い: 成長の持続・質の持続・生存・恒久毀損を、asof時点の**機械で測れる値**で
#   予言できたか？ できたなら門に欠けている測りがある。できないなら
#   「欠けているのは新しい機械指標ではなく、(a)成長減衰そのもの (b)定性の堀」と確定する。
#
# 方法: retro_cohort_{asof}.json の asof時点変数（roic_med5/opm/cagr5/conv/規模/score）で
#   コホートを二分し、前方アウトカム（10年成長・ROIC持続・生存・実現リターン）の
#   中央値の差を出す。差が小さければその指標は「測っても予言できない」。
#
# 実行: python3 night/retro_predictors.py --asof 2013
import json, os, sys, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASOF = 2013
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])

rows = json.load(open(os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")))["rows"]
try:
    rets = json.load(open(os.path.join(BASE, "out", f"retro_returns_{ASOF}.json")))
    TR = {r["ticker"]: r["tr_cagr"] for r in rets["rows"] if r.get("tr_cagr") is not None}
except FileNotFoundError:
    TR = {}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


CANDS = [
    ("roic_med5>=20%", lambda r: (r.get("roic_med5") or 0) >= 0.20),
    ("roic_med5>=30%", lambda r: (r.get("roic_med5") or 0) >= 0.30),
    ("roic_worst5>=10%", lambda r: (r.get("roic_worst5") or -9) >= 0.10),
    ("opm>=15%", lambda r: (r.get("opm") or 0) >= 0.15),
    ("opm>=25%", lambda r: (r.get("opm") or 0) >= 0.25),
    ("fcf_conv>=0.8", lambda r: (r.get("fcf_conv_5y") or 0) >= 0.8),
    ("売上>=5億$", lambda r: (r.get("rev_asof") or 0) >= 500e6),
    ("売上>=50億$", lambda r: (r.get("rev_asof") or 0) >= 5e9),
    ("score==7", lambda r: r.get("score") == 7),
]


def table(pop, outcome, label, fmt=lambda v: f"{v*100:.1f}%" if v is not None else "—",
          agg=med):
    # 二値の帰結（生存0/1）は中央値だと0%/100%に潰れる——平均を渡すこと
    print(f"\n--- {label}（母集団 n={len(pop)}） 指標 | 該当群(n) | 非該当群(n) | 差")
    base = agg([outcome(r) for r in pop])
    print(f"  （全体: {fmt(base)}）")
    for name, f in CANDS:
        yes = [outcome(r) for r in pop if f(r)]
        no = [outcome(r) for r in pop if not f(r)]
        my, mn = agg(yes), agg(no)
        d = (my - mn) if (my is not None and mn is not None) else None
        print(f"  {name:18s} | {fmt(my)} (n={len([x for x in yes if x is not None])})"
              f" | {fmt(mn)} (n={len([x for x in no if x is not None])})"
              f" | {'+' if (d or 0) >= 0 else ''}{d*100:.1f}pt" if d is not None else
              f"  {name:18s} | {fmt(my)} | {fmt(mn)} | —")


# ---- A) 高成長で入った社の「成長持続」を何が予言したか --------------------------
hg = [r for r in rows if (r.get("sales_cagr5") or 0) >= 0.15]
table(hg, lambda r: r.get("fwd_cagr_10y"), f"asof時点cagr5≥15%の社の 前方10年売上CAGR")

# ---- B) grower条件（門X v9.9.26と同形: cagr≥15 ∧ roic≥20）の前方成長 ------------
grower = [r for r in hg if (r.get("roic_med5") or 0) >= 0.20]
print(f"\n--- 門Xのgrower条件相当(cagr5≥15% ∧ roic_med5≥20%): n={len(grower)}")
print(f"  前方5年成長の中央値: {med([r.get('fwd_cagr_5y') for r in grower])}")
print(f"  前方10年成長の中央値: {med([r.get('fwd_cagr_10y') for r in grower])}")
print(f"  前方10年も15%以上: "
      f"{sum(1 for r in grower if (r.get('fwd_cagr_10y') or -9) >= 0.15)}"
      f"/{len([r for r in grower if r.get('fwd_cagr_10y') is not None])}")

# ---- C) 生存（データ末端−1年まで報告）を何が予言したか ---------------------------
data_end = max((r["last_year"] or 0) for r in rows)
alive = lambda r: 1.0 if (r["last_year"] or 0) >= data_end - 1 else 0.0
mean = lambda xs: round(statistics.mean([x for x in xs if x is not None]), 3) \
    if [x for x in xs if x is not None] else None
table(rows, alive, "生存率", fmt=lambda v: f"{v*100:.0f}%" if v is not None else "—",
      agg=mean)

# ---- D) 実現リターン（サンプルのみ）を何が予言したか -----------------------------
if TR:
    samp = [r for r in rows if r.get("ticker") in TR]
    table(samp, lambda r: TR[r["ticker"]], f"実現トータルリターン(サンプルn={len(samp)})")
    # 恒久毀損（CAGR≤−15%）した社のasof時点の姿——機械値で見分けられたか
    losers = [r for r in samp if TR[r["ticker"]] <= -0.15]
    print(f"\n--- 恒久毀損（実現CAGR≤−15%）{len(losers)}社のasof時点の機械値")
    for r in losers:
        print(f"  {r['ticker']:6s} score{r['score']} roic_med5 {r.get('roic_med5')}"
              f" opm {r.get('opm')} cagr5 {r.get('sales_cagr5')}"
              f" conv {r.get('fcf_conv_5y')} 売上 {round((r.get('rev_asof') or 0)/1e9,1)}B$")
