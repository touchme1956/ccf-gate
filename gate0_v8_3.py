# =====================================================================
# CCF Ω Final Gate — 第0の門 統合版 v8.3（1セル・1実行で全工程）
#
#   漏斗(2,887社判定) → golden set回帰 → 業態除外 → 待ち行列100
#   → 敗者復活の椅子(現金控除ROIC内蔵) → WATCH照合
#
# 【v7.1からの統合】gate1_rank / gate1_autopsy を本体に吸収。
#   解剖(現金・短期投資・のれん)は漏斗の1パス内で同時取得 — 追加コストほぼゼロ。
# 【焼き込んだ教訓】
#   ・短期投資タグ9種(VEEV/LMATを誤殺したタグ漏れの修正) + 年別最大値方式
#   ・IC-現金が負になる年がある企業(SPGI型)は椅子にせず「要手動」へ隔離
#   ・中国VIEの既知すり抜け(NTES等)を明示ブラックリストで補強
#   ・椅子の回帰テスト: VEEVが椅子に居なければこの実行は不採用
#
# 【v8.1 (2026-07-14) の変更 — 壊れない複利の門 v9.6思想との統一】
#   ・RESCUE_FAILSに"FCF転換"を追加: FCF転換70%未満でも現金控除ROICが閾値超なら椅子で救済。
#     採点機v9.6の「ROIIC≥WACC+5なら転換率未満でも通す(Amazon型)」と整合。入口で種まき型を殺さない。
#   ・次工程をhachimon_fetch.py(採取器v3.0)に更新: 待ち行列→SEC自動採取→採点機JSONの一気通貫。
#   ・来年動かす前に必ず更新: HOLDINGS / GOLDENの期待スコア / STALE_DAYS / (採取器側)SKIP。
#     詳細は門のⅠ解説タブ冒頭「運用手順書」「来年動かす前のチェックリスト」を参照。
#
# 【v8.2 (2026-07-17) の変更 — 並走環境(ccf-gate)での門0改修。検証後にColab正本へ移植】
#   ・負資本の墓場はずし: equity_neg でも score==7 かつ IC>0 でROIC正常計算なら、⚑負資本フラグ付きで
#     待ち行列プールに合流(FICO/ORLY/AZO/FTNT型=自社株買いで簿価資本を消した複利機械)。
#     レバレッジの当否は第二の門の財務安全(f系)が裁く——門0が入口で殺さない。負資本6点のみnegeqに残す。
#   ・のれんの椅子: 現金椅子と対称に、のれん控除ROIC(IC-のれん)が閾値超の敗者復活候補を「要審査」枠で
#     可視化(ROP型ロールアップ)。救済ではなく番人の審査対象。のれん控除は買収の高値掴みを化粧できるため、
#     買収の巧拙はf系資本配分で必ず裁くこと。IC-のれんが負の年がある企業は要手動へ隔離(SPGI型と同じ扱い)。
#   ・回帰追加: FICOが待ち行列に居ること(負資本合流の固定)。のれん椅子の回帰は初回観測後に固定する。
#
# 【v8.3 (2026-07-17) の変更 — 病名「成長停止」の隔離】
#   ・6点で唯一の失敗が売上CAGR(<5%)の企業は待ち行列に入れず「成長停止棚」(gate1_stalled.json)へ。
#     根拠: 品質7項目のうち門2の定性審査で挽回しうるのはROIC系(現金/のれんの化粧)やFCF転換(種まき型)だが、
#     成長の欠如だけは20-30年複利で直せない唯一の病。数字が正しく絶望している会社に審査枠を使わない。
#   ・永久追放ではない: CAGRは毎年の門0で再計算されるため、成長が戻れば翌年自動で待ち行列に復帰する。
#   ・空いた枠はpt次点が自動で繰り上がる。回帰追加: AAPL(3%成長・golden set銘柄)が棚に居て待ち行列に居ないこと。
#
# 前提: Drive/ccf に companyfacts.zip（無ければ自動DL 10-20分）
# 実行: zipあり約10-12分 / 初回 25-35分
# =====================================================================
EMAIL = "fortis5280@gmail.com"

YEARS, MIN_SALES_CAGR = 5, 0.05
MIN_ROIC_LATEST, MIN_ROIC_WORST = 0.15, 0.10
MIN_OPM, MIN_FCF_CONV = 0.15, 0.70
SEND_TO_GATE1, TOP_N = 6, 100
SEAM_TOL, STALE_DAYS = 0.02, 600
RESCUE_MIN_OPM, RESCUE_MIN_CAGR = 0.15, 0.08
RESCUE_FAILS = {"ROIC", "ROIC最低値", "FCF転換"}  # v9.6: FCF転換未達でも高ROIC(現金控除ROIC)なら椅子で救済——種まき型を入口で殺さない
KNOWN_CN = {"PDD","NTES","BABA","JD","BIDU","TCOM","YUMC","LI","NIO","XPEV","QFIN","XYF","ATAT"}

HOLDINGS = {"NVDA","MSFT","V","TSM","ASML","RACE","ADBE","IDXX","FTNT","RMD",
            "COST","CPRT","KLAC","SNPS","INTU","LIN","ROP","MA","GOOGL","META"}
WATCH = HOLDINGS | {"VEEV","LMAT","CTAS","ADP","MANH","MEDP","HEI","ANET","KARO","LLY"}

import json, time, csv, urllib.request, collections, datetime, os, zipfile

SAVE_DIR = "/content/drive/MyDrive/ccf"
try:
    from google.colab import drive
    drive.mount('/content/drive', force_remount=False)
    os.makedirs(SAVE_DIR, exist_ok=True)
except Exception as e:
    SAVE_DIR = "."
print(f"■ 保存先: {SAVE_DIR}\n")

HDR = {"User-Agent": f"CCF-Omega-Screener {EMAIL}"}
ZIP_PATH = f"{SAVE_DIR}/companyfacts.zip"
if os.path.exists(ZIP_PATH) and os.path.getsize(ZIP_PATH) > 1e9:
    print(f"■ companyfacts.zip 再利用 ({os.path.getsize(ZIP_PATH)/1e9:.2f} GB)")
else:
    print("■ companyfacts.zip をダウンロード中（約1.4GB）...")
    req = urllib.request.Request(
        "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip", headers=HDR)
    with urllib.request.urlopen(req, timeout=120) as r, open(ZIP_PATH, "wb") as f:
        done = 0
        while True:
            c = r.read(1 << 22)
            if not c: break
            f.write(c); done += len(c)
    print(f"    完了 {done/1e9:.2f} GB")

def get(u):
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=45) as r:
                return json.loads(r.read())
        except Exception: time.sleep(0.4)
    return None

tk = get("https://www.sec.gov/files/company_tickers.json") or {}
CIK2TK, TK2CIK = {}, {}
for row in tk.values():
    CIK2TK.setdefault(int(row["cik_str"]), row["ticker"])
    TK2CIK.setdefault(row["ticker"], int(row["cik_str"]))

TAGS = {
 "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax","Revenues",
             "RevenueFromContractWithCustomerIncludingAssessedTax","SalesRevenueNet",
             "SalesRevenueGoodsNet","SalesRevenueServicesNet","Revenue",
             "RevenueFromContractsWithCustomers"],
 "opinc":   ["OperatingIncomeLoss","ProfitLossFromOperatingActivities","OperatingProfitLoss"],
 "gross":   ["GrossProfit"], "rnd": ["ResearchAndDevelopmentExpense"],
 "sga":     ["SellingGeneralAndAdministrativeExpense","GeneralAndAdministrativeExpense"],
 "sell":    ["SellingAndMarketingExpense","SellingExpense"],
 "cogs":    ["CostOfRevenue","CostOfGoodsAndServicesSold","CostOfGoodsSold"],
 "ni":      ["NetIncomeLoss","ProfitLossAttributableToOwnersOfParent","ProfitLoss",
             "NetIncomeLossAvailableToCommonStockholdersBasic"],
 "ocf":     ["NetCashProvidedByUsedInOperatingActivities",
             "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
             "CashFlowsFromUsedInOperatingActivities","NetCashFlowsFromUsedInOperatingActivities"],
 "capex":   ["PaymentsToAcquirePropertyPlantAndEquipment","PaymentsToAcquireProductiveAssets",
             "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
             "PaymentsForCapitalImprovements",
             "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
             "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsAndOtherLongtermAssets"],
 "equity":  ["StockholdersEquity","StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
             "EquityAttributableToOwnersOfParent","Equity"],
 "debt_lt": ["LongTermDebtNoncurrent","LongTermDebt","BorrowingsNoncurrent","LongtermBorrowings"],
 "debt_st": ["LongTermDebtCurrent","DebtCurrent","ShortTermBorrowings","BorrowingsCurrent",
             "CurrentPortionOfNoncurrentBorrowings","ShorttermBorrowings"],
 "cash":    ["CashAndShortTermInvestments","CashAndCashEquivalentsAtCarryingValue","CashAndCashEquivalents"],
 "sti":     ["ShortTermInvestments","MarketableSecuritiesCurrent","CurrentInvestments",
             "AvailableForSaleSecuritiesDebtSecuritiesCurrent","AvailableForSaleSecuritiesCurrent",
             "DebtSecuritiesAvailableForSaleCurrent","HeldToMaturitySecuritiesCurrent",
             "TradingSecuritiesCurrent","ShortTermInvestmentsAndMarketableSecurities"],
 "gw":      ["Goodwill"],
}
FLOW = {"revenue","opinc","gross","rnd","sga","sell","cogs","ni","ocf","capex"}
def d2(s): return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
def near(a, b, days=7): return abs((d2(a)-d2(b)).days) <= days
TODAY = datetime.date.today()

def collect(facts, key):
    out = []
    flow = key in FLOW
    for taxo in ("us-gaap","ifrs-full"):
        ns = facts.get(taxo)
        if not ns: continue
        for tag in TAGS[key]:
            node = ns.get(tag)
            if not node: continue
            for unit, ents in node.get("units", {}).items():
                if "/" in unit: continue
                d = {}
                for e in ents:
                    en = e.get("end"); fl = e.get("filed","")
                    if not en: continue
                    if flow:
                        st = e.get("start")
                        if not st or not (330 <= (d2(en)-d2(st)).days <= 400): continue
                        y = int(en[:4])
                        if y not in d or fl > d[y][2]: d[y] = (en, float(e["val"]), fl)
                    else:
                        if e.get("start"): continue
                        if en not in d or fl > d[en][1]: d[en] = (float(e["val"]), fl)
                if d: out.append((tag, unit, d))
    return out

def pick_series(cands, yrs, unit_lock=None, fye=None, stock=False):
    if unit_lock: cands = [(t,u,d) for (t,u,d) in cands if u == unit_lock]
    if stock and fye:
        f2 = []
        for t,u,d in cands:
            dd = {}
            for y, fy_end in fye.items():
                hits = [(en,v) for en,(v,fl) in d.items() if near(en, fy_end)]
                if hits: dd[y] = (sorted(hits)[-1][0], sorted(hits)[-1][1], "")
            if dd: f2.append((t,u,dd))
        cands = f2
    elif fye:
        cands = [(t,u,{y:v for y,v in d.items() if y in fye and near(v[0], fye[y])}) for (t,u,d) in cands]
        cands = [(t,u,d) for (t,u,d) in cands if d]
    if not cands: return None, None, None
    cands.sort(key=lambda c: -sum(1 for y in yrs if y in c[2]))
    tag0, unit0, d0 = cands[0]
    merged = {y: d0[y][1] for y in yrs if y in d0}
    lineage = tag0
    for t,u,d in cands[1:]:
        if u != unit0: continue
        missing = [y for y in yrs if y not in merged]
        if not missing: break
        overlap = [y for y in yrs if y in merged and y in d]
        if not all(merged[y]==0 or abs(d[y][1]-merged[y])/abs(merged[y])<=SEAM_TOL for y in overlap):
            continue
        filled = False
        for y in missing:
            if y in d: merged[y] = d[y][1]; filled = True
        if filled: lineage += f"+{t}"
    if all(y in merged for y in yrs):
        return [merged[y] for y in yrs], unit0, lineage
    return None, None, None

def sti_series(facts, yrs, unit, fye):
    """短期投資: タグごとに取り年別最大値(別名重複は二重計上しない/取り漏らし防止)"""
    si = [0.0]*len(yrs)
    for tag,u,d in collect(facts,"sti"):
        if u != unit: continue
        for k,y in enumerate(yrs):
            hits = [v for en,(v,fl) in d.items() if near(en, fye[y])]
            if hits: si[k] = max(si[k], max(hits))
    return si

def derive_opinc(facts, yrs, unit, fye):
    def grab(key):
        v,_,_ = pick_series(collect(facts,key), yrs, unit_lock=unit, fye=fye)
        return v
    g = grab("gross")
    if g is None:
        rv, cg = grab("revenue"), grab("cogs")
        if rv is None or cg is None: return None
        g = [rv[i]-cg[i] for i in range(len(yrs))]
    rnd = grab("rnd") or [0.0]*len(yrs)
    sga = grab("sga")
    if sga is None:
        cands = collect(facts,"sga")
        ga,_,_ = pick_series([(t,u,d) for (t,u,d) in cands if t=="GeneralAndAdministrativeExpense"],
                             yrs, unit_lock=unit, fye=fye)
        se = grab("sell")
        if ga is None or se is None: return None
        sga = [ga[i]+se[i] for i in range(len(yrs))]
    return [g[i]-rnd[i]-sga[i] for i in range(len(yrs))]

def evaluate(rev, op, ni, ocf, cap, eq, lt, st):
    n = len(rev)
    if any(x <= 0 for x in rev): return None, "revenue_zero"
    fcf = [ocf[i]-cap[i] for i in range(n)]
    roic = []
    for i in range(n):
        ic = eq[i]+lt[i]+st[i]
        if ic <= 0: return None, "invested_capital_broken"
        roic.append(op[i]*0.79/ic)
    opm  = op[-1]/rev[-1]
    cagr = (rev[-1]/rev[0])**(1/(n-1)) - 1
    s_ni = sum(ni)
    conv = sum(fcf)/s_ni if s_ni > 0 else None
    m = {"sales_cagr5":round(cagr,4),"opm":round(opm,4),
         "roic_latest":round(roic[-1],4),"roic_worst5":round(min(roic),4),
         "fcf_conv_5y":round(conv,4) if conv is not None else None,
         "op_all_pos":all(x>0 for x in op),"fcf_all_pos":all(x>0 for x in fcf),
         "equity_neg":any(x<=0 for x in eq),
         "warn_anomaly":(opm>1.0 or max(roic)>1.5)}
    f = []
    if not m["op_all_pos"]: f.append("営業赤字")
    if not m["fcf_all_pos"]: f.append("FCFマイナス")
    if m["sales_cagr5"] < MIN_SALES_CAGR: f.append("売上CAGR")
    if m["roic_latest"] < MIN_ROIC_LATEST: f.append("ROIC")
    if m["roic_worst5"] < MIN_ROIC_WORST: f.append("ROIC最低値")
    if m["opm"] < MIN_OPM: f.append("営業利益率")
    if conv is None or conv < MIN_FCF_CONV: f.append("FCF転換")
    m["score"] = 7-len(f); m["fails"] = "; ".join(f)
    return m, None

# ============================ PART A: 漏斗 ============================
print("\n■ PART A — 漏斗（全社1パス・解剖同時取得）")
z = zipfile.ZipFile(ZIP_PATH)
names = [n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json")]
print(f"    {len(names)} ファイル")
RESULTS, QUAR = [], collections.Counter()
t0 = time.time()
for i, name in enumerate(names, 1):
    if i % 3000 == 0:
        el = time.time()-t0
        print(f"    {i}/{len(names)}  判定:{len(RESULTS)}  残り約{el/i*(len(names)-i)/60:.0f}分")
    cik = int(name[3:13]); tkr = CIK2TK.get(cik)
    if not tkr: continue
    try:
        j = json.loads(z.read(name)); facts = j.get("facts", {})
    except Exception: continue
    if not facts: continue
    rev_c = collect(facts, "revenue")
    if not rev_c: QUAR["no_revenue_tag"] += 1; continue
    best = None
    for unit in dict.fromkeys(u for (_,u,_) in rev_c):
        ys = sorted({y for (_,uu,d) in rev_c if uu==unit for y in d})
        if len(ys) < YEARS: continue
        yrs = ys[-YEARS:]
        v, u0, lin = pick_series(rev_c, yrs, unit_lock=unit)
        if v is not None and (best is None or yrs[-1] > best[1][-1]):
            fye = {y: max(d[y][0] for (_,uu,d) in rev_c if uu==unit and y in d) for y in yrs}
            best = (v, yrs, unit, lin, fye)
    if best is None: QUAR["revenue_5y_incomplete"] += 1; continue
    rev, yrs, unit, rev_lin, fye = best
    if (TODAY - d2(fye[yrs[-1]])).days > STALE_DAYS:
        QUAR["stale_filer"] += 1; continue
    STOCK = {"equity","debt_lt","debt_st","cash","gw"}
    def grab(key, zero=False):
        v,_,_ = pick_series(collect(facts,key), yrs, unit_lock=unit, fye=fye, stock=(key in STOCK))
        if v is None and zero: return [0.0]*YEARS
        return v
    ni, ocf, eq = grab("ni"), grab("ocf"), grab("equity")
    cap = grab("capex", zero=True); lt = grab("debt_lt", zero=True); st = grab("debt_st", zero=True)
    op, op_src = grab("opinc"), "reported"
    if op is None:
        op = derive_opinc(facts, yrs, unit, fye); op_src = "derived"
    miss = [k for k,v in [("ni",ni),("ocf",ocf),("equity",eq),("opinc",op)] if v is None]
    if miss: QUAR["欠損:"+miss[0]] += 1; continue
    m, err = evaluate(rev, op, ni, ocf, cap, eq, lt, st)
    if err: QUAR[err] += 1; continue
    if m["warn_anomaly"] and op_src == "derived":
        QUAR["derived_suspect"] += 1; continue
    # --- 解剖列（同一パスで現金・短期投資・のれんを取得）---
    ca = grab("cash", zero=True); si = sti_series(facts, yrs, unit, fye); gw = grab("gw", zero=True)
    roic_ex, ic_ex_neg = [], False
    for k in range(YEARS):
        icx = eq[k]+lt[k]+st[k]-ca[k]-si[k]
        if icx <= 0: ic_ex_neg = True; break
        roic_ex.append(op[k]*0.79/icx)
    roic_gw, ic_gw_neg = [], False  # v8.2: のれん控除ROIC(ロールアップの実体収益力)
    for k in range(YEARS):
        icg = eq[k]+lt[k]+st[k]-gw[k]
        if icg <= 0: ic_gw_neg = True; break
        roic_gw.append(op[k]*0.79/icg)
    ic = eq[-1]+lt[-1]+st[-1]
    m.update({"ticker":tkr,"name":j.get("entityName","")[:40],"ccy":unit,
              "fy_latest":yrs[-1],"op_src":op_src,"rev_tag":rev_lin[:60],
              "roic_ex_latest": round(roic_ex[-1],4) if not ic_ex_neg else None,
              "roic_ex_worst":  round(min(roic_ex),4) if not ic_ex_neg else None,
              "ic_ex_neg": ic_ex_neg,
              "roic_gw_latest": round(roic_gw[-1],4) if not ic_gw_neg else None,
              "roic_gw_worst":  round(min(roic_gw),4) if not ic_gw_neg else None,
              "ic_gw_neg": ic_gw_neg,
              "cash_pct": round((ca[-1]+si[-1])/ic*100,1) if ic>0 else None,
              "gw_pct":   round(gw[-1]/ic*100,1) if ic>0 else None})
    RESULTS.append(m)
print(f"    処理完了: {len(RESULTS)} 社  ({(time.time()-t0)/60:.0f}分)")

RESULTS.sort(key=lambda r: (-r["score"], -r["roic_worst5"]))
cols = ["ticker","name","ccy","fy_latest","score","fails","roic_latest","roic_worst5",
        "opm","sales_cagr5","fcf_conv_5y","op_all_pos","fcf_all_pos","equity_neg",
        "warn_anomaly","op_src","rev_tag","roic_ex_latest","roic_ex_worst","ic_ex_neg",
        "roic_gw_latest","roic_gw_worst","ic_gw_neg","cash_pct","gw_pct"]
with open(f"{SAVE_DIR}/gate0_all.csv","w",newline="",encoding="utf-8-sig") as fp:
    w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
    w.writeheader(); w.writerows(RESULTS)
sc = collections.Counter(r["score"] for r in RESULTS)
print(f"\n判定 {len(RESULTS)} 社 / 7点 {sc[7]} / 6点 {sc[6]} / 隔離上位: "
      + ", ".join(f"{k}:{v}" for k,v in QUAR.most_common(4)))

# ============================ PART B: golden set ============================
BYT = {r["ticker"]: r for r in RESULTS}
GOLDEN = {"MA":(7,{"rev_tag_contains":"Revenues"}),"GOOGL":(7,{}),"MSFT":(7,{}),
          "NVDA":(7,{}),"V":(7,{}),"META":(7,{}),"ADBE":(7,{}),"IDXX":(7,{}),
          "RACE":(7,{}),"NVO":(7,{}),"ASML":(7,{}),"FTNT":(7,{"op_src":"reported"}),
          "TSM":(6,{"ccy":"TWD"}),"AAPL":(6,{}),"CPRT":(6,{}),
          "KLAC":(None,{"op_src":"derived"}),"VEEV":(5,{}),"LMAT":(5,{})}
print("\n■ PART B — golden set 回帰テスト")
gfail = 0
for t,(exp,extra) in sorted(GOLDEN.items()):
    r = BYT.get(t)
    if r is None: print(f"  ✗ {t} 消失"); gfail += 1; continue
    ok, why = True, []
    if exp is not None and r["score"] != exp: ok=False; why.append(f"スコア{r['score']}≠{exp}")
    for k,v in extra.items():
        if k=="rev_tag_contains":
            if v not in r["rev_tag"]: ok=False; why.append("rev_tag")
        elif r.get(k)!=v: ok=False; why.append(k)
    if not ok: gfail += 1
    print(f"  {'○' if ok else '✗'} {t:<6} {r['score']}/7 {r['op_src']:<8} {'; '.join(why)}")

# ============================ PART C: 待ち行列・椅子・WATCH ============================
print("\n■ PART C — 業態除外・待ち行列・敗者復活")
rows = [r for r in RESULTS if r["score"] >= SEND_TO_GATE1]
resc = [r for r in RESULTS if r["score"]==5
        and set(f.strip() for f in r["fails"].split(";") if f.strip()).issubset(RESCUE_FAILS)
        and r["op_all_pos"] and r["fcf_all_pos"]
        and r["opm"]>=RESCUE_MIN_OPM and r["sales_cagr5"]>=RESCUE_MIN_CAGR]
need_sic = rows + resc
print(f"    SIC判定対象: {len(need_sic)} 社")
def excluded_sic(s):
    if not s: return None
    s = int(s)
    if 6000 <= s <= 6799: return "金融/保険/REIT"
    if 1000 <= s <= 1499: return "資源採掘"
    if s == 2911: return "石油精製"
    if 4400 <= s <= 4499: return "海運"
    return None
for i, r in enumerate(need_sic, 1):
    if i % 80 == 0: print(f"    {i}/{len(need_sic)}")
    cik = TK2CIK.get(r["ticker"]); sic, country = None, ""
    if cik:
        jj = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"); time.sleep(0.1)
        if jj:
            sic = jj.get("sic")
            country = ((jj.get("addresses") or {}).get("business") or {}).get("stateOrCountry","")
            r["sic_desc"] = jj.get("sicDescription","")
    why = excluded_sic(sic)
    if not why and (country in ("F4","K3","CN","HK") or r["ticker"] in KNOWN_CN):
        why = "中国/香港/VIE"
    if not why and r["opm"] > 1.0: why = "anomaly"
    r["excluded"] = why
    r["rx"] = bool(sic) and (2833 <= int(sic) <= 2836 or int(sic)==8731)

keep = [r for r in rows if not r.get("excluded")]
def clamp(x, lo, hi): return max(0.0, min(1.0, (x-lo)/(hi-lo)))
for r in keep:
    conv = min(r["fcf_conv_5y"] or 0, 1.5)
    r["pt"] = round(0.30*clamp(r["roic_worst5"],0.10,0.45)+0.30*clamp(r["sales_cagr5"],0.05,0.30)
                  + 0.20*clamp(r["opm"],0.15,0.50)+0.10*clamp(conv,0.70,1.20)
                  + 0.10*(1.0 if r["score"]==7 else 0.0), 4)
# v8.2: 負資本7点は墓場に置かない——⚑フラグ付きで待ち行列プールへ合流。6点のみnegeqに残す
neg7 = [r for r in keep if r["equity_neg"] and r["score"]==7]
for r in neg7: r["neg_flag"] = True
# v8.3: 病名=成長停止(6点・唯一の失敗が売上CAGR)は棚へ。門2で直せない唯一の病に審査枠を使わない。
#       CAGRは毎年再計算——成長が戻れば翌年自動復帰する棚であって、追放ではない。
stalled = sorted([r for r in keep if not r["equity_neg"] and r["score"]==6 and r["fails"]=="売上CAGR"],
                 key=lambda r: -r["pt"])
stset = {r["ticker"] for r in stalled}
pool  = sorted([r for r in keep if not r["equity_neg"] and r["ticker"] not in stset] + neg7,
               key=lambda r: -r["pt"])
negeq = sorted([r for r in keep if r["equity_neg"] and r["score"]!=7], key=lambda r: -r["pt"])
queue, backlog = pool[:TOP_N], pool[TOP_N:]

chairs  = [r for r in resc if not r.get("excluded") and not r["ic_ex_neg"]
           and r["roic_ex_latest"] is not None
           and r["roic_ex_latest"]>=MIN_ROIC_LATEST and r["roic_ex_worst"]>=MIN_ROIC_WORST]
manualq = [r for r in resc if not r.get("excluded") and r["ic_ex_neg"]]
# v8.2: のれんの椅子——現金椅子と対称。のれんを引けば閾値超のロールアップを「要審査」で可視化
in_chair = {r["ticker"] for r in chairs}
gwchairs = [r for r in resc if not r.get("excluded") and r["ticker"] not in in_chair
            and not r["ic_gw_neg"] and r["roic_gw_latest"] is not None
            and r["roic_gw_latest"]>=MIN_ROIC_LATEST and r["roic_gw_worst"]>=MIN_ROIC_WORST]
gwmanual = [r for r in resc if not r.get("excluded") and r["ticker"] not in in_chair and r["ic_gw_neg"]]
for r in RESULTS: r["held"] = "◆" if r["ticker"] in HOLDINGS else " "

for path, data in [("gate1_queue.json",queue),("gate1_backlog.json",backlog),
                   ("gate1_negeq.json",negeq),("gate1_rescue_final.json",chairs),
                   ("gate1_rescue_gw.json",gwchairs),("gate1_stalled.json",stalled)]:
    with open(f"{SAVE_DIR}/{path}","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

def line(i, r):
    fl = "⚑ " if r.get("neg_flag") else "Rx" if r.get("rx") else "  "  # ⚑=負資本合流(v8.2)
    return (f"{i:>3}.{r['held']}{fl} {r['ticker']:<6} pt{r.get('pt',0):.3f} {r['score']}/7 "
            f"ROIC最低{r['roic_worst5']*100:5.1f}% 営利{r['opm']*100:5.1f}% "
            f"CAGR{r['sales_cagr5']*100:5.1f}%  {r['name'][:24]}")
print("\n" + "="*78)
print(f"■ 待ち行列: {len(queue)} 社")
print("="*78)
for i, r in enumerate(queue, 1): print(line(i, r))
print("\n" + "="*78)
print(f"★ 敗者復活の椅子（現金型・{len(chairs)}社）— 現金を引けば門の閾値超え。番人の審査対象")
print("="*78)
for r in sorted(chairs, key=lambda r: -r["roic_ex_latest"]):
    print(f"  {r['ticker']:<6} 現金込み{r['roic_latest']*100:5.1f}% → 控除{r['roic_ex_latest']*100:6.1f}%"
          f"(最低{r['roic_ex_worst']*100:5.1f}%) 現金{r['cash_pct']}%/のれん{r['gw_pct']}%  {r['name'][:24]}")
if manualq:
    print(f"\n■ IC-現金が負の年あり（SPGI型・要手動・椅子にしない）: "
          + ", ".join(r["ticker"] for r in manualq))
print("\n" + "="*78)
print(f"★ のれんの椅子（ロールアップ型・{len(gwchairs)}社）— のれんを引けば門の閾値超え。番人の審査対象")
print("   ※のれん控除は買収の高値掴みを化粧できる。買収の巧拙はf系資本配分で必ず裁くこと")
print("="*78)
for r in sorted(gwchairs, key=lambda r: -r["roic_gw_latest"]):
    print(f"  {r['ticker']:<6} 込み{r['roic_latest']*100:5.1f}% → のれん控除{r['roic_gw_latest']*100:6.1f}%"
          f"(最低{r['roic_gw_worst']*100:5.1f}%) のれん{r['gw_pct']}%/IC  {r['name'][:24]}")
if gwmanual:
    print(f"■ IC-のれんが負の年あり（要手動・椅子にしない）: "
          + ", ".join(r["ticker"] for r in gwmanual))
print("\n" + "="*78)
print(f"▤ 成長停止棚（{len(stalled)}社）— 質は無傷・唯一の失敗が売上CAGR<5%。門2で直せない病。成長復帰で翌年自動復活")
print("="*78)
for r in stalled:
    print(f"  {r['held']} {r['ticker']:<6} pt{r['pt']:.3f} CAGR{r['sales_cagr5']*100:5.1f}% "
          f"営利{r['opm']*100:5.1f}% ROIC最低{r['roic_worst5']*100:5.1f}%  {r['name'][:24]}")
print(f"\n■ 自己資本マイナス枠(6点のみ・7点{len(neg7)}社は⚑合流): {len(negeq)} 社 / backlog: {len(backlog)} 社 / 成長停止棚: {len(stalled)} 社")

# 椅子の回帰テスト（今日の教訓の恒久化）
if not any(r["ticker"]=="VEEV" for r in chairs):
    gfail += 1
    print("\n⚠ 椅子回帰: VEEVが椅子に居ない — stiタグ取得を疑うこと")
# v8.2回帰: 負資本7点の合流(FICO=pt上位の負資本複利機械が待ち行列に居ること)
if not any(r["ticker"]=="FICO" for r in queue):
    gfail += 1
    print("\n⚠ 負資本合流回帰: FICOが待ち行列に居ない — equity_neg合流ロジックを疑うこと")
# v8.2回帰: のれん椅子(2026-07-17初回観測で固定: ROP=WATCH銘柄, SPGI=現金椅子の要手動から昇格)
for _t in ("ROP","SPGI"):
    if not any(r["ticker"]==_t for r in gwchairs):
        gfail += 1
        print(f"\n⚠ のれん椅子回帰: {_t}が椅子に居ない — gwタグ取得かのれん控除ロジックを疑うこと")
# v8.3回帰: 成長停止棚(AAPL=golden set銘柄・CAGR3%が棚に居て待ち行列に居ないこと)
if not any(r["ticker"]=="AAPL" for r in stalled) or any(r["ticker"]=="AAPL" for r in queue):
    gfail += 1
    print("\n⚠ 成長停止棚回帰: AAPLが棚に居ない(または待ち行列に混入) — stalledロジックを疑うこと")

print("\n■ WATCH照合")
qs = {r["ticker"] for r in queue}; bs = {r["ticker"] for r in backlog}
ns = {r["ticker"] for r in negeq}; cs = {r["ticker"] for r in chairs}
gs = {r["ticker"] for r in gwchairs}
for t in sorted(WATCH):
    r = BYT.get(t)
    st = ("待ち行列⚑負資本" if t in qs and r and r.get("neg_flag")
          else "待ち行列" if t in qs else "★椅子" if t in cs
          else "★のれん椅子" if t in gs else "▤成長停止棚" if t in stset
          else "自己資本マイナス枠" if t in ns
          else "backlog" if t in bs
          else f"業態除外({r.get('excluded')})" if r and r.get("excluded")
          else f"⚠落選 {r['score']}/7 ✗{r['fails']}" if r else "⚠⚠判定不能")
    print(f"  {t:<6} {st}")

print("\n" + ("★★★ golden set + 椅子回帰 全通過。この実行は採用可。 ★★★" if gfail==0
      else f"⚠⚠⚠ 回帰テスト {gfail} 件失敗。この実行は不採用。 ⚠⚠⚠"))
print("\n→ 次: hachimon_fetch.py（採取器v3.0）。TICKERS空で実行=この待ち行列の上位5社を自動採取し、門のⅡ採点機JSONを生成。")
try:
    from google.colab import files
    files.download(f"{SAVE_DIR}/gate0_all.csv")
except Exception: pass
