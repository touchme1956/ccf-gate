#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_aturn_rnd.py
  候補「f2_aturn[中央値超] ∧ f2_rnd_r[上位1/4] / 勝者側 / P_quality」を **潰しにかかる**。

────────────────────────────────────────────────────────────
立場
────────────────────────────────────────────────────────────
反証が仕事であって確認ではない。prereg(out/hist_winner_destroyer_prereg.json) の線
（lift>=0.15 ∧ 分子>=5 ∧ 3ビンテージ符号不変 ∧ 業種調整 ∧ irr非影）を**一つも緩めない**。
線を緩めた数字を出すときは必ず `事前登録の外・診断専用` と明記し、合否には数えない。
「測れない(判定不能)」と「不合格」を区別する。

この候補の探索側の弁（＝これから潰す主張）:
  ・13組の合格のうち**唯一 sga_r を脚に持たない**組
  ・被覆 96.8%（両脚が測れる行/母集団）＝欠測交絡がほとんど無い
  ・業種内 lift が 3年とも正（+0.111/+0.127/+0.177）で13組中最大
  ・ただし帰無の最大統計量分布の中に収まる水準

────────────────────────────────────────────────────────────
独立実装
────────────────────────────────────────────────────────────
探索器(hist_wd_win_pair.py)・既存の検証器から **一行も import しない**。
入力は out/hist_wd_panel.json と生の retro_{sic,monthly} だけ。
最後に探索側の数字と**セル単位で突き合わせる**（信じる前に検算する・v9.9.65）。

────────────────────────────────────────────────────────────
当てる6つ（1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 ビンテージ符号   2016/2017/2018 の符号。2013/2015 は f2_ が構造的に無く判定不能。
                   **「3ビンテージ＝3証拠」か**をティッカー重なり・群の重なり・
                   窓の重なり・結果ラベルの一致率で実測する
2 業種調整         MH（＋**MHが群の何%を覆っているか**）／間接標準化（層を落とさない版）／
                   層内置換／業種1つずつ除去／**業種単独の lift との比較**
3 irr の影         irr>=70 層内で残るか・直交か。irr の被覆率も出す
4 1社の影響        ティッカーを1社ずつパネルごと抜き、閾値・母集団・群・判定を全部作り直す
5 置換             (a)この候補単体の p（ティッカー束置換2000回）
                   (b)**探索空間の最大統計量の帰無**（P_quality の1420検定を自前で再構成）
                   (c)**業種内置換**での最大統計量（群が半導体の形をしているだけでないか）
6 既存の関門との重複 事業の収縮 / 利払カバー(nde代理) / 質実証 の生存者の中でも残るか＝増分

補助（事前登録の外・診断専用。合否には数えない）:
  M 可測性の交絡   両脚が測れること自体が勝者を予言していないか
  R レジーム分割   2018-07→2022-07 / 2022-07→末（月次在庫から自前で計算）
  L 脚の分解       aturn 単独 / rnd_r 単独 と増分
  S 群の正体       業種構成・勝者の顔ぶれ
"""
import json, os, math, random
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
SEARCH = os.path.join(OUT, "hist_wd_win_pair.json")      # 突合せ相手
SICF = os.path.join(OUT, "retro_sic.json")
MONTHLY = os.path.join(OUT, "retro_monthly_2018_2026.json")
DEST = os.path.join(OUT, "hist_wd_verify_aturn_rnd.json")

# ─── prereg の線（読むだけ・作らない） ───
LIFT_LINE = 0.15
MIN_NUM = 5
VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
NPERM = 2000
SEED = 20260811

# ─── 候補の定義（探索側のラベルをそのまま機械化。線を動かさない） ───
POP = "P_quality"
A_VAR, A_CUT = "f2_aturn", "中央値超"      # x >  q50
B_VAR, B_CUT = "f2_rnd_r", "上位1/4"       # x >= q75

# ─── 探索空間の再構成に使う語彙（探索側の設計をそのまま写す） ───
F2VARS = ["f2_gm", "f2_sga_r", "f2_capex_r", "f2_rnd_r", "f2_opm", "f2_intcov",
          "f2_aturn", "f2_accr", "f2_cash_r", "f2_gw_r", "f2_cagr5", "f2_accel",
          "f2_streak_rev", "f2_streak_opm", "f2_opmD5", "f2_fcfpos5", "f2_conv5",
          "f2_netiss_r", "f2_payout5", "f2_rev"]
ALLVARS = F2VARS + ["size_rev"]
CUTS = ["中央値超", "中央値以下", "上位1/4", "下位1/4"]
# 探索側 seeds をそのまま（実データで選ばれた10本＝固定種の帰無に使う）
SEEDS_PQ = [("f2_sga_r", "low"), ("f2_rnd_r", "high"), ("f2_cash_r", "high"),
            ("f2_aturn", "high"), ("f2_intcov", "high"), ("f2_netiss_r", "low"),
            ("f2_gm", "high"), ("f2_accel", "high"), ("f2_rev", "high"),
            ("size_rev", "high")]
SEEDS_PF = [("f2_sga_r", "low"), ("f2_gm", "low"), ("f2_aturn", "high"),
            ("f2_cash_r", "high"), ("f2_accel", "high"), ("f2_rnd_r", "high"),
            ("f2_accr", "low"), ("f2_opm", "low"), ("f2_capex_r", "low"),
            ("f2_intcov", "high")]
CUTS_BY_SIDE = {"high": ["中央値超", "上位1/4"], "low": ["中央値以下", "下位1/4"]}
SEMI = {"35", "36", "38"}   # 半導体連鎖（装置・電子部品・計測）


# ═══════════════════════════ 基本部品 ═══════════════════════════
def q_nearest_rank(vals, p):
    """nearest-rank 分位（探索側と同じ作法）。1-based index = ceil(p*n)。"""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    k = max(1, math.ceil(p * n))
    return s[min(k, n) - 1]


def cut_pred(x, thr, cut):
    """線は一つも作らない。探索側の演算子をそのまま写す。"""
    if x is None or thr is None:
        return False
    if cut == "中央値超":
        return x > thr
    if cut == "中央値以下":
        return x <= thr
    if cut == "上位1/4":
        return x >= thr
    if cut == "下位1/4":
        return x <= thr
    raise ValueError(cut)


CUT_P = {"中央値超": 0.50, "中央値以下": 0.50, "上位1/4": 0.75, "下位1/4": 0.25}


def r4(x):
    return None if x is None else round(float(x), 4)


def load_panel():
    return json.load(open(PANEL))["rows"]


def analysis_rows(rows, vintage, pop=POP):
    """解析対象＝ has_outcome ∧ window_full ∧ 母集団（探索側と同一）。"""
    return [r for r in rows
            if r["vintage"] == vintage and r.get("has_outcome")
            and r.get("window_full") and r.get(pop)]


def thresholds(pop_rows, var, cut):
    vals = [r[var] for r in pop_rows if r.get(var) is not None]
    if not vals:
        return None
    return q_nearest_rank(vals, CUT_P[cut])


def cell(pop_rows, spec):
    """spec = [(var,cut),...] の AND。lift は prereg literal（母集団全体が分母）。"""
    n_pop = len(pop_rows)
    if n_pop == 0:
        return None
    base_k = sum(1 for r in pop_rows if r["win"])
    p_base = base_k / n_pop
    thrs = {}
    for var, cut in spec:
        thrs[(var, cut)] = thresholds(pop_rows, var, cut)
    grp = []
    meas = 0
    for r in pop_rows:
        if all(r.get(v) is not None for v, _ in spec):
            meas += 1
        if all(cut_pred(r.get(v), thrs[(v, c)], c) for v, c in spec):
            grp.append(r)
    n_g = len(grp)
    k = sum(1 for r in grp if r["win"])
    p_g = (k / n_g) if n_g else None
    # 可測な行だけを分母にした base（欠測交絡の点検用）
    meas_rows = [r for r in pop_rows if all(r.get(v) is not None for v, _ in spec)]
    p_base_meas = (sum(1 for r in meas_rows if r["win"]) / len(meas_rows)) if meas_rows else None
    return {
        "n_pop": n_pop, "p_base": p_base, "base_k": base_k,
        "n_group": n_g, "numerator": k, "p_group": p_g,
        "lift": (p_g - p_base) if p_g is not None else None,
        "lift_meas": (p_g - p_base_meas) if (p_g is not None and p_base_meas is not None) else None,
        "n_measurable_both": meas,
        "coverage": meas / n_pop if n_pop else None,
        "thresholds": {f"{v}[{c}]": r4(thrs[(v, c)]) for v, c in spec},
        "group_tickers": sorted(r["ticker"] for r in grp),
        "winner_tickers": sorted(r["ticker"] for r in grp if r["win"]),
    }


def maintained(cells):
    """3ビンテージで符号が揃ったうえでの最小|lift|。揃わなければ None。"""
    lifts = [c["lift"] for c in cells if c and c["lift"] is not None]
    if len(lifts) != len(VINTAGES):
        return None
    if not (all(l > 0 for l in lifts) or all(l < 0 for l in lifts)):
        return None
    return min(abs(l) for l in lifts)


def verdict_L5(cells, mh_by_v, irr_ok):
    """prereg の5条件。1つでも欠ければ不合格。"""
    m = maintained(cells)
    reasons = []
    if m is None:
        reasons.append("sign_stability")
    if any((c is None or c["numerator"] < MIN_NUM) for c in cells):
        reasons.append("min_numerator")
    if m is None or m < LIFT_LINE:
        reasons.append("lift")
    if any((mh is None or abs(mh) < LIFT_LINE) for mh in mh_by_v):
        reasons.append("sector_control")
    if not irr_ok:
        reasons.append("not_irr_shadow")
    return ("合格" if not reasons else "不合格"), reasons


# ═══════════════════════════ 2 業種 ═══════════════════════════
def mh_risk_diff(pop_rows, grp_set, key="sic2"):
    """Mantel-Haenszel リスク差。**両側に人が居る層しか使えない**ので被覆も返す。"""
    strata = defaultdict(list)
    for r in pop_rows:
        strata[r.get(key) or "NA"].append(r)
    num = den = 0.0
    used = dropped = 0
    g_covered = g_total = 0
    for s, rs in strata.items():
        g = [r for r in rs if r["ticker"] in grp_set]
        ng = [r for r in rs if r["ticker"] not in grp_set]
        g_total += len(g)
        if not g or not ng:
            dropped += 1
            continue
        used += 1
        g_covered += len(g)
        n1, n0, N = len(g), len(ng), len(rs)
        p1 = sum(1 for r in g if r["win"]) / n1
        p0 = sum(1 for r in ng if r["win"]) / n0
        w = n1 * n0 / N
        num += w * (p1 - p0)
        den += w
    return {
        "mh_risk_diff": (num / den) if den else None,
        "strata_used": used, "strata_dropped": dropped,
        "group_covered": g_covered, "group_total": g_total,
        "group_coverage": (g_covered / g_total) if g_total else None,
    }


def indirect_standardized(pop_rows, grp_set, key="sic2"):
    """間接標準化＝**層を一つも落とさない**業種調整。
    期待勝者数 = Σ_s (群の人数_s × 群を除いた同層の勝率_s)。
    同層に非群が一人も居ない層は、母集団全体の勝率で埋める（埋めた人数も出す）。"""
    strata = defaultdict(list)
    for r in pop_rows:
        strata[r.get(key) or "NA"].append(r)
    p_all = sum(1 for r in pop_rows if r["win"]) / len(pop_rows)
    obs = exp = 0.0
    n_g = 0
    fallback_n = 0
    for s, rs in strata.items():
        g = [r for r in rs if r["ticker"] in grp_set]
        if not g:
            continue
        ng = [r for r in rs if r["ticker"] not in grp_set]
        n_g += len(g)
        obs += sum(1 for r in g if r["win"])
        if ng:
            p0 = sum(1 for r in ng if r["win"]) / len(ng)
        else:
            p0 = p_all
            fallback_n += len(g)
        exp += len(g) * p0
    return {
        "n_group": n_g, "observed_wins": obs, "expected_wins_given_sector": r4(exp),
        "excess_rate": r4((obs - exp) / n_g) if n_g else None,
        "strata_without_nongroup_members": fallback_n,
        "note": "excess_rate が業種調整後の実効 lift。層を一つも落とさない。",
    }


def fixed_lift(pop_rows, grp_set):
    """**群の顔ぶれを固定したまま**母集団を切り出して lift を測る。
    cell() は部分集合の中で分位を取り直すので群が入れ替わる——『この業種を抜いたら
    どうなるか』を問うときはそれでは答えにならない。ここは membership を動かさない。"""
    if not pop_rows:
        return None
    g = [r for r in pop_rows if r["ticker"] in grp_set]
    n = len(pop_rows)
    base = sum(1 for r in pop_rows if r["win"]) / n
    if not g:
        return {"n_pop": n, "p_base": base, "n_group": 0, "numerator": 0,
                "p_group": None, "lift": None}
    k = sum(1 for r in g if r["win"])
    return {"n_pop": n, "p_base": base, "n_group": len(g), "numerator": k,
            "p_group": k / len(g), "lift": k / len(g) - base}


def within_sector_perm_p(pop_rows, grp_set, nperm, rng, key="sic2"):
    """業種の中だけで結果を入れ替える帰無。業種で説明できる分は帰無にも残る。"""
    strata = defaultdict(list)
    for i, r in enumerate(pop_rows):
        strata[r.get(key) or "NA"].append(i)
    in_g = [1 if r["ticker"] in grp_set else 0 for r in pop_rows]
    wins = [1 if r["win"] else 0 for r in pop_rows]
    n_g = sum(in_g)
    if n_g == 0:
        return None
    obs = sum(w for w, g in zip(wins, in_g) if g) / n_g - sum(wins) / len(wins)
    ge = 0
    for _ in range(nperm):
        w2 = wins[:]
        for s, idx in strata.items():
            vals = [wins[i] for i in idx]
            rng.shuffle(vals)
            for i, v in zip(idx, vals):
                w2[i] = v
        lift = sum(w for w, g in zip(w2, in_g) if g) / n_g - sum(w2) / len(w2)
        if lift >= obs - 1e-12:
            ge += 1
    return {"observed_lift": r4(obs), "p_within_sector": (ge + 1) / (nperm + 1), "n_perm": nperm}


# ═══════════════════════════ 5 置換（束・最大統計量） ═══════════════════════════
def popcount(x):
    return bin(x).count("1")


def build_masks(rows, pop=POP):
    """ビンテージごとに (var,cut) の bitmask を作る。"""
    per_v = {}
    for v in VINTAGES:
        pr = analysis_rows(rows, v, pop)
        idx = {r["ticker"]: i for i, r in enumerate(pr)}
        masks = {}
        for var in ALLVARS:
            for cut in CUTS:
                thr = thresholds(pr, var, cut)
                m = 0
                for i, r in enumerate(pr):
                    if cut_pred(r.get(var), thr, cut):
                        m |= (1 << i)
                masks[(var, cut)] = m
        win = 0
        for i, r in enumerate(pr):
            if r["win"]:
                win |= (1 << i)
        per_v[v] = {"rows": pr, "idx": idx, "masks": masks, "win": win, "n": len(pr)}
    return per_v


def pair_space(seeds):
    """探索側の 1420 検定/母集団 を再構成（種10×2切り × 相手20×4切り、正規化して重複除去）。"""
    seen = set()
    out = []
    for svar, side in seeds:
        for scut in CUTS_BY_SIDE[side]:
            for pvar in ALLVARS:
                if pvar == svar:
                    continue
                for pcut in CUTS:
                    key = tuple(sorted([(svar, scut), (pvar, pcut)]))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(key)
    return out


def precompute_groups(per_v, pairs):
    """群マスクは置換で動かない（動くのは結果だけ）。1回だけ作って使い回す。
    第3要素は『脚に f2_sga_r を含まないか』——13件の合格のうち12件が sga_r を含むので、
    本候補（唯一の非sga_r組）を裁くときはこの部分空間だけを相手にするのが公平。"""
    out = []
    for a, b in pairs:
        gm, ng = [], []
        ok = True
        for v in VINTAGES:
            mv = per_v[v]["masks"]
            g = mv[a] & mv[b]
            c = popcount(g)
            if c == 0:
                ok = False
                break
            gm.append(g)
            ng.append(c)
        if ok:
            nosga = (a[0] != "f2_sga_r" and b[0] != "f2_sga_r")
            out.append((gm, ng, nosga, (a, b)))
    return out


TOPK = 13   # 実データの合格数と同じ深さまで順序統計量を見る


def max_stat(per_v, win_masks, groups):
    """帰無1回ぶんの『符号が揃ったうえでの3ビンテージ最小|lift|』の上位TOPK と L3 合格数。
    **最大値だけでは足りない**——実データでこの候補は13件中5位なので、
    比べる相手は帰無の『5番目に強い候補』でなければならない。"""
    top, top_ns = [], []
    npass = 0
    base = [popcount(win_masks[v]) / per_v[v]["n"] for v in VINTAGES]
    wm = [win_masks[v] for v in VINTAGES]
    for gm, ng, nosga, _pair in groups:
        l0 = popcount(gm[0] & wm[0])
        if l0 < MIN_NUM:
            continue
        l1 = popcount(gm[1] & wm[1])
        if l1 < MIN_NUM:
            continue
        l2 = popcount(gm[2] & wm[2])
        if l2 < MIN_NUM:
            continue
        a0 = l0 / ng[0] - base[0]
        a1 = l1 / ng[1] - base[1]
        a2 = l2 / ng[2] - base[2]
        if not ((a0 > 0 and a1 > 0 and a2 > 0) or (a0 < 0 and a1 < 0 and a2 < 0)):
            continue
        m = min(abs(a0), abs(a1), abs(a2))
        if len(top) < TOPK:
            top.append(m); top.sort()
        elif m > top[0]:
            top[0] = m; top.sort()
        if nosga:
            if len(top_ns) < TOPK:
                top_ns.append(m); top_ns.sort()
            elif m > top_ns[0]:
                top_ns[0] = m; top_ns.sort()
        if m >= LIFT_LINE:
            npass += 1
    return top, top_ns, npass


def ticker_outcomes(rows):
    """ティッカー→{ビンテージ: win} と ティッカー→sic2。母集団は P_full（上位集合）で作る。"""
    tick_out = defaultdict(dict)
    tick_sic = {}
    for v in VINTAGES:
        for r in analysis_rows(rows, v, "P_full"):
            tick_out[r["ticker"]][v] = r["win"]
            tick_sic[r["ticker"]] = r.get("sic2") or "NA"
    return tick_out, tick_sic


def make_mapping(ticks, rng, tick_sic, sector_bound=False):
    """ティッカー束置換の対応表。sector_bound なら**同じ sic2 の中でだけ**入れ替える
    （業種で説明できる分を帰無に残す＝より強い検査）。"""
    if sector_bound:
        by_s = defaultdict(list)
        for t in ticks:
            by_s[tick_sic.get(t, "NA")].append(t)
        mapping = {}
        for s, ts in by_s.items():
            perm = ts[:]
            rng.shuffle(perm)
            mapping.update(zip(ts, perm))
        return mapping
    perm = ticks[:]
    rng.shuffle(perm)
    return dict(zip(ticks, perm))


def apply_mapping(per_v, mapping, tick_out):
    """対応表から各ビンテージの win ビットマスクを作る。"""
    win_masks = {}
    for v in VINTAGES:
        m = 0
        for i, r in enumerate(per_v[v]["rows"]):
            src = mapping.get(r["ticker"], r["ticker"])
            val = tick_out.get(src, {}).get(v)
            if val is None:                       # 束の相手がその年に居ない→自分の値を残す
                val = r["win"]
            if val:
                m |= (1 << i)
        win_masks[v] = m
    return win_masks


# ═══════════════════════════ 本体 ═══════════════════════════
def main():
    rng = random.Random(SEED)
    rows = load_panel()
    search = json.load(open(SEARCH))
    spec = [(A_VAR, A_CUT), (B_VAR, B_CUT)]

    res = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_verify_aturn_rnd.py",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "stance": "反証が仕事。prereg の線を一つも緩めない。緩めた数字は『事前登録の外・診断専用』と明記し合否に数えない。",
        "candidate": {
            "label": f"{A_VAR}[{A_CUT}] ∧ {B_VAR}[{B_CUT}]",
            "side": "winner (P(tr_cagr>=+15%))",
            "population": POP,
            "search_side_claim": {
                "maintained_lift": 0.2044, "n_group_2018": 33,
                "numerator_2018": 15, "lift_2018": 0.2599,
                "弁": "13組で唯一 sga_r を含まない／被覆97%／業種内liftが13組中最大",
            },
        },
    }

    # ── 0 再現（信じる前に検算する） ──
    cells = {}
    for v in ALL_VINTAGES:
        pr = analysis_rows(rows, v)
        meas = sum(1 for r in pr if r.get(A_VAR) is not None and r.get(B_VAR) is not None)
        if meas == 0:
            cells[v] = None
            continue
        cells[v] = cell(pr, spec)
    c3 = [cells[v] for v in VINTAGES]
    obs_maintained = maintained(c3)

    cmp_rows = []
    for v in VINTAGES:
        s = None
        for p in search["passing_pairs_detail"]:
            if p["label"] == f"{A_VAR}[{A_CUT}] ∧ {B_VAR}[{B_CUT}]" and p["population"] == POP:
                s = p["by_vintage"].get(str(v))
        mine = cells[v]
        cmp_rows.append({
            "vintage": v,
            "mine": {"n_pop": mine["n_pop"], "n_group": mine["n_group"],
                     "numerator": mine["numerator"], "lift": r4(mine["lift"])},
            "search": {"n_pop": s["n_pop"], "n_group": s["n_group"],
                       "numerator": s["numerator"], "lift": s["lift"]} if s else None,
            "match": bool(s and s["n_pop"] == mine["n_pop"] and s["n_group"] == mine["n_group"]
                          and s["numerator"] == mine["numerator"]
                          and abs(s["lift"] - mine["lift"]) < 5e-4),
        })
    res["step0_reproduction"] = {
        "note": "探索側と独立に組み直して突き合わせる。ここが合わなければ以降の反証は意味を持たない。",
        "cells": cmp_rows,
        "all_match": all(x["match"] for x in cmp_rows),
        "observed_maintained_lift": r4(obs_maintained),
    }

    # ── 1 ビンテージ符号 ＋ 「3ビンテージ＝3証拠か」 ──
    per_v_pop = {v: analysis_rows(rows, v) for v in ALL_VINTAGES}
    thin = {}
    for v in [2013, 2015]:
        pr = per_v_pop[v]
        thin[v] = {
            "n_pop": len(pr),
            "n_measurable_f2_aturn": sum(1 for r in pr if r.get(A_VAR) is not None),
            "n_measurable_f2_rnd_r": sum(1 for r in pr if r.get(B_VAR) is not None),
            "verdict": "判定不能（f2_ 系の列が構造的に存在しない。不合格ではない）",
        }
    # 群・母集団・結果ラベルの重なり
    gsets = {v: set(cells[v]["group_tickers"]) for v in VINTAGES}
    psets = {v: set(r["ticker"] for r in per_v_pop[v]) for v in VINTAGES}
    def jac(a, b):
        return len(a & b) / len(a | b) if (a | b) else None
    win_by_v = {v: {r["ticker"]: r["win"] for r in per_v_pop[v]} for v in VINTAGES}
    agree = {}
    for a in VINTAGES:
        for b in VINTAGES:
            if a >= b:
                continue
            common = set(win_by_v[a]) & set(win_by_v[b])
            same = sum(1 for t in common if win_by_v[a][t] == win_by_v[b][t])
            agree[f"{a}vs{b}"] = {"n_common": len(common),
                                  "outcome_agreement": r4(same / len(common)) if common else None}
    yrs = {}
    for v in VINTAGES:
        ys = [r["years"] for r in per_v_pop[v] if r.get("years")]
        yrs[v] = r4(sum(ys) / len(ys)) if ys else None
    res["attack1_vintage_sign"] = {
        "lifts": {str(v): r4(cells[v]["lift"]) for v in VINTAGES},
        "numerators": {str(v): cells[v]["numerator"] for v in VINTAGES},
        "n_group": {str(v): cells[v]["n_group"] for v in VINTAGES},
        "signs_all_positive": all(cells[v]["lift"] > 0 for v in VINTAGES),
        "maintained_lift": r4(obs_maintained),
        "thin_vintages_2013_2015": thin,
        "is_three_vintages_three_evidence": {
            "group_jaccard": {"2016vs2017": r4(jac(gsets[2016], gsets[2017])),
                              "2016vs2018": r4(jac(gsets[2016], gsets[2018])),
                              "2017vs2018": r4(jac(gsets[2017], gsets[2018]))},
            "population_jaccard": {"2016vs2018": r4(jac(psets[2016], psets[2018]))},
            "outcome_agreement_same_ticker": agree,
            "mean_window_years": {str(v): yrs[v] for v in VINTAGES},
            "window_overlap_note": "3窓とも終点が同じ（2026年）。2018窓は2016窓に完全に含まれる＝"
                                   "共有期間 / 2016窓 ≈ " +
                                   (str(r4(yrs[2018] / yrs[2016])) if yrs[2016] else "NA"),
            "verdict": "prereg 自身が『独立標本ではない』と警告している通り。符号不変ゲートは"
                       "通るが、独立な3証拠としては読めない",
        },
        "gate_pass": all(cells[v]["lift"] > 0 for v in VINTAGES) and obs_maintained is not None,
    }

    # ── 2 業種 ──
    sec = {}
    mh_list = []
    for v in VINTAGES:
        pr = per_v_pop[v]
        gs = gsets[v]
        m = mh_risk_diff(pr, gs)
        mh_list.append(m["mh_risk_diff"])
        ind = indirect_standardized(pr, gs)
        perm = within_sector_perm_p(pr, gs, NPERM, random.Random(SEED + v))
        # 業種単独の lift（群を使わずに業種だけで何が出るか）
        cnt = Counter(r.get("sic2") or "NA" for r in pr)
        p_base = cells[v]["p_base"]
        sec_alone = []
        for s, n in cnt.most_common(6):
            rs = [r for r in pr if (r.get("sic2") or "NA") == s]
            k = sum(1 for r in rs if r["win"])
            sec_alone.append({"sic2": s, "n": n, "p": r4(k / n), "lift_of_sector_alone": r4(k / n - p_base),
                              "group_members_in_sector": sum(1 for r in rs if r["ticker"] in gs)})
        # 群の業種構成
        gcnt = Counter(r.get("sic2") or "NA" for r in pr if r["ticker"] in gs)
        top3 = gcnt.most_common(3)
        # 業種1つずつ除去（**群の顔ぶれを固定**。分位を取り直す版も併記する）
        drop = {}
        for s in sorted(cnt):
            sub = [r for r in pr if (r.get("sic2") or "NA") != s]
            if not sub:
                continue
            fx = fixed_lift(sub, gs)
            rc = cell(sub, spec)
            drop[s] = {
                "fixed_membership": {"lift": r4(fx["lift"]), "n_group": fx["n_group"],
                                     "numerator": fx["numerator"]} if fx else None,
                "requantiled": {"lift": r4(rc["lift"]), "n_group": rc["n_group"],
                                "numerator": rc["numerator"]} if rc and rc["n_group"] else None,
            }
        # 業種ごとの超過勝者数の分解（どの業種が lift を運んでいるか）
        excess = []
        for s in sorted(cnt):
            rs = [r for r in pr if (r.get("sic2") or "NA") == s]
            g_s = [r for r in rs if r["ticker"] in gs]
            if not g_s:
                continue
            ng_s = [r for r in rs if r["ticker"] not in gs]
            p0 = (sum(1 for r in ng_s if r["win"]) / len(ng_s)) if ng_s else p_base
            obs = sum(1 for r in g_s if r["win"])
            excess.append({"sic2": s, "n_group": len(g_s), "observed_wins": obs,
                           "expected_wins_same_sector": r4(len(g_s) * p0),
                           "excess_wins": r4(obs - len(g_s) * p0)})
        excess.sort(key=lambda x: -(x["excess_wins"] or 0))
        tot_excess = sum(e["excess_wins"] for e in excess)
        # 半導体連鎖(SIC 35/36/38)の内外——**群の顔ぶれを固定**
        inside = [r for r in pr if (r.get("sic2") or "NA") in SEMI]
        outside = [r for r in pr if (r.get("sic2") or "NA") not in SEMI]
        c_in = fixed_lift(inside, gs)
        c_out = fixed_lift(outside, gs)
        sec[str(v)] = {
            "mh": {k: (r4(m[k]) if isinstance(m[k], float) else m[k]) for k in m},
            "indirect_standardized_all_strata": ind,
            "within_sector_permutation": perm,
            "sector_alone_top6": sec_alone,
            "group_sector_top3": [{"sic2": s, "n": n, "share_of_group": r4(n / cells[v]["n_group"])}
                                  for s, n in top3],
            "group_top3_share": r4(sum(n for _, n in top3) / cells[v]["n_group"]),
            "drop_one_sector": drop,
            "sector_excess_decomposition": {
                "rows": excess, "total_excess_wins": r4(tot_excess),
                "top_sector_share_of_excess": r4(excess[0]["excess_wins"] / tot_excess)
                                              if excess and tot_excess else None,
                "note": "群の超過勝者が『どの業種から出ているか』。1業種に偏るほど、"
                        "指標ではなく業種を選んでいる",
            },
            "semi_chain_split_sic35_36_38_fixed_membership": {
                "inside": {"n_pop": c_in["n_pop"], "p_base": r4(c_in["p_base"]),
                           "n_group": c_in["n_group"], "numerator": c_in["numerator"],
                           "lift": r4(c_in["lift"])} if c_in else None,
                "outside": {"n_pop": c_out["n_pop"], "p_base": r4(c_out["p_base"]),
                            "n_group": c_out["n_group"], "numerator": c_out["numerator"],
                            "lift": r4(c_out["lift"])} if c_out else None,
                "note": "群が半導体連鎖の形をしているだけなら、外側で lift は消える",
            },
        }
    # 業種を1つ落としたときの**維持lift**（同じ業種を3ビンテージから落とす）
    drop_maint = {}
    all_sec = sorted(set(s for v in VINTAGES for s in sec[str(v)]["drop_one_sector"]))
    for s in all_sec:
        for mode in ("fixed_membership", "requantiled"):
            ls = []
            for v in VINTAGES:
                d0 = sec[str(v)]["drop_one_sector"].get(s, {}).get(mode)
                ls.append(d0["lift"] if d0 else None)
            if any(l is None for l in ls):
                continue
            if not (all(l > 0 for l in ls) or all(l < 0 for l in ls)):
                m = None
            else:
                m = min(abs(l) for l in ls)
            drop_maint.setdefault(mode, {})[s] = {"lifts": ls, "maintained": r4(m),
                                                  "still_passes_line": bool(m is not None and m >= LIFT_LINE)}
    drop_summary = {}
    for mode, dd in drop_maint.items():
        fails = [s for s, x in dd.items() if not x["still_passes_line"]]
        worst = min(dd, key=lambda s: (dd[s]["maintained"] is None, dd[s]["maintained"] or -9))
        drop_summary[mode] = {
            "n_sectors_tested": len(dd),
            "sectors_whose_removal_breaks_the_line": fails,
            "worst_sector": worst, "worst_maintained": dd[worst]["maintained"],
            "worst_lifts": dd[worst]["lifts"],
        }
    res["attack2_sector"] = {
        "by_vintage": sec,
        "drop_one_sector_maintained": drop_maint,
        "drop_one_sector_summary": drop_summary,
        "mh_all_ge_line": all(mh is not None and abs(mh) >= LIFT_LINE for mh in mh_list),
        "mh_coverage_warning": "MH は『群と非群が両方いる層』しか使えない。被覆(group_coverage)が"
                               "低いほど MH は群の一部しか見ていない",
        "gate_pass": all(mh is not None and abs(mh) >= LIFT_LINE for mh in mh_list),
    }

    # ── 3 irr の影 ──
    irr = {}
    for v in VINTAGES:
        pr = per_v_pop[v]
        gs = gsets[v]
        with_irr = [r for r in pr if r.get("irr_near") is not None]
        g_with_irr = [r for r in with_irr if r["ticker"] in gs]
        layers = {}
        for name, cond in [("irr>=70", lambda x: x >= 70), ("irr>=85", lambda x: x >= 85),
                           ("irr<70", lambda x: x < 70)]:
            sub = [r for r in with_irr if cond(r["irr_near"])]
            if not sub:
                layers[name] = None
                continue
            b = sum(1 for r in sub if r["win"]) / len(sub)
            g = [r for r in sub if r["ticker"] in gs]
            k = sum(1 for r in g if r["win"])
            layers[name] = {"n": len(sub), "base": r4(b), "n_group": len(g), "numerator": k,
                            "p_group": r4(k / len(g)) if g else None,
                            "lift": r4(k / len(g) - b) if g else None,
                            "numerator_ge_5": k >= MIN_NUM}
        # 相関（群フラグ vs irr）
        xs = [1.0 if r["ticker"] in gs else 0.0 for r in with_irr]
        ys = [float(r["irr_near"]) for r in with_irr]
        n = len(xs)
        if n > 2:
            mx, my = sum(xs) / n, sum(ys) / n
            sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
            sy = math.sqrt(sum((y - my) ** 2 for y in ys))
            corr = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)) if sx and sy else None
        else:
            corr = None
        irr[str(v)] = {
            "irr_coverage_population": r4(len(with_irr) / len(pr)),
            "irr_coverage_group": r4(len(g_with_irr) / len(gs)) if gs else None,
            "irr_reading_year_source": dict(Counter(str(r.get("irr_near_src")) for r in with_irr)),
            "corr_group_vs_irr": r4(corr),
            "irr_distribution_group": dict(Counter(r["irr_near"] for r in g_with_irr)),
            "irr_distribution_pop": dict(Counter(r["irr_near"] for r in with_irr)),
            "layers": layers,
        }
    ok70 = []
    for v in VINTAGES:
        L = irr[str(v)]["layers"].get("irr>=70")
        ok70.append(bool(L and L["lift"] is not None and abs(L["lift"]) >= LIFT_LINE and L["numerator_ge_5"]))
    ok_lo = []
    for v in VINTAGES:
        L = irr[str(v)]["layers"].get("irr<70")
        ok_lo.append(bool(L and L["lift"] is not None and abs(L["lift"]) >= LIFT_LINE and L["numerator_ge_5"]))
    corrs = [irr[str(v)]["corr_group_vs_irr"] for v in VINTAGES]
    res["attack3_irr_shadow"] = {
        "by_vintage": irr,
        "two_readings_of_the_gate": {
            "reading_A_2018_only": {
                "holds": ok70[-1],
                "note": "**探索側が実際に当てた読み**（出力キーが irr_control_2018）。"
                        "3ビンテージのうち効果が最大の年だけで対照を取っている",
            },
            "reading_B_all_three_vintages": {
                "holds": all(ok70),
                "lifts": {str(v): irr[str(v)]["layers"]["irr>=70"]["lift"] for v in VINTAGES},
                "note": "prereg 全体が3ビンテージの符号不変を土台にしている以上、対照も3年に当てるのが筋。"
                        "**2016(0.1182)・2017(0.1386) が線を割る**",
            },
            "which_this_tool_uses": "B（厳しい側）。ただし A の結果も残す——"
                                    "どちらの読みかで結論が変わる論点であることを隠さない",
        },
        "orthogonality": {
            "corr_group_vs_irr": {str(v): c for v, c in zip(VINTAGES, corrs)},
            "orthogonal": all(c is not None and abs(c) < 0.10 for c in corrs),
            "note": "prereg の逃げ道『irr と直交』はこの相関では成立しない（0.18〜0.23）",
        },
        "counter_evidence_for_the_candidate": {
            "irr_lt70_layer_holds_all_vintages": all(ok_lo),
            "irr_lt70_lifts": {str(v): irr[str(v)]["layers"]["irr<70"]["lift"] for v in VINTAGES},
            "note": "**候補に有利な事実も書く**。低irr層では3年とも線を超える＝この候補は"
                    "『irr の影』そのものではない。高irr層で弱く見えるのは、その層の基準勝率が"
                    "既に0.31-0.36と高く lift の伸びしろが小さいという天井効果も混じる",
        },
        "provenance_warning": {
            "issue": "**irr_near はビンテージごとに読解年が違う**（irr_reading_year_source を見よ）。"
                     "2016 はほぼ全部 2015年の読解、2018 は 2015年と2018年の読解が混在する。"
                     "同じ『irr>=70 層』と呼んでいるものが年によって別の構成になっている＝"
                     "この台帳が繰り返し踏んできた『基準の違う二つを突き合わせる』型。",
            "consequence": "reading_B（3年に当てる）の 2016/2017 の不合格は、指標の弱さなのか"
                           "irr ラベルの出所の違いなのかを**この在庫では分離できない**。"
                           "よってこのゲートは『不合格』と『判定不能』の境目にある",
        },
        "caveat": "irr の読解は母集団の一部しか覆っていない。層内 n が小さいほど『残った』は弱い証拠",
        "gate_pass": all(ok70),
    }

    # ── 4 1社の影響（パネルごと抜いて全部作り直す） ──
    all_ticks = sorted(set().union(*[psets[v] for v in VINTAGES]))
    loo = []
    for t in all_ticks:
        cs = []
        ok = True
        for v in VINTAGES:
            pr = [r for r in per_v_pop[v] if r["ticker"] != t]
            cc = cell(pr, spec)
            if cc is None or cc["n_group"] == 0:
                ok = False
                break
            cs.append(cc)
        if not ok or len(cs) != 3:
            continue
        m = maintained(cs)
        minnum = min(c["numerator"] for c in cs)
        loo.append({"ticker": t, "maintained_lift": m, "min_numerator": minnum,
                    "fails_lift": (m is None or m < LIFT_LINE),
                    "fails_minnum": minnum < MIN_NUM})
    loo_sorted = sorted(loo, key=lambda x: (x["maintained_lift"] is None, x["maintained_lift"]))
    n_flip = sum(1 for x in loo if x["fails_lift"] or x["fails_minnum"])
    res["attack4_one_company"] = {
        "n_tickers_dropped_one_at_a_time": len(loo),
        "maintained_lift_min": r4(loo_sorted[0]["maintained_lift"]) if loo_sorted else None,
        "maintained_lift_max": r4(loo_sorted[-1]["maintained_lift"]) if loo_sorted else None,
        "worst5": [{"ticker": x["ticker"], "maintained_lift": r4(x["maintained_lift"]),
                    "min_numerator": x["min_numerator"]} for x in loo_sorted[:5]],
        "n_drops_that_flip_verdict": n_flip,
        "flipping_tickers": [x["ticker"] for x in loo if x["fails_lift"] or x["fails_minnum"]][:20],
        "gate_pass": n_flip == 0,
        "note": "1社抜きで判定が反転するなら、その候補は1社が作っている",
    }

    # ── 5 置換 ──
    per_vq = build_masks(rows, "P_quality")
    per_vf = build_masks(rows, "P_full")
    pairs_q = pair_space(SEEDS_PQ)
    pairs_f = pair_space(SEEDS_PF)
    grp_q = precompute_groups(per_vq, pairs_q)
    grp_f = precompute_groups(per_vf, pairs_f)
    tick_out, tick_sic = ticker_outcomes(rows)
    ticks = sorted(tick_out)
    a_key, b_key = (A_VAR, A_CUT), (B_VAR, B_CUT)
    obs_m = obs_maintained

    def pct(a, p):
        return a[min(len(a) - 1, max(0, int(round(p * (len(a) - 1)))))]

    def run_null(sector_bound, seed):
        """1つの対応表を**両母集団に同時に**当てる（同じティッカー束置換＝一貫した帰無）。
        返すのは (この候補単体の超過回数, 全2840検定の最大統計量の列, L3合格数の列)。"""
        rng = random.Random(seed)
        ge = 0
        maxes, maxes_ns, npasses = [], [], []
        for _ in range(NPERM):
            mp = make_mapping(ticks, rng, tick_sic, sector_bound)
            wq = apply_mapping(per_vq, mp, tick_out)
            wf = apply_mapping(per_vf, mp, tick_out)
            # 候補単体
            lifts, okk = [], True
            for i, v in enumerate(VINTAGES):
                mv = per_vq[v]["masks"]
                g = mv[a_key] & mv[b_key]
                ng = popcount(g)
                if ng == 0:
                    okk = False
                    break
                lifts.append(popcount(g & wq[v]) / ng - popcount(wq[v]) / per_vq[v]["n"])
            if okk and (all(l > 0 for l in lifts) or all(l < 0 for l in lifts)) \
               and min(abs(l) for l in lifts) >= obs_m - 1e-12:
                ge += 1
            # 全空間の順序統計量（両母集団を合流させてから上位を取る）
            tq, tqn, nq = max_stat(per_vq, wq, grp_q)
            tf, tfn, nf = max_stat(per_vf, wf, grp_f)
            maxes.append(sorted(tq + tf, reverse=True))
            maxes_ns.append(sorted(tqn + tfn, reverse=True))
            npasses.append(nq + nf)
        return ge, maxes, maxes_ns, npasses

    def order_stat(maxes, k):
        """帰無の『k番目に強い候補』の分布（k は1始まり）。"""
        return sorted((m[k - 1] if len(m) >= k else 0.0) for m in maxes)

    ge_plain, maxes_raw, maxes_raw_ns, npasses = run_null(False, SEED)
    p_single = (ge_plain + 1) / (NPERM + 1)
    maxes = order_stat(maxes_raw, 1)
    p_max = sum(1 for m in maxes if m >= obs_m - 1e-12) / len(maxes)

    ge_sec, maxes_raw_s, maxes_raw_s_ns, npasses_s = run_null(True, SEED + 2)
    p_single_sec = (ge_sec + 1) / (NPERM + 1)
    maxes_s = order_stat(maxes_raw_s, 1)
    p_max_s = sum(1 for m in maxes_s if m >= obs_m - 1e-12) / len(maxes_s)

    # ── 順序統計量（この候補は実データで13件中5位。比べる相手は帰無の5位） ──
    RANK = 5
    ord_plain = order_stat(maxes_raw, RANK)
    ord_sec = order_stat(maxes_raw_s, RANK)
    p_ord = sum(1 for m in ord_plain if m >= obs_m - 1e-12) / len(ord_plain)
    p_ord_sec = sum(1 for m in ord_sec if m >= obs_m - 1e-12) / len(ord_sec)

    # ── sga_r を含まない部分空間だけを相手にした帰無（本候補にとって最も公平な単一検定） ──
    ns_max = order_stat(maxes_raw_ns, 1)
    ns_max_s = order_stat(maxes_raw_s_ns, 1)
    p_ns = sum(1 for m in ns_max if m >= obs_m - 1e-12) / len(ns_max)
    p_ns_s = sum(1 for m in ns_max_s if m >= obs_m - 1e-12) / len(ns_max_s)
    ns_2nd = order_stat(maxes_raw_ns, 2)
    ns_2nd_s = order_stat(maxes_raw_s_ns, 2)
    p_ns2 = sum(1 for m in ns_2nd if m >= obs_m - 1e-12) / len(ns_2nd)
    p_ns2_s = sum(1 for m in ns_2nd_s if m >= obs_m - 1e-12) / len(ns_2nd_s)
    # 実データで sga_r 抜き空間の最大は誰か（本候補が1位かを確かめる）
    def observed_nosga_top():
        out = []
        for per_v, grp, pop in ((per_vq, grp_q, "P_quality"), (per_vf, grp_f, "P_full")):
            base = [popcount(per_v[v]["win"]) / per_v[v]["n"] for v in VINTAGES]
            wm = [per_v[v]["win"] for v in VINTAGES]
            for gm, ng, nosga, pr in grp:
                if not nosga:
                    continue
                ks = [popcount(gm[i] & wm[i]) for i in range(3)]
                if min(ks) < MIN_NUM:
                    continue
                ls = [ks[i] / ng[i] - base[i] for i in range(3)]
                if not (all(l > 0 for l in ls) or all(l < 0 for l in ls)):
                    continue
                out.append((min(abs(l) for l in ls), pop,
                            f"{pr[0][0]}[{pr[0][1]}] ∧ {pr[1][0]}[{pr[1][1]}]"))
        out.sort(reverse=True)
        return out[:6]
    ns_top_real = observed_nosga_top()

    res["attack5_permutation"] = {
        "null_construction": "ティッカーの結果ベクトル(3ビンテージぶん)を丸ごと入れ替える束置換。"
                             "特徴量・欠測構造・母集団の定義を保ったまま特徴量↔結果だけを壊す。"
                             "**1つの対応表を P_full と P_quality に同時に当てる**（一貫した帰無）。",
        "a_single_test": {
            "observed_maintained_lift": r4(obs_m),
            "p_plain": r4(p_single), "p_within_sector": r4(p_single_sec), "n_perm": NPERM,
            "note": "この候補**だけ**を検定したときの p。多重検定の値札を払っていない",
        },
        "b_search_space_max_statistic": {
            "space": "探索側の全空間を再構成（P_full 1420 + P_quality 1420 = 2840検定）",
            "n_tests_reconstructed": len(pairs_f) + len(pairs_q),
            "n_tests_with_nonempty_group": len(grp_f) + len(grp_q),
            "coverage_of_full_bill": r4((len(pairs_f) + len(pairs_q)) / 2840),
            "null_max_percentiles": {"p50": r4(pct(maxes, 0.50)), "p75": r4(pct(maxes, 0.75)),
                                     "p90": r4(pct(maxes, 0.90)), "p95": r4(pct(maxes, 0.95)),
                                     "p99": r4(pct(maxes, 0.99)), "max": r4(maxes[-1])},
            "observed": r4(obs_m),
            "p_of_observed_vs_null_max": r4(p_max),
            "mean_L3_passes_per_permutation": r4(sum(npasses) / len(npasses)),
            "note": "**探索が2840通りを試した以上、値札はこちら**。『雑音を並べ替えただけのデータでも、"
                    "最良の候補はこれくらい強く見える』の分布",
        },
        "d_order_statistic_rank5": {
            "why": "**この候補は実データの合格13件のうち5位**（1位 0.2985 / 2位 0.2953 / 3位 0.2424 / "
                   "4位 0.2072 / **5位 0.2044＝本候補**）。最大値の帰無と比べるのは1位の候補への検定であって、"
                   "5位の候補にはむしろ甘い。正しい相手は帰無の『5番目に強い候補』の分布。",
            "rank_in_real_passes": RANK,
            "null_5th_percentiles_plain": {"p50": r4(pct(ord_plain, 0.50)), "p90": r4(pct(ord_plain, 0.90)),
                                           "p95": r4(pct(ord_plain, 0.95)), "max": r4(ord_plain[-1])},
            "p_of_observed_vs_null_5th_plain": r4(p_ord),
            "null_5th_percentiles_within_sector": {"p50": r4(pct(ord_sec, 0.50)), "p90": r4(pct(ord_sec, 0.90)),
                                                   "p95": r4(pct(ord_sec, 0.95)), "max": r4(ord_sec[-1])},
            "p_of_observed_vs_null_5th_within_sector": r4(p_ord_sec),
        },
        "e_sga_free_subspace": {
            "why": "**13件の合格のうち12件が脚に f2_sga_r を持つ**。合格の集団が『雑音より多い』という"
                   "探索側の弁（13件 vs 帰無平均1.2〜3.5・p=0.004）は、その sga_r 一族が担っている。"
                   "本候補は**唯一 sga_r を含まない組**なので、その集団の証拠を借りられない。"
                   "公平な相手は『sga_r を脚に持たない候補だけ』の空間での最大統計量。",
            "observed_top6_in_real_data": [{"maintained": r4(m), "population": pop, "label": lab}
                                           for m, pop, lab in ns_top_real],
            "rank_of_candidate_in_this_subspace": next(
                (i + 1 for i, (m, pop, lab) in enumerate(ns_top_real)
                 if lab.startswith("f2_aturn") and pop == "P_quality"), None),
            "null_max_percentiles_plain": {"p50": r4(pct(ns_max, 0.50)), "p90": r4(pct(ns_max, 0.90)),
                                           "p95": r4(pct(ns_max, 0.95)), "max": r4(ns_max[-1])},
            "p_of_observed_plain": r4(p_ns),
            "null_max_percentiles_within_sector": {"p50": r4(pct(ns_max_s, 0.50)), "p90": r4(pct(ns_max_s, 0.90)),
                                                   "p95": r4(pct(ns_max_s, 0.95)), "max": r4(ns_max_s[-1])},
            "p_of_observed_within_sector": r4(p_ns_s),
            "second_order_statistic_because_candidate_is_rank2": {
                "p_plain": r4(p_ns2), "p_within_sector": r4(p_ns2_s),
                "null_2nd_p50_plain": r4(pct(ns_2nd, 0.50)),
                "null_2nd_p50_within_sector": r4(pct(ns_2nd_s, 0.50)),
                "note": "この部分空間で本候補は2位なので、最大値より2位の分布のほうが正しい相手",
            },
        },
        "c_within_sector_max_statistic": {
            "null_max_percentiles": {"p50": r4(pct(maxes_s, 0.50)), "p75": r4(pct(maxes_s, 0.75)),
                                     "p90": r4(pct(maxes_s, 0.90)), "p95": r4(pct(maxes_s, 0.95)),
                                     "max": r4(maxes_s[-1])},
            "p_of_observed_vs_null_max": r4(p_max_s),
            "mean_L3_passes_per_permutation": r4(sum(npasses_s) / len(npasses_s)),
            "note": "業種の中だけで結果を入れ替えた帰無。業種で説明できる分は帰無にも残るので、"
                    "ここを超えて初めて『指標が分けた』と言える。**MHは層の9割を落とすので"
                    "こちらのほうが強い検査**",
        },
    }

    # ── 6 既存の関門との重複（増分） ──
    inc = {}
    for v in VINTAGES:
        pr = per_v_pop[v]
        gs = gsets[v]
        def shrink(r):
            a, b = r.get("f2_cagr5"), r.get("f2_opmD5")
            return (a is not None and b is not None and a < 0 and b < 0)
        def lowcov(r, line):
            x = r.get("f2_intcov")
            return (x is not None and x < line)
        g_rows = [r for r in pr if r["ticker"] in gs]
        surv = [r for r in pr if not shrink(r) and not lowcov(r, 3.0)]
        cs = cell(surv, spec) if surv else None
        surv5 = [r for r in pr if not shrink(r) and not lowcov(r, 5.0)]
        cs5 = cell(surv5, spec) if surv5 else None
        inc[str(v)] = {
            "group_caught_by_shrink_gate": sum(1 for r in g_rows if shrink(r)),
            "group_caught_by_intcov_lt3": sum(1 for r in g_rows if lowcov(r, 3.0)),
            "group_caught_by_intcov_lt5": sum(1 for r in g_rows if lowcov(r, 5.0)),
            "group_n": len(g_rows),
            "lift_among_survivors_intcov3": {"n_pop": cs["n_pop"], "n_group": cs["n_group"],
                                             "numerator": cs["numerator"], "lift": r4(cs["lift"])} if cs else None,
            "lift_among_survivors_intcov5": {"n_pop": cs5["n_pop"], "n_group": cs5["n_group"],
                                             "numerator": cs5["numerator"], "lift": r4(cs5["lift"])} if cs5 else None,
        }
    # 質実証の外（P_full）でどうなるか＝この候補が『質』と別の情報か
    pfull = {}
    for v in VINTAGES:
        pr = [r for r in rows if r["vintage"] == v and r.get("has_outcome")
              and r.get("window_full") and r.get("P_full")]
        cc = cell(pr, spec)
        pfull[str(v)] = {"n_pop": cc["n_pop"], "n_group": cc["n_group"],
                         "numerator": cc["numerator"], "lift": r4(cc["lift"])}
    res["attack6_increment_over_existing_gates"] = {
        "note": "この候補は『買わない理由』ではなく『勝者を拾う側』なので、増分は"
                "『既存の関門を通った社の中でも差が残るか』で測る。母集団は既に P_quality なので"
                "質実証との増分は構造上ゼロ（重複しているのではなく、同じ土俵の上に立っている）",
        "by_vintage": inc,
        "same_pair_in_P_full": pfull,
        "existing_gate_proxies": {
            "事業の収縮": "f2_cagr5<0 ∧ f2_opmD5<0（門の ccfShrinkGate と同型）",
            "財務キル": "f2_intcov による代理。**nde>4 そのものではない**（パネルに nde が無い）",
            "質実証": "母集団 P_quality そのもの",
        },
    }

    # ── 判定 ──
    irr_ok = all(ok70)
    v_verdict, reasons = verdict_L5(c3, mh_list, irr_ok)
    res["verdict"] = {
        "prereg_5_gates": {
            "lift>=0.15": bool(obs_m is not None and obs_m >= LIFT_LINE),
            "numerator>=5": all(c["numerator"] >= MIN_NUM for c in c3),
            "sign_stability": obs_m is not None,
            "sector_control_MH": all(mh is not None and abs(mh) >= LIFT_LINE for mh in mh_list),
            "not_irr_shadow": irr_ok,
        },
        "prereg_verdict": v_verdict,
        "failed_gates": reasons,
    }

    # ═══ 補助（事前登録の外・診断専用。合否には数えない） ═══
    diag = {"header": "事前登録の外・診断専用。合否には数えない。"}

    # M 可測性の交絡
    meas_conf = {}
    for v in VINTAGES:
        pr = per_v_pop[v]
        m_rows = [r for r in pr if r.get(A_VAR) is not None and r.get(B_VAR) is not None]
        nm_rows = [r for r in pr if not (r.get(A_VAR) is not None and r.get(B_VAR) is not None)]
        meas_conf[str(v)] = {
            "n_measurable_both": len(m_rows), "n_not_measurable": len(nm_rows),
            "coverage": r4(len(m_rows) / len(pr)),
            "p_win_measurable": r4(sum(1 for r in m_rows if r["win"]) / len(m_rows)) if m_rows else None,
            "p_win_not_measurable": r4(sum(1 for r in nm_rows if r["win"]) / len(nm_rows)) if nm_rows else None,
            "lift_vs_measurable_base": r4(cells[v]["lift_meas"]),
        }
    diag["M_measurability_confound"] = meas_conf

    # L 脚の分解
    legs = {}
    for name, sp in [("aturn_alone", [(A_VAR, A_CUT)]), ("rnd_alone", [(B_VAR, B_CUT)]),
                     ("pair", spec)]:
        legs[name] = {str(v): r4(cell(per_v_pop[v], sp)["lift"]) for v in VINTAGES}
        legs[name]["maintained"] = r4(maintained([cell(per_v_pop[v], sp) for v in VINTAGES]))
    best_leg = max(legs["aturn_alone"]["maintained"] or 0, legs["rnd_alone"]["maintained"] or 0)
    legs["increment_of_pair_over_best_leg"] = r4((obs_m or 0) - best_leg)
    diag["L_leg_decomposition"] = legs

    # S 群の正体
    sic_desc = {}
    try:
        sd = json.load(open(SICF))
        srows = sd["rows"] if isinstance(sd, dict) else sd
        for r in srows:
            s2 = str(r.get("sic2") or "")
            if s2 and s2 not in sic_desc and r.get("sicDesc"):
                sic_desc[s2] = r["sicDesc"]
    except Exception:
        pass
    prof = {}
    for v in VINTAGES:
        pr = per_v_pop[v]
        gs = gsets[v]
        grows = [r for r in pr if r["ticker"] in gs]
        cnt = Counter((r.get("sic2") or "NA") for r in grows)
        prof[str(v)] = {
            "n_group": len(grows),
            "winners": cells[v]["winner_tickers"],
            "sic2_composition": [{"sic2": s, "n": n, "desc": sic_desc.get(s, "")}
                                 for s, n in cnt.most_common(8)],
            "semi_chain_share_sic35_36_38": r4(sum(n for s, n in cnt.items() if s in {"35", "36", "38"}) / len(grows)),
        }
        w = [r for r in grows if r["win"]]
        wc = Counter((r.get("sic2") or "NA") for r in w)
        prof[str(v)]["winner_semi_share"] = r4(sum(n for s, n in wc.items() if s in {"35", "36", "38"}) / len(w)) if w else None
    diag["S_group_identity"] = prof

    # R レジーム分割（2018ビンテージのみ・月次から自前で計算）
    try:
        mon = json.load(open(MONTHLY))
        SPLIT = 1657000000   # 2022-07 近辺
        def cagr_between(series, t0, t1):
            pts = [(t, p) for t, p in series if p and p > 0]
            if len(pts) < 4:
                return None
            a = min((p for p in pts if p[0] >= t0), key=lambda x: x[0], default=None)
            b = max((p for p in pts if p[0] <= t1), key=lambda x: x[0], default=None)
            if not a or not b or b[0] <= a[0]:
                return None
            yrs = (b[0] - a[0]) / (365.25 * 24 * 3600)
            if yrs < 1:
                return None
            return (b[1] / a[1]) ** (1 / yrs) - 1
        pr = per_v_pop[2018]
        gs = gsets[2018]
        def med(xs):
            xs = sorted(x for x in xs if x is not None)
            if not xs:
                return None
            n = len(xs)
            return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
        out_r = {}
        for nm, (t0, t1) in [("2018-07→2022-07", (1530400000, SPLIT)),
                             ("2022-07→末", (SPLIT, 4000000000))]:
            g = [cagr_between(mon[r["ticker"]], t0, t1) for r in pr
                 if r["ticker"] in gs and r["ticker"] in mon]
            o = [cagr_between(mon[r["ticker"]], t0, t1) for r in pr
                 if r["ticker"] not in gs and r["ticker"] in mon]
            out_r[nm] = {"n_group": sum(1 for x in g if x is not None),
                         "median_group": r4(med(g)),
                         "n_rest": sum(1 for x in o if x is not None),
                         "median_rest": r4(med(o)),
                         "gap_pt": r4((med(g) - med(o)) * 100) if (med(g) is not None and med(o) is not None) else None}
        diag["R_regime_2018_vintage"] = out_r
    except Exception as e:
        diag["R_regime_2018_vintage"] = {"error": str(e)}

    # P 相手の入れ替え可能性——種 rnd_r[上位1/4] に対して相手を総当たりする。
    #   もし多くの相手が同じくらい lift を持ち上げるなら、『aturn × rnd』は発見ではなく
    #   『rnd_r ＋ n を縮める何か』の一つの引きにすぎない。
    part = []
    for pv in ALLVARS:
        if pv == B_VAR:
            continue
        for pc in CUTS:
            cs = [cell(per_v_pop[v], [(B_VAR, B_CUT), (pv, pc)]) for v in VINTAGES]
            if any(c is None or c["n_group"] == 0 for c in cs):
                continue
            m = maintained(cs)
            if m is None:
                continue
            part.append({"partner": f"{pv}[{pc}]", "maintained": r4(m),
                         "min_numerator": min(c["numerator"] for c in cs),
                         "n_group_2018": cs[-1]["n_group"],
                         "passes_lift_and_num": bool(m >= LIFT_LINE
                                                     and min(c["numerator"] for c in cs) >= MIN_NUM)})
    part.sort(key=lambda x: -(x["maintained"] or 0))
    n_ok = sum(1 for x in part if x["passes_lift_and_num"])
    rank_aturn = next((i + 1 for i, x in enumerate(part)
                       if x["partner"] == f"{A_VAR}[{A_CUT}]"), None)
    diag["P_partner_interchangeability"] = {
        "seed_fixed": f"{B_VAR}[{B_CUT}]（P_quality）",
        "n_partner_cuts_tested": len(part),
        "n_partners_that_pass_lift_and_numerator": n_ok,
        "rank_of_aturn_among_partners": rank_aturn,
        "top12": part[:12],
        "aturn_row": next((x for x in part if x["partner"] == f"{A_VAR}[{A_CUT}]"), None),
        "note": "相手が何本も同じ線を越えるなら、効いているのは種のほうで、"
                "相手は『n を縮めて lift を持ち上げる』役をしているだけかもしれない。"
                "**その中から最良を選ぶ行為そのものが多重検定の値札**",
    }

    res["diagnostics_outside_prereg"] = diag

    json.dump(res, open(DEST, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"verdict": res["verdict"], "dest": DEST}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
