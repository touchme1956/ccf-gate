#!/usr/bin/env bash
# main への push が「remote が進んだ」だけで捨てられるのを止める（2026-08-18新設）
#
# ■ なぜ要るか（実測で見つけた事故・「作った答えを捨てる」7例目）
#   `market.yml` が **2026-08-14 と 08-17 の2営業日つづけて失敗**していた。ログの最後はこう:
#       [main 3e9ceb8] market prices 2026-08-17｜64社｜投下可は不変
#        70 files changed, 2294 insertions(+), 2256 deletions(-)
#       ! [rejected] main -> main (fetch first)
#   ＝**コミットは作られているのに push で弾かれ、70ファイルまるごと消えた**。
#   結果 `out/dashboard.json` は 08-13 で止まり、回転盤が「株価・盤データ」「門の判定の履歴」を
#   停止疑いにしていた。
#
# ■ 原因は「時間をずらす」が効かないこと
#   ワークフローは 21:30 / 22:00 / 22:10 と**わざと時間をずらしてある**。だが
#   **GitHub Actions の cron は best-effort で 10〜40分ふつうに遅れる**——実測でも
#   market.yml は 21:52 / 22:20 と日によって始まりが動き、08-17 は ops.yml の
#   `monthly ops`(21:52) と正面衝突した。**スケジュールは要望であって保証ではない。**
#   ⇒ 衝突は予防できない。**push の側で受け止める**しかない。
#
# ■ 何をするか
#   push が弾かれたら `git fetch` → `git rebase origin/<branch>` → 再試行（最大4回・2/4/8/16秒）。
#   生成物どうしがぶつかって rebase が解けないときは **abort して名指しで落とす**——
#   ここで自動解決すると「相手の仕事を黙って上書きした」のか「自分の仕事が消えた」のか
#   後から判らなくなる。落ちれば次の実行が新しい main を土台にやり直す（自己修復する）。
#
# ■ 使い方
#     . night/git_push_safe.sh
#     ccf_git_push            # 現在のブランチを push
#
# ⚠ `git push -u origin <branch>`（PRブランチ）はここを通さない——衝突しないので要らない。

ccf_git_push() {
  local br n=0 max=4 wait=2 conflicts
  br="$(git rev-parse --abbrev-ref HEAD)"
  while :; do
    if git push "$@"; then
      [ "$n" -gt 0 ] && echo "✓ ${n}回目の再試行で push できた"
      return 0
    fi
    n=$((n + 1))
    if [ "$n" -gt "$max" ]; then
      echo "::error::push が ${max}回とも弾かれた——**このジョブの成果はコミットされたが main に届いていない**"
      return 1
    fi
    echo "::warning::push が弾かれた（${n}/${max}）——remote が進んだので rebase して再試行する"
    git fetch origin "$br" || { echo "::error::fetch できない"; return 1; }
    if ! git rebase "origin/$br"; then
      conflicts="$(git diff --name-only --diff-filter=U | tr '\n' ' ')"
      git rebase --abort 2>/dev/null || true
      echo "::error::rebase が解けない（衝突: ${conflicts:-不明}）——**自動で解決しない**。"
      echo "::error::  どちらを採るかは機械には判らない。次の実行が新しい main を土台にやり直す"
      return 1
    fi
    sleep "$wait"; wait=$((wait * 2))
  done
}
