#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日本株ROICを米国株規約へ揃えたときの影の計測（正本の採点は変えない）。

JP規約(2026-07-28)  : NOPAT=営業利益×0.70固定 / IC=自己資本+有利子負債−のれん / min(...,60) / IC縮退ガードなし
米国規約(絶対のルール7-b): NOPAT=営業利益×(1−実効税率) / IC=自己資本+有利子負債−のれん−無形 / 上限なし /
                          IC<基準(自己資本、負なら総資産)の20%なら算出不能

  --write でパックへ反映（roic/roicg/roicEx と _meta.basis/evidence/kenshi）
  引数なしなら退避→適用→score_all→**必ず元へ戻す**

値の作り方（night/README.md にも記す）:
  有利子負債はEDINET_DBがJGAAP中小型でnullを返す（実測: カナミックは実際676百万円の借入があるのに
  longTermLoans 306百万円しか出ない）。**ルール7により欠測をゼロと読めない**ので再採取しない。
  代わりに**パックのroic/roicgから投下資本を逆算する**——パックの値は審査官が原本から門式で出したものなので
      ICg = NOPAT_jp ÷ roicg,   IC = NOPAT_jp ÷ roic
  が恒等的に成り立つ。変換は IC_us = IC_jp − 無形(のれん除く) と税率の掛け替えだけで済み、負債に触れない。
  検算: 逆算した (ICg − IC) が EDINET ののれんと ICg比±0.32%以内で一致した社が 35社中34社
  （唯一外れる6857はパックが既に5年中央値だから＝想定どおり。TC済2社は5年系列から別途組み直す）。

無形(のれん除く)の求め方——**会計基準では決まらない。開示の行の作り方で決まる**:
  JGAAP  : 財務諸表等規則により 無形固定資産合計は**のれんを含む** → 無形(のれん除く) = intan − gw
           （3939: gw793,637+ソフトウェア663,560=1,457,197 vs intan1,457,274 で数値一致。3922/3692でも確認）
  IFRS   : 開示による。intan < gw なら**のれん別行**が数学的に確定 → intan をそのまま控除
           （3989/6532/7378）。そうでなければ原本を読む
           （**6857はIFRSだが連結BSが「のれん及び無形資産 84,250」の合算1行**＝のれん込み。
             注記12: のれん65,690/ソフトウェア5,760/企業結合で認識した無形資産12,523/その他277＝合計84,250）
"""
import json, os, sys, shutil, subprocess
from statistics import median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")

SRC = "EDINET_DB compare_companies（パックの審査年）＋原本検算"

# 単年パック: 変換後の (roic, roicg)。作り方は上の docstring。
SINGLE = {
 "2477": (15.6, 15.6), "3496": (29.5, 27.2), "3692": (27.9, 27.1), "3798": (17.7, 17.7),
 "3901": (23.0, 22.6), "3922": (28.2, 27.2), "3923": (52.7, 46.7), "3939": (28.7, 20.9),
 "3989": (27.1, 26.3), "4071": (28.8, 27.2), "4262": (17.2, 12.8), "4393": (22.9, 22.9),
 "4431": (27.8, 23.2), "4493": (20.2, 17.1), "5032": (52.5, 52.2), "5038": (33.9, 32.1),
 "5132": (28.9, 24.2), "5254": (25.8, 19.1), "5570": (16.4, 16.1), "5582": (7.8, 7.6),
 "6196": (21.8, 21.8), "6200": (36.4, 33.7), "6532": (36.2, 30.5), "6777": (25.0, 24.1),
 "6920": (42.0, 41.5), "7373": (33.9, 27.6), "7378": (41.0, 27.4), "8136": (32.1, 30.9),
 "9242": (15.5, 14.2), "9552": (47.2, 47.2), "9554": (21.7, 17.3), "9790": (15.4, 15.3),
}
# through-cycle済（パックのroicが5年中央値）は5年系列を規約ごと組み直した
TC = {"6857": (35.9, 28.1), "6146": (24.0, 24.0)}

# 当てない社と、その理由（_meta.nulls ではなく作業リストへ）
HOLD = {
 "3984": "EDINETに無形の開示が無く上限も定まらない（ルール7: 欠測をゼロと読まない）",
 "5139": "EDINETに無形の開示が無く上限も定まらない（ルール7: 欠測をゼロと読まない）",
 "7034": "実効税率が算出不能（純利益205百万円 vs 税引前4,955百万円）。Ω失格で判定圏外",
}

EV = {
 "6857": ("系列[2022-2026]の中央値。米国規約=NOPAT営利×(1−実効税率)／IC=自己資本+有利子負債−のれん−無形。"
          "無形は原本 注記12（FY2026有報 docID S100YKTA）で のれん65,690+ソフトウェア5,760+"
          "企業結合で認識した無形資産12,523+その他277＝合計84,250 と確定＝**連結BSの「のれん及び無形資産」は合算1行**。"
          "年別 roic 35.9/41.7/16.0/32.5/49.6 → 中央35.9、roicg 26.5/31.8/12.8/28.1/44.5 → 中央28.1"),
 "6146": ("系列[2022-2026]の中央値。のれん0・有利子負債0（総負債155,285＝流動154,458+固定826のみ）。"
          "年別 roic 22.9/24.0/22.8/25.8/24.0 → 中央24.0"),
}


def convert(write=False):
    changed = []
    for t, (rc, rg) in list(SINGLE.items()) + list(TC.items()):
        p = os.path.join(OUT, "%s_gate_pack.json" % t)
        d = json.load(open(p, encoding="utf-8"))
        old = (d.get("roic"), d.get("roicg"))
        d["roic"], d["roicg"], d["roicEx"] = rc, rg, rc
        if write:
            m = d.setdefault("_meta", {})
            b = m.setdefault("basis", {})
            b["roicConvention"] = "us-unified(v9.9.73)"
            ev = m.setdefault("evidence", {})
            note = EV.get(t) or (
                "米国規約へ統一（v9.9.73）。NOPAT=営業利益×(1−実効税率)／"
                "IC=自己資本+有利子負債−のれん−無形。投下資本は旧JP規約値からの逆算"
                "（ICg=NOPAT_jp÷roicg・IC=NOPAT_jp÷roic）で復元し、負債には触れていない。出典 " + SRC)
            for k in ("roic", "roicg"):
                ev[k] = (ev.get(k, "") + "｜**v9.9.73 米国規約へ統一**: " + note).lstrip("｜")
            m.setdefault("kenshi", [])
            if isinstance(m["kenshi"], str):
                m["kenshi"] = [m["kenshi"]]
            m["kenshi"].append(
                "2026-08-03 日本株の採点基準を米国株と統一（v9.9.73）: roic %s→%s / roicg %s→%s。"
                "固定税率0.70を実効税率へ、投下資本の控除にのれんだけでなく無形も加えた。" % (old[0], rc, old[1], rg))
        # 影の計測でも書き出す（呼び元が out/ を退避→復元する）
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        changed.append((t, old, (rc, rg)))
    return changed


def score():
    # A5是正後(2026-08-04)の前提: `--jp` は**部分実行**なので out/score_all.partial.json へ書く。
    #   正本 out/score_all.json には触れない（従来は --jp が正本を約40行の部分集合で潰していた）。
    r = subprocess.run(["node", os.path.join(ROOT, "night", "score_all.js"), "--jp"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("score_all.js 失敗")
    return {x["t"]: x for x in json.load(open(os.path.join(OUT, "score_all.partial.json"), encoding="utf-8"))}


def score_full():
    """復元後の正本を全件で書き直す（旗なし＝正本 out/score_all.json を更新する唯一の経路）"""
    r = subprocess.run(["node", os.path.join(ROOT, "night", "score_all.js")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("score_all.js（全件）失敗")


def main():
    write = "--write" in sys.argv
    force = "--force" in sys.argv
    # B18(2026-08-04): **適用済みガード**。この移行(v9.9.73)は一度きりなのに再実行可能なままで、
    #   再実行すると (a)roic/roicg が 2026-08-03 時点のハードコード値へ巻き戻る（以後の是正を消す）
    #   (b)kenshi に同じ移行記録が重複追記される。_meta.basis.roicConvention="us-unified" が
    #   既に付いている社が対象に居たら拒否する。意図的にやり直すなら --force。
    if write and not force:
        applied = []
        for t in list(SINGLE) + list(TC):
            p = os.path.join(OUT, "%s_gate_pack.json" % t)
            try:
                b = ((json.load(open(p, encoding="utf-8")).get("_meta") or {}).get("basis") or {})
            except Exception:
                continue
            if str(b.get("roicConvention", "")).startswith("us-unified"):
                applied.append(t)
        if applied:
            print("✗ --write を拒否: v9.9.73 の統一は**適用済み**（roicConvention=us-unified が "
                  "%d社: %s …）。\n  再実行すると roic が 2026-08-03 のハードコード値へ巻き戻り、"
                  "kenshi が重複追記される。\n  それでも意図的にやり直すなら --force を付けること。"
                  % (len(applied), " ".join(applied[:8])))
            return 1
    if write:
        convert(True)
        print("パックへ反映しました（%d社）。night/score_all.js で確認してください。" % (len(SINGLE) + len(TC)))
        for t, why in HOLD.items():
            print("  据置 %s: %s" % (t, why))
        return

    bak = os.path.join(ROOT, ".jp_us_bak")
    if os.path.exists(bak):
        shutil.rmtree(bak)
    shutil.copytree(OUT, bak)
    try:
        before = score()
        convert(False)
        after = score()
    finally:
        shutil.rmtree(OUT)
        shutil.copytree(bak, OUT)
        shutil.rmtree(bak)
        # 復元後は**全件（旗なし）**で正本 out/score_all.json を書き直す（2026-08-04・B18a）。
        #   従来ここも --jp で回しており、正本が日本株だけの部分集合に潰れたまま残っていた（A5）。
        score_full()

    print("%-6s %-16s %6s %6s %7s  %-8s %-8s" % ("T", "銘柄", "Ω前", "Ω後", "差", "四段前", "四段後"))
    mv = 0
    for t in sorted(before, key=lambda x: -before[x]["s"]):
        a, b = before[t], after[t]
        if abs(a["s"] - b["s"]) < 0.05 and a["buy"] == b["buy"]:
            continue
        mv += 1
        print("%-6s %-16s %6.1f %6.1f %+7.1f  %-8s %-8s" % (
            t, a["nm"][5:19], a["s"], b["s"], b["s"] - a["s"],
            "🟢" if a["buy"] else ("Ω%s" % ("75+" if a["s"] >= 75 else "-")),
            "🟢" if b["buy"] else ("Ω%s" % ("75+" if b["s"] >= 75 else "-"))))
    print("\nΩが動いた %d社 / 投下可 %d社 → %d社" % (
        mv, sum(1 for x in before.values() if x["buy"]), sum(1 for x in after.values() if x["buy"])))
    for lab, st in (("前", before), ("後", after)):
        print("  %s: Ω75+ %d社 / 堀70+かつΩ75+ %d社 / 投下可 %s" % (
            lab, sum(1 for x in st.values() if x["s"] >= 75),
            sum(1 for x in st.values() if x["s"] >= 75 and x["moatOK"]),
            " ".join(sorted(x["t"] for x in st.values() if x["buy"]))))


if __name__ == "__main__":
    sys.exit(main())   # B18: 適用済みガードの拒否(return 1)を終了コードに乗せる（黙って0を返さない）
