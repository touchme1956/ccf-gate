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

日本株（2026-08-04追加）: 環境変数 EDINET_API_KEY があれば EDINET API v2 の日付別提出一覧を走査し、
  **臨時報告書**（8-Kの相当物＝役員異動・重要事象）と**訂正報告書**を警報に、
  有報・四半期・半期報告書の新規提出を「決算・報告イベント」に立てる。
  鍵が無ければ対象外＝穴のまま。出力にその旨を明示する——
  黙って対象外にすると「監視されている」顔をする（kessan_check の偽健全と同型の事故になる）。
  鍵は https://api.edinet-fsa.go.jp/ で無料登録し、GitHub Secrets の EDINET_API_KEY に置く。

使い方:
  python3 night/watch_events.py            直近7日窓（日次CI用。休日またぎを吸収）
  python3 night/watch_events.py --days 30  窓を広げる（初回・停止後の追いつき）
出力: out/events_watch.json（ヒット・対象外・取得失敗を全部書く。失敗を「異常なし」と書かない）
"""
import json, os, re, sys, time, urllib.request
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
    # ★2026-08-20新設。**理由も書かずに抜けていた**——2.02 は「四半期点検の領分だから警報にしない」と
    #   明示的に外してあるのに、4.01 はどこにも書かれていなかった＝意図的な除外ではなく取りこぼし。
    #   実害を踏んで足している: **RMD（保有銘柄）の 2026-08-17 の 8-K は items=[4.01,5.02,7.01,9.01]** で、
    #   **32年つづいた監査人 KPMG を解任して PwC へ替えた**のに、警報に立ったのは 5.02（取締役の退任）だけだった。
    #   ⇒ 監査人の交代という、この日いちばん重い事実が**警報の言葉に一度も現れなかった**。
    #   【重さは本文で分かれる】8-K は Reg S-K 304 により **disagreement と reportable event の有無を
    #   必ず述べる義務がある**ので、原本を開けば機械的に読み分けられる——
    #     ・disagreement あり／reportable event あり → **極めて重い**（門の「誠」そのもの）
    #     ・どちらも無し → 通常のローテーション（RMD がこれ。意見は無限定・競争入札の結果・後任は Big4）
    #   だからここでは**警報に立てるが断定はしない**。言葉に「有無を原本で確かめよ」と書いて人を原本へ送る
    #   （FPI_ALERT が「語で拾うのは項目番号より弱いので警報の言葉も弱くする」と同じ作法）。
    #   【鳴りすぎないことを先に測った】直近の窓で 4.01 は **1件だけ**（RMD）＝
    #   「鳴りすぎる警報は鳴らないのと同じ」には当たらない。
    "4.01": "監査人の交代——**disagreement / reportable event の有無を原本(Item 4.01(a))で確かめよ**。無ければ通常のローテーション、有れば誠(会計)",
    "5.02": "退任——取締役・主要役員の異動",
}

# ── 外国私募発行体(FPI)の 6-K（2026-08-10新設）──────────────────────────────
# 【なぜ要るか】この道具は `if f not in ("8-K","8-K/A"): continue` で 8-K だけを見ていた。
#   ところが **20-F を出す外国私募発行体は 8-K を一本も出さない**——重要事象は 6-K で出す。
#   実測: ASML（**🟢投下可**）/ SAP / RELX / RACE / AZN / BUD / NVO / GSK / INFY / TSM …
#   彼らは監視リストに載っているのに **原理的にイベントが立たない**のに、
#   日本株の not_covered_jp と違って**穴の明示すら無く** `checked_us=38 / errors=0` と出る
#   ＝**「監視した」顔をする**。ルール7の親戚（欠測を健全と読むな）。
#
# 【どう扱うか】6-K には Item 番号が無いので ALERT_ITEMS を当てられない。
#   代わりに **8-K の Item が意味しているのと同じ事象を語で拾う**。
#   語で拾うのは項目番号より弱いので、**警報の言葉も弱くする**（"6-K語ヒット"）——
#   強さを偽らないのがこの台帳の作法。ヒットしない 6-K も件数として必ず出す
#   （「見ていない」と「見て何も無い」を区別する）。
FPI_FORMS = ("6-K", "6-K/A")
#
# ⚠**語は締めてある。** 初版は `\bimpairment\b` や `\bresign\w*` の素の語で拾ったところ、
#   ASML・RELX・SAP の**半期報告が全部鳴った**——IFRSの中間財務諸表は会計方針として
#   「impairment of financial assets」を必ず書き、ガバナンス節は必ず「resignation」に触れる。
#   **鳴りすぎる警報は鳴らないのと同じ**なので、
#   「**事象が起きた**」と読める言い回し（金額・実行済みの動詞）だけを拾う形へ締めた。
FPI_ALERT = [
    (r"impairment (?:charge|loss(?:es)?) of\b|recognis?ed an impairment|"
     r"goodwill impairment (?:charge|loss)|wrote (?:down|off)\b|"
     r"impairment (?:charge|loss)[^.]{0,60}?(?:million|billion|€|\$|£)",
     "減損——8-K Item 2.06 相当"),
    (r"non[- ]reliance|should no longer be relied upon|"
     r"restatement of (?:our |the |its )?(?:previously issued |prior )?(?:consolidated )?financial|"
     r"material weakness in (?:our |the )?internal control", "誠(会計)——同 4.02 相当"),
    (r"has (?:resigned|stepped down)|will (?:resign|step down)|"
     r"resignation of (?:the |our |mr|ms|dr)|(?:ceo|cfo|chief executive|chief financial officer)"
     r"[^.]{0,60}?(?:to step down|will leave|departure)", "退任——同 5.02 相当"),
    (r"\bfiled for bankruptcy|chapter 11|insolvency proceedings|"
     r"\bplaced into (?:administration|receivership)", "誠(存続)——同 1.03 相当"),
    (r"notice of (?:non[- ]?compliance|delisting)|"
     r"listing (?:standard|rule)s?[^.]{0,40}?(?:non[- ]?compliance|deficien)", "誠——同 3.01 相当"),
    (r"profit warning|(?:cut|lowered|reduced|withdrew|withdrawn)[^.]{0,40}?(?:guidance|outlook)|"
     r"guidance[^.]{0,30}?(?:cut|lowered|reduced|withdrawn)",
     "業績下方——8-Kに対応項目は無いが門2再審査の気づき"),
]


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


def edinet_scan(jp, days, hits, earnings, others, errors):
    """EDINET日付別一覧から監視中の日本株の新規提出を拾う。鍵が無ければ None（=対象外の穴）"""
    key = os.environ.get("EDINET_API_KEY", "").strip()
    if not key or not jp:
        return None
    want = {t[:4] for t in jp}          # documents.json の secCode は5桁（末尾0）
    n_days_ok = 0
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        try:
            j = json.loads(get(f"https://api.edinet-fsa.go.jp/api/v2/documents.json?date={d}&type=2&Subscription-Key={key}"))
            n_days_ok += 1
        except Exception as e:
            errors.append({"t": f"EDINET:{d}", "err": str(e)[:120]})
            continue
        for doc in (j.get("results") or []):
            sec = str(doc.get("secCode") or "")
            if sec[:4] not in want:
                continue
            desc = str(doc.get("docDescription") or "")
            row = {"t": sec[:4], "form": desc[:60], "date": doc.get("submitDateTime", d)[:10],
                   "items": [], "flags": [], "url": "",
                   "docID": doc.get("docID")}
            if "臨時報告書" in desc:
                row["flags"] = ["臨時報告書＝重要事象（役員異動・訂正等）の可能性——原本を読む(EDINETでdocID検索)"]
                hits.append(row)
            elif "訂正" in desc:
                row["flags"] = ["訂正報告書＝過年度の記載訂正の可能性——原本を読む"]
                hits.append(row)
            elif any(x in desc for x in ("有価証券報告書", "四半期報告書", "半期報告書")):
                earnings.append(row)     # 決算・報告イベント（警報ではない）
            else:
                others.append(row)       # 大量保有等——記録のみ
    return {"covered": True, "days_scanned": n_days_ok, "tickers": sorted(want)}


def main():
    days = 7
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    since = (date.today() - timedelta(days=days)).isoformat()

    us, jp = kanshi_us()
    m = cik_map(us)
    missing = [t for t in us if t.upper() not in m]

    hits, earnings, others, errors, checked = [], [], [], [], 0
    fpi_seen, fpi_counts = [], {}   # 6-K経路の社（外国私募発行体）
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
            # FPI判定: 窓に関係なく **recent に 8-K が一本も無く 20-F/40-F がある**なら
            #   8-K経路では原理的に何も立たない社（＝6-K経路で見る）。
            is_fpi = ("8-K" not in forms) and any(x in forms for x in ("20-F", "40-F", "6-K"))
            if is_fpi:
                fpi_seen.append(t)
                n6 = 0
                for i, f in enumerate(forms):
                    if f not in FPI_FORMS or i >= len(dates) or dates[i] < since:
                        continue
                    n6 += 1
                    a = (accn[i] if i < len(accn) else "").replace("-", "")
                    url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a}/{docs[i]}"
                           if a and i < len(docs) and docs[i] else "")
                    # ⚠**6-K の primaryDocument は表紙**で、中身は添付(EX-99)に在る。
                    #   実測 RACE 2026-07-30: 表紙 16KB に対し本体 ferrarinvinterimreport 1.77MB。
                    #   表紙だけ舐めると**語が原理的にヒットしない＝鳴らない警報**になる
                    #   （この台帳が何度も潰してきた型）。filing の index.json を引いて
                    #   **中身の大きい文書から**読む。
                    txt = ""
                    if a:
                        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a}/"
                        try:
                            idx = json.loads(get(base + "index.json"))
                            it = [x for x in (idx.get("directory", {}).get("item") or [])
                                  if str(x.get("name", "")).lower().endswith((".htm", ".html", ".txt"))
                                  and "index" not in str(x.get("name", "")).lower()]
                            it.sort(key=lambda x: -int(x.get("size") or 0))
                            for x in it[:2]:
                                txt += re.sub(r"<[^>]+>", " ", get(base + x["name"])[:800000])
                        except Exception as e:
                            errors.append({"t": t, "err": f"6-K本文の取得失敗 {dates[i]}: {str(e)[:120]}"})
                    flags = [lab for pat, lab in FPI_ALERT if re.search(pat, txt, re.I)]
                    row = {"t": t, "form": f, "date": dates[i], "items": [],
                           "flags": [f"6-K語ヒット｜{x}" for x in flags], "url": url}
                    (hits if flags else others).append(row)
                fpi_counts[t] = n6
                continue
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

    jp_cov = edinet_scan(jp, days, hits, earnings, others, errors)

    # ── 未完了の重大事象の「見落としの網」（v9.9.128・2026-08-10）────────────────
    #   【なぜ要るか】第四の関門の `_meta.pending`（合意済み・未完了の買収等）は**審査官が書く**欄で、
    #   門ができるのは「書かれていたら必ず効かせる」ところまで。書き漏らすと関門が眠る。
    #   そこで **8-K の Item 1.01(重要な契約の締結) / 1.02(同 解除) / 8.01(その他)** を
    #   **判定圏(Ω72+)に絞って作業リストに出す**——M&Aの合意・解除・判決はこの3つに載る。
    #   【なぜ警報に格上げしないか】8.01 は雑多で、格上げすると「鳴りすぎる警報は鳴らないのと同じ」を
    #   自分で作ることになる（実測: 今日の others は KLAC/APH の 8.01 が2件で、どちらも M&A ではない）。
    #   だから **alerts には入れず、todo として別に出す**。判定には一切使わない（門の第四の関門は
    #   あくまで `_meta.pending` を読む）——これは**人が pending を書き漏らしていないかの点検**。
    TODO_ITEMS = {"1.01": "重要な契約の締結", "1.02": "重要な契約の解除", "8.01": "その他の事象"}
    q72 = set()
    try:
        for r in json.load(open(os.path.join(os.path.dirname(OUT), "score_all.json"), encoding="utf-8")):
            if (r.get("s") or 0) >= 72:
                q72.add(r["t"])
    except Exception:
        q72 = set()      # 取れなければ空＝この網は眠るだけ（無いことを「異常なし」と偽らない・ルール7）
    pending_todo = []
    for r in others:
        if r["t"] not in q72:
            continue
        hit = [f"Item {x}: {TODO_ITEMS[x]}" for x in r.get("items", []) if x in TODO_ITEMS]
        if hit:
            pending_todo.append(dict(r, todo=hit))

    out = {
        "asof": date.today().isoformat(),
        "window_days": days,
        "checked_us": checked,
        # 2026-08-10: **8-K経路と6-K経路を分けて出す。**「38社を見た」の中身が
        #   実は「8-K経路28社＋原理的に何も立たない10社」だったのを可視化する。
        "fpi_6k": {"tickers": sorted(fpi_seen), "filings_in_window": fpi_counts,
                   "note": "外国私募発行体は8-Kを出さず6-Kで重要事象を報じる。"
                           "6-KにはItem番号が無いので、8-KのItemが意味するのと同じ事象を"
                           "**語で**拾う（項目番号より弱いので警報の言葉も『6-K語ヒット』と弱くする）。"
                           "ヒット0でも件数は出す＝『見ていない』と『見て何も無い』を区別する。"} if fpi_seen else None,
        "alerts": sorted(hits, key=lambda x: (x["date"], x["t"]), reverse=True),
        "earnings": sorted(earnings, key=lambda x: (x["date"], x["t"]), reverse=True),
        "others": sorted(others, key=lambda x: (x["date"], x["t"]), reverse=True),
        "pending_todo": sorted(pending_todo, key=lambda x: (x["date"], x["t"]), reverse=True),
        "pending_todo_note": ("判定圏(Ω72+)の Item 1.01/1.02/8.01。**警報ではなく作業リスト**——"
                              "M&Aの合意・解除・判決はここに載るので、読んで該当すれば "
                              "パックの _meta.pending へ書く（night/audit_pending.py が関門で読む）。"
                              "8.01は雑多なので警報には格上げしない＝鳴りすぎる警報は鳴らないのと同じ"),
        "errors": errors,
        "cik_unresolved": missing,
        "jp": jp_cov if jp_cov else None,
        "not_covered_jp": None if jp_cov else {
            "tickers": jp,
            "why": ("EDINET_API_KEY 未設定＝日本株のイベント監視は穴のまま。"
                    "鍵は https://api.edinet-fsa.go.jp/ で無料登録し、GitHub Secrets の EDINET_API_KEY に置くと"
                    "臨時報告書(8-K相当)・訂正・有報/四半期の提出が自動で入る")},
        "note": "判定には使わない。alertsが立った銘柄は門2再審査（依頼文）へ回す。四半期点検の隙間を埋める気づきの層であり、株価は見ない",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # 空書き込みの検問（audit_stale_bs:243 と同じ言葉。v9.9.140）
    #   ⚠**1社も走査できていないのに書き換えない**。SECが落ちている日に上書きすると、
    #     alerts=[] が「見て何も無かった」に見える＝この道具が塞いだはずの穴を自分で作る。
    #   errors が出ていること自体は正常（個別社の取得失敗は errors に載せて続行する）ので、
    #   裁くのは **checked（実際に走査できた社数）が 0 かどうか**だけ。
    if checked == 0 and not (jp_cov and jp_cov.get("tickers")):
        print("⚠ 1社も走査できていない（SEC/EDINETが落ちている等）。"
              "**out/events_watch.json を書き換えない**——空の alerts は『見て何も無い』ではない")
        return 1
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    jp_msg = (f"日本株{len(jp_cov['tickers'])}社をEDINETで走査" if jp_cov
              else f"日本株{len(jp)}社は対象外（EDINET_API_KEY未設定＝明示）")
    print(f"イベント監視: 米国{checked}社（うち6-K経路{len(fpi_seen)}社・窓{days}日）＋{jp_msg} → 警報 {len(hits)}件 / 決算・報告 {len(earnings)}件 / その他 {len(others)}件 / 取得失敗 {len(errors)}件 / CIK不明 {len(missing)}件")
    for h in hits:
        print(f"  ⚠ {h['t']} {h['date']} {'; '.join(h['flags'])}")
    if pending_todo:
        print(f"\n  📋 未完了の重大事象の点検（判定圏 {len(pending_todo)}件・**警報ではなく作業リスト**）")
        print(f"     読んで M&A の合意・解除・判決なら パックの _meta.pending へ書く（audit_pending.py が関門で読む）")
        for r in pending_todo:
            print(f"     {r['t']:<6}{r['date']}  {'; '.join(r['todo'])}  {r['url']}")
    if errors:
        print("  取得失敗:", ", ".join(e["t"] for e in errors))
    print(f"→ {os.path.relpath(OUT, BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
