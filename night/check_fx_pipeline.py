#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/check_fx_pipeline.py — ドル円の自動更新（fetch_dashboard.fetch_fx）の振る舞いを**ネット無しで**検査する

何のための検査か（2026-10-10 ユーザー指示「為替も自動更新できるようにして」）:
  為替は 2026-07-30 から自動（CI が毎営業日 out/dashboard.json の fx.USDJPY を更新）だったが、**前営業日の値を持たず**、
  🏦保有の前日比は「株価だけ（為替は含まない）」だった。総資産は今のドル円で円換算しているのに、
  前日比に為替の動きが入らなければ「昨日の総資産との差」にならない。
  → fetch_fx が **prev（前営業日のドル円）・chgPct・day** も残し、門は fx.prev があるときだけ前日比に為替を含める。

見ること（外部には出ない。Yahoo と open.er-api の応答を差し替えて呼ぶ）:
  ⓪ fx_pair_24h（Yahoo JPY=X の1時間足から「最新」と「24時間前」を取る純関数）: 平日・月曜（週末をまたぐ＝金曜の終値）・
     足の欠け（平日で6時間超は prev なし）・足が少なすぎる・終値が None の足を捨てる
  ① Yahoo が引けたら 出所＝Yahoo・prev・chgPct・day が付く
  ② 常識帯（100〜250円）を外れた値は捨てる（px も prev も）。pxが外れたら open.er-api へ落ちる
  ③ prev が遠すぎる（前日比5%超＝日足の欠けで遠い日の値を拾った疑い）なら prev だけ付けない（px は残す）
  ④ Yahoo が引けず open.er-api だけ: **前回コミットの同じ出所の値（別の日）**から prev を作る
  ⑤ ④で出所が違う（前回は Yahoo だった）なら prev を付けない＝基準の違う二つを割らない
  ⑥ ④で前回が stale なら prev を付けない
  ⑦ 同じ日の再実行（workflow_dispatch）は、前回の prev を引き継ぐ（同じ日の値を prev にしない）
  ⑧ 両方引けなければ None（ゼロで埋めない・呼び出し側が前回値を stale で据え置く）

使い方: python3 night/check_fx_pipeline.py     終了コード 1 = 1件でも ✗
"""
import os
import sys
import importlib.util
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("fd", os.path.join(ROOT, "night", "fetch_dashboard.py"))
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)

NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
ok = bad = 0


def check(cond, msg):
    global ok, bad
    if cond:
        ok += 1
        print("  ✓ " + msg)
    else:
        bad += 1
        print("  ✗ " + msg)


def yh(px, prev=None, day="2026-10-09"):
    d = {"px": px, "prev": prev, "day": day}
    return lambda: dict(d)


def er(px):
    return lambda: {"rates": {"JPY": px}}


NO_YH = lambda: None
NO_ER = lambda: None

print("■ ⓪ fx_pair_24h（1時間足から 最新と24時間前）")
UTC = timezone.utc


def ts(y, m, d, h):
    return int(datetime(y, m, d, h, tzinfo=UTC).timestamp())


def hourly(start, end, skip=lambda t: False):
    """start〜end（unix秒）の毎時の足。終値は 150 + 通し番号×0.01（どの足が選ばれたか値から分かる）。"""
    rows, i, t = [], 0, start
    while t <= end:
        if not skip(t):
            rows.append((t, round(150 + i * 0.01, 2)))
        i += 1
        t += 3600
    return rows


# 平日: 月曜0時〜金曜20時（週末は市場が閉じている）。最新＝金曜20時の足
wk = hourly(ts(2026, 10, 5, 0), ts(2026, 10, 9, 20))
r = fd.fx_pair_24h(wk)
check(r and r["px"] == wk[-1][1] and r["prev"] == wk[-25][1] and r["day"] == "2026-10-09",
      f"平日: 最新は金曜20時の足・prev は24時間前（木曜20時＝{r and r['prev']}）・day=2026-10-09")
# 月曜: 先週の金曜20時まで＋日曜22時〜月曜21時。24時間前は日曜21時＝市場が閉じている → 金曜の終値
prev_week = hourly(ts(2026, 10, 2, 0) - 40 * 3600, ts(2026, 10, 2, 20))
mon = hourly(ts(2026, 10, 4, 22), ts(2026, 10, 5, 21))
r = fd.fx_pair_24h(prev_week + mon)
check(r and r["prev"] == prev_week[-1][1] and r["day"] == "2026-10-05",
      f"月曜: 24時間前は日曜昼（閉場）なので金曜の終値（{r and r['prev']} / 期待 {prev_week[-1][1]}）")
# 平日の足の欠け: 木曜 10:00〜23:00 が無い → 24時間前（木曜20時）に近い足が11時間前 → prev なし（px は出る）
gap = hourly(ts(2026, 10, 5, 0), ts(2026, 10, 9, 20), skip=lambda t: ts(2026, 10, 8, 10) <= t <= ts(2026, 10, 8, 23))
r = fd.fx_pair_24h(gap)
check(r and r["px"] == gap[-1][1] and r["prev"] is None, "平日に足が欠けて24時間前に近い足が無ければ prev なし（遠い日の値を前日にしない）")
check(fd.fx_pair_24h(wk[:20]) is None, "足が30本に満たなければ None")
none_rows = [(t, None if i % 7 == 0 else c) for i, (t, c) in enumerate(wk)]
r = fd.fx_pair_24h(none_rows)
check(r and r["px"] == wk[-1][1] and r["prev"] is not None, "終値が None の足は捨てて続ける")

print("■ ① Yahoo が引けた")
r = fd.fetch_fx(_yahoo=yh(158.246, 158.063), _er=NO_ER, _prev=lambda: {})
check(r and r["USDJPY"] == 158.246 and r["src"] == fd.FX_YH, f"出所は Yahoo・値 {r and r['USDJPY']}")
check(r and r.get("prev") == 158.063 and abs(r.get("chgPct", 0) - 0.116) < 0.002, f"prev と chgPct（{r and r.get('prev')} / {r and r.get('chgPct')}%）")
check(r and r.get("day") == "2026-10-09" and r.get("asof"), "day（終値の日）と asof（取得時刻）が付く")

print("■ ② 常識帯の検問")
r = fd.fetch_fx(_yahoo=yh(1.58, 1.57), _er=er(158.3), _prev=lambda: {})
check(r and r["src"] == fd.FX_ER and r["USDJPY"] == 158.3, "Yahoo の値が桁違い（1.58）なら捨てて open.er-api へ落ちる")
r = fd.fetch_fx(_yahoo=yh(158.2, 1.57), _er=NO_ER, _prev=lambda: {})
check(r and r["USDJPY"] == 158.2 and "prev" not in r, "prev だけ桁違いなら prev を付けない（px は残す）")
r = fd.fetch_fx(_yahoo=NO_YH, _er=er(9999), _prev=lambda: {})
check(r is None, "open.er-api の値も帯の外なら None")

print("■ ③ prev が遠すぎる（日足の欠け）")
r = fd.fetch_fx(_yahoo=yh(158.0, 140.0), _er=NO_ER, _prev=lambda: {})
check(r and r["USDJPY"] == 158.0 and "prev" not in r and "chgPct" not in r, "前日比が5%を超える prev は付けない（前日比が化けるより「無い」）")

print("■ ④ Yahoo が引けず open.er-api だけ・前回は別の日の同じ出所")
prev_file = {"USDJPY": 157.5, "src": fd.FX_ER, "asof": YESTERDAY + "T01:00:00+00:00"}
r = fd.fetch_fx(_yahoo=NO_YH, _er=er(158.0), _prev=lambda: dict(prev_file))
check(r and r["src"] == fd.FX_ER and r.get("prev") == 157.5, f"前回の値が prev になる（{r and r.get('prev')}）")
check(r and abs(r.get("chgPct", 0) - (158.0 / 157.5 - 1) * 100) < 0.002, "chgPct も出る")

print("■ ⑤ 出所が違うものは混ぜない")
r = fd.fetch_fx(_yahoo=NO_YH, _er=er(158.0), _prev=lambda: {"USDJPY": 157.5, "src": fd.FX_YH, "asof": YESTERDAY + "T01:00:00+00:00"})
check(r and r["src"] == fd.FX_ER and "prev" not in r, "前回が Yahoo の値なら prev を付けない（基準の違う二つを割らない）")

print("■ ⑥ 前回が stale")
r = fd.fetch_fx(_yahoo=NO_YH, _er=er(158.0), _prev=lambda: {"USDJPY": 157.5, "src": fd.FX_ER, "asof": YESTERDAY + "T01:00:00+00:00", "stale": True})
check(r and "prev" not in r, "前回の値が stale（古い据え置き）なら prev にしない")

print("■ ⑦ 同じ日の再実行")
r = fd.fetch_fx(_yahoo=NO_YH, _er=er(158.0), _prev=lambda: {"USDJPY": 157.9, "prev": 157.5, "src": fd.FX_ER, "asof": TODAY + "T01:00:00+00:00"})
check(r and r.get("prev") == 157.5, f"同じ日の値（157.9）を prev にせず、前回の prev（157.5）を引き継ぐ（{r and r.get('prev')}）")
r = fd.fetch_fx(_yahoo=NO_YH, _er=er(158.0), _prev=lambda: {"USDJPY": 157.9, "src": fd.FX_ER, "asof": TODAY + "T01:00:00+00:00"})
check(r and "prev" not in r, "同じ日で前回に prev が無ければ付けない")

print("■ ⑧ どちらも引けない")
r = fd.fetch_fx(_yahoo=NO_YH, _er=NO_ER, _prev=lambda: {"USDJPY": 157.5, "src": fd.FX_ER, "asof": YESTERDAY + "T01:00:00+00:00"})
check(r is None, "None を返す（0 や前回値で黙って埋めない）")


def boom():
    raise RuntimeError("network down")


r = fd.fetch_fx(_yahoo=boom, _er=er(158.0), _prev=lambda: {})
check(r and r["src"] == fd.FX_ER, "Yahoo が例外を投げても open.er-api へ落ちる（落ちずに続く）")

print(f"\n結果: ✓ {ok} / ✗ {bad}")
sys.exit(1 if bad else 0)
