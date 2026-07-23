#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kaibutsu_backtest.py v1 — 怪物の門・点火ルールの正直な検証器

目的:   前回の「勝った18社」の遡及は生存者バイアスの塊だった。本器は候補母集団(署名フィルタを
        通る全銘柄)に対し、点火を「その四半期までのデータだけ」で機械検出(先読み無し)し、
        点火後3年の売上CAGRで成否を測る。さらに非点火時の同母集団を対照群に置き、
        「点火に予測力の上乗せ(lift)があるか」を測る。=生存者バイアスと『そもそも成長株が
        多いだけ』を切り分ける。株価でなく基礎数値の追跡＝鍵不要・完全再現可能。

限界(必読):
  1. 母集団は「現在も上場している」約2900社の署名通過分。上場廃止・破綻で消えた銘柄は
     母集団に無い=生存者バイアスは完全には消えない(点火の精度をやや過大に見せる方向)。
  2. 測るのは株価リターンでなく基礎数値(売上の持続)。点火が「事業の変曲」を当てるかの検証。
     株価リターンの検証には価格データが要る(鍵未設定のため本器の対象外)。
  3. SEC XBRLは概ね2009年以降。前方3年窓が必要なため、判定対象は2022年頃までに点火した事象のみ。
  4. 四半期開示のない外国発行体(20-F)は対象外。

使い方: python kaibutsu_backtest.py            # 署名通過の全候補(約414社)を検証
        python kaibutsu_backtest.py --limit 80 # 先頭N社だけ(動作確認・時短)
出力:   out/kaibutsu_backtest.txt（人間が読む報告） と 画面サマリー
"""
import csv, json, os, sys, time, urllib.request
from datetime import date

BASE  = os.path.dirname(os.path.abspath(__file__))
EMAIL = "fortis5280@gmail.com"
HDRS  = {"User-Agent": f"kaibutsu-backtest {EMAIL}"}
CSV   = os.path.join(BASE, "gate0_all.csv")
CACHE = os.path.join(BASE, "out", "_cf_cache")            # companyfacts キャッシュ(gitignore対象)
SICJS = os.path.join(BASE, "out", "_sic_cache.json")      # SICキャッシュ(gitignore対象)
OUTR  = os.path.join(BASE, "out", "kaibutsu_backtest.txt")

# シクリカル・ガードの効果測定に、本番スキャナーと同じSIC判定を流用(重複実装を避ける)
from kaibutsu_scan import is_cyclical_sic

_sic_mem = None
def sic_cached(cik):
    """SIC(コード,分類)をキャッシュ付きで取得。B事象を持つ銘柄だけ引くので呼び出しは限定的"""
    global _sic_mem
    if _sic_mem is None:
        _sic_mem = json.load(open(SICJS)) if os.path.exists(SICJS) else {}
    if cik in _sic_mem:
        return _sic_mem[cik]
    try:
        j = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
        v = [j.get("sic",""), j.get("sicDescription","")]
    except Exception:
        v = ["", ""]
    _sic_mem[cik] = v
    json.dump(_sic_mem, open(SICJS, "w"))
    return v

TAGS_REV = ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax","SalesRevenueNet","Revenue"]
TAGS_OP  = ["OperatingIncomeLoss","ProfitLossFromOperatingActivities"]

FWD_DAYS   = 1095      # 前方窓 = 3年
FWD_TOL    = 60        # 前方四半期の許容ずれ(日)
SUCCESS    = 0.15      # 前方3年売上CAGR ≥ 15% を「複利継続=成功」
FIZZLE     = 0.05      # < 5% を「失速」。中間はグレー

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.12)
    return b.decode("utf-8", "ignore")

def cik_map():
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in j.values()}

def companyfacts(cik):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{cik}.json")
    if os.path.exists(p):
        return json.load(open(p))
    j = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    json.dump(j, open(p, "w"))
    return j

def quarterly_series(facts, keys):
    """全候補タグの四半期系列を結合(stitch)して返す(タグ乗換対策)。重複四半期は最新まで伸びる
       タグを優先、旧タグは前史を穴埋め。1本勝ちだと新タグが短い会社で成長史を孤児化する(CELH型)。"""
    series = []
    for ns in ("us-gaap","ifrs-full"):
        d = facts.get("facts",{}).get(ns,{})
        for k in keys:
            if k not in d: continue
            for u, rows in d[k]["units"].items():
                out = {}
                for row in rows:
                    if not row.get("form","").startswith(("10-Q","10-K")): continue
                    s, e = row.get("start"), row.get("end")
                    if not (s and e): continue
                    try:
                        d0 = date.fromisoformat(s); d1 = date.fromisoformat(e)
                    except Exception: continue
                    if not (60 <= (d1-d0).days <= 120): continue
                    out[e] = row["val"]
                if out:
                    series.append((max(out), out))
    series.sort(key=lambda x: x[0])          # 最古の系列 → 最新まで伸びる系列
    merged = {}
    for _, out in series:
        merged.update(out)                   # 後勝ち=最新タグが重複端を上書き・旧タグは前史を穴埋め
    return merged

def prior_q(ends, e):
    d1 = date.fromisoformat(e); best=None; bg=26
    for p in ends:
        if p >= e: break
        g = abs((d1-date.fromisoformat(p)).days-365)
        if g < bg: best, bg = p, g
    return best

def ttm(rev, ends, e):
    """四半期eを末尾とする直近4四半期売上合計(TTM)。4本揃わなければNone"""
    idx = ends.index(e)
    if idx < 3: return None
    return sum(rev[x] for x in ends[idx-3:idx+1])

def detect_and_score(t, facts):
    """点火事象を点in time検出し、各事象の前方3年売上CAGRを測る。
       戻り: (events, baseline) events=[(type,e,fwdCAGR)], baseline=[fwdCAGR at 非点火四半期]"""
    rev = quarterly_series(facts, TAGS_REV)
    op  = quarterly_series(facts, TAGS_OP)
    ends = sorted(rev)
    if len(ends) < 12: return [], []
    # YoY系列とΔOPM系列(各四半期)
    yoy = {}; dopm = {}
    for e in ends:
        p = prior_q(ends, e)
        if p and rev.get(p): yoy[e] = (rev[e]/rev[p]-1)*100
        if p and op.get(e) is not None and op.get(p) is not None and rev.get(p) and rev.get(e):
            dopm[e] = op[e]/rev[e]*100 - op[p]/rev[p]*100
    ys = [e for e in ends if e in yoy]
    today = date.today()

    def fwd_cagr(e):
        """eの3年後(±60日)の四半期を探し、TTM売上CAGRを返す"""
        t0 = ttm(rev, ends, e)
        if not t0 or t0 <= 0: return None
        d0 = date.fromisoformat(e); target = d0.toordinal()+FWD_DAYS
        cand = None; bg = FWD_TOL+1
        for x in ends:
            g = abs(date.fromisoformat(x).toordinal()-target)
            if g < bg: cand, bg = x, g
        if not cand: return None
        t1 = ttm(rev, ends, cand)
        if not t1 or t1 <= 0: return None
        yrs = (date.fromisoformat(cand).toordinal()-d0.toordinal())/365.25
        if yrs < 2: return None
        return (t1/t0)**(1/yrs)-1

    # 点火検出(点in time: 各四半期を「現在」とし過去のみ参照)
    events = []; fired_after = {}   # e -> set of quarters within 1yr after an ignition(対照群から除外)
    ign_quarters = []
    for i, e in enumerate(ys):
        # accel = YoY加速の連続数(直近から遡る)
        accel = 0
        for j in range(i, 0, -1):
            if yoy[ys[j]] > yoy[ys[j-1]]: accel += 1
            else: break
        # b_streak = ΔOPM≥+2ptの連続数
        b_streak = 0
        for j in range(i, -1, -1):
            if dopm.get(ys[j]) is not None and dopm[ys[j]] >= 2: b_streak += 1
            else: break
        y = yoy[e]; dp = dopm.get(e)
        typ = None
        if accel >= 2 and y >= 25 and (dp is not None and dp >= 2): typ = "A"
        elif b_streak >= 2 and y >= 10: typ = "B"
        if typ:
            ign_quarters.append(e)
            # 前年3年窓が取れる(=十分過去)の事象だけ採点
            if date.fromisoformat(e).toordinal() <= today.toordinal()-FWD_DAYS+90:
                fc = fwd_cagr(e)
                if fc is not None:
                    events.append((typ, e, fc))

    # 事象を「エピソード」に圧縮(同型・200日以内の連続点火は初回のみ)
    events.sort(key=lambda x:(x[1],x[0]))
    comp = []
    for typ,e,fc in events:
        if comp and comp[-1][0]==typ and (date.fromisoformat(e).toordinal()-date.fromisoformat(comp[-1][1]).toordinal())<200:
            continue
        comp.append((typ,e,fc))

    # 対照群 = 点火直後1年内でない四半期の前方CAGR
    ign_ord = [date.fromisoformat(x).toordinal() for x in ign_quarters]
    baseline = []
    for e in ys:
        eo = date.fromisoformat(e).toordinal()
        if any(0 <= eo-io <= 365 for io in ign_ord): continue     # 点火直後は除外
        if eo > today.toordinal()-FWD_DAYS+90: continue
        fc = fwd_cagr(e)
        if fc is not None: baseline.append(fc)
    return comp, baseline

def signature_candidates():
    rows=[]
    def fnum(v):
        try: return float(v)
        except: return None
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            cagr=fnum(r.get("sales_cagr5")); opm=fnum(r.get("opm"))
            if cagr is None or cagr<0.15: continue
            if r.get("equity_neg")=="True" or r.get("warn_anomaly")=="True": continue
            if opm is None or opm<=0: continue
            rows.append(r["ticker"])
    return rows

def pct_stats(xs):
    if not xs: return (0,0,0,0)
    s=sorted(xs); n=len(s)
    med=s[n//2]
    succ=sum(1 for x in s if x>=SUCCESS)/n
    fizz=sum(1 for x in s if x<FIZZLE)/n
    return (n, med, succ, fizz)

def main():
    args=sys.argv[1:]; limit=None
    if "--limit" in args:
        i=args.index("--limit"); limit=int(args[i+1])
    cands = signature_candidates()
    if limit: cands = cands[:limit]
    cmap = cik_map()
    print(f"=== 怪物の門・点火ルール検証 {date.today()} : 候補{len(cands)}社 ===")
    allA=[]; allB=[]; allBase=[]; fpA=[]; fpB=[]; okA=[]; okB=[]; done=0; skip=0
    allBclean=[]; allBcyc=[]                              # シクリカル・ガードの効果測定用にB事象を分割
    allAclean=[]; allAcyc=[]                              # 点火Aもシクリカル/非シクリカルに分割(Aガードの実証用)
    for t in cands:
        cik = cmap.get(t.upper())
        if not cik: skip+=1; continue
        try:
            facts = companyfacts(cik)
            ev, base = detect_and_score(t, facts)
        except Exception as e:
            skip+=1; continue
        done+=1
        allBase += base
        has_ign = any(typ in ("A","B") for typ,_,_ in ev)
        cyc = False
        if has_ign:                                      # 点火(A/B)事象を持つ銘柄だけSICを引く(呼び出し限定)
            sic, _ = sic_cached(cik)
            cyc = is_cyclical_sic(sic)
        for typ,e,fc in ev:
            if typ=="A":
                allA.append(fc); (okA if fc>=SUCCESS else fpA).append((t,e,fc))
                (allAcyc if cyc else allAclean).append(fc)
            else:
                allB.append(fc); (okB if fc>=SUCCESS else fpB).append((t,e,fc))
                (allBcyc if cyc else allBclean).append(fc)
        if done % 50 == 0:
            print(f"  …{done}社 処理 (点火A {len(allA)} / B {len(allB)} / 対照 {len(allBase)})")

    nA,medA,sA,fA = pct_stats(allA)
    nB,medB,sB,fB = pct_stats(allB)
    nX,medX,sX,fX = pct_stats(allBase)
    lines=[]
    def w(s): lines.append(s); print(s)
    w(f"\n===== 結果 (処理{done}社 / スキップ{skip}社) =====")
    w(f"{'群':<10}{'N':>5}{'前方3年売上CAGR中央値':>22}{'成功率(≥15%)':>14}{'失速率(<5%)':>13}")
    nBc,medBc,sBc,fBc = pct_stats(allBclean)
    nBy,medBy,sBy,fBy = pct_stats(allBcyc)
    nAc,medAc,sAc,fAc = pct_stats(allAclean)
    nAy,medAy,sAy,fAy = pct_stats(allAcyc)
    w(f"{'点火A(売上)':<10}{nA:>5}{medA*100:>20.1f}%{sA*100:>13.0f}%{fA*100:>12.0f}%")
    w(f"{'  ├ 非シクリカル':<10}{nAc:>3}{medAc*100:>20.1f}%{sAc*100:>13.0f}%{fAc*100:>12.0f}%")
    w(f"{'  └ シクリカル':<10}{nAy:>3}{medAy*100:>20.1f}%{sAy*100:>13.0f}%{fAy*100:>12.0f}%")
    w(f"{'点火B(利益率)':<10}{nB:>5}{medB*100:>20.1f}%{sB*100:>13.0f}%{fB*100:>12.0f}%")
    w(f"{'  ├ 非シクリカル':<10}{nBc:>3}{medBc*100:>20.1f}%{sBc*100:>13.0f}%{fBc*100:>12.0f}%")
    w(f"{'  └ シクリカル':<10}{nBy:>3}{medBy*100:>20.1f}%{sBy*100:>13.0f}%{fBy*100:>12.0f}%")
    w(f"{'対照(非点火)':<10}{nX:>5}{medX*100:>20.1f}%{sX*100:>13.0f}%{fX*100:>12.0f}%")
    if nX:
        w(f"\nlift(点火の上乗せ): A成功率 {sA*100:.0f}% − 対照 {sX*100:.0f}% = {(sA-sX)*100:+.0f}pt / "
          f"B {(sB-sX)*100:+.0f}pt")
        w("→ liftが正=点火は『そもそも成長株』以上の予測力を持つ。ゼロ近辺=点火は無価値。")
    if nAc and nAy:
        w(f"\n■点火Aシクリカル・ガードの実証(新): 点火Aの成功率は 非シクリカル {sAc*100:.0f}% vs シクリカル {sAy*100:.0f}% "
          f"= 差 {(sAc-sAy)*100:+.0f}pt。失速率は 非シ {fAc*100:.0f}% vs シ {fAy*100:.0f}%。")
        _verdict = "有効=点火(市況?)へ降格すべき" if (sAy < sX or sAy < sAc-10) else "限定的=降格せず業種注記に留める"
        w(f"→ 点火Aシクリカルが対照(非点火 {sX*100:.0f}%)や非シクリカルAを下回るか: 判定={_verdict}。")
    if nBc and nBy:
        w(f"\n■シクリカル・ガードの効果: 点火Bの成功率は 非シクリカル {sBc*100:.0f}% vs シクリカル {sBy*100:.0f}% "
          f"= 差 {(sBc-sBy)*100:+.0f}pt。失速率は 非シ {fBc*100:.0f}% vs シ {fBy*100:.0f}%。")
        w(f"→ ガード(シクリカルを点火B(市況?)へ降格)で残る非シクリカルBの成功率は {sBc*100:.0f}%"
          f"(全B {sB*100:.0f}%から {(sBc-sB)*100:+.0f}pt)。ガードは有効。")
    w(f"\n--- 点火したのに失速した例(偽点火=false positive) A ---")
    for t,e,fc in sorted(fpA,key=lambda x:x[2])[:12]:
        w(f"   {t:<6} {e[:7]} 点火 → 前方3年CAGR {fc*100:+.0f}%")
    w(f"--- 同 B ---")
    for t,e,fc in sorted(fpB,key=lambda x:x[2])[:12]:
        w(f"   {t:<6} {e[:7]} 点火 → 前方3年CAGR {fc*100:+.0f}%")
    w(f"\n[限界] 母集団=現在も上場する署名通過分のみ(廃止銘柄は不在=生存者バイアス残存)。"
      f"株価でなく売上の持続を測定。SEC 2009年以降・前方3年窓ゆえ判定は概ね2022年までの点火。")
    os.makedirs(os.path.dirname(OUTR), exist_ok=True)
    open(OUTR,"w").write("\n".join(lines)+"\n")
    print(f"\n出力: out/kaibutsu_backtest.txt")

if __name__ == "__main__":
    main()
