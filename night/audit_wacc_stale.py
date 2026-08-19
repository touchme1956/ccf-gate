#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_wacc_stale.py — **WACCの既定値（無リスク金利）が古くなっていないか**（2026-08-07新設）

なぜ要るか（2026-08-07の全点検で見つけた）:
  `rfr`（無リスク金利＝米10年債利回り）は index.html に **ハードコード**され（現行 `value="4.68"`）、
  月1回**手で**更新する運用になっている。todo_list.json 自身が
  「定期(手動)＝**忘れても盤が検出できない種類**」と書いており、実際に検出器が無かった。

  実測（2026-08-07）: 門の既定 4.48 は **2026-05の値**。FREDの最新は 4.63（2026-08-05）＝**0.15pt 古い**。
  そしてこの 0.15pt は小さくない——**+0.12pt を当てただけで 116社のΩが動き、最大 10.20pt**
  （SPGI 58.0→47.8 / ZWS 68.3→60.3）。原因は `roicg < WACC → −8` のキルで、
  **崖が小さなズレを10pt級の跳ねに増幅する**。投下可の顔ぶれは今日は変わらないが、
  「気づかないうちに全台帳が動いている」状態は、この門が繰り返し潰してきた型そのもの。

★この検出器が実際に効いた（2026-08-19）: 乖離 0.2（市場4.68 vs 門4.48）で発火し、既定を **4.48→4.68** へ更新した。
  影の計測は頭注の実測を独立に再現した——**150社のΩが動き最大 −10.3pt（SPGI 57.7→47.4 / ZWS 67.0→59.0）、
  投下可10社とΩ75+ 30社はいずれも不変**。動くのは `roicg<WACC → −8` の崖を跨ぐ社だけで、3社とも判定圏外だった。
  ⚠ パックが持つ rfr は18社とも **4.69**（2026-07/08の日本株審査で審査官が入れた実測値）で、
  既定との差は 0.01＝入力欄の step 0.1 未満なので触っていない。**既定を上げたことで混在はむしろ縮んだ**。
  ⚠ ERP(4.45) は触っていない——Damodaran implied ERP は公開CSVの取得先が無く、この検出器も見ていない。

何を測るか:
  FREDの公開CSV（**鍵不要**）から米10年債利回り DGS10 の最新値を取り、
  index.html の `rfr` 既定値と比べる。

  **閾値は発明していない**——入力欄自身が持つ `step="0.1"` を「意味のある変化」の単位として使う。
  刻みより大きくズレたら報告する、というだけ。

思想:
  この道具は**読むだけ**。値は書き換えない（rfr の更新はユーザーの月次ルーチン＝
  「買うリズムと選ぶリズムを分ける」の設計に属する。自動で毎日当てるとΩが債券市場と一緒に
  日々ドリフトし、選ぶリズムが壊れる）。**自動化するのは適用ではなく検出**。

使い方:
  python3 night/audit_wacc_stale.py            表示のみ
  python3 night/audit_wacc_stale.py --write    out/wacc_drift.json を更新（回転盤が読む）
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
WRITE = "--write" in sys.argv[1:]


def latest_dgs10():
    """FREDの公開CSV（鍵不要）から最新の米10年債利回りを返す。休場日は '.' なので飛ばす。"""
    req = urllib.request.Request(FRED, headers={"User-Agent": "ccf-gate fortis5280@gmail.com"})
    with urllib.request.urlopen(req, timeout=45) as r:
        txt = r.read().decode("utf-8", "ignore")
    for line in reversed(txt.strip().splitlines()):
        parts = line.split(",")
        if len(parts) != 2:
            continue
        d, v = parts[0].strip(), parts[1].strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            continue
        try:
            return d, float(v)
        except ValueError:
            continue          # 休場日の '.'
    return None, None


def gate_rfr(h):
    """門の rfr 既定値と刻み。HTMLの既定と JS のフォールバックが**食い違っていないか**も見る
    ——片方だけ直すのはこの repo が繰り返している型なので、ここで捕まえる。"""
    m = re.search(r'id="rfr"[^>]*?step="([\d.]+)"[^>]*?value="([\d.]+)"', h)
    html_v = float(m.group(2)) if m else None
    step = float(m.group(1)) if m else 0.1
    m2 = re.search(r"n\('rfr'\)\s*\|\|\s*([\d.]+)", h)
    js_v = float(m2.group(1)) if m2 else None
    return html_v, js_v, step


def main():
    h = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    html_v, js_v, step = gate_rfr(h)
    d, cur = latest_dgs10()

    print("■ WACCの既定値（無リスク金利 rfr）が古くなっていないか")
    print(f"  門の既定    HTML {html_v} ／ JSフォールバック {js_v}（刻み {step}）")
    if html_v is None or cur is None:
        print("  ✗ 取得できなかった（門側 or FRED）。**取れないことを『異常なし』と偽らない**")
        return 0
    print(f"  市場の実勢  {cur}（米10年債 DGS10・FRED {d}・鍵不要の公開CSV）")

    bad = False
    if js_v is not None and html_v != js_v:
        print(f"  ⚠ **門の中で二つの既定が食い違っている**（HTML {html_v} ≠ JS {js_v}）"
              f"——片方だけ直した痕跡。両方を揃えること")
        bad = True

    drift = cur - html_v
    print(f"  ズレ        {drift:+.2f}pt")
    if abs(drift) > step:
        print(f"  ⚠ **刻み({step})より大きくズレている＝更新どき**")
        print(f"     index.html の `id=\"rfr\"` の value と、`n('rfr')||…` のフォールバックを"
              f"**両方** {cur} へ。更新後は `node night/score_all.js` で影響を確認すること")
        print(f"     ※ 参考: 2026-08-07の実測では +0.12pt を当てただけで **116社のΩが動き最大10.20pt**"
              f"（`roicg<WACC` のキルが小さなズレを増幅する）")
        bad = True
    else:
        print(f"  ✓ 刻み({step})の範囲内")

    if WRITE:
        p = os.path.join(ROOT, "out", "wacc_drift.json")
        json.dump({"asof": str(date.today()), "source": "FRED DGS10 (公開CSV・鍵不要)",
                   "market": {"date": d, "rfr": cur},
                   "gate": {"html": html_v, "js": js_v, "step": step},
                   "drift": round(drift, 3), "stale": bool(abs(drift) > step),
                   "rule": "入力欄自身の step より大きくズレたら更新どき（新しい閾値は作らない）"},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を更新")
    else:
        print("\n（--write で out/wacc_drift.json を更新する）")
    return 0 if not bad else 0     # 落とさない＝作業リストであって関門ではない


if __name__ == "__main__":
    sys.exit(main())
