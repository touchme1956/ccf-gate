#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kaibutsu_scan.py v1 — 怪物の門・点火スキャナー（NVIDIA型の複利怪物を最速で待ち伏せる係）

思想:   「次のNVIDIAを事前に名指しする方法」は存在しない。存在するのは、
        ①過去の怪物に共通する初期署名（超成長の持続×資本効率×営業レバレッジ）で候補を絞り、
        ②点火（四半期売上YoYの加速）を法定開示と同じ速度で機械検知することだけ。
        法定開示より速い検知はインサイダーだけ。ゆえに本器の四半期サイクルが「最速」である。
        詳細な掟は kaibutsu.html（怪物の門）に全文。

使い方: python kaibutsu_scan.py              # gate0_all.csv から署名上位40社 → SEC四半期で点火検知
        python kaibutsu_scan.py --top 60     # 候補数を変える
        python kaibutsu_scan.py --max-rev 5  # 年商5B USD以下（中型小型）だけを行列に残す
        python kaibutsu_scan.py NVDA CRWD    # 指定銘柄のみ点火検知（署名フィルタを飛ばす）
規模:   直近4四半期売上の合計（年商）で 微<$0.3B / 小<$1.5B / 中<$8B / 大≥$8B に分類。
        同じ判定内では小さい順に並ぶ（怪物は小さいうちに拾うのが本旨）。時価総額でなく
        年商基準なのは、価格APIなしで全自動にするため。非USD決算は現地通貨表記。
出力:   kaibutsu_queue.json（点火→点火B→くすぶり→待機の順・審査待ち）
        out/kaibutsu_report.txt（人間が読む報告）
判定:   点火     = YoY加速2連続 ∧ 最新YoY ≥ +25% ∧ 営業利益率 前年同期比 ≥ +2pt（売上加速型・NVIDIA型）
        点火B    = 営業利益率 前年同期比+2pt以上が2四半期連続 ∧ 最新YoY ≥ +10%（利益率階段型・
                   Amazon2015/Microsoft2017/Axon/Celsius2019型。18社遡及テストで実証）
        くすぶり = YoY加速∧YoY≥+15%、または 営利率+2ptが1四半期（B予鳴り）∧YoY≥+10%
        待機     = それ以外
⚑検死フラグ(v2 精度強化): 見かけの点火を注記(降格でなく人手確認)。市況注意=点火Aシクリカル /
        base?=YoY>150%(小ベース・M&A) / 段差?=QoQ+40%超(合併/一時) / 微小流動性=年商<$0.3B /
        営利差過大=ΔOPM>20pt(一時益)。※点火Aシクリカルはバックテスト実証(成功率75%>対照54%)で降格せず注記のみ
集団発火: 同一走査で点火(A+B)が有効データの30%以上を占めたら「マクロ点火の疑い」を報告に明記
        （2021年コロナ反動型＝ベータの一斉発火をアルファと誤認しないための割引）
注意:   点火銘柄は「買い」ではない。門Ω（index.html）の審査に回し、サイズは門X
        （chomirai.html）の無知の枠（資本の5〜10%・全損前提・¼ケリー上限）で縛ること。
        SECレート制限(10req/s)遵守。User-Agentメール設定済み。
"""
import csv, json, os, re, sys, time, urllib.request
from datetime import date

BASE  = os.path.dirname(os.path.abspath(__file__))
EMAIL = "fortis5280@gmail.com"
HDRS  = {"User-Agent": f"kaibutsu-gate {EMAIL}"}
CSV   = os.path.join(BASE, "gate0_all.csv")
OUTQ  = os.path.join(BASE, "kaibutsu_queue.json")
OUTR  = os.path.join(BASE, "out", "kaibutsu_report.txt")
KILLJS = os.path.join(BASE, "kaibutsu_killlist.json")     # 確定死足切り: 門Ω審査で構造的キル確認済=◆から除外

TAGS_REV = ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax","SalesRevenueNet","Revenue"]
TAGS_OP  = ["OperatingIncomeLoss","ProfitLossFromOperatingActivities"]

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)
    return b.decode("utf-8", "ignore")

# ---------------- 段1: 怪物署名（gate0_all.csv・年次） ----------------
def fnum(v):
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return None

def signature_rank(top_n):
    """怪物の初期署名で全母集団を採点し上位を返す。
       署名 = 超成長の持続(5年CAGR) × 資本効率(ROIC) × 利益体質(OPM) × FCF転換。
       除外 = 債務超過・会計異常。成長が全ての起点なので CAGR15%未満は署名なし。"""
    rows = []
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            cagr = fnum(r.get("sales_cagr5")); opm = fnum(r.get("opm"))
            roic = fnum(r.get("roic_ex_latest")) or fnum(r.get("roic_latest"))
            fcfc = fnum(r.get("fcf_conv_5y"))
            if cagr is None or cagr < 0.15:            continue   # 超成長が起点
            if r.get("equity_neg") == "True":          continue   # 債務超過
            if r.get("warn_anomaly") == "True":        continue   # 会計異常
            if opm is None or opm <= 0:                continue   # 赤字体質は門0の病名行き
            # 署名点: 各項を0-1に圧縮して加重（成長40 / ROIC25 / OPM20 / FCF転換15）
            s_g = min(cagr / 0.40, 1.0)
            s_r = min(max(roic or 0, 0) / 0.30, 1.0)
            s_m = min(opm / 0.30, 1.0)
            s_f = min(max(fcfc or 0, 0) / 1.0, 1.0)
            sig = round(100 * (0.40*s_g + 0.25*s_r + 0.20*s_m + 0.15*s_f), 1)
            rows.append({"ticker": r["ticker"], "name": r.get("name",""),
                         "sig": sig, "cagr5": round(cagr*100,1),
                         "roic": round((roic or 0)*100,1), "opm": round(opm*100,1),
                         "ccy": r.get("ccy",""), "byomei": r.get("byomei","")})
    rows.sort(key=lambda x: -x["sig"])
    return rows[:top_n]

# ---------------- 段2: 点火検知（SEC・四半期） ----------------
def cik_map():
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in j.values()}

def sic_of(cik):
    """SEC submissionsからSICコードと分類名を取得。点火が出た銘柄だけ引く(呼び出し最小)。
       B降格の信頼性のため一時失敗は1回リトライ"""
    for attempt in range(2):
        try:
            j = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            return j.get("sic",""), j.get("sicDescription","")
        except Exception:
            if attempt == 0: time.sleep(0.5); continue
            raise

def is_cyclical_sic(sic):
    """商品市況・金利で利益率が振れるシクリカル。利益率階段型(点火B)の偽点火が集中する型。
       検証(kaibutsu_backtest)で点火Bの失速例がこの群に固まった: 石油ガス・鉱業・海運・不動産・公益。
       採掘1000-1499 / 石油精製2900-2999 / 一次金属3300-3399 / 水運4400-4499 / 公益4900-4999 / 不動産6500-6599"""
    try: s = int(sic)
    except (TypeError, ValueError): return False
    return (1000<=s<=1499) or (2900<=s<=2999) or (3300<=s<=3399) or (4400<=s<=4499) or (4900<=s<=4999) or (6500<=s<=6599)

def quarterly_series(facts, keys):
    """全候補タグの四半期系列を結合(stitch)して返す。重複四半期は最新まで伸びるタグを優先し、
       旧タグは前史を穴埋めする。1本勝ち(最新end最大の系列だけ採用)だと、新タグが短い会社で
       旧タグの持つ成長史を孤児化する事故が起きる(例: CELH/FAST/ROP/AME)。stitchでそれを防ぐ。
       点火式は不変——供給する系列を完全化するだけ。"""
    series = []
    for ns in ("us-gaap","ifrs-full"):
        d = facts.get("facts",{}).get(ns,{})
        for k in keys:
            if k not in d: continue
            for u, rows in d[k]["units"].items():
                out = {}
                for row in rows:
                    if not row.get("form","").startswith(("10-Q","10-K","20-F","40-F","6-K")): continue
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

def yoy_series(q, n=8):
    """直近n四半期の {end: YoY%}。約1年前(±25日)の四半期と比較。"""
    ends = sorted(q)
    out = []
    for e in ends[-n:]:
        d1 = date.fromisoformat(e)
        prior = None; bestgap = 26
        for p in ends:
            if p >= e: break
            gap = abs((d1 - date.fromisoformat(p)).days - 365)
            if gap < bestgap: prior, bestgap = p, gap
        if prior and q[prior]:
            out.append((e, round((q[e]/q[prior]-1)*100, 1)))
    return out

SIZE_BANDS = [(0.3e9, "微"), (1.5e9, "小"), (8e9, "中"), (float("inf"), "大")]

def size_class(rev):
    """直近4四半期売上の合計（年商）で規模を分類。価格API不要の全自動プロキシ。"""
    ends = sorted(rev)
    if len(ends) < 4: return None, None
    ttm = sum(rev[e] for e in ends[-4:])
    for cap, label in SIZE_BANDS:
        if ttm < cap: return ttm, label
    return ttm, "大"

def ignition(t, cik):
    facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    rev = quarterly_series(facts, TAGS_REV)
    op  = quarterly_series(facts, TAGS_OP)
    ttm, size = size_class(rev)
    ys  = yoy_series(rev)
    if len(ys) < 3:
        return {"verdict": "四半期開示なし", "yoy": None, "accel": 0, "opm_d": None,
                "trail": [], "rev_ttm": ttm, "size": size}
    if (date.today() - date.fromisoformat(ys[-1][0])).days > 400:
        return {"verdict": "古い開示", "yoy": None, "accel": 0, "opm_d": None,
                "trail": [f"{e[:7]}:{y:+.0f}%" for e, y in ys[-4:]], "rev_ttm": ttm, "size": size}
    trail = ys[-4:]                                   # 直近4本のYoY推移
    yoy   = ys[-1][1]
    accel = 0                                          # 加速の連続数（直近から遡る）
    for i in range(len(ys)-1, 0, -1):
        if ys[i][1] > ys[i-1][1]: accel += 1
        else: break

    def dopm_at(e):
        """四半期eの営業利益率の前年同期差(pt)"""
        d1 = date.fromisoformat(e)
        prior = None; bestgap = 26
        for p in sorted(rev):
            if p >= e: break
            gap = abs((d1 - date.fromisoformat(p)).days - 365)
            if gap < bestgap: prior, bestgap = p, gap
        if prior and op.get(e) is not None and op.get(prior) is not None and rev.get(prior) and rev.get(e):
            return round(op[e]/rev[e]*100 - op[prior]/rev[prior]*100, 1)
        return None

    dopms = [dopm_at(e) for e, _ in ys]
    opm_d = dopms[-1]
    b_streak = 0                                       # ΔOPM≥+2pt の連続数（直近から遡る）
    for i in range(len(dopms)-1, -1, -1):
        if dopms[i] is not None and dopms[i] >= 2: b_streak += 1
        else: break

    if accel >= 2 and yoy >= 25 and (opm_d is not None and opm_d >= 2):
        v = "点火"                                     # A: 売上加速型（NVIDIA型）
    elif b_streak >= 2 and yoy >= 10:
        v = "点火B"                                    # B: 利益率階段型（Amazon/Microsoft型）
    elif (accel >= 1 and yoy >= 15) or (b_streak == 1 and yoy >= 10):
        v = "くすぶり"
    else:
        v = "待機"
    # シクリカル・ガード: 点火が出た時だけSICを引く。利益率階段型(B)が商品市況由来なら「点火B(市況?)」に降格。
    #   点火A(売上加速)のシクリカルは降格しない——バックテスト実証(kaibutsu_backtest 412社)で
    #   点火Aシクリカルの前方3年成功率75% > 対照(非点火)54% ＝ 有効な信号(売上は続く=怪物の仕事)。
    #   利益率階段(点火B)シクリカルだけが49%<対照=真の偽点火。堀の無さは門Ωの三本柱が裁く分業。
    #   ゆえに点火Aは降格せず"市況注意"の軟フラグに留める(推測でなくデータに従う)。
    sic, sic_desc, cyc = "", "", False
    if v in ("点火", "点火B"):
        try:
            sic, sic_desc = sic_of(cik)
            cyc = is_cyclical_sic(sic)
        except Exception:
            pass
        if v == "点火B" and cyc:
            v = "点火B(市況?)"                          # 商品市況で利益率が振れる型＝偽点火の常連。要人手確認
    # ===== 検死フラグ(v2 精度強化): 見かけの点火を注記。降格でなく人手確認の合図。核の点火式は不変 =====
    flags = []
    if cyc and v == "点火":
        flags.append("市況注意")                        # 点火Aシクリカル=売上は続くが堀は門Ωで厳しく(実証:成功率75%)
    if yoy is not None and yoy > 150:
        flags.append("base?")                           # 前年比2.5倍超=小ベース/M&Aで%が誇張(ONC 22179%型)
    ends_r = sorted(rev)
    if len(ends_r) >= 2 and rev.get(ends_r[-2]):
        qoq = rev[ends_r[-1]] / rev[ends_r[-2]] - 1
        if qoq > 0.40:
            flags.append("段差?")                       # 直近QoQ+40%超=緩やかでない段差=合併/一時の疑い(TKO合併型)
    if size == "微" and v in ("点火", "点火B", "点火B(市況?)"):
        flags.append("微小流動性")                      # 年商<$0.3B=流動性・集中の脆さ(FDCTD型)
    if opm_d is not None and opm_d > 20:
        flags.append("営利差過大")                      # 単一四半期でΔ営利率>20pt=一時益/構造要確認(INSW +56pt型)
    # ===== 無知の枠 一次適格: 綺麗な点火(点火/点火B ∧ 検死フラグ無し=市況/base/段差/微小/営利差過大が無い)。
    #   買い信号ではない——「採取→門Ω審査に回す価値のある偽点火でない点火」の一次選別。
    #   S1キル(負債/EBITDA>4・債務超過・Altman Z''<1.1・ROIC≤WACC・堀崩壊)等の耐久床は門Ωでしか出せない=審査で確定。
    #   通過先は城でなく無知の枠(未実証・資本5-10%・全損前提・別管理)。Ω75+二段関門で城へ卒業。核の点火式は不変。
    sleeve = (v in ("点火", "点火B")) and not flags
    return {"verdict": v, "yoy": yoy, "accel": accel, "opm_d": opm_d, "b_streak": b_streak,
            "sic": sic, "sic_desc": sic_desc, "cyc": cyc, "flags": flags, "sleeve": sleeve,
            "trail": [f"{e[:7]}:{y:+.0f}%" for e, y in trail], "rev_ttm": ttm, "size": size}

# ---------------- 主処理 ----------------
def main():
    args = sys.argv[1:]
    top_n = 40
    max_rev = None                                   # 年商上限（$B・USD想定）
    if "--top" in args:
        i = args.index("--top"); top_n = int(args[i+1]); del args[i:i+2]
    if "--max-rev" in args:
        i = args.index("--max-rev"); max_rev = float(args[i+1]) * 1e9; del args[i:i+2]
    tickers = [a.upper() for a in args if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,7}", a)]

    if tickers:
        cands = [{"ticker": t, "name": "", "sig": None, "cagr5": None,
                  "roic": None, "opm": None, "ccy": "", "byomei": ""} for t in tickers]
        print(f"=== 怪物の門・点火検知 {date.today()}（指定 {len(cands)}社） ===")
    else:
        cands = signature_rank(top_n)
        print(f"=== 怪物の門 {date.today()}: 署名上位{len(cands)}社（母集団 gate0_all.csv） → 点火検知 ===")

    cmap = cik_map()
    kills = {}                                          # 確定死足切り(門Ω審査で構造的キル確認済=◆から除外)
    if os.path.exists(KILLJS):
        try: kills = json.load(open(KILLJS)).get("kills", {})
        except Exception: kills = {}
    order = {"点火": 0, "点火B": 1, "点火B(市況?)": 2, "くすぶり": 3, "待機": 4,
             "古い開示": 5, "四半期開示なし": 6, "失敗": 7}
    results = []
    for c in cands:
        t = c["ticker"]
        try:
            cik = cmap.get(t)
            if not cik: raise RuntimeError("CIK不明")
            r = ignition(t, cik)
        except Exception as e:
            r = {"verdict": "失敗", "yoy": None, "accel": 0, "opm_d": None,
                 "trail": [], "rev_ttm": None, "size": None, "err": str(e)[:80]}
        # 確定死足切り: 既知の構造的キル(特許cliff等)は無知でなく既知の死ゆえ◆一次適格から外す。
        #   機械で判る債務超過は署名段階で除外済。ここは門Ω審査で確定した死をリストで記憶し反映する。
        if t in kills:
            r["sleeve"] = False
            r["kill"] = kills[t].get("reason", "確定死")
        c.update(r)
        results.append(c)
        mark = {"点火": "🔥", "点火B": "🔶", "点火B(市況?)": "🔸", "くすぶり": "…", "待機": "  "}.get(r["verdict"], "×")
        sz = f"{r['size']}(${r['rev_ttm']/1e9:.1f}B{'' if c.get('ccy') in ('USD','') else ' '+c['ccy']})" if r.get("rev_ttm") else "?"
        cycn = f" [{r.get('sic_desc','')[:20]}]" if r.get("cyc") else ""
        flagn = f" ⚑{'/'.join(r['flags'])}" if r.get("flags") else ""
        killn = f" ☠確定死({r['kill']})" if r.get("kill") else ""
        flagn = flagn + killn
        slvn  = " ◆無知の枠" if r.get("sleeve") else ""
        print(f" {mark} {t:<6} {r['verdict']:<10} 規模{sz:<14} YoY {str(r['yoy'])+'%':>8} 加速{r['accel']}連続 "
              f"営利差 {str(r['opm_d'])+'pt':>8} B連続{r.get('b_streak',0)}{cycn}{flagn}{slvn}  {' '.join(r['trail'])}")

    # 集団発火フィルタ: 有効データ中の点火(A+B)比率が高い＝マクロの一斉点火の疑い(2021年型)
    scanned = [c for c in results if c["verdict"] in ("点火","点火B","点火B(市況?)","くすぶり","待機")]
    fires   = [c for c in results if c["verdict"] in ("点火","点火B")]      # 市況?は本物の点火に数えない
    macro = len(scanned) >= 10 and len(fires) / len(scanned) >= 0.30
    macro_note = (f"⚠ 集団発火の疑い: 有効{len(scanned)}社中{len(fires)}社が点火。市場全体の反動(ベータ)の"
                  f"可能性が高く、個別のアルファとして扱わないこと" if macro else "")
    if macro: print(f"\n{macro_note}")

    if max_rev is not None:
        before = len(results)
        results = [c for c in results if c.get("rev_ttm") is None or c["rev_ttm"] <= max_rev]
        print(f"\n--max-rev {max_rev/1e9:.0f}B: 年商超過 {before-len(results)}社を行列から除外")
    # 同じ判定内では小さい順（怪物は小さいうちに拾う）→ 同規模なら署名点順
    size_ord = {"微": 0, "小": 1, "中": 2, "大": 3, None: 4}
    results.sort(key=lambda x: (order.get(x["verdict"], 9),
                                size_ord.get(x.get("size"), 4), -(x["sig"] or 0)))
    json.dump({"asof": str(date.today()), "note": "審査待ち。点火銘柄は門Ω審査→門Xのサイズ規律へ。台帳データではない。",
               "macro_fire": macro_note or None,
               "queue": results}, open(OUTQ, "w"), ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(OUTR), exist_ok=True)
    with open(OUTR, "w") as f:
        f.write(f"怪物の門 点火報告 {date.today()}\n")
        f.write("判定: 点火=YoY加速2連続∧YoY≥25%∧営利率+2pt(売上加速型) / "
                "点火B=営利率+2pt×2Q連続∧YoY≥10%(利益率階段型) / くすぶり=どちらかの予鳴り\n")
        f.write("点火B(市況?)=点火BだがSICがシクリカル(石油ガス/鉱業/海運/公益/不動産)。"
                "検証で偽点火が集中した型ゆえ降格。利益率上昇が構造でなく商品市況由来でないか人手確認\n")
        f.write("規模: 年商(直近4Q売上) 微<$0.3B/小<$1.5B/中<$8B/大≥$8B。同判定内は小さい順。\n")
        f.write("⚑検死フラグ(v2 精度強化・降格でなく人手確認の合図): 市況注意=点火Aシクリカル(実証:売上は続くが堀は門Ωで厳しく) / "
                "base?=YoY>150%で小ベース・M&Aによる%誇張の疑い / 段差?=直近QoQ+40%超=合併/一時の疑い / "
                "微小流動性=年商<$0.3B / 営利差過大=単一四半期でΔ営利率>20pt=一時益/構造要確認\n")
        f.write("◆無知の枠 一次適格=点火/点火B ∧ 検死フラグ無し(偽点火でない綺麗な点火)。"
                "無知の枠の入口は怪物の門のみ＝これが入館証(門Ω二段関門は城への卒業のみで入口ではない)。"
                "買い信号ではない——小口・全損前提・別管理でバスケット。\n")
        f.write("☠確定死=門Ω審査で構造的キル確認済(特許cliff/顧客集中等)=『無知』でなく『既知の死』ゆえ◆から除外"
                "(kaibutsu_killlist.json)。機械で判る債務超過は署名段階で除外済。質的な不確実性は無知として受け入れる。\n")
        f.write("点火は買いではない。◆一次適格を無知の枠へ小さく(1匹1.5-2%×10-13匹・上限5-10%・全損前提の別管理)。"
                "門Ω二段関門(Ω75+ ∧ 門X開通)を満たせば城(本張り)へ卒業。\n")
        if macro_note: f.write(macro_note + "\n")
        f.write("\n")
        for c in results:
            sz = f"{c['size']} ${c['rev_ttm']/1e9:.1f}B" if c.get("rev_ttm") else "規模?"
            cycn = f" 【{c.get('sic_desc','')}】" if c.get("cyc") else ""
            flagn = f" ⚑{'/'.join(c['flags'])}" if c.get("flags") else ""
            killn = f" ☠確定死({c['kill']})" if c.get("kill") else ""
            flagn = flagn + killn
            cbase = "(base?)" if (isinstance(c.get('cagr5'), (int,float)) and c['cagr5'] > 200) else ""
            slvn = " ◆無知の枠" if c.get("sleeve") else ""
            f.write(f"[{c['verdict']}]{slvn} {c['ticker']:<6} {sz:<10} 署名{c['sig']}点 "
                    f"CAGR5 {c['cagr5']}%{cbase} ROIC {c['roic']}% OPM {c['opm']}% | "
                    f"YoY {c['yoy']}% 加速{c['accel']}連続 営利差 {c['opm_d']}pt B連続{c.get('b_streak',0)}{cycn}{flagn} | "
                    f"{' '.join(c['trail'])} {c.get('err','')}\n")
    fireA = [c["ticker"] for c in results if c["verdict"] == "点火"]
    fireB = [c["ticker"] for c in results if c["verdict"] == "点火B"]
    smo  = [c["ticker"] for c in results if c["verdict"] == "くすぶり"]
    sleeveL = [c["ticker"] for c in results if c.get("sleeve")]
    killedL = [c["ticker"] for c in results if c.get("kill")]
    print(f"\n点火A {len(fireA)}社: {fireA or 'なし'}\n点火B {len(fireB)}社: {fireB or 'なし'}\nくすぶり {len(smo)}社: {smo or 'なし'}")
    print(f"◆無知の枠 一次適格 {len(sleeveL)}社: {sleeveL or 'なし'}（入口は怪物の門のみ。無知の枠へ小口・全損前提。門Ω二段関門は城への卒業のみ）")
    if killedL: print(f"☠確定死足切り {len(killedL)}社: {killedL}（門Ω審査で構造的キル確認済＝既知の死ゆえ◆除外・kaibutsu_killlist.json）")
    print(f"出力: {os.path.basename(OUTQ)} / out/kaibutsu_report.txt")
    print("点火銘柄は hachimon_fetch.py で採取 → 門Ω審査 → 門Xのサイズ規律へ。")

if __name__ == "__main__":
    main()
