# -*- coding: utf-8 -*-
"""角度D の候補「全20本の加法スコア score>=12 / >=13」を潰しにかかる（6検問）。

候補（探索側 out/hist10_angleD.json の記述）:
    母集団 P_full ／ 部分集合 all20（f2_ の20本）の complete-case ／ 二値化=各ビンテージの中央値
    向きは **2016 のラベルから決める**（変種T）。J=20（全部使う＝変数選択ゼロ）。群は score>=s。
    s=12 → 探索側は「業種調整で不合格」
    s=13 → 2018 で n=27・分子=20・lift=0.303、探索側は「増分が測定不能で判定不能」

この道具は **hist10_diag / hist10_angleD を一行も import しない**。
panel と targets を自分で読み、中央値・向き・スコア・群・lift・MH・置換をすべて自前で組む。
食い違いが出たらそれ自体が発見なので、境界の約束（>= か >）まで振って比べる。

判定・採点・台帳・index.html・パックには一切触らない（読むだけ）。
出力: out/hist10_verify_addscore20.json
"""
import json
import math
import random
import sys
from collections import defaultdict

PANEL = "out/hist_wd_panel.json"
TARGETS = "out/hist10_targets.json"
PREREG = "out/hist10_prereg.json"
OUT = "out/hist10_verify_addscore20.json"

TRIO = (2016, 2017, 2018)
DISC = 2016                     # 変種T: 向きは2016で決める
HURDLE = 0.10                   # y10 の線（prereg。新しい定数を作らない）
LIFT = 0.15                     # prereg
MIN_NUM = 20                    # prereg
MAX_CAUGHT = 0.70               # prereg
N_PERM = 2000                   # prereg「置換2000回」
SEED = 20260812

F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r",
      "gw_r", "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5",
      "conv5", "netiss_r", "payout5", "rev"]
COLS = ["f2_" + k for k in F2]


# ───────────────────────────── 小道具（自前） ─────────────────────────────
def r4(x):
    return None if x is None else round(x, 4)


def med_of(xs):
    """中央値。偶数個は2点の平均（線形補間の q=0.5 と同じ）。"""
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    i = 0.5 * (n - 1)
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (i - lo)


def popcount(x):
    return bin(x).count("1")


def spearman(a, b):
    n = len(a)
    if n < 3:
        return None

    def rk(v):
        idx = sorted(range(n), key=lambda i: v[i])
        rr = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for t in range(i, j + 1):
                rr[idx[t]] = avg
            i = j + 1
        return rr
    ra, rb = rk(a), rk(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((x - mb) ** 2 for x in rb))
    return None if da == 0 or db == 0 else num / (da * db)


# ───────────────────────────── 読み込み（自前の join） ─────────────────────────────
def load():
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
        q["y10"] = t.get("y10")
        rows.append(q)
    return panel, tg, rows


def universe(rows, v):
    """all20 / P_full / vintage v の complete-case。ticker 昇順（探索側と同じ並び）。"""
    rs = [r for r in rows
          if r["vintage"] == v and r.get("P_full") is True
          and r.get("y10") is not None
          and all(r.get(c) is not None for c in COLS)]
    return sorted(rs, key=lambda r: r["ticker"])


def y10_check(rows):
    """y10 が『tr_cagr>=0.10』であることを自分で確かめる（在庫のラベルを鵜呑みにしない）。"""
    bad = 0
    n = 0
    for r in rows:
        if r.get("y10") is None or r.get("tr_cagr") is None:
            continue
        n += 1
        if bool(r["y10"]) != (r["tr_cagr"] >= HURDLE - 1e-12):
            bad += 1
    return {"n_checked": n, "n_mismatch": bad,
            "note": "y10 = tr_cagr>=0.10 を panel の tr_cagr から自前で再計算して照合"}


# ───────────────────────────── スコアの構成 ─────────────────────────────
def hi_masks(rs, boundary=">="):
    """各列の『上側』bitmask。中央値はこのビンテージのコホート内で取り直す。"""
    n = len(rs)
    out = {}
    for c in COLS:
        xs = [r[c] for r in rs]
        m = med_of(xs)
        h = 0
        for i, r in enumerate(rs):
            ok = (r[c] >= m) if boundary == ">=" else (r[c] > m)
            if ok:
                h |= (1 << i)
        out[c] = h
    return out, n


def label_mask(rs):
    lm = 0
    k = 0
    for i, r in enumerate(rs):
        if r["y10"]:
            lm |= (1 << i)
            k += 1
    return lm, len(rs), k


def sides_from(lmD, hiD, nD):
    """発見年のラベルで各列の『良い側』を決める。lift>=0 なら hi、そうでなければ lo。"""
    fullD = (1 << nD) - 1
    base = popcount(lmD) / nD
    sd = {}
    lifts = {}
    for c in COLS:
        h = hiD[c]
        mh = popcount(h)
        if mh == 0 or mh == nD:
            sd[c] = "hi"
            lifts[c] = 0.0
            continue
        lf = popcount(lmD & h) / mh - base
        sd[c] = "hi" if lf >= 0 else "lo"
        lifts[c] = lf
    return sd, lifts, base


def good_masks(hi, n, sd):
    full = (1 << n) - 1
    return {c: (hi[c] if sd[c] == "hi" else (full & ~hi[c])) for c in COLS}


def score_vec(gm, n):
    """各行の『良い側に入った本数』。bit-plane ではなく素直に数える（独立実装）。"""
    sc = [0] * n
    for c in COLS:
        g = gm[c]
        i = 0
        x = g
        while x:
            if x & 1:
                sc[i] += 1
            x >>= 1
            i += 1
    return sc


def group_mask(sc, s, n):
    g = 0
    for i in range(n):
        if sc[i] >= s:
            g |= (1 << i)
    return g


# ───────────────────────────── 検問①〜⑥ ─────────────────────────────
def cell(rs, lm, n, k_all, gmask):
    m = popcount(gmask)
    k = popcount(lm & gmask)
    base = k_all / n if n else None
    return {"n_universe": n, "base": r4(base), "m_group": m, "k_group": k,
            "p_group": r4(k / m) if m else None,
            "lift": r4(k / m - base) if m else None}


def mh(rs, gset, ykey="y10"):
    """Mantel-Haenszel 重み付きリスク差 ＋ その調整が群の何割を見ているか。"""
    rr = [r for r in rs if r.get("sic2") and r.get(ykey) is not None]
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for r in rr:
        d = strata[r["sic2"]]
        w = 1 if r[ykey] else 0
        if r["ticker"] in gset:
            d[0] += 1
            d[1] += w
        else:
            d[2] += 1
            d[3] += w
    num = den = 0.0
    used = drop = 0
    g_used = g_drop = 0
    for _s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            g_drop += n1
            continue
        w = n1 * n0 / (n1 + n0)
        num += w * (k1 / n1 - k0 / n0)
        den += w
        used += 1
        g_used += n1
    return {"mh_risk_diff": r4(num / den) if den else None,
            "strata_used": used, "strata_dropped": drop,
            "group_in_used_strata": g_used, "group_in_dropped_strata": g_drop,
            "share_of_group_covered": r4(g_used / (g_used + g_drop)) if (g_used + g_drop) else None}


def drop_one_sector(rs, gset, ykey="y10", min_bg=40, min_grp=10):
    """業種を1つずつ抜く。探索側と同じ足切り(min_grp=10)と、足切り無しの厳しい版の両方。"""
    rr = [r for r in rs if r.get(ykey) is not None]
    secs = sorted({r.get("sic2") for r in rr if r.get("sic2")})
    res = []
    skipped = []
    for dr in secs:
        RR = [r for r in rr if r.get("sic2") != dr]
        nb = len(RR)
        if nb < min_bg:
            skipped.append({"sector": dr, "why": "背景 %d < %d" % (nb, min_bg)})
            continue
        kb = sum(1 for r in RR if r[ykey])
        grp = [r for r in RR if r["ticker"] in gset]
        if not grp:
            skipped.append({"sector": dr, "why": "群が空"})
            continue
        kg = sum(1 for r in grp if r[ykey])
        lf = kg / len(grp) - kb / nb
        res.append({"dropped_sector": dr, "n_group": len(grp), "k": kg, "lift": r4(lf),
                    "below_group_floor": len(grp) < min_grp})
    if not res:
        return {"status": "算出不能", "skipped": skipped}
    with_floor = [x for x in res if not x["below_group_floor"]]
    worst_wf = min(with_floor, key=lambda x: abs(x["lift"])) if with_floor else None
    worst_all = min(res, key=lambda x: abs(x["lift"]))
    return {"worst_with_discovery_floor": worst_wf,
            "worst_no_floor": worst_all,
            "n_sectors_evaluated": len(res),
            "n_exempted_by_group_floor": len(res) - len(with_floor),
            "all": sorted(res, key=lambda x: abs(x["lift"]))[:6]}


# 既存の門の関門（歴史側の相当物）。角度A/D と同一定義（規則を作り替えない）
def g_shrink(r):
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def g_thin(r):
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def g_notq(r):
    return not r.get("P_quality")


def g_blocked(r):
    return g_shrink(r) or g_thin(r) or g_notq(r)


def incremental(rs, gset, ykey="y10"):
    """増分を3つの読みで測る（どれか一つに黙って倒さない）。"""
    rr = [r for r in rs if r.get(ykey) is not None]
    grp = [r for r in rr if r["ticker"] in gset]
    keep = [r for r in rr if not g_blocked(r)]
    g_keep = [r for r in grp if not g_blocked(r)]
    winners = [r for r in grp if r[ykey]]
    # 読み1: 既存関門を通る社だけに絞って測り直した lift（探索側の実装）
    read1 = {"n_rows": len(rr), "n_keep": len(keep),
             "n_group": len(grp), "n_group_after_gates": len(g_keep),
             "share_of_group_already_blocked": r4(1 - len(g_keep) / len(grp)) if grp else None}
    if len(g_keep) >= 10 and len(keep) >= 40:
        base = sum(1 for r in keep if r[ykey]) / len(keep)
        k = sum(1 for r in g_keep if r[ykey])
        read1.update({"k": k, "base": r4(base), "lift": r4(k / len(g_keep) - base)})
    else:
        read1["status"] = ("群 %d 社のうち既存関門を通るのは %d 社で、門の中では測れない"
                           % (len(grp), len(g_keep)))
    # 読み2: prereg の字義「既存の関門で説明される社が7割を超えたら不合格」を
    #        『群の10%+を出した社が、門の admissible set の外にいるか』で読む
    w_blocked = sum(1 for r in winners if g_blocked(r))
    read2 = {"n_winners_in_group": len(winners), "winners_blocked_by_existing": w_blocked,
             "share": r4(w_blocked / len(winners)) if winners else None,
             "line": MAX_CAUGHT,
             "note": "門が既に落としている社が7割を超えるなら、この群は門の中では買えない"}
    # 読み3: 関門ごとの内訳
    def sh(f):
        return r4(sum(1 for r in grp if f(r)) / len(grp)) if grp else None
    read3 = {"share_group_notP_quality": sh(g_notq), "share_group_shrink": sh(g_shrink),
             "share_group_thin": sh(g_thin), "share_group_any": sh(g_blocked),
             "share_universe_any": r4(sum(1 for r in rr if g_blocked(r)) / len(rr)) if rr else None}
    return {"read1_within_gate_passers": read1, "read2_winners_outside_gate": read2,
            "read3_breakdown": read3}


def irr_layer(rs, gset, sc_by_ticker, ykey="y10"):
    rr = [r for r in rs if r.get("irr") is not None and r.get(ykey) is not None]
    out = {"n_with_irr": len(rr)}
    if len(rr) < 20:
        out["status"] = "irr の読解が %d 行しかなく判定不能" % len(rr)
        return out
    out["corr_score_vs_irr_spearman"] = r4(spearman([sc_by_ticker[r["ticker"]] for r in rr],
                                                    [float(r["irr"]) for r in rr]))
    hi = [r for r in rr if r["irr"] >= 70]
    out["n_irr_ge70"] = len(hi)
    if len(hi) < 20:
        out["irr_ge70"] = {"status": "irr>=70 が %d 行で判定不能（分子>=20 に構造的に届かない）"
                                     % len(hi)}
        return out
    base = sum(1 for r in hi if r[ykey]) / len(hi)
    g = [r for r in hi if r["ticker"] in gset]
    out["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g),
                       "k": sum(1 for r in g if r[ykey]),
                       "lift": r4(sum(1 for r in g if r[ykey]) / len(g) - base) if g else None}
    return out


# ───────────────────────────── 置換（会社単位・全ビンテージ同時） ─────────────────────────────
def perm_labels(rows, seed=SEED):
    """sic2 の層内で会社を入れ替え、その会社のラベルを**全ビンテージまとめて**移す。"""
    rnd = random.Random(seed)
    full = {v: [r for r in rows if r["vintage"] == v and r.get("P_full") is True
                and r.get("y10") is not None] for v in TRIO}
    lab = {v: {r["ticker"]: (1 if r["y10"] else 0) for r in full[v]} for v in TRIO}
    sic = {}
    for v in TRIO:
        for r in full[v]:
            sic[r["ticker"]] = r.get("sic2")
    common = set(lab[2016]) & set(lab[2017]) & set(lab[2018])
    by_sic = defaultdict(list)
    for t in sorted(common):
        by_sic[sic[t]].append(t)
    solo = {v: defaultdict(list) for v in TRIO}
    for v in TRIO:
        for t in lab[v]:
            if t not in common:
                solo[v][sic[t]].append(t)

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
    return draw, {"n_common_tickers": len(common), "n_strata": len(by_sic)}


def stat_for_disc(labs, U, HI, S_LIST, disc):
    """置換ラベルから、この手続きが出す統計量を作り直す（向きも作り直す）。"""
    n = {v: len(U[v]) for v in TRIO}
    lm = {}
    kk = {}
    for v in TRIO:
        m = 0
        c = 0
        lv = labs[v]
        for i, r in enumerate(U[v]):
            if lv.get(r["ticker"]):
                m |= (1 << i)
                c += 1
        lm[v] = m
        kk[v] = c
    sd, _lf, _b = sides_from(lm[disc], HI[disc], n[disc])
    out = {}
    for s in S_LIST:
        per = {}
        for v in TRIO:
            gm = good_masks(HI[v], n[v], sd)
            sc = score_vec(gm, n[v])
            g = group_mask(sc, s, n[v])
            m = popcount(g)
            k = popcount(lm[v] & g)
            base = kk[v] / n[v]
            per[v] = {"m": m, "k": k, "lift": (k / m - base) if m else None, "base": base}
        out[s] = per
    return out


def stat_for(labs, U, HI, S_LIST):
    return stat_for_disc(labs, U, HI, S_LIST, DISC)


def gate1_ok(per):
    """探索側の gate1 と同じ判定（群>=20・分子>=20・|lift|>=0.15・3年で符号不変）。"""
    up = None
    for v in TRIO:
        d = per[v]
        if d["m"] < MIN_NUM or d["m"] >= 10 ** 9 or d["lift"] is None:
            return False
        if d["k"] < MIN_NUM or abs(d["lift"]) < LIFT:
            return False
        if up is None:
            up = d["lift"] > 0
        elif (d["lift"] > 0) != up:
            return False
    return True


# ───────────────────────────── main ─────────────────────────────
def main():
    panel, tg, rows = load()
    U = {v: universe(rows, v) for v in TRIO}
    out = {
        "generated": "2026-08-12",
        "tool": "night/hist10_verify_addscore20.py",
        "prereg": PREREG,
        "candidate": {
            "angle": "D — 全20本の加法スコア（変数選択ゼロ・向きだけ2016で決定）",
            "pop": "P_full", "subset": "all20", "binarize": "median(各ビンテージのコホート内)",
            "discovery_vintage": DISC, "J": 20, "s": [12, 13], "mode": "ge",
            "claimed_2018": {"n_group": 27, "k": 20, "lift": 0.303},
            "discovery_verdict": {"s12": "不合格(業種調整)", "s13": "判定不能(増分が測れない)"},
        },
        "independence": "hist10_diag / hist10_angleD を import していない。panel と targets だけを読む",
        "y10_selfcheck": y10_check(rows),
        "universe": {str(v): {"n": len(U[v]),
                              "k_y10": sum(1 for r in U[v] if r["y10"]),
                              "base": r4(sum(1 for r in U[v] if r["y10"]) / len(U[v]))}
                     for v in TRIO},
    }

    # ── 検問1 再現（境界の約束まで振る） ──
    rep = {}
    for boundary in (">=", ">"):
        HI = {}
        NN = {}
        for v in TRIO:
            HI[v], NN[v] = hi_masks(U[v], boundary)
        lmD, nD, kD = label_mask(U[DISC])
        sd, lfD, baseD = sides_from(lmD, HI[DISC], nD)
        per_s = {}
        for s in (11, 12, 13, 14):
            per_v = {}
            for v in TRIO:
                lm, n, k_all = label_mask(U[v])
                gm = good_masks(HI[v], n, sd)
                sc = score_vec(gm, n)
                g = group_mask(sc, s, n)
                per_v[str(v)] = cell(U[v], lm, n, k_all, g)
            per_s[str(s)] = per_v
        rep[boundary] = {"sides": {c: sd[c] for c in COLS},
                         "abs_lift_at_disc": {c: r4(abs(lfD[c])) for c in COLS},
                         "by_s": per_s}
    # 主実装は ">=" （探索側の約束）
    HI = {}
    NN = {}
    for v in TRIO:
        HI[v], NN[v] = hi_masks(U[v], ">=")
    lmD, nD, kD = label_mask(U[DISC])
    SD, LFD, BASED = sides_from(lmD, HI[DISC], nD)

    claim = rep[">="]["by_s"]["13"]["2018"]
    rep["match_with_discovery"] = {
        "s13_2018_mine": {"m": claim["m_group"], "k": claim["k_group"], "lift": claim["lift"]},
        "s13_2018_discovery": {"m": 27, "k": 20, "lift": 0.303},
        "identical": (claim["m_group"] == 27 and claim["k_group"] == 20
                      and abs(claim["lift"] - 0.303) < 5e-4),
        "boundary_sensitivity": {
            "note": "中央値ちょうどの行をどちらへ入れるかで群が変わるか",
            "s13_2018_with_gt": {k: rep[">"]["by_s"]["13"]["2018"][k]
                                 for k in ("m_group", "k_group", "lift")},
            "sides_flipped_by_boundary": [c for c in COLS
                                          if rep[">="]["sides"][c] != rep[">"]["sides"][c]],
        },
    }
    out["attack1_reproduce"] = rep

    # ── スコアの中身（この候補の性格を見る） ──
    weak = [c for c in COLS if abs(LFD[c]) < 0.05]
    out["what_the_score_actually_counts"] = {
        "sides_chosen_at_2016": {c: SD[c] for c in COLS},
        "abs_lift_at_2016": {c: r4(abs(LFD[c])) for c in COLS},
        "n_sides_with_abs_lift_below_0.05": len(weak),
        "coin_flip_sides": weak,
        "sides_that_point_at_low_quality": {c: SD[c] for c in
                                            ("f2_opm", "f2_gm", "f2_fcfpos5", "f2_opmD5",
                                             "f2_conv5", "f2_intcov", "f2_streak_opm",
                                             "f2_streak_rev", "f2_aturn")},
        "why_it_matters": "『美点の数』という名前だが、向きはラベルから当てた結果であって"
                          "美点の定義ではない。低い営業利益率・低いFCF転換・利益率の低下が"
                          "『美点』に数えられていれば、その群は門の質実証と正面から衝突する",
    }

    # ── 群の実体 ──
    gsets = {}
    scs = {}
    for v in TRIO:
        lm, n, k_all = label_mask(U[v])
        gm = good_masks(HI[v], n, SD)
        sc = score_vec(gm, n)
        scs[v] = {U[v][i]["ticker"]: sc[i] for i in range(n)}
        gsets[v] = {13: {U[v][i]["ticker"] for i in range(n) if sc[i] >= 13},
                    12: {U[v][i]["ticker"] for i in range(n) if sc[i] >= 12}}
    out["group_membership"] = {}
    for s in (12, 13):
        ov = {}
        for v in TRIO:
            ov[str(v)] = sorted(gsets[v][s])
        a, b, c = gsets[2016][s], gsets[2017][s], gsets[2018][s]
        out["group_membership"]["s%d" % s] = {
            "tickers_by_vintage": ov,
            "n_by_vintage": {str(v): len(gsets[v][s]) for v in TRIO},
            "in_all_three": sorted(a & b & c),
            "n_in_all_three": len(a & b & c),
            "jaccard_2016_2018": r4(len(a & c) / len(a | c)) if (a | c) else None,
            "sector_mix_2018": dict(sorted(
                ((k, v2) for k, v2 in
                 __import__("collections").Counter(
                     r["sic2"] for r in U[2018] if r["ticker"] in c).items()),
                key=lambda x: -x[1])),
        }

    # ── 検問2 ビンテージ ──
    v2 = {}
    for s in (12, 13):
        lifts = {str(v): rep[">="]["by_s"][str(s)][str(v)]["lift"] for v in TRIO}
        ks = {str(v): rep[">="]["by_s"][str(s)][str(v)]["k_group"] for v in TRIO}
        ms = {str(v): rep[">="]["by_s"][str(s)][str(v)]["m_group"] for v in TRIO}
        ok = all(x is not None and abs(x) >= LIFT for x in lifts.values()) and \
            len({x > 0 for x in lifts.values()}) == 1
        numok = all(x >= MIN_NUM for x in ks.values()) and all(x >= MIN_NUM for x in ms.values())
        v2["s%d" % s] = {"lift": lifts, "k": ks, "m": ms,
                         "lift_ok": ok, "min_numerator_ok": numok,
                         "verdict": "通る" if (ok and numok) else "落ちる",
                         "margin_to_min_numerator": {kk: vv - MIN_NUM for kk, vv in ks.items()}}
    out["attack2_vintages"] = v2

    # ── 検問3 業種 ──
    a3 = {}
    for s in (12, 13):
        per = {}
        for v in TRIO:
            gset = gsets[v][s]
            per[str(v)] = {"mh": mh(U[v], gset), "drop_one": drop_one_sector(U[v], gset)}
        mh_ok = all(per[str(v)]["mh"]["mh_risk_diff"] is not None
                    and per[str(v)]["mh"]["mh_risk_diff"] >= LIFT for v in TRIO)
        d_wf = [per[str(v)]["drop_one"].get("worst_with_discovery_floor") for v in TRIO]
        d_nf = [per[str(v)]["drop_one"].get("worst_no_floor") for v in TRIO]
        dwf_ok = all(x and x["lift"] is not None and x["lift"] >= LIFT for x in d_wf)
        dnf_ok = all(x and x["lift"] is not None and x["lift"] >= LIFT for x in d_nf)
        a3["s%d" % s] = {"by_vintage": per, "mh_ok": mh_ok,
                         "drop_one_ok_with_discovery_floor": dwf_ok,
                         "drop_one_ok_without_floor": dnf_ok,
                         "verdict": "通る" if (mh_ok and dwf_ok) else "落ちる"}
    out["attack3_sector"] = a3

    # ── 検問4 irr の層 ──
    a4 = {}
    for s in (12, 13):
        a4["s%d" % s] = {str(v): irr_layer(U[v], gsets[v][s], scs[v]) for v in TRIO}
    out["attack4_irr"] = a4

    # ── 検問6 増分 ──
    a6 = {}
    for s in (12, 13):
        a6["s%d" % s] = {str(v): incremental(U[v], gsets[v][s]) for v in TRIO}
    out["attack6_incremental"] = a6

    # ── 検問6 追補: 候補にいちばん有利な形（門の中で s を下げてでも効くか） ──
    best = {}
    for v in TRIO:
        keep = [r for r in U[v] if not g_blocked(r)]
        lm, n, k_all = label_mask(U[v])
        gm = good_masks(HI[v], n, SD)
        sc = score_vec(gm, n)
        sm = {U[v][i]["ticker"]: sc[i] for i in range(n)}
        base = sum(1 for r in keep if r["y10"]) / len(keep)
        row = {}
        for s in range(6, 15):
            g = [r for r in keep if sm[r["ticker"]] >= s]
            if not g:
                continue
            k = sum(1 for r in g if r["y10"])
            row[str(s)] = {"m": len(g), "k": k, "lift": r4(k / len(g) - base),
                           "lift_ok": abs(k / len(g) - base) >= LIFT, "min_num_ok": k >= MIN_NUM}
        best[str(v)] = {"n_gate_passers": len(keep), "base": r4(base), "by_s": row}
    out["attack6_best_case_within_gate"] = {
        "why": "増分が『測れない』のは s=13 が高すぎるからかもしれない。門を通る社の中で"
               "s を下げてでも prereg の線（lift>=0.15 ∧ 分子>=20）を同時に満たす s があるかを探す",
        "by_vintage": best}

    # ── 中央値の同値（>= と > の食い違いの正体） ──
    ties = {}
    for v in TRIO:
        t = {}
        for c in COLS:
            xs = [r[c] for r in U[v]]
            m = med_of(xs)
            nt = sum(1 for x in xs if x == m)
            if nt > 2:
                t[c] = {"median": m, "n_at_median": nt, "share": r4(nt / len(xs))}
        ties[str(v)] = t
    # 「中央値分割」が実際に何対何で割れているか＋整数3本を外した版
    split = {}
    for v in TRIO:
        n = len(U[v])
        split[str(v)] = {c: {"hi_share": r4(popcount(HI[v][c]) / n),
                             "fitted_side": SD[c],
                             "share_with_the_virtue": r4((popcount(HI[v][c]) if SD[c] == "hi"
                                                          else n - popcount(HI[v][c])) / n)}
                         for c in COLS if abs(popcount(HI[v][c]) / n - 0.5) > 0.08}
    INT3 = ["f2_streak_rev", "f2_streak_opm", "f2_fcfpos5"]
    sub = [c for c in COLS if c not in INT3]
    abl = {}
    for v in TRIO:
        n = len(U[v])
        lm, _n, k_all = label_mask(U[v])
        full = (1 << n) - 1
        gm = {c: (HI[v][c] if SD[c] == "hi" else full & ~HI[v][c]) for c in sub}
        sc = [0] * n
        for c in sub:
            g = gm[c]
            for i in range(n):
                if (g >> i) & 1:
                    sc[i] += 1
        row = {}
        for s in range(9, 15):
            idx = [i for i in range(n) if sc[i] >= s]
            if not idx:
                continue
            k = sum(1 for i in idx if U[v][i]["y10"])
            row[str(s)] = {"m": len(idx), "k": k, "lift": r4(k / len(idx) - k_all / n),
                           "min_num_ok": k >= MIN_NUM}
        abl[str(v)] = row
    out["not_a_median_split"] = {
        "why": "整数の列は中央値に塊があるので『中央値で二値化』が 50:50 にならない。"
               "78:22 で割れている列の向きを当てはめるのは、中央値分割ではなく閾値の当てはめ",
        "columns_far_from_50_50": split,
        "drop_the_three_integer_columns": {
            "cols_dropped": INT3, "by_vintage": abl,
            "read": "外しても形は残るが、分子>=20 を満たす s では lift が 0.15 前後まで落ちる"},
    }
    out["median_ties"] = {
        "why": "中央値ちょうどの行をどちらへ入れるかは実装の約束であって仮説ではない。"
               "整数の列（連続年数・黒字年数）は中央値に大きな塊があるので、約束を替えると群が入れ替わる",
        "by_vintage": ties}

    # ── 検問5 置換 ──
    draw, pinfo = perm_labels(rows)
    S_LIST = [12, 13]
    obs = stat_for(draw(False), U, HI, S_LIST)
    # 統計量: (a) 3年の |lift| の最小 (b) 発見年を除く2年の最小 (c) gate1 を通るか
    def stats(o, s):
        per = o[s]
        li = [per[v]["lift"] for v in TRIO]
        if any(x is None for x in li):
            return None, None, False
        return (min(abs(x) for x in li),
                min(abs(per[v]["lift"]) for v in (2017, 2018)),
                gate1_ok(per))
    obs_st = {s: stats(obs, s) for s in S_LIST}
    ge_all = {s: 0 for s in S_LIST}
    ge_out = {s: 0 for s in S_LIST}
    n_g1 = {s: 0 for s in S_LIST}
    fam_any = 0
    null_all = {s: [] for s in S_LIST}
    null_out = {s: [] for s in S_LIST}
    for _ in range(N_PERM):
        labs = draw(True)
        o = stat_for(labs, U, HI, list(range(1, 21)))
        any_pass = False
        for s in range(1, 21):
            if gate1_ok(o[s]):
                any_pass = True
                break
        if any_pass:
            fam_any += 1
        for s in S_LIST:
            a, b, g = stats(o, s)
            if a is None:
                continue
            null_all[s].append(a)
            null_out[s].append(b)
            if obs_st[s][0] is not None and a >= obs_st[s][0] - 1e-12:
                ge_all[s] += 1
            if obs_st[s][1] is not None and b >= obs_st[s][1] - 1e-12:
                ge_out[s] += 1
            if g:
                n_g1[s] += 1
    # 族の偽陽性率に **発見年の選択** も入れる（disc=2016 は2つの候補から選ばれている）
    fam_any_disc = 0
    rnd2 = random.Random(SEED + 77)
    draw2, _pi = perm_labels(rows, seed=SEED + 77)
    for _ in range(N_PERM):
        labs = draw2(True)
        hit = False
        for dsc in (2016, 2018):
            o = stat_for_disc(labs, U, HI, list(range(1, 21)), dsc)
            for s in range(1, 21):
                if gate1_ok(o[s]):
                    hit = True
                    break
            if hit:
                break
        if hit:
            fam_any_disc += 1

    a5 = {"design": "会社単位・sic2 層内・全ビンテージ同時に y10 を入れ替え、"
                    "**置換のたびに向きも2016から作り直す**（向きの当てはめを帰無に含める）",
          "n_perm": N_PERM, "perm_info": pinfo}
    for s in S_LIST:
        d = sorted(null_all[s])
        do = sorted(null_out[s])
        a5["s%d" % s] = {
            "observed_min_abs_lift_3v": r4(obs_st[s][0]),
            "p_one_sided_3v": r4((ge_all[s] + 1) / (N_PERM + 1)),
            "null_p95_3v": r4(d[int(0.95 * (len(d) - 1))]) if d else None,
            "observed_min_abs_lift_excl_disc": r4(obs_st[s][1]),
            "p_one_sided_excl_disc": r4((ge_out[s] + 1) / (N_PERM + 1)),
            "null_p95_excl_disc": r4(do[int(0.95 * (len(do) - 1))]) if do else None,
            "fpr_this_exact_config_gate1": r4(n_g1[s] / N_PERM),
        }
    a5["fpr_family_any_s_1to20_gate1"] = r4(fam_any / N_PERM)
    a5["fpr_family_any_s_and_any_discovery_year"] = r4(fam_any_disc / N_PERM)
    a5["note_on_family"] = ("この候補は『変数選択ゼロ』を弁にするが、s（何本以上を良しとするか）は"
                           "1..20 から選ばれている。族としての偽陽性率はそれを含めて数える")
    out["attack5_permutation"] = a5

    # ── 追加: 発見年を替えたら生き残るか（向きの当てはめの安定性） ──
    alt = {}
    for disc in TRIO:
        lmA, nA, _k = label_mask(U[disc])
        sdA, lfA, _b = sides_from(lmA, HI[disc], nA)
        agree = sum(1 for c in COLS if sdA[c] == SD[c])
        per_s = {}
        for s in (12, 13):
            pv = {}
            for v in TRIO:
                lm, n, k_all = label_mask(U[v])
                gm = good_masks(HI[v], n, sdA)
                sc = score_vec(gm, n)
                g = group_mask(sc, s, n)
                pv[str(v)] = cell(U[v], lm, n, k_all, g)
            per_s[str(s)] = pv
        g1 = {}
        for s in (12, 13):
            pv = {v: {"m": per_s[str(s)][str(v)]["m_group"],
                      "k": per_s[str(s)][str(v)]["k_group"],
                      "lift": per_s[str(s)][str(v)]["lift"]} for v in TRIO}
            g1[str(s)] = gate1_ok(pv)
        alt[str(disc)] = {"sides_agree_with_2016": agree, "of": len(COLS),
                          "flipped_cols": [c for c in COLS if sdA[c] != SD[c]],
                          "flipped_abs_lift_at_2016": {c: r4(abs(LFD[c])) for c in COLS
                                                       if sdA[c] != SD[c]},
                          "gate1_ok": g1, "by_s": per_s}
    out["direction_stability"] = {
        "why": "『向きだけ2016で決定』は自由度ゼロではない——20本の向きは2^20 の当てはめ。"
               "発見年を替えて向きが入れ替わるなら、その向きはラベルの雑音を写している",
        "by_discovery_vintage": alt}

    # ── 追加: 候補の弁「変数選択ゼロ＝数そのものが働いている」を正面から試す ──
    # 向きを **データから当てず、経済的な意味で先に決めた**『本物の美点の数』。
    # これが働くなら「数そのもの」は本物。働かないなら、効いていたのは数ではなく
    # 20本の向きの当てはめ（2^20 の自由度）である。
    APRIORI = {"f2_gm": "hi", "f2_sga_r": "lo", "f2_capex_r": "lo", "f2_rnd_r": "hi",
               "f2_opm": "hi", "f2_intcov": "hi", "f2_aturn": "hi", "f2_accr": "lo",
               "f2_cash_r": "hi", "f2_gw_r": "lo", "f2_cagr5": "hi", "f2_accel": "hi",
               "f2_streak_rev": "hi", "f2_streak_opm": "hi", "f2_opmD5": "hi",
               "f2_fcfpos5": "hi", "f2_conv5": "hi", "f2_netiss_r": "lo",
               "f2_payout5": "lo", "f2_rev": "hi"}
    APRIORI_ALT = dict(APRIORI)
    APRIORI_ALT["f2_payout5"] = "hi"      # 還元性向は門の中で両論あるので裏返した版も出す
    apri = {}
    for tag, sd_ap in (("apriori", APRIORI), ("apriori_payout_hi", APRIORI_ALT)):
        per_s = {}
        for s in (11, 12, 13, 14):
            pv = {}
            for v in TRIO:
                lm, n, k_all = label_mask(U[v])
                gm = good_masks(HI[v], n, sd_ap)
                sc = score_vec(gm, n)
                g = group_mask(sc, s, n)
                pv[str(v)] = cell(U[v], lm, n, k_all, g)
            per_s[str(s)] = pv
        apri[tag] = {"agree_with_fitted_2016": sum(1 for c in COLS if sd_ap[c] == SD[c]),
                     "of": len(COLS),
                     "disagree_cols": [c for c in COLS if sd_ap[c] != SD[c]],
                     "by_s": per_s}
    out["apriori_virtues"] = {
        "why": "候補の最大の肯定的発見は『選択の自由度をゼロにしても線を越える』だった。"
               "ならば向きも当てずに、意味で先に決めた本物の美点の数で同じことが起きるはず",
        "directions": APRIORI, "result": apri}

    # ── 追加: スコアが高いほど門の関門に落ちるのか（増分の機構） ──
    mech = {}
    for v in TRIO:
        lm, n, k_all = label_mask(U[v])
        gm = good_masks(HI[v], n, SD)
        sc = score_vec(gm, n)
        by = defaultdict(lambda: [0, 0, 0])
        for i, r in enumerate(U[v]):
            b = by[sc[i]]
            b[0] += 1
            if g_blocked(r):
                b[1] += 1
            if r["y10"]:
                b[2] += 1
        tbl = {str(k): {"n": x[0], "blocked": x[1],
                        "blocked_share": r4(x[1] / x[0]),
                        "p_y10": r4(x[2] / x[0])} for k, x in sorted(by.items())}
        xs = [sc[i] for i in range(n)]
        ys = [1.0 if g_blocked(U[v][i]) else 0.0 for i in range(n)]
        mech[str(v)] = {"by_score": tbl, "spearman_score_vs_blocked": r4(spearman(xs, ys))}
    out["mechanism_score_vs_gate"] = {
        "why": "増分が測れない理由を機構で示す。スコアの向きが門の質実証と逆を向いているなら、"
               "スコアが高い社ほど門が落とす社になる", "by_vintage": mech}

    # ── 追加: s の刻みは崖か（単調な信号なら s を1つ動かしても壊れない） ──
    curve = {}
    rowcorr = {}
    for v in TRIO:
        lm, n, k_all = label_mask(U[v])
        gm = good_masks(HI[v], n, SD)
        sc = score_vec(gm, n)
        rowcorr[str(v)] = r4(spearman(sc, [1.0 if U[v][i]["y10"] else 0.0 for i in range(n)]))
        row = {}
        for s in range(8, 17):
            g = group_mask(sc, s, n)
            row[str(s)] = cell(U[v], lm, n, k_all, g)
        curve[str(v)] = row
    out["s_curve"] = {"why": "本物の加法信号なら s を1段動かしても壊れない。"
                            "s=13 でだけ立つなら、それは崖であって信号ではない",
                      "by_vintage": curve,
                      "row_level_spearman_score_vs_y10": rowcorr}

    # ── 追加: 1社抜き（群が小さいので1社で動く） ──
    loo = {}
    for s in (12, 13):
        per = {}
        for v in TRIO:
            lm, n, k_all = label_mask(U[v])
            gm = good_masks(HI[v], n, SD)
            sc = score_vec(gm, n)
            idx = [i for i in range(n) if sc[i] >= s]
            base = k_all / n
            worst = None
            for i in idx:
                m2 = len(idx) - 1
                k2 = sum(1 for j in idx if j != i and U[v][j]["y10"])
                lf = k2 / m2 - base
                if worst is None or lf < worst["lift"]:
                    worst = {"dropped": U[v][i]["ticker"], "m": m2, "k": k2, "lift": r4(lf)}
            per[str(v)] = worst
        loo["s%d" % s] = per
    out["leave_one_out_worst"] = loo

    # ── 総括（線は prereg のまま。緩めた版は合否に数えない） ──
    def g13(key):
        return out[key]["s13"] if "s13" in out[key] else out[key]
    v13 = {
        "1_reproduce": {"ok": out["attack1_reproduce"]["match_with_discovery"]["identical"],
                        "note": "n=27・分子=20・lift=0.303 まで一致。ただし中央値ちょうどの行を"
                                "『>』側へ入れると 2018 は m=26・k=15・lift=0.139 へ崩れる"
                                "（分子も lift も prereg の線を割る）"},
        "2_vintages": {"ok": out["attack2_vintages"]["s13"]["verdict"] == "通る",
                       "note": "3年とも lift>=0.15。ただし 2018 の分子は 20 ちょうど＝線の上に載っている"},
        "3_sector": {"ok": out["attack3_sector"]["s13"]["verdict"] == "通る",
                     "note": "MH も業種1つ抜きも通る。ただし MH が見ているのは群の 52〜61% だけ"
                             "（3〜4 層／36〜41 層）"},
        "4_irr": {"ok": None,
                  "note": "判定不能。この complete-case に irr の読解は 2018 の 34 行しかなく、"
                          "irr>=70 は 17 行で prereg の分子>=20 に構造的に届かない"},
        "5_permutation": {"ok": True,
                          "note": "p=0.0025（発見年を除く2年）。**この検問は落とせなかった**。"
                                  "ただし手続きの偽陽性率は s の選択で 0.117、"
                                  "発見年の選択も入れると 0.20"},
        "6_incremental": {"ok": False,
                          "note": "群の 78〜81% を門が既に落としている。門を通る社は 5〜6 社で"
                                  "測れず（読み1＝探索側と同じ結論）、群の勝者の 74〜81% が"
                                  "門の外にいる（読み2＝prereg の字義で 7割超＝不合格）。"
                                  "門の中で s を下げても、lift>=0.15 と分子>=20 を同時に満たす s は無い"},
    }
    out["verdict"] = {
        "line": "prereg の全条件。1つでも欠ければ不合格（判定不能は合格ではない）",
        "s13": v13,
        "s13_result": "不合格",
        "s12_result": "不合格（業種調整。MH 2017=0.141・業種1つ抜き 2018=0.132 が 0.15 を割る）",
        "killed_by": ["6_incremental（門の中では使えない）",
                      "1_reproduce の境界感度（中央値の同値の扱いで 0.303→0.139）",
                      "向きの当てはめの不安定（発見年を替えると gate1 が落ちる）",
                      "『美点の数』ではない（意味で決めた向きだと lift 0.02〜0.14）"],
        "could_not_kill": ["5_permutation（p=0.0025）",
                           "3_sector（MH・業種1つ抜きとも通る。ただし被覆は群の半分）"],
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)
    return out


if __name__ == "__main__":
    o = main()
    # 画面の要約
    print("\n=== 検問1 再現 ===")
    print(json.dumps(o["attack1_reproduce"]["match_with_discovery"], ensure_ascii=False, indent=1))
    print("\n=== 検問2 ビンテージ ===")
    print(json.dumps(o["attack2_vintages"], ensure_ascii=False, indent=1))
