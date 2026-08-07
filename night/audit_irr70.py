#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_irr70.py — **irr=70 の根拠が「移行の摩擦」を実証しているか**（2026-08-07新設）

なぜ要るか（2026-08-07の実測で判った検査の非対称）:
  2026-08-06 の全数検算は **irr==85 だけ**を対象にし、53社→11社へ削った。
  70 と 50 は**一度も同じ厳格さで検査されていない**。ところが決定に効いているのは 70 のほうだった:

    ・irr=85 を全部 70 に落としても **投下可は0社しか動かない**（`night/shadow_irr85.py`）
    ・判定圏の irr=70 を 50 に落とすと **45社中19社が堀の関門70を割り、投下可10社中6社が落ちる**
      （6857 / HWM / IDXX / IRMD / KLAC / RMD）

  そして歴史側では 70↔50 の差のほうが**母集団が桁違いに大きい**:
    プール754件の P(継続): 50:**0.162** < 70:**0.366** < 85:0.579（ベース0.204）
    ＝ 70は50の **2.3倍**（85は70の1.6倍）。しかも該当社数は 70:209社 / 50:123社 に対し 85:12社。

  **つまり「85かどうか」より「70か50か」のほうが、この台帳の買付を実際に決めている。**

この道具がすること:
  irr=70 の社の `_meta.evidence.irr` を読み、**移行の摩擦を名指ししているか**を機械で仕分ける。
    A 摩擦の機構を名指し … 切替コスト・データ移行・工程組込・長期契約・設置基盤 等の具体語がある
    B 認定・認証の語だけ  … 85の試験で落とした型（自社が取得する側／向きが逆）の残りかもしれない
    C 一般的な競争記述だけ … 『highly competitive』『barriers to entry』等で摩擦の実体が無い＝50の疑い
    D 根拠なし

  **これは原本の判定ではなく triage（読む順を決める道具）**。evidence の文言を見ているだけなので、
  A に分類されても原本が支えているとは限らないし、C でも原本には記述があるかもしれない。
  audit_irr85.py が 85 に対してやったことの 70 版で、**次に原本を読む先を絞る**のが目的。

使い方:
  python3 night/audit_irr70.py            判定圏(Ω72+)だけ
  python3 night/audit_irr70.py --all      全362社
  python3 night/audit_irr70.py --buy      投下可だけ
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
ALL = "--all" in sys.argv[1:]
BUYONLY = "--buy" in sys.argv[1:]
BAND = 72

# 摩擦の機構を名指しする語（70を支える側）
FRICTION = [
    "switch", "スイッチ", "切替", "切り替え", "migrat", "移行", "乗り換え", "乗換",
    "installed base", "設置基盤", "導入基盤", "integrat", "組込", "組み込", "統合",
    "long-term contract", "長期契約", "multi-year", "複数年", "retrain", "再教育", "習熟",
    "data", "データ移行", "workflow", "ワークフロー", "embedded", "sole source", "単独指定",
    "disrupt their", "costly", "time-consuming", "解約率", "churn", "retention", "更新率",
]
# 認定・認証の語（85の試験で落とした型が残っていないか）
CERT = ["qualif", "certif", "認定", "認証", "承認", "approval", "validation", "バリデーション"]
# 摩擦の実体が無い一般的な競争記述（50の疑い）
GENERIC = ["highly competitive", "barriers to entry", "competitive market", "激しい競争",
           "many competitors", "fragmented", "price competition", "価格競争"]


def has(txt, words):
    t = txt.lower()
    return [w for w in words if w.lower() in t]


def main():
    sa = {r["t"]: r for r in json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}
    rows = []
    for p in glob.glob(os.path.join(OUT, "*_gate_pack.json")):
        t = os.path.basename(p).replace("_gate_pack.json", "")
        d = json.load(open(p, encoding="utf-8"))
        x = d.get("data") or d
        if x.get("irr") != 70:
            continue
        r = sa.get(t) or {}
        if BUYONLY and not r.get("buy"):
            continue
        if not ALL and not BUYONLY and (r.get("s") or 0) < BAND:
            continue
        ev = ((d.get("_meta") or {}).get("evidence") or {}).get("irr") or ""
        f, c, g = has(ev, FRICTION), has(ev, CERT), has(ev, GENERIC)
        cls = "D 根拠なし" if not ev else ("A 摩擦の機構を名指し" if f else
              ("B 認定・認証の語だけ" if c else "C 一般的な競争記述だけ"))
        rows.append(dict(t=t, s=r.get("s"), moat=r.get("moat"), moatOK=r.get("moatOK"),
                         buy=r.get("buy"), cls=cls, n=len(ev),
                         hit=" ".join(sorted(set(f))[:5]) or " ".join(sorted(set(c))[:3]) or
                             " ".join(sorted(set(g))[:3])))
    scope = "全362社" if ALL else ("投下可" if BUYONLY else f"判定圏(Ω{BAND}+)")
    print(f"■ irr=70 の根拠が『移行の摩擦』を実証しているか（{scope}・n={len(rows)}）")
    print("  ※ evidence の文言を見る triage であって原本の判定ではない——**次に読む先を絞る道具**\n")
    from collections import Counter
    c = Counter(r["cls"] for r in rows)
    for k in ("A 摩擦の機構を名指し", "B 認定・認証の語だけ", "C 一般的な競争記述だけ", "D 根拠なし"):
        if c.get(k):
            print(f"  {k:<22}{c[k]:>4}社")
    order = {"D 根拠なし": 0, "C 一般的な競争記述だけ": 1, "B 認定・認証の語だけ": 2, "A 摩擦の機構を名指し": 3}
    print(f"\n  {'銘柄':<9}{'Ω':>6}{'堀':>7}{'字数':>6}  分類                    拾った語")
    for r in sorted(rows, key=lambda z: (order[z["cls"]], -(z["s"] or 0))):
        mark = "🟢" if r["buy"] else ("  " if r["moatOK"] else "⛔")
        print(f"  {mark}{r['t']:<7}{(r['s'] or 0):>6}{(r['moat'] or 0):>7.1f}{r['n']:>6}  "
              f"{r['cls']:<22}  {r['hit'][:44]}")

    if not ALL and not BUYONLY:
        risky = [r for r in rows if r["buy"] and r["cls"] != "A 摩擦の機構を名指し"]
        print(f"\n■ 読む順（投下可で分類がA以外＝{len(risky)}社）: "
              f"{' '.join(r['t'] for r in risky) or 'なし'}")
        print("  実測の重み: **判定圏の70を50に落とすと45社中19社が堀の関門を割り、投下可6社が落ちる**"
              "（6857/HWM/IDXX/IRMD/KLAC/RMD）。一方 85→70 では投下可は0社しか動かない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
