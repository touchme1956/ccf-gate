#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_intcov.py — 利払カバー（財務キルの第二の物差し）をパックへ充填する（2026-08-13新設）

■ なぜ要るか
  v9.9.142（ユーザー明示指示「入れて」）で財務キルが **nde>4 または 利払カバー<3** の OR になった。
  利払カバーは `night/v11_facts.py` が SEC XBRL から作るが、**パックの欄として流さないと
  compute() のキルが読めない**（外部JSONは関門にしかなれない——compute() は DOM しか見ない）。
  この器は v11_facts の答えを**そのままパックへ写すだけ**で、利息の採り方を再実装しない（v9.9.65）。

■ ⚠ 真正の利息だけを使う（`intcov_strict`）
  `intcov`（混合基準）を使ってはいけない——IFRSの `FinanceCosts` は支払利息 **＋ 為替差損・
  リース利息・引当の割引** の上位概念で、これで作ると**純現金の会社が利払カバー3未満に見える**
  （実測8社: AFYA/TIGO/TIMB/BUD/AXIA/ASAIY/CEPU/AMBIQ＝中南米の高金利・通貨安に集中）。
  歴史側 `retro_features2.py` の候補にも FinanceCosts は無く、**strict が歴史と揃う基準**。

■ ⚠ 空欄は「安全」ではない
  被覆は **184/369（日本株は SEC 経路の外で 68社すべて空欄）**。空欄ではキルが眠るので
  **未測定が有利**になる。この非対称は消せないが、**穴は night/audit_intcov.py が名前で出し続ける**。
  だから「追加」であって「交換」ではない——追加なら被覆が薄くても絶対に緩くならない。

使い方: python3 night/fill_intcov.py [--write] [--only T,T]
出力なし（--write でパックの `intcov` と `_meta.evidence.intcov` を書く）
"""
import glob
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
TODAY = time.strftime("%Y-%m-%d")


def main():
    write = "--write" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = {x.upper() for x in sys.argv[sys.argv.index("--only") + 1].split(",")}

    p = os.path.join(BASE, "out", "v11_facts.json")
    if not os.path.exists(p):
        sys.exit("out/v11_facts.json が無い（先に python3 night/v11_facts.py）")
    facts = json.load(open(p, encoding="utf-8")).get("items") or {}
    # ★空書き込みの検問（audit_stale_bs:243 と同じ言葉）。採取が壊れた日に
    #   **全パックの intcov を消す**のを、人の注意力ではなく機構で防ぐ。
    have = sum(1 for v in facts.values() if v.get("intcov_strict") is not None)
    if have == 0:
        sys.exit("✗ v11_facts に intcov_strict が1社も無い＝採取が壊れている。何も書かずに中止")

    n_w = n_same = n_blank = n_jp = 0
    changed = []
    for pk in sorted(glob.glob(os.path.join(BASE, "out", "*_gate_pack.json"))):
        t = os.path.basename(pk).replace("_gate_pack.json", "")
        if only and t.upper() not in only:
            continue
        r = facts.get(t) or {}
        v = r.get("intcov_strict")
        if v is None:
            n_blank += 1
            if t[:4].isdigit():
                n_jp += 1
            continue
        d = json.load(open(pk, encoding="utf-8"))
        tag = r.get("int_strict_tag") or r.get("int_tag")
        fy = r.get("int_strict_fy") or r.get("int_fy")
        per = r.get("int_strict_period") or "annual"
        ev = (f"機械算出 {fy}年: 営業利益 ÷ 支払利息 = {v}。利息タグ {tag}"
              f"（基準=**真正の利息**。IFRSの FinanceCosts・受取利息と相殺した純額・"
              f"債務消滅損を含む上位概念は使わない）"
              f"{'・四半期4本を合算' if per == 'quarters_sum' else ''}。"
              f"night/v11_facts.py の intcov_strict")
        old = d.get("intcov")
        if old == v and (d.get("_meta", {}).get("evidence", {}) or {}).get("intcov") == ev:
            n_same += 1
            continue
        if old is not None and old != v:
            changed.append((t, old, v))
        if write:
            m = d.setdefault("_meta", {})
            m.setdefault("evidence", {})["intcov"] = ev
            d["intcov"] = v
            json.dump(d, open(pk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n_w += 1

    print(f"■ 利払カバーの充填  書き{'込み' if write else '込み予定'} {n_w}社 / 変化なし {n_same}"
          f" / 空欄のまま {n_blank}（うち日本株 {n_jp}＝SEC経路の外の構造的な穴）")
    if changed:
        print(f"  ⚠既存の値が変わる {len(changed)}社（採取器の年が進んだ等・原因を確かめること）:")
        for t, o, v in changed[:15]:
            print(f"     {t:<7} {o} → {v}")
    if not write:
        print("  ※ --write で反映")
    return 0


if __name__ == "__main__":
    sys.exit(main())
