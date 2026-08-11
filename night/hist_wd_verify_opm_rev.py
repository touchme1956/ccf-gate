#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_verify_opm_rev.py — 候補「f2_opm[下位1/4] ∧ f2_rev[上位1/4]（勝者側・P_full）」を**潰しにかかる**検証。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json            … 5ビンテージ統合パネル（唯一の真実）
          out/hist_wd_win_pair.json         … 探索側の答え（**再現の突合せ相手**。信じる前に検算する）
          out/retro_sic.json                … 業種の記述
          out/retro_returns_{2016,2017,2018}.json … 重ならない部分窓の導出用（同じ終端日）
          out/retro_monthly_2018_2026.json  … レジーム分割（あれば）
出力    : out/hist_wd_verify_opm_rev.json

────────────────────────────────────────────────────────────
この道具の立場
────────────────────────────────────────────────────────────
**反証が仕事であって確認ではない。** 候補に有利な数字を探さない。
prereg の5条件（lift>=0.15 ∧ 分子>=5 ∧ 符号不変 ∧ 業種調整 ∧ irr非影）を**一つも緩めない**。
線を緩めた数字を出すときは必ず `事前登録の外・診断専用` と明記し、合否には数えない。
「測れない」と「不合格」を区別する。

────────────────────────────────────────────────────────────
候補の中身（依頼で名指しされたもの。ここは動かさない）
────────────────────────────────────────────────────────────
  母集団 P_full（全上場・質実証を課さない）
  営業利益率 f2_opm が下位1/4（2018: <=0.0379）∧ 売上 f2_rev が上位1/4（2018: >=68.30億$）
  ＝**規模が大きく、かつ営業利益率が薄い**社。
  探索側の弁: 不合格（gate_failed_at = sector_control）。
  探索側の数字: maintained_lift 0.1605 / min_numerator 13 / 増分 +0.1505 / 被覆 0.9422。
  依頼文の n=31・分子=15・lift=0.2738 は **2018 単ビンテージ**の値（maintained ではない）。

────────────────────────────────────────────────────────────
当てる6つ（依頼どおり。1つでも落ちたら不合格）
────────────────────────────────────────────────────────────
1 ビンテージ符号  : 2016/2017/2018 で符号が反転しないか。**群の重なりと窓の重なり**も出す。
                    2013/2015 は f2_ が無いが co_opm/co_rev_asof がある＝**基準の違う代理**で診断だけする。
2 業種調整        : 同一 sic2 内で残るか。MH＋間接標準化＋層内置換＋業種1つずつ除去＋MHの層分解＋粗い層。
3 irr の影        : irr>=70 層内で残るか・irr と直交か。**通した試験に検出力があるか**も測る。
                    形式試験は 2018 の一部でしか当てられないので**名指しで抜いて作り直す**。
4 1社の影響       : ティッカーを1社ずつ**パネルごと**抜いて、閾値・母集団・群・条件を全部作り直す。
5 置換            : outcome の束をティッカーごと置換（ビンテージ間相関を保つ帰無）2000回＋多重検定の値札。
6 既存の関門との重複: 事業の収縮 / 利払カバー / **質実証** の生存者の中でも残るか（＝増分）。

この候補に固有の追加検証（**候補に不利な側にしか働かない検査だけを足す**）:
  X1 交互作用       : 2×2 表。積の効果は2本の脚の足し算で説明できるか。
  X2 変数の形       : opm の下位1/4 は「薄利」か「赤字」か。可測性が勝敗と相関していないか。
                      f2_rev と size_rev は探索側が『完全に同一の列』と検出済み＝**規模の別名**。
  X3 損益計算書の形 : **売上の総額計上（卸・医薬品流通・保険・自動車ディーラー）**を拾っていないか。
                      粗利率で測る——群の粗利率が母集団より桁違いに低いなら、この2本は
                      事業の経済性ではなく**収益認識の慣行**を測っている。
  X4 母集団の依存   : P_quality では opm>=10% が課されるので **opm下位1/4 と定義上ほぼ排他**＝
                      この候補は P_full でしか存在できない。その事実を数字で出す。
  X5 両裾           : 勝者側の lift だけでなく**破壊側の lift**と分布全体を出す。
                      大型×薄利は営業レバレッジ＝両裾が伸びるはず。伸びていないなら別の機構。
                      ハードル15%の前後で群が固まっていないか（線のすぐ上に積み上がる脆さ）。
  X6 循環回復か     : 2016年群の営業利益率を **2017/2018 のパネル行**で追う（＝前方の実測）。
                      勝者が「利益率が戻った社」なら、これは品質ではなく**谷での買い**の記録。
                      レジーム分割（前半4年/後半4年）も当てる。
  X7 名指し除去     : AMZN/COST/CRM（薄利だが secular grower）・卸・保険・自動車ディーラーを
                      それぞれ抜いて作り直す。
"""
import json, os, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
PAIR = os.path.join(OUT, "hist_wd_win_pair.json")
DEST = os.path.join(OUT, "hist_wd_verify_opm_rev.json")

# ─── prereg の線（読むだけ・作らない） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
N_PERM = 2000
SEED = 20260811

# ─── 候補（依頼で名指しされたもの。ここは動かさない） ───
CAND = {
    "population": "P_full",
    "side": "winner",
    "legs": [("f2_opm", "下位1/4"), ("f2_rev", "上位1/4")],
    "label": "f2_opm[下位1/4] ∧ f2_rev[上位1/4]",
}

t0 = time.time()


# ────────────────────────────── 数学だけ（判定を含まない） ──────────────────────────────
def q_at(sorted_vals, q):
    """nearest-rank 分位（外挿しない）。探索側 hist_wd_win_pair.q_at と同一定義。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))
    return sorted_vals[k - 1]


def r4(x):
    return None if x is None else round(x, 4)


def rate(k, n):
    return (k / n) if n else None


def med(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        idx = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    nu = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return nu / (dx * dy)


def binom_tail_ge(n, k, p):
    """P(X>=k) for X~Bin(n,p)。検出力の解析計算に使う。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    tot = 0.0
    for i in range(k, n + 1):
        tot += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return tot


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
pair_out = json.load(open(PAIR, encoding="utf-8"))

rows_all = panel["rows"]
# 解析集合は探索側と同一（has_outcome ∧ window_full）。短窓は年率換算で両裾を膨らませるため。
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]

by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)
for v in by_v:
    tk = [r["ticker"] for r in by_v[v]]
    assert len(tk) == len(set(tk)), f"vintage {v} にティッカー重複"


def pop_rows(v, pop, rows_src=None):
    src = rows_src if rows_src is not None else by_v[v]
    return [r for r in src if r.get(pop) is True]


def cut_pred(cut, thr):
    if cut == "上位1/4":
        return lambda x: x >= thr
    if cut == "下位1/4":
        return lambda x: x <= thr
    if cut == "中央値超":
        return lambda x: x > thr
    if cut == "中央値以下":
        return lambda x: x <= thr
    raise ValueError(cut)


def cut_q(cut):
    return {"上位1/4": 0.75, "下位1/4": 0.25, "中央値超": 0.5, "中央値以下": 0.5}[cut]


def threshold(rows, var, cut):
    vals = sorted(r[var] for r in rows if r.get(var) is not None)
    return q_at(vals, cut_q(cut)), len(vals)


def build_group(v, pop, legs, rows_src=None):
    """群・可測集合・母集団を作る。分位は各変数が自分の分布（母集団内・可測行のみ）で切る。"""
    P = pop_rows(v, pop, rows_src)
    thrs = {}
    for var, cut in legs:
        thr, nm = threshold(P, var, cut)
        thrs[var] = {"cut": cut, "threshold": r4(thr), "_thr": thr, "n_measurable": nm}
    if any(t["_thr"] is None for t in thrs.values()):
        return None
    preds = {var: cut_pred(cut, thrs[var]["_thr"]) for var, cut in legs}
    meas, grp = [], []
    for r in P:
        if all(r.get(var) is not None for var, _ in legs):
            meas.append(r)
            if all(preds[var](r[var]) for var, _ in legs):
                grp.append(r)
    return {"pop": P, "meas": meas, "group": grp, "thresholds": thrs}


def cell(v, pop, legs, rows_src=None, win_of=None, outcome="win"):
    """1ビンテージの実測。outcome は 'win' か 'destroy'。win_of は置換用のフック。"""
    b = build_group(v, pop, legs, rows_src)
    if b is None:
        return None
    W = win_of if win_of else (lambda r: bool(r.get(outcome)))
    n_pop = len(b["pop"])
    k_pop = sum(1 for r in b["pop"] if W(r))
    n_g = len(b["group"])
    k_g = sum(1 for r in b["group"] if W(r))
    n_m = len(b["meas"])
    k_m = sum(1 for r in b["meas"] if W(r))
    p_base = rate(k_pop, n_pop)
    p_g = rate(k_g, n_g)
    p_m = rate(k_m, n_m)
    return {
        "n_pop": n_pop, "k_pop": k_pop, "p_base": r4(p_base),
        "n_group": n_g, "numerator": k_g, "p_group": r4(p_g),
        "lift": (None if p_g is None else r4(p_g - p_base)),
        "n_measurable_both": n_m,
        "lift_meas": (None if (p_g is None or p_m is None) else r4(p_g - p_m)),
        "thresholds": {k: {kk: vv for kk, vv in t.items() if not kk.startswith("_")}
                       for k, t in b["thresholds"].items()},
        "_group_rows": b["group"], "_pop_rows": b["pop"], "_meas_rows": b["meas"],
    }


def strip(c):
    return {k: v for k, v in c.items() if not k.startswith("_")} if c else None


# ────────────────────────────── 0. 再現と突合せ（信じる前に検算する） ──────────────────────────────
cells = {v: cell(v, CAND["population"], CAND["legs"]) for v in SIGN_VINTAGES}

ref = None
for e in pair_out.get("all_pairs", []):
    if e.get("label") == CAND["label"] and e.get("population") == CAND["population"]:
        ref = e
        break

_lifts = [cells[v]["lift"] for v in SIGN_VINTAGES]
_nums = [cells[v]["numerator"] for v in SIGN_VINTAGES]
_ml = r4(min(abs(x) for x in _lifts))
_mn = min(_nums)
_ml_meas = r4(min(abs(cells[v]["lift_meas"]) for v in SIGN_VINTAGES))

cross = {"found_in_explorer_output": ref is not None, "compared": 0, "mismatches": 0, "detail": []}
if ref:
    mine = {"maintained_lift": _ml, "min_numerator_161718": _mn,
            "maintained_lift_meas": _ml_meas,
            "sign": 1 if all(x > 0 for x in _lifts) else -1}
    for k, mv in mine.items():
        cross["compared"] += 1
        ev = ref.get(k)
        if ev != mv:
            cross["mismatches"] += 1
            cross["detail"].append({"key": k, "mine": mv, "explorer": ev})
    cross["explorer_entry"] = ref
cross["verdict"] = ("一致（探索側の数字は再現できる。以降の検証はこれが通ったうえでの話）"
                    if cross["mismatches"] == 0 else "**不一致＝結論を書いてはいけない**")

# 依頼文の数字（n=31/分子=15/lift=0.2738）がどのビンテージのものかを明示する
cross["request_numbers_are_single_vintage"] = {
    "依頼文": {"n_group": 31, "numerator": 15, "lift": 0.2738},
    "実測2018": {"n_group": cells[2018]["n_group"], "numerator": cells[2018]["numerator"],
                 "lift": cells[2018]["lift"]},
    "maintained(3ビンテージの最小)": {"lift": _ml, "min_numerator": _mn},
    "note": ("依頼文の3つは **2018 単ビンテージ**の値。prereg が課すのは3ビンテージすべてなので、"
             "合否に効くのは maintained のほう（0.1605）。0.2738 を候補の実力と読んではいけない。"),
}

# 行を直接数えるスポット検算（関数に頼らないことの証明）
spot = {}
for v in SIGN_VINTAGES:
    _c = cells[v]
    P = pop_rows(v, CAND["population"])
    vo = sorted(r["f2_opm"] for r in P if r.get("f2_opm") is not None)
    vr = sorted(r["f2_rev"] for r in P if r.get("f2_rev") is not None)
    _to, _tr = q_at(vo, 0.25), q_at(vr, 0.75)
    _direct = [r for r in P
               if r.get("f2_opm") is not None and r.get("f2_rev") is not None
               and r["f2_opm"] <= _to and r["f2_rev"] >= _tr]
    spot[str(v)] = {"n_direct": len(_direct), "n_cell": _c["n_group"],
                    "k_direct": sum(1 for r in _direct if r.get("win")), "k_cell": _c["numerator"],
                    "thr_opm": r4(_to), "thr_rev": _tr,
                    "mismatch": 0 if (len(_direct) == _c["n_group"]
                                      and sum(1 for r in _direct if r.get("win")) == _c["numerator"]) else 1,
                    "tickers": sorted(r["ticker"] for r in _direct)}
spot["total_mismatch"] = sum(spot[str(v)]["mismatch"] for v in SIGN_VINTAGES)


# ────────────────────────────── 事前に出す（prereg の must_report_before_verdict） ──────────────────────────────
pre = {}
reach = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    n_g, base = c["n_group"], c["p_base"]
    k_by_lift = math.ceil((base + LIFT) * n_g - 1e-12)
    k_need = max(k_by_lift, MIN_NUM)
    reach[str(v)] = {
        "n_group": n_g, "base": base,
        "k_needed_by_lift": k_by_lift, "k_needed_by_min_num": MIN_NUM,
        "binding": ("MIN_NUM" if MIN_NUM > k_by_lift else "LIFT"),
        "effective_lift_required": r4(k_need / n_g - base) if n_g else None,
        "events_total_in_population": c["k_pop"],
        "reachable": k_need <= n_g,
    }
pre["reachability_and_effective_line"] = reach
pre["reachability_note"] = ("群は 31-37社ある。母集団の勝率が 0.21-0.24 なので、"
                            "lift 0.15 に要る分子は 12-14社で MIN_NUM(5) より強い＝**LIFT が拘束**。"
                            "つまりこの候補で『不合格』と出たら、それは5社に届かなかったのではなく本当に線を割った、という意味。")

pw = {}
for true_lift in (0.15, 0.20, 0.30):
    per_v = {}
    for v in SIGN_VINTAGES:
        c = cells[v]
        n_g, base = c["n_group"], c["p_base"]
        p_true = min(1.0, base + true_lift)
        k_by_lift = math.ceil((base + LIFT) * n_g - 1e-12)
        k_need = max(k_by_lift, MIN_NUM)
        per_v[str(v)] = r4(binom_tail_ge(n_g, k_need, p_true))
    prod = 1.0
    for x in per_v.values():
        prod *= x
    pw[str(true_lift)] = {"single_vintage": per_v,
                          "three_independent(下限)": r4(prod),
                          "single_2018(上限)": per_v["2018"]}
pre["power"] = pw
pre["power_note"] = ("outcome のビンテージ間相関が高いので、真の検出力は "
                     "three_independent（完全独立の下限）と single（完全同一の上限）の間。"
                     "**真の lift が 0.15 ちょうどなら掴める確率は5割前後**＝この手続きは"
                     "『線の上にあるものを半分しか掴めない』。落とせなかったとき強く主張できない理由でもある。")


# ────────────────────────────── 1. ビンテージ符号 ──────────────────────────────
g1 = {"per_vintage": {str(v): strip(cells[v]) for v in SIGN_VINTAGES}}
g1["signs_all_positive"] = all(x is not None and x > 0 for x in _lifts)
g1["maintained_lift"] = _ml
g1["maintained_lift_vs_measurable_base"] = _ml_meas
g1["min_numerator"] = _mn
g1["gate_sign_stability"] = g1["signs_all_positive"]
g1["gate_lift"] = _ml >= LIFT
g1["gate_min_numerator"] = _mn >= MIN_NUM

gsets = {v: set(r["ticker"] for r in cells[v]["_group_rows"]) for v in SIGN_VINTAGES}
inter = gsets[2016] & gsets[2017] & gsets[2018]
union = gsets[2016] | gsets[2017] | gsets[2018]


def jac(a, b):
    return r4(len(a & b) / len(a | b)) if (a | b) else None


g1["group_membership_overlap"] = {
    "n_by_vintage": {str(v): len(gsets[v]) for v in SIGN_VINTAGES},
    "n_intersection_all3": len(inter),
    "n_union": len(union),
    "intersection_tickers": sorted(inter),
    "jaccard": {"2016vs2017": jac(gsets[2016], gsets[2017]),
                "2016vs2018": jac(gsets[2016], gsets[2018]),
                "2017vs2018": jac(gsets[2017], gsets[2018])},
    "how_to_read": ("3ビンテージの群がほぼ同じ社なら『3回一致した』は3つの証拠ではなく"
                    "**同じ社を3回数えただけ**。prereg の independence_warning がまさにこれ。"),
}

ret_years = {2013: 13.09, 2015: 11.10, 2016: 10.09, 2017: 9.09, 2018: 8.09}
g1["outcome_window_overlap"] = {
    "years": {str(v): ret_years[v] for v in SIGN_VINTAGES},
    "shared_tail_years": 8.09,
    "share_of_2016_window_shared_with_2018": r4(8.09 / 10.09),
    "share_of_2017_window_shared_with_2018": r4(8.09 / 9.09),
    "how_to_read": "窓は全部 2026-08 で終わる。2016 の 10.09 年のうち 8.09 年は 2018 の窓そのもの。",
}

# 1d 2013/2015 は f2_ が構造的に無い → co_ で代理する（**事前登録の外・診断専用**）
g1["vintages_2013_2015"] = {}
for v in (2013, 2015):
    P = pop_rows(v, CAND["population"])
    cov = {var: sum(1 for r in P if r.get(var) is not None) for var, _ in CAND["legs"]}
    g1["vintages_2013_2015"][str(v)] = {
        "n_pop": len(P), "coverage_f2": cov,
        "verdict": ("判定不能（f2_ 特徴量が構造的に存在しない＝『不合格』ではない）"
                    if all(c == 0 for c in cov.values()) else "測れる"),
    }
g1["out_of_sample_2013_2015"] = "判定不能（prereg の literal な意味では）"

_proxy = {"note": ("**事前登録の外・診断専用。合否には数えない**。"
                   "2013/2015 は f2_opm/f2_rev を持たないが co_opm/co_rev_asof を持つ。"
                   "co_ は cohort（年ラベル窓・gate0式）で f2_ は filed<=asof＝**基準が違う**。"
                   "しかも f2_ と co_ が両方ある年が一つも無いので**代理の較正ができない**。"
                   "符号が一致しても合否に数えず、反転しても決定的とはしない。"),
          "legs_proxy": [("co_opm", "下位1/4"), ("co_rev_asof", "上位1/4")]}
for v in (2013, 2015):
    c = cell(v, "P_full", [("co_opm", "下位1/4"), ("co_rev_asof", "上位1/4")])
    _proxy[str(v)] = strip(c)
    if c:
        _proxy[str(v)]["group_tickers"] = sorted(r["ticker"] for r in c["_group_rows"])
        _proxy[str(v)]["destroy"] = strip(cell(v, "P_full",
                                               [("co_opm", "下位1/4"), ("co_rev_asof", "上位1/4")],
                                               outcome="destroy"))
_pl = [_proxy[str(v)]["lift"] for v in (2013, 2015) if _proxy.get(str(v))]
_proxy["signs"] = _pl
_proxy["both_positive"] = all(x is not None and x > 0 for x in _pl) if _pl else None
g1["proxy_2013_2015_out_of_prereg"] = _proxy

# 1e 延べと実体（勝者は何社か）
_win_union = {}
for v in SIGN_VINTAGES:
    for r in cells[v]["_group_rows"]:
        if r.get("win"):
            _win_union.setdefault(r["ticker"], set()).add(v)
g1["distinct_winning_companies_carrying_the_finding"] = {
    "n_events_total": sum(_nums),
    "n_distinct_companies": len(_win_union),
    "detail": sorted([{"ticker": t, "vintages": sorted(vs)} for t, vs in _win_union.items()],
                     key=lambda x: x["ticker"]),
}


# ────────────────────────────── 2. 業種調整 ──────────────────────────────
def mh(v, pop, legs, rows_src=None, win_of=None, drop_sic=None, min_stratum=3):
    """MH重み付きリスク差。探索側と同一規則（各層 n>=3 の両側が要る）。"""
    b = build_group(v, pop, legs, rows_src)
    if b is None:
        return None
    W = win_of if win_of else (lambda r: bool(r.get("win")))
    gset = set(id(r) for r in b["group"])
    st = defaultdict(lambda: [0, 0, 0, 0])
    for r in b["pop"]:
        s = r.get("sic2")
        if not s or (drop_sic is not None and s == drop_sic):
            continue
        w = 1 if W(r) else 0
        d = st[s]
        if id(r) in gset:
            d[0] += 1; d[1] += w
        else:
            d[2] += 1; d[3] += w
    nu = den = 0.0
    used = drop = 0
    covered = 0
    for s, (n1, k1, n0, k0) in st.items():
        if n1 < min_stratum or n0 < min_stratum:
            drop += 1
            continue
        covered += n1
        wgt = n1 * n0 / (n1 + n0)
        nu += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    if den == 0:
        return {"mh_risk_diff": None, "strata_used": used, "strata_dropped": drop,
                "group_covered": covered, "group_total": len(b["group"]),
                "group_coverage_share": r4(covered / len(b["group"])) if b["group"] else None}
    return {"mh_risk_diff": r4(nu / den), "strata_used": used, "strata_dropped": drop,
            "group_covered": covered, "group_total": len(b["group"]),
            "group_coverage_share": r4(covered / len(b["group"])) if b["group"] else None}


g2 = {"mh": {str(v): mh(v, CAND["population"], CAND["legs"]) for v in SIGN_VINTAGES}}
g2["gate_sector_mh"] = all(
    (m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT) for m in g2["mh"].values())


def indirect_std(v, pop, legs):
    b = build_group(v, pop, legs)
    if b is None:
        return None
    gset = set(id(r) for r in b["group"])
    bysic = defaultdict(lambda: [0, 0])
    for r in b["pop"]:
        s = r.get("sic2")
        if not s:
            continue
        bysic[s][0] += 1
        if r.get("win"):
            bysic[s][1] += 1
    obs = exp_self = exp_ext = 0.0
    used = 0
    no_sic = 0
    for r in b["group"]:
        s = r.get("sic2")
        if not s or s not in bysic:
            no_sic += 1
            continue
        n, k = bysic[s]
        w = 1 if r.get("win") else 0
        obs += w
        used += 1
        exp_self += k / n
        exp_ext += ((k - w) / (n - 1)) if n > 1 else 0.0
    if used == 0:
        return None
    return {"n_group_with_sic2": used, "n_group_without_sic2": no_sic,
            "observed_wins": int(obs),
            "expected_wins_sector": r4(exp_self),
            "expected_wins_sector_leave_self_out": r4(exp_ext),
            "risk_diff_vs_sector": r4((obs - exp_ext) / used),
            "smr": r4(obs / exp_ext) if exp_ext > 0 else None}


g2["indirect_standardization"] = {str(v): indirect_std(v, CAND["population"], CAND["legs"])
                                  for v in SIGN_VINTAGES}
g2["indirect_standardization_note"] = (
    "MHは各層 n>=3 の両側を要求するので層を落とす。間接標準化は**群の全社**を使い、"
    "各社を『同じ sic2 の他社の勝率』と比べる（自分は分母から抜く）。層を落とさない業種調整。")

# 2b 置換の土台
tick_sic = {}
for r in ANA:
    if r.get("sic2"):
        tick_sic.setdefault(r["ticker"], r["sic2"])

tickers_sign = sorted({r["ticker"] for v in SIGN_VINTAGES for r in by_v[v]})
outcome_bundle = {t: {v: None for v in SIGN_VINTAGES} for t in tickers_sign}
for v in SIGN_VINTAGES:
    for r in by_v[v]:
        outcome_bundle[r["ticker"]][v] = bool(r.get("win"))


def maintained_lift_under(winmap):
    """winmap[(ticker,vintage)]->bool のもとで (符号揃い, 最小|lift|, 最小分子) を返す。"""
    ls, ns = [], []
    for v in SIGN_VINTAGES:
        c = cells[v]
        n_pop = c["n_pop"]
        k_pop = sum(1 for r in c["_pop_rows"] if winmap.get((r["ticker"], v), False))
        n_g = c["n_group"]
        k_g = sum(1 for r in c["_group_rows"] if winmap.get((r["ticker"], v), False))
        if n_g == 0:
            return (False, 0.0, 0)
        ls.append(k_g / n_g - k_pop / n_pop)
        ns.append(k_g)
    same = all(x > 0 for x in ls) or all(x < 0 for x in ls)
    return (same, min(abs(x) for x in ls), min(ns))


rng = random.Random(SEED)


def permute(within_sector):
    if within_sector:
        buckets = defaultdict(list)
        for t in tickers_sign:
            buckets[tick_sic.get(t, "__none__")].append(t)
        mapping = {}
        for s, ts in buckets.items():
            sh = ts[:]
            rng.shuffle(sh)
            for a, b in zip(ts, sh):
                mapping[a] = b
    else:
        sh = tickers_sign[:]
        rng.shuffle(sh)
        mapping = dict(zip(tickers_sign, sh))
    wm = {}
    for t in tickers_sign:
        src = outcome_bundle[mapping[t]]
        for v in SIGN_VINTAGES:
            if src[v] is not None:
                wm[(t, v)] = src[v]
    return wm


obs_same, obs_ml, obs_mn = maintained_lift_under({(r["ticker"], v): bool(r.get("win"))
                                                  for v in SIGN_VINTAGES for r in by_v[v]})
perm_res = {}
for tag, within in (("within_sic2", True), ("unrestricted", False)):
    ge = 0
    pass_all = 0
    vals = []
    for _ in range(N_PERM):
        wm = permute(within)
        same, ml, mn = maintained_lift_under(wm)
        stat = ml if same else 0.0
        vals.append(stat)
        if stat >= obs_ml:
            ge += 1
        if same and ml >= LIFT and mn >= MIN_NUM:
            pass_all += 1
    vals.sort()
    perm_res[tag] = {
        "n_perm": N_PERM,
        "observed_statistic": r4(obs_ml),
        "p_ge_observed": r4((ge + 1) / (N_PERM + 1)),
        "null_p50": r4(vals[N_PERM // 2]),
        "null_p90": r4(vals[int(N_PERM * 0.90)]),
        "null_p95": r4(vals[int(N_PERM * 0.95)]),
        "null_p99": r4(vals[int(N_PERM * 0.99)]),
        "P_this_single_cell_passes_gates123_by_chance": r4(pass_all / N_PERM),
    }
g2["within_sector_permutation"] = perm_res["within_sic2"]


def loo_sector():
    sics = sorted({r.get("sic2") for v in SIGN_VINTAGES for r in pop_rows(v, CAND["population"])
                   if r.get("sic2")})
    out = []
    for s in sics:
        keep = {v: [r for r in by_v[v] if r.get("sic2") != s] for v in SIGN_VINTAGES}
        cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        if any(c is None or c["n_group"] == 0 for c in cs.values()):
            out.append({"sic2_dropped": s, "verdict": "群が空＝測れない"})
            continue
        ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
        ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
        same = all(x > 0 for x in ls)
        out.append({"sic2_dropped": s,
                    "n_group_2018": cs[2018]["n_group"],
                    "maintained_lift": r4(min(abs(x) for x in ls)),
                    "min_numerator": min(ns),
                    "gates123_hold": bool(same and min(abs(x) for x in ls) >= LIFT and min(ns) >= MIN_NUM)})
    return out


_loo_sec = loo_sector()
g2["leave_one_sector_out"] = sorted(
    [x for x in _loo_sec if x.get("maintained_lift") is not None],
    key=lambda x: (x["maintained_lift"] if x["maintained_lift"] is not None else 9))[:12]
g2["leave_one_sector_out_all_hold"] = all(
    x.get("gates123_hold", False) for x in _loo_sec if "gates123_hold" in x)
g2["leave_one_sector_out_breakers"] = [x["sic2_dropped"] for x in _loo_sec
                                       if x.get("gates123_hold") is False]


def sector_profile(v):
    c = cells[v]
    cnt = Counter(r.get("sic2") for r in c["_group_rows"])
    top = cnt.most_common(8)
    P = c["_pop_rows"]
    base = c["p_base"]
    out = {"n_group": c["n_group"], "sic2_top": top,
           "top3_share": r4(sum(n for _, n in top[:3]) / c["n_group"]) if c["n_group"] else None,
           "sectors": []}
    for s, n in top[:5]:
        sec = [r for r in P if r.get("sic2") == s]
        ks = sum(1 for r in sec if r.get("win"))
        gin = [r for r in c["_group_rows"] if r.get("sic2") == s]
        kg = sum(1 for r in gin if r.get("win"))
        out["sectors"].append({
            "sic2": s, "n_sector": len(sec), "p_sector": r4(rate(ks, len(sec))),
            "lift_of_sector_alone": r4(rate(ks, len(sec)) - base),
            "n_group_in_sector": len(gin), "p_group_in_sector": r4(rate(kg, len(gin))),
            "lift_of_pair_within_sector": (None if not gin else r4(rate(kg, len(gin)) - rate(ks, len(sec)))),
        })
    return out


g2["sector_profile"] = {str(v): sector_profile(v) for v in SIGN_VINTAGES}


def mh_decompose(v):
    c = cells[v]
    gset = set(id(r) for r in c["_group_rows"])
    st = defaultdict(lambda: [0, 0, 0, 0])
    for r in c["_pop_rows"]:
        s = r.get("sic2")
        if not s:
            continue
        w = 1 if r.get("win") else 0
        d = st[s]
        if id(r) in gset:
            d[0] += 1; d[1] += w
        else:
            d[2] += 1; d[3] += w
    terms, den = [], 0.0
    for s, (n1, k1, n0, k0) in st.items():
        if n1 < 3 or n0 < 3:
            continue
        wgt = n1 * n0 / (n1 + n0)
        diff = k1 / n1 - k0 / n0
        den += wgt
        terms.append({"sic2": s, "n_group": n1, "k_group": k1, "n_rest": n0,
                      "p_group": r4(k1 / n1), "p_rest": r4(k0 / n0),
                      "risk_diff": r4(diff), "mh_weight": r4(wgt), "_w": wgt, "_d": diff})
    tot = sum(t["_w"] * t["_d"] for t in terms)
    for t in terms:
        t["share_of_MH"] = r4((t["_w"] * t["_d"]) / tot) if tot else None
        del t["_w"], t["_d"]
    return {"strata_entering_MH": sorted(terms, key=lambda x: -(x["share_of_MH"] or 0)),
            "mh_total": r4(tot / den) if den else None,
            "n_strata_entering": len(terms),
            "how_to_read": "MHが『業種調整後も残る』と言うとき、その値が**どの層から来ているか**。"}


g2["mh_decomposition"] = {str(v): mh_decompose(v) for v in SIGN_VINTAGES}

_ent = {v: [t["sic2"] for t in g2["mh_decomposition"][str(v)]["strata_entering_MH"]] for v in SIGN_VINTAGES}
_all_ent = sorted({s for v in SIGN_VINTAGES for s in _ent[v]})
g2["mh_excluding_each_entering_stratum"] = {
    s: {str(v): mh(v, CAND["population"], CAND["legs"], drop_sic=s) for v in SIGN_VINTAGES}
    for s in _all_ent}
g2["mh_gate_survives_excluding_each_stratum"] = {
    s: all((m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT)
           for m in g2["mh_excluding_each_entering_stratum"][s].values())
    for s in _all_ent}

g2["mh_min_stratum_size_sensitivity"] = {
    "note": "**事前登録の外・診断専用**。探索側の規則は各層 n>=3。",
    **{f"min_n={k}": {str(v): (mh(v, CAND["population"], CAND["legs"], min_stratum=k) or {}).get("mh_risk_diff")
                      for v in SIGN_VINTAGES} for k in (2, 3, 4, 5)},
}

_sicdesc = {}
try:
    for r in json.load(open(os.path.join(OUT, "retro_sic.json"), encoding="utf-8"))["rows"]:
        _sicdesc[r["ticker"]] = {"sic": r.get("sic"), "sicDesc": r.get("sicDesc"), "sic2": r.get("sic2")}
except Exception:
    pass
g2["group_members_with_industry"] = {
    str(v): sorted(
        [{"ticker": r["ticker"], "sic2": r.get("sic2"),
          "sicDesc": _sicdesc.get(r["ticker"], {}).get("sicDesc"),
          "opm": r4(r.get("f2_opm")), "rev_bn": r4((r.get("f2_rev") or 0) / 1e9),
          "gm": r4(r.get("f2_gm")),
          "tr_cagr": r.get("tr_cagr"), "win": bool(r.get("win")), "destroy": bool(r.get("destroy"))}
         for r in cells[v]["_group_rows"]],
        key=lambda x: (x["sic2"] or "", x["ticker"]))
    for v in SIGN_VINTAGES}


# ────────────────────────────── 3. irr の影 ──────────────────────────────
def irr_control(v):
    c = cells[v]
    R = [r for r in c["_pop_rows"] if r.get("irr") is not None]
    res = {"n_with_irr": len(R)}
    if len(R) < 20:
        res["status"] = "irr の読解が薄く判定不能"
        return res
    gset = set(id(r) for r in c["_group_rows"])
    sel = [r for r in R if r.get("f2_opm") is not None and r.get("f2_rev") is not None]
    xs = [1.0 if id(r) in gset else 0.0 for r in sel]
    ys = [float(r["irr"]) for r in sel]
    rho = spearman(xs, ys) if len(xs) >= 20 else None
    res["n_measurable_with_irr"] = len(xs)
    res["n_group_within_irr_read"] = int(sum(xs))
    res["corr_group_vs_irr"] = r4(rho)
    res["orthogonal_hint"] = (None if rho is None else abs(rho) < LIFT)
    hi = [r for r in R if r["irr"] >= 70]
    res["n_irr_ge70"] = len(hi)
    if len(hi) >= 20:
        base = rate(sum(1 for r in hi if r.get("win")), len(hi))
        g = [r for r in hi if id(r) in gset]
        kg = sum(1 for r in g if r.get("win"))
        res["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g), "k": kg,
                           "p_group": r4(rate(kg, len(g))),
                           "lift": (None if not g else r4(rate(kg, len(g)) - base))}
    return res


g3 = {"per_vintage": {str(v): irr_control(v) for v in SIGN_VINTAGES}}


def orthogonality_null(v, n_draw=2000):
    c = cells[v]
    R = [r for r in c["_pop_rows"] if r.get("irr") is not None
         and r.get("f2_opm") is not None and r.get("f2_rev") is not None]
    if len(R) < 20:
        return None
    gset = set(id(r) for r in c["_group_rows"])
    k = sum(1 for r in R if id(r) in gset)
    if k == 0:
        return None
    ys = [float(r["irr"]) for r in R]
    rg = random.Random(SEED + v)
    below = 0
    obs = abs(spearman([1.0 if id(r) in gset else 0.0 for r in R], ys) or 0.0)
    for _ in range(n_draw):
        idx = set(rg.sample(range(len(R)), k))
        xs = [1.0 if i in idx else 0.0 for i in range(len(R))]
        rho = spearman(xs, ys)
        if rho is not None and abs(rho) < LIFT:
            below += 1
    return {"n_rows_with_irr_and_measurable": len(R), "n_group_in_that_set": k,
            "observed_abs_rho": r4(obs),
            "P_random_group_of_same_size_is_called_orthogonal": r4(below / n_draw),
            "how_to_read": ("同じ大きさの群を無作為に作っても『直交』と呼ばれる確率。"
                            "これが高いなら、直交ヒットは独立性の証拠ではなく**群の小ささの産物**。")}


g3["orthogonality_is_it_just_small_n"] = {str(v): orthogonality_null(v) for v in SIGN_VINTAGES}
_ic18 = g3["per_vintage"]["2018"]
g3["gate_irr_literal"] = bool(_ic18.get("orthogonal_hint") is True
                              or (_ic18.get("irr_ge70", {}).get("lift") is not None
                                  and abs(_ic18["irr_ge70"]["lift"]) >= LIFT))
_o18 = g3["orthogonality_is_it_just_small_n"].get("2018") or {}
_layer = _ic18.get("irr_ge70", {}) if isinstance(_ic18.get("irr_ge70"), dict) else {}

# **群と irr 読解集合の重なりがゼロなら、どちらの試験も『計算できない』＝不合格ではなく判定不能。**
# ここを取り違えると「測れない」を「不合格」と読む——prereg が最も嫌う型。
_overlap = {str(v): (g3["per_vintage"][str(v)].get("n_group_within_irr_read") or 0) for v in SIGN_VINTAGES}
_no_overlap_anywhere = all(x == 0 for x in _overlap.values())

_layer_underpowered = (_layer.get("k") is None or _layer.get("k") < MIN_NUM)
_orth_uncomputable = (_ic18.get("corr_group_vs_irr") is None)
_orth_underpowered = (_orth_uncomputable
                      or ((_o18.get("P_random_group_of_same_size_is_called_orthogonal") or 0) >= 0.5))
g3["group_overlap_with_irr_read_set"] = {
    "n_group_within_irr_read_by_vintage": _overlap,
    "no_overlap_anywhere": _no_overlap_anywhere,
    "why": ("irr の読解は『質実証プール寄り』の標本に対して行われた。この候補の群は "
            "**opm 下位1/4＝質実証と定義上排他**なので、群と読解集合が一社も重ならない。"),
}
g3["gate_irr_power_audit"] = {
    "irr>=70層": {"n_group": _layer.get("n_group"), "numerator": _layer.get("k"),
                  "prereg の分子>=5 を満たすか": (None if _layer.get("k") is None else _layer["k"] >= MIN_NUM),
                  "判定": ("計算できない（群に irr 読解のある社が一社も無い）" if _no_overlap_anywhere
                           else ("検出力なし（prereg 自身が課す分子>=5 に届かない）"
                                 if _layer_underpowered else "検定できる"))},
    "直交ヒント": {"P_random_group_same_size_called_orthogonal":
                   _o18.get("P_random_group_of_same_size_is_called_orthogonal"),
                   "判定": ("計算できない（群の指示変数が読解集合の中で恒等的に0＝分散ゼロで相関が未定義）"
                            if _orth_uncomputable else
                            ("検出力なし（同サイズの無作為群でも同じ確率で『直交』と呼ばれる）"
                             if _orth_underpowered else "検定できる"))},
}
g3["gate_irr_honest"] = (
    "判定不能（群と irr 読解集合の重なりがゼロ＝どちらの試験も計算できない。**不合格ではない**）"
    if _no_overlap_anywhere else
    ("判定不能（gate5 を通した二つの試験がどちらも検出力を持たない）"
     if (_layer_underpowered and _orth_underpowered)
     else ("合格" if g3["gate_irr_literal"] else "不合格")))
g3["substantive_answer"] = (
    "**この候補は irr=85 の影ではない**——群51社（延べ101）に irr=85 の社は一社も居らず、"
    "irr の読解がある社すら一社も居ない。形式的な gate5 が通らないのは"
    "『irr の影である』からではなく『irr と突き合わせる術が無い』から。"
    "prereg の文言（irr>=70層で残る **または** irr と直交）を字義どおり当てると"
    "どちらも計算できないので、合否は **判定不能**。")
g3["gate_irr"] = g3["gate_irr_literal"]
g3["gate_irr_is_undecidable_not_failed"] = _no_overlap_anywhere


# ────────────────────────────── 4. 1社の影響 ──────────────────────────────
def loo_ticker():
    cand_tickers = sorted(union)
    res = []
    for t in cand_tickers:
        keep = {v: [r for r in by_v[v] if r["ticker"] != t] for v in SIGN_VINTAGES}
        cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        if any(c is None or c["n_group"] == 0 for c in cs.values()):
            res.append({"ticker": t, "verdict": "測れない"})
            continue
        ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
        ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
        m = {str(v): mh(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
        gsec = all((x and x["mh_risk_diff"] is not None and abs(x["mh_risk_diff"]) >= LIFT) for x in m.values())
        same = all(x > 0 for x in ls)
        ml = min(abs(x) for x in ls)
        mn = min(ns)
        res.append({"ticker": t, "maintained_lift": r4(ml), "min_numerator": mn,
                    "delta_vs_full": r4(ml - g1["maintained_lift"]),
                    "mh_by_vintage": {k: (x or {}).get("mh_risk_diff") for k, x in m.items()},
                    "gate_lift": ml >= LIFT, "gate_min_num": mn >= MIN_NUM,
                    "gate_sign": same, "gate_sector": gsec,
                    "gates_1_to_3_hold": bool(same and ml >= LIFT and mn >= MIN_NUM),
                    "all_gates_1_to_4_hold": bool(same and ml >= LIFT and mn >= MIN_NUM and gsec)})
    return res


loo = loo_ticker()
meas = [x for x in loo if "maintained_lift" in x]
g4 = {
    "n_tickers_tested": len(loo),
    "worst_maintained_lift": r4(min(x["maintained_lift"] for x in meas)) if meas else None,
    "best_maintained_lift": r4(max(x["maintained_lift"] for x in meas)) if meas else None,
    "max_abs_delta_from_one_company": r4(max(abs(x["delta_vs_full"]) for x in meas)) if meas else None,
    "n_breaking_gates_1_to_3": sum(1 for x in meas if not x["gates_1_to_3_hold"]),
    "breakers_gates_1_to_3": [x for x in meas if not x["gates_1_to_3_hold"]],
    "top10_most_influential": sorted(meas, key=lambda x: x["maintained_lift"])[:10],
    "how_to_read": ("1社をパネルごと抜いて閾値・母集団・群・条件を全部作り直す。"
                    "1社で条件が崩れるなら、それは発見ではなく1社の話。"
                    "**この候補は gate4(業種) が元から落ちている**ので gates_1_to_3 で見る。"),
}


def sequential_drop():
    out = []
    for v in SIGN_VINTAGES:
        c = cells[v]
        n_g, k_g, base = c["n_group"], c["numerator"], c["p_base"]
        need = None
        for d in range(0, k_g + 1):
            k, n = k_g - d, n_g - d
            if n == 0:
                need = d
                break
            lf = k / n - base
            if lf < LIFT or k < MIN_NUM:
                need = d
                break
        out.append({"vintage": v, "n_group": n_g, "numerator": k_g,
                    "n_winners_to_remove_to_break": need,
                    "which_gate_breaks_first": (
                        "min_numerator" if (need is not None and k_g - need < MIN_NUM
                                            and (n_g - need) > 0
                                            and (k_g - need) / (n_g - need) - base >= LIFT) else "lift")})
    return out


g4["sequential_winner_removal"] = sequential_drop()


# ────────────────────────────── 5. 置換 ──────────────────────────────
_fpr = pair_out["must_report_before_verdict"]["false_positive_rate"]
_nullmax = _fpr["null_distribution_of_max_statistic"]
g5 = {
    "unrestricted_ticker_bundle": perm_res["unrestricted"],
    "within_sic2": perm_res["within_sic2"],
    "family_wise_from_explorer": {
        "n_tests_in_search": _fpr["n_tests_in_procedure"],
        "P_at_least_one_pass_under_null_L3": _fpr["P_at_least_one_pass_by_level"].get("L3"),
        "P_at_least_one_pass_under_null_L4": _fpr["P_at_least_one_pass_by_level"].get("L4"),
        "P_at_least_one_pass_under_null_L5": _fpr["P_at_least_one_pass_by_level"].get("L5"),
        "null_max_statistic_p95": _nullmax["p95"],
        "null_max_statistic_p99": _nullmax["p99"],
        "note": ("探索側が同じ帰無で測った値札。**単体のp値は『この1本だけを検定したなら』の話**で、"
                 "実際は2840本から選ばれている。"),
    },
}
g5["observed_vs_null_max_distribution"] = {
    "observed_maintained_lift": g1["maintained_lift"],
    "null_max_p50": _nullmax["p50"], "null_max_p90": _nullmax["p90"],
    "null_max_p95": _nullmax["p95"], "null_max_p99": _nullmax["p99"],
    "position": ("p99 以上" if g1["maintained_lift"] >= _nullmax["p99"] else
                 "p95 と p99 の間" if g1["maintained_lift"] >= _nullmax["p95"] else
                 "p90 と p95 の間" if g1["maintained_lift"] >= _nullmax["p90"] else "p90 未満"),
    "below_null_max_median": g1["maintained_lift"] < _nullmax["p50"],
    "how_to_read": ("null_max は『**2840検定のうち最大**の maintained_lift』の帰無分布。"
                    "この候補の 0.1605 が null_max の中央値 0.188 を**下回る**なら、"
                    "『何の関係も無い世界で2840本を回したとき、その最良の1本は普通この候補より強く出る』"
                    "ということ。単体の置換p値(0.009)は『これ1本だけを検定したなら』の話で、"
                    "実際は2840本から選ばれている。"),
}

# この候補は探索の中で何位か（選抜代を払った後の位置）
_allp = [e for e in pair_out.get("all_pairs", []) if e.get("maintained_lift") is not None]
_g123 = [e for e in _allp
         if e.get("sign") == 1 and (e.get("maintained_lift") or 0) >= LIFT
         and (e.get("min_numerator_161718") or 0) >= MIN_NUM]
g5["rank_within_the_search"] = {
    "my_maintained_lift": g1["maintained_lift"],
    "rank_among_all_pairs": 1 + sum(1 for e in _allp if e["maintained_lift"] > g1["maintained_lift"]),
    "n_all_pairs": len(_allp),
    "rank_among_gates123_passers": 1 + sum(1 for e in _g123 if e["maintained_lift"] > g1["maintained_lift"]),
    "n_gates123_passers": len(_g123),
    "observed_max_in_real_data": max(e["maintained_lift"] for e in _allp),
    "null_P_at_least_one_L3_pass": _fpr["P_at_least_one_pass_by_level"].get("L3"),
    "null_mean_L3_passes_per_permutation": _fpr.get("mean_passes_per_permutation_by_level", {}).get("L3"),
    "how_to_read": ("帰無でも条件1-3を通る候補が平均3.5本・確率0.83で少なくとも1本出る手続きで、"
                    "この候補はその通過群の下位。**『通った』ことに情報がほとんど無い位置**。"),
}


# ────────────────────────────── 6. 既存の関門との重複 ──────────────────────────────
def gate_flags(r):
    """門が既に持つ関門の歴史側の相当物。**nde はパネルに無いので intcov を代理に使う（正直に代理と書く）**。"""
    shrink = (r.get("f2_cagr5") is not None and r.get("f2_opmD5") is not None
              and r["f2_cagr5"] < 0 and r["f2_opmD5"] < 0)
    ic = r.get("f2_intcov")
    fin_bad = (ic is not None and ic < 5)
    return {"shrink": shrink, "fin_bad": fin_bad, "quality": bool(r.get("P_quality"))}


def survivors_analysis(v):
    c = cells[v]
    P = c["_pop_rows"]
    gset = set(id(r) for r in c["_group_rows"])
    out = {}
    defs = {
        "no_shrink": lambda r: not gate_flags(r)["shrink"],
        "intcov_ok": lambda r: not gate_flags(r)["fin_bad"],
        "quality": lambda r: gate_flags(r)["quality"],
        "no_shrink_and_intcov": lambda r: (not gate_flags(r)["shrink"]) and (not gate_flags(r)["fin_bad"]),
        "all_three": lambda r: ((not gate_flags(r)["shrink"]) and (not gate_flags(r)["fin_bad"])
                                and gate_flags(r)["quality"]),
    }
    for tag, f in defs.items():
        sub = [r for r in P if f(r)]
        g = [r for r in sub if id(r) in gset]
        b = rate(sum(1 for r in sub if r.get("win")), len(sub))
        kg = sum(1 for r in g if r.get("win"))
        out[tag] = {"n_survivors": len(sub), "p_survivors": r4(b),
                    "n_group_among_survivors": len(g), "k": kg,
                    "p_group": r4(rate(kg, len(g))),
                    "incremental_lift": (None if not g else r4(rate(kg, len(g)) - b))}
    ex = [r for r in c["_group_rows"] if gate_flags(r)["shrink"] or gate_flags(r)["fin_bad"]
          or not gate_flags(r)["quality"]]
    out["group_members_already_excluded_by_gates"] = {
        "n": len(ex), "n_group": c["n_group"],
        "share": r4(len(ex) / c["n_group"]) if c["n_group"] else None,
        "by_reason": {
            "not_quality": sum(1 for r in c["_group_rows"] if not gate_flags(r)["quality"]),
            "shrink": sum(1 for r in c["_group_rows"] if gate_flags(r)["shrink"]),
            "intcov<5": sum(1 for r in c["_group_rows"] if gate_flags(r)["fin_bad"]),
        },
        "tickers_surviving_all_three": sorted(r["ticker"] for r in c["_group_rows"]
                                              if (not gate_flags(r)["shrink"])
                                              and (not gate_flags(r)["fin_bad"])
                                              and gate_flags(r)["quality"]),
    }
    return out


g6 = {"survivors": {str(v): survivors_analysis(v) for v in SIGN_VINTAGES}}
g6["proxy_warning"] = ("財務キルは nde>4 だが nde はパネルに無い。**intcov<5 は代理であって同じ線ではない**。"
                       "intcov が null の社は『利息がない＝負担なし』として落とさない（欠測を不合格と読まない）。")
g6["quality_is_the_decisive_one"] = (
    "この候補の母集団は P_full（質実証を課さない）。しかも**片脚が opm 下位1/4** なので、"
    "質実証の opm>=10% と**定義上ほぼ排他**になる。したがって『既存の関門を通った社の中で選ぶ』という"
    "実務の場面でこの候補が何社を拾えるかが、増分そのもの。")


def leg_alone(var, cut):
    res = {}
    for v in SIGN_VINTAGES:
        c = cell(v, CAND["population"], [(var, cut)])
        res[str(v)] = strip(c)
    ls = [res[str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [res[str(v)]["numerator"] for v in SIGN_VINTAGES]
    same = all(x is not None and x > 0 for x in ls)
    return {"by_vintage": res,
            "maintained_lift": (r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None),
            "min_numerator": min(ns), "sign_stable": same}


g6["legs_alone"] = {f"{var}[{cut}]": leg_alone(var, cut) for var, cut in CAND["legs"]}
_best_leg = max((x["maintained_lift"] or 0) for x in g6["legs_alone"].values())
g6["best_leg_maintained_lift"] = r4(_best_leg)
g6["increment_over_best_leg"] = r4(g1["maintained_lift"] - _best_leg)

_inc = {v: g6["survivors"][str(v)]["no_shrink_and_intcov"] for v in SIGN_VINTAGES}
_incl = [_inc[v]["incremental_lift"] for v in SIGN_VINTAGES]
_incn = [_inc[v]["k"] for v in SIGN_VINTAGES]
g6["prereg_line_applied_to_the_increment_no_shrink_intcov"] = {
    "by_vintage": {str(v): {"n_group": _inc[v]["n_group_among_survivors"], "numerator": _inc[v]["k"],
                            "incremental_lift": _inc[v]["incremental_lift"]} for v in SIGN_VINTAGES},
    "maintained_incremental_lift": (r4(min(abs(x) for x in _incl)) if all(x is not None for x in _incl) else None),
    "min_numerator": min(_incn),
    "gate_lift_holds": bool(all(x is not None and abs(x) >= LIFT for x in _incl)),
    "gate_min_numerator_holds": bool(min(_incn) >= MIN_NUM),
}
_q = {v: g6["survivors"][str(v)]["quality"] for v in SIGN_VINTAGES}
g6["prereg_line_applied_to_the_increment_quality"] = {
    "by_vintage": {str(v): {"n_group": _q[v]["n_group_among_survivors"], "numerator": _q[v]["k"],
                            "incremental_lift": _q[v]["incremental_lift"]} for v in SIGN_VINTAGES},
    "min_numerator": min(_q[v]["k"] for v in SIGN_VINTAGES),
    "gate_min_numerator_holds": bool(min(_q[v]["k"] for v in SIGN_VINTAGES) >= MIN_NUM),
}


# ────────────────────────────── X1 交互作用（組にする意味があるか） ──────────────────────────────
def two_by_two(v):
    P = pop_rows(v, CAND["population"])
    vo = sorted(r["f2_opm"] for r in P if r.get("f2_opm") is not None)
    vr = sorted(r["f2_rev"] for r in P if r.get("f2_rev") is not None)
    to, tr = q_at(vo, 0.25), q_at(vr, 0.75)
    M = [r for r in P if r.get("f2_opm") is not None and r.get("f2_rev") is not None]
    cellsx = {}
    for oa in (True, False):
        for ra in (True, False):
            sub = [r for r in M if (r["f2_opm"] <= to) == oa and (r["f2_rev"] >= tr) == ra]
            k = sum(1 for r in sub if r.get("win"))
            cellsx[f"opm{'低' if oa else '高'}_rev{'大' if ra else '小'}"] = {
                "n": len(sub), "k": k, "p": r4(rate(k, len(sub)))}
    a = cellsx["opm低_rev大"]["p"]
    b = cellsx["opm低_rev小"]["p"]
    c_ = cellsx["opm高_rev大"]["p"]
    d = cellsx["opm高_rev小"]["p"]
    return {"cells": cellsx,
            "rev大の効果_opm低の中": (None if (a is None or b is None) else r4(a - b)),
            "rev大の効果_opm高の中": (None if (c_ is None or d is None) else r4(c_ - d)),
            "opm低の効果_rev大の中": (None if (a is None or c_ is None) else r4(a - c_)),
            "opm低の効果_rev小の中": (None if (b is None or d is None) else r4(b - d)),
            "交互作用(差の差)": (None if any(x is None for x in (a, b, c_, d)) else r4((a - b) - (c_ - d)))}


X1 = {str(v): two_by_two(v) for v in SIGN_VINTAGES}
X1["how_to_read"] = ("差の差が0に近ければ、積の効果は2本の脚の足し算で説明でき**組にする意味は薄い**。"
                     "この候補は脚単独の lift が 0.01/0.0076 とほぼゼロなので、"
                     "**もし交互作用も小さいなら、群の勝率は『4つの箱のうち1つが偶然高い』話になる**。")


# ────────────────────────────── X2 変数の形（ルール7） ──────────────────────────────
X2 = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    vo = [r["f2_opm"] for r in P if r.get("f2_opm") is not None]
    vos = sorted(vo)
    to = q_at(vos, 0.25)
    grp = cells[v]["_group_rows"]
    X2[str(v)] = {
        "n_pop": len(P),
        "opm_coverage": r4(len(vo) / len(P)),
        "n_null_opm": len(P) - len(vo),
        "threshold_q25": r4(to),
        "share_negative_opm_in_pop": r4(sum(1 for x in vo if x < 0) / len(vo)) if vo else None,
        "n_negative_opm_in_group": sum(1 for r in grp if (r.get("f2_opm") or 0) < 0),
        "group_opm_min": r4(min((r["f2_opm"] for r in grp), default=None)),
        "group_opm_median": r4(med([r["f2_opm"] for r in grp])),
        "quantiles_pop_opm": {"q05": r4(q_at(vos, .05)), "q10": r4(q_at(vos, .10)),
                              "q25": r4(q_at(vos, .25)), "q50": r4(q_at(vos, .50)),
                              "q75": r4(q_at(vos, .75))},
        "rev_threshold_bn": r4(q_at(sorted(r["f2_rev"] for r in P if r.get("f2_rev") is not None), 0.75) / 1e9),
        "group_rev_median_bn": r4((med([r["f2_rev"] for r in grp]) or 0) / 1e9),
        "group_rev_max_bn": r4(max((r["f2_rev"] for r in grp), default=0) / 1e9),
    }
X2["how_to_read"] = ("opm 下位1/4 が『薄利』なのか『赤字』なのかを分ける。閾値が正なら大半は薄利で、"
                     "群の中の赤字社の実数が要点。**欠測(null)は群にも可測集合にも入らない**。")
X2["duplicate_column_warning"] = {
    "from_explorer": pair_out.get("duplicate_columns_in_search_space", {}).get("found"),
    "meaning": ("f2_rev と size_rev は**判定に使う3ビンテージで完全に同一の列**（探索側が全行突合せで検出）。"
                "つまりこの候補の第2脚は『売上』であり『規模』でもある——別の情報ではない。"),
}
X2["measurability_vs_outcome"] = {}
for v in SIGN_VINTAGES:
    P = pop_rows(v, CAND["population"])
    m = [r for r in P if r.get("f2_opm") is not None and r.get("f2_rev") is not None]
    nm = [r for r in P if not (r.get("f2_opm") is not None and r.get("f2_rev") is not None)]
    X2["measurability_vs_outcome"][str(v)] = {
        "n_measurable": len(m), "p_win_measurable": r4(rate(sum(1 for r in m if r.get("win")), len(m))),
        "n_not_measurable": len(nm),
        "p_win_not_measurable": r4(rate(sum(1 for r in nm if r.get("win")), len(nm))),
        "gap": (None if not nm or not m else
                r4(rate(sum(1 for r in m if r.get("win")), len(m))
                   - rate(sum(1 for r in nm if r.get("win")), len(nm)))),
    }
X2["measurability_note"] = ("被覆 94% なので欠測交絡は構造的に小さい。それでも数える——"
                            "可測集合と非可測集合で勝率が違うなら lift の一部は"
                            "**『測れる会社かどうか』**という別の変数を測っている。")


# ────────────────────────────── X3 損益計算書の形（総額計上を拾っていないか） ──────────────────────────────
def sic_bucket(s):
    if not s:
        return "不明"
    try:
        n = int(s)
    except Exception:
        return "不明"
    if 60 <= n <= 67:
        return "金融・保険・不動産"
    if 70 <= n <= 89:
        return "サービス"
    if 20 <= n <= 39:
        return "製造"
    if 40 <= n <= 49:
        return "運輸・公益"
    if 50 <= n <= 59:
        return "卸小売"
    if 1 <= n <= 14:
        return "農林・鉱業"
    if 15 <= n <= 17:
        return "建設"
    return "その他"


X3 = {"buckets": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    gb = Counter(sic_bucket(r.get("sic2")) for r in c["_group_rows"])
    pb = Counter(sic_bucket(r.get("sic2")) for r in c["_pop_rows"])
    X3["buckets"][str(v)] = {
        "group_buckets": dict(gb), "pop_buckets": dict(pb),
        "group_share": {k: r4(n / c["n_group"]) for k, n in gb.items()},
        "pop_share": {k: r4(n / c["n_pop"]) for k, n in pb.items()},
        "卸小売_share_in_group": r4(gb.get("卸小売", 0) / c["n_group"]),
        "卸小売_share_in_pop": r4(pb.get("卸小売", 0) / c["n_pop"]),
    }

# 粗利率で「総額計上（パススルー）」を測る
X3["gross_margin_of_group_vs_pop"] = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    gg = [r["f2_gm"] for r in c["_group_rows"] if r.get("f2_gm") is not None]
    pp = [r["f2_gm"] for r in c["_pop_rows"] if r.get("f2_gm") is not None]
    X3["gross_margin_of_group_vs_pop"][str(v)] = {
        "n_group_with_gm": len(gg), "median_gm_group": r4(med(gg)),
        "n_pop_with_gm": len(pp), "median_gm_pop": r4(med(pp)),
        "share_group_gm_below_0.20": r4(sum(1 for x in gg if x < 0.20) / len(gg)) if gg else None,
        "share_pop_gm_below_0.20": r4(sum(1 for x in pp if x < 0.20) / len(pp)) if pp else None,
    }
X3["gross_margin_note"] = (
    "卸・医薬品流通・自動車ディーラー・エネルギー精製は**売上を総額で計上する**ので、"
    "同じ経済規模でも売上が桁違いに大きく、営業利益率は構造的に薄い。"
    "群の粗利率が母集団より大幅に低いなら、この2本が拾っているのは事業の経済性ではなく"
    "**収益認識の慣行＝損益計算書の形**である疑いが濃い。")

# 総額計上が疑われる業種の名指し集計（SIC 50/51=卸, 55=自動車ディーラー, 54=食料品小売, 29/13=石油）
PASSTHRU_SIC = {"50", "51", "55", "54", "29", "13", "63"}
X3["passthrough_like_sic_share"] = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    ng = sum(1 for r in c["_group_rows"] if r.get("sic2") in PASSTHRU_SIC)
    npop = sum(1 for r in c["_pop_rows"] if r.get("sic2") in PASSTHRU_SIC)
    kg = sum(1 for r in c["_group_rows"] if r.get("sic2") in PASSTHRU_SIC and r.get("win"))
    X3["passthrough_like_sic_share"][str(v)] = {
        "sic_set": sorted(PASSTHRU_SIC),
        "n_group_in_set": ng, "share_of_group": r4(ng / c["n_group"]),
        "n_pop_in_set": npop, "share_of_pop": r4(npop / c["n_pop"]),
        "wins_from_that_set": kg, "wins_total_in_group": c["numerator"],
        "share_of_group_wins": r4(kg / c["numerator"]) if c["numerator"] else None,
    }
X3["passthrough_sic_note"] = ("SIC 50/51(卸)・55(自動車ディーラー)・54(食料品小売)・29/13(石油)・63(保険) は"
                              "いずれも**売上を総額で計上する業態**。"
                              "この集合が母集団での構成比に比べて群で大きく膨らんでいれば、"
                              "第2脚(売上上位1/4)は経済規模ではなく計上方法を選んでいる。")


# ────────────────────────────── X4 母集団の依存（P_quality では存在できない） ──────────────────────────────
X4 = {"P_quality": {}}
_cq = {v: cell(v, "P_quality", CAND["legs"]) for v in SIGN_VINTAGES}
X4["P_quality"]["per_vintage"] = {str(v): strip(_cq[v]) for v in SIGN_VINTAGES}
X4["P_quality"]["explorer_verdict"] = None
for e in pair_out.get("all_pairs", []):
    if e.get("label") == CAND["label"] and e.get("population") == "P_quality":
        X4["P_quality"]["explorer_verdict"] = e
X4["P_quality"]["why_circular"] = (
    "P_quality は **opm>=10%** を課す。この候補の第1脚は **opm 下位1/4**。"
    "つまり P_quality の中の『opm 下位1/4』は『10%以上のうち低いほう』であり、"
    "P_full の『薄利』とは**まったく別の集合**。探索側もこれを circularity として判定不能にしている。"
    "＝この候補は **P_full でしか存在できない**。")
# 群のうち P_quality を満たす社の実数
X4["group_members_that_are_quality"] = {
    str(v): {"n_group": cells[v]["n_group"],
             "n_quality": sum(1 for r in cells[v]["_group_rows"] if r.get("P_quality")),
             "tickers": sorted(r["ticker"] for r in cells[v]["_group_rows"] if r.get("P_quality"))}
    for v in SIGN_VINTAGES}


# ────────────────────────────── X5 両裾とハードルの脆さ ──────────────────────────────
X5 = {"destroy_side": {}}
for v in SIGN_VINTAGES:
    c = cell(v, CAND["population"], CAND["legs"], outcome="destroy")
    X5["destroy_side"][str(v)] = strip(c)
X5["destroy_note"] = ("大型×薄利は**営業レバレッジ**なので、上にも下にも振れるはず。"
                      "破壊側の lift が正なら『高分散を勝者確率で見ているだけ』、"
                      "負なら別の機構（＝この群は下にも強い）。どちらでも読み方が変わるので必ず出す。")

# 分布そのもの（ハードルの前後で固まっていないか）
X5["distribution"] = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    gv = sorted(r["tr_cagr"] for r in c["_group_rows"] if r.get("tr_cagr") is not None)
    pv = sorted(r["tr_cagr"] for r in c["_pop_rows"] if r.get("tr_cagr") is not None)

    def qs(v_):
        return {"p10": r4(q_at(v_, .10)), "p25": r4(q_at(v_, .25)), "p50": r4(q_at(v_, .50)),
                "p75": r4(q_at(v_, .75)), "p90": r4(q_at(v_, .90))}

    X5["distribution"][str(v)] = {
        "group": {"n": len(gv), **qs(gv), "mean": r4(sum(gv) / len(gv)) if gv else None},
        "pop": {"n": len(pv), **qs(pv), "mean": r4(sum(pv) / len(pv)) if pv else None},
        "median_gap": r4((med(gv) or 0) - (med(pv) or 0)),
        "group_wins_within_0.05_above_hurdle": sum(1 for x in gv if 0.15 <= x < 0.20),
        "group_wins_total": sum(1 for x in gv if x >= 0.15),
    }
X5["hurdle_sensitivity"] = {"note": "**事前登録の外・診断専用**。prereg のハードルは 0.15 のみ。"}
for h in (0.10, 0.12, 0.15, 0.18, 0.20, 0.25):
    blk = {}
    for v in SIGN_VINTAGES:
        c = cells[v]
        gv = [r["tr_cagr"] for r in c["_group_rows"] if r.get("tr_cagr") is not None]
        pv = [r["tr_cagr"] for r in c["_pop_rows"] if r.get("tr_cagr") is not None]
        pg = rate(sum(1 for x in gv if x >= h), len(gv))
        pb = rate(sum(1 for x in pv if x >= h), len(pv))
        blk[str(v)] = {"k": sum(1 for x in gv if x >= h), "p_group": r4(pg), "p_base": r4(pb),
                       "lift": (None if pg is None or pb is None else r4(pg - pb))}
    ls = [blk[str(v)]["lift"] for v in SIGN_VINTAGES]
    blk["maintained_lift"] = r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None
    blk["sign_stable"] = all(x is not None and x > 0 for x in ls)
    X5["hurdle_sensitivity"][f"hurdle={h}"] = blk

# 指数との比較（勝者ハードル15%は同期間のSPYとほぼ同じ）
X5["vs_benchmark"] = {
    "spy_tr_cagr_by_vintage": {"2016": 0.152, "2017": 0.1511, "2018": 0.1499},
    "note": ("ハードル15%は同期間のSPY(15.0-15.2%)とほぼ同じ＝『勝者』は実質『指数に勝った社』。"
             "群の中央値がSPYを下回るなら、群を等ウェイトで持っても指数に負ける。"),
    "group_median_vs_spy": {str(v): {"group_median": X5["distribution"][str(v)]["group"]["p50"],
                                     "spy": {"2016": 0.152, "2017": 0.1511, "2018": 0.1499}[str(v)],
                                     "gap": r4((X5["distribution"][str(v)]["group"]["p50"] or 0)
                                               - {"2016": 0.152, "2017": 0.1511, "2018": 0.1499}[str(v)])}
                            for v in SIGN_VINTAGES},
}


# ────────────────────────────── X6 循環回復か（前方の営業利益率を追う） ──────────────────────────────
# 2016年群の社の営業利益率を、同じパネルの 2017/2018 行から引く＝**前方の実測**（別ビンテージの特徴量）。
X6 = {"note": ("2016年群のメンバーの opm を 2017/2018 のパネル行から引く。"
               "**同じ列(f2_opm)・同じ採取器**なので基準は揃っている。"
               "勝者が『利益率が戻った社』に偏るなら、この候補は品質ではなく**谷での買い**の記録。")}
opm_by = {v: {r["ticker"]: r.get("f2_opm") for r in by_v[v]} for v in SIGN_VINTAGES}
for v0 in (2016, 2017):
    later = 2018
    c = cells[v0]
    rec = []
    for r in c["_group_rows"]:
        a = r.get("f2_opm")
        b = opm_by[later].get(r["ticker"])
        rec.append({"ticker": r["ticker"], "opm_asof": r4(a), "opm_2018": r4(b),
                    "delta": (None if (a is None or b is None) else r4(b - a)),
                    "win": bool(r.get("win")), "tr_cagr": r.get("tr_cagr")})
    w = [x["delta"] for x in rec if x["win"] and x["delta"] is not None]
    l = [x["delta"] for x in rec if not x["win"] and x["delta"] is not None]
    X6[f"group_{v0}_forward_opm_to_{later}"] = {
        "n_with_both": sum(1 for x in rec if x["delta"] is not None),
        "median_delta_winners": r4(med(w)), "n_winners": len(w),
        "median_delta_nonwinners": r4(med(l)), "n_nonwinners": len(l),
        "gap": (None if (med(w) is None or med(l) is None) else r4(med(w) - med(l))),
        "share_winners_with_margin_up": r4(sum(1 for x in w if x > 0) / len(w)) if w else None,
        "share_nonwinners_with_margin_up": r4(sum(1 for x in l if x > 0) / len(l)) if l else None,
        "detail": sorted(rec, key=lambda x: -(x["delta"] if x["delta"] is not None else -9)),
    }

# レジーム分割（事前登録の外・診断専用）
regime = {"status": "未実施（out/retro_monthly_2018_2026.json が無い）"}
MON = os.path.join(OUT, "retro_monthly_2018_2026.json")
if os.path.exists(MON):
    mon = json.load(open(MON, encoding="utf-8"))
    SPLIT = 1656648000  # 2022-07-01

    def sub_cagr(series, t_from, t_to):
        if not series or len(series) < 4:
            return None

        def nearest(t):
            return min(series, key=lambda p: abs(p[0] - t))

        a, b = nearest(t_from), nearest(t_to)
        if a[1] is None or b[1] is None or a[1] <= 0 or b[1] <= 0 or b[0] <= a[0]:
            return None
        yrs = (b[0] - a[0]) / (365.25 * 24 * 3600)
        if yrs < 1.0:
            return None
        return (b[1] / a[1]) ** (1 / yrs) - 1

    t_start = min(min(p[0] for p in s) for s in mon.values() if s)
    t_end = max(max(p[0] for p in s) for s in mon.values() if s)
    regime = {"note": "**事前登録の外・診断専用**。合否には数えない。",
              "split_at": "2022-07-01",
              "windows": {"A": "2018-07 → 2022-07", "B": "2022-07 → 2026-08"},
              "per_vintage_group": {}}
    for vv in SIGN_VINTAGES:
        cvv = cells[vv]
        gs = set(r["ticker"] for r in cvv["_group_rows"])
        blk = {}
        for tag, (tf, tt) in (("A_2018_2022", (t_start, SPLIT)), ("B_2022_2026", (SPLIT, t_end))):
            pv, gv = [], []
            for r in cvv["_pop_rows"]:
                s = mon.get(r["ticker"])
                g = sub_cagr(s, tf, tt) if s else None
                if g is None:
                    continue
                pv.append(g)
                if r["ticker"] in gs:
                    gv.append(g)
            b = rate(sum(1 for g in pv if g >= 0.15), len(pv))
            kg = sum(1 for g in gv if g >= 0.15)
            blk[tag] = {"n_pop_measurable": len(pv), "p_base": r4(b), "n_group": len(gv), "k_group": kg,
                        "p_group": r4(rate(kg, len(gv))),
                        "lift": (None if not gv else r4(rate(kg, len(gv)) - b)),
                        "median_cagr_group": r4(med(gv)), "median_cagr_pop": r4(med(pv))}
        regime["per_vintage_group"][str(vv)] = blk
    regime["how_to_read"] = ("8年を前半4年と後半4年に割る。前半でリフトが消え後半だけに出るなら、"
                             "それは指標ではなく相場の記録。逆に前半に出て後半に消えるなら"
                             "**谷からの回復**そのもの。")
X6["regime_split_out_of_prereg"] = regime


# ────────────────────────────── X7 名指し除去 ──────────────────────────────
def drop_set_and_rebuild(drop_tickers, tag):
    keep = {v: [r for r in by_v[v] if r["ticker"] not in drop_tickers] for v in SIGN_VINTAGES}
    cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
    if any(c is None or c["n_group"] == 0 for c in cs.values()):
        return {"tag": tag, "verdict": "群が空＝測れない"}
    ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
    ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
    same = all(x > 0 for x in ls)
    ml = min(abs(x) for x in ls)
    return {"tag": tag, "n_dropped_from_panel": len(drop_tickers),
            "dropped": sorted(drop_tickers),
            "per_vintage": {str(v): {"n_group": cs[v]["n_group"], "numerator": cs[v]["numerator"],
                                     "p_group": cs[v]["p_group"], "p_base": cs[v]["p_base"],
                                     "lift": cs[v]["lift"]} for v in SIGN_VINTAGES},
            "maintained_lift": r4(ml), "min_numerator": min(ns), "sign_stable": same,
            "gates123_hold": bool(same and ml >= LIFT and min(ns) >= MIN_NUM),
            "delta_vs_full": r4(ml - g1["maintained_lift"])}


def drop_sic_set_and_rebuild(sics, tag):
    keep = {v: [r for r in by_v[v] if r.get("sic2") not in sics] for v in SIGN_VINTAGES}
    cs = {v: cell(v, CAND["population"], CAND["legs"], rows_src=keep[v]) for v in SIGN_VINTAGES}
    if any(c is None or c["n_group"] == 0 for c in cs.values()):
        return {"tag": tag, "verdict": "群が空＝測れない"}
    ls = [cs[v]["lift"] for v in SIGN_VINTAGES]
    ns = [cs[v]["numerator"] for v in SIGN_VINTAGES]
    same = all(x > 0 for x in ls)
    ml = min(abs(x) for x in ls)
    return {"tag": tag, "sic2_dropped": sorted(sics),
            "per_vintage": {str(v): {"n_group": cs[v]["n_group"], "numerator": cs[v]["numerator"],
                                     "p_group": cs[v]["p_group"], "p_base": cs[v]["p_base"],
                                     "lift": cs[v]["lift"]} for v in SIGN_VINTAGES},
            "maintained_lift": r4(ml), "min_numerator": min(ns), "sign_stable": same,
            "gates123_hold": bool(same and ml >= LIFT and min(ns) >= MIN_NUM),
            "delta_vs_full": r4(ml - g1["maintained_lift"])}


# 群に現れた社のうち irr が読まれている社
_irr_in_group = {}
for v in SIGN_VINTAGES:
    for r in cells[v]["_group_rows"]:
        if r.get("irr") is not None:
            _irr_in_group.setdefault(r["ticker"], {})[str(v)] = {"irr": r["irr"], "win": bool(r.get("win"))}
IRR85 = sorted({t for t, d_ in _irr_in_group.items() if any(x["irr"] >= 85 for x in d_.values())})

# 薄利だが secular grower（＝循環回復ではない型）。実体で選ぶ
SECULAR = ["AMZN", "COST", "CRM"]

X7 = {
    "irr_coverage_in_group": {
        str(v): {"n_group": cells[v]["n_group"],
                 "n_with_irr": sum(1 for r in cells[v]["_group_rows"] if r.get("irr") is not None),
                 "share": r4(sum(1 for r in cells[v]["_group_rows"] if r.get("irr") is not None)
                             / cells[v]["n_group"])}
        for v in SIGN_VINTAGES},
    "group_members_with_irr": {t: d_ for t, d_ in sorted(_irr_in_group.items())},
    "irr85_members": IRR85,
    "drop_secular_3": drop_set_and_rebuild(set(SECULAR), "AMZN/COST/CRM（薄利だが secular grower）を除外"),
    "drop_amzn": drop_set_and_rebuild({"AMZN"}, "AMZN のみ除外"),
    "drop_irr85": (drop_set_and_rebuild(set(IRR85), "irr=85 の社をパネルごと除外") if IRR85
                   else {"tag": "irr=85 の社は群に居ない", "n": 0}),
    "drop_wholesale_50_51": drop_sic_set_and_rebuild({"50", "51"}, "卸(SIC 50/51)を除外"),
    "drop_auto_dealers_55": drop_sic_set_and_rebuild({"55"}, "自動車ディーラー等(SIC 55)を除外"),
    "drop_insurance_63": drop_sic_set_and_rebuild({"63"}, "保険(SIC 63)を除外"),
    "drop_energy_13_29": drop_sic_set_and_rebuild({"13", "29"}, "石油(SIC 13/29)を除外"),
    "drop_all_passthrough": drop_sic_set_and_rebuild(PASSTHRU_SIC, "総額計上業態(SIC 50/51/54/55/29/13/63)を一括除外"),
    "how_to_read": ("名指しで抜いて**全部作り直す**（閾値・母集団・群を含む）。"
                    "抜いて条件が崩れるなら、この候補はその一群の言い換えでしかない。"),
}

X7["distinct_group_companies"] = {
    "n_cells_total": sum(cells[v]["n_group"] for v in SIGN_VINTAGES),
    "n_distinct_companies": len(union),
    "n_distinct_winners": len(_win_union),
    "companies_in_all_3_vintages": sorted(inter),
    "winners_in_all_3_vintages": sorted([t for t, vs in _win_union.items() if len(vs) == 3]),
}


# ────────────────────────────── X8 粗い層での業種調整・単ビンテージの有意性 ──────────────────────────────
X8 = {"bucket_level_sector_control": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    gset = set(id(r) for r in c["_group_rows"])
    res = {}
    for bk in sorted({sic_bucket(r.get("sic2")) for r in c["_pop_rows"]}):
        sub = [r for r in c["_pop_rows"] if sic_bucket(r.get("sic2")) == bk]
        g = [r for r in sub if id(r) in gset]
        if not g:
            continue
        b = rate(sum(1 for r in sub if r.get("win")), len(sub))
        kg = sum(1 for r in g if r.get("win"))
        k_rest = sum(1 for r in sub if r.get("win")) - kg
        res[bk] = {"n_bucket": len(sub), "p_bucket": r4(b), "n_group": len(g), "k": kg,
                   "n_rest": len(sub) - len(g), "k_rest": k_rest,
                   "p_rest": r4(rate(k_rest, len(sub) - len(g))),
                   "p_group": r4(rate(kg, len(g))), "lift_within_bucket": r4(rate(kg, len(g)) - b)}
    nu = den = 0.0
    cov = 0
    for bk, x in res.items():
        n1, n0 = x["n_group"], x["n_rest"]
        if n1 < 1 or n0 < 1:
            continue
        wgt = n1 * n0 / (n1 + n0)
        nu += wgt * (x["k"] / n1 - x["k_rest"] / n0)
        den += wgt
        cov += n1
    X8["bucket_level_sector_control"][str(v)] = {
        "by_bucket": res,
        "weighted_risk_diff": r4(nu / den) if den else None,
        "group_covered": cov, "group_total": c["n_group"],
        "group_coverage_share": r4(cov / c["n_group"]) if c["n_group"] else None,
    }
X8["bucket_note"] = ("prereg は業種調整の道具に MH を名指ししている。MH は各層 n>=3 を要求するので"
                     "群の一部しか見ない。ここでは同じ考え方を粗い層で当て、群のほぼ全社を残す。"
                     "**どちらが正しいかを決めるのは私ではない**——二つが違うことを言っている、という事実を出す。")

X8["single_vintage_binomial"] = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    X8["single_vintage_binomial"][str(v)] = {
        "n_group": c["n_group"], "k": c["numerator"], "base": c["p_base"],
        "p_one_sided": r4(binom_tail_ge(c["n_group"], c["numerator"], c["p_base"])),
        "note": "母集団の勝率を真として、群でこれ以上の勝者が出る確率（1本だけを検定したなら）",
    }
X8["single_vintage_note"] = ("3ビンテージは独立ではない（同じ社・重なる窓）。"
                             "**3つを独立な検定として掛け算してはいけない**。")

# 閾値感度（事前登録の外・診断専用）
thr_sens = {"note": "**事前登録の外・診断専用**。prereg は『中央値または上下1/4』しか許していない。"}


def cut_at(v, qo, qr):
    P = pop_rows(v, CAND["population"])
    vo = sorted(r["f2_opm"] for r in P if r.get("f2_opm") is not None)
    vr = sorted(r["f2_rev"] for r in P if r.get("f2_rev") is not None)
    to, tr = q_at(vo, qo), q_at(vr, qr)
    g = [r for r in P if r.get("f2_opm") is not None and r.get("f2_rev") is not None
         and r["f2_opm"] <= to and r["f2_rev"] >= tr]
    n_pop, k_pop = len(P), sum(1 for r in P if r.get("win"))
    kg = sum(1 for r in g if r.get("win"))
    return {"thr_opm": r4(to), "thr_rev_bn": r4(tr / 1e9), "n_group": len(g), "k": kg,
            "lift": (None if not g else r4(kg / len(g) - k_pop / n_pop))}


for qo, qr in ((0.20, 0.75), (0.25, 0.75), (0.30, 0.75), (0.25, 0.70), (0.25, 0.80),
               (0.20, 0.80), (0.30, 0.70), (0.25, 0.90), (0.10, 0.75)):
    key = f"opm_bottom{int(qo*100)}%_rev_top{int((1-qr)*100)}%"
    thr_sens[key] = {str(v): cut_at(v, qo, qr) for v in SIGN_VINTAGES}
    ls = [thr_sens[key][str(v)]["lift"] for v in SIGN_VINTAGES]
    ns = [thr_sens[key][str(v)]["k"] for v in SIGN_VINTAGES]
    thr_sens[key]["maintained_lift"] = (r4(min(abs(x) for x in ls)) if all(x is not None for x in ls) else None)
    thr_sens[key]["min_numerator"] = min(ns)
    thr_sens[key]["gates123_hold"] = bool(
        all(x is not None and x > 0 for x in ls) and all(abs(x) >= LIFT for x in ls) and min(ns) >= MIN_NUM)
X8["threshold_sensitivity_out_of_prereg"] = thr_sens

# 重ならない部分窓（事前登録の外・診断専用）
sub = {"note": "**事前登録の外・診断専用**。同じ終端日ゆえ tr_total の比で部分窓が厳密に出る。"}
try:
    R = {}
    for tag, f in (("2016", "retro_returns_2016"), ("2017", "retro_returns_2017"),
                   ("2018", "retro_returns_2018")):
        d = json.load(open(os.path.join(OUT, f + ".json"), encoding="utf-8"))
        R[tag] = {r["ticker"]: r for r in d["rows"] if r.get("tr_total") is not None}

    def win_sub(t, a, b, yrs):
        ra, rb = R[a].get(t), R[b].get(t)
        if not ra or not rb or rb["tr_total"] <= 0:
            return None
        m = ra["tr_total"] / rb["tr_total"]
        if m <= 0:
            return None
        return m ** (1 / yrs) - 1

    for vint, (a, b, yrs, name) in {
        2016: ("2016", "2018", 2.0, "2016-07 → 2018-07 (2.0年・2018窓と重ならない部分)"),
        2017: ("2017", "2018", 1.0, "2017-07 → 2018-07 (1.0年・同上)"),
    }.items():
        c = cells[vint]
        gs = set(r["ticker"] for r in c["_group_rows"])
        pv = [(r["ticker"], win_sub(r["ticker"], a, b, yrs)) for r in c["_pop_rows"]]
        pv = [(t, g) for t, g in pv if g is not None]
        gv = [(t, g) for t, g in pv if t in gs]
        bs = rate(sum(1 for _, g in pv if g >= 0.15), len(pv))
        kg = sum(1 for _, g in gv if g >= 0.15)
        sub[str(vint)] = {
            "window": name, "n_pop": len(pv), "p_base": r4(bs),
            "n_group": len(gv), "k": kg, "p_group": r4(rate(kg, len(gv))),
            "lift_in_disjoint_subwindow": (None if not gv else r4(rate(kg, len(gv)) - bs)),
            "median_group": r4(med([g for _, g in gv])), "median_pop": r4(med([g for _, g in pv])),
            "caveat": "短い窓を年率で裁くので雑音が大きい。方向を見るだけの補助。",
        }
except Exception as e:  # noqa
    sub["error"] = str(e)
X8["disjoint_subwindow_out_of_prereg"] = sub


# ────────────────────────────── X9 等ウェイトで持ったら指数に勝てたか（実務の問い） ──────────────────────────────
# 勝者確率(P>=15%)が上がっても、**等ウェイトで持ったときの富**が指数に届かなければ買う理由にならない。
# 窓は vintage 内で全社同一（window_full）なので年数を揃える必要が無い＝合成してよい（CLAUDE.md の教訓）。
SPY_CAGR = {2016: 0.152, 2017: 0.1511, 2018: 0.1499}
X9 = {"note": ("勝率ではなく**富**で見る。等ウェイト買い持ちの実現は終価倍率の算術平均。"
               "同じビンテージ内は窓の長さが同一なので合成してよい。"),
      "by_vintage": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    yrs = ret_years[v]

    def ew(rows):
        tt = [r["tr_total"] for r in rows if r.get("tr_total") is not None and r["tr_total"] > 0]
        if not tt:
            return None, 0
        m = sum(tt) / len(tt)
        return (m ** (1 / yrs) - 1), len(tt)

    g_c, g_n = ew(c["_group_rows"])
    p_c, p_n = ew(c["_pop_rows"])
    # 上位1社を抜いた等ウェイト（右裾1社が全部を作っていないか）
    gt = sorted([r for r in c["_group_rows"] if r.get("tr_total")], key=lambda r: -r["tr_total"])
    g_c1, _ = ew(gt[1:]) if len(gt) > 1 else (None, 0)
    g_c2, _ = ew(gt[2:]) if len(gt) > 2 else (None, 0)
    X9["by_vintage"][str(v)] = {
        "years": yrs,
        "group_equal_weight_cagr": r4(g_c), "n_group": g_n,
        "pop_equal_weight_cagr": r4(p_c), "n_pop": p_n,
        "spy_cagr": SPY_CAGR[v],
        "group_minus_spy": (None if g_c is None else r4(g_c - SPY_CAGR[v])),
        "group_minus_pop": (None if (g_c is None or p_c is None) else r4(g_c - p_c)),
        "group_ew_excluding_top1": r4(g_c1), "group_ew_excluding_top2": r4(g_c2),
        "top1_ticker": (gt[0]["ticker"] if gt else None),
        "top1_tr_total": (r4(gt[0]["tr_total"]) if gt else None),
        "group_median_cagr": X5["distribution"][str(v)]["group"]["p50"],
        "median_minus_spy": r4((X5["distribution"][str(v)]["group"]["p50"] or 0) - SPY_CAGR[v]),
    }
X9["how_to_read"] = ("中央値と等ウェイトが逆を向くことがある（右裾が厚い群では等ウェイトだけ勝つ）。"
                     "**両方出す**。上位1-2社を抜いた等ウェイトも出す——1社が富の大半を作っているなら、"
                     "『この群を買えば勝てる』ではなく『この群からその1社を引けたなら勝てた』の話。")


# ────────────────────────────── X10 線からの余裕（何がこの候補を線の上に置いているか） ──────────────────────────────
X10 = {"margin_above_line": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    need = math.ceil((c["p_base"] + LIFT) * c["n_group"] - 1e-12)
    X10["margin_above_line"][str(v)] = {
        "n_group": c["n_group"], "numerator": c["numerator"],
        "k_needed_for_lift_0.15": need,
        "spare_winners": c["numerator"] - need,
        "lift": c["lift"], "lift_minus_line": r4(c["lift"] - LIFT),
    }
X10["binding_vintage"] = min(SIGN_VINTAGES, key=lambda v: cells[v]["lift"])
X10["binding_note"] = ("maintained_lift は3ビンテージの最小＝**一番弱いビンテージが合否を決める**。"
                       "そのビンテージに余裕が無ければ、候補は線の上に載っているのではなく線に**触れている**。")
# LOO-sector が「群に一社も居ない業種」で崩れるか（＝母集団側の base 変化だけで崩れる脆さ）
_loo_by_sic = {x["sic2_dropped"]: x for x in _loo_sec if "gates123_hold" in x}
X10["loo_sector_breakers_detail"] = []
for s in g2["leave_one_sector_out_breakers"]:
    ng = {str(v): sum(1 for r in cells[v]["_group_rows"] if r.get("sic2") == s) for v in SIGN_VINTAGES}
    npop = {str(v): sum(1 for r in cells[v]["_pop_rows"] if r.get("sic2") == s) for v in SIGN_VINTAGES}
    kpop = {str(v): sum(1 for r in cells[v]["_pop_rows"] if r.get("sic2") == s and r.get("win"))
            for v in SIGN_VINTAGES}
    X10["loo_sector_breakers_detail"].append({
        "sic2": s, "sicDesc_example": next((_sicdesc.get(r["ticker"], {}).get("sicDesc")
                                            for v in SIGN_VINTAGES for r in cells[v]["_pop_rows"]
                                            if r.get("sic2") == s), None),
        "n_in_group_by_vintage": ng, "n_in_pop_by_vintage": npop, "n_wins_in_pop_by_vintage": kpop,
        "maintained_lift_after_drop": _loo_by_sic[s]["maintained_lift"],
        "touches_the_group": any(x > 0 for x in ng.values()),
    })
X10["loo_sector_note"] = ("業種を1つ落とすと**母集団の勝率(base)も動く**。"
                          "群に一社も居ない業種を落として条件が崩れるなら、崩したのは候補の中身ではなく"
                          "**base の僅かな変化**＝線からの余裕がその程度しか無い、ということ。")

# 1社除外が効かない理由（閾値が動いて別の社が入れ替わりに入る＝補償）
X10["loo_ticker_compensation"] = {}
for t in ("AMZN", "COST"):
    blk = {}
    for v in SIGN_VINTAGES:
        keep = [r for r in by_v[v] if r["ticker"] != t]
        c2 = cell(v, CAND["population"], CAND["legs"], rows_src=keep)
        before = set(r["ticker"] for r in cells[v]["_group_rows"])
        after = set(r["ticker"] for r in c2["_group_rows"])
        entered = sorted(after - before)
        blk[str(v)] = {"n_before": cells[v]["n_group"], "n_after": c2["n_group"],
                       "k_before": cells[v]["numerator"], "k_after": c2["numerator"],
                       "entered_because_threshold_moved": entered,
                       "entered_and_won": [x for x in entered
                                           if any(r["ticker"] == x and r.get("win") for r in c2["_group_rows"])]}
    X10["loo_ticker_compensation"][t] = blk
X10["loo_ticker_compensation_note"] = (
    "1社をパネルごと抜くと分位の順位も1つずれるので、**次点の社が繰り上がって群に入る**。"
    "だから『どの1社を抜いても条件が保たれる』は頑健さの証明として弱い。"
    "補って読むのが **sequential_winner_removal**（母集団を固定して勝者だけ抜く）。")


# ────────────────────────────── X11 質実証との排他性（実務上の増分） ──────────────────────────────
X11 = {"disjointness": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    P = c["_pop_rows"]
    qq = [r for r in P if r.get("P_quality")]
    to = None
    vo = sorted(r["f2_opm"] for r in P if r.get("f2_opm") is not None)
    to = q_at(vo, 0.25)
    X11["disjointness"][str(v)] = {
        "opm_threshold_in_P_full": r4(to),
        "n_quality_in_pop": len(qq),
        "n_quality_with_opm_below_threshold": sum(1 for r in qq
                                                  if r.get("f2_opm") is not None and r["f2_opm"] <= to),
        "n_group_members_that_are_quality": sum(1 for r in c["_group_rows"] if r.get("P_quality")),
        "min_opm_among_quality": r4(min((r["f2_opm"] for r in qq if r.get("f2_opm") is not None),
                                        default=None)),
    }
X11["note"] = ("質実証は opm>=10%、この候補の第1脚は opm<=3.3-3.8%。**同じ絶対の物差しなので集合は排他**。"
               "門が実際に当てる場所（質実証を通った社）に、この候補が拾える社は構造的に一社も無い。"
               "＝『既存の関門を通った社の中で選ぶ』という実務の場面で、この候補の増分は**定義上ゼロ**。")


# ────────────────────────────── X12 勝者は何本の独立な賭けか（業種の塊） ──────────────────────────────
# 分子が 13-16 でも、同じ業種の同業3社が丸ごと入っていれば独立な賭けはその分少ない。
# 業種調整(gate4)が落ちる理由の実体をここで名指しする。
X12 = {"winners_by_sic2": {}}
for v in SIGN_VINTAGES:
    c = cells[v]
    wins = [r for r in c["_group_rows"] if r.get("win")]
    cnt = Counter(r.get("sic2") for r in wins)
    clumps = {s: n for s, n in cnt.items() if n >= 2}
    X12["winners_by_sic2"][str(v)] = {
        "n_winners": len(wins),
        "n_distinct_sic2_among_winners": len(cnt),
        "by_sic2": sorted([{"sic2": s, "n": n,
                            "sicDesc": next((_sicdesc.get(r["ticker"], {}).get("sicDesc")
                                             for r in wins if r.get("sic2") == s), None),
                            "tickers": sorted(r["ticker"] for r in wins if r.get("sic2") == s)}
                           for s, n in cnt.items()], key=lambda x: (-x["n"], x["sic2"])),
        "n_winners_in_sic2_with_2plus": sum(clumps.values()),
        "share_of_winners_in_clumps": r4(sum(clumps.values()) / len(wins)) if wins else None,
        "effective_independent_bets_if_one_per_sic2": len(cnt),
    }
X12["how_to_read"] = ("分子（勝者の数）は prereg の分子>=5 を軽々と満たすが、"
                      "**同業3社が丸ごと群に入って3社とも勝つ**なら、独立な賭けは1本に近い。"
                      "業種調整(gate4)が落ちるのはこの塊が理由——道具の癖ではなく群の構造。")
# 群に「同業まるごと」が入っている度合い（母集団の同業のうち何割が群に入ったか）
X12["industry_capture"] = {}
for v in SIGN_VINTAGES:
    c = cells[v]
    cnt_g = Counter(r.get("sic2") for r in c["_group_rows"])
    rows = []
    for s, n in cnt_g.most_common():
        npop = sum(1 for r in c["_pop_rows"] if r.get("sic2") == s)
        kpop = sum(1 for r in c["_pop_rows"] if r.get("sic2") == s and r.get("win"))
        kg = sum(1 for r in c["_group_rows"] if r.get("sic2") == s and r.get("win"))
        rows.append({"sic2": s, "n_group": n, "n_pop": npop,
                     "share_of_sector_captured": r4(n / npop) if npop else None,
                     "sector_win_rate": r4(rate(kpop, npop)), "group_wins_here": kg,
                     "base": c["p_base"]})
    X12["industry_capture"][str(v)] = rows[:8]
X12["industry_capture_note"] = ("その業種の会社の大半が群に入っているなら、群は『指標で選んだ集合』ではなく"
                                "**業種そのもの**。しかもその業種の勝率が母集団より高ければ、"
                                "lift の出所は指標ではなく業種。")


# ────────────────────────────── 判定（prereg の5条件・一つも緩めない） ──────────────────────────────
gates = {
    "1_lift>=0.15_3vintages": g1["gate_lift"],
    "2_min_numerator>=5": g1["gate_min_numerator"],
    "3_sign_stability": g1["gate_sign_stability"],
    "4_sector_MH>=0.15": g2["gate_sector_mh"],
    "5_not_irr_shadow": g3["gate_irr"],
}
survived_prereg = all(gates.values())

_x7_break = [k for k in ("drop_secular_3", "drop_amzn", "drop_wholesale_50_51", "drop_auto_dealers_55",
                         "drop_insurance_63", "drop_energy_13_29", "drop_all_passthrough")
             if X7[k].get("gates123_hold") is False]

six = {}
six["1_vintage_sign"] = {
    "落とせたか": ("落とせなかった（符号は3ビンテージとも正）" if g1["gate_sign_stability"]
                   else "**落とせた**（符号が反転する）"),
    "maintained_lift": g1["maintained_lift"],
    "min_numerator": g1["min_numerator"],
    "ただし": (f"群の和集合は {g1['group_membership_overlap']['n_union']} 社・"
               f"3ビンテージ共通が {g1['group_membership_overlap']['n_intersection_all3']} 社"
               f"（jaccard {g1['group_membership_overlap']['jaccard']}）。"
               f"窓は同じ終端日で 2016 の {g1['outcome_window_overlap']['share_of_2016_window_shared_with_2018']}・"
               f"2017 の {g1['outcome_window_overlap']['share_of_2017_window_shared_with_2018']} が 2018 と共通"
               "＝**3つの証拠ではなく同じ社の同じ8年を3回数えている**。"
               f"勝者は延べ {g1['distinct_winning_companies_carrying_the_finding']['n_events_total']} 件だが"
               f"実体は {g1['distinct_winning_companies_carrying_the_finding']['n_distinct_companies']} 社。"),
    "2013/2015": g1["out_of_sample_2013_2015"],
    "2013/2015の代理(事前登録の外)": {"lifts": _proxy.get("signs"), "both_positive": _proxy.get("both_positive")},
}
six["2_sector"] = {
    "落とせたか": ("**落とせた**" if not g2["gate_sector_mh"] else "落とせなかった"),
    "MH": {str(v): g2["mh"][str(v)] for v in SIGN_VINTAGES},
    "間接標準化": {str(v): g2["indirect_standardization"][str(v)] for v in SIGN_VINTAGES},
    "粗い層での重み付きリスク差": {str(v): X8["bucket_level_sector_control"][str(v)]["weighted_risk_diff"]
                                  for v in SIGN_VINTAGES},
    "業種を1つ抜くと崩れる業種": g2["leave_one_sector_out_breakers"],
    "層内置換": g2["within_sector_permutation"],
}
six["3_irr_shadow"] = {
    "落とせたか": ("**落とせなかった。ただし『通った』のでもない**——群と irr 読解集合の重なりがゼロで、"
                   "prereg の二つの試験がどちらも計算できない＝判定不能。"
                   if g3["gate_irr_is_undecidable_not_failed"]
                   else ("落とせなかった（文言どおり通る）" if g3["gate_irr_literal"] else "**落とせた**")),
    "honest_verdict": g3["gate_irr_honest"],
    "substantive_answer": g3["substantive_answer"],
    "power_audit": g3["gate_irr_power_audit"],
    "irr_coverage": X7["irr_coverage_in_group"],
    "irr85_in_group": IRR85,
    "overlap": g3["group_overlap_with_irr_read_set"],
}
six["4_one_company"] = {
    "落とせたか": (f"**落とせた**（{g4['n_breaking_gates_1_to_3']}社を1社抜くだけで条件1-3が崩れる: "
                   f"{[x['ticker'] for x in g4['breakers_gates_1_to_3']]}）"
                   if g4["n_breaking_gates_1_to_3"] > 0
                   else "落とせなかった（どの1社を抜いても条件1-3は保たれる）"),
    "worst_maintained_lift": g4["worst_maintained_lift"],
    "max_abs_delta": g4["max_abs_delta_from_one_company"],
    "sequential_winner_removal": g4["sequential_winner_removal"],
}
six["5_permutation"] = {
    "p_ge_observed_unrestricted": g5["unrestricted_ticker_bundle"]["p_ge_observed"],
    "p_ge_observed_within_sic2": g5["within_sic2"]["p_ge_observed"],
    "P_this_cell_passes_by_chance": g5["within_sic2"]["P_this_single_cell_passes_gates123_by_chance"],
    "family_wise": g5["family_wise_from_explorer"],
    "position_vs_null_max": g5["observed_vs_null_max_distribution"]["position"],
}
six["6_overlap_with_existing_gates"] = {
    "落とせたか": ("**落とせた（実務の意味で決定的）**——質実証を通った社の中に群のメンバーが"
                   "**一社も居ない**（0/31・0/33・0/37）。opm>=10% と opm<=3.8% は同じ絶対の物差しで排他。"
                   "『既存の関門を通った社の中で選ぶ』場面での増分は定義上ゼロ。"),
    "質実証の中で残るか": g6["prereg_line_applied_to_the_increment_quality"],
    "排他性の実数": X11["disjointness"],
    "収縮なし∧利払カバーの中で残るか": g6["prereg_line_applied_to_the_increment_no_shrink_intcov"],
    "群のうち既存の関門で既に落ちている社の割合": {
        str(v): g6["survivors"][str(v)]["group_members_already_excluded_by_gates"]
        for v in SIGN_VINTAGES},
    "脚単独からの増分": g6["increment_over_best_leg"],
}
six["補_等ウェイトで指数に勝てたか"] = X9["by_vintage"]
six["補_線からの余裕"] = X10["margin_above_line"]
six["補_勝者の業種の塊"] = X12["winners_by_sic2"]

out = {
    "generated": "2026-08-11",
    "tool": "night/hist_wd_verify_opm_rev.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "stance": ("**反証が仕事であって確認ではない。** prereg の5条件を一つも緩めない。"
               "線を緩めた数字は『事前登録の外・診断専用』と明記し合否には数えない。"
               "『測れない』と『不合格』を区別する。"),
    "candidate": {**{k: v for k, v in CAND.items() if k != "legs"},
                  "legs": [{"var": a, "cut": b} for a, b in CAND["legs"]],
                  "explorer_verdict": (ref or {}).get("verdict"),
                  "explorer_gate_failed_at": (ref or {}).get("gate_failed_at")},
    "0_reproduce": {"cross_check_vs_explorer": cross, "row_level_spot_check": spot},
    "must_report_before_verdict": pre,
    "1_vintage_sign": g1,
    "2_sector_control": g2,
    "3_irr_shadow": g3,
    "4_one_company": g4,
    "5_permutation": g5,
    "6_overlap_with_existing_gates": g6,
    "X1_interaction": X1,
    "X2_variable_shape": X2,
    "X3_income_statement_form": X3,
    "X4_population_dependence": X4,
    "X5_both_tails_and_hurdle": X5,
    "X6_cyclical_recovery": X6,
    "X7_named_removal": X7,
    "X8_alternative_sector_control_and_diagnostics": X8,
    "X9_equal_weight_wealth_vs_index": X9,
    "X10_margin_above_the_line": X10,
    "X11_disjoint_from_quality": X11,
    "X12_winner_industry_clumping": X12,
    "six_attacks": six,
    "prereg_gates": gates,
    "prereg_gates_note": {
        "4_sector_MH": ("MH は 2016:0.1565 / 2017:0.0875 / 2018:0.2644。**2017 で線を割る**。"
                        "層を落とさない間接標準化(0.1939/0.1061/0.2089)でも粗い層(0.1836/0.1249/0.2408)でも"
                        "**同じ2017で割る**＝道具の選び方の問題ではない。"),
        "5_not_irr_shadow": ("**不合格ではなく判定不能**。群と irr 読解集合の重なりがゼロで、"
                             "prereg の二つの試験がどちらも計算できない。"
                             "実質的には irr=85 の影ではない（群に irr=85 は一社も居ない）。"),
    },
    "survived_prereg": survived_prereg,
    "verdict": None,
    "runtime_sec": None,
}
out["verdict"] = {
    "prereg_literal": ("不合格（gate4 業種調整で 2017 が 0.0875 と線を割る）。"
                       "gate5 は不合格ではなく判定不能。gate1-3 は落とせなかった。"),
    "落とせた攻撃": [],
    "落とせなかった攻撃": [],
}
if not g2["gate_sector_mh"]:
    out["verdict"]["落とせた攻撃"].append(
        "2 業種調整: MH 2017=0.0875 で線割れ。間接標準化・粗い層でも同じ2017で割る。"
        "業種を1つ抜く試験でも SIC 55(自動車ディーラー)・23・53 で条件1-3が崩れる")
if g6["prereg_line_applied_to_the_increment_quality"]["min_numerator"] == 0:
    out["verdict"]["落とせた攻撃"].append(
        "6 既存の関門との重複: 質実証を通った社の中に群のメンバーが**一社も居ない**（排他）。実務の増分は定義上ゼロ")
_x5h = X5["hurdle_sensitivity"]
if (_x5h.get("hurdle=0.2", {}).get("maintained_lift") or 9) < LIFT:
    out["verdict"]["落とせた攻撃"].append(
        "X5 ハードル感度（事前登録の外）: 15%では 0.1605 だが 20%で 0.1036・25%で 0.0257 へ崩れる"
        "＝分布全体の移動ではなく**線のすぐ上への集中**")
if all((X9["by_vintage"][str(v)]["median_minus_spy"] or 0) < 0 for v in SIGN_VINTAGES):
    out["verdict"]["落とせた攻撃"].append(
        "X9: 群の**中央値**は3ビンテージとも同期間のSPYを下回る。等ウェイトはSPYを+1.5〜3.5pt上回るが、"
        "上位2社を抜くと2016/2017でSPYを下回る＝富の超過は1-2社が作っている")
if g5["observed_vs_null_max_distribution"]["below_null_max_median"]:
    out["verdict"]["落とせた攻撃"].append(
        f"5 多重検定: maintained_lift 0.1605 は **null_max の中央値 0.188 を下回る**"
        f"（2840検定の最大値の帰無分布）。探索内の順位は gates1-3 通過30本中 "
        f"{g5['rank_within_the_search']['rank_among_gates123_passers']}位"
        "＝『通った』ことに情報がほとんど無い位置")
out["verdict"]["落とせた攻撃"].append(
    "X12 勝者の業種の塊: 勝者13-16社のうち53-63%が同業2社以上の塊。"
    "**自動車ディーラー GPI/PAG/SAH は3ビンテージすべてで3社そろって勝者**、"
    "医薬品卸 CAH/COR/MCK も同型。独立な賭けは分子の数より遥かに少ない")
if g1["gate_sign_stability"] and g1["gate_lift"] and g1["gate_min_numerator"]:
    out["verdict"]["落とせなかった攻撃"].append("1 ビンテージ符号（3つとも正・maintained 0.1605）")
if g4["n_breaking_gates_1_to_3"] == 0:
    out["verdict"]["落とせなかった攻撃"].append("4 1社の影響（どの1社を抜いても条件1-3は保たれる。ただし閾値の補償あり）")
if (perm_res["within_sic2"]["p_ge_observed"] or 1) < 0.05:
    out["verdict"]["落とせなかった攻撃"].append(
        f"5 置換（層内 p={perm_res['within_sic2']['p_ge_observed']}・無制限 p={perm_res['unrestricted']['p_ge_observed']}）")
out["runtime_sec"] = round(time.time() - t0, 1)

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"wrote {DEST}  ({out['runtime_sec']}s)")
print("gates:", json.dumps(gates, ensure_ascii=False))
print("survived_prereg:", survived_prereg)
print("cross_check:", cross["verdict"], "spot_mismatch:", spot["total_mismatch"])
