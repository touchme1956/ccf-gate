#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H5（トレンドの持続性）——opmD5<0 は次の窓でも opmD5<0 か。
事前登録: out/opm_trend_prereg.json の H5_persistence
土台:     out/opmtrend_base.json（自分で結合し直さない）
出力:     out/opmtrend_h5.json

★この器は「読むだけ」。out/*_gate_pack.json / index.html / night/score_all.js には触れない。

──────────────────────────────────────────────────────────────────────
★★ 判定の線（結果を1件も見る前にここへ固定する）★★

**事前登録の H5 には line が無い**（H1 は line あり／H3 は「H1と同じ線」／H4 は「H2と同じ」と
書いてあるのに、H5 だけ stat しか無い）。よって線を後から書くと「結果を見てから線を書く」ことになる。
そこで **この文書の中に唯一存在する lift の線（H1）をそのまま借りる**——他所から新しい定数を
持ち込まないため。借りものであることを出力にも報告にも明記する。

  primary_stat  : 事前登録の H5 の文言どおり  lift_base = P(次も opmD5<0 | 今 opmD5<0) − P(次も opmD5<0)
  secondary_stat: H1 と同じ形の対比          lift_contrast = P(次<0 | 今<0) − P(次<0 | 今>=0)
                  （lift_base = (1-f)·lift_contrast なので約2倍ちがう。両方を別々に裁いて両方報告する）
  line          : lift >= 0.15 かつ **すべての対で符号が同じ**（H1 から借用）
  pools         : 全社 / 質実証（H1 と同じ2プール。qual は **now 側のビンテージ**で評価する
                  ＝当時その社を質実証と判定したかどうか、が意思決定の順序だから）
  pairs         : 2013->2018 / 2016->2021 / 2017->2022（opmD5 は5会計年度窓なので5年離す）

到達可能性（結果の前に数える・v1/v3/v11 の失敗を四度目にしない）:
  lift_base の上限 = 1 − base（今<0 の社が全員 次<0 なら）。これが 0.15 未満のセルは **判定不能**。
  n(今<0) = 0 のセルも判定不能。

対照（仮説ではない・器が壊れていないかの検査）:
  L1 opm(水準) の持続性——「水準は持続するが変化は持続しない」という仮説の検定
  L2 rev(売上規模) の順位相関——同じ会社を突き合わせているかの計測器チェック（ρが低ければ結合が壊れている）

反証（prereg の adversarial を H5 の形へ）:
  (a) 業種 SIC2 の中で当て直す (b) 規模3分位の中で当て直す (c) 1業種抜き (d) 置換検定
  (e) 単位（opmD5 は比率pt）(f) **窓の重なり**——gap=fy_next−fy_now が 4 以下だと窓が重なり、
      共有する年が符号違いで入るので **機械的に負の相関**が出る。gap==5 に限った版も出す。

置換の帰無（prereg「会社単位・全ビンテージ同時に混ぜる」を H5 へ翻訳）:
  会社ラベルを1本の置換で作り、**next 側だけ**をそれで入れ替える（now→next の対応だけを壊し、
  同じ会社が複数の対に出ることによる対どうしの従属は保つ）。ビンテージ内で独立に混ぜると
  従属が壊れて偽陽性率を過小評価する（既記録）。
──────────────────────────────────────────────────────────────────────
"""
import json, os, random, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

LINE = 0.15
PAIRS = [(2013, 2018), (2016, 2021), (2017, 2022)]
NPERM = 2000
SEED = 20260818
# H2 の事前登録済みの閾値をそのまま借りる（新しい線を作らない）
DEPTH = [-0.02, -0.05, -0.10]


# ---------- 小道具（再実装しない方針: 統計の素だけ自前） ----------
def ranks(xs):
    """平均順位（同順位は平均）。"""
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and xs[idx[j + 1]] == xs[idx[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[idx[k]] = r
        i = j + 1
    return out


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    sa = sum((x - ma) ** 2 for x in a)
    sb = sum((x - mb) ** 2 for x in b)
    if sa <= 0 or sb <= 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (sa ** 0.5 * sb ** 0.5)


def spearman(a, b):
    if len(a) < 3:
        return None
    return pearson(ranks(a), ranks(b))


def partial_spearman(x, y, z):
    """順位での偏相関 r_xy.z（水準 z を統制したときの x-y）。"""
    rx, ry, rz = ranks(x), ranks(y), ranks(z)
    rxy, rxz, ryz = pearson(rx, ry), pearson(rx, rz), pearson(ry, rz)
    if None in (rxy, rxz, ryz):
        return None
    den = ((1 - rxz ** 2) * (1 - ryz ** 2)) ** 0.5
    return None if den <= 0 else (rxy - rxz * ryz) / den


def med(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def r4(x):
    return None if x is None else round(x, 4)


# ---------- 土台を読む ----------
def load_base():
    with open(os.path.join(OUT, "opmtrend_base.json"), encoding="utf-8") as f:
        b = json.load(f)
    by = defaultdict(dict)
    for r in b["rows"]:
        by[r["vintage"]][r["ticker"]] = r
    return b, by


def load_fy():
    """窓の重なりを検算するためだけに features2 の fy(アンカー年) を読む。
    分析値は一切ここから採らない（土台は opmtrend_base.json）。"""
    fy = defaultdict(dict)
    for v in sorted({v for p in PAIRS for v in p}):
        p = os.path.join(OUT, f"retro_features2_{v}.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        for r in d["rows"]:
            if r.get("fy") is not None:
                fy[v][r["ticker"]] = r["fy"]
    return fy


# ---------- 対を作る ----------
def build_pair(by, fy, a, b, pool):
    """now=a, next=b。opmD5 が両方ある社だけ。qual は now 側で評価。"""
    rows = []
    na = by.get(a, {})
    nb = by.get(b, {})
    for t, ra in na.items():
        rb = nb.get(t)
        if rb is None:
            continue
        if ra.get("opmD5") is None or rb.get("opmD5") is None:
            continue
        if pool == "qual" and not ra.get("qual"):
            continue
        gap = None
        if t in fy.get(a, {}) and t in fy.get(b, {}):
            gap = fy[b][t] - fy[a][t]
        rows.append({
            "ticker": t,
            "now": ra["opmD5"], "next": rb["opmD5"],
            "now_opm": ra.get("opm"), "next_opm": rb.get("opm"),
            "now_rev": ra.get("rev"), "next_rev": rb.get("rev"),
            "sic2": ra.get("sic2"), "gap": gap,
        })
    return rows


def transition(rows):
    """今<0 / 今>=0 × 次<0 / 次>=0 の実数。"""
    dd = sum(1 for r in rows if r["now"] < 0 and r["next"] < 0)
    du = sum(1 for r in rows if r["now"] < 0 and r["next"] >= 0)
    ud = sum(1 for r in rows if r["now"] >= 0 and r["next"] < 0)
    uu = sum(1 for r in rows if r["now"] >= 0 and r["next"] >= 0)
    return dd, du, ud, uu


def stats(rows):
    n = len(rows)
    if n == 0:
        return None
    dd, du, ud, uu = transition(rows)
    n_now_dn = dd + du
    n_now_up = ud + uu
    base = (dd + ud) / n
    p_dn = dd / n_now_dn if n_now_dn else None
    p_up = ud / n_now_up if n_now_up else None
    out = {
        "n": n,
        "n_now_down": n_now_dn, "n_now_up": n_now_up,
        "matrix": {"down_down": dd, "down_up": du, "up_down": ud, "up_up": uu},
        "base_next_down": r4(base),
        "p_next_down_given_now_down": r4(p_dn),
        "p_next_down_given_now_up": r4(p_up),
        "lift_base": r4(p_dn - base) if p_dn is not None else None,
        "lift_contrast": r4(p_dn - p_up) if (p_dn is not None and p_up is not None) else None,
        "ceiling_lift_base": r4(1.0 - base),
        "rho_opmD5": r4(spearman([r["now"] for r in rows], [r["next"] for r in rows])),
        "median_now": r4(med([r["now"] for r in rows])),
        "median_next": r4(med([r["next"] for r in rows])),
    }
    # 対照 L1: opm(水準)
    lv = [r for r in rows if r["now_opm"] is not None and r["next_opm"] is not None]
    if len(lv) >= 10:
        mn = med([r["now_opm"] for r in lv])
        mx = med([r["next_opm"] for r in lv])
        lo_lo = sum(1 for r in lv if r["now_opm"] < mn and r["next_opm"] < mx)
        lo = sum(1 for r in lv if r["now_opm"] < mn)
        nx_lo = sum(1 for r in lv if r["next_opm"] < mx)
        out["level_control"] = {
            "n": len(lv),
            "rho_opm": r4(spearman([r["now_opm"] for r in lv], [r["next_opm"] for r in lv])),
            "base_next_below_median": r4(nx_lo / len(lv)),
            "p_next_below_given_now_below": r4(lo_lo / lo) if lo else None,
            "lift_base": r4(lo_lo / lo - nx_lo / len(lv)) if lo else None,
        }
    # 対照 L2: 売上規模（結合が正しいかの計測器チェック）
    rv = [r for r in rows if r["now_rev"] and r["next_rev"] and r["now_rev"] > 0 and r["next_rev"] > 0]
    if len(rv) >= 10:
        out["instrument_check"] = {
            "n": len(rv),
            "rho_rev": r4(spearman([r["now_rev"] for r in rv], [r["next_rev"] for r in rv])),
        }
    # 深さ別（H2 の事前登録済み閾値を流用）
    dep = {}
    for th in DEPTH:
        sub = [r for r in rows if r["now"] < th]
        if sub:
            dep[str(th)] = {
                "n": len(sub),
                "p_next_down": r4(sum(1 for r in sub if r["next"] < 0) / len(sub)),
                "lift_base": r4(sum(1 for r in sub if r["next"] < 0) / len(sub) - base),
            }
        else:
            dep[str(th)] = {"n": 0, "p_next_down": None, "lift_base": None}
    out["by_depth"] = dep
    # 事後の診断（合否には使わない）: 「変化が持続しない」のか「水準が平均回帰している」のか
    dg = [r for r in rows if r["now_opm"] is not None]
    if len(dg) >= 30:
        out["diagnostics_posthoc"] = {
            "n": len(dg),
            "note": "合否には使わない。負の rho の正体を分けるための診断",
            "partial_rho_change_given_level":
                r4(partial_spearman([r["now"] for r in dg], [r["next"] for r in dg],
                                    [r["now_opm"] for r in dg])),
            "rho_level_now_vs_next_change":
                r4(spearman([r["now_opm"] for r in dg], [r["next"] for r in dg])),
            "rho_change_now_vs_next_level":
                r4(spearman([r["now"] for r in dg], [r["next_opm"] for r in dg]))
                if all(r["next_opm"] is not None for r in dg) else None,
        }
    return out


# ---------- 置換検定 ----------
def permutation(pairs_rows, nperm=NPERM, seed=SEED):
    """会社ラベル1本の置換を全対へ同時に当て、next 側だけ入れ替える。
    返す: 対ごとの p（lift_base・rho）と、宣言した線を帰無が満たす確率（偽陽性率）。"""
    rnd = random.Random(seed)
    universe = sorted({r["ticker"] for rows in pairs_rows.values() for r in rows})
    obs = {}
    pre = {}
    for key, rows in pairs_rows.items():
        st = stats(rows)
        obs[key] = (st["lift_base"], st["rho_opmD5"])
        pre[key] = {
            "idx": {r["ticker"]: i for i, r in enumerate(rows)},
            "now_dn": [r["now"] < 0 for r in rows],
            "next_dn": [r["next"] < 0 for r in rows],
            "rank_now": ranks([r["now"] for r in rows]),
            "rank_next": ranks([r["next"] for r in rows]),
            "tickers": [r["ticker"] for r in rows],
        }
    cnt_lift = {k: 0 for k in pairs_rows}
    cnt_lift_lo = {k: 0 for k in pairs_rows}
    cnt_rho = {k: 0 for k in pairs_rows}
    cnt_line = 0
    for _ in range(nperm):
        perm = universe[:]
        rnd.shuffle(perm)
        m = dict(zip(universe, perm))
        lifts, ok = {}, True
        for key, rows in pairs_rows.items():
            P = pre[key]
            aN, bN, aR, bR = [], [], [], []
            for i, t in enumerate(P["tickers"]):
                src = m.get(t)
                j = P["idx"].get(src)
                if j is None:
                    continue
                aN.append(P["now_dn"][i]); bN.append(P["next_dn"][j])
                aR.append(P["rank_now"][i]); bR.append(P["rank_next"][j])
            n = len(aN)
            if n < 10:
                ok = False
                continue
            base = sum(bN) / n
            nd = sum(1 for i in range(n) if aN[i])
            pd = (sum(1 for i in range(n) if aN[i] and bN[i]) / nd) if nd else None
            lf = (pd - base) if pd is not None else None
            rh = pearson(aR, bR)
            lifts[key] = lf
            if lf is not None and obs[key][0] is not None:
                if lf >= obs[key][0]:
                    cnt_lift[key] += 1
                if lf <= obs[key][0]:
                    cnt_lift_lo[key] += 1
            if rh is not None and obs[key][1] is not None and abs(rh) >= abs(obs[key][1]):
                cnt_rho[key] += 1
        vals = [v for v in lifts.values() if v is not None]
        if ok and len(vals) == len(pairs_rows):
            if all(v >= LINE for v in vals):
                cnt_line += 1
    return {
        "n_perm": nperm, "seed": seed,
        "p_lift_one_sided_high": {k: round((cnt_lift[k] + 1) / (nperm + 1), 4) for k in cnt_lift},
        "p_lift_one_sided_low": {k: round((cnt_lift_lo[k] + 1) / (nperm + 1), 4) for k in cnt_lift_lo},
        "p_rho_two_sided": {k: round((cnt_rho[k] + 1) / (nperm + 1), 4) for k in cnt_rho},
        "false_positive_rate_of_declared_line": round(cnt_line / nperm, 4),
    }


def power(cells, lifts=(0.05, 0.10, 0.15, 0.20, 0.25, 0.30), nsim=2000, seed=SEED):
    """宣言した線（lift_base >= 0.15 かつ全対で同符号）の検出力。
    ⚠ 構造だけで決まる量（観測の結果に依らない）。真の lift が L のとき合格を出す確率。"""
    rnd = random.Random(seed + 7)
    usable = [(k, st) for k, st in cells.items()
              if st and st["n_now_down"] > 0 and st["n_now_up"] > 0]
    if not usable:
        return {}
    out = {}
    for L in lifts:
        hit = 0
        for _ in range(nsim):
            ok = True
            for k, st in usable:
                n, ndn, nup = st["n"], st["n_now_down"], st["n_now_up"]
                b0, f = st["base_next_down"], ndn / st["n"]
                p_dn = min(0.999, max(0.001, b0 + L))
                p_up = min(0.999, max(0.001, (b0 - f * p_dn) / (1 - f)))
                dd = sum(1 for _ in range(ndn) if rnd.random() < p_dn)
                ud = sum(1 for _ in range(nup) if rnd.random() < p_up)
                lf = dd / ndn - (dd + ud) / n
                if not (lf >= LINE):
                    ok = False
                    break
            hit += 1 if ok else 0
        out[str(L)] = round(hit / nsim, 4)
    return {"note": "真の lift_base が L のとき、宣言した線が合格を出す確率（全対同時）", "n_sim": nsim, "power": out}


# ---------- 反証 ----------
def adversarial(rows):
    out = {}
    # (f) 窓の重なり
    g = defaultdict(int)
    for r in rows:
        g[str(r["gap"])] += 1
    out["gap_dist"] = dict(sorted(g.items(), key=lambda kv: (kv[0] == "None", kv[0])))
    g5 = [r for r in rows if r["gap"] == 5]
    out["gap5_only"] = stats(g5) if len(g5) >= 20 else {"n": len(g5), "note": "n<20 で測らない"}
    # (a) 業種の中で当て直す（SIC2 内で opmD5 の順位相関→全体へ Fisher-z 平均ではなく単純な層内 pooled lift）
    bys = defaultdict(list)
    for r in rows:
        if r["sic2"]:
            bys[r["sic2"]].append(r)
    dd = du = 0
    ud = uu = 0
    rhos = []
    for s, rs in bys.items():
        if len(rs) < 10:
            continue
        a, b, c, d = transition(rs)
        dd += a; du += b; ud += c; uu += d
        rh = spearman([r["now"] for r in rs], [r["next"] for r in rs])
        if rh is not None:
            rhos.append(rh)
    n = dd + du + ud + uu
    if n:
        base = (dd + ud) / n
        pd = dd / (dd + du) if (dd + du) else None
        out["within_sic2"] = {
            "n": n, "n_sic2_used": len(rhos),
            "lift_base": r4(pd - base) if pd is not None else None,
            "median_rho_within_sic2": r4(med(rhos)) if rhos else None,
        }
    # (b) 規模3分位の中で
    rv = sorted([r for r in rows if r["now_rev"]], key=lambda r: r["now_rev"])
    ter = {}
    if len(rv) >= 30:
        k = len(rv) // 3
        for name, sub in (("small", rv[:k]), ("mid", rv[k:2 * k]), ("large", rv[2 * k:])):
            st = stats(sub)
            ter[name] = {"n": st["n"], "lift_base": st["lift_base"], "rho": st["rho_opmD5"]}
    out["by_size_tercile"] = ter
    # (c) 1業種抜き
    loo = []
    full = stats(rows)
    for s, rs in bys.items():
        if len(rs) < 10:
            continue
        sub = [r for r in rows if r["sic2"] != s]
        st = stats(sub)
        loo.append({"drop_sic2": s, "n_dropped": len(rs), "lift_base": st["lift_base"], "rho": st["rho_opmD5"]})
    loo.sort(key=lambda x: (x["lift_base"] is None, x["lift_base"]))
    out["leave_one_sic2_out"] = {
        "full_lift_base": full["lift_base"], "full_rho": full["rho_opmD5"],
        "min": loo[0] if loo else None, "max": loo[-1] if loo else None, "n_variants": len(loo),
    }
    return out


def verdict(cells):
    """宣言した線に照らす。判定不能→合否から外す。"""
    usable, undec = [], []
    for k, st in cells.items():
        if st is None or st["n_now_down"] == 0:
            undec.append({"pair": k, "why": "n(今<0)=0"})
            continue
        if st["ceiling_lift_base"] < LINE:
            undec.append({"pair": k, "why": f"到達不能（上限 {st['ceiling_lift_base']} < {LINE}）"})
            continue
        usable.append((k, st))
    if not usable:
        return {"verdict": "判定不能", "why": "判定可能な対がゼロ", "undecidable": undec}
    res = {}
    for form in ("lift_base", "lift_contrast"):
        vals = [(k, st[form]) for k, st in usable if st[form] is not None]
        if len(vals) < len(usable):
            res[form] = {"verdict": "判定不能", "why": "対の一部で統計が作れない"}
            continue
        v = [x for _, x in vals]
        same = all(x > 0 for x in v) or all(x < 0 for x in v)
        # 借りた H1 の線は**向きつき**（lift >= 0.15）。|lift| で当てると強い負が「合格」に化ける
        passed = all(x >= LINE for x in v)
        anti = all(x <= -LINE for x in v)   # 反対向き（平均回帰）に同じ大きさで越えたか
        res[form] = {
            "verdict": "合格" if passed else "不合格",
            "values": {k: x for k, x in vals},
            "same_sign": same,
            "min": r4(min(v)), "max": r4(max(v)),
            "line": f"lift >= {LINE}（向きつき）",
            "crossed_line_in_opposite_direction": anti,
            "why": ("線を満たす" if passed else
                    f"最大 lift {r4(max(v))} < {LINE}"
                    + ("（しかも全対で負＝持続ではなく平均回帰の向き）" if all(x < 0 for x in v) else "")),
        }
    res["undecidable"] = undec
    return res


def main():
    base, by = load_base()
    fy = load_fy()
    out = {
        "generated": "2026-08-18",
        "tool": "night/opmtrend_h5.py",
        "role": "H5（トレンドの持続性）のみ。合否は宣言した線だけで裁く。値も規約も一切変えない。",
        "prereg": "out/opm_trend_prereg.json の H5_persistence",
        "base": "out/opmtrend_base.json（結合し直していない）",
        "line_declaration": {
            "h5_has_no_line_of_its_own": True,
            "borrowed_from": "H1_selector",
            "line": f"lift >= {LINE} かつ すべての対で符号が同じ",
            "primary_stat": "lift_base = P(次も opmD5<0 | 今 opmD5<0) − P(次も opmD5<0)（事前登録 H5 の文言どおり）",
            "secondary_stat": "lift_contrast = P(次<0 | 今<0) − P(次<0 | 今>=0)（H1 と同じ形）",
            "note": "lift_base = (1−f)·lift_contrast（f=今<0の割合）なので約2倍ちがう。両方を別々に裁いて両方報告する。",
        },
        "pairs": [f"{a}->{b}" for a, b in PAIRS],
        "pools": {"all": "全社", "qual": "質実証（opm>=10% かつ fcfpos5>=5）。**now 側のビンテージ**で評価"},
        "warnings": [],
        "reachability": {},
        "results": {},
        "verdicts": {},
        "permutation": {},
        "power_of_declared_line": {},
        "adversarial": {},
    }

    if base["rows"][0].get("opm_raw") is not None:
        out["unit_check"] = {
            "opmD5": "比率pt のまま（土台の opmD5）。%pt は opmD5_pp。閾値 -0.02/-0.05/-0.10 は比率pt",
            "opm": "土台で%へ換算済み（opm列）。qual の 10% 判定は土台が実施",
        }

    cov = base.get("opmD5_coverage", {})
    if cov.get("2013", {}).get("coverage", 1) < 0.6:
        out["warnings"].append(
            "2013 の opmD5 被覆は %.0f%%・opmD5 がある社の売上中央値は欠測社の %.2f倍＝**大型に偏った別の標本**。"
            "2013->2018 の対は他の2対と比較可能でない（土台の警告を引き継ぐ）"
            % (cov["2013"]["coverage"] * 100, cov["2013"]["rev_ratio"]))

    pools_rows = {}
    for pool in ("all", "qual"):
        cells = {}
        prows = {}
        for a, b in PAIRS:
            key = f"{a}->{b}"
            rows = build_pair(by, fy, a, b, pool)
            prows[key] = rows
            cells[key] = stats(rows)
        pools_rows[pool] = prows
        out["results"][pool] = cells
        out["reachability"][pool] = {
            k: {"n": (v or {}).get("n"), "n_now_down": (v or {}).get("n_now_down"),
                "base_next_down": (v or {}).get("base_next_down"),
                "ceiling_lift_base": (v or {}).get("ceiling_lift_base"),
                "reachable": (v is not None and v["n_now_down"] > 0 and v["ceiling_lift_base"] >= LINE)}
            for k, v in cells.items()}
        out["verdicts"][pool] = verdict(cells)
        out["power_of_declared_line"][pool] = power(cells)
        out["permutation"][pool] = permutation({k: v for k, v in prows.items() if len(v) >= 30})
        out["adversarial"][pool] = {k: adversarial(v) for k, v in prows.items() if len(v) >= 50}

    # 対照のまとめ（水準 vs 変化）
    summ = []
    for pool in ("all", "qual"):
        for k, st in out["results"][pool].items():
            if not st:
                continue
            summ.append({
                "pool": pool, "pair": k, "n": st["n"],
                "rho_opmD5(変化)": st["rho_opmD5"],
                "rho_opm(水準)": (st.get("level_control") or {}).get("rho_opm"),
                "rho_rev(計測器)": (st.get("instrument_check") or {}).get("rho_rev"),
                "lift_base_opmD5": st["lift_base"],
                "lift_base_opm水準": (st.get("level_control") or {}).get("lift_base"),
            })
    out["level_vs_change"] = summ

    # 期間(マクロ) と 会社(自分の過去) のどちらが opmD5 の符号を動かしているか
    negfrac = {}
    for v in sorted(by):
        rs = [r for r in by[v].values() if r.get("opmD5") is not None]
        if rs:
            negfrac[str(v)] = r4(sum(1 for r in rs if r["opmD5"] < 0) / len(rs))
    vals = [x for x in negfrac.values()]
    lifts = [st["lift_base"] for pool in ("all", "qual") for st in out["results"][pool].values()
             if st and st["lift_base"] is not None]
    out["period_vs_company"] = {
        "note": "opmD5<0 の割合はビンテージ（＝マクロの窓）でどれだけ動くか vs 会社自身の前回の符号でどれだけ動くか",
        "share_negative_by_vintage": negfrac,
        "spread_across_vintages_pp": r4((max(vals) - min(vals)) * 100) if vals else None,
        "company_own_prior_lift_base_pp_range": [r4(min(lifts) * 100), r4(max(lifts) * 100)] if lifts else None,
    }

    out["limits"] = [
        "8ビンテージは同じ956社・窓が重なる＝真の out-of-sample はゼロ（事前登録の限界をそのまま引き継ぐ）",
        "2013 の opmD5 被覆は48%で大型に偏る（上の warnings）",
        "**機械的な負のバイアス**: opmD5_now = opm[a]−opm[a−4]、opmD5_next = opm[b]−opm[b−4]。"
        "b−4 = a+1 は a の隣年で強く相関するので、端点の一過性の揺れは now を上げ next を下げる向きに入る。"
        "＝持続がゼロでも ρ はやや負へ引かれる。gap==5 でもこの偏りは残る（gap<=4 なら同じ年が符号違いで共有され、もっと強く効く）",
        "opmD5 は会計上の営業利益率で一過性費用を調整しない",
        "gmt(門の3値・審査官の判断) と opmD5(機械の連続量) は同じものではない",
    ]

    p = os.path.join(OUT, "opmtrend_h5.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", p)
    return out


if __name__ == "__main__":
    o = main()
    # 画面用の要約（在庫に入れた数字だけを出す）
    for pool in ("all", "qual"):
        print(f"\n===== プール: {pool} =====")
        for k, st in o["results"][pool].items():
            if not st:
                print(f"{k}: なし"); continue
            lc = st.get("level_control") or {}
            ic = st.get("instrument_check") or {}
            print(f"{k}: n={st['n']} 今<0={st['n_now_down']} base={st['base_next_down']} "
                  f"P(次<0|今<0)={st['p_next_down_given_now_down']} P(次<0|今>=0)={st['p_next_down_given_now_up']} "
                  f"lift_base={st['lift_base']} lift_contrast={st['lift_contrast']} "
                  f"rho_opmD5={st['rho_opmD5']} | 対照 rho_opm={lc.get('rho_opm')} "
                  f"lift_opm水準={lc.get('lift_base')} | 計測器 rho_rev={ic.get('rho_rev')}")
        v = o["verdicts"][pool]
        for form in ("lift_base", "lift_contrast"):
            if form in v:
                print(f"  判定[{form}] = {v[form]['verdict']}（{v[form].get('why')}）")
        print("  置換:", json.dumps(o["permutation"][pool], ensure_ascii=False))
