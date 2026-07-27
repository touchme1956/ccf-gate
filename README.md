# 壊れない複利の門 — 引っ越しキット（並走用）

現行（Drive+Colab）はそのまま。このリポジトリは並走検証用の新環境。

## 手順（スマホだけで完結・初回のみ）
1. **GitHubにリポジトリを作る**: github.com → New repository → 名前 `ccf-gate` → **Private** → Create
2. **ファイルを上げる**: Add file → Upload files → このキットの中身を全部選択 → Commit changes
   （あれば gate1_queue.json も一緒に上げる＝待ち行列を引き継げる）
3. **門の配信（GitHub Pages・2026-07移行）**: リポジトリ Settings → Pages → Branch `main` を選択 → Save。
   以後、リポジトリの index.html を更新するだけで門が自動で新しくなる（手動アップロード不要）。
   公開URL: `touchme1956.github.io/ccf-gate/index.html`
4. **Claude Codeから使う**: スマホのClaudeアプリ → 「コード」 → `ccf-gate` を開く →
   「採取して」「発掘して」と頼むだけ。詳しい約束事は CLAUDE.md に書いてある

## 同梱ページ・データ
- `portfolio.html` — Ⅶ資産タブの中身（iframe）。網/城の全保有・出口判定の色丸・完全バックアップ/復元
- `kanshi_list.json` — 決算監視の正本リスト（kessan_check / kessan_calendar の入力）
- `kessan_checklist.md` — 決算点検の手順書（運用サイクルの全体像）
- `night/` — 夜間バッチ審査の作業場（チャンク・審査官テンプレ・進行表。night/README.md 参照）
- `v10.html` — v10「系列の門」影スコアの閲覧ページ（/ccf-gate/v10.html。正本の合否には不使用・V10_SPEC.md参照）

## 別枠の門（＝門X 一本）
- `chomirai.html` — **超未来の門（CCF X）**: 期待リターン最大化の別枠。予知はせず、
  期待リターンの三項分解（純還元＋b×ROIIC＋倍率の重力）・非対称チェック・複利の漏れ・
  ケリー基準の賭けサイズを裁く。正本 index.html（門Ω）の採点・売却規律は一切変更しない。
  GitHub Pages配信後は `/ccf-gate/chomirai.html` で開ける

（怪物の門＝点火検知は、無知の枠を運用しない方針のため2026-07に撤去。git履歴に保存。）

## 並走のルール
- 正本は現行（Drive+Colab+今の門URL）。台帳・保有の記帳は現行のみ
- 新環境の出力（待ち行列・採取JSON）を現行と突き合わせ、一致したら乗り換えを検討
