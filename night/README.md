# night/ — 夜間バッチ審査の作業場

gate1_queue の未審査銘柄を約10社ずつのチャンクに割り、夜間に門2審査（完成パック生成）を回すための道具一式。

- `chunkNN.txt` — 審査する銘柄リスト（10社/枚・計約150社）
- `agent_prompt_template.txt` — 審査官エージェントへの指示文。**正本は index.html Ⅱ実行手順「3 審査」の門2審査プロトコル**——正本を改定したら本テンプレも必ず同期すること（二重正本ドリフト防止）
- `agent_prompt_template_jp.txt` — 日本株版（2026-07新設）。EDINET_DB/Webで自力採取し、JP必須規約（門式ROIC・roicEx必須・TTM PER）を強制。一括再審査は「日本株を夜間審査して: 6861 6920 …」とコード列を渡すだけ
- `progress.json` — 進行表。`fetched`（採取済）→ `pending_review`（審査待ち）→ `reviewed`（審査済）
- `kenshi_helper.py` — 検死用: companyfacts.zip から年次系列（売上/営利/OCF/capex/株数…）を機械表示
- `make_copypage.py` — 完成パックのコピー用ページ生成
- `make_chunks.py` — 未審査分のチャンク自動生成（queue/椅子/棚/backlog−審査済−SKIP。10社/枚・連番継続）

出力は `out/{T}_gate_pack.json`（完成パック）。パックは門のⅢ採点機「＋取り込む」へ。
機械値だけのドラフト（`{T}_gate_input.json`）は台帳データではない（CLAUDE.md 絶対のルール2）。
