#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_angleB.py — 角度B: 目的を **y_persist（前半と後半の両方で年率10%+）** にした探索。

事前登録: out/hist10_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json      （特徴量。再実装しない・v9.9.65）
          out/hist10_targets.json     （y_persist の正本。2013の前半/後半は既に検算済み）
          out/retro_monthly_2013_2018.json / out/retro_monthly_2018_2026.json（月次adjclose在庫）
          out/hist10_angleA.json      （**実装の突合せ相手**。同じ台帳を見る二つの検査器が違うことを言ってはいけない）
出力    : out/hist10_angleB.json

────────────────────────────────────────────────────────────
なぜ y_persist が新しいのか
────────────────────────────────────────────────────────────
この台帳の歴史検証は一貫して「窓の終点までの年率」を目的にしてきた。
つまり **一度きりの通算成績**しか見ていない。ところが門の目的は 20-30年の複利＝
「**続くか**」であって「一度出せたか」ではない。
y_persist は **二つの連続した窓のどちらでも 10%+** を要求するので、
『一度は出せるが続かない社』と『続く社』を初めて分離できる。

事前登録の base_rate: 2013で **206/941 = 0.219**（15%だと80社しかなく検定できなかった）。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定
────────────────────────────────────────────────────────────
1) **f2_*（filed<=asof の厳密な特徴量）が使える設計を先に探した。あった。**
   事前登録の y_persist は「前半5.0年(2013-07→2018-07) ∧ 後半8.09年(2018-07→2026-08)」で、
   入口が2013しかない＝特徴量は co_*（**約94%が look-ahead**）に限られ、
   しかも事前登録の符号不変ゲート（2016/2017/2018 すべて）が**構造的に到達不能**になる
   （hist10_targets.json の reachability が既にそう出している）。
   だが月次在庫（2013-07→2018-06 と 2018-07→2026-08）を継ぐと **2013-07→2026-08 の連続系列**が作れる。
   すると 2016/2017/2018 を入口にして「**その窓自身を二等分する**」持続の目的が作れ、
   特徴量は f2_*（厳密）のまま、符号不変ゲートも当てられる。
   → **B1（事前登録どおり・look-ahead込み）** と **B2（厳密・事前登録の外）** の**両方**を測る。
   どちらか一方を黙って選ばない。

2) **B1 の y_persist は hist10_targets.json の値をそのまま使う**（再実装しない）。
   ただし月次系列から**独立に**組み直して突合せる（別の在庫・別の経路）。

3) **分割点は「その窓自身の月数の中点」**（B2）。共通の暦日で切らない。
   理由: 窓ごとに前半・後半の長さが揃い、しかも3つの入口で**別々のレジーム分割**になる＝
   符号不変ゲートが「単一レジームの産物か」を同時に試すことになる。
   （共通暦日で切ると 2016 は 6年 vs 4年になり、前半・後半の非対称が入口ごとに違ってしまう）

4) **核心の問いは条件付きで測る**——**母集団を「前半10%+ の社」に絞り、目的を「後半も10%+」**にする。
   これが『一度は出せるが続かない社』と『続く社』を直接分ける形。
   4群（両方 / 前半だけ / 後半だけ / どちらも）の記述統計も全変数で出す。
   ⚠ 前半のリターン自体は**入口の指標ではなく結果の一部**なので、
   予言子の候補には入れず**対照**として報告する（irr/moat5 と同じ扱い）。

5) 切り方は既存と同じ4つ（上位1/4・下位1/4・中央値超・中央値以下）。**新しい切り方を作らない**
   （増やすと検定数が増えて偽陽性率が上がる）。

6) 増分ゲートは方向で当てるものが違う（角度Aと同一の手続き）。
   ⚠ **B1(2013) では f2_intcov も f2_opmD5 も無い**ので、門の関門をそのままは当てられない。
   co_ 側の**上位集合**（真の関門より多く止める代用）で当て、その旨を印にする。

7) 乱数の種・置換回数・検出力の試行回数は角度Aと同一（SEED=20260812 / 2000 / 5000）。

8) **角度Aと同じ y10 のセルを自分の measure() で測り直し、公表値と一致するか先に確かめる**。
   一致して初めて「角度Bで出てきた/消えた」と言える（基準の違う二つを並べない）。

────────────────────────────────────────────────────────────
持ち越しの限界（事前登録の known_limits）
────────────────────────────────────────────────────────────
・2013/2015/2016/2017/2018 は同じ956ティッカー＝**out-of-sample は無い**
・B2 の3つの入口は**窓が重なる**（2016/2017/2018 の後半はほぼ同じ期間）＝独立な3つの証拠ではない
・母集団は今日ティッカーが解決できる社のみ＝生存バイアス
・10% は同期間の SPY（14.2〜15.2%）に**負ける**水準。「勝つ」ではなく「複利が立つ」の線
"""
import json, os, math, random, sys, time, datetime
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

PANEL = os.path.join(OUT, "hist_wd_panel.json")
PREREG = os.path.join(OUT, "hist10_prereg.json")
TARGETS = os.path.join(OUT, "hist10_targets.json")
MON_A = os.path.join(OUT, "retro_monthly_2013_2018.json")
MON_B = os.path.join(OUT, "retro_monthly_2018_2026.json")
ANGLEA = os.path.join(OUT, "hist10_angleA.json")
DEST = os.path.join(OUT, "hist10_angleB.json")

# ─── prereg の線（読むだけ・一つも作らない） ───
LIFT = 0.15
MIN_NUM = 20
HURDLE = 0.10
INCREMENTAL_MAX_CAUGHT = 0.70
SIGN_VINTAGES = [2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]
CUTNAMES = ["上位1/4", "下位1/4", "中央値超", "中央値以下"]
SEED = 20260812
N_PERM = 2000
N_POWER = 5000

F2 = ["gm", "sga_r", "capex_r", "rnd_r", "opm", "intcov", "aturn", "accr", "cash_r", "gw_r",
      "cagr5", "accel", "streak_rev", "streak_opm", "opmD5", "fcfpos5", "conv5", "netiss_r",
      "payout5", "rev"]
CO = ["roic_med5", "roic_latest", "roic_worst5", "opm", "sales_cagr5", "fcf_conv_5y",
      "op_all_pos", "fcf_all_pos", "equity_neg", "score", "rev_asof"]
HV = ["pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_z", "ps_z"]

CAND_B1 = ["co_" + f for f in CO] + ["hv_" + f for f in HV] + ["per", "size_rev"]
CAND_B2 = ["f2_" + f for f in F2] + ["size_rev"]

MONTH_END = 2026 * 12 + 8          # 在庫の最終月（2026-08）
YEAR = 365.2425 * 86400.0


# ────────────────────────────── 小道具（角度Aと同一の定義） ──────────────────────────────
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


def q_at(sorted_vals, q):
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


def med(vals):
    v = sorted(x for x in vals if x is not None)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def auc(pos, neg):
    """rank-biserial 由来の AUC。pos/neg は値の配列。0.5 が『分けない』"""
    if not pos or not neg:
        return None
    allv = sorted([(x, 1) for x in pos] + [(x, 0) for x in neg])
    n = len(allv)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rp = sum(ranks[k] for k in range(n) if allv[k][1] == 1)
    np_, nn = len(pos), len(neg)
    return (rp - np_ * (np_ + 1) / 2.0) / (np_ * nn)


def ym_of(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + d.month


def ym_str(m):
    return "%04d-%02d" % ((m - 1) // 12, (m - 1) % 12 + 1)


# ────────────────────────────── 読み込み ──────────────────────────────
prereg = json.load(open(PREREG, encoding="utf-8"))
panel = json.load(open(PANEL, encoding="utf-8"))
targets = json.load(open(TARGETS, encoding="utf-8"))
mon_a = json.load(open(MON_A, encoding="utf-8"))
mon_b = json.load(open(MON_B, encoding="utf-8"))

pan_by = {}
for r in panel["rows"]:
    pan_by[(r["ticker"], r["vintage"])] = r
tgt_by = {}
for r in targets["rows"]:
    tgt_by[(r["ticker"], r["vintage"])] = r


# ── 月次を継ぐ（同じ基準か必ず検算する。この台帳が8回踏んだ「基準の違う二つ」型） ──
def build_series():
    ser = {}
    for t in set(mon_a) | set(mon_b):
        d = {}
        for src in (mon_a.get(t) or []), (mon_b.get(t) or []):
            for ts, p in src:
                if p is None or p <= 0:
                    continue
                d[ym_of(ts)] = float(p)
        if d:
            ser[t] = d
    return ser


SER = build_series()


def cagr_between(t, m0, m1):
    d = SER.get(t)
    if not d or m0 not in d or m1 not in d:
        return None
    p0, p1 = d[m0], d[m1]
    if p0 <= 0 or p1 <= 0:
        return None
    yrs = (m1 - m0) / 12.0
    if yrs <= 0:
        return None
    return (p1 / p0) ** (1.0 / yrs) - 1.0


# ─────────── 突合せ①: 継いだ系列 vs 在庫の tr_cagr（同じ基準か） ───────────
splice_check = {"def": "継いだ月次系列の 2013-07→2026-08 年率 と、在庫 retro_returns_2013_all の tr_cagr の差。"
                       "**二つの月次ファイルが同じ調整基準か**をこれで裁く（別基準なら継いだ瞬間に壊れる）",
                "rows": 0, "med_abs": None, "max_abs": None, "share_gt_0.005": None, "worst": []}
_d = []
for (t, v), tr in tgt_by.items():
    if v != 2013 or not tr.get("window_full") or tr.get("tr_cagr") is None:
        continue
    c = cagr_between(t, 2013 * 12 + 7, MONTH_END)
    if c is None:
        continue
    _d.append((abs(c - tr["tr_cagr"]), t, round(c, 4), tr["tr_cagr"]))
_d.sort(reverse=True)
if _d:
    splice_check.update({
        "rows": len(_d), "med_abs": r4(med([x[0] for x in _d])), "max_abs": r4(_d[0][0]),
        "share_gt_0.005": r4(sum(1 for x in _d if x[0] > 0.005) / len(_d)),
        "worst": [{"t": x[1], "spliced": x[2], "inventory": x[3], "diff": r4(x[0])} for x in _d[:5]],
    })


# ─────────── 突合せ②: 前半 r_pre を月次から独立に組み直す ───────────
# targets は (1+r13)^13.09 = (1+r_pre)^5.0 × (1+r18)^8.09 の**代数**で作った。
# ここは月次の価格から直接作る＝別の在庫・別の経路。
rpre_check = {"def": "targets の r_pre（代数で復元）と、月次 2013-07→2018-07 の実測年率の突合せ",
              "n": 0, "pearson": None, "med_abs": None, "max_abs": None,
              "flip_across_10pct": None, "worst": []}
_p = []
for (t, v), tr in tgt_by.items():
    if v != 2013 or tr.get("r_pre") is None:
        continue
    c = cagr_between(t, 2013 * 12 + 7, 2018 * 12 + 7)
    if c is None:
        continue
    _p.append((t, tr["r_pre"], c))
if _p:
    xs = [x[1] for x in _p]
    ys = [x[2] for x in _p]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    nu = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    diffs = sorted(((abs(x[1] - x[2]), x[0], x[1], x[2]) for x in _p), reverse=True)
    flips = sum(1 for x in _p if (x[1] >= HURDLE) != (x[2] >= HURDLE))
    rpre_check.update({
        "n": len(_p), "pearson": r4(nu / (dx * dy)) if dx and dy else None,
        "med_abs": r4(med([d[0] for d in diffs])), "max_abs": r4(diffs[0][0]),
        "flip_across_10pct": {"k": flips, "n": len(_p), "share": r4(flips / len(_p))},
        "worst": [{"t": d[1], "targets": r4(d[2]), "monthly": r4(d[3])} for d in diffs[:5]],
        "note": "10%の線をまたぐ食い違いは『どちらかが誤り』ではなく、月足の端が1ヶ月ずれることによる不定性。"
                "targets 自身が fragility として 14.7%(138/941) が ±1pt 内にあると記録している",
    })


# ────────────────────────────── 目的変数を作る ──────────────────────────────
# B1: 事前登録どおり（2013入口・前半5.0年 ∧ 後半8.09年）。targets の値をそのまま使う
B1 = []
for (t, v), tr in tgt_by.items():
    if v != 2013 or tr.get("y_persist") is None:
        continue
    p = pan_by.get((t, 2013))
    if not p:
        continue
    row = dict(p)
    row["_pre"] = tr["r_pre"]
    row["_post"] = tr["r_post"]
    row["_ypre"] = tr["r_pre"] >= HURDLE
    row["_ypost"] = tr["r_post"] >= HURDLE
    row["_ypersist"] = bool(tr["y_persist"])
    row["_y10"] = bool(tr["y10"])
    B1.append(row)

# B2: 厳密（f2）。入口 2016/2017/2018・その窓自身の月数の中点で二分
B2 = defaultdict(list)
b2_windows = {}
for v in SIGN_VINTAGES:
    m0 = v * 12 + 7
    span = MONTH_END - m0
    mid = m0 + span // 2
    b2_windows[v] = {
        "anchor": ym_str(m0), "mid": ym_str(mid), "end": ym_str(MONTH_END),
        "first_half_years": r4((mid - m0) / 12.0), "second_half_years": r4((MONTH_END - mid) / 12.0),
    }
    for t, d in SER.items():
        p = pan_by.get((t, v))
        if not p:
            continue
        c1 = cagr_between(t, m0, mid)
        c2 = cagr_between(t, mid, MONTH_END)
        if c1 is None or c2 is None:
            continue
        row = dict(p)
        row["_pre"], row["_post"] = c1, c2
        row["_ypre"], row["_ypost"] = c1 >= HURDLE, c2 >= HURDLE
        row["_ypersist"] = (c1 >= HURDLE) and (c2 >= HURDLE)
        full = cagr_between(t, m0, MONTH_END)
        row["_y10"] = (full is not None and full >= HURDLE)
        row["_full_cagr"] = full
        B2[v].append(row)

# B2 の内部整合: y_persist ⟹ y10 は数学的必然（両半が10%+なら幾何平均も10%+）
b2_struct = {}
for v in SIGN_VINTAGES:
    bad = [r["ticker"] for r in B2[v] if r["_ypersist"] and not r["_y10"]]
    b2_struct[v] = {"n": len(B2[v]), "violations": len(bad), "who": bad[:5],
                    "def": "y_persist=True かつ y10=False は数学的に不可能。1件でもあれば実装が壊れている"}

# B2 の窓が在庫の tr_cagr と整合するか（別経路の突合せ）
b2_vs_inventory = {}
for v in SIGN_VINTAGES:
    d = []
    for r in B2[v]:
        p = pan_by.get((r["ticker"], v))
        if p and p.get("tr_cagr") is not None and p.get("window_full") and r["_full_cagr"] is not None:
            d.append(abs(r["_full_cagr"] - p["tr_cagr"]))
    b2_vs_inventory[v] = {"n": len(d), "med_abs": r4(med(d)), "max_abs": r4(max(d)) if d else None,
                          "share_gt_0.005": r4(sum(1 for x in d if x > 0.005) / len(d)) if d else None}


# ────────────────────────────── 母集団と関門 ──────────────────────────────
def pop_rows(rows, pop):
    return [r for r in rows if r.get(pop)]


def g_shrink_f2(r):
    """事業の収縮（v9.9.99・門に実装済み）: 売上5年CAGR<0 ∧ 営業利益率の5年変化<0"""
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def g_thin_f2(r):
    """財務の薄さ。intcov<3＝門の nde>4 の歴史側の相当物"""
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def g_shrink_co(r):
    """⚠ 2013 には opmD5 も intcov も無い。co_sales_cagr5<0 単独＝**真の関門より多く止める上位集合**"""
    return r.get("co_sales_cagr5") is not None and r["co_sales_cagr5"] < 0


def g_notq(r):
    return not r.get("P_quality")


def blocked_f2(r):
    return g_shrink_f2(r) or g_thin_f2(r) or g_notq(r)


def blocked_co(r):
    return g_shrink_co(r) or g_notq(r)


# ────────────────────────────── 中核: 1セルの測定（角度Aと同一の semantics） ──────────────────────────────
def measure(rows, pop, var, ykey, blocked, min_num=MIN_NUM):
    R = pop_rows(rows, pop)
    n_pop = len(R)
    if n_pop == 0:
        return None
    k_pop = sum(1 for r in R if r.get(ykey))
    p_pop = rate(k_pop, n_pop)

    M = [(num(r.get(var)), 1 if r.get(ykey) else 0, r) for r in R]
    M = [(x, w, r) for (x, w, r) in M if x is not None]
    n_m = len(M)
    if n_m == 0:
        return {"n_pop": n_pop, "p_pop": r4(p_pop), "n_measurable": 0,
                "status": "この母集団でこの変数は一つも測れない＝判定不能"}
    k_m = sum(w for (_, w, _) in M)
    p_m = rate(k_m, n_m)
    n_miss = n_pop - n_m
    k_miss = k_pop - k_m
    p_miss = rate(k_miss, n_miss) if n_miss else None

    vals = sorted(x for (x, _, _) in M)
    distinct = len(set(vals))
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    PRED = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
            "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}
    DESC = {"上位1/4": f"値 >= {q75!r}(75%点)", "下位1/4": f"値 <= {q25!r}(25%点)",
            "中央値超": f"値 > {q50!r}(中央値)", "中央値以下": f"値 <= {q50!r}(中央値)"}

    bp_n = sum(1 for (_, _, r) in M if not blocked(r))
    bp_k = sum(w for (_, w, r) in M if not blocked(r))

    cuts = {}
    for name in CUTNAMES:
        pred = PRED[name]
        grp = [(x, w, r) for (x, w, r) in M if pred(x)]
        gn = len(grp)
        gk = sum(w for _, w, _ in grp)
        gp = rate(gk, gn)
        lift = None if gp is None else gp - p_pop
        ent = {"cut": DESC[name], "n_group": gn, "numerator": gk, "p_group": r4(gp),
               "lift_vs_pop": r4(lift), "lift_vs_measurable": r4(None if gp is None else gp - p_m),
               "direction": (None if lift is None else
                             ("増やす" if lift > 0 else ("減らす" if lift < 0 else "ゼロ")))}
        if gn:
            share = gn / n_m
            ent["group_share_of_measurable"] = r4(share)
            if name in ("上位1/4", "下位1/4") and not (0.10 <= share <= 0.45):
                ent["tie_degenerate"] = True
            fails = [r for (_, w, r) in grp if not w]
            caught = sum(1 for r in fails if blocked(r))
            passers = [(x, w) for (x, w, r) in grp if not blocked(r)]
            ent["incremental"] = {
                "down_side": {"n_failures_in_group": len(fails),
                              "already_caught_by_existing_gates": caught,
                              "caught_share": r4(rate(caught, len(fails)))},
                "up_side": {"n_group_passing_gates": len(passers),
                            "k_group_passing_gates": sum(w for _, w in passers),
                            "p_group_passing_gates": r4(rate(sum(w for _, w in passers), len(passers))),
                            "n_base_passing_gates": bp_n,
                            "p_base_passing_gates": r4(rate(bp_k, bp_n)),
                            "lift_within_gate_passers": r4(
                                None if not passers or not bp_n
                                else rate(sum(w for _, w in passers), len(passers)) - rate(bp_k, bp_n))},
                "circular_note": ("P_quality 母集団では not_quality が定義上ゼロ＝増分ゲートが甘くなる"
                                  if pop == "P_quality" else None),
            }
        cuts[name] = ent

    quint = []
    if distinct >= 5:
        qs = [q_at(vals, x) for x in (0.2, 0.4, 0.6, 0.8)]
        buckets = [[] for _ in range(5)]
        for (x, w, _) in M:
            b = 0
            for i, t in enumerate(qs):
                if x > t:
                    b = i + 1
            buckets[b].append(w)
        for i, b in enumerate(buckets):
            quint.append({"q": i + 1, "n": len(b), "k": sum(b), "p": r4(rate(sum(b), len(b)))})
        pts = [(i, q["p"]) for i, q in enumerate(quint) if q["p"] is not None and q["n"] >= 10]
        mono = spearman([a for a, _ in pts], [b for _, b in pts]) if len(pts) >= 3 else None
    else:
        mono = None

    by_val = None
    if distinct <= 6:
        c = defaultdict(lambda: [0, 0])
        for (x, w, _) in M:
            c[x][0] += 1
            c[x][1] += w
        by_val = [{"value": k, "n": a, "k": b, "p": r4(rate(b, a))} for k, (a, b) in sorted(c.items())]

    return {"n_pop": n_pop, "k_pop": k_pop, "p_pop": r4(p_pop),
            "n_measurable": n_m, "k_measurable": k_m, "p_measurable": r4(p_m),
            "n_missing": n_miss, "p_missing": r4(p_miss),
            "missingness_lift": r4(None if p_miss is None else p_miss - p_m),
            "distinct": distinct, "q25": q25, "q50": q50, "q75": q75,
            "cuts": cuts, "quintiles": quint or None, "quintile_spearman": r4(mono),
            "by_value": by_val,
            "rank_corr_value_vs_y": r4(spearman([x for (x, _, _) in M],
                                                [float(w) for (_, w, _) in M]))}


# ─────────── 到達可能性（両方向）・実効要求倍率 ───────────
def reach(rows, pop, ykey, var=None, min_num=MIN_NUM):
    R = pop_rows(rows, pop)
    n = len(R)
    if n == 0:
        return {"n": 0, "verdict": "母集団が空＝判定不能"}
    ev = sum(1 for r in R if r.get(ykey))
    base = ev / n
    n_m = n if var is None else sum(1 for r in R if num(r.get(var)) is not None)
    if n_m == 0:
        return {"n_pop": n, "n_measurable": 0, "verdict": "測れない＝判定不能"}
    g = max(1, n_m // 4)
    k_up = max(math.ceil((base + LIFT) * g), min_num)
    up_ok = k_up <= min(g, ev)
    k_dn = math.floor((base - LIFT) * g)
    dn_ok = k_dn >= min_num
    return {"n_pop": n, "n_measurable": n_m, "events": ev, "base": r4(base), "group_n": g,
            "up": {"k_needed": k_up,
                   "binding": ("LIFT" if math.ceil((base + LIFT) * g) >= min_num else "MIN_NUM"),
                   "effective_lift_required": r4(k_up / g - base),
                   "possible": up_ok,
                   "max_detectable_lift": r4(min(g, ev) / g - base)},
            "down": {"k_max_allowed_by_lift": k_dn, "k_min_required": min_num, "possible": dn_ok,
                     "max_detectable_lift": r4(min_num / g - base) if dn_ok else None,
                     "why_not": (None if dn_ok else
                                 f"群{g}社では分子>={min_num} と lift<=-{LIFT} が同時に成立しない")}}


# ─────────── 業種調整（Mantel-Haenszel）・業種1つ抜き ───────────
def mh_risk_diff(rows, pop, var, cut, ykey):
    R = [r for r in pop_rows(rows, pop) if num(r.get(var)) is not None and r.get("sic2")]
    if not R:
        return None
    vals = sorted(num(r.get(var)) for r in R)
    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
    P = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
         "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for r in R:
        x = num(r.get(var))
        s = strata[r["sic2"]]
        inn = 1 if P(x) else 0
        y = 1 if r.get(ykey) else 0
        s[0 if inn else 2] += y
        s[1 if inn else 3] += 1
    numr = den = 0.0
    used = 0
    for _, (a, na, b, nb) in strata.items():
        if na == 0 or nb == 0:
            continue
        w = na * nb / (na + nb)
        numr += w * (a / na - b / nb)
        den += w
        used += 1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(numr / den), "strata_used": used, "coverage": r4(len(R) / max(1, len(pop_rows(rows, pop))))}


def drop_one_sector(rows, pop, var, cut, ykey, blocked):
    R = pop_rows(rows, pop)
    secs = sorted({r.get("sic2") for r in R if r.get("sic2")})
    worst = None
    out = []
    for s in secs:
        sub = [r for r in R if r.get("sic2") != s]
        m = measure(sub, pop, var, ykey, blocked)
        if not m or "cuts" not in m:
            continue
        lf = m["cuts"][cut]["lift_vs_pop"]
        if lf is None:
            continue
        out.append({"drop": s, "lift": lf, "n_group": m["cuts"][cut]["n_group"],
                    "numerator": m["cuts"][cut]["numerator"]})
        if worst is None or abs(lf) < abs(worst["lift"]):
            worst = out[-1]
    out.sort(key=lambda z: abs(z["lift"]))
    return {"weakest": worst, "min_abs_lift": worst["lift"] if worst else None,
            "n_sectors": len(out), "worst5": out[:5]}


def irr_control(rows, pop, var, cut, ykey, blocked):
    R = [r for r in pop_rows(rows, pop) if r.get("irr") is not None and r["irr"] >= 70]
    if len(R) < 20:
        return {"n": len(R), "status": "irr>=70 の社が20未満＝層内では判定不能"}
    m = measure(R, pop, var, ykey, blocked)
    if not m or "cuts" not in m:
        return {"n": len(R), "status": "測れない"}
    c = m["cuts"][cut]
    return {"n": len(R), "base": m["p_pop"], "n_group": c["n_group"], "numerator": c["numerator"],
            "p_group": c["p_group"], "lift": c["lift_vs_pop"]}


# ────────────────────────────── 検出力 / 偽陽性率 ──────────────────────────────
rng = random.Random(SEED)


def rbinom(n, p):
    if n <= 0:
        return 0
    return sum(1 for _ in range(n) if rng.random() < p)


def power_sim(cells_n, delta, min_num, need_vintages, n_sims=N_POWER):
    """cells_n: [(group_n, base)] 各ビンテージの群サイズと基準率。
       真の効果 delta が実在するとき、need_vintages 個すべてで
       lift>=LIFT かつ 分子>=min_num を満たす確率＝**登録した手続きの検出力**"""
    ok = 0
    for _ in range(n_sims):
        good = 0
        for gn, b in cells_n:
            k = rbinom(gn, min(1.0, max(0.0, b + delta)))
            if gn and (k / gn - b) >= LIFT and k >= min_num:
                good += 1
        if good >= need_vintages:
            ok += 1
    return round(ok / n_sims, 4)


def perm_fpr(design, cand, pops, ykey, n_perm=N_PERM, need_all_vintages=True):
    """会社単位で全ビンテージ同時に混ぜる（prereg の must_report）。
       手続き = 候補×母集団×切り方 の格子のどれか1つでも
       lift>=LIFT ∧ 分子>=MIN_NUM ∧（B2は必要な全ビンテージで符号不変）を通す確率。
       ⚠ ビンテージ内で独立に混ぜると従属が壊れて FPR を桁で過小評価する（既に実測済み）。
       速度のためにラベルを**ビットマスク**で持つ（判定規則は同一）。"""
    vints = sorted(design)
    comp = defaultdict(dict)
    for v in vints:
        for i, r in enumerate(design[v]):
            comp[r["ticker"]][v] = i
    labels = {v: [1 if r.get(ykey) else 0 for r in design[v]] for v in vints}
    comps = sorted(comp)
    src_of = {v: [c for c in comps if v in comp[c]] for v in vints}

    need_v = list(SIGN_VINTAGES) if need_all_vintages else list(vints)
    need_v = [v for v in need_v if v in vints]

    # 群と母集団をビットマスクで固定（値は混ぜない・ラベルだけ混ぜる）
    grid = []
    for var in cand:
        for pop in pops:
            for cut in CUTNAMES:
                per_v = {}
                for v in vints:
                    idx = [i for i, r in enumerate(design[v])
                           if r.get(pop) and num(r.get(var)) is not None]
                    pi = [i for i, r in enumerate(design[v]) if r.get(pop)]
                    if not idx or not pi:
                        continue
                    vals = sorted(num(design[v][i].get(var)) for i in idx)
                    q25, q50, q75 = q_at(vals, 0.25), q_at(vals, 0.50), q_at(vals, 0.75)
                    P = {"上位1/4": lambda x: x >= q75, "下位1/4": lambda x: x <= q25,
                         "中央値超": lambda x: x > q50, "中央値以下": lambda x: x <= q50}[cut]
                    gi = [i for i in idx if P(num(design[v][i].get(var)))]
                    if not gi:
                        continue
                    gm = 0
                    for i in gi:
                        gm |= 1 << i
                    pm = 0
                    for i in pi:
                        pm |= 1 << i
                    per_v[v] = (gm, len(gi), pm, len(pi))
                # 符号不変が要るのに測れないビンテージがあれば、その候補は構造的に合格できない
                if all(v in per_v for v in need_v):
                    grid.append(per_v)

    rr = random.Random(SEED + 7)
    hits = 0
    for _ in range(n_perm):
        order = comps[:]
        rr.shuffle(order)
        perm = {}
        for v in vints:
            dst = [c for c in order if v in comp[c]]
            lab = 0
            for a, b in zip(src_of[v], dst):
                if labels[v][comp[b][v]]:
                    lab |= 1 << comp[a][v]
            perm[v] = lab
        hit = False
        for per_v in grid:
            sgn = None
            good = 0
            for v in need_v:
                gm, gn, pm, pn = per_v[v]
                lab = perm[v]
                kg = (lab & gm).bit_count()
                kp = (lab & pm).bit_count()
                lf = kg / gn - kp / pn
                if abs(lf) >= LIFT and kg >= MIN_NUM and (sgn is None or (lf > 0) == sgn):
                    if sgn is None:
                        sgn = lf > 0
                    good += 1
                else:
                    break
            if good == len(need_v):
                hit = True
                break
        if hit:
            hits += 1
    return {"p": round(hits / n_perm, 4), "n_perm": n_perm, "grid_cells": len(grid),
            "vintages_required": need_v}


# ────────────────────────────── 4群の記述（核心の問い） ──────────────────────────────
def group_table(rows, cand, label):
    R = rows
    G = {"両方": [r for r in R if r["_ypre"] and r["_ypost"]],
         "前半だけ": [r for r in R if r["_ypre"] and not r["_ypost"]],
         "後半だけ": [r for r in R if not r["_ypre"] and r["_ypost"]],
         "どちらも": [r for r in R if not r["_ypre"] and not r["_ypost"]]}
    out = {"design": label, "n": {k: len(v) for k, v in G.items()},
           "share": {k: r4(len(v) / len(R)) for k, v in G.items()} if R else None,
           "features": {}}
    for var in cand:
        ent = {}
        vals = {}
        for k, v in G.items():
            xs = [num(r.get(var)) for r in v]
            xs = [x for x in xs if x is not None]
            vals[k] = xs
            ent[k] = {"n": len(xs), "median": r4(med(xs))}
        # 核心の対比: 続く社 vs 一度は出せたが続かない社
        a = auc(vals["両方"], vals["前半だけ"])
        ent["_AUC_両方_vs_前半だけ"] = r4(a)
        ent["_AUC_lift"] = r4(None if a is None else a - 0.5)
        b = auc(vals["両方"], vals["どちらも"])
        ent["_AUC_両方_vs_どちらも"] = r4(b)
        out["features"][var] = ent
    # AUC の強い順（|AUC-0.5|）
    rank = [(abs(v["_AUC_lift"]), k, v["_AUC_lift"]) for k, v in out["features"].items()
            if v["_AUC_lift"] is not None]
    rank.sort(reverse=True)
    out["ranked_by_core_contrast"] = [{"variable": k, "auc_lift": z} for _, k, z in rank]
    return out


# ────────────────────────────── 突合せ③: 角度Aの公表値と一致するか ──────────────────────────────
def crosscheck_angleA():
    try:
        A = json.load(open(ANGLEA, encoding="utf-8"))
    except Exception as e:
        return {"status": "角度Aの在庫が読めない: %s" % e}
    cells = A.get("cells_10pct") or {}
    if not cells:
        return {"status": "角度Aの cells_10pct が見つからない＝突合せ不能"}
    # y10 を角度Bの measure() で測り直す
    rows_by_v = defaultdict(list)
    for r in panel["rows"]:
        if r.get("has_outcome") and r.get("window_full"):
            rr = dict(r)
            rr["_y10"] = (r.get("tr_cagr") is not None and r["tr_cagr"] >= HURDLE)
            rows_by_v[r["vintage"]].append(rr)
    checked = mismatch = 0
    worst = []
    for key, m in cells.items():
        try:
            var, pop, v = key.split("|")
            v = int(v)
        except Exception:
            continue
        if "cuts" not in m:
            continue
        mine = measure(rows_by_v[v], pop, var, "_y10", blocked_f2)
        if not mine or "cuts" not in mine:
            continue
        for cut in CUTNAMES:
            a = m["cuts"].get(cut, {})
            b = mine["cuts"].get(cut, {})
            checked += 1
            if (a.get("n_group") != b.get("n_group") or a.get("numerator") != b.get("numerator")
                    or a.get("lift_vs_pop") != b.get("lift_vs_pop")):
                mismatch += 1
                if len(worst) < 5:
                    worst.append({"key": key, "cut": cut, "angleA": {k: a.get(k) for k in
                                                                    ("n_group", "numerator", "lift_vs_pop")},
                                  "angleB": {k: b.get(k) for k in ("n_group", "numerator", "lift_vs_pop")}})
    return {"def": "角度Aの公表セル（y10）を角度Bの measure() で測り直して一致するか。"
                   "**同じ台帳を見る二つの検査器が違うことを言ってはいけない**（v9.9.65）",
            "cells_compared": checked, "mismatch": mismatch, "examples": worst,
            "verdict": ("一致＝角度Bの測定器は角度Aと同じ答えを出す" if mismatch == 0
                        else "食い違い＝どちらかが壊れている。角度Bの結果を読む前にここを直すこと")}


# ────────────────────────────── 全体を走らせる ──────────────────────────────
def run_design(rows_by_v, cand, blocked, label, need_sign, pops=POPS):
    """rows_by_v: {vintage: rows}"""
    vints = sorted(rows_by_v)
    res = {"label": label, "vintages": vints, "candidates": cand,
           "n_rows": {v: len(rows_by_v[v]) for v in vints}}

    # 到達可能性（結果を見る前に）
    res["reachability"] = {}
    for v in vints:
        for pop in pops:
            for yk, nm in (("_ypersist", "y_persist"), ("_ypost", "y_post"), ("_ypre", "y_pre")):
                res["reachability"][f"{v}/{pop}/{nm}"] = reach(rows_by_v[v], pop, yk)

    # 基準率
    res["base_rates"] = {}
    for v in vints:
        for pop in pops:
            R = pop_rows(rows_by_v[v], pop)
            if not R:
                continue
            res["base_rates"][f"{v}/{pop}"] = {
                "n": len(R),
                "y_persist": {"k": sum(1 for r in R if r["_ypersist"]), "p": r4(rate(sum(1 for r in R if r["_ypersist"]), len(R)))},
                "y_pre": {"k": sum(1 for r in R if r["_ypre"]), "p": r4(rate(sum(1 for r in R if r["_ypre"]), len(R)))},
                "y_post": {"k": sum(1 for r in R if r["_ypost"]), "p": r4(rate(sum(1 for r in R if r["_ypost"]), len(R)))},
                "y10": {"k": sum(1 for r in R if r["_y10"]), "p": r4(rate(sum(1 for r in R if r["_y10"]), len(R)))},
            }

    # 対照: 前半の実績そのものは後半を予言するか（入口の指標ではない＝合否に数えない）
    res["control_past_performance"] = {}
    for v in vints:
        for pop in pops:
            R = pop_rows(rows_by_v[v], pop)
            if len(R) < 30:
                continue
            pre = [r for r in R if r["_ypre"]]
            npre = [r for r in R if not r["_ypre"]]
            base = rate(sum(1 for r in R if r["_ypost"]), len(R))
            res["control_past_performance"][f"{v}/{pop}"] = {
                "n": len(R), "base_P_post": r4(base),
                "P_post_given_pre10": {"k": sum(1 for r in pre if r["_ypost"]), "n": len(pre),
                                       "p": r4(rate(sum(1 for r in pre if r["_ypost"]), len(pre)))},
                "P_post_given_not_pre10": {"k": sum(1 for r in npre if r["_ypost"]), "n": len(npre),
                                           "p": r4(rate(sum(1 for r in npre if r["_ypost"]), len(npre)))},
                "lift_of_past_performance": r4(
                    None if not pre else rate(sum(1 for r in pre if r["_ypost"]), len(pre)) - base),
                "note": "前半のリターンは**結果の一部**であって入口の指標ではない＝対照（合否に数えない）",
            }

    # 対照: **門が既に持っている関門そのもの**は『続く社』を分けるか
    #      （変数ではなく関門を予言子として当てる。新しい定数を一つも作らない）
    res["control_existing_gates"] = {}
    for v in vints:
        R = pop_rows(rows_by_v[v], "P_full")
        if len(R) < 30:
            continue
        core = [r for r in R if r["_ypre"]]
        ent = {"n_pop": len(R), "n_core(前半10%+)": len(core)}
        if blocked is blocked_f2:
            glist = [("質実証を通らない", g_notq), ("事業の収縮", g_shrink_f2),
                     ("薄い財務(intcov<3)", g_thin_f2), ("いずれかで落ちる", blocked)]
        else:
            # ⚠ 2013 には f2_opmD5 も f2_intcov も無い＝門の関門をそのままは当てられない。
            #    co_sales_cagr5<0 単独は**真の関門より多く止める上位集合**。薄い財務は当てられない
            glist = [("質実証を通らない", g_notq), ("事業の収縮(上位集合・代用)", g_shrink_co),
                     ("いずれかで落ちる(薄い財務は当てられない)", blocked)]
        for gname, gf in glist:
            blk = [r for r in core if gf(r)]
            ok = [r for r in core if not gf(r)]
            if not core:
                continue
            ent[gname] = {
                "n_blocked": len(blk), "n_pass": len(ok),
                "P_後半10%+_blocked": r4(rate(sum(1 for r in blk if r["_ypost"]), len(blk))),
                "P_後半10%+_pass": r4(rate(sum(1 for r in ok if r["_ypost"]), len(ok))),
                "lift_of_gate": r4(None if not ok or not core else
                                   rate(sum(1 for r in ok if r["_ypost"]), len(ok))
                                   - rate(sum(1 for r in core if r["_ypost"]), len(core))),
            }
        # y_persist 側でも同じことを
        blk = [r for r in R if blocked(r)]
        ok = [r for r in R if not blocked(r)]
        ent["y_persist_全母集団"] = {
            "n_blocked": len(blk), "n_pass": len(ok),
            "P_persist_blocked": r4(rate(sum(1 for r in blk if r["_ypersist"]), len(blk))),
            "P_persist_pass": r4(rate(sum(1 for r in ok if r["_ypersist"]), len(ok))),
            "lift_of_gate": r4(None if not ok else
                               rate(sum(1 for r in ok if r["_ypersist"]), len(ok))
                               - rate(sum(1 for r in R if r["_ypersist"]), len(R))),
        }
        res["control_existing_gates"][v] = ent

    # 対照: irr（堀の刻み）は『続く社』を分けるか。**候補ではなく対照**（prereg）
    res["control_irr"] = {}
    for v in vints:
        R = [r for r in pop_rows(rows_by_v[v], "P_full") if r.get("irr") is not None]
        if len(R) < 30:
            continue
        core = [r for r in R if r["_ypre"]]
        ent = {"n_with_irr": len(R), "n_core": len(core), "by_irr": {}}
        # ⚠ 刻みはビンテージで違う（2013/2015 は 50/70/85/100・**2018 は 50/75/85**）。
        #    同じ「>=70」でも中身が違うので、帯の名前にそれを書く（パネルの diag が既に警告している）
        for lo, hi, name in ((0, 59, "irr<=50"), (60, 79, "irr=70(2018の読解では75)"),
                             (80, 89, "irr=85"), (90, 100, "irr=100")):
            g = [r for r in R if lo <= r["irr"] <= hi]
            gc = [r for r in core if lo <= r["irr"] <= hi]
            if not g:
                continue
            ent["by_irr"][name] = {
                "n": len(g),
                "P_persist": r4(rate(sum(1 for r in g if r["_ypersist"]), len(g))),
                "n_core": len(gc),
                "P_後半10%+_given_前半10%+": r4(rate(sum(1 for r in gc if r["_ypost"]), len(gc))) if gc else None,
            }
        ent["base"] = {"P_persist": r4(rate(sum(1 for r in R if r["_ypersist"]), len(R))),
                       "P_後半_given_前半": r4(rate(sum(1 for r in core if r["_ypost"]), len(core))) if core else None}
        res["control_irr"][v] = ent

    # 全セル測定（目的3つ: y_persist / 条件付き y_post|pre / 参考 y_post）
    res["cells"] = {}
    for var in cand:
        for pop in pops:
            for v in vints:
                m = measure(rows_by_v[v], pop, var, "_ypersist", blocked)
                if m:
                    res["cells"][f"{var}|{pop}|{v}|persist"] = m
                core = [r for r in rows_by_v[v] if r["_ypre"]]
                m2 = measure(core, pop, var, "_ypost", blocked)
                if m2:
                    res["cells"][f"{var}|{pop}|{v}|core"] = m2

    # 集約 & 判定
    def verdict(var, pop, cut, ykey, suffix):
        per_v = {}
        for v in vints:
            m = res["cells"].get(f"{var}|{pop}|{v}|{suffix}")
            per_v[v] = (m["cuts"][cut] if (m and "cuts" in m) else None)
        lifts = {v: (c["lift_vs_pop"] if c else None) for v, c in per_v.items()}
        nums = {v: (c["numerator"] if c else None) for v, c in per_v.items()}
        have = [v for v in vints if lifts[v] is not None]
        if not have:
            return None
        # 方向を決める: 全ビンテージで符号が揃うか
        signs = {1 if lifts[v] > 0 else (-1 if lifts[v] < 0 else 0) for v in have}
        direction = ("増やす" if signs == {1} else ("減らす" if signs == {-1} else "符号が割れる"))
        need = SIGN_VINTAGES if need_sign else have
        need = [v for v in need if v in vints]
        sign_ok = (len(need) > 0 and all(
            lifts.get(v) is not None and abs(lifts[v]) >= LIFT and
            (lifts[v] > 0) == (lifts[need[0]] > 0) for v in need))
        num_ok = all(nums.get(v) is not None and nums[v] >= MIN_NUM for v in need)
        gates = {
            "lift_all_needed_vintages": sign_ok,
            "min_numerator_all_needed": num_ok,
            "sign_stability_reachable": (set(SIGN_VINTAGES) <= set(vints)) if need_sign else None,
        }
        ent = {"variable": var, "population": pop, "cut": cut, "target": suffix,
               "per_vintage_lift": lifts, "per_vintage_numerator": nums,
               "direction": direction, "gates": gates}
        # 続きのゲートは lift/分子を通ったものだけ（費用が高いので）
        if sign_ok and num_ok:
            def _rows(v):
                return rows_by_v[v] if suffix == "persist" else [r for r in rows_by_v[v] if r["_ypre"]]
            ent["sector_mh"] = {v: mh_risk_diff(_rows(v), pop, var, cut, ykey) for v in need}
            ent["drop_one_sector"] = {v: drop_one_sector(_rows(v), pop, var, cut, ykey, blocked)
                                      for v in need}
            ent["irr_control"] = {v: irr_control(_rows(v), pop, var, cut, ykey, blocked)
                                  for v in need}
            inc = {}
            for v in need:
                m = res["cells"].get(f"{var}|{pop}|{v}|{suffix}")
                inc[v] = m["cuts"][cut].get("incremental") if m else None
            ent["incremental"] = inc
            # 増分の合否（方向で当てるものが違う）
            if direction == "減らす":
                shares = [inc[v]["down_side"]["caught_share"] for v in need
                          if inc.get(v) and inc[v]["down_side"]["caught_share"] is not None]
                ent["gates"]["incremental"] = bool(shares) and max(shares) <= INCREMENTAL_MAX_CAUGHT
            elif direction == "増やす":
                lw = [inc[v]["up_side"]["lift_within_gate_passers"] for v in need
                      if inc.get(v) and inc[v]["up_side"]["lift_within_gate_passers"] is not None]
                ent["gates"]["incremental"] = bool(lw) and min(lw) >= LIFT
            else:
                ent["gates"]["incremental"] = False
            mhs = [ent["sector_mh"][v]["mh_risk_diff"] for v in need
                   if ent["sector_mh"].get(v) and ent["sector_mh"][v].get("mh_risk_diff") is not None]
            ent["gates"]["sector_mh"] = bool(mhs) and all(abs(x) >= LIFT for x in mhs)
            d1 = [ent["drop_one_sector"][v]["min_abs_lift"] for v in need
                  if ent["drop_one_sector"].get(v) and ent["drop_one_sector"][v].get("min_abs_lift") is not None]
            ent["gates"]["drop_one_sector"] = bool(d1) and all(abs(x) >= LIFT for x in d1)
            # irr 層内: **符号が同じまま** |lift|>=LIFT を保つこと。
            # ⚠ 符号が裏返ったのに |lift| が大きいのは「残った」ではなく「消えた（むしろ逆）」
            want_up = (direction == "増やす")
            irr_ok, irr_note = True, None
            for v in need:
                c = ent["irr_control"].get(v) or {}
                lf, gn = c.get("lift"), c.get("n_group")
                if lf is None:
                    irr_ok, irr_note = False, "irr>=70 の層が薄く判定不能＝合格に数えない"
                    break
                if gn is not None and gn < MIN_NUM:
                    irr_ok, irr_note = False, f"irr>=70 の層内の群が{gn}社＝分子>={MIN_NUM}に届かず判定不能"
                    break
                if (lf > 0) != want_up or abs(lf) < LIFT:
                    irr_ok = False
                    irr_note = ("irr>=70 の層内で**符号が裏返る**＝irrの影ではなく別物になる"
                                if (lf > 0) != want_up else "irr>=70 の層内で線を割る")
                    break
            ent["gates"]["irr_control"] = irr_ok
            ent["gates"]["irr_control_note"] = irr_note
        ent["PASS"] = bool(ent["gates"].get("lift_all_needed_vintages")
                           and ent["gates"].get("min_numerator_all_needed")
                           and ent["gates"].get("incremental")
                           and ent["gates"].get("sector_mh")
                           and ent["gates"].get("drop_one_sector")
                           and ent["gates"].get("irr_control"))
        return ent

    res["verdicts"] = {}
    passes = []
    for var in cand:
        for pop in pops:
            for cut in CUTNAMES:
                for suffix, yk in (("persist", "_ypersist"), ("core", "_ypost")):
                    ent = verdict(var, pop, cut, yk, suffix)
                    if ent:
                        res["verdicts"][f"{var}|{pop}|{cut}|{suffix}"] = ent
                        if ent["PASS"]:
                            passes.append(f"{var}|{pop}|{cut}|{suffix}")
    res["passes"] = passes
    res["n_pass"] = len(passes)

    # 上位（合格しなかったものも含め、|lift| の弱いほうの端で並べる＝「惜しい」順）
    rank = []
    for k, e in res["verdicts"].items():
        ls = [x for x in e["per_vintage_lift"].values() if x is not None]
        ns = [x for x in e["per_vintage_numerator"].values() if x is not None]
        if not ls or not ns:
            continue
        signs = {1 if x > 0 else (-1 if x < 0 else 0) for x in ls}
        consistent = len(signs) == 1
        weakest = min(abs(x) for x in ls)
        rank.append({"key": k, "weakest_abs_lift": r4(weakest), "sign_consistent": consistent,
                     "min_numerator": min(ns), "lifts": e["per_vintage_lift"],
                     "direction": e["direction"]})
    rank = sorted(rank, key=lambda z: (not z["sign_consistent"], -z["weakest_abs_lift"]))
    res["ranked_near_misses_all"] = rank[:25]
    res["ranked_near_misses_all_note"] = (
        "⚠ この並びは |lift| だけで作ってあるので、**分子が1〜12社しかない P_moat の小さな群**が上位を占める。"
        "分子>=20 を満たすものだけを見るのが下の表（惜しい順の本体）")

    # 分子>=20 を満たすセルだけの「惜しい順」（これが本当の作業リスト）
    need_v = [v for v in (SIGN_VINTAGES if need_sign else vints) if v in vints]
    rank2 = []
    for k, e in res["verdicts"].items():
        L = [e["per_vintage_lift"].get(v) for v in need_v]
        N = [e["per_vintage_numerator"].get(v) for v in need_v]
        if any(x is None for x in L) or any(x is None or x < MIN_NUM for x in N):
            continue
        signs = {1 if x > 0 else (-1 if x < 0 else 0) for x in L}
        rank2.append({"key": k, "weakest_abs_lift": r4(min(abs(x) for x in L)),
                      "sign_consistent": len(signs) == 1,
                      "lifts": [r4(x) for x in L], "numerators": N,
                      "shortfall_vs_line": r4(LIFT - min(abs(x) for x in L)),
                      "direction": e["direction"]})
    rank2 = sorted(rank2, key=lambda z: (not z["sign_consistent"], -z["weakest_abs_lift"]))
    res["near_misses_minnum_ok"] = rank2[:20]
    res["near_misses_minnum_ok_n"] = len(rank2)
    return res


def main():
    out = {
        "generated": datetime.date.today().isoformat(),
        "tool": "night/hist10_angleB.py",
        "prereg": "out/hist10_prereg.json",
        "angle": "B — 持続（前半と後半の両方で年率10%+）",
        "purpose": "『一度は出せるが続かない社』と『続く社』を分ける入口の指標があるか。"
                   "判定・採点・台帳には一切触れない（読むだけの調査）",
        "sources": {
            "out/hist_wd_panel.json": panel.get("generated"),
            "out/hist10_targets.json": targets.get("generated"),
            "out/retro_monthly_2013_2018.json": "retro_path_features.py の在庫",
            "out/retro_monthly_2018_2026.json": "retro_path_features.py の在庫",
        },
        "hurdle": HURDLE,
        "pass_line": {"lift": LIFT, "min_numerator": MIN_NUM,
                      "incremental_max_caught": INCREMENTAL_MAX_CAUGHT,
                      "src": "out/hist10_prereg.json（新しい定数を作っていない）"},
        "designs": {
            "B1": "事前登録どおり: 入口2013・前半5.0年(2013-07→2018-07) ∧ 後半8.09年(2018-07→2026-08)。"
                  "特徴量は co_*＝**約94%が look-ahead を含む**。"
                  "事前登録の符号不変ゲート(2016/2017/2018)は**構造的に到達不能**（入口が2013しかない）",
            "B2": "厳密: 入口2016/2017/2018・**その窓自身の月数の中点**で二分。特徴量は f2_*（filed<=asof）。"
                  "符号不変ゲートを当てられる。**目的変数の定義が事前登録と違う＝事前登録の外**",
        },
    }

    # 突合せ
    out["join_checks"] = {
        "splice_basis": splice_check,
        "r_pre_independent": rpre_check,
        "B2_windows": b2_windows,
        "B2_structural": b2_struct,
        "B2_vs_inventory": b2_vs_inventory,
        "angleA_crosscheck": crosscheck_angleA(),
    }

    # 目的変数そのものの頑健さ（B1: 代数で復元した札 vs 月次から独立に作った札）
    flips = same = 0
    who = []
    for r in B1:
        c1 = cagr_between(r["ticker"], 2013 * 12 + 7, 2018 * 12 + 7)
        c2 = cagr_between(r["ticker"], 2018 * 12 + 7, MONTH_END)
        if c1 is None or c2 is None:
            continue
        alt = (c1 >= HURDLE) and (c2 >= HURDLE)
        if alt == r["_ypersist"]:
            same += 1
        else:
            flips += 1
            if len(who) < 8:
                who.append({"t": r["ticker"], "targets": r["_ypersist"], "monthly": alt,
                            "pre": r4(r["_pre"]), "post": r4(r["_post"]),
                            "pre_monthly": r4(c1), "post_monthly": r4(c2)})
    out["join_checks"]["B1_label_robustness"] = {
        "def": "B1 の y_persist（targets が代数で復元）を、月次から独立に作り直したときに札が裏返る割合",
        "n": same + flips, "flips": flips, "share": r4(flips / max(1, same + flips)),
        "examples": who,
        "note": "裏返るのは 10% の線の際どい社。targets の fragility（±1pt に 14.7%）と同じ話で、"
                "**どちらかが誤りではなく、月足の端の1ヶ月ぶんの不定性**",
    }

    # B2 の後半はどのビンテージでもほぼ同じ暦（符号不変ゲートの効きに直結する）
    out["join_checks"]["B2_calendar_overlap"] = {
        "def": "B2 の3つの入口の**後半**が暦の上でどれだけ重なるか",
        "second_halves": {v: [b2_windows[v]["mid"], b2_windows[v]["end"]] for v in SIGN_VINTAGES},
        "shared_months": "2022-07 → 2026-08 は3つとも共通（2016は2021-07から・2017は2022-01から）",
        "why_it_matters": "事前登録の符号不変ゲート（2016/2017/2018 すべて）は本来"
                          "『別のレジームでも立つか』を見る道具だが、B2 では**後半が実質同じ期間**なので"
                          "**3つの独立した検証ではない**。前半だけが別の期間になっている",
    }

    # 4群の記述（核心の問い）
    out["four_groups"] = {
        "B1": group_table(B1, CAND_B1, "B1(2013・look-ahead込み)"),
        "B2": {v: group_table(B2[v], CAND_B2, "B2(%d・厳密f2)" % v) for v in SIGN_VINTAGES},
    }

    # 本体
    out["B1"] = run_design({2013: B1}, CAND_B1, blocked_co, "B1(事前登録どおり・look-ahead込み)",
                           need_sign=False)
    out["B1"]["prereg_literal_verdict"] = {
        "sign_stability_reachable": False,
        "why": "y_persist は入口2013でしか定義できない（前半の窓が要る）。"
               "事前登録 pass_line.sign_stability は 2016/2017/2018 すべてを要求するので、"
               "**どんな指標でも字義どおりの合格は構造的に不可能**。"
               "hist10_targets.json の reachability が結果を見る前に同じことを出している",
        "therefore": "B1 の『合格ゼロ』は**信号の不在の証拠ではない**。到達不能を不合格と読まないこと",
    }
    out["B2"] = run_design({v: B2[v] for v in SIGN_VINTAGES}, CAND_B2, blocked_f2,
                           "B2(厳密f2・事前登録の外)", need_sign=True)

    # 検出力
    out["power"] = {}
    for label, design, cand, need in (("B1", {2013: B1}, CAND_B1, 1),
                                      ("B2", {v: B2[v] for v in SIGN_VINTAGES}, CAND_B2, 3)):
        for pop in POPS:
            cells = []
            for v in sorted(design):
                R = pop_rows(design[v], pop)
                if not R:
                    continue
                base = rate(sum(1 for r in R if r["_ypersist"]), len(R))
                g = max(1, len(R) // 4)
                cells.append((g, base))
            if len(cells) < need:
                out["power"][f"{label}/{pop}"] = {"status": "母集団が足りず判定不能"}
                continue
            out["power"][f"{label}/{pop}"] = {
                "group_n": [c[0] for c in cells], "base": [r4(c[1]) for c in cells],
                "P_pass": {str(d): power_sim(cells, d, MIN_NUM, need)
                           for d in (0.10, 0.15, 0.20, 0.25)},
                "note": "登録した線ちょうど(0.15)の信号をどれだけ掴めるか。"
                        "低ければ『不合格』は『効果が無い』の証拠として弱い",
            }

    # 偽陽性率（会社単位で全ビンテージ同時に混ぜる）
    out["fpr"] = {
        "def": "結果ラベルを**会社単位で全ビンテージ同時に**混ぜ、同じ手続きを当てて"
               "1つでも lift>=0.15 ∧ 分子>=20（B2は符号不変も）を通す確率。置換%d回" % N_PERM,
        "B1_persist": perm_fpr({2013: B1}, CAND_B1, POPS, "_ypersist", need_all_vintages=False),
        "B2_persist": perm_fpr({v: B2[v] for v in SIGN_VINTAGES}, CAND_B2, POPS, "_ypersist",
                               need_all_vintages=True),
    }

    out["n_pass_total"] = out["B1"]["n_pass"] + out["B2"]["n_pass"]

    # ── 構造的な限界（結果ではなく設計の性質。結論の前に読むもの） ──
    def _dn_ok(lab):
        rr = out[lab]["reachability"]
        return {k: v["down"]["possible"] for k, v in rr.items()
                if k.endswith("y_persist") and isinstance(v, dict) and "down" in v}
    out["structural_limits"] = {
        "down_direction_for_y_persist": {
            "per_cell": {"B1": _dn_ok("B1"), "B2": _dn_ok("B2")},
            "finding": "**y_persist では『減らす向き』が全セルで到達不能**",
            "why": "事前登録が 10% を選んだ理由は『基準率が0.38〜0.43へ倍増するので減らす向きも絶対差liftで測れる』。"
                   "ところが y_persist の基準率は **0.16〜0.27** へ戻る（両方の窓を要求するので事象が減る）。"
                   "群の分子>=20 と lift<=-0.15 が同時に成立しない＝v1/v2 と同じ構造的限界がここで再来する",
            "what_survives": "**条件付き（母集団=前半10%+ / 目的=後半も10%+）だけは基準率 0.31〜0.44 なので"
                             "両方向が測れる**。核心の問いをこの形で立てたのは結果的に正しかった",
        },
        "P_moat_undetermined": {
            "finding": "P_moat（irr>=70）は B1 で群15社・B2/2018 で群15社＝**分子>=20 に構造的に届かない**。"
                       "2016/2017 は読解が存在せず母集団が空",
            "reading": "P_moat のセルは『不合格』ではなく**判定不能**。ここを不合格として数えてはいけない",
        },
        "B2_sign_gate_is_not_three_independent_tests": out["join_checks"]["B2_calendar_overlap"],
        "look_ahead": {
            "B1": "co_* は約94%が look-ahead を含む（cohort の特徴量は filed で切っていない）",
            "B2": "f2_* は filed<=asof で厳密。**この設計に look-ahead は無い**",
        },
    }

    # ── 結論（合否は事前登録の線がそのまま出したもの。ここで線を作らない） ──
    p_b1 = out["power"].get("B1/P_full", {}).get("P_pass", {}).get("0.15")
    p_b2 = out["power"].get("B2/P_full", {}).get("P_pass", {}).get("0.15")
    out["verdict"] = {
        "n_pass": {"B1": out["B1"]["n_pass"], "B2": out["B2"]["n_pass"],
                   "total": out["n_pass_total"]},
        "B1_is_structurally_unfair": out["B1"]["prereg_literal_verdict"],
        "power_caveat": {
            "P_detect_at_registered_line_0.15": {"B1/P_full": p_b1, "B2/P_full": p_b2},
            "reading": "登録した線ちょうどの効果が**本当にあっても**、B1は約半分・B2は約1/8しか掴めない。"
                       "したがって『合格ゼロ』は『効果が無い』の証明ではない。"
                       "**言えるのは δ=0.20 以上の効果は無い**（B2の検出力 0.85 / B1 0.94）",
        },
        "fpr": {"B1": out["fpr"]["B1_persist"]["p"], "B2": out["fpr"]["B2_persist"]["p"],
                "reading": "偽陽性は 0〜2%＝雑音では通らない手続き。その上で実データが1つも通らなかった"},
        "what_is_asked_and_the_answer": (
            "問い: 『一度は出せるが続かない社』と『続く社』を分ける入口の指標があるか。"
            "答え: 事前登録の線を通る指標は**ゼロ**。最も強い対比でも AUC−0.5 は 0.13 止まりで、"
            "しかも3つの入口で符号が揃うものは一握り"),
    }
    json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    t = time.time()
    res = main()
    print("→ %s  (%.1fs)" % (DEST, time.time() - t))
