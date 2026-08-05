# night/retro_fulltext.py — 歴史検証・堀の定型言語のEDGAR全文検索採取（2026-08-05新設）
#
# 目的: 2018-07-01「途中乗り」時点より前に提出された 10-K 本文に、堀に関わる
#       定型言語（事前登録の8フレーズ）が有るか無いかだけを採る。
#       方向の解釈（良い/悪い）は後段の分析に任せ、ここでは有無のみ記録する。
#
# look-ahead 防止: efts の提出日窓 startdt=2016-07-01 / enddt=2018-06-30 で切る。
#       enddt が乗車日(2018-07-01)より前なので、年ラベルではなく提出日で
#       未来の紙を構造的に排除している（12月決算社のFY2018=2019年2月提出は入らない）。
#
# API: https://efts.sec.gov/LATEST/search-index?q=%22PHRASE%22&forms=10-K
#        &startdt=2016-07-01&enddt=2018-06-30&ciks=<10桁ゼロ埋めCIK>
#      hits.total.value >= 1 なら該当。forms=10-K のみ（10-K/A 等は含まない）。
#
# 事前登録フレーズ（8つで固定）:
#   ft_frag: "highly fragmented"        ft_swc:  "switching costs"
#   ft_ltc:  "long-term contracts"      ft_rec:  "recurring revenue"
#   ft_net:  "network effect"           ft_cust: "customer accounted for"
#   ft_comp: "intense competition"      ft_qual: "qualified by our customers"
#
# 【実装上の逸脱1件・実測根拠つき】 ft_net は指示文の意図が
# 「"network effects"も拾えるよう q は "network effect" とする」だったが、
# efts はステミングしない完全フレーズ一致であることを事前実測で確認した
# （Coupa 0001385867・窓内10-K: "network effects"=2ヒット / "network effect"=0ヒット）。
# 単数形だけでは複数形を拾えず意図に反するため、ft_net のみ
# 単数形と複数形の2クエリのORで判定する。他の7フレーズは登録どおり1クエリ
# （したがって例えば "recurring revenues"（複数形）は ft_rec に拾われない——
#  事前登録を後から広げないため。この非対称は note に明記する）。
#
# 欠測の扱い（欠測を0と読まない・ルール7）:
#   - 窓内に 10-K が1件も無い社（no-q 検索で0ヒット）→ 全欄欠測 + "no10k": true
#   - クエリ失敗（2秒待って1回再試行しても失敗）→ その欄は出力に含めない（欠測）。
#     失敗した欄は "fail": [...] に名指しで残す（黙って False にしない）
#   - OR判定(ft_net)は「片方がヒット確定なら他方が失敗でも True」
#     「片方0で他方失敗なら False と断定できない→欠測」
#
# レート: グローバルなペーサーで全リクエスト開始の間隔を0.22秒以上に強制
# （＝毎秒4.5クエリ以下。仕様の「毎秒5クエリ以下」を並列でも構造的に超えられない）。
# 並列は4ワーカー（1社の中は逐次）——実測で1クエリの往復が約0.7秒とレート上限より
# 遅延が支配的だったため、逐次sleep(0.2)では毎秒1.4クエリしか出ず全体が2時間半かかる。
# 途中経過: 50社ごとに print。約25社ごとに .partial.json へチェックポイント
# （中断しても再実行で続きから走る。完走時に partial は削除）。
#
# 実行: python3 night/retro_fulltext.py
# 出力: out/retro_fulltext_2018.json
#   {"generated": 日付, "note": 設計メモ, "rows": [{"ticker","cik",...}]}

import json
import os
import time
import datetime
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETURNS = os.path.join(BASE, "out", "retro_returns_2018.json")
COHORT = os.path.join(BASE, "out", "retro_cohort_2013.json")
OUT = os.path.join(BASE, "out", "retro_fulltext_2018.json")
CKPT = os.path.join(BASE, "out", "retro_fulltext_2018.partial.json")

API = "https://efts.sec.gov/LATEST/search-index"
UA = {"User-Agent": "CCF-Omega-Screener fortis5280@gmail.com"}
STARTDT, ENDDT = "2016-07-01", "2018-06-30"

# (欄名, [qフレーズ, ...]) — 複数あればOR判定（ft_netのみ・頭注の実測根拠を見よ）
PHRASES = [
    ("ft_frag", ['"highly fragmented"']),
    ("ft_swc", ['"switching costs"']),
    ("ft_ltc", ['"long-term contracts"']),
    ("ft_rec", ['"recurring revenue"']),
    ("ft_net", ['"network effect"', '"network effects"']),
    ("ft_cust", ['"customer accounted for"']),
    ("ft_comp", ['"intense competition"']),
    ("ft_qual", ['"qualified by our customers"']),
]


# グローバルペーサー: 全スレッド共通で「リクエスト開始」の間隔を 0.22秒以上にする。
# ロックを持ったまま眠るのは意図的——次のスレッドはロック待ちで自然に列に並ぶので、
# 並列度に関係なく毎秒 1/0.22 ≒ 4.5 クエリを構造的に超えられない。
_rl_lock = threading.Lock()
_rl_last = [0.0]
MIN_INTERVAL = 0.22


def _pace():
    with _rl_lock:
        now = time.monotonic()
        wait = _rl_last[0] + MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _rl_last[0] = now


def query_total(params):
    """efts に1クエリ投げて hits.total.value を返す。失敗は None（欠測）。
    仕様: エラー時は2秒待って1回だけ再試行（429/403だけ10秒——ブロックの兆候に
    2秒は短すぎ、失敗の連鎖で残り全社が欠測になるのを防ぐ保険）。"""
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    url = f"{API}?{qs}"
    for attempt in (0, 1):
        _pace()  # 毎秒5クエリ以下（再試行側にも掛ける）
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read())
            return int(j["hits"]["total"]["value"])
        except Exception as e:
            if attempt == 0:
                code = getattr(e, "code", None)
                time.sleep(10 if code in (429, 403) else 2)
            else:
                return None
    return None


def main():
    ret = json.load(open(RETURNS))
    tickers = [r["ticker"] for r in ret["rows"]]  # 順序保存・実測956・unique確認済み
    coh = json.load(open(COHORT))
    cikmap = {r["ticker"]: r.get("cik") for r in coh["rows"] if r.get("ticker")}

    done = {}
    if os.path.exists(CKPT):
        try:
            prev = json.load(open(CKPT))
            done = {r["ticker"]: r for r in prev.get("rows", [])}
            print(f"checkpoint 読込: {len(done)}社は採取済み・スキップ")
        except Exception:
            done = {}

    def collect(t):
        """1社ぶんの採取（社内は逐次・レートはグローバルペーサーが守る）"""
        cik = cikmap.get(t)
        row = {"ticker": t, "cik": cik}
        fails = []
        if not cik:
            # 対応表に無い（実測0社のはずだが、欠測は欠測として明示）
            row["no_cik"] = True
        else:
            cik10 = f"{int(cik):010d}"
            base_params = {"forms": "10-K", "startdt": STARTDT,
                           "enddt": ENDDT, "ciks": cik10}
            # 窓内に10-Kがあるか（q無し検索・疎通実測: AAPL=2, FB=2）
            n10k = query_total(base_params)
            if n10k is None:
                fails.append("no10k_check")  # 有無すら判定不能→全欄欠測
            elif n10k == 0:
                row["no10k"] = True
            else:
                row["n10k"] = n10k
                for key, qlist in PHRASES:
                    totals = [query_total(dict(base_params, q=q)) for q in qlist]
                    if any(v is not None and v >= 1 for v in totals):
                        row[key] = True  # ヒット確定はOR相手の失敗に関係なくTrue
                    elif any(v is None for v in totals):
                        fails.append(key)  # False と断定できない→欠測
                    else:
                        row[key] = False
        if fails:
            row["fail"] = fails
        return row

    todo = [t for t in tickers if t not in done]
    t0 = time.time()
    n_done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(collect, t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]
            done[t] = fut.result()
            n_done += 1
            if n_done % 50 == 0:
                el = time.time() - t0
                print(f"{n_done}/{len(todo)} 社 ({el:.0f}s, {el/n_done:.2f}s/社)",
                      flush=True)
            if n_done % 25 == 0:
                json.dump({"rows": list(done.values())}, open(CKPT, "w"))

    rows = [done[t] for t in tickers]  # 元の順序で出力

    # 集計（notesへ転記する数字）
    tally = {}
    for key, _ in PHRASES:
        tally[key] = sum(1 for r in rows if r.get(key) is True)
    n_no10k = sum(1 for r in rows if r.get("no10k"))
    n_fail = sum(1 for r in rows if r.get("fail"))

    note = (
        "EDGAR全文検索(efts.sec.gov/LATEST/search-index)で、乗車(2018-07-01)前に提出された"
        f"10-K本文の堀の定型言語の有無を採取。提出日窓 {STARTDT}〜{ENDDT}・forms=10-Kのみ"
        "（10-K/A含まず）＝filed基準でlook-ahead無し。hits.total.value>=1で該当。"
        "事前登録8フレーズ: ft_frag='highly fragmented' / ft_swc='switching costs' / "
        "ft_ltc='long-term contracts' / ft_rec='recurring revenue' / "
        "ft_net='network effect' OR 'network effects' / ft_cust='customer accounted for' / "
        "ft_comp='intense competition' / ft_qual='qualified by our customers'。"
        "【逸脱1件・実測根拠】eftsはステミング無しの完全フレーズ一致（実測: Coupa 0001385867の"
        "窓内10-Kで 'network effects'=2ヒット/'network effect'=0ヒット）のため、"
        "指示の意図（複数形も拾う）どおりft_netのみ単複2クエリのOR。他7フレーズは登録どおり"
        "1クエリ＝複数形は拾わない（例: 'recurring revenues'はft_recに入らない）。"
        "窓内に10-Kが無い社は全欄欠測+no10k:true。クエリ失敗（2秒待ち1回再試行後）は"
        "その欄を欠測としfail:[]に名指し（欠測を0/Falseと読まない）。"
        "有無のみの記録であり方向（堀の強弱）の解釈は後段の分析に委ねる。"
        "レート: グローバルペーサーで全リクエスト開始の間隔0.22秒以上（毎秒4.5クエリ以下＝"
        "仕様の毎秒5以下を並列4ワーカーでも構造的に遵守）。"
    )
    out = {
        "generated": datetime.date.today().isoformat(),
        "note": note,
        "window": {"startdt": STARTDT, "enddt": ENDDT, "forms": "10-K"},
        "tally": dict(tally, no10k=n_no10k, fail_rows=n_fail, n=len(rows)),
        "rows": rows,
    }
    json.dump(out, open(OUT, "w"), indent=1)
    if os.path.exists(CKPT):
        os.remove(CKPT)
    print(f"完了: {len(rows)}社 → {OUT}")
    print("該当社数:", json.dumps(tally))
    print(f"no10k={n_no10k} fail_rows={n_fail}")


if __name__ == "__main__":
    main()
