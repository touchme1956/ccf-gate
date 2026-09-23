# night/retro_per_asof.py — 歴史検証・案C 追補「asof時点のPER」(2026-08-04新設)
#
# 目的: 門の二門構造（質は門Ω・買値は門X）の歴史検証。機械screen通過群を
#   「asof時点の倍率」で二分し、実現リターンが分かれるかを見る。
#
# look-ahead の防ぎ方:
#   EPSは「FY末が asof年3月1日 以前」の最後の会計年度だけ使う（12月決算社は前年FY）。
#   FY末から asof年7月の株価まで最大16ヶ月あるが、その間に公表済みなのは確実。
#
# 分割の補正（2026-08-04是正・初版はKLAC事故の型を自分で踏んだ）:
#   Yahooの close は「今日までの分割」で調整済み＝当時の板の値ではない。初版はこれを
#   当時の申告株数で割ったため、**後に分割した社（＝勝者に多い）ほどPERが安く出る**
#   汚染が起きた（実測: AAPL 2.32 / ISRG 3.49 / BKNG 3.27——実際は 9.3 / 29 / 30）。
#   帯検問(2-200)はこの「もっともらしい誤値」を素通りさせた。
#   → 是正: (1) Yahooの splits イベントから asof→今日の累積分割倍率を掛けて当時の
#   板の値へ復元 (2) 株数・純利益は **filedが最も古い値**（as-reported）を採る
#   ——後年の10-Kの比較年度は分割で遡及修正されるため、filed最新を採ると
#   「どこまで比較年度が続いたか」次第で倍率が中途半端に混ざる（実測: AAPLは
#   FY2014 10-Kの7:1修正だけ拾い2020年の4:1は拾わない＝28倍中7倍だけ補正の中途半端）。
#
# 実行: python3 night/retro_per_asof.py --asof 2013 --sample .../retro_sample.json
# 出力: out/retro_per_{asof}.json
import json, os, sys, time, datetime, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_guard as PXG   # noqa: E402  株価履歴の検問（2026-09-23）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASOF = 2013
SAMPLE = None
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])
    if a == "--sample" and i + 1 < len(sys.argv):
        SAMPLE = sys.argv[i + 1]
ALL = "--all" in sys.argv  # サンプルでなくコホートのticker有り全社を対象にする
OUT = os.path.join(BASE, "out", f"retro_per_{ASOF}{'_all' if ALL else ''}.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
CUTOFF = f"{ASOF}-03-01"  # これ以前にFYが締まっていること（公表済み保証）

NI_TAGS = ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss",
           "NetIncomeLossAvailableToCommonStockholdersBasic"]
SH_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding",
           "WeightedAverageNumberOfSharesOutstandingBasic"]


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def annual_entries(facts, tags, unit_names):
    """年次(330-400日)のフロー値を (end, val) で列挙。filed最新を採る。"""
    out = {}
    for taxo in ("us-gaap", "ifrs-full"):
        ns = facts.get(taxo) or {}
        for tag in tags:
            node = ns.get(tag)
            if not node:
                continue
            for unit, ents in node.get("units", {}).items():
                if unit not in unit_names:
                    continue
                for e in ents:
                    en, st, fl = e.get("end"), e.get("start"), e.get("filed", "")
                    if not en or not st:
                        continue
                    try:
                        if not (330 <= (d2(en) - d2(st)).days <= 400):
                            continue
                    except Exception:
                        continue
                    k = (tag, en)
                    # filedが最も古い値＝as-reported（後年の分割遡及修正を拾わない）
                    if k not in out or fl < out[k][1]:
                        out[k] = (float(e["val"]), fl)
            if any(t == tag for (t, _) in out):
                break  # タグは代替。最初に見つかった系列で足りる（PERの分母用）
    return out


def latest_before(entries, cutoff):
    best = None
    for (tag, en), (v, _) in entries.items():
        if en <= cutoff and (best is None or en > best[0]):
            best = (en, v)
    return best


def fetch_raw_close(sym, y):
    """asof年7月頭の**当時の板の値**を返す。Yahooのcloseは今日までの分割で調整済み
    なので、asof以降のsplitsイベントの累積倍率を掛けて復元する。"""
    t0 = int(datetime.datetime(y, 7, 1).timestamp())
    t1 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={t0}&period2={t1}&interval=1mo&events=splits")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                return None
            closes = ((res.get("indicators", {}).get("quote") or [{}])[0].get("close")) or []
            ts = res.get("timestamp") or []
            first_i = next((i for i, c in enumerate(closes) if c is not None), None)
            if first_i is None:
                return None
            first = closes[first_i]
            # ★px_guard（2026-09-23・todo yahoo_history_vanished）: 旧版は「最初の足」を**日付を見ずに**
            #   asof年7月の値として使っていた。Yahoo が過去の足を消した記号（EQR/QVCAQ/SALM…）では
            #   2026-07 の株価を 2013-07 の株価として PER を作る＝もっともらしい誤値になる。
            #   最初の足が要求の始まりから40日を超えて遅ければ採らない（台帳にも照らす）
            if first_i >= len(ts) or (ts[first_i] - t0) > PXG.TOL_DAYS * 86400:
                PXG.log_refusal(sym, "retro_per_asof.fetch_raw_close",
                                f"最初の足が asof {y}-07 より遅い"
                                f"（{datetime.date.fromtimestamp(ts[first_i]).isoformat() if first_i < len(ts) else '?'}）",
                                None, None, kept="none(測れない)")
                return None
            PXG.vet(sym, [ts[first_i]], "retro_per_asof.fetch_raw_close", req_start=t0, record=False)
            factor = 1.0
            for sp in (res.get("events", {}).get("splits") or {}).values():
                num, den = float(sp.get("numerator", 1)), float(sp.get("denominator", 1))
                if num > 0 and den > 0:
                    factor *= num / den
            return first * factor  # 逆分割(den>num)はfactor<1で正しく縮む
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def main():
    # ticker→CIK は cohort ファイルから引く（SECの現行表と同じ出所）。
    # 中間時点(2018等)のPERを採るときは cohort が無いので 2013 のCIK対応表へフォールバック
    cf = os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")
    if not os.path.exists(cf):
        cf = os.path.join(BASE, "out", "retro_cohort_2013.json")
    cohort = json.load(open(cf))
    t2cik = {r["ticker"]: r["cik"] for r in cohort["rows"] if r.get("ticker")}
    if ALL:
        tickers = sorted(t2cik)
    else:
        samp = json.load(open(SAMPLE))
        tickers = sorted(set(samp["pass"] + samp["ctrl"]))
    z = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip"))
    rows, miss = [], []
    for i, t in enumerate(tickers, 1):
        cik = t2cik.get(t)
        if not cik:
            miss.append({"ticker": t, "why": "no_cik"})
            continue
        try:
            facts = json.loads(z.read(f"CIK{cik:010d}.json")).get("facts", {})
        except Exception:
            miss.append({"ticker": t, "why": "no_facts"})
            continue
        ni = latest_before(annual_entries(facts, NI_TAGS, ("USD",)), CUTOFF)
        sh = latest_before(annual_entries(facts, SH_TAGS, ("shares",)), CUTOFF)
        px = fetch_raw_close(t, ASOF)
        time.sleep(0.5)
        if not ni or not sh or px is None or ni[1] <= 0 or sh[1] <= 0:
            miss.append({"ticker": t, "why": "eps_or_px",
                         "ni": ni and ni[0], "sh": sh and sh[0], "px": px})
            continue
        eps = ni[1] / sh[1]
        per = px / eps
        if not (2 <= per <= 200):  # 桁事故の帯検問（分割・単位混線）
            miss.append({"ticker": t, "why": f"per_band {per:.1f}"})
            continue
        rows.append({"ticker": t, "px": round(px, 2), "eps_fy": round(eps, 3),
                     "fy_end": ni[0], "per": round(per, 2)})
        if i % 20 == 0:
            print(f"  {i}/{len(tickers)}  per算出:{len(rows)}")
    # ★px_guard（2026-09-23）: 出力を丸ごと書き直す前に、**前の出力で算出できていた銘柄を今回の
    #   「株価が取れない（eps_or_px で px=None）」で消さない**。前の行を残してログに名指しする
    kept_old = []
    if os.path.exists(OUT):
        try:
            prev = {r["ticker"]: r for r in json.load(open(OUT)).get("rows", [])}
        except Exception:
            prev = {}
        have = {r["ticker"] for r in rows}
        for t, pr in prev.items():
            m = next((u for u in miss if u.get("ticker") == t), None)
            if t in have or m is None or not (m.get("why") == "eps_or_px" and m.get("px") is None):
                continue
            PXG.log_refusal(t, "retro_per_asof", "今回は株価が取れない（Yahoo の過去の足が無い）",
                            None, None, kept="old")
            rows.append(dict(pr, px_guard_kept_from=os.path.relpath(OUT, BASE)))
            miss = [u for u in miss if u is not m]
            kept_old.append(t)
    result = {"generated": datetime.date.today().isoformat(), "asof": ASOF,
              "cutoff_fy_end": CUTOFF, "rows": rows, "unmeasured": miss,
              "px_guard_kept_old": kept_old}
    json.dump(result, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"■ 書き出し: {OUT}  算出 {len(rows)} / 不能 {len(miss)}")


if __name__ == "__main__":
    main()
