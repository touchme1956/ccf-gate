#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_rung_top.py — **堀の刻みの「最上段」を一つ下として採点したら誰がどう動くか**（2026-08-12新設）

★これは影の計測であって規約の変更ではない。index.html を一時的に書き換えて score_all を回し、
  **必ず元へ戻す**（shadow_gmpt.py と同じ型）。値・採点式・関門・売却規律は正本では一切動かない。

■ なぜ測るか（歴史の実測）
  事前登録つきの読解（2013:249社 / 2015:505社）で、**最上段が一つ下の段を下回る**が繰り返し出た:
    irr=100  … 2013/2015/2018 の**3ビンテージすべてで最下位**（既記録）
    dur=100  … 2013 (+0.1319 < 85の+0.1720) / 2015 (+0.0875 < 85の+0.1461・n=86と厚い) ＝**2回とも逆転**
    rep=100  … 2015のみ逆転（n=7＝薄い）。2013は n=1 で読めない
    dom=100  … 2015のみ逆転（85 n=3 / 100 n=8＝両方薄い）。2013はデータ無し
    moatW=100… 2013はほぼ同値・**2015は正順（100のほうが高い）＝逆転していない**
  ⇒ **証拠の強さは柱ごとにまったく違う**。だから一律に当てず、柱ごとに測って出す。

■ 変更の形（新しい定数を発明しない）
  「最上段を**一つ下の刻みの値**として採点する」だけ。irr/dur/dom/moatW は 100→85、rep は 100→80。
  どれも**既存の刻みの値**なので、新しい数字を持ち込まない。

実行: python3 night/shadow_rung_top.py [--json]
"""
import json, os, re, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
ANCHOR = ("  const legs=Object.keys(W).map(k=>[k,num(d[k])])"
          ".filter(l=>l[1]!=null&&l[1]>0);")
NEXT = {"irr": 85, "dur": 85, "rep": 80, "dom": 85, "moatW": 85}
CASES = [
    ("A  irr のみ", {"irr"}),
    ("B  dur のみ", {"dur"}),
    ("C  irr + dur（証拠が2ビンテージ以上）", {"irr", "dur"}),
    ("D  irr+dur+rep+dom（moatWは逆転していないので外す）", {"irr", "dur", "rep", "dom"}),
    ("E  5本すべて（参考・過剰）", set(NEXT)),
]


def run():
    r = subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("score_all が失敗:\n" + r.stderr[-1500:])
    d = json.load(open("out/score_all.json", encoding="utf-8"))
    rs = d["rows"] if isinstance(d, dict) and "rows" in d else d
    out = {}
    for x in rs:
        t = (x.get("t") or x.get("ticker") or x.get("nm") or "").split()[0]
        if t:
            out[t] = x
    return out


def main():
    src = open(HTML, encoding="utf-8").read()
    if ANCHOR not in src:
        raise SystemExit("錨が見つからない——index.html の ccfMoat が変わった。**当てずに止める**")
    bak = tempfile.mktemp(suffix=".html")
    shutil.copy(HTML, bak)
    shutil.copy("out/score_all.json", bak + ".json")
    res = {}
    try:
        base = run()
        buy0 = [t for t, r in base.items() if r.get("buy")]
        res["base"] = {"buy": sorted(buy0), "n_buy": len(buy0)}
        for label, keys in CASES:
            cap = {k: NEXT[k] for k in keys}
            patched = ANCHOR.replace(
                "map(k=>[k,num(d[k])])",
                "map(k=>[k,(function(v){var C=%s;return (C[k]!=null&&v===100)?C[k]:v;})(num(d[k]))])"
                % json.dumps(cap))
            open(HTML, "w", encoding="utf-8").write(src.replace(ANCHOR, patched))
            cur = run()
            buy = [t for t, r in cur.items() if r.get("buy")]
            moved = {t: (round(base[t].get("s") or 0, 1), round(cur[t].get("s") or 0, 1))
                     for t in cur if t in base
                     and abs((cur[t].get("s") or 0) - (base[t].get("s") or 0)) >= 0.05}
            res[label] = {
                "cap": cap, "n_buy": len(buy), "buy": sorted(buy),
                "out": sorted(set(buy0) - set(buy)), "in": sorted(set(buy) - set(buy0)),
                "n_moved": len(moved),
                "worst": sorted(((v[1] - v[0]), t) for t, v in moved.items())[:6],
            }
    finally:
        shutil.copy(bak, HTML)
        shutil.copy(bak + ".json", "out/score_all.json")
        os.remove(bak); os.remove(bak + ".json")
    same = open(HTML, encoding="utf-8").read() == src
    res["_restored"] = same
    if not same:
        raise SystemExit("⚠ 復元に失敗した——index.html を git checkout すること")

    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print("■ 堀の刻みの『最上段を一つ下として採点』——影の計測（正本は不変・復元済✓）\n")
    print(f"  現行  投下可 {res['base']['n_buy']}社: {' '.join(res['base']['buy'])}\n")
    for label, _ in CASES:
        r = res[label]
        print(f"  {label}")
        print(f"     置き換え {r['cap']}  → 投下可 {r['n_buy']}社 ／ Ωが動く {r['n_moved']}社")
        if r["out"] or r["in"]:
            print(f"     **出 {' '.join(r['out']) or 'なし'} ／ 入 {' '.join(r['in']) or 'なし'}**")
        else:
            print("     **顔ぶれは不変**")
        if r["worst"]:
            print("     Ωの下げ幅 上位: " + " / ".join(f"{t} {d:+.1f}" for d, t in r["worst"]))
        print()


if __name__ == "__main__":
    main()
