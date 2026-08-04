#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v10_series.py — CCF Ω v10「系列の門」影スコア計算器(2026-07制定・並走検証用)
正本(v9.9.x)は不変。本器はSEC XBRLの年次系列から機械実測5系列を計算し、既存パックの
定性(堀4問・geopol・資本配分材料)と合成した v10影スコア を out/v10_shadow.json に書く。
2027-07の較正(calibration_check.py)で新旧の予実を答え合わせし、勝った方を正本にする。
仕様の正本: V10_SPEC.md
  機械実測5系列(70%): ROIIC系列20 / 増分マージン系列15 / through-cycle実測15 /
                       希薄化調整1株FCF成長15 / 粗利安定×転嫁力5
  定性(30%): 堀1因子18(dom/irr/rep/durの加重+方向) / 資本配分7 / geopol5
  合成は幾何平均(弱点を隠せない)・キル/三本柱/門Xは現行ゲートのまま(影は序列のみ)
使い方: python v10_series.py            … kanshi_list.jsonの監視銘柄(US)を計算
        python v10_series.py NVDA MSFT  … 指定銘柄のみ
データ: data.sec.gov companyfacts API(銘柄ごと1リクエスト・10req/s遵守)
"""
import json, re, sys, time, os, math, urllib.request
from datetime import date

EMAIL = "fortis5280@gmail.com"
HDRS = {"User-Agent": f"ccf-v10 {EMAIL}"}
OUTP = "out/v10_shadow.json"

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)
    return b.decode("utf-8", "ignore")

def cik_of(t, _c={}):
    if not _c:
        j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
        for v in j.values():
            _c[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
    return _c.get(t.upper())

TAGS = {
 "rev":   ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenue"],
 "op":    ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
 "gp":    ["GrossProfit"],
 "ocf":   ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
 "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipment"],
 "eq":    ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"],
 "cash":  ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalents"],
 "debt":  ["LongTermDebtNoncurrent", "LongTermDebt", "Borrowings"],
 "sh":    ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageShsOutDil"],
}
FLOW = {"rev", "op", "gp", "ocf", "capex", "sh"}   # duration系(FY) / 残りはinstant

def annual(facts, keys, flow):
    """FY(10-K/20-F)の年次系列 {fy_end: val}。タグ乗換対応=最新年が最も新しい系列を採用"""
    best = {}
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get("facts", {}).get(ns, {})
        for k in keys:
            if k not in d: continue
            for u, rows in d[k]["units"].items():
                out = {}
                for r in rows:
                    if not r.get("form", "").startswith(("10-K", "20-F")): continue
                    e = r.get("end")
                    if not e: continue
                    if flow:
                        s = r.get("start")
                        if not s: continue
                        try:
                            days = (date.fromisoformat(e) - date.fromisoformat(s)).days
                        except Exception: continue
                        if not (330 <= days <= 400): continue
                    out[e] = r["val"]
                if out and (not best or max(out) > max(best)):
                    best = out
    return dict(sorted(best.items()))

def series(t):
    cik = cik_of(t)
    if not cik: return None
    facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    s = {k: annual(facts, v, k in FLOW) for k, v in TAGS.items()}
    return s

def align(s, keys):
    """共通年(全keysが揃うFY末)の昇順リスト"""
    yrs = None
    for k in keys:
        ks = set(s[k].keys())
        yrs = ks if yrs is None else (yrs & ks)
    return sorted(yrs or [])

def clamp(x, lo=1.0, hi=100.0): return max(lo, min(hi, x))

def f_roiic(s, notes):
    """F1 ROIIC系列20%: 3年ローリングΔNOPAT/ΔICの水準+傾き"""
    yrs = align(s, ["op", "eq", "cash"])
    if len(yrs) < 5: notes.append("roiic: 系列5年未満→na(60)"); return 60.0
    nop = {y: s["op"][y] * 0.79 for y in yrs}
    # ルール7の限界注記(2026-08-04): debt は align 対象外で、タグが無い年を 0 と読んでいる
    #   （cashはalign済みで常にある）。他年に報告があるのにその年だけ欠測なら ΔIC が歪み
    #   ROIICが過大/過小に出うる。影スコア（序列のみ・正本不使用）ゆえ挙動は据え置くが、
    #   欠測年を検出したら note に残して黙らせない（欠測と無借金を区別できないため値は触らない）。
    if s["debt"] and any(y not in s["debt"] for y in yrs):
        notes.append("roiic: 有利子負債タグの欠測年を0と読んでいる(影の限界——ΔICが歪みうる)")
    ic = {y: s["eq"][y] + s["debt"].get(y, 0) - s["cash"].get(y, 0) for y in yrs}
    rr = []
    for i in range(3, len(yrs)):
        dn, di = nop[yrs[i]] - nop[yrs[i-3]], ic[yrs[i]] - ic[yrs[i-3]]
        rr.append((yrs[i], dn / di * 100 if di > 0 else None))
    vals = [v for _, v in rr if v is not None]
    if not vals: notes.append("roiic: ΔIC≤0(資本を返しながら成長)→還元型75"); return 75.0
    lvl = vals[-1]
    sc = 90 if lvl >= 24 else 80 if lvl >= 17 else 70 if lvl >= 12 else 60 if lvl >= 9 else 45
    if len(vals) >= 3:
        if vals[-1] > vals[-3] * 1.15: sc += 5; notes.append(f"roiic上昇 {vals[-3]:.0f}→{vals[-1]:.0f}%")
        elif vals[-1] < vals[-3] * 0.7: sc -= 8; notes.append(f"roiic低下 {vals[-3]:.0f}→{vals[-1]:.0f}%")
    return clamp(sc)

def f_incmargin(s, notes):
    """F2 増分マージン系列15%: ΔOP/ΔRev(3年)と現行OPMの比較。反転2期でフラグ"""
    yrs = align(s, ["rev", "op"])
    if len(yrs) < 5: notes.append("incM: 系列不足→na(60)"); return 60.0
    opm = s["op"][yrs[-1]] / s["rev"][yrs[-1]] * 100 if s["rev"][yrs[-1]] else 0
    inc = []
    for i in range(3, len(yrs)):
        dr = s["rev"][yrs[i]] - s["rev"][yrs[i-3]]
        inc.append(( (s["op"][yrs[i]] - s["op"][yrs[i-3]]) / dr * 100) if dr > 0 else None)
    vals = [v for v in inc if v is not None]
    if not vals: notes.append("incM: 減収期→50"); return 50.0
    m = vals[-1]
    sc = 90 if m > opm * 1.1 and m > 0 else 75 if m >= opm * 0.8 else 55 if m >= opm * 0.5 else 40
    if len(vals) >= 2 and vals[-1] < 0 and vals[-2] < 0:
        sc = 35; notes.append("⚠増分マージン2期連続マイナス——堀劣化の機械的先行指標(S2相当で要審査)")
    return clamp(sc)

def f_cycle(s, notes):
    """F3 through-cycle実測15%: 2008-09/2020/2022-23の営利DD実測(最悪値)"""
    yrs = align(s, ["op"])
    if len(yrs) < 8: notes.append("cycle: 上場浅く不況実測なし→上限70"); return 65.0
    op = {y[:4]: s["op"][y] for y in yrs}
    worst = 0.0; hit = False
    for ev, (pre, win) in {"GFC": ("2007", ["2008", "2009"]), "COVID": ("2019", ["2020"]),
                            "2022": ("2021", ["2022", "2023"])}.items():
        if pre in op and op[pre] > 0 and any(w in op for w in win):
            hit = True
            dd = min((op[w] / op[pre] - 1) * 100 for w in win if w in op)
            worst = min(worst, dd)
            if dd < -20: notes.append(f"cycle {ev}: 営利{dd:.0f}%")
    if not hit: notes.append("cycle: 対象期の系列なし→上限70"); return 65.0
    return clamp(95 if worst >= -10 else 85 if worst >= -25 else 70 if worst >= -40 else 50 if worst >= -60 else 35)

def f_fcfps(s, notes):
    """F4 希薄化調整1株FCF成長5年15%: 経営の通信簿(買収・還元・希薄化を1本に集約)"""
    yrs = align(s, ["ocf", "capex", "sh"])
    if len(yrs) < 5: notes.append("fcfps: 系列不足→na(60)"); return 60.0
    y0, y1 = yrs[-5], yrs[-1]
    f0 = (s["ocf"][y0] - abs(s["capex"].get(y0, 0))) / s["sh"][y0]
    f1v = (s["ocf"][y1] - abs(s["capex"].get(y1, 0))) / s["sh"][y1]
    if f0 <= 0: notes.append("fcfps: 起点FCF≤0→na(55)"); return 55.0
    cagr = ((f1v / f0) ** 0.25 - 1) * 100 if f1v > 0 else -99
    notes.append(f"fcfps CAGR4y {cagr:.1f}%")
    return clamp(95 if cagr >= 20 else 85 if cagr >= 15 else 75 if cagr >= 10 else 60 if cagr >= 5 else 50 if cagr >= 0 else 35)

def f_gross(s, notes):
    """F5 粗利安定×転嫁力5%: 水準・σ・21→23の転嫁実績"""
    yrs = align(s, ["gp", "rev"])
    # 2026-08-04是正(B1): 年と粗利率は**対で**組む。旧実装は gm を rev>0 で間引いたのに
    #   yrs は間引かず zip(yrs, gm) していたため、rev=0の年が1つでもあると以降の年ラベルが
    #   1つずつずれた（「基準の違う二つを割る」型のzip版）。
    pairs = [(y, s["gp"][y] / s["rev"][y] * 100) for y in yrs if s["rev"][y]]
    if len(pairs) < 4: notes.append("gross: GrossProfit未開示→na(65)"); return 65.0
    gm = [v for _, v in pairs]
    lvl = gm[-1]; n = min(5, len(gm))
    mu = sum(gm[-n:]) / n
    sd = (sum((x - mu) ** 2 for x in gm[-n:]) / n) ** 0.5
    sc = 80 if lvl >= 50 else 70 if lvl >= 35 else 60 if lvl >= 20 else 50
    sc += 10 if sd < 1.5 else (-10 if sd > 4 else 0)
    g21 = {y[:4]: v for y, v in pairs}
    if "2021" in g21 and "2023" in g21:
        sc += 5 if g21["2023"] >= g21["2021"] else -5
    return clamp(sc)

def qual_from_pack(t, notes):
    """定性30%は既存パックから: 堀1因子18 / 資本配分7 / geopol5(新審査は不要=影の原則)"""
    fp = f"out/{t}_gate_pack.json"
    if not os.path.exists(fp): notes.append("pack無し→定性na(65/70/85)"); return 65.0, 70.0, 85.0
    o = json.load(open(fp, encoding="utf-8"))
    num = lambda k, d: float(o[k]) if o.get(k) is not None and str(o[k]).replace(".", "").replace("-", "").isdigit() else d
    dom, irr, rep, dur = num("dom", 65), num("irr", 65), num("rep", 60), num("dur", 70)
    moat = math.exp(0.35 * math.log(max(dom, 1)) + 0.25 * math.log(max(irr, 1))
                    + 0.20 * math.log(max(rep, 1)) + 0.20 * math.log(max(dur, 1)))
    if o.get("erosion") == "emerging": moat -= 6
    if o.get("erosion") == "active": moat -= 15; notes.append("erosion=active→堀-15")
    if o.get("disrupt") == "threat": moat -= 12
    cap = 75.0
    roic, roicg = num("roic", 0), num("roicg", 0)
    if roicg and roic and roicg < roic - 8: cap -= 10; notes.append("のれん込みROIC乖離→資本配分-10")
    sbc = num("sbc", 0)
    if sbc >= 12: cap -= min(15, sbc - 12)
    geo = {0: 95, 1: 80, 2: 60, 3: 40}.get(int(num("geopol", 0)), 80)
    return clamp(moat), clamp(cap), float(geo)

W = {"roiic": .20, "incm": .15, "cycle": .15, "fcfps": .15, "gross": .05,
     "moat": .18, "cap": .07, "geo": .05}

def score(t):
    notes = []
    s = series(t)
    if s is None: return None
    f = {"roiic": f_roiic(s, notes), "incm": f_incmargin(s, notes), "cycle": f_cycle(s, notes),
         "fcfps": f_fcfps(s, notes), "gross": f_gross(s, notes)}
    f["moat"], f["cap"], f["geo"] = qual_from_pack(t, notes)
    v10 = math.exp(sum(W[k] * math.log(max(f[k], 1)) for k in W))
    return {"v10": round(v10, 1), "factors": {k: round(v, 1) for k, v in f.items()}, "notes": notes}

if __name__ == "__main__":
    args = [a.upper() for a in sys.argv[1:] if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,7}", a)]
    if not args:
        kn = json.load(open("kanshi_list.json", encoding="utf-8"))
        # 2026-08-04是正(B1): make_kanshi.py が書くキーは **"list"**（＋pin）。旧キー "tickers" しか
        #   読んでおらず**引数なし実行は黙って0銘柄**＝v10影スコア(2027-07較正の材料)が2026-07-27の
        #   28社のまま更新されていなかった。kessan_check/calendar は同事故を是正済みでここだけ
        #   取り残し。旧キーは後方互換で残す。日本株(数字コード)はSEC対象外ゆえ従来どおり除外
        tk = (kn.get("list") or kn.get("tickers") or []) + (kn.get("pin") or [])
        seen = set()
        args = [t for t in tk
                if not re.fullmatch(r"\d{4,5}(?:\.T)?", t) and not (t in seen or seen.add(t))]
    out = {}
    if os.path.exists(OUTP):
        try: out = json.load(open(OUTP, encoding="utf-8")).get("scores", {})
        except Exception: pass
    for t in args:
        try:
            r = score(t)
            if r: out[t] = r; print(f"{t:<6} v10影={r['v10']:5.1f}  " + " ".join(f"{k}{v:.0f}" for k, v in r["factors"].items()))
            else: print(f"{t:<6} CIK不明→スキップ")
        except Exception as e:
            print(f"{t:<6} 失敗: {e}")
    os.makedirs("out", exist_ok=True)
    json.dump({"generated": str(date.today()), "spec": "v10-series-shadow-1(V10_SPEC.md)",
               "scores": out}, open(OUTP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {OUTP}（影スコア。正本の採点・合否には不使用——2027-07の較正で新旧を答え合わせ）")
