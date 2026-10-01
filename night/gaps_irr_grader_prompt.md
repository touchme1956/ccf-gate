# 採点者への指示（歴史検証の穴⑦・引用だけを盲検で採点する）

`out/irr_regrade/RUBRIC.md` を最初に読み、その規約だけで採点する。

- 採点する束: `out/gaps_delisted_irr/grade_items.json`（`id` と `quote` だけ）
- 読んでよいのは RUBRIC.md と この束だけ。リポジトリの他のファイル（とくに `out/gaps_delisted_irr/` の他のファイル）・ウェブは開かない
- 会社を推測しない。**引用文に書いてあることだけで裁く。迷ったら下の刻みへ倒す**

出す形: 束の全件を1つの JSON 配列で、指定されたファイルへ書く。各行は RUBRIC.md の「出す欄」:
```json
{"id": "Gxxxxxxxx", "rung": 70, "mech": "設置基盤", "dir": "顧客が負う", "tense": "断定", "conf": "med", "why": "30〜80字。引用の中の語を必ず挙げる"}
```
全件を書き終えたら、最後の返答は `done 件数` の1行だけにする。
