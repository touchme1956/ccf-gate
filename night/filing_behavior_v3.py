# night/filing_behavior_v3.py — 事前登録 v3 を一度だけ当てる（2026-08-12新設）
#
# 事前登録: out/filing_behavior_prereg_v3.json（結果を見る前にコミット済み・db1e693）
#
# 問い: 『報告が綺麗に届かなかった』という提出書類の振る舞いは、遮断に値するか
# 判定プール: **規模で絞らない P_wide**（ユーザー明示指示 2026-08-12「大型にとらわれずにv3やって」）
# 判定ビンテージ: **2016 と 2017 だけ**（2013/2018 は 2026-08-12 に左尾まで見た＝汚染済み・記述のみ）
# 物差し: 主=元本割れ P(y<0)／従=恒久毀損 P(y<=-0.15)（hist_val v2 と同一）
# 合否: v2 の6基準（1 左尾>=2.0倍∧分子>=5 ／ 2 勝者を巻き込まない ／ 3 2016と2017の両方 ／
#       4 止率<=15% ／ 5 質実証プールでも1∧2 ／ 6 格子固定）
#
# 判定の前に必ず出す: 止率（結果を使わず計算できる）→ 基準4を満たさないセルは**結果を見る前に判定不能**／
#                     到達可能性／実効的に要求される元本割れ率／偽陽性率（置換2000回）
#
# 実行: python3 night/filing_behavior_v3.py

import json
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

RATIO = 2.0
MIN_NUM = 5
MAX_STOP = 0.15
NPERM = 2000
JUDGE = (2016, 2017)          # 未見のビンテージだけで判定する
DESCRIPTIVE = (2018, 2013)    # 汚染済み＝記述のみ

CELLS = {
    "A_report_integrity": ("報告の綻び(NT∪4.02∪4.01∪10-K/A)>=1", lambda r: (
        any((r.get(k) or 0) >= 1 for k in ("nt", "nonrel", "audchg", "amend")))),
    "A1_nt": ("NT(期限内に出せず)>=1", lambda r: (r.get("nt") or 0) >= 1),
    "A2_nonreliance": ("8-K 4.02(非依拠)>=1", lambda r: (r.get("nonrel") or 0) >= 1),
    "B60_lag": ("提出ラグ>=60日", lambda r: r.get("lag10k") is not None and r["lag10k"] >= 60),
    "B75_lag": ("提出ラグ>=75日", lambda r: r.get("lag10k") is not None and r["lag10k"] >= 75),
    "B90_lag": ("提出ラグ>=90日", lambda r: r.get("lag10k") is not None and r["lag10k"] >= 90),
}
# そのセルが「測れた」社かどうか（測れない社はプールから外す。0と読まない）
MEASURABLE = {
    "A_report_integrity": lambda r: True,
    "A1_nt": lambda r: True,
    "A2_nonreliance": lambda r: True,
    "B60_lag": lambda r: r.get("lag10k") is not None,
    "B75_lag": lambda r: r.get("lag10k") is not None,
    "B90_lag": lambda r: r.get("lag10k") is not None,
}


def load(vint):
    fb = json.load(open(os.path.join(OUT, f"filing_behavior_{vint}.json")))
    rf = {2018: "retro_returns_2018.json", 2017: "retro_returns_2017.json",
          2016: "retro_returns_2016.json", 2013: "retro_returns_2013_all.json"}[vint]
    rets = {r["ticker"]: r for r in json.load(open(os.path.join(OUT, rf)))["rows"]}
    qual, rev = {}, {}
    fpath = os.path.join(OUT, f"retro_features2_{vint}.json")
    if os.path.exists(fpath):
        for r in json.load(open(fpath))["rows"]:
            opm, f5 = r.get("opm"), r.get("fcfpos5")
            if opm is not None and f5 is not None:
                qual[r["ticker"]] = (opm >= 0.10) and bool(f5)
            if r.get("rev"):
                rev[r["ticker"]] = r["rev"]
    else:
        for r in json.load(open(os.path.join(OUT, "retro_cohort_2013.json")))["rows"]:
            t, opm = r.get("ticker"), r.get("opm")
            if t and opm is not None:
                qual[t] = (opm >= 0.10) and bool(r.get("fcf_all_pos")) and bool(r.get("op_all_pos"))
            if t and r.get("rev_asof"):
                rev[t] = r["rev_asof"]
    rows = []
    for t, v in fb["rows"].items():
        if not v or not v.get("fetched"):
            continue
        ret = rets.get(t)
        if not ret or ret.get("tr_cagr") is None:
            continue
        rec = dict(v)
        rec.update({"t": t, "y": ret["tr_cagr"], "years": ret.get("years"),
                    "q": qual.get(t), "rev": rev.get(t)})
        rows.append(rec)
    return fb, rows


def st(sub):
    n = len(sub)
    if not n:
        return None
    neg = [r for r in sub if r["y"] < 0]
    imp = [r for r in sub if r["y"] <= -0.15]
    return {"n": n, "p_neg": round(len(neg) / n, 3), "num_neg": len(neg),
            "p_imp": round(len(imp) / n, 3), "num_imp": len(imp),
            "med": round(statistics.median(r["y"] for r in sub) * 100, 1),
            "worst": round(min(r["y"] for r in sub) * 100, 1)}


def eval_cell(rows, cell):
    label, pred = CELLS[cell]
    pool = [r for r in rows if MEASURABLE[cell](r)]
    if len(pool) < 30:
        return {"label": label, "skip": "測れた社が30未満", "n_pool": len(pool)}
    stop = [r for r in pool if pred(r)]
    pas = [r for r in pool if not pred(r)]
    base, s, p = st(pool), st(stop), st(pas)
    stop_rate = round(len(stop) / len(pool), 3)
    out = {"label": label, "n_pool": len(pool), "stop_rate": stop_rate,
           "base": base, "stopped": s, "passed": p}
    # 結果を使わずに決まるもの
    out["c4_narrow"] = stop_rate <= MAX_STOP
    if not s:
        out["verdict"] = "判定不能（止めた社ゼロ）"
        return out
    # 到達可能性と実効要求
    need_ratio = base["p_neg"] * RATIO
    need_num = MIN_NUM / s["n"]
    out["reach"] = {"max_num_possible": s["n"],
                    "need_p_neg_by_ratio": round(need_ratio, 3),
                    "need_p_neg_by_min_num": round(need_num, 3),
                    "binds": "MIN_NUM" if need_num > need_ratio else "RATIO",
                    "reachable": s["n"] >= MIN_NUM}
    out["ratio"] = round(s["p_neg"] / base["p_neg"], 2) if base["p_neg"] else None
    out["ratio_imp"] = round(s["p_imp"] / base["p_imp"], 2) if base["p_imp"] else None
    out["c1_left_tail"] = bool(s["p_neg"] >= need_ratio and s["num_neg"] >= MIN_NUM)
    out["c2_no_winner_capture"] = bool(s["med"] <= p["med"])
    return out


def perm_fp(rows, seed=20260812):
    """6セルのどれか1つでも c1∧c2∧c4 を満たす確率（結果ラベルを並べ替え）。"""
    rnd = random.Random(seed)
    idx = {r["t"]: i for i, r in enumerate(rows)}
    cells = []
    for cell in CELLS:
        _lab, pred = CELLS[cell]
        pool = [r for r in rows if MEASURABLE[cell](r)]
        if len(pool) < 30:
            continue
        stop_i = [idx[r["t"]] for r in pool if pred(r)]
        pool_i = [idx[r["t"]] for r in pool]
        if not stop_i or len(stop_i) / len(pool_i) > MAX_STOP:
            continue          # c4 で結果を見る前に落ちるセルは数えない（登録どおり）
        cells.append((pool_i, set(stop_i)))
    if not cells:
        return None
    neg = [1 if r["y"] < 0 else 0 for r in rows]
    ys = [r["y"] for r in rows]
    hit = 0
    for _ in range(NPERM):
        order = list(range(len(rows)))
        rnd.shuffle(order)
        for pool_i, stop_s in cells:
            sn = sp = 0
            sy, py = [], []
            for i in pool_i:
                j = order[i]
                if i in stop_s:
                    sn += neg[j]
                    sy.append(ys[j])
                else:
                    sp += neg[j]
                    py.append(ys[j])
            bn = (sn + sp) / len(pool_i)
            if sn >= MIN_NUM and sy and (sn / len(sy)) >= bn * RATIO and statistics.median(sy) <= statistics.median(py):
                hit += 1
                break
    return round(hit / NPERM, 4)


def main():
    rep = {"generated": "2026-08-12", "prereg": "out/filing_behavior_prereg_v3.json",
           "judge_vintages": list(JUDGE), "descriptive_vintages": list(DESCRIPTIVE),
           "criteria": {"ratio": RATIO, "min_num": MIN_NUM, "max_stop": MAX_STOP},
           "vintages": {}}

    for vint in list(JUDGE) + list(DESCRIPTIVE):
        p = os.path.join(OUT, f"filing_behavior_{vint}.json")
        if not os.path.exists(p):
            continue
        fb, rows = load(vint)
        qrows = [r for r in rows if r.get("q")]
        v = {"asof_date": fb["asof_date"], "n": len(rows),
             "years": None, "wide": {}, "quality": {}, "role": "judge" if vint in JUDGE else "descriptive"}
        yrs = [r["years"] for r in rows if r.get("years")]
        v["years"] = round(statistics.median(yrs), 2) if yrs else None
        for cell in CELLS:
            v["wide"][cell] = eval_cell(rows, cell)
            if len(qrows) >= 30:
                v["quality"][cell] = eval_cell(qrows, cell)
        v["false_positive_rate"] = perm_fp(rows)
        # 記述のみ: 売上3分位
        have = sorted([r for r in rows if r.get("rev")], key=lambda r: r["rev"])
        if len(have) >= 90:
            n = len(have)
            v["by_size"] = {}
            for sname, sub in (("小", have[:n // 3]), ("中", have[n // 3:2 * n // 3]), ("大", have[2 * n // 3:])):
                v["by_size"][sname] = {c: eval_cell(sub, c) for c in ("A_report_integrity", "B90_lag")}
        rep["vintages"][vint] = v

    # 判定
    verdict = {}
    for cell in CELLS:
        det = {}
        ok = True
        for vint in JUDGE:
            d = rep["vintages"].get(vint, {}).get("wide", {}).get(cell, {})
            det[vint] = {k: d.get(k) for k in ("stop_rate", "c4_narrow", "c1_left_tail",
                                               "c2_no_winner_capture", "ratio", "ratio_imp")}
            if not (d.get("c4_narrow") and d.get("c1_left_tail") and d.get("c2_no_winner_capture")):
                ok = False
        q = all(rep["vintages"].get(vt, {}).get("quality", {}).get(cell, {}).get("c1_left_tail")
                and rep["vintages"].get(vt, {}).get("quality", {}).get(cell, {}).get("c2_no_winner_capture")
                for vt in JUDGE)
        verdict[cell] = {"label": CELLS[cell][0], "detail": det, "c5_incremental": bool(q), "pass": bool(ok and q)}
    rep["verdict"] = verdict
    rep["n_passed"] = sum(1 for v in verdict.values() if v["pass"])
    json.dump(rep, open(os.path.join(OUT, "filing_behavior_v3.json"), "w"), ensure_ascii=False, indent=1)

    for vint, v in rep["vintages"].items():
        tag = "【判定】" if v["role"] == "judge" else "【記述のみ・汚染済み】"
        print(f"\n===== {vint}年ビンテージ {tag} asof {v['asof_date']}・窓{v['years']}年・n={v['n']}"
              f"  偽陽性率={v['false_positive_rate']} =====")
        for cell, d in v["wide"].items():
            if "stopped" not in d or not d["stopped"]:
                print(f"  {d['label']:<34} 判定不能")
                continue
            b, s, p = d["base"], d["stopped"], d["passed"]
            c4 = "✓" if d["c4_narrow"] else f"✗(止率{d['stop_rate']:.0%}>15%)"
            if not d["c4_narrow"]:
                print(f"  {d['label']:<34} 止率{d['stop_rate']:.0%} → **結果を見る前に判定不能**（間引きであって遮断器ではない）")
                continue
            print(f"  {d['label']:<34} 止率{d['stop_rate']:.0%} n={s['n']}／{d['n_pool']}  縛り={d['reach']['binds']}")
            print(f"      止めた群 元本割れ{s['p_neg']:.3f}({s['num_neg']}社) ×{d['ratio']}  毀損{s['p_imp']:.3f}({s['num_imp']}) ×{d['ratio_imp']}"
                  f"  中央値{s['med']}%  最悪{s['worst']}%")
            print(f"      通過群   元本割れ{p['p_neg']:.3f}  中央値{p['med']}%   ベース元本割れ{b['p_neg']:.3f}（要求{d['reach']['need_p_neg_by_ratio']}）")
            print(f"      基準1 {'✓' if d['c1_left_tail'] else '✗'} ／ 基準2 {'✓' if d['c2_no_winner_capture'] else '✗'} ／ 基準4 {c4}")

    print("\n===== 判定（2016と2017の両方で 1∧2∧4、かつ質実証でも1∧2）=====")
    for cell, v in rep["verdict"].items():
        print(f"  {v['label']:<34} {'★合格' if v['pass'] else '不合格'}")
    print(f"\n合格 {rep['n_passed']} / {len(CELLS)}")


if __name__ == "__main__":
    main()
