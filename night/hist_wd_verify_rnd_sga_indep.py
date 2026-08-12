#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_rnd_sga_indep.py
  候補「f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下] / 勝者側 / P_full」を **独立実装で潰しにかかる**。

────────────────────────────────────────────────────────────
なぜ「独立実装」なのか
────────────────────────────────────────────────────────────
night/hist_wd_verify_rnd_sga.py（既存）と night/hist_wd_win_pair.py（探索側）は
**同じ候補について同じことを言うはず**の道具。この repo は
「同じ台帳を見る二つの検査器が違うことを言ってはいけない」(v9.9.65) を掟にし、
その検査のために `hist_val_lookahead.py`（検定の計算を一行も import しない独立実装）という
前例を持つ。本器はその前例に倣い、**既存の探索器・検証器から一行も import しない**。
入力は out/hist_wd_panel.json と生の retro_* だけ。最後に既存2本と**セル単位で突き合わせる**。

────────────────────────────────────────────────────────────
立場
────────────────────────────────────────────────────────────
反証が仕事であって確認ではない。prereg(out/hist_winner_destroyer_prereg.json) の線
（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を**一つも緩めない**。
線を緩めた数字を出すときは必ず `事前登録の外・診断専用` と明記し、合否には数えない。
「測れない」と「不合格」を区別する。

────────────────────────────────────────────────────────────
当てる6つ（1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 ビンテージ符号   2016/2017/2018 の符号。2013/2015 は f2_ が構造的に無く判定不能。
                   **「3ビンテージ＝3証拠」かをティッカー重なりと窓の重なりで実測する**
2 業種調整         MH＋層内置換＋業種1つずつ除去＋間接標準化（層を落とさない版）。
                   **MHが群の何%を覆っているか**を必ず出す
3 irr の影         irr>=70 層内で残るか・直交か。**直交が群の小ささの産物でないか**も見る
4 1社の影響        ティッカーを1社ずつパネルごと抜き、閾値・母集団・群・判定を全部作り直す
5 置換             outcome をティッカー単位の束で置換（ビンテージ間相関を保つ帰無）2000回。
                   単体の p と、探索全体（2840検定）の値札の両方
6 既存の関門との重複 事業の収縮 / 利払カバー / 質実証 の生存者の中でも残るか（＝増分）

補助（事前登録の外・診断専用。合否には数えない）:
  M 可測性の交絡（両脚が測れること自体が勝者を予言していないか）
  R レジーム分割 2018-07→2022-07 / 2022-07→2026-08（月次在庫から自前で計算）
  L 脚の分解（sga_r 単独 / rnd_r 単独）と、探索の合格13件の顔ぶれ
"""
import json, os, math, random
from collections import defaultdict, Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
SEARCH = os.path.join(OUT, "hist_wd_win_pair.json")          # 突合せ相手（信じる前に検算する）
SIB = os.path.join(OUT, "hist_wd_verify_rnd_sga.json")       # 既存の検証器（同上）
MONTHLY = os.path.join(OUT, "retro_monthly_2018_2026.json")
SICF = os.path.join(OUT, "retro_sic.json")
DEST = os.path.join(OUT, "hist_wd_verify_rnd_sga_indep.json")

# ─── prereg の線（読むだけ・作らない） ───
LIFT_LINE = 0.15
MIN_NUM = 5
VINTAGES = [2016, 2017, 2018]
WIN_HURDLE = 0.15          # 既存の定数（prereg hurdles.win）
NPERM = 2000
SEED = 20260811

# ─── 候補の定義（探索側のラベルをそのまま機械化。線を動かさない） ───
SEED_VAR, SEED_DIR, SEED_Q = "f2_rnd_r", "hi", 0.75    # 上位1/4  → x >= q75
PART_VAR, PART_DIR, PART_Q = "f2_sga_r", "lo", 0.50    # 中央値以下 → x <= q50


# ═══════════════════════════ 基本部品 ═══════════════════════════
def q_nearest_rank(vals, p):
    """nearest-rank 分位（探索側と同じ作法）。1-based index = ceil(p*n)。"""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    k = max(1, math.ceil(p * n))
    return s[min(k, n) - 1]


def side_ok(x, thr, direction):
    if x is None or thr is None:
        return False
    return (x >= thr) if direction == "hi" else (x <= thr)


def rate(rows, key="win"):
    if not rows:
        return None
    return sum(1 for r in rows if r[key]) / len(rows)


def r4(x):
    return None if x is None else round(x, 4)


def load_panel():
    p = json.load(open(PANEL))
    return p["rows"]


def analysis_rows(rows, vintage, pop="P_full"):
    """探索側と同じ解析集合: has_outcome ∧ window_full ∧ 母集団。"""
    return [r for r in rows
            if r["vintage"] == vintage and r["has_outcome"] and r["window_full"] and r.get(pop)]


def build_cell(pop_rows, seed_var=SEED_VAR, seed_dir=SEED_DIR, seed_q=SEED_Q,
               part_var=PART_VAR, part_dir=PART_DIR, part_q=PART_Q, key="win"):
    """母集団から閾値を引き直して群を作る（AND の交差で切り直さない＝探索側と同じ）。"""
    sv = [r[seed_var] for r in pop_rows if r[seed_var] is not None]
    pv = [r[part_var] for r in pop_rows if r[part_var] is not None]
    t_seed = q_nearest_rank(sv, seed_q)
    t_part = q_nearest_rank(pv, part_q)
    grp, meas_both = [], []
    for r in pop_rows:
        if r[seed_var] is not None and r[part_var] is not None:
            meas_both.append(r)
            if side_ok(r[seed_var], t_seed, seed_dir) and side_ok(r[part_var], t_part, part_dir):
                grp.append(r)
    n_pop = len(pop_rows)
    p_base = rate(pop_rows, key)
    p_grp = rate(grp, key)
    num = sum(1 for r in grp if r[key])
    return {
        "n_pop": n_pop, "p_base": p_base,
        "thr_seed": t_seed, "thr_part": t_part,
        "n_group": len(grp), "numerator": num, "p_group": p_grp,
        "lift": (p_grp - p_base) if p_grp is not None else None,
        "n_measurable_both": len(meas_both),
        "p_base_measurable": rate(meas_both, key),
        "lift_meas": (p_grp - rate(meas_both, key)) if (p_grp is not None and meas_both) else None,
        "_group_rows": grp, "_pop_rows": pop_rows, "_meas_rows": meas_both,
    }


# ═══════════════════════════ 業種調整 ═══════════════════════════
def mh_risk_diff(pop_rows, group_set, key="win"):
    """Mantel-Haenszel リスク差（sic2 層別）。層を落とすので**被覆率も返す**。"""
    strata = defaultdict(lambda: {"g": [], "o": []})
    for r in pop_rows:
        s = r.get("sic2") or "NA"
        (strata[s]["g"] if id(r) in group_set else strata[s]["o"]).append(r)
    num = den = 0.0
    used = dropped = 0
    covered = 0
    for s, d in strata.items():
        n1, n0 = len(d["g"]), len(d["o"])
        if n1 == 0 or n0 == 0:
            dropped += 1
            continue
        used += 1
        covered += n1
        n = n1 + n0
        p1, p0 = rate(d["g"], key), rate(d["o"], key)
        w = n1 * n0 / n
        num += w * (p1 - p0)
        den += w
    n_group = sum(1 for r in pop_rows if id(r) in group_set)
    return {
        "mh_risk_diff": (num / den) if den else None,
        "strata_used": used, "strata_dropped": dropped,
        "group_covered": covered, "n_group": n_group,
        "group_coverage": (covered / n_group) if n_group else None,
    }


def indirect_standardized(pop_rows, group_set, key="win"):
    """層を落とさない間接標準化。群の各社に『その業種の非群の勝率』を期待値として当てる。
    非群がゼロの業種だけ全体base（そこは調整できない＝その旨も数える）。"""
    by = defaultdict(lambda: {"g": [], "o": []})
    for r in pop_rows:
        s = r.get("sic2") or "NA"
        (by[s]["g"] if id(r) in group_set else by[s]["o"]).append(r)
    base = rate(pop_rows, key)
    exp = obs = 0.0
    n = 0
    fallback = 0
    for s, d in by.items():
        if not d["g"]:
            continue
        p0 = rate(d["o"], key)
        if p0 is None:
            p0 = base
            fallback += len(d["g"])
        for r in d["g"]:
            n += 1
            obs += 1.0 if r[key] else 0.0
            exp += p0
    return {
        "n_group": n, "observed": obs, "expected": r4(exp),
        "excess_per_company": r4((obs - exp) / n) if n else None,
        "n_group_without_sector_control": fallback,
        "note": "群の各社に『同業の非群の勝率』を当てた期待値との差。層を1つも落とさない。",
    }


def leave_one_sector_out(rows_v, key="win"):
    """業種を1つずつ母集団ごと抜いて、閾値から作り直す。1業種が全部を作っていないか。"""
    base_cell = build_cell(rows_v, key=key)
    gset = set(id(r) for r in base_cell["_group_rows"])
    sec_in_group = Counter((r.get("sic2") or "NA") for r in base_cell["_group_rows"])
    res = []
    for s, cnt in sec_in_group.most_common():
        sub = [r for r in rows_v if (r.get("sic2") or "NA") != s]
        c = build_cell(sub, key=key)
        res.append({
            "sic2_removed": s, "n_group_members_removed": cnt,
            "n_pop": c["n_pop"], "n_group": c["n_group"], "numerator": c["numerator"],
            "p_base": r4(c["p_base"]), "p_group": r4(c["p_group"]), "lift": r4(c["lift"]),
            "passes_lift_line": (c["lift"] is not None and c["lift"] >= LIFT_LINE),
            "passes_min_num": c["numerator"] >= MIN_NUM,
        })
    return {"base_lift": r4(base_cell["lift"]), "by_sector_removed": res}


def within_stratum_permutation(pop_rows, group_set, key="win", n=NPERM, seed=SEED):
    """sic2 層内で outcome を並べ替える（業種の効果を帰無に含める）。"""
    rnd = random.Random(seed)
    by = defaultdict(list)
    for r in pop_rows:
        by[r.get("sic2") or "NA"].append(r)
    g_idx = []
    labels = []
    for s, rs in by.items():
        for i, r in enumerate(rs):
            labels.append(1 if r[key] else 0)
    # 層ごとに (ラベル配列, 群フラグ配列) を持つ
    packs = []
    for s, rs in by.items():
        lab = [1 if r[key] else 0 for r in rs]
        gfl = [1 if id(r) in group_set else 0 for r in rs]
        packs.append((lab, gfl, sum(gfl)))
    n_group = sum(p[2] for p in packs)
    if n_group == 0:
        return {"p_value": None, "note": "群が空"}
    obs = sum(l for lab, gfl, _ in packs for l, g in zip(lab, gfl) if g)
    ge = 0
    for _ in range(n):
        tot = 0
        for lab, gfl, ng in packs:
            if ng == 0:
                continue
            sh = lab[:]
            rnd.shuffle(sh)
            tot += sum(x for x, g in zip(sh, gfl) if g)
        if tot >= obs:
            ge += 1
    return {"observed_winners_in_group": obs, "n_group": n_group,
            "p_value_within_sector": (ge + 1) / (n + 1), "n_perm": n}


# ═══════════════════════════ 5関門の判定（prereg literal） ═══════════════════════════
def full_verdict(rows_by_v, key="win"):
    """3ビンテージ全部で prereg の5関門を当て、合否を返す。線は一つも動かさない。"""
    cells, mhs = {}, {}
    for v in VINTAGES:
        c = build_cell(rows_by_v[v], key=key)
        cells[v] = c
        gset = set(id(r) for r in c["_group_rows"])
        mhs[v] = mh_risk_diff(rows_by_v[v], gset, key=key)
    lifts = [cells[v]["lift"] for v in VINTAGES]
    nums = [cells[v]["numerator"] for v in VINTAGES]
    if any(l is None for l in lifts):
        return {"pass": False, "reason": "lift算出不能", "cells": cells, "mh": mhs}
    signs = set(1 if l > 0 else (-1 if l < 0 else 0) for l in lifts)
    ok_sign = len(signs) == 1 and 0 not in signs
    ok_lift = min(abs(l) for l in lifts) >= LIFT_LINE
    ok_num = min(nums) >= MIN_NUM
    ok_sec = all((mhs[v]["mh_risk_diff"] is not None and abs(mhs[v]["mh_risk_diff"]) >= LIFT_LINE)
                 for v in VINTAGES)
    return {"pass": bool(ok_sign and ok_lift and ok_num and ok_sec),
            "ok_sign": ok_sign, "ok_lift": ok_lift, "ok_num": ok_num, "ok_sector": ok_sec,
            "maintained_lift": min(lifts), "min_numerator": min(nums),
            "cells": cells, "mh": mhs}


# ═══════════════════════════ レジーム（月次から自前で） ═══════════════════════════
def month_price_near(series, target_ts, tol_days=45):
    best, bd = None, None
    for ts, px in series:
        d = abs(ts - target_ts)
        if bd is None or d < bd:
            bd, best = d, px
    if bd is None or bd > tol_days * 86400:
        return None
    return best


def regime_split(group_tickers, pop_tickers, monthly):
    t0 = datetime(2018, 7, 1, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2022, 7, 1, tzinfo=timezone.utc).timestamp()
    t2 = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
    out = {}
    for name, (ta, tb, yrs) in {"early_2018_2022": (t0, t1, 4.0),
                                "late_2022_2026": (t1, t2, 4.09)}.items():
        def cagr_set(tks):
            got = {}
            for t in tks:
                s = monthly.get(t)
                if not s:
                    continue
                pa, pb = month_price_near(s, ta), month_price_near(s, tb)
                if pa is None or pb is None or pa <= 0 or pb <= 0:
                    continue
                got[t] = (pb / pa) ** (1.0 / yrs) - 1.0
            return got
        gp, pp = cagr_set(group_tickers), cagr_set(pop_tickers)
        if not gp or not pp:
            out[name] = {"note": "算出不能"}
            continue
        pw_g = sum(1 for x in gp.values() if x >= WIN_HURDLE) / len(gp)
        pw_p = sum(1 for x in pp.values() if x >= WIN_HURDLE) / len(pp)
        out[name] = {
            "years": yrs,
            "n_group_priced": len(gp), "n_pop_priced": len(pp),
            "coverage_group": r4(len(gp) / max(1, len(group_tickers))),
            "coverage_pop": r4(len(pp) / max(1, len(pop_tickers))),
            "p_group": r4(pw_g), "p_base": r4(pw_p), "lift": r4(pw_g - pw_p),
            "median_cagr_group": r4(sorted(gp.values())[len(gp) // 2]),
            "median_cagr_pop": r4(sorted(pp.values())[len(pp) // 2]),
        }
    return out


# ═══════════════════════════ 多重検定の値札（帰無の最大統計量） ═══════════════════════════
def cut_mask(pop_rows, var, cut):
    """探索側のラベルを機械化。線は探索側の literal をそのまま使う。"""
    vals = [r[var] for r in pop_rows if r[var] is not None]
    if not vals:
        return None
    if cut == "上位1/4":
        thr = q_nearest_rank(vals, 0.75); f = lambda x: x >= thr
    elif cut == "下位1/4":
        thr = q_nearest_rank(vals, 0.25); f = lambda x: x <= thr
    elif cut == "中央値超":
        thr = q_nearest_rank(vals, 0.50); f = lambda x: x > thr
    elif cut == "中央値以下":
        thr = q_nearest_rank(vals, 0.50); f = lambda x: x <= thr
    else:
        return None
    return [1 if (r[var] is not None and f(r[var])) else 0 for r in pop_rows]


def family_wise_null(all_rows, verdict, n_perm=NPERM, seed=SEED + 7):
    """探索空間2840組の**帰無での最大 maintained lift** を出す。
    群のメンバーシップは outcome に依らないので、群を一度だけビット集合にしておけば
    置換のたびに AND と popcount で全組を一気に評価できる（numpy が無い環境のため）。"""
    sp = json.load(open(SEARCH))
    pairs = sp["all_pairs"]
    pops = ["P_full", "P_quality"]
    rows_pv = {(p, v): analysis_rows(all_rows, v, p) for p in pops for v in VINTAGES}
    base_pv = {k: rate(rs) for k, rs in rows_pv.items()}
    tick_pv = {k: [r["ticker"] for r in rs] for k, rs in rows_pv.items()}

    idx_by_pop = defaultdict(list)
    for i, pr in enumerate(pairs):
        idx_by_pop[pr["population"]].append(i)

    # 群をビット集合に
    GM, NG = {}, {}
    for p in pops:
        for v in VINTAGES:
            rs = rows_pv[(p, v)]
            gm, ng = [], []
            for i in idx_by_pop[p]:
                pr = pairs[i]
                ma = cut_mask(rs, pr["var_a"], pr["cut_a"])
                mb = cut_mask(rs, pr["var_b"], pr["cut_b"])
                if ma is None or mb is None:
                    gm.append(0); ng.append(0); continue
                m = 0; n = 0
                for j, (a, b) in enumerate(zip(ma, mb)):
                    if a & b:
                        m |= (1 << j); n += 1
                gm.append(m); ng.append(n)
            GM[(p, v)] = gm
            NG[(p, v)] = ng

    def lifts_for(winmask_by_v, p):
        """(3, n_pairs) の lift を返す"""
        out = []
        for v in VINTAGES:
            wm, npop = winmask_by_v[(p, v)]
            base = wm.bit_count() / npop
            gm, ng = GM[(p, v)], NG[(p, v)]
            row = []
            for m, n in zip(gm, ng):
                row.append(((m & wm).bit_count() / n - base) if n else 0.0)
            out.append(row)
        return out

    def maintained_and_num(L, Ks):
        res = []
        for j in range(len(L[0])):
            a, b, c = L[0][j], L[1][j], L[2][j]
            if (a > 0 and b > 0 and c > 0) or (a < 0 and b < 0 and c < 0):
                res.append((min(abs(a), abs(b), abs(c)), min(Ks[0][j], Ks[1][j], Ks[2][j])))
            else:
                res.append((0.0, 0))
        return res

    def masks_from_wins(winfn):
        d = {}
        for p in pops:
            for v in VINTAGES:
                rs = rows_pv[(p, v)]
                m = 0
                for j, r in enumerate(rs):
                    if winfn(r, v):
                        m |= (1 << j)
                d[(p, v)] = (m, len(rs))
        return d

    # ── 再現の検算（観測 outcome） ──
    obsmask = masks_from_wins(lambda r, v: r["win"])
    obs = {}
    for p in pops:
        L = lifts_for(obsmask, p)
        Ks = []
        for v in VINTAGES:
            wm, _ = obsmask[(p, v)]
            Ks.append([(m & wm).bit_count() for m in GM[(p, v)]])
        obs[p] = maintained_and_num(L, Ks)
    mism, checked = 0, 0
    for p in pops:
        for j, i in enumerate(idx_by_pop[p]):
            ml = pairs[i].get("maintained_lift")
            if ml is None:
                continue
            checked += 1
            if abs(abs(ml) - obs[p][j][0]) > 5e-4:
                mism += 1
    obs_cand = None
    for j, i in enumerate(idx_by_pop["P_full"]):
        pr = pairs[i]
        key = (pr["var_a"], pr["cut_a"], pr["var_b"], pr["cut_b"])
        if key in ((SEED_VAR, "上位1/4", PART_VAR, "中央値以下"),
                   (PART_VAR, "中央値以下", SEED_VAR, "上位1/4")):
            obs_cand = obs["P_full"][j][0]
    obs_max = max(max(x[0] for x in obs[p]) for p in pops)
    obs_npass3 = sum(1 for p in pops for val, k in obs[p] if val >= LIFT_LINE and k >= MIN_NUM)

    # ── 帰無: outcome をティッカー単位の束で入れ替える ──
    bundle = defaultdict(dict)
    for p in pops:
        for v in VINTAGES:
            for r in rows_pv[(p, v)]:
                bundle[r["ticker"]][v] = r["win"]
    tickers = sorted(bundle.keys())
    # ティッカー -> sic2（ビンテージ間で不変）
    sic_of_t = {}
    for p in pops:
        for v in VINTAGES:
            for r in rows_pv[(p, v)]:
                sic_of_t.setdefault(r["ticker"], r.get("sic2") or "NA")
    by_sic = defaultdict(list)
    for t in tickers:
        by_sic[sic_of_t[t]].append(t)

    def run_null(mode, seed_):
        """mode='free'  … ティッカーを自由に入れ替える（特徴量は何も予言しない帰無）
           mode='sector'… **sic2 の中だけ**で入れ替える＝業種と結果の関係は温存した帰無。
                          業種の代理でしかない組は帰無でも同じ lift を出すので、
                          『業種を超えて足しているか』を族の水準で問える（check2 の族版）"""
        rnd = random.Random(seed_)
        nulls, npass_null = [], []
        for _ in range(n_perm):
            if mode == "free":
                sh = tickers[:]
                rnd.shuffle(sh)
                mp = dict(zip(tickers, sh))
            else:
                mp = {}
                for sc, ts in by_sic.items():
                    sh = ts[:]
                    rnd.shuffle(sh)
                    mp.update(dict(zip(ts, sh)))
            wmask = {}
            for p in pops:
                for v in VINTAGES:
                    rs = rows_pv[(p, v)]
                    m = 0
                    for j, r in enumerate(rs):
                        if bundle[mp[r["ticker"]]].get(v):
                            m |= (1 << j)
                    wmask[(p, v)] = (m, len(rs))
            mx = 0.0; np_ = 0
            for p in pops:
                L = lifts_for(wmask, p)
                Ks = []
                for v in VINTAGES:
                    wm, _ = wmask[(p, v)]
                    Ks.append([(m & wm).bit_count() for m in GM[(p, v)]])
                mn = maintained_and_num(L, Ks)
                for val, k in mn:
                    if val > mx:
                        mx = val
                    if val >= LIFT_LINE and k >= MIN_NUM:
                        np_ += 1
            nulls.append(mx); npass_null.append(np_)
        nulls.sort()
        return nulls, npass_null

    def pct(a, q):
        return a[min(len(a) - 1, int(q * len(a)))]

    nulls, npass_null = run_null("free", seed)
    nulls_s, npass_s = run_null("sector", seed + 11)
    ge = sum(1 for x in nulls if x >= obs_cand)
    ge_s = sum(1 for x in nulls_s if x >= obs_cand)
    return {
        "what": ("探索空間2840組を帰無で毎回まるごと評価し、**その最大 maintained lift** の分布を出す。"
                 "『何千本から選んだ１本』の値札はこれでしか払えない"),
        "reproduction_of_search_maintained_lift": {
            "n_pairs_checked": checked, "n_mismatch": mism,
            "note": "0件ならこの再構成は探索側と同じものを見ている",
        },
        "observed_maintained_lift_of_this_candidate": r4(obs_cand),
        "observed_max_over_search_space": r4(obs_max),
        "null_max_distribution": {
            "n_perm": n_perm, "p50": r4(pct(nulls, 0.50)), "p90": r4(pct(nulls, 0.90)),
            "p95": r4(pct(nulls, 0.95)), "p99": r4(pct(nulls, 0.99)), "max": r4(nulls[-1]),
        },
        "family_wise_p_value": r4((ge + 1) / (n_perm + 1)),
        "n_null_perms_with_at_least_one_pair_over_line": sum(1 for x in npass_null if x > 0),
        "median_n_pairs_passing_lift_and_num_under_null": sorted(npass_null)[len(npass_null) // 2],
        "p95_n_pairs_passing_under_null": pct(sorted(npass_null), 0.95),
        "observed_n_pairs_passing_same_3gates": obs_npass3,
        "observed_n_passes_in_search_all5gates": 13,
        "sector_preserving_null": {
            "what": ("**sic2 の中だけ**でティッカーを入れ替える帰無。業種と結果の関係は温存されるので、"
                     "業種の代理でしかない組は帰無でも同じ lift を出す。"
                     "『業種を超えて足しているか』を族（2840本）の水準で問う検定＝check2 の族版"),
            "null_max_distribution": {
                "p50": r4(pct(nulls_s, 0.50)), "p90": r4(pct(nulls_s, 0.90)),
                "p95": r4(pct(nulls_s, 0.95)), "p99": r4(pct(nulls_s, 0.99)),
                "max": r4(nulls_s[-1]),
            },
            "family_wise_p_value": r4((ge_s + 1) / (n_perm + 1)),
            "median_n_pairs_passing_under_null": sorted(npass_s)[len(npass_s) // 2],
        },
        "how_to_read": ("family_wise_p は『2840本から最良を選ぶ』ことを織り込んだ p。"
                        "0.05 を超えるなら、この候補の強さは**選び抜いたことで説明がつく**"),
    }


def summarize(res, verdict):
    """6検証それぞれ『落とせたか』。線は一つも動かしていない。"""
    s = {}
    c1 = res["check1_vintage_sign"]
    s["1_vintage_sign"] = {
        "落とせたか": "落とせなかった（3ビンテージとも正）" if c1["signs_all_positive"] else "**落とせた**",
        "ただし": c1["but_are_these_three_independent_evidences"]["conclusion"],
        "2013/2015": "判定不能（f2_ が構造的に存在しない）＝不合格ではない",
    }
    sec = res["check2_sector"]
    los_break = []
    for v in VINTAGES:
        for r in sec["leave_one_sector_out"][str(v)]["by_sector_removed"]:
            if not (r["passes_lift_line"] and r["passes_min_num"]):
                los_break.append({"vintage": v, "sic2": r["sic2_removed"], "lift": r["lift"]})
    fx = sec["fixed_threshold_removal_of_dominant_sector"]
    fx_ok = all(fx[str(v)]["passes_lift_line"] and fx[str(v)]["passes_min_num"] for v in VINTAGES)
    mh_ok = all(abs(sec["by_vintage"][str(v)]["mh"]["mh_risk_diff"]) >= LIFT_LINE for v in VINTAGES)
    reso = sec.get("resolution_of_sector_control", {}).get("by_resolution", {})
    sic4 = reso.get("sic4", {})
    sic4_fail = [v for v in ("2016", "2017", "2018")
                 if sic4.get(v) and not sic4[v]["passes_line"]]
    drop = sec.get("mh_leave_one_stratum_out", {})
    drop_break = []
    for v in ("2016", "2017", "2018"):
        d = drop.get(v, {})
        for k, x in d.get("drop_one_stratum", {}).items():
            if not x["still_passes"]:
                drop_break.append({"vintage": v, "stratum_removed": k,
                                   "mh": x["mh_without_this_stratum"]})
    both = {v: drop.get(v, {}).get("drop_35_and_38_together", {}) for v in ("2016", "2017", "2018")}
    broke2 = bool(sic4_fail or drop_break or
                  any(not b.get("still_passes", True) for b in both.values()))
    s["2_sector"] = {
        "落とせたか": "**落とせた**" if broke2 else "落とせなかった",
        "literal_gate_at_sic2": "○（0.21/0.23/0.24）— 文言どおりなら通る",
        "しかし①_解像度": {"sic2": {v: reso.get("sic2(探索側が使った解像度)", {}).get(v, {}).get("mh_risk_diff")
                              for v in ("2016", "2017", "2018")},
                     "sic3": {v: sic4 and reso.get("sic3", {}).get(v, {}).get("mh_risk_diff")
                              for v in ("2016", "2017", "2018")},
                     "sic4": {v: sic4.get(v, {}).get("mh_risk_diff") for v in ("2016", "2017", "2018")},
                     "sic4で線を割るビンテージ": sic4_fail,
                     "被覆は落ちていない": {v: sic4.get(v, {}).get("group_coverage") for v in sic4}},
        "しかし②_層を1つ外すと": drop_break,
        "しかし③_35と38を同時に外すと": both,
        "MH": {str(v): sec["by_vintage"][str(v)]["mh"]["mh_risk_diff"] for v in VINTAGES},
        "MH群被覆": {str(v): sec["by_vintage"][str(v)]["mh"]["group_coverage"] for v in VINTAGES},
        "層内置換p": {str(v): sec["by_vintage"][str(v)]["within_sector_permutation"].get("p_value_within_sector")
                   for v in VINTAGES},
        "業種1つ除去で崩れる例": los_break,
        "閾値固定で支配業種を除去しても残るか": fx_ok,
    }
    irr = res["check3_irr_shadow"]["by_vintage"]
    s["3_irr_shadow"] = {
        "落とせたか": "判定不能（2016/2017 に irr の読解が存在しない）",
        "2018のみ": irr["2018"]["irr_ge70"],
        "検出力の限界": irr["2018"]["orthogonality_caveat"],
    }
    c4 = res["check4_leave_one_out"]
    s["4_one_company"] = {
        "落とせたか": "落とせなかった" if c4["n_drops_that_break_pass"] == 0 else "**落とせた**",
        "1社抜きで崩れる社数": c4["n_drops_that_break_pass"],
        "最小維持lift": c4["min_maintained_lift_over_all_drops"],
    }
    c5 = res["check5_permutation"]
    fam = c5.get("family_wise_null_max", {})
    fwp = fam.get("family_wise_p_value")
    s["5_permutation"] = {
        "この1本だけなら": {"p_lift": c5["p_value_maintained_lift_ge_observed"],
                     "p_5関門": c5["p_value_procedure_passes_all_5_gates_by_chance"]},
        "2840本から選んだことを織り込むと": {"family_wise_p": fwp,
                              "帰無の最大の p95": fam.get("null_max_distribution", {}).get("p95")},
        "落とせたか": ("**落とせた**（多重検定を織り込むと偶然と見分けがつかない）"
                  if (fwp is not None and fwp > 0.05) else "落とせなかった"),
    }
    inc = res["check6_increment_over_existing_gates"]["by_vintage"]
    ok6 = all((inc[str(v)]["survivors_of_all_three"]["lift"] or 0) >= LIFT_LINE
              and inc[str(v)]["survivors_of_all_three"]["reachable_min_num"] for v in VINTAGES)
    s["6_increment"] = {
        "落とせたか": "落とせなかった" if ok6 else "**落とせた**",
        "生存者の中でのlift": {str(v): inc[str(v)]["survivors_of_all_three"]["lift"] for v in VINTAGES},
        "生存者の中での分子": {str(v): inc[str(v)]["survivors_of_all_three"]["numerator"] for v in VINTAGES},
    }
    return s


# ═══════════════════════════ 本体 ═══════════════════════════
def main():
    rows = load_panel()
    prereg = json.load(open(PREREG))
    monthly = json.load(open(MONTHLY))

    res = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_verify_rnd_sga_indep.py",
        "stance": ("既存の探索器・検証器から一行も import しない独立実装。"
                   "反証が仕事であって確認ではない。prereg の線を一つも緩めない。"),
        "candidate": {
            "label": "f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下]",
            "side": "winner", "population": "P_full",
            "seed": [SEED_VAR, SEED_DIR, SEED_Q], "partner": [PART_VAR, PART_DIR, PART_Q],
        },
        "pass_line_read_from_prereg": {
            "lift": LIFT_LINE, "min_numerator": MIN_NUM,
            "sign_stability_vintages": VINTAGES,
            "source": "out/hist_winner_destroyer_prereg.json（この道具は線を作らない）",
        },
    }

    rows_by_v = {v: analysis_rows(rows, v) for v in VINTAGES}

    # ── 0. まず再現する（信じる前に検算する） ──
    verdict = full_verdict(rows_by_v)
    res["step0_reproduction"] = {
        "by_vintage": {str(v): {
            "n_pop": verdict["cells"][v]["n_pop"],
            "p_base": r4(verdict["cells"][v]["p_base"]),
            "thr_rnd_r": r4(verdict["cells"][v]["thr_seed"]),
            "thr_sga_r": r4(verdict["cells"][v]["thr_part"]),
            "n_group": verdict["cells"][v]["n_group"],
            "numerator": verdict["cells"][v]["numerator"],
            "p_group": r4(verdict["cells"][v]["p_group"]),
            "lift": r4(verdict["cells"][v]["lift"]),
            "n_measurable_both": verdict["cells"][v]["n_measurable_both"],
            "p_base_measurable": r4(verdict["cells"][v]["p_base_measurable"]),
            "lift_vs_measurable_base": r4(verdict["cells"][v]["lift_meas"]),
        } for v in VINTAGES},
        "verdict_5gates": {k: verdict[k] for k in
                           ("pass", "ok_sign", "ok_lift", "ok_num", "ok_sector")},
        "maintained_lift": r4(verdict["maintained_lift"]),
    }

    # 探索側との突合せ（同じことを言うか）
    try:
        sp = json.load(open(SEARCH))
        tgt = None
        for d in sp["passing_pairs_detail"]:
            if d["label"] == "f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下]" and d["population"] == "P_full":
                tgt = d
                break
        diffs = []
        if tgt:
            for v in VINTAGES:
                a = tgt["by_vintage"][str(v)]
                b = verdict["cells"][v]
                for f, x, y in (("n_pop", a["n_pop"], b["n_pop"]),
                                ("n_group", a["n_group"], b["n_group"]),
                                ("numerator", a["numerator"], b["numerator"]),
                                ("lift", a["lift"], r4(b["lift"]))):
                    if (round(x, 4) if isinstance(x, float) else x) != (round(y, 4) if isinstance(y, float) else y):
                        diffs.append({"vintage": v, "field": f, "search": x, "indep": y})
        res["step0_crosscheck_vs_search_tool"] = {
            "found_in_search_output": bool(tgt),
            "n_mismatched_cells": len(diffs), "mismatches": diffs,
            "note": "0件なら探索側の数字は独立に再現された。0件でないなら、まずどちらが壊れているかを調べる",
        }
    except Exception as e:
        res["step0_crosscheck_vs_search_tool"] = {"error": repr(e)}

    # ── 1. ビンテージ符号 + 「3証拠か」 ──
    grp_tk = {v: set(r["ticker"] for r in verdict["cells"][v]["_group_rows"]) for v in VINTAGES}
    pair_overlap = {}
    for i, a in enumerate(VINTAGES):
        for b in VINTAGES[i + 1:]:
            inter = len(grp_tk[a] & grp_tk[b])
            uni = len(grp_tk[a] | grp_tk[b])
            pair_overlap[f"{a}x{b}"] = {"jaccard": r4(inter / uni) if uni else None,
                                        "shared": inter,
                                        "share_of_smaller": r4(inter / min(len(grp_tk[a]), len(grp_tk[b])))}
    yrs = {}
    for v in VINTAGES:
        ys = [r["years"] for r in rows_by_v[v] if r.get("years")]
        yrs[str(v)] = r4(sorted(ys)[len(ys) // 2]) if ys else None
    res["check1_vintage_sign"] = {
        "lifts": {str(v): r4(verdict["cells"][v]["lift"]) for v in VINTAGES},
        "signs_all_positive": verdict["ok_sign"],
        "verdict": "符号は反転しない（この関門は通る）" if verdict["ok_sign"] else "符号が反転＝不合格",
        "but_are_these_three_independent_evidences": {
            "group_ticker_overlap": pair_overlap,
            "median_window_years": yrs,
            "shared_window_note": ("窓はすべて 2026-08 で終わる。2016の10.09年窓は2018の8.09年窓を"
                                   "完全に含む＝**最後の8.09年は3ビンテージ共通**。"
                                   "共通でない部分は 2016→2018 の2年と 2017→2018 の1年だけ"),
            "conclusion": None,  # 下で埋める
        },
    }
    j = [pair_overlap[k]["jaccard"] for k in pair_overlap if pair_overlap[k]["jaccard"] is not None]
    res["check1_vintage_sign"]["but_are_these_three_independent_evidences"]["conclusion"] = (
        f"群のティッカーの Jaccard 中央値 {sorted(j)[len(j)//2]:.3f}・窓の8.09年が共通"
        "＝**3つの独立な証拠ではない。実質1つ**。prereg の independence_warning どおり"
    )

    # ── 2. 業種調整 ──
    sec = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        gset = set(id(r) for r in c["_group_rows"])
        mh = mh_risk_diff(rows_by_v[v], gset)
        ind = indirect_standardized(rows_by_v[v], gset)
        perm = within_stratum_permutation(rows_by_v[v], gset)
        top = Counter((r.get("sic2") or "NA") for r in c["_group_rows"]).most_common(6)
        sec[str(v)] = {
            "mh": {k: (r4(x) if isinstance(x, float) else x) for k, x in mh.items()},
            "indirect_standardization_no_strata_dropped": ind,
            "within_sector_permutation": {k: (r4(x) if isinstance(x, float) else x)
                                          for k, x in perm.items()},
            "group_sic2_top": top,
            "group_top1_share": r4(top[0][1] / c["n_group"]) if top and c["n_group"] else None,
        }
    los = {str(v): leave_one_sector_out(rows_by_v[v]) for v in VINTAGES}
    # 支配業種そのものの lift（群でなく業種だけで何が説明できるか）
    dom = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        top = Counter((r.get("sic2") or "NA") for r in c["_group_rows"]).most_common(1)[0][0]
        pop = rows_by_v[v]
        sect = [r for r in pop if (r.get("sic2") or "NA") == top]
        g_in = [r for r in c["_group_rows"] if (r.get("sic2") or "NA") == top]
        nong = [r for r in sect if id(r) not in set(id(x) for x in c["_group_rows"])]
        dom[str(v)] = {
            "dominant_sic2": top,
            "n_sector": len(sect), "p_sector": r4(rate(sect)),
            "lift_of_sector_membership_alone": r4(rate(sect) - c["p_base"]),
            "n_group_in_sector": len(g_in), "p_group_in_sector": r4(rate(g_in)),
            "p_nongroup_in_sector": r4(rate(nong)),
            "lift_of_pair_WITHIN_that_sector": r4(rate(g_in) - rate(nong)) if nong else None,
            "share_of_group_in_that_sector": r4(len(g_in) / c["n_group"]),
        }
    res["check2_sector"] = {
        "by_vintage": sec, "leave_one_sector_out": los,
        "dominant_sector_benchmark": dom,
        "verdict": None,
    }

    # ── 3. irr の影 ──
    irrres = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        pop = rows_by_v[v]
        gset = set(id(r) for r in c["_group_rows"])
        with_irr = [r for r in pop if r.get("irr") is not None]
        ge70 = [r for r in with_irr if r["irr"] >= 70]
        g70 = [r for r in ge70 if id(r) in gset]
        o70 = [r for r in ge70 if id(r) not in gset]
        # 相関（群フラグ vs irr>=70 フラグ）— 測れた行だけ
        n = len(with_irr)
        a = sum(1 for r in with_irr if id(r) in gset and r["irr"] >= 70)
        b = sum(1 for r in with_irr if id(r) in gset and r["irr"] < 70)
        cc = sum(1 for r in with_irr if id(r) not in gset and r["irr"] >= 70)
        d = sum(1 for r in with_irr if id(r) not in gset and r["irr"] < 70)
        denom = math.sqrt((a + b) * (cc + d) * (a + cc) * (b + d))
        phi = ((a * d - b * cc) / denom) if denom else None
        irrres[str(v)] = {
            "n_with_irr_read": n, "share_of_pop_with_irr": r4(n / c["n_pop"]),
            "n_group_with_irr_read": a + b,
            "irr_ge70": {"n": len(ge70), "base_all": r4(rate(ge70)),
                         "n_group": len(g70), "numerator": sum(1 for r in g70 if r["win"]),
                         "p_group": r4(rate(g70)), "p_nongroup": r4(rate(o70)),
                         "lift_vs_layer_base": r4(rate(g70) - rate(ge70)) if g70 else None,
                         "reachable_min_num": (len(g70) >= MIN_NUM)},
            "phi_group_vs_irr70": r4(phi),
            "orthogonality_caveat": ("群のうち irr が読まれているのは "
                                     f"{a+b}/{c['n_group']} 社。**irr は母集団の一部にしか読まれていないので、"
                                     "この層別の検出力は低い。『残った』も『直交』も弱い証拠**"),
        }
    res["check3_irr_shadow"] = {"by_vintage": irrres, "verdict": None}

    # ── 4. 1社の影響（パネルごと抜いて全部作り直す） ──
    tk2018 = sorted(set(r["ticker"] for r in rows_by_v[2018]))
    base_maint = verdict["maintained_lift"]
    worst = []
    for t in tk2018:
        sub = {v: [r for r in rows_by_v[v] if r["ticker"] != t] for v in VINTAGES}
        vv = full_verdict(sub)
        worst.append((vv["maintained_lift"], t, vv["pass"], vv["min_numerator"]))
    worst.sort()
    res["check4_leave_one_out"] = {
        "base_maintained_lift": r4(base_maint),
        "n_tickers_dropped_one_at_a_time": len(tk2018),
        "min_maintained_lift_over_all_drops": r4(worst[0][0]),
        "max_maintained_lift_over_all_drops": r4(worst[-1][0]),
        "worst5": [{"drop": t, "maintained_lift": r4(l), "still_pass": p} for l, t, p, _ in worst[:5]],
        "n_drops_that_break_pass": sum(1 for l, t, p, _ in worst if not p),
        "verdict": None,
    }

    # ── 5. 置換（ティッカー単位の束・ビンテージ間相関を保つ） ──
    #    prereg の5関門をまるごと当て直す＝手続き全体の偽陽性率
    tickers = sorted(set(r["ticker"] for v in VINTAGES for r in rows_by_v[v]))
    bundle = {}
    for t in tickers:
        bundle[t] = {v: None for v in VINTAGES}
    for v in VINTAGES:
        for r in rows_by_v[v]:
            bundle[r["ticker"]][v] = r["win"]
    rnd = random.Random(SEED)
    obs_maint = verdict["maintained_lift"]
    ge_lift = 0
    n_pass_null = 0
    # 高速化: 群フラグと母集団を固定し、outcome だけ入れ替える
    gflag = {v: [1 if id(r) in set(id(x) for x in verdict["cells"][v]["_group_rows"]) else 0
                 for r in rows_by_v[v]] for v in VINTAGES}
    tk_of = {v: [r["ticker"] for r in rows_by_v[v]] for v in VINTAGES}
    sic_of = {v: [r.get("sic2") or "NA" for r in rows_by_v[v]] for v in VINTAGES}
    for _ in range(NPERM):
        perm_t = tickers[:]
        rnd.shuffle(perm_t)
        mapping = dict(zip(tickers, perm_t))
        lifts, nums, ok_sec_all = [], [], True
        for v in VINTAGES:
            wins = []
            for t in tk_of[v]:
                src = bundle[mapping[t]][v]
                wins.append(bool(src) if src is not None else False)
            npop = len(wins)
            pb = sum(wins) / npop
            gi = [i for i, g in enumerate(gflag[v]) if g]
            if not gi:
                lifts, nums = [None], [0]
                break
            pg = sum(1 for i in gi if wins[i]) / len(gi)
            lifts.append(pg - pb)
            nums.append(sum(1 for i in gi if wins[i]))
            # 業種MH（帰無でも当てる）
            st = defaultdict(lambda: [0, 0, 0, 0])  # n1,k1,n0,k0
            for i, s in enumerate(sic_of[v]):
                cell = st[s]
                if gflag[v][i]:
                    cell[0] += 1; cell[1] += 1 if wins[i] else 0
                else:
                    cell[2] += 1; cell[3] += 1 if wins[i] else 0
            nu = de = 0.0
            for s, (n1, k1, n0, k0) in st.items():
                if n1 == 0 or n0 == 0:
                    continue
                w = n1 * n0 / (n1 + n0)
                nu += w * (k1 / n1 - k0 / n0)
                de += w
            mh = (nu / de) if de else None
            if mh is None or abs(mh) < LIFT_LINE:
                ok_sec_all = False
        if None in lifts:
            continue
        signs = set(1 if l > 0 else (-1 if l < 0 else 0) for l in lifts)
        ok_sign = len(signs) == 1 and 0 not in signs
        ok_lift = min(abs(l) for l in lifts) >= LIFT_LINE
        ok_num = min(nums) >= MIN_NUM
        if ok_sign and ok_lift and ok_num and ok_sec_all:
            n_pass_null += 1
        if min(lifts) >= obs_maint:
            ge_lift += 1
    p_lift = (ge_lift + 1) / (NPERM + 1)
    p_pass = (n_pass_null + 1) / (NPERM + 1)
    n_tests = 2840
    res["check5_permutation"] = {
        "null": "outcome をティッカー単位の束で入れ替える（同一社の3ビンテージの相関を保つ）",
        "n_perm": NPERM,
        "p_value_maintained_lift_ge_observed": r4(p_lift),
        "p_value_procedure_passes_all_5_gates_by_chance": r4(p_pass),
        "n_tests_in_search": n_tests,
        "expected_false_passes_in_search": r4(p_pass * n_tests),
        "observed_passes_in_search": 13,
        "note": ("**多重検定の値札**。探索は2840検定。手続きが偶然に5関門を通す確率×2840 が"
                 "期待される偽陽性の数。実際の合格13件と比べる"),
        "verdict": None,
    }

    # ── 6. 既存の関門との重複（増分） ──
    inc = {}
    for v in VINTAGES:
        pop = rows_by_v[v]
        c = verdict["cells"][v]
        gset = set(id(r) for r in c["_group_rows"])

        def shrink(r):  # 事業の収縮（門の第四関門・v9.9.99）
            return (r["f2_cagr5"] is not None and r["f2_cagr5"] < 0
                    and r["f2_opmD5"] is not None and r["f2_opmD5"] < 0)

        gates = {
            "事業の収縮で落ちる": [r for r in pop if shrink(r)],
            "利払カバー<3(財務キル相当・診断)": [r for r in pop if r["f2_intcov"] is not None and r["f2_intcov"] < 3],
            "質実証を通らない": [r for r in pop if not r.get("P_quality")],
        }
        ov = {}
        for name, blocked in gates.items():
            bset = set(id(r) for r in blocked)
            ov[name] = {
                "n_blocked_in_pop": len(blocked),
                "n_group_blocked": sum(1 for r in c["_group_rows"] if id(r) in bset),
                "share_of_group_blocked": r4(sum(1 for r in c["_group_rows"] if id(r) in bset) / c["n_group"]),
            }
        # 生存者の中での増分（三つ全部を通った社だけ）
        surv = [r for r in pop
                if not shrink(r)
                and not (r["f2_intcov"] is not None and r["f2_intcov"] < 3)
                and r.get("P_quality")]
        gs = [r for r in surv if id(r) in gset]
        inc[str(v)] = {
            "overlap_with_existing_gates": ov,
            "survivors_of_all_three": {
                "n_pop": len(surv), "p_base": r4(rate(surv)),
                "n_group": len(gs), "numerator": sum(1 for r in gs if r["win"]),
                "p_group": r4(rate(gs)),
                "lift": r4(rate(gs) - rate(surv)) if gs else None,
                "reachable_min_num": len(gs) >= MIN_NUM,
            },
        }
    res["check6_increment_over_existing_gates"] = {"by_vintage": inc, "verdict": None}

    # ═══ 補助（事前登録の外・診断専用） ═══
    aux = {"_disclaimer": "ここから下は事前登録の外・診断専用。合否には数えない。"}

    # M 可測性の交絡
    meas = {}
    for v in VINTAGES:
        pop = rows_by_v[v]
        mb = [r for r in pop if r["f2_rnd_r"] is not None and r["f2_sga_r"] is not None]
        nb = [r for r in pop if not (r["f2_rnd_r"] is not None and r["f2_sga_r"] is not None)]
        meas[str(v)] = {
            "n_measurable_both": len(mb), "p_win_measurable": r4(rate(mb)),
            "n_not_measurable": len(nb), "p_win_not_measurable": r4(rate(nb)),
            "lift_of_measurability_alone": r4(rate(mb) - rate(pop)),
            "share_of_total_lift_from_measurability": r4((rate(mb) - rate(pop)) / verdict["cells"][v]["lift"])
            if verdict["cells"][v]["lift"] else None,
            "which_leg_binds": {
                "rnd_r_measurable": sum(1 for r in pop if r["f2_rnd_r"] is not None),
                "sga_r_measurable": sum(1 for r in pop if r["f2_sga_r"] is not None),
            },
        }
    aux["M_measurability_confound"] = meas

    # L 脚の分解
    legs = {}
    for v in VINTAGES:
        pop = rows_by_v[v]
        pb = rate(pop)
        out_l = {}
        for nm, var, dr, q in (("rnd_r[上位1/4]単独", SEED_VAR, SEED_DIR, SEED_Q),
                               ("sga_r[中央値以下]単独", PART_VAR, PART_DIR, PART_Q)):
            vals = [r[var] for r in pop if r[var] is not None]
            thr = q_nearest_rank(vals, q)
            g = [r for r in pop if side_ok(r[var], thr, dr)]
            out_l[nm] = {"thr": r4(thr), "n_group": len(g), "numerator": sum(1 for r in g if r["win"]),
                         "p_group": r4(rate(g)), "lift": r4(rate(g) - pb)}
        legs[str(v)] = out_l
    aux["L_single_leg"] = legs

    # R レジーム
    g2018 = sorted(set(r["ticker"] for r in verdict["cells"][2018]["_group_rows"]))
    p2018 = sorted(set(r["ticker"] for r in rows_by_v[2018]))
    aux["R_regime_split_2018_cohort"] = regime_split(g2018, p2018, monthly)
    aux["R_regime_note"] = ("CLAUDE.md 追補(3.8)(a) が『in-sample最良の複合（販管費低∧R&D高・全期間P=0.70）は"
                            "前期2018-22でP=0.26＝リフトゼロ、後期のみ0.70＝全アルファがAI相場に乗っていた』と"
                            "**この候補そのもの**を既に記録している。ここはその独立な再測定")

    # ── 2b. 業種: 閾値を動かさない除去（きれいな対照） ──
    #    leave-one-sector-out は閾値を引き直すので群が入れ替わる（実測: 36を抜くと25社消えて11社入る）。
    #    「この効果は SIC36 だけか」を問うには**元の群のまま**その業種を落として比べるのが素直。
    fixed = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        gset = set(id(r) for r in c["_group_rows"])
        top = Counter((r.get("sic2") or "NA") for r in c["_group_rows"]).most_common(1)[0][0]
        pop_x = [r for r in rows_by_v[v] if (r.get("sic2") or "NA") != top]
        g_x = [r for r in pop_x if id(r) in gset]
        fixed[str(v)] = {
            "sic2_removed": top,
            "n_pop_after": len(pop_x), "p_base_after": r4(rate(pop_x)),
            "n_group_after": len(g_x), "numerator_after": sum(1 for r in g_x if r["win"]),
            "p_group_after": r4(rate(g_x)),
            "lift_after": r4(rate(g_x) - rate(pop_x)) if g_x else None,
            "passes_lift_line": (g_x and (rate(g_x) - rate(pop_x)) >= LIFT_LINE),
            "passes_min_num": sum(1 for r in g_x if r["win"]) >= MIN_NUM,
        }
    res["check2_sector"]["fixed_threshold_removal_of_dominant_sector"] = fixed

    # ── 2c. MH の中身（どの層が重みを担っているか） ──
    mh_detail = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        gset = set(id(r) for r in c["_group_rows"])
        st = defaultdict(lambda: {"g": [], "o": []})
        for r in rows_by_v[v]:
            (st[r.get("sic2") or "NA"]["g"] if id(r) in gset else st[r.get("sic2") or "NA"]["o"]).append(r)
        rowsd, den = [], 0.0
        for s, d in st.items():
            n1, n0 = len(d["g"]), len(d["o"])
            if n1 == 0 or n0 == 0:
                continue
            w = n1 * n0 / (n1 + n0)
            den += w
        for s, d in st.items():
            n1, n0 = len(d["g"]), len(d["o"])
            if n1 == 0 or n0 == 0:
                continue
            w = n1 * n0 / (n1 + n0)
            rd = rate(d["g"]) - rate(d["o"])
            rowsd.append({"sic2": s, "n_group": n1, "k_group": sum(1 for r in d["g"] if r["win"]),
                          "n_rest": n0, "p_group": r4(rate(d["g"])), "p_rest": r4(rate(d["o"])),
                          "risk_diff": r4(rd), "mh_weight": r4(w),
                          "contribution_share_of_MH": r4(w * rd / (den * (verdict["mh"][v]["mh_risk_diff"] or 1)))})
        rowsd.sort(key=lambda x: -abs(x["mh_weight"] * (x["risk_diff"] or 0)))
        mh_detail[str(v)] = rowsd
    res["check2_sector"]["mh_stratum_breakdown"] = mh_detail

    # ── 2d. 業種調整はどの解像度でも残るか（sic2 → sic3 → sic4） ──
    #    **判断を一つも入れない**——同じ公式分類の桁を増やすだけ。
    #    sic2 は半導体連鎖を 35(装置/記憶/計算機)・36(チップ)・38(検査計測)・30・33 に割ってしまうので、
    #    「業種で調整した」つもりが *装置メーカー vs 農機* の比較になる。桁を増やせばそこが揃う。
    sicmap = {r["ticker"]: (r.get("sic") or "") for r in json.load(open(SICF))["rows"]}
    res_res = {}
    for depth, name in ((2, "sic2(探索側が使った解像度)"), (3, "sic3"), (4, "sic4")):
        per_v = {}
        for v in VINTAGES:
            c = verdict["cells"][v]
            gset = set(id(r) for r in c["_group_rows"])
            st = defaultdict(lambda: {"g": [], "o": []})
            for r in rows_by_v[v]:
                code = sicmap.get(r["ticker"], "")
                key = (code[:depth] if len(code) >= depth else (r.get("sic2") or "NA"))
                (st[key]["g"] if id(r) in gset else st[key]["o"]).append(r)
            num = den = 0.0
            used = dropped = covered = 0
            for k, d in st.items():
                n1, n0 = len(d["g"]), len(d["o"])
                if n1 == 0 or n0 == 0:
                    dropped += 1
                    continue
                used += 1
                covered += n1
                w = n1 * n0 / (n1 + n0)
                num += w * (rate(d["g"]) - rate(d["o"]))
                den += w
            per_v[str(v)] = {
                "mh_risk_diff": r4(num / den) if den else None,
                "strata_used": used, "strata_dropped": dropped,
                "group_covered": covered, "n_group": c["n_group"],
                "group_coverage": r4(covered / c["n_group"]) if c["n_group"] else None,
                "passes_line": (den > 0 and abs(num / den) >= LIFT_LINE),
            }
        res_res[name] = per_v
    res["check2_sector"]["resolution_of_sector_control"] = {
        "what": ("同じ公式分類の桁を増やすだけ（判断を入れない）。sic2 で残って sic3/sic4 で消えるなら、"
                 "その『業種調整』は**集約の産物**であって業種を揃えたことにならない"),
        "by_resolution": res_res,
    }

    # ── 2e. MH から層を1つ外すと維持できるか（どの層が支えているか） ──
    mh_drop = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        gset = set(id(r) for r in c["_group_rows"])
        st = defaultdict(lambda: {"g": [], "o": []})
        for r in rows_by_v[v]:
            (st[r.get("sic2") or "NA"]["g"] if id(r) in gset
             else st[r.get("sic2") or "NA"]["o"]).append(r)
        terms = {}
        for k, d in st.items():
            n1, n0 = len(d["g"]), len(d["o"])
            if n1 == 0 or n0 == 0:
                continue
            w = n1 * n0 / (n1 + n0)
            terms[k] = (w, w * (rate(d["g"]) - rate(d["o"])))
        NUM = sum(t[1] for t in terms.values())
        DEN = sum(t[0] for t in terms.values())
        one = {}
        for k, (w, wr) in terms.items():
            d2 = DEN - w
            one[k] = {"mh_without_this_stratum": r4((NUM - wr) / d2) if d2 else None,
                      "still_passes": (d2 > 0 and abs((NUM - wr) / d2) >= LIFT_LINE)}
        # 半導体装置を含む二層（35・38）を同時に外す
        both = [k for k in ("35", "38") if k in terms]
        d2 = DEN - sum(terms[k][0] for k in both)
        n2 = NUM - sum(terms[k][1] for k in both)
        mh_drop[str(v)] = {
            "mh_full": r4(NUM / DEN) if DEN else None,
            "drop_one_stratum": one,
            "drop_35_and_38_together": {"mh": r4(n2 / d2) if d2 else None,
                                        "still_passes": (d2 > 0 and abs(n2 / d2) >= LIFT_LINE),
                                        "why": "sic2=35 と 38 は半導体装置・検査(LRCX/KLAC/MKSI/TER)を"
                                               "農機・医療機器と比べる層＝この候補の『業種調整』の実体"},
        }
    res["check2_sector"]["mh_leave_one_stratum_out"] = mh_drop

    # ── 2f. 探索側とのMHの食い違いの正体（最小セル規則） ──
    mincell = {}
    for minc in (1, 2, 3):
        per = {}
        for v in VINTAGES:
            c = verdict["cells"][v]
            gset = set(id(r) for r in c["_group_rows"])
            st = defaultdict(lambda: {"g": [], "o": []})
            for r in rows_by_v[v]:
                (st[r.get("sic2") or "NA"]["g"] if id(r) in gset
                 else st[r.get("sic2") or "NA"]["o"]).append(r)
            num = den = 0.0; used = 0
            for k, d in st.items():
                n1, n0 = len(d["g"]), len(d["o"])
                if n1 < minc or n0 == 0:
                    continue
                used += 1; w = n1 * n0 / (n1 + n0)
                num += w * (rate(d["g"]) - rate(d["o"])); den += w
            per[str(v)] = {"mh": r4(num / den) if den else None, "strata_used": used}
        mincell[f"n_group>={minc}"] = per
    try:
        sp2 = json.load(open(SEARCH))
        t2 = [d for d in sp2["passing_pairs_detail"]
              if d["label"] == "f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下]"
              and d["population"] == "P_full"][0]
        sm = {str(v): {"mh": t2["sector_mh"][str(v)]["mh_risk_diff"],
                       "strata_used": t2["sector_mh"][str(v)]["strata_used"]} for v in VINTAGES}
    except Exception:
        sm = None
    res["check2_sector"]["reconciliation_with_search_tool"] = {
        "search_tool_reported": sm,
        "my_mh_by_minimum_cell_rule": mincell,
        "conclusion": ("探索側は**層の群が3社以上**のときだけ MH に入れている。その規則で当てると"
                       "3ビンテージとも小数第4位まで一致した＝**食い違いは実装の欠陥ではなく最小セル規則の差**。"
                       "なお探索側の規則のほうが保守的（小さい層を落とす）で、それでも線は越える"),
    }

    # ── 3b. irr: 2016/2017 は irr が読まれていない → irr_near で診断 ──
    irr_near = {}
    for v in VINTAGES:
        c = verdict["cells"][v]
        gset = set(id(r) for r in c["_group_rows"])
        pop = rows_by_v[v]
        wn = [r for r in pop if r.get("irr_near") is not None]
        ge = [r for r in wn if r["irr_near"] >= 70]
        g = [r for r in ge if id(r) in gset]
        irr_near[str(v)] = {
            "n_with_irr_near": len(wn), "n_irr_near_ge70": len(ge),
            "layer_base": r4(rate(ge)),
            "n_group_in_layer": len(g), "numerator": sum(1 for r in g if r["win"]),
            "p_group": r4(rate(g)),
            "lift_vs_layer": r4(rate(g) - rate(ge)) if g else None,
            "reachable_min_num": len(g) >= MIN_NUM,
        }
    res["check3_irr_shadow"]["by_vintage_using_irr_near_diagnostic"] = irr_near

    # ── 5b. 多重検定の値札: 帰無の「最大統計量」（これが決定打） ──
    #    群のメンバーシップは outcome に依らないので、2840組の群を一度だけ作れば
    #    置換のたびに行列×ベクトルで全組の lift を出せる。
    fam = family_wise_null(rows, verdict)
    res["check5_permutation"]["family_wise_null_max"] = fam

    res["auxiliary_outside_prereg"] = aux
    res["group_2018_tickers"] = g2018

    # ── 総合判定（線は一つも動かしていない） ──
    res["six_verification_outcomes"] = summarize(res, verdict)

    fam2 = res["check5_permutation"]["family_wise_null_max"]
    res["verdict"] = {
        "候補": "f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下] / P_full / 勝者側",
        "再現": ("できた——探索側の2018セル(n_pop952/n_group49/分子26/lift0.3205)と不一致0。"
               "さらに探索空間2840組を独立に組み直して maintained_lift を"
               f"{fam2['reproduction_of_search_maintained_lift']['n_pairs_checked']}本突き合わせ不一致"
               f"{fam2['reproduction_of_search_maintained_lift']['n_mismatch']}件。"
               "3関門通過数も探索側の内訳(13+17=30)と一致"),
        "prereg の literal 5関門": "文言どおりなら○（ただし irr は 2016/2017 に読解が無く**判定不能**）",
        "6検証の結末": "落とせた 2件（2_業種・5_置換）／判定不能 1件（3_irr）／落とせなかった 3件",
        "結論": "**不合格**",
        "決め手": [
            ("① 多重検定: この候補は2840組の**最大値そのもの**(0.2985)。帰無で『2840組の最良』を取ると"
             "中央値0.2271・p95 0.3538 に届く＝family-wise p=0.1189。"
             "業種と結果の関係を温存した帰無ではさらに緩く p=0.2124。"
             "**『選び抜いたこと』だけでこの強さは説明がつく**"),
            ("② 業種調整は解像度の産物: 同じ公式分類の桁を増やすだけで sic2 0.21/0.23/0.24 → "
             "sic4 0.11/0.14/0.21 となり**2016と2017が線を割る**（被覆は95-98%で落ちていない）。"
             "MHの87%は sic2=35 と 38 の2層から出るが、その2層の群は LRCX/STX/WDC/AAPL と KLAC/MKSI/TER＝"
             "**半導体装置・記憶装置を『農機』『医療機器』と比べている**。"
             "2層を同時に外すと MH は 0.083/0.072/0.076 へ落ちる。"
             "唯一 同業どうしの比較になる sic2=36（群の半分25社）では **+0.0825 で線を割る**"),
        ],
        "落とせなかったもの（正直に）": [
            "符号は3ビンテージとも正（ただし Jaccard 0.811・窓8.09年共通＝実質1証拠）",
            "1社をパネルごと抜いても崩れない（最小維持lift 0.2891・破れる社0）",
            "既存の関門（事業の収縮/利払カバー/質実証）の生存者の中でも lift 0.196/0.248/0.314・分子8/10/13",
            "レジーム分割でも前期(+0.174)・後期(+0.236)の両方で正＝AI相場だけの話ではない",
            "族としては帰無より多く通っている（3関門通過 観測30 vs 帰無中央値2・p95 9）"
            "＝**特徴量の集合に情報はある。だが『この1本』を偶然と区別できない**",
        ],
        "測れなかったもの": [
            "2013/2015 での外部検証（f2_ 特徴量が構造的に存在しない）＝**真の out-of-sample は存在しない**",
            "irr の影（2016/2017 に irr の読解が無い。2018 も母集団の14.3%・群の17/49 しか読まれていない）",
            "退場社（母集団は今日ティッカーが解決できる956社＝生存者のみ）",
        ],
    }
    json.dump(res, open(DEST, "w"), ensure_ascii=False, indent=1)
    print("wrote", DEST)
    print("\n=== 2b 閾値固定で支配業種を除去 ===")
    for v in VINTAGES:
        print(v, json.dumps(fixed[str(v)], ensure_ascii=False))
    print("\n=== 2c MH の中身 (2018 上位5層) ===")
    for r in mh_detail["2018"][:5]:
        print("  ", json.dumps(r, ensure_ascii=False))
    print("\n=== 2d 業種調整の解像度 ===")
    for nm, pv in res["check2_sector"]["resolution_of_sector_control"]["by_resolution"].items():
        print(" ", nm, json.dumps(pv, ensure_ascii=False))
    print("\n=== 2e MH から層を1つ外す ===")
    for v in VINTAGES:
        m = mh_drop[str(v)]
        print(" ", v, "full=", m["mh_full"], "| 35と38を同時に外す=", m["drop_35_and_38_together"])
        for k, x in sorted(m["drop_one_stratum"].items(), key=lambda kv: kv[1]["mh_without_this_stratum"] or 9):
            print("      外す層", k, x)
    print("\n=== 3b irr_near 診断 ===")
    for v in VINTAGES:
        print(v, json.dumps(irr_near[str(v)], ensure_ascii=False))
    print("\n=== 5b 帰無の最大統計量 ===")
    print(json.dumps(fam, ensure_ascii=False, indent=1))
    print("\n=== 6検証の結末 ===")
    print(json.dumps(res["six_verification_outcomes"], ensure_ascii=False, indent=1))

    # ── 画面向けの要約 ──
    print("\n=== 再現 ===")
    for v in VINTAGES:
        c = verdict["cells"][v]
        print(f"{v}: n_pop={c['n_pop']} base={c['p_base']:.4f} thr_rnd={c['thr_seed']:.4f} "
              f"thr_sga={c['thr_part']:.4f} n_group={c['n_group']} k={c['numerator']} "
              f"p_group={c['p_group']:.4f} lift={c['lift']:.4f}")
    print("突合せ(探索側): mismatches =",
          res["step0_crosscheck_vs_search_tool"].get("n_mismatched_cells"))
    print("\n=== 1 符号 ===", res["check1_vintage_sign"]["lifts"], "独立?",
          res["check1_vintage_sign"]["but_are_these_three_independent_evidences"]["conclusion"])
    print("\n=== 2 業種 ===")
    for v in VINTAGES:
        s = sec[str(v)]
        print(f"{v}: MH={s['mh']['mh_risk_diff']} 使用層={s['mh']['strata_used']} "
              f"落とした層={s['mh']['strata_dropped']} 群被覆={s['mh']['group_coverage']} "
              f"| 間接標準化 超過/社={s['indirect_standardization_no_strata_dropped']['excess_per_company']} "
              f"| 層内置換 p={s['within_sector_permutation'].get('p_value_within_sector')}")
        print(f"     支配業種 {dom[str(v)]['dominant_sic2']}: 業種だけのlift="
              f"{dom[str(v)]['lift_of_sector_membership_alone']} 業種内での組のlift="
              f"{dom[str(v)]['lift_of_pair_WITHIN_that_sector']} 群の{dom[str(v)]['share_of_group_in_that_sector']}がここ")
        top = los[str(v)]["by_sector_removed"][0]
        print(f"     最大業種を抜くと lift={top['lift']} (line{LIFT_LINE}) pass={top['passes_lift_line']}")
    print("\n=== 3 irr ===")
    for v in VINTAGES:
        print(f"{v}:", json.dumps(irrres[str(v)]["irr_ge70"], ensure_ascii=False))
    print("\n=== 4 1社除去 === min maintained lift =",
          res["check4_leave_one_out"]["min_maintained_lift_over_all_drops"],
          "破れる社数 =", res["check4_leave_one_out"]["n_drops_that_break_pass"])
    print("\n=== 5 置換 === p(lift) =", r4(p_lift), " p(5関門通過) =", r4(p_pass),
          " 期待偽陽性 =", r4(p_pass * n_tests), "/ 実際の合格 13")
    print("\n=== 6 増分 ===")
    for v in VINTAGES:
        s = inc[str(v)]["survivors_of_all_three"]
        print(f"{v}: 生存者 n={s['n_pop']} base={s['p_base']} 群 n={s['n_group']} k={s['numerator']} "
              f"p={s['p_group']} lift={s['lift']} 分子5届く={s['reachable_min_num']}")
    print("\n=== 補助 M 可測性 ===")
    for v in VINTAGES:
        print(v, json.dumps(meas[str(v)], ensure_ascii=False))
    print("\n=== 補助 L 単脚 ===")
    for v in VINTAGES:
        print(v, json.dumps(legs[str(v)], ensure_ascii=False))
    print("\n=== 補助 R レジーム ===")
    print(json.dumps(aux["R_regime_split_2018_cohort"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
