#!/usr/bin/env python3
# night/retro_build_readlist.py — irr=85 の追試（2013/2015ビンテージ）の読解リストを作る（2026-08-05新設）
#
# 2018年ビンテージで見つかった「irr=85＝顧客の側が再認定をやり直す型」が
# 別のビンテージでも立つかを検証するための、**読む原本の一覧**を機械的に組む。
#
# look-ahead を構造で防ぐ:
#   ・その社の 10-K/20-F のうち **filingDate ≤ asof(7/1)** の最新のものだけを採る。
#     決算期末ではなく**提出日**で切るのが肝（12月決算社のFY2012は2013-02提出なので可、
#     FY2013は2014-02提出なので不可）。
#   ・リターンは一覧に**入れない**。読解班には結末を一切渡さない。
#
# 標本の取り方（事前登録・2018年の反省を反映）:
#   2018年の読解は「ティッカーのアルファベット順で先頭から140社」で打ち切られ、
#   R〜Zに該当型がほとんど無いという偏りを残した。今回は**ティッカー昇順に並べて
#   等間隔で抜く**（systematic sampling）ので、標本はA〜Zに散る。
#
# 使い方:
#   python3 night/retro_build_readlist.py --asof 2013 --n 120
#   python3 night/retro_build_readlist.py --asof 2015 --n 164
# 出力: out/retro_readlist_{asof}.json
import json, os, sys, time, urllib.request, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
CACHE = os.path.join(OUT, "_subs_cache")
EMAIL = "fortis5280@gmail.com"
HD = {"User-Agent": f"hachimon-gate {EMAIL}"}
FORMS = {"10-K", "20-F", "10-K405", "10-KSB"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HD), timeout=120).read()


def cached(p, url):
    """壊れたキャッシュ（中断で0バイト等）は読まずに取り直す＝ルール7の作法"""
    for _ in range(2):
        if os.path.exists(p) and os.path.getsize(p) > 200:
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                os.remove(p)
        tmp = p + ".part"
        open(tmp, "wb").write(get(url))
        os.replace(tmp, p)
        time.sleep(0.12)
    return json.load(open(p, encoding="utf-8"))


def subs(cik):
    os.makedirs(CACHE, exist_ok=True)
    return cached(os.path.join(CACHE, f"{cik}.json"),
                  f"https://data.sec.gov/submissions/CIK{cik:010d}.json")


def all_filings(cik):
    """recent + 過去分ファイルを結合して (form, filingDate, accession, primaryDocument, reportDate) を返す"""
    d = subs(cik)
    out = []

    def push(blk):
        n = len(blk.get("form", []))
        for i in range(n):
            out.append((blk["form"][i], blk["filingDate"][i], blk["accessionNumber"][i],
                        blk.get("primaryDocument", [""] * n)[i], blk.get("reportDate", [""] * n)[i]))
    f = d.get("filings", {})
    push(f.get("recent", {}))
    for extra in f.get("files", []):
        push(cached(os.path.join(CACHE, f"{cik}_{extra['name']}"),
                    f"https://data.sec.gov/submissions/{extra['name']}"))
    return out


def pick(cik, cutoff):
    """filingDate ≤ cutoff の最新の年次報告書。無ければ None"""
    best = None
    for form, filed, acc, doc, rep in all_filings(cik):
        if form not in FORMS or not filed or filed > cutoff or not doc:
            continue
        if best is None or filed > best[1]:
            best = (form, filed, acc, doc, rep)
    if not best:
        return None
    form, filed, acc, doc, rep = best
    a = acc.replace("-", "")
    return {"form": form, "filed": filed, "reportDate": rep,
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{a}/{doc}"}


def main():
    asof = int(sys.argv[sys.argv.index("--asof") + 1]) if "--asof" in sys.argv else 2013
    want = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 120
    cutoff = f"{asof}-07-01"

    rf = "retro_returns_2013_all.json" if asof == 2013 else f"retro_returns_{asof}.json"
    rows = json.load(open(os.path.join(OUT, rf), encoding="utf-8"))["rows"]
    have = {r["ticker"] for r in rows if r.get("tr_cagr") is not None}
    coh = json.load(open(os.path.join(OUT, f"retro_cohort_{asof}.json"), encoding="utf-8"))["rows"]
    cik = {}
    for r in coh:
        if r.get("ticker") and r.get("cik"):
            cik.setdefault(r["ticker"], r["cik"])
    uni = sorted(t for t in have if t in cik)
    print(f"asof={asof} リターンあり {len(have)} / CIK解決 {len(uni)}")

    # 事前登録: ティッカー昇順の等間隔抽出（A〜Zに散る・私の選択が入らない）
    N = len(uni)
    if N <= want:
        cand = uni
    else:  # 両端を含めて全域に等間隔で散らす（末尾のZ側が落ちないように）
        cand = [uni[round(i * (N - 1) / (want - 1))] for i in range(want)]
        cand = list(dict.fromkeys(cand))

    out, miss = [], []
    for i, t in enumerate(cand, 1):
        try:
            f = pick(cik[t], cutoff)
        except Exception as e:
            f = None
            print(f"  ▲{t}: {e}")
        if not f:
            miss.append(t)
            continue
        out.append({"ticker": t, "cik": cik[t], **f})
        if i % 20 == 0:
            print(f"  … {i}/{len(cand)}")
    o = {"generated": "2026-08-05", "asof": asof, "cutoff": cutoff,
         "universe": len(uni), "sampling": "ティッカー昇順・両端を含む等間隔抽出（A〜Zの全域に散る）",
         "n": len(out), "missing": miss, "rows": out}
    p = os.path.join(OUT, f"retro_readlist_{asof}.json")
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {p}（{len(out)}社・原本なし {len(miss)}社）")


if __name__ == "__main__":
    main()
