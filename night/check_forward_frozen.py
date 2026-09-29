#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前向きの検定（mw_forward・nx_forward）の道具が、事前登録のときのままかを確かめる（2026-09-29新設）。

## なぜ要るか
前向きの検定は、測る前に固定した規則（事前登録）のとおりに最長20年回して、初めて意味を持つ。
その規則の実体は night/ の道具の中にある——**道具が1文字変われば、事前登録の規則が黙って変わる**。
ところが見張りは穴だらけだった:
  - nx の事前登録が持つ道具の指紋（frozen.tool_sha256_at_registration）は nx_forward.py の1本だけ。
    F3 の母集団を決める nx_jpfunds_data（category・kind・passes_filter）、ブランドの親会社の表を持つ
    nx_brand_data（BRAND_OWNER）、共通部品の nx_common は誰も見ていない
  - mw の事前登録には道具の指紋が1つも無い（mw_common.py は登録の後に2回変わった＝out/forward_frozen.json の note）
  - 前向きの更新の書き手が CI（ops.yml）になると、merge や手直しで道具が変わっても誰も気づかない
→ 道具と依存（と事前登録そのもの）の git の blob を out/forward_frozen.json に記録し、毎回突き合わせる。
  合わなければ非0で終わって名指しする。ops.yml はこれが通ったときだけ前向きの更新を回す。
  ci.yml も毎回回す（道具を変えたコミットがその日に赤くなる）。

## 共有の部品は「使う部分」だけを見る（2026-09-29・検査役の指摘）
mw_common.py は約80本、nx_common.py は約34本の研究の道具が import していて、研究の枝は今も直している
（mw_common は登録の後1日で2回＝yahoo() だけ）。blob まるごとで見ると、前向きの検定が使わない関数の1行でも
ci.yml が赤くなり前向きの更新が止まる——鳴りすぎる警報は鳴らないのと同じで、blob の書き換えが習慣になれば
検査の意味が消える。そこで2本だけは **ast の閉包の指紋**（"fingerprint"）で見る:
  - 根＝凍結した利用者（mw: mw_forward・mw_sec_replication の `M.名前`／nx: nx_forward・nx_brand_data・
    nx_jpfunds_data の `N.名前`）が触る名前。利用者は blob で凍結してあるので根も動かない
  - 閉包＝根から、モジュールの最上位の定義（関数・クラス・代入）を名前の参照でたどった全部＋最上位で走る文
    （import の時に効く副作用）。import 文と `if __name__ == '__main__':` は含めない
  - 指紋＝閉包の各節を正規化した文字列（行番号・docstring・空の欄を落とす＝Python 3.10〜3.13 で同じ値）の sha256
  ⚠ 限界: 閉包の外から実行時に書き換える経路（別の関数が global を変える・getattr の文字列）や、import 文の変化
    （例: 最上位で numpy を import して CI で落ちる）は見ない。後者は道具が落ちる＝実行の印と盤の見張り (d) に出る。
  実測: mw_common の指紋は登録の版（e87f7b4）・e5233ad5・今（baecc53）で同じ＝登録の後の直しが前向きの値を
  変えないことを機械で確かめた（yahoo は閉包に入らない）。

## 合わなかったら（直し方）
- **誤って変えた** → 記録の版へ戻す: `git cat-file -p <記録の blob> > <パス>`
  （blob で戻すので、取り込みの形〔merge・cherry-pick・複写〕に関係なく使える）
- **意図して変えた**（不具合の直しなど） → 事前登録の規則を変えたことになる。どの月の値が変わりうるかを確かめ、
  out/forward_frozen.json の changes に「いつ・何を・なぜ・どの月に効くか」を書いてから blob を書き換える。
  規則そのもの（相手・λ・B・μ_d・規則の文言）を変えるなら、それは別の新しい登録（e=1 から）——事前登録の約束
- **共有の部品（fingerprint を持つ mw_common・nx_common）** はファイルごと戻さない（研究の直しまで巻き戻る）。
  `git diff <blob_at_record> -- <パス>` で閉包の関数（記録の fingerprint.closure）の差だけを見て戻す。
  意図して変えたなら上と同じく changes に書き、`--fingerprint <パス>` が出す sha256・closure で記録を書き換える

## この器が守っている作法
- **判定を持たない**——採点にも門にも触れない。出力は標準出力だけ（ファイルを書かない＝CI の生成物を増やさない）
- **測れないを一致と読まない**——記録が読めない・ファイルが無い・blob が計算できない、はすべて食い違いとして落とす（ルール7）
- 前向きの出力（out/mw_forward.json・out/nx_forward.json）は毎月変わるので対象外（変わるのが正常）

使い方: python3 night/check_forward_frozen.py [--group mw|nx] [--json]
        python3 night/check_forward_frozen.py --fingerprint night/mw_common.py   # 今の閉包と指紋を出す（記録を直すとき）
  終了コード: 0＝すべて記録どおり ／ 1＝食い違い・測れない（名指しする）
"""
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(BASE, "out", "forward_frozen.json")


def blob_of(rel):
    """git の blob（git hash-object と同じ値）。ファイルが無ければ None。
    git が使えないときは同じ定義（sha1("blob <長さ>\\0" + 中身)）で計算する——この repo には
    .gitattributes が無いので、2つは一致する（2026-09-29 に3通りで一致を確かめた）"""
    p = os.path.join(BASE, rel)
    if not os.path.isfile(p):
        return None
    try:
        r = subprocess.run(["git", "hash-object", "--", rel], cwd=BASE, capture_output=True, text=True, timeout=60)
        v = r.stdout.strip()
        if r.returncode == 0 and len(v) == 40:
            return v
    except Exception:  # noqa: BLE001
        pass
    b = open(p, "rb").read()
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


# ── 共有の部品の ast の閉包の指紋 ─────────────────────────────────────────────
def used_names(src, alias):
    """利用者のソースで `alias.名前` として触られる名前（読み・書きとも）"""
    t = ast.parse(src)
    return {n.attr for n in ast.walk(t)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == alias}


def _is_main_guard(st):
    return (isinstance(st, ast.If) and isinstance(st.test, ast.Compare)
            and isinstance(st.test.left, ast.Name) and st.test.left.id == "__name__")


def _module_defs(tree):
    """最上位で名前を定義する節 {名前: [節]} と、最上位で走る文（定義でも import でもない）のリスト。
    if/try/with などの中の定義は、その文ごと（外側の節で）名前に結びつける"""
    defs, others = {}, []

    def add(name, st):
        defs.setdefault(name, [])
        if st not in defs[name]:
            defs[name].append(st)

    def visit(stmts, top):
        for st in stmts:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(st.name, top or st)
            elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            add(n.id, top or st)
            elif isinstance(st, (ast.Import, ast.ImportFrom)):
                if top is not None:            # try: import x except: x = None のような形は、文ごと名前に結びつける
                    for a in st.names:
                        add((a.asname or a.name).split(".")[0], top)
            elif isinstance(st, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                if _is_main_guard(st):
                    continue
                if top is None:
                    others.append(st)
                for fld in ("body", "orelse", "finalbody"):
                    visit(getattr(st, fld, None) or [], top or st)
                for hd in getattr(st, "handlers", None) or []:
                    visit(hd.body, top or st)
            elif top is None:
                others.append(st)

    visit(tree.body, None)
    return defs, others


def _names_in(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Global):
            out.update(n.names)
    return out


def _canon(node):
    """節の正規化した文字列。行番号などの属性・docstring・空の欄（None・[]）を落とす
    ＝版で増えた空の欄（3.12 の type_params）や ast.dump の既定の違い（3.13 の show_empty）に左右されない"""
    if isinstance(node, ast.AST):
        parts = [type(node).__name__]
        for f in node._fields:
            if f == "type_comment":
                continue
            v = getattr(node, f, None)
            if (f == "body" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and v
                    and isinstance(v[0], ast.Expr) and isinstance(getattr(v[0], "value", None), ast.Constant)
                    and isinstance(v[0].value.value, str)):
                v = v[1:]
            if v is None or (isinstance(v, list) and not v):
                continue
            parts.append(f"{f}={_canon(v)}")
        return "(" + " ".join(parts) + ")"
    if isinstance(node, list):
        return "[" + ",".join(_canon(x) for x in node) + "]"
    return repr(node)


def closure_fingerprint(rel, users):
    """→ {"roots", "closure", "missing", "sha256"}。users={利用者のパス: 別名}"""
    roots = set()
    for u, alias in sorted(users.items()):
        roots |= used_names(open(os.path.join(BASE, u), encoding="utf-8").read(), alias)
    tree = ast.parse(open(os.path.join(BASE, rel), encoding="utf-8").read())
    defs, others = _module_defs(tree)
    missing = sorted(r for r in roots if r not in defs)
    want = {r for r in roots if r in defs}
    nodes = {}
    changed = True
    while changed:
        changed = False
        for st in others:                       # 最上位で走る文は全部（import の時の副作用）
            if id(st) not in nodes:
                nodes[id(st)] = st
                changed = True
        for nm in sorted(want):
            for node in defs[nm]:
                if id(node) not in nodes:
                    nodes[id(node)] = node
                    changed = True
        for node in list(nodes.values()):
            for ref in _names_in(node):
                if ref in defs and ref not in want:
                    want.add(ref)
                    changed = True
    sha = hashlib.sha256("\n".join(sorted(_canon(n) for n in nodes.values())).encode("utf-8")).hexdigest()
    return {"roots": sorted(roots), "closure": sorted(want), "missing": missing, "sha256": sha}


def dig(d, dotted):
    for k in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def check(groups_wanted=None):
    """→ (所見のリスト, 見たファイルの数)。所見が空なら記録どおり"""
    bad = []
    try:
        rec = json.load(open(RECORD, encoding="utf-8"))
        groups = rec["groups"]
        assert isinstance(groups, dict) and groups
    except Exception as e:  # noqa: BLE001
        return [{"group": "-", "path": os.path.relpath(RECORD, BASE),
                 "why": f"凍結の記録が読めない（{type(e).__name__}）＝何も確かめられない"}], 0
    want = groups_wanted or sorted(groups)
    n = 0
    for g in want:
        G = groups.get(g)
        if not isinstance(G, dict) or not G.get("files"):
            bad.append({"group": g, "path": "-", "why": f"記録に群 {g} が無い"})
            continue
        for rel, f in G["files"].items():
            n += 1
            fp = (f or {}).get("fingerprint")
            if fp:                                   # 共有の部品: 使う部分（ast の閉包）だけを見る
                try:
                    cur_fp = closure_fingerprint(rel, fp.get("users") or {})
                except Exception as e:  # noqa: BLE001
                    bad.append({"group": g, "path": rel, "why": f"閉包の指紋を計算できない（{type(e).__name__}）"})
                    continue
                if cur_fp["missing"]:
                    bad.append({"group": g, "path": rel, "why": "前向きの道具が使う名前が無い: " + "・".join(cur_fp["missing"][:6]),
                                "restore": f"git diff {f.get('blob_at_record') or ''} -- {rel} で何が消えたかを見る"})
                elif cur_fp["roots"] != sorted(fp.get("roots") or []):
                    bad.append({"group": g, "path": rel, "why": "使う名前の一覧（根）が記録と違う（利用者の道具が変わった？）"})
                elif cur_fp["sha256"] != fp.get("sha256"):
                    bad.append({"group": g, "path": rel, "recorded": fp.get("sha256"), "current": cur_fp["sha256"],
                                "why": "前向きの道具が使う関数（閉包 " + str(len(cur_fp["closure"])) + "個）の中身が記録と違う"
                                       "（事前登録の規則が黙って変わりうる）",
                                "restore": f"git diff {f.get('blob_at_record') or ''} -- {rel} で閉包の関数の差を見て、"
                                           "誤って変えたなら戻す（閉包の名前は out/forward_frozen.json の fingerprint.closure）"})
                continue
            want_blob = (f or {}).get("blob")
            cur = blob_of(rel)
            if not want_blob:
                bad.append({"group": g, "path": rel, "why": "記録に blob が無い"})
            elif cur is None:
                bad.append({"group": g, "path": rel, "recorded": want_blob, "why": "ファイルが無い"})
            elif cur != want_blob:
                bad.append({"group": g, "path": rel, "recorded": want_blob, "current": cur,
                            "why": "中身が記録と違う（事前登録の規則が黙って変わりうる）",
                            "restore": f"git cat-file -p {want_blob} > {rel}"})
        # 事前登録そのものが持つ指紋（nx は nx_forward.py の sha256 を登録の時点で書いた）
        for s in G.get("prereg_sha256_checks") or []:
            n += 1
            try:
                pr = json.load(open(os.path.join(BASE, s["prereg"]), encoding="utf-8"))
                reg = dig(pr, s["key"])
                cur = hashlib.sha256(open(os.path.join(BASE, s["file"]), "rb").read()).hexdigest()
            except Exception as e:  # noqa: BLE001
                bad.append({"group": g, "path": s.get("file", "-"),
                            "why": f"事前登録の指紋を確かめられない（{type(e).__name__}）"})
                continue
            if not reg or reg != cur:
                bad.append({"group": g, "path": s["file"], "recorded": reg, "current": cur,
                            "why": f"sha256 が事前登録（{s['prereg']} の {s['key']}）と違う"})
    return bad, n


def main():
    ap = argparse.ArgumentParser(description="前向きの検定の道具が事前登録のときのままか")
    ap.add_argument("--group", choices=["mw", "nx"], action="append",
                    help="この群だけ見る（ops.yml は更新する道具の群だけを見る）。省けば全部")
    ap.add_argument("--json", action="store_true", help="所見を JSON で標準出力へ（ファイルは書かない）")
    ap.add_argument("--fingerprint", metavar="PATH",
                    help="記録に fingerprint を持つ共有の部品の、今の閉包と指紋を出す（記録を意図して直すとき用・何も書かない）")
    a = ap.parse_args()
    if a.fingerprint:
        rec = json.load(open(RECORD, encoding="utf-8"))
        for G in rec["groups"].values():
            f = (G.get("files") or {}).get(a.fingerprint) or {}
            if f.get("fingerprint"):
                json.dump(closure_fingerprint(a.fingerprint, f["fingerprint"].get("users") or {}),
                          sys.stdout, ensure_ascii=False, indent=1)
                print()
                return 0
        print(f"✗ {a.fingerprint} は記録に fingerprint を持たない（blob で見ている）")
        return 1
    bad, n = check(a.group)
    if a.json:
        json.dump({"ok": not bad, "n_checked": n, "groups": a.group or "all", "mismatches": bad},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0 if not bad else 1
    label = "・".join(a.group) if a.group else "全部"
    if not bad:
        print(f"✓ 前向きの検定の道具は事前登録のときのまま（{label}・{n}件が {os.path.relpath(RECORD, BASE)} と一致）")
        return 0
    print(f"✗ 前向きの検定の道具が記録と違う（{label}・{len(bad)}件）——**前向きの更新は回さない**")
    for b in bad:
        print(f"  ✗ [{b['group']}] {b['path']}  {b['why']}")
        if b.get("recorded") or b.get("current"):
            print(f"      記録 {b.get('recorded') or '—'} ／ 今 {b.get('current') or '（無い）'}")
        if b.get("restore"):
            print(f"      誤って変えたなら戻す: {b['restore']}")
    if any(b.get("current") for b in bad):
        print("  → 意図して変えたなら、事前登録の規則を変えたことになる。どの月に効くかを確かめ、"
              "out/forward_frozen.json の changes に記録してから blob を書き換える（規則そのものを変えるなら別の新しい登録）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
