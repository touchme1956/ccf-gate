#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_panel.py — 勝者／破壊の対称探索のための5ビンテージ統合パネル。

事前登録: out/hist_winner_destroyer_prereg.json（合否の線はそこにある。この道具は線を持たない）

**この道具は判定を一つも持たない。** 出すのは 1行 = (ticker, vintage) のパネルと、
そのパネルを読む前に知っておかねばならない診断だけ。以降の全探索はこの1本を読む
（二重実装を作らない・v9.9.65）。

────────────────────────────────────────────────────────────
設計上の決定と、その理由（後から読む人へ）
────────────────────────────────────────────────────────────
1) **特徴量は出所で名前空間を分ける**（f2_ / co_ / pa_ / hv_ / per）。
   同じ「opm」でも features2（fy時点の営業利益率）と cohort（gate0式・asof窓の最終年）は
   別のパイプラインの別の量。素朴に一つの列へ混ぜると、2013と2018を比べたときに
   「基準の違う二つを割る」型をそのまま踏む。**混ぜないことが唯一の防御。**
   とくに co_roic_* は gate0式（のれん・無形を控除しない）で、門式ROICではない。

2) **P_quality の定義はビンテージで揃わない。揃えられない。**
   規約は opm>=10% ∧ 5年FCF全年黒字 ∧ 営業利益全年黒字 の3条件。
   ところが retro_features2 は営業利益全年黒字を持たない——`streak_opm` は
   「営業利益率が前年より上がった年数」であって「黒字の年数」ではない（生成器を読んで確認）。
   よって 2016-2018 は **2条件しか当てられない＝真の定義より緩い上位集合**。
   2013/2015（cohort）は op_all_pos / fcf_all_pos を持つので3条件そろう。
   → 各行に `quality_basis` を書き、**ビンテージ間で P_quality の水準を直接比べない**ことを診断で明示する。
   （hist_val も同じ2条件で quality を作っていた＝この非対称は既存の在庫にも入っている）

3) **outcome の正本は returns ファイルだけ。** hist_val も tr_cagr を持つが、
   同じ台帳を読む二つが違うことを言っていないかは診断で突き合わせる（conflict を数える）。

4) **years は揃っていない。** 全ビンテージに短窓の行が混じる（DBD 3.01年など）。
   年率で比べる以上、短窓は両裾を機械的に膨らませる。`window_full` を必ず持たせ、
   基準率は「全行」と「window_fullのみ」の両方を出す。

5) **irr は同一ビンテージの読解のみを `irr` に入れる。** 2016/2017 は読解が存在しないので null。
   近傍ビンテージの読解は `irr_near`(+`irr_near_src`) に分けて置く——
   使うかどうかは下流の判断で、既定では混ぜない。

6) 行の母集団は returns ∪ features の**和集合**。outcome の無い行も `has_outcome=false` で残す
   （黙って落とすと 2015 の outcome 被覆が偏っている事実そのものが見えなくなる）。
   基準率の計算は has_outcome の行だけで行う。

⚠ retro_returns_2013.json(70社の抽出) と retro_returns_2015.json(164社) は**使わない**。
   使うのは _2013_all(956) と _2015_q(506)。後者も「全社ではない」＝質実証プール寄りの偏りがある。
"""
import json, os, sys, math
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")

WIN_HURDLE = 0.15      # 既存のハードル（新しい定数を作らない）
DESTROY_HURDLE = -0.15  # 既存の恒久毀損の定義（retro_moat_durability と同じ）

# ─────────────────────────── 出所の定義 ───────────────────────────
# returns は各ビンテージの正本。2013は _all(956)、2015は _q(506)。抽出版は使わない。
RETURNS = {
    2013: "retro_returns_2013_all.json",
    2015: "retro_returns_2015_q.json",
    2016: "retro_returns_2016.json",
    2017: "retro_returns_2017.json",
    2018: "retro_returns_2018.json",
}
FEATURES2 = {2016: "retro_features2_2016.json", 2017: "retro_features2_2017.json",
             2018: "retro_features2_2018.json"}
COHORT = {2013: "retro_cohort_2013.json", 2015: "retro_cohort_2015.json"}
PATH = {2018: "retro_path_2018.json"}
HISTVAL = {2013: "hist_val_2013.json", 2015: "hist_val_2015.json", 2018: "hist_val_2018.json"}
PERF = {2013: "retro_per_2013_all.json", 2015: "retro_per_2015.json", 2018: "retro_per_2018_all.json"}
# moat は対照専用（候補にしない・prereg candidates_excluded）
MOAT = {
    2013: [("retro_moat_2013.json", "ticker", "irr"), ("retro_moat_2013q.json", "ticker", "irr")],
    2015: [("retro_moat_2015.json", "ticker", "irr"), ("retro_moat_2015q.json", "ticker", "irr"),
           ("retro_moat_2015qb.json", "ticker", "irr")],
    2018: [("retro_moat_2018.json", "t", "irr18"), ("retro_moat_2018_rest.json", "t", "irr18")],
}

F2_FEATS = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r",
            "gw_r", "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5",
            "conv5", "netiss_r", "payout5", "rev"]
PA_FEATS = ["rf5", "mdd5", "vol_m", "worst12", "prox_hi", "upmo_r", "r2_log"]
CO_FEATS = ["sales_cagr5", "opm", "roic_latest", "roic_worst5", "roic_med5", "fcf_conv_5y",
            "op_all_pos", "fcf_all_pos", "equity_neg", "score", "rev_asof"]
HV_FEATS = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_z", "ps_z"]

VINTAGES = [2013, 2015, 2016, 2017, 2018]


def load(fn):
    p = os.path.join(OUT, fn)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def rows_of(d):
    if not d:
        return []
    return d.get("rows") or d.get("items") or []


# ─────────────────────────── 小さな統計 ───────────────────────────
def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def sd(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def spearman(pairs):
    """pairs = [(a,b)] 両方 non-null。順位相関（同順位は平均順位）。"""
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return None, n

    def ranks(vals):
        idx = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and vals[idx[j + 1]] == vals[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((x - mb) ** 2 for x in rb))
    if da == 0 or db == 0:
        return None, n
    return round(num / (da * db), 4), n


def rate(rows, key):
    """事象の分子と分母を必ず対で返す（率だけを返さない）。"""
    den = [r for r in rows if r.get("tr_cagr") is not None]
    num = [r for r in den if r.get(key)]
    return {"n": len(den), "k": len(num), "p": round(len(num) / len(den), 4) if den else None}


# ─────────────────────────── パネル構築 ───────────────────────────
def build():
    diag = {}
    src_meta = {}
    panel = []

    # --- 文脈: sic2（現在の登録分類＝時点付きではない。粗い層別専用） ---
    sicd = load("retro_sic.json")
    sic2 = {r["ticker"]: r.get("sic2") for r in rows_of(sicd)}
    src_meta["retro_sic.json"] = {"generated": (sicd or {}).get("generated"), "n": len(sic2)}

    # --- irr（対照専用）: 同一ビンテージの読解のみ ---
    irr_by_v = {}
    irr_conflicts = {}
    moat5_by_v = {}
    for v, specs in MOAT.items():
        m, m5, conf = {}, {}, []
        for fn, tk, ik in specs:
            d = load(fn)
            if not d:
                continue
            src_meta[fn] = {"generated": d.get("generated"), "n": len(rows_of(d))}
            for r in rows_of(d):
                t = r.get(tk)
                if not t:
                    continue
                val = r.get(ik)
                if t in m and m[t] != val:
                    conf.append({"ticker": t, "a": m[t], "b": val, "file": fn})
                m[t] = val
                if r.get("moat5") is not None:
                    m5[t] = r.get("moat5")
        irr_by_v[v] = m
        moat5_by_v[v] = m5
        irr_conflicts[v] = conf

    # 近傍ビンテージの irr（既定では使わない・下流の判断用）
    def nearest_irr(t, v):
        best = None
        for vv in sorted(irr_by_v, key=lambda x: (abs(x - v), x)):
            if t in irr_by_v[vv] and irr_by_v[vv][t] is not None:
                best = (irr_by_v[vv][t], vv)
                break
        return best

    hv_outcome_conflicts = []

    for v in VINTAGES:
        # ---- outcome（正本） ----
        rd = load(RETURNS[v])
        if not rd:
            raise SystemExit("missing returns for %d" % v)
        src_meta[RETURNS[v]] = {"generated": rd.get("generated"), "n": len(rows_of(rd)),
                                "asof_date": rd.get("asof_date"), "now_date": rd.get("now_date"),
                                "benchmark_years": rd["benchmark"]["years"],
                                "benchmark_tr_cagr": rd["benchmark"]["tr_cagr"],
                                "note": rd.get("note")}
        ret = {r["ticker"]: r for r in rows_of(rd)}
        # modal 窓長はデータから決める（決め打ちしない）。ベンチマークと一致するはず。
        modal = Counter(round(r["years"], 2) for r in ret.values()).most_common(1)[0][0]
        bench_years = rd["benchmark"]["years"]

        # ---- 特徴量 ----
        f2 = {}
        if v in FEATURES2:
            d = load(FEATURES2[v])
            src_meta[FEATURES2[v]] = {"generated": d.get("generated"), "n": len(rows_of(d)),
                                      "deadline": d.get("deadline")}
            f2 = {r["ticker"]: r for r in rows_of(d)}
        co = {}
        if v in COHORT:
            d = load(COHORT[v])
            src_meta[COHORT[v]] = {"generated": d.get("generated"), "n": len(rows_of(d)),
                                   "window": d.get("window")}
            for r in rows_of(d):
                if r.get("ticker"):
                    co[r["ticker"]] = r
        pa = {}
        if v in PATH:
            d = load(PATH[v])
            src_meta[PATH[v]] = {"generated": d.get("generated"), "n": len(rows_of(d))}
            pa = {r["ticker"]: r for r in rows_of(d)}
        hv = {}
        if v in HISTVAL:
            d = load(HISTVAL[v])
            src_meta[HISTVAL[v]] = {"generated": d.get("generated"), "n": len(rows_of(d)),
                                    "tool_rev": d.get("tool_rev")}
            hv = {r["ticker"]: r for r in rows_of(d)}
        pf = {}
        if v in PERF:
            d = load(PERF[v])
            if d:
                src_meta[PERF[v]] = {"generated": d.get("generated"), "n": len(rows_of(d))}
                pf = {r["ticker"]: r for r in rows_of(d)}

        # ---- 行の母集団 = returns ∪ features（黙って落とさない） ----
        feat_keys = set(f2) | set(co)
        universe = sorted(set(ret) | feat_keys)

        for t in universe:
            rr = ret.get(t)
            tr = rr.get("tr_cagr") if rr else None
            row = {
                "ticker": t, "vintage": v,
                "has_outcome": rr is not None and tr is not None,
                "tr_cagr": tr,
                "tr_total": rr.get("tr_total") if rr else None,
                "years": rr.get("years") if rr else None,
                "mdd": rr.get("mdd") if rr else None,
                "stale": rr.get("stale") if rr else None,
                # 窓が modal と揃っている行だけが年率の比較に耐える
                "window_full": (abs(rr["years"] - modal) < 0.02) if rr else None,
                "win": (tr >= WIN_HURDLE) if tr is not None else None,
                "destroy": (tr <= DESTROY_HURDLE) if tr is not None else None,
                "sic2": sic2.get(t),
            }

            # 対照（候補にしない）
            row["irr"] = irr_by_v.get(v, {}).get(t)
            row["moat5"] = moat5_by_v.get(v, {}).get(t)
            near = nearest_irr(t, v)
            row["irr_near"] = near[0] if near else None
            row["irr_near_src"] = near[1] if near else None

            # 特徴量（出所ごとに名前空間を分ける）
            r2 = f2.get(t)
            for k in F2_FEATS:
                row["f2_" + k] = r2.get(k) if r2 else None
            row["f2_fy"] = r2.get("fy") if r2 else None
            row["f2_fy_end"] = r2.get("fy_end") if r2 else None

            rc = co.get(t)
            for k in CO_FEATS:
                row["co_" + k] = rc.get(k) if rc else None

            rp = pa.get(t)
            for k in PA_FEATS:
                row["pa_" + k] = rp.get(k) if rp else None

            rh = hv.get(t)
            for k in HV_FEATS:
                row["hv_" + k] = rh.get(k) if rh else None

            rf = pf.get(t)
            row["per"] = rf.get("per") if rf else None

            # 規模（context）: 出所を必ず添える。f2_rev と co_rev_asof は別の量。
            if row["f2_rev"] is not None:
                row["size_rev"], row["size_src"] = row["f2_rev"], "f2_rev"
            elif row["co_rev_asof"] is not None:
                row["size_rev"], row["size_src"] = row["co_rev_asof"], "co_rev_asof"
            else:
                row["size_rev"], row["size_src"] = None, None

            # ---- 母集団フラグ ----
            row["P_full"] = row["has_outcome"]
            # P_quality: 使える条件だけを当て、何を当てたかを必ず書く
            if v in FEATURES2:
                if row["f2_opm"] is None or row["f2_fcfpos5"] is None:
                    row["P_quality"], row["quality_basis"] = None, "unavailable"
                else:
                    row["P_quality"] = bool(row["f2_opm"] >= 0.10 and row["f2_fcfpos5"] == 5)
                    # ⚠ 営業利益全年黒字は features2 に無い＝真の定義より緩い（上位集合）
                    row["quality_basis"] = "opm+fcfpos5 (op_all_pos 欠如=規約より緩い)"
            elif v in COHORT:
                if rc is None or rc.get("opm") is None or rc.get("fcf_all_pos") is None \
                        or rc.get("op_all_pos") is None:
                    row["P_quality"], row["quality_basis"] = None, "unavailable"
                else:
                    row["P_quality"] = bool(rc["opm"] >= 0.10 and rc["fcf_all_pos"] and rc["op_all_pos"])
                    row["quality_basis"] = "opm+fcf_all_pos+op_all_pos (規約どおり3条件)"
            else:
                row["P_quality"], row["quality_basis"] = None, "unavailable"
            # P_moat: 同一ビンテージの読解がある行だけ。無い＝判定不能（False ではない）
            row["P_moat"] = (row["irr"] >= 70) if row["irr"] is not None else None

            panel.append(row)

            # hist_val が持つ outcome との突合せ（同じ台帳を読む二つが違うことを言っていないか）
            if rh is not None and rh.get("tr_cagr") is not None and tr is not None:
                if abs(rh["tr_cagr"] - tr) > 1e-6:
                    hv_outcome_conflicts.append({"vintage": v, "ticker": t,
                                                 "returns": tr, "hist_val": rh["tr_cagr"]})

        diag.setdefault("per_vintage", {})[v] = {
            "returns_file": RETURNS[v],
            "modal_years_observed": modal,
            "benchmark_years": bench_years,
            "modal_matches_benchmark": abs(modal - bench_years) < 0.02,
            "benchmark_tr_cagr": rd["benchmark"]["tr_cagr"],
        }

    diag["hist_val_outcome_conflicts"] = {"n": len(hv_outcome_conflicts),
                                          "rows": hv_outcome_conflicts[:20]}
    diag["irr_conflicts"] = {str(k): v for k, v in irr_conflicts.items()}
    return panel, diag, src_meta


# ─────────────────────────── 診断 ───────────────────────────
def diagnostics(panel, diag):
    by_v = defaultdict(list)
    for r in panel:
        by_v[r["vintage"]].append(r)

    ALL_FEATS = (["f2_" + k for k in F2_FEATS] + ["co_" + k for k in CO_FEATS]
                 + ["pa_" + k for k in PA_FEATS] + ["hv_" + k for k in HV_FEATS]
                 + ["per", "sic2", "irr", "moat5"])

    # (1) 行数・outcome・被覆率
    cov = {}
    for v in VINTAGES:
        rows = by_v[v]
        out = [r for r in rows if r["has_outcome"]]
        full = [r for r in out if r["window_full"]]
        c = {}
        for f in ALL_FEATS:
            k = sum(1 for r in out if r.get(f) is not None)
            c[f] = {"k": k, "p": round(k / len(out), 4) if out else None}
        cov[v] = {
            "rows": len(rows),
            "has_outcome": len(out),
            "no_outcome": len(rows) - len(out),
            "window_full": len(full),
            "window_short": len(out) - len(full),
            "feature_coverage_over_has_outcome": c,
        }
    diag["coverage"] = cov

    # (2) 基準率（分子と分母を両方）
    base = {}
    for v in VINTAGES:
        out = [r for r in by_v[v] if r["has_outcome"]]
        full = [r for r in out if r["window_full"]]
        pops = {
            "P_full": out,
            "P_full_window_full": full,
            "P_quality": [r for r in out if r["P_quality"] is True],
            "P_quality_window_full": [r for r in full if r["P_quality"] is True],
            "P_moat": [r for r in out if r["P_moat"] is True],
            "P_moat_window_full": [r for r in full if r["P_moat"] is True],
        }
        base[v] = {}
        for pn, rs in pops.items():
            base[v][pn] = {"win": rate(rs, "win"), "destroy": rate(rs, "destroy"),
                           "median_tr_cagr": round(median([r["tr_cagr"] for r in rs]), 4) if rs else None,
                           "sd_tr_cagr": round(sd([r["tr_cagr"] for r in rs]), 4) if len(rs) > 1 else None}
        # P_quality / P_moat の判定不能件数（False と混同しないため）
        base[v]["_undetermined"] = {
            "P_quality_null": sum(1 for r in out if r["P_quality"] is None),
            "P_moat_null": sum(1 for r in out if r["P_moat"] is None),
            "quality_basis": sorted({r["quality_basis"] for r in out}),
        }
    diag["base_rates"] = base

    # (3) ビンテージ間の重複
    sets = {v: {r["ticker"] for r in by_v[v] if r["has_outcome"]} for v in VINTAGES}
    ov = {}
    for i, a in enumerate(VINTAGES):
        for b in VINTAGES[i + 1:]:
            inter = len(sets[a] & sets[b])
            ov["%d-%d" % (a, b)] = {
                "inter": inter, "n_a": len(sets[a]), "n_b": len(sets[b]),
                "share_of_a": round(inter / len(sets[a]), 4) if sets[a] else None,
                "share_of_b": round(inter / len(sets[b]), 4) if sets[b] else None,
                "jaccard": round(inter / len(sets[a] | sets[b]), 4),
            }
    ov["_all5_common"] = len(set.intersection(*sets.values()))
    ov["_161718_common"] = len(sets[2016] & sets[2017] & sets[2018])
    diag["vintage_overlap"] = ov

    # (4) 窓の長さの効果
    # (4a) 観測（共通ticker・window_full のみ）——⚠ 窓長と開始時点の相場が交絡している
    common = set.intersection(*[{r["ticker"] for r in by_v[v]
                                 if r["has_outcome"] and r["window_full"]} for v in VINTAGES])
    obs = {}
    for v in VINTAGES:
        rs = [r for r in by_v[v] if r["ticker"] in common and r["window_full"]]
        yrs = diag["per_vintage"][v]["modal_years_observed"]
        s = sd([r["tr_cagr"] for r in rs])
        obs[v] = {"years": yrs, "n": len(rs),
                  "win": rate(rs, "win"), "destroy": rate(rs, "destroy"),
                  "median": round(median([r["tr_cagr"] for r in rs]), 4),
                  "sd": round(s, 4),
                  "sd_x_sqrtT": round(s * math.sqrt(yrs), 4)}
    diag["window_effect_observed"] = {
        "common_tickers": len(common),
        "by_vintage": obs,
        "caveat": "窓長と『開始時点の相場』が交絡している。この表だけでは分離できない。分離は (4b)。",
    }

    # (4b) 純粋な算術の分離: 結果(tr_total)を固定し、年率換算の指数だけを変える。
    #      同じ実現結果を長い窓で年率にすると両裾がどれだけ縮むかが、これで一意に出る。
    lens = [diag["per_vintage"][v]["modal_years_observed"] for v in VINTAGES]
    arith = {}
    for anchor in VINTAGES:
        rs = [r for r in by_v[anchor] if r["has_outcome"] and r["window_full"]
              and r["tr_total"] is not None and r["tr_total"] > 0]
        a = {"anchor_years": diag["per_vintage"][anchor]["modal_years_observed"], "n": len(rs), "reannualized": {}}
        for T in lens:
            cg = [r["tr_total"] ** (1.0 / T) - 1 for r in rs]
            a["reannualized"][str(T)] = {
                "win_k": sum(1 for x in cg if x >= WIN_HURDLE),
                "win_p": round(sum(1 for x in cg if x >= WIN_HURDLE) / len(cg), 4) if cg else None,
                "destroy_k": sum(1 for x in cg if x <= DESTROY_HURDLE),
                "destroy_p": round(sum(1 for x in cg if x <= DESTROY_HURDLE) / len(cg), 4) if cg else None,
                "sd": round(sd(cg), 4), "median": round(median(cg), 4),
            }
        arith[anchor] = a
    diag["window_effect_arithmetic"] = {
        "method": "同一ビンテージの tr_total を固定し、年率換算の指数 1/T だけを差し替える。"
                  "結果も母集団も動かさないので、窓長（年率換算）の効果だけが残る。",
        "by_anchor": arith,
    }

    # (4c) 短窓行を混ぜたときの影響
    mix = {}
    for v in VINTAGES:
        out = [r for r in by_v[v] if r["has_outcome"]]
        full = [r for r in out if r["window_full"]]
        short = [r for r in out if not r["window_full"]]
        mix[v] = {"all": {"win": rate(out, "win"), "destroy": rate(out, "destroy")},
                  "window_full_only": {"win": rate(full, "win"), "destroy": rate(full, "destroy")},
                  "short_rows": [{"ticker": r["ticker"], "years": r["years"],
                                  "tr_cagr": r["tr_cagr"], "win": r["win"], "destroy": r["destroy"]}
                                 for r in sorted(short, key=lambda x: x["years"])]}
    diag["window_effect_short_rows"] = mix

    # (5) look-ahead の確認: fy_end <= deadline（10-K は期末より後にしか提出できないので必要条件）
    la = {}
    for v in FEATURES2:
        d = load(FEATURES2[v])
        dl = d.get("deadline")
        fes = [r["fy_end"] for r in rows_of(d) if r.get("fy_end")]
        bad = [r["ticker"] for r in rows_of(d) if r.get("fy_end") and r["fy_end"] > dl]
        la[v] = {"deadline": dl, "n_fy_end": len(fes), "max_fy_end": max(fes), "min_fy_end": min(fes),
                 "violations_fy_end_gt_deadline": len(bad), "violation_tickers": bad[:20],
                 "fy_dist": dict(sorted(Counter(r["fy"] for r in rows_of(d)).items()))}
    # cohort(2013/2015) の look-ahead の実測。会計年度末の月は会社ごとにほぼ不変なので
    # features2 の fy_end から採り、窓の最終年が asof(7/1)までに提出されえたかを数える。
    fy_mon = {}
    for v in FEATURES2:
        for r in rows_of(load(FEATURES2[v])):
            if r.get("fy_end"):
                fy_mon.setdefault(r["ticker"], int(r["fy_end"][5:7]))
    cohort_la = {}
    for v in COHORT:
        ts = [r["ticker"] for r in by_v[v] if r["has_outcome"] and r.get("co_opm") is not None]
        have = [t for t in ts if t in fy_mon]
        early = [t for t in have if fy_mon[t] <= 3]  # FY末3月以前なら+90日でも7/1前に提出されうる
        cohort_la[v] = {
            "n_with_cohort_features": len(ts), "n_fiscal_month_known": len(have),
            "n_could_have_filed_by_asof": len(early),
            "share_could_have_filed": round(len(early) / len(have), 4) if have else None,
            "share_lookahead": round(1 - len(early) / len(have), 4) if have else None,
            "method": "会計年度末の月(features2 の fy_end 由来)が3月以前なら、+90日の提出期限でも "
                      "asof(7/1)前に提出されえた。それ以外は窓の最終年が当時未提出＝look-ahead。",
        }
    # 独立な裏取り: features2 は filed で切った結果、当年度FYを採れた社が何%だったか
    cohort_la["_independent_check"] = {
        str(v): {"fy_equals_asof": sum(1 for r in rows_of(load(FEATURES2[v])) if r["fy"] == v),
                 "n": len(rows_of(load(FEATURES2[v])))} for v in FEATURES2}
    cohort_la["_independent_check"]["note"] = (
        "features2 は提出日で切ってあるので『7/1までに当年度を提出できた社』の実測になる（5.6-7.3%）。"
        "上の推定 5.2-5.7% とほぼ一致＝二つの独立な道が同じ答えに着いた。")

    diag["lookahead_check"] = {
        "features2": la,
        "logic": "10-K/20-F は会計年度末より後にしか提出できないので fy_end <= filed <= deadline。"
                 "rows は filed を持たないため、検証できるのは必要条件 fy_end <= deadline まで。",
        "cohort_windows": {2013: [2009, 2013], 2015: [2011, 2015]},
        "cohort_note": "⚠ retro_cohort.py には filed による絞りが一行も無い（年ラベル窓 asof-4..asof のみ）。"
                       "したがって 2013/2015 の特徴量は、窓の最終年が asof(7/1)時点で未提出の社を含む。"
                       "CLAUDE.md の『look-aheadが構造で防がれる』は"
                       "『評価規則を後知恵で変えていない』という意味であって"
                       "『当時読めたデータだけを使った』という意味ではない——二つは別物。",
        "cohort_lookahead_measured": cohort_la,
    }

    # (6) 到達可能性 —— prereg の must_report_before_verdict。
    #     事象の総数が5未満なら、どんな部分群も分子5に届かない＝『不合格』ではなく『判定不能』。
    reach = {}
    for v in VINTAGES:
        out = [r for r in by_v[v] if r["has_outcome"] and r["window_full"]]
        pops = {"P_full": out,
                "P_quality": [r for r in out if r["P_quality"] is True],
                "P_moat": [r for r in out if r["P_moat"] is True]}
        reach[v] = {}
        for pn, rs in pops.items():
            e = {}
            for obj in ("win", "destroy"):
                tot = sum(1 for r in rs if r.get(obj))
                base = tot / len(rs) if rs else None
                cell = {"population_n": len(rs), "events_total": tot,
                        "base": round(base, 4) if base is not None else None,
                        "min_numerator_reachable": tot >= 5}
                # 実効的に要求される lift（MIN_NUM が LIFT を上書きしていないか・v2の教訓）
                for label, frac in (("quartile", 0.25), ("decile", 0.10)):
                    m = int(len(rs) * frac)
                    if m <= 0 or base is None:
                        cell[label] = None
                        continue
                    k_lift = math.ceil((base + 0.15) * m)
                    k_min = 5
                    binding = "MIN_NUM" if k_min > k_lift else "LIFT"
                    need = max(k_lift, k_min)
                    cell[label] = {"group_n": m, "k_by_lift": k_lift, "k_by_min_num": k_min,
                                   "binding": binding,
                                   "effective_lift_required": round(need / m - base, 4),
                                   "possible": need <= tot,
                                   # 合格するには全事象の何割がこの群に集まらねばならないか
                                   # ——破壊側は base が小さいので、ここが1に近づくと実質到達不能
                                   "required_share_of_all_events": round(need / tot, 4) if tot else None}
                e[obj] = cell
            reach[v][pn] = e
    diag["reachability"] = {
        "note": "window_full のみ。events_total < 5 のセルは、どんな部分群を作っても分子5に届かない"
                "＝合否を出せない（『不合格』と書いてはいけない・判定不能）。"
                "effective_lift_required は MIN_NUM(5社) が LIFT(0.15) より強く縛っていないかの確認。",
        "by_vintage": reach,
    }

    # (7) ビンテージ間の独立性 —— ticker が同一なだけでなく、結果そのものがどれだけ共有されているか。
    #     窓が入れ子（2018の窓は2013の窓の末尾）なので、符号一致は自動的に起きうる。
    dep = {}
    for i, a in enumerate(VINTAGES):
        for b in VINTAGES[i + 1:]:
            pa_ = {r["ticker"]: r for r in by_v[a] if r["has_outcome"] and r["window_full"]}
            pb_ = {r["ticker"]: r for r in by_v[b] if r["has_outcome"] and r["window_full"]}
            com = set(pa_) & set(pb_)
            if len(com) < 10:
                continue
            rho, n = spearman([(pa_[t]["tr_cagr"], pb_[t]["tr_cagr"]) for t in com])
            wa = {t for t in com if pa_[t]["win"]}
            wb = {t for t in com if pb_[t]["win"]}
            da = {t for t in com if pa_[t]["destroy"]}
            db = {t for t in com if pb_[t]["destroy"]}
            dep["%d-%d" % (a, b)] = {
                "common_n": len(com), "spearman_tr_cagr": rho,
                "win": {"a": len(wa), "b": len(wb), "both": len(wa & wb),
                        "P_b_given_a": round(len(wa & wb) / len(wa), 4) if wa else None,
                        "jaccard": round(len(wa & wb) / len(wa | wb), 4) if (wa | wb) else None},
                "destroy": {"a": len(da), "b": len(db), "both": len(da & db),
                            "P_b_given_a": round(len(da & db) / len(da), 4) if da else None,
                            "jaccard": round(len(da & db) / len(da | db), 4) if (da | db) else None},
            }
    diag["outcome_dependence"] = {
        "note": "窓は入れ子（すべて2026-08終わり）。2018の窓は2013の窓の末尾8.09年そのもの。"
                "したがって『5ビンテージで符号一致』は独立な5証拠ではない。ここの数字がその度合い。",
        "pairs": dep,
    }

    # (8) irr の刻みの分布（対照の中身。2018だけ 75 を使い 70 が無い＝同じ >=70 でも中身が違う）
    diag["irr_distribution"] = {
        str(v): dict(sorted(Counter(r["irr"] for r in by_v[v]
                                    if r["irr"] is not None).items(), key=lambda x: x[0]))
        for v in VINTAGES}
    diag["irr_distribution"]["_note"] = ("2018 の読解は刻み 50/75/85、2013/2015 は 50/70/85/100。"
                                         "P_moat(irr>=70) は 2018 では {75,85}、2013/2015 では {70,85,100} を指す。")

    # (補) 定義の突合せ: co_opm(asof2015・窓最終年FY2015) vs f2_opm(asof2016・fy は879社がFY2015)
    p15 = {r["ticker"]: r for r in by_v[2015]}
    p16 = {r["ticker"]: r for r in by_v[2016]}
    pairs, same_fy = [], 0
    for t, a in p15.items():
        b = p16.get(t)
        if not b or a.get("co_opm") is None or b.get("f2_opm") is None:
            continue
        pairs.append((a["co_opm"], b["f2_opm"]))
        if b.get("f2_fy") == 2015:
            same_fy += 1
    rho, n = spearman(pairs)
    ratios = [b / a for a, b in pairs if a not in (None, 0)]
    diag["definition_crosscheck_co_opm_vs_f2_opm"] = {
        "why": "cohort_2015 の窓は [2011,2015]、features2_2016 の fy は879社がFY2015＝ほぼ同じ会計年度。"
               "同じ量なら強く一致するはず。一致しなければ『同じ opm』という名前で混ぜてはいけない証拠。",
        "n": n, "spearman": rho, "n_same_fy2015": same_fy,
        "median_ratio_f2_over_co": round(median(ratios), 4) if ratios else None,
        "within_1pt": round(sum(1 for a, b in pairs if abs(a - b) <= 0.01) / len(pairs), 4) if pairs else None,
        "verdict": "名前空間を分けたまま使うこと（この道具はそうしている）。",
    }
    return diag


def main():
    panel, diag, src_meta = build()
    diag = diagnostics(panel, diag)
    out = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_panel.py",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "purpose": "勝者(P(tr_cagr>=+15%))／破壊(P(tr_cagr<=-15%))の対称探索のための5ビンテージ統合パネル。"
                   "以降の全探索はこの1本を読む。この道具は判定・合否の線を一つも持たない。",
        "hurdles": {"win": WIN_HURDLE, "destroy": DESTROY_HURDLE,
                    "note": "既存の定数のみ。新しい線を作っていない。"},
        "sources": src_meta,
        "namespacing": {
            "f2_": "retro_features2_{2016,2017,2018}（filed<=asof で厳密に切ってある）",
            "co_": "retro_cohort_{2013,2015}（gate0式。co_roic_* は門式ROICではない・のれん/無形を控除しない）",
            "pa_": "retro_path_2018（2018のみ・前半5年の値動きの質）",
            "hv_": "hist_val_{2013,2015,2018}（自己相対バリュエーション分位）",
            "per": "retro_per_{2013_all,2015,2018_all}（横断面PER・分割補正済）",
            "warning": "同名の量（opm/rev/cagr）でも出所が違えば別の列にしてある。混ぜて比べないこと。",
        },
        "known_asymmetries": [
            "P_quality の条件数がビンテージで違う（2016-2018は op_all_pos が無く2条件＝規約より緩い）。"
            "quality_basis を各行に持たせてある。ビンテージ間で P_quality の水準を直接比べないこと。",
            "2015 の outcome は retro_returns_2015_q（506社＝質実証プール寄り）で全社ではない。",
            "irr の読解は 2013/2015/2018 のみ。2016/2017 は irr=null＝P_moat が判定不能。",
            "hv_/per は 2016/2017 に存在しない。",
            "cohort(2013/2015) は年ラベル窓で、features2 のような提出日での切り方をしていない。",
        ],
        "n_rows": len(panel),
        "diagnostics": diag,
        "rows": panel,
    }
    p = os.path.join(OUT, "hist_wd_panel.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", p, len(panel), "rows")

    # 端末向けの要約
    print("\n== 行数 / outcome / 窓 ==")
    for v in VINTAGES:
        c = diag["coverage"][v]
        print("  %d: rows=%4d outcome=%4d (no_outcome=%4d) window_full=%4d short=%2d"
              % (v, c["rows"], c["has_outcome"], c["no_outcome"], c["window_full"], c["window_short"]))
    print("\n== 基準率 (window_full のみ) ==")
    for v in VINTAGES:
        for pn in ("P_full_window_full", "P_quality_window_full", "P_moat_window_full"):
            b = diag["base_rates"][v][pn]
            print("  %d %-24s win %3d/%4d = %-7s  destroy %3d/%4d = %s"
                  % (v, pn, b["win"]["k"], b["win"]["n"], b["win"]["p"],
                     b["destroy"]["k"], b["destroy"]["n"], b["destroy"]["p"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
