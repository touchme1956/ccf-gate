"""GRID・CIBR を含む案と新しい main を本物の記録で並べる（参考・判定なし・2026-11-25）。
共通の窓＝全部の本の記録がそろう月から（CIBR 2015-07 設定）。Yahoo の調整後終値（配当込み）・円（FRED のドル円は使わず Yahoo の JPY=X 月足）。
NASDAQ100 は QQQ で代える。毎月元の比へ組み直す。出力 out/gridcibr_real.json。"""
import json, math, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import mw_common as M
FORMS = {
 "新 main 45/25/15/15": {"QQQ": 45, "SMH": 25, "ITA": 15, "FBT": 15},
 "案 40/20/15/XLV10/GRID5/CIBR5": {"QQQ": 40, "SMH": 20, "ITA": 15, "XLV": 10, "GRID": 5, "CIBR": 5},
}
T = sorted({t for f in FORMS.values() for t in f} | {"SPY"})
R = {t: M.yahoo(t) for t in T}
fx = M.yahoo("JPY=X")
months = sorted(set.intersection(*[set(R[t]) for t in T]) & set(fx))
months = [m for m in months if m >= min(m for m in R["CIBR"]) ]
def stats(rets):
    v = 1.0; peak = 1.0; mdd = 0.0
    for r in rets:
        v *= 1 + r; peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    n = len(rets); ann = v ** (12 / n) - 1
    mu = sum(rets) / n; sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1)) * math.sqrt(12)
    return {"年率": round(ann * 100, 2), "ぶれ": round(sd * 100, 1), "最大下落": round(mdd * 100, 1)}
out = {"窓": f"{months[0]}〜{months[-1]}", "月数": len(months), "形": {}, "一本": {}}
for name, w in list(FORMS.items()) + [("S&P500（SPY）", {"SPY": 100})]:
    tot = sum(w.values())
    usd = [sum(w[t] / tot * R[t][m] for t in w) for m in months]
    jpy = [(1 + u) * (1 + fx[m]) - 1 for u, m in zip(usd, months)]
    out["形"][name] = {"ドル": stats(usd), "円": stats(jpy)}
for t in ["GRID", "CIBR", "XLV", "FBT", "QQQ"]:
    out["一本"][t] = stats([R[t][m] for m in months])
q = [R["QQQ"][m] for m in months]
def corr(a, b):
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    return sum((x-ma)*(y-mb) for x, y in zip(a, b)) / math.sqrt(sum((x-ma)**2 for x in a) * sum((y-mb)**2 for y in b))
out["QQQとの相関"] = {t: round(corr([R[t][m] for m in months], q), 2) for t in ["GRID", "CIBR", "XLV", "FBT", "ITA", "SMH"]}
json.dump(out, open(os.path.join(os.path.dirname(__file__), "..", "out", "gridcibr_real.json"), "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
