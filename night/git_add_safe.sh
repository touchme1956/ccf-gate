#!/usr/bin/env bash
# 一つの実在しないパスが git add 全体を落とすのを止める（2026-08-17新設）
#
# ■ なぜ要るか（実測で見つけた事故）
#   `git add a b c` は **1つでもパスが実在しないと、コマンド全体が失敗して1つもステージしない**。
#   ワークフローはどれも末尾に `2>/dev/null || true` を付けているので、
#   **エラーメッセージも終了コードも消える＝「作ったのに残らない」が完全に無音で起きる**。
#
#   実証（2026-08-17）:
#     $ git add a.txt nonexistent.json b.txt 2>/dev/null || true
#     $ git diff --staged --name-only
#     （空）        ← a.txt も b.txt も捨てられる
#
#   実害: `ops.yml` の38パスの add に **`out/market_data.json`（実在しない。本物は repo 直下）** が
#   混じっており、**38パス全部が毎回捨てられていた**。GitHub上での初回実行(run_number 1)で
#   next_earnings.json / kanshi_list.json / divy.json / profiles.json / hist_val_now.json /
#   sht_report.json / _sic_cache.json / packs_index.json / logos … が1件も入らなかった。
#   このとき AV_KEY は正しく効いており、ログには
#   `Alpha Vantage: 10/39 銘柄の決算日を取得` `ASML 2026-10-14` と出ていた——
#   **鍵は効いていたのに、成果だけが捨てられていた。**
#   `fix.yml` も同型（out/roiic.json / out/acq5.json / out/sht.json が実在しない）。
#
# ■ 直し方は「悪いパスを消す」ではなく「構造で効かなくする」
#   悪いパスを消すのは今日の1件しか直さない。**次に誰かがステップを足したらまた同じことが起きる。**
#   1パスずつ add して、落ちたものを**名指しで出す**——
#   これで (a)巻き添えが原理的に起きない (b)実在しないパスが静かに増えない。
#
# ■ 使い方（ワークフローの commit 段で）
#     . night/git_add_safe.sh
#     ccf_git_add out/a.json 'out/*_gate_pack.json' out/dir
#   ⚠ **glob は必ずシングルクォートで渡す**（呼び出し側で展開させない）。
#     クォートすると git へ1回で渡るので速い。クォートし忘れても動くが add の回数が増えるだけ。
#
# ■ 返り値は常に 0
#   「実在しないパスがあった」ことでジョブを落とさない（落とすと今度は他の成果物が残らない）。
#   代わりに ::warning:: で GitHub の実行サマリに出す＝**静かに壊れない**。

ccf_git_add() {
  local p miss=""
  for p in "$@"; do
    # shellcheck disable=SC2086  # glob を展開させるため意図的にクォートしない
    if ! git add -- $p 2>/dev/null; then
      miss="$miss $p"
    fi
  done
  if [ -n "$miss" ]; then
    echo "::warning::git add で無視したパス（実在しないか glob が0件）:$miss"
    echo "⚠ git add で無視したパス（実在しないか glob が0件）:$miss" >&2
    echo "   → ワークフローの add 一覧から消すか、そのファイルを作るステップを直すこと" >&2
  fi
  return 0
}
