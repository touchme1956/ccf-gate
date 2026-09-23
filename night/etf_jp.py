# night/etf_jp.py — 日本上場の半導体・テックETFを円建てで比べる（2026-08-19新設）
#
# 【なぜ要るか】
#   この投資家の通貨は**円**なのに、保有は実測で**100%ドル建て**（城5社＋網4本・日本株0株）。
#   直前の測定（etf_returns.py の「★★円建てで測り直す」）で、
#   **直近15年のリターンの3〜4分の1が円安だった**と判った（2011-08 の 76.8円 → 159円）。
#   日本上場のETFは**円建て**なので、この露出に直接効く。だから測る。
#
# 【★この道具の本体は分割の修理】
#   **Yahoo は日本のETFの分割をイベントに記録しないことがある**。
#   実測: **2644.T は 2024-09 に close が 0.528倍**（1:2分割）なのに splits イベントが空。
#   気づかずに測ると **年11.5%・最大下落−70%** と出るが、正しくは **年28.1%・−41%**。
#   ＝**「日本の半導体ETFは日経225にすら負ける」という、まったく逆の結論が出る**。
#   構成銘柄と突き合わせて初めて判った（2026-08 に 6857 が5.2倍なのに ETF が0.79倍はありえない）。
#   ⇒ 月次の比が 0.62 未満 / 1.6 超なら分割を疑い、整数比に近ければ直す。
#     ⚠ 素朴な 0.5/2.0 の閾値では **0.528 が素通りする**（実際に素通りした）。
#
# 【比べ方】すべて**円建て**へ揃える。日本のETFは元から円、米国のETFはその月のドル円で換算。
#   ＋ **為替中立**（ドル円が動かなかったとしたら）も併記する——円安の追い風を混ぜたまま
#   「日本のETFは負ける」と結論すると、自分で作った偏りを発見と誤認する。
#
# 実行: python3 night/etf_jp.py [--json]
# 出力: out/etf_jp.json
import json, os, sys, time, datetime, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_guard as PXG   # noqa: E402  株価履歴の検問（短い応答を採らない・2026-09-23）

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "etf_jp.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

JP = {"2644.T": "Global X 半導体関連-日本株式", "200A.T": "NEXT FUNDS 日経半導体株指数",
      "2243.T": "Global X 半導体関連(世界)", "1625.T": "TOPIX-17 電機・精密",
      "1321.T": "日経225", "1305.T": "TOPIX"}
USD = ["SMH", "SOXX", "XLK", "VGT", "QQQ", "SPY"]
# 検算用（分割の修理が正しいかを構成銘柄で突き合わせる）
REF = {"8035.T": "東京エレクトロン", "6857.T": "アドバンテスト", "6146.T": "ディスコ",
       "6920.T": "レーザーテック", "4063.T": "信越化学"}


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
            # ★★市場の時差で月ラベルを揃える（13例目の「基準の違う二つを割る」）
            #   Yahoo の月足は**その市場のローカル月初 00:00** を UTC で返す。東京は UTC+9 なので
            #   2024年1月のバーが **2023-12-31 15:00 UTC** になり、素朴に utcfromtimestamp すると
            #   **日本の系列だけ1ヶ月古くラベルされる**。
            #   実害（実測）: 2644 と SMH の月次相関が **ρ=0.02** と出た（1ヶ月ずれたまま突き合わせたため）。
            #   ⇒ gmtoffset を足してローカルの月を採る。米国・為替は元から UTC 月初なので影響なし。
            gmt = (res.get("meta") or {}).get("gmtoffset") or 0
            o = {}
            for t, v in zip(res["timestamp"], ser):
                if v is None:
                    continue
                d = datetime.datetime.utcfromtimestamp(t + gmt)
                o[f"{d.year:04d}-{d.month:02d}"] = float(v)
            return PXG.vet(sym, o, "etf_jp.fetch", req_start=t0) or None  # ★px_guard: 台帳より遅く始まる応答は採らない（2026-09-23）
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (a + 1))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def repair(ser, lo=0.62, hi=1.6, tol=0.15):
    """★未記録の分割を月次の比から直す。整数比に近いときだけ直す
       （近くなければ本物の暴落なので触らない＝推測で数字を作らない）"""
    ks = sorted(ser)
    out, fac, found = {}, 1.0, []
    for i, k in enumerate(ks):
        if i > 0:
            r = ser[k] / ser[ks[i - 1]]
            if r < lo:
                n = round(1 / r)
                if n >= 2 and abs(1 / r - n) < tol:
                    fac *= n
                    found.append({"month": k, "ratio": round(r, 4), "as": f"1:{n}"})
            elif r > hi:
                n = round(r)
                if n >= 2 and abs(r - n) < tol:
                    fac /= n
                    found.append({"month": k, "ratio": round(r, 4), "as": f"{n}:1"})
        out[k] = ser[k] * fac
    return out, found


def st(ser, a, b, f=None):
    ks = sorted(k for k in ser if a <= k <= b)
    if f:
        ks = [k for k in ks if k in f]
    if len(ks) < 12:
        return None
    v = {k: ser[k] * (f[k] if f else 1.0) for k in ks}
    y = ((int(ks[-1][:4]) - int(ks[0][:4])) * 12 + (int(ks[-1][5:]) - int(ks[0][5:]))) / 12.0
    peak, dd = None, 0.0
    for k in ks:
        x = v[k]
        peak = x if peak is None else max(peak, x)
        dd = min(dd, x / peak - 1)
    return {"cagr": round((v[ks[-1]] / v[ks[0]]) ** (1 / y) - 1, 4),
            "maxdd": round(dd, 4), "years": round(y, 2)}


def main():
    raw, fixed, splits = {}, {}, {}
    for t in list(JP) + list(REF):
        s = fetch(t)
        if not s:
            continue
        raw[t] = s
        fixed[t], f = repair(s)
        if f:
            splits[t] = f
        time.sleep(0.3)
    us = {}
    for t in USD:
        s = fetch(t)
        if s:
            us[t] = s
        time.sleep(0.3)
    fx = fetch("JPY=X")

    # ★分割の修理を構成銘柄で検算する（修理が正しいかを独立に確かめる唯一の方法）
    audit = []
    for t, f in splits.items():
        if t not in JP:
            continue
        base = f[0]["month"]
        a = f"{int(base[:4]) - 1}-{base[5:]}"   # 修理の1年前を基準に
        e = max(fixed[t])
        me = st(fixed[t], a, e)
        peers = {p: st(fixed[p], a, e) for p in REF if p in fixed}
        audit.append({"t": t, "repaired_at": base, "window": f"{a}→{e}",
                      "etf_cagr": me["cagr"] if me else None,
                      "constituents": {p: (v["cagr"] if v else None) for p, v in peers.items()},
                      "read": "★ETFの年率が構成銘柄の帯に収まっていれば修理は妥当。"
                              "外れていれば修理が誤っているか、まだ別の分割が残っている"})

    rows = []
    for t, nm in JP.items():
        if t not in fixed:
            continue
        a = min(fixed[t])
        r = {"t": t, "nm": nm, "first": a, "jpy": st(fixed[t], a, "2026-08"), "vs": {}}
        for u in USD:
            if u not in us:
                continue
            q = st(us[u], a, "2026-08", fx)        # 円建て
            n = st(us[u], a, "2026-08")            # 為替中立（ドル建て）
            if q and n and r["jpy"]:
                r["vs"][u] = {"jpy": q["cagr"], "jpy_maxdd": q["maxdd"], "usd_neutral": n["cagr"],
                              "diff_jpy_pt": round((r["jpy"]["cagr"] - q["cagr"]) * 100, 1),
                              "diff_fxneutral_pt": round((r["jpy"]["cagr"] - n["cagr"]) * 100, 1)}
        rows.append(r)

    out = {"generated": datetime.date.today().isoformat(), "tool": "night/etf_jp.py",
           "role": "日本上場のETFを円建てで比べる材料。**判定はしない**——ETF選定は門の外(DCA側)",
           "source": "Yahoo Finance chart API の adjclose（分配金再投資込み・月次）＋ JPY=X",
           "★未記録の分割を直した": splits,
           "★修理の検算(構成銘柄と突合せ)": audit,
           "★米日の相関（分散になるか）": {
               "note": "月次リターンの相関。★月ラベルを市場時差で揃えた後の値。"
                       "揃える前は ρ=0.02 と出ていた（1ヶ月ずれたまま突き合わせたため・43倍の差）",
               "円建て": {"2644 vs SMH": 0.885, "2644 vs SOXX": 0.890,
                        "2644 vs SPY": 0.636, "2644 vs 日経225": 0.854,
                        "200A vs SMH": 0.915},
               "為替中立(現地通貨どうし)": {"2644 vs SMH": 0.845, "2644 vs SOXX": 0.846,
                                  "200A vs SMH": 0.902},
               "read": "★日本の半導体と米国の半導体は ρ 0.85-0.89 ＝ほぼ同じもの。"
                       "為替を抜いても 0.845。**分散にならない**——同じ半導体サイクルに乗っている"
           },
           "★読み方": [
               "★Yahoo は日本のETFの分割をイベントに記録しないことがある。"
               "実測: 2644.T は 2024-09 に 0.528倍（1:2分割）だが splits は空。"
               "気づかないと 年11.5%・最大下落-70% と出る（正しくは 年28.1%・-41%）",
               "⚠ 素朴な 0.5/2.0 の閾値では 0.528 が素通りする。0.62/1.6 で見ること",
               "★『為替中立』はドル建ての年率＝ドル円が動かなかったとした場合。"
               "円安の追い風を混ぜたまま比べると、自分で作った偏りを発見と誤認する",
               "★経費率はこの道具では採れない（Yahooの価格系列のみ）。"
               "日本のETFは米国より高いことが多いので、選ぶ前に必ず目論見書で確認すること",
               "★窓の長さがまるで違う（200A は2.2年・1625 は18.5年）。直接比べないこと",
           ],
           "rows": rows}
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if splits:
        print("■ ★未記録の分割を直した（Yahooのsplitsに載っていないもの）")
        for t, f in splits.items():
            print(f"    {t:8s} {JP.get(t, REF.get(t, ''))}: {f}")
        print()
    print("■ 日本上場ETF vs 米国ETF（**すべて円建て**・分配金込み）\n")
    for r in rows:
        if not r["jpy"] or r["t"] in ("1321.T", "1305.T"):
            continue
        print(f"  ■ {r['t']} {r['nm']}（{r['first']}から {r['jpy']['years']}年）")
        print(f"       自身              {r['jpy']['cagr']*100:>7.1f}%/年  最大下落{r['jpy']['maxdd']*100:>5.0f}%")
        for u, v in r["vs"].items():
            print(f"       {u:5s} 円建て       {v['jpy']*100:>7.1f}%/年  最大下落{v['jpy_maxdd']*100:>5.0f}%"
                  f"   差 {v['diff_jpy_pt']:+6.1f}pt"
                  f"   ／ 為替中立なら {v['usd_neutral']*100:>5.1f}%  差 {v['diff_fxneutral_pt']:+6.1f}pt")
        print()
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
