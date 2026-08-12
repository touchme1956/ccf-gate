# night/retro_v4_test.py — 事前登録 v4 を一度だけ当てる（2026-08-12新設）
#
# 事前登録: out/retro_v4_prereg.json（突合せの前にコミット済み・5aae2e8）
#
# 主判定: agr5 / noa_r / gwimp_n の3本だけ（方向は片側固定・低い側が良い）
# 探索  : 新規27本（retro_fund2 20 + retro_shape 7）＋ 既存40本（features2 19 / path 7 / filing 14）
# 結果  : robust（主・経路つき）／deep（年率15%+・既存）／neg（元本割れ・既存）
# 基準  : lift >= 0.15 ∧ 分子 >= 5 ∧ **2016/2017/2018 の3ビンテージすべて**
#
# 判定の前に必ず出す（v1/v2/v3 の失敗を繰り返さない）:
#   到達可能性（主判定・探索の両方）／実効要求 P／族全体の偽陽性率（置換2000回）／新旧の相関
#
# 実行: python3 night/retro_v4_test.py [--json]

import json
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
ANCHORS = (2016, 2017, 2018)
LIFT, MIN_NUM, NPERM = 0.15, 5, 2000

PRIMARY = {
    "agr5":    ("総資産5年CAGR", "low"),
    "noa_r":   ("純営業資産/前期総資産", "low"),
    "gwimp_n": ("のれん減損の年数(5年)", "low"),
}
FUND = ["agr1", "agr5", "noa_r", "lease_r", "leasex", "sbc_r", "age_pp", "gwimp_n", "gwimp_r",
        "restr_n", "getr", "cetr", "etrgap", "defrev_gap", "shr_cagr", "shr_down",
        "dso", "dso_d", "dio_d", "divcut_n"]
SHAPE = ["mx1", "skew", "kurt", "dsd", "vol", "negrun", "beta", "ivol"]
FEAT2 = ["gm", "sga_r", "capex_r", "aturn", "accr", "streak_rev", "streak_opm", "fcfpos5",
         "intcov", "cash_r", "gw_r", "netiss_r", "rnd_r", "conv5", "payout5",
         "opm", "opmD5", "cagr5", "accel"]
PATH = ["rf5", "mom1y", "mdd5", "prox_hi", "vol_m", "upmo_r", "worst12"]
FILING = ["age_yrs", "lag10k", "lag_d", "k8", "f4", "sz", "szchg", "nt", "nonrel",
          "audchg", "shelf", "d13d", "amend", "exec5"]
COUNTISH = {"gwimp_n", "restr_n", "divcut_n", "shr_down", "negrun", "streak_rev", "streak_opm",
            "fcfpos5", "nt", "nonrel", "audchg", "shelf", "d13d", "amend", "exec5"}


def load(anchor):
    def j(p):
        return json.load(open(os.path.join(OUT, p)))
    rb = {r["t"]: r for r in j(f"retro_robust_{anchor}.json")["rows"]}
    fu = {r["ticker"]: r for r in j(f"retro_fund2_{anchor}.json")["rows"]}
    sh = {r["t"]: r for r in j(f"retro_shape_{anchor}.json")["rows"]}
    f2 = {r["ticker"]: r for r in j(f"retro_features2_{anchor}.json")["rows"]}
    fr = {r["t"]: r for r in j(f"retro_frame_{anchor}.json")["rows"]}   # path列を持つ
    fb = j(f"filing_behavior_{anchor}.json")["rows"]
    rows = []
    for t, r in rb.items():
        rec = {"t": t, "robust": r["robust"], "deep": r["deep"], "neg": r["cagr"] < 0,
               "cagr": r["cagr"], "mdd": r["mdd"]}
        for k in FUND:
            rec[k] = fu.get(t, {}).get(k)
        for k in SHAPE:
            rec[k] = sh.get(t, {}).get(k)
        for k in FEAT2:
            rec[k] = f2.get(t, {}).get(k)
        for k in PATH:
            rec[k] = fr.get(t, {}).get(k)
        v = fb.get(t) or {}
        for k in FILING:
            rec[k] = v.get(k) if v.get("fetched") else None
        q = f2.get(t, {})
        rec["q"] = (q.get("opm") is not None and q.get("fcfpos5") is not None
                    and q["opm"] >= 0.10 and bool(q["fcfpos5"]))
        rows.append(rec)
    return rows


def groups(rows, key):
    """事前登録どおりの二分。カウント系は 0 vs >=1、連続量は中央値で低い側/高い側。"""
    have = [r for r in rows if r.get(key) is not None]
    if len(have) < 30:
        return None, None, None
    if key in COUNTISH:
        vals = sorted(set(r[key] for r in have))
        if len(vals) < 2:
            return None, None, None
        cut = 0.5 if 0 in vals else statistics.median(r[key] for r in have)
        lo = [r for r in have if r[key] <= cut]
        hi = [r for r in have if r[key] > cut]
    else:
        cut = statistics.median(r[key] for r in have)
        lo = [r for r in have if r[key] < cut]
        hi = [r for r in have if r[key] >= cut]
    if len(lo) < 10 or len(hi) < 10:
        return None, None, None
    return {"低い側": lo, "高い側": hi}, round(cut, 4), len(rows) - len(have)


def rate(sub, oc):
    n = len(sub)
    num = sum(1 for r in sub if r[oc])
    return n, num, (num / n if n else None)


def eval_ind(rows, key, oc):
    gs, cut, miss = groups(rows, key)
    if not gs:
        return None
    bn, bnum, bp = rate(rows, oc)
    out = {"cut": cut, "missing": miss, "base_p": round(bp, 3), "base_num": bnum, "groups": {}}
    for gname, sub in gs.items():
        n, num, p = rate(sub, oc)
        need_lift = bp + LIFT
        need_num = MIN_NUM / n
        out["groups"][gname] = {
            "n": n, "num": num, "p": round(p, 3), "lift": round(p - bp, 3),
            "reachable": n >= MIN_NUM,
            "req_p": round(max(need_lift, need_num), 3),
            "binds": "MIN_NUM" if need_num > need_lift else "LIFT",
            "pass": bool(p - bp >= LIFT and num >= MIN_NUM),
        }
    return out


def perm_fp(rows, keys, oc, seed=20260812):
    """族全体の偽陽性率: 結果ラベルを並べ替え、keys のどれか1本・どちらかの群でも通る確率。"""
    rnd = random.Random(seed)
    idx = {r["t"]: i for i, r in enumerate(rows)}
    cells = []
    for k in keys:
        gs, _c, _m = groups(rows, k)
        if not gs:
            continue
        for _gn, sub in gs.items():
            cells.append([idx[r["t"]] for r in sub])
    if not cells:
        return None
    lab = [1 if r[oc] else 0 for r in rows]
    base_p = sum(lab) / len(lab)
    hit = 0
    for _ in range(NPERM):
        rnd.shuffle(lab)
        for g in cells:
            num = 0
            for i in g:
                num += lab[i]
            if num >= MIN_NUM and (num / len(g)) - base_p >= LIFT:
                hit += 1
                break
    return round(hit / NPERM, 4)


def main():
    as_json = "--json" in sys.argv
    data = {a: load(a) for a in ANCHORS}
    rep = {"generated": "2026-08-12", "prereg": "out/retro_v4_prereg.json",
           "criteria": {"lift": LIFT, "min_num": MIN_NUM, "vintages": list(ANCHORS)},
           "base": {}, "primary": {}, "sweep": {}, "fp": {}, "orthogonality": {}}

    for a in ANCHORS:
        rows = data[a]
        rep["base"][a] = {oc: {"n": len(rows), "p": round(sum(1 for r in rows if r[oc]) / len(rows), 3),
                               "num": sum(1 for r in rows if r[oc])} for oc in ("robust", "deep", "neg")}

    # ---- 主判定（3本・方向は片側固定・低い側が良い）----
    for k, (label, direction) in PRIMARY.items():
        det, ok = {}, True
        for a in ANCHORS:
            e = eval_ind(data[a], k, "robust")
            det[a] = e
            g = (e or {}).get("groups", {}).get("低い側")
            if not (g and g["pass"]):
                ok = False
        rep["primary"][k] = {"label": label, "direction": direction, "detail": det, "pass": ok}

    # ---- 探索（全指標 × 3結果）----
    ALL = [("新:会計", FUND), ("新:分布の形", SHAPE), ("既:財務比率", FEAT2),
           ("既:値動き", PATH), ("既:提出behavior", FILING)]
    for oc in ("robust", "deep", "neg"):
        rep["sweep"][oc] = {}
        for fam, keys in ALL:
            for k in keys:
                per, ok = {}, True
                best = None
                for a in ANCHORS:
                    e = eval_ind(data[a], k, oc)
                    per[a] = e
                if all(per[a] for a in ANCHORS):
                    for side in ("低い側", "高い側"):
                        if all(per[a]["groups"][side]["pass"] for a in ANCHORS):
                            best = side
                rep["sweep"][oc][k] = {"family": fam, "pass_side": best,
                                       "lift": {a: (per[a]["groups"]["低い側"]["lift"] if per[a] else None) for a in ANCHORS},
                                       "lift_hi": {a: (per[a]["groups"]["高い側"]["lift"] if per[a] else None) for a in ANCHORS},
                                       "detail_2018": per[2018]}
        allkeys = [k for _f, ks in ALL for k in ks]
        rep["fp"][oc] = {a: perm_fp(data[a], allkeys, oc) for a in ANCHORS}
        rep["fp"][f"{oc}_primary_only"] = {a: perm_fp(data[a], list(PRIMARY), oc) for a in ANCHORS}

    # ---- 新規指標 × 既存4系統 の相関（直交性）----
    rows = data[2018]
    olds = ["opm", "cagr5", "conv5", "accr", "mdd5", "mom1y", "lag10k"]
    for k in FUND + SHAPE:
        row = {}
        for o in olds:
            xs = [(r[k], r[o]) for r in rows if r.get(k) is not None and r.get(o) is not None]
            if len(xs) >= 50:
                try:
                    row[o] = round(statistics.correlation([x[0] for x in xs], [x[1] for x in xs]), 2)
                except Exception:
                    pass
        if row:
            rep["orthogonality"][k] = row

    json.dump(rep, open(os.path.join(OUT, "retro_v4_test.json"), "w"), ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1)[:20000])
        return

    print("===== ベース率 =====")
    for a in ANCHORS:
        b = rep["base"][a]
        print(f"  {a}: robust {b['robust']['p']}({b['robust']['num']}社) / deep {b['deep']['p']} / 元本割れ {b['neg']['p']}  n={b['robust']['n']}")
    print("\n===== 偽陽性率（置換2000回・族全体でどれか1本でも通る確率）=====")
    for oc in ("robust", "deep", "neg"):
        print(f"  {oc}: 全67本 {rep['fp'][oc]} ／ 主判定3本のみ {rep['fp'][oc+'_primary_only']}")

    print("\n===== 主判定（robust・低い側が良い・3ビンテージすべて）=====")
    for k, v in rep["primary"].items():
        print(f"\n  {v['label']}（{k}）  {'★合格' if v['pass'] else '不合格'}")
        for a in ANCHORS:
            e = v["detail"][a]
            if not e:
                print(f"    {a}: 判定不能")
                continue
            lo, hi = e["groups"]["低い側"], e["groups"]["高い側"]
            print(f"    {a}: 分割={e['cut']} 欠測{e['missing']} ベース{e['base_p']}  "
                  f"低い側 n={lo['n']} P={lo['p']}({lo['num']}社) lift={lo['lift']:+.3f} 要求{lo['req_p']}[{lo['binds']}] "
                  f"／ 高い側 P={hi['p']} lift={hi['lift']:+.3f}")

    print("\n===== 探索（3ビンテージすべてで lift>=0.15 ∧ 分子>=5 を満たした指標）=====")
    for oc in ("robust", "deep", "neg"):
        hits = [(k, v) for k, v in rep["sweep"][oc].items() if v["pass_side"]]
        print(f"  [{oc}] 合格 {len(hits)} / {len(rep['sweep'][oc])}本")
        for k, v in hits:
            print(f"     {v['family']:<14}{k:<12} {v['pass_side']}  lift(低)={v['lift']} lift(高)={v['lift_hi']}")


if __name__ == "__main__":
    main()
