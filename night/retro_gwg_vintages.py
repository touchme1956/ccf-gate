# night/retro_gwg_vintages.py — のれん増加率(gwg)を 2013/2015 ビンテージでも作る（2026-09-21新設）
#
# 目的: `out/retro_features_2018.json` にしか `gwg`（のれん増加率＝5年）が無く、
#   「買収の多寡と実現リターンの逆U字」（docs/CLAUDE_ARCHIVE.md:3541）が
#   **2018年の一窓だけ**の形だった。採点へ焼き付ける前に、別のビンテージで同じ形が出るかを測る。
#
# 採取: SEC XBRL **frames** API（companyfacts.zip 1.4GB を落とさずに済む）。
#   us-gaap/Goodwill/USD/CY{y}Q{q}I.json を年4本ずつ取り、各社の **fy_end** に最も近い
#   instant を採る（±45日）。決算期が12月でない社も拾える（実測: AAR CORP 2013-11-30）。
# 規約は 2018 版(night/retro_features_2018.py:135)とそろえる——
#   **基準年ののれんが >0 のときだけ** gwg を定義する（0除算を避けるため。
#   ＝「のれんが最初から無い社」は gwg を持たない。この非対称は 2018 版から引き継ぐ）。
# 実行: python3 night/retro_gwg_vintages.py → out/retro_gwg_vintages.json
import json, os, sys, time, datetime, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRS = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
WIN = 45  # fy_end との許容日数


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def L(p):
    d = json.load(open(os.path.join(BASE, p)))
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


def frame(y, q):
    u = "https://data.sec.gov/api/xbrl/frames/us-gaap/Goodwill/USD/CY%dQ%dI.json" % (y, q)
    for i in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=120)
            return json.loads(r.read()).get("data", [])
        except Exception as e:
            if i == 3:
                print("  ! %d Q%d: %s" % (y, q, e))
                return []
            time.sleep(2 ** i)


def main():
    sic = json.load(open(os.path.join(BASE, "out/_sic_cache.json")))
    cik = {t: int(v["cik"]) for t, v in sic.items() if v.get("cik")}
    SETS = {
        2013: ("out/retro_features2_2013.json", "out/retro_returns_2013_all.json"),
        2015: ("out/retro_features2_2015.json", "out/retro_returns_2015_q.json"),
        2016: ("out/retro_features2_2016.json", "out/retro_returns_2016.json"),
        2017: ("out/retro_features2_2017.json", "out/retro_returns_2017.json"),
        2018: ("out/retro_features2_2018.json", "out/retro_returns_2018.json"),
        2019: ("out/retro_features2_2019.json", "out/retro_returns_2019.json"),
        2020: ("out/retro_features2_2020.json", "out/retro_returns_2020.json"),
        2021: ("out/retro_features2_2021.json", "out/retro_returns_2021.json"),
    }
    # 必要な暦年を集める
    need, meta = set(), {}
    for v, (ff, _) in SETS.items():
        for r in L(ff):
            t = r["ticker"]
            if t not in cik or not r.get("fy") or not r.get("fy_end"):
                continue
            meta.setdefault(v, {})[t] = (cik[t], int(r["fy"]), d2(r["fy_end"]))
            need.add(int(r["fy"]))
            need.add(int(r["fy"]) - 5)
    print("暦年 %d本 × 4四半期 = %d フレーム" % (len(need), 4 * len(need)))
    # cik -> {date: goodwill}
    gw = {}
    for y in sorted(need):
        for q in (1, 2, 3, 4):
            for e in frame(y, q):
                gw.setdefault(e["cik"], {})[e["end"]] = e["val"]
            time.sleep(0.12)
        print("  %d 取得済 (社数 %d)" % (y, len(gw)))

    def at(c, target):
        m = gw.get(c)
        if not m:
            return None
        best = None
        for s, v in m.items():
            dd = abs((d2(s) - target).days)
            if dd <= WIN and (best is None or dd < best[0]):
                best = (dd, v)
        return best[1] if best else None

    out = {}
    for v, mp in meta.items():
        res = {}
        for t, (c, fy, fe) in mp.items():
            try:
                base = fe.replace(year=fe.year - 5)
            except ValueError:
                base = fe.replace(year=fe.year - 5, day=28)
            g1, g0 = at(c, fe), at(c, base)
            if g1 is not None and g0 and g0 > 0:
                res[t] = g1 / g0 - 1.0
        out[str(v)] = res
        print("ビンテージ %d: gwg を作れた社 %d / %d" % (v, len(res), len(mp)))
    p = os.path.join(BASE, "out/retro_gwg_vintages.json")
    json.dump({"generated": datetime.date.today().isoformat(),
               "note": "SEC frames(us-gaap/Goodwill)から各社のfy_end±45日で採取。基準年のれん>0の社のみ",
               "gwg": out}, open(p, "w"), ensure_ascii=False, indent=1)
    print("→", p)


if __name__ == "__main__":
    main()
