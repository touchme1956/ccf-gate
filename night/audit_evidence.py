#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_evidence.py — 「値は入っているが根拠が無い」項目を全パックで数える（2026-07-29新設）

なぜ要るか（2026-07-29 に是正が続いた理由そのもの）:
  この日だけで NJR(roic 16.5→6.6, p2 90→40)・9790(p2 95→40)・UI(roic 136.6→80.7)・
  SSD/ISRG/INTU/VEEV/WDFC/TJX/ALLE の dom・KLAC等11社の市場値、と是正が続いた。
  一件ずつは別の原因に見えるが、**共通しているのは「入力時に根拠を要求していなかった」こと**だけ。
  台帳の中で、原本から測った値と、それらしく置いた値は**見た目が完全に同じ**になる。
  だから誤りは静かに溜まり、**人が根拠を1件ずつ読むまで見つからない**。

  初回実測（全316パック・値が入っている採点項目 7138 個）:
      _meta.evidence に根拠があるのは **2414 個 = 33.8%**
      moatW  100.0%   ← 規約(v9.9.36)が出来てから作られた項目。最初から根拠必須だった
      dom     63.4% / dur 58.2% / p4 58.9% / irr・rep 57.3% / p2 54.1%
      roic    16.2% / shy 10.4% / nde 7.3% / roicg 6.2% / gm 4.8% / fcf 2.8%
      accr     1.6% / cagr 1.0% / ni 0.3%
  **機械が出した項目ほど根拠が無い。**「機械の出力だから正しい」という前提が置かれていたため。
  絶対のルール7で潰したバグは、まさにその前提が外れる場所にあった。

この検査器がやること／やらないこと:
  ・やる: 項目ごとの根拠被覆率と、**買付に効く帯（Ω75+）で根拠を欠く項目**の作業リスト
  ・やらない: 値の正否の判定。根拠が無い＝誤り、ではない（正しく測ったが書き忘れた場合もある）。
    audit_moat / audit_roic と同じく、**出力は作業リストであって有罪判決ではない**。
  ・null は数えない。「測っていない」と正しく宣言された欄は健全（v9.9.39 の再正規化で採点から外れる）。
    ただし null の理由が _meta.nulls に無いものは別枠で数える（宣言なき空欄＝理由が失われている）。

使い方:
  python3 night/audit_evidence.py            全パックの被覆率
  python3 night/audit_evidence.py --q75      Ω75+ だけ（out/score_all.json が要る）
  python3 night/audit_evidence.py --list     根拠を欠く項目を持つコード列だけ
  python3 night/audit_evidence.py --t NVDA   1社の明細
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# 判断項目＝審査官が原本を読んで置く。憶測が最も入りやすいので根拠は必須（絶対のルール2）
JUDGE = ["dom", "moatW", "irr", "rep", "dur", "p1", "p2", "p3", "p4",
         "f1", "f2", "f3", "f4", "f5", "erosion", "disrupt", "moatdecay",
         "expiry", "geopol", "founder", "idx"]
# 機械項目＝採取器が算出する。「機械だから正しい」が誤りだったので、こちらも出典が要る
MACHINE = ["roic", "roicg", "roicEx", "gm", "cagr", "nde", "fcf", "ni",
           "accr", "gpa", "z", "sbc", "dilNet", "acq5", "eps", "nrr"]
# 市場項目＝外部APIで日々動く。根拠は「いつ・どこから」で足りる
MARKET = ["per", "perF", "px", "shy", "evebit", "beta", "analysts", "instOwn"]

# evidence のキー名がフィールド名と一致しない箇所（既存パックの表記ゆれ）
ALIAS = {"per": ["px_per", "per"], "px": ["px_per", "px"], "perF": ["px_per", "perF"],
         "roicg": ["roic", "roicg"], "roicEx": ["roic", "roicEx"],
         "roict": ["roic", "roict"], "nde": ["nde", "roic"]}


def has_val(v):
    """値が入っているか。null・空文字・'na' は「測っていない」＝健全なので数えない。"""
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip().lower()
        return s not in ("", "na", "n/a", "-", "—", "null")
    return True


def has_ev(ev, k):
    for key in ALIAS.get(k, [k]):
        t = ev.get(key)
        if isinstance(t, str) and t.strip():
            return True
        if isinstance(t, (dict, list)) and t:
            return True
    return False


def load_packs():
    rows = []
    for f in sorted(os.listdir(OUT)):
        if not f.endswith("_gate_pack.json"):
            continue
        try:
            d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
        except Exception:
            continue
        rows.append((f.split("_gate_pack")[0], d))
    return rows


def omega():
    try:
        rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
    except Exception:
        return None
    return {r["t"]: (r.get("s") or 0) for r in rows}


def main():
    only_list = "--list" in sys.argv
    q75 = "--q75" in sys.argv
    one = None
    if "--t" in sys.argv:
        i = sys.argv.index("--t")
        if i + 1 < len(sys.argv):
            one = sys.argv[i + 1].upper()

    packs = load_packs()
    om = omega()
    if q75:
        if om is None:
            print("out/score_all.json が無い。先に `node night/score_all.js`")
            return 1
        packs = [(t, d) for t, d in packs if om.get(t, 0) >= 75]
    if one:
        packs = [(t, d) for t, d in packs if t.upper() == one]
        if not packs:
            print(f"{one} のパックが無い")
            return 1

    groups = [("判断", JUDGE), ("機械", MACHINE), ("市場", MARKET)]
    stat = {k: [0, 0] for _, g in groups for k in g}   # [根拠あり, 値あり]
    gaps = {}                                          # コード -> 根拠を欠く項目
    undoc_null = {}                                    # コード -> 理由なき空欄

    for t, d in packs:
        meta = d.get("_meta") or {}
        ev = meta.get("evidence") or {}
        nl = meta.get("nulls") or {}
        miss, un = [], []
        for _, g in groups:
            for k in g:
                if has_val(d.get(k)):
                    stat[k][1] += 1
                    if has_ev(ev, k):
                        stat[k][0] += 1
                    else:
                        miss.append(k)
                elif k in d and k in JUDGE and not nl.get(k):
                    un.append(k)
        if miss:
            gaps[t] = miss
        if un:
            undoc_null[t] = un

    if only_list:
        print(" ".join(sorted(gaps)))
        return 0

    if one:
        t, d = packs[0]
        print(f"=== {t} {(d.get('nm') or '')} "
              f"{'Ω' + format(om.get(t, 0), '.1f') if om else ''}")
        print(f"  根拠を欠く値: {' '.join(gaps.get(t, [])) or '(なし)'}")
        print(f"  理由なき空欄: {' '.join(undoc_null.get(t, [])) or '(なし)'}")
        return 0

    tot_ev = sum(v[0] for v in stat.values())
    tot_va = sum(v[1] for v in stat.values())
    scope = f"Ω75+ {len(packs)}社" if q75 else f"全{len(packs)}社"
    print(f"■ {scope} — 値が入っている採点項目 {tot_va} 個のうち、"
          f"_meta.evidence に根拠があるのは {tot_ev} 個 = "
          f"{(100.0 * tot_ev / tot_va) if tot_va else 0:.1f}%\n")
    for name, g in groups:
        sub_e = sum(stat[k][0] for k in g)
        sub_v = sum(stat[k][1] for k in g)
        print(f"【{name}項目】 {sub_e}/{sub_v} = "
              f"{(100.0 * sub_e / sub_v) if sub_v else 0:.1f}%")
        for k in g:
            e, v = stat[k]
            if not v:
                continue
            print(f"    {k:9s} {e:4d}/{v:4d} = {100.0 * e / v:5.1f}%")
        print()

    print(f"根拠を欠く値を持つ社: {len(gaps)}/{len(packs)}")
    if undoc_null:
        print(f"判断項目が空欄なのに _meta.nulls に理由が無い社: {len(undoc_null)}"
              f"（空欄自体は健全。理由が失われているのが問題）")
    print("\n※根拠が無い＝誤り、ではない。正しく測って書き忘れた場合もある。"
          "\n  これは再監査の作業リストであって、有罪判決ではない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
