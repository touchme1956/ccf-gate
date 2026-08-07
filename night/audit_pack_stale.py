#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_pack_stale.py — **パックより新しい年次報告が、もう出ていないか**（2026-08-07新設）

なぜ要るか（既存の検査が全部すり抜ける穴）:
  2026-08-06 に APH で「パックの決算期末の9日後に会社が別物になっていた」を踏み、
  audit_stale_bs.py を作った。だがあれは **のれんの入れ替わり** しか見ていない
  ——つまり**大型買収をした社しか捕まえられない**。買収をしない優良企業が、
  ただ静かに1会計年度ぶん古くなっていくのは、今日どの検査器にも掛からない:

    validate_packs の鮮度検査 : reportDate と auditDate の**「年」の差**（3年でFAIL・2年でwarn）
                                 → 1年遅れは警告すら出ない
    audit_stale_bs            : のれんの新しさ ≥30%
                                 → 買収の無い社は素通り
    ops_status（回転盤）        : **道具が回っているか**は見るが、**パックが現在を描いているか**は見ない

  実測（2026-08-07・判定圏の米国等39社）——**5社でパックより新しい10-Kが既に提出済み**:
      MSFT Ω85.0 ★投下可  パック FY2025(2025-06-30) → 最新 FY2026(2026-06-30) 提出 2026-07-29
      KLAC Ω81.0 ★投下可  パック FY2025(2025-06-30) → 最新 FY2026(2026-06-30) 提出 2026-08-06
      CTAS / BR / ADP も1会計年度ぶん古い
  MSFT は利用者の資産の 22.7% を占める最大の個別保有で、買付順位にも入っている。
  **1年前の会社の姿で配分を決めていた**ことになる。

何を測るか:
  パックの `_meta.reportDate` と、SEC に提出済みの**最新の年次報告(10-K/20-F/40-F)の決算期末**を比べ、
  後者が新しければ「再審査待ち」とする。閾値は無い——**新しい年次報告が出ている、という事実だけ**。
  提出からの経過日数も出す（昨日出たものと3ヶ月放置は別物なので、優先順位はそこで付ける）。

思想:
  **これは関門にしていない。** 新しい10-Kが出ていることは*欠陥ではなく再審査の合図*で、
  今日これを関門にすると投下可の MSFT・KLAC が即座に落ちる。この門の作法では
  「落ちる社がいるなら、規則の追加ではなく現状の是正が先」（v9.9.95で守った順序）。
  したがってこれは**作業リストを出す道具**であり、Ω・堀・売却規律・四関門はいずれも動かさない。

  **日本株は対象外＝穴として明示する**（EDINET経路が要る）。黙って対象外にしない。

使い方:
  python3 night/audit_pack_stale.py            判定圏(Ω72+)だけ（SECへの請求を絞る）
  python3 night/audit_pack_stale.py --all      全パック
  python3 night/audit_pack_stale.py --t MSFT   1銘柄
  python3 night/audit_pack_stale.py --write    out/pack_stale.json を更新
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
EMAIL = "fortis5280@gmail.com"
HDRS = {"User-Agent": f"ccf-gate {EMAIL}"}
ANNUAL = ("10-K", "20-F", "40-F")

ARGV = sys.argv[1:]
ALL = "--all" in ARGV
WRITE = "--write" in ARGV
ONE = ARGV[ARGV.index("--t") + 1] if "--t" in ARGV else None


def get(url):
    """SECは10req/s制限。混雑時の429はバックオフで待つ（黙って諦めない）。"""
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=45) as r:
                b = r.read()
            time.sleep(0.15)
            return b.decode("utf-8", "ignore")
        except Exception as e:                     # noqa: BLE001
            last = e
            time.sleep(2 ** i)
    raise last


_TICK = {}


def cik_of(t):
    global _TICK
    if not _TICK:
        j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
        _TICK = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in j.values()}
    return _TICK.get(t.upper())


def latest_annual(cik):
    """{決算期末, 提出日, 様式} を返す。年次報告が一つも無ければ None。"""
    s = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    f = s.get("filings", {}).get("recent", {})
    best = None
    for form, rep, fil in zip(f.get("form", []), f.get("reportDate", []), f.get("filingDate", [])):
        if form in ANNUAL and rep and (best is None or rep > best[0]):
            best = (rep, fil, form)
    return best


def days_between(a, b):
    return (date(*map(int, b.split("-"))) - date(*map(int, a.split("-")))).days


def main():
    rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
    if ONE:
        pick = [r for r in rows if r["t"] == ONE]
    elif ALL:
        pick = rows
    else:
        pick = [r for r in rows if (r.get("s") or 0) >= 72]

    today = str(date.today())
    print(f"■ パックより新しい年次報告が既に出ていないか　対象 {len(pick)}社"
          f"{'（判定圏 Ω72+）' if not (ALL or ONE) else ''}")
    print("  判定に閾値は無い——**新しい10-K/20-Fが提出済みという事実だけ**。")
    print("  既存の検査はどれもこれを見ていない（validate_packsの鮮度は『年』3年でFAIL／"
          "audit_stale_bsはのれんの入替のみ＝買収しない社は素通り）\n")

    res, skipped = {}, []
    for r in pick:
        t = r["t"]
        if re.fullmatch(r"\d{4}", t):
            skipped.append((t, "日本株（SEC対象外・EDINET経路が要る＝監視の穴）"))
            continue
        p = os.path.join(OUT, f"{t}_gate_pack.json")
        if not os.path.exists(p):
            continue
        rd = str((json.load(open(p, encoding="utf-8")).get("_meta") or {}).get("reportDate") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rd):
            skipped.append((t, "reportDate が無い/不正"))
            continue
        cik = cik_of(t)
        if not cik:
            skipped.append((t, "CIK不明（ADR等）"))
            continue
        try:
            best = latest_annual(cik)
        except Exception as e:                     # noqa: BLE001
            skipped.append((t, f"取得失敗: {e}"))
            continue
        if not best:
            skipped.append((t, "年次報告が見つからない"))
            continue
        rep, fil, form = best
        behind = rep > rd
        mark = "⚠ 再審査待ち" if behind else "✓"
        print(f"  {t:<7}パック {rd} / 最新 {rep}（{form} 提出 {fil}）  {mark}")
        if behind:
            res[t] = dict(pack=rd, latest=rep, filed=fil, form=form,
                          sinceFiled=days_between(fil, today),
                          omega=r.get("s"), buy=bool(r.get("buy")), quali=bool(r.get("quali")))

    print()
    if res:
        print("■ 再審査待ち（門2審査を新しい年次報告で回し直す）　提出が古い順＝放置が長い順")
        for t, v in sorted(res.items(), key=lambda x: -x[1]["sinceFiled"]):
            tag = " ★投下可" if v["buy"] else (" 🔵次点" if v["quali"] else "")
            print(f"   {t:<7}Ω{v['omega']:>5.1f}{tag:<8} {v['pack']} → {v['latest']}"
                  f"（提出から {v['sinceFiled']} 日）")
        nb = sum(1 for v in res.values() if v["buy"])
        if nb:
            print(f"\n   うち **{nb}社が投下可**——1会計年度前の姿で配分を決めている状態。")
            print("   ただしこれは欠陥ではなく**再審査の合図**なので、関門にはしていない"
                  "（今日これで切ると投下可が落ちる＝『落ちるなら是正が先』の順序に反する）")
    else:
        print("✓ 判定圏のパックはすべて最新の年次報告に追いついている")

    if skipped:
        from collections import Counter
        print(f"\n  対象外 {len(skipped)}社（穴として明示する・黙って対象外にしない）:")
        for why, n in Counter(w for _, w in skipped).most_common():
            print(f"    {n:>3}社  {why}")

    if WRITE:
        path = os.path.join(OUT, "pack_stale.json")
        json.dump({"asof": today,
                   "rule": "パックの reportDate より新しい年次報告(10-K/20-F/40-F)が提出済み＝再審査待ち。"
                           "関門ではなく作業リスト",
                   "items": res,
                   "skipped": [{"t": a, "why": b} for a, b in skipped]},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {path} を更新（再審査待ち {len(res)}社）")
    else:
        print("\n（--write で out/pack_stale.json を更新する）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
