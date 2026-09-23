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
# ── 退場の判定 v2（2026-09-23・todo retro_exit_date_form15）────────────────────────
#   v1 の classify_exit は「asof 以後の最初の Form 25（無ければ Form 15）」を退場日にしていた。
#   **Form 25 も Form 15 も証券の種類ごとに出る**ので、社債・優先株・買収防衛の権利の抹消が
#   普通株の退場に化けた（実測: 退場日の後に10-Kを出していた社が 807社中158社。
#   Masimo は 2016-02-17 の『Preferred Stock Purchase Rights』の Form 25 を退場にされ、
#   本当の退場は 2026-06-10 の Danaher による買収完了だった）。
#   v2 は **原本の『証券の種類』の欄を読み**（Form 25-NSE は XML の descriptionClassSecurity、
#   発行体の Form 25 と Form 15 は表紙の欄）、普通株の抹消だけを候補にし、さらに
#   合併完了8-K（2.01∧(3.01∨5.01)）・破産8-K（1.03）・**定期報告の停止**で裏を取る
#   （規則の全文は classify_exit の docstring）。退場日は**合併完了8-Kの日を優先**する
#   （retro_delisted_secpx の回避策と同じ）。
#
# ── 段階（それぞれキャッシュ・再開可能）────────────────────────────────────
#   --subs     SEC submissions を採る（**全履歴**・定期報告の日付・Form 25/15 の原本の在処）
#   --exitdocs asof 以後の Form 25/15 の原本を採り、証券の種類を読む
#   --map      CIK → **当時の**ティッカーを解決（AV LISTING_STATUS の名寄せ＋SEC旧社名）
#   --px       価格を採る（Yahoo adjclose・上の使い回し検問つき）
#   --av       Yahoo で取れなかった銘柄を Alpha Vantage で採る（MCP経由の手動投入）
#   (既定)     解析して out/retro_delisted_{vintage}.json を書く
#   --reexit   前回の出力の**価格欄を運び、退場の欄だけ**を v2 で引き直す
#              （Yahoo は上場廃止銘柄の履歴を消すので、今日採り直すと是正と無関係に行が動く）
#
# 実行:
#   python3 night/retro_delisted.py --vintage 2013 --subs
#   python3 night/retro_delisted.py --vintage 2013 --exitdocs
#   python3 night/retro_delisted.py --vintage 2013 --map
#   python3 night/retro_delisted.py --vintage 2013 --px
#   python3 night/retro_delisted.py --vintage 2013
#   python3 night/retro_delisted.py --vintage 2013 --reexit     # 退場の欄だけ引き直す
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
#   v2（2026-09-23・retro_exit_date_form15 の是正）: **全履歴**を読む。
#   v1 は `filings.recent`（直近1000件）しか読まず、提出の多い社は 2013-2016年の
#   Form 25/15・8-K が別ページ（filings.files）に落ちて見えていなかった
#   （実測 Masimo: recent は 2016-02-15 以降だけ）。さらに v1 は
#   **普通株の定期報告（10-K/10-Q/20-F/40-F）の日付**と **Form 25/15 の原本の在処**
#   （accession・primaryDocument）を捨てていたので、「その退場は普通株のものか」を
#   確かめる材料が手元に無かった。v2 はその二つを残す。
SUBS_V = 2
PERIODIC = ("10-K", "10-K405", "10-KSB", "10-KSB40", "10-KT", "10-Q", "10-QSB", "10-QT",
            "20-F", "40-F")                     # 修正（/A）は数えない＝遅れて出るので停止日を歪める
EVENT_FORMS = ("8-K", "SC 13E3", "SC 13E3/A", "DEFM14A", "DEFM14C", "PREM14A", "S-4", "S-4/A",
               "SC TO-T", "SC TO-T/A", "SC 14D9", "SC 14D9/A")


def is_removal_form(fm):
    """普通株の退場の**候補**になる様式（Form 25＝上場廃止 / Form 15・15F＝登録抹消）。
    **候補であって退場ではない**——どちらも『証券の種類ごと』に出るので、
    社債・優先株・権利の抹消でも同じ様式が立つ（是正の本体は classify_exit）。"""
    return (fm in ("25", "25-NSE", "25/A", "25-NSE/A") or fm.startswith("15-")
            or fm.startswith("15F-"))


def _sec_json(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=SEC_UA)
            with urllib.request.urlopen(req, timeout=40) as f:
                raw = f.read()
                if f.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            time.sleep(0.11)                       # SEC 10req/s
            return json.loads(raw), None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, 404
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None, "retry-exhausted"


def fetch_subs(cik, since="2012-06-01"):
    p = os.path.join(SUBS, f"{cik}.json")
    if os.path.exists(p):
        j = json.load(open(p))
        if j.get("v") == SUBS_V or j.get("missing"):
            return j
    j, err = _sec_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if j is None:
        if err == 404:
            json.dump({"cik": cik, "missing": True, "v": SUBS_V}, open(p, "w"))
            return {"cik": cik, "missing": True, "v": SUBS_V}
        return None
    pages = [j.get("filings", {}).get("recent", {}) or {}]
    older = j.get("filings", {}).get("files") or []
    n_pages_read = 0
    for fx in older:
        # asof より前しか持たないページは読まない（退場の候補は asof より後にしか無い）
        if (fx.get("filingTo") or "9999") < since:
            continue
        pj, perr = _sec_json(f"https://data.sec.gov/submissions/{fx['name']}")
        if pj is None:
            return None                            # 半端な履歴で判定しない（誤値より空欄）
        pages.append(pj)
        n_pages_read += 1
    forms, dates, items, accs, docs = [], [], [], [], []
    for pg in pages:
        n = len(pg.get("form") or [])
        forms += pg.get("form") or []
        dates += pg.get("filingDate") or []
        items += (pg.get("items") or [""] * n)
        accs += (pg.get("accessionNumber") or [""] * n)
        docs += (pg.get("primaryDocument") or [""] * n)
    ev, per = [], []
    for fm, dt, it, acc, doc in zip(forms, dates, items, accs, docs):
        if fm in PERIODIC:
            per.append([dt, fm])
        if is_removal_form(fm) or fm in EVENT_FORMS:
            ev.append({"form": fm, "date": dt, "items": it or "", "acc": acc, "doc": doc or ""})
    ev.sort(key=lambda e: (e["date"], e["form"]))
    per.sort()
    red = {
        "v": SUBS_V,
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
        "periodic": per,
        "events": ev,
        "has_extra_files": bool(older),
        "older_pages_read": n_pages_read,
    }
    json.dump(red, open(p, "w"))
    return red


EXIT_FORMS = ("25", "25-NSE")        # v1 の名残（外部から参照されうるので残す）

# ── Form 25/15 の原本から「どの種類の証券の抹消か」を読む（v2・2026-09-23）──────────
#   **Form 15 も Form 25 も証券の種類ごとに出る**。v1 は様式だけを見ていたので
#   社債・優先株・買収防衛の権利の抹消が**普通株の退場**に化けた。実測:
#     Masimo(937556) 2016-02-17 Form 25 ＝『Preferred Stock Purchase Rights』（権利の失効）
#       → v1 は退場日 2016-02-17。本当の退場は **2026-06-10 Danaher による買収完了**
#         （8-K item 2.01/3.01/5.01 と Form 25-NSE『Common Stock』が同じ日）。
#   **機械で読める**: Form 25-NSE は XML の <descriptionClassSecurity>、
#   発行体の Form 25 は『(Description of class of securities)』の直前、
#   Form 15 は『(Title of each class of securities covered by this Form)』の直前に種類が書いてある
#   （Form 15 はさらに『Titles of all other classes … remains』に**残る種類**まで書く）。
EXITDOCS = os.path.join(CACHE, "exitdocs")
os.makedirs(EXITDOCS, exist_ok=True)
POST_EXIT_GRACE = 120      # 退場の後この日数を過ぎて出た定期報告＝「提出が続いている」
                           # （12月に抹消した社が翌3月に最後の10-Kを出すのは停止のうち。実測 Psychemedics）
MERGER_WIN = (-150, 45)    # 普通株の抹消の前後で、合併完了8-K を同じ出来事とみなす窓
BANKR_WIN = (-730, 30)     # 普通株の抹消の前後で、破産8-K(1.03) を同じ出来事とみなす窓
                           # （上場廃止は申立ての**後**に来る。抹消の後の申立ては別の出来事）
ALIVE_DAYS = 450           # 地平の手前この日数以内に定期報告があれば「提出を続けている」

_CLS_LABELS = [
    # 発行体の Form 25（取引所の古い版も同じ文言）
    re.compile(r"\(\s*Description\s+of\s+(?:the\s+)?class(?:es)?\s+of\s+securities?\s*\)", re.I),
    # Form 15 / 15F
    re.compile(r"\(\s*Titles?\s+of\s+each\s+class\s+of\s+(?:equity\s+)?securities?\s+"
               r"covered\s+by\s+this\s+Form\s*\)", re.I),
    re.compile(r"\(\s*Title\s+of\s+(?:each\s+)?class\s+of\s+(?:equity\s+)?securities?\s*\)", re.I),
]
_CLS_REMAIN = re.compile(r"\(\s*Titles?\s+of\s+all\s+other\s+classes\s+of\s+securities[^)]{0,160}\)",
                         re.I)
_CLS_PREV = re.compile(r"(?i)(executive\s+offices?\s*\)|registrant.s\s+principal[^)]{0,80}\)|"
                       r"\(\s*Commission\s+File\s+Number\s*\)|charter\s*\)|registered\s*\)|"
                       r"area\s+code\s*\)|"
                       r"Exchange\s+where\s+security\s+is\s+listed\s+and/or\s+registered\s*\))")


def _html_text(s):
    s = re.sub(r"(?is)<(script|style|ix:header).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    try:
        import html as _h
        s = _h.unescape(s)
    except Exception:
        pass
    return re.sub(r"\s+", " ", s)


def _parse_class(raw):
    """原本から (種類の文言, 残る種類の文言, 読み方) を返す。読めなければ (None, None, why)。"""
    m = re.search(r"<descriptionClassSecurity>\s*(.*?)\s*</descriptionClassSecurity>", raw, re.S | re.I)
    if m:
        return _html_text(m.group(1)).strip(), None, "xml"
    t = _html_text(raw)
    for lab in _CLS_LABELS:
        mm = lab.search(t)
        if not mm:
            continue
        pre = t[max(0, mm.start() - 700):mm.start()]
        cut = None
        for pm in _CLS_PREV.finditer(pre):
            cut = pm.end()
        cls = (pre[cut:] if cut is not None else pre[-320:]).strip(" |:;,.")
        rem = None
        rm = _CLS_REMAIN.search(t, mm.end())
        if rm and rm.start() - mm.end() < 700:
            rem = t[mm.end():rm.start()].strip(" |:;,.")
        return cls[-700:], rem, "label"
    return None, None, "no_label"


# 種類の判定。**普通株（と同等の持分）かどうかだけ**を問う。
#   普通株と同等に数えるもの: Common Stock / Common Shares / Ordinary Shares / ADS・ADR /
#   Shares of Beneficial Interest（REIT）/ Common Units・LP Units（MLP）/ Capital Stock
#   そうでないもの: Notes/Debentures/Bonds・Preferred・Warrants・Rights・Units(SPAC等)
_EQ = re.compile(r"(?i)\b(common\s+(?:stock|shares?|units?|equity)|ordinary\s+shares?|"
                 r"american\s+deposit[ao]ry\s+(?:shares?|receipts?)|deposit[ao]ry\s+receipts?|"
                 r"\bADSs?\b|\bADRs?\b|registered\s+shares?|class\s+[a-c]\s+common\s*$|"
                 r"limited\s+liability\s+company\s+interests?|"
                 r"(?:shares?\s+of\s+)?beneficial\s+interests?|capital\s+stock|"
                 r"limited\s+partner(?:ship)?\s+(?:interests?|units?)|partnership\s+units?|"
                 r"units?\s+representing\s+limited|class\s+[a-c]\s+(?:shares?|stock|units?)|"
                 r"(?<!preferred\s)(?<!depositary\s)shares\s+of\s+(?:the\s+)?(?:registrant|company|"
                 r"issuer)|^\s*(?:class\s+[a-c]\s+)?shares?\s*[,(]|^\s*shares?\s*$|"
                 r"^\s*common\s*(?:[,(]|$))")
_NONEQ = re.compile(r"(?i)(\bnotes?\b|debentures?|\bbonds?\b|\bdue\s+(?:19|20)\d\d|"
                    r"plan\s+(?:participation\s+)?interests?|interests?\s+in\s+(?:the\s+)?[^|]{0,80}?plan\b|"
                    r"\bpreferred\b|\bwarrants?\b|\brights?\b|trust\s+(?:preferred|securities)|"
                    r"capital\s+securities|\bguarantee|\bcertificates?\b|\bunits?\b|"
                    r"income\s+(?:prides|equity)|\bprides\b|\bpiers\b|\bquips\b|\btops\b|"
                    r"\d+(?:\.\d+)?\s*%)")


# 普通株に**付いてくる**権利（買収防衛のポイズンピル）は普通株の抹消の文言の一部であって、
# 別の種類ではない（実測: 『Common Stock, par value $.01 per share (and associated Preferred
# Stock Purchase Rights)』）。先に外してから種類を読む。
_ATTACHED = re.compile(r"(?i)[(\[]?\s*(?:and|together\s+with|including|with)\s+(?:the\s+)?"
                       r"(?:associated|related|attached|accompanying)\s+[^()\[\];]*?rights?\s*[)\]]?")
_RIGHTS_LIKE = re.compile(r"(?i)(purchase\s+rights?|rights?\s+to\s+(?:purchase|acquire)|"
                          r"plan\s+(?:participation\s+)?interests?|interests?\s+(?:in|under)\s+(?:the\s+)?"
                          r"[^|]{0,80}?plan\b|contingent\s+value\s+rights?|stock\s+options?|"
                          r"deferred\s+compensation|obligations\s+under|plan\s+benefits?|issuable\s+under|"
                          r"preference\s+shares?|restricted\s+stock\s+units?|conditional\s+rights|"
                          r"guarantees?\s+of|"
                          r"warrants?|exchangeable|convertible\s+(?:into|senior|notes?|"
                          r"debentures?)|\bnotes?\b|debentures?|preferred)")


_CLS_START = re.compile(r"(?i)(?<=\s)(?:(?P<pct>\d+(?:\.\d+)?\s*[⅛¼⅜½⅝¾⅞]?\s*%|floating\s+rate)|"
                        r"(?P<misc>deferred\s+compensation|guarantees?\s+of|restricted\s+stock\s+units?)|"
                        r"(?P<com>common\s+(?:stock|shares?)\b|ordinary\s+shares?\b|american\s+deposit[ao]ry)|"
                        r"(?P<pref>preferred\s+(?:stock|shares?)\b)|(?P<note>senior\s+(?:secured\s+)?notes)|"
                        r"(?P<cls>class\s+[a-c]\b|series\s+[a-z]\b)|(?P<wr>warrants?\b|rights?\s+to\s+purchase))")
# 直前の語がこれなら**切らない**（同じ種類の名前の途中）。種類の頭ごとに違う
_BLOCK = {
    "pct": {"of", "a", "an", "the", "with", "at", "bearing", "s", "company", "issuer"},
    "com": {"of", "to", "into", "for", "purchase", "acquire", "a", "b", "c", "class", "series",
            "voting", "the", "each", "one", "two", "three", "its", "our", "company", "registrant",
            "issuer", "exchangeable", "convertible", "representing", "underlying", "such"},
    "pref": {"of", "to", "into", "for", "purchase", "acquire", "junior", "participating",
             "convertible", "cumulative", "perpetual", "mandatory", "redeemable", "noncumulative",
             "series", "class", "a", "b", "c", "the", "representing", "each", "one"},
    "note": {"of", "the", "convertible", "exchangeable", "subordinated", "guarantee", "guarantees"},
    "cls": {"of", "the", "each", "one", "into", "for", "purchase", "into", "a", "an"},
    "wr": None,     # 下で別扱い: 『par value … / per share』の直後だけ切る
    "misc": {"the", "of", "a"},
}


def class_kind(cls):
    """'common' / 'noncommon' / 'unknown'。複数の種類が並ぶときは普通株が一つでもあれば common。"""
    if not cls:
        return "unknown"
    t = re.sub(r"\s+", " ", cls).strip()
    if re.fullmatch(r"(?i)(none|n/?a|not\s+applicable|-+)", t):
        return "unknown"
    t = _ATTACHED.sub(" ", t)
    # 優先株の預託株式（『Depositary Shares, each representing 1/100th of a share of …
    # Preferred Stock』『American Depositary Shares, each representing 1/100 th of a share of the
    # Company’s 8.625% Series H … Preferred』）は優先株。先に一つの札へ畳む
    t = re.sub(r"(?i)(?:american\s+)?deposit[ao]ry\s+shares?\s*,?\s*\(?\s*each\s+representing"
               r"[^;]{0,200}?(?:preferred|preference|series\s+[a-z]\s+cumulative|cumulative\s+redeemable)\b"
               r"[^;]*?(?=deposit[ao]ry\s+shares?|;|$)",
               " ; preferred depositary ; ", t)
    t = re.sub(r"(?i)401\s*\(\s*k\s*\)", "401k", t)
    # CVR（条件付き価値受益権）は別の種類。『Common Stock, no par value Series A Contingent
    # Value Rights』のように区切りなしで並ぶので、その前で切る
    t = re.sub(r"(?i)\s(?=(?:series\s+[a-z]\s+)?contingent\s+value\s+rights?)", " ; ", t)
    # 区切り無しで並ぶ種類を切る（表の改行が空白に潰れる。実測『Common Stock, par value $0.01 per
    # share 4.600% Senior Notes due 2024』『Common Shares American Depositary Shares, each …
    # Preferred Shares …』）。『Rights to Purchase Common Stock』『Class A Common Stock』は切らない
    cut, last = [], 0
    for mm in _CLS_START.finditer(t):
        i = mm.start()
        if i == 0:
            continue
        typ = mm.lastgroup
        prev = re.findall(r"[A-Za-z]+", t[max(0, i - 20):i])
        pw = prev[-1].lower() if prev else ""
        if typ == "wr":
            if pw not in ("value", "share", "shares"):
                continue
        elif pw in _BLOCK[typ] or (typ in ("com", "pref") and len(pw) == 1):
            continue          # 『Class L Common Stock』『Series B Preferred』は一つの名前
        cut.append(t[last:i])
        last = i
    t = " ; ".join(cut + [t[last:]])
    # 並列を区切る（『Common Stock, par value $.01, and Preferred Share Purchase Rights』は2つ）
    segs = re.split(r"(?i);|\(|\)|\s(?:and|&)\s(?=(?:the\s+)?(?:associated|related|series|preferred|"
                    r"common|rights?|warrants?|\$?[\d.]+\s*%?|class|contingent|stock\s+purchase))|\n|\s{3,}", t)
    any_eq, any_non = False, False
    for sg in segs:
        sg = sg.strip(" ,.:")
        if not sg:
            continue
        # 『Common Stock Purchase Rights』『Warrants to purchase Common Stock』
        # 『Notes exchangeable into Common Stock』は普通株そのものではない
        rights_like = _RIGHTS_LIKE.search(sg)
        if re.search(r"(?i)\bsub-?shares?\b", sg) and not re.search(r"(?i)preferred|notes?", sg):
            any_eq = True          # Texas Pacific Land Trust の持分（Sub-share certificates）
            continue
        if _EQ.search(sg) and not rights_like:
            any_eq = True
        elif _NONEQ.search(sg) or rights_like:
            any_non = True
    if any_eq:
        return "common"
    if any_non:
        return "noncommon"
    return "unknown"


# 種類の読みの回帰検査（`--selftest`）。どれも Form 25/15 の原本に実在した文言
CLASS_TESTS = [
    ("common", "Common Stock"),
    ("common", "Common Stock, par value $.01 per share (and associated Preferred Stock Purchase Rights)"),
    ("common", "Common Stock, par value $0.01 per share 4.600% Senior Notes due 2024"),
    ("common", "Common Stock; 0.500% Senior Notes due 2029; 3.750% Senior Notes due 2034"),
    ("common", "Class A common stock, par value $0.01 Class B common stock, par value $0.01 "
               "Series B Junior Participating Preferred Share Purchase Rights"),
    ("common", "Common Shares American Depositary Shares, each representing two Common Shares "
               "Preferred Shares Preferred American Depositary Shares, each representing one-half "
               "of one Preferred Share"),
    ("common", "American Depositary Shares, each representing one ordinary share"),
    ("common", "Common Units representing limited partner interests"),
    ("common", "Shares of Beneficial Interest"),
    ("common", "Registered Shares of Pentair Ltd."),
    ("common", "Sub-shares in Certificates of Proprietary Interest"),
    ("common", "Common Stock, no par value Series A Contingent Value Rights"),
    ("noncommon", "Preferred Stock Purchase Rights, par value $0.001 per share"),   # Masimo 2016
    ("noncommon", "1.750% Senior Notes due 2021"),                                  # Kellanova 2021
    ("noncommon", "11.125% Series A Mandatory Convertible Preferred Stock"),        # Frontier 2018
    ("noncommon", "Depositary Shares, each representing a 1/20th interest in a share of 6.00% "
                  "Mandatory Convertible Preferred Stock"),
    ("noncommon", "Common Stock Purchase Rights"),
    ("noncommon", "Rights to Purchase Shares of Common Stock"),
    ("noncommon", "Warrants Exercisable for Common Stock (Expiring April 16, 2017)"),
    ("noncommon", "Units, each consisting of one share of Class A common stock and one-half of one warrant"),
    ("noncommon", "Plan Interests in the United Airlines Ground Employee 401(k) Plan"),
    ("noncommon", "Plan Benefits in Media General, Inc. Voting Common Stock, no par value"),
    ("noncommon", "As Guarantor of the 0.632% Notes due 2023"),
    ("unknown", "None"),
]


def selftest():
    bad = [(exp, class_kind(t), t) for exp, t in CLASS_TESTS if class_kind(t) != exp]
    for exp, got, t in bad:
        print(f"  ✗ 期待 {exp} / 実際 {got} | {t[:90]}")
    print(f"selftest: {len(CLASS_TESTS) - len(bad)}/{len(CLASS_TESTS)} ✓")
    return not bad


def _sec_raw(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA),
                                        timeout=60) as f:
                raw = f.read(6 * 1024 * 1024)
                if f.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            time.sleep(0.11)
            return raw.decode("utf-8", "replace"), None
        except urllib.error.HTTPError as e:
            time.sleep(0.11)
            if e.code in (403, 404, 401):
                return None, f"HTTP{e.code}"
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            time.sleep(1.5 * (attempt + 1))
    return None, "retry-exhausted"


def removal_doc(cik, ev, fetch=True):
    """Form 25/15 の原本から種類を読む（out/_delisted_cache/exitdocs/{acc}.json にキャッシュ）。
    fetch=False のときはキャッシュだけを見る（無ければ 'unfetched'）。"""
    acc = ev.get("acc") or ""
    if not acc:
        return {"kind": "unknown", "how": "no_accession"}
    p = os.path.join(EXITDOCS, f"{acc}.json")
    if os.path.exists(p):
        rec = json.load(open(p))
        rec["kind"] = class_kind(rec.get("cls"))      # 判定の規則を直したら採り直さずに効く
        return rec
    if not fetch:
        return {"kind": "unknown", "how": "unfetched"}
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
    doc = ev.get("doc") or ""
    urls = []
    if doc:
        if doc.lower().endswith(".xml") and "/" in doc:
            urls.append(base + doc.split("/")[-1])      # xsl で描画される前の生の XML
        urls.append(base + doc)
    urls.append(base + f"{acc}.txt")                     # 提出一式（古い様式の予備）
    rec = {"acc": acc, "form": ev.get("form"), "date": ev.get("date"), "cls": None,
           "remain": None, "how": None, "src": None}
    errs = []
    for u in urls:
        raw, err = _sec_raw(u)
        if raw is None:
            errs.append(err)
            continue
        cls, rem, how = _parse_class(raw)
        if cls:
            rec.update(cls=cls, remain=rem, how=how, src=u.rsplit("/", 1)[-1])
            break
        errs.append(how)
    if not rec["cls"]:
        rec["how"] = "unreadable:" + ",".join(str(e) for e in errs)
    rec["kind"] = class_kind(rec["cls"])
    json.dump(rec, open(p, "w"), ensure_ascii=False)
    return rec


REGS = os.path.join(CACHE, "regs")
os.makedirs(REGS, exist_ok=True)
REG_FORMS = ("8-A12B", "8-A12G", "S-1", "S-1/A", "424B4", "10-12B", "10-12G", "F-1", "8-K12B")


def reg_events(cik):
    """株式の（再）登録の様式だけを採る（再上場＝GrafTech 型の判定にだけ使う・キャッシュ）。"""
    p = os.path.join(REGS, f"{cik}.json")
    if os.path.exists(p):
        return json.load(open(p))
    j, err = _sec_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    out = []
    if j:
        pages = [j.get("filings", {}).get("recent", {}) or {}]
        for fx in j.get("filings", {}).get("files") or []:
            if (fx.get("filingTo") or "9999") >= "2012-06-01":
                pj, _ = _sec_json(f"https://data.sec.gov/submissions/{fx['name']}")
                if pj:
                    pages.append(pj)
        for pg in pages:
            for fm, dt in zip(pg.get("form") or [], pg.get("filingDate") or []):
                if fm in REG_FORMS:
                    out.append([dt, fm])
    rec = {"cik": cik, "regs": sorted(out), "err": err if j is None else None}
    if j is not None:
        json.dump(rec, open(p, "w"))
    return rec


def _d(s):
    return datetime.date.fromisoformat(s)


def _plus(s, days):
    return (_d(s) + datetime.timedelta(days=days)).isoformat()


def _is_merger_8k(it):
    """合併完了の8-K（**買われた側**の書き方）。2.01 だけだと『自社が買った』でも立つので、
    3.01（上場廃止の通知）か 5.01（支配権の移転）が同時に立つものだけを採る。"""
    return ("2.01" in it and ("3.01" in it or "5.01" in it)) or ("3.01" in it and "5.01" in it)


def classify_exit(sub, asof_date, horizon=None, fetch_docs=True):
    """**普通株の**退場の日と種類を返す（v2・2026-09-23）。決めつけない——判らなければ 'unknown'。

    退場と認めるのは次のどれか（asof < 日付 <= 地平）:
      ①普通株を名指す Form 25/15 ＋ 前後の**合併完了8-K**（2.01∧(3.01∨5.01)）
          → 退場日は**8-Kの日**（secpx の回避策と同じ優先。Form 25-NSE は取引所が
            数日後に出し、Form 15 は10日ほど後に出るので、経済的な退場は8-Kの日）
      ②普通株を名指す Form 25/15 ＋ 前後の**破産8-K**（1.03）→ 抹消の日
          （旧株は消却される。**再建後の会社が同じCIKで提出を続けても**旧株の退場は退場。
            実例 Frontier）
      ③普通株を名指す Form 25/15 ＋ その後**定期報告が止まる** → 抹消の日
      ④種類が読めない Form 25/15 ＋ 合併完了8-K か 定期報告の停止 → ①/③と同じ
      ⑤様式が無くても 合併完了8-K ＋ その後定期報告が止まる → 8-Kの日
      ⑥様式も8-Kも無く、定期報告が地平の {ALIVE_DAYS}日より前に止まっている → 最後の提出日
    退場と**認めない**もの:
      ・普通株以外（社債・優先株・権利・ワラント）を名指す Form 25/15 ——v1 の誤りの本体
      ・普通株を名指すが、合併も破産も無く**定期報告が続く**もの（取引所の鞍替え・
        上場廃止後も報告を続ける社）——株はまだ存在し、会社も提出を続けている
    """
    if not sub or sub.get("missing"):
        return {"exit": "unknown", "why": "submissions取得不能"}
    hz = horizon or HORIZON
    cik = sub.get("cik")
    ev = sub.get("events") or []
    per = [d for d, _ in (sub.get("periodic") or [])]
    last = sub.get("last_filing")
    last_per = max(per) if per else None
    post = [e for e in ev if asof_date < e["date"] <= hz]
    rem = [e for e in post if is_removal_form(e["form"])]
    # 合併完了8-K と破産8-K は asof の**少し前**からも拾う: asof の直前に買収が完了し、
    # Form 25/15 だけが asof の後に出た社（実測 H.J. Heinz: 2013-06-13 完了・Form 25/A と
    # 15 が 7〜8月）は **asof の時点で既に買えなかった**。退場日は asof より前になる
    pre = [e for e in ev if _plus(asof_date, -MERGER_WIN[1] - 150) < e["date"] <= hz]
    mrg = [e for e in pre if e["form"] == "8-K" and _is_merger_8k(e.get("items") or "")]
    bkr = [e for e in pre if e["form"] == "8-K" and "1.03" in (e.get("items") or "")]
    e13 = [e for e in ev if e["form"].startswith("SC 13E3") or e["form"].startswith("SC TO-T")]
    # 買われる側が出す書類（株主総会の委任状・公開買付への意見表明）
    edeal = [e for e in ev if e["form"] in ("DEFM14A", "DEFM14C", "SC 14D9", "SC 14D9/A")]

    def cont_after(dt):
        return [d for d in per if d > _plus(dt, POST_EXIT_GRACE)]

    def near(lst, dt, win):
        lo, hi = _plus(dt, win[0]), _plus(dt, win[1])
        return [e for e in lst if lo <= e["date"] <= hi]

    # 今もこの CIK に**普通株の**ティッカーがあるか（『CTA-PB』のような優先株の記号は数えない）
    common_ticker_today = any("-" not in t for t in (sub.get("tickers") or []))

    def kind_of(e2):
        return removal_doc(cik, e2, fetch=fetch_docs).get("kind", "unknown") if cik else "unknown"

    def later_true_exit(dt):
        """dt より180日以上後に、**5.01 の8-K を伴う普通株の抹消**がある＝dt は再編だった
        （実測 Nielsen: 2015 の N.V.→plc の本拠移転と 2022 の買収 / CBS: 2019 の Viacom 統合時の
        取引所の鞍替えと 2025 の Skydance 取引）。"""
        for e2 in rem:
            if e2["date"] <= _plus(dt, 180) or kind_of(e2) != "common":
                continue
            if any("5.01" in (m.get("items") or "") for m in near(mrg, e2["date"], MERGER_WIN)):
                return e2["date"]
        return None

    skipped, cls_used, basis, date = [], None, None, None
    for e in rem:
        rd = removal_doc(cik, e, fetch=fetch_docs) if cik else {"kind": "unknown"}
        ck = rd.get("kind", "unknown")
        info = [e["date"], e["form"], ck, (rd.get("cls") or rd.get("how") or "")[:120]]
        if ck == "noncommon":
            skipped.append(info + ["普通株以外の抹消"])
            continue
        mn = near(mrg, e["date"], MERGER_WIN)
        bn = near(bkr, e["date"], BANKR_WIN)
        stops = not cont_after(e["date"])
        m0 = min(mn, key=lambda x: abs((_d(x["date"]) - _d(e["date"])).days)) if mn else None
        going_priv = near(e13, e["date"], (-540, 60))
        deal_doc = near(edeal, e["date"], (-400, 30))
        # 8-K が無くても取引の書類があれば取引の退場とみなす候補にする（外国の発行体は 8-K を
        # 出さない＝Altera Infrastructure 2020 は SC 13E3 と Form 25 だけ／Baker Hughes 2017 は
        # 完了の 8-K が新会社の CIK に出て、旧 CIK には DEFM14A と Form 25 だけ）
        deal = bool(m0 or ((going_priv or deal_doc) and ck == "common"))
        why_not = None
        if deal and not stops:
            # 抹消の後も定期報告が続く合併8-K は三通りある: 買われて**子会社として社債の報告を
            # 続ける**（Dow Chemical＝退場）／**買った側**が取引所を移った（Willis→WTW）／
            # **本拠移転・持株会社化**（Nielsen 2015）。後の二つは退場ではない
            # 合併8-K が有るのに 5.01 が無いときは、委任状（DEFM14A）では救わない——
            # 資産売却（HG Holdings 2018）や分割（Liberty Interactive 2018）でも委任状は出る
            if m0 and "5.01" not in (m0.get("items") or "") and not going_priv:
                # 支配株主による非公開化（Continental Resources 2022: Hamm が既に過半を持つので
                # 5.01 が立たない）は SC 13E3 / SC TO-T で裏を取る
                why_not = "合併8-Kに5.01（支配権の移転）も SC 13E3 も無い＝買った側・鞍替え"
            elif common_ticker_today:
                # 今もこの CIK に普通株のティッカーがある＝持株会社化・本拠移転で**同じ株が続く**
                # （ADTRAN 2022）。ただし一度非公開になって**再上場**した社（GrafTech: 2015年に
                # Brookfield が現金で買い、2018年に同じ CIK で再上場）は、2013年の株主にとっては退場
                allr = reg_events(cik).get("regs", [])
                # 再上場＝**新規の上場登録（8-A）と公募の目論見書（424B4）が30日以内に揃う**
                # （GrafTech 2018-04-18/19）。8-A だけなら優先株や新しい種類の登録もありうる
                regs = [x for x in allr
                        if x[0] > _plus(e["date"], 180) and x[1] in ("8-A12B", "8-A12G")
                        and any(y[1] == "424B4" and abs((_d(y[0]) - _d(x[0])).days) <= 30
                                for y in allr)]
                if not regs:
                    why_not = "今もこのCIKに普通株のティッカーがある（再上場の登録なし＝同じ株が続く）"
            else:
                lt = later_true_exit(e["date"])
                if lt:
                    why_not = f"{lt} に5.01を伴う本当の退場がある＝これは再編"
        if deal and not why_not:
            if m0:
                date, basis = m0["date"], ("①" if ck == "common" else "④") + "抹消+合併完了8-K"
            else:
                date, basis = e["date"], "①'普通株の抹消+取引の書類（SC 13E3/TO・DEFM14A/14D9）"
        elif bn and ck == "common":
            date, basis = e["date"], "②普通株の抹消+破産8-K"
        elif stops:
            date, basis = e["date"], ("③" if ck == "common" else "④") + "抹消+定期報告の停止"
        else:
            skipped.append(info + [why_not or "抹消の後も定期報告が続く（鞍替え・社債の報告等）"])
            continue
        cls_used = info
        break
    if date is None:
        for m in mrg:
            if not cont_after(m["date"]):
                date, basis = m["date"], "⑤合併完了8-K+定期報告の停止"
                break
    if date is None:
        recent_per = last_per and last_per >= _plus(hz, -ALIVE_DAYS)
        if recent_per or (sub.get("tickers") and last and last >= _plus(hz, -ALIVE_DAYS)):
            return {"exit": None, "why": "生存（普通株の退場の証拠なし・定期報告が地平の手前まで続く）",
                    "last_filing": last, "last_periodic": last_per,
                    "removals_skipped": skipped, "exit_basis": None}
        if last and last > asof_date:
            # 最後に**報告した**日（定期報告）。v1 は全様式の最終提出日で、延滞したまま 8-K や
            # Form 4 だけ出し続ける社の退場日が何年も後ろへずれた（実測 GlassBridge）
            date = last_per if (last_per and last_per > asof_date) else min(last, hz)
            basis = "⑥提出の停止（様式も合併8-Kも無い）"
        else:
            return {"exit": "unknown", "why": "asof 以後の提出が無い", "last_filing": last,
                    "removals_skipped": skipped}
    # ── 種類（v1 と同じ items の読み。窓は**正しい退場日**の前後）─────────────────
    kinds = set()
    lo, hi = _plus(date, -210), _plus(date, 60)
    for e in ev:
        if e["form"] != "8-K" or not (lo <= e["date"] <= hi):
            continue
        it = e.get("items") or ""
        if "1.03" in it:
            kinds.add("bankruptcy")
        if "5.01" in it:
            kinds.add("change_of_control")
        if "2.01" in it:
            kinds.add("completion_of_acquisition")
        if "3.01" in it:
            kinds.add("listing_deficiency")
    if basis.startswith("②"):
        kinds.add("bankruptcy")
    if basis.startswith("①'"):
        # 8-K が無い取引（外国の発行体・新会社の CIK に完了の 8-K が出た社）は書類で種類を決める
        kinds.add("completion_of_acquisition")
    # SC 13E3 は**その退場の近く**だけ（v1 は全期間で見ていたので、昔の非公開化の試みが
    # 後年の別の退場の種類を塗り替えていた）
    has13e3 = any(e["form"].startswith("SC 13E3") and _plus(date, -540) <= e["date"] <= _plus(date, 60)
                  for e in ev)
    f25 = any(e["form"].startswith("25") for e in rem)
    f15 = any(e["form"].startswith("15") for e in rem)
    if "bankruptcy" in kinds:
        kind = "bankruptcy"
    elif "change_of_control" in kinds or "completion_of_acquisition" in kinds:
        kind = "going_private" if has13e3 else "acquired"
    elif has13e3:
        kind = "going_private"
    elif "listing_deficiency" in kinds:
        kind = "listing_deficiency"
    elif basis[0] in "①②③④":
        kind = "deregistered"
    else:
        kind = "stopped_filing"
    return {"exit": date, "kind": kind, "signals": sorted(kinds),
            "form25": f25, "form15": f15, "sc13e3": has13e3,
            "last_filing": last, "last_periodic": last_per,
            "exit_basis": basis, "exit_class": cls_used, "removals_skipped": skipped,
            "periodic_after_exit": len(cont_after(date))}


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


def corroborate(last_day, exd):
    """価格系列の末尾と SEC の退場日の突合せ（名寄せの裏取りに使う）。"""
    if not last_day:
        return None
    if exd and exd != "unknown":
        gap = (datetime.date.fromisoformat(last_day[:10]) - datetime.date.fromisoformat(exd)).days
        return "strong" if abs(gap) <= 400 else ("continuous" if gap > 400 else "early_end")
    if last_day >= HORIZON[:7]:
        return "alive_to_horizon"
    return None


def exit_fields(ex, sub, asof):
    """classify_exit の結果を行の欄へ。v2 で足した欄は『なぜその日か』を残すためのもの。"""
    ex = ex or {}
    # §15(d)だけの報告義務で消えた社は「取引所に上場していなかった」印
    # （15-12B=§12(b)登録=取引所上場 / 15-15D=募集に伴う報告義務のみ）。
    # v2: asof 以後の**普通株（または種類不明）**の Form 15 だけを見る
    #     （v1 は全期間・全種類を見ていたので社債の 15-15D が印になっていた）。
    f15 = []
    cik = (sub or {}).get("cik")
    for e in ((sub or {}).get("events") or []):
        if not (e["form"].startswith("15-") and e["date"] > asof):
            continue
        k = removal_doc(cik, e, fetch=False).get("kind") if cik else "unknown"
        if k != "noncommon":
            f15.append(e["form"])
    dereg = ("15-12B" if any(x.startswith("15-12B") for x in f15) else
             "15-12G" if any(x.startswith("15-12G") for x in f15) else
             "15-15D" if any(x.startswith("15-15D") for x in f15) else None)
    return {"exit_date": ex.get("exit"), "exit_kind": ex.get("kind"),
            "exit_signals": ex.get("signals"),
            "exit_basis": ex.get("exit_basis"), "exit_class": ex.get("exit_class"),
            "exit_skipped": ex.get("removals_skipped") or [],
            "periodic_after_exit": ex.get("periodic_after_exit"),
            "last_periodic": ex.get("last_periodic"),
            "dereg_form": dereg}


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


def summarize(rows_out, Y, asof, bench_mult, extra=None):
    """左尾がどれだけ戻ったか＋漏斗。既定の解析と --reexit が共有する（二重実装を作らない）。"""
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
           "tool": "night/retro_delisted.py", "exit_rule": "v2",
           "vintage": Y, "asof": asof,
           "horizon": HORIZON, "benchmark_mult_SPY": round(bench_mult, 3) if bench_mult else None,
           "n": len(rows_out),
           "funnel": dict(collections.Counter(r["status"] for r in rows_out)),
           "resolve": dict(collections.Counter((r["resolve"] or "なし").split("(")[0]
                                               for r in rows_out)),
           "corroboration": dict(collections.Counter(r.get("corroboration") or "なし"
                                                     for r in rows_out)),
           "exit_kinds": dict(collections.Counter(r.get("exit_kind") or "生存/不明"
                                                  for r in rows_out)),
           "exit_basis": dict(collections.Counter((r.get("exit_basis") or "なし")[:1]
                                                  for r in rows_out)),
           "left_tail": summ, "by_exit_kind": bykind}
    if extra:
        out.update(extra)
    out["rows"] = rows_out
    return out


def report(out, p):
    rows_out = out["rows"]
    c = collections.Counter(r["status"] for r in rows_out)
    print(f"{out['vintage']}: {len(rows_out)}社 / " + " / ".join(f"{k}:{v}" for k, v in c.most_common()))
    for lab, d in out["left_tail"].items():
        print(f"  [{lab}] 旧 n={d['旧(ティッカー経由)']['n']} 毀損{d['旧(ティッカー経由)'].get('恒久毀損')} "
              f"→ 新 n={d['新(退場込み・打ち切りCAGR)']['n']} 毀損{d['新(退場込み・打ち切りCAGR)'].get('恒久毀損')}")
    print("→", p)


PREV_KEYS = ("exit_date", "exit_kind", "exit_signals", "status", "corroboration", "dereg_form")


def reexit(Y, asof, path, fetch_docs=True):
    """**退場の欄だけ**を v2 の規則で引き直す（2026-09-23・retro_exit_date_form15）。

    価格の欄（Yahoo の採取・名寄せ・穴での切断・CAGR）は**前回の出力をそのまま運ぶ**。
    理由: (1)この是正が動かすのは退場の判定であって価格ではない (2)Yahoo は上場廃止銘柄の
    履歴を消し、今日採り直すと 2026-08-10 の採取と**別の理由で**行が動く（ベンダーの漂流を
    是正の効果と取り違えない＝基準の違う二つを割らない）。
    退場日に依存する価格側の欄は二つだけで、どちらもここで引き直す:
      corroboration（系列末尾と退場日の突合せ）／ 手動の名寄せの裏取り（manual_unverified）。
    **旧の値は各行の exit_prev に残す**（2回回しても v1 の値は上書きしない）。"""
    prev = json.load(open(path))
    rows = prev["rows"]
    moved = []
    for r in rows:
        old = r.get("exit_prev") or {k: r.get(k) for k in PREV_KEYS}
        sub = fetch_subs(r["cik"])
        ex = classify_exit(sub, asof, fetch_docs=fetch_docs)
        r.update(exit_fields(ex, sub, asof))
        r["exit_prev"] = old
        if r.get("end") and r.get("status") in ("survivor", "exited"):
            corr = corroborate(r["end"], r.get("exit_date"))
            r["corroboration"] = corr
            if (r.get("resolve") or "").startswith("手動") and corr not in (
                    "strong", "continuous", "alive_to_horizon"):
                # 手動の仮説が新しい退場日で裏を失った＝**価格を使わない**（誤値より空欄）
                r["px_dropped"] = {k: r.get(k) for k in ("ticker_hist", "px_src", "start", "end",
                                                         "years", "tr_total", "tr_cagr",
                                                         "tr_cagr_reinvest", "mdd")}
                for k in r["px_dropped"]:
                    r[k] = None
                r["status"] = "manual_unverified"
        if (old.get("exit_date"), old.get("exit_kind")) != (r.get("exit_date"), r.get("exit_kind")):
            moved.append(r)

    def trans(sel):
        c = collections.Counter()
        for r in rows:
            if not sel(r):
                continue
            o = r["exit_prev"]
            c[f"{o.get('exit_kind') or '生存'} → {r.get('exit_kind') or '生存'}"] += 1
        return dict(c.most_common())

    def date_moves(sel):
        c = collections.Counter()
        for r in rows:
            if not sel(r):
                continue
            o, n = r["exit_prev"].get("exit_date"), r.get("exit_date")
            if o == n:
                c["不変"] += 1
            elif not n:
                c["退場→生存"] += 1
            elif not o:
                c["生存→退場"] += 1
            elif o == "unknown" or n == "unknown":
                c["unknown絡み"] += 1
            elif n > o:
                c["後ろへ（退場が遅かった）"] += 1
            else:
                c["前へ"] += 1
        return dict(c.most_common())

    fix = {"rule": "v2（普通株を名指す Form 25/15・合併完了8-K・定期報告の停止で裁く）",
           "generated": datetime.date.today().isoformat(),
           "prices": "前回の出力（2026-08-10 の Yahoo 採取）をそのまま運んだ。退場の欄だけを引き直した",
           "prev_generated": prev.get("generated"),
           "prev_summary": prev.get("exit_fix", {}).get("prev_summary") or {
               k: prev.get(k) for k in ("funnel", "corroboration", "left_tail", "by_exit_kind")},
           "n_rows_moved": len(moved),
           "transitions": {"全社": trans(lambda r: True), "質実証": trans(lambda r: r["quality"])},
           "date_moves": {"全社": date_moves(lambda r: True),
                          "質実証": date_moves(lambda r: r["quality"])},
           "status_moves": dict(collections.Counter(
               f"{r['exit_prev'].get('status')} → {r.get('status')}" for r in rows
               if r["exit_prev"].get("status") != r.get("status")))}
    out = summarize(rows, Y, asof, prev.get("benchmark_mult_SPY"), extra={"exit_fix": fix})
    out["benchmark_mult_SPY"] = prev.get("benchmark_mult_SPY")
    json.dump(out, open(path, "w"), ensure_ascii=False)
    report(out, path)
    print("  退場の欄が動いた行:", len(moved))
    for lab in ("全社", "質実証"):
        print(f"  [{lab}] 日付:", fix["date_moves"][lab])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, default=2013)
    ap.add_argument("--subs", action="store_true")
    ap.add_argument("--exitdocs", action="store_true",
                    help="asof 以後の Form 25/15 の原本を採り、証券の種類を読む（キャッシュ）")
    ap.add_argument("--reexit", action="store_true",
                    help="前回の出力の価格欄を運び、退場の欄だけ v2 の規則で引き直す")
    ap.add_argument("--selftest", action="store_true", help="証券の種類の読みの回帰検査だけ")
    ap.add_argument("--map", action="store_true")
    ap.add_argument("--px", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(0 if selftest() else 1)
    Y = a.vintage
    asof = f"{Y}-07-01"
    t0 = int(datetime.datetime(Y, 7, 1).timestamp())

    coh = json.load(open(os.path.join(OUT, f"retro_cohort_{Y}.json")))
    rows = coh["rows"]

    # ── --subs ────────────────────────────────────────────────────────────
    if a.subs:
        def _have(cik):
            p = os.path.join(SUBS, f"{cik}.json")
            if not os.path.exists(p):
                return False
            j = json.load(open(p))
            return j.get("v") == SUBS_V or bool(j.get("missing"))
        todo = [r for r in rows if not _have(r["cik"])]
        if a.limit:
            todo = todo[:a.limit]
        print(f"submissions: {len(todo)}社を採る（既存 {len(rows)-len(todo)}）")
        for i, r in enumerate(todo):
            fetch_subs(r["cik"])               # 1リクエストごとに 0.11秒待つ（SEC 10req/s）
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(todo)}")
        print("done")
        return

    # ── --exitdocs ────────────────────────────────────────────────────────
    if a.exitdocs:
        todo = []
        for r in rows:
            sub = fetch_subs(r["cik"])
            for e in ((sub or {}).get("events") or []):
                if is_removal_form(e["form"]) and asof < e["date"] <= HORIZON and e.get("acc") \
                        and not os.path.exists(os.path.join(EXITDOCS, f"{e['acc']}.json")):
                    todo.append((r["cik"], e))
        if a.limit:
            todo = todo[:a.limit]
        print(f"exitdocs: {len(todo)}件の Form 25/15 を読む")
        for i, (cik, e) in enumerate(todo):
            removal_doc(cik, e)
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(todo)}")
        print("done")
        return

    # ── --reexit ──────────────────────────────────────────────────────────
    if a.reexit:
        reexit(Y, asof, a.json or os.path.join(OUT, f"retro_delisted_{Y}.json"))
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
               "sic": (sub or {}).get("sic"),
               "n_10k": (sub or {}).get("n_10k"), "last_filing": (sub or {}).get("last_filing"),
               "px_src": None, "status": None,
               "start": None, "end": None, "years": None,
               "tr_total": None, "tr_cagr": None, "tr_cagr_reinvest": None, "mdd": None}
        row.update(exit_fields(ex, sub, asof))

        # 上場株を持たない filer（社債だけの子会社・LP・従業員持株）は母集団外
        man = manual.get(str(cik))
        if man and man.get("listed") is False:
            row["status"] = "no_listed_equity"
            row["why"] = man.get("evidence")
        elif not m["cands"]:
            row["status"] = "unresolved"
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
            corr = corroborate(last[0], ex.get("exit"))
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
    out = summarize(rows_out, Y, asof, bench_mult)
    p = a.json or os.path.join(OUT, f"retro_delisted_{Y}.json")
    json.dump(out, open(p, "w"), ensure_ascii=False)
    report(out, p)


if __name__ == "__main__":
    main()
