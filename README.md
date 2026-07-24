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

## 別枠の門（＝門X 一本）
- `chomirai.html` — **超未来の門（CCF X）**: 期待リターン最大化の別枠。予知はせず、
  期待リターンの三項分解（純還元＋b×ROIIC＋倍率の重力）・非対称チェック・**点火（右裾の早期検知）**・
  複利の漏れ・ケリー基準の賭けサイズを裁く。正本 index.html（門Ω）の採点・売却規律は一切変更しない。
  配信後は `/chomirai` で開ける
- `kaibutsu_scan.py` — **点火の採取器**（門Xの右裾検知）: 段1で候補母集団を怪物署名でランク → 段2で
  SEC四半期を走査し点火A（売上加速）/B（利益率階段）を検知。シクリカルの点火Bは対照以下ゆえ降格。
  `python kaibutsu_scan.py` → `kaibutsu_queue.json` / `out/kaibutsu_report.txt`。点火は買いでなく門Ω審査への合図。
- `kaibutsu_backtest.py` — 点火ルールの検証器（414社・生存者バイアスを排し前方3年で成否を測定）。

## 並走のルール
- 正本は現行（Drive+Colab+今の門URL）。台帳・保有の記帳は現行のみ
- 新環境の出力（待ち行列・採取JSON）を現行と突き合わせ、一致したら乗り換えを検討
