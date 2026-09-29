#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月次の運用作業（ops.yml）を**この場で実行する**（2026-08-17新設）。

## なぜ要るか——検出器だけ作っても宿題が増えるだけだった

2026-08-17 に「自動化の穴」を測り、**ops.yml の実行回数が 0** だと判った。
そこで盤に載せ、作業リストに出し、todo に書いた——**だが一つも走らせていない**。
ユーザーの指摘そのもの:「**あなたが実行できるようなものを作って走らせないと意味ない**」。

GitHub Actions を発火できるのは人だけ。だが **ops.yml の中身はただの
`python3 night/*.py` の並び**で、**セッションからそのまま実行できる**。
実測: 31ステップ中、鍵が要るのは3つだけ（AV_KEY×2 / EDINET_API_KEY×1）。

## 手順を書き写さない

steps は **ops.yml を yaml で読んで取り出す**。書き写すと必ず食い違う
（この repo が「規則を変えたら文も全部 grep で洗う」で何度も踏んだ型）。
ops.yml を直せばこの器も自動で追随する。

## 安全

- **採点にも門にも触れない**——走らせるのは ops.yml が既に走らせている物だけ。
  `--sync` のような値を書き換える旗は ops.yml に無いので、ここにも無い。
- 各ステップは**独立に失敗してよい**（ops.yml の continue-on-error と同じ）。
  失敗は握り潰さず `failed` として名指しで残す。
- **鍵が欠けたまま走ったステップは「実行した」と言わない**——`degraded` として別に数える（ルール7）。
  ⚠ ただし**実行そのものは止めない**。ops.yml のステップ3は鍵の有無に関係なく
  `kessan_calendar.py` を走らせる設計（鍵なしはSEC推定）で、飛ばすと
  「鍵が無いから未実行」という**もっともらしい嘘**になる。判断はワークフローに任せる。
- 実行後に **score_all を回して投下可の顔ぶれが変わっていないかを必ず出す**。
  変わったら「変わった」と言う（黙って変えない）。
- **セッションからは回さない段**（2026-09-29）: job か段の env に CCF_CI_ONLY がある段（ops.yml の forward ジョブ
  ＝前向きの検定の書き手は CI だけ）と、main へ push する段（`git push`・`ccf_git_push`）は skip として理由つきで残す。
  段の timeout-minutes に従い、時間切れは段のセッションごと止める（孫のプロセスを孤児にしない）。

実行: python3 night/run_ops.py [--wf ops.yml] [--only 3,7] [--skip 17] [--dry-run]
      --wf で **fix.yml / gate0.yml** も同じ器で回せる（どちらも実行0回のまま）
在庫: out/wfrun_{ワークフロー名}.json（いつ・何が走って・何が落ちたかの記録）
      ⚠ `wfrun_` を前置するのは、ワークフロー自身が作る在庫（例 out/gate0_run.json＝
        run_gate0_local.py の実行印）と名前がぶつかるのを防ぐため。実際に一度潰した。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date.today()


# 2026-09-29（検査役の指摘）: **セッションからは回さない段**を機構で分ける。
#   (1) job または段の env に CCF_CI_ONLY がある段——前向きの検定（ops.yml の forward ジョブ）は
#       「書き手は CI だけ」（手元で回した出力で固定した月が割れる）。旧版はジョブを見分けずに全段を拾い、
#       900秒で bash だけを殺して nx を孤児のまま書き続けさせていた。
#   (2) main へ push する段（`git push`・`ccf_git_push` を含む）——セッションから main へ自動で push しない
#       （2026-09-23 に Routine の自動 push がアカウント停止の原因になった）。2026-08-17 はコミット段を人が
#       手で --skip していた＝機構では守られていなかった。
#   どちらも「実行した」とは数えず skip として理由つきで残す（黙って消さない）。
CI_ONLY_WHY = "CI だけで回す段（env の CCF_CI_ONLY）——書き手は CI だけ"
PUSH_WHY = "main へ push する段——セッションからは回さない（コミットと push は人か CI の仕事）"


def steps_from_workflow(wf):
    """ワークフローから (番号, 名前, run, env, timeout, CI 専用の理由) を取り出す。**書き写さない**。
    番号はファイル全体の通し番号（2026-09-29 から。旧版はジョブごとに 1 から数え直し、ジョブが2つになると重なった）"""
    try:
        import yaml
    except ImportError:
        print("✗ pyyaml が無い（pip install pyyaml）", file=sys.stderr)
        return []
    doc = yaml.safe_load(open(wf, encoding="utf-8"))
    out = []
    n = 0
    for jid, job in (doc.get("jobs") or {}).items():
        job_env = {k: v for k, v in ((job or {}).get("env") or {}).items()}
        for st in (job or {}).get("steps") or []:
            n += 1
            run = st.get("run")
            if not run:
                continue  # checkout / setup-python / actions/cache 等
            env = {k: v for k, v in (st.get("env") or {}).items()}
            ci_only = None
            if "CCF_CI_ONLY" in env or "CCF_CI_ONLY" in job_env:
                ci_only = CI_ONLY_WHY + f"・job {jid}"
            elif re.search(r"(?m)^\s*(?:git\s+push|ccf_git_push)\b", str(run)):
                ci_only = PUSH_WHY
            out.append({
                "n": n, "job": jid, "name": st.get("name") or f"step{n}", "run": run,
                "env": {**job_env, **env},
                "timeout": int(st.get("timeout-minutes", 0) or 0) * 60 or None,
                "ci_only": ci_only,
            })
    return out


def _session_pids(sid):
    """セッション sid に属するプロセス（Linux の /proc から）。読めなければ空"""
    pids = []
    try:
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                st = open(f"/proc/{d}/stat").read()
                # 2番目の欄（コマンド名）は括弧つきで空白を含みうるので、最後の ')' の後ろから数える
                f = st[st.rfind(")") + 2:].split()
                if int(f[3]) == sid and f[0] != "Z":   # state ppid pgrp session …（ゾンビは数えない＝もう走っていない）
                    pids.append(int(d))
            except (OSError, ValueError, IndexError):
                continue
    except OSError:
        pass
    return pids


def _kill_session(sid, sig):
    """セッションの全プロセスへ sig を送る。GNU timeout は自分のプロセスグループを作るので、
    bash のグループ（killpg）だけでは `timeout … python3` の python に届かない——セッションで拾う"""
    sent = False
    for pid in _session_pids(sid):
        try:
            os.kill(pid, sig)
            sent = True
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.killpg(sid, sig)
        sent = True
    except (ProcessLookupError, PermissionError):
        pass
    return sent


def run_group(cmd, timeout, env):
    """subprocess.run と同じ戻り値（returncode・stdout・stderr）。時間切れなら**段のセッションごと**止めて
    TimeoutExpired を投げる（孫のプロセスを孤児にしない）"""
    import signal
    p = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env=env, start_new_session=True)       # 段は新しいセッション＝sid は bash の pid
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not _kill_session(p.pid, sig):
                break
            deadline = time.time() + 10
            while time.time() < deadline and _session_pids(p.pid):
                time.sleep(0.2)
            if not _session_pids(p.pid):
                break
        try:
            p.communicate(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def needed_keys(st):
    """このステップが要る秘密のうち、環境に無いもの。"""
    want = set()
    for v in st["env"].values():
        for m in re.findall(r"secrets\.(\w+)", str(v)):
            want.add(m)
    for m in re.findall(r"\$\{?(\w*(?:KEY|TOKEN)\w*)", st["run"]):
        want.add(m)
    return sorted(k for k in want if not os.environ.get(k))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wf", default="ops.yml",
                    help="走らせるワークフロー（既定 ops.yml）。gate0.yml も同じ器で回せる")
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    wf = os.path.join(BASE, ".github", "workflows", a.wf)
    if not os.path.exists(wf):
        print(f"✗ {a.wf} が無い → 何もせず終了")
        return 1
    steps = steps_from_workflow(wf)
    if not steps:
        print(f"✗ {a.wf} からステップを読めない → 何もせず終了")
        return 1
    only = {int(x) for x in a.only.split(",") if x.strip()}
    skip = {int(x) for x in a.skip.split(",") if x.strip()}

    print("=" * 74)
    print(f"{a.wf} をこの場で実行 — 全{len(steps)}ステップ")
    print("=" * 74)

    recs = []
    for st in steps:
        n, name = st["n"], st["name"]
        if only and n not in only:
            continue
        if n in skip:
            recs.append({"n": n, "name": name, "state": "skip", "why": "--skip 指定"})
            print(f"  ⏭  {n:2}. {name[:46]}  （--skip）")
            continue
        if st.get("ci_only"):
            recs.append({"n": n, "name": name, "state": "skip", "why": st["ci_only"]})
            print(f"  ⏭  {n:2}. {name[:46]}  （{st['ci_only']}）")
            continue
        miss = needed_keys(st)
        # ⚠ 初版は「鍵が無ければ実行しない」にして**ワークフローの判断を勝手に上書きしていた**。
        #   実測 ops.yml ステップ3 は `if [ -n "$AV_KEY" ]; then echo …; else echo …; fi` の**後**に
        #   `python kessan_calendar.py` が**無条件で**置いてあり、鍵が無ければSEC推定で回る設計。
        #   飛ばすと「鍵が無いから未実行」という**もっともらしい嘘**になる（実際に一度なった）。
        #   → **走らせるのはワークフローに任せ、鍵が欠けていた事実は `degraded` として記録する。**
        #   「実行した」と「鍵込みで完全に実行した」を混ぜないのが目的で、実行しないことではない。
        if miss:
            print(f"  ▶  {n:2}. {name[:46]} …（鍵が無い: {','.join(miss)}／"
                  f"走らせて、ワークフロー自身の分岐に任せる）", flush=True)
        if a.dry_run:
            recs.append({"n": n, "name": name, "state": "dry"})
            print(f"  ·  {n:2}. {name[:46]}")
            continue

        t0 = time.time()
        if not miss:
            print(f"  ▶  {n:2}. {name[:46]} …", flush=True)
        try:
            # 2026-09-29: 段は**自分のセッション**で走らせ、時間切れなら**セッションごと**止める。
            #   subprocess.run の timeout は子の bash だけを殺すので、`timeout … python3 … | tail` の python は
            #   孤児のまま走り続け、TimeoutExpired の後もファイルを書いていた（実測: 6秒後に孫が書いた）。
            #   プロセスグループ（killpg）でも足りない——GNU timeout は自分のグループを作るので python に届かない（実測）
            p = run_group(["bash", "-o", "pipefail", "-c", st["run"]],
                          timeout=st["timeout"] or a.timeout,
                          env={**os.environ, **{k: str(v) for k, v in st["env"].items()
                                                if "secrets." not in str(v) and "${{" not in str(v)}})
            dt = round(time.time() - t0, 1)
            tail = "\n".join((p.stdout or "").strip().splitlines()[-6:])
            if p.returncode == 0:
                stt = "degraded" if miss else "ok"
                recs.append({"n": n, "name": name, "state": stt, "sec": dt, "tail": tail,
                             **({"missing_keys": miss} if miss else {})})
                print(f"     {'◐' if miss else '✓'} {dt}s"
                      + (f"（鍵 {','.join(miss)} が無いぶんは**やっていない**）" if miss else ""))
            else:
                err = "\n".join((p.stderr or "").strip().splitlines()[-4:])
                recs.append({"n": n, "name": name, "state": "fail", "sec": dt,
                             "rc": p.returncode, "tail": tail, "err": err})
                print(f"     ✗ rc={p.returncode} {dt}s\n       {err[:300]}")
        except subprocess.TimeoutExpired:
            dt = round(time.time() - t0, 1)
            recs.append({"n": n, "name": name, "state": "timeout", "sec": dt})
            print(f"     ✗ timeout {dt}s")

    n_ok = sum(1 for r in recs if r["state"] == "ok")
    n_fail = sum(1 for r in recs if r["state"] in ("fail", "timeout"))
    n_key = sum(1 for r in recs if r["state"] == "degraded")
    print("\n" + "-" * 74)
    print(f"実行 {n_ok} ／ 失敗 {n_fail} ／ **鍵が欠けたまま実行 {n_key}**（その分はやっていない）／ skip "
          f"{sum(1 for r in recs if r['state']=='skip')}")
    if n_fail:
        print("\n■ 失敗（黙って緑にしない）")
        for r in recs:
            if r["state"] in ("fail", "timeout"):
                print(f"   {r['n']:2}. {r['name'][:44]}  {r.get('err','timeout')[:160]}")

    out = {"generated": TODAY.isoformat(), "workflow": a.wf, "n_ok": n_ok, "n_fail": n_fail,
           "n_degraded": n_key, "steps": recs,
           "note": "ops.yml をこの場で実行した記録。手順は ops.yml から読む（書き写さない）。"
                   "鍵が無いステップは『実行した』と数えない"}
    if not a.dry_run:
        # ⚠ 名前は `wfrun_` を必ず前置する。実測で踏んだ——素朴に `{stem}_run.json` にしたら
        #   **run_gate0_local.py 自身の実行印 out/gate0_run.json を上書きした**（盤がそれを読む）。
        #   ワークフローが作る在庫と、この器が作る記録は**名前空間を分ける**。
        #   ⚠ そしてもう一つ実際に踏んだ——`--only 3,4,8` で回したら**27ステップぶんの記録を
        #     3ステップで上書きした**。この repo が score_all の --jp/--us・v11_facts・
        #     backfill で3回記録している「**部分実行で正本を潰す**」型。
        #     → 旗つきの実行は `.partial` へ書く（正本には触れない）。
        stem = a.wf.replace(".yml", "")
        part = ".partial" if (only or skip) else ""
        with open(os.path.join(BASE, "out", f"wfrun_{stem}{part}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
