#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ワークフローが「作った答えを捨てる」形になっていないかを検査する（2026-08-17新設）

  見るのは2つ: **(1) git add の巻き添え** と **(2) main への素の git push**。
  どちらも「計算は正しく走ったのに成果だけが残らない」という同じ壊れ方をする。

■ なぜ要るか
  この repo は「作った答えを捨てる」型の事故を **6回** 踏んでいる:
    1. ci.yml が out/score_all.json を add していなかった
    2. ci.yml が out/pending.json を add していなかった（第四の関門が読む表）
    3. market.yml が out/validate_fail.json を add していなかった
    4. ops.yml が out/*_gate_pack.json を add していなかった
    5. ops.yml が out/*_gate_input.json / _hits.txt / fetch_run.json を add していなかった
    6. **ops.yml の38パスの add に実在しないパスが1つ混じり、38パス全部が捨てられていた**
    7. **market.yml が素の `git push` で弾かれ、70ファイルのコミットがまるごと消えた**
       （2026-08-14 と 08-17 の2営業日連続。`! [rejected] main -> main (fetch first)`）

  6回目が質的に違う: 1〜5は「一覧への足し忘れ」だが、6は**一覧に正しく入っているのに
  隣の1つが巻き添えにする**。`git add a b c` は1つでもパスが実在しないと
  **全体が失敗して1つもステージしない**（実証済み）。そして末尾の `2>/dev/null || true` が
  エラーも終了コードも消すので、**完全に無音**で起きる。

■ この検査が見るもの（2つ）
  (A) `ccf_git_add` を通していない多パスの add で、実在しないパスがあるもの → **落とす**
      （巻き添えが今まさに起きている）
  (B) `ccf_git_add` を通しているものの、実在しないパス → **警告のみ**
      （巻き添えは起きないが、一覧が陳腐化している合図）

■ 見ないもの（意図的）
  - 単一パスの add（巻き添えのしようがない）
  - `git add .` / `git add -A <dir>`（ディレクトリは常に在る）
  - night/log_review_run.py の低レベル経路（作業ツリーを使わないので git add を通らない）

■ 限界（正直に）
  実行時にだけ生成されるファイル（ジョブの前段が作るもの）は、静的検査では「実在しない」に見える。
  だから **(A)で落とすのは ccf_git_add を通していない行だけ**にしてある——
  ccf_git_add を通していれば実行時に無くても巻き添えは起きないので、警告で足りる。

■ (2) main への素の `git push`
  cron は10〜40分ふつうに遅れるので、**時間をずらしても衝突は防げない**（実測: market.yml は
  21:52 / 22:20 と日によって始まりが動き、ops.yml と正面衝突した）。
  `night/git_push_safe.sh` の `ccf_git_push`（rebase して再試行・衝突したら名指しで落とす）を
  通していない `git push` を **落とす**。⚠ `git push -u origin <branch>`（PRブランチ）は対象外
  ——新しいブランチなので衝突しない。

使い方: python3 night/check_workflow_add.py [--json]
"""
import glob
import json
import os
import re
import sys

WF = ".github/workflows"


def paths_of(cmd: str):
    """add コマンドからパスらしいトークンだけを採る（旗・リダイレクト・継続行は除く）"""
    out = []
    for t in cmd.split():
        if t in ("git", "add", "ccf_git_add", "true", "||", "&&", "--", "\\"):
            continue
        if t.startswith(("-", "2>", "1>", ">", "#")):
            continue
        out.append(t.strip("'\""))
    return out


def missing(paths):
    miss = []
    for p in paths:
        if any(c in p for c in "*?["):
            if not glob.glob(p):
                miss.append(p)
        elif not os.path.exists(p):
            miss.append(p)
    return miss


def scan():
    rows = []
    for f in sorted(glob.glob(f"{WF}/*.yml")):
        src = open(f, encoding="utf-8").read().split("\n")
        i = 0
        while i < len(src):
            s = src[i].strip()
            if not re.match(r"^(git add|ccf_git_add)\b", s):
                i += 1
                continue
            # 継続行(\)を結合する
            joined, j = s, i
            while joined.rstrip().endswith("\\") and j + 1 < len(src):
                j += 1
                joined = joined.rstrip()[:-1] + " " + src[j].strip()
            safe = joined.startswith("ccf_git_add")
            ps = paths_of(joined)
            # ディレクトリ丸ごと(-A dir)や単一パスは巻き添えのしようがない
            if len(ps) >= 2:
                m = missing(ps)
                if m:
                    rows.append({"file": f, "line": i + 1, "safe": safe,
                                 "n_paths": len(ps), "missing": m})
            i = j + 1
    return rows


def scan_push():
    """main へ素の `git push` をしている行を拾う（PRブランチへの push は対象外）"""
    bad = []
    for f in sorted(glob.glob(f"{WF}/*.yml")):
        for i, ln in enumerate(open(f, encoding="utf-8").read().split("\n")):
            s = ln.strip()
            if not re.match(r"^git push\b", s):
                continue
            if re.search(r"-u\s+origin\s+", s):     # PRブランチ＝衝突しない
                continue
            bad.append({"file": f, "line": i + 1, "cmd": s})
    return bad


def main():
    rows = scan()
    pushes = scan_push()
    bad = [r for r in rows if not r["safe"]]
    warn = [r for r in rows if r["safe"]]
    if "--json" in sys.argv:
        json.dump({"bad": bad, "warn": warn, "raw_push": pushes},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 1 if (bad or pushes) else 0

    print("■ ワークフローの git add の巻き添え検査")
    if not rows:
        print("  ✓ 実在しないパスは無い（多パスの add すべて）")
    for r in bad:
        print(f"  ✗ {r['file']}:{r['line']}  {r['n_paths']}パスの `git add` に実在しないパス "
              f"{len(r['missing'])}件 → **この行は1つもステージしない**")
        for m in r["missing"]:
            print(f"      ✗ {m}")
        print("      → `. night/git_add_safe.sh` を読んで `ccf_git_add` に替えるか、パスを直すこと")
    for r in warn:
        print(f"  ⚠ {r['file']}:{r['line']}  ccf_git_add の一覧に実在しないパス {len(r['missing'])}件"
              f"（巻き添えは起きないが一覧が古い可能性）")
        for m in r["missing"]:
            print(f"      ⚠ {m}")

    print("■ main への push が rebase 再試行を通しているか")
    if not pushes:
        print("  ✓ 素の `git push` は無い（すべて ccf_git_push）")
    for r in pushes:
        print(f"  ✗ {r['file']}:{r['line']}  素の `git push`"
              " → remote が進んだだけでコミットがまるごと捨てられる")
        print("      → `. night/git_push_safe.sh` を読んで `ccf_git_push` に替えること")
    return 1 if (bad or pushes) else 0


if __name__ == "__main__":
    sys.exit(main())
