# night/retro_anchors_new.py — 未見の新アンカー（2019-2022）の前方リターンを在庫から作る（2026-08-12新設）
#
# 目的: これまでの歴史検証のアンカーは 2013/2015/2016/2017/2018 の5つで、**すべて2026年終点**。
#   CLAUDE.md が繰り返し「独立標本ではない」と記録してきた当の制約を、初めて部分的に緩める。
#   out/retro_monthly_2018_2026.json（952社・2018-07〜2026-08）があるので、
#   2019/2020/2021/2022年7月を起点にした前方リターンが**追加取得ゼロ**で作れる。
#
# 出力の形は既存の out/retro_returns_{asof}.json と**完全に同じスキーマ**にする。
#   ＝ retro_features2.py / retro_fund2.py / retro_shape.py / retro_robust.py が
#      --asof を変えるだけでそのまま動く（二重実装を作らない）。
#
# ⚠ 窓が短い: 2019起点=7.1年 / 2020=6.1 / 2021=5.1 / 2022=4.1年。
#   20-30年の複利を語る窓ではない。**ベース率をアンカー間で直接比べない**（既記録の作法）。
# ⚠ 母集団は同じ952社で期間も重なるので、これも完全な独立標本ではない。
#   ただし「入口の年」が違うので、少なくとも**入口の相場と入口の財務は別物**になる。
#
# 実行: python3 night/retro_anchors_new.py

import datetime
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
SRC = os.path.join(OUT, "retro_monthly_2018_2026.json")
ANCHORS = (2019, 2020, 2021, 2022)
MIN_MONTHS = 36          # 3年未満の窓は作らない


def ym(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)


def main():
    raw = json.load(open(SRC))
    panel = {}
    for t, series in raw.items():
        m = {}
        for ts, px in series:
            if px is None or px <= 0:
                continue
            k = ym(ts)
            if k not in m:      # 同一年月は最初のバー（末尾の部分バー対策）
                m[k] = px
        if m:
            panel[t] = m
    kend = max(k for m in panel.values() for k in m)

    # SPY の月次は在庫に無い（実測）。ベンチマークは既存 retro_returns_2018.json の SPY を
    # そのまま流用できないので、**パネル自身の等ウェイト指数**をベンチとして併記する
    # （robust の『市場より浅い』には使わない＝v4 は母集団中央値を使う）
    for a in ANCHORS:
        k0 = a * 12 + 6         # その年の7月
        rows, unmeasured = [], []
        for t, m in panel.items():
            ks = [k for k in sorted(m) if k0 <= k <= kend]
            if len(ks) < MIN_MONTHS:
                unmeasured.append({"ticker": t, "months": len(ks)})
                continue
            p0, p1 = m[ks[0]], m[ks[-1]]
            yrs = (ks[-1] - ks[0]) / 12.0
            if p0 <= 0 or yrs <= 0:
                unmeasured.append({"ticker": t, "why": "価格が非正"})
                continue
            peak, mdd = p0, 0.0
            for k in ks:
                peak = max(peak, m[k])
                mdd = min(mdd, m[k] / peak - 1.0)
            rows.append({
                "ticker": t, "group": "all",
                "start": f"{a}-07-01", "end": "2026-08-01",
                "years": round(yrs, 2), "mdd": round(mdd, 4), "stale": False,
                "tr_total": round(p1 / p0, 4), "tr_cagr": round((p1 / p0) ** (1 / yrs) - 1, 4),
            })
        # 等ウェイト指数（記述用）
        idx = []
        for k in range(k0, kend + 1):
            v = [m[k] / m[k - 1] - 1 for m in panel.values() if m.get(k) and m.get(k - 1)]
            if len(v) >= 100:
                idx.append(sum(v) / len(v))
        tot = 1.0
        for r in idx:
            tot *= (1 + r)
        yrs = len(idx) / 12.0
        out = {
            "generated": datetime.date.today().isoformat(), "asof": a, "asof_date": f"{a}-07-01",
            "now_date": "2026-08-12",
            "source": "out/retro_monthly_2018_2026.json（Yahoo adjclose・追加取得ゼロ）",
            "note": "新アンカー。既存 retro_returns_* と同一スキーマ。⚠窓が短い（アンカー間でベース率を直接比べない）。"
                    "⚠母集団952社は既存アンカーと同じで期間も重なる＝完全な独立標本ではない",
            "benchmark": {"symbol": "EW(パネル自身の等ウェイト指数・SPYの月次は在庫に無い)",
                          "start": f"{a}-07-01", "end": "2026-08-01", "years": round(yrs, 2),
                          "tr_total": round(tot, 4),
                          "tr_cagr": round(tot ** (1 / yrs) - 1, 4) if yrs > 0 else None,
                          "mdd": None, "stale": False},
            "sampled_tickers": None, "rows": rows, "unmeasured": unmeasured,
        }
        p = os.path.join(OUT, f"retro_returns_{a}.json")
        json.dump(out, open(p, "w"), ensure_ascii=False)
        n15 = sum(1 for r in rows if r["tr_cagr"] >= 0.15)
        print(f"{a}: n={len(rows)} 窓{out['benchmark']['years']}年 等W指数{out['benchmark']['tr_cagr']} "
              f"15%+={n15}({n15/len(rows):.3f}) 欠測{len(unmeasured)} → {p}")


if __name__ == "__main__":
    main()
