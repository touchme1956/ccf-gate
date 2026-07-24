# CCF Ω 壊れない複利の門 — パイプライン作業場

個人投資家たっちみーさんの銘柄審査パイプライン。20-30年の長期複利が目的。
**index.html が門（UI・台帳・売却規律・審査プロトコルの正本）**。Cloudflare Pagesで自動配信される。

## コマンド
- 年1回（1-2月）発掘: `python run_gate0_local.py`
  - companyfacts.zip(1.4GB)が45日超なら自動で最新に更新（検証母集団=全上場が毎年更新される）
  - holdings.json があれば HOLDINGS/WATCH を自動差し替え（門のⅤ保有タブから書き出したもの）
  - 出力: gate1_queue.json（待ち行列100社）、gate0_all.csv
- 四半期 保有点検: `python kessan_check.py`
  - holdings.jsonの保有銘柄について、直近の10-Q/8-Kを確認し、四半期売上YoY・営業利益率の前年同期差・警報(誠/限/集/指針/減損/退任)を機械抽出
  - 出力: out/kessan/{T}_qcheck.txt と要審査フラグ。要審査は門2再審査(依頼文)へ回す。株価は判定に使わない
- 四半期 決算カレンダー: `python kessan_calendar.py`
  - 監視リスト(保有+質80+)の次回決算日を取得(Alpha Vantage、鍵なしはSEC推定)
  - 出力: kessan_calendar.ics(Googleカレンダー取込=スケジュール連動) と out/next_earnings.json(門のⅤ保有で読込→常時表示)
- 月1-2回 採取: `python hachimon_fetch.py`
  - 引数なし=gate1_queue.jsonの未処理上位5社を自動採取。個別指定: `python hachimon_fetch.py NVDA MSFT`
  - 出力: out/{T}_gate_input.json（機械値ドラフト・審査待ち）+ out/{T}_hits.txt（原本キーワード抜粋）
- 年1回＋四半期 怪物の点火検知: `python kaibutsu_scan.py`
  - NVIDIA型の複利怪物を法定開示と同速で待ち伏せる別枠（怪物の門）。段1: gate0_all.csv 全母集団を
    怪物署名(超成長×資本効率×利益体質×FCF転換)でランク → 段2: 上位のSEC四半期データで点火検知
  - 判定: 点火A=売上加速型(YoY加速2連続∧YoY≥25%∧営利率+2pt) / 点火B=利益率階段型(営利率+2pt×2Q連続∧
    YoY≥10%) / くすぶり / 待機。集団発火(30%超同時点火=マクロのベータ)は自動警告
  - 引数: `--top N`(署名候補数) / `--max-rev N`(年商N B USD以下=中型小型のみ) / 個別指定 `kaibutsu_scan.py CRWD`
  - 出力: kaibutsu_queue.json（点火→点火B→くすぶり順）+ out/kaibutsu_report.txt
  - **点火は「買い」ではない。** hachimon_fetch.py で採取 → 門Ω審査 → 門Xのサイズ規律(無知の枠5-10%・¼ケリー)へ回す合図

## 別枠の門（正本ではない・思想不変）
- **門X = chomirai.html（超未来の門）**: 期待リターン最大化。予知せず E[r]=純還元(現金還元−希薄化)+b×ROIIC+
  倍率の重力 の分解機・非対称チェック・複利の漏れ・ケリー(¼上限)を裁く対話式ページ。配信後 `/chomirai`。
  **旧・怪物の門の芯（点火A＋非シクリカル点火B）は門Xの裁きⅡ「点火節」に統合済み**（検証で+26pt lift等を確認した部分のみ）
- **点火の採取器 = kaibutsu_scan.py**: 門Xの右裾検知の採取器。段1で候補母集団を怪物署名でランク→段2でSEC四半期を
  点in time走査し点火A/Bを検知。シクリカルの点火Bは「点火B(市況?)」に降格(検証で対照以下と実証)。
  静的HTMLは2900社を走査できないので機械部分はスクリプトのまま残す
- **kaibutsu_backtest.py**: 点火ルールの検証器(414社・生存者バイアスを排し前方3年売上CAGRで成否測定)。
  怪物の四類型(A売上点火/B利益率階段/C還元複利/D拍子木)・第二S字の思想は門Xの点火節に収録済み
- 順序は必ず **点火(見つける) → 門Ω(壊れないか審査) → 門X(期待値・サイズ)**。別枠は門Ωの採点・売却規律を上書きしない

## 絶対のルール
1. index.html の採点ロジック・売却規律(S1/S2/S3)・採点基準は、ユーザーの明示指示なしに変更しない
2. 採取器の出力は「審査待ち」であり台帳データではない。定性項目(dom/irr/rep/dur/p1-4/f1-5)を勝手に埋めない
3. 銘柄審査を頼まれたら: out/{T}_gate_input.json と {T}_hits.txt を読み、index.html内の審査プロトコル
   （Ⅱ実行手順「3 審査」に全文）に従う。憶測禁止・全判定に原本根拠を付ける
4. companyfacts.zip はコミットしない(.gitignore済)。生成物(gate1_queue.json, out/, kaibutsu_queue.json)はコミットする
5. SEC アクセスの User-Agent メールは設定済み。レート制限(10req/s)を守る
6. 門Xも別枠であって正本ではない。chomirai.html の採点式・閾値は明示指示なしに変更しない。
   点火検知は一次スクリーニングであり、買い推奨でも台帳データでもない

## 並走運用（重要）
現行の正本系は Google Drive + Colab + Cloudflare。このリポジトリは並走検証中の新環境。
台帳・保有の記帳は現行側のみ。ここの出力は現行と突き合わせて一致を確認するのが仕事。
