# night/retro_acqspend.py — 「買収の強度」をのれん残高ではなく**買収支出**で測り直す（2026-09-21新設）
#
# なぜ: gwg（のれん残高の5年増加率）は **減損・売却・為替** で汚れる。実測で Q1「買収しない」の内訳は
#   のれんが3割以上消えた群 4.0% / やや減 5.6% / ほぼ横ばい 6.0% ＝
#   **Q1の下半分は「買わなかった社」ではなく「買って償却した社」**だった。
#   支出(PaymentsToAcquireBusinessesNetOfCashAcquired)なら 0 が「本当に買っていない」を意味する。
# 実行: python3 night/retro_acqspend.py → out/retro_acqspend.json（読むだけ・採点に不使用）
import json, os, time, datetime, urllib.request, statistics as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRS = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
SETS = {2018: ("retro_features2_2018.json", "retro_returns_2018.json", range(2014, 2019), 2013),
        2015: ("retro_features2_2015.json", "retro_returns_2015_q.json", range(2011, 2016), 2010),
        2016: ("retro_features2_2016.json", "retro_returns_2016.json", range(2012, 2017), 2011),
        2017: ("retro_features2_2017.json", "retro_returns_2017.json", range(2013, 2018), 2012),
        2019: ("retro_features2_2019.json", "retro_returns_2019.json", range(2015, 2020), 2014),
        2020: ("retro_features2_2020.json", "retro_returns_2020.json", range(2016, 2021), 2015),
        2021: ("retro_features2_2021.json", "retro_returns_2021.json", range(2017, 2022), 2016)}
_FC = {}  # 同じフレームを何度も引かない（ビンテージ間で年が重なる）


def L(p):
    d = json.load(open(os.path.join(BASE, "out", p)))
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


def frame(url):
    if url in _FC:
        return _FC[url]
    for i in range(4):
        try:
            _FC[url] = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=120).read()).get("data", [])
            return _FC[url]
        except Exception:
            if i == 3:
                _FC[url] = []
                return []
            time.sleep(2 ** i)


def main():
    sic = json.load(open(os.path.join(BASE, "out/_sic_cache.json")))
    cik = {t: int(v["cik"]) for t, v in sic.items() if v.get("cik")}
    out = {}
    for v, (ff, rf, years, basey) in SETS.items():
        pay = {}   # cik -> 5年の買収支出の合計
        gwa = {}   # cik -> 同じ窓で「のれんが増えた」証拠（＝買ってはいるのに支出行が無い社の検出）
        for y in years:
            for e in frame("https://data.sec.gov/api/xbrl/frames/us-gaap/PaymentsToAcquireBusinessesNetOfCashAcquired/USD/CY%d.json" % y):
                pay[e["cik"]] = pay.get(e["cik"], 0) + max(0.0, e["val"])
            time.sleep(0.12)
            # ⚠ 支出行を切り出さない社がある（実測 MSFT: PaymentsToAcquireBusinesses… は FY2011 で終わり、
            #   Activision 690億$ は GoodwillAcquiredDuringPeriod 51,235百万$ にしか出ない）。
            #   これを「買っていない」と読むと絶対のルール7そのもの——**別系列で汚染を数える**
            for e in frame("https://data.sec.gov/api/xbrl/frames/us-gaap/GoodwillAcquiredDuringPeriod/USD/CY%d.json" % y):
                if e["val"] > 0:
                    gwa[e["cik"]] = gwa.get(e["cik"], 0) + e["val"]
            time.sleep(0.12)
        assets = {}
        for q in (1, 2, 3, 4):
            for e in frame("https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY%dQ%dI.json" % (basey, q)):
                assets.setdefault(e["cik"], e["val"])
            time.sleep(0.12)
        R = {r["ticker"]: r["tr_cagr"] for r in L(rf) if not r.get("stale") and r.get("tr_cagr") is not None}
        rows = []
        for r in L(ff):
            t = r["ticker"]
            c = cik.get(t)
            if not c or t not in R or not assets.get(c):
                continue
            # ⚠ 支出フレームに一度も現れない社は「買っていない」か「タグ付けしていない」か
            #   区別できない。総資産は申告しているので**タグ付けはしている**＝0 と読んでよい
            #   （絶対のルール7の「上限の不等式」と同じ作法）
            rows.append((pay.get(c, 0.0) / assets[c], R[t], t, bool(gwa.get(c))))
        rows.sort()
        n = len(rows)
        zero = [x for x in rows if x[0] <= 0]
        dirty = [x for x in zero if x[3]]          # 支出0だが のれんは増えている＝**測れていない**社
        zero = [x for x in zero if not x[3]]        # 本当に一円も買っていない社だけを残す
        pos = [x for x in rows if x[0] > 0]
        med = lambda s: 100 * st.median([x[1] for x in s]) if s else None
        # 買った社だけを3等分＝「買わない / 控えめ / 中 / 大きく」の4群を支出で作る
        m = len(pos)
        tert = [pos[i * m // 3:(i + 1) * m // 3] for i in range(3)]
        lab = ["買収しない(支出0)", "控えめ", "中", "大きく買う"]
        ms = [med(zero)] + [med(x) for x in tert]
        order = sorted(range(4), key=lambda i: -(ms[i] or -99))
        print("■ %d年ビンテージ  n=%d（真の支出0 %d社 = %.0f%% ／ 支出0だがのれん増＝測れていない %d社 中央値 %s）"
              % (v, n, len(zero), 100 * len(zero) / n, len(dirty),
                 ("%.1f%%" % med(dirty)) if dirty else "—"))
        for i, (l, mm) in enumerate(zip(lab, ms)):
            rng = "" if i == 0 else "  支出/総資産 %.3f..%.3f" % (tert[i - 1][0][0], tert[i - 1][-1][0])
            print("   %-16s n=%3d  中央値 %.1f%%%s" % (l, len(zero) if i == 0 else len(tert[i - 1]), mm, rng))
        print("   → 最良 %s ／ 最悪 %s\n" % (lab[order[0]], lab[order[3]]))
        out[str(v)] = {"n": n, "zero_n": len(zero), "dirty_n": len(dirty),
                       "dirty_median_cagr_pct": round(med(dirty), 1) if dirty else None, "labels": lab,
                       "median_cagr_pct": [round(x, 1) for x in ms],
                       "best": lab[order[0]], "worst": lab[order[3]]}
    p = os.path.join(BASE, "out/retro_acqspend.json")
    json.dump({"generated": datetime.date.today().isoformat(),
               "note": "買収支出(PaymentsToAcquireBusinessesNetOfCashAcquired の5年合計)÷期初総資産。のれん残高と違い減損・売却・為替で汚れない",
               "vintages": out}, open(p, "w"), ensure_ascii=False, indent=1)
    print("→", p)


if __name__ == "__main__":
    main()
