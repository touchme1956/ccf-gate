# CCF Ω 壊れない複利の門 — パイプライン作業場

個人投資家たっちみーさんの銘柄審査パイプライン。20-30年の長期複利が目的。
**index.html が門（UI・台帳・売却規律・審査プロトコルの正本）**。Cloudflare Pagesで自動配信される。

## コマンド
- 年1回（1-2月）発掘: `python run_gate0_local.py`
  - companyfacts.zip(1.4GB)が45日超なら自動で最新に更新（検証母集団=全上場が毎年更新される）
  - holdings.json があれば HOLDINGS/WATCH を自動差し替え（門のⅤ保有タブから書き出したもの）
  - 出力: gate1_queue.json（待ち行列100社）、gate0_all.csv
- 月1-2回 採取: `python hachimon_fetch.py`
  - 引数なし=gate1_queue.jsonの未処理上位5社を自動採取。個別指定: `python hachimon_fetch.py NVDA MSFT`
  - 出力: out/{T}_gate_input.json（機械値ドラフト・審査待ち）+ out/{T}_hits.txt（原本キーワード抜粋）

## 絶対のルール
1. index.html の採点ロジック・売却規律(S1/S2/S3)・採点基準は、ユーザーの明示指示なしに変更しない
2. 採取器の出力は「審査待ち」であり台帳データではない。定性項目(dom/irr/rep/dur/p1-4/f1-5)を勝手に埋めない
3. 銘柄審査を頼まれたら: out/{T}_gate_input.json と {T}_hits.txt を読み、index.html内の審査プロトコル
   （Ⅱ実行手順「3 審査」に全文）に従う。憶測禁止・全判定に原本根拠を付ける
4. companyfacts.zip はコミットしない(.gitignore済)。生成物(gate1_queue.json, out/)はコミットする
5. SEC アクセスの User-Agent メールは設定済み。レート制限(10req/s)を守る

## 並走運用（重要）
現行の正本系は Google Drive + Colab + Cloudflare。このリポジトリは並走検証中の新環境。
台帳・保有の記帳は現行側のみ。ここの出力は現行と突き合わせて一致を確認するのが仕事。
