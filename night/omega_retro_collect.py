#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro_collect.py — 歴史のビンテージで**門式の**機械値を採る（2026-08-14新設）

■ なぜ新しく採るのか（★ここが肝。踏みかけた事故の記録）
  「歴史の在庫に roic があるから使えばよい」——**これが間違いだった**。
  `gate0_v8_5.evaluate()` の roic は

      roic = 営業利益 × 0.79 ÷ (自己資本 + 有利子負債)

  で、これは**門の `roicg`**（のれん込み・しかも実効税率でなく固定0.79）である。
  門の `roic` は 絶対のルール7-b により

      roic = 営業利益 × (1−実効税率) ÷ (自己資本 + 有利子負債 − のれん − 無形)

  ＝**別の指標**。`retro_cohort` の `roic_med5` を Ω̂ の `roic` 欄へ流し込めば、
  「基準の違う二つを割る」型をこの台帳で10例目として自分で作ることになる。
  しかも**もっともらしい値が出る**ので、気づかない。

■ どう採るか——**門の採取器をそのまま呼ぶ**（v9.9.65: 再実装しない）
  `hachimon_fetch.build_numbers(facts)` は facts 辞書を受け取るので、
  **companyfacts を `filed <= 締切` で切ってから渡す**だけでよい。こうすると
  税タグ欠測・有利子負債欠測・無形の構成要素合成・IC縮退・債務超過の物差し——
  門が積み上げてきたガードが**全部そのまま効く**。基準は構造的に一致する。

■ look-ahead を構造で防ぐ
  締切は `{ビンテージ}-07-01`（既存の retro_* と同じ）。**決算期末ではなく提出日(filed)で切る**
  ——12月決算社の FY2013 は 2013-07 時点で未公表だから（2026-08-05 に確立した作法）。

使い方: python3 night/omega_retro_collect.py [--limit N] [--only T,T]
出力: out/omega_retro_machine_{2013,2015}.json
"""
import json
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
OUT = os.path.join(BASE, "out")

import hachimon_fetch as H  # noqa: E402  ——門の採取器そのもの

VINTAGES = {
    2013: dict(pil="out/retro_moat_pillars_2013.json",
               irr=["out/retro_moat_2013.json", "out/retro_moat_2013q.json"],
               coh="out/retro_cohort_2013.json"),
    2015: dict(pil="out/retro_moat_pillars_2015.json",
               irr=["out/retro_moat_2015.json", "out/retro_moat_2015q.json",
                    "out/retro_moat_2015qb.json"],
               coh="out/retro_cohort_2015.json"),
}


def load(f):
    d = json.load(open(f, encoding="utf-8"))
    r = d.get("items") or d.get("rows") or d
    return list(r.values()) if isinstance(r, dict) else r


def key(x):
    return x.get("ticker") or x.get("t")


def cut(facts, deadline):
    """companyfacts を filed<=deadline で切る。**当時読めた数字だけ**にする。
    ⚠ 空になった単位・タグは落とす——残すと series() が「タグはあるが年が無い」を
      別の意味で扱いうるため（欠測をゼロと読まない、の親戚）。"""
    root = facts.get("facts") or {}
    out_ns = {}
    for ns, tags in root.items():
        keep_tags = {}
        for tag, node in tags.items():
            units = {}
            for u, arr in (node.get("units") or {}).items():
                k = [e for e in arr if e.get("filed") and e["filed"] <= deadline]
                if k:
                    units[u] = k
            if units:
                keep_tags[tag] = dict(node, units=units)
        if keep_tags:
            out_ns[ns] = keep_tags
    return dict(facts, facts=out_ns)


def main():
    only = None
    if "--only" in sys.argv:
        only = {x.upper() for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    zp = os.path.join(BASE, "companyfacts.zip")
    if not os.path.exists(zp):
        sys.exit("companyfacts.zip が無い（.gitignore 済み。SECから取り直す）")
    z = zipfile.ZipFile(zp)

    for yr, v in VINTAGES.items():
        deadline = f"{yr}-07-01"
        P = {key(x): x for x in load(v["pil"])}
        irr = set()
        for f in v["irr"]:
            for x in load(f):
                if x.get("irr") is not None:
                    irr.add(key(x))
        C = {key(x): x for x in load(v["coh"])}
        # 対象＝堀4本以上（門の下限）そろう社
        want = [t for t in P if t in irr
                and sum(1 for k in ("dom", "rep", "dur", "moatW")
                        if P[t].get(k) is not None) >= 3]
        if only:
            want = [t for t in want if t in only]
        if limit:
            want = want[:limit]
        cik = {t: C[t]["cik"] for t in want if C.get(t, {}).get("cik")}
        print(f"■ {yr}: 対象 {len(want)}社（CIK解決 {len(cik)}社・締切 filed<={deadline}）")

        rows, ng = {}, {}
        for i, (t, ck) in enumerate(sorted(cik.items()), 1):
            name = f"CIK{int(ck):010d}.json"
            try:
                facts = json.loads(z.read(name))
            except KeyError:
                ng[t] = "companyfacts に無い"
                continue
            try:
                ev = H.build_numbers(cut(facts, deadline))
            except Exception as e:
                ng[t] = f"build_numbers 例外: {type(e).__name__}"
                continue
            # ★門の採取器が返す欄だけを採る。**ここで計算しない**（再実装しない）
            rows[t] = {k: ev.get(k) for k in
                       ("roic", "roicg", "roicEx", "nde", "roiic", "roiic5", "gm", "cagr",
                        "accr", "fcf", "ni", "dilNet", "sbc", "z", "gpa", "intcov",
                        "eq", "acc")}
            rows[t]["_fy"] = ev.get("reportDate") or ev.get("fy")
            # ★案A(2026-08-14): p1(ROIC変動係数) と p2(不況時の営利DD) を機械で出すための系列。
            #   ここでは**保存するだけ**——刻みを当てるのは build 側（採取と判定を混ぜない）。
            rows[t]["tc"] = ev.get("_tcSeries")          # {年: [roic, roicg]} ＝ p1 の材料
            try:                                          # 営業利益の年次系列 ＝ p2 の材料
                rows[t]["op"] = H.series(cut(facts, deadline), H.TAGS["op"])[0] or None
            except Exception:
                rows[t]["op"] = None
            if i % 25 == 0:
                print(f"   {i}/{len(cik)} …")
        # ★部分実行は .partial へ（2026-08-14・**同じ日に3度目**）。v11_facts / backfill と同じ構造で塞ぐ。
        #   正本を数社で上書きすると、それを読む build/test がその数社を全母集団と誤認して静かに嘘をつく。
        part = bool(only or limit)
        p = os.path.join(OUT, f"omega_retro_machine_{yr}{'.partial' if part else ''}.json")
        json.dump({"generated": __import__("time").strftime("%Y-%m-%d"),
                   "vintage": yr, "deadline": deadline,
                   "note": "門の hachimon_fetch.build_numbers を filed<=締切 で切った facts に当てたもの"
                           "＝基準は門式と構造的に一致（gate0 の roic は門の roicg なので使わない）",
                   "n": len(rows), "items": rows, "failed": ng},
                  open(p, "w"), ensure_ascii=False, indent=1)
        got = sum(1 for r in rows.values() if r.get("roic") is not None)
        print(f"   → {p}  採れた {len(rows)}社（roic あり {got}社 / 失敗 {len(ng)}社）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
