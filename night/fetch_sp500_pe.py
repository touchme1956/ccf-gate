# night/fetch_sp500_pe.py — S&P500 実績PERの月次系列を取得して保存（2026-08-04新設）
#
# 何のためか: 「非法外な倍率」の線を**市場との相対**で持つための錨。
#   multpl.com の S&P500 PE Ratio（1871年〜・実績GAAP・時価総額加重）は
#   過去と今を同じ定義で測れる一本の系列＝「基準の違う二つを割る」事故が構造的に起きない。
#   歴史検証（asofビンテージの線の換算）と、採用時の毎月の錨の両方に使う。
# 依存の注意: 第三者サイト。途絶えたら SPY株価÷実績EPS の自算へ切替（設計メモ）。
# 実行: python3 night/fetch_sp500_pe.py → out/sp500_pe_monthly.json
import json, os, re, datetime, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "sp500_pe_monthly.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def main():
    url = "https://www.multpl.com/s-p-500-pe-ratio/table/by-month"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        h = r.read().decode("utf-8", "replace")
    rows = re.findall(
        r"<td>((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4})</td>"
        r"\s*<td>\s*(?:&#x2002;)?\s*([\d.]+)", h)
    if len(rows) < 1000:
        raise SystemExit(f"取得が {len(rows)} 行しかない——ページ構造が変わった疑い。パーサを見直すこと")
    ser = {}
    for d, v in rows:
        m, dd, y = d.replace(",", "").split()
        ser[f"{y}-{MON[m]:02d}"] = float(v)
    out = {"generated": datetime.date.today().isoformat(),
           "source": "multpl.com S&P 500 PE Ratio (trailing GAAP, monthly)",
           "n": len(ser), "series": dict(sorted(ser.items()))}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    latest = sorted(ser)[-1]
    print(f"■ 書き出し: {OUT}  {len(ser)}点  最新 {latest}={ser[latest]}  "
          f"2013-07={ser.get('2013-07')}  2015-07={ser.get('2015-07')}")


if __name__ == "__main__":
    main()
