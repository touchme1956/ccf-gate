# kenshi_helper.py — 門2審査の検死用: companyfacts.zipから年次系列を機械抽出して表示
# 使い方: python3 night/kenshi_helper.py TICKER
# 出力: 通貨ユニット別の年次系列(売上/営利/純利/OCF/capex/自己資本/借入/現金/のれん/D&A/税/株数/EPS)
#       + ROIC系列(のれん込み/除き)・nde・accr・FCF転換の機械計算(参考値。審査官が原本と突き合わせて採否判断)
import zipfile, json, sys, datetime, statistics, urllib.request

T = sys.argv[1].upper()
HDR = {"User-Agent": "CCF-Omega-kenshi fortis5280@gmail.com"}
try:
    tk = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://www.sec.gov/files/company_tickers.json", headers=HDR), timeout=30).read())
    cik = next(str(v["cik_str"]).zfill(10) for v in tk.values() if v["ticker"].upper()==T)
except Exception as e:
    sys.exit(f"CIK解決失敗: {e}")
z = zipfile.ZipFile('companyfacts.zip')
try:
    facts = json.loads(z.read(f'CIK{cik}.json'))['facts']
except KeyError:
    sys.exit(f"companyfacts.zipにCIK{cik}なし(新規上場等)。ライブAPIで要取得")

def d2(s): return datetime.date(int(s[:4]),int(s[5:7]),int(s[8:10]))
def annual(ns_tag_list, flow=True):
    """(ns,tag)候補リストから、ユニット別に年次系列を返す {unit: {year: val}}"""
    out = {}
    for ns, tag in ns_tag_list:
        node = facts.get(ns, {}).get(tag)
        if not node: continue
        for unit, ents in node.get('units', {}).items():
            if '/' in unit: continue
            d = out.setdefault(f"{tag}[{unit}]", {})
            best = {}
            for e in ents:
                en = e.get('end'); fl = e.get('filed','')
                if not en: continue
                if flow:
                    st = e.get('start')
                    if not st or not (330 <= (d2(en)-d2(st)).days <= 400): continue
                else:
                    if e.get('start'): continue
                y = int(en[:4])
                if y not in best or fl > best[y][1]: best[y] = (float(e['val']), fl)
            for y,(v,_) in best.items(): d[y] = v
    return out

G = lambda *pairs: annual(list(pairs))
GS = lambda *pairs: annual(list(pairs), flow=False)
SETS = {
 "rev":  G(("us-gaap","Revenues"),("us-gaap","RevenueFromContractWithCustomerExcludingAssessedTax"),("ifrs-full","Revenue"),("ifrs-full","RevenueFromContractsWithCustomers")),
 "op":   G(("us-gaap","OperatingIncomeLoss"),("ifrs-full","ProfitLossFromOperatingActivities")),
 "gp":   G(("us-gaap","GrossProfit"),("ifrs-full","GrossProfit")),
 "ni":   G(("us-gaap","NetIncomeLoss"),("ifrs-full","ProfitLoss")),
 "niP":  G(("ifrs-full","ProfitLossAttributableToOwnersOfParent")),
 "tax":  G(("us-gaap","IncomeTaxExpenseBenefit"),("ifrs-full","IncomeTaxExpenseContinuingOperations")),
 "ocf":  G(("us-gaap","NetCashProvidedByUsedInOperatingActivities"),("ifrs-full","CashFlowsFromUsedInOperatingActivities")),
 "capex":G(("us-gaap","PaymentsToAcquirePropertyPlantAndEquipment"),("ifrs-full","PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")),
 "capin":G(("us-gaap","PaymentsToAcquireIntangibleAssets"),("ifrs-full","PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities")),
 "dep":  G(("us-gaap","DepreciationDepletionAndAmortization"),("us-gaap","DepreciationAndAmortization"),("ifrs-full","AdjustmentsForDepreciationAndAmortisationExpense")),
 "sbc":  G(("us-gaap","ShareBasedCompensation"),("ifrs-full","ExpenseFromSharebasedPaymentTransactionsWithEmployees")),
 "acq":  G(("us-gaap","PaymentsToAcquireBusinessesNetOfCashAcquired"),("ifrs-full","CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities")),
 "epsB": G(("us-gaap","EarningsPerShareBasic"),("ifrs-full","BasicEarningsLossPerShare")),
 "epsD": G(("us-gaap","EarningsPerShareDiluted"),("ifrs-full","DilutedEarningsLossPerShare")),
 "shW":  G(("us-gaap","WeightedAverageNumberOfSharesOutstandingBasic"),("ifrs-full","WeightedAverageShares")),
 "eq":   GS(("us-gaap","StockholdersEquity"),("ifrs-full","Equity")),
 "eqP":  GS(("ifrs-full","EquityAttributableToOwnersOfParent")),
 "debtL":GS(("us-gaap","LongTermDebtNoncurrent"),("us-gaap","LongTermDebt"),("ifrs-full","NoncurrentBorrowings"),("ifrs-full","LongtermBorrowings"),("ifrs-full","Borrowings")),
 "debtS":GS(("us-gaap","LongTermDebtCurrent"),("us-gaap","DebtCurrent"),("ifrs-full","CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"),("ifrs-full","ShorttermBorrowings")),
 "cash": GS(("us-gaap","CashAndCashEquivalentsAtCarryingValue"),("ifrs-full","CashAndCashEquivalents")),
 "sti":  GS(("us-gaap","ShortTermInvestments"),("us-gaap","MarketableSecuritiesCurrent")),
 "gw":   GS(("us-gaap","Goodwill"),("ifrs-full","Goodwill")),
 "assets":GS(("us-gaap","Assets"),("ifrs-full","Assets")),
 "shOut":GS(("dei","EntityCommonStockSharesOutstanding")),
}
print(f"=== {T} CIK{cik} — 年次系列(直近8年・ユニット別) ===")
print("namespaces:", list(facts.keys()))
for k, series in SETS.items():
    for tagunit, d in series.items():
        ys = sorted(d)[-8:]
        if not ys: continue
        scale = 1e9 if max(abs(d[y]) for y in ys) > 5e9 else (1e6 if max(abs(d[y]) for y in ys) > 5e6 else 1)
        sfx = "十億" if scale==1e9 else ("百万" if scale==1e6 else "")
        print(f" {k:<6} {tagunit:<58} {sfx:>2}: " + " ".join(f"{y}:{d[y]/scale:,.1f}" for y in ys))

# ---- 参考機械計算(最多年数ユニットで。審査官は必ず原本と突き合わせること) ----
def pick(key):
    best = None
    for tu, d in SETS[key].items():
        if best is None or len(d) > len(best[1]): best = (tu, d)
    return best or (None, {})
tu_rev, rev = pick("rev"); tu_op, op = pick("op"); _, ni = pick("ni"); _, ocf = pick("ocf")
_, capex = pick("capex"); _, capin = pick("capin"); _, eq = pick("eq")
_, dL = pick("debtL"); _, dS = pick("debtS"); _, cash = pick("cash"); _, gw = pick("gw")
_, assets = pick("assets"); _, dep = pick("dep"); _, tax = pick("tax")
yrs = sorted(set(rev) & set(op) & set(eq))[-5:]
print(f"\n=== 参考機械計算 (rev={tu_rev}, op={tu_op}, 直近5共通年={yrs}) ===")
if yrs:
    for y in yrs:
        ic  = eq.get(y,0)+dL.get(y,0)+dS.get(y,0)
        icg = ic - gw.get(y,0)
        r1 = op[y]*0.79/ic if ic>0 else None
        r2 = op[y]*0.79/icg if icg>0 else None
        print(f" {y}: opm={op[y]/rev[y]*100:5.1f}% ROIC(込み)={r1*100:5.1f}%" if r1 else f" {y}: opm={op[y]/rev[y]*100:5.1f}% ROIC=IC<=0",
              f" ROIC(のれん除き)={r2*100:5.1f}%" if r2 else "")
    rr = [op[y]*0.79/(eq[y]+dL.get(y,0)+dS.get(y,0)) for y in yrs if (eq[y]+dL.get(y,0)+dS.get(y,0))>0]
    if len(rr)>=3: print(f" ROICσ({len(rr)}年)={statistics.pstdev(rr)*100:.1f}pt 最低={min(rr)*100:.1f}%")
    y = yrs[-1]
    if y in ocf:
        fcf = ocf[y]-capex.get(y,0)-capin.get(y,0)
        print(f" FY{y}: OCF={ocf[y]/1e6:,.0f}M capex={-(-capex.get(y,0)-capin.get(y,0))/1e6:,.0f}M FCF={fcf/1e6:,.0f}M NI={ni.get(y,0)/1e6:,.0f}M")
        if y in assets and y in ni: print(f" accr=({ni[y]/1e6:,.0f}-{ocf[y]/1e6:,.0f})/{assets[y]/1e6:,.0f} = {(ni[y]-ocf[y])/assets[y]*100:.1f}%")
    nd = dL.get(y,0)+dS.get(y,0)-cash.get(y,0)
    ebitda = op[y]+dep.get(y,0)
    if ebitda>0: print(f" nde=({dL.get(y,0)/1e6:,.0f}+{dS.get(y,0)/1e6:,.0f}-{cash.get(y,0)/1e6:,.0f})/{ebitda/1e6:,.0f} = {nd/ebitda:.2f}")
    sni = sum(ni.get(y,0) for y in yrs)
    sfcf = sum(ocf.get(y,0)-capex.get(y,0)-capin.get(y,0) for y in yrs if y in ocf)
    if sni>0: print(f" 5年FCF転換={sfcf/sni*100:.0f}%")
    # 2026-09-23: **sbc 欄は「株式報酬÷売上（%）」**（門の入力欄「SBC比率」）。上の生系列は十億/百万の金額なので、
    #   それをそのまま sbc に写すと単位が違う——実測 63パックが金額（十億$/百万$）で入っていた
    #   （MSFT 12.0＝SBC 12.0十億$ → 真の比率 3.74% ／ GOOGL 25.0 は「12%以上で減点」を誤って −10.4pt 効かせていた）。
    _, sbcS = pick("sbc")
    if y in sbcS and rev.get(y):
        print(f" sbc（門の欄・SBC比率）= 株式報酬 {sbcS[y]/1e6:,.0f}M ÷ 売上 {rev[y]/1e6:,.0f}M = {sbcS[y]/rev[y]*100:.2f}%"
              f"   ⚠金額（十億/百万）を sbc に入れないこと")
print("\n⚠ ユニット混在(別通貨/COP/BRL等)・IAS29(ARS)・SPAC断絶・FY年ズレは審査官が上の生系列で必ず確認すること")
