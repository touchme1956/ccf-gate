#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/apply_prices.py — 実測価格をパックへ自動反映する（2026-08-02新設）

なぜ自動化してよいか（2026-08-02の実測で確認）:
  ・**株価はΩをほぼ動かさない** — 全社の株価を+10%振ってもΩが0.05pt超動くのは 8/317社、最大0.30pt。
    質の採点は価格から独立している（設計どおり）。
  ・**日々の値動きでは投下可が入れ替わらない** — ±1%/±2%/±3% のいずれでも出入り**0社**。
    ±5%でようやく3社（しかも戻ってくる方向）。つまり「毎日ガチャガチャ動く」は起きない。
  ・動くのは 6857 の+14.5% や MSFT の+16.6% のような**大きな動きのときだけ**で、それは動くべきとき。

危険なのは自動更新ではなく **古い価格** のほうだった（2026-08-02に二度実証）:
  MSFT は台帳が16.6%古かったせいで投下可に残り続け、6857 も同じ理由で残っていた。
  門Xの「良い会社を高値で掴まない」という役目が、価格が古いというだけで空回りしていた。

設計上まもるもの:
  ・**kenshi には積まない**。毎日317行を積むと年8万行になり、監査記録が読めなくなる。
    今日 MA の ROIC で「後から書かれた記録を先に探す」ことで事故を回避しており、
    **記録が埋もれるのは実害**。価格の履歴は git が持っている。
    → `_meta.market` に**最新1件だけ上書き**する。
  ・**採点式・Ω・売却規律S1/S2/S3・門X閾値・堀の関門には触れない**。動かすのは市場欄だけ。
  ・換算は**基準保存式** per_new = per_old × (px_new ÷ px_old)。px÷eps で計算し直すと
    eps欄がTTM実績か通期実績かで**期間基準が黙って切り替わる**（v9.9.57の決着）。
  ・`_meta.nulls` に「空欄と決めた理由」がある欄は触らない（v9.9.61でmarket_mergeに入れた関門と同じ）。
  ・記録は `_meta.px` へ。`_meta.market` は market_merge の充填履歴なので使わない（衝突を試験で確認）。
  ・**投下可の出入りが起きたときだけ**コミットメッセージに明記する。埋もれさせないため。
"""
import json, os, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
SCALE = ("per", "perF", "evebit")      # 価格に比例する欄
INVERSE = ("shy",)                     # 還元額が不変で時価だけ動く＝1/比率


def buy_set():
    """門そのもの（score_all.js）で投下可を出す。推測しない。"""
    try:
        subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True, timeout=300)
        rows = json.load(open("out/score_all.json", encoding="utf-8"))
        return {r["t"] for r in rows if r.get("buy") is True}
    except Exception as e:
        print(f"  ▲ 投下可の判定に失敗: {e}")
        return None


def main():
    write = "--write" in sys.argv
    try:
        D = json.load(open("out/dashboard.json", encoding="utf-8"))
    except Exception:
        print("out/dashboard.json が無い → 何もしない")
        return 0
    Q, ASOF = D.get("quotes") or {}, (D.get("asof") or "")[:10]
    if not Q:
        print("株価が空 → 何もしない")
        return 0

    before = buy_set() if write else None
    rows, protected = [], []
    for f in sorted(os.listdir("out")):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f[: -len("_gate_pack.json")]
        q = Q.get(t.upper()) or Q.get(t)
        if not q or not q.get("px"):
            continue
        P = "out/" + f
        try:
            d = json.load(open(P, encoding="utf-8"))
        except Exception:
            continue
        try:
            old = float(d.get("px"))
        except Exception:
            old = None
        if not old or old <= 0:
            continue
        new = float(q["px"])
        r = new / old
        if abs(r - 1) < 0.0005:            # 動いていない社は触らない（無用なコミットを作らない）
            continue
        meta = d.setdefault("_meta", {})
        decided = set((meta.get("nulls") or {}))
        chg = []
        for k in SCALE + INVERSE:
            if k in decided:               # 「空欄と決めた」欄は機械が埋め戻さない
                protected.append(f"{t}.{k}")
                continue
            v = d.get(k)
            if v in (None, ""):
                continue
            nv = round(float(v) * (1 / r if k in INVERSE else r), 1 if k == "evebit" else 2)
            chg.append((k, v, nv))
        rows.append((t, old, new, r, chg))
        if write:
            for k, _, nv in chg:
                d[k] = nv
            d["px"] = new
            d["ddate"] = ASOF
            # **kenshi には積まない**。最新1件だけを `_meta.px` に上書きする（履歴はgitが持つ）。
            #   キー名は `market` を避ける——**そちらは market_merge.py が「どの欄をnull充填したか」の
            #   記録に使っており**、上書きすると充填履歴が消える（2026-08-02の試験で衝突を発見）。
            meta["px"] = {
                "date": ASOF, "day": q.get("day"), "ccy": q.get("ccy", "USD"),
                "src": "Yahoo Finance(東証)" if q.get("ccy") == "JPY" else "Finnhub",
                "px_old": old, "px_new": new, "pct": round((r - 1) * 100, 2),
                "conv": "基準保存式 per_new = per_old × (px_new÷px_old)／shy は 1/比率",
                "fields": {k: nv for k, _, nv in chg},
            }
            json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    rows.sort(key=lambda x: -abs(x[3] - 1))
    print(f"価格が動いた {len(rows)}社" + ("（**書込済み**）" if write else "（--write で書込）"))
    for t, o, n, r, _ in rows[:8]:
        print(f"  {t:8}{o:12,.2f} → {n:12,.2f}  {(r-1)*100:+6.1f}%")
    if protected:
        print(f"  🛡 空欄と決めた欄は触らず: {' / '.join(protected[:8])}")

    msg = f"market prices {ASOF}｜{len(rows)}社"
    if write and before is not None:
        after = buy_set()
        if after is not None and after != before:
            gone, came = sorted(before - after), sorted(after - before)
            parts = []
            if gone:
                parts.append("投下可から外れた: " + " ".join(gone))
            if came:
                parts.append("投下可に入った: " + " ".join(came))
            msg += "｜★" + " / ".join(parts) + f"（{len(before)}社→{len(after)}社）"
            print("\n★ 投下可が動いた: " + " / ".join(parts))
        else:
            msg += "｜投下可は不変"
            print("\n投下可は不変")
    open("out/_price_commit_msg.txt", "w", encoding="utf-8").write(msg + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
