#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops_status.py — 運用サイクルの回転状態を機械で出す（2026-08-04新設・「すべて回るように」）

なぜ要るか:
  この台帳の周期作業は 毎営業日2本・月次5本・四半期2本・年次5本 に増えた。回っているかどうかを
  人の記憶で管理すると20年は続かない（予実台帳をCIに入れたのと同じ理由）。各作業の
  「最終実行がいつか・期限内か」を出力ファイルの実測から作り、門の🔔イベントタブが表示する。
  **回っていない作業が黙って止まるのが最悪**——止まっていること自体を毎日見えるようにする。

日付の取り方:
  出力JSONに日付フィールドがあればそれ（採取時刻の実測）、無ければ git の最終コミット日。
  git履歴が浅いcheckout(fetch-depth:1)では正しい日付が出ないため、CI側は fetch-depth:0 で走らせる。
  取れないものは「不明」と書く——不明を健全と読まない（ルール7の親戚）。

使い方: python3 night/ops_status.py  → out/ops_status.json ＋ 標準出力に一覧
"""
import glob
import json, os, subprocess, sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_date(path):
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path],
                           capture_output=True, text=True, cwd=BASE, timeout=30)
        d = r.stdout.strip()
        return d if len(d) == 10 else None
    except Exception:
        return None


def json_field(path, *keys):
    try:
        d = json.load(open(os.path.join(BASE, path), encoding="utf-8"))
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and len(v) >= 10:
                return v[:10]
        return None
    except Exception:
        return None


def er_last_obs():
    try:
        d = json.load(open(os.path.join(BASE, "out", "er_ledger.json"), encoding="utf-8"))
        return max((o.get("date", "") for o in d.get("observations", [])), default=None)
    except Exception:
        return None


def kessan_last(suffix):
    files = glob.glob(os.path.join(BASE, "out", "kessan", f"*{suffix}"))
    if not files:
        return None
    dates = [git_date(os.path.relpath(f, BASE)) for f in files]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


# 各周期作業の定義: (id, 表示名, 周期ラベル, 期限日数, 日付の取り方, 回し方)
# 期限日数は「これを超えたら止まっているとみなす」線——毎営業日=4日(連休吸収)/月次=40日/四半期=100日/年次=430日
def build():
    today = date.today()
    items = [
        ("market",  "株価・盤データ",          "毎営業日", 4,
         json_field("out/dashboard.json", "asof") or git_date("out/dashboard.json"),
         "CI: market.yml 21:30UTC（FINNHUB_KEY要）"),
        ("events",  "8-K監視",                "毎営業日", 4,
         json_field("out/events_watch.json", "asof"),
         "CI: events.yml 22:10UTC（鍵不要）"),
        ("er",      "E[r]予実の観測封印",      "月1",     40,
         er_last_obs(),
         "CI: market.yml（月初・snapは月次idempotent）"),
        ("divy",    "配当分離(divY)",          "月1",     40,
         json_field("out/divy.json", "asof"),
         "CI: ops.yml（毎月2日）／手動 python3 night/fill_divy.py"),
        ("kanshi",  "監視リスト生成",          "月1",     40,
         git_date("kanshi_list.json"),
         "CI: ops.yml／手動 python3 make_kanshi.py"),
        ("cal",     "決算カレンダー",          "月1",     40,
         json_field("out/next_earnings.json", "generated"),
         "CI: ops.yml／手動 python kessan_calendar.py"),
        ("xwatch",  "X監視表(開通ライン)",     "月1",     40,
         git_date("gate1_x_watch.json"),
         "CI: ops.yml／手動 python x_watch_recalc.py"),
        ("kessanUS","保有・監視の決算点検(米)", "四半期",  100,
         kessan_last("_qcheck.txt"),
         "CI: ops.yml（月次で先回り）／手動 python kessan_check.py"),
        ("kessanJP","日本株の決算点検",        "四半期",  100,
         kessan_last("_qcheck_jp.txt"),
         "手動 python3 kessan_check_jp.py（EDINET鍵なしは点検不能＝既知の穴）"),
        ("v10",     "v10影スコア更新",         "年1(7月)", 430,
         json_field("out/v10_shadow.json", "generated") or git_date("out/v10_shadow.json"),
         "CI: ops.yml（7月）／手動 python3 v10_series.py"),
        ("calib",   "年次較正(答え合わせ)",     "年1(7月)", 430,
         git_date("out/calibration.json"),
         "手動 python calibration_check.py——v9/v10の勝敗判定はユーザーと（V10_SPEC）"),
        ("gate0",   "米国門0発掘",             "年1(1-2月)", 430,
         git_date("gate1_queue.json"),
         "手動 python run_gate0_local.py（companyfacts.zip 1.4GB＝CI外）"),
        ("gate0jp", "日本株門0",               "年1",     430,
         git_date("gate0_jp_queue.json"),
         "手動 python3 night/rebuild_gate0_jp.py --write（rerankは旧世代＝封鎖済み）"),
        ("backtest","疑似バックテスト",        "年1",     430,
         max((git_date(os.path.relpath(f, BASE)) or "" for f in
              glob.glob(os.path.join(BASE, "out", "backtest_*.json"))), default=None) or None,
         "手動 python3 night/backtest_core.py"),
    ]
    rows = []
    for id_, name, cad, due, last, how in items:
        days = None
        if last:
            try:
                y, m, d = map(int, last[:10].split("-"))
                days = max(0, (today - date(y, m, d)).days)  # コミットTZ(+0900)でUTC日付を跨ぐと負になるため0で床
            except Exception:
                days = None
        state = "unknown" if days is None else ("due" if days > due else "ok")
        rows.append({"id": id_, "name": name, "cadence": cad, "due_days": due,
                     "last": last, "days": days, "state": state, "how": how})
    return {"asof": today.isoformat(), "items": rows,
            "note": "state=due は「期限日数を超えて止まっている」の機械判定。unknown は日付が取れない＝健全と読まないこと"}


def main():
    out = build()
    p = os.path.join(BASE, "out", "ops_status.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_due = sum(1 for r in out["items"] if r["state"] == "due")
    n_unk = sum(1 for r in out["items"] if r["state"] == "unknown")
    print(f"運用サイクル {len(out['items'])}本: 期限内 {len(out['items'])-n_due-n_unk} / 停止疑い {n_due} / 不明 {n_unk}")
    for r in out["items"]:
        mark = {"ok": "🟢", "due": "⚠", "unknown": "？"}[r["state"]]
        ago = "" if r["days"] is None else f"（{r['days']}日前・期限{r['due_days']}日）"
        print(f"  {mark} {r['name']:<14}（{r['cadence']}）最終 {r['last'] or '不明'}{ago}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
