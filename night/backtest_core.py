#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_core.py — 機械コアの疑似バックテスト（2026-08-04新設・提案3）

目的:
  門の「出力の検証」（予測が当たったか）は2026-08に始まったばかりで実績ゼロ回。
  予実台帳が答えを出すのは数年先だが、**機械で測れる欄だけなら過去時点の再構成ができる**——
  companyfacts の各行は filed(提出日) を持つので、「その時点で読めた数字」だけで
  through-cycle ROIC・営業利益率・成長率を作り、その後の配当込みリターン・実現成長と突き合わせる。
  とくに E[r] の g=20%上限に張り付く社（投下可の4割）の「その後の実現成長」は、
  現在保留中の成長減衰パラメータ（結論を総合9.4%〜13.6%と4pt動かす最大の未較正項）の
  事前分布を予実台帳より4年早く与える。

厳格な限界（読み手が誤認しないための明記）:
  1. **生存バイアス**: 母集団は「今のパック台帳」＝2018年時点に存在して今も残る社。
     倒産・被買収・上場廃止は消えているので、**リターンの絶対水準は上に偏る**。
     クインタイル間の相対比較と成長減衰の分布にだけ使うこと。
  2. **定性欄は遡及できない**: dom/irr/erosion 等は当時の判断が残っていないため、
     これは Ω の検証ではなく **機械コア（roic/opm/cagr）の識別力**の検証。
  3. 価格は Yahoo chart の adjclose（配当調整済み＝トータルリターン近似）。分割も調整済み。
  4. 当時のタグ体系で欠測する社は欠測のまま落とす（欠測をゼロと読まない——ルール7）。

使い方:
  python3 night/backtest_core.py                     # cutoff 2018-07-01・全米国パック
  python3 night/backtest_core.py --cutoff 2015-07-01 --limit 50
出力: out/backtest_<year>.json ＋ 標準出力に要約（クインタイル・g張り付き群の実現成長）
キャッシュ: out/_cf_cache/（gitignore済——companyfactsの生JSONは1.4GB級になるためコミットしない）
"""
import json, os, sys, time, urllib.request, statistics
from datetime import date

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL = "fortis5280@gmail.com"
HDRS  = {"User-Agent": f"ccf-gate-backtest {EMAIL}"}
CACHE = os.path.join(BASE, "out", "_cf_cache")

TAGS = {
 "rev":   ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenue"],
 "op":    ["OperatingIncomeLoss"],
 "tax":   ["IncomeTaxExpenseBenefit"],
 "pre":   ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
           "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
 "eq":    ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
 "assets":["Assets"],
 "gw":    ["Goodwill"],
}
# 有利子負債・無形は「総額タグ優先・無ければ構成要素の和」（series_sumの作法。代替と構成要素を混ぜない）
DEBT_TOTAL = ["LongTermDebt"]
DEBT_PARTS = ["LongTermDebtNoncurrent", "LongTermDebtCurrent", "ShortTermBorrowings",
              "DebtCurrent", "CommercialPaper"]
INT_TOTAL  = ["IntangibleAssetsNetExcludingGoodwill"]
INT_PARTS  = ["FiniteLivedIntangibleAssetsNet", "IndefiniteLivedIntangibleAssetsExcludingGoodwill"]


def get(url, binary=False):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=90) as r:
        b = r.read()
    time.sleep(0.15)
    return b if binary else b.decode("utf-8", "ignore")


def facts_of(cik):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"CIK{cik}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    j = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    json.dump(j, open(p, "w", encoding="utf-8"))
    return j


def annual_rows(facts, tag, cutoff):
    """FY年次行 {会計年: 値}。cutoff指定時は filed<=cutoff の行だけ＝当時読めた数字。
       同じ会計年に複数の提出があれば「cutoff以前で最後に提出された」値を採る"""
    node = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not node:
        return {}
    best = {}
    for unit, rows in (node.get("units") or {}).items():
        if unit not in ("USD", "USD/shares", "shares"):
            continue
        for r in rows:
            if r.get("fp") != "FY" or r.get("form") not in ("10-K", "10-K/A") or r.get("val") is None:
                continue
            fy = r.get("fy"); end = r.get("end") or ""; filed = r.get("filed") or ""
            if cutoff and filed > cutoff:
                continue
            s = r.get("start")
            if s and end:
                try:
                    y0, m0, d0 = map(int, s.split("-")); y1, m1, d1 = map(int, end.split("-"))
                    if (date(y1, m1, d1) - date(y0, m0, d0)).days < 300:  # 期間検問(四半期行を弾く)
                        continue
                except Exception:
                    pass
            yr = int(end[:4]) if end else fy
            if yr is None:
                continue
            k = int(yr)
            if k not in best or filed > best[k][0]:
                best[k] = (filed, float(r["val"]))
    return {k: v[1] for k, v in best.items()}


def series_pick(facts, cands, cutoff):
    """候補=代替: 最新年が最も進んでいる候補群のうち優先順が最も高いものを1本採る"""
    got = {t: annual_rows(facts, t, cutoff) for t in cands}
    mx = max((max(v) for v in got.values() if v), default=None)
    if mx is None:
        return {}
    for t in cands:
        v = got[t]
        if v and max(v) >= mx - 1:
            return v
    return {}


def series_total_or_sum(facts, totals, parts, cutoff):
    """候補=構成要素: その年に総額タグがあれば総額、無ければ構成要素の和（series_sumの作法）"""
    tot = {}
    for t in totals:
        for y, v in annual_rows(facts, t, cutoff).items():
            if y not in tot:
                tot[y] = v
    ps = [annual_rows(facts, t, cutoff) for t in parts]
    years = set(tot) | {y for p in ps for y in p}
    out = {}
    for y in years:
        if y in tot:
            out[y] = tot[y]
        else:
            vals = [p[y] for p in ps if y in p]
            if vals:
                out[y] = sum(vals)
    return out


def pit_metrics(facts, cutoff):
    """cutoff時点の機械コア: through-cycle roic/roicg(med5)・opm・cagr3y。門式の検問つき"""
    rev = series_pick(facts, TAGS["rev"], cutoff)
    op  = series_pick(facts, TAGS["op"], cutoff)
    tax = series_pick(facts, TAGS["tax"], cutoff)
    pre = series_pick(facts, TAGS["pre"], cutoff)
    eq  = series_pick(facts, TAGS["eq"], cutoff)
    ast = series_pick(facts, TAGS["assets"], cutoff)
    gw  = annual_rows(facts, "Goodwill", cutoff)
    debt = series_total_or_sum(facts, DEBT_TOTAL, DEBT_PARTS, cutoff)
    intan = series_total_or_sum(facts, INT_TOTAL, INT_PARTS, cutoff)
    if not rev or not op or not eq:
        return None
    y_max = max(set(rev) & set(op) & set(eq), default=None)
    if y_max is None or y_max < int(cutoff[:4]) - 2:
        return None  # 当時点で2年以上古いデータしか無い＝母集団から外す（BKNG型の年検問）
    roics, roicgs = [], []
    for y in sorted(set(op) & set(eq)):
        if y < y_max - 5:
            continue
        if y not in tax:
            if tax:  # 他の年は報告があるのにこの年だけ欠測→飛ばす（無税NOPATを作らない）
                continue
            else:
                return None  # 税が一度も取れない＝NOPAT系は算出不能
        tr = 0.0
        if y in pre and pre[y] not in (0, None) and abs(pre[y]) > 1:
            tr = max(0.0, min(0.6, tax[y] / pre[y]))
        else:
            tr = 0.25  # 税引前が無い年は実効税率25%の保守近似(注記: 厳密門式ではない——疑似バックテスト限定)
        nop = op[y] * (1 - tr)
        e = eq.get(y); d = debt.get(y, 0.0)
        g_ = gw.get(y, 0.0) if (not gw or y in gw or min(gw, default=y) > y) else None   # 他年報告ありの欠測年→skip
        i_ = intan.get(y, 0.0) if (not intan or y in intan or min(intan, default=y) > y) else None
        if e is None or g_ is None or i_ is None:
            continue
        icg = e + d
        ic = icg - g_ - i_
        base = e if e > 0 else ast.get(y, 0)
        if icg <= 0 or ic < 0.2 * max(base, 1):
            continue  # IC縮退ガード(門式と同じ物差し)
        roics.append(nop / ic * 100); roicgs.append(nop / icg * 100)
    if len(roics) < 3:
        return None
    opm = op[y_max] / rev[y_max] * 100 if rev.get(y_max) else None
    cagr = None
    ys = sorted(rev)
    if y_max - 3 in rev and rev[y_max - 3] > 0 and rev[y_max] > 0:
        cagr = ((rev[y_max] / rev[y_max - 3]) ** (1 / 3) - 1) * 100
    return {"year": y_max, "roic_med5": round(statistics.median(roics), 1),
            "roicg_med5": round(statistics.median(roicgs), 1), "n_years": len(roics),
            "opm": None if opm is None else round(opm, 1),
            "cagr3y": None if cagr is None else round(cagr, 1)}


def fwd_revenue(facts, pit_year):
    rev = series_pick(facts, TAGS["rev"], None)
    lat = max(rev, default=None)
    if lat is None or pit_year not in rev or lat <= pit_year or rev[pit_year] <= 0 or rev[lat] <= 0:
        return None
    n = lat - pit_year
    return {"to_year": lat, "years": n, "rev_cagr": round(((rev[lat] / rev[pit_year]) ** (1 / n) - 1) * 100, 1)}


def total_return(t, cutoff):
    """Yahoo adjclose(配当調整済み)月次で cutoff→現在 の年率トータルリターン"""
    try:
        j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=12y&interval=1mo"))
        res = j["chart"]["result"][0]
        ts = res["timestamp"]; adj = res["indicators"]["adjclose"][0]["adjclose"]
        import calendar
        cut_ts = calendar.timegm(tuple(map(int, cutoff.split("-"))) + (0, 0, 0, 0, 0, 0))
        pts = [(a, b) for a, b in zip(ts, adj) if b]
        p0 = next(((a, b) for a, b in pts if a >= cut_ts), None)
        p1 = pts[-1] if pts else None
        if not p0 or not p1 or p1[0] <= p0[0]:
            return None
        yrs = (p1[0] - p0[0]) / 86400 / 365.25
        if yrs < 1:
            return None
        return {"years": round(yrs, 2), "ret_cagr": round(((p1[1] / p0[1]) ** (1 / yrs) - 1) * 100, 1)}
    except Exception:
        return None


def main():
    cutoff = "2018-07-01"
    if "--cutoff" in sys.argv:
        cutoff = sys.argv[sys.argv.index("--cutoff") + 1]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    rows = json.load(open(os.path.join(BASE, "out", "score_all.json"), encoding="utf-8"))
    us = [r["t"] for r in rows if not r.get("jp")]
    if limit:
        us = us[:limit]
    cm = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in cm.values()}

    out, skipped = [], {"cik": 0, "pit": 0, "px": 0, "err": 0}
    for i, t in enumerate(us):
        c = cik.get(t.upper())
        if not c:
            skipped["cik"] += 1
            continue
        try:
            f = facts_of(c)
            pit = pit_metrics(f, cutoff)
            if not pit:
                skipped["pit"] += 1
                continue
            ret = total_return(t, cutoff)
            if not ret:
                skipped["px"] += 1
                continue
            fw = fwd_revenue(f, pit["year"])
            out.append({"t": t, "pit": pit, "ret": ret, "fwd": fw})
        except Exception as e:
            skipped["err"] += 1
        if (i + 1) % 25 == 0:
            print(f"  …{i+1}/{len(us)}（採用{len(out)}）", flush=True)

    res = {"cutoff": cutoff, "n": len(out), "skipped": skipped,
           "caveat": ("生存バイアスあり——母集団は現在の台帳に残る社のみ。倒産・被買収は消えているため"
                      "絶対水準は上に偏る。クインタイルの相対比較と成長減衰の分布にだけ使うこと。"
                      "定性欄は遡及不能＝これはΩでなく機械コアの検証"),
           "rows": out}
    op = os.path.join(BASE, "out", f"backtest_{cutoff[:4]}.json")
    json.dump(res, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ── 要約 ──
    print(f"\n疑似バックテスト cutoff={cutoff}  採用 {len(out)}社  除外 {skipped}")
    ok = [r for r in out if r["pit"]["roic_med5"] is not None]
    ok.sort(key=lambda r: r["pit"]["roic_med5"])
    if len(ok) >= 10:
        q = len(ok) // 5
        print("\n■ through-cycle ROIC(med5・当時点) 五分位 → その後の年率トータルリターン(中央値)")
        for k in range(5):
            grp = ok[k * q:(k + 1) * q] if k < 4 else ok[4 * q:]
            rets = [g["ret"]["ret_cagr"] for g in grp]
            rr = [g["pit"]["roic_med5"] for g in grp]
            print(f"  Q{k+1}: roic {min(rr):5.1f}〜{max(rr):5.1f}%  n={len(grp):3}  実現リターン中央値 {statistics.median(rets):5.1f}%/年")
    hi = [r for r in out if (r["pit"]["cagr3y"] or 0) >= 20 and r.get("fwd")]
    if hi:
        fc = sorted(x["fwd"]["rev_cagr"] for x in hi)
        print(f"\n■ g=20%上限の検証: 当時cagr3y≥20%だった {len(hi)}社の**その後の実現売上CAGR**")
        print(f"  中央値 {statistics.median(fc):.1f}% / 25-75% {fc[len(fc)//4]:.1f}〜{fc[3*len(fc)//4]:.1f}% / 20%以上を維持 {sum(1 for x in fc if x>=20)}/{len(fc)}社")
        print("  → E[r]が『20%成長がN年続く』を前提に置くときの実測の事前分布（成長減衰の較正材料）")
    print(f"\n→ {os.path.relpath(op, BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
