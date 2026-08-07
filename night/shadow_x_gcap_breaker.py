#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_x_gcap_breaker.py — **門Xの価格の関門は二つあり、二つは別のものを止めている**（2026-08-07新設）

なぜ要るか:
  門Xの遮断器は v9.9.84 で `E[r]≥0` になった。採用理由は 6920レーザーテック——
  会社自身が減益予想(−18.8%)を出している最中に買うのを止める、という**gcap機構**の実例だった。
  ところが遮断器の式は E[r] = shy + g + **倍率の重力(mult)** で、mult は
  「今のPERが fairPER より高い」ことへの罰＝**価格の判断**。
  2026-08-07の歴史検定（night/retro_er_test.py）は、質実証プールの中では
  **E[r]は弱い逆信号**（Q5−Q1 = −5.3pt / E[r]≥12%群 5.2% vs <12%群 8.1%）と出た。
  つまり遮断器は「減益予想を止める」と「高倍率を止める」を**一本の式で兼ねており、
  後者は歴史が支持しない**。分けて測る必要がある。

何を測るか:
  判定圏(Ω72+)の各社について、
    (a) 現行の遮断器 E[r]≥0 が誰を止めているか
    (b) その社の **gr = per/perF − 1**（＝門が gcap 空欄時に使う暫定代用。1年フォワードの増益率）が
        負かどうか——「会社/市場が下りだと言っているか」だけを見る狭い遮断器
  の二つを並べる。**規約は何も変えない**（絶対のルール1・6）——影の計測だけ。

  併せて、遮断器を緩めても買付が動かない理由——**配分式の E[r]点（E[r]≤2%でウェイト0）が
  同じ仕事を先にやっている**——を実測で出す。「価格の関門は二重にある」(2026-08-06)の再測定。

前提:
  gcap は全362社で 0件、perF は 37件（判定圏49社中14件＝29%）しかない。
  **gcap基準の遮断器は今日は採用できない**——入力が無い社を素通りさせると
  「測らないほうが有利」になり、この台帳が繰り返し潰してきた型を規約の側から再導入することになる。
  この道具はまずその被覆率を数える。

使い方: python3 night/shadow_x_gcap_breaker.py [--write]
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
WRITE = "--write" in sys.argv[1:]
BAND = 72          # 判定圏


def erpt(er):
    """配分式の E[r]点（門の erPtW と同式・錨 12%=50点・±10ptで0-100）"""
    if er is None:
        return 0.0
    return max(0.0, min(100.0, 50 + (er - 12) * 5))


def main():
    sa = {r["t"]: r for r in json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}
    rows, cov_all, cov_perf = [], 0, 0
    for p in glob.glob(os.path.join(OUT, "*_gate_pack.json")):
        t = os.path.basename(p).replace("_gate_pack.json", "")
        d = json.load(open(p, encoding="utf-8"))
        x = d.get("data") or d
        cov_all += 1
        has_pf = x.get("perF") not in (None, "", 0)
        cov_perf += has_pf
        r = sa.get(t)
        if not r or (r.get("s") or 0) < BAND:
            continue
        per, pf = x.get("per"), x.get("perF")
        gr = (per / pf - 1) * 100 if (per and pf) else None
        rows.append(dict(t=t, s=r.get("s"), er=r.get("xEr"), xPass=r.get("xPass"),
                         gr=None if gr is None else round(gr, 1), moatOK=r.get("moatOK"),
                         buy=r.get("buy"), a=r.get("a")))

    band = [r for r in rows if r["s"] >= BAND]
    pf_band = sum(1 for r in band if r["gr"] is not None)
    print("■ 門Xの価格の関門は二つあり、二つは別のものを止めている")
    print(f"  被覆率: perF は全{cov_all}社中 **{cov_perf}社** ／ "
          f"判定圏(Ω{BAND}+){len(band)}社中 **{pf_band}社（{pf_band/len(band):.0%}）**／ gcap は **0社**")
    print("  → **gcap基準の遮断器は今日は採用できない**。入力の無い社を素通りさせると"
          "『測らないほうが有利』になる（未測定を最良ケースで裁く型）")

    blocked = [r for r in band if r["xPass"] is not True]
    print(f"\n── (a) 現行の遮断器 E[r]≥0 が止めている {len(blocked)}社 ──")
    print(f"     {'銘柄':<8}{'Ω':>6}{'E[r]':>7}{'gr(1年フォワード)':>18}  堀   止めた理由の正体")
    for r in sorted(blocked, key=lambda z: (z["er"] is None, z["er"] if z["er"] is not None else 0)):
        if r["gr"] is not None and r["gr"] < 0:
            why = "**減益予想**＝gcap機構（6920型・狭い遮断器でも捕まる）"
        elif r["gr"] is not None:
            why = "増益予想なのに落ちた＝**倍率の重力だけ**で落ちている"
        elif r["er"] is None:
            why = "**E[r]算出不能**（per未取得＝門X未評価。価格の判断ですらない）"
        else:
            why = "perF未取得——E[r]が僅かに負＝**倍率の重力**が shy+g をわずかに上回っただけ"
        grs = "—" if r["gr"] is None else f"{r['gr']:+.1f}%"
        ers = "na" if r["er"] is None else f"{r['er']}"
        print(f"     {r['t']:<8}{r['s']:>6}{ers:>7}{grs:>18}"
              f"  {'✓' if r['moatOK'] else '✗'}   {why}")

    neg = [r for r in band if r["gr"] is not None and r["gr"] < 0]
    print(f"\n── (b) 狭い遮断器（gr<0＝会社/市場が下りだと言っている）が止める {len(neg)}社 ──")
    for r in neg:
        print(f"     {r['t']:<8}Ω{r['s']:>6}  gr {r['gr']:+.1f}%  "
              f"（現行の遮断器でも{'止まる' if r['xPass'] is not True else '通る'}）")

    # ── 二重の関門: 遮断器を外しても配分式の E[r]点 が同じ仕事をする ──────────
    print("\n── (c) 遮断器を外しても買付が動かない理由＝配分式の E[r]点 ──")
    print("     合成点 = Ω × E[r]点 ÷ 50、E[r]点 = clamp(50+(E[r]−12)×5, 0, 100)")
    print("     ⇒ **E[r]≤2% で E[r]点=0＝合成点0**。四段関門を通っても上位10社に構造的に入れない")
    rel = [r for r in blocked if r["moatOK"] and r["s"] >= 75]
    if rel:
        print(f"     遮断器だけを外すと資格を得る社（Ω75+ ∧ 堀70+）: "
              f"{' '.join(r['t'] for r in rel)}")
        last = min(x["a"] for x in band if x["buy"])
        for r in sorted(rel, key=lambda z: -(z["er"] if z["er"] is not None else -99)):
            if r["er"] is None:
                print(f"       {r['t']:<6} E[r] **算出不能**（per未取得）→ 合成点を作れない"
                      f"＝遮断器を外しても席は取れない。**止めているのは価格でなく採取の穴**")
                continue
            print(f"       {r['t']:<6} E[r]{r['er']:>6}% → E[r]点 {erpt(r['er']):.0f} → "
                  f"合成点 {r['s']*erpt(r['er'])/50:.2f}（現行10位 {last:.2f} に届かない）")
    print("     ＝ **遮断器と配分式の二重**。遮断器だけを触っても買付は1社も動かない"
          "（2026-08-06の shadow_x_moat_exception の再現）")

    if WRITE:
        p = os.path.join(OUT, "shadow_x_gcap_breaker.json")
        json.dump({"generated": "2026-08-07", "band": BAND,
                   "coverage": {"packs": cov_all, "perF": cov_perf,
                                "band": len(band), "band_perF": pf_band, "gcap": 0},
                   "rows": rows,
                   "note": "規約は不変。gcap基準の遮断器は被覆率29%では採用不可"},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
