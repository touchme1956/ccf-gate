#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/wf_watch.py — **走っているワークフローの進捗を一目で出す**（2026-08-12新設）

■ なぜ要るか
  この repo は 26班・42班といった大きな読解ワークフローを回すが、
  進捗を見る手段が「人が聞く」しか無かった。**待っているのか止まっているのかが判らない**のが
  いちばん困る（回転盤を作った理由と同じ——回っていない作業が黙って止まるのが最悪）。

■ ⚠ この道具は判定を一つも持たない
  journal.jsonl を数えるだけ。Ω・採点式・関門・売却規律には一切触れない。
  **被覆の速報は出すが、ρ も p も出さない**——事前登録の検定は
  読解が全部終わってから `retro_pillars_test.py` が一度だけ下す。
  ここで途中経過の相関を覗くと、事前登録の意味が消える。

使い方:
  python3 night/wf_watch.py              最新のワークフロー
  python3 night/wf_watch.py --id wf_xxx  特定のラン
  python3 night/wf_watch.py --watch      10秒ごとに更新（Ctrl-Cで止める）
"""
import argparse, glob, json, os, sys, time, datetime

HOME = os.path.expanduser("~/.claude/projects")


def latest_dir(run_id=None):
    pats = glob.glob(os.path.join(HOME, "*", "*", "subagents", "workflows", "wf_*"))
    if not pats:
        return None
    if run_id:
        m = [p for p in pats if os.path.basename(p).startswith(run_id)]
        return m[0] if m else None
    return max(pats, key=lambda p: os.path.getmtime(p))


def read(d):
    p = os.path.join(d, "journal.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass          # 書き込み途中の行は飛ばす（次の実行で読める）
    return out


def bar(done, total, w=28):
    if not total:
        return "…"
    f = int(w * done / total)
    return "█" * f + "░" * (w - f)


def show(d):
    ev = read(d)
    started = sum(1 for e in ev if e.get("type") == "started")
    res = [e for e in ev if e.get("type") == "result"]
    # 段の判別は**返り値の形**で行う（ラベルに依存しない＝スクリプトを書き換えても壊れない）
    rd = [e for e in res if isinstance(e.get("result"), dict) and "rows" in e["result"]]
    vf = [e for e in res if isinstance(e.get("result"), dict) and "verdicts" in e["result"]]
    other = len(res) - len(rd) - len(vf)
    mt = os.path.getmtime(os.path.join(d, "journal.jsonl"))
    idle = time.time() - mt
    ag = len(glob.glob(os.path.join(d, "agent-*.jsonl")))

    print(f"■ {os.path.basename(d)}")
    print(f"  起動 {started}班 ／ 返り {len(res)}班（読解 {len(rd)} ／ 反証 {len(vf)}"
          + (f" ／ その他 {other}" if other else "") + f"）／ エージェント記録 {ag}本")
    if rd:
        n = sum(len(e["result"].get("rows") or []) for e in rd)
        print(f"  読解 [{bar(len(rd), max(len(rd), started // 2 or len(rd)))}] {len(rd)}班・{n}社")
        cov = {k: 0 for k in ("rep", "dur", "dom", "moatW")}
        for e in rd:
            for r in e["result"].get("rows") or []:
                for k in cov:
                    if r.get(k) is not None:
                        cov[k] += 1
        print("  被覆(速報・判定ではない): " + " / ".join(
            f"{k} {v}({v/max(n,1):.0%})" + ("✓150" if k in ("rep", "dur") and v >= 150 else "")
            for k, v in cov.items()))
    if vf:
        nv = sum(len(e["result"].get("verdicts") or []) for e in vf)
        tot = len(rd) or len(vf)
        print(f"  反証 [{bar(len(vf), tot)}] {len(vf)}/{tot}班・判定 {nv}件")
    print(f"  最終更新 {datetime.datetime.fromtimestamp(mt):%H:%M:%S}"
          f"（{int(idle)}秒前）")

    # ★**「遅い」と「死んでいる」を区別する**（2026-08-12に実害を踏んで追加）
    #   実測: 26班の読解が終わって反証3班まで進んだところで、**セッションが中断されて
    #   ワークフローが死んだ**（私が次の指示を受けた瞬間）。ところが journal は
    #   **ただ書き込みが止まるだけ**で、外からは「重い班が走っている」と区別が付かなかった。
    #   ＝この repo が最も嫌う「静かに止まる」型。中断の痕跡は agent-*.jsonl の末尾に残るので、
    #   **止まっているように見えたら中身を見て理由まで言う**。
    #   ⚠**中断の痕跡だけで鳴らしてはいけない**（この器を作った当日に自分で誤検出した）——
    #     再開すると死んだ班は re-launch されるが、**古い agent-*.jsonl は残ったまま**なので、
    #     痕跡は永久に見つかる。動いている最中に「死んでいる」と鳴る警報は、
    #     鳴りすぎる警報＝鳴らないのと同じ。**止まっていること(idle)と併せて初めて鳴らす。**
    dead = [os.path.basename(f).split("agent-")[1][:8]
            for f in glob.glob(os.path.join(d, "agent-*.jsonl"))
            if "Request interrupted by user" in open(f, encoding="utf-8", errors="ignore").read()[-4000:]]
    run_id = os.path.basename(d)
    IDLE = 300
    if idle > IDLE and dead:
        print(f"  ⚠⚠ **止まっている。しかも中断の痕跡が {len(dead)}本**（{' '.join(dead)}）"
              "＝遅いのではなく**死んでいる**")
        print(f"     → 再開: Workflow({{scriptPath: …, resumeFromRunId: '{run_id}'}}) "
              "／完了済みの班はキャッシュから即返るので読み直しは起きない")
    elif idle > IDLE:
        print("  ⚠ 5分以上 動きがない。中断の痕跡は無いので**重い班が走っている**可能性が高いが、"
              "さらに伸びるなら journal と agent-*.jsonl の末尾を見ること")
    elif dead:
        print(f"  ・過去に中断された班の痕跡 {len(dead)}本（{' '.join(dead)}）"
              "——**いまは動いているので再開済み**。痕跡は消えないので数だけ出す")
    # ⚠ 完了の判定は「返りが起動と同数」だけでは足りない（次の段がまだ起動していない場合がある）
    if len(res) == started and idle > 60 and not dead:
        print("  → 起動した班はすべて返っている。次の段が無ければ完了")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--every", type=int, default=10)
    a = ap.parse_args()
    d = latest_dir(a.id)
    if not d:
        sys.exit("走っているワークフローが見つからない")
    while True:
        if a.watch:
            print("\033[2J\033[H", end="")
        show(d)
        if not a.watch:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
