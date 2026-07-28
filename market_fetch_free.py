#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_fetch_free.py — 市場データを「鍵なし・上限なし」で採る（2026-07-28新設）

なぜ作ったか:
  market_fetch.py は px/per を Alpha Vantage の無料鍵に頼っており、**日次25リクエスト**で
  止まる。実測で28社中4社しか採れず、残り23社は門X判定不能のまま＝「投下可ゼロ」が
  規律なのか欠測なのか区別できない状態を生んでいた。運用に耐えないので置き換える。

データ源（どちらも鍵不要）:
  ・株価 px      : Yahoo Finance chart API（regularMarketPrice）
  ・それ以外全部 : SEC companyfacts API（EPS/株数/配当/自社株買い/BS）
  per  = px ÷ EPS(TTM・希薄化後)      ← 実績ベース。会予は使わない（門のTTM統一規約）
  mcap = px × 発行済株式数(dei)
  shy  = (配当支払 + 自社株買い) ÷ mcap × 100
  evebit, z(Altman Z'') = market_fetch.py と同一定義
  beta = 5年月次で対S&P500の回帰（Yahooの履歴から自前計算）

使い方:
  python3 market_fetch_free.py                 監視リスト(kanshi_list.json)全社
  python3 market_fetch_free.py MSFT ASML KLAC  指定のみ
出力: market_data.json（既存キーを壊さずマージ）
次:   python market_merge.py → 門で再取込 → python x_watch_recalc.py
"""
import json, os, sys, time, datetime, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
import market_fetch as MF          # _get / _cik / _series を再利用（二重実装を作らない）

OUT = "market_data.json"
PER_MIN, PER_MAX = 8.0, 200.0   # 算出PERの常識帯
SHY_MAX = 12.0                  # 純還元の上限目安(超えたらmcap過小を疑う)   # 算出PERの常識帯(外れたら株価源の取り違えを疑う)
YH = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval={}&range={}"
UA = {"User-Agent": "Mozilla/5.0 (compatible; CCF-Omega/1.0)"}


def _yh(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode())


def price(t):
    """現値。Yahooのchart APIは鍵も上限も無い。"""
    try:
        m = _yh(YH.format(t, "1d", "5d"))["chart"]["result"][0]["meta"]
        return float(m["regularMarketPrice"])
    except Exception:
        return None


def monthly_closes(t, rng="5y"):
    try:
        r = _yh(YH.format(t, "1mo", rng))["chart"]["result"][0]
        ts, cl = r["timestamp"], r["indicators"]["quote"][0]["close"]
        return [(a, b) for a, b in zip(ts, cl) if b is not None]
    except Exception:
        return []


def beta_vs_market(t, mkt):
    """5年月次リターンの回帰係数。mktはあらかじめ取った(ts,close)列。"""
    a = monthly_closes(t)
    if len(a) < 24 or len(mkt) < 24:
        return None
    mm = dict(mkt)
    xs, ys = [], []
    for i in range(1, len(a)):
        t0, t1 = a[i - 1][0], a[i][0]
        if t0 not in mm or t1 not in mm or a[i - 1][1] <= 0 or mm[t0] <= 0:
            continue
        ys.append(a[i][1] / a[i - 1][1] - 1)
        xs.append(mm[t1] / mm[t0] - 1)
    n = len(xs)
    if n < 24:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return round(cov / var, 3)


def _flow_pershare(facts, tag):
    """EPS等の per-share 系列。market_fetch._series は単位に'/'を含むUSD/sharesを
       除外するため（絶対額を採る前提の実装）、ここだけ自前で読む。"""
    node = facts.get("us-gaap", {}).get(tag)
    if not node:
        return []
    out = []
    for u, ents in node.get("units", {}).items():
        if "/shares" not in u:
            continue
        for e in ents:
            st, en = e.get("start"), e.get("end")
            if not st or not en:
                continue
            d = (datetime.date.fromisoformat(en) - datetime.date.fromisoformat(st)).days
            out.append((st, en, d, float(e["val"]), e.get("filed", "")))
    return out


def eps_ttm(facts):
    """直近4四半期(80-100日)を重複なく足してTTM EPSを作る。四半期が揃わない時は年次で代替。"""
    rows = _flow_pershare(facts, "EarningsPerShareDiluted") or _flow_pershare(facts, "EarningsPerShareBasic")
    if not rows:
        return None, "EPSタグ無し"
    q = sorted([r for r in rows if 80 <= r[2] <= 100], key=lambda r: r[1], reverse=True)
    picked, cursor = [], None
    for st, en, d, v, fl in q:
        if cursor is None or en <= cursor:
            picked.append(v)
            cursor = st                      # 直前の期首より前に終わる四半期だけ拾う＝重複排除
        if len(picked) == 4:
            break
    if len(picked) == 4:
        return round(sum(picked), 4), "四半期4本の合計"
    ann = sorted([r for r in rows if 330 <= r[2] <= 400], key=lambda r: r[1], reverse=True)
    if ann:
        return round(ann[0][3], 4), f"年次で代替({ann[0][1]})"
    return None, "TTMを構成できない"


def fetch(t, mkt):
    px = price(t)
    r = {"px": px} if px else {}
    note = [] if px else ["株価取得不可"]
    cik = MF._cik(t)
    if not cik:
        return r, "・".join(note + ["CIK不明"])
    try:
        facts = json.loads(MF._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))["facts"]
    except Exception as e:
        return r, "・".join(note + [f"companyfacts不可({e})"])

    # 株数 → mcap
    #   dei:EntityCommonStockSharesOutstanding は表紙の1クラス分しか無いことがあり、
    #   複数株式クラス(MA/GOOGL/META)やADR(TSM)で大幅に過小になる。実測でMAの時価総額が
    #   68.8B(実際は約500B)となり shy が21%という偽の高還元を生んだ。
    #   EPSと整合する「希薄化後加重平均株数」を優先し、deiは代替に落とす。
    sh, sh_src = None, ""
    wa = MF._series(facts, [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")], True)
    if wa:
        sh, sh_src = wa[max(wa)], "希薄化後加重平均"
    if not sh:
        node = facts.get("dei", {}).get("EntityCommonStockSharesOutstanding")
        if node:
            ents = [e for u in node["units"].values() for e in u if e.get("end")]
            if ents:
                sh = float(sorted(ents, key=lambda e: (e["end"], e.get("filed", "")))[-1]["val"])
                sh_src = "dei表紙(複数クラス・ADRで過小の恐れ)"
    if px and sh:
        r["mcap"] = round(px * sh / 1e9, 4)
        note.append(f"株数={sh_src}")

    # per = px ÷ EPS(TTM)
    #   安全弁: 算出perが常識帯を外れたら書かない。株価源の取り違え(別上場・別通貨・
    #   分割未調整)が最も出やすい事故で、per=5.5のような値をそのまま流すと門Xが
    #   偽の「投下可」を点灯させる。誤値より空欄。
    e, how = eps_ttm(facts)
    if px and e and e > 0:
        cand = round(px / e, 2)
        if PER_MIN <= cand <= PER_MAX:
            r["per"] = cand
            note.append(f"EPS_TTM={e}({how})")
        else:
            r["per_suspect"] = cand
            note.append(f"per={cand}が常識帯[{PER_MIN},{PER_MAX}]外＝株価源の取り違えを疑い未記入"
                        f"(px={px}/EPS_TTM={e})。要手動確認")
    elif e is not None and e <= 0:
        note.append(f"EPS_TTM={e}＝赤字のためperは空欄")
    else:
        note.append(how)

    # z / shy / evebit は market_fetch と同一定義
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

    ys = [y for y in ta if y in tl and y in eq and y >= 2024]
    if ys:
        y = max(ys); TA, TL = ta[y], tl[y]
        if TA > 0 and TL > 0 and y in ca and y in cl and y in re_:
            oy = max([x for x in op if abs(x - y) <= 1], default=None)
            if oy:
                r["z"] = round(6.56*(ca[y]-cl[y])/TA + 3.26*re_[y]/TA + 6.72*op[oy]/TA + 1.05*eq[y]/TL, 2)
    mc = r.get("mcap", 0) * 1e9
    if mc and "per_suspect" in r:
        note.append("mcapも同じ株価に依存するためshy/evebitは未記入")
        mc = 0
    if mc:
        fy = max([y for y in op if y >= 2024], default=None)
        if fy:
            if fy in div or fy in bb:
                cand = round((div.get(fy, 0) + bb.get(fy, 0)) / mc * 100, 2)
                # 純還元が二桁%は稀。まず時価総額(=株数)の取り違えを疑う——誤値より空欄
                if cand <= SHY_MAX:
                    r["shy"] = cand
                else:
                    r["shy_suspect"] = cand
                    note.append(f"shy={cand}%が{SHY_MAX}%超＝mcap過小(株数の取り違え)を疑い未記入")
            else:
                note.append("配当・自社株買いのタグが無くshyは空欄(0と断定しない)")
            by = max([y for y in eq if y >= 2024], default=None)
            if by and op[fy] > 0:
                r["evebit"] = round((mc + dL.get(by, 0) + dS.get(by, 0) - cash.get(by, 0) - sti.get(by, 0)) / op[fy], 1)

    b = beta_vs_market(t, mkt)
    if b is not None:
        r["beta"] = b
    return r, "・".join(note)


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

    print("S&P500の月次を取得中(betaの基準)…")
    mkt = monthly_closes("%5EGSPC")
    print(f"  {len(mkt)}ヶ月ぶん\n")

    ok = 0
    for t in tickers:
        try:
            r, note = fetch(t, mkt)
        except Exception as e:
            print(f"{t}: 失敗({e})"); continue
        if r:
            cur = data.get(t) or {}
            cur.update(r); data[t] = cur
            if r.get("px") and r.get("per"): ok += 1
        print(f"{t}: px={r.get('px')} per={r.get('per')} mcap={r.get('mcap')} shy={r.get('shy')} "
              f"evebit={r.get('evebit')} z={r.get('z')} beta={r.get('beta')}" + (f"  ({note})" if note else ""))
        json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)  # 逐次保存
        time.sleep(0.15)                               # SEC 10req/s を守る

    print(f"\n保存 {OUT}: {len(tickers)}社中 px+per揃い {ok}社")
    print("次: python market_merge.py → 門で再取込 → python x_watch_recalc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
