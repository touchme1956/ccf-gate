#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""20年保有の目で ETF を測る（2026-09-22新設）。

【なぜ新しい道具が要ったか】
既存の `out/etf_beat_spy.json` の最長窓は **2006-08起点**で、
**ドットコム天井(2000-03)を構造的に外している**。テック/半導体が20年で何をするかの
いちばん重い証拠がその窓の外にあるので、20年保有の問いには原理的に答えられない。
→ 系列を**設定来（Yahooは1993から）**取り直し、**転がる20年窓**で測る。

【20年保有の目で何を測るか】3つだけ。
 (1) 転がる20年窓で SPY に勝った割合と、**最悪の窓**（平均ではなく裾）
 (2) **水没期間**＝自分の過去最高値を下回り続けた最長月数。20年保有で実際に効くのはここ
 (3) **2000-03 天井から買った場合**の年率（最悪の起点を明示して引く）

⚠ 転がる窓は**重なっている**ので独立試行ではない。本数ではなく形として読む。
⚠ 生存バイアス: 母集団は「今日 買えるETF」＝償還された本は最初から居ない。
⚠ 採取器 `etf_theme.fetch` をそのまま使う（月の揃え方を再実装しない・v9.9.65の掟）。

実行: python3 night/etf_long_windows.py [--fetch]
"""
import json, os, sys, gzip, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
import etf_theme as T

OUT = os.path.join(BASE, "out", "etf_long_windows.json")
CACHE = os.path.join(BASE, "out", "_etf_long_cache.json.gz")

# 既存在庫 out/etf_beat_spy.json の「4窓すべてで勝った10本」＋ 比較の錨
TICKERS = ["SPY",                                   # 基準
           "SMH", "VGT", "XLK", "QQQ", "QTEC", "IXN", "ITA", "SPYG", "OEF", "IVV",  # 4窓勝者
           "QQQM", "VUG", "VOO", "VTI"]             # 実保有・錨
WIN = [20, 15, 10]


def mkey(y, m):
    return f"{y:04d}-{m:02d}"


def add_months(k, n):
    y, m = int(k[:4]), int(k[5:7])
    t = (y * 12 + (m - 1)) + n
    return mkey(t // 12, t % 12 + 1)


def months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def load():
    if os.path.exists(CACHE):
        with gzip.open(CACHE, "rt") as f:
            return json.load(f)
    return {}


def cagr(ser, a, b):
    """窓の全月を持つときだけ年率を返す（穴を跨いで年率を作らない）。"""
    if a not in ser or b not in ser:
        return None
    n = months_between(a, b)
    have = sum(1 for m in ser if a <= m <= b)
    if n <= 0 or have < n * 0.97:
        return None
    return (ser[b] / ser[a]) ** (12.0 / n) - 1


def underwater(ser, start=None):
    """自分の過去最高値を下回り続けた最長の月数と、その区間。"""
    ms = sorted(m for m in ser if start is None or m >= start)
    pk, pk_m = None, None
    worst, cur, cur_from = 0, 0, None
    span = None
    for m in ms:
        v = ser[m]
        if pk is None or v >= pk:
            pk, pk_m = v, m
            cur, cur_from = 0, None
        else:
            if cur_from is None:
                cur_from = pk_m
            cur += 1
            if cur > worst:
                worst, span = cur, (cur_from, m)
    return worst, span


# ── 混合（網の中の配合）を同じ窓で比べる（--mix・2026-09-22 ユーザーの問い「リターン効率を考えて」）
#   ⚠ リターンだけ並べると「効率」にならない。**年率 / ボラ / 最大下落 / 毎月積立の倍率**を同じ窓で出す。
#   ⚠ 配合は**毎月リバランス**（網の中の規約と同じ作法）。買い持ちは別物なので混ぜない。
#   ⚠ 重みは**網の中で正規化**する（城の比率に依らない＝配合そのものの効率を見る）。
def mix_series(cache, w):
    """{ticker:重み} → {月: 指数}（毎月リバランス・起点1.0）。全員が持つ月だけで作る。"""
    ms = None
    for t in w:
        s = set(cache.get(t) or {})
        ms = s if ms is None else (ms & s)
    if not ms:
        return {}
    ms = sorted(ms)
    tot = sum(w.values()) or 1.0
    out = {ms[0]: 1.0}
    for a, b in zip(ms, ms[1:]):
        r = sum((w[t] / tot) * (cache[t][b] / cache[t][a]) for t in w)
        out[b] = out[a] * r
    return out


def stats(ser, spy, a, b):
    """年率・年率ボラ・最大下落・毎月積立の倍率（とSPY積立との比）。"""
    ms = sorted(m for m in ser if a <= m <= b)
    if len(ms) < 24:
        return None
    n = months_between(a, b)
    cg = (ser[b] / ser[a]) ** (12.0 / n) - 1
    rets = [ser[y] / ser[x] - 1 for x, y in zip(ms, ms[1:])]
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    vol = (var ** 0.5) * (12 ** 0.5)
    pk, dd = None, 0.0
    for m in ms:
        v = ser[m]
        pk = v if pk is None or v > pk else pk
        dd = min(dd, v / pk - 1)
    buy = sorted(m for m in ser if a <= m < b)
    mult = sum(1.0 / ser[m] for m in buy) * ser[b] / len(buy)
    sm = None
    if spy and a in spy and b in spy:
        sb = sorted(m for m in spy if a <= m < b)
        sm = sum(1.0 / spy[m] for m in sb) * spy[b] / len(sb)
    return {"年率": round(cg * 100, 2), "年率ボラ": round(vol * 100, 2),
            "最大下落": round(dd * 100, 1),
            "年率÷ボラ": round(cg / vol, 3) if vol else None,
            "年率÷|最大下落|": round(cg / abs(dd), 3) if dd else None,
            "積立倍率": round(mult, 3),
            "積立倍率比SPY": round(mult / sm, 3) if sm else None}


def mix_view(cache, end, spec):
    spy = cache.get("SPY") or {}
    mixes = {}
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        lab, _, body = part.partition(":")
        if not body:
            lab, body = part, part
        w = {}
        for kv in body.split(","):
            k, _, v = kv.partition("=")
            k = k.strip().upper()
            if not k or not v.strip():
                raise SystemExit(f"--mix の書式は 'ラベル:QQQM=40,XLK=30' 。読めない: {kv!r}")
            if k not in cache or not cache[k]:
                raise SystemExit(f"系列が無い: {k}（--fetch で取るか TICKERS へ足す）")
            w[k] = float(v)
        mixes[lab.strip()] = w
    # ★共通の窓で比べる——起点が違う案どうしを並べると「設定日の罠」をここで再演する
    start = None
    for w in mixes.values():
        s = mix_series(cache, w)
        if not s:
            continue
        start = min(s) if start is None else max(start, min(s))
    out = {"共通の窓": f"{start}→{end}", "⚠": "毎月リバランス・重みは網の中で正規化・共通の窓でのみ比較",
           "案": {}}
    print(f"\n■ 混合の効率（共通の窓 {start}→{end}・毎月リバランス）", file=sys.stderr)
    print(f"   {'案':26} {'年率':>7} {'ボラ':>7} {'最大下落':>8} {'年率/ボラ':>9} {'年率/DD':>8} {'積立比SPY':>9}", file=sys.stderr)
    for lab, w in mixes.items():
        ser = mix_series(cache, w)
        st = stats(ser, spy, start, end) if ser else None
        out["案"][lab] = {"重み": w, "全窓": st}
        if st:
            print(f"   {lab:26} {st['年率']:7.2f} {st['年率ボラ']:7.2f} {st['最大下落']:8.1f} "
                  f"{st['年率÷ボラ']:9.3f} {st['年率÷|最大下落|']:8.3f} {st['積立倍率比SPY']:9.3f}", file=sys.stderr)
    # 転がる20年窓（毎月積立）でも比べる——全窓の1本値は起点に依存するため
    print(f"\n   ── 転がる20年窓の毎月積立（重なる窓・独立試行ではない）", file=sys.stderr)
    print(f"   {'案':26} {'n':>4} {'倍率比SPY 中央':>14} {'最小':>8} {'勝率':>6}", file=sys.stderr)
    for lab, w in mixes.items():
        ser = mix_series(cache, w)
        rs = []
        for a in sorted(ser):
            b = add_months(a, 240)
            if b > end:
                break
            s1 = stats(ser, spy, a, b)
            if s1 and s1.get("積立倍率比SPY"):
                rs.append(s1["積立倍率比SPY"])
        if not rs:
            continue
        rr = sorted(rs)
        out["案"][lab]["転がる20年_積立"] = {"n": len(rr), "倍率比_中央": rr[len(rr) // 2],
                                        "倍率比_最小": rr[0],
                                        "勝率": round(sum(1 for x in rr if x > 1) / len(rr), 3)}
        print(f"   {lab:26} {len(rr):4d} {rr[len(rr)//2]:14.3f} {rr[0]:8.3f} "
              f"{sum(1 for x in rr if x>1)/len(rr)*100:5.0f}%", file=sys.stderr)
    return out


def main():
    cache = load()
    if "--fetch" in sys.argv or not cache:
        for t in TICKERS:
            if t in cache and cache[t]:
                continue
            cache[t] = T.fetch(t)
            print(f"  {t}: {len(cache[t] or {})}ヶ月", file=sys.stderr)
            time.sleep(0.5)
        with gzip.open(CACHE, "wt") as f:
            json.dump(cache, f)

    spy = cache.get("SPY") or {}
    end = max(m for m in spy)
    # 直近の完全な月まで（当月は未完なので落とす）
    end = max(m for m in spy if m < time.strftime("%Y-%m"))
    print(f"終点 {end}", file=sys.stderr)

    rows = {}
    for t in TICKERS:
        ser = cache.get(t) or {}
        if not ser:
            rows[t] = {"未取得": True}
            continue
        first = min(ser)
        r = {"開始": first, "月数": len(ser)}
        for y in WIN:
            n = y * 12
            recs = []
            for a in sorted(ser):
                b = add_months(a, n)
                if b > end:
                    break
                ca, cs = cagr(ser, a, b), cagr(spy, a, b)
                if ca is None or cs is None:
                    continue
                recs.append({"from": a, "to": b, "cagr": round(ca * 100, 2),
                             "spy": round(cs * 100, 2), "ex": round((ca - cs) * 100, 2)})
            if not recs:
                r[f"{y}y"] = {"n": 0, "note": "この長さの窓を持たない"}
                continue
            ex = sorted(x["ex"] for x in recs)
            wr = sum(1 for x in ex if x > 0) / len(ex)
            worst = min(recs, key=lambda x: x["ex"])
            worst_abs = min(recs, key=lambda x: x["cagr"])
            r[f"{y}y"] = {
                "n": len(recs), "窓の起点": f"{recs[0]['from']}〜{recs[-1]['from']}",
                "勝率": round(wr, 3),
                "超過_中央値": ex[len(ex) // 2], "超過_最小": ex[0], "超過_最大": ex[-1],
                "最悪の超過の窓": worst, "年率が最低の窓": worst_abs,
            }
        uw, span = underwater(ser)
        r["水没_最長月数"] = uw
        r["水没_区間"] = span
        rows[t] = r

    # ★被覆をそろえた比較——勝率は「どの窓を持っているか」で嘘をつく（VGT 99.3% vs XLK 79.2% の型）
    aligned = {}
    for y in WIN:
        n = y * 12
        # 全員が持つ起点だけを使う（SPYは基準なので除く・20年窓を持たない本も除く）
        pool = [t for t in TICKERS if t != "SPY" and (cache.get(t) or {})
                and cagr(cache[t], min(cache[t]), add_months(min(cache[t]), n)) is not None]
        if not pool:
            continue
        starts = None
        for t in pool:
            ser = cache[t]
            ok = {a for a in ser if add_months(a, n) <= end
                  and cagr(ser, a, add_months(a, n)) is not None
                  and cagr(spy, a, add_months(a, n)) is not None}
            starts = ok if starts is None else (starts & ok)
        if not starts:
            aligned[f"{y}y"] = {"n": 0, "note": "全員が共有する起点が無い"}
            continue
        ss = sorted(starts)
        tbl = {}
        for t in pool:
            ex = [cagr(cache[t], a, add_months(a, n)) - cagr(spy, a, add_months(a, n)) for a in ss]
            tbl[t] = {"勝率": round(sum(1 for e in ex if e > 0) / len(ex), 3),
                      "超過_中央値": round(sorted(ex)[len(ex) // 2] * 100, 2),
                      "超過_最小": round(min(ex) * 100, 2)}
        aligned[f"{y}y"] = {"n": len(ss), "共通の起点": f"{ss[0]}〜{ss[-1]}",
                            "⚠": "全員が持つ起点だけ＝いちばん新しい本に合わせて窓が短く新しくなる", "表": tbl}

    # ★長い系列だけで被覆をそろえる——全員そろえると QTEC/ITA(2006-05開始)に引きずられて n=4 になる。
    #   ⚠ここを揃えると共通の起点が 2001-11 以降＝**ドットコム天井そのものが窓から消える**。
    #   「被覆を揃える」と「天井の証拠を残す」は両立しない。両方を並べて読むこと。
    LONG = ["SMH", "XLK", "QQQ", "IXN", "SPYG", "OEF", "IVV"]
    aligned_long = {}
    for y in WIN:
        n = y * 12
        starts = None
        for t in LONG:
            ser = cache.get(t) or {}
            ok = {a for a in ser if add_months(a, n) <= end
                  and cagr(ser, a, add_months(a, n)) is not None
                  and cagr(spy, a, add_months(a, n)) is not None}
            starts = ok if starts is None else (starts & ok)
        if not starts:
            continue
        ss = sorted(starts)
        tbl = {}
        for t in LONG:
            ex = [cagr(cache[t], a, add_months(a, n)) - cagr(spy, a, add_months(a, n)) for a in ss]
            exs = sorted(ex)
            tbl[t] = {"一括_勝率": round(sum(1 for e in ex if e > 0) / len(ex), 3),
                      "一括_超過中央": round(exs[len(exs) // 2] * 100, 2),
                      "一括_超過最小": round(exs[0] * 100, 2)}
        aligned_long[f"{y}y"] = {"n": len(ss), "共通の起点": f"{ss[0]}〜{ss[-1]}",
                                 "窓の終点": f"{add_months(ss[0], n)}〜{add_months(ss[-1], n)}",
                                 "⚠": "揃えた代償にドットコム天井が窓から消えている", "表": tbl}

    # ★毎月積立(DCA)で同じ窓を測る——この資産の実際の買い方はこちら。
    #   一括の転がる窓は「天井で全額入れた人」の話で、積立は下げ続きの窓で口数を多く拾う。
    def dca(ser, a, b):
        """毎月1単位の金額を入れたときの最終評価額 ÷ 投じた総額。"""
        ms = sorted(m for m in ser if a <= m < b)
        n = months_between(a, b)
        if len(ms) < n * 0.97 or b not in ser:
            return None
        units = sum(1.0 / ser[m] for m in ms)
        return units * ser[b] / len(ms)          # 倍率（投下額=len(ms)）

    dca_tbl = {}
    for y in WIN:
        n = y * 12
        rec = {}
        for t in TICKERS:
            ser = cache.get(t) or {}
            xs = []
            for a in sorted(ser):
                b = add_months(a, n)
                if b > end:
                    break
                mt, ms_ = dca(ser, a, b), dca(spy, a, b)
                if mt is None or ms_ is None:
                    continue
                xs.append({"from": a, "mult": round(mt, 3), "spy": round(ms_, 3),
                           "ratio": round(mt / ms_, 3)})
            if not xs:
                continue
            rs = sorted(x["ratio"] for x in xs)
            worst = min(xs, key=lambda x: x["ratio"])
            rec[t] = {"n": len(xs), "起点": f"{xs[0]['from']}〜{xs[-1]['from']}",
                      "勝率": round(sum(1 for r in rs if r > 1) / len(rs), 3),
                      "倍率比_中央値": rs[len(rs) // 2], "倍率比_最小": rs[0],
                      "最悪の窓": worst}
        dca_tbl[f"{y}y"] = rec

    # ドットコム天井(2000-03)から20年
    dot = {}
    for t in TICKERS:
        ser = cache.get(t) or {}
        for a in ["2000-03", "2000-08"]:
            b = add_months(a, 240)
            if b > end:
                continue
            c = cagr(ser, a, b)
            if c is not None:
                dot.setdefault(a, {})[t] = round(c * 100, 2)

    mixdoc = None
    for _i, _a in enumerate(sys.argv):
        if _a == "--mix" and _i + 1 < len(sys.argv):
            mixdoc = mix_view(cache, end, sys.argv[_i + 1])

    doc = {
        "generated": time.strftime("%Y-%m-%d"),
        "tool": "night/etf_long_windows.py",
        "終点": end,
        "母集団": "out/etf_beat_spy.json の『4窓すべてで勝った10本』＋ 実保有/錨（QQQM/VUG/VOO/VTI）",
        "読み方": [
            "転がる窓は重なっている＝独立試行ではない。本数ではなく形として読む。",
            "『超過_最小』＝その長さで保有して最も悪かったとき。20年保有はここを引く可能性がある。",
            "水没_最長月数＝自分の過去最高値を下回り続けた最長。20年保有で実際に効くのはここ。",
            "★勝率は『どの窓を持っているか』で嘘をつく。必ず ★被覆をそろえた勝率 と両方読む。",
            "★この資産の買い方は毎月積立なので ★毎月積立(DCA) が実際に当たる数字。一括の転がる窓は『天井で全額入れた人』の話。",
        ],
        "⚠限界": [
            "生存バイアスは構造的（今日買えるETFだけ）",
            "系列はYahooの月次adjclose（分配金込み）・USD建て",
            "ETFの設定日より前は存在しない＝長い窓を持てない本は比較に出ない",
        ],
        "★被覆をそろえた勝率": aligned,
        "★長い系列だけで揃えた勝率": aligned_long,
        "★毎月積立(DCA)": dca_tbl,
        "ドットコム天井から20年": dot,
        "★混合の効率": mixdoc,
        "rows": rows,
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
