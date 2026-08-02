#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/fetch_dashboard.py — ダッシュボード用の市場データを一括取得（2026-07-30新設）

なぜ作ったか:
  「自動で価格がでてない」の正体は **API鍵が無く market_fetch.py が動かない** ことだった
  （av_key.txt / fmp_key.txt が不在。px が入っているのは 185/317 パックだけ）。
  そして実害は「価格が見えない」ではなく **「価格が古い」** の側に出た——2026-07-30の実測で
  MSFT の台帳価格が 398.66 と 16.6% 古く、**それだけで MSFT が投下可に残り続けていた**。
  門Xの「良い会社を高値で掴まない」という役目が、価格が古いという理由で空回りしていた。

設計:
  ・鍵は環境変数 FINNHUB_KEY（GitHub Secrets 経由）。**ブラウザには一度も出さない**
  ・出力は out/dashboard.json（門が同一オリジンでfetchする静的JSON）と market_data.json
  ・鍵が無ければ**何も壊さず終了**（既存ファイルを空で上書きしない）
  ・取得できなかった銘柄は**書かない**——欠測をゼロや前回値で埋めない（絶対のルール7）
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
KEY = os.environ.get("FINNHUB_KEY") or ""
for p in ("./finnhub_key.txt", "./ccf/finnhub_key.txt"):
    if not KEY and os.path.exists(p):
        KEY = open(p).read().strip()
API = "https://finnhub.io/api/v1"
UA = {"User-Agent": "ccf-gate dashboard"}


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def tickers():
    """監視リスト ∪ 保有 ∪ Ω72+。全317社を毎日叩く必要はない（分あたり制限を無駄に食う）"""
    s = set()
    for p, k in (("kanshi_list.json", ("list", "tickers", "pin")), ("holdings.json", ("holdings", "elite"))):
        if os.path.exists(p):
            try:
                cfg = json.load(open(p, encoding="utf-8"))
                for key in k:
                    s |= {t.strip().upper() for t in (cfg.get(key) or []) if str(t).strip()}
            except Exception:
                pass
    try:
        for r in json.load(open("out/score_all.json", encoding="utf-8")):
            if (r.get("s") or 0) >= 72:
                s.add(str(r.get("t", "")).upper())
    except Exception:
        pass
    return sorted(t for t in s if t)


def jp_quotes(codes):
    """日本株はYahoo Financeから取る（2026-08-02新設）。

    なぜ別経路か: **Finnhubの無料枠は東証を返さない**（実測で 6146.T / 6857.T / TSE:6146 とも
    HTTP 401）。Alpha Vantage の GLOBAL_QUOTE も 6146.T で空を返す。無料・鍵不要で
    東証の現在値が取れるのは Yahoo Finance の chart エンドポイントだけだった。

    非公式APIなので**落ちても何も壊さない**——取れなければその銘柄を書かないだけ。
    門は「価格未取得」と出して台帳/手入力の値へ落ちる（前回値やゼロで埋めない＝絶対のルール7）。
    """
    out = {}
    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    for c in codes:
        try:
            u = f"https://query1.finance.yahoo.com/v8/finance/chart/{c}.T?interval=1d&range=5d"
            with urllib.request.urlopen(urllib.request.Request(u, headers=ua), timeout=25) as r:
                m = json.loads(r.read().decode("utf-8", "ignore"))["chart"]["result"][0]["meta"]
            px = m.get("regularMarketPrice")
            prev = m.get("chartPreviousClose") or m.get("previousClose")
            if not px:
                continue
            q = {"px": px, "prev": prev, "ccy": m.get("currency") or "JPY"}
            if prev:
                q["chg"] = round(px - prev, 2)
                q["chgPct"] = round((px / prev - 1) * 100, 4)
            out[c] = q
        except Exception as e:
            print(f"  {c}: 取得できず（{type(e).__name__}）→ 書かない")
        time.sleep(1.2)
    return out


def main():
    if not KEY:
        print("FINNHUB_KEY が無い → 何も書かずに終了（既存ファイルは壊さない）")
        print("  設定: GitHub → Settings → Secrets and variables → Actions → FINNHUB_KEY")
        # 2026-08-02是正: **CIでは異常終了する**。
        #   初回実行で env に FINNHUB_KEY が空のまま渡り、スクリプトは正しく「何も書かず終了」したが
        #   return 0 だったため**ワークフローは緑（成功）**になった。12秒で終わり何もコミットされて
        #   いないのに、画面上は成功。**鳴らない警報**そのもので、このリポジトリが何度も踏んできた
        #   「静かな壊れ方」と同型（acq5が既定へ化けた／kanshiのキー違いで点検が3社に縮んだ／
        #   古い株価がMSFTを投下可に残した）。
        #   手元で鍵無しに走らせるのは正常な使い方なので0のまま。**CIだけ赤くする。**
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error::FINNHUB_KEY が空。Secretの名前が FINNHUB_KEY ちょうどか、"
                  "Repository secret として登録されているか（Environment secret ではないか）を確認せよ")
            return 1
        return 0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"asof": ts, "quotes": {}, "news": {}, "fx": {}}

    # 為替: Finnhub の /forex/rates は**無料枠では引けない**（2026-07-30の実測で quote が返らず
    #   USDJPY=None になった）。鍵不要で使える open.er-api.com へ切り替える。
    #   取れなければ書かない——盤は「為替未取得」と出し、Ⅶ保有の手入力値へ落ちる（ゼロで埋めない）。
    fx = _get("https://open.er-api.com/v6/latest/USD")
    if fx and isinstance(fx.get("rates"), dict) and fx["rates"].get("JPY"):
        out["fx"]["USDJPY"] = round(float(fx["rates"]["JPY"]), 3)
        out["fx"]["src"] = "open.er-api.com（鍵不要）"

    ALL = tickers()
    JP = [t for t in ALL if t.isdigit()]
    T = [t for t in ALL if not t.isdigit()]
    print(f"対象 {len(ALL)}社（米国等 {len(T)}=Finnhub / 日本株 {len(JP)}=Yahoo Finance）")
    if JP:
        jq = jp_quotes(JP)
        out["quotes"].update(jq)
        print(f"  日本株 {len(jq)}/{len(JP)}社 取得")
    for i, t in enumerate(T, 1):
        q = _get(f"{API}/quote?symbol={t}&token={KEY}")
        # c=現在値 pc=前日終値 d=前日比 dp=前日比% —— 0埋めされた応答は「取得失敗」として捨てる
        if q and q.get("c"):
            out["quotes"][t] = {"px": q.get("c"), "prev": q.get("pc"),
                                "chg": q.get("d"), "chgPct": q.get("dp"),
                                "high": q.get("h"), "low": q.get("l")}
        n = _get(f"{API}/company-news?symbol={t}&from={ts[:8]}01&to={ts[:10]}&token={KEY}")
        if isinstance(n, list) and n:
            out["news"][t] = [{"h": x.get("headline"), "u": x.get("url"),
                               "d": x.get("datetime"), "s": x.get("source")} for x in n[:3]]
        if i % 30 == 0:
            print(f"  {i}/{len(T)}")
        time.sleep(1.1)          # 無料枠の分あたり制限に対する保険

    os.makedirs("out", exist_ok=True)
    json.dump(out, open("out/dashboard.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # market_merge.py が読む形へも書き出す（px だけ。定性・機械値には触れない）
    md = {}
    if os.path.exists("market_data.json"):
        try:
            md = json.load(open("market_data.json", encoding="utf-8"))
        except Exception:
            md = {}
    for t, q in out["quotes"].items():
        md.setdefault(t, {})["px"] = q["px"]
    json.dump(md, open("market_data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ out/dashboard.json（株価{len(out['quotes'])}社 / ニュース{len(out['news'])}社 / "
          f"USDJPY={out['fx'].get('USDJPY')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
