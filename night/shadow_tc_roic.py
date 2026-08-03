#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_tc_roic.py — roic を「単年」から「through-cycle（5年）」へ替えたら誰がどう動くかの影の計測。
                          パックを退避→書換→score_all→**必ず元へ戻す**。

なぜ要るか（2026-08-03の診断）:
  audit_weights --q75 で 単年roic の実効は **38.2%** で単独最大、時間を通して見る欄は合計 12.7%。
  さらに `sustain`(.30・名前は「持つか」)の中身は gm([pm, pr]) ＝堀とROICの**現在値だけ**。
  重みを上げる案（night/shadow_time_axis.py）は実測で**緩くなるだけ**だった——判定帯での変動係数が
  p4 7.9% / f1 6.4% / p1 13.5% / p2 19.1% に対し roic 64.0% ＝**時間軸の欄はほぼ定数**で、
  定数の重みを上げても順位は動かないから。**roicが支配的なのは、判定帯で唯一ばらついている数字だから。**
  → 直すべきは重みではなく、その唯一ばらつく数字が**何を測っているか**。

三つの約束:
  (1) **roic / roicg / roicEx を同時に替える。** roicだけ替えると roic<roicg という数学的に不可能な
      組み合わせができる（投下資本はのれん・無形を引いたほうが必ず小さいので roic≥roicg は恒等式）。
      初版はこれを 22-46% の社で作り、門の全件点検が err で捕まえた。
      KLACの分割・ADRのper・JP門0のptと同じ「基準の違う二つを割る」型。
  (2) **絶対値でなく比で適用する。** パックの値は審査官が原本で検算した値で、採取器の直近値と
      ずれる社がある（実測 ASML パック49.5 / 採取器43.2）。絶対値で置き換えると
      **through-cycleの効果と「採取器 vs 審査官」の差が混ざる**。
      new = パック値 × (5年値 ÷ 採取器の直近値) なら、変わるのは時間軸の分だけ。
  (3) **在庫のある社だけ触る。** 投下可12社は全社在庫あり（US10社=SEC / JP2社=EDINET）。

候補:
  med5  5年の中央値（外れ年に強い。基準線として素直）
  w5    5年の最悪値（不況耐性そのもの。保守的すぎないかを見る）
  min   min(直近, 中央値)＝**悪化は即座に拾い、良化はゆっくり認める**非対称

使い方: python3 night/shadow_tc_roic.py
"""
import json, os, glob, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
TC = "out/tc_roic.json"
CAP = 60.0          # JP ROIC規約の上限。US側は元々上限を置いていないので JP パックにだけ効かせる


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    d = json.load(open("out/score_all.json", encoding="utf-8"))
    return {r["t"]: r for r in (d["rows"] if isinstance(d, dict) else d)}


def apply(t, v, mode, d):
    """through-cycle を当てる。三つの約束——

    (1) **roic/roicg/roicEx を同時に替える**。片方だけ替えると roic<roicg（NOPAT>0では
        数学的に不可能）ができる。KLACの分割・ADRのper・JP門0のptと同じ「基準の違う二つを割る」型。
    (2) **絶対値でなく比で適用する**。パックの値は審査官が原本で検算した値で、採取器の直近値と
        ずれる社がある（実測 ASML パック49.5 / 採取器43.2）。絶対値で置き換えると
        through-cycleの効果と「採取器 vs 審査官」の差が混ざる。
        **比は欄ごとに取る**——単一係数だと roicGap=roic−roicg の信号そのものを潰す
        （実測APH: 本当のthrough-cycle gapは 中央roic42.2−中央roicg16.1=**26.1pt**で罰の線15ptを
        大きく超えるのに、単一係数だと17.6ptにしか見えない）。
    (3) **採取器とパックが食い違う社には当てない**。審査官が採取器の値を棄却して書き直した社
        （実測 GEN: 採取器107.9→パック15.5 ／ CHH 51.9→19.9 ／ RBA 56.5→10.6）では、
        **採取器の5年系列も同じ縮退を含む**ので比が意味を持たない。触らず作業リストへ出す
        （誤値より空欄）。線は直近値どうしが15%以内。
    """
    if not v.get("last") or not v.get("g_last"): return 0, "採取器の直近値が無い"
    if d.get("roic") is None or d.get("roicg") in (None, ""): return 0, "パックのroic/roicgが空"
    dr = abs(d["roic"] - v["last"]) / max(abs(v["last"]), 1e-9)
    dg = abs(float(d["roicg"]) - v["g_last"]) / max(abs(v["g_last"]), 1e-9)
    if max(dr, dg) > 0.15:
        return 0, f"採取器とパックが{max(dr,dg)*100:.0f}%食い違う（審査官が棄却した値＝系列も信用できない）"
    k  = {"med5": v["med5"], "w5": v["w5"], "min": min(v["last"], v["med5"])}[mode] / v["last"]
    kg = {"med5": v["g_med5"], "w5": v["g_w5"], "min": min(v["g_last"], v["g_med5"])}[mode] / v["g_last"]
    jp = t[:1].isdigit()
    cap = (lambda x: round(min(x, CAP) if jp else x, 1))
    nr, ng = cap(d["roic"] * k), cap(float(d["roicg"]) * kg)
    # (4) **恒等式が壊れる社は変換しない。** NOPAT>0 では roic≥roicg が恒等式（投下資本はのれん・
    #     無形を引いたほうが必ず小さい）。採取器の中央値どうしは順序統計量として必ずこれを満たすが、
    #     パック側で審査官が roic と roicg の関係を書き換えている社（実測 MPTI: 採取器 13.9/12.6 に対し
    #     パックは 12.6/12.6 と**等値に直してある**）では、欄ごとの比を掛けると逆転する。
    #     clampで黙って直すと審査官の判断を機械が上書きすることになるので、**触らず作業リストへ出す**。
    if nr > 0 and ng > 0 and nr < ng:
        return 0, f"変換すると roic{nr}<roicg{ng} で恒等式が壊れる（パックの両欄の関係が採取器と違う）"
    n = 0
    for f, val in (("roic", nr), ("roicg", ng), ("roicEx", nr)):
        if d.get(f) is not None:
            d[f] = val; n += 1
    return n, None


def main():
    tc = json.load(open(TC, encoding="utf-8"))["tc"]
    print(f"through-cycle 在庫 {len(tc)}社\n")
    bak = tempfile.mkdtemp(prefix="ccf_packs_")
    for p in glob.glob("out/*_gate_pack.json"):
        shutil.copy2(p, bak)
    base = run()
    res = {}
    try:
        for mode, label in (("med5", "med5 5年中央値"), ("w5", "w5 5年最悪値"),
                            ("min", "min(直近,中央値)")):
            n = 0
            for t, v in tc.items():
                p = f"out/{t}_gate_pack.json"
                if not os.path.exists(p): continue
                d = json.load(open(p, encoding="utf-8"))
                cnt, why = apply(t, v, mode, d)
                if cnt:
                    n += 1
                    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            res[label] = run()
            buy = sorted(t for t, r in res[label].items() if r.get("buy"))
            q75 = [t for t, r in res[label].items() if (r.get("s") or 0) >= 75]
            err = sum(1 for r in res[label].values() if r.get("audE"))
            print(f"{label:16s} 置換{n:3d}社  Ω75+ {len(q75):3d} / 🟢投下可 {len(buy):2d} / 要修正{err}件")
            print(f"                 {' '.join(buy)}")
            for p in glob.glob("out/*_gate_pack.json"):
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
    print(f"\n現行（単年roic）  Ω75+ {len([1 for r in base.values() if (r.get('s') or 0)>=75]):3d} / 🟢投下可 {len(buy0):2d}")
    print(f"                 {' '.join(buy0)}")
    for label in res:
        cur = res[label]
        d = sorted(((cur[t]["s"] - base[t]["s"], t) for t in base if t in cur), reverse=True)
        nb = sorted(t for t in cur if cur[t].get("buy") and not base[t].get("buy"))
        gone = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        print(f"\n=== {label}")
        print(f"  Ωが動く {len([x for x in d if abs(x[0])>0.05])}社 / 最大 {d[0][0]:+.1f} ({d[0][1]}) / 最小 {d[-1][0]:+.1f} ({d[-1][1]})")
        print(f"  投下可に入る: {' '.join(nb) or 'なし'} / 外れる: {' '.join(gone) or 'なし'}")
        for t in gone:
            v = tc.get(t, {})
            print(f"     {t:6s} Ω{base[t]['s']:5.1f}→{cur[t]['s']:5.1f}  堀{base[t].get('moat')}  "
                  f"採取器 直近{v.get('last')}/中央{v.get('med5')}/最悪{v.get('w5')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
