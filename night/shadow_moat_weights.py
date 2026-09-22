#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_moat_weights.py — **堀5本の重みを振ったら誰がどう動くか**（2026-09-21新設）

★これは影の計測であって規約の変更ではない。index.html の `const W={...}` の**1行だけ**を
  差し替えて `node night/score_all.js` を回し、**必ず元へ戻す**（shadow_gmpt.py / shadow_rung_top.py と同じ型）。
  終了時に sha256 で復元を検算する。正本の採点・合否はこの道具では動かない。

■ なぜ測るか（ユーザーの要望「irr85 の評価をスコアで強く出したい／独占かつ参入困難も強く入れたい」）
  現行 W = dom .25 / irr .25 / rep .20 / dur .12 / moatW .18（加重幾何平均・v9.9.36）。
  **幾何平均は既に「両方高い」を要求する形**なので、「独占かつ参入困難」を強くするのに
  新しい規則は要らない——**dom と irr の重みを上げれば、両方高い社だけが伸びる**。
  （別枠の加点を作ると Ω への三つ目の経路になり、v9.9.45「同じ信号を二度数えない」に触れる）

■ 歴史側の裏づけ（out/retro_moat_pillars.json・2026-08-12）
  irr   … 2013 +0.322 / 2015 +0.175 / 2018 +0.342（**3ビンテージすべて p=0.000＝5本で唯一**）
  dom   … 2018 +0.007 p0.94 ＝**測れていない**（124社中113社が50＝変動が無い）
  moatW … 代理(nseg) +0.021 p0.79 ＝**検出力があって効かなかった**（本物の陰性）
  rep / dur … どのビンテージにも記録が無い＝**構造的に検定不能**
  ⚠ 「測っていない」と「測って効かない」を分ける。dom を上げるのは測定ではなく**指示**の領分。

■ 案（内部比を壊さない形で作る＝測っていない3本の相対関係に手を入れない）
  rep:dur:moatW = 20:12:18 の比は全案で不変。動かすのは **dom+irr が全体の何割か**だけ。
実行: python3 night/shadow_moat_weights.py [--json]
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
HTML = "index.html"
CUR = "  const W={dom:.25,irr:.25,rep:.20,dur:.12,moatW:.18};"

REST = {"rep": .20, "dur": .12, "moatW": .18}          # 比 20:12:18 を保つ
RSUM = sum(REST.values())


def weights(dom, irr):
    """dom/irr を決め、残りを 20:12:18 の比で埋める（合計は必ず 1.000）"""
    rest = 1.0 - dom - irr
    w = {"dom": dom, "irr": irr}
    for k, v in REST.items():
        w[k] = rest * v / RSUM
    return w


CASES = [
    ("現行            dom .25 / irr .25", weights(.25, .25)),
    ("A  irr だけ上げる  dom .25 / irr .35", weights(.25, .35)),
    ("B  両方上げる      dom .30 / irr .30", weights(.30, .30)),
    ("C  両方を強く      dom .35 / irr .35", weights(.35, .35)),
    ("D  irr 優位        dom .30 / irr .35", weights(.30, .35)),
]


def line(w):
    return ("  const W={dom:%s,irr:%s,rep:%s,dur:%s,moatW:%s};"
            % tuple(("%.4f" % w[k]).rstrip("0").rstrip(".") for k in
                    ("dom", "irr", "rep", "dur", "moatW")))


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run():
    r = subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("score_all が失敗:\n" + r.stderr[-1500:])
    rs = json.load(open("out/score_all.json", encoding="utf-8"))
    return {x["t"]: x for x in rs}


def main():
    src = open(HTML, encoding="utf-8").read()
    if src.count(CUR) != 1:
        raise SystemExit("錨が1つ見つからない——ccfMoat の W 行が変わった。**当てずに止める**")
    bak = tempfile.mktemp(suffix=".html")
    shutil.copy(HTML, bak)
    before = sha(HTML)
    out = {}
    try:
        for name, w in CASES:
            open(HTML, "w", encoding="utf-8").write(src.replace(CUR, line(w)))
            rows = run()
            buy = [t for t, x in rows.items() if x.get("buy")]
            buy.sort(key=lambda t: -rows[t]["s"])
            out[name] = {
                "w": {k: round(v, 4) for k, v in w.items()},
                "buy": buy,
                "moat70": sum(1 for x in rows.values()
                              if x.get("moat") is not None and x["moat"] >= 70),
                "rows": {t: {"s": x["s"], "moat": x["moat"]} for t, x in rows.items()},
            }
    finally:
        shutil.copy(bak, HTML)
        os.remove(bak)
        assert sha(HTML) == before, "★復元に失敗した——git checkout index.html せよ"
        subprocess.run(["node", "night/score_all.js"], capture_output=True, text=True)

    base = out[CASES[0][0]]
    for name, _ in CASES:
        o = out[name]
        print("■", name, " 堀70+ %d社" % o["moat70"])
        print("   🟢投下可:", " ".join(o["buy"]))
        if name != CASES[0][0]:
            gone = [t for t in base["buy"] if t not in o["buy"]]
            new = [t for t in o["buy"] if t not in base["buy"]]
            if gone or new:
                print("   出", " ".join(gone) or "—", " / 入", " ".join(new) or "—")
            mv = sorted(((o["rows"][t]["s"] - base["rows"][t]["s"], t)
                         for t in o["rows"] if t in base["rows"]),
                        key=lambda x: -abs(x[0]))[:6]
            print("   Ωの動き(絶対値上位):",
                  " ".join("%s %+.1f" % (t, d) for d, t in mv))
        print()
    if "--json" in sys.argv:
        json.dump(out, open("out/shadow_moat_weights.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("→ out/shadow_moat_weights.json")


main()
