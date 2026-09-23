#!/usr/bin/env python3
# night/audit_gate0_fye.py — 門0の「決算日の錨」のずれで母集団から落ちた社を数える（2026-08-06新設）
#
# 発端: **RBC Bearings が門0の母集団2,902社に一行も無かった**（歴史検証で irr=85 が付き
#       13年で年率+20.5%を出した社）。原因は gate0_v8_5.py の錨の作り方だった——
#         fye = {年: 売上候補タグ**全部**の決算日の max}
#       RBCは Revenues が 2022-04-02、RevenueFromContractWithCustomerIncludingAssessedTax が
#       2022-04-30 で、max が**実際には使わないタグ**の28日ずれを拾う。結果 ni/ocf/equity/opinc が
#       一斉に錨と一致せず「欠損:ni」で丸ごと脱落していた。
#       ＝この台帳が繰り返し踏んでいる「基準の違う二つを突き合わせる」型（KLACの分割・ADRのper・JP門0のpt）。
#
# 是正: 錨は **pick_series が実際に採用した売上系列のタグ** の決算日から作る。
#       ふるいの条件（roic/opm/cagr等の閾値）は一切変えていない。
#
# この道具は「その是正で何社が母集団へ戻るか」を全社スキャンで実測する。
# 実行: python3 night/audit_gate0_fye.py [--limit N]
# 出力: out/audit_gate0_fye.json
import json, os, sys, zipfile, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
ZIP = os.path.join(BASE, "companyfacts.zip")

ns = {"__name__": "_x", "__file__": os.path.join(BASE, "gate0_v8_5.py")}
src = open(os.path.join(BASE, "gate0_v8_5.py"), encoding="utf-8").read()
try:
    exec(src.split("z = zipfile")[0], ns)
except SystemExit:
    pass
except Exception as e:  # noqa: BLE001
    print("(注)", type(e).__name__, e)

collect, pick_series, evaluate = ns["collect"], ns["pick_series"], ns["evaluate"]
derive_opinc, d2 = ns["derive_opinc"], ns["d2"]
Y, STALE, CIK2TK = ns["YEARS"], ns["STALE_DAYS"], ns["CIK2TK"]
TODAY = ns["TODAY"]
STOCK = {"equity", "debt_lt", "debt_st", "cash", "gw"}


def resolve(facts, yrs, unit, fye):
    """その錨で ni/ocf/equity/opinc が全部取れるか"""
    def grab(k, zero=False):
        v, _, _ = pick_series(collect(facts, k), yrs, unit_lock=unit, fye=fye, stock=(k in STOCK))
        if v is None and zero:
            return [0.0] * Y
        return v
    ni, ocf, eq = grab("ni"), grab("ocf"), grab("equity")
    op = grab("opinc") or derive_opinc(facts, yrs, unit, fye)
    return all([ni, ocf, eq, op]), (ni, ocf, eq, op, grab("capex", True), grab("debt_lt", True), grab("debt_st", True))


def main():
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    if not os.path.exists(ZIP):
        sys.exit("companyfacts.zip が無い（年1回の門0と同じ前提）")
    z = zipfile.ZipFile(ZIP)
    names = [n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json")]
    if lim:
        names = names[:lim]
    stat = collections.Counter()
    rescued, changed = [], []
    for i, name in enumerate(names, 1):
        if i % 500 == 0:
            print(f"  {i}/{len(names)} 錨ずれ{stat['anchor_diff']} 復活{len(rescued)}", flush=True)
        try:
            cik = int(name[3:13])
        except Exception:
            continue
        tkr = CIK2TK.get(cik)
        if not tkr:
            continue
        try:
            facts = json.loads(z.read(name)).get("facts", {})
        except Exception:
            continue
        rev_c = collect(facts, "revenue")
        if not rev_c:
            continue
        best = None
        for unit in dict.fromkeys(u for (_, u, _) in rev_c):
            ys = sorted({y for (_, uu, d) in rev_c if uu == unit for y in d})
            if len(ys) < Y:
                continue
            yrs = ys[-Y:]
            v, _, lin = pick_series(rev_c, yrs, unit_lock=unit)
            if v is None:
                continue
            if best is None or yrs[-1] > best[1][-1]:
                best = (v, yrs, unit, lin)
        if not best:
            continue
        v, yrs, unit, lin = best
        old = {y: max(d[y][0] for (_, uu, d) in rev_c if uu == unit and y in d) for y in yrs}
        used = set((lin or "").split("+"))
        new = {y: max(d[y][0] for (t, uu, d) in rev_c if uu == unit and y in d and (not used or t in used)) for y in yrs}
        stat["scanned"] += 1
        if old == new:
            continue
        stat["anchor_diff"] += 1
        if (TODAY - d2(new[yrs[-1]])).days > STALE:
            stat["stale"] += 1
            continue
        ok_old, _ = resolve(facts, yrs, unit, old)
        ok_new, vals = resolve(facts, yrs, unit, new)
        rec = {"ticker": tkr, "cik": cik, "lineage": lin,
               "fye_old": old[yrs[0]], "fye_new": new[yrs[0]], "years": yrs}
        if ok_new and not ok_old:
            m, err = evaluate(v, vals[3], vals[0], vals[1], vals[4], vals[2], vals[5], vals[6])
            rec["score"] = None if err else m["score"]
            rec["fails"] = err or m["fails"]
            rescued.append(rec)
            stat["rescued"] += 1
        else:
            changed.append(rec)
            stat["diff_but_ok"] += 1
    o = {"generated": __import__("datetime").date.today().isoformat(), "first_run": "2026-08-06", "stat": dict(stat),
         "note": "錨=売上候補タグ全部のmax → 採用系列のタグのみ、へ是正した影響。ふるいの条件は不変",
         "rescued": sorted(rescued, key=lambda r: -(r.get("score") or 0)),
         "anchor_diff_but_resolved": changed[:200]}
    p = os.path.join(OUT, "audit_gate0_fye.json")
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n走査 {stat['scanned']}社 / 錨がずれていた {stat['anchor_diff']}社 / "
          f"**母集団へ復活 {stat['rescued']}社** / ずれても取れていた {stat['diff_but_ok']}社")
    for r in o["rescued"][:25]:
        print(f"  {r['ticker']:6} score={r.get('score')} {str(r.get('fails'))[:40]:42} 錨 {r['fye_old']}→{r['fye_new']}")
    print(f"→ {p}")


if __name__ == "__main__":
    main()
