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
import json, re, sys, time, urllib.request, os
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

# ---------- XBRL: 年次系列の取り出し ----------
def facts_of(cik):
    return json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))

TAGS = {  # us-gaap優先、ifrs-fullへフォールバック
 "rev":   ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","RevenueFromContractWithCustomerIncludingAssessedTax","SalesRevenueNet","Revenue"],
 "gp":    ["GrossProfit"],
 "op":    ["OperatingIncomeLoss","ProfitLossFromOperatingActivities"],
 "ni":    ["NetIncomeLoss","ProfitLoss"],
 "tax":   ["IncomeTaxExpenseBenefit","IncomeTaxExpenseContinuingOperations"],
 "ocf":   ["NetCashProvidedByUsedInOperatingActivities","CashFlowsFromUsedInOperatingActivities"],
 "capex": ["PaymentsToAcquirePropertyPlantAndEquipment","PurchaseOfPropertyPlantAndEquipment"],
 "dep":   ["DepreciationDepletionAndAmortization","DepreciationAndAmortization","DepreciationAmortisationAndImpairmentLoss"],
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
 "cash":  ["CashAndCashEquivalentsAtCarryingValue","CashAndCashEquivalents"],
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
def _annual(units):
    """単位ごとのXBRL行から年次dictを組む。最多データの単位を優先。"""
    for u in sorted(units.keys(), key=lambda x: -len(units[x])):
        out = {}
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
            if s and e:  # 損益・CF系は期間300日超のみ(四半期を排除)
                try:
                    from datetime import date
                    d0 = date.fromisoformat(s); d1 = date.fromisoformat(e)
                    if (d1 - d0).days < 300: continue
                except Exception: pass
            out[fy] = row["val"]
        if out: return out, u
    return None, None


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
    """
    cands = []
    for ns in ("us-gaap","ifrs-full","dei"):
        d = facts.get("facts",{}).get(ns,{})
        for i, k in enumerate(keys):
            if k not in d: continue
            out, u = _annual(d[k]["units"])
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
    i, k0, merged, unit = min(elig, key=lambda c: (c[0], -max(c[2])))
    merged = dict(merged)
    for _, k, out, u in cands:
        if k == k0 or u != unit: continue
        ov = set(out) & set(merged)
        if not ov: continue                        # 重なり無し＝同一指標と確かめられない
        if any(merged[y] and abs(out[y]-merged[y])/abs(merged[y]) > 0.02 for y in ov):
            continue                               # 重なる年で食い違う＝別の指標
        for y, v in out.items():
            merged.setdefault(y, v)
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


def debt_evidence(facts, year, span=2):
    """有利子負債の**痕跡**を候補タグの外まで独立に走査する（2026-08-03新設）。

    なぜ要るか: 「候補タグに当たらない」だけでは
      (a) 本当に無借金  と  (b) 我々が知らないタグで報告している  を区別できない。
    (b)を(a)と誤れば NJR/HEI/APH の事故（debt=0でICが縮退しROICが発散）を再発させ、
    (a)を(b)と誤れば IRMD のように**無借金の優良企業のROICが永久に算出不能**になる。
    どちらも「確かめていない前提」なので、上限の不等式で決着させる——
    対象年から span 年以内に債務らしき残高が**一つも無い**なら、債務ゼロは事実。

    返り値: 生きた痕跡の "タグ名(年)=値" のリスト（空なら痕跡ゼロ＝無借金と断定してよい）
    """
    out = []
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        for k in d:
            if not DEBT_EVI.search(k) or DEBT_NOT.search(k):
                continue
            for arr in d[k]["units"].values():
                for x in arr:
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


def series_sum(facts, keys, total_key=None):
    """**足し合わせるべきタグ**を合計する。series() は候補から1本を選ぶので有利子負債には使えない。

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
    """
    if isinstance(total_key, str):
        total_keys = [total_key]
    else:
        total_keys = list(total_key or [])
    per, unit_of = {}, {}
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        found = False
        for k in keys:
            if k not in d:
                continue
            out, u = _annual(d[k]["units"])
            if out:
                per[k] = out
                unit_of[k] = u
                found = True
        if found:
            break                        # 名前空間はまたがない（series()と同じ）
    if not per:
        return {}, {}
    # 単位の一致検問: 最多の単位を主単位とし、違う単位のタグは合算しない（足すと桁が壊れる）
    _cnt = {}
    for u in unit_of.values():
        _cnt[u] = _cnt.get(u, 0) + 1
    main_u = max(_cnt, key=lambda u: _cnt[u])
    for k in [k for k in per if unit_of[k] != main_u]:
        del per[k]
    years = set().union(*[set(v) for v in per.values()]) if per else set()
    out, used = {}, {}
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


def build_numbers(facts):
    S, diag = {}, {}
    for k, v in TAGS.items():
        S[k] = series(facts, v)[0]
        diag[k] = f"{len(S[k])}年分" if S[k] else "タグ不発見"
    # 有利子負債だけは「代替」でなく「構成要素」なので合計する（上の series は上書き）
    # 2026-08-04是正(A7): debtL の総額は LongTermDebt(us-gaap) と Borrowings(IFRS・流動込み総額の
    #   ことが多い) の2本。Borrowings を構成要素扱いすると内数 LongtermBorrowings と二重計上する
    #   （実測 WIT で約64B INR。詳細は series_sum の頭注）
    S["debtS"], _usedS = series_sum(facts, TAGS["debtS"], total_key="DebtCurrent")
    S["debtL"], _usedL = series_sum(facts, TAGS["debtL"], total_key=("LongTermDebt", "Borrowings"))
    # 2026-08-03: 無形も同じく「構成要素」だった（TAGS["intan"]の頭注を見よ）。総額タグがその年に
    #   あれば総額、無ければ 確定分＋無期限分 を足す＝series_sum の total_key がそのまま使える。
    #   実測 CELH: 総額タグが2024年で終わり、2025年は二本に割れていたので series() では欠測になった。
    S["intan"], _usedI = series_sum(facts, TAGS["intan"],
                                    total_key="IntangibleAssetsNetExcludingGoodwill")
    # IFRS勢は のれん を単独で出さず `IntangibleAssetsAndGoodwill`(のれん**込み**の合算)だけを
    #   出す社がある（実測TSM: Goodwillタグ自体が存在しない）。sum候補に入れると `Goodwill` や
    #   `IntangibleAssetsOtherThanGoodwill` を併せ持つ社で**二重に引く**ので、
    #   **他の無形も のれん も取れない年に限って**合算値を無形として使う（gw=0 なので過不足なし）。
    _iag = series(facts, ["IntangibleAssetsAndGoodwill"])[0]
    if _iag:
        for _y, _v in _iag.items():
            if _y not in S["intan"] and _y not in S["gw"]:
                S["intan"][_y] = _v
    for k in ("debtS", "debtL", "intan"):
        diag[k] = f"{len(S[k])}年分(合計)" if S[k] else "タグ不発見"
    ev, note = {}, []
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
    if _dbl:
        note.append(f"有利子負債の二重計上の疑い（{_dbl[-1]}年ほか{len(_dbl)}年）: LongTermDebt を"
                    f"1年内返済分込みで報告する会社では LongTermDebtCurrent を足すと重複する。"
                    f"原本のBSで総額を確認せよ。重複していれば IC が過大＝ROICは**過小**に出ている")
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
        if len(yy)==2:
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
        cash = (S["cash"].get(y0,0) or 0)+(S["sti"].get(y0,0) or 0)
        # 2026-07-29追加修正: EBITDAの営業利益も「タグが無い年を0」と読んでいた。
        #   実測 KLAC: OperatingIncomeLoss が2014年で途切れており（同社は売上−原価−R&D−販管費で
        #   開示）、EBITDA が減価償却394百万$だけになって **nde=9.66**（原本からの検算では約0.2-0.5）。
        #   roic側は既に年検問で落としていたが、ndeだけ素通りしていた＝同じ穴の取り残し。
        if y0 not in S["op"]:
            note.append(f"nde算出不能: {y0}年に営業利益タグが無い（EBITDAが減価償却だけになり過大に出る）。"
                        f"原本の損益計算書から営業利益を確認して手入力せよ")
            ebitda = 0
        else:
            ebitda = S["op"][y0] + (S["dep"].get(y0,0) or 0)
        # 2026-08-03: 「タグ不在と無借金は機械で区別できない」——**区別できるようになった**ので
        #   debt_evidence() で裁く（ROIC側と同じ判定を使う＝同じ台帳に二つの基準を作らない）。
        #   痕跡ゼロなら債務ゼロは事実で、ネットキャッシュの会社の nde が空欄のままになるのを止める。
        if not has_debt and not (S["debtL"] or S["debtS"]) and not debt_evidence(facts, y0) and ebitda:
            ev["nde"] = round((0-cash)/ebitda, 2)
            evd["nde"] = (f"機械算出 {y0}年: (有利子負債 0 − 現金同等物 {_u(cash)})"
                          f" ÷ (営業利益 {_u(S['op'].get(y0,0) or 0)} + 減価償却 {_u(S['dep'].get(y0,0) or 0)})。"
                          f"**有利子負債は候補タグ・独立走査とも痕跡ゼロ＝実質無借金**（欠測を0と読んだのではない）")
        elif not has_debt:
            note.append(f"nde算出不能: {y0}年に有利子負債タグが無い。無借金なら nde=−{_u(cash)}/EBITDA "
                        f"だが、他年に報告があるか未知のタグに痕跡があるため断定できない。原本のBSで確認して手入力せよ")
        elif ebitda:
            debt = (S["debtL"].get(y0,0) or 0)+(S["debtS"].get(y0,0) or 0)
            ev["nde"] = round((debt-cash)/ebitda, 2)
            evd["nde"] = (f"機械算出 {y0}年: (有利子負債 {_u(debt)} − 現金同等物 {_u(cash)})"
                          f" ÷ (営業利益 {_u(S['op'].get(y0,0) or 0)} + 減価償却 {_u(S['dep'].get(y0,0) or 0)})")
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
                if S["debtL"] or S["debtS"]:
                    # 2026-08-03: 他年に報告があっても、**その額が自己資本比で無視できるなら**
                    #   欠測年を0と読んでよい（上限の不等式）。実測 EXPD は短期銀行借入を
                    #   有る年だけ報告し最大でも自己資本の約1.5%＝ROICを動かせない。
                    #   従来はこの型で5年系列が1年も作れなかった。
                    _mx = max([(S["debtL"].get(_y,0) or 0)+(S["debtS"].get(_y,0) or 0)
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
                    _m = ("有利子負債タグが全年で不発見、かつ独立走査でも債務の痕跡ゼロ＝"
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
            if ic <= 0 or (_base > 0 and ic < 0.20*_base):
                roic_skip.append(f"{y}:IC={ic:.0f}が{_what}{_base:.0f}の2割未満＝のれん控除で分母縮退"
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
                           f" − 無形 {_u(intan)}。**IC/自己資本={ic/max(S['eq'][y],1)*100:.1f}%**"
                           f"（2割未満なら分母縮退＝算出不能。絶対のルール7(b)）"
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
    # 2026-08-03: **3年未満の「中央値」は through-cycle ではない。** 従来は `if roics:` で
    #   1-2年でも med5/w5 を出していたため、在庫を数えると220社に見えたが実体は179社だった
    #   （1点の中央値はその点そのもの）。3年以上のときだけ出す。
    if len(roics) >= 3:
        ev["roicExW5"]  = round(min(_rSeq),1)
        ev["roicExMed5"]= round(median(_rSeq),1)
        ev["roicgW5"]   = round(min(_gSeq),1)
        ev["roicgMed5"] = round(median(_gSeq),1)
        ev["_tcYears"]  = len(_rSeq)
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
    if S["impair"] and any(S["impair"][y] > 0 for y in sorted(S["impair"])[-5:]):
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
            if _icg0 <= 0 or (_b0 > 0 and _icg0 < 0.20*_b0):
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
                               else "。**有利子負債タグ不在＝0扱いのため過大の可能性あり（要原本確認）**"))
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
    if roics and not stale(max(S["op"]) if S["op"] else None):
        ev["roic"]=round(median(_rSeq),1)
        if _gSeq: ev["roicg"]=round(median(_gSeq),1)
        evd["roic"]=(evd.get("roic","")+f"｜**v9.9.72: through-cycle 化**。5年系列 {len(_rSeq)}年の"
                     f"**中央値 {median(_rSeq):.1f}%** を採用（直近年 {_rSeq[-1]:.1f}% / 最悪 {min(_rSeq):.1f}%）。"
                     f"roicg も同じ年の系列の中央値 {median(_gSeq):.1f}% にして roic≥roicg を保つ")
    elif roics:
        note.append(f"roic算出不能: 営業利益系列が{max(S['op'])}年で途切れ最新{LATEST}年から遅れている"
                    f"（タグ改称の疑い）。原本で確認して手入力せよ")
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
    if len(_rSeq)>=2:
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
    for t in targets:
        try:
            run(t)
        except Exception as e:
            print(f"{t}: 失敗 → {e}")
