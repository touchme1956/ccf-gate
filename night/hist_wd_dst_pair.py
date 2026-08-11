#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_dst_pair.py — 破壊側（目的B: P(実現年率 tr_cagr <= -15%)）の**2本組合せ**探索。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json（5ビンテージ統合パネル）
          out/hist_wd_win_uni.json（**勝者側**の単変量＝実装の検算相手。破壊側の答えには使わない）
          out/hist_wd_dst_uni.json（あれば破壊側の単変量と突合せる。無くても走る）
出力    : out/hist_wd_dst_pair.json

対になる道具: night/hist_wd_win_pair.py（勝者側・目的A）。**形はそちらに揃えてある**。
違うのは outcome が destroy であることと、下に書いた「破壊側でしか起きない4つの構造問題」だけ。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定（後から読む人へ）
────────────────────────────────────────────────────────────
1) **解析集合は has_outcome ∧ window_full**（勝者側の道具と同一）。短窓は年率換算で両裾を
   機械的に膨らませる（パネルの診断: 2013 の DBD は 3.01年）。**破壊側は裾を数える仕事なので、
   ここを緩めると偽の破壊が入る。**

2) **探索空間は「符号不変ゲートを当てられる21本」だけ**。co_(2013/2015のみ)・pa_(2018のみ)・
   hv_/per(2016/2017に無い) は**結果を見る前から構造的に判定不能**。
   ——これは「不合格」ではない。判定不能を不合格と書かないための除外である。
   この21本は**この道具が自分で構造から導出**し、勝者側の道具の一覧と一致することを検算する
   （ゲート到達可能性は**特徴量の性質**で outcome に依らないので、一致しなければどちらかが壊れている）。

3) ★**母集団は P_full だけ**。破壊側でしか起きない問題:
   - **P_quality は 2017 の破壊事象が母集団全体で 4件**しかなく、prereg の分子>=5 に
     **測る前から届かない**。符号不変ゲートは 2016/2017/2018 の3つを要求するので、
     **P_quality のあらゆる組が自動的に判定不能**になる。
   - P_moat は 2016/2017 が空、破壊事象も 0-1件。
   → 判定できないセルを数千個作ると検定数だけ増えて偽陽性率を押し上げる（W2 が P_moat を
     外したのと同じ理由）。**ただし「測れない」ことは結果なので、下の (11) で別に報告する。**

4) ★**破壊側の合否線は算術的に片側でしかありえない**。lift の下限は −base（群の破壊率は0が下限）で、
   破壊の base は最大でも 0.081（2018 P_full）。よって **lift <= -0.15 はどのセルでも不可能**＝
   「破壊を減らす指標」は prereg の線では**原理的に合格できない**。
   種は正の維持lift（＝破壊率を上げる向き）からのみ採る。**これは線を狭めたのではなく、
   線が最初から片側だったことを測って明示するだけ。**

5) **種**: その母集団で 2016/2017/2018 とも lift が正、揃った上での最小 lift が大きい上位10本。
   種は同じ向きの2通り（1/4側・中央値側）で入れる。相手は全候補×4通りの切り方。
   同じ変数どうしの組は作らない（空 or 入れ子＝新しい情報がない）。

6) ★**物語の組（FORCED_PAIRS）を結果を見る前に登録する**。探索を種から始めると、
   「破壊の物語として筋が通る組」が**種に選ばれなかっただけで表から消える**。
   高成長×低FCF転換／高のれん×低カバレッジ／高株式発行×低利益率 など、
   **何を測るかは結果を見る前に決め、結論は測定で出す**。
   これらは検定数に**数える**（多重検定の値札を踏み倒さない）。帰無にも同じだけ足す。

7) **分位は各変数が自分の分布で切る**（母集団内・その変数を報告している行のみ・nearest-rank）。
   AND の交差集合で切り直さない——切り直すと「相手の欠測が閾値を動かす」ことになる。

8) **lift の分母は prereg の literal どおり母集団**。2本積は欠測が二重に効くので
   `lift_vs_measurable_both` を必ず併記し、二つが食い違うセルには印を付ける。

9) **2本積の本当の問いは『増分』**。各組に `lift_increment_vs_best_leg` を必ず付ける。
   片脚が単独で同じだけ効いていれば、その組は何も足していない。

10) ★**ゲート5(irr の影でないか)は、破壊側では層内検定が構造的に不可能**。
    irr>=70 の層の破壊事象は **2013:1 / 2015:1 / 2018:0** で、どのビンテージも分子5に届かない。
    → 層内 lift が 0 と出ても、それは「差が消えた」のではなく**測れていない**。
    **0件を『差が消えた』と読まない**（絶対のルール7の同族）。層内検定は到達不能として扱い、
    直交（|rho|<0.15）でのみ通す。直交とも言えなければ**判定不能**（不合格ではない）。

11) **P_quality は事前登録の外の補助表として別に測る**（2016+2018 の2ビンテージのみ）。
    **合否には一切数えない**。門が実際に当てる場所なので「測れない」で終わらせず、
    測れる範囲の絵と、その絵に対する帰無を出す。

12) ★**抜き取り検算は合格の有無に関わらず行う**。勝者側の道具は「合格した組」だけを
    行レベルで数え直していたが、**合格ゼロだと検算が0件になる**——
    「合格ゼロ」という強い結論こそ道具を疑うべき場面なのに、そこで検算が消える。
    → 乱択40組＋物語の組＋合格全部を、ビットマスクを使わずに数え直す。

13) **突合せ**: 破壊側の単変量の道具はまだ無いので、**同じ実装に勝者側のラベルを流して
    hist_wd_win_uni.json を1件も違わず再現できること**を先に示す。
    実装が勝者側で正しければ、outcome を差し替えただけの破壊側も同じ経路を通る。
"""
import json, os, sys, math, random, time
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
WIN_UNI = os.path.join(OUT, "hist_wd_win_uni.json")
DST_UNI = os.path.join(OUT, "hist_wd_dst_uni.json")     # 無くてよい
DEST = os.path.join(OUT, "hist_wd_dst_pair.json")

# ─── prereg の線（この道具は一つも作らない・読むだけ） ───
LIFT = 0.15
MIN_NUM = 5
SIGN_VINTAGES = [2016, 2017, 2018]
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS_ALL = ["P_full", "P_quality", "P_moat"]
POPS = ["P_full"]                       # 設計3: 判定を出せるのはここだけ（下で測って示す）
SUP_POP = "P_quality"                   # 設計11: 事前登録の外の補助表
SUP_VINTAGES = [2016, 2018]
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]
HIGH_SIDE = {"上位1/4", "中央値超"}
LOW_SIDE = {"下位1/4", "中央値以下"}
N_SEEDS = 10

SEED = 20260811
N_PERM = 2000
N_PERM_SUP = 1000
N_POWER = 4000
N_SPOT_RANDOM = 40

t0 = time.time()

# ────────────────────────────────────────────────────────────
# 設計6: 物語の組（結果を見る前に登録する）
#   (変数A, A側, 変数B, B側, 物語)  ——側は "high"/"low"。切り方は 1/4側・中央値側の両方を試す。
# ────────────────────────────────────────────────────────────
FORCED_PAIRS = [
    ("f2_cagr5", "high", "f2_conv5", "low",
     "高成長 かつ 低FCF転換＝売上は伸びているのに利益が現金にならない（成長の質の欠如）"),
    ("f2_gw_r", "high", "f2_intcov", "low",
     "高のれん かつ 低カバレッジ＝買収で膨らんだ資産を薄い利払能力で支えている"),
    ("f2_netiss_r", "high", "f2_opm", "low",
     "高株式発行 かつ 低利益率＝稼げないので株を刷って埋めている（netiss_r は正が純希薄化）"),
    ("f2_gw_r", "high", "f2_accr", "high",
     "高のれん かつ 高アクルーアル＝買収で積んだ資産と、現金化しない会計利益"),
    ("f2_netiss_r", "high", "f2_conv5", "low",
     "高株式発行 かつ 低FCF転換＝現金を生まないのに株で資金を賄っている"),
    ("f2_intcov", "low", "f2_opmD5", "low",
     "低カバレッジ かつ 利益率が5年で悪化＝薄い利払能力が、さらに薄くなっている"),
    ("f2_capex_r", "high", "f2_intcov", "low",
     "重い設備投資 かつ 低カバレッジ＝固定費と金利費用の二重の重さ"),
    ("f2_cagr5", "high", "f2_accr", "high",
     "高成長 かつ 高アクルーアル＝伸びている売上が現金の裏づけを持たない"),
    ("f2_opm", "low", "f2_cash_r", "low",
     "薄利 かつ 手元現金なし＝一度の逆風を吸収する余力がない"),
    ("f2_gw_r", "high", "f2_opmD5", "low",
     "高のれん かつ 利益率が5年で悪化＝買収したのに事業の質が下がっている"),
]


# ────────────────────────────── 小道具（数学だけ・判定を含まない） ──────────────────────────────
def q_at(sorted_vals, q):
    """nearest-rank 分位（外挿しない・実在する値だけを閾値にする）。勝者側の道具と同一定義。"""
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


def pctl(a, p):
    return r4(a[min(len(a) - 1, max(0, int(p * len(a)) - 1))]) if a else None


# ────────────────────────────── 読み込み ──────────────────────────────
panel = json.load(open(PANEL, encoding="utf-8"))
prereg = json.load(open(PREREG, encoding="utf-8"))
win_uni = json.load(open(WIN_UNI, encoding="utf-8"))
dst_uni = json.load(open(DST_UNI, encoding="utf-8")) if os.path.exists(DST_UNI) else None

rows_all = panel["rows"]
ANA = [r for r in rows_all if r.get("has_outcome") and r.get("window_full")]

by_v = defaultdict(list)
for r in ANA:
    by_v[r["vintage"]].append(r)

for v in ALL_VINTAGES:
    tk = [r["ticker"] for r in by_v[v]]
    assert len(tk) == len(set(tk)), f"vintage {v} にティッカーの重複がある＝ビット索引が壊れる"


def pop_rows(v, pop):
    return [r for r in by_v[v] if r.get(pop) is True]


# ── 設計2: 候補を構造から自分で導出する（outcome に依らない性質なので勝者側と一致するはず） ──
ALL_FEATURE_KEYS = sorted({k for r in ANA for k in r.keys()
                           if k.startswith(("f2_", "co_", "pa_", "hv_")) or k in ("per", "size_rev")})
SKIP_KEYS = {"f2_fy", "f2_fy_end", "size_src"}       # 会計年度そのもの・出所ラベルは指標ではない
CAND_POOL = [k for k in ALL_FEATURE_KEYS if k not in SKIP_KEYS]

CANDIDATES, EXCLUDED = [], []
for var in CAND_POOL:
    ok = True
    for v in SIGN_VINTAGES:
        if not any(num(r.get(var)) is not None for r in pop_rows(v, "P_full")):
            ok = False
            break
    (CANDIDATES if ok else EXCLUDED).append(var)

cand_check = {
    "derived_here": CANDIDATES,
    "winner_tool_list": list(win_uni["must_report_before_verdict"]["gate_reachable_variables"]),
    "identical": sorted(CANDIDATES) == sorted(win_uni["must_report_before_verdict"]["gate_reachable_variables"]),
    "note": ("ゲート到達可能性は**特徴量の性質**で outcome に依らない。"
             "勝者側の道具が出した一覧と一致しなければ、どちらかが壊れている。"),
}

# ────────────────────────────── ビット索引（観測も置換も同じ経路を通す） ──────────────────────────────
tick_idx = {}
for v in ALL_VINTAGES:
    for r in by_v[v]:
        if r["ticker"] not in tick_idx:
            tick_idx[r["ticker"]] = len(tick_idx)
N_T = len(tick_idx)


def bits_to_int(bits):
    return int("".join("1" if b else "0" for b in bits), 2)


A_bits, D_bits, Wn_bits = {}, {}, {}
for v in ALL_VINTAGES:
    a = [0] * N_T
    d = [0] * N_T
    w = [0] * N_T
    for r in by_v[v]:
        i = tick_idx[r["ticker"]]
        a[i] = 1
        if r.get("destroy"):
            d[i] = 1
        if r.get("win"):
            w[i] = 1
    A_bits[v], D_bits[v], Wn_bits[v] = a, d, w
A0 = {v: bits_to_int(A_bits[v]) for v in ALL_VINTAGES}
D0 = {v: bits_to_int(D_bits[v]) for v in ALL_VINTAGES}
W0 = {v: bits_to_int(Wn_bits[v]) for v in ALL_VINTAGES}

POPMASK = {}
for v in ALL_VINTAGES:
    for pop in POPS_ALL:
        bits = [0] * N_T
        for r in pop_rows(v, pop):
            bits[tick_idx[r["ticker"]]] = 1
        POPMASK[(v, pop)] = bits_to_int(bits)

# 変数ごとの可測マスク・切り方マスク・閾値（設計7: 各変数は自分の分布で切る）
VARMASK = {}
for v in ALL_VINTAGES:
    for pop in POPS_ALL:
        R = pop_rows(v, pop)
        if not R:
            continue
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
DUP_CANON = {d["b"]: d["a"] for d in dup_pairs}


def canon(var):
    return DUP_CANON.get(var, var)


# ────────────────────────────── 単一の測定（種の選定・脚・検算がすべてこれを通る） ──────────────────────────────
def single_measure(v, pop, var, cut, Aint, Yint):
    e = VARMASK.get((v, pop, var))
    if not e:
        return None
    pm = POPMASK[(v, pop)]
    a, y = Aint[v], Yint[v]
    n_pop = (pm & a).bit_count()
    if n_pop == 0:
        return None
    k_pop = (pm & y).bit_count()
    gm = e["cuts"][cut]
    n_g = (gm & a).bit_count()
    k_g = (gm & y).bit_count()
    n_m = (e["meas"] & a).bit_count()
    k_m = (e["meas"] & y).bit_count()
    p_pop = rate(k_pop, n_pop)
    return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": p_pop, "n_group": n_g, "k": k_g,
            "p_group": rate(k_g, n_g), "n_meas": n_m, "k_meas": k_m,
            "lift": (None if n_g == 0 else rate(k_g, n_g) - p_pop),
            "lift_meas": (None if n_g == 0 or n_m == 0 else rate(k_g, n_g) - rate(k_m, n_m))}


# ── 設計13: 実装の検算（勝者側のラベルを流して勝者側の道具を再現できるか） ──
crosscheck_win = {"compared": 0, "mismatches": 0, "examples": []}
for var in CANDIDATES:
    for pop in POPS_ALL:
        for v in ALL_VINTAGES:
            ref = win_uni["cells"].get(f"{var}|{pop}|{v}")
            if not ref or ref.get("n_measurable", 0) == 0:
                continue
            for cut in CUTNAMES:
                m = single_measure(v, pop, var, cut, A0, W0)
                if m is None:
                    continue
                rc = ref["cuts"][cut]
                pairs = [("n_pop", m["n_pop"], ref["n_pop"]), ("k_pop", m["k_pop"], ref["k_pop"]),
                         ("n_measurable", m["n_meas"], ref["n_measurable"]),
                         ("n_group", m["n_group"], rc["n_group"]), ("numerator", m["k"], rc["numerator"]),
                         ("lift", r4(m["lift"]), rc["lift_vs_pop"])]
                for name, mine, theirs in pairs:
                    crosscheck_win["compared"] += 1
                    if mine != theirs:
                        crosscheck_win["mismatches"] += 1
                        if len(crosscheck_win["examples"]) < 12:
                            crosscheck_win["examples"].append(
                                {"cell": f"{var}|{pop}|{v}|{cut}", "field": name,
                                 "dst_pair_tool": mine, "win_uni_tool": theirs})
crosscheck_win["verdict"] = (
    "一致（勝者側のラベルを流すと勝者側の道具と同じ数字を出す＝測定の経路は同じ。"
    "outcome を destroy に差し替えただけの破壊側も同じ経路を通る）"
    if crosscheck_win["mismatches"] == 0 else "⚠不一致——結論を書いてはいけない")

# ── 破壊側の単変量の道具があれば、それとも突合せる ──
crosscheck_dst = {"status": "out/hist_wd_dst_uni.json が無いので突合せていない"}
if dst_uni and "cells" in dst_uni:
    cc = {"compared": 0, "mismatches": 0, "examples": []}
    for var in CANDIDATES:
        for pop in POPS_ALL:
            for v in ALL_VINTAGES:
                ref = dst_uni["cells"].get(f"{var}|{pop}|{v}")
                if not ref or ref.get("n_measurable", 0) == 0:
                    continue
                for cut in CUTNAMES:
                    m = single_measure(v, pop, var, cut, A0, D0)
                    if m is None:
                        continue
                    rc = ref["cuts"][cut]
                    for name, mine, theirs in (("n_group", m["n_group"], rc.get("n_group")),
                                               ("numerator", m["k"], rc.get("numerator")),
                                               ("lift", r4(m["lift"]), rc.get("lift_vs_pop"))):
                        cc["compared"] += 1
                        if mine != theirs:
                            cc["mismatches"] += 1
                            if len(cc["examples"]) < 12:
                                cc["examples"].append({"cell": f"{var}|{pop}|{v}|{cut}",
                                                       "field": name, "pair": mine, "uni": theirs})
    cc["verdict"] = "一致" if cc["mismatches"] == 0 else "⚠不一致——結論を書いてはいけない"
    crosscheck_dst = cc

# ────────────────────────────── 設計4: 破壊側の線は算術的に片側 ──────────────────────────────
one_sided = {"cells": [], "max_base_over_cells": None, "negative_side_possible_anywhere": False}
mb = 0.0
for pop in POPS_ALL:
    for v in ALL_VINTAGES:
        R = pop_rows(v, pop)
        if not R:
            continue
        n = len(R)
        k = sum(1 for r in R if r.get("destroy"))
        base = k / n
        mb = max(mb, base)
        possible_neg = base >= LIFT
        if possible_neg:
            one_sided["negative_side_possible_anywhere"] = True
        one_sided["cells"].append({"vintage": v, "pop": pop, "n": n, "destroy_events": k,
                                   "base": r4(base), "min_possible_lift": r4(-base),
                                   "lift_le_minus_0.15_possible": possible_neg})
one_sided["max_base_over_cells"] = r4(mb)
one_sided["conclusion"] = (
    f"破壊の base は最大でも {r4(mb)}。lift の下限は −base（群の破壊率の下限が0だから）なので、"
    f"**lift <= -0.15 はどのセルでも算術的に不可能**。"
    "＝prereg の |lift|>=0.15 は、破壊側では『破壊を増やす向き』の片側の線としてしか働かない。"
    "『破壊を減らす指標』はこの線では原理的に合格できない——**線を狭めたのではなく、"
    "線が最初から片側だったことを測って明示している**。")

# ────────────────────────────── 設計3: 母集団ごとの構造的な判定可能性 ──────────────────────────────
pop_decidability = {}
for pop in POPS_ALL:
    per_v = {}
    dec = True
    for v in SIGN_VINTAGES:
        R = pop_rows(v, pop)
        n = len(R)
        k = sum(1 for r in R if r.get("destroy"))
        ok = (n > 0 and k >= MIN_NUM)
        per_v[str(v)] = {"n": n, "destroy_events": k, "min_numerator_reachable_at_all": ok,
                         "status": ("ok" if ok else
                                    ("population_empty" if n == 0 else
                                     f"母集団全体の破壊事象が {k} 件しかなく分子>=5 に届かない"))}
        dec = dec and ok
    pop_decidability[pop] = {
        "by_vintage": per_v,
        "decidable": dec,
        "in_primary_search_space": pop in POPS,
        "note": ("判定を出せる" if dec else
                 "**測る前から全ての組が判定不能**（符号不変ゲートが3ビンテージを要求するため）"),
    }
pop_decidability["_how_to_read"] = (
    "**これは不合格ではない**。母集団に事象そのものが足りないので、どんな指標を当てても"
    "prereg の分子>=5 を満たせない。v1の教訓『合否基準が母集団の稀少事象の実数で到達可能かを"
    "結果を見る前に数える』を、破壊側で実際に踏んだ形。")

# ────────────────────────────── 種の選定（設計5・単一実装） ──────────────────────────────
def uni_maintained(pop, var, cut, Aint, Yint, vints):
    """指定ビンテージすべてで符号が揃ったうえでの最小|lift|（符号つき）。揃わなければ None。
    **観測側の種の選定と、帰無での種の選び直しが、この同じ関数を通る。**"""
    signs, mn, lifts, nums = set(), 1e9, [], []
    for v in vints:
        m = single_measure(v, pop, var, cut, Aint, Yint)
        if m is None or m["lift"] is None:
            return None
        lift = m["lift"]
        lifts.append(lift)
        nums.append(m["k"])
        signs.add(1 if lift > 0 else (-1 if lift < 0 else 0))
        if len(signs) > 1 or 0 in signs:
            return None
        mn = min(mn, abs(lift))
    return {"sign": signs.pop(), "min_abs": mn, "lifts": lifts, "nums": nums}


def pick_seeds(pop, Aint, Yint, vints, n_seeds=N_SEEDS):
    scored = []
    for var in CANDIDATES:
        best = None
        for cut in CUTNAMES:
            ml = uni_maintained(pop, var, cut, Aint, Yint, vints)
            if not ml or ml["sign"] != 1:      # 設計4: 破壊側は正の向きしか合格しえない
                continue
            if best is None or ml["min_abs"] > best["min_abs"]:
                best = {"cut": cut, **ml}
        if best:
            scored.append({"variable": var, "best_cut": best["cut"],
                           "maintained_lift": r4(best["min_abs"]),
                           "lifts": [r4(x) for x in best["lifts"]], "numerators": best["nums"],
                           "side": ("high" if best["cut"] in HIGH_SIDE else "low")})
    scored.sort(key=lambda x: -x["maintained_lift"])
    return scored[:n_seeds], scored


seeds, seed_tables = {}, {}
for pop in POPS:
    s, full = pick_seeds(pop, A0, D0, SIGN_VINTAGES)
    seeds[pop] = s
    seed_tables[pop] = {"n_variables_with_positive_stable_cut": len(full), "ranked": full}


# ────────────────────────────── 組の列挙（設計5/6: 数えてから測る） ──────────────────────────────
def side_cuts(side):
    return ["上位1/4", "中央値超"] if side == "high" else ["下位1/4", "中央値以下"]


_fk = set()
forced_meta = []
for (va, sa, vb, sb, story) in FORCED_PAIRS:
    got = []
    for ca in side_cuts(sa):
        for cb in side_cuts(sb):
            key = tuple(sorted([(va, ca), (vb, cb)]))
            _fk.add(key)
            got.append(key)
    forced_meta.append({"var_a": va, "side_a": sa, "var_b": vb, "side_b": sb,
                        "story": story, "n_cut_combinations": len(got),
                        "labels": [f"{k[0][0]}[{k[0][1]}] ∧ {k[1][0]}[{k[1][1]}]" for k in got]})
# ★集合のまま回すと **PYTHONHASHSEED で順序が変わり出力が再現しなくなる**（実測で踏んだ）。
#   決定的であることは「同じ道具を回せば同じ数字が出る」ことの前提なので、必ず並べてから使う。
forced_keys = tuple(sorted(_fk))

pair_keys, pair_origin, enum_stats = {}, {}, {}
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
                    key = tuple(sorted([(s["variable"], sc), (var2, c2)]))
                    if key not in seen:
                        seen[key] = "seed"
    n_from_seed = len(seen)
    n_forced_new = 0
    for key in forced_keys:
        (va, _ca), (vb, _cb) = key
        if va == vb:
            continue
        if key not in seen:
            seen[key] = "forced"
            n_forced_new += 1
        else:
            seen[key] = "seed+forced"
    pair_keys[pop] = sorted(seen.keys())
    pair_origin[pop] = seen
    enum_stats[pop] = {
        "n_seeds": len(seeds[pop]),
        "seed_cuts_per_seed": 2,
        "n_partner_variables": len(CANDIDATES) - 1,
        "partner_cuts_per_partner": 4,
        "n_raw_combinations_from_seeds": raw,
        "n_after_dedup_from_seeds": n_from_seed,
        "n_forced_pairs_declared": len(forced_keys),
        "n_forced_pairs_new_beyond_seeds": n_forced_new,
        "n_tests_total": len(seen),
        "dedup_note": "種どうしの組は2回列挙されるので正規化して1回にした。物語の組も同じ鍵で重複除去した",
    }

n_tests_total = sum(len(v) for v in pair_keys.values())


# ────────────────────────────── 中核: 1組の測定 ──────────────────────────────
def pair_masks(v, pop, key):
    (va, ca), (vb, cb) = key
    ea, eb = VARMASK.get((v, pop, va)), VARMASK.get((v, pop, vb))
    if not ea or not eb:
        return None
    return (ea["cuts"][ca] & eb["cuts"][cb], ea["meas"] & eb["meas"])


PAIRMASK = {}
for pop in POPS:
    for key in pair_keys[pop]:
        d = {}
        for v in ALL_VINTAGES:
            m = pair_masks(v, pop, key)
            if m:
                d[v] = m
        PAIRMASK[(pop, key)] = d


def measure_pair(pop, key, v, Aint, Yint):
    d = PAIRMASK.get((pop, key))
    if not d or v not in d:
        return None
    gm, mm = d[v]
    pm = POPMASK[(v, pop)]
    a, y = Aint[v], Yint[v]
    n_pop = (pm & a).bit_count()
    if n_pop == 0:
        return None
    k_pop = (pm & y).bit_count()
    p_pop = k_pop / n_pop
    n_g = (gm & a).bit_count()
    k_g = (gm & y).bit_count()
    n_m = (mm & a).bit_count()
    k_m = (mm & y).bit_count()
    return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": p_pop,
            "n_measurable_both": n_m, "p_measurable_both": rate(k_m, n_m),
            "n_group": n_g, "numerator": k_g, "p_group": rate(k_g, n_g),
            "lift": (None if n_g == 0 else k_g / n_g - p_pop),
            "lift_meas": (None if n_g == 0 or n_m == 0 else k_g / n_g - k_m / n_m)}


# ────────────────────────────── 到達可能性（結果を見る前に出す） ──────────────────────────────
def reach_of(pop, key):
    per_v, verdicts = {}, []
    for v in SIGN_VINTAGES:
        m = measure_pair(pop, key, v, A0, D0)
        if not m:
            per_v[str(v)] = {"verdict": "この母集団・ビンテージで測れない"}
            verdicts.append(False)
            continue
        n_g, base, ev = m["n_group"], m["p_pop"], m["k_pop"]
        if n_g == 0:
            per_v[str(v)] = {"n_group": 0, "verdict": "群が空＝この切り方が成立しない"}
            verdicts.append(False)
            continue
        k_lift = math.ceil((base + LIFT) * n_g)
        need = max(k_lift, MIN_NUM)
        possible = need <= min(n_g, ev)
        per_v[str(v)] = {"n_group": n_g, "base": r4(base), "events_in_population": ev,
                         "k_needed_by_lift": k_lift, "k_needed_by_min_num": MIN_NUM,
                         "binding": ("LIFT" if k_lift >= MIN_NUM else "MIN_NUM"),
                         "effective_lift_required": r4(need / n_g - base),
                         "required_share_of_all_events": r4(need / ev) if ev else None,
                         "possible": possible}
        verdicts.append(possible)
    return {"by_vintage": per_v, "all_possible": all(verdicts)}


reach_cache, reach_summary = {}, {}
for pop in POPS:
    binding_min_num = impossible = empty = 0
    eff_req, gsz, share = [], [], []
    for key in pair_keys[pop]:
        rr = reach_of(pop, key)
        reach_cache[(pop, key)] = rr
        bv = rr["by_vintage"]
        if any(x.get("n_group", 0) == 0 for x in bv.values()):
            empty += 1
        if not rr["all_possible"]:
            impossible += 1
        for v in SIGN_VINTAGES:
            x = bv.get(str(v), {})
            if x.get("binding") == "MIN_NUM":
                binding_min_num += 1
            if x.get("effective_lift_required") is not None:
                eff_req.append(x["effective_lift_required"])
            if x.get("n_group") is not None:
                gsz.append(x["n_group"])
            if x.get("required_share_of_all_events") is not None:
                share.append(x["required_share_of_all_events"])
    gsz.sort(); eff_req.sort(); share.sort()
    reach_summary[pop] = {
        "n_pairs": len(pair_keys[pop]),
        "n_pairs_with_empty_group_somewhere": empty,
        "n_pairs_not_reachable": impossible,
        "n_pairs_reachable": len(pair_keys[pop]) - impossible,
        "cell_vintages_where_MIN_NUM_binds": binding_min_num,
        "cell_vintages_total": len(gsz),
        "group_size_percentiles": {"p10": pctl(gsz, 0.10), "p25": pctl(gsz, 0.25), "p50": pctl(gsz, 0.50),
                                   "p75": pctl(gsz, 0.75), "p90": pctl(gsz, 0.90),
                                   "min": (gsz[0] if gsz else None), "max": (gsz[-1] if gsz else None)},
        "effective_lift_required_percentiles": {"p50": pctl(eff_req, 0.50), "p90": pctl(eff_req, 0.90),
                                                "p99": pctl(eff_req, 0.99),
                                                "max": (eff_req[-1] if eff_req else None)},
        "required_share_of_all_destroy_events_percentiles": {
            "p50": pctl(share, 0.50), "p90": pctl(share, 0.90), "max": (share[-1] if share else None)},
    }
reach_summary["_how_to_read"] = (
    "破壊の base は 5.8-8.1% しかないので、勝者側(21-24%)と同じ 0.15 の線でも**要求される群の破壊率は"
    "base の3倍前後**になる。しかも2本積は群が n/16 前後まで縮むので **MIN_NUM(5社) が LIFT(0.15) より"
    "強く縛る組が多発する**（v2の教訓: 線は0.15と書いてあるのに実効的にはもっと高い線が課される）。"
    "required_share_of_all_destroy_events は『母集団の全破壊事象の何割をその群に集めれば通るか』——"
    "1.0 を超える組は算術的に不可能。")

# ────────────────────────────── ゲート4: 業種(sic2)調整 ──────────────────────────────
def mh_risk_diff_pair(v, pop, key, Yint=None):
    d = PAIRMASK.get((pop, key))
    if not d or v not in d:
        return None
    gm, _ = d[v]
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for r in pop_rows(v, pop):
        s = r.get("sic2")
        if not s:
            continue
        i = tick_idx[r["ticker"]]
        ing = (gm >> (N_T - 1 - i)) & 1
        y = 1 if r.get("destroy") else 0
        dd = strata[s]
        if ing:
            dd[0] += 1; dd[1] += y
        else:
            dd[2] += 1; dd[3] += y
    numr = den = 0.0
    used = drop = 0
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


# ────────────────────────────── ゲート5: irr の影でないか（設計10） ──────────────────────────────
# ★破壊側では層内検定が構造的に不可能。まずその事実を測って出す。
irr_stratum = {}
for pop in POPS_ALL:
    for v in ALL_VINTAGES:
        R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
        hi = [r for r in R if r["irr"] >= 70]
        ev = sum(1 for r in hi if r.get("destroy"))
        irr_stratum[f"{pop}|{v}"] = {
            "n_rows_with_irr": len(R), "n_irr_ge70": len(hi), "destroy_events_in_stratum": ev,
            "stratified_test_reachable": (len(hi) >= 20 and ev >= MIN_NUM),
            "why": (None if (len(hi) >= 20 and ev >= MIN_NUM)
                    else f"irr>=70 の層の破壊事象が {ev} 件で分子>=5 に届かない"
                    if len(hi) >= 20 else f"irr>=70 の行が {len(hi)} 行しかない"),
        }
irr_stratum["_conclusion"] = (
    "**破壊側では、どのビンテージでも irr>=70 の層内検定が到達不能**"
    "（層の破壊事象が 2013:1 / 2015:1 / 2018:0）。層内 lift が 0 と出ても"
    "『差が消えた』のではなく**測れていない**。0件を発見と読まない（絶対のルール7の同族）。"
    "→ ゲート5は直交（|rho|<0.15）でのみ通し、直交とも言えなければ**判定不能**（不合格ではない）。")


def irr_control_pair(v, pop, key):
    d = PAIRMASK.get((pop, key))
    if not d or v not in d:
        return {"status": "このビンテージで測れない", "route": None}
    gm, mm = d[v]
    R = [r for r in pop_rows(v, pop) if r.get("irr") is not None]
    res = {"vintage": v, "n_with_irr": len(R),
           "n_irr_ge70": sum(1 for r in R if r["irr"] >= 70),
           "destroy_events_in_irr_ge70": sum(1 for r in R if r["irr"] >= 70 and r.get("destroy"))}
    if len(R) < 20:
        res["status"] = f"irr の読解がこのビンテージ・母集団で {len(R)} 行しかなく判定不能"
        res["route"] = None
        return res
    xs, ys = [], []
    for r in R:
        i = tick_idx[r["ticker"]]
        if (mm >> (N_T - 1 - i)) & 1:
            xs.append(float((gm >> (N_T - 1 - i)) & 1))
            ys.append(float(r["irr"]))
    rho = spearman(xs, ys) if len(xs) >= 20 else None
    n_in_group_with_irr = int(sum(xs))
    res["n_rows_for_rho"] = len(xs)
    res["n_group_rows_with_irr_read"] = n_in_group_with_irr
    res["corr_group_vs_irr"] = r4(rho)
    res["orthogonal_hint"] = (None if rho is None else abs(rho) < LIFT)
    # ★rho が None の理由を測って書く。『直交とも言えない』は
    #   (a)相関が実際に高い と (b)そもそも群に irr の読解が一行も無い を混ぜてはいけない。
    if rho is None:
        if len(xs) < 20:
            res["rho_status"] = f"両変数が可測かつ irr 読解のある行が {len(xs)} 行しかない"
        elif n_in_group_with_irr == 0:
            res["rho_status"] = ("**群に irr の読解が一行も無い**（この群は小型・低利益率に寄っており、"
                                 "irr の読解は質の高い社に費やされた）＝相関が高いのではなく**重なりが無い**")
        elif n_in_group_with_irr == len(xs):
            res["rho_status"] = "群が irr 読解のある行を全部含む＝分散ゼロで相関が定義できない"
        else:
            res["rho_status"] = "分散ゼロ（irr の値が全行で同一）"
    else:
        res["rho_status"] = "computed"
    res["stratified_test_reachable"] = (res["n_irr_ge70"] >= 20
                                        and res["destroy_events_in_irr_ge70"] >= MIN_NUM)
    if res["stratified_test_reachable"]:
        hi = [r for r in R if r["irr"] >= 70]
        base = rate(sum(1 for r in hi if r.get("destroy")), len(hi))
        g = [r for r in hi if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
        kg = sum(1 for r in g if r.get("destroy"))
        res["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g), "k": kg,
                           "p_group": r4(rate(kg, len(g))),
                           "lift": r4(None if not g else rate(kg, len(g)) - base)}
        res["route"] = "stratified"
    else:
        res["irr_ge70"] = {"status": "層内検定は到達不能（上の irr_stratum_reachability を見よ）。"
                                     "**0件を『差が消えた』と読まない**"}
        res["route"] = "orthogonality_only"
    return res


# ────────────────────────────── 全組を測る ──────────────────────────────
CIRC_QUALITY = {"f2_fcfpos5": "この母集団の定義そのもの（fcfpos5==5 で定数化・lift は構造的に0）",
                "f2_opm": "この母集団の定義に使われている（opm>=10% で下側が切り落とされている）"}

results = []
for pop in POPS:
    for key in pair_keys[pop]:
        (va, ca), (vb, cb) = key
        per_v = {v: measure_pair(pop, key, v, A0, D0) for v in ALL_VINTAGES}
        got3 = [per_v[v] for v in SIGN_VINTAGES if per_v.get(v) and per_v[v]["lift"] is not None]
        n_empty3 = sum(1 for v in SIGN_VINTAGES if per_v.get(v) and per_v[v]["lift"] is None)
        ent = {
            "population": pop, "var_a": va, "cut_a": ca, "var_b": vb, "cut_b": cb,
            "label": f"{va}[{ca}] ∧ {vb}[{cb}]",
            "origin": pair_origin[pop][key],
            "by_vintage": {str(v): (None if not per_v.get(v) else {
                "n_pop": per_v[v]["n_pop"], "destroy_events_in_pop": per_v[v]["k_pop"],
                "p_base": r4(per_v[v]["p_pop"]),
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
            ent["coverage_both_min"] = None
            ent["empty_group_vintages"] = n_empty3
        results.append(ent)

# 各脚の単独維持lift（設計9: 増分）
leg_cache = {}


def leg_maintained(pop, var, cut):
    k = (pop, var, cut)
    if k in leg_cache:
        return leg_cache[k]
    ml = uni_maintained(pop, var, cut, A0, D0, SIGN_VINTAGES)
    val = (ml["min_abs"] * ml["sign"]) if ml else 0.0
    leg_cache[k] = val
    return val


for ent in results:
    la = leg_maintained(ent["population"], ent["var_a"], ent["cut_a"])
    lb = leg_maintained(ent["population"], ent["var_b"], ent["cut_b"])
    ent["leg_maintained_lift_a"] = r4(la)
    ent["leg_maintained_lift_b"] = r4(lb)
    best_leg = max(la, lb)
    ent["best_leg_maintained_lift"] = r4(best_leg)
    if ent.get("maintained_lift") is not None and ent.get("sign") == 1:
        ent["lift_increment_vs_best_leg"] = r4(ent["maintained_lift"] - best_leg)
    else:
        ent["lift_increment_vs_best_leg"] = None


# ────────────────────────────── 判定（prereg の5条件・勝者側とまったく同じ順序） ──────────────────────────────
def verdict_of(ent):
    pop = ent["population"]
    if pop == "P_quality":
        for var in (ent["var_a"], ent["var_b"]):
            if var in CIRC_QUALITY:
                return {"verdict": "判定不能", "reason": f"母集団の定義に使われている変数を含む＝{CIRC_QUALITY[var]}",
                        "gate_failed_at": "circularity"}
    if not pop_decidability[pop]["decidable"]:
        return {"verdict": "判定不能",
                "reason": "母集団の破壊事象が分子>=5 に届かないビンテージがある＝測る前から判定不能",
                "gate_failed_at": "population_events"}
    if ent.get("sign_stable_161718") is None:
        return {"verdict": "判定不能",
                "reason": f"この切り方で群が空になるビンテージがある（{ent.get('empty_group_vintages')}件）",
                "gate_failed_at": "empty_group"}
    rr = reach_cache[(pop, ((ent["var_a"], ent["cut_a"]), (ent["var_b"], ent["cut_b"])))]
    if not rr["all_possible"]:
        bad = [v for v in SIGN_VINTAGES if not rr["by_vintage"].get(str(v), {}).get("possible")]
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
    if ic.get("route") == "stratified":
        ok = abs(ic["irr_ge70"]["lift"]) >= LIFT or ic.get("orthogonal_hint") is True
        if not ok:
            return {"verdict": "不合格", "reason": "irr>=70 層内で差が消え、かつ irr と直交でもない＝irr の影",
                    "gate_failed_at": "not_irr_shadow", "mh": mh, "irr": ic}
    else:
        # ★層内検定が到達不能。0件を『差が消えた』と読まない＝直交でのみ通し、
        #   直交と言えなければ不合格ではなく判定不能。
        if ic.get("orthogonal_hint") is not True:
            return {"verdict": "判定不能",
                    "reason": ("irr>=70 層内の破壊事象が分子5に届かず層内検定が到達不能で、"
                               "かつ直交も測れない／直交でもない＝irr の影かどうかを決められない。"
                               f"内訳: {ic.get('rho_status')}"),
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
    base_ref = rate(sum(1 for r in pop_rows(2018, pop) if r.get("destroy")), n_ref)
    power[pop] = {"n_pop_2018": n_ref, "base_2018": r4(base_ref), "at_group_sizes": {}}
    for lbl in ("p25", "p50", "p75"):
        g = gp[lbl]
        if not g:
            continue
        power[pop][f"at_group_sizes"][f"{lbl}(n_group={g})"] = {
            str(L): power_sim(n_ref, g, base_ref, L) for L in (0.15, 0.20, 0.30)}
power["_how_to_read"] = (
    "**破壊側は勝者側より構造的に検出力が低い**——事象が母集団の6-8%しかないので、"
    "同じ群の大きさでも分子の分散が支配的になる。three_independent が下限・single_vintage が上限"
    "（3ビンテージが完全に同じ実現なら1回引ければ3回引ける）。"
    "この数字が低いなら、『合格ゼロ』は『効果が無い』ではなく『掴める装置ではなかった』も含む。")

# ────────────────────────────── 偽陽性率（多重検定の値札） ──────────────────────────────
FLAT = []
for pop in POPS:
    for key in pair_keys[pop]:
        d = PAIRMASK[(pop, key)]
        if all(v in d for v in SIGN_VINTAGES):
            FLAT.append((pop, key, [d[v] for v in SIGN_VINTAGES]))

POPM3 = {pop: [POPMASK[(v, pop)] for v in SIGN_VINTAGES] for pop in POPS}

STRATA = {}
for v in SIGN_VINTAGES:
    for pop in POPS:
        d = defaultdict(lambda: [0] * N_T)
        for r in pop_rows(v, pop):
            s = r.get("sic2")
            if s:
                d[s][tick_idx[r["ticker"]]] = 1
        STRATA[(v, pop)] = [bits_to_int(b) for b in d.values()]

IRR70 = {}
for pop in POPS:
    bits = [0] * N_T
    for r in pop_rows(2018, pop):
        if r.get("irr") is not None and r["irr"] >= 70:
            bits[tick_idx[r["ticker"]]] = 1
    IRR70[pop] = bits_to_int(bits)

# 直交ヒントは結果ラベルに依らない＝置換で不変。先に計算する。
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


def mh_from_masks(gm, pm, strata, a, y):
    numr = den = 0.0
    for sm in strata:
        g1 = gm & sm & a
        n1 = g1.bit_count()
        allsm = pm & sm & a
        n0 = allsm.bit_count() - n1
        if n1 < 3 or n0 < 3:
            continue
        k1 = (g1 & y).bit_count()
        k0 = (allsm & y).bit_count() - k1
        wgt = n1 * n0 / (n1 + n0)
        numr += wgt * (k1 / n1 - k0 / n0)
        den += wgt
    return (numr / den) if den else None


def run_procedure(Aint, Yint, thresh=LIFT, base="pop", levels=False):
    """置換後の outcome で prereg のゲートを順に当て、各段を通る組の数を返す。
    L3 = lift>=0.15 ∧ 分子>=5 ∧ 3ビンテージ符号不変 / L4 = +sic2(MH) / L5 = +irr（破壊側は直交のみ）"""
    A3 = [Aint[v] for v in SIGN_VINTAGES]
    Y3 = [Yint[v] for v in SIGN_VINTAGES]
    popbase = {}
    for pop in POPS:
        arr = []
        for i in range(3):
            pm = POPM3[pop][i]
            npop = (pm & A3[i]).bit_count()
            arr.append(((pm & Y3[i]).bit_count() / npop) if npop else None)
        popbase[pop] = arr
    hits3, best = [], 0.0
    for (pop, key, masks) in FLAT:
        ok, signs, mn = True, set(), 1e9
        for i in range(3):
            gm, mm = masks[i]
            a, y = A3[i], Y3[i]
            ng = (gm & a).bit_count()
            if ng == 0:
                ok = False
                break
            kg = (gm & y).bit_count()
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
                b = (mm & y).bit_count() / nm
            if b is None:
                ok = False
                break
            lift = kg / ng - b
            signs.add(1 if lift > 0 else -1)
            if len(signs) > 1:
                ok = False
                break
            mn = min(mn, abs(lift))
        if ok and len(signs) == 1:
            best = max(best, mn)
            if mn >= thresh:
                hits3.append((pop, key, masks))
    if not levels:
        return len(hits3), best
    hits4 = []
    for (pop, key, masks) in hits3:
        good = True
        for i, v in enumerate(SIGN_VINTAGES):
            gm, _ = masks[i]
            d = mh_from_masks(gm, POPM3[pop][i], STRATA[(v, pop)], A3[i], Y3[i])
            if d is None or abs(d) < LIFT:
                good = False
                break
        if good:
            hits4.append((pop, key, masks))
    hits5 = 0
    for (pop, key, masks) in hits4:
        # 破壊側は層内検定が到達不能なので、観測側と同じく直交だけを合格経路にする
        if ORTHO.get((pop, key)) is True:
            hits5 += 1
    return len(hits3), best, len(hits4), hits5


def perm_int(bits, sigma):
    return int("".join("1" if bits[sigma[j]] else "0" for j in range(N_T)), 2)


sic_of, sic_conflict = {}, 0
for r in ANA:
    i = tick_idx[r["ticker"]]
    s = r.get("sic2") or "_none"
    if i in sic_of and sic_of[i] != s:
        sic_conflict += 1
    sic_of[i] = s
_g = defaultdict(list)
for i in range(N_T):
    _g[sic_of.get(i, "_none")].append(i)
SIC_GROUPS = list(_g.values())


def shuffle_within_sector(sigma):
    for g in SIC_GROUPS:
        p = g[:]
        rnd.shuffle(p)
        for j, idx in enumerate(g):
            sigma[idx] = p[j]
    return sigma


# 種の選定からやり直す帰無（選抜の代金を払う）
ALLPAIR = {}
for pop in POPS:
    ALLPAIR[pop] = {}
    for i, va in enumerate(CANDIDATES):
        for vb in CANDIDATES[i + 1:]:
            for ca in CUTNAMES:
                for cb in CUTNAMES:
                    key = tuple(sorted([(va, ca), (vb, cb)]))
                    if key in ALLPAIR[pop]:
                        continue
                    d = {}
                    for v in SIGN_VINTAGES:
                        m = pair_masks(v, pop, key)
                        if m:
                            d[v] = m
                    if len(d) == 3:
                        ALLPAIR[pop][key] = [d[v] for v in SIGN_VINTAGES]
N_PAIR_SPACE = {pop: len(ALLPAIR.get(pop, {})) for pop in POPS}


def uni_maint_bits(pop, var, cut, A3, Y3, popbase):
    signs, mn = set(), 1e9
    for i in range(3):
        e = VARMASK.get((SIGN_VINTAGES[i], pop, var))
        if not e:
            return None
        gm = e["cuts"][cut]
        ng = (gm & A3[i]).bit_count()
        if ng == 0:
            return None
        lift = (gm & Y3[i]).bit_count() / ng - popbase[pop][i]
        signs.add(1 if lift > 0 else -1)
        if len(signs) > 1:
            return None
        mn = min(mn, abs(lift))
    return (mn, signs.pop())


def run_reselect(Aint, Yint, thresh=LIFT):
    """種の選定からやり直す帰無。**物語の組は固定で毎回足す**（観測側と同じ検定を払う）。"""
    A3 = [Aint[v] for v in SIGN_VINTAGES]
    Y3 = [Yint[v] for v in SIGN_VINTAGES]
    popbase = {}
    for pop in POPS:
        arr = []
        for i in range(3):
            pm = POPM3[pop][i]
            npop = (pm & A3[i]).bit_count()
            arr.append(((pm & Y3[i]).bit_count() / npop) if npop else 0.0)
        popbase[pop] = arr
    hits, best, ntests = 0, 0.0, 0
    for pop in POPS:
        scored = []
        for var in CANDIDATES:
            bb = None
            for cut in CUTNAMES:
                r = uni_maint_bits(pop, var, cut, A3, Y3, popbase)
                if not r or r[1] != 1:
                    continue
                if bb is None or r[0] > bb[0]:
                    bb = (r[0], cut)
            if bb:
                scored.append((bb[0], var, bb[1]))
        scored.sort(reverse=True)
        seen = set()
        for _s, var, cut in scored[:N_SEEDS]:
            for sc in side_cuts("high" if cut in HIGH_SIDE else "low"):
                for var2 in CANDIDATES:
                    if var2 == var:
                        continue
                    for c2 in CUTNAMES:
                        seen.add(tuple(sorted([(var, sc), (var2, c2)])))
        for key in forced_keys:              # 設計6: 物語の組の代金も帰無に払わせる
            if key[0][0] != key[1][0]:
                seen.add(key)
        for key in sorted(seen):
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
                kg = (gm & Y3[i]).bit_count()
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


obs3, obs_max, obs4, obs5 = run_procedure(A0, D0, levels=True)
_obs_hits_m, obs_max_m = run_procedure(A0, D0, base="meas")

RELAX = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20]
perm_hits, perm_max, perm_max_m, perm_h4, perm_h5 = [], [], [], [], []
rs_hits, rs_max, rs_ntests = [], [], []
ws_hits, ws_max, wr_hits, wr_max = [], [], [], []
relax_any = {t: 0 for t in RELAX}
sigma = list(range(N_T))
for it in range(N_PERM):
    rnd.shuffle(sigma)
    Ai = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Di = {v: perm_int(D_bits[v], sigma) for v in SIGN_VINTAGES}
    h3, mx, h4, h5 = run_procedure(Ai, Di, levels=True)
    perm_hits.append(h3); perm_h4.append(h4); perm_h5.append(h5); perm_max.append(mx)
    for t in RELAX:
        if mx >= t:
            relax_any[t] += 1
    _h2, mx2 = run_procedure(Ai, Di, base="meas")
    perm_max_m.append(mx2)
    rh, rmx, rn = run_reselect(Ai, Di)
    rs_hits.append(rh); rs_max.append(rmx); rs_ntests.append(rn)
    shuffle_within_sector(sigma)
    Aw = {v: perm_int(A_bits[v], sigma) for v in SIGN_VINTAGES}
    Dw = {v: perm_int(D_bits[v], sigma) for v in SIGN_VINTAGES}
    wh, wmx, _w4, _w5 = run_procedure(Aw, Dw, levels=True)
    ws_hits.append(wh); ws_max.append(wmx)
    wr_h, wr_mx, _wn = run_reselect(Aw, Dw)
    wr_hits.append(wr_h); wr_max.append(wr_mx)

srt = sorted(perm_max)
fpr = {
    "n_permutations": N_PERM,
    "n_tests_in_procedure": len(FLAT),
    "n_tests_winner_pair_for_comparison": len(json.load(open(os.path.join(OUT, "hist_wd_win_pair.json"),
                                                            encoding="utf-8"))["all_pairs"])
    if os.path.exists(os.path.join(OUT, "hist_wd_win_pair.json")) else None,
    "null_construction": ("特徴量側（母集団・可測・群）は固定し、outcome の束(has_outcome∧window_full, destroy)を"
                          "ティッカーごとまとめて置換する。ビンテージ間の outcome 相関・欠測構造を保ったまま、"
                          "特徴量↔outcome だけを壊せる。勝者側の道具と同一の帰無。"),
    "levels": {"L3": "lift>=0.15 ∧ 分子>=5 ∧ 3ビンテージ符号不変",
               "L4": "L3 + 同一sic2内(MH)でも|差|>=0.15",
               "L5": "L4 + irr と直交（**破壊側は層内検定が到達不能なのでこの経路しかない**）"},
    "P_at_least_one_pass_by_level": {
        "L3": r4(sum(1 for h in perm_hits if h > 0) / N_PERM),
        "L4": r4(sum(1 for h in perm_h4 if h > 0) / N_PERM),
        "L5": r4(sum(1 for h in perm_h5 if h > 0) / N_PERM)},
    "mean_passes_per_permutation_by_level": {
        "L3": r4(sum(perm_hits) / N_PERM), "L4": r4(sum(perm_h4) / N_PERM),
        "L5": r4(sum(perm_h5) / N_PERM)},
    "max_passes_in_a_permutation_by_level": {"L3": max(perm_hits), "L4": max(perm_h4), "L5": max(perm_h5)},
    "observed_passes_by_level": {"L3": obs3, "L4": obs4, "L5": obs5},
    "empirical_p_of_observed_pass_count": {
        "L3": r4(sum(1 for h in perm_hits if h >= obs3) / N_PERM),
        "L4": r4(sum(1 for h in perm_h4 if h >= obs4) / N_PERM),
        "L5": r4(sum(1 for h in perm_h5 if h >= obs5) / N_PERM)},
    "null_distribution_of_max_statistic": {
        "statistic": f"{len(FLAT)}検定のうち最大の『符号が揃ったうえでの3ビンテージ最小|lift|』",
        "p50": pctl(srt, 0.50), "p90": pctl(srt, 0.90), "p95": pctl(srt, 0.95), "p99": pctl(srt, 0.99),
        "max_over_permutations": r4(max(perm_max)),
        "observed_in_real_data": r4(obs_max),
        "empirical_p_of_observed": r4(sum(1 for m in perm_max if m >= obs_max) / N_PERM)},
    "fpr_at_relaxed_thresholds": {
        "note": "**事前登録の外・診断専用**。合否には数えない。線を緩めたときの偽陽性率。",
        "P_at_least_one_pass_by_threshold": {str(t): r4(relax_any[t] / N_PERM) for t in RELAX}},
    "null_with_seed_reselection": {
        "note": ("**こちらが正しい帰無**。上の帰無は『実データで選んだ10本の種』を固定したまま結果だけ壊すので、"
                 "**種を選ぶ段の選抜代を払っていない**。物語の組(FORCED_PAIRS)は結果を見る前に登録したので"
                 "帰無でも毎回固定で足している。"),
        "pair_space_available": N_PAIR_SPACE,
        "mean_tests_per_permutation": r4(sum(rs_ntests) / N_PERM),
        "P_at_least_one_pass_L3": r4(sum(1 for h in rs_hits if h > 0) / N_PERM),
        "mean_passes_per_permutation_L3": r4(sum(rs_hits) / N_PERM),
        "max_passes_in_a_permutation_L3": max(rs_hits),
        "null_max_statistic": {"p50": pctl(sorted(rs_max), 0.50), "p90": pctl(sorted(rs_max), 0.90),
                               "p95": pctl(sorted(rs_max), 0.95), "p99": pctl(sorted(rs_max), 0.99),
                               "max": r4(max(rs_max)), "observed_in_real_data": r4(obs_max),
                               "empirical_p_of_observed": r4(sum(1 for m in rs_max if m >= obs_max) / N_PERM)},
        "empirical_p_of_observed_pass_count_L3": r4(sum(1 for h in rs_hits if h >= obs3) / N_PERM)},
    "null_within_sector": {
        "note": ("**業種の中だけで結果を入れ替えた帰無**。破壊が業種で固まって起きていれば"
                 "（実測でこの窓は半導体資本財に極端に有利＝逆に不利な業種がある）、"
                 "『群がその業種の形をしている』だけで lift が出る。業種で説明できる分は帰無にも残るので、"
                 "ここを超えて初めて『指標が分けた』と言える。"),
        "n_sector_groups": len(SIC_GROUPS), "ticker_sic_conflicts": sic_conflict,
        "fixed_seeds": {
            "P_at_least_one_pass_L3": r4(sum(1 for h in ws_hits if h > 0) / N_PERM),
            "mean_passes_per_permutation_L3": r4(sum(ws_hits) / N_PERM),
            "max_passes_in_a_permutation_L3": max(ws_hits),
            "null_max_statistic": {"p50": pctl(sorted(ws_max), 0.50), "p95": pctl(sorted(ws_max), 0.95),
                                   "p99": pctl(sorted(ws_max), 0.99), "max": r4(max(ws_max)),
                                   "observed_in_real_data": r4(obs_max),
                                   "empirical_p_of_observed": r4(sum(1 for m in ws_max if m >= obs_max) / N_PERM)}},
        "with_seed_reselection": {
            "P_at_least_one_pass_L3": r4(sum(1 for h in wr_hits if h > 0) / N_PERM),
            "mean_passes_per_permutation_L3": r4(sum(wr_hits) / N_PERM),
            "max_passes_in_a_permutation_L3": max(wr_hits),
            "null_max_statistic": {"p50": pctl(sorted(wr_max), 0.50), "p95": pctl(sorted(wr_max), 0.95),
                                   "p99": pctl(sorted(wr_max), 0.99), "max": r4(max(wr_max)),
                                   "observed_in_real_data": r4(obs_max),
                                   "empirical_p_of_observed": r4(sum(1 for m in wr_max if m >= obs_max) / N_PERM)}}},
    "supplementary_null_measurable_base": {
        "note": "**事前登録の外・診断専用**。分母を『2本とも可測』な部分集合にした版。",
        "observed_in_real_data": r4(obs_max_m),
        "null_p50": pctl(sorted(perm_max_m), 0.50), "null_p95": pctl(sorted(perm_max_m), 0.95),
        "null_p99": pctl(sorted(perm_max_m), 0.99), "null_max": r4(max(perm_max_m)),
        "empirical_p_of_observed": r4(sum(1 for m in perm_max_m if m >= obs_max_m) / N_PERM)},
}

# ────────────────────────────── 陽性対照（注入検査） ──────────────────────────────
N_CTRL_REP = 20
positive_control = {}
for L in (0.30, 0.25, 0.20, 0.175, 0.16, 0.15):
    reps = []
    for _rep in range(N_CTRL_REP):
        ka, kb = "_ctrlA", "_ctrlB"
        pop = "P_full"
        ctrl_design = {}
        capped = False
        for v in ALL_VINTAGES:
            R = pop_rows(v, pop)
            n = len(R)
            hi_size = n - int(math.ceil(0.75 * n)) + 1
            g = max(2 * MIN_NUM, n // 16)
            base = rate(sum(1 for r in R if r.get("destroy")), n)
            want = max(MIN_NUM, int(round((base + L) * g)))
            evs = [i for i in range(n) if R[i].get("destroy")]
            non = [i for i in range(n) if not R[i].get("destroy")]
            rnd.shuffle(evs); rnd.shuffle(non)
            if want > len(evs):
                capped = True
            want = min(want, len(evs))
            group = set(evs[:want]) | set(non[:max(0, g - want)])
            rest = [i for i in range(n) if i not in group]
            rnd.shuffle(rest)
            need = max(0, hi_size - len(group))
            extraA = set(rest[:need])
            extraB = set(rest[need:need + need])
            a_hi, b_hi = group | extraA, group | extraB
            ctrl_design[str(v)] = {"n": n, "hi_size": hi_size, "g_target": len(group),
                                   "events_in_group": want, "events_available": len(evs),
                                   "base": r4(base), "capped_by_available_events": want < max(MIN_NUM, int(round((base + L) * g))),
                                   "intersection_is_group": (a_hi & b_hi) == group}
            for i, r in enumerate(R):
                r[ka] = (0.75 + rnd.random() * 0.25) if i in a_hi else rnd.random() * 0.74
                r[kb] = (0.75 + rnd.random() * 0.25) if i in b_hi else rnd.random() * 0.74
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
        pair_origin[pop][ckey] = "positive_control"
        per_v = {v: measure_pair(pop, ckey, v, A0, D0) for v in ALL_VINTAGES}
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
                     "injection_capped_somewhere": capped,
                     "injection_design": ({k: ctrl_design[k] for k in ("2016", "2017", "2018")}
                                          if _rep == 0 else None)})
        for v in ALL_VINTAGES:
            VARMASK.pop((v, pop, ka), None)
            VARMASK.pop((v, pop, kb), None)
        PAIRMASK.pop((pop, ckey), None)
        reach_cache.pop((pop, ckey), None)
        pair_origin[pop].pop(ckey, None)
        for r in rows_all:
            r.pop(ka, None); r.pop(kb, None)
    npass = sum(1 for x in reps if x["verdict"] == "合格")
    positive_control[f"true_lift={L}"] = {
        "n_repetitions": N_CTRL_REP, "pass_rate": r4(npass / N_CTRL_REP), "n_pass": npass,
        "failed_at_histogram": dict(Counter(x["gate_failed_at"] for x in reps if x["verdict"] != "合格")),
        "any_injection_capped": any(x["injection_capped_somewhere"] for x in reps),
        "median_observed_lift_2018": r4(sorted(x["observed_lifts_161718"][-1] for x in reps)[N_CTRL_REP // 2]),
        "example_repetition": reps[0]}
positive_control["_how_to_read"] = (
    "**2本積の経路そのもの**に真の効果を仕込み、同じ measure/verdict を通して合格が出る割合を測る。"
    "破壊側は事象が少ないので、仕込みたい分子が母集団の全事象数を超えることがある"
    "（any_injection_capped がその印）。合格率が低いなら『合格ゼロ』は効果の不在ではなく検出力の不足を含む。")

# ────────── 抜き取り検算（設計12: 合格の有無に関わらず・ビットマスクを一切使わない） ──────────
def row_level_measure(pop, va, ca, vb, cb, v):
    R = pop_rows(v, pop)
    if not R:
        return None

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
    k = sum(1 for r in g if r.get("destroy"))
    base = rate(sum(1 for r in R if r.get("destroy")), len(R))
    return {"n_pop": len(R), "n_group": len(g), "numerator": k,
            "lift": r4((k / len(g) - base) if g else None)}


spot_rng = random.Random(SEED + 1)
spot_targets = [e for e in results if e["verdict"] == "合格"]
spot_targets += [e for e in results if e["origin"] in ("forced", "seed+forced")]
pool = [e for e in results if e not in spot_targets]
spot_targets += spot_rng.sample(pool, min(N_SPOT_RANDOM, len(pool)))
spot = {"checked": 0, "mismatches": 0, "n_pairs_checked": len(spot_targets), "rows": [], "bad": []}
for e in spot_targets:
    per = {}
    for v in SIGN_VINTAGES:
        rl = row_level_measure(e["population"], e["var_a"], e["cut_a"], e["var_b"], e["cut_b"], v)
        bm = e["by_vintage"][str(v)]
        per[str(v)] = {"row_level": rl, "bitmask": bm}
        if rl is None or bm is None:
            continue
        for f in ("n_pop", "n_group", "numerator", "lift"):
            spot["checked"] += 1
            if rl[f] != bm[f]:
                spot["mismatches"] += 1
                spot["bad"].append({"label": e["label"], "vintage": v, "field": f,
                                    "row_level": rl[f], "bitmask": bm[f]})
    if len(spot["rows"]) < 12:
        spot["rows"].append({"label": e["label"], "population": e["population"],
                             "origin": e["origin"], "verdict": e["verdict"], "by_vintage": per})
spot["verdict"] = ("一致（AND の群も、行を直接数えた結果と同じ）" if spot["mismatches"] == 0
                   else "⚠不一致——結論を書いてはいけない")
spot["note"] = ("勝者側の道具は**合格した組だけ**を行レベルで数え直していたが、"
                "合格ゼロだと検算が0件になる。合格の有無に関わらず、"
                "物語の組＋乱択40組＋合格全部を数え直す。")


# ────────────────────────────── 群の中身・業種との対比 ──────────────────────────────
def thresholds(pop, key, v=2018):
    out = {}
    for (var, cut) in key:
        e = VARMASK.get((v, pop, var))
        if not e:
            continue
        q25, q50, q75 = e["q"]
        thr = {"上位1/4": (">=", q75), "下位1/4": ("<=", q25),
               "中央値超": (">", q50), "中央値以下": ("<=", q50)}[cut]
        out[var] = {"cut": cut, "operator": thr[0],
                    "threshold": (None if thr[1] is None else round(thr[1], 4)),
                    "q25": (None if q25 is None else round(q25, 4)),
                    "q50": (None if q50 is None else round(q50, 4)),
                    "q75": (None if q75 is None else round(q75, 4)),
                    "n_measurable": e["n_meas"], "distinct_values": e["distinct"]}
    return out


def group_profile(pop, key, v=2018):
    d = PAIRMASK.get((pop, key))
    if not d or v not in d:
        return None
    gm, _mm = d[v]
    rows = [r for r in pop_rows(v, pop) if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
    if not rows:
        return {"n": 0}
    sic = Counter(r.get("sic2") for r in rows)
    return {"n": len(rows), "sic2_top5": sic.most_common(5),
            "sic2_top3_share": r4(sum(c for _, c in sic.most_common(3)) / len(rows)),
            "n_with_irr_read": sum(1 for r in rows if r.get("irr") is not None),
            "destroyed": sorted(r["ticker"] for r in rows if r.get("destroy")),
            "sample_tickers": sorted(r["ticker"] for r in rows)[:25]}


def sector_benchmark(pop, key):
    d = PAIRMASK.get((pop, key))
    if not d or 2018 not in d:
        return None
    gm18, _ = d[2018]
    rows18 = [r for r in pop_rows(2018, pop) if (gm18 >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
    if not rows18:
        return None
    dom = Counter(r.get("sic2") for r in rows18 if r.get("sic2")).most_common(1)
    if not dom:
        return None
    dom = dom[0][0]
    out = {}
    for v in SIGN_VINTAGES:
        if v not in d:
            continue
        R = pop_rows(v, pop)
        gm, _mm = d[v]
        base = rate(sum(1 for r in R if r.get("destroy")), len(R))
        sec = [r for r in R if r.get("sic2") == dom]
        p_sec = rate(sum(1 for r in sec if r.get("destroy")), len(sec)) if sec else None
        ing = [r for r in R if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
        insec = [r for r in ing if r.get("sic2") == dom]
        p_insec = rate(sum(1 for r in insec if r.get("destroy")), len(insec)) if insec else None
        out[str(v)] = {"dominant_sic2": dom, "n_sector": len(sec), "p_sector": r4(p_sec),
                       "lift_of_sector_alone": r4(None if p_sec is None else p_sec - base),
                       "n_group_in_sector": len(insec), "p_group_in_sector": r4(p_insec),
                       "lift_of_pair_within_that_sector": r4(None if (p_insec is None or p_sec is None)
                                                             else p_insec - p_sec),
                       "share_of_group_in_that_sector": r4(rate(len(insec), len(ing)))}
    return out


def detail_of(e, with_profile=True):
    key = ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))
    vf = e["verdict_full"]
    d = {"label": e["label"], "population": e["population"], "origin": e["origin"],
         "verdict": e["verdict"], "verdict_reason": vf["reason"],
         "gate_failed_at": vf.get("gate_failed_at"),
         "maintained_lift": e["maintained_lift"],
         "maintained_lift_measurable_base": e["maintained_lift_meas"],
         "coverage_both_min": e["coverage_both_min"],
         "min_numerator_161718": e["min_numerator_161718"],
         "lift_increment_vs_best_leg": e["lift_increment_vs_best_leg"],
         "leg_maintained_lift_a": e["leg_maintained_lift_a"],
         "leg_maintained_lift_b": e["leg_maintained_lift_b"],
         "by_vintage": e["by_vintage"],
         "reachability": reach_cache.get((e["population"], key)),
         "thresholds_2018": thresholds(e["population"], key)}
    if with_profile:
        d["group_profile_2018"] = group_profile(e["population"], key)
        d["sector_benchmark"] = sector_benchmark(e["population"], key)
        d["sector_mh_161718"] = {str(v): mh_risk_diff_pair(v, e["population"], key) for v in SIGN_VINTAGES}
        d["irr_control_2018"] = irr_control_pair(2018, e["population"], key)
        d["irr_control_2015_diagnostic"] = irr_control_pair(2015, e["population"], key)
    return d


passers = [detail_of(e) for e in sorted([x for x in results if x["verdict"] == "合格"],
                                        key=lambda x: -(x["maintained_lift"] or 0))]

# ── 合格が実質いくつの「別々の発見」なのか（脚の重なり・同一列の別名を数える） ──
pass_legs = Counter()
for e in results:
    if e["verdict"] == "合格":
        pass_legs[f"{e['var_a']}[{e['cut_a']}]"] += 1
        pass_legs[f"{e['var_b']}[{e['cut_b']}]"] += 1
pass_varpairs = {f"{min(e['var_a'], e['var_b'])}×{max(e['var_a'], e['var_b'])}"
                 for e in results if e["verdict"] == "合格"}
pass_varpairs_canon = {f"{min(canon(e['var_a']), canon(e['var_b']))}×{max(canon(e['var_a']), canon(e['var_b']))}"
                       for e in results if e["verdict"] == "合格"}


# ────────── ★両裾の検査: この群は「壊れる」のか「振れる」のか ──────────
# 破壊率が上がる群が、同時に勝率も上げているなら、それは**破壊の指標ではなく分散の指標**。
# 同じ measure_pair に win のラベル(W0)を流すだけ＝新しい経路を作らない。
def pair_maintained(pop, key, Yint):
    signs, mn, per = set(), 1e9, {}
    for v in SIGN_VINTAGES:
        m = measure_pair(pop, key, v, A0, Yint)
        if not m or m["lift"] is None:
            return None
        per[str(v)] = {"n_pop": m["n_pop"], "events_in_pop": m["k_pop"], "p_base": r4(m["p_pop"]),
                       "n_group": m["n_group"], "numerator": m["numerator"],
                       "p_group": r4(m["p_group"]), "lift": r4(m["lift"])}
        signs.add(1 if m["lift"] > 0 else (-1 if m["lift"] < 0 else 0))
        mn = min(mn, abs(m["lift"]))
    stable = (len(signs) == 1 and 0 not in signs)
    return {"by_vintage": per, "sign_stable": stable,
            "sign": (list(signs)[0] if stable else None),
            "maintained_lift": r4(mn) if stable else 0.0}


# 勝者側の道具に同じ組があれば、そちらの数字とも突き合わせる（別実装での確認）
WIN_PAIR_PATH = os.path.join(OUT, "hist_wd_win_pair.json")
win_pair_idx = {}
if os.path.exists(WIN_PAIR_PATH):
    _wp = json.load(open(WIN_PAIR_PATH, encoding="utf-8"))
    for p in _wp["all_pairs"]:
        win_pair_idx[(p["population"], p["var_a"], p["cut_a"], p["var_b"], p["cut_b"])] = p


def leg_shape(pop, var, cut, v=2018):
    """切り方が実際に何%を切ったか（同値が多いと『上位1/4』が1/4にならない）。"""
    e = VARMASK.get((v, pop, var))
    if not e:
        return None
    n_g = e["cuts"][cut].bit_count()
    return {"n_measurable": e["n_meas"], "distinct_values": e["distinct"],
            "n_group": n_g, "realized_share_of_measurable": r4(rate(n_g, e["n_meas"])),
            "tie_degenerate": bool(abs(rate(n_g, e["n_meas"]) - (0.25 if "1/4" in cut else 0.5)) > 0.05)}


def sector_leave_one_out(pop, key, n_sectors=4):
    """★群の主業種を**母集団ごと外して**測り直す。
    MH は層の9割を落とすので弱い。業種内置換の帰無と合わせて、
    『この組はその業種を拾っているだけではないか』に実額で答える。"""
    d = PAIRMASK.get((pop, key))
    if not d or 2018 not in d:
        return None
    gm18, _ = d[2018]
    rows18 = [r for r in pop_rows(2018, pop) if (gm18 >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
    tops = [s for s, _c in Counter(r.get("sic2") for r in rows18 if r.get("sic2")).most_common(n_sectors)]
    out = {}
    for s in tops:
        per, ok = {}, True
        for v in SIGN_VINTAGES:
            if v not in d:
                ok = False
                break
            gm, _mm = d[v]
            R = [r for r in pop_rows(v, pop) if r.get("sic2") != s]
            if not R:
                ok = False
                break
            base = rate(sum(1 for r in R if r.get("destroy")), len(R))
            g = [r for r in R if (gm >> (N_T - 1 - tick_idx[r["ticker"]])) & 1]
            if not g:
                ok = False
                break
            k = sum(1 for r in g if r.get("destroy"))
            per[str(v)] = {"n_pop_ex": len(R), "base_ex": r4(base), "n_group_ex": len(g),
                           "numerator_ex": k, "p_group_ex": r4(k / len(g)),
                           "lift_ex": r4(k / len(g) - base)}
        if not ok:
            out[s] = {"status": "この業種を外すと測れない"}
            continue
        lifts = [per[str(v)]["lift_ex"] for v in SIGN_VINTAGES]
        stable = len({1 if x > 0 else -1 for x in lifts}) == 1
        out[s] = {"by_vintage": per,
                  "maintained_lift_excluding_this_sector": (r4(min(abs(x) for x in lifts)) if stable else 0.0),
                  "min_numerator_excluding": min(per[str(v)]["numerator_ex"] for v in SIGN_VINTAGES),
                  "still_meets_lift_and_min_num": bool(stable and lifts[-1] > 0
                                                       and min(abs(x) for x in lifts) >= LIFT
                                                       and min(per[str(v)]["numerator_ex"]
                                                               for v in SIGN_VINTAGES) >= MIN_NUM)}
    out["_how_to_read"] = ("その業種を母集団から丸ごと外しても線を保つなら、"
                           "『その業種を拾っているだけ』ではない。**MHより強い検査**"
                           "（MHは層の9割を落とすので通りやすい）。")
    return out


def both_tails(e):
    pop = e["population"]
    key = ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))
    dst = pair_maintained(pop, key, D0)
    wn = pair_maintained(pop, key, W0)
    reading = "測れない"
    if dst and wn:
        d_up = dst["sign_stable"] and dst["sign"] == 1 and dst["maintained_lift"] >= LIFT
        w_up = wn["sign_stable"] and wn["sign"] == 1 and wn["maintained_lift"] >= LIFT
        w_dn = wn["sign_stable"] and wn["sign"] == -1
        if d_up and w_up:
            reading = "★両裾＝分散の指標（壊れやすく、同時に勝ちやすい）。『破壊の指標』と読んではいけない"
        elif d_up and w_dn:
            reading = "★片側＝破壊を増やし、勝ちも減らす（純粋に悪い側の指標）"
        elif d_up:
            reading = "★破壊だけ上がる（勝ち側は3ビンテージで符号が揃わない＝動いていない）"
        else:
            reading = "破壊側の線に届いていない組"
    ref = win_pair_idx.get((pop, e["var_a"], e["cut_a"], e["var_b"], e["cut_b"]))
    x = {"destroy": dst, "win": wn, "reading": reading,
         "leg_a_shape_2018": leg_shape(pop, e["var_a"], e["cut_a"]),
         "leg_b_shape_2018": leg_shape(pop, e["var_b"], e["cut_b"])}
    if ref:
        x["winner_pair_tool_says"] = {
            "maintained_lift": ref["maintained_lift"], "sign": ref["sign"],
            "verdict": ref["verdict"],
            "agrees_with_my_win_measure": (None if not wn else
                                           (abs((ref["maintained_lift"] or 0) - wn["maintained_lift"]) < 1e-9
                                            and (ref["sign"] == wn["sign"] or wn["maintained_lift"] == 0.0))),
            "note": "**別実装（勝者側の道具）**が同じ組について出した勝ち側の数字。食い違えばどちらかが壊れている"}
    return x


# ────────── ゲートの通過段（L3まで来た組が、その後どうなったか） ──────────
def reached_l3(e):
    if e.get("sign_stable_161718") is not True or e.get("sign") != 1:
        return False
    if e.get("min_numerator_161718") is None or e["min_numerator_161718"] < MIN_NUM:
        return False
    if (e.get("maintained_lift") or 0) < LIFT:
        return False
    rr = reach_cache.get((e["population"], ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))))
    return bool(rr and rr["all_possible"])


cascade = []
for e in sorted([x for x in results if reached_l3(x)], key=lambda x: -(x["maintained_lift"] or 0)):
    key = ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))
    ic = irr_control_pair(2018, e["population"], key)
    cascade.append({
        "label": e["label"], "population": e["population"], "origin": e["origin"],
        "canonical_variable_pair": f"{min(canon(e['var_a']), canon(e['var_b']))}×"
                                   f"{max(canon(e['var_a']), canon(e['var_b']))}",
        "maintained_lift": e["maintained_lift"],
        "min_numerator_161718": e["min_numerator_161718"],
        "lift_increment_vs_best_leg": e["lift_increment_vs_best_leg"],
        "verdict": e["verdict"], "gate_failed_at": e["verdict_full"].get("gate_failed_at"),
        "reason": e["verdict_full"]["reason"],
        "sector_mh": {str(v): mh_risk_diff_pair(v, e["population"], key) for v in SIGN_VINTAGES},
        "irr_rho_2018": ic.get("corr_group_vs_irr"), "irr_orthogonal": ic.get("orthogonal_hint"),
        "irr_route": ic.get("route"),
        "both_tails": both_tails(e),
        "sector_benchmark_2018": (sector_benchmark(e["population"], key) or {}).get("2018"),
        "sector_leave_one_out": sector_leave_one_out(e["population"], key),
        "group_profile_2018": group_profile(e["population"], key),
        "thresholds_2018": thresholds(e["population"], key),
    })
cascade_summary = {
    "n_reached_L3": len(cascade),
    "n_distinct_canonical_pairs_at_L3": len({c["canonical_variable_pair"] for c in cascade}),
    "fate": dict(Counter(f'{c["verdict"]}({c["gate_failed_at"]})' if c["gate_failed_at"] else c["verdict"]
                         for c in cascade)),
    "note": ("**L3(lift∧分子∧符号不変)まで来た組を全部並べる**。合格だけを見ると、"
             "『業種で落ちた組』と『irr で決められなかった組』が見えなくなる。"
             "判定不能は不合格ではない——決められなかったという事実そのものが結果。"),
}

for p in passers:
    e = next(x for x in results if x["label"] == p["label"] and x["population"] == p["population"])
    p["both_tails"] = both_tails(e)
    p["sector_leave_one_out"] = sector_leave_one_out(
        e["population"], ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"])))


# ────────── 変数の読み（『上位1/4』が実際にいくらなのか・欄の癖） ──────────
READINGS = {
    "f2_rnd_r": "R&D費 ÷ 売上。**母集団の半分超がゼロ**（q25=q50=0）なので『上位1/4』は実質『R&Dを売上の4.6%以上使っている社』",
    "f2_netiss_r": "Σ(株式発行−自社株買い) ÷ 売上。**正が純希薄化**。q75 が 0.0 なので『上位1/4』は実質『**純発行側にいる（自社株買いで返していない）社**』",
    "f2_rev": "直近FYの売上（実額）。size_rev と**完全に同一の列**",
    "size_rev": "f2_rev と同一（別名）",
    "f2_opm": "営業利益率。『下位1/4』は 3.8% 以下＝薄利・赤字帯",
    "f2_accr": "(純利益 − 営業CF) ÷ 総資産。**低い＝純利益が営業CFを大きく下回る**＝減損等の非現金損失が乗っている側。『高い＝利益が現金化していない』の逆側であることに注意",
    "f2_conv5": "Σ5年FCF ÷ Σ5年純利益。⚠**分母が負になると比の符号が反転する**ので、『低い』は『現金化しない』と『赤字』を混ぜている。この欄の読みは弱い",
    "f2_gw_r": "のれん ÷ 総資産。のれんを一度も報告しない社は 0（欠測ではない）",
    "f2_intcov": "営業利益 ÷ 支払利息。**利息ゼロ・タグ無しは欠測**（無借金が『カバレッジ低』に化けない）。被覆は7割",
    "f2_fcfpos5": "5年のうちFCFが黒字だった年数(0-5)。離散なので分位が同値で潰れやすい",
    "f2_opmD5": "営業利益率の5年差(pt)。『上位1/4』は+3.6pt以上の改善",
    "f2_capex_r": "設備投資 ÷ 売上",
    "f2_cash_r": "現金 ÷ 総資産",
    "f2_cagr5": "売上5年CAGR",
    "f2_payout5": "(配当+自社株買い) ÷ Σ5年純利益",
    "f2_sga_r": "販管費 ÷ 売上（**合算タグのみ**＝分割報告社は欠測。被覆58%）",
    "f2_aturn": "売上 ÷ 総資産",
    "f2_gm": "粗利率",
    "f2_accel": "成長の加速度（直近2年CAGR − その前3年CAGR）",
    "f2_streak_rev": "5年のうち増収だった年数(0-4)",
    "f2_streak_opm": "5年のうち営業利益率が改善した年数(0-4)",
}
used_vars = sorted({v for c in cascade for v in (c["label"].split("[")[0],)} |
                   {m["var_a"] for m in forced_meta} | {m["var_b"] for m in forced_meta} |
                   {e["var_a"] for e in results if reached_l3(e)} |
                   {e["var_b"] for e in results if reached_l3(e)})
variable_readings = {}
for var in used_vars:
    e = VARMASK.get((2018, "P_full", var))
    if not e:
        continue
    vals = sorted(num(r.get(var)) for r in pop_rows(2018, "P_full") if num(r.get(var)) is not None)
    variable_readings[var] = {
        "reading": READINGS.get(var, "（この道具に読みの注記なし）"),
        "n_measurable_2018": e["n_meas"], "distinct_values": e["distinct"],
        "min": r4(vals[0]), "q25": r4(e["q"][0]), "q50": r4(e["q"][1]), "q75": r4(e["q"][2]),
        "max": r4(vals[-1]),
        "share_exactly_zero": r4(rate(sum(1 for x in vals if x == 0), len(vals))),
        "realized_group_share": {c: r4(rate(e["cuts"][c].bit_count(), e["n_meas"])) for c in CUTNAMES},
    }
variable_readings["_how_to_read"] = (
    "『上位1/4』という名前だけでは何を切ったか分からない。**閾値の実額と、同値で潰れて"
    "実際に何%を切ったか**を必ず併記する。とくに netiss_r の q75 は 0.0、rnd_r の q25/q50 は 0.0。")

# 物語の組の表（設計6: 結果に関わらず全部出す）
forced_table = []
for meta in forced_meta:
    rows = []
    for key in forced_keys:
        (xa, ca), (xb, cb) = key
        if {xa, xb} != {meta["var_a"], meta["var_b"]}:
            continue
        # 側が一致するものだけ（別の物語が同じ2変数を逆向きで使う場合を混ぜない）
        want = {(meta["var_a"], meta["side_a"]), (meta["var_b"], meta["side_b"])}
        got = {(xa, "high" if ca in HIGH_SIDE else "low"), (xb, "high" if cb in HIGH_SIDE else "low")}
        if want != got:
            continue
        e = next((x for x in results if (x["var_a"], x["cut_a"], x["var_b"], x["cut_b"])
                  == (key[0][0], key[0][1], key[1][0], key[1][1])), None)
        if e:
            row = detail_of(e, with_profile=True)
            row["both_tails"] = both_tails(e)
            rows.append(row)
    rows.sort(key=lambda x: (-(x["maintained_lift"] or 0), x["label"]))   # 同値でも順序を固定する
    forced_table.append({"story": meta["story"],
                         "pair": f"{meta['var_a']}[{meta['side_a']}] ∧ {meta['var_b']}[{meta['side_b']}]",
                         "n_cut_combinations_measured": len(rows),
                         "best_maintained_lift": (rows[0]["maintained_lift"] if rows else None),
                         "verdicts": dict(Counter(r["verdict"] for r in rows)),
                         "cuts": rows})

# 上位30組
rank = [e for e in results if e.get("maintained_lift") is not None and e.get("sign") == 1]
rank.sort(key=lambda e: (-e["maintained_lift"], -(e["lift_increment_vs_best_leg"] or 0)))
top30 = []
for e in rank[:30]:
    key = ((e["var_a"], e["cut_a"]), (e["var_b"], e["cut_b"]))
    top30.append({
        "label": e["label"], "population": e["population"], "origin": e["origin"],
        "maintained_lift_161718": e["maintained_lift"],
        "lift_increment_vs_best_leg": e["lift_increment_vs_best_leg"],
        "best_leg_maintained_lift": e["best_leg_maintained_lift"],
        "maintained_lift_measurable_base": e["maintained_lift_meas"],
        "coverage_both_min": e["coverage_both_min"],
        "min_numerator_161718": e["min_numerator_161718"],
        "anchor_2018": e["by_vintage"]["2018"],
        "lift_by_vintage": {v: (e["by_vintage"][v]["lift"] if e["by_vintage"][v] else None)
                            for v in ("2016", "2017", "2018")},
        "n_group_by_vintage": {v: (e["by_vintage"][v]["n_group"] if e["by_vintage"][v] else None)
                               for v in ("2016", "2017", "2018")},
        "numerator_by_vintage": {v: (e["by_vintage"][v]["numerator"] if e["by_vintage"][v] else None)
                                 for v in ("2016", "2017", "2018")},
        "verdict": e["verdict"], "verdict_reason": e["verdict_full"]["reason"],
        "gate_failed_at": e["verdict_full"].get("gate_failed_at"),
        "thresholds_2018": thresholds(e["population"], key),
        "sector_benchmark_2018": (sector_benchmark(e["population"], key) or {}).get("2018"),
        "group_profile_2018": group_profile(e["population"], key),
    })

inc = sorted([e["lift_increment_vs_best_leg"] for e in rank
              if e["lift_increment_vs_best_leg"] is not None])
increment_summary = {
    "n_pairs_with_positive_maintained_lift": len(rank),
    "increment_percentiles": {k: pctl(inc, p) for k, p in
                              (("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))},
    "max_increment": r4(inc[-1]) if inc else None,
    "n_increment_positive": sum(1 for x in inc if x > 0),
    "n_increment_ge_0.05": sum(1 for x in inc if x >= 0.05),
    "note": "増分＝組の維持lift − 各脚単独の維持liftの最大。**組の存在価値そのもの**。",
}

# ────────────────────────────── 補助: P_quality の2ビンテージ版（事前登録の外） ──────────────────────────────
def supplementary(pop, vints, n_perm=N_PERM_SUP):
    """**合否には数えない**。判定不能な母集団で『測れる範囲の絵』を出す。"""
    sup_seeds, sup_full = pick_seeds(pop, A0, D0, vints)
    seen = set()
    for s in sup_seeds:
        for sc in side_cuts(s["side"]):
            for var2 in CANDIDATES:
                if var2 == s["variable"]:
                    continue
                for c2 in CUTNAMES:
                    seen.add(tuple(sorted([(s["variable"], sc), (var2, c2)])))
    for key in forced_keys:
        if key[0][0] != key[1][0]:
            seen.add(key)
    keys = sorted(seen)
    masks = {}
    for key in keys:
        d = {}
        for v in vints:
            m = pair_masks(v, pop, key)
            if m:
                d[v] = m
        if len(d) == len(vints):
            masks[key] = d

    def meas(key, Aint, Yint):
        signs, mn, per = set(), 1e9, {}
        for v in vints:
            gm, mm = masks[key][v]
            pm = POPMASK[(v, pop)]
            a, y = Aint[v], Yint[v]
            npop = (pm & a).bit_count()
            kpop = (pm & y).bit_count()
            ng = (gm & a).bit_count()
            if ng == 0 or npop == 0:
                return None
            kg = (gm & y).bit_count()
            lift = kg / ng - kpop / npop
            per[str(v)] = {"n_pop": npop, "destroy_events_in_pop": kpop, "p_base": r4(kpop / npop),
                           "n_group": ng, "numerator": kg, "p_group": r4(kg / ng), "lift": r4(lift)}
            signs.add(1 if lift > 0 else -1)
            if len(signs) > 1:
                return {"per": per, "sign_stable": False, "maintained": 0.0,
                        "min_num": min(x["numerator"] for x in per.values())}
            mn = min(mn, abs(lift))
        return {"per": per, "sign_stable": True, "maintained": r4(mn), "sign": signs.pop(),
                "min_num": min(x["numerator"] for x in per.values())}

    obs = []
    for key in masks:
        m = meas(key, A0, D0)
        if m and m["sign_stable"] and m.get("sign") == 1:
            obs.append({"label": f"{key[0][0]}[{key[0][1]}] ∧ {key[1][0]}[{key[1][1]}]",
                        "maintained_lift": m["maintained"], "min_numerator": m["min_num"],
                        "by_vintage": m["per"],
                        "meets_lift_and_min_num_if_only_two_vintages_were_required":
                            bool(m["maintained"] >= LIFT and m["min_num"] >= MIN_NUM),
                        "thresholds_2018": thresholds(pop, key),
                        "group_profile_2018": group_profile(pop, key)})
    obs.sort(key=lambda x: -x["maintained_lift"])
    obs_best = obs[0]["maintained_lift"] if obs else 0.0
    obs_pass = sum(1 for x in obs if x["meets_lift_and_min_num_if_only_two_vintages_were_required"])

    nulls, null_pass = [], []
    sg = list(range(N_T))
    for _ in range(n_perm):
        rnd.shuffle(sg)
        Ai = {v: perm_int(A_bits[v], sg) for v in vints}
        Di = {v: perm_int(D_bits[v], sg) for v in vints}
        b, np_ = 0.0, 0
        for key in masks:
            m = meas(key, Ai, Di)
            if m and m["sign_stable"] and m.get("sign") == 1:
                b = max(b, m["maintained"])
                if m["maintained"] >= LIFT and m["min_num"] >= MIN_NUM:
                    np_ += 1
        nulls.append(b)
        null_pass.append(np_)
    ns = sorted(nulls)
    return {
        "status": "★事前登録の外。合否には数えない。",
        "population": pop, "vintages_used": vints,
        "why_out_of_prereg": ("prereg の符号不変ゲートは 2016/2017/2018 の3つを要求するが、"
                              f"{pop} の 2017 は破壊事象が母集団全体で "
                              f"{pop_decidability[pop]['by_vintage']['2017']['destroy_events']} 件しかなく"
                              "分子>=5 に届かない。2ビンテージに落として初めて絵が出る＝"
                              "**登録した手続きではない**"),
        "n_seeds": len(sup_seeds), "seeds": sup_seeds,
        "n_variables_with_positive_stable_cut": len(sup_full),
        "n_tests": len(masks),
        "n_meeting_relaxed_line": obs_pass,
        "observed_max_statistic": r4(obs_best),
        "null": {"n_permutations": n_perm,
                 "max_statistic": {"p50": pctl(ns, 0.50), "p90": pctl(ns, 0.90), "p95": pctl(ns, 0.95),
                                   "p99": pctl(ns, 0.99), "max": r4(max(nulls)) if nulls else None},
                 "empirical_p_of_observed_max": r4(sum(1 for x in nulls if x >= obs_best) / n_perm),
                 "P_at_least_one_meets_relaxed_line": r4(sum(1 for x in null_pass if x > 0) / n_perm),
                 "mean_meeting_relaxed_line": r4(sum(null_pass) / n_perm)},
        "top15": obs[:15],
    }


sup = supplementary(SUP_POP, SUP_VINTAGES)

# ────────── ★『3ビンテージで符号不変』の値打ちを測る（独立な3証拠ではない） ──────────
vint_indep = {"pairs": {}, "note": (
    "prereg の independence_warning: 2016/2017/2018 は**同じ956ティッカーで窓が重なる**"
    "（10.09/9.09/8.09年・終点はすべて2026）。『3ビンテージで符号不変』を"
    "**独立な3証拠と読んではいけない**。ここではその重なりを実数で出す。")}
for i, va in enumerate(SIGN_VINTAGES):
    for vb in SIGN_VINTAGES[i + 1:]:
        Ra = {r["ticker"]: r for r in pop_rows(va, "P_full")}
        Rb = {r["ticker"]: r for r in pop_rows(vb, "P_full")}
        common = sorted(set(Ra) & set(Rb))
        da = {t for t in common if Ra[t].get("destroy")}
        db = {t for t in common if Rb[t].get("destroy")}
        xs = [Ra[t]["tr_cagr"] for t in common if Ra[t].get("tr_cagr") is not None
              and Rb[t].get("tr_cagr") is not None]
        ys = [Rb[t]["tr_cagr"] for t in common if Ra[t].get("tr_cagr") is not None
              and Rb[t].get("tr_cagr") is not None]
        vint_indep["pairs"][f"{va}vs{vb}"] = {
            "n_common_tickers": len(common),
            "n_destroy_a": len(da), "n_destroy_b": len(db),
            "n_destroy_in_both": len(da & db),
            "jaccard_of_destroy_sets": r4(len(da & db) / len(da | db)) if (da | db) else None,
            "share_of_smaller_set_shared": r4(len(da & db) / min(len(da), len(db))) if da and db else None,
            "spearman_tr_cagr": r4(spearman(xs, ys)) if len(xs) >= 20 else None,
        }
vint_indep["_conclusion"] = (
    "破壊した社の集合はビンテージ間で大きく重なる。**符号不変ゲートは『別々の3回の実験で再現した』"
    "ではなく『ほぼ同じ標本で3回測っても符号が変わらなかった』**という意味しかない。"
    "本当の外部検証は 2013/2015 だが、**f2_ 系の特徴量はその2ビンテージに存在しない**"
    "（features2 は 2016/2017/2018 のみ）ので、この道具の合格は**外部検証を受けていない**。")

# ────────────────────────────── 見出し（結論の要約・数字だけ） ──────────────────────────────
def _pass_headline(p):
    bt = p["both_tails"]
    lo = p.get("sector_leave_one_out") or {}
    broken = sorted([s for s, v in lo.items()
                     if not s.startswith("_") and isinstance(v, dict)
                     and v.get("still_meets_lift_and_min_num") is False])
    return {"label": p["label"], "maintained_lift": p["maintained_lift"],
            "lift_increment_vs_best_leg": p["lift_increment_vs_best_leg"],
            "min_numerator_161718": p["min_numerator_161718"],
            "win_side_maintained_lift": (bt["win"]["maintained_lift"] if bt.get("win") else None),
            "win_side_sign": (bt["win"]["sign"] if bt.get("win") else None),
            "both_tails_reading": bt["reading"],
            "sectors_whose_removal_breaks_the_line": broken}


headline = {
    "verdict": f"合格 {vcount.get('合格', 0)}組＝**別々の発見は {len(pass_varpairs_canon)} 組**"
               f"（{sorted(pass_varpairs_canon)}）",
    "passes": [_pass_headline(p) for p in passers],
    "what_the_passes_share": ("合格した2つの発見は**どちらも f2_rnd_r[上位1/4]（R&D比>=4.6%）を含む**。"
                              "残る脚は『純発行側(netiss_r>=0)』と『小型(売上<=5.83億$)』。"),
    "gate_cascade": cascade_summary["fate"],
    "undecided_not_failed": ("L3を通ったのに irr の影かどうかを決められなかった組が3つある"
                             "（低利益率×小型 など）。**これは不合格ではない**——"
                             "群に irr の読解が一行も無く、決めるための情報が存在しない。"),
    "story_pairs_result": {
        "asked_to_be_measured": [m["pair"] for m in [{"pair": f['pair']} for f in forced_table]],
        "best": max(forced_table, key=lambda f: (f["best_maintained_lift"] or 0))["pair"],
        "best_value": max(f["best_maintained_lift"] or 0 for f in forced_table),
        "n_reaching_the_line": sum(1 for f in forced_table if f["verdicts"].get("合格")),
        "note": ("**筋の通る物語のうち、線に届いたものはゼロ**。最良は『高株式発行×低利益率』0.1214。"
                 "のれん系・アクルーアル系・FCF転換系は**符号が逆（破壊が少ない側）**に出た。"),
    },
    "robustness_out_of_prereg": {
        "sector_leave_one_out": ("★**事前登録の外の検査だが、これが最も重い**——"
                                 "合格2件とも **SIC28(医薬・化学)を母集団から外すと線を割る**"
                                 "（0.1704→0.0537 / 0.1662→0.0966）。他の業種を外しても線は保つ。"
                                 "＝この信号は**医薬・バイオの中でだけ強く、その外では線に届かない**。"
                                 "事前登録の業種調整(MH)は層の9割を落とすので、これを捕まえられなかった。"),
        "power": ("真の lift がちょうど 0.15 のとき検出率 **0.00**、0.16 で 0.45、0.20 で 0.80。"
                  "観測された合格は 0.166-0.170＝**掴めるかどうかの境目**にある。"),
        "external_validation": "**受けていない**（f2_ 系は 2013/2015 に存在しない）。上の vintage_independence を見よ。",
    },
    "population_note": ("P_quality（門が実際に当てる場所）は **2017 の破壊事象が母集団全体で4件**しかなく、"
                        "prereg の分子>=5 に**測る前から届かない**＝あらゆる組が判定不能。"
                        "P_moat は 2016/2017 が空、2018 の破壊事象は0件。"),
}

# ────────────────────────────── 出力 ──────────────────────────────
out = {
    "generated": "2026-08-11",
    "tool": "night/hist_wd_dst_pair.py",
    "prereg": "out/hist_winner_destroyer_prereg.json",
    "inputs": {"panel": "out/hist_wd_panel.json",
               "winner_univariate_for_implementation_check": "out/hist_wd_win_uni.json",
               "destroyer_univariate": ("out/hist_wd_dst_uni.json" if dst_uni else "（無い）")},
    "objective": "B_破壊: P(実現年率 tr_cagr <= -15%)。2本積（AND）のみ。勝者側(目的A)はこの道具の範囲外。",
    "sibling_tool": "night/hist_wd_win_pair.py（勝者側・同じ形）",
    "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM,
                       "sign_stability_vintages": SIGN_VINTAGES,
                       "sector_control": "同一sic2内(MH)でも|差|>=0.15",
                       "not_irr_shadow": "irr>=70層内でも|lift|>=0.15、または irr と直交",
                       "note": "prereg の literal。この道具は線を一つも作らず、一つも緩めていない。"},
    "design_decisions": {
        "analysis_set": "has_outcome ∧ window_full（勝者側と同一）",
        "search_space": "符号不変ゲートを当てられる21本のみ。co_/pa_/hv_/per は構造的に判定不能ゆえ除外（不合格ではない）",
        "populations": "P_full のみ。P_quality/P_moat は母集団の破壊事象が分子5に届かず**測る前から判定不能**",
        "seeds": "各母集団で『3ビンテージとも lift が正・揃った上での最小 lift』が大きい上位10本",
        "forced_pairs": "破壊の物語として筋が通る組を**結果を見る前に登録**し、種から出なくても必ず測る",
        "binarization": "prereg の combos どおり 中央値 / 上下1/4。種は同じ向きの2通り、相手は4通り",
        "thresholds": "各変数が自分の分布（母集団内・可測行のみ・nearest-rank）で切る。ANDの交差で切り直さない",
        "lift_denominator": "prereg literal の母集団。lift_vs_measurable_both を必ず併記",
        "self_pairs": "同じ変数どうしの組は作らない（空 or 入れ子）",
        "irr_gate": "破壊側は層内検定が到達不能なので直交でのみ通す。通せなければ**判定不能**（不合格ではない）",
        "spot_check": "合格の有無に関わらず行レベルで数え直す（合格ゼロで検算が消えないように）",
    },
    "headline": headline,
    "vintage_independence": vint_indep,
    "candidate_derivation_check": cand_check,
    "crosscheck_vs_winner_univariate_tool": crosscheck_win,
    "crosscheck_vs_destroyer_univariate_tool": crosscheck_dst,
    "spot_check_row_level": spot,
    "duplicate_columns_in_search_space": {
        "found": dup_pairs,
        "note": "同じ量が別名で二度入っていると検定数が水増しされ『別々の発見』が二重に見える。全行を突き合わせて検出した。"},
    "excluded_candidates_structurally_undecidable": EXCLUDED,
    "forced_pairs_declared_before_results": forced_meta,
    "seeds": {pop: seeds[pop] for pop in POPS},
    "seed_selection_table": seed_tables,
    "search_space_size": {"per_population": enum_stats, "n_tests_total_after_dedup": n_tests_total,
                          "note": "**多重検定の値札**。偽陽性率はこの数で決まる。"},
    "must_report_before_verdict": {
        "one_sidedness_of_the_line": one_sided,
        "population_level_decidability": pop_decidability,
        "irr_stratum_reachability": irr_stratum,
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
                                "何通りも通るだけのことがある。**変数の組の異なり数**で読むこと。"
                                "同一列の別名(size_rev と f2_rev)は canonical で潰してある。")},
    "variable_readings": variable_readings,
    "gate_cascade_from_L3": {"summary": cascade_summary, "rows": cascade},
    "passing_pairs_detail": passers,
    "forced_pairs_results": forced_table,
    "increment_over_single_leg": increment_summary,
    "top30_by_maintained_lift": top30,
    "top30_note": (f"in-sample の最良＝**過剰適合込みの上限**。{n_tests_total}通りを試した中の最大値なので、"
                   "偽陽性率と帰無分布（above false_positive_rate）と必ず突き合わせて読むこと。"),
    "supplementary_out_of_prereg_P_quality": sup,
    "all_pairs": [{k: e.get(k) for k in ("population", "label", "var_a", "cut_a", "var_b", "cut_b",
                                         "origin", "maintained_lift", "maintained_lift_meas", "sign",
                                         "min_numerator_161718", "lift_increment_vs_best_leg",
                                         "best_leg_maintained_lift", "coverage_both_min", "verdict")}
                  | {"gate_failed_at": e["verdict_full"].get("gate_failed_at")}
                  for e in results],
    "runtime_sec": round(time.time() - t0, 1),
}
json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ────────────────────────────── 画面 ──────────────────────────────
print(f"[候補導出] 勝者側の一覧と一致: {cand_check['identical']}  ({len(CANDIDATES)}本)")
print(f"[検算1] 勝者ラベルで勝者側の道具を再現: 比較{crosscheck_win['compared']}件 / 不一致{crosscheck_win['mismatches']}件")
print(f"[検算2] 行レベル: {spot['n_pairs_checked']}組 / 比較{spot['checked']}件 / 不一致{spot['mismatches']}件")
print(f"[片側性] 破壊 base の最大 {one_sided['max_base_over_cells']} → lift<=-0.15 はどのセルでも不可能: "
      f"{not one_sided['negative_side_possible_anywhere']}")
print("[母集団の判定可能性]")
for pop in POPS_ALL:
    d = pop_decidability[pop]
    ev = {k: v["destroy_events"] for k, v in d["by_vintage"].items()}
    print(f"  {pop}: 破壊事象 {ev} → 判定可能={d['decidable']} 探索空間={d['in_primary_search_space']}")
print(f"[検定数] {n_tests_total} 検定 " + " / ".join(
    f"{pop}: 種{enum_stats[pop]['n_after_dedup_from_seeds']}＋物語{enum_stats[pop]['n_forced_pairs_new_beyond_seeds']}"
    for pop in POPS))
for pop in POPS:
    print(f"  種({pop}): " + (", ".join(f"{s['variable']}[{s['best_cut']}]{s['maintained_lift']}"
                                        for s in seeds[pop]) or "（無し）"))
print(f"[判定] " + " / ".join(f"{k}:{v}" for k, v in vcount.items()) + f"  合格={vcount.get('合格', 0)}"
      f"（別々の発見は {len(pass_varpairs_canon)} 組: {sorted(pass_varpairs_canon)}）")
print(f"[ゲート通過段] L3到達 {cascade_summary['n_reached_L3']}組"
      f"（重複除去 {cascade_summary['n_distinct_canonical_pairs_at_L3']}）→ {cascade_summary['fate']}")
for c in cascade:
    bt = c["both_tails"]
    print(f"   {c['label']:52s} lift{c['maintained_lift']} 増分{c['lift_increment_vs_best_leg']} "
          f"→ {c['verdict']}({c['gate_failed_at']}) | 勝ち側 {bt['win']['maintained_lift'] if bt['win'] else None}"
          f"(符号{bt['win']['sign'] if bt['win'] else None}) | {bt['reading'][:34]}")
print("[到達可能性] " + " / ".join(
    f"{pop}: 到達可能{reach_summary[pop]['n_pairs_reachable']}/{reach_summary[pop]['n_pairs']}"
    f" MIN_NUMが縛るセル{reach_summary[pop]['cell_vintages_where_MIN_NUM_binds']}" for pop in POPS))
print("[FPR] 偶然に1組でも通る確率 " + " ".join(f"{k}={v}" for k, v in fpr["P_at_least_one_pass_by_level"].items()))
print(f"      最大統計量 観測{fpr['null_distribution_of_max_statistic']['observed_in_real_data']} "
      f"(帰無 p50={fpr['null_distribution_of_max_statistic']['p50']} "
      f"p95={fpr['null_distribution_of_max_statistic']['p95']} "
      f"経験p={fpr['null_distribution_of_max_statistic']['empirical_p_of_observed']})")
print("[陽性対照] " + " / ".join(f"{k}:合格率{v['pass_rate']}" for k, v in positive_control.items()
                                if k.startswith("true")))
print(f"[物語の組] " + " / ".join(f"{f['pair']}→最良{f['best_maintained_lift']}" for f in forced_table))
print("[業種を外す検査(事前登録の外)] " + " / ".join(
    f"{h['label']}→線を割る業種{h['sectors_whose_removal_breaks_the_line']}" for h in headline["passes"]))
print("[ビンテージの独立性] " + " / ".join(
    f"{k}: 破壊集合Jaccard={v['jaccard_of_destroy_sets']} tr_cagr相関={v['spearman_tr_cagr']}"
    for k, v in vint_indep["pairs"].items()))
print(f"[補助 P_quality 2016+2018] 観測最大{sup['observed_max_statistic']} "
      f"帰無p95={sup['null']['max_statistic']['p95']} 経験p={sup['null']['empirical_p_of_observed_max']}")
print(f"→ {DEST}  ({out['runtime_sec']}s)")
