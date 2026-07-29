#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_roic.py — ROICが「分母の縮退」で発散していないかを全パックで点検する（2026-07-29新設）

なぜ要るか（絶対のルール7「欠測をゼロと読むな」の検査器）:
  門の roic は **のれん除外版** ＝ NOPAT ÷ (自己資本 + 有利子負債 − のれん − 無形)。
  買収で伸びた会社は自己資本の大半がのれん＋無形なので、**分母が自己資本のごく一部まで縮退し、
  わずかな推定誤差が桁で暴れる**。実測:
    NJR  16.5 → 真値6.6（有利子負債3.6十億$が丸ごと欠落＝タグ不在をゼロと読んでいた）
    HEI  93.0 → null（負債を正しく入れても63.4%。IC が自己資本の31%まで縮退し
                      5年系列が 71.7/80.6/51.1/59.1/63.4 と桁で振れて識別力なし）
    APH 163.4 → 28.0 ／ COLL 160.3 → 41.3 ／ TRN 63.1 → 8.0
  日本株では同型を 2026-07-28 に規約化済み（min(...,60) の60%上限）。米国側には上限が無い。

**実測で判った——roic>60 は弱い信号。本当の判別子は IC/自己資本**（2026-07-29 Ω70+の7社で検証）:
  MA   roic 74.9→**131.0**  IC=自己資本の150.2%（自社株買いで自己資本が薄い）＝縮退なし・実測が正しい
  MCO  roic 93.6→**93.7**   IC=自己資本の69.4% ＝縮退なし・実測が正しい
  NVDA roic 78.1 据置        IC=自己資本の90.0%（のれん+無形が自己資本の15.4%しかなく構造的に縮退しえない）
  CTAS roic 62.6 据置        縮退なし
  SPGI roic 147.8→**null**  のれん36,475+無形16,271が自己資本31,127の1.69倍 → **IC=−8,531（負）**＝定義上算出不能
  RELX roic 132.4→**null**  のれん7,930+無形3,072が自己資本2,366の4.65倍 → **IC=−1,369（負）**＝同上
  IDXX roic 71.1→**56.4**   縮退ではなく、リボルビング枠 LinesOfCreditCurrent 398,000千$ の数え落とし
  ＝「60%超だから怪しい」はほぼ外れ、「のれん+無形が自己資本を上回る」が当たり。
  この検査器は roic/roicg 比を代理指標にしているが、**代理でしかない**。判定は原本の IC/自己資本 で行うこと。

**重要な但し書き — 高いROICそのものは異常ではない**:
  roic と roicg の乖離は門が意図して作っている（roic=事業の質 / roicg=買収規律、
  roicGap = roic − roicg > 15 を買収依存として減点する設計）。資産軽量企業のROICが高いのも当然。
  したがってこの検査器は「疑わしい帯」を出すだけで、**値の正否は原本でしか決まらない**。
  出力は再監査の作業リストであって、有罪判決ではない。

仕分け:
  【要検算】roic > 60 かつ roicg との乖離が大きい（＝分母縮退が主因の疑いが濃い）
  【注意】  roic > 60 だが roicg も高い（＝本当に資本が軽い可能性。実測で確かめる価値あり）
  【参考】  乖離のみ大きい（買収体として設計どおり。roicGapの減点で既に処理されている）

使い方:
  python3 night/audit_roic.py           全パック
  python3 night/audit_roic.py --q70     Ω70+ だけ（買付に効く帯。out/score_all.json が要る）
  python3 night/audit_roic.py --list    要検算のコード列だけ
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

CAP = 60.0        # 日本株規約と同じ上限。これを超える帯は「資本が軽い」の言い換えで識別力が乏しい
GAP_X = 3.0       # roic / roicg がこの倍率以上＝のれん控除で分母が大きく縮んでいる


def classify(roic, roicg):
    """戻り: (区分, 理由) / 疑いが無ければ None"""
    if roic is None:
        return None
    try:
        r = float(roic)
    except Exception:
        return None
    g = None
    if roicg is not None:
        try:
            g = float(roicg)
        except Exception:
            g = None
    ratio = (r / g) if (g and g > 0) else None
    if r > CAP and ratio and ratio >= GAP_X:
        # 代理指標にすぎない。実測では MA(131.0)・MCO(93.7) が「縮退なし・実測が正しい」だった一方、
        # SPGI・RELX は IC が**負**（のれん+無形が自己資本+負債を上回る）で定義上算出不能だった。
        # 原本で IC/自己資本 を出すまでは、この区分は「調べる価値がある」以上を意味しない。
        return ("要検算", f"roic={r:.1f}>{CAP:.0f} かつ roic/roicg={ratio:.1f}倍"
                        f"——原本で IC/自己資本 を確かめよ（負またはごく小なら算出不能）")
    if r > CAP:
        return ("注意", f"roic={r:.1f}>{CAP:.0f}（roicg={g if g is not None else '—'}）"
                       f"——本当に資本が軽い可能性。原本で確かめる価値あり")
    if ratio and ratio >= GAP_X:
        return ("参考", f"roic/roicg={ratio:.1f}倍——買収体として設計どおり。roicGapの減点で処理済み")
    return None


def main():
    argv = sys.argv[1:]
    only = None
    if "--q70" in argv:
        try:
            rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
            only = {r["t"] for r in rows if r.get("s", 0) >= 70}
        except Exception:
            print("out/score_all.json が無い。先に `node night/score_all.js` を回すこと")
            return 1
    try:
        sc = {r["t"]: r.get("s") for r in
              json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}
    except Exception:
        sc = {}

    buckets = {"要検算": [], "注意": [], "参考": []}
    for f in sorted(os.listdir(OUT)):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        if only is not None and t not in only:
            continue
        try:
            d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
        except Exception:
            continue
        c = classify(d.get("roic"), d.get("roicg"))
        if c:
            buckets[c[0]].append((t, sc.get(t), d.get("roic"), d.get("roicg"), d.get("nde"), c[1]))

    if "--list" in argv:
        print(" ".join(t for t, *_ in buckets["要検算"]))
        return 0

    for k in ("要検算", "注意", "参考"):
        g = sorted(buckets[k], key=lambda x: -(x[1] or 0))
        print(f"\n【{k}】{len(g)}社")
        for t, s, r, rg, nde, why in g:
            print(f"  {t:<6} Ω{str(s):<6} roic={str(r):<8} roicg={str(rg):<8} nde={str(nde):<7} {why}")
    print("\n※高いROICそのものは異常ではない——のれん除外ROICは買収体・資産軽量企業ほど高く出るのが設計。")
    print("  この一覧は再監査の作業リストであって有罪判決ではない。値の正否は原本でしか決まらない。")
    print("  検算のしかた: 10-Kの実額で NOPAT ÷ (自己資本 + 有利子負債 − のれん − 無形) を組み直す。")
    print("  **判定は roic の水準ではなく IC/自己資本 で行う**——負またはごく小なら算出不能としてnull化し、")
    print("  経済実態は roicg(のれん込み)で評価する旨を_metaに書く。IC が健全なら60%超でもそれが実測。")
    print("  実測(2026-07-29): SPGI/RELX は IC が負→null。MA(131.0)/MCO(93.7)/NVDA(78.1) は縮退なしで採用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
