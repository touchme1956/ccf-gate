#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_todo.py — **人の作業リスト自身が古びていないかを機械で測る**（2026-08-10新設）

■ なぜ要るか
  `night/ops_status.py` は**機械の周期作業**が止まっていないかを測る。
  一方 `todo_list.json` は**人の作業と判断**の正本だが、**それを測るものが無かった**。
  2026-08-10 の全数監査で、未完了67件のうち **9件が解決済み／数字が古い／重複**だった:
    ・nde_kill_monotonicity … v9.9.126 で解決済みなのに done:false のまま
    ・single_year_25 / vfail_worklist_5 / disrupt_blank_12 … 実測と件数が食い違う
    ・ami_fangplus と ami_fangplus_gate … 同一内容の重複
  **古い作業リストは、作業リストが無いより悪い**——「まだ残っている」と嘘をつくので、
  本当に残っている項目がその中に埋もれる（鳴りすぎる警報は鳴らないのと同じ）。

■ 設計（ここが肝）
  総花的な「陳腐化検出」は作らない。**id ごとに「何を測れば決着するか」を明示した検査**だけを持つ。
  測れないものは測れないと言う——それがこの台帳の作法。
  検査は3種類:
    (1) **CHECKS**   … id → 実測して「解決済みか」を返す関数。証拠つき
    (2) **COUNTS**   … id → title/note に埋まった件数を今日の実測と突き合わせる
    (3) **重複/整合** … 同一内容の重複、gate_exceptions.json との突合せ

■ gate_exceptions.json との突合せ（2026-08-10・監査 6-4）
  門外例外は **gate_exceptions.json**（index.html が読む＝按分と表示）と
  **todo_list.json の gate_exception_***（night/watch_exceptions.py が読む＝四半期の財務監視）に
  **別々に書かれ、どちらも他方を参照しない**。
  → **gate_exceptions.json にだけ足すと四半期監視が付かない＝警報を切ったまま乗る**
  （watch_exceptions.py がまさにそれを防ぐために作られた事態）。ここで突き合わせる。

**判定も値も一切変えない。** 出るのは作業リストの健康診断だけ。

使い方:
  python3 night/audit_todo.py          人が読む形
  python3 night/audit_todo.py --json   out/todo_audit.json を書く
"""
import glob
import itertools
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = "--json" in sys.argv


def packs():
    for f in glob.glob("out/*_gate_pack.json"):
        try:
            x = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        yield os.path.basename(f).split("_gate_pack")[0].upper(), x


def score():
    try:
        return json.load(open("out/score_all.json", encoding="utf-8"))
    except Exception:
        return []


# ── (1) id ごとの「決着したか」の実測 ────────────────────────────────────────
#   返り値: (解決済みか, 証拠の一行)。測れないものは登録しない
def _nde_monotonic():
    h = open("index.html", encoding="utf-8").read()
    m = re.search(r"if\(ndeV>2\.5([^)]*)\)\{levPen", h)
    if not m:
        return None, "index.html に levPen の坂が見つからない（構造が変わった？）"
    return ("ndeV<=4" not in m.group(1)), f"index.html の坂の条件: `ndeV>2.5{m.group(1)}`"


def _single_year():
    n = [t for t, x in packs()
         if ((x.get("_meta") or {}).get("basis") or {}).get("roic") == "single-year"
         and any(r["t"] == t and (r.get("s") or 0) >= 72 for r in score())]
    return (not n), f"判定圏(Ω72+)で single-year のまま: {len(n)}社 {' '.join(sorted(n)[:12])}"


def _vfail_promotion():
    try:
        vf = set((json.load(open("out/validate_fail.json", encoding="utf-8")).get("rows") or []))
    except Exception:
        return None, "out/validate_fail.json が無い（ci.yml が生成する）"
    if isinstance(next(iter(vf), None), dict):
        vf = {r.get("t") for r in vf}
    rows = score()
    tgt = [r["t"] for r in rows if (r.get("buy") or r.get("quali")) and r["t"] in vf]
    return (not tgt), f"投下可・次点で納品検査FAIL: {len(tgt)}社 {' '.join(sorted(tgt))}"


def _disrupt_blank_irr85():
    n = [t for t, x in packs()
         if int(((x.get("data") or x).get("irr") or 0)) == 85
         and not (x.get("data") or x).get("disrupt")]
    return (not n), f"irr=85 で disrupt が空欄: {len(n)}社 {' '.join(sorted(n))}"


def _sic_cache():
    if not os.path.exists("out/_sic_cache.json"):
        return False, "out/_sic_cache.json が無い＝sht が全社で測れない"
    d = json.load(open("out/_sic_cache.json", encoding="utf-8"))
    return True, f"SICキャッシュ {len([k for k in d if not k.startswith('_')])}社"


def _sht_blank():
    tot = blank = 0
    for t, x in packs():
        tot += 1
        if not (x.get("data") or x).get("sht"):
            blank += 1
    return (blank == 0), f"sht が空欄: {blank}/{tot}社（空欄は門が 'flat' に化かす）"


CHECKS = {
    "nde_kill_monotonicity": _nde_monotonic,
    "single_year_25":        _single_year,
    "vfail_worklist_5":      _vfail_promotion,
    "disrupt_blank_12":      _disrupt_blank_irr85,
    "sic_cache_rebuild":     _sic_cache,
    "lrcx_f3_sht":           _sht_blank,
}


def main():
    todo = json.load(open("todo_list.json", encoding="utf-8"))
    items = todo.get("items", todo)
    open_items = [i for i in items if not i.get("done")]

    resolved, drifted, dup, notes = [], [], [], []
    dup_maybe = []   # 「重複かもしれない」候補。**判定しない**（スコアを出して人が読む）

    # (1) 決着の実測
    for i in open_items:
        fn = CHECKS.get(i.get("id"))
        if not fn:
            continue
        try:
            ok, ev = fn()
        except Exception as e:
            notes.append({"id": i["id"], "err": str(e)[:160]})
            continue
        if ok is True:
            resolved.append({"id": i["id"], "title": i.get("title", "")[:70], "evidence": ev})
        elif ok is None:
            notes.append({"id": i["id"], "err": ev})

    # (2) title/note に埋まった件数と実測のズレ
    for i in open_items:
        fn = CHECKS.get(i.get("id"))
        if not fn:
            continue
        try:
            ok, ev = fn()
        except Exception:
            continue
        if ok:
            continue
        claimed = re.findall(r"(\d+)\s*社", (i.get("title", "") + " " + str(i.get("note", ""))))
        actual = re.findall(r"(\d+)\s*社", ev)
        if claimed and actual and claimed[0] != actual[0]:
            drifted.append({"id": i["id"], "claimed": claimed[0] + "社",
                            "actual": actual[0] + "社", "evidence": ev})

    # (3) 重複。**2026-08-18 に較正して作り直した**（ユーザー「直して」）。
    #   旧実装は「タイトル先頭36字の完全一致」だけで、**言い換えた重複を原理的に拾えなかった**
    #   ——実例 `ami_fangplus`「FANG+ を網の門で審査する（実保有なのに一度も裁いていない）」と
    #   `ami_fangplus_gate`「FANG+ が網の門で未審査（実保有4本のうち唯一）」は先頭36字が違う。
    #
    #   【較正して分かったこと（実測137件・全ペア）】
    #     ・**id の前方一致は 1/1・誤検出0**（`ami_fangplus` ⊂ `ami_fangplus_gate`）＝最も安い確実な信号
    #     ・**タイトルの意味的な類似は単独では使えない**。正解ペアの文字bigram Jaccard は **0.25** しかなく、
    #       そこまで閾値を下げると**4ペア鳴って正解1件＝適合率25%**。鳴りすぎる警報は鳴らないのと同じ
    #     ・`同一ticker × 同kind × 同owner` は **6組すべて誤検出**（CW の gmt と roic は別の欄／
    #       MSFT の株数と v欄は別／CTAS の再審査と UniFirst 買収は別）＝この軸は重複を意味しない
    #     ・**だが「未完了どうし」に絞ると 4ペア → 1ペアへ落ちた**。残った1件
    #       （routine_freq_gap / review_routine_silent）は**互いに矛盾していて本物の疑い**だった。
    #       ＝誤検出の正体は**完了済みを混ぜていたこと**で、絞りは意味ではなく**状態**で効く
    #
    #   → 二段にする。**確実なものだけ「重複」と呼び、似ているだけは「候補」**にしてスコアを出す（判定しない）。
    #     ⚠ どちらも今日のデータでは誤検出0だが **n=1 ずつ**なので、適合率は主張しない
    def _bigrams(t):
        t = re.sub(r"[\s（）()【】・、。「」*`]", "", t or "")
        return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())

    def _jaccard(a, b):
        A, B = _bigrams(a), _bigrams(b)
        return len(A & B) / len(A | B) if (A | B) else 0.0

    # (3-a) 確実: id が前方一致（`x` と `x_...`）。相手は完了済みでもよい——統合先が閉じている場合がある
    for a in open_items:
        for b in items:
            if a is b or not a.get("id") or not b.get("id"):
                continue
            if a["id"].startswith(b["id"] + "_"):
                dup.append({"id": a["id"], "same_as": b["id"], "how": "idが前方一致",
                            "title": a.get("title", "")[:60]})

    # (3-b) 確実: タイトルが実質同一（旧実装をこの特殊形として残す）
    seen = {}
    for i in open_items:
        k = re.sub(r"[\s（）()]", "", (i.get("title") or ""))[:36]
        if k and k in seen:
            dup.append({"id": i["id"], "same_as": seen[k], "how": "タイトル先頭36字が一致",
                        "title": i.get("title", "")[:60]})
        elif k:
            seen[k] = i["id"]

    # (3-c) 候補: **未完了どうし** ∧ 文字bigram Jaccard≥0.25 ∧ 同kind ∧ 同owner。断定しない
    _named = {x["id"] for x in dup}
    for a, b in itertools.combinations(open_items, 2):
        if a["id"] in _named or b["id"] in _named:
            continue
        if a.get("kind") != b.get("kind") or (a.get("owner") or "") != (b.get("owner") or ""):
            continue
        sc = _jaccard(a.get("title"), b.get("title"))
        if sc >= 0.25:
            dup_maybe.append({"id": a["id"], "same_as": b["id"], "score": round(sc, 3),
                              "a": a.get("title", "")[:56], "b": b.get("title", "")[:56]})

    # (4) gate_exceptions.json ↔ todo_list.json（**片方だけに足すと監視が付かない**）
    exc = []
    try:
        ge = {str(r.get("t")).upper()
              for r in (json.load(open("gate_exceptions.json", encoding="utf-8")).get("items") or [])}
    except Exception:
        ge = None
    tl = set()
    for i in items:
        if str(i.get("id", "")).startswith("gate_exception"):
            tl |= {str(t).upper() for t in (i.get("tickers") or [])}
    if ge is not None:
        for t in sorted(ge - tl):
            exc.append({"t": t, "問題": "gate_exceptions.json にあるが todo_list.json の "
                                        "gate_exception_* に無い＝**watch_exceptions.py の四半期監視が付かない**"
                                        "（警報を切ったまま乗る）"})
        for t in sorted(tl - ge):
            exc.append({"t": t, "問題": "todo_list.json にあるが gate_exceptions.json に無い＝"
                                        "門のⅥが名指しせず按分にも入らない（黙って消える・v9.9.52型）"})

    doc = {"generated": __import__("datetime").date.today().isoformat(),
           "note": "todo_list.json（人の作業と判断の正本）自身の健康診断。"
                   "**判定も値も変えない。** 総花的な陳腐化検出ではなく、"
                   "**id ごとに『何を測れば決着するか』を明示した検査**だけを持つ（測れないものは測らない）。",
           "open": len(open_items), "checked": len(CHECKS),
           "resolved": resolved, "drifted": drifted, "duplicates": dup, "duplicates_maybe": dup_maybe,
           "gate_exception_mismatch": exc, "notes": notes}
    if AS_JSON:
        json.dump(doc, open("out/todo_audit.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    print(f"■ todo_list.json の健康診断　未完了 {len(open_items)}件 / 機械で測れる {len(CHECKS)}件")
    print(f"\n▶ **解決済みなのに done:false** {len(resolved)}件")
    for r in resolved:
        print(f"   ✓ {r['id']:26s} {r['evidence']}")
    print(f"\n▶ **件数が実測とずれている** {len(drifted)}件")
    for r in drifted:
        print(f"   ⚠ {r['id']:26s} 記載{r['claimed']} → 実測{r['actual']}　{r['evidence']}")
    print(f"\n▶ **重複（確実）** {len(dup)}件")
    for r in dup:
        print(f"   ⚠ {r['id']:26s} ≒ {r['same_as']}  （{r.get('how', '')}）")
    # 候補は**断定しない**。似ているだけかもしれないので、スコアと両方の題を出して人が読む
    print(f"\n▶ 重複の**候補**（断定しない・未完了どうし・題の類似≥0.25 ∧ 同種別 ∧ 同担当） {len(dup_maybe)}件")
    for r in dup_maybe:
        print(f"   ? {r['id']} / {r['same_as']}  類似 {r['score']}")
        print(f"       A: {r['a']}")
        print(f"       B: {r['b']}")
    print(f"\n▶ **門外例外の食い違い** {len(exc)}件"
          + ("（gate_exceptions.json と todo_list.json は互いを参照しない）" if exc else "  ✓ 一致"))
    for r in exc:
        print(f"   ⚠ {r['t']}: {r['問題']}")
    if notes:
        print(f"\n▶ 測れなかったもの {len(notes)}件")
        for r in notes:
            print(f"   － {r['id']}: {r['err']}")
    print("\n→ out/todo_audit.json" if AS_JSON else "\n（--json で out/todo_audit.json を書く）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
