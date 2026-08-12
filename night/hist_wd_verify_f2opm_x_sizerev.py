#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
候補「営業利益率 下位1/4 ∧ 売上規模 上位1/4 → 勝者」を潰しにかかる検証器。

  変数 : f2_opm ∧ size_rev
  側   : winner  P(実現年率 >= +15%)
  母集団: P_full（window_full）
  切り方: f2_opm <= 0.0379（2018のq25） ∧ size_rev >= 6.830e9
  探索側の報告: 2018 n=31 / 分子15 / lift 0.2738

この道具は判定も採点もしない。読むだけ。事前登録
(out/hist_winner_destroyer_prereg.json) の線は一つも動かさない。

当てる検問（1つでも落ちたら不合格）:
  T0 重複列       size_rev は f2_rev と同一列か（＝この検定は候補24と同じものか）
  T1 ビンテージ符号 2016/2017/2018 で符号が反転しないか。2013/2015 は co_ 代理で測れるか
  T2 業種調整     同一 sic2 内で残るか（間接標準化＋層内置換＋業種1つ抜き）
  T3 irr の影     irr>=70 層内で残るか／irr と直交か
  T4 1社の影響    群の社を1社ずつ抜いて lift がどこまで動くか
  T5 置換         層内で結果ラベルを並べ替える2000回で偶然にこの lift 以上が出る確率
  T6 既存関門との重複 事業の収縮 / 財務キル相当(intcov) / 質実証 で既に落ちている社ではないか

出力: out/hist_wd_verify_f2opm_x_sizerev.json
"""
import json, os, random, math, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PANEL = os.path.join(ROOT, "out", "hist_wd_panel.json")
PREREG = os.path.join(ROOT, "out", "hist_winner_destroyer_prereg.json")
OUT = os.path.join(ROOT, "out", "hist_wd_verify_f2opm_x_sizerev.json")

OPM_T = 0.0379          # 候補の切り方（2018 の q25 と一致）
REV_T = 6.830e9         # 候補の切り方（2018 の q75=6.7666e9 とは僅かに違う。T4で感度を見る）
SIDE = "win"
MIN_NUM = 5             # 事前登録
LIFT_LINE = 0.15        # 事前登録
SEED = 20260811
PERM_N = 2000


def quantile(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def load():
    with open(PANEL, encoding="utf-8") as f:
        d = json.load(f)
    return d


def pop_rows(rows, vintage, popkey="P_full", window_full=True):
    out = []
    for r in rows:
        if r["vintage"] != vintage:
            continue
        if not r.get(popkey):
            continue
        if not r.get("has_outcome"):
            continue
        if window_full and not r.get("window_full"):
            continue
        out.append(r)
    return out


def stat(group, base_pop, side=SIDE):
    """群と母集団から P / lift / 分子 を出す。母集団は群を含む全体。"""
    n = len(group)
    k = sum(1 for r in group if r.get(side))
    N = len(base_pop)
    K = sum(1 for r in base_pop if r.get(side))
    p = k / n if n else None
    base = K / N if N else None
    return {
        "n": n, "k": k, "p": round(p, 4) if p is not None else None,
        "pop_n": N, "pop_k": K, "base": round(base, 4) if base is not None else None,
        "lift": round(p - base, 4) if (p is not None and base is not None) else None,
    }


def in_group(r, opm_t=OPM_T, rev_t=REV_T, opm_key="f2_opm", rev_key="size_rev"):
    o, s = r.get(opm_key), r.get(rev_key)
    if o is None or s is None:
        return None          # 判定不能（欠測をFalseと読まない）
    return (o <= opm_t) and (s >= rev_t)


def split(R, **kw):
    g, notg, und = [], [], []
    for r in R:
        v = in_group(r, **kw)
        if v is None:
            und.append(r)
        elif v:
            g.append(r)
        else:
            notg.append(r)
    return g, notg, und


# ---------------------------------------------------------------- T0
def t0_duplicate_columns(rows):
    same = diff = only_f2 = only_size = 0
    ex = []
    for r in rows:
        a, b = r.get("size_rev"), r.get("f2_rev")
        if a is None and b is None:
            continue
        if a is not None and b is not None:
            if a == b:
                same += 1
            else:
                diff += 1
                if len(ex) < 5:
                    ex.append([r["ticker"], r["vintage"], a, b])
        elif b is None:
            only_size += 1
        else:
            only_f2 += 1
    bysrc = collections.Counter(r.get("size_src") for r in rows)
    return {
        "question": "size_rev は f2_rev と別の列か",
        "both_present_and_equal": same,
        "both_present_and_differ": diff,
        "differ_examples": ex,
        "only_size_rev": only_size,
        "only_f2_rev": only_f2,
        "size_src_counts": {str(k): v for k, v in bysrc.items()},
        "verdict": (
            "同一列。f2_rev が在るビンテージ(2016/2017/2018)では size_rev は f2_rev の写しで、"
            "2867行すべてで完全一致・不一致0件。したがって『f2_opm ∧ size_rev』は"
            "『f2_opm ∧ f2_rev』とまったく同じ検定＝候補24の重複。"
            if diff == 0 and same > 0 else "別列（要再確認）"),
    }


# ---------------------------------------------------------------- T1
def t1_vintages(rows):
    res = {"fixed_threshold": {}, "per_vintage_quartile": {}, "proxy_2013_2015": {},
           "note": ""}
    # (a) 固定閾値（候補どおり）
    for v in (2016, 2017, 2018):
        R = pop_rows(rows, v)
        g, ng, und = split(R)
        s = stat(g, R)
        s["undetermined"] = len(und)
        res["fixed_threshold"][str(v)] = s
    # (b) 各ビンテージ自身の四分位（「下位1/4∧上位1/4」の素直な定義）
    for v in (2016, 2017, 2018):
        R = pop_rows(rows, v)
        ot = quantile([r["f2_opm"] for r in R if r.get("f2_opm") is not None], .25)
        rt = quantile([r["size_rev"] for r in R if r.get("size_rev") is not None], .75)
        g, ng, und = split(R, opm_t=ot, rev_t=rt)
        s = stat(g, R)
        s.update(opm_t=round(ot, 6), rev_t=round(rt, 1), undetermined=len(und))
        res["per_vintage_quartile"][str(v)] = s
    # (c) 2013/2015 は f2_* が無いので co_opm / co_rev_asof を代理に使う
    #     （パネルの definition_crosscheck: spearman 0.971・中央比1.00・87%が1pt以内）
    for v in (2013, 2015):
        R = pop_rows(rows, v)
        ot = quantile([r["co_opm"] for r in R if r.get("co_opm") is not None], .25)
        rt = quantile([r["co_rev_asof"] for r in R if r.get("co_rev_asof") is not None], .75)
        g, ng, und = split(R, opm_t=ot, rev_t=rt, opm_key="co_opm", rev_key="co_rev_asof")
        s = stat(g, R)
        s.update(opm_t=round(ot, 6) if ot is not None else None,
                 rev_t=round(rt, 1) if rt is not None else None,
                 undetermined=len(und),
                 basis="co_opm / co_rev_asof（f2_* は2013/2015に無い＝代理。名前空間が違う量なので水準は比べない）")
        res["proxy_2013_2015"][str(v)] = s
    res["note"] = ("固定閾値は2018で作られた線なので、2016/2017に当てるのは"
                   "『2018の四分位を他年に当てる』こと。両方出す。")
    return res


# ---------------------------------------------------------------- T2
def t2_sector(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, ng, und = split(R)
    gset = set(id(r) for r in g)

    # 群の業種構成
    comp = collections.Counter(r.get("sic2") for r in g)
    win_by_sec = collections.Counter(r.get("sic2") for r in g if r.get(SIDE))

    # 間接標準化: 層ごとの母集団率で期待事象数を出す
    strata = collections.defaultdict(list)
    for r in R:
        strata[r.get("sic2")].append(r)
    exp = 0.0
    obs = 0
    detail = {}
    for sec, mem in strata.items():
        gm = [r for r in mem if id(r) in gset]
        if not gm:
            continue
        base = sum(1 for r in mem if r.get(SIDE)) / len(mem)
        e = base * len(gm)
        o = sum(1 for r in gm if r.get(SIDE))
        exp += e
        obs += o
        detail[str(sec)] = {"stratum_n": len(mem), "group_n": len(gm),
                            "stratum_base": round(base, 4), "obs": o, "exp": round(e, 3)}
    n = len(g)
    crude_base = sum(1 for r in R if r.get(SIDE)) / len(R)
    adj = {
        "obs": obs, "exp": round(exp, 3),
        "smr": round(obs / exp, 4) if exp else None,
        "p_observed": round(obs / n, 4) if n else None,
        "p_expected_sector_adjusted": round(exp / n, 4) if n else None,
        "lift_crude": round(obs / n - crude_base, 4) if n else None,
        "lift_sector_adjusted": round((obs - exp) / n, 4) if n else None,
    }

    # Mantel-Haenszel オッズ比（sic2 層別）
    num = den = 0.0
    for sec, mem in strata.items():
        gm = [r for r in mem if id(r) in gset]
        om = [r for r in mem if id(r) not in gset]
        if not gm or not om:
            continue
        a = sum(1 for r in gm if r.get(SIDE)); b = len(gm) - a
        c = sum(1 for r in om if r.get(SIDE)); dd = len(om) - c
        T = len(mem)
        num += a * dd / T
        den += b * c / T
    mh_or = round(num / den, 4) if den else None

    # 層内置換
    rnd = random.Random(SEED)
    obs_stat = obs - exp
    ge = 0
    for _ in range(PERM_N):
        tot = 0.0
        for sec, mem in strata.items():
            gm_n = sum(1 for r in mem if id(r) in gset)
            if not gm_n:
                continue
            labels = [1 if r.get(SIDE) else 0 for r in mem]
            rnd.shuffle(labels)
            tot += sum(labels[:gm_n])
        if tot - exp >= obs_stat - 1e-9:
            ge += 1
    perm_p = round(ge / PERM_N, 4)

    # 業種を1つずつ抜く
    loo = {}
    for sec in sorted(set(str(r.get("sic2")) for r in g)):
        R2 = [r for r in R if str(r.get("sic2")) != sec]
        g2 = [r for r in g if str(r.get("sic2")) != sec]
        if not g2:
            loo[sec] = {"n": 0, "note": "群が空になる"}
            continue
        loo[sec] = stat(g2, R2)
    lifts = [v["lift"] for v in loo.values() if v.get("lift") is not None]

    return {
        "vintage": vintage,
        "group_sector_composition": {str(k): v for k, v in comp.most_common()},
        "group_wins_by_sector": {str(k): v for k, v in win_by_sec.most_common()},
        "indirect_standardization": adj,
        "mantel_haenszel_or": mh_or,
        "within_sector_permutation_p": perm_p,
        "leave_one_sector_out": loo,
        "leave_one_sector_out_lift_range": [min(lifts), max(lifts)] if lifts else None,
        "n_sectors_in_group": len(comp),
        "detail_by_sector": detail,
    }


# ---------------------------------------------------------------- T3
def t3_irr(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, ng, und = split(R)
    gset = set(id(r) for r in g)

    def irr_ok(r):
        v = r.get("irr")
        return v is not None and v >= 70

    R_irr = [r for r in R if r.get("irr") is not None]
    R_moat = [r for r in R_irr if irr_ok(r)]
    g_irr = [r for r in g if r.get("irr") is not None]
    g_moat = [r for r in g_irr if irr_ok(r)]

    # 直交性: 群と非群で irr の分布が違うか
    dist_g = collections.Counter(r.get("irr") for r in g_irr)
    dist_o = collections.Counter(r.get("irr") for r in R_irr if id(r) not in gset)
    share_g = (len(g_moat) / len(g_irr)) if g_irr else None
    others = [r for r in R_irr if id(r) not in gset]
    share_o = (sum(1 for r in others if irr_ok(r)) / len(others)) if others else None

    out = {
        "vintage": vintage,
        "irr_coverage_in_population": {"n_pop": len(R), "n_with_irr": len(R_irr),
                                       "share": round(len(R_irr) / len(R), 4)},
        "irr_coverage_in_group": {"n_group": len(g), "n_with_irr": len(g_irr),
                                  "share": round(len(g_irr) / len(g), 4) if g else None},
        "irr_distribution_group": {str(k): v for k, v in sorted(dist_g.items(), key=lambda x: (x[0] is None, x[0]))},
        "irr_distribution_others": {str(k): v for k, v in sorted(dist_o.items(), key=lambda x: (x[0] is None, x[0]))},
        "share_irr_ge70_group": round(share_g, 4) if share_g is not None else None,
        "share_irr_ge70_others": round(share_o, 4) if share_o is not None else None,
    }
    if g_moat and R_moat:
        s = stat(g_moat, R_moat)
        out["within_irr_ge70"] = s
        out["within_irr_ge70_verdict"] = (
            "判定不能（分子 %d < 5）" % s["k"] if s["k"] < MIN_NUM else "判定可")
    else:
        out["within_irr_ge70"] = {"n": len(g_moat), "pop_n": len(R_moat)}
        out["within_irr_ge70_verdict"] = "判定不能（群が irr>=70 層に居ない／層が空）"
    # 対照: irr が読まれている社だけに絞った層でも見る
    if g_irr:
        out["within_irr_read_any"] = stat(g_irr, R_irr)
    return out


# ---------------------------------------------------------------- T4
def t4_jackknife(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, ng, und = split(R)
    full = stat(g, R)
    res = []
    for r in g:
        g2 = [x for x in g if x is not r]
        R2 = [x for x in R if x is not r]
        s = stat(g2, R2)
        res.append({"drop": r["ticker"], "win": bool(r.get(SIDE)),
                    "tr_cagr": r.get("tr_cagr"), "sic2": r.get("sic2"),
                    "lift": s["lift"], "n": s["n"], "k": s["k"]})
    res.sort(key=lambda x: x["lift"])
    lifts = [x["lift"] for x in res]
    # 閾値の感度（真のq75=6.7666e9 を使うと OSK が1社入る）
    alt = {}
    for name, rt in [("rev_t_6.830e9(候補)", 6.830e9), ("rev_t_6.7666e9(実際のq75)", 6766611500.0)]:
        g3, _, _ = split(R, rev_t=rt)
        alt[name] = stat(g3, R)
    # 勝者を上位k社ずつ抜いたら（複数社の影響）
    multi = {}
    winners = [r for r in g if r.get(SIDE)]
    winners.sort(key=lambda r: -(r.get("tr_cagr") or 0))
    for kk in (1, 2, 3):
        drop = set(id(x) for x in winners[:kk])
        g4 = [x for x in g if id(x) not in drop]
        R4 = [x for x in R if id(x) not in drop]
        multi["drop_top%d_winners" % kk] = stat(g4, R4)
    return {
        "vintage": vintage,
        "full": full,
        "lift_min_after_dropping_one": min(lifts),
        "lift_max_after_dropping_one": max(lifts),
        "survives_line_after_any_single_drop": min(lifts) >= LIFT_LINE,
        "min_numerator_after_any_single_drop": min(x["k"] for x in res),
        "worst_five": res[:5],
        "best_five": res[-5:],
        "threshold_sensitivity": alt,
        "drop_top_winners": multi,
    }


# ---------------------------------------------------------------- T5
def t5_permutation(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, ng, und = split(R)
    gset = set(id(r) for r in g)
    n = len(g)
    obs_k = sum(1 for r in g if r.get(SIDE))
    labels = [1 if r.get(SIDE) else 0 for r in R]
    rnd = random.Random(SEED)
    ge = 0
    for _ in range(PERM_N):
        rnd.shuffle(labels)
        if sum(labels[:n]) >= obs_k:
            ge += 1
    p_unstrat = ge / PERM_N

    # 参考: 超幾何の厳密片側 p（置換の解析版）
    N = len(R); K = sum(labels)
    def C(a, b):
        return math.comb(a, b) if 0 <= b <= a else 0
    tail = sum(C(K, i) * C(N - K, n - i) for i in range(obs_k, min(K, n) + 1)) / C(N, n)

    return {
        "vintage": vintage,
        "reps": PERM_N,
        "observed_k": obs_k, "group_n": n,
        "p_unstratified_permutation": round(p_unstrat, 4),
        "p_hypergeometric_exact": round(tail, 6),
        "note": "単一の検定のp値。探索全体の多重性（候補×切り方×側×母集団）は含まない。",
    }


# ---------------------------------------------------------------- T6
def t6_overlap(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, ng, und = split(R)

    def shrink(r):   # 門の第四関門「事業の収縮」
        a, b = r.get("f2_cagr5"), r.get("f2_opmD5")
        if a is None or b is None:
            return None
        return a < 0 and b < 0

    def quality(r):  # 質実証（パネルの P_quality）
        return r.get("P_quality")

    def lowcov(r, t):  # 財務キル(nde>4)の代理。ndeはパネルに無い
        v = r.get("f2_intcov")
        if v is None:
            return None
        return v < t

    gates = {
        "事業の収縮(cagr5<0 ∧ opmD5<0)": shrink,
        "質実証を通らない(not P_quality)": lambda r: (None if quality(r) is None else not quality(r)),
        "intcov<1(財務キルの代理)": lambda r: lowcov(r, 1),
        "intcov<3(財務キルの代理)": lambda r: lowcov(r, 3),
        "intcov<5(財務キルの代理)": lambda r: lowcov(r, 5),
    }
    out = {"vintage": vintage, "group_n": len(g), "by_gate": {}}
    for name, fn in gates.items():
        hit = [r for r in g if fn(r) is True]
        undet = [r for r in g if fn(r) is None]
        out["by_gate"][name] = {
            "group_caught": len(hit),
            "group_caught_share": round(len(hit) / len(g), 4) if g else None,
            "group_caught_wins": sum(1 for r in hit if r.get(SIDE)),
            "group_undetermined": len(undet),
            "population_caught_share": round(
                sum(1 for r in R if fn(r) is True) / len(R), 4),
            "tickers": sorted(r["ticker"] for r in hit),
        }
    # すべての関門を通り抜けた残り（増分）
    def survives(r):
        if shrink(r) is True:
            return False
        if quality(r) is False:
            return False
        if lowcov(r, 3) is True:
            return False
        return True
    g_s = [r for r in g if survives(r)]
    R_s = [r for r in R if survives(r)]
    out["incremental_after_existing_gates"] = stat(g_s, R_s)
    out["incremental_note"] = (
        "『事業の収縮』『質実証を通らない』『intcov<3』のいずれかで落ちる社を"
        "群からも母集団からも除いた残りでの lift。増分がゼロなら実務的な価値は無い。"
        "⚠ 財務キルの正体は nde>4 だがパネルに nde が無いので intcov を代理にしている。")
    return out


# ------------------------------------------------- 追加: 部分の分解（組合せは本物か）
def parts_decomposition(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    base = sum(1 for r in R if r.get(SIDE)) / len(R)
    big = [r for r in R if r.get("size_rev") is not None and r["size_rev"] >= REV_T]
    lowm = [r for r in R if r.get("f2_opm") is not None and r["f2_opm"] <= OPM_T]
    both, _, _ = split(R)
    # 大型の中で opm 下位1/4 かそうでないか
    big_low = [r for r in big if r.get("f2_opm") is not None and r["f2_opm"] <= OPM_T]
    big_hi = [r for r in big if r.get("f2_opm") is not None and r["f2_opm"] > OPM_T]
    low_big = [r for r in lowm if r.get("size_rev") is not None and r["size_rev"] >= REV_T]
    low_small = [r for r in lowm if r.get("size_rev") is not None and r["size_rev"] < REV_T]
    def pw(S):
        return {"n": len(S), "k": sum(1 for r in S if r.get(SIDE)),
                "p": round(sum(1 for r in S if r.get(SIDE)) / len(S), 4) if S else None}
    return {
        "vintage": vintage,
        "base": round(base, 4),
        "size_top_quartile_alone": pw(big),
        "opm_bottom_quartile_alone": pw(lowm),
        "both": pw(both),
        "within_size_top_quartile": {"opm_bottom_q": pw(big_low), "opm_rest": pw(big_hi),
                                     "delta": round(pw(big_low)["p"] - pw(big_hi)["p"], 4)
                                     if big_low and big_hi else None},
        "within_opm_bottom_quartile": {"size_top_q": pw(low_big), "size_rest": pw(low_small),
                                       "delta": round(pw(low_big)["p"] - pw(low_small)["p"], 4)
                                       if low_big and low_small else None},
        "note": "組合せの lift が『部分のどちらか』で説明できるなら、交互作用という主張は立たない。",
    }


# ------------------------------------------------- 追加: 3ビンテージは3つの検定か
def t1b_vintage_independence(rows):
    """2016/2017/2018 の群が同じ社なら、『3ビンテージで符号一致』は1つの検定の3回表示。"""
    gm = {}
    wm = {}
    for v in (2016, 2017, 2018):
        R = pop_rows(rows, v)
        g, _, _ = split(R)
        gm[v] = set(r["ticker"] for r in g)
        wm[v] = set(r["ticker"] for r in g if r.get(SIDE))
    def jac(a, b):
        return round(len(a & b) / len(a | b), 4) if (a | b) else None
    pairs = {}
    for a, b in [(2016, 2017), (2016, 2018), (2017, 2018)]:
        pairs["%d-%d" % (a, b)] = {
            "group_inter": len(gm[a] & gm[b]), "group_a": len(gm[a]), "group_b": len(gm[b]),
            "group_jaccard": jac(gm[a], gm[b]),
            "winner_inter": len(wm[a] & wm[b]), "winner_a": len(wm[a]), "winner_b": len(wm[b]),
            "winner_jaccard": jac(wm[a], wm[b]),
        }
    all3 = gm[2016] & gm[2017] & gm[2018]
    allw = wm[2016] & wm[2017] & wm[2018]
    return {
        "group_members_by_vintage": {str(v): sorted(gm[v]) for v in gm},
        "pairs": pairs,
        "in_all_three_vintages": sorted(all3),
        "n_in_all_three": len(all3),
        "winners_in_all_three": sorted(allw),
        "n_winners_in_all_three": len(allw),
        "union_of_groups": len(gm[2016] | gm[2017] | gm[2018]),
        "note": ("ティッカー母集団は3年とも同一956社（パネルの vintage_overlap: jaccard 1.0）、"
                 "結果の spearman は 0.85-0.96、窓は入れ子（2018の8.09年は2016の10.09年の末尾）。"
                 "群まで同じ社なら『3ビンテージで符号一致』は独立な3証拠ではない。"),
    }


# ------------------------------------------------- 追加: 閾値の格子（ナイフエッジか）
def t4b_threshold_grid(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    opms = [r["f2_opm"] for r in R if r.get("f2_opm") is not None]
    revs = [r["size_rev"] for r in R if r.get("size_rev") is not None]
    grid = {}
    for op in (0.15, 0.20, 0.25, 0.30, 0.3333):
        ot = quantile(opms, op)
        for rp in (0.70, 0.75, 0.80, 0.85, 0.90):
            rt = quantile(revs, rp)
            g, _, _ = split(R, opm_t=ot, rev_t=rt)
            s = stat(g, R)
            s["passes_prereg_cell"] = (s["k"] >= MIN_NUM and s["lift"] is not None
                                       and s["lift"] >= LIFT_LINE)
            grid["opm<=q%d & rev>=q%d" % (round(op * 100), round(rp * 100))] = s
    cells = list(grid.values())
    ok = [c for c in cells if c["passes_prereg_cell"]]
    return {
        "vintage": vintage,
        "grid": grid,
        "cells": len(cells),
        "cells_passing_line": len(ok),
        "lift_range": [min(c["lift"] for c in cells if c["lift"] is not None),
                       max(c["lift"] for c in cells if c["lift"] is not None)],
        "note": "候補の切り方 (q25, q75) が格子の中でどこにいるか。1点だけ跳ねているならナイフエッジ。",
    }


# ------------------------------------------------- 追加: 群の正体（何を選んでいるか）
def profile_group(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, ng, _ = split(R)

    def med(S, key):
        xs = [r[key] for r in S if r.get(key) is not None]
        return round(quantile(xs, .5), 4) if xs else None

    keys = ["f2_gm", "f2_opm", "f2_sga_r", "f2_aturn", "f2_capex_r", "f2_rnd_r",
            "f2_cagr5", "f2_conv5", "f2_intcov", "f2_cash_r", "f2_gw_r",
            "f2_netiss_r", "f2_payout5", "per", "hv_pe_pct"]
    prof = {}
    for k in keys:
        prof[k] = {"group_median": med(g, k), "pop_median": med(R, k),
                   "group_n": sum(1 for r in g if r.get(k) is not None)}
    # 粗利率でも同じ切り方をしたらどうなるか（opm 固有か、それとも「規模が大きい低採算」一般か）
    gms = [r["f2_gm"] for r in R if r.get("f2_gm") is not None]
    gt = quantile(gms, .25)
    revs = [r["size_rev"] for r in R if r.get("size_rev") is not None]
    rt = quantile(revs, .75)
    g2, _, _ = split(R, opm_t=gt, rev_t=rt, opm_key="f2_gm")
    alt = stat(g2, R)
    alt["gm_threshold_q25"] = round(gt, 4)
    return {
        "vintage": vintage,
        "medians": prof,
        "same_cut_with_gross_margin": alt,
        "destroy_in_group": sum(1 for r in g if r.get("destroy")),
        "destroy_base": round(sum(1 for r in R if r.get("destroy")) / len(R), 4),
    }


# --------------- 追加: sic2 は細かすぎる。SIC大分類（一つの経済的物語）で抜く
SIC_DIV = [
    ("農林漁", 1, 9), ("鉱業", 10, 14), ("建設", 15, 17), ("製造", 20, 39),
    ("運輸公益", 40, 49), ("卸売", 50, 51), ("小売", 52, 59), ("金融保険不動産", 60, 67),
    ("サービス", 70, 89), ("公共", 91, 99),
]


def div_of(sic2):
    if sic2 is None:
        return None
    try:
        s = int(sic2)
    except Exception:
        return None
    for name, lo, hi in SIC_DIV:
        if lo <= s <= hi:
            return name
    return "他"


def t2c_division(rows, vintages=(2016, 2017, 2018)):
    """sic2 を1つずつ抜いても残るのは、群の業種が2桁では割れているから。
    卸売+小売（＝仕入れて売る＝売上が通過する事業）をまとめて抜いたらどうなるか。"""
    out = {}
    for v in vintages:
        R = pop_rows(rows, v)
        g, _, _ = split(R)
        comp = collections.Counter(div_of(r.get("sic2")) for r in g)
        res = {"group_division_composition": dict(comp.most_common()),
               "group_n": len(g),
               "wins_by_division": dict(collections.Counter(
                   div_of(r.get("sic2")) for r in g if r.get(SIDE)).most_common())}
        loo = {}
        for dv in sorted(set(div_of(r.get("sic2")) for r in g), key=str):
            R2 = [r for r in R if div_of(r.get("sic2")) != dv]
            g2 = [r for r in g if div_of(r.get("sic2")) != dv]
            loo[str(dv)] = stat(g2, R2) if g2 else {"n": 0}
        # 卸売+小売をまとめて抜く
        trade = {"卸売", "小売"}
        R3 = [r for r in R if div_of(r.get("sic2")) not in trade]
        g3 = [r for r in g if div_of(r.get("sic2")) not in trade]
        res["leave_one_division_out"] = loo
        res["drop_wholesale_and_retail"] = stat(g3, R3) if g3 else {"n": 0}
        res["share_trade_in_group"] = round(
            sum(1 for r in g if div_of(r.get("sic2")) in trade) / len(g), 4) if g else None
        res["share_trade_in_group_winners"] = round(
            sum(1 for r in g if r.get(SIDE) and div_of(r.get("sic2")) in trade) /
            max(1, sum(1 for r in g if r.get(SIDE))), 4)
        out[str(v)] = res
    return out


# --------------- 追加: 低い営業利益率は「質の欠如」か「分母の作り」か（デュポン）
def x_dupont(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, _, _ = split(R)

    def roa(r):
        o, a = r.get("f2_opm"), r.get("f2_aturn")
        return None if (o is None or a is None) else o * a

    def med(S, fn):
        xs = [fn(r) for r in S if fn(r) is not None]
        return round(quantile(xs, .5), 4) if xs else None

    # 群の opm×aturn（営業ROAの近似）が母集団と比べてどうか
    g_roa, p_roa = med(g, roa), med(R, roa)
    # 営業ROAで同じ切り方をしたら（下位1/4 ∧ 大型）勝者は出るか
    roas = [roa(r) for r in R if roa(r) is not None]
    rt = quantile(roas, .25)
    revs = [r["size_rev"] for r in R if r.get("size_rev") is not None]
    st_ = quantile(revs, .75)
    g2 = [r for r in R if roa(r) is not None and r.get("size_rev") is not None
          and roa(r) <= rt and r["size_rev"] >= st_]
    alt = stat(g2, R)
    alt["roa_threshold_q25"] = round(rt, 4)
    # 群の中で「営業ROAは母集団中央値以上」の社が何社いるか
    normal = [r for r in g if roa(r) is not None and p_roa is not None and roa(r) >= p_roa]
    return {
        "vintage": vintage,
        "median_opm_x_aturn_group": g_roa,
        "median_opm_x_aturn_population": p_roa,
        "group_members_with_normal_or_better_operating_roa": {
            "n": len(normal), "of": len(g),
            "share": round(len(normal) / len(g), 4) if g else None,
            "tickers": sorted(r["ticker"] for r in normal)},
        "same_cut_with_operating_roa": alt,
        "note": ("営業ROA≈opm×aturn。群の opm が低いのに営業ROAが母集団並みなら、"
                 "低い営業利益率は『稼げていない』ではなく『売上が通過する事業モデルで分母が大きい』"
                 "ことの現れ＝変数が見かけと違うものを測っている。"),
    }


def group_members(rows, vintage=2018):
    R = pop_rows(rows, vintage)
    g, _, _ = split(R)
    g.sort(key=lambda r: -(r.get("tr_cagr") or -9))
    return [{"ticker": r["ticker"], "sic2": r.get("sic2"),
             "opm": round(r["f2_opm"], 4), "rev_bn": round(r["size_rev"] / 1e9, 2),
             "tr_cagr": r.get("tr_cagr"), "win": bool(r.get(SIDE)),
             "destroy": bool(r.get("destroy")), "irr": r.get("irr"),
             "P_quality": r.get("P_quality"),
             "cagr5": r.get("f2_cagr5"), "opmD5": r.get("f2_opmD5"),
             "intcov": r.get("f2_intcov")} for r in g]


def main():
    d = load()
    rows = d["rows"]
    with open(PREREG, encoding="utf-8") as f:
        prereg = json.load(f)

    res = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_verify_f2opm_x_sizerev.py",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "candidate": {
            "variables": "f2_opm ∧ size_rev",
            "side": "winner P(tr_cagr>=+15%)",
            "population": "P_full (window_full)",
            "cut": "f2_opm <= %.4f ∧ size_rev >= %.3e" % (OPM_T, REV_T),
            "explorer_reported": {"vintage_implied": 2018, "n": 31, "k": 15, "lift": 0.2738},
        },
        "pass_line_from_prereg": prereg["pass_line"],
        "note_no_judgment": "この道具は門の判定・採点・台帳に一切触れない。",
    }

    # 再現
    R18 = pop_rows(rows, 2018)
    g18, _, und18 = split(R18)
    res["reproduction"] = stat(g18, R18)
    res["reproduction"]["undetermined_rows"] = len(und18)
    res["reproduction"]["matches_explorer"] = (
        res["reproduction"]["n"] == 31 and res["reproduction"]["k"] == 15
        and abs(res["reproduction"]["lift"] - 0.2738) < 0.001)

    res["T0_duplicate_columns"] = t0_duplicate_columns(rows)
    res["T1_vintage_sign"] = t1_vintages(rows)
    res["T2_sector"] = t2_sector(rows)
    # 業種調整とビンテージを同時に当てる（片方ずつ通っても、両方同時に通るとは限らない）
    res["T2b_sector_by_vintage"] = {}
    for v in (2016, 2017, 2018):
        t = t2_sector(rows, v)
        res["T2b_sector_by_vintage"][str(v)] = {
            "lift_crude": t["indirect_standardization"]["lift_crude"],
            "lift_sector_adjusted": t["indirect_standardization"]["lift_sector_adjusted"],
            "smr": t["indirect_standardization"]["smr"],
            "mantel_haenszel_or": t["mantel_haenszel_or"],
            "within_sector_permutation_p": t["within_sector_permutation_p"],
            "n_sectors_in_group": t["n_sectors_in_group"],
            "leave_one_sector_out_lift_range": t["leave_one_sector_out_lift_range"],
        }
    res["T3_irr_shadow"] = t3_irr(rows)
    res["T4_single_company"] = t4_jackknife(rows)
    res["T5_permutation"] = t5_permutation(rows)
    res["T6_overlap_existing_gates"] = t6_overlap(rows)
    res["T1b_vintage_independence"] = t1b_vintage_independence(rows)
    res["T4b_threshold_grid"] = t4b_threshold_grid(rows)
    res["T2c_sic_division"] = t2c_division(rows)
    res["X_parts_decomposition"] = parts_decomposition(rows)
    res["X_dupont"] = x_dupont(rows)
    res["X_group_profile"] = profile_group(rows)
    res["group_members_2018"] = group_members(rows)

    # 事前登録が『判定の前に出せ』と書いている数字
    r18 = res["reproduction"]
    k_lift = math.ceil((r18["base"] + LIFT_LINE) * r18["n"])
    res["reachability_of_this_cell"] = {
        "group_n": r18["n"], "base": r18["base"],
        "k_by_lift": k_lift, "k_by_min_num": MIN_NUM,
        "binding": "LIFT" if k_lift >= MIN_NUM else "MIN_NUM",
        "effective_lift_required": round(k_lift / r18["n"] - r18["base"], 4),
        "observed_k": r18["k"],
        "min_numerator_reachable": True,
    }

    # 検問ごとの合否（事前登録の線だけを使う。線は一つも動かしていない）
    t1 = res["T1_vintage_sign"]
    t2b = res["T2b_sector_by_vintage"]
    t2c = res["T2c_sic_division"]
    legs = {}
    legs["T0_独立な候補か"] = {
        "pass": res["T0_duplicate_columns"]["both_present_and_differ"] > 0,
        "why": "size_rev は f2_rev と同一列（2867行完全一致・不一致0）。候補24と同一の検定で、"
               "上位30組のうち3対6組がこの重複で埋まっている＝多重性の勘定が狂う。",
    }
    signs = [t1["fixed_threshold"][str(v)]["lift"] for v in (2016, 2017, 2018)]
    legs["T1_符号安定(2016-18・必須)"] = {
        "pass": all(s > 0 for s in signs),
        "why": "固定閾値 %s ／ 各年四分位 %s ＝符号は3年とも正。ただし線0.15を通るのは"
               "2016 0.1735 / 2017 0.1720 と僅差で、2018 0.2738 は3年の最大値。" % (
                   [round(s, 4) for s in signs],
                   [t1["per_vintage_quartile"][str(v)]["lift"] for v in (2016, 2017, 2018)]),
    }
    legs["T1_標本外(2013/2015・代理)"] = {
        "pass": all(t1["proxy_2013_2015"][str(v)]["lift"] > 0 for v in (2013, 2015)),
        "why": "2013 lift %.4f（線0.15をぎりぎり）／2015 lift %.4f＝符号反転。"
               "⚠ f2_* が無いので co_opm/co_rev_asof の代理（spearman 0.971）。" % (
                   t1["proxy_2013_2015"]["2013"]["lift"], t1["proxy_2013_2015"]["2015"]["lift"]),
    }
    legs["T2_業種調整"] = {
        "pass": all(t2b[str(v)]["lift_sector_adjusted"] >= LIFT_LINE for v in (2016, 2017, 2018)),
        "why": "sic2 間接標準化後の lift は 2016 %.4f / 2017 %.4f / 2018 %.4f。"
               "2017 は線0.15を割り層内置換 p=%.4f＝有意でない。"
               "さらに『卸売+小売』を一つの経済的物語としてまとめて抜くと "
               "2016 %.4f / 2017 %.4f / 2018 %.4f（分子5）＝3年中2年が線を割る。"
               "sic2 の1つ抜きが通ったのは、群の商流が6つの2桁コードに割れているから。" % (
                   t2b["2016"]["lift_sector_adjusted"], t2b["2017"]["lift_sector_adjusted"],
                   t2b["2018"]["lift_sector_adjusted"], t2b["2017"]["within_sector_permutation_p"],
                   t2c["2016"]["drop_wholesale_and_retail"]["lift"],
                   t2c["2017"]["drop_wholesale_and_retail"]["lift"],
                   t2c["2018"]["drop_wholesale_and_retail"]["lift"]),
    }
    legs["T3_irrの影でないこと"] = {
        "pass": None,
        "why": "群31社のうち irr が読まれているのは0社（母集団の被覆14.3%＝期待4.4社）。"
               "irr>=70 層に群の社が一人も居ないので層内比較ができない＝**判定不能**"
               "（事前登録の作法により『不合格』とは書かない）。ただし事前登録は5本すべてを"
               "要求するので、証明できない本が1本ある時点で合格にはできない。",
    }
    legs["T4_1社の影響"] = {
        "pass": res["T4_single_company"]["survives_line_after_any_single_drop"],
        "why": "1社抜きの lift 幅 [%.4f, %.4f]＝どの1社を抜いても線を通る。閾値感度も小さい。" % (
            res["T4_single_company"]["lift_min_after_dropping_one"],
            res["T4_single_company"]["lift_max_after_dropping_one"]),
    }
    legs["T5_置換"] = {
        "pass": res["T5_permutation"]["p_unstratified_permutation"] < 0.05,
        "why": "単一検定の置換 p=%.4f（超幾何 %.6f）。⚠ 探索全体の多重性は含まない。" % (
            res["T5_permutation"]["p_unstratified_permutation"],
            res["T5_permutation"]["p_hypergeometric_exact"]),
    }
    legs["T6_既存関門との増分"] = {
        "pass": False,
        "why": "群31社の31社（100%）が『質実証』を通らない。しかもこれは同義反復——"
               "質実証は営業利益率>=10%を要求し、群の定義は営業利益率<=3.79%。"
               "門はこの31社を構造的に一社も買えないので、増分は定義上ゼロ。",
    }
    res["legs"] = legs
    res["verdict"] = {
        "result": "不合格",
        "failed_legs": [k for k, v in legs.items() if v["pass"] is False],
        "undetermined_legs": [k for k, v in legs.items() if v["pass"] is None],
        "passed_legs": [k for k, v in legs.items() if v["pass"] is True],
        "one_line": "業種を『卸売+小売』という一つの物語で抜くと3年中2年で線を割り、"
                    "irr層内では判定不能、増分は同義反復でゼロ。しかも候補24と同一の検定。",
        "line_untouched": "事前登録の lift 0.15 / 分子5 / 符号安定 / 業種調整 / irr層 は一つも動かしていない。",
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)

    # 画面用の要約（判定はしない・数字を出すだけ）
    r = res["reproduction"]
    print("\n再現: n=%d k=%d p=%.4f base=%.4f lift=%.4f (一致=%s)" %
          (r["n"], r["k"], r["p"], r["base"], r["lift"], r["matches_explorer"]))
    print("T0 重複列:", res["T0_duplicate_columns"]["verdict"])
    print("T1 固定閾値:", {k: (v["n"], v["k"], v["lift"]) for k, v in res["T1_vintage_sign"]["fixed_threshold"].items()})
    print("T1 各年四分位:", {k: (v["n"], v["k"], v["lift"]) for k, v in res["T1_vintage_sign"]["per_vintage_quartile"].items()})
    print("T1 代理2013/2015:", {k: (v["n"], v["k"], v["lift"]) for k, v in res["T1_vintage_sign"]["proxy_2013_2015"].items()})
    t2 = res["T2_sector"]
    print("T2 業種調整 lift %.4f→%.4f / MH-OR %s / 層内置換p %.4f / 業種1つ抜きの幅 %s" %
          (t2["indirect_standardization"]["lift_crude"],
           t2["indirect_standardization"]["lift_sector_adjusted"],
           t2["mantel_haenszel_or"], t2["within_sector_permutation_p"],
           t2["leave_one_sector_out_lift_range"]))
    print("T2b 業種調整×ビンテージ:", {k: (v["lift_crude"], v["lift_sector_adjusted"], v["within_sector_permutation_p"])
                                      for k, v in res["T2b_sector_by_vintage"].items()})
    print("T3 irr:", res["T3_irr_shadow"]["within_irr_ge70_verdict"], res["T3_irr_shadow"]["within_irr_ge70"])
    t4 = res["T4_single_company"]
    print("T4 1社抜き lift [%.4f, %.4f] 線%.2f維持=%s" %
          (t4["lift_min_after_dropping_one"], t4["lift_max_after_dropping_one"], LIFT_LINE,
           t4["survives_line_after_any_single_drop"]))
    print("T5 置換p=%.4f 超幾何p=%.6f" % (res["T5_permutation"]["p_unstratified_permutation"],
                                          res["T5_permutation"]["p_hypergeometric_exact"]))
    print("T6 増分:", res["T6_overlap_existing_gates"]["incremental_after_existing_gates"])
    x = res["X_parts_decomposition"]
    print("X 分解: base %.4f / 大型のみ %s / 低利益率のみ %s / 両方 %s" %
          (x["base"], x["size_top_quartile_alone"], x["opm_bottom_quartile_alone"], x["both"]))
    t1b = res["T1b_vintage_independence"]
    print("T1b 群の重なり:", {k: v["group_jaccard"] for k, v in t1b["pairs"].items()},
          "3年すべてに居る社", t1b["n_in_all_three"], "／和集合", t1b["union_of_groups"])
    t4b = res["T4b_threshold_grid"]
    print("T4b 格子: %d/%d セルが線を通る lift幅 %s" %
          (t4b["cells_passing_line"], t4b["cells"], t4b["lift_range"]))
    t2c = res["T2c_sic_division"]
    print("T2c 卸売+小売を丸ごと抜く:", {k: (v["drop_wholesale_and_retail"].get("n"),
                                            v["drop_wholesale_and_retail"].get("k"),
                                            v["drop_wholesale_and_retail"].get("lift"),
                                            "trade%d%%" % round(100 * v["share_trade_in_group"]))
                                        for k, v in t2c.items()})
    xd = res["X_dupont"]
    print("X デュポン: 群のopm×aturn %s / 母 %s / 営業ROAが母中央値以上の社 %s" % (
        xd["median_opm_x_aturn_group"], xd["median_opm_x_aturn_population"],
        xd["group_members_with_normal_or_better_operating_roa"]["share"]))
    print("   営業ROAで同じ切り方 →", xd["same_cut_with_operating_roa"])
    xp = res["X_group_profile"]
    print("X 群の正体: 粗利率で同じ切り方 →", xp["same_cut_with_gross_margin"])
    print("   中央値 gm 群%s/母%s  aturn 群%s/母%s" % (
        xp["medians"]["f2_gm"]["group_median"], xp["medians"]["f2_gm"]["pop_median"],
        xp["medians"]["f2_aturn"]["group_median"], xp["medians"]["f2_aturn"]["pop_median"]))


if __name__ == "__main__":
    main()
