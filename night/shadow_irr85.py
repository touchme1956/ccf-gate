#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_irr85.py — **irr=85 は今の門で何をしているのか**（2026-08-07新設）

なぜ要るか（ユーザーの問い「irr85があまり意味をなしてないのでは？」）:
  この台帳の歴史検証は、**リターンと生死を分けた変数は irr=85 ただ一つ**だと繰り返し出した——
    ・2018年ビンテージ(n=21): P(継続)=0.71 vs ベース0.23、等加重 **+24.6%/年**（SPY 15.0%）
    ・2013年(n=6) P=0.667 ／ 2015年(n=13) P=0.538 ＝事前登録した再現条件を満たした
    ・プール754件の刻み別: 50:**0.162** < 70:**0.366** < 85:**0.579**（ベース0.204）
    ・主観の堀(moat5)は lift +0.02、dom≥70 は P=0.00 ＝**分けたのは移行障壁の型ひとつだけ**
  ところが門の中では irr は **絶対MOAT指数の5本柱の1本（重み.25）** にすぎず、
  その堀指数も **70の関門を越えるか否か**のハードルとしてしか働かない（判定帯の変動係数は約10%）。
  **歴史が「唯一効く」と言った変数が、決定にほとんど現れていないのではないか。**

この道具が測ること:
  (a) 今 irr=85 が付いている社と、その分布（全体／判定圏／投下可）
  (b) **irr=85 を全部 70 に落としたら**誰がどう動くか＝85 が今まさに支えているもの
  (c) **判定圏の irr=70 を 85 に上げたら**誰が動くか＝85 のご褒美の大きさ
  (d) 判定圏での irr のばらつき（＝順位を作る力があるか）

  影の計測なので**パックを退避→書き換え→score_all→必ず元へ戻す**。正本は変えない。

使い方: python3 night/shadow_irr85.py
"""
import glob
import json
import os
import shutil
import subprocess
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = "out"
BAND = 72


def packs():
    return sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json")))


def read(p):
    return json.load(open(p, encoding="utf-8"))


def score():
    subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    return {r["t"]: r for r in json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}


def snapshot(sa):
    return {t: (r.get("s"), r.get("moat"), r.get("moatOK"), r.get("buy")) for t, r in sa.items()}


def diff(a, b, label):
    moved = [(t, a[t], b[t]) for t in a if t in b and (a[t][0] != b[t][0] or a[t][3] != b[t][3])]
    buy_a = sorted(t for t in a if a[t][3])
    buy_b = sorted(t for t in b if b[t][3])
    print(f"\n  【{label}】Ωか買付が動いた {len(moved)}社")
    for t, x, y in sorted(moved, key=lambda z: -abs((z[2][0] or 0) - (z[1][0] or 0)))[:14]:
        mark = "" if x[3] == y[3] else ("  🟢→⛔" if x[3] else "  ⛔→🟢")
        print(f"     {t:<8} Ω {x[0]:>5} → {y[0]:>5} ({(y[0] or 0)-(x[0] or 0):+.1f})"
              f"　堀 {x[1]} → {y[1]}{mark}")
    out_, in_ = sorted(set(buy_a) - set(buy_b)), sorted(set(buy_b) - set(buy_a))
    print(f"     投下可: 出 {' '.join(out_) or '—'} ／ 入 {' '.join(in_) or '—'}")


def main():
    base_sa = score()
    base = snapshot(base_sa)

    irr = {}
    for p in packs():
        t = os.path.basename(p).replace("_gate_pack.json", "")
        d = read(p)
        irr[t] = (d.get("data") or d).get("irr")

    band = [t for t, r in base_sa.items() if (r.get("s") or 0) >= BAND]
    buy = [t for t, r in base_sa.items() if r.get("buy")]
    print("■ irr=85 は今の門で何をしているのか")
    from collections import Counter
    for name, pool in (("全362社", list(irr)), (f"判定圏(Ω{BAND}+)", band), ("投下可", buy)):
        c = Counter(irr.get(t) for t in pool)
        tot = len(pool)
        s = " / ".join(f"{k if k is not None else '空欄'}:{v}({v/tot:.0%})"
                       for k, v in sorted(c.items(), key=lambda kv: -(kv[0] or 0)))
        print(f"  {name:<14} n={tot:<4} {s}")

    vals = [irr[t] for t in band if irr.get(t) is not None]
    if len(vals) > 1:
        m, sd = statistics.mean(vals), statistics.pstdev(vals)
        print(f"\n  判定圏の irr: 平均 {m:.1f} / 標準偏差 {sd:.1f} / **変動係数 {sd/m:.1%}**"
              f"（同じ帯の roic は約52% — irr は**ほぼ定数**で順位を作る力がない）")
    print(f"  irr=85 の社（投下可）: {' '.join(t for t in buy if irr.get(t)==85) or 'なし'}")

    bak = "/tmp/_irr85_bak"
    shutil.rmtree(bak, ignore_errors=True)
    os.makedirs(bak)
    for p in packs():
        shutil.copy(p, os.path.join(bak, os.path.basename(p)))
    try:
        # (b) irr=85 → 70
        for p in packs():
            d = read(p); x = d.get("data") or d
            if x.get("irr") == 85:
                x["irr"] = 70
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        diff(base, snapshot(score()), "irr=85 を全部 70 に落とす＝85 が今まさに支えているもの")

        # 戻してから (c) 判定圏の irr=70 → 85
        for f in os.listdir(bak):
            shutil.copy(os.path.join(bak, f), os.path.join(OUT, f))
        for p in packs():
            t = os.path.basename(p).replace("_gate_pack.json", "")
            if t not in band:
                continue
            d = read(p); x = d.get("data") or d
            if x.get("irr") == 70:
                x["irr"] = 85
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        diff(base, snapshot(score()), "判定圏の irr=70 を 85 に上げる＝85 のご褒美の大きさ")
    finally:
        for f in os.listdir(bak):
            shutil.copy(os.path.join(bak, f), os.path.join(OUT, f))
        subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
        after = snapshot(score())
        same = all(base[t] == after[t] for t in base)
        print(f"\n（パックと score_all.json を元へ戻した — 完全一致: {same}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
