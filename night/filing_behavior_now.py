# night/filing_behavior_now.py — 今日の投下可・次点に「提出書類の振る舞い」を当てる（2026-08-12新設）
#
# ⚠ 判定には一切使わない。歴史検証（night/filing_behavior_test.py）で
#    **主指標（複利15%+）は14本すべて不合格**、左尾の差も**大型株では消える**と実測済み。
#    ここは「今日の顔ぶれに綻びの痕跡があるか」を人が見るための表示専用。
#
# ⚠ カウントは「綻び」と「事務」を区別できない。実測の3例——
#    RBC 8-K 4.02(2022-08) は**本物の修正再表示**（CEO/COOの株式報酬の認識時期・FY2020-22を restate）／
#    LRCX 8-K 4.01(2025-09) は**通常の監査人交代**（EY→KPMG・disagreement も reportable event も無しと明記）／
#    IRMD 10-K/A(2025-09) は**906条証明の添付漏れの訂正**。
#    ＝件数が立ったら原本を読むまで何も言えない（irr=85 と同じ）。
#
# 出力: out/filing_behavior_now.json ／ 実行: python3 night/filing_behavior_now.py

import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))
import filing_behavior as fb  # noqa: E402

KEYS = ["age_yrs", "lag10k", "lag_d", "nt", "nonrel", "audchg", "amend", "exec5", "d13d", "k8", "shelf"]


def cikmap(tickers):
    m = {r["ticker"]: r["cik"] for r in json.load(open(os.path.join(OUT, "retro_sic.json")))["rows"]}
    need = [t for t in tickers if t not in m]
    if need:
        ct = fb.paced_get("https://www.sec.gov/files/company_tickers.json") or {}
        by = {v["ticker"]: v["cik_str"] for v in ct.values()}
        for t in need:
            if t in by:
                m[t] = by[t]
    return m


def main():
    rows = json.load(open(os.path.join(OUT, "score_all.json")))
    buy = [r["t"] for r in rows if r.get("buy")]
    nxt = [r["t"] for r in rows if r.get("quali") and not r.get("buy")]
    jp = {r["t"] for r in rows if r.get("jp")}
    asof = datetime.date.today().isoformat()
    cm = cikmap([t for t in buy + nxt if t not in jp])

    out, holes = [], []
    for t in buy + nxt:
        kind = "投下可" if t in buy else "次点"
        if t in jp:
            holes.append({"t": t, "kind": kind, "why": "日本株＝SEC経路の外（EDINET未実装）"})
            continue
        cik = cm.get(t)
        if not cik:
            holes.append({"t": t, "kind": kind, "why": "CIK不明"})
            continue
        r = fb.collect(cik, asof)
        if not r or not r.get("fetched"):
            holes.append({"t": t, "kind": kind, "why": "SEC submissions を取得できず"})
            continue
        rec = {"t": t, "kind": kind, "cik": cik, "name": r.get("name")}
        rec.update({k: r.get(k) for k in KEYS})
        # 20-F/40-F 提出体は 10-K 系が無いのでラグが原理的に出ない（欠測を0と読まない）
        if r.get("lag10k") is None:
            rec["lag_note"] = "10-K系の提出が無い（20-F/40-F等）＝提出ラグは測れない"
        rec["flags"] = [k for k in ("nt", "nonrel", "audchg", "amend") if (r.get(k) or 0) >= 1]
        out.append(rec)

    json.dump({"generated": asof, "note": "表示専用・判定に不使用。件数は綻びと事務を区別しない＝立ったら原本を読む",
               "rows": out, "holes": holes},
              open(os.path.join(OUT, "filing_behavior_now.json"), "w"), ensure_ascii=False, indent=1)

    print(f"asof={asof}  ※日本株{len([h for h in holes if 'SEC経路' in h['why']])}社は対象外（穴として明示）\n")
    print(f"{'銘柄':<7}{'区分':<7}{'年齢':>4}{'ラグ':>5}{'Δラグ':>6}{'NT':>4}{'4.02':>5}{'4.01':>5}{'10-K/A':>7}{'5.02':>5}{'13D':>4}  印")
    for r in out:
        lag = r["lag10k"] if r["lag10k"] is not None else "--"
        ld = r["lag_d"] if r["lag_d"] is not None else "--"
        print(f"{r['t']:<7}{r['kind']:<7}{r['age_yrs']:>4.0f}{str(lag):>5}{str(ld):>6}"
              f"{r['nt']:>4}{r['nonrel']:>5}{r['audchg']:>5}{r['amend']:>7}{r['exec5']:>5}{r['d13d']:>4}  "
              f"{'/'.join(r['flags'])}")
    for h in holes:
        print(f"  ⚠ {h['t']}（{h['kind']}）: {h['why']}")


if __name__ == "__main__":
    main()
