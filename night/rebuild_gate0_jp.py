#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rebuild_gate0_jp.py — 日本株門0の一次ふるいから roic を外し、キューを二枠で組み直す
                            （2026-08-03・ユーザー明示指示）

■ なぜ変えるか（穴は二層あった）

【第一層】一次ふるいの `roic>=15` が、手元流動性の厚い日本の優良企業をまるごと弾いていた。
  JP ROIC規約(2026-07-28)は**過剰現金を控除しない**（「貯めるほど点が上がる」旧式の逆走を止める
  ための意図的な保守選択）。だが**採点での減点とふるいでの除外は別物**——後者は候補から永久に消える。
  実測 キーエンス(6861): 営業利益率51.0% / 自己資本比率94.6% / cagr3y 8.2% なのに
  roic = NOPAT 0.417兆 ÷ 自己資本 3.414兆 = **12.2%** で脱落（現金0.45兆+短期有価証券0.90兆+
  投資有価証券1.51兆＝**約2.9兆円が丸ごと分母に残る**。事業資産ベースなら20%前後）。
  同じ理由で オリエンタルランド・ネクソン・塩野義製薬・マニー・日産化学・東京応化工業 等 計65社が消えていた。

  → **ふるいから roic を外す**。これは pt から roic を外した(2026-07-29)のと**同じ証拠・同じ理由**:
    審査済み36社で生ROICは審査後と中央値5.01倍・最大204倍ずれ、7034は符号まで逆だった。
    採点で使えない指標を、選別ではもっと強い形（永久除外）で使い続ける理由は無い。
    roic は審査時に門式で算出する。

【第二層——実測して判った】**roic を外すだけでは問題は解けない**。
  合流後265社を pt降順で上位50を取ると、救済分から入るのは **メタプラネット(pt41.5・cagr189.8%)** と
  **インテグラル(pt40.8・PE)** の2社だけで、**キーエンスは入らない**（pt31.5 対 50位の40.7）。
  原因は pt の重み——`pt = 0.4615*min(cagr,30) + 0.3846*min(opm,40) + 0.1538*min(eq,80)` で
  **cagr が最大の重み**を持つため、成熟した高収益企業は構造的に沈む:
      キーエンス   pt31.5 = cagr 3.8 + opm 15.4 + eq 12.3   （cagr 8.2% が効かない）
      オリエンタルランド pt25.8 = cagr 6.2 + opm  9.2 + eq 10.4   （cagr 13.4% が効かない）
      日産化学     pt23.2 = cagr 3.2 + opm  8.7 + eq 11.2   （cagr 7.0% が効かない）
  pt の上位は小型の新規上場（3年成長が小さい母数から測られる社）で埋まる。
  **20-30年の複利を探しているのに、選別が「直近3年の成長率」に支配されている**。

  → **キューを二枠にする**: `pt上位50 ∪ 質の椅子`。
    これは新発明ではなく**米国門0とまったく同じ形**（gate1_queue = TOP_N100 ＋
    審査優先〔谷/種まき/未成熟〕の合流で約155社）。数字で上位に来ない群を別枠で救うのが門の作法。

■ 質の椅子の定義と較正（opm>=35 かつ eq>=75 かつ cagr>=5）
  「高収益 × 厚い自己資本」＝ pt では拾えないが構造的に見るべき社。実測で15社を拾い、その中に:
    **6146 ディスコ**（＝日本株で唯一 四関門を通った社）／キーエンス／カプコン／オービック／
    オービックビジネスコンサルタント／USS／ジャストシステム／日本M&Aセンター／イー・ギャランティ
  **既に門を通り抜けた唯一の日本株を拾う線**であることが、この閾値の妥当性の実測的な裏付け。
  線を緩めると(opm>=30) 22社、締めると(opm>=40 & eq>=80) 6社。35/75 は「拾うべき社を拾い、
  かつ審査枠を食い潰さない」帯として選んだ。

■ cagr のアーティファクトは**除外せず印を付ける**（cagr_artifact）
  cagr3y > 100% は事業の成長ではなく、上場直後の期間比較・資産評価益・基準変更のアーティファクト
  （実測: メタプラネット 189.8%〔ビットコイン財務〕/ サイバーソリューションズ 1229.6% / グロービング 170.4%）。
  だが**ふるいの条件を増やすのはユーザー明示指示の領分**なので、ここでは roic_artifact と同じく
  **印だけ付けて審査官へ渡す**（キューは審査待ちであって合格ではない。門2が裁く）。

使い方:
  python3 night/rebuild_gate0_jp.py            判定だけ表示（書き換えない）
  python3 night/rebuild_gate0_jp.py --write    gate0_jp_queue.json / gate0_jp_all.csv を書き換える
                                               （旧ファイルは .prev へ退避）
"""
import csv
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 一次ふるい（roic を外した）。門0-JPの選別基準＝変更にはユーザー明示指示が要る
SIEVE = dict(opm=15.0, cagr=5.0, eq=50.0)
TOP_N = 50                                  # pt枠
CHAIR = dict(opm=35.0, eq=75.0, cagr=5.0)   # 質の椅子（上の頭注で較正の実測を示した）
CAGR_ARTIFACT = 100.0                       # 印を付けるだけ・ふるいではない


def pt_of(cagr, opm, eq):
    """2026-07-29でroicを外した現行式。ここは唯一の実装（rerank_gate0_jp.py と同値）"""
    return round(0.4615 * min(cagr, 30) + 0.3846 * min(opm, 40) + 0.1538 * min(eq, 80), 2)


def load():
    """roic>=15 を通った母集団(CSV・pt上位200) と、roic<15 で落ちていた救済分(65社) を合流する"""
    rows = []
    with open(os.path.join(BASE, "gate0_jp_all.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "sec": r["sec"], "edinet": r.get("edinet"), "nm": r["nm"], "ind": r["ind"],
                "acc": r.get("acc"), "opm": float(r["opm"]), "cagr": float(r["cagr"]),
                "eq": float(r["eq"]), "roic_raw": float(r["roic"]),
                "roic_artifact": r["roic_artifact"] == "True", "src": "roic>=15",
            })
    miss = json.load(open(os.path.join(BASE, "gate0_jp_netcash_miss.json"), encoding="utf-8"))["list"]
    have = {r["sec"] for r in rows}
    for x in miss:
        if x["sec"] in have:
            continue
        rows.append({
            "sec": x["sec"], "edinet": None, "nm": x["nm"], "ind": x["ind"], "acc": x.get("acc"),
            "opm": float(x["opm"]), "cagr": float(x["cagr"]), "eq": float(x["eq"]),
            # 絶対のルール7: 「取れなかった」と「0」を区別する。救済分はroicを持たない＝null
            "roic_raw": None, "roic_artifact": None, "src": "roic<15(救済)",
        })
    for r in rows:
        r["pt"] = pt_of(r["cagr"], r["opm"], r["eq"])
        r["cagr_artifact"] = r["cagr"] > CAGR_ARTIFACT
    return rows


def main():
    write = "--write" in sys.argv
    rows = load()
    kept = [r for r in rows
            if r["opm"] >= SIEVE["opm"] and r["cagr"] >= SIEVE["cagr"] and r["eq"] >= SIEVE["eq"]]
    kept.sort(key=lambda r: -r["pt"])

    top = kept[:TOP_N]
    intop = {r["sec"] for r in top}
    chair = [r for r in kept if r["sec"] not in intop
             and r["opm"] >= CHAIR["opm"] and r["eq"] >= CHAIR["eq"] and r["cagr"] >= CHAIR["cagr"]]
    chair.sort(key=lambda r: -r["pt"])
    for r in top:
        r["lane"] = "pt"
    for r in chair:
        r["lane"] = "質の椅子"
    queue = top + chair

    print(f"母集団 {len(rows)}社（roic>=15の上位200 + roic<15の救済65）→ ふるい通過 {len(kept)}社")
    print(f"  ふるい: opm>={SIEVE['opm']:.0f} & cagr3y>={SIEVE['cagr']:.0f} & equity>={SIEVE['eq']:.0f}"
          f"（**roic条件は撤廃**）")
    print(f"キュー {len(queue)}社 ＝ pt上位{len(top)} ∪ 質の椅子{len(chair)}"
          f"（opm>={CHAIR['opm']:.0f} & eq>={CHAIR['eq']:.0f} & cagr>={CHAIR['cagr']:.0f}）")
    resc = [r for r in queue if r["src"].startswith("roic<15")]
    print(f"  うち今回の救済分が {len(resc)}社: {' '.join(r['sec'] + r['nm'][:8] for r in resc)}")
    art = [r for r in queue if r["cagr_artifact"]]
    print(f"  ⚠cagr_artifact（cagr3y>{CAGR_ARTIFACT:.0f}%＝事業成長でない疑い・**除外はせず印のみ**）: "
          f"{len(art)}社 {' '.join(r['sec'] for r in art)}")
    print(f"\n質の椅子 {len(chair)}社:")
    for r in chair:
        print(f"  pt{r['pt']:5.1f} {r['sec']:5s} {r['nm'][:22]:24s} opm{r['opm']:5.1f} "
              f"cagr{r['cagr']:6.1f} eq{r['eq']:5.1f}  [{r['src']}]")

    if not write:
        print("\n※--write で gate0_jp_queue.json / gate0_jp_all.csv を書き換える（旧は .prev へ退避）")
        return 0

    for fn in ("gate0_jp_queue.json", "gate0_jp_all.csv"):
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            shutil.copy(p, p + ".prev")
    out = {
        # ⚠2026-08-10: **日付がハードコードされていた**——再実行しても去年の日付を名乗るので、
        #   回転盤(ops_status)の gate0jp が**永久に緑で固定される**（止まっても検出できない）。
        #   これは「回っているつもりで止まっている」の最悪の形なので実行日にした。
        "generated": __import__("datetime").date.today().isoformat(),
        "source": "EDINET_DB screen_companies（roic>=15版CSV上位200）+ gate0_jp_netcash_miss.json（roic<15の救済65）",
        "filter": f"opm>={SIEVE['opm']:.0f} & cagr3y>={SIEVE['cagr']:.0f} & equity>={SIEVE['eq']:.0f}"
                  f"（**roic条件は2026-08-03のユーザー明示指示で撤廃**）",
        "total_passed": len(kept),
        "lanes": {"pt": len(top), "質の椅子": len(chair)},
        "note": (
            "門0-JP定量ふるい(1次)。**穴は二層あった**——(1)一次ふるいの roic>=15 が、過剰現金を控除しない"
            "JP ROIC規約のせいで手元流動性の厚い優良企業を永久除外していた（キーエンス roic12.2%で脱落。"
            "現金+有価証券 約2.9兆円が丸ごと分母に残る）。ptからroicを外したのと同じ証拠・同じ理由で撤廃した。"
            "(2)だが roic を外しても解けない——pt は cagr の重みが最大(0.4615)なので成熟した高収益企業は"
            "構造的に沈み、キーエンスは pt31.5 で50位の40.7に届かない。救済分から上位50に入るのは"
            "メタプラネット(cagr189.8%・ビットコイン財務)とインテグラル(PE)だけだった。"
            "→ **キューを二枠にした**: pt上位50 ∪ 質の椅子(opm>=35 & eq>=75 & cagr>=5)。"
            "米国門0の『TOP_N100＋審査優先』とまったく同じ形。質の椅子は**ディスコ(6146)＝日本株で唯一"
            "四関門を通った社**を拾う線で、それが閾値の妥当性の実測的な裏付け。"
            "cagr3y>100%は事業成長でないアーティファクトだが、ふるいの条件追加は明示指示の領分ゆえ"
            "**除外せず cagr_artifact の印だけ付けて審査官へ渡す**（キューは審査待ちであって合格ではない）。"
            "pt=0.4615*min(cagr,30)+0.3846*min(opm,40)+0.1538*min(eq,80)。"
            "roic は審査時に門式(NOPAT÷(有利子負債+自己資本−のれん)・現金非控除・60%上限)で算出する。"
            "定性(p/f・堀)は門2審査で評価。旧キューは gate0_jp_queue.json.prev"
        ),
        "queue": [{
            "sec": r["sec"], "edinet": r["edinet"], "nm": r["nm"], "ind": r["ind"],
            "opm": r["opm"], "cagr": r["cagr"], "eq": r["eq"],
            "roic_raw": r["roic_raw"], "roic_artifact": r["roic_artifact"],
            "cagr_artifact": r["cagr_artifact"], "pt": r["pt"], "lane": r["lane"],
        } for r in queue],
    }
    json.dump(out, open(os.path.join(BASE, "gate0_jp_queue.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(os.path.join(BASE, "gate0_jp_all.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sec", "edinet", "nm", "ind", "acc", "roic", "opm", "cagr", "eq", "pt",
                    "roic_artifact", "cagr_artifact", "src"])
        for r in kept:
            w.writerow([r["sec"], r["edinet"] or "", r["nm"], r["ind"], r["acc"] or "",
                        "" if r["roic_raw"] is None else r["roic_raw"], r["opm"], r["cagr"],
                        r["eq"], r["pt"],
                        "" if r["roic_artifact"] is None else r["roic_artifact"],
                        r["cagr_artifact"], r["src"]])
    print(f"\n→ gate0_jp_queue.json（{len(queue)}社）/ gate0_jp_all.csv（{len(kept)}社・全通過分）")
    print("  ※旧ファイルは .prev へ退避した。次は night/make_chunks.py で審査チャンクを生成する")
    return 0


if __name__ == "__main__":
    sys.exit(main())
