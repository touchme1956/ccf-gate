#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_events.py — 監視リストの 8-K / 6-K を日次で見張るイベント駆動監視（2026-08-04新設・提案4／6-K本文走査 2026-09-23）

なぜ要るか:
  四半期点検(kessan_check.py)は3ヶ月に1回しか回らず、その間の減損・経営者退任・
  過年度訂正は誰も見ていなかった。KLACの$230.4百万のれん減損を「監視リストにいたのに
  見逃しかけた」型の事故は、この四半期の隙間で起きる。8-K は SEC がイベント発生から
  原則4営業日以内の提出を義務づける一次情報なので、これを毎日なめれば隙間が塞がる。

何をするか:
  kanshi_list.json（list ∪ pin）の米国上場銘柄について SEC submissions API の直近提出を読み、
  8-K は Item 番号で、6-K は本文の警報語で警報を立てる。判定には一切使わない——ヒットは門2再審査（依頼文）へ
  回すための「気づき」であり、株価は見ない（kessan_check と同じ思想）。

警報にする Item（門の6警報語との対応）:
  1.03 破産・管財         → 誠(存続)
  2.06 重要な減損         → 減損
  3.01 上場廃止通知       → 誠
  4.02 過年度財務の非依拠  → 誠(会計)
  5.02 役員・取締役の退任  → 退任
  ※ 2.02(決算発表)は四半期点検の領分なので警報にしない（毎四半期鳴る警報は鳴らないのと同じ）

外国私募発行体の 6-K（2026-09-23 作り直し・todo sixk_watch「保有ASMLが死角」）:
  20-F/40-F を出す社（ASML=保有・SAP・RELX・RACE・TSM …）は 8-K を一本も出さず、重要事象も決算も 6-K で出す。
  6-K には Item 番号が無いので **提出一覧＋本文の警報語走査**（kessan_check_jp 型）で見る:
    ① submissions の 6-K を窓で拾う（20-F/40-F 提出体かは submissions の最新の年次報告の様式で判定——列挙しない）
    ② 提出の索引(-index.htm)を読み、主文書と EX-99.x を取る（6-K の主文書はたいてい表紙で、中身は添付）
    ③ 警報語は kessan_check.ALERTS（四半期点検の6砲台）と下の FPI_ALERT（8-K Item 相当の事象語）。
       門番は kessan_check._is_real（否定・定型・仮定法・金額）をそのまま通す＝二重実装を作らない
    ④ 見出しで決算・報告（8-K 2.02 相当）を見分けて earnings へ
  **読めなかった 6-K は errors（監視の穴）へ**——「警報なし」には数えない。取得は1回 --max-6k-docs まで
  （索引＋文書の数・既定120）で、上限で読めなかった分も穴として名指しする（黙って切らない）。

日本株（2026-08-04追加）: 環境変数 EDINET_API_KEY があれば EDINET API v2 の日付別提出一覧を走査し、
  **臨時報告書**（8-Kの相当物＝役員異動・重要事象）と**訂正報告書**を警報に、
  有報・四半期・半期報告書の新規提出を「決算・報告イベント」に立てる。
  鍵が無ければ対象外＝穴のまま。出力にその旨を明示する——
  黙って対象外にすると「監視されている」顔をする（kessan_check の偽健全と同型の事故になる）。
  鍵は https://api.edinet-fsa.go.jp/ で無料登録し、GitHub Secrets の EDINET_API_KEY に置く。

使い方:
  python3 night/watch_events.py                    直近7日窓（日次CI用。休日またぎを吸収）
  python3 night/watch_events.py --days 30          窓を広げる（初回・停止後の追いつき）
  python3 night/watch_events.py --max-6k-docs 200  6-K の取得上限（索引＋文書の数・既定120/回）
  python3 night/watch_events.py --only TSM,ASML --days 30 --out /tmp/x.json
                                                   試験用。監視リスト外の銘柄も可。**正本 out/events_watch.json は書き換えない**
出力: out/events_watch.json（ヒット・対象外・取得失敗を全部書く。失敗を「異常なし」と書かない）
"""
import html
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL = "fortis5280@gmail.com"
HDRS  = {"User-Agent": f"hachimon-gate research {EMAIL}"}
OUT   = os.path.join(BASE, "out", "events_watch.json")
SEC   = "https://www.sec.gov"

# 6-K の警報語と門番の単一実装は四半期点検 kessan_check.py（v9.9.65の掟: 二重実装を作らない）。
#   読めなければ 6-K の本文走査を止め、**全件を監視の穴として書く**（黙って「警報なし」にしない）。
sys.path.insert(0, BASE)
try:
    import kessan_check as kc
    KC_ERR = None
except Exception as _e:  # noqa: BLE001 — 何が起きても 8-K の監視は止めない
    kc, KC_ERR = None, f"{type(_e).__name__}: {str(_e)[:120]}"

# Item番号 → 門の警報語（ここに無いItemは記録するが警報にしない）
ALERT_ITEMS = {
    "1.03": "誠(存続)——破産・管財",
    "2.06": "減損——重要な資産の減損",
    "3.01": "誠——上場維持基準の不適合通知",
    "4.02": "誠(会計)——過年度財務諸表の非依拠(non-reliance)",
    # ★2026-08-20新設。**理由も書かずに抜けていた**——2.02 は「四半期点検の領分だから警報にしない」と
    #   明示的に外してあるのに、4.01 はどこにも書かれていなかった＝意図的な除外ではなく取りこぼし。
    #   実害を踏んで足している: **RMD（保有銘柄）の 2026-08-17 の 8-K は items=[4.01,5.02,7.01,9.01]** で、
    #   **32年つづいた監査人 KPMG を解任して PwC へ替えた**のに、警報に立ったのは 5.02（取締役の退任）だけだった。
    #   ⇒ 監査人の交代という、この日いちばん重い事実が**警報の言葉に一度も現れなかった**。
    #   【重さは本文で分かれる】8-K は Reg S-K 304 により **disagreement と reportable event の有無を
    #   必ず述べる義務がある**ので、原本を開けば機械的に読み分けられる——
    #     ・disagreement あり／reportable event あり → **極めて重い**（門の「誠」そのもの）
    #     ・どちらも無し → 通常のローテーション（RMD がこれ。意見は無限定・競争入札の結果・後任は Big4）
    #   だからここでは**警報に立てるが断定はしない**。言葉に「有無を原本で確かめよ」と書いて人を原本へ送る
    #   （FPI_ALERT が「語で拾うのは項目番号より弱いので警報の言葉も弱くする」と同じ作法）。
    #   【鳴りすぎないことを先に測った】直近の窓で 4.01 は **1件だけ**（RMD）＝
    #   「鳴りすぎる警報は鳴らないのと同じ」には当たらない。
    "4.01": "監査人の交代——**disagreement / reportable event の有無を原本(Item 4.01(a))で確かめよ**。無ければ通常のローテーション、有れば誠(会計)",
    "5.02": "退任——取締役・主要役員の異動",
}

# ── 外国私募発行体(FPI)の 6-K（2026-08-10新設 → 2026-09-23 本文走査を作り直し）──────────────
# 【なぜ要るか】この道具は `if f not in ("8-K","8-K/A"): continue` で 8-K だけを見ていた。
#   ところが **20-F を出す外国私募発行体は 8-K を一本も出さない**——重要事象は 6-K で出す。
#   実測: ASML（**🟢投下可**）/ SAP / RELX / RACE / AZN / BUD / NVO / GSK / INFY / TSM …
#   彼らは監視リストに載っているのに **原理的にイベントが立たない**のに、
#   日本株の not_covered_jp と違って**穴の明示すら無く** `checked_us=38 / errors=0` と出る
#   ＝**「監視した」顔をする**。ルール7の親戚（欠測を健全と読むな）。
#
# 【どう扱うか】6-K には Item 番号が無いので ALERT_ITEMS を当てられない。
#   代わりに **8-K の Item が意味しているのと同じ事象を語で拾う**。
#   語で拾うのは項目番号より弱いので、**警報の言葉も弱くする**（"6-K語ヒット"）——
#   強さを偽らないのがこの台帳の作法。ヒットしない 6-K も件数として必ず出す
#   （「見ていない」と「見て何も無い」を区別する）。
#
# 【2026-09-23 に直した初版の穴】(todo sixk_watch)
#   ・本文の取得に失敗しても txt="" のまま others へ入れていた＝**取得失敗が「警報なし」に化けていた**
#     （errors にも書いてはいたが、行そのものは「見て何も無い」と同じ顔で残った）→ 失敗は errors だけへ
#   ・索引の「大きい順2件」を読んでいた——最大はたいてい**提出全体の .txt**（全文書の連結）で、
#     しかも 800KB で黙って切っていた（実測 RACE 半期報告 1.77MB）→ 主文書＋EX-99.x を種別で選び、切ったら穴と書く
#   ・実体参照を復号していなかった——EDGAR は語の間を &#160; で繋ぐので『has&#160;resigned』が語をすり抜ける
#   ・決算・報告の 6-K を earnings に入れていなかった（8-K の 2.02 に当たるものが画面に出なかった）
FPI_FORMS = ("6-K", "6-K/A")
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
MAX_6K_FETCH = 120            # 1回の実行で 6-K に使う取得の上限（索引＋文書）。既定の7日窓は実測で10〜40
MAX_EX_PER_FILING = 12        # 1提出の添付の上限（RELX は1か月分の RNS を EX-99.1〜99.7 に束ねて出す）
MAX_DOC_BYTES = 16_000_000    # 1文書の上限。超えたら切って穴と書く。実測の最大級: SAP の統合報告書(毎年3月) 8.6〜9.7MB
                              #   （平文にすると約1MB・走査1秒未満）／TSM の四半期財務諸表 4.8MB
#
# ⚠**語は締めてある。** 初版は `\bimpairment\b` や `\bresign\w*` の素の語で拾ったところ、
#   ASML・RELX・SAP の**半期報告が全部鳴った**——IFRSの中間財務諸表は会計方針として
#   「impairment of financial assets」を必ず書き、ガバナンス節は必ず「resignation」に触れる。
#   **鳴りすぎる警報は鳴らないのと同じ**なので、
#   「**事象が起きた**」と読める言い回し（金額・実行済みの動詞）だけを拾う形へ締めた。
# 2026-09-23: 門の警報語へ束ねるため (語, 分類, 表示) の三つ組にした。語そのものは変えていない。
#   分類は kessan_check.ALERTS と同じ名前（誠/減損/退任/指針）＋8-K にしか無い2つ（存続/上場）。
FPI_ALERT = [
    (r"impairment (?:charge|loss(?:es)?) of\b|recognis?ed an impairment|"
     r"goodwill impairment (?:charge|loss)|wrote (?:down|off)\b|"
     r"impairment (?:charge|loss)[^.]{0,60}?(?:million|billion|€|\$|£)",
     "減損", "減損——8-K Item 2.06 相当"),
    (r"non[- ]reliance|should no longer be relied upon|"
     r"restatement of (?:our |the |its )?(?:previously issued |prior )?(?:consolidated )?financial|"
     r"material weakness in (?:our |the )?internal control", "誠", "誠(会計)——同 4.02 相当"),
    # 2026-09-23: 『(will|to) retire (from|as|on|at|effective)』を足した。**保有ASML自身の直近の社長交代を拾えなかった**——
    #   2023-11-30 の 6-K は『Co-Presidents Peter Wennink and Martin van den Brink to retire on April 24, 2024』
    #   『will retire from ASML』で、resign/step down を一度も使わない（8-K 5.02 は定年・任期満了の退任も含む）。
    #   前置詞で人の退任に限った（『will retire the notes / shares』＝社債償還・自社株消却は拾わない）。
    #   英国式の定例『all Directors will retire at the AGM and offer themselves for re-appointment』（実測 DEO 年次報告）は除く。
    (r"has (?:resigned|stepped down)|will (?:resign|step down)|"
     r"(?:will|to) retire (?:from|as|on|at|effective)\b(?![^.]{0,80}(?:re-?elect|re-?appoint|offer (?:themselves|himself|herself)|by rotation))|"
     r"resignation of (?:the |our |mr|ms|dr)|(?:ceo|cfo|chief executive|chief financial officer)"
     r"[^.]{0,60}?(?:to step down|will leave|departure)", "退任", "退任——同 5.02 相当"),
    (r"\bfiled for bankruptcy|chapter 11|insolvency proceedings|"
     r"\bplaced into (?:administration|receivership)", "存続", "誠(存続)——同 1.03 相当"),
    (r"notice of (?:non[- ]?compliance|delisting)|"
     r"listing (?:standard|rule)s?[^.]{0,40}?(?:non[- ]?compliance|deficien)", "上場", "誠——同 3.01 相当"),
    # 2026-09-23: 現在形（cuts/lowers/reduces/withdraws）を足した。欧州の発表は見出しが現在形——
    #   実測 NVO 2025-07-29『Novo Nordisk lowers sales and operating profit outlook for 2025』を過去形だけでは拾えなかった。
    #   動詞の前後に \b を置いた（旧版は『execute … guidance』の cut でも当たりえた）。
    #   『profit warning』は単数に限った（実測 SAP 2019 統合報告書『the increasing number of profit warnings including
    #   from some large DAX enterprises』＝他社についての市況の記述）。
    (r"\bprofit warning\b|\b(?:cuts?|lower(?:s|ed)|reduce[sd]|withdr(?:ew|awn|aws))\b[^.]{0,40}?(?:guidance|outlook)|"
     r"guidance[^.]{0,30}?(?:cut|lowered|reduced|withdrawn)",
     "指針", "業績下方——8-Kに対応項目は無いが門2再審査の気づき"),
]
SIXK_LABEL = {lab_cat: lab for _p, lab_cat, lab in FPI_ALERT}   # 分類 → 旗の言葉（kessan_check の語も同じ言葉で出す）
SIXK_ORDER = ("存続", "誠", "上場", "減損", "退任", "指針")      # 旗の並び（重い順）
# 限(独占・特許の期限)/集(顧客・調達の集中)は**毎期再掲される常設の開示**＝6-K では記録のみで警報にしない。
#   kessan_check 自身も集は「前回点検に無かった新規出現」だけを警報化している（28社中12社が鳴る型の再演を避ける）。
#   実測(2026-09-23): ASML 半期報告『single-source key components』・TSM 財務諸表『ten largest customers accounted for 84%』
#   ＝どちらも毎期同じ文。吉報(吉S字/吉流通)は警報ではないのでこの層では見ない。
SIXK_REF = ("限", "集")
# 金額の門番の補い: kessan_check.AMOUNT は「$ / million / billion / %」だけなので、FPI の書き方
#   （€1.3bn・£45m・NT$1,234・EUR 200 million）で本物の減損を「金額が近傍に無い」と落とす。
#   → _is_real が**金額だけを理由に**落としたときに限り、通貨記号・略記で拾い直す（他の理由の却下は覆さない）
AMOUNT_FX = re.compile(
    r"(?:€|£|¥|₩|₹|(?:US|NT|A|C|HK|R|S)\$|\b(?:EUR|GBP|USD|JPY|CHF|DKK|SEK|NOK|TWD|KRW|INR|CNY|RMB|AUD|CAD|BRL|HKD|SGD)\b)\s?\d"
    r"|\b\d[\d,.]*\s?(?:bn|mn)\b", re.I)
# 表の行の門番: 財務諸表の明細（『Less: Allowance for impairment loss (182,532) (134,187)…』
#   『Impairment losses - - 1,670,522 - - 1,670,522』＝実測 TSM 2026Q2 財務諸表）は**毎期の行項目**で、
#   起きた事象の記述ではない。重い事象は必ず文章で説明されるので、数字が密に並ぶ窓の中の語は落とす。
NUMTOK = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 6-K の門番の補い（_is_real の後に掛ける）。2026-09-23 に**監視外の大型FPI 16社の定例 6-K 132件**へ掛けて出た空振りから:
#   誠  : kessan_check の素の『restatement』が**会計基準の適用・超インフレ会計(IAS 29)の比較修正**に当たる
#         （実測 SNY『applied IAS 29. The impact of the resulting restatements is immaterial』／BUD『restatement of
#         non-monetary assets under hyperinflation accounting』）。2027年の IFRS 18 適用で欧州勢の中間報告が一斉に鳴る型。
#         ⚠素の restatement にだけ掛け、近くに error / misstatement があれば落とさない（誤りの訂正こそ本物）
#   存続: 『insolvency proceedings』が**否定・条項の中**に出る（実測 DEO『the absence of insolvency proceedings』）
#   指針: 『the lower end of the guidance assumes…』＝幅の端の説明（実測 INFY）。語そのものにだけ掛ける
#         （『lowered … to the lower end of the range』のような本物の下方修正を近傍の語で落とさないため）
SIXK_NOT_CTX = {
    "誠": re.compile(r"\bIAS\s?\d+|\bIFRS\s?\d+|\bASC\s?\d+|hyperinflation|non-monetary|new accounting (?:standard|pronouncement)|"
                    r"adoption of|changes? in accounting polic|reclassif", re.I),
    "存続": re.compile(r"absence of|in the event of|event of default|bail-?in|subordinat|noteholders|holders of the notes|"
                      r"liquidation, administration or", re.I),
    #   減損: IFRS 9 の**金融資産の貸倒引当(ECL)**と、行項目名の一部（『(including impairment losses)』）は毎期の定型
    #         （実測 BUD『The allowance for impairment recognized during the period on trade and other receivables』・
    #         『Business and asset disposal (including impairment losses) 61 (47)』。上の FPI_ALERT の注記が言う
    #         「impairment of financial assets を必ず書く」型）。本物の減損を巻き込まないよう窓は ±120字に狭める
    "減損": re.compile(r"receivables|financial assets|expected credit loss|credit losses|"
                      r"allowance for (?:impairment|doubtful|expected)|\(incl(?:uding|\.)? impairment", re.I),
}
SIXK_NOT_WIN = {"誠": 200, "存続": 200, "減損": 120}
SIXK_NOT_MATCH = {"指針": re.compile(r"\b(?:lower|upper|low|high|top|bottom) end of\b", re.I)}
ERRORISH = re.compile(r"\berrors?\b|misstat", re.I)
#   誠: 監査委員会の**職務の列挙**に出る『material weakness』（実測 ASML 2018 年次報告『Any material weaknesses and / or
#       deficiencies (if applicable) in design and operation of…』）。素の material weakness にだけ掛ける
DUTYISH = re.compile(r"\bany material weakness|\bif applicable\b|responsib|\boversee|\breview(?:s|ing)?\b|\bdiscuss(?:es|ing)?\b", re.I)
#   減損: 戻入れは利益側（実測 TSM 2019『recognized a reversal of impairment loss of NT$301,384 thousand』）。直前の語だけで見る
#       （NVO『…impairment reversal in Q2 2025 as well as non-cash impairment charges of DKK 6.3 billion』の本物を巻き込まない）
REVERSAL = re.compile(r"revers(?:al|ed|e)\s+(?:of\s+)?(?:an?\s+|the\s+)?$", re.I)
#   減損: 何年も前の減損への言及が毎期の報告に再掲される（実測 BUD『a 1.1 billion US dollar non-cash impairment charge …
#         as of 30 June 2022』を 2026年の中間報告が繰り返す）。kessan_check_jp の『前期の事象への言及』の英語版として、
#         近傍の年が**すべて提出年の2年以上前**なら落とす（年の書いていない文は落とさない）
YEAR = re.compile(r"\b(?:19|20)\d\d\b")
# 募集書類（引受契約 EX-1・社債の条件 EX-4・法律意見 EX-5/8・同意 EX-23・委任 EX-24・T-1 EX-25）と XBRL は事象の文書ではない。
#   実測 HSBC 2026-09-11 の EX-4.1（indenture の bail-in 条項）・SAN 2026-08-25 の EX-5.1（倒産法上の劣後の意見）が
#   『insolvency proceedings』で鳴った。EX-99 が無い 6-K の代わりの添付からだけ外す（走査しなかったことは行に書く）
OFFERING_EX = re.compile(r"EX-(?:1|4|5|8|23|24|25|101|104)(?:\.|$)")
TABLE_NUMS = 12               # ±150字の窓に数字が12個以上＝表の行（文章の段落は実測で多くても8前後）

# 決算・報告（8-K 2.02 相当）の見分け: 各文書の**見出し**（表紙・『Exhibit 99.1』等を除いた先頭）だけを見る。
#   本文の奥まで見ると、自社株買いの週報や配当の通知まで「results」「financial statements」で決算に化ける。
EARN = re.compile(
    r"\b(?:first|second|third|fourth|1st|2nd|3rd|4th|Q[1-4]|H[12]|half[- ]year(?:ly)?|interim|annual|full[- ]year|"
    r"preliminary|quarterly|fiscal|financial|20\d\d)\b[^.]{0,40}?\b(?:results|earnings)\b"
    r"|\b(?:results|earnings) (?:for|of) the (?:first|second|third|fourth|quarter|half|year|six|nine|three|twelve|fiscal|financial)"
    r"|\b(?:quarterly|interim|half[- ]year(?:ly)?|semi[- ]annual|annual|integrated)\s+(?:financial\s+)?(?:report|statement)s?\b"
    r"|\bfinancial statements\b|\brevenue report\b|\bmonthly (?:net )?(?:revenue|sales)\b|\btrading (?:update|statement)\b"
    r"|\breports?\b[^.]{0,80}?\b(?:net sales|revenues?|net income|net profit|EPS|earnings per share)\b"
    r"|\bearnings (?:release|report)\b", re.I)
#   『発表日の予告』『株主総会の結果』は決算そのものではない（実測 RACE 2026-07-15
#   『FERRARI TO ANNOUNCE SECOND QUARTER 2026 FINANCIAL RESULTS ON JULY 30』）
EARN_NOT = re.compile(r"\b(?:to|will) (?:announce|report|release|publish|present|host|hold)\b|\bconference call\b|"
                      r"\bwebcast\b|\bgeneral meeting\b|\b[AE]GM\b|\bnotice of\b|\bvoting\b", re.I)
#   見出しが決算の型に当たらなくても、先頭に業績の語が3種以上並べば決算の発表
#   （実測 RACE 2026-07-30『…STRONG RESULTS AND 2026 GUIDANCE RAISE • Net revenues… EBITDA… EPS…』）
FINTERM = re.compile(r"\bnet (?:revenues?|sales|income|profit)\b|\brevenues?\b|\bEBITDA\b|\bEBIT\b|"
                     r"\boperating (?:income|profit|margin)\b|\bgross margin\b|\bEPS\b|\bearnings per share\b|"
                     r"\bfree cash flow\b", re.I)


def _fetch(url, limit=None, timeout=60):
    """1回の取得。戻り (bytes, 切り詰めたか)。
    一時的な失敗（429/5xx/切断・時間切れ）は 2秒・6秒 待って2回まで取り直す（実測 2026-09-23 に SEC が 503 を返した）。
    ⚠ 取り直しても取れなければ**例外を上げる**——呼び手が『監視の穴』として書く（黙って空文字にしない）。"""
    last = None
    for wait in (0, 2, 6):
        if wait:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read(limit + 1) if limit else r.read()
            time.sleep(0.15)  # 礼儀(10req/s未満・hachimon_fetchと同じ)
            if limit and len(b) > limit:
                return b[:limit], True
            return b, False
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(0.15)
            if e.code not in (429, 500, 502, 503, 504):
                break          # 403/404 等は取り直しても同じ
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            last = e
            time.sleep(0.15)
    raise last


def get(url):
    return _fetch(url)[0].decode("utf-8", "ignore")


def kanshi_us():
    """監視リストの米国銘柄（4-5桁コード=日本株は対象外として別に返す）"""
    p = os.path.join(BASE, "kanshi_list.json")
    k = json.load(open(p, encoding="utf-8"))
    names = list(dict.fromkeys((k.get("list") or []) + (k.get("pin") or [])))
    us, jp = [], []
    for n in names:
        t = str(n).strip().split()[0]
        (jp if t[:1].isdigit() else us).append(t)
    return us, jp


def cik_map(tickers):
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    want = {t.upper() for t in tickers}
    m = {}
    for v in j.values():
        tk = v["ticker"].upper()
        if tk in want:
            m[tk] = str(v["cik_str"]).zfill(10)
    return m


# ── 6-K の本文走査 ─────────────────────────────────────────────────────────────
def _text(h):
    """HTML → 平文。kessan_check.strip_html（script/style/タグ）に、実体参照の復号と空白の正規化を足す。
    ⚠ EDGAR の HTML は語の間を &#160; や U+200B で繋ぐ（実測 RELX の表紙）——復号しないと語の正規表現をすり抜ける。"""
    h = kc.strip_html(h) if kc else re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    for z in ("\u200b", "\xa0", "\u2009", "\u202f"):
        h = h.replace(z, " ")
    return re.sub(r"\s+", " ", h).strip()


def filing_index(cik, acc):
    """提出の索引 {acc}-index.htm の文書表（Seq/Description/Document/Type/Size）→ [{name,type,url}]。
    submissions は主文書の名前しか持たず、添付(EX-99.x)の種別は索引にしか無い。"""
    a = acc.replace("-", "")
    ix = get(f"{SEC}/Archives/edgar/data/{int(cik)}/{a}/{acc}-index.htm")
    docs = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", ix):
        tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)
        m = re.search(r'href="([^"]+)"', tr)
        if len(tds) < 5 or not m:
            continue
        url = re.sub(r"^/ix\?doc=", "", m.group(1))       # インラインXBRLの閲覧器を経由するリンク
        if url.startswith("/"):
            url = SEC + url
        docs.append({"name": url.rsplit("/", 1)[-1], "type": _text(tds[3]).upper(), "url": url})
    if not docs:
        # 読めたのに表が空＝様式が変わった等。空の一覧を「添付なし」と読まない（ルール7）
        raise ValueError("索引に文書の表が見つからない")
    return docs


# 6-K 表紙の終わり（20-F/40-F の選択欄・旧様式の Rule 101(b)(7) / 12g3-2(b) 欄）と、その後ろのチェック記号
COVER_END = re.compile(r"Form\s*40-F|Rule\s*101\(b\)\(7\)|"
                       r"Rule\s*12g3-2\(b\)[^.]{0,120}?(?:1934|82-\s*_*|:\s*(?:n/?a|not applicable)\b)", re.I)
CHECKS = re.compile(r"(?:[\s☐☒⌧□■✓✔þ¨\[\]|_:()\-–—.,]|\b(?:x|o|yes|no|n/?a)\b)*", re.I)
COVER = re.compile(r"REPORT OF FOREIGN (?:PRIVATE )?ISSUER|\bFORM 6-K\b", re.I)   # 旧様式は PRIVATE が無い（BP）


def _head(t):
    """文書の見出し: 先頭の SGML の残り（『EX-99.1 2 file.htm』）と 6-K 表紙と
    『Exhibit 99.1』『Document』等の飾りを除いた本文の先頭。題の表示と決算・報告の見分けにだけ使う。
    表紙つきの主文書は2つの型がある——本文が**表紙の選択欄と署名の間**（NVO・BP）か、**署名の後**（TSM）。"""
    s = re.sub(r"^(?:6-K(?:/A)?|EX-[\d.]+)\s+\d+\s+\S+\s+", "", t)
    if COVER.search(s[:2500]):
        ends = [m.end() for m in COVER_END.finditer(s[:6000])]
        rest = s[ends[-1]:] if ends else ""
        rest = rest[CHECKS.match(rest).end():]
        if rest and not re.match(r"SIGNATURES?\b", rest, re.I):
            s = rest                                   # 選択欄の直後から本文
        else:
            sig = [m.end() for m in re.finditer(r"/\s?s/", s[:15000])]
            if sig:                                    # 署名欄（役職まで）の後ろから本文
                k = sig[-1]
                o = re.search(r"\b(?:Officer|Secretary|Director|Counsel)\b", s[k:k + 300])
                s = s[k + (o.end() if o else 0):]
    s = re.sub(r"^(?:\s*(?:6-K(?:/A)?|EX-[\d.]+|Document|EXHIBIT|Exhibit|No\.?|[\d.]+|[-–—•|:]+)(?=\s|$))+", "", s)
    return s.strip()


def _is_earnings(head):
    """見出しの型は先頭160字だけで見る（実測 RELX 2026-07-23『Changes to Board Committee roles … effective following
    publication of the results for the first half』＝183字目の results で委員会人事が決算に化けた）。"""
    h = head[:600]
    if EARN_NOT.search(h[:150]):
        return False
    return bool(EARN.search(h[:160])) or len({x.lower() for x in FINTERM.findall(h)}) >= 3


def _patterns():
    """分類 → 正規表現。kessan_check.ALERTS（四半期点検の6砲台＝単一実装）＋ FPI_ALERT（8-K Item 相当）"""
    pats = {}
    if kc is not None:
        for cat, ps in kc.ALERTS.items():
            if not cat.startswith("吉"):
                pats.setdefault(cat, []).extend(ps)
    for p, cat, _lab in FPI_ALERT:
        pats.setdefault(cat, []).append(p)
    return {c: [re.compile(p, re.I) for p in ps] for c, ps in pats.items()}


def _gate(cat, t, m, fyear=None):
    """「語が出た」ではなく「事象が起きた」かの門番。kessan_check._is_real をそのまま通し、
    ①通貨の書き方の違いで金額を見落とした却下だけを拾い直し ②表の行を落とす。戻り (採用するか, 却下の理由)"""
    before, after = t[max(0, m.start() - 300):m.start()], t[m.end():m.end() + 300]
    ok, why = kc._is_real(cat, before, after)
    if not ok and why.startswith("金額"):
        # 業績下方は発表の**見出し**に立ち、数字は次の段落に来る（実測 NVO 2025-07-29: 見出しから%まで200字超）。
        #   語そのものが実行の動詞＋outlook/guidance なので、金額の窓だけ ±500字へ広げる（減損は ±200字のまま）
        w = 500 if cat == "指針" else 200
        near = t[max(0, m.start() - w):m.start()] + " " + t[m.end():m.end() + w]
        if AMOUNT_FX.search(near) or (w > 200 and kc.AMOUNT.search(near)):
            ok, why = True, ""
    if ok and len(NUMTOK.findall(t[max(0, m.start() - 150):m.end() + 150])) >= TABLE_NUMS:
        ok, why = False, "数字の並ぶ表の行（財務諸表の明細＝毎期の行項目）"
    if ok and cat in SIXK_NOT_CTX:
        w = SIXK_NOT_WIN[cat]
        near = t[max(0, m.start() - w):m.end() + w]
        bare = cat != "誠" or m.group(0).lower() == "restatement"
        if bare and SIXK_NOT_CTX[cat].search(near) and not (cat == "誠" and ERRORISH.search(near)):
            ok, why = False, {"誠": "会計基準の適用・超インフレ会計の比較修正（誤りの訂正ではない）",
                              "存続": "条項・否定の中の破産語（事象の記述ではない）",
                              "減損": "金融資産の貸倒引当・行項目名の一部（毎期の定型）"}[cat]
    if ok and cat == "誠" and m.group(0).lower().startswith("material weakness") and \
            DUTYISH.search(t[max(0, m.start() - 120):m.end() + 120]):
        ok, why = False, "監査委員会等の職務の列挙（事象の記述ではない）"
    if ok and cat == "減損" and REVERSAL.search(before[-40:]):
        ok, why = False, "減損の戻入れ（利益側）"
    if ok and cat in SIXK_NOT_MATCH and SIXK_NOT_MATCH[cat].search(m.group(0)):
        ok, why = False, "見通しの幅の端の説明（下方修正ではない）"
    if ok and cat == "減損" and fyear:
        ys = [int(y) for y in YEAR.findall(t[max(0, m.start() - 150):m.end() + 150])]
        if ys and max(ys) <= fyear - 2:
            ok, why = False, f"過去の事象への言及（近傍の年が最も新しくて{max(ys)}年）"
    return ok, why


def _scan_text(t, doc, pats, acc, fyear=None):
    """1文書を走査して acc へ積む（分類ごとに採用2件まで・却下は件数と先頭3件だけ残す＝目視用）"""
    for cat, rxs in pats.items():
        keep = acc["ref" if cat in SIXK_REF else "hit"].setdefault(cat, [])
        seen = acc["pos"].setdefault((doc, cat), [])
        for rx in rxs:
            for m in rx.finditer(t):
                if len(keep) >= 2:
                    break
                if any(abs(m.start() - p) < 120 for p in seen):
                    continue          # 同じ箇所を別の語で二度数えない
                ok, why = _gate(cat, t, m, fyear)
                if not ok:
                    acc["ndrop"] += 1
                    if len(acc["drop"]) < 3:
                        acc["drop"].append(f"[却下:{cat}|{why}] {doc}: …{t[max(0, m.start() - 80):m.end() + 80]}…")
                    continue
                seen.append(m.start())
                keep.append({"doc": doc,
                             "s": t[max(0, m.start() - 110):m.end() + 110],
                             "short": t[max(0, m.start() - 40):m.end() + 70]})


def scan_6k(t, cik, acc, primary, form, fdate, pats, budget):
    """6-K 1件: 索引 → 主文書 → EX-99.x を読み、警報語と決算・報告の見出しを見る。
    戻り row（scan = ok / partial（一部読めず） / failed（何も読めず） / cap（上限で未着手）・gap に穴の理由）。"""
    a = acc.replace("-", "")
    base = f"{SEC}/Archives/edgar/data/{int(cik)}/{a}/"
    row = {"t": t, "form": form, "date": fdate, "items": [], "flags": [],
           "url": base + (primary or f"{acc}-index.htm"), "scan": "failed", "docs": []}
    if kc is None:
        row["gap"] = f"kessan_check を読み込めず本文を走査できない（{KC_ERR}）"
        return row
    if budget["left"] < 2:
        row["scan"], row["gap"] = "cap", f"1回の取得上限（--max-6k-docs {budget['limit']}）に達して未走査——次回の実行で読む"
        budget["capped"] += 1
        return row
    budget["left"] -= 1
    budget["used"] += 1
    try:
        docs = filing_index(cik, acc)
    except Exception as e:  # noqa: BLE001
        row["gap"] = f"提出の索引を取得できず（{str(e)[:80]}）"
        return row
    main = (next((d for d in docs if primary and d["name"] == primary), None)
            or next((d for d in docs if d["type"] in FPI_FORMS), None)
            or ({"name": primary, "type": form, "url": base + primary} if primary else None))
    ex = [d for d in docs if d["type"].startswith("EX-99")]
    skipped = []
    if not ex:   # EX-99 が無い表紙もある（EX-10 契約・EX-16 監査人の書簡・EX-17 辞任の書簡 等は読む）
        ex = [d for d in docs if d["type"].startswith("EX-") and not OFFERING_EX.match(d["type"])]
        skipped = [d["name"] for d in docs if d["type"].startswith("EX-") and OFFERING_EX.match(d["type"])]
    if main:
        row["url"] = main["url"]
    todo = ([main] if main else []) + ex
    acc_ = {"hit": {}, "ref": {}, "drop": [], "ndrop": 0, "pos": {}}
    heads, gaps = [], []
    if len(todo) > 1 + MAX_EX_PER_FILING:
        gaps.append(f"添付 {len(todo) - 1 - MAX_EX_PER_FILING}件は1提出の上限{MAX_EX_PER_FILING}で未走査")
        todo = todo[:1 + MAX_EX_PER_FILING]
    for d in todo:
        if not d["name"].lower().endswith((".htm", ".html", ".txt")):
            gaps.append(f"{d['name']}（{d['type']}）は本文を読めない形式")
            continue
        if budget["left"] < 1:
            gaps.append(f"{d['name']} は1回の取得上限で未走査")
            budget["capped_docs"] += 1
            continue
        budget["left"] -= 1
        budget["used"] += 1
        try:
            b, cut = _fetch(d["url"], limit=MAX_DOC_BYTES)
        except Exception as e:  # noqa: BLE001
            gaps.append(f"{d['name']} の取得失敗（{str(e)[:60]}）")
            continue
        tx = _text(b.decode("utf-8", "ignore"))
        if cut:
            gaps.append(f"{d['name']} は{MAX_DOC_BYTES // 1_000_000}MB超で後半を未走査")
        row["docs"].append(d["name"])
        heads.append((d is main, _head(tx)))
        _scan_text(tx, d["name"], pats, acc_, int(fdate[:4]) if str(fdate[:4]).isdigit() else None)
    if not row["docs"]:
        row["gap"] = "；".join(gaps) or "本文を1件も読めず"
        return row
    row["scan"] = "partial" if gaps else "ok"
    if gaps:
        row["gap"] = "；".join(gaps)[:400]
    if skipped:   # 読まなかったことは書く（穴ではない＝事象の文書ではないと決めて外したもの）
        row["skipped"] = f"募集書類・XBRL {len(skipped)}件は事象の文書ではないので走査せず: " + " ".join(skipped)[:200]
    # 題: 添付があればその先頭（表紙の主文書は定型文だけ）、無ければ主文書の署名欄より後
    exh = [h for is_main, h in heads if not is_main]
    title = (exh[0] if exh else heads[0][1])[:80].strip()
    if len(exh) > 1:
        title += f"（他{len(exh) - 1}件）"
    row["form"] = f"{form}｜{title}" if title else form
    row["kind"] = "earnings" if any(_is_earnings(h) for _m, h in heads) else "other"
    # 原文書の行き先: 表紙では何も読めないので、**警報の根拠がある文書**（無ければ最初の添付）へ向ける
    urls = {d["name"]: d["url"] for d in todo}
    content = [n for n in row["docs"] if not (main and n == main["name"])]
    if content:
        row["url"] = urls.get(content[0], row["url"])
    for cat in sorted(acc_["hit"], key=lambda c: SIXK_ORDER.index(c) if c in SIXK_ORDER else 99):
        hs = acc_["hit"][cat]
        if hs:
            if not row["flags"]:
                row["url"] = urls.get(hs[0]["doc"], row["url"])
            row["flags"].append(f"6-K語ヒット｜{SIXK_LABEL.get(cat, cat)}：…{hs[0]['short']}…")
    row["snips"] = [f"[{c}] {h['doc']}: …{h['s']}…" for c in acc_["hit"] for h in acc_["hit"][c]]
    row["ref"] = [f"[{c}・記録のみ] {h['doc']}: …{h['s']}…" for c in acc_["ref"] for h in acc_["ref"][c]]
    if acc_["ndrop"]:
        row["dropped"] = {"n": acc_["ndrop"], "top": acc_["drop"]}
    for k in ("snips", "ref"):
        if not row[k]:
            del row[k]
    return row


def edinet_scan(jp, days, hits, earnings, others, errors):
    """EDINET日付別一覧から監視中の日本株の新規提出を拾う。鍵が無ければ None（=対象外の穴）"""
    key = os.environ.get("EDINET_API_KEY", "").strip()
    if not key or not jp:
        return None
    want = {t[:4] for t in jp}          # documents.json の secCode は5桁（末尾0）
    n_days_ok = 0
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        try:
            j = json.loads(get(f"https://api.edinet-fsa.go.jp/api/v2/documents.json?date={d}&type=2&Subscription-Key={key}"))
            n_days_ok += 1
        except Exception as e:
            errors.append({"t": f"EDINET:{d}", "err": str(e)[:120]})
            continue
        for doc in (j.get("results") or []):
            sec = str(doc.get("secCode") or "")
            if sec[:4] not in want:
                continue
            desc = str(doc.get("docDescription") or "")
            row = {"t": sec[:4], "form": desc[:60], "date": doc.get("submitDateTime", d)[:10],
                   "items": [], "flags": [], "url": "",
                   "docID": doc.get("docID")}
            if "臨時報告書" in desc:
                row["flags"] = ["臨時報告書＝重要事象（役員異動・訂正等）の可能性——原本を読む(EDINETでdocID検索)"]
                hits.append(row)
            elif "訂正" in desc:
                row["flags"] = ["訂正報告書＝過年度の記載訂正の可能性——原本を読む"]
                hits.append(row)
            elif any(x in desc for x in ("有価証券報告書", "四半期報告書", "半期報告書")):
                earnings.append(row)     # 決算・報告イベント（警報ではない）
            else:
                others.append(row)       # 大量保有等——記録のみ
    return {"covered": True, "days_scanned": n_days_ok, "tickers": sorted(want)}


def _opt(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    days = int(_opt("--days", 7))
    cap = int(_opt("--max-6k-docs", MAX_6K_FETCH))
    only = _opt("--only")
    out_path = os.path.abspath(_opt("--out") or OUT)
    since = (date.today() - timedelta(days=days)).isoformat()

    if only:   # 試験用: 監視リストの外でも指定できる（正本は書き換えない＝下の書き込みで止める）
        names = [x.strip().upper() for x in only.split(",") if x.strip()]
        us, jp = [x for x in names if not x[:1].isdigit()], [x for x in names if x[:1].isdigit()]
    else:
        us, jp = kanshi_us()
    m = cik_map(us)
    missing = [t for t in us if t.upper() not in m]

    hits, earnings, others, errors, checked = [], [], [], [], 0
    fpi_seen, fpi_counts = [], {}   # 6-K経路の社（外国私募発行体）
    sixk = []                       # 窓内の 6-K（本文は下でまとめて読む＝上限を新しい順に配るため）
    for t in us:
        cik = m.get(t.upper())
        if not cik:
            continue
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
            rec = sub.get("filings", {}).get("recent", {})
            forms = rec.get("form", []); dates = rec.get("filingDate", [])
            items = rec.get("items", []); accn = rec.get("accessionNumber", [])
            docs  = rec.get("primaryDocument", [])
            checked += 1
            # FPI判定（2026-09-23）: **最新の年次報告が 20-F/40-F** なら 6-K 経路の社。
            #   旧判定「recent に 8-K が1本も無い」は、国内提出体へ移った社（古い 8-K が残る）や
            #   その逆で割れる。年次報告の様式は会社が今どちらの制度にいるかを直接言う。
            #   年次報告が recent に無い若い社は 6-K の有無で見る。いずれも列挙はしない。
            annual = next((f for f in forms if f in ANNUAL_FORMS), None)
            is_fpi = (annual or "").startswith(("20-F", "40-F")) or (
                annual is None and any(f in FPI_FORMS for f in forms))
            n6 = 0
            for i, f in enumerate(forms):
                if i >= len(dates) or dates[i] < since:
                    continue
                a = (accn[i] if i < len(accn) else "").replace("-", "")
                url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a}/{docs[i]}"
                       if a and i < len(docs) and docs[i] else "")
                if f in FPI_FORMS:
                    # ⚠**6-K の主文書はたいてい表紙**で、中身は添付(EX-99)に在る——本文は scan_6k が索引から読む
                    n6 += 1
                    sixk.append({"t": t, "cik": cik, "acc": accn[i] if i < len(accn) else "",
                                 "primary": docs[i] if i < len(docs) else "", "form": f, "date": dates[i],
                                 "url": url})
                    continue
                if f not in ("8-K", "8-K/A"):
                    continue
                its = [x.strip() for x in (items[i] if i < len(items) else "").split(",") if x.strip()]
                flags = [f"Item {x}: {ALERT_ITEMS[x]}" for x in its if x in ALERT_ITEMS]
                row = {"t": t, "form": f, "date": dates[i], "items": its, "flags": flags, "url": url}
                if flags:
                    hits.append(row)
                elif "2.02" in its:
                    earnings.append(row)   # 決算発表(2.02)は警報でなく「決算イベント」として別置き（門のイベントタブが表示）
                else:
                    others.append(row)     # 1.01契約/7.01RegFD/8.01その他等——警報ではないが記録は残す
            if is_fpi or n6:
                fpi_seen.append(t)
                fpi_counts[t] = n6
        except Exception as e:
            # 取得失敗は失敗として書く。黙って飛ばすと「監視した」顔をする（ルール7の親戚: 欠測を健全と読むな）
            errors.append({"t": t, "err": str(e)[:200]})

    # ── 6-K の本文を読む（新しい順・1回 cap 取得まで）──────────────────────────────
    #   上限は**新しい提出から配る**——日次の窓で古い側は前日までに読んでいる公算が高く、
    #   新しい側は今日初めて見る。上限で読めなかった分は下で errors（監視の穴）に名指しする。
    pats = _patterns() if kc is not None else {}
    budget = {"limit": cap, "left": cap, "used": 0, "capped": 0, "capped_docs": 0}
    gaps6, scanned6, partial6 = {}, {}, {}
    for fl in sorted(sixk, key=lambda x: (x["date"], x["acc"]), reverse=True):
        row = scan_6k(fl["t"], fl["cik"], fl["acc"], fl["primary"], fl["form"], fl["date"], pats, budget)
        t = fl["t"]
        if row["scan"] in ("failed", "cap"):
            gaps6.setdefault(t, []).append({"date": row["date"], "url": row["url"] or fl["url"], "why": row["gap"]})
            print(f"  6-K {t:<6}{row['date']}  ⚠未走査——{row['gap']}")
            continue
        if row["scan"] == "partial":
            gaps6.setdefault(t, []).append({"date": row["date"], "url": row["url"], "why": row["gap"]})
            row["form"] += "（一部未走査＝監視の穴）"
            partial6[t] = partial6.get(t, 0) + 1
        else:
            scanned6[t] = scanned6.get(t, 0) + 1
        kind = "決算・報告" if row.get("kind") == "earnings" else "その他"
        print(f"  6-K {t:<6}{row['date']}  {'✓' if row['scan'] == 'ok' else '△'}{len(row['docs'])}文書 "
              f"{kind:<5} {'⚠' + str(len(row['flags'])) + '旗 ' if row['flags'] else ''}{row['form'][:90]}")
        if row["flags"]:
            hits.append(row)       # 決算の 6-K でも警報語が立てば警報（8-K の Item と同じ優先）
        elif row.get("kind") == "earnings":
            earnings.append(row)   # 8-K 2.02 相当＝決算・報告イベント（警報ではない）
        else:
            others.append(row)     # 自社株買いの週報・配当・議決権総数等——記録のみ
    # 読めなかった 6-K は**社ごとに1行**で errors へ（門は errors の件数を『N社』と数えるので社で束ねる）。
    #   ⚠ここに載った社は「見て何も無い」ではなく「見ていない」——📋今日の死角にも出る。
    for t, lst in gaps6.items():
        errors.append({"t": t, "kind": "6-K本文の未走査",
                       "err": f"6-K {len(lst)}件の本文を走査できていない: "
                              + "／".join(f"{g['date']} {g['why']}" for g in lst)[:400],
                       "why": f"6-K {len(lst)}件の本文未走査（{lst[0]['why'][:60]}）＝警報なしではなく見ていない",
                       "filings": lst})

    jp_cov = edinet_scan(jp, days, hits, earnings, others, errors)

    # ── 未完了の重大事象の「見落としの網」（v9.9.128・2026-08-10）────────────────
    #   【なぜ要るか】第四の関門の `_meta.pending`（合意済み・未完了の買収等）は**審査官が書く**欄で、
    #   門ができるのは「書かれていたら必ず効かせる」ところまで。書き漏らすと関門が眠る。
    #   そこで **8-K の Item 1.01(重要な契約の締結) / 1.02(同 解除) / 8.01(その他)** を
    #   **判定圏(Ω72+)に絞って作業リストに出す**——M&Aの合意・解除・判決はこの3つに載る。
    #   【なぜ警報に格上げしないか】8.01 は雑多で、格上げすると「鳴りすぎる警報は鳴らないのと同じ」を
    #   自分で作ることになる（実測: 今日の others は KLAC/APH の 8.01 が2件で、どちらも M&A ではない）。
    #   だから **alerts には入れず、todo として別に出す**。判定には一切使わない（門の第四の関門は
    #   あくまで `_meta.pending` を読む）——これは**人が pending を書き漏らしていないかの点検**。
    TODO_ITEMS = {"1.01": "重要な契約の締結", "1.02": "重要な契約の解除", "8.01": "その他の事象"}
    q72 = set()
    try:
        for r in json.load(open(os.path.join(os.path.dirname(OUT), "score_all.json"), encoding="utf-8")):
            if (r.get("s") or 0) >= 72:
                q72.add(r["t"])
    except Exception:
        q72 = set()      # 取れなければ空＝この網は眠るだけ（無いことを「異常なし」と偽らない・ルール7）
    pending_todo = []
    for r in others:
        if r["t"] not in q72:
            continue
        hit = [f"Item {x}: {TODO_ITEMS[x]}" for x in r.get("items", []) if x in TODO_ITEMS]
        if hit:
            pending_todo.append(dict(r, todo=hit))

    n6_all = len(sixk)
    n6_ok = sum(scanned6.values())
    n6_part = sum(partial6.values())
    n6_gap = sum(len(v) for v in gaps6.values()) - n6_part
    out = {
        "asof": date.today().isoformat(),
        "window_days": days,
        "checked_us": checked,
        # 2026-08-10: **8-K経路と6-K経路を分けて出す。**「38社を見た」の中身が
        #   実は「8-K経路28社＋原理的に何も立たない10社」だったのを可視化する。
        # 2026-09-23: 本文を読めた件数・読めなかった件数・取得の上限を足した（キーは足しただけで既存は不変）。
        "fpi_6k": {"tickers": sorted(fpi_seen), "filings_in_window": fpi_counts,
                   "scanned": scanned6, "partial": partial6,
                   "unscanned": {t: len(v) - partial6.get(t, 0) for t, v in gaps6.items()
                                 if len(v) - partial6.get(t, 0) > 0},
                   "fetch": {"limit": cap, "used": budget["used"],
                             "capped_filings": budget["capped"], "capped_docs": budget["capped_docs"],
                             "truncated": bool(budget["capped"] or budget["capped_docs"])},
                   "note": "外国私募発行体は8-Kを出さず6-Kで重要事象も決算も報じる。"
                           "6-KにはItem番号が無いので、提出の索引から主文書＋EX-99.xを読み、"
                           "kessan_check の警報語（誠/減損/退任/指針）とFPI_ALERT（8-K Item相当: 存続/上場）を**語で**拾う"
                           "（項目番号より弱いので警報の言葉も『6-K語ヒット』と弱くする）。門番は kessan_check._is_real"
                           "（否定・定型・仮定法・金額）＋表の行。限/集は毎期の常設開示なので各行の ref に記録のみ。"
                           "決算・報告の6-Kは earnings へ（8-K 2.02 相当）。"
                           "**本文を読めなかった6-Kは errors（監視の穴）**＝『見ていない』と『見て何も無い』を区別する。"}
        if fpi_seen else None,
        "alerts": sorted(hits, key=lambda x: (x["date"], x["t"]), reverse=True),
        "earnings": sorted(earnings, key=lambda x: (x["date"], x["t"]), reverse=True),
        "others": sorted(others, key=lambda x: (x["date"], x["t"]), reverse=True),
        "pending_todo": sorted(pending_todo, key=lambda x: (x["date"], x["t"]), reverse=True),
        "pending_todo_note": ("判定圏(Ω72+)の Item 1.01/1.02/8.01。**警報ではなく作業リスト**——"
                              "M&Aの合意・解除・判決はここに載るので、読んで該当すれば "
                              "パックの _meta.pending へ書く（night/audit_pending.py が関門で読む）。"
                              "8.01は雑多なので警報には格上げしない＝鳴りすぎる警報は鳴らないのと同じ"),
        "errors": errors,
        "cik_unresolved": missing,
        "jp": jp_cov if jp_cov else None,
        "not_covered_jp": None if jp_cov else {
            "tickers": jp,
            "why": ("EDINET_API_KEY 未設定＝日本株のイベント監視は穴のまま。"
                    "鍵は https://api.edinet-fsa.go.jp/ で無料登録し、GitHub Secrets の EDINET_API_KEY に置くと"
                    "臨時報告書(8-K相当)・訂正・有報/四半期の提出が自動で入る")},
        "note": "判定には使わない。alertsが立った銘柄は門2再審査（依頼文）へ回す。四半期点検の隙間を埋める気づきの層であり、株価は見ない",
    }
    jp_msg = (f"日本株{len(jp_cov['tickers'])}社をEDINETで走査" if jp_cov
              else f"日本株{len(jp)}社は対象外（EDINET_API_KEY未設定＝明示）")
    six_msg = (f"6-K {n6_all}件（本文走査✓{n6_ok}・一部{n6_part}・未走査{n6_gap}・取得{budget['used']}/{cap}"
               f"{'＝上限で打ち切り' if out['fpi_6k'] and out['fpi_6k']['fetch']['truncated'] else ''}）")
    print(f"イベント監視: 米国{checked}社（うち6-K経路{len(fpi_seen)}社・窓{days}日）＋{jp_msg} → {six_msg} → "
          f"警報 {len(hits)}件 / 決算・報告 {len(earnings)}件 / その他 {len(others)}件 / 取得失敗 {len(errors)}件 / CIK不明 {len(missing)}件")
    for h in hits:
        print(f"  ⚠ {h['t']} {h['date']} {'; '.join(h['flags'])}")
    if pending_todo:
        print(f"\n  📋 未完了の重大事象の点検（判定圏 {len(pending_todo)}件・**警報ではなく作業リスト**）")
        print(f"     読んで M&A の合意・解除・判決なら パックの _meta.pending へ書く（audit_pending.py が関門で読む）")
        for r in pending_todo:
            print(f"     {r['t']:<6}{r['date']}  {'; '.join(r['todo'])}  {r['url']}")
    if errors:
        print("  取得失敗:", ", ".join(e["t"] for e in errors))
    # 空書き込みの検問（audit_stale_bs:243 と同じ言葉。v9.9.140）
    #   ⚠**1社も走査できていないのに書き換えない**。SECが落ちている日に上書きすると、
    #     alerts=[] が「見て何も無かった」に見える＝この道具が塞いだはずの穴を自分で作る。
    #   errors が出ていること自体は正常（個別社の取得失敗は errors に載せて続行する）ので、
    #   裁くのは **checked（実際に走査できた社数）が 0 かどうか**だけ。
    if checked == 0 and not (jp_cov and jp_cov.get("tickers")):
        print("⚠ 1社も走査できていない（SEC/EDINETが落ちている等）。"
              "**out/events_watch.json を書き換えない**——空の alerts は『見て何も無い』ではない")
        return 1
    # ★2026-09-23（ユーザー「日本株をEDINETキーで接続したい」→鍵は 2026-08-17 から Secrets に在った）:
    #   鍵を持たない**手元のセッション**でこの道具を回すと、CI が鍵ありで作った『日本株16社を走査済み』を
    #   『EDINET_API_KEY 未設定』で上書きしていた（実害: 0be8a197 が門に「未接続」と出させた）。
    #   ⇒ **鍵が無く、正本が鍵ありの走査結果を持っているときは正本を書き換えない**（--out で別の場所へは書ける）。
    if not jp_cov and jp and out_path == os.path.abspath(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                _prev_jp = (json.load(f) or {}).get("jp") or {}
        except Exception:
            _prev_jp = {}
        if _prev_jp.get("covered"):
            print("⚠ EDINET_API_KEY がこの環境に無い——正本 out/events_watch.json は CI が鍵ありで作った"
                  "日本株の走査結果を持っているので**書き換えない**（鍵なしの結果で『未接続』に戻さない）。"
                  "試すなら --out で別の場所へ。鍵は GitHub Secrets にあり、events.yml が毎日使う")
            return 1
    if only and out_path == os.path.abspath(OUT):
        print("※ --only は試験用なので正本 out/events_watch.json は書き換えない（--out で別の場所へ書ける）")
        return 0
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {os.path.relpath(out_path, BASE) if out_path.startswith(BASE + os.sep) else out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
