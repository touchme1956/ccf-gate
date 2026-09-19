#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_drop_scores.py — 「必要ないスコア」を外したら誰がどう動くか（2026-09-19新設）

■ なぜ
  `python3 night/audit_deadweight.py --swing` は「値があっても判定が動かない欄」を出すが、
  **その表に analysts / instOwn / mcap が入っていない**（RANGES に無い）。
  この3本は 発見度(negS) の入力で、negS は evalScore を **±1.5/−1.0 直接** 動かす。
  ＝**Ωを直接動かす経路が、無駄かどうかの検査の対象外だった**。
  実測: negApplied≠0 は **50社**（+1.5 が42社・−1.0 が8社）で、うち **IRMD は🟢投下可**。

■ 型は shadow_gmpt.py と同じ: index.html の指定行だけ差し替え→score_all→**必ず元へ戻す**（sha256で検算）
  ⚠ 正本の採点は変えない。out/score_all.json も上書きしない（--only 等と同じく .partial へ逃がす）。

使い方: python3 night/shadow_drop_scores.py
出力: out/shadow_drop_scores.json
"""
import hashlib, json, os, re, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
IDX = os.path.join(BASE, "index.html")

# ---- 差し替える実文（index.html に一字一句あること。無ければ中止＝錨が外れたまま測らない）
NEG0 = ("  if(negS>=2){negApplied=1.5;evalScore=Math.min(100,evalScore+1.5);}\n"
        "  else if(negS<=-2){negApplied=-1.0;evalScore=Math.max(0,evalScore-1.0);}")
NEG1 = "  /*shadow: 発見度(negS)をΩから外す*/"

# ⚠ v9.9.171 で memo フォールバックは撤去済み。B は「founder+8 **そのもの**を外す」案で未採用なので
#   錨を現行の実文へ更新する（更新しないと「本採用済み」と**誤ラベル**される）。
FND0 = "    if(founderV==='yes')sc+=8; void(memoV);"
FND1 = "    /*shadow: 創業者経営 +8 を外す*/ void(founderV); void(memoV);"

IDXN0 = "  if(idxV==='no')negS+=1;"
IDXN1 = "  /*shadow: 主要指数採用(idx)を発見度から外す*/ void(idxV);"

CASES = {
    "A_negSを外す":            [(NEG0, NEG1)],
    "B_founder+8を外す":        [(FND0, FND1)],
    "C_idxだけ外す":            [(IDXN0, IDXN1)],
}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run():
    # 部分実行ではないので正本を潰さないよう --only で全社を指定…はできないため、
    # score_all を回した後に必ず git から正本を復元する。
    r = subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("score_all 失敗:\n" + r.stderr[-2000:])
    return json.load(open("out/score_all.json"))


def digest(rows):
    buy = [x["t"] for x in rows if x.get("buy")]
    return {
        "buy": buy,
        "n_buy": len(buy),
        "q75": sum(1 for x in rows if (x.get("s") or 0) >= 75),
        "q72": sum(1 for x in rows if (x.get("s") or 0) >= 72),
        "s": {x["t"]: x.get("s") for x in rows},
    }


def main():
    before = sha(IDX)
    src = open(IDX, encoding="utf-8").read()
    # ★v9.9.171 で A（negS）と B2（memoフォールバック）は**本採用した**ので、その錨は index.html に無い。
    #   錨が消えた案は「壊れた」ではなく「**適用済み**」——黙って落とさず名指しで飛ばす（ルール7の表示版）。
    applied = []
    for name in list(CASES):
        if any(src.count(a) != 1 for a, _ in CASES[name]):
            applied.append(name); del CASES[name]
    if applied:
        print("※ 錨が無い案＝**本採用済み**なので測らない: " + " / ".join(applied))
    if not CASES:
        raise SystemExit("測る案が残っていない（すべて本採用済み）")

    base = digest(run())
    out = {"asof": __import__("datetime").date.today().isoformat(),
           "base": {k: v for k, v in base.items() if k != "s"}, "cases": {}}
    print(f"基準: 投下可 {base['n_buy']}社 {' '.join(base['buy'])} ／ Ω75+ {base['q75']} ／ Ω72+ {base['q72']}")

    try:
        for name, pats in CASES.items():
            mod = src
            for a, b in pats:
                mod = mod.replace(a, b, 1)
            open(IDX, "w", encoding="utf-8").write(mod)
            d = digest(run())
            moved = {t: round(d["s"][t] - base["s"][t], 2)
                     for t in base["s"] if t in d["s"] and abs((d["s"][t] or 0) - (base["s"][t] or 0)) >= 0.05}
            inn = sorted(set(d["buy"]) - set(base["buy"]))
            outb = sorted(set(base["buy"]) - set(d["buy"]))
            out["cases"][name] = {
                "n_buy": d["n_buy"], "buy": d["buy"], "in": inn, "out": outb,
                "q75": d["q75"], "q72": d["q72"],
                "n_moved": len(moved), "max_abs": (max(abs(v) for v in moved.values()) if moved else 0.0),
                "moved_top": dict(sorted(moved.items(), key=lambda kv: -abs(kv[1]))[:12]),
            }
            print(f"\n{name}: 投下可 {d['n_buy']}社 (出 {outb or 'なし'} ／ 入 {inn or 'なし'})  "
                  f"Ω75+ {d['q75']} Ω72+ {d['q72']}  Ωが動く {len(moved)}社 最大 {out['cases'][name]['max_abs']:.2f}pt")
            if moved:
                print("   " + " ".join(f"{t}{v:+.1f}" for t, v in list(out["cases"][name]["moved_top"].items())[:10]))
            open(IDX, "w", encoding="utf-8").write(src)
    finally:
        open(IDX, "w", encoding="utf-8").write(src)
        # ★git から戻すと**変更前の正本**に戻ってしまう（本採用した改定が消える）。
        #   復元は「今の index.html でもう一度回す」——正本は常に現行の門の出力であるべき。
        run()

    after = sha(IDX)
    assert after == before, f"index.html の復元に失敗: {before} → {after}"
    print(f"\n✓ index.html 復元を検算（sha256 {before[:12]}…）")
    print("✓ out/score_all.json は現行の index.html で回し直して復元（正本を潰さない）")
    os.makedirs("out", exist_ok=True)
    json.dump(out, open("out/shadow_drop_scores.json", "w"), ensure_ascii=False, indent=1)
    print("→ out/shadow_drop_scores.json")


if __name__ == "__main__":
    main()
