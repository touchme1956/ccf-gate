#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate_fetch v3.0 — SEC一撃採取器（壊れない複利の門 v9.6・Ⅲ採点機JSON下書き生成）
使い方:  python hachimon_fetch.py MSFT ASML ANET
出力:    ./out/{TICKER}_gate_input.json … 門のⅢ採点機に貼れるJSON下書き(SEC客観値を充填。Colab/Drive時はhachimon_out/)
         ./out/{TICKER}_hits.txt        … 定性6砲台(限/集/誠/蝕/堀/循)+facts用のキーワードヒット報告(2-3KB)
注意:    EMAIL を自分のものに書き換えること(SECはUser-Agent必須・10req/s制限)。
         px(株価)とbetaはSECに無いので空欄のまま——取込時に手入力かツール側で補完。
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
 "rev":   ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueNet","Revenue"],
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
 #   ※フォールバック時は無期限無形(商標・ブランド等)が控除されず依然として過少になるため、
 #     ROIC算出側の「ICが自己資本の2割未満なら飛ばす」ガードで受ける。
 "intan": ["IntangibleAssetsNetExcludingGoodwill","FiniteLivedIntangibleAssetsNet"],
 "cash":  ["CashAndCashEquivalentsAtCarryingValue","CashAndCashEquivalents"],
 "sti":   ["ShortTermInvestments","MarketableSecuritiesCurrent"],
 # 2026-07-29: 実測で取りこぼしが3件出たのでタグを拡張した（絶対のルール7「欠測をゼロと読むな」）。
 #   IDXX: リボルビング枠 LinesOfCreditCurrent 398,000千$ を数え落とし → roic 71.1→56.4
 #   CHKP: 転換社債 ConvertibleNotesPayable 1,972.1百万$ を丸ごと取りこぼし → IC 892→2,736百万$
 #   DXC : FY2026で LongTermDebtNoncurrent が消え LongTermDebtAndCapitalLeaseObligations へ移行
 #         → 負債3,552百万$が丸ごと欠落。**タグ名は年次で移行する**ので同義タグを並べて拾う
 #   なお「タグが1つも当たらない年は算出不能として飛ばす」ガードは下のROIC算出側にある。
 #   タグを増やすのは、飛ばす前にまず拾えるようにするため（飛ばすのは最後の手段）。
 "debtL": ["LongTermDebtNoncurrent","LongTermDebt","LongTermDebtAndCapitalLeaseObligations",
           "DebtAndCapitalLeaseObligations","LongTermNotesPayable","ConvertibleLongTermNotesPayable",
           "NoncurrentBorrowings","Borrowings"],
 "debtS": ["LongTermDebtCurrent","DebtCurrent","LinesOfCreditCurrent","CommercialPaper",
           "ConvertibleNotesPayableCurrent","ConvertibleNotesPayable","NotesPayableCurrent",
           "CurrentBorrowings","ShortTermBorrowings"],
 "sh":    ["CommonStockSharesOutstanding","EntityCommonStockSharesOutstanding","NumberOfSharesOutstanding"],
 "impair":["GoodwillImpairmentLoss","ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill"],
}
def _annual(units):
    """単位ごとのXBRL行から年次dictを組む。最多データの単位を優先。"""
    for u in sorted(units.keys(), key=lambda x: -len(units[x])):
        out = {}
        for row in units[u]:
            if not row.get("form","").startswith(("10-K","20-F")): continue
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


def series_sum(facts, keys, total_key=None):
    """**足し合わせるべきタグ**を合計する。series() は候補から1本を選ぶので有利子負債には使えない。

    2026-07-29修正: debtS は LongTermDebtCurrent / LinesOfCreditCurrent / CommercialPaper …
      と**同時に存在しうる別の科目**なのに、series() が優先順で1本だけ選んでいた。
      実測 IDXX: LongTermDebtCurrent が選ばれ、リボルビング枠 LinesOfCreditCurrent 398,000千$ が
      丸ごと落ちて roic 71.1（真値56.4）。**タグを候補リストに足しても、選ぶ実装のままでは拾えない**
      ——2026-07-29 に debtS のタグを9個へ拡張したのに IDXX が直らなかったのはこれが理由で、
      審査官が手で直していた。「候補＝代替」と「候補＝構成要素」を取り違えていた。

    total_key があり、その年に総額タグが存在するなら**合計せず総額を採る**（二重計上を避ける）。
    """
    per = {}
    for k in keys:
        for ns in ("us-gaap", "ifrs-full"):
            d = facts.get("facts", {}).get(ns, {})
            if k not in d:
                continue
            out, _u = _annual(d[k]["units"])
            if out:
                per[k] = out
            break
    years = set().union(*[set(v) for v in per.values()]) if per else set()
    out, used = {}, {}
    for y in years:
        if total_key and total_key in per and y in per[total_key]:
            out[y] = per[total_key][y]
            used[y] = [f"{total_key}(総額)"]
            continue
        parts = [(k, per[k][y]) for k in keys if k != total_key and k in per and y in per[k]]
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
    S["debtS"], _usedS = series_sum(facts, TAGS["debtS"], total_key="DebtCurrent")
    S["debtL"], _usedL = series_sum(facts, TAGS["debtL"], total_key="LongTermDebt")
    for k in ("debtS", "debtL"):
        diag[k] = f"{len(S[k])}年分(合計)" if S[k] else "タグ不発見"
    ev, note = {}, []
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
            shl = sh.get(y0) or list(sh.values())[-1]
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
        ebitda = (S["op"].get(y0,0) or 0)+(S["dep"].get(y0,0) or 0)
        if not has_debt:
            note.append(f"nde算出不能: {y0}年に有利子負債タグが無い。無借金なら nde=−{_u(cash)}/EBITDA "
                        f"だが、タグ不在と無借金は機械で区別できない。原本のBSで確認して手入力せよ")
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
            tax_rate = 1 - S["ni"][y]/max(S["ni"][y]+S["tax"].get(y,0), 1)
            nopat = S["op"][y]*(1-max(0,min(0.5,tax_rate)))
            # 2026-07-29修正: 有利子負債タグが「その年に存在しない」場合、従来は debt=0 と見なして
            #   IC = 自己資本 − のれん − 無形 になっていた。買収で伸びた会社は自己資本の大半が
            #   のれん＋無形なので**分母が0へ縮退してROICが発散する**。実測: NJR roic=16.5(真値6.6・
            #   負債3.6十億$が丸ごと欠落) / HEI 93.0 / APH 163.4。日本株で廃止した旧・門式
            #   (投下資本−過剰現金)と同型のアーティファクトで、原因は「欠測をゼロと読む」こと。
            #   **タグが無い年は算出不能として飛ばす**（誤値より空欄）。
            has_debt = (y in S["debtL"]) or (y in S["debtS"])
            if not has_debt:
                roic_skip.append(f"{y}:有利子負債タグ不在でIC算出不能")
                continue
            debt = (S["debtL"].get(y,0) or 0)+(S["debtS"].get(y,0) or 0)
            gw, intan = (S["gw"].get(y,0) or 0), (S["intan"].get(y,0) or 0)
            ic = S["eq"][y]+debt-gw-intan
            # 分母が自己資本の2割を切ったら、のれん・無形の控除でICが縮退している＝発散の前兆。
            #   この帯のROICは「資本が軽い」の言い換えで識別力が無く、桁違いの偽陽性だけを生む。
            if ic <= 0 or ic < 0.20*max(S["eq"][y], 1):
                roic_skip.append(f"{y}:IC={ic:.0f}が自己資本{S['eq'][y]:.0f}の2割未満＝のれん控除で分母縮退")
                continue
            roics.append(nopat/ic*100)
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
    if roics:
        ev["roicExW5"]  = round(min(roics),1)
        ev["roicExMed5"]= round(median(roics),1)
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
    if S["impair"] and any(v>0 for v in list(S["impair"].values())[-5:]):
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
    if y0 and all(y0 in S[k] for k in ("op","ni","eq")):
        _safe(ev,note,"roicg",lambda:(lambda tax:round(S["op"][y0]*(1-max(0,min(0.5,tax)))/max(S["eq"][y0]+((S["debtL"].get(y0,0)or 0)+(S["debtS"].get(y0,0)or 0)),1)*100,1))(1-S["ni"][y0]/max(S["ni"][y0]+S["tax"].get(y0,0),1)))
        if ev.get("roicg") is not None:
            _d = (S["debtL"].get(y0,0) or 0)+(S["debtS"].get(y0,0) or 0)
            evd["roicg"] = (f"機械算出 {y0}年: NOPAT ÷ (自己資本 {_u(S['eq'][y0])} + 有利子負債 {_u(_d)})"
                            f"＝のれん込み。roic(除外)との差が買収規律の指標"
                            + ("" if ((y0 in S['debtL']) or (y0 in S['debtS']))
                               else "。**有利子負債タグ不在＝0扱いのため過大の可能性あり（要原本確認）**"))
    # のれん除外ROIC 直近年 roic (門のroic欄=単年・除外)
    # 5年系列そのものは古い年を含んでよい（それが系列の意味）。検問するのは**直近値の年**だけ——
    # 古い年の値を"直近ROIC"として台帳に載せないため。
    if roics and not stale(max(S["op"]) if S["op"] else None):
        ev["roic"]=round(roics[-1],1)
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
        tr = 1 - S["ni"][y]/max(S["ni"][y]+S["tax"].get(y,0), 1)
        np_ = S["op"][y]*(1-max(0,min(0.5,tr)))
        icg = S["eq"][y] + (S["debtL"].get(y,0) or 0) + (S["debtS"].get(y,0) or 0)
        return (np_, icg) if icg > 0 else None

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
    if len(roics)>=2:
        ev["roict"]="up" if roics[-1]-roics[0]>2 else "down" if roics[-1]-roics[0]<-2 else "flat"
        evd["roict"] = (f"機械算出: のれん除外ROIC 5年系列 "
                        f"{' / '.join(f'{x:.1f}%' for x in roics)}（最古→直近の差で判定）")
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
        if f in ("10-K","20-F"):
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
        "eq": "neg" if (ev.get("roicg") is not None and False) else "pos",  # 債務超過は稀・原本確認、既定pos
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
                  "nulls": {},
                  "todo_原本": ["expiry(限)","moatdecay/erosion/disrupt(蝕)","dom/irr/rep/dur(堀四性質)","geopol(集)","nrr"],
                  "todo_市場": ["beta","per","perF","evebit","px","shy"],
                  "todo_書記": ["p1-p4","f1-f5","fin業態","analysts/instOwn/gls/idx/indG/founder"]}}
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{ticker}_gate_input.json","w") as f: json.dump(draft, f, ensure_ascii=False, indent=1)
    with open(f"{OUT}/{ticker}_hits.txt","w") as f: f.write(f"{ticker} {form} {rdate}\n{url}\n"+rep)
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
