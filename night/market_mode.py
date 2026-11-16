#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/market_mode.py — market.yml の今回の実行で何をするかを決める（2026-11-16新設）

なぜ作ったか（ユーザー「全然最新にならない。自動で価格を最新にできないの？」）:
  market.yml は平日 21:30 UTC（米国の引けの後）に1回だけ予約していたが、**GitHub の予約実行は
  毎回 3.5〜6時間遅れて**いた（実測 2026-10-22〜11-13: 開始は 00:06〜03:44 UTC＝日本時間の
  9時〜12時台）。日本時間の朝に開くと、まだ前の前の取引日の値のままだった。
  予約の遅れは GitHub の側にあり時刻をずらしても消えないので、**毎時に予約して**
  （遅れても、どれかが引けの直後に当たる）中身を時刻で分ける:

    light … 米国の取引時間中（NY 9:30〜16:20・平日）＝株価と為替だけ（out/dashboard.json だけ・
            株価が動いたときだけ書く＝コミットはその分だけ）
    full  … 引けの後で、その取引日の全部の更新（パックへの反映・成績・配当ほか従来の market.yml）が
            まだのとき＝1取引日に1回
    skip  … 引けの後で、その取引日の全部の更新がもう済んでいる（何もしない・コミットなし）

  「済んでいるか」は out/dashboard.json の fullSession（full のときに書く取引日）で見る。
  16:20 は引けの値が配信元でそろうまでの余裕（16:00 ちょうどでは最後の約定のことがある）。
  祝日は数えない（その日の full は値が変わらないだけで害がない）。

使い方: python3 night/market_mode.py [auto|full|light]  → 標準出力に mode=… と session=…（GITHUB_OUTPUT の形）
        python3 night/market_mode.py --selftest
"""
import json, os, sys
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN, SETTLE = time(9, 30), time(16, 20)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_open(ny):
    return ny.weekday() < 5 and OPEN <= ny.time() < SETTLE


def latest_session(ny):
    """引け（＋余裕）を過ぎた直近の取引日（平日）。"""
    d = ny.date()
    if ny.weekday() < 5 and ny.time() >= SETTLE:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def decide(now_utc, forced="auto", full_session=None):
    ny = now_utc.astimezone(NY)
    s = latest_session(ny).isoformat()
    if forced in ("full", "light"):
        return forced, s
    if is_open(ny):
        return "light", s
    return ("skip" if full_session == s else "full"), s


def selftest():
    U = lambda *a: datetime(*a, tzinfo=timezone.utc)
    cases = [
        # (UTC, fullSession, 期待 mode, 期待 session)
        (U(2026, 11, 16, 15, 7), None, "light", "2026-11-13"),          # 月曜 10:07 NY（EST）
        (U(2026, 11, 16, 21, 7), "2026-11-13", "light", "2026-11-13"),  # 16:07 NY＝まだ余裕の中
        (U(2026, 11, 16, 21, 27), "2026-11-13", "full", "2026-11-16"),  # 16:27 NY＝引けの後・未
        (U(2026, 11, 16, 23, 7), "2026-11-16", "skip", "2026-11-16"),
        (U(2026, 11, 17, 2, 7), "2026-11-16", "skip", "2026-11-16"),    # 火曜の朝（NY 前夜）
        (U(2026, 11, 17, 2, 7), "2026-11-13", "full", "2026-11-16"),    # 前夜の full が遅れに飲まれた
        (U(2026, 11, 14, 1, 7), "2026-11-12", "full", "2026-11-13"),    # 土曜 UTC＝金曜の夜 NY
        (U(2026, 11, 16, 13, 7), "2026-11-13", "skip", "2026-11-13"),   # 月曜 8:07 NY＝寄りの前
        (U(2026, 7, 15, 13, 37), None, "light", "2026-07-14"),          # 夏時間 9:37 NY
        (U(2026, 7, 15, 20, 27), "2026-07-14", "full", "2026-07-15"),   # 夏時間 16:27 NY
    ]
    bad = 0
    for now, fs, em, es in cases:
        m, s = decide(now, "auto", fs)
        ok = (m, s) == (em, es)
        bad += not ok
        print(("✓" if ok else "✗"), now.isoformat(), fs, "→", m, s, "" if ok else f"（期待 {em} {es}）")
    m, s = decide(U(2026, 11, 16, 15, 7), "full", None)
    ok = m == "full" and s == "2026-11-13"; bad += not ok
    print(("✓" if ok else "✗"), "手動の full は時刻によらず full（session は直近の引けの日）")
    print("✓ 全項目 通過" if not bad else f"✗ {bad}件 失敗")
    return 1 if bad else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    forced = (argv[0] if argv else "auto").strip() or "auto"
    if forced not in ("auto", "full", "light"):
        forced = "auto"
    fs = None
    try:
        fs = (json.load(open(os.path.join(BASE, "out/dashboard.json"), encoding="utf-8")) or {}).get("fullSession")
    except Exception:
        fs = None                      # 読めない＝済んでいるか判らない→full（判らないを済んだと読まない）
    m, s = decide(datetime.now(timezone.utc), forced, fs)
    print(f"mode={m}")
    print(f"session={s}")
    print(f"  ※ NY {datetime.now(timezone.utc).astimezone(NY):%Y-%m-%d %H:%M}・直近の引けの日 {s}・"
          f"全部の更新が済んだ日 {fs or '—'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
