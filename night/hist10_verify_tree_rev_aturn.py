#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_verify_tree_rev_aturn.py — 角度E の候補を**潰しにかかる**独立検証。

候補（探索側 out/hist10_angleE.json の cells_y10["P_full|cov90_14"]["down"]）:
    木(深さ2-3・best_leaf) の外側fold群 ＝ 実質 `f2_rev < 中央値 ∧ f2_aturn < 下位1/4`
    目的 = y10（tr_cagr >= 0.10）／母集団 = P_full|cov90_14（2289行・808社）
    n_group=235 ／ 分子(会社)=28 ／ lift=-0.19（**下向き＝避けるべき群**）

事前登録: out/hist10_prereg.json（**線はそこにある。この道具は一つも作らない**）
出力    : out/hist10_verify_tree_rev_aturn.json

────────────────────────────────────────────────────────────
この道具は「独立実装」である
────────────────────────────────────────────────────────────
探索側(night/hist10_angleE.py)は **bitmask** で木を育てる。この道具は
**集合(set of row index)** で同じ手続きを書き直す＝表現がまったく違う。
import するのは `json/math/random` だけで、hist10_diag / hist10_angleD / hist10_angleE の
どの関数も呼ばない（分位・木・fold・MH・既存関門をすべて自前で書く）。
**揃えるのは「約束」だけ**——分位の内挿・`>=` の向き・最小葉20・貪欲の同点処理・
fold の seed。約束を変えたら「一致しない」が実装差なのか本物なのか分からなくなる。

────────────────────────────────────────────────────────────
6つの検問（1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 再現   : 独立実装で n/分子/lift が一致するか（境界の約束まで）
2 ビンテージ: 2016/2017/2018 すべてで |lift|>=0.15 を維持するか
3 業種   : MH ＋ 業種を1つずつ抜いても残るか
4 irr の影: irr>=70 の層内でも残るか（測れないなら「判定不能」と書く）
5 置換   : 会社単位で全ビンテージ同時に並べ替える2000回（層なし／sic2層内の2通り）
6 増分   : 門が既に持つ関門で群の何割が説明されるか（7割超で不合格）

⚠ 候補に有利な数字を探さない。落とせなかった場合だけ「落とせなかった」と書く。
"""

import json
import math
import os
import random
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")
DEST = os.path.join(OUT, "hist10_verify_tree_rev_aturn.json")

# ── 事前登録の線（動かさない） ──
LIFT_LINE = 0.15
MIN_NUM = 20
INCREMENTAL_MAX_CAUGHT = 0.70

# ── 探索側と揃える「約束」（結果ではなく手続きの取り決め） ──
SEED = 20260812
TRIO = [2016, 2017, 2018]
CUT_QS = [0.25, 0.50, 0.75]
MIN_LEAF = 20
DEPTHS = (2, 3)
MODES = ("best_leaf", "leaf_union")
DIRS = ("up", "down")
N_OUTER = 5
N_INNER = 4
DIRECTION = "down"          # 候補の向き。先に固定（結果で選ばない）
POP = "P_full"
SUBSET = "cov90_14"
COV90 = ["aturn", "cagr5", "rev", "capex_r", "accel", "streak_rev", "rnd_r", "cash_r",
         "accr", "fcfpos5", "gw_r", "opm", "streak_opm", "opmD5"]
COLS = ["f2_" + k for k in COV90]
N_PERM = int(os.environ.get("VERIFY_NPERM", 2000))


def r4(x):
    return None if x is None else round(x, 4)


def rate(k, n):
    return (k / n) if n else None


# ─────────────────────── 読み込み（自前） ───────────────────────
def load_rows():
    with open(os.path.join(OUT, "hist_wd_panel.json"), encoding="utf-8") as f:
        panel = json.load(f)
    with open(os.path.join(OUT, "hist10_targets.json"), encoding="utf-8") as f:
        tg = json.load(f)
    tmap = {(r["ticker"], r["vintage"]): r for r in tg["rows"]}
    rows = []
    for r in panel["rows"]:
        if not (r["has_outcome"] and r["window_full"]):
            continue
        t = tmap.get((r["ticker"], r["vintage"]))
        if t is None:
            continue
        q = dict(r)
        q["y10"] = t.get("y10")
        rows.append(q)
    return panel, tg, rows


def build_set(rows):
    """complete-case（cov90_14 の全列が数値）・y10 が定義済み・P_full・2016-2018。"""
    rs = []
    for r in rows:
        if r["vintage"] not in TRIO:
            continue
        if r.get("y10") is None:
            continue
        ok = True
        for c in COLS:
            v = r.get(c)
            if v is None or isinstance(v, str):
                ok = False
                break
        if ok:
            rs.append(r)
    return rs


# ─────────────────────── 分位（約束: 線形内挿） ───────────────────────
def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = q * (len(xs) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


# ─────────────────────── fold（会社単位・seed を揃える） ───────────────────────
def ticker_folds(rs, k, seed):
    ts = sorted({r["ticker"] for r in rs})
    order = list(ts)
    random.Random(seed).shuffle(order)
    assign = {t: i % k for i, t in enumerate(order)}
    return [set(i for i, r in enumerate(rs) if assign[r["ticker"]] == f) for f in range(k)]


def inner_folds(rs, train_idx, k, seed):
    sub = sorted(train_idx)
    ts = sorted({rs[i]["ticker"] for i in sub})
    order = list(ts)
    random.Random(seed).shuffle(order)
    assign = {t: i % k for i, t in enumerate(order)}
    out = []
    for g in range(k):
        ite = set(i for i in sub if assign[rs[i]["ticker"]] == g)
        out.append((train_idx - ite, ite))
    return out


# ─────────────────────── 条件格子（train の分位・`>=`） ───────────────────────
def cond_grid(rs, train_idx):
    allidx = set(range(len(rs)))
    out, seen = [], set()
    for c in COLS:
        vals = [float(rs[i][c]) for i in sorted(train_idx)]
        for q in CUT_QS:
            cut = quantile(vals, q)
            if cut is None:
                continue
            m = frozenset(i for i in range(len(rs)) if float(rs[i][c]) >= cut)
            if len(m) == 0 or len(m) == len(rs):
                continue
            key = (c, m)
            if key in seen:
                continue
            seen.add(key)
            out.append(("%s>=q%d" % (c, int(q * 100)), c, m, allidx - m))
    return out


# ─────────────────────── 木（貪欲・エントロピー・最小葉20） ───────────────────────
def went(k, n):
    if n <= 0 or k <= 0 or k >= n:
        return 0.0
    p = k / n
    return -n * (p * math.log(p) + (1 - p) * math.log(1 - p))


def grow(rule_idx, node_idx, depth, lab, conds, leaves, splits, level, path):
    n = len(node_idx)
    k = sum(1 for i in node_idx if lab[i])
    if depth <= 0 or n < 2 * MIN_LEAF:
        leaves.append((rule_idx, n, k, list(path)))
        return
    base_w = went(k, n)
    best = None
    for ci, (_name, _col, cm, _inv) in enumerate(conds):
        L = node_idx & cm
        nl = len(L)
        if nl < MIN_LEAF:
            continue
        nr = n - nl
        if nr < MIN_LEAF:
            continue
        kl = sum(1 for i in L if lab[i])
        gain = base_w - went(kl, nl) - went(k - kl, nr)
        if best is None or gain > best[0]:      # 同点は先着（探索側と同じ約束）
            best = (gain, ci, L)
    if best is None or best[0] <= 1e-12:
        leaves.append((rule_idx, n, k, list(path)))
        return
    _, ci, L = best
    name, col, cm, inv = conds[ci]
    splits.append({"level": level, "cond": name, "col": col, "n_node": n})
    grow(rule_idx & cm, L, depth - 1, lab, conds, leaves, splits, level + 1, path + [name])
    grow(rule_idx & inv, node_idx & inv, depth - 1, lab, conds, leaves, splits,
         level + 1, path + ["!" + name])


def grow_once(rs, train_idx, conds, lab, depth):
    leaves, splits = [], []
    grow(set(range(len(rs))), set(train_idx), depth, lab, conds, leaves, splits, 0, [])
    ntr = len(train_idx)
    base_tr = (sum(1 for i in train_idx if lab[i]) / ntr) if ntr else 0.0
    return leaves, splits, base_tr


def extract(leaves, base_tr, direction, mode):
    cand = [x for x in leaves if x[1] >= MIN_LEAF]
    if not cand:
        return set(), []
    if mode == "best_leaf":
        best = None
        for rule_idx, n, k, path in cand:
            d = k / n - base_tr
            if (d > 0) if direction == "up" else (d < 0):
                if best is None or abs(d) > abs(best[0]):
                    best = (d, rule_idx, path, n, k)
        if not best:
            return set(), []
        return best[1], [{"path": best[2], "n_train": best[3], "k_train": best[4],
                          "p_train": r4(rate(best[4], best[3]))}]
    m, used = set(), []
    for rule_idx, n, k, path in cand:
        d = k / n - base_tr
        if (d > 0) if direction == "up" else (d < 0):
            m |= rule_idx
            used.append({"path": path, "n_train": n, "k_train": k, "p_train": r4(rate(k, n))})
    return m, used


# ─────────────────────── 入れ子交差検証（外側fold の群だけ返す） ───────────────────────
def nested_oof(rs, lab, direction, keep_detail=True):
    n = len(rs)
    allidx = set(range(n))
    te_folds = ticker_folds(rs, N_OUTER, SEED)
    oof = set()
    chosen = []
    for fi, te in enumerate(te_folds):
        tr = allidx - te
        base_tr = sum(1 for i in tr if lab[i]) / len(tr)
        inner = inner_folds(rs, tr, N_INNER, SEED + 1000 + fi)
        gi_grids = [cond_grid(rs, itr) for itr, _ in inner]
        acc = {(dp, md): set() for dp in DEPTHS for md in MODES}
        for gi, (itr, ite) in enumerate(inner):
            g = gi_grids[gi]
            for dp in DEPTHS:
                leaves, _sp, b = grow_once(rs, itr, g, lab, dp)
                for md in MODES:
                    rm, _u = extract(leaves, b, direction, md)
                    acc[(dp, md)] |= (rm & ite)
        best = None
        for dp in DEPTHS:                    # 探索側の反復順（dp -> md）を揃える
            for md in MODES:
                gg = acc[(dp, md)]
                m = len(gg)
                if m == 0:
                    continue
                k = sum(1 for i in gg if lab[i])
                lf = k / m - base_tr
                s = lf if direction == "up" else -lf
                if m < MIN_NUM:
                    s -= 1e6
                if best is None or s > best[0]:
                    best = (s, dp, md)
        if best is None:
            chosen.append(None)
            continue
        _s, dp, md = best
        og = cond_grid(rs, tr)
        leaves, splits, b = grow_once(rs, tr, og, lab, dp)
        rm, used = extract(leaves, b, direction, md)
        oof |= (rm & te)
        ent = {"fold": fi, "depth": dp, "mode": md, "inner_score": r4(_s),
               "n_rule_train": len(rm & tr), "n_rule_test": len(rm & te)}
        if keep_detail:
            ent["splits"] = splits
            ent["leaves_used"] = used
        chosen.append(ent)
    return oof, chosen


# ─────────────────────── 統計（自前） ───────────────────────
def lift_of(rs, lab, gidx, idx=None):
    idx = set(range(len(rs))) if idx is None else set(idx)
    n = len(idx)
    if n == 0:
        return None
    base = sum(1 for i in idx if lab[i]) / n
    g = idx & gidx
    if not g:
        return {"n": n, "base": r4(base), "n_group": 0, "k": 0, "p_group": None, "lift": None}
    k = sum(1 for i in g if lab[i])
    return {"n": n, "base": r4(base), "n_group": len(g), "k": k,
            "p_group": r4(k / len(g)), "lift": r4(k / len(g) - base)}


def mh_diff(rs, lab, gidx, idx, key):
    """MH リスク差。層は key(r)。層の足切りは探索側と同じ n1>=3 ∧ n0>=3。"""
    strata = defaultdict(lambda: [0, 0, 0, 0])   # n1,k1,n0,k0
    for i in idx:
        s = key(rs[i])
        if s is None:
            continue
        d = strata[s]
        w = 1 if lab[i] else 0
        if i in gidx:
            d[0] += 1
            d[1] += w
        else:
            d[2] += 1
            d[3] += w
    num = den = 0.0
    used = drop = 0
    rows_kept = 0
    grp_kept = 0
    for _s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        w = n1 * n0 / (n1 + n0)
        num += w * (k1 / n1 - k0 / n0)
        den += w
        used += 1
        rows_kept += n1 + n0
        grp_kept += n1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(num / den), "strata_used": used, "strata_dropped": drop,
            "rows_in_kept_strata": rows_kept, "group_rows_in_kept_strata": grp_kept}


def main():
    panel, tg, rows = load_rows()
    rs = build_set(rows)
    n = len(rs)
    lab = [1 if r["y10"] else 0 for r in rs]
    companies = sorted({r["ticker"] for r in rs})

    out = {
        "generated": "2026-08-12",
        "tool": "night/hist10_verify_tree_rev_aturn.py",
        "prereg": "out/hist10_prereg.json",
        "candidate": {
            "angle": "E（決定木・入れ子交差検証・外側fold の群）",
            "rule_in_words": "f2_rev < 中央値 ∧ f2_aturn < 下位1/4（5foldのうち4foldで同一）",
            "target": "y10 = tr_cagr >= 0.10",
            "population": "P_full|cov90_14（2016/2017/2018 プール）",
            "direction": "down（避けるべき群）",
            "claimed": {"n_group": 235, "numerator_companies": 28, "lift": -0.19},
        },
        "independence": "hist10_diag / hist10_angleD / hist10_angleE を一つも import しない。"
                        "bitmask ではなく集合で書き直した独立実装。約束（分位の内挿・>= の向き・"
                        "最小葉20・同点先着・fold の seed）だけを揃えてある",
        "pass_line_used": {"lift": LIFT_LINE, "min_numerator": MIN_NUM,
                           "incremental_max_caught": INCREMENTAL_MAX_CAUGHT,
                           "note": "事前登録の値。動かしていない"},
        "analysis_set": {"n_rows": n, "n_companies": len(companies),
                         "base_rate": r4(sum(lab) / n),
                         "by_vintage": {}},
    }
    for v in TRIO:
        idx = [i for i in range(n) if rs[i]["vintage"] == v]
        out["analysis_set"]["by_vintage"][str(v)] = {
            "n": len(idx), "base": r4(sum(lab[i] for i in idx) / len(idx))}

    # ── 検問1: 再現 ───────────────────────────────────────────
    oof, chosen = nested_oof(rs, lab, DIRECTION)
    g_tick = {rs[i]["ticker"] for i in oof}
    num_rows = sum(1 for i in oof for _ in [0] if lab[i])
    num_tick = len({rs[i]["ticker"] for i in oof if lab[i]})
    base = sum(lab) / n
    obs_lift = (num_rows / len(oof) - base) if oof else None
    paths = []
    for c in chosen:
        if c and c.get("leaves_used"):
            paths.append("｜".join(c["leaves_used"][0]["path"]) if c["mode"] == "best_leaf"
                         else "leaf_union(%d葉)" % len(c["leaves_used"]))
        else:
            paths.append(None)
    pc = defaultdict(int)
    for p in paths:
        pc[p] += 1
    t1 = {
        "n_group_rows": len(oof), "numerator_rows": num_rows,
        "n_group_companies": len(g_tick), "numerator_companies": num_tick,
        "base": r4(base), "p_group": r4(rate(num_rows, len(oof))), "lift": r4(obs_lift),
        "match_claimed": {
            "n_group": len(oof) == 235,
            "numerator_companies": num_tick == 28,
            "lift": (obs_lift is not None and abs(obs_lift - (-0.19)) < 0.0051),
        },
        "per_fold_rule": paths,
        "rule_agreement": {str(k): v for k, v in sorted(pc.items(), key=lambda x: -x[1])},
        "chosen_detail": chosen,
    }
    core = ["!f2_rev>=q50", "!f2_aturn>=q25"]
    n_core = sum(1 for c in chosen
                 if c and c.get("leaves_used") and c["mode"] == "best_leaf"
                 and c["leaves_used"][0]["path"][:2] == core)
    n_exact = max(pc.values()) if pc else 0
    t1["rule_stability_correction"] = {
        "claimed_in_brief": "5foldのうち4foldで同一",
        "measured_exact_same_leaf_path": n_exact,
        "measured_core_prefix_present": n_core,
        "core": "!f2_rev>=q50 ∧ !f2_aturn>=q25",
        "note": "**同一の葉は最大2fold**。ただし2条件の核は**5/5 fold で経路の先頭にある**"
                "（残り3foldはその核の部分集合を葉に採る）＝安定性の主張はむしろ強い側に訂正",
    }
    t1["verdict"] = ("一致（再現した）" if all(t1["match_claimed"].values())
                     else "一致しない＝独立実装で再現できない")
    out["test1_reproduce"] = t1

    # ── 検問2: ビンテージ ───────────────────────────────────────
    pv = {}
    for v in TRIO:
        idx = [i for i in range(n) if rs[i]["vintage"] == v]
        pv[str(v)] = lift_of(rs, lab, oof, idx)
    sign = -1 if DIRECTION == "down" else 1
    ok2 = all(x["lift"] is not None and abs(x["lift"]) >= LIFT_LINE
              and (1 if x["lift"] > 0 else -1) == sign for x in pv.values())
    out["test2_vintage"] = {"per_vintage": pv, "all_maintain_0.15": ok2,
                            "verdict": "通過" if ok2 else "不合格"}

    # ── 検問3: 業種 ─────────────────────────────────────────
    allidx = set(range(n))
    mh_pool_sic = mh_diff(rs, lab, oof, allidx, lambda r: r.get("sic2"))
    mh_pool_sicv = mh_diff(rs, lab, oof, allidx,
                           lambda r: (r.get("sic2"), r["vintage"]) if r.get("sic2") else None)
    mh_pv = {}
    for v in TRIO:
        idx = [i for i in range(n) if rs[i]["vintage"] == v]
        mh_pv[str(v)] = mh_diff(rs, lab, oof, idx, lambda r: r.get("sic2"))
    # 業種構成
    comp = []
    secs = sorted({rs[i].get("sic2") for i in range(n) if rs[i].get("sic2")})
    for s in secs:
        idx = [i for i in range(n) if rs[i].get("sic2") == s]
        gi = [i for i in idx if i in oof]
        if not gi:
            continue
        sb = sum(lab[i] for i in idx) / len(idx)
        comp.append({"sic2": s, "group_rows": len(gi),
                     "share_of_group": r4(len(gi) / len(oof)),
                     "share_of_population": r4(len(idx) / n),
                     "over_representation_x": r4((len(gi) / len(oof)) / (len(idx) / n)),
                     "sector_base_rate": r4(sb),
                     "group_rate_in_sector": r4(sum(lab[i] for i in gi) / len(gi)),
                     "within_sector_lift": r4(sum(lab[i] for i in gi) / len(gi) - sb)})
    comp.sort(key=lambda x: -x["group_rows"])
    # 業種を1つずつ抜く（プール／ビンテージ別）。足切りは探索側と同じ nb>=40・群>=10
    drop_pool = []
    for s in secs:
        idx = [i for i in range(n) if rs[i].get("sic2") != s]
        if len(idx) < 40:
            continue
        gi = set(idx) & oof
        if len(gi) < 10:
            continue
        b = sum(lab[i] for i in idx) / len(idx)
        k = sum(lab[i] for i in gi)
        drop_pool.append({"dropped_sector": s, "n_group": len(gi), "k": k,
                          "lift": r4(k / len(gi) - b)})
    drop_pool.sort(key=lambda x: abs(x["lift"]))
    drop_pv = {}
    for v in TRIO:
        vi = [i for i in range(n) if rs[i]["vintage"] == v]
        worst = None
        for s in secs:
            idx = [i for i in vi if rs[i].get("sic2") != s]
            if len(idx) < 40:
                continue
            gi = set(idx) & oof
            if len(gi) < 10:
                continue
            b = sum(lab[i] for i in idx) / len(idx)
            k = sum(lab[i] for i in gi)
            lf = k / len(gi) - b
            e = {"dropped_sector": s, "n_group": len(gi), "k": k, "lift": r4(lf)}
            if worst is None or abs(lf) < abs(worst["lift"]):
                worst = e
        drop_pv[str(v)] = worst
    mh_ok = all(m and abs(m["mh_risk_diff"]) >= LIFT_LINE
                and (1 if m["mh_risk_diff"] > 0 else -1) == sign
                for m in list(mh_pv.values()) + [mh_pool_sic, mh_pool_sicv])
    dos_ok = all(w and abs(w["lift"]) >= LIFT_LINE and (1 if w["lift"] > 0 else -1) == sign
                 for w in list(drop_pv.values()) + ([drop_pool[0]] if drop_pool else [None]))
    out["test3_sector"] = {
        "mh_pooled_by_sic2": mh_pool_sic,
        "mh_pooled_by_sic2_x_vintage": mh_pool_sicv,
        "mh_per_vintage": mh_pv,
        "share_of_group_measurable_pooled":
            r4(mh_pool_sic["group_rows_in_kept_strata"] / len(oof)) if mh_pool_sic else None,
        "share_of_group_measurable_pooled_sic_x_vintage":
            r4(mh_pool_sicv["group_rows_in_kept_strata"] / len(oof)) if mh_pool_sicv else None,
        "sector_composition": comp,
        "drop_one_sector_pooled_worst5": drop_pool[:5],
        "drop_one_sector_per_vintage_worst": drop_pv,
        "mh_ok": mh_ok, "drop_one_sector_ok": dos_ok,
        "verdict": "通過" if (mh_ok and dos_ok) else "不合格",
    }

    # ── 検問4: irr の影 ───────────────────────────────────────
    irr4 = {}
    for kind, getter in (("irr（読解そのもの・2018のみ）", lambda r: r.get("irr")),
                         ("irr_near（近傍ビンテージからの持ち回り）", lambda r: r.get("irr_near"))):
        have = [i for i in range(n) if getter(rs[i]) is not None]
        hi = [i for i in have if getter(rs[i]) >= 70]
        ent = {"n_with_irr": len(have), "n_irr_ge70": len(hi),
               "n_group_in_irr_ge70": len(set(hi) & oof)}
        if len(hi) >= 20:
            ent["stat"] = lift_of(rs, lab, oof, hi)
            gg = set(hi) & oof
            ent["numerator_companies_in_layer"] = len({rs[i]["ticker"] for i in gg if lab[i]})
            if len(gg) < 10:
                ent["status"] = "層内の群が %d 行しかなく判定不能" % len(gg)
            else:
                lf = ent["stat"]["lift"]
                ent["status"] = ("維持" if (lf is not None and abs(lf) >= LIFT_LINE
                                            and (1 if lf > 0 else -1) == sign)
                                 else "維持しない")
        else:
            ent["status"] = "irr>=70 が %d 行で判定不能" % len(hi)
        irr4[kind] = ent
    prim = irr4["irr_near（近傍ビンテージからの持ち回り）"]
    out["test4_irr"] = {
        "detail": irr4,
        "⚠": "irr の読解は 2013/2015/2018 のみ。2016/2017 は irr=null なので "
             "irr_near（近傍からの持ち回り）でしか層を作れない。両方出してある",
        "verdict": ("通過" if prim.get("status") == "維持"
                    else ("判定不能" if "判定不能" in str(prim.get("status")) else "不合格")),
    }

    # ── 検問5: 置換（会社単位・全ビンテージ同時） ────────────────────
    lab_by = defaultdict(dict)
    for i, r in enumerate(rs):
        lab_by[r["ticker"]][r["vintage"]] = lab[i]
    sic_of = {r["ticker"]: r.get("sic2") for r in rs}
    idx_of = defaultdict(list)
    for i, r in enumerate(rs):
        idx_of[r["ticker"]].append(i)

    def perm_stat(stratified, seed):
        rnd = random.Random(seed)
        if stratified:
            groups = defaultdict(list)
            for t in companies:
                groups[sic_of[t]].append(t)
            blocks = [sorted(v) for v in groups.values()]
        else:
            blocks = [list(companies)]
        cnt_ge = 0
        vals = []
        for _ in range(N_PERM):
            mapping = {}
            for b in blocks:
                sh = list(b)
                rnd.shuffle(sh)
                for a, c in zip(b, sh):
                    mapping[a] = c
            pl = [0] * n
            for t in companies:
                src = lab_by[mapping[t]]
                for i in idx_of[t]:
                    v = rs[i]["vintage"]
                    # 相手にその年が無ければ相手の持つ年から**決定的に**回す
                    # （会社の年ベクトルごと入替。hash() は実行ごとに変わるので使わない）
                    x = src.get(v)
                    if x is None:
                        ks = sorted(src)
                        x = src[ks[TRIO.index(v) % len(ks)]] if ks else 0
                    pl[i] = x
            b0 = sum(pl) / n
            k = sum(pl[i] for i in oof)
            lf = k / len(oof) - b0
            vals.append(lf)
            if abs(lf) >= abs(obs_lift):
                cnt_ge += 1
        vals.sort()
        return {"n_perm": N_PERM, "p_two_sided": r4((cnt_ge + 1) / (N_PERM + 1)),
                "null_lift_p2.5": r4(vals[int(0.025 * N_PERM)]),
                "null_lift_p97.5": r4(vals[int(0.975 * N_PERM)]),
                "null_lift_median": r4(vals[N_PERM // 2]),
                "observed_lift": r4(obs_lift)}

    p_uncond = perm_stat(False, SEED + 7)
    p_sector = perm_stat(True, SEED + 8)
    out["test5_permutation"] = {
        "unconditional_company_level": p_uncond,
        "within_sic2_company_level": p_sector,
        "read": "層なしは『会社単位の雑音より強いか』。sic2層内は『業種構成が説明する以上に強いか』"
                "——後者で p が大きければ生の lift は業種構成",
        "verdict": ("通過（層なし・sic2層内とも p<0.05）"
                    if (p_uncond["p_two_sided"] < 0.05 and p_sector["p_two_sided"] < 0.05)
                    else "不合格（sic2層内で有意でない）"
                    if p_uncond["p_two_sided"] < 0.05 else "不合格"),
    }

    # ── 検問6: 増分 ──────────────────────────────────────────
    def g_shrink(r):
        return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
                and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)

    def g_thin(r):
        return r.get("f2_intcov") is not None and r["f2_intcov"] < 3

    def g_notq(r):
        return not r.get("P_quality")

    def g_blocked(r):
        return g_shrink(r) or g_thin(r) or g_notq(r)

    gidx = sorted(oof)
    blocked = [i for i in gidx if g_blocked(rs[i])]
    fails = [i for i in gidx if not lab[i]]
    fails_caught = [i for i in fails if g_blocked(rs[i])]
    hits = [i for i in gidx if lab[i]]
    hits_caught = [i for i in hits if g_blocked(rs[i])]
    by_gate = {
        "事業の収縮(cagr5<0 ∧ opmD5<0)": sum(1 for i in gidx if g_shrink(rs[i])),
        "薄い財務(intcov<3)": sum(1 for i in gidx if g_thin(rs[i])),
        "質実証を通らない(not P_quality)": sum(1 for i in gidx if g_notq(rs[i])),
    }
    keep = [i for i in range(n) if not g_blocked(rs[i])]
    resid = lift_of(rs, lab, oof, keep)
    # irr>=70 も既存の関門として当てる（門の別枠85 の歴史側）
    def blocked_or_lowirr(i):
        r = rs[i]
        ir = r.get("irr_near")
        return g_blocked(r) or (ir is not None and ir < 70)
    blocked2 = [i for i in gidx if blocked_or_lowirr(i)]
    out["test6_incremental"] = {
        "group_rows": len(gidx),
        "already_blocked_rows": len(blocked),
        "already_blocked_share": r4(len(blocked) / len(gidx)),
        "by_gate_rows(重複あり)": by_gate,
        "including_irr_lt70": {"blocked_rows": len(blocked2),
                               "share": r4(len(blocked2) / len(gidx))},
        "literal_reading_prereg": {
            "note": "登録の字義（下向き）＝『群の10%未満だった社のうち既存関門で既に落ちている割合』",
            "n_failures_in_group": len(fails), "already_caught": len(fails_caught),
            "caught_share": r4(rate(len(fails_caught), len(fails)))},
        "group_achievers": {"n": len(hits), "already_caught": len(hits_caught),
                            "caught_share": r4(rate(len(hits_caught), len(hits)))},
        "residual_lift_inside_gate_survivors": resid,
        "read": "既存関門を通る行だけに絞って群の lift を測り直す＝**増分そのもの**。"
                "ここで |lift| が線を割るなら、この規則が門に足すものは無い",
        "verdict": ("不合格（既存関門で7割超が説明される）"
                    if (len(blocked) / len(gidx)) > INCREMENTAL_MAX_CAUGHT
                    else ("不合格（既存関門を通る行では lift が線を割る）"
                          if (resid and resid["lift"] is not None
                              and abs(resid["lift"]) < LIFT_LINE)
                          else "通過")),
    }

    # ── 追加の反証（登録の6検問の外。合否には数えない・攻撃の材料） ──────────
    extra = {}

    # (A) 増分の残差に業種調整を当てる。
    #     検問3が「生の lift の大半は業種構成」と出した以上、増分の残差にも同じ問いが要る
    keepset = set(keep)
    resid_mh = mh_diff(rs, lab, oof, keepset, lambda r: r.get("sic2"))
    resid_comp = []
    for s in secs:
        idx = [i for i in keep if rs[i].get("sic2") == s]
        gi = [i for i in idx if i in oof]
        if not gi:
            continue
        sb = sum(lab[i] for i in idx) / len(idx) if idx else None
        resid_comp.append({"sic2": s, "group_rows": len(gi),
                           "share_of_group": r4(len(gi) / len(keepset & oof)),
                           "share_of_keep": r4(len(idx) / len(keep)),
                           "sector_base_rate": r4(sb)})
    resid_comp.sort(key=lambda x: -x["group_rows"])
    extra["A_residual_under_sector_control"] = {
        "n_keep": len(keep), "n_group_in_keep": len(keepset & oof),
        "n_group_companies_in_keep": len({rs[i]["ticker"] for i in (keepset & oof)}),
        "numerator_rows": sum(1 for i in (keepset & oof) if lab[i]),
        "numerator_companies": len({rs[i]["ticker"] for i in (keepset & oof) if lab[i]}),
        "raw_lift": resid["lift"],
        "mh_by_sic2": resid_mh,
        "sector_composition_of_residual_group": resid_comp[:8],
        "read": "増分の残差でも MH が線を割るなら、『既存関門を通る行でも効く』という反論は業種構成",
    }

    # (B) 既存関門を1つずつ抜いたときの『既に説明される割合』（73%が線の際なので）
    drops = {}
    for nm, fn in (("事業の収縮を外す", lambda r: g_thin(r) or g_notq(r)),
                   ("薄い財務を外す", lambda r: g_shrink(r) or g_notq(r)),
                   ("質実証を外す", lambda r: g_shrink(r) or g_thin(r))):
        c = sum(1 for i in gidx if fn(rs[i]))
        drops[nm] = {"blocked_rows": c, "share": r4(c / len(gidx))}
    extra["B_incremental_sensitivity"] = {
        "with_all_three": r4(len(blocked) / len(gidx)),
        "drop_one_gate": drops,
        "line": INCREMENTAL_MAX_CAUGHT,
        "read": "0.7319 は線の際。どの関門を外しても線を割るなら『際どいから通す』とは言えない",
    }

    # (C) この規則は何を検出しているのか——業種の中で刻みを作り直す（業種中立版）
    #     rev/aturn の分位を **sic2 ごとに** 作れば、業種構成では群を作れない
    within = {}
    for label_, qrev, qatn in (("同じ刻み(rev<q50 ∧ aturn<q25)", 0.50, 0.25),):
        gmask = set()
        for s in secs:
            idx = [i for i in range(n) if rs[i].get("sic2") == s]
            if len(idx) < 12:
                continue
            cr = quantile([float(rs[i]["f2_rev"]) for i in idx], qrev)
            ca = quantile([float(rs[i]["f2_aturn"]) for i in idx], qatn)
            for i in idx:
                if float(rs[i]["f2_rev"]) < cr and float(rs[i]["f2_aturn"]) < ca:
                    gmask.add(i)
        within[label_] = lift_of(rs, lab, gmask, None)
        within[label_]["n_group_companies"] = len({rs[i]["ticker"] for i in gmask})
    # 対照: 同じ刻みをコホート全体の分位で作った版（＝この候補の素の形）
    cr = quantile([float(rs[i]["f2_rev"]) for i in range(n)], 0.50)
    ca = quantile([float(rs[i]["f2_aturn"]) for i in range(n)], 0.25)
    pooled_mask = set(i for i in range(n)
                      if float(rs[i]["f2_rev"]) < cr and float(rs[i]["f2_aturn"]) < ca)
    pooled_stat = lift_of(rs, lab, pooled_mask, None)
    pooled_stat["n_group_companies"] = len({rs[i]["ticker"] for i in pooled_mask})
    extra["C_sector_neutral_rebuild"] = {
        "pooled_cuts(この候補の素の形)": pooled_stat,
        "within_sector_cuts(業種中立)": within,
        "read": "同じ規則を**業種の中で**作り直すと、業種構成では群を作れない。"
                "ここで lift が縮むなら『小型∧低資産回転』ではなく『どの業種か』を測っていた",
    }

    # (D) 群の正体を数字で書く（規則が何を拾っているか）
    def med(vals):
        v = sorted(vals)
        return None if not v else r4(v[len(v) // 2])
    gsel = sorted(oof)
    extra["D_what_the_group_is"] = {
        "median_f2_rev_group": med([float(rs[i]["f2_rev"]) for i in gsel]),
        "median_f2_rev_population": med([float(rs[i]["f2_rev"]) for i in range(n)]),
        "median_f2_aturn_group": med([float(rs[i]["f2_aturn"]) for i in gsel]),
        "median_f2_aturn_population": med([float(rs[i]["f2_aturn"]) for i in range(n)]),
        "cut_rev_q50": r4(cr), "cut_aturn_q25": r4(ca),
        "top_sic2_in_group": [{"sic2": c["sic2"], "share_of_group": c["share_of_group"],
                               "over_representation_x": c["over_representation_x"],
                               "sector_base_rate": c["sector_base_rate"]}
                              for c in comp[:6]],
    }

    # (F) ★不合格 と 判定不能 を分ける——業種ゲートは**プールの読み**なら到達可能か
    #     探索側の到達可能性は per-vintage MH（52/60 層が落ちる）で測っており、
    #     「δ=0.25 を仕込んでも 0%」と出た。だが**プール MH は群の97.9%が測定可能**。
    #     そこで群を固定したまま真の効果 δ=0.25 を仕込み、プール MH が拾えるかを実測する。
    #     拾えるなら実測の −0.080 は『測れなかった』ではなく『効果が無い』である。
    sec_base = {}
    for s in secs:
        idx = [i for i in range(n) if rs[i].get("sic2") == s]
        sec_base[s] = sum(lab[i] for i in idx) / len(idx) if idx else base
    pc_rnd = random.Random(SEED + 99)
    REPS = 300
    got, vals_mh, vals_raw = 0, [], []
    for _ in range(REPS):
        pl = [0] * n
        for i in range(n):
            s = rs[i].get("sic2")
            p = sec_base.get(s, base)
            if i in oof:
                p = max(0.0, min(1.0, p - 0.25))
            pl[i] = 1 if pc_rnd.random() < p else 0
        # プール MH（同じ実装）
        strata = defaultdict(lambda: [0, 0, 0, 0])
        for i in range(n):
            s = rs[i].get("sic2")
            if s is None:
                continue
            d = strata[s]
            w = pl[i]
            if i in oof:
                d[0] += 1
                d[1] += w
            else:
                d[2] += 1
                d[3] += w
        num_ = den_ = 0.0
        for _s, (n1, k1, n0, k0) in strata.items():
            if n1 < 3 or n0 < 3:
                continue
            w = n1 * n0 / (n1 + n0)
            num_ += w * (k1 / n1 - k0 / n0)
            den_ += w
        mh = (num_ / den_) if den_ else None
        b0 = sum(pl) / n
        raw = sum(pl[i] for i in oof) / len(oof) - b0
        vals_raw.append(raw)
        if mh is not None:
            vals_mh.append(mh)
            if abs(mh) >= LIFT_LINE:
                got += 1
    vals_mh.sort()
    vals_raw.sort()
    extra["F_is_the_sector_gate_reachable_pooled"] = {
        "design": "群(235行)を固定し、真の効果 δ=0.25 を業種別基準率の上に仕込む。"
                  "群の行は p = 業種基準率 − 0.25、群外は p = 業種基準率。300回",
        "planted_delta": -0.25,
        "pooled_mh_median": r4(vals_mh[len(vals_mh) // 2]),
        "pooled_mh_p5": r4(vals_mh[int(0.05 * len(vals_mh))]),
        "pooled_mh_p95": r4(vals_mh[int(0.95 * len(vals_mh))]),
        "share_reaching_0.15": r4(got / REPS),
        "raw_lift_median_for_contrast": r4(vals_raw[len(vals_raw) // 2]),
        "observed_pooled_mh": mh_pool_sic["mh_risk_diff"] if mh_pool_sic else None,
        "★read": "仕込んだ真の効果をプール MH が拾えるなら、業種ゲートは**この読みでは到達可能**。"
                 "したがって実測 −0.080 は『測れなかった(判定不能)』ではなく『効果が業種構成だった(不合格)』",
    }

    # (G) 境界の約束（>= か >）に結果が乗っていないか
    ties_rev = sum(1 for i in range(n) if float(rs[i]["f2_rev"]) == cr)
    ties_atn = sum(1 for i in range(n) if float(rs[i]["f2_aturn"]) == ca)
    strict = set(i for i in range(n)
                 if float(rs[i]["f2_rev"]) <= cr and float(rs[i]["f2_aturn"]) <= ca)
    extra["G_boundary_convention"] = {
        "rows_exactly_at_rev_cut": ties_rev, "rows_exactly_at_aturn_cut": ties_atn,
        "lift_with_ge_convention": pooled_stat["lift"],
        "lift_with_le_convention": lift_of(rs, lab, strict, None)["lift"],
        "read": "同点が実質ゼロなら、結論は境界の約束に乗っていない",
    }

    # (E) 群の分子の会社が本当に20社を超えるか（行ではなく会社で数える・登録の字義）
    extra["E_numerator_unit"] = {
        "numerator_rows": num_rows, "numerator_companies": num_tick,
        "group_companies": len(g_tick),
        "note": "登録の分子>=20は『社』。行で数えると 50、会社で数えると %d" % num_tick,
    }
    out["extra_attacks_outside_prereg"] = extra

    # ── 総括 ────────────────────────────────────────────────
    verd = {
        "1_reproduce": out["test1_reproduce"]["verdict"],
        "2_vintage": out["test2_vintage"]["verdict"],
        "3_sector": out["test3_sector"]["verdict"],
        "4_irr": out["test4_irr"]["verdict"],
        "5_permutation": out["test5_permutation"]["verdict"],
        "6_incremental": out["test6_incremental"]["verdict"],
    }
    failed = [k for k, v in verd.items() if v.startswith("不合格")]
    undec = [k for k, v in verd.items() if v.startswith("判定不能")]
    F = extra["F_is_the_sector_gate_reachable_pooled"]
    out["★verdict"] = {
        "per_test": verd,
        "failed_tests": failed,
        "undecidable_tests": undec,
        "final": ("不合格" if failed else ("判定不能" if undec else "落とせなかった")),
        "line": "6つ全部を当てて1つでも落ちたら不合格（依頼文の線）",
        "★why_not_undecidable": {
            "探索側の読み": "per-vintage MH は 60層中52層を落とすので薄い＝δ=0.25 を仕込んでも "
                            "後段まで通るのは 0.0%。だから探索側は『判定不能』と書いた",
            "この検証の読み": "**プール MH は群の "
                              + str(out["test3_sector"]["share_of_group_measurable_pooled"])
                              + " が測定可能**。そこへ δ=0.25 を仕込む陽性対照を回すと中央値 "
                              + str(F["pooled_mh_median"]) + "・到達割合 "
                              + str(F["share_reaching_0.15"])
                              + " ＝この読みでは業種ゲートは到達可能",
            "結論": "到達可能な読みが存在し、その読みが −0.0801（線の 0.15 の半分強）と出す。"
                    "よって『測れなかった』ではなく『効果の大半が業種構成だった』＝**不合格**",
        },
        "★how_big_is_what_survives_sector": {
            "raw_lift": r4(obs_lift),
            "pooled_MH": mh_pool_sic["mh_risk_diff"] if mh_pool_sic else None,
            "within_sector_permutation_null_median": p_sector["null_lift_median"],
            "implied_beyond_sector": r4(obs_lift - p_sector["null_lift_median"]),
            "within_sector_rebuilt_rule": within["同じ刻み(rev<q50 ∧ aturn<q25)"]["lift"],
            "read": "業種を除いた後に残るのは −0.06〜−0.08。雑音ではない（sic2層内置換で p="
                    + str(p_sector["p_two_sided"])
                    + "）が、登録の線 0.15 の半分以下。『効果ゼロ』ではなく『小さすぎる』が正確",
        },
    }
    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"final": out["★verdict"], "t1": {k: v for k, v in t1.items()
                                                      if k not in ("chosen_detail",)}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
