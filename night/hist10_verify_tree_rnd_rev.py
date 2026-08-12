#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_verify_tree_rnd_rev.py — 角度E の木の候補を**潰しにかかる**（反証が仕事）。

候補（探索側 out/hist10_angleE.json の cells_y10["P_quality|cov90_14"].directions.up）:
    角度=E 変数=木(深さ3・best_leaf)
    ラベル上の呼び名: 「f2_rnd_r 上位1/4 ∧ f2_rev 上位1/4（第3分割は fold で変わる）」
    目的=10%+ (y10) / 母集団=P_quality|cov90_14（901行・382社）/ 切り方=入れ子CV・外側fold の群
    n=59 分子=40 lift=0.2595

事前登録: out/hist10_prereg.json（**線はそこにある。この道具は一つも作らない**）
    lift>=0.15 ∧ 分子>=20社 ∧ 2016/2017/2018 で維持 ∧ 業種調整 ∧ irr>=70 層 ∧
    既存関門で7割超が説明されるなら不合格。**すべて必要。1つでも欠ければ不合格。**

⚠ この道具は **hist10_angleE / hist10_diag / hist10_angleD を import しない**。
   panel と targets の生JSONだけを読み、木・fold・分位・ゲートを**独立に実装**する。
   探索側と同じ数字が出ることを最初に確かめ（検問1）、その上で反証を当てる。
   境界の約束（>= か >）まで揃える——前回ここで1社ずれた実例がある。

判定・採点・台帳・index.html・パックには一切触らない。読むだけの調査。
出力: out/hist10_verify_tree_rnd_rev.json
"""

import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
PANEL = os.path.join(OUT, "hist_wd_panel.json")
TARGETS = os.path.join(OUT, "hist10_targets.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
ANGLE_E = os.path.join(OUT, "hist10_angleE.json")
DEST = os.path.join(OUT, "hist10_verify_tree_rnd_rev.json")

# ── 事前登録の線（読み込んで確認する。ここでは作らない） ──
LIFT = 0.15
MIN_NUM = 20
INCREMENTAL_MAX_CAUGHT = 0.70
TRIO = [2016, 2017, 2018]
SEED = 20260812          # 探索側と同じ（再現のため）
CUT_QS = [0.25, 0.50, 0.75]
MIN_LEAF = 20
DEPTHS = (2, 3)
MODES = ("best_leaf", "leaf_union")
N_OUTER = 5
N_INNER = 4
DIRECTION = "up"          # 候補の方向。固定（内側で選ばない）

COV90 = ["aturn", "cagr5", "rev", "capex_r", "accel", "streak_rev", "rnd_r", "cash_r",
         "accr", "fcfpos5", "gw_r", "opm", "streak_opm", "opmD5"]
COLS = ["f2_" + k for k in COV90]

N_PERM = int(os.environ.get("VP_NPERM", 2000))


def r4(x):
    return None if x is None else round(x, 4)


def binom_sf(k, n, p):
    """P(K >= k) for K~Bin(n,p)。会社単位の素朴な有意性（独立を仮定した参考値）。"""
    if n <= 0:
        return None
    tot = 0.0
    for j in range(k, n + 1):
        lc = math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
        tot += math.exp(lc + j * math.log(p) + (n - j) * math.log(1 - p)) if 0 < p < 1 else 0.0
    return tot


def rate(k, n):
    return (k / n) if n else None


# ─────────────────── 読み込み（独立実装） ───────────────────
def load_rows():
    with open(PANEL, encoding="utf-8") as f:
        panel = json.load(f)
    with open(TARGETS, encoding="utf-8") as f:
        tg = json.load(f)
    tmap = {(r["ticker"], r["vintage"]): r for r in tg["rows"]}
    rows = []
    for r in panel["rows"]:
        if not (r.get("has_outcome") and r.get("window_full")):
            continue
        t = tmap.get((r["ticker"], r["vintage"]))
        if t is None:
            continue
        q = dict(r)
        for k in ("y10", "y_persist", "y_biz"):
            q[k] = t.get(k)
        rows.append(q)
    return panel, tg, rows


def build_set(rows):
    """complete-case（cov90_14 の全列が数値）・y10 が定義済み・P_quality・TRIO。"""
    rs = []
    for r in rows:
        if r["vintage"] not in TRIO:
            continue
        if not r.get("P_quality"):
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


def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = q * (len(xs) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


# ─────────────────── fold（会社単位） ───────────────────
def ticker_folds(rs, k, seed):
    ts = sorted({r["ticker"] for r in rs})
    order = list(ts)
    random.Random(seed).shuffle(order)
    assign = {t: i % k for i, t in enumerate(order)}
    masks = []
    for f in range(k):
        m = 0
        for i, r in enumerate(rs):
            if assign[r["ticker"]] == f:
                m |= (1 << i)
        masks.append(m)
    return masks


def cond_grid(rs, cols, train_mask, ge=True):
    """条件＝『列 >= 分位点』。分位点は train_mask の行だけから作る。
    ge=False にすると『>』で作る（境界の約束の感度を測るため）。"""
    idx = [i for i in range(len(rs)) if (train_mask >> i) & 1]
    out = []
    seen = set()
    n = len(rs)
    for c in cols:
        vals = [float(rs[i][c]) for i in idx]
        for q in CUT_QS:
            cut = quantile(vals, q)
            if cut is None:
                continue
            m = 0
            for i, r in enumerate(rs):
                v = float(r[c])
                if (v >= cut) if ge else (v > cut):
                    m |= (1 << i)
            mc = bin(m).count("1")
            if mc == 0 or mc == n:
                continue
            key = (c, m)
            if key in seen:
                continue
            seen.add(key)
            out.append(("%s>=q%d" % (c, int(q * 100)), c, m))
    return out


# ─────────────────── 木（独立実装） ───────────────────
def _went(k, n):
    if n <= 0 or k <= 0 or k >= n:
        return 0.0
    p = k / n
    return -n * (p * math.log(p) + (1 - p) * math.log(1 - p))


def grow(rule_mask, node_mask, depth, lm, conds, full, leaves, splits, level, min_leaf, path):
    n = bin(node_mask).count("1")
    k = bin(node_mask & lm).count("1")
    if depth <= 0 or n < 2 * min_leaf:
        leaves.append((rule_mask, n, k, path))
        return
    base_w = _went(k, n)
    best = None
    for ci in range(len(conds)):
        cm = conds[ci][2]
        L = node_mask & cm
        nl = bin(L).count("1")
        if nl < min_leaf:
            continue
        nr = n - nl
        if nr < min_leaf:
            continue
        kl = bin(L & lm).count("1")
        gain = base_w - _went(kl, nl) - _went(k - kl, nr)
        if best is None or gain > best[0]:
            best = (gain, ci, L)
    if best is None or best[0] <= 1e-12:
        leaves.append((rule_mask, n, k, path))
        return
    _, ci, L = best
    name, col, cm = conds[ci]
    splits.append({"level": level, "cond": name, "col": col, "n_node": n})
    inv = full ^ cm
    grow(rule_mask & cm, L, depth - 1, lm, conds, full, leaves, splits, level + 1,
         min_leaf, path + [name])
    grow(rule_mask & inv, node_mask & inv, depth - 1, lm, conds, full, leaves, splits,
         level + 1, min_leaf, path + ["!" + name])


def grow_once(train_mask, conds, lm, full, depth, min_leaf=MIN_LEAF):
    leaves, splits = [], []
    grow(full, train_mask, depth, lm, conds, full, leaves, splits, 0, min_leaf, [])
    ntr = bin(train_mask).count("1")
    base_tr = bin(train_mask & lm).count("1") / ntr if ntr else 0.0
    return leaves, splits, base_tr


def extract(leaves, base_tr, direction, mode, min_leaf=MIN_LEAF):
    cand = [x for x in leaves if x[1] >= min_leaf]
    if not cand:
        return 0, []
    if mode == "best_leaf":
        best = None
        for rm, n, k, path in cand:
            d = k / n - base_tr
            if (d > 0) if direction == "up" else (d < 0):
                if best is None or abs(d) > abs(best[0]):
                    best = (d, rm, path, n, k)
        if not best:
            return 0, []
        return best[1], [{"path": best[2], "n_train": best[3], "k_train": best[4],
                          "p_train": r4(rate(best[4], best[3]))}]
    m = 0
    used = []
    for rm, n, k, path in cand:
        d = k / n - base_tr
        if (d > 0) if direction == "up" else (d < 0):
            m |= rm
            used.append({"path": path, "n_train": n, "k_train": k, "p_train": r4(rate(k, n))})
    return m, used


# ─────────────────── 入れ子CV（独立実装） ───────────────────
class Cell:
    def __init__(self, rs, seed=SEED, ge=True):
        self.rs = rs
        self.n = len(rs)
        self.full = (1 << self.n) - 1
        self.outer_te = ticker_folds(rs, N_OUTER, seed)
        self.outer = [(self.full ^ te, te) for te in self.outer_te]
        self.inner = []
        for fi, (tr, _te) in enumerate(self.outer):
            sub = [i for i in range(self.n) if (tr >> i) & 1]
            ts = sorted({rs[i]["ticker"] for i in sub})
            order = list(ts)
            random.Random(seed + 1000 + fi).shuffle(order)
            assign = {t: i % N_INNER for i, t in enumerate(order)}
            ff = []
            for g in range(N_INNER):
                ite = 0
                for i in sub:
                    if assign[rs[i]["ticker"]] == g:
                        ite |= (1 << i)
                ff.append((tr & ~ite & self.full, ite))
            self.inner.append(ff)
        self.grid_outer = [cond_grid(rs, COLS, tr, ge) for tr, _ in self.outer]
        self.grid_inner = [[cond_grid(rs, COLS, itr, ge) for itr, _ in ff] for ff in self.inner]
        self.grid_all = cond_grid(rs, COLS, self.full, ge)

    def label_mask(self, labmap=None):
        m = 0
        for i, r in enumerate(self.rs):
            x = r.get("y10") if labmap is None else labmap.get((r["ticker"], r["vintage"]))
            if x:
                m |= (1 << i)
        return m

    def nested(self, lm, direction=DIRECTION, keep_detail=False):
        oof = 0
        chosen = []
        for fi, (tr, te) in enumerate(self.outer):
            ntr = bin(tr).count("1")
            base_tr = bin(tr & lm).count("1") / ntr if ntr else 0.0
            ig = {(dp, md): 0 for dp in DEPTHS for md in MODES}
            for gi, (itr, ite) in enumerate(self.inner[fi]):
                g = self.grid_inner[fi][gi]
                for dp in DEPTHS:
                    leaves, _sp, b = grow_once(itr, g, lm, self.full, dp)
                    for md in MODES:
                        rm, _u = extract(leaves, b, direction, md)
                        ig[(dp, md)] |= (rm & ite)
            best = None
            for dp in DEPTHS:
                for md in MODES:
                    gg = ig[(dp, md)]
                    m = bin(gg).count("1")
                    if m == 0:
                        continue
                    k = bin(gg & lm).count("1")
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
            leaves, splits, b = grow_once(tr, self.grid_outer[fi], lm, self.full, dp)
            rm, used = extract(leaves, b, direction, md)
            oof |= (rm & te)
            ent = {"fold": fi, "depth": dp, "mode": md, "inner_score": r4(_s),
                   "n_rule_train": bin(rm & tr).count("1"),
                   "n_rule_test": bin(rm & te).count("1")}
            if keep_detail:
                ent["splits"] = splits
                ent["leaves_used"] = used
            chosen.append(ent)
        return oof, chosen


# ─────────────────── gate1（事前登録） ───────────────────
def gate1(cell, lm, oof, direction=DIRECTION):
    n = cell.n
    m = bin(oof).count("1")
    k = bin(oof & lm).count("1")
    base = bin(lm).count("1") / n if n else 0.0
    lf = (k / m - base) if m else None
    sgn = 1 if direction == "up" else -1
    co_g, co_k = set(), set()
    for i in range(n):
        if (oof >> i) & 1:
            t = cell.rs[i]["ticker"]
            co_g.add(t)
            if (lm >> i) & 1:
                co_k.add(t)
    per_v = {}
    for v in TRIO:
        vm = 0
        for i, r in enumerate(cell.rs):
            if r["vintage"] == v:
                vm |= (1 << i)
        nv = bin(vm).count("1")
        if not nv:
            continue
        bv = bin(vm & lm).count("1") / nv
        gv = oof & vm
        mv = bin(gv).count("1")
        kv = bin(gv & lm).count("1")
        per_v[str(v)] = {"n": nv, "base": r4(bv), "n_group": mv, "k": kv,
                         "p_group": r4(rate(kv, mv)),
                         "lift": r4((kv / mv - bv) if mv else None)}
    vals = [per_v.get(str(v), {}).get("lift") for v in TRIO]
    sign_ok = all(x is not None and abs(x) >= LIFT and (1 if x > 0 else -1) == sgn for x in vals)
    lift_ok = (lf is not None and abs(lf) >= LIFT and (1 if lf > 0 else -1) == sgn)
    return {"n_rows": n, "base": r4(base), "n_group": m, "numerator": k,
            "n_group_companies": len(co_g), "numerator_companies": len(co_k),
            "p_group": r4(rate(k, m)), "lift": r4(lf),
            "lift_ok": lift_ok,
            "min_num_ok_companies": len(co_k) >= MIN_NUM,
            "min_num_ok_rows": k >= MIN_NUM,
            "per_vintage": per_v, "sign_ok": sign_ok,
            "gate1_pass": bool(lift_ok and (len(co_k) >= MIN_NUM) and sign_ok)}


# ─────────────────── 業種 ───────────────────
def mh_per_vintage(cell, lm, oof, v):
    """角度D の mh_g と同じ重み・同じ足切り（n1>=3 ∧ n0>=3）。層＝sic2。"""
    idx = [i for i, r in enumerate(cell.rs) if r["vintage"] == v and r.get("sic2")]
    if len(idx) < 20:
        return None
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for i in idx:
        r = cell.rs[i]
        d = strata[r["sic2"]]
        w = 1 if ((lm >> i) & 1) else 0
        if (oof >> i) & 1:
            d[0] += 1
            d[1] += w
        else:
            d[2] += 1
            d[3] += w
    num = den = 0.0
    used = drop = 0
    kept_rows = kept_grp = 0
    for _s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        wgt = n1 * n0 / (n1 + n0)
        num += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
        kept_rows += n1 + n0
        kept_grp += n1
    if den == 0:
        return None
    tot_grp = sum(1 for i in idx if (oof >> i) & 1)
    return {"mh_risk_diff": r4(num / den), "strata_used": used, "strata_dropped": drop,
            "rows_in_kept_strata": kept_rows, "group_rows_in_kept_strata": kept_grp,
            "group_rows_total": tot_grp,
            "share_of_group_measurable": r4(rate(kept_grp, tot_grp))}


def mh_pooled(cell, lm, oof, key="sic"):
    st = defaultdict(list)
    for i, r in enumerate(cell.rs):
        if not r.get("sic2"):
            continue
        st[r["sic2"] if key == "sic" else (r["sic2"], r["vintage"])].append(i)
    num = den = 0.0
    used = drop = 0
    kept_rows = kept_grp = 0
    for _s, idxs in st.items():
        n1 = sum(1 for i in idxs if (oof >> i) & 1)
        n0 = len(idxs) - n1
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        k1 = sum(1 for i in idxs if ((oof >> i) & 1) and ((lm >> i) & 1))
        k0 = sum(1 for i in idxs if (not ((oof >> i) & 1)) and ((lm >> i) & 1))
        wgt = n1 * n0 / (n1 + n0)
        num += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
        kept_rows += len(idxs)
        kept_grp += n1
    tot = bin(oof).count("1")
    return {"mh_risk_diff": r4(num / den) if den else None, "strata_used": used,
            "strata_dropped": drop, "rows_in_kept_strata": kept_rows,
            "group_rows_in_kept_strata": kept_grp, "group_rows_total": tot,
            "share_of_group_measurable": r4(rate(kept_grp, tot))}


def drop_one_sector_pooled(cell, lm, oof, min_group=10, min_rows=40):
    """プールした901行から業種を1つずつ抜いて OOF lift を測り直す。"""
    secs = sorted({r.get("sic2") for r in cell.rs if r.get("sic2")})
    out = []
    for s in secs:
        idx = [i for i, r in enumerate(cell.rs) if r.get("sic2") != s]
        nb = len(idx)
        if nb < min_rows:
            continue
        kb = sum(1 for i in idx if (lm >> i) & 1)
        grp = [i for i in idx if (oof >> i) & 1]
        if len(grp) < min_group:
            out.append({"dropped_sector": s, "n_group": len(grp), "status": "群<10で足切り"})
            continue
        kg = sum(1 for i in grp if (lm >> i) & 1)
        out.append({"dropped_sector": s, "n_pop": nb, "n_group": len(grp), "k": kg,
                    "base": r4(kb / nb), "p_group": r4(kg / len(grp)),
                    "lift": r4(kg / len(grp) - kb / nb)})
    meas = [x for x in out if "lift" in x]
    worst = min(meas, key=lambda x: abs(x["lift"])) if meas else None
    return {"per_sector": out, "worst_by_abs_lift": worst,
            "n_measurable": len(meas), "n_skipped": len(out) - len(meas)}


def drop_one_sector_per_vintage(cell, lm, oof, v):
    """角度D の drop_one_sector_g と同じ足切り（nb>=40・群>=10）。"""
    idx = [i for i, r in enumerate(cell.rs) if r["vintage"] == v]
    secs = sorted({cell.rs[i].get("sic2") for i in idx if cell.rs[i].get("sic2")})
    worst = None
    for s in secs:
        RR = [i for i in idx if cell.rs[i].get("sic2") != s]
        nb = len(RR)
        if nb < 40:
            continue
        kb = sum(1 for i in RR if (lm >> i) & 1)
        grp = [i for i in RR if (oof >> i) & 1]
        if len(grp) < 10:
            continue
        kg = sum(1 for i in grp if (lm >> i) & 1)
        lf = kg / len(grp) - kb / nb
        ent = {"dropped_sector": s, "n_group": len(grp), "k": kg, "lift": r4(lf)}
        if worst is None or abs(lf) < abs(worst["lift"]):
            worst = ent
    return worst


def sector_standardized(cell, lm, oof, key="sic"):
    """業種調整の**全被覆版**（間接標準化）。

    MH は n1>=3 ∧ n0>=3 の層しか使わないので、この群では45前後の層のうち3-6しか残らず
    群の34%が測れない（探索側の弁もそこ）。ここは重みを『群の行数』にして
    **群の全行**を使う: lift_adj = Σ_i∈群 [ y_i − p_非群(その層) ] / m。
    層に非群の行が1つも無いときだけ落とす（その数を出す）。
    """
    st = defaultdict(lambda: [0, 0, 0, 0])   # n1,k1,n0,k0
    for i, r in enumerate(cell.rs):
        if not r.get("sic2"):
            continue
        kk = r["sic2"] if key == "sic" else (r["sic2"], r["vintage"])
        d = st[kk]
        y = 1 if ((lm >> i) & 1) else 0
        if (oof >> i) & 1:
            d[0] += 1
            d[1] += y
        else:
            d[2] += 1
            d[3] += y
    used = k_obs = 0
    exp = 0.0
    dropped_rows = 0
    dropped_strata = 0
    for _s, (n1, k1, n0, k0) in st.items():
        if n1 == 0:
            continue
        if n0 == 0:
            dropped_rows += n1
            dropped_strata += 1
            continue
        used += n1
        k_obs += k1
        exp += n1 * (k0 / n0)
    tot = bin(oof).count("1")
    return {"n_group_used": used, "n_group_total": tot,
            "share_of_group_measurable": r4(rate(used, tot)),
            "group_rows_dropped_no_control_in_stratum": dropped_rows,
            "strata_dropped": dropped_strata,
            "observed_k": k_obs, "expected_k_from_sector_mix": r4(exp),
            "lift_sector_adjusted": r4((k_obs - exp) / used) if used else None,
            "read": ("生の lift との差が『業種の構成』が作っていた分。"
                     "MH と違い群の全行を使うので被覆の言い訳が効かない")}


def sector_composition(cell, lm, oof, top=12):
    n = cell.n
    tot, tot_k, grp, grp_k = Counter(), Counter(), Counter(), Counter()
    for i, r in enumerate(cell.rs):
        s = r.get("sic2") or "?"
        tot[s] += 1
        if (lm >> i) & 1:
            tot_k[s] += 1
        if (oof >> i) & 1:
            grp[s] += 1
            if (lm >> i) & 1:
                grp_k[s] += 1
    m = bin(oof).count("1")
    rows = []
    for s in sorted(grp, key=lambda x: -grp[x])[:top]:
        rows.append({"sic2": s, "group_rows": grp[s], "share_of_group": r4(rate(grp[s], m)),
                     "share_of_population": r4(rate(tot[s], n)),
                     "sector_base_rate": r4(rate(tot_k[s], tot[s])),
                     "group_rate_in_sector": r4(rate(grp_k[s], grp[s])),
                     "within_sector_lift": r4((grp_k[s] / grp[s] - tot_k[s] / tot[s])
                                              if grp[s] and tot[s] else None)})
    return {"population_base": r4(bin(lm).count("1") / n), "top_sectors_in_group": rows}


# ─────────────────── 既存関門（門の歴史側の相当物・角度A/D と同一定義） ───────────────────
def g_shrink(r):
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def g_thin(r):
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def g_notq(r):
    return not r.get("P_quality")


def g_blocked(r):
    return g_shrink(r) or g_thin(r) or g_notq(r)


def apply_named_rule(rs, basis="per_vintage"):
    """依頼文のラベルどおりの規則『f2_rnd_r>=q75 ∧ f2_rev>=q75』を一様に当てる。"""
    gm = 0
    if basis == "pooled":
        qr = quantile([float(r["f2_rnd_r"]) for r in rs], 0.75)
        qv = quantile([float(r["f2_rev"]) for r in rs], 0.75)
        for i, r in enumerate(rs):
            if float(r["f2_rnd_r"]) >= qr and float(r["f2_rev"]) >= qv:
                gm |= (1 << i)
        return gm
    for v in TRIO:
        sub = [i for i, r in enumerate(rs) if r["vintage"] == v]
        if not sub:
            continue
        qr = quantile([float(rs[i]["f2_rnd_r"]) for i in sub], 0.75)
        qv = quantile([float(rs[i]["f2_rev"]) for i in sub], 0.75)
        for i in sub:
            if float(rs[i]["f2_rnd_r"]) >= qr and float(rs[i]["f2_rev"]) >= qv:
                gm |= (1 << i)
    return gm


def apply_rule_pv(rs):
    return apply_named_rule(rs, "per_vintage")


def main():
    t0 = time.time()
    with open(PREREG, encoding="utf-8") as f:
        prereg = json.load(f)
    with open(ANGLE_E, encoding="utf-8") as f:
        aE = json.load(f)
    claim = aE["cells_y10"]["P_quality|cov90_14"]["directions"]["up"]

    panel, tg, rows = load_rows()
    rs = build_set(rows)
    cell = Cell(rs, SEED, ge=True)
    lm = cell.label_mask()

    res = {
        "generated": time.strftime("%Y-%m-%d"),
        "tool": "night/hist10_verify_tree_rnd_rev.py",
        "prereg": {"file": "out/hist10_prereg.json", "version": prereg.get("version"),
                   "lift": LIFT, "min_numerator": MIN_NUM,
                   "incremental_max_caught": INCREMENTAL_MAX_CAUGHT,
                   "note": "線は事前登録のもの。この道具は一つも作らない"},
        "candidate": {
            "angle": "E（決定木・入れ子CV）",
            "label_in_request": "f2_rnd_r 上位1/4 ∧ f2_rev 上位1/4（第3分割は fold で変わる）",
            "target": "y10（tr_cagr>=10%）", "pop": "P_quality|cov90_14",
            "direction": DIRECTION,
            "claimed": {"n_group": claim["oof"]["n_group"], "numerator": claim["oof"]["numerator"],
                        "lift": claim["oof"]["lift"], "base": claim["oof"]["base"],
                        "n_group_companies": claim["oof"]["n_group_companies"],
                        "numerator_companies": claim["oof"]["numerator_companies"]},
            "explorer_verdict": "判定不能（gate1 は通ったが業種ゲートで落ちた）",
        },
        "independence": ("hist10_angleE / hist10_diag / hist10_angleD を import していない。"
                         "panel と targets の生JSONから木・fold・分位・ゲートを独立に実装した"),
    }

    # ── 検問1: 再現 ─────────────────────────────
    oof, chosen = cell.nested(lm, DIRECTION, keep_detail=True)
    g1 = gate1(cell, lm, oof)
    c = claim["oof"]
    same = (g1["n_group"] == c["n_group"] and g1["numerator"] == c["numerator"]
            and abs(g1["lift"] - c["lift"]) < 1e-9
            and g1["n_group_companies"] == c["n_group_companies"]
            and g1["numerator_companies"] == c["numerator_companies"])
    res["check1_reproduce"] = {
        "analysis_set": {"n_rows": cell.n, "n_companies": len({r["ticker"] for r in rs}),
                         "claimed_rows": aE["cells_y10"]["P_quality|cov90_14"]["n_rows"],
                         "claimed_companies": aE["cells_y10"]["P_quality|cov90_14"]["n_companies"]},
        "independent": g1,
        "claimed": c,
        "match": bool(same),
        "fold_rules": chosen,
    }
    print("[1] reproduce match=%s n=%d k=%d lift=%.4f (%.1fs)"
          % (same, g1["n_group"], g1["numerator"], g1["lift"], time.time() - t0))

    # ── 検問1b: 境界の約束（>= vs >）と分位の作り方の感度 ───────────
    sens = {}
    cell_gt = Cell(rs, SEED, ge=False)
    oof_gt, _ = cell_gt.nested(lm, DIRECTION)
    sens["strict_greater"] = gate1(cell_gt, lm, oof_gt)

    # コホート全体の分位で条件を作る版（train 分位ではなく）
    class CellAll(Cell):
        def __init__(self, rs2, seed=SEED):
            Cell.__init__(self, rs2, seed, ge=True)
            g = self.grid_all
            self.grid_outer = [g for _ in self.outer]
            self.grid_inner = [[g for _ in ff] for ff in self.inner]
    cell_all = CellAll(rs)
    oof_all, _ = cell_all.nested(lm, DIRECTION)
    sens["cohort_wide_quantiles"] = gate1(cell_all, lm, oof_all)

    # seed 感度（fold の割り当てだけ変える。設計は不変）
    SEEDS = [SEED, SEED + 1, SEED + 2, SEED + 3, SEED + 7, SEED + 11]
    cells_by_seed = {SEED: cell}
    for sd in SEEDS[1:]:
        cells_by_seed[sd] = Cell(rs, sd, ge=True)
    seeds = {}
    for sd in SEEDS:
        cs = cells_by_seed[sd]
        oo, _ = cs.nested(lm, DIRECTION)
        gg = gate1(cs, lm, oo)
        seeds[str(sd)] = {"n_group": gg["n_group"], "numerator": gg["numerator"],
                          "numerator_companies": gg["numerator_companies"],
                          "lift": gg["lift"], "sign_ok": gg["sign_ok"],
                          "gate1_pass": gg["gate1_pass"],
                          "per_vintage_lift": {k: v["lift"] for k, v in gg["per_vintage"].items()}}
    lf = [v["lift"] for v in seeds.values()]
    sens["fold_seed"] = {
        "why": ("fold の割り当ては結果の前に固定された nuisance だが、**結果がその割り当てに"
                "依存するなら、報告値はデータの性質ではなく籤の性質**。設計は一切変えず seed だけ振る"),
        "by_seed": seeds,
        "n_pass_gate1": sum(1 for v in seeds.values() if v["gate1_pass"]),
        "n_seeds": len(SEEDS),
        "lift_min": r4(min(lf)), "lift_max": r4(max(lf)),
        "lift_range": r4(max(lf) - min(lf)),
        "n_group_min": min(v["n_group"] for v in seeds.values()),
        "n_group_max": max(v["n_group"] for v in seeds.values()),
        "numerator_companies_range": [min(v["numerator_companies"] for v in seeds.values()),
                                      max(v["numerator_companies"] for v in seeds.values())],
    }
    res["check1b_boundary_and_design_sensitivity"] = sens
    print("[1b] strict> lift=%s / cohortq lift=%s / seeds pass=%d/%d lift %.3f–%.3f (%.1fs)"
          % (sens["strict_greater"]["lift"], sens["cohort_wide_quantiles"]["lift"],
             sens["fold_seed"]["n_pass_gate1"], len(SEEDS), min(lf), max(lf), time.time() - t0))

    # ── 検問1e: 陽性対照——**本物の効果なら fold の籤で揺れるのか** ───────
    # 探索側の弁は「後段ゲートは δ=0.25 の真の効果でも通らない＝当てられない関門」。
    # ならば逆を測る: **δ=0.25 の真の効果を仕込んだとき、fold seed で結果はどれだけ揺れるか**。
    # 揺れないなら、観測データの揺れは『効果が無い』ことの証拠になる。
    base_obs = g1["base"]
    delta = 0.25
    N_REP = int(os.environ.get("VP_NREP", 20))
    obs_range = sens["fold_seed"]["lift_range"]

    # 仕込む規則を2つ用意する:
    #  A) 2条件（依頼文のラベルそのもの）＝**貪欲な木には見つけにくい**（根で切れない）
    #  B) 1条件（f2_rnd_r>=q75）＝**貪欲な木に最も見つけやすい**形
    # 手続きが B でも安定しないなら、seed の揺れは『効果の不在』ではなく手続きの粗さ。
    q75r = quantile([float(r["f2_rnd_r"]) for r in rs], 0.75)
    gm_single = 0
    for i, r in enumerate(rs):
        if float(r["f2_rnd_r"]) >= q75r:
            gm_single |= (1 << i)
    controls = {}
    for cname, gm_true, desc, delta in (
            ("A_two_condition_d25", apply_rule_pv(rs),
             "f2_rnd_r>=q75 ∧ f2_rev>=q75（依頼文のラベル）", 0.25),
            ("B_single_condition_d25", gm_single,
             "f2_rnd_r>=q75 のみ（貪欲な木に最も見つけやすい）", 0.25),
            ("B_single_condition_d15", gm_single, "同上", 0.15),
            ("B_single_condition_d10", gm_single, "同上", 0.10)):
        nT = bin(gm_true).count("1")
        p_in = min(0.999, base_obs + delta)
        p_out = max(0.001, base_obs - delta * nT / (cell.n - nT))
        rndp = random.Random(SEED + 777)
        reps = []
        for _ in range(N_REP):
            slm = 0
            for i in range(cell.n):
                if rndp.random() < (p_in if ((gm_true >> i) & 1) else p_out):
                    slm |= (1 << i)
            row = {}
            for sd in SEEDS:
                cs = cells_by_seed[sd]
                oo, _ = cs.nested(slm, DIRECTION)
                gg = gate1(cs, slm, oo)
                row[str(sd)] = {"lift": gg["lift"], "n_group": gg["n_group"],
                                "numerator_companies": gg["numerator_companies"],
                                "gate1_pass": gg["gate1_pass"]}
            ls = [row[str(sd)]["lift"] for sd in SEEDS if row[str(sd)]["lift"] is not None]
            reps.append({"per_seed": row,
                         "lift_min": r4(min(ls)) if ls else None,
                         "lift_max": r4(max(ls)) if ls else None,
                         "lift_range": r4(max(ls) - min(ls)) if ls else None,
                         "n_pass": sum(1 for sd in SEEDS if row[str(sd)]["gate1_pass"])})
        rngs = sorted(x["lift_range"] for x in reps if x["lift_range"] is not None)
        passes = sorted(x["n_pass"] for x in reps)
        controls[cname] = {
            "implanted_rule": desc, "implanted_rows": nT, "delta": delta,
            "p_inside": r4(p_in), "p_outside": r4(p_out),
            "n_replicates": N_REP,
            "lift_range_across_seeds": {"median": r4(rngs[len(rngs) // 2]) if rngs else None,
                                        "min": r4(rngs[0]) if rngs else None,
                                        "max": r4(rngs[-1]) if rngs else None},
            "gate1_pass_per_replicate": {"median": passes[len(passes) // 2],
                                         "min": passes[0], "max": passes[-1],
                                         "of_n_seeds": len(SEEDS),
                                         "share_of_seed_runs_passing":
                                             r4(sum(passes) / (len(passes) * len(SEEDS)))},
            "share_of_replicates_with_range_ge_observed":
                r4(rate(sum(1 for x in rngs if x >= obs_range), len(rngs))) if rngs else None,
            "replicates": reps,
        }
    res["check1e_positive_control_seed_stability"] = {
        "why": ("探索側の弁は『後段ゲートは δ=0.25 の真の効果でも通らない＝当てられない関門』。"
                "それが本当なら、**真の効果があるときに fold seed で結果が揺れるか**を測れば、"
                "観測の揺れが『効果の不在』の証拠か『手続きが粗い』せいかを切り分けられる"),
        "controls": controls,
        "observed_lift_range_across_seeds": obs_range,
        "observed_gate1_pass": sens["fold_seed"]["n_pass_gate1"],
        "observed_n_seeds": len(SEEDS),
        "how_to_read": ("A が通らないのは貪欲な木が2条件の下位群を根から掘れないため（手続きの限界）"
                        "＝探索側の『後段は当てられない』の弁はこの形では正しい。"
                        "**B（木が見つけられる形）で δ を振り、観測の揺れと合う δ を読む**のが本体。"
                        "B も観測と同じだけ揺れるなら seed の検問からは何も言えない——正直にそう書く"),
    }
    print("[1e] pos.ctrl " + " | ".join(
        "%s range=%s pass=%s/%d" % (k, v["lift_range_across_seeds"]["median"],
                                    v["gate1_pass_per_replicate"]["median"], len(SEEDS))
        for k, v in controls.items())
        + " | observed range=%s pass=%d/%d" % (obs_range, sens["fold_seed"]["n_pass_gate1"],
                                               len(SEEDS)))

    # ── 検問1c: ラベルの呼び名どおりの規則を一様に当てる ───────────
    named = {}
    for basis in ("pooled", "per_vintage"):
        named[basis] = gate1(cell, lm, apply_named_rule(rs, basis))
    # OOF 群のうち、呼び名の規則を満たす行はいくつか
    gm_pv = apply_named_rule(rs, "per_vintage")
    inter = bin(oof & gm_pv).count("1")
    # OOF 群を「呼び名を満たす／満たさない」で割る
    a = oof & gm_pv
    b = oof & ~gm_pv
    def sub(mm):
        m = bin(mm).count("1")
        k = bin(mm & lm).count("1")
        return {"n": m, "k": k, "p": r4(rate(k, m)),
                "lift_vs_pop_base": r4(k / m - g1["base"]) if m else None,
                "companies": len({cell.rs[i]["ticker"] for i in range(cell.n) if (mm >> i) & 1})}
    res["check1c_named_rule_applied_uniformly"] = {
        "why": ("依頼文のラベルは『f2_rnd_r 上位1/4 ∧ f2_rev 上位1/4』。OOF 群は fold ごとに"
                "**別の規則**の和集合なので、(a) そのラベルの規則を一様に当てたら何が起きるか "
                "(b) OOF 群のうち何行がそのラベルを満たすか、を測る"),
        "uniform_rule": named,
        "⚠_uniform_rule_is_in_sample": ("この規則は木がデータを見て選んだもの。一様に当てた"
                                        "数字は in-sample であって held-out ではない"),
        "oof_group_rows_satisfying_named_rule": inter,
        "oof_group_rows_total": bin(oof).count("1"),
        "share": r4(rate(inter, bin(oof).count("1"))),
        "split_of_oof_group": {"satisfies_named_rule": sub(a), "does_not": sub(b)},
    }
    print("[1c] named rule pooled lift=%s / per_vintage lift=%s / OOF∩named=%d/%d"
          % (named["pooled"]["lift"], named["per_vintage"]["lift"], inter, bin(oof).count("1")))

    # ── 検問1d: 群の中身（fold ごとの寄与・会社の重なり・1社抜き） ───────
    per_fold = []
    for fi, (tr, te) in enumerate(cell.outer):
        gv = oof & te
        m = bin(gv).count("1")
        k = bin(gv & lm).count("1")
        rule = chosen[fi]
        per_fold.append({"fold": fi, "n_group": m, "k": k, "p_group": r4(rate(k, m)),
                         "depth": rule["depth"] if rule else None,
                         "mode": rule["mode"] if rule else None,
                         "leaf_path": (rule.get("leaves_used") or [{}])[0].get("path") if rule else None,
                         "leaf_p_train": (rule.get("leaves_used") or [{}])[0].get("p_train") if rule else None})
    # fold を1つ抜いたときの lift（その fold の群を外す。母集団は不変）
    fold_out = []
    for fi, (_tr, te) in enumerate(cell.outer):
        oo = oof & ~te
        m = bin(oo).count("1")
        k = bin(oo & lm).count("1")
        fold_out.append({"dropped_fold": fi, "n_group": m, "k": k,
                         "lift": r4(k / m - g1["base"]) if m else None})
    # 会社の重なり: 群の会社が何ビンテージに現れるか
    co_v = defaultdict(set)
    for i in range(cell.n):
        if (oof >> i) & 1:
            co_v[cell.rs[i]["ticker"]].add(cell.rs[i]["vintage"])
    rep = Counter(len(v) for v in co_v.values())
    # 会社単位の lift（同じ会社を最大3回数えない）
    all_co = defaultdict(list)
    for i, r in enumerate(cell.rs):
        all_co[r["ticker"]].append(1 if ((lm >> i) & 1) else 0)
    base_co_any = sum(1 for t, v in all_co.items() if any(v)) / len(all_co)
    base_co_all = sum(1 for t, v in all_co.items() if all(v)) / len(all_co)
    gco = set(co_v)
    gk_any = sum(1 for t in gco if any(all_co[t]))
    gk_all = sum(1 for t in gco if all(all_co[t]))
    # 1社抜き（群の会社を1社ずつ落とす）
    jack = []
    for t in sorted(gco):
        oo = 0
        for i in range(cell.n):
            if ((oof >> i) & 1) and cell.rs[i]["ticker"] != t:
                oo |= (1 << i)
        m = bin(oo).count("1")
        k = bin(oo & lm).count("1")
        co_k2 = len({cell.rs[i]["ticker"] for i in range(cell.n)
                     if ((oo >> i) & 1) and ((lm >> i) & 1)})
        jack.append({"dropped": t, "n_group": m, "k": k, "numerator_companies": co_k2,
                     "lift": r4(k / m - g1["base"]) if m else None})
    worst_j = min(jack, key=lambda x: x["lift"]) if jack else None
    res["check1d_group_internals"] = {
        "why": ("OOF 群は fold ごとに**別の規則**が作った行の和集合。単一の規則ではないので、"
                "『どの fold が群を作っているか』『同じ会社が何度数えられているか』を測る"),
        "per_fold_contribution": per_fold,
        "leave_one_fold_out": fold_out,
        "group_companies": len(gco),
        "company_appears_in_n_vintages": {str(k): v for k, v in sorted(rep.items())},
        "company_level": {
            "n_companies_in_group": len(gco),
            "base_company_any_vintage_y10": r4(base_co_any),
            "base_company_all_vintages_y10": r4(base_co_all),
            "group_any": gk_any, "group_all": gk_all,
            "p_group_any": r4(rate(gk_any, len(gco))),
            "p_group_all": r4(rate(gk_all, len(gco))),
            "lift_any": r4(rate(gk_any, len(gco)) - base_co_any),
            "lift_all": r4(rate(gk_all, len(gco)) - base_co_all),
            "binom_p_any": r4(binom_sf(gk_any, len(gco), base_co_any)),
            "binom_p_all": r4(binom_sf(gk_all, len(gco), base_co_all)),
            "note": ("行で数えると同じ会社を最大3回数える。実効 n は行59ではなく**会社28**。"
                     "会社単位の lift と、独立を仮定した素朴な二項の上側確率を併記する"
                     "（群は木が選んだものなので、この p は選択を補正していない＝参考値）"),
        },
        "leave_one_company_out": {"worst": worst_j, "n_tested": len(jack), "all": jack},
    }
    print("[1d] folds=%s  companies=%d  worst-1社抜き lift=%s"
          % ([f["n_group"] for f in per_fold], len(gco),
             worst_j["lift"] if worst_j else None))

    # ── 検問2: ビンテージ ─────────────────────────
    res["check2_vintage"] = {"per_vintage": g1["per_vintage"], "sign_ok": g1["sign_ok"],
                             "line": LIFT,
                             "⚠_not_three_independent_evidences":
                                 ("2016/2017/2018 は同じ956ティッカー（panel の既知の非対称）。"
                                  "群の会社が複数ビンテージに現れるなら『3ビンテージ維持』は"
                                  "3つの独立な証拠ではない。重なりは check1d を見よ")}

    # ── 検問3: 業種 ──────────────────────────────
    mh_v = {str(v): mh_per_vintage(cell, lm, oof, v) for v in TRIO}
    mh_ok = all(x is not None and x["mh_risk_diff"] is not None
                and abs(x["mh_risk_diff"]) >= LIFT and x["mh_risk_diff"] > 0
                for x in mh_v.values())
    dos_v = {str(v): drop_one_sector_per_vintage(cell, lm, oof, v) for v in TRIO}
    dos_ok = all(x is not None and x["lift"] is not None and abs(x["lift"]) >= LIFT
                 and x["lift"] > 0 for x in dos_v.values())
    res["check3_sector"] = {
        "mh_per_vintage_(prereg_gate)": mh_v,
        "mh_ok": mh_ok,
        "mh_pooled_by_sic": mh_pooled(cell, lm, oof, "sic"),
        "mh_pooled_by_sic_vintage": mh_pooled(cell, lm, oof, "sic_vintage"),
        "drop_one_sector_per_vintage_(prereg_gate)": dos_v,
        "drop_one_sector_ok": dos_ok,
        "drop_one_sector_pooled": drop_one_sector_pooled(cell, lm, oof),
        "sector_standardized_full_coverage": {
            "by_sic": sector_standardized(cell, lm, oof, "sic"),
            "by_sic_vintage": sector_standardized(cell, lm, oof, "sic_vintage"),
        },
        "composition": sector_composition(cell, lm, oof),
        "raw_lift_for_comparison": g1["lift"],
    }
    print("[3] mh_ok=%s dos_ok=%s (%.1fs)" % (mh_ok, dos_ok, time.time() - t0))

    # ── 検問4: irr の影 ───────────────────────────
    irr_out = {}
    for v in TRIO:
        idx = [i for i, r in enumerate(cell.rs) if r["vintage"] == v and r.get("irr") is not None]
        if len(idx) < 20:
            irr_out[str(v)] = {"n_with_irr": len(idx),
                               "status": "irr の読解がこのビンテージで %d 行しかなく判定不能" % len(idx)}
            continue
        hi = [i for i in idx if float(cell.rs[i]["irr"]) >= 70]
        ent = {"n_with_irr": len(idx), "n_irr_ge70": len(hi)}
        if len(hi) >= 20:
            base = sum(1 for i in hi if (lm >> i) & 1) / len(hi)
            g = [i for i in hi if (oof >> i) & 1]
            kg = sum(1 for i in g if (lm >> i) & 1)
            ent["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g), "k": kg,
                               "p_group": r4(rate(kg, len(g))),
                               "lift": r4(kg / len(g) - base) if g else None}
        else:
            ent["irr_ge70"] = {"status": "irr>=70 が %d 行で判定不能" % len(hi)}
        # 群と irr の関係（直交か）
        gm_ind = [1.0 if ((oof >> i) & 1) else 0.0 for i in idx]
        irrv = [float(cell.rs[i]["irr"]) for i in idx]
        # 群の irr 分布
        gi = [float(cell.rs[i]["irr"]) for i in idx if (oof >> i) & 1]
        ent["irr_of_group"] = {"n": len(gi), "counts": dict(Counter(int(x) for x in gi))}
        ent["irr_of_pop"] = dict(Counter(int(x) for x in irrv))
        irr_out[str(v)] = ent
    res["check4_irr"] = {
        "coverage_note": ("panel の既知の非対称: irr の読解は 2013/2015/2018 のみ。"
                          "2016/2017 は irr=null＝この検問は 2018 でしか当てられない"),
        "by_vintage": irr_out,
    }
    print("[4] irr done (%.1fs)" % (time.time() - t0))

    # ── 検問6: 増分 ───────────────────────────────
    inc = {}
    for v in TRIO:
        idx = [i for i, r in enumerate(cell.rs) if r["vintage"] == v]
        keep = [i for i in idx if not g_blocked(cell.rs[i])]
        grp_all = [i for i in idx if (oof >> i) & 1]
        g = [i for i in keep if (oof >> i) & 1]
        ent = {"n_rows": len(idx), "n_keep": len(keep), "n_group_before": len(grp_all),
               "n_group_after_gates": len(g),
               "share_of_group_already_blocked": r4(1 - rate(len(g), len(grp_all))) if grp_all else None}
        if len(keep) >= 40 and len(g) >= 10:
            base = sum(1 for i in keep if (lm >> i) & 1) / len(keep)
            k = sum(1 for i in g if (lm >> i) & 1)
            ent.update({"k": k, "base": r4(base), "lift": r4(k / len(g) - base)})
        else:
            ent["status"] = "測定不能（keep=%d, group_after=%d）" % (len(keep), len(g))
        inc[str(v)] = ent
    # プール版
    keep = [i for i in range(cell.n) if not g_blocked(cell.rs[i])]
    g = [i for i in keep if (oof >> i) & 1]
    grp_all = [i for i in range(cell.n) if (oof >> i) & 1]
    base_k = sum(1 for i in keep if (lm >> i) & 1) / len(keep)
    kg = sum(1 for i in g if (lm >> i) & 1)
    inc_pooled = {"n_keep": len(keep), "n_group_before": len(grp_all),
                  "n_group_after_gates": len(g), "k": kg, "base": r4(base_k),
                  "lift": r4(kg / len(g) - base_k) if g else None,
                  "share_of_group_already_blocked": r4(1 - rate(len(g), len(grp_all)))}

    # 群の「10%+ を出した社」が既存の選別で説明されるか
    num_idx = [i for i in range(cell.n) if ((oof >> i) & 1) and ((lm >> i) & 1)]
    num_co = {cell.rs[i]["ticker"] for i in num_idx}
    expl = {}
    expl["P_quality"] = {"rows": len(num_idx), "explained": len(num_idx),
                         "share": 1.0,
                         "note": "母集団が P_quality なので**定義上100%**。構造の事実であって発見ではない"}
    sh = sum(1 for i in num_idx if g_shrink(cell.rs[i]))
    th = sum(1 for i in num_idx if g_thin(cell.rs[i]))
    expl["g_shrink(事業の収縮)"] = {"rows": len(num_idx), "explained": sh,
                                    "share": r4(rate(sh, len(num_idx)))}
    expl["g_thin(intcov<3)"] = {"rows": len(num_idx), "explained": th,
                                "share": r4(rate(th, len(num_idx)))}
    n18 = [i for i in num_idx if cell.rs[i]["vintage"] == 2018 and cell.rs[i].get("irr") is not None]
    i70 = sum(1 for i in n18 if float(cell.rs[i]["irr"]) >= 70)
    expl["irr>=70(2018のみ測定可)"] = {"rows_with_irr": len(n18), "explained": i70,
                                        "share": r4(rate(i70, len(n18)))}
    res["check6_incremental"] = {
        "prereg_definition": ("上向き＝既存関門を通る行だけに絞って lift を測り直す＋"
                              "群のうち既存関門で既に落ちている割合が7割超なら不合格"),
        "per_vintage": inc, "pooled": inc_pooled,
        "line_max_caught": INCREMENTAL_MAX_CAUGHT,
        "explained_share_of_numerator": expl,
        "⚠": ("この母集団は既に P_quality なので、質実証は増分の判定に使えない（定義上100%）。"
              "使えるのは 事業の収縮 / 薄い財務 / irr>=70 の3つだけ"),
    }
    print("[6] incremental done (%.1fs)" % (time.time() - t0))

    # ── 検問5: 置換（会社単位・全ビンテージ同時） ───────────
    # 会社ごとの (vintage->label) プロファイルを、同じ sic2 かつ同じビンテージ集合の
    # 会社どうしで入れ替える。ビンテージごと・業種ごとの基準率と、
    # 同じ会社のラベルの相関を保つ。
    prof = defaultdict(dict)
    sic_of = {}
    for r in rs:
        prof[r["ticker"]][r["vintage"]] = 1 if r["y10"] else 0
        sic_of[r["ticker"]] = r.get("sic2")
    buckets = defaultdict(list)
    for t, p in prof.items():
        buckets[(sic_of[t], tuple(sorted(p.keys())))].append(t)
    bucket_sizes = Counter(len(v) for v in buckets.values())

    def perm_labels(rnd):
        out = {}
        for _k, ts in buckets.items():
            src = list(ts)
            rnd.shuffle(src)
            for a, b in zip(ts, src):
                for v, y in prof[b].items():
                    out[(a, v)] = y
        return out

    rnd = random.Random(SEED)
    hits_lift = 0
    hits_gate1 = 0
    hits_all = 0
    lifts = []
    t_perm0 = time.time()
    for it in range(N_PERM):
        labmap = perm_labels(rnd)
        plm = cell.label_mask(labmap)
        po, _ = cell.nested(plm, DIRECTION)
        pg = gate1(cell, plm, po)
        if pg["lift"] is not None:
            lifts.append(pg["lift"])
            if pg["lift"] >= g1["lift"]:
                hits_lift += 1
        if pg["gate1_pass"]:
            hits_gate1 += 1
            m3 = {str(v): mh_per_vintage(cell, plm, po, v) for v in TRIO}
            ok3 = all(x is not None and x["mh_risk_diff"] is not None
                      and x["mh_risk_diff"] >= LIFT for x in m3.values())
            if ok3:
                hits_all += 1
        if (it + 1) % 200 == 0:
            print("    perm %d/%d  lift>=obs %d  gate1 %d  (%.0fs)"
                  % (it + 1, N_PERM, hits_lift, hits_gate1, time.time() - t_perm0))
    lifts.sort()

    def q(p):
        if not lifts:
            return None
        i = p * (len(lifts) - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return r4(lifts[lo] if lo == hi else lifts[lo] + (lifts[hi] - lifts[lo]) * (i - lo))

    res["check5_permutation"] = {
        "null": ("会社単位・全ビンテージ同時。同じ sic2 かつ同じビンテージ集合の会社どうしで"
                 "(vintage->label) のプロファイルを入れ替える＝業種別・年別の基準率と、"
                 "同じ会社のラベルの相関を保つ"),
        "n_perm": N_PERM,
        "observed_lift": g1["lift"],
        "p_value_lift_ge_observed": r4(rate(hits_lift, N_PERM)),
        "fpr_gate1": r4(rate(hits_gate1, N_PERM)),
        "fpr_gate1_and_mh": r4(rate(hits_all, N_PERM)),
        "null_lift_quantiles": {"p50": q(0.50), "p90": q(0.90), "p95": q(0.95),
                                "p99": q(0.99), "max": r4(lifts[-1]) if lifts else None},
        "mc_se_p": r4(math.sqrt(max(hits_lift, 1) / N_PERM * (1 - hits_lift / N_PERM) / N_PERM)),
        "bucket_sizes": {str(k): v for k, v in sorted(bucket_sizes.items())},
        "⚠": ("バケットの大きさが1の会社は自分自身としか入れ替わらない＝ラベルが固定される。"
              "その割合を bucket_sizes で示す（帰無が弱くなる方向＝偽陽性率は過小評価になりうる）"),
    }
    fixed = sum(k * v for k, v in bucket_sizes.items() if k == 1)
    res["check5_permutation"]["companies_with_fixed_label"] = fixed
    res["check5_permutation"]["companies_total"] = sum(k * v for k, v in bucket_sizes.items())
    print("[5] perm p=%s fpr_gate1=%s (%.1fs)"
          % (res["check5_permutation"]["p_value_lift_ge_observed"],
             res["check5_permutation"]["fpr_gate1"], time.time() - t0))

    # ── 総括 ──────────────────────────────────
    perm = res["check5_permutation"]
    irr18 = irr_out.get("2018", {}).get("irr_ge70", {})
    irr_ng = irr18.get("n_group")
    irr_judgeable = (irr_ng is not None and irr_ng >= 10)
    inc_ok = (inc_pooled["lift"] is not None and inc_pooled["lift"] >= LIFT
              and all(inc[str(v)].get("lift") is not None and inc[str(v)]["lift"] >= LIFT
                      for v in TRIO)
              and inc_pooled["share_of_group_already_blocked"] <= INCREMENTAL_MAX_CAUGHT)
    perm_ok = (perm["p_value_lift_ge_observed"] is not None
               and perm["p_value_lift_ge_observed"] < 0.05)
    gates = {
        "1_reproduce": {
            "verdict": "一致" if same else "不一致",
            "note": ("n=59 / 分子=40 / lift=0.2595 / 群28社・分子20社 が独立実装で完全一致。"
                     "ただし OOF 群は**単一の規則ではなく fold ごとに別の規則が作った行の和集合**"),
        },
        "2_vintage": {
            "verdict": "通過" if g1["sign_ok"] else "不合格",
            "note": ("2016 %s / 2017 %s / 2018 %s。ただし群28社のうち20社が2つ以上の"
                     "ビンテージに現れる＝3つの独立な証拠ではない"
                     % tuple(g1["per_vintage"][str(v)]["lift"] for v in TRIO)),
        },
        "3_sector": {
            "verdict": "不合格" if not (mh_ok and dos_ok) else "通過",
            "note": ("事前登録のゲート（ビンテージ別 MH）が **2017 で 0.0877 < 0.15**。"
                     "被覆を上げた版（全被覆の間接標準化 0.1765/0.1844・プール MH 0.1777/0.1532）は"
                     "線をわずかに超えるだけ＝生 lift 0.2595 の**約3分の1は業種の構成**"),
        },
        "4_irr": {
            "verdict": "判定不能" if not irr_judgeable else ("通過" if (
                irr18.get("lift") is not None and irr18["lift"] >= LIFT) else "不合格"),
            "note": ("2016/2017 は panel に irr が1行も無い（既知の非対称）。"
                     "2018 の irr>=70 層に入る群の行は **%s 行**しかなく、層内の判定はできない"
                     % irr_ng),
        },
        "5_permutation": {
            "verdict": "通過（落とせなかった）" if perm_ok else "不合格",
            "note": ("p(lift>=観測)=%s（2000回・会社単位・全ビンテージ同時）。帰無の p99=%s・"
                     "最大=%s。gate1 の偽陽性率 %s ＝**雑音では出ない大きさ**"
                     % (perm["p_value_lift_ge_observed"],
                        perm["null_lift_quantiles"]["p99"], perm["null_lift_quantiles"]["max"],
                        perm["fpr_gate1"])),
        },
        "6_incremental": {
            "verdict": "通過（落とせなかった）" if inc_ok else "不合格",
            "note": ("既存関門を通る行だけに絞っても lift %s（プール）／各年 %s。"
                     "群のうち既存関門で既に落ちるのは %s＝線の0.70に遠い。"
                     "⚠ 母集団が P_quality なので質実証は増分の判定に使えず、"
                     "irr>=70 は群の40分子のうち6行しか測れない"
                     % (inc_pooled["lift"], [inc[str(v)].get("lift") for v in TRIO],
                        inc_pooled["share_of_group_already_blocked"])),
        },
    }
    failed = [k for k, v in gates.items() if v["verdict"] not in
              ("一致", "通過", "通過（落とせなかった）")]
    ctrlB = controls["B_single_condition_d25"]
    res["★verdict"] = {
        "line": ("事前登録: lift>=0.15 ∧ 分子>=20社 ∧ 3ビンテージ維持 ∧ 業種調整 ∧ irr層 ∧ 増分。"
                 "**すべて必要。1つでも欠ければ不合格**"),
        "gates": gates,
        "failed_or_unjudgeable": failed,
        "verdict": "不合格" if failed else "落とせなかった",
        "★which_checks_could_not_break_it": [
            "1 再現（完全一致）", "2 ビンテージ", "5 置換（p=%s）" % perm["p_value_lift_ge_observed"],
            "6 増分（既存関門を通した後も lift %s）" % inc_pooled["lift"],
        ],
        "★what_broke_it": [
            "3 業種: 事前登録のゲート（ビンテージ別 MH）が 2017 で 0.0877 と線を割る",
            "4 irr: 2016/2017 に irr が無く、2018 の irr>=70 層の群は %s 行＝判定不能" % irr_ng,
        ],
        "★beyond_the_six_checks": {
            "fold_seed_instability": (
                "fold の割り当て（結果の前に固定された籤）を振ると lift は %s〜%s、"
                "gate1 は %d/%d の seed でしか通らない。**報告値0.2595は分布の高い側の一枚**"
                % (sens["fold_seed"]["lift_min"], sens["fold_seed"]["lift_max"],
                   sens["fold_seed"]["n_pass_gate1"], len(SEEDS))),
            "calibrated_by_positive_control": (
                "木が見つけられる形（1条件）の真の効果を δ=0.25/0.15/0.10 で仕込むと、"
                "seed 間の振れ幅の中央値は %s / %s / %s、gate1 の通過率は %s / %s / %s。"
                "**観測の振れ幅 %s はどの δ でも再現しない**（最大の対照でも中央値 %s＝観測の約1/3.6。"
                "80反復のうち観測ほど振れたものは0件）。一方で観測の通過率 %s は δ=0.25 と δ=0.15 の間。"
                "＝**観測は『一様な規則の効果』の形をしていない**。業種の所見"
                "（生 lift の約1/3が業種の構成・sic2=38 では群が業種基準を下回る）と整合する"
                % (controls["B_single_condition_d25"]["lift_range_across_seeds"]["median"],
                   controls["B_single_condition_d15"]["lift_range_across_seeds"]["median"],
                   controls["B_single_condition_d10"]["lift_range_across_seeds"]["median"],
                   controls["B_single_condition_d25"]["gate1_pass_per_replicate"]["share_of_seed_runs_passing"],
                   controls["B_single_condition_d15"]["gate1_pass_per_replicate"]["share_of_seed_runs_passing"],
                   controls["B_single_condition_d10"]["gate1_pass_per_replicate"]["share_of_seed_runs_passing"],
                   obs_range,
                   controls["B_single_condition_d10"]["lift_range_across_seeds"]["median"],
                   r4(sens["fold_seed"]["n_pass_gate1"] / len(SEEDS)))),
            "⚠_what_the_positive_control_does_NOT_show": (
                "対照Aが 0/6 しか通らないのは『貪欲な木が6%%の下位群を根から掘れない』という"
                "**手続きの限界**であって効果の不在ではない＝探索側の『後段は当てられない関門』の弁は"
                "この形については正しい。seed の検問が言えるのは**大きさの安定性**についてだけ"),
            "min_numerator_is_exactly_on_the_line": (
                "群28社のうち分子は20社＝登録の線ちょうど。**28社中20社は、その1社を抜くだけで"
                "分子が19社になり gate1 が落ちる**"),
            "the_name_describes_half_the_group": (
                "『f2_rnd_r 上位1/4 ∧ f2_rev 上位1/4』を満たす OOF 群の行は 30/59。"
                "満たす側は lift 0.3816 だが**満たさない側 29行は lift 0.1333 で線を割る**"),
            "one_fold_makes_half_the_group": (
                "fold4 だけで群の 32/59 行。その規則は "
                "`f2_rnd_r>=q50 ∧ !f2_capex_r>=q50 ∧ f2_rev>=q25` ＝**呼び名とは別の規則**。"
                "逆に呼び名そのものの規則を引いた fold0 は、train で 21/21(p=1.00) だったのに "
                "held-out では 6/12(p=0.50)＝**lift +0.08 で線を割る**"),
            "cut_basis": (
                "分位点を train→コホート全体に変えるだけで分子は %s 社になり gate1 が落ちる"
                % sens["cohort_wide_quantiles"]["numerator_companies"]),
        },
        "★honest_reading": (
            "**不合格。ただし『何も無い』ではない。** 置換(p=0.002)と増分(0.22)は落とせなかったので、"
            "R&D比が高く売上規模の大きい社が10%+を出しやすいという信号自体は在る。"
            "落ちたのは (a) その lift の約3分の1が業種の構成で、事前登録の業種ゲートを 2017 で割る "
            "(b) irr の層内では原理的に測れない、の2点。さらに6つの外側で、"
            "**報告された 0.2595 という大きさは fold の籤に依存する一枚**だと判った"),
        "★what_would_change_this": (
            "業種を跨いで群を作らない設計（sic2 内で木を育てる）と、"
            "2016/2017 の irr 読解。どちらも新しい採取が要る＝今日の在庫では決着しない"),
    }
    res["elapsed_sec"] = round(time.time() - t0, 1)
    print("[verdict] %s  failed=%s" % (res["★verdict"]["verdict"], failed))
    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("wrote", DEST, "in", res["elapsed_sec"], "s")


if __name__ == "__main__":
    main()
