# night/retro_delisted.py — 退場した社を母集団へ戻す（2026-08-09新設）
#
# ── なぜ要るか ─────────────────────────────────────────────────────────────
#   この台帳の retro 母集団は**全部ティッカー経由**で組まれている。ところが
#   SECのティッカー表は「**今日**の登録社」なので、ティッカーで絞ると
#   **その後に退場した社が最初から消える**。実測(hist_val_survivorship):
#     2013質実証 563 CIK → ティッカー有り 360（退場率 0.0%）／
#                          ティッカー無し 203（**退場率 75.9%**・Form15 148/Form25 5）
#     判定プール117社の恒久毀損は **0件**・最悪 −14.6%/年＝**−15%の線に一度も触れない**
#   CLAUDE.md は 2026-08-04 に案D（成長持続）で同じ罠を踏んで是正したが
#   （20-30%組の10年dropout 21.6%→**57.7%**）、**その是正はティッカー経由の
#   他の道具へ波及していない**。案C・retro_moat_durability・retro_breaker_test・
#   backtest_core は**すべて左尾を過小に測っている疑い**がある。この道具はその実数を出す。
#
# ── 何を測り、何を測らないか ────────────────────────────────────────────────
#   測る : 退場社の同定数／歴史ティッカーの解決数／価格が取れた数／
#          退場の**種類**（買収・破産・上場基準・非公開化・重複上場抹消…）／
#          左尾（元本割れ・恒久毀損）が**各ビンテージ・各プールで何件になるか**
#   測らない: 採点・合否・規約。**値は一つも動かさない**（絶対のルール1/6）
#
# ── 守っている作法 ──────────────────────────────────────────────────────────
#   ■ **退場＝全損と決めつけない**。プレミアム付き買収は勝ちで終わる。
#     退場の値は**最後に観測できた価格**で決め、その後は打ち切り（生存時間解析の形）。
#   ■ **ティッカーの使い回しを踏まない**（この作業で最初に踏んだ罠）。
#     実測: Yahoo で `DELL` を引くと 2016-08 開始の**再上場した別の Dell**、
#     `EMC` は 2023-05 開始の**まったく別の会社**が返る。退場日から大きく先へ
#     伸びる系列は**別会社**として棄却する（CLAUDE.md「基準の違う二つを割る」型）。
#   ■ **欠測をゼロと読むな**。ティッカーが解決できない／価格が取れない社は
#     「−100%」ではなく **unresolved / no_price** として数える。
#   ■ **上場株を持たない filer を母集団に入れない**。CIKには社債だけの子会社や
#     LLC が混じる（実測: CENTERPOINT ENERGY HOUSTON ELECTRIC, LLC ／ GCI, LLC ／
#     NORTHERN STATES POWER CO /WI/）。これらは**そもそも買えなかった**ので
#     「退場」ではなく **no_listed_equity**（母集団外）として分ける。
#   ■ 二重実装を作らない: 母集団は retro_cohort_{y}.json、質実証の定義は
#     hist_val_join.quality_for と同じ3条件、リターンの綴じ方は retro_fetch_returns と同じ
#     Yahoo adjclose（配当込み・遡及調整）。
#
# ── 段階（それぞれキャッシュ・再開可能）────────────────────────────────────
#   --subs    SEC submissions を採る（退場日・退場の種類・旧社名）
#   --map     CIK → **当時の**ティッカーを解決（AV LISTING_STATUS の名寄せ＋SEC旧社名）
#   --px      価格を採る（Yahoo adjclose・上の使い回し検問つき）
#   --av      Yahoo で取れなかった銘柄を Alpha Vantage で採る（MCP経由の手動投入）
#   (既定)    解析して out/retro_delisted_{vintage}.json を書く
#
# 実行:
#   python3 night/retro_delisted.py --vintage 2013 --subs
#   python3 night/retro_delisted.py --vintage 2013 --map
#   python3 night/retro_delisted.py --vintage 2013 --px
#   python3 night/retro_delisted.py --vintage 2013
import argparse
import collections
import csv
import datetime
import difflib
import gzip
import json
import math
import os
import re
import statistics as st
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
CACHE = os.path.join(OUT, "_delisted_cache")
SUBS = os.path.join(CACHE, "subs")
PX = os.path.join(CACHE, "px")
for d in (CACHE, SUBS, PX):
    os.makedirs(d, exist_ok=True)

SEC_UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com", "Accept-Encoding": "gzip"}
YH_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
HORIZON = "2026-08-04"          # 既存の retro_returns_* と同じ終端（基準を揃える）

# ── 名寄せ ─────────────────────────────────────────────────────────────────
SUF = (r'\b(INC|INCORPORATED|CORP|CORPORATION|CO|COS|COMPANY|COMPANIES|LTD|LIMITED|PLC|LP|LLC|'
       r'HOLDING|HOLDINGS|HLDGS|HLDG|GROUP|GRP|THE|OF|COM|COMMON|STOCK|SA|NV|AG|USA|US|'
       r'CLASS [A-Z]|CL [A-Z]|SER [A-Z]|NEW|TRUST|REIT|PARTNERS|ENTERPRISES)\b')


def norm(s):
    s = (s or "").upper()
    s = re.sub(r'/[A-Z]{2,3}[/ ]', ' ', s)      # SEC の /DE/ /NJ/ 等
    s = re.sub(r'&', 'AND', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(SUF, ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def tokkey(s):
    """語順に依らない鍵（SEC『BARD C R INC』 ↔ AV『C.R. Bard Inc』）"""
    return " ".join(sorted(norm(s).split()))


def compact(s):
    """空白まで畳んだ鍵。AVは区切りを**詰めて**綴ることがある
    （実測: SEC『SIGMA ALDRICH CORP』 ↔ AV『SigmaAldrich Corp』／
            SEC『ROCK-TENN CO』 ↔ AV『RockTenn Company』）"""
    return norm(s).replace(" ", "")


# ── SEC submissions ───────────────────────────────────────────────────────
def fetch_subs(cik):
    p = os.path.join(SUBS, f"{cik}.json")
    if os.path.exists(p):
        return json.load(open(p))
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=SEC_UA)
            with urllib.request.urlopen(req, timeout=40) as f:
                raw = f.read()
                if f.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            j = json.loads(raw)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                json.dump({"cik": cik, "missing": True}, open(p, "w"))
                return {"cik": cik, "missing": True}
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    else:
        return None
    rec = j.get("filings", {}).get("recent", {}) or {}
    forms = rec.get("form", []) or []
    dates = rec.get("filingDate", []) or []
    items = rec.get("items", []) or [""] * len(forms)
    ev = []
    for fm, dt, it in zip(forms, dates, items):
        if fm.startswith("25") or fm.startswith("15-") or fm == "8-K" or fm in (
                "SC 13E3", "SC 13E3/A", "DEFM14A", "S-4", "S-4/A"):
            ev.append({"form": fm, "date": dt, "items": it or ""})
    red = {
        "cik": cik,
        "name": j.get("name"),
        "tickers": j.get("tickers") or [],
        "exchanges": j.get("exchanges") or [],
        "sic": j.get("sic"),
        "sicDescription": j.get("sicDescription"),
        "formerNames": [x.get("name") for x in (j.get("formerNames") or [])],
        "last_filing": max(dates) if dates else None,
        "first_filing": min(dates) if dates else None,
        "n_10k": sum(1 for f in forms if f.startswith("10-K")),
        "last_10k": max([d for f, d in zip(forms, dates) if f.startswith("10-K")], default=None),
        "events": ev,
        "has_extra_files": bool(j.get("filings", {}).get("files")),
    }
    json.dump(red, open(p, "w"))
    return red


EXIT_FORMS = ("25", "25-NSE")


def classify_exit(sub, asof_date):
    """退場の日と**種類**を返す。決めつけない——判らなければ 'unknown'。"""
    if not sub or sub.get("missing"):
        return {"exit": "unknown", "why": "submissions取得不能"}
    ev = sub.get("events") or []
    f25 = [e for e in ev if e["form"] in EXIT_FORMS and e["date"] > asof_date]
    f15 = [e for e in ev if e["form"].startswith("15-") and e["date"] > asof_date]
    last = sub.get("last_filing")
    # 生存: 今日もティッカーを持つ or 直近2年に提出がある
    alive = bool(sub.get("tickers")) or (last and last >= "2024-08-01")
    if alive and not f25:
        return {"exit": None, "why": "生存（今日もティッカー有り or 直近提出あり）",
                "last_filing": last}
    date = min([e["date"] for e in (f25 or f15)], default=last)
    # 8-K の items で理由を分ける（退場日の前後180日）
    kinds = set()
    if date:
        lo = (datetime.date.fromisoformat(date) - datetime.timedelta(days=210)).isoformat()
        hi = (datetime.date.fromisoformat(date) + datetime.timedelta(days=60)).isoformat()
        for e in ev:
            if e["form"] != "8-K" or not (lo <= e["date"] <= hi):
                continue
            it = e["items"]
            if "1.03" in it:
                kinds.add("bankruptcy")
            if "5.01" in it:
                kinds.add("change_of_control")
            if "2.01" in it:
                kinds.add("completion_of_acquisition")
            if "3.01" in it:
                kinds.add("listing_deficiency")
    has13e3 = any(e["form"].startswith("SC 13E3") for e in ev)
    if "bankruptcy" in kinds:
        kind = "bankruptcy"
    elif "change_of_control" in kinds or "completion_of_acquisition" in kinds:
        kind = "going_private" if has13e3 else "acquired"
    elif has13e3:
        kind = "going_private"
    elif "listing_deficiency" in kinds:
        kind = "listing_deficiency"
    elif f25 or f15:
        kind = "deregistered"
    else:
        kind = "stopped_filing"
    return {"exit": date, "kind": kind, "signals": sorted(kinds),
            "form25": bool(f25), "form15": bool(f15), "sc13e3": has13e3,
            "last_filing": last}


# ── 価格 ───────────────────────────────────────────────────────────────────
def yahoo(sym, t0):
    p = os.path.join(PX, f"YH_{sym.replace('/','-')}.json")
    if os.path.exists(p):
        return json.load(open(p))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={t0}&period2={int(time.time())}&interval=1mo")
    out = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=YH_UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                out = {"pts": [], "err": "no-result"}
                break
            ts = res.get("timestamp") or []
            adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
            pts = [[datetime.date.fromtimestamp(t).isoformat(), v]
                   for t, v in zip(ts, adj) if v is not None]
            out = {"pts": pts}
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 401):
                out = {"pts": [], "err": f"HTTP{e.code}"}
                break
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            out = {"pts": [], "err": type(e).__name__}
            time.sleep(2 * (attempt + 1))
    if out is None:
        out = {"pts": [], "err": "retry-exhausted"}
    json.dump(out, open(p, "w"))
    return out


def load_av(sym):
    """--av で投入した Alpha Vantage の系列（out/_delisted_cache/px/AV_{sym}.json）"""
    p = os.path.join(PX, f"AV_{sym.replace('/','-')}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def pick(pts, day, tol_days=95):
    """day 以前で最も近い観測。無ければ day 以後 tol_days 以内の最初の観測。"""
    if not pts:
        return None
    d = datetime.date.fromisoformat(day)
    before = [p for p in pts if datetime.date.fromisoformat(p[0]) <= d]
    if before:
        return before[-1]
    after = [p for p in pts if 0 <= (datetime.date.fromisoformat(p[0]) - d).days <= tol_days]
    return after[0] if after else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, default=2013)
    ap.add_argument("--subs", action="store_true")
    ap.add_argument("--map", action="store_true")
    ap.add_argument("--px", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    Y = a.vintage
    asof = f"{Y}-07-01"
    t0 = int(datetime.datetime(Y, 7, 1).timestamp())

    coh = json.load(open(os.path.join(OUT, f"retro_cohort_{Y}.json")))
    rows = coh["rows"]

    # ── --subs ────────────────────────────────────────────────────────────
    if a.subs:
        todo = [r for r in rows if not os.path.exists(os.path.join(SUBS, f"{r['cik']}.json"))]
        if a.limit:
            todo = todo[:a.limit]
        print(f"submissions: {len(todo)}社を採る（既存 {len(rows)-len(todo)}）")
        for i, r in enumerate(todo):
            fetch_subs(r["cik"])
            time.sleep(0.11)                       # SEC 10req/s
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(todo)}")
        print("done")
        return

    # ── --map ─────────────────────────────────────────────────────────────
    if a.map:
        # 手動の対応表（根拠つき）。機械が裏を取れない社だけをここに置く
        mpp = os.path.join(CACHE, f"manual_map_{Y}.json")
        manual = json.load(open(mpp)) if os.path.exists(mpp) else {}
        # ── 名簿の作り方（ここで一度間違えた。記録する価値がある）──────────────
        #   AV LISTING_STATUS?date=asof は **asof に売買できた銘柄の名簿**を返すが、
        #   名前は「その symbol の記録の**今日の**名前」＝**使い回された symbol は
        #   後の会社の名前で返る**（実測: ALTR は 2013年 Altera だが AV の退場表では
        #   Altair Engineering／MON は Monsanto だが Monument Circle Acquisition／
        #   NSR は NeuStar だが Nomad Royalty／EDR は Education Realty だが Endeavor）。
        #   最初の実装は退場表を先に読んで setdefault したので**後の会社の名前が勝ち**、
        #   Altera・Monsanto・NeuStar・Education Realty・Mindray が丸ごと未解決になっていた。
        #   → **asof の名簿を正**にし、退場表は「asof 以後に退場した行」だけを
        #     別名として足す（＝退場した社の当時の名前を拾うため）。
        roster_p = os.path.join(CACHE, f"av_active_{Y}.csv")
        if not os.path.exists(roster_p):
            print(f"  ! av_active_{Y}.csv が無い（AV LISTING_STATUS?date={asof} を先に採る）")
            return
        av, alias = {}, collections.defaultdict(set)
        for r in csv.DictReader(open(roster_p)):
            if r.get("assetType") != "Stock":
                continue
            av[r["symbol"]] = r
            if r.get("name"):
                alias[r["symbol"]].add(r["name"])
        #   **どちらの表も単独では不完全**（これも実測で分かった）——asof名簿には
        #   PCP(プレシジョン・キャストパーツ・当時S&P500) / LLTC / FDC / QLGC / LXK /
        #   APOL / AMSG / EQY が**入っていない**のに、退場表には正しい当時の名前と
        #   退場日で載っている。→ **和集合**を取る。名簿にある symbol は名簿を正とし
        #   （使い回し対策）、名簿に無い symbol は「asof 以後に退場した行」に限って足す
        #   （asof より前に退場した行は、同じ symbol を先に使っていた別の証券）。
        dp = os.path.join(CACHE, "av_delisted.csv")
        n_add = 0
        if os.path.exists(dp):
            for r in csv.DictReader(open(dp)):
                if r.get("assetType") != "Stock" or not r.get("name"):
                    continue
                dl = r.get("delistingDate")
                if not (dl and dl not in ("null", "None") and dl >= asof):
                    continue
                if r["symbol"] in av:
                    alias[r["symbol"]].add(r["name"])
                    av[r["symbol"]]["delistingDate"] = dl
                else:
                    av[r["symbol"]] = r
                    alias[r["symbol"]].add(r["name"])
                    n_add += 1
        print(f"  名簿 {len(av)-n_add} + 退場表からの補充 {n_add}")
        # **時代の検問**: そのビンテージの asof より前に退場した AV 行は、
        # 同じ名前を先に使っていた**別の証券**（実測: VAL は 2013年 Valspar・今日は Valaris／
        # HOT は 2013年 Starwood・今日はETF）。母集団の社ではありえないので候補から外す。
        exact, tok, comp = (collections.defaultdict(list), collections.defaultdict(list),
                            collections.defaultdict(list))
        for sym, r in av.items():
            for nm in alias[sym]:
                exact[norm(nm)].append(r)
                tok[tokkey(nm)].append(r)
                comp[compact(nm)].append(r)
        out = {}
        for r in rows:
            cik = r["cik"]
            sub = fetch_subs(cik) if os.path.exists(os.path.join(SUBS, f"{cik}.json")) else None
            names = [r["name"]] + list((sub or {}).get("formerNames") or [])
            cand, how = [], None
            if r.get("has_ticker") and r.get("ticker"):
                cand, how = [r["ticker"]], "cohort(今日のティッカー)"
            else:
                for label, idx, key in (("AV名一致", exact, norm),
                                        ("AV語順非依存一致", tok, tokkey),
                                        ("AV詰め綴り一致", comp, compact)):
                    for nm in names:
                        c = idx.get(key(nm)) or []
                        if c:
                            cand, how = c, label
                            break
                    if cand:
                        break
                if not cand:
                    # 近似一致は**それだけでは採らない**。実測で作った偽の一致:
                    #   『Capital Financial Holdings』→COF(Capital One) ／
                    #   『TESSERA TECHNOLOGIES』→TESS(Tessco) ／
                    #   『SIMON PROPERTY GROUP, L.P.』→SPG(上場しているのは Inc の方)
                    # ＝名前の近さは同一性の証拠にならない。**独立の裏取り**を要求する:
                    #   AVの退場日 と SECの退場日（Form25/15）が 400日以内で一致すること。
                    # 裏が取れない近似は unresolved のまま残す（誤値より空欄）。
                    exd = classify_exit(sub, asof).get("exit") if sub else None
                    best, bs = None, 0.0
                    for nm in names:
                        k = compact(nm)
                        if len(k) < 5:
                            continue
                        for kk, lst in comp.items():
                            if kk[:4] != k[:4]:
                                continue
                            sc = difflib.SequenceMatcher(None, k, kk).ratio()
                            if sc > bs:
                                best, bs = lst, sc
                    if best and bs >= 0.90 and exd and exd != "unknown":
                        ok = []
                        for x in best:
                            dl = x.get("delistingDate")
                            if dl and dl not in ("null", "None"):
                                gap = abs((datetime.date.fromisoformat(dl) -
                                           datetime.date.fromisoformat(exd)).days)
                                if gap <= 400:
                                    ok.append(x)
                        if ok:
                            cand, how = ok, f"AV近似一致+退場日一致({bs:.2f})"
                cand = sorted({x["symbol"] for x in cand})
                if len(cand) > 1:
                    # 同名で複数出るのは**優先株・ユニット・種類株**（実測: SO に対し
                    # SOJA/SOJB、NS に対し NS-P-A…）。普通株は「区切り記号が無く短い」。
                    plain = [s for s in cand if "-" not in s and " " not in s]
                    if plain:
                        cand = [min(plain, key=lambda s: (len(s), s))]
                        how = (how or "") + "+普通株選択"
                if not cand:
                    man = manual.get(str(cik))
                    if man and man.get("ticker"):
                        cand, how = [man["ticker"]], f"手動({man.get('evidence','根拠なし')})"
            out[str(cik)] = {"cik": cik, "name": r["name"], "cands": cand, "how": how,
                             "delist": {s: av[s].get("delistingDate") for s in cand if s in av},
                             "avname": {s: av[s].get("name") for s in cand if s in av}}
        json.dump(out, open(os.path.join(CACHE, f"map_{Y}.json"), "w"), ensure_ascii=False)
        n1 = sum(1 for v in out.values() if len(v["cands"]) == 1)
        nm = sum(1 for v in out.values() if not v["cands"])
        print(f"map: 一意 {n1} / 曖昧 {len(out)-n1-nm} / 未解決 {nm}（全{len(out)}）")
        return

    # ── --px ──────────────────────────────────────────────────────────────
    mp = json.load(open(os.path.join(CACHE, f"map_{Y}.json")))
    if a.px:
        syms = sorted({s for v in mp.values() for s in v["cands"]})
        todo = [s for s in syms if not os.path.exists(os.path.join(PX, f"YH_{s.replace('/','-')}.json"))]
        if a.limit:
            todo = todo[:a.limit]
        print(f"px: {len(todo)}銘柄をYahooで採る（既存 {len(syms)-len(todo)}）")
        for i, s in enumerate(todo):
            yahoo(s, t0)
            time.sleep(0.45)
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(todo)}")
        print("done")
        return

    # ── 解析 ──────────────────────────────────────────────────────────────
    mpp = os.path.join(CACHE, f"manual_map_{Y}.json")
    manual = json.load(open(mpp)) if os.path.exists(mpp) else {}
    bench = yahoo("SPY", t0)["pts"]
    b0, b1 = pick(bench, asof), bench[-1] if bench else None
    bench_mult = (b1[1] / b0[1]) if (b0 and b1) else None
    HZ = datetime.date.fromisoformat(HORIZON)
    full_years = (HZ - datetime.date.fromisoformat(asof)).days / 365.25

    res = []
    for r in rows:
        cik = r["cik"]
        m = mp.get(str(cik)) or {"cands": [], "how": None, "delist": {}}
        sub = fetch_subs(cik) if os.path.exists(os.path.join(SUBS, f"{cik}.json")) else None
        ex = classify_exit(sub, asof)
        quality = bool(r.get("op_all_pos")) and bool(r.get("fcf_all_pos")) and \
            ((r.get("opm") or -1) >= 0.10)
        row = {"cik": cik, "name": r["name"], "score": r.get("score"),
               "quality": quality, "opm": r.get("opm"), "roic_med5": r.get("roic_med5"),
               "sales_cagr5": r.get("sales_cagr5"),
               "has_ticker_today": bool(r.get("has_ticker")),
               "ticker_hist": None, "resolve": m.get("how"), "cands": m["cands"],
               "exit_date": ex.get("exit"), "exit_kind": ex.get("kind"),
               "exit_signals": ex.get("signals"), "sic": (sub or {}).get("sic"),
               "n_10k": (sub or {}).get("n_10k"), "last_filing": (sub or {}).get("last_filing"),
               "px_src": None, "status": None,
               "start": None, "end": None, "years": None,
               "tr_total": None, "tr_cagr": None, "tr_cagr_reinvest": None, "mdd": None}

        # 上場株を持たない filer（社債だけの子会社・LP・従業員持株）は母集団外
        man = manual.get(str(cik))
        if man and man.get("listed") is False:
            row["status"] = "no_listed_equity"
            row["why"] = man.get("evidence")
        elif not m["cands"]:
            row["status"] = "unresolved"
        # §15(d)だけの報告義務で消えた社は「取引所に上場していなかった」印
        # （15-12B=§12(b)登録=取引所上場 / 15-15D=募集に伴う報告義務のみ）
        f = [e["form"] for e in ((sub or {}).get("events") or [])]
        row["dereg_form"] = ("15-12B" if any(x.startswith("15-12B") for x in f) else
                             "15-12G" if any(x.startswith("15-12G") for x in f) else
                             "15-15D" if any(x.startswith("15-15D") for x in f) else None)
        res.append((row, m, ex))

    # 価格の綴じ込み（使い回しの検問つき）
    for row, m, ex in res:
        best = None
        for s in m["cands"]:
            src, d = "yahoo", yahoo(s, t0)
            pts = d.get("pts") or []
            if not pts:
                av = load_av(s)
                if av and av.get("pts"):
                    pts, src = av["pts"], "alphavantage"
            if not pts:
                continue
            p0 = pick(pts, f"{Y}-07-01")
            if not p0:
                row["status"] = row["status"] or "no_start"
                continue
            # ── 同一性の検問（**穴で切る**）──────────────────────────────
            #   月次の系列に9ヶ月超の穴があれば、そこで証券が入れ替わっている
            #   （退場 → 別の会社が同じ symbol で後に上場）。**棄却ではなく
            #   穴の手前で切る**——手前は当の会社の実データだから使える。
            #   一方 **穴が無いまま退場日を越えて続く系列は改称・再編の承継**
            #   （実測: Avago→Broadcom の AVGO ／ Mylan Inc→Mylan N.V. の MYL）で、
            #   1株が1株になっているので切ってはいけない。
            cut = None
            for i in range(1, len(pts)):
                d0 = datetime.date.fromisoformat(pts[i - 1][0])
                d1 = datetime.date.fromisoformat(pts[i][0])
                if (d1 - d0).days > 270 and pts[i - 1][0] > p0[0]:
                    cut = i
                    break
            corr, note = None, None
            if cut:
                note = f"系列に穴({pts[cut-1][0]}→{pts[cut][0]})＝別証券とみて手前で切る"
                pts = pts[:cut]
            last = pts[-1]
            exd = ex.get("exit")
            if exd and exd != "unknown":
                gap = (datetime.date.fromisoformat(last[0]) -
                       datetime.date.fromisoformat(exd)).days
                corr = "strong" if abs(gap) <= 400 else ("continuous" if gap > 400 else "early_end")
            elif last[0] >= HORIZON[:7]:
                corr = "alive_to_horizon"
            row["corroboration"], row["px_note"] = corr, note
            # 手動の仮説は**裏が取れたときだけ**採る（誤値より空欄）
            if (m.get("how") or "").startswith("手動") and corr not in (
                    "strong", "continuous", "alive_to_horizon"):
                row["status"] = "manual_unverified"
                continue
            if best is None or len(pts) > len(best[1]):
                best = (s, pts, src, p0, last)
        if best is None:
            row["status"] = row["status"] or "no_price"
            continue
        s, pts, src, p0, last = best
        row.update(ticker_hist=s, px_src=src, start=p0[0], end=last[0])
        yrs = (datetime.date.fromisoformat(last[0]) - datetime.date.fromisoformat(p0[0])).days / 365.25
        row["years"] = round(yrs, 2)
        mult = last[1] / p0[1]
        row["tr_total"] = round(mult, 4)
        row["tr_cagr"] = round(mult ** (1 / yrs) - 1, 4) if yrs >= 0.5 else None
        peak, mdd = p0[1], 0.0
        for _, v in pts:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        row["mdd"] = round(mdd, 3)
        # 退場後は指数へ再投資（ポートフォリオとしての全期間換算）
        if last[0] >= HORIZON[:7]:
            row["tr_cagr_reinvest"] = row["tr_cagr"]
            row["status"] = row["status"] or "survivor"
        else:
            bx = pick(bench, last[0])
            if bx and b1 and bench_mult:
                m2 = mult * (b1[1] / bx[1])
                row["tr_cagr_reinvest"] = round(m2 ** (1 / full_years) - 1, 4)
            row["status"] = row["status"] or "exited"

    rows_out = [r for r, _, _ in res]

    # ── 左尾がどれだけ戻ったか ────────────────────────────────────────────
    def tail(rs, key):
        v = [r[key] for r in rs if r.get(key) is not None]
        if not v:
            return {"n": 0}
        loss = [x for x in v if x < 0]
        imp = [x for x in v if x <= -0.15]
        return {"n": len(v), "median": round(st.median(v), 4), "min": round(min(v), 4),
                "元本割れ": len(loss), "元本割れ率": round(len(loss) / len(v), 4),
                "恒久毀損": len(imp), "恒久毀損率": round(len(imp) / len(v), 4),
                # 0件は真のゼロではない: 95%上端(3/n)
                "恒久毀損率95%上端": round(3 / len(v), 4) if not imp else None}

    have = [r for r in rows_out if r.get("tr_cagr") is not None]
    old = [r for r in have if r["has_ticker_today"]]          # 従来＝ティッカー経由
    summ = {}
    for label, sel in (("全社", lambda r: True), ("質実証", lambda r: r["quality"])):
        o, n = [r for r in old if sel(r)], [r for r in have if sel(r)]
        summ[label] = {
            "旧(ティッカー経由)": tail(o, "tr_cagr"),
            "新(退場込み・打ち切りCAGR)": tail(n, "tr_cagr"),
            "新(退場込み・退場後は指数へ再投資)": tail(n, "tr_cagr_reinvest"),
            "戻した社数": len(n) - len(o),
        }
    bykind = {}
    for k in sorted({r["exit_kind"] for r in have if r["status"] == "exited" and r["exit_kind"]}):
        g = [r for r in have if r["exit_kind"] == k and r["status"] == "exited"]
        v = [r["tr_cagr"] for r in g if r["tr_cagr"] is not None]
        bykind[k] = {"n": len(g), "median_cagr": round(st.median(v), 4) if v else None,
                     "元本割れ": sum(1 for x in v if x < 0),
                     "恒久毀損": sum(1 for x in v if x <= -0.15)}

    out = {"generated": datetime.date.today().isoformat(),
           "tool": "night/retro_delisted.py", "vintage": Y, "asof": asof,
           "horizon": HORIZON, "benchmark_mult_SPY": round(bench_mult, 3) if bench_mult else None,
           "n": len(rows_out),
           "funnel": dict(collections.Counter(r["status"] for r in rows_out)),
           "resolve": dict(collections.Counter((r["resolve"] or "なし").split("(")[0]
                                               for r in rows_out)),
           "corroboration": dict(collections.Counter(r.get("corroboration") or "なし"
                                                     for r in rows_out)),
           "left_tail": summ, "by_exit_kind": bykind, "rows": rows_out}
    p = a.json or os.path.join(OUT, f"retro_delisted_{Y}.json")
    json.dump(out, open(p, "w"), ensure_ascii=False)
    c = collections.Counter(r["status"] for r in rows_out)
    print(f"{Y}: {len(rows_out)}社 / " + " / ".join(f"{k}:{v}" for k, v in c.most_common()))
    for lab, d in summ.items():
        print(f"  [{lab}] 旧 n={d['旧(ティッカー経由)']['n']} 毀損{d['旧(ティッカー経由)'].get('恒久毀損')} "
              f"→ 新 n={d['新(退場込み・打ち切りCAGR)']['n']} 毀損{d['新(退場込み・打ち切りCAGR)'].get('恒久毀損')}")
    print("→", p)


if __name__ == "__main__":
    main()
