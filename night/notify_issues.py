#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/notify_issues.py — **行動が要ることだけを GitHub Issue にする**（2026-08-10新設）

■ なぜ要るか
  CIの全ステップは `continue-on-error` で、**失敗しても翌日 ops_status が⚠にするまで誰も知らない**。
  門の🔔イベントタブは表示するが、それは**開いた人にしか届かない**。
  20-30年回す前提のパイプラインで、**知らせる経路が「人が見に行く」だけ**なのは弱い。
  Issue なら通知が飛び、履歴が残り、閉じるまで消えない。

■ 何を Issue にするか（**行動が要るものだけ**）
  鳴りすぎる警報は鳴らないのと同じなので、線を高く置く:
    1. **投下可の顔ぶれが変わった**       … 買付の対象が変わった＝いちばん重い
    2. **投下可・次点に納品検査FAIL**     … 買っている社の根拠が欠けている（第四の関門の入力）
    3. **回転盤に停止疑い**               … 自動化が止まった＝以後の全部が古くなる
    4. **8-K/6-K の警報**                 … 減損・退任・非依拠・破産・上場廃止通知
    5. **期末後の重大事象で要審査**       … パックが会社の現在を描いていない
  出さないもの: 納品検査FAILの全276社／未解決warn／表示専用の道具の結果。
  **今日の状態を毎日 Issue にはしない**——変化と行動だけ。

■ 冪等（ここが実装の肝）
  毎日走るので、同じことで Issue が増え続けたら**それ自体が警報の死**になる。
  各 Issue に **`<!--ccf:キー-->`** を埋め、呼び出し側が同じキーの open issue を探して
  **有れば作らない**。キーは「何が起きたか」で作る（例 `buy:ASML,MSFT,...` のハッシュ）ので、
  **状態が変われば新しい Issue になり、変わらなければ増えない**。

**判定も値も一切変えない。** 読むだけ。

使い方:
  python3 night/notify_issues.py            人が読む形
  python3 night/notify_issues.py --json     出す予定の Issue を JSON で（CIが使う）
  python3 night/notify_issues.py --base <ref>  投下可の差分を取る基準（既定 HEAD~1）
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = "--json" in sys.argv
BASE = "HEAD~1"
if "--base" in sys.argv:
    i = sys.argv.index("--base")
    if i + 1 < len(sys.argv):
        BASE = sys.argv[i + 1]


def jload(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d if d is not None else {}


def key(s):
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def main():
    out = []
    rows = jload("out/score_all.json", [])
    buy = [r["t"] for r in rows if r.get("buy")]

    # 1. 投下可の顔ぶれが変わった（**黙って変わるのが一番怖い**・v9.9.52）
    try:
        prev = json.loads(subprocess.run(["git", "show", f"{BASE}:out/score_all.json"],
                                         capture_output=True, text=True, timeout=60).stdout)
        pb = [r["t"] for r in prev if r.get("buy")]
    except Exception:
        pb = None
    if pb is not None and set(pb) != set(buy):
        gone = [t for t in pb if t not in buy]
        came = [t for t in buy if t not in pb]
        out.append({
            "k": "buy:" + key(",".join(sorted(buy))),
            "title": f"🟢投下可が変わった — 出: {' '.join(gone) or '—'} ／ 入: {' '.join(came) or '—'}",
            "body": f"**出**: {' '.join(gone) or '—'}\n**入**: {' '.join(came) or '—'}\n\n"
                    f"現在の投下可（{len(buy)}社）: `{' '.join(buy)}`\n\n"
                    "門の Ⅵ買付順位 で理由を確認してください。"
                    "**買わない理由であって売る理由ではありません**（堀不足と同じ扱い）。",
            "labels": ["投下可"]})

    # 2. 投下可・次点に納品検査FAIL（**第四の関門の入力が欠けている**）
    vf = (jload("out/validate_fail.json").get("items") or {})
    bad = [r["t"] for r in rows if (r.get("buy") or r.get("quali")) and r["t"] in vf]
    if bad:
        out.append({
            "k": "vfail:" + key(",".join(sorted(bad))),
            "title": f"⚠ 投下可・次点に納品検査FAIL {len(bad)}社: {' '.join(bad)}",
            "body": "値があるのに根拠が無い欄があります（第四の関門が読む表）。\n\n"
                    + "\n".join(f"- **{t}**: " + "／".join(vf[t].get("fails", []))[:300] for t in bad)
                    + "\n\n`python3 night/audit_promotion_ready.py` で席順＝繰り上がる順に出ます。",
            "labels": ["納品検査"]})

    # 3. 回転盤の停止疑い（**止まると以後の全部が古くなる**）
    ops = jload("out/ops_status.json")
    due = [i for i in (ops.get("items") or []) if i.get("state") == "due"]
    if due:
        out.append({
            "k": "ops:" + key(",".join(sorted(i["id"] for i in due))),
            "title": f"⚠ 回転盤に停止疑い {len(due)}本: " + " ".join(i["id"] for i in due),
            "body": "\n".join(f"- **{i.get('name')}**（{i.get('cadence','')}）最終 {i.get('last')} "
                              f"／ {i.get('how','')}" for i in due)
                    + "\n\n**止まった作業は、止まったことが見えている間だけ直せます。**",
            "labels": ["回転盤"]})

    # 4. 8-K / 6-K の警報（門2再審査の気づき。**判定には使わない**）
    al = (jload("out/events_watch.json").get("alerts") or [])
    if al:
        out.append({
            "k": "events:" + key(",".join(sorted(f"{a['t']}{a['date']}" for a in al))),
            "title": f"🔔 8-K/6-K 警報 {len(al)}件: " + " ".join(sorted({a["t"] for a in al})),
            "body": "\n".join(f"- **{a['t']}** {a['date']} {a['form']} — "
                              + "／".join(a.get("flags") or []) + (f"\n  {a['url']}" if a.get("url") else "")
                              for a in al)
                    + "\n\n**判定には使いません**——門2再審査の気づきです（株価も見ません）。",
            "labels": ["イベント"]})

    # 5. 期末後の重大事象で要審査（**パックが会社の現在を描いていない**）
    sb = {t: v for t, v in (jload("out/stale_bs.json").get("items") or {}).items()
          if str(v.get("verdict", "")).startswith("要審査")}
    if sb:
        out.append({
            "k": "stalebs:" + key(",".join(sorted(sb))),
            "title": f"⚠ 期末後の重大事象で要審査 {len(sb)}社: " + " ".join(sorted(sb)),
            "body": "\n".join(f"- **{t}**: のれんの新しさ {v.get('newPct')}%"
                              f"（パック {v.get('reportDate')} → {v.get('asOf')}）"
                              f"{' ／ **🟢投下可**' if v.get('buy') else ''}" for t, v in sb.items())
                    + "\n\n第四の関門が買付の土俵から降ろします。再審査は "
                      "`python3 night/make_chunks.py --reaudit` の待ち行列へ入ります。",
            "labels": ["再審査"]})

    if AS_JSON:
        print(json.dumps({"n": len(out), "issues": out}, ensure_ascii=False, indent=1))
        return 0
    print(f"■ 立てるべき Issue {len(out)}件"
          + ("（**行動が要ることだけ**——今日の状態は毎日は出さない）" if out else "  ✓ 行動が要ることは無い"))
    for o in out:
        print(f"\n▶ {o['title']}\n   key={o['k']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
