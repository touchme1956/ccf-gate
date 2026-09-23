#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kessan_check.py v1 — 保有銘柄の四半期決算チェッカー（門の四半期点検・機械抽出係）
使い方: python kessan_check.py            … kanshi_list.json の監視28社のうちADR3社(ASML/TSM/NVMI)を除く25社を自動点検(ADRは§C手動確認)
        python kessan_check.py NVDA MSFT  … 指定銘柄のみ
        （kanshi_list.json が無ければ holdings.json にフォールバック。
          日本株コード=SEC点検不可ゆえ除外→EDINET経路で別途）
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
KANSHI_PATHS = ["./kanshi_list.json", "./ccf/kanshi_list.json",
                "/content/drive/MyDrive/ccf/kanshi_list.json"]
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

# 2026-07-29: 「言葉の出現」でなく「事象の発生」を見るための門番。
#   実測(2026-07-29の28社点検)では 減損 が12社で発火し、中身は全て定型文だった:
#     MSFT  "Application of the goodwill impairment test **requires judgment**…" ＝会計方針の定型
#     GOOGL "**No** impairment loss was recognized upon initial classification…" ＝減損が無かった文
#     IDXX  キャッシュフロー調整表の行項目名（通常はゼロ計上）
#     IDXX(限) "…and patent expiration. **Critical Accounting Estimates**…" ＝リスク列挙
#   28社中12社が鳴る警報は、鳴らないのと同じ（読む側が無視を学習する）。
#   そこで (1)否定文 (2)会計方針・リスク列挙の定型 を近傍で見て落とし、
#   (3)金額を伴う警報カテゴリは近傍に数字が無ければ落とす。
NEGATION = re.compile(
    r"\bno\b[^.]{0,40}$|\bnot\b[^.]{0,40}$|did not recogni[sz]e[^.]{0,40}$"
    r"|\bno\s+(?:goodwill\s+)?impairment|were no impairment|was no impairment"
    r"|did not (?:record|recogni[sz]e|incur)", re.I)
BOILERPLATE = re.compile(
    r"critical accounting|significant accounting polic|requires? (?:judgment|management)"
    r"|application of the .{0,30}test|if the carrying (?:value|amount)"
    r"|we (?:test|assess|evaluate) .{0,30}(?:annually|for impairment)"
    r"|risk factors|reconcile net income"
    # 仮定法＝リスク要因の記述。「起きた」ではなく「起きうる」なので警報にしない。
    #   実測: ANET『…may impact financial results and result in restatements of, or irregularities in,
    #   financial statements』が「誠(restatement)」として発火していた。
    r"|\b(?:may|might|could|would)\s+(?:\w+\s+){0,3}"
    r"(?:impact|result|lead|cause|require|be|adversely|negatively|materially)"
    , re.I)
NEEDS_AMOUNT = {"減損", "指針"}   # 実際に起きたなら金額または率が近傍にあるはず
AMOUNT = re.compile(r"\$\s?[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*(?:million|billion|%)", re.I)


def _is_real(cat, ctx_before, ctx_after):
    """定型文・否定文を落とす。戻り: (採用するか, 落とした理由)"""
    near = ctx_before[-200:] + " " + ctx_after[:200]
    if NEGATION.search(ctx_before[-120:]) or NEGATION.search(ctx_after[:80]):
        return False, "否定文（減損が無かった旨の記述）"
    if BOILERPLATE.search(near):
        return False, "会計方針・リスク列挙の定型文"
    if cat in NEEDS_AMOUNT and not AMOUNT.search(near):
        return False, "金額・率の記載が近傍に無い（実際の計上ではない）"
    return True, ""


def scan(text, width=260, per=2):
    lines, hitcats, dropped = [], [], []
    for cat, pats in ALERTS.items():
        n = 0
        for p in pats:
            for m in re.finditer(p, text, re.I):
                if n >= per: break
                s = max(0, m.start()-width//2)
                frag = re.sub(r"\s+", " ", text[s:s+width])
                ok, why = _is_real(cat, text[max(0, m.start()-300):m.start()],
                                   text[m.end():m.end()+300])
                if not ok:
                    dropped.append(f"[却下:{cat}|{why}] …{frag[:120]}…")
                    continue
                lines.append(f"[{cat}|{p}] …{frag}…")
                n += 1
        if n: hitcats.append(cat)
    if dropped:
        lines.append("")
        lines.append("=== 定型文として却下したヒット（判定には使わない・目視用） ===")
        lines.extend(dropped[:12])
    return lines, hitcats


# ── 減損は「言葉」ではなく「その四半期の実額」で裁く（2026-09-23 ユーザー指示「(b)でやって」）──
#   本文の正規表現は のれんロールフォワード表の列見出し『Accumulated impairment charge』を拾い、
#   MCO で2回（2026-08-20 / 09-23）人を原本へ呼び戻した（当期の減損は0）。KLAC(2026-08-12)も同型。
#   → XBRL（us-gaap と会社独自タグ）の **Impairment を含む流量タグ** の「その四半期ぶん」と、
#     **のれんの累計減損(GoodwillImpairedAccumulatedImpairmentLoss) の前期末からの増分** を見る。
#   ⚠ 取れないことを0と読まない（絶対のルール7）: その四半期末の行が1本も無ければ「XBRLで測れない」として
#     **従来どおり本文の警報で判定する**（鳴る側に倒す）。
#   ⚠ 引当・リストラと合算したタグ（Restructuring…AndAssetImpairment 等）は減損だけを切り出せないので使わない。
IMP_SKIP = ("Accumulated", "Restructuring", "Reversal", "Recover", "Policy", "Tax")

def impairment_xbrl(facts, qend):
    """戻り: (measured, amount_usd, detail[str])。amount はその四半期ぶんの減損の**最大のタグ**（0なら測って0）。
       合計しないのは、AssetImpairmentCharges が ImpairmentOfLongLivedAssets… を内に含むなど
       タグ同士が重なり、足すと二重計上になるため（実測 WST 3.9M ⊃ 0.4M）。内訳は detail に全部出す。"""
    if not qend:
        return False, None, []
    measured, amt, detail = False, 0.0, []
    for ns, tags in (facts.get("facts") or {}).items():
        if ns in ("dei", "srt", "invest"):
            continue
        for k, v in tags.items():
            if "mpairment" not in k:
                continue
            units = v.get("units") or {}
            rows = [r for u, rs in units.items() if u == "USD" for r in rs
                    if str(r.get("form", "")).startswith(("10-Q", "10-K"))]
            if k == "GoodwillImpairedAccumulatedImpairmentLoss":
                inst = sorted({r["end"]: r["val"] for r in rows if not r.get("start")}.items())
                now = dict(inst).get(qend)
                prev = [val for e, val in inst if e < qend]
                if now is not None and prev:
                    measured = True
                    d = now - prev[-1]
                    if d > 0:
                        amt = max(amt, d); detail.append(f"のれん累計減損 +${d/1e6:,.1f}M")
                continue
            if any(x in k for x in IMP_SKIP):
                continue
            flows = [r for r in rows if r.get("start") and r["end"] == qend]
            if not flows:
                continue
            q = [r for r in flows if 60 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 120]
            if q:
                val = max(r["val"] for r in q)
            else:
                # 累計(YTD)しか無い: 同じ期首で一つ前の期末の累計を引く＝この四半期ぶん
                ytd = max(flows, key=lambda r: r["start"])
                prev = [r["val"] for r in rows if r.get("start") == ytd["start"] and r["end"] < qend]
                days = (date.fromisoformat(ytd["end"]) - date.fromisoformat(ytd["start"])).days
                if not prev and days > 120:
                    # 年次の合計しか無い＝この四半期ぶんを切り出せない。0とも実額とも読まない
                    #   （実測 KLAC FY2025末: GoodwillAndIntangibleAssetImpairment 239.1M は前々四半期の再掲だった）
                    continue
                val = ytd["val"] - (max(prev) if prev else 0)
            measured = True
            if val and val > 0:
                amt = max(amt, val); detail.append(f"{k} ${val/1e6:,.1f}M")
    return measured, (amt if measured else None), detail

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

def is_jp(t):
    """日本株コード(4-5桁数字・末尾.Tも許容)。SEC/XBRLでは点検不可＝EDINET経路が要る"""
    return bool(re.fullmatch(r"\d{4,5}(?:\.T)?", t))

def load_holdings():
    """点検対象＝決算監視の正本リスト。優先: kanshi_list.json(監視セット・キーは list)。
       無ければ holdings.json(保有+質80+)。日本株コードはSEC点検不可ゆえ除外し注記する
       （日本株の決算監視は Stage2完走後の EDINET 経路で別途対応）"""
    for p in KANSHI_PATHS:
        if os.path.exists(p):
            cfg = json.load(open(p, encoding="utf-8"))
            # 2026-07-30 是正: make_kanshi.py が書くキーは **"list"**。ここは "tickers" しか
            #   読んでおらず、ファイルが在ってパースも通るのに中身がゼロ件になり、**黙って
            #   holdings.json へフォールバック**していた（画面には正常な行に見える
            #   「監視リスト: ./holdings.json → 保有3…」だけが出る）。実害: 監視33社のうち
            #   3社しか点検されず、ADBE/NVDA/MA/APH/IRMD/TSM 等が一度も見られていなかった。
            #   pin(手で足した銘柄)も対象に含める。旧キー "tickers" は後方互換で残す。
            tk = [t.strip().upper() for t in
                  ((cfg.get("list") or cfg.get("tickers") or []) + (cfg.get("pin") or []))
                  if t.strip()]
            tk = sorted(set(tk))
            us = [t for t in tk if not is_jp(t)]
            jp = [t for t in tk if is_jp(t)]
            if us:
                print(f"監視リスト: {p} → 監視{len(tk)}社（うち米国{len(us)}社を点検）")
                if jp:
                    print(f"  ※日本株{len(jp)}社はSEC点検不可のため除外→EDINET経路へ: {jp}")
                return sorted(set(us))
            # フォールバックは**黙って**行わない——上の事故は「静かな縮退」が原因だった
            print(f"⚠ {p} は在るが点検可能な銘柄が0件（キー list/tickers/pin を確認）→ holdings.json へ退避")
    for p in HOLD_PATHS:
        if os.path.exists(p):
            cfg = json.load(open(p, encoding="utf-8"))
            H = [t.strip().upper() for t in (cfg.get("holdings") or []) if t.strip()]
            E = [t.strip().upper() for t in (cfg.get("elite") or []) if t.strip()]
            us = [t for t in sorted(set(H) | set(E)) if not is_jp(t)]
            if us:
                print(f"監視リスト: {p} → 保有{len(H)} + 質80+{len(E)} = {us}")
                return us
    print("kanshi_list.json / holdings.json が見つからない → 引数で銘柄を指定して実行")
    return []

def check(t):
    if t in ADR_MANUAL:
        # 既知の20-F/6-K発行体は採取(companyfacts)を試みる前に手動確認へ回す＝通信の節約。
        # 列挙外の20-F社は下の構造的検問（10-Q/10-K系列が空なら健全と書かない）が捕まえる。
        verdict = "要審査: 機械抽出不可(ADR=20-F/6-K)→kessan_checklist §Cの手動確認へ"
        os.makedirs(OUT, exist_ok=True)
        with open(f"{OUT}/{t}_qcheck.txt", "w", encoding="utf-8") as f:
            f.write(f"{t} 点検日 {date.today()}\n判定: {verdict}\n"
                    "(10-Q/10-Kを提出しないため売上YoY・営利率・警報スキャンの機械値は算出できない)\n")
        print(f"  {t:<6} → {verdict}")
        return verdict
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
    # 2026-08-04是正(A1): **10-Q/10-K系列が空なら健全と書かない。** 従来はADR_MANUALの
    #   ハードコード3社(ASML/TSM/NVMI)しか止めておらず、列挙外の20-F発行体(実測 SAP/RACE/RELX)は
    #   全項目None・スキャン0件のまま素通りして「異常なし(機械判定)」という**偽の健全宣言**が
    #   ファイルに残っていた。列挙は必ず漏れるので、**測れなかったこと自体を構造で検出する**——
    #   四半期系列が1本も取れず10-Qも走査できなかったら、それは「異常なし」ではなく「点検不能」。
    if not rev and not op and q10 is None:
        verdict = ("要審査: 点検不能（10-Q/10-K系列なし＝20-F/40-F発行体の可能性。手動確認要）")
        os.makedirs(OUT, exist_ok=True)
        with open(f"{OUT}/{t}_qcheck.txt", "w", encoding="utf-8") as f:
            f.write(f"{t} 点検日 {date.today()}\n"
                    f"新規提出({SINCE_DAYS}日以内): " + "; ".join(f"{a} {b}" for a, b, _ in fils) + "\n"
                    f"判定: {verdict}\n"
                    "(10-Q/10-Kの四半期系列が1本も取れず警報スキャンも実行できていない。\n"
                    " 20-F/6-K発行体なら kessan_checklist §C の手動確認へ——健全と判定したのではない)\n")
        print(f"  {t:<6} → {verdict}")
        return verdict
    flags = []
    if yoy is not None and yoy < -5: flags.append(f"売上YoY {yoy}%")
    if opm_d is not None and opm_d < -3: flags.append(f"営利率 前年比{opm_d}pt")
    # 集(顧客集中)は毎四半期再掲される定型注記に当たるため、前回点検に無かった「新規出現」だけを警報化する。
    # (常時フラグ化すると監視銘柄の約半数が恒久的に要審査となり、本物の集中悪化が埋もれる。スニペット表示は従来どおり維持)
    prev_cats = set()
    try:
        with open(f"{OUT}/{t}_qcheck.txt", encoding="utf-8") as pf:
            prev_cats = set(re.findall(r"^\[(誠|限|集|指針|減損|退任|吉S字|吉流通)\|", pf.read(), re.M))
    except OSError:
        pass
    # 減損は実額で裁く（上の impairment_xbrl）。測れた四半期は本文のヒットを判定に使わない
    imp_note = ""
    if True:
        m_, a_, det = impairment_xbrl(facts, latest)
        if m_:
            if a_ and a_ > 0:
                if "減損" not in cats: cats.append("減損")
                imp_note = "（XBRL実額 " + " / ".join(det) + "）"
            elif "減損" in cats:
                cats = [c for c in cats if c != "減損"]
                snip.append("")
                snip.append(f"※減損の本文ヒットは判定に使っていない——XBRLで四半期末{latest}の減損額が0と測れたため（列見出し・定型文の空振り）")
        elif "減損" in cats:
            imp_note = "（XBRLで測れず本文で判定）"
    for c in cats:
        if c == "集":
            if "集" not in prev_cats: flags.append("警報:集(新規出現)")
        elif c == "減損": flags.append(f"警報:減損{imp_note}")
        elif c in ("誠","限","指針","退任"): flags.append(f"警報:{c}")
    yoshi = [c for c in cats if c.startswith("吉")]
    verdict = "要審査: " + " / ".join(flags) if flags else "異常なし(機械判定)"
    if yoshi:
        verdict += "  ☀吉報:" + "/".join(yoshi) + "（第二S字・流通の兆候→原文スニペット確認）"
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{t}_qcheck.txt", "w", encoding="utf-8") as f:
        f.write(f"{t} 点検日 {date.today()}  四半期末 {latest}\n"
                f"売上YoY: {yoy}%  営業利益率の前年同期差: {opm_d}pt\n"
                f"新規提出({SINCE_DAYS}日以内): " + "; ".join(f"{a} {b}" for a,b,_ in fils) + "\n"
                f"判定: {verdict}\n\n=== 警報スニペット ===\n" + "\n".join(snip))
    print(f"  {t:<6} YoY {str(yoy)+'%':>7}  営利差 {str(opm_d)+'pt':>7}  → {verdict}")
    return verdict

# ADR(外国私募発行体)の**既知例のヒント**: 10-Q/10-Kを出さず20-F/6-Kのため機械抽出が効かない。
# 2026-08-04是正(A1): このハードコードは通信節約の早期スキップに格下げした。列挙外の20-F社は
# check() 内の構造的検問（10-Q/10-K系列が空なら「点検不能・要審査」）が捕まえる——列挙は必ず漏れる。
ADR_MANUAL = {"ASML", "TSM", "NVMI"}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,7}", a)]
    targets = args or load_holdings()
    if not args:
        adr = [t for t in targets if t in ADR_MANUAL]
        if adr:
            print(f"※ADR {len(adr)}社は10-Q機械抽出不可のため除外→§Cの手動確認へ: {adr}")
            targets = [t for t in targets if t not in ADR_MANUAL]
    print(f"=== 四半期点検 {date.today()} ===")
    for t in targets:
        try: check(t)
        except Exception as e: print(f"  {t:<6} 失敗 → {e}")
    print("要審査が出た銘柄は、門の依頼文ボタンで門2再審査へ。ADR(ASML/TSM/NVMI)は決算リリース/6-Kを手動確認。")
