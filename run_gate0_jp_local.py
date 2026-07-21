# =====================================================================
# CCF Ω 第一の門・日本株漏斗 gate0_jp v2（校正モード）— ローカル移植版
#
#   EDINET全上場企業 → 二段漏斗 → 待ち行列TOP50 ＋ 敗者復活の椅子(現金型)
#
# 【設計】SEC版(gate0_v8)の思想を移植。落とすだけ・裁量ゼロ。
#   ・Stage1: 最新の有価証券報告書1冊(主要指標5年サマリー+当期財務諸表)で
#     「絶対に通らない企業」だけを安全に切る(偽陰性ゼロの条件のみ使用)
#   ・Stage2: 生き残りのみ過去の有報を追加取得し、5年フルで7項目採点
#   ・税率は日本の実効税率 ×0.70(SEC版は×0.79)
#   ・椅子: ROIC系のみで落ちた5点企業を現金控除ROICで再評価(キーエンス型)
# 【v1は校正モード】golden銘柄の抽出値を印字して目視確認する。
#   期待値の固定(回帰テスト化)はv2で行う。
#
# 【移植版の変更点(Drive/ccf/gate0_jp_v2.py → このリポジトリ)】
#   ・Colabマウント除去。SAVE_DIR=リポジトリ直下、キャッシュ=./edinet_csv
#   ・非対話化: input()を廃止——edinet_key.txt が無い/401なら明示して停止
#   ・選別ロジック・閾値・要素名候補は原本のまま変更なし
# 前提: リポジトリ直下に edinet_key.txt(APIキー1行・.gitignore済)。
# 初回所要: 索引 約45-60分 + Stage1 約2時間 + Stage2 約30分 ≒ 3時間前後
#   キャッシュ済みなら数分〜。中断しても再実行で続きから。
# =====================================================================
import json, time, csv, io, os, re, urllib.request, urllib.parse, zipfile, collections, datetime

YEARS = 5
MIN_SALES_CAGR, MIN_ROIC_LATEST, MIN_ROIC_WORST = 0.05, 0.15, 0.10
MIN_OPM, MIN_FCF_CONV = 0.15, 0.70
TAX = 0.70                      # 日本の実効税率控除
TOP_N_JP = 50
SEND_TO_GATE1 = 6
RESCUE_MIN_OPM, RESCUE_MIN_CAGR = 0.15, 0.08
RESCUE_FAILS = {"ROIC", "ROIC最低値"}
STALE_DAYS = 550
INDEX_YEARS = 6                 # 書類索引を遡る年数

GOLDEN_JP = {"6861":"キーエンス","4063":"信越化学","6273":"SMC","8035":"東京エレクトロン",
             "7716":"ナカニシ","6920":"レーザーテック","4684":"オービック"}
EXCLUDE_GYOSHU = {"銀行業","保険業","証券、商品先物取引業","その他金融業","鉱業","石油・石炭製品","海運業"}

SAVE_DIR = os.path.dirname(os.path.abspath(__file__)) or "."
CACHE = f"{SAVE_DIR}/edinet_csv"; os.makedirs(CACHE, exist_ok=True)
print(f"■ 保存先: {SAVE_DIR}")

# ---------- APIキー ----------
KEY_PATH = f"{SAVE_DIR}/edinet_key.txt"
if os.path.exists(KEY_PATH):
    API_KEY = open(KEY_PATH).read().strip()
else:
    raise SystemExit("edinet_key.txt が無い。EDINET APIキーを1行書いて置くこと(コミット禁止・.gitignore済)")

BASE = "https://api.edinet-fsa.go.jp/api/v2"
class AuthError(Exception):
    def __str__(self): return "EDINET APIキーが無効(401)"
_last, WAIT = [0.0], [1.2]   # レート制限: 最低間隔を敷き、失敗したら自動減速
def api(path, params, binary=False, retries=4):
    global API_KEY
    p = dict(params); p["Subscription-Key"] = API_KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(p)}"
    for k in range(retries):
        gap = WAIT[0] - (time.time() - _last[0])
        if gap > 0: time.sleep(gap)
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
                _last[0] = time.time()
                b = r.read()
                if binary:
                    if b[:1] == b"{":   # バイナリ要求にJSONが返る=エラー通知
                        try:
                            j = json.loads(b)
                            if "401" in str(j.get("StatusCode","")) : raise AuthError()
                        except AuthError: raise
                        except Exception: pass
                        return None
                    return b
                j = json.loads(b)
                if str(j.get("metadata", {}).get("status", "200")) == "401" or "401" in str(j.get("StatusCode","")):
                    raise AuthError()
                return j
        except AuthError:
            raise
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code == 401: raise AuthError()
            WAIT[0] = min(WAIT[0] + 0.4, 4.0); time.sleep(1.0*(k+1))
        except Exception:
            _last[0] = time.time()
            WAIT[0] = min(WAIT[0] + 0.4, 4.0); time.sleep(1.0*(k+1))
    return None

# ---------- キー疎通テスト(通らなければ停止) ----------
print("\n■ APIキー疎通テスト")
try:
    j = api("documents.json", {"date": "2026-06-25", "type": 2})
except AuthError:
    raise SystemExit("    ✗ 401: キーが無効。edinet_key.txt を正しいキーで置き直して再実行を。")
if j is None:
    raise SystemExit("    応答なし——回線かEDINET側の問題。数分待って再実行を。")
n = j.get("metadata", {}).get("resultset", {}).get("count")
print(f"    OK — 2026-06-25 の提出書類 {n} 件。キーは有効。")

# ---------- EDINETコードリスト(証券コード・業種・上場区分) ----------
print("\n■ EDINETコードリスト取得")
CODELIST_PATH = f"{SAVE_DIR}/edinet_codelist.zip"
if not os.path.exists(CODELIST_PATH):
    try:
        req = urllib.request.Request(
            "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip",
            headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            open(CODELIST_PATH,"wb").write(r.read())
    except Exception as e:
        raise SystemExit(f"コードリスト取得失敗: {e} — URLが変わった可能性。Claudeへ。")
E2INFO = {}   # edinetCode -> (証券コード4桁, 名前, 業種)
with zipfile.ZipFile(CODELIST_PATH) as z:
    name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    raw = z.read(name).decode("cp932", errors="replace")
    rows = list(csv.reader(io.StringIO(raw)))
    hdr_i = 0 if "ＥＤＩＮＥＴコード" in ",".join(rows[0]) else 1
    hdr = rows[hdr_i]
    def col(*names):
        for n in names:
            for i,h in enumerate(hdr):
                if n in h: return i
        return None
    c_ed, c_lst, c_sec, c_nm, c_gy = (col("ＥＤＩＮＥＴコード"), col("上場区分"),
                                      col("証券コード"), col("提出者名"), col("提出者業種"))
    for r in rows[hdr_i+1:]:
        if len(r) <= max(c_ed, c_sec): continue
        if r[c_lst].strip() != "上場": continue
        sec = r[c_sec].strip()
        if not sec: continue
        E2INFO[r[c_ed].strip()] = (sec[:4], r[c_nm].strip(), r[c_gy].strip())
print(f"    上場企業 {len(E2INFO)} 社")

# ---------- 書類索引(有価証券報告書のdocID) 増分キャッシュ ----------
IDX_PATH = f"{SAVE_DIR}/edinet_docindex.json"
IDX = {"last_date": None, "docs": []}
if os.path.exists(IDX_PATH):
    IDX = json.load(open(IDX_PATH, encoding="utf-8"))
today = datetime.date.today()
start = (datetime.date.fromisoformat(IDX["last_date"]) + datetime.timedelta(days=1)
         if IDX["last_date"] else today - datetime.timedelta(days=365*INDEX_YEARS))
print(f"\n■ 書類索引: {start} → {today} を走査(キャッシュ済 {len(IDX['docs'])} 件)")
d, fetched = start, 0
while d <= today:
    if d.weekday() < 5:  # 土日は提出なし
        j = api("documents.json", {"date": d.isoformat(), "type": 2})
        if j and j.get("results"):
            for doc in j["results"]:
                if (doc.get("ordinanceCode")=="010" and doc.get("formCode")=="030000"
                        and doc.get("docTypeCode")=="120" and doc.get("csvFlag")=="1"
                        and doc.get("edinetCode") in E2INFO and doc.get("withdrawalStatus")=="0"):
                    IDX["docs"].append({"id":doc["docID"],"ec":doc["edinetCode"],
                                        "pe":doc.get("periodEnd") or "", "sd":d.isoformat()})
        fetched += 1
        if fetched % 120 == 0:
            IDX["last_date"] = d.isoformat()
            json.dump(IDX, open(IDX_PATH,"w",encoding="utf-8"), ensure_ascii=False)
            print(f"    {d} まで走査(有報 {len(IDX['docs'])} 件)")
    d += datetime.timedelta(days=1)
IDX["last_date"] = today.isoformat()
json.dump(IDX, open(IDX_PATH,"w",encoding="utf-8"), ensure_ascii=False)
print(f"    索引完了: 有報 {len(IDX['docs'])} 件")

# 会社ごとに提出日降順で整列
BYCO = collections.defaultdict(list)
for doc in IDX["docs"]:
    if doc["pe"]: BYCO[doc["ec"]].append(doc)
for ec in BYCO:
    BYCO[ec].sort(key=lambda x: x["pe"], reverse=True)
    dedup, seen = [], set()
    for doc in BYCO[ec]:
        if doc["pe"] in seen: continue   # 訂正等の重複は最新提出のみ
        seen.add(doc["pe"]); dedup.append(doc)
    BYCO[ec] = dedup

# ---------- CSV取得と解析 ----------
def fetch_doc(docid):
    p = f"{CACHE}/{docid}.zip"
    if not os.path.exists(p):
        b = api(f"documents/{docid}", {"type": 5}, binary=True)
        if not b or len(b) < 200: return None
        open(p,"wb").write(b)
    try:
        rows = []
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if "XBRL_TO_CSV" in n and os.path.basename(n).startswith("jpcrp") and n.endswith(".csv"):
                    raw = z.read(n)
                    try: txt = raw.decode("utf-16")
                    except Exception: txt = raw.decode("utf-8-sig", errors="replace")
                    rows += list(csv.reader(io.StringIO(txt), delimiter="\t"))
        return rows
    except Exception:
        try: os.remove(p)
        except Exception: pass
        return None

REL = {"当期":0,"前期":1,"前々期":2,"3期前":3,"4期前":4}
def parse_doc(rows):
    """CSV行 → {(要素ローカル名, 相対idx, 連結/個別): float}"""
    if not rows: return None
    hdr = rows[0]
    def ci(name):
        for i,h in enumerate(hdr):
            if name in h: return i
        return None
    i_el, i_rel, i_con, i_dur, i_val = ci("要素ID"), ci("相対年度"), ci("連結"), ci("期間・時点"), ci("値")
    if None in (i_el, i_rel, i_val): return None
    out = {}
    for r in rows[1:]:
        if len(r) <= max(i_el, i_rel, i_val): continue
        el = r[i_el].split(":")[-1].strip()
        rel = r[i_rel].strip()
        # 相対年度は「当期」「前期末」等。末尾の"末"を落として期に正規化
        rel_k = rel.replace("末","")
        if rel_k not in REL: continue
        con = (r[i_con].strip() if i_con is not None and len(r)>i_con else "")
        con = "連結" if "個別" not in con and "非連結" not in con else "個別"
        v = r[i_val].strip().replace(",","")
        if not v or v in ("－","-","―"): continue
        try: v = float(v)
        except Exception: continue
        key = (el, REL[rel_k], con)
        if key not in out: out[key] = v
    return out

def pick(d, names, idx, prefer="連結"):
    """優先順位付き要素名リストから値を1つ取る(連結優先→個別)"""
    for con in ([prefer, "個別"] if prefer=="連結" else ["個別","連結"]):
        for nm in names:
            v = d.get((nm, idx, con))
            if v is not None: return v
    return None

def series(d, names, n=YEARS):
    """当期→4期前の5年系列(古→新の順で返す)。全年揃わなければNone"""
    vals = []
    for k in range(n):
        v = pick(d, names, k)
        if v is None: return None
        vals.append(v)
    return vals[::-1]

# ---------- 要素名(優先順位) — v1候補。校正で更新する ----------
T = {
 # 5年サマリー(jpcrp)
 "rev_s": ["NetSalesSummaryOfBusinessResults","RevenueIFRSSummaryOfBusinessResults",
           "RevenuesUSGAAPSummaryOfBusinessResults","OperatingRevenue1SummaryOfBusinessResults",
           "OperatingRevenue2SummaryOfBusinessResults","GrossOperatingRevenueSummaryOfBusinessResults",
           "NetSalesOfCompletedConstructionContractsSummaryOfBusinessResults",
           "RevenueSummaryOfBusinessResults"],
 "ocf_s": ["CashFlowsFromUsedInOperatingActivitiesSummaryOfBusinessResults",
           "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults",
           "NetCashProvidedByUsedInOperatingActivitiesUSGAAPSummaryOfBusinessResults"],
 "eq_s":  ["NetAssetsSummaryOfBusinessResults","EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
           "TotalEquityIFRSSummaryOfBusinessResults","NetAssetsUSGAAPSummaryOfBusinessResults"],
 "ni_s":  ["ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
           "ProfitAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
           "NetIncomeLossSummaryOfBusinessResults",
           "ProfitLossAttributableToOwnersOfParentUSGAAPSummaryOfBusinessResults"],
 # 財務諸表(jppfs/jpigp — 各有報に当期・前期の2年分)
 "op":    ["OperatingIncome","OperatingProfitLossIFRS","OperatingIncomeLoss"],
 "d_st":  ["ShortTermLoansPayable","CurrentPortionOfLongTermLoansPayable","CurrentPortionOfBonds",
           "CommercialPapersLiabilities","BondsAndBorrowingsCurrentIFRS","BorrowingsCurrentIFRS"],
 "d_lt":  ["LongTermLoansPayable","BondsPayable","ConvertibleBonds",
           "BondsAndBorrowingsNoncurrentIFRS","BorrowingsNoncurrentIFRS"],
 "cash":  ["CashAndDeposits","CashAndCashEquivalentsIFRS"],
 "sti":   ["Securities","ShortTermInvestmentSecurities","OtherSecurities"],
 "capex": ["PurchaseOfPropertyPlantAndEquipmentInvCF",
           "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsInvCF",
           "PurchaseOfPropertyPlantAndEquipmentIFRSInvCF",
           "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsIFRSInvCF"],
}

def sum_multi(d, names, idx):
    """負債系: 該当要素を合算(無い要素は0)"""
    tot, hit = 0.0, False
    for con in ("連結","個別"):
        for nm in names:
            v = d.get((nm, idx, con))
            if v is not None: tot += v; hit = True
        if hit: return tot
    return 0.0

# ============================ Stage 1 ============================
print(f"\n■ Stage1 — 最新有報で一次ふるい(対象 {len(BYCO)} 社)")
S1, QUAR = [], collections.Counter()
t0, done = time.time(), 0
for ec, docs in BYCO.items():
    done += 1
    if done % 300 == 0:
        el = time.time()-t0
        print(f"    {done}/{len(BYCO)}  生存:{len(S1)}  経過{el/60:.0f}分 残り約{el/done*(len(BYCO)-done)/60:.0f}分")
    sec, nm, gy = E2INFO[ec]
    if gy in EXCLUDE_GYOSHU: QUAR["業態除外"] += 1; continue
    if not docs: QUAR["有報なし"] += 1; continue
    latest = docs[0]
    if (today - datetime.date.fromisoformat(latest["pe"])).days > STALE_DAYS:
        QUAR["stale"] += 1; continue
    d = parse_doc(fetch_doc(latest["id"]))
    if d is None: QUAR["取得失敗"] += 1; continue
    rev = series(d, T["rev_s"])
    if rev is None or any(x <= 0 for x in rev): QUAR["売上5年不備"] += 1; continue
    ocf = series(d, T["ocf_s"]); ni = series(d, T["ni_s"]); eq = series(d, T["eq_s"])
    if ocf is None or ni is None or eq is None: QUAR["サマリー欠損"] += 1; continue
    op0 = pick(d, T["op"], 0)
    if op0 is None: QUAR["営業利益なし"] += 1; continue
    cagr = (rev[-1]/rev[0])**(1/(YEARS-1)) - 1
    # 偽陰性ゼロの条件だけで切る(ROICでは切らない=椅子候補を守る)
    if cagr < MIN_SALES_CAGR: QUAR["S1:売上CAGR"] += 1; continue
    if any(x <= 0 for x in ocf): QUAR["S1:営業CF"] += 1; continue
    if op0/rev[-1] < MIN_OPM: QUAR["S1:営業利益率"] += 1; continue
    if sum(ni) <= 0: QUAR["S1:純利益合計"] += 1; continue
    S1.append({"ec":ec,"sec":sec,"name":nm,"gy":gy,"docs":docs,"d0":d,
               "rev":rev,"ocf":ocf,"ni":ni,"eq":eq,"cagr":cagr,
               "pe":latest["pe"]})
print(f"    Stage1通過: {len(S1)} 社  隔離上位: " + ", ".join(f"{k}:{v}" for k,v in QUAR.most_common(6)))

# ============================ Stage 2 ============================
print(f"\n■ Stage2 — 生存 {len(S1)} 社を5年フル判定(過去有報を追加取得)")
RESULTS = []
for i, s in enumerate(S1, 1):
    if i % 40 == 0: print(f"    {i}/{len(S1)}")
    # 5年分の財務諸表: 最新有報が0,1期をカバー。残る2〜4期は過去有報を
    # 決算日の年差で対応付けて埋める(年ズレ・決算期変更に頑健)
    pe0 = datetime.date.fromisoformat(s["pe"])
    stm, need = {0: s["d0"]}, {2, 3, 4}
    for doc in s["docs"][1:]:
        if not need: break
        delta = round((pe0 - datetime.date.fromisoformat(doc["pe"])).days / 365.25)
        if delta < 1 or delta > 4: continue
        if delta in need or (delta+1) in need:
            dd = parse_doc(fetch_doc(doc["id"]))
            if dd:
                stm[delta] = dd
                need.discard(delta); need.discard(delta+1)
    def stm_series(names, mode="pick"):
        out = [None]*YEARS
        for ofs, dd in stm.items():
            for k in (0, 1):
                idx = ofs + k
                if idx >= YEARS: continue
                v = sum_multi(dd, names, k) if mode=="sum" else pick(dd, names, k)
                if out[idx] is None: out[idx] = v
        if mode=="pick" and any(v is None for v in out): return None
        if mode=="sum": out = [v if v is not None else 0.0 for v in out]
        return out[::-1]
    op  = stm_series(T["op"])
    cap = [abs(x) for x in stm_series(T["capex"], mode="sum")]  # EDINETのCF支出は負値
    dbt_st = stm_series(T["d_st"], mode="sum"); dbt_lt = stm_series(T["d_lt"], mode="sum")
    ca  = stm_series(T["cash"], mode="sum"); si = stm_series(T["sti"], mode="sum")
    if op is None: QUAR["S2:営業利益5年"] += 1; continue
    rev, ocf, ni, eq = s["rev"], s["ocf"], s["ni"], s["eq"]
    fcf = [ocf[k]-cap[k] for k in range(YEARS)]
    roic, broken = [], False
    for k in range(YEARS):
        ic = eq[k] + dbt_lt[k] + dbt_st[k]
        if ic <= 0: broken = True; break
        roic.append(op[k]*TAX/ic)
    if broken: QUAR["S2:投下資本"] += 1; continue
    opm = op[-1]/rev[-1]
    conv = sum(fcf)/sum(ni)
    m = {"sales_cagr5":round(s["cagr"],4),"opm":round(opm,4),
         "roic_latest":round(roic[-1],4),"roic_worst5":round(min(roic),4),
         "fcf_conv_5y":round(conv,4),
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
    if conv < MIN_FCF_CONV: f.append("FCF転換")
    m["score"] = 7-len(f); m["fails"] = "; ".join(f)
    # 解剖列と椅子材料(現金+流動有価証券控除。投資有価証券は含めない=校正論点)
    roic_ex, ic_ex_neg = [], False
    for k in range(YEARS):
        icx = eq[k]+dbt_lt[k]+dbt_st[k]-ca[k]-si[k]
        if icx <= 0: ic_ex_neg = True; break
        roic_ex.append(op[k]*TAX/icx)
    ic = eq[-1]+dbt_lt[-1]+dbt_st[-1]
    m.update({"ticker":s["sec"],"name":s["name"][:30],"gyoshu":s["gy"],"ccy":"JPY",
              "fy_latest":s["pe"][:7],"op_src":"reported",
              "roic_ex_latest":round(roic_ex[-1],4) if not ic_ex_neg else None,
              "roic_ex_worst":round(min(roic_ex),4) if not ic_ex_neg else None,
              "ic_ex_neg":ic_ex_neg,
              "cash_pct":round((ca[-1]+si[-1])/ic*100,1) if ic>0 else None})
    RESULTS.append(m)
print(f"    判定完了: {len(RESULTS)} 社")

# ============================ 出力 ============================
RESULTS.sort(key=lambda r: (-r["score"], -r["roic_worst5"]))
cols = ["ticker","name","gyoshu","ccy","fy_latest","score","fails","roic_latest","roic_worst5",
        "opm","sales_cagr5","fcf_conv_5y","op_all_pos","fcf_all_pos","equity_neg","warn_anomaly",
        "op_src","roic_ex_latest","roic_ex_worst","ic_ex_neg","cash_pct"]
with open(f"{SAVE_DIR}/gate0_jp_all.csv","w",newline="",encoding="utf-8-sig") as fp:
    w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(RESULTS)
sc = collections.Counter(r["score"] for r in RESULTS)
print(f"\n判定 {len(RESULTS)} 社 / 7点 {sc[7]} / 6点 {sc[6]} / 5点 {sc[5]}")

rows = [r for r in RESULTS if r["score"] >= SEND_TO_GATE1 and not r["warn_anomaly"]]
queue = sorted([r for r in rows if not r["equity_neg"]],
               key=lambda r: -(0.30*min(max((r["roic_worst5"]-0.10)/0.35,0),1)
                              +0.30*min(max((r["sales_cagr5"]-0.05)/0.25,0),1)
                              +0.20*min(max((r["opm"]-0.15)/0.35,0),1)
                              +0.10*min(max((min(r["fcf_conv_5y"],1.5)-0.70)/0.50,0),1)
                              +0.10*(1.0 if r["score"]==7 else 0.0)))[:TOP_N_JP]
resc = [r for r in RESULTS if r["score"]==5
        and set(x.strip() for x in r["fails"].split(";") if x.strip()).issubset(RESCUE_FAILS)
        and r["op_all_pos"] and r["fcf_all_pos"]
        and r["opm"]>=RESCUE_MIN_OPM and r["sales_cagr5"]>=RESCUE_MIN_CAGR]
chairs = [r for r in resc if not r["ic_ex_neg"] and r["roic_ex_latest"] is not None
          and r["roic_ex_latest"]>=MIN_ROIC_LATEST and r["roic_ex_worst"]>=MIN_ROIC_WORST]
for path, data in [("gate0_jp_queue.json",queue),("gate0_jp_rescue.json",chairs)]:
    json.dump(data, open(f"{SAVE_DIR}/{path}","w",encoding="utf-8"), ensure_ascii=False, indent=1)

print("\n" + "="*74 + f"\n■ 日本株 待ち行列: {len(queue)} 社\n" + "="*74)
for i, r in enumerate(queue, 1):
    print(f"{i:>3}. {r['ticker']} {r['score']}/7 ROIC最低{r['roic_worst5']*100:5.1f}% "
          f"営利{r['opm']*100:5.1f}% CAGR{r['sales_cagr5']*100:5.1f}%  {r['name'][:18]}")
print("\n" + "="*74 + f"\n★ 敗者復活の椅子(現金型・{len(chairs)}社)\n" + "="*74)
for r in sorted(chairs, key=lambda r: -r["roic_ex_latest"]):
    print(f"  {r['ticker']} 現金込み{r['roic_latest']*100:5.1f}% → 控除{r['roic_ex_latest']*100:6.1f}% "
          f"現金{r['cash_pct']}%  {r['name'][:18]}")

# ============================ 校正モード ============================
print("\n■ 校正 — golden銘柄の抽出値(目視で有報と突合すること)")
BYT = {r["ticker"]: r for r in RESULTS}
for sec, nm in GOLDEN_JP.items():
    r = BYT.get(sec)
    if r is None:
        print(f"  ✗ {sec} {nm}: RESULTSに不在 — Stage1隔離理由を確認せよ"); continue
    print(f"  ○ {sec} {nm}: {r['score']}/7 ✗{r['fails'] or 'なし'} | ROIC{r['roic_latest']*100:.1f}% "
          f"最低{r['roic_worst5']*100:.1f}% 営利{r['opm']*100:.1f}% CAGR{r['sales_cagr5']*100:.1f}% "
          f"転換{r['fcf_conv_5y']:.2f} 現金{r['cash_pct']}%")
print("\n【校正の見方】キーエンスはROIC落ち→椅子入りが期待形(現金の山)。数字が有報と")
print("合わない銘柄はタグ取り違え——銘柄名と正しい値をClaudeへ。v2で期待値を固定する。")
print("\n→ 出力: gate0_jp_all.csv / gate0_jp_queue.json / gate0_jp_rescue.json")
