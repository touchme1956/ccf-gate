#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/recalc_roic.py — SEC companyfacts から ROIC の分母を機械的に組み直す（2026-07-29新設）

なぜ道具にしたか:
  audit_roic.py が出す「要検算」リストを人（審査官）が1社ずつ10-Kを読んで潰していたが、
  **判定に必要なのは実額6つ（営業利益・税引前・法人税等・自己資本・有利子負債・のれん・無形）だけ**で、
  これは companyfacts から機械的に取れる。読解が要るのは「タグが見つからないとき」に限られる。
  そこで機械で取れる分は機械で取り、**取れなかった項目を明示して人へ回す**形にした。

出力するもの（判定はしない・材料を出すだけ）:
  ・NOPAT / 自己資本 / 有利子負債 / のれん / 無形 の実額
  ・IC(のれん除外) と **IC/自己資本**（＝2026-07-29に確立した本当の判別子）
  ・roic(のれん除外) / roicg(のれん込み) / nde の再計算値と、パック現行値との差
  ・5年系列と最大÷最小（桁で振れるかを見る）
  ・**取れなかったタグの一覧**——ここが空でなければ人が10-Kを読む必要がある

【この道具の限界——判定は自動化できない（2026-07-29に5回の反証を経て確定）】
  自動判定の規則を作ろうとするたびに、どちらかの向きに誤検出が出た:
    ・「自己資本が負→算出不能」→ ORLY/BKNG/NATH/FICO/IHG/GLXZ は**ICは正**（負債が上回る）
    ・「IC/自己資本の振れ→不安定」→ UI は IC自体は安定で、自己資本が小さい年に比が暴れただけ
    ・「IC自体の振れ→不安定」→ NVDA の5.2倍は **事業の成長**（IC 27B→142B）であって縮退ではない
    ・「IC系列の符号反転→算出不能」→ MCO は過去に負の年があるが当期は自己資本の69%で健全
  **一義的に言えるのは「当期のICが0以下なら定義上算出できない」ことだけ。**
  それ以外は材料を出すに留め、判定は人が下す。この道具は作業を減らすためのもので、
  判断を代行するものではない。

判定線（HEI/SPGI/RELXで確立・audit_roic.pyの頭注と同じ）:
  IC が負 → 定義上算出不能。IC が自己資本の2割未満、または5年系列が2倍超に振れる → 識別力なし。
  いずれも roic を null 化し、経済実態は roicg で評価する。
  **IC が健全なら60%超でもそれが実測**（MA 131.0 / MCO 93.7 / NVDA 78.1 の前例）。

使い方:
  python3 night/recalc_roic.py MANH PH FTNT      指定銘柄
  python3 night/recalc_roic.py --list-file x.txt ファイルから
出力: 画面の表 + out/roic_recalc.json（後段で適用するための材料）
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com"}

# hachimon_fetch.py と同じタグ集合（2026-07-29に拡張したもの）。二重実装を作らないため揃える
TAGS = {
    "op":    ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "pre":   ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
              "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
              "ProfitLossBeforeTax"],
    "tax":   ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "eq":    ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
              "Equity", "EquityAttributableToOwnersOfParent"],
    "debtL": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations",
              "DebtAndCapitalLeaseObligations", "LongTermNotesPayable", "ConvertibleLongTermNotesPayable",
              "NoncurrentBorrowings", "Borrowings"],
    "debtS": ["LongTermDebtCurrent", "DebtCurrent", "LinesOfCreditCurrent", "CommercialPaper",
              "ConvertibleNotesPayableCurrent", "ConvertibleNotesPayable", "NotesPayableCurrent",
              "CurrentBorrowings", "ShortTermBorrowings"],
    "gw":    ["Goodwill"],
    # IFRS勢(20-F)は us-gaap のタグを持たない。RELXで実測: 無形が取れず **0として扱われ**、
    #   IC が過大→roic 132.4 が「縮退なし」に見えていた。**自分で「欠測をゼロと読む」をやっていた**。
    #   IFRS名を並べたうえで、それでも取れない年は下で算出不能として扱う。
    "intan": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet",
              "IntangibleAssetsOtherThanGoodwill", "OtherIntangibleAssetsNet"],
    "cash":  ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "dep":   ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
              "DepreciationAmortizationAndAccretionNet"],
}


def get(url, tries=3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=60).read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def cik_map():
    d = get("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in d.values()}


def series(facts, keys):
    """年次(10-K/20-F)の値を {fy: value} で返す。**最初に当たったタグを採る**——
    タグの優先順は TAGS の並び順が意味を持つ（無形は総額タグを先頭に置いてある）。"""
    # 【2026-08-03 是正】初版は「候補の先頭でデータがあるもの」を無条件に採っていた。
    #   実害: ADBE の debtL で **LongTermDebtNoncurrent が2009年で途切れている**のに先頭なので選ばれ、
    #   FY2025 が系列に無い → `.get(y) or 0` で **debt=0** → IC が自己資本−のれん−無形へ縮退し
    #   IC=−1,729百万$（自己資本の−15%）＝「算出不能」と出た。実際の負債は LongTermDebt に
    #   **6,210百万$** があり、正しい IC は 4,481百万$（自己資本の38.6%）で健全＝パックの roic 158.6 が正しく、
    #   **検査器のほうが壊れていた**。CLAUDE.md が BR（売上タグがASC606改称で2017年止まり）で
    #   記録している「候補タグの先頭を無条件採用」とまったく同じ事故を、その検査器自身がやっていた。
    # 規約どおりに直す: **最新年に届く候補の中で、keysの並び＝意味の優先順が最も高いもの**を主系列にする。
    #   （単純に「最新年がいちばん新しいタグ」を採ると意味の違うタグへ黙って乗り換える＝BKNGのeq事故）
    cands = []
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        for pri, k in enumerate(keys):
            if k not in d:
                continue
            units = d[k]["units"]
            u = max(units, key=lambda x: len(units[x]))
            out = {}
            for row in units[u]:
                if not str(row.get("form", "")).startswith(("10-K", "20-F")):
                    continue
                fy = row.get("fy")
                if fy is None:
                    continue
                s, e = row.get("start"), row.get("end")
                if s and e:                      # 期間もの＝年次(300日超)のみ
                    from datetime import date
                    try:
                        y0 = date.fromisoformat(s); y1 = date.fromisoformat(e)
                        if (y1 - y0).days < 300:
                            continue
                    except Exception:
                        continue
                out[fy] = row["val"]
            if out:
                cands.append((pri, max(out), out, f"{ns}:{k}"))
    if not cands:
        return {}, None
    newest = max(c[1] for c in cands)
    live = [c for c in cands if c[1] >= newest - 1] or cands
    live.sort(key=lambda c: (c[0], -c[1]))
    return live[0][2], live[0][3]


def one(t, cm):
    cik = cm.get(t.upper())
    if not cik:
        return {"t": t, "err": "CIK不明（SECのticker一覧に無い）"}
    try:
        facts = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception as e:
        return {"t": t, "err": f"companyfacts取得不可({type(e).__name__})"}
    S, used, miss = {}, {}, []
    for k, keys in TAGS.items():
        S[k], used[k] = series(facts, keys)
        if not S[k]:
            miss.append(k)
    yrs = sorted(set(S["op"]) & set(S["eq"]))[-5:]
    rows = []
    for y in yrs:
        op = S["op"].get(y)
        pre, tax = S["pre"].get(y), S["tax"].get(y)
        eq = S["eq"].get(y)
        if op is None or eq is None:
            continue
        rate = (tax / pre) if (pre and tax is not None and pre > 0) else None
        rate = min(max(rate, 0.0), 0.5) if rate is not None else 0.21   # 取れない年は米国法定21%
        nopat = op * (1 - rate)
        debt = (S["debtL"].get(y) or 0) + (S["debtS"].get(y) or 0)
        has_debt = (y in S["debtL"]) or (y in S["debtS"])
        gw, intan = (S["gw"].get(y) or 0), (S["intan"].get(y) or 0)
        # 「タグが無い」と「値が0」を区別する（絶対のルール7）。無形タグが1つも当たらない会社で
        #   intan=0 と置くと IC が過大になり、縮退している会社が「健全」に見える
        has_gw, has_intan = (y in S["gw"]), (y in S["intan"])
        ic = eq + debt - gw - intan
        icg = eq + debt
        rows.append({"fy": y, "op": op, "nopat": round(nopat), "eq": eq, "debt": debt,
                     "has_debt": has_debt, "has_gw": has_gw, "has_intan": has_intan,
                     "gw": gw, "intan": intan, "ic": ic,
                     "roic": (nopat / ic * 100) if ic > 0 else None,
                     "roicg": (nopat / icg * 100) if icg > 0 else None,
                     "ic_eq": (ic / eq * 100) if eq else None})
    r = {"t": t, "cik": cik, "years": rows, "missing_tags": miss, "tags_used": used}
    # **振れは分母で見る。** roic の振れは分子（利益）の変化でも起きるので判定に使えない。
    #   実測NVDA: roic 15.6→86.4(5.5倍)だが IC/自己資本は90-122%で完全に安定＝縮退ではなく
    #   利益が伸びただけ。人の検算も「縮退なし・採用」だった。分母の安定性だけを見る。
    # 振れの判定も自己資本が正の年だけで行う（負の年の比率は意味を持たない）
    # **振れは IC そのもので見る。** IC/自己資本 の比は自己資本が小さい年に分母側で暴れるだけで、
    #   分母の不安定さを表さない（実測UI: IC/自己資本が131倍に振れたが IC自体は396-956百万$の
    #   2.4倍で安定。自己資本が2.7百万→−383百万→668百万と動いただけだった）。
    live = [x for x in rows if x["ic"] > 0]
    if live:
        v = [x["ic"] for x in live]
        r["ic_swing"] = max(v) / min(v)
        r["roic_swing"] = (lambda w: (max(w) / min(w)) if w and min(w) > 0 else None)(
            [x["roic"] for x in rows if x["roic"] is not None])
    # **IC系列の符号反転**——年によってICが正負を行き来する会社は、分母が「資本」ではなく
    #   「自己資本の負値を負債が埋めた残差」になっている。人の検算がDELL/OTISをnull化した理由がこれ
    #   （DELL: −1,962/+322/−1,634/−1,023/+4,953 ／ OTIS: +1,562/−38/+51/+1,617/+570）。
    ics = [x["ic"] for x in rows]
    r["ic_sign_flip"] = bool(ics) and any(v > 0 for v in ics) and any(v <= 0 for v in ics)
    if rows:
        last = rows[-1]
        ebitda = (last["op"] or 0) + (S["dep"].get(last["fy"]) or 0)
        cash = S["cash"].get(last["fy"]) or 0
        r["nde"] = round((last["debt"] - cash) / ebitda, 2) if ebitda else None
        r["last"] = last
    return r


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--list-file" in sys.argv:
        args = open(sys.argv[sys.argv.index("--list-file") + 1], encoding="utf-8").read().split()
    if not args:
        print("銘柄を指定せよ")
        return 1
    cm = cik_map()
    out = {}
    print(f"{'銘柄':<6}{'roic現行':>9}{'roic実測':>9}{'roicg実測':>10}{'IC/自己資本':>11}"
          f"{'IC振れ':>8}{'nde実測':>8}  判定材料")
    print("-" * 108)
    for t in args:
        r = one(t, cm)
        out[t] = r
        time.sleep(0.15)                        # SEC 10req/s
        if r.get("err"):
            print(f"{t:<6}  {r['err']}")
            continue
        try:
            cur = json.load(open(f"out/{t}_gate_pack.json", encoding="utf-8")).get("roic")
        except Exception:
            cur = None
        L = r.get("last")
        if not L:
            print(f"{t:<6}  年次系列を組めず（欠落タグ: {','.join(r['missing_tags']) or '—'}）")
            continue
        # 2026-07-29 判定規則の是正: **一次判定は IC の符号**であって自己資本の符号ではない。
        #   自己資本が負でも、負債が |自己資本|+のれん+無形 を上回れば IC は正で ROIC は算出できる
        #   （実測: ORLY 自己資本−763百万$だが IC=+4,234百万$ / BKNG −5,578→+9,571 /
        #    NATH −14→+33 / FICO −1,746→+527 / IHG −2,736→+1,130 / GLXZ −17→+21）。
        #   IC/自己資本 という比率は自己資本が負のとき意味を持たないので、その場合は使わない。
        #   人の検算で null 化した DELL/OTIS は「自己資本が負」ではなく「**IC自体が負・符号反転**」が理由だった。
        ic_eq = L["ic_eq"] if L["eq"] > 0 else None
        note = []
        if not L["has_debt"]:
            note.append("⚠有利子負債タグ不在")
        if not L["has_intan"]:
            note.append("⚠**無形タグ不在→0として計算している**（ICが過大の恐れ・要10-K確認）")
        if not L["has_gw"]:
            note.append("⚠のれんタグ不在（のれん0の会社なら正常）")
        if L["ic"] <= 0:
            note.append("**ICが負またはゼロ**→定義上算出不能")
        elif ic_eq is None:
            # 自己資本が負のときは |自己資本| を基準に縮退を測る。ICが|自己資本|のごく一部なら、
            #   それは資本ではなく「負債が埋めた残差」（実測OTIS: IC=311百万 vs |自己資本|5,392百万=5.8%）
            ratio = L["ic"] / abs(L["eq"]) * 100 if L["eq"] else None
            if ratio is not None and ratio < 20:
                note.append(f"自己資本が負({L['eq']:,})でICは|自己資本|の{ratio:.0f}%しかない"
                            f"＝資本ではなく**負債が埋めた残差**→算出不能")
            else:
                note.append(f"自己資本が負({L['eq']:,})だがICは正({L['ic']:,}・|自己資本|の"
                            f"{ratio:.0f}%)＝**自己株買いによる資本構成**。算出は可能")
        elif ic_eq < 20:
            note.append(f"ICが自己資本の{ic_eq:.0f}%→縮退・算出不能")
        # 過去年の符号反転は**判定に使わない**（参考表示のみ）。資本構成が変わった会社
        #   （買収・自己株買い・分社）では過去にICが負の年があっても、当期の分母が健全なら
        #   ROICは算出できる。実測MCO: 過去年に負の年があるがFY2025はIC=2,814百万$＝自己資本の
        #   69%で健全、人の検算も「縮退なし・採用」だった。
        if r.get("ic_sign_flip"):
            note.append("(参考)過去にICが負の年あり——資本構成の変化。当期が健全なら算出可")
        # 振れの大きさは**判定に使わない**（参考表示のみ）。ICが5年で何倍になったかは
        #   「分母が不安定」でも「事業が成長した」でも同じ数字になり、両者を区別できない。
        #   実測NVDA: IC 27,006→141,623百万$の5.2倍は**成長**であって縮退ではなく、
        #   人の検算も「縮退なし・採用」だった。不安定さは符号反転(上)で捉える。
        sw = r.get("ic_swing")
        if not note:
            note.append("縮退なし＝実測を採用してよい")
        print(f"{t:<6}{str(cur):>9}{(('%.1f' % L['roic']) if L['roic'] else '—'):>9}"
              f"{(('%.1f' % L['roicg']) if L['roicg'] else '—'):>10}"
              f"{(('%.0f%%' % ic_eq) if ic_eq is not None else '—'):>11}"
              f"{(('%.1f倍' % sw) if sw else '—'):>8}"
              f"{str(r.get('nde')):>8}  {' / '.join(note)}")
    json.dump(out, open("out/roic_recalc.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n→ out/roic_recalc.json（実額・5年系列・使用タグ・欠落タグ）")
    print("※これは**材料**であって判定ではない。欠落タグがある社は10-K本文を人が読む必要がある。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
