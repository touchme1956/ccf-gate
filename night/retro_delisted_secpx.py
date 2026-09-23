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
#   ■ **分割（2026-09-23 に塞いだ穴）** 10-K の表は「その10-Kの提出時点までの分割で
#     調整済み」なので、**表を読んだ10-Kの後・退場までの間に分割があると割れる**。
#     向きは、順方向分割なら始値が過大＝CAGR が過小＝**偽の左尾を作る側**。
#     v1 は検問なし（負けで終わった8社の始値が2013年の実勢と一致したことだけ確かめた）。
#     v2 は split_factor(): companyfacts の EPS が**同じ期間について提出書類の間で
#     きれいな比で書き直された**ことから分割の比と時期の窓を出し、始値の10-K の提出日と
#     退場の間にまるごと入る分割だけ始値に掛ける（前後が決まらなければ打ち切り）。
#     2本の10-Kを合わせるときは、重なる四半期の比で2本目を1本目の基準へ戻す。
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
#
# 退場の判定 v2（2026-09-23・retro_exit_date_form15）の後の作り直しの順番（質実証だけ・本文はキャッシュ）:
#   --quality --end --force            # 退場日が動いた社の対価を採り直す（v1 は各行の "v1" に残る）
#   --quality --start --reparse --force  # Item5 を v2 の読みで（v1 は各行の "v1"）
#   （解析）→ --quality --nonma --force → --quality --reused --force →（解析）
#   解析の前に out/retro_delisted_secpx_2013.json を**v1 の出力**に戻しておくと survivor の close が
#   v1（2026-08-10 の採取）から運ばれる（途中の版を挟むと運びが切れる社が出る）。
#   RETRO_SECPX_NO_SPLIT=1 で分割の検問を外した版（層の比較用）。
# v2 の読みで足したこと（どれも「測れなかった社」を測れるようにするだけ・既存の区間は1件も動かないことを確認）:
#   提出一式の大きさで本文を飛ばさない（MAXSUB）／四半期が列の表（S5: Dow・Raytheon・Time Warner）／
#   年の無い四半期末の札（S2b: Atlas Air・CoreLogic）／上付きの序数（Foot Locker）／『quarterly』の見出し／
#   年次報告書の添付 EX-13（TSYS 型）／2本の10-Kの間の分割で2本目を1本目の基準へ戻す（Continental）／
#   価格表の後ろの配当の表を読まない（Avago）。合併対価は: 『plus 0.9560 …』『a portion of a share … having a
#   value equal to』を混合に数える（Rockwell Collins・Eaton Vance）／他社の株主への対価（Covidien の $35.19 を
#   Medtronic Inc の対価と読んでいた）・優先ユニットの価格・幅や上限つきの見積りを採らない／旧社名で本人確認
import argparse
import collections
import datetime
import gzip
import zipfile
import zlib
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
# ⚠ 提出索引の `sz` は**提出一式（XBRL・添付を含む）の大きさ**であって本文の大きさではない
#   （実測 Protective Life の 10-K: sz 45MB／本文の Item5 は先頭の数%）。v1 は sz>40MB を
#   読まずに飛ばしていたので、**大きな会社ほど始値・対価が採れない**偏りがあった（質実証の
#   14社：Dow・Protective・Windstream・Validus…）。本文は _get が先頭 MAXDOC だけ読むので、
#   v2 の経路は提出一式の大きさでは飛ばさない（MAXSUB は壊れた索引への保険だけ）
MAXSUB = 1024 * 1024 * 1024

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
                    try:
                        raw = gzip.decompress(raw)
                    except EOFError:
                        # 圧縮後でも MAXDOC を超える本文: 先頭だけ解凍して使う（Item5・対価は先頭側）
                        raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
            return raw, None
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 401):
                return None, f"HTTP{e.code}"
            last = f"HTTP{e.code}"
        except Exception as e:
            last = type(e).__name__
        time.sleep(1.5 * (a + 1))
    return None, last or "fail"


SUBF_V = 2


def subs_full(cik):
    """提出索引（accessionNumber つき）。**2012-06以降の関係フォームだけ**残す。

    v2（2026-09-23）: `filings.recent`（直近1000件）に加えて**古いページ（filings.files）も読む**。
    v1 は recent しか読まなかったので、提出の多い社は asof 直後の 10-K が別ページに落ち、
    **Item5 の表を数年後の 10-K から読んでいた**（実測 Masimo: recent は 2016-02-15 以降だけ
    → FY2015 の 10-K の 2015年の四半期を 2013年の始値として使っていた）。"""
    p = os.path.join(SUBF, f"{cik}.json")
    if os.path.exists(p):
        j = json.load(open(p))
        if j.get("v") == SUBF_V or j.get("err"):
            return j
    raw, err = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", SEC_UA)
    time.sleep(0.11)
    if raw is None:
        j = {"cik": cik, "err": err, "f": []}
    else:
        s = json.loads(raw)
        pages = [s["filings"]["recent"]]
        for fx in (s["filings"].get("files") or []):
            if (fx.get("filingTo") or "9999") < "2012-06-01":
                continue
            praw, perr = _get(f"https://data.sec.gov/submissions/{fx['name']}", SEC_UA)
            time.sleep(0.11)
            if praw is None:
                return {"cik": cik, "err": f"older_page:{perr}", "f": []}   # キャッシュしない
            pages.append(json.loads(praw))
        keep = []
        for r in pages:
            n = len(r["form"])
            for i in range(n):
                if r["filingDate"][i] < "2012-06-01" or r["form"][i] not in KEEP_FORMS:
                    continue
                keep.append({"form": r["form"][i], "d": r["filingDate"][i],
                             "acc": r["accessionNumber"][i], "doc": r["primaryDocument"][i],
                             "items": r["items"][i], "rep": r["reportDate"][i],
                             "sz": r["size"][i]})
        keep.sort(key=lambda x: x["d"], reverse=True)      # recent と同じ新しい順
        j = {"cik": cik, "name": s.get("name"), "fye": s.get("fiscalYearEnd"), "f": keep,
             "v": SUBF_V}
    json.dump(j, open(p, "w"))
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
MKT_CTX = re.compile(r"(?i)(repurchas|closing\s+(?:sale\s+)?price\s+of\s+(?:the|our|its)\s+common|"
                     r"last\s+reported\s+sale\s+price)")
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
    # 『$35.19 plus 0.9560 of the implied equity value per share for New Medtronic』（実測: Covidien の
    # 株主への対価を Medtronic Inc の退場の対価と読んでいた）
    r"|\bplus\s+\d*\.\d+\b"
    r"|\d*\.\d+\s+of\s+(?:the\s+)?implied\s+(?:equity\s+)?value"
    # 『(1) $93.33 in cash … and (2) a portion of a share of UTC’s common stock having a value
    # equal to …』（実測 Rockwell Collins。株式の脚が金額で書かれる版組）
    r"|\b(?:portion|fraction)\s+of\s+an?\s+share\b"
    r"|\bhaving\s+a\s+value\s+equal\s+to\b"
    r")")
# 対価の文脈が**他社の株主**を名指していたら、その対価は自社のものではない
OTHER_HOLDERS = re.compile(r"(?i:holders\s+of\s+(?:the\s+)?(?:outstanding\s+)?(?:ordinary\s+shares|"
                           r"common\s+stock|common\s+shares|shares))\s+of\s+([A-Z][A-Za-z&.\-]+)")


def _toks(name):
    """社名の語。name は一つの名前か名前の並び（旧社名も含めて渡す: 今の社名だけだと
    Kellogg→Kellanova・CBS→Paramount Skydance のように退場の書類の名前と合わない）。"""
    names = name if isinstance(name, (list, tuple, set)) else [name]
    out = set()
    for nm in names:
        out |= {w for w in re.sub(r"[^A-Za-z ]", " ", (nm or "")).upper().split()
                if len(w) > 3 and w not in ("INC", "CORP", "CORPORATION", "COMPANY", "HOLDINGS",
                                            "GROUP", "LTD", "LIMITED", "THE", "AND", "CLASS",
                                            "TRUST", "PLC", "COMPANIES", "HOLDING")}
    return out


def _is_us(word, name):
    """『holders of … of <word>』の word が自社（今の名前・旧社名・略称）か。名前が無ければ自社扱い。"""
    names = name if isinstance(name, (list, tuple, set)) else [name]
    blob = " ".join(x for x in names if x).upper()
    if not blob.strip():
        return True
    w = word.upper().strip(".")
    return w in ("THE", "OUR", "ITS", "COMPANY", "SUCH", "EACH", "PARENT") or \
        w in re.sub(r"[^A-Z0-9 ]", " ", blob).split()


def _names(cik, *extra):
    """今の社名＋旧社名（retro_delisted の提出索引キャッシュの formerNames）。"""
    out = [x for x in extra if x]
    p = os.path.join(CACHE, "subs", f"{int(cik)}.json")
    if os.path.exists(p):
        try:
            j = json.load(open(p))
            out += [j.get("name")] + [fn.get("name") if isinstance(fn, dict) else fn
                                      for fn in (j.get("formerNames") or [])]
        except (ValueError, OSError):
            pass
    return [x for x in out if x]


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
            # 株価の参照（『the closing price of the Common Stock』）や自社株買いの価格は
            # 対価ではない（実測 Rovi 2015: 社債発行時の自社株買い $22.94 を対価と読んでいた）
            if MKT_CTX.search(t[max(0, m.start() - 120):m.end() + 60]):
                continue
            if not GOOD_CTX.search(t[max(0, m.start() - 160):m.end() + 60]):
                continue
            # 優先株・優先ユニットの価格（『$1.60 per Class A Preferred Unit』・実測 Evolve 2015）
            if re.search(r"(?i)\bpreferred\b", t[m.end():m.end() + 45]):
                continue
            # 幅で書かれた見積り（『between $1.77 and $2.19 per share … as estimated』・実測 CTC Media）
            if re.search(r"(?i)between\s+\$\s?[\d,.]+\s+(?:and|to)\s+$", t[max(0, m.start() - 40):m.start()]) or \
                    re.search(r"(?i)^[^$]{0,25}\$\s?[\d,.]+\s+(?:and|to)\s+\$", t[m.start():m.end() + 30]) or \
                    re.search(r"(?i)\b(?:between|up\s+to|as\s+much\s+as|no\s+more\s+than|potential(?:ly)?|"
                              r"potentiation)\b[^$.]{0,40}$", t[max(0, m.start() - 60):m.start()]):
                # （『implied』『estimated』まで広げた版は、混合対価の書類で**推定の総額**の候補を消し、
                #   残った現金の脚が最多票になって混合の検問をすり抜けた（Maxim・ILG）。
                #   混合・株式の検問は最多票の文脈にしか掛からないので、候補を消す検問は狭く保つ）
                continue
            oh = OTHER_HOLDERS.search(t[max(0, m.start() - 160):m.end() + 60])
            if oh and not _is_us(oh.group(1), name):
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
    toks = _toks(name)
    if toks:
        # 3文字の略称（NIC 等）も語として数える（旧社名で語が増えても略称の社を落とさない）
        names = name if isinstance(name, (list, tuple, set)) else [name]
        short = {w for nm in names if nm for w in re.sub(r"[^A-Za-z ]", " ", nm).upper().split()
                 if len(w) == 3 and w not in ("INC", "THE", "AND", "LTD", "PLC", "LLC", "CORP", "CO")}
        ok = any(re.search(r"(?i)\bthe\s+Company\b|\bCompany\s+Common\s+Stock\b", c) or
                 any(tk in c.upper() for tk in toks) or
                 any(re.search(r"\b" + sw + r"\b", c.upper()) for sw in short) for c in ctxs)
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


# ── Item5 の読み v2（2026-09-23）────────────────────────────────────────────────
#   v1 の item5_quarters は**行の直前に出てくる最後の年**をその行の年にしていた。
#   ところが Item5 の表の多くは **2年を横に並べる**（『2013 | 2012 | High | Low | High | Low |
#   First Quarter | 79.32 | 74.28 | 74.31 | 61.68』）。v1 はこの版組で**全行に古い方の年(2012)**を
#   付け、しかも**先頭の組＝新しい年(2013)の数字**を読んだ——四半期の窓が丸1年ずれる。
#   実測（旧の測定45社のうち18社）: Sigma-Aldrich は 2013年Q4 の高安[82.90,94.78] を
#   『2012年Q4』として始値にしていた（正しくは 2013年Q2/Q3 の交差 [80.25,85.91]）。
#   Juniper は recent しか読まない索引のせいで FY2015 の10-Kに行き、**2015年Q1** を始値にしていた。
#   v2 は (1) 見出しの High/Low の並びから**列の組**を作り、組ごとに数字を読む
#   (2) 年の札は信じすぎず、**10-K の期末日（reportDate）を最も新しい組に当てて**遡る
#   (3) lo<hi でない行（分配金の表・気配の無い非上場REIT）を捨てる
#   (4) できた区間が asof の隣の四半期でなければ**使わない**（誤値より空欄）。
HDR_TOK = re.compile(r"(?i)(?<![A-Za-z])(high|low|div(?:idends?|\.)?)(?![A-Za-z])")
YEAR_TOK = re.compile(r"(?<![\d.$,])(20[0-2]\d)(?![\d.,%])")


def _fy_end(rep, back_years, fye_end):
    """10-K の期末日 rep から back_years 年前の会計年度末。rep が無ければ fye と年で作る。"""
    if rep:
        d = datetime.date.fromisoformat(rep)
        try:
            return d.replace(year=d.year - back_years)
        except ValueError:
            return d.replace(year=d.year - back_years, day=28)
    return None


def _qwin(fy_end, q):
    s = fy_end - datetime.timedelta(days=365)
    return (s + datetime.timedelta(days=int(365 * (q - 1) / 4)),
            s + datetime.timedelta(days=int(365 * q / 4)))


def _nums_row(w, i0, i1, k=8):
    out = [float(x.replace(",", "")) for x in NUM.findall(w[i0:i1])[:k]]
    return out


# 節の終わり（v2）: v1 の STOP5 は『Dividend』でも切ったので、**配当の列を持つ価格表**の
# 見出しで表が切れていた（実測 Protective Life『Range | High | Low | Dividends』）
STOP5B = re.compile(r"(?i)(Performance\s+Graph|Issuer\s+Purchases?\s+of\s+Equity|Stock\s+Performance|"
                    r"Equity\s+Compensation\s+Plan|Item\s*6\b)")
# 数字だけの四半期の札（『Quarter | High | Low … | 1 | $43.87 | $35.67 |』・実測 Waddell & Reed）
QLAB_NUM = re.compile(r"(?<=\|)\s*([1-4])\s*(?=\|\s*\$?\s*\|?\s*\d{1,4}(?:,\d{3})?\.\d{2})")
# v2 の裸の札は『4th | $8.75』も読む（実測 Windstream『Year | Quarter | High | Low | Close』）。
# v1 の QLAB_BARE は v1 の記録を再現できるよう変えない
QLAB_BARE2 = re.compile(r"(?i)(?<![A-Za-z0-9])(first|second|third|fourth|1st|2nd|3rd|4th)(?![A-Za-z])")
# 年の無い四半期末の札（『High | Low | 2013 Quarter Ended | December 31 | $ | 49.64 | …』・
# 実測 Atlas Air）。年は直前の年のセル、会計年度が暦年でない社は期末月より後の月を前年に置く
QLAB_MD = re.compile(rf"(?i)(?<=\|)\s*(?:(?:fiscal\s+)?quarter\s+ended\s+)?({MONTH})\.?\s+(\d{{1,2}}),?\s*"
                     rf"(?=\|\s*\$?\s*\|?\s*\d{{1,4}}(?:,\d{{3}})?\.\d{{2}})")
# 上付きの序数（『1 | st | Quarter』『1 | st | Qtr』・実測 Foot Locker・Bard）を一つのセルに戻す
SUP_ORD = re.compile(r"(?i)(?<![\d.,$])\b([1-4])\s*\|\s*(st|nd|rd|th)\b")


def _item5_windows(t):
    hits = [m.start() for m in SEC5.finditer(t)]
    spans = []
    for s0 in hits[::-1][:4]:
        w = t[s0:s0 + 9000]
        m = STOP5B.search(w, 300)
        if m:
            w = w[:m.start() + 200]
        spans.append((s0, s0 + len(w)))
        yield w
    # 予備: 注記（Kellogg は『Note 15』に価格表）や見出しの綴りが違う社（Stericycle）、
    # 節の途中で窓が切れた社（DST）のために、文書全体から『| High |』のセルを探して、
    # **既に読んだ窓の外にあるものだけ**その前後を窓にする
    for m in re.finditer(r"(?i)\|\s*high\s*\|", t):
        p = m.start()
        if any(a <= p <= b - 400 for a, b in spans):
            continue
        spans.append((max(0, p - 900), p + 3500))
        yield t[max(0, p - 900):p + 3500]


DATED_AFTER = re.compile(rf"(?i)[\s|,(]*(?:quarter\s+)?(?:ended|ending)?\s*\|?\s*({MONTH})\.?\s+\d{{1,2}},?\s*\|?\s*20[0-2]\d")


def _div_gap(w, a, b):
    """価格の表の**後ろに続く配当の表**: 行を読み始めた後で、札と札の間に『Dividends』の節が
    挟まったらそこで打ち切る（実測 Avago: 価格の8行の後の『Dividends | … | First Quarter |
    $0.17 | $0.12』を株価 [0.12,0.17] と読んでいた）。表の前の散文の配当は数えない。"""
    gap = w[a:b]
    return bool(re.search(r"(?i)\bdividends?\b", gap)) and not re.search(r"(?i)\|\s*(high|low)\s*\|", gap)


def _row_starts_here(w, i0, i1):
    """日付の札の行: 札のすぐ後（40字以内・語を挟まず）に数字が来ること（散文の日付
    『As of | December 6, 2013 | , there were 4 holders…』の後ろの別の表の数字を拾わない）。"""
    m = NUM.search(w, i0, i1)
    if not m:
        return False
    gap = w[i0:m.start()]
    return len(gap) <= 40 and not re.search(r"[A-Za-z]{4,}", gap)


def _parse_item5_window(w, fye_end, rep):
    for strat in ("S1", "S2", "S2b", "S3", "S4"):
        # 『quarterly』も四半期の表の印に数える（実測 Nielsen『Quarterly Period』・Rockwood）
        if strat in ("S3", "S4") and not re.search(r"(?i)\bquarter(?:s|ly)?\b", w):
            continue
        pat = {"S1": QLAB, "S2": QLAB_DATE, "S2b": QLAB_MD, "S3": QLAB_BARE2, "S4": QLAB_NUM}[strat]
        labs = list(pat.finditer(w))
        if len(labs) < 4:
            continue
        if strat == "S2b":
            rows = []
            fm = int(fye_end[:2]) if fye_end else 12
            # 横並びの2年（『2013 | 2012 | High | Low | High | Low | Quarter ended March 31, | …』・
            # 実測 CoreLogic）: 見出しの年の並びを組に当てる。**散文の最後の年を行の年にしない**
            hc = [c.strip() for c in w[max(0, labs[0].start() - 500):labs[0].start()].split("|")]
            hc = [c for c in hc if 0 < len(c) <= 40]
            hi_n = sum(1 for c in hc if re.fullmatch(r"(?i)high", c))
            k0 = next((i for i, c in enumerate(hc) if re.fullmatch(r"(?i)high|low", c)), None)
            run = []
            if k0 is not None:
                for c in reversed(hc[:k0]):
                    if YEAR_TOK.fullmatch(c):
                        run.insert(0, int(c))
                    elif run:
                        break
            side_y = run if (hi_n >= 2 and len(run) >= 2) else None
            for i, lb in enumerate(labs):
                j = labs[i + 1].start() if i + 1 < len(labs) else min(len(w), lb.end() + 260)
                if rows and _div_gap(w, labs[i - 1].end(), lb.start()):
                    break
                if not _row_starts_here(w, lb.end(), j):
                    continue
                nums = [x for x in _nums_row(w, lb.end(), j, 8) if 0.05 <= x <= 9000]
                if side_y:
                    pairs = [(nums[2 * g:2 * g + 2], side_y[g]) for g in range(len(side_y))
                             if len(nums) >= 2 * g + 2]
                else:
                    pre = w[max(0, lb.start() - 1500):lb.start()]
                    ys = [int(y) for y in re.findall(r"(?<![\d.])(20[0-2]\d)(?![\d.,])", pre)]
                    if not ys or len(nums) < 2:
                        continue
                    pairs = [(nums[:2], ys[-1])]
                mo = MON_N.get(lb.group(1)[:3].lower())
                for nn, y0 in pairs:
                    hi, lo = max(nn), min(nn)
                    if not (0 < lo < hi) or hi / lo > 6:
                        continue
                    yr = y0 - (1 if mo > fm else 0)
                    try:
                        end = datetime.date(yr, mo, int(lb.group(2)))
                    except ValueError:
                        continue
                    rows.append({"a": end - datetime.timedelta(days=91), "b": end,
                                 "hi": hi, "lo": lo, "how": "S2b" + ("横" if side_y else "")})
            yield rows
            continue
        if strat != "S2":
            # 行の札は**高安の見出しより後**にある（散文の『the first quarter of 2014』を
            # 札に数えると、見出しの読みが表の外になる。実測 Kellogg の注記15）
            hh = re.search(r"(?i)\|\s*(high|low)\s*\|", w)
            if hh:
                aft = [lb for lb in labs if lb.start() > hh.start()]
                if 4 <= len(aft) < len(labs):
                    labs = aft
        rows = []
        if strat == "S2":
            for i, lb in enumerate(labs):
                j = labs[i + 1].start() if i + 1 < len(labs) else min(len(w), lb.end() + 260)
                if rows and _div_gap(w, labs[i - 1].end(), lb.start()):
                    break
                if not _row_starts_here(w, lb.end(), j):
                    continue
                nums = [x for x in _nums_row(w, lb.end(), j, 6) if 0.05 <= x <= 9000]
                if len(nums) < 2:
                    continue
                hi, lo = max(nums[0], nums[1]), min(nums[0], nums[1])
                if not (0 < lo < hi) or hi / lo > 6:
                    continue
                mo = MON_N.get(lb.group(1)[:3].lower())
                try:
                    end = datetime.date(int(lb.group(3)), mo, int(lb.group(2)))
                except ValueError:
                    continue
                rows.append({"a": end - datetime.timedelta(days=91), "b": end,
                             "hi": hi, "lo": lo, "how": "S2"})
            yield rows
            continue
        head = w[max(0, labs[0].start() - 500):labs[0].start()]
        # 見出しは**表のセル**（' | ' で区切られた短い断片）からだけ読む。散文の
        # 『high and low sales prices』『cash dividends declared』を列に数えると
        # 列の位置がずれる（実測 Allergan・Beam）
        cells = [c.strip() for c in head.split("|")]
        cells = [c for c in cells if 0 < len(c) <= 40]
        # 表の見出しの範囲＝最初の High/Low のセルの少し手前から（散文の日付
        # 『At | November 30, 2013 | , we had…』を列の年に数えない。実測 ISCA）
        i0 = next((i for i, c in enumerate(cells) if re.search(r"(?i)\b(high|low)\b", c)), None)
        if i0 is not None:
            cells = cells[max(0, i0 - 5):]
        if sum(1 for c in cells if re.fullmatch(r"(?i)years?", c)) >= 2:
            # 『Year | Quarter | Low | High | Year | Quarter | Low | High』＝複数年を2列に
            # 折り返した表（実測 TEGNA）。行の年が列ごとに違うので読まない（誤値より空欄）
            continue
        toks_all = []
        for c in cells:
            toks_all += [x.lower()[:3] for x in HDR_TOK.findall(c)]

        def groups_of(toks):
            gs, cur, col = [], {}, 0
            for tk in toks:
                key = "hi" if tk == "hig" else ("lo" if tk == "low" else "dv")
                if key in cur:
                    gs.append(cur)
                    cur = {}
                cur[key] = col
                col += 1
            if cur:
                gs.append(cur)
            return [g for g in gs if "hi" in g and "lo" in g]
        # 表の左上の『Dividends』が**列の組の見出し**（Sigma: 配当の列は右端）なのか
        # **本当の列**（DST: 『Dividend | High | Low』）なのかは見出しだけでは決まらない。
        # 両方の読みで行を読み、**高安が成り立つ行が多い方**を採る
        t_drop = list(toks_all)
        while t_drop and t_drop[0] not in ("hig", "low"):
            t_drop.pop(0)
        variants = [groups_of(t_drop)]
        if t_drop != toks_all:
            variants.append(groups_of(toks_all))
        # 列の年＝最初の High/Low の**直前に連なる年のセル**だけ（『…years ended |
        # September 30, 2013 | and | 2012 | : | 2013 | 2012 | Fiscal Quarters | High』の
        # 散文側の 2013/2012 を拾うと順番が逆になる。実測 Rockwell Collins）
        yrs_h = []
        if i0 is not None:
            hdr_i = next((i for i, c in enumerate(cells)
                          if re.search(r"(?i)\b(high|low)\b", c)), len(cells))
            run = []
            for c in reversed(cells[:hdr_i]):
                ys = YEAR_TOK.findall(c)
                if ys and len(c) <= 30:
                    run.append(int(ys[0]))
                elif re.fullmatch(r"(?i)(fiscal|calendar)?\s*(quarters?|year|period|periods|"
                                  r"price\s+range|market\s+price|range|dividends?(\s+(paid|declared))?|"
                                  r"(per\s+share)|in\s+dollars|for\s+(the\s+)?fiscal\s+years?|"
                                  r"fiscal\s+years?|:|\$|\s*)", c):
                    if run and c.strip() in (":",):
                        break
                    continue
                else:
                    if run:
                        break
            for y in reversed(run):
                if y not in yrs_h:
                    yrs_h.append(y)
        best = None
        for groups in variants:
            side = len(groups) >= 2 and len(yrs_h) >= 2
            # 年ごとに縦に積んだ表（『Fiscal 2012 | First…Fourth | Fiscal 2013 | First…』）は
            # 4本目と5本目の見出しの間に年が立つ。組が2つあっても**種類株の並び**（ISCA/ISCB）
            if len(labs) >= 8 and YEAR_TOK.search(w[labs[3].end():labs[4].start()]) \
                    and len(yrs_h) <= 1:
                side = False
            rows, started = [], False
            for i, lb in enumerate(labs):
                j = labs[i + 1].start() if i + 1 < len(labs) else min(len(w), lb.end() + 260)
                if (rows or started) and _div_gap(w, labs[i - 1].end(), lb.start()):
                    break
                # 札の直後に**四半期末の日付**があれば、この行は日付の札（S2）で読む。序数から
                # 年を推すと『ended August 3, 2013』の 2013 を次の行の年に取り違える（実測 Hibbett）
                if DATED_AFTER.match(w, lb.end()):
                    started = True
                    continue
                q = QIDX.get(lb.group(1).lower()) or int(lb.group(1))
                nums = _nums_row(w, lb.end(), j, 8)
                if side:
                    ymax = max(yrs_h[:len(groups)])
                    for g, gy in zip(groups, yrs_h):
                        if max(g["hi"], g["lo"]) >= len(nums):
                            continue
                        hi, lo = nums[g["hi"]], nums[g["lo"]]
                        if not (0.05 <= lo < hi <= 9000) or hi / lo > 6:
                            continue
                        fe = _fy_end(rep, ymax - gy, fye_end)
                        a, b = (_qwin(fe, q) if fe else q_window(gy, q, fye_end))
                        rows.append({"a": a, "b": b, "hi": hi, "lo": lo, "how": strat + "横",
                                     "yr": gy})
                    continue
                g = groups[0] if groups else None
                if g and max(g["hi"], g["lo"]) < len(nums):
                    hi, lo = nums[g["hi"]], nums[g["lo"]]       # 見出しの列の位置で読む（DST）
                else:
                    nn = [x for x in nums if 0.05 <= x <= 9000]
                    if len(nn) < 2:
                        continue
                    hi, lo = max(nn[0], nn[1]), min(nn[0], nn[1])
                if not (0.05 <= lo < hi <= 9000) or hi / lo > 6:
                    continue
                # 年: 札の**直後**に年が付く版組（『First quarter 2013』・実測 Stericycle）を先に見る
                after = re.match(r"(?i)[\s|]*(?:quarter)?[\s|,]*(?:of\s+|fiscal\s+)?(20[0-2]\d)\b",
                                 w[lb.end():lb.end() + 25])
                if after:
                    yr = int(after.group(1))
                else:
                    pre = w[max(0, lb.start() - 2500):lb.start()]
                    ys = [int(y) for y in re.findall(r"(?<![\d.])(20[0-2]\d)(?![\d.,])", pre)]
                    if not ys:
                        continue
                    yr = ys[-1]
                # 『(ended January 29, 2012)』は**終わった**四半期の日付であって途中ではない
                # （含めていた版は Avago の価格の行を全部落とし、後ろの配当の表を株価として読んだ）
                part = bool(re.match(r"(?is)[\s|]*(?:quarter)?[\s|]*\(?\s*(through|to\s+date|since|"
                                     r"as\s+of|until)", w[lb.end():lb.end() + 40]))
                rows.append({"q": q, "yr": yr, "hi": hi, "lo": lo, "how": strat, "partial": part})
            if not side and rows:
                # 縦積みの表: 年の札の最大を 10-K の期末日に当てて遡る。ただし**期末の後の
                # 途中の四半期**（『2014 | First Quarter (through February 25, 2014)』）は
                # 年の札の最大に数えない（数えると全行が1年前へずれる。実測 Gulfport）
                rows = [r for r in rows if not r.get("partial")]
                if rows:
                    ymax = max(r["yr"] for r in rows)
                    if rep:
                        ymax = min(ymax, int(rep[:4]))
                    for r in rows:
                        fe = _fy_end(rep, ymax - r["yr"], fye_end)
                        r["a"], r["b"] = (_qwin(fe, r["q"]) if fe else q_window(r["yr"], r["q"], fye_end))
            if best is None or len(rows) > len(best):
                best = rows
        yield best or []


# S5: 四半期が**列**・高安が**行**の表（v2 追補・2026-09-23）。大きな会社ほど Item5 は
#   『四半期の業績（注記）を見よ』とだけ書き、価格は四半期業績の表の最後の2行に載る:
#   Dow『2013 | 1st | 2nd | 3rd | 4th | Year | … | High | 34.83 | 36.00 | 41.08 | 44.99 | 44.99 | Low | …』／
#   Raytheon『2013 | First | (3) | Second | … | Common stock prices | High | $ | 59.01 | …』／
#   Time Warner『Quarter Ended | March 31, | June 30, | … | 2013 | … | Common stock — high | 57.62 | …』。
#   列の順は**直前の見出しの札**で決め（無ければ読まない）、年は High の行から見出しまで遡った
#   最も近い年のセル。5列目（通年）は『最大の高値・最小の安値』と一致するときだけ落とす。
T_ORD = re.compile(r"(?i)^(?:fiscal\s+)?(first|second|third|fourth|1st|2nd|3rd|4th)"
                   r"(?:\s+(?:fiscal\s+)?quarter)?$")
T_QN = re.compile(r"(?i)^(?:q([1-4])|quarter\s+([1-4]))$")
T_MD = re.compile(rf"(?i)^({MONTH})\.?\s+(\d{{1,2}}),?$")
T_HI = re.compile(r"(?i)^(?:[^|]{0,40}?[\s—–-])?high(?:\s+(?:sales\s+)?price)?(?:\s*\(\w{1,2}\))?\s*:?$")
T_LO = re.compile(r"(?i)^(?:[^|]{0,40}?[\s—–-])?low(?:\s+(?:sales\s+)?price)?(?:\s*\(\w{1,2}\))?\s*:?$")
T_YEAR = re.compile(r"(?i)^(?:fiscal\s+(?:year\s+)?)?(20[0-2]\d)(?:\s*\(\w{1,2}\))?:?$")
T_NUM = re.compile(r"^\$?\s*(\d{1,4}(?:,\d{3})?\.\d{2,4})$")
T_SKIP = re.compile(r"^(?:\$|\(\w{1,2}\)|\(|\))?$")


def _t_nums(cells, j):
    vals = []
    while j < len(cells):
        c = cells[j]
        m = T_NUM.match(c)
        if m:
            vals.append(float(m.group(1).replace(",", "")))
        elif not T_SKIP.match(c):
            break
        j += 1
    return vals, j


def _t_label(c):
    m = T_ORD.match(c)
    if m:
        return ("q", QIDX[m.group(1).lower()])
    m = T_QN.match(c)
    if m:
        return ("q", int(m.group(1) or m.group(2)))
    m = T_MD.match(c)
    if m:
        return ("m", MON_N[m.group(1)[:3].lower()])
    return None


def _t_order(labs):
    kinds = {x[1][0] for x in labs}
    vals = [x[1][1] for x in labs]
    if kinds == {"q"} and sorted(vals) == [1, 2, 3, 4]:
        return vals
    if kinds == {"m"}:
        d = [(vals[n + 1] - vals[n]) % 12 for n in range(3)]
        if d == [3, 3, 3]:
            return [1, 2, 3, 4]
        if d == [9, 9, 9]:
            return [4, 3, 2, 1]
    return None


def _t_header(cells, i, back=700, need=4):
    """High の行 i から遡って、最も近い『need 個の四半期の札』（need×3 セル以内に並ぶ）を返す。
    need=8 は2年を横に並べた表（『2013 | 2012 | Quarter Ended | Quarter Ended | March 31 | … ×8』・
    実測 Continental）で、4つずつの組がそれぞれ四半期の順になっていること。"""
    labs = []
    for k in range(i - 1, max(-1, i - back), -1):
        lb = _t_label(cells[k])
        if not lb:
            continue
        labs.insert(0, (k, lb))
        while labs and labs[-1][0] - labs[0][0] > need * 3:
            labs.pop()
        if len(labs) == need:
            orders = [_t_order(labs[g:g + 4]) for g in range(0, need, 4)]
            if all(orders):
                return sum(orders, []), labs[0][0]
            labs.pop()
    return None


def _parse_transposed(t, fye_end, rep):
    cells = [c.strip() for c in t.split("|")]
    rows = []
    for i, c in enumerate(cells):
        if len(c) > 60 or not T_HI.match(c):
            continue
        his, j = _t_nums(cells, i + 1)
        if j >= len(cells) or not T_LO.match(cells[j]):
            continue
        los, _ = _t_nums(cells, j + 1)
        if len(his) != len(los) or len(his) not in (4, 5, 8):
            continue
        if len(his) == 8:
            if not all(0.05 <= lo < hi <= 9000 and hi / lo <= 6 for hi, lo in zip(his, los)):
                continue
            hdr = _t_header(cells, i, need=8)
            if not hdr:
                continue
            order, h0 = hdr
            ys = []
            for k in range(h0 - 1, max(-1, h0 - 10), -1):
                m = T_YEAR.match(cells[k])
                if m:
                    ys.insert(0, int(m.group(1)))
            if len(ys) != 2 or ys[0] == ys[1]:
                continue
            for n, (q, hi, lo) in enumerate(zip(order, his, los)):
                rows.append({"q": q, "yr": ys[n // 4], "hi": hi, "lo": lo, "how": "S5縦横"})
            continue
        if len(his) == 5:
            if abs(his[4] - max(his[:4])) < 0.006 and abs(los[4] - min(los[:4])) < 0.006:
                his, los = his[:4], los[:4]
            elif abs(his[0] - max(his[1:])) < 0.006 and abs(los[0] - min(los[1:])) < 0.006:
                his, los = his[1:], los[1:]
            else:
                continue
        if not all(0.05 <= lo < hi <= 9000 and hi / lo <= 6 for hi, lo in zip(his, los)):
            continue
        hdr = _t_header(cells, i)
        if not hdr:
            continue
        order, h0 = hdr
        yr = None
        for k in range(i - 1, max(-1, h0 - 5), -1):
            m = T_YEAR.match(cells[k])
            if m:
                yr = int(m.group(1))
                break
        if yr is None:
            continue
        for q, hi, lo in zip(order, his, los):
            rows.append({"q": q, "yr": yr, "hi": hi, "lo": lo, "how": "S5縦"})
    if rows:
        ymax = max(r["yr"] for r in rows)
        if rep:
            ymax = min(ymax, int(rep[:4]))
        for r in rows:
            fe = _fy_end(rep, ymax - r["yr"], fye_end)
            r["a"], r["b"] = (_qwin(fe, r["q"]) if fe else q_window(r["yr"], r["q"], fye_end))
    return rows


def _q_filter(rows, rep):
    if rep:
        R = datetime.date.fromisoformat(rep)
        rows = [r for r in rows if "a" in r and
                R - datetime.timedelta(days=760) <= r["a"] and r["b"] <= R + datetime.timedelta(days=40)]
    # 同じ四半期の窓は**最初に出た行**だけ（後ろに配当の表が続く版組で、配当の行を
    # 株価として拾わない）
    seen, uniq = set(), []
    for r in rows:
        k = (r.get("a"), r.get("b"))
        if k in seen or r.get("a") is None:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def item5_quarters_v2(t, fye_end, rep=None):
    """Item5 から [{a,b,hi,lo}] を返す（v2・横並びの2年を列の組で読む）。"""
    if t.startswith("__ERR__"):
        return [], t[7:]
    t = SUP_ORD.sub(r"\1\2", t)
    for w in _item5_windows(t):
        for rows in _parse_item5_window(w, fye_end, rep):
            uniq = _q_filter(rows, rep)
            if len(uniq) >= 4:
                return uniq, None
    # 予備: 四半期が列の表（S5）。文書全体から読む（見出しが価格の行から離れているため）
    uniq = _q_filter(_parse_transposed(t, fye_end, rep), rep)
    if len(uniq) >= 4:
        return uniq, None
    return [], "no_quarter_rows"


def start_ok(iv, asof, tol=45):
    """区間が **asof の隣の四半期**から作られたか（v2 の検問）。"""
    if not iv:
        return False
    A = datetime.date.fromisoformat(asof)
    qa, qb = datetime.date.fromisoformat(iv["qa"]), datetime.date.fromisoformat(iv["qb"])
    T = datetime.timedelta(days=tol)
    if iv["how"] in ("交差", "隙間"):
        return abs((qa - A).days) <= tol and abs((qb - A).days) <= tol
    return qa - T <= A <= qb + T


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
    # v2: 境界を跨ぐ組が無ければ、**asof を含む四半期**を先に採る（決算期が暦とずれる社は
    # asof が四半期の途中に落ちる。v1 は次の四半期を採っていた＝窓が最大3ヶ月ずれる）
    cont = [c for c in cand if c["a"] <= A <= c["b"]]
    c = cont[0] if cont else (q or p)
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
    # ★px_guard（2026-09-23）: 台帳より遅く始まる応答はキャッシュに焼き付けない（retro_delisted.yahoo と同じ）
    import px_guard as PXG
    if PXG.vet(sym, out["pts"], "retro_delisted_secpx.yahoo_close", req_start=t0) is None:
        return {"pts": [], "err": "px_guard_refused(台帳より短い)"}
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
TARGET_STATUS = ("no_price", "unresolved", "no_start", "manual_unverified")


def targets(vint):
    src = json.load(open(os.path.join(OUT, f"retro_delisted_{vint}.json")))
    # manual_unverified（手動の名寄せが退場日で裏を失った社）も価格が無い＝原本で採る側
    rows = [r for r in src["rows"] if r["status"] in TARGET_STATUS]
    rows.sort(key=lambda r: (not r.get("quality"), r["cik"]))   # 質実証を先に
    return src, rows


def exit_prev_date(r):
    """その行の END を採ったときの退場日。v2 以前の記録は exit_used を持たないので、
    retro_delisted が残した旧の退場日（exit_prev）で採ったとみなす。"""
    return (r.get("exit_prev") or {}).get("exit_date", r.get("exit_date"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, default=2013)
    ap.add_argument("--subs", action="store_true")
    ap.add_argument("--end", action="store_true")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--closes", action="store_true")
    ap.add_argument("--reused", action="store_true",
                    help="退場（合併・破産）の後も記号の系列が続く survivor を原本で測り直す")
    ap.add_argument("--nonma", action="store_true",
                    help="非M&Aの打ち切り（破産・登録抹消…）の返り値を原本から戻す")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quality", action="store_true", help="質実証プールだけ")
    ap.add_argument("--force", action="store_true",
                    help="--end と併用: 全社の対価を今の抽出器で採り直す（本文はキャッシュ）。"
                         "--start --reparse と併用: v2 の記録も今の読みで読み直す。"
                         "--nonma / --reused と併用: 既存の記録も採り直す")
    ap.add_argument("--retry", action="store_true",
                    help="--end と併用: 対価が採れていない社を v2 の提出索引で採り直す")
    ap.add_argument("--reparse", action="store_true",
                    help="--start と併用: Item5 を v2 の読みで読み直す（v1 の記録は各行の v1 に残す）")
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
                # **退場日が変わった社は採り直す**（合併対価は退場日の前後の窓で探すので、
                # 誤った退場日で探した結果は使えない）。v2 以前の記録は exit_used を持たない
                used = res[k].get("exit_used", exit_prev_date(r))
                if used == r.get("exit_date") and not a.force and \
                        not (a.retry and not res[k].get("px") and not res[k].get("retried")):
                    res[k].setdefault("exit_used", used)
                    continue
                # 最初の版（2026-08-10 の採取）は v1 に残す（何度採り直しても上書きしない）
                v1 = res[k].get("v1") or {kk: vv for kk, vv in res[k].items()
                                          if kk not in ("superseded", "v1")}
                res[k] = {"v1": v1, **extract_end(r)}
                if used == r.get("exit_date"):
                    res[k]["retried"] = ("抽出器の是正後に採り直し" if a.force else
                                         "v2の提出索引（古いページ込み）で採り直し")
            else:
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
            if k in res and (not a.reparse or (res[k].get("parser") == "v2" and not a.force)):
                continue
            if a.reparse:
                # v2 の読み（横並びの2年を列の組で読む・区間の検問）。v1 の記録は v1 に残す
                # （--force: v2 の記録も今の読みで読み直す。v1 は最初の版のまま運ぶ）
                old = res.get(k)
                res[k] = extract_start_v2(r, ASOF)
                if old is not None:
                    v1 = old.get("v1") if old.get("parser") == "v2" else old.get("v1", old)
                    if v1 is not None:
                        res[k]["v1"] = v1
            else:
                res[k] = extract_start(r, ASOF)
            if i % 10 == 0:
                json.dump(res, open(p, "w"), ensure_ascii=False)
                print(f"  start {i}/{len(rows)} ok={sum(1 for v in res.values() if v.get('lo'))}",
                      flush=True)
        json.dump(res, open(p, "w"), ensure_ascii=False)
        print("start done", len(res), "with interval:", sum(1 for v in res.values() if v.get("lo")))
        return

    if a.nonma:
        res = {}
        p = os.path.join(OUT, f"retro_delisted_secpx_{V}_nonma.json")
        if os.path.exists(p):
            res = json.load(open(p))
        prev_out = {}
        pp = os.path.join(OUT, f"retro_delisted_secpx_{V}.json")
        if os.path.exists(pp):
            prev_out = {str(x["cik"]): x for x in json.load(open(pp)).get("rows", [])}
        for i, r in enumerate(rows):
            k = str(r["cik"])
            po = prev_out.get(k, {})
            # 対象: 打ち切りのうち合併対価が存在しない種類（と、v2 で「生存」なのに価格が無い社）
            if not ((po.get("kind") == "打ち切り" or po.get("nonma")) and
                    (r.get("exit_kind") in NONMA_KINDS)):
                continue
            if k in res and res[k].get("exit_used") == r.get("exit_date") and not a.force:
                continue
            res[k] = extract_nonma(r, ASOF)
            json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
            print(f"  nonma {k} {r['name'][:30]} -> {res[k].get('how') or res[k].get('note')}", flush=True)
        json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
        print("nonma done", len(res), "restored:", sum(1 for v in res.values() if v.get("how")))
        return

    if a.reused:
        # survivor のうち、v2 の退場（合併・破産）より 400日以上先まで Yahoo の系列が続く社
        # ＝**同じ記号を後の別会社が使っている**か**承継会社の系列**。合併対価（現金）か破産の
        # 消却が原本で取れた社は、その記号の系列ではなく原本の値で測り直す
        res = {}
        p = os.path.join(OUT, f"retro_delisted_secpx_{V}_reused.json")
        if os.path.exists(p):
            res = json.load(open(p))
        cand = [r for r in src["rows"] if r["status"] == "survivor"
                and r.get("corroboration") == "continuous"
                and (r.get("exit_basis") or "")[:1] in ("①", "②")
                and (r.get("quality") or not a.quality)]
        print(f"reused: {len(cand)}社（survivor・v2 の退場の後も系列が続く）")
        for r in cand:
            k = str(r["cik"])
            if k in res and res[k].get("exit_used") == r.get("exit_date") and not a.force:
                continue
            rec = {"exit_used": r.get("exit_date"), "exit_kind": r.get("exit_kind"),
                   "ticker": r.get("ticker_hist"), "end": extract_end(r),
                   "start": extract_start_v2(r, ASOF)}
            if r.get("exit_kind") == "bankruptcy":
                rec["nonma"] = extract_nonma(r, ASOF)
            res[k] = rec
            json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
            print(f"  {k} {r['name'][:28]} {r.get('ticker_hist')} end={rec['end'].get('px') or rec['end'].get('note')}"
                  f" start={rec['start'].get('lo') or rec['start'].get('note')}"
                  f" nonma={(rec.get('nonma') or {}).get('how')}", flush=True)
        json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
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
    ex = r.get("exit_date")
    out = _extract_end(r)
    out["exit_used"] = ex
    return out


def _extract_end(r):
    cik = r["cik"]
    s = subs_full(cik)
    if s.get("err"):
        return {"note": "subs:" + s["err"]}
    ex = r.get("exit_date")
    if not ex or ex == "unknown":
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
        if c["sz"] > MAXSUB:
            continue
        t = doc_text(cik, c["acc"], c["doc"], "E")
        px, note, ev = merger_price(t, _names(cik, s.get("name"), r.get("name")))
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


FRAMES = os.path.join(CACHE, "frames")
_FLOAT = {}


def float_implied(cik, asof):
    """**独立の検算**: 10-K 表紙の非関係者の時価総額（dei:EntityPublicFloat・asof の直前の
    6月末）÷ 同じ日の発行済株数（us-gaap:CommonStockSharesOutstanding）。関係者の持分を
    除くので**真の株価以下**に出る（中央値で 0.93 倍）。12月決算の社にしか当たらない。
    SEC XBRL frames を2本だけ読む（全社ぶん一度に返る）。"""
    if not _FLOAT:
        os.makedirs(FRAMES, exist_ok=True)
        y = asof[:4]
        for key, concept in (("float", f"dei/EntityPublicFloat/USD/CY{y}Q2I"),
                             ("shares", f"us-gaap/CommonStockSharesOutstanding/shares/CY{y}Q2I"),
                             ("deishares", f"dei/EntityCommonStockSharesOutstanding/shares/CY{y}Q3I")):
            p = os.path.join(FRAMES, f"{key}_{concept.split('/')[-1]}.json")
            if not os.path.exists(p):
                raw, err = _get(f"https://data.sec.gov/api/xbrl/frames/{concept}.json", SEC_UA)
                time.sleep(0.11)
                if raw is None:
                    _FLOAT[key] = {}
                    continue
                open(p, "wb").write(raw)
            _FLOAT[key] = {d["cik"]: d for d in json.load(open(p)).get("data", [])}
    f = _FLOAT.get("float", {}).get(int(cik))
    s = _FLOAT.get("shares", {}).get(int(cik)) or _FLOAT.get("deishares", {}).get(int(cik))
    if not f or not s or not s.get("val"):
        return None
    if abs((datetime.date.fromisoformat(f["end"]) - datetime.date.fromisoformat(asof)).days) > 15:
        return None
    return {"px": f["val"] / s["val"], "float_end": f["end"], "shares_end": s["end"],
            "float_accn": f.get("accn"), "shares_accn": s.get("accn")}


def filing_index(cik, acc):
    """提出一式の中のファイル名（index.json）。キャッシュつき。"""
    p = os.path.join(DOCS, f"IDX_{cik}_{acc.replace('-', '')}.json")
    if os.path.exists(p):
        return json.load(open(p))
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/index.json"
    raw, err = _get(url, SEC_UA, timeout=60)
    time.sleep(0.11)
    out = {"err": err} if raw is None else {
        "items": [{"name": x.get("name"), "size": x.get("size")}
                  for x in json.loads(raw.decode("utf-8", "replace")).get("directory", {}).get("item", [])]}
    json.dump(out, open(p, "w"))
    return out


EX13 = re.compile(r"(?i)(?:^|[^a-z0-9])(?:ex|exh|exhibit)[-_ ]?13(?![0-9])[^/]*\.(?:htm|html|txt)$")


def item5_with_ex13(cik, c, fye):
    """本文に四半期高安が無ければ**年次報告書の添付（EX-13）**を読む。古い大会社は
    Item5・Item8 を『年次報告書の◯頁を参照』で済ませ、価格表は EX-13 にしか無い
    （実測 TSYS『Quarterly Financial Data (Unaudited), Stock Price, Dividend Information』）。"""
    t = doc_text(cik, c["acc"], c["doc"], "S")
    rows, note = item5_quarters_v2(t, fye, c.get("rep"))
    if rows:
        return rows, note, None
    ix = filing_index(cik, c["acc"])
    for it in (ix.get("items") or []):
        nm = it.get("name") or ""
        if nm == c["doc"] or not EX13.search(nm):
            continue
        t13 = doc_text(cik, c["acc"], nm, "S13")
        r13, n13 = item5_quarters_v2(t13, fye, c.get("rep"))
        if r13:
            return r13, None, nm
    return rows, note, None


def extract_start_v2(r, asof):
    """v2: asof の後の**最初の2本の10-K**の Item5 を v2 の読みで読み、四半期を**合わせて**
    区間を作る（6月決算の社は asof の前の四半期と後の四半期が別の10-Kに載る）。
    区間が asof の隣の四半期から作れなければ使わない（start_window_off）。"""
    cik = r["cik"]
    s = subs_full(cik)
    if s.get("err"):
        return {"note": "subs:" + s["err"], "parser": "v2"}
    fye = (s.get("fye") or "1231")
    tens = [x for x in s["f"] if x["form"] in ("10-K", "10-K405", "10-KSB")
            and x["d"] >= asof]
    tens.sort(key=lambda x: x["d"])
    if not tens:
        return {"note": "no_10k_after_asof", "parser": "v2"}
    note, allrows, used, exh = None, [], [], []
    for c in tens[:2]:
        if not c["doc"] or c["sz"] > MAXSUB:
            continue
        rows, note, ex13 = item5_with_ex13(cik, c, fye)
        if not rows:
            continue
        if ex13:
            exh.append(ex13)
        seen = {(x["a"], x["b"]) for x in allrows}
        # 2本の10-Kの**重なる四半期**で基準をそろえる: 2本目の表が分割で調整されていたら
        # （実測 Continental: FY2014 の表は2014年9月の2:1分割の後＝2013年も半値）、
        # 2本目の行を1本目の基準へ戻してから足す。比が分割のきれいな比でなければ足さない
        if allrows:
            ov = [(x["hi"] / y["hi"], x["lo"] / y["lo"]) for x in allrows for y in rows
                  if (x["a"], x["b"]) == (y["a"], y["b"])]
            if ov:
                rr = sorted(v for pr in ov for v in pr)[len(ov)]
                if abs(rr - 1) > 0.03:
                    cr = clean_ratio(rr)
                    if not cr:
                        continue
                    rows = [{**y, "hi": round(y["hi"] * cr, 4), "lo": round(y["lo"] * cr, 4),
                             "rebased": cr} for y in rows]
        allrows += [x for x in rows if (x["a"], x["b"]) not in seen]
        used.append(c)
    if not allrows:
        return {"note": note or "no_interval", "parser": "v2"}
    iv = start_interval(allrows, fye, asof)
    if not iv:
        return {"note": "no_interval", "parser": "v2"}
    c = used[0]
    iv.update({"from": c["form"], "d": c["d"], "acc": c["acc"], "fye": fye, "rep": c.get("rep"),
               "layout": sorted({x.get("how") for x in allrows}), "parser": "v2",
               "docs": [x["acc"] for x in used]})
    if exh:
        iv["ex13"] = exh
    if any(x.get("rebased") for x in allrows):
        iv["rebased_2nd_doc"] = sorted({x["rebased"] for x in allrows if x.get("rebased")})
    if not start_ok(iv, asof):
        return {"note": "start_window_off", "parser": "v2", "rejected": iv}
    # 公開浮動株からの含意株価で検算（関係者の持分があるので**下限**としてだけ使う）:
    # 表の区間が含意株価より 25% 以上**低い**なら、表の読みが別の年・別の列を拾っている
    # （実測 TEGNA: 表 [13.73,15.28] に対し含意 24.53）。単位違い（100倍超）は検算に使わない
    fi = float_implied(cik, asof)
    if fi:
        ratio = fi["px"] / math.sqrt(iv["lo"] * iv["hi"])
        iv["float_check"] = {"implied_px": round(fi["px"], 2), "ratio": round(ratio, 3),
                             "float_end": fi["float_end"], "accn": fi["float_accn"]}
        # 単位の違い（浮動株が千ドル単位など）は**10の累乗にほぼ一致する比**だけ。それ以外で
        # 大きく外れたら表の読み違い（実測 Avago: 配当の表 [0.15,0.21] を株価と読むと比は約190）
        # 浮動株が 0・欠測のときは検算に使わない（実測 Stamps.com: EntityPublicFloat=0）
        lg = math.log10(ratio) if ratio > 0 else 99.0
        unit = (abs(lg) >= 0.96 and abs(lg - round(lg)) < 0.04) or abs(lg) > 3.5
        if not unit and (ratio > 1.25 or ratio < 0.25):
            return {"note": "start_float_mismatch", "parser": "v2", "rejected": iv}
    return iv


# ── 非M&Aの退場の返り値を原本から戻す（2026-09-23・todo retro_base_rate_band (b)）──────────
#   合併対価が存在しない種類（破産・登録抹消・上場基準・提出停止）は左尾を作る側なのに、
#   v1 では**全部が打ち切り**だった。二つの経路で原本から戻す:
#   ① 破産: 計画の効力発生・認可の 8-K（item 1.03/3.03/5.01）に**既存の普通株の扱い**が
#      書いてある。『消却され分配なし』なら終値 0（−100%）。『新ワラントのみ』も 0 とみなす
#      （旧株1株あたりの価値は始値の数%に届かず、−15%/年の線から遠い）。
#   ② それ以外（と①で文言が無い破産）: 退場前の最後の 10-K の Item5 の四半期高安
#      ＝**最後の気配**。そこで打ち切る（その後の値動きは測らない＝生存時間解析の形）。
#   **原本に書いていなければ戻さない**（誤値より空欄）。
NONMA_KINDS = ("bankruptcy", "deregistered", "listing_deficiency", "stopped_filing")
EQ_SUBJ = (r"(?:existing|old|outstanding|prepetition|previously\s+issued\s+and\s+outstanding)\s+"
           r"(?:shares\s+of\s+)?(?:the\s+company.s\s+|our\s+|its\s+|parent\s+)?"
           r"(?:common\s+stock|equity(?:\s+interests?)?|common\s+shares|interests|parent\s+equity\s+interests)")
# 『all outstanding shares of its common stock … will be cancelled under the Plan, with shareholders
#   receiving no distributions thereunder』（実測 GNC 2020-10-07 の 8-K item 2.01）も読む
EQ_CANCEL = re.compile(
    r"(?is)(?:" + EQ_SUBJ + r"|holders\s+of\s+(?:the\s+|our\s+)?common\s+stock)[^.]{0,400}?"
    r"(?:without\s+(?:any\s+)?(?:distribution|consideration|value|compensation)|"
    r"will\s+not\s+receive\s+(?:a|any)\s+distribution|have\s+no\s+value|"
    r"receiv(?:e|ing)\s+no\s+(?:recovery|distributions?)|"
    r"not\s+(?:receive|be\s+entitled\s+to)\s+(?:a\s+|any\s+)?(?:recovery|distributions?))")
EQ_WARRANT = re.compile(
    r"(?is)(?:holders?\s+of\s+(?:allowed\s+)?" + EQ_SUBJ + r")[^.]{0,200}?receive\s+"
    r"(?:its|their)\s+pro\s+rata\s+share\s+of\s+the\s+new\s+warrants")


def extract_nonma(r, asof):
    cik, ex, kind = r["cik"], r.get("exit_date"), r.get("exit_kind")
    s = subs_full(cik)
    if s.get("err"):
        return {"note": "subs:" + s["err"], "exit_used": ex}
    if not ex or ex == "unknown":
        return {"note": "no_exit_date", "exit_used": ex}
    E = datetime.date.fromisoformat(ex)
    out = {"exit_used": ex, "exit_kind": kind}
    if kind == "bankruptcy":
        # 計画・売却の完了の 8-K（item 2.01・8.01）にも普通株の扱いが書かれる（GNC は 2.01 にだけ）
        docs = [x for x in s["f"] if x["form"] == "8-K"
                and E - datetime.timedelta(days=200) <= datetime.date.fromisoformat(x["d"])
                <= E + datetime.timedelta(days=900)
                and any(it in (x.get("items") or "") for it in ("1.03", "3.03", "5.01", "2.01", "8.01"))]
        docs.sort(key=lambda x: x["d"])
        for x in docs:
            if not x["doc"] or x["sz"] > MAXSUB:
                continue
            t = doc_text(cik, x["acc"], x["doc"], "B")
            for pat, how in ((EQ_CANCEL, "破産: 既存の普通株は消却・分配なし"),
                             (EQ_WARRANT, "破産: 既存の普通株は消却・新ワラントの按分のみ")):
                m = pat.search(t[:900000])
                if m:
                    a0 = max(t.rfind(".", 0, m.start()) + 1, m.start() - 160)
                    return {**out, "end_lo": 0.0, "end_hi": 0.0, "end_date": x["d"], "how": how,
                            "form": "8-K", "acc": x["acc"], "items": x.get("items"),
                            "ev": re.sub(r"\s+", " ", t[a0:m.end() + 100])[:600]}
        # 破産で計画の文言が見つからない社に**古い気配**を当てると、申立て前の株価で打ち切る
        # ことになり損失を小さく見せる（実測 ADDvantage: 最後の表は申立ての15か月前）。打ち切りのまま
        return {**out, "note": "破産: 計画の8-Kに既存の普通株の扱いが見つからない（打ち切りのまま）"}
    # 最後の気配（退場前の最後の 10-K の Item5）
    fye = (s.get("fye") or "1231")
    tens = [x for x in s["f"] if x["form"] in ("10-K", "10-K405", "10-KSB")
            and asof < x["d"] <= (E + datetime.timedelta(days=120)).isoformat()]
    tens.sort(key=lambda x: x["d"], reverse=True)
    for c in tens[:2]:
        if not c["doc"] or c["sz"] > MAXSUB:
            continue
        t = doc_text(cik, c["acc"], c["doc"], "S")
        rows, note = item5_quarters_v2(t, fye, c.get("rep"))
        rows = [q for q in rows if q["b"] <= E + datetime.timedelta(days=30)
                and q["b"] > datetime.date.fromisoformat(asof) + datetime.timedelta(days=90)]
        if not rows:
            continue
        q = max(rows, key=lambda q: q["b"])
        return {**out, "end_lo": q["lo"], "end_hi": q["hi"], "end_date": q["b"].isoformat(),
                "how": "最後の気配（退場前の最後の10-K の Item5 四半期高安）",
                "form": c["form"], "acc": c["acc"], "d": c["d"],
                "stale_days": (E - q["b"]).days}
    return {**out, "note": "no_last_quote"}


# ── 分割の検問（2026-09-23・頭注の『未実装の穴』を塞ぐ）─────────────────────────────
#   10-K の Item5 の表は**その10-Kの提出時点までの分割で調整済み**。表を読んだ10-Kの後・
#   退場までの間に分割があると、始値（分割前の値）と終値（分割後の合併対価）は**基準が違う**。
#   実測 Continental Resources: FY2013 の表の 2013年Q2/Q3 は [86.56, 89.63]、2014年9月に 2:1
#   分割、2022年の非公開化は $74.28（分割後）→ そのまま割ると −1.8%/年、正しくは +5.7%/年。
#   **原本の中で測る**: 会社は分割の後、過去の EPS を**遡って**分割後の株数で書き直す。
#   companyfacts（XBRL）には同じ期間の EPS が提出書類ごとに残るので、**同じ期間の EPS が
#   二つの提出書類の間できれいな比（2・3・1/5…）で変わったら、その間に分割がある**。
#   比は複数の期間で一致すること（修正再表示は期間ごとに比が違う）、EPS の絶対値が 0.30 以上
#   （丸めの誤差）を条件にする。窓は期間ごとの窓の**共通部分**。
#   始値の10-K の提出日 d0 と終値の日 d1 の**間に窓がまるごと入る**分割だけ掛ける。窓が
#   d0 か d1 を跨ぐ（前か後か決まらない）ときは**測らない**（誤値より空欄）。
CF_ZIP = os.path.join(BASE, "companyfacts.zip")
SPLITS = os.path.join(CACHE, "splits")
SPLIT_RATIOS = sorted({2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 1.5, 1.25, 4 / 3, 5 / 3, 1.2, 2.5, 7 / 4} |
                      {1 / x for x in (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100,
                                       1.5, 1.25)})
EPS_TAGS = ("EarningsPerShareBasic", "EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
SH_TAGS = ("WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageNumberOfDilutedSharesOutstanding",
           "WeightedAverageNumberOfShareOutstandingBasicAndDiluted")
_CFZ = None


def clean_ratio(r, tol=0.02):
    """r が分割のきれいな比に近ければその比。株式配当（1.02〜1.10）は丸めの誤差と区別できないので数えない。"""
    if not r or r <= 0:
        return None
    best = min(SPLIT_RATIOS, key=lambda v: abs(math.log(r / v)))
    return best if abs(r / best - 1) <= tol else None


def eps_facts(cik):
    """companyfacts の EPS と加重平均株数（種類・タグ・期間・提出日・提出書類・値）。
    キャッシュつき。zip が無ければ None。"""
    p = os.path.join(SPLITS, f"{int(cik)}.json")
    if os.path.exists(p):
        return json.load(open(p))
    global _CFZ
    if _CFZ is None:
        if not os.path.exists(CF_ZIP):
            return None
        _CFZ = zipfile.ZipFile(CF_ZIP)
    try:
        j = json.loads(_CFZ.read(f"CIK{int(cik):010d}.json"))
    except KeyError:
        out = []
    else:
        g = (j.get("facts") or {}).get("us-gaap") or {}
        out = []
        for kind, tags, ok in (("eps", EPS_TAGS, lambda u: "/shares" in u),
                               ("sh", SH_TAGS, lambda u: u == "shares")):
            for tag in tags:
                for unit, arr in ((g.get(tag) or {}).get("units") or {}).items():
                    if not ok(unit):
                        continue
                    out += [[kind, tag, x.get("start"), x.get("end"), x.get("filed"), x.get("accn"),
                             x.get("val")] for x in arr]
    os.makedirs(SPLITS, exist_ok=True)
    json.dump(out, open(p, "w"))
    return out


def split_events(cik):
    """分割の候補を EPS の書き直しから作り、**窓の前後で全系列を突き合わせて**確かめる。
    修正再表示（非継続事業の組み替え等）は期間ごとに比が散る（実測 CAI International 2020:
    2019年上期 1.30→1.09 の 1.19 が『1.2 の分割』に見えたが、同じ窓で他の期間は 2.5・0.9…）。
    分割なら**すべての期間の EPS が同じ比で下がり、加重平均株数が同じ比で増える**。"""
    facts = eps_facts(cik)
    if facts is None:
        return None
    ser = collections.defaultdict(dict)
    for kind, tag, s0, e0, filed, accn, val in facts:
        if val is None or not filed:
            continue
        ser[(kind, tag, s0, e0)].setdefault(accn, (filed, val))
    ser = {k: sorted(v.values()) for k, v in ser.items()}
    # 1) 候補: 同じ期間の EPS（または加重平均株数）が隣り合う提出書類の間できれいな比で変わった窓。
    #    比は**価格の比**にそろえる（EPS: 前÷後／株数: 後÷前。2:1 分割ならどちらも 2）
    cands = []
    for key, seq in ser.items():
        for (fa, va), (fb, vb) in zip(seq, seq[1:]):
            if fa >= fb:
                continue
            if key[0] == "eps":
                if abs(va) < 0.30 or abs(vb) < 0.30 or (va > 0) != (vb > 0):
                    continue
                q = va / vb
            else:
                if not va or not vb or va <= 0 or vb <= 0:
                    continue
                q = vb / va
            cr = clean_ratio(q, 0.035)
            if cr and abs(q - 1) > 0.03:
                cands.append({"lo": fa, "hi": fb, "ratio": cr})
            elif key[0] == "sh" and abs(math.log(q)) > math.log(1.15) and \
                    min(abs(math.log10(q) - p) for p in (-6, -3, 3, 6)) > 0.01:
                # （千株・百万株の単位の付け替え＝ちょうど 10^±3 は分割ではない。実測 Continental 2012）
                # きれいでない比（1:6.6 の併合・実測 Cedar Realty 2020）は**株数だけ**から候補にし、
                # 確かめも株数で行う（EPS は小さく丸めの誤差が大きい）
                cands.append({"lo": fa, "hi": fb, "ratio": float(f"{q:.4g}"), "raw": True})
    cands.sort(key=lambda e: (e["lo"], e["hi"]))
    wins = []
    for e in cands:
        for m in wins:
            lo, hi = max(m["lo"], e["lo"]), min(m["hi"], e["hi"])
            if abs(m["ratio"] / e["ratio"] - 1) < (0.02 if (m.get("raw") or e.get("raw")) else 0.01) \
                    and lo < hi:
                m["lo"], m["hi"] = lo, hi
                if m.get("raw") and not e.get("raw"):
                    m["ratio"], m["raw"] = e["ratio"], False
                break
        else:
            wins.append(dict(e))
    # 2) 確かめ: 窓の前の最後の値と後の最初の値を、**全系列**で突き合わせる
    out = []
    for w in wins:
        r = w["ratio"]
        cnt = {"eps": [0, 0], "sh": [0, 0]}
        for key, seq in ser.items():
            before = [v for f, v in seq if f <= w["lo"]]
            after = [v for f, v in seq if f >= w["hi"]]
            if not before or not after:
                continue
            vb, va = before[-1], after[0]
            if key[0] == "eps":
                if abs(vb) < 0.30 or abs(va) < 0.30 or (vb > 0) != (va > 0):
                    continue
                q = vb / va
            else:
                if not vb or not va or vb <= 0 or va <= 0:
                    continue
                q = va / vb
            cnt[key[0]][0 if abs(q / r - 1) <= 0.035 else 1] += 1
        e_ok, e_ng = cnt["eps"]
        s_ok, s_ng = cnt["sh"]
        # 株数は損益の組み替えで書き直されない＝**分割の最も強い証拠**。株数で確かめられる窓は
        # 株数で裁き（EPS は向きが合っていればよい: 実測 Iconix 2018 の 1:10 併合は株数 12/12 が
        # ちょうど 0.1、EPS は別の修正再表示が重なって 4/11）、株数の無い窓は EPS だけで厳しく裁く
        if w.get("raw"):
            # EPS が比べられるなら**逆らわない**こと（単位の付け替えなら EPS は動かない）
            ok = s_ok >= 3 and s_ok >= 3 * s_ng and (e_ok + e_ng < 2 or e_ok >= e_ng)
        elif s_ok + s_ng >= 2:
            ok = s_ok >= 2 and s_ok >= 3 * s_ng and (e_ok + e_ng == 0 or e_ok >= 1)
        else:
            ok = e_ok >= 4 and e_ok >= 3 * e_ng
        if ok:
            out.append({"lo": w["lo"], "hi": w["hi"], "ratio": round(r, 6), "clean": not w.get("raw"),
                        "eps_agree": e_ok, "eps_disagree": e_ng, "sh_agree": s_ok, "sh_disagree": s_ng})
    return out


def split_factor(cik, d0, d1):
    """表を読んだ10-K の提出日 d0 から d1（退場・最後の気配の10-K）までの分割の累積比。
    戻り値 (F, 掛けた分割, 前後の決まらない分割, 検問できたか)。始値は F で割る。"""
    if os.environ.get("RETRO_SECPX_NO_SPLIT") == "1":   # 層の比較用（検問を外した版）
        return 1.0, [], [], True
    evs = split_events(cik)
    if evs is None or not d0 or not d1:
        return 1.0, [], [], False
    F, used, amb = 1.0, [], []
    for e in evs:
        if e["hi"] <= d0 or e["lo"] >= d1:
            continue
        if e["lo"] >= d0 and e["hi"] <= d1:
            F *= e["ratio"]
            used.append(e)
        else:
            amb.append(e)
    return F, used, amb, bool(eps_facts(cik))


def _stat(vals, label):
    if not vals:
        return {"n": 0}
    neg = [v for v in vals if v < 0]
    perm = [v for v in vals if v <= -0.15]
    return {"n": len(vals), "median": round(st.median(vals), 4), "min": round(min(vals), 4),
            "元本割れ": len(neg), "元本割れ率": round(len(neg) / len(vals), 4),
            "恒久毀損": len(perm), "恒久毀損率": round(len(perm) / len(vals), 4)}


def _reason(x):
    """打ち切りの理由（v1 は start の有無と理由の札が逆になっていた＝『始値なし』の45社は
    実は**始値はある**社だった。ここで札を正す）。"""
    if x.get("note_censor"):
        return x["note_censor"]
    if not x.get("end_px") and not x.get("start_lo"):
        return f"終値も始値もなし(end:{x.get('end_note')}/start:{x.get('start_note')})"
    if not x.get("end_px"):
        return f"終値なし:{x.get('end_note')}"
    if not x.get("start_lo"):
        return f"始値なし:{x.get('start_note')}"
    return "その他"


def analyse2(V, ASOF, src):
    """左尾を『退場込み・price-only』で組み直す。survivorも close(配当なし)へ降ろす。"""
    END = json.load(open(os.path.join(OUT, f"retro_delisted_secpx_{V}_end.json")))
    START = json.load(open(os.path.join(OUT, f"retro_delisted_secpx_{V}_start.json")))
    np_ = os.path.join(OUT, f"retro_delisted_secpx_{V}_nonma.json")
    NONMA = json.load(open(np_)) if os.path.exists(np_) else {}
    rp_ = os.path.join(OUT, f"retro_delisted_secpx_{V}_reused.json")
    REUSED = json.load(open(rp_)) if os.path.exists(rp_) else {}
    outp = os.path.join(OUT, f"retro_delisted_secpx_{V}.json")
    # 前回の出力: survivor の close が手元のキャッシュに無いときは**前回の値を運ぶ**
    # （close は 2026-08-10 に採った。今日採り直すと 8月の月足が月末値に替わり、
    #   上場廃止された社は404になる＝**ベンダーの漂流を是正の効果と取り違える**）
    prev = json.load(open(outp)) if os.path.exists(outp) else {}
    prev_sur = {r["cik"]: r for r in prev.get("rows", []) if r.get("kind") == "survivor"}
    hz = datetime.date.fromisoformat(HORIZON)
    A = datetime.date.fromisoformat(ASOF)
    v2 = src.get("exit_rule") == "v2"
    subs = {}
    rows_out = []

    def _split(rec, cik, d0, d1):
        """始値の表（d0 提出の10-K）から d1 までの分割。rec に残し (F, 決まらない) を返す。"""
        F, used, amb, ok = split_factor(cik, d0, d1)
        if used:
            rec["split"] = {"factor": round(F, 6), "events": used, "from": d0, "to": d1}
        if amb:
            rec["split_ambiguous"] = amb
        if not ok:
            rec["split_unchecked"] = "companyfacts に EPS が無い（分割の検問なし）"
        return F, bool(amb)

    for r in src["rows"]:
        k = str(r["cik"])
        rec = {"cik": r["cik"], "name": r["name"], "quality": bool(r.get("quality")),
               "status": r["status"], "exit_kind": r.get("exit_kind")}
        if v2:
            rec["exit_basis"] = r.get("exit_basis")
            rec["exit_prev"] = {kk: (r.get("exit_prev") or {}).get(kk)
                                for kk in ("exit_date", "exit_kind")}
        ru = REUSED.get(k) or {}
        if r["status"] == "survivor" and ru and ru.get("exit_used") == r.get("exit_date"):
            e_, s_, n_ = ru.get("end") or {}, ru.get("start") or {}, ru.get("nonma") or {}
            ex_ = r.get("exit_date")
            if e_.get("form") == "8-K" and e_.get("date") and abs(
                    (datetime.date.fromisoformat(e_["date"]) - datetime.date.fromisoformat(ex_)).days) <= 45:
                ex_ = e_["date"]
            meas = None
            if n_.get("how") and n_.get("end_hi") == 0.0:
                meas = ("破産で消却（" + n_["how"] + "）", -1.0, -1.0, -1.0, n_.get("end_date") or ex_)
            elif e_.get("px") and s_.get("lo"):
                yrs_ = (datetime.date.fromisoformat(ex_) - A).days / 365.25
                F_, amb_ = _split(rec, r["cik"], s_.get("d"), ex_)
                if not amb_:
                    lo_s, hi_s = s_["lo"] / F_, s_["hi"] / F_
                    meas = ("10-K Item5 の高安 ÷ 合併対価", cagr(hi_s, e_["px"], yrs_),
                            cagr(lo_s, e_["px"], yrs_),
                            cagr(math.sqrt(lo_s * hi_s), e_["px"], yrs_), ex_)
            if meas:
                ed = meas[4]
                # status も替える: 下流の器の一部は status=='survivor' で生存者を数える
                rec.update({"kind": "退場(測定)", "reused_ticker": ru.get("ticker"),
                            "status": "survivor→退場(記号の使い回し)",
                            "years": round((datetime.date.fromisoformat(ed) - A).days / 365.25, 2),
                            "basis": "price-only（" + meas[0] + "・Yahoo の系列は退場の後に別の証券）",
                            "exit_date_eff": ed, "end_px": e_.get("px"), "start_lo": s_.get("lo"),
                            "start_hi": s_.get("hi"), "ev_end": e_.get("ev") or n_.get("ev"),
                            "px_cagr_lo": meas[1], "px_cagr_hi": meas[2], "px_cagr": meas[3]})
                rows_out.append(rec)
                continue
        if r["status"] == "survivor" and r.get("cands"):
            p = os.path.join(PX, f"YC_{r['cands'][0].replace('/', '-')}.json")
            pts = (json.load(open(p)).get("pts") or []) if os.path.exists(p) else []
            a, b = pick(pts, ASOF), pick(pts, HORIZON)
            if a and b and a[1] > 0:
                yrs = (hz - A).days / 365.25
                rec.update({"kind": "survivor", "px_cagr": cagr(a[1], b[1], yrs),
                            "years": round(yrs, 2), "basis": "close(分割調整・配当なし)"})
            elif r["cik"] in prev_sur:
                o = prev_sur[r["cik"]]
                rec.update({"kind": "survivor", "px_cagr": o.get("px_cagr"),
                            "years": o.get("years"), "basis": o.get("basis"),
                            "carried": "前回の出力の close を運んだ（キャッシュ無し）"})
                if o.get("note"):
                    rec["note"] = o["note"]
            else:
                rec.update({"kind": "survivor", "px_cagr": None, "note": "close未取得"})
            rows_out.append(rec)
            continue
        if r["status"] not in TARGET_STATUS:
            rows_out.append(rec | {"kind": "対象外"})
            continue
        e, s0 = END.get(k, {}), START.get(k, {})
        # 退場日は **合併完了8-K の日** を最優先（Form15/25 は証券の種類ごとに出るので当てにならない）
        ex = r.get("exit_date")
        if ex == "unknown":
            ex = None
        if e.get("form") == "8-K" and e.get("date") and (
                not v2 or not ex or abs((datetime.date.fromisoformat(e["date"]) -
                                         datetime.date.fromisoformat(ex)).days) <= 45):
            # v2: 合意の8-K（item 1.01）は完了の数か月前に出る。完了日から45日以内の8-K だけを
            # 退場日に採る（実測 IPC Healthcare: 合意 2015-08-07 / 完了 2015-11-23）
            ex = e["date"]
        rec.update({"exit_date_eff": ex, "end_px": e.get("px"), "end_form": e.get("form"),
                    "end_note": e.get("note"), "start_lo": s0.get("lo"), "start_hi": s0.get("hi"),
                    "start_how": s0.get("how"), "start_note": s0.get("note"),
                    "ev_end": e.get("ev")})
        if k not in subs:
            subs[k] = subs_full(r["cik"])
        tens = [x["d"] for x in (subs[k].get("f") or []) if x["form"].startswith("10-K")]
        late = [d for d in tens if ex and d > ex]
        rec["late_10k"] = max(late) if late else None
        if ex and ex <= ASOF:
            # asof より**前に**退場を終えていた社（H.J. Heinz: 2013-06-13 に買収完了）は
            # asof の時点で既に買えなかった＝母集団に入らない（v2 で退場日が正しく前へ動いた）
            # 下流の器（hist_val2_*・hist_wd_*）は kind=='対象外' だけを母集団から外すので、同じ札にする
            rec.update({"kind": "対象外", "note": "asof より前に退場（母集団外）", "years": round(
                (datetime.date.fromisoformat(ex) - A).days / 365.25, 2)})
            rows_out.append(rec)
            continue
        if v2 and r.get("exit_date") is None:
            # v2 が「普通株の退場の証拠なし＝地平まで生存」と判定した社。価格が採れていないだけ
            rec.update({"kind": "打ち切り", "note_censor": "生存（普通株の退場なし）だが価格なし"})
            rows_out.append(rec)
            continue
        if not (e.get("px") and s0.get("lo") and ex):
            nm = NONMA.get(k) or {}
            if nm.get("how") and nm.get("exit_used") == r.get("exit_date") and (
                    nm.get("end_hi") == 0.0 or s0.get("lo")):
                # 非M&A（破産・登録抹消…）を原本で戻した（extract_nonma の二経路）
                ed = nm.get("end_date") or ex
                yrs = (datetime.date.fromisoformat(ed) - A).days / 365.25
                if nm.get("end_hi") == 0.0:
                    lo_ = hi_ = mid_ = -1.0
                else:
                    # 最後の気配の表（nm["d"] 提出）も分割調整済み＝始値の表との間の分割だけ掛ける
                    F_, amb_ = _split(rec, r["cik"], s0.get("d"), nm.get("d") or ed)
                    if amb_:
                        rec.update({"kind": "打ち切り",
                                    "note_censor": "分割の時期が二つの表の間で決まらない"})
                        rows_out.append(rec)
                        continue
                    slo, shi = s0["lo"] / F_, s0["hi"] / F_
                    lo_ = cagr(shi, nm["end_lo"], yrs)
                    hi_ = cagr(slo, nm["end_hi"], yrs)
                    mid_ = cagr(math.sqrt(slo * shi),
                                math.sqrt(nm["end_lo"] * nm["end_hi"]), yrs)
                rec.update({"kind": "退場(測定)", "years": round(yrs, 2), "nonma": True,
                            "basis": "price-only（" + nm["how"] + "）",
                            "end_lo": nm.get("end_lo"), "end_hi": nm.get("end_hi"),
                            "end_date": ed, "end_acc": nm.get("acc"), "ev_nonma": nm.get("ev"),
                            "px_cagr_lo": lo_, "px_cagr_hi": hi_, "px_cagr": mid_})
                rows_out.append(rec)
                continue
            rec["kind"] = "打ち切り"
            if nm.get("note"):
                rec["nonma_note"] = nm["note"]
            rows_out.append(rec)
            continue
        yrs = (datetime.date.fromisoformat(ex) - A).days / 365.25
        if yrs <= 0.25:
            rec.update({"kind": "asof前後に退場", "years": round(yrs, 2)})
            rows_out.append(rec)
            continue
        # **退場後に10-Kを出していたら、その退場は普通株のものではない**→打ち切り（v1 の回避策）。
        # v2 の退場日は普通株を名指す Form 25/15・合併完了8-K・定期報告の停止で裁いてあるので、
        # その後の10-K は**子会社としての社債の報告**（Dow）か**再建後の会社**（Frontier）であって
        # 反証にならない。v1 の入力（exit_basis が無い）のときだけ回避策を使う。
        if late and not v2:
            rec.update({"kind": "打ち切り", "note": "退場日より後に10-K＝普通株の退場ではない",
                        "note_censor": "退場日より後に10-K（v1の回避策）"})
            rows_out.append(rec)
            continue
        # 分割: 始値の表（s0["d"] 提出）の後・退場までの分割で始値を割る（頭注の穴・2026-09-23）
        F, amb = _split(rec, r["cik"], s0.get("d"), ex)
        if amb:
            rec.update({"kind": "打ち切り", "note_censor": "分割の時期が始値の表と退場の間で決まらない"})
            rows_out.append(rec)
            continue
        slo, shi = s0["lo"] / F, s0["hi"] / F
        rec.update({"kind": "退場(測定)", "years": round(yrs, 2),
                    "basis": "price-only（10-K Item5 の高安 ÷ 合併対価）",
                    "px_cagr_lo": cagr(shi, e["px"], yrs),
                    "px_cagr_hi": cagr(slo, e["px"], yrs),
                    "px_cagr": cagr(math.sqrt(slo * shi), e["px"], yrs)})
        rows_out.append(rec)

    res = {"generated": str(datetime.date.today()), "tool": "night/retro_delisted_secpx.py",
           "vintage": V, "asof": ASOF, "horizon": HORIZON,
           "exit_rule": src.get("exit_rule", "v1"),
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
            "うち非M&Aを原本で戻した社数": sum(1 for x in sel if x["kind"] == "退場(測定)"
                                        and x.get("nonma")),
            "うち記号の使い回しで survivor から移した社数": sum(1 for x in sel if x.get("reused_ticker")),
            "うち分割で始値を調整した社数": sum(1 for x in sel if x["kind"] == "退場(測定)"
                                        and x.get("split")),
            "分割の検問なし(EPSが無い)の測定社数": sum(1 for x in sel if x["kind"] == "退場(測定)"
                                             and x.get("split_unchecked")),
            "まだ打ち切り": len(cen),
            "打ち切りの内訳": dict(collections.Counter(_reason(x) for x in cen).most_common()),
            "打ち切りの退場の種類": dict(collections.Counter(
                x.get("exit_kind") or "生存/不明" for x in cen).most_common()),
            "asof前後に退場(母集団外)": sum(1 for x in sel if x["kind"] == "asof前後に退場"
                                       or x.get("note") == "asof より前に退場（母集団外）"),
            "上界(打ち切りが全部 恒久毀損だったら)": round(
                (len([v for v in sur + ext if v <= -0.15]) + len(cen)) /
                max(1, len(sur) + len(ext) + len(cen)), 4),
        }
    # 旧の版の要点を残す（2回回しても最初の版＝v1 の値を上書きしない）
    base_prev = prev.get("prev") or ({"exit_rule": prev.get("exit_rule", "v1"),
                                      "generated": prev.get("generated"),
                                      "left_tail": prev.get("left_tail")} if prev else None)
    if base_prev:
        res["prev"] = base_prev
    res["rows"] = rows_out
    json.dump(res, open(outp, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res["left_tail"], ensure_ascii=False, indent=1))
    print("->", outp)


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
