# night/retro_delisted_secpx.py — 退場社の株価を**SEC原本から**採る（2026-08-10新設）
#
# ── なぜ要るか ─────────────────────────────────────────────────────────────
#   retro_delisted.py が母集団を CIK で組み直したところ、2013年ビンテージの
#   質実証プールは **563社中 175社が価格を採れない**（no_price 149 / no_start 24 /
#   unresolved 2）＝**31%が未測定**のまま残った。原因は一つ:
#   **Yahoo は上場廃止銘柄の履歴を消す**。実測（2026-08-10・この器で確認）:
#     BMS(Bemis) …… meta は返るが timestamp **0件**（longName も firstTradeDate も正しいのに空）
#     BCR/BYI ……… instrumentType=MUTUALFUND・exchange=YHD ＝**別の商品が記号を再利用**
#     AVP/SWN/TREC/RTN/CELG/ATVI/TWTR/XLNX/MYL …… **HTTP 404**
#     FRCB だけ n=164 ＝ **今もOTCで気配が立っている**銘柄だけが例外
#   ＝ベンダー経路は原理的に閉じている。**残る道は原本(SEC)しかない。**
#
# ── 何を採るか（二つの値を、別々の原本から）─────────────────────────────────
#   終値側 = **合併対価**。8-K(item 2.01/5.01)・DEFM14A・SC 13E3・SC 14D9 の
#            『the right to receive $NN.NN in cash』。実測 Bally(2491) で $83.30 を
#            正しく採れることを確認（par value $0.10 を除く検問つき）。
#   始値側 = **10-K Item 5 の四半期高安の表**（Reg S-K 201(a)・FY2018頃まで必須）。
#            asof(7/1) を**跨ぐ二つの四半期**を採り、境界の価格が満たす**不等式**で挟む:
#              lo = max(低_前, 低_後) ／ hi = min(高_前, 高_後)（交われば区間、
#              交わらなければ隙間が区間）。実測 Bally: 前[47.33,57.30]・後[56.52,76.30]
#              → **[56.52, 57.30]（幅1.4%）**。四半期の中値を使うと 66.4 で+17%外す。
#            **点推定ではなく区間**なのが肝——「どこを取っても毀損」なら毀損と言い切れる。
#
# ── 決めつけないこと（絶対のルール7の系）──────────────────────────────────
#   ■ **退場＝全損としない**。プレミアム付き買収は勝ちで終わる。対価が採れなければ
#     `censored`（打ち切り）であって −100% ではない。
#   ■ **株式対価の合併は金額に直さない**（相手の株価が要る＝別の基準を混ぜる）。
#     `stock_merger` として打ち切る。
#   ■ **基準の違う二つを割らない**。ここで作る系列は **price-only（配当なし・
#     10-K表の実勢値）**。survivor 側の adjclose(配当込み) と**割ってはいけない**ので、
#     比較は survivor も Yahoo の `close`(分割調整・配当なし) で採り直して行う
#     （--closes 段）。**同じ土俵に降ろしてから比べる。**
#   ■ **未実装の穴（正直に書く）** 分割: 10-K の表は「その10-Kの提出時点までの分割で
#     調整済み」なので、**表を読んだ10-Kの後・退場までの間に分割があると割れる**。
#     `split_risk` の検問は**まだ入れていない**。向きは、順方向分割なら始値が過大＝
#     CAGR が過小＝**偽の左尾を作る側**。今日の実測では負けで終わった8社の始値が
#     いずれも2013年の実勢と一致したので駆動していないが、検問がある状態ではない。
#   ■ **混合対価が最大の誤りだった（実測で学んだ）**。現金の脚だけを全対価と読むと
#     勝った社が偽の恒久毀損に化ける: Starwood $21.00+0.800 Marriott株／
#     B/E Aero $34.10+0.3101 Rockwell株／Questcor $30.00+0.897 Mallinckrodt株／
#     tw telecom $10.00+Level3株／Celgene $50.00+1 BMY株+CVR／St Jude $46.75+0.8708 Abbott株／
#     Starz $7.26+0.6321×2 Lions Gate株／Rovi は **$7.95 が株式の脚のほう**だった。
#     初版はこの8件を全部「マイナス」として数え、恒久毀損を 9→18 に**倍増させて見せた**。
#     MIX_PAT で落として 9→11 に落ち着いた。**誤りの向きは常に下側**なので、
#     プラスで終わった社は混合でも結論が変わらない（現金の脚だけで既に勝っている）。
#
# 実行（すべてキャッシュ・再開可能。落ちても成果は消えない）:
#   python3 night/retro_delisted_secpx.py --vintage 2013 --subs     # 提出索引
#   python3 night/retro_delisted_secpx.py --vintage 2013 --end      # 合併対価
#   python3 night/retro_delisted_secpx.py --vintage 2013 --start    # Item5 高安
#   python3 night/retro_delisted_secpx.py --vintage 2013 --closes   # survivor の close
#   python3 night/retro_delisted_secpx.py --vintage 2013            # 解析・出力
import argparse
import collections
import datetime
import gzip
import html
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
SUBF = os.path.join(CACHE, "subsfull")
DOCS = os.path.join(CACHE, "secpx")
PX = os.path.join(CACHE, "px")
for d in (CACHE, SUBF, DOCS, PX):
    os.makedirs(d, exist_ok=True)

SEC_UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com", "Accept-Encoding": "gzip"}
YH_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
HORIZON = "2026-08-04"
MAXDOC = 40 * 1024 * 1024

KEEP_FORMS = {"10-K", "10-K405", "10-KSB", "10-K/A", "8-K", "8-K/A", "DEFM14A", "PREM14A",
              "DEF 14A", "DEFA14A", "DEFM14C", "SC 13E3", "SC 13E3/A", "SC 14D9", "SC 14D9/A",
              "SC TO-T", "425", "15-12B", "15-12G", "15-15D", "25-NSE", "25", "S-4"}


# ── 取得 ───────────────────────────────────────────────────────────────────
def _get(url, headers, timeout=60, tries=3):
    last = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=timeout) as f:
                raw = f.read(MAXDOC)
                if f.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            return raw, None
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 401):
                return None, f"HTTP{e.code}"
            last = f"HTTP{e.code}"
        except Exception as e:
            last = type(e).__name__
        time.sleep(1.5 * (a + 1))
    return None, last or "fail"


def subs_full(cik):
    """提出索引（accessionNumber つき）。**2013年以降の関係フォームだけ**残す。"""
    p = os.path.join(SUBF, f"{cik}.json")
    if os.path.exists(p):
        return json.load(open(p))
    raw, err = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", SEC_UA)
    if raw is None:
        j = {"cik": cik, "err": err, "f": []}
    else:
        s = json.loads(raw)
        r = s["filings"]["recent"]
        n = len(r["form"])
        keep = []
        for i in range(n):
            if r["filingDate"][i] < "2012-06-01" or r["form"][i] not in KEEP_FORMS:
                continue
            keep.append({"form": r["form"][i], "d": r["filingDate"][i],
                         "acc": r["accessionNumber"][i], "doc": r["primaryDocument"][i],
                         "items": r["items"][i], "rep": r["reportDate"][i],
                         "sz": r["size"][i]})
        j = {"cik": cik, "name": s.get("name"), "fye": s.get("fiscalYearEnd"), "f": keep}
    json.dump(j, open(p, "w"))
    time.sleep(0.11)
    return j


def doc_text(cik, acc, fn, tag):
    """提出書類の本文をプレーンテキストに。表の列境界は ' | ' で残す。"""
    p = os.path.join(DOCS, f"{tag}_{cik}_{acc.replace('-', '')}.txt.gz")
    if os.path.exists(p):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return f.read()
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fn}"
    raw, err = _get(url, SEC_UA, timeout=120)
    time.sleep(0.11)
    if raw is None:
        t = f"__ERR__{err}"
    else:
        s = raw.decode("utf-8", "replace")
        s = re.sub(r"(?is)<(script|style|ix:header).*?</\1>", " ", s)
        s = re.sub(r"(?s)<[^>]+>", " | ", s)
        s = html.unescape(s)
        s = re.sub(r"[^\S\n]+", " ", s)
        t = re.sub(r"(\s*\|\s*)+", " | ", s)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(t)
    return t


# ── 合併対価 ───────────────────────────────────────────────────────────────
CASH_PATS = [
    (r"right\s+to\s+receive\s+(?:[^.$]{0,90}?)?\$\s?([\d,]+\.\d{2,4})", 3),
    (r"\$\s?([\d,]+\.\d{2,4})\s+(?:in\s+cash\s+)?(?:per\s+share|for\s+each\s+share|per\s+Share)", 3),
    (r"\$\s?([\d,]+\.\d{2,4})\s+in\s+cash", 2),
    (r"(?:merger|cash|per\s+share)\s+consideration\s+of\s+\$\s?([\d,]+\.\d{2,4})", 3),
    (r"(?:purchase|offer)\s+price\s+of\s+\$\s?([\d,]+\.\d{2,4})", 2),
]
BAD_CTX = re.compile(r"(?i)(par\s+value|stated\s+value|no\s+par|exercise\s+price|"
                     r"strike\s+price|par\s+amount|dividend|quarterly\s+rate|"
                     r"conversion\s+price|liquidation\s+preference)")
# 対価の文脈でだけ数える（実測: Dow/DuPont の DEFM14A で配当上限 $0.57 を拾った是正）
GOOD_CTX = re.compile(r"(?i)(converted?\s+into|right\s+to\s+receive|merger\s+consideration|"
                      r"cancell?ed|in\s+exchange\s+for|offer\s+price|purchase\s+price|"
                      r"consideration\s+of)")
# 株式対価（実測: Dow は『converted into the right to receive **one** ... share of DowDuPont』
# ＝数字ではなく**数詞**なので [\d.]+ では捕まらなかった）
STOCK_PAT = re.compile(r"(?i)(exchange\s+ratio|"
                       r"converted?\s+into\s+(?:the\s+right\s+to\s+receive\s+)?"
                       r"(?:[\d.]+|one|two|three|a\s+fraction\s+of)\s+(?:fully\s+paid[^|]{0,40})?"
                       r"(?:validly\s+issued\s+)?shares?\b|"
                       r"shares\s+of\s+[A-Za-z ]{0,40}common\s+stock\s+for\s+each)")


# 現金**と株式**の混合対価。実測でこれが最大の誤りだった——現金の脚だけを全対価と読むと
# 勝ちで終わった社が**偽の恒久毀損**に化ける:
#   Starwood  $21.00 + **0.800 Marriott株** （実勢 約$79）→ 単独だと −29.8%/年
#   B/E Aero  $34.10 + **0.3101 Rockwell株**（約$62）    → −20.2%/年
#   Questcor  $30.00 + **0.897 Mallinckrodt株**（約$86） → −34.0%/年
#   tw telecom $10.00 + **Level 3株**                    → −54.4%/年
# 相手の株価を当てに行くのは**別の基準を混ぜる**ことなので、混合は測らず打ち切る。
# 文脈のどこかに**株式の脚**があれば混合とみなす。数量つきの shares を拾うが、
# 『$10.00 **per share** in cash』の慣用句は除く（除かないと純現金の案件まで落ちる）。
MIX_PAT = re.compile(
    r"(?i)("
    r"\d*\.\d+\s+(?:of\s+an?\s+)?(?:(?!cash|per\s)[A-Za-z ,\-]){0,40}?shares?\b"
    r"|\b(?:one|two|three|an?\s+fraction\s+of\s+an?)\s+"
    r"(?:validly\s+issued[^|]{0,60}?)?shares?\s+of\b"
    r"|\bin\s+(?:shares\s+of\s+)?common\s+stock\b"
    r"|\bstock\s+consideration\b|\bexchange\s+ratio\b"
    r"|\bcontingent\s+value\s+right"
    r"|\bexcluding\s+the\s+consideration\b"
    r")")


def merger_price(t, name=None):
    """本文から現金対価を採る。**par value・配当・混合対価・他社の対価を除く**。"""
    if t.startswith("__ERR__"):
        return None, t[7:], []
    votes = collections.Counter()
    ev = {}
    for pat, w in CASH_PATS:
        for m in re.finditer(pat, t[:900000], re.I):
            ctx = t[max(0, m.start() - 110):m.end() + 300]
            if BAD_CTX.search(t[max(0, m.start() - 70):m.start() + 30]):
                continue
            if not GOOD_CTX.search(t[max(0, m.start() - 160):m.end() + 60]):
                continue
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if not (0.02 <= v <= 5000):
                continue
            votes[v] += w
            ev.setdefault(v, []).append(re.sub(r"\s+", " ", ctx)[:420])
    if not votes:
        return None, ("stock_merger" if STOCK_PAT.search(t[:400000]) else "no_price_in_doc"), []
    best = max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    ctxs = ev[best][:2]
    if any(MIX_PAT.search(c) for c in ctxs):
        return None, "mixed_cash_stock", ctxs[:1]
    # **その対価は誰の株に対するものか**。実測 US Ecology(742126) は自社ではなく
    # 相手方 NRCG の対価を拾っていた（8-K item2.01 は「自社が買った」ときにも立つ）。
    toks = {w for w in re.sub(r"[^A-Za-z ]", " ", (name or "")).upper().split()
            if len(w) > 3 and w not in ("INC", "CORP", "CORPORATION", "COMPANY", "HOLDINGS",
                                        "GROUP", "LTD", "LIMITED", "THE", "AND", "CLASS",
                                        "TRUST", "PLC", "COMPANIES", "HOLDING")}
    if toks:
        ok = any(re.search(r"(?i)\bthe\s+Company\b|\bCompany\s+Common\s+Stock\b", c) or
                 any(tk in c.upper() for tk in toks) for c in ctxs)
        if not ok:
            return None, "subject_unconfirmed", ctxs[:1]
    return best, None, ctxs


# ── 10-K Item 5 の四半期高安 ───────────────────────────────────────────────
QLAB = re.compile(r"(?i)\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b")
NUM = re.compile(r"\b(\d{1,4}(?:,\d{3})?\.\d{2,4})\b")
YEAR_HDR = re.compile(r"(?i)(?:fiscal\s+)?year\s+ended[^|]{0,40}?(20\d\d)|(?<![\d.])(20[01]\d)(?![\d.])")
# **アポストロフィは活字体 ’(U+2019) のことが多い**。ASCII の ' だけを見ていた初版は
# 151社中92社を no_item5 で落としていた（EDGARの本文はスマートクォートが既定）。
SEC5 = re.compile(r"(?i)Market\s+for\s+(?:the\s+)?"
                  r"(?:Registrant|Compan(?:y|ies)|Issuer|Our)?\s*['’‘`´]?\s*s?\s*\|?\s*"
                  r"Common\s+(?:Equity|Stock)")
STOP5 = re.compile(r"(?i)(Dividend|Holders\s+of\s+Record|Performance\s+Graph|Issuer\s+Purchase|"
                   r"Stock\s+Performance|Equity\s+Compensation|Item\s*6)")


MONTH = ("January|February|March|April|May|June|July|August|September|October|November|December|"
         "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
# 実測した3つの版組（どれも FY2013 の 10-K に実在）:
#   S1 『First Quarter』行           … Bally / 多数
#   S2 『Quarter Ended | March 2, 2013』行 … CLARCOR(20740)。**四半期末の実日付**が入るので最も正確
#   S3 『Quarter | First | …』の裸の序数 … Esterline(33619)。見出しに Quarter があるときだけ許す
QLAB_DATE = re.compile(rf"(?i)\b({MONTH})\.?\s+(\d{{1,2}}),?\s*\|?\s*(20[0-2]\d)\b")
QLAB_BARE = re.compile(r"(?i)(?<![A-Za-z])(first|second|third|fourth)(?![A-Za-z])")
MON_N = {m[:3].lower(): i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
QIDX = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
        "fourth": 4, "4th": 4}


def _nums_after(w, i0, i1):
    out = [float(x.replace(",", "")) for x in NUM.findall(w[i0:i1])[:6]]
    return [x for x in out if 0.05 <= x <= 9000]


def q_window(fy_year, q, fye_end):
    """会計年度 fy_year・第q四半期 の [開始, 終了]。fye_end='MMDD'。"""
    mm, dd = int(fye_end[:2]), int(fye_end[2:])
    try:
        end = datetime.date(fy_year, mm, dd)
    except ValueError:
        end = datetime.date(fy_year, mm, 28)
    s = end - datetime.timedelta(days=365)
    return (s + datetime.timedelta(days=int(365 * (q - 1) / 4)),
            s + datetime.timedelta(days=int(365 * q / 4)))


def item5_quarters(t, fye_end):
    """Item5 から [{a,b,hi,lo}]（四半期の期間と高安）を返す。"""
    if t.startswith("__ERR__"):
        return [], t[7:]
    hits = [m.start() for m in SEC5.finditer(t)]
    if not hits:
        return [], "no_item5"
    for s0 in hits[::-1][:4]:
        w = t[s0:s0 + 9000]
        m = STOP5.search(w, 400)
        if m and m.start() > 300:
            w = w[:m.start() + 200]
        for strat in ("S1", "S2", "S3"):
            if strat == "S3" and not re.search(r"(?i)\bquarter\b", w):
                continue
            pat = {"S1": QLAB, "S2": QLAB_DATE, "S3": QLAB_BARE}[strat]
            labs = list(pat.finditer(w))
            if len(labs) < 4:
                continue
            rows = []
            for i, lb in enumerate(labs):
                j = labs[i + 1].start() if i + 1 < len(labs) else min(len(w), lb.end() + 260)
                nums = _nums_after(w, lb.end(), j)
                if len(nums) < 2:
                    continue
                hi, lo = max(nums[0], nums[1]), min(nums[0], nums[1])
                if lo <= 0 or hi / lo > 6:
                    continue
                if strat == "S2":
                    mo = MON_N.get(lb.group(1)[:3].lower())
                    try:
                        end = datetime.date(int(lb.group(3)), mo, int(lb.group(2)))
                    except ValueError:
                        continue
                    a, b = end - datetime.timedelta(days=91), end
                else:
                    pre = w[max(0, lb.start() - 2500):lb.start()]
                    yrs = [int(y) for y in re.findall(r"(?<![\d.])(20[0-2]\d)(?![\d.,])", pre)]
                    if not yrs:
                        continue
                    a, b = q_window(yrs[-1], QIDX[lb.group(1).lower()], fye_end)
                rows.append({"a": a, "b": b, "hi": hi, "lo": lo, "how": strat})
            if len(rows) >= 4:
                return rows, None
    return [], "no_quarter_rows"


def start_interval(cand, fye_end, asof):
    """asof を跨ぐ二つの四半期の高安から、境界価格の**区間**を作る。"""
    A = datetime.date.fromisoformat(asof)
    if not cand:
        return None
    prev = [c for c in cand if c["b"] <= A + datetime.timedelta(days=20)]
    nxt = [c for c in cand if c["a"] >= A - datetime.timedelta(days=20)]
    prev.sort(key=lambda c: c["b"])
    nxt.sort(key=lambda c: c["a"])
    p = prev[-1] if prev else None
    q = nxt[0] if nxt else None
    if p and q and (q["a"] - p["b"]).days <= 40:
        a_, b_ = max(p["lo"], q["lo"]), min(p["hi"], q["hi"])
        if a_ <= b_:
            return {"lo": a_, "hi": b_, "how": "交差", "prev": [p["lo"], p["hi"]],
                    "next": [q["lo"], q["hi"]], "qa": p["b"].isoformat(), "qb": q["a"].isoformat()}
        return {"lo": min(b_, a_), "hi": max(b_, a_), "how": "隙間",
                "prev": [p["lo"], p["hi"]], "next": [q["lo"], q["hi"]],
                "qa": p["b"].isoformat(), "qb": q["a"].isoformat()}
    c = q or p
    if not c:
        return None
    return {"lo": c["lo"], "hi": c["hi"], "how": "単一四半期",
            "qa": c["a"].isoformat(), "qb": c["b"].isoformat()}


# ── survivor を price-only に降ろす ────────────────────────────────────────
def yahoo_close(sym, t0):
    p = os.path.join(PX, f"YC_{sym.replace('/', '-')}.json")
    if os.path.exists(p):
        return json.load(open(p))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={t0}&period2={int(time.time())}&interval=1mo")
    raw, err = _get(url, YH_UA, timeout=30)
    if raw is None:
        out = {"pts": [], "err": err}
    else:
        j = json.loads(raw)
        res = (j.get("chart", {}).get("result") or [None])[0]
        if not res:
            out = {"pts": [], "err": "no-result"}
        else:
            ts = res.get("timestamp") or []
            cl = ((res.get("indicators", {}).get("quote") or [{}])[0].get("close")) or []
            out = {"pts": [[datetime.date.fromtimestamp(t).isoformat(), v]
                           for t, v in zip(ts, cl) if v is not None]}
    json.dump(out, open(p, "w"))
    time.sleep(0.25)
    return out


def pick(pts, day, tol=95):
    if not pts:
        return None
    d = datetime.date.fromisoformat(day)
    bef = [p for p in pts if datetime.date.fromisoformat(p[0]) <= d]
    if bef:
        return bef[-1]
    aft = [p for p in pts if 0 <= (datetime.date.fromisoformat(p[0]) - d).days <= tol]
    return aft[0] if aft else None


def cagr(v0, v1, years):
    if not v0 or v0 <= 0 or v1 is None or years <= 0:
        return None
    if v1 <= 0:
        return -1.0
    return (v1 / v0) ** (1.0 / years) - 1.0


# ── 本体 ───────────────────────────────────────────────────────────────────
def targets(vint):
    src = json.load(open(os.path.join(OUT, f"retro_delisted_{vint}.json")))
    rows = [r for r in src["rows"] if r["status"] in ("no_price", "unresolved", "no_start")]
    rows.sort(key=lambda r: (not r.get("quality"), r["cik"]))   # 質実証を先に
    return src, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, default=2013)
    ap.add_argument("--subs", action="store_true")
    ap.add_argument("--end", action="store_true")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--closes", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quality", action="store_true", help="質実証プールだけ")
    a = ap.parse_args()
    V = a.vintage
    ASOF = f"{V}-07-01"
    src, rows = targets(V)
    if a.quality:
        rows = [r for r in rows if r.get("quality")]
    if a.limit:
        rows = rows[:a.limit]
    prog = os.path.join(OUT, f"retro_delisted_secpx_{V}_progress.json")

    if a.subs:
        for i, r in enumerate(rows):
            subs_full(r["cik"])
            if i % 25 == 0:
                json.dump({"stage": "subs", "i": i, "n": len(rows)}, open(prog, "w"))
                print(f"  subs {i}/{len(rows)}", flush=True)
        print("subs done", len(rows))
        return

    if a.end:
        res = {}
        p = os.path.join(OUT, f"retro_delisted_secpx_{V}_end.json")
        if os.path.exists(p):
            res = json.load(open(p))
        for i, r in enumerate(rows):
            k = str(r["cik"])
            if k in res:
                continue
            res[k] = extract_end(r)
            if i % 10 == 0:
                json.dump(res, open(p, "w"), ensure_ascii=False)
                print(f"  end {i}/{len(rows)} ok={sum(1 for v in res.values() if v.get('px'))}",
                      flush=True)
        json.dump(res, open(p, "w"), ensure_ascii=False)
        print("end done", len(res), "with price:", sum(1 for v in res.values() if v.get("px")))
        return

    if a.start:
        res = {}
        p = os.path.join(OUT, f"retro_delisted_secpx_{V}_start.json")
        if os.path.exists(p):
            res = json.load(open(p))
        for i, r in enumerate(rows):
            k = str(r["cik"])
            if k in res:
                continue
            res[k] = extract_start(r, ASOF)
            if i % 10 == 0:
                json.dump(res, open(p, "w"), ensure_ascii=False)
                print(f"  start {i}/{len(rows)} ok={sum(1 for v in res.values() if v.get('lo'))}",
                      flush=True)
        json.dump(res, open(p, "w"), ensure_ascii=False)
        print("start done", len(res), "with interval:", sum(1 for v in res.values() if v.get("lo")))
        return

    if a.closes:
        surv = [r for r in src["rows"] if r["status"] == "survivor" and r.get("cands")]
        t0 = int(time.mktime(time.strptime(f"{V}-01-01", "%Y-%m-%d")))
        for i, r in enumerate(surv):
            yahoo_close(r["cands"][0], t0)
            if i % 50 == 0:
                print(f"  closes {i}/{len(surv)}", flush=True)
        print("closes done", len(surv))
        return

    analyse2(V, ASOF, src)


def extract_end(r):
    cik = r["cik"]
    s = subs_full(cik)
    if s.get("err"):
        return {"note": "subs:" + s["err"]}
    ex = r.get("exit_date")
    if not ex:
        return {"note": "no_exit_date"}
    E = datetime.date.fromisoformat(ex)
    def near(f, lo, hi, items=None):
        out = []
        for x in s["f"]:
            if x["form"] != f:
                continue
            d = datetime.date.fromisoformat(x["d"])
            if not (E + datetime.timedelta(days=lo) <= d <= E + datetime.timedelta(days=hi)):
                continue
            if items and not any(it in x["items"] for it in items):
                continue
            out.append(x)
        return out
    cands = (near("8-K", -120, 45, ["3.01"]) + near("8-K", -120, 45, ["5.01"]) +
             near("DEFM14A", -450, 30) + near("SC 13E3", -450, 30) +
             near("SC 14D9", -450, 30) + near("DEFM14C", -450, 30) +
             near("PREM14A", -520, 30) + near("8-K", -560, 30, ["1.01"]))
    seen, note = set(), None
    for c in cands[:6]:
        if c["acc"] in seen or not c["doc"]:
            continue
        seen.add(c["acc"])
        if c["sz"] > MAXDOC:
            continue
        t = doc_text(cik, c["acc"], c["doc"], "E")
        px, note, ev = merger_price(t, s.get("name") or r.get("name"))
        if px:
            return {"px": px, "date": c["d"], "form": c["form"], "acc": c["acc"], "ev": ev}
    return {"note": note or "no_candidate_doc"}


def extract_start(r, asof):
    cik = r["cik"]
    s = subs_full(cik)
    if s.get("err"):
        return {"note": "subs:" + s["err"]}
    fye = (s.get("fye") or "1231")
    tens = [x for x in s["f"] if x["form"] in ("10-K", "10-K405", "10-KSB")
            and x["d"] >= asof]
    tens.sort(key=lambda x: x["d"])
    if not tens:
        return {"note": "no_10k_after_asof"}
    note = None
    for c in tens[:2]:
        if not c["doc"] or c["sz"] > MAXDOC:
            continue
        t = doc_text(cik, c["acc"], c["doc"], "S")
        rows, note = item5_quarters(t, fye)
        if not rows:
            continue
        iv = start_interval(rows, fye, asof)
        if iv:
            iv.update({"from": c["form"], "d": c["d"], "acc": c["acc"], "fye": fye,
                       "layout": rows[0].get("how")})
            return iv
    return {"note": note or "no_interval"}


def _stat(vals, label):
    if not vals:
        return {"n": 0}
    neg = [v for v in vals if v < 0]
    perm = [v for v in vals if v <= -0.15]
    return {"n": len(vals), "median": round(st.median(vals), 4), "min": round(min(vals), 4),
            "元本割れ": len(neg), "元本割れ率": round(len(neg) / len(vals), 4),
            "恒久毀損": len(perm), "恒久毀損率": round(len(perm) / len(vals), 4)}


def analyse2(V, ASOF, src):
    """左尾を『退場込み・price-only』で組み直す。survivorも close(配当なし)へ降ろす。"""
    END = json.load(open(os.path.join(OUT, f"retro_delisted_secpx_{V}_end.json")))
    START = json.load(open(os.path.join(OUT, f"retro_delisted_secpx_{V}_start.json")))
    hz = datetime.date.fromisoformat(HORIZON)
    A = datetime.date.fromisoformat(ASOF)
    subs = {}
    rows_out = []
    for r in src["rows"]:
        k = str(r["cik"])
        rec = {"cik": r["cik"], "name": r["name"], "quality": bool(r.get("quality")),
               "status": r["status"], "exit_kind": r.get("exit_kind")}
        if r["status"] == "survivor" and r.get("cands"):
            j = yahoo_close(r["cands"][0], 0) if False else None
            p = os.path.join(PX, f"YC_{r['cands'][0].replace('/', '-')}.json")
            pts = (json.load(open(p)).get("pts") or []) if os.path.exists(p) else []
            a, b = pick(pts, ASOF), pick(pts, HORIZON)
            if a and b and a[1] > 0:
                yrs = (hz - A).days / 365.25
                rec.update({"kind": "survivor", "px_cagr": cagr(a[1], b[1], yrs),
                            "years": round(yrs, 2), "basis": "close(分割調整・配当なし)"})
            else:
                rec.update({"kind": "survivor", "px_cagr": None, "note": "close未取得"})
            rows_out.append(rec)
            continue
        if r["status"] not in ("no_price", "unresolved", "no_start"):
            rows_out.append(rec | {"kind": "対象外"})
            continue
        e, s0 = END.get(k, {}), START.get(k, {})
        # 退場日は **合併完了8-K の日** を最優先（Form15/25 は証券の種類ごとに出るので当てにならない）
        ex = r.get("exit_date")
        if e.get("form") == "8-K" and e.get("date"):
            ex = e["date"]
        rec.update({"exit_date_eff": ex, "end_px": e.get("px"), "end_form": e.get("form"),
                    "end_note": e.get("note"), "start_lo": s0.get("lo"), "start_hi": s0.get("hi"),
                    "start_how": s0.get("how"), "start_note": s0.get("note"),
                    "ev_end": e.get("ev")})
        # **退場後に10-Kを出していたら、その退場は普通株のものではない**→打ち切り
        if k not in subs:
            subs[k] = subs_full(r["cik"])
        tens = [x["d"] for x in (subs[k].get("f") or []) if x["form"].startswith("10-K")]
        late = [d for d in tens if ex and d > ex]
        rec["late_10k"] = late[-1] if late else None
        if not (e.get("px") and s0.get("lo") and ex):
            rec["kind"] = "打ち切り"
            rows_out.append(rec)
            continue
        yrs = (datetime.date.fromisoformat(ex) - A).days / 365.25
        if yrs <= 0.25:
            rec.update({"kind": "asof前後に退場", "years": round(yrs, 2)})
            rows_out.append(rec)
            continue
        if late:
            rec.update({"kind": "打ち切り", "note": "退場日より後に10-K＝普通株の退場ではない"})
            rows_out.append(rec)
            continue
        rec.update({"kind": "退場(測定)", "years": round(yrs, 2),
                    "basis": "price-only（10-K Item5 の高安 ÷ 合併対価）",
                    "px_cagr_lo": cagr(s0["hi"], e["px"], yrs),
                    "px_cagr_hi": cagr(s0["lo"], e["px"], yrs),
                    "px_cagr": cagr(math.sqrt(s0["lo"] * s0["hi"]), e["px"], yrs)})
        rows_out.append(rec)

    res = {"generated": str(datetime.date.today()), "tool": "night/retro_delisted_secpx.py",
           "vintage": V, "asof": ASOF, "horizon": HORIZON,
           "basis": "price-only。survivor=Yahoo close(分割調整・配当なし)／"
                    "退場=10-K Item5高安 ÷ SEC原本の合併対価。**adjcloseと割らないこと**",
           "rows": rows_out}
    for pool in ("全社", "質実証"):
        sel = [x for x in rows_out if pool == "全社" or x["quality"]]
        sur = [x["px_cagr"] for x in sel if x["kind"] == "survivor" and x.get("px_cagr") is not None]
        ext = [x["px_cagr"] for x in sel if x["kind"] == "退場(測定)"]
        ext_lo = [x["px_cagr_lo"] for x in sel if x["kind"] == "退場(測定)"]
        cen = [x for x in sel if x["kind"] == "打ち切り"]
        res.setdefault("left_tail", {})[pool] = {
            "A_survivorのみ(旧と同じ母集団・price-only)": _stat(sur, "sur"),
            "B_退場込み(測定できた分だけ)": _stat(sur + ext, "both"),
            "B_悲観端(始値区間の高い端)": _stat(sur + ext_lo, "both_lo"),
            "退場で戻した社数": len(ext),
            "まだ打ち切り": len(cen),
            "打ち切りの内訳": dict(collections.Counter(
                (x.get("end_note") or "終値あり") if not x.get("start_lo")
                else "始値なし" for x in cen)),
            "上界(打ち切りが全部 恒久毀損だったら)": round(
                (len([v for v in sur + ext if v <= -0.15]) + len(cen)) /
                max(1, len(sur) + len(ext) + len(cen)), 4),
        }
    p = os.path.join(OUT, f"retro_delisted_secpx_{V}.json")
    json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res["left_tail"], ensure_ascii=False, indent=1))
    print("->", p)


def analyse_old(V, ASOF, src):
    endp = os.path.join(OUT, f"retro_delisted_secpx_{V}_end.json")
    startp = os.path.join(OUT, f"retro_delisted_secpx_{V}_start.json")
    END = json.load(open(endp)) if os.path.exists(endp) else {}
    START = json.load(open(startp)) if os.path.exists(startp) else {}
    hz = datetime.date.fromisoformat(HORIZON)
    A = datetime.date.fromisoformat(ASOF)
    out = []
    for r in src["rows"]:
        if r["status"] not in ("no_price", "unresolved", "no_start"):
            continue
        k = str(r["cik"])
        e, s0 = END.get(k, {}), START.get(k, {})
        rec = {"cik": r["cik"], "name": r["name"], "quality": r.get("quality"),
               "exit_kind": r.get("exit_kind"), "exit_date": r.get("exit_date"),
               "end_px": e.get("px"), "end_note": e.get("note"), "end_form": e.get("form"),
               "start_lo": s0.get("lo"), "start_hi": s0.get("hi"), "start_how": s0.get("how"),
               "start_note": s0.get("note"), "ev_end": e.get("ev")}
        if e.get("px") and s0.get("lo") and r.get("exit_date"):
            yrs = (datetime.date.fromisoformat(r["exit_date"]) - A).days / 365.25
            if yrs > 0.25:
                rec["years"] = round(yrs, 2)
                # 高い始値 → 低いCAGR（悲観端）／低い始値 → 楽観端
                rec["cagr_lo"] = cagr(s0["hi"], e["px"], yrs)
                rec["cagr_hi"] = cagr(s0["lo"], e["px"], yrs)
                rec["cagr_mid"] = cagr(math.sqrt(s0["lo"] * s0["hi"]), e["px"], yrs)
                rec["measured"] = True
        out.append(rec)
    meas = [x for x in out if x.get("measured")]
    res = {"generated": str(datetime.date.today()), "tool": "night/retro_delisted_secpx.py",
           "vintage": V, "asof": ASOF, "n_target": len(out), "n_measured": len(meas),
           "note": "price-only（配当なし）。survivorのadjcloseと**割らないこと**",
           "rows": out}
    for pool, sel in (("全社", out), ("質実証", [x for x in out if x["quality"]])):
        m = [x for x in sel if x.get("measured")]
        res.setdefault("summary", {})[pool] = {
            "対象": len(sel), "測定できた": len(m),
            "終値のみ": sum(1 for x in sel if x["end_px"] and not x.get("start_lo")),
            "始値のみ": sum(1 for x in sel if x.get("start_lo") and not x["end_px"]),
            "元本割れ(中値)": sum(1 for x in m if x["cagr_mid"] < 0),
            "元本割れ(確定)": sum(1 for x in m if x["cagr_hi"] < 0),
            "恒久毀損(中値)": sum(1 for x in m if x["cagr_mid"] <= -0.15),
            "恒久毀損(確定)": sum(1 for x in m if x["cagr_hi"] <= -0.15),
            "中央値": round(st.median([x["cagr_mid"] for x in m]), 4) if m else None,
        }
    p = os.path.join(OUT, f"retro_delisted_secpx_{V}.json")
    json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
    print("->", p)


if __name__ == "__main__":
    main()
