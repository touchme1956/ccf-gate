#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_blank_penalty.py — **「測れない欄が多いほど減点」を当てたら誰がどう動くか**（2026-09-21新設）

★これは影の計測であって規約の変更ではない。`index.html` の compute() に1行足して score_all を回し、
  **必ず元へ戻す**（sha256 で検算）。正本の採点・合否は動かない。

■ なぜ測るか（2026-09-21・ユーザーの問い「測れないものが多いほど−1をいれるなど」）
  この台帳は「**測らないほうが有利**」を繰り返し潰してきた（erosion/disrupt/acq5/sht/堀5本）。
  門は既にその欄を `CCF_BLANK` の **'best'** として分類済み——
  **erosion / disrupt / eq / geopol / moatdecay / expiry / dom / irr / rep / dur / moatW / cagrT の12欄**。
  ⇒ **新しい分類を作る必要は無い。門自身の 'best' 群を数えて引くだけ**で規則になる。

■ 案（どれも新しい欄・新しい分類を作らない）
  m1   : best群の空欄 × **−1**
  m2   : best群の空欄 × **−2**
  moat1: **堀5本だけ**（dom/irr/rep/dur/moatW）の空欄 × −1

⚠ **実測の要点**: 判定圏33社の空欄数は**中央値1・最大2**で、**投下可6社のうち4社（CW/MSFT/LRCX/BR）が
  そろって1件（dom だけ）**。⇒ **「測れていない量」でBRだけを狙い撃つことはできない**。
  それでも順位は動く——BR は MCO と **0.3pt差**で、MCO は空欄ゼロだから。

実行: python3 night/shadow_blank_penalty.py [--json]
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
H = "index.html"
ANCH = ("  if(acqAdj)evalScore=Math.max(0,Math.min(100,evalScore+acqAdj));"
        " // v9.9.180: 買収の強度（控えめ+2 / 中+1 / 大きく買う0 / 買収しない−1。v9.9.181で物差しを acqS5 へ）")
BEST = ['erosion', 'disrupt', 'eq', 'geopol', 'moatdecay', 'expiry',
        'dom', 'irr', 'rep', 'dur', 'moatW', 'cagrT']
MOAT = ['dom', 'irr', 'rep', 'dur', 'moatW']


def patch(fields, per):
    js = ",".join("'%s'" % k for k in fields)
    return ANCH + ("\n  {const _bk=[%s];let _n=0;for(const _k of _bk){const _e=$(_k);"
                   "const _v=_e?String(_e.value||'').trim():'';if(_v==='')_n++;}"
                   "if(_n>0)evalScore=Math.max(0,evalScore-%g*_n);}" % (js, per))


CASES = [("now   現行", None),
         ("m1    best群の空欄 × −1", (BEST, 1)),
         ("m2    best群の空欄 × −2", (BEST, 2)),
         ("moat1 堀5本だけの空欄 × −1", (MOAT, 1))]


def run():
    r = subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("score_all が失敗:\n" + r.stderr[-1200:])
    return {x["t"]: x for x in json.load(open("out/score_all.json", encoding="utf-8"))}


def main():
    src = open(H, encoding="utf-8").read()
    if src.count(ANCH) != 1:
        raise SystemExit("錨が1つ見つからない——compute() が変わった。**当てずに止める**")
    sha = lambda: hashlib.sha256(open(H, "rb").read()).hexdigest()
    b4 = sha()
    bak = tempfile.mktemp(suffix=".html")
    shutil.copy(H, bak)
    out = {}
    try:
        for name, cfg in CASES:
            s = src if cfg is None else src.replace(ANCH, patch(*cfg))
            open(H, "w", encoding="utf-8").write(s)
            out[name] = run()
    finally:
        shutil.copy(bak, H)
        os.remove(bak)
        assert sha() == b4, "★復元に失敗——git checkout index.html せよ"
        run()

    base = out[CASES[0][0]]
    for name, _ in CASES:
        r = out[name]
        buy = sorted([t for t, x in r.items() if x["buy"]], key=lambda t: -r[t]["s"])
        nxt = sorted([t for t, x in r.items() if x["quali"] and not x["buy"]], key=lambda t: -r[t]["s"])
        print(f"■ {name}")
        print("   🟢", " ".join(f"{t}({r[t]['s']})" for t in buy))
        print("   🔵", " ".join(f"{t}({r[t]['s']})" for t in nxt[:6]) or "—")
        if name != CASES[0][0]:
            bb = [t for t, x in base.items() if x["buy"]]
            gone = [t for t in bb if t not in buy]
            new = [t for t in buy if t not in bb]
            print("   出", " ".join(gone) or "—", " / 入", " ".join(new) or "—")
        print()
    if "--json" in sys.argv:
        json.dump({k: {t: (x["s"], x["moat"], x["buy"]) for t, x in v.items()} for k, v in out.items()},
                  open("out/shadow_blank_penalty.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("→ out/shadow_blank_penalty.json")


main()
