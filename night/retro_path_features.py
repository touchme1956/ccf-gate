# night/retro_path_features.py — 歴史検証・前半(2013-07-01〜2018-07-01)の「値動きの質」採取（2026-08-05新設）
#
# 目的: retro_midway（途中乗り検証）の対象956社について、前半5年の月次adjclose系列と
#       そこから導く「複利の滑らかさ」系の特徴量を在庫化する。
#
# 設計メモ:
#   - データ源は retro_fetch_returns.py と同じ Yahoo chart API の adjclose 一本
#     （ソースを混ぜない——FMP/Yahooは配当調整の作法が違い「基準の違う二つを割る」型になる）
#   - period2 を 2018-07-01 のunixで固定して取る＝この系列自体に look-ahead は無い。
#     adjclose は「今日基準」の配当・分割調整だが、**窓内の比率**（リターン・DD・R²）は正しい。
#     水準（当時の板の値）としては使えない——PER初版事故（2026-08-04）の教訓をここに明記
#   - ts >= period2 のバー（Yahooが境界で1本余分に返すことがある）は捨てる
#   - 「タグが無い」と「値が0」を区別する作法と同型: 取得失敗・系列なしは unmeasured として
#     数えて記録する（黙って捨てない）。特徴量は系列45ヶ月以上の社のみ（それ未満は short として記録）
#   - 中断に備え50社ごとにチェックポイントを書く（再実行は取得済み・失敗済みをスキップ）
#
# 実行: python3 night/retro_path_features.py
# 出力:
#   out/retro_monthly_2013_2018.json — {"ticker": [[unix_ts, adjclose], ...]} の在庫
#     （後で任意のアンカーで切り直せる。素のJSON）
#   out/retro_path_2018.json — 派生特徴量 {"generated","note","rows":[...]}
#     rf5   前半CAGR = (末値/初値)^(1/年数)-1（年数はタイムスタンプ実測）
#     mdd5  前半の最大ドローダウン
#     vol_m 月次リターンの標準偏差（標本・ddof=1）
#     worst12 最悪の12ヶ月ローリングリターン（p[i+12]/p[i]-1 の最小）
#     prox_hi 末値/系列最高値（2018-07時点で高値からどれだけ下か）
#     r2_log 対数価格の線形回帰R²（複利の滑らかさ。x=年数）
#     upmo_r 月次リターンが正だった月の割合
import json, math, os, sys, time, datetime, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "out", "retro_returns_2018.json")
OUT_MONTHLY = os.path.join(BASE, "out", "retro_monthly_2013_2018.json")
OUT_PATH = os.path.join(BASE, "out", "retro_path_2018.json")
CKPT = os.path.join(
    "/tmp/claude-0/-home-user-ccf-gate/b90bb53b-9bea-5ca6-a006-afe566952534/scratchpad",
    "retro_path_ckpt.json")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
T0 = int(datetime.datetime(2013, 7, 1).timestamp())  # 窓の始点
T1 = int(datetime.datetime(2018, 7, 1).timestamp())  # アンカー（固定＝look-aheadなし）
MIN_MONTHS = 45


def fetch(sym):
    """月次adjclose系列 [(ts, adj), ...] を返す。取れなければ None。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={T0}&period2={T1}&interval=1mo")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                return None
            ts = res.get("timestamp") or []
            adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
            # v>0 のみ（logを取るため）・アンカー以降のバーは捨てる
            pts = [[t, v] for t, v in zip(ts, adj) if v is not None and v > 0 and t < T1]
            return pts or None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def features(pts):
    """系列45ヶ月以上の社だけ特徴量を出す。それ未満は None。"""
    n = len(pts)
    if n < MIN_MONTHS:
        return None
    t_start, p_start = pts[0]
    t_end, p_end = pts[-1]
    years = (t_end - t_start) / (365.25 * 86400)
    if years <= 0 or p_start <= 0:
        return None
    prices = [p for _, p in pts]
    # rf5: 前半CAGR
    rf5 = (p_end / p_start) ** (1 / years) - 1
    # mdd5: 最大ドローダウン
    peak, mdd = 0.0, 0.0
    for p in prices:
        peak = max(peak, p)
        mdd = min(mdd, p / peak - 1)
    # 月次リターン
    rets = [prices[i + 1] / prices[i] - 1 for i in range(n - 1)]
    mean_r = sum(rets) / len(rets)
    vol_m = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1))
    # worst12: 最悪の12ヶ月ローリング
    worst12 = min(prices[i + 12] / prices[i] - 1 for i in range(n - 12))
    # prox_hi: 末値/最高値
    prox_hi = p_end / max(prices)
    # r2_log: 対数価格 vs 経過年数のOLS R²
    xs = [(t - t_start) / (365.25 * 86400) for t, _ in pts]
    ys = [math.log(p) for p in prices]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or sst <= 1e-12:
        r2 = None  # 価格が定数など退化系。もっともらしい値を置かない
    else:
        b = sxy / sxx
        ssr = sum((y - (my + b * (x - mx))) ** 2 for x, y in zip(xs, ys))
        r2 = 1 - ssr / sst
    out = {"months": n, "years": round(years, 2),
           "rf5": round(rf5, 4), "mdd5": round(mdd, 3),
           "vol_m": round(vol_m, 4), "worst12": round(worst12, 3),
           "prox_hi": round(prox_hi, 3), "upmo_r": round(sum(1 for r in rets if r > 0) / len(rets), 3)}
    if r2 is not None:
        out["r2_log"] = round(r2, 3)
    return out


def main():
    src = json.load(open(SRC))
    tickers = []
    seen = set()
    for r in src["rows"]:
        t = r.get("ticker")
        if t and t not in seen:
            seen.add(t)
            tickers.append(t)
    print(f"対象 {len(tickers)}社（{os.path.basename(SRC)} rows）"
          f" 窓 2013-07-01〜2018-07-01 interval=1mo")

    # チェックポイント読み込み（再実行時は取得済み・失敗済みをスキップ）
    series, failed = {}, []
    if os.path.exists(CKPT):
        ck = json.load(open(CKPT))
        series, failed = ck.get("series", {}), ck.get("failed", [])
        print(f"  チェックポイント再開: 取得済み{len(series)} 失敗済み{len(failed)}")
    failed_set = set(failed)

    n_done = 0
    for i, t in enumerate(tickers, 1):
        if t in series or t in failed_set:
            continue
        pts = fetch(t)
        time.sleep(0.5)
        n_done += 1
        if pts:
            series[t] = pts
        else:
            failed.append(t)
            failed_set.add(t)
        if n_done % 20 == 0:
            print(f"  {i}/{len(tickers)}  取得:{len(series)} 失敗:{len(failed)}", flush=True)
        if n_done % 50 == 0:
            os.makedirs(os.path.dirname(CKPT), exist_ok=True)
            json.dump({"series": series, "failed": failed}, open(CKPT, "w"))

    # (1) 月次在庫（素のJSON・ticker→系列）
    os.makedirs(os.path.join(BASE, "out"), exist_ok=True)
    json.dump(series, open(OUT_MONTHLY, "w"))
    print(f"■ 書き出し: {OUT_MONTHLY}  {len(series)}社")

    # (2) 派生特徴量
    rows, short = [], []
    for t in tickers:
        pts = series.get(t)
        if not pts:
            continue
        f = features(pts)
        if f is None:
            short.append({"ticker": t, "months": len(pts)})
        else:
            rows.append({"ticker": t, **f})
    note = ("前半(2013-07-01〜2018-07-01)の値動きの質。Yahoo chart API adjclose(1mo)・"
            "period2をアンカーで固定＝系列にlook-aheadなし。adjcloseは今日基準の配当・分割調整"
            "だが窓内の比率(リターン/DD/R²)は正しい——水準(当時の板の値)には使えない。"
            "特徴量は系列45ヶ月以上のみ: rf5=前半CAGR / mdd5=最大DD / vol_m=月次リターン標準偏差(標本) / "
            "worst12=最悪12ヶ月ローリング / prox_hi=末値÷系列最高値 / r2_log=対数価格OLSのR²(複利の滑らかさ) / "
            "upmo_r=正の月の割合。月次系列そのものは out/retro_monthly_2013_2018.json（任意アンカーで切り直せる在庫）。"
            f"取得失敗{len(failed)}社はunmeasured・45ヶ月未満{len(short)}社はshortに記録（黙って捨てない）")
    result = {"generated": datetime.date.today().isoformat(), "note": note,
              "window": ["2013-07-01", "2018-07-01"], "min_months": MIN_MONTHS,
              "rows": rows, "short": short, "unmeasured": failed}
    json.dump(result, open(OUT_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"■ 書き出し: {OUT_PATH}  特徴量 {len(rows)} / short {len(short)} / 未測 {len(failed)}")

    # 分布の要約
    if rows:
        rf = sorted(r["rf5"] for r in rows)
        med = rf[len(rf) // 2]
        n15 = sum(1 for v in rf if v >= 0.15)
        print(f"  rf5 中央値 {med:.1%} / 15%+ {n15}社 / 被覆 {len(rows)}/{len(tickers)}")


if __name__ == "__main__":
    main()
