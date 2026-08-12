#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/enqueue_reaudit.py — **検出器の出力を再審査の待ち行列へ流す**（2026-08-10新設）

■ なぜ要るか（今日の監査で見つかった、いちばん構造的な断絶）
  この門は検出器を次々に増やしてきたが、**見つけたものを誰にも渡していなかった**:

    audit_pack_stale      新しい年次報告が出た社          → 渡し先なし
    audit_promotion_ready 根拠さえ埋めれば繰り上がる社     → 渡し先なし
    validate_packs        納品検査FAIL                   → 渡し先なし
    audit_stale_bs        期末後にBSが大きく変わった社     → 渡し先なし
    watch_new_listings    上場後1年の新規社（KRMN型）     → 渡し先なし
    watch_events          8-K/6-K の警報                 → 渡し先なし

  しかも `night/make_chunks.py:44` は
  `if t in seen or t in done or t in SKIP or t in in_chunks: continue` で
  **既にパックのある社を除外する**——つまり**再審査は構造的にキューへ載らない**。
  ＝「検出は自動・作業は手動」の断絶の正体はここ。

■ 何をするか（判定はしない・順番を付けるだけ）
  上の6つの出力を読んで **銘柄ごとに理由をまとめ、優先度を付けた待ち行列**を作る。
  優先度は**門の中での位置**で決める——買付判断に近いところから直すのが一番効くから:
      100 投下可（🟢）      … いま買っている社の根拠が欠けている
       80 次点（🔵）        … 次に繰り上がる社（v9.9.95で6回連続で踏んだ「繰り上がりは検査の引き金」）
       60 判定圏（Ω72+）    … 線が動けば効く
       30 それ以外
  ＋ 理由ごとの重み（新しい年次報告・BS急変は「今のパックが会社の現在を描いていない」ので重い）。

  **値も規約も一切触らない。** 出るのは順番の付いた作業リストだけ。
  実際に審査するのは `night/agent_prompt_template.txt`（正本はⅡ手順3）に従う審査官の仕事で、
  定性項目を機械が埋めることは絶対のルール2が禁じている。

使い方:
  python3 night/enqueue_reaudit.py            人が読む形
  python3 night/enqueue_reaudit.py --json     night/reaudit_queue.json を書く
  python3 night/enqueue_reaudit.py --top 20   上位だけ
出力: night/reaudit_queue.json（make_chunks.py --reaudit が読む）
"""
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = "--json" in sys.argv
TOP = None
if "--top" in sys.argv:
    i = sys.argv.index("--top")
    if i + 1 < len(sys.argv):
        TOP = int(sys.argv[i + 1])


def jload(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def main():
    # 2026-08-11: **作業リストを自分で作り直してから読む**。
    #   out/promotion_ready.json は out/score_all.json から数秒で作れるので、
    #   「呼ぶ側が先に回してくれている」に依存しない（依存すると、今朝 market.yml が
    #   validate_fail.json を古いまま採点していたのと同じ順序の穴ができる）。
    #   再実装はしない——既存の道具をそのまま呼ぶ。
    for tool in (["night/audit_promotion_ready.py", "--json"],
                 # 2026-08-12: irr=70 の根拠の triage も同じ理由でここで作り直す
                 #   （呼ぶ側の順序に依存すると、古い在庫を今日の作業リストとして配ることになる）
                 ["night/audit_irr70.py", "--json"]):
        try:
            subprocess.run([sys.executable] + tool, capture_output=True, timeout=180)
        except Exception:
            pass
    rows = jload("out/score_all.json", [])
    pos = {r["t"]: r for r in rows}

    def rank(t):
        r = pos.get(t)
        if not r:
            return 30, "台帳外"
        if r.get("buy"):
            return 100, "🟢投下可"
        if r.get("quali"):
            return 80, "🔵次点"
        if (r.get("s") or 0) >= 72:
            return 60, "判定圏Ω72+"
        # 2026-08-11追加: **別枠85 の社は Ω で近さを測れない**。
        #   v9.9.119 の別枠は Ω75+ を免除する経路なので、この群の Ω は 60 前後でも買付の一歩手前にいる。
        #   ここを Ω だけで切ると、**データ健全で投下可から落ちた瞬間に作業リストからも消える**
        #   ——落とした当のFAILを直す仕事が誰にも渡らない自己封鎖になる（実害: RBC 2026-08-10）。
        #   make_kanshi の「要審査の社を必ず残す」（Ω75+だけで引くと異常を拾った社が消える）と同じ話。
        if r.get("frame85"):
            return 60, "別枠85"
        return 30, ""

    q = {}

    def add(t, w, why):
        t = str(t).strip().upper()
        if not t:
            return
        d = q.setdefault(t, {"t": t, "w": 0, "why": []})
        d["w"] += w
        d["why"].append(why)

    # 1. 新しい年次報告が出た＝**パックが会社の現在を描いていない**。最も重い
    for t, v in (jload("out/pack_stale.json").get("items") or {}).items():
        add(t, 40, f"新しい年次報告あり（パック {v.get('packFY') or v.get('reportDate')} "
                   f"→ 最新 {v.get('latestFY') or v.get('latest')}）")
    # 2. 期末後に貸借対照表が大きく変わった（のれんの新しさ≥30%＝要審査）
    for t, v in (jload("out/stale_bs.json").get("items") or {}).items():
        if str(v.get("verdict", "")).startswith("要審査"):
            add(t, 35, f"期末後の重大事象（のれんの新しさ {v.get('newPct')}%）")
    # 3. 納品検査FAIL——**買付判断に近い社だけ**を拾う。全276社を並べると作業リストが死ぬ
    for t, v in (jload("out/validate_fail.json").get("items") or {}).items():
        r0, lab = rank(t)
        if r0 >= 60:
            add(t, 20, f"納品検査FAIL {v.get('n')}件（{lab}）")
    # 3-b. **根拠さえ埋めれば四関門を通る社**——2026-08-11新設（audit_promotion_ready --json）。
    #   検出はずっと自動だったのに、**渡し先が人の目しか無かった**（この repo が繰り返してきた
    #   「見つけたものを誰にも渡していない」型。night/enqueue_reaudit.py の頭注そのもの）。
    #   重みは **45＝最上位**（年次報告の40より上）。理由: この群は**次の席が空いた瞬間に繰り上がる社**で、
    #   根拠の穴を残したまま繰り上がると 2026-08-06 に6回連続で起きた
    #   「席に着いてから初めて検査され、2社は誤値そのものが出て脱落」がまた起きる。
    #   ＝**不意打ちを消すために先に潰す**のが、待ち行列の中で最も価値の高い一手。
    prank = {}
    for v in (jload("out/promotion_ready.json").get("rows") or []):
        add(v.get("t"), 45, f"根拠さえ埋めれば四関門を通る（繰り上がり{v.get('rank')}番目・"
                            f"納品検査FAIL {v.get('vFail')}件）")
        prank[str(v.get("t")).strip().upper()] = v.get("rank") or 999
    # 4. 新規上場の作業リスト（🆕未審査 / ⚠根拠なし）
    nl = jload("out/new_listings_irr.json")
    st = {r.get("t"): r.get("state") for r in (nl.get("rows") or [])}
    for t in (nl.get("work") or []):
        s = st.get(t) or ""
        add(t, 25 if s == "⚠根拠なし" else 15, f"新規上場の掃除 {s or ''}".strip())
    # 4-b. **irr=70 で「摩擦の機構」の根拠が無い社**（2026-08-12新設・規約改定と対）
    #   規約を「70は残余ではなく積極的な主張＝機構の名指し＋原本引用が要る」へ改めたので、
    #   その要求を満たさない社は**充填の対象**になる。渡し先が人の目しか無いと腐るので待ち行列へ入れる。
    #   重み22 は 納品検査FAIL(20) と 新規上場の根拠なし(25) の間。**判定圏だけ**に絞る
    #   （全213社を並べると作業リストが死ぬ——因子3と同じ規律）。
    #   ⚠実測の重み: 判定圏の70を50に落とすと**投下可10社中7社が落ちる**（night/shadow_irr_step.js）。
    #   刻み別のラベル一致率は70だけ0.706（50は0.971・85/100は1.00）＝**穴はここ一点**。
    for v in (jload("out/audit_irr70.json").get("rows") or []):
        if str(v.get("cls", "")).startswith(("A", "B")):
            continue                      # A=機構を名指し / B=認定の語（Bは85側の疑いで別作業）
        r0, lab = rank(v.get("t"))
        if r0 >= 60:
            add(v.get("t"), 22, f"irr=70 に摩擦の機構の根拠が無い（{v.get('cls')}・{v.get('n')}字）")
    # 5. 8-K / 6-K の警報（門2再審査の「気づき」＝判定には使わない）
    for a in (jload("out/events_watch.json").get("alerts") or []):
        add(a.get("t"), 15, f"{a.get('form')} {a.get('date')}：" + "／".join(a.get("flags") or []))

    out = []
    for t, d in q.items():
        base, lab = rank(t)
        r = pos.get(t) or {}
        out.append({"t": t, "priority": base + d["w"], "place": lab,
                    # 同点は**繰り上がる順**で割る（この群を先頭に置く意味そのもの）
                    "porder": prank.get(t, 999),
                    "omega": r.get("s"), "buy": bool(r.get("buy")),
                    "quali": bool(r.get("quali")),
                    "reasons": d["why"]})
    out.sort(key=lambda x: (-x["priority"], x.get("porder", 999), x["t"]))
    if TOP:
        out = out[:TOP]

    doc = {"generated": datetime.date.today().isoformat(),
           "note": "**検出器の出力を再審査の待ち行列へ流したもの。** 判定も値も一切変えない。"
                   "優先度は門の中での位置（投下可100 / 次点80 / 判定圏60 / 他30）＋理由の重み。"
                   "実際の審査は night/agent_prompt_template.txt に従う審査官の仕事で、"
                   "定性項目を機械が埋めることは絶対のルール2が禁じている。"
                   "`python3 night/make_chunks.py --reaudit` がこれを読んで night/rechunkNN.txt を作る。",
           "n": len(out), "rows": out}
    if AS_JSON:
        json.dump(doc, open("night/reaudit_queue.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    print(f"■ 再審査の待ち行列 {len(out)}社（検出器6本の合流）")
    print(f"{'順':>3} {'':7}{'Ω':>6} {'位置':<10}理由")
    for i, r in enumerate(out[:40], 1):
        print(f"{i:>3} {r['t']:<7}{(r['omega'] if r['omega'] is not None else 0):>6.1f} "
              f"{r['place']:<10}" + " ／ ".join(r["reasons"])[:96])
    if len(out) > 40:
        print(f"    …ほか {len(out)-40}社")
    print("\n→ night/reaudit_queue.json" if AS_JSON else "\n（--json で night/reaudit_queue.json を書く）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
