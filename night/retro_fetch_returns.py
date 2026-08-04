# night/retro_fetch_returns.py — 歴史検証・案C リターン採取(2026-08-04新設)
#
# サンプル銘柄（retro_cohort の通過群/対照群）の実現トータルリターンを採る。
# データ源は Yahoo Finance chart API の adjclose 一本に統一する:
#   - 配当再投資込み（実測検証: MSFT 2013-07-01 生値34.36 vs adjclose27.97）
#   - FMP無料枠はデモ銘柄以外の履歴を拒否（実測: AFL/AZO等でACCESS DENIED）
#   - **ソースを混ぜない**——FMPとYahooは配当調整の作法が微妙に違い
#     （実測 MSFT 2012-13の調整比 0.789 vs 0.814）、混ぜると
#     「基準の違う二つを割る」型（KLACの分割・ADRのper）の事故になる
#   - 価格のみのリターンは配当分だけ構造的に低く出る（audit_er_realized の教訓）
#     ので adjclose 必須
#
# 1銘柄1リクエスト（interval=1mo・13年分）で両端点と途中経過を同時に取る。
# 退場銘柄（Yahooに無い/系列が途中で終わる）は**測れない**——黙って捨てず
# unmeasured として数える。退場率そのものは cohort の last_year が正。
#
# 実行: python3 night/retro_fetch_returns.py --asof 2013 \
#           --sample /path/to/retro_sample.json
# 出力: out/retro_returns_{asof}.json
import json, os, sys, time, datetime, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASOF = 2013
SAMPLE = None
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])
    if a == "--sample" and i + 1 < len(sys.argv):
        SAMPLE = sys.argv[i + 1]

ALL = "--all" in sys.argv  # サンプルでなくコホートのticker有り全社を対象にする
OUT = os.path.join(BASE, "out", f"retro_returns_{ASOF}{'_all' if ALL else ''}.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
T0 = int(datetime.datetime(ASOF, 7, 1).timestamp())
T1 = int(time.time())


def fetch(sym):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={T0}&period2={T1}&interval=1mo")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                return None
            ts = res.get("timestamp") or []
            adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
            pts = [(t, v) for t, v in zip(ts, adj) if v is not None]
            return pts or None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def analyze(pts):
    t_start, p_start = pts[0]
    t_end, p_end = pts[-1]
    years = (t_end - t_start) / (365.25 * 86400)
    if years < 1 or p_start <= 0:
        return None
    # 系列が現在から180日以上手前で終わる＝上場廃止の疑い。CAGRにせず印だけ
    stale = (T1 - t_end) > 180 * 86400
    peak, mdd = 0.0, 0.0
    for _, p in pts:
        peak = max(peak, p)
        mdd = min(mdd, p / peak - 1)
    out = {"start": datetime.date.fromtimestamp(t_start).isoformat(),
           "end": datetime.date.fromtimestamp(t_end).isoformat(),
           "years": round(years, 2), "mdd": round(mdd, 3), "stale": stale,
           "tr_total": round(p_end / p_start, 3)}
    out["tr_cagr"] = None if stale else round((p_end / p_start) ** (1 / years) - 1, 4)
    return out


def main():
    if ALL:
        cohort = json.load(open(os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")))
        tickers = [("all", r["ticker"]) for r in cohort["rows"] if r.get("has_ticker")]
        samp = {"pass": [], "ctrl": []}
    else:
        samp = json.load(open(SAMPLE)) if SAMPLE else None
        if not samp:
            sys.exit("--sample が要る（retro_sample.json: {'pass':[...], 'ctrl':[...]}）")
        tickers = [("pass", t) for t in samp["pass"]] + [("ctrl", t) for t in samp["ctrl"]]
    rows, unmeasured = [], []
    for i, (grp, t) in enumerate(tickers, 1):
        pts = fetch(t)
        time.sleep(0.6)
        if not pts:
            unmeasured.append({"ticker": t, "group": grp})
            continue
        a = analyze(pts)
        if a is None:
            unmeasured.append({"ticker": t, "group": grp})
            continue
        rows.append({"ticker": t, "group": grp, **a})
        if i % 20 == 0:
            print(f"  {i}/{len(tickers)}  実測:{len(rows)} 未測:{len(unmeasured)}")
    spy = analyze(fetch("SPY"))
    result = {"generated": datetime.date.today().isoformat(), "asof": ASOF,
              "asof_date": f"{ASOF}-07-01", "now_date": datetime.date.today().isoformat(),
              "source": "Yahoo Finance chart API adjclose (dividend-adjusted, monthly)",
              "sampled_tickers": samp["pass"] + samp["ctrl"],
              "benchmark": {"symbol": "SPY", **(spy or {})},
              "rows": rows, "unmeasured": unmeasured}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"■ 書き出し: {OUT}  実測 {len(rows)} / 未測 {len(unmeasured)}"
          f"  SPY {spy and spy.get('tr_cagr')}")


if __name__ == "__main__":
    main()
