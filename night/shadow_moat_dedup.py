#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_moat_dedup.py — 「二重計上を解いたら誰がどう動くか」を実測する（2026-08-13新設）

■ なぜ道具にしたか
  todo: moat_dom_irr_double_count ——「領域独占が irr と dom の両方で数えられ、
  重み .50 が一つの事実から出ている」。**解き方は3つあり、どれも採点を動かす**ので、
  絶対のルール1により先に「変えたら誰がどう動くか」を実測する。
  **基準を変えたら誰がどう動くかは、推測でなく実測で出す**（門の既定の作法）。

■ 測る案（いずれも「同じ信号を二度数えない」の実装違い）
  A 現行                   何もしない
  B 引用共有の軽いほうを空欄  読解で確定した対だけ、重みの軽い柱を空欄にする（＝(b)どちらか一方へ寄せる）
  C 規約の定義の重なりを解く  irr=100 の社は dom を空欄にする
                            （dom=100 の刻み『または実質唯一供給』は irr=100 と同じ引き金なので）
  D B ∪ C                  両方

  ⚠ **空欄にするのは「値を消す」ことではない**——門は空欄を残りの柱へ再正規化するので、
    「その柱はもう測らない」ではなく「**その事実は他の柱が既に数えている**」という意味になる。

■ やること
  1. 全パックを退避 → 指定の柱を null 化 → node night/score_all.js → **必ず元へ戻す**（finally）
  2. 復元をバイト単位で検算する（戻し忘れは正本の汚染そのものなので）
  ※これは影の計測であって、正本の採点・台帳・規約は一切変えない。

■ 使い方
  python3 night/shadow_moat_dedup.py                       A/B/C/D を全部
  python3 night/shadow_moat_dedup.py --case C              1案だけ
  python3 night/shadow_moat_dedup.py --pairs a.json        Bの対象を差し替える
      （既定は out/moat_dc_verdicts.json の confirmed_up。無ければ out/moat_double_count.json の引用共有全部）
"""
import glob, hashlib, json, os, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")
SCORE = os.path.join(OUT, "score_all.json")
# ★2026-09-23: 重みは audit_moat_gap.py（index.html の ccfMoat から読む）から取る——写しは v9.9.36 のまま残っていた。
#   ここでの用途は「軽いほうの柱を落とす」選択だけで、6組とも新旧どちらの重みでも同じ柱が選ばれる（実測）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_moat_gap as _AMG  # noqa: E402
W = _AMG.W


def packs():
    return sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json")))


def digest():
    h = hashlib.sha256()
    for f in packs():
        h.update(open(f, "rb").read())
    return h.hexdigest()


def run_score():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    return json.load(open(SCORE, encoding="utf-8"))


def summarise(rows):
    buy = [r["t"] for r in rows if r.get("buy")]
    return {
        "n_buy": len(buy), "buy": sorted(buy),
        "n_quali": sum(1 for r in rows if r.get("quali")),
        "n_moat_ok": sum(1 for r in rows if r.get("moatOK")),
        "omega": {r["t"]: r.get("s") for r in rows},
        "moat": {r["t"]: r.get("moat") for r in rows},
    }


def drops_B(pairs):
    """引用共有の対ごとに、**重みの軽いほう**を空欄にする（同じ社で複数対なら和集合）"""
    d = {}
    for p in pairs:
        a, b = p["a"], p["b"]
        k = a if W[a] <= W[b] else b
        d.setdefault(p["ticker"], set()).add(k)
    return d


def drops_C():
    """irr=100 の社は dom を空欄（規約の dom=100『または実質唯一供給』が irr=100 と同じ引き金）"""
    d = {}
    for f in packs():
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        try:
            irr = float(str(p.get("irr")).strip())
        except Exception:
            continue
        if irr == 100 and p.get("dom") not in (None, ""):
            d[(p.get("nm") or "?").split(" ")[0]] = {"dom"}
    return d


def apply_drops(d):
    """d = {ticker: {柱, ...}} をパックへ当てる"""
    n = 0
    for f in packs():
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        t = (p.get("nm") or "?").split(" ")[0]
        if t not in d:
            continue
        ch = False
        for k in d[t]:
            if p.get(k) not in (None, ""):
                p[k] = None
                ch = True
        if ch:
            json.dump(p, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            n += 1
    return n


def load_pairs(path=None):
    if path and os.path.exists(path):
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, list) else d.get("confirmed_up") or d.get("rows") or []
    v = os.path.join(OUT, "moat_dc_verdicts.json")
    if os.path.exists(v):
        d = json.load(open(v, encoding="utf-8"))
        ups = d.get("confirmed_up") or []
        if ups:
            return [{"ticker": u["ticker"], "a": u["a"], "b": u["b"]} for u in ups]
        print("  ⚠ moat_dc_verdicts.json はあるが confirmed_up が空——B は空集合になる")
        return []
    c = os.path.join(OUT, "moat_double_count.json")
    if not os.path.exists(c):
        return []
    print("  ⚠ 読解の結果がまだ無いので、**引用共有の全対**を B の対象にする（上限の計測）")
    d = json.load(open(c, encoding="utf-8"))
    return [{"ticker": r["t"], "a": pr["a"], "b": pr["b"]}
            for r in d["rows"] for pr in r["pairs"] if pr["shared_quote"]]


def main():
    only = sys.argv[sys.argv.index("--case") + 1].upper() if "--case" in sys.argv else None
    pfile = sys.argv[sys.argv.index("--pairs") + 1] if "--pairs" in sys.argv else None

    before = digest()
    tmp = tempfile.mkdtemp(prefix="moat_dedup_")
    for f in packs():
        shutil.copy2(f, tmp)
    bscore = open(SCORE, "rb").read() if os.path.exists(SCORE) else None

    try:
        pairs = load_pairs(pfile)
        cases = {
            "A": {},
            "B": drops_B(pairs),
            "C": drops_C(),
        }
        cases["D"] = {t: set(cases["B"].get(t, set())) | set(cases["C"].get(t, set()))
                      for t in set(cases["B"]) | set(cases["C"])}

        base = None
        res = {}
        for name in ("A", "B", "C", "D"):
            if only and name != only and name != "A":
                continue
            # 毎回まっさらへ戻してから当てる（案が積み重ならないように）
            for f in glob.glob(os.path.join(tmp, "*_gate_pack.json")):
                shutil.copy2(f, OUT)
            n = apply_drops(cases[name]) if cases[name] else 0
            rows = run_score()
            s = summarise(rows)
            s["n_packs_touched"] = n
            s["drops"] = {t: sorted(v) for t, v in sorted(cases[name].items())}
            res[name] = s
            if name == "A":
                base = s
            print(f"■ 案{name}  触ったパック {n}社  🟢投下可 {s['n_buy']}社")
            print(f"    {' '.join(s['buy'])}")
            if base and name != "A":
                out_ = [t for t in base["buy"] if t not in s["buy"]]
                in_ = [t for t in s["buy"] if t not in base["buy"]]
                moved = sorted(((t, round((s["omega"].get(t) or 0) - (base["omega"].get(t) or 0), 2))
                                for t in base["omega"]
                                if abs((s["omega"].get(t) or 0) - (base["omega"].get(t) or 0)) > 0.05),
                               key=lambda x: x[1])
                print(f"    出 {' '.join(out_) or '—'} ／ 入 {' '.join(in_) or '—'}")
                print(f"    Ωが動いた社 {len(moved)}／最大 {moved[0][1] if moved else 0:+.1f}"
                      f" ・最小 {moved[-1][1] if moved else 0:+.1f}")
            print()

        with open(os.path.join(OUT, "shadow_moat_dedup.json"), "w", encoding="utf-8") as f:
            json.dump({"tool": "shadow_moat_dedup", "rev": "r1",
                       "n_pairs_for_B": len(pairs), "cases": res}, f, ensure_ascii=False, indent=1)
        print("→ out/shadow_moat_dedup.json")
    finally:
        for f in glob.glob(os.path.join(tmp, "*_gate_pack.json")):
            shutil.copy2(f, OUT)
        if bscore is not None:
            open(SCORE, "wb").write(bscore)
        after = digest()
        ok = (after == before)
        print(("✓ パックを完全に復元した（sha256一致）" if ok
               else "✗✗ 復元に失敗した。git status を確認して手で戻すこと"))
        shutil.rmtree(tmp, ignore_errors=True)
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
