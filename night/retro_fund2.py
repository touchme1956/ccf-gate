# night/retro_fund2.py — 未検証のファンダメンタル族の採取（2026-08-12新設）
#
# 目的: 歴史検証の在庫（retro_features2 の19本）に**一度も入っていない**会計の族を採る。
#   偵察（2026-08-12・6班）が word-boundary grep で不在を確認した族だけを実装する:
#     agr1/agr5      総資産成長（Cooper-Gulen-Schill 2008）— この台帳の成長は全部「売上」でBS側は未測定
#     noa_r          純営業資産/前期総資産（Hirshleifer-Hou-Teoh-Zhang 2004）— accruals のストック版
#     lease_r/leasex 隠れ負債（pre-ASC842 のオペレーティングリース）— 門の nde キルは構造的にこれを見逃す
#     sbc_r          株式報酬/売上 — 門は sbc を採点に使っているのに歴史で一度も検証していない
#     age_pp         設備の年齢（累積減価償却÷取得原価）— 維持capexの過小評価
#     gwimp_n/r      のれん減損の履歴 — gwg(買ったか)はあるが「払いすぎを認めたか」は無い
#     restr_n        restructuring の反復 — 報告opmの質
#     cetr/etrgap    現金実効税率と会計実効税率の乖離（Dyreng-Hanlon-Maydew）
#     defrev_gap     契約負債の伸び − 売上の伸び — 唯一「まだ計上していない売上」を映す
#     shr_cagr       希薄化後株数の軌道（1株当たりの複利）— netiss_r は金額ベースでSBC相殺が見えない
#     dso_d/dio_d    運転資本の劣化（Beneish の DSRI 相当）
#     divcut_n       減配の履歴
#
# **判定はしない。** 合否は事前登録した検定器の仕事。ここは採取だけ。
#
# 作法は night/retro_features2.py を **import して再利用**する（二重実装を作らない・v9.9.65）:
#   look-ahead は filed <= {asof}-07-01 ／ 年次は330-400日 ／ 同一(タグ,年)は期限内で最新filed ／
#   インスタントは**その年のFY末日±10日**で照合（年ラベル照合はQ末残高が混入する）／
#   CF活動項目は三値読み（値あり／触れる報告はあるが年次なし＝欠測／一切なし＝0）
#
# 偵察が実測した罠への検問（ここで先回りしたもの）:
#   ・Liabilities は EXPD/ORLY に一件も無い（5社中2社）→ Assets − StockholdersEquity で代替し、
#     どちらを使ったかを noa_src に記録する（黙って0にしない）
#   ・有利子負債は「総額」と「Noncurrent+Current」が同居する → **恒等式が成立する年だけ**構成要素を足す
#     （WIT/IDXX/CELH の二重計上と同じ型を作らない）
#   ・減損タグは「無い＝減損なし」ではない → **のれんを持たない社は0が事実**、持つ社でタグが一度も
#     現れなければ0（報告しない＝計上していない）。持つ社で当該年だけ欠けるのは欠測
#   ・株数は後年の10-Kが分割で遡及修正する → YoY比が 1.5超/0.67未満 の不連続がある社は**系列ごと欠測**
#     （NVDA の dilNet 事故＝+114%/年の希薄化と読んだ型を再現しない）
#   ・税前利益タグは会社ごとに綴りが違う → 候補を並べ、5年合計が正の社だけ ETR を出す
#   ・ASC606 で DeferredRevenue → ContractWithCustomerLiability へ改称 → 両方を候補に置き年ごと先頭一致
#
# 実行: python3 night/retro_fund2.py --asof 2018   → out/retro_fund2_2018.json

import argparse
import datetime
import json
import os
import statistics
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
from retro_features2 import (  # noqa: E402  作法を再利用（二重実装を作らない）
    REV, OP, NI, OCF, d2, flow_maps, flow3, tag_seen, inst_at, cagr, r4,
)

# ---- 追加のタグ候補（偵察が5社×9年で実在を確認した綴りを優先順に）----
ASSETS = ["Assets"]
EQ = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
LIAB = ["Liabilities"]
CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
STI = ["ShortTermInvestments", "AvailableForSaleSecuritiesCurrent", "MarketableSecuritiesCurrent",
       "OtherShortTermInvestments"]
DEBT_TOTAL = ["LongTermDebt", "DebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligations"]
DEBT_NC = ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"]
DEBT_C = ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"]
DEBT_ST = ["ShortTermBorrowings", "OtherShortTermBorrowings", "CommercialPaper"]
GOODWILL = ["Goodwill"]
GWIMP = ["GoodwillImpairmentLoss", "GoodwillAndIntangibleAssetImpairment",
         "ImpairmentOfIntangibleAssetsIncludingGoodwill"]
RESTR = ["RestructuringCharges", "RestructuringSettlementAndImpairmentProvisions",
         "RestructuringCostsAndAssetImpairmentCharges"]
SBC = ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]
DA = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
      "DepreciationAndAmortization"]
PPE_GROSS = ["PropertyPlantAndEquipmentGross"]
ACCDEP = ["AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment"]
LEASE = ["OperatingLeasesFutureMinimumPaymentsDue"]
TAXEXP = ["IncomeTaxExpenseBenefit"]
TAXPAID = ["IncomeTaxesPaidNet", "IncomeTaxesPaid"]
PRETAX = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesAndMinorityInterest",
          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeignAndDomestic"]
DEFREV = ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"]
DEFREV_NC = ["ContractWithCustomerLiabilityNoncurrent", "DeferredRevenueNoncurrent"]
AR = ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
      "AccountsReceivableNet"]
INV = ["InventoryNet"]
COGS = ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold", "CostOfServices"]
DIVC = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]
SHARES = ["WeightedAverageNumberOfDilutedSharesOutstanding",
          "WeightedAverageNumberOfDilutedSharesOutstandingIncludingParticipatingSecurities"]


def year_ends(rev_maps):
    """{年ラベル: FY末日}。同一年の重複は期限内で最新filedを採る（flow_maps と同じ流儀）。"""
    out = {}
    for m in rev_maps:
        for y, (_v, fl, en) in m.items():
            if y not in out or fl > out[y][0]:
                out[y] = (fl, en)
    return {y: v[1] for y, v in out.items()}


def shares_map(g, deadline):
    """希薄化後株数の年次。units は 'shares'。同一年は期限内で最新filed。"""
    m = {}
    for tag in SHARES:
        node = g.get(tag)
        if not node:
            continue
        for e in node.get("units", {}).get("shares", []):
            en, st, fl = e.get("end", ""), e.get("start", ""), e.get("filed", "")
            if not en or not st or not fl or fl > deadline:
                continue
            try:
                if not (330 <= (d2(en) - d2(st)).days <= 400):
                    continue
            except Exception:
                continue
            y = int(en[:4])
            if y not in m or fl > m[y][1]:
                m[y] = (e["val"], fl)
        if m:
            break                      # 候補は代替＝先頭が取れたらそれを使う
    return {y: v[0] for y, v in m.items()}


def debt_at(g, deadline, end_date):
    """有利子負債。総額タグ優先。総額が無いときだけ Noncurrent+Current を足す。
    総額と構成要素が両方ある年は **恒等式が±2%で成立するときだけ**総額を採る（両方足さない）。"""
    tot = inst_at(g, DEBT_TOTAL, deadline, end_date)
    nc = inst_at(g, DEBT_NC, deadline, end_date)
    cu = inst_at(g, DEBT_C, deadline, end_date)
    st = inst_at(g, DEBT_ST, deadline, end_date) or 0.0
    if tot is not None:
        if nc is not None and cu is not None:
            s = nc + cu
            if s > 0 and abs(tot - s) / s > 0.02 and tot < s:
                tot = s          # 総額タグが部分しか含まない社（恒等式が壊れる）は和を採る
        return tot + st
    if nc is not None or cu is not None:
        return (nc or 0.0) + (cu or 0.0) + st
    return None if st == 0 else st


def build(t, g, deadline):
    row = {"ticker": t}
    rev_get, rev_maps = flow_maps(g, REV, deadline, mode="max")
    ends = [v[2] for m in rev_maps for v in m.values()]
    if not ends:
        return row
    fy_end = max(ends, key=d2)
    a = int(fy_end[:4])
    ye = year_ends(rev_maps)
    row["fy"] = a
    row["fy_end"] = fy_end
    W = list(range(a - 4, a + 1))

    rev = {y: rev_get(y) for y in range(a - 5, a + 1)}
    op_get, _ = flow_maps(g, OP, deadline)
    ni_get, _ = flow_maps(g, NI, deadline)
    ocf_get, _ = flow_maps(g, OCF, deadline)

    def inst(tags, y):
        e = ye.get(y)
        return inst_at(g, tags, deadline, e) if e else None

    # ---- 1. 総資産成長 ----
    A = {y: inst(ASSETS, y) for y in range(a - 5, a + 1)}
    if A.get(a) and A.get(a - 1):
        row["agr1"] = r4(A[a] / A[a - 1] - 1)
    if A.get(a) and A.get(a - 5):
        row["agr5"] = r4(cagr(A[a - 5], A[a], 5))

    # ---- 2. 純営業資産 / 前期総資産 ----
    cash = inst(CASH, a)
    sti = inst(STI, a) or 0.0
    eq = inst(EQ, a)
    liab = inst(LIAB, a)
    src = "Liabilities"
    if liab is None and A.get(a) is not None and eq is not None:
        liab = A[a] - eq
        src = "Assets-Equity"
    debt = debt_at(g, deadline, fy_end)
    if A.get(a) and A.get(a - 1) and cash is not None and liab is not None and debt is not None:
        opa = A[a] - cash - sti
        opl = liab - debt
        row["noa_r"] = r4((opa - opl) / A[a - 1])
        row["noa_src"] = src

    # ---- 3. 隠れ負債（pre-ASC842 のオペレーティングリース）----
    lease = inst(LEASE, a)
    if lease is not None and A.get(a):
        row["lease_r"] = r4(lease / A[a])
        da_get, _ = flow_maps(g, DA, deadline)
        da, opv = da_get(a), op_get(a)
        if da is not None and opv is not None and (opv + da) > 0 and debt is not None and cash is not None:
            row["leasex"] = r4((debt + lease / 8.0 - cash - sti) / (opv + da))

    # ---- 4. 株式報酬 ----
    sbc_get, _ = flow_maps(g, SBC, deadline)
    vals = [sbc_get(y) / rev[y] for y in W if sbc_get(y) is not None and rev.get(y)]
    if len(vals) >= 3:
        row["sbc_r"] = r4(statistics.median(vals))

    # ---- 5. 設備の年齢 ----
    ppg, acd = inst(PPE_GROSS, a), inst(ACCDEP, a)
    if ppg and acd is not None and ppg > 0:
        row["age_pp"] = r4(acd / ppg)

    # ---- 6. のれん減損の履歴 ----
    gw = inst(GOODWILL, a)
    gw_ever = tag_seen(g, GOODWILL, deadline)
    if not gw_ever or (gw is not None and gw <= 0):
        row["gwimp_n"], row["gwimp_r"] = 0, 0.0      # のれんを持たない社は減損しえない
    else:
        imp_get, _ = flow_maps(g, GWIMP, deadline)
        seen = tag_seen(g, GWIMP, deadline)
        if not seen:
            row["gwimp_n"], row["gwimp_r"] = 0, 0.0  # 報告が一度も無い＝計上していない
        else:
            iv = {y: (imp_get(y) or 0.0) for y in W}
            row["gwimp_n"] = sum(1 for y in W if iv[y] > 0)
            e5 = inst(EQ, a - 4)
            if e5 and e5 > 0:
                row["gwimp_r"] = r4(sum(iv.values()) / e5)

    # ---- 7. restructuring の反復 ----
    if tag_seen(g, RESTR, deadline):
        rg, _ = flow_maps(g, RESTR, deadline)
        row["restr_n"] = sum(1 for y in W if (rg(y) or 0) > 0)
    else:
        row["restr_n"] = 0

    # ---- 8. 現金実効税率と会計実効税率 ----
    pt_get, _ = flow_maps(g, PRETAX, deadline)
    pts = [pt_get(y) for y in W]
    if all(v is not None for v in pts) and sum(pts) > 0:
        te_get, _ = flow_maps(g, TAXEXP, deadline)
        tes = [te_get(y) for y in W]
        if all(v is not None for v in tes):
            row["getr"] = r4(sum(tes) / sum(pts))
        tp3 = flow3(g, TAXPAID, deadline)
        tps = [tp3(y) for y in W]
        if all(s != "miss" for s, _ in tps) and any(s == "val" for s, _ in tps):
            row["cetr"] = r4(sum(v for _s, v in tps) / sum(pts))
            if row.get("getr") is not None:
                row["etrgap"] = r4(row["getr"] - row["cetr"])

    # ---- 9. 契約負債の伸び − 売上の伸び ----
    def dr(y):
        c = inst(DEFREV, y)
        nc = inst(DEFREV_NC, y)
        return None if (c is None and nc is None) else (c or 0.0) + (nc or 0.0)
    d0, d3 = dr(a), dr(a - 3)
    if d0 and d3 and d0 > 0 and d3 > 0 and rev.get(a) and rev.get(a - 3):
        g3 = cagr(d3, d0, 3)
        r3 = cagr(rev[a - 3], rev[a], 3)
        if g3 is not None and r3 is not None:
            row["defrev_gap"] = r4(g3 - r3)

    # ---- 10. 株数の軌道（分割の不連続は系列ごと欠測にする）----
    sh = shares_map(g, deadline)
    got = [sh.get(y) for y in W]
    if all(v and v > 0 for v in got):
        ratios = [got[i + 1] / got[i] for i in range(len(got) - 1)]
        if all(0.67 <= x <= 1.5 for x in ratios):        # 分割・逆分割の不連続を排除
            row["shr_cagr"] = r4(cagr(got[0], got[-1], 4))
            row["shr_down"] = sum(1 for x in ratios if x <= 1.0)
        else:
            row["shr_note"] = "株数系列に不連続（分割の疑い）→欠測"

    # ---- 11. 運転資本の劣化 ----
    def dso(y):
        r_, ar = rev.get(y), inst(AR, y)
        return (ar / r_) * 365 if (r_ and r_ > 0 and ar is not None) else None
    cg_get, _ = flow_maps(g, COGS, deadline)

    def dio(y):
        c, iv = cg_get(y), inst(INV, y)
        return (iv / c) * 365 if (c and c > 0 and iv is not None) else None
    x0, x5 = dso(a), dso(a - 4)
    if x0 is not None and x5 is not None:
        row["dso_d"] = r4(x0 - x5)
        row["dso"] = r4(x0)
    y0, y5 = dio(a), dio(a - 4)
    if y0 is not None and y5 is not None:
        row["dio_d"] = r4(y0 - y5)

    # ---- 12. 減配の履歴 ----
    dv3 = flow3(g, DIVC, deadline)
    dvs = [dv3(y) for y in W]
    if all(s != "miss" for s, _ in dvs):
        v = [x for _s, x in dvs]
        if sum(v) > 0:                                   # 一度も配当を払わない社は測れない（0ではない）
            row["divcut_n"] = sum(1 for i in range(1, len(v)) if v[i] < v[i - 1] * 0.99)
    # 参考: 純利益・営業CF（他族の分母検算用）
    row["_ni"] = r4(ni_get(a)) if ni_get(a) is not None else None
    row["_ocf"] = r4(ocf_get(a)) if ocf_get(a) is not None else None
    return row


FEATS = ["agr1", "agr5", "noa_r", "lease_r", "leasex", "sbc_r", "age_pp", "gwimp_n", "gwimp_r",
         "restr_n", "getr", "cetr", "etrgap", "defrev_gap", "shr_cagr", "shr_down",
         "dso", "dso_d", "dio_d", "divcut_n"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", type=int, default=2018)
    # 母集団とCIK表の選び方は retro_features2.py と**同じ**にした（2026-09-20・既定は従来どおり）。
    # 理由: 2015 は retro_returns_2015.json が164社の抽出で、実際の母集団は
    # retro_returns_2015_q.json の506社（164 ⊂ 506）。かつ**101社が cohort_2013 に無い**。
    ap.add_argument("--returns", default=None,
                    help="母集団に使う out/retro_returns_*.json（省略時 retro_returns_{asof}.json）")
    args = ap.parse_args()
    deadline = f"{args.asof}-07-01"
    rname = args.returns or f"retro_returns_{args.asof}.json"
    rets = json.load(open(os.path.join(BASE, "out", rname)))
    tickers = sorted({r["ticker"] for r in rets["rows"] if r.get("ticker")})
    cname = f"retro_cohort_{args.asof}.json"
    if not os.path.exists(os.path.join(BASE, "out", cname)):
        cname = "retro_cohort_2013.json"
    cohort = json.load(open(os.path.join(BASE, "out", cname)))
    t2cik = {r["ticker"]: r["cik"] for r in cohort["rows"] if r.get("ticker")}
    z = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip"))
    have = set(z.namelist())
    rows, miss = [], []
    for i, t in enumerate(tickers, 1):
        if i % 200 == 0:
            print(f"  {i}/{len(tickers)}")
        cik = t2cik.get(t)
        nm = f"CIK{cik:010d}.json" if cik is not None else None
        if not nm or nm not in have:
            miss.append(t)
            rows.append({"ticker": t})
            continue
        try:
            g = json.loads(z.read(nm)).get("facts", {}).get("us-gaap", {})
        except Exception:
            miss.append(t)
            rows.append({"ticker": t})
            continue
        rows.append(build(t, g, deadline))
    cov = {k: sum(1 for r in rows if r.get(k) is not None) for k in FEATS}
    out = {"generated": datetime.date.today().isoformat(), "asof": args.asof, "deadline": deadline,
           "note": "night/retro_features2.py の作法を import して再利用（look-ahead は filed<=deadline・"
                   "インスタントは各年のFY末日±10日・CF活動は三値読み）。判定はしない採取器。",
           "universe_file": rname, "cohort_file": cname,
           "n": len(rows), "n_missing_cik": len(miss), "coverage": cov, "rows": rows}
    p = os.path.join(BASE, "out", f"retro_fund2_{args.asof}.json")
    json.dump(out, open(p, "w"), ensure_ascii=False)
    print(f"asof={args.asof} n={len(rows)} CIK不明{len(miss)} → {p}")
    print("被覆:", {k: f"{v}({v*100//max(len(rows),1)}%)" for k, v in cov.items()})


if __name__ == "__main__":
    main()
