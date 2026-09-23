#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate_fetch v3.0 — SEC一撃採取器（壊れない複利の門 v9.6・Ⅲ採点機JSON下書き生成）
使い方:  python hachimon_fetch.py MSFT ASML ANET
出力:    ./out/{TICKER}_gate_input.json … 門のⅢ採点機に貼れるJSON下書き(SEC客観値を充填。Colab/Drive時はhachimon_out/)
         ./out/{TICKER}_hits.txt        … 定性6砲台(限/集/誠/蝕/堀/循)+facts用のキーワードヒット報告(2-3KB)
注意:    EMAIL を自分のものに書き換えること(SECはUser-Agent必須・10req/s制限)。
         px(株価)とbetaはSECに無いので空欄のまま——取込時に手入力かツール側で補完。
既知の要再採取(2026-08-04・A7): **WIT** のパックは有利子負債が Borrowings(総額) と
         LongtermBorrowings(その内数) の**二重計上**（約64B INR過大）で採られている。
         series_sum の総額タグ複数対応で採取器側は是正済みだが、パック自体はここでは直さない
         （審査官の検算経路を通すこと）。
"""
import hashlib, json, re, sys, time, urllib.request, os
from statistics import median

EMAIL   = "fortis5280@gmail.com"        # ★1. 自分のメールに書き換える(SECの必須マナー)
TICKERS = []                              # ★2. 空のまま=門0の待ち行列(gate1_queue.json)から自動で未処理上位を採取
                                          #     手動指定したい時だけ ["MSFT","ANET"] のように書く
BATCH   = 5                               # 自動モードで1回に処理する銘柄数
SKIP    = ["LLY","MSFT","ASML","RMD"]     # 審査済み・採取不要の銘柄(判決が出たら追記)
QUEUE_PATHS = ["./gate1_queue.json", "./ccf/gate1_queue.json",
               "/content/drive/MyDrive/ccf/gate1_queue.json",
               "/content/drive/MyDrive/gate1_queue.json"]
HDRS  = {"User-Agent": f"hachimon-gate {EMAIL}"}
# Colab上ならGoogle Driveをマウントして MyDrive/hachimon_out に保存(Claudeが直接読める)
try:
    from google.colab import drive as _gdrive
    _gdrive.mount("/content/drive", force_remount=False)
    OUT = "/content/drive/MyDrive/hachimon_out"
except Exception:
    OUT = "out"

def get(url, binary=False):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)                       # 礼儀(10req/s未満)
    return b if binary else b.decode("utf-8", "ignore")

# ---------- ティッカー→CIK ----------
def cik_of(ticker):
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    for v in j.values():
        if v["ticker"].upper() == ticker.upper():
            return str(v["cik_str"]).zfill(10)
    raise SystemExit(f"CIK不明: {ticker}")

# ---------- 採取器の版（2026-08-13新設）----------
# ★なぜ要るか: **採取器が直ってもパックが追いつかない**という取り残しが実在した。
#   実測(2026-08-13) nde が12社で「純現金」と誤っており（ENB は実際には有利子負債 104,410百万CAD）、
#   12社とも審査日は 2026-07——その後の是正3回（08-03 無形の合成／08-07 有利子負債の二重計上を
#   恒等式で確定／08-09 規制公益の売上タグ）をどれも受け取っていなかった。
#   そして**どのパックがどの版で作られたかを記録する欄が一つも無かった**ので、
#   全社を再計算する（約40分）以外に知る方法が無かった。
# ★版は**ファイルの内容ハッシュ**にする——手で上げる定数だと必ず忘れる（この台帳が
#   版番号・堀の線・四関門の再掲で繰り返し踏んだ「数字を書き写した箇所は必ず陳腐化する」型）。
#   ⚠ 注釈を1文字直しただけでも版が変わる＝**過剰に鳴る側**。それでよい——
#   過剰に鳴れば再計算して backfill_diff が「実際は差が無い」と言うだけだが、
#   鳴らなければ取り残しが静かに残る。**片側の誤りだけを許す**設計。
def _fetcher_rev():
    try:
        with open(os.path.abspath(__file__), "rb") as _f:
            return "h" + hashlib.sha256(_f.read()).hexdigest()[:10]
    except Exception:
        return None


FETCHER_REV = _fetcher_rev()


# ---------- XBRL: 年次系列の取り出し ----------
def facts_of(cik):
    return json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))

TAGS = {  # us-gaap優先、ifrs-fullへフォールバック
 # 並び＝**意味の優先順**（series() は「代替」として1本選ぶので、総額を先・subsetを後に置く）。
 # RegulatedAndUnregulatedOperatingRevenue は規制公益の損益計算書の**最上段 OPERATING REVENUES**（総額）。
 #   これが候補に無かったため、この行を最上段に使う会社では **ASC606 の契約収益（総額の subset）** が
 #   選ばれ、営業利益率と売上CAGRが分母違いで出ていた。実害2件——
 #   **NJR**（2026-07-29に是正: gm 37.7→25.0 / cagr 10.1→0.8）と、同じ型が残っていた
 #   **NEE**（2026-08-09に是正: gm 32.1→30.2 / cagr −3.0→8.8。しかも cagr の符号が違ったので
 #   v9.9.99「事業の収縮」の関門が誤発火していた）。**同じ会社の同じ年を指しているつもりの二つの数字が、
 #   実は総額と構成要素だった**＝CLAUDE.md が無形・有利子負債・販管費で繰り返し記録している型。
 "rev":   ["Revenues","RegulatedAndUnregulatedOperatingRevenue","RevenueFromContractWithCustomerExcludingAssessedTax","RevenueFromContractWithCustomerIncludingAssessedTax","SalesRevenueNet","Revenue"],
 "gp":    ["GrossProfit"],
 "op":    ["OperatingIncomeLoss","ProfitLossFromOperatingActivities"],
 "ni":    ["NetIncomeLoss","ProfitLoss"],
 "tax":   ["IncomeTaxExpenseBenefit","IncomeTaxExpenseContinuingOperations"],
 "ocf":   ["NetCashProvidedByUsedInOperatingActivities","CashFlowsFromUsedInOperatingActivities"],
 # 2026-09-23追加（todo fetcher_small_gaps_0923）: **設備投資の行を別のタグで出す社が296社中39社あった**
 #   （V/HD/QCOM/LRCX/MSI/NVDA/TT/SPGI/LMT/WM/AWI …）——候補に無いので fcf と ni が丸ごと None だった
 #   （ni は fcf と同じ条件の中で出す）。「候補＝代替か構成要素か」を先に確かめた:
 #   ・PaymentsToAcquireProductiveAssets は**代替**（設備投資の総額。有形＋ソフト・無形を含む定義）。PP&E タグと
 #     両方ある社では同額（ALLE/ANET/FDS/LDOS/TT/UPBD 等で完全一致）か、ソフト・無形の分だけ大きい（ACI +1.7%）。
 #     series() は keys の並びで PP&E を先に採り、食い違う年がある社（CHE/SSD/TRN/CPRT: 買収や貸出資産を含む）は
 #     接がないので、PP&E タグが最新年まで届いている社では何も変わらない。
 #   ・PaymentsToAcquireOtherProductiveAssets は**ほとんどの社で構成要素**（「その他」の小さな行: DRI 26.4 vs PP&E 734.0 /
 #     PAYX 42.4 vs 234.9 / IRMD / PWR / SPGI / TRN / WCN 百万$）。だが BCPC/INCY/ROP は CF 計算書の設備投資の行そのものを
 #     このタグで出す（BCPC『Capital expenditures and intangible assets acquired』43,489千$・0000009326-26-000007 /
 #     INCY『Capital expenditures』58,867千$・0000879169-26-000010 / ROP『Capital expenditures』47.4百万$・0000882835-26-000009。
 #     BCPC の PaymentsToAcquirePropertyPlantAndEquipment は2022年で止まり注記側の値）。
 #     → 最後の候補に置く＝PP&E 系のタグが最新年に届かない社でしか主系列にならない。さらに build_numbers で
 #     「PP&E 系と重なる年に半分未満だった社」（＝構成要素）では使わない（下の capex の検問）。
 "capex": ["PaymentsToAcquirePropertyPlantAndEquipment","PurchaseOfPropertyPlantAndEquipment",
           "PaymentsToAcquireProductiveAssets","PaymentsToAcquireOtherProductiveAssets"],
 # 2026-08-08是正: **これも「候補＝代替か構成要素か」の取り違えだった**（無形・有利子負債・販管費に続く4例目）。
 #   合計タグを一つも報告せず **減価償却と無形償却を別行で出す社**がある。series() は候補から1本しか選ばないので、
 #   そういう社では D&A が丸ごと欠測 → EBITDA が営業利益だけになり **nde が過大**に出る＝財務キル(>4)の誤爆。
 #   実測 **LOAR**: 合計タグ不在で D&A=0 と読み nde 5.94（原本は Depreciation 11.9 + AmortizationOfIntangibleAssets 38.5
 #   + FinanceLeaseRightOfUseAssetAmortization 0.3 = 50.7百万$ で **nde 4.01**）。10-Kの実額 50,999千$ と整合。
 #   ※ AmortizationOfFinancingCosts は**財務費用**なので構成要素に入れない（EBITDAの D&A ではない）。
 "dep":   ["DepreciationDepletionAndAmortization","DepreciationAndAmortization","DepreciationAmortisationAndImpairmentLoss"],
 "depParts": ["Depreciation","AmortizationOfIntangibleAssets","FinanceLeaseRightOfUseAssetAmortization",
              "DepreciationNonproduction","AmortizationOfDeferredCharges"],
 "assets":["Assets"],
 "eq":    ["StockholdersEquity","StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest","Equity"],
 "gw":    ["Goodwill"],
 # 2026-07-29修正: series() は**最初に一致したタグ**を採るため、FiniteLivedIntangibleAssetsNet
 #   (耐用年数が確定した分だけ)が常に総額タグに勝ち、**無形の控除が過少になっていた**。
 #   投下資本 IC = 自己資本 + 有利子負債 − のれん − 無形 なので、控除が過少だと IC が過大に出て
 #   ROICが歪む（負であるべきICが正の小さい値になり、有限だが桁違いのROICを生む）。実測:
 #     CHE  BS計上額 82,764千$ に対し確定分 12,760千$ だけを控除 → roic 84.2（是正後はICが自己資本の
 #          23.4%・5年系列3.53倍振れでnull化）
 #     GDDY BS計上額 986.3百万$ に対し確定分 31.2百万$ だけを控除 → roic 292.2（是正後 IC=−624.2で負）
 #   総額タグを先頭に置き、無い場合のみ確定分へフォールバックする。
 # 2026-08-03修正: **上の但し書き（無期限無形が控除されず過少になる）が現実に事故を起こした。**
 #   series() は候補から**1本を選ぶ**ので、総額タグが古い年で止まっていると新しい年が丸ごと欠測になり、
 #   さらに ROIC算出側が `.get(y,0)` で**欠測をゼロと読んで**いた（絶対のルール7(a)そのもの）。
 #   実測 CELH(2025年): IntangibleAssetsNetExcludingGoodwill は**2024年で終了**しており、
 #     2025年は FiniteLived 111,910千$ ＋ **IndefiniteLived 1,280,005千$（Alani Nuのブランド）** の
 #     二本に分かれていた。IndefiniteLived は候補リストに**一つも入っていなかった**ため、
 #     無形 1,391,915千$ が丸ごと 0 として扱われ IC 947,833千$（自己資本の80.2%）＝roic 12.9 と出た。
 #     正しくは IC = 1,181,467 + 676,926 − 917,560 − 1,391,915 = **−451,082＝負** で算出不能。
 #   → 無形は有利子負債と同じく「代替」ではなく**構成要素**なので intan_series() で合成する:
 #     その年に総額タグがあれば総額、無ければ FiniteLived + IndefiniteLived を足す。
 #     2022-2024のCELHで総額=両者の和が**円単位まで一致**する（12,254 / 12,139 / 12,213）ことを確認済み。
 #   ※このリストは series() 用ではなく intan_series() の材料。並びは [総額, 確定分, 無期限分]。
 "intan": ["IntangibleAssetsNetExcludingGoodwill",
           "FiniteLivedIntangibleAssetsNet","IndefiniteLivedIntangibleAssetsExcludingGoodwill",
           "IntangibleAssetsOtherThanGoodwill"],
 # 2026-08-10: **現金タグが古い年で終わる社**を実測で確認して候補を足した（絶対のルール7）。
 #   MWA: CashAndCashEquivalentsAtCarryingValue が **2022年で終了**し、以後は
 #   CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents（ASU2016-18で多くの社が移行）。
 #   その結果 y0 の現金 431.5百万$ を **0** と読み、nde が 1.47（正しくは0.065）と出ていた。
 #   ⚠この誤りは**保守側に出る**（現金0＝より借金が多く見える）ので気づきにくい——
 #   「静かな壊れ方」の典型で、DXCの負債タグ移行とまったく同じ型。
 #   ※制限付現金を含む点は厳密には過大だが、**欠測を0と読むより桁で正しい**。
 #     順序は「純粋な現金 → 制限付込み」＝総額を後に置く（無形・負債と同じ作法）。
 "cash":  ["CashAndCashEquivalentsAtCarryingValue","CashAndCashEquivalents",
           "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
           "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations"],
 # 短期投資の BS の行。これが無い年だけ流動の AFS・満期保有・その他の短期投資で補う（STI_* と build_numbers の (5)・2026-09-23）
 "sti":   ["ShortTermInvestments","MarketableSecuritiesCurrent"],
 # 2026-07-29: 実測で取りこぼしが3件出たのでタグを拡張した（絶対のルール7「欠測をゼロと読むな」）。
 #   IDXX: リボルビング枠 LinesOfCreditCurrent 398,000千$ を数え落とし → roic 71.1→56.4
 #   CHKP: 転換社債 ConvertibleNotesPayable 1,972.1百万$ を丸ごと取りこぼし → IC 892→2,736百万$
 #   DXC : FY2026で LongTermDebtNoncurrent が消え LongTermDebtAndCapitalLeaseObligations へ移行
 #         → 負債3,552百万$が丸ごと欠落。**タグ名は年次で移行する**ので同義タグを並べて拾う
 #   なお「タグが1つも当たらない年は算出不能として飛ばす」ガードは下のROIC算出側にある。
 #   タグを増やすのは、飛ばす前にまず拾えるようにするため（飛ばすのは最後の手段）。
 # 2026-08-03: **IFRS(20-F)勢と、us-gaapの取りこぼしを追加した。** debt_evidence() が
 #   「痕跡はあるが候補タグに無い」と検出した13社を1社ずつ原本タグで確認した結果。
 #   実測 TSM(投下可): 有利子負債が ifrs-full の NoncurrentPortionOfNoncurrentBondsIssued /
 #     LongtermBorrowings / CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued /
 #     CurrentPortionOfLongtermBorrowings に入っており、us-gaap名しか並んでいなかったため
 #     **1つも当たらず debt=0 で IC が縮退**していた（NJR/HEI/APH型のADR版）。
 #   ほかに EXPD=ShortTermBankLoansAndNotesPayable / MPWR・QLYS=CommercialPaperAtCarryingValue /
 #     NBIX=ConvertibleDebtCurrent を追加。
 #   ※**リース負債は入れない**——門式の有利子負債は借入・社債であり、IFRS16のリース負債を混ぜると
 #     us-gaap勢と基準が割れる。
 #   ※**枠・利率・額面は残高ではない**ので入れない（LineOfCreditFacility*Capacity は与信枠、
 #     DebtInstrumentFaceAmount は注記の額面、*InterestRate* は利率）。下の DEBT_NOT で除外する。
 "debtL": ["LongTermDebtNoncurrent","LongTermDebt","LongTermDebtAndCapitalLeaseObligations",
           "DebtAndCapitalLeaseObligations","LongTermNotesPayable","ConvertibleLongTermNotesPayable",
           "NoncurrentBorrowings","Borrowings",
           "NoncurrentPortionOfNoncurrentBondsIssued","LongtermBorrowings","BondsIssued",
           "UnsecuredLongTermDebt","OtherLongTermDebtNoncurrent"],
 "debtS": ["LongTermDebtCurrent","DebtCurrent","LinesOfCreditCurrent","CommercialPaper",
           "ConvertibleNotesPayableCurrent","ConvertibleNotesPayable","NotesPayableCurrent",
           "CurrentBorrowings","ShortTermBorrowings",
           "CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
           "CurrentPortionOfLongtermBorrowings","ShorttermBorrowings",
           "ShortTermBankLoansAndNotesPayable","CommercialPaperAtCarryingValue",
           "ConvertibleDebtCurrent"],
 "sh":    ["CommonStockSharesOutstanding","EntityCommonStockSharesOutstanding","NumberOfSharesOutstanding"],
 "impair":["GoodwillImpairmentLoss","ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill"],
}
# ---------- 2026-09-23（todo fetcher_debt_tags_0923）: 候補に無かった負債・短期投資のタグ ----------
# ★TAGS に入れない理由: build_numbers は TAGS の全キーで series()（＝1本を選ぶ代替）を回すが、ここに並べるタグは
#   **構成要素**であり、しかも「他のタグの中に入っているかもしれない明細」なので、足してよい年を個別に確かめてから足す
#   （build_numbers の「負債タグの穴」の節）。候補ごとに「代替か構成要素か」を先に答えた（CLAUDE.md が3度記録した取り違え）:
#   ・DEBT_NEW_L＝**非流動の明細**（構成要素）。ConvertibleDebtNoncurrent（転換社債・非流動）/ LongTermLineOfCredit（リボルバー・非流動）/
#     LongTermLoansPayable / SeniorNotesNoncurrent / SeniorLongTermNotes / IFRS の …SecuredBankLoansReceived 等（銀行借入・非流動）。
#     実測で**総額の中の明細**として出す社がある（PRGS: LongTermDebtNoncurrent 534.5＝Convertible 294.5＋Other 240.0／
#     RBC 2024: LongTermDebtNoncurrent 1,188.1 ≒ LongTermLineOfCredit 695.2＋SeniorNotes 500−費用／EXLS・BRC は同額の別名）
#     → **その年に総額系のタグ（DEBT_AGG_L）が一つも無いときだけ**足す（CAMT/LMAT/GMED の転換社債・KFRC/BCPC/UTHR のリボルバー・GOOS の担保付銀行借入）。
#   ・DEBT_NEW_S＝**流動の明細**。SeniorNotesCurrent（GMED 2024: 443.4百万$）/ LoansPayableCurrent / WarehouseAgreementBorrowings（TOL の
#     住宅ローン子会社の借入枠 150.0百万$・BS に独立の行）等 → 流動の総額系（DEBT_AGG_S）と流動込みの総額（LongTermDebt 等）が無い年だけ。
#   ・DEBT_NEW_T＝**流動込みの総額**（SeniorNotes / LoansPayable は us-gaap の定義上「流動・非流動を含む」）→ 総額系が非流動にも流動にも無い年だけ
#     （TOL: Loans payable 896.4＋Senior notes 1,741.5。その内訳の OtherLoansPayable / SecuredDebt 249.1 は**入れない**＝Loans payable の中）。
DEBT_NEW_L = ["ConvertibleDebtNoncurrent", "LongTermLineOfCredit", "LongTermLoansPayable", "SeniorNotesNoncurrent",
              "SeniorLongTermNotes", "NoncurrentPortionOfNoncurrentSecuredBankLoansReceived",
              "NoncurrentPortionOfNoncurrentUnsecuredBankLoansReceived", "NoncurrentPortionOfNoncurrentLoansReceived"]
DEBT_NEW_S = ["SeniorNotesCurrent", "LoansPayableCurrent", "WarehouseAgreementBorrowings",
              "CurrentSecuredBankLoansReceivedAndCurrentPortionOfNoncurrentSecuredBankLoansReceived",
              "CurrentUnsecuredBankLoansReceivedAndCurrentPortionOfNoncurrentUnsecuredBankLoansReceived"]
DEBT_NEW_T = ["SeniorNotes", "LoansPayable", "SecuredBankLoansReceived", "UnsecuredBankLoansReceived"]
# 総額系（その年にあれば、上の明細はその中に入っていると見なして足さない＝二重計上より取りこぼしを選ぶ。取りこぼしは旧来どおり）
DEBT_AGG_L = ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations", "DebtAndCapitalLeaseObligations",
              "LongTermNotesPayable", "UnsecuredLongTermDebt", "NoncurrentBorrowings", "Borrowings", "LongtermBorrowings",
              "NoncurrentPortionOfNoncurrentBondsIssued", "BondsIssued", "DebtLongtermAndShorttermCombinedAmount"]
DEBT_AGG_S = ["LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "NotesPayableCurrent",
              "CurrentBorrowings", "CurrentPortionOfLongtermBorrowings",
              "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"]
# 流動込みの総額（非流動の総額系のうち流動分も含むもの）: これがある年は流動の明細も足さない
DEBT_AGG_LC = ["LongTermDebt", "DebtAndCapitalLeaseObligations", "Borrowings", "DebtLongtermAndShorttermCombinedAmount"]
# 短期投資の追加候補（流動の AFS・満期保有・その他の短期投資）。ShortTermInvestments / MarketableSecuritiesCurrent（BS の行）が
#   **その年に無いときだけ**使う（あるときは BS の行が正で、これらは注記の内訳のことが多い＝足すと二重計上）
STI_AFS = ["AvailableForSaleSecuritiesDebtSecuritiesCurrent", "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent"]
STI_HTM = ["HeldToMaturitySecuritiesCurrent", "DebtSecuritiesHeldToMaturityAmortizedCostAfterAllowanceForCreditLossCurrent"]
STI_OTHER = ["OtherShortTermInvestments"]
# ---------- 年の付け方（2026-09-23是正・todo fetcher_fy_label_mislabel） ----------
# ★旧 `_annual()` は年次の行を **提出書類の fy ラベル** で数えていた（`out[row["fy"]] = row["val"]`）。
#   fy は提出書類の DEI（Document Fiscal Year Focus）で**期間の年ではない**——同じ提出の比較年度の行も
#   すべて同じ fy を持ち、並び（期末順）の最後＝その提出の当期の行が勝つので、普段は正しく見えていた。
#   壊れていた型は三つ（キャッシュ済み296社・年次提出4,076件で実測）:
#   (1) **付番そのものの誤り**: STX の FY2025 10-K（0001137789-25-000157・期末 2025-06-27）は DEI が 2027
#       （R1.htm の Document Fiscal Year Focus も 2027）→ 実体の FY2026 より「新しい年」に見え、gm/ni が
#       FY2025 のまま出ていた。MWA の FY2023 10-K は 2022 → FY2022 が上書きされて消える。同型の衝突・飛びが
#       ほかに ACI/BBW/BBY/COHR/FICO/HCKT/LQDT/NVDA/PZZA/RSG/ULTA/VEEV …。1〜3月決算の社は2014年頃を境に
#       「期末の前年」→「期末の年」へ付番が変わり（NVDA/TJX/ADSK/EXP/RBC …）、TJX は 2021 が欠番
#       （FY2021→FY2026 の5年を「2020→2026＝6年」と数え cagr が過小だった）。
#   (2) **その提出にそのタグの当期の行が無い**と、比較年度の行が当期のラベルで残る: XPEL の FY2021 10-K は
#       NetIncomeLoss を 2019年分しか持たず ni[2021] に FY2019 の値、GMAB の FY2025 20-F は DKK の行が
#       2023/2024 の比較年度だけで 2025 のラベルに 2024-12-31 期の値、ANET の FY2014 10-K は
#       LongTermDebtCurrent を 2013-12-31 分しか持たず（2014年末は 0）debtS[2014] に前年の 98,793,000。
#   (3) **タグの行き来で接げない**: GOOGL は売上を Revenues（2015-17/2020/2021/2025）と
#       RevenueFromContract…（2018/2019/2022-24）で交互に付け、fy ラベルで数えた二つの dict は**重なる年が
#       一つも無い**ので series() が接がず、cagr5 は2015→2025の10年窓（18.3%・真値は5年窓 17.2%）になっていた。
#       CW/CHDN/OKE/CVCO は2年窓、AME/CELH は1年窓で同じことが起きていた。
# → 年は**期間から**付ける:
#   (a) 提出ごとの期末（FPE）＝その提出の年次の事実（300日以上の期間＋時点）の終了日のうち、件数が最大の25%以上
#       ある最も新しい日（将来の予定額など数件だけの日付に引かれない。SEC submissions の reportDate と
#       4,069/4,076件で一致し、残る7件は reportDate 側の誤り——事実の分布で確認済み）。
#   (b) 提出のラベルは「直近の付番の流儀」に揃える: c＝ラベル−期末の小数年。直近5提出のうち c が最も多く
#       揃う提出（同数なら新しい方）を錨にして前後へ歩き、**c が整数ずれた提出だけ**ラベルを整数ずらす。
#       52/53週の揺れ（±0.02）と決算期の変更（端数のずれ）は付け替えない＝整数のずれだけが付番の誤り。
#       直近の流儀に揃えるので最新年のラベルは会社の現在の呼び方のまま（TJX/BBY/HD/ROST の最新年は不変）。
#       ⚠「期末日の暦年」で数える素朴な直し方は使えない——HD/ROST は2月初めに終わる年を前年の数字で、
#       TJX/BBY は当年の数字で呼び、52/53週の社は期末が年末と年初に揺れる（固定のずらしは必ずどこかで割れる）。
#   (c) 行は**自分の期末**で年を付ける: 提出の期末から183日以内＝当期の行（提出のラベル）、それより前＝比較年度の行
#       （最寄りの提出の期末から整数年の位置にあるものだけ・その年数でラベル。格子から外れた時点＝買収日の取得原価配分や
#       決算期変更の移行期末などは使わない）、183日より後＝将来の日付＝使わない。
#   (d) 値は**当期の行を優先**（旧来どおり「その年が当期だった提出で報告された値」。同じラベルに当期の行が
#       複数あれば旧来どおり並び順の最後＝10-K/A が後から出ていればそちら）。当期の行が一つも無いラベルは、
#       **そのタグが出てくる提出のラベルの範囲内に限り**比較年度の値で埋める（最も早い提出の値）——
#       最初の提出より前へは延ばさない（上場直後の社の窓を黙って変えない）。
#   (e) 比較年度の値（格子上のもの）は**範囲の外も含めてすべて**「同じ指標か」の証拠に使う（series() の接ぎ）。
#       値としては当期優先のまま。
# ⚠ 旧来と同じ結果になることを確かめてある: 付け替え・比較年度の扱いを外すと296社すべてで出力が一致する。
from datetime import date as _date


def _pdate(s):
    try:
        return _date.fromisoformat(s)
    except Exception:
        return None


def _decyear(d):
    return d.year + (d.timetuple().tm_yday - 1) / 365.2425


_FYM_CACHE = []          # [(facts, model)]。1社の build_numbers は series() を約50回呼ぶので作り直さない


def _fy_model(facts):
    """facts 全体から「提出→(ラベル, 期末)」を作る（上の頭注 (a)(b)）。同じ facts なら使い回す。"""
    for f, m in _FYM_CACHE:
        if f is facts:
            return m
    m = _build_fy_model(facts)
    _FYM_CACHE.insert(0, (facts, m))
    del _FYM_CACHE[4:]
    return m


def _build_fy_model(facts):
    acc = {}
    filed = {}                                         # 2026-09-23: 提出日（最新の年次報告が dei だけの社の検出に使う・年の付け方には不使用）
    for ns in ("us-gaap", "ifrs-full"):
        for tag in (facts.get("facts", {}).get(ns) or {}).values():
            for rows in (tag.get("units") or {}).values():
                for r in rows:
                    if not str(r.get("form", "")).startswith(("10-K", "20-F", "40-F")):
                        continue
                    a, fy, e = r.get("accn"), r.get("fy"), r.get("end")
                    if not a or fy is None or not e:
                        continue
                    s = r.get("start")
                    if s:
                        d0, d1 = _pdate(s), _pdate(e)
                        if d0 is None or d1 is None or (d1 - d0).days < 300:
                            continue
                    x = acc.get(a)
                    if x is None:
                        x = acc[a] = ({}, {})
                    x[0][e] = x[0].get(e, 0) + 1
                    x[1][fy] = x[1].get(fy, 0) + 1
                    if (r.get("filed") or "") > filed.get(a, ""):
                        filed[a] = r["filed"]
    pts = []
    for a, (cnt, fys) in acc.items():
        m = max(cnt.values())
        thr = max(min(2, m), 0.25 * m)
        fpe = _pdate(max(e for e, n in cnt.items() if n >= thr))
        if fpe is not None:
            pts.append([fpe, max(fys, key=lambda k: fys[k]), a])
    pts.sort(key=lambda p: (p[0], p[2]))
    n = len(pts)
    if not n:
        return {"acc": {}, "pts": [], "fixed": {}, "filed": {}}
    c = [p[1] - _decyear(p[0]) for p in pts]
    last = list(range(max(0, n - 5), n))
    sup = {i: sum(1 for j in last if abs(c[j] - c[i]) <= 0.2) for i in last}
    ai = max(i for i in last if sup[i] == max(sup.values()))
    lab = [p[1] for p in pts]
    fixed = {}
    for rng in (range(ai + 1, n), range(ai - 1, -1, -1)):
        ref = c[ai]
        for i in rng:
            d = c[i] - ref
            k = round(d)
            if k != 0 and abs(d - k) <= 0.2:          # 整数のずれ＝付番の誤り
                lab[i] = pts[i][1] - k
                fixed[pts[i][2]] = (pts[i][1], lab[i], pts[i][0].isoformat())
                ref = c[i] - k
            else:                                     # 揺れ・決算期の変更はそのまま追う
                ref = c[i]
    return {"acc": {pts[i][2]: (lab[i], pts[i][0]) for i in range(n)},
            "pts": [(pts[i][0], lab[i]) for i in range(n)],
            "fixed": fixed,
            "filed": {pts[i][2]: filed.get(pts[i][2]) for i in range(n)}}


def _label_for(fym, d):
    """比較年度の行の期末 d のラベル＝最寄りの提出の期末からの年数（決算期の変更をまたいでも局所で数える）。
    **期末の格子から外れた日付は None**（年次の値ではない）: 最寄りの期末から整数年±0.05年（約18日）に
    無い時点は、買収日の取得原価配分・決算期変更の移行期末などで、どの年度の期末残高でもない
    （実測 IRDM: FY2024 10-K の Goodwill 98,186,000 は 2024-04-01＝買収日の値。格子を見ないと 2023年末ののれんに化ける）。"""
    p = min(fym["pts"], key=lambda q: abs((d - q[0]).days))
    yrs = (d - p[0]).days / 365.2425
    k = round(yrs)
    if abs(yrs - k) > 0.05:
        return None
    return p[1] + k


class _Yearly(dict):
    """年→値の dict（当期の値＋範囲内の比較年度の埋め）。付帯情報:
       cmp  … 比較年度の値で埋めた年（当期の行が一つも無かった年）
       ev   … 比較年度の値をすべて含む年→値（series() の「同じ指標か」の証拠。値としては使わない）
       snap … 会社の提出の範囲内で当期の行が無い年の (提出日|accn, 値)（series_sum の比較年度の補い）"""
    cmp = frozenset()
    ev = None
    snap = None


def _annual(units, fym=None):
    """単位ごとのXBRL行から年次dictを組む。最多データの単位を優先。年の付け方は上の頭注。"""
    accm = (fym or {}).get("acc") or {}
    pts = (fym or {}).get("pts") or []
    snap_only = None
    for u in sorted(units.keys(), key=lambda x: -len(units[x])):
        cur, cmpv, labs = {}, {}, set()
        for row in units[u]:
            # 2026-07-29: **40-F を足した**。カナダのMJDS登録企業は年次報告が40-Fで、
            #   ここに無いと全タグが「不発見」になり build_numbers が丸ごと None を返す。
            #   実害: DSGX(Descartes) は機械値が一つも取れず、しかも latest_annual_url が
            #   同じ理由で40-Fを飛ばして**2005年の20-F**（同社が最後に出した20-F）を原本として掴んでいた。
            #   「審査日は今日なのに読んだ紙が21年前」の正体はこの2行だった。
            if not row.get("form","").startswith(("10-K","20-F","40-F")): continue
            fy = row.get("fy")
            if fy is None: continue
            s, e = row.get("start"), row.get("end")
            d1 = _pdate(e) if e else None
            if s and e:  # 損益・CF系は期間300日超のみ(四半期を排除)
                d0 = _pdate(s)
                if d0 is not None and d1 is not None and (d1 - d0).days < 300: continue
            ent = accm.get(row.get("accn"))
            if ent is None or d1 is None:
                cur[fy] = row["val"]                   # 期末が決められない提出＝旧来どおり fy ラベル
                labs.add(fy)
                continue
            lab, fpe = ent
            dd = (d1 - fpe).days
            if dd > 183:
                continue                               # 期末より後の日付（将来の予定額など）は年次値に使わない
            labs.add(lab)
            if dd >= -183:
                cur[lab] = row["val"]                  # 当期の行: 並び順の最後が勝つ（旧来どおり）
                continue
            y = _label_for(fym, d1)                    # 比較年度の行: 自分の期末で年を付ける
            if y is None:
                continue                               # 期末の格子から外れた時点（買収日など）は使わない
            src = (row.get("filed") or "") + "|" + (row.get("accn") or "")
            prev = cmpv.get(y)
            if prev is None or src <= prev[0]:         # 最も早い提出の値（同じ提出なら並び順の最後）
                cmpv[y] = (src, row["val"])
        if not (cur or cmpv):
            continue
        lo, hi = min(labs), max(labs)
        clo, chi = (min(p[1] for p in pts), max(p[1] for p in pts)) if pts else (lo, hi)
        fill = {y for y in cmpv if y not in cur and lo <= y <= hi}
        out = _Yearly((y, cur[y] if y in cur else cmpv[y][1]) for y in sorted(set(cur) | fill))
        out.cmp = frozenset(fill)
        ev = {y: v for y, (_s, v) in cmpv.items()}
        ev.update(cur)
        out.ev = ev
        out.snap = {y: cmpv[y] for y in cmpv if y not in cur and clo <= y <= chi}
        if out:
            return out, u
        if out.snap and snap_only is None:
            snap_only = (out, u)                       # 比較年度の行しか無い単位（series_sum の補いにだけ使う）
    if snap_only is not None:
        return snap_only
    return None, None


def _cur_only(d):
    """当期の行の値だけ（比較年度で埋めた年を除く）"""
    cm = getattr(d, "cmp", None)
    return {y: v for y, v in d.items() if y not in cm} if cm else dict(d)


def series(facts, keys, unit_pref=("USD","EUR","JPY")):
    """候補タグの中から**最新年まで届いている系列**を主系列に選ぶ。

    2026-07-29修正: 従来は「keys の中で最初に見つかったタグ」を無条件で採用し、
      他のタグを一切見なかった。米国企業はASC606適用(2018年前後)で売上タグを
      Revenues → RevenueFromContractWithCustomerExcludingAssessedTax へ改称しており、
      旧タグが先頭にあるため**2017年で止まった系列で成長率・利益率を測っていた**。
      実測 BR: 売上系列が 2012→2017 で終わっており、8年前の数字でcagrを出していた。
      「最初に見つかったタグが正しい」もまた、確かめていない前提＝絶対のルール7と同型。

    重なる年で値が一致するタグだけを接ぐ（一致しなければ別の指標＝接がない）。
    重なりが無い場合も接がない——同一指標だと確かめる手段が無いため。主系列だけで足りる。
    2026-09-23: 当期の値どうしに重なりが無いときは、**比較年度の値**も「同じ指標か」の証拠に使う
      （GOOGL の売上は二つのタグを年ごとに行き来し、当期の値どうしは一年も重ならない。だが FY2020 10-K の
      Revenues は 2018/2019 を、FY2022 10-K の RevenueFromContract… は 2020/2021 を比較年度として持ち、
      同じ年の値が一致する）。当期の値どうしに重なりがあるときは旧来どおりその年だけで裁く。
      接いだ系列の値は**当期の値が先**（主系列→接いだタグ）、比較年度の埋めは最後。
    """
    fym = _fy_model(facts)
    cands = []
    for ns in ("us-gaap","ifrs-full","dei"):
        d = facts.get("facts",{}).get(ns,{})
        for i, k in enumerate(keys):
            if k not in d: continue
            out, u = _annual(d[k]["units"], fym)
            if out: cands.append((i, k, out, u))
        if cands: break            # 名前空間はまたがない(us-gaapとifrsを混ぜない)
    if not cands: return {}, None

    # 主系列の選び方: **keys の並び（＝意味の優先順）を守る**。ただし著しく古い系列は退ける。
    #   単純に「最新年が新しいタグ」を採ると、意味の違うタグへ黙って乗り換える事故が起きる
    #   （実測 BKNG: eq が StockholdersEquity → …IncludingPortionAttributableToNoncontrollingInterest
    #   へ乗り換わり roicg 53.1→17.8 と桁近く動いた）。**古い値も危険だが、意味の違う値はもっと危険。**
    #   → 最新年から1年以内に届いている候補の中で、keys の優先順が最も高いものを主系列にする。
    # 2026-08-04是正(B12f): unit_pref は宣言だけで**一度も使われていなかった**（呼び手は
    #   ("shares",) を渡して単位フィルタを期待していた）。**優先フィルタ**として実装する——
    #   候補に希望単位の系列があればそれだけに絞る（株数の候補にUSD等の別単位系列が混ざって
    #   主系列に選ばれる型の事故を防ぐ）。希望単位が一つも無ければ全候補を残す
    #   （TWD/INR等の現地通貨報告を弾かないため＝厳格フィルタにすると20-F勢が全滅する）。
    if unit_pref:
        _pref = [c for c in cands if c[3] in unit_pref]
        if _pref:
            cands = _pref
    newest = max(max(c[2]) for c in cands)
    elig = [c for c in cands if max(c[2]) >= newest - 1]
    i, k0, prim, unit = min(elig, key=lambda c: (c[0], -max(c[2])))
    merged = _cur_only(prim)                       # 当期の値（旧来の突き合わせはこれだけで行う）
    seen = dict(prim.ev or prim)                   # 比較年度も含む証拠
    fills = [prim]
    for _, k, out, u in cands:
        if k == k0 or u != unit: continue
        oc = _cur_only(out)
        ov = set(oc) & set(merged)
        if ov:
            if any(merged[y] and abs(oc[y]-merged[y])/abs(merged[y]) > 0.02 for y in ov):
                continue                           # 重なる年で食い違う＝別の指標
        else:
            oe = out.ev or out
            ov = set(oe) & set(seen)
            if not ov: continue                    # 比較年度を含めても重なり無し＝同一指標と確かめられない
            if any(seen[y] and abs(oe[y]-seen[y])/abs(seen[y]) > 0.02 for y in ov):
                continue
        for y, v in oc.items():
            merged.setdefault(y, v)
        for y, v in (out.ev or out).items():
            seen.setdefault(y, v)
        fills.append(out)
    for t in fills:                                # 比較年度の埋めは最後（当期の値を上書きしない）
        for y in sorted(t.cmp):
            merged.setdefault(y, t[y])
    return merged, unit

def last_n(d, n=6):
    ys = sorted(d)[-n:]
    return ys, [d[y] for y in ys]

def _safe(ev, note, key, fn):
    try:
        v = fn()
        if v is not None: ev[key] = v
    except Exception as e:
        note.append(f"{key}: 計算失敗({type(e).__name__})")

def _u(x):
    """実額を読める形に。桁を落とさず、単位を書かずに済ませない。"""
    try:
        return f"{float(x):,.0f}"
    except Exception:
        return str(x)


# 2026-08-03: **InterestExpense を外した。** 痕跡として探すべきは債務の**残高**であって費用ではない。
#   実測の偽陽性: MANH は `UnrecognizedTaxBenefitsIncomeTaxPenaltiesAndInterestExpense`（税の延滞利息）、
#   TTD は `InterestExpenseNonoperating` 1,656千$（リース等）しか無いのに「債務あり」と判定され、
#   **本当に無借金の会社のROICが永久に算出不能**になっていた。
DEBT_EVI = re.compile(r"LongTermDebt|NotesPayable|Borrowing|LinesOfCredit|CommercialPaper"
                      r"|ConvertibleNotes|DebtCurrent|DebtInstrument")
# 投資有価証券側の「債券」は債務ではない。ここを除かないと現金の厚い会社が全部「債務あり」になる
DEBT_NOT = re.compile(r"AvailableForSale|DebtSecurit|TradingSecurit|HeldToMaturity"
                      r"|Maturities|Repayments|Proceeds|WeightedAverage|FairValue|Unamortized"
                      # 2026-08-03: 以下は**債務残高ではない**ので痕跡に数えない。数えると
                      #   本当に無借金の会社（実測 GRVY/MANH/TTD/VEEV）が永久に算出不能になる。
                      #   InstrumentsHeld は**保有している債券＝投資**（実測 TSM の
                      #   CorporateDebtInstrumentsHeld 190,568百万TWD は資産であって債務ではない）。
                      r"|InstrumentsHeld|Capacity|FaceAmount|InterestRate|StatedPercentage"
                      r"|Covenant|Guarantee|Undrawn|Available")
# 2026-09-23追加（todo fetcher_debt_tags_0923）: **上の正規表現にも候補にも無い負債タグ**があり、古い負債タグを持たない社では
#   「痕跡ゼロ＝実質無借金」（嘘の純現金）になっていた——ConvertibleDebtNoncurrent（転換社債・非流動）/ LongTermLineOfCredit・LineOfCredit
#   （単数形。上の LinesOfCredit は複数形しか拾わない＝KFRC のリボルバー 66.4百万$）/ LoansPayable・SeniorNotes 系（TOL）/
#   IFRS の …LoansReceived（GOOS の担保付銀行借入 407.7百万CAD）/ DebtLongtermAndShorttermCombinedAmount（負債総額）ほか。
#   ⚠ これらの名前は**流量**（InterestOnConvertibleDebtNetOfTax・AdjustmentsToAdditionalPaidInCapital…ConvertibleDebt・
#   EarlyRepaymentOfSubordinatedDebt）や**資産**（DebtIssuanceCostsLineOfCreditArrangementsNet＝繰延の発行費用）にも現れる
#   （実測296社）。上の正規表現を広げると既存の判定まで変わるので別に置き、**時点の値（残高）だけ**を痕跡に数え、下の語を除く。
DEBT_EVI2 = re.compile(r"ConvertibleDebt|ConvertibleSubordinatedDebt|LineOfCredit(?!Facility)|LoansPayable|SeniorNotes"
                       r"|SeniorLongTermNotes|LoansReceived|DebtLongtermAndShorttermCombinedAmount|SecuredDebt|UnsecuredDebt"
                       r"|SubordinatedDebt|DebenturesIssued")
DEBT_NOT2 = re.compile(r"Issuance|Cost|Accumulated|Assumed|Interest|Adjustment|Repayment|Induced|Expense")


def debt_evidence(facts, year, span=2):
    """有利子負債の**痕跡**を候補タグの外まで独立に走査する（2026-08-03新設）。

    なぜ要るか: 「候補タグに当たらない」だけでは
      (a) 本当に無借金  と  (b) 我々が知らないタグで報告している  を区別できない。
    (b)を(a)と誤れば NJR/HEI/APH の事故（debt=0でICが縮退しROICが発散）を再発させ、
    (a)を(b)と誤れば IRMD のように**無借金の優良企業のROICが永久に算出不能**になる。
    どちらも「確かめていない前提」なので、上限の不等式で決着させる——
    対象年から span 年以内に債務らしき残高が**一つも無い**なら、債務ゼロは事実。

    返り値: 生きた痕跡の "タグ名(年)=値" のリスト（空なら痕跡ゼロ＝無借金と断定してよい）
    2026-09-23: DEBT_EVI に無かった負債タグ（転換社債・リボルバー・LoansPayable・SeniorNotes・IFRS の …LoansReceived 等）を
      DEBT_EVI2 で拾う。こちらは**年次報告の残高（時点の値）**だけを数える（名前が同じ流量・繰延費用や、10-Q の期中の残高を除く）。
    """
    out = []
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        for k in d:
            if DEBT_NOT.search(k):
                continue
            old = bool(DEBT_EVI.search(k))
            if not old and (not DEBT_EVI2.search(k) or DEBT_NOT2.search(k)):
                continue
            for arr in d[k]["units"].values():
                for x in arr:
                    if not old and (x.get("start") or not str(x.get("form", "")).startswith(("10-K", "20-F", "40-F"))):
                        continue                      # 追加の型（DEBT_EVI2）は**年次報告の残高（時点の値）**だけを痕跡に数える
                        #   （TTD: 2020年3月に引き出し年内に返したリボルバー 143百万$ が10-Qの LongTermLineOfCredit に残る。
                        #   年末残高はゼロ＝2021・2022年の無借金を止める痕跡ではない）
                    try:
                        y = int(x["end"][:4]); v = float(x["val"])
                    except Exception:
                        continue
                    if abs(y - year) <= span and v > 0:
                        out.append(f"{k}({y})={v:,.0f}")
                        break
                else:
                    continue
                break
    return sorted(set(out))


def series_sum(facts, keys, total_key=None, meta=None):
    """**足し合わせるべきタグ**を合計する。series() は候補から1本を選ぶので有利子負債には使えない。
    meta: dict を渡すと、選んだ名前空間と主単位を meta["ns"] / meta["unit"] に書く（2026-09-23・値は変えない）。

    2026-07-29修正: debtS は LongTermDebtCurrent / LinesOfCreditCurrent / CommercialPaper …
      と**同時に存在しうる別の科目**なのに、series() が優先順で1本だけ選んでいた。
      実測 IDXX: LongTermDebtCurrent が選ばれ、リボルビング枠 LinesOfCreditCurrent 398,000千$ が
      丸ごと落ちて roic 71.1（真値56.4）。**タグを候補リストに足しても、選ぶ実装のままでは拾えない**
      ——2026-07-29 に debtS のタグを9個へ拡張したのに IDXX が直らなかったのはこれが理由で、
      審査官が手で直していた。「候補＝代替」と「候補＝構成要素」を取り違えていた。

    total_key: 総額系タグ。**str または 優先順の列挙(複数可)**（2026-08-04是正・A7）。
      その年にいずれかの総額タグが存在するなら**合計せず最優先の総額を採る**（二重計上を避ける）。
      なぜ複数か: IFRS勢の `Borrowings` は流動込みの総額として報告されることが多く、その内数
      `LongtermBorrowings` と**同時に報告される**。旧実装は総額を1本しか知らなかったため両方を
      構成要素として合算した——実測 WIT: Borrowings 161,817百万INR ＋ LongtermBorrowings
      63,954百万INR を足して約64B INRを二重計上（**既納品の WIT パックは要再採取**。パックは
      ここでは直さない＝審査官の検算経路を通す）。
    2026-08-04是正(A7): series() と同じ**名前空間・単位の一致検問**を追加した。旧実装はタグごとに
      us-gaap/ifrs-full を独立に探し、単位も見ずに合算していた＝別名前空間・別単位の値を
      足し合わせうる（「基準の違う二つを割る」型の合算版）。名前空間はまたがず、
      主単位（最多）と違う単位のタグは合算から外す。
    2026-09-23（年の付け方の是正と対）: **合計には当期の値だけを使う**（series() の比較年度の埋めは使わない）。
      タグの付け替え年に「旧タグの当期の値」と「新タグの比較年度の値」を足すと二重計上になるため。
      旧実装は比較年度の行を当期のラベルで数えていたので、返済済みの負債が翌年も残っていた
      （実測 ANET: FY2014 10-K の LongTermDebtCurrent は 2013-12-31 の 98,793,000 だけ＝2014年末は 0。
      MNST: FY2025 10-K の LongTermDebt は 2024-12-31 の 373,951,000 だけ）。
      例外は**どの提出でも当期の値として出てこないタグ**（比較年度の行しか無い）: その期間を当期として報告した
      提出がどのタグにも無い年に限り、**最も早い提出一つ分**の値で補う（別々の提出の比較値を足さない）。
      実測 QLYS: CommercialPaperAtCarryingValue は FY2025 10-K の 2024-12-31（6,443,000）にしか無い。
      補わないと候補タグの値が debt_evidence() に「未知のタグの痕跡」として見え、2022-25年の roic が止まる。
    """
    if isinstance(total_key, str):
        total_keys = [total_key]
    else:
        total_keys = list(total_key or [])
    per, unit_of, snaps = {}, {}, {}
    fym = _fy_model(facts)
    ns_used = None
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        found = False
        for k in keys:
            if k not in d:
                continue
            out, u = _annual(d[k]["units"], fym)
            if out is None:
                continue
            cur = _cur_only(out)
            if not cur and out.snap:
                snaps[k] = (out.snap, u)
                found = True
            if cur:
                per[k] = cur
                unit_of[k] = u
                found = True
        if found:
            ns_used = ns
            break                        # 名前空間はまたがない（series()と同じ）
    if not per and not snaps:
        return {}, {}
    # 単位の一致検問: 最多の単位を主単位とし、違う単位のタグは合算しない（足すと桁が壊れる）
    _cnt = {}
    for u in list(unit_of.values()) + [u for _v, u in snaps.values()]:
        _cnt[u] = _cnt.get(u, 0) + 1
    main_u = max(_cnt, key=lambda u: _cnt[u])
    if meta is not None:
        meta["ns"], meta["unit"] = ns_used, main_u
    for k in [k for k in per if unit_of[k] != main_u]:
        del per[k]
    years = set().union(*[set(v) for v in per.values()]) if per else set()
    out, used = {}, {}
    _snapY = {}
    for k, (sv, u) in snaps.items():
        if u != main_u:
            continue
        for y, (src, v) in sv.items():
            if y not in years:                   # その年を当期として報告した構成要素が一つも無い年だけ
                _snapY.setdefault(y, {})[k] = (src, v)
    for y, kv in _snapY.items():
        src0 = min(src for src, _v in kv.values())
        one = {k: v for k, (src, v) in kv.items() if src == src0}     # 最も早い提出一つ分
        tk = next((k for k in total_keys if k in one), None)
        if tk is not None:
            out[y] = one[tk]
            used[y] = [f"{tk}(総額・比較年度 {src0.split('|')[-1]})"]
            continue
        parts = [(k, one[k]) for k in keys if k not in total_keys and k in one]
        if parts:
            out[y] = sum(v for _, v in parts)
            used[y] = [f"{k}={v:,.0f}(比較年度 {src0.split('|')[-1]})" for k, v in parts]
    for y in years:
        tk = next((k for k in total_keys if k in per and y in per[k]), None)
        if tk is not None:
            out[y] = per[tk][y]
            used[y] = [f"{tk}(総額)"]
            continue
        parts = [(k, per[k][y]) for k in keys if k not in total_keys and k in per and y in per[k]]
        if not parts:
            continue
        out[y] = sum(v for _, v in parts)
        used[y] = [f"{k}={v:,.0f}" for k, v in parts]
    return out, used


# ---------- 2026-09-23（todo fetcher_debt_tags_0923）の道具 ----------
def _tag_cur(facts, key, nss=("us-gaap", "ifrs-full")):
    """1本のタグの**当期の値だけ**（比較年度の埋めを含まない）と単位・名前空間。無ければ ({}, None, None)"""
    fym = _fy_model(facts)
    for ns in nss:
        d = facts.get("facts", {}).get(ns, {})
        if key in d:
            out, u = _annual(d[key]["units"], fym)
            if out:
                return _cur_only(out), u, ns
    return {}, None, None


def _tag_ev(facts, key, nss=("us-gaap", "ifrs-full")):
    """1本のタグの**当期の値＋（当期の値が無い年は）翌年以降の提出の比較年度の値**と単位。恒等式の証拠にだけ使う（値としては使わない）。
    実測 WSO: オペレーティングリース負債のタグは FY2022 10-K から当期の行があり、2021年末の値（非流動 187.0・流動 81.9百万$）は
    FY2022 10-K の比較年度の列にしか無い"""
    fym = _fy_model(facts)
    for ns in nss:
        d = facts.get("facts", {}).get(ns, {})
        if key in d:
            out, u = _annual(d[key]["units"], fym)
            if out:
                return dict(out.ev or out), u, ns
    return {}, None, None


def _filing_vals(facts, key, accn, ns, unit):
    """1つの提出（accn）が key について報告した**年次の期間の値** {期末: 値}（当期・比較年度の列すべて）"""
    d = facts.get("facts", {}).get(ns, {})
    out = {}
    for r in ((d.get(key) or {}).get("units") or {}).get(unit) or []:
        if r.get("accn") != accn or not r.get("start"):
            continue
        d0, d1 = _pdate(r["start"]), _pdate(r.get("end") or "")
        if d0 is None or d1 is None or (d1 - d0).days < 300:
            continue
        out[r["end"]] = r["val"]
    return out


def _used_vals(used):
    """series_sum の内訳の文（"タグ=1,234"）から {タグ: 値}。総額の年（"…(総額)"）は値を持たない"""
    out = {}
    for x in used or []:
        m = re.match(r"([A-Za-z0-9]+)=(-?[\d,]+)", x)
        if m:
            try:
                out[m.group(1)] = float(m.group(2).replace(",", ""))
            except ValueError:
                pass
    return out


def _lease_residual(x, oll, fll, others=()):
    """x（LongTermDebtAndCapitalLeaseObligations 系の値）が**リース負債（＋別に報告された借入の明細）と恒等式で一致**するか。
    一致すれば (内訳の名, リース額, x の中の借入分) を返す（借入分は 0 か others のどれか）。一致しなければ None。
    ±0.5% の一致だけを証拠にする（のれんの上限・LongTermDebt の総額判定と同じ作法）。"""
    if not x:
        return None
    cands = []
    if oll and fll:
        cands.append(("オペレーティング＋ファイナンスリース", oll + fll))
    if fll:
        cands.append(("ファイナンスリース", fll))
    if oll:
        cands.append(("オペレーティングリース", oll))
    tol = 0.005 * abs(x)
    for nm, lv in cands:
        r = x - lv
        if abs(r) <= tol:
            return nm, lv, 0
        for ov in others:
            if ov and abs(r - ov) <= tol:
                return nm, lv, ov
    return None


def _dep_subtotal_fix(facts, y, T):
    """D&A の総額タグの値 T（y 年）が**小計**だと証明できるなら、証明できる下限の最大値を返す。無ければ None。
    証明＝T を出した提出の中で、どれかの年の列で T が構成要素（無形の償却 A・減価償却 D）より**小さい**
    （総額は構成要素以上のはず。0.5% を超えて下回れば、その行は A か D の全部を含んでいない）。
    置き換える値は**下限として確かなものだけ**の最大: T・D・A・他の総額タグ、そして T が A を含まないと証明できたときの T＋A。
    ⚠ D＋A は使わない——D が総額の誤用のことがある（BBY: CF の『Depreciation and amortization』831 に DDA、注記の
    Depreciation も 831、無形の償却 14 は別＝831 は総額。D＋A は 845 で過大）。"""
    fym = _fy_model(facts)
    hit = None
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        for k in TAGS["dep"]:
            for u, rows in ((d.get(k) or {}).get("units") or {}).items():
                for r in rows:
                    if r.get("val") != T or not r.get("start"):
                        continue
                    ent = fym["acc"].get(r.get("accn"))
                    d0, d1 = _pdate(r["start"]), _pdate(r.get("end") or "")
                    if ent is None or d0 is None or d1 is None or (d1 - d0).days < 300:
                        continue
                    if ent[0] == y and abs((d1 - ent[1]).days) <= 183:
                        hit = (ns, k, u, r["accn"])       # 当期の行（旧来どおり並び順の最後）
        if hit:
            break
    if not hit:
        return None
    ns, k, u, accn = hit
    Tv = _filing_vals(facts, k, accn, ns, u)
    Av = _filing_vals(facts, "AmortizationOfIntangibleAssets", accn, ns, u)
    Dv = _filing_vals(facts, "Depreciation", accn, ns, u)
    excA = sorted(e for e in Tv if Av.get(e) and Tv[e] < Av[e] * 0.995)
    belowD = sorted(e for e in Tv if Dv.get(e) and Tv[e] < Dv[e] * 0.995)
    if not (excA or belowD):
        return None

    def _v(tag):
        v, uu, _ = _tag_cur(facts, tag, (ns,))
        return v.get(y) if uu == u else None
    A0, D0 = _v("AmortizationOfIntangibleAssets"), _v("Depreciation")
    T2 = {k2: _v(k2) for k2 in TAGS["dep"] if k2 not in (k, "DepreciationAmortisationAndImpairmentLoss")}
    cands = [("総額タグ", T)] + [(nm, x) for nm, x in (("Depreciation", D0), ("AmortizationOfIntangibleAssets", A0)) if x]
    cands += [(k2, x) for k2, x in T2.items() if x]
    if excA and A0:
        cands.append((f"{k}＋AmortizationOfIntangibleAssets", T + A0))
    nm, new = max(cands, key=lambda c: c[1])
    if new <= T * 1.005:
        return None
    return new, {"tag": k, "accn": accn, "excA": excA, "belowD": belowD, "A": Av, "D": Dv, "T": Tv, "pick": nm}


def _dei_only_annual(facts):
    """最新の年次報告が companyfacts に**dei の事実だけ**で載っているか（財務の数字が未収載）。
    実測: 2026年提出の20-F（TSM・CEPU・INFY ほか）は EntityCommonStockSharesOutstanding しか無く、採取器は黙って前年を使っていた。
    訂正報告（10-K/A 等）は Part III だけのことが多く財務を持たないのが普通なので数えない。
    返り値: [(accn, form, 提出日, DEI の年度)]（財務のある最新の年次報告より後に提出されたものだけ）"""
    fym = _fy_model(facts)
    filed = [v for v in (fym.get("filed") or {}).values() if v]
    if not filed:
        return []
    last = max(filed)
    out = {}
    for tag in (facts.get("facts", {}).get("dei") or {}).values():
        for rows in (tag.get("units") or {}).values():
            for r in rows:
                a = r.get("accn")
                if r.get("form") not in ("10-K", "20-F", "40-F") or not a or a in fym["acc"]:
                    continue
                if (r.get("filed") or "") > last:
                    out[a] = (r.get("form"), r.get("filed"), r.get("fy"))
    return sorted(((a,) + v for a, v in out.items()), key=lambda x: x[2])


def build_numbers(facts):
    S, diag = {}, {}
    for k, v in TAGS.items():
        S[k] = series(facts, v)[0]
        diag[k] = f"{len(S[k])}年分" if S[k] else "タグ不発見"
    # 有利子負債だけは「代替」でなく「構成要素」なので合計する（上の series は上書き）
    # 2026-08-04是正(A7): debtL の総額は LongTermDebt(us-gaap) と Borrowings(IFRS・流動込み総額の
    #   ことが多い) の2本。Borrowings を構成要素扱いすると内数 LongtermBorrowings と二重計上する
    #   （実測 WIT で約64B INR。詳細は series_sum の頭注）
    _dmS, _dmL = {}, {}
    S["debtS"], _usedS = series_sum(facts, TAGS["debtS"], total_key="DebtCurrent", meta=_dmS)
    S["debtL"], _usedL = series_sum(facts, TAGS["debtL"], total_key=("LongTermDebt", "Borrowings"), meta=_dmL)
    # 旧来の候補タグで報告のある年（下の「負債タグの穴」の節で足す明細の年とは分けて持つ。nde の無借金判定・ROIC の欠測判定で使う）
    _origDebtYears = set(S["debtL"]) | set(S["debtS"])
    # 2026-08-07是正: **`LongTermDebt` が総額か非流動のみかは、恒等式で機械的に判る。**
    #   旧実装は「機械では区別できない」として警告だけ出していた（下の _dbl）が、その年に
    #   `LongTermDebt ≒ LongTermDebtNoncurrent + LongTermDebtCurrent` が成り立てば
    #   **LongTermDebt は総額であることが証明される**（のれんの上限＝無形総額 と同じ「不等式・恒等式で
    #   結論を出す」作法。ルール7に触れない）。成り立つ年だけ 1年内返済分を debtS から差し引く。
    #   実害の実測（WIT・IDXX に続く3例目）: **LRCX** は全年でこの恒等式が成立し、
    #   FY2024 +501 / FY2025 +750百万$ の負債過大 → through-cycle roic が 42.4% と出るべきところ 40.1%。
    #   IC が過大＝ROIC は**過小**に出るので、この事故は「保守的な誤り」に見えて実は
    #   Ω の実効36.5%を占める単一最大の入力を静かに削っていた。
    _ltc = series(facts, ["LongTermDebtCurrent"])[0]
    _ltn = series(facts, ["LongTermDebtNoncurrent"])[0]
    _ltd = series(facts, ["LongTermDebt"])[0]
    _fixed = []
    for _y in sorted(set(_ltc) & set(_ltn) & set(_ltd)):
        if not any("LongTermDebt(総額)" in x for x in (_usedL.get(_y) or [])):
            continue
        if not any(x.startswith("LongTermDebtCurrent=") for x in (_usedS.get(_y) or [])):
            continue
        _sum = _ltn[_y] + _ltc[_y]
        if _ltd[_y] <= 0 or abs(_ltd[_y] - _sum) / abs(_ltd[_y]) > 0.005:
            continue                      # 恒等式が成り立たない＝LongTermDebt は非流動のみ。触らない
        S["debtS"][_y] = (S["debtS"].get(_y, 0) or 0) - _ltc[_y]
        _usedS[_y] = [x for x in _usedS[_y] if not x.startswith("LongTermDebtCurrent=")] + \
                     [f"LongTermDebtCurrent={_ltc[_y]:,.0f}は総額に含まれるため控除"]
        _fixed.append(_y)
    # 2026-09-23是正: 同じ二重計上が **`DebtCurrent`（総額タグ）** 経由でも起きていた。上の是正は
    #   `LongTermDebtCurrent` がある年しか見ないので、1年内返済分を DebtCurrent だけで報告する会社を素通りした。
    #   実測 **CW**: LongTermDebt 957,884 = LongTermDebtNoncurrent 757,884 + DebtCurrent 200,000（千$）が
    #   全年で成立（2020/2022/2024/2025 に1年内返済分）→ 負債が 200,000 過大・roic 33.7%（真値39.1%）。
    #   同じ恒等式で総額と証明できた年だけ DebtCurrent を控除する（成り立たない年は CP 等を含みうるので触らない）。
    _dc = series(facts, ["DebtCurrent"])[0]
    for _y in sorted(set(_dc) & set(_ltn) & set(_ltd)):
        if _y in _fixed or _y in _ltc:
            continue
        if not any("LongTermDebt(総額)" in x for x in (_usedL.get(_y) or [])):
            continue
        if (_usedS.get(_y) or []) != ["DebtCurrent(総額)"] or not _dc[_y]:
            continue
        _sum = _ltn[_y] + _dc[_y]
        if _ltd[_y] <= 0 or abs(_ltd[_y] - _sum) / abs(_ltd[_y]) > 0.005:
            continue
        S["debtS"][_y] = (S["debtS"].get(_y, 0) or 0) - _dc[_y]
        _usedS[_y] = [f"DebtCurrent={_dc[_y]:,.0f}は LongTermDebt 総額に含まれるため控除"]
        _fixed.append(_y)
    _fixed.sort()
    # 2026-09-23是正(2): **debtL の中で「同じ負債の別名」と「流動込みの総額」を足していた**（候補＝代替か構成要素か、の5例目）。
    #   series_sum は total_key 以外を構成要素として合計するが——
    #   (a) LongTermDebtNoncurrent と LongTermDebtAndCapitalLeaseObligations は**同じ非流動負債の別名**（後者はリース込み）で、
    #       両方を報告する社では同額が二度入る（実測 ASML 2025: 2,709百万€×2 ／ IP 8,839百万$×2）。
    #   (b) DebtAndCapitalLeaseObligations は**流動分込みの総額**（リース込み）。非流動の別名と足すと非流動が二重になり、
    #       さらに debtS の流動分とも重なる（実測 EBAY 2025: 5,996 + 6,746 + 流動750 ＝ **13,492**＝原本の総額 6,746 の2倍。
    #       nde は 4.31＝財務キルの線を越えていた。HXL は 993百万$×2 で nde 6.52 ＝キルが誤発火）。
    #   → (a) 別名どうしが同額（±0.5%）なら1本だけ数える。
    #     (b) DebtAndCapitalLeaseObligations が「残りの非流動 + 流動(debtS)」と恒等式で一致する年は、それが総額だと
    #         証明できるので**足さない**（流動分は debtS に残る）。一致しない年は触らず注記だけ（機械で確定できない）。
    _ALIAS = ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermNotesPayable",
              "UnsecuredLongTermDebt", "NoncurrentBorrowings", "LongtermBorrowings")
    _fixedL, _suspL = [], []
    _ltcl = series(facts, ["LongTermDebtAndCapitalLeaseObligationsCurrent"])[0]
    for _y in sorted(S["debtL"]):
        _parts = {}
        for _x in (_usedL.get(_y) or []):
            if "=" in _x and "(総額)" not in _x:
                _k, _v = _x.split("=", 1)
                try:
                    _parts[_k] = float(_v.replace(",", ""))
                except ValueError:
                    pass
        if len(_parts) < 2:
            continue
        _val, _used = S["debtL"][_y], list(_usedL[_y])
        # (a) 同じ非流動負債の別名どうしが同額なら1本だけ数える。別名の組は LTDNoncurrent×LTDAndCLO だけではなかった
        #   （2026-09-23 JKHY の再審査で LongTermDebtAndCapitalLeaseObligations×LongTermNotesPayable が FY2021-22 に同額）。
        #   ⚠ OtherLongTermDebtNoncurrent 等「その他の負債」は構成要素なので別名の組に入れない。
        for _i, _ka in enumerate(_ALIAS):
            for _kb in _ALIAS[_i + 1:]:
                _a, _b = _parts.get(_ka), _parts.get(_kb)
                if _a and _b is not None and abs(_a - _b) / abs(_a) <= 0.005:
                    _val -= _b
                    _parts.pop(_kb)
                    _used = [u for u in _used if not u.startswith(_kb + "=")] + \
                            [f"{_kb}={_b:,.0f}は{_ka}と同額の別名＝二重に数えない"]
        _tot = _parts.get("DebtAndCapitalLeaseObligations")
        if _tot and len(_parts) >= 2:
            # DebtAndCapitalLeaseObligations は US-GAAP の定義上「流動＋非流動＋リース」の**総額**。
            #   非流動のタグと足すことは定義からして二重計上なので、**総額として採る**（debtL＋debtS＝総額 になるよう
            #   debtL＝総額−debtS）。恒等式の一致は根拠の文にだけ残す——流動分は LongTermDebtAndCapitalLeaseObligationsCurrent
            #   にあって debtS の候補に無い社が多い（実測 MUSA 19.0 / SYY 1,201 / ECL 759.4 百万$）。
            _nonc = sum(v for k, v in _parts.items() if k != "DebtAndCapitalLeaseObligations")
            _cur = S["debtS"].get(_y, 0) or 0
            _curL = _ltcl.get(_y)
            if _tot >= _nonc * 0.995:
                _ok = any(c is not None and abs(_tot - (_nonc + c)) / abs(_tot) <= 0.005 for c in (_cur, _curL))
                _val = max(_tot - _cur, 0)
                _used = [u for u in _used if "=" not in u or "(総額)" in u] + \
                        [f"DebtAndCapitalLeaseObligations={_tot:,.0f}＝流動込みの総額を採った（非流動 {_nonc:,.0f} を足さない。"
                         + (f"非流動＋流動と恒等式で一致" if _ok else "流動分の内訳は恒等式で確かめられず") + "）"]
                if not _ok:
                    _suspL.append(_y)
            else:
                _suspL.append(_y)
        if _val != S["debtL"][_y]:
            S["debtL"][_y] = _val
            _usedL[_y] = _used
            _fixedL.append(_y)
    # ===== 2026-09-23（todo fetcher_debt_tags_0923）: 負債タグの穴 (1)〜(4) =====
    #   nde の是正（原本との突合せ42パック）で見つかった穴。どれも「候補＝代替か構成要素か」を先に答え、
    #   **恒等式か不等式で確かめられた年だけ**値を動かす（確かめられない年は旧来どおり＝取りこぼしは残るが二重計上は作らない）。
    _debtNs = _dmL.get("ns") or _dmS.get("ns")
    _debtU = _dmL.get("unit") or _dmS.get("unit")
    _debtNotes = []

    def _tc(k, nss=None):
        """その社の負債の系列と同じ名前空間・単位での、タグ k の当期の値（違えば {}＝足さない）"""
        v, u, _ns = _tag_cur(facts, k, nss or ((_debtNs,) if _debtNs else ("us-gaap", "ifrs-full")))
        return v if v and (not _debtU or u == _debtU) else {}
    # (3) IFRS の Borrowings は**流動込みの総額**のことが多いのに、流動の構成要素（ShorttermBorrowings 等）を debtS に足していた。
    #   実測 TIMB 2025: Borrowings 2,778,723 ＝ LongtermBorrowings 1,853,097 ＋ ShorttermBorrowings 925,626（千BRL）が全年で成立
    #   → 流動の借入 925,626 を二重計上（nde −0.23 のところ +0.01）。同じ恒等式が CPA・IHG・LOMA・TGS・TIGO・KARO 2025・
    #   OMAB 2018-20・CEPU 2018・DLO 2021 で成立した（296社）。**恒等式が成り立つ年だけ**流動の構成要素を控除する
    #   （GSK・NVO・PAC・SAP・AMBIQ・ASR は成り立たない＝Borrowings の中身を機械で確かめられないので触らない）。
    _fixB = []
    if _debtNs == "ifrs-full":
        _bor = _tc("Borrowings")
        _ncI = [_tc(k) for k in ("LongtermBorrowings", "NoncurrentBorrowings", "NoncurrentPortionOfNoncurrentBondsIssued")]
        for _y in sorted(S["debtS"]):
            _b, _cs = _bor.get(_y), S["debtS"].get(_y) or 0
            if not _b or not _cs or S["debtL"].get(_y) != _b or "Borrowings(総額)" not in (_usedL.get(_y) or []):
                continue
            _nc = sum(v[_y] for v in _ncI if _y in v)
            if abs(_b - (_nc + _cs)) <= 0.005 * abs(_b):
                _usedS[_y] = [f"{x}は Borrowings（流動込みの総額 {_b:,.0f}＝非流動 {_nc:,.0f}＋流動 {_cs:,.0f} と恒等式で一致）に"
                              f"含まれるため控除" for x in (_usedS.get(_y) or [])]
                S["debtS"][_y] = 0
                _fixB.append(_y)
    if _fixB:
        _debtNotes.append(f"有利子負債の二重計上を恒等式で確定して是正した（IFRS・{len(_fixB)}年: {_fixB[0]}〜{_fixB[-1]}）: "
                          f"Borrowings＝非流動＋流動の構成要素 が成立＝Borrowings は流動込みの総額なので、流動の構成要素を控除した")
    # (3') TSM 型: IFRS の CurrentPortionOfLongtermBorrowings（1年内返済の長期負債）が社債の1年内償還分を**含む**ことがある
    #   （TSM の BS『Long-term liabilities - current portion』59,857.9百万TWD＝社債 57,148＋銀行借入。CurrentBondsIssued… 57,148 も
    #   別に付くので二重）。含むかどうかは銀行借入の1年内分が別のタグで出ていないと恒等式で確かめられない→**値は動かさず注記だけ**。
    _suspCB = []
    for _y in sorted(S["debtS"]):
        _pv = _used_vals(_usedS.get(_y))
        _cb, _cp = _pv.get("CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued"), _pv.get("CurrentPortionOfLongtermBorrowings")
        if _cb and _cp and _cp >= _cb:
            _suspCB.append((_y, _cb, _cp))
    if _suspCB:
        _y, _cb, _cp = _suspCB[-1]
        _debtNotes.append(f"有利子負債の二重計上の疑い（{_y}年ほか{len(_suspCB)}年）: CurrentPortionOfLongtermBorrowings {_cp:,.0f} は"
                          f" CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued {_cb:,.0f} 以上＝社債の1年内償還分を含む"
                          f"『1年内返済の長期負債』の総額かもしれない（TSM の BS はそう）。銀行借入の1年内分が別に出ていないので"
                          f"**機械では確定できず両方を足している**。原本のBSで確認せよ")
    # (2) LongTermDebtAndCapitalLeaseObligations に**リース負債だけ**（＋別に報告された借入の明細）が入っている社がある。
    #   実測 WSO 2025: 361,635千$＝OperatingLeaseLiabilityNoncurrent 350,616＋FinanceLeaseLiabilityNoncurrent 11,019（BS『Total long-term
    #   obligations』・借入は無い）。2023年は 304,5xx＝リース 289,1xx＋LongTermLineOfCredit 15,4xx。PLAB は FinanceLeaseLiability と同額。
    #   規約はリース負債を入れない（ACI のように借入と同じ行で内訳の分からないファイナンスリースは込みのまま——ここは
    #   **リース負債と恒等式で一致して分離できると確かめられた年だけ**借入分（0 か別に報告された明細の額）にする）。
    def _te(k):
        """リース負債のタグの値（当期、無ければ翌年以降の提出の比較年度）。恒等式の証拠にだけ使う"""
        v, u, _ns = _tag_ev(facts, k, ("us-gaap",))
        return v if v and (not _debtU or u == _debtU) else {}
    _oll, _ollc = _te("OperatingLeaseLiabilityNoncurrent"), _te("OperatingLeaseLiabilityCurrent")
    _fll, _fllc = _te("FinanceLeaseLiabilityNoncurrent"), _te("FinanceLeaseLiabilityCurrent")
    _fllt = _te("FinanceLeaseLiability")

    def _fl(y, nc):
        a, b = (_fll, _fllc) if nc else (_fllc, _fll)
        if y in a:
            return a[y]
        if y in _fllt and y in b:
            return _fllt[y] - b[y]
        return None
    _newL = {k: _tc(k) for k in DEBT_NEW_L}
    _leaseY = []
    if _debtNs in (None, "us-gaap"):
        _A = _tc("LongTermDebtAndCapitalLeaseObligations", ("us-gaap",))
        for _y in sorted(S["debtL"]):
            _hitA = [x for x in (_usedL.get(_y) or []) if re.fullmatch(r"LongTermDebtAndCapitalLeaseObligations=-?[\d,]+", x)]
            if not _hitA or _y not in _A:
                continue
            _x = _A[_y]
            _res = _lease_residual(_x, _oll.get(_y), _fl(_y, True), [v[_y] for v in _newL.values() if _y in v])
            if _res is None:
                continue
            _nm, _lv, _keep = _res
            S["debtL"][_y] -= (_x - _keep)
            _usedL[_y] = [x for x in _usedL[_y] if x not in _hitA] + [
                f"LongTermDebtAndCapitalLeaseObligations={_x:,.0f}は{_nm} {_lv:,.0f}"
                + (f"＋借入の明細 {_keep:,.0f}" if _keep else "") + "と恒等式で一致＝リース負債は入れず借入分"
                + f" {_keep:,.0f} だけ数えた"]
            _leaseY.append(_y)
    if _leaseY:
        _debtNotes.append(f"LongTermDebtAndCapitalLeaseObligations がリース負債（＋別に出ている借入の明細）と恒等式で一致した年がある"
                          f"（{_leaseY[0]}〜{_leaseY[-1]}年・{len(_leaseY)}年）: リース負債は入れず借入分だけを数えた（実測 WSO）")
    # (1) 1年内返済分のタグ LongTermDebtAndCapitalLeaseObligationsCurrent が debtS の候補に無かった（ACI が 534.0百万$ を落とす）。
    #   代替か構成要素か: LongTermDebtCurrent の**別名／上位集合**（＋ファイナンスリースの1年内分）で、DebtCurrent・
    #   DebtAndCapitalLeaseObligations・LongTermDebt（流動込み）の**構成要素**。実測（296社）で LongTermDebtCurrent と同額の社
    #   （ASML/HPQ/MTN/CHH/HEI）、LongTermDebt＝LTDACLO＋これ が恒等式で成立する社（ETN/MELI）がある
    #   → その年に LongTermDebtCurrent・DebtCurrent・DebtAndCapitalLeaseObligations・流動込みの総額（LongTermDebt/Borrowings）が
    #   **どれも無い年だけ**足す（ACI/APH/KO/NJR/DXC 2025-26…）。リース負債だけの年（WSO・PLAB）は (2) と同じ恒等式で 0 として数える。
    _addC, _skipC = [], []
    _newDebt = {}                                 # 年→今回足した負債の額（nde の無借金判定・ROIC の欠測判定で±2年の窓に使う）
    if _debtNs in (None, "us-gaap"):
        _Ac = _tc("LongTermDebtAndCapitalLeaseObligationsCurrent", ("us-gaap",))
        _blkC = [_tc(k, ("us-gaap",)) for k in ("LongTermDebtCurrent", "DebtCurrent", "DebtAndCapitalLeaseObligations")]
        # この社の LTDACLO 系の行が**どこかの年でリース負債だと証明できた**なら、恒等式で借入分を確かめられない年の
        #   1年内分は足さない＝旧来どおり（WSO: 2019年の LTDACLOCurrent 69.4百万$ はオペレーティングリース 68.2＋ファイナンスリースの
        #   1年内分と見られるが、ファイナンスリースの内訳が無く恒等式が閉じない。確かめられない年に足すとリースが借入に化ける）
        _leaseCo = bool(_leaseY) or any(_lease_residual(v, _ollc.get(y), _fl(y, False)) for y, v in _Ac.items())
        for _y, _xc in sorted(_Ac.items()):
            if any(_y in b for b in _blkC):
                continue
            if any("(総額" in x or x.startswith("DebtAndCapitalLeaseObligations=") for x in (_usedL.get(_y) or [])):
                continue
            _pv = _used_vals(_usedS.get(_y))
            if _xc and any(v and abs(v - _xc) <= 0.005 * abs(_xc) for v in _pv.values()):
                continue                          # 他の流動の構成要素と同額＝同じ負債の別名
            _res = _lease_residual(_xc, _ollc.get(_y), _fl(_y, False))
            if _res is None and _leaseCo:
                _skipC.append(_y)
                continue
            _add = _res[2] if _res else _xc
            if _add > 0:
                _newDebt[_y] = _newDebt.get(_y, 0) + _add
            S["debtS"][_y] = (S["debtS"].get(_y) or 0) + _add
            _usedS[_y] = list(_usedS.get(_y) or []) + [
                f"LongTermDebtAndCapitalLeaseObligationsCurrent={_xc:,.0f}"
                + (f"は{_res[0]} {_res[1]:,.0f}と恒等式で一致＝リース負債なので 0 として数えた" if _res else "")]
            _addC.append(_y)
    if _skipC:
        _debtNotes.append(f"LongTermDebtAndCapitalLeaseObligationsCurrent を足さなかった年がある（{_skipC[0]}〜{_skipC[-1]}年）: この社の同じ行は"
                          f"他の年にリース負債と恒等式で一致した（{', '.join(str(y) for y in _leaseY) or '1年内分'}）のに、この年はリースのタグが無く"
                          f"確かめられない＝リース負債を借入として数える恐れ（旧来どおり数えない）")
    # (4) 候補にも痕跡の正規表現にも無かった負債タグ（DEBT_NEW_* の頭注）。**総額系のタグがその年に一つも無いときだけ**足す。
    #   流動込みの総額（SeniorNotes / LoansPayable ほか）はその家族の明細（…Noncurrent/…Current）より優先し、明細は足さない。
    _FAM = {"SeniorNotes": ("SeniorNotesNoncurrent", "SeniorNotesCurrent", "SeniorLongTermNotes"),
            "LoansPayable": ("LongTermLoansPayable", "LoansPayableCurrent"),
            "SecuredBankLoansReceived": ("NoncurrentPortionOfNoncurrentSecuredBankLoansReceived",
                                         "CurrentSecuredBankLoansReceivedAndCurrentPortionOfNoncurrentSecuredBankLoansReceived"),
            "UnsecuredBankLoansReceived": ("NoncurrentPortionOfNoncurrentUnsecuredBankLoansReceived",
                                           "CurrentUnsecuredBankLoansReceivedAndCurrentPortionOfNoncurrentUnsecuredBankLoansReceived")}
    _aggL = [_tc(k) for k in DEBT_AGG_L]
    _aggS = [_tc(k) for k in DEBT_AGG_S]
    _aggLC = [_tc(k) for k in DEBT_AGG_LC]
    _newS = {k: _tc(k) for k in DEBT_NEW_S}
    _newT = {k: _tc(k) for k in DEBT_NEW_T}
    _addN = []
    for _side, _grp, _blk in (("T", _newT, _aggL + _aggS), ("L", _newL, _aggL), ("S", _newS, _aggS + _aggLC)):
        for _k, _vals in _grp.items():
            for _y, _v in sorted(_vals.items()):
                if any(_y in b for b in _blk):
                    continue                      # 総額系がある年＝この明細はその中にあると見なす（二重計上より取りこぼし）
                if _side != "T" and any(_k in fam and _y in _newT.get(tot, {}) for tot, fam in _FAM.items()):
                    continue                      # 家族の総額（流動込み）がある年は明細を足さない
                _pv = {**_used_vals(_usedL.get(_y)), **_used_vals(_usedS.get(_y))}
                if _v and any(v and abs(v - _v) <= 0.005 * abs(_v) for v in _pv.values()):
                    continue                      # 他の構成要素と同額＝同じ負債の別名（NBIX 2019: 転換社債が非流動にも流動にも 408.8）
                _tgt, _used = ("debtS", _usedS) if _side == "S" else ("debtL", _usedL)
                S[_tgt][_y] = (S[_tgt].get(_y) or 0) + _v
                _used[_y] = list(_used.get(_y) or []) + [f"{_k}={_v:,.0f}"]
                _addN.append((_k, _y))
                if _v > 0:
                    _newDebt[_y] = _newDebt.get(_y, 0) + _v
    if _addN:
        _ks = sorted({k for k, _y in _addN})
        _debtNotes.append(f"候補外だった負債タグを足した（{', '.join(_ks)}・{min(y for _k, y in _addN)}〜{max(y for _k, y in _addN)}年）: "
                          f"その年に総額系の負債タグ（LongTermDebt・LongTermDebtNoncurrent・Borrowings 等）が一つも無いので"
                          f"明細が総額の中に入っている恐れが無い年だけ")

    def _debtHist(y):
        """y 以外の年に負債の報告があるか。旧来の候補タグは**全年**（従来どおり）、今回足した明細は debt_evidence() と同じ±2年の窓
        （TTD の2017年のリボルバー 27百万$ が、2018年から借入の無い今の年の無借金の判定を止めないように）"""
        return bool(_origDebtYears) or any(abs(yy - y) <= 2 for yy, v in _newDebt.items() if v > 0)
    # （注記は note が作られた後＝下の _fixed の注記の隣で出す）
    # 2026-08-03: 無形も同じく「構成要素」だった（TAGS["intan"]の頭注を見よ）。総額タグがその年に
    #   あれば総額、無ければ 確定分＋無期限分 を足す＝series_sum の total_key がそのまま使える。
    #   実測 CELH: 総額タグが2024年で終わり、2025年は二本に割れていたので series() では欠測になった。
    S["intan"], _usedI = series_sum(facts, TAGS["intan"],
                                    total_key="IntangibleAssetsNetExcludingGoodwill")
    # 2026-08-08: 減価償却も同じ「構成要素」型（TAGS["depParts"] の頭注を見よ）。
    #   合計タグがその年に無い年だけ、構成要素の合計で補う（合計があるならそれを使う＝二重計上しない）。
    _depS, _usedD = series_sum(facts, TAGS["depParts"])
    # 2026-09-23追加（todo fetcher_small_gaps_0923）: **AdjustmentForAmortization は CF 計算書の「Amortization」行＝償却の総額**。
    #   構成要素として depParts に並べると償却を二重に足す——実測（296社）でこのタグは AmortizationOfIntangibleAssets と
    #   **同額**（NDSN/PH）・ほぼ同額（ECL/GILD/MRK）・それより大きい（GRMN/INTU/BMI＝ソフト等の償却も含む）。
    #   → 合計タグ（dep）が無い年で、しかも償却の構成要素（無形・繰延費用の償却）が一つも無いときだけ、
    #     償却の欄の**代替**として足す。実測 JKHY: FY2026 の償却 171,138千$ がこのタグだけで報告され、D&A が減価償却
    #     42,103千$ だけになって nde 0.04（原本の EBITDA 848,274千$ で 0.03・0000779152-26-000067）。
    _afa = series_sum(facts, ["AdjustmentForAmortization"])[0]
    for _y, _v in (_afa or {}).items():
        if not _v or _y in S["dep"]:
            continue
        _u0 = _usedD.get(_y) or []
        if any(x.startswith(("AmortizationOfIntangibleAssets=", "AmortizationOfDeferredCharges=")) for x in _u0):
            continue                          # 償却の構成要素がある年は足さない（二重計上になる）
        _depS[_y] = (_depS.get(_y) or 0) + _v
        _usedD[_y] = _u0 + [f"AdjustmentForAmortization={_v:,.0f}（償却の総額・構成要素が無い年の代替）"]
    _depFilled = []
    for _y, _v in (_depS or {}).items():
        if _y not in S["dep"] and _v:
            S["dep"][_y] = _v
            _depFilled.append(_y)
    # IFRS勢は のれん を単独で出さず `IntangibleAssetsAndGoodwill`(のれん**込み**の合算)だけを
    #   出す社がある（実測TSM: Goodwillタグ自体が存在しない）。sum候補に入れると `Goodwill` や
    #   `IntangibleAssetsOtherThanGoodwill` を併せ持つ社で**二重に引く**ので、
    #   **他の無形も のれん も取れない年に限って**合算値を無形として使う（gw=0 なので過不足なし）。
    _iag = series(facts, ["IntangibleAssetsAndGoodwill"])[0]
    if _iag:
        for _y, _v in _iag.items():
            if _y not in S["intan"] and _y not in S["gw"]:
                S["intan"][_y] = _v
    # 2026-09-23（todo fetcher_debt_tags_0923 (5)）: **短期投資の候補が BS の行の2本だけだった**。流動の AFS
    #   （AvailableForSaleSecuritiesDebtSecuritiesCurrent / DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent）・
    #   流動の満期保有・OtherShortTermInvestments だけで短期投資を出す社は現金だけで nde を出していた（機械の根拠を持つ
    #   ASML/FTNT/GRMN/KO/SYK/SYY/VEEV/WAY が狭い基準・原本の突合せで確定）。規約（2026-09-23 の nde の是正）は
    #   「現金＝現金＋流動の短期投資（AFS・満期保有・定期預金を含む）」。
    #   代替か構成要素か: ShortTermInvestments / MarketableSecuritiesCurrent は **BS の行**、AFS・満期保有は多くの社で**その内訳の注記**
    #   （ADI: ShortTermInvestments 1,152.9 ＝ AFS流動 1,152.9／CMG・LRN: MarketableSecuritiesCurrent ＝ 満期保有）→
    #   **BS の行のタグがその年に無いときだけ**使う。AFS と満期保有は別の資産（足す）。その他の短期投資が AFS＋満期保有と
    #   同額（または片方と同額）ならそれが総額か別名なので1本だけ。
    _stiUsed = {}
    _stiP = []
    for _grp in (STI_AFS, STI_HTM, STI_OTHER):
        _m = {}
        for _k in _grp:
            for _y, _v in (_tag_cur(facts, _k, ("us-gaap",))[0] or {}).items():
                _m.setdefault(_y, (_k, _v))
        _stiP.append(_m)
    for _y in sorted(set().union(*[set(m) for m in _stiP])):
        if _y in S["sti"]:
            continue
        _parts = [m[_y] for m in _stiP[:2] if _y in m]
        _o = _stiP[2].get(_y)
        if _o:
            _tot = sum(v for _k, v in _parts)
            if _parts and _o[1] and (abs(_o[1] - _tot) <= 0.005 * abs(_o[1])
                                     or any(abs(_o[1] - v) <= 0.005 * abs(_o[1]) for _k, v in _parts)):
                _parts = [_o]
            else:
                _parts.append(_o)
        if len(_parts) == 2 and _parts[0][0] in STI_AFS and _parts[1][0] in STI_HTM and _parts[0][1] \
                and abs(_parts[0][1] - _parts[1][1]) <= 0.005 * abs(_parts[0][1]):
            _parts = _parts[:1]
        S["sti"][_y] = sum(v for _k, v in _parts)
        _stiUsed[_y] = _parts
    for k in ("debtS", "debtL", "intan"):
        diag[k] = f"{len(S[k])}年分(合計)" if S[k] else "タグ不発見"
    ev, note = {}, []
    # 2026-09-23: capex の検問（TAGS["capex"] の頭注）。PaymentsToAcquireOtherProductiveAssets は多くの社で
    #   「その他」の小さな構成要素なので、**PP&E 系のタグと重なる年に半分未満だった社**では設備投資の総額として使わない
    #   （PP&E 系のタグが途切れた年にその小さな行が設備投資に化けると FCF が過大に出る。誤値より空欄）。
    _opa = series(facts, ["PaymentsToAcquireOtherProductiveAssets"])[0]
    if _opa and S["capex"]:
        _ppe = series(facts, [k for k in TAGS["capex"] if k != "PaymentsToAcquireOtherProductiveAssets"])[0]
        _ovy = [y for y in set(_opa) & set(_ppe) if _ppe[y]]
        if any(abs(_opa[y]) < 0.5 * abs(_ppe[y]) for y in _ovy):
            _drop = sorted(y for y in S["capex"] if y not in _ppe and y in _opa and S["capex"][y] == _opa[y])
            for y in _drop:
                del S["capex"][y]
            if _drop:
                note.append(f"設備投資を算出不能とした年がある（{_drop[0]}〜{_drop[-1]}年）: その年の設備投資が "
                            f"PaymentsToAcquireOtherProductiveAssets にしか無いが、この社では PP&E 系のタグと重なる年に"
                            f"その半分未満＝『その他』の構成要素なので総額として使わない。原本の CF 計算書で確認せよ")
    # 2026-08-03: **営業利益タグが途中で消える会社がある。** 実測 KLAC(投下可の社):
    #   `OperatingIncomeLoss` が **2015年で終了**し、TAGS["op"]の候補2つとも最新年に届かない。
    #   series() は「最新年から1年以内に届く候補」の中から選ぶが、**どの候補も届かない場合は
    #   一番マシな古い系列を返す**ので、KLACの営業利益率・NOPATは**11年前(FY2015)**で計算されていた
    #   ——BKNG事故（ルール7「取れた値＝最新の値」）と同型。
    #   → 直接タグが最新年に届かないときだけ **売上−原価−R&D−販管費** で導出する。
    #   **較正**: KLAC FY2025 の導出値は営業利益率 **41.2%** で、原本で審査済みのパックの
    #   手入力値 **41.3** と一致した。償却(220.4百万$)や減損(239.1百万$)を追加で引くと 39.4/39.3% と
    #   **逆に一致が壊れる**＝これらは既に原価/販管費の中にある。だから4行ちょうどで止める。
    #   導出したことは note と evidence に必ず残す（審査官が原本で検算できるように）。
    _opDeriv = None
    _refY = [y for k in ("rev", "ni", "assets", "eq") for y in S[k]]
    if _refY:
        _newest = max(_refY)
        if not S["op"] or max(S["op"]) < _newest - 1:
            _cost, _ = series_sum(facts, ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
                                  total_key="CostOfRevenue")
            _rd = series(facts, ["ResearchAndDevelopmentExpense"])[0]
            # 販管費も**構成要素**（無形・有利子負債と同じ型を、同じセッションで3度目に踏んだ）。
            #   ADSK/ABNB/MELI/PCTY は SG&A を SellingAndMarketing + GeneralAndAdministrative に
            #   **分けて**報告する。1本だけ選ぶと片方が丸ごと落ち、営業利益が**過大**に出る。
            #   実測(初版): ADSK 導出4,913百万$ に対し報告1,578百万$＝売上比 +46.3pt の過大。
            _sga, _ = series_sum(facts,
                                 ["SellingGeneralAndAdministrativeExpense",
                                  "SellingAndMarketingExpense", "GeneralAndAdministrativeExpense",
                                  "MarketingExpense", "SellingExpense",
                                  "MarketingAndAdvertisingExpense"],
                                 total_key="SellingGeneralAndAdministrativeExpense")
            # 自己検証には**売上の全候補タグの和集合**を使う。導出が要る会社は直接タグが古い年で
            #   終わっており、売上タグもASC606で同じ頃に改称しているため、S["rev"](主系列)だけだと
            #   **重なる年が1年も無く検証が空振りする**（実測KLAC: op 2009-2015 / 主系列rev 2017-2026）。
            #   検証は「その会社自身の報告値と合うか」を見るのが目的なので、古い売上タグも使ってよい。
            _revAll = {}
            for _k in TAGS["rev"]:
                for _y, _v in (series(facts, [_k])[0] or {}).items():
                    _revAll.setdefault(_y, _v)
            _revAll.update(S["rev"])
            _der = {}
            for y in _revAll:
                if y in _cost and (y in _rd or y in _sga):
                    _der[y] = _revAll[y] - _cost[y] - _rd.get(y, 0) - _sga.get(y, 0)
            # **自己検証**: その会社自身が報告している年で導出値が一致するときだけ採用する。
            #   series() の「重なる年で値が一致するタグだけを接ぐ」と同じ作法を導出にも掛ける。
            #   一致しない＝その会社の費用構造をこの式が捉えていない証拠なので、
            #   **黙って使わず算出不能のままにする**（誤値より空欄）。
            _ov = sorted(set(_der) & set(S["op"]))[-3:]
            _fit = [abs(_der[y] - S["op"][y]) / max(abs(_revAll.get(y, 0)), 1) for y in _ov]
            _okfit = bool(_ov) and max(_fit) <= 0.01          # 売上比1pt以内
            if _der and max(_der) >= _newest - 1 and _okfit:
                _old = f"{max(S['op'])}年で終了" if S["op"] else "タグ不発見"
                S["op"], _opDeriv = _der, sorted(_der)
                diag["op"] = f"{len(_der)}年分(導出)"
                note.append(
                    f"営業利益を**導出**した（直接タグは{_old}）: 売上 − 原価 − 研究開発費 − 販管費。"
                    f"直接タグが最新年に届かないため（実測KLAC: OperatingIncomeLossが2015年で終了し、"
                    f"営業利益率とNOPATが11年前の決算で計算されていた）。"
                    f"**償却・減損は引いていない**——KLACでの較正では追加で引くと原本の値と一致が壊れる"
                    f"（既に原価/販管費の中にある）。"
                    f"**自己検証済**: 同社が直接タグを報告している {len(_ov)}年（{_ov}）で"
                    f"導出値が売上比 最大{max(_fit)*100:.2f}pt の差で一致した。営業利益率が業態と乖離する場合は原本で検算せよ")
            elif _der and max(_der) >= _newest - 1:
                # 2026-08-03: **検証できなかった場合と、検証して落ちた場合を書き分ける。**
                #   直接タグを一度も報告しない会社（実測 LLY/MRK/ADP/ZTS 等。損益計算書に
                #   営業利益の小計を置かない様式）では重なる年が無く自己検証が**走らない**のに、
                #   「差 最大0.0pt で落ちた」と出て誤解を招いていた。
                _why = (f"同社が報告している年との差が売上比 最大{max(_fit)*100:.1f}pt" if _fit
                        else "同社は営業利益の直接タグを一度も報告しておらず**照合できる年が無い**")
                note.append(
                    f"営業利益の直接タグが最新年に届かず（{max(S['op']) if S['op'] else '不発見'}年で終了）、"
                    f"導出（売上−原価−R&D−販管費）も**採用しなかった**（{_why}）。"
                    f"式が費用構造を捉えている確証が無いので**算出不能のままにした**（誤値より空欄）。"
                    f"営業利益率・NOPAT・ROICは原本の損益計算書から手入力せよ")
    ev["_debtUsed"] = {"debtS": _usedS, "debtL": _usedL}
    # us-gaap の LongTermDebt は「1年内返済分を含む総額」で報告する会社と「非流動分のみ」の
    # 会社が混在する。前者に LongTermDebtCurrent を足すと**二重計上**になる。機械では区別できない
    # ので、両方を使った年は警告だけ出す（黙って足しも引きもしない＝ルール7の作法）。
    _dbl = sorted(y for y in _usedL
                  if any("LongTermDebt(総額)" in x for x in _usedL[y])
                  and any("LongTermDebtCurrent" in x for x in _usedS.get(y, [])))
    if _fixed:
        note.append(f"有利子負債の二重計上を**恒等式で確定して是正した**（{len(_fixed)}年: {_fixed[0]}〜{_fixed[-1]}）: "
                    f"LongTermDebt = LongTermDebtNoncurrent + LongTermDebtCurrent が成立＝"
                    f"LongTermDebt は1年内返済分**込みの総額**なので、1年内返済分を控除した。"
                    f"控除しないと IC が過大＝ROICは**過小**に出る")
    if _fixedL:
        note.append(f"有利子負債の別名・総額の二重計上を是正した（{len(_fixedL)}年: {_fixedL[0]}〜{_fixedL[-1]}）: "
                    f"LongTermDebtNoncurrent と LongTermDebtAndCapitalLeaseObligations の同額は1本、"
                    f"DebtAndCapitalLeaseObligations は流動込みの総額と恒等式で確かめて足さない")
    if _suspL:
        note.append(f"有利子負債の総額タグ（DebtAndCapitalLeaseObligations）を採った年のうち、流動分の内訳が恒等式で"
                    f"確かめられない年がある（{_suspL[-1]}年ほか{len(_suspL)}年）。総額は定義どおり採っているが、原本のBSで確認せよ")
    if _dbl:
        note.append(f"有利子負債の二重計上の疑い（{_dbl[-1]}年ほか{len(_dbl)}年）: LongTermDebt を"
                    f"1年内返済分込みで報告する会社では LongTermDebtCurrent を足すと重複する。"
                    f"恒等式（総額＝非流動＋流動）が成立しないか、非流動タグが無い年なので"
                    f"**機械では確定できなかった**。原本のBSで総額を確認せよ")
    note.extend(_debtNotes)                       # 2026-09-23 負債タグの穴 (1)〜(4) の注記
    # 2026-07-29新設: 機械項目にも根拠を刻む。
    #   実測(night/audit_evidence.py)で、機械項目の _meta.evidence 被覆率は 9.8%
    #   (ni 0.3% / cagr 1.0% / gm 4.8% / roic 16.2%)だった。「機械の出力だから正しい」
    #   という前提が置かれていたためで、絶対のルール7で潰したバグ(欠測をゼロと読む)は
    #   まさにその前提が外れる場所にあった。**式と実額を残せば、同じ事故は次から目で見える。**
    evd = {}
    ev["_evid"] = evd
    # 全系列の最新年。以降の各算出は「使った年がここから2年以上遅れていないか」で検問する
    _all_years = [y for k in ("rev","op","ni","assets","eq","ocf") for y in S[k]]
    LATEST = max(_all_years) if _all_years else None
    # 2026-09-23: 年ラベルを付け直した提出を明示する（直近の窓に掛かるものだけ。頭注「年の付け方」）
    _fx = sorted((e, o, n) for o, n, e in _fy_model(facts)["fixed"].values()
                 if LATEST is not None and n >= LATEST - 6)
    if _fx:
        note.append("年ラベルを期末日から付け直した提出がある（SEC の fy＝提出書類の DEI の付番が、期末の順序と"
                    "整数年ずれていた）: " + " / ".join(f"期末 {e} の年次報告 fy{o}→{n}" for e, o, n in _fx)
                    + "。系列の年はこの付け直し後のラベル（会社の直近の呼び方に揃えてある）")
    # 2026-09-23（todo fetcher_debt_tags_0923 (7)）: **最新の年次報告の数字が companyfacts に無い**のを黙らない。
    #   実測: 2026年提出の20-F（TSM 0001628280-26-025362・CEPU・INFY ほか CPAC/GRVY/KARO/LOMA/TGS/WIT）は dei の事実
    #   （EntityCommonStockSharesOutstanding）しか載っておらず、採取器は一つ前の年次報告の数字を「最新」として出していた
    #   （stale() は取れた系列の中の最新年で測るので気づけない）。値は前年のまま（その年の値としては正しい）で、ここでは注記で名指しする。
    _dei = _dei_only_annual(facts)
    if _dei:
        _pts = _fy_model(facts)["pts"]
        _lastP = max(p[0] for p in _pts).isoformat() if _pts else "?"
        note.append("最新の年次報告の数字が companyfacts に未収載: "
                    + " / ".join(f"{f} accn {a}（{fl} 提出・DEI の年度 {fy}）" for a, f, fl, fy in _dei)
                    + f" は dei の事実だけ。機械値はすべて財務の数字がある最後の年次報告（期末 {_lastP}）までで、"
                      f"**最新年の数字ではない**——原本の本文で最新年を確認せよ")

    def stale(y):
        return LATEST is not None and y is not None and y < LATEST - 1

    ys_rev, rev = last_n(S["rev"])
    if len(rev) >= 2:
        # 2026-07-29修正: 従来は「系列の要素数」を年数として使っていた。XBRLの年次系列は
        #   タグの改称・様式変更で**年が飛ぶ**（実測 NVDA: 2018→2022 が隣り合っており、
        #   8年の伸びを5年で年率化して cagr=85.9%（真値47.4%）になっていた）。
        #   cagrは門XのE[r]のgに直結するので、過大なcagrはそのまま買付判断を歪める。
        #   **年数は年ラベルの差で数える**（要素数＝年数、は欠測をゼロと読むのと同型の思い込み）。
        n = min(5, len(rev)-1)
        span = ys_rev[-1] - ys_rev[-1-n]
        if stale(ys_rev[-1]):
            note.append(f"cagr算出不能: 売上系列が{ys_rev[-1]}年で途切れており最新{LATEST}年から遅れている"
                        f"（売上タグがTAGSに無いものへ改称された疑い）")
        elif span <= 0:
            note.append(f"cagr算出不能: 年ラベルが単調でない({ys_rev[-1-n]}→{ys_rev[-1]})")
        else:
            _safe(ev, note, "cagr5",
                  lambda: round(((rev[-1]/rev[-1-n])**(1/span)-1)*100,1) if rev[-1-n] else None)
            if ev.get("cagr5") is not None:
                gap = "" if span == n else f"（系列に欠年あり: 要素{n}個だが実年数{span}年——年数は年ラベルで数える）"
                evd["cagr"] = (f"機械算出: 売上 {ys_rev[-1-n]}年 {_u(rev[-1-n])} → {ys_rev[-1]}年 {_u(rev[-1])}"
                               f"＝{span}年の年率{gap}")
    # 粗利トレンド
    if S["gp"]:
        ys,gp = last_n(S["gp"])
        gm = {y: S["gp"][y]/S["rev"][y]*100 for y in ys if S["rev"].get(y)}
        yy = sorted(gm)[-2:]
        # 2026-09-23: 他の欄と同じ年検問（stale）を掛ける。粗利タグは途中で止まる社が多く（EXPD 2012年・OKE 2014年・
        #   PH 2017年で終了）、年の付け方の是正で売上の系列がその年まで届くようになると、10年以上前の粗利率の差が
        #   「粗利トレンド」として出てしまう（旧版は売上の欠年で偶然 None だった）。
        if len(yy)==2 and not stale(yy[1]):
            _safe(ev, note, "gmDelta", lambda: round(gm[yy[1]]-gm[yy[0]],1))
    # accr / conv (直近年)
    # 2026-07-29新設の安全網: **使っている年が古すぎないかを必ず見る。**
    #   TAGS に載っていないタグを使う会社では、機械は「取れた中でいちばん新しい年」を
    #   黙って直近年として扱う。実測 BKNG は NetIncomeLoss が2015年で途切れており、
    #   roicg/gpa/eps/nde が**11年前の決算**で計算されていた（eps 51.42 ← 実際は166）。
    #   タグを個別に足しても次の会社で同じことが起きるので、**年で検問する**。
    #   これも絶対のルール7の一族——「取れた値＝最新の値」という確かめていない前提。
    y0 = max(S["ni"]) if S["ni"] else None
    if y0 is not None and LATEST is not None and y0 < LATEST - 1:
        note.append(f"損益系の直近年が{y0}年で、他の系列の最新{LATEST}年から{LATEST-y0}年遅れている"
                    f"（純利益タグが途中で途切れている＝TAGSに無いタグを使っている疑い）。"
                    f"accr/nde/gm/roicg/gpa/fcf/ni/eps を算出不能とした。原本で確認して手入力せよ")
        y0 = None
    if y0 and y0 in S["ocf"] and S["assets"].get(y0):
        _safe(ev, note, "accr", lambda: round((S["ni"][y0]-S["ocf"][y0])/S["assets"][y0]*100, 1))
        if ev.get("accr") is not None:
            evd["accr"] = (f"機械算出 {y0}年: (純利益 {_u(S['ni'][y0])} − 営業CF {_u(S['ocf'][y0])})"
                           f" ÷ 総資産 {_u(S['assets'][y0])}")
    if y0 and y0 in S["ocf"] and y0 in S["capex"] and S["ni"].get(y0):
        fcf = S["ocf"][y0]-abs(S["capex"][y0])
        _safe(ev, note, "conv", lambda: round(fcf/S["ni"][y0]*100,1))
        sh,_ = series(facts, TAGS["sh"], ("shares",))
        if sh:
            # 2026-08-04是正(B12e): フォールバックは**最新の年ラベル**の株数。旧 `list(sh.values())[-1]`
            #   は辞書の挿入順の末尾＝最新年とは限らない（「取れた値＝最新の値」の思い込みと同型）
            shl = sh.get(y0) or sh[max(sh)]
            _safe(ev, note, "fcfps", lambda: round(fcf/shl,2) if shl else None)
    # nde
    if y0:
        # 2026-07-29修正: ここにも roic と同型の「欠測をゼロと読む」が残っていた。
        #   有利子負債タグが無い年を debt=0 と読むと nde = −現金/EBITDA となり、
        #   **借入のある会社が純現金の優良企業に見える**（roicは発散という派手な形で出たが、
        #   ndeは"健全に見える"という静かな形で出るぶん質が悪い）。
        #   無借金企業もタグを出さないので機械では区別できない＝絶対のルール7(a)そのもの。
        #   **タグが無い年は算出不能として null にし、理由を残す**（誤値より空欄）。
        has_debt = (y0 in S["debtL"]) or (y0 in S["debtS"])
        # 2026-08-10: **「他の年は報告があるのにその年だけ欠測」を0と読まない**（無形で確立した作法）。
        #   タグを足しても新しい移行先が現れれば同じことが起きるので、**構造で検出する**。
        # 2026-09-23是正: **上の検出は注記だけで、値は0と読んで出し続けていた**（見出しの「0と読まない」と実装が逆）。
        #   実測: MWA を08-10以前の現金候補（CashAndCashEquivalentsAtCarryingValue / CashAndCashEquivalents）で
        #   今の採取器に通すと、この注記つきで **nde 1.47**（根拠文は「現金同等物 0」）がそのまま出る。
        #   原本: CashAndCashEquivalentsAtCarryingValue は FY2021 10-K（2021-09-30 の 227,500,000）が最後で、
        #   FY2022 10-K 以降は CashCashEquivalentsRestrictedCash… へ移行（FY2025 431,500,000）。真値は
        #   (有利子負債 451,600,000 − 431,500,000) ÷ (営業利益 260,600,000 + 減価償却 46,900,000) = **0.065**。
        #   MWA 自身は08-10の候補追加で直っているが、次の移行先が現れた社では同じ誤値が注記つきで出る。
        #   → **欠測年は nde を出さない**（有利子負債タグが無い年と同じ作法・誤値より空欄）。
        _cashGap = bool(S["cash"]) and y0 not in S["cash"]
        if _cashGap:
            note.append(f"nde算出不能: {y0}年に現金タグが無い（他の年にはある）。0と読むと**借金が多く見える側**へ"
                        f"ずれる（MWAで現金431.5百万$を0と読み nde 1.47＝真値0.065 と出た実例）。"
                        f"欠測を0と読まず空欄にした——原本のBSで現金を確認して手入力せよ")
        cash = (S["cash"].get(y0,0) or 0)+(S["sti"].get(y0,0) or 0)
        # 2026-07-29追加修正: EBITDAの営業利益も「タグが無い年を0」と読んでいた。
        #   実測 KLAC: OperatingIncomeLoss が2014年で途切れており（同社は売上−原価−R&D−販管費で
        #   開示）、EBITDA が減価償却394百万$だけになって **nde=9.66**（原本からの検算では約0.2-0.5）。
        #   roic側は既に年検問で落としていたが、ndeだけ素通りしていた＝同じ穴の取り残し。
        # 2026-09-23（todo fetcher_debt_tags_0923 (5)(6)）: 短期投資の追加候補と D&A の小計を使ったときは根拠の文に書く
        _ndeX = ""
        if y0 in _stiUsed:
            _ndeX += ("｜短期投資は BS の行のタグ（ShortTermInvestments / MarketableSecuritiesCurrent）が無い年なので "
                      + " + ".join(f"{k}={v:,.0f}" for k, v in _stiUsed[y0]) + " を使った（流動の AFS・満期保有・その他の短期投資）")
        if y0 not in S["op"]:
            note.append(f"nde算出不能: {y0}年に営業利益タグが無い（EBITDAが減価償却だけになり過大に出る）。"
                        f"原本の損益計算書から営業利益を確認して手入力せよ")
            ebitda = 0
        else:
            # (6) D&A の総額タグが**小計**のことがある: 総額は構成要素以上のはずなのに、その値を出した提出の中で
            #   無形の償却や減価償却より小さい列がある＝その行は A か D の全部を含まない（実測 CHKP 24.8＜無形の償却 68.1 ／
            #   RMBS 11.9＜減価償却 30.8 ／ ENTG は FY2025 10-K の2023・2024年の列で 172.7＜214.5・188.1＜190.1＝CF は
            #   Depreciation 205.3 と Amortization 184.4 の2行）。証明できる下限の最大値へ置き換える（_dep_subtotal_fix）。
            #   ⚠ HD（3,514＝無形の償却 607 を除く行）・LOPE・NSSC・NDSN は不等式が立たず機械では確かめられない＝触らない。
            if y0 in S["dep"] and y0 not in _depFilled:
                _dfx = _dep_subtotal_fix(facts, y0, S["dep"][y0])
                if _dfx:
                    _new, _dinfo = _dfx
                    _why = []
                    if _dinfo["excA"]:
                        _e = _dinfo["excA"][0]
                        _why.append(f"{_e[:4]}年の列で {_dinfo['tag']} {_dinfo['T'][_e]:,.0f}＜AmortizationOfIntangibleAssets {_dinfo['A'][_e]:,.0f}")
                    if _dinfo["belowD"]:
                        _e = _dinfo["belowD"][0]
                        _why.append(f"{_e[:4]}年の列で {_dinfo['tag']} {_dinfo['T'][_e]:,.0f}＜Depreciation {_dinfo['D'][_e]:,.0f}")
                    _ndeX += (f"｜減価償却: 総額タグ {_dinfo['tag']} {S['dep'][y0]:,.0f} は小計（同じ提出 {_dinfo['accn']} の"
                              f"{'・'.join(_why)}）→ 証明できる下限の最大 {_dinfo['pick']} {_new:,.0f} を使った")
                    note.append(f"減価償却の総額タグが小計だった（{y0}年 {_dinfo['tag']} {S['dep'][y0]:,.0f}→{_new:,.0f}）: "
                                f"{'・'.join(_why)}（同じ提出 {_dinfo['accn']}）。総額は構成要素以上のはずなのでその行は全部を含まない。"
                                f"小計のままだと EBITDA が過小＝nde が過大（財務キル(>4)の誤爆）。原本のCF計算書で D&A を確認せよ")
                    S["dep"][y0] = _new
            ebitda = S["op"][y0] + (S["dep"].get(y0,0) or 0)
            # 2026-09-23: **EBITDA が 0 以下なら nde は定義できない**（負で割ると符号が逆になり、純負債の社が純現金に見える）。
            #   実測 CMTL 2025: 営業利益 −139,098,000。旧値 0.28 は「純現金÷負の EBITDA」（リボルバー 114,414,000 を見落として
            #   純現金に見えていた）、見落としを直すと −0.74＝純負債が純現金の符号で出る。296社でこの型は CMTL だけ。
            if ebitda <= 0:
                note.append(f"nde算出不能: {y0}年の EBITDA が 0 以下（営業利益 {_u(S['op'][y0])} + 減価償却 "
                            f"{_u(S['dep'].get(y0,0) or 0)}）＝有利子負債÷EBITDA の倍率が定義できない"
                            f"（負の EBITDA で割ると符号が逆になり純負債が純現金に見える）")
                ebitda = 0
            if y0 in _depFilled:
                note.append(f"減価償却は合計タグが無く**構成要素の合計**で補った（{y0}年 {_u(S['dep'][y0])}: "
                            f"{' + '.join(_usedD.get(y0) or [])}）。合計タグしか見ないと D&A が丸ごと欠測し "
                            f"EBITDA が営業利益だけになって nde が過大＝財務キル(>4)を誤爆させる")
            if y0 not in S["dep"]:
                note.append(f"nde注意: {y0}年に減価償却が合計タグでも構成要素でも取れず EBITDA=営業利益 とした＝"
                            f"**nde は過大に出ている**。原本のCF計算書から D&A を確認して手入力せよ")
        # 2026-08-03: 「タグ不在と無借金は機械で区別できない」——**区別できるようになった**ので
        #   debt_evidence() で裁く（ROIC側と同じ判定を使う＝同じ台帳に二つの基準を作らない）。
        #   痕跡ゼロなら債務ゼロは事実で、ネットキャッシュの会社の nde が空欄のままになるのを止める。
        if _cashGap:
            pass                              # 2026-09-23: 算出不能（上で注記済み）。現金の欠測を0と読まない
        elif not has_debt and not _debtHist(y0) and not debt_evidence(facts, y0) and ebitda:
            ev["nde"] = round((0-cash)/ebitda, 2)
            _far = sorted(set(S["debtL"]) | set(S["debtS"]))
            evd["nde"] = (f"機械算出 {y0}年: (有利子負債 0 − 現金同等物 {_u(cash)})"
                          f" ÷ (営業利益 {_u(S['op'].get(y0,0) or 0)} + 減価償却 {_u(S['dep'].get(y0,0) or 0)})。"
                          + ("**有利子負債は候補タグ・独立走査とも痕跡ゼロ＝実質無借金**" if not _far else
                             f"**有利子負債は候補タグの報告が±2年の外（{_far[-1]}年）だけ・独立走査も痕跡ゼロ＝実質無借金**")
                          + "（欠測を0と読んだのではない）" + _ndeX)
        elif not has_debt:
            note.append(f"nde算出不能: {y0}年に有利子負債タグが無い。無借金なら nde=−{_u(cash)}/EBITDA "
                        f"だが、他年に報告があるか未知のタグに痕跡があるため断定できない。原本のBSで確認して手入力せよ")
        elif ebitda:
            debt = (S["debtL"].get(y0,0) or 0)+(S["debtS"].get(y0,0) or 0)
            ev["nde"] = round((debt-cash)/ebitda, 2)
            evd["nde"] = (f"機械算出 {y0}年: (有利子負債 {_u(debt)} − 現金同等物 {_u(cash)})"
                          f" ÷ (営業利益 {_u(S['op'].get(y0,0) or 0)} + 減価償却 {_u(S['dep'].get(y0,0) or 0)})" + _ndeX)
    # のれん除外ROIC 5年系列 → worst/median
    roics = []
    roic_skip = []
    for y in sorted(S["op"])[-5:]:
        if all(y in S[k] for k in ("ni","eq")) and y in S["op"]:
            # 2026-08-04是正(B12a): **税タグの欠測を税率0%と読まない。** 従来の
            #   `S["tax"].get(y,0)` は、その年に税タグが無いと 実効税率0% → NOPAT=EBIT となり
            #   roic が約1.3倍過大に出ていた（欠測をゼロと読む・絶対のルール7の取り残し）。
            #   他年に報告があるのにその年だけ無い→欠測＝算出不能で飛ばす。
            #   会社全体で一度も税タグが無い→実効税率が測れない＝NOPAT系は全年算出不能
            #   （税0%と断定しない。誤値より空欄）。
            if y not in S["tax"]:
                roic_skip.append(f"{y}:税タグ不在で実効税率が測れずNOPAT算出不能"
                                 + ("（他年は報告あり＝欠測）" if S["tax"]
                                    else "（全年で不発見＝税0%と断定しない）"))
                continue
            tax_rate = 1 - S["ni"][y]/max(S["ni"][y]+S["tax"][y], 1)
            nopat = S["op"][y]*(1-max(0,min(0.5,tax_rate)))
            # 2026-07-29修正: 有利子負債タグが「その年に存在しない」場合、従来は debt=0 と見なして
            #   IC = 自己資本 − のれん − 無形 になっていた。買収で伸びた会社は自己資本の大半が
            #   のれん＋無形なので**分母が0へ縮退してROICが発散する**。実測: NJR roic=16.5(真値6.6・
            #   負債3.6十億$が丸ごと欠落) / HEI 93.0 / APH 163.4。日本株で廃止した旧・門式
            #   (投下資本−過剰現金)と同型のアーティファクトで、原因は「欠測をゼロと読む」こと。
            #   **タグが無い年は算出不能として飛ばす**（誤値より空欄）。
            # 2026-08-03: **このガードは無借金の会社で偽陽性を出していた。**
            #   実測 IRMD(投下可の社): 有利子負債タグが一つも当たらないため**5年すべてが算出不能**になり
            #   through-cycle ROIC が1年も作れなかった。だがIRMDは本当に無借金で、負債系タグは
            #   2013年の関係者向け手形 $6,333 とその2014年の返済しか存在しない。
            #   **「タグが無い＝債務あり(採れず)」も「タグが無い＝債務ゼロ」も、確かめていない前提。**
            #   → 今日 無形で入れたのと同じ**不等式の作法**で裁く: 候補タグの外まで独立に走査し、
            #     生きた（対象年から2年以内の）債務残高の痕跡が**一つも無い**ときだけ debt=0 を事実とする。
            #     痕跡があるのに候補タグで拾えていないなら、それは**未知のタグ**なので従来どおり飛ばし、
            #     どのタグかを警告に出す（NJR/HEI/APHの事故を再発させないため。あの3社は債務が実在した）。
            # 2026-08-03: **「自己資本比」の物差しは債務超過の会社で壊れる**（max(eq,1)だと閾値が
            #   1や0.02へ潰れ、検問が素通り or 全弾きになる）。実測で roic>60 の25社中6社が債務超過
            #   （ORLY/IHG/BKNG/FICO/NATH/GLXZ。大規模自社株買いの結果で、ICは総資産の26〜100%あり
            #   経済的には実体がある）。自己資本が正でないときは**総資産**を物差しにする。
            #   以下の3つの検問（有利子負債の重要性・無形の重要性・IC縮退）で同じ物差しを使う。
            _eqY = S["eq"][y]
            _base = _eqY if _eqY > 0 else (S["assets"].get(y) or 0)
            _what = "自己資本" if _eqY > 0 else "総資産（自己資本がマイナスのため）"
            has_debt = (y in S["debtL"]) or (y in S["debtS"])
            if not has_debt:
                if _debtHist(y):                  # 2026-09-23: 今回足した明細は±2年の窓だけで数える（_debtHist の頭注）
                    # 2026-08-03: 他年に報告があっても、**その額が自己資本比で無視できるなら**
                    #   欠測年を0と読んでよい（上限の不等式）。実測 EXPD は短期銀行借入を
                    #   有る年だけ報告し最大でも自己資本の約1.5%＝ROICを動かせない。
                    #   従来はこの型で5年系列が1年も作れなかった。
                    # 2026-09-23: 今回足した明細の額は±2年の窓の中だけ数える（_debtHist と同じ。LMAT: 2024年発行の転換社債
                    #   168.6百万$ が2021年の「他年の最大」になると、借入の無かった年まで算出不能になる）
                    _mx = max([(S["debtL"].get(_y,0) or 0)+(S["debtS"].get(_y,0) or 0)
                               - (_newDebt.get(_y, 0) if abs(_y - y) > 2 else 0)
                               for _y in set(S["debtL"])|set(S["debtS"])] or [0])
                    if _base > 0 and _mx >= 0.02*_base:
                        roic_skip.append(f"{y}:有利子負債タグ不在でIC算出不能（他年は報告あり＝欠測）")
                        continue
                    _m2 = (f"有利子負債タグが一部の年に無いが、報告のある年の最大でも{_what}の"
                           f"{_mx/max(_base,1)*100:.1f}%＝ROICを動かせない水準なので"
                           f"**欠測年は0として算出**した（上限の不等式）")
                    if _m2 not in note: note.append(_m2)
                else:
                    _eviD = debt_evidence(facts, y)
                    if _eviD:
                        roic_skip.append(f"{y}:有利子負債タグ不在でIC算出不能"
                                         f"（未知のタグに痕跡あり: {', '.join(_eviD[:3])}）")
                        note.append(f"有利子負債の候補タグに当たらないが、{y}年前後に債務の痕跡がある: "
                                    f"{', '.join(_eviD[:5])}。TAGSの拡張が要る（絶対のルール7）")
                        continue
                    # 痕跡ゼロ＝実質無借金。debt=0 は欠測ではなく事実（注記は年ごとに1回だけ）
                    _m = (("有利子負債タグが全年で不発見" if not (S["debtL"] or S["debtS"]) else
                           f"有利子負債の報告は±2年の外（{max(set(S['debtL']) | set(S['debtS']))}年）だけ")
                          + "、かつ独立走査でも債務の痕跡ゼロ＝"
                          "**実質無借金として debt=0 で算出**した（欠測をゼロと読んだのではない）")
                    if _m not in note: note.append(_m)
            debt = (S["debtL"].get(y,0) or 0)+(S["debtS"].get(y,0) or 0)
            # 2026-08-03修正: 無形も有利子負債と同じ「欠測をゼロと読む」事故を起こしていた。
            #   `S["intan"].get(y,0)` は「無形が無い会社」と「その年だけタグが出ていない会社」を
            #   区別できない。**他の年に無形を報告している会社**でその年だけ欠測なら、それは
            #   「無形ゼロ」ではなく「採れなかった」＝算出不能として飛ばす（誤値より空欄）。
            #   一度も無形を報告していない会社だけ 0 と読んでよい（不等式として上限が0だから）。
            if S["intan"] and y not in S["intan"]:
                # 2026-08-03: 負債と同じ**上限の不等式**を無形にも当てる。他年に報告があっても、
                #   その最大額が自己資本比で無視できるなら欠測年を0と読んでよい。
                #   実測 MANH（無形は2011年に0のみ）/ EXPD（2009-2011に3-5百万$＝自己資本の0.2%）は
                #   この検問だけで5年系列が1年も作れなかった。負債側を直したら無形側が同じ形で残っていた。
                _mxI = max(S["intan"].values() or [0])
                if _base > 0 and _mxI >= 0.02*_base:
                    roic_skip.append(f"{y}:無形タグ不在でIC算出不能（他年は報告あり＝欠測）")
                    continue
                _m3 = (f"無形タグが一部の年に無いが、報告のある年の最大でも{_what}の"
                       f"{_mxI/max(_base,1)*100:.1f}%＝ROICを動かせない水準なので"
                       f"**欠測年は0として算出**した（上限の不等式）")
                if _m3 not in note: note.append(_m3)
            # 2026-08-04是正(B12b): **のれんにも無形と同じ欠測ガードを当てる**（CELH型の取り残し）。
            #   他年に Goodwill を報告しているのにその年だけ無い→欠測をゼロと読むと控除が過少＝
            #   IC過大でROICが歪む。上限の不等式で裁き、無視できない額なら算出不能で飛ばす。
            #   一度も報告していない会社だけ 0 と読んでよい（のれんの上限＝0が文書化された例外）。
            if S["gw"] and y not in S["gw"]:
                _mxG = max(S["gw"].values() or [0])
                if _base > 0 and _mxG >= 0.02*_base:
                    roic_skip.append(f"{y}:のれんタグ不在でIC算出不能（他年は報告あり＝欠測）")
                    continue
                _m4 = (f"のれんタグが一部の年に無いが、報告のある年の最大でも{_what}の"
                       f"{_mxG/max(_base,1)*100:.1f}%＝ROICを動かせない水準なので"
                       f"**欠測年は0として算出**した（上限の不等式）")
                if _m4 not in note: note.append(_m4)
            gw, intan = (S["gw"].get(y,0) or 0), (S["intan"].get(y,0) or 0)
            ic = S["eq"][y]+debt-gw-intan
            # 2026-08-16 ユーザー明示指示「3つともやって」: **IC縮退ガードの物差しを ICg（控除前の投下資本）へ。**
            #   閾値20%は据置＝新しい定数を一つも作っていない。動かしたのは分母だけ。
            #   【なぜ自己資本が誤りか】この検問が問うのは「**のれん・無形を引いた結果、投下資本がどれだけ残ったか**」。
            #   その分母は控除**前**の同じ資本＝ICg=自己資本+有利子負債 でなければ意味を成さない。
            #   自己資本を分母にすると、負債の厚い社ほど IC/自己資本 が大きく出て検問が緩む——
            #   実測 MSI は IC/自己資本 69.2% で素通りするが、**IC/ICg は 14.4%**（のれん+無形が投下資本の85.6%を食った）。
            #   【なぜ総資産ではないか】総資産は**資本でない負債を含む**。実測で判定圏を総資産基準にすると
            #   V(16.4%)・ADP(9.6%) が縮退と判定されるが、両社の低さは**顧客資金・決済フロート**のせいで
            #   のれん縮退とは無関係＝機構の違うものを同じ物差しで裁くことになる（「基準の違う二つを割る」型）。
            #   ICg 基準なら V は 24.7% で残る＝**フロートの厚い社を巻き込まずにMSI型だけを捕まえる**。
            #   自己資本が正でないときだけ従来どおり総資産へ倒す（ICg も潰れているため）。
            _icg0 = S["eq"][y] + debt
            _icBase = _icg0 if _icg0 > 0 else _base
            _icWhat = "ICg(自己資本+有利子負債)" if _icg0 > 0 else _what
            # 分母が自己資本の2割を切ったら、のれん・無形の控除でICが縮退している＝発散の前兆。
            #   この帯のROICは「資本が軽い」の言い換えで識別力が無く、桁違いの偽陽性だけを生む。
            # 2026-08-03: **自己資本がマイナスの会社でこの検問が素通りしていた。**
            #   `0.20*max(eq,1)` は eq<0 のとき閾値が 0.2 になるので、**どんな正のICも通る**。
            #   実測で roic>60 の25社のうち6社が債務超過だった（ORLY −763 / IHG −2,736 /
            #   BKNG −5,578 / FICO −1,746 / NATH −14 / GLXZ −17 百万$。大規模な自社株買いの結果で、
            #   IC自体は総資産の26〜100%あり**経済的には実体がある**＝値は本物）。
            #   今回は害が出ていないが、**債務超過かつICが縮退した会社が来たら素通りする**ので塞ぐ。
            #   自己資本が使えないときは**総資産**を物差しにする（縮退の意味は「資本の実体に対して
            #   分母が小さすぎる」なので、資本の代理として総資産を使うのが素直）。
            if ic <= 0 or (_icBase > 0 and ic < 0.20*_icBase):
                roic_skip.append(f"{y}:IC={ic:.0f}が{_icWhat}{_icBase:.0f}の2割未満＝のれん控除で分母縮退"
                                 if ic > 0 else f"{y}:IC={ic:.0f}が負＝算出不能")
                continue
            # 2026-08-04是正(B12c): roicg 側の分母にも縮退ガードを当てる。従来の `max(eq+debt,1)` は
            #   債務超過＋低負債で分母が1へ潰れ、roicg が発散した（「比率で裁く検問は分母の符号を
            #   確かめよ」の取り残し——roic側だけ2026-08-03に塞いでいた）。eq>0 なら eq+debt≥eq で
            #   このガードは決して誤爆しない＝効くのは債務超過の会社だけ。
            icg = S["eq"][y] + debt
            if icg <= 0 or (_base > 0 and icg < 0.20*_base):
                roic_skip.append(f"{y}:のれん込みIC={icg:.0f}が"
                                 + (f"{_what}{_base:.0f}の2割未満（債務超過で有利子負債も薄い）＝算出不能"
                                    if icg > 0 else "負または0＝算出不能"))
                continue
            roics.append((nopat/ic*100, nopat/icg*100, y))
            # 実額を残す。**IC/自己資本が本当の判別子**（2026-07-29の19社検算で確立——
            # 「roic>60だから怪しい」はほぼ外れ、MAは74.9→131.0の上方修正だった）。
            # 比率だけでは後から検算できないので、NOPAT・自己資本・負債・のれん・無形の各実額を書く。
            evd["roic"] = (f"機械算出 {y}年: NOPAT {_u(nopat)}（営業利益 {_u(S['op'][y])}×(1−実効税率"
                           f"{max(0,min(0.5,tax_rate)):.1%})） ÷ IC {_u(ic)}"
                           f"＝自己資本 {_u(S['eq'][y])} + 有利子負債 {_u(debt)} − のれん {_u(gw)}"
                           f" − 無形 {_u(intan)}。**IC/ICg={ic/max(_icBase,1)*100:.1f}%**"
                           f"（ICg=自己資本+有利子負債＝控除前の投下資本。2割未満なら分母縮退＝算出不能。"
                           f"絶対のルール7(b)）｜参考 IC/自己資本={ic/max(S['eq'][y],1)*100:.1f}%"
                           f"｜有利子負債の内訳: "
                           f"{' + '.join((ev['_debtUsed']['debtL'].get(y) or []) + (ev['_debtUsed']['debtS'].get(y) or [])) or '—'}")
    if roic_skip:
        note.append("roic系列の一部を算出不能として除外: " + " / ".join(roic_skip))
    # 2026-08-03: **roicg の5年系列も同じ年・同じNOPATから対で作る。** roicだけ through-cycle 化すると
    #   roic<roicg（NOPAT>0では数学的に不可能）ができる＝「基準の違う二つを割る」型。
    _rSeq = [x[0] for x in roics]
    _gSeq = [x[1] for x in roics]
    # 2026-08-03: **年つきの系列も出す。** through-cycle をパックへ当てるとき、比は
    #   「パックが審査した年」で取らないと意味を持たない——採取器とパックが別の会計年度を
    #   見ている社があるため（実測 MSFT: 採取器FY2026 / パックFY2025）。
    #   検査器側で系列を組み直すと採取器と違う判定になるので（v9.9.65の教訓）ここで出す。
    if roics: ev["_tcSeries"] = {str(x[2]): [round(x[0],2), round(x[1],2)] for x in roics}
    # 2026-09-23: 系列の最新年が古い（stale）かどうか。判定と理由は下の「年検問」の節を見よ
    _tcStale = bool(roics) and stale(max(x[2] for x in roics))
    # 2026-08-03: **3年未満の「中央値」は through-cycle ではない。** 従来は `if roics:` で
    #   1-2年でも med5/w5 を出していたため、在庫を数えると220社に見えたが実体は179社だった
    #   （1点の中央値はその点そのもの）。3年以上のときだけ出す。
    #   2026-09-23: 系列が古い（_tcStale）ときも出さない＝古い窓の中央値を through-cycle と名乗らせない
    if len(roics) >= 3 and not _tcStale:
        ev["roicExW5"]  = round(min(_rSeq),1)
        ev["roicExMed5"]= round(median(_rSeq),1)
        ev["roicgW5"]   = round(min(_gSeq),1)
        ev["roicgMed5"] = round(median(_gSeq),1)
        ev["_tcYears"]  = len(_rSeq)
    # 2026-08-10: **年検問を through-cycle にも掛ける。**
    #   他の欄には「全系列の最新年から2年以上遅れたら算出不能」という検問（BKNG事故の対策）が
    #   あるのに、**roic の through-cycle 経路にだけ掛かっていなかった**。
    #   実測 STX: roic が **FY2022** の1年しか作れないのに gm/ni は FY2025＝
    #   **同じパックの中で3年ずれた値が並ぶ**（「取れた値＝最新の値」のBKNG型）。
    #   3年未満で med5 を出さない検問は入っているが、**古い年の単年値がそのまま roic として
    #   残る経路**は塞がっていない。ここで注記を出して審査官に見せる。
    # 2026-09-23是正: **上の注記は注記だけで、値は出し続けていた。** 今日の採取器でも STX は
    #   roic 42.6 / roicg 33.4 を返していた＝`_tcSeries` {2022: [42.58, 33.36]} の **FY2022 の1年**
    #   （NOPAT 1,920,068,493 ÷ IC 4,509,000,000＝自己資本 109,000,000 + 有利子負債 5,646,000,000
    #   − のれん 1,237,000,000 − 無形 9,000,000）。2023年は IC −1,409,000,000 で負、2024/2026/2027年は
    #   無形タグ不在で算出不能——全系列の最新 2027年から5年遅れの値が「当期の roic」として出ていた。
    #   審査官は原本で空欄に直していた（out/STX_gate_pack.json の _meta.nulls.roic「42.6 は4年前の値」）。
    #   ※年は SEC の fy ラベル。STX は FY2025 の10-K（0001137789-25-000157）が fy=2027 と付番されており
    #     「2027年」の実体は FY2025（別の穴・ここでは直さない）。実体の最新 FY2026 で測っても 2022 は stale。
    #   → 系列の最新年が **stale()**（他の欄と同じ規則＝全系列の最新年 LATEST から2年以上遅れ）に当たるなら
    #     through-cycle の roic/roicg（中央値）・roicExW5/Med5・roict を**出さない**（誤値より空欄）。
    #     roicg は単年値へも倒さず対で空欄にする（理由は下の中央値ブロックの 2026-09-23 の注）。
    #     年つきの `_tcSeries` は残す（年ラベルつきの記録で「最新」を名乗らない）。
    #   ⚠ 物差しを stale() に揃えた: 旧注記は op/eq/rev の最新年で測っていた（stale() は ni/assets/ocf も見る）。
    if _tcStale:
        _tcLatest = max(x[2] for x in roics)
        note.append(f"roic算出不能: ROIC系列の最新は **{_tcLatest}年**（{len(_rSeq)}年分・中央値 roic "
                    f"{median(_rSeq):.1f}% / roicg {median(_gSeq):.1f}%）で、全系列の最新 {LATEST}年から"
                    f"{LATEST - _tcLatest}年遅れている。**古い年の値を当期の roic として出さない**"
                    f"（BKNG型『取れた値＝最新の値』の同族・誤値より空欄）。roic/roicg は対で空欄"
                    f"（roicg を単年値へ倒さない）、roicExW5/Med5・roict も出さない。"
                    f"原本で最新年の投下資本を確認して手入力せよ")
    # 純希薄化率(株数の年率変化)
    sh,_ = series(facts, TAGS["sh"], ("shares",))
    if len(sh)>=3:
        # 2026-07-29修正: 従来は生の株数をそのまま比べていたので、**株式分割をまたぐと
        #   希薄化として計上された**。実測 NVDA: 2,466百万株(2023) → 24,304百万株(2026) は
        #   2024年6月の10:1分割によるもので、dilNet=+114.4%/年（＝毎年株数が倍増）と出ていた。
        #   分割調整後の実態は −0.5%/年（自社株買いで減少）＝**符号が逆**。
        #   門は dilNet を純還元(現金還元−希薄化)に使うので、これはE[r]を直接壊す。
        #   SECのcompanyfactsに分割情報は無く、機械では「分割」と「大型増資」を区別できない。
        #   → **不連続の手前は捨て、直近の連続区間だけで測る**（絶対のルール7と同じ思想＝
        #     区別できないものを片方に決め打ちしない）。区間が取れなければ空欄＋理由。
        ys = sorted(sh)[-4:]
        cut = 0
        for i in range(1, len(ys)):
            r = (sh[ys[i]] / sh[ys[i-1]]) if sh[ys[i-1]] else 0
            if r and (r > 1.4 or r < 0.6):
                cut = i                      # ここで不連続。以降だけを使う
        ys = ys[cut:]
        if cut:
            note.append(f"dilNet: {sorted(sh)[-4:][cut-1]}→{ys[0]}年に株数が"
                        f"{sh[ys[0]]/max(sh[sorted(sh)[-4:][cut-1]],1):.1f}倍に不連続変化（株式分割の疑い）。"
                        f"手前を捨てて{ys[0]}年以降で算出")
        span = (ys[-1] - ys[0]) if len(ys) >= 2 else 0
        if span <= 0:
            note.append("dilNet算出不能: 不連続を除くと連続区間が1年未満。"
                        "原本の株主資本等変動計算書で分割調整後の株数を確認して手入力せよ")
        else:
            d0,d1 = sh[ys[0]], sh[ys[-1]]
            _safe(ev, note, "dilNet", lambda: round(((d1/d0)**(1/span)-1)*100,2) if d0 else None)
            if ev.get("dilNet") is not None:
                evd["dilNet"] = (f"機械算出: 株数 {ys[0]}年 {_u(d0)} → {ys[-1]}年 {_u(d1)}"
                                 f"＝{span}年の年率（自社株買い後の純希薄化）"
                                 + (f"。**{ys[0]}年より前は株数の不連続（分割の疑い）があるため除外**" if cut else ""))
    # 減損履歴(配)
    # 2026-08-04是正(B12e): 「直近5年」は**年ラベルで**選ぶ。旧 `list(...values())[-5:]` は挿入順の
    #   末尾5件＝最新5年とは限らない（fcfpsのフォールバックと同じ思い込み）
    # 2026-09-23是正: B12e の `sorted(...)[-5:]` も**「最後の5ラベル」であって「直近5年」ではなかった**。
    #   減損の系列は計上した年にしか行が無い（まばら）ので、最後の5ラベルが10年以上前まで届く——
    #   実測（旧採取器・296社）で 48社の acqImpair="yes" が5会計年度より前の減損だけで立っていた
    #   （CDNS/MA は2010年、NDSN は2011年、PH は2014-16年）。年の付け方の是正で比較年度の持ち越し
    #   （翌年・翌々年のラベルに同じ減損額が残る）が消えると系列はさらにまばらになり、AZO は2013年の
    #   18,300,000 で新たに "yes" になりかけた。→ **全系列の最新年 LATEST から5年以内のラベル**だけを見る。
    if S["impair"] and LATEST is not None and any(v > 0 for y, v in S["impair"].items() if y > LATEST - 5):
        ev["acqImpair"] = "yes"; note.append("のれん/無形減損の計上履歴あり(配=保S候補、原本で規模確認)")
    # 循環性の機械プロキシ: 売上の前年比が5年内にマイナス2回以上 or 振れ幅>25pt
    if len(rev)>=4 and all(rev[i] for i in range(len(rev)-1)):
        g = [(rev[i+1]/rev[i]-1)*100 for i in range(len(rev)-1)]
        ev["cyclical"] = "yes" if (sum(1 for x in g if x<0)>=2 or (max(g)-min(g))>25) else "no"
    # ===== 門(v9.6)フォーマット用の追加算出 =====
    # 営業利益率 gm(%) 直近年
    if y0 and y0 in S["op"] and S["rev"].get(y0):
        _safe(ev, note, "gm", lambda: round(S["op"][y0]/S["rev"][y0]*100,1))
        if ev.get("gm") is not None:
            # 門のgm欄は**営業利益率**であって粗利率ではない（日本株で粗利混入が36社中12社で再発）。
            # 実額を残せば取り違えは目で見える。
            evd["gm"] = f"機械算出 {y0}年: 営業利益 {_u(S['op'][y0])} ÷ 売上 {_u(S['rev'][y0])}（粗利ではない）"
    # 営業利益率トレンド gmt (3年: up/flat/down)
    if S["op"] and S["rev"]:
        oy = sorted(set(S["op"])&set(S["rev"]))[-3:]
        if len(oy)>=2 and not stale(oy[-1]) and S["rev"].get(oy[0]) and S["rev"].get(oy[-1]):
            m0=S["op"][oy[0]]/S["rev"][oy[0]]*100; m1=S["op"][oy[-1]]/S["rev"][oy[-1]]*100
            ev["gmt"]="up" if m1-m0>1 else "down" if m1-m0<-1 else "flat"
            evd["gmt"] = f"機械算出: 営業利益率 {oy[0]}年 {m0:.1f}% → {oy[-1]}年 {m1:.1f}%（±1ptでup/down）"
    # のれん込みROIC roicg (直近年・のれん除外しない版)
    # 2026-08-04是正(B12a/c): (a)税タグ欠測年を税率0%と読まない——従来は `S["tax"].get(y0,0)` で
    #   NOPAT=EBITになっていた（5年系列側と同じ穴の直近年版）。(b)分母の `max(eq+debt,1)` は
    #   債務超過＋低負債で1へ潰れて発散するので、roic側と同じ縮退ガード（eq>0なら誤爆しない）。
    if y0 and all(y0 in S[k] for k in ("op","ni","eq")):
        if y0 not in S["tax"]:
            note.append(f"roicg算出不能: {y0}年に税タグが無く実効税率が測れない（税0%と断定しない）")
        else:
            _d0 = (S["debtL"].get(y0,0) or 0)+(S["debtS"].get(y0,0) or 0)
            _icg0 = S["eq"][y0] + _d0
            _b0 = S["eq"][y0] if S["eq"][y0] > 0 else (S["assets"].get(y0) or 0)
            # 2026-09-23是正（todo fetcher_single_roicg_debt0・絶対のルール7）: 有利子負債タグが無い年を0と読み、
            #   根拠文に「過大の可能性あり」と書くだけで値を出していた。この単年値は through-cycle の中央値が
            #   組めない社（系列が1年も無い／古い）でだけ表に出るので、中央値の上書きに隠れて見えなかった。
            #   nde と同じく debt_evidence() で裁く——痕跡ゼロなら無借金は事実（値を出す）、
            #   痕跡があるなら**出さない**（誤値より空欄。MGRC は NotesPayable 658.8百万$ があるのに0と読んでいた）。
            _noDebtTag = not ((y0 in S["debtL"]) or (y0 in S["debtS"]))
            _dTrace = debt_evidence(facts, y0) if _noDebtTag else []
            if _noDebtTag and _dTrace:
                note.append(f"roicg算出不能: {y0}年に有利子負債タグが無いのに負債の痕跡がある"
                            f"（{', '.join(_dTrace[:3])}）。0と読むと分母が縮み roicg が過大に出るので空欄にした"
                            f"——原本のBSで有利子負債を確認して手入力せよ")
            elif _icg0 <= 0 or (_b0 > 0 and _icg0 < 0.20*_b0):
                note.append(f"roicg算出不能: {y0}年ののれん込みIC={_icg0:.0f}が縮退"
                            f"（債務超過で有利子負債も薄い＝分母に実体が無い）")
            else:
                _tax0 = 1 - S["ni"][y0]/max(S["ni"][y0]+S["tax"][y0], 1)
                _safe(ev, note, "roicg",
                      lambda: round(S["op"][y0]*(1-max(0,min(0.5,_tax0)))/_icg0*100, 1))
        if ev.get("roicg") is not None:
            _d = (S["debtL"].get(y0,0) or 0)+(S["debtS"].get(y0,0) or 0)
            evd["roicg"] = (f"機械算出 {y0}年: NOPAT ÷ (自己資本 {_u(S['eq'][y0])} + 有利子負債 {_u(_d)})"
                            f"＝のれん込み。roic(除外)との差が買収規律の指標"
                            + ("" if ((y0 in S['debtL']) or (y0 in S['debtS']))
                               else "。有利子負債タグ不在・負債の痕跡ゼロ（debt_evidence）＝無借金と断定して0"))
    # のれん除外ROIC 直近年 roic (門のroic欄=単年・除外)
    # 5年系列そのものは古い年を含んでよい（それが系列の意味）。検問するのは**直近値の年**だけ——
    # 古い年の値を"直近ROIC"として台帳に載せないため。
    # v9.9.72（2026-08-03・ユーザー明示指示「今の12社に忖度するのではなく本当に必要なものを」）:
    #   **roic / roicg は単年でなく through-cycle＝5年の中央値**。
    #   【なぜ重みでなくここを直したか】audit_weights --q75 の実測で 単年roic の実効ウェイトは **38.2%**
    #   ＝単独最大なのに、時間を通して見る欄は合計12.7%、`sustain`(.30・名前は「持つか」)の中身も
    #   堀とROICの**現在値だけ**だった。ところが重みを上げる案は7案すべて**投下可が増えるだけ**
    #   （night/shadow_time_axis.py）——判定帯の変動係数が p4 7.9% / f1 6.4% / p1 13.5% / p2 19.1% に対し
    #   **roic 64.0%**＝時間軸の欄はほぼ定数で、定数の重みを上げても順位は動かない
    #   （v9.9.43のgmPt・v9.9.45のTAM柱と同じ「情報を持たない定数」の病）。
    #   **roicが支配的なのは重みが大きいからではなく、判定帯で唯一ばらついている数字だから。**
    #   【なぜ中央値か】roic欄が答えるべきは「この事業が通常いくら稼ぐか」で、中央値がその推定量。
    #   周期性は **p1（同じ5年系列の変動係数）が既に別枠で測っている**ので、水準へ折り込むと二重計上。
    #   5年最悪値は「一年が決める」問題を悲観側へ置き換えるだけ（実測で投下可12→7。IRMD/NVDA/6857等が
    #   谷の1年で脱落、いずれもWACC超なのに）。min(直近,中央)は投下可12社を保つが、
    #   **保つこと自体を選定理由にしたのは忖度**であり、技術的根拠（roicGapの誤発火）も
    #   **実装の副作用**だった——単一係数が roicGap の信号を潰していた。実測 APH の本当の
    #   through-cycle 乖離は 中央roic42.2 − 中央roicg16.1 = **26.1pt**（罰の線15pt）で、
    #   単年だと12.4ptと線のすぐ下に隠れる＝**単年測定が買収依存を隠していた**。
    #   【roicgも同時に】中央値どうしなら系列が点ごとに roic_y≥roicg_y なので恒等式が保たれる。
    # 2026-09-23: 系列が古い（_tcStale）ときは出さない（上の「年検問」の節・実測 STX）。営業利益系列そのものが
    #   古いときは従来の注記も残す（その場合 _tcStale も必ず真——系列の年は営業利益の年の部分集合だから）。
    if roics and not _tcStale and not stale(max(S["op"]) if S["op"] else None) and len(_rSeq) >= 3:
        ev["roic"]=round(median(_rSeq),1)
        if _gSeq: ev["roicg"]=round(median(_gSeq),1)
        evd["roic"]=(evd.get("roic","")+f"｜**v9.9.72: through-cycle 化**。5年系列 {len(_rSeq)}年の"
                     f"**中央値 {median(_rSeq):.1f}%** を採用（直近年 {_rSeq[-1]:.1f}% / 最悪 {min(_rSeq):.1f}%）。"
                     f"roicg も同じ年の系列の中央値 {median(_gSeq):.1f}% にして roic≥roicg を保つ")
    elif roics and not _tcStale and not stale(max(S["op"]) if S["op"] else None):
        # 2026-09-23是正: **有効な年が3年未満なら中央値を出さない**（7-c の3年ガード。上の Med5/W5 には入っていたが
        #   roic 本体には無く、2年なら**2年の平均**を through-cycle と名乗って出していた。実測 BCPC: 2021年 35.96 と
        #   2025年 49.43 の平均 42.7 ——どちらの年の値でもない）。直近の有効年の単年値を**対で**出し、単年と明記する。
        ev["roic"] = round(_rSeq[-1], 1)
        ev["roicg"] = round(_gSeq[-1], 1)
        evd["roic"] = (evd.get("roic", "") + f"｜**単年**: 有効な系列が {len(_rSeq)}年（{', '.join(str(x[2]) for x in roics)}）で"
                       f"3年未満＝through-cycle 不可（7-c）。{roics[-1][2]}年の値を roic/roicg の対で採った")
        evd["roicg"] = (f"機械算出 {roics[-1][2]}年（単年・roic と同じ年）: {_gSeq[-1]:.1f}%。"
                        f"有効な系列が3年未満のため中央値にしない")
    elif roics and stale(max(S["op"]) if S["op"] else None):
        note.append(f"roic算出不能: 営業利益系列が{max(S['op'])}年で途切れ最新{LATEST}年から遅れている"
                    f"（タグ改称の疑い）。原本で確認して手入力せよ")
    if _tcStale:
        # 出さない欄に機械の根拠を残さない——run() は _evid から provenance="machine" を刻むので、
        #   空欄の roic に「機械算出 2022年: …」が付くと出所と空欄が食い違う（古い年と値は注記に残してある）
        evd.pop("roic", None)
        # roicg も**対で**出さない（v9.9.72 の対の作法。STX の審査官も nulls.roicg に「roic と同じ理由
        #   （同じ系列から作られる）」と書いた）。上の単年ブロックの値を残すと、単年ブロックは有利子負債タグが
        #   無い年を0と読む（根拠文に「過大の可能性あり」と書くだけ）ので、中央値の上書きが消えた途端に
        #   その値が表へ出る——実測（全米国パック296社を旧版と突き合わせ）で8社が該当し、
        #   TRN は roicg 15.3 → **44.3**（有利子負債 0 扱い。パックの原本値は有利子負債 5,442.5百万$）になった。
        ev.pop("roicg", None)
        evd.pop("roicg", None)
    # ===== ROIIC（増分投下資本利益率・v9.9.46 / 2026-07-29新設） =====
    #   なぜ機械で出すか: roiic は門の未来門 F6「内部複利」の入力だが、**全316パックで空欄**だった。
    #   空欄だと roiicNA=true で F6 は中身に入らず **58 の定数**を返し、
    #   「再投資率＝1−FCF転換率」の計算は一度も実行されず、キル「ROIIC³<WACC（複利停止）」も
    #   一度も発火していなかった。滑走路（あとどれだけ複利できるか）の本体は
    #   g = 再投資率 × ROIIC なので、ここが死んでいると門は複利余地を測れない。
    #
    #   **のれん込みの投下資本(自己資本+有利子負債)を使う。** ROIICは「次の1ドルが何を稼いだか」。
    #   買収に使った金も投じた資本なので、のれんを除外すると連続買収企業のROIICが過大に出る
    #   （$10Bの買収で$1BのNOPATが増えたなら、それは10%であって、有形分だけで測った数字ではない）。
    #   門のroicは「のれん除外＝事業の質」で別目的。コード上の比較先はどちらもWACC。
    #
    #   欠測・縮退の扱い（絶対のルール7）:
    #     ΔIC ≤ 0 または ΔIC/IC(古) < 10% → **'na'**。これは失敗ではなく
    #       「成熟還元型＝再投資が限定的」という意味のある答えで、門はroiicNAをその型として扱う
    #       （F6=58）。**判らないときに低い数字を置くと、複利停止キルを誤爆させる。**
    #     |ROIIC| > 150% → 'na'。分母が小さすぎて識別力が無い帯（roicの2割ガードと同じ思想）
    def _nopat_ic(y):
        """のれん込みIC と NOPAT。取れなければ None"""
        if not all(y in S[k] for k in ("op","ni","eq")):
            return None
        if not ((y in S["debtL"]) or (y in S["debtS"])):
            return None                      # タグ不在を0と読まない
        if y not in S["tax"]:
            return None                      # 2026-08-04是正(B12a): 税タグ欠測を税率0%と読まない
        tr = 1 - S["ni"][y]/max(S["ni"][y]+S["tax"][y], 1)
        np_ = S["op"][y]*(1-max(0,min(0.5,tr)))
        icg = S["eq"][y] + (S["debtL"].get(y,0) or 0) + (S["debtS"].get(y,0) or 0)
        # 2026-08-04是正(B12c): 債務超過＋低負債の縮退分母を弾く（roic側と同じ物差し）
        _b = S["eq"][y] if S["eq"][y] > 0 else (S["assets"].get(y) or 0)
        if icg <= 0 or (_b > 0 and icg < 0.20*_b):
            return None
        return (np_, icg)

    def _roiic(win):
        """win年窓のROIIC。戻り: (値 or 'na', 根拠文)"""
        ys = sorted(S["op"])
        if not ys or stale(ys[-1]):
            return None, None
        y1 = ys[-1]
        cand = [y for y in ys if y <= y1 - win]
        if not cand:
            return None, None
        y0 = cand[-1]
        a, b = _nopat_ic(y0), _nopat_ic(y1)
        if not a or not b:
            return None, None
        dn, dic = b[0]-a[0], b[1]-a[1]
        base = (f"機械算出 {y0}→{y1}年({y1-y0}年窓): ΔNOPAT {_u(dn)} ÷ Δ投下資本 {_u(dic)}"
                f"（IC=自己資本+有利子負債＝**のれん込み**。買収に投じた資本も分母に入れる）"
                f"｜IC {_u(a[1])}→{_u(b[1])}（{dic/max(a[1],1)*100:+.1f}%）")
        if dic <= 0 or dic < 0.10*a[1]:
            return "na", base + " → Δ投下資本が10%未満（または減少）＝**成熟還元型**として na。再投資が限定的で増分利回りは定義できない"
        v = round(dn/dic*100, 1)
        if abs(v) > 150:
            return "na", base + f" → 算出値{v}%は分母が小さく識別力なし＝na（絶対のルール7(b)と同じ思想）"
        return v, base

    _r3, _e3 = _roiic(3)
    _r5, _e5 = _roiic(5)
    # **低い3年窓は、5年窓の裏付けが取れないなら書かない。**
    #   門は roiic<WACC を「複利停止」キル（Ωを60で頭打ち）に使い、その誤爆を防ぐために
    #   5年窓レスキュー（3年窓がサイクルピークを跨ぐ場合）を持っている。5年窓が取れない会社では
    #   **そのレスキューが構造的に働けない**ので、投資サイクルの谷（新工場・大型買収の直後で
    #   まだ利益が出ていない）と構造的な複利停止を、門が区別する手段が無くなる。
    #   実測(2026-07-29): 新たにキルが立った30社のうち7社が5年窓なしだった（ADI/SSD/IT/BBY/CHH/HCKT等。
    #   ADIはMaxim買収、TXNは300mm新工場の建設期＝門0の病名でいう「谷」に当たる）。
    #   この道具の原則どおり**迷ったら'na'に倒す**——判らないときに低い数字を置くと誤爆させる。
    if isinstance(_r3, (int, float)) and _r3 < 15 and not isinstance(_r5, (int, float)):
        _e3 = (_e3 or "") + f" → 3年窓{_r3}%は低いが**5年窓が取れず門の5年窓レスキューが働けない**" \
              "＝投資サイクルの谷と構造的な複利停止を区別できないため na（誤値より空欄）"
        _r3 = "na"
    if _r3 is not None:
        ev["roiic"] = _r3
        evd["roiic"] = _e3
    if _r5 is not None:
        ev["roiic5"] = _r5
        evd["roiic5"] = _e5

    # ROICトレンド roict (5年 up/flat/down): worst年 vs 直近
    # 2026-09-23: 系列が古い（_tcStale）なら出さない——「直近」が当期でない傾きを当期の趨勢と名乗らせない
    if len(_rSeq)>=2 and not _tcStale:
        ev["roict"]="up" if _rSeq[-1]-_rSeq[0]>2 else "down" if _rSeq[-1]-_rSeq[0]<-2 else "flat"
        evd["roict"] = (f"機械算出: のれん除外ROIC 5年系列 "
                        f"{' / '.join(f'{x:.1f}%' for x in _rSeq)}（最古→直近の差で判定）")
    # GP/A(gpa) 直近年
    if y0 and y0 in S["gp"] and S["assets"].get(y0):
        _safe(ev,note,"gpa",lambda:round(S["gp"][y0]/S["assets"][y0]*100,1))
        if ev.get("gpa") is not None:
            evd["gpa"] = f"機械算出 {y0}年: 売上総利益 {_u(S['gp'][y0])} ÷ 総資産 {_u(S['assets'][y0])}"
    # fcf/ni の生値(門はfcf・niを直接欄に持つ。単位は_unit/1e9でB表示)
    if y0 and y0 in S["ocf"] and y0 in S["capex"]:
        # 2026-07-29修正: 従来は小数2桁（＝十億$の百分の一＝千万$刻み）で丸めていた。
        #   門は fcf/ni を**比**でしか使わない（conv＝FCF転換率、reinvest＝1−conv）ので
        #   単位が揃っていれば単位自体は無害だが、**小型株では丸めが比を壊す**。
        #   実例 IRMD: FCF $24百万 / NI $16百万 は 0.02/0.02 となり conv=100%（真値150%）。
        #   有効数字を残す桁数で丸める。
        u=1e9
        ev["fcf_abs"]=round((S["ocf"][y0]-abs(S["capex"][y0]))/u,4)
        evd["fcf"] = (f"機械算出 {y0}年: 営業CF {_u(S['ocf'][y0])} − 設備投資 {_u(abs(S['capex'][y0]))}"
                      f"（÷1e9で十億単位表示。設備投資のみ控除＝買収は含めない）")
        if S["ni"].get(y0) is not None:
            ev["ni_abs"]=round(S["ni"][y0]/u,4)
            evd["ni"] = f"機械算出 {y0}年: 純利益 {_u(S['ni'][y0])}（÷1e9で十億単位表示）"
    # eps(TTM近似=直近NI/株数)
    sh2,_=series(facts,TAGS["sh"],("shares",))
    if y0 and sh2 and (sh2.get(y0) or 0):
        _safe(ev,note,"eps",lambda:round(S["ni"][y0]/sh2[y0],2))
        if ev.get("eps") is not None:
            evd["eps"] = f"機械算出 {y0}年: 純利益 {_u(S['ni'][y0])} ÷ 株数 {_u(sh2[y0])}（TTMではなく通期実績）"
    # 債務超過判定 eq (pos/neg)
    # 2026-08-04是正(B12d): 従来は出力側で `"neg" if (…and False) else "pos"` ＝**恒久的にposと断定**
    #   していた（未測定を最良ケースで採点させる型・RELXのdisruptと同族）。自己資本の最新年の符号で
    #   実測する。系列が無い/古すぎるなら**空欄**（posと断定しない。理由は_meta.nullsへ）。
    if S["eq"]:
        _ye = max(S["eq"])
        if not stale(_ye):
            ev["eqSign"] = "neg" if S["eq"][_ye] < 0 else "pos"
            evd["eq"] = (f"機械算出 {_ye}年: 自己資本 {_u(S['eq'][_ye])} → "
                         + ("**債務超過(neg)**" if S["eq"][_ye] < 0 else "正(pos)"))
        else:
            note.append(f"eq(債務超過判定)算出不能: 自己資本系列が{_ye}年で途切れ最新{LATEST}年から"
                        f"遅れている——posと断定しない（原本のBSで確認して手入力せよ）")
    else:
        note.append("eq(債務超過判定)算出不能: 自己資本タグ不発見——posと断定しない")
    # 業態fin: 金融判定(粗い) — 純利が金利収入主体かは判定不能なのでnull据置
    ev["_unit"] = series(facts, TAGS["rev"])[1]
    ev["_note"] = note
    ev["_diag"] = diag   # 自己申告: 取れたタグ/取れなかったタグ
    return ev

# ---------- 原本: キーワード砲台 ----------
BATTERY = {
 "限": [r"patent[s]? (?:expir|protection)", r"loss of exclusivity", r"exclusivity", r"license[s]? .{0,40}expir",
        r"concession[s]? .{0,60}(?:expir|term|until 20\d\d)", r"expiration of (?:our|the) concession"],
 "集": [r"largest customer", r"customers? accounted", r"\d{1,2}(?:\.\d)?% of (?:our )?(?:total )?(?:net )?(?:sales|revenue)",
        r"sole suppli", r"single[- ]source", r"single suppli", r"concentration of"],
 "誠": [r"material weakness", r"was not effective", r"unresolved staff comments",
        r"notice of proposed adjustment", r"accrued .{0,30}litigation", r"IRS"],
 "蝕": [r"market share", r"pricing pressure", r"competit.{0,20}intensif"],
 "堀": [r"barriers to entry", r"network effect", r"switching cost", r"economies of scale", r"installed base"],
 "循": [r"cyclical", r"cyclicality"],
}
def latest_annual_url(cik):
    j = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    r = j["filings"]["recent"]
    for i,f in enumerate(r["form"]):
        if f in ("10-K","20-F","40-F"):   # 40-F=カナダMJDSの年次報告（2026-07-29追加。詳細は _annual の頭注）
            acc = r["accessionNumber"][i].replace("-","")
            doc = r["primaryDocument"][i]
            return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}", r["reportDate"][i], f
    raise SystemExit("年次報告が見つからない")

def strip_html(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S|re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;?", " ", h); h = re.sub(r"&amp;", "&", h)
    return re.sub(r"[ \t]{2,}", " ", h)

def hit_report(text, width=300, per_kw=3):
    lines = []
    for cat, pats in BATTERY.items():
        lines.append(f"\n===== {cat} =====")
        n = 0
        for p in pats:
            for m in re.finditer(p, text, re.I):
                if n >= per_kw*len(pats): break
                s = max(0, m.start()-width//2)
                snippet = re.sub(r"\s+"," ", text[s:s+width])
                lines.append(f"[{p}] …{snippet}…")
                n += 1
        if n == 0: lines.append("(ヒットなし)")
    return "\n".join(lines)

# ---------- main ----------
def run(ticker):
    cik = cik_of(ticker)
    print(f"{ticker}: CIK {cik}")
    ev = build_numbers(facts_of(cik))
    url, rdate, form = latest_annual_url(cik)
    txt = strip_html(get(url))
    rep = hit_report(txt)
# ===== 門(壊れない複利の門 v9.6)フォーマットで出力 =====
    # SEC由来の客観値のみ充填。市場データ(px/beta/per/perF/evebit/shy/gr)と主観(p1-4/f1-5/dom/irr/rep/dur/erosion/disrupt/geopol)はnull=空欄
    draft = {
        "nm": ticker.upper(),
        # --- 第一の門: 生存・複利(SEC充填) ---
        "roic": ev.get("roic"), "roicg": ev.get("roicg"),
        # v9.9.46: ROIIC³（増分投下資本利益率）。門の未来門F6「内部複利」の入力。
        #   'na' は失敗ではなく「成熟還元型＝再投資が限定的」という意味のある答え（門はF6=58で扱う）
        "roiic": ev.get("roiic"), "roiic5": ev.get("roiic5"),
        "nde": ev.get("nde"), "z": None,               # z=Altman: 要別計算(運転資本等)→当面手当て、空欄=保留
        "gpa": ev.get("gpa"), "accr": ev.get("accr"),
        "gm": ev.get("gm"), "gmt": ev.get("gmt"), "roict": ev.get("roict"),
        "cagr": ev.get("cagr5"),
        "fcf": ev.get("fcf_abs"), "ni": ev.get("ni_abs"),
        "sbc": None, "dilNet": ev.get("dilNet"),
        "acc": {"USD":"usgaap","EUR":"ifrs","JPY":"jgaap"}.get(ev.get("_unit"),"usgaap"),
        # 2026-08-04是正(B12d): 自己資本の実測符号（build_numbersのeqSign）。測れなければnull＝
        #   posと断定しない（旧実装は `…and False` で恒久pos断定だった）。理由は_meta.nullsに残す
        "eq": ev.get("eqSign"),
        "acq5": "yes" if ev.get("acqImpair")=="yes" else None,
        "eps": ev.get("eps"),
        # --- 定性(原本読み・空欄=保留) ---
        "expiry": None,       # ★限: hits.txtの限セクションを読んで no/yes/na
        "moatdecay": None,    # ★堀減衰: 蝕セクション
        "erosion": None, "disrupt": None,
        "dom": None, "irr": None, "rep": None, "dur": None,
        "geopol": None,       # 集中・地政学: 集セクション
        "nrr": None,
        # --- 市場データ(AV/手入力・空欄) ---
        "beta": None, "per": None, "perF": None, "evebit": None,
        "px": None, "shy": None, "gr": None, "gcap": None,
        # --- 外部・書記(空欄) ---
        "analysts": None, "instOwn": None, "gls": None, "idx": None,
        "indG": None, "founder": None, "fin": None,
        "p1": None, "p2": None, "p3": None, "p4": None,
        "f1": None, "f2": None, "f3": None, "f4": None, "f5": None,
        "_meta": {"form": form, "reportDate": rdate, "unit": ev.get("_unit"),
                  "source": url, "notes": ev.get("_note",[]), "diag": ev.get("_diag",{}),
                  # 2026-07-29新設。**根拠と出所を値と同時に刻む**——これが無かったために、
                  #   原本から測った値とそれらしく置いた値が台帳上まったく同じ見た目になり、
                  #   誤りは人が1件ずつ読むまで見つからなかった（機械項目の根拠被覆率9.8%）。
                  # provenance は「誰が置いたか」。審査官は machine の欄を上書きしてはならない
                  #   （検算して直すのは可。その場合は _meta.kenshi に旧→新と原本根拠を書く）。
                  "evidence": {k: v for k, v in (ev.get("_evid") or {}).items() if v},
                  "provenance": {k: "machine" for k, v in (ev.get("_evid") or {}).items() if v},
                  # eq(債務超過判定)が測れなかったときは空欄の理由を残す（ルール8。詳細は notes）
                  "nulls": ({} if ev.get("eqSign") is not None
                            else {"eq": "自己資本の符号を機械で確定できず空欄——posと断定しない（notes参照）"}),
                  "todo_原本": ["expiry(限)","moatdecay/erosion/disrupt(蝕)","dom/irr/rep/dur(堀四性質)","geopol(集)","nrr"],
                  "todo_市場": ["beta","per","perF","evebit","px","shy"],
                  "todo_書記": ["p1-p4","f1-f5","fin業態","analysts/instOwn/gls/idx/indG/founder"]}}
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{ticker}_gate_input.json", "w", encoding="utf-8") as f: json.dump(draft, f, ensure_ascii=False, indent=1)
    with open(f"{OUT}/{ticker}_hits.txt", "w", encoding="utf-8") as f: f.write(f"{ticker} {form} {rdate}\n{url}\n"+rep)
    print(f"  → {OUT}/{ticker}_gate_input.json / {ticker}_hits.txt")

def load_queue():
    """門0の待ち行列を読み、未処理の上位BATCH件を返す(門0の並び順=審査優先→pt降順・excluded除外)"""
    import glob
    path = next((q for q in QUEUE_PATHS if os.path.exists(q)), None)
    if not path:
        g = glob.glob("/content/drive/MyDrive/**/gate1_queue.json", recursive=True)
        path = g[0] if g else None
    if not path:
        print("待ち行列(gate1_queue.json)が見つからない——TICKERSに手動指定して実行"); return []
    rows = json.load(open(path, encoding="utf-8"))
    rows = [r for r in rows if not r.get("excluded")]
    # v3.1(2026-07-17): pt再ソートを廃止。門0 v8.5の並び順そのものが採取順
    # (先頭=審査優先〔谷/種まき/未成熟〕=数字で裁けない群、以降pt降順)。並び替えると優先設計が壊れる。
    todo = []
    for r in rows:
        t = r["ticker"]
        if t in SKIP or os.path.exists(f"{OUT}/{t}_gate_input.json"):
            continue  # 審査済み・採取済みはスキップ
        todo.append(t)
        if len(todo) >= BATCH: break
    print(f"待ち行列: {path}\n今回の被告(審査優先→pt順・未処理): {todo}")
    return todo

if __name__ == "__main__":
    if EMAIL.startswith("your-"):
        print("★ファイル冒頭のEMAILを書き換えてから実行"); sys.exit(0)
    # コマンドライン引数があれば使う(Colabの -f 等の疑似引数は無視)、無ければTICKERSを使う
    args = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,7}", a)]
    targets = args or TICKERS or load_queue()
    ok, ng = [], []
    for t in targets:
        try:
            run(t)
            ok.append(t)
        except Exception as e:
            print(f"{t}: 失敗 → {e}")
            ng.append(t)
    # ⚠2026-08-17新設: **実行印**。回転盤(night/ops_status.py)は錨ファイルの日付で
    #   「回っているか」を測るが、この採取器の出力は out/{T}_gate_input.json という
    #   **銘柄ごとのファイル**で、盤が見る単一の錨が無かった＝**止まっても誰も気づけない**。
    #   run_gate0_local.py の実行印(out/gate0_run.json)と同じ作法で1本残す。
    #   ⚠ 成功と失敗を分けて数える——「走った」と「全部採れた」を混ぜない（ルール7）。
    try:
        import datetime as _dt, json as _json, glob as _g, os as _os
        _stock = [_os.path.basename(f).split('_gate_input')[0]
                  for f in _g.glob(_os.path.join(OUT, '*_gate_input.json'))]
        _done = {_os.path.basename(f).split('_gate_pack')[0]
                 for f in _g.glob(_os.path.join(OUT, '*_gate_pack.json'))}
        _json.dump({'generated': _dt.date.today().isoformat(),
                    'n_ok': len(ok), 'n_fail': len(ng), 'ok': ok, 'fail': ng,
                    'stock_unreviewed': len([t for t in _stock if t not in _done]),
                    'note': '機械値の下ごしらえ(hachimon_fetch)の実行印。'
                            'stock_unreviewed=採取ずみで未審査の在庫＝門2審査の何日分あるか'},
                   open(_os.path.join(OUT, 'fetch_run.json'), 'w', encoding='utf-8'),
                   ensure_ascii=False, indent=1)
        print('■ 実行印: out/fetch_run.json')
    except Exception as _e:
        print(f'▲ 実行印を書けなかった: {_e}')
