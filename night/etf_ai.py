# night/etf_ai.py — 「AIの恩恵を受けるETF」を実測で比べる（2026-08-19新設）
#
# 【この道具が答えられること / 答えられないこと】
#   答えられない: **どのETFが今後AIの恩恵を受けるか**。これは予測であって測定ではない。
#     門の思想は「予知せず」で、この台帳は13年かけて
#     「過去のリターンは将来のリターンを当てない（他の3窓の実現リターンそのもので選んでも ×0.84〜1.12）」
#     を実測している。この道具はその結論を覆さない。
#   答えられる:
#     (1) テーマ型AI ETF は**同じ窓で** 半導体/広いテックに勝ってきたか
#     (2) 経費率——**唯一 確実に複利へ効く数字**（リターンは推定・費用は確定値）
#     (3) 前回の技術の波（インターネット）で「明らかな受益者」に集中したら何が返ったか
#
# 実行: python3 night/etf_ai.py [--json]
# 出力: out/etf_ai.json
import json, os, sys, time, datetime, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "etf_ai.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

CANDS = {
    "テーマ型AI/ロボ": ["BOTZ", "ROBO", "IRBO", "AIQ", "THNQ", "ARTY", "WTAI", "CHAT", "LOUP", "UBOT"],
    "半導体":         ["SMH", "SOXX", "SMHX", "PSI", "XSD"],
    "ソフト/クラウド":  ["IGV", "SKYY", "WCLD", "CLOU", "XSW"],
    "AIの電力・設備":   ["GRID", "PAVE", "XLU", "VPU", "URA"],
    "広いテック":      ["XLK", "VGT", "QQQ", "FTEC"],
    "土台":           ["SPY", "VTI", "VT"],
}
ALL = [t for g in CANDS.values() for t in g]


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
            ts = res.get("timestamp") or []
            adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
            o = {}
            for t, v in zip(ts, adj):
                if v is None:
                    continue
                d = datetime.datetime.utcfromtimestamp(t)
                o[f"{d.year:04d}-{d.month:02d}"] = float(v)
            return o or None
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (a + 1))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def stats(ser, a, b):
    ks = sorted(k for k in ser if a <= k <= b)
    if len(ks) < 12:
        return None
    yrs = ((int(ks[-1][:4]) - int(ks[0][:4])) * 12 + (int(ks[-1][5:]) - int(ks[0][5:]))) / 12.0
    if yrs <= 0.5:
        return None
    peak, dd = None, 0.0
    for k in ks:
        v = ser[k]
        peak = v if peak is None else max(peak, v)
        dd = min(dd, v / peak - 1)
    return {"cagr": round((ser[ks[-1]] / ser[ks[0]]) ** (1 / yrs) - 1, 4),
            "maxdd": round(dd, 4), "years": round(yrs, 2)}


def main():
    series, miss = {}, []
    for t in ALL:
        s = fetch(t)
        if s:
            series[t] = s
        else:
            miss.append(t)
        time.sleep(0.35)
    grp = {t: g for g, ts in CANDS.items() for t in ts}

    # ★テーマ型AI ETF は「テーマが明らかになってから」設定される。
    #   だから比較は必ず**そのETFの設定日から**、同じ窓で行う。
    themes = [t for t in CANDS["テーマ型AI/ロボ"] if t in series]
    bench = [t for t in ("SMH", "SOXX", "XLK", "VGT", "QQQ", "SPY") if t in series]
    headtohead = []
    for t in sorted(themes, key=lambda x: min(series[x])):
        a, b = min(series[t]), max(series[t])
        row = {"t": t, "設定": a, "窓": f"{a}→{b}",
               "自身": stats(series[t], a, b), "比較": {}}
        for m in bench:
            if min(series[m]) <= a:
                row["比較"][m] = stats(series[m], a, b)
        s0 = row["自身"]
        if s0:
            row["対SMH_pt"] = (round((s0["cagr"] - row["比較"]["SMH"]["cagr"]) * 100, 1)
                               if row["比較"].get("SMH") else None)
            row["対SPY_pt"] = (round((s0["cagr"] - row["比較"]["SPY"]["cagr"]) * 100, 1)
                               if row["比較"].get("SPY") else None)
        headtohead.append(row)

    # ★共通窓（テーマ型のうち最も古い設定日で全員を揃える）
    common = None
    if themes:
        a = max(min(series[t]) for t in themes)  # 全テーマ型が存在する最古の月
        # ⚠ 終端は max で取る。min にすると**償還されたETF1本が全員の窓を切る**
        #    （実測: IRBO は 2025-05 で系列が終わる＝償還。これで全31本が2年窓に切られていた）
        b = max(max(series[t]) for t in series)
        recs = []
        for t, s in series.items():
            if min(s) > a:
                continue
            st = stats(s, a, b)
            if st:
                recs.append({"t": t, "group": grp[t], "last": max(s),
                             "closed": max(s) < b, **st})
        recs.sort(key=lambda x: -x["cagr"])
        common = {"start": a, "end": b, "n": len(recs), "rows": recs}

    # ★前回の技術の波——インターネットは本物だったが、明らかな受益者に集中したら
    prev = {}
    for t in ("SMH", "XLK", "QQQ", "IGV", "SPY"):
        if t in series and min(series[t]) <= "2000-08":
            prev[t] = {"2000-2010": stats(series[t], "2000-08", "2010-08"),
                       "2000-2026": stats(series[t], "2000-08", max(series[t]))}

    all_rows = []
    for t, s in series.items():
        ks = sorted(s)
        all_rows.append({"t": t, "group": grp[t], "first": ks[0], "last": ks[-1],
                         "n_months": len(ks), "full": stats(s, ks[0], ks[-1])})
    all_rows.sort(key=lambda x: (x["group"], -(x["full"]["cagr"] if x["full"] else -9)))

    out = {"generated": datetime.date.today().isoformat(), "tool": "night/etf_ai.py",
           "role": "『AIの恩恵を受けるETF』の材料。**判定はしない**——ETF選定は門の外(DCA側)。"
                   "そして『今後どれが恩恵を受けるか』は予測であってこの道具は答えられない",
           "source": "Yahoo Finance chart API の adjclose（分配金再投資込み・月次）",
           "n_fetched": len(series), "missing": miss,
           "★テーマ型AIを設定日から同じ窓で比べる": headtohead,
           "★共通窓": common,
           "★前回の技術の波(インターネット)": prev,
           "★読み方": [
               "テーマ型ETFは**テーマが明らかになってから設定される**ので、"
               "設定前の期間は存在しない。だから『設定日から同じ窓で』しか比べられない",
               "★経費率はこの道具では採っていない（Yahooの価格系列のみ）。"
               "**費用は唯一 確実に複利へ効く数字**なので、選ぶ前に必ず目論見書で確認すること",
               "★『AIの恩恵』は将来の話で、この道具は測れない。測れるのは『同じ窓で勝ってきたか』だけ",
               "★★生存バイアス——テーマ型ETFは資金が集まらないと**償還される**。"
               "実測: IRBO(iShares Robotics & AI・2018-06設定)は2025-05で系列が終わっている。"
               "今日ティッカーが引けるテーマ型だけを見ると、消えた分が母集団から落ちる",
           ],
           "rows": all_rows}
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    print(f"■ AI関連ETF — {len(series)}本 / 取得できず {len(miss)}本 {miss or ''}\n")
    print("  ★テーマ型AI ETF を『設定日から・同じ窓で』比べる（年率・分配金込み）")
    print(f"    {'':6s} {'設定':9s}{'年':>5s}{'自身':>8s}{'SMH':>8s}{'XLK':>8s}{'QQQ':>8s}{'SPY':>8s}   対SMH   対SPY")
    for r in headtohead:
        if not r["自身"]:
            continue
        c = r["比較"]
        f = lambda k: (f"{c[k]['cagr']*100:>7.1f}%" if c.get(k) else f"{'—':>8s}")
        print(f"    {r['t']:6s} {r['設定']:9s}{r['自身']['years']:>5.1f}"
              f"{r['自身']['cagr']*100:>7.1f}%{f('SMH')}{f('XLK')}{f('QQQ')}{f('SPY')}"
              f"  {r['対SMH_pt']:>+6.1f}  {r['対SPY_pt']:>+6.1f}")
    if common:
        print(f"\n  ★共通窓 {common['start']}→{common['end']}（全テーマ型が存在する最古の月で揃えた・{common['n']}本）")
        print("    ⚠ 終端は各ETF自身の最終月。★印は途中で系列が終わった＝償還")
        for r in common["rows"]:
            print(f"    {r['t']:6s} {r['group']:14s} 年率{r['cagr']*100:>6.1f}%  "
                  f"最大下落{r['maxdd']*100:>5.0f}%  {r['years']:.1f}年"
                  f"{'  ★償還 '+r['last'] if r['closed'] else ''}")
    if prev:
        print("\n  ★前回の技術の波——インターネットは本物だった。明らかな受益者に集中したら:")
        for t, v in prev.items():
            a = v["2000-2010"]
            b = v["2000-2026"]
            print(f"    {t:6s} 2000-2010 {a['cagr']*100:>7.1f}%/年 (最大下落{a['maxdd']*100:.0f}%)"
                  f"   2000-2026 {b['cagr']*100:>6.1f}%/年")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
