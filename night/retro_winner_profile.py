# night/retro_winner_profile.py — 高年率を維持した勝者の逆引きプロファイル（2026-08-05新設）
#
# 問い（ユーザー）: 「高い年率を維持した銘柄を特定して、どの数字が共通して高かったのか検証して」
# retro_predictors.py（指標→前方を予言できるか）の**逆方向**——勝者を先に確定し、
# 入口(asof)時点の各指標が勝者群でどれだけ「揃って高かったか」を測る。
#
# 共通性の物差し:
#   share_hi = 勝者のうち、その指標が全体中央値より上だった割合（50%なら情報ゼロ）
#   lift     = P(勝者 | 指標が上位四分位) ÷ P(勝者)（1.0なら情報ゼロ）
# 入口で見えた数字と、事後に実現した数字（前方ROIC等）を分けて出す——後者は
# 「勝者の共通点」ではあるが事前には使えない（それが堀の審査の仕事という含意になる）。
#
# 実行: python3 night/retro_winner_profile.py --asof 2013 [--win 0.15]
import json, os, sys, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASOF = 2013
WIN = 0.15
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])
    if a == "--win" and i + 1 < len(sys.argv):
        WIN = float(sys.argv[i + 1])


def load(name):
    p = os.path.join(BASE, "out", name)
    return json.load(open(p)) if os.path.exists(p) else None


C = {r["ticker"]: r for r in load(f"retro_cohort_{ASOF}.json")["rows"] if r.get("ticker")}
R = load(f"retro_returns_{ASOF}_all.json") or load(f"retro_returns_{ASOF}.json")
TR = {r["ticker"]: r for r in R["rows"] if r.get("tr_cagr") is not None}
pers = load(f"retro_per_{ASOF}_all.json") or load(f"retro_per_{ASOF}.json")
PER = {r["ticker"]: r["per"] for r in pers["rows"]} if pers else {}

both = [t for t in TR if t in C]
winners = [t for t in both if TR[t]["tr_cagr"] >= WIN]
rest = [t for t in both if TR[t]["tr_cagr"] < WIN]
base = len(winners) / len(both)
print(f"=== asof={ASOF}  対象{len(both)}社  勝者(年率{WIN*100:.0f}%+)={len(winners)}社"
      f"  基礎確率{base:.2f} ===")
print(f"  勝者の実現: 中央値 {statistics.median(TR[t]['tr_cagr'] for t in winners)*100:.1f}%/年"
      f" / 最大DD中央値 {statistics.median(TR[t]['mdd'] for t in winners)*100:.0f}%")


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def profile(label, get, fmt=lambda v: f"{v:.3f}" if v is not None else "—"):
    vals_all = [(t, get(t)) for t in both]
    vals_all = [(t, v) for t, v in vals_all if v is not None]
    if len(vals_all) < 50:
        return
    m_all = med([v for _, v in vals_all])
    sv = sorted(v for _, v in vals_all)
    q75 = sv[int(len(sv) * 0.75)]
    inset = {t for t, _ in vals_all}
    w = [t for t in winners if t in inset]
    r = [t for t in rest if t in inset]
    if not w:
        return
    share_hi = sum(1 for t in w if get(t) > m_all) / len(w)
    topq = [t for t, v in vals_all if v >= q75]
    winq = sum(1 for t in topq if TR[t]["tr_cagr"] >= WIN)
    lift = (winq / len(topq)) / (len(w) / len(inset)) if topq else None
    print(f"  {label:26s} 勝者med {fmt(med([get(t) for t in w])):>8s} vs 他 {fmt(med([get(t) for t in r])):>8s}"
          f" | 勝者の{share_hi*100:3.0f}%が中央値超 | 上位1/4のlift {lift:.2f}")


g = lambda k: (lambda t: C[t].get(k))
print("\n--- 入口(2013年時点)で見えた数字 ---（共通性: 中央値超シェア50%・lift1.0なら情報ゼロ）")
profile("score(門0の7点)", lambda t: C[t].get("score"), lambda v: f"{v:.0f}" if v is not None else "—")
profile("roic_med5(through-cycle)", g("roic_med5"))
profile("roic_worst5(最悪年)", g("roic_worst5"))
profile("opm(営業利益率)", g("opm"))
profile("sales_cagr5(直近成長)", g("sales_cagr5"))
profile("fcf_conv(FCF転換)", g("fcf_conv_5y"))
profile("売上規模($)", lambda t: C[t].get("rev_asof"), lambda v: f"{v/1e9:.1f}B" if v is not None else "—")
if PER:
    profile("PER(分割補正済)", lambda t: PER.get(t), lambda v: f"{v:.1f}" if v is not None else "—")

print("\n--- 事後に実現した数字（＝勝者の共通点だが事前には見えない） ---")
profile("前方ROIC med5(+6..+10年)", g("fwd_roic_med5_a2"))
profile("前方売上CAGR(10年)", g("fwd_cagr_10y"))

# 勝者の中の「複合プロファイル」——何%が質の条件を同時に満たしていたか
print("\n--- 勝者の複合プロファイル（何%が該当したか / 全体の該当率） ---")
conds = [
    ("営業黒字5年継続(op_all_pos)", lambda t: C[t].get("op_all_pos") is True),
    ("FCF黒字5年継続(fcf_all_pos)", lambda t: C[t].get("fcf_all_pos") is True),
    ("roic_med5≥15%", lambda t: (C[t].get("roic_med5") or 0) >= 0.15),
    ("roic_worst5≥10%(谷でも2桁)", lambda t: (C[t].get("roic_worst5") or -9) >= 0.10),
    ("conv≥0.8", lambda t: (C[t].get("fcf_conv_5y") or 0) >= 0.8),
    ("opm≥15%", lambda t: (C[t].get("opm") or 0) >= 0.15),
    ("cagr5 5〜15%(中庸)", lambda t: 0.05 <= (C[t].get("sales_cagr5") or -9) < 0.15),
    ("score==7", lambda t: C[t].get("score") == 7),
]
for label, f in conds:
    pw = sum(1 for t in winners if f(t)) / len(winners)
    pa = sum(1 for t in both if f(t)) / len(both)
    print(f"  {label:28s} 勝者の{pw*100:3.0f}% / 全体の{pa*100:3.0f}%  (差{(pw-pa)*100:+.0f}pt)")
