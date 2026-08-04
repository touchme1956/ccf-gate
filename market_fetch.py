# market_fetch.py — 市場データ採取器（門の間・発見度を全自動で埋める）
#   出力: market_data.json  {TICKER: {px, mcap, beta, per, perF, analysts, instOwn, z, shy, evebit}}
#   これを門の「Ⅲ採点機→市場データ」に使う。審査パック(out/*_gate_pack.json)へのマージも可。(vs_spx流し込みは機能撤去済み・2026-07)
#
# 【思想】発見度(Neglect)を中型でも効かせる。<$2Bはmcapプロキシで門が自動加点するが、
#   $2-100Bの中型は「アナリスト数・機関保有%」の実データが無いと未発見か発見済みか判別できない。
#   本器がそれを埋めることで、門の既存 negS ロジック(≤3社=+2 / 4-8=+1 / >15=-1 / instOwn<40=+1 / >85=-1)が中型にも発火する。
#
# 【データ源と鍵】
#   px/mcap/beta : FMP (fmp_key.txt / FMP_KEY)。無ければAVのGLOBAL_QUOTE+OVERVIEWで代替。
#   per/perF/analysts/instOwn : Alpha Vantage OVERVIEW (av_key.txt / AV_KEY)。無料鍵は25req/日 → 未処理は次回へ(resume)。
#   z/shy/evebit : companyfacts.zip からローカル計算(鍵不要・全自動)。
#
# 【使い方】
#   python market_fetch.py                 # gate1_queue.json + holdings.json を対象、market_data.json に追記(resume)
#   python market_fetch.py MSFT QLYS IRMD  # 個別指定
#   python market_fetch.py --merge         # 取得済み market_data.json を out/*_gate_pack.json にマージ
import json, os, sys, time, zipfile, datetime, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
HDR  = {"User-Agent": "CCF-Omega-market fortis5280@gmail.com"}
OUT  = os.path.join(BASE, "market_data.json")
KEYFILES = lambda n: [f"./{n}", f"./ccf/{n}", f"/content/drive/MyDrive/ccf/{n}"]

def _key(name, env):
    for p in KEYFILES(name):
        if os.path.exists(p):
            v = open(p).read().strip()
            if v: return v
    return os.environ.get(env, "").strip()

AV_KEY  = _key("av_key.txt",  "AV_KEY")
FMP_KEY = _key("fmp_key.txt", "FMP_KEY")

def _get(url, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=timeout) as r:
        return r.read().decode()

def _num(v):
    try:
        if v in (None, "", "None", "-", "N/A"): return None
        return float(v)
    except Exception:
        return None

# ---- 対象ティッカー ----
def targets():
    args = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    if args: return args
    ts = []
    q = os.path.join(BASE, "gate1_queue.json")
    if os.path.exists(q):
        ts += [r["ticker"] for r in json.load(open(q))]
    h = os.path.join(BASE, "holdings.json")
    if os.path.exists(h):
        try:
            hd = json.load(open(h))
            ts += [x.get("ticker") or x.get("nm") for x in (hd if isinstance(hd, list) else hd.get("holdings", []))]
        except Exception:
            pass
    seen, out = set(), []
    for t in ts:
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out

# ---- FMP: px / mcap / beta ----
def fmp_profile(t):
    if not FMP_KEY: return {}
    try:
        j = json.loads(_get(f"https://financialmodelingprep.com/stable/profile?symbol={t}&apikey={FMP_KEY}"))
        d = j[0] if isinstance(j, list) and j else (j if isinstance(j, dict) else {})
        return {"px": _num(d.get("price")), "mcap": (_num(d.get("marketCap")) or 0)/1e9 or None, "beta": _num(d.get("beta"))}
    except Exception:
        return {}

# ---- Alpha Vantage OVERVIEW: per / perF / analysts / instOwn (+ px/mcap/beta フォールバック) ----
def av_overview(t):
    if not AV_KEY: return None  # None=未取得(resume対象)
    try:
        d = json.loads(_get(f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={t}&apikey={AV_KEY}"))
    except Exception:
        return None
    if not d or "Symbol" not in d:
        # レート上限 or 不明シンボル。Note/Informationがあれば上限扱い→None(resume)
        return None
    rate = lambda k: int(_num(d.get(k)) or 0)
    an = rate("AnalystRatingStrongBuy")+rate("AnalystRatingBuy")+rate("AnalystRatingHold")+rate("AnalystRatingSell")+rate("AnalystRatingStrongSell")
    return {
        "per":   _num(d.get("PERatio")),
        "perF":  _num(d.get("ForwardPE")),
        "analysts": an or None,
        "instOwn":  _num(d.get("PercentInstitutions")),
        "beta":  _num(d.get("Beta")),
        "mcap":  (_num(d.get("MarketCapitalization")) or 0)/1e9 or None,
    }

# ---- ローカル: z(Altman Z'') / shy / evebit ----
def _d2(s): return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
def _series(facts, pairs, flow):
    m = {}
    for ns, tag in pairs:
        node = facts.get(ns, {}).get(tag)
        if not node: continue
        for u, ents in node.get("units", {}).items():
            if "/" in u: continue
            for e in ents:
                en = e.get("end"); fl = e.get("filed", "")
                if not en: continue
                if flow:
                    st = e.get("start")
                    if not st or not (330 <= (_d2(en)-_d2(st)).days <= 400): continue
                else:
                    if e.get("start"): continue
                y = int(en[:4])
                if y not in m or fl > m[y][1]: m[y] = (float(e["val"]), fl)
    return {y: v for y, (v, _) in m.items()}

_CIK = None
def _cik(t):
    global _CIK
    if _CIK is None:
        j = json.loads(_get("https://www.sec.gov/files/company_tickers.json"))
        _CIK = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in j.values()}
    return _CIK.get(t)

def local_health(t, zf, mcap_b):
    cik = _cik(t)
    if not cik: return {}
    try:
        facts = json.loads(zf.read(f"CIK{cik}.json"))["facts"]
    except KeyError:
        return {}
    U = lambda x: [("us-gaap", x)]
    op  = _series(facts, U("OperatingIncomeLoss"), True)
    gp  = _series(facts, U("GrossProfit"), True); cor = _series(facts, [("us-gaap","CostOfRevenue"),("us-gaap","CostOfGoodsAndServicesSold")], True)
    rev = _series(facts, [("us-gaap","Revenues"),("us-gaap","RevenueFromContractWithCustomerExcludingAssessedTax")], True)
    rd  = _series(facts, U("ResearchAndDevelopmentExpense"), True); sga = _series(facts, U("SellingGeneralAndAdministrativeExpense"), True)
    for y in list(rev):
        if y not in gp and y in cor: gp[y] = rev[y]-cor[y]
    for y in gp:
        if y not in op and y in rd and y in sga: op[y] = gp[y]-rd[y]-sga[y]
    ca=_series(facts,U("AssetsCurrent"),False); cl=_series(facts,U("LiabilitiesCurrent"),False); re_=_series(facts,U("RetainedEarningsAccumulatedDeficit"),False)
    tl=_series(facts,U("Liabilities"),False); ta=_series(facts,U("Assets"),False); eq=_series(facts,U("StockholdersEquity"),False)
    dL=_series(facts,[("us-gaap","LongTermDebtNoncurrent"),("us-gaap","LongTermDebt"),("us-gaap","DebtAndCapitalLeaseObligations")],False)
    dS=_series(facts,[("us-gaap","LongTermDebtCurrent"),("us-gaap","DebtCurrent")],False)
    cash=_series(facts,U("CashAndCashEquivalentsAtCarryingValue"),False); sti=_series(facts,[("us-gaap","ShortTermInvestments"),("us-gaap","MarketableSecuritiesCurrent")],False)
    div=_series(facts,[("us-gaap","PaymentsOfDividends"),("us-gaap","PaymentsOfDividendsCommonStock")],True)
    bb =_series(facts,[("us-gaap","PaymentsForRepurchaseOfCommonStock")],True)
    # 2026-08-04是正(B13): 門の定義は shy=(配当+自社株買い−株式発行)÷時価総額＝**純額**。
    #   ここだけグロス(発行控除なし)で、market_fetch_free.py と定義が割れていた——発行の大きい
    #   会社でE[r]過大→門X誤開通の方向。発行タグ群は free 版と同一。
    iss=_series(facts,[("us-gaap","ProceedsFromIssuanceOfCommonStock"),
                       ("us-gaap","ProceedsFromStockOptionsExercised"),
                       ("us-gaap","ProceedsFromIssuanceOfSharesUnderIncentiveAndShareBasedCompensationPlans")],True)
    mc = (mcap_b or 0)*1e9
    r = {}
    ys=[y for y in ta if y in tl and y in eq and y>=2024]
    if ys:
        y=max(ys); TA=ta[y]; TL=tl[y]
        if TA>0 and TL>0 and y in ca and y in cl and y in re_:
            oy=max([x for x in op if abs(x-y)<=1], default=None)
            if oy: r["z"]=round(6.56*(ca[y]-cl[y])/TA+3.26*re_[y]/TA+6.72*op[oy]/TA+1.05*eq[y]/TL, 2)
    if mc:
        fy=max([y for y in op if y>=2024], default=None)
        if fy:
            d=div.get(fy,0)+bb.get(fy,0)
            if d>0: r["shy"]=round(max(0.0, d-iss.get(fy,0))/mc*100, 2)   # 純額(B13・free版と同式)
            by=max([y for y in eq if y>=2024], default=None)
            if by and op[fy]>0: r["evebit"]=round((mc+dL.get(by,0)+dS.get(by,0)-cash.get(by,0)-sti.get(by,0))/op[fy], 1)
    return r

def merge_into_packs(data):
    """--merge は market_merge.py へ委譲する（2026-08-04是正・A6）。
    旧実装はここに**第二のマージ経路**を持っており、market_merge.py の関門をすべて素通りしていた:
      (1) null以外も上書き＝**審査官の手入力値を消せる** (2) BANDS常識帯の検問なし＝KLAC型の
      旧不正値が再注入される (3) _meta.nulls（「測ったうえで空欄と決めた」欄）の保護なし
      (4) 充填履歴(_meta.market / evidence / provenance)を残さない。
    「同じ台帳を見る二つの道具が違うことを言ってはいけない」(v9.9.65) ——マージの正本は
    market_merge.py 一本にし、こちらは呼び出すだけにする。"""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(BASE, "market_merge.py")], cwd=BASE)
    if r.returncode != 0:
        print("▲ market_merge.py が失敗 — market_data.json を先に更新したか確認")

def main():
    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if "--merge" in sys.argv:
        merge_into_packs(data); return
    ts = targets()
    zf = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip")) if os.path.exists(os.path.join(BASE,"companyfacts.zip")) else None
    # 2026-08-04是正(R10): av_done は従来**失敗(None)しか数えていなかった**ため、成功が続く日は
    #   発行リクエスト数が無検問のまま無料鍵の25/日を突き抜けた。予算は**発行した全リクエスト**で
    #   数える（成否は無関係——上限側は成功も失敗も同じ1回）。
    av_done, av_capped = 0, False
    for t in ts:
        cur = data.get(t, {})
        # 既に analysts/instOwn まで揃っていればスキップ(resume)
        if cur.get("analysts") is not None and cur.get("instOwn") is not None and cur.get("px") is not None:
            continue
        rec = dict(cur)
        # FMP: px/mcap/beta
        for k, v in fmp_profile(t).items():
            if v is not None: rec[k] = v
        # AV: per/perF/analysts/instOwn(+フォールバック)。無料鍵は25/日 → 予算を使い切ったら
        #   AVだけ止めて FMP/ローカル計算は続行(resume——未取得分は次回)
        ov = None
        if AV_KEY and av_done < 24:
            ov = av_overview(t)
            av_done += 1
        elif AV_KEY and not av_capped:
            print(f"AV日次予算(24req)を使い切り — {t} 以降のAV項目は次回(resume)。")
            av_capped = True
        if ov:
            for k, v in ov.items():
                if v is not None and rec.get(k) is None: rec[k] = v
        # ローカル health
        if zf:
            for k, v in local_health(t, zf, rec.get("mcap")).items():
                rec[k] = v
        data[t] = rec
        time.sleep(0.8)  # SEC/FMPレート礼儀
        print(f"{t}: px={rec.get('px')} mcap={rec.get('mcap')} beta={rec.get('beta')} analysts={rec.get('analysts')} instOwn={rec.get('instOwn')}")
    json.dump(data, open(OUT, "w"), ensure_ascii=False, indent=1)
    got = sum(1 for v in data.values() if v.get("analysts") is not None)
    print(f"\n保存 {OUT}: {len(data)}社 (analysts取得済 {got}社)。全自動化するには av_key.txt(premiumで日次上限解除) と fmp_key.txt を置く。")
    print("次: python market_fetch.py --merge でパックへ反映 → 門で再採点")

if __name__ == "__main__":
    main()
