# night/filing_behavior_test.py — 事前登録どおりに一度だけ当てる（2026-08-12新設）
#
# 事前登録: out/filing_behavior_prereg.json（結果を見る前にコミット済み・4b8b237）
# 入力: out/filing_behavior_{2018,2013}.json × out/retro_returns_*.json
#       質実証プールは 2018=retro_features2_2018.json（opm/fcfpos5）
#                      2013=retro_cohort_2013.json（opm/fcf_all_pos/op_all_pos）
#
# 判定（事前登録のまま・格子探索はしない）:
#   c1 lift >= 0.15 ／ c2 その群の15%+の実数 >= 5社 ／ c3 2ビンテージで符号が反転しない
#
# 判定の前に必ず出す（v1/v2の失敗を三度繰り返さないため）:
#   - 到達可能性: 各群で c2 の分子>=5 に届きうるか（群の大きさ×ベース率）
#   - 偽陽性率: 結果ラベルをプール内で並べ替える置換検定2000回
#   - 実効的に要求される lift（MIN_NUM が c1 を上書きしていないか）
#
# 実行: python3 night/filing_behavior_test.py [--json]

import json
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

HURDLE = 0.15
IMPAIR = -0.15
LIFT = 0.15
MIN_NUM = 5
NPERM = 2000

# 事前登録の split（ここを結果で動かさない）
CONT = ["age_yrs", "lag10k", "lag_d", "k8", "f4", "sz", "szchg"]
COUNT = ["nt", "nonrel", "audchg", "shelf", "d13d", "amend"]
SPECIAL = {"exec5": 2}  # 0-1 vs >=2

LABEL = {
    "age_yrs": "会社の年齢(年)",
    "lag10k": "10-K提出ラグ(日)",
    "lag_d": "提出ラグの変化(日・正=遅くなった)",
    "k8": "8-K年間件数",
    "f4": "Form4件数(直近1年)",
    "sz": "10-K提出サイズ",
    "szchg": "10-Kサイズ前年比(%)",
    "nt": "期限内に出せなかった(NT)",
    "nonrel": "過年度決算の非依拠(8-K 4.02)",
    "audchg": "監査人交代(8-K 4.01)",
    "shelf": "資金調達の提出(S-1/S-3/424B)",
    "d13d": "アクティビスト(SC 13D)",
    "amend": "10-K訂正(10-K/A)",
    "exec5": "役員異動(8-K 5.02)",
}
ALL = CONT + COUNT + list(SPECIAL)


def load(vint):
    fb = json.load(open(os.path.join(OUT, f"filing_behavior_{vint}.json")))
    rf = "retro_returns_2018.json" if vint == 2018 else "retro_returns_2013_all.json"
    rets = {r["ticker"]: r for r in json.load(open(os.path.join(OUT, rf)))["rows"]}

    qual = {}
    if vint == 2018:
        for r in json.load(open(os.path.join(OUT, "retro_features2_2018.json")))["rows"]:
            opm, f5 = r.get("opm"), r.get("fcfpos5")
            if opm is not None and f5 is not None:
                qual[r["ticker"]] = (opm >= 0.10) and bool(f5)
    else:
        for r in json.load(open(os.path.join(OUT, "retro_cohort_2013.json")))["rows"]:
            t, opm = r.get("ticker"), r.get("opm")
            if t and opm is not None:
                qual[t] = (opm >= 0.10) and bool(r.get("fcf_all_pos")) and bool(r.get("op_all_pos"))

    rows = []
    for t, v in fb["rows"].items():
        if not v or not v.get("fetched"):
            continue
        ret = rets.get(t)
        if not ret or ret.get("tr_cagr") is None:
            continue
        rec = {k: v.get(k) for k in ALL}
        rec.update({"t": t, "y": ret["tr_cagr"], "years": ret.get("years"), "q": qual.get(t)})
        rows.append(rec)
    return fb, rows


def stats(sub):
    n = len(sub)
    if not n:
        return None
    w = [r for r in sub if r["y"] >= HURDLE]
    imp = [r for r in sub if r["y"] <= IMPAIR]
    return {
        "n": n,
        "p15": round(len(w) / n, 3),
        "num15": len(w),
        "med": round(statistics.median(r["y"] for r in sub) * 100, 1),
        "p_imp": round(len(imp) / n, 3),
        "num_imp": len(imp),
    }


def split(rows, key):
    """事前登録どおりの二分。(群名, 部分集合) の2件と、欠測数を返す。"""
    have = [r for r in rows if r.get(key) is not None]
    miss = len(rows) - len(have)
    if len(have) < 10:
        return [], miss, None
    if key in COUNT:
        cut = 0.5
        lo = [r for r in have if r[key] == 0]
        hi = [r for r in have if r[key] >= 1]
        return [("0件", lo), ("1件以上", hi)], miss, cut
    if key in SPECIAL:
        c = SPECIAL[key]
        return [(f"{c-1}件以下", [r for r in have if r[key] < c]), (f"{c}件以上", [r for r in have if r[key] >= c])], miss, c
    med = statistics.median(r[key] for r in have)
    return [("中央値未満", [r for r in have if r[key] < med]), ("中央値以上", [r for r in have if r[key] >= med])], miss, round(med, 2)


def run_pool(rows, pool_name):
    base = stats(rows)
    res = {"pool": pool_name, "base": base, "indicators": {}}
    for k in ALL:
        groups, miss, cut = split(rows, k)
        if not groups:
            res["indicators"][k] = {"label": LABEL[k], "skip": "測れた社が10未満", "missing": miss}
            continue
        gs = []
        for gname, sub in groups:
            st = stats(sub)
            if not st:
                continue
            st["group"] = gname
            st["lift"] = round(st["p15"] - base["p15"], 3)
            st["lift_imp"] = round(st["p_imp"] - base["p_imp"], 3)
            # 到達可能性: この群の大きさで分子>=5 に届きうるか
            st["reach"] = st["n"] >= MIN_NUM
            # 実効的に要求される lift（MIN_NUM が c1 を上書きしていないか）
            need = max(MIN_NUM / st["n"], base["p15"] + LIFT) if st["n"] else None
            st["req_p15"] = round(need, 3) if need else None
            st["binds"] = "MIN_NUM" if (MIN_NUM / st["n"]) > (base["p15"] + LIFT) else "LIFT"
            st["pass"] = bool(st["lift"] >= LIFT and st["num15"] >= MIN_NUM)
            gs.append(st)
        res["indicators"][k] = {"label": LABEL[k], "cut": cut, "missing": miss, "groups": gs,
                                "pass": any(g["pass"] for g in gs)}
    return res


def perm_fp(rows, seed=20260812):
    """登録した手続き全体の偽陽性率。結果ラベルをプール内で並べ替え、
    14指標のどれか1本でも c1∧c2 を満たす確率を数える。
    分割は結果に依らないので一度だけ作って使い回す（並べ替えるのはラベルだけ）。"""
    rnd = random.Random(seed)
    idx = {r["t"]: i for i, r in enumerate(rows)}
    groups = []
    for k in ALL:
        gs, _, _ = split(rows, k)
        for _gn, sub in gs:
            if sub:
                groups.append([idx[r["t"]] for r in sub])
    labels = [1 if r["y"] >= HURDLE else 0 for r in rows]
    base_p = sum(labels) / len(labels)   # 並べ替えても母集団のベースは不変
    hit = 0
    for _ in range(NPERM):
        rnd.shuffle(labels)
        for g in groups:
            num = 0
            for i in g:
                num += labels[i]
            if num >= MIN_NUM and (num / len(g)) - base_p >= LIFT:
                hit += 1
                break
    return round(hit / NPERM, 4)


def orthogonality(rows, vint):
    """新系統が既存4系統とどれだけ別物かを実測（相関）。"""
    try:
        f2 = {r["ticker"]: r for r in json.load(open(os.path.join(OUT, f"retro_features2_{vint}.json")))["rows"]}
        fr = {r["t"]: r for r in json.load(open(os.path.join(OUT, f"retro_frame_{vint}.json")))["rows"]}
    except Exception:
        return None
    olds = {"opm": ("f2", "opm"), "cagr5": ("f2", "cagr5"), "conv5": ("f2", "conv5"),
            "per18": ("fr", "per18"), "mom1y": ("fr", "mom1y"), "mdd5": ("fr", "mdd5")}
    out = {}
    for k in ALL:
        row = {}
        for oname, (src, ok) in olds.items():
            xs, ys = [], []
            for r in rows:
                if r.get(k) is None:
                    continue
                o = (f2 if src == "f2" else fr).get(r["t"])
                if not o or o.get(ok) is None:
                    continue
                xs.append(r[k])
                ys.append(o[ok])
            if len(xs) >= 30:
                try:
                    row[oname] = round(statistics.correlation(xs, ys), 3)
                except Exception:
                    pass
        if row:
            out[k] = row
    return out


def main():
    as_json = "--json" in sys.argv
    report = {"generated": "2026-08-12", "prereg": "out/filing_behavior_prereg.json",
              "hurdle": HURDLE, "lift": LIFT, "min_num": MIN_NUM, "vintages": {}}

    for vint in (2018, 2013):
        path = os.path.join(OUT, f"filing_behavior_{vint}.json")
        if not os.path.exists(path):
            continue
        fb, rows = load(vint)
        pools = {"full": rows, "quality": [r for r in rows if r.get("q")]}
        v = {"asof_date": fb["asof_date"], "n_fetched": fb["n_fetched"],
             "n_joined": len(rows), "pools": {}}
        for pname, prows in pools.items():
            if len(prows) < 30:
                continue
            v["pools"][pname] = run_pool(prows, pname)
            v["pools"][pname]["false_positive_rate"] = perm_fp(list(prows))
        v["orthogonality"] = orthogonality(rows, vint)
        report["vintages"][vint] = v

    # c3: 2ビンテージで符号が反転しないか
    if 2018 in report["vintages"] and 2013 in report["vintages"]:
        rep = {}
        for pool in ("full", "quality"):
            a = report["vintages"][2018]["pools"].get(pool, {}).get("indicators", {})
            b = report["vintages"][2013]["pools"].get(pool, {}).get("indicators", {})
            for k in ALL:
                ga, gb = a.get(k, {}).get("groups"), b.get(k, {}).get("groups")
                if not ga or not gb:
                    continue
                # 「中央値以上 / 1件以上 / N件以上」側の lift の符号で見る
                la, lb = ga[-1]["lift"], gb[-1]["lift"]
                rep.setdefault(k, {})[pool] = {"lift2018": la, "lift2013": lb,
                                               "same_sign": (la >= 0) == (lb >= 0)}
        report["replication"] = rep
        verdict = []
        for k in ALL:
            r = rep.get(k, {})
            q18 = report["vintages"][2018]["pools"].get("quality", {}).get("indicators", {}).get(k, {})
            if q18.get("pass") and r.get("quality", {}).get("same_sign"):
                verdict.append(k)
        report["verdict"] = {"passed": verdict, "n_passed": len(verdict)}

    json.dump(report, open(os.path.join(OUT, "filing_behavior_test.json"), "w"), ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return

    for vint, v in report["vintages"].items():
        print(f"\n===== {vint}年ビンテージ（asof {v['asof_date']}・採取{v['n_fetched']}・突合{v['n_joined']}）=====")
        for pname, p in v["pools"].items():
            b = p["base"]
            print(f"\n-- プール {pname}: n={b['n']} 中央値{b['med']}%/年 P(15%+)={b['p15']} 恒久毀損={b['p_imp']}"
                  f"  偽陽性率={p['false_positive_rate']}")
            for k in ALL:
                d = p["indicators"].get(k, {})
                if "groups" not in d:
                    continue
                head = f"  {LABEL[k]:<32} 分割={d['cut']} 欠測{d['missing']}"
                print(head)
                for g in d["groups"]:
                    mark = "★合格" if g["pass"] else ""
                    print(f"     {g['group']:<12} n={g['n']:<4} 中央値{g['med']:>6}%  "
                          f"P15={g['p15']:.3f}({g['num15']}社) lift={g['lift']:+.3f}  "
                          f"毀損={g['p_imp']:.3f}({g['num_imp']}) 縛り={g['binds']} {mark}")
    if "verdict" in report:
        print(f"\n===== 判定 =====\n合格: {report['verdict']['passed'] or 'なし'}")


if __name__ == "__main__":
    main()
