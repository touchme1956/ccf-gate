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
# B24(2026-08-04): evebit を SCALE から外した。EV = 時価総額 + 純負債 のうち**価格に比例するのは
#   時価総額だけ**なので、EV/EBIT 全体を価格比で掛けるのは純負債≠0の社で誤り。しかも毎営業日
#   適用されるので誤差が複利的に蓄積する（per/perF/shy は分子または分母が時価そのもの＝比例で正しい）。
#   パックの evebit は**触らず据え置く**——正しく更新するには純負債の実額が要り、それは審査の仕事。
SCALE = ("per", "perF", "mcap")        # 価格に比例する欄（時価そのものが分子/分母の欄だけ）
# 2026-09-23（決定 mcap_field_stale(a)）: mcap も px に厳密に比例するので足した（表示・発見度の表示だけに使う欄＝Ωは不変）。
INVERSE = ("shy",)                     # 還元額が不変で時価だけ動く＝1/比率

# 2026-09-18 新設: **株式分割を「値下がり」と読んで書き込むのを止める**。
#   基準保存式は「価格が動いた」前提なので、分割では per を分割比で割ってしまう（shy は掛けてしまう）。
#   実害: APH は 2026-09-03 の 2:1 分割で per 45.11→22.52・shy 0.47→0.94 と書かれた（この日に是正）。
#   ⚠ validate_packs の「per が帯の下・shy が帯の上へ逆方向に同時に外れる」は KLAC(per5.6/shy12.9)の
#     ような**桁の誤り**しか捕まえない——2:1 なら per22.5 も shy0.94 も帯の中なので素通りする（実測）。
#   直し方は「比率から分割を推測する」ではなく**測れないなら書かない**（絶対のルール7）:
#   大きく動いた社は書かずに**名前で出す**。人が SPLITS を見て、分割なら手で是正し、
#   本物の値動きなら --force-move で通す。⚠代金: 本物の暴落・急騰は1回ぶん反映が遅れる
#   （実測 2026-08-21→09-18 の28日で 25%超は 63社中2社＝APH〔分割〕と KRMN〔本物の−34%〕だけ）。
SPLIT_SUSPECT = 0.25                   # この幅を超えたら分割の疑いとして書かずに人へ渡す


def buy_set():
    """門そのもの（score_all.js）で投下可を出す。推測しない。

    2026-08-11の是正: **先に納品検査の表を作り直す**。
      第四の関門（データ健全）は `out/validate_fail.json` を読むが、この道具が書き換える `per` は
      **その表のFAIL条件そのもの**（per と px÷eps の乖離）なので、表を古いまま score_all を回すと
      **昨日の答案で今日の合否を出す**ことになる。実害: 2026-08-10 に RBC の per を更新して
      FAIL が立ったのに、committed の score_all.json は🟢投下可のままで、
      門(ブラウザ・毎回validate_fail.jsonを読む)と端末が違うことを言っていた（v9.9.65の破れ）。
      検査は369件0.12秒なので費用は無視できる。**再実装せず既存の道具を順に呼ぶ**。
    """
    try:
        subprocess.run(["python3", "night/validate_packs.py", "--json"],
                       capture_output=True, text=True, timeout=300)
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
    rows, protected, suspect = [], [], []
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
        if abs(r - 1) >= SPLIT_SUSPECT and "--force-move" not in sys.argv:
            suspect.append((t, old, new, r))   # 分割かもしれない＝書かずに人へ渡す
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
            nv = round(float(v) * (1 / r if k in INVERSE else r), 2)
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
    if suspect:
        print(f"\n  ⚠ 分割の疑いで **書いていない** {len(suspect)}社"
              f"（{int(SPLIT_SUSPECT*100)}%超の変動）——分割なら基準保存式は per を壊す:")
        for t, o, n, r in sorted(suspect, key=lambda x: -abs(x[3] - 1)):
            print(f"     {t:8}{o:12,.2f} → {n:12,.2f}  {(r-1)*100:+6.1f}%  比 {r:.4f}")
        print("     確認: Alpha Vantage SPLITS で分割履歴を見る。"
              "**分割だった** → px/per/shy/eps を手で是正（per は不変・eps は分割比で割る）。"
              "**本物の値動き** → python3 night/apply_prices.py --write --force-move")

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
