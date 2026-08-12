#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/hist_wd_verify_destroy.py — **破壊側の合格2本を潰しにかかる**（2026-08-11新設）

■ なぜ要るか
  2026-08-11 の対称探索（20エージェント）で、事前登録の5条件を通ったのは
  勝者11セル・**破壊2セル**だった。ところが反証にかけた10本は**すべて勝者側**で、
  破壊側は一度も叩かれていない（候補選抜を |lift| 上位10本で切ったため＝設計の落ち度）。
  したがって破壊側は「合格2件」とも「合格ゼロ」とも書けない＝**未確定**のまま残っていた。
  ユーザーの問いの半分は破壊側なので、ここを閉じる。

■ 叩く候補（out/hist_wd_verdict.json の pass_table より・P_full）
  D1: f2_netiss_r[上位1/4] ∧ f2_rnd_r[上位1/4]   維持lift +0.1704 / 分子16
  D2: f2_rev[下位1/4]     ∧ f2_rnd_r[上位1/4]   維持lift +0.1662 / 分子24

■ 仕事は反証であって確認ではない。6つ当てて、1つでも落ちたら不合格。
  1 ビンテージ符号   2016/2017/2018 すべてで lift>=0.15 を維持するか
  2 業種            同一 sic2 内でも残るか（Mantel-Haenszel）＋業種を1つずつ抜いて残るか
  3 irr の影        irr>=70 の層内でも残るか（測れないなら「判定不能」と書く）
  4 1社の影響       群の社を1社ずつ抜いて維持liftがどこまで動くか
  5 置換            **会社単位で全ビンテージ同時に**結果を並べ替える2000回
                    （ビンテージ内で独立に混ぜると従属が壊れ、偽陽性率が33倍過小に出る——
                     事前診断が実測済みの罠）
  6 既存関門との増分 その群の破壊社は、門が既に持つ関門で**既に落ちている社**ではないか

■ 破壊側の物差しは非対称（事前診断の指摘・ここでも効く）
  破壊の基準率は5.8〜8.1%なので、絶対差の lift では「破壊を**減らす**向き」は
  数学的に到達不能（群の破壊が0でも |lift| は基準率までしか下がらない）。
  よってここで測れるのは「破壊を**増やす**向き」だけ。比(risk ratio)も併記する。

実行: python3 night/hist_wd_verify_destroy.py   → out/hist_wd_verify_destroy.json
判定・採点・台帳・index.html・パックには一切触れない（読むだけ）。
"""
import json
import os
import random
import statistics as st
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
VINT = [2016, 2017, 2018]
SEED = 20260811
LIFT_LINE = 0.15
MIN_NUM = 5


def load():
    d = json.load(open("out/hist_wd_panel.json", encoding="utf-8"))
    return d["rows"]


ROWS = load()


def pop(v, name="P_full"):
    """そのビンテージの母集団（window_full で窓を揃える＝短窓の混入を除く）"""
    return [r for r in ROWS if r["vintage"] == v and r.get("has_outcome")
            and r.get("window_full") and r.get(name)]


def q(vals, p):
    """nearest-rank 分位（探索器と同じ約束。境界は strict で比較する）"""
    xs = sorted(x for x in vals if x is not None)
    if not xs:
        return None
    i = max(0, min(len(xs) - 1, int(round(p * (len(xs) - 1)))))
    return xs[i]


# 候補の定義。**閾値はそのビンテージの母集団内で引く**（探索器と同じ）
def cut_hi(col, p=0.75):
    def f(rs):
        t = q([r.get(col) for r in rs], p)
        return (lambda r: r.get(col) is not None and r[col] > t), f"{col}>{t:.6g}(上位{int((1-p)*100)}%)"
    return f


def cut_lo(col, p=0.25):
    def f(rs):
        t = q([r.get(col) for r in rs], p)
        return (lambda r: r.get(col) is not None and r[col] < t), f"{col}<{t:.6g}(下位{int(p*100)}%)"
    return f


CANDS = {
    "D1_netiss_hi_AND_rnd_hi": {
        "label": "f2_netiss_r[上位1/4] ∧ f2_rnd_r[上位1/4]",
        "legs": [cut_hi("f2_netiss_r"), cut_hi("f2_rnd_r")],
        "published_lift": 0.1704, "published_num": 16},
    "D2_rev_lo_AND_rnd_hi": {
        "label": "f2_rev[下位1/4] ∧ f2_rnd_r[上位1/4]",
        "legs": [cut_lo("f2_rev"), cut_hi("f2_rnd_r")],
        "published_lift": 0.1662, "published_num": 24},
}


def group_of(rs, legs):
    fns, desc = [], []
    for mk in legs:
        f, d = mk(rs)
        fns.append(f); desc.append(d)
    g = [r for r in rs if all(f(r) for f in fns)]
    return g, " ∧ ".join(desc)


def rate(rs, key="destroy"):
    n = len(rs)
    e = sum(1 for r in rs if r.get(key))
    return n, e, (e / n if n else None)


def cell(v, legs, key="destroy", popname="P_full"):
    rs = pop(v, popname)
    g, desc = group_of(rs, legs)
    n0, e0, p0 = rate(rs, key)
    n1, e1, p1 = rate(g, key)
    return {"vintage": v, "n_pop": n0, "events_pop": e0, "base": p0,
            "n_group": n1, "numerator": e1, "p_group": p1,
            "lift": (p1 - p0) if p1 is not None else None,
            "risk_ratio": (p1 / p0) if (p1 is not None and p0) else None,
            "cut": desc, "tickers": [r["ticker"] for r in g]}


# ── 2. 業種: Mantel-Haenszel（層=sic2）＋ 層を1つずつ抜く ──────────────────
def mh(v, legs, key="destroy"):
    rs = pop(v)
    g, _ = group_of(rs, legs)
    gs = set(r["ticker"] for r in g)
    strata = defaultdict(lambda: {"g": [], "o": []})
    for r in rs:
        s = r.get("sic2") or "NA"
        (strata[s]["g"] if r["ticker"] in gs else strata[s]["o"]).append(r)
    num = den = 0.0
    used = 0
    for s, d in strata.items():
        a = sum(1 for r in d["g"] if r.get(key)); n1 = len(d["g"])
        c = sum(1 for r in d["o"] if r.get(key)); n0 = len(d["o"])
        if n1 == 0 or n0 == 0:
            continue
        used += 1
        w = n1 * n0 / (n1 + n0)
        num += w * (a / n1 - c / n0); den += w
    return {"mh_lift": (num / den) if den else None, "strata_used": used,
            "group_covered": sum(len(d["g"]) for s, d in strata.items()
                                 if d["g"] and d["o"]) / max(1, len(g))}


def drop_one_sector(v, legs, key="destroy"):
    rs = pop(v)
    secs = sorted({(r.get("sic2") or "NA") for r in rs})
    out = []
    for s in secs:
        sub = [r for r in rs if (r.get("sic2") or "NA") != s]
        g, _ = group_of(sub, legs)          # ⚠閾値も抜いた後の母集団で引き直す（公平）
        n0, e0, p0 = rate(sub, key); n1, e1, p1 = rate(g, key)
        if n1 >= 1:
            out.append({"dropped": s, "n_group": n1, "numerator": e1,
                        "lift": (p1 - p0), "base": p0})
    out.sort(key=lambda x: x["lift"])
    return out


# ── 4. 1社抜き（jackknife・群の中の破壊社を1社ずつ抜く）──────────────────
def jackknife(legs, key="destroy"):
    cells = {v: cell(v, legs, key) for v in VINT}
    base_maint = min(c["lift"] for c in cells.values())
    # 群に居て破壊した社の和集合
    dest = set()
    for v in VINT:
        rs = pop(v); g, _ = group_of(rs, legs)
        for r in g:
            if r.get(key):
                dest.add(r["ticker"])
    res = []
    for t in sorted(dest):
        lifts = []
        for v in VINT:
            rs = [r for r in pop(v) if r["ticker"] != t]
            g, _ = group_of(rs, legs)
            n0, e0, p0 = rate(rs, key); n1, e1, p1 = rate(g, key)
            lifts.append((p1 - p0) if p1 is not None else -9)
        res.append({"ticker": t, "maintained_lift": min(lifts)})
    res.sort(key=lambda x: x["maintained_lift"])
    return {"base_maintained": base_maint, "n_destroyers_in_group": len(dest),
            "worst_after_drop": res[:6], "still_passes_all": all(r["maintained_lift"] >= LIFT_LINE for r in res)}


# ── 5. 置換（会社単位で全ビンテージ同時・層内）────────────────────────────
def permute(legs, key="destroy", n=2000, stratify_sector=True):
    """会社ごとの結果ベクトル（3ビンテージ分）を**丸ごと**入れ替える。
       ビンテージ内で独立に混ぜると従属が壊れ、偽陽性率が33倍過小に出る（事前診断の実測）。"""
    rows = {v: pop(v) for v in VINT}
    # 会社→(ビンテージ→行) と 会社→層
    byt = defaultdict(dict); sec = {}
    for v in VINT:
        for r in rows[v]:
            byt[r["ticker"]][v] = r
            sec[r["ticker"]] = r.get("sic2") or "NA"
    tick = sorted(byt)
    obs_vec = {t: {v: bool(byt[t].get(v, {}).get(key)) for v in VINT} for t in tick}
    # 群の所属は固定（特徴量は動かさない）——動かすのは結果ラベルだけ
    ing = {}
    for v in VINT:
        g, _ = group_of(rows[v], legs)
        s = set(r["ticker"] for r in g)
        for t in tick:
            ing.setdefault(t, {})[v] = (t in s)

    def maintained(vecs):
        lifts = []
        for v in VINT:
            n0 = e0 = n1 = e1 = 0
            for t in tick:
                if v not in byt[t]:
                    continue
                d = vecs[t][v]; n0 += 1; e0 += d
                if ing[t][v]:
                    n1 += 1; e1 += d
            if n1 == 0:
                return -9
            lifts.append(e1 / n1 - e0 / n0)
        return min(lifts)

    obs = maintained(obs_vec)
    rnd = random.Random(SEED)
    groups = defaultdict(list)
    for t in tick:
        groups[sec[t] if stratify_sector else "*"].append(t)
    hits = 0
    for _ in range(n):
        perm = {}
        for s, ts in groups.items():
            src = ts[:]; rnd.shuffle(src)
            for a, b in zip(ts, src):
                perm[a] = obs_vec[b]
        if maintained(perm) >= obs:
            hits += 1
    return {"observed_maintained_lift": obs, "n_perm": n,
            "p_value": (hits + 1) / (n + 1), "stratified_by_sector": stratify_sector}


# ── 6. 既存の関門との増分 ───────────────────────────────────────────────
def incremental(legs, key="destroy"):
    """群の破壊社のうち、門が既に持つ関門で**既に落ちている**社は何%か。
       増分がゼロなら、新しい指標としての実務的価値は無い。"""
    out = {}
    for v in VINT:
        rs = pop(v); g, _ = group_of(rs, legs)
        d = [r for r in g if r.get(key)]
        def shrink(r):   # 事業の収縮（v9.9.99・門に実装済み）
            return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
                    and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)
        def thin(r):     # 財務の薄さ（intcov<3＝門の nde>4 の歴史側の相当物）
            return r.get("f2_intcov") is not None and r["f2_intcov"] < 3
        def notq(r):     # 質実証を通らない
            return not r.get("P_quality")
        out[v] = {"n_destroyers": len(d),
                  "already_shrink": sum(1 for r in d if shrink(r)),
                  "already_thin": sum(1 for r in d if thin(r)),
                  "not_quality": sum(1 for r in d if notq(r)),
                  "caught_by_any": sum(1 for r in d if shrink(r) or thin(r) or notq(r))}
    return out


def irr_stratum(legs, key="destroy"):
    """3 irr の影。irr は 2016/2017 に読解が無いので、測れるのは 2018 と近傍のみ。"""
    out = {}
    for v in VINT:
        rs = [r for r in pop(v) if r.get("irr") is not None]
        if len(rs) < 30:
            out[v] = {"status": "判定不能", "n_with_irr": len(rs),
                      "why": "そのビンテージに irr の読解がほとんど無い"}
            continue
        s = [r for r in rs if r["irr"] >= 70]
        g, _ = group_of(s, legs)
        n0, e0, p0 = rate(s, key); n1, e1, p1 = rate(g, key)
        out[v] = {"status": "測定", "n_stratum": n0, "n_group": n1,
                  "numerator": e1, "lift": (p1 - p0) if p1 is not None else None}
    return out


def run(name, spec):
    legs = spec["legs"]
    cells = {v: cell(v, legs) for v in VINT}
    maint = min(c["lift"] for c in cells.values())
    minnum = min(c["numerator"] for c in cells.values())
    checks = {}
    # 1 ビンテージ符号／維持
    checks["1_vintage"] = {
        "lifts": {v: round(cells[v]["lift"], 4) for v in VINT},
        "risk_ratios": {v: (round(cells[v]["risk_ratio"], 2) if cells[v]["risk_ratio"] else None) for v in VINT},
        "maintained_lift": round(maint, 4), "min_numerator": minnum,
        "pass": maint >= LIFT_LINE and minnum >= MIN_NUM,
        "note_2013_2015": "f2_ 特徴量は 2013/2015 に構造的に存在しない＝外部標本ゼロ（判定不能）"}
    # 2 業種
    mhv = {v: mh(v, legs) for v in VINT}
    dos = {v: drop_one_sector(v, legs) for v in VINT}
    worst = {v: (dos[v][0] if dos[v] else None) for v in VINT}
    checks["2_sector"] = {
        "mh_lift": {v: (round(mhv[v]["mh_lift"], 4) if mhv[v]["mh_lift"] is not None else None) for v in VINT},
        "worst_drop_one_sector": {v: worst[v] for v in VINT},
        "pass": all((mhv[v]["mh_lift"] or 0) >= LIFT_LINE for v in VINT)
                and all((worst[v] or {}).get("lift", -9) >= LIFT_LINE for v in VINT)}
    # 3 irr
    ir = irr_stratum(legs)
    checks["3_irr"] = {"by_vintage": ir,
                       "pass": None if all(x.get("status") == "判定不能" for x in ir.values())
                       else all((x.get("lift") or -9) >= LIFT_LINE for x in ir.values() if x.get("status") == "測定")}
    # 4 1社抜き
    jk = jackknife(legs)
    checks["4_jackknife"] = {**jk, "pass": jk["still_passes_all"]}
    # 5 置換
    pm = permute(legs)
    checks["5_permutation"] = {**pm, "pass": pm["p_value"] <= 0.05}
    # 6 増分
    inc = incremental(legs)
    tot = sum(x["n_destroyers"] for x in inc.values())
    caught = sum(x["caught_by_any"] for x in inc.values())
    checks["6_incremental"] = {"by_vintage": inc, "total_destroyers": tot,
                               "already_caught_by_existing_gates": caught,
                               "incremental_share": (1 - caught / tot) if tot else None,
                               "pass": (tot > 0 and (1 - caught / tot) >= 0.3)}
    fails = [k for k, v in checks.items() if v.get("pass") is False]
    undet = [k for k, v in checks.items() if v.get("pass") is None]
    verdict = ("不合格（" + " / ".join(fails) + " で落ちた）") if fails else (
        "落とせなかった（ただし " + " / ".join(undet) + " は判定不能）" if undet else "落とせなかった")
    return {"label": spec["label"], "published_lift": spec["published_lift"],
            "published_numerator": spec["published_num"],
            "reproduced": {"maintained_lift": round(maint, 4), "min_numerator": minnum,
                           "matches_published": abs(maint - spec["published_lift"]) < 0.02},
            "cells": {v: {k: cells[v][k] for k in
                          ("n_pop", "events_pop", "base", "n_group", "numerator", "p_group",
                           "lift", "risk_ratio", "cut")} for v in VINT},
            "group_tickers_2018": cells[2018]["tickers"],
            "checks": checks, "verdict": verdict}


def main():
    out = {"generated": "2026-08-11", "tool": "night/hist_wd_verify_destroy.py",
           "role": "破壊側の合格2本を6検問で潰しにかかる。反証が仕事であって確認ではない",
           "prereg": "out/hist_winner_destroyer_prereg.json（22c740b・結果を見る前に固定）",
           "asymmetry_warning": "破壊の基準率は5.8〜8.1%。絶対差の lift では『破壊を減らす向き』は"
                                "数学的に到達不能なので、ここで測れるのは増やす向きだけ。比(risk_ratio)も併記した",
           "candidates": {}}
    for name, spec in CANDS.items():
        print(f"■ {name}: {spec['label']}")
        r = run(name, spec)
        out["candidates"][name] = r
        c = r["checks"]
        print(f"   再現 維持lift {r['reproduced']['maintained_lift']}（公表 {r['published_lift']}）"
              f" 一致={r['reproduced']['matches_published']}")
        for v in VINT:
            x = r["cells"][v]
            print(f"   {v}: 群{x['n_group']:>4}社 破壊{x['numerator']:>3} "
                  f"p={x['p_group']:.3f} base={x['base']:.3f} lift={x['lift']:+.4f} RR={x['risk_ratio']:.2f}")
        print(f"   1符号 {c['1_vintage']['pass']} / 2業種 {c['2_sector']['pass']}"
              f" / 3irr {c['3_irr']['pass']} / 4一社抜き {c['4_jackknife']['pass']}"
              f" / 5置換 p={c['5_permutation']['p_value']:.4f} {c['5_permutation']['pass']}"
              f" / 6増分 {c['6_incremental']['incremental_share']} {c['6_incremental']['pass']}")
        print(f"   → {r['verdict']}\n")
    json.dump(out, open("out/hist_wd_verify_destroy.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("→ out/hist_wd_verify_destroy.json")


if __name__ == "__main__":
    main()
