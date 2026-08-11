#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/hist_wd_verify_irr85.py — 候補「irr=85（勝者側）」を潰しにかかる検証器

  仕事は反証であって確認ではない。候補に有利な数字を探さない。

【この候補の位置づけ（結果を見る前に確定している事実）】
  out/hist_winner_destroyer_prereg.json の candidates_excluded に
  "irr18" / "irr" / "moat5" / "dom18" / "mech" / "時制" が明記されている。
  ＝ irr は事前登録上ふつうの候補ではなく **対照** であり、
     「事前登録に合格した新指標」として数えることは定義上できない。
  それでも6検問を全部当てる。当てないと対照が何をしているかが判らないから。

【当てる6検問（1つでも落ちたら不合格）】
  T1 ビンテージ符号  T2 業種調整  T3 irr の影  T4 1社の影響  T5 置換  T6 既存関門との重複
【追加検問（事前登録の外・すべて反証の方向）】
  E1 クラスタ（同一社が2ビンテージに重複計上されていないか）
  E2 窓の重なり／ビンテージ間の銘柄重複（3ビンテージは独立な3証拠か）
  E3 半導体連鎖の除外
  E4 母集団の構成差（2013=全上場サブセット / 2015=質実証寄り）
  E5 到達可能性・実効要求リフト・検出力・偽陽性率（prereg の must_report_before_verdict）
  E6 破壊側を単独で（分子が何社に載っているか）
  E7 窓長の違いとハードルの相性
  E8 複合ストレス（業種最大群の除外 × クラスタ畳み × 半導体除外）
  E9 LLM事前知識の混入（無名・小型だけで残るか）
  E10 ハードル感度（15%の一点でしか出ない結果ではないか）

判定・採点・台帳・パックには一切書き込まない。読むだけ。
出力: out/hist_wd_verify_irr85.json
"""
import json, os, math, random
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, "out", "hist_wd_panel.json")
PREREG = os.path.join(ROOT, "out", "hist_winner_destroyer_prereg.json")
OUT = os.path.join(ROOT, "out", "hist_wd_verify_irr85.json")

SEED = 20260811
N_PERM = 2000
LIFT_LINE = 0.15      # 事前登録の線。動かさない
MIN_NUM = 5           # 事前登録の線。動かさない

# 半導体連鎖（E3）。同じ設備投資サイクルに乗るかで採る（既存 SEMI と同じ考え方）
SEMI = {"LRCX", "ENTG", "MKSI", "STX", "AMAT", "KLAC", "ASML", "NVMI",
        "ACMR", "ONTO", "TER", "MPWR", "NXPI", "ADI", "AEIS", "COHR", "IPGP", "OLED"}


# ---------------- 基本 ----------------
def rate(rows, key):
    n = len(rows)
    k = sum(1 for x in rows if x[key])
    return n, k, (k / n if n else None)


def lift(group, base, key):
    ng, kg, pg = rate(group, key)
    nb, kb, pb = rate(base, key)
    return {"n_group": ng, "num_group": kg, "p_group": round(pg, 4) if pg is not None else None,
            "n_base": nb, "num_base": kb, "p_base": round(pb, 4) if pb is not None else None,
            "lift": round(pg - pb, 4) if (pg is not None and pb is not None) else None,
            "passes_lift_line": (pg - pb >= LIFT_LINE) if (pg is not None and pb is not None) else None,
            "passes_min_numerator": kg >= MIN_NUM}


def grp(rows, val=85, field="irr"):
    return [x for x in rows if x.get(field) == val]


def collapse(rs):
    """同一社を最古ビンテージ1行へ畳む（最も長い窓＝最も厳しい）"""
    best = {}
    for x in rs:
        t = x["ticker"]
        if t not in best or x["vintage"] < best[t]["vintage"]:
            best[t] = x
    return list(best.values())


def mh(rows, expo, key):
    """Mantel-Haenszel の層別リスク差とオッズ比。exposed = irr==85。
    層内に片側しかいなければ寄与ゼロ（自動的に落ちる）＝その分だけ実効nが減る。"""
    strata = defaultdict(list)
    for x in rows:
        strata[expo(x)].append(x)
    rd_num = rd_den = or_num = or_den = 0.0
    used = []
    for s, xs in strata.items():
        e = [x for x in xs if x["irr"] == 85]
        u = [x for x in xs if x["irr"] != 85]
        n1, n0, N = len(e), len(u), len(xs)
        if n1 == 0 or n0 == 0:
            continue
        a = sum(1 for x in e if x[key]); b = n1 - a
        c = sum(1 for x in u if x[key]); dd = n0 - c
        rd_num += (a * n0 - c * n1) / N
        rd_den += (n1 * n0) / N
        or_num += (a * dd) / N
        or_den += (b * c) / N
        used.append({"stratum": str(s), "n_exposed": n1, "num_exposed": a,
                     "p_exposed": round(a / n1, 3),
                     "n_unexposed": n0, "num_unexposed": c,
                     "p_unexposed": round(c / n0, 3)})
    return {"mh_risk_diff": round(rd_num / rd_den, 4) if rd_den else None,
            "mh_odds_ratio": round(or_num / or_den, 4) if or_den else None,
            "strata_used": len(used),
            "n_rows_in_used_strata": sum(u["n_exposed"] + u["n_unexposed"] for u in used),
            "n_rows_total": len(rows),
            "strata_detail": sorted(used, key=lambda z: -z["n_exposed"])}


def perm_test(rows, key, expo=None, cluster=None, n_perm=N_PERM, seed=SEED):
    """層内で群の印を並べ替え、観測 lift 以上が偶然に出る一側確率。
    cluster があればクラスタ単位で入れ替える（同一社の2行を割り裂かない）。"""
    rng = random.Random(seed)
    obs_g = [x for x in rows if x["irr"] == 85]
    if not obs_g:
        return {"note": "群が空"}
    obs = sum(1 for x in obs_g if x[key]) / len(obs_g) - sum(1 for x in rows if x[key]) / len(rows)
    if cluster is None:
        units = [[x] for x in rows]
    else:
        cd = defaultdict(list)
        for x in rows:
            cd[cluster(x)].append(x)
        units = list(cd.values())
    by = defaultdict(list)
    for u in units:
        by[expo(u[0]) if expo else "_all"].append(u)
    ge = 0
    for _ in range(n_perm):
        num_g = n_g = num_all = n_all = 0.0
        for s, us in by.items():
            flags = [1 if u[0]["irr"] == 85 else 0 for u in us]
            rng.shuffle(flags)
            for f, u in zip(flags, us):
                for x in u:
                    ev = 1 if x[key] else 0
                    n_all += 1; num_all += ev
                    if f:
                        n_g += 1; num_g += ev
        if n_g == 0:
            continue
        if num_g / n_g - num_all / n_all >= obs - 1e-12:
            ge += 1
    return {"observed_lift": round(obs, 4), "n_perm": n_perm,
            "p_one_sided": round(ge / n_perm, 4),
            "clustered": cluster is not None, "stratified": expo is not None}


def binom_tail(n, p, k):
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k, n + 1))


# ---------------- 本体 ----------------
def main():
    panel = json.load(open(PANEL))
    rows = panel["rows"]
    prereg = json.load(open(PREREG))

    out = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_verify_irr85.py",
        "panel": "out/hist_wd_panel.json",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "seed": SEED, "n_perm": N_PERM,
        "reproducibility": {
            "deterministic": True,
            "checked": "同一入力で3回走らせて出力JSONのmd5が一致することを確認した",
            "gotcha": "最初の確認は **並列セッションが残した別の /tmp/a.json を読んでいて** "
                      "『非決定的』という誤った結論を出した。中間ファイルは必ず自分専用のパスへ置くこと"},
        "candidate": {"variable": "irr=85", "side": "winner",
                      "population": "2013+2015 プール（has_outcome ∧ window_full ∧ irr not null）",
                      "cut": "irr==85",
                      "claimed": {"n": 19, "numerator": 11, "lift": 0.3746}},
        "prereg_status": {
            "is_registered_candidate": False,
            "candidates_excluded": prereg["candidates_excluded"],
            "why": "ユーザーの問いが『irr85以外』。prereg は irr を candidates_excluded に置き、"
                   "『対照としては使う』と明記している。したがって irr=85 を"
                   "『事前登録に合格した新指標』として数えることは定義上できない。"
                   "以下は対照が何をしているかを測るために当てる。",
        },
        "tests": {},
    }

    P = [x for x in rows if x["vintage"] in (2013, 2015) and x["has_outcome"]
         and x["window_full"] and x["irr"] is not None]
    G = grp(P)

    # ---- T0 再現 ----
    rep = lift(G, P, "win"); repd = lift(G, P, "destroy")
    out["tests"]["T0_reproduce"] = {
        "winner": rep, "destroyer": repd,
        "matches_claim": rep["n_group"] == 19 and rep["num_group"] == 11
                         and abs(rep["lift"] - 0.3746) < 1e-9,
        "verdict": "再現した" if rep["num_group"] == 11 else "再現しない"}

    # ---- E1 クラスタ ----
    tick_g = Counter(x["ticker"] for x in G)
    win_rows = [x for x in G if x["win"]]; dst_rows = [x for x in G if x["destroy"]]
    Pu, Gu = collapse(P), collapse(G)
    repu, repdu = lift(Gu, Pu, "win"), lift(Gu, Pu, "destroy")
    out["tests"]["E1_cluster_duplication"] = {
        "question": "n=19 は19社か",
        "rows_in_group": len(G), "unique_tickers_in_group": len(tick_g),
        "duplicated_tickers": sorted([t for t, c in tick_g.items() if c > 1]),
        "winner_rows": len(win_rows),
        "winner_unique": sorted(set(x["ticker"] for x in win_rows)),
        "destroyer_rows": len(dst_rows),
        "destroyer_unique": sorted(set(x["ticker"] for x in dst_rows)),
        "population_rows": len(P), "population_unique_tickers": len(set(x["ticker"] for x in P)),
        "collapsed_winner": repu, "collapsed_destroyer": repdu,
        "verdict": "分子11は**8社**・破壊2は**1社**。畳んでも lift %.4f・分子 %d で線は保つ"
                   % (repu["lift"], repu["num_group"])}

    # ---- T1 ビンテージ符号 ----
    v_native = {}
    for v in (2013, 2015, 2018):
        pv = [x for x in rows if x["vintage"] == v and x["has_outcome"]
              and x["window_full"] and x["irr"] is not None]
        gv = grp(pv)
        v_native[str(v)] = {"winner": lift(gv, pv, "win"), "destroyer": lift(gv, pv, "destroy"),
                            "irr_levels": {str(k): c for k, c in Counter(x["irr"] for x in pv).items()},
                            "group_tickers": sorted(x["ticker"] for x in gv)}
    v_carry = {}
    for v in (2016, 2017):
        pv = [x for x in rows if x["vintage"] == v and x["has_outcome"]
              and x["window_full"] and x["irr_near"] is not None]
        gv = grp(pv, 85, "irr_near")
        src = Counter(x["irr_near_src"] for x in gv)
        ahead = sum(c for s, c in src.items() if s and s > v)
        v_carry[str(v)] = {"winner": lift(gv, pv, "win"),
                           "native_irr_readings_in_this_vintage": sum(
                               1 for x in rows if x["vintage"] == v and x["irr"] is not None),
                           "irr_near_src_of_group": {str(k): c for k, c in src.items()},
                           "rows_with_lookahead_src": ahead,
                           "lookahead_share": round(ahead / len(gv), 4) if gv else None}
    signs = [v_native[str(v)]["winner"]["lift"] for v in (2013, 2015, 2018)]
    out["tests"]["T1_vintage_sign"] = {
        "prereg_requires": "2016/2017/2018 の3つで符号が反転しない（必須）",
        "structural_problem": "2016/2017 に irr の読解が存在しない（native readings = 0）。"
                              "panel.known_asymmetries も『irr の読解は 2013/2015/2018 のみ』と明記。"
                              "＝必須基準そのものが irr については構造的に検定不能",
        "native_vintages": v_native,
        "carried_forward_2016_2017": v_carry,
        "carry_warning": "irr_near は他ビンテージの読解の持ち回り。(a)同じラベルを別の窓に当てるだけで"
                         "独立な証拠ではない (b)src>vintage なら look-ahead（2017は78%がそれ）",
        "sign_native": {"2013": signs[0], "2015": signs[1], "2018": signs[2]},
        "sign_reversed_native": any(s is not None and s < 0 for s in signs),
        "verdict": "判定不能（必須の 2016/2017 に irr の観測が無い）／"
                   "native 3ビンテージでは符号は反転していない"}

    # ---- E2 独立性（窓の重なり・銘柄の重なり） ----
    tsets = {v: set(v_native[str(v)]["group_tickers"]) for v in (2013, 2015, 2018)}
    union = tsets[2013] | tsets[2015] | tsets[2018]
    out["tests"]["E2_independence"] = {
        "years_by_vintage": {"2013": 13.09, "2015": 11.10, "2018": 8.09},
        "all_windows_end": "2026-08（終点が共通＝終点の相場は全ビンテージに等しく乗る）",
        "shared_years_2013_vs_2015": 11.10,
        "shared_share_of_2013_window": round(11.10 / 13.09, 4),
        "group_rows_across_3_vintages": sum(len(s) for s in tsets.values()),
        "group_unique_companies_across_3_vintages": len(union),
        "overlap_2018_with_2013_2015": sorted(tsets[2018] & (tsets[2013] | tsets[2015])),
        "verdict": "40行＝28社。2018 は 2013/2015 と7社を共有し窓も8.09年ぶん重なる。"
                   "『3ビンテージで符号一致』は独立な3証拠ではない（prereg の independence_warning どおり）"}

    # ---- T2 業種 ----
    sec_key = lambda x: x["sic2"] if x["sic2"] else "NA"
    sec = mh(P, sec_key, "win"); sec_d = mh(P, sec_key, "destroy")
    sec_perm = perm_test(P, "win", expo=sec_key)
    sec_perm_cl = perm_test(P, "win", expo=sec_key, cluster=lambda x: x["ticker"])
    gsec = Counter(str(x["sic2"]) for x in G)
    loso = []
    for s in sorted(set(x["sic2"] for x in G if x["sic2"])):
        pp = [x for x in P if x["sic2"] != s]
        r = lift(grp(pp), pp, "win")
        r["dropped_sic2"] = s
        r["dropped_tickers"] = sorted(set(x["ticker"] for x in G if x["sic2"] == s))
        loso.append(r)
    loso_fail = [r for r in loso if not (r["passes_lift_line"] and r["passes_min_numerator"])]
    # 公平のための追検: 最大業種を抜いた残りは「線を割る」だけか、それとも雑音と区別できないか
    fair = {}
    for r in loso_fail:
        pp = [x for x in P if x["sic2"] != r["dropped_sic2"]]
        fair[r["dropped_sic2"]] = {
            "residual": lift(grp(pp), pp, "win"),
            "ratio_p_group_over_p_base": round(
                lift(grp(pp), pp, "win")["p_group"] / lift(grp(pp), pp, "win")["p_base"], 2),
            "perm_within_vintage": perm_test(pp, "win", expo=lambda x: x["vintage"]),
            "perm_within_vintage_clustered": perm_test(
                pp, "win", expo=lambda x: x["vintage"], cluster=lambda x: x["ticker"]),
            "note": "群の37%を落とすので弱まるのは当然。問うべきは『残りが雑音と区別できるか』"}
    # sic1（粗い層）でも
    sic1_key = lambda x: (x["sic2"][0] if x["sic2"] else "NA")
    loso1 = []
    for s in sorted(set(sic1_key(x) for x in G if x["sic2"])):
        pp = [x for x in P if sic1_key(x) != s]
        r = lift(grp(pp), pp, "win"); r["dropped_sic1"] = s
        loso1.append(r)
    out["tests"]["T2_sector"] = {
        "group_sic2_distribution": dict(gsec),
        "largest_sic2": "35",
        "largest_sic2_share_of_group_rows": round(gsec.get("35", 0) / len(G), 4),
        "largest_sic2_share_of_winners": round(
            sum(1 for x in win_rows if x["sic2"] == "35") / len(win_rows), 4),
        "mantel_haenszel_winner": sec,
        "mantel_haenszel_destroyer": sec_d,
        "mh_caveat": "MH は片側しかいない層を落とすので、実効の母数は %d/%d 行"
                     % (sec["n_rows_in_used_strata"], sec["n_rows_total"]),
        "stratified_permutation_winner": sec_perm,
        "stratified_permutation_winner_clustered": sec_perm_cl,
        "leave_one_sector_out": loso,
        "leave_one_sic1_out": loso1,
        "loso_failures": [{"dropped_sic2": r["dropped_sic2"], "tickers": r["dropped_tickers"],
                           "lift": r["lift"], "num_group": r["num_group"]} for r in loso_fail],
        "loso_failure_fairness_check": fair,
        "verdict": ("MH は残る（RD %.4f・perm p=%.4f）。だが **sic2=35(CW/LRCX/RBC/STX) を抜くと "
                    "lift %.4f・分子 %d** で事前登録の両方の線を割り、しかも残りは "
                    "perm p=%.3f＝雑音と区別できない。1業種が結果を作っている"
                    % (sec["mh_risk_diff"], sec_perm["p_one_sided"],
                       loso_fail[0]["lift"], loso_fail[0]["num_group"],
                       fair[loso_fail[0]["dropped_sic2"]]["perm_within_vintage"]["p_one_sided"]))
                   if loso_fail else "業種を抜いても残る"}

    # ---- T3 irr の影（候補が irr 自身なので「85 は 70 と別か」） ----
    by_level = {}
    for lv in (50, 70, 85, 100):
        rs = [x for x in P if x["irr"] == lv]
        n, k, p = rate(rs, "win"); n2, k2, p2 = rate(rs, "destroy")
        by_level[str(lv)] = {"n": n, "win_num": k, "p_win": round(p, 4) if p is not None else None,
                             "destroy_num": k2, "p_destroy": round(p2, 4) if p2 is not None else None}
    hi = [x for x in P if x["irr"] is not None and x["irr"] >= 70]
    r_in_hi = lift(grp(hi), hi, "win")
    hi70 = [x for x in P if x["irr"] in (70, 85)]
    r_vs70 = lift(grp(hi70), hi70, "win")
    out["tests"]["T3_irr_shadow"] = {
        "note": "候補が irr 自身なので『irr の影か』は『85 は 70/100 と別の刻みか』に読み替える",
        "by_irr_level": by_level,
        "within_irr_ge_70": r_in_hi,
        "vs_irr_70_only": r_vs70,
        "mh_stratified_by_moat5": mh(P, lambda x: x["moat5"], "win"),
        "verdict": "50(.160)<70(.366)<85(.579) は単調。85 は irr>=70 層内でも +%.4f 残る＝"
                   "『85 だけが跳ねる』のではなく irr が連続に効き、85 がその上端。"
                   "irr=100 は .056 で最下位＝刻みの順序は単調ではない" % r_in_hi["lift"]}

    # ---- T4 1社の影響 ----
    loo_rows = []
    for i, x in enumerate(G):
        gg = [y for j, y in enumerate(G) if j != i]
        pp = [y for y in P if y is not x]
        r = lift(gg, pp, "win"); r["dropped"] = "%s@%s" % (x["ticker"], x["vintage"])
        loo_rows.append(r)
    loo_tick = []
    for t in sorted(set(x["ticker"] for x in G)):
        gg = [y for y in G if y["ticker"] != t]
        pp = [y for y in P if y["ticker"] != t]
        r = lift(gg, pp, "win"); r["dropped_ticker"] = t
        loo_tick.append(r)
    out["tests"]["T4_leave_one_out"] = {
        "row_level": {"min_lift": min(r["lift"] for r in loo_rows),
                      "min_numerator": min(r["num_group"] for r in loo_rows), "detail": loo_rows},
        "ticker_level": {"min_lift": min(r["lift"] for r in loo_tick),
                         "min_numerator": min(r["num_group"] for r in loo_tick), "detail": loo_tick},
        "verdict": "1社を全行落としても lift は最小 %.4f・分子は最小 %d で両方の線を保つ＝"
                   "1社では消えない" % (min(r["lift"] for r in loo_tick),
                                       min(r["num_group"] for r in loo_tick))}

    # ---- T5 置換 ----
    p_plain = perm_test(P, "win")
    p_vint = perm_test(P, "win", expo=lambda x: x["vintage"])
    p_vint_cl = perm_test(P, "win", expo=lambda x: x["vintage"], cluster=lambda x: x["ticker"])
    p_vs = perm_test(P, "win", expo=lambda x: (x["vintage"], x["sic2"]))
    p_vs_cl = perm_test(P, "win", expo=lambda x: (x["vintage"], x["sic2"]),
                        cluster=lambda x: x["ticker"])
    p_dest = perm_test(P, "destroy", expo=lambda x: x["vintage"])

    def freedom(expo):
        """置換に使える自由度＝両側がいる層だけが実際に入れ替わる"""
        st = defaultdict(list)
        for x in P:
            st[expo(x)].append(x)
        good = [(s, len(v), sum(1 for y in v if y["irr"] == 85)) for s, v in st.items()]
        good = [t for t in good if 0 < t[2] < t[1]]
        return {"strata": len(st), "strata_with_both_sides": len(good),
                "rows_in_those_strata": sum(t[1] for t in good), "rows_total": len(P)}

    out["tests"]["T5_permutation"] = {
        "freedom": {"vintage": freedom(lambda x: x["vintage"]),
                    "sic2": freedom(lambda x: x["sic2"] or "NA"),
                    "vintage_x_sic2": freedom(lambda x: (x["vintage"], x["sic2"]))},
        "unstratified": p_plain, "within_vintage": p_vint,
        "within_vintage_clustered": p_vint_cl,
        "within_vintage_x_sic2": p_vs, "within_vintage_x_sic2_clustered": p_vs_cl,
        "destroyer_within_vintage": p_dest,
        "verdict": "勝者側は最も厳しい層別（ビンテージ×業種・クラスタ）でも p=%.4f。"
                   "破壊側は p=%.4f で 0.05 を割らない" % (p_vs_cl["p_one_sided"], p_dest["p_one_sided"])}

    # ---- T6 既存関門との重複 ----
    qual_P = [x for x in P if x["P_quality"]]
    r_in_qual = lift(grp(qual_P), qual_P, "win")
    shrink_sup = [x for x in G if x["co_sales_cagr5"] is not None and x["co_sales_cagr5"] < 0]
    negeq = [x for x in G if x["co_equity_neg"]]
    P18 = [x for x in rows if x["vintage"] == 2018 and x["has_outcome"]
           and x["window_full"] and x["irr"] is not None]
    G18 = grp(P18)
    shrink18 = [x for x in G18 if x["f2_cagr5"] is not None and x["f2_opmD5"] is not None
                and x["f2_cagr5"] < 0 and x["f2_opmD5"] < 0]
    lowcov18 = [x for x in G18 if x["f2_intcov"] is not None and x["f2_intcov"] < 3]
    q18 = [x for x in P18 if x["P_quality"]]
    cmtl = [x for x in G if x["ticker"] == "CMTL"]
    out["tests"]["T6_overlap_existing_gates"] = {
        "pool_2013_2015": {
            "measurable": ["質実証(P_quality)", "事業の収縮の上位集合(co_sales_cagr5<0)", "債務超過(co_equity_neg)"],
            "not_measurable_here": ["事業の収縮の厳密式(opmD5 は 2013/2015 の在庫に無い)",
                                    "財務キル nde>4 相当(intcov は 2013/2015 の在庫に無い)"],
            "group_in_quality": sum(1 for x in G if x["P_quality"]), "group_n": len(G),
            "lift_within_quality_pool": r_in_qual,
            "group_hit_by_shrink_superset": ["%s@%s" % (x["ticker"], x["vintage"]) for x in shrink_sup],
            "group_equity_neg": ["%s@%s" % (x["ticker"], x["vintage"]) for x in negeq]},
        "destroyer_CMTL_vs_gates": [
            {"row": "%s@%s" % (x["ticker"], x["vintage"]), "P_quality": x["P_quality"],
             "co_sales_cagr5": x["co_sales_cagr5"], "co_opm": x["co_opm"],
             "co_equity_neg": x["co_equity_neg"], "co_score": x["co_score"]} for x in cmtl],
        "vintage_2018_strict": {
            "n_group": len(G18),
            "shrink_gate_hits": [x["ticker"] for x in shrink18],
            "intcov_lt_3_hits": [x["ticker"] for x in lowcov18],
            "lift_within_quality": lift(grp(q18), q18, "win") if q18 else None},
        "verdict": "勝者側は『止める』のではなく『選ぶ』ので増分の問いは『質実証の中でも効くか』。"
                   "質実証の中で lift %.4f・分子 %d ＝ 質実証の影ではない。"
                   "2018の厳密式では収縮・低カバレッジのヒットゼロ＝既存関門と重ならない"
                   % (r_in_qual["lift"], r_in_qual["num_group"])}

    # ---- E3 半導体除外 ----
    P_ns = [x for x in P if x["ticker"] not in SEMI]
    out["tests"]["E3_ex_semiconductor"] = {
        "semi_in_group": sorted(set(x["ticker"] for x in G if x["ticker"] in SEMI)),
        "winner_ex_semi": lift(grp(P_ns), P_ns, "win"),
        "destroyer_ex_semi": lift(grp(P_ns), P_ns, "destroy"),
        "collapsed_ex_semi": lift(collapse(grp(P_ns)), collapse(P_ns), "win")}

    # ---- E4 母集団の構成差 ----
    def sub(v):
        return [x for x in P if x["vintage"] == v]
    out["tests"]["E4_population_composition"] = {
        "2013": {"irr_rows": len(sub(2013)),
                 "source": "retro_returns_2013_all（全上場956）のうち読解済み",
                 "base_win": round(sum(1 for x in sub(2013) if x["win"]) / len(sub(2013)), 4),
                 "quality_share": round(sum(1 for x in sub(2013) if x["P_quality"]) / len(sub(2013)), 4)},
        "2015": {"irr_rows": len(sub(2015)),
                 "source": "retro_returns_2015_q（506社＝質実証プール寄り・全社ではない）",
                 "base_win": round(sum(1 for x in sub(2015) if x["win"]) / len(sub(2015)), 4),
                 "quality_share": round(sum(1 for x in sub(2015) if x["P_quality"]) / len(sub(2015)), 4)},
        "note": "性質の違う2つを1つのベースに混ぜている。ベース率は近い(0.215/0.199)ので"
                "リフトの主因ではないが、ビンテージ層別の置換で確かめてある(T5)",
        "design_caveat": "CLAUDE.md の記録: 2015 は irr=85 が n>=5 に届かないため質実証プールから"
                         "130社を追加して検出力を得た＝母集団は設計されている（停止規則は事前固定）"}

    # ---- E5 到達可能性・検出力・偽陽性率 ----
    p0, ng = rep["p_base"], rep["n_group"]
    need_lift = math.ceil((LIFT_LINE + p0) * ng - 1e-9)
    need = max(need_lift, MIN_NUM)
    out["tests"]["E5_reachability_power"] = {
        "base_rate": p0, "group_n": ng,
        "events_required_by_lift_line": need_lift, "min_numerator_line": MIN_NUM,
        "binding_constraint": "lift" if need_lift >= MIN_NUM else "min_numerator",
        "effective_required_lift": round(need / ng - p0, 4),
        "reachable": ng >= need,
        "power": {str(d): round(binom_tail(ng, min(0.999, p0 + d), need), 4)
                  for d in (0.15, 0.20, 0.30, rep["lift"])},
        "false_positive_rate_binomial_single_variable": round(binom_tail(ng, p0, need), 4),
        "note": "検出力は lift+分子 の部分だけ。符号安定・業種・irr層内の3つは含まない"
                "（含めれば検出力はこれより低い）。FPR は単一変数の値であり、"
                "prereg が想定する20本探索の多重性は含まない"}

    # ---- E6 破壊側 ----
    out["tests"]["E6_destroyer_side_alone"] = {
        "rows": ["%s@%s" % (x["ticker"], x["vintage"]) for x in dst_rows],
        "unique_companies": sorted(set(x["ticker"] for x in dst_rows)),
        "n_unique": len(set(x["ticker"] for x in dst_rows)),
        "lift": repd["lift"], "p_group": repd["p_group"], "p_base": repd["p_base"],
        "risk_ratio": round(repd["p_group"] / repd["p_base"], 2) if repd["p_base"] else None,
        "passes_min_numerator": len(dst_rows) >= MIN_NUM,
        "permutation_p": p_dest["p_one_sided"],
        "verdict": "分子2行＝**1社(CMTL)を2回数えたもの**。事前登録の分子>=5に到達しない＝判定不能。"
                   "RR4.6 は1社に載っている"}

    # ---- E7 窓長 ----
    out["tests"]["E7_window_length"] = {
        "years_by_vintage": {"2013": 13.09, "2015": 11.10, "2018": 8.09},
        "base_win_by_vintage": {"2013": v_native["2013"]["winner"]["p_base"],
                                "2015": v_native["2015"]["winner"]["p_base"],
                                "2018": v_native["2018"]["winner"]["p_base"]},
        "note": "年率ハードルなので窓長で直接は歪まないが、窓が長いほど15%/年の維持は難しく"
                "ベース率が下がる（実測 0.215/0.199/0.265）。ビンテージ間でベース率を直接比べない"}

    # ---- E8 複合ストレス ----
    stress = {}
    combos = [
        ("as_is", lambda x: True),
        ("drop_sic2_35", lambda x: x["sic2"] != "35"),
        ("ex_semi", lambda x: x["ticker"] not in SEMI),
        ("drop_sic2_35_and_ex_semi", lambda x: x["sic2"] != "35" and x["ticker"] not in SEMI),
    ]
    for name, f in combos:
        pp = [x for x in P if f(x)]
        stress[name] = {"rows": lift(grp(pp), pp, "win"),
                        "collapsed": lift(collapse(grp(pp)), collapse(pp), "win")}
    out["tests"]["E8_combined_stress"] = {
        "grid": stress,
        "verdict": "業種最大群(sic2=35)を抜くと行ベースで lift %.4f・分子 %d、"
                   "畳むと lift %.4f・分子 %d ＝ どちらも事前登録の線を割る"
                   % (stress["drop_sic2_35"]["rows"]["lift"], stress["drop_sic2_35"]["rows"]["num_group"],
                      stress["drop_sic2_35"]["collapsed"]["lift"], stress["drop_sic2_35"]["collapsed"]["num_group"])}

    # ---- E9 LLM事前知識（無名・小型だけで残るか） ----
    e9 = {}
    for thr, label in ((1e9, "under_1B"), (2e9, "under_2B")):
        pp = [x for x in P if x["size_rev"] is not None and x["size_rev"] < thr]
        e9[label] = lift(grp(pp), pp, "win")
    out["tests"]["E9_llm_prior_contamination"] = {
        "why": "CLAUDE.md: 2018では『売上10億$未満の無名社だけでも lift+0.31』で否定できたが、"
               "2015の無名社サブセットには irr85 が0社でこの検問は効かせられなかった、と記録がある。"
               "2013+2015 プールなら当てられる",
        "by_size": e9,
        "group_sizes_musd": sorted([[x["ticker"], x["vintage"], round(x["size_rev"] / 1e6, 1), x["win"]]
                                    for x in G], key=lambda z: z[2])}

    # ---- E10 ハードル感度 ----
    e10 = {}
    for h in (0.10, 0.12, 0.15, 0.18, 0.20):
        gk = sum(1 for x in G if x["tr_cagr"] is not None and x["tr_cagr"] >= h)
        bk = sum(1 for x in P if x["tr_cagr"] is not None and x["tr_cagr"] >= h)
        e10["%.2f" % h] = {"p_group": round(gk / len(G), 4), "p_base": round(bk / len(P), 4),
                           "lift": round(gk / len(G) - bk / len(P), 4), "num_group": gk}
    out["tests"]["E10_hurdle_sensitivity"] = {
        "note": "事前登録は 15% 固定。これは『15%の一点でしか出ない結果ではないか』の確認で、合否には数えない",
        "grid": e10}

    # ---- 総合判定 ----
    t2_ok = not loso_fail
    out["verdict"] = {
        "six_tests": {
            "T1_vintage_sign": {"result": "判定不能",
                                "why": "必須の 2016/2017 に irr の観測がゼロ。持ち回り(irr_near)は"
                                       "同じラベルの再利用＋2017は78%が look-ahead"},
            "T2_sector": {"result": "不合格" if not t2_ok else "合格",
                          "why": "MH は残るが sic2=35 を抜くと lift 0.1451(<0.15)・分子 4(<5)、"
                                 "残りは perm p=0.179 で雑音と区別できない"},
            "T3_irr_shadow": {"result": "合格（ただし読み替えの上で）",
                              "why": "85 は irr>=70 層内でも +0.2218。ただし 50<70<85 は単調で"
                                     "『85 だけが跳ねる』ではない。irr=100 は最下位で順序は崩れる"},
            "T4_one_company": {"result": "合格", "why": "1社を全行落としても lift 0.3273・分子 9"},
            "T5_permutation": {"result": "合格（最厳では際どい）",
                               "why": "vintage×sic2×クラスタで p=0.0420。単一変数の FPR 0.0745 に近い"},
            "T6_overlap": {"result": "合格", "why": "質実証の中でも lift 0.4325・分子10。"
                                                   "2018厳密式で収縮・低カバレッジのヒットゼロ"},
        },
        "overall": "不合格",
        "overall_why": [
            "(0) そもそも prereg.candidates_excluded に irr が入っており、"
            "『事前登録に合格した新指標』として数えることは定義上できない（対照）",
            "(1) T2 で落ちた——sic2=35 の4社(CW/LRCX/RBC/STX)が11勝者のうち7を出しており、"
            "抜くと事前登録の2本の線をどちらも割り、残りは雑音と区別できない",
            "(2) T1 は判定不能——必須の 2016/2017 に irr の観測が無い。"
            "prereg 自身の作法では判定不能は不合格ではないが、必須基準が満たされたとも数えられない",
            "(3) 破壊側(E6)は分子2行＝1社(CMTL)で分子>=5に届かない＝判定不能",
        ],
        "what_did_not_fall": [
            "関連そのものは実在する: 畳んでも(E1) 1社抜きでも(T4) 置換でも(T5) 質実証の中でも(T6) 残る",
            "既存関門との重複はゼロ(T6)＝もし本物なら増分がある",
            "ハードルを 0.10〜0.20 で振っても符号は不変(E10)＝15%の一点の産物ではない",
            "小型(<$2B)だけでも lift 0.2276・分子5(E9)＝LLMの事前知識だけでは説明しにくい",
        ],
        "the_single_most_load_bearing_fact": "sic2=35 の CW/LRCX/RBC/STX ——この4社が7行すべて勝者(7/7)。"
                                             "irr=85 の勝者側の証拠は、実質この1業種4社に載っている",
    }

    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("wrote", OUT)

    # ---- 画面要約 ----
    T = out["tests"]
    print("\n=== T0 再現 ===", T["T0_reproduce"]["verdict"], rep)
    print("=== E1 クラスタ === 19行=%d社 / 勝者11行=%d社 / 破壊2行=%d社"
          % (len(tick_g), len(set(x['ticker'] for x in win_rows)), len(set(x['ticker'] for x in dst_rows))))
    print("   畳んだ後:", repu)
    print("=== T1 ビンテージ ===", T["T1_vintage_sign"]["verdict"])
    for v in ("2013", "2015", "2018"):
        w = v_native[v]["winner"]
        print("   %s n=%d num=%d lift=%.4f" % (v, w["n_group"], w["num_group"], w["lift"]))
    for v in ("2016", "2017"):
        c = v_carry[v]
        print("   carry %s lift=%.4f (native readings=%d, lookahead %.0f%%)"
              % (v, c["winner"]["lift"], c["native_irr_readings_in_this_vintage"],
                 100 * (c["lookahead_share"] or 0)))
    print("=== E2 独立性 ===", T["E2_independence"]["verdict"])
    print("=== T2 業種 === MH-RD %.4f OR %.2f (実効 %d/%d行) / perm p=%.4f cluster p=%.4f"
          % (sec["mh_risk_diff"], sec["mh_odds_ratio"], sec["n_rows_in_used_strata"],
             sec["n_rows_total"], sec_perm["p_one_sided"], sec_perm_cl["p_one_sided"]))
    for r in loso:
        f = "  <== 線割れ" if not (r["passes_lift_line"] and r["passes_min_numerator"]) else ""
        print("   drop sic2=%-3s n=%2d num=%2d lift=%.4f %s%s"
              % (r["dropped_sic2"], r["n_group"], r["num_group"], r["lift"], r["dropped_tickers"], f))
    print("   >>>", T["T2_sector"]["verdict"])
    print("=== T3 刻み ===", by_level)
    print("   ", T["T3_irr_shadow"]["verdict"])
    print("=== T4 LOO ===", T["T4_leave_one_out"]["verdict"])
    print("=== T5 置換 ===", T["T5_permutation"]["verdict"])
    print("=== T6 重複 ===", T["T6_overlap_existing_gates"]["verdict"])
    print("=== E3 半導体除外 === 行:", T["E3_ex_semiconductor"]["winner_ex_semi"])
    print("   畳み:", T["E3_ex_semiconductor"]["collapsed_ex_semi"])
    print("=== E5 === need=%d binding=%s efflift=%.4f power=%s FPR=%.4f"
          % (need, T["E5_reachability_power"]["binding_constraint"],
             T["E5_reachability_power"]["effective_required_lift"],
             T["E5_reachability_power"]["power"],
             T["E5_reachability_power"]["false_positive_rate_binomial_single_variable"]))
    print("=== E6 破壊 ===", T["E6_destroyer_side_alone"]["verdict"])
    print("=== E8 複合ストレス ===")
    for k, v in stress.items():
        print("   %-26s 行 lift=%.4f num=%2d | 畳み lift=%.4f num=%2d"
              % (k, v["rows"]["lift"], v["rows"]["num_group"],
                 v["collapsed"]["lift"], v["collapsed"]["num_group"]))
    print("=== E9 小型のみ ===", e9)
    print("=== E10 ハードル感度 ===", e10)


if __name__ == "__main__":
    main()
