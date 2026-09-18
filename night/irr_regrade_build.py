#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr_regrade_build.py — 歴史の irr 読解を「今日の規約」で再採点するための入力を作る（2026-09-18新設）

★なぜ要るか（この台帳が12回踏んだ「基準の違う二つを割る」型の、**ラベル版**）:
  門は irr の基礎率として 50:0.162 / 70:0.366 / 85:0.579 を引き続けている。
  だがその数字を作った歴史のラベルは **今日の規約で付けられたものではない**——

    ・**70**: 2026-08-12 の v9.9.144 で「残余」から「積極的な主張（摩擦の機構を名指し＋原本の引用）」へ
      改めた。歴史の 70 は**改定前の残余**。しかも 2026-08-20 の全数二重読みで
      **今日の台帳の 70 は 200社中163社が 50 へ落ちた**＝今日の 70 は歴史の 70 より遥かに狭い。
    ・**85**: 2026-08-05/06 の全数検算で **53社→11社**。しかも実測で
      **同じ111社でも班が違うと 85 の付与率が 5.4%→17.1%（3.2倍・p=0.017）**＝
      歴史の 85 のうち（とくに2018年ビンテージの）相当数は、今日の6検問なら 70 以下になる公算がある。

  ⇒ **「+24.6%/年・P=0.71」も「70:0.366」も、今日の門が使っているラベルについての数字ではないかもしれない。**
  これは効き幅の話ではなく**何を測ったかの話**なので、重みや線をいくら較正しても出てこない。

★既存の道具との違い（重複ではない）:
  `night/irr70_mech_test.py` が同じ問いに**代理変数**で答えている——歴史の `mech` 欄
  （機構の型）が埋まっているかで 70 を割った（named 0.456 vs unnamed 0.297・lift 0.159・perm p=0.049）。
  だがその道具の頭注自身が限界を3つ書いている:
    (a) `mech` は**85の型分けのために記録された欄**で、70 は「たまたま書かれていた」もの
    (b) 「mech が書かれている」は「**その班が丁寧だった**」の代理かもしれない（交絡）
    (c) **2018 は mech が全社『なし』＝42社が構造的に検定できない**
  この道具は **引用そのものを今日の規約で採点し直す**ので (a)(b) が消え、(c) の42社が入る。
  そして **85 側を今日の6検問で再採点するのは初めて**（既存の irr85_mech_test は 85 の *中* の型分け）。

★出力（採点は含まない・入力だけ）: out/irr_regrade_items.json
  採点者には **引用文だけ**を渡す（ティッカー・元の刻み・元の注記・リターンはいっさい渡さない＝盲検）。
使い方: python3 night/irr_regrade_build.py
"""
import json, os, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
L = lambda n: json.load(open(os.path.join(OUT, n), encoding="utf-8"))["rows"]


def build():
    items, meta = [], []
    src = [
        (2013, ["retro_moat_2013.json", "retro_moat_2013q.json"], "ticker", "irr", "quote",
         "retro_returns_2013_all.json"),
        (2015, ["retro_moat_2015.json", "retro_moat_2015q.json", "retro_moat_2015qb.json"], "ticker", "irr", "quote",
         "retro_returns_2015_q.json"),
        (2018, ["retro_moat_2018.json", "retro_moat_2018_rest.json"], "t", "irr18", "irr_quote",
         "retro_returns_2018.json"),
    ]
    seen = set()
    for v, files, tk, rk, qk, rf in src:
        R = {r["ticker"]: r for r in L(rf)}
        rows = []
        for f in files:
            rows += L(f)
        for r in rows:
            rung = r.get(rk)
            # 2018 の中間刻みは 75（2013/2015 は 70）。どちらも「高摩擦移行困難」で同じ段。
            if rung not in (70, 75, 85):
                continue
            q = (r.get(qk) or "").strip()
            t = r.get(tk)
            if not q or not t:
                continue
            key = (v, t)
            if key in seen:
                continue
            seen.add(key)
            ret = R.get(t) or {}
            iid = "Q" + hashlib.sha1(f"{v}|{t}".encode()).hexdigest()[:8]
            items.append({"id": iid, "quote": q})
            meta.append({"id": iid, "v": v, "t": t, "orig": rung,
                         "mech": r.get("mech"), "tense": r.get("tense"), "moat5": r.get("moat5"),
                         "tr": ret.get("tr_cagr"), "tot": ret.get("tr_total"), "mdd": ret.get("mdd")})
    return items, meta


def main():
    items, meta = build()
    json.dump({"generated": "2026-09-18", "n": len(items),
               "note": "採点者へ渡すのは quote だけ。ティッカー・元の刻み・リターンは meta 側にあり渡さない",
               "rows": items}, open(os.path.join(OUT, "irr_regrade_items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"generated": "2026-09-18", "n": len(meta), "rows": meta},
              open(os.path.join(OUT, "irr_regrade_meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    from collections import Counter
    print("items:", len(items))
    print("ビンテージ×元の刻み:", Counter((m["v"], m["orig"]) for m in meta))
    print("リターン有り:", sum(1 for m in meta if m["tr"] is not None))
    print("引用の長さ 中央値:", sorted(len(i["quote"]) for i in items)[len(items) // 2])


if __name__ == "__main__":
    main()
