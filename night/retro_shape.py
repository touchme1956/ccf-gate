# night/retro_shape.py — 「リターン分布の形」の採取（2026-08-12新設）
#
# 既存の retro_path_features.py は 7統計量（rf5 / mdd5 / vol_m / worst12 / prox_hi / upmo_r / r2_log）を
# 作っているが、**分布の形そのもの**（宝くじ性・歪度・尖度・下方リスク・市場感応度）は一つも無い。
# ここはその欄を埋める採取器。**判定はしない**（合否は事前登録した検定器の仕事）。
#
# 入力: out/retro_monthly_{2013_2018,2018_2026}.json を連結（952社・2013-07〜2026-08 の158ヶ月・
#       Yahoo adjclose）＝**追加のネットワーク取得はゼロ**。在庫だけで作る
# 窓: asof の直前 **36ヶ月に固定**（全アンカーで同じ基準にするため。窓長をアンカーごとに変えると
#     『基準の違う二つ』を作る）
# asof=2013 は作れない（2008-2013 の月次が在庫に無い）＝**穴として明示する**
#
# 市場基準: SPYの月次系列は在庫のどこにも無い（実測）。**パネル自身の等ウェイト指数**を市場とする。
#   ＝追加取得ゼロ。SPYではないので `beta` は「この母集団に対する感応度」であって市場ベータではない。
#   毎月、その月のリターンが取れる全社の単純平均。窓ごとに作り直す（look-ahead なし）
#
# look-ahead: 窓の終端は asof の**前月末**。asof 当月は含めない
#
# 出力: out/retro_shape_{2016..2022}.json（2019-2022 は 2026-08-12 に新設した未見のアンカー）
# 実行: python3 night/retro_shape.py

import datetime
import json
import math
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
SRC = [os.path.join(OUT, "retro_monthly_2013_2018.json"),
       os.path.join(OUT, "retro_monthly_2018_2026.json")]  # 2本を連結（接合部は実測で整合・偵察が確認）
WINDOW = 36
ANCHORS = {y: f"{y}-07-01" for y in (2016, 2017, 2018, 2019, 2020, 2021, 2022)}


def ym(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)


def load_panel():
    """{ticker: {ym: adjclose}}。同じ年月に複数バーがあるときは**最初のバー**を採る
    （末尾の部分バーで最終月が二重にならないように。規約を先に決める）。
    2本のファイルを連結する（接合部の比は中央値1.0218・0.5〜2.0の外0件と実測済み）。"""
    panel = {}
    for path in SRC:
        raw = json.load(open(path))
        for t, series in raw.items():
            m = panel.setdefault(t, {})
            for ts, px in series:
                if px is None or px <= 0:
                    continue
                k = ym(ts)
                if k not in m:
                    m[k] = px
    return {t: m for t, m in panel.items() if m}


def rets(m, k0, k1):
    """[k0, k1] の月について前月比リターン。欠測があればその月は None。"""
    out = {}
    for k in range(k0, k1 + 1):
        a, b = m.get(k - 1), m.get(k)
        out[k] = (b / a - 1.0) if (a and b) else None
    return out


def moments(xs):
    n = len(xs)
    mu = sum(xs) / n
    sd = statistics.pstdev(xs)
    if sd == 0:
        return mu, sd, None, None
    m3 = sum((x - mu) ** 3 for x in xs) / n
    m4 = sum((x - mu) ** 4 for x in xs) / n
    return mu, sd, m3 / sd ** 3, m4 / sd ** 4 - 3.0


def build(anchor):
    panel = load_panel()
    a = datetime.date.fromisoformat(ANCHORS[anchor])
    end = a.year * 12 + (a.month - 1) - 1          # asof の前月
    start = end - WINDOW + 1
    # 各社の月次リターン
    R = {t: rets(m, start, end) for t, m in panel.items()}
    # 市場＝その月にリターンが取れる全社の等ウェイト平均
    mkt = {}
    for k in range(start, end + 1):
        v = [R[t][k] for t in R if R[t].get(k) is not None]
        mkt[k] = sum(v) / len(v) if len(v) >= 100 else None

    rows, holes = [], []
    for t, r in R.items():
        obs = [(k, r[k]) for k in range(start, end + 1) if r.get(k) is not None]
        if len(obs) < 30:                            # 36ヶ月窓で30ヶ月未満は測らない（0と読まない）
            holes.append({"t": t, "months": len(obs)})
            continue
        xs = [x for _k, x in obs]
        mu, sd, skew, kurt = moments(xs)
        neg = [x for x in xs if x < 0]
        dsd = math.sqrt(sum(x * x for x in neg) / len(xs)) if neg else 0.0
        # 直近12ヶ月の最大月次リターン（MAX効果）
        last12 = [x for k, x in obs if k > end - 12]
        mx1 = max(last12) if last12 else None
        # 最長連続下落月
        run = best = 0
        for _k, x in obs:
            run = run + 1 if x < 0 else 0
            best = max(best, run)
        # 市場感応度と特異ボラ（市場が取れた月だけ）
        pair = [(mkt[k], x) for k, x in obs if mkt.get(k) is not None]
        beta = ivol = None
        if len(pair) >= 30:
            mm = [p[0] for p in pair]
            yy = [p[1] for p in pair]
            mbar, ybar = sum(mm) / len(mm), sum(yy) / len(yy)
            var = sum((v - mbar) ** 2 for v in mm)
            if var > 0:
                beta = sum((mm[i] - mbar) * (yy[i] - ybar) for i in range(len(mm))) / var
                alpha = ybar - beta * mbar
                res = [yy[i] - (alpha + beta * mm[i]) for i in range(len(mm))]
                ivol = statistics.pstdev(res)
        rows.append({
            "t": t, "months": len(obs),
            "mx1": round(mx1, 4) if mx1 is not None else None,
            "skew": round(skew, 3) if skew is not None else None,
            "kurt": round(kurt, 3) if kurt is not None else None,
            "dsd": round(dsd, 4),
            "vol": round(sd, 4),
            "negrun": best,
            "beta": round(beta, 3) if beta is not None else None,
            "ivol": round(ivol, 4) if ivol is not None else None,
        })
    return {
        "generated": datetime.date.today().isoformat(),
        "asof": anchor, "asof_date": ANCHORS[anchor],
        "window_months": WINDOW,
        "source": "out/retro_monthly_{2013_2018,2018_2026}.json を連結（Yahoo adjclose・追加取得ゼロ）",
        "market": "パネル自身の等ウェイト指数（SPYの月次は在庫に無い）＝市場ベータではなく母集団感応度",
        "note": "同一年月に複数バーがある場合は最初のバーを採る。asof当月は含めない。30ヶ月未満は欠測",
        "n": len(rows), "n_hole": len(holes), "holes": holes[:50], "rows": rows,
    }


def main():
    for a in ANCHORS:
        d = build(a)
        p = os.path.join(OUT, f"retro_shape_{a}.json")
        json.dump(d, open(p, "w"), ensure_ascii=False)
        cov = {k: sum(1 for r in d["rows"] if r.get(k) is not None) for k in ("mx1", "skew", "kurt", "dsd", "beta", "ivol")}
        print(f"{a}: n={d['n']} 欠測{d['n_hole']}  被覆 {cov} → {p}")


if __name__ == "__main__":
    main()
