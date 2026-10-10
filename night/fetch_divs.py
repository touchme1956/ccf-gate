#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/fetch_divs.py — 直近12か月の1株あたり配当（実績）を取り out/holdings_div.json へ書く（鍵不要・表示専用）

何のためか（2026-10-10 ユーザー「保有の銘柄を押すとこのような画面が出て詳細が見れるようにして」＝家計アプリの詳細画面の写真）:
  🏦保有の銘柄の詳細画面に「配当利回り（評価額）／（取得額）」を出す。**門にも repo にも配当の1株あたりの実額が無かった**
  （out/divy.json は E[r] 用に SEC のFY末の1株配当から作った24社だけで、ETF〔XLK・SMH・QQQM〕と外国株〔ASML〕が無い）。
  Yahoo の chart API は `events=div` で配当の履歴を返すので、そこから12か月ぶんを足す（鍵不要・価格と同じ出所）。

定義（ここを写真の家計アプリと揃えた——MSFT で 0.68% が出る）:
  ttm  ＝ 直近365日（最新の値段の日から数える）に払われた1株あたり配当の合計（その銘柄の通貨・分割調整済み）
  n    ＝ その回数（年4回の株なら 4・年1回の ETF なら 1）
  配当利回り（評価額）＝ ttm ÷ 現在値
  配当利回り（取得額）＝ ttm × 株数 ÷ 取得額（円換算は門が行う）
  ⚠ 税引前・実績。**予想ではない**（増配・減配はこれから）。ETF の分配は年によって増減する。
  ⚠ 年1回払いの ETF（SMH など）は、支払日が前年より1日でも遅れると365日の窓から外れて 0 に見える日がある
     ＝回数 n を一緒に出し、門は n=0 を「0%」ではなく「直近12か月に配当なし」と書く。

取れなかったとき（絶対のルール7）:
  取れなかった銘柄は**前回の値を残して stale:true を立てる**（0 で埋めない・空で上書きしない）。1銘柄も取れなければ
  ファイルを書かずに終了コード1（CI では continue-on-error なので門は前回のファイルを読み続ける）。

出力: out/holdings_div.json  {asof, src, window_days, div:{T:{ttm,n,ccy,last_d,last_a,asof[,stale]}}, missing:[…]}
使い方: python3 night/fetch_divs.py [--only MSFT,XLK] [--dry]
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "holdings_div.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
WINDOW_DAYS = 365
SRC = "Yahoo chart events=div（鍵不要）"


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def tickers():
    """対象: 保有（state.json）と盤の価格表（out/dashboard.json）にある株・ETF。
    投資信託（投信協会の基準価額）と暗号資産（配当の概念が無い）は外す。"""
    out = []

    def add(t):
        t = str(t or "").strip().upper()
        if t and t not in out:
            out.append(t)

    st = _read(os.path.join(BASE, "state.json")) or {}
    try:
        pf = json.loads(((st.get("data") or {}).get("pf:portfolio")) or "{}")
        for p in pf.get("positions") or []:
            if (p.get("kind") or "") not in ("投資信託", "暗号資産"):
                add(p.get("t"))
    except Exception:
        pass
    dj = _read(os.path.join(BASE, "out", "dashboard.json")) or {}
    for t, q in (dj.get("quotes") or {}).items():
        if (q or {}).get("src") == "toushin-lib":      # 投資信託
            continue
        add(t)
    return [t for t in out if not t.endswith("-USD")]


def ysym(t):
    """門のコード → Yahoo の記号。日本株（数字）は .T・BRK.B のような点は -"""
    if t.isdigit():
        return t + ".T"
    return t.replace(".", "-")


def fetch(sym, tries=3):
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym)
         + "?range=2y&interval=1mo&events=div")
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as f:
                j = json.load(f)
            res = (j.get("chart") or {}).get("result") or []
            if res:
                return res[0]
            last = (j.get("chart") or {}).get("error") or "empty"
        except Exception as e:      # 通信・JSON の壊れ・429 など
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(str(last))


def ttm_of(res):
    """chart の結果から {ttm,n,ccy,last_d,last_a,asof} を作る。配当の履歴が無いのは 0（無配）、応答が壊れていれば例外。"""
    meta = res.get("meta") or {}
    ts = meta.get("regularMarketTime") or int(time.time())
    ev = ((res.get("events") or {}).get("dividends")) or {}
    rows = []
    for v in ev.values():
        d, a = v.get("date"), v.get("amount")
        if isinstance(d, (int, float)) and isinstance(a, (int, float)) and a > 0:
            rows.append((int(d), float(a)))
    rows.sort()
    cut = ts - WINDOW_DAYS * 86400
    win = [(d, a) for d, a in rows if cut < d <= ts + 86400]
    out = {"ttm": round(sum(a for _, a in win), 6), "n": len(win), "ccy": meta.get("currency") or "",
           "asof": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")}
    if rows:
        d, a = rows[-1]
        out["last_d"] = datetime.fromtimestamp(d, tz=timezone.utc).strftime("%Y-%m-%d")
        out["last_a"] = round(a, 6)
    return out


def main():
    only = None
    if "--only" in sys.argv:
        only = [x.strip().upper() for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x.strip()]
    dry = "--dry" in sys.argv
    T = only or tickers()
    prev = (_read(OUT) or {}).get("div") or {}
    div, missing, n_ok = {}, [], 0
    for i, t in enumerate(T, 1):
        try:
            div[t] = ttm_of(fetch(ysym(t)))
            n_ok += 1
        except Exception as e:
            missing.append(t)
            if t in prev:                       # 取れなかった日は前回の値を残す（0で埋めない）
                div[t] = dict(prev[t], stale=True)
            print(f"  ✗ {t}: {e}")
        if i % 20 == 0:
            print(f"  {i}/{len(T)}")
        time.sleep(0.35)
    print(f"配当 {n_ok}/{len(T)}社 取得" + (f"・取れなかった {len(missing)}社: {' '.join(missing)}" if missing else ""))
    if not n_ok:
        print("※1社も取れなかった＝ファイルを書かない（前回のまま）")
        return 1
    out = {"asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "src": SRC, "window_days": WINDOW_DAYS,
           "note": "直近365日の1株あたり配当の合計（実績・税引前・その銘柄の通貨）。予想ではない。門は ttm÷現在値 を配当利回りとして出す。",
           "div": dict(sorted(div.items())), "missing": sorted(missing)}
    if dry:
        print(json.dumps(out, ensure_ascii=False)[:600])
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
        f.write("\n")
    print(f"→ {os.path.relpath(OUT, BASE)}（{len(div)}社）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
