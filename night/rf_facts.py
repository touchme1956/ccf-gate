#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rf_facts.py — Bloomberg Reformers Index（＝Smart-i Pro 米国リブート75 の対象指数）の再現・段1
（SEC の四半期から『直近12か月(LTM)の純利益・営業利益・売上』を、提出日基準で作る・リターンは見ない）

事前登録: out/reformers_prereg.json（この道具は判定を持たない。測る前に固定した規則はそちらにある）
規則の原文: Bloomberg「Bloomberg Reformers Index Methodology」2026年2月（out/reformers_method.txt に全文を写した）

作るもの（companyfacts.zip の 1周・us-gaap の 10-K/10-Q 提出社だけ）:
  各社について、純利益(ni)・営業利益(oi)・売上(rev) の『期間の事実』を、(開始日, 終了日) ごとに
  提出のたびの値〔提出日つき・改訂を全部残す〕として保存する。
  → 組み立て側（rf_replicate.py）が任意の日付 S で『S までに提出されたものだけ』を使い、
     四半期（3か月）の値を、直接の3か月の事実 or 累計(YTD)の差で作り、LTM を4四半期の和で作る。

タグの族（期間ごとに先頭から探す＝事実が無い期間だけ次のタグへ落ちる）:
  ni  : NetIncomeLoss → NetIncomeLossAvailableToCommonStockholdersBasic → ProfitLoss
  oi  : OperatingIncomeLoss
  rev : Revenues → RevenueFromContractWithCustomerExcludingAssessedTax → RevenueFromContractWithCustomerIncludingAssessedTax
        → SalesRevenueNet → SalesRevenueGoodsNet → RevenuesNetOfInterestExpense
期間の長さ: 3か月(80-100日)・6か月(170-200)・9か月(260-290)・12か月(350-380) だけ残す。
形式: 10-Q・10-K・10-KT とその訂正（/A）。20-F・40-F（ifrs-full）の社は対象外（Bloomberg の米国指数は米国の発行体）。

株数・浮動株: dei の EntityCommonStockSharesOutstanding（sh・種類株は同じ提出・同じ日の値を足す）と
EntityPublicFloat（pf）を提出日つきで全部残す。表紙の株数が無い社の代わりに、貸借対照表の
CommonStockSharesOutstanding（bs・足す）と基本加重平均株数（wa・最大）も残す
（時価総額の資格の判定に、組み立て側が S までのものだけ使う。優先は sh → bs → wa）。

使い方:
  python3 night/rf_facts.py --only MU,NVDA,HOOD,DUOL,PLTR,UBER    # 数社だけ（出力は .partial）
  python3 night/rf_facts.py                                       # 全社
出力: out/_rf_facts.json.gz（大きいのでコミットしない・.gitignore へ）
"""
import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import zipfile
from multiprocessing import Pool

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
ZIP = os.path.join(BASE, "companyfacts.zip")

FORMS = {"10-Q", "10-K", "10-KT", "10-Q/A", "10-K/A", "10-KT/A"}
TAGS = {
    "ni": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
    "oi": ["OperatingIncomeLoss"],
    # 営業利益の事実が無い社（証券・銀行・保険など。Robinhood は 0 行）の代わり＝税引前利益（事後の感度 V1pt にだけ使う）
    "pt": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
           "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
            "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense"],
}
LEN_OK = ((80, 100), (170, 200), (260, 290), (350, 380))


def _d(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def group_rows(g, tags):
    """期間ごとに（先頭のタグから）提出の系列を作る → {(start,end): [(filed,val,form), …]（提出日昇順・値が変わったものだけ）}"""
    per = {}
    for pri, tag in enumerate(tags):
        rows = ((g.get(tag) or {}).get("units") or {}).get("USD") or []
        for r in rows:
            if r.get("form") not in FORMS or not r.get("start") or not r.get("end") or not r.get("filed"):
                continue
            v = _num(r.get("val"))
            if v is None:
                continue
            try:
                dd = (_d(r["end"]) - _d(r["start"])).days
            except Exception:  # noqa
                continue
            if not any(a <= dd <= b for a, b in LEN_OK):
                continue
            per.setdefault((r["start"], r["end"]), {}).setdefault(pri, []).append((r["filed"], float(v), r["form"]))
    out = {}
    for k, byp in per.items():
        p0 = min(byp)                       # その期間で使えた最も優先のタグ
        seq = sorted(byp[p0])
        keep, last = [], None
        for f, v, fm in seq:
            if last is None or v != last:
                keep.append([f, v])
                last = v
        out[k] = keep
    return out


def cover_rows(dei, tag, unit, add):
    """dei の表紙の値を提出日つきで返す。add=True は同じ提出(accn)・同じ終了日の別の値（種類株）を足す"""
    rows = ((dei.get(tag) or {}).get("units") or {}).get(unit) or []
    by = {}
    for r in rows:
        if _num(r.get("val")) is None or not r.get("filed") or not r.get("end"):
            continue
        by.setdefault((r["filed"], r["end"], r.get("accn")), set()).add(float(r["val"]))
    out = []
    for (f, e, _a), vals in sorted(by.items()):
        out.append([f, e, sum(vals) if add else max(vals), len(vals)])
    # 同じ提出日の重複は最後だけ
    ded = {}
    for x in out:
        ded[x[0]] = x
    return [ded[k] for k in sorted(ded)]


_Z = None


def _init():
    global _Z
    _Z = zipfile.ZipFile(ZIP)


def work(name):
    try:
        fc = json.loads(_Z.read(name))
    except Exception as e:  # noqa
        return name, {"why": f"読めない: {type(e).__name__}"}
    facts = fc.get("facts") or {}
    g = facts.get("us-gaap")
    if not g:
        return name, {"why": "us-gaap なし（IFRS/20-F 等）"}
    res = {"cik": fc.get("cik"), "name": fc.get("entityName")}
    for k, tags in TAGS.items():
        gr = group_rows(g, tags)
        res[k] = [[s, e, seq] for (s, e), seq in sorted(gr.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    if not res["ni"]:
        return name, {"why": "純利益の事実なし"}
    dei = facts.get("dei") or {}
    res["sh"] = cover_rows(dei, "EntityCommonStockSharesOutstanding", "shares", True)
    res["pf"] = cover_rows(dei, "EntityPublicFloat", "USD", False)
    # 表紙の株数が無い社（種類株を別々に書く Palantir・Duolingo 等）の代わり: 貸借対照表の発行済株数と基本加重平均株数
    res["bs"] = cover_rows(g, "CommonStockSharesOutstanding", "shares", True)
    res["wa"] = cover_rows(g, "WeightedAverageNumberOfSharesOutstandingBasic", "shares", False)
    # 最初と最後の提出（消えた社の目安）
    fl = [seq[0][0] for _s, _e, seq in res["ni"]] + [seq[-1][0] for _s, _e, seq in res["ni"]]
    res["first_filed"], res["last_filed"] = min(fl), max(fl)
    return name, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="ティッカーではなく CIK（カンマ区切り）。数社の確認用")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    z = zipfile.ZipFile(ZIP)
    names = sorted(n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json"))
    if a.only:
        ciks = {int(x) for x in a.only.split(",")}
        names = [n for n in names if int(n[3:13]) in ciks]
    t0 = time.time()
    res, skip = {}, {}
    with Pool(a.procs, initializer=_init) as pool:
        for i, (n, r) in enumerate(pool.imap_unordered(work, names, chunksize=16), 1):
            cik = str(int(n[3:13]))
            if "why" in r:
                skip[r["why"]] = skip.get(r["why"], 0) + 1
            else:
                res[cik] = r
            if i % 2000 == 0:
                print(f"   {i}/{len(names)}  {time.time() - t0:.0f}s  採用{len(res)}", flush=True)
    p = os.path.join(OUT, "_rf_facts.partial.json.gz" if a.only else "_rf_facts.json.gz")
    with gzip.open(p + ".tmp", "wt") as f:
        json.dump({"built": datetime.date.today().isoformat(), "skip": skip, "firms": res}, f)
    os.replace(p + ".tmp", p)
    print(f"■ {len(res)}社 採用／除外 {skip}／{time.time() - t0:.0f}s → {p} ({os.path.getsize(p) / 1e6:.1f}MB)")


if __name__ == "__main__":
    main()
