#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_win_pair.py — 勝者側（目的A: P(tr_cagr >= +15%)）の**2本組合せ**探索。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル）
          out/hist_wd_win_uni.json（単変量の答え＝種の選定と、突合せの相手）
出力    : out/hist_wd_win_pair.json

────────────────────────────────────────────────────────────
この道具が測るもの
────────────────────────────────────────────────────────────
「単変量で lift が正の上位10本」を種にし、**全候補との2本積（AND）**を測る。
各変数は prereg の combos どおり **中央値 または 上下1/4** で二値化する。

合否は prereg の5条件すべて（この道具は一つも足さない・緩めない）:
  lift>=0.15 ∧ 分子>=5社 ∧ 2016/2017/2018で符号不変 ∧ 業種(sic2)調整後も残る ∧ irr>=70層内でも残る

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定（後から読む人へ）
────────────────────────────────────────────────────────────
1) **解析集合は has_outcome ∧ window_full**（単変量と同一）。短窓は年率換算で両裾を機械的に
   膨らませるため（パネルの診断: 2013 の DBD は 3.01年で tr_cagr 62.5%＝win 判定）。

2) **探索空間は「符号不変ゲートを当てられる21本」だけ**。co_(2013/2015のみ)・pa_(2018のみ)・
   hv_/per(2016/2017に無い) は**結果を見る前から構造的に判定不能**なので、2本積にしても
   判定できない。検定の数だけ増えて偽陽性率を上げるので入れない。
   ——これは「不合格」ではない。判定不能を不合格と書かないための除外である。

3) **P_moat は探索空間に入れない**。2016/2017 で母集団が空（irr の読解が存在しない）＝
   符号不変ゲートが構造的に当てられない。単変量では「判定不能」として出したが、
   2本積では検定数が数千に増えるため、判定できないセルを数千個作ることに意味がない。
   irr の影かどうかは**ゲート5(irr>=70層内)**が別に見る。

4) **種の直進性**: 種は「その母集団で 2016/2017/2018 の3ビンテージとも lift が正、
   かつ揃った上での最小 lift が大きい」順の上位10本。種の向き（高い側／低い側）は
   その最良の切り方が決める。種は**同じ向きの2通り（1/4側・中央値側）**で入れる
   ——prereg が「中央値または上下1/4」の両方を許しているので、片方だけ使う理由がない。

5) **相手は全候補×4通りの切り方**（上位1/4・下位1/4・中央値超・中央値以下）。
   相手の向きは事前に決められないので両方向を試す。**同じ変数どうしの組は作らない**
   （A高 ∧ A低 は空、A高 ∧ A中央値超 は入れ子＝新しい情報がない）。

6) **分位は各変数が自分の分布で切る**（母集団内・その変数を報告している行のみ・nearest-rank）。
   単変量とまったく同じ定義。AND の交差集合で切り直さない
   ——切り直すと「相手の欠測が閾値を動かす」ことになり、同じ変数が組ごとに違う意味になる。

7) **lift の分母は prereg の literal どおり母集団**。ただし2本積は**欠測が二重に効く**
   （実測: f2_sga_r の被覆58%）ので、両方が可測な部分集合を分母にした
   `lift_vs_measurable_both` を必ず併記し、二つが食い違うセルには印を付ける。
   食い違うとき、それは「2本の値が分けた」のではなく「2本を報告している社が違う」ことを見ている。

8) **2本積の本当の問いは『増分』**。組が効いて見えても、片方の脚が単独で同じだけ効いていれば
   組は何も足していない。各組に
   `lift_increment_vs_best_leg`（＝組の維持lift − 各脚単独の維持liftの最大）を必ず付ける。

9) **実装は単変量の道具と別**（群が「2条件のAND」になるので measure() をそのまま呼べない）。
   そこで**写したことを主張せず、測って証明する**——同じ道具で各脚を単独測定し、
   out/hist_wd_win_uni.json の cells と n_pop/k_pop/n_group/numerator/lift が
   1件も食い違わないことを毎回確認する（crosscheck.mismatches が 0 でなければ結論を書かない）。

10) **検定の数を先に数える**（多重検定の値札）。単変量は168検定で FPR 0.000 だったが、
    2本積はその十数倍になる。**同じ帰無（結果の束をティッカーごと置換）**で偽陽性率を測り直す。
"""
import json, os, sys, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
UNI = os.path.join(OUT, "hist_wd_win_uni.json")
DEST = os.path.join(OUT, "hist_wd_win_pair.json")

# ─── prereg の線（この道具は一つも作らない・読むだけ） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality"]          # 設計3: P_moat は探索空間外
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]
HIGH_SIDE = {"上位1/4", "中央値超"}
LOW_SIDE = {"下位1/4", "中央値以下"}
N_SEEDS = 10

SEED = 20260811
N_PERM = 2000
N_POWER = 4000

t0 = time.time()

# ────────────────────────────── 小道具（数学だけ・判定を含まない） ──────────────────────────────
def q_at(sorted_vals, q):
    """nearest-rank 分位（外挿しない・実在する値だけを閾値にする）。単変量と同一定義。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))
    return sorted_vals[k - 1]


def num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


def rate(k, n):
    return (k / n) if n else None


def r4(x):
    return None if x is None else round(x, 4)


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
    numr = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return numr / (dx * dy)


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
uni = json.load(open(UNI, encoding="utf-8"))

rows_all = panel["rows"]
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]

by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)

# (ticker, vintage) が一意であること（マスク＝ティッカー索引なので前提が要る）
for v in ALL_VINTAGES:
    tk = [r["ticker"] for r in by_v[v]]
    assert len(tk) == len(set(tk)), f"vintage {v} にティッカーの重複がある＝ビット索引が壊れる"


def pop_rows(v, pop):
    return [r for r in by_v[v] if r.get(pop) is True]


# 候補（単変量の道具が「符号不変ゲートを当てられる」と出した21本をそのまま使う）
CANDIDATES = list(uni["must_report_before_verdict"]["gate_reachable_variables"])
EXCLUDED = list(uni["must_report_before_verdict"]["gate_unreachable_variables"])

# ────────────────────────────── ビット索引（観測も置換も同じ経路を通す） ──────────────────────────────
tick_idx = {}
for v in ALL_VINTAGES:
    for r in by_v[v]:
        if r["ticker"] not in tick_idx:
            tick_idx[r["ticker"]] = len(tick_idx)
N_T = len(tick_idx)


def bits_to_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


A_bits, W_bits = {}, {}
for v in ALL_VINTAGES:
    a = [0] * N_T
    w = [0] * N_T
    for r in by_v[v]:
        i = tick_idx[r["ticker"]]
        a[i] = 1
        if r.get("win"):
            w[i] = 1
    A_bits[v], W_bits[v] = a, w
A0 = {v: bits_to_int(A_bits[v]) for v in ALL_VINTAGES}
W0 = {v: bits_to_int(W_bits[v]) for v in ALL_VINTAGES}

# 母集団マスク（特徴量側＝置換で動かさない）
POPMASK = {}
for v in ALL_VINTAGES:
    for pop in POPS:
        bits = [0] * N_T
        for r in pop_rows(v, pop):
            bits[tick_idx[r["ticker"]]] = 1
        POPMASK[(v, pop)] = bits_to_int(bits)

# 変数ごとの可測マスク・切り方マスク・閾値（設計6: 各変数は自分の分布で切る）
VARMASK = {}     # (v,pop,var) -> {"meas":int, "cuts":{name:int}, "q":(q25,q50,q75), "n_meas":int, "distinct":int}
for v in ALL_VINTAGES:
    for pop in POPS:
        R = pop_rows(v, pop)
        for var in CANDIDATES:
            entries = []
            for r in R:
                x = num(r.get(var))
                if x is not None:
                    entries.append((x, tick_idx[r["ticker"]]))
            if not entries:
                continue
            vals = sorted(x for x, _ in entries)
            q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
            mm = [0] * N_T
            cm = {c: [0] * N_T for c in CUTNAMES}
            preds = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                     "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}
            for x, i in entries:
                mm[i] = 1
                for c, p in preds.items():
                    if p(x):
                        cm[c][i] = 1
            VARMASK[(v, pop, var)] = {
                "meas": bits_to_int(mm),
                "cuts": {c: bits_to_int(cm[c]) for c in CUTNAMES},
                "q": (q25, q50, q75),
                "n_meas": len(entries),
                "distinct": len(set(vals)),
            }

# ────────── 探索空間に同じ列が二度入っていないか（測って確かめる・仮定しない） ──────────
# 同じ量が別名で二度入っていると (a)検定数が水増しされ (b)『別々の発見』が二重に見え
# (c)種の枠を一つ食う。パネルは名前空間を分けているが、**中身が同じかは測らないと判らない**。
dup_pairs = []
for i, va in enumerate(CANDIDATES):
    for vb in CANDIDATES[i + 1:]:
        same, both, diff = 0, 0, 0
        for v in SIGN_VINTAGES:
            for r in by_v[v]:
                a, b = num(r.get(va)), num(r.get(vb))
                if a is None and b is None:
                    continue
                both += 1
                if a == b:
                    same += 1
                else:
                    diff += 1
        if both and diff == 0:
            dup_pairs.append({"a": va, "b": vb, "rows_compared": both,
                              "identical_rows": same, "differing_rows": diff,
                              "note": "判定に使う3ビンテージで**完全に同一の列**"})
DUP_CANON = {}
for d in dup_pairs:
    DUP_CANON[d["b"]] = d["a"]


def canon(var):
    return DUP_CANON.get(var, var)


# ────────────────────────────── 突合せ（設計9: 写したと主張せず、測って証明する） ──────────────────────────────
def single_measure(v, pop, var, cut, Aint, Wint):
    e = VARMASK.get((v, pop, var))
    if not e:
        return None
    pm = POPMASK[(v, pop)]
    a, w = Aint[v], Wint[v]
    n_pop = (pm & a).bit_count()
    k_pop = (pm & w).bit_count()
    gm = e["cuts"][cut]
    n_g = (gm & a).bit_count()
    k_g = (gm & w).bit_count()
    n_m = (e["meas"] & a).bit_count()
    k_m = (e["meas"] & w).bit_count()
    p_pop = rate(k_pop, n_pop)
    return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": p_pop, "n_group": n_g, "k": k_g,
            "p_group": rate(k_g, n_g), "n_meas": n_m,
            "lift": (None if n_g == 0 else rate(k_g, n_g) - p_pop),
            "lift_meas": (None if n_g == 0 or n_m == 0 else rate(k_g, n_g) - rate(k_m, n_m))}


crosscheck = {"compared": 0, "mismatches": 0, "examples": []}
for var in CANDIDATES:
    for pop in POPS:
        for v in ALL_VINTAGES:
            ref = uni["cells"].get(f"{var}|{pop}|{v}")
            if not ref or ref.get("n_measurable", 0) == 0:
                continue
            mine_pop = single_measure(v, pop, var, "上位1/4", A0, W0)
            if mine_pop is None:
                continue
            for cut in CUTNAMES:
                m = single_measure(v, pop, var, cut, A0, W0)
                rc = ref["cuts"][cut]
                pairs = [("n_pop", m["n_pop"], ref["n_pop"]), ("k_pop", m["k_pop"], ref["k_pop"]),
                         ("n_measurable", m["n_meas"], ref["n_measurable"]),
                         ("n_group", m["n_group"], rc["n_group"]), ("numerator", m["k"], rc["numerator"]),
                         ("lift", r4(m["lift"]), rc["lift_vs_pop"])]
                for name, mine, theirs in pairs:
                    crosscheck["compared"] += 1
                    if mine != theirs:
                        crosscheck["mismatches"] += 1
                        if len(crosscheck["examples"]) < 12:
                            crosscheck["examples"].append(
                                {"cell": f"{var}|{pop}|{v}|{cut}", "field": name,
                                 "pair_tool": mine, "uni_tool": theirs})
crosscheck["verdict"] = ("一致（単変量の道具と同じ数字を出す＝群の作り方だけが違う）"
                         if crosscheck["mismatches"] == 0 else "⚠不一致——結論を書いてはいけない")

# ────────────────────────────── 種の選定（設計4） ──────────────────────────────
def maintained_lift(var, pop, cut):
    """2016/2017/2018 の3ビンテージとも符号が揃ったうえでの最小|lift|。揃わなければ None。"""
    s = uni["summaries"].get(f"{var}|{pop}")
    if not s:
        return None
    row = s["cuts"][cut]
    got = [row.get(str(v)) for v in SIGN_VINTAGES]
    if any(g is None or g.get("lift") is None for g in got):
        return None
    signs = {(1 if g["lift"] > 0 else (-1 if g["lift"] < 0 else 0)) for g in got}
    if len(signs) != 1 or 0 in signs:
        return None
    return {"sign": signs.pop(), "min_abs": min(abs(g["lift"]) for g in got),
            "lifts": [g["lift"] for g in got], "nums": [g["k"] for g in got]}


seeds = {}
seed_tables = {}
for pop in POPS:
    scored = []
    for var in CANDIDATES:
        best = None
        for cut in CUTNAMES:
            ml = maintained_lift(var, pop, cut)
            if not ml or ml["sign"] != 1:      # 「lift が正」＝勝率を上げる向き
                continue
            if best is None or ml["min_abs"] > best["min_abs"]:
                best = {"cut": cut, **ml}
        if best:
            scored.append({"variable": var, "best_cut": best["cut"],
                           "maintained_lift": r4(best["min_abs"]),
                           "lifts_161718": best["lifts"], "numerators_161718": best["nums"],
                           "side": ("high" if best["cut"] in HIGH_SIDE else "low")})
    scored.sort(key=lambda x: -x["maintained_lift"])
    seed_tables[pop] = {"n_variables_with_positive_stable_cut": len(scored), "ranked": scored}
    seeds[pop] = scored[:N_SEEDS]

# ────────────────────────────── 組の列挙（設計4/5/10: 数えてから測る） ──────────────────────────────
def side_cuts(side):
    return ["上位1/4", "中央値超"] if side == "high" else ["下位1/4", "中央値以下"]


pair_keys = {}          # pop -> [ (varA,cutA,varB,cutB) 正規化済み ]
enum_stats = {}
for pop in POPS:
    raw = 0
    seen = {}
    for s in seeds[pop]:
        for sc in side_cuts(s["side"]):
            for var2 in CANDIDATES:
                if var2 == s["variable"]:
                    continue
                for c2 in CUTNAMES:
                    raw += 1
                    a, b = (s["variable"], sc), (var2, c2)
                    key = tuple(sorted([a, b]))
                    if key not in seen:
                        seen[key] = (s["variable"], sc)    # どの種から来たか（先に見つけたほう）
    pair_keys[pop] = sorted(seen.keys())
    enum_stats[pop] = {
        "n_seeds": len(seeds[pop]),
        "seed_cuts_per_seed": 2,
        "n_partner_variables": len(CANDIDATES) - 1,
        "partner_cuts_per_partner": 4,
        "n_raw_combinations": raw,
        "n_after_dedup": len(seen),
        "dedup_note": "種どうしの組は2回列挙されるので正規化して1回にした",
    }

n_tests_total = sum(len(v) for v in pair_keys.values())

# ────────────────────────────── 中核: 1組の測定 ──────────────────────────────
def pair_masks(v, pop, key):
    (va, ca), (vb, cb) = key
    ea, eb = VARMASK.get((v, pop, va)), VARMASK.get((v, pop, vb))
    if not ea or not eb:
        return None
    return (ea["cuts"][ca] & eb["cuts"][cb], ea["meas"] & eb["meas"])


PAIRMASK = {}       # (pop, key) -> {v: (group_int, measboth_int)}
for pop in POPS:
    for key in pair_keys[pop]:
        d = {}
        for v in ALL_VINTAGES:
            m = pair_masks(v, pop, key)
            if m:
                d[v] = m
        PAIRMASK[(pop, key)] = d


def measure_pair(pop, key, v, Aint, Wint):
    d = PAIRMASK[(pop, key)]
    if v not in d:
        return None
    gm, mm = d[v]
    pm = POPMASK[(v, pop)]
    a, w = Aint[v], Wint[v]
    n_pop = (pm & a).bit_count()
    if n_pop == 0:
        return None
    k_pop = (pm & w).bit_count()
    p_pop = k_pop / n_pop
    n_g = (gm & a).bit_count()
    k_g = (gm & w).bit_count()
    n_m = (mm & a).bit_count()
    k_m = (mm & w).bit_count()
    return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": p_pop,
            "n_measurable_both": n_m, "p_measurable_both": rate(k_m, n_m),
            "n_group": n_g, "numerator": k_g, "p_group": rate(k_g, n_g),
            "lift": (None if n_g == 0 else k_g / n_g - p_pop),
            "lift_meas": (None if n_g == 0 or n_m == 0 else k_g / n_g - k_m / n_m)}


# ────────────────────────────── 到達可能性（結果を見る前に出す） ──────────────────────────────
# 群の大きさは組ごとに実現するので、母集団単位ではなく**組ごと**に数える。
def reach_of(pop, key):
    per_v = {}
    verdicts = []
    for v in SIGN_VINTAGES:
        m = measure_pair(pop, key, v, A0, W0)
        if not m:
            per_v[v] = {"verdict": "この母集団・ビンテージで測れない"}
            verdicts.append(False)
            continue
        n_g, base = m["n_group"], m["p_pop"]
        ev = m["k_pop"]
        if n_g == 0:
            per_v[v] = {"n_group": 0, "verdict": "群が空＝この切り方が成立しない"}
            verdicts.append(False)
            continue
        k_lift = math.ceil((base + LIFT) * n_g)
        need = max(k_lift, MIN_NUM)
        possible = need <= min(n_g, ev)
        per_v[v] = {"n_group": n_g, "base": r4(base), "k_needed_by_lift": k_lift,
                    "k_needed_by_min_num": MIN_NUM,
                    "binding": ("LIFT" if k_lift >= MIN_NUM else "MIN_NUM"),
                    "effective_lift_required": r4(need / n_g - base),
                    "possible": possible}
        verdicts.append(possible)
    return {"by_vintage": per_v, "all_possible": all(verdicts)}


reach_summary = {}
reach_cache = {}
for pop in POPS:
    binding_min_num = 0
    impossible = 0
    empty = 0
    eff_req = []
    gsz = []
    for key in pair_keys[pop]:
        rr = reach_of(pop, key)
        reach_cache[(pop, key)] = rr
        bv = rr["by_vintage"]
        if any(x.get("n_group", 0) == 0 for x in bv.values()):
            empty += 1
        if not rr["all_possible"]:
            impossible += 1
        for v in SIGN_VINTAGES:
            x = bv.get(v, {})
            if x.get("binding") == "MIN_NUM":
                binding_min_num += 1
            if x.get("effective_lift_required") is not None:
                eff_req.append(x["effective_lift_required"])
            if x.get("n_group") is not None:
                gsz.append(x["n_group"])
    gsz.sort()
    eff_req.sort()

    def pq(a, q):
        return a[min(len(a) - 1, max(0, int(q * len(a)) - 1))] if a else None

    reach_summary[pop] = {
        "n_pairs": len(pair_keys[pop]),
        "n_pairs_with_empty_group_somewhere": empty,
        "n_pairs_not_reachable": impossible,
        "n_pairs_reachable": len(pair_keys[pop]) - impossible,
        "cell_vintages_where_MIN_NUM_binds": binding_min_num,
        "cell_vintages_total": len(gsz),
        "group_size_percentiles": {"p10": pq(gsz, 0.10), "p25": pq(gsz, 0.25), "p50": pq(gsz, 0.50),
                                   "p75": pq(gsz, 0.75), "p90": pq(gsz, 0.90),
                                   "min": (gsz[0] if gsz else None), "max": (gsz[-1] if gsz else None)},
        "effective_lift_required_percentiles": {"p50": pq(eff_req, 0.50), "p90": pq(eff_req, 0.90),
                                                "p99": pq(eff_req, 0.99),
                                                "max": (eff_req[-1] if eff_req else None)},
    }
reach_summary["_how_to_read"] = (
    "2本積は群が n/16 前後まで縮むので、**MIN_NUM(5社) が LIFT(0.15) より強く縛る組が出る**"
    "（v2の教訓: 線は0.15と書いてあるのに実効的にはもっと高い線が課される）。"
    "その組で『不合格』と出ても、それは 0.15 を割ったのではなく 5社に届かなかったのかもしれない。"
    "effective_lift_required がその実効の線。")

# ────────────────────────────── ゲート4: 業種(sic2)調整 ──────────────────────────────
def mh_risk_diff_pair(v, pop, key):
    d = PAIRMASK[(pop, key)]
    if v not in d:
        return None
    gm, _ = d[v]
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for r in pop_rows(v, pop):
        s = r.get("sic2")
        if not s:
            continue
        i = tick_idx[r["ticker"]]
        ing = (gm >> (N_T - 1 - i)) & 1
        w = 1 if r.get("win") else 0
        dd = strata[s]
        if ing:
            dd[0] += 1; dd[1] += w
        else:
            dd[2] += 1; dd[3] += w
    numr, den, used, drop = 0.0, 0.0, 0, 0
    for s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        wgt = n1 * n0 / (n1 + n0)
        numr += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(numr / den), "strata_used": used, "strata_dropped": drop}


# ────────────────────────────── ゲート5: irr の影でないか ──────────────────────────────
def irr_control_pair(v, pop, key):
    d = PAIRMASK[(pop, key)]
    if v not in d:
        return {"status": "このビンテージで測れない"}
    gm, mm = d[v]
    R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
    if len(R) < 20:
        return {"status": f"irr の読解がこのビンテージ・母集団で {len(R)} 行しかなく判定不能"}
    hi = [r for r in R if r["irr"] >= 70]
    res = {"n_with_irr": len(R), "n_irr_ge70": len(hi)}
    # 群に入るかどうかと irr の相関（直交ヒント）
    xs, ys = [], []
    for r in R:
        i = tick_idx[r["ticker"]]
        if (mm >> (N_T - 1 - i)) & 1:
            xs.append(float((gm >> (N_T - 1 - i)) & 1))
            ys.append(float(r["irr"]))
    rho = spearman(xs, ys) if len(xs) >= 20 else None
    res["corr_group_vs_irr"] = r4(rho)
    res["orthogonal_hint"] = (None if rho is None else abs(rho) < 0.15)
    if len(hi) >= 20:
        base = rate(sum(1 for r in hi if r.get("win")), len(hi))
        g = [r for r in hi if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
        kg = sum(1 for r in g if r.get("win"))
        res["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g), "k": kg,
                           "p_group": r4(rate(kg, len(g))),
                           "lift": r4(None if not g else rate(kg, len(g)) - base)}
    else:
        res["irr_ge70"] = {"status": f"irr>=70 が {len(hi)} 行で判定不能（分子5に届かない）"}
    return res


# ────────────────────────────── 全組を測る ──────────────────────────────
CIRC_QUALITY = {"f2_fcfpos5": "この母集団の定義そのもの（fcfpos5==5 で定数化・lift は構造的に0）",
                "f2_opm": "この母集団の定義に使われている（opm>=10% で下側が切り落とされている）"}

results = []
for pop in POPS:
    for key in pair_keys[pop]:
        (va, ca), (vb, cb) = key
        per_v = {}
        for v in ALL_VINTAGES:
            per_v[v] = measure_pair(pop, key, v, A0, W0)
        got3 = [per_v[v] for v in SIGN_VINTAGES if per_v.get(v) and per_v[v]["lift"] is not None]
        n_empty3 = sum(1 for v in SIGN_VINTAGES
                       if per_v.get(v) and per_v[v]["lift"] is None)
        ent = {
            "population": pop, "var_a": va, "cut_a": ca, "var_b": vb, "cut_b": cb,
            "label": f"{va}[{ca}] ∧ {vb}[{cb}]",
            "by_vintage": {str(v): (None if not per_v.get(v) else {
                "n_pop": per_v[v]["n_pop"], "p_base": r4(per_v[v]["p_pop"]),
                "n_group": per_v[v]["n_group"], "numerator": per_v[v]["numerator"],
                "p_group": r4(per_v[v]["p_group"]), "lift": r4(per_v[v]["lift"]),
                "lift_meas": r4(per_v[v]["lift_meas"]),
                "n_measurable_both": per_v[v]["n_measurable_both"],
            }) for v in ALL_VINTAGES},
        }
        if len(got3) == 3:
            lifts = [m["lift"] for m in got3]
            signs = {(1 if l > 0 else (-1 if l < 0 else 0)) for l in lifts}
            ent["sign_stable_161718"] = (len(signs) == 1 and 0 not in signs)
            ent["maintained_lift"] = r4(min(abs(l) for l in lifts)) if ent["sign_stable_161718"] else 0.0
            ent["sign"] = (1 if lifts[-1] > 0 else -1)
            ent["min_numerator_161718"] = min(m["numerator"] for m in got3)
            lm = [m["lift_meas"] for m in got3 if m["lift_meas"] is not None]
            ent["maintained_lift_meas"] = (r4(min(abs(x) for x in lm))
                                           if len(lm) == 3 and len({1 if x > 0 else -1 for x in lm}) == 1
                                           else 0.0)
            cov = [m["n_measurable_both"] / m["n_pop"] for m in got3 if m["n_pop"]]
            ent["coverage_both_min"] = r4(min(cov)) if cov else None
        else:
            ent["sign_stable_161718"] = None
            ent["maintained_lift"] = None
            ent["maintained_lift_meas"] = None
            ent["min_numerator_161718"] = None
            ent["empty_group_vintages"] = n_empty3
        results.append(ent)

# 各脚の単独維持lift（設計8: 増分）
leg_cache = {}
def leg_maintained(pop, var, cut):
    k = (pop, var, cut)
    if k in leg_cache:
        return leg_cache[k]
    ml = maintained_lift(var, pop, cut)
    val = (ml["min_abs"] * ml["sign"]) if ml else 0.0
    leg_cache[k] = val
    return val


for ent in results:
    la = leg_maintained(ent["population"], ent["var_a"], ent["cut_a"])
    lb = leg_maintained(ent["population"], ent["var_b"], ent["cut_b"])
    ent["leg_maintained_lift_a"] = r4(la)
    ent["leg_maintained_lift_b"] = r4(lb)
    best_leg = max(la, lb)          # 勝者側なので正の維持liftの大きいほう
    ent["best_leg_maintained_lift"] = r4(best_leg)
    if ent.get("maintained_lift") is not None and ent.get("sign") == 1:
        ent["lift_increment_vs_best_leg"] = r4(ent["maintained_lift"] - best_leg)
    else:
        ent["lift_increment_vs_best_leg"] = None

# ────────────────────────────── 判定（prereg の5条件・単変量とまったく同じ順序） ──────────────────────────────
def verdict_of(ent):
    pop = ent["population"]
    if pop == "P_quality":
        for var in (ent["var_a"], ent["var_b"]):
            if var in CIRC_QUALITY:
                return {"verdict": "判定不能", "reason": f"母集団の定義に使われている変数を含む＝{CIRC_QUALITY[var]}",
                        "gate_failed_at": "circularity"}
    if ent.get("sign_stable_161718") is None:
        return {"verdict": "判定不能",
                "reason": f"この切り方で群が空になるビンテージがある（{ent.get('empty_group_vintages')}件）",
                "gate_failed_at": "empty_group"}
    rr = reach_cache[(pop, ((ent["var_a"], ent["cut_a"]), (ent["var_b"], ent["cut_b"])))]
    if not rr["all_possible"]:
        bad = [v for v in SIGN_VINTAGES if not rr["by_vintage"].get(v, {}).get("possible")]
        return {"verdict": "判定不能",
                "reason": f"群が小さく lift0.15∧分子5 が算術的に成立しないビンテージがある: {bad}",
                "gate_failed_at": "reachability"}
    if ent["min_numerator_161718"] < MIN_NUM:
        return {"verdict": "不合格", "reason": f"分子>=5社 を満たさないビンテージがある（最小 {ent['min_numerator_161718']}）",
                "gate_failed_at": "min_numerator"}
    if not ent["sign_stable_161718"]:
        return {"verdict": "不合格", "reason": "2016/2017/2018 で符号が反転する", "gate_failed_at": "sign_stability"}
    if ent["maintained_lift"] < LIFT:
        return {"verdict": "不合格", "reason": f"|lift|>=0.15 を3ビンテージで維持できない（最小 {ent['maintained_lift']}）",
                "gate_failed_at": "lift"}
    key = ((ent["var_a"], ent["cut_a"]), (ent["var_b"], ent["cut_b"]))
    mh = {str(v): mh_risk_diff_pair(v, pop, key) for v in SIGN_VINTAGES}
    if not all(m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT for m in mh.values()):
        return {"verdict": "不合格", "reason": "同一 sic2 内（MH重み付きリスク差）で 0.15 を維持できない",
                "gate_failed_at": "sector_control", "mh": mh}
    ic = irr_control_pair(2018, pop, key)
    if ic.get("irr_ge70", {}).get("lift") is None and not ic.get("orthogonal_hint"):
        return {"verdict": "判定不能", "reason": "irr>=70 層が薄く層内検定ができず、かつ irr と直交とも言えない",
                "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic}
    ok = (ic.get("orthogonal_hint") is True
          or (ic.get("irr_ge70", {}).get("lift") is not None and abs(ic["irr_ge70"]["lift"]) >= LIFT))
    if not ok:
        return {"verdict": "不合格", "reason": "irr>=70 層内で差が消え、かつ irr と直交でもない＝irr の影",
                "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic}
    return {"verdict": "合格", "reason": "prereg の5条件すべてを満たす", "mh": mh, "irr": ic}


for ent in results:
    ent["verdict_full"] = verdict_of(ent)
    ent["verdict"] = ent["verdict_full"]["verdict"]

vcount = Counter(e["verdict"] for e in results)
fail_hist = Counter(e["verdict_full"].get("gate_failed_at") for e in results if e["verdict"] == "不合格")
und_hist = Counter(e["verdict_full"].get("gate_failed_at") for e in results if e["verdict"] == "判定不能")

# ────────────────────────────── 検出力（結果の前に出す・実現した群の大きさで） ──────────────────────────────
rnd = random.Random(SEED)


def binom(n, p):
    return sum(1 for _ in range(n) if rnd.random() < p)


def power_sim(n_pop, g, base, true_lift, n_sims=N_POWER):
    rest = n_pop - g
    if rest <= 0:
        return None
    p_g = min(0.999, max(0.001, base + true_lift))
    p_r = min(0.999, max(0.001, (base * n_pop - p_g * g) / rest))
    single = triple = 0
    for _ in range(n_sims):
        ok = []
        for _v in range(3):
            kg = binom(g, p_g)
            kr = binom(rest, p_r)
            b = (kg + kr) / n_pop
            lift = kg / g - b
            ok.append((abs(lift) >= LIFT and kg >= MIN_NUM, 1 if lift > 0 else -1))
        if ok[0][0]:
            single += 1
        if all(o[0] for o in ok) and len({o[1] for o in ok}) == 1:
            triple += 1
    return {"single_vintage": r4(single / n_sims), "three_independent": r4(triple / n_sims)}


power = {}
for pop in POPS:
    gp = reach_summary[pop]["group_size_percentiles"]
    n_ref = len(pop_rows(2018, pop))
    base_ref = rate(sum(1 for r in pop_rows(2018, pop) if r.get("win")), n_ref)
    power[pop] = {"n_pop_2018": n_ref, "base_2018": r4(base_ref),
                  "at_group_sizes": {}}
    for lbl in ("p25", "p50", "p75"):
        g = gp[lbl]
        if not g:
            continue
        power[pop]["at_group_sizes"][f"{lbl}(n_group={g})"] = {
            str(L): power_sim(n_ref, g, base_ref, L) for L in (0.15, 0.20, 0.30)}
power["_how_to_read"] = (
    "単変量は群が n/4 だったが、2本積は n/16 前後まで縮む＝**同じ真の効果でも掴む確率が落ちる**。"
    "three_independent が下限・single_vintage が上限（3ビンテージが完全に同じ実現なら1回引ければ3回引ける）。"
    "実際の outcome の Spearman は 0.845〜0.961 なので真の検出力はこの間。")

# ────────────────────────────── 偽陽性率（多重検定の値札・実データの相関を保った置換） ──────────────────────────────
FLAT = []      # (pop, key, [(gm,mm) x3])
for pop in POPS:
    for key in pair_keys[pop]:
        d = PAIRMASK[(pop, key)]
        if all(v in d for v in SIGN_VINTAGES):
            FLAT.append((pop, key, [d[v] for v in SIGN_VINTAGES]))

POPM3 = {pop: [POPMASK[(v, pop)] for v in SIGN_VINTAGES] for pop in POPS}

# 業種(sic2)の層マスク — 特徴量側なので置換で動かない
STRATA = {}
for v in SIGN_VINTAGES:
    for pop in POPS:
        d = defaultdict(lambda: [0] * N_T)
        for r in pop_rows(v, pop):
            s = r.get("sic2")
            if s:
                d[s][tick_idx[r["ticker"]]] = 1
        STRATA[(v, pop)] = [bits_to_int(b) for b in d.values()]

# irr>=70 の層マスク（2018のみ・特徴量側）
IRR70 = {}
for pop in POPS:
    bits = [0] * N_T
    for r in pop_rows(2018, pop):
        if r.get("irr") is not None and r["irr"] >= 70:
            bits[tick_idx[r["ticker"]]] = 1
    IRR70[pop] = bits_to_int(bits)

# 直交ヒント（群に入るかどうかと irr の相関）は**結果ラベルに依らない**＝置換で不変。先に計算する。
ORTHO = {}
for (pop, key, masks) in FLAT:
    gm, mm = PAIRMASK[(pop, key)].get(2018, (0, 0))
    xs, ys = [], []
    for r in pop_rows(2018, pop):
        if r.get("irr") is None:
            continue
        i = tick_idx[r["ticker"]]
        if (mm >> (N_T - 1 - i)) & 1:
            xs.append(float((gm >> (N_T - 1 - i)) & 1))
            ys.append(float(r["irr"]))
    rho = spearman(xs, ys) if len(xs) >= 20 else None
    ORTHO[(pop, key)] = (None if rho is None else abs(rho) < LIFT)


def mh_from_masks(gm, pm, strata, a, w):
    """MH重み付きリスク差（置換後のラベルでも回せるビット版）。mh_risk_diff_pair と同じ規則。"""
    numr = den = 0.0
    for sm in strata:
        g1 = gm & sm & a
        n1 = g1.bit_count()
        allsm = pm & sm & a
        n0 = allsm.bit_count() - n1
        if n1 < 3 or n0 < 3:
            continue
        k1 = (g1 & w).bit_count()
        k0 = (allsm & w).bit_count() - k1
        wgt = n1 * n0 / (n1 + n0)
        numr += wgt * (k1 / n1 - k0 / n0)
        den += wgt
    return (numr / den) if den else None


def run_procedure(Aint, Wint, thresh=LIFT, base="pop", levels=False):
    """置換後の outcome で prereg のゲートを順に当て、各段を通る組の数を返す。

    L3 = lift>=0.15 ∧ 分子>=5 ∧ 3ビンテージ符号不変（＝安いゲート1-3）
    L4 = L3 + 同一sic2内(MH)でも|差|>=0.15
    L5 = L4 + irr>=70層内でも残る or irr と直交（＝観測側の『合格』と同じ5条件）
    統計量 = 符号が揃ったうえでの3ビンテージ最小|lift|の、全検定中の最大。
    """
    A3 = [Aint[v] for v in SIGN_VINTAGES]
    W3 = [Wint[v] for v in SIGN_VINTAGES]
    popbase = {}
    for pop in POPS:
        arr = []
        for i in range(3):
            pm = POPM3[pop][i]
            npop = (pm & A3[i]).bit_count()
            kpop = (pm & W3[i]).bit_count()
            arr.append(kpop / npop if npop else None)
        popbase[pop] = arr
    hits3 = []
    best = 0.0
    for (pop, key, masks) in FLAT:
        ok = True
        signs = set()
        mn = 1e9
        for i in range(3):
            gm, mm = masks[i]
            a, w = A3[i], W3[i]
            ng = (gm & a).bit_count()
            if ng == 0:
                ok = False
                break
            kg = (gm & w).bit_count()
            if kg < MIN_NUM:
                ok = False
                break
            if base == "pop":
                b = popbase[pop][i]
            else:
                nm = (mm & a).bit_count()
                if nm == 0:
                    ok = False
                    break
                b = (mm & w).bit_count() / nm
            if b is None:
                ok = False
                break
            lift = kg / ng - b
            signs.add(1 if lift > 0 else -1)
            if len(signs) > 1:
                ok = False
                break
            av = abs(lift)
            if av < mn:
                mn = av
        if ok and len(signs) == 1:
            if mn > best:
                best = mn
            if mn >= thresh:
                hits3.append((pop, key, masks))
    if not levels:
        return len(hits3), best
    # ── L4: 業種調整（通った組だけに当てる＝費用は通過数に比例） ──
    hits4 = []
    for (pop, key, masks) in hits3:
        good = True
        for i, v in enumerate(SIGN_VINTAGES):
            gm, _ = masks[i]
            d = mh_from_masks(gm, POPM3[pop][i], STRATA[(v, pop)], A3[i], W3[i])
            if d is None or abs(d) < LIFT:
                good = False
                break
        if good:
            hits4.append((pop, key, masks))
    # ── L5: irr の影でないか ──
    hits5 = 0
    for (pop, key, masks) in hits4:
        if ORTHO.get((pop, key)) is True:
            hits5 += 1
            continue
        gm = PAIRMASK[(pop, key)][2018][0]
        hi = IRR70[pop]
        a, w = Aint[2018], Wint[2018]
        nh = (hi & a).bit_count()
        if nh < 20:
            continue                      # 判定不能＝合格に数えない（観測側と同じ扱い）
        bh = (hi & w).bit_count() / nh
        gh = gm & hi & a
        ng = gh.bit_count()
        if ng == 0:
            continue
        if abs((gh & w).bit_count() / ng - bh) >= LIFT:
            hits5 += 1
    return len(hits3), best, len(hits4), hits5


def perm_int(bits, sigma):
    return int("".join("1" if bits[sigma[j]] else "0" for j in range(N_T)), 2)


# ── 第三の帰無: **業種の中だけで並べ替える** ──────────────────────────────
# 上の二つはティッカーを自由に入れ替えるので、**業種が揃って勝った/負けたという構造そのものを壊す**。
# 2016-2026 は半導体資本財に極端に有利な窓だと台帳が既に記録しており、
# 「群が半導体の形をしている」だけで lift が出ているなら、それは指標の発見ではない。
# sic2 の中だけで結果を入れ替えれば『業種で説明できる分』は帰無にも残る＝
# **業種を超えて分けているか**だけを問える。（MHは層の92%を落とすので、この帰無のほうが強い）
sic_of = {}
sic_conflict = 0
for r in ANA:
    i = tick_idx[r["ticker"]]
    s = r.get("sic2") or "_none"
    if i in sic_of and sic_of[i] != s:
        sic_conflict += 1
    sic_of[i] = s
SIC_GROUPS = defaultdict(list)
for i in range(N_T):
    SIC_GROUPS[sic_of.get(i, "_none")].append(i)
SIC_GROUPS = [g for g in SIC_GROUPS.values()]


def shuffle_within_sector(sigma):
    for g in SIC_GROUPS:
        p = g[:]
        rnd.shuffle(p)
        for j, idx in enumerate(g):
            sigma[idx] = p[j]
    return sigma


# ── 第二の帰無: **種の選定そのものを毎回やり直す** ──────────────────────────────
# 上の帰無は「実データで選んだ10本」を固定したまま結果だけ壊す＝**選抜の代金を払っていない**。
# 実際の手続きは『同じ結果を見て種を選び、その種で組を作った』ので、
# 帰無でも毎回 種を選び直さないと偽陽性率を過小に見積もる。
ALLPAIR = {}
for pop in POPS:
    for i, va in enumerate(CANDIDATES):
        for vb in CANDIDATES[i + 1:]:
            for ca in CUTNAMES:
                for cb in CUTNAMES:
                    key = tuple(sorted([(va, ca), (vb, cb)]))
                    if key in ALLPAIR.get(pop, {}):
                        continue
                    d = {}
                    for v in SIGN_VINTAGES:
                        m = pair_masks(v, pop, key)
                        if m:
                            d[v] = m
                    if len(d) == 3:
                        ALLPAIR.setdefault(pop, {})[key] = [d[v] for v in SIGN_VINTAGES]
N_PAIR_SPACE = {pop: len(ALLPAIR.get(pop, {})) for pop in POPS}


def uni_maintained(pop, var, cut, A3, W3, popbase):
    """置換後ラベルでの単変量の維持lift（符号が揃ったうえでの最小lift・符号つき）。"""
    signs, mn = set(), 1e9
    for i, v in enumerate(SIGN_VINTAGES):
        e = VARMASK.get((v, pop, var))
        if not e:
            return None
        gm = e["cuts"][cut]
        ng = (gm & A3[i]).bit_count()
        if ng == 0:
            return None
        lift = (gm & W3[i]).bit_count() / ng - popbase[pop][i]
        signs.add(1 if lift > 0 else -1)
        if len(signs) > 1:
            return None
        mn = min(mn, abs(lift))
    return (mn, signs.pop())


def run_reselect(Aint, Wint, thresh=LIFT):
    """種の選定からやり直す帰無。返り値は (L3通過数, 最大統計量, 検定数)。"""
    A3 = [Aint[v] for v in SIGN_VINTAGES]
    W3 = [Wint[v] for v in SIGN_VINTAGES]
    popbase = {}
    for pop in POPS:
        arr = []
        for i in range(3):
            pm = POPM3[pop][i]
            npop = (pm & A3[i]).bit_count()
            arr.append(((pm & W3[i]).bit_count() / npop) if npop else 0.0)
        popbase[pop] = arr
    hits, best, ntests = 0, 0.0, 0
    for pop in POPS:
        scored = []
        for var in CANDIDATES:
            bb = None
            for cut in CUTNAMES:
                r = uni_maintained(pop, var, cut, A3, W3, popbase)
                if not r or r[1] != 1:
                    continue
                if bb is None or r[0] > bb[0]:
                    bb = (r[0], cut)
            if bb:
                scored.append((bb[0], var, bb[1]))
        scored.sort(reverse=True)
        seen = set()
        for _s, var, cut in scored[:N_SEEDS]:
            side = "high" if cut in HIGH_SIDE else "low"
            for sc in side_cuts(side):
                for var2 in CANDIDATES:
                    if var2 == var:
                        continue
                    for c2 in CUTNAMES:
                        key = tuple(sorted([(var, sc), (var2, c2)]))
                        if key in seen:
                            continue
                        seen.add(key)
                        masks = ALLPAIR.get(pop, {}).get(key)
                        if not masks:
                            continue
                        ntests += 1
                        ok, signs, mn = True, set(), 1e9
                        for i in range(3):
                            gm, _mm = masks[i]
                            ng = (gm & A3[i]).bit_count()
                            if ng == 0:
                                ok = False
                                break
                            kg = (gm & W3[i]).bit_count()
                            if kg < MIN_NUM:
                                ok = False
                                break
                            lift = kg / ng - popbase[pop][i]
                            signs.add(1 if lift > 0 else -1)
                            if len(signs) > 1:
                                ok = False
                                break
                            mn = min(mn, abs(lift))
                        if ok and len(signs) == 1:
                            best = max(best, mn)
                            if mn >= thresh:
                                hits += 1
    return hits, best, ntests


obs3, obs_max, obs4, obs5 = run_procedure(A0, W0, levels=True)
obs_hits_m, obs_max_m = run_procedure(A0, W0, base="meas")

RELAX = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20]
perm_hits, perm_max, perm_max_m, perm_h4, perm_h5 = [], [], [], [], []
rs_hits, rs_max, rs_ntests = [], [], []
ws_hits, ws_max, wr_hits, wr_max = [], [], [], []
relax_any = {t: 0 for t in RELAX}
sigma = list(range(N_T))
for it in range(N_PERM):
    rnd.shuffle(sigma)
    Ai = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Wi = {v: perm_int(W_bits[v], sigma) for v in SIGN_VINTAGES}
    h3, mx, h4, h5 = run_procedure(Ai, Wi, levels=True)
    perm_hits.append(h3)
    perm_h4.append(h4)
    perm_h5.append(h5)
    perm_max.append(mx)
    for t in RELAX:
        if mx >= t:
            relax_any[t] += 1
    _h2, mx2 = run_procedure(Ai, Wi, base="meas")
    perm_max_m.append(mx2)
    rh, rmx, rn = run_reselect(Ai, Wi)
    rs_hits.append(rh)
    rs_max.append(rmx)
    rs_ntests.append(rn)
    # 業種内だけで入れ替えた帰無（業種が揃って勝った構造を保つ）
    shuffle_within_sector(sigma)
    Aw = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Ww = {v: perm_int(W_bits[v], sigma) for v in SIGN_VINTAGES}
    wh, wmx, _w4, _w5 = run_procedure(Aw, Ww, levels=True)
    ws_hits.append(wh)
    ws_max.append(wmx)
    wr_h, wr_mx, _wn = run_reselect(Aw, Ww)
    wr_hits.append(wr_h)
    wr_max.append(wr_mx)

srt = sorted(perm_max)


def pctl(a, p):
    return r4(a[min(len(a) - 1, max(0, int(p * len(a)) - 1))]) if a else None


fpr = {
    "n_permutations": N_PERM,
    "n_tests_in_procedure": len(FLAT),
    "n_tests_univariate_for_comparison": uni["must_report_before_verdict"]["false_positive_rate"]["n_tests_in_procedure"],
    "multiple_testing_bill": r4(len(FLAT) / uni["must_report_before_verdict"]["false_positive_rate"]["n_tests_in_procedure"]),
    "null_construction": ("特徴量側（母集団・可測・群）は固定し、outcome の束(has_outcome∧window_full, win)を"
                          "ティッカーごとまとめて置換する。ビンテージ間の outcome 相関・欠測構造・"
                          "P_quality の定義を保ったまま、特徴量↔outcome だけを壊せる。単変量と同一の帰無。"),
    "levels": {"L3": "lift>=0.15 ∧ 分子>=5 ∧ 3ビンテージ符号不変",
               "L4": "L3 + 同一sic2内(MH)でも|差|>=0.15",
               "L5": "L4 + irr>=70層内でも残る or irr と直交（＝観測側の『合格』と同じ5条件）"},
    "P_at_least_one_pass": r4(sum(1 for h in perm_hits if h > 0) / N_PERM),
    "P_at_least_one_pass_by_level": {
        "L3": r4(sum(1 for h in perm_hits if h > 0) / N_PERM),
        "L4": r4(sum(1 for h in perm_h4 if h > 0) / N_PERM),
        "L5": r4(sum(1 for h in perm_h5 if h > 0) / N_PERM),
    },
    "mean_passes_per_permutation": r4(sum(perm_hits) / N_PERM),
    "mean_passes_per_permutation_by_level": {
        "L3": r4(sum(perm_hits) / N_PERM), "L4": r4(sum(perm_h4) / N_PERM),
        "L5": r4(sum(perm_h5) / N_PERM)},
    "max_passes_in_a_permutation": max(perm_hits),
    "max_passes_in_a_permutation_by_level": {"L3": max(perm_hits), "L4": max(perm_h4), "L5": max(perm_h5)},
    "observed_passes_by_level": {"L3": obs3, "L4": obs4, "L5": obs5},
    "empirical_p_of_observed_pass_count": {
        "L3": r4(sum(1 for h in perm_hits if h >= obs3) / N_PERM),
        "L4": r4(sum(1 for h in perm_h4 if h >= obs4) / N_PERM),
        "L5": r4(sum(1 for h in perm_h5 if h >= obs5) / N_PERM),
    },
    "observed_passes_gates123": obs3,
    "null_distribution_of_max_statistic": {
        "statistic": f"{len(FLAT)}検定のうち最大の『符号が揃ったうえでの3ビンテージ最小|lift|』",
        "p50": pctl(srt, 0.50), "p90": pctl(srt, 0.90), "p95": pctl(srt, 0.95), "p99": pctl(srt, 0.99),
        "max_over_permutations": r4(max(perm_max)),
        "observed_in_real_data": r4(obs_max),
        "empirical_p_of_observed": r4(sum(1 for m in perm_max if m >= obs_max) / N_PERM),
    },
    "fpr_at_relaxed_thresholds": {
        "note": "**事前登録の外・診断専用**。合否には数えない。線を緩めたときの偽陽性率。",
        "P_at_least_one_pass_by_threshold": {str(t): r4(relax_any[t] / N_PERM) for t in RELAX},
    },
    "null_with_seed_reselection": {
        "note": ("**こちらが正しい帰無**。上の帰無は『実データで選んだ10本の種』を固定したまま結果だけ壊すので、"
                 "**種を選ぶ段の選抜代を払っていない**。実際の手続きは同じ結果を見て種を選んでいるので、"
                 "帰無でも毎回選び直す。二つの差が『事前スクリーンがどれだけ偽陽性を押し上げるか』そのもの。"),
        "pair_space_available": N_PAIR_SPACE,
        "mean_tests_per_permutation": r4(sum(rs_ntests) / N_PERM),
        "P_at_least_one_pass_L3": r4(sum(1 for h in rs_hits if h > 0) / N_PERM),
        "mean_passes_per_permutation_L3": r4(sum(rs_hits) / N_PERM),
        "max_passes_in_a_permutation_L3": max(rs_hits),
        "null_max_statistic": {"p50": pctl(sorted(rs_max), 0.50), "p90": pctl(sorted(rs_max), 0.90),
                               "p95": pctl(sorted(rs_max), 0.95), "p99": pctl(sorted(rs_max), 0.99),
                               "max": r4(max(rs_max)),
                               "observed_in_real_data": r4(obs_max),
                               "empirical_p_of_observed": r4(sum(1 for m in rs_max if m >= obs_max) / N_PERM)},
        "empirical_p_of_observed_pass_count_L3": r4(sum(1 for h in rs_hits if h >= obs3) / N_PERM),
    },
    "null_within_sector": {
        "note": ("**業種の中だけで結果を入れ替えた帰無**。2016-2026 は半導体資本財に極端に有利な窓だと"
                 "台帳が既に記録しているので、『群が半導体の形をしている』だけで lift が出ていないかを問う。"
                 "業種で説明できる分は帰無にも残るため、ここを超えて初めて『指標が分けた』と言える。"
                 "MH は層の9割を落とすので、この帰無のほうが強い検査になる。"),
        "n_sector_groups": len(SIC_GROUPS),
        "ticker_sic_conflicts": sic_conflict,
        "fixed_seeds": {
            "P_at_least_one_pass_L3": r4(sum(1 for h in ws_hits if h > 0) / N_PERM),
            "mean_passes_per_permutation_L3": r4(sum(ws_hits) / N_PERM),
            "max_passes_in_a_permutation_L3": max(ws_hits),
            "null_max_statistic": {"p50": pctl(sorted(ws_max), 0.50), "p90": pctl(sorted(ws_max), 0.90),
                                   "p95": pctl(sorted(ws_max), 0.95), "p99": pctl(sorted(ws_max), 0.99),
                                   "max": r4(max(ws_max)), "observed_in_real_data": r4(obs_max),
                                   "empirical_p_of_observed": r4(sum(1 for m in ws_max if m >= obs_max) / N_PERM)},
            "empirical_p_of_observed_pass_count_L3": r4(sum(1 for h in ws_hits if h >= obs3) / N_PERM),
        },
        "with_seed_reselection": {
            "P_at_least_one_pass_L3": r4(sum(1 for h in wr_hits if h > 0) / N_PERM),
            "mean_passes_per_permutation_L3": r4(sum(wr_hits) / N_PERM),
            "max_passes_in_a_permutation_L3": max(wr_hits),
            "null_max_statistic": {"p50": pctl(sorted(wr_max), 0.50), "p90": pctl(sorted(wr_max), 0.90),
                                   "p95": pctl(sorted(wr_max), 0.95), "p99": pctl(sorted(wr_max), 0.99),
                                   "max": r4(max(wr_max)), "observed_in_real_data": r4(obs_max),
                                   "empirical_p_of_observed": r4(sum(1 for m in wr_max if m >= obs_max) / N_PERM)},
            "empirical_p_of_observed_pass_count_L3": r4(sum(1 for h in wr_hits if h >= obs3) / N_PERM),
        },
    },
    "supplementary_null_measurable_base": {
        "note": "**事前登録の外・診断専用**。分母を『2本とも可測』な部分集合にした版（欠測の交絡を外した版）。",
        "observed_in_real_data": r4(obs_max_m),
        "null_p50": pctl(sorted(perm_max_m), 0.50), "null_p95": pctl(sorted(perm_max_m), 0.95),
        "null_p99": pctl(sorted(perm_max_m), 0.99), "null_max": r4(max(perm_max_m)),
        "empirical_p_of_observed": r4(sum(1 for m in perm_max_m if m >= obs_max_m) / N_PERM),
    },
}

# ────────────────────────────── 陽性対照（注入検査） ──────────────────────────────
# 「合格ゼロ」という強い結論ほど先に道具を疑う。**2本積の経路そのもの**に本物の効果を仕込み、
# 同じ measure/verdict を通して合格が出ることを実証する。
N_CTRL_REP = 20
positive_control = {}
for L in (0.30, 0.25, 0.20, 0.15):
  reps = []
  for _rep in range(N_CTRL_REP):
    ka, kb = "_ctrlA", "_ctrlB"
    pop = "P_full"
    ctrl_design = {}
    for v in ALL_VINTAGES:
        R = pop_rows(v, pop)
        n = len(R)
        # **AND群を先に作る**（初版はここを間違えた——A側とB側を独立に引いてから
        # その交差集合の中で勝者を選ぼうとしたので、交差集合に居る勝者の数が上限になり
        # 仕込んだ lift が出なかった。群を先に決め、各変数の上位1/4をその群から広げる）。
        # 上位1/4の大きさは nearest-rank の q75 が高帯の最小値にちょうど載る値にする
        hi_size = n - int(math.ceil(0.75 * n)) + 1
        g = max(2 * MIN_NUM, n // 16)
        base = rate(sum(1 for r in R if r.get("win")), n)
        want = max(MIN_NUM, int(round((base + L) * g)))
        wins = [i for i in range(n) if R[i].get("win")]
        loss = [i for i in range(n) if not R[i].get("win")]
        rnd.shuffle(wins); rnd.shuffle(loss)
        want = min(want, len(wins))
        group = set(wins[:want]) | set(loss[:max(0, g - want)])
        rest = [i for i in range(n) if i not in group]
        rnd.shuffle(rest)
        need = max(0, hi_size - len(group))
        extraA = set(rest[:need])
        extraB = set(rest[need:need + need])     # A と交わらない＝交差集合はちょうど group
        a_hi, b_hi = group | extraA, group | extraB
        ctrl_design[v] = {"n": n, "hi_size": hi_size, "g_target": len(group),
                          "wins_in_group": want, "base": r4(base),
                          "intersection_is_group": (a_hi & b_hi) == group}
        for i, r in enumerate(R):
            r[ka] = (0.75 + rnd.random() * 0.25) if i in a_hi else rnd.random() * 0.74
            r[kb] = (0.75 + rnd.random() * 0.25) if i in b_hi else rnd.random() * 0.74
    # マスクを作って測る
    for v in ALL_VINTAGES:
        R = pop_rows(v, pop)
        for var in (ka, kb):
            entries = [(num(r.get(var)), tick_idx[r["ticker"]]) for r in R if num(r.get(var)) is not None]
            vals = sorted(x for x, _ in entries)
            q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
            mm = [0] * N_T
            cm = {c: [0] * N_T for c in CUTNAMES}
            preds = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                     "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}
            for x, i in entries:
                mm[i] = 1
                for c, p in preds.items():
                    if p(x):
                        cm[c][i] = 1
            VARMASK[(v, pop, var)] = {"meas": bits_to_int(mm),
                                      "cuts": {c: bits_to_int(cm[c]) for c in CUTNAMES},
                                      "q": (q25, q50, q75), "n_meas": len(entries),
                                      "distinct": len(set(vals))}
    ckey = ((ka, "上位1/4"), (kb, "上位1/4"))
    PAIRMASK[(pop, ckey)] = {v: pair_masks(v, pop, ckey) for v in ALL_VINTAGES
                             if pair_masks(v, pop, ckey)}
    per_v = {v: measure_pair(pop, ckey, v, A0, W0) for v in ALL_VINTAGES}
    got3 = [per_v[v] for v in SIGN_VINTAGES if per_v.get(v) and per_v[v]["lift"] is not None]
    lifts = [m["lift"] for m in got3]
    ent = {"population": pop, "var_a": ka, "cut_a": "上位1/4", "var_b": kb, "cut_b": "上位1/4",
           "sign_stable_161718": len({1 if l > 0 else -1 for l in lifts}) == 1,
           "maintained_lift": r4(min(abs(l) for l in lifts)),
           "sign": 1 if lifts[-1] > 0 else -1,
           "min_numerator_161718": min(m["numerator"] for m in got3)}
    reach_cache[(pop, ckey)] = reach_of(pop, ckey)
    vd = verdict_of(ent)
    reps.append({"verdict": vd["verdict"], "gate_failed_at": vd.get("gate_failed_at"),
                 "observed_lifts_161718": [r4(l) for l in lifts],
                 "n_group_161718": [m["n_group"] for m in got3],
                 "numerators_161718": [m["numerator"] for m in got3],
                 "injection_design": ({str(v): ctrl_design[v] for v in SIGN_VINTAGES}
                                      if _rep == 0 else None)})
    for v in ALL_VINTAGES:
        VARMASK.pop((v, pop, ka), None)
        VARMASK.pop((v, pop, kb), None)
    PAIRMASK.pop((pop, ckey), None)
    reach_cache.pop((pop, ckey), None)
    for r in rows_all:
        r.pop(ka, None)
        r.pop(kb, None)
  npass = sum(1 for x in reps if x["verdict"] == "合格")
  positive_control[f"true_lift={L}"] = {
      "n_repetitions": N_CTRL_REP,
      "pass_rate": r4(npass / N_CTRL_REP),
      "n_pass": npass,
      "failed_at_histogram": dict(Counter(x["gate_failed_at"] for x in reps if x["verdict"] != "合格")),
      "median_observed_lift_2018": r4(sorted(x["observed_lifts_161718"][-1] for x in reps)[N_CTRL_REP // 2]),
      "example_repetition": reps[0],
  }
positive_control["_how_to_read"] = (
    "**2本積の経路そのもの**に真の効果を仕込み、同じ measure/verdict を通して合格が出る割合を測る"
    "（1回だけ引くと乱数で結論が変わるので繰り返す）。**これは5関門すべてを通した実測の検出力**であり、"
    "上の解析的な power（ゲート1-3のみ）より低く出るのが正しい——業種調整が小さい群に厳しいため。"
    "0.30 で高い合格率が出るなら道具は動いている。出ないなら道具か検出力を疑う。")

# ────────────── 抜き取り検算（ビットマスクを一切使わず、行を直接数え直す） ──────────────
# crosscheck は「単変量の道具と同じ数字か」を見たが、**ANDの経路そのもの**は別に確かめる。
# 強い結論（合格が出た）ほど先に道具を疑う。
def row_level_measure(pop, va, ca, vb, cb, v):
    R = pop_rows(v, pop)
    def vals(var):
        return sorted(num(r.get(var)) for r in R if num(r.get(var)) is not None)
    qa, qb = vals(va), vals(vb)
    if not qa or not qb:
        return None
    def pred(cut, arr):
        q25, q50, q75 = q_at(arr, 0.25), q_at(arr, 0.50), q_at(arr, 0.75)
        return {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    pa, pb = pred(ca, qa), pred(cb, qb)
    g = [r for r in R if num(r.get(va)) is not None and num(r.get(vb)) is not None
         and pa(num(r.get(va))) and pb(num(r.get(vb)))]
    k = sum(1 for r in g if r.get("win"))
    base = rate(sum(1 for r in R if r.get("win")), len(R))
    return {"n_pop": len(R), "n_group": len(g), "numerator": k,
            "lift": r4((k / len(g) - base) if g else None),
            "tickers_2018_sample": sorted(r["ticker"] for r in g)[:15] if v == 2018 else None}


spot = {"checked": 0, "mismatches": 0, "rows": []}
for e in sorted([x for x in results if x["verdict"] == "合格"],
                key=lambda x: -(x["maintained_lift"] or 0))[:20]:
    per = {}
    for v in SIGN_VINTAGES:
        rl = row_level_measure(e["population"], e["var_a"], e["cut_a"], e["var_b"], e["cut_b"], v)
        bm = e["by_vintage"][str(v)]
        per[str(v)] = {"row_level": rl, "bitmask": bm}
        for f in ("n_pop", "n_group", "numerator", "lift"):
            spot["checked"] += 1
            if rl[f] != bm[f if f != "lift" else "lift"]:
                spot["mismatches"] += 1
    spot["rows"].append({"label": e["label"], "population": e["population"], "by_vintage": per})
spot["verdict"] = ("一致（AND の群も行を直接数えた結果と同じ）" if spot["mismatches"] == 0
                   else "⚠不一致——結論を書いてはいけない")


# ────────────── 合格した組の中身（何が群に入っているのか） ──────────────
def thresholds(pop, key, v=2018):
    """その切り方が実額でいくつなのか（『低SG&A』が何%なのかを読めるように）。"""
    out = {}
    for (var, cut) in key:
        e = VARMASK.get((v, pop, var))
        if not e:
            continue
        q25, q50, q75 = e["q"]
        thr = {"上位1/4": (">=", q75), "下位1/4": ("<=", q25),
               "中央値超": (">", q50), "中央値以下": ("<=", q50)}[cut]
        out[var] = {"cut": cut, "operator": thr[0], "threshold": (None if thr[1] is None else round(thr[1], 4)),
                    "q25": (None if q25 is None else round(q25, 4)),
                    "q50": (None if q50 is None else round(q50, 4)),
                    "q75": (None if q75 is None else round(q75, 4)),
                    "n_measurable": e["n_meas"]}
    return out


def group_profile(pop, key, v=2018):
    gm, mm = PAIRMASK[(pop, key)][v]
    rows = [r for r in pop_rows(v, pop) if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
    sic = Counter(r.get("sic2") for r in rows)
    irr = Counter(r.get("irr") for r in rows if r.get("irr") is not None)
    return {"n": len(rows), "sic2_top5": sic.most_common(5),
            "sic2_top3_share": r4(sum(c for _, c in sic.most_common(3)) / len(rows)) if rows else None,
            "n_with_irr_read": sum(1 for r in rows if r.get("irr") is not None),
            "irr_distribution": dict(sorted(irr.items())),
            "winners": sorted(r["ticker"] for r in rows if r.get("win"))[:20],
            "sample_tickers": sorted(r["ticker"] for r in rows)[:25]}


def sector_benchmark(pop, key):
    """『その群の主業種を丸ごと買う』だけの単純な規則と比べて、組は何を足しているか。
    MH は層の9割を落とすので、**支配業種そのものの lift** と **その業種の中での組の lift** を実額で出す。"""
    out = {}
    gm18, _ = PAIRMASK[(pop, key)][2018]
    rows18 = [r for r in pop_rows(2018, pop) if (gm18 >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
    if not rows18:
        return None
    dom = Counter(r.get("sic2") for r in rows18 if r.get("sic2")).most_common(1)
    if not dom:
        return None
    dom = dom[0][0]
    for v in SIGN_VINTAGES:
        R = pop_rows(v, pop)
        gm, _mm = PAIRMASK[(pop, key)][v]
        base = rate(sum(1 for r in R if r.get("win")), len(R))
        sec = [r for r in R if r.get("sic2") == dom]
        p_sec = rate(sum(1 for r in sec if r.get("win")), len(sec)) if sec else None
        ing = [r for r in R if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
        insec = [r for r in ing if r.get("sic2") == dom]
        p_insec = rate(sum(1 for r in insec if r.get("win")), len(insec)) if insec else None
        out[str(v)] = {
            "dominant_sic2": dom, "n_sector": len(sec), "p_sector": r4(p_sec),
            "lift_of_sector_alone": r4(None if p_sec is None else p_sec - base),
            "n_group_in_sector": len(insec), "p_group_in_sector": r4(p_insec),
            "lift_of_pair_within_that_sector": r4(None if (p_insec is None or p_sec is None)
                                                  else p_insec - p_sec),
            "share_of_group_in_that_sector": r4(rate(len(insec), len(ing))),
        }
    return out


passers = []
for e in sorted([x for x in results if x["verdict"] == "合格"], key=lambda x: -(x["maintained_lift"] or 0)):
    key = ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))
    vf = e["verdict_full"]
    passers.append({
        "label": e["label"], "population": e["population"],
        "maintained_lift": e["maintained_lift"],
        "maintained_lift_measurable_base": e["maintained_lift_meas"],
        "coverage_both_min": e["coverage_both_min"],
        "lift_increment_vs_best_leg": e["lift_increment_vs_best_leg"],
        "by_vintage": e["by_vintage"],
        "sector_mh": vf.get("mh"), "irr_control_2018": vf.get("irr"),
        "group_profile_2018": group_profile(e["population"], key),
        "sector_benchmark": sector_benchmark(e["population"], key),
        "thresholds_2018": thresholds(e["population"], key),
    })

# 合格した組が実質いくつの「別々の発見」なのか（脚の重なりを数える）
pass_legs = Counter()
for e in results:
    if e["verdict"] == "合格":
        pass_legs[f"{e['var_a']}[{e['cut_a']}]"] += 1
        pass_legs[f"{e['var_b']}[{e['cut_b']}]"] += 1
pass_varpairs = {f"{min(e['var_a'], e['var_b'])}×{max(e['var_a'], e['var_b'])}"
                 for e in results if e["verdict"] == "合格"}
pass_varpairs_canon = {f"{min(canon(e['var_a']), canon(e['var_b']))}×{max(canon(e['var_a']), canon(e['var_b']))}"
                       for e in results if e["verdict"] == "合格"}


# ────────────────────────────── 上位30組 ──────────────────────────────
rank = [e for e in results if e.get("maintained_lift") is not None and e.get("sign") == 1]
rank.sort(key=lambda e: (-e["maintained_lift"], -(e["lift_increment_vs_best_leg"] or 0)))
top30 = []
for e in rank[:30]:
    b18 = e["by_vintage"]["2018"]
    top30.append({
        "label": e["label"], "population": e["population"],
        "maintained_lift_161718": e["maintained_lift"],
        "lift_increment_vs_best_leg": e["lift_increment_vs_best_leg"],
        "best_leg_maintained_lift": e["best_leg_maintained_lift"],
        "maintained_lift_measurable_base": e["maintained_lift_meas"],
        "coverage_both_min": e["coverage_both_min"],
        "min_numerator_161718": e["min_numerator_161718"],
        "anchor_2018": b18,
        "lift_by_vintage": {v: (e["by_vintage"][v]["lift"] if e["by_vintage"][v] else None)
                            for v in ("2016", "2017", "2018")},
        "n_group_by_vintage": {v: (e["by_vintage"][v]["n_group"] if e["by_vintage"][v] else None)
                               for v in ("2016", "2017", "2018")},
        "numerator_by_vintage": {v: (e["by_vintage"][v]["numerator"] if e["by_vintage"][v] else None)
                                 for v in ("2016", "2017", "2018")},
        "verdict": e["verdict"], "verdict_reason": e["verdict_full"]["reason"],
        "gate_failed_at": e["verdict_full"].get("gate_failed_at"),
        "thresholds_2018": thresholds(e["population"],
                                      ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))),
        "sector_benchmark_2018": (sector_benchmark(e["population"],
                                                   ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))) or {}).get("2018"),
    })

# 増分の分布（設計8: 組は片脚に対して何を足したか）
inc = [e["lift_increment_vs_best_leg"] for e in rank if e["lift_increment_vs_best_leg"] is not None]
inc.sort()
increment_summary = {
    "n_pairs_with_positive_maintained_lift": len(rank),
    "increment_percentiles": {k: pctl(inc, p) for k, p in
                              (("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))},
    "max_increment": r4(inc[-1]) if inc else None,
    "n_increment_positive": sum(1 for x in inc if x > 0),
    "n_increment_ge_0.05": sum(1 for x in inc if x >= 0.05),
    "note": "増分＝組の維持lift − 各脚単独の維持liftの最大。**組の存在価値そのもの**。"
            "増分が小さければ、その組は片脚が運んでいるだけで2本目は何も足していない。",
}

# ────────────────────────────── 出力 ──────────────────────────────
out = {
    "generated": "2026-08-11",
    "tool": "night/hist_wd_win_pair.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "inputs": {"panel": "out/hist_wd_panel.json", "univariate": "out/hist_wd_win_uni.json"},
    "objective": "A_勝者: P(実現年率 tr_cagr >= +15%)。2本積（AND）のみ。破壊側(目的B)はこの道具の範囲外。",
    "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM,
                       "sign_stability_vintages": SIGN_VINTAGES,
                       "sector_control": "同一sic2内(MH)でも|差|>=0.15",
                       "not_irr_shadow": "irr>=70層内でも|lift|>=0.15、または irr と直交",
                       "note": "prereg の literal。この道具は線を一つも作らず、一つも緩めていない。"},
    "design_decisions": {
        "analysis_set": "has_outcome ∧ window_full（単変量と同一）",
        "search_space": "符号不変ゲートを当てられる21本のみ。co_/pa_/hv_/per は構造的に判定不能ゆえ除外（不合格ではない）",
        "populations": "P_full と P_quality。P_moat は 2016/2017 に母集団が無く符号不変ゲートを当てられない",
        "seeds": "各母集団で『3ビンテージとも lift が正・揃った上での最小 lift』が大きい上位10本",
        "binarization": "prereg の combos どおり 中央値 / 上下1/4。種は同じ向きの2通り、相手は4通り",
        "thresholds": "各変数が自分の分布（母集団内・可測行のみ・nearest-rank）で切る。ANDの交差で切り直さない",
        "lift_denominator": "prereg literal の母集団。lift_vs_measurable_both を必ず併記",
        "self_pairs": "同じ変数どうしの組は作らない（空 or 入れ子）",
    },
    "crosscheck_vs_univariate_tool": crosscheck,
    "spot_check_row_level": spot,
    "duplicate_columns_in_search_space": {
        "found": dup_pairs,
        "note": ("同じ量が別名で二度入っていると、検定数が水増しされ・『別々の発見』が二重に見え・"
                 "種の枠を一つ食う。仮定せず全行を突き合わせて検出した。"),
    },
    "excluded_candidates_structurally_undecidable": EXCLUDED,
    "seeds": {pop: seeds[pop] for pop in POPS},
    "seed_selection_table": seed_tables,
    "search_space_size": {
        "per_population": enum_stats,
        "n_tests_total_after_dedup": n_tests_total,
        "n_tests_univariate": uni["must_report_before_verdict"]["false_positive_rate"]["n_tests_in_procedure"],
        "note": "**多重検定の値札**。単変量の168検定に対して何倍を試したか。偽陽性率はこの数で決まる。",
    },
    "must_report_before_verdict": {
        "reachability": reach_summary,
        "power": power,
        "false_positive_rate": fpr,
        "positive_control_injection": positive_control,
    },
    "verdict_counts": {"by_verdict": dict(vcount), "fail_gate_histogram": dict(fail_hist),
                       "undetermined_gate_histogram": dict(und_hist),
                       "n_pass": vcount.get("合格", 0),
                       "n_distinct_variable_pairs_among_passes": len(pass_varpairs),
                       "distinct_variable_pairs_among_passes": sorted(pass_varpairs),
                       "n_distinct_after_deduplicating_identical_columns": len(pass_varpairs_canon),
                       "distinct_variable_pairs_deduplicated": sorted(pass_varpairs_canon),
                       "leg_frequency_among_passes": dict(pass_legs.most_common()),
                       "note": ("合格が複数出ても『別々の発見』とは限らない——同じ脚の入れ子の切り方が"
                                "何通りも通るだけのことがある。**変数の組の異なり数**で読むこと。")},
    "passing_pairs_detail": passers,
    "increment_over_single_leg": increment_summary,
    "top30_by_maintained_lift": top30,
    "top30_note": ("in-sample の最良＝**過剰適合込みの上限**。"
                   f"{n_tests_total}通りを試した中の最大値なので、"
                   "偽陽性率と帰無分布（上の false_positive_rate）と必ず突き合わせて読むこと。"),
    "all_pairs": [{k: e.get(k) for k in ("population", "label", "var_a", "cut_a", "var_b", "cut_b",
                                         "maintained_lift", "maintained_lift_meas", "sign",
                                         "min_numerator_161718", "lift_increment_vs_best_leg",
                                         "best_leg_maintained_lift", "coverage_both_min", "verdict")}
                  | {"gate_failed_at": e["verdict_full"].get("gate_failed_at")}
                  for e in results],
    "runtime_sec": round(time.time() - t0, 1),
}
json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print(f"[crosscheck] 比較 {crosscheck['compared']} 件 / 不一致 {crosscheck['mismatches']} 件 → {crosscheck['verdict']}")
print(f"[検定数] 2本積 {n_tests_total} 検定（単変量 168 の {n_tests_total/168:.1f}倍）")
for pop in POPS:
    print(f"  {pop}: 種{len(seeds[pop])}本 → 生{enum_stats[pop]['n_raw_combinations']} → 重複除去{enum_stats[pop]['n_after_dedup']}")
    print(f"    種: " + ", ".join(f"{s['variable']}[{s['best_cut']}]{s['maintained_lift']}" for s in seeds[pop]))
print(f"[判定] " + " / ".join(f"{k}:{v}" for k, v in vcount.items()) + f"  合格={vcount.get('合格',0)}")
print("[到達可能性] " + " / ".join(
    f"{pop}: 到達可能{reach_summary[pop]['n_pairs_reachable']}/{reach_summary[pop]['n_pairs']}"
    f" MIN_NUMが縛るセル{reach_summary[pop]['cell_vintages_where_MIN_NUM_binds']}" for pop in POPS))
print("[FPR] 偶然に1組でも通る確率 " + " ".join(
    f"{k}={v}" for k, v in fpr["P_at_least_one_pass_by_level"].items())
      + " / 平均通過数 " + " ".join(f"{k}={v}" for k, v in fpr["mean_passes_per_permutation_by_level"].items()))
print(f"      観測通過数 {fpr['observed_passes_by_level']} 経験p {fpr['empirical_p_of_observed_pass_count']}")
print(f"      最大統計量 観測{fpr['null_distribution_of_max_statistic']['observed_in_real_data']} "
      f"(帰無 p50={fpr['null_distribution_of_max_statistic']['p50']} p95={fpr['null_distribution_of_max_statistic']['p95']} "
      f"経験p={fpr['null_distribution_of_max_statistic']['empirical_p_of_observed']})")
print("[陽性対照] " + " / ".join(f"{k}:合格率{v['pass_rate']}"
                                for k, v in positive_control.items() if k.startswith("true")))
print(f"[増分] 中央値 {increment_summary['increment_percentiles']['p50']} / 0.05以上 {increment_summary['n_increment_ge_0.05']}組")
print(f"→ {DEST}  ({out['runtime_sec']}s)")
