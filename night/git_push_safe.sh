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
  local br n=0 max=4 wait=2 conflicts stashed
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
    # ⚠2026-11-23 是正: コミットしなかった変更が作業ツリーに残っていると、rebase は**始まりもしない**
    #   （"error: cannot rebase: You have unstaged changes."）。旧はそれを「衝突: 不明」と報じて落ちた。
    #   実害: ops.yml（月次）は 2026-11-03、387ファイルをコミットしたあと push が弾かれ、この道で落ちて
    #   **11月の月次の成果がまるごと main に届かなかった**（回転盤の月次の作業が全部 10-03 のまま＝停止疑い 31本）。
    #   月次のジョブは add しない生成物（キャッシュの外の途中のファイル）を作業ツリーに残すので、remote が1回でも
    #   進めば必ずこうなる。⇒ 残っている変更は**退避してから** rebase し、終わったら戻す（コミットの中身は変えない）。
    stashed=0
    if [ -n "$(git status --porcelain)" ]; then
      if git stash push --include-untracked --quiet -m "ccf_git_push: rebase の前にコミットしなかった変更を退避"; then
        stashed=1
      else
        echo "::error::コミットしなかった変更を退避できない——rebase に進めない"
        return 1
      fi
    fi
    if ! git rebase "origin/$br"; then
      conflicts="$(git diff --name-only --diff-filter=U | tr '\n' ' ')"
      git rebase --abort 2>/dev/null || true
      if [ "$stashed" = 1 ]; then
        git stash pop --quiet || echo "::warning::退避した変更を戻せなかった（stash に残っている）"
      fi
      echo "::error::rebase が解けない（衝突: ${conflicts:-不明}）——**自動で解決しない**。"
      echo "::error::  どちらを採るかは機械には判らない。次の実行が新しい main を土台にやり直す"
      return 1
    fi
    if [ "$stashed" = 1 ]; then
      if ! git stash pop --quiet; then
        # remote が同じファイルを書き換えていた／同じ名前のファイルを足していた。コミットした成果には関係ない。
        # 作業ツリーを rebase 後の姿にそろえる（退避は stash に残す＝捨てない）。
        echo "::warning::退避したコミットしなかった変更を戻せなかった（remote が同じファイルを触っていた）——コミットした成果には影響しない。作業ツリーは rebase 後の姿にした（退避は stash に残してある）"
        git reset --hard --quiet HEAD
      fi
    fi
    sleep "$wait"; wait=$((wait * 2))
  done
}
