#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/log_review_run.py — **日次の門2審査 Routine が「走った証拠」を repo に残す**（2026-08-11新設）

■ なぜ要るか（実害を踏んでから作っている）
  2026-08-11 の試運転で、Routine 起動のセッションが **29分・出力9万トークン走ってから、
  リポジトリに痕跡を一つも残さずに終わった**（コミット無し・ブランチ無し・PR無し）。
  しかも **Routine が起こしたセッションはコード一覧に表示されない**（トリガー発火のものは既定で除外）。
  ＝報告は一覧に出ない場所の中にしか無く、ユーザーは「どこにもない」状態になった。

  これは事故ではなく**手順書どおりの挙動**だった——
    「待ち行列が空なら一行で終える（何も作らない）」
    「SECが落ちていたら一行報告して何も作らずに終える」
  つまり**静かに終わる経路が、どれも外から見えない**。すると次が起きる:

      **Routine が明日から毎日何もしなくなっても、誰も気づけない。**

  回転盤(ops_status)を作った理由——「回っていない作業が黙って止まるのが最悪。
  止まっていること自体を毎日見えるようにする」——と正面から矛盾していた。
  PRが出た日は見えるが、**PRが出ない日こそ見えなければならない**（それが止まった日と区別できないから）。

■ 何をするか
  `out/review_runs.json` に **1回1行**を追記するだけ。判定にも採点にも一切使わない。
      date / at(UTC) / outcome / n(納品検査を通した社数) / tickers / pr / note / session
  これで **PRが無い日も「なぜ無いか」が git に残る**。
  回転盤は最新の date を見て「毎営業日・期限4日」で裁く＝止まれば🔔イベントタブが赤くなる。

■ --push が「ここだけ main へ直接書いてよい」理由と、その安全装置
  手順書は **main へ直接コミットしない（PRを作ってマージは人）** を絶対の約束にしている。
  これは**審査結果（パック）**についての約束で、人の目を通さずに台帳が動くのを防ぐためのもの。
  一方この走行ログは審査結果ではなく**「走った／走らなかった」の事実**で、
  PRが出ない日にこそ要る＝PR経由では原理的に残せない。

  そこで**ログだけは main へ直接**書けるようにしたが、**抜け道にならないよう構造で縛った**——
  `--push` は作業ツリーを一切使わず、git の低レベルコマンドで
  **「origin/main のツリー ＋ out/review_runs.json だけを差し替えた木」**を組んでコミットする。
      hash-object → 一時index に read-tree → update-index（このパスだけ）→ write-tree → commit-tree → push
  ＝**このツールでは out/review_runs.json 以外の1バイトも main へ送れない。**
  審査中のブランチに何が積まれていようと関係ない（`HEAD:main` を押さないので巻き込まない）。
  競合したら origin/main を取り直して積み直す（追記なので何度でも安全）。

使い方（Routine の最後に必ず1回）:
  python3 night/log_review_run.py --outcome pr    --n 3 --tickers SAP,ETN,6920 --pr 159 --push
  python3 night/log_review_run.py --outcome empty --note "待ち行列が空" --push
  python3 night/log_review_run.py --outcome limit --n 2 --tickers SAP,ETN --note "セッション上限" --push
  python3 night/log_review_run.py                      # 引数なし＝台帳を読むだけ
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = "out/review_runs.json"
PATH = os.path.join(BASE, REL)

# 終わり方の語彙。**「何も起きなかった」を一語にまとめない**——
#   待ち行列が空(empty)と、SECが落ちていた(source_down)と、上限で止まった(limit)は
#   同じ「PR無し」でも意味がまるで違う。区別が消えると、この台帳が繰り返し潰してきた
#   「測っていない」と「測って問題なし」の取り違えを、運用の側で作ることになる。
OUTCOMES = {
    "pr":          "PRを作った",
    "empty":       "待ち行列が空＝審査待ちなし",
    "limit":       "セッション上限で打ち切り",
    "source_down": "SEC/EDINETが不通",
    "discarded":   "納品検査FAILで全部捨てた",
    "error":       "その他の失敗",
    # このログが無かった日を後から埋めるための語。**「何も無かった」と書いてはいけない**
    #   ——外から判別できないだけで、空振りだったのか止まったのかは分からない（ルール7の親戚）。
    "unknown":     "外から判別できない",
}

NOTE = ("日次の門2審査 Routine の走行ログ。**判定にも採点にも一切使わない。** "
        "PRが出ない日も「なぜ出なかったか」を残すためのもの——"
        "Routine 起動のセッションはコード一覧に出ないので、"
        "これが無いと『毎日何もしていない』と『毎日ちゃんと空振りしている』を区別できない。"
        "回転盤(ops_status)が最新の date を毎営業日・期限4日で裁く。"
        "追記は night/log_review_run.py --push（このファイル以外は構造上pushできない）。")


def git(*args, env=None, check=True):
    r = subprocess.run(["git"] + list(args), cwd=BASE, capture_output=True,
                       text=True, env=env, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} → {r.returncode}\n{r.stderr.strip()}")
    return r.stdout.strip()


def load(text=None):
    """台帳を読む。壊れていても**捨てない**（読めない=空、で上書きすると履歴が消える）。"""
    raw = text
    if raw is None:
        try:
            raw = open(PATH, encoding="utf-8").read()
        except Exception:
            raw = ""
    if not raw.strip():
        return {"generated": None, "note": NOTE, "runs": []}
    try:
        d = json.loads(raw)
    except Exception as e:
        raise SystemExit(f"✗ {REL} が壊れている（{e}）。手で直すこと——"
                         f"機械が空で上書きすると走行の履歴が消える")
    if not isinstance(d.get("runs"), list):
        raise SystemExit(f"✗ {REL} の runs が配列でない")
    d["note"] = NOTE
    return d


def remote_text():
    """origin/main 側の中身を取る（無ければ空）。ローカルの古い写しに追記しないため。"""
    try:
        git("fetch", "-q", "origin", "main")
        return git("show", f"FETCH_HEAD:{REL}")
    except Exception:
        return ""


def build_commit(base, msg, src=None):
    """origin/main のツリー ＋ このファイルだけを差し替えた commit を作る（push はしない）。"""
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, "idx"))
        git("read-tree", base, env=env)
        blob = git("hash-object", "-w", src or PATH)
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{REL}", env=env)
        tree = git("write-tree", env=env)
    return git("commit-tree", tree, "-p", base, "-m", msg)


def dry_run(msg, d):
    """**安全性の証明を回せる形にしておく**——作られる commit が本当に1ファイルしか触らないか。
    副作用の無い経路は失敗しても静かなので、性質は文章ではなく実測で示す。
    ⚠ 検査そのものが台帳を汚さないよう、**一時ファイルへ書いて**それを対象にする。"""
    base = git("rev-parse", "FETCH_HEAD")
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "review_runs.json")
        write(dict(d), tmp)
        c = build_commit(base, msg, src=tmp)
    changed = [x for x in git("diff", "--name-only", base, c).splitlines() if x]
    print(f"■ --dry-run: {base[:7]} → {c[:7]} が触るファイル {len(changed)}件")
    for f in changed:
        print(f"   {'✓' if f == REL else '✗'} {f}")
    ok = changed == [REL]
    print("✓ このコミットは out/review_runs.json 以外を1バイトも動かさない" if ok
          else "✗ 想定外のファイルが混ざっている——push してはいけない")
    return ok


def push_only_this_file(msg):
    """**out/review_runs.json だけ**を main へ push する。他は構造的に混ざらない。"""
    for attempt in range(4):
        base = git("rev-parse", "FETCH_HEAD")
        commit = build_commit(base, msg)
        r = subprocess.run(["git", "push", "origin", f"{commit}:main"],
                           cwd=BASE, capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            print(f"■ main へ追記 {commit[:7]}（{REL} のみ）")
            return True
        print(f"  ▲ push 失敗（{attempt+1}/4）— origin/main を取り直して積み直す")
        # 競合＝他のコミットが入っただけ。相手の中身の上へ自分の1行を積み直す（追記なので安全）
        txt = remote_text()
        d = load(txt)
        d["runs"] = merge_runs(d["runs"], PENDING)
        write(d)
    print("  ✗ push できなかった。out/review_runs.json は手元にあるので手でコミットすること")
    return False


PENDING = []


def merge_runs(runs, new):
    """同じ (date, at) は二重に積まない＝何度回しても同じ結果（再試行に強い）。"""
    seen = {(r.get("date"), r.get("at")) for r in runs}
    for e in new:
        if (e.get("date"), e.get("at")) not in seen:
            runs.append(e)
    runs.sort(key=lambda r: (r.get("date") or "", r.get("at") or ""))
    return runs


def write(d, path=None):
    d["generated"] = datetime.date.today().isoformat()
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def show(d):
    runs = d.get("runs") or []
    print(f"■ 日次 門2審査の走行ログ {len(runs)}件")
    if not runs:
        print("  （まだ1件も無い）")
        return
    print(f"{'日付':<11}{'終わり方':<13}{'社数':>4}  銘柄 / 備考")
    for r in runs[-30:]:
        t = ",".join(r.get("tickers") or []) or "—"
        pr = f"PR#{r['pr']} " if r.get("pr") else ""
        print(f"{r.get('date',''):<11}{OUTCOMES.get(r.get('outcome'), r.get('outcome','')):<13}"
              f"{r.get('n', 0):>4}  {pr}{t}"
              + (f" — {r['note']}" if r.get("note") else ""))
    # **空振りが続いていることを黙って見過ごさない**（止まっているのと見分けが付かないため）
    tail = [r for r in runs[-5:] if r.get("outcome") != "pr"]
    if len(tail) >= 3:
        print(f"\n⚠ 直近5回のうち {len(tail)} 回がPR無し。"
              f"待ち行列が本当に空か `python3 night/enqueue_reaudit.py` で確かめること")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcome", choices=sorted(OUTCOMES))
    ap.add_argument("--n", type=int, default=0, help="納品検査まで通した社数")
    ap.add_argument("--tickers", default="", help="カンマ区切り")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--note", default="")
    ap.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""))
    ap.add_argument("--push", action="store_true", help="out/review_runs.json だけを main へ push")
    ap.add_argument("--dry-run", action="store_true",
                    help="push せず、作られるコミットが1ファイルしか触らないことを実測で示す")
    a = ap.parse_args()

    if not a.outcome:
        show(load())
        return 0

    now = datetime.datetime.now(datetime.timezone.utc)
    entry = {"date": now.date().isoformat(), "at": now.strftime("%H:%M:%SZ"),
             "outcome": a.outcome, "n": a.n,
             "tickers": [t.strip().upper() for t in a.tickers.split(",") if t.strip()]}
    if a.pr:
        entry["pr"] = a.pr
    if a.note:
        entry["note"] = a.note[:300]
    if a.session:
        entry["session"] = a.session
    PENDING.append(entry)

    if a.push or a.dry_run:
        # **remote と手元の union を取る**。remote だけを錨にすると、
        #   前回 push に失敗して手元にしか無い行を黙って捨てる（ルール7の親戚——
        #   「取れなかった」を「無かった」と読まない）。追記なので union が常に正しい。
        d = load(remote_text())
        d["runs"] = merge_runs(d.get("runs") or [], (load(None).get("runs") or []))
    else:
        d = load()
    d["runs"] = merge_runs(d.get("runs") or [], PENDING)
    if not a.dry_run:
        write(d)
    show(d)

    if a.push or a.dry_run:
        tail = f"（{a.n}社" + (f"・PR#{a.pr}" if a.pr else "") + "）"
        msg = (f"門2審査の走行ログ {entry['date']}：{OUTCOMES[a.outcome]}{tail}\n\n"
               f"night/log_review_run.py が out/review_runs.json だけを追記したもの。"
               f"判定・採点・台帳には一切触れていない。")
        remote_text()          # FETCH_HEAD を作る
        if a.dry_run:
            return 0 if dry_run(msg, d) else 1
        push_only_this_file(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
