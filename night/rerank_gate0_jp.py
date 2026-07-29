#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rerank_gate0_jp.py — 門0-JPの待ち行列を「測れる指標だけ」で組み直す（2026-07-29・ユーザー明示指示）

■ 何が壊れていたか
  旧 pt = 0.35*min(roic,60) + 0.30*min(cagr,30) + 0.25*min(opm,40) + 0.10*min(eq,80)
  この式のすぐ隣（gate0_jp_queue.json の note）に、こう書いてある——
    「roicはEDINET生値でnet-cash/資産軽量で異常値あり＝門式で審査時に再計算」
  **異常値だと判っている入力に、最大の重み0.35を置いていた。**

■ 実測（2026-07-29・母集団200社／うち門2で審査済み36社で突き合わせ）
  生の値と、審査官が原本から出し直した値の倍率:
    opm  中央値 **1.00倍**（四分位 1.00〜1.00・35/36社で完全一致）  ← 信頼できる
    cagr 中央値 **1.00倍**（四分位 0.92〜1.21）                    ← おおむね信頼できる
    roic 中央値 **5.01倍**（四分位 3.38〜13.40・最大 **204倍**）    ← 使えない
  roic_artifact フラグも役に立たない: False の138社でも中央値3.5倍で、
  7034プロレド・パートナーズは 生72.5% → 審査後 **−10.2%（符号が逆）** なのに旧ptで**1位**だった。

  結果、待ち行列（pt上位50社）の中身は:
    roic_artifact=True     33/50社(66%)  ← 門2が「取込拒否」と規約で決めている種類
    生ROIC>60%（規約超え）  47/50社(94%)  生5551.9% / 4275.2% / 2608.2% …
    cagr中央値 30.0%（母集団は15.0%）＝小型高成長に強く偏る
  ディスコ(6146)は roic 45.8%・営業利益率42.3%（母集団15位）・artifact=False なのに
  **ROICが本物だから**生297%・1284%・5551%の社に負けて73位＝キュー(上位50)に届いていなかった。

■ 直し方（今日ずっと使ってきた作法と同じ）
  **測れない項は落として、残りの重みを再正規化する**（ccfMoatのdom/moatW、v9.9.44のpenと同じ）。
  重みを下げるのではなく外すのは、roicが「精度が悪い」のではなく**桁で違う**から。
    新 pt = 0.4615*min(cagr,30) + 0.3846*min(opm,40) + 0.1538*min(eq,80)
            （旧の 0.30/0.25/0.10 を合計0.65で再正規化＝設計者の相対比を保つ）
  roic_artifact による除外はしない——roicを式から外した以上、フラグは順位に関係しない。
  62社を捨てずに済み、審査時に門式ROICで再計算するという既存の流れも変わらない。

■ 使い方
  python3 night/rerank_gate0_jp.py           新旧を比較して表示（書き換えない）
  python3 night/rerank_gate0_jp.py --write   gate0_jp_queue.json を更新（旧は .prev へ退避）
"""
import csv
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
CSV = "gate0_jp_all.csv"
QUEUE = "gate0_jp_queue.json"
TOP_N = 50

OLD_NOTE = "pt=0.35*min(roic,60)+0.30*min(cagr,30)+0.25*min(opm,40)+0.10*min(eq,80)"
NEW_PT = "pt=0.4615*min(cagr,30)+0.3846*min(opm,40)+0.1538*min(eq,80)"


def clamp(x, hi):
    return max(0.0, min(float(x), hi))


def old_pt(r):
    return (0.35 * clamp(r["roic"], 60) + 0.30 * clamp(r["cagr"], 30)
            + 0.25 * clamp(r["opm"], 40) + 0.10 * clamp(r["eq"], 80))


def new_pt(r):
    return (0.4615 * clamp(r["cagr"], 30) + 0.3846 * clamp(r["opm"], 40)
            + 0.1538 * clamp(r["eq"], 80))


def main():
    write = "--write" in sys.argv
    rows = [{k: (float(v) if k in ("roic", "opm", "cagr", "eq", "pt") else v)
             for k, v in r.items()} for r in csv.DictReader(open(CSV, encoding="utf-8"))]
    for r in rows:
        r["pt_old"], r["pt_new"] = old_pt(r), new_pt(r)
    o = sorted(rows, key=lambda r: -r["pt_old"])
    n = sorted(rows, key=lambda r: -r["pt_new"])
    ro = {r["sec"]: i + 1 for i, r in enumerate(o)}
    rn = {r["sec"]: i + 1 for i, r in enumerate(n)}

    ino, inn = {r["sec"] for r in o[:TOP_N]}, {r["sec"] for r in n[:TOP_N]}
    added, dropped = sorted(inn - ino), sorted(ino - inn)
    nm = {r["sec"]: r["nm"] for r in rows}

    print(f"母集団 {len(rows)}社 / 待ち行列は上位 {TOP_N}社\n")
    print(f"■ 新キューに入る {len(added)}社")
    for c in sorted(added, key=lambda c: rn[c]):
        r = next(x for x in rows if x["sec"] == c)
        print(f"   {rn[c]:3d}位(旧{ro[c]:3d}位) {c:5s} {nm[c][:20]:22s} "
              f"opm{r['opm']:5.1f} cagr{r['cagr']:5.1f} eq{r['eq']:5.1f} 生roic{r['roic']:8.1f} art={r['roic_artifact']}")
    print(f"\n■ 新キューから外れる {len(dropped)}社（生ROICの高さだけで上位に来ていた社が中心）")
    for c in sorted(dropped, key=lambda c: ro[c]):
        r = next(x for x in rows if x["sec"] == c)
        print(f"   旧{ro[c]:3d}位→新{rn[c]:3d}位 {c:5s} {nm[c][:20]:22s} "
              f"opm{r['opm']:5.1f} cagr{r['cagr']:5.1f} 生roic{r['roic']:8.1f} art={r['roic_artifact']}")
    art_o = sum(1 for r in o[:TOP_N] if r["roic_artifact"] == "True")
    art_n = sum(1 for r in n[:TOP_N] if r["roic_artifact"] == "True")
    print(f"\n■ キューに占める roic_artifact=True の割合: {art_o}/{TOP_N} → {art_n}/{TOP_N}")
    for c in ("6146", "6920", "6857"):
        if c in ro:
            print(f"   {c} {nm[c][:16]:18s} {ro[c]:3d}位 → **{rn[c]:3d}位**")

    if not write:
        print("\n※--write で gate0_jp_queue.json を更新（旧は .prev へ退避）")
        return 0

    if os.path.exists(QUEUE):
        shutil.copy2(QUEUE, QUEUE + ".prev")
    old = json.load(open(QUEUE, encoding="utf-8")) if os.path.exists(QUEUE) else {}
    out = {
        "generated": "2026-07-29",
        "source": old.get("source", "EDINET_DB screen_companies"),
        "filter": old.get("filter", "roic>=15 & opm>=15 & cagr3y>=5 & equity>=50"),
        "total_passed": old.get("total_passed"),
        "note": (f"門0-JP定量ふるい(1次)。{NEW_PT}。"
                 "**ptからroicを外した(2026-07-29・ユーザー明示指示)**——EDINET生ROICは審査後の値と"
                 "中央値5.01倍・最大204倍ずれ、7034は符号まで逆(生72.5%→審査後−10.2%)で旧ptの1位だった。"
                 "opmは生/審査後が1.00倍(35/36社で完全一致)、cagrも1.00倍で信頼できるため、"
                 "旧の0.30/0.25/0.10を合計0.65で再正規化して残した(測れない項は落として再正規化＝門の作法)。"
                 "roicは審査時に門式(NOPAT÷(有利子負債+自己資本−のれん)・現金非控除・60%上限)で算出する。"
                 "定性(p/f・堀)は門2審査で評価。旧キューは gate0_jp_queue.json.prev"),
        "queue": [{"sec": r["sec"], "edinet": r["edinet"], "nm": r["nm"], "ind": r["ind"],
                   "opm": r["opm"], "cagr": r["cagr"], "eq": r["eq"],
                   "roic_raw": r["roic"], "roic_artifact": r["roic_artifact"],
                   "pt": round(r["pt_new"], 2)} for r in n[:TOP_N]],
    }
    json.dump(out, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {QUEUE} を更新（{TOP_N}社）。旧は {QUEUE}.prev")
    return 0


if __name__ == "__main__":
    sys.exit(main())
