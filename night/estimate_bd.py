#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""買付日(bd)を取得単価から**想定**する（2026-08-18新設・ユーザー指示「かいつけ日は想定日でいい」）

出力: state.json の `bd` / `bdEst` / `bdWin`。**表示専用の系にしか効かない**——
Ω・採点式・四関門・堀の関門・売却規律・配分はどれもこの欄を読まない。

■ なぜ「想定」と明示するのか
  取引履歴が無いので、判るのは「**終値がその水準だった日**」まで。しかも平均取得価額は
  複数回買付の平均でありうるので、**一致する日が実際の買付日とは限らない**
  （実測: MSFT は 2株@¥59,091 ＋ 1株@¥72,333 の合算で、2×59,091+72,333=190,515 とぴったり合う
   ＝単一の買付日は存在しない）。だから `bdEst:true` を必ず立て、
  **S&P500 との比較は「想定」と札を付けたまま出す**。

■ 二つの制約で挟む（ここが肝）
  A) 終値 ≈ bpx（平均取得価額・現地通貨）
  B) 終値 × ドル円 ≈ bjpy ÷ 株数（実際に出した円）
  **A と B が同じ日で交わるなら、独立な二系列が一致したということ**——偶然そうなる確率は低い。
  実測で MSFT は36日→**3日**、RMD は18日→**2日**まで狭まった。片方しか無ければ窓は広いままで、
  そのぶん答えは想定に依存する（`--report` が窓の両端で答えがどう動くかを出す）。

■ 想定日は**窓の中央値**にする（最も偏りが少ない・決定的）
  ⚠ 直感に反するが「最新の一致日」を採ってはいけない——保有期間が最短になる＝
  **S&P500 の複利期間も最短になる＝自分に一番有利な仮定**を選ぶことになる。
  実測 RMD: 最新なら S&P500 +1.1%（差 +10.4pt）／最古なら +77.0%（差 −65.5pt）＝**76pt の開き**。

使い方:
  python3 night/estimate_bd.py            測るだけ（窓と感度を出す）
  python3 night/estimate_bd.py --write    state.json へ書く
"""
import datetime
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST = os.path.join(ROOT, "state.json")
TOL = 0.005          # ±0.5%
_spec = importlib.util.spec_from_file_location("fr", os.path.join(ROOT, "night", "fetch_returns.py"))
fr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fr)   # 価格の採り方を再実装しない


def candidates(ser, fxs, sh, bpx, bjpy):
    """(窓, 使った制約) を返す。A∩B が空でないときだけ二制約と名乗る"""
    ds = sorted(ser)
    jpsh = (bjpy / sh) if (bjpy and sh) else None
    A = [d for d in ds if bpx and abs(ser[d][0] - bpx) / bpx < TOL] if bpx else []
    B = []
    if jpsh:
        for d in ds:
            f = fr.on_or_before(fxs, d)
            if f and abs(ser[d][0] * f[0] - jpsh) / jpsh < TOL:
                B.append(d)
    both = sorted(set(A) & set(B))
    if both:
        return both, "A∩B（終値とドル円の両方が一致）"
    if A:
        return A, "A（終値のみ）"
    if B:
        return B, "B（円の取得額のみ）"
    return [], "該当なし"


def main():
    write = "--write" in sys.argv
    st = json.load(open(ST, encoding="utf-8"))
    pf = json.loads(st["data"]["pf:portfolio"])
    t1 = int(time.time()); t0 = t1 - 86400 * 1200
    fxs = fr.yahoo("JPY=X", t0, t1)
    bench = fr.yahoo("^SP500TR", t0, t1)
    if not fxs or not bench:
        print("✗ ドル円か指数が取れない——**書かずに終わる**"); return 1
    fx1 = fr.last(fxs)[1][0]; b1 = fr.last(bench)[1][1]

    print("■ 買付日の想定（night/estimate_bd.py）")
    print(f"  {'銘柄':<6}{'想定日':<12}{'窓':<26}{'制約':<26}{'S&P500との差':>26}")
    n = 0
    for p in pf["positions"]:
        t = p["t"]; sh = float(p.get("sh") or 0)
        bpx = float(p.get("bpx") or 0); bjpy = float(p.get("bjpy") or 0)
        if not sh or (not bpx and not bjpy):
            print(f"  {t:<6}—— 取得単価も取得額も無いので想定できない"); continue
        ser = fr.yahoo(t if not t[:1].isdigit() else f"{t}.T", t0, t1)
        if not ser:
            print(f"  {t:<6}—— 価格が取れない"); continue
        win, how = candidates(ser, fxs, sh, bpx, bjpy)
        if not win:
            print(f"  {t:<6}—— 終値がその水準だった日が見つからない（{how}）"); continue
        pick = win[len(win) // 2]          # 中央値＝最も偏りが少ない
        cost = bjpy if bjpy else sh * bpx * fr.on_or_before(fxs, pick)[0]
        val = sh * fr.last(ser)[1][0] * fx1
        diffs = []
        for d in (win[0], pick, win[-1]):
            b0 = fr.on_or_before(bench, d); f0 = fr.on_or_before(fxs, d)[0]
            sp = cost * (b1 / b0[1]) * (fx1 / f0)
            diffs.append((val / cost - 1) - (sp / cost - 1))
        span = f"{win[0]}〜{win[-1]}({len(win)}日)"
        rng = f"{diffs[1]*100:+.1f}pt（窓の両端で {diffs[0]*100:+.1f}〜{diffs[2]*100:+.1f}）"
        print(f"  {t:<6}{pick:<12}{span:<26}{how:<26}{rng:>26}")
        if write:
            p["bd"] = pick; p["bdEst"] = True
            p["bdWin"] = {"first": win[0], "last": win[-1], "n": len(win), "how": how}
            n += 1
    if write:
        st["data"]["pf:portfolio"] = json.dumps(pf, ensure_ascii=False, separators=(",", ":"))
        st["savedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        open(ST, "w", encoding="utf-8").write(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
        print(f"\n→ state.json に {n}件の想定日を書いた（bdEst:true・取引履歴が判ったら上書きすること）")
    else:
        print("\n（--write で state.json へ書く）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
