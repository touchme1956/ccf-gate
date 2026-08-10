#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/build_sic_cache.py — **SIC業種キャッシュを作る**（2026-08-10新設）

■ なぜ要るか（実測の穴）
  `night/fill_sht.py:92-93` は `out/_sic_cache.json` が無ければ
  `sys.exit("先にSICキャッシュを作ること")` で止まる。ところが——
  **そのキャッシュを作る道具がリポジトリに一本も存在しなかった**
  （`grep -rln "_sic_cache" --include=*.py` → fill_sht.py だけ）。

  結果として **`sht`（シェア趨勢）は全369社中 322社が空欄**。門は空欄を SELECT 既定の
  `'flat'` に化かすので、sht を使う規則が**まるごと不発**のまま残っていた:
    ・pm ±3 / −10（堀柱の加減点）
    ・地味業界の勝者 +2
    ・**Intel警報（gmt=down ∧ sht=down＝堀崩壊の先行検出）**
    ・S2売却規律「堀の軌道反転」／S2「ROIC×(粗利orシェア)同時劣化」の sht の側
  CLAUDE.md が「**Intelという実例から作った先行警報が一度も鳴っていない**」と記録している、
  その原因がこれ。道具の欠落であって、規約の問題ではない。

■ 何をするか（判定はしない・キャッシュを作るだけ）
  1. SEC の company_tickers.json で **ticker → CIK** を引く
  2. 各CIKの submissions JSON の**先頭チャンクだけ**読んで "sic" / "sicDescription" を抜く
     （数MBある社もあるが sic はヘッダ部にある。`night/retro_sic.py:9-13` の作法をそのまま踏襲）
  3. `out/_sic_cache.json` に {ticker: {cik, sic, sic2, desc}} で貯める

  **増分**——既にキャッシュにある ticker は引き直さない（`--force` で全部引き直す）。
  月次で回すと新規上場ぶんだけが数十件増える形になる。

■ ルール7の作法
  ・「タグが無い」と「値が空」を区別する。sic が取れなければ **その社は書かない**
    （0や"" で埋めない）。理由は `_errors` に残す
  ・母集団は `gate0_all.csv` の **ccy=USD の社だけ**——fill_sht が同業比を USD建てに
    限っているのと同じ理由（名目成長に現地インフレが乗るため）。ここで揃えておかないと
    「基準の違う二つを割る」型になる

使い方:
  python3 night/build_sic_cache.py              増分（キャッシュに無い社だけ引く）
  python3 night/build_sic_cache.py --force      全部引き直す
  python3 night/build_sic_cache.py --limit 200  上限つき（試し打ち）
"""
import csv
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
CACHE = os.path.join("out", "_sic_cache.json")
UA = {"User-Agent": "CCF-Omega-Screener fortis5280@gmail.com",
      "Accept-Encoding": "identity"}
SLEEP = 0.13                      # 毎秒8リクエスト以下（SECは10req/s）
RE_SIC = re.compile(r'"sic"\s*:\s*"((?:[^"\\]|\\.)*)"')
RE_DESC = re.compile(r'"sicDescription"\s*:\s*"((?:[^"\\]|\\.)*)"')

FORCE = "--force" in sys.argv
LIMIT = None
if "--limit" in sys.argv:
    i = sys.argv.index("--limit")
    if i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])


def get(url, head=None, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read(head) if head else r.read()
        except Exception:
            time.sleep(1.0 * (a + 1))
    return None


def ticker_map():
    """SEC公式の ticker → CIK。**これが唯一の正しい経路**——
    ティッカーを推測でCIKへ変換すると AMBIQ で踏んだ『別会社の財務が台帳に入る』事故になる"""
    raw = get("https://www.sec.gov/files/company_tickers.json")
    if not raw:
        sys.exit("company_tickers.json を取得できない")
    d = json.loads(raw)
    out = {}
    for v in d.values():
        t = str(v.get("ticker") or "").upper()
        if t:
            out.setdefault(t, str(v.get("cik_str")).zfill(10))
    return out


def universe():
    """gate0_all.csv の ccy=USD の ticker（fill_sht の母集団と揃える）"""
    if not os.path.exists("gate0_all.csv"):
        sys.exit("gate0_all.csv が無い（門0の出力。先に run_gate0_local.py を回すこと）")
    ts = []
    for r in csv.DictReader(open("gate0_all.csv", encoding="utf-8-sig")):
        if (r.get("ccy") or "").upper() != "USD":
            continue
        t = (r.get("ticker") or "").strip().upper()
        if t:
            ts.append(t)
    return sorted(set(ts))


def main():
    cache = {}
    if os.path.exists(CACHE) and not FORCE:
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    errs = cache.pop("_errors", {}) if isinstance(cache.get("_errors"), dict) else {}

    uni = universe()
    tmap = ticker_map()
    todo = [t for t in uni if t not in cache]
    if LIMIT:
        todo = todo[:LIMIT]
    print(f"母集団 {len(uni)}社（USD）／キャッシュ済 {len(cache)}社／今回引く {len(todo)}社",
          file=sys.stderr)

    got = miss = 0
    for i, t in enumerate(todo, 1):
        cik = tmap.get(t)
        if not cik:
            errs[t] = "SECの ticker→CIK 表に無い"
            miss += 1
            continue
        raw = get(f"https://data.sec.gov/submissions/CIK{cik}.json", head=8192)
        time.sleep(SLEEP)
        if not raw:
            errs[t] = "submissions 取得失敗"
            miss += 1
            continue
        txt = raw.decode("utf-8", "ignore")
        ms, md = RE_SIC.search(txt), RE_DESC.search(txt)
        sic = json.loads('"%s"' % ms.group(1)) if ms else ""
        desc = json.loads('"%s"' % md.group(1)) if md else ""
        if not sic:
            # 「タグが無い」を 0 や "" で埋めない（絶対のルール7）
            errs[t] = "sic が空（登録分類なし）"
            miss += 1
            continue
        errs.pop(t, None)
        cache[t] = {"cik": cik, "sic": sic,
                    "sic2": sic[:2] if sic[:2].isdigit() else None, "desc": desc}
        got += 1
        if i % 200 == 0:
            print(f"  …{i}/{len(todo)}（取得{got} / 欠測{miss}）", file=sys.stderr)
            json.dump({**cache, "_errors": errs}, open(CACHE, "w", encoding="utf-8"),
                      ensure_ascii=False)

    json.dump({**cache, "_errors": errs}, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    n = len([k for k in cache if not k.startswith("_")])
    print(f"■ {CACHE}  {n}社（今回 +{got} / 欠測{miss}・理由つき {len(errs)}件）")
    print("   → python3 night/fill_sht.py --json で sht の作業リストが出る"
          "（--write はパックへ書くので審査官の手＝絶対のルール2）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
