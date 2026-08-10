# night/scan_irr85_universe.py — 全上場企業から「顧客側の再認定型の堀」を探す（2026-08-05新設）
#
# 背景: 2026-08-05の歴史検証で、途中乗りの継続組（後半も年率15%+）を事前に分けた唯一の変数が
#   irr=85（顧客側の再認定が要る型）だと判った（統合177社 P=0.71・等加重+24.6%/年 vs SPY15.0%）。
#   ならば **門の中の350社だけでなく、市場全体からこの型を探す** のが筋になる。
#
# 方法（検索を逆向きにする）: 1社ずつ照会すると全上場で10時間かかる。EDGAR全文検索を
#   **フレーズ側から引いて**該当企業を全部回収する（5,700件≒600リクエスト≒3分）。
#   フレーズは歴史で勝った16社の引用から抽出した「顧客が動かねばならない」語に限定する
#   ——CWの 'certification under customer quality requirements' を初版で取りこぼした反省から、
#   願望形・逆方向（自社が仕入先を認定する側）も別カテゴリで拾って後段で仕分ける。
#
# 出力: out/irr85_universe.json（CIK→{ticker, name, phrases, sic}）
# 実行: python3 night/scan_irr85_universe.py [--days 1200] [--forms 10-K,20-F]
#
# 2026-08-10: **フレーズ表を他の道具から読めるようにした**（`if __name__` で本体を包んだだけ・
#   走らせたときの挙動は不変）。night/watch_new_listings.py が STRONG/MED/ASPIR と fetch() を
#   そのまま呼ぶ——フレーズ表を書き写すと、片方を直したときにもう片方が取り残される（v9.9.65の掟）。
#   あわせて **--forms** を可変にした。旧実装は `forms=10-K,20-F` の決め打ちで、
#   **S-1・424B4（IPO目論見書）を一度も掛けていなかった**＝上場初年度の会社が構造的に網の外だった。
import json, os, sys, time, re, urllib.request, urllib.parse, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "CCF-Omega-Screener fortis5280@gmail.com"}
DAYS = 1200
FORMS = "10-K,20-F"
for i, a in enumerate(sys.argv):
    if a == "--days" and i + 1 < len(sys.argv):
        DAYS = int(sys.argv[i + 1])
    if a == "--forms" and i + 1 < len(sys.argv):
        FORMS = sys.argv[i + 1]
END = datetime.date.today()
START = END - datetime.timedelta(days=DAYS)

# 機構を示す語（歴史で勝った側）。weight=強さ
STRONG = {  # 顧客側が再認定・再試験をやり直す必要を直接述べる
    "qualified by our customers": 3, "customer re-formulation": 3,
    "maintains that selection": 3, "certify another supplier": 3,
    "barriers to subsequent supplier": 3, "qualified for the application": 3,
    "certification under customer": 3, "customers must generate": 3,
    "re-qualification": 2, "requalification": 2, "lengthy qualification": 2,
    "stringent qualification": 2, "qualification period": 2,
}
MED = {  # 設計組込・認定の一般語（文脈次第で機構になる）
    "design win": 1, "design-in": 1, "designed into our customers": 2,
    "qualification requirements": 1, "qualification process": 1,
    "qualified suppliers": 1, "approved supplier": 1, "qualify our products": 1,
}
ASPIR = {  # 願望形（歴史ではP=0.40）——別カテゴリで記録し混ぜない
    "strive to differentiate": 0, "ability to achieve qualification": 0,
    "evaluating and qualifying": 0,
}
ALL = {**STRONG, **MED, **ASPIR}


def fetch(q, frm=0, forms=None, start=None, end=None):
    u = ("https://efts.sec.gov/LATEST/search-index?q=" + urllib.parse.quote(f'"{q}"')
         + f"&forms={urllib.parse.quote(forms or FORMS)}"
         + f"&startdt={start or START}&enddt={end or END}&from={frm}")
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.2 * (a + 1))
    return None


CIKRE = re.compile(r"\(CIK (\d{10})\)")
TKRE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,5})\)\s+\(CIK")

if __name__ == "__main__":   # ← 本体。import されたときは走らせない（フレーズ表を共有するため）
    hits = {}   # cik -> {'name','ticker','ph':{phrase:count},'sic'}
    for ph, w in ALL.items():
        j = fetch(ph)
        if not j:
            print(f"  {ph:34s} 取得失敗")
            continue
        total = j["hits"]["total"]["value"]
        if total == 0:
            print(f"  {ph:34s}      0件")
            continue
        got, frm = 0, 0
        while frm < min(total, 9990):
            jj = j if frm == 0 else fetch(ph, frm)
            if not jj:
                break
            for h in jj["hits"]["hits"]:
                src = h.get("_source", {})
                ciks = src.get("ciks") or []
                names = src.get("display_names") or []
                for k, c in enumerate(ciks):
                    c = str(c).zfill(10)
                    nm = names[k] if k < len(names) else ""
                    d = hits.setdefault(c, {"name": nm, "ticker": None, "ph": {}, "sic": None})
                    if not d["name"] and nm:
                        d["name"] = nm
                    m = TKRE.search(nm)
                    if m and not d["ticker"]:
                        d["ticker"] = m.group(1)
                    d["ph"][ph] = d["ph"].get(ph, 0) + 1
                got += 1
            frm += 10
            time.sleep(0.22)
        print(f"  {ph:34s} {total:6d}件 → 企業累計 {len(hits)}")

    # 強度スコア: 機構語の重みの合計（願望形は0）
    for c, d in hits.items():
        d["score"] = sum(ALL.get(p, 0) for p in d["ph"])
        d["strong"] = [p for p in d["ph"] if p in STRONG]
        d["aspir"] = [p for p in d["ph"] if p in ASPIR]

    path = os.path.join(BASE, "out", "irr85_universe.json")
    json.dump({"generated": END.isoformat(), "window": f"{START}..{END}", "forms": FORMS,
               "note": f"全上場企業のEDGAR全文検索（forms={FORMS}）。機構語(STRONG)の有無で候補を仕分ける。"
                       "SEC提出書類のみ＝日本株は対象外（EDINETは別経路）",
               "n": len(hits), "phrases": {"strong": list(STRONG), "med": list(MED),
                                           "aspir": list(ASPIR)},
               "rows": [{"cik": c, **d} for c, d in
                        sorted(hits.items(), key=lambda kv: -kv[1]["score"])]},
              open(path, "w"), ensure_ascii=False, indent=1)
    ns = sum(1 for d in hits.values() if d["strong"])
    print(f"\n■ {path}  企業 {len(hits)}社／うち機構語(STRONG)あり {ns}社")
