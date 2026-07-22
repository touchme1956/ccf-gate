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

## 別枠の門
- `chomirai.html` — **超未来の門（CCF X）**: 期待リターン最大化の別枠。予知はせず、
  期待リターンの三項分解（還元＋b×ROIIC＋倍率の重力）・非対称チェック・複利の漏れ・
  ケリー基準の賭けサイズを裁く。正本 index.html（門Ω）の採点・売却規律は一切変更しない。
  Cloudflare Pages配信後は `/chomirai` で開ける
- `kaibutsu.html` + `kaibutsu_scan.py` — **怪物の門（CCF IGNIS）**: NVIDIA型の複利怪物を
  最速（＝法定開示と同速）で待ち伏せる別枠。段1: gate0_all.csv 全母集団を怪物署名
  （超成長×資本効率×利益体質×FCF転換）でランク → 段2: 上位のSEC四半期データで
  点火検知。点火A=売上加速型（YoY加速2連続∧YoY≥25%∧営利率+2pt・NVIDIA型）、
  点火B=利益率階段型（営利率+2pt×2Q連続∧YoY≥10%・Amazon/Microsoft型）。
  集団発火（30%超が同時点火=マクロ）は自動警告。kessan_check.py は新セグメント・
  大手流通契約を「☀吉報」検知（第二S字の見張り）。年1回＋四半期に
  `python kaibutsu_scan.py` を実行 → `kaibutsu_queue.json` / `out/kaibutsu_report.txt`。
  点火銘柄は買いではなく門Ω審査へ回す合図。サイズは門Xの無知の枠(5-10%)・¼ケリーで縛る。
  配信後は `/kaibutsu` で開ける

## 並走のルール
- 正本は現行（Drive+Colab+今の門URL）。台帳・保有の記帳は現行のみ
- 新環境の出力（待ち行列・採取JSON）を現行と突き合わせ、一致したら乗り換えを検討
