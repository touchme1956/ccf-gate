#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rf_prices.py — Bloomberg Reformers Index の再現・段1b（月次の価格・出来高・分割・ベンチマーク・為替）

事前登録: out/reformers_prereg.json。この道具は規則も成績も持たない（価格を揃えるだけ）。

  - 銘柄: rf_facts の us-gaap 提出社のうち、今日の SEC ティッカー表に普通株の記号がある社（gate_add_facts.ticker_table と同じ規則）。
    記号ごとに out/_nx_cache/yh_{T}_1mo.json（Yahoo の月足・配当と分割つき）を読む。無ければ取りに行く（3並列・404 は負のキャッシュ）。
    1つの社に記号が複数あれば、月数の多いほう。Yahoo の instrumentType が EQUITY 以外は落とす（ETF・投信）。
  - 出力（コミットしない・.gitignore）: out/_rf_prices.json.gz
      firms[cik] = {t: 記号, ccy, bars: {yyyymm: [adjclose, close, volume]}, splits: [[YYYY-MM-DD, 比], …]}
      bench[名前] = {yyyymm: adjclose}   ^SP500TR（配当込み）・QQQ・IWM・JPY=X（ドル円の月末）
  - Yahoo に現存する銘柄だけ＝生存バイアスあり。今日のティッカー表に無い社（上場廃止・合併・社名変更前の記号のみ）は価格が無い
    → 組み立て側が『価格なし』として数え、上下限の場合分けにする（欠測を0と読まない）
"""
import concurrent.futures as cf
import datetime
import gzip
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
sys.path.insert(0, BASE)
import gate_add_facts as G  # noqa: E402  ——ティッカー表・Yahoo の取得（同じキャッシュ名）

OUT = os.path.join(BASE, "out")
BENCH = ["^SP500TR", "QQQ", "IWM", "JPY=X", "^GSPC"]


def bars_full(r):
    """{yyyymm: [adjclose, close, volume]}・分割 [[日付, 比]]・通貨・instrumentType"""
    if not r:
        return None
    ts = r.get("timestamp") or []
    ind = r.get("indicators") or {}
    adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
    q = (ind.get("quote") or [{}])[0]
    cl, vo = q.get("close"), q.get("volume")
    if not ts or adj is None or cl is None:
        return None
    out = {}
    for i, t in enumerate(ts):
        a, c = adj[i], cl[i]
        if not isinstance(a, (int, float)) or not isinstance(c, (int, float)) or a <= 0 or c <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        v = vo[i] if vo is not None and i < len(vo) and isinstance(vo[i], (int, float)) else None
        out[d.year * 100 + d.month] = [a, c, v]
    sp = []
    for k, v in ((r.get("events") or {}).get("splits") or {}).items():
        try:
            dd = datetime.datetime.utcfromtimestamp(int(v.get("date", k))).date()
            num, den = float(v.get("numerator") or 0), float(v.get("denominator") or 0)
            if num > 0 and den > 0:
                sp.append([dd.isoformat(), num / den])
        except Exception:  # noqa
            pass
    meta = r.get("meta") or {}
    return {"bars": out, "splits": sorted(sp), "ccy": meta.get("currency"), "type": meta.get("instrumentType")}


def fx_month_end(t="JPY=X"):
    """為替は Yahoo の月足の時刻が夏時間で1か月ずれて（4〜10月の足が1か月早いラベルになり毎年10月が欠ける）使えない。
    日足を取り、その月の最後の日の終値を月末値にする（日付は UTC+3 で丸める＝ロンドンの午前0時の足も同じ日に入る）"""
    p = os.path.join(G.NXC, "yh_JPY_X_1d.json")
    if not (os.path.exists(p) and os.path.getsize(p) > 0 and time.time() - os.path.getmtime(p) < 3 * 86400):
        import urllib.parse
        import urllib.request
        u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}"
             f"&interval=1d")
        ua = {"User-Agent": "Mozilla/5.0 (ccf-gate research; contact via github touchme1956/ccf-gate)"}
        b = urllib.request.urlopen(urllib.request.Request(u, headers=ua), timeout=90).read()
        open(p, "wb").write(b)
    r = json.load(open(p))["chart"]["result"][0]
    ts = r["timestamp"]
    cl = r["indicators"]["quote"][0]["close"]
    last = {}
    for a, c in zip(ts, cl):
        if not isinstance(c, (int, float)) or c <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(a + 3 * 3600)
        last[d.year * 100 + d.month] = (d.day, c)   # 昇順に並んでいる前提で上書き＝月内で最後の日
    return {k: v[1] for k, v in last.items()}


def one(args):
    cik, tickers = args
    best = None
    for t in tickers:
        for tt in dict.fromkeys([t, t.replace(".", "-")]):
            b = bars_full(G.yahoo_raw(tt, fetch=True))
            if b and b["bars"] and (best is None or len(b["bars"]) > len(best[1]["bars"])):
                best = (tt, b)
    return cik, best


def main():
    T, dt = G.ticker_table()
    facts = json.load(gzip.open(os.path.join(OUT, "_rf_facts.json.gz"), "rt"))["firms"]
    todo = [(c, T[int(c)]) for c in facts if int(c) in T and T[int(c)]]
    print(f"ティッカー表 {dt}・対象 {len(todo)}社", flush=True)
    firms, miss, nonequity = {}, 0, 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(3) as ex:
        for i, (cik, best) in enumerate(ex.map(one, todo), 1):
            if best is None:
                miss += 1
            else:
                tt, b = best
                if b["type"] and b["type"] != "EQUITY":
                    nonequity += 1
                else:
                    firms[cik] = {"t": tt, **b}
            if i % 500 == 0:
                print(f"   {i}/{len(todo)} {time.time() - t0:.0f}s 価格あり{len(firms)} 価格なし{miss} 非株式{nonequity}", flush=True)
    bench = {}
    for name in BENCH:
        if name == "JPY=X":
            bench[name] = fx_month_end(name)
            continue
        b = bars_full(G.yahoo_raw(name, fetch=True))
        if b:
            bench[name] = {k: v[0] for k, v in b["bars"].items()}
    p = os.path.join(OUT, "_rf_prices.json.gz")
    with gzip.open(p + ".tmp", "wt") as f:
        json.dump({"built": datetime.date.today().isoformat(), "ticker_table": dt, "firms": firms, "bench": bench,
                   "no_price": miss, "non_equity": nonequity}, f)
    os.replace(p + ".tmp", p)
    print(f"■ 価格あり{len(firms)}社／価格なし{miss}／非株式{nonequity}／ベンチ {list(bench)} → {p} ({os.path.getsize(p) / 1e6:.1f}MB) {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
