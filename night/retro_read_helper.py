#!/usr/bin/env python3
# night/retro_read_helper.py — 追試の読解班が原本を読むための道具（2026-08-05新設）
#
# 読解班が 10-K/20-F の全文をそのまま抱えると文脈が溢れるので、
# **原本を落として、指定した語の周りだけを窓で切り出す**。引用は必ずここから採る。
#
# 使い方（cwd=リポジトリ根）:
#   python3 night/retro_read_helper.py AIR                      # 既定の堀パターンで走査
#   python3 night/retro_read_helper.py AIR --asof 2015          # 2015ビンテージの原本
#   python3 night/retro_read_helper.py AIR --p "qualif;;certif" --w 300
#   python3 night/retro_read_helper.py AIR --sec "Competition"  # 節見出しから2000字
#
# パターンは ';;' 区切り（正規表現・大小無視）。--w は前後の窓（既定260字）。
import json, os, re, sys, html, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
DOC = os.path.join(OUT, "_retro_docs")
HD = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}

DEFAULT = ";;".join([
    r"requalif", r"re-qualif", r"qualif\w* (by|with|for) (our |the )?(customer|OEM|user|agenc)",
    r"customer[^.]{0,60}qualif", r"qualification (process|period|requirement|change)",
    r"approved (supplier|vendor|source)", r"qualified (supplier|vendor|source|for the application)",
    r"certified by", r"certification", r"designed in", r"design-?in", r"designed into",
    r"switching cost", r"sole source", r"single source", r"only (manufacturer|supplier|provider)",
    r"barriers to entry", r"Competition",
])


def plain(url):
    s = urllib.request.urlopen(urllib.request.Request(url, headers=HD), timeout=180).read().decode("utf-8", "ignore")
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s))


def doc(t, asof):
    os.makedirs(DOC, exist_ok=True)
    p = os.path.join(DOC, f"{asof}_{t}.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    rl = json.load(open(os.path.join(OUT, f"retro_readlist_{asof}.json"), encoding="utf-8"))
    row = next((r for r in rl["rows"] if r["ticker"] == t), None)
    if not row:
        sys.exit(f"{t}: readlist_{asof} に無い")
    s = plain(row["url"])
    open(p, "w", encoding="utf-8").write(s)
    return s


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__ or "usage: retro_read_helper.py TICKER [--asof 2013] [--p 'pat;;pat'] [--w 260]")
    t = a[0].upper()
    asof = int(a[a.index("--asof") + 1]) if "--asof" in a else 2013
    w = int(a[a.index("--w") + 1]) if "--w" in a else 260
    s = doc(t, asof)
    if "--sec" in a:
        k = a[a.index("--sec") + 1]
        for m in list(re.finditer(re.escape(k), s, re.I))[:4]:
            print(f"--[{k}]--\n{s[m.start():m.start()+2000]}\n")
        return
    pats = (a[a.index("--p") + 1] if "--p" in a else DEFAULT).split(";;")
    print(f"# {t} asof={asof} 全{len(s)}字")
    seen = []
    for p in pats:
        try:
            it = list(re.finditer(p, s, re.I))
        except re.error as e:
            print(f"  ▲パターン不正 {p}: {e}")
            continue
        for m in it[:6]:
            x, y = max(0, m.start() - w), min(len(s), m.end() + w)
            if any(abs(x - q) < w for q in seen):
                continue
            seen.append(x)
            print(f"--[{p}]--\n{s[x:y]}\n")


if __name__ == "__main__":
    main()
