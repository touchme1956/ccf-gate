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
    # auto: True=CIが全自動 / "key"=鍵をSecretsに置けば自動(無ければ手動) / False=人の作業
    items = [
        ("market",  "株価・盤データ",          "毎営業日", 4,
         json_field("out/dashboard.json", "asof") or git_date("out/dashboard.json"),
         "market.yml 21:30UTC（FINNHUB_KEY）", True),
        ("events",  "8-K・臨報監視",           "毎営業日", 4,
         json_field("out/events_watch.json", "asof"),
         "events.yml 22:10UTC（米国は鍵不要・日本株はEDINET_API_KEY）", True),
        ("er",      "E[r]予実の観測封印",      "月1",     40,
         er_last_obs(),
         "market.yml（月初・snapは月次idempotent）", True),
        ("divy",    "配当分離(divY)",          "月1",     40,
         json_field("out/divy.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/fill_divy.py", True),
        # v9.9.118(2026-08-09): 自己相対バリュエーション（Ⅵ買付順位の表示専用・合否には不使用）。
        #   **表示だけの作業でも盤に載せる**——止まると門は「未取得」ではなく
        #   **古い分位を今日の分位として出し続ける**（JSONが残るので画面は何も言わない）。
        #   黙って劣化する種類なので、回転の側で見張る。
        ("histval", "自己相対バリュエーション",  "月1",     40,
         json_field("out/hist_val_now.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/hist_valuation.py --asof 〈今日の日付〉 "
         "--tickers kanshi_list.json --out out/hist_val_now.json", True),
        # v9.9.125(2026-08-09): 銘柄ごとの企業説明（Ⅳ台帳・Ⅵ買付順位の🏢チップ／表示専用）。
        #   止まっても判定は動かないが、**新しく審査した社の説明が出ないまま気づかれない**ので盤に載せる。
        ("profiles", "企業説明(原本Item1)",   "月1",     40,
         json_field("out/profiles.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/fetch_profiles.py", True),
        # 2026-08-09: 門外例外（特別枠）の四半期監視。**止まると甘い側へ壊れる**——
        #   例外は「門が止めているものを承知で越える」判断で、パックは年次基準なので
        #   止めている当の指標(nde)が年1回しか更新されない。この道具が回らないと
        #   **警報を切ったまま乗る**ことになる。
        ("excwatch", "門外例外の四半期監視",  "四半期",  100,
         json_field("out/exception_watch.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/watch_exceptions.py", True),
        # v9.9.124(2026-08-09): irr=85 の実績台帳（別枠85・席の優先の特権をどの社に与えるかを決める）。
        #   **止まると穴が開く向きが危ない**——新しく irr=85 になった社は台帳に載らず「中立」扱いで
        #   特権を受ける。実績が悪い社でもそうなるので、載せ直しが止まると**甘い側へ静かに壊れる**。
        ("irr85hist", "irr=85の実績台帳",      "月1",     40,
         json_field("out/irr85_history.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/irr85_mech_test.py --json", True),
        # 2026-08-10(ユーザー明示指示「上場後1年後にirr85の銘柄は測定できるようにしたい」):
        #   **新規上場社を母集団へ入れ続ける**。上場初年度は10-Kが無いので網に掛からず、
        #   翌年に初めての10-Kが出ても**掃除が一回きりだと誰も見ていない**。
        #   2026-08-08のスイープはまさにこの形で、しかも読解リストを「パックが無い社」に
        #   絞っていたため **KRMN（irr=70・根拠が空）が読解対象から外れていた**。
        #   止まっても今日の判定は動かないが、**測る対象が入ってこなくなる**＝
        #   歴史が「唯一効く」と出した変数の被覆が静かに痩せる種類。
        ("newlist", "新規上場のirr機構語",   "月1",     40,
         json_field("out/new_listings_irr.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/watch_new_listings.py", True),
        # v9.9.94(2026-08-06): 期末後の重大事象の検査。**回っているかを盤で見張る**——
        #   この検査が黙って止まると「パックが会社の現在を描いていない」銘柄が
        #   何食わぬ顔で投下可に戻る（APHがまさにその状態で資産の6.3%を受けていた）。
        ("stalebs", "期末後の重大事象の検査",  "毎営業日", 4,
         json_field("out/stale_bs.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_stale_bs.py --write", True),
        # 2026-08-07新設: パックより新しい年次報告が出ていないか。**既存の検査が全部すり抜ける穴**——
        #   validate_packs の鮮度は「年」の差(3年でFAIL)、audit_stale_bs は のれんの入替のみ
        #   ＝買収しない優良企業が静かに1会計年度ぶん古くなるのは誰も見ていなかった。
        #   実測(初回): MSFT・KLAC（ともに投下可）を含む5社が1年遅れ。
        ("packstale", "パックの会計年度の遅れ",  "毎営業日", 4,
         json_field("out/pack_stale.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_pack_stale.py --write", True),
        # 2026-08-07新設: WACCの既定値(無リスク金利)のズレ。**これは検出器であって適用器ではない**
        #   ——rfrの更新はユーザーの月次ルーチン（買うリズムと選ぶリズムを分ける設計）に属する。
        #   自動化するのは適用ではなく検出。todo_listが自ら「忘れても盤が検出できない種類」と
        #   書いていた項目に、初めて検出器が付いた。
        ("waccdrift", "WACC既定のズレ検出",     "月1",     40,
         json_field("out/wacc_drift.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/audit_wacc_stale.py --write", True),
        # v9.9.95(2026-08-07): 納品検査のFAIL。**関門がこのJSONを読む以上、
        #   JSONの鮮度が関門の鮮度そのもの**——止まると古いFAIL表で買付を裁くことになる。
        ("vfail",   "納品検査FAIL表",          "毎営業日", 4,
         json_field("out/validate_fail.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/validate_packs.py --json", True),
        ("kanshi",  "監視リスト生成",          "月1",     40,
         git_date("kanshi_list.json"),
         "ops.yml／手動 python3 make_kanshi.py", True),
        ("cal",     "決算カレンダー",          "月1",     40,
         json_field("out/next_earnings.json", "generated"),
         "ops.yml／手動 python kessan_calendar.py", True),
        ("xwatch",  "X監視表(開通ライン)",     "月1",     40,
         git_date("gate1_x_watch.json"),
         "ops.yml／手動 python x_watch_recalc.py", True),
        ("kessanUS","決算点検（米国）",        "四半期",  100,
         kessan_last("_qcheck.txt"),
         "ops.yml（月次で先回り）／手動 python kessan_check.py", True),
        ("kessanJP","決算点検（日本株）",      "四半期",  100,
         kessan_last("_qcheck_jp.txt"),
         "ops.yml（EDINET_API_KEYをSecretsに置けば自動）／手動 python3 kessan_check_jp.py", "key"),
        ("v10",     "v10影スコア更新",         "年1(7月)", 430,
         json_field("out/v10_shadow.json", "generated") or git_date("out/v10_shadow.json"),
         "ops.yml（7月）／手動 python3 v10_series.py", True),
        ("calib",   "年次較正(答え合わせ)",     "年1(7月)", 430,
         git_date("out/calibration.json"),
         "python calibration_check.py——v9/v10の勝敗判定はユーザーの判断（V10_SPEC）", False),
        ("gate0",   "米国門0発掘",             "年1(1-2月)", 430,
         git_date("gate1_queue.json"),
         "python run_gate0_local.py（companyfacts.zip 1.4GB＝CI外）", False),
        ("gate0jp", "日本株門0",               "年1",     430,
         git_date("gate0_jp_queue.json"),
         "python3 night/rebuild_gate0_jp.py --write（rerankは旧世代＝封鎖済み）", False),
        ("backtest","疑似バックテスト",        "年1",     430,
         max((git_date(os.path.relpath(f, BASE)) or "" for f in
              glob.glob(os.path.join(BASE, "out", "backtest_*.json"))), default=None) or None,
         "python3 night/backtest_core.py", False),
    ]
    rows = []
    for id_, name, cad, due, last, how, auto in items:
        days = None
        if last:
            try:
                y, m, d = map(int, last[:10].split("-"))
                days = max(0, (today - date(y, m, d)).days)  # コミットTZ(+0900)でUTC日付を跨ぐと負になるため0で床
            except Exception:
                days = None
        state = "unknown" if days is None else ("due" if days > due else "ok")
        rows.append({"id": id_, "name": name, "cadence": cad, "due_days": due,
                     "last": last, "days": days, "state": state, "how": how, "auto": auto})
    # 人のやるべきこと（宿題・決断待ち・機械で測れない定期ルーチン）は todo_list.json が正本。
    # 盤と同じJSONに同梱して門が1回のfetchで両方読めるようにする（v9.9.83）
    todos = None
    try:
        todos = json.load(open(os.path.join(BASE, "todo_list.json"), encoding="utf-8"))
    except Exception:
        pass
    return {"asof": today.isoformat(), "items": rows, "todos": todos,
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
