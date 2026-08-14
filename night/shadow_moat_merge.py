#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_moat_merge.py — 二重計上を「空欄」ではなく「**合併**」で解いたらどうなるかを実測する（2026-08-13新設）

■ なぜこの器が要るか
  shadow_moat_dedup.py（案B/C＝片方を空欄にする）の実測で、**60社中46社が堀 算出不能(NA)へ落ちた**。
  原因は構造で、門は「5本中4本を切ったら堀を測ったとは言えない」という下限を持ち、
  今日の台帳は **moatW が空欄の社が多く 4本ぎりぎり**だから。
  ＝**「どちらか一方の欄へ寄せる」を素直に実装すると、二重計上を解くのではなく測れなくする。**

  そこで「重みを配り直す」側（todoの(c)）を測る。二つの柱が同じ事実なら、
  **一つの柱に合併し、重みは重いほうの1本ぶんだけ数える**（重み .50 → .25）。
  ⚠**新しい定数を一つも導入していない**——合併後の値は幾何平均（指数が既に使っている集約）、
    重みは既存の W の大きいほう。

■ 二つの変種を分けて測る（これが本題）
  E1  床を**合併後**の本数で見る … 正直な実装（同じ事実なら独立な測定は1本減る）
  E2  床を**合併前**の本数で見る … **重みの効果だけ**を切り出す（床の効果と分離する）
  この二つを並べないと「NAへ落ちたのは重みのせいか床のせいか」が判らない。

■ やること
  index.html の ccfMoat の3行を差し替えて `node night/score_all.js` を回し、**必ず元へ戻す**（finally・sha256で検算）。
  正本の採点・規約・台帳は一切変えない。

■ 使い方
  python3 night/shadow_moat_merge.py                 既定の対（読解が済んでいれば confirmed_up）
  python3 night/shadow_moat_merge.py --pairs a.json
"""
import glob, hashlib, json, os, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")
SCORE = os.path.join(OUT, "score_all.json")
HTML = os.path.join(BASE, "index.html")

ANCHOR = (
    "  const legs=Object.keys(W).map(k=>[k,rung(k,num(d[k]))]).filter(l=>l[1]!=null&&l[1]>0);\n"
    "  const miss=Object.keys(W).filter(k=>!legs.some(l=>l[0]===k));\n"
    "  if(legs.length<4)return {idx:null,na:true,miss:miss,legs:legs.length};\n"
)
# ★2026-08-13: 初版は d.nm で銘柄を引いたが **ccfMoat には銘柄が渡っていなかった**（実測で全社 0 動き）。
#   呼び出し側(compute)は 5本＋gls/disrupt/erosion だけを渡す。
#   ＝**錨が当たったのに効かない**という一番静かな壊れ方。合併の対象は銘柄ごとなので nm を渡す側も差し替える。
ANCHOR_CALL = (
    "  const moatR=ccfMoat({dom:$('dom').value,irr:$('irr').value,rep:$('rep').value,dur:$('dur').value,\n"
    "                       moatW:$('moatW').value,gls:$('gls').value,"
    "disrupt:$('disrupt').value,erosion:$('erosion').value});\n"
)
PATCH_CALL = (
    "  const moatR=ccfMoat({nm:$('nm').value,dom:$('dom').value,irr:$('irr').value,"
    "rep:$('rep').value,dur:$('dur').value,\n"
    "                       moatW:$('moatW').value,gls:$('gls').value,"
    "disrupt:$('disrupt').value,erosion:$('erosion').value});\n"
)


def patch(mg, floor_pre):
    return (
        "  let legs=Object.keys(W).map(k=>[k,rung(k,num(d[k]))]).filter(l=>l[1]!=null&&l[1]>0);\n"
        "  const miss=Object.keys(W).filter(k=>!legs.some(l=>l[0]===k));\n"
        "  const __pre=legs.length;\n"
        f"  const __MG={json.dumps(mg, ensure_ascii=False)}, __FP={'true' if floor_pre else 'false'};\n"
        "  const __t=String(d.nm||'').split(' ')[0];\n"
        "  if(__MG[__t]){for(const pr of __MG[__t]){\n"
        "    const a=pr[0],b=pr[1];const ia=legs.findIndex(l=>l[0]===a),ib=legs.findIndex(l=>l[0]===b);\n"
        "    if(ia>=0&&ib>=0){const keep=(W[a]>=W[b])?a:b,drop=(keep===a)?b:a;\n"
        "      const va=legs[ia][1],vb=legs[ib][1];\n"
        "      legs[legs.findIndex(l=>l[0]===keep)][1]=Math.sqrt(va*vb);\n"
        "      legs=legs.filter(l=>l[0]!==drop);}}}\n"
        "  if((__FP?__pre:legs.length)<4)return {idx:null,na:true,miss:miss,legs:legs.length};\n"
    )


def digest(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run_score():
    subprocess.run(["node", "night/score_all.js"], check=True, capture_output=True, text=True)
    return json.load(open(SCORE, encoding="utf-8"))


def summarise(rows):
    return {"n_buy": sum(1 for r in rows if r.get("buy")),
            "buy": sorted(r["t"] for r in rows if r.get("buy")),
            "n_moat_na": sum(1 for r in rows if r.get("moat") is None),
            "omega": {r["t"]: r.get("s") for r in rows},
            "moat": {r["t"]: r.get("moat") for r in rows}}


def load_pairs(path=None):
    if path and os.path.exists(path):
        d = json.load(open(path, encoding="utf-8"))
        rows = d if isinstance(d, list) else d.get("confirmed_up") or d.get("rows") or []
        return [{"ticker": r["ticker"], "a": r["a"], "b": r["b"]} for r in rows]
    v = os.path.join(OUT, "moat_dc_verdicts.json")
    if os.path.exists(v):
        d = json.load(open(v, encoding="utf-8"))
        ups = d.get("confirmed_up") or []
        if ups:
            return [{"ticker": u["ticker"], "a": u["a"], "b": u["b"]} for u in ups]
        print("  ⚠ confirmed_up が空——合併する対が無いので E は A と同じになる")
        return []
    c = os.path.join(OUT, "moat_double_count.json")
    if not os.path.exists(c):
        return []
    print("  ⚠ 読解の結果がまだ無いので、**引用共有の全対**で測る（上限の計測）")
    d = json.load(open(c, encoding="utf-8"))
    return [{"ticker": r["t"], "a": pr["a"], "b": pr["b"]}
            for r in d["rows"] for pr in r["pairs"] if pr["shared_quote"]]


def main():
    pfile = sys.argv[sys.argv.index("--pairs") + 1] if "--pairs" in sys.argv else None
    src = open(HTML, encoding="utf-8").read()
    for a, nm in ((ANCHOR, "ccfMoat の legs"), (ANCHOR_CALL, "ccfMoat の呼び出し")):
        if a not in src:
            sys.exit(f"✗ 錨({nm})が index.html に見つからない＝この器を直すこと")
    before = digest(HTML)
    bscore = open(SCORE, "rb").read() if os.path.exists(SCORE) else None

    pairs = load_pairs(pfile)
    mg = {}
    for p in pairs:
        mg.setdefault(p["ticker"], [])
        if [p["a"], p["b"]] not in mg[p["ticker"]]:
            mg[p["ticker"]].append([p["a"], p["b"]])

    res = {}
    try:
        rows = run_score()
        res["A"] = summarise(rows)
        print(f"■ 案A 現行  🟢投下可 {res['A']['n_buy']}社  堀NA {res['A']['n_moat_na']}社")
        print(f"    {' '.join(res['A']['buy'])}\n")
        for name, fp in (("E1", False), ("E2", True)):
            open(HTML, "w", encoding="utf-8").write(
                src.replace(ANCHOR, patch(mg, fp)).replace(ANCHOR_CALL, PATCH_CALL))
            rows = run_score()
            s = summarise(rows)
            res[name] = s
            lab = "床は合併後の本数（正直な実装）" if name == "E1" else "床は合併前の本数（重みの効果だけ）"
            print(f"■ 案{name} 合併・{lab}  🟢投下可 {s['n_buy']}社  堀NA {s['n_moat_na']}社")
            print(f"    {' '.join(s['buy'])}")
            a = res["A"]
            out_ = [t for t in a["buy"] if t not in s["buy"]]
            in_ = [t for t in s["buy"] if t not in a["buy"]]
            mv = sorted(((t, round((s["omega"].get(t) or 0) - (a["omega"].get(t) or 0), 2))
                         for t in a["omega"]
                         if abs((s["omega"].get(t) or 0) - (a["omega"].get(t) or 0)) > 0.05),
                        key=lambda x: x[1])
            print(f"    出 {' '.join(out_) or '—'} ／ 入 {' '.join(in_) or '—'}")
            print(f"    Ωが動いた社 {len(mv)}／最大 {mv[0][1] if mv else 0:+.1f}"
                  f" ・最小 {mv[-1][1] if mv else 0:+.1f}")
            if mv:
                print("    下がった上位: " + " ".join(f"{t}{x:+.1f}" for t, x in mv[:8]))
            print()
        with open(os.path.join(OUT, "shadow_moat_merge.json"), "w", encoding="utf-8") as f:
            json.dump({"tool": "shadow_moat_merge", "rev": "r1",
                       "n_pairs": len(pairs), "merge": mg, "cases": res}, f, ensure_ascii=False, indent=1)
        print("→ out/shadow_moat_merge.json")
    finally:
        open(HTML, "w", encoding="utf-8").write(src)
        if bscore is not None:
            open(SCORE, "wb").write(bscore)
        ok = digest(HTML) == before
        print("✓ index.html を完全に復元した（sha256一致）" if ok
              else "✗✗ 復元に失敗した。git checkout index.html で戻すこと")
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
