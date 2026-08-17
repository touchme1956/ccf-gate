#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v10_calib_power.py — 2027-07 の「v9 vs v10」答え合わせに**検出力があるか**を、その日が来る前に測る
                     (2026-08-16新設・ユーザー指示「あなたの判断で直して」)

なぜ要るか:
  この台帳は「基準が母集団の稀少事象の実数で到達可能か」を結果の前に数えていなかったせいで
  4回失敗している（hist_val v1 は 2013/2015 が構造的に到達不能／v3 は質実証プールの分子が
  届かない／v11 は層0∧層1 に恒久毀損が1社／v12 は同じ形）。**2027-07 も同じ形になりうる**——
  v10 のカバレッジは 28〜40社しかなく、そこから「劣化群」を抜くと分子は一桁になる。
  勝敗の判定式は rank-AUC の bootstrap 95%CI が重なれば「引き分け→現行v9維持」と規定しており、
  **CIが構造的に重なるなら、答え合わせは走る前から『引き分け』と決まっている。**
  それは v10 が悪いのではなく**試験に検出力が無い**ということで、両者はまったく違う。

測るもの:
  (1) v9のΩと v10 の順位相関——**同じ順位を作っているなら、標本をいくら増やしても分けられない**
  (2) 検出力——v10 が真に AUC で Δ だけ優れているとき、bootstrap CI が 0 を外す確率
  (3) 最小検出可能差——その n・その劣化社数で、検出力0.80 に要る Δ

⚠ これは予測器でも判定器でもない。**試験そのものの性能の測定**で、v10 の優劣は一切測らない。
使い方: python3 night/v10_calib_power.py [--json]
出力:   out/v10_calib_power.json
"""
import json, os, random, statistics as st, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(BASE, "out/calibration.json")
OUT = os.path.join(BASE, "out/v10_calib_power.json")
SEED = 20260816          # 決定的にする（同じ入力なら同じ答え）
SIMS = 2000              # 検出力の試行回数
BOOT = 400               # bootstrap の回数


def spearman(x, y):
    """順位相関。x,y は {ticker: value}"""
    ts = sorted(set(x) & set(y))
    if len(ts) < 3:
        return None, len(ts)
    def rk(v):
        s = sorted(ts, key=lambda t: v[t])
        return {t: i for i, t in enumerate(s)}
    a, b = rk(x), rk(y)
    ma, mb = st.mean(a.values()), st.mean(b.values())
    num = sum((a[t] - ma) * (b[t] - mb) for t in ts)
    den = (sum((a[t] - ma) ** 2 for t in ts) * sum((b[t] - mb) ** 2 for t in ts)) ** .5
    return (num / den if den else None), len(ts)


def auc(scores, bad):
    """Mann-Whitney AUC。「劣化群を**下位**に置けていたか」を測るので、
       スコアが低い＝劣化 を当てた形を 1.0 とする（同値は0.5）。"""
    pos = [scores[i] for i in range(len(scores)) if not bad[i]]   # 健全
    neg = [scores[i] for i in range(len(scores)) if bad[i]]       # 劣化
    if not pos or not neg:
        return None
    w = 0.0
    for p in pos:
        for q in neg:
            w += 1.0 if p > q else (0.5 if p == q else 0.0)
    return w / (len(pos) * len(neg))


def boot_ci(s1, s2, bad, rng, n_boot=BOOT):
    """会社単位の resample（対応あり＝同じ会社の二つのスコアを一緒に動かす）。
       対応を壊すと差のSEを過大評価するので必ず一緒に抜く。"""
    n = len(bad)
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        b = [bad[i] for i in idx]
        if not any(b) or all(b):
            continue
        a1 = auc([s1[i] for i in idx], b)
        a2 = auc([s2[i] for i in idx], b)
        if a1 is not None and a2 is not None:
            diffs.append(a2 - a1)
    if len(diffs) < 50:
        return None
    diffs.sort()
    lo = diffs[int(.025 * len(diffs))]
    hi = diffs[int(.975 * len(diffs)) - 1]
    return lo, hi


def power(n, k, delta, rng, sims=SIMS):
    """v10 が真に AUC で delta だけ優れているとき、CIが0を外す確率。
       置き方（正直に書く）: v9 と v10 を**独立**に生成し、v9 は無情報(AUC≈0.5)とした。
         ・独立にしたのは**実測の順位相関が ρ≈−0.13 でほぼ無相関だったから**（対応のある検定は
           相関が高いほど差のSEが縮むので、勝手に相関を仮定すると検出力を水増しする）
         ・v9 を 0.5 に置くのは AUC の分散が 0.5 付近で最大＝**検出力を過小に見積もる側**。
           つまりここで出る数字は下限寄りで、「足りない」という結論は保守的に読むこと。
       ⚠ 真の劣化社数 k は 2027年まで判らないので、**当てずに 15/25/35% で挟む**。"""
    hit = 0
    ok = 0
    for _ in range(sims):
        bad = [i < k for i in range(n)]
        rng.shuffle(bad)
        # v9: 劣化と無関係な順位
        s9 = [rng.random() for _ in range(n)]
        # v10: 劣化社を delta の分だけ下へ寄せる（AUC≈0.5+delta になるようずらす）
        s10 = [rng.random() - (2 * delta if bad[i] else 0) for i in range(n)]
        ci = boot_ci(s9, s10, bad, rng)
        if ci is None:
            continue
        ok += 1
        if ci[0] > 0:
            hit += 1
    return (hit / ok if ok else None), ok


def main():
    cal = json.load(open(CAL, encoding="utf-8"))
    v9 = {t: r["omega"] for t, r in cal["v9_scores_2026"]["byTicker"].items()
          if r.get("omega") is not None}
    v10a = {t: r["v10"] for t, r in cal["snapshots"]["2026"].items()
            if isinstance(r, dict) and r.get("v10") is not None}
    v10b = {t: r["v10"] for t, r in cal["v10_scores_2026"]["byTicker"].items()}

    out = {"generated": "2026-08-16", "seed": SEED, "sims": SIMS, "boot": BOOT,
           "note": "試験そのものの性能の測定。v10 の優劣は測っていない",
           "rank_corr": {}, "power": {}, "mde": {}}

    print("■ (1) v9 と v10 は別の順位を作っているか")
    for nm, v in (("v10_2026_07_27(n=28)", v10a), ("v10_2026_08_04(n=40)", v10b)):
        rho, n = spearman(v9, v)
        out["rank_corr"][f"v9_vs_{nm}"] = {"rho": round(rho, 3), "n": n}
        print(f"   v9のΩ × {nm}: ρ={rho:+.3f} (重なり{n}社)")
    rho, n = spearman(v10a, v10b)
    out["rank_corr"]["v10_0727_vs_0804"] = {"rho": round(rho, 3), "n": n}
    print(f"   07-27版 × 08-04版: ρ={rho:+.3f} ({n}社)"
          f"  ← 1.0に近いほど『どちらを選んでも順位は同じ』")

    print("\n■ (2) 検出力——v10 が真に AUC+Δ 優れているとき、CIが0を外す確率")
    rng = random.Random(SEED)
    print("      n   劣化社数   Δ=0.15  Δ=0.25  Δ=0.35")
    for n in (28, 40):
        for frac in (0.15, 0.25, 0.35):
            k = max(2, round(n * frac))
            row = []
            for d in (0.15, 0.25, 0.35):
                p, _ = power(n, k, d, rng)
                row.append(p)
                out["power"][f"n{n}_k{k}_d{d}"] = round(p, 3) if p is not None else None
            print(f"     {n:3d}   {k:2d}社     " +
                  "  ".join(f"{p:5.1%} " for p in row))

    print("\n■ (3) 検出力0.80 に要る Δ（最小検出可能差）")
    for n in (28, 40):
        k = max(2, round(n * 0.25))
        best = None
        for d in [x / 100 for x in range(5, 51, 5)]:
            p, _ = power(n, k, d, rng, sims=600)
            if p is not None and p >= .80:
                best = d
                break
        out["mde"][f"n{n}_k{k}"] = best
        print(f"     n={n} (劣化{k}社): " +
              (f"AUC差 {best:.2f} 以上でないと検出できない" if best
               else "Δ=0.50 まで振っても検出力0.80に届かない"))

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.relpath(OUT, BASE)}")


if __name__ == "__main__":
    main()
