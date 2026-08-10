#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/validate_state.py — **人の決定の正本 state.json を検査する**（v9.9.131・2026-08-10）

■ なぜ要るか
  state.json はブラウザが吐いたファイルを人がコミットする経路で入ってくる。
  **形が壊れたまま入ると、門は起動時に黙って「未初期化」と読んで何もしない**——
  つまり壊れたことが誰にも見えないまま、手元にしかない決定が守られていない状態になる。
  だから CI で形を検査し、**何が入っていて何が欠けているか**を名指しで出す。

■ 検査するもの
  (1) 形（fmt/ver/savedAt/data）
  (2) **想定外のキーが混ざっていないか**——state.js が読むのは6つだけで、
      それ以外は取り込まれずに捨てられる＝「入れたのに効かない」という静かな事故になる
  (3) 値が JSON として読めるか（pf:portfolio 等は JSON 文字列）
  (4) **何が欠けているか**（欠けていること自体は失敗ではない。まだ入れていないだけ）
  (5) savedAt が未来でないか（端末の時計ずれは「repoのほうが新しい」を永久に成立させる）

■ 何を FAIL にするか（線は高く置く）
  形が壊れている／想定外のキー／値が壊れている／savedAt が未来 だけ。
  **空であること・欠けていることは FAIL にしない**——初期状態がまさにそれで、
  ここで落とすと CI が常時赤になり、本当の破損がその中に埋もれる。

使い方:
  python3 night/validate_state.py            人が読む形
  python3 night/validate_state.py --json     機械可読
"""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "state.json")
AS_JSON = "--json" in sys.argv

# state.js と同じ集合（**片方だけ増やすと静かに割れる**ので、増やすときは両方）
EXACT = ["pf:portfolio", "pf:weights", "pf:sold", "pf:monthly", "g7ignite:map"]
PREFIX = ["g7log:"]
LABEL = {"pf:portfolio": "株数（Ⅶ資産）", "pf:weights": "目標ウェイト",
         "pf:sold": "売却記録", "pf:monthly": "今月の個別枠",
         "g7ignite:map": "点灯日（48h冷却）", "g7log:": "検証履歴"}


def watched(k):
    return k in EXACT or any(k.startswith(p) for p in PREFIX)


def main():
    fails, warns, info = [], [], []
    try:
        s = json.load(open(P, encoding="utf-8"))
    except FileNotFoundError:
        fails.append("state.json が無い")
        s = None
    except Exception as e:
        fails.append(f"state.json が JSON として読めない: {e}")
        s = None

    data, saved = {}, None
    if s is not None:
        if s.get("fmt") != "ccf-state":
            fails.append(f'fmt が "ccf-state" でない（{s.get("fmt")!r}）＝門は読まずに素通りする')
        if s.get("ver") != 1:
            warns.append(f'ver が 1 でない（{s.get("ver")!r}）')
        data = s.get("data") or {}
        if not isinstance(data, dict):
            fails.append("data が辞書でない")
            data = {}
        saved = s.get("savedAt")
        if saved:
            try:
                t = datetime.fromisoformat(str(saved).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if (t - datetime.now(timezone.utc)).total_seconds() > 3600:
                    fails.append(f"savedAt が未来（{saved}）＝端末の時計ずれ。"
                                 "門は永久に「repoのほうが新しい」と判定し続ける")
            except Exception:
                fails.append(f"savedAt が日時として読めない（{saved!r}）")

    # (2) 想定外のキー＝入れても門が捨てる＝静かな事故
    for k in data:
        if not watched(k):
            fails.append(f"想定外のキー {k!r}——門は取り込まない（state.js の集合に無い）")
    # 台帳をここに入れてはいけない（out/*_gate_pack.json が正本。二重の正本を作らない）
    for k in data:
        if k.startswith("g7:"):
            fails.append(f"{k!r} は台帳＝正本は out/*_gate_pack.json。state.json に入れない")

    # (3) 値が読めるか
    for k, v in data.items():
        if k == "pf:monthly":
            continue                    # 数値の文字列
        if not isinstance(v, str):
            fails.append(f"{k!r} の値が文字列でない（localStorage の生値をそのまま入れる）")
            continue
        try:
            o = json.loads(v)
        except Exception:
            warns.append(f"{k!r} の値が JSON として読めない（門は読めるかもしれないが要確認）")
            continue
        # ⚠ 形の検査（実測で踏んだ穴）: Ⅶ資産の load() は positions が配列でなければ
        #   **黙って既定値へ落として書き戻す**。つまり形が壊れた pf:portfolio を
        #   コミットすると、門を開いた瞬間に repo の株数が既定の3社で潰される。
        #   「JSONとして読める」だけでは足りない——中身の形まで見る。
        if k == "pf:portfolio":
            if not isinstance(o, dict) or not isinstance(o.get("positions"), list):
                fails.append("'pf:portfolio' に positions 配列が無い"
                             "——門を開くとⅦ資産が既定値に落として**書き戻す**（株数が消える）")
        if k == "pf:sold" and not isinstance(o, list):
            warns.append("'pf:sold' が配列でない（売却記録は配列で持つ）")

    # (4) 何が入っていて何が欠けているか
    have, miss = [], []
    for k in EXACT:
        (have if k in data else miss).append(k)
    nlog = sum(1 for k in data if k.startswith("g7log:"))
    (have if nlog else miss).append("g7log:")

    if AS_JSON:
        print(json.dumps({"ok": not fails, "savedAt": saved, "n": len(data),
                          "have": have, "missing": miss, "logs": nlog,
                          "fails": fails, "warns": warns}, ensure_ascii=False, indent=1))
        return 1 if fails else 0

    print("■ 人の決定の正本 state.json の検査（night/validate_state.py）")
    if saved is None:
        print("  savedAt: **null＝未初期化**——門は何もしない（手元の決定を消さない側に倒れている）。")
        print("  埋め方: 門のⅦ資産の「📤 state.json」で落として repo 直下へ置きコミットする。")
    else:
        print(f"  savedAt: {saved}　／　キー {len(data)}件（検証履歴 {nlog}件）")
    if have:
        print("  入っている: " + " / ".join(LABEL.get(k, k) for k in have))
    if miss:
        print("  まだ無い　: " + " / ".join(LABEL.get(k, k) for k in miss)
              + "　※欠けていること自体は失敗ではない（まだ入れていないだけ）")
    for w in warns:
        print("  ⚠ " + w)
    if fails:
        print(f"\n✗ FAIL {len(fails)}件")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✓ 形は正しい")
    return 0


if __name__ == "__main__":
    sys.exit(main())
