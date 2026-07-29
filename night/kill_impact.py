#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/kill_impact.py — キルを外したら誰がどう動くかを門そのもので実測する（2026-07-29新設）

なぜ要るか:
  audit_kill_roiic.py は「データが健全か」を仕分ける道具で、その先に
  「では26社の原本を読もう」という重い作業が待っている。だがその前に問うべきことがある——
  **読んで合否が動くのか。**

  2026-07-29の初回実測は、はっきりノーだった:
    ・複利停止キル(ROIIC³<WACC)が立っている28社すべてについて roiic を 'na' にしてキルを外しても、
      **Ω75 に届く社は一社も無かった**（最大 HD 71.3 / 次点 EVTC 69.5 / LMT 58.2）。
    ・28社は holdings.json の保有にも watch にも kanshi_list.json の監視にも**一社も入っていない**。
  ＝このキルは買付判断にも売却判断にも効いていない。26社ぶんの原本読解は**やっても何も動かない**。
  キルが効くのは (a) 外せば Ω75 に届く社がいるとき か (b) **保有銘柄に立ったとき**（S1の売却規律に直結）だけ。

  これは audit_moat_gap.py と同じ作法——**読む先を絞る道具**であって、読むこと自体が目的ではない。
  「キルが立っている」ことと「キルが効いている」ことは別で、後者だけが仕事を生む。

使い方:
  python3 night/kill_impact.py            複利停止キル(roiic<12)の候補帯
  python3 night/kill_impact.py --all      キルが1つ以上立っている全社
"""
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

JS = """
const {scorePack} = require('./night/score_all.js');
const fs = require('fs');
const ts = %s;
const out = [];
for (const t of ts) {
  const d = JSON.parse(fs.readFileSync('out/' + t + '_gate_pack.json', 'utf8'));
  const a = +scorePack(d).evalScore;
  const b = +scorePack({...d, roiic: 'na', roiic5: null}).evalScore;
  out.push([t, a, b]);
}
console.log(JSON.stringify(out));
"""


def main():
    show_all = "--all" in sys.argv
    sc = {r["t"]: r for r in json.load(open("out/score_all.json", encoding="utf-8"))}
    ts = []
    for t, r in sc.items():
        if re.match(r"^\d", t) or not r.get("kills"):
            continue
        try:
            d = json.load(open(f"out/{t}_gate_pack.json", encoding="utf-8"))
        except Exception:
            continue
        if show_all or (isinstance(d.get("roiic"), (int, float)) and d["roiic"] < 12):
            ts.append(t)
    ts.sort()
    print(f"キルが立っている{len(ts)}社について、roiic を 'na' にしてキルを外したときのΩを門そのもので実測する\n")

    r = subprocess.run(["node", "-e", JS % json.dumps(ts)], capture_output=True, text=True, cwd=BASE)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print("実測に失敗:", (r.stderr or "")[-500:])
        return 1

    held = set()
    try:
        h = json.load(open("holdings.json", encoding="utf-8"))
        held |= set(h.get("holdings") or []) | set(h.get("watch") or [])
    except Exception:
        pass
    try:
        held |= set(json.load(open("kanshi_list.json", encoding="utf-8")).get("list") or [])
    except Exception:
        pass

    print(f"{'':7s} {'現Ω':>6s} {'キルを外すと':>12s} {'差':>7s}  ")
    worth = []
    for t, a, b in sorted(rows, key=lambda x: -x[2]):
        mark = "★保有/監視＝S1の売却規律に直結" if t in held else ("★Ω75に届く" if b >= 75 else "")
        print(f"{t:7s} {a:6.1f} {b:12.1f} {b-a:+7.1f}  {mark}")
        if mark:
            worth.append(t)

    print(f"\n**原本を読む価値のある社（外せばΩ75に届く／保有・監視にいる）: {' '.join(worth) if worth else 'なし'}**")
    if not worth:
        print("  → キルは買付判断にも売却判断にも効いていない。**原本を読んでも何も動かない**ので、")
        print("     この社群の原本読解は作業リストから外してよい（キルが立つこと自体は正しい読み）。")
        print("     ただし保有に入った瞬間に話が変わる——買う前に必ずこれをもう一度回すこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
