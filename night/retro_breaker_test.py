#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_breaker_test.py — **遮断器は何で切るのが一番いいか**を左尾で裁く（2026-08-07新設）

なぜ別の道具が要るか:
  night/retro_er_test.py は E[r] を**選別器**として検定した（五分位・相関）。答えは
  「効かない・質実証プール内ではむしろ逆」だった。
  だが v9.9.84 の遮断器は**選別器ではない**と明言している——
  「選別は堀の審査の仕事。門は『マイナス期待の極端』だけを弾く回路遮断器」。
  **遮断器の良し悪しは、通した側の平均ではなく『止めた側の左尾』で決まる。**
  上位が伸びるかではなく、**止めた群が本当に壊れているか**。物差しを間違えたまま
  「E[r]は効かない→遮断器も無意味」と結論すると、2026-08-04に自分で撤回した
  「ハードルを上げれば質が上がる」と同じ型の誤りになる。

測る指標（全て『止めた側』について）:
  ・n（何社止めたか＝機会費用の大きさ）
  ・中央値リターン（止めた群 vs 通した群）
  ・**恒久毀損率** P(年率CAGR ≤ −15%)   ← 20年複利で最も高くつく事象
  ・元本割れ率 P(年率CAGR < 0)
  良い遮断器＝**少数だけ止めて、その群の恒久毀損率がベースより明確に高い**。
  止めた群がベースと同じなら、それは遮断器ではなく**ただの間引き**。

在庫: out/retro_er_test.json（2018年に組んだ E[r] と部品）
      out/retro_features2_2018.json（提出日で切った厳密frameの20系統）
      out/retro_returns_2018.json（Yahoo adjclose＝配当込み・8.1年）

**測れないもの（正直に書く）**: gcap<0（＝会社/市場が来期減益を予想）は
  2018年時点のコンセンサスが在庫に無いので**歴史で検定できない**。
  6920レーザーテックの実例は n=1 の逸話であって証拠ではない。この道具はそれを明示する。

使い方: python3 night/retro_breaker_test.py [--write]
"""
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
WRITE = "--write" in sys.argv[1:]
IMPAIR = -15.0        # 恒久毀損の線（歴史検証の既存定義と同じ）


def load(name, key="rows"):
    d = json.load(open(os.path.join(OUT, name), encoding="utf-8"))
    return d.get(key) if isinstance(d, dict) and key in d else d


def stat(g):
    if not g:
        return None
    return dict(n=len(g),
                med=round(statistics.median(x["real"] for x in g), 1),
                impair=round(sum(1 for x in g if x["real"] <= IMPAIR) / len(g), 3),
                loss=round(sum(1 for x in g if x["real"] < 0) / len(g), 3))


def report(label, rows, pred, base):
    blocked = [r for r in rows if pred(r)]
    passed = [r for r in rows if not pred(r)]
    b, p = stat(blocked), stat(passed)
    if not b:
        print(f"  {label:<34} 止めた社 0——この母集団では一度も作動しない")
        return dict(rule=label, blocked=0)
    lift = b["impair"] - base["impair"]
    mark = "◎" if lift >= 0.05 else ("○" if lift >= 0.02 else "×")
    print(f"  {label:<34} 止めた {b['n']:>3}社 "
          f"中央値 {b['med']:>6.1f}%（通過 {p['med']:>5.1f}%） "
          f"恒久毀損 {b['impair']:>5.1%}（ベース {base['impair']:.1%}・差 {lift:+.1%}） "
          f"元本割れ {b['loss']:>5.1%}  {mark}")
    return dict(rule=label, blocked=b, passed=p, impair_lift=round(lift, 3))


def main():
    rows = load("retro_er_test.json")
    fea = {r["ticker"]: r for r in load("retro_features2_2018.json")}
    base = stat(rows)
    print("■ 遮断器は何で切るのが一番いいか——**止めた側の左尾**で裁く")
    print(f"  母集団 {base['n']}社（2018-07-01に観測できた数字のみ・その後8.1年の配当込みリターン）")
    print(f"  ベース: 中央値 {base['med']}% ／ **恒久毀損率 {base['impair']:.1%}**（年率≤{IMPAIR:.0f}%） "
          f"／ 元本割れ {base['loss']:.1%}")
    print("\n  良い遮断器＝**少数だけ止めて、その群の恒久毀損率がベースより明確に高い**。"
          "\n  ベースと同じなら遮断器ではなくただの間引き（機会費用だけ払う）。\n")

    res = []
    print("── (A) 現行の遮断器とその部品 ──")
    res.append(report("E[r] < 0（現行の遮断器）", rows, lambda r: r["er"] < 0, base))
    res.append(report("E[r] < 12（旧ハードル）", rows, lambda r: r["er"] < 12, base))
    res.append(report("純還元 shy < 0", rows, lambda r: r["shy"] < 0, base))
    res.append(report("成長 g = 0（実績が伸びていない）", rows, lambda r: r["g"] <= 0, base))
    res.append(report("倍率の重力 mult < −3%/年", rows, lambda r: r["mult"] < -3, base))

    print("\n── (B) 門が既に持っている他の材料で切ったら ──")
    def f(t, k):
        v = fea.get(t, {}).get(k)
        return v

    res.append(report("PER > 40（高倍率）", rows, lambda r: r["per"] > 40, base))
    res.append(report("営業利益率 < 5%", rows,
                      lambda r: (f(r["t"], "opm") or 1) < 0.05, base))
    res.append(report("5年FCFに赤字年がある", rows,
                      lambda r: (f(r["t"], "fcfpos5") or 5) < 5, base))
    res.append(report("営業利益率が5年で低下（堀の侵食）", rows,
                      lambda r: (f(r["t"], "opmD5") or 0) < 0, base))
    res.append(report("直近売上が縮小（cagr5 < 0）", rows,
                      lambda r: (f(r["t"], "cagr5") or 0) < 0, base))
    res.append(report("純発行がプラス（希薄化している）", rows,
                      lambda r: (f(r["t"], "netiss_r") or 0) > 0, base))

    print("\n── (C) 二つ重ねる（左尾を狙い撃つ） ──")
    res.append(report("売上縮小 ∧ 営業利益率低下", rows,
                      lambda r: (f(r["t"], "cagr5") or 0) < 0 and (f(r["t"], "opmD5") or 0) < 0, base))
    res.append(report("FCF赤字年あり ∧ 営業利益率<10%", rows,
                      lambda r: (f(r["t"], "fcfpos5") or 5) < 5 and (f(r["t"], "opm") or 1) < 0.10, base))

    print("\n■ 測れないもの（正直に）")
    print("  **gcap < 0（会社/市場が来期減益を予想）は歴史で検定できない**——")
    print("  2018年時点のアナリスト・コンセンサスが在庫に無い。6920レーザーテックの実例は")
    print("  **n=1 の逸話であって証拠ではない**。採否を『6920が捕まったから』で決めるのは、")
    print("  この台帳が繰り返し戒めてきた『1社のための規約＝curve-fitting』の型。")

    if WRITE:
        p = os.path.join(OUT, "retro_breaker_test.json")
        json.dump({"generated": "2026-08-07", "asof": "2018-07-01", "horizon_years": 8.09,
                   "impair_line": IMPAIR, "base": base, "rules": res,
                   "note": "遮断器は『止めた側の恒久毀損率』で裁く。gcap<0は在庫が無く検定不能"},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
