# night/ — 夜間バッチ審査の作業場

gate1_queue の未審査銘柄を約10社ずつのチャンクに割り、夜間に門2審査（完成パック生成）を回すための道具一式。

- `chunkNN.txt` — 審査する銘柄リスト（10社/枚・計約150社）
- `agent_prompt_template.txt` — 審査官エージェントへの指示文。**正本は index.html Ⅱ実行手順「3 審査」の門2審査プロトコル**——正本を改定したら本テンプレも必ず同期すること（二重正本ドリフト防止）
- `agent_prompt_template_jp.txt` — 日本株版（2026-07新設）。EDINET_DB/Webで自力採取し、JP必須規約（ROIC三点＝現金非控除・60%上限、roicEx必須、TTM PER）を強制。一括再審査は「日本株を夜間審査して」だけでよい（`make_chunks.py` が `jp_chunkNN.txt` を作るのでコード貼りは不要）。EDINET_DB MCPが未接続のときの代替採取経路も明記済み
- `progress.json` — 進行表。`fetched`（採取済）→ `pending_review`（審査待ち）→ `reviewed`（審査済）
- `kenshi_helper.py` — 検死用: companyfacts.zip から年次系列（売上/営利/OCF/capex/株数…）を機械表示
- `make_copypage.py` — 完成パックのコピー用ページ生成
- `make_chunks.py` — 未審査分のチャンク自動生成（queue/椅子/棚/backlog−審査済−SKIP。10社/枚・連番継続）＋日本株の `jp_chunkNN.txt` と `out/packs_index.json`（門の一括取込ボタン用の目録）を更新
- `validate_jp_packs.py` — 日本株パックの納品検査。`python3 night/validate_jp_packs.py`（コード指定も可）。nmがコード始まりか（＝門のJP検問が発火するか）・ROIC三点（roic/roicEx同値・60%上限・roicg≤roicののれん整合）・TTM PERの符号・様式キー一致（受理キーは門のapplyFieldsから読む）・列挙値/点数域・_meta必須を落とす。**致命があれば審査官へ差し戻す**（そのまま置くと門が取込拒否して審査待ちに溜まる）

出力は `out/{T}_gate_pack.json`（完成パック）。パックは門のⅢ採点機「＋取り込む」へ。
機械値だけのドラフト（`{T}_gate_input.json`）は台帳データではない（CLAUDE.md 絶対のルール2）。
