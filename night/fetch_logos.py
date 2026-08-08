#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fetch_logos.py — 銘柄アイコンを **リポジトリに取り込む**（2026-08-06新設・ユーザー要望「各銘柄にその企業のアイコンを入れてほしい」）

なぜ外部CDNを直接参照しないか:
  門は GitHub Pages の静的ページで、価格すら「同一オリジンの out/*.json を読むだけ」という作り
  （盤 v9.9.58 の設計思想＝CORSも認証もサーバーも要らない）。アイコンだけ毎回外部ホストを叩くと、
  (a)外部が落ちれば表示が欠ける (b)閲覧のたびに第三者へ銘柄リストが漏れる (c)オフラインで崩れる。
  → **CIで取り込んで out/logos/ に置き、門は同一オリジンで読む。**

取れなかった銘柄は「無い」ままにする（ルール7: 欠測を別物で埋めない）。
門の側は取れなかった銘柄を **モノグラム（ティッカー先頭文字の色付き丸）** で描くので、
表示が欠けることはなく、かつ「本物のロゴ」と「代替の印」が見た目で区別できる。

出典: assets.parqet.com（SVG・小さい）→ 失敗したら financialmodelingprep.com（PNG）。
      日本株（4桁数字コード）は `.T` を付けて引く。
      ロゴは各社の商標であり、ここでの利用は**銘柄の識別**のための名目的使用に限る。

使い方:
  python3 night/fetch_logos.py            # 未取得のぶんだけ取る
  python3 night/fetch_logos.py --all      # 既存も取り直す
  python3 night/fetch_logos.py --only MSFT,6146
出力: out/logos/{T}.svg|.png ＋ out/logos/index.json（取得状況＝穴が見えるようにする）
"""
import json, os, re, sys, glob, time, urllib.request, concurrent.futures as cf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
DIR = os.path.join(OUT, "logos")
HD = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
SRC = [("parqet", "https://assets.parqet.com/logos/symbol/{q}", "svg"),
       ("fmp", "https://financialmodelingprep.com/image-stock/{q}.png", "png")]


def is_jp(t):
    return bool(re.fullmatch(r"\d{4}", t))


def tickers():
    ts = {os.path.basename(p).rsplit("_gate_pack", 1)[0] for p in glob.glob(os.path.join(OUT, "*_gate_pack.json"))}
    p = os.path.join(BASE, "kanshi_list.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        for k in ("list", "tickers", "pin"):
            ts |= {str(x).strip().split()[0].upper() for x in (d.get(k) or [])}
    return sorted(x for x in ts if x and re.fullmatch(r"[A-Z0-9.\-]{1,8}", x))


def existing(t):
    for e in ("svg", "png"):
        p = os.path.join(DIR, f"{t}.{e}")
        if os.path.exists(p) and os.path.getsize(p) > 120:
            return e
    return None


def grab(t):
    q = f"{t}.T" if is_jp(t) else t
    for name, tmpl, ext in SRC:
        try:
            r = urllib.request.urlopen(urllib.request.Request(tmpl.format(q=q), headers=HD), timeout=25)
            b = r.read()
        except Exception:
            continue
        # 中身の検問——404本文やHTMLエラーページを画像として保存しない（ルール7の作法）
        if len(b) < 120:
            continue
        head = b[:400].lstrip()
        if ext == "svg" and not head.startswith(b"<svg") and b"<svg" not in head:
            continue
        if ext == "png" and not b.startswith(b"\x89PNG"):
            continue
        tmp = os.path.join(DIR, f"{t}.{ext}.part")
        open(tmp, "wb").write(b)
        os.replace(tmp, os.path.join(DIR, f"{t}.{ext}"))
        return t, ext, name, len(b)
    return t, None, None, 0


def main():
    os.makedirs(DIR, exist_ok=True)
    a = sys.argv[1:]
    ts = tickers()
    if "--only" in a:
        want = {x.strip().upper() for x in a[a.index("--only") + 1].split(",")}
        ts = [t for t in ts if t in want]
    todo = ts if "--all" in a else [t for t in ts if not existing(t)]
    print(f"対象 {len(ts)}銘柄 / 取得 {len(todo)}（既存 {len(ts)-len(todo)}）")
    got, miss = {}, []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, (t, ext, src, n) in enumerate(ex.map(grab, todo), 1):
            if ext:
                got[t] = {"ext": ext, "src": src, "bytes": n}
            else:
                miss.append(t)
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}  取得{len(got)} 未取得{len(miss)}", flush=True)
    idx = {t: existing(t) for t in ts}
    idx = {t: e for t, e in idx.items() if e}
    total = sum(os.path.getsize(os.path.join(DIR, f"{t}.{e}")) for t, e in idx.items())
    o = {"generated": time.strftime("%Y-%m-%d"), "n": len(idx), "bytes": total,
         "note": "門は同一オリジンで out/logos/{T}.{ext} を読む。無い銘柄はモノグラムで描く（欠測を別物で埋めない）",
         "have": idx, "missing": sorted(set(ts) - set(idx))}
    json.dump(o, open(os.path.join(DIR, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n取得済み **{len(idx)}/{len(ts)}銘柄**（合計 {total/1024:.0f}KB）")
    if o["missing"]:
        print(f"未取得 {len(o['missing'])}: {' '.join(o['missing'][:40])}")
    print(f"→ {DIR}/index.json")


if __name__ == "__main__":
    main()
