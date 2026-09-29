#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前向きの検定の「実行の印」を残す（2026-09-29新設・検査役の指摘「10月の nx は全部か無しか」から）。

## なぜ要るか
前向きの検定の道具（night/mw_forward.py・night/nx_forward.py＝凍結）は、最後にまとめて出力を書く。
だから**落ちた・時間切れの実行は何も残さない**——盤（night/ops_status.py）は出力の generated しか見ないので、
印が無いと 40日の期限（次の定期実行の約9〜12日後）まで誰も気づけない。とくに 10月の nx は国内株式の投信
約770本の基準価額を取りに行き、時間切れに当たると F3 以外の月も含めて8本すべてが進まない。

ops.yml の forward ジョブが段ごとに、始めに `started`、終わりに結果を out/forward_run.json の runs[群] へ書き、
結果と同じコミットに載せる。段ごと殺されたら `started` のまま残る＝「途中で止まった」と読める。
盤は ops_status.forward_watch の (d) でこれを読む（出力の generated より新しい失敗の印があれば ⚠）。

## この器が守っている作法
- **判定・採点・配分には使わない**（読むのは ops_status の見張りだけ）
- 書くのは自分の群の行だけ（他の群の行は触らない）。書き込みは一時ファイル＋os.replace（途中で切れても壊れない）
- 書けなくても段を落とさない（終了コード 0）——印のために本体の結果を捨てない。書けなかったことは標準出力に出す

使い方: python3 night/forward_run_mark.py <mw|nx> <started|auto|ok|failed|timeout|frozen|broken_output> [終了コード] [秒]
  auto は終了コードから決める: 0→ok ／ 124（timeout コマンドが止めた）→timeout ／ それ以外→failed
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(BASE, "out", "forward_run.json")
GROUPS = ("mw", "nx")
OUTCOMES = ("started", "ok", "failed", "timeout", "frozen", "broken_output")


def main(argv):
    if len(argv) < 3 or argv[1] not in GROUPS or argv[2] not in OUTCOMES + ("auto",):
        print(__doc__.strip().splitlines()[-2])
        return 2
    group, outcome = argv[1], argv[2]
    rc = argv[3] if len(argv) > 3 else None
    sec = argv[4] if len(argv) > 4 else None
    if outcome == "auto":
        outcome = "ok" if str(rc) == "0" else ("timeout" if str(rc) == "124" else "failed")
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        doc = json.load(open(PATH, encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("runs"), dict):
            raise ValueError("形が違う")
    except Exception:  # noqa: BLE001  読めない・無い → 作り直す（他の群の行は失うが、印は補助の見張りなので段を止めない）
        doc = {"runs": {}}
    doc["role"] = ("前向きの検定（mw_forward・nx_forward）の最後の実行の印。ops.yml の forward ジョブが段ごとに書き、"
                   "night/ops_status.py の見張り (d) が読む。判定・採点・配分には不使用")
    prev = doc["runs"].get(group) if isinstance(doc["runs"].get(group), dict) else {}
    row = {"date": now.strftime("%Y-%m-%d"), "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "outcome": outcome,
           "trigger": os.environ.get("GITHUB_EVENT_NAME") or "manual",
           "run_id": os.environ.get("GITHUB_RUN_ID") or None}
    if rc is not None:
        row["rc"] = rc
    if sec is not None:
        try:
            row["sec"] = int(float(sec))
        except ValueError:
            pass
    # 始めの印（started）の時刻を結果の行にも残す＝段がどれだけ走ったかが後から分かる
    if outcome != "started" and prev.get("outcome") == "started" and prev.get("run_id") == row["run_id"]:
        row["started_at"] = prev.get("at")
    doc["runs"][group] = row
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, PATH)
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 実行の印を書けなかった（{type(e).__name__}: {e}）——本体の結果には影響しない")
        return 0
    print(f"実行の印: {group} {outcome}" + (f"（終了コード {rc}）" if rc is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
