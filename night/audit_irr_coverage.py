#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_irr_coverage.py — irr の被覆の穴を測って作業リストにする（2026-08-14新設・ユーザー指示の①）

■ なぜ irr なのか
  13年・5系統・204通り・7アンカーの検証を**生き延びた唯一の指標**が irr（移行障壁の型）。
  効く機構まで分かっている——`ρ(irr, 事業の「驚き」) = +0.077〜+0.294`。
  「驚き」＝実現した事業のうち**入口の財務からは読めなかった部分**で、構造上 入口の財務と直交する。
  ⇒ **irr は財務諸表に無い情報を運んでいる**。だから価格の線が5回とも空振りする中で irr だけが残った。

■ ★その欄が、母集団の 12.3% にしか付いていない（実測）
  門0の母集団 2,902社 ／ パックがある 369社 ／ irr が測られている 357社。

■ ★「キューの幅」は測ったら実質的な問題ではなかった（2026-08-14・私の初版の断定を訂正する）
  初版は「2,605社が未審査＝門0のキューの幅が詰まっている」と書いたが**誤りだった**。
  落ちた理由を分解すると（score>=5 の297社）:
      pt足切り **96社**（7点 **0社** / 6点1 / 5点95）  ← これだけが「キューの幅」の問題
      業態除外 107社（金融/保険/REIT 69・資源採掘26・海運7・石油精製5）← 別の・もっと大きな規約判断
      棚(成長停止) 59 ／ 低マージン業態 17 ／ 再現不能18       ← 設計どおり
  **7点は pt足切りが0社**＝質のふるいを全部通った社は既に全員キューに載っている。
  17社が未審査なのは**全部 業態除外か国籍除外**（AMT/CUBE/NSA=REIT、SCCO/AU/USLM=鉱山、
  COP/PNRG/REPX=石油、ERIE/FHI/WT=金融、ESEA=海運、NTES/XYF=中国）。

■ ★そして歩留まりが桁違いだった（読む前に「読んで意味があるか」を測る＝kill_impact.py の作法）
      7点: 審査済100社 → Ω75+ **20社(20.0%)** / irr=85 3社
      6点: 審査済 77社 → Ω75+ **4社(5.2%)**  / irr=85 2社
      5点: 審査済101社 → Ω75+ **1社(1.0%)**  / irr=85 **0社**
  pt足切りの96社は **7点0 / 6点1 / 5点95**＝**ほぼ全部が歩留まり1%の5点**。
  しかも審査済みの5点101社は**pt上位側**なので、未審査の低pt95社の歩留まりは**さらに低い**。
  ⇒ 95社（Routineで19日）を読んで期待できるのは **Ω75+ 約1社・irr=85 ほぼ0**。
  **キューを広げても irr の被覆は上がらない。** 12.3%→22% と書いた初版の見積りは誤りだった。

■ この道具がすること（判定には一切触れない）
  (1) 被覆を数える（母集団／パック／irr あり／刻み別）
  (2) **一度も審査されていない社**を門0スコア順に出す＝読む先の作業リスト
  (3) パックはあるが irr が空の社を名指しする
  ⚠ キューの幅を広げること自体は**門0の選別基準の改定＝絶対のルール1の領分**。
    この道具は「何が漏れているか」を見せるだけで、規約は一つも変えない。

使い方: python3 night/audit_irr_coverage.py [--json] [--top N]
出力: out/irr_coverage.json
"""
import csv
import glob
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")


def load_queue():
    p = os.path.join(BASE, "gate1_queue.json")
    if not os.path.exists(p):
        return set()
    q = json.load(open(p, encoding="utf-8"))
    q = q if isinstance(q, list) else (q.get("items") or q.get("queue") or [])
    s = set()
    for x in q:
        t = (x.get("ticker") or x.get("t")) if isinstance(x, dict) else x
        if t:
            s.add(str(t).upper())
    return s


def main():
    top = 40
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])

    # ⚠ gate0_all.csv は BOM 付き。utf-8 で開くと 'ticker' が '﻿ticker' になり
    #   **全社のティッカーが空** になって「漏れ0社」というもっともらしい嘘が出る（実際に踏んだ）。
    csvp = os.path.join(BASE, "gate0_all.csv")
    rows = list(csv.DictReader(open(csvp, encoding="utf-8-sig"))) if os.path.exists(csvp) else []
    if rows and not (rows[0].get("ticker") or "").strip():
        sys.exit("★gate0_all.csv の ticker が読めない（BOM？）——測らずに終わる")

    packs, irr_have, irr_blank, rung = {}, 0, [], Counter()
    for p in glob.glob(os.path.join(OUT, "*_gate_pack.json")):
        t = os.path.basename(p).split("_gate_pack")[0]
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        packs[t.upper()] = d
        v = d.get("irr")
        if v is None:
            irr_blank.append(t)
        else:
            irr_have += 1
            rung[str(v)] += 1

    # ★2026-08-14: 「未審査◯社」を一つの数として出すのは**誤り**だった（私が実際に誤読した）。
    #   落ちた理由は4種類あって、直し方も判断の重さもまったく違う——
    #     (a)業態除外  … SIC で 金融/保険/REIT・資源採掘・石油精製・海運、および中国/香港/VIE。
    #                    **設計どおりの意図的な除外**で、開けるなら「門は金融やREITを審査するのか」
    #                    という別の、もっと大きな規約判断になる
    #     (b)棚(成長停止) … 6点で唯一のfailが売上CAGR。**門2で直せない唯一の病**なので審査枠を使わない。
    #                    毎年再計算されるので追放ではない
    #     (c)低マージン業態 … 6点・営業利益率fail・opm<10%。設計どおり
    #     (d)★pt足切り  … 上の3つでないのに TOP_N=100 に入らなかった＝**これだけが「キューの幅」の問題**
    #   ⚠ SIC が手元のキャッシュに無い社は「不明」として別に数える（除外と決めつけない・ルール7）
    sic = {}
    sp = os.path.join(OUT, "_sic_cache.json")
    if os.path.exists(sp):
        raw = json.load(open(sp, encoding="utf-8"))
        raw = raw.get("items") or raw
        for k, v in raw.items():
            try:
                sic[k.upper()] = int(v if not isinstance(v, dict) else (v.get("sic") or 0))
            except Exception:
                pass

    def excl(s):
        if not s:
            return None
        if 6000 <= s <= 6799: return "金融/保険/REIT"
        if 1000 <= s <= 1499: return "資源採掘"
        if s == 2911: return "石油精製"
        if 4400 <= s <= 4499: return "海運"
        return None

    def reason(r):
        """★門0が実際に落とした理由。CSV に excluded 列があればそれを使う（v9.9.144以降）。
        無い古いCSVでは SIC から再構成するが、**完全には再現できない**ことを明示する——
        (a)門0は SIC が取れなければ除外しない（`excluded_sic(None)` は None）ので
           「SIC不明」を除外扱いにするのは誤り（初版が踏んだ）
        (b)国籍による中国/香港/VIE 除外は SIC では再現できない（NTES/XYF がこれ）"""
        t = (r.get("ticker") or "").upper()
        ex = (r.get("excluded") or "").strip() if r.get("excluded") is not None else ""
        if ex:
            return "業態除外:" + ex          # ★CSVが持っていれば正確
        b = r.get("byomei") or ""
        if t in sic:
            w = excl(sic[t])
            if w:
                return "業態除外:" + w
        if b == "成長停止":
            return "棚(成長停止)"
        if b == "低マージン業態":
            return "低マージン業態"
        if t not in sic and "excluded" not in r:
            return "pt足切り?(SIC不明・国籍除外は再現不能)"
        return "pt足切り"

    qt = load_queue()
    seen = set(packs) | qt
    never, by_score = [], Counter()
    for r in rows:
        t = (r.get("ticker") or "").upper()
        try:
            s = int(float(r.get("score") or 0))
        except Exception:
            continue
        by_score[s] += 1
        if t and t not in seen:
            never.append((s, t, r.get("name") or "", r.get("roic_latest"), r.get("opm")))
    never.sort(key=lambda x: (-x[0], x[1]))
    hi = [x for x in never if x[0] >= 5]

    n_uni = len(rows)
    print("■ irr の被覆（13年の検証を生き延びた唯一の指標が、どれだけ測られているか）")
    print(f"   門0の母集団      {n_uni:5d} 社")
    print(f"   パックがある     {len(packs):5d} 社  = {len(packs)/n_uni*100:4.1f}%")
    print(f"   irr が測られた   {irr_have:5d} 社  = {irr_have/n_uni*100:4.1f}%   ← ここが門の精度の上限")
    print(f"   刻み別: " + " / ".join(f"{k}:{v}" for k, v in sorted(rung.items(), key=lambda x: -float(x[0]))))
    print(f"\n■ パックはあるが irr が空: {len(irr_blank)}社")
    print(f"   {' '.join(sorted(irr_blank))}")
    jp = [t for t in irr_blank if t[:1].isdigit()]
    if jp:
        print(f"   ⚠ うち日本株 {len(jp)}社——有報に代替可能性の記述が無く"
              f"**掘り尽くして確定した空欄**（キーエンス型）。規約を変えない限り埋まらない")

    print(f"\n■ ★門2審査に一度も載っていない社: {len(never)}社 / {n_uni}社")
    print(f"   うち門0スコア5点以上（質のふるいを概ね通る群）: **{len(hi)}社**")
    print(f"   {'点':>3s} {'社数':>5s}  {'未審査':>6s}")
    for s in sorted(by_score, reverse=True):
        m = sum(1 for x in never if x[0] == s)
        print(f"   {s:>3d} {by_score[s]:>5d}  {m:>6d}" + ("  ← 読む価値のある帯" if s >= 5 else ""))

    # ★落ちた理由で分解する（一つの数にまとめると誤読する。実際に私が誤読した）
    byrow = {(r.get("ticker") or "").upper(): r for r in rows}
    rsn = Counter()
    rsn_by = {}
    for s, t, nm, _, _ in hi:
        w = reason(byrow.get(t, {}))
        rsn[w] += 1
        rsn_by.setdefault(w, []).append((s, t))
    print(f"\n■ ★その297社が落ちた理由（直し方も判断の重さもまったく違う）")
    for w, c in rsn.most_common():
        mark = ("  ← **これだけが「キューの幅」の問題**" if w == "pt足切り"
                else "  ← 別の・もっと大きな規約判断（門は金融/REIT/資源/海運/中国を審査しない）"
                if w.startswith("業態")
                else "  ← ⚠再現不能（門0のCSVに excluded 列が入れば正確に分かる）"
                if w.startswith("pt足切り?") else "  ← 設計どおり")
        print(f"   {w:22s} {c:4d}社{mark}")

    # 歩留まり: 審査済みの社が実際どこまで届いたか（読む前に「読んで意味があるか」を測る）
    yld = {}
    for t, d in packs.items():
        r = byrow.get(t)
        if not r:
            continue
        try:
            k = int(float(r.get("score") or 0))
        except Exception:
            continue
        e = yld.setdefault(k, dict(n=0, o75=0, irr85=0))
        e["n"] += 1
        if d.get("irr") == 85:
            e["irr85"] += 1
    sa = os.path.join(OUT, "score_all.json")
    if os.path.exists(sa):
        S = json.load(open(sa, encoding="utf-8"))
        S = S if isinstance(S, list) else (S.get("rows") or S.get("items") or [])
        SM = {str(x.get("t")).upper(): x for x in S}
        for t in packs:
            r = byrow.get(t)
            if not r:
                continue
            try:
                k = int(float(r.get("score") or 0))
            except Exception:
                continue
            if (SM.get(t, {}).get("s") or 0) >= 75:
                yld[k]["o75"] += 1
    print(f"\n■ ★歩留まり（審査済みの社が実際どこまで届いたか）——読む前に「読んで意味があるか」を測る")
    print(f"   {'点':>3s}{'審査済':>7s}{'Ω75+':>7s}{'率':>8s}{'irr=85':>8s}")
    for k in sorted(yld, reverse=True):
        e = yld[k]
        if e["n"] < 3:
            continue
        print(f"   {k:>3d}{e['n']:>7d}{e['o75']:>7d}{e['o75']/e['n']*100:7.1f}%{e['irr85']:>8d}")

    print(f"\n■ 読む先の作業リスト（★pt足切りの社だけ・門0スコア順・上位{top}社）")
    ptcut = [(s, t) for s, t in [(x[0], x[1]) for x in hi] if reason(byrow.get(t, {})) == "pt足切り"]
    if not ptcut:
        print("   （なし）")
    for s, t in ptcut[:top]:
        r = byrow.get(t, {})
        print(f"   {s}点 {t:8s} {str(r.get('name'))[:34]:34s} roic {str(r.get('roic_latest'))[:6]:>6s}")

    doc = dict(generated=__import__("time").strftime("%Y-%m-%d"),
               universe=n_uni, packs=len(packs), irr_measured=irr_have,
               irr_pct=round(irr_have / n_uni * 100, 1), rungs=dict(rung),
               irr_blank=sorted(irr_blank),
               never_reviewed=len(never), never_reviewed_score5plus=len(hi),
               reasons=dict(rsn),
               worklist=[dict(score=s, ticker=t, name=nm, reason=reason(byrow.get(t, {})))
                         for s, t, nm, _, _ in hi[:300]],
               yield_by_score={str(k): v for k, v in yld.items()},
               NOTE="キューの幅を広げるのは門0の選別基準の改定＝絶対のルール1の領分。"
                    "この道具は漏れを見せるだけで規約は一つも変えない。")
    json.dump(doc, open(os.path.join(OUT, "irr_coverage.json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n→ out/irr_coverage.json")
    print("⚠ キューの幅を広げること自体は門0の選別基準の改定＝ユーザーの明示指示の領分。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
