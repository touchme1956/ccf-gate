#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_roiic.py — 既存パックの roiic / roiic5 を原本から機械算出して充填する（2026-07-29新設）

なぜ要るか:
  roiic（ROIIC³）は門の未来門 F6「内部複利」の入力だが、**全316パックで空欄**だった。
  空欄だと roiicNA=true になり、F6 は中身に一切入らず **58 の定数**を返す:
      const F6=(()=>{ if(roiicNA){ return 58; } ... })   ← 316社ぜんぶここで返っていた
  つまり F6 の中の「再投資率 ＝ 1 − FCF転換率」の計算は**一度も実行されておらず**、
  キル「ROIIC³<WACC（複利停止）」も**一度も発火していなかった**。
  長期複利の余地は g = 再投資率 × ROIIC なので、ここが死んでいると門は複利余地を測れない。
  実効重みは F6 が Ω の 3.7%。滑走路系（f1 4.3% + F6 3.7% + F11 2.8% + f2 1.8%）のうち
  F6 だけが定数だった。

何を書くか（絶対のルール8: 値を書くなら根拠も書く）:
  ・roiic / roiic5 と、_meta.evidence に **ΔNOPAT・ΔIC の実額と年**、_meta.provenance に "machine"
  ・**'na' も立派な答え**——「成熟還元型＝再投資が限定的」の意味。門はこれを F6=58 で扱う。
    判らないときに低い数字を置くと**複利停止キルを誤爆させる**ので、迷ったら 'na' に倒す。

安全側の設計:
  ・既に値が入っている欄は触らない（審査官が原本で置いた値のほうが機械より強い）
  ・ΔIC ≤ 0 または ΔIC/IC(古) < 10% → 'na'
  ・|ROIIC| > 150% → 'na'（分母が小さく識別力なし。roicの「ICが自己資本の2割未満」ガードと同じ思想）
  ・系列が最新年から遅れていれば算出しない（絶対のルール7の年検問）

使い方:
  python3 night/fill_roiic.py            検算のみ（何がどう入るかを表示）
  python3 night/fill_roiic.py --write    パックへ書き込む
  python3 night/fill_roiic.py NVDA MSFT  指定銘柄のみ
日本株(コード始まり)はEDINET経路なので対象外。
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import hachimon_fetch as H       # noqa: E402  採取器をそのまま呼ぶ＝二重正本を作らない

# 2026-08-04(P2): "2026-07-29" のハードコードだった——後日実行しても過去日で kenshi に刻まれる。実行日を使う
import datetime  # noqa: E402
TODAY = datetime.date.today().isoformat()


def main():
    write = "--write" in sys.argv
    only = {a.upper() for a in sys.argv[1:] if not a.startswith("--")}

    packs = []
    for f in sorted(os.listdir("out")):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        if re.match(r"^\d", t):
            continue
        if only and t.upper() not in only:
            continue
        packs.append(t)

    n_val = n_na = n_skip = n_have = 0
    err = []
    vals = []
    for t in packs:
        p = f"out/{t}_gate_pack.json"
        d = json.load(open(p, encoding="utf-8"))
        if d.get("roiic") not in (None, ""):
            n_have += 1
            continue
        try:
            calc = H.build_numbers(H.facts_of(H.cik_of(t)))
        except (Exception, SystemExit) as e:
            err.append((t, str(e)[:60]))
            continue
        r3, r5 = calc.get("roiic"), calc.get("roiic5")
        evid = calc.get("_evid") or {}
        if r3 is None:
            n_skip += 1
            continue
        if r3 == "na":
            n_na += 1
        else:
            n_val += 1
            vals.append((t, r3, r5))
        print(f"{t:6s} roiic={str(r3):>6s}  roiic5={str(r5):>6s}")
        if write:
            m = d.setdefault("_meta", {})
            ev = m.setdefault("evidence", {})
            pv = m.setdefault("provenance", {})
            d["roiic"] = r3
            if evid.get("roiic"):
                ev["roiic"] = evid["roiic"]
            pv["roiic"] = "machine"
            if r5 is not None:
                d["roiic5"] = r5
                if evid.get("roiic5"):
                    ev["roiic5"] = evid["roiic5"]
                pv["roiic5"] = "machine"
            line = (f"{TODAY} roiic機械算出（新設・v9.9.46）: 3年窓={r3} / 5年窓={r5}。"
                    f"空欄のままだと門は roiicNA として F6=58 の定数を返し、"
                    f"『再投資率×ROIIC』も複利停止キルも一度も作動しない状態だった")
            k = m.get("kenshi")
            if isinstance(k, list):
                k.append(line)
            elif isinstance(k, str) and k:
                m["kenshi"] = k + "\n" + line
            else:
                m["kenshi"] = [line]
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n対象 {len(packs)}社 / 数値が入った {n_val} / 'na'（成熟還元型）{n_na}"
          f" / 算出不能で空欄のまま {n_skip} / 既に値あり {n_have}")
    if vals:
        v = sorted(x[1] for x in vals)
        print(f"  ROIIC³の分布: 中央値 {v[len(v)//2]:.1f}% / 最小 {v[0]:.1f}% / 最大 {v[-1]:.1f}%"
              f" / WACC(概ね8-11%)未満 {sum(1 for x in v if x < 9):d}社"
              f"——ここが複利停止キルの候補（門はWACCを個別に算出して裁く）")
    if err:
        print(f"  取得失敗 {len(err)}社: " + " ".join(t for t, _ in err))
    if not write:
        print("  ※--write で書き込む")
    return 0


if __name__ == "__main__":
    sys.exit(main())
