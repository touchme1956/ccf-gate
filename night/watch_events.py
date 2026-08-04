#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_events.py — 監視リストの 8-K を日次で見張るイベント駆動監視（2026-08-04新設・提案4）

なぜ要るか:
  四半期点検(kessan_check.py)は3ヶ月に1回しか回らず、その間の減損・経営者退任・
  過年度訂正は誰も見ていなかった。KLACの$230.4百万のれん減損を「監視リストにいたのに
  見逃しかけた」型の事故は、この四半期の隙間で起きる。8-K は SEC がイベント発生から
  原則4営業日以内の提出を義務づける一次情報なので、これを毎日なめれば隙間が塞がる。

何をするか:
  kanshi_list.json（list ∪ pin）の米国銘柄について SEC submissions API の直近提出を読み、
  8-K の Item 番号で警報を立てる。判定には一切使わない——ヒットは門2再審査（依頼文）へ
  回すための「気づき」であり、株価は見ない（kessan_check と同じ思想）。

警報にする Item（門の6警報語との対応）:
  1.03 破産・管財         → 誠(存続)
  2.06 重要な減損         → 減損
  3.01 上場廃止通知       → 誠
  4.02 過年度財務の非依拠  → 誠(会計)
  5.02 役員・取締役の退任  → 退任
  ※ 2.02(決算発表)は四半期点検の領分なので警報にしない（毎四半期鳴る警報は鳴らないのと同じ）

日本株は対象外＝穴のまま（EDINET APIは鍵が要る）。出力にその旨を明示する——
黙って対象外にすると「監視されている」顔をする（kessan_check の偽健全と同型の事故になる）。

使い方:
  python3 night/watch_events.py            直近7日窓（日次CI用。休日またぎを吸収）
  python3 night/watch_events.py --days 30  窓を広げる（初回・停止後の追いつき）
出力: out/events_watch.json（ヒット・対象外・取得失敗を全部書く。失敗を「異常なし」と書かない）
"""
import json, os, sys, time, urllib.request
from datetime import date, timedelta

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL = "fortis5280@gmail.com"
HDRS  = {"User-Agent": f"ccf-gate-events {EMAIL}"}
OUT   = os.path.join(BASE, "out", "events_watch.json")

# Item番号 → 門の警報語（ここに無いItemは記録するが警報にしない）
ALERT_ITEMS = {
    "1.03": "誠(存続)——破産・管財",
    "2.06": "減損——重要な資産の減損",
    "3.01": "誠——上場維持基準の不適合通知",
    "4.02": "誠(会計)——過年度財務諸表の非依拠(non-reliance)",
    "5.02": "退任——取締役・主要役員の異動",
}


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)  # 礼儀(10req/s未満・hachimon_fetchと同じ)
    return b.decode("utf-8", "ignore")


def kanshi_us():
    """監視リストの米国銘柄（4-5桁コード=日本株は対象外として別に返す）"""
    p = os.path.join(BASE, "kanshi_list.json")
    k = json.load(open(p, encoding="utf-8"))
    names = list(dict.fromkeys((k.get("list") or []) + (k.get("pin") or [])))
    us, jp = [], []
    for n in names:
        t = str(n).strip().split()[0]
        (jp if t[:1].isdigit() else us).append(t)
    return us, jp


def cik_map(tickers):
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    want = {t.upper() for t in tickers}
    m = {}
    for v in j.values():
        tk = v["ticker"].upper()
        if tk in want:
            m[tk] = str(v["cik_str"]).zfill(10)
    return m


def main():
    days = 7
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    since = (date.today() - timedelta(days=days)).isoformat()

    us, jp = kanshi_us()
    m = cik_map(us)
    missing = [t for t in us if t.upper() not in m]

    hits, earnings, others, errors, checked = [], [], [], [], 0
    for t in us:
        cik = m.get(t.upper())
        if not cik:
            continue
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            rec = sub.get("filings", {}).get("recent", {})
            forms = rec.get("form", []); dates = rec.get("filingDate", [])
            items = rec.get("items", []); accn = rec.get("accessionNumber", [])
            docs  = rec.get("primaryDocument", [])
            checked += 1
            for i, f in enumerate(forms):
                if f not in ("8-K", "8-K/A"):
                    continue
                if i >= len(dates) or dates[i] < since:
                    continue
                its = [x.strip() for x in (items[i] if i < len(items) else "").split(",") if x.strip()]
                flags = [f"Item {x}: {ALERT_ITEMS[x]}" for x in its if x in ALERT_ITEMS]
                a = (accn[i] if i < len(accn) else "").replace("-", "")
                url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a}/{docs[i]}"
                       if a and i < len(docs) and docs[i] else "")
                row = {"t": t, "form": f, "date": dates[i], "items": its, "flags": flags, "url": url}
                if flags:
                    hits.append(row)
                elif "2.02" in its:
                    earnings.append(row)   # 決算発表(2.02)は警報でなく「決算イベント」として別置き（門のイベントタブが表示）
                else:
                    others.append(row)     # 1.01契約/7.01RegFD/8.01その他等——警報ではないが記録は残す
        except Exception as e:
            # 取得失敗は失敗として書く。黙って飛ばすと「監視した」顔をする（ルール7の親戚: 欠測を健全と読むな）
            errors.append({"t": t, "err": str(e)[:200]})

    out = {
        "asof": date.today().isoformat(),
        "window_days": days,
        "checked_us": checked,
        "alerts": sorted(hits, key=lambda x: (x["date"], x["t"]), reverse=True),
        "earnings": sorted(earnings, key=lambda x: (x["date"], x["t"]), reverse=True),
        "others": sorted(others, key=lambda x: (x["date"], x["t"]), reverse=True),
        "errors": errors,
        "cik_unresolved": missing,
        "not_covered_jp": {"tickers": jp,
                           "why": "EDINET APIは鍵(EDINET_API_KEY)が必要で本経路では読めない。日本株のイベント監視は未整備の穴＝kessan_check_jp.pyの制約と同根。鍵が用意でき次第ここに統合する"},
        "note": "判定には使わない。alertsが立った銘柄は門2再審査（依頼文）へ回す。四半期点検の隙間を埋める気づきの層であり、株価は見ない",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"8-K監視: {checked}社を走査（窓{days}日）→ 警報 {len(hits)}件 / 決算発表 {len(earnings)}件 / その他8-K {len(others)}件 / 取得失敗 {len(errors)}件 / CIK不明 {len(missing)}件 / 日本株{len(jp)}社は対象外（明示）")
    for h in hits:
        print(f"  ⚠ {h['t']} {h['date']} {'; '.join(h['flags'])}")
    if errors:
        print("  取得失敗:", ", ".join(e["t"] for e in errors))
    print(f"→ {os.path.relpath(OUT, BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
