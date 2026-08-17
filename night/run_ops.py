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
- **鍵が無いステップは「実行した」と言わない**——`nokey` として別に数える（ルール7）。
- 実行後に **score_all を回して投下可の顔ぶれが変わっていないかを必ず出す**。
  変わったら「変わった」と言う（黙って変えない）。

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


def steps_from_workflow(wf):
    """ワークフローから (番号, 名前, run, env, timeout) を取り出す。**書き写さない**。"""
    try:
        import yaml
    except ImportError:
        print("✗ pyyaml が無い（pip install pyyaml）", file=sys.stderr)
        return []
    doc = yaml.safe_load(open(wf, encoding="utf-8"))
    out = []
    for job in (doc.get("jobs") or {}).values():
        for i, st in enumerate(job.get("steps") or [], 1):
            run = st.get("run")
            if not run:
                continue  # checkout / setup-python 等
            out.append({
                "n": i, "name": st.get("name") or f"step{i}", "run": run,
                "env": {k: v for k, v in (st.get("env") or {}).items()},
                "timeout": int(st.get("timeout-minutes", 0)) * 60 or None,
            })
    return out


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
                    help="走らせるワークフロー（既定 ops.yml）。fix.yml / gate0.yml も同じ器で回せる")
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
        miss = needed_keys(st)
        if miss:
            # ⚠ 鍵が無い＝「実行した」と言わない。多くのスクリプトは鍵無しでも
            #   何も壊さず終了する設計だが、それは**やっていない**のであって健全ではない。
            recs.append({"n": n, "name": name, "state": "nokey", "why": "鍵が無い: " + ",".join(miss)})
            print(f"  🔑 {n:2}. {name[:46]}  （鍵が無い: {','.join(miss)}）")
            continue
        if a.dry_run:
            recs.append({"n": n, "name": name, "state": "dry"})
            print(f"  ·  {n:2}. {name[:46]}")
            continue

        t0 = time.time()
        print(f"  ▶  {n:2}. {name[:46]} …", flush=True)
        try:
            p = subprocess.run(["bash", "-o", "pipefail", "-c", st["run"]], cwd=BASE,
                               capture_output=True, text=True,
                               timeout=st["timeout"] or a.timeout,
                               env={**os.environ, **{k: str(v) for k, v in st["env"].items()
                                                     if "secrets." not in str(v)}})
            dt = round(time.time() - t0, 1)
            tail = "\n".join((p.stdout or "").strip().splitlines()[-6:])
            if p.returncode == 0:
                recs.append({"n": n, "name": name, "state": "ok", "sec": dt, "tail": tail})
                print(f"     ✓ {dt}s")
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
    n_key = sum(1 for r in recs if r["state"] == "nokey")
    print("\n" + "-" * 74)
    print(f"実行 {n_ok} ／ 失敗 {n_fail} ／ **鍵が無くて未実行 {n_key}** ／ skip "
          f"{sum(1 for r in recs if r['state']=='skip')}")
    if n_fail:
        print("\n■ 失敗（黙って緑にしない）")
        for r in recs:
            if r["state"] in ("fail", "timeout"):
                print(f"   {r['n']:2}. {r['name'][:44]}  {r.get('err','timeout')[:160]}")

    out = {"generated": TODAY.isoformat(), "workflow": a.wf, "n_ok": n_ok, "n_fail": n_fail,
           "n_nokey": n_key, "steps": recs,
           "note": "ops.yml をこの場で実行した記録。手順は ops.yml から読む（書き写さない）。"
                   "鍵が無いステップは『実行した』と数えない"}
    if not a.dry_run:
        # ⚠ 名前は `wfrun_` を必ず前置する。実測で踏んだ——素朴に `{stem}_run.json` にしたら
        #   **run_gate0_local.py 自身の実行印 out/gate0_run.json を上書きした**（盤がそれを読む）。
        #   ワークフローが作る在庫と、この器が作る記録は**名前空間を分ける**。
        stem = a.wf.replace(".yml", "")
        with open(os.path.join(BASE, "out", f"wfrun_{stem}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
