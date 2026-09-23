#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_price_tail_vintages.py — 「極端な倍率だけ押し目待ち」の恒久毀損を、別ビンテージで n を厚くして測り直す
（2026-09-23新設・todo `price_tail_gate` の宿題「採るなら別ビンテージで n を厚くするのが先」）

なぜ要るか:
  night/retro_price_tail.py（2026-08-07）は「一貫して悪いのは恒久毀損だけ（4つの切り方すべてで上昇）」と
  出したが、**質実証プール（門が当てる場所）での分子は1社（MLCO）**で、規約にするには薄かった。
  しかも PER÷fairPER の倍率と質実証プールを作れたのは **2018年の一窓だけ**だった
  （2013/2015 は生PER・全母集団のみ。2015 は137社の抽出）。
  → 定義を1文字も変えずに、在庫で作れるビンテージを全部作り、分子を**社名つきで**数え直す。

順番が肝（結果を見る前に線を固定する）:
  ① --prereg : 仮説・切り方・物差し・合格基準を out/retro_price_tail_vintages.json の "preregistered" に書く。
               sha256 と時刻を刻む。**既に在れば上書きしない**（中身が違えば止まる＝後から動かせない）
  ② --fetch  : Yahoo 月足（close＋adjclose＋splits）を **1社1回** で取る——hist_valuation.fetch_px をそのまま使う
               （2004-01〜今日・キャッシュ再開可能）。ビンテージごとに叩き直さない（956社×7回 → 956回）
  ③ --run    : 在庫を組み、**まず再現検査**（2018/2013/2015 の記録済みの数字を1桁違わず出せるか・
               新しい株価の器が既存の px を再現するか）、次に事前登録どおりに判定して同じファイルへ追記する。
               事前登録の sha256 がコードと食い違えば止まる

再実装しない（v9.9.65）:
  PER       = retro_per_asof（annual_entries / latest_before / NI_TAGS / SH_TAGS / 帯検問 2-200）
  当時の板値 = retro_per_asof.fetch_raw_close と同じ意味論（asof年7月の足の close × 7/1以降の分割の累積）を
              hist_valuation.fetch_px のキャッシュから切り出す（fetch_raw_close はビンテージごとに1回叩く器なので）
  統計・判定 = retro_price_tail.st() と cut() の判定式（各ビンテージで cut() 自身と突き合わせて一致を確かめる）
  母集団    = retro_er_test.build() の条件（per・cagr5・payout5・tr_cagr がそろい、shy 帯 −5〜15）
  2015 の特徴量 = retro_features2.build_row（在庫の2015は506社の抽出なので956社で組み直す）
  2015 のリターン = retro_anchors_new.py と同じ月キー方式（adjclose・配当込み）

読むだけの在庫（書き換えない）:
  out/retro_per_2013_all.json / out/retro_per_2018_all.json、out/retro_features2_{2013,2016..2022}.json、
  out/retro_returns_2013_all.json / out/retro_returns_{2016..2022}.json、out/retro_cohort_2013.json（社名・CIK）、
  out/retro_er_test.json / out/retro_price_tail.json（再現検査の答え）。
  新しく算出した PER・2015 の特徴量とリターンは**ファイルに書かない**（retro_per_{Y}_all.json を作ると
  他の道具の glob に黙って拾われる）。行は結果JSONの "rows" に同梱する。

⚠ 依存: out/retro_delisted_2013.json（退場銘柄の出口日）は 2026-09-23 に別作業で作り直し中なので**読まない**。
  本器の母集団は「2026年に生きている956社」＝生存者条件付きのまま。倒産した社（−100%）は分子に入らない。

実測（2026-09-23・事前登録 sha256 9203f52f… を 13:25Z に書いてから回した）:
  ・再現検査は全部通った: retro_er_test の581行・retro_price_tail の2018の4ブロック・2013(701)/2015(136)の生PERを1桁違わず再現。
    新しい株価の器は既存在庫の px を 2013/2018 とも 100% が1%以内で再現。組み直した特徴量は在庫と差0件（8ビンテージ＋2015の506社）
  ・主（質実証プール × PER÷fair>4）: **P_tail=FAIL_direction**（支持 2/7＝2019・2020 だけ）。分子は MLCO・OSUR・SAM の3社。
    2013/2015/2016/2017 起点（9-13年窓）の極端な裾は恒久毀損0で、中央値はむしろ高い。悪化は 2019-2022 起点の短い窓だけ
  ・全母集団（文脈）は 4/7 で境界線上（EPSの欠陥行を外すと 5/7）。極端な裾には EPS の会計年度が古い行が 10-60%（中央値25%・母集団は4-7%）集まっている
  ・詳細は out/retro_price_tail_vintages.json の verdict / reading_2026_09_23 / post_hoc_not_in_verdict

使い方:
  python3 night/retro_price_tail_vintages.py --prereg
  python3 night/retro_price_tail_vintages.py --fetch [--cache DIR]
  python3 night/retro_price_tail_vintages.py --run   [--cache DIR]
  （--cache を省くと hist_valuation と同じ out/_histval_cache/ ＝ .gitignore 済み）
  ⚠ Yahoo は 2026-07 頃から BBBY/EA/EQR/HLX/ISSC/LEG/QVCAQ/SALM の過去の系列を返さない（範囲指定は HTTP 400）。
    本器が算出するビンテージではこの8社の PER が作れない（validation.px_series_start_after_2013_07 に名指し）
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import statistics
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DEST = os.path.join(OUT, "retro_price_tail_vintages.json")
sys.path.insert(0, os.path.join(ROOT, "night"))

import retro_per_asof as RP       # noqa: E402  PER の作法
import retro_price_tail as RPT    # noqa: E402  st() と cut()
import retro_features2 as RF      # noqa: E402  build_row
import hist_valuation as HV       # noqa: E402  fetch_px（Yahoo 月足・キャッシュ）

IMPAIR = RPT.IMPAIR                # −15.0（恒久毀損の線・retro_price_tail と同じ）
COUNTED = (2013, 2015, 2016, 2017, 2019, 2020, 2021)
DISCOVERY = (2018,)
SENS_ONLY = (2022,)
ALL_V = (2013, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022)
CELLS = {"Q>4": ("quality", 4.0), "Q>3": ("quality", 3.0), "F>4": ("full", 4.0), "F>3": ("full", 3.0)}
PRIMARY = "Q>4"
K_MIN = 5          # 支持ビンテージの下限（7つ中）
M_MIN = 5          # 分子（重複を除いた社数）の下限
THIN = 8           # 止めた群がこれ未満なら結論にしない（retro_price_tail.cut と同じ）
STALE_D = 450      # EPS の会計年度の古さの上限（retro_mcap.LAG_MAX と同じ）
GRID = (2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0)   # retro_price_tail の ratio 格子（記述のみ）
RET_END_MK = "2026-08"   # 2015 のリターンの終点の月（他ビンテージの在庫が 2026-08 で終わっているのに揃える）

PER_SRC = {2013: "retro_per_2013_all.json", 2018: "retro_per_2018_all.json"}
RET_SRC = {2013: "retro_returns_2013_all.json", 2016: "retro_returns_2016.json",
           2017: "retro_returns_2017.json", 2018: "retro_returns_2018.json",
           2019: "retro_returns_2019.json", 2020: "retro_returns_2020.json",
           2021: "retro_returns_2021.json", 2022: "retro_returns_2022.json"}
FEA_SRC = {y: f"retro_features2_{y}.json" for y in ALL_V if y != 2015}

# ═════════════════════════════════════════════════════════════════════════════
# 事前登録（2026-09-23・**新しいビンテージの結果を一つも見る前に**書いた）。
# ここを書き換えると --run が sha256 の不一致で止まる。直したくなったら "deviations" に理由を書くこと。
# ═════════════════════════════════════════════════════════════════════════════
PREREG = {
    "todo": "price_tail_gate（極端な倍率〔fairPERの4倍超など〕だけを押し目待ちにするか）",
    "status": "測定であって決定ではない。関門にするか否かはユーザーの明示指示の領分（CLAUDE.md 絶対のルール1）。この道具は todo_list.json も門も触らない",
    "discovery": {
        "source": "out/retro_price_tail.json（night/retro_price_tail.py・2026-08-07）",
        "what_was_seen": "2018年（発見のビンテージ）: 質実証プール274社で PER÷fair>4 は止めた19社・恒久毀損5.3%（分子1社=MLCO）vs プール全体2.2%、"
                         ">3 は33社・3.0%（分子1社）。全母集団581社で >3 は77社・6.5% vs 4.5%、>4 は43社・7.0% vs 4.5%。"
                         "2013（生PER・全母集団のみ）と2015（137社の抽出・生PERのみ）では質実証プールも fair 比も作っていない",
        "not_yet_seen": "2013/2015/2016/2017/2019/2020/2021/2022 の『PER÷fair × 質実証プール × 恒久毀損』はこの切り方では一度も測っていない"
                        "（2016/2017/2019-2022 は PER の在庫そのものが無かった。hist_val 系が測ったのは自己相対PERで別の問い）",
    },
    "post_hoc_rule": "結果を見た後に線・プール・ビンテージ・母集団を足したら、それは探索として別に記し、この判定には混ぜない。"
                     "事前登録を直す必要が出たら PREREG は書き換えず、結果JSONの deviations に理由を書く",
    "hypothesis": {
        "H1_primary": "質実証プールの中で PER÷fairPER>4 の社（止めた群）は、恒久毀損率（配当込み実現年率≤−15%）が"
                      "プール全体より高い。それがビンテージをまたいで一貫し、分子が1社ではない",
        "H2_breaker": "H1 に加えて、止めた群の実現年率の中央値が通過群より低い（門の遮断器の作法＝両方向・v9.9.98/99）",
        "secondary": "同じ検定を PER÷fair>3（2026-08-07 の見出しの線）でも、全母集団（文脈）でも回す。判定の主は Q>4",
    },
    "definitions": {
        "same_as": "night/retro_price_tail.py（2018 の行は night/retro_er_test.py の build() の母集団）。定義は1文字も変えない",
        "per": "retro_per_asof の作法: 純利益=NI_TAGS の年次(330-400日)USDで、FY末が asof年03-01 以前の最後の年度・"
               "同じ(タグ,期末)は filed が最も古い値（as-reported）。株数=SH_TAGS（加重平均希薄化後→基本）を同じ規則で。"
               "eps=純利益÷株数、per=px÷eps、ni>0 ∧ 株数>0 ∧ 2≤per≤200。"
               "px=asof年7月の月足の close（Yahoo・今日までの分割で調整済み）× asof年07-01 以降の分割比の累積（＝当時の板の値）",
        "per_sources": "2013 と 2018 は既存在庫（out/retro_per_2013_all.json / out/retro_per_2018_all.json）。"
                       "2015/2016/2017/2019/2020/2021/2022 は本器が同じ関数で算出（株価は hist_valuation.fetch_px の月足キャッシュ）。"
                       "使う前に、新しい器で 2013/2018 の px を再計算して既存在庫と突き合わせる（再現検査）",
        "fair_ratio": "g=round(min(max(cagr5×100,0),20),2)／fair=max(16,min(30,8+g))／ratio=per÷fair（門X本体と同式）",
        "features": "out/retro_features2_{y}.json（filed≤asof年07-01）。2015 は在庫が506社の抽出なので"
                    "retro_features2.build_row で956社を組み直す（在庫と重なる社で値の一致を確かめてから使う）",
        "returns": "tr_cagr（Yahoo adjclose＝配当込み）。2013=retro_returns_2013_all、2016-2022=retro_returns_{y}（既存）。"
                   "2015 は全社版の在庫が無いので fetch_px の adjclose から retro_anchors_new.py と同じ月キー方式で作る"
                   "（起点=2015-07 の足・終点=2026-08 の足・年数=月数÷12）",
        "population_A": "retro_er_test.build() の条件そのまま: per・cagr5・payout5・tr_cagr がそろい、2≤per≤200、"
                        "shy=payout5÷per×100 が −5〜15。母集団は 956 ティッカー（out/retro_returns_2016.json の行＝全ビンテージ共通の名簿）",
        "quality_pool": "opm≥0.10 ∧ fcfpos5≥5（None は0扱い＝外れる）。retro_price_tail.py と同一。"
                        "⚠堀の読解は歴史側に無いので『門が当てる場所』は機械の質の代理",
        "guard_window": "（新設・結果を見る前に決めた唯一の追加）リターンの系列が asof年7月の足から始まっていない行は外して名指しする。"
                        "既存在庫には起点が asof より後の行がある（例: DBD 2023-08 / GPOR 2021-05 / EXE 2021-02 ＝倒産後の新株、"
                        "HWM 2016-11 ＝分社後）——別の証券のリターンを当時の倍率に結び付けることになるため。"
                        "判定: 2013-2018 の在庫は start==asof年07-01、2019-2022 の在庫は start が固定書きなので years==そのビンテージの最頻値、"
                        "2015（本器）は最初の足が 2015-07。新しく算出する px も asof年7月の足が無ければ算出しない（後の月へ滑らせない）",
    },
    "metrics": "retro_price_tail.st() をそのまま import: n / 中央値(real=tr_cagr×100) / impair=P(real≤−15) / win15=P(real≥15)",
    "cells": {
        "Q>4": "主。質実証プールで ratio>4 を止めた群 vs ratio≤4",
        "Q>3": "副。質実証プールで ratio>3",
        "F>4": "文脈。全母集団で ratio>4",
        "F>3": "文脈。全母集団で ratio>3",
    },
    "per_vintage_flags": {
        "thin": "止めた群 n<8 は結論にしない（retro_price_tail.cut と同じ）＝支持に数えない",
        "imp_up": "blocked.impair > base.impair + 0.01（base＝そのプール全体・丸めた値どうし。retro_price_tail.cut と同じ式）",
        "med_down": "blocked.med < passed.med − 0.5（同上）",
    },
    "vintages": {
        "counted": list(COUNTED),
        "discovery_not_counted": list(DISCOVERY),
        "sensitivity_only": list(SENS_ONLY),
        "why": "2018 は仮説を生んだ窓なので数えない（再現検査として報告）。2022 は窓が4.1年で、年率−15%の線が"
               "累積−48%しか意味しない（13年窓では−88%）ので数えない（感度S3として報告）。"
               "2014 は在庫が無く、この台帳のビンテージ集合（retro_gwg_vintages 等の 2013/2015-2021）にも無いので作らない",
    },
    "pass_criteria": {
        "support": "counted の7ビンテージのうち、thin でなく imp_up が立ったビンテージの数",
        "numerator": "支持したビンテージで『止めた群 ∧ 恒久毀損』に入った社の、ビンテージをまたいで重複を除いた社数",
        "P_tail": "support≥5（7つ中）∧ numerator≥5社 ＝『裾の保険』の証拠が一社の偶然ではない",
        "P_breaker": "P_tail ∧ （imp_up ∧ med_down）のビンテージが≥5 ＝門の遮断器の作法（両方向）でも立つ",
        "labels": "PASS／FAIL_direction（thinでないビンテージが5以上あるのに支持が5未満）／"
                  "FAIL_thin_numerator（支持は5以上だが分子が5社未満）／UNDETERMINED（thinでないビンテージが5未満＝原理的に届かない）"
                  "／P_breaker だけの FAIL_median（P_tail は通るが中央値の方向がそろわない）",
        "headline": "判定の主は Q>4 の P_tail。PASS なら『別ビンテージで n を厚くしても恒久毀損の上昇が残った』＝todo を再開する材料。"
                    "PASS でなければ 2026-08-07 の結論（関門にしない・fair線の表示で指値対応）を支える材料",
    },
    "robustness": {
        "S1_stale_eps": "EPS の会計年度が cutoff から450日超古い、または株数の期末が純利益の期末と違う行を外す（retro_mcap が名指しした在庫の欠陥）",
        "S2_split_gap": "株数の提出日から asof年07-01 の間に分割がある行を外す（NKE/HAE 型＝株数は分割前・株価は分割後で PER が分割比だけ安く出る）",
        "B_population": "payout5 と shy 帯の条件を外した母集団（per・cagr5・tr_cagr だけ要求）。payout5 は2013で被覆が薄い（XBRL前の年が窓に入る）",
        "S3_with_2022": "counted に 2022 を足した8ビンテージ・support≥6（=ceil(8×5/7)）",
        "robust_if": "Q>4 の P_tail の判定ラベルが S1・S2・B のすべてで本判定と同じ。S3 は報告のみ",
        "also_reported": "2018 を含めた 2013-2021 の8ビンテージでの support（記述のみ）",
    },
    "descriptive_only": [
        "ratio 格子 2.0〜6.0（retro_price_tail と同じ）の全ビンテージ×両プール——判定には使わない",
        "counted をプールした観測（社×ビンテージ）の恒久毀損率と相対危険度——同じ社が何度も出るので独立ではない",
        "質実証プールの通過群側で恒久毀損に落ちた社の名前（分子が低倍率側に偏っていないかを見るため）",
    ],
    "known_limits_declared_in_advance": [
        "生存者条件付き: 母集団は2013コホートのうち2026年に Yahoo で取引が続いている956社。倒産・被買収・上場廃止は入らない（恒久毀損は下限）",
        "独立標本ではない: 全ビンテージが同じ956ティッカーで、窓はすべて2026年終点＝重なる。『7つ中5つ』は独立試行の数ではない",
        "窓の長さが違う: 2013=13.1年 … 2021=5.1年。同じ−15%/年でも累積の意味が違うので、ビンテージ間でベース率を比べない",
        "2013年以降のIPOは入らない: 2019-2021年の高倍率の裾（新規上場のSaaS等）は構造的に欠ける",
        "PER 200超と赤字は帯検問で母集団に居ない（retro_per_asof:150）＝『PER 300』には答えられない",
        "EPS は通期の as-reported（TTMではない）。株価は asof年7月末の終値（1ヶ月先の値・原器と同じ）",
        "USD 報告の ADR は株数(普通株)と株価(ADS)の比で PER がずれうる（TSM/SAP 型）",
    ],
}


# 2026-09-23 の実測の読み（事前登録の外。結果を見た後に書いた要約＝判定は "verdict" が正）
READING_20260923 = [
    "事前登録どおりの判定（主: 質実証プール × PER÷fair>4）: P_tail=FAIL_direction。支持は 2/7（2019・2020 だけ）で、"
    "thin でないビンテージは 2016/2017/2019/2020/2021 の5つ。P_breaker も同じ",
    "分子（支持したビンテージで『止めた群∧恒久毀損』）は MLCO・OSUR・SAM の3社。counted 全体では NICE・IPGP（2021）を足して5社だが、"
    "2021 はプール全体の毀損率 9.2% のほうが止めた群 6.9% より高く、支持にならない。1社（MLCO）→3社に増えたが、方向がそろわない",
    "長い窓では極端な裾に恒久毀損が一件も無い: 2013(13.1年)/2015(11.1)/2016(10.1)/2017(9.1) の Q>4 の止めた群は 4/5/8/10社で毀損0。"
    "中央値も 2015-2018 起点では止めた群のほうが高い（13.6/9.8/11.4/10.1% vs 通過 7.6/7.7/8.4/7.2%）",
    "毀損の上昇と中央値の悪化が出るのは短い窓（2019-2022 起点・4-7年）だけ＝2020-21年の高値圏で乗った窓。"
    "窓の長さと相場の局面が交絡しているので、この在庫ではどちらの効果かを分けられない（全窓が2026年終点）",
    "副（Q>3）も FAIL_direction（支持 2/7）。文脈の全母集団（F>4/F>3）は 4/7 で本判定は FAIL_direction だが、"
    "S1・S2（EPSの欠陥行・分割ずれ行を外す）と B（F>4）では 5/7 で PASS に届く＝全母集団では『高倍率の裾は壊れやすい』が境界線上で残る。"
    "門が当てる質のプールでは残らない",
    "頑健性: 主セルは S2・B・S3・2018込みで FAIL_direction、S1 で UNDETERMINED（ラベルが変わるので事前登録の定義では robust=false）。"
    "どの変種でも PASS にはならない",
    "プールした観測（記述・独立ではない）: Q>4 の止めた群 79観測（54社）で恒久毀損 6.3% vs 通過 2.8%（相対危険度2.25）・中央値 4.8% vs 8.2%。"
    "毀損5観測はすべて 2019-2021 起点",
    "事後の観察（判定に混ぜない）: Q>4 の止めた群の 10-60%（中央値25%）が『EPSの会計年度が古い／株数と純利益の期末が合わない』行"
    "（BKNG・WST・ECL・EGP・CCI 等）で、母集団の 4-7% より何倍も濃い＝極端な倍率の裾は在庫の欠陥（todo retro_per_stale_fy）が集まる場所。"
    "2026-08-07 の記録が挙げた『WST 8.0x・ECL 4.9x』にもこの印が立つ",
    "結論（測定として）: 別ビンテージで n を厚くしても、質実証プールでの恒久毀損の上昇は一貫しなかった。"
    "2026-08-07 の結論（関門にしない・fair線の表示で指値対応）を支える材料。採否はユーザーの判断",
]


def prereg_sha():
    s = json.dumps(PREREG, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_dest():
    if not os.path.exists(DEST):
        return None
    return json.load(open(DEST, encoding="utf-8"))


def write_dest(obj):
    tmp = DEST + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, DEST)


def cmd_prereg():
    h = prereg_sha()
    cur = load_dest()
    if cur and cur.get("preregistered") is not None:
        if cur.get("prereg_sha256") == h:
            print(f"■ 事前登録は既に在る（sha256 {h[:16]}… 一致）。何もしない")
            return 0
        print("■ 既存の事前登録とコードの PREREG が食い違う——上書きしない（後から線を動かさない）")
        return 2
    write_dest({"generated": dt.date.today().isoformat(),
                "tool": "night/retro_price_tail_vintages.py",
                "preregistered": PREREG,
                "prereg_sha256": h,
                "prereg_written_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "deviations": [],
                "results": None,
                "note": "結果はまだ無い（--run が追記する）"})
    print(f"■ 事前登録を書いた: {DEST}  sha256 {h}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 名簿・在庫
# ─────────────────────────────────────────────────────────────────────────────
def universe():
    return [r["ticker"] for r in RPT.rows_of("retro_returns_2016.json")]


def cohort_maps():
    rows = json.load(open(os.path.join(OUT, "retro_cohort_2013.json"), encoding="utf-8"))["rows"]
    t2cik = {r["ticker"]: r["cik"] for r in rows if r.get("ticker")}
    names = {r["ticker"]: (r.get("name") or "") for r in rows if r.get("ticker")}
    return t2cik, names


def set_cache(cache):
    if cache:
        HV.CACHE = os.path.abspath(cache)


def px_of(t):
    """hist_valuation のキャッシュを読むだけ（ネットには出ない）。"""
    return HV.fetch_px(t, offline=True)


def cmd_fetch(cache):
    set_cache(cache)
    tick = universe()
    print(f"■ Yahoo 月足を {len(tick)}社ぶん取る（キャッシュ {HV.CACHE}/px）")
    bad = []
    for i, t in enumerate(tick, 1):
        p = os.path.join(HV.CACHE, "px", f"{t.upper().replace('/', '_')}.json.gz")
        j = HV.fetch_px(t)
        tries = 0
        while (not j or not j.get("close")) and tries < 2:
            # fetch_px は一時的な失敗も 'yahoo_no_data' としてキャッシュする——消して取り直す
            tries += 1
            time.sleep(6 * tries)
            if os.path.exists(p):
                os.remove(p)
            j = HV.fetch_px(t)
        if not j or not j.get("close"):
            bad.append(t)
        time.sleep(0.25)
        if i % 50 == 0:
            print(f"  {i}/{len(tick)}  取れない {len(bad)}", flush=True)
    print(f"■ 完了: 取れない {len(bad)}社 {bad[:30]}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 当時の板の値・PER・特徴量・リターン
# ─────────────────────────────────────────────────────────────────────────────
def px_at(pxd, y):
    """retro_per_asof.fetch_raw_close と同じ意味論: asof年7月の足の close × asof年07-01 以降の分割比の累積。
    ただし7月の足が無ければ None（原器は『最初に値のある足』を採る＝後の月へ滑る。ここでは滑らせない）。"""
    if not pxd:
        return None
    c = (pxd.get("close") or {}).get(f"{y}-07")
    if c is None:
        return None
    f = 1.0
    for s in pxd.get("splits") or []:
        if s["date"] >= f"{y}-07-01":
            f *= s["ratio"]
    return c * f


def filed_of(entries, pick):
    if not pick:
        return None
    fl = [f for (_tag, en), (v, f) in entries.items() if en == pick[0] and v == pick[1]]
    return min(fl) if fl else None


def split_gap(pxd, sh_filed, y):
    """株数の提出日より後・asof年07-01 より前の分割の累積（≠1 なら株数と株価の基準が割れている）。"""
    if not pxd or not sh_filed:
        return None
    f = 1.0
    for s in pxd.get("splits") or []:
        if sh_filed < s["date"] < f"{y}-07-01":
            f *= s["ratio"]
    return f


def per_block(facts, pxd, years):
    """retro_per_asof.main() の1社ぶんをビンテージの数だけ回す（株価だけキャッシュから）。"""
    ni_e = RP.annual_entries(facts, RP.NI_TAGS, ("USD",))
    sh_e = RP.annual_entries(facts, RP.SH_TAGS, ("shares",))
    out = {}
    for y in years:
        cutoff = f"{y}-03-01"
        ni = RP.latest_before(ni_e, cutoff)
        sh = RP.latest_before(sh_e, cutoff)
        px = px_at(pxd, y)
        rec = {"ni_end": ni[0] if ni else None, "sh_end": sh[0] if sh else None,
               "sh_filed": filed_of(sh_e, sh), "px_raw": px}
        if not ni or not sh or px is None or ni[1] <= 0 or sh[1] <= 0:
            rec["why"] = "eps_or_px"
        else:
            eps = ni[1] / sh[1]
            per = px / eps
            if not (2 <= per <= 200):
                rec["why"] = f"per_band {per:.1f}"
            else:
                rec.update(px=round(px, 2), eps_fy=round(eps, 3), fy_end=ni[0], per=round(per, 2))
        out[y] = rec
    return out


def mk_i(mk):
    return int(mk[:4]) * 12 + int(mk[5:7]) - 1


def ret_from_px(pxd, y, end_mk=RET_END_MK):
    """retro_anchors_new.py と同じ月キー方式の実現リターン（adjclose・配当込み）。"""
    adj = (pxd or {}).get("adj") or {}
    ks = sorted(k for k, v in adj.items() if f"{y}-07" <= k <= end_mk and v and v > 0)
    if not ks:
        return None
    k0, k1 = ks[0], ks[-1]
    p0, p1 = adj[k0], adj[k1]
    yrs = (mk_i(k1) - mk_i(k0)) / 12.0
    peak, mdd = p0, 0.0
    for k in ks:
        peak = max(peak, adj[k])
        mdd = min(mdd, adj[k] / peak - 1.0)
    stale = k1 != end_mk
    ok = (not stale) and yrs >= 1
    return {"ticker": None, "group": "all", "start": f"{k0}-01", "end": f"{k1}-01",
            "years": round(yrs, 2), "mdd": round(mdd, 4), "stale": stale,
            "tr_total": round(p1 / p0, 4), "tr_cagr": round((p1 / p0) ** (1 / yrs) - 1, 4) if ok else None}


def modal_years(rets):
    c = {}
    for r in rets.values():
        c[r.get("years")] = c.get(r.get("years"), 0) + 1
    return max(c.items(), key=lambda kv: kv[1])[0] if c else None


def window_ok(y, rr, modal):
    """リターンの系列が asof年7月の足から始まっているか（guard_window）。"""
    if y >= 2019:
        return rr.get("years") == modal
    return rr.get("start") == f"{y}-07-01"


# ─────────────────────────────────────────────────────────────────────────────
# 母集団・セル・判定
# ─────────────────────────────────────────────────────────────────────────────
def build_pop(y, perm, fea, ret, flags, modal, guard=True, require_payout=True):
    """retro_er_test.build() の条件そのまま（require_payout=False が感度B）。"""
    rows, excluded = [], []
    for t, f in fea.items():
        p, rr = perm.get(t), ret.get(t)
        if not p or not rr:
            continue
        pv, c5, po, tr = p.get("per"), f.get("cagr5"), f.get("payout5"), rr.get("tr_cagr")
        if pv is None or c5 is None or tr is None:
            continue
        if require_payout and po is None:
            continue
        if not (2 <= pv <= 200):
            continue
        g = min(max(c5 * 100, 0.0), 20.0)
        if require_payout:
            shy = po / pv * 100.0
            if not (-5 <= shy <= 15):
                continue
        row = dict(t=t, per=pv, g=round(g, 2), real=round(tr * 100, 2))
        row["ratio"] = pv / max(16.0, min(30.0, 8.0 + row["g"]))
        row["q"] = (f.get("opm") or 0) >= 0.10 and (f.get("fcfpos5") or 0) >= 5
        fl = flags.get(t) or {}
        row["stale_eps"] = bool(fl.get("stale_eps"))
        row["split_gap"] = bool(fl.get("split_gap"))
        if guard and not window_ok(y, rr, modal):
            excluded.append(dict(t=t, start=rr.get("start"), years=rr.get("years"),
                                 per=pv, ratio=round(row["ratio"], 2), q=row["q"], real=row["real"]))
            continue
        rows.append(row)
    return rows, excluded


VERDICT = ("◎中央値も低い＝両方向とも正しい", "△恒久毀損だけ高い＝裾の保険にはなるが勝者も掴む", "×効かない")


def cell(pool, th, names, listing=True):
    base = RPT.st(pool)
    blk = [r for r in pool if r["ratio"] > th]
    pas = [r for r in pool if r["ratio"] <= th]
    b, p = RPT.st(blk), RPT.st(pas)
    thin = len(blk) < THIN
    imp_up = (not thin) and b is not None and base is not None and b["impair"] > base["impair"] + 0.01
    med_down = (not thin) and b is not None and p is not None and b["med"] < p["med"] - 0.5
    if thin:
        verdict = "薄い（止めた群 n<8・結論にしない）"
    else:
        verdict = VERDICT[0] if (med_down and imp_up) else (VERDICT[1] if imp_up else VERDICT[2])
    out = dict(th=th, n_pool=len(pool), base=base, blocked=b, passed=p, thin=thin,
               imp_up=imp_up, med_down=med_down, verdict=verdict,
               n_blocked_impaired=sum(1 for r in blk if r["real"] <= IMPAIR),
               n_passed_impaired=sum(1 for r in pas if r["real"] <= IMPAIR))
    if listing:
        out["numerator"] = sorted(
            (dict(t=r["t"], name=names.get(r["t"], ""), per=r["per"], ratio=round(r["ratio"], 2), real=r["real"])
             for r in blk if r["real"] <= IMPAIR), key=lambda x: x["real"])
    return out


def selfcheck_cut(pool, th, mine):
    """retro_price_tail.cut() 自身を同じプールに当て、止めた群・通過群・判定が一致するかを確かめる。"""
    base = RPT.st(pool)
    if not base:
        return True
    with contextlib.redirect_stdout(io.StringIO()):
        res = RPT.cut(pool, base, lambda r: r["ratio"], (th,), "selfcheck")
    if mine["thin"]:
        return res == []
    return (len(res) == 1 and res[0]["blocked"] == mine["blocked"] and res[0]["passed"] == mine["passed"]
            and res[0]["verdict"] == mine["verdict"])


def judge(cells_by_v, cname, vintages, k_min):
    nonthin = [y for y in vintages if not cells_by_v[y][cname]["thin"]]
    sup = [y for y in vintages if cells_by_v[y][cname]["imp_up"]]
    both = [y for y in sup if cells_by_v[y][cname]["med_down"]]
    distinct = sorted({n["t"] for y in sup for n in cells_by_v[y][cname].get("numerator", [])})
    distinct_all = sorted({n["t"] for y in vintages for n in cells_by_v[y][cname].get("numerator", [])})
    if len(nonthin) < k_min:
        tail = "UNDETERMINED"
    elif len(sup) < k_min:
        tail = "FAIL_direction"
    elif len(distinct) < M_MIN:
        tail = "FAIL_thin_numerator"
    else:
        tail = "PASS"
    breaker = tail if tail != "PASS" else ("PASS" if len(both) >= k_min else "FAIL_median")
    return dict(vintages=list(vintages), k_min=k_min, m_min=M_MIN, nonthin=nonthin, support=sup,
                support_both=both, numerator_distinct_in_support=distinct,
                numerator_distinct_all_counted=distinct_all, P_tail=tail, P_breaker=breaker)


def pooled(pops_by_v, cname, vintages, names):
    pool_name, th = CELLS[cname]
    blk, pas = [], []
    for y in vintages:
        pool = pops_by_v[y][pool_name]
        blk += [dict(r, y=y) for r in pool if r["ratio"] > th]
        pas += [dict(r, y=y) for r in pool if r["ratio"] <= th]
    b, p = RPT.st(blk), RPT.st(pas)
    rr = (b["impair"] / p["impair"]) if (b and p and p["impair"] > 0) else None
    imp_b = sorted({r["t"] for r in blk if r["real"] <= IMPAIR})
    imp_p = sorted({r["t"] for r in pas if r["real"] <= IMPAIR})
    return dict(obs_blocked=b, obs_passed=p, relative_risk=round(rr, 2) if rr else None,
                distinct_blocked=len({r["t"] for r in blk}), distinct_passed=len({r["t"] for r in pas}),
                distinct_blocked_impaired=[f"{t} {names.get(t, '')}".strip() for t in imp_b],
                n_distinct_passed_impaired=len(imp_p),
                note="社×ビンテージの観測をプールした記述。同じ社が何度も出るので独立ではない（判定には使わない）")


# ─────────────────────────────────────────────────────────────────────────────
# 再現検査
# ─────────────────────────────────────────────────────────────────────────────
def repro_2018(names):
    """retro_er_test.build() と retro_price_tail の 2018 の数字を、既存在庫から1桁違わず出せるか。"""
    per = {r["ticker"]: r for r in RPT.rows_of("retro_per_2018_all.json")}
    fea = {r["ticker"]: r for r in RPT.rows_of("retro_features2_2018.json")}
    ret = {r["ticker"]: r for r in RPT.rows_of("retro_returns_2018.json")}
    rows, _ = build_pop(2018, per, fea, ret, {}, None, guard=False)
    er = {r["t"]: r for r in RPT.rows_of("retro_er_test.json")}
    mism = [r["t"] for r in rows if r["t"] not in er or er[r["t"]]["per"] != r["per"]
            or er[r["t"]]["g"] != r["g"] or er[r["t"]]["real"] != r["real"]]
    rec = json.load(open(os.path.join(OUT, "retro_price_tail.json"), encoding="utf-8"))["results"]
    qp = [r for r in rows if r["q"]]
    out = {"er_test_rows": {"mine": len(rows), "recorded": len(er), "mismatch": mism[:20],
                            "missing": sorted(set(er) - {r["t"] for r in rows})[:20]}}
    bad = []
    for label, pool in (("2018年 全母集団", rows), ("2018年 質実証プール＝門が当てる場所", qp)):
        base = RPT.st(pool)
        with contextlib.redirect_stdout(io.StringIO()):
            got = RPT.cut(pool, base, lambda r: r["ratio"], (2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0), "x")
            gotp = RPT.cut(pool, base, lambda r: r["per"], (40, 50, 60, 70, 80, 90, 100, 110, 120), "x")
        for key, g in ((label + "/ratio", got), (label + "/PER", gotp)):
            want = rec.get(key)
            if json.loads(json.dumps(g)) != want:
                bad.append(key)
    out["retro_price_tail_2018_cells_reproduced"] = not bad
    out["mismatched_blocks"] = bad
    out["n_full"], out["n_quality"] = len(rows), len(qp)
    return out


def repro_raw(yr, pf, rf, recorded_key):
    """retro_price_tail の 2013/2015（生PER・全母集団）を再現する。"""
    per = {(r.get("ticker") or r.get("t")): r for r in RPT.rows_of(pf)}
    ret = {(r.get("ticker") or r.get("t")): r for r in RPT.rows_of(rf)}
    g = []
    for t, p in per.items():
        rr, pv = ret.get(t), p.get("per")
        if not rr or pv is None or rr.get("tr_cagr") is None or not (2 <= pv <= 200):
            continue
        g.append(dict(t=t, per=pv, real=rr["tr_cagr"] * 100))
    rec = json.load(open(os.path.join(OUT, "retro_price_tail.json"), encoding="utf-8"))["results"].get(recorded_key)
    b = RPT.st(g)
    with contextlib.redirect_stdout(io.StringIO()):
        got = RPT.cut(g, b, lambda r: r["per"], (40, 50, 60, 70, 80, 90, 100, 120), "x")
    return {"n": len(g), "reproduced": json.loads(json.dumps(got)) == rec}


# ─────────────────────────────────────────────────────────────────────────────
# 本体
# ─────────────────────────────────────────────────────────────────────────────
def compact(rows):
    return [[r["t"], r["per"], r["g"], round(r["ratio"], 3), r["real"], int(r["q"]),
             int(r["stale_eps"]), int(r["split_gap"])] for r in rows]


def cmd_run(cache):
    cur = load_dest()
    h = prereg_sha()
    if not cur or cur.get("prereg_sha256") != h or cur.get("preregistered") is None:
        print("■ 事前登録が無い／コードの PREREG と sha256 が合わない——止める（先に --prereg）")
        return 2
    set_cache(cache)
    tick = universe()
    t2cik, names = cohort_maps()
    t0 = time.time()

    # ── 在庫の読み込み ─────────────────────────────────────────────────────
    per_inv = {y: {r["ticker"]: r for r in RPT.rows_of(f)} for y, f in PER_SRC.items()}
    fea_inv = {y: {r["ticker"]: r for r in RPT.rows_of(f)} for y, f in FEA_SRC.items()}
    fea_inv[2015] = None
    ret_inv = {y: {r["ticker"]: r for r in RPT.rows_of(f)} for y, f in RET_SRC.items()}
    fea15_old = {r["ticker"]: r for r in RPT.rows_of("retro_features2_2015.json")}
    ret15_old = {r["ticker"]: r for r in RPT.rows_of("retro_returns_2015_q.json")}
    per15_old = {r["ticker"]: r for r in RPT.rows_of("retro_per_2015.json")}

    # ── 1社ずつ: companyfacts を1回読み、全ビンテージの PER・特徴量を組む ───────
    z = zipfile.ZipFile(os.path.join(ROOT, "companyfacts.zip"))
    have = set(z.namelist())
    per_new = {y: {} for y in ALL_V}
    fea_new = {y: {} for y in ALL_V}
    per_meta = {y: {} for y in ALL_V}
    ret15 = {}
    px_missing, facts_missing = [], []
    pxs = {}
    for i, t in enumerate(tick, 1):
        pxd = px_of(t)
        if not pxd or not pxd.get("close"):
            px_missing.append(t)
            pxd = None
        pxs[t] = pxd
        cik = t2cik.get(t)
        name = f"CIK{cik:010d}.json" if cik is not None else None
        if not name or name not in have:
            facts_missing.append(t)
            continue
        facts = json.loads(z.read(name)).get("facts", {})
        blk = per_block(facts, pxd, ALL_V)
        for y, rec in blk.items():
            per_meta[y][t] = rec
            if rec.get("per") is not None:
                per_new[y][t] = {"ticker": t, "px": rec["px"], "eps_fy": rec["eps_fy"],
                                 "fy_end": rec["fy_end"], "per": rec["per"]}
        g = facts.get("us-gaap", {})
        for y in ALL_V:
            fea_new[y][t] = RF.build_row(t, g, f"{y}-07-01")
        if pxd:
            r15 = ret_from_px(pxd, 2015)
            if r15:
                r15["ticker"] = t
                ret15[t] = r15
        if i % 100 == 0:
            print(f"  {i}/{len(tick)}  ({time.time()-t0:.0f}s)", flush=True)

    # ── 再現検査（新しい結果を見る前に器を確かめる）──────────────────────────
    val = {}
    val["repro_2018"] = repro_2018(names)
    val["repro_2013_rawPER"] = repro_raw("2013", "retro_per_2013_all.json", "retro_returns_2013_all.json", "2013")
    val["repro_2015_rawPER"] = repro_raw("2015", "retro_per_2015.json", "retro_returns_2015.json", "2015")

    def px_agree(y, inv):
        d, big = [], []
        for t, r in inv.items():
            m = per_meta[y].get(t) or {}
            if m.get("px_raw") is None:
                continue
            rel = m["px_raw"] / r["px"] - 1 if r["px"] else None
            if rel is None:
                continue
            d.append(abs(rel))
            if abs(rel) > 0.02:
                big.append((t, r["px"], round(m["px_raw"], 2)))
        pe = [abs(per_new[y][t]["per"] / r["per"] - 1) for t, r in inv.items() if t in per_new[y]]
        return {"n_compared": len(d), "median_abs_rel": round(statistics.median(d), 5) if d else None,
                "share_within_1pct": round(sum(1 for x in d if x <= 0.01) / len(d), 4) if d else None,
                "px_off_gt2pct": big[:25], "n_px_off_gt2pct": len(big),
                "per_share_within_1pct": round(sum(1 for x in pe if x <= 0.01) / len(pe), 4) if pe else None,
                "n_per_inv": len(inv), "n_per_mine": len(per_new[y]),
                "only_in_inv": sorted(set(inv) - set(per_new[y]))[:25],
                "only_in_mine": sorted(set(per_new[y]) - set(inv))[:25]}
    val["px_vs_inventory_2013"] = px_agree(2013, per_inv[2013])
    val["px_vs_inventory_2018"] = px_agree(2018, per_inv[2018])
    val["px_vs_inventory_2015_sample"] = px_agree(2015, per15_old)

    def fea_agree(y, inv):
        keys = ("opm", "fcfpos5", "cagr5", "payout5")
        n, diff = 0, []
        for t, r in inv.items():
            m = fea_new[y].get(t)
            if m is None:
                continue
            n += 1
            for k in keys:
                if r.get(k) != m.get(k):
                    diff.append((t, k, r.get(k), m.get(k)))
        return {"n_compared": n, "n_field_diffs": len(diff), "diffs": diff[:20]}
    val["features_rebuilt_vs_inventory"] = {str(y): fea_agree(y, fea_inv[y]) for y in FEA_SRC}
    val["features_rebuilt_vs_inventory"]["2015_subset506"] = fea_agree(2015, fea15_old)

    def ret_agree(y, inv, mine_fn):
        d = []
        for t, r in inv.items():
            m = mine_fn(t)
            if not m or m.get("tr_cagr") is None or r.get("tr_cagr") is None:
                continue
            d.append(abs(m["tr_cagr"] - r["tr_cagr"]) * 100)
        return {"n": len(d), "median_abs_pt": round(statistics.median(d), 3) if d else None,
                "share_within_1pt": round(sum(1 for x in d if x <= 1) / len(d), 4) if d else None,
                "max_abs_pt": round(max(d), 2) if d else None}
    val["returns_monthkey_vs_inventory"] = {
        "2015_q_overlap": ret_agree(2015, ret15_old, lambda t: ret15.get(t)),
        "2016": ret_agree(2016, ret_inv[2016], lambda t: ret_from_px(pxs.get(t), 2016)),
        "2018": ret_agree(2018, ret_inv[2018], lambda t: ret_from_px(pxs.get(t), 2018)),
        "note": "2015 は月キー方式・終点 2026-08 の足。既存在庫は 2026-08-04（timestamp 方式）なので端点の差だけずれる",
    }
    val["px_missing"] = px_missing
    val["facts_missing"] = facts_missing
    # Yahoo の系列が 2013-07 より後から始まる社（新しく算出するビンテージでは7月の足が無い年は PER を作らない）。
    # 2026-09-23 の実測: BBBY/EA/EQR/HLX/ISSC/LEG/QVCAQ/SALM は Yahoo が 2026-07 以降しか返さない
    # （過去の範囲を頼むと HTTP 400＝歴史が付け替えられた）。既存在庫（2026-08 取得）には全履歴があるので
    # 2013/2018 の PER とすべての実現リターンは無事だが、本器が算出するビンテージからは落ちる
    starts = []
    for t in tick:
        ks = sorted(((pxs.get(t) or {}).get("close")) or {})
        if ks and ks[0] > "2013-07":
            starts.append({"t": t, "name": names.get(t, ""), "first": ks[0], "last": ks[-1],
                           "stub_since_2026": ks[0] >= "2026-01"})
    val["px_series_start_after_2013_07"] = starts
    print("■ 再現検査:", json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items()
                                                                          if not isinstance(vv, list)})
                                    for k, v in val.items() if k.startswith("repro")}, ensure_ascii=False))

    # ── ビンテージごとの PER・特徴量・リターン（在庫があるものは在庫）──────────
    PERM = {y: (per_inv[y] if y in per_inv else per_new[y]) for y in ALL_V}
    FEA = {y: (fea_inv[y] if fea_inv.get(y) is not None else fea_new[y]) for y in ALL_V}
    RET = {y: (ret_inv[y] if y in ret_inv else ret15) for y in ALL_V}
    FLAGS = {}
    for y in ALL_V:
        fy = {}
        cutoff = dt.date(y, 3, 1)
        for t in tick:
            m = per_meta[y].get(t) or {}
            p = PERM[y].get(t)
            if not p:
                continue
            ni_end = p.get("fy_end") or m.get("ni_end")
            try:
                lag = (cutoff - dt.date.fromisoformat(ni_end)).days
            except Exception:
                lag = None
            stale = (lag is not None and lag > STALE_D) or (m.get("sh_end") not in (None, ni_end))
            sg = split_gap(pxs.get(t), m.get("sh_filed"), y)
            fy[t] = {"stale_eps": stale, "split_gap": (sg is not None and abs(sg - 1.0) > 1e-9),
                     "lag": lag, "gap": sg}
        FLAGS[y] = fy

    POPS, POPS_B, GUARD, COVER = {}, {}, {}, {}
    for y in ALL_V:
        modal = modal_years(RET[y])
        rows, exc = build_pop(y, PERM[y], FEA[y], RET[y], FLAGS[y], modal)
        rows_b, _ = build_pop(y, PERM[y], FEA[y], RET[y], FLAGS[y], modal, require_payout=False)
        POPS[y] = {"full": rows, "quality": [r for r in rows if r["q"]]}
        POPS_B[y] = {"full": rows_b, "quality": [r for r in rows_b if r["q"]]}
        GUARD[y] = [dict(e, name=names.get(e["t"], "")) for e in exc]
        COVER[y] = {"horizon_years_modal": modal,
                    "per_source": PER_SRC.get(y, "本器が算出（retro_per_asof の関数・fetch_px の月足）"),
                    "features_source": FEA_SRC.get(y, "本器が retro_features2.build_row で956社を組み直し"),
                    "returns_source": RET_SRC.get(y, "本器（fetch_px の adjclose・月キー方式・2015-07→2026-08）"),
                    "n_universe": len(tick), "n_per": len([t for t in tick if t in PERM[y]]),
                    "n_cagr5": sum(1 for t in tick if (FEA[y].get(t) or {}).get("cagr5") is not None),
                    "n_payout5": sum(1 for t in tick if (FEA[y].get(t) or {}).get("payout5") is not None),
                    "n_returns": sum(1 for t in tick if (RET[y].get(t) or {}).get("tr_cagr") is not None),
                    "n_guard_excluded": len(exc), "n_popA": len(rows), "n_quality": len(POPS[y]["quality"]),
                    "n_popB": len(rows_b), "n_qualityB": len(POPS_B[y]["quality"]),
                    "n_stale_eps_in_popA": sum(1 for r in rows if r["stale_eps"]),
                    "n_split_gap_in_popA": sum(1 for r in rows if r["split_gap"])}

    # ── セル・自己検査 ────────────────────────────────────────────────────
    CELLRES, SELF, GRIDRES = {}, [], {}
    for y in ALL_V:
        CELLRES[y] = {}
        for cname, (pool_name, th) in CELLS.items():
            pool = POPS[y][pool_name]
            c = cell(pool, th, names)
            if pool_name == "quality":
                c["passed_impaired"] = sorted(
                    (dict(t=r["t"], name=names.get(r["t"], ""), per=r["per"], ratio=round(r["ratio"], 2),
                          real=r["real"]) for r in pool if r["ratio"] <= th and r["real"] <= IMPAIR),
                    key=lambda x: x["real"])
            CELLRES[y][cname] = c
            if not selfcheck_cut(pool, th, c):
                SELF.append((y, cname))
        GRIDRES[y] = {pn: [{k: v for k, v in cell(POPS[y][pn], th, names, listing=False).items()
                            if k in ("th", "blocked", "passed", "thin", "imp_up", "med_down", "verdict")}
                           for th in GRID] for pn in ("quality", "full")}
    val["selfcheck_vs_retro_price_tail_cut"] = {"mismatch": SELF, "ok": not SELF}

    # ── 判定（事前登録どおり）──────────────────────────────────────────────
    CRIT = {c: judge(CELLRES, c, COUNTED, K_MIN) for c in CELLS}

    def variant(filter_fn=None, pops=None, vintages=COUNTED, k_min=K_MIN):
        pops = pops or POPS
        cr = {}
        for y in vintages:
            cr[y] = {}
            for cname, (pool_name, th) in CELLS.items():
                pool = [r for r in pops[y][pool_name] if (filter_fn is None or filter_fn(r))]
                cr[y][cname] = cell(pool, th, names)
        return {c: judge(cr, c, vintages, k_min) for c in CELLS}, cr

    ROB = {}
    ROB["S1_stale_eps"], _ = variant(lambda r: not r["stale_eps"])
    ROB["S2_split_gap"], _ = variant(lambda r: not r["split_gap"])
    ROB["B_population"], crB = variant(pops=POPS_B)
    ROB["S3_with_2022"], _ = variant(vintages=COUNTED + SENS_ONLY, k_min=math.ceil(8 * K_MIN / 7))
    ROB["incl_2018_2013to2021"], _ = variant(vintages=tuple(sorted(COUNTED + DISCOVERY)),
                                           k_min=math.ceil(8 * K_MIN / 7))
    robust = all(ROB[k][PRIMARY]["P_tail"] == CRIT[PRIMARY]["P_tail"]
                 for k in ("S1_stale_eps", "S2_split_gap", "B_population"))
    POOL = {c: pooled(POPS, c, COUNTED, names) for c in CELLS}

    # ── 事後の観察（post_hoc_rule: 結果を見た後に足した。判定には混ぜない）──────────
    POST = {"rule": PREREG["post_hoc_rule"]}
    POST["stale_eps_in_extreme_tail"] = {}
    for y in ALL_V:
        qb = [r for r in POPS[y]["quality"] if r["ratio"] > 4.0]
        POST["stale_eps_in_extreme_tail"][str(y)] = {
            "Q>4_blocked": len(qb), "stale_eps": sum(1 for r in qb if r["stale_eps"]),
            "stale_names": [r["t"] for r in qb if r["stale_eps"]],
            "popA_stale_share": round(sum(1 for r in POPS[y]["full"] if r["stale_eps"]) / max(len(POPS[y]["full"]), 1), 3)}
    # 7月の足が無くて本器が PER を作れなかった社のうち、質実証プール∧恒久毀損のもの
    # （Q>4 の分子を増やしうるのはこれだけ）。独立の目安として hist_val の TTM PE を添える（在るビンテージのみ）
    POST["unpriced_quality_impaired"] = {}
    for y in ALL_V:
        if y in PER_SRC:
            continue
        hv = {}
        hp = os.path.join(OUT, f"hist_val_{y}.json")
        if os.path.exists(hp):
            hv = {r["ticker"]: r for r in json.load(open(hp, encoding="utf-8"))["rows"]}
        lst = []
        for t in tick:
            m = per_meta[y].get(t) or {}
            if m.get("px_raw") is not None:
                continue
            f, rr = FEA[y].get(t) or {}, RET[y].get(t) or {}
            q = (f.get("opm") or 0) >= 0.10 and (f.get("fcfpos5") or 0) >= 5
            tr = rr.get("tr_cagr")
            if q and tr is not None and tr * 100 <= IMPAIR:
                lst.append({"t": t, "name": names.get(t, ""), "real": round(tr * 100, 2),
                            "hist_val_pe_ttm": (hv.get(t) or {}).get("pe")})
        POST["unpriced_quality_impaired"][str(y)] = lst
    POST["median_Q>4_by_vintage"] = {
        str(y): {"horizon": COVER[y]["horizon_years_modal"],
                 "blocked_med": (CELLRES[y]["Q>4"]["blocked"] or {}).get("med"),
                 "passed_med": (CELLRES[y]["Q>4"]["passed"] or {}).get("med"),
                 "blocked_n": (CELLRES[y]["Q>4"]["blocked"] or {}).get("n", 0)} for y in ALL_V}

    head = CRIT[PRIMARY]
    verdict = {
        "primary_cell": PRIMARY,
        "P_tail": head["P_tail"], "P_breaker": head["P_breaker"],
        "support": f"{len(head['support'])}/{len(COUNTED)}（thinでない {len(head['nonthin'])}）",
        "numerator_distinct_in_support": head["numerator_distinct_in_support"],
        "robust_S1_S2_B": robust,
        "by_cell": {c: {"P_tail": CRIT[c]["P_tail"], "P_breaker": CRIT[c]["P_breaker"],
                        "support": len(CRIT[c]["support"]), "nonthin": len(CRIT[c]["nonthin"]),
                        "numerator_distinct": len(CRIT[c]["numerator_distinct_in_support"])} for c in CELLS},
    }

    # ── 書き出し（事前登録の塊は触らない）───────────────────────────────────
    cur["generated"] = dt.date.today().isoformat()
    cur["results_written_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cur["prereg_sha256_verified"] = h
    cur["note"] = ("事前登録（preregistered）→再現検査（validation）→判定（verdict）。"
                   "新しく算出した PER・2015 の特徴量とリターンはファイルに書かず rows に同梱")
    cur["validation"] = val
    cur["coverage"] = {str(y): COVER[y] for y in ALL_V}
    cur["guard_excluded"] = {str(y): GUARD[y] for y in ALL_V}
    cur["results"] = {
        "per_vintage": {str(y): {"role": ("counted" if y in COUNTED else "discovery" if y in DISCOVERY
                                          else "sensitivity_only"),
                                 "cells": CELLRES[y]} for y in ALL_V},
        "criteria": CRIT,
        "robustness": ROB,
        "pooled_counted_descriptive": POOL,
        "grid_descriptive": {str(y): GRIDRES[y] for y in ALL_V},
    }
    cur["verdict"] = verdict
    cur["post_hoc_not_in_verdict"] = POST
    cur["reading_2026_09_23"] = READING_20260923
    cur["rows"] = {"columns": ["ticker", "per", "g", "ratio", "real", "quality", "stale_eps", "split_gap"],
                   "popA": {str(y): compact(POPS[y]["full"]) for y in ALL_V},
                   "popB_only": {str(y): compact([r for r in POPS_B[y]["full"]
                                                  if r["t"] not in {x["t"] for x in POPS[y]["full"]}])
                                 for y in ALL_V}}
    write_dest(cur)

    # ── 画面 ─────────────────────────────────────────────────────────────
    print(f"\n■ {DEST} を書いた（{time.time()-t0:.0f}s）")
    print("  自己検査（retro_price_tail.cut との一致）:", "OK" if not SELF else SELF)
    print(f"\n  {'年':<5}{'窓':>6}{'母A':>5}{'質':>5} | " + " | ".join(f"{c:^30}" for c in CELLS))
    for y in ALL_V:
        cells = []
        for c in CELLS:
            x = CELLRES[y][c]
            b = x["blocked"] or {}
            base = x["base"] or {}
            tag = "薄" if x["thin"] else ("◎" if x["imp_up"] and x["med_down"] else "△" if x["imp_up"] else "×")
            cells.append(f"{tag} 止{b.get('n', 0):>3} 毀{x['n_blocked_impaired']:>2}社 "
                         f"{(b.get('impair') or 0):.1%}/{(base.get('impair') or 0):.1%} "
                         f"中{b.get('med', float('nan')):>5}/{(x['passed'] or {}).get('med', float('nan'))}")
        role = "" if y in COUNTED else ("(発見)" if y in DISCOVERY else "(感度)")
        print(f"  {y}{role:<5}{COVER[y]['horizon_years_modal']:>5} {len(POPS[y]['full']):>4} "
              f"{len(POPS[y]['quality']):>4} | " + " | ".join(cells))
    print("\n■ 判定（事前登録: support≥5/7 ∧ 分子≥5社）")
    for c in CELLS:
        x = CRIT[c]
        print(f"  {c}: P_tail={x['P_tail']} / P_breaker={x['P_breaker']}  支持 {x['support']}  "
              f"thinでない {x['nonthin']}  分子 {x['numerator_distinct_in_support']}")
    print(f"  頑健性（Q>4 の P_tail が S1/S2/B で不変）: {robust}  "
          + "  ".join(f"{k}={ROB[k][PRIMARY]['P_tail']}" for k in ROB))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--cache", default=None, help="hist_valuation のキャッシュの置き場（既定 out/_histval_cache）")
    a = ap.parse_args()
    if a.prereg:
        return cmd_prereg()
    if a.fetch:
        return cmd_fetch(a.cache)
    if a.run:
        return cmd_run(a.cache)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
