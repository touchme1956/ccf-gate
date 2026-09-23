# night/hist_valuation.py — 自己相対バリュエーションの採取器 (2026-08-09新設)
#
# 目的: 事前登録 out/hist_valuation_prereg.json の指標を実測する。測るのは
#   「ある asof 時点で、その銘柄の株価が **その銘柄自身の過去** と比べてどれくらい高いか」。
#   この台帳が過去に測った価格の線は全部**横断面**（他社と比べて高いか）で、自己相対は未測定だった。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【この採取器が守っている作法（読まずに直さないこと）】
#
# ■ 基準の違う二つを割らない（この台帳が5回踏んでいる事故の型）
#   Yahoo の `quote.close` は **今日までの分割で調整済み**＝当時の板の値ではない。
#   ここへ「当時の申告株数」を掛けたり「当時の申告EPS」で割ったりすると、
#   **後に分割した社（＝勝者に多い）ほど倍率が安く出る**（retro_per_asof.py の冒頭が
#   実測を記録している: AAPL 2.32 / ISRG 3.49 / BKNG 3.27 ← 真値 10.25 / 24.29 / 30前後）。
#   → 本器は **すべてを「今日の株数基準」に揃えてから割る**:
#        S(f) = ex-date が f より後の分割比の累積（＝f 時点の1株が今日の何株になったか）
#        mcap(M) = close(M) × 申告株数(filed=f) × S(f)
#      これは **恒等的に当時の時価総額**になる（証明: close(M)=board(M)/S(M)、
#      実株数(M)=申告株数(f)×S(f)/S(M) なので S(M) が約分で消える）。
#      分割は「単位の付け替え」であって金額を動かさないので、**将来の分割情報を使っても
#      look-ahead にならない**（値ではなく単位の翻訳にしか使っていない）。
#   同じ理由で PER も PS も PFCF も **時価総額を分子に統一**した。株価側の変換を
#   1箇所にまとめれば、間違える場所も1箇所で済む。
#
# ■ 自己相対だから ADR の比率事故に強い（設計上の副産物・重要）
#   1 ADS = k 普通株 の社では、申告株数は普通株・株価は ADS なので **時価総額も PER も
#   k 倍ずれる**（ADRのper事故の型で、この台帳が TSM/SAP で踏んだもの）。
#   ところが本器が出すのは **その社自身の履歴の中での分位と z** なので、
#   履歴を通して一定な倍率 k は **分位でも log-z でも完全に打ち消える**。
#   壊れるのは `pe` `ps` `mcap` の**水準**だけ。分位を主指標にする理由の一つ。
#   （k が途中で変わる社は Yahoo が分割として記録することが多く、その場合は分割補正が吸う）
#
# ■ 欠測をゼロと読むな（絶対のルール7）
#   capex のタグが1本も無い社は FCF を **算出不能(null)** にする（0 と読まない）。
#   純利益が正でない月は PER を null にして分布から外し、その月数を数える。
#   単位が USD でない申告（ADR勢の現地通貨報告）は **割らずに null**（ADRのper事故の型）。
#
# ■ look-ahead を構造で防ぐ
#   (a) 各月に使ってよい決算は **filed ≤ その月末** のものだけ（決算期末では切らない。
#       12月決算社のFY2013は2013年7月時点で未公表）。
#   (b) 同じ会計期間に複数の申告がある場合は **filed が最も古い値**（as-reported）。
#       後年の修正・遡及再表示は「当時読めた数字」ではない。
#   (c) 価格は **月末が asof 以下**の月足を使う（既定 --px-mode le_asof）。
#       Yahoo の月足は「その月の最終営業日の終値」なので、asof=2018-07-01 で
#       2018-07 の足を採ると **1ヶ月先の値**になる。
#   (d) S&P500実績PERの分位も **asof 以前の月だけ**で取る。
#
# ■ 二重実装を作らない
#   タグの選び方は hachimon_fetch.series() の意味論をそのまま踏襲する
#   （keys の並び＝意味の優先順を守る／重なる年で一致するタグだけ接ぐ／名前空間はまたがない）。
#   ただし本器は**四半期を含む「期間」を鍵にする**ため、会計年度を鍵にする series() を
#   そのまま呼べない（series() の _annual は 10-K/20-F/40-F しか見ない＝10-Q が落ちる）。
#   よって *移植* であって別実装ではない。意味論を変えたらこの注記も直すこと。
#
# ■ TTM は「量」であって「基準」ではない
#   年次だけの社は年1回更新の階段、四半期がある社は四半期更新の階段になるが、
#   **測っている量はどちらも trailing 12 months** なので混ぜても「基準の違う二つ」にはならない。
#   ただし更新頻度の差は「読み取りの古さ」の差になるので、
#   **年次更新だけで組んだ分位 (pe_pct_ann) も併記**して感度を見られるようにした。
#
# ─────────────────────────────────────────────────────────────────────────────
# 実行:
#   python3 night/hist_valuation.py --asof 2018-07-01 --tickers out/retro_returns_2018.json \
#                                   --out out/hist_val_2018.json
#   python3 night/hist_valuation.py --t MSFT,AAPL,KO --asof 2018-07-01      # 点検用
#   python3 night/hist_valuation.py --t MSFT --asof 2026-08-09              # 今日の台帳にも使える
#
# キャッシュ: out/_histval_cache/（.gitignore 済）。1000社超を扱うので**再開可能**。
#   facts/CIK##########.json.gz  … SEC companyfacts（必要タグだけに剪定）
#   px/{TICKER}.json.gz          … Yahoo 月足 close + splits（asof に依らないので全ビンテージで再利用）
import argparse
import csv
import datetime as dt
import gzip
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
import os as _os_pxg, sys as _sys_pxg
_sys_pxg.path.insert(0, _os_pxg.path.dirname(_os_pxg.path.abspath(__file__)))
import px_guard as PXG   # noqa: E402  株価履歴の検問（短い応答で在庫を上書きしない・2026-09-23）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "out", "_histval_cache")
SEC_UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com",
          "Accept-Encoding": "gzip"}
YF_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# XBRL の実質的な開始（これ以前は自己履歴が作れない）
XBRL_START = "2009-01"

# ── タグ ─────────────────────────────────────────────────────────────────────
# 並びは **意味の優先順**（series() と同じ約束）。ASC606 の改称は「代替」なので
# 重なる期間で値が一致するときだけ接ぐ。「構成要素」を足すのは capex だけではなく
# ここでは扱わない（capex は代替タグ・OCF も代替タグ）。
TAGS = {
    "ni":  ["NetIncomeLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
            "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted",
            "EarningsPerShareBasicAndDiluted",
            "EarningsPerShareBasic"],
    "wsh": ["WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
            "WeightedAverageNumberOfSharesOutstandingBasic"],
    "rev": ["Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
            "SalesRevenueServicesNet",
            "RevenueFromContractWithCustomerExcludingAssessedTaxMember"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    # capex は「代替」（総額の言い方が社によって違うだけ）。1本も無ければ **0 と読まず null**
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets",
              "PaymentsToAcquirePropertyPlantAndEquipmentExcludingCapitalizedInterest",
              "PaymentsForCapitalImprovements",
              "PaymentsToAcquireOtherPropertyPlantAndEquipment"],
}
DEI_SHARES = "EntityCommonStockSharesOutstanding"
TAGSET_VERSION = 3          # 剪定キャッシュの鍵。タグを増やしたら上げる

FLOW_KEYS = ("ni", "eps", "rev", "ocf", "capex")   # 期間フロー（TTMを組む）
USD_KEYS = ("ni", "rev", "ocf", "capex")           # 通貨単位でなければならない

_last_sec_call = [0.0]


# ── 小道具 ───────────────────────────────────────────────────────────────────
def D(s):
    return dt.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def month_end(mk):
    y, m = int(mk[:4]), int(mk[5:])
    return (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))


def months_between(a, b):
    """月キー a..b（両端含む）を昇順で返す。"""
    y, m = int(a[:4]), int(a[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _get(url, headers, timeout=45, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            last = e
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def _sec_get(url):
    """SEC は 10 req/s 厳守。余裕を見て 8 req/s 程度に抑える。"""
    wait = 0.13 - (time.time() - _last_sec_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_sec_call[0] = time.time()
    return _get(url, SEC_UA)


def _cache_read(path):
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


# ── ticker → CIK ─────────────────────────────────────────────────────────────
def ticker_map(offline=False):
    """SEC の現行登録表。**これは「今日の」登録社なので生存バイアスがある**
    （2026-08-04 の歴史検証で ticker 必須にすると退場社が最初から消えると実測済み）。
    入力ファイルが cik を持っているならそちらを優先すること。"""
    p = os.path.join(CACHE, "company_tickers.json.gz")
    j = _cache_read(p)
    if j is None:
        if offline:
            return {}
        raw = _get("https://www.sec.gov/files/company_tickers.json", SEC_UA)
        j = json.loads(raw)
        _cache_write(p, j)
    out = {}
    for r in j.values():
        t = str(r.get("ticker", "")).upper().strip()
        if t and t not in out:
            out[t] = int(r["cik_str"])
    return out


# ── SEC companyfacts（必要タグだけに剪定してキャッシュ）───────────────────────
def _prune(j):
    want = set()
    for v in TAGS.values():
        want.update(v)
    facts = j.get("facts", {})
    keep, forms = {}, {}
    for ns in ("us-gaap", "ifrs-full"):
        d = facts.get(ns) or {}
        sub = {k: d[k] for k in want if k in d}
        if sub:
            keep[ns] = sub
    dei = facts.get("dei") or {}
    if DEI_SHARES in dei:
        keep["dei"] = {DEI_SHARES: dei[DEI_SHARES]}
    for ns, tags in keep.items():
        for node in tags.values():
            for ents in node.get("units", {}).values():
                for e in ents:
                    f = e.get("form", "")
                    forms[f] = forms.get(f, 0) + 1
    return {"cik": j.get("cik"), "entityName": j.get("entityName"),
            "facts": keep, "forms": forms, "v": TAGSET_VERSION}


def fetch_facts(cik, offline=False):
    p = os.path.join(CACHE, "facts", f"CIK{cik:010d}.json.gz")
    j = _cache_read(p)
    if j is not None and j.get("v") == TAGSET_VERSION:
        return j
    if offline:
        return None
    try:
        raw = _sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _cache_write(p, {"cik": cik, "facts": {}, "forms": {}, "v": TAGSET_VERSION,
                             "why": "companyfacts 404"})
            return _cache_read(p)
        raise
    j = _prune(json.loads(raw))
    _cache_write(p, j)
    return j


# ── Yahoo 月足（close は今日基準の分割調整済み・splits で当時へ翻訳する）────────
PX_CACHE_VERSION = 2        # adjclose を足したので上げた（古いキャッシュは取り直す）


def fetch_px(ticker, offline=False):
    p = os.path.join(CACHE, "px", f"{ticker.upper().replace('/', '_')}.json.gz")
    j = _cache_read(p)
    if j is not None and j.get("v") == PX_CACHE_VERSION:
        return j
    if offline:
        return j                      # 旧版でも無いよりよい（adjclose が無いだけ）
    t0 = int(dt.datetime(2004, 1, 1).timestamp())
    t1 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t0}&period2={t1}&interval=1mo&events=splits")
    try:
        raw = _get(url, YF_UA, tries=3)
        res = (json.loads(raw).get("chart", {}).get("result") or [None])[0]
    except Exception as e:
        res = None
        err = f"{type(e).__name__}"
    if not res:
        out = {"ticker": ticker, "close": {}, "splits": [], "adj": {},
               "v": PX_CACHE_VERSION, "why": "yahoo_no_data"}
        # ★px_guard（2026-09-23）: 前のキャッシュ（旧版でも）に足があれば、空の応答で上書きしない
        if j is not None and (j.get("close") or {}):
            PXG.log_refusal(ticker, "hist_valuation.fetch_px", "応答が空（取得失敗）",
                            PXG.span(j.get("close")), None, kept="old")
            return j
        if PXG.vet(ticker, {}, "hist_valuation.fetch_px", req_start=t0, record=False) is None:
            return dict(out, why="px_guard_refused(台帳より短い)")   # 書かない＝次回また取りに行く
        _cache_write(p, out)
        return out
    ts = res.get("timestamp") or []
    cl = ((res.get("indicators", {}).get("quote") or [{}])[0].get("close")) or []
    ac = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
    close, adj = {}, {}
    for i, (t, c) in enumerate(zip(ts, cl)):
        if c is None:
            continue
        mk = dt.datetime.utcfromtimestamp(t).strftime("%Y-%m")
        close[mk] = float(c)
        if i < len(ac) and ac[i] is not None:
            adj[mk] = float(ac[i])
    splits = []
    for sp in (res.get("events", {}).get("splits") or {}).values():
        try:
            num, den = float(sp["numerator"]), float(sp["denominator"])
            if num > 0 and den > 0:
                splits.append({"date": dt.datetime.utcfromtimestamp(int(sp["date"])).strftime("%Y-%m-%d"),
                               "ratio": num / den})
        except Exception:
            pass
    splits.sort(key=lambda s: s["date"])
    out = {"ticker": ticker, "close": close, "adj": adj, "splits": splits,
           "v": PX_CACHE_VERSION,
           "currency": (res.get("meta") or {}).get("currency")}
    # ★px_guard（2026-09-23・todo yahoo_history_vanished）: Yahoo が過去の足を消した記号
    #   （EQR/QVCAQ/SALM/BBBY…は 2026-07 以降しか返さない）で、**在庫の長い履歴を短い応答で上書きしない**。
    #   前のキャッシュがあれば前を残す（旧版でも。adj が無いだけのほうが、履歴が無いより良い）。
    #   前が無ければ台帳 out/px_span_ledger.json と突き合わせ、短ければ「測れない」を返して書かない。
    if j is not None and (j.get("close") or {}):
        if PXG.shorter_reason(j.get("close"), close):
            PXG.keep_longer(ticker, j.get("close"), close, "hist_valuation.fetch_px")
            return j
    elif PXG.vet(ticker, close, "hist_valuation.fetch_px", req_start=t0, record=False) is None:
        return {"ticker": ticker, "close": {}, "splits": [], "adj": {},
                "v": PX_CACHE_VERSION, "why": "px_guard_refused(台帳より短い)"}
    PXG.note(ticker, close, "hist_valuation.fetch_px")
    _cache_write(p, out)
    time.sleep(0.35)
    return out


def big_distributions(px, months, thresh=0.15):
    """**特別配当・スピンオフ**で自己履歴が途切れていないかを見る（2026-08-09追加）。

    分割は「単位の付け替え」なので補正できるが、**特別配当とスピンオフは会社そのものを
    小さくする**ので、その前後の倍率は同じ会社を測っていない。分割補正も時価総額の式も
    これを吸わないので、放っておくと**自己相対の分位が静かに壊れる**。
    実例（この採取器の突合せで実際に出た）: **KDP** は 2018-07 に Dr Pepper Snapple が
    Keurig と統合する際 **1株あたり $103.75 の特別配当**（株価の約85%）を払った。
    2018年6月の株価122ドルと7月の24ドルは**同じ会社の連続した系列ではない**。

    検出法: Yahoo の close（分割のみ調整）と adjclose（分割＋配当調整）の**月次リターンの比**が
    そのまま「その月に払い出された割合」になる。通常の配当は月あたり1%未満なので、
    15%を超えたら通常の配当ではない。
    **値は落とさず印だけ付ける**——会社が縮んだこと自体は事実で、どう扱うかは使う側の判断。

    ⚠**この検出には穴がある（実測して確かめた・過大に主張しないこと）**:
      拾えるのは **Yahoo が配当として調整に織り込んだ分配だけ**。実測——
        MDLZ 2012-10 に 50% を検出（Kraft の分社）＝◎
        ABT（2013-01 AbbVie 分社）・HPQ（2015-11 HPE 分社）は **0.0 で素通り**
        ——Yahoo の adjclose がこの種の分社を織り込んでいないため。
      よって `distrib_break=false` の意味は「**分社が無かった**」ではなく
      「**Yahoo の配当調整に現れる大きな分配は無かった**」。分社の網羅的な検出には
      別の出所（8-K / CIK の系譜）が要る＝未実装の穴として明示する。
    """
    adj = px.get("adj") or {}
    if not adj:
        return None, []
    ms = [m for m in months if m in px["close"] and m in adj]
    hits = []
    for a, b in zip(ms, ms[1:]):
        c0, c1 = px["close"][a], px["close"][b]
        a0, a1 = adj[a], adj[b]
        if min(c0, c1, a0, a1) <= 0:
            continue
        d = (a1 / a0) / (c1 / c0) - 1.0        # ≒ その月の分配 ÷ 前月末株価
        if d >= thresh:
            hits.append({"month": b, "pct": round(d, 4)})
    return (max((h["pct"] for h in hits), default=0.0), hits)


def split_factor_after(splits, day):
    """day より**後**の分割比の累積。申告値（day 時点の株数基準）を今日基準へ直す倍率。
    分割は申告日までのぶんは遡及修正済みなので、切るのは **filed 日**（期末ではない）。"""
    f = 1.0
    for s in splits:
        if s["date"] > day:
            f *= s["ratio"]
    return f


# ── 期間フロー・時点値の取り出し（series() の意味論の移植）─────────────────────
def _entries(node, want_units, filed_le=None):
    """1タグの XBRL 行を (start,end,val,filed,unit) に均す。**filed が最も古い値**を採る
    ＝as-reported（後年の遡及修正は「当時読めた数字」ではない）。

    filed_le: これより後に提出された行は **最初から見ない**。
      2026-08-09 に踏んだ実害の是正——初版は今日の全データでタグを選んでいたので、
      MSFT の売上主系列に **ASC606 の新タグ**（同社は FY2019 の 10-K で遡及適用＝
      2019-08 提出）が選ばれ、2018-07 時点では 1行も存在せず **P/S が丸ごと空**になった。
      旧タグ `Revenues`（2017年まで）は「最新に届かない」として主系列から外れていた。
      asof で切れば、その時点で最新に届いているのは旧タグなので正しく選ばれる。
      ＝look-ahead の除去とタグ選択の是正が**同じ1行**で片づく。
    """
    per_unit = {}
    for unit, ents in (node.get("units") or {}).items():
        acc = {}
        for e in ents:
            en, fl = e.get("end"), e.get("filed")
            if not en or not fl:
                continue
            if filed_le and fl > filed_le:
                continue
            st = e.get("start")
            k = (st or "", en)
            v = float(e["val"])
            if k not in acc or fl < acc[k][1]:
                acc[k] = (v, fl)
        if acc:
            per_unit[unit] = acc
    if not per_unit:
        return {}, None
    # 単位は「行数が最も多いもの」を主単位にする（_annual と同じ作法）。ただし
    # **欲しい単位があればそれを優先**する（series() の unit_pref と同じ「優先フィルタ」。
    # 厳格フィルタにすると現地通貨も併記する社が丸ごと落ちる）。
    pool = [u for u in per_unit if u in want_units] if want_units else list(per_unit)
    pool = pool or list(per_unit)
    unit = max(pool, key=lambda u: len(per_unit[u]))
    return per_unit[unit], unit


def pick_periods(facts, keys, kind, want_units=None, filed_le=None):
    """候補タグから主系列を選び、重なる期間で一致する候補だけを接ぐ。

    hachimon_fetch.series() の意味論の移植（会計年度→期間へ鍵を変えただけ）:
      * 名前空間はまたがない（us-gaap と ifrs-full を混ぜない）
      * keys の並び＝意味の優先順を守る。ただし著しく古い系列は主系列にしない
      * 重なる期間で 2% 超ずれる候補は「別の指標」として接がない
    kind: "flow"（start/end のある期間値）/ "point"（時点値）
    """
    cands = []
    for ns in ("us-gaap", "ifrs-full", "dei"):
        d = (facts.get("facts") or {}).get(ns) or {}
        for i, k in enumerate(keys):
            if k not in d:
                continue
            acc, unit = _entries(d[k], want_units, filed_le)
            if not acc:
                continue
            if want_units and unit not in want_units:
                continue
            sel = {}
            for (st, en), (v, fl) in acc.items():
                if kind == "flow":
                    if not st:
                        continue
                    dur = (D(en) - D(st)).days
                    if dur < 25 or dur > 400:
                        continue
                    sel[(st, en)] = (v, fl, dur)
                else:
                    sel[("", en)] = (v, fl, 0)
            if sel:
                cands.append((i, k, sel, unit))
        if cands:
            break
    if not cands:
        return {}, None, []
    newest = max(max(en for (_, en) in c[2]) for c in cands)
    # 「最新に届いている候補の中で優先順が最も高いもの」を主系列に（BR/BKNG事故の型の予防）
    elig = [c for c in cands if max(en for (_, en) in c[2]) >= _minus_days(newest, 400)]
    elig = elig or cands
    i, k0, merged, unit = min(elig, key=lambda c: (c[0], _neg_date(max(en for (_, en) in c[2]))))
    merged = dict(merged)
    used = [k0]
    for _, k, sel, u in cands:
        if k == k0 or u != unit:
            continue
        ov = [p for p in sel if p in merged and merged[p][0]]
        if not ov:
            continue                                  # 重なり無し＝同一指標と確かめられない
        # 一致の検問は **中央値** で行う（最大値ではない）。
        #   series() の掟「重なる期間で食い違うタグは接がない」は *別の指標* を混ぜないための
        #   ものだが、`filed が最も古い値` を採る本器では **後年の遡及修正**が片方のタグにだけ
        #   反映されて数期だけずれる。実測 AAON: 8期中6期が完全一致・2016年の2期だけ
        #   3.8%/4.7% ずれる（ASU2016-09 の組み替えで 2017-05 に再表示）。最大値で裁くと
        #   この2期のせいで **2013-2017年の年次OCFが丸ごと落ち**、TTMが2013年で止まっていた。
        #   → 「4分の3以上が2%以内 かつ 中央値のずれが2%以内」を同一性の証明とする。
        #   自己資本 vs 非支配持分込み のような *別の指標* は重なるほぼ全期でずれるので、
        #   この緩和では通らない（＝掟の目的は保たれる）。
        diffs = sorted(abs(sel[p][0] - merged[p][0]) / abs(merged[p][0]) for p in ov)
        hit = sum(1 for x in diffs if x <= 0.02) / len(diffs)
        if hit < 0.75 or statistics.median(diffs) > 0.02:
            continue                                  # 重なる期間で食い違う＝別の指標
        add = 0
        for p, v in sel.items():
            if p not in merged:
                merged[p] = v
                add += 1
        if add:
            used.append(k + (f"(重なり{len(diffs)}期中{sum(1 for x in diffs if x>0.02)}期は"
                             f"遡及修正で不一致)" if hit < 1 else ""))
    return merged, unit, used


def _minus_days(iso, n):
    return (D(iso) - dt.timedelta(days=n)).isoformat()


def _neg_date(iso):
    return tuple(-int(x) for x in iso.split("-"))


# ── TTM の組み立て ───────────────────────────────────────────────────────────
def build_ttm(sel):
    """期間値 {(start,end):(val,filed,dur)} から trailing-12-months 点列を作る。

    3通りの作り方をこの順で試す（**どれも測っている量は同じ trailing 12ヶ月**なので
    社の中で混ざってよい。混ぜてはいけないのは「TTM と 直近FY」のような別の量）:
      A 年次     : 期間長 330-400 日の行そのもの
      C 通期+スタブ−前年同スタブ : CLAUDE.md が per の検算で使っている式。
                   四半期のYTD（期首からの累計）が 10-Q に必ずあるので被覆が広い
      B 連続タイル: 期末から遡って重ならない期間で 12ヶ月をちょうど敷き詰める
                   （四半期を離散で出す社の受け皿）
    返り値: {end_iso: (val, known_iso, method)} — known は構成要素の filed の最大値
            （＝その TTM が世に出た日）。同じ end に複数の作り方が当たったら
            **1%以内で一致するか検算**し、食い違えば残さない（もっともらしい誤値より空欄）。
    """
    if not sel:
        return {}, {}
    ann, ytd, quarters = {}, [], []
    for (st, en), (v, fl, dur) in sel.items():
        if 330 <= dur <= 400:
            if en not in ann or fl < ann[en][1]:
                ann[en] = (v, fl, st)
        elif 25 <= dur <= 330:
            ytd.append((st, en, v, fl, dur))
    by_end = {}
    for (st, en), (v, fl, dur) in sel.items():
        by_end.setdefault(en, []).append((st, en, v, fl, dur))

    cand = {}      # end -> list of (val, known, method)

    # A 年次
    for en, (v, fl, st) in ann.items():
        cand.setdefault(en, []).append((v, fl, "A_annual"))

    # C 通期 + 期末後スタブ − 前年同スタブ
    ytd_by_start = {}
    for row in ytd:
        ytd_by_start.setdefault(row[0], []).append(row)
    for st, en, v, fl, dur in ytd:
        prev_fy_end = (D(st) - dt.timedelta(days=1)).isoformat()
        a = None
        for cand_end in (prev_fy_end,
                         (D(st) - dt.timedelta(days=2)).isoformat(),
                         D(st).isoformat()):
            if cand_end in ann:
                a = ann[cand_end]
                break
        if not a:
            continue
        # 前年同期の YTD（期首が約365日前・期間長が同じ）
        best = None
        for st2, en2, v2, fl2, dur2 in ytd:
            if abs((D(st) - D(st2)).days - 365) > 20:
                continue
            if abs(dur - dur2) > 12:
                continue
            if best is None or fl2 < best[3]:
                best = (st2, en2, v2, fl2, dur2)
        if not best:
            continue
        val = a[0] + v - best[2]
        known = max(a[1], fl, best[3])
        cand.setdefault(en, []).append((val, known, "C_fy_stub"))

    # B 連続タイル（期末から遡って 12ヶ月ちょうど敷く）
    ends = sorted(by_end)
    for en in ends:
        if en in cand:
            continue
        E = D(en)
        found = _tile(by_end, E, E, 0, 0.0, "")
        if found:
            cand.setdefault(en, []).append((found[0], found[1], "B_tile"))

    out, conflicts = {}, {}
    for en, lst in cand.items():
        lst = sorted(lst, key=lambda x: ("ACB".index(x[2][0]), x[1]))
        v0 = lst[0][0]
        ok = True
        for v, k, m in lst[1:]:
            if v0 and abs(v - v0) / max(abs(v0), 1e-9) > 0.01:
                ok = False
                conflicts[en] = [(round(x[0], 4), x[2]) for x in lst]
                break
        if ok:
            # known は「一番早く世に出た作り方」を採る（当時読めた日）
            v, k, m = min(lst, key=lambda x: x[1])
            out[en] = (v, k, m)
    return out, conflicts


def _tile(by_end, E, cursor, depth, total, known):
    """cursor から遡って、重ならない期間で [E-365日, E] をちょうど敷けるか探す。"""
    span = (E - cursor).days
    if 350 <= span <= 381:
        return (total, known)
    if depth >= 5 or span > 395:
        return None
    ck = cursor.isoformat()
    cands = []
    for off in range(-4, 5):
        k = (cursor + dt.timedelta(days=off)).isoformat()
        for row in by_end.get(k, []):
            cands.append(row)
    seen = set()
    uniq = []
    for st, en, v, fl, dur in sorted(cands, key=lambda r: (-r[4], r[3])):
        if (st, en) in seen:
            continue
        seen.add((st, en))
        uniq.append((st, en, v, fl, dur))
    for st, en, v, fl, dur in uniq[:6]:
        if (E - D(st)).days > 400:
            continue
        r = _tile(by_end, E, D(st) - dt.timedelta(days=1), depth + 1,
                  total + v, max(known, fl))
        if r:
            return r
    return None


def as_known_timeline(ttm, months, max_stale_days=550):
    """各月に「その月末までに世に出ていた中で最も新しい期末」の TTM を割り当てる。"""
    pts = sorted(((k, en, v, m) for en, (v, k, m) in ttm.items()))   # known 昇順
    out = {}
    for mk in months:
        me = month_end(mk).isoformat()
        best = None
        for k, en, v, m in pts:
            if k > me:
                break
            if best is None or en > best[1]:
                best = (k, en, v, m)
        if not best:
            continue
        if (D(me) - D(best[1])).days > max_stale_days:
            continue                                   # 古すぎる決算で倍率を作らない
        out[mk] = (best[2], best[1], best[3])
    return out


def share_scale_guard(rows, tol=0.10, min_n=6):
    """**同じ会社・同じタグの中で株数が桁で飛ぶ申告**（filer のタグ付け誤り）を落とす。
    (2026-08-09追加・2013ビンテージの点検で発見。全ビンテージに効く)

    ■ 何を見つけたか（実額・すべて as-reported の原本）
        QCOM  2011-04-20 と 2011-11-02 の2枚だけ **1,669,532,005,000株**（正 1.67e9＝×1000）
        MOG-A 2012-05 以降の 10-Q が **45,766,798,000株**（正 45.8e6＝×1000。10-K は正しい）
        CSX   2011-04-20 の 10-Q が **val = 1**（一株）
        ORCL  ×1e6 ／ ON・AMD・CLX・WHR・EXC ほか。**956社中57社(6.0%)** が ≥4倍の桁飛びを含む
    ■ なぜ致命的か
        分位は **その社自身の履歴の中の順位**なので、履歴の一部だけが×1000だと
        「自己史上いちばん高い」が機械的に作られる。実測で **MDU の ps_pct が 1.0**、
        2018年ビンテージでは **VSH の pe_pct が 1.0**＝**この検定が探している信号そのものを捏造する**。
        単独の帯検問（時価総額が大きすぎないか）では拾えない——桁飛びが履歴の側にあると
        現在値は正常に見えるから。
    ■ なぜ株数にだけ当てるか（測ってから決めた）
        同じ「中央値からの clean な10のべき乗」検定を **フロー**へ当てると
        ni の **10.6%**・ocf の 6.4% が引っかかるが、中身は BA・AMAT の**本物の減益**だった
        ——利益は10倍動きうるので、この検定は誤りと不振を区別できない。
        株数はそうではない（分割は下で正規化済み・増資や合併は clean な10のべき乗にならない）。
        rev は 0.7%、株数の桁飛びは 0 件＝**株数系列にだけ効く検問**だと実測で確かめた。
    ■ 直さずに落とす（推測で桁を戻さない）
        `1` を `1e9` に「直す」のは桁の推測＝データの捏造。**もっともらしい誤値より空欄**。
        落とした結果その月の株数が無くなれば時価総額も倍率も null になる（安全側）。
        生き残った申告は**同じ桁で揃う**ので、分位は壊れない。
        ⚠ ただし多数派の桁が誤っている社では**水準（pe/ps/mcap の絶対値）が10のべき乗ぶんずれる**。
          分位・log-z は定数倍で打ち消えるので無事（この器の頭注の ADR の k と同じ理屈）。

    rows: [(filed, end, 今日基準へ正規化ずみの株数)] 昇順。返り値は (残した rows, 落とした記録)
    """
    if len(rows) < min_n:
        return rows, []
    med = statistics.median([v for _, _, v in rows])
    if med <= 0:
        return rows, []
    keep, dropped = [], []
    for fl, en, v in rows:
        d = math.log10(v / med)
        k = round(d)
        # (a) 中央値の clean な10のべき乗＝桁の付け間違い
        # (b) 桁は clean でないが **100倍以上**離れている＝桁の打ち間違いで数字ごと壊れている。
        #     実測 **CSX** の 2011-04-20 の 10-Q は `val = 1`（一株）。今日基準へ直すと 9 で、
        #     中央値 3.2e9 との比は 10^-8.55 ＝ clean ではないので (a) では拾えない。
        #     分割の正規化を済ませた後で 100 倍以上動く株数は、増資でも合併でも起きない
        #     （起きるのは破綻して普通株が入れ替わった社＝DBD型で、それは落とすのが正しい）。
        if abs(d) >= 2.0 or (k != 0 and abs(d - k) <= tol):
            dropped.append({"end": en, "filed": fl, "val": v, "k": k})
        else:
            keep.append((fl, en, v))          # べき乗で説明できない差は**実際の増資・合併**かもしれない＝残す
    return (keep, dropped) if keep else (rows, [])


def point_timeline(sel, months, splits, max_stale_days=550, guard=True):
    """時点値（発行済株数）の as-known 時系列。**今日の株数基準へ翻訳**して返す。

    **株数 0 は「測定値」ではなく空欄の代わり**なので採らない（ルール7の同族——
    欠測をゼロと読むな、の裏返しで *ゼロを実測と読むな*）。実測 **MGA**（40-F提出体）は
    dei:EntityCommonStockSharesOutstanding に 0 を報告しており、これを株数として使うと
    時価総額が 0 になって全指標が落ちるうえ、**「その月に株数が無い」という判定にも
    引っかからない**ので理由が『算出不能』としか出せなかった。

    正規化（分割の翻訳）は **申告を選ぶ前に**済ませる。桁の検問は「同じ基準に揃えた後」で
    ないと、分割による正当な2倍・3倍と filer の桁誤りが混ざるため。
    返り値: (月→株数, 桁誤りで落とした申告の記録)
    """
    rows = sorted(((fl, en, v * split_factor_after(splits, fl))
                   for (st, en), (v, fl, dur) in sel.items() if v and v > 0))
    dropped = []
    if guard:
        rows, dropped = share_scale_guard(rows)
    out = {}
    for mk in months:
        me = month_end(mk).isoformat()
        best = None
        for fl, en, v in rows:
            if fl > me:
                break
            if best is None or en > best[1] or (en == best[1] and fl < best[0]):
                best = (fl, en, v)
        if not best:
            continue
        if (D(me) - D(best[1])).days > max_stale_days:
            continue
        out[mk] = best[2]
    return out, dropped


# ── 統計 ─────────────────────────────────────────────────────────────────────
def pctile(hist, now):
    """now が hist の何%タイルか（中位順位法）。0-1。"""
    if not hist or now is None:
        return None
    lt = sum(1 for h in hist if h < now)
    eq = sum(1 for h in hist if h == now)
    return (lt + 0.5 * eq) / len(hist)


def zscore(hist, now, log=False):
    if not hist or now is None or len(hist) < 8:
        return None
    xs = hist
    x = now
    if log:
        if now <= 0 or any(h <= 0 for h in hist):
            return None
        xs = [math.log(h) for h in hist]
        x = math.log(now)
    sd = statistics.pstdev(xs)
    if sd <= 0:
        return None
    return (x - statistics.median(xs)) / sd


def r(x, n=4):
    return None if x is None else round(x, n)


# ── S&P500 実績PER ───────────────────────────────────────────────────────────
def load_spx():
    p = os.path.join(BASE, "out", "sp500_pe_monthly.json")
    if not os.path.exists(p):
        return {}, None
    j = json.load(open(p))
    s = {k: float(v) for k, v in (j.get("series") or {}).items() if v}
    return s, (max(s) if s else None)


def spx_at(spx, mk):
    """その月の値。無ければ**直前の月**を持ち越し、古さを返す（黙って埋めない）。"""
    if mk in spx:
        return spx[mk], 0
    ks = [k for k in spx if k < mk]
    if not ks:
        return None, None
    k = max(ks)
    a = (int(mk[:4]) - int(k[:4])) * 12 + (int(mk[5:]) - int(k[5:]))
    return spx[k], a


# ── 本体 ─────────────────────────────────────────────────────────────────────
def analyse(ticker, cik, asof, spx, spx_last, window_years=0, min_months=36,
            px_mode="le_asof", offline=False, keep_series=False):
    row = {"ticker": ticker, "cik": cik, "asof": asof.isoformat()}
    nulls, diag = {}, {}
    row["nulls"], row["diag"] = nulls, diag

    if not cik:
        nulls["all"] = "CIKが引けない（SECの現行登録表に無い＝退場・改称の可能性）"
        return row
    facts = fetch_facts(cik, offline=offline)
    if not facts or not facts.get("facts"):
        nulls["all"] = "companyfacts が空（XBRL提出なし・404）"
        return row
    forms = facts.get("forms") or {}
    fk = {k.split("/")[0] for k in forms}
    diag["forms"] = sorted(forms, key=lambda k: -forms[k])[:5]
    row["foreign_filer"] = bool({"20-F", "40-F", "6-K"} & fk)

    px = fetch_px(ticker, offline=offline)
    if not px or not px.get("close"):
        nulls["all"] = "Yahooに月足が無い（上場廃止・ティッカー改称の可能性）"
        return row
    if px.get("currency") and px["currency"] != "USD":
        nulls["all"] = f"株価がUSDでない({px['currency']})＝申告と通貨基準が違う"
        return row
    splits = px["splits"]
    diag["splits"] = len(splits)
    if not (px.get("adj") or {}):
        diag["distrib_checked"] = False   # 旧キャッシュ＝「調べていない」（0件ではない）

    # 月グリッド: 価格の最初の月 / XBRL開始 / --window のうち最も遅いところから asof まで
    asof_mk = month_key(asof)
    if px_mode == "le_asof":
        now_mk = max([m for m in px["close"] if month_end(m) <= asof] or [""])
    else:
        now_mk = max([m for m in px["close"] if m <= asof_mk] or [""])
    if not now_mk:
        nulls["all"] = "asof 以前の月足が無い（asof 時点で未上場）"
        return row
    start_mk = max(XBRL_START, min(px["close"]))
    if window_years:
        w = dt.date(asof.year - window_years, asof.month, 1)
        start_mk = max(start_mk, month_key(w))
    if start_mk > now_mk:
        nulls["all"] = "自己履歴の窓が空"
        return row
    months = months_between(start_mk, now_mk)
    row["px_month"] = now_mk
    row["px_mode"] = px_mode

    # ── ファンダの期間値 → TTM → as-known 時系列
    # **asof より後に提出された行は一切見ない**（タグ選択もこの制約の中で行う）
    filed_le = asof.isoformat()
    tl, basis_note, raw_ttm, raw_sel = {}, {}, {}, {}
    for key in FLOW_KEYS:
        units = ("USD",) if key in USD_KEYS else (("USD/shares",) if key == "eps" else ("shares",))
        sel, unit, used = pick_periods(facts, TAGS[key], "flow", want_units=units,
                                       filed_le=filed_le)
        diag[f"tag_{key}"] = used or None
        if not sel:
            tl[key] = {}
            basis_note[key] = "タグ不発見"
            continue
        if key in USD_KEYS and unit != "USD":
            tl[key] = {}
            basis_note[key] = f"単位が{unit}＝USDでない（割らない）"
            continue
        raw_sel[key] = sel
        ttm, conf = build_ttm(sel)
        if conf:
            diag[f"ttm_conflict_{key}"] = len(conf)
        raw_ttm[key] = ttm
        tl[key] = as_known_timeline(ttm, months)
        basis_note[key] = None
        # 年次更新だけの版（更新頻度の感度を見るための対照）
        ann_only = {en: t for en, t in ttm.items() if t[2] == "A_annual"}
        tl[key + "_ann"] = as_known_timeline(ann_only, months)

    # FCF は **生の会計期間の段階で引き算**してから TTM を組む（TTM どうしを引かない）。
    #   同じ期・同じ提出書類のキャッシュフロー計算書の2行を引くので「基準の違う二つを引く」
    #   余地が無く、しかも 3通りの TTM の組み方がそのまま使える。
    #   （TTM を作ってから引くと、片方のタグだけが移行・再表示で先へ進んだ社で期末が噛み合わず
    #   FCF が丸ごと落ちる。実測 KO: OCF が Q1 2018 に …ContinuingOperations へ移行／
    #   AEO: 期末の揃う月が 26ヶ月しか無かった）
    o_sel, c_sel = raw_sel.get("ocf") or {}, raw_sel.get("capex") or {}
    if not c_sel:
        basis_note["capex"] = basis_note.get("capex") or \
            "capexタグが1本も無い（欠測を0と読まない＝ルール7）"
    fcf_sel = {p: (o_sel[p][0] - c_sel[p][0], max(o_sel[p][1], c_sel[p][1]), o_sel[p][2])
               for p in set(o_sel) & set(c_sel)}
    diag["fcf_periods"] = f"{len(fcf_sel)}期(ocf {len(o_sel)} / capex {len(c_sel)})"
    fcf_ttm, fcf_conf = build_ttm(fcf_sel)
    if fcf_conf:
        diag["ttm_conflict_fcf"] = len(fcf_conf)
    tl["fcf"] = as_known_timeline(fcf_ttm, months)
    tl["fcf_ann"] = as_known_timeline(
        {en: t for en, t in fcf_ttm.items() if t[2] == "A_annual"}, months)

    # 発行済株数（時価総額用）→ 今日の株数基準
    # 株数の出所は **被覆で選ぶ**（存在するかどうかではない）。
    #   dei:EntityCommonStockSharesOutstanding は表紙の実発行済株数で時価総額には最適だが、
    #   **複数株式クラスの社では次元付きタグになり companyfacts から落ちる**
    #   （CLAUDE.md が V の EPS で記録している型）。実測 ACN: dei は2009-2010の2行しか無く、
    #   「存在するか」だけで選ぶと 2018年の時価総額が作れず PE/PS/PFCF が**全部**落ちていた。
    #   → 両方を組んでから、**asof の月を覆えるほう**（同点なら dei）を採る。
    #   出所は社の中で1本に固定する（月ごとに切り替えると時価総額が飛ぶ＝基準の混在）。
    cands_sh = []
    a, _u, _k = pick_periods(facts, [DEI_SHARES], "point", want_units=("shares",),
                             filed_le=filed_le)
    if a:
        cands_sh.append(("dei:EntityCommonStockSharesOutstanding",)
                        + point_timeline(a, months, splits))
    b, _u, _k = pick_periods(facts, TAGS["wsh"], "flow", want_units=("shares",),
                             filed_le=filed_le)
    if b:
        cands_sh.append(("WeightedAverageNumberOfDilutedShares(代替)",)
                        + point_timeline(b, months, splits))
    sh, sh_src, sh_dropped = {}, None, []
    if cands_sh:
        sh_src, sh, sh_dropped = max(cands_sh, key=lambda c: (now_mk in c[1], len(c[1])))
    diag["shares_src"] = sh_src
    if not sh:
        nulls["mcap"] = "発行済株数が取れない（dei・加重平均とも不発見）"
    # 桁を付け間違えた申告を落とした記録（分位を捏造する型なので必ず残す）
    row["shares_scale_dropped"] = len(sh_dropped)
    if sh_dropped:
        diag["shares_scale_dropped"] = sh_dropped[:6]
        nulls["_shares_scale"] = (
            f"株数の申告 {len(sh_dropped)}枚が中央値の clean な10のべき乗ぶんずれていた"
            f"（k={sorted({d['k'] for d in sh_dropped})}）＝filer のタグ付け誤りとして落とした。"
            f"残りは同じ桁で揃うので分位は壊れないが、**多数派の桁が誤っている社では"
            f"pe/ps/mcap の水準が10のべき乗ぶんずれうる**（分位・log-z は定数倍で打ち消える）")

    # ── 月次の倍率
    def series_of(fn):
        out = {}
        for mk in months:
            c = px["close"].get(mk)
            if c is None:
                continue
            try:
                v = fn(mk, c)
            except Exception:
                v = None
            if v is not None and v > 0 and math.isfinite(v):
                out[mk] = v
        return out

    def mcap(mk, c):
        n = sh.get(mk)
        return None if n is None else c * n

    def pe_of(mk, c, suf=""):
        m = mcap(mk, c)
        e = tl["ni" + suf].get(mk)
        if m is None or e is None or e[0] <= 0:
            return None
        return m / e[0]

    def ps_of(mk, c, suf=""):
        m = mcap(mk, c)
        s = tl["rev" + suf].get(mk)
        if m is None or s is None or s[0] <= 0:
            return None
        return m / s[0]

    def pfcf_of(mk, c, suf=""):
        m = mcap(mk, c)
        f = tl["fcf" + suf].get(mk)
        if m is None or f is None or f[0] <= 0:
            return None
        return m / f[0]

    ser = {
        "pe": series_of(lambda mk, c: pe_of(mk, c)),
        "ps": series_of(lambda mk, c: ps_of(mk, c)),
        "pfcf": series_of(lambda mk, c: pfcf_of(mk, c)),
        "pe_ann": series_of(lambda mk, c: pe_of(mk, c, "_ann")),
    }
    # 市場調整版
    ser["adj_pe"] = {}
    ser["adj_pe_ann"] = {}
    spx_stale = None
    for mk, v in ser["pe"].items():
        s, age = spx_at(spx, mk)
        if s:
            ser["adj_pe"][mk] = v / s
    for mk, v in ser["pe_ann"].items():
        s, age = spx_at(spx, mk)
        if s:
            ser["adj_pe_ann"][mk] = v / s

    s_now, spx_stale = spx_at(spx, now_mk)
    row["spx_pe"] = r(s_now, 2)
    if spx_stale:
        diag["spx_pe_stale_months"] = spx_stale
        nulls["spx_pe"] = (f"S&P500実績PERの系列は {spx_last} までしか無く "
                           f"{now_mk} は {spx_stale}ヶ月ぶん持ち越し")
    # S&P500 自身の歴史分位（asof 以前だけで取る＝look-ahead を作らない）
    if s_now:
        hist_spx = [v for k, v in spx.items() if k < now_mk]
        row["spx_pe_pct"] = r(pctile(hist_spx, s_now))
        diag["spx_pe_hist_months"] = len(hist_spx)
    else:
        row["spx_pe_pct"] = None

    row["px"] = r(px["close"].get(now_mk), 4)
    nxt = [m for m in px["close"] if m > now_mk]
    row["px_next_month"] = r(px["close"][min(nxt)], 4) if nxt else None
    if sh.get(now_mk):
        row["shares_today_basis"] = r(sh[now_mk], 0)
        row["mcap"] = r(px["close"][now_mk] * sh[now_mk], 0)

    extras = {}
    # 事前登録の指標 + 対照（_ann = 年次更新だけで組んだ版＝直近FY基準。
    # retro_per_asof.py の per と同じ基準なので、既存在庫との突合せはこちらで行う）
    for name in ("pe", "ps", "pfcf", "adj_pe", "pe_ann", "adj_pe_ann"):
        s = ser[name]
        now = s.get(now_mk)
        hist = [v for k, v in s.items() if k < now_mk]
        row[name] = r(now, 4)
        pct_key = f"{name}_pct" if not name.endswith("_ann") else f"{name[:-4]}_pct_ann"
        if now is None:
            row[pct_key] = None
            nulls.setdefault(name, _why_null(name, tl, sh, now_mk, basis_note))
        elif len(hist) < min_months:
            row[pct_key] = None
            nulls[pct_key] = f"自己履歴 {len(hist)}ヶ月 < 下限 {min_months}ヶ月"
        else:
            row[pct_key] = r(pctile(hist, now))
        row[f"{name}_hist_months"] = len(hist)
        if name in ("pe", "ps"):
            row[f"{name}_z"] = r(zscore(hist, now))
            extras[f"{name}_lz"] = r(zscore(hist, now, log=True))
        if hist:
            extras[f"{name}_median_hist"] = r(statistics.median(hist), 3)

    # 純利益が正でなくて PER が作れなかった月の数（分布の質）
    pe_possible = sum(1 for mk in months
                      if px["close"].get(mk) is not None and mk in sh and mk in tl["ni"])
    row["pe_neg_months"] = pe_possible - len(ser["pe"])
    row["hist_months"] = len([m for m in months if m < now_mk])
    row["hist_start"] = months[0] if months else None
    # 特別配当・スピンオフによる自己履歴の断絶（値は落とさず印だけ）
    mx, hits = big_distributions(px, months)
    if mx is not None:
        row["max_distrib_pct"] = r(mx, 4)
        row["distrib_break"] = bool(hits)
        if hits:
            diag["distributions"] = hits[:5]
            nulls["_distrib_break"] = (
                f"自己履歴の中で株価の{max(h['pct'] for h in hits)*100:.0f}%に当たる分配"
                f"（特別配当・スピンオフ）があった＝前後で同じ会社を測っていない。"
                f"値は残すが分位の解釈に注意")
    else:
        row["max_distrib_pct"] = None
        row["distrib_break"] = None
    _t = tl["ni"].get(now_mk)
    if _t:
        diag["ni_ttm_end"] = _t[1]
        diag["ni_ttm_age_days"] = (month_end(now_mk) - D(_t[1])).days
        diag["ni_ttm_method"] = _t[2]
    meth = {}
    for mk, t in tl["ni"].items():
        meth[t[2]] = meth.get(t[2], 0) + 1
    diag["ttm_method_months"] = meth
    # 「年次の決算しか当たっていない月」の割合＝読み取りの古さの指標
    #   （1.0 なら TTM と言いつつ実質は直近FY基準。0 に近いほど四半期で更新されている）
    row["ann_only_frac"] = r(meth.get("A_annual", 0) / max(sum(meth.values()), 1), 3)

    # EPSタグ版の PER（NI÷株数版との突合せ用。どちらを採るかは実測で決める）
    eps_now = tl["eps"].get(now_mk)
    if eps_now and eps_now[0] > 0 and row.get("px"):
        # EPS も「今日の株数基準」へ: 申告EPS ÷ S(filed)。
        # **TTM の窓の中で分割があった社は出さない**——四半期EPSは各期の加重平均株数で
        # 割られているので、分割をまたいで足すと基準の違う二つを足すことになる。
        # （この脆さこそ、主指標を「時価総額÷純利益」にした理由。純利益は株数に依らない）
        lo = (D(eps_now[1]) - dt.timedelta(days=400)).isoformat()
        if not any(lo <= s["date"] <= eps_now[1] for s in splits):
            f = split_factor_after(splits, eps_now[1])
            extras["pe_eps"] = r(px["close"][now_mk] / (eps_now[0] / f), 3)
            if row.get("pe"):
                extras["pe_eps_over_pe_mcap"] = r(extras["pe_eps"] / row["pe"], 4)
    for k, v in basis_note.items():
        if v:
            nulls.setdefault(f"src_{k}", v)
    row["extras"] = extras
    if keep_series:
        row["series"] = {k: {m: r(v, 4) for m, v in s.items()} for k, s in ser.items()}
    return row


def _why_null(name, tl, sh, now_mk, basis_note):
    # `_ann`（年次更新だけの対照）は **その系列**を見ないと理由が出せない。
    # ここを TTM 側で見ていたため「TTM はあるのに年次版が無い」社が全部
    # 中身のない『算出不能』になっていた（実測10件・ATEC/CMPR/DIOD/GEN/GSAT）。
    suf = "_ann" if name.endswith("_ann") else ""
    base = name.replace("adj_", "")[:len(name.replace("adj_", "")) - len(suf)] if suf \
        else name.replace("adj_", "")
    m = {"pe": "ni", "ps": "rev", "pfcf": "fcf"}.get(base, base)
    if not sh.get(now_mk):
        return "発行済株数がその月に無い（時価総額が作れない）"
    if m == "fcf":
        for src in ("ocf", "capex"):
            if basis_note.get(src):
                return f"{src}: {basis_note[src]}"
    if basis_note.get(m):
        return basis_note[m]
    t = tl.get(m + suf, {}).get(now_mk)
    if t is None:
        if suf:
            return (f"{m} の**年次決算だけ**の系列がその月に無い"
                    f"（直近の通期が古すぎる／通期が未提出。TTM 側は算出できている）")
        if m == "fcf":
            return "ocf と capex が同じ期末で揃う期が無い（別の期末どうしは引き算しない）"
        return f"{m} の TTM がその月に無い（決算が古すぎる/未提出）"
    if t[0] <= 0:
        return f"{m}{'(年次)' if suf else ''} が正でない（{t[0]:,.0f}）＝倍率が定義できない"
    return "算出不能"


# ── 入力 ─────────────────────────────────────────────────────────────────────
def load_tickers(path):
    """list[str] / list[{ticker,cik}] / {"rows":[...]} / {"sampled_tickers":[...]} / CSV を受ける。"""
    if path.lower().endswith(".csv"):
        out = []
        with open(path, newline="", encoding="utf-8") as f:
            for i, rec in enumerate(csv.reader(f)):
                if not rec:
                    continue
                t = rec[0].strip()
                if i == 0 and t.lower() in ("ticker", "symbol", "code"):
                    continue
                if t:
                    out.append({"ticker": t.upper(), "cik": None})
        return out
    j = json.load(open(path))
    rows = None
    if isinstance(j, list):
        rows = j
    elif isinstance(j, dict):
        for k in ("rows", "sampled_tickers", "tickers", "pass", "list"):
            if isinstance(j.get(k), list):
                rows = j[k] if rows is None else rows + j[k]
        if rows is None:
            rows = list(j.keys())
    out, seen = [], set()
    for x in rows or []:
        if isinstance(x, str):
            t, c = x.upper(), None
        elif isinstance(x, dict):
            t = str(x.get("ticker") or x.get("t") or "").upper()
            c = x.get("cik")
        else:
            continue
        if not t or t in seen:
            continue
        seen.add(t)
        out.append({"ticker": t, "cik": int(c) if c else None})
    return out


def main():
    ap = argparse.ArgumentParser(description="自己相対バリュエーションの採取器")
    ap.add_argument("--asof", default=dt.date.today().isoformat())
    ap.add_argument("--tickers")
    ap.add_argument("--t", help="ティッカー直指定（カンマ区切り）")
    ap.add_argument("--out")
    ap.add_argument("--window", type=int, default=0, help="自己履歴の年数（0=取れるだけ）")
    ap.add_argument("--min-months", type=int, default=36)
    ap.add_argument("--px-mode", default="le_asof", choices=("le_asof", "asof_month"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offline", action="store_true", help="キャッシュだけで動かす")
    ap.add_argument("--series", action="store_true", help="月次系列も出力（点検用・巨大）")
    a = ap.parse_args()

    asof = D(a.asof) if len(a.asof) == 10 else dt.date(int(a.asof), 7, 1)
    if a.t:
        items = [{"ticker": x.strip().upper(), "cik": None} for x in a.t.split(",") if x.strip()]
    elif a.tickers:
        items = load_tickers(a.tickers)
    else:
        ap.error("--tickers か --t が要る")
    if a.limit:
        items = items[:a.limit]

    tmap = ticker_map(offline=a.offline)
    spx, spx_last = load_spx()
    if not spx:
        print("⚠ out/sp500_pe_monthly.json が無い → adj_pe / spx_pe_pct は出ない")

    # **部分実行は正本を書かない**（2026-08-09・実際に踏んだ事故の是正）。
    #   `--t MSFT` の点検を --out 無しで回すと既定の出力先が
    #   out/hist_val_{年}.json ＝**そのビンテージの正本**になり、961社の在庫が
    #   MSFT 1社で上書きされる。実際に一度潰した（cacheから29秒で復元できたが、
    #   気づかなければ後段の検定が n=1 の在庫を読む）。
    #   CLAUDE.md が記録する `score_all.js --jp/--us が正本を部分集合で上書きしていた`
    #   とまったく同じ型なので、同じ作法で塞ぐ——**旗つきの実行は .partial へ**。
    partial = bool(a.t) or bool(a.limit)
    if a.out:
        out_path = a.out
    elif partial:
        out_path = os.path.join(BASE, "out", f"_partial_hist_val_{asof.year}.json")
        print(f"※ 部分実行（{'--t' if a.t else '--limit'}）なので正本ではなく {out_path} へ書く。"
              f"\n  正本を作り直すなら --tickers と --out を明示すること")
    else:
        out_path = os.path.join(BASE, "out", f"hist_val_{asof.year}.json")
    rows, t0 = [], time.time()
    for i, it in enumerate(items, 1):
        tk = it["ticker"]
        cik = it.get("cik") or tmap.get(tk)
        try:
            row = analyse(tk, cik, asof, spx, spx_last, a.window, a.min_months,
                          a.px_mode, a.offline, a.series)
        except Exception as e:
            row = {"ticker": tk, "cik": cik, "asof": asof.isoformat(),
                   "nulls": {"all": f"例外 {type(e).__name__}: {e}"}}
        rows.append(row)
        if a.t:
            print(json.dumps(row, ensure_ascii=False, indent=1))
        if i % 25 == 0 or i == len(items):
            ok = sum(1 for r_ in rows if r_.get("pe_pct") is not None)
            el = time.time() - t0
            print(f"  {i}/{len(items)}  pe_pct算出:{ok}  {el:.0f}s")
            _dump(out_path, asof, a, rows, items)
    _dump(out_path, asof, a, rows, items)
    ok = sum(1 for r_ in rows if r_.get("pe_pct") is not None)
    print(f"■ 書き出し: {out_path}  {len(rows)}社 / pe_pct {ok}社 "
          f"({100.0*ok/max(len(rows),1):.1f}%)")


def _dump(path, asof, a, rows, items):
    """途中経過も含めて **原子的に**書く。25社ごとに書き足すので、素で上書きすると
    読み手（別プロセスの検算器）が**書きかけの壊れたJSON**を掴む——実際に踏んだ。
    一時ファイルへ書いて os.replace で差し替えれば、読み手は必ず前後どちらかの完全な版を見る。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump({"generated": dt.date.today().isoformat(),
               "tool": "night/hist_valuation.py",
               # 採取器の版。**ビンテージ間で版が違う在庫を突き合わせない**ための印
               #（この台帳が5回踏んだ「基準の違う二つを割る」型を、在庫の側で見えるようにする）。
               # r2 = share_scale_guard（filer の桁誤りの申告を落とす）を入れた版。
               # 版が無い在庫＝r1 で、株数の桁誤りが分位を捏造している社を含む
               "tool_rev": "r2 (2026-08-09 share_scale_guard)",
               "asof": asof.isoformat(),
               "px_mode": a.px_mode, "window_years": a.window,
               "min_months": a.min_months,
               "n_input": len(items), "n_rows": len(rows),
               "basis": "TTM（trailing 12ヶ月）。倍率の分子は時価総額に統一",
               "rows": rows},
              open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
