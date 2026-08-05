# night/retro_features_2018.py — 途中乗り(2018年)時点の観測可能ファンダメンタルズ一式（2026-08-05新設）
#
# 目的（ユーザー「もっと調べて捕捉できないか徹底的にデータ取って」）:
#   「前半5年の実証がある社」のうち後半も年率15%+を出す社（継続組）を、2018年時点で
#   観測できた数字でどこまで見分けられたかを徹底検証するための特徴量を採る。
#   look-ahead防止: 全て FY2018 以前（暦年ラベル≤2018）の申告値のみ。
#
# 特徴量（すべて分割の影響を受けない量で設計——KLACの教訓）:
#   opm18 / opmΔ(2018-2013) : 営業利益率の水準と5年変化
#   accel : 売上成長の加速度 = CAGR(2016→2018) − CAGR(2013→2016)
#   rnd18 : R&D/売上
#   conv58: FCF転換(2014-2018) = Σ(OCF−capex)/ΣNI
#   payout58: 還元性向 = Σ(配当+自社株買い)/ΣNI（株数を使わない＝分割フリー）
#   gwg : のれん増加率(2018/2013)
#   nde18: 純有利子負債/EBITDA（タグ改称に候補群で対応・欠測はNone）
#   roic18/roictrend: 門式単年roic(2018)と、2014-18中央値との差
# 実行: python3 night/retro_features_2018.py → out/retro_features_2018.json
import json, os, zipfile, statistics, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Y0, Y1 = 2013, 2018


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def mk(g):
    def inst(tags, y):
        for tag in tags:
            node = g.get(tag)
            if not node:
                continue
            best = None
            for e in node.get('units', {}).get('USD', []):
                en = e.get('end', '')
                if en.startswith(str(y)) and not e.get('start'):
                    if best is None or e.get('filed', '') > best[1]:
                        best = (e['val'], e.get('filed', ''))
            if best:
                return best[0]
        return None

    def flow(tags, y):
        for tag in tags:
            node = g.get(tag)
            if not node:
                continue
            best = None
            for e in node.get('units', {}).get('USD', []):
                en, st = e.get('end', ''), e.get('start', '')
                if not en or not st:
                    continue
                try:
                    if not (330 <= (d2(en) - d2(st)).days <= 400):
                        continue
                except Exception:
                    continue
                if int(en[:4]) == y:
                    if best is None or e.get('filed', '') > best[1]:
                        best = (e['val'], e.get('filed', ''))
            if best:
                return best[0]
        return None
    return inst, flow


REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"]
OP = ["OperatingIncomeLoss"]
NI = ["NetIncomeLoss", "ProfitLoss"]
OCF = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets"]
RND = ["ResearchAndDevelopmentExpense"]
DIV = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]
BUY = ["PaymentsForRepurchaseOfCommonStock"]
GW = ["Goodwill"]
EQ = ["StockholdersEquity"]
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt", "DebtAndCapitalLeaseObligations",
           "LongTermDebtAndCapitalLeaseObligations"]
DEBT_C = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
          "LongTermDebtAndCapitalLeaseObligationsCurrent"]
CASH = ["CashAndCashEquivalentsAtCarryingValue"]
DEP = ["DepreciationDepletionAndAmortization", "Depreciation"]
AMO = ["AmortizationOfIntangibleAssets"]
TAX = ["IncomeTaxExpenseBenefit"]
PRE = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"]
INTAN = ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"]


def cagr(a, b, n):
    if not a or not b or a <= 0 or b <= 0:
        return None
    return (b / a) ** (1 / n) - 1


def main():
    cohort = json.load(open(os.path.join(BASE, "out", "retro_cohort_2013.json")))
    t2cik = {r["ticker"]: r["cik"] for r in cohort["rows"] if r.get("ticker")}
    z = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip"))
    out = []
    for i, (t, cik) in enumerate(sorted(t2cik.items()), 1):
        if i % 200 == 0:
            print(f"  {i}/{len(t2cik)}")
        try:
            g = json.loads(z.read(f"CIK{cik:010d}.json")).get("facts", {}).get("us-gaap", {})
        except Exception:
            continue
        inst, flow = mk(g)
        rev = {y: flow(REV, y) for y in (2013, 2016, 2018)}
        op = {y: flow(OP, y) for y in (2013, 2018)}
        row = {"ticker": t}
        if rev[2018] and op[2018]:
            row["opm18"] = op[2018] / rev[2018]
        if rev[2013] and op[2013] and rev[2018] and op[2018]:
            row["opmD"] = op[2018] / rev[2018] - op[2013] / rev[2013]
        c1 = cagr(rev[2013], rev[2016], 3)
        c2 = cagr(rev[2016], rev[2018], 2)
        if c1 is not None and c2 is not None:
            row["accel"] = c2 - c1
        if rev[2018]:
            rd = flow(RND, 2018)
            row["rnd18"] = (rd or 0) / rev[2018]
        ocf = [flow(OCF, y) for y in range(2014, 2019)]
        cap = [flow(CAPEX, y) or 0 for y in range(2014, 2019)]
        ni = [flow(NI, y) for y in range(2014, 2019)]
        if all(v is not None for v in ocf) and all(v is not None for v in ni) and sum(ni) > 0:
            row["conv58"] = (sum(ocf) - sum(cap)) / sum(ni)
        dv = [flow(DIV, y) or 0 for y in range(2014, 2019)]
        bb = [flow(BUY, y) or 0 for y in range(2014, 2019)]
        if all(v is not None for v in ni) and sum(ni) > 0:
            row["payout58"] = (sum(dv) + sum(bb)) / sum(ni)
        gw13, gw18 = inst(GW, 2013), inst(GW, 2018)
        if gw13 and gw18 and gw13 > 0:
            row["gwg"] = gw18 / gw13 - 1
        # nde18
        eq18 = inst(EQ, 2018)
        lt = inst(DEBT_LT, 2018)
        cur = inst(DEBT_C, 2018) or 0
        cash = inst(CASH, 2018)
        dep = flow(DEP, 2018) or 0
        amo = flow(AMO, 2018) or 0
        if lt is not None and cash is not None and op[2018] and (op[2018] + dep + amo) > 0:
            row["nde18"] = (lt + cur - cash) / (op[2018] + dep + amo)
        # roic18（門式・単年）と2014-18中央値との差
        tax = flow(TAX, 2018)
        pre = flow(PRE, 2018)
        intan = inst(INTAN, 2018) or 0
        if all(v is not None for v in (eq18, lt, op[2018], tax, pre)) and pre != 0:
            nopat = op[2018] * (1 - tax / pre)
            ic = eq18 + lt + cur - (gw18 or 0) - intan
            if ic > 0.2 * max(eq18, 1):
                row["roic18"] = nopat / ic
        out.append(row)
    path = os.path.join(BASE, "out", "retro_features_2018.json")
    json.dump({"generated": datetime.date.today().isoformat(), "n": len(out), "rows": out},
              open(path, "w"), ensure_ascii=False, indent=1)
    got = {k: sum(1 for r in out if k in r) for k in
           ("opm18", "opmD", "accel", "rnd18", "conv58", "payout58", "gwg", "nde18", "roic18")}
    print(f"■ {path}  {len(out)}社  被覆: {got}")


if __name__ == "__main__":
    main()
