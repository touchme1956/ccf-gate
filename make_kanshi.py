#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_kanshi.py — 監視リスト kanshi_list.json を台帳から生成する（2026-07-29新設）

なぜ道具にしたか:
  従来の定義は「保有 + 質80+」で、手で維持されていた。ところが 2026-07-29 の全数是正で
  **Ω80+ が4社まで収縮**し、定義どおりに絞ると監視は7社になる。そこまで絞っていたら、
  同日の四半期点検が拾った **KLAC の $230.4百万 のれん減損**（業績見通しの下方修正を伴う実計上・
  当時Ω79.8）を見逃していた。ティアの絶対値は採点の是正で動くので、
  **「監視に値するか」を Ω80 という一点に紐づけるのは脆い。**

新しい定義（2026-07-29・ユーザー明示指示）:
  監視 = 保有(holdings.json) ∪ 🟢投下可 ∪ Ω75+（投下閾値の帯）
         ∪ **直近の四半期点検で要審査が出た社** ∪ 明示的な pin
  ・投下閾値75は「買ってよい資格」の線なので、四半期で壊れていないかを見る単位として自然
  ・保有は当然。投下可はいつでも買う可能性がある
  ・**要審査の社を必ず残す**のが肝。Ω75+ だけで引くと、点検が異常を拾った直後に
    Ωが75を割った社が**警報を出した次の四半期に監視から消える**という最悪の抜けが起きる。
    実測: ADBE（のれん減損$70百万を計上・Ω74.4）と HEI（Ω64.2）が Ω75+ の線だけでは落ちていた
  ・pin は機械の外で見たい銘柄（例: 一度キルが出たが復活を待っている社）を手で足す枠

使い方:
  python3 make_kanshi.py            生成して kanshi_list.json を書き換え（差分を表示）
  python3 make_kanshi.py --dry      書き換えずに差分だけ見る
  前提: out/score_all.json が最新であること（先に `node night/score_all.js`）

注意: kessan_check.py / kessan_calendar.py はどちらも SEC 経由なので**日本株は処理できない**。
  日本株は kessan_check_jp.py（EDINET経路）で別に点検する。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

BUY_GATE = 75.0          # 投下閾値。ここが監視の下限
PIN_KEY = "pin"          # kanshi_list.json に手で足したい銘柄を残す枠


def _alerted():
    """直近の四半期点検で「要審査」が出た社を拾う。
    Ω75+ だけで監視を引くと、**警報を出した次の四半期に監視から消える**という抜けが起きる
    （実測: ADBEはのれん減損$70百万を計上した四半期にΩ74.4で線を割っていた）。
    異常を拾った社こそ翌期も見る必要があるので、点検結果を監視の入力に戻す。"""
    d = os.path.join("out", "kessan")
    if not os.path.isdir(d):
        return set()
    out = set()
    # 【2026-08-03 是正】`_qcheck.txt`(米国) しか見ておらず、**日本株の `_qcheck_jp.txt` を読み落としていた**。
    #   kessan_check.py がSEC経路で日本株を点検できないので kessan_check_jp.py を別に作ったのに、
    #   その出力を監視リストの入力に戻す側が追随していなかった＝**採取は直したが利用側が取り残された**型。
    #   実害の条件: Ω75未満の日本株が警報を出しても監視に残らない（今回の4071/6857はΩ75+なので偶然無害だった）。
    #   規約「要審査の社を必ず残す」は国を問わないので、両方を読む。
    for f in os.listdir(d):
        if f.endswith("_qcheck.txt"):
            key = f.split("_qcheck")[0]
        elif f.endswith("_qcheck_jp.txt"):
            key = f.split("_qcheck_jp")[0]
        else:
            continue
        try:
            head = open(os.path.join(d, f), encoding="utf-8").read().split("=== 警報スニペット")[0]
        except Exception:
            continue
        if "要審査" in head:
            out.add(key)
    return out


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def main():
    rows = load("out/score_all.json", None)
    if not rows:
        print("out/score_all.json が無い。先に `node night/score_all.js` を回すこと")
        return 1

    hold = set((load("holdings.json", {}) or {}).get("holdings") or [])
    q75 = {r["t"] for r in rows if (r.get("s") or 0) >= BUY_GATE}
    buy = {r["t"] for r in rows if r.get("buy")}
    alert = _alerted()          # 直近の四半期点検で要審査が出た社（Ωが線を割っても落とさない）

    cur_raw = load("kanshi_list.json", [])
    if isinstance(cur_raw, dict):
        cur = set(cur_raw.get("list") or cur_raw.get("tickers") or [])
        pins = set(cur_raw.get(PIN_KEY) or [])
    else:
        cur, pins = set(cur_raw or []), set()

    new = sorted(hold | q75 | buy | alert | pins)
    added, removed = sorted(set(new) - cur), sorted(cur - set(new))

    print(f"保有 {len(hold)} ∪ 投下可 {len(buy)} ∪ Ω{BUY_GATE:.0f}+ {len(q75)}"
          f" ∪ 要審査 {len(alert)} ∪ pin {len(pins)} → 監視 {len(new)}社")
    keep = sorted(alert - q75 - hold - buy)
    if keep:
        print(f"  ※Ω{BUY_GATE:.0f}未満だが要審査のため残す: {' '.join(keep)}")
    print(f"  追加 {len(added)}: {' '.join(added) or '(なし)'}")
    print(f"  除外 {len(removed)}: {' '.join(removed) or '(なし)'}")
    if removed:
        print("  ※除外は「監視から降ろす」であって売却指示ではない。保有はholdings.jsonで常に残る。")
    jp = [t for t in new if t[:1].isdigit()]
    if jp:
        print(f"  ⚠日本株 {len(jp)}社 ({' '.join(jp)}) は kessan_check.py / kessan_calendar.py の"
              f"対象外（SEC経路）。kessan_check_jp.py で点検すること")

    if "--dry" in sys.argv:
        print("\n--dry のため書き換えていない")
        return 0
    out = {"list": new, PIN_KEY: sorted(pins),
           "note": f"自動生成 (make_kanshi.py)。定義=保有 ∪ 投下可 ∪ Ω{BUY_GATE:.0f}+ ∪ 要審査 ∪ pin。"
                   f"手で足したい銘柄は '{PIN_KEY}' に入れると次回生成でも残る。"}
    json.dump(out, open("kanshi_list.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n→ kanshi_list.json を更新。次: python kessan_check.py / python kessan_calendar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
