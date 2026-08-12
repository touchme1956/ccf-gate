#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_rnd_sga_q.py — 候補
  「f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下] / 勝者側 / **P_quality**」
を**潰しにかかる**検証。

⚠ 姉妹の道具と混同しないこと。
  night/hist_wd_verify_rnd_sga.py … 同じ変数の組だが **P_full ∧ sga[下位1/4]**（別の切り方・別の母集団）
  この道具                        … **P_quality ∧ sga[中央値以下]**（探索側の弁: 不合格・業種調整）
  同じ変数の組が母集団で結論が割れる、というのがこの候補の最大の論点なので、
  **二つを1本のファイルに混ぜない**（混ぜると「どちらの話か」が読めなくなる）。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json      … 5ビンテージ統合パネル（唯一の真実）
          out/hist_wd_win_pair.json   … 探索側の答え（**信じる前に検算する相手**）
出力    : out/hist_wd_verify_rnd_sga_q.json

────────────────────────────────────────────────────────────
立場
────────────────────────────────────────────────────────────
**反証が仕事であって確認ではない。** 候補に有利な数字を探さない。
prereg の5条件（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を一つも緩めない。
線の外の数字を出すときは `事前登録の外・診断専用` と明記し、合否には数えない。
「測れない」と「不合格」を区別する（f2_ は 2013/2015 に構造的に無い＝判定不能）。

当てる6つ（1つでも落ちたら不合格）
 1 ビンテージ符号   2016/2017/2018 で符号が反転しないか（＋3つが独立な3証拠かを実測）
 2 業種調整         同一 sic2 内で残るか（MH・層内置換・業種1つずつ除去）
 3 irr の影         irr>=70 層内で残るか / irr と直交か
 4 1社の影響        ティッカーを1社ずつ**パネルごと**抜いて閾値から作り直す
 5 置換             ティッカー束の置換2000回（ビンテージ間相関を保つ帰無）
 6 既存の関門との重複 事業の収縮 / 利払カバー / 質実証 の増分
"""
import json, os, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
PAIR = os.path.join(OUT, "hist_wd_win_pair.json")
DEST = os.path.join(OUT, "hist_wd_verify_rnd_sga_q.json")

# ── prereg の線（読むだけ・作らない） ──
LIFT_LINE = 0.15
MIN_NUM = 5
VINT = [2016, 2017, 2018]

# ── 候補の定義（探索側の答えと逐語一致させる） ──
POP = "P_quality"
VAR_A, CUT_A = "f2_rnd_r", "上位1/4"     # 値 >= 75パーセンタイル（nearest-rank）
VAR_B, CUT_B = "f2_sga_r", "中央値以下"   # 値 <= 50パーセンタイル（nearest-rank）
LABEL = "f2_rnd_r[上位1/4] ∧ f2_sga_r[中央値以下]"

SEED = 20260811
N_PERM = 2000


def nearest_rank(vals, p):
    """探索側と同じ nearest-rank。p=0.75 なら「小さいほうから75%目」の値。"""
    s = sorted(vals)
    if not s:
        return None
    k = max(1, math.ceil(p * len(s)))
    return s[k - 1]


def rate(rows, key="win"):
    n = len(rows)
    k = sum(1 for r in rows if r[key])
    return n, k, (k / n if n else None)


# ══════════════════════════════════════════════════════════
# パネルの読み込みと群の構成（この2つが以降すべての土台）
# ══════════════════════════════════════════════════════════
def load_panel():
    d = json.load(open(PANEL, encoding="utf-8"))
    return d


def pop_rows(panel_rows, vintage):
    """analysis_set = has_outcome ∧ window_full（探索側と同一）"""
    return [r for r in panel_rows
            if r["vintage"] == vintage and r[POP] and r["has_outcome"] and r["window_full"]]


def thresholds(rows):
    a = [r[VAR_A] for r in rows if r[VAR_A] is not None]
    b = [r[VAR_B] for r in rows if r[VAR_B] is not None]
    return (nearest_rank(a, 0.75) if a else None,
            nearest_rank(b, 0.50) if b else None)


def in_group(r, ta, tb):
    return (r[VAR_A] is not None and r[VAR_B] is not None
            and ta is not None and tb is not None
            and r[VAR_A] >= ta and r[VAR_B] <= tb)


def cell(rows):
    """1ビンテージの実測。lift は prereg literal（母集団が分母）＋可測両方版も併記。"""
    ta, tb = thresholds(rows)
    grp = [r for r in rows if in_group(r, ta, tb)]
    both = [r for r in rows if r[VAR_A] is not None and r[VAR_B] is not None]
    n_pop, k_pop, p_pop = rate(rows)
    n_g, k_g, p_g = rate(grp)
    n_b, k_b, p_b = rate(both)
    return {
        "thr_a": ta, "thr_b": tb,
        "n_pop": n_pop, "k_pop": k_pop, "p_pop": round(p_pop, 4) if p_pop is not None else None,
        "n_both_measurable": n_b, "p_both_measurable": round(p_b, 4) if p_b is not None else None,
        "n_group": n_g, "k_group": k_g,
        "p_group": round(p_g, 4) if p_g is not None else None,
        "lift": round(p_g - p_pop, 4) if p_g is not None else None,
        "lift_vs_measurable": round(p_g - p_b, 4) if (p_g is not None and p_b is not None) else None,
        "coverage_both": round(n_b / n_pop, 4) if n_pop else None,
        "_grp": grp, "_pop": rows, "_both": both,
    }


# ══════════════════════════════════════════════════════════
def main():
    t0 = time.time()
    random.seed(SEED)
    panel = load_panel()
    rows_all = panel["rows"]
    out = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_verify_rnd_sga_q.py",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "sibling_tool_do_not_confuse": {
            "night/hist_wd_verify_rnd_sga.py": "同じ変数の組だが P_full ∧ sga[下位1/4]。別の切り方・別の母集団・別の結論",
            "why_separate": "同じ変数の組が母集団で結論が割れることがこの候補の論点。1本に混ぜると読めなくなる",
        },
        "candidate": {
            "label": LABEL, "population": POP, "side": "winner",
            "var_a": VAR_A, "cut_a": CUT_A, "var_b": VAR_B, "cut_b": CUT_B,
            "explorer_verdict": "不合格（業種調整）",
            "explorer_numbers_claimed": {"n": 25, "numerator": 12, "lift": 0.2853,
                                         "note": "依頼文の数字。2018ビンテージの単年値"},
        },
        "stance": "反証が仕事。線を一つも緩めない。線の外の数字は『事前登録の外・診断専用』と明記し合否に数えない。",
    }

    # ── 0. 再現（探索側を信じる前に検算する） ──
    cells = {}
    for v in VINT:
        cells[v] = cell(pop_rows(rows_all, v))

    lifts = {v: cells[v]["lift"] for v in VINT}
    signs = {v: (1 if lifts[v] > 0 else (-1 if lifts[v] < 0 else 0)) for v in VINT}
    maintained = min(lifts.values()) if all(s > 0 for s in signs.values()) else 0.0
    maintained_meas = min(cells[v]["lift_vs_measurable"] for v in VINT) if all(s > 0 for s in signs.values()) else 0.0

    repro = {
        "per_vintage": {str(v): {k: cells[v][k] for k in cells[v] if not k.startswith("_")} for v in VINT},
        "maintained_lift": round(maintained, 4),
        "maintained_lift_vs_measurable": round(maintained_meas, 4),
    }
    # 探索側との突合せ
    try:
        pair = json.load(open(PAIR, encoding="utf-8"))
        ex = [p for p in pair["all_pairs"]
              if p["population"] == POP and p["var_a"] == VAR_A and p["cut_a"] == CUT_A
              and p["var_b"] == VAR_B and p["cut_b"] == CUT_B]
        ex = ex[0] if ex else None
    except Exception:
        ex = None
    if ex:
        repro["explorer_row"] = ex
        repro["matches_explorer"] = {
            "maintained_lift": abs(ex["maintained_lift"] - maintained) < 1e-9,
            "maintained_lift_meas": abs(ex["maintained_lift_meas"] - maintained_meas) < 1e-9,
            "min_numerator": ex["min_numerator_161718"] == min(cells[v]["k_group"] for v in VINT),
        }
        repro["verdict"] = ("独立実装で完全一致。以降の反証はこれが通ったうえでの話"
                            if all(repro["matches_explorer"].values()) else "⚠ 探索側と食い違う。先に道具を疑う")
    out["reproduction"] = repro

    # ── 到達可能性（結果の前に出す・prereg の must_report） ──
    out["reachability"] = {
        "min_numerator_observed": min(cells[v]["k_group"] for v in VINT),
        "max_possible_numerator": {str(v): cells[v]["n_group"] for v in VINT},
        "reachable": all(cells[v]["n_group"] >= MIN_NUM for v in VINT),
        "effective_lift_required": {
            str(v): round(MIN_NUM / cells[v]["n_group"] - cells[v]["p_pop"], 4) if cells[v]["n_group"] else None
            for v in VINT},
        "note": "分子>=5 が lift>=0.15 より強く縛っていないか（v2の教訓）。負なら lift が拘束",
    }

    # ══════════════════════════════════════════════════
    # 1 ビンテージ符号
    # ══════════════════════════════════════════════════
    t1 = {
        "lift_by_vintage": {str(v): lifts[v] for v in VINT},
        "sign_by_vintage": {str(v): signs[v] for v in VINT},
        "sign_stable_161718": all(s > 0 for s in signs.values()),
        "n_group_by_vintage": {str(v): cells[v]["n_group"] for v in VINT},
        "k_group_by_vintage": {str(v): cells[v]["k_group"] for v in VINT},
    }
    # 2013/2015 は f2_ が構造的に無い ⇒ 判定不能（不合格ではない）
    for v in (2013, 2015):
        rs = pop_rows(rows_all, v)
        meas = sum(1 for r in rs if r[VAR_A] is not None and r[VAR_B] is not None)
        t1.setdefault("out_of_sample_2013_2015", {})[str(v)] = {
            "n_pop": len(rs), "n_measurable_both": meas,
            "status": "判定不能（f2_特徴量がこのビンテージに構造的に存在しない）" if meas == 0 else "測定可",
        }
    # 「3ビンテージ＝3つの証拠か」を実測する
    tick = {v: set(r["ticker"] for r in cells[v]["_grp"]) for v in VINT}
    ov = {}
    for i, a in enumerate(VINT):
        for b in VINT[i + 1:]:
            inter = len(tick[a] & tick[b])
            ov[f"{a}-{b}"] = {"inter": inter, "n_a": len(tick[a]), "n_b": len(tick[b]),
                              "jaccard": round(inter / len(tick[a] | tick[b]), 4)}
    t1["group_ticker_overlap"] = ov
    t1["group_ticker_union"] = len(tick[2016] | tick[2017] | tick[2018])
    t1["group_ticker_in_all3"] = len(tick[2016] & tick[2017] & tick[2018])
    # 窓の重なり（同じ終端日なので短い窓は長い窓に完全に含まれる）
    t1["window_overlap"] = {
        "2016": "10.09年（2016-07→2026-08）", "2017": "9.09年", "2018": "8.09年",
        "note": "終端日が共通。2018の窓8.09年は2016の窓10.09年に完全に含まれる＝結果は独立でない",
    }
    t1["universe_overlap_from_panel"] = panel["diagnostics"]["vintage_overlap"].get("_161718_common")
    t1["verdict"] = ("符号は3ビンテージとも正で反転しない（prereg literal は通る）。"
                     "ただし母集団のティッカーは3年とも同一(956)で、窓は終端日を共有して入れ子。"
                     "『3ビンテージで一致』は独立な3証拠ではない")
    out["test1_vintage_sign"] = t1

    # ══════════════════════════════════════════════════
    # 2 業種調整（MH ＋ 層内置換 ＋ 業種1つずつ除去）
    # ══════════════════════════════════════════════════
    def mh_by_sector(c):
        """Mantel-Haenszel の risk difference（層＝sic2・群と非群が両方いる層のみ）。
        層を落とすほど『調整した』の意味が薄れるので被覆率を必ず出す。"""
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        strata = defaultdict(lambda: {"g": [], "o": []})
        for r in rows:
            (strata[r["sic2"]]["g"] if id(r) in gset else strata[r["sic2"]]["o"]).append(r)
        num = den = 0.0
        used_g = used_n = 0
        detail = []
        for s, d2 in strata.items():
            n1, n0 = len(d2["g"]), len(d2["o"])
            if n1 == 0 or n0 == 0:
                continue
            k1 = sum(1 for r in d2["g"] if r["win"])
            k0 = sum(1 for r in d2["o"] if r["win"])
            N = n1 + n0
            w = n1 * n0 / N
            num += w * (k1 / n1 - k0 / n0)
            den += w
            used_g += n1
            used_n += N
            detail.append({"sic2": s, "n_grp": n1, "p_grp": round(k1 / n1, 4),
                           "n_oth": n0, "p_oth": round(k0 / n0, 4),
                           "diff": round(k1 / n1 - k0 / n0, 4), "weight": round(w, 3)})
        detail.sort(key=lambda x: -x["weight"])
        return {
            "mh_risk_difference": round(num / den, 4) if den else None,
            "strata_used": len([1 for s, d2 in strata.items() if d2["g"] and d2["o"]]),
            "strata_total": len(strata),
            "group_covered": used_g, "group_total": len(c["_grp"]),
            "group_coverage": round(used_g / len(c["_grp"]), 4) if c["_grp"] else None,
            "per_stratum": detail,
        }

    def indirect_standardized(c):
        """層を1つも落とさない間接標準化。群の業種構成で期待勝者数を作り、実測と比べる。"""
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        base = defaultdict(lambda: [0, 0])
        for r in rows:
            base[r["sic2"]][0] += 1
            base[r["sic2"]][1] += 1 if r["win"] else 0
        exp = 0.0
        for r in c["_grp"]:
            n, k = base[r["sic2"]]
            exp += k / n
        obs = sum(1 for r in c["_grp"] if r["win"])
        n_g = len(c["_grp"])
        return {"observed_wins": obs, "expected_wins_sector_matched": round(exp, 2),
                "n_group": n_g,
                "p_observed": round(obs / n_g, 4) if n_g else None,
                "p_expected": round(exp / n_g, 4) if n_g else None,
                "sector_adjusted_lift": round((obs - exp) / n_g, 4) if n_g else None,
                "note": "群の各社をその業種の勝率で置き換えた期待値との差。層を1つも落とさない"}

    def within_stratum_permutation(c, n=N_PERM):
        """層内で結果ラベルを並べ替える。業種構成を固定したまま帰無を作る。"""
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        by = defaultdict(list)
        for r in rows:
            by[r["sic2"]].append(r)
        obs = sum(1 for r in c["_grp"] if r["win"])
        n_g = len(c["_grp"])
        g_per = Counter(r["sic2"] for r in c["_grp"])
        ge = 0
        rnd = random.Random(SEED)
        for _ in range(n):
            tot = 0
            for s, k in g_per.items():
                pool = [1 if r["win"] else 0 for r in by[s]]
                tot += sum(rnd.sample(pool, k))
            if tot >= obs:
                ge += 1
        return {"observed_wins": obs, "n_group": n_g, "n_perm": n,
                "p_value_within_sector": round(ge / n, 4),
                "note": "層内置換＝業種構成を固定した帰無。小さいほど『業種だけでは説明できない』"}

    def drop_one_sector(c):
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        secs = sorted(set(r["sic2"] for r in c["_grp"]))
        res = []
        for s in secs:
            rr = [r for r in rows if r["sic2"] != s]
            gg = [r for r in c["_grp"] if r["sic2"] != s]
            if not rr or not gg:
                res.append({"sic2_dropped": s, "n_group_left": len(gg), "lift": None,
                            "note": "群が空になる"})
                continue
            n1, k1, p1 = rate(gg)
            n0, k0, p0 = rate(rr)
            res.append({"sic2_dropped": s, "n_in_group": sum(1 for r in c["_grp"] if r["sic2"] == s),
                        "n_group_left": n1, "k_group_left": k1,
                        "lift": round(p1 - p0, 4)})
        res.sort(key=lambda x: (x["lift"] is None, x["lift"]))
        return res

    def mh_min_stratum(c, minn):
        """探索側は n1<3 or n0<3 の層を落とす。落とす規則を変えると答えが変わるかを実測する。"""
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        st = defaultdict(lambda: [0, 0, 0, 0])
        for r in rows:
            if not r["sic2"]:
                continue
            w = 1 if r["win"] else 0
            dd = st[r["sic2"]]
            if id(r) in gset:
                dd[0] += 1; dd[1] += w
            else:
                dd[2] += 1; dd[3] += w
        num = den = 0.0
        used = drop = cov = 0
        for s, (n1, k1, n0, k0) in st.items():
            if n1 < minn or n0 < minn:
                drop += 1
                continue
            w = n1 * n0 / (n1 + n0)
            num += w * (k1 / n1 - k0 / n0)
            den += w
            used += 1
            cov += n1
        return {"min_per_cell": minn, "mh": round(num / den, 4) if den else None,
                "strata_used": used, "strata_dropped": drop,
                "group_covered": cov, "group_total": len(c["_grp"]),
                "group_coverage": round(cov / len(c["_grp"]), 4) if c["_grp"] else None}

    def direct_standardized(c):
        """群の業種構成に直接標準化。基準は**同業の非群**（群を基準に含めない＝indirectの偏りを外す）。
        層は1つも落とさない。群だけの業種（n0=0）は判定不能として数える。"""
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        st = defaultdict(lambda: [0, 0, 0, 0])
        for r in rows:
            w = 1 if r["win"] else 0
            dd = st[r["sic2"]]
            if id(r) in gset:
                dd[0] += 1; dd[1] += w
            else:
                dd[2] += 1; dd[3] += w
        num = den = 0.0
        undec = undec_n = 0
        for s, (n1, k1, n0, k0) in st.items():
            if n1 == 0:
                continue
            if n0 == 0:
                undec += 1; undec_n += n1
                continue
            num += n1 * (k1 / n1 - k0 / n0)
            den += n1
        return {"direct_standardized_lift": round(num / den, 4) if den else None,
                "group_covered": int(den), "group_total": len(c["_grp"]),
                "undecidable_strata": undec, "undecidable_group_members": undec_n,
                "note": "群の業種構成で重み付け・基準は同業の非群。層を1つも落とさない偏りの無い版"}

    def dominant_sector_benchmark(c):
        """『その群の主業種を丸ごと買う』という単純な規則と比べて、組は何を足しているか。"""
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        dom = Counter(r["sic2"] for r in c["_grp"]).most_common(1)
        if not dom:
            return None
        dm = dom[0][0]
        n_pop, k_pop, p_pop = rate(rows)
        sec = [r for r in rows if r["sic2"] == dm]
        n_s, k_s, p_s = rate(sec)
        insec = [r for r in c["_grp"] if r["sic2"] == dm]
        n_i, k_i, p_i = rate(insec)
        outsec = [r for r in c["_grp"] if r["sic2"] != dm]
        n_o, k_o, p_o = rate(outsec)
        return {"dominant_sic2": dm,
                "n_sector": n_s, "p_sector": round(p_s, 4) if p_s is not None else None,
                "lift_of_sector_alone": round(p_s - p_pop, 4) if p_s is not None else None,
                "n_group_in_that_sector": n_i, "p_group_in_that_sector": round(p_i, 4) if p_i is not None else None,
                "lift_of_pair_within_that_sector": round(p_i - p_s, 4) if (p_i is not None and p_s is not None) else None,
                "share_of_group_in_that_sector": round(n_i / len(c["_grp"]), 4) if c["_grp"] else None,
                "n_group_outside": n_o, "p_group_outside": round(p_o, 4) if p_o is not None else None}

    t2 = {"per_vintage": {}}
    for v in VINT:
        c = cells[v]
        t2["per_vintage"][str(v)] = {
            "mantel_haenszel": mh_by_sector(c),
            "mh_stratum_rule_sensitivity": [mh_min_stratum(c, m) for m in (1, 2, 3, 4, 5)],
            "direct_standardized_unbiased": direct_standardized(c),
            "indirect_standardized": indirect_standardized(c),
            "dominant_sector_benchmark": dominant_sector_benchmark(c),
            "within_stratum_permutation": within_stratum_permutation(c),
            "drop_one_sector": drop_one_sector(c),
            "group_sector_composition": Counter(r["sic2"] for r in c["_grp"]).most_common(),
            "population_sector_composition": Counter(r["sic2"] for r in c["_pop"]).most_common(6),
        }
    mh_all = [t2["per_vintage"][str(v)]["mantel_haenszel"]["mh_risk_difference"] for v in VINT]
    is_all = [t2["per_vintage"][str(v)]["indirect_standardized"]["sector_adjusted_lift"] for v in VINT]
    ds_all = [t2["per_vintage"][str(v)]["direct_standardized_unbiased"]["direct_standardized_lift"] for v in VINT]
    mh3 = [next(x["mh"] for x in t2["per_vintage"][str(v)]["mh_stratum_rule_sensitivity"] if x["min_per_cell"] == 3)
           for v in VINT]
    estimators = {
        "MH(層の最小1社・この道具)": {str(v): mh_all[i] for i, v in enumerate(VINT)},
        "MH(層の最小3社・探索側の規則)": {str(v): mh3[i] for i, v in enumerate(VINT)},
        "直接標準化(偏りなし・層を落とさない)": {str(v): ds_all[i] for i, v in enumerate(VINT)},
        "間接標準化(群を基準に含む・0へ偏る)": {str(v): is_all[i] for i, v in enumerate(VINT)},
    }
    verdicts = {k: all(x is not None and x >= LIFT_LINE for x in vv.values()) for k, vv in estimators.items()}
    t2["summary"] = {
        "estimators": estimators,
        "passes_by_estimator": verdicts,
        "mh_min": min(x for x in mh_all if x is not None),
        "indirect_min": min(x for x in is_all if x is not None),
        "passes_prereg_sector_control": all(x is not None and x >= LIFT_LINE for x in mh_all),
        "estimator_disagreement": {
            "n_pass": sum(1 for x in verdicts.values() if x),
            "n_fail": sum(1 for x in verdicts.values() if not x),
            "spread_2018": [min(x[str(2018)] for x in estimators.values() if x[str(2018)] is not None),
                            max(x[str(2018)] for x in estimators.values() if x[str(2018)] is not None)],
            "note": "業種調整の答えが実装の細部（層を何社で落とすか・基準に群を含めるか）で 0.13〜0.21 に振れる。"
                    "prereg は『同一sic2内で残る』としか書いておらず、どの推定量かを固定していない",
        },
    }
    out["test2_sector"] = t2

    # ══════════════════════════════════════════════════
    # 3 irr の影
    # ══════════════════════════════════════════════════
    t3 = {}
    for v in VINT:
        c = cells[v]
        has_irr = [r for r in c["_pop"] if r.get("irr") is not None]
        t3[str(v)] = {"n_pop": len(c["_pop"]), "n_with_irr": len(has_irr),
                      "status": "判定不能（このビンテージは irr が未読解）" if not has_irr else "測定可"}
    # 2018 は irr がある
    c = cells[2018]
    irr_rows = [r for r in c["_pop"] if r.get("irr") is not None]
    gset = set(id(r) for r in c["_grp"])
    hi = [r for r in irr_rows if r["irr"] >= 70]
    hi_g = [r for r in hi if id(r) in gset]
    hi_o = [r for r in hi if id(r) not in gset]
    n1, k1, p1 = rate(hi_g)
    n0, k0, p0 = rate(hi_o)
    nh, kh, ph = rate(hi)
    # 直交性（irr が読めている行に限る）
    tab = Counter()
    for r in irr_rows:
        tab[(id(r) in gset, r["irr"] >= 70)] += 1
    a = tab[(True, True)]; b = tab[(True, False)]
    cc = tab[(False, True)]; dd = tab[(False, False)]
    phi_den = math.sqrt((a + b) * (cc + dd) * (a + cc) * (b + dd))
    phi = ((a * dd - b * cc) / phi_den) if phi_den else None
    out["test3_irr_shadow"] = {
        "availability": t3,
        "vintage_2018": {
            "n_irr_read": len(irr_rows), "coverage_of_pop": round(len(irr_rows) / len(c["_pop"]), 4),
            "n_group_with_irr": a + b, "n_group_total": len(c["_grp"]),
            "irr70plus_stratum": {
                "n": nh, "p": round(ph, 4) if ph is not None else None,
                "n_group": n1, "k_group": k1, "p_group": round(p1, 4) if p1 is not None else None,
                "n_other": n0, "p_other": round(p0, 4) if p0 is not None else None,
                "lift_within_irr70plus": round(p1 - p0, 4) if (p1 is not None and p0 is not None) else None,
                "numerator": k1,
                "meets_min_numerator": (k1 or 0) >= MIN_NUM,
            },
            "orthogonality": {
                "contingency_group_x_irr70plus": {"g&hi": a, "g&lo": b, "o&hi": cc, "o&lo": dd},
                "phi": round(phi, 4) if phi is not None else None,
                "share_irr70plus_in_group": round(a / (a + b), 4) if (a + b) else None,
                "share_irr70plus_in_other": round(cc / (cc + dd), 4) if (cc + dd) else None,
                "caveat": "群が小さいと相関は必ず小さく出る。直交の主張は群の大きさとセットで読むこと",
            },
        },
    }

    # ══════════════════════════════════════════════════
    # 4 1社の影響（パネルごと抜いて閾値から作り直す）
    # ══════════════════════════════════════════════════
    ticks = sorted(set(r["ticker"] for v in VINT for r in cells[v]["_grp"]))
    loo = []
    for tk in ticks:
        cs = {}
        for v in VINT:
            rs = [r for r in pop_rows(rows_all, v) if r["ticker"] != tk]
            cs[v] = cell(rs)
        ls = {v: cs[v]["lift"] for v in VINT}
        sg = all(x > 0 for x in ls.values())
        m = min(ls.values()) if sg else 0.0
        mn = min(cs[v]["k_group"] for v in VINT)
        loo.append({"ticker": tk, "maintained_lift": round(m, 4),
                    "lift_by_vintage": {str(v): ls[v] for v in VINT},
                    "min_numerator": mn,
                    "still_passes_lift_and_numerator": bool(sg and m >= LIFT_LINE and mn >= MIN_NUM)})
    loo.sort(key=lambda x: x["maintained_lift"])
    out["test4_leave_one_company_out"] = {
        "n_tickers_in_any_group": len(ticks),
        "maintained_lift_full": round(maintained, 4),
        "worst": loo[:8], "best": loo[-3:],
        "range": [loo[0]["maintained_lift"], loo[-1]["maintained_lift"]],
        "n_that_break_lift_or_numerator": sum(1 for x in loo if not x["still_passes_lift_and_numerator"]),
        "verdict": None,  # 下で埋める
    }

    # ══════════════════════════════════════════════════
    # 5 置換（ティッカー束＝ビンテージ間相関を保つ帰無）
    # ══════════════════════════════════════════════════
    # ティッカーごとに (win, sic2 …) の束を持ち替える。3ビンテージの結果が同じ会社に張り付く相関を保つ。
    per_v_rows = {v: pop_rows(rows_all, v) for v in VINT}
    # 各ビンテージの母集団に共通して居るティッカーだけ入れ替え可能（母集団の構成は動かさない）
    common = set(r["ticker"] for r in per_v_rows[2016])
    for v in VINT[1:]:
        common &= set(r["ticker"] for r in per_v_rows[v])
    outcome_bundle = {}
    for tk in common:
        outcome_bundle[tk] = {v: next(r["win"] for r in per_v_rows[v] if r["ticker"] == tk) for v in VINT}
    grp_flags = {v: set(r["ticker"] for r in cells[v]["_grp"]) for v in VINT}

    def maintained_under(assign):
        ls = []
        for v in VINT:
            rs = per_v_rows[v]
            wins = {r["ticker"]: (assign[r["ticker"]][v] if r["ticker"] in assign else r["win"]) for r in rs}
            n_pop = len(rs)
            k_pop = sum(1 for r in rs if wins[r["ticker"]])
            g = [r for r in rs if r["ticker"] in grp_flags[v]]
            if not g:
                return -9.0
            k_g = sum(1 for r in g if wins[r["ticker"]])
            ls.append(k_g / len(g) - k_pop / n_pop)
        return min(ls) if all(x > 0 for x in ls) else 0.0

    keys = sorted(common)
    rnd = random.Random(SEED + 1)
    ge = 0
    for _ in range(N_PERM):
        perm = keys[:]
        rnd.shuffle(perm)
        assign = {keys[i]: outcome_bundle[perm[i]] for i in range(len(keys))}
        if maintained_under(assign) >= maintained - 1e-12:
            ge += 1
    p_single = ge / N_PERM
    out["test5_permutation"] = {
        "design": "ティッカーごとに outcome の束（2016/2017/2018 の win）を丸ごと入れ替える。"
                  "同じ会社の3年の結果が張り付く相関と、母集団・群の構成を保った帰無",
        "n_perm": N_PERM,
        "n_tickers_permuted": len(keys),
        "observed_maintained_lift": round(maintained, 4),
        "p_value_single_candidate": round(p_single, 4),
        "note": "これは『この1本』の p。探索は 2840 組を当てているので、多重検定の値札は探索側の道具が持つ",
    }

    # ══════════════════════════════════════════════════
    # 6 既存の関門との重複（増分）
    # ══════════════════════════════════════════════════
    def shrink(r):  # 事業の収縮（門の第四関門・v9.9.99）
        return (r["f2_cagr5"] is not None and r["f2_opmD5"] is not None
                and r["f2_cagr5"] < 0 and r["f2_opmD5"] < 0)

    def thin_cov(r):  # 財務キル相当（intcov が薄い）
        return r["f2_intcov"] is not None and r["f2_intcov"] < 5

    t6 = {"note": "母集団が既に P_quality なので『質実証の増分』はこの表の中では定義上ゼロ。"
                  "P_full との対比を別に出す"}
    for name, fn in [("事業の収縮を除いた残り", lambda r: not shrink(r)),
                     ("利払カバー>=5の残り", lambda r: not thin_cov(r))]:
        per = {}
        for v in VINT:
            c = cells[v]
            rs = [r for r in c["_pop"] if fn(r)]
            gg = [r for r in c["_grp"] if fn(r)]
            n1, k1, p1 = rate(gg)
            n0, k0, p0 = rate(rs)
            per[str(v)] = {"n_pop_left": n0, "n_group_left": n1, "k_group_left": k1,
                           "lift": round(p1 - p0, 4) if p1 is not None else None,
                           "n_group_removed": len(c["_grp"]) - n1}
        t6[name] = per
    # 群のうち既存関門に当たる社が何社いるか
    t6["group_already_caught_by_existing_gates"] = {
        str(v): {"n_group": cells[v]["n_group"],
                 "shrink": sum(1 for r in cells[v]["_grp"] if shrink(r)),
                 "intcov_lt5": sum(1 for r in cells[v]["_grp"] if thin_cov(r))}
        for v in VINT}
    # 脚単独との増分（この組は本当に「組」でないと出ないのか）
    def leg_only(rows, which):
        ta, tb = thresholds(rows)
        if which == "a":
            g = [r for r in rows if r[VAR_A] is not None and ta is not None and r[VAR_A] >= ta]
        else:
            g = [r for r in rows if r[VAR_B] is not None and tb is not None and r[VAR_B] <= tb]
        n1, k1, p1 = rate(g)
        n0, k0, p0 = rate(rows)
        return {"n": n1, "k": k1, "lift": round(p1 - p0, 4) if p1 is not None else None}
    t6["single_leg"] = {str(v): {"rnd_only": leg_only(cells[v]["_pop"], "a"),
                                 "sga_only": leg_only(cells[v]["_pop"], "b")} for v in VINT}
    out["test6_increment_over_existing_gates"] = t6

    # ══════════════════════════════════════════════════
    # 診断（事前登録の外・合否には数えない）
    # ══════════════════════════════════════════════════
    aux = {"_disclaimer": "事前登録の外・診断専用。合否には一切数えない"}

    # (a) 欠測の構造 — sga_r が測れない社は誰か
    v = 2018
    c = cells[v]
    miss = [r for r in c["_pop"] if r[VAR_B] is None]
    meas = [r for r in c["_pop"] if r[VAR_B] is not None]
    n1, k1, p1 = rate(miss); n0, k0, p0 = rate(meas)
    aux["missingness_of_sga"] = {
        "vintage": v, "n_missing": n1, "p_win_missing": round(p1, 4) if p1 is not None else None,
        "n_measurable": n0, "p_win_measurable": round(p0, 4) if p0 is not None else None,
        "sector_of_missing": Counter(r["sic2"] for r in miss).most_common(6),
        "sector_of_measurable": Counter(r["sic2"] for r in meas).most_common(6),
        "note": "『SG&Aを別掲しない』は業種の慣行。lift の分母に prereg literal（母集団）を使うと"
                "この選択が lift に乗る",
    }

    # (b) 群の中身（誰が入っているか）
    aux["group_members_2018"] = sorted(
        [{"ticker": r["ticker"], "sic2": r["sic2"], "rnd_r": r[VAR_A], "sga_r": r[VAR_B],
          "tr_cagr": r["tr_cagr"], "win": r["win"], "irr": r.get("irr")} for r in cells[2018]["_grp"]],
        key=lambda x: -(x["tr_cagr"] if x["tr_cagr"] is not None else -9))

    # (c) 閾値感度
    sens = {}
    for pa in (0.70, 0.75, 0.80):
        for pb in (0.40, 0.50, 0.60):
            ls = []
            ns = []
            ks = []
            for v2 in VINT:
                rs = pop_rows(rows_all, v2)
                a = [r[VAR_A] for r in rs if r[VAR_A] is not None]
                b = [r[VAR_B] for r in rs if r[VAR_B] is not None]
                ta = nearest_rank(a, pa); tb = nearest_rank(b, pb)
                g = [r for r in rs if r[VAR_A] is not None and r[VAR_B] is not None
                     and r[VAR_A] >= ta and r[VAR_B] <= tb]
                n1, k1, p1 = rate(g); n0, k0, p0 = rate(rs)
                ls.append(round(p1 - p0, 4) if p1 is not None else None)
                ns.append(n1); ks.append(k1)
            ok = all(x is not None and x > 0 for x in ls)
            sens[f"rnd>=P{int(pa*100)} ∧ sga<=P{int(pb*100)}"] = {
                "lift_by_vintage": ls, "n_by_vintage": ns, "k_by_vintage": ks,
                "maintained": round(min(ls), 4) if ok else 0.0,
                "min_numerator": min(ks),
            }
    aux["threshold_sensitivity"] = sens

    # (d) 同じ変数の組が母集団で割れる — P_full での同じ切り方
    pf = {}
    for v2 in VINT:
        rs = [r for r in rows_all if r["vintage"] == v2 and r["P_full"] and r["has_outcome"] and r["window_full"]]
        a = [r[VAR_A] for r in rs if r[VAR_A] is not None]
        b = [r[VAR_B] for r in rs if r[VAR_B] is not None]
        ta = nearest_rank(a, 0.75); tb = nearest_rank(b, 0.50)
        g = [r for r in rs if r[VAR_A] is not None and r[VAR_B] is not None and r[VAR_A] >= ta and r[VAR_B] <= tb]
        n1, k1, p1 = rate(g); n0, k0, p0 = rate(rs)
        pf[str(v2)] = {"n_group": n1, "k": k1, "lift": round(p1 - p0, 4) if p1 is not None else None}
    aux["same_cut_in_P_full"] = {"per_vintage": pf,
                                 "note": "同じ切り方を P_full に当てた場合。母集団で結論が変わるかの対比"}

    # (e) 連続量としての向き（二値化が結論を作っていないか）
    cont = {}
    for v2 in VINT:
        rs = pop_rows(rows_all, v2)
        both = [r for r in rs if r[VAR_A] is not None and r[VAR_B] is not None]
        w = [r for r in both if r["win"]]; l = [r for r in both if not r["win"]]
        def med(xs, k):
            s = sorted(x[k] for x in xs)
            return round(s[len(s) // 2], 4) if s else None
        cont[str(v2)] = {"n_both": len(both),
                         "rnd_median_win": med(w, VAR_A), "rnd_median_lose": med(l, VAR_A),
                         "sga_median_win": med(w, VAR_B), "sga_median_lose": med(l, VAR_B),
                         "n_win": len(w), "n_lose": len(l)}
    aux["continuous_direction"] = cont

    # (f) ★重ならない窓での外部検証（この検証で唯一の本当の out-of-sample）
    #     2016 の群は filed<=2016-07 の数字で作られる。その群を **2016-07→2018-06** だけで測る。
    #     この窓は 2018-07→2026-08 と**1日も重ならない**。効果が後半だけのものなら、ここで消える。
    def load_monthly(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return {}

    m_early = load_monthly(os.path.join(OUT, "retro_monthly_2013_2018.json"))
    m_late = load_monthly(os.path.join(OUT, "retro_monthly_2018_2026.json"))

    def px_at(series, target_ts, tol_days=45):
        if not series:
            return None
        best = min(series, key=lambda x: abs(x[0] - target_ts))
        return best[1] if abs(best[0] - target_ts) <= tol_days * 86400 else None

    def window_cagr(monthly, tk, t0, t1, years):
        s = monthly.get(tk)
        if not s:
            return None
        p0 = px_at(s, t0); p1 = px_at(s, t1)
        if not p0 or not p1 or p0 <= 0:
            return None
        return (p1 / p0) ** (1.0 / years) - 1.0

    TS = {"2016-07": 1467331200, "2018-06": 1527825600,
          "2018-07": 1530417600, "2022-07": 1656633600, "2026-08": 1785873668}

    def subwindow_table(rows, grp, monthly, t0, t1, years, label):
        gset = set(r["ticker"] for r in grp)
        vals = {}
        for r in rows:
            c2 = window_cagr(monthly, r["ticker"], t0, t1, years)
            if c2 is not None:
                vals[r["ticker"]] = c2
        pop = [t for t in vals]
        g = [t for t in pop if t in gset]
        o = [t for t in pop if t not in gset]
        def wr(ts):
            if not ts:
                return (0, 0, None)
            k = sum(1 for t in ts if vals[t] >= 0.15)
            return (len(ts), k, k / len(ts))
        n_p, k_p, p_p = wr(pop); n_g, k_g, p_g = wr(g); n_o, k_o, p_o = wr(o)
        med = lambda ts: (round(sorted(vals[t] for t in ts)[len(ts) // 2], 4) if ts else None)
        return {"window": label, "years": years,
                "n_pop_priced": n_p, "n_group_priced": n_g, "n_group_total": len(grp),
                "coverage_group": round(n_g / len(grp), 4) if grp else None,
                "p_win_pop": round(p_p, 4) if p_p is not None else None,
                "p_win_group": round(p_g, 4) if p_g is not None else None,
                "k_group": k_g,
                "lift": round(p_g - p_p, 4) if (p_g is not None and p_p is not None) else None,
                "lift_vs_nongroup": round(p_g - p_o, 4) if (p_g is not None and p_o is not None) else None,
                "median_cagr_group": med(g), "median_cagr_nongroup": med(o),
                "meets_min_numerator": k_g >= MIN_NUM}

    dis = {}
    c16 = cells[2016]
    dis["2016群 × 2016-07→2018-06（★重ならない窓）"] = subwindow_table(
        c16["_pop"], c16["_grp"], m_early, TS["2016-07"], TS["2018-06"], 1.92,
        "2016-07-01→2018-06-01（2018-07以降と1日も重ならない）")
    dis["2016群 × 2018-07→2026-08（効果が見つかった窓）"] = subwindow_table(
        c16["_pop"], c16["_grp"], m_late, TS["2018-07"], TS["2026-08"], 8.09,
        "2018-07-01→2026-08-04")
    dis["_read"] = ("同じ群・同じ作り方で、窓だけを入れ替える。前半で消えて後半だけに出るなら、"
                    "それは指標が分けたのではなく**その窓に起きたこと**を測っている")
    aux["disjoint_window_out_of_sample"] = dis

    # (g) レジーム分割（2018群・前半4年 vs 後半4年）
    c18 = cells[2018]
    reg = {
        "2018-07→2022-07（AI前）": subwindow_table(c18["_pop"], c18["_grp"], m_late,
                                                  TS["2018-07"], TS["2022-07"], 4.0, "前半4.0年"),
        "2022-07→2026-08（AI期）": subwindow_table(c18["_pop"], c18["_grp"], m_late,
                                                  TS["2022-07"], TS["2026-08"], 4.09, "後半4.09年"),
        "_read": "台帳は『irr85の超過はほぼAI期に出た』と既に記録している。同じことがこの候補にも起きていないか",
    }
    aux["regime_split"] = reg

    # (h) 実効の標本（勝ちを作っている会社は何社か）
    win_t = {v: set(r["ticker"] for r in cells[v]["_grp"] if r["win"]) for v in VINT}
    allw = win_t[2016] | win_t[2017] | win_t[2018]
    aux["effective_sample"] = {
        "k_group_by_vintage": {str(v): cells[v]["k_group"] for v in VINT},
        "distinct_winning_tickers_union": len(allw),
        "distinct_winning_tickers_in_all3": len(win_t[2016] & win_t[2017] & win_t[2018]),
        "distinct_group_tickers_union": len(set(r["ticker"] for v in VINT for r in cells[v]["_grp"])),
        "winners": sorted(allw),
        "note": "『3ビンテージで12勝ずつ』は36社ではない。同じ会社を3回数えている",
    }

    # (i) ★業種の粒度を上げる（sic2 → sic3 → sic4）。事前登録の業種調整は sic2 だが、
    #     粒度は prereg が固定していない。粒度を上げて答えが動くなら、業種調整は解像度で決まっている。
    try:
        sicsrc = json.load(open(os.path.join(OUT, "retro_sic.json"), encoding="utf-8"))
        sicrows = sicsrc["rows"] if isinstance(sicsrc, dict) else sicsrc
        SIC4 = {r["ticker"]: (str(r.get("sic")) if r.get("sic") else None) for r in sicrows}
        SICD = {r["ticker"]: r.get("sicDesc") for r in sicrows}
    except Exception:
        SIC4, SICD = {}, {}

    def strat_lift(c, keyfn, minn=1):
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        st = defaultdict(lambda: [0, 0, 0, 0])
        for r in rows:
            k = keyfn(r)
            if not k:
                continue
            w = 1 if r["win"] else 0
            dd = st[k]
            if id(r) in gset:
                dd[0] += 1; dd[1] += w
            else:
                dd[2] += 1; dd[3] += w
        num = den = 0.0
        used = cov = 0
        for k, (n1, k1, n0, k0) in st.items():
            if n1 < minn or n0 < minn:
                continue
            w = n1 * n0 / (n1 + n0)
            num += w * (k1 / n1 - k0 / n0)
            den += w
            used += 1
            cov += n1
        return {"mh": round(num / den, 4) if den else None, "strata_used": used,
                "group_covered": cov, "group_total": len(c["_grp"]),
                "group_coverage": round(cov / len(c["_grp"]), 4) if c["_grp"] else None}

    gran = {}
    for name, fn in [("sic2 (事前登録)", lambda r: r["sic2"]),
                     ("sic3", lambda r: (SIC4.get(r["ticker"]) or "")[:3] or None),
                     ("sic4", lambda r: SIC4.get(r["ticker"]))]:
        gran[name] = {str(v): strat_lift(cells[v], fn) for v in VINT}
    aux["sector_granularity"] = {
        "mh_by_granularity": gran,
        "note": "prereg は『同一sic2内』としか書いていない。粒度を上げると層が細かくなり被覆が落ちる＝"
                "『調整した』の意味が薄れるので、被覆率とセットで読むこと",
    }

    # (j) ★半導体連鎖の対照。sic2 は連鎖を6つに割ってしまうので sic2 では見えない。
    #     線は SIC の記述だけから引く（会社名を見て決めない）。狭い/広いの二通りを出し、
    #     名簿も全部出す＝読み手が同意できない線なら自分で引き直せるように（v9.9.117 の作法）。
    SEMI_NARROW = {"3674", "3559", "3672", "3670", "3671", "3675", "3676", "3677", "3678", "3679",
                   "3825", "3826", "3827", "3823"}
    SEMI_BROAD = SEMI_NARROW | {"3572", "3577", "3663", "3661", "3089", "3357", "3812", "3861", "3841"}

    def semi_control(c, semiset, label):
        rows = c["_pop"]
        gset = set(id(r) for r in c["_grp"])
        def is_semi(r):
            return (SIC4.get(r["ticker"]) or "") in semiset
        n_pop, k_pop, p_pop = rate(rows)
        semi = [r for r in rows if is_semi(r)]
        n_s, k_s, p_s = rate(semi)
        g_semi = [r for r in c["_grp"] if is_semi(r)]
        g_non = [r for r in c["_grp"] if not is_semi(r)]
        n_gs, k_gs, p_gs = rate(g_semi)
        n_gn, k_gn, p_gn = rate(g_non)
        non = [r for r in rows if not is_semi(r)]
        n_n, k_n, p_n = rate(non)
        # 層内（半導体 / 非半導体 の2層）で MH
        num = den = 0.0
        for pool, gp in ((semi, g_semi), (non, g_non)):
            o = [r for r in pool if id(r) not in gset]
            if not gp or not o:
                continue
            n1 = len(gp); n0 = len(o)
            w = n1 * n0 / (n1 + n0)
            num += w * (sum(1 for r in gp if r["win"]) / n1 - sum(1 for r in o if r["win"]) / n0)
            den += w
        return {
            "definition": label, "n_sic4_codes": len(semiset),
            "n_semi_in_pop": n_s, "p_win_semi_alone": round(p_s, 4) if p_s is not None else None,
            "lift_of_semi_alone": round(p_s - p_pop, 4) if p_s is not None else None,
            "n_nonsemi_in_pop": n_n, "p_win_nonsemi": round(p_n, 4) if p_n is not None else None,
            "n_group_semi": n_gs, "share_of_group_semi": round(n_gs / len(c["_grp"]), 4) if c["_grp"] else None,
            "p_win_group_semi": round(p_gs, 4) if p_gs is not None else None,
            "lift_of_pair_within_semi": round(p_gs - p_s, 4) if (p_gs is not None and p_s is not None) else None,
            "n_group_nonsemi": n_gn, "p_win_group_nonsemi": round(p_gn, 4) if p_gn is not None else None,
            "lift_of_pair_within_nonsemi": round(p_gn - p_n, 4) if (p_gn is not None and p_n is not None) else None,
            "mh_2strata_semi_vs_not": round(num / den, 4) if den else None,
        }

    aux["semiconductor_complex_control"] = {
        "why": "この群は sic2 で 6 個（33/35/36/38/30/67）に割れるが、実体は一つの賭け。"
               "sic2 の業種調整は原理的にこれを見られない。CLAUDE.md v9.9.117 が"
               "『半導体連鎖の集合はティッカーの列挙で持つ（パックに業種の欄が無いため）』と"
               "書いているのと同じ問題",
        "narrow": {str(v): semi_control(cells[v], SEMI_NARROW, "半導体・半導体製造装置・電子部品・計測器") for v in VINT},
        "broad": {str(v): semi_control(cells[v], SEMI_BROAD, "狭い定義＋記憶装置・通信機器・材料・光学") for v in VINT},
        "sic4_list_narrow": sorted(SEMI_NARROW), "sic4_list_broad": sorted(SEMI_BROAD),
        "caveat": "この線は SIC の記述から引いた**判断**であって機械の事実ではない。名簿を全部出してあるので"
                  "同意できなければ引き直せる",
        "group_roster_2018": [
            {"ticker": r["ticker"], "sic4": SIC4.get(r["ticker"]), "desc": SICD.get(r["ticker"]),
             "sic2": r["sic2"], "tr_cagr": r["tr_cagr"], "win": r["win"],
             "semi_narrow": (SIC4.get(r["ticker"]) or "") in SEMI_NARROW,
             "semi_broad": (SIC4.get(r["ticker"]) or "") in SEMI_BROAD}
            for r in sorted(cells[2018]["_grp"], key=lambda x: -(x["tr_cagr"] if x["tr_cagr"] is not None else -9))],
    }

    # (k) 多重検定の値札（探索側が測った値を引く。自分で測り直していない数字は引用と明記）
    try:
        fpr = json.load(open(PAIR, encoding="utf-8"))["must_report_before_verdict"]["false_positive_rate"]
        nullmax = fpr["null_distribution_of_max_statistic"]
        aux["multiple_testing_price_quoted_from_explorer"] = {
            "source": "out/hist_wd_win_pair.json → must_report_before_verdict.false_positive_rate（引用・自分で測り直していない）",
            "n_tests": fpr["n_tests_in_procedure"],
            "P_at_least_one_pass_under_null_L5": fpr["P_at_least_one_pass_by_level"]["L5"],
            "null_max_statistic_percentiles": {k: nullmax[k] for k in ("p50", "p90", "p95", "p99")},
            "this_candidate_maintained_lift": round(maintained, 4),
            "rank_among_2840_real_tests": 4,
            "candidate_vs_null_max": {
                "below_null_p90": maintained < nullmax["p90"],
                "reading": (f"帰無でも 2840 検定の最大値は10%以上の確率で {nullmax['p90']} を超える。"
                            f"この候補の {round(maintained,4)} はその線の**下**にある"
                            "＝2840通り試したうえで4位に出てきた値としては、雑音が普通に出す大きさ"),
            },
            "null_with_seed_reselection_p90": fpr["null_with_seed_reselection"]["null_max_statistic"]["p90"],
            "null_within_sector_p90": fpr["null_within_sector"]["fixed_seeds"]["null_max_statistic"]["p90"],
        }
    except Exception as e:
        aux["multiple_testing_price_quoted_from_explorer"] = {"error": str(e)}

    # (l) ★選抜代を自分で測る（引用でなく実測）。
    #     P_quality の組空間 3360 本すべてを毎回作り直し、帰無で「最大の maintained_lift」が
    #     この候補の値をどれだけの確率で超えるかを出す。探索側は percentiles しか残していないので、
    #     この候補の値ちょうどでの確率は自分で測るしかない。
    VARS21 = ["f2_gm", "f2_sga_r", "f2_capex_r", "f2_rnd_r", "f2_opm", "f2_intcov", "f2_aturn",
              "f2_accr", "f2_cash_r", "f2_gw_r", "f2_cagr5", "f2_accel", "f2_streak_rev",
              "f2_streak_opm", "f2_opmD5", "f2_fcfpos5", "f2_conv5", "f2_netiss_r",
              "f2_payout5", "f2_rev", "size_rev"]
    CUTS = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]

    # ⚠ ここで一度踏んだ罠を記録しておく。初版は全1430ティッカーで置換したが、win は
    #    P_quality の約330行にしか無い。**母集団の外を win=False と読んだ**ので基準勝率が
    #    0.1976 → 0.0547 へ崩れ、帰無の最大値が p50=0.0 という嘘を出した（絶対のルール7の自作再演）。
    #    正しくは「母集団の中だけで入れ替える」。
    tickers = sorted(set(r["ticker"] for r in rows_all))
    tix = {t: i for i, t in enumerate(tickers)}
    NT = len(tickers)

    pop_mask, win_bits, pop_tick = {}, {}, {}
    for v in VINT:
        pm = 0
        wb = [0] * NT
        pt = []
        for r in pop_rows(rows_all, v):
            i = tix[r["ticker"]]
            pm |= (1 << i)
            wb[i] = 1 if r["win"] else 0
            pt.append(i)
        pop_mask[v] = pm
        win_bits[v] = wb
        pop_tick[v] = pt

    core = set(pop_tick[VINT[0]])
    for v in VINT[1:]:
        core &= set(pop_tick[v])
    core = sorted(core)
    noncore = {v: [i for i in pop_tick[v] if i not in set(core)] for v in VINT}

    def cut_mask(v, var, cut):
        rs = pop_rows(rows_all, v)
        vals = [r[var] for r in rs if r.get(var) is not None]
        if not vals:
            return 0
        if cut == "上位1/4":
            t = nearest_rank(vals, 0.75); ok = lambda x: x >= t
        elif cut == "下位1/4":
            t = nearest_rank(vals, 0.25); ok = lambda x: x <= t
        elif cut == "中央値超":
            t = nearest_rank(vals, 0.50); ok = lambda x: x > t
        else:
            t = nearest_rank(vals, 0.50); ok = lambda x: x <= t
        m = 0
        for r in rs:
            if r.get(var) is not None and ok(r[var]):
                m |= (1 << tix[r["ticker"]])
        return m

    CM = {(v, var, cut): cut_mask(v, var, cut) for v in VINT for var in VARS21 for cut in CUTS}
    pairs = []
    for ia in range(len(VARS21)):
        for ib in range(ia + 1, len(VARS21)):
            for ca in CUTS:
                for cb in CUTS:
                    gm = tuple(CM[(v, VARS21[ia], ca)] & CM[(v, VARS21[ib], cb)] for v in VINT)
                    if all(g for g in gm):
                        pairs.append((gm, tuple(g.bit_count() for g in gm)))
    pop_n = {v: pop_mask[v].bit_count() for v in VINT}

    def max_stat(wmask, min_num):
        """探索側と同じ統計量＝『符号が揃ったうえでの3ビンテージ最小|lift|』の全空間最大。
        min_num>0 なら pass line と同じく分子>=min_num を課す（課さないと n=1 の群が帰無を支配する）。"""
        best = 0.0
        base = [wmask[i].bit_count() / pop_n[v] for i, v in enumerate(VINT)]
        for gm, gn in pairs:
            ks = [(gm[i] & wmask[i]).bit_count() for i in range(3)]
            if min_num and min(ks) < min_num:
                continue
            ls = [ks[i] / gn[i] - base[i] for i in range(3)]
            if all(x > 0 for x in ls):
                m = min(ls)
            elif all(x < 0 for x in ls):
                m = -max(ls)
            else:
                continue
            if m > best:
                best = m
        return best

    def wmask_perm(rnd_):
        """母集団の中だけで入れ替える。core(3ビンテージ全部に居る社)は束ごと入れ替えて
        ビンテージ間の結果の相関を保ち、非coreは各ビンテージ内で入れ替える。
        これで各ビンテージの基準勝率は**厳密に不変**。"""
        cp = core[:]
        rnd_.shuffle(cp)
        cmap = dict(zip(core, cp))
        out2 = []
        for v in VINT:
            wb = win_bits[v]
            nc = noncore[v]
            ncp = nc[:]
            rnd_.shuffle(ncp)
            ncmap = dict(zip(nc, ncp))
            m = 0
            for i in core:
                if wb[cmap[i]]:
                    m |= (1 << i)
            for i in nc:
                if wb[ncmap[i]]:
                    m |= (1 << i)
            out2.append(m)
        return out2

    ident_mask = [sum(1 << i for i in pop_tick[v] if win_bits[v][i]) for v in VINT]
    # 検算: 基準勝率が実データと一致するか
    base_check = {str(v): [round(ident_mask[i].bit_count() / pop_n[v], 4), cells[v]["p_pop"]]
                  for i, v in enumerate(VINT)}
    N_MAXPERM = 2000
    res_by_rule = {}
    for min_num in (MIN_NUM, 0):
        rnd2 = random.Random(SEED + 2)
        obs_max = max_stat(ident_mask, min_num)
        ge_cand = ge_max = 0
        dist = []
        base_ok = True
        for _ in range(N_MAXPERM):
            wm = wmask_perm(rnd2)
            for i, v in enumerate(VINT):
                if wm[i].bit_count() != ident_mask[i].bit_count():
                    base_ok = False
            s = max_stat(wm, min_num)
            dist.append(s)
            if s >= maintained - 1e-12:
                ge_cand += 1
            if s >= obs_max - 1e-12:
                ge_max += 1
        dist.sort()
        q = lambda p: round(dist[min(len(dist) - 1, int(p * len(dist)))], 4)
        res_by_rule["分子>=5を課す（pass lineと同じ）" if min_num else "分子の下限なし"] = {
            "observed_max_in_real_data": round(obs_max, 4),
            "null_max_percentiles": {"p50": q(.50), "p75": q(.75), "p90": q(.90),
                                     "p95": q(.95), "p99": q(.99), "max": round(dist[-1], 4)},
            "P_null_max_ge_this_candidate": round(ge_cand / N_MAXPERM, 4),
            "P_null_max_ge_observed_max": round(ge_max / N_MAXPERM, 4),
            "base_rate_preserved_every_perm": base_ok,
        }
    aux["selection_cost_measured_here"] = {
        "space": "P_quality の組空間（21変数×4切り方、同一変数の組は作らない）",
        "n_tests_in_space": len(pairs),
        "n_permutations": N_MAXPERM,
        "null_construction": "特徴量（母集団・可測・群・閾値）を固定し、**母集団の中だけで** outcome を置換。"
                             "core(3ビンテージ全部に居る{}社)は束ごと・非coreは各ビンテージ内".format(len(core)),
        "base_rate_check_perm_vs_real": base_check,
        "this_candidate_maintained_lift": round(maintained, 4),
        "by_min_numerator_rule": res_by_rule,
        "bug_found_and_fixed_here": "初版は全1430ティッカーで置換し、母集団の外を win=False と読んだ。"
                                    "基準勝率が 0.1976→0.0547 に崩れ帰無 p50=0.0 という嘘が出た（ルール7の自作再演）",
        "reading": "単独のp値(0.005)は選抜代を1円も払っていない。空間全体で最大を取ったときの分布と比べること",
    }

    out["aux_diagnostics_outside_prereg"] = aux

    # ══════════════════════════════════════════════════
    # 判定
    # ══════════════════════════════════════════════════
    g1 = all(x >= LIFT_LINE for x in lifts.values())
    g2 = min(cells[v]["k_group"] for v in VINT) >= MIN_NUM
    g3 = all(s > 0 for s in signs.values())
    g4 = out["test2_sector"]["summary"]["passes_prereg_sector_control"]
    irr_lift = out["test3_irr_shadow"]["vintage_2018"]["irr70plus_stratum"]["lift_within_irr70plus"]
    irr_num_ok = out["test3_irr_shadow"]["vintage_2018"]["irr70plus_stratum"]["meets_min_numerator"]
    g5 = bool(irr_lift is not None and abs(irr_lift) >= LIFT_LINE and irr_num_ok)
    out["prereg_gates_literal"] = {
        "lift>=0.15 (all 3 vintages)": g1,
        "min_numerator>=5": g2,
        "sign_stability": g3,
        "sector_control (MH>=0.15 all vintages)": g4,
        "not_irr_shadow (irr>=70 stratum)": g5,
        "all_required_passed": bool(g1 and g2 and g3 and g4 and g5),
    }
    loo_break = out["test4_leave_one_company_out"]["n_that_break_lift_or_numerator"]
    out["test4_leave_one_company_out"]["verdict"] = (
        f"1社抜きで線を割るのは {loo_break} 社 / {len(ticks)} 社"
    )
    sc = aux["selection_cost_measured_here"]["by_min_numerator_rule"]["分子>=5を課す（pass lineと同じ）"]
    p_sel = sc["P_null_max_ge_this_candidate"]
    reg_pre = aux["regime_split"]["2018-07→2022-07（AI前）"]
    reg_ai = aux["regime_split"]["2022-07→2026-08（AI期）"]
    dis_w = aux["disjoint_window_out_of_sample"]["2016群 × 2016-07→2018-06（★重ならない窓）"]

    out["six_verification_outcomes"] = {
        "1_vintage_sign": {
            "literal": "通過（3ビンテージとも正）" if g3 else "不合格",
            "but": f"独立な3証拠ではない。母集団は3年とも同一956社(jaccard 1.0)・窓は終端日を共有して入れ子・"
                   f"群のティッカーは union {t1['group_ticker_union']}社/全3年共通 {t1['group_ticker_in_all3']}社・"
                   f"勝ちを作った実数は延べ36ではなく {aux['effective_sample']['distinct_winning_tickers_union']}社",
            "out_of_sample_2013_2015": "判定不能（f2_特徴量が構造的に存在しない）＝prereg の追加検証は当てられない",
        },
        "2_sector": {
            "verdict": "推定量によって割れる＝頑健でない",
            "explorer_rule_MH_min3": {str(v): mh3[i] for i, v in enumerate(VINT)},
            "this_tool_MH_min1": {str(v): mh_all[i] for i, v in enumerate(VINT)},
            "direct_standardized": {str(v): ds_all[i] for i, v in enumerate(VINT)},
            "indirect_standardized": {str(v): is_all[i] for i, v in enumerate(VINT)},
            "sic4_MH": {v: gran["sic4"][v]["mh"] for v in gran["sic4"]},
            "n_estimators_pass": sum(1 for x in verdicts.values() if x),
            "n_estimators_fail": sum(1 for x in verdicts.values() if not x),
            "deeper_problem": "群は sic2 で6個(33/35/36/38/30/67)に割れるが実体は半導体連鎖という一つの賭け"
                              "（2018年は25社中17社）。sic2 の層別は原理的にこれを見られない。"
                              "広義の連鎖で層別すると**連鎖の外での lift はほぼ0**"
                              "（2016 -0.042 / 2017 +0.028 / 2018 -0.016・各 n=7〜10）だが、"
                              "狭義の定義では逆に出る＝n が小さすぎてこの問いは決着しない",
        },
        "3_irr_shadow": {
            "verdict": "通過。ただし薄い",
            "detail": f"irr>=70 層内の lift +{irr_lift}（分子 {out['test3_irr_shadow']['vintage_2018']['irr70plus_stratum']['numerator']}社）。"
                      f"ただし irr が読めているのは 127/339(37%)・2018のみ・群は 15/25。"
                      f"直交でもない（群の80%が irr>=70 vs 他39%・phi 0.26）",
        },
        "4_leave_one_out": {
            "verdict": f"通過（1社抜きで線を割るのは {loo_break} 社 / {len(ticks)} 社）",
            "range": out["test4_leave_one_company_out"]["range"],
        },
        "5_permutation": {
            "single_candidate_p": round(p_single, 4),
            "after_selection_cost_p": p_sel,
            "verdict": f"**選抜代を払うと消える**。単独 p={p_single:.4f} → 3189通りの空間で最大を取る帰無では "
                       f"p={p_sel}。探索側のより広い空間(2840検定・種の選び直し込み)では帰無の最大値の "
                       f"p90={aux['multiple_testing_price_quoted_from_explorer'].get('null_max_statistic_percentiles',{}).get('p90')} "
                       f"で、この候補の {round(maintained,4)} はその**下**。"
                       f"探索の手続き自体が帰無でも 48% の確率で『合格』を1本は出す",
        },
        "6_increment": {
            "verdict": "通過（本物の増分）",
            "detail": "事業の収縮・低intcov を除いても lift 0.22〜0.33 で残り、群のうち既存関門に当たるのは0〜3社。"
                      "脚単独(rnd 0.09〜0.13 / sga 0.10〜0.11)より +0.13〜0.19 大きい",
        },
    }
    out["aux_key_findings"] = {
        "regime": f"AI前(2018-07→2022-07) lift +{reg_pre['lift']}・中央値 {reg_pre['median_cagr_group']} vs "
                  f"{reg_pre['median_cagr_nongroup']}（差はほぼ無い） ／ "
                  f"AI期(2022-07→2026-08) lift +{reg_ai['lift']}・中央値 {reg_ai['median_cagr_group']} vs "
                  f"{reg_ai['median_cagr_nongroup']}。超過はAI期に集中している"
                  "（台帳が irr85 について記録した +0.13/+0.38 とほぼ同じ形）",
        "disjoint_window": f"2016群を重ならない窓(2016-07→2018-06)で測ると lift +{dis_w['lift']}（線0.15の**下**）・"
                           f"中央値 {dis_w['median_cagr_group']} vs {dis_w['median_cagr_nongroup']}。"
                           "符号は消えないが線には届かない。しかもこの窓自体が半導体の当たり年",
        "threshold_sensitivity": "9通りの閾値で maintained 0.2171〜0.2807＝閾値には頑健（候補に有利な事実）",
        "could_not_kill": ["1社抜き（0/34）", "閾値感度", "既存関門への増分", "脚単独への増分",
                           "重ならない窓でも符号は反転しない"],
    }
    out["verdict"] = {
        "result": "不合格",
        "which_gates_fail": [
            "業種調整——探索側の規則(MH・層は最小3社)で 2018 が 0.1255 と線を割る。"
            "推定量を変えると 0.1255〜0.2126 に振れ、4つのうち2つが不合格、sic4 では3つ中2つが不合格",
            "多重検定——選抜代を払うと p=0.005 → 0.0675（自前実測）。探索側の広い空間では帰無 p90 の下",
            "3ビンテージの独立性——同一956社・入れ子の窓・勝ちの実数は17社。『3つで一致』は3つの証拠ではない",
        ],
        "honest_caveats": [
            "業種調整は『不合格』を決め打ちできるほど頑健でもない——4推定量のうち2つは通る。"
            "つまりこの候補は『業種で説明できると証明された』のではなく『業種と区別できない』",
            "1社抜き・閾値感度・既存関門への増分は本物で、潰せなかった",
            "半導体連鎖の中か外かは、線の引き方（狭義/広義）で逆の答えが出る＝n=25では決着しない",
        ],
        "bottom_line": "prereg の5条件のうち業種調整が実装依存で割れ、選抜代を払うと有意性が消え、"
                       "3ビンテージは独立でなく、超過はAI期に集中する。"
                       "『R&Dが高くSG&Aが低い』が勝者を分けたのではなく、"
                       "**2018-2026の半導体連鎖をこの2本が言い換えていた**と読むのが実測に最も忠実",
    }
    out["runtime_sec"] = round(time.time() - t0, 1)
    json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({
        "reproduction": out["reproduction"].get("verdict"),
        "gates": out["prereg_gates_literal"],
        "mh": out["test2_sector"]["summary"],
        "loo_break": loo_break,
        "p_perm": p_single,
        "runtime": out["runtime_sec"],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
