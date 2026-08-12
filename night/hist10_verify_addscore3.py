#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_verify_addscore3.py — 角度D の唯一の合格配置を**潰しにかかる**検証。

対象（依頼文が名指しした候補）
  角度   : D（加法スコア＝美点の数）
  変数   : **3ビンテージの群の重なり**（「3年で維持」は3つの証拠か）
  目的   : y10 ＝ tr_cagr >= 0.10
  母集団 : P_quality × cov90_14（complete-case）
  切り方 : 合格配置の score>=2 群
           ＝ 変種T（発見年2016）・上下1/4二値化・J=3・s=2・ge
             sel = [f2_rev(hi), f2_rnd_r(hi), f2_cagr5(lo)]
  探索側の数字 : n_distinct=82 / n_in_all_three=30 / share=0.3659

事前登録: out/hist10_prereg.json（**線はそこにある。この道具は一つも作らない**）
入力    : out/hist_wd_panel.json / out/hist10_targets.json / out/hist10_angleD.json（照合用）
出力    : out/hist10_verify_addscore3.json

⚠ **独立実装**。night/hist10_diag.py も night/hist10_angleD.py も import しない
   （同じ実装を呼べば「一致」は自明になる。照合は探索側の**出力JSON**とだけ行う）。
   判定・採点・台帳・index.html・パックには一切触らない。読むだけの調査。

6つの検問（1つでも落ちたら不合格）
  1 再現   : 独立実装で n/分子/lift/重なりが一致するか（>= か > の境界の約束まで）
  2 ビンテージ: 2016/2017/2018 すべてで lift>=0.15 か。
              **かつ、その3つが独立な3つの証拠かを実測する**（＝この候補の変数そのもの）
  3 業種   : Mantel-Haenszel ＋ 業種を1つずつ抜いて残るか
  4 irrの影: irr>=70 層内でも残るか（測れないなら「判定不能」と書く）
  5 置換   : 会社単位で全ビンテージ同時に結果を並べ替える2000回
             (a) 配置固定の p 値 (b) **探索空間ぜんぶを含めた選択調整後**の偽陽性率
  6 増分   : 群の「10%+を出した社」が既存の関門でどれだけ説明されるか（7割超なら不合格）

★7本目（依頼された6つの外）——**ここで落ちた**
  事前登録 pass_line.for_D_and_E:
    「加法スコアと木は**外側foldでの性能のみ**を合否に使う。in-sample は参考値として明示」
  ところが out/hist10_angleD.json に交差検証の節が一つも無い（診断の nested_cv は角度E だけ）。
  ＝**事前登録が角度Dの合否に使えと書いている数字が、一度も測られていなかった**。
  会社単位5分割で測ったら、3ビンテージとも線(0.15)を割った。
  正の対照（列を固定＝分位点だけ train）は in-sample 満額を返すので protocol の副作用ではない。
"""

import json
import math
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
DEST = os.path.join(OUT, "hist10_verify_addscore3.json")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
TARGETS = os.path.join(OUT, "hist10_targets.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
ANGLED = os.path.join(OUT, "hist10_angleD.json")

N_PERM = int(os.environ.get("VERIFY_NPERM", 2000))
SEED = 20260812          # 探索側と同じ種（帰無の作り方まで同じにするため）
TRIO = [2016, 2017, 2018]

# ── 候補の定義（依頼文が固定した配置。この道具は何も選ばない） ──
CAND = {
    "pop": "P_quality", "subset": "cov90_14", "disc": 2016,
    "binar": "quartile", "J": 3, "s": 2, "mode": "ge",
}

# 探索側が実際に回した空間（選択調整後の偽陽性率で再現する）
SPACE_DISCS = [2016, 2018]
SPACE_BINARS = ["median", "quartile"]
SPACE_POPS = ["P_full", "P_quality"]
SPACE_JS = (3, 5, 8, 10)

COV90 = ["aturn", "cagr5", "rev", "capex_r", "accel", "streak_rev", "rnd_r", "cash_r",
         "accr", "fcfpos5", "gw_r", "opm", "streak_opm", "opmD5"]
F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r",
      "gw_r", "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5",
      "conv5", "netiss_r", "payout5", "rev"]
SUBSETS = {"cov90_14": ["f2_" + k for k in COV90], "all20": ["f2_" + k for k in F2]}


def r4(x):
    return None if x is None else round(x, 4)


def quantile(xs, q):
    """探索側と同じ線形補間の分位点（実装は独立に書いたが約束は同じ）。"""
    ys = sorted(xs)
    if not ys:
        return None
    i = q * (len(ys) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    return ys[lo] if lo == hi else ys[lo] + (ys[hi] - ys[lo]) * (i - lo)


def pc(x):
    return bin(x).count("1")


# ─────────────────────────── 読み込み ───────────────────────────
def load():
    with open(PANEL, encoding="utf-8") as f:
        panel = json.load(f)
    with open(TARGETS, encoding="utf-8") as f:
        tg = json.load(f)
    with open(PREREG, encoding="utf-8") as f:
        prereg = json.load(f)
    tmap = {(r["ticker"], r["vintage"]): r for r in tg["rows"]}
    rows = []
    for r in panel["rows"]:
        if not (r.get("has_outcome") and r.get("window_full")):
            continue
        t = tmap.get((r["ticker"], r["vintage"]))
        if t is None:
            continue
        q = dict(r)
        q["y10"] = t.get("y10")
        q["y_persist"] = t.get("y_persist")
        rows.append(q)
    return panel, tg, prereg, rows


def universe(rows, sname, pop, v):
    cols = SUBSETS[sname]
    rs = [r for r in rows if r["vintage"] == v]
    if pop == "P_quality":
        rs = [r for r in rs if r.get("P_quality") is True]
    rs = [r for r in rs
          if all(r.get(c) is not None for c in cols) and r.get("y10") is not None]
    return sorted(rs, key=lambda r: r["ticker"])


# ───────────────────── 二値化と加法スコア（独立実装） ─────────────────────
def side_masks(rs, col, binar):
    """(hi_mask, lo_mask)。境界: median は x>=med が hi・その補集合が lo。
    quartile は x>=q75 が hi・x<=q25 が lo（真ん中の半分はどちらでもない）。"""
    n = len(rs)
    full = (1 << n) - 1
    xs = [r[col] for r in rs]
    if binar == "median":
        med = quantile(xs, 0.5)
        hi = 0
        for i, r in enumerate(rs):
            if r[col] >= med:
                hi |= (1 << i)
        return hi, (full & ~hi)
    q25 = quantile(xs, 0.25)
    q75 = quantile(xs, 0.75)
    hi = lo = 0
    for i, r in enumerate(rs):
        if r[col] >= q75:
            hi |= (1 << i)
        if r[col] <= q25:
            lo |= (1 << i)
    return hi, lo


def pick_feats(cols, sm, lm, n, binar):
    """発見年の標本で各候補の『良い側』と |lift| を決め、(-|lift|, col) で並べる。
    median: lf>=0 なら hi（探索側 score_masks と同じ約束）
    quartile: hi/lo のうち **符号つき lift が大きい側**（探索側 feats_at と同じ）"""
    base = pc(lm) / n if n else 0.0
    feats = []
    for c in cols:
        hi, lo = sm[c]
        if binar == "median":
            m = pc(hi)
            if m == 0 or m == n:
                continue
            lf = pc(lm & hi) / m - base
            good = hi if lf >= 0 else lo
            feats.append({"col": c, "side": "hi" if lf >= 0 else "lo",
                          "abs_lift": abs(lf), "good": good})
        else:
            best = None
            for side, g in (("hi", hi), ("lo", lo)):
                m = pc(g)
                if m == 0 or m == n:
                    continue
                lf = pc(lm & g) / m - base
                if best is None or lf > best[1]:
                    best = (side, lf, g)
            if best is None:
                continue
            feats.append({"col": c, "side": best[0],
                          "abs_lift": abs(best[1]), "good": best[2]})
    feats.sort(key=lambda x: (-x["abs_lift"], x["col"]))
    return feats, base


def score_planes(masks, full):
    """bit-plane 加算器。planes[j] のビットが立つ＝スコアの2進 j 桁目が1。"""
    planes = [0] * (len(masks).bit_length() + 2)
    for m in masks:
        carry = m
        for j in range(len(planes)):
            new = planes[j] ^ carry
            carry = planes[j] & carry
            planes[j] = new
            if carry == 0:
                break
    return planes


def exact_and_ge(planes, J, full):
    """スコアちょうど v の mask と、v 以上の mask を一括で作る。"""
    ex = {}
    for v in range(0, J + 1):
        out = full
        for j, p in enumerate(planes):
            out &= p if (v >> j) & 1 else (full & ~p)
        ex[v] = out
    ge = {}
    acc = 0
    for v in range(J, -1, -1):
        acc |= ex[v]
        ge[v] = acc
    return ex, ge


def group_mask(ge, s, J, full, mode):
    if mode == "ge":
        return ge[s]
    return full & ~ge[s + 1] if (s + 1) in ge else full


# ─────────────────────────── 検問の道具 ───────────────────────────
def cell(lm, g, n, kd):
    m = pc(g)
    k = pc(lm & g)
    base = kd / n if n else 0.0
    return {"n": n, "n_group": m, "k": k, "p_group": r4(k / m) if m else None,
            "base": r4(base), "lift": r4(k / m - base) if m else None}


def mh_risk_diff(lm, g, full, strata_masks, min_cell=3):
    """Mantel-Haenszel 重み付きリスク差。w = n1*n0/(n1+n0)。n1<3 or n0<3 の層は落とす
    （探索側 mh_g と同じ足切り）。落とした層の重みも同時に返す＝『何割を見ていないか』。"""
    num = den = 0.0
    used = drop = 0
    n_used_rows = n_drop_rows = 0
    g_used = 0
    for sec, sm in strata_masks.items():
        n1 = pc(g & sm)
        n0 = pc(sm & ~g & full)
        if n1 < min_cell or n0 < min_cell:
            drop += 1
            n_drop_rows += n1 + n0
            continue
        k1 = pc(lm & g & sm)
        k0 = pc(lm & sm & ~g & full)
        w = n1 * n0 / (n1 + n0)
        num += w * (k1 / n1 - k0 / n0)
        den += w
        used += 1
        n_used_rows += n1 + n0
        g_used += n1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(num / den), "strata_used": used, "strata_dropped": drop,
            "rows_in_used_strata": n_used_rows, "rows_in_dropped_strata": n_drop_rows,
            "share_of_rows_used": r4(n_used_rows / (n_used_rows + n_drop_rows)),
            "group_members_in_used_strata": g_used,
            "share_of_group_used": r4(g_used / pc(g)) if pc(g) else None}


def drop_one_sector(lm, g, full, strata_masks, min_nb=40, min_g=10):
    """業種を1つずつ抜いた最悪 lift（探索側と同じ足切り: 残り>=40行・群>=10）。"""
    worst = None
    tbl = []
    for sec, sm in strata_masks.items():
        keep = full & ~sm
        nb = pc(keep)
        gg = g & keep
        m = pc(gg)
        if nb < min_nb or m < min_g:
            continue
        k = pc(lm & gg)
        base = pc(lm & keep) / nb
        lf = k / m - base
        tbl.append({"dropped_sector": sec, "n_group": m, "k": k, "lift": r4(lf)})
        if worst is None or lf < worst["lift_raw"]:
            worst = {"dropped_sector": sec, "n_group": m, "k": k,
                     "lift": r4(lf), "lift_raw": lf}
    tbl.sort(key=lambda x: x["lift"])
    if worst:
        worst.pop("lift_raw")
    return worst, tbl[:5]


def drop_two_sectors(lm, g, full, strata_masks, min_nb=40, min_g=10):
    """**事前登録の外**（登録は『1つずつ』）。参考値として最悪の2業種同時抜きを出す。"""
    secs = list(strata_masks.items())
    worst = None
    for i in range(len(secs)):
        for j in range(i + 1, len(secs)):
            keep = full & ~secs[i][1] & ~secs[j][1]
            nb = pc(keep)
            gg = g & keep
            m = pc(gg)
            if nb < min_nb or m < min_g:
                continue
            k = pc(lm & gg)
            lf = k / m - pc(lm & keep) / nb
            if worst is None or lf < worst[0]:
                worst = (lf, secs[i][0], secs[j][0], m, k)
    if worst is None:
        return None
    return {"dropped": [worst[1], worst[2]], "n_group": worst[3], "k": worst[4],
            "lift": r4(worst[0])}


# ─────────────────────────── 帰無（置換） ───────────────────────────
def build_perm(rows, seed=SEED):
    """会社単位で全ビンテージ同時に y10 を並べ替える（sic2 の層内）。
    ビンテージ内で独立に混ぜると従属が壊れて偽陽性率を大きく過小評価する
    ——v2 の実測で33倍。探索側 perm_engine と同じ帰無を独立に組む。"""
    rnd = random.Random(seed)
    full = {v: sorted([r for r in rows if r["vintage"] == v], key=lambda r: r["ticker"])
            for v in TRIO}
    lab = {v: {r["ticker"]: (1 if r["y10"] else 0) for r in full[v] if r.get("y10") is not None}
           for v in TRIO}
    sic_of = {}
    for v in TRIO:
        for r in full[v]:
            sic_of[r["ticker"]] = r.get("sic2")
    common = set(lab[2016]) & set(lab[2017]) & set(lab[2018])
    by_sic = defaultdict(list)
    for t in sorted(common):
        by_sic[sic_of[t]].append(t)
    solo = {v: defaultdict(list) for v in TRIO}
    for v in TRIO:
        for t in lab[v]:
            if t not in common:
                solo[v][sic_of[t]].append(t)

    def draw(shuffle=True):
        if not shuffle:
            return {v: dict(lab[v]) for v in TRIO}
        mp = {}
        for _s, ts in by_sic.items():
            sh = list(ts)
            rnd.shuffle(sh)
            for a, b in zip(ts, sh):
                mp[a] = b
        out = {}
        for v in TRIO:
            cur = {t: lab[v][mp[t]] for t in common}
            for _s, ts in solo[v].items():
                vals = [lab[v][t] for t in ts]
                rnd.shuffle(vals)
                for t, x in zip(ts, vals):
                    cur[t] = x
            out[v] = cur
        return out

    info = {"n_common_tickers": len(common), "n_strata": len(by_sic),
            "n_solo_by_vintage": {str(v): sum(len(x) for x in solo[v].values()) for v in TRIO}}
    return draw, info


def main():
    panel, tg, prereg, rows = load()
    LIFT = prereg["pass_line"]["lift"] if isinstance(prereg["pass_line"]["lift"], float) else 0.15
    MIN_NUM = 20
    INCR_MAX = 0.70
    # 事前登録から読む（この道具は線を作らない）
    assert abs(LIFT - 0.15) < 1e-9

    out = {
        "generated": "2026-08-12",
        "tool": "night/hist10_verify_addscore3.py",
        "prereg": "out/hist10_prereg.json",
        "role": "反証。確認ではない。6検問のうち1つでも落ちたら不合格",
        "independence_of_implementation":
            "night/hist10_diag.py も night/hist10_angleD.py も import していない。"
            "照合は探索側の出力 out/hist10_angleD.json とだけ行う",
        "candidate": dict(CAND),
        "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM,
                           "incremental_max_caught": INCR_MAX,
                           "src": "out/hist10_prereg.json"},
    }

    # ───────── 全部の宇宙・マスクを組む ─────────
    U, SM, LM, ND, KD, FULL, STR = {}, {}, {}, {}, {}, {}, {}
    for sname in SUBSETS:
        for pop in SPACE_POPS:
            for v in TRIO:
                rs = universe(rows, sname, pop, v)
                n = len(rs)
                U[(sname, pop, v)] = rs
                FULL[(sname, pop, v)] = (1 << n) - 1
                sm = {}
                for binar in SPACE_BINARS:
                    for c in SUBSETS[sname]:
                        sm[(binar, c)] = side_masks(rs, c, binar)
                SM[(sname, pop, v)] = sm
                lm = 0
                kd = 0
                for i, r in enumerate(rs):
                    if r["y10"]:
                        lm |= (1 << i)
                        kd += 1
                LM[(sname, pop, v)] = lm
                ND[(sname, pop, v)] = n
                KD[(sname, pop, v)] = kd
                st = defaultdict(int)
                for i, r in enumerate(rs):
                    if r.get("sic2"):
                        st[r["sic2"]] |= (1 << i)
                STR[(sname, pop, v)] = dict(st)

    key = (CAND["subset"], CAND["pop"])
    disc = CAND["disc"]
    binar = CAND["binar"]
    J, s, mode = CAND["J"], CAND["s"], CAND["mode"]

    # ───────── 1 再現 ─────────
    rsD = U[key + (disc,)]
    smD = {c: SM[key + (disc,)][(binar, c)] for c in SUBSETS[key[0]]}
    featsD, baseD = pick_feats(SUBSETS[key[0]], smD, LM[key + (disc,)], ND[key + (disc,)], binar)
    sel = [f["col"] for f in featsD[:J]]
    sides = [f["side"] for f in featsD[:J]]

    per_v = {}
    gmask = {}
    members = {}
    for v in TRIO:
        rs = U[key + (v,)]
        full = FULL[key + (v,)]
        masks = []
        for f in featsD[:J]:
            hi, lo = SM[key + (v,)][(binar, f["col"])]
            masks.append(hi if f["side"] == "hi" else lo)
        pl = score_planes(masks, full)
        _ex, ge = exact_and_ge(pl, J, full)
        g = group_mask(ge, s, J, full, mode)
        gmask[v] = g
        per_v[v] = cell(LM[key + (v,)], g, ND[key + (v,)], KD[key + (v,)])
        members[v] = sorted(rs[i]["ticker"] for i in range(len(rs)) if (g >> i) & 1)

    setv = {v: set(members[v]) for v in TRIO}
    distinct = setv[2016] | setv[2017] | setv[2018]
    all3 = setv[2016] & setv[2017] & setv[2018]

    with open(ANGLED, encoding="utf-8") as f:
        aD = json.load(f)
    disc_pass = aD["passes"][0]
    disc_ov = disc_pass["detail"]["group_overlap"]
    disc_pv = disc_pass["per_v"]

    mism = []
    for v in TRIO:
        d = disc_pv[str(v)]
        mine = per_v[v]
        for a, b, nm in ((mine["n_group"], d["m"], "n_group"), (mine["k"], d["k"], "k"),
                         (mine["base"], d["base"], "base"), (mine["lift"], d["lift"], "lift"),
                         (mine["p_group"], d["p"], "p_group")):
            if a != b:
                mism.append({"vintage": v, "field": nm, "mine": a, "discovery": b})
    ov_mine = {"n_group_by_vintage": {str(v): len(setv[v]) for v in TRIO},
               "n_distinct_companies": len(distinct),
               "n_in_all_three": len(all3),
               "share_in_all_three": r4(len(all3) / len(distinct))}
    ov_mism = []
    for k2 in ("n_distinct_companies", "n_in_all_three", "share_in_all_three"):
        if ov_mine[k2] != disc_ov[k2]:
            ov_mism.append({"field": k2, "mine": ov_mine[k2], "discovery": disc_ov[k2]})
    for v in TRIO:
        if ov_mine["n_group_by_vintage"][str(v)] != disc_ov["n_group_by_vintage"][str(v)]:
            ov_mism.append({"field": f"n_group_by_vintage/{v}",
                            "mine": ov_mine["n_group_by_vintage"][str(v)],
                            "discovery": disc_ov["n_group_by_vintage"][str(v)]})
    # 探索側 attacks_on_passes の members とも突き合わせる（銘柄名まで一致するか）
    acell = list(aD["attacks_on_passes"]["cells"].values())[0]
    mem_mism = {}
    for v in TRIO:
        dm = set(acell["members"].get(str(v), []))
        if dm:
            mem_mism[str(v)] = {"only_mine": sorted(setv[v] - dm),
                                "only_discovery": sorted(dm - setv[v])}

    out["t1_reproduce"] = {
        "member_diff_vs_discovery": mem_mism,
        "selected_columns": sel, "sides": sides,
        "feats_ranking_at_disc": [{"col": f["col"], "side": f["side"], "abs_lift": r4(f["abs_lift"])}
                                  for f in featsD[:6]],
        "per_vintage": {str(v): per_v[v] for v in TRIO},
        "group_overlap_mine": ov_mine,
        "group_overlap_discovery": {k2: disc_ov[k2] for k2 in
                                    ("n_group_by_vintage", "n_distinct_companies",
                                     "n_in_all_three", "share_in_all_three")},
        "mismatches_per_v": mism,
        "mismatches_overlap": ov_mism,
        "member_mismatch_count": sum(len(x["only_mine"]) + len(x["only_discovery"])
                                     for x in mem_mism.values()),
        "boundary_conventions": {
            "hi": "x >= q75", "lo": "x <= q25",
            "quantile": "sorted, i=q*(n-1), 線形補間（探索側と同じ約束）",
            "group": "score >= s（ge）", "base": "k_defined / n_defined",
            "min_group": "m >= 20 かつ m < n",
        },
        "verdict": ("一致" if (not mism and not ov_mism
                              and sum(len(x["only_mine"]) + len(x["only_discovery"])
                                      for x in mem_mism.values()) == 0)
                    else "不一致"),
    }

    # ───────── 2 ビンテージ ＋ 独立性の実測（＝この候補の変数そのもの） ─────────
    lifts = [per_v[v]["lift"] for v in TRIO]
    ks = [per_v[v]["k"] for v in TRIO]
    gate2 = all(l is not None and l >= LIFT for l in lifts) and all(k >= MIN_NUM for k in ks)

    # (a) 宇宙そのものの重なり
    uni_t = {v: {r["ticker"] for r in U[key + (v,)]} for v in TRIO}
    # (b) 同じ会社の y10 がビンテージ間でどれだけ一致するか
    y = {v: {r["ticker"]: bool(r["y10"]) for r in U[key + (v,)]} for v in TRIO}
    agree = {}
    for a in TRIO:
        for b in TRIO:
            if a >= b:
                continue
            com = uni_t[a] & uni_t[b]
            same = sum(1 for t in com if y[a][t] == y[b][t])
            k11 = sum(1 for t in com if y[a][t] and y[b][t])
            k1_ = sum(1 for t in com if y[a][t])
            k_1 = sum(1 for t in com if y[b][t])
            n = len(com)
            po = same / n
            pe = (k1_ / n) * (k_1 / n) + (1 - k1_ / n) * (1 - k_1 / n)
            agree[f"{a}v{b}"] = {"n_common": n, "agreement": r4(po),
                                 "cohen_kappa": r4((po - pe) / (1 - pe)) if pe < 1 else None,
                                 "both_yes": k11}
    # (c) 群の重なり（Jaccard）
    jac = {}
    for a in TRIO:
        for b in TRIO:
            if a >= b:
                continue
            jac[f"{a}v{b}"] = r4(len(setv[a] & setv[b]) / len(setv[a] | setv[b]))
    # (d) 窓の重なり
    yrs = {}
    for v in TRIO:
        vv = [r["years"] for r in U[key + (v,)] if r.get("years")]
        yrs[str(v)] = r4(sorted(vv)[len(vv) // 2]) if vv else None
    win = {"windows_end_same_year": "3ビンテージとも 2026 で終わる",
           "median_years": yrs,
           "shared_share_of_2016_window": r4(yrs["2018"] / yrs["2016"]) if yrs["2016"] else None,
           "shared_share_of_2017_window": r4(yrs["2018"] / yrs["2017"]) if yrs["2017"] else None}
    # (e) 会社1社=1観測にしたときの実数
    comp_all3 = all3
    comp_none = (uni_t[2016] & uni_t[2017] & uni_t[2018]) - distinct
    def comp_rate(ts, v):
        ts = [t for t in ts if t in y[v]]
        return {"n": len(ts), "k": sum(1 for t in ts if y[v][t]),
                "p": r4(sum(1 for t in ts if y[v][t]) / len(ts)) if ts else None}
    company_level = {
        "def": "会社を1回だけ数える。群=3ビンテージすべてに入った会社／対照=一度も入らなかった会社。"
               "結果は 2018 の窓（3つのうち最短＝他の2つに完全に含まれる）",
        "group_all3": comp_rate(comp_all3, 2018),
        "control_never": comp_rate(comp_none, 2018),
        "base_whole_2018_universe": {"n": ND[key + (2018,)], "k": KD[key + (2018,)],
                                     "p": r4(KD[key + (2018,)] / ND[key + (2018,)])},
    }
    if company_level["group_all3"]["p"] is not None:
        b18 = KD[key + (2018,)] / ND[key + (2018,)]
        company_level["lift_vs_control_never"] = r4(
            company_level["group_all3"]["p"] - company_level["control_never"]["p"])
        company_level["lift_vs_whole_universe"] = r4(company_level["group_all3"]["p"] - b18)
        company_level["min_numerator_met"] = company_level["group_all3"]["k"] >= MIN_NUM
        company_level["⚠"] = ("対照を『一度も入らなかった会社』にすると、1〜2回だけ入った52社を"
                              "両側から外すので差が大きく出る。母集団全体を基準にした値も併記した")

    # 群は結局『大きい会社』ではないのか（f2_rev(hi) が選ばれた第1変数）
    size_proxy = {}
    for v in TRIO:
        hi_rev, _lo = SM[key + (v,)][(binar, "f2_rev")]
        lm = LM[key + (v,)]
        full = FULL[key + (v,)]
        n = ND[key + (v,)]
        b = KD[key + (v,)] / n
        g = gmask[v]
        inside = g & hi_rev
        outside = g & ~hi_rev & full
        # f2_rev(hi) 層の中だけで、群に入るかどうかで差が付くか
        lay = hi_rev
        nlay = pc(lay)
        blay = pc(lm & lay) / nlay if nlay else None
        glay = g & lay
        size_proxy[str(v)] = {
            "f2_rev_hi_alone": {"n_group": nlay, "k": pc(lm & lay),
                                "lift": r4(pc(lm & lay) / nlay - b) if nlay else None},
            "jaccard_group_vs_f2_rev_hi": r4(pc(g & hi_rev) / pc(g | hi_rev)),
            "group_inside_rev_hi": {"n": pc(inside), "k": pc(lm & inside),
                                    "p": r4(pc(lm & inside) / pc(inside)) if pc(inside) else None},
            "group_outside_rev_hi": {"n": pc(outside), "k": pc(lm & outside),
                                     "p": r4(pc(lm & outside) / pc(outside)) if pc(outside) else None},
            "lift_within_rev_hi_layer": r4(pc(lm & glay) / pc(glay) - blay) if pc(glay) and blay is not None else None,
        }

    out["t2_vintage"] = {
        "lifts": {str(v): per_v[v]["lift"] for v in TRIO},
        "numerators": {str(v): per_v[v]["k"] for v in TRIO},
        "gate_met": gate2,
        "independence": {
            "why": "依頼文が名指しした変数そのもの。『3年で維持』が3つの証拠なら符号不変ゲートは強い。"
                   "同じ会社・重なる窓を3回数えているだけなら、それは1つの証拠",
            "universe_ticker_overlap_jaccard": {
                f"{a}v{b}": r4(len(uni_t[a] & uni_t[b]) / len(uni_t[a] | uni_t[b]))
                for a in TRIO for b in TRIO if a < b},
            "group_overlap_jaccard": jac,
            "outcome_agreement_same_company": agree,
            "return_windows": win,
            "company_level_one_row_per_company": company_level,
        },
        "is_the_score_just_size": {
            "why": "選ばれた第1変数が f2_rev(hi)＝売上の上位1/4。群がほぼそれなら"
                   "『美点の数』という新しい関数形ではなく規模の粗い測り方にすぎない",
            "by_vintage": size_proxy,
        },
        "verdict": "合格" if gate2 else "不合格",
    }

    # ───────── 3 業種 ─────────
    sec = {}
    for v in TRIO:
        mh = mh_risk_diff(LM[key + (v,)], gmask[v], FULL[key + (v,)], STR[key + (v,)])
        w, tbl = drop_one_sector(LM[key + (v,)], gmask[v], FULL[key + (v,)], STR[key + (v,)])
        d2 = drop_two_sectors(LM[key + (v,)], gmask[v], FULL[key + (v,)], STR[key + (v,)])
        cnt = defaultdict(int)
        rs = U[key + (v,)]
        for i in range(len(rs)):
            if (gmask[v] >> i) & 1 and rs[i].get("sic2"):
                cnt[rs[i]["sic2"]] += 1
        top = sorted(cnt.items(), key=lambda x: -x[1])[:5]
        sec[str(v)] = {"mh": mh, "worst_drop_one": w, "five_worst_drops": tbl,
                       "drop_two_worst_OUTSIDE_PREREG": d2,
                       "group_sector_concentration_top5": [{"sic2": a, "n": b} for a, b in top]}
    mh_ok = all(sec[str(v)]["mh"] and sec[str(v)]["mh"]["mh_risk_diff"] >= LIFT for v in TRIO)
    d1_ok = all(sec[str(v)]["worst_drop_one"] and sec[str(v)]["worst_drop_one"]["lift"] >= LIFT
                for v in TRIO)
    out["t3_sector"] = {
        "by_vintage": sec, "mh_ok": mh_ok, "drop_one_ok": d1_ok,
        "margin_over_line": {str(v): r4(sec[str(v)]["worst_drop_one"]["lift"] - LIFT)
                             for v in TRIO if sec[str(v)]["worst_drop_one"]},
        "verdict": "合格" if (mh_ok and d1_ok) else "不合格",
    }

    # ───────── 4 irr の影 ─────────
    def spearman(a, b):
        n = len(a)
        if n < 8:
            return None
        def rk(v):
            idx = sorted(range(n), key=lambda i: v[i])
            r = [0.0] * n
            i = 0
            while i < n:
                j = i
                while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                    j += 1
                avg = (i + j) / 2.0 + 1.0
                for t in range(i, j + 1):
                    r[idx[t]] = avg
                i = j + 1
            return r
        x, z = rk(a), rk(b)
        mx, mz = sum(x) / n, sum(z) / n
        num = sum((x[i] - mx) * (z[i] - mz) for i in range(n))
        dx = math.sqrt(sum((t - mx) ** 2 for t in x))
        dz = math.sqrt(sum((t - mz) ** 2 for t in z))
        return None if dx == 0 or dz == 0 else num / (dx * dz)

    irr_res = {}
    for v in TRIO:
        rs = U[key + (v,)]
        for fld in ("irr", "irr_near"):
            idx = [i for i, r in enumerate(rs) if r.get(fld) is not None]
            if len(idx) < 20:
                irr_res[f"{v}/{fld}"] = {"n_with_irr": len(idx), "status": "判定不能（irr の被覆が薄い）"}
                continue
            lay = [i for i in idx if rs[i][fld] >= 70]
            nlay = len(lay)
            klay = sum(1 for i in lay if rs[i]["y10"])
            gl = [i for i in lay if (gmask[v] >> i) & 1]
            kg = sum(1 for i in gl if rs[i]["y10"])
            # スコア（0..J）と irr の順位相関
            sc = []
            for i in idx:
                cscore = 0
                for f in featsD[:J]:
                    hi, lo = SM[key + (v,)][(binar, f["col"])]
                    mm = hi if f["side"] == "hi" else lo
                    cscore += 1 if (mm >> i) & 1 else 0
                sc.append(cscore)
            rho = spearman(sc, [rs[i][fld] for i in idx])
            se = 1.0 / math.sqrt(len(idx) - 3) if len(idx) > 3 else None
            ci = None
            if rho is not None and se:
                zz = 0.5 * math.log((1 + rho) / (1 - rho)) if abs(rho) < 1 else None
                if zz is not None:
                    lo_, hi_ = zz - 1.96 * se, zz + 1.96 * se
                    ci = [r4(math.tanh(lo_)), r4(math.tanh(hi_))]
            irr_res[f"{v}/{fld}"] = {
                "n_with_irr": len(idx),
                "layer_irr_ge70": {"n": nlay, "base": r4(klay / nlay) if nlay else None,
                                   "n_group": len(gl), "k": kg,
                                   "p_group": r4(kg / len(gl)) if gl else None,
                                   "lift": r4(kg / len(gl) - klay / nlay) if gl and nlay else None},
                "min_num_met_in_layer": kg >= MIN_NUM,
                "spearman_score_vs_irr": r4(rho), "spearman_95ci": ci,
            }
    layer_judgeable = any(x.get("min_num_met_in_layer") for x in irr_res.values())
    rhos = [x["spearman_score_vs_irr"] for x in irr_res.values()
            if x.get("spearman_score_vs_irr") is not None]
    orth = all(abs(x) < 0.15 for x in rhos) if rhos else False
    ci_clean = all(x.get("spearman_95ci") is None or abs(x["spearman_95ci"][0]) < 0.15
                   and abs(x["spearman_95ci"][1]) < 0.15 for x in irr_res.values())
    out["t4_irr_layer"] = {
        "note": "事前登録の条件は『irr>=70 層内でも残る、**または** irr と直交』（OR）。"
                "層の側だけを見て不合格と書くのは線を動かすことになるので、両方を出す",
        "cells": irr_res,
        "branch_1_layer": {"judgeable": layer_judgeable,
                           "status": "判定不能（層内の分子が最大でも10で 20 に届かない）"
                           if not layer_judgeable else "判定可能"},
        "branch_2_orthogonal": {"all_cells_abs_rho_below_0.15": orth,
                                "rhos": rhos,
                                "ci_also_below_0.15_everywhere": ci_clean,
                                "⚠": "点推定は4セルとも |ρ|<0.15 だが、n=113〜288 なので"
                                     "95%CI の上端は 0.15 を超えるセルがある＝"
                                     "『直交』は幅の中でしか言えていない"},
        "verdict": "合格" if (layer_judgeable or orth) else "判定不能",
        "verdict_layer_branch_only": "合格" if layer_judgeable else "判定不能",
    }

    # ───────── 6 増分（5より先に置く：置換で使い回すため） ─────────
    def blocked_mask(sname, pop, v, use_irr=False):
        rs = U[(sname, pop, v)]
        b = 0
        for i, r in enumerate(rs):
            shrink = (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
                      and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)
            thin = r.get("f2_intcov") is not None and r["f2_intcov"] < 3
            notq = not r.get("P_quality")
            irrlow = False
            if use_irr:
                iv = r.get("irr") if r.get("irr") is not None else r.get("irr_near")
                irrlow = (iv is not None and iv < 70)
            if shrink or thin or notq or irrlow:
                b |= (1 << i)
        return b

    BLK = {}
    for sname in SUBSETS:
        for pop in SPACE_POPS:
            for v in TRIO:
                BLK[(sname, pop, v)] = blocked_mask(sname, pop, v)

    incr = {}
    for v in TRIO:
        full = FULL[key + (v,)]
        lm = LM[key + (v,)]
        blk = BLK[key + (v,)]
        keep = full & ~blk
        g = gmask[v]
        gk = g & keep
        nb = pc(keep)
        # 群の「10%+を出した社」の何割が既存の関門の中にいるか
        win_in_group = lm & g
        n_win = pc(win_in_group)
        n_win_blocked = pc(win_in_group & blk)
        rec = {
            "group_n": pc(g), "group_k_10pct": n_win,
            "group_already_blocked": pc(g & blk),
            "share_of_group_already_blocked": r4(pc(g & blk) / pc(g)),
            "winners_already_blocked": n_win_blocked,
            "share_of_winners_already_blocked": r4(n_win_blocked / n_win) if n_win else None,
            "within_gate_passers": {
                "n": nb, "n_group": pc(gk), "k": pc(lm & gk),
                "base": r4(pc(lm & keep) / nb) if nb else None,
                "lift": r4(pc(lm & gk) / pc(gk) - pc(lm & keep) / nb) if pc(gk) else None,
                "min_num_met": pc(lm & gk) >= MIN_NUM,
            },
        }
        # irr>=70 も既存の関門に加えた版（依頼文の指定）
        blk2 = blocked_mask(key[0], key[1], v, use_irr=True)
        keep2 = full & ~blk2
        gk2 = g & keep2
        rec["with_irr70_gate"] = {
            "n": pc(keep2), "n_group": pc(gk2), "k": pc(lm & gk2),
            "lift": r4(pc(lm & gk2) / pc(gk2) - pc(lm & keep2) / pc(keep2)) if pc(gk2) and pc(keep2) else None,
            "min_num_met": pc(lm & gk2) >= MIN_NUM,
            "note": "irr は 2016/2017 に読解が無く irr_near で代用。空欄は『低い』と読まない（欠測を0と読まない）",
        }
        incr[str(v)] = rec
    caught = [incr[str(v)]["share_of_winners_already_blocked"] for v in TRIO]
    incr_lift_ok = all(incr[str(v)]["within_gate_passers"]["lift"] is not None
                       and incr[str(v)]["within_gate_passers"]["lift"] >= LIFT for v in TRIO)
    incr_num_ok = all(incr[str(v)]["within_gate_passers"]["min_num_met"] for v in TRIO)
    caught_ok = all(c is not None and c <= INCR_MAX for c in caught)
    out["t6_incremental"] = {
        "existing_gates": "質実証(P_quality) ∧ 事業の収縮(f2_cagr5<0 ∧ f2_opmD5<0) ∧ 薄い財務(f2_intcov<3)"
                          "（＋依頼文の指定で irr>=70 を足した版も併記）",
        "⚠": "母集団が既に P_quality なので、質実証はこの検問の中で**常に通過**する。"
             "残る関門は収縮と薄い財務の2本だけ＝この検問はもともと弱い",
        "by_vintage": incr,
        "share_of_winners_already_blocked_3v": caught,
        "line": INCR_MAX,
        "verdict": "合格" if (caught_ok and incr_lift_ok and incr_num_ok) else "不合格",
    }

    # ───────── 5 置換 ─────────
    draw, perm_info = build_perm(rows, SEED)

    def labs_to_masks(labs):
        mm = {}
        for k2, rs in U.items():
            lv = labs[k2[2]]
            lm = 0
            kd = 0
            nd = 0
            for i, r in enumerate(rs):
                x = lv.get(r["ticker"])
                if x is None:
                    continue
                nd += 1
                if x:
                    lm |= (1 << i)
                    kd += 1
            mm[k2] = (lm, nd, kd)
        return mm

    # (a) 配置固定の p 値: 統計量 = 3ビンテージの lift の最小値
    obs_min = min(lifts)
    ge_cnt = 0           # 統計量（3年の最小 lift）が観測以上
    gate1_cnt = 0        # 配置固定で gate1（lift ∧ 分子 ∧ 同符号）を通る
    one_v_cnt = 0        # 2016 だけを見たときの p（＝『1つの証拠』の値札）
    cond_cnt = 0         # 2016 が通った条件の下で 2017/2018 も通る回数
    each_v_cnt = [0, 0, 0]
    npass_hist = [0, 0, 0, 0]
    perm_min = []
    for _ in range(N_PERM):
        labs = draw(True)
        mm = labs_to_masks(labs)
        ls, kk = [], []
        for v in TRIO:
            lm, nd, kd = mm[key + (v,)]
            g = gmask[v]
            m = pc(g)
            k = pc(lm & g)
            ls.append(k / m - (kd / nd if nd else 0))
            kk.append(k)
        mn = min(ls)
        perm_min.append(mn)
        if mn >= obs_min:
            ge_cnt += 1
        ok3 = [ls[i] >= LIFT and kk[i] >= MIN_NUM for i in range(3)]
        for i in range(3):
            if ok3[i]:
                each_v_cnt[i] += 1
        npass_hist[sum(ok3)] += 1
        if all(ok3):
            gate1_cnt += 1
        if ok3[0]:
            one_v_cnt += 1
            if ok3[1] and ok3[2]:
                cond_cnt += 1
    perm_min.sort()
    p_each = [c / N_PERM for c in each_v_cnt]
    p_indep = p_each[0] * p_each[1] * p_each[2]
    out_a = {
        "statistic": "3ビンテージの lift の最小値",
        "observed": r4(obs_min),
        "n_perm": N_PERM,
        "p_one_sided": r4(ge_cnt / N_PERM),
        "p_gate1_for_this_fixed_config": r4(gate1_cnt / N_PERM),
        "null_p95": r4(perm_min[int(0.95 * N_PERM)]),
        "null_median": r4(perm_min[N_PERM // 2]),
        "⚠": "これは**配置を事前に決めていた場合の**値札。実際にはこの配置は探索で選ばれた",
    }
    out_b_cond = {
        "why": "依頼文の変数そのもの。『3年で維持』が独立な3つの証拠なら、"
               "1年通った条件の下で残り2年も通る確率は小さいはず",
        "P(each vintage passes alone | null)": {str(TRIO[i]): r4(p_each[i]) for i in range(3)},
        "P(all three pass | null) OBSERVED": r4(gate1_cnt / N_PERM),
        "P(all three pass | null) IF INDEPENDENT": r4(p_indep),
        "ratio_observed_over_independent": r4((gate1_cnt / N_PERM) / p_indep) if p_indep > 0 else None,
        "P(2016 passes | null)": r4(one_v_cnt / N_PERM),
        "P(2017 and 2018 also pass | 2016 passed, null)":
            r4(cond_cnt / one_v_cnt) if one_v_cnt else None,
        "n_vintages_passing_histogram_under_null": {str(i): npass_hist[i] for i in range(4)},
        "effective_number_of_independent_vintages":
            r4(math.log(gate1_cnt / N_PERM) / math.log(sum(p_each) / 3))
            if gate1_cnt > 0 and 0 < sum(p_each) / 3 < 1 else None,
        "read": "条件付き確率が大きいほど、符号不変ゲートは**証拠を増やしていない**。"
                "実効ビンテージ数 = log P(3年とも) / log P(1年) （独立なら 3.0）",
    }

    # (b) 選択調整後：探索空間ぜんぶを含めた偽陽性率（全ゲートまで）
    def full_search_pass(mm, want_detail=False):
        """1回の（本物 or 置換）標本で、探索空間のどこかに
        『gate1 ∧ 業種(MH+1つ抜き) ∧ 増分』を通る配置があるか。
        irr 層は本物のデータでも判定不能なので、ここでは**課さない**
        （課すと帰無側でも常に不成立になり値札が甘く出る）。"""
        n_g1 = 0
        n_all = 0
        hits = []
        for d in SPACE_DISCS:
            for bn in SPACE_BINARS:
                for sname in SUBSETS:
                    cols = SUBSETS[sname]
                    for pop in SPACE_POPS:
                        kk = (sname, pop)
                        if ND[kk + (d,)] < 100:
                            continue
                        lmD, ndD, kdD = mm[kk + (d,)]
                        smD2 = {c: SM[kk + (d,)][(bn, c)] for c in cols}
                        fts, _b = pick_feats(cols, smD2, lmD, ndD, bn)
                        if not fts:
                            continue
                        Js = sorted({j for j in tuple(SPACE_JS) + (len(fts),)
                                     if 1 <= j <= len(fts)})
                        pre = {}
                        for v in TRIO:
                            full = FULL[kk + (v,)]
                            gm = []
                            for f in fts:
                                hi, lo = SM[kk + (v,)][(bn, f["col"])]
                                gm.append(hi if f["side"] == "hi" else lo)
                            pre[v] = (full, gm)
                        for Jx in Js:
                            gecache = {}
                            for v in TRIO:
                                full, gm = pre[v]
                                pl = score_planes(gm[:Jx], full)
                                _e, ge = exact_and_ge(pl, Jx, full)
                                gecache[v] = ge
                            for sx in range(1, Jx + 1):
                                for md in ("ge", "le"):
                                    ok = True
                                    up = None
                                    gmk = {}
                                    for v in TRIO:
                                        full = pre[v][0]
                                        g = group_mask(gecache[v], sx, Jx, full, md)
                                        m = pc(g)
                                        if m < MIN_NUM or m >= ND[kk + (v,)]:
                                            ok = False
                                            break
                                        lmv, ndv, kdv = mm[kk + (v,)]
                                        k = pc(lmv & g)
                                        base = kdv / ndv if ndv else 0
                                        lf = k / m - base
                                        if up is None:
                                            up = lf > 0
                                        if k < MIN_NUM or abs(lf) < LIFT or ((lf > 0) != up):
                                            ok = False
                                            break
                                        gmk[v] = g
                                    if not ok:
                                        continue
                                    n_g1 += 1
                                    # 業種
                                    good = True
                                    for v in TRIO:
                                        lmv, ndv, kdv = mm[kk + (v,)]
                                        mh = mh_risk_diff(lmv, gmk[v], FULL[kk + (v,)],
                                                          STR[kk + (v,)])
                                        if mh is None or abs(mh["mh_risk_diff"]) < LIFT:
                                            good = False
                                            break
                                        w, _t = drop_one_sector(lmv, gmk[v], FULL[kk + (v,)],
                                                                STR[kk + (v,)])
                                        if w is None or abs(w["lift"]) < LIFT:
                                            good = False
                                            break
                                    if not good:
                                        continue
                                    # 増分
                                    for v in TRIO:
                                        lmv, ndv, kdv = mm[kk + (v,)]
                                        full = FULL[kk + (v,)]
                                        keep = full & ~BLK[kk + (v,)]
                                        gk3 = gmk[v] & keep
                                        nb = pc(keep)
                                        if pc(gk3) == 0 or nb == 0:
                                            good = False
                                            break
                                        lf2 = pc(lmv & gk3) / pc(gk3) - pc(lmv & keep) / nb
                                        if abs(lf2) < LIFT or pc(lmv & gk3) < MIN_NUM:
                                            good = False
                                            break
                                    if good:
                                        n_all += 1
                                        if want_detail:
                                            hits.append({"disc": d, "binar": bn, "subset": sname,
                                                         "pop": pop, "J": Jx, "s": sx, "mode": md})
        return n_g1, n_all, hits

    mm_true = labs_to_masks(draw(False))
    g1_true, all_true, hits_true = full_search_pass(mm_true, want_detail=True)

    n_run_g1 = n_run_all = 0
    tot_g1 = tot_all = 0
    for _ in range(N_PERM):
        labs = draw(True)
        mm = labs_to_masks(labs)
        a, b, _h = full_search_pass(mm)
        tot_g1 += a
        tot_all += b
        n_run_g1 += 1 if a > 0 else 0
        n_run_all += 1 if b > 0 else 0

    out["t5_permutation"] = {
        "scheme": "y10 を**会社単位で全ビンテージ同時に** sic2 の層内で並べ替える。"
                  "群の定義（特徴量）は不変＝帰無は『候補は結果と無関係』",
        "perm_info": perm_info,
        "a_config_fixed": out_a,
        "b_conditional_independence_of_the_3_vintages": out_b_cond,
        "c_selection_adjusted_whole_search_space": {
            "why": "この配置は**探索で選ばれた**。手続きの値札は『探索空間のどこかに合格が出る確率』。"
                   "探索側は gate1 の値札しか測っていない（union 0.741）",
            "space": {"discs": SPACE_DISCS, "binars": SPACE_BINARS, "pops": SPACE_POPS,
                      "subsets": list(SUBSETS), "J": list(SPACE_JS) + ["len(feats)"],
                      "s": "1..J", "mode": ["ge", "le"]},
            "gates_applied": "gate1（lift ∧ 分子 ∧ 符号不変）＋業種（MH ∧ 1業種抜き）＋増分。"
                             "irr 層は本物でも判定不能なので課さない（課すと値札が甘く出る）",
            "real_data": {"n_pass_gate1": g1_true, "n_pass_all_gates": all_true,
                          "hits": hits_true},
            "null": {"n_perm": N_PERM,
                     "fpr_any_gate1": r4(n_run_g1 / N_PERM),
                     "fpr_any_all_gates": r4(n_run_all / N_PERM),
                     "expected_gate1_passes_per_run": r4(tot_g1 / N_PERM),
                     "expected_all_gate_passes_per_run": r4(tot_all / N_PERM)},
        },
    }

    # ───────── 7 事前登録が角度Dに課している「外側fold」（探索側が測っていない） ─────────
    # prereg pass_line.for_D_and_E:
    #   「加法スコアと木は**外側foldでの性能のみ**を合否に使う。in-sample は参考値として明示」
    # 探索側 out/hist10_angleD.json に交差検証の節は無く、角度E だけが診断で nested_cv を測っている。
    # ここで角度D に**同じ作法**を当てる。fold は**会社単位**（3ビンテージに同じ会社が出るので
    # 行で切ると train と test に同じ会社が入り、fold が漏れる）。
    N_FOLDS = 5
    all_t = sorted({r["ticker"] for v in TRIO for r in U[key + (v,)]})
    cols_c = SUBSETS[key[0]]
    te_mask = {}

    def set_folds(seed_f):
        rnd_f = random.Random(seed_f)
        shuf = list(all_t)
        rnd_f.shuffle(shuf)
        fold_of = {t: i % N_FOLDS for i, t in enumerate(shuf)}
        te_mask.clear()
        for v in TRIO:
            rs = U[key + (v,)]
            mk = [0] * N_FOLDS
            for i, r in enumerate(rs):
                mk[fold_of[r["ticker"]]] |= (1 << i)
            te_mask[v] = mk

    set_folds(SEED)

    def cv_run(mode_name, LMx=None, KDx=None):
        """mode_name:
           'full_research'  = train で列・向き・J・s・mode をすべて選び直す（角度E の作法）
           'fixed_structure'= J=3/s=2/ge/quartile を固定し、**列と向きだけ** train から選び直す
           'fixed_columns'  = 列も向きも報告された配置に固定し、**分位点だけ** train から取る
                              ＝これは正しいOOF検定ではない（列の選択に全データの知識が入っている）。
                                縮みが『列の選択』から来るのか『分位点の雑音』から来るのかを分ける対照
        """
        LMu = LMx if LMx is not None else LM
        KDu = KDx if KDx is not None else KD
        oof = {v: 0 for v in TRIO}
        picks = []
        for f in range(N_FOLDS):
            trD = FULL[key + (disc,)] & ~te_mask[disc][f]
            ntr = pc(trD)
            lm_tr = LMu[key + (disc,)] & trD
            # train だけで各列の向きと |lift| を決める
            smtr = {}
            rsD2 = U[key + (disc,)]
            tr_rows = [rsD2[i] for i in range(len(rsD2)) if (trD >> i) & 1]
            # train 標本の分位点で二値化し直す（cut も train から）
            good_tr = {}
            base_tr = pc(lm_tr) / ntr if ntr else 0.0
            fts = []
            for c in cols_c:
                xs = [r[c] for r in tr_rows]
                q25, q75 = quantile(xs, 0.25), quantile(xs, 0.75)
                hi = lo = 0
                for i, r in enumerate(rsD2):
                    if not ((trD >> i) & 1):
                        continue
                    if r[c] >= q75:
                        hi |= (1 << i)
                    if r[c] <= q25:
                        lo |= (1 << i)
                best = None
                for side, g in (("hi", hi), ("lo", lo)):
                    m = pc(g)
                    if m == 0 or m == ntr:
                        continue
                    lf = pc(lm_tr & g) / m - base_tr
                    if best is None or lf > best[1]:
                        best = (side, lf, g)
                if best is None:
                    continue
                fts.append({"col": c, "side": best[0], "abs_lift": abs(best[1]),
                            "q25": q25, "q75": q75})
            fts.sort(key=lambda x: (-x["abs_lift"], x["col"]))
            if not fts:
                continue
            if mode_name == "fixed_columns":
                order = {f["col"]: f for f in fts}
                fts = []
                for ci, cnm in enumerate(sel):
                    ft = order.get(cnm)
                    if ft is None:
                        continue
                    fts.append({"col": cnm, "side": sides[ci],
                                "abs_lift": ft["abs_lift"], "q25": ft["q25"], "q75": ft["q75"]})
            if mode_name in ("fixed_structure", "fixed_columns"):
                if len(fts) < J:      # train で J 本そろわない fold は使わない（数を水増ししない）
                    continue
                cand_cfg = [(J, s, mode)]
            else:
                Js = sorted({j for j in tuple(SPACE_JS) + (len(fts),) if 1 <= j <= len(fts)})
                cand_cfg = [(Jx, sx, md) for Jx in Js for sx in range(1, Jx + 1)
                            for md in ("ge", "le")]
            min_tr = max(3, int(round(MIN_NUM * ntr / ND[key + (disc,)])))
            best = None
            for (Jx, sx, md) in cand_cfg:
                masks = []
                for ft in fts[:Jx]:
                    g = 0
                    for i, r in enumerate(rsD2):
                        if not ((trD >> i) & 1):
                            continue
                        ok = (r[ft["col"]] >= ft["q75"]) if ft["side"] == "hi" \
                            else (r[ft["col"]] <= ft["q25"])
                        if ok:
                            g |= (1 << i)
                    masks.append(g)
                pl = score_planes(masks, trD)
                _e, ge = exact_and_ge(pl, Jx, trD)
                g = ge[sx] if md == "ge" else (trD & ~(ge[sx + 1] if (sx + 1) in ge else 0))
                g &= trD
                m = pc(g)
                if m < min_tr or m >= ntr:
                    continue
                lf = pc(lm_tr & g) / m - base_tr
                if best is None or abs(lf) > abs(best[0]):
                    best = (lf, Jx, sx, md, [ft["col"] for ft in fts[:Jx]],
                            [ft["side"] for ft in fts[:Jx]],
                            [(ft["q25"], ft["q75"]) for ft in fts[:Jx]])
            if best is None:
                continue
            _lf, Jx, sx, md, selc, selsd, cuts = best
            picks.append({"fold": f, "J": Jx, "s": sx, "mode": md,
                          "cols": selc, "sides": selsd, "train_lift": r4(_lf)})
            # ★ held-out で評価。**cut も向きも train のもの**を当てる（test を一切見ない）
            for v in TRIO:
                rsv = U[key + (v,)]
                tm = te_mask[v][f]
                masks = []
                for ci, cnm in enumerate(selc):
                    g = 0
                    q25, q75 = cuts[ci]
                    for i, r in enumerate(rsv):
                        if not ((tm >> i) & 1):
                            continue
                        ok = (r[cnm] >= q75) if selsd[ci] == "hi" else (r[cnm] <= q25)
                        if ok:
                            g |= (1 << i)
                    masks.append(g)
                pl = score_planes(masks, tm)
                _e, ge = exact_and_ge(pl, Jx, tm)
                gg = ge[sx] if md == "ge" else (tm & ~(ge[sx + 1] if (sx + 1) in ge else 0))
                oof[v] |= (gg & tm)
        res = {}
        for v in TRIO:
            g = oof[v]
            m = pc(g)
            k = pc(LMu[key + (v,)] & g)
            b = KDu[key + (v,)] / ND[key + (v,)]
            res[str(v)] = {"oof_group_n": m, "oof_k": k,
                           "oof_p": r4(k / m) if m else None, "base": r4(b),
                           "oof_lift": r4(k / m - b) if m else None,
                           "min_num_met": k >= MIN_NUM,
                           "line_met": (m > 0 and k >= MIN_NUM and abs(k / m - b) >= LIFT)}
        res["_picks"] = picks
        res["_all_three_vintages_pass"] = all(res[str(v)]["line_met"] for v in TRIO)
        res["_discovery_vintage_only_pass"] = res[str(disc)]["line_met"]
        return res

    cv_full = cv_run("full_research")
    cv_fixed = cv_run("fixed_structure")
    cv_cols = cv_run("fixed_columns")

    # fold の切り方の運で結論が動かないことを確かめる（種を10通り振る）
    seeds_tbl = []
    for sd in range(10):
        set_folds(SEED + 1000 * (sd + 1))
        a = cv_run("full_research")
        b = cv_run("fixed_structure")
        seeds_tbl.append({
            "seed": SEED + 1000 * (sd + 1),
            "full_research": {"lift_3v": [a[str(v)]["oof_lift"] for v in TRIO],
                              "k_3v": [a[str(v)]["oof_k"] for v in TRIO],
                              "pass": a["_all_three_vintages_pass"]},
            "fixed_structure": {"lift_3v": [b[str(v)]["oof_lift"] for v in TRIO],
                                "k_3v": [b[str(v)]["oof_k"] for v in TRIO],
                                "pass": b["_all_three_vintages_pass"]},
        })
    set_folds(SEED)
    # 主 fold（SEED）も合わせた 11 分割の集計＝OOF 性能の正直な点推定
    allsp = [{"full_research": {"lift_3v": [cv_full[str(v)]["oof_lift"] for v in TRIO],
                                "pass": cv_full["_all_three_vintages_pass"]},
              "fixed_structure": {"lift_3v": [cv_fixed[str(v)]["oof_lift"] for v in TRIO],
                                  "pass": cv_fixed["_all_three_vintages_pass"]}}] + seeds_tbl

    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        if not xs:
            return None
        m = len(xs) // 2
        return r4(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2)

    agg = {}
    for nm in ("full_research", "fixed_structure"):
        per_v_lift = {str(TRIO[i]): [x[nm]["lift_3v"][i] for x in allsp] for i in range(3)}
        agg[nm] = {
            "n_splits": len(allsp),
            "median_oof_lift_by_vintage": {k2: med(v2) for k2, v2 in per_v_lift.items()},
            "n_splits_passing_all_3_vintages": sum(1 for x in allsp if x[nm]["pass"]),
            "n_vintage_cells_over_line": sum(1 for x in allsp for l in x[nm]["lift_3v"]
                                             if l is not None and l >= LIFT),
            "n_vintage_cells": 3 * len(allsp),
        }
    seed_summary = {
        "aggregate_over_11_splits_including_main": agg,
        "n_seeds": len(seeds_tbl),
        "full_research_passes": sum(1 for x in seeds_tbl if x["full_research"]["pass"]),
        "fixed_structure_passes": sum(1 for x in seeds_tbl if x["fixed_structure"]["pass"]),
        "fixed_structure_lift_range": [
            r4(min(min(x["fixed_structure"]["lift_3v"]) for x in seeds_tbl)),
            r4(max(max(x["fixed_structure"]["lift_3v"]) for x in seeds_tbl))],
        "fixed_structure_n_vintage_cells_over_line":
            sum(1 for x in seeds_tbl for l in x["fixed_structure"]["lift_3v"] if l >= LIFT),
        "fixed_structure_total_cells": 3 * len(seeds_tbl),
    }

    # 到達可能性: OOF の分子が 20 に届きうるか（届かないなら『判定不能』であって不合格ではない）
    reach = {}
    for v in TRIO:
        reach[str(v)] = {"n": ND[key + (v,)], "k_total": KD[key + (v,)],
                         "in_sample_group_k": per_v[v]["k"],
                         "note": "OOF 群は各 fold の held-out 部分の合併＝おおむね in-sample 群と同じ大きさ"}

    out["t7_outer_fold_required_by_prereg"] = {
        "prereg_clause": prereg["pass_line"]["for_D_and_E"],
        "⚠": "探索側 out/hist10_angleD.json に交差検証の節は無い＝**事前登録が角度Dの合否に使えと"
             "書いている数字が、一度も測られていない**（診断の nested_cv は角度E だけ）",
        "protocol": "fold は**会社単位** 5分割（3ビンテージに同じ会社が出るので行で切ると漏れる）。"
                    "各 fold の train だけで 分位点・向き・列・J・s・mode を決め、held-out でだけ測る。"
                    "5 fold の held-out 群を合併。base は各ビンテージの母集団全体。"
                    "合否は診断の角度E と同じ: 分子>=20 かつ |lift|>=0.15",
        "reachability": reach,
        "cv_full_research": cv_full,
        "cv_fixed_structure": cv_fixed,
        "cv_fixed_columns_CONTROL_not_a_valid_oof_test": cv_cols,
        "in_sample_vs_oof": {
            "in_sample_lift_3v": {str(v): per_v[v]["lift"] for v in TRIO},
            "oof_fixed_structure_3v": {str(v): cv_fixed[str(v)]["oof_lift"] for v in TRIO},
            "shrinkage": {str(v): r4(per_v[v]["lift"] - cv_fixed[str(v)]["oof_lift"])
                          for v in TRIO if cv_fixed[str(v)]["oof_lift"] is not None},
            "control_fixed_columns_3v": {str(v): cv_cols[str(v)]["oof_lift"] for v in TRIO},
            "read": "対照（列も向きも固定＝分位点だけ train）が in-sample 近くに残るなら、"
                    "縮みの出所は**列の選択**であって分位点の雑音ではない",
        },
        "column_selection_stability": {
            "why": "『どの美点を数えるか』が fold ごとに変わるなら、加法スコアは"
                   "『美点の数』ではなく『その標本で効いた列の数』を数えている",
            "reported_columns": sel,
            "picked_per_fold": [{"fold": p["fold"], "cols": p["cols"][:3]}
                                for p in cv_fixed["_picks"]],
            "times_each_reported_column_was_reselected":
                {c: sum(1 for p in cv_fixed["_picks"] if c in p["cols"]) for c in sel},
            "n_folds": N_FOLDS,
        },
        "fold_seed_robustness": {"summary": seed_summary, "by_seed": seeds_tbl},
        "controls": {
            "positive_control": {
                "what": "列も向きも報告された配置に固定し、分位点だけ train から取る",
                "oof_lift_3v": [cv_cols[str(v)]["oof_lift"] for v in TRIO],
                "in_sample_3v": [per_v[v]["lift"] for v in TRIO],
                "read": "外側fold の仕組み自体は、本物の効果を**満額で**掴める。"
                        "つまり不合格は protocol の副作用ではない",
            },
            "negative_control": None,
        },
        "verdict": ("合格" if (cv_full["_all_three_vintages_pass"]
                             or cv_fixed["_all_three_vintages_pass"]) else "不合格"),
        "verdict_full_research": ("合格" if cv_full["_all_three_vintages_pass"] else "不合格"),
        "verdict_fixed_structure": ("合格" if cv_fixed["_all_three_vintages_pass"] else "不合格"),
    }

    # 負の対照: 帰無（会社単位の置換）で同じ外側fold を回す。
    # 仕組みが信号を作っていないこと、と、観測 0.13 が帰無より上か（＝効果は在るが線より小さい）を分ける
    N_NULL_CV = int(os.environ.get("VERIFY_NCV", 200))
    null_lift = {str(v): [] for v in TRIO}
    null_base = {str(v): [] for v in TRIO}
    null_pass = 0
    for _ in range(N_NULL_CV):
        labs = draw(True)
        mmx = labs_to_masks(labs)
        LMx = {k2: mmx[k2][0] for k2 in mmx}
        KDx = {k2: mmx[k2][2] for k2 in mmx}
        for v in TRIO:
            null_base[str(v)].append(KDx[key + (v,)] / ND[key + (v,)])
        rr = cv_run("fixed_structure", LMx, KDx)
        for v in TRIO:
            if rr[str(v)]["oof_lift"] is not None:
                null_lift[str(v)].append(rr[str(v)]["oof_lift"])
        if rr["_all_three_vintages_pass"]:
            null_pass += 1

    def pctl(xs, q):
        ys = sorted(xs)
        return r4(ys[min(int(q * len(ys)), len(ys) - 1)]) if ys else None

    out["t7_outer_fold_required_by_prereg"]["controls"]["negative_control"] = {
        "what": "帰無（会社単位・全ビンテージ同時の置換）で同じ外側fold を %d 回" % N_NULL_CV,
        "null_median_oof_lift": {v: pctl(null_lift[v], 0.5) for v in null_lift},
        "null_p95_oof_lift": {v: pctl(null_lift[v], 0.95) for v in null_lift},
        "observed_oof_lift": {str(v): cv_fixed[str(v)]["oof_lift"] for v in TRIO},
        "p_oof_lift_ge_observed": {
            str(v): r4(sum(1 for x in null_lift[str(v)]
                           if x >= cv_fixed[str(v)]["oof_lift"]) / max(1, len(null_lift[str(v)])))
            for v in TRIO},
        "null_rate_of_passing_all_3_vintages_OOF": r4(null_pass / N_NULL_CV),
        "why_the_null_median_is_not_zero": {
            "measured": "置換は sic2 の**層内**で行うので、業種を通じた関連は帰無でも残る（設計どおり）。"
                        "選択手続きは帰無でも『結果率の高い業種に群を寄せる列』を選べるため、"
                        "OOF lift の帰無中央値は 0 でなく 0.02〜0.04 になる",
            "true_base_by_vintage": {str(v): r4(KD[key + (v,)] / ND[key + (v,)]) for v in TRIO},
            "null_mean_base_by_vintage": {v: r4(sum(x) / len(x)) for v, x in null_base.items()},
            "read": "母集団の base も置換で下がる（P_quality∧complete-case の率が全コホートより高いため）。"
                    "lift は**その置換の base で**測っているので中心はずれていない——"
                    "残る 0.02〜0.04 は『選択が業種構成から取れる分』であって効果ではない",
        },
        "read": "帰無の中央値が0付近で観測が帰無より上なら、**効果は在るが事前登録の線(0.15)より小さい**。"
                "『効果ゼロ』と『線に届かない』は別物なので分けて書く。"
                "ここでは観測 0.13〜0.14 に対し帰無 p95 が 0.13〜0.15＝**帰無の裾とほぼ重なる**",
    }

    # ───────── 事前登録が「合否の前に必ず出せ」と書いている4つ ─────────
    must = {"src": prereg["must_report_before_verdict"]}
    reach2 = {}
    for v in TRIO:
        n = ND[key + (v,)]
        b = KD[key + (v,)] / n
        up_min = math.ceil(MIN_NUM / (b + LIFT)) if (b + LIFT) > 0 else None
        dn_min = math.ceil(MIN_NUM / (b - LIFT)) if (b - LIFT) > 0 else None
        m = per_v[v]["n_group"]
        need_lift = math.ceil(m * (b + LIFT) - 1e-9)
        reach2[str(v)] = {
            "n": n, "base": r4(b),
            "min_group_for_up": up_min, "min_group_for_down": dn_min,
            "up_possible": up_min is not None and up_min <= n,
            "down_possible": dn_min is not None and dn_min <= n,
            "actual_group_n": m,
            "k_needed_by_LIFT": need_lift, "k_needed_by_MIN_NUM": MIN_NUM,
            "which_line_binds": "LIFT" if need_lift >= MIN_NUM else "MIN_NUM",
            "effective_required_lift": r4(max(need_lift, MIN_NUM) / m - b),
            "actual_k": per_v[v]["k"],
        }
    must["reachability_two_way_and_effective_requirement"] = reach2
    # 検出力（単一ビンテージ・二項の厳密計算。3年同時は従属があるので単年だけを出す）
    pw = {}
    for delta in (0.10, 0.15, 0.20):
        cells = {}
        for v in TRIO:
            n = ND[key + (v,)]
            b = KD[key + (v,)] / n
            m = per_v[v]["n_group"]
            need = max(math.ceil(m * (b + LIFT) - 1e-9), MIN_NUM)
            p = min(1.0, b + delta)
            # P(K >= need), K~Bin(m,p)
            tot = 0.0
            for k in range(need, m + 1):
                tot += math.exp(math.lgamma(m + 1) - math.lgamma(k + 1) - math.lgamma(m - k + 1)
                                + k * math.log(p) + (m - k) * math.log(1 - p)) if 0 < p < 1 else 0.0
            cells[str(v)] = r4(tot)
        pw[f"delta={delta}"] = cells
    must["power_single_vintage_exact_binomial"] = {
        "def": "群の大きさを固定し、真の lift が δ のとき『そのビンテージ単独で線を通す』確率",
        "⚠": "3ビンテージ同時の検出力ではない（3年は従属しているので単純な積にならない）。"
             "δ=0.15 で約0.5 になるのは構造（真の効果が線とちょうど等しいと標本は上下に半々に割れる）",
        "cells": pw,
    }
    must["false_positive_rate"] = {
        "config_fixed_statistic_p": out_a["p_one_sided"],
        "config_fixed_gate1_p": out_a["p_gate1_for_this_fixed_config"],
        "selection_adjusted_angle_D_whole_space_gate1_only":
            out["t5_permutation"]["c_selection_adjusted_whole_search_space"]["null"]["fpr_any_gate1"],
        "selection_adjusted_angle_D_whole_space_all_gates":
            out["t5_permutation"]["c_selection_adjusted_whole_search_space"]["null"]["fpr_any_all_gates"],
        "⚠_family_is_larger_than_angle_D": {
            "why": "候補は角度A〜E の5本立ての探索から出た。家族単位の値札は角度Dだけではない",
            "from_out/hist10_diag.json": {
                "angle_A_L4_plus_sector_control": 0.0235,
                "angle_E_nested_cv_cov90_14": 0.034,
                "angle_E_nested_cv_all20": 0.0125,
                "union_across_angles_with_tree_nested_cv": 0.51,
                "note": "診断の union 0.51 は D と E に業種調整が入っていない**上限**。"
                        "この道具が D の全ゲート版を 0.0165 と測ったので、"
                        "A(0.0235)+D(0.0165)+E(<=0.0465) の和は約 0.087＝**5%を超える**。"
                        "しかも角度B（持続）と角度C（分解）の値札は誰も測っていない",
            },
        },
    }
    out["prereg_must_report_before_verdict"] = must

    # ───────── 総括 ─────────
    v1 = out["t1_reproduce"]["verdict"]
    v2 = out["t2_vintage"]["verdict"]
    v3 = out["t3_sector"]["verdict"]
    v4 = out["t4_irr_layer"]["verdict"]
    v6 = out["t6_incremental"]["verdict"]
    fpr_all = out["t5_permutation"]["c_selection_adjusted_whole_search_space"]["null"]["fpr_any_all_gates"]
    v5 = "合格" if (out_a["p_one_sided"] is not None and out_a["p_one_sided"] < 0.05) else "不合格"
    v7 = out["t7_outer_fold_required_by_prereg"]["verdict"]
    out["verdicts"] = {"t1_reproduce": v1, "t2_vintage": v2, "t3_sector": v3,
                       "t4_irr_layer": v4, "t5_permutation_config_fixed": v5,
                       "t6_incremental": v6,
                       "t7_outer_fold(prereg for_D_and_E)": v7,
                       "t5c_selection_adjusted_fpr": fpr_all}
    six = ["t1_reproduce", "t2_vintage", "t3_sector", "t4_irr_layer",
           "t5_permutation_config_fixed", "t6_incremental"]
    fails6 = [k for k in six if out["verdicts"][k] not in ("合格", "一致")]
    cvf = out["t7_outer_fold_required_by_prereg"]
    out["final"] = {
        "the_six_assigned_tests": {k: out["verdicts"][k] for k in six},
        "six_all_passed": len(fails6) == 0,
        "six_failed": fails6,
        "⚠_honest_statement":
            "**割り当てられた6検問では落とせなかった**。落ちたのは7本目——"
            "事前登録 pass_line.for_D_and_E が『加法スコアと木は外側foldでの性能のみを合否に使う』と"
            "書いているのに、探索側 out/hist10_angleD.json に交差検証の節が一つも無く、"
            "その要求された数字が一度も測られていなかった。ここで測ったら線を割った",
        "t7_outer_fold": {
            "verdict": cvf["verdict"],
            "median_oof_lift_over_11_splits":
                cvf["fold_seed_robustness"]["summary"]["aggregate_over_11_splits_including_main"],
            "in_sample_vs_oof": cvf["in_sample_vs_oof"]["shrinkage"],
            "control_says_shrinkage_is_from_column_selection":
                cvf["in_sample_vs_oof"]["control_fixed_columns_3v"],
            "column_reselection_counts":
                cvf["column_selection_stability"]["times_each_reported_column_was_reselected"],
            "positive_control_oof": cvf["controls"]["positive_control"]["oof_lift_3v"],
            "negative_control": {
                "null_median": cvf["controls"]["negative_control"]["null_median_oof_lift"],
                "null_p95": cvf["controls"]["negative_control"]["null_p95_oof_lift"],
                "observed": cvf["controls"]["negative_control"]["observed_oof_lift"],
                "p": cvf["controls"]["negative_control"]["p_oof_lift_ge_observed"],
                "read": "観測の OOF lift は3ビンテージとも**帰無の p95 を下回る**"
                        "（p=0.06〜0.07）＝線に届かないだけでなく、帰無と区別も付いていない",
            },
        },
        "verdict": ("不合格（事前登録の for_D_and_E＝外側fold を満たさない）"
                    if cvf["verdict"] != "合格" and len(fails6) == 0
                    else ("不合格" if fails6 else "落とせなかった")),
        "selection_adjusted_fpr_of_angle_D_whole_procedure": fpr_all,
    }

    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"verdicts": out["verdicts"], "final": out["final"]},
                     ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    main()
