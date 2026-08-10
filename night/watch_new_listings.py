#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/watch_new_listings.py — **上場後1年で irr=85 を測れるようにする**
（2026-08-10新設・ユーザー明示指示「上場後1年後にirr85の銘柄は測定できるようにしたい」）

■ なぜ要るか（穴の実測）
  2026-08-08 の全母集団スイープは `forms=10-K,20-F` の**一回きりの掃除**で、
  読解リストは「**パックが無い社**」403社に絞っていた。この設計には二つの穴があった:

  (1) **新しく上場した会社が入ってこない**。上場初年度は10-Kをまだ出さないので網に掛からず、
      翌年に初めての10-Kを出しても**スイープはもう回っていない**。
      実測: LOAR（2024-04 IPO・今日の台帳で irr=85）は 424B4 に機構語があるのに、
      当時の網は年次報告しか見ていなかった。

  (2) **パックはあるが irr の根拠が空の社が読解対象から外れる**。
      実測: **KRMN（カーマン・2025-02 IPO）は ranked に居たのに readlist から外された**
      ——`packed:true` だったから。その台帳の irr=70 は `_meta.evidence.irr` が空で、
      FY2025 10-K には『once a supplier has been qualified on a particular program …
      it is unlikely that **a customer would pursue re-qualification**, given its typically
      lengthy and costly nature』＋『**certification under customer quality requirements
      and assurance programs**』（後者は CW の2018年ビンテージと**一字同文**）がある。

  歴史検証は「リターンと生死を分けた唯一の変数は irr の測定精度」と出している。
  ならば**測る対象が母集団に入ってこない**ことは、測り方の誤りと同じ重さで効く。

■ 何をするか（判定はしない・作業リストを出すだけ）
  1. EDGAR全文検索を**フレーズ側から**引く（scan_irr85_universe.py の STRONG/MED/ASPIR と
     fetch() を **import して共有**する。フレーズ表を書き写すと片方が取り残される＝v9.9.65の掟）
  2. 当たった CIK ごとに submissions を引き、**最初の年次報告(10-K/20-F/40-F)の提出日**を出す
     → これが「上場後1年」の実務的な錨。IPO日そのものではなく**機構語が年次報告として
       読める最初の瞬間**を採る（審査は原本優先・2026-07-28の方針）
  3. 台帳と突き合わせて3つに仕分ける:
       🆕 未審査（パック無し）           → 門2審査へ
       ⚠ 根拠なし（パックはあるが evidence.irr が空）→ 読み直し（KRMNの穴）
       ✓ 測定済み（根拠つき）
  4. out/new_listings_irr.json へ在庫し、作業リストを出す

  **値も規約も触らない。** irr の刻みを決めるのは原本を読む審査官の仕事（絶対のルール2）で、
  この道具は「**同じ材料を全員に配る**」だけ。

■ 「新しい会社か」の判定（上限の不等式で決める・ルール7に触れない作法）
  submissions の `filings.recent` は直近1000件まで。**それより古い提出が一つでもあれば
  `filings.files` が空でない**ので、その会社は新規ではないと**確定できる**。
  recent の中に newdays より古い年次報告があっても同じく新規ではない。
  つまり「新規」と言えるのは**両方とも否定できたときだけ**＝取りこぼす側に倒れる。

使い方:
  python3 night/watch_new_listings.py                 直近420日の年次報告を掃く（作業リストだけ出す）
  python3 night/watch_new_listings.py --days 420 --newdays 900
  python3 night/watch_new_listings.py --s1            IPO目論見書(S-1/424B4/F-1)も掃く
  python3 night/watch_new_listings.py --all           一般語だけの社まで全件出す
  python3 night/watch_new_listings.py --json          機械可読で出す

■ 実測（初回・2026-08-10／窓 2025-06-16..2026-08-10・新規の線 2024-02-22）
  掃いた 1,066社 → 新規上場組 **186社** → **作業リストは6社**
  （機構語STRONGを持つ社だけに絞る。一般語 'qualification requirements' 等まで並べると
    REIT・白地小切手・アパレルが180社並んで**鳴りすぎる警報は鳴らないのと同じ**になる）
    KRMN w7 ⚠根拠なし ／ ALAB w5 📖読解済み(提案85→反証70) ／ LOAR w4 ✓測定済み(85) ／
    FLY w4 🆕未審査 ／ SELX w3 🆕未審査 ／ YSS w3 🆕未審査
"""
import datetime
import glob
import importlib.util
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = {"User-Agent": "CCF-Omega-Screener fortis5280@gmail.com"}
ANNUAL = ("10-K", "20-F", "40-F")
IPO_FORMS = "S-1,S-1/A,424B4,424B3,F-1,F-1/A"


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return cast(sys.argv[i + 1])
    return default


DAYS = arg("--days", 420, int)        # 年次報告を掃く窓。上場1年目の10-Kが必ず入る幅
NEWDAYS = arg("--newdays", 900, int)  # 「最初の年次報告がこの日数以内＝新規上場組」
AS_JSON = "--json" in sys.argv
WITH_S1 = "--s1" in sys.argv
SHOW_ALL = "--all" in sys.argv     # 一般語だけの社まで全部出す（既定は作業リストのみ）
MAXPAGE = arg("--maxpage", 300, int)  # 1フレーズあたり拾う最大件数（多すぎる一般語の暴走止め）


def load_phrases():
    """scan_irr85_universe.py のフレーズ表と fetch() をそのまま借りる（二重実装を作らない）"""
    spec = importlib.util.spec_from_file_location(
        "scan_irr85_universe", os.path.join(ROOT, "night", "scan_irr85_universe.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)   # `if __name__` で包んであるので本体は走らない
    return m


def get(url, tries=4):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.0 * (a + 1))
    return None


TKRE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,5})\)\s+\(CIK")


def sweep(m, forms, start, end):
    """フレーズ側から引いて CIK→{name,ticker,ph{}} を集める"""
    hits = {}
    for ph, w in {**m.STRONG, **m.MED, **m.ASPIR}.items():
        j = m.fetch(ph, 0, forms, start, end)
        if not j:
            print(f"  {ph:32s} 取得失敗", file=sys.stderr)
            continue
        total = j["hits"]["total"]["value"]
        if not total:
            continue
        frm = 0
        while frm < min(total, MAXPAGE):
            jj = j if frm == 0 else m.fetch(ph, frm, forms, start, end)
            if not jj:
                break
            hs = jj["hits"]["hits"]
            if not hs:
                break
            for h in hs:
                src = h.get("_source", {})
                names = src.get("display_names") or []
                for k, c in enumerate(src.get("ciks") or []):
                    c = str(c).zfill(10)
                    nm = names[k] if k < len(names) else ""
                    d = hits.setdefault(c, {"name": nm, "ticker": None, "ph": {}})
                    if not d["name"] and nm:
                        d["name"] = nm
                    mm = TKRE.search(nm or "")
                    if mm and not d["ticker"]:
                        d["ticker"] = mm.group(1)
                    d["ph"][ph] = d["ph"].get(ph, 0) + 1
            frm += len(hs)
            time.sleep(0.22)
        print(f"  {ph:32s} {total:6d}件 → 累計 {len(hits)}社", file=sys.stderr)
    for c, d in hits.items():
        d["score"] = sum({**m.STRONG, **m.MED, **m.ASPIR}.get(p, 0) for p in d["ph"])
        d["strong"] = sorted(p for p in d["ph"] if p in m.STRONG)
        d["aspir"] = sorted(p for p in d["ph"] if p in m.ASPIR)
    return hits


def first_annual(cik):
    """(最初の年次報告の提出日, 直近の年次報告の提出日, 確実に新規でないか, sic) を返す。
    filings.files が非空＝recent より古い提出が在る＝**新規ではないと確定できる**"""
    j = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not j:
        return None, None, None, None, None
    older = bool((j.get("filings") or {}).get("files"))
    rec = (j.get("filings") or {}).get("recent") or {}
    forms, dates = rec.get("form") or [], rec.get("filingDate") or []
    ann = sorted(d for f, d in zip(forms, dates) if f in ANNUAL)
    tk = (j.get("tickers") or [None])[0]
    return (ann[0] if ann else None), (ann[-1] if ann else None), older, j.get("sicDescription"), tk


def ledger():
    """台帳: ticker → (irrの値, 根拠があるか)"""
    out = {}
    for f in glob.glob("out/*_gate_pack.json"):
        t = os.path.basename(f).split("_gate_pack")[0].upper()
        try:
            x = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        d = x.get("data") or x
        ev = ((x.get("_meta") or {}).get("evidence") or {}).get("irr")
        nl = ((x.get("_meta") or {}).get("nulls") or {}).get("irr")
        out[t] = (d.get("irr"), bool((ev or "").strip() or (nl or "").strip()))
    return out


def already_read():
    """**パックが無くても読解済みの社**: ticker → {irr, why}
    2026-08-08 の全母集団スイープは403社を原本で読んだが、**85が出なかった社はパック化していない**。
    ここを見ないと、毎月の掃除が同じ403社を「未審査」として出し続ける＝
    作業リストが本物でなくなる（鳴りすぎる警報は鳴らないのと同じ）。
    ⚠ rows は**読解者の提案**なので、反証(triage)で覆った社は最終値で上書きする
       ——実測: ALAB は提案85 → 反証で70（『If we fail to achieve design wins』＝NVDAと同型）"""
    out = {}
    try:
        for r in (json.load(open("out/irr85_hunt_result.json", encoding="utf-8")).get("rows") or []):
            t = (r.get("ticker") or r.get("t") or "").upper()
            if t:
                out[t] = {"irr": r.get("irr"), "why": (r.get("why") or "")[:300],
                          "src": "hunt2026-08-08"}
    except Exception:
        pass
    try:
        for r in (json.load(open("out/irr85_hunt_triage.json", encoding="utf-8")).get("refuted") or []):
            t = (r.get("ticker") or "").upper()
            if t:
                out[t] = {"irr": r.get("finalIrr"), "why": (r.get("reason") or "")[:300],
                          "src": "hunt2026-08-08/反証", "was": r.get("was"),
                          "failureMode": r.get("failureMode")}
    except Exception:
        pass
    return out


def main():
    m = load_phrases()
    end = datetime.date.today()
    start = end - datetime.timedelta(days=DAYS)
    print(f"■ 年次報告を掃く（{start}..{end}・forms=10-K,20-F,40-F）", file=sys.stderr)
    hits = sweep(m, "10-K,20-F,40-F", start, end)
    if WITH_S1:
        print(f"■ IPO目論見書も掃く（forms={IPO_FORMS}）", file=sys.stderr)
        for c, d in sweep(m, IPO_FORMS, start, end).items():
            t = hits.setdefault(c, {"name": d["name"], "ticker": d["ticker"], "ph": {},
                                    "score": 0, "strong": [], "aspir": []})
            t["ipo_doc"] = True
            for p, n in d["ph"].items():
                t["ph"][p] = t["ph"].get(p, 0) + n
            t["score"] = max(t.get("score", 0), d["score"])
            t["strong"] = sorted(set(t.get("strong", [])) | set(d["strong"]))

    led, red = ledger(), already_read()
    cut = (end - datetime.timedelta(days=NEWDAYS)).isoformat()
    print(f"■ {len(hits)}社の提出履歴を引いて「最初の年次報告が {cut} 以降」を選ぶ", file=sys.stderr)
    rows = []
    for i, (c, d) in enumerate(sorted(hits.items(), key=lambda kv: -kv[1]["score"])):
        fa, la, older, sic, tk2 = first_annual(c)
        time.sleep(0.12)
        if older or not fa or fa < cut:
            continue                       # 古い提出が在る／年次報告がまだ無い／古参 → 新規ではない
        t = (d["ticker"] or tk2 or "").upper()
        irr, has_ev = led.get(t, (None, None))
        rd = red.get(t)
        state = ("✓測定済み" if (t in led and has_ev)
                 else "⚠根拠なし" if t in led
                 else "📖読解済み" if rd
                 else "🆕未審査")
        rows.append({"cik": c, "t": t or None, "nm": d["name"], "sic": sic,
                     "firstAnnual": fa, "latestAnnual": la,
                     "score": d["score"], "strong": d["strong"], "aspir": d["aspir"],
                     "ph": sorted(d["ph"]), "ipoDoc": bool(d.get("ipo_doc")),
                     "packIrr": irr, "hasEvidence": has_ev, "read": rd, "state": state})
        if (i + 1) % 50 == 0:
            print(f"    …{i+1}/{len(hits)}社 照会済み・該当{len(rows)}社", file=sys.stderr)

    rows.sort(key=lambda r: (-r["score"], r["firstAnnual"]))
    work = [r for r in rows if r["strong"] or r["state"] == "⚠根拠なし"]
    doc = {"generated": end.isoformat(),
           "window": f"{start}..{end}", "newSince": cut,
           "note": "上場後1年前後で最初の年次報告を出した会社のうち、irr の機構語を含む社。"
                   "**判定ではなく作業リスト**——irr の刻みは原本を読む審査官が決める（絶対のルール2）。"
                   "SEC提出書類のみ＝日本株は対象外（EDINETは別経路＝穴として明示）。"
                   "作業リスト(work)は**機構語STRONGを含む社と、パックはあるが irr の根拠が空の社**だけ"
                   "——一般語(qualification requirements 等)だけの社まで並べると"
                   "『鳴りすぎる警報は鳴らないのと同じ』になるため。全件は rows に在る。",
           "nSwept": len(hits), "n": len(rows), "nWork": len(work),
           "counts": {k: sum(1 for r in rows if r["state"] == k)
                      for k in ("🆕未審査", "📖読解済み", "⚠根拠なし", "✓測定済み")},
           "work": [r["t"] or r["cik"] for r in work],
           "rows": rows}
    json.dump(doc, open("out/new_listings_irr.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    if AS_JSON:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    print(f"\n■ 上場後1年前後の新規社 {len(rows)}社（掃いた {len(hits)}社から）　{doc['counts']}")
    print(f"■ 作業リスト {len(work)}社＝機構語STRONGを含む社 ＋ irr の根拠が空の社\n")
    print(f"{'状態':<10}{'':<7}{'強度':>3}  {'初回年次':<11}{'業種':<26}機構語 / 既に読んだ結論")
    for r in (rows if SHOW_ALL else work):
        note = ",".join(r["strong"] or r["ph"])[:44]
        if r["read"]:
            note += f"  → 読解済み irr={r['read'].get('irr')}"
            if r["read"].get("was"):
                note += f"（提案{r['read']['was']}→反証: {r['read'].get('failureMode')}）"
        elif r["state"] == "⚠根拠なし":
            note += f"  → 台帳 irr={r['packIrr']} だが根拠が空"
        print("%-10s%-7s%3d  %-11s%-26s%s"
              % (r["state"], r["t"] or "—", r["score"], r["firstAnnual"],
                 (r["sic"] or "")[:24], note))
    print("\n→ out/new_listings_irr.json（--all で全件・--s1 でIPO目論見書も掃く）")
    print("   🆕未審査 は hachimon_fetch → 門2審査へ／⚠根拠なし は原本で irr を読み直す／"
          "📖読解済み は 2026-08-08 のスイープで結論が出ている（再読しない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
