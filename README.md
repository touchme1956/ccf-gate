# 壊れない複利の門 — 引っ越しキット（並走用）

現行（Drive+Colab）はそのまま。このリポジトリは並走検証用の新環境。

## 手順（スマホだけで完結・初回のみ）
1. **GitHubにリポジトリを作る**: github.com → New repository → 名前 `ccf-gate` → **Private** → Create
2. **ファイルを上げる**: Add file → Upload files → このキットの中身を全部選択 → Commit changes
   （あれば gate1_queue.json も一緒に上げる＝待ち行列を引き継げる）
3. **門の配信（Cloudflare Pages）**: Cloudflareダッシュボード → Workers & Pages → Create → Pages →
   Connect to Git → `ccf-gate` を選択 → ビルド設定は空のまま Deploy。
   以後、リポジトリの index.html を更新するだけで門が自動で新しくなる（手動アップロード不要）
4. **Claude Codeから使う**: スマホのClaudeアプリ → 「コード」 → `ccf-gate` を開く →
   「採取して」「発掘して」と頼むだけ。詳しい約束事は CLAUDE.md に書いてある

## 並走のルール
- 正本は現行（Drive+Colab+今の門URL）。台帳・保有の記帳は現行のみ
- 新環境の出力（待ち行列・採取JSON）を現行と突き合わせ、一致したら乗り換えを検討
