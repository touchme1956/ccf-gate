#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_moat.py — 堀5本(dom/irr/rep/dur/moatW)の「根拠の質」を全パックで点検する（2026-07-29新設）

なぜ要るか:
  v9.9.39 で堀のふるい（絶対MOAT指数 ≥ 75 を新規投下の第三の関門）を入れた。
  ふるいは入力の質を超えられない——測っていない値で優良企業を切ったら、堀ではなく
  審査の手抜きを罰していることになる。この道具は「どの銘柄の堀が現行の刻みで
  measured か」を機械的に仕分けし、再監査の作業リストを出す。

点検するもの:
  1) dom が入っているのに、根拠が空 / 定性表現のみ / 「原本にシェア開示なし」と自認
     → v9.9.38の刻みは**市場構造**（上位2社で≥80%か等）で決まるので、シェア%すら
       無い根拠から刻みは導けない。数字が入っていること自体が憶測（絶対のルール2違反）
  2) dom が空欄なのに、空欄にした理由が _meta に残っていない
     → v9.9.39 の再正規化は「測定不能」にだけ許した扱い。単に調べていない空欄が
       同じ得をすると、埋めないほど有利という逆向きの誘因になる
  3) moatW が空欄（旧4本式へフォールバック＝堀の本数を測っていない）
  4) dom は入っているが上位N社の構造が未確認（△。刻みが1段ずれ得る）

使い方:
  python3 night/audit_moat.py            全パック
  python3 night/audit_moat.py --q75      Ω75+ だけ（out/score_all.json が要る）
  python3 night/audit_moat.py --list     再監査の作業リスト（コード列）だけを出す
  python3 night/audit_moat.py --all      合格分（根拠つきの空欄を含む）も表示する
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# 「原本にシェアの開示が無い」と審査官自身が書いている定型
NO_DISCLOSURE = re.compile(
    r"シェア[%％]?(?:の)?(?:記載|開示|数値|実数)?(?:は)?(?:なし|無し|ない|取れ(?:ず|なかった))"
    r"|明示的(?:な)?シェア(?:%|％)?(?:の)?記載なし"
    r"|シェア(?:%|％)?を(?:一切)?開示(?:して)?(?:い)?ない"
    r"|開示なし"
)
# 市場構造（v9.9.38の刻みが要求するもの）
STRUCTURE = re.compile(r"上位\s*[23]\s*社|複占|寡占構造|合計シェア|CR\s*[23]")


def grade_dom(dom, ev):
    """dom の根拠を4段階に仕分ける。戻り: (記号, 説明, 再監査が要るか)"""
    ev = str(ev or "").strip()
    has_pct = bool(re.search(r"\d+(?:\.\d+)?\s*[%％]", ev))
    if dom in (None, ""):
        return None  # 空欄側は別で見る
    if not ev:
        return ("✗", "dom根拠が空——数字の出どころが無い", True)
    if NO_DISCLOSURE.search(ev):
        return ("✗", "「原本にシェア開示なし」と自認しながら数字が入っている（根拠と値が矛盾）", True)
    if not has_pct:
        return ("✗", "定性表現のみ（leading/leader等）でシェア数値が無い", True)
    if not STRUCTURE.search(ev):
        return ("△", "シェア%はあるが上位N社の構造が未確認——v9.9.38の刻みは構造で決まる", True)
    return ("◎", "シェア%＋市場構造（上位N社／複占）で刻みが導けている", False)


def dom_null_ok(meta):
    """dom を空欄にした理由が _meta に残っているか（残っていれば再正規化を許す）"""
    nulls = meta.get("nulls") or {}
    if isinstance(nulls, dict):
        for k, v in nulls.items():
            if k == "dom" or k.startswith("dom"):
                return True, str(v)[:160]
    ev = (meta.get("evidence") or {}).get("dom")
    if ev and re.search(r"未記入|測定不能|空欄", str(ev)):
        return True, str(ev)[:160]
    for s in (meta.get("kenshi") or []):
        if re.search(r"dom.*(未記入|測定不能|空欄)", str(s)):
            return True, str(s)[:160]
    return False, ""


def main():
    argv = sys.argv[1:]
    only = None
    if "--q75" in argv:
        try:
            rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
            only = {r["t"] for r in rows if r.get("s", 0) >= 75}
        except Exception:
            print("out/score_all.json が無い。先に `node night/score_all.js` を回すこと")
            return 1

    need, ok, rows = [], 0, []
    for f in sorted(os.listdir(OUT)):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        if only is not None and t not in only:
            continue
        try:
            d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
        except Exception:
            continue
        meta = d.get("_meta") or {}
        ev = (meta.get("evidence") or {}).get("dom")
        dom, moatw = d.get("dom"), d.get("moatW")
        flags, notes = [], []
        if dom in (None, ""):
            documented, why = dom_null_ok(meta)
            if documented:
                # 根拠つきの空欄は「合格」——再監査待ちに数えない（v9.9.39の再正規化が許す状態）。
                # ここを need に入れると、正しく空欄にした銘柄が永久に作業リストへ残り続ける
                mark = "◎"
                notes.append("dom空欄・理由あり＝再正規化を許す（%s…）" % why[:70])
            else:
                mark = "✗"
                flags.append("dom空欄だが理由が_metaに無い——単に未調査の可能性。再正規化を許さず差し戻し")
        else:
            g = grade_dom(dom, ev)
            mark = g[0]
            if g[2]:
                flags.append("dom=%s: %s" % (dom, g[1]))
        if moatw in (None, ""):
            flags.append("moatW空欄——堀の本数が未測定（旧4本式で採点中）")
            if mark == "◎":
                mark = "△"
        rows.append((t, str(d.get("nm") or t), mark, dom, moatw, flags, notes))
        if flags:
            need.append(t)
        else:
            ok += 1

    if "--list" in argv:
        print(" ".join(need))
        return 0

    verbose = "--all" in argv
    for t, nm, mark, dom, moatw, flags, notes in rows:
        if not flags and not verbose:
            continue
        print("%s %-7s %-26s dom=%-5s moatW=%-5s" % (mark, t, nm[:26], dom, moatw))
        for x in flags:
            print("      · %s" % x)
        for x in notes:
            print("      ○ %s" % x)
    n = len(rows)
    nnull = sum(1 for r in rows if r[6])
    print("\n%d社中 %d社は合格（うち %d社は dom を根拠つきで空欄にした＝再正規化で採点）。%d社が再監査待ち。"
          % (n, ok, nnull, len(need)))
    print("  ◎=根拠十分 / △=刻みが1段ずれ得る / ✗=根拠と値が食い違う・根拠が無い")
    print("  再監査は night/agent_prompt_template.txt（日本株は _jp）で原本から dom / moatW を取り直す。")
    print("  作業リストのコード列は `python3 night/audit_moat.py --list` で取れる。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
