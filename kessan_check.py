#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kessan_check.py v1 — 保有銘柄の四半期決算チェッカー（門の四半期点検・機械抽出係）
使い方: python kessan_check.py            … holdings.json の保有銘柄を点検
        python kessan_check.py NVDA MSFT  … 指定銘柄のみ
出力:   out/kessan/{T}_qcheck.txt（数値+警報スニペット） と 画面のサマリー表
判定:   売上YoY<-5% / 営業利益率が前年同期比-3pt超の悪化 / 誠・限・ガイダンス系の警報ヒット → 要審査
吉報:   新セグメント開示・大手流通契約のキーワード(吉S字/吉流通)は警報でなく「☀吉報」として表示。
        怪物列伝の分析より、最大の上昇は保有銘柄の「第二S字」から始まることが多い(iPhone/AWS/HOKA型)
注意:   機械判定は一次スクリーニング。最終判断は門2審査（依頼文）で行う。
        v1はClaude Code上での初回実行で動作確認すること（ここでは構文+ロジックのみ検証済）。
"""
import json, re, sys, time, os, urllib.request
from datetime import date

EMAIL = "fortis5280@gmail.com"
SINCE_DAYS = 100                       # この日数以内の新規提出だけを「未点検」とみなす
HOLD_PATHS = ["./holdings.json", "./ccf/holdings.json",
              "/content/drive/MyDrive/ccf/holdings.json"]
OUT = "out/kessan"
HDRS = {"User-Agent": f"hachimon-kessan {EMAIL}"}

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)
    return b.decode("utf-8", "ignore")

def cik_of(ticker):
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    for v in j.values():
        if v["ticker"].upper() == ticker.upper():
            return str(v["cik_str"]).zfill(10)
    raise SystemExit(f"CIK不明: {ticker}")

TAGS_REV = ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueNet","Revenue"]
TAGS_OP  = ["OperatingIncomeLoss","ProfitLossFromOperatingActivities"]

def quarterly_series(facts, keys):
    """10-Q/10-K行から四半期(60-120日)の {end_date: val} を作る。
       タグ乗換(例: Revenues→RevenueFromContractWithCustomer)で古い系列だけが残る銘柄が
       多数あるため、最初のヒットではなく「最新の四半期末が最も新しい系列」を採用する"""
    best = {}
    for ns in ("us-gaap","ifrs-full"):
        d = facts.get("facts",{}).get(ns,{})
        for k in keys:
            if k in d:
                for u, rows in d[k]["units"].items():
                    out = {}
                    for row in rows:
                        if not row.get("form","").startswith(("10-Q","10-K")): continue
                        s, e = row.get("start"), row.get("end")
                        if not (s and e): continue
                        try:
                            d0 = date.fromisoformat(s); d1 = date.fromisoformat(e)
                        except Exception: continue
                        days = (d1-d0).days
                        if not (60 <= days <= 120): continue   # 四半期のみ
                        out[e] = row["val"]
                    if out and (not best or max(out) > max(best)):
                        best = out
    return best

def yoy_pair(q):
    """最新四半期と、その約1年前(±25日)の四半期を返す"""
    if not q: return None, None, None
    ends = sorted(q)
    latest = ends[-1]
    ld = date.fromisoformat(latest)
    best = None
    for e in ends[:-1]:
        gap = abs((ld - date.fromisoformat(e)).days - 365)
        if gap <= 25 and (best is None or gap < best[1]):
            best = (e, gap)
    return latest, (best[0] if best else None), q

ALERTS = {
 "誠": [r"material weakness", r"was not effective", r"restatement"],
 "限": [r"loss of exclusivity", r"patent[s]? (?:expir|protection)", r"concession[s]? .{0,60}(?:expir|term)"],
 "集": [r"largest customer", r"customers? accounted", r"single[- ]source", r"sole suppli"],
 "指針": [r"withdraw.{0,30}guidance", r"suspend.{0,30}guidance", r"lower(?:ed|ing)? .{0,20}guidance", r"revis.{0,20}guidance .{0,20}down"],
 "減損": [r"goodwill impairment", r"impairment (?:charge|loss)"],
 "退任": [r"(?:chief executive|chief financial) officer .{0,40}(?:resign|depart|step(?:ped|s)? down)"],
 # 吉報（警報でなく好機の兆候。怪物列伝の分析より: 最大の上昇は「第二S字」=新セグメント/
 # 大手流通契約から始まった。AAPL iPhone・AMZN AWS・DECK HOKA・MNST×コカコーラ・CELH×ペプシ型）
 "吉S字": [r"new (?:reportable |operating )?segment", r"(?:began|commenced|will begin) report(?:ing)? .{0,40}segment",
           r"realign.{0,40}segment"],
 "吉流通": [r"distribution agreement", r"(?:exclusive|strategic|global) distribution",
            r"(?:co[- ]?marketing|commercialization) agreement"],
}

def strip_html(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S|re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;?", " ", h); h = re.sub(r"&amp;", "&", h)
    return re.sub(r"[ \t]{2,}", " ", h)

def scan(text, width=260, per=2):
    lines, hitcats = [], []
    for cat, pats in ALERTS.items():
        n = 0
        for p in pats:
            for m in re.finditer(p, text, re.I):
                if n >= per: break
                s = max(0, m.start()-width//2)
                frag = re.sub(r"\s+", " ", text[s:s+width])
                lines.append(f"[{cat}|{p}] …{frag}…")
                n += 1
        if n: hitcats.append(cat)
    return lines, hitcats

def recent_filings(cik, since_days):
    j = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    r = j["filings"]["recent"]
    cut = (date.today().toordinal() - since_days)
    out = []
    for i, f in enumerate(r["form"]):
        try:
            fd = date.fromisoformat(r["filingDate"][i])
        except Exception: continue
        if fd.toordinal() < cut: continue
        if f in ("10-Q","10-K","20-F") or f.startswith("8-K"):
            acc = r["accessionNumber"][i].replace("-","")
            doc = r["primaryDocument"][i]
            out.append((f, r["filingDate"][i],
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"))
    return out

def load_holdings():
    for p in HOLD_PATHS:
        if os.path.exists(p):
            cfg = json.load(open(p, encoding="utf-8"))
            H = [t.strip().upper() for t in (cfg.get("holdings") or []) if t.strip()]
            E = [t.strip().upper() for t in (cfg.get("elite") or []) if t.strip()]
            tg = sorted(set(H) | set(E))
            if tg:
                print(f"監視リスト: {p} → 保有{len(H)} + 質80+{len(E)} = {tg}")
                return tg
    print("holdings.json が見つからない → 引数で銘柄を指定して実行")
    return []

def check(t):
    cik = cik_of(t)
    facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    rev = quarterly_series(facts, TAGS_REV)
    op  = quarterly_series(facts, TAGS_OP)
    latest, prior, _ = yoy_pair(rev)
    yoy = opm_d = None
    if latest and prior and rev.get(prior):
        yoy = round((rev[latest]/rev[prior]-1)*100, 1)
        if op.get(latest) is not None and op.get(prior) is not None:
            opm_d = round(op[latest]/rev[latest]*100 - op[prior]/rev[prior]*100, 1)
    fils = recent_filings(cik, SINCE_DAYS)
    snip, cats = [], []
    q10 = next((u for f_, d_, u in fils if f_ == "10-Q"), None)
    if q10:
        s, c = scan(strip_html(get(q10)))
        snip, cats = s, c
    flags = []
    if yoy is not None and yoy < -5: flags.append(f"売上YoY {yoy}%")
    if opm_d is not None and opm_d < -3: flags.append(f"営利率 前年比{opm_d}pt")
    for c in cats:
        if c in ("誠","限","指針","減損","退任"): flags.append(f"警報:{c}")
    yoshi = [c for c in cats if c.startswith("吉")]
    verdict = "要審査: " + " / ".join(flags) if flags else "異常なし(機械判定)"
    if yoshi:
        verdict += "  ☀吉報:" + "/".join(yoshi) + "（第二S字・流通の兆候→原文スニペット確認）"
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{t}_qcheck.txt","w") as f:
        f.write(f"{t} 点検日 {date.today()}  四半期末 {latest}\n"
                f"売上YoY: {yoy}%  営業利益率の前年同期差: {opm_d}pt\n"
                f"新規提出({SINCE_DAYS}日以内): " + "; ".join(f"{a} {b}" for a,b,_ in fils) + "\n"
                f"判定: {verdict}\n\n=== 警報スニペット ===\n" + "\n".join(snip))
    print(f"  {t:<6} YoY {str(yoy)+'%':>7}  営利差 {str(opm_d)+'pt':>7}  → {verdict}")
    return verdict

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,7}", a)]
    targets = args or load_holdings()
    print(f"=== 四半期点検 {date.today()} ===")
    for t in targets:
        try: check(t)
        except Exception as e: print(f"  {t:<6} 失敗 → {e}")
    print("要審査が出た銘柄は、門の依頼文ボタンで門2再審査へ。")
