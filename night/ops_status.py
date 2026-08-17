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


def review_last_run():
    """日次の門2審査 Routine が最後に走った日（out/review_runs.json の最新 date）。

    **PRの有無ではなく「走ったか」で測る**——PRが出ない日（待ち行列が空・SEC不通・上限）も
    正常な終わり方なので、PRを錨にすると空振りの日と止まった日が区別できない。
    """
    try:
        d = json.load(open(os.path.join(BASE, "out", "review_runs.json"), encoding="utf-8"))
        return max((r.get("date", "") for r in d.get("runs", [])), default=None) or None
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
        # 2026-08-11(ユーザー指示「1と2やって」): **日次の門2審査 Routine が走ったか**。
        #   ここは他の項と穴の空き方が違う——他は「CIが止まればファイルが古くなる」ので自然に見えるが、
        #   Routine は **GitHub Actions ではなく Claude のセッション**なので、
        #   走らなくても・走って何もしなくても、**リポジトリには何の変化も起きない**。
        #   しかも **Routine 起動のセッションはコード一覧に出ない**（トリガー発火は既定で除外）ので、
        #   報告は人が直リンクを開かない限り誰の目にも触れない。
        #   実害: 2026-08-11 の試運転は29分・出力9万トークン走って**痕跡ゼロ**で終わり、
        #   ユーザーが「どこにもない」状態になった。
        #   → night/log_review_run.py が**毎回1行**を残し、ここがその日付を見る。
        #   **PRの有無ではなく「走ったか」で測る**（空振りは正常な終わり方で、止まったのとは別物）。
        # v9.9.140: 📋今日 の集計。**止まると画面が「今日やることはありません」と言い続ける**
        #   ——この画面はいちばん人が信じるところなので、止まったことが判る必要がある。
        # v9.9.140: 門(ブラウザ)と端末(score_all.js)の一致。**v9.9.65の掟を機械で測る唯一の道具**
        #   ——止まると「同じ台帳を見る二つが違うことを言う」を誰も見張っていない状態に戻る。
        ("parity",  "門と端末の一致",          "毎営業日", 4,
         json_field("out/gate_parity.json", "generated"),
         "ci.yml 平日22:00UTC（実ブラウザ）／手動 node night/check_gate_parity.js", True),
        ("today",   "📋今日の集計",            "毎営業日", 4,
         json_field("out/today.json", "generated"),
         "ci.yml 平日22:00UTC／手動 python3 night/today.py --json", True),
        # 2026-08-17新設: **この盤自身の死角を見張る器**。
        #   ここ（ops_status）は錨の**日付しか見ていない**が、日付と中身は独立に壊れる——
        #     A 日付が凍る（中身は動く）＝**偽陽性**。実際に audit_irr85_dual で5日間鳴りっぱなしだった
        #     B 日付は動くが中身が凍る    ＝**偽陰性**
        #     C 中身も動くが入力が死ぬ    ＝**偽陰性**。実測 sp500_pe_monthly(2026-03停止)→hist_val_now(08-09)
        #   A は check_frozen_dates（CIで落とす）、**B と C は check_freshness** が測る。
        #   偽陰性は盤が緑なので誰も探しに行かない＝**この器が止まると死角が死角のまま戻る**。
        #   ⚠ 作業リストなのでCIでは落とさない（鳴りすぎる警報は鳴らないのと同じ）。
        #     落とさない以上、止まったことを見るのはここしかない。
        ("freshness", "中身と入力の鮮度",       "毎営業日", 4,
         json_field("out/freshness.json", "generated"),
         "ci.yml 平日22:00UTC／手動 python3 night/check_freshness.py --json", True),
        ("reviewrun", "日次 門2審査(Routine)",  "毎営業日", 4,
         review_last_run(),
         "Routine『【門】日次 門2審査（自動・5社）』平日05:00 JST（claude-opus-5）／"
         "痕跡は python3 night/log_review_run.py --outcome … --push", True),
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
        # ★v9.9.143(2026-08-14・ユーザー指示「1.2.3すべてやりたい」)
        #   ②門が自分の過去の判定を持つ。**止まると履歴に穴が空き、後から埋められない**
        #   （git の score_all.json は CI と作業ブランチが交互に入って一本の系列にならない）。
        ("gatehist", "門の判定の履歴",            "毎営業日", 4,
         json_field("out/gate_state.json", "day"),
         "market.yml が毎日／手動 python3 night/gate_history.py --append", True),
        #   ①irr の被覆。**判定には使わない**が、13年の検証を生き延びた唯一の指標が
        #   母集団の12.3%にしか付いていない、という数字を見えるところに置き続ける。
        ("irrcov", "irr の被覆と未審査の穴",       "月1",     40,
         json_field("out/irr_coverage.json", "generated"),
         "ci.yml 月次／手動 python3 night/audit_irr_coverage.py", True),
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
        # 2026-08-11(ユーザー明示指示「irr85の銘柄が出た場合は先ほどまでに使っていた基準で採点してほしい」):
        #   **新しく irr=85 になった社を、ユーザーの基準（営利率11.89 / FCF転換5年0.639 / 成長1.76）で採点する。**
        #   日次の門2審査 Routine がパックを足すので irr=85 の顔ぶれは動く（実測: このセッション中に14→15社）。
        #   止まっても今日の判定は動かない（この道具は読むだけ）が、**新着が誰にも採点されないまま溜まる**
        #   ——「8社」が写真からルールへ変わった意味が消える種類。毎営業日にした理由は、
        #   Routine が毎日走るのに月次で拾うと最大1ヶ月ぶん新着が見えないから。
        # 2026-08-11(ユーザー指示「進めて」): irr=85 を**捌く**ための3本。いずれも読むだけ。
        #   ①機構文の年次diff——**歴史が唯一「効く」と出した変数の劣化を機械が見張る**。
        #     台帳に刻んだ引用が最新の年次報告にまだ在るか。⚠片側の検査（消えたら赤信号／
        #     在っても安全ではない＝CMTL は文を残したまま壊れた）。
        #   ②城の相関——1銘柄の上限8%は守るのに**束では一度も見ていなかった**。
        #     半導体5社・航空防衛4社で城の62.6%なのに、同じ束かの判断材料が業種ラベルだけだった。
        #   ③irr=85 の根拠監査——**回転盤にもCIにも登録が無く2026-08-05の54社のまま6日間止まっていた**
        #     （実データは15社）。KRMN が監視から漏れていたのと同じ形。
        ("irr85mech", "機構文の年次diff",      "毎営業日", 4,
         json_field("out/irr85_mech_diff.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/irr85_mech_diff.py --json", True),
        ("castlecorr", "城の相関（同時に落ちるか）", "月1",  40,
         json_field("out/castle_correlation.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/castle_correlation.py --json", True),
        # ⚠期限は「月1・40日」ではなく**毎営業日・4日**（2026-08-11 同日中の是正）。
        #   この2本は ops.yml（月次）ではなく **ci.yml（push/PR毎＋平日22:00UTCのschedule）**で回るので、
        #   実際の周期は毎営業日。40日にすると**CIが壊れて止まっても40日間 ✓ が出続ける**——
        #   まさにこの道具が2026-08-05から6日間止まっていたのを誰も検出できなかったのと同じ形を、
        #   期限の側から作り直すことになる。同じ ci.yml で回る irr85myrule（毎営業日・4日）と揃える。
        ("irr85audit", "irr=85の根拠監査",      "毎営業日", 4,
         json_field("out/audit_irr85.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_irr85.py", True),
        # 2026-08-11: 機構の射程と認定の寿命（_meta.mech）。**測定は原本読解＝人の作業**だが、
        #   この表は「まだ測っていない社」を名指しするので回し続ける意味がある
        #   ——新しく irr=85 になった社は未着手のまま静かに溜まる（KRMNが監視から漏れたのと同じ形）。
        ("irr85scope", "機構の射程と認定の寿命",  "月1",     40,
         json_field("out/irr85_scope_life.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/irr85_scope_life.py --json", True),
        ("irr85myrule", "irr=85をあなたの基準で採点", "毎営業日", 4,
         json_field("out/irr85_myrule.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/irr85_myrule.py --json", True),
        # 2026-08-12(A-1): **irr=85 の二重読み**の有無を数える。
        #   実測で「同じ111社でも班により irr=85 の付与率が 5.4%→17.1%（3.2倍・p=0.017）」と判った。
        #   門は irr=85 に別枠(v9.9.119)と席の優先(v9.9.100)を与えているので、
        #   **「いつ・誰に読まれたか」で買付の資格が動きうる**。
        #   ⚠ 関門ではなく作業リスト（未検証は欠陥ではなく工程の途中）。だが**盤に載せる**——
        #   載せないと「新しく85が付いたのに誰も検証していない」が静かに溜まる（KRMNがまさにその形）。
        ("irr85dual", "irr=85の二重読み",      "毎営業日", 4,
         json_field("out/irr85_dual.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_irr85_dual.py", True),
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
        # 2026-08-10: **採点入力の再測定2本**。どちらも --write を付けず測るだけ（ルール2）だが、
        #   止まると**新しく審査した社ほど甘くなる**種類なので盤で見張る。
        #   cagrT: compute() が使う欄で、空欄は CCF_BLANK の 'best'＝罰が発火しない
        #   sht  : 空欄は SELECT既定の 'flat' に化け、**Intel警報（gmt=down ∧ sht=down）**を含む
        #          5規則がまるごと不発になる。実測で369社中322社が空欄だった
        ("cagrt",   "成長の軌道cagrTの測定", "月1",     40,
         json_field("out/growth_trend.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/fill_growth_trend.py（反映は --write＝審査官の手）", True),
        # 2026-08-10: **検出器の出力を作業へ流す接続**。止まると「検出は自動・作業は手動」の
        #   断絶が戻る——新しい10-Kが出ても納品検査がFAILしても、待ち行列に何も入らなくなる。
        ("reaudit", "再審査の待ち行列",      "月1",     40,
         json_field("night/reaudit_queue.json", "generated"),
         "ci.yml（push毎）＋ops.yml 毎月2日／手動 python3 night/enqueue_reaudit.py --json "
         "&& python3 night/make_chunks.py --reaudit --top 20", True),
        # 2026-08-10: **自動化そのものを見張る3本**。
        #   通知・機械是正・門2審査が止まっても、今日の判定は動かないので**気づけない**——
        #   だからこそ盤に載せる（「回っているつもりで止まっている」を作らない）。
        ("notify",  "通知(Issue化)",         "毎営業日", 4,
         json_field("out/events_watch.json", "asof"),
         "events.yml（行動が要ることだけIssueにする・冪等）", True),
        ("fix",     "機械是正の自動提案",     "週1",     10,
         git_date("out/score_all.json"),
         "fix.yml 毎週土曜（判定が動かなければmain直・動けばPR）", True),
        ("review",  "門2審査(自動)",         "毎営業日", 4,
         git_date("night/progress.json"),
         "review.yml 平日17:00UTC（**ANTHROPIC_API_KEY が要る**。無ければ何もせず終了）", "key"),
        ("sht",     "シェア趨勢shtの測定",   "月1",     40,
         json_field("out/sht_report.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/build_sic_cache.py && python3 night/fill_sht.py --json"
         "（反映は --write＝審査官の手）", True),
        # v9.9.94(2026-08-06): 期末後の重大事象の検査。**回っているかを盤で見張る**——
        #   この検査が黙って止まると「パックが会社の現在を描いていない」銘柄が
        #   何食わぬ顔で投下可に戻る（APHがまさにその状態で資産の6.3%を受けていた）。
        ("stalebs", "期末後の重大事象の検査",  "毎営業日", 4,
         json_field("out/stale_bs.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_stale_bs.py --write", True),
        # v9.9.128(2026-08-10): 合意済み・**未完了**の重大事象。stale_bs の**時間的な穴**を塞ぐ検査で、
        #   これが止まると「合意/判決からクローズまでの数ヶ月〜1年超」がまた無防備になる。
        #   ⚠ この欄は審査官が _meta.pending に書くので、**盤が緑でも書き漏らしは検出できない**
        #   ——見落としの網は watch_events の pending_todo（8-K Item 1.01/1.02/8.01）が受け持つ。
        ("pending", "未完了の重大事象の検査",  "毎営業日", 4,
         json_field("out/pending.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_pending.py --all --write", True),
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
         "ops.yml（7月）／手動 python3 v10_series.py"
         "　⚠**その v10_series.py が repo に存在しない**（git 全履歴にも無い）"
         "＝影の在庫はあるのに作り直せない。2027-07の答え合わせの前に要復旧", True),
        # v11「引き算の門」の影（2026-08-12新設）。**v10 の轍を踏まないために回転盤へ載せる**
        #   ——v10 は仕様書に「毎年7月に python v10_series.py」と書きながら、その道具が
        #   一度も repo に入っていなかった（＝影が更新できないまま1年が過ぎた）。
        #   v11 は判定に一切使わないが、**止まったことが見えるようにしておく**。
        # 採取器の是正がパックに届いているかの実測（2026-08-13新設）。
        #   **止まると「取り残し」が静かに溜まる**——nde の12社はこの経路で8ヶ月見えなかった。
        ("bfdiff",  "採取器とパックの食い違い",  "月1",     40,
         json_field("out/backfill_diff.json", "generated") or git_date("out/backfill_diff.json"),
         "ops.yml 毎月2日／手動 python3 night/backfill_machine_evidence.py --json"
         "（**読むだけ**。--sync は単位ずれ・年ずれを注入するので自動では走らせない）", True),
        ("v11",     "v11影スコア更新",         "月1",     40,
         json_field("out/v11_shadow.json", "generated") or git_date("out/v11_shadow.json"),
         "ops.yml 毎月2日／手動 python3 night/v11_facts.py && node night/v11_gate.js"
         "（V11_SPEC.md・正本の判定には一切使わない）", True),
        # 2026-08-10: **auto=False → True**。人の判断が要るのは *v9 vs v10 の勝敗判定* であって
        #   スナップショットの生成ではない（鍵もネットも companyfacts も不要）。もう半分の
        #   v10_series.py は既に7月だけ自動で、**片方だけ手動という非対称**が残っていた。
        #   しかもこれは**時点を逃すと永久に失われる**唯一の項目——一度失敗している
        #   （calibration.json に v9 の Ω合成値が無く 2027-07 の答え合わせが成立しなくなった）。
        ("calib",   "年次較正の封印(7月)",      "年1(7月)", 430,
         git_date("out/calibration.json"),
         "ops.yml（7月）／手動 python calibration_check.py"
         "——**封印は自動・v9/v10の勝敗判定はユーザーの判断**（V10_SPEC）", True),
        # 2026-08-10: 錨を **git のコミット日 → 実行印(out/gate0_run.json)** へ。
        #   実測では gate1_queue.json の直近コミットが門0と無関係の作業（予実台帳の基準印）で、
        #   それでも盤は「期限内」と出していた。**年次作業ほど測り方が弱い**という倒錯を直す。
        ("gate0",   "米国門0発掘",             "年1(1-2月)", 430,
         json_field("out/gate0_run.json", "generated") or git_date("gate1_queue.json"),
         "python run_gate0_local.py（companyfacts.zip 1.4GB＝CI外）", False),
        # 2026-08-10: rebuild_gate0_jp が **generated を "2026-08-03" にハードコード**していたため、
        #   再実行しても去年の日付を名乗り**盤が永久に緑で固定**されていた（実行日を書くよう直した）。
        #   ⚠auto は False のまま——**母集団の更新には EDINET鍵が要る**（run_gate0_jp_local.py）。
        #     rebuild_gate0_jp は凍結スナップショットの**再ランク**であって母集団の再取得ではない。
        ("gate0jp", "日本株門0",               "年1",     430,
         json_field("gate0_jp_queue.json", "generated") or git_date("gate0_jp_queue.json"),
         "python3 night/rebuild_gate0_jp.py --write（**再ランクのみ**。母集団の更新は "
         "run_gate0_jp_local.py＝EDINET_API_KEY が要る）", "key"),
        # 2026-08-10: 錨に **生成印(generated)** を優先させた（git コミット日は最後の手段）。
        #   あわせて auto=**True**——実測では companyfacts.zip を使っておらず
        #   （`grep zipfile night/backtest_core.py` は0件・per-CIK APIと独自キャッシュ）、
        #   「資源制約で自動化できない」は**一度も試していない**の言い換えだった。
        # v9.9.131: **人の決定(state.json)の鮮度**。株数・目標ウェイト・売却記録・検証履歴・
        #   点灯日・個別枠は 2026-08-10 まで localStorage が正本で repo にコピーが無く、
        #   **消えたら復元手段がゼロ**だった。repo へ移したが、門はブラウザから repo へ書けないので
        #   「人が書き出してコミットする」経路になる＝**書き出し忘れが唯一の穴**。
        #   だから盤で測る——auto は False（人の手が要る作業だと明示する）。
        #   savedAt が null（未初期化）なら日付が取れず state=unknown ＝「健全と読まない」側に落ちる。
        ("state",   "人の決定の書き出し(state.json)", "月次", 40,
         (json_field("state.json", "savedAt") or "")[:10] or None,
         "門のⅦ資産「📤 state.json」→ repo直下へ置いてコミット（検査 python3 night/validate_state.py）", False),
        ("backtest","疑似バックテスト",        "年1",     430,
         max((json_field(os.path.relpath(f, BASE), "generated")
              or git_date(os.path.relpath(f, BASE)) or "" for f in
              glob.glob(os.path.join(BASE, "out", "backtest_*.json"))), default=None) or None,
         "gate0.yml（年1・7月）／手動 python3 night/backtest_core.py", True),
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
        # 2026-08-10: **鍵待ち(auto=="key")の作業を「停止疑い」と同じ赤にしない。**
        #   鍵が無いのは*止まった*のではなく*まだ始めていない*——両方を同じ色にすると
        #   盤が常時⚠になり、**本当に止まった作業がその中に埋もれる**
        #   （鳴りすぎる警報は鳴らないのと同じ）。別の状態として出す。
        #   ⚠**健全と読ませない**ためにラベルは残す＝「穴を明示する」の作法。
        if state == "due" and auto == "key":
            state = "nokey"
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
            "note": "state=due は「期限日数を超えて止まっている」の機械判定。"
                    "unknown は日付が取れない＝健全と読まないこと。"
                    "**nokey は鍵待ち**（止まったのではなく、まだ始めていない）——"
                    "健全ではないが『止まった』とも違うので別の色で出す"}


def main():
    out = build()
    p = os.path.join(BASE, "out", "ops_status.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_due = sum(1 for r in out["items"] if r["state"] == "due")
    n_unk = sum(1 for r in out["items"] if r["state"] == "unknown")
    n_key = sum(1 for r in out["items"] if r["state"] == "nokey")
    print(f"運用サイクル {len(out['items'])}本: 期限内 {len(out['items'])-n_due-n_unk-n_key}"
          f" / 停止疑い {n_due} / 鍵待ち {n_key} / 不明 {n_unk}")
    for r in out["items"]:
        mark = {"ok": "🟢", "due": "⚠", "unknown": "？", "nokey": "🔑"}[r["state"]]
        ago = "" if r["days"] is None else f"（{r['days']}日前・期限{r['due_days']}日）"
        print(f"  {mark} {r['name']:<14}（{r['cadence']}）最終 {r['last'] or '不明'}{ago}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
