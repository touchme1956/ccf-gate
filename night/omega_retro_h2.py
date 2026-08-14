#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro_h2.py — H2: 重みの候補は現行より良いか（2026-08-14・H1_A 合格後に実施）

■ 事前登録は out/omega_retro_prereg.json（候補7つ・判定・停止規則とも撃つ前に固定済み）
  H2 の判定（登録のまま・ここで書き足さない）:
      baseline に対する lift の増分 >= 0.15 ∧ **両ビンテージ** ∧ 厳密OOS でも維持 ∧ 多重検定調整後 p < 0.05

■ 候補（事前登録の文言そのもの）
  C0 現行 / C1 roicPt の飽和を外す / C2 堀 .13→.20 / C3 堀 .13→.26 /
  C4 F .22→.15（余りは Q へ）/ C5 Q .35→.28（余りは sustain へ）/ C6 sustain .30→.38（余りは F へ）

  ⚠ C2/C3 は「余りをどこから取るか」が登録に無い。**残り3本を比のまま再正規化**する
    ——一本だけを削ると、その一本を同時に検定していることになるため。
  ⚠ C1「飽和を外す」も一意でない。**新しい定数を作らない形**にした——
    直前の区間 [30,90]→[40,96] の傾き(0.6/pt)をそのまま伸ばし、**目盛りの天井100**で止める
    （96→100 は 6.67pt なので roic 46.67 で 100）。任意の数字を置いていない。

■ やり方（shadow_gmpt.py と同じ型）
  index.html の1行だけを差し替えて buildA → **必ず元へ戻す**（sha256 で復元を検算）。

■ 多重検定（2026-08-12 に33倍の過小評価を踏んだ型を再演しない）
  会社単位でラベルを並べ替え、**両ビンテージに同じ置換**を当てる。
  族の統計量は「候補ごとの min(両ビンテージの増分)」の**最大値**＝family-wise。

使い方: python3 night/omega_retro_h2.py
出力: out/omega_retro_h2.json
"""
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")
IDX = os.path.join(BASE, "index.html")

BREAK, FWD = -0.15, 0.15
LINE, ALPHA = 0.15, 0.05
NPERM, SEED = 2000, 20260814

RET = {2013: "out/retro_returns_2013_all.json", 2015: "out/retro_returns_2015_q.json"}
COH = {2013: "out/retro_cohort_2013.json", 2015: "out/retro_cohort_2015.json"}

W0 = "let evalScore=gm([Q,sustain,F,moatIdx],[0.35,0.30,0.22,0.13]);"
R0 = ("function roicPt(r){const P=[[0,40],[8,50],[12,62],[16,72],[22,82],[30,90],[40,96],[200,96]];"
      "for(let i=0;i<P.length-1;i++){const[x0,y0]=P[i],[x1,y1]=P[i+1];"
      "if(r<=x1)return y0+(y1-y0)*(r-x0)/(x1-x0);}return 96;}")


def w(q, s, f, m):
    return f"let evalScore=gm([Q,sustain,F,moatIdx],[{q},{s},{f},{m}]);"


def renorm(moat):
    """C2/C3: 堀を上げた残りを Q/sustain/F の比(.35:.30:.22)のまま配り直す。"""
    rest, tot = 1.0 - moat, 0.35 + 0.30 + 0.22
    return [round(rest * x / tot, 5) for x in (0.35, 0.30, 0.22)] + [moat]


C = {
    "C0 現行": None,
    "C1 roicPt の飽和を外す": (R0, R0.replace("[40,96],[200,96]", "[40,96],[46.6667,100],[200,100]")
                              .replace("return 96;}", "return 100;}")),
    "C2 堀 .13→.20": (W0, w(*renorm(0.20))),
    "C3 堀 .13→.26": (W0, w(*renorm(0.26))),
    "C4 F .22→.15（余りはQ）": (W0, w(0.42, 0.30, 0.15, 0.13)),
    "C5 Q .35→.28（余りはsustain）": (W0, w(0.28, 0.37, 0.22, 0.13)),
    "C6 sustain .30→.38（余りはF）": (W0, w(0.35, 0.38, 0.14, 0.13)),
}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


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


def build():
    r = subprocess.run(["node", "night/omega_retro_buildA.js"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])


def read_omegas():
    o = {}
    for yr in (2013, 2015):
        d = json.load(open(os.path.join(OUT, f"omega_retro_A_{yr}.json"), encoding="utf-8"))["items"]
        o[yr] = {t: float(v["omega"]) for t, v in d.items() if v.get("omega") is not None}
    return o


def main():
    src = open(IDX, encoding="utf-8").read()
    before = sha(IDX)
    bak = {yr: os.path.join(OUT, f"omega_retro_A_{yr}.json") + ".h2bak" for yr in (2013, 2015)}
    for yr, b in bak.items():
        shutil.copy(os.path.join(OUT, f"omega_retro_A_{yr}.json"), b)

    # --- durable ラベル（候補に依らない） ---
    lab, keep = {}, {}
    for yr in (2013, 2015):
        R = {key(x): x for x in load(RET[yr])}
        Ck = {key(x): x for x in load(COH[yr])}
        s = {}
        for t in set(R) | set(Ck):
            tr = (R.get(t) or {}).get("tr_cagr")
            fw = (Ck.get(t) or {}).get("fwd_roic_med5_a1")
            if tr is not None and fw is not None:
                s[t] = bool(tr > BREAK and fw >= FWD)
        lab[yr] = s
        keep[yr] = set(s)

    om = {}
    try:
        for name, patch in C.items():
            if patch:
                old, new = patch
                if old not in src:
                    raise RuntimeError(f"{name}: 錨が index.html に無い")
                open(IDX, "w", encoding="utf-8").write(src.replace(old, new, 1))
            else:
                open(IDX, "w", encoding="utf-8").write(src)
            build()
            om[name] = read_omegas()
            print(f"  ✓ {name}")
    finally:
        open(IDX, "w", encoding="utf-8").write(src)
        for yr, b in bak.items():
            shutil.move(b, os.path.join(OUT, f"omega_retro_A_{yr}.json"))
    assert sha(IDX) == before, "★index.html の復元に失敗した"
    print(f"  ✓ index.html 復元を検算（sha256 {before[:12]}…）")

    # 厳密OOS: 2015 のうち 2013 に居ない社
    t13 = set(om["C0 現行"][2013])
    oos = [t for t in om["C0 現行"][2015] if t not in t13]

    def lift(name, yr, tick=None):
        o = om[name][yr]
        ts = [t for t in o if t in lab[yr] and (tick is None or t in tick)]
        return split_lift([(o[t], lab[yr][t]) for t in ts])

    base = {yr: lift("C0 現行", yr) for yr in (2013, 2015)}
    base_oos = lift("C0 現行", 2015, set(oos))

    rows = {}
    for name in C:
        l13, l15 = lift(name, 2013), lift(name, 2015)
        lo = lift(name, 2015, set(oos))
        inc13, inc15 = l13 - base[2013], l15 - base[2015]
        rows[name] = dict(lift_2013=round(l13, 4), lift_2015=round(l15, 4),
                          inc_2013=round(inc13, 4), inc_2015=round(inc15, 4),
                          inc_min=round(min(inc13, inc15), 4),
                          lift_oos=round(lo, 4), inc_oos=round(lo - base_oos, 4),
                          passed_line=bool(min(inc13, inc15) >= LINE and lo - base_oos >= LINE))

    # --- family-wise 置換 ---
    cand = [n for n in C if n != "C0 現行"]
    obs = max(rows[n]["inc_min"] for n in cand)
    rnd = random.Random(SEED)
    allt = sorted(set(lab[2013]) | set(lab[2015]))
    vals0 = [lab[2013].get(t, lab[2015].get(t)) for t in allt]
    hit = 0
    for _ in range(NPERM):
        v = list(vals0)
        rnd.shuffle(v)
        perm = dict(zip(allt, v))
        best = -9
        for n in cand:
            m = 9
            for yr in (2013, 2015):
                o, o0 = om[n][yr], om["C0 現行"][yr]
                ts = [t for t in o if t in perm]
                a = split_lift([(o[t], perm[t]) for t in ts])
                b = split_lift([(o0[t], perm[t]) for t in ts])
                m = min(m, a - b)
            best = max(best, m)
        if best >= obs:
            hit += 1
    p = (hit + 1) / (NPERM + 1)

    # --- ★instrument の分解能（合否には使わない・診断） ---
    #   「増分ゼロ」は候補が悪い証拠とは限らない——中央値二分は粗い統計なので、
    #   Ω̂ が動いても上半分の顔ぶれが変わらなければ lift は 1ミリも動かない。
    #   **どれだけ動いてどれだけ跨いだか**を出しておかないと、この不合格を読み違える。
    res = {}
    for name in cand:
        rr = {}
        for yr in (2013, 2015):
            o, o0 = om[name][yr], om["C0 現行"][yr]
            ts = [t for t in o if t in lab[yr]]
            moved = sum(1 for t in ts if abs(o[t] - o0[t]) > 1e-9)
            mx = max((abs(o[t] - o0[t]) for t in ts), default=0.0)
            ra = sorted(ts, key=lambda t: -o[t])
            rb = sorted(ts, key=lambda t: -o0[t])
            h = len(ts) // 2
            cross = len(set(ra[:h]) ^ set(rb[:h])) // 2
            rr[yr] = dict(n=len(ts), moved=moved, max_delta=round(mx, 2), crossed_median=cross)
        res[name] = rr

    passed = [n for n in cand if rows[n]["passed_line"]] if p < ALPHA else []
    out = dict(generated=__import__("time").strftime("%Y-%m-%d"),
               prereg="out/omega_retro_prereg.json",
               line=f"増分>={LINE} を両ビンテージ ∧ 厳密OOS でも維持 ∧ 多重検定調整後 p<{ALPHA}",
               note_C2C3="余りの出所が登録に無いので残り3本を比のまま再正規化（一本だけ削ると二つ同時に検定になる）",
               note_C1="飽和の外し方は『直前の傾き0.6/pt を目盛りの天井100まで伸ばす』＝新しい定数を置いていない",
               base=dict(lift_2013=round(base[2013], 4), lift_2015=round(base[2015], 4),
                         lift_oos=round(base_oos, 4), n_oos=len(oos)),
               rows=rows, family_p=round(p, 4), passed=passed,
               verdict="合格ゼロ" if not passed else "／".join(passed),
               resolution=res,
               RESOLUTION_WARNING="★この不合格の読み方——中央値二分は粗い。Ω̂ は動いているのに"
                                  "上半分の顔ぶれが変わらなければ lift は1ミリも動かない。"
                                  "resolution の crossed_median を見ること。0 なら測っているのは"
                                  "『候補が悪い』ではなく『この統計では分解できない』である。")
    json.dump(out, open(os.path.join(OUT, "omega_retro_h2.json"), "w"), ensure_ascii=False, indent=1)

    print("\n=== H2: 重みの候補は現行より良いか（事前登録どおり）===")
    print(f"  baseline  lift 2013 {base[2013]:+.4f} / 2015 {base[2015]:+.4f}"
          f" / 厳密OOS {base_oos:+.4f}（n={len(oos)}）")
    for n in C:
        r = rows[n]
        print(f"  {n:28s} lift {r['lift_2013']:+.4f}/{r['lift_2015']:+.4f}"
              f"  増分 {r['inc_2013']:+.4f}/{r['inc_2015']:+.4f}"
              f"  OOS増分 {r['inc_oos']:+.4f}")
    print(f"\n  最大の増分(min両ビンテージ) = {obs:+.4f} ／ family-wise 置換p = {p:.4f}")
    print(f"  判定: **{out['verdict']}**")
    print("\n--- ★instrument の分解能（合否に使わない診断）---")
    print("    Ω̂ が動いた社 / 最大差pt / **中央値を跨いだ社**")
    for n in cand:
        a, b = res[n][2013], res[n][2015]
        print(f"  {n:28s} 2013 {a['moved']:3d}社 {a['max_delta']:5.2f}pt 跨ぎ {a['crossed_median']:2d}"
              f"  ／ 2015 {b['moved']:3d}社 {b['max_delta']:5.2f}pt 跨ぎ {b['crossed_median']:2d}")
    print("\n→ out/omega_retro_h2.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
