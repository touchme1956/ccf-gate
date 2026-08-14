#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro_h3.py — H3(ablation): どの欄が Ω̂ の当たりを運んでいるか（2026-08-14）

■ 事前登録（out/omega_retro_prereg.json）の H3 をそのまま実行する
      「各欄は Ω̂ の当たりに貢献している。判定: その欄を**中立固定**すると lift が 0.15 以上落ちる」

■ ★「中立固定」は null ではなく**全社をその欄の中央値に固定**する
  AMENDMENT で判ったとおり、門では空欄は中立ではなく**潰し**（gm の下限クランプ＋evalScore の 0 床）。
  null にすると「情報を抜いた効果」と「水準が落ちた効果」が混ざって読めなくなる。
  中央値固定なら**その欄は存在するが会社を区別しない**＝ablation の定義そのもの。

■ なぜ H2 より H3 のほうが答えに近いか（H2 の実測を受けて）
  H2 は合格ゼロだったが、原因は「候補が悪い」ではなかった——
  **重みを振っても順位相関 ρ が 0.9937〜0.9996** ＝ どんな順位統計でも分解できない。
  ⇒ Ω を「歴史的に良く」したいなら**重みではなく、欄が何を測っているか**しかない。
     その欄がどれかを名指しするのが H3。

使い方: python3 night/omega_retro_h3.py
出力: out/omega_retro_h3.json
"""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")

BREAK, FWD, LINE = -0.15, 0.15, 0.15
RET = {2013: "out/retro_returns_2013_all.json", 2015: "out/retro_returns_2015_q.json"}
COH = {2013: "out/retro_cohort_2013.json", 2015: "out/retro_cohort_2015.json"}

# 中立固定する欄（歴史側で再構成できた入力だけ。無いものは ablate しても意味が無い）
FIELDS = [
    ("roic", "ROIC（through-cycle）"), ("roicg", "ROIC（のれん込み）"),
    ("roic,roicg", "ROIC系まとめて"),
    ("dom", "堀: 支配シェア"), ("irr", "堀: 代替不能性"), ("rep", "堀: 複製障壁"),
    ("dur", "堀: 堀の型"), ("moatW", "堀: 広さ"),
    ("dom,irr,rep,dur,moatW", "堀5本まとめて"),
    ("p1", "ROIC安定性"), ("p2", "不況耐性"), ("p4", "会計健全"),
    ("p1,p2,p4", "判断項目まとめて"),
    ("nde", "純有利子負債/EBITDA"), ("gm", "営業利益率"), ("cagr", "売上成長"),
    ("accr", "アクルーアル"),
]


def load(f):
    d = json.load(open(f, encoding="utf-8"))
    r = d.get("items") or d.get("rows") or d
    return list(r.values()) if isinstance(r, dict) else r


def key(x):
    return x.get("ticker") or x.get("t")


def split_lift(pairs):
    s = sorted(pairs, key=lambda x: -x[0])
    h = len(s) // 2
    if not h or h == len(s):
        return None
    a = sum(1 for _, d in s[:h] if d) / h
    b = sum(1 for _, d in s[h:] if d) / (len(s) - h)
    return a - b


def build(ablate, suffix):
    env = dict(os.environ, OMEGA_ABLATE=ablate, OMEGA_OUT=suffix)
    r = subprocess.run(["node", "night/omega_retro_buildA.js"],
                       capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    o = {}
    for yr in (2013, 2015):
        f = os.path.join(OUT, f"omega_retro_A_{yr}{'_' + suffix if suffix else ''}.json")
        o[yr] = {t: float(v["omega"]) for t, v in
                 json.load(open(f, encoding="utf-8"))["items"].items() if v.get("omega") is not None}
        if suffix:
            os.remove(f)          # 中間物は残さない（正本と紛らわしい）
    return o


def main():
    lab = {}
    for yr in (2013, 2015):
        R = {key(x): x for x in load(RET[yr])}
        C = {key(x): x for x in load(COH[yr])}
        s = {}
        for t in set(R) | set(C):
            tr = (R.get(t) or {}).get("tr_cagr")
            fw = (C.get(t) or {}).get("fwd_roic_med5_a1")
            if tr is not None and fw is not None:
                s[t] = bool(tr > BREAK and fw >= FWD)
        lab[yr] = s

    def lift(om, yr):
        ts = [t for t in om[yr] if t in lab[yr]]
        return split_lift([(om[yr][t], lab[yr][t]) for t in ts])

    base_om = build("", "")            # 正本を上書きするが値は同じ（検算済み）
    base = {yr: lift(base_om, yr) for yr in (2013, 2015)}
    print(f"  baseline lift 2013 {base[2013]:+.4f} / 2015 {base[2015]:+.4f}\n")

    rows = {}
    for i, (fld, jp) in enumerate(FIELDS, 1):
        om = build(fld, f"abl{i}")
        d13, d15 = lift(om, 2013) - base[2013], lift(om, 2015) - base[2015]
        rows[fld] = dict(label=jp, lift_2013=round(lift(om, 2013), 4),
                         lift_2015=round(lift(om, 2015), 4),
                         drop_2013=round(-d13, 4), drop_2015=round(-d15, 4),
                         drop_min=round(min(-d13, -d15), 4),
                         contributes=bool(min(-d13, -d15) >= LINE))
        r = rows[fld]
        mark = "★貢献" if r["contributes"] else "  "
        print(f"  {mark} {jp:22s} 落ち {r['drop_2013']:+.4f}/{r['drop_2015']:+.4f}"
              f"（残る lift {r['lift_2013']:+.4f}/{r['lift_2015']:+.4f}）")

    win = [f for f, r in rows.items() if r["contributes"]]
    out = dict(generated=__import__("time").strftime("%Y-%m-%d"),
               prereg="out/omega_retro_prereg.json",
               line=f"中立固定で lift が {LINE} 以上落ちる（両ビンテージ）＝その欄は当たりを運んでいる",
               neutral="★中立固定＝全社をその欄の**中央値**に固定（null にしない。空欄は中立ではなく潰しだから）",
               base=dict(lift_2013=round(base[2013], 4), lift_2015=round(base[2015], 4)),
               rows=rows, contributing=win,
               CAVEAT="★当てる先は縮退している（durable ≒ 持続 ＝ 前方ROIC>=15%）。"
                      "入口 roic と前方ROIC は定義が違うが**同じ経済量を時点を変えて測ったもの**なので、"
                      "roic が効くのは『資本利益率は持続する』という事実であって Ω の設計の良さではない。"
                      "逆に堀が効かないのは、堀が検証されている領域（恒久毀損の回避）を"
                      "この当てる先が測っていないから＝**堀の反証ではない**。")
    json.dump(out, open(os.path.join(OUT, "omega_retro_h3.json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n  当たりを運んでいる欄: {('／'.join(win)) if win else '**なし**'}")
    print("\n→ out/omega_retro_h3.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
