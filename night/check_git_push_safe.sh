#!/usr/bin/env bash
# night/check_git_push_safe.sh — ccf_git_push（night/git_push_safe.sh）の検査（2026-11-23 新設）
#
# ネットワークに出ない。一時ディレクトリの中に「remote（bare）と2つの clone」を作って、push のやり直しの道を通す。
#
# なぜ要るか（実害）
#   ops.yml（月次）は 2026-11-03、387ファイルをコミットしたあと push が弾かれ（別の workflow が先に push した）、
#   やり直しの rebase が "cannot rebase: You have unstaged changes." で始まりもせず、その月の成果が main に届かなかった。
#   月次のジョブはコミットしない生成物を作業ツリーに残すので、remote が1回でも進めば必ず落ちる形だった。
#   是正は「残っている変更を退避してから rebase し、終わったら戻す」。この検査はその道を見張る。
#
# 見るもの
#   ① remote が進んでいない              → 1回で push
#   ② コミットしなかった変更が残ったまま remote が進んだ（別のファイル）→ push できる・残した変更はそのまま
#   ③ 追跡していないファイルが残ったまま remote が進んだ          → push できる・ファイルは残る
#   ④ 同じファイルを両方がコミットした（本当の衝突）             → 落ちる（自動で解決しない）・rebase は片付いている・
#                                                                自分のコミットは残る・残した変更は戻っている
#   ⑤ 残した変更と remote のコミットが同じファイル               → push はできる（コミットした成果は届く）
#
# 使い方: bash night/check_git_push_safe.sh   （約15秒・終了コード 0=全部通過 / 1=どれか落ちた）
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
bad=0
ok()  { echo "✓ $1"; }
ng()  { echo "✗ $1"; bad=$((bad + 1)); }

G() { git -c user.name=test -c user.email=test@example.invalid -c init.defaultBranch=main -c advice.detachedHead=false "$@"; }

setup() {  # $1=名前 → $T/$1/{remote.git,a,b}（a と b は同じ最初のコミットを持つ）
  local d="$T/$1"
  mkdir -p "$d"
  G init --quiet --bare "$d/remote.git"
  G clone --quiet "$d/remote.git" "$d/a" 2>/dev/null
  ( cd "$d/a" && G config user.name test && G config user.email test@example.invalid \
      && G checkout --quiet -b main 2>/dev/null; printf 'one\n' > f1.txt; printf 'two\n' > f2.txt; printf 'three\n' > f3.txt \
      && G add -A && G commit --quiet -m init && G push --quiet -u origin main ) >/dev/null 2>&1
  G clone --quiet "$d/remote.git" "$d/b" >/dev/null 2>&1
  ( cd "$d/b" && G config user.name test && G config user.email test@example.invalid ) >/dev/null 2>&1
}

remote_advance() {  # $1=名前 $2=ファイル $3=中身 → b がコミットして push（remote が進む）
  ( cd "$T/$1/b" && printf '%s\n' "$3" > "$2" && G add -- "$2" && G commit --quiet -m "remote: $2" && G push --quiet ) >/dev/null 2>&1
}

run_push() {  # $1=名前 → a で ccf_git_push（出力は $T/$1/log）
  ( cd "$T/$1/a" && . "$HERE/git_push_safe.sh" && ccf_git_push ) > "$T/$1/log" 2>&1
}

remote_has() {  # $1=名前 $2=コミットの題
  G --git-dir="$T/$1/remote.git" log --format=%s main 2>/dev/null | grep -qx "$2"
}

# ① remote が進んでいない
setup c1
( cd "$T/c1/a" && printf 'mine\n' > f1.txt && G add -- f1.txt && G commit --quiet -m "mine: f1" ) >/dev/null 2>&1
if run_push c1 && remote_has c1 "mine: f1" && ! grep -q "再試行" "$T/c1/log"; then ok "① remote が進んでいない → 1回で push"; else ng "① 1回で push できない"; cat "$T/c1/log"; fi

# ② コミットしなかった変更が残ったまま remote が進んだ（別のファイル）
setup c2
( cd "$T/c2/a" && printf 'mine\n' > f1.txt && G add -- f1.txt && G commit --quiet -m "mine: f1" && printf 'leftover\n' > f2.txt ) >/dev/null 2>&1
remote_advance c2 f3.txt 'theirs'
if run_push c2 && remote_has c2 "mine: f1" && remote_has c2 "remote: f3.txt" \
   && [ "$(cat "$T/c2/a/f2.txt")" = "leftover" ] && [ -z "$(cd "$T/c2/a" && G stash list)" ]; then
  ok "② コミットしなかった変更が残っていても、やり直しで push できる（残した変更はそのまま）"
else ng "② コミットしなかった変更が残っていると push できない（11-03 の月次の落ち方）"; tail -5 "$T/c2/log"; fi

# ③ 追跡していないファイルが残ったまま remote が進んだ
setup c3
( cd "$T/c3/a" && printf 'mine\n' > f1.txt && G add -- f1.txt && G commit --quiet -m "mine: f1" && printf 'new\n' > untracked.txt ) >/dev/null 2>&1
remote_advance c3 f3.txt 'theirs'
if run_push c3 && remote_has c3 "mine: f1" && [ "$(cat "$T/c3/a/untracked.txt" 2>/dev/null)" = "new" ]; then
  ok "③ 追跡していないファイルが残っていても push できる（ファイルは残る）"
else ng "③ 追跡していないファイルが残っていると push できない"; tail -5 "$T/c3/log"; fi

# ④ 同じファイルを両方がコミットした（本当の衝突）→ 落ちる・片付いている
setup c4
( cd "$T/c4/a" && printf 'mine\n' > f1.txt && G add -- f1.txt && G commit --quiet -m "mine: f1" && printf 'leftover\n' > f2.txt ) >/dev/null 2>&1
remote_advance c4 f1.txt 'theirs'
if run_push c4; then ng "④ 本当の衝突なのに push が通った（自動で解決してはいけない）"
else
  a="$T/c4/a"
  if [ ! -d "$a/.git/rebase-merge" ] && [ ! -d "$a/.git/rebase-apply" ] \
     && [ "$(cd "$a" && G log -1 --format=%s)" = "mine: f1" ] && [ "$(cat "$a/f2.txt")" = "leftover" ] \
     && grep -q "rebase が解けない（衝突: f1.txt" "$T/c4/log" && ! remote_has c4 "mine: f1"; then
    ok "④ 本当の衝突は落ちる（衝突のファイルを名指し・rebase は片付いている・自分のコミットと残した変更はそのまま）"
  else ng "④ 落ちたあとの姿がおかしい"; tail -6 "$T/c4/log"; fi
fi

# ⑤ 残した変更と remote のコミットが同じファイル → コミットした成果は届く
setup c5
( cd "$T/c5/a" && printf 'mine\n' > f1.txt && G add -- f1.txt && G commit --quiet -m "mine: f1" && printf 'leftover\n' > f2.txt ) >/dev/null 2>&1
remote_advance c5 f2.txt 'theirs'
if run_push c5 && remote_has c5 "mine: f1" && remote_has c5 "remote: f2.txt"; then
  ok "⑤ 残した変更と remote が同じファイルでも、コミットした成果は届く"
else ng "⑤ 残した変更と remote が同じファイルだと push できない"; tail -6 "$T/c5/log"; fi

echo
if [ "$bad" -gt 0 ]; then echo "✗ ${bad}件——push のやり直しの道が壊れている（その月・その日の成果が main に届かなくなる）"; exit 1; fi
echo "✓ ccf_git_push: 5つの場合とも期待どおり"
