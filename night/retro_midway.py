# night/retro_midway.py — 「途中から乗る」戦略の検証（2026-08-05新設）
#
# 問い（ユーザー）: 「最初を取る必要はない。途中の銘柄をどれだけ取れるかにすべてをつぎ込みたい」
#   ＝入口(2013)で当てるのではなく、**最初の5年(2013-2018)の実証**——実現リターンと
#   ファンダメンタルズの持続——を見てから2018年に乗り、残り8年(2018-2026)を取れたか。
#
# 方法:
#   r13 = 2013-07→現在の実現CAGR（retro_returns_2013_all）
#   r18 = 2018-07→現在の実現CAGR（retro_returns_2018）
#   最初の5年 r_first = ((1+r13)^y13 / (1+r18)^y18)^(1/(y13−y18)) − 1（同一ソース内の恒等分解）
#   実証の条件（2018年時点で観測可能なものだけ）:
#     価格実証   = r_first ≥ 15%/年
#     質の実証   = cohortの fwd_roic_med5_a1（2014-2018のROIC中央値）≥ 15% / 20%
#     成長の実証 = fwd_cagr_5y（2013→2018売上CAGR）≥ 10%
#   帰結 = r18 の中央値・P(15%+)・P(マイナス)。
#   look-ahead防止: 条件はすべて2018年までに確定する数字のみ（fwd_roic_med5_a1は
#   2014-2018年のXBRL＝2019年初までに全て公表済み）。
#
# 注意（正直に）:
#   - 2018年に生存していた社への条件付け＝この戦略自身の情報集合なのでバイアスではない
#   - r18はYahooに系列が残る社のみ＝生存者条件付き（従来と同じ・件数を並記）
#   - 長期の過去勝者はリバーサル（DeBondt-Thaler）が知られる——負け組の反発も併記して確かめる
#
# 実行: python3 night/retro_midway.py
import json, os, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    return json.load(open(os.path.join(BASE, "out", name)))


C = {r["ticker"]: r for r in load("retro_cohort_2013.json")["rows"] if r.get("ticker")}
R13 = {r["ticker"]: r for r in load("retro_returns_2013_all.json")["rows"] if r.get("tr_cagr") is not None}
R18 = {r["ticker"]: r for r in load("retro_returns_2018.json")["rows"] if r.get("tr_cagr") is not None}

both = [t for t in R13 if t in R18 and t in C]
rows = []
for t in both:
    y13, y18 = R13[t]["years"], R18[t]["years"]
    if y13 - y18 < 4:  # 最初の窓が4年未満なら実証と呼べない
        continue
    g13 = (1 + R13[t]["tr_cagr"]) ** y13
    g18 = (1 + R18[t]["tr_cagr"]) ** y18
    rf = (g13 / g18) ** (1 / (y13 - y18)) - 1
    rows.append({"t": t, "rf": rf, "r18": R18[t]["tr_cagr"], "mdd18": R18[t].get("mdd"),
                 "roicA": C[t].get("fwd_roic_med5_a1"), "cagrA": C[t].get("fwd_cagr_5y")})


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def stats(g, label):
    xs = sorted(r["r18"] for r in g)
    if not xs:
        print(f"  {label}: 0件")
        return
    print(f"  {label:46s} n={len(xs):3d} | 後半8年 中央値{med(xs)*100:5.1f}%/年"
          f" | P(15%+)={sum(1 for x in xs if x >= .15)/len(xs):.2f}"
          f" | P(<0)={sum(1 for x in xs if x < 0)/len(xs):.2f}")


base = med([r["r18"] for r in rows])
print(f"=== 「途中から乗る」検証: 2013-2018の実証 → 2018-2026(8.1年)の実り  n={len(rows)} ===")
stats(rows, "全体（ベースライン）")
print("\n--- 価格の実証（最初の5年の実現リターン）で乗る ---")
for lo, hi, label in ((0.15, 99, "最初の5年 年率15%+（勝ち実証）"),
                      (0.25, 99, "最初の5年 年率25%+（強い実証）"),
                      (0.0, 0.15, "0〜15%（並）"),
                      (-99, 0.0, "マイナス（負け実証）")):
    stats([r for r in rows if lo <= r["rf"] < hi], label)
print("\n--- 質の実証（2014-2018のROIC中央値）で乗る ---")
for th in (0.15, 0.20):
    stats([r for r in rows if (r["roicA"] or -9) >= th], f"実証ROIC≥{th*100:.0f}%")
print("\n--- 成長の実証（2013→2018売上CAGR）で乗る ---")
for th in (0.10, 0.15):
    stats([r for r in rows if (r["cagrA"] or -9) >= th], f"実証成長≥{th*100:.0f}%")
print("\n--- 複合: 価格×質×成長の実証がそろった「途中の本物」 ---")
stats([r for r in rows if r["rf"] >= 0.15 and (r["roicA"] or -9) >= 0.15], "価格15%+ ∧ ROIC15%+")
stats([r for r in rows if r["rf"] >= 0.15 and (r["roicA"] or -9) >= 0.15 and (r["cagrA"] or -9) >= 0.10],
      "価格15%+ ∧ ROIC15%+ ∧ 成長10%+")
g = [r for r in rows if r["rf"] >= 0.15 and (r["roicA"] or -9) >= 0.15 and (r["cagrA"] or -9) >= 0.10]
if g:
    print("\n  該当銘柄（後半8年の実り順・上位15）:")
    for r in sorted(g, key=lambda r: -r["r18"])[:15]:
        print(f"    {r['t']:6s} 前半{r['rf']*100:+5.1f}% → 後半{r['r18']*100:+5.1f}%/年 (DD{(r['mdd18'] or 0)*100:.0f}%)")
