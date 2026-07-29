#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_p1_cv.py — p1(ROIC安定性)の目盛りを「絶対σ」→「変動係数」に替えたら誰がどう動くかを実測（2026-07-29新設）

なぜ要るか（night/fill_derived_judgment.py の実測より）:
  現行の刻みは **絶対の百分点**（σ<3pt→90 / <6pt→80 / <10pt→65 / 二桁→50）。
  これは ROIC が 10-25% の帯を想定した目盛りで、ROIC が 50-130% ある会社では σ が必ず二桁になる。
  実測: 食い違い105社のサンプル25社で **ROIC平均40%超が18社**、台帳との一致率 **0/25**。
        V は ROIC 76/102/114/138/128% → σ21.5pt → 刻み50（実態は「一貫して桁外れに高い」）。
  **測っているのは不安定さではなく、ROICの絶対水準**になっていた。

  変動係数（CV = σ ÷ 平均）なら水準に依存しない。台帳との一致率は 32% へ上がる。
  ただしこれは**採点基準の変更**なので、`shadow_gmpt.py` と同じ作法で
  「誰がどう動くか」を先に実測する。**このスクリプトは正本を書き換えない。**

使い方:
  python3 night/shadow_p1_cv.py              CV刻みでの新p1と、Ω・投下可の変化を実測（書き換えない）
  python3 night/shadow_p1_cv.py --write      正本のp1をCV刻みで書き換える（要ユーザー明示指示）
"""
import json
import os
import statistics
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "night"))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")
CACHE = os.path.join(OUT, "_roic_series_cache.json")

from fill_derived_judgment import roic_series, p1_of   # noqa: E402  現行の絶対σ刻みはここが正本


def p1_cv(cv):
    """変動係数(σ÷平均・%)の刻み。絶対σの 3/6/10pt を ROIC平均20%の会社で等価になるよう置いた
       （3/20=15% / 6/20=30% / 10/20=50%）——現行の目盛りが想定していた帯で連続にするため。"""
    return 90 if cv < 15 else 80 if cv < 30 else 65 if cv < 50 else 50


def series_all():
    """ROIC5年系列を全米国株ぶん取る（SECを叩くのでキャッシュする）"""
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    ts = [f.split("_gate_pack")[0] for f in sorted(os.listdir(OUT)) if f.endswith("_gate_pack.json")]
    ts = [t for t in ts if not t[0].isdigit()]
    todo = [t for t in ts if t not in cache]
    for i, t in enumerate(todo, 1):
        try:
            ser, why = roic_series(t)
        except (Exception, SystemExit):
            ser, why = None, "取得失敗"
        cache[t] = {"ser": [[y, v] for y, v in ser] if ser else None, "why": why}
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return cache


def main():
    write = "--write" in sys.argv
    cache = series_all()
    rows = []
    for t, o in cache.items():
        if not o.get("ser"):
            continue
        vals = [v for _, v in o["ser"]]
        if len(vals) < 3:
            continue
        sd = statistics.pstdev(vals)
        mean = statistics.mean(vals)
        if mean <= 0:
            continue
        cv = sd / mean * 100
        d = json.load(open(f"{OUT}/{t}_gate_pack.json", encoding="utf-8"))
        cur = d.get("p1") if isinstance(d.get("p1"), (int, float)) else None
        rows.append(dict(t=t, cur=cur, sd=sd, mean=mean, cv=cv,
                         abs_g=p1_of(sd), cv_g=p1_cv(cv), ser=o["ser"]))

    print(f"\n■ ROIC5年系列が取れた米国株 {len(rows)}社\n")
    ok_abs = sum(1 for r in rows if r["cur"] is not None and abs(r["cur"] - r["abs_g"]) < 0.5)
    ok_cv = sum(1 for r in rows if r["cur"] is not None and abs(r["cur"] - r["cv_g"]) < 0.5)
    has = sum(1 for r in rows if r["cur"] is not None)
    print(f"  台帳p1との一致率: 現行の絶対σ刻み {ok_abs}/{has} ({ok_abs/max(has,1)*100:.0f}%)"
          f" / **変動係数刻み {ok_cv}/{has} ({ok_cv/max(has,1)*100:.0f}%)**")
    hi = [r for r in rows if r["mean"] >= 40]
    print(f"  ROIC平均40%以上の社: {len(hi)}社——うち絶対σ刻みが50を返すのは "
          f"{sum(1 for r in hi if r['abs_g']==50)}社 / 変動係数刻みでは {sum(1 for r in hi if r['cv_g']==50)}社")
    import collections
    print(f"  刻みの分布: 絶対σ {dict(sorted(collections.Counter(r['abs_g'] for r in rows).items()))}")
    print(f"              変動係数 {dict(sorted(collections.Counter(r['cv_g'] for r in rows).items()))}")

    # --- 門そのものでΩ・投下可の変化を実測 ---
    newp1 = {r["t"]: r["cv_g"] for r in rows}
    js = ("const {scorePack}=require('%s/night/score_all.js');const fs=require('fs');"
          "const NP=%s;const out=[];"
          "for(const f of fs.readdirSync('out')){if(!f.endsWith('_gate_pack.json'))continue;"
          "const t=f.split('_gate_pack')[0];let d;try{d=JSON.parse(fs.readFileSync('out/'+f,'utf8'));}catch(e){continue;}"
          "let a,b,xa,xb,ma,mb;try{"
          "a=scorePack(d);xa=ccfXJudge(d,+a.evalScore)||{};ma=ccfMoatGate(a,d)||{};"
          "const d2={...d};if(NP[t]!=null)d2.p1=NP[t];"
          "b=scorePack(d2);xb=ccfXJudge(d2,+b.evalScore)||{};mb=ccfMoatGate(b,d2)||{};"
          "}catch(e){continue;}"
          "const sa=+a.evalScore,sb=+b.evalScore;if(!isFinite(sa)||!isFinite(sb))continue;"
          "out.push([t,sa,sb,(sa>=75&&xa.xPass===true&&ma.pass===true),(sb>=75&&xb.xPass===true&&mb.pass===true),"
          "a.tierShort,b.tierShort]);}console.log(JSON.stringify(out));" % (BASE, json.dumps(newp1)))
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, cwd=BASE)
    try:
        sc = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print("\n実測に失敗:", (r.stderr or "")[-400:])
        return 1
    moved = [x for x in sc if abs(x[2] - x[1]) > 0.05]
    buy_in = [x for x in sc if not x[3] and x[4]]
    buy_out = [x for x in sc if x[3] and not x[4]]
    tier = [x for x in sc if x[5] != x[6]]
    print(f"\n■ 門そのもので実測（全{len(sc)}社）")
    print(f"  Ωが動く社: {len(moved)}　平均 {sum(x[2]-x[1] for x in moved)/max(len(moved),1):+.2f}pt"
          f" / 最大 {max((x[2]-x[1] for x in moved), default=0):+.1f}pt / 最小 {min((x[2]-x[1] for x in moved), default=0):+.1f}pt")
    print(f"  **投下可に入る: {len(buy_in)}社** {' '.join(x[0] for x in buy_in) or 'なし'}")
    print(f"  **投下可から外れる: {len(buy_out)}社** {' '.join(x[0] for x in buy_out) or 'なし'}")
    print(f"  ティアが変わる: {len(tier)}社 " + " ".join(f"{x[0]}({x[5]}→{x[6]})" for x in tier[:12]))
    print("\n  Ωの動きが大きい社（上位10・下位10）:")
    for x in sorted(moved, key=lambda x: -(x[2]-x[1]))[:10]:
        rr = next(r for r in rows if r["t"] == x[0])
        print(f"    {x[0]:7s} Ω{x[1]:5.1f}→{x[2]:5.1f} ({x[2]-x[1]:+5.1f})  p1 {rr['cur']}→{rr['cv_g']}  "
              f"ROIC平均{rr['mean']:6.1f}% σ{rr['sd']:5.1f}pt CV{rr['cv']:5.1f}%")
    for x in sorted(moved, key=lambda x: (x[2]-x[1]))[:10]:
        rr = next(r for r in rows if r["t"] == x[0])
        print(f"    {x[0]:7s} Ω{x[1]:5.1f}→{x[2]:5.1f} ({x[2]-x[1]:+5.1f})  p1 {rr['cur']}→{rr['cv_g']}  "
              f"ROIC平均{rr['mean']:6.1f}% σ{rr['sd']:5.1f}pt CV{rr['cv']:5.1f}%")

    if not write:
        print("\n※これは影の計測。正本は書き換えていない。--write で反映（要ユーザー明示指示）")
        return 0
    n = 0
    for r_ in rows:
        p = f"{OUT}/{r_['t']}_gate_pack.json"
        d = json.load(open(p, encoding="utf-8"))
        m = d.setdefault("_meta", {})
        old = d.get("p1")
        d["p1"] = r_["cv_g"]
        txt = " / ".join(f"{y} {v:.1f}%" for y, v in r_["ser"])
        m.setdefault("evidence", {})["p1"] = (
            f"【2026-07-29 機械算出・変動係数刻み(v9.9.50)】ROIC安定性＝のれん・無形除外ROIC{len(r_['ser'])}年系列の"
            f"**変動係数(σ÷平均)**。系列: {txt} → 平均 {r_['mean']:.1f}% / σ {r_['sd']:.1f}pt / "
            f"**CV {r_['cv']:.1f}%** → 刻み(CV<15→90 / <30→80 / <50→65 / 以上→50)で **{r_['cv_g']}**。"
            f"投下資本 = 自己資本 + 有利子負債 − のれん − 無形（門式）。出典: SEC XBRL companyfacts。")
        m.setdefault("provenance", {})["p1"] = "machine"
        m.setdefault("kenshi", []).append(
            f"2026-07-29 p1 {old}→{r_['cv_g']}（v9.9.50・目盛りを絶対σから変動係数へ）。"
            f"旧刻みは絶対の百分点なのでROICが高い会社ほど機械的にσが二桁になり、"
            f"**不安定さではなくROICの絶対水準を測っていた**（ROIC平均{r_['mean']:.1f}%・σ{r_['sd']:.1f}pt・CV{r_['cv']:.1f}%）。")
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n += 1
    print(f"\n→ {n}社の p1 を変動係数刻みへ更新。`node night/score_all.js` で実測すること")
    return 0


if __name__ == "__main__":
    sys.exit(main())
