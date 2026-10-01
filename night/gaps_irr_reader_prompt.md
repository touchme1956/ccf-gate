# 読み手への指示（歴史検証の穴⑦・2013年の年次報告書から irr の引用を選ぶ）

あなたは、年次報告書（2013年7月以前に提出されたもの）を読み、**顧客が当社から他社へ乗り換えるとき、費用と時間を負うのは誰か**を示す引用を1つ選び、刻みを提案する。

## 読むもの（これ以外は開かない）
- あなたの束のファイル（`out/gaps_delisted_irr/batchNN.json`）: 各行に `id` と本文のファイルの場所 `file`
- 刻みの規約: `out/irr_regrade/RUBRIC.md`（必ず最初に読む）
- 束に書かれた本文ファイルだけ

リポジトリの他のファイル・ウェブ・会社の知識は使わない。本文の社名は "the Company" に伏せてあるが、伏せきれていない所がある。**会社が分かっても、その後どうなったか（買収・破産・株価）の知識を採点に持ち込まない。**本文に書いてあることだけで裁く。

## 読み方（1社ずつ）
1. 本文は長い（20万〜60万字）。全部は読まない。まず Grep で次の語を探し、見つかった所の前後を読む:
   `qualif` `requalif` `certif` `approved vendor` `approved supplier` `validat` `specified` `sole source` `single source` `sole supplier` `only supplier` `designed into` `design-in` `design win` `switch` `switching cost` `long-term contract` `long-term agreement` `multi-year` `installed base` `consumable` `proprietary` `recurring` `renewal rate` `retention` `churn` `attrition` `embedded` `integrated into` `difficult to replace` `costly` `time-consuming` `barriers to entry` `compet`
2. 「Item 1. Business」の競争（Competition）の節も読む。
3. 乗り換えの費用を**顧客が**負うと述べる、いちばん強い一文（本文のとおり・英語・60語以内）を選ぶ。
4. RUBRIC.md の刻みで提案する: 85（顧客の側が再認定・再試験をやり直すと断定）／70（摩擦の機構を名指し）／50（それ以外）。**迷ったら下の刻みへ倒す。**向きの逆（当社が受ける認証・当社が仕入先を認定する話・当社が新規顧客を取るための認定）は 85 にしない。
5. 70 以上に当たる一文が無ければ 50。そのときは競争の記述など代表的な一文を quote に入れる（無ければ空文字）。

## 出す形（束の全社ぶんを1つの JSON 配列で）
書き先: `out/gaps_delisted_irr/read_NN.json`（NN は束の番号）
各行:
```json
{"id": "Dxxxxxxxx", "rung": 85, "quote": "本文のとおりの英文", "mech": "顧客側の再認定", "dir": "顧客が負う", "tense": "断定", "conf": "high", "sole_supplier": false, "why": "30〜80字の日本語。引用の中の語を必ず挙げる"}
```
- `rung`: 85 / 70 / 50
- `mech`: 顧客側の再認定 / 複数年の購買義務 / 消耗品の専用性 / データ移行・再教育 / 設置基盤 / 工程への組込 / 解約率・更新率の実数 / 物理的固着 / なし
- `dir`: 顧客が負う / 当社が負う / どちらでもない
- `tense`: 断定 / 願望形 / 該当なし
- `sole_supplier`: 本文が「顧客にとって唯一の供給者」と断定していれば true
- quote は**本文からそのまま写す**（要約・言い換えをしない）。後で本文と照合する

全社を書き終えたら、最後の返答は `done NN 件数` の1行だけにする。
