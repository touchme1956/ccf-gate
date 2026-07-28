#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_fetch_sec.py — z / shy / evebit を SEC の companyfacts API から算出する（2026-07-28新設）

背景: market_fetch.py はこの3項目をローカルの companyfacts.zip(1.4GB) から計算するが、
      zipはgitignoreで環境によっては存在しない。SECは銘柄単位のJSON APIも公開しており、
      そちらなら鍵もzipも要らない。定義は market_fetch.py と完全に同じものを再利用する
      （shy=(配当支払+自社株買い)÷時価総額×100 / z=Altman Z'' / evebit=EV÷営業利益）。

なぜ要るか: shy が欠測すると x_watch_recalc が「還元ゼロ」と誤認して開通線を実際より
      遠くに描く（2026-07-28に判定不能へ倒す修正済み）。つまり shy が無いと門Xが動かない。

使い方:
  python3 market_fetch_sec.py                  監視リスト(kanshi_list.json)の全銘柄
  python3 market_fetch_sec.py MSFT ASML KLAC   指定銘柄のみ
  ※時価総額は market_data.json の mcap を使う。無い銘柄は shy/evebit を出せない
    （Alpha Vantage の COMPANY_OVERVIEW から MarketCapitalization を先に入れておくこと）
出力: market_data.json へ z/shy/evebit をマージ（既存の他項目は壊さない）
"""
import json, os, sys, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
OUT = "market_data.json"

# market_fetch.py と同じ定義を再利用する（二重実装を作らない）
sys.path.insert(0, BASE)
import market_fetch as MF


def companyfacts(cik):
    """SECの銘柄単位API。zipの CIK{cik}.json と同じ構造を返す。"""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return json.loads(MF._get(url))["facts"]


def health(t, mcap_b):
    """market_fetch.local_health と同一の計算。データ源だけ zip→API に差し替える。"""
    cik = MF._cik(t)
    if not cik:
        return {}, "CIK不明"
    try:
        facts = companyfacts(cik)
    except Exception as e:
        return {}, f"companyfacts取得不可({e})"

    S, U = MF._series, (lambda x: [("us-gaap", x)])
    op = S(facts, U("OperatingIncomeLoss"), True)
    gp = S(facts, U("GrossProfit"), True)
    cor = S(facts, [("us-gaap", "CostOfRevenue"), ("us-gaap", "CostOfGoodsAndServicesSold")], True)
    rev = S(facts, [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")], True)
    rd = S(facts, U("ResearchAndDevelopmentExpense"), True)
    sga = S(facts, U("SellingGeneralAndAdministrativeExpense"), True)
    for y in list(rev):
        if y not in gp and y in cor: gp[y] = rev[y] - cor[y]
    for y in gp:
        if y not in op and y in rd and y in sga: op[y] = gp[y] - rd[y] - sga[y]
    ca = S(facts, U("AssetsCurrent"), False); cl = S(facts, U("LiabilitiesCurrent"), False)
    re_ = S(facts, U("RetainedEarningsAccumulatedDeficit"), False)
    tl = S(facts, U("Liabilities"), False); ta = S(facts, U("Assets"), False)
    eq = S(facts, U("StockholdersEquity"), False)
    dL = S(facts, [("us-gaap", "LongTermDebtNoncurrent"), ("us-gaap", "LongTermDebt"), ("us-gaap", "DebtAndCapitalLeaseObligations")], False)
    dS = S(facts, [("us-gaap", "LongTermDebtCurrent"), ("us-gaap", "DebtCurrent")], False)
    cash = S(facts, U("CashAndCashEquivalentsAtCarryingValue"), False)
    sti = S(facts, [("us-gaap", "ShortTermInvestments"), ("us-gaap", "MarketableSecuritiesCurrent")], False)
    div = S(facts, [("us-gaap", "PaymentsOfDividends"), ("us-gaap", "PaymentsOfDividendsCommonStock")], True)
    bb = S(facts, [("us-gaap", "PaymentsForRepurchaseOfCommonStock")], True)

    r, notes = {}, []
    ys = [y for y in ta if y in tl and y in eq and y >= 2024]
    if ys:
        y = max(ys); TA, TL = ta[y], tl[y]
        if TA > 0 and TL > 0 and y in ca and y in cl and y in re_:
            oy = max([x for x in op if abs(x - y) <= 1], default=None)
            if oy:
                r["z"] = round(6.56*(ca[y]-cl[y])/TA + 3.26*re_[y]/TA + 6.72*op[oy]/TA + 1.05*eq[y]/TL, 2)
    mc = (mcap_b or 0) * 1e9
    if not mc:
        notes.append("mcap未取得のためshy/evebitは算出不可")
    else:
        fy = max([y for y in op if y >= 2024], default=None)
        if fy:
            d = div.get(fy, 0) + bb.get(fy, 0)
            # 還元が0でも「実測して0」と「タグが無い」は別物。タグが両方無ければ空欄のまま
            if fy in div or fy in bb:
                r["shy"] = round(d / mc * 100, 2)
            else:
                notes.append("配当・自社株買いのタグが無くshyは空欄(0と断定しない)")
            by = max([y for y in eq if y >= 2024], default=None)
            if by and op[fy] > 0:
                r["evebit"] = round((mc + dL.get(by, 0) + dS.get(by, 0) - cash.get(by, 0) - sti.get(by, 0)) / op[fy], 1)
        else:
            notes.append("FY2024以降の営業利益が取れずshy/evebitは算出不可")
    return r, "・".join(notes)


def main():
    args = [a.upper() for a in sys.argv[1:]]
    if args:
        tickers = args
    else:
        try:
            k = json.load(open("kanshi_list.json", encoding="utf-8"))
            tickers = k if isinstance(k, list) else (k.get("list") or k.get("tickers") or [])
        except Exception:
            tickers = []
    tickers = [t for t in tickers if t.isalpha()]      # 日本株(数字コード)はSEC対象外
    if not tickers:
        print("対象銘柄が無い"); return 0

    data = {}
    if os.path.exists(OUT):
        try: data = json.load(open(OUT, encoding="utf-8"))
        except Exception: data = {}

    got = 0
    for t in tickers:
        cur = data.get(t) or {}
        r, note = health(t, cur.get("mcap"))
        if r:
            cur.update(r); data[t] = cur; got += 1
        print(f"{t}: z={r.get('z')} shy={r.get('shy')} evebit={r.get('evebit')}" + (f"  ({note})" if note else ""))
        time.sleep(0.12)                                # SEC 10req/s を守る

    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n保存 {OUT}: {len(tickers)}社中 {got}社に z/shy/evebit を書き込み")
    print("次: python market_merge.py でパックへ充填 → 門で再取込 → python x_watch_recalc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
