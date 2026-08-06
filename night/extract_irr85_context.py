# night/extract_irr85_context.py — 機構語の「前後の文」を全候補から機械で抜く（2026-08-05新設）
#
# scan_irr85_universe.py は語の有無しか見ていない。'requalification' は半導体の工程再認定でも
# REITの税制資格でも使われるので、**文脈を見ないと機構かどうか判らない**。
# 候補社の最新10-K/20-Fを取り、機構語の前後±420字を抜いて out/irr85_context.json へ。
# 判定（機構か否か）は後段の読解に回す——ここは採取だけ。
#
# 実行: python3 night/extract_irr85_context.py [--limit N]
import json, os, sys, re, html, time, urllib.request, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "CCF-Omega-Screener fortis5280@gmail.com"}
LIMIT = None
for i, a in enumerate(sys.argv):
    if a == "--limit" and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

U = json.load(open(os.path.join(BASE, "out", "irr85_universe.json")))
rows = [r for r in U["rows"] if r.get("strong")]
if LIMIT:
    rows = rows[:LIMIT]
print(f"対象 {len(rows)}社")

OUT = os.path.join(BASE, "out", "irr85_context.json")
done = {}
if os.path.exists(OUT):
    done = {r["cik"]: r for r in json.load(open(OUT))["rows"]}
    print(f"  既存 {len(done)}社はスキップ")


def latest_doc(cik):
    u = f"https://data.sec.gov/submissions/CIK{cik}.json"
    j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read())
    r = j["filings"]["recent"]
    for i, f in enumerate(r["form"]):
        if f in ("10-K", "20-F"):
            return (f, r["filingDate"][i], r["accessionNumber"][i].replace("-", ""),
                    r["primaryDocument"][i], j.get("sic"), j.get("sicDescription"))
    return None


def plain(cik, acc, doc):
    u = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
    raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read()
    t = raw.decode("utf8", "ignore")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


res = list(done.values())
for n, r in enumerate(rows, 1):
    if r["cik"] in done:
        continue
    try:
        d = latest_doc(r["cik"])
        time.sleep(0.15)
        if not d:
            res.append({**{k: r[k] for k in ("cik", "ticker", "name")}, "err": "no10k"})
            continue
        tx = plain(r["cik"], d[2], d[3])
        time.sleep(0.15)
        ctx = []
        for ph in r["strong"]:
            for m in list(re.finditer(re.escape(ph), tx, re.I))[:2]:
                ctx.append({"ph": ph, "s": tx[max(0, m.start() - 420):m.start() + 420]})
        res.append({"cik": r["cik"], "ticker": r.get("ticker"),
                    "name": (r.get("name") or "").split("  (")[0],
                    "form": d[0], "filed": d[1], "sic": d[4], "sicDesc": d[5],
                    "phrases": r["strong"], "ctx": ctx})
    except Exception as e:
        res.append({"cik": r["cik"], "ticker": r.get("ticker"), "err": str(e)[:80]})
    if n % 10 == 0:
        print(f"  {n}/{len(rows)}  採取{len(res)}")
        json.dump({"generated": datetime.date.today().isoformat(), "n": len(res), "rows": res},
                  open(OUT, "w"), ensure_ascii=False, indent=1)

json.dump({"generated": datetime.date.today().isoformat(), "n": len(res), "rows": res},
          open(OUT, "w"), ensure_ascii=False, indent=1)
ok = sum(1 for r in res if r.get("ctx"))
print(f"■ {OUT}  {len(res)}社（文脈が取れた {ok}社）")
