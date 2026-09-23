# night/etf_theme.py — テーマ型ETF（宇宙・未来産業）を設定日から同じ窓で裁く（2026-08-19新設）
#
# 【この道具が答えられること / 答えられないこと】
#   答えられない: **今後どの産業が伸びるか**。予測であって測定ではない。門の思想は「予知せず」。
#   答えられる: **テーマ型ETFという商品が、同じ窓でベンチに勝ってきたか**。
#     ★テーマ型は「テーマが明らかになってから」設定されるので、比較は必ず**そのETFの設定日から**行う。
#     全期間の年率を並べるのは「基準の違う二つを割る」型（etf_returns.py で実証済み）。
#
# 【先行する実測】etf_ai.py で **テーマ型AI ETF 10本が10本とも SMH に負けた**（−8.4〜−39.8pt）。
#   4本は SPY にも負け、1本（IRBO）は**償還された**。この道具はその検定を宇宙・他テーマへ広げる。
#
# 【市場時差】月ラベルは gmtoffset でローカル月へ揃える（etf_jp.py で見つけた13例目の型）。
#
# 実行: python3 night/etf_theme.py [--json]
# 出力: out/etf_theme.json
import json, os, sys, time, datetime, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_guard as PXG   # noqa: E402  株価履歴の検問（短い応答を採らない・2026-09-23）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "etf_theme.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

THEMES = {
    "宇宙": ["UFO", "ARKX", "ROKT"],
    "防衛・航空": ["ITA", "PPA", "XAR", "SHLD"],
    "ゲノム・バイオ": ["ARKG", "IDNA", "GNOM", "XBI", "IBB"],
    "クリーンエネ": ["ICLN", "TAN", "QCLN", "PBW", "FAN"],
    "原子力・ウラン": ["URA", "URNM", "NLR"],
    "EV・電池": ["LIT", "DRIV", "IDRV", "BATT"],
    "サイバー": ["CIBR", "HACK", "BUG"],
    "フィンテック": ["FINX", "ARKF", "IPAY"],
    "ブロックチェーン": ["BLOK", "BKCH"],
    "水・インフラ": ["PHO", "FIW", "CGW", "PAVE", "IFRA"],
    "破壊的イノベ": ["ARKK", "ARKQ", "ARKW", "DTEC", "XT"],
    "ロボ・AI・量子": ["BOTZ", "ROBO", "AIQ", "QTUM"],
}
BENCH = ["SMH", "XLK", "QQQ", "SPY"]
ALL = [t for g in THEMES.values() for t in g] + BENCH


def fetch(sym):
    t0 = int(datetime.datetime(1993, 1, 1).timestamp())
    t1 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={t0}&period2={t1}&interval=1mo")
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                return None
            ind = res["indicators"]
            ser = (ind.get("adjclose") or [{}])[0].get("adjclose") or ind["quote"][0]["close"]
            gmt = (res.get("meta") or {}).get("gmtoffset") or 0   # ★市場時差で月を揃える
            o = {}
            for t, v in zip(res["timestamp"], ser):
                if v is None:
                    continue
                d = datetime.datetime.utcfromtimestamp(t + gmt)
                o[f"{d.year:04d}-{d.month:02d}"] = float(v)
            return PXG.vet(sym, o, "etf_theme.fetch", req_start=t0) or None  # ★px_guard: 台帳より遅く始まる応答は採らない（2026-09-23）
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (a + 1))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def st(ser, a, b):
    ks = sorted(k for k in ser if a <= k <= b)
    if len(ks) < 12:
        return None
    y = ((int(ks[-1][:4]) - int(ks[0][:4])) * 12 + (int(ks[-1][5:]) - int(ks[0][5:]))) / 12.0
    if y <= 0.9:
        return None
    peak, dd = None, 0.0
    for k in ks:
        v = ser[k]
        peak = v if peak is None else max(peak, v)
        dd = min(dd, v / peak - 1)
    return {"cagr": round((ser[ks[-1]] / ser[ks[0]]) ** (1 / y) - 1, 4),
            "maxdd": round(dd, 4), "years": round(y, 2)}


def main():
    ser, miss = {}, []
    for t in ALL:
        s = fetch(t)
        if s:
            ser[t] = s
        else:
            miss.append(t)
        time.sleep(0.3)
    grp = {t: g for g, ts in THEMES.items() for t in ts}
    END = max(max(v) for v in ser.values())

    rows, closed = [], []
    for t in [x for x in ALL if x not in BENCH and x in ser]:
        a, b = min(ser[t]), max(ser[t])
        me = st(ser[t], a, b)
        if not me:
            continue
        if b < END:                      # ★系列が途中で終わる＝償還（生存バイアスの実例）
            closed.append({"t": t, "last": b})
        r = {"t": t, "group": grp[t], "first": a, "last": b, **me, "vs": {}}
        for m in BENCH:
            if m in ser and min(ser[m]) <= a:
                q = st(ser[m], a, b)
                if q:
                    r["vs"][m] = {"cagr": q["cagr"], "maxdd": q["maxdd"],
                                  "diff_pt": round((me["cagr"] - q["cagr"]) * 100, 1)}
        rows.append(r)
    rows.sort(key=lambda x: -(x["vs"].get("SPY", {}).get("diff_pt", -999)))

    # ★★同じテーマなのに設定日が違う対を、**同じ窓で**揃え直す。
    #   実測: URA(2010-11設定・15.8年) −3.4%/年 vs URNM(2019-12設定・6.7年) +27.1%/年 ＝符号が逆。
    #   ところが窓を揃えると **+26.9% vs +27.1%＝差0.2pt**。
    #   ⇒ **符号の逆転はテーマの差ではなく完全に設定日の産物だった。**
    same = []
    for a, b in (("URA", "URNM"), ("ICLN", "QCLN"), ("ROBO", "QTUM"), ("UFO", "ARKX")):
        if a not in ser or b not in ser:
            continue
        st0 = max(min(ser[a]), min(ser[b]))
        en0 = max(ser[a])
        x, y = st(ser[a], st0, en0), st(ser[b], st0, en0)
        if not x or not y:
            continue
        same.append({"pair": [a, b], "window": f"{st0}→{en0}", "years": x["years"],
                     "raw_from_inception": [next((r["cagr"] for r in rows if r["t"] == a), None),
                                            next((r["cagr"] for r in rows if r["t"] == b), None)],
                     "same_window": [x["cagr"], y["cagr"]],
                     "diff_pt": round((x["cagr"] - y["cagr"]) * 100, 1),
                     "SMH": (st(ser["SMH"], st0, en0) or {}).get("cagr"),
                     "SPY": (st(ser["SPY"], st0, en0) or {}).get("cagr")})

    # ★宇宙3本を同じ窓で揃える（最も新しい設定日に合わせる）
    space = None
    sp3 = [t for t in THEMES["宇宙"] if t in ser]
    if len(sp3) >= 2:
        st0 = max(min(ser[t]) for t in sp3)
        en0 = min(max(ser[t]) for t in sp3)
        space = {"window": f"{st0}→{en0}", "rows": []}
        for t in sp3 + [b for b in BENCH if b in ser]:
            q = st(ser[t], st0, en0)
            if q:
                space["rows"].append({"t": t, **q})
        space["rows"].sort(key=lambda x: -x["cagr"])

    def tally(m):
        v = [r for r in rows if m in r["vs"]]
        w = [r for r in v if r["vs"][m]["diff_pt"] > 0]
        return {"n": len(v), "勝ち": len(w), "率": round(len(w) / len(v), 3) if v else None,
                "勝った本": [r["t"] for r in w]}
    out = {"generated": datetime.date.today().isoformat(), "tool": "night/etf_theme.py",
           "role": "テーマ型ETFの材料。**判定はしない**——ETF選定は門の外(DCA側)。"
                   "そして『今後どの産業が伸びるか』は予測でこの道具は答えられない",
           "source": "Yahoo Finance chart API の adjclose（分配金再投資込み・月次）",
           "method": "各テーマ型ETFの**設定日から今日まで**、同じ窓でベンチと比べる",
           "n": len(rows), "missing": miss,
           "★償還されたETF": closed,
           "★勝敗": {m: tally(m) for m in BENCH},
           "★同じテーマを同じ窓で揃え直す": same,
           "★宇宙3本を同じ窓で": space,
           "★読み方": [
               "★テーマ型は『テーマが明らかになってから』設定される。だから設定日から比べるしかない",
               "★生存バイアス——今日ティッカーが引けるものだけ。資金が集まらないテーマ型は償還される",
               "★経費率はこの道具では採れない。テーマ型は 0.4〜0.75% と高いことが多く、"
               "**コストは唯一 確実に複利へ効く数字**なので必ず目論見書で確認すること",
               "★窓の長さがばらばら（設定日が違うため）。ETF どうしを直接比べないこと",
           ],
           "rows": rows}
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"■ テーマ型ETF {len(rows)}本 — 設定日から同じ窓でベンチと比べる"
          f"{'（取得できず ' + ','.join(miss) + '）' if miss else ''}\n")
    print(f"  {'':6s}{'群':14s}{'設定':9s}{'年':>5s}{'自身':>8s}{'最大下落':>8s}"
          f"{'対SPY':>8s}{'対QQQ':>8s}{'対SMH':>8s}")
    for r in rows:
        f_ = lambda m: (f"{r['vs'][m]['diff_pt']:>+7.1f}" if m in r["vs"] else f"{'—':>8s}")
        print(f"  {r['t']:6s}{r['group']:14s}{r['first']:9s}{r['years']:>5.1f}"
              f"{r['cagr']*100:>7.1f}%{r['maxdd']*100:>7.0f}%{f_('SPY')}{f_('QQQ')}{f_('SMH')}")
    print("\n  ★勝敗（設定日から今日まで・同じ窓）")
    for m in BENCH:
        t_ = out["★勝敗"][m]
        print(f"    対 {m:5s} {t_['勝ち']:>2d}/{t_['n']:>2d}本 ({(t_['率'] or 0)*100:.0f}%)"
              f"   勝った本: {', '.join(t_['勝った本']) or 'なし'}")
    if same:
        print("\n  ★同じテーマなのに設定日が違う対を、同じ窓で揃え直す")
        for x in same:
            a, b = x["pair"]
            print(f"    {a}/{b}  設定日から: {x['raw_from_inception'][0]*100:+.1f}% / "
                  f"{x['raw_from_inception'][1]*100:+.1f}%  →  同じ窓({x['window']}・{x['years']}年): "
                  f"{x['same_window'][0]*100:+.1f}% / {x['same_window'][1]*100:+.1f}%  差{x['diff_pt']:+.1f}pt")
    if space:
        print(f"\n  ★宇宙3本を同じ窓で（{space['window']}）")
        for r in space["rows"]:
            print(f"    {r['t']:6s} {r['cagr']*100:>+6.1f}%/年  最大下落{r['maxdd']*100:>5.0f}%")
    if closed:
        print(f"\n  ★系列が途中で終わったETF（償還の疑い）: {[c['t'] + '(' + c['last'] + ')' for c in closed]}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
