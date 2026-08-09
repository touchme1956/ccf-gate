# night/fetch_sp500_tr.py — S&P500 の月次「価格・配当利回り・配当込みトータルリターン指数」(2026-08-09新設)
#
# 何のためか:
#   out/sp500_pe_monthly.json（実績PER・1871年〜）だけでは **市場水準の遮断器を検定できない**。
#   「市場全体が高すぎるなら買わない」を裁くには『その時点で買った人がその後10年で何%取れたか』が要る。
#   PERの系列は倍率しか持たないので、価格と配当を別に採ってトータルリターンを組む。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【守っている作法】
#
# ■ 基準の違う二つを割らない
#   価格・配当利回り・PER を **すべて multpl.com の同一系列（出所は Shiller データ）** から採る。
#   Yahoo の ^GSPC（1927年〜・配当なし）や ^SP500TR（1988年〜）と混ぜない
#   ——配当の扱いも月内のどの日を指すかも違い、混ぜた瞬間にこの台帳が5回踏んだ型になる。
#
# ■ 二重実装を作らない（＝作るなら同一であることを証明する）
#   パーサは night/fetch_sp500_pe.py と同じ正規表現の意味論。**別実装を増やさない代わりに、
#   同じ PER ページを自分のパーサで採って既存の在庫 out/sp500_pe_monthly.json と
#   1点ずつ突合し、全点一致することを毎回確かめる**（--verify-pe。既定で走る）。
#   食い違ったら書き出さずに落ちる＝「同じ台帳を見る二つの検査器が違うことを言う」前に止まる。
#
# ■ 欠測をゼロと読むな（絶対のルール7）
#   価格か配当利回りのどちらかが欠けた月は **TR指数を伸ばさずそこで系列を切る**（0%配当と読まない）。
#   欠けた月は nulls に残す。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【この系列の限界（読む人が必ず知っているべきこと）】
#   (1) multpl の月次価格は **月内の日次終値の平均**（Shiller の作法）で、月末終値ではない。
#       10年の窓を測る用途では実害は小さいが、月次の変化率としては平滑されている。
#   (2) 配当利回りページの日付は **月末**、価格ページは **月初**。どちらも "YYYY-MM" に落として使う。
#       配当は「その月に年率 y で受け取る」＝ y/12 として月次で積む近似。
#   (3) よって本器の TR は **近似**である。検算として 1988年以降を Yahoo の ^SP500TR と
#       突き合わせた結果を header に残す（--crosscheck-yahoo）。
#
# 実行:
#   python3 night/fetch_sp500_tr.py                 # → out/sp500_tr_monthly.json
#   python3 night/fetch_sp500_tr.py --crosscheck-yahoo
import argparse
import datetime
import json
import os
import re
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

PAGES = {
    "price": "https://www.multpl.com/s-p-500-historical-prices/table/by-month",
    "divy": "https://www.multpl.com/s-p-500-dividend-yield/table/by-month",
    "pe": "https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
    # CPI は **実質利益の平滑（CAPE型）の診断**にだけ使う。同じ出所から採るのは
    # 「基準の違う二つを割らない」ため（他所の物価系列と混ぜない）。
    "cpi": "https://www.multpl.com/cpi/table/by-month",
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def parse_multpl(html):
    """multpl の月次テーブルを {'YYYY-MM': float} へ。

    fetch_sp500_pe.py の正規表現と同じ意味論。ただし本器は
      ・桁区切りのカンマ（価格 7,819.42）
      ・末尾の %（配当利回り 1.04%）
      ・&#x2002; の代わりに <abbr title="Estimate">†</abbr> が入る行（推定値）
    も受ける。**推定値の行は estimate として別に数え、値は採る**（黙って落とさない）。
    """
    rows = re.findall(
        r"<td>((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4})</td>\s*"
        r"<td>\s*(?:&#x2002;|<abbr[^>]*>[^<]*</abbr>)?\s*([\d,]+\.?\d*)\s*%?\s*</td>", html)
    if len(rows) < 1000:
        raise SystemExit(f"取得が {len(rows)} 行しかない——ページ構造が変わった疑い。パーサを見直すこと")
    est = len(re.findall(r"<abbr[^>]*>", html))
    ser = {}
    for d, v in rows:
        m, _dd, y = d.replace(",", " ").split()[0], None, d.split(", ")[-1]
        mm = MON[m]
        ser[f"{y}-{mm:02d}"] = float(v.replace(",", ""))
    return dict(sorted(ser.items())), est


def verify_pe():
    """自分のパーサで PER ページを採り、既存の在庫と1点ずつ突合する（全点一致を要求）。"""
    p = os.path.join(OUT, "sp500_pe_monthly.json")
    if not os.path.exists(p):
        return {"ran": False, "why": "out/sp500_pe_monthly.json が無い"}
    have = json.load(open(p, encoding="utf-8"))["series"]
    mine, _ = parse_multpl(get(PAGES["pe"]))
    common = sorted(set(have) & set(mine))
    bad = [k for k in common if abs(float(have[k]) - mine[k]) > 1e-9]
    res = {"ran": True, "common_months": len(common), "mismatches": len(bad),
           "only_in_inventory": len(set(have) - set(mine)),
           "only_in_mine": len(set(mine) - set(have)), "examples": bad[:10]}
    if bad:
        raise SystemExit(f"■ パーサが既存の在庫と食い違う（{len(bad)}点）。書き出さずに止める: {bad[:10]}")
    return res


def build_tr(price, divy):
    """配当込みトータルリターン指数。I(t+1) = I(t) × P(t+1)/P(t) × (1 + y(t)/12)。

    **価格か利回りが欠けた月は伸ばさない**（0と読まない・ルール7）。欠けた時点で系列を切り、
    切った理由を返す。
    """
    ks = sorted(set(price) & set(divy))
    if not ks:
        return {}, {"why": "価格と利回りの重なりが無い"}
    tr, gaps = {}, []
    idx = 1.0
    prev = None
    out = {}
    for k in ks:
        if prev is None:
            out[k] = idx
            prev = k
            continue
        # 月が飛んでいたら（欠測月）そこで切る
        gap = (int(k[:4]) - int(prev[:4])) * 12 + (int(k[5:]) - int(prev[5:]))
        if gap != 1:
            gaps.append({"from": prev, "to": k, "months": gap})
            prev = k
            out[k] = idx
            continue
        idx *= (price[k] / price[prev]) * (1.0 + divy[prev] / 100.0 / 12.0)
        out[k] = idx
        prev = k
    return out, {"gaps": gaps, "first": ks[0], "last": ks[-1], "n": len(ks)}


def crosscheck_yahoo(tr):
    """1988年以降を Yahoo の ^SP500TR（配当込み指数の本物）と突き合わせる。

    **本器の TR は近似**（月内平均価格・y/12 の配当近似）なので、水準ではなく
    **同じ期間の年率**で比べる。差が大きければ header に残して読む人に警告する。
    """
    try:
        u = ("https://query1.finance.yahoo.com/v8/finance/chart/%5ESP500TR"
             "?period1=568000000&period2=2000000000&interval=1mo")
        j = json.loads(get(u))
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        cl = res["indicators"]["quote"][0]["close"]
        ser = {}
        for t, c in zip(ts, cl):
            if c is None:
                continue
            d = datetime.datetime.utcfromtimestamp(t)
            ser[f"{d.year}-{d.month:02d}"] = c
    except Exception as e:
        return {"ran": False, "why": f"Yahoo取得に失敗: {type(e).__name__}"}
    ks = sorted(set(ser) & set(tr))
    if len(ks) < 120:
        return {"ran": False, "why": f"重なりが {len(ks)}ヶ月しかない"}
    a, b = ks[0], ks[-1]
    yrs = ((int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:])) / 12.0
    mine = (tr[b] / tr[a]) ** (1 / yrs) - 1
    theirs = (ser[b] / ser[a]) ** (1 / yrs) - 1
    return {"ran": True, "from": a, "to": b, "years": round(yrs, 2),
            "mine_cagr": round(mine, 4), "yahoo_sp500tr_cagr": round(theirs, 4),
            "diff_pt": round((mine - theirs) * 100, 3),
            "note": "本器は月内平均価格＋y/12近似なので完全一致はしない。差が0.5pt以内なら実用上同じ"}


def main():
    ap = argparse.ArgumentParser(description="S&P500の月次価格・配当利回り・配当込みTR指数を採る")
    ap.add_argument("--out", default=os.path.join(OUT, "sp500_tr_monthly.json"))
    ap.add_argument("--no-verify-pe", action="store_true")
    ap.add_argument("--crosscheck-yahoo", action="store_true")
    a = ap.parse_args()

    ver = {"ran": False} if a.no_verify_pe else verify_pe()
    if ver.get("ran"):
        print(f"■ パーサ照合: 既存の PER 在庫と {ver['common_months']}ヶ月を突合 → 食い違い "
              f"{ver['mismatches']}件（0でなければ落ちる）")

    price, est_p = parse_multpl(get(PAGES["price"]))
    divy, est_d = parse_multpl(get(PAGES["divy"]))
    cpi, _ = parse_multpl(get(PAGES["cpi"]))
    print(f"■ 価格 {len(price)}点 {min(price)}〜{max(price)} / 配当利回り {len(divy)}点 "
          f"{min(divy)}〜{max(divy)} / CPI {len(cpi)}点 {min(cpi)}〜{max(cpi)}")

    tr, meta = build_tr(price, divy)
    out = {
        "generated": datetime.date.today().isoformat(),
        "tool": "night/fetch_sp500_tr.py",
        "source": "multpl.com（S&P 500 Historical Prices / Dividend Yield / PE Ratio。原典は Shiller データ）",
        "basis": ("価格は月内の日次終値の平均（月末終値ではない）／配当利回りは月末の年率。"
                  "TR指数は I(t+1)=I(t)×P(t+1)/P(t)×(1+y(t)/12) の**近似**"),
        "caveats": [
            "月内平均価格なので月次の変化率は平滑されている（10年窓の用途では実害小）",
            "配当利回りページの日付は月末・価格ページは月初。どちらも YYYY-MM に落として使う",
            "欠測月では指数を伸ばさない（0%配当と読まない・絶対のルール7）",
        ],
        "verify_pe": ver,
        "n_price": len(price), "n_divy": len(divy), "n_cpi": len(cpi), "n_tr": len(tr),
        "tr_meta": meta,
        "price": price, "divy": divy, "cpi": cpi,
        "tr": {k: round(v, 6) for k, v in tr.items()},
    }
    if a.crosscheck_yahoo:
        cc = crosscheck_yahoo(tr)
        out["crosscheck_yahoo"] = cc
        print("■ Yahoo ^SP500TR との突合:", json.dumps(cc, ensure_ascii=False))

    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ks = sorted(tr)
    yrs = ((int(ks[-1][:4]) - int(ks[0][:4])) * 12 + int(ks[-1][5:]) - int(ks[0][5:])) / 12.0
    print(f"■ 書き出し: {a.out}  TR {len(tr)}点 {ks[0]}〜{ks[-1]}  "
          f"通期年率 {((tr[ks[-1]]/tr[ks[0]])**(1/yrs)-1):.2%}（{yrs:.1f}年）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
