#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate_fetch v3.0 — SEC一撃採取器（壊れない複利の門 v9.6・Ⅱ採点機JSON下書き生成）
使い方:  python hachimon_fetch.py MSFT ASML ANET
出力:    ./hachimon_out/{TICKER}_gate_input.json … 門のⅡ採点機に貼れるJSON下書き(SEC客観値を充填)
         ./out/{TICKER}_hits.txt             … 定性4問(限集誠蝕)+facts用のキーワードヒット報告(2-3KB)
注意:    EMAIL を自分のものに書き換えること(SECはUser-Agent必須・10req/s制限)。
         px(株価)とbetaはSECに無いので空欄のまま——取込時に手入力かツール側で補完。
"""
import json, re, sys, time, urllib.request, os
from statistics import median

EMAIL   = "fortis5280@gmail.com"        # ★1. 自分のメールに書き換える(SECの必須マナー)
TICKERS = []                              # ★2. 空のまま=門0の待ち行列(gate1_queue.json)から自動で未処理上位を採取
                                          #     手動指定したい時だけ ["MSFT","ANET"] のように書く
BATCH   = 5                               # 自動モードで1回に処理する銘柄数
SKIP    = ["LLY","MSFT","ASML"]           # 審査済み・採取不要の銘柄(判決が出たら追記)
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
 "intan": ["FiniteLivedIntangibleAssetsNet","IntangibleAssetsNetExcludingGoodwill"],
 "cash":  ["CashAndCashEquivalentsAtCarryingValue","CashAndCashEquivalents"],
 "sti":   ["ShortTermInvestments","MarketableSecuritiesCurrent"],
 "debtL": ["LongTermDebtNoncurrent","LongTermDebt","NoncurrentBorrowings","Borrowings"],
 "debtS": ["LongTermDebtCurrent","DebtCurrent","CurrentBorrowings","ShortTermBorrowings"],
 "sh":    ["CommonStockSharesOutstanding","EntityCommonStockSharesOutstanding","NumberOfSharesOutstanding"],
 "impair":["GoodwillImpairmentLoss","ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill"],
}
def series(facts, keys, unit_pref=("USD","EUR","JPY")):
    for ns in ("us-gaap","ifrs-full","dei"):
        d = facts.get("facts",{}).get(ns,{})
        for k in keys:
            if k in d:
                units = d[k]["units"]
                ordered = sorted(units.keys(), key=lambda u: -len(units[u]))  # 最多データの単位を優先
                for u in ordered:
                    if True:
                        # FY(年次)のみ、frame重複は末尾優先で年次dict化
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
    return {}, None

def last_n(d, n=6):
    ys = sorted(d)[-n:]
    return ys, [d[y] for y in ys]

def _safe(ev, note, key, fn):
    try:
        v = fn()
        if v is not None: ev[key] = v
    except Exception as e:
        note.append(f"{key}: 計算失敗({type(e).__name__})")

def build_numbers(facts):
    S, diag = {}, {}
    for k, v in TAGS.items():
        S[k] = series(facts, v)[0]
        diag[k] = f"{len(S[k])}年分" if S[k] else "タグ不発見"
    ev, note = {}, []
    ys_rev, rev = last_n(S["rev"])
    if len(rev) >= 2:
        _safe(ev, note, "cagr5", lambda: (lambda yrs: round(((rev[-1]/rev[-1-yrs])**(1/yrs)-1)*100,1) if rev[-1-yrs] else None)(min(5,len(rev)-1)))
    # 粗利トレンド
    if S["gp"]:
        ys,gp = last_n(S["gp"])
        gm = {y: S["gp"][y]/S["rev"][y]*100 for y in ys if S["rev"].get(y)}
        yy = sorted(gm)[-2:]
        if len(yy)==2:
            _safe(ev, note, "gmDelta", lambda: round(gm[yy[1]]-gm[yy[0]],1))
    # accr / conv (直近年)
    y0 = max(S["ni"]) if S["ni"] else None
    if y0 and y0 in S["ocf"] and S["assets"].get(y0):
        _safe(ev, note, "accr", lambda: round((S["ni"][y0]-S["ocf"][y0])/S["assets"][y0]*100, 1))
    if y0 and y0 in S["ocf"] and y0 in S["capex"] and S["ni"].get(y0):
        fcf = S["ocf"][y0]-abs(S["capex"][y0])
        _safe(ev, note, "conv", lambda: round(fcf/S["ni"][y0]*100,1))
        sh,_ = series(facts, TAGS["sh"], ("shares",))
        if sh:
            shl = sh.get(y0) or list(sh.values())[-1]
            _safe(ev, note, "fcfps", lambda: round(fcf/shl,2) if shl else None)
    # nde
    if y0:
        debt = (S["debtL"].get(y0,0) or 0)+(S["debtS"].get(y0,0) or 0)
        cash = (S["cash"].get(y0,0) or 0)+(S["sti"].get(y0,0) or 0)
        ebitda = (S["op"].get(y0,0) or 0)+(S["dep"].get(y0,0) or 0)
        if ebitda: ev["nde"] = round((debt-cash)/ebitda, 2)
    # のれん除外ROIC 5年系列 → worst/median
    roics = []
    for y in sorted(S["op"])[-5:]:
        if all(y in S[k] for k in ("ni","eq")) and y in S["op"]:
            tax_rate = 1 - S["ni"][y]/max(S["ni"][y]+S["tax"].get(y,0), 1)
            nopat = S["op"][y]*(1-max(0,min(0.5,tax_rate)))
            debt = (S["debtL"].get(y,0) or 0)+(S["debtS"].get(y,0) or 0)
            ic = S["eq"][y]+debt-(S["gw"].get(y,0) or 0)-(S["intan"].get(y,0) or 0)
            if ic>0: roics.append(nopat/ic*100)
    if roics:
        ev["roicExW5"]  = round(min(roics),1)
        ev["roicExMed5"]= round(median(roics),1)
    # 純希薄化率(株数の年率変化)
    sh,_ = series(facts, TAGS["sh"], ("shares",))
    if len(sh)>=3:
        ys = sorted(sh)[-4:]
        d0,d1 = sh[ys[0]], sh[ys[-1]]
        _safe(ev, note, "dilNet", lambda: round(((d1/d0)**(1/(len(ys)-1))-1)*100,2) if d0 else None)
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
    # 営業利益率トレンド gmt (3年: up/flat/down)
    if S["op"] and S["rev"]:
        oy = sorted(set(S["op"])&set(S["rev"]))[-3:]
        if len(oy)>=2 and S["rev"].get(oy[0]) and S["rev"].get(oy[-1]):
            m0=S["op"][oy[0]]/S["rev"][oy[0]]*100; m1=S["op"][oy[-1]]/S["rev"][oy[-1]]*100
            ev["gmt"]="up" if m1-m0>1 else "down" if m1-m0<-1 else "flat"
    # のれん込みROIC roicg (直近年・のれん除外しない版)
    if y0 and all(y0 in S[k] for k in ("op","ni","eq")):
        _safe(ev,note,"roicg",lambda:(lambda tax:round(S["op"][y0]*(1-max(0,min(0.5,tax)))/max(S["eq"][y0]+((S["debtL"].get(y0,0)or 0)+(S["debtS"].get(y0,0)or 0)),1)*100,1))(1-S["ni"][y0]/max(S["ni"][y0]+S["tax"].get(y0,0),1)))
    # のれん除外ROIC 直近年 roic (門のroic欄=単年・除外)
    if roics: ev["roic"]=round(roics[-1],1)
    # ROICトレンド roict (5年 up/flat/down): worst年 vs 直近
    if len(roics)>=2:
        ev["roict"]="up" if roics[-1]-roics[0]>2 else "down" if roics[-1]-roics[0]<-2 else "flat"
    # GP/A(gpa) 直近年
    if y0 and y0 in S["gp"] and S["assets"].get(y0):
        _safe(ev,note,"gpa",lambda:round(S["gp"][y0]/S["assets"][y0]*100,1))
    # fcf/ni の生値(門はfcf・niを直接欄に持つ。単位は_unit/1e9でB表示)
    if y0 and y0 in S["ocf"] and y0 in S["capex"]:
        u=1e9
        ev["fcf_abs"]=round((S["ocf"][y0]-abs(S["capex"][y0]))/u,2)
        if S["ni"].get(y0) is not None: ev["ni_abs"]=round(S["ni"][y0]/u,2)
    # eps(TTM近似=直近NI/株数)
    sh2,_=series(facts,TAGS["sh"],("shares",))
    if y0 and sh2 and (sh2.get(y0) or 0):
        _safe(ev,note,"eps",lambda:round(S["ni"][y0]/sh2[y0],2))
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
