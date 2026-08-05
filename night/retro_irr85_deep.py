# night/retro_irr85_deep.py — irr=85（顧客側の再認定型）の深掘り検証（2026-08-05新設）
#
# 30%の壁の検証で唯一 P>=0.50 を越えた規則を、あらゆる角度から潰しに行く。
# 「もっともらしい発見」を殺す検問を先に全部通してから採用の可否を語るため。
#
# 検問（すべて出力する。どれか一つでも落ちたら記録に明記する）:
#   (1) 閾値依存: 15%だけの現象か（0〜25%で走査）
#   (2) 分布: 閾値を使わない比較（分位点）
#   (3) ポートフォリオ: 等加重で持ったときの年率（負け社込み・SPYとの比較）
#   (4) 業種交絡: 同一SIC2内での比較・半導体サプライチェーン実体除外
#   (5) レジーム: 2018-22 / 2022-26
#   (6) 機械代替性: 入口の数字で irr85 を近似できるか（できるなら読む価値は無い）
#   (7) エントリー時点: 買値2016/2017/2018
# 実行: python3 night/retro_irr85_deep.py
import json, os, statistics, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD_YEARS = 8.09
SPY = 0.150


def load(n):
    p = os.path.join(BASE, "out", n)
    return json.load(open(p)) if os.path.exists(p) else None


M = {r["t"]: r for r in load("retro_moat_2018.json")["rows"]}
rest = load("retro_moat_2018_rest.json")
if rest:  # 残り37社の読解が届いていれば統合
    M.update({r["t"]: r for r in rest["rows"]})
SIC = {r["ticker"]: r for r in load("retro_sic.json")["rows"]}
MON2 = load("retro_monthly_2018_2026.json")
CUT = datetime.datetime(2022, 7, 1).timestamp()
SEMI = {"LRCX", "NVMI", "AMAT", "MPWR", "COHR", "AEIS", "ADI", "ENTG", "MKSI", "NXPI",
        "NOVT", "OLED", "IPGP", "ROG", "TER", "SWKS", "TXN", "STM", "SNPS", "KLIC"}


def frame(anchor):
    FR = load(f"retro_frame_{anchor}.json")["rows"]
    dq = [r for r in FR if r["rf5"] >= 0.15
          and (r.get("fcfpos5") or 0) >= 4 and (r.get("opm") or -9) >= 0.10]
    return [{**r, "irr18": M[r["t"]].get("irr18"), "moat5": M[r["t"]].get("moat5"),
             "sic2": SIC.get(r["t"], {}).get("sic2")} for r in dq if r["t"] in M]


def subs(t):
    pts = MON2.get(t)
    if not pts or len(pts) < 24:
        return None, None
    a = [(x, v) for x, v in pts if x < CUT]
    b = [(x, v) for x, v in pts if x >= CUT]
    if len(a) < 24 or len(b) < 24 or a[0][1] <= 0 or b[0][1] <= 0:
        return None, None
    ya = (a[-1][0] - a[0][0]) / (365.25 * 86400)
    yb = (b[-1][0] - b[0][0]) / (365.25 * 86400)
    return (a[-1][1] / a[0][1]) ** (1 / ya) - 1, (b[-1][1] / b[0][1]) ** (1 / yb) - 1


rows = frame(2018)
g = [r for r in rows if r["irr18"] == 85]
o = [r for r in rows if r["irr18"] != 85]
print(f"=== irr=85 深掘り検証（読了 {len(rows)}社 / irr85 {len(g)}社） ===")

print("\n(1) 閾値依存")
for th in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25):
    pa = sum(1 for r in g if r["r18"] >= th) / len(g)
    pb = sum(1 for r in o if r["r18"] >= th) / len(o)
    print(f"  {th*100:4.0f}%以上: irr85 {pa:.2f} vs 他 {pb:.2f}  差{pa-pb:+.2f}")

print("\n(2) 分布（閾値を使わない）")
for lab, xs in (("irr85", sorted(r["r18"] for r in g)), ("それ以外", sorted(r["r18"] for r in o))):
    q = lambda p: xs[int(len(xs) * p)]
    print(f"  {lab:8s} n={len(xs):3d} p10{q(.1)*100:+6.1f} p25{q(.25)*100:+6.1f} "
          f"中央{statistics.median(xs)*100:+6.1f} p75{q(.75)*100:+6.1f} p90{q(.9)*100:+6.1f}")


def basket(rs):
    return (sum((1 + r["r18"]) ** HOLD_YEARS for r in rs) / len(rs)) ** (1 / HOLD_YEARS) - 1


print("\n(3) 等加重ポートフォリオ（負け社込み・後半8.1年）")
print(f"  irr85 {basket(g)*100:+5.1f}%/年 ({(1+basket(g))**HOLD_YEARS:.2f}倍)  |  "
      f"それ以外 {basket(o)*100:+5.1f}%  |  全体 {basket(rows)*100:+5.1f}%  |  SPY {SPY*100:+5.1f}%")

print("\n(4) 業種交絡")
cy = ty = cn = tn = 0
for s in sorted({r["sic2"] for r in rows if r["sic2"]}):
    gg = [r for r in rows if r["sic2"] == s]
    y = [r for r in gg if r["irr18"] == 85]
    n = [r for r in gg if r["irr18"] != 85]
    if not y or not n:
        continue
    cy += sum(1 for r in y if r["r18"] >= .15); ty += len(y)
    cn += sum(1 for r in n if r["r18"] >= .15); tn += len(n)
print(f"  同一SIC2内プール: irr85 {cy}/{ty}={cy/max(ty,1):.2f} vs 同業他 {cn}/{tn}={cn/max(tn,1):.2f}")
gn = [r for r in g if r["t"] not in SEMI]
on = [r for r in o if r["t"] not in SEMI]
if gn:
    print(f"  半導体連鎖を実体で全除外: irr85 {sum(1 for r in gn if r['r18']>=.15)}/{len(gn)} "
          f"vs 他 {sum(1 for r in on if r['r18']>=.15)/len(on):.2f}  該当 {[r['t'] for r in gn]}")

print("\n(5) レジーム")
for i, lab in ((0, "前期2018-22"), (1, "後期2022-26")):
    xs = [subs(r["t"])[i] for r in rows if subs(r["t"])[i] is not None]
    ys = [subs(r["t"])[i] for r in g if subs(r["t"])[i] is not None]
    if len(ys) >= 8:
        pb = sum(1 for x in xs if x >= .15) / len(xs)
        pg = sum(1 for y in ys if y >= .15) / len(ys)
        print(f"  {lab}: base {pb:.2f} → irr85 {pg:.2f} (n={len(ys)}) lift{pg-pb:+.2f}"
              f" 中央値{statistics.median(ys)*100:+.1f}%")

print("\n(6) 機械代替性（入口の数字で irr85 を再現できるか）")
best = None
for k in ("opm", "cagr5", "rnd_r", "gm", "capex_r", "aturn", "rev", "cash_r"):
    v = sorted(r[k] for r in rows if r.get(k) is not None)
    if len(v) < 50:
        continue
    for q in (0.5, 0.6, 0.7, 0.75):
        th = v[int(len(v) * q)]
        sel = [r for r in rows if (r.get(k) or -9e9) > th]
        if len(sel) < 10:
            continue
        tp = sum(1 for r in sel if r["irr18"] == 85)
        prec, rec = tp / len(sel), tp / len(g)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        p = sum(1 for r in sel if r["r18"] >= .15) / len(sel)
        if not best or f1 > best[0]:
            best = (f1, k, q, prec, rec, len(sel), p)
print(f"  最良近似 {best[1]}上位{(1-best[2])*100:.0f}%: F1={best[0]:.2f} 適合率{best[3]:.2f} "
      f"再現率{best[4]:.2f} → その群のP(継続)={best[6]:.2f}（原本読解のirr85は"
      f"{sum(1 for r in g if r['r18']>=.15)/len(g):.2f}）")

print("\n(7) エントリー時点の頑健性（※堀の型は2018年の読解＝2016/17へは1-2年の先読み）")
for a in (2016, 2017, 2018):
    rs = frame(a)
    gg = [r for r in rs if r["irr18"] == 85]
    if len(gg) < 5:
        continue
    base = sum(1 for r in rs if r["r18"] >= .15) / len(rs)
    p = sum(1 for r in gg if r["r18"] >= .15) / len(gg)
    print(f"  買値{a}: base {base:.2f} → irr85 {p:.2f} (n={len(gg)}) lift{p-base:+.2f}")

json.dump({"generated": datetime.date.today().isoformat(), "n_read": len(rows), "n85": len(g),
           "p85": round(sum(1 for r in g if r["r18"] >= .15) / len(g), 3),
           "basket_irr85": round(basket(g), 4), "basket_other": round(basket(o), 4),
           "spy": SPY, "firms85": sorted(r["t"] for r in g)},
          open(os.path.join(BASE, "out", "retro_irr85_deep.json"), "w"),
          ensure_ascii=False, indent=1)
print("\n■ out/retro_irr85_deep.json へ記録")
