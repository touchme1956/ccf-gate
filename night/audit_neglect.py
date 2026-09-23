#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_neglect.py — 発見度(Neglect/negS)は何で発火し、その向きは歴史と合うか（2026-09-19新設）

■ なぜ要ったか
  negS は evalScore を **±1.5/−1.0 直接** 動かす（index.html の唯一の「Ωに直接足し引きする修飾子」）。
  ところが `night/audit_deadweight.py --swing` の RANGES に **analysts / instOwn / mcap が入っていない**ので、
  「無駄か否か」の検査の対象から**主要な入力3本がまるごと抜けていた**（idx だけが入っていて
  「0.09pt＝ほぼ動かない」に見えていた）。＝**Ωを直接動かす経路が一度も裁かれていなかった。**

■ この道具が測る2つ
  ① 発火の内訳——「実データ（アナリスト数を実際に測った）」か「時価総額の代理（測っていないから）」か。
     代理は `anl<=0 && io<=0 && mcap>0` のときだけ働く＝**測らないほうが加点される**形になっていないか。
  ② 向き——negS が加点する帯（<$2B）と減点する帯（>$100B）の**その後の実現リターンと恒久毀損**を、
     repo の歴史在庫（2018/2013ビンテージ）で測る。⚠ 売上は時価総額の代理であって同じではない。

■ 判定は持たない（読むだけ・採点に一切触れない）。使い方: python3 night/audit_neglect.py [--json]
"""
import glob, json, os, statistics as st, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)


def num(v):
    try:
        if v in (None, "", "na"):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def negs(d):
    """index.html の negS をそのまま写す。⚠ 写しなので、門を変えたらここも変える（v9.9.65）。"""
    anl, io, mc = num(d.get("analysts")), num(d.get("instOwn")), num(d.get("mcap"))
    idx = d.get("idx") or ""
    s, parts, via = 0, [], False
    if anl > 0:
        a = 2 if anl <= 5 else 1 if anl <= 10 else 0 if anl <= 20 else -1 if anl <= 35 else -2
        s += a; parts.append(f"anl{anl:.0f}:{a:+d}")
    if 0 < io < 40:
        s += 1; parts.append(f"io{io:.0f}:+1")
    if idx == "no":
        s += 1; parts.append("idx=no:+1")
    if anl <= 0 and io <= 0 and mc > 0:
        via = True
        if mc < 2:
            s += 2; parts.append(f"mcap{mc:.2f}:+2(代理)")
        elif mc > 100:
            s -= 1; parts.append(f"mcap{mc:.0f}:-1(代理)")
    return s, (1.5 if s >= 2 else (-1.0 if s <= -2 else 0.0)), parts, via


def load(f):
    d = json.load(open(f))
    return d.get("rows") if isinstance(d, dict) else d


def bands(rows, label, out):
    """rows = [(ticker, 売上十億$, 前方年率)]"""
    if len(rows) < 20:
        print(f"   {label}: n={len(rows)} ＝少なすぎるので測らない"); return
    segs = [("★<$2B (negSが+2を与える帯)", [x for x in rows if x[1] < 2]),
            ("  $2-100B (据え置き)", [x for x in rows if 2 <= x[1] <= 100]),
            ("★>$100B (negSが−1を与える帯)", [x for x in rows if x[1] > 100])]
    rec = {}
    print(f"\n   {label}  n={len(rows)}")
    for nm, seg in segs:
        if not seg:
            print(f"      {nm:26s} n=0"); continue
        v = [x[2] for x in seg]
        r = {"n": len(seg), "median": round(st.median(v) * 100, 1),
             "p15": round(sum(1 for x in v if x >= .15) / len(v), 3),
             "impair": round(sum(1 for x in v if x <= -.15) / len(v), 3)}
        rec[nm.strip()] = r
        print(f"      {nm:26s} n={r['n']:4d}  中央 {r['median']:6.1f}%  15%+ {r['p15']:.2f}  恒久毀損 {r['impair']:.2f}")
    out[label] = rec


def main():
    packs = []
    for p in sorted(glob.glob("out/*_gate_pack.json")):
        try:
            packs.append((os.path.basename(p).split("_")[0], json.load(open(p))))
        except Exception:
            continue
    fired, real, proxy, other = [], [], [], []
    cov = {"analysts": 0, "instOwn": 0, "mcap": 0, "idx=no": 0}
    for t, d in packs:
        s, ap, parts, via = negs(d)
        cov["analysts"] += num(d.get("analysts")) > 0
        cov["instOwn"] += num(d.get("instOwn")) > 0
        cov["mcap"] += num(d.get("mcap")) > 0
        cov["idx=no"] += (d.get("idx") or "") == "no"
        if ap == 0:
            continue
        row = {"t": t, "applied": ap, "why": "/".join(parts)}
        fired.append(row)
        (proxy if via else (real if num(d.get("analysts")) > 0 else other)).append(row)

    print(f"■ ① 発火の内訳（全{len(packs)}社）")
    print(f"   入力の被覆: アナリスト数 {cov['analysts']}社 / 機関保有 {cov['instOwn']}社 / "
          f"時価総額 {cov['mcap']}社 / idx='no' {cov['idx=no']}社")
    print(f"   negApplied≠0 は {len(fired)}社")
    print(f"     実データ（アナリスト数を実際に測った）      {len(real):3d}社")
    print(f"   ★ 時価総額の代理（anl も io も未取得＝測っていない） {len(proxy):3d}社"
          f"  ← {len(proxy)/max(len(fired),1)*100:.0f}%")
    print(f"     機関保有 / idx だけ                      {len(other):3d}社")
    if proxy:
        ups = sum(1 for r in proxy if r["applied"] > 0)
        print(f"   ★ 代理経路の内訳: 加点 {ups}社 / 減点 {len(proxy)-ups}社"
              f"{'  ← 代理は加点しかしていない' if ups == len(proxy) else ''}")

    print("\n■ ② 向き——negS が加点する帯／減点する帯のその後（repo の歴史在庫）")
    print("   ⚠ 売上は時価総額の代理であって同じではない（歴史在庫に時価総額が無いため）")
    hist = {}
    try:
        ret18 = {r["ticker"]: r["tr_cagr"] for r in load("out/retro_returns_2018.json") if r.get("tr_cagr") is not None}
        f2 = {r["ticker"]: r for r in load("out/retro_features2_2018.json")}
        a18 = [(t, f2[t]["rev"] / 1e9, ret18[t]) for t in ret18 if t in f2 and f2[t].get("rev")]
        bands(a18, "2018年ビンテージ・全社（前方8.1年）", hist)

        def opmpct(o):  # 率/百分点の帯検問（fill_sht で踏んだ罠）
            o = o or 0
            return o * 100 if abs(o) <= 3 else o
        q = [x for x in a18 if f2[x[0]].get("opm") is not None
             and opmpct(f2[x[0]]["opm"]) >= 10 and f2[x[0]].get("fcfpos5")]
        bands(q, "2018年・質実証プール(opm≥10% ∧ 5年FCF全年黒字)", hist)
    except Exception as e:
        print(f"   2018が測れない: {e}")
    try:
        c13 = {r["ticker"]: r for r in load("out/retro_cohort_2013.json") if r.get("ticker") and r.get("rev_asof")}
        r13 = {r["ticker"]: r["tr_cagr"] for r in load("out/retro_returns_2013_all.json") if r.get("tr_cagr") is not None}
        bands([(t, c13[t]["rev_asof"] / 1e9, r13[t]) for t in r13 if t in c13],
              "2013年ビンテージ・全社（前方13.1年・別ビンテージ）", hist)
    except Exception as e:
        print(f"   2013が測れない: {e}")

    print("\n■ 限界（正直に）")
    print("   ・売上 ≠ 時価総額。刻み(<$2B / >$100B)は時価総額の線なので、当てているのは近い帯であって同じ帯ではない")
    print("   ・>$100B は n が 4〜13 と薄い（売上$100B超の社はそもそも少ない）")
    print("   ・母集団は生存者中心（左尾は 4.20〜19.16% の幅・2026-09-23 退場日の是正後／是正前は 2.00〜25.68%・retro_delisted_secpx 参照）")
    print("   ・窓はすべて2026年で終わる＝終点の相場が全ビンテージに等しく乗る")

    if "--json" in sys.argv:
        os.makedirs("out", exist_ok=True)
        json.dump({"asof": __import__("datetime").date.today().isoformat(),
                   "coverage": cov, "fired": fired,
                   "by_source": {"real": len(real), "proxy_mcap": len(proxy), "other": len(other)},
                   "history": hist},
                  open("out/audit_neglect.json", "w"), ensure_ascii=False, indent=1)
        print("\n→ out/audit_neglect.json")


if __name__ == "__main__":
    main()
