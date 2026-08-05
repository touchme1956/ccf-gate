# night/retro_sic.py — 歴史検証: 全対象銘柄のSIC業種コード採取（2026-08-05新設）
#
# 対象: out/retro_returns_2018.json の rows の ticker 全部（約956社）。
# ticker→CIK は out/retro_cohort_2013.json の rows（ticker/cik）。
# データ源: SEC submissions API
#   https://data.sec.gov/submissions/CIK{10桁ゼロ埋め}.json の "sic" / "sicDescription"
#
# 設計メモ:
# - submissions JSON は大きい社で数MBあるが、sic/sicDescription はファイル先頭の
#   ヘッダ部にあるので、先頭チャンクだけ読んで正規表現で抜く（全量ダウンロードしない）。
#   値の取り出しは JSON エスケープを保存する形（(?:[^"\\]|\\.)*）で採り、
#   json.loads で復号する＝切り詰めた JSON を「それらしく」読む事故を避ける。
# - 「タグが無い」と「値が空」を区別する: sic キーが見つからない/空文字列は欠測として
#   sic 欄を出力に含めない（0や""で埋めない・ルール7）。error/reason を記録して先へ進む。
# - sic2 = sic の先頭2桁（sic が2桁以上の数字のときだけ）。
# - レート: time.sleep(0.13) ＝毎秒8リクエスト以下（SECの10req/s制限の内側）。
# - User-Agent: "CCF-Omega-Screener fortis5280@gmail.com"（SECの規約どおり）。
# - look-ahead の論点なし: SIC は「現在の」登録分類であり時点付きデータではない。
#   業種の粗い層別にだけ使う（notes に明記）。
#
# 実行: python3 night/retro_sic.py
# 出力: out/retro_sic.json = {"generated","note","sic2_dist","rows"}
import json
import os
import re
import time
import datetime
import urllib.request
import urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COHORT = os.path.join(BASE, "out", "retro_cohort_2013.json")
RETURNS = os.path.join(BASE, "out", "retro_returns_2018.json")
OUT = os.path.join(BASE, "out", "retro_sic.json")
UA = {"User-Agent": "CCF-Omega-Screener fortis5280@gmail.com",
      "Accept-Encoding": "identity"}
SLEEP = 0.13  # 毎秒8リクエスト以下

RE_SIC = re.compile(r'"sic"\s*:\s*"((?:[^"\\]|\\.)*)"')
RE_DESC = re.compile(r'"sicDescription"\s*:\s*"((?:[^"\\]|\\.)*)"')


def unescape(s):
    """JSONエスケープを復号する（切り出した値は必ずここを通す）。"""
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def fetch_head(cik):
    """submissions JSON の先頭部だけ読む。返り値: (buf:str|None, err:str|None)"""
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                buf = b""
                # sic/sicDescription はヘッダ部（先頭数百バイト）にある。
                # 念のため最大64KBまで読み、両キーが揃ったら打ち切る。
                while len(buf) < 65536:
                    chunk = r.read(8192)
                    if not chunk:
                        break
                    buf += chunk
                    if b'"sic"' in buf and b'"sicDescription"' in buf:
                        # 値が切れている可能性に備えもう1チャンクだけ足す
                        extra = r.read(8192)
                        if extra:
                            buf += extra
                        break
            return buf.decode("utf-8", errors="replace"), None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "http 404 (submissions無し)"
            if attempt == 2:
                return None, f"http {e.code}"
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            if attempt == 2:
                return None, f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    return None, "retries exhausted"


def main():
    cohort = json.load(open(COHORT))["rows"]
    cik_map = {}
    for r in cohort:
        t, k = r.get("ticker"), r.get("cik")
        if t and k:
            cik_map[t] = int(k)

    targets = [r["ticker"] for r in json.load(open(RETURNS))["rows"]]

    rows = []
    ok = miss = 0
    t0 = time.time()
    for i, t in enumerate(targets):
        cik = cik_map.get(t)
        if cik is None:
            rows.append({"ticker": t, "error": "cik不明（cohortに無い）"})
            miss += 1
            continue
        buf, err = fetch_head(cik)
        row = {"ticker": t, "cik": cik}
        if buf is None:
            row["error"] = err
            miss += 1
        else:
            m_sic = RE_SIC.search(buf)
            m_desc = RE_DESC.search(buf)
            sic = unescape(m_sic.group(1)).strip() if m_sic else None
            desc = unescape(m_desc.group(1)).strip() if m_desc else None
            if sic:  # キー不在・空文字列はどちらも欠測（0と読まない）
                row["sic"] = sic
                if desc:
                    row["sicDesc"] = desc
                if len(sic) >= 2 and sic[:2].isdigit():
                    row["sic2"] = sic[:2]
                ok += 1
            else:
                row["error"] = ("sicキー不在" if not m_sic else "sic空文字列")
                miss += 1
        rows.append(row)
        if (i + 1) % 50 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(targets)}  ok={ok} miss={miss}  {el:.0f}s", flush=True)
        time.sleep(SLEEP)

    dist = {}
    for r in rows:
        s2 = r.get("sic2")
        if s2:
            dist[s2] = dist.get(s2, 0) + 1
    dist = dict(sorted(dist.items(), key=lambda kv: -kv[1]))

    out = {
        "generated": datetime.date.today().isoformat(),
        "note": ("SEC submissions API の sic/sicDescription。対象=retro_returns_2018 の全ticker、"
                 "CIKはretro_cohort_2013のticker→cik対応。SICは現在の登録分類（時点付きデータではない）"
                 "＝業種の粗い層別専用。sicキー不在・空文字列は欠測として欄を出力しない（0と読まない）。"
                 "sic2=先頭2桁。submissions JSONは先頭チャンクのみ読取（sic系はヘッダ部にあるため）。"
                 f" 採取 {ok}/{len(targets)}・欠測 {miss}。"),
        "sic2_dist": dist,
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"done: {OUT}  ok={ok} miss={miss} total={len(targets)}")
    print("sic2 dist (top20):", dict(list(dist.items())[:20]))


if __name__ == "__main__":
    main()
