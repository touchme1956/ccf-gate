#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_tc_roic.py — roic を「単年」から「through-cycle（5年の中央値／最悪値）」に替えたら
                          誰がどう動くかの影の計測。パックを退避→書換→score_all→**必ず元へ戻す**。

なぜ要るか（2026-08-03の実測で診断がついた）:
  audit_weights --q75 では 単年roic の実効が **38.2%** で単独最大、一方
  時間を通して見る欄（p1 3.7% / p2 4.8% / f1 3.3% / f5 0.9%）は合計 **12.7%** しかない。
  さらに `sustain`（.30・名前は「持つか」）の中身は gm([pm, pr]) ＝ **堀とROICの現在値だけ**。

  そこで「時間軸の欄の重みを上げる」案を先に影で測ったが（night/shadow_time_axis.py）、
  **どの案でも投下可から落ちる社が一つも無く、増えるだけ**だった＝門が厳しくならず緩くなる。
  原因を分布で確かめると、判定帯(Ω75+)での変動係数が
      p4 7.9% / f1 6.4% / p3 11.4% / p1 13.5% / p2 19.1%  に対し  **roic 64.0%**。
  ＝**時間軸の欄は判定帯でほぼ定数**で、定数の重みを上げても順位は動かない
  （v9.9.43のgmPt・v9.9.45のTAM柱と同じ「情報を持たない定数」の病）。
  **roicが支配的なのは重みが大きいからではなく、判定帯で唯一ばらついている数字だから。**

  → ならば直すべきは重みではなく**その唯一ばらつく数字が何を測っているか**。
    単年ROICを through-cycle ROIC に替えれば、**重みを1つも動かさずに** 38.2%が
    「今年の水準」から「5年を通した水準」へ変わる。CLAUDE.mdが積み残していた
    「through-cycleは未評価＝門2審査へ」を機械側で埋める話でもある。

候補:
  med5  5年の中央値（外れ年に強い。基準線として素直）
  w5    5年の最悪値（不況耐性そのもの。保守的すぎないかを見る）
  min(last,med5) 直近と中央値の小さいほう（悪化を即座に拾い、良化はゆっくり認める）

使い方: python3 night/shadow_tc_roic.py [tc_roic.jsonのパス]
"""
import json, os, glob, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
TC = sys.argv[1] if len(sys.argv) > 1 else "out/tc_roic.json"


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    d = json.load(open("out/score_all.json", encoding="utf-8"))
    return {r["t"]: r for r in (d["rows"] if isinstance(d, dict) else d)}


def main():
    tc = json.load(open(TC, encoding="utf-8"))["tc"]
    print(f"through-cycle ROIC の在庫: {len(tc)}社（5年系列が3年以上取れた社）\n")
    bak = tempfile.mkdtemp(prefix="ccf_packs_")
    for p in glob.glob("out/*_gate_pack.json"):
        shutil.copy2(p, bak)
    base = run()
    modes = {
        "med5 5年中央値": lambda v: v["med5"],
        "w5 5年最悪値": lambda v: v["w5"],
        "min(直近,中央)": lambda v: min(v["last"], v["med5"]),
    }
    res = {}
    try:
        for label, fn in modes.items():
            n = 0
            for t, v in tc.items():
                p = f"out/{t}_gate_pack.json"
                if not os.path.exists(p): continue
                d = json.load(open(p, encoding="utf-8"))
                if d.get("roic") is None: continue     # 算出不能はroicgフォールバックのまま触らない
                d["roic"] = round(fn(v), 1); n += 1
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            res[label] = run()
            buy = sorted(t for t, r in res[label].items() if r.get("buy"))
            q75 = [t for t, r in res[label].items() if (r.get("s") or 0) >= 75]
            print(f"{label:16s} 置換{n:3d}社  Ω75+ {len(q75):3d} / 🟢投下可 {len(buy):2d}  {' '.join(buy)}")
            for p in glob.glob("out/*_gate_pack.json"):     # 次の候補の前に必ず戻す
                b = os.path.join(bak, os.path.basename(p))
                if os.path.exists(b): shutil.copy2(b, p)
    finally:
        for p in glob.glob("out/*_gate_pack.json"):
            b = os.path.join(bak, os.path.basename(p))
            if os.path.exists(b): shutil.copy2(b, p)
        shutil.rmtree(bak, ignore_errors=True)
        run()
        print("\n※パックと score_all.json は元へ戻した（影の計測であって正本は変えていない）")

    buy0 = sorted(t for t, r in base.items() if r.get("buy"))
    print(f"\n現行（単年roic）      Ω75+ {len([1 for r in base.values() if (r.get('s') or 0)>=75]):3d} / 🟢投下可 {len(buy0):2d}  {' '.join(buy0)}")
    for label in modes:
        cur = res[label]
        d = sorted(((cur[t]["s"] - base[t]["s"], t) for t in base if t in cur), reverse=True)
        nb = sorted(t for t in cur if cur[t].get("buy") and not base[t].get("buy"))
        gone = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        moved = [x for x in d if abs(x[0]) > 0.05]
        print(f"\n=== {label}")
        print(f"  Ωが動く {len(moved)}社 / 最大 {d[0][0]:+.1f}pt ({d[0][1]}) / 最小 {d[-1][0]:+.1f}pt ({d[-1][1]})")
        print(f"  投下可に入る: {' '.join(nb) or 'なし'}")
        print(f"  投下可から外れる: {' '.join(gone) or 'なし'}")
        if gone:
            for t in gone:
                print(f"     {t:6s} Ω{base[t]['s']:5.1f} → {cur[t]['s']:5.1f}"
                      f"  直近{tc[t]['last']} / 中央{tc[t]['med5']} / 最悪{tc[t]['w5']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
