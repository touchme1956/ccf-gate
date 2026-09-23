# night/etf_returns.py — 網(ETF)の歴史リターンを重ならない窓で測る（2026-08-19新設）
#
# 【何のための道具か】
#   網(ETF)の中身を決めるための材料を出す。**判定はしない**——ETFの選定は門の外
#   （DCA側の決断）で、門Ωの採点・四関門・売却規律にはいっさい触れない。
#
# 【なぜ「重ならない窓」なのか】
#   「過去10年のリターン」は**一つの窓**で、その窓は一つの相場でしかない。
#   この台帳は個別株について「他の3窓の実現リターンそのもので選んでも当てられない
#   （×0.84〜1.12）」を実測している（retro_persistence）。同じ検問を指数にも当てる:
#     (a) 重ならない5年窓を4つ取り、窓ごとに順位を出す
#     (b) 隣り合う窓の順位相関を測る＝**過去の順位が次の順位を当てるか**
#   当たらなければ「過去10年で一番だったETF」は選定の根拠にならない。
#
# 【データ源】Yahoo Finance chart API の adjclose 一本（分配金再投資込み）。
#   ソースを混ぜない（retro_fetch_returns.py と同じ理由＝配当調整の作法が違うと
#   「基準の違う二つを割る」型の事故になる）。
#
# 【欠測の扱い】設定前の期間は**測れない**。ゼロや代替指数で埋めない（絶対のルール7）。
#   窓に届かないETFは na として数え、順位からも外す。
#
# 実行: python3 night/etf_returns.py [--json]
# 出力: out/etf_returns.json
import json, os, sys, time, datetime, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_guard as PXG   # noqa: E402  株価履歴の検問（短い応答を採らない・2026-09-23）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "etf_returns.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# 候補（群ごと）。★今日の網は XLK/QQQ/SMH/FANG+
CANDS = {
    "広い土台":   ["VT", "VTI", "VOO", "SPY", "RSP", "ACWI"],
    "大型成長":   ["QQQ", "VUG", "MGK", "SCHG", "IWY"],
    "テック":     ["XLK", "VGT", "FTEC", "IYW"],
    "半導体":     ["SMH", "SOXX"],
    "ファクター": ["MTUM", "QUAL", "SPMO", "COWZ", "MOAT", "SPHQ"],
    "他セクター": ["XLY", "XLV", "XLF", "XLI"],
    "海外":       ["VXUS", "VEA", "VWO"],
}
ALL = [t for g in CANDS.values() for t in g]

# 重ならない5年窓（4つ＝20年）。終端は直近の月末。
# ★ドットコム崩壊(2000-02)とGFC(2008-09)を必ず含める——この2つが唯一の「相場が変わった」観測
WINDOWS = [("1996-08", "2001-08"), ("2001-08", "2006-08"),
           ("2006-08", "2011-08"), ("2011-08", "2016-08"),
           ("2016-08", "2021-08"), ("2021-08", "2026-08")]


def fetch(sym):
    t0 = int(datetime.datetime(1993, 1, 1).timestamp())
    t1 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={t0}&period2={t1}&interval=1mo")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                return None
            ts = res.get("timestamp") or []
            adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
            out = {}
            for t, v in zip(ts, adj):
                if v is None:
                    continue
                d = datetime.datetime.utcfromtimestamp(t)
                out[f"{d.year:04d}-{d.month:02d}"] = float(v)
            return PXG.vet(sym, out, "etf_returns.fetch", req_start=t0) or None  # ★px_guard: 台帳より遅く始まる応答は採らない（2026-09-23）
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def on_or_before(ser, ym):
    """その年月以前で最も新しい観測。無ければ None（＝測れない・埋めない）"""
    ks = sorted(k for k in ser if k <= ym)
    return (ks[-1], ser[ks[-1]]) if ks else None


def cagr(ser, a, b):
    """窓 [a,b] の年率。★起点が窓の開始より後なら None（設定前は測れない）"""
    ka = on_or_before(ser, a)
    kb = on_or_before(ser, b)
    if not ka or not kb or ka[0] == kb[0]:
        return None
    # 起点が窓の開始から3ヶ月以上遅れていたら「その窓には居なかった」
    ya, ma = int(a[:4]), int(a[5:])
    yk, mk = int(ka[0][:4]), int(ka[0][5:])
    if (yk - ya) * 12 + (mk - ma) < -0 and False:
        pass
    if ka[0] < a:
        # 起点が窓開始より前＝正常（直前の月末を使う）
        pass
    elif (yk - ya) * 12 + (mk - ma) > 3:
        return None
    yrs = ((int(kb[0][:4]) - yk) * 12 + (int(kb[0][5:]) - mk)) / 12.0
    if yrs <= 0.5:
        return None
    return (kb[1] / ka[1]) ** (1 / yrs) - 1


def maxdd(ser, a, b):
    ks = sorted(k for k in ser if a <= k <= b)
    if len(ks) < 6:
        return None
    peak, dd = None, 0.0
    for k in ks:
        v = ser[k]
        peak = v if peak is None else max(peak, v)
        dd = min(dd, v / peak - 1)
    return dd


def spearman(xs, ys):
    n = len(xs)
    if n < 4:
        return None

    def rank(v):
        s = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[s[j + 1]] == v[s[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[s[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    return round(num / (dx * dy), 4) if dx and dy else None


def main():
    series, miss = {}, []
    for t in ALL:
        s = fetch(t)
        if s:
            series[t] = s
        else:
            miss.append(t)
        time.sleep(0.35)

    rows = []
    grp = {t: g for g, ts in CANDS.items() for t in ts}
    for t, s in series.items():
        ks = sorted(s)
        r = {"t": t, "group": grp[t], "first": ks[0], "last": ks[-1],
             "n_months": len(ks), "windows": {}, "dd": {}}
        for a, b in WINDOWS:
            key = f"{a[:4]}-{b[:4]}"
            c = cagr(s, a, b)
            r["windows"][key] = None if c is None else round(c, 4)
            d = maxdd(s, a, b)
            r["dd"][key] = None if d is None else round(d, 4)
        # 全期間（共通ではない＝設定日が違うので直接比べない）
        c = cagr(s, ks[0], ks[-1])
        r["full_cagr"] = None if c is None else round(c, 4)
        r["full_years"] = round(((int(ks[-1][:4]) - int(ks[0][:4])) * 12 +
                                 (int(ks[-1][5:]) - int(ks[0][5:]))) / 12.0, 2)
        r["full_maxdd"] = maxdd(s, ks[0], ks[-1])
        # ★転がる10年の年率——20-30年持つなら相場の転換を2〜3回は通る。
        #   「最良の10年」ではなく「**最悪の10年**」がその代金
        roll = []
        for i, k in enumerate(ks):
            y, m = int(k[:4]), int(k[5:])
            tgt = f"{y+10:04d}-{m:02d}"
            if tgt in s:
                roll.append((k, (s[tgt] / s[k]) ** 0.1 - 1))
        if roll:
            vs = sorted(x[1] for x in roll)
            r["roll10"] = {"n": len(roll),
                           "worst": round(vs[0], 4),
                           "worst_start": min(roll, key=lambda x: x[1])[0],
                           "med": round(vs[len(vs) // 2], 4),
                           "best": round(vs[-1], 4),
                           "neg_share": round(sum(1 for v in vs if v < 0) / len(vs), 3)}
        else:
            r["roll10"] = None
        rows.append(r)
    rows.sort(key=lambda x: -(x["windows"].get("2021-2026") or -9))

    # ★持続の検定: 隣り合う窓で順位が持続するか
    pers = []
    for i in range(len(WINDOWS) - 1):
        ka = f"{WINDOWS[i][0][:4]}-{WINDOWS[i][1][:4]}"
        kb = f"{WINDOWS[i+1][0][:4]}-{WINDOWS[i+1][1][:4]}"
        pairs = [(r["windows"][ka], r["windows"][kb]) for r in rows
                 if r["windows"].get(ka) is not None and r["windows"].get(kb) is not None]
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 4 else None
        # 前の窓の上位半分が、次の窓でも上位半分か
        hit = None
        if len(pairs) >= 6:
            srt = sorted(pairs, key=lambda p: -p[0])
            half = len(srt) // 2
            top = set(id(x) for x in srt[:half])
            nxt = sorted(pairs, key=lambda p: -p[1])[:half]
            nxt_ids = set(id(x) for x in nxt)
            hit = round(len(top & nxt_ids) / half, 3)
        pers.append({"from": ka, "to": kb, "n": len(pairs), "rho": rho,
                     "上位半分が次も上位半分の割合": hit})

    # ★★★円建てで測り直す——**この投資家の通貨は円**。
    #   上の数字はすべてドル建てで、円で見た実感とは違う。
    #   実測: 2011-08 のドル円は 76.8円（史上最安値圏）→ 2026-08 は 159.1円。
    #   この15年、**円安が年5〜10pt をリターンに乗せていた**。
    #   ⚠ これは将来の期待ではない——76.8→159 をもう一度やるには 320円が要る。
    #   逆に円高へ戻ると同じ大きさの逆風になる。**ETF間の差(年0〜2pt)より大きい**。
    fxs = fetch("JPY=X")
    fxsec = None
    if fxs:
        def cg(ser, a, b, f=None):
            ks = sorted(k for k in ser if a <= k <= b)
            if len(ks) < 12:
                return None
            k0, k1 = ks[0], ks[-1]
            y = ((int(k1[:4]) - int(k0[:4])) * 12 + (int(k1[5:]) - int(k0[5:]))) / 12.0
            v0, v1 = ser[k0], ser[k1]
            if f:
                if k0 not in f or k1 not in f:
                    return None
                v0 *= f[k0]
                v1 *= f[k1]
            return round((v1 / v0) ** (1 / y) - 1, 4)
        fxsec = {"note": "同じ系列を円建てへ直しただけ（配当込みのadjclose × その月のドル円）",
                 "windows": []}
        for a, b in (("2000-06", "2026-08"), ("2011-08", "2026-08"),
                     ("2016-08", "2026-08"), ("2021-08", "2026-08")):
            if a not in fxs or b not in fxs:
                continue
            yy = ((int(b[:4]) - int(a[:4])) * 12 + (int(b[5:]) - int(a[5:]))) / 12.0
            w = {"window": f"{a}→{b}", "fx_from": round(fxs[a], 1), "fx_to": round(fxs[b], 1),
                 "fx_cagr": round((fxs[b] / fxs[a]) ** (1 / yy) - 1, 4), "rows": []}
            for t in ("SMH", "SOXX", "XLK", "VGT", "QQQ", "SPY", "VTI", "VT"):
                if t not in series:
                    continue
                u, j = cg(series[t], a, b), cg(series[t], a, b, fxs)
                if u is None or j is None:
                    continue
                w["rows"].append({"t": t, "usd": u, "jpy": j, "diff_pt": round((j - u) * 100, 1)})
            fxsec["windows"].append(w)

    # ★★共通の開始日で揃える——「転がる10年の最悪」は**設定日で決まってしまう**。
    #   実測: SMH(2000-06開始・ドットコムの天井を含む) 最悪 -13.1% vs
    #         SOXX(2001-07開始・崩壊の後から) 最悪 -3.1%。ほぼ同じ半導体指数なのに10pt差。
    #   ＝始まりが違う系列の「最悪」を並べるのは「基準の違う二つを割る」型。
    #   さらに設定の新しいETF(FTEC/SPMO/MOAT/MTUM/QUAL)は**悪い10年を一度も通っていない**ので
    #   最悪の値がきれいに見えるだけ。共通窓で揃え直す。
    anchors = ["2000-06", "2001-07", "2004-01", "2008-06", "2013-10"]  # 2000-06 = ドットコムの天井から
    common = []
    for a in anchors:
        pool = [r for r in rows if r["first"] <= a]
        end = max(max(series[r["t"]]) for r in pool) if pool else None
        recs = []
        for r in pool:
            ser = series[r["t"]]
            c = cagr(ser, a, end)
            d = maxdd(ser, a, end)
            roll = []
            for k in sorted(k for k in ser if k >= a):
                y, m = int(k[:4]), int(k[5:])
                tgt = f"{y+10:04d}-{m:02d}"
                if tgt in ser:
                    roll.append((ser[tgt] / ser[k]) ** 0.1 - 1)
            recs.append({"t": r["t"], "group": r["group"],
                         "cagr": None if c is None else round(c, 4),
                         "maxdd": None if d is None else round(d, 4),
                         "roll10_worst": round(min(roll), 4) if roll else None,
                         "roll10_med": round(sorted(roll)[len(roll) // 2], 4) if roll else None,
                         "roll10_n": len(roll)})
        recs.sort(key=lambda x: -(x["cagr"] or -9))
        common.append({"start": a, "end": end, "n": len(recs), "rows": recs})

    # ★選定規則そのものを回す——「過去5年の上位N本を買い、次の5年持つ」を
    #   窓の境目ごとに実行し、SPY を持ち続けた場合と比べる。
    #   ⚠ 各時点で**その時に実在したETFだけ**から選ぶ（後から出たETFを選ばない）
    ruletest = []
    for topn in (1, 2, 3):
        legs, spy_legs = [], []
        for i in range(len(WINDOWS) - 1):
            ka = f"{WINDOWS[i][0][:4]}-{WINDOWS[i][1][:4]}"
            kb = f"{WINDOWS[i+1][0][:4]}-{WINDOWS[i+1][1][:4]}"
            avail = [r for r in rows if r["windows"].get(ka) is not None
                     and r["windows"].get(kb) is not None]
            if len(avail) < topn + 2:
                continue
            pick = sorted(avail, key=lambda r: -r["windows"][ka])[:topn]
            got = sum(r["windows"][kb] for r in pick) / topn
            spy = next((r["windows"][kb] for r in rows if r["t"] == "SPY"), None)
            legs.append({"選んだ窓": ka, "持った窓": kb,
                         "選んだ本": [r["t"] for r in pick],
                         "選んだ本の実現": round(got, 4),
                         "SPY": None if spy is None else round(spy, 4),
                         "差(pt)": None if spy is None else round((got - spy) * 100, 1)})
            spy_legs.append(spy)
        # 通期の複利（差が測れる脚だけ）
        ok = [l for l in legs if l["差(pt)"] is not None]
        cum_r = cum_s = 1.0
        for l in ok:
            cum_r *= (1 + l["選んだ本の実現"]) ** 5
            cum_s *= (1 + l["SPY"]) ** 5
        yrs = len(ok) * 5
        ruletest.append({
            "上位何本": topn, "脚": legs,
            "通期(年)": yrs,
            "規則の年率": None if yrs == 0 else round(cum_r ** (1 / yrs) - 1, 4),
            "SPYの年率": None if yrs == 0 else round(cum_s ** (1 / yrs) - 1, 4),
        })

    out = {
        "generated": datetime.date.today().isoformat(),
        "tool": "night/etf_returns.py",
        "role": "網(ETF)の中身を決めるための材料。**判定はしない**——ETF選定は門の外(DCA側)で、"
                "門Ωの採点・四関門・売却規律にはいっさい触れない",
        "source": "Yahoo Finance chart API の adjclose（分配金再投資込み・月次）",
        "windows": [f"{a}→{b}" for a, b in WINDOWS],
        "n_fetched": len(series), "missing": miss,
        "★持続の検定": pers,
        "★★円建てで測り直す": fxsec,
        "★共通の開始日で揃えた比較": common,
        "★選定規則を回した結果": ruletest,
        "★読み方": [
            "窓ごとの年率は**その窓の相場**を測っている。全期間の年率は設定日が違うので直接比べない",
            "測れない窓は null（設定前）。ゼロや代替指数で埋めていない（絶対のルール7）",
            "★生存バイアス——今日ティッカーが引けるETFだけを見ている。"
            "この20年で償還・統合されたセクターETFは母集団に居ない",
            "★★開始日で結論が変わる。SMH(2000-06=ドットコムの天井から)は年10.7%だが"
            "SOXX(2001-07=崩壊の後から)は年13.9%。ほぼ同じ半導体指数なのに3.2pt差＝"
            "『共通の開始日で揃えた比較』だけを読むこと。全期間の年率を並べてはいけない",
            "★設定の新しいETF(FTEC n=35 / SPMO n=11 / MOAT n=53 / MTUM n=41 / QUAL n=38)は"
            "**悪い10年を一度も通っていない**。転がる10年の最悪がきれいに見えるのはそのため",
        ],
        "rows": rows,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"■ 網(ETF)の歴史リターン — {len(series)}本 / 取得できず {len(miss)}本 {miss or ''}")
    print("  重ならない5年窓4つ（年率・分配金込み）\n")
    hdr = f"  {'':6s} {'群':10s}" + "".join(f"{f'{a[:4]}-{b[:4]}':>12s}" for a, b in WINDOWS)
    print(hdr)
    for r in rows:
        cells = ""
        for a, b in WINDOWS:
            v = r["windows"][f'{a[:4]}-{b[:4]}']
            cells += f"{'—':>12s}" if v is None else f"{v*100:>11.1f}%"
        print(f"  {r['t']:6s} {r['group']:10s}{cells}")
    print("\n  ★最大下落（窓ごと・分配金込みの月末ベース）")
    for r in rows:
        if r["t"] not in ("SMH", "SOXX", "XLK", "QQQ", "VGT", "SPY", "VTI", "VT", "RSP", "MOAT", "QUAL", "MTUM", "SPMO"):
            continue
        cells = ""
        for a, b in WINDOWS:
            v = r["dd"][f'{a[:4]}-{b[:4]}']
            cells += f"{'—':>12s}" if v is None else f"{v*100:>11.0f}%"
        print(f"  {r['t']:6s} {r['group']:10s}{cells}")
    print("\n  ★転がる10年の年率（最悪 / 中央 / 最良・n=観測数）")
    for r in sorted([x for x in rows if x.get("roll10")], key=lambda x: -x["roll10"]["med"]):
        q = r["roll10"]
        print(f"  {r['t']:6s} {r['group']:10s} 最悪{q['worst']*100:>7.1f}% ({q['worst_start']})"
              f"  中央{q['med']*100:>6.1f}%  最良{q['best']*100:>6.1f}%  n={q['n']:>3d}"
              f"  マイナスの10年 {q['neg_share']*100:.0f}%")
    for c in common:
        if c["start"] not in ("2000-06", "2001-07", "2008-06"):
            continue
        print(f"\n  ★共通窓 {c['start']} → {c['end']}（{c['n']}本・設定日を揃えた）")
        print(f"    {'':6s} {'群':10s} {'年率':>7s} {'最大下落':>8s} {'転10最悪':>8s} {'転10中央':>8s}")
        for r in c["rows"]:
            print(f"    {r['t']:6s} {r['group']:10s} {(r['cagr'] or 0)*100:>6.1f}% "
                  f"{(r['maxdd'] or 0)*100:>7.0f}% {(r['roll10_worst'] or 0)*100:>7.1f}% "
                  f"{(r['roll10_med'] or 0)*100:>7.1f}%")
    if fxsec:
        print("\n  ★★円建てで測り直す（この投資家の通貨は円）")
        for w in fxsec["windows"]:
            print(f"\n    {w['window']}  ドル円 {w['fx_from']}→{w['fx_to']}円（年{w['fx_cagr']*100:+.1f}%）")
            for r in w["rows"]:
                print(f"      {r['t']:5s} USD {r['usd']*100:>6.1f}%/年 → "
                      f"**円建て {r['jpy']*100:>6.1f}%/年**  差 {r['diff_pt']:+5.1f}pt")
    print("\n  ★持続（前の窓の順位は次の窓を当てるか）")
    for p in pers:
        print(f"    {p['from']} → {p['to']}  n={p['n']}  ρ={p['rho']}  "
              f"上位半分の残留 {p['上位半分が次も上位半分の割合']}")
    print("\n  ★『過去5年の上位N本を買い、次の5年持つ』を実際に回すと")
    for rt in ruletest:
        print(f"    上位{rt['上位何本']}本: 規則 {(rt['規則の年率'] or 0)*100:.1f}%/年 vs "
              f"SPY {(rt['SPYの年率'] or 0)*100:.1f}%/年  ({rt['通期(年)']}年)")
        for l in rt["脚"]:
            print(f"       {l['選んだ窓']}で選ぶ→{l['持った窓']}で持つ: "
                  f"{','.join(l['選んだ本'])} {l['選んだ本の実現']*100:+.1f}% vs SPY "
                  f"{(l['SPY'] or 0)*100:+.1f}%  差 {l['差(pt)']:+.1f}pt")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
