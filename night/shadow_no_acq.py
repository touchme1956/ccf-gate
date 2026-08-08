#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_no_acq.py — **「買収を無視したら誰がどう動くか」**（2026-08-08新設）

なぜ要るか（ユーザーの問い「買収は無視するとどうなる？」）:
  LOAR（roic 34.5 / roicg 5.0・乖離29.5）と RBC（38.3 / 7.0・乖離31.3）は、
  堀は関門を通っているのにΩで落ちる。落としているのは**買収に払った代金**である。
  では**払った代金を無視して事業だけを見たら**、門は何と言うのか。

  門が買収を裁く経路は**三つ**あり、それぞれ別のものを測っている:
    (1) `roicGap = roic − roicg > 15 ∧ acq5='yes'` → 段階減点（v9.9.93: 15pt→0 / 30pt→6）
        ＝「のれんを除けば高いが、払った代金を入れると落ちる」＝買収規律の罰
    (2) `roicg < WACC` → −8
        ＝全資本ベースで資本コストを稼げていない＝価値破壊の警報
    (3) roic そのもの（Ωの実効36.5%＝単独最大の入力）
        ＝**のれんと無形を分母から除いた**利回り。既に「買収代金の一部を無視した」数字である

  したがって「買収を無視する」は一意ではない。三段階で測る:
    A 現行
    B (1)だけ外す ＝ acq5 を全社 'no' に（罰は消えるが roicg は残る）
    C (1)+(2) を外す ＝ さらに roicg を roic と同値に置く（＝**払った代金を完全に無視**）

  **これは影の計測であって規約の変更ではない。** パックは必ず元へ戻す（絶対のルール1）。

使い方: python3 night/shadow_no_acq.py [--write]   （--write で out/shadow_no_acq.json を保存）
"""
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
WRITE = "--write" in sys.argv[1:]
OUT = "out"
BAK = "/tmp/_shadow_no_acq_bak"


def packs():
    return sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json")))


def score():
    subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    return {r["t"]: r for r in json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}


def snap(sa):
    return {t: (r.get("s"), r.get("moat"), r.get("buy"), r.get("quali"), r.get("kills"))
            for t, r in sa.items()}


def diff(base, now, label, focus=()):
    moved = [(t, base[t], now[t]) for t in base
             if t in now and (base[t][0] != now[t][0] or base[t][2] != now[t][2])]
    bb = sorted(t for t in base if base[t][2])
    nb = sorted(t for t in now if now[t][2])
    print(f"\n  【{label}】Ωか買付が動いた {len(moved)}社")
    for t, a, b in sorted(moved, key=lambda z: -((z[2][0] or 0) - (z[1][0] or 0)))[:14]:
        mk = "" if a[2] == b[2] else ("  ⛔→🟢" if b[2] else "  🟢→⛔")
        print(f"     {t:<7} Ω {a[0]:>5} → {b[0]:>5} ({(b[0] or 0)-(a[0] or 0):+.1f}){mk}")
    out_, in_ = sorted(set(bb) - set(nb)), sorted(set(nb) - set(bb))
    print(f"     投下可 {len(bb)}社 → {len(nb)}社 ／ 出 {' '.join(out_) or '—'} ／ 入 {' '.join(in_) or '—'}")
    q0 = sum(1 for t in base if base[t][3])
    q1 = sum(1 for t in now if now[t][3])
    print(f"     四関門通過(資格) {q0}社 → {q1}社")
    if focus:
        print(f"     注目: " + " ／ ".join(
            f"{t} Ω{base[t][0]}→{now[t][0]}" for t in focus if t in base and t in now))
    return dict(moved=len(moved), buy_before=bb, buy_after=nb, quali_before=q0, quali_after=q1)


def main():
    base_sa = score()
    base = snap(base_sa)
    FOCUS = ("LOAR", "RBC", "TDG", "ENTG", "MKSI", "BWXT", "NOVT", "HXL", "ST", "APH", "BR", "ROP")

    acq, gap = [], []
    for p in packs():
        t = os.path.basename(p).replace("_gate_pack.json", "")
        d = json.load(open(p, encoding="utf-8"))
        x = d.get("data") or d
        if str(x.get("acq5")) == "yes":
            acq.append(t)
        ro, rg = x.get("roic"), x.get("roicg")
        if isinstance(ro, (int, float)) and isinstance(rg, (int, float)) and ro - rg > 15:
            gap.append((t, round(ro - rg, 1)))

    print("■ 「買収を無視する」と誰がどう動くか（影の計測・規約は不変）")
    print(f"  acq5='yes' の社: **{len(acq)}社** ／ 乖離(roic−roicg)>15pt の社: **{len(gap)}社**")
    top = sorted(gap, key=lambda z: -z[1])[:10]
    print("  乖離の大きい順: " + " / ".join(f"{t} {g}" for t, g in top))

    shutil.rmtree(BAK, ignore_errors=True)
    os.makedirs(BAK)
    for p in packs():
        shutil.copy(p, os.path.join(BAK, os.path.basename(p)))
    res = {}
    try:
        # ── B: 買収規律の罰だけ外す（acq5 を全社 'no'）───────────────────
        for p in packs():
            d = json.load(open(p, encoding="utf-8"))
            x = d.get("data") or d
            if str(x.get("acq5")) == "yes":
                x["acq5"] = "no"
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        res["B"] = diff(base, snap(score()),
                        "B: 買収規律の罰(roicGap−6)だけ外す＝acq5を全社'no'", FOCUS)

        # ── C: さらに払った代金そのものを無視（roicg ← roic）──────────────
        for f in os.listdir(BAK):
            shutil.copy(os.path.join(BAK, f), os.path.join(OUT, f))
        for p in packs():
            d = json.load(open(p, encoding="utf-8"))
            x = d.get("data") or d
            ro, rg = x.get("roic"), x.get("roicg")
            if str(x.get("acq5")) == "yes":
                x["acq5"] = "no"
            if isinstance(ro, (int, float)) and isinstance(rg, (int, float)) and ro > rg:
                x["roicg"] = ro
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        res["C"] = diff(base, snap(score()),
                        "C: 払った代金を完全に無視＝roicg←roic（roicg<WACCの−8も同時に消える）", FOCUS)
    finally:
        for f in os.listdir(BAK):
            shutil.copy(os.path.join(BAK, f), os.path.join(OUT, f))
        after = snap(score())
        same = all(base[t] == after[t] for t in base)
        print(f"\n（パックと score_all.json を元へ戻した — 完全一致: {same}）")

    print("\n■ 読み方")
    print("  ・**Bで動く社は『買収そのものが罰されている』のではない**——罰は")
    print("    `乖離>15pt ∧ acq5=yes` でしか出ない＝**払った代金を入れると利回りが落ちる買収**だけを裁いている")
    print("    （v9.9.93の段階減点で、乖離が小さいほど罰も軽い＝一律の罰ではなく質のフィルタ）")
    print("  ・**Cは『買った事業だけを見る』世界**。roicg を消すと、")
    print("    LOAR(5.0)・RBC(7.0)・ROP(6.1)のような『事業は良いが高く買った』社と、")
    print("    自前で育てた社が**同じ土俵に並ぶ**。歴史(2026-08-06)は逆U字を出しており、")
    print("    買収しない群が最下位(5.6%/年)・控えめが最良(9.1%)・大きく買う群は6.1%＝")
    print("    **買収を一律に罰するのは誤りだが、大きく買う群を通してよいという含意も無い**")

    if WRITE:
        p = os.path.join(OUT, "shadow_no_acq.json")
        json.dump(dict(generated="2026-08-08", acq5_yes=acq, gap_over15=gap, result=res),
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
