#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""つみたて投資枠の候補（S&P500 / MSCI ACWI）を 信託報酬 と 実際の連動 で並べる。

出典は **投資信託協会 投信総合検索ライブラリー**（https://toushin-lib.fwg.ne.jp/）の
検索API `/FdsWeb/FDST999900/fundDataSearch` ——画面の DataTables がそのまま叩いている経路。
値は運用会社が協会へ提出したもので、ベンダーの推計ではない。

なぜこの一本で足りるか:
  - trustReward        = 信託報酬（年率・税抜%）＋ 委託/販売/受託の内訳
  - standardPriceRaNy  = 基準価額騰落率（1y/3y/5y/10y/20y・**全ファンド同じ基準日**）
  同じ指数を追う群の中では、この騰落率の差＝費用＋連動のズレの合計＝実際に手元へ残った差。
  信託報酬は「名目の費用」、騰落率の差は「実際に引かれた総額」。**両方を並べる**。

⚠ 母集団は out/tsumitate_lineup.json（金融庁の届出一覧）。ここに無い商品は扱わない。
⚠ 引けなかった項目は **未取得** と書く（推測で埋めない＝絶対のルール7）。
"""
import json, os, re, sys, time, unicodedata
import urllib.request, urllib.parse, http.cookiejar

BASE = "https://toushin-lib.fwg.ne.jp"
TOP  = BASE + "/FdsWeb/FDST000000"
API  = BASE + "/FdsWeb/FDST999900/fundDataSearch"
UA   = "ccf-gate/1.0 (personal portfolio research; fortis5280@gmail.com)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINEUP = os.path.join(ROOT, "out", "tsumitate_lineup.json")
OUT    = os.path.join(ROOT, "out", "tsumitate_funds.json")

TARGET_IDX = ["S&P500", "MSCI ACWI Index"]

ARRAY_FIELDS = ['s_investAssetKindCd','s_investArea3kindCd','s_instCd','s_fdsInstCd','s_dcFundCD',
    't_investArea10kindCd','t_investAssetKindCd','t_instCd','t_fdsInstCd','s_investArea10kindCd',
    's_setlFqcy','s_dividend1y','s_totalNetAssets','s_nowToRedemptionDate','s_establishedDateToNow','s_isinCd']

KEEP = ['isinCd','associFundCd','fundNm','entrustCmpNm','trustReward','entrustTrustReward',
        'bondTrustReward','custodyTrustReward','buyFee','establishedDate','totalNetAssets',
        'standardPrice','standardDate','dividend1y','nisaFlg','nisaGrowthFlg','reportUrl',
        'standardPriceRa6m','standardPriceRa1y','standardPriceRa3y','standardPriceRa5y',
        'standardPriceRa10y','standardPriceRa20y','riskRa3y','riskRa5y','sharpRa5y']


def norm(s):
    """全角/半角・空白・記号ゆれを吸収した比較用キー。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("＆", "&").replace("・", "").replace("－", "-")
    s = re.sub(r"[\s　（）()【】]", "", s)
    return s.lower()


class Lib:
    def __init__(self):
        cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.op.addheaders = [("User-Agent", UA)]
        self.op.open(TOP, timeout=40).read()   # セッション確立（無いと「不正操作エラー」）

    def search(self, keyword, limit=200):
        rows, start = [], 0
        while start < limit:
            body = {f: [] for f in ARRAY_FIELDS}
            body.update({"t_keyword": keyword, "t_kensakuKbn": "1", "t_searchInfoFlag": "1",
                         "startNo": start, "draw": 1, "searchBtnClickFlg": True})
            req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "X-Requested-With": "XMLHttpRequest",
                                                  "Referer": BASE + "/FdsWeb/FDST999900",
                                                  "User-Agent": UA})
            d = json.loads(self.op.open(req, timeout=40).read().decode())
            info = d.get("searchResultInfo") or {}
            got = info.get("resultInfoMapList") or []
            rows += got
            total = int(info.get("recordsTotal") or 0)
            start += len(got)
            if not got or start >= total:
                break
            time.sleep(0.4)
        return rows


def main():
    lineup = json.load(open(LINEUP, encoding="utf-8"))
    src_rows = lineup["指定インデックス投資信託"]["rows"]
    cands = [r for r in src_rows if r["idx"] in TARGET_IDX]
    print(f"母集団 {len(cands)}本（{' / '.join(TARGET_IDX)}）", file=sys.stderr)

    lib = Lib()
    out, miss = [], []
    for r in cands:
        nm = r["nm"]
        hits = lib.search(nm)
        key = norm(nm)
        exact = [h for h in hits if norm(h.get("fundNm")) == key]
        if len(exact) != 1:
            # 名称ゆれ対策: 前方一致で絞る
            exact = [h for h in hits if norm(h.get("fundNm")).startswith(key) or key.startswith(norm(h.get("fundNm")))]
        if len(exact) != 1:
            miss.append({"nm": nm, "co": r["co"], "idx": r["idx"],
                         "hits": [h.get("fundNm") for h in hits][:6], "理由": "一意に定まらず"})
            print(f"  未取得 {nm}  (hits={len(hits)})", file=sys.stderr)
            time.sleep(0.4)
            continue
        h = exact[0]
        rec = {"idx": r["idx"], "届出名": nm, "co": r["co"]}
        rec.update({k: h.get(k) for k in KEEP})
        out.append(rec)
        print(f"  ok {nm}  信託報酬(税抜) {h.get('trustReward')}%", file=sys.stderr)
        time.sleep(0.4)

    std = sorted({o.get("standardDate") for o in out if o.get("standardDate")})
    doc = {
        "generated": time.strftime("%Y-%m-%d"),
        "tool": "night/fetch_tsumitate_funds.py",
        "source": "投資信託協会 投信総合検索ライブラリー /FdsWeb/FDST999900/fundDataSearch",
        "母集団": f"out/tsumitate_lineup.json の 指定インデックス投資信託 のうち {' / '.join(TARGET_IDX)}",
        "基準日": std[-1] if std else None,
        "欄の意味": {
            "trustReward": "信託報酬 年率(税抜%)。税込は ×1.1",
            "standardPriceRaNy": "基準価額騰落率(%)・全ファンド同一基準日。同一指数の群では差＝費用＋連動のズレ",
            "totalNetAssets": "純資産総額(百万円)",
            "buyFee": "購入時手数料(上限%)",
        },
        "⚠限界": [
            "騰落率は分配金の扱いが協会の定義に従う。ここの候補は dividend1y=0 が大半だが、0でない社は差の解釈に注意",
            "設定日が違うと長い窓が取れない（10y/20y が None）。窓を揃えた比較だけを読むこと",
            "実質コスト（売買委託手数料・保管費用等を含む）は運用報告書にしかない。reportUrl を置いてある",
        ],
        "n": len(out),
        "未取得": miss,
        "rows": out,
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}  取得 {len(out)} / 未取得 {len(miss)}", file=sys.stderr)


if __name__ == "__main__":
    main()
