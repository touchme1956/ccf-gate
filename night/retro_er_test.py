#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_er_test.py — **E[r] は指標として役に立つのか**を歴史で直接検定する（2026-08-07新設）

なぜ要るか:
  門X の E[r] = 純還元(shy) + 成長(g) + 倍率の重力(mult) は、
  **配分の順位を100%決めている**（2026-08-07の実測: Ωを全社一定にしても順位は0/11箇所しか違わない）。
  ところが E[r] 自身が当たるかは一度も検証されていない——予実台帳(audit_er_realized)は
  初回スナップが2026-08-03で、規約どおり180日未満は年率換算しないため結論はまだ出ない。
  **20年待たずに、歴史で同じ式を組んで答え合わせできる。**

何をするか:
  2018-07-01 時点で観測できた数字だけで E[r] を構成し、その後 8.1年の
  **配当込み実現リターン(tr_cagr)** と突き合わせる。

    shy  = payout5 ÷ per × 100     ← 恒等式（還元性向÷PER＝還元利回り）
    g    = min(max(cagr5,0), 20)
    fairPER = max(16, min(30, 8+g))
    mult = ((min(per,fairPER) ÷ per)^(1/20) − 1) × 100
    E[r] = shy + g + mult

  **簡略化を明示する**: 門の g は roicg≥15 のとき min(cagr,20)、それ以外は bR×roicg へ分岐するが、
  2018年の在庫に roicg が無いので**全社を前者（成長を信じる枝＝門にとって有利な側）**で組んだ。
  したがってここで出る E[r] は門の実装より**楽観側**に寄る。それでも当たらないなら結論は強くなる。

  三つの部品（shy / g / mult）を**別々にも**検定する——合成が効かなくても部品が効くなら
  「式の組み方が悪い」であり、部品も効かないなら「材料そのものが効かない」。区別が要る。

在庫: out/retro_per_2018_all.json（分割補正済みPER）／out/retro_features2_2018.json（提出日で切った厳密frame）
      ／out/retro_returns_2018.json（Yahoo adjclose＝配当込み）
使い方: python3 night/retro_er_test.py [--write]
"""
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
WRITE = "--write" in sys.argv[1:]
HOLD = 20          # 門X本体と同じ保有年数（v9.9.69）


def load(name, key="rows"):
    d = json.load(open(os.path.join(OUT, name), encoding="utf-8"))
    return d.get(key) or d


def build():
    per = {r["ticker"]: r for r in load("retro_per_2018_all.json")}
    fea = {r["ticker"]: r for r in load("retro_features2_2018.json")}
    ret = {r["ticker"]: r for r in load("retro_returns_2018.json")}
    rows = []
    for t, f in fea.items():
        p, rr = per.get(t), ret.get(t)
        if not p or not rr:
            continue
        pv, c5, po = p.get("per"), f.get("cagr5"), f.get("payout5")
        tr = rr.get("tr_cagr")
        if pv is None or c5 is None or po is None or tr is None:
            continue
        if not (2 <= pv <= 200):       # 分割事故の帯検問（既存の作法）
            continue
        g = min(max(c5 * 100, 0.0), 20.0)
        shy = po / pv * 100.0
        if not (-5 <= shy <= 15):      # 常識帯（market_merge.BANDS と同じ発想）
            continue
        fair = max(16.0, min(30.0, 8.0 + g))
        mult = ((min(pv, fair) / pv) ** (1.0 / HOLD) - 1.0) * 100.0
        rows.append(dict(t=t, per=pv, shy=round(shy, 2), g=round(g, 2),
                         mult=round(mult, 2), er=round(shy + g + mult, 2),
                         real=round(tr * 100, 2), mdd=rr.get("mdd")))
    return rows


def quint(rows, key, label):
    rs = sorted(rows, key=lambda r: r[key])
    n = len(rs) // 5
    print(f"\n  ── {label} の五分位 → その後8.1年の実現リターン（配当込み・年率） ──")
    print(f"     {'分位':<6}{'n':>5}{label+'の中央値':>14}{'実現の中央値':>13}{'実現の平均':>11}{'15%+の割合':>11}")
    band = []
    for i in range(5):
        g = rs[i * n:(i + 1) * n] if i < 4 else rs[4 * n:]
        med = statistics.median(x[key] for x in g)
        rmed = statistics.median(x["real"] for x in g)
        rmean = statistics.mean(x["real"] for x in g)
        p15 = sum(1 for x in g if x["real"] >= 15) / len(g)
        band.append((f"Q{i+1}", len(g), med, rmed, rmean, p15))
        print(f"     Q{i+1:<5}{len(g):>5}{med:>14.1f}{rmed:>13.1f}{rmean:>11.1f}{p15:>10.0%}")
    lo, hi = band[0], band[-1]
    print(f"     → Q5−Q1 の差: 中央値 {hi[3]-lo[3]:+.1f}pt ／ 15%+の割合 {hi[5]-lo[5]:+.0%}")
    return band


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    return 0.0 if sx == 0 or sy == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def main():
    rows = build()
    print("■ E[r] は指標として役に立つのか——2018-07-01 に組んだ E[r] vs その後8.1年の実現リターン")
    print(f"  対象 {len(rows)}社（PER・還元性向・成長・実現リターンが揃い、帯検問を通った社）")
    print(f"  実現リターン: 中央値 {statistics.median(r['real'] for r in rows):.1f}% ／ "
          f"15%+の割合 {sum(1 for r in rows if r['real']>=15)/len(rows):.0%}")
    print(f"  組んだ E[r] : 中央値 {statistics.median(r['er'] for r in rows):.1f}% ／ "
          f"幅 {min(r['er'] for r in rows):.1f}〜{max(r['er'] for r in rows):.1f}%")
    print("\n  ※ 門の g は roicg≥15 で分岐するが2018年の在庫に roicg が無いため、"
          "**全社を『成長を信じる枝』＝門に有利な側**で組んだ（楽観側に寄る）")

    res = {}
    for key, label in [("er", "E[r] 合成"), ("shy", "純還元 shy"), ("g", "成長 g"), ("mult", "倍率の重力 mult")]:
        b = quint(rows, key, label)
        c = corr([r[key] for r in rows], [r["real"] for r in rows])
        print(f"     相関 r={c:+.3f}（r²={c*c:.1%}）")
        res[key] = {"quintiles": b, "r": round(c, 4)}

    print("\n■ 門Xの遮断器（E[r]≥0）は何を止めたか")
    neg = [r for r in rows if r["er"] < 0]
    pos = [r for r in rows if r["er"] >= 0]
    if neg:
        print(f"   E[r]<0 の {len(neg)}社: 実現の中央値 {statistics.median(r['real'] for r in neg):+.1f}%")
        print(f"   E[r]≥0 の {len(pos)}社: 実現の中央値 {statistics.median(r['real'] for r in pos):+.1f}%")
    else:
        print("   E[r]<0 の社は0（この構成では遮断器が一度も働かない）")

    print("\n■ 門Xの旧ハードル（E[r]≥12%）は何を選んだか")
    hi = [r for r in rows if r["er"] >= 12]
    lo = [r for r in rows if r["er"] < 12]
    print(f"   E[r]≥12% の {len(hi)}社: 実現の中央値 {statistics.median(r['real'] for r in hi):+.1f}% "
          f"／ 15%+の割合 {sum(1 for r in hi if r['real']>=15)/len(hi):.0%}")
    print(f"   E[r]<12% の {len(lo)}社: 実現の中央値 {statistics.median(r['real'] for r in lo):+.1f}% "
          f"／ 15%+の割合 {sum(1 for r in lo if r['real']>=15)/len(lo):.0%}")

    # ── 質のふるいを通した後で測る（門が実際に E[r] を使う場所） ──────────────
    #   門は E[r] を**Ω75+ ∧ 堀70+ を通った後**の順位付けに使う。だから広い母集団での
    #   検定だけでは足りない。2018年の在庫で作れる最も近い相当物＝質実証プール
    #   （opm≥10% ∧ 5年FCF全年黒字）でもう一度測る。
    fea = {r["ticker"]: r for r in load("retro_features2_2018.json")}
    qp = [r for r in rows
          if (fea.get(r["t"], {}).get("opm") or 0) >= 0.10
          and (fea.get(r["t"], {}).get("fcfpos5") or 0) >= 5]
    print(f"\n■ 質のふるいを通した後で測る（{len(qp)}社＝今日の判定圏の歴史側の相当物）")
    print("   門は E[r] を **Ω75+ ∧ 堀70+ を通った後**の順位付けに使うので、こちらが本番の検定")
    qb = quint(qp, "er", "E[r] 合成（質実証プール内）")
    qc = corr([r["er"] for r in qp], [r["real"] for r in qp])
    print(f"     相関 r={qc:+.3f}（r²={qc*qc:.1%}）")
    for th in (0, 12):
        a = [r for r in qp if r["er"] >= th]
        b = [r for r in qp if r["er"] < th]
        if a and b:
            print(f"     E[r]≥{th}%: {len(a):>3}社 実現中央値 {statistics.median(x['real'] for x in a):+.1f}%"
                  f"  ／ <{th}%: {len(b):>3}社 {statistics.median(x['real'] for x in b):+.1f}%")
    res["er_quality_pool"] = {"n": len(qp), "quintiles": qb, "r": round(qc, 4)}

    if WRITE:
        p = os.path.join(OUT, "retro_er_test.json")
        json.dump({"generated": "2026-08-07", "asof": "2018-07-01", "horizon_years": 8.09,
                   "n": len(rows), "note": "gはroicg分岐を持たず全社を成長信頼の枝で構成＝門より楽観側",
                   "summary": res, "rows": rows},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
