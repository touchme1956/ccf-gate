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
import json, os, re, sys, time, urllib.request, urllib.error
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
    # ── 網(ETF)も価格を採る（2026-08-20 ユーザー指示「買付順位にETFもいれて」）──────────
    #   Ⅵ買付順位が網の5本を出すようになったので、**株数を出すには価格が要る**。
    #   出所は portfolio.json の **target.ami_names（目標の5本）** と **positions（実際に持っている本）**
    #   ——目標から外れたが保有している本（QQQ/FANG+）も価格が要る（黙って消さないため・v9.9.52）。
    #   ⚠ここに足さないと、門は「単価未取得」と出し続ける（推測の価格は置かない＝ルール7）。
    try:
        #   ⚠ `portfolio.json` の ticker は**表示のラベル**でもあるので、ティッカーとして
        #     成立しない文字列が混じる（実測 `FANG+`＝iFreeNEXT等の非上場投信で、
        #     どの価格APIにも存在しない）。**毎日404を叩いて diag を埋めるのは
        #     「鳴りすぎる警報は鳴らないのと同じ」**なので、ティッカーの形のものだけ採る。
        #     ⚠**黙って落としているのではない**——門のⅥは目標から外れた本を
        #     `◇ 目標から外れたが、まだ持っている本` として保有%つきで名指しで出す（v9.9.52）し、
        #     価格が要る欄（株数）はそもそもその行に無い。
        TK = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,5}$")
        pf = json.load(open("portfolio.json", encoding="utf-8"))
        cand = [str(t).strip().upper() for t in ((pf.get("target") or {}).get("ami_names") or [])]
        cand += [str(pos.get("ticker", "")).strip().upper() for pos in (pf.get("positions") or [])]
        s |= {t for t in cand if t and TK.match(t)}
    except Exception:
        pass
    return sorted(t for t in s if t)


def _yahoo_ctx():
    """Yahoo は endpoint によって **Cookie + crumb** を要求する（2023年以降）。
    fc.yahoo.com で Cookie を得て、/v1/test/getcrumb で crumb を取る。取れなくても続行する
    （v8/chart は本来 crumb 不要で、要るのは v7/quote 系。両方試すための下ごしらえ）。"""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    hdr = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
           ("Accept", "application/json,text/plain,*/*"),
           ("Accept-Language", "en-US,en;q=0.9"),
           ("Connection", "keep-alive")]
    op.addheaders = hdr
    crumb = None
    try:
        op.open("https://fc.yahoo.com/", timeout=15).read()
    except Exception:
        pass          # Cookie さえ取れれば十分なことが多い。403でもCookieは載る
    try:
        crumb = op.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).read().decode().strip()
        if len(crumb) > 40 or not crumb:
            crumb = None
    except Exception:
        crumb = None
    return op, crumb


def jp_quotes(codes):
    """日本株はYahoo Financeから取る。

    なぜ別経路か（2026-08-02実測）: **Finnhubの無料枠は東証を返さない**（6146.T/6857.T/TSE:6146 とも
    HTTP 401）。Alpha Vantage の GLOBAL_QUOTE も空。stooq は404。FMPはPremium必須。
    J-Quants の無料プランは12週間遅延で、門Xの判定には古すぎる。
    残るのは Yahoo Finance だけ。

    2026-08-02の初回実装は**全10社が失敗**したが、例外型しかログしておらず原因不明だった。
    ここでは **実際のHTTPステータスと本文の頭**を必ず出す——「動かない」で終わらせず
    「なぜ動かないか」を残すため（このリポジトリが繰り返し踏んできた"静かな失敗"を作らない）。
    """
    out, diag = {}, []
    pxday = None
    op, crumb = _yahoo_ctx()
    print(f"  Yahoo: crumb={'取得' if crumb else '無し'}")
    hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
    for c in codes:
        got = False
        for host in hosts:
            for path in (f"/v8/finance/chart/{c}.T?interval=1d&range=10d",
                         f"/v7/finance/quote?symbols={c}.T" + (f"&crumb={crumb}" if crumb else "")):
                try:
                    with op.open(f"https://{host}{path}", timeout=20) as r:
                        j = json.loads(r.read().decode("utf-8", "ignore"))
                    if "chart" in j:
                        res = j["chart"]["result"][0]
                        m = res["meta"]
                        px = m.get("regularMarketPrice")
                        ccy = m.get("currency") or "JPY"
                        # 2026-08-02 是正: **chartPreviousClose を前日終値に使ってはいけない**。
                        #   これは「指定レンジの**直前**の終値」で、range=5d なら**5営業日前**の値。
                        #   初回はこれを使ったため 6146 が −6.66% / 6857 が +14.52% と、
                        #   前日比ではなく**5日間の変化率**を表示していた（ユーザーが違和感で発見）。
                        #   日足の終値系列から「最後から2番目」を取るのが正しい前日終値。
                        prev = m.get("previousClose")
                        try:
                            cl = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
                            if len(cl) >= 2:
                                prev = cl[-2]          # 最後=当日 / その前=前営業日
                                if px is None:
                                    px = cl[-1]
                        except Exception:
                            pass
                        if prev is None:
                            prev = m.get("chartPreviousClose")   # 最後の手段（レンジ直前の終値）
                        # どの営業日の終値かを持たせる（休場日に開くと「いつの値か」が分からなくなるため）
                        try:
                            import datetime as _dt
                            _ts = res.get("timestamp") or []
                            if _ts:
                                pxday = _dt.datetime.utcfromtimestamp(_ts[-1]).strftime("%Y-%m-%d")
                        except Exception:
                            pxday = None
                    else:
                        q = (j.get("quoteResponse") or {}).get("result") or []
                        if not q:
                            continue
                        px, prev, ccy = q[0].get("regularMarketPrice"), q[0].get("regularMarketPreviousClose"), q[0].get("currency") or "JPY"
                    if not px:
                        continue
                    d = {"px": px, "prev": prev, "ccy": ccy}
                    if locals().get("pxday"):
                        d["day"] = pxday
                    if prev:
                        d["chg"] = round(px - prev, 2)
                        d["chgPct"] = round((px / prev - 1) * 100, 4)
                    out[c] = d
                    got = True
                    break
                except urllib.error.HTTPError as e:
                    body = ""
                    try:
                        body = e.read().decode("utf-8", "ignore")[:120].replace("\n", " ")
                    except Exception:
                        pass
                    diag.append(f"{c} {host[:6]}{path[:14]} → HTTP {e.code} {body}")
                except Exception as e:
                    diag.append(f"{c} {host[:6]} → {type(e).__name__} {str(e)[:60]}")
            if got:
                break
        time.sleep(1.0)
    if diag:
        print("  ── 失敗の実際（先頭6件）")
        for d in diag[:6]:
            print("    " + d)
    return out


def fetch_fx():
    """ドル円を引く（**鍵は要らない**）。取れなければ None——ゼロで埋めない（絶対のルール7）。

    為替: Finnhub の /forex/rates は**無料枠では引けない**（2026-07-30の実測で quote が返らず
      USDJPY=None になった）。鍵不要で使える open.er-api.com へ切り替えてある。
    """
    fx = _get("https://open.er-api.com/v6/latest/USD")
    if fx and isinstance(fx.get("rates"), dict) and fx["rates"].get("JPY"):
        return {"USDJPY": round(float(fx["rates"]["JPY"]), 3),
                "src": "open.er-api.com（鍵不要）",
                # ★fx は自分の時刻を持つ。out['asof'] は**株価**の時刻なので、
                #   鍵が無くて為替だけ更新した日に asof を読むと為替の鮮度を誤る
                "asof": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return None


def main():
    if not KEY:
        # ★2026-08-18 の是正（ユーザーの問い「為替を自動更新できるようにしたほうがよい?」で発覚）——
        #   **ドル円は鍵が要らないのに、鍵の検問の後ろに置かれていた**。
        #   ＝FINNHUB_KEY が切れた日は、引けるはずの為替まで一緒に止まる。
        #   為替は Ⅶ資産の円換算と v9.9.146 の時価総額Tier（配分）に効くので、
        #   「株価が止まった」と「為替も止まった」が同時に起きると影響が二重になる。
        #   → **鍵が無くても為替だけは更新する。ただし既存の quotes は絶対に壊さない**
        #     （読んで fx だけ差し替える＝audit_stale_bs:243 と同じ空書き込みの検問）。
        fxo = fetch_fx()
        if fxo and os.path.exists("out/dashboard.json"):
            try:
                cur = json.load(open("out/dashboard.json", encoding="utf-8"))
                if isinstance(cur.get("quotes"), dict) and cur["quotes"]:
                    cur["fx"] = fxo
                    json.dump(cur, open("out/dashboard.json", "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                    print(f"  ※鍵が無いので株価は据置。**ドル円だけ更新した** USDJPY={fxo['USDJPY']}"
                          f"（株価の asof は {cur.get('asof')} のまま）")
                else:
                    print("  ※既存 dashboard.json に株価が無い＝空で上書きしないため為替も書かない")
            except Exception as e:
                print(f"  ※既存 dashboard.json を読めないので為替も書かない（{e}）")
        elif not fxo:
            print("  ※ドル円も引けなかった（open.er-api.com）")
        print("FINNHUB_KEY が無い → 株価とニュースは書かずに終了（既存ファイルは壊さない）")
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

    # 為替（鍵不要・単一実装 fetch_fx）。取れなければ書かない——盤は「為替未取得」と出し、
    #   Ⅶ保有の手入力値へ落ちる（ゼロで埋めない）。
    fxo = fetch_fx()
    if fxo:
        out["fx"] = fxo
    else:
        # ★引けなかった日に**前回の為替を捨てない**。株価は今日の値・為替は前回の値、と分けて持つ
        #   （fx.asof がその日付を持つので、どの日の為替かは画面から辿れる）
        try:
            prev = json.load(open("out/dashboard.json", encoding="utf-8")).get("fx") or {}
            if prev.get("USDJPY"):
                out["fx"] = dict(prev)
                out["fx"]["stale"] = True
                print(f"  ※ドル円が引けなかった → 前回値を据え置く USDJPY={prev.get('USDJPY')}"
                      f"（{prev.get('asof') or '取得日不明'}）")
        except Exception:
            pass

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
