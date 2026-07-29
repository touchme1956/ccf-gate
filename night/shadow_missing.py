#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_missing.py — 欠測の扱いを変えたら誰がどう動くかの影の計測（pen＝TAM浸透率）

なぜ要るか:
  門は「欠測をゼロと読まない」を何度も直してきた。
    p3  : 「Z空欄→25点(倒産圏=最悪)・nde空欄→100点(最良)と**欠測の扱いが真逆だった**」→ 落として再正規化
    dom : パックの null が SELECT既定70に化けて「測っていない」が「測って70」になっていた（v9.9.39）→ 空欄選択肢＋再正規化
    moatW: 同上
  ところが **pen（TAM浸透率）だけが取り残されている**。実測（2026-07-29・全316パック）:
    ・pen は **316社すべてが空欄**。門は n('pen')=parseFloat('')||0 で **0** と読む
    ・pt = 58 + (60−pen)×0.45 + cagr×1.8 なので pen=0 は「浸透率0%＝滑走路無限」として
      **+27点の満額ボーナス**。cagr≥8.3% なら pt=100 に張り付く
    ・結果 **202社(64%)が pt=100**。sustain の20%を占める柱が、ほぼ全社で同じ値＝定数になっている
  「測っていない」が最良評価に化ける形で、gmPt（v9.9.43で是正）と同じ「情報を持たない項」を作っていた。

  なお同じ調査で判った、**是正が要らないもの**も記録しておく（鳴らす必要のない警報を増やさないため）:
    ・sht  316社が空欄→既定flat。ただし flat の調整量は **0** なので中立と一致＝採点への実害なし
      （台帳表示が「横ばい」と出るのは誤解を招くので、選択肢に「未測定」を足すのが筋）
    ・roict 37社が空欄→flat。同上（flat=0で中立）
    ・irr/rep/dur は**空欄の選択肢が無い**ので null は既定(70/60/85)に化けるが、実測では空欄0社＝
      現時点の実害なし。dom/moatW と同じ穴が3本残っている（将来の穴）
    ・p1-p4/f1-f5 の空欄は 2社のみ（ABNB f3 / TGS p1）

案:
  A 現行            pen 空欄 → 0 と読む（+27点の満額）
  B 中立値          pen 空欄 → 30% として扱う（+13.5点）
  C 落として再正規化  pen 空欄 → pt を sustain から外し [pm,pr] を [.475,.525] で再正規化
                     （p3・dom・moatW と同じ形＝門の既存の作法）
使い方: python3 night/shadow_missing.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"

PT = "let pt=Math.max(0,Math.min(100,58+(60-pen)*0.45+cagr*1.8));"
SUS = "let sustain=gm([pm,pr,pt],[0.38,0.42,0.20]);"

PATCH = {
    "A 現行（空欄=0=満額+27）": [],
    "B 中立値（空欄=30%）": [(PT, "let pt=Math.max(0,Math.min(100,58+(60-(nn('pen')==null?30:pen))*0.45+cagr*1.8));")],
    "C 落として再正規化": [(SUS, "let sustain=(nn('pen')==null)?gm([pm,pr],[0.475,0.525]):gm([pm,pr,pt],[0.38,0.42,0.20]);")],
}


def run():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    return json.load(open("out/score_all.json", encoding="utf-8"))


def main():
    src = open(HTML, encoding="utf-8").read()
    for pairs in PATCH.values():
        for old, _ in pairs:
            if old not in src:
                print(f"index.html に想定の式が無い: {old[:60]}…")
                return 1
    bak = tempfile.mkdtemp(prefix="ccf_html_")
    shutil.copy2(HTML, os.path.join(bak, "index.html"))
    res = {}
    try:
        for label, pairs in PATCH.items():
            cur = src
            for old, new in pairs:
                cur = cur.replace(old, new)
            open(HTML, "w", encoding="utf-8").write(cur)
            rows = run()
            res[label] = {r["t"]: r for r in rows}
            q75 = [r for r in rows if (r.get("s") or 0) >= 75]
            buy = sorted(r["t"] for r in rows if r.get("buy"))
            med = sorted((r.get("s") or 0) for r in rows)[len(rows) // 2]
            print(f"{label:26s} Ω中央値 {med:5.1f} / Ω75+ {len(q75):3d}社 / 🟢投下可 {len(buy):2d}社"
                  f"  ({' '.join(buy) or 'なし'})")
    finally:
        shutil.copy2(os.path.join(bak, "index.html"), HTML)
        shutil.rmtree(bak, ignore_errors=True)
        run()
        print("\n※index.html と score_all.json は元へ戻した（影の計測であって正本は変えていない）")

    base = res["A 現行（空欄=0=満額+27）"]
    for label in list(PATCH)[1:]:
        cur = res[label]
        d = sorted(((cur[t]["s"] - base[t]["s"], t) for t in base if t in cur))
        print(f"\n=== {label} — 現行との差")
        print(f"  下がる {sum(1 for x in d if x[0] < -0.05)}社 / 変わらない "
              f"{sum(1 for x in d if abs(x[0]) <= 0.05)}社 / 上がる {sum(1 for x in d if x[0] > 0.05)}社"
              f" / 最大の下げ {d[0][0]:+.1f}pt")
        print("  下げ幅の大きい順（上位10）:")
        for dl, t in d[:10]:
            print(f"    {t:6s} Ω{base[t]['s']:5.1f} → {cur[t]['s']:5.1f} ({dl:+.1f})"
                  + ("  ← 投下可から外れる" if base[t].get("buy") and not cur[t].get("buy") else ""))
        gone = sorted(t for t in cur if base[t].get("buy") and not cur[t].get("buy"))
        add = sorted(t for t in cur if cur[t].get("buy") and not base[t].get("buy"))
        print(f"  投下可から外れる: {' '.join(gone) or 'なし'} / 入る: {' '.join(add) or 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
