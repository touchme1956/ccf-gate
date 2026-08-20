# night/etf_xar.py — XAR（SPDR S&P 航空防衛・等ウェイト）を詳しく測る（2026-08-19新設）
#
# 【何のための道具か】
#   「irr=85 に類似するETFは？」の答えが XAR だったので、その一本を掘る。
#   **判定はしない**——ETFの選定は門の外（DCA側の決断）で、
#   門Ωの採点・四関門・売却規律・配分にはいっさい触れない。
#
# 【測るもの】
#   (1) 中身  実効銘柄数(1/HHI)・irr=85 の被覆・城との重なり・ITA/PPAとの違い
#   (2) 窓    重ならない5年窓ごとの年率と順位（XARの設定 2011-09 以降）
#   (3) 同窓  XARの設定日から ITA/PPA/SPY/SMH/XLK を同じ窓で
#   (4) 危機  COVID(2020-01→2020-03)・2022デレーティング・転がる3年の最悪
#   (5) 相関  月次リターンの相関——**この資産にとって分散になるか**
#   (6) 見通し ルックスルー（城＋網）で網の一部をXARにしたら何が変わるか
#
# 【データ源】Yahoo adjclose 月次（分配金込み）一本。ソースを混ぜない
# 【欠測】設定前は測れない。ゼロや代替で埋めない（絶対のルール7）
# 【再実装しない】fetch/cagr/maxdd/on_or_before は etf_returns.py から import（v9.9.65）
#
# 実行: python3 night/etf_xar.py [--json]
# 出力: out/etf_xar.json
import json, os, sys, importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "etf_xar.json")

_spec = importlib.util.spec_from_file_location("etf_returns", os.path.join(BASE, "night", "etf_returns.py"))
_er = importlib.util.module_from_spec(_spec)
sys.modules["etf_returns"] = _er
_spec.loader.exec_module(_er)
fetch, cagr, maxdd, on_or_before = _er.fetch, _er.cagr, _er.maxdd, _er.on_or_before

IRR85 = {"ASML", "BWXT", "CW", "ENTG", "HXL", "KRMN", "LOAR", "LRCX",
         "MKSI", "NOVT", "RBC", "ST", "TDG", "VRSK", "WST"}
PEERS = ["XAR", "ITA", "PPA", "SPY", "SMH", "XLK", "QQQ", "VT"]
# 重ならない窓。XARの設定は2011-09なので、そこから3つ取れる
WINDOWS = [("2011-09", "2016-09"), ("2016-09", "2021-09"), ("2021-09", "2026-08")]
CRISES = {"COVID暴落 2020-01→2020-03": ("2020-01", "2020-03"),
          "2022デレーティング 2021-12→2022-09": ("2021-12", "2022-09"),
          "2018Q4 2018-09→2018-12": ("2018-09", "2018-12"),
          "GFC 2007-10→2009-02": ("2007-10", "2009-02")}


def eff_n(ws):
    """実効銘柄数 = 1/HHI。★掲載の重みだけで作る（掲載計が薄いと過大に出るので併記）"""
    s = sum(ws)
    if s <= 0:
        return None
    return round(1.0 / sum((w / s) ** 2 for w in ws), 1)


def monthly_rets(ser, a, b):
    ks = sorted(k for k in ser if a <= k <= b)
    return {ks[i]: ser[ks[i]] / ser[ks[i - 1]] - 1 for i in range(1, len(ks))}


def corr(x, y):
    ks = sorted(set(x) & set(y))
    n = len(ks)
    if n < 24:
        return None
    mx = sum(x[k] for k in ks) / n
    my = sum(y[k] for k in ks) / n
    sxy = sum((x[k] - mx) * (y[k] - my) for k in ks)
    sxx = sum((x[k] - mx) ** 2 for k in ks)
    syy = sum((y[k] - my) ** 2 for k in ks)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / (sxx * syy) ** 0.5, 3), n


def window_ret(ser, a, b):
    ka, kb = on_or_before(ser, a), on_or_before(ser, b)
    if not ka or not kb or ka[0] == kb[0]:
        return None
    return round(kb[1] / ka[1] - 1, 4)


def roll_worst(ser, months):
    ks = sorted(ser)
    out = []
    for i in range(len(ks) - months):
        a, b = ks[i], ks[i + months]
        out.append(((ser[b] / ser[a]) ** (12.0 / months) - 1, a, b))
    if not out:
        return None
    w = min(out)
    return {"最悪": round(w[0], 4), "窓": f"{w[1]}→{w[2]}", "n": len(out),
            "中央": round(sorted(o[0] for o in out)[len(out) // 2], 4)}


def build():
    prof = json.load(open(os.path.join(BASE, "out", "etf_profiles.json")))["etfs"]
    out = {"asof": "2026-08-19", "対象": "XAR (SPDR S&P Aerospace & Defense ETF・等ウェイト)",
           "注意": "ETFの選定は門の外（DCA側）。この道具は判定を持たない"}

    # ---- (1) 中身
    x = prof["XAR"]
    ws = [w for _, w in x["h"]]
    out["中身"] = {
        "経費率": x["er"], "設定": x["inc"], "掲載本数": len(ws),
        "掲載計": round(sum(ws), 4),
        "実効銘柄数(1/HHI)": eff_n(ws),
        "上位10合計": round(sum(sorted(ws, reverse=True)[:10]), 4),
        "最大の1社": round(max(ws), 4),
        "上位10": [[s, w] for s, w in sorted(x["h"], key=lambda z: -z[1])[:10]],
        "irr85": {"合計": round(sum(w for s, w in x["h"] if s in IRR85), 4),
                  "内訳": sorted([[s, w] for s, w in x["h"] if s in IRR85], key=lambda z: -z[1])},
    }
    # 同じテーマの3本を並べる（重みの作り方の違いが全部ここに出る）
    cmp3 = {}
    for t in ("XAR", "ITA", "PPA"):
        p = prof[t]
        w = [z for _, z in p["h"]]
        cmp3[t] = {"経費率": p["er"], "掲載": len(w), "実効銘柄数": eff_n(w),
                   "最大の1社": round(max(w), 4), "上位10合計": round(sum(sorted(w, reverse=True)[:10]), 4),
                   "irr85": round(sum(z for s, z in p["h"] if s in IRR85), 4),
                   "上位3": [[s, z] for s, z in sorted(p["h"], key=lambda q: -q[1])[:3]]}
    out["中身"]["同テーマ3本の比較"] = cmp3

    # 城との重なり（保有と投下可）
    try:
        st = json.load(open(os.path.join(BASE, "state.json")))
        pf = json.loads(st["data"]["pf:portfolio"]) if isinstance(st["data"]["pf:portfolio"], str) else st["data"]["pf:portfolio"]
        held = {p.get("t") or (p.get("nm") or "").split()[0] for p in (pf.get("positions") or [])}
    except Exception:
        held = set()
    try:
        sa = json.load(open(os.path.join(BASE, "out", "score_all.json")))
        rows = sa["rows"] if isinstance(sa, dict) and "rows" in sa else sa
        buy = {r["t"] for r in rows if r.get("buy")}
    except Exception:
        buy = set()
    syms = {s for s, _ in x["h"]}
    out["中身"]["城との重なり"] = {
        "保有銘柄と重なる": sorted(syms & held) or "なし",
        "投下可10社と重なる": sorted(syms & buy) or "なし",
        "★意味": "重なりが無い＝この網は城を増幅しない（XLK/QQQ/SMH は MSFT・ASML・LRCX で城を増幅する）",
    }

    # ---- (2)(3) 窓
    ser = {t: fetch(t) for t in PEERS}
    ser = {k: v for k, v in ser.items() if v}
    out["取得できた"] = sorted(ser)
    wins = {}
    for a, b in WINDOWS:
        row = {}
        for t, s in ser.items():
            c = cagr(s, a, b)
            if c is not None:
                row[t] = round(c, 4)
        wins[f"{a}→{b}"] = dict(sorted(row.items(), key=lambda z: -z[1]))
    out["重ならない5年窓"] = wins

    inc = "2011-09"
    same = {}
    for t, s in ser.items():
        c = cagr(s, inc, "2026-08")
        if c is None:
            continue
        same[t] = {"年率": round(c, 4), "最大下落": maxdd(s, inc, "2026-08")}
    out[f"同じ窓 {inc}→2026-08"] = dict(sorted(same.items(), key=lambda z: -z[1]["年率"]))

    # ---- (4) 危機
    cr = {}
    for nm, (a, b) in CRISES.items():
        row = {}
        for t, s in ser.items():
            r = window_ret(s, a, b)
            if r is not None:
                row[t] = r
        if row:
            cr[nm] = dict(sorted(row.items(), key=lambda z: -z[1]))
    out["危機の窓（累積・年率ではない）"] = cr
    out["転がる3年の年率"] = {t: roll_worst(s, 36) for t, s in ser.items() if t in ("XAR", "SMH", "XLK", "SPY")}

    # ---- (5) 相関
    rets = {t: monthly_rets(s, inc, "2026-08") for t, s in ser.items()}
    cm = {}
    for t in ser:
        if t == "XAR":
            continue
        c = corr(rets["XAR"], rets[t])
        if c:
            cm[t] = {"ρ": c[0], "n": c[1]}
    out["月次相関（XAR vs・2011-09以降）"] = dict(sorted(cm.items(), key=lambda z: z[1]["ρ"]))

    # ---- (6) ルックスルー
    try:
        spec2 = importlib.util.spec_from_file_location("lt", os.path.join(BASE, "night", "lookthrough.py"))
        _ = spec2  # 既存の道具があることだけ記録（引数の形が違うので呼ばない）
        out["ルックスルー"] = "night/lookthrough.py で別途。XARは城と1社も重ならないので、入れた分だけ半導体とMSFTの比率が下がる"
    except Exception:
        pass

    out["限界"] = [
        "窓はすべて2026-08で終わる＝終点の相場が全部に等しく乗る",
        "XARの設定は2011-09＝**GFCを一度も通っていない**（ITA/PPAは通っている）",
        "重ならない窓は3つしか取れない（設定が新しいため）",
        "掲載の重みは採取日の一枚＝等ウェイトは四半期リバランスなのでズレる",
        "生存バイアス——今日ティッカーが引けるETFだけ",
    ]
    return out


if __name__ == "__main__":
    o = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(o, open(OUT, "w"), ensure_ascii=False, indent=1)
    if "--json" in sys.argv:
        print(json.dumps(o, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(o, ensure_ascii=False, indent=1))
