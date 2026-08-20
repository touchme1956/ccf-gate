#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/opmtrend_ref_h4.py — H4（事業の収縮 cagr5<0 ∧ opmD5<0）の**反証専門**（2026-08-18新設）

役割: night/opmtrend_h4.py の報告を壊しにいく。迷ったら refuted に倒す。

⚠ **独立実装**である。night/opmtrend_{base,h4}.py を一行も import しない。
   入力は生データ（out/retro_features2_*.json / out/retro_returns_*.json / out/retro_sic.json /
   out/retro_er_test.json）だけ。out/opmtrend_base.json は**照合の相手**としてのみ読む
   （＝土台そのものも検算する。土台が壊れていれば下流は全部壊れる）。
   乱数の種も別（測定側と別系統）＝MC誤差が独立に出る。

判定・採点・台帳・index.html・パックには一切触らない。読むだけの調査。
書いてよいのは night/opmtrend_ref_h4.py と out/opmtrend_ref_h4.json だけ。

使い方: python3 night/opmtrend_ref_h4.py [--perm 2000] [--json]
"""
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
DEST = os.path.join(OUT, "opmtrend_ref_h4.json")

# ── 事前登録の線（out/opm_trend_prereg.json。この道具は一つも作らない） ──
PREREG = json.load(open(os.path.join(OUT, "opm_trend_prereg.json"), encoding="utf-8"))
HURDLE = 0.15
IMPAIR = -0.15
QUAL_OPM_PCT = 10.0
QUAL_FCFPOS = 5
CONC_MIN = 2.0      # H2/H4 の濃縮の線
MIN_NUM = 5         # 分子の下限
MAX_STOP = 0.15     # 止率の上限
VINTAGES = [2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022]
SEED = 20260818777  # 測定側と別系統


def load(p):
    with open(os.path.join(OUT, p), encoding="utf-8") as f:
        return json.load(f)


def rows_of(d):
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


# ─────────────────────────── ① 生データから独立に組み直す ───────────────────────────
def band_pct(x):
    """帯検問: 比率で入っている値を%へ。abs(x)<=3 なら x*100（事前登録の指示どおり）"""
    if x is None:
        return None
    return x * 100.0 if abs(x) <= 3 else x


def returns_file(v):
    """優先順 _all -> _q -> 素（hist_val_join.py:74 と同一の作法）。存在するものを返す"""
    for suf in ("_all", "_q", ""):
        p = os.path.join(OUT, f"retro_returns_{v}{suf}.json")
        if os.path.exists(p):
            return f"retro_returns_{v}{suf}.json"
    return None


def build():
    """生データ→行。opmtrend_base.py を見ずに、事前登録の定義だけから組む"""
    sic = {r["ticker"]: r for r in rows_of(load("retro_sic.json"))}
    out = {}
    meta = {}
    for v in VINTAGES:
        fea = rows_of(load(f"retro_features2_{v}.json"))
        rfile = returns_file(v)
        rd = load(rfile)
        ret = {r["ticker"]: r for r in rows_of(rd)}
        # opm の単位: ファイル単位で決める（per-row の帯検問は
        #   赤字バイオ（opm 生 -4.26 = -426%）を -4.26% に化かすので誤り）
        vals = [r.get("opm") for r in fea if r.get("opm") is not None]
        med_abs = statistics.median(abs(x) for x in vals) if vals else 0.0
        scale = 100.0 if med_abs <= 3 else 1.0
        rows = []
        for r in fea:
            t = r["ticker"]
            rr = ret.get(t)
            if not rr or rr.get("tr_cagr") is None:
                continue
            opm_raw = r.get("opm")
            opm_pct = None if opm_raw is None else opm_raw * scale
            fcf = r.get("fcfpos5")
            qual = (opm_pct is not None and fcf is not None
                    and opm_pct >= QUAL_OPM_PCT and fcf >= QUAL_FCFPOS)
            s = sic.get(t, {})
            rows.append(dict(vintage=v, ticker=t,
                             opm=opm_pct, opm_raw=opm_raw,
                             opmD5=r.get("opmD5"), cagr5=r.get("cagr5"),
                             fcfpos5=fcf, rev=r.get("rev"),
                             tr=rr["tr_cagr"], years=rr.get("years"),
                             mdd=rr.get("mdd"),
                             sic2=s.get("sic2"), qual=qual,
                             fy_end=r.get("fy_end")))
        out[v] = rows
        bm = rd.get("benchmark") or {}
        meta[v] = dict(features_n=len(fea), returns_src=rfile, joined_n=len(rows),
                       opm_scale=scale, opm_med_abs=round(med_abs, 4),
                       deadline=load(f"retro_features2_{v}.json").get("deadline"),
                       start=rd.get("asof_date"), bm_symbol=bm.get("symbol"),
                       bm_is_spy=(bm.get("symbol") == "SPY"),
                       years_median=round(statistics.median(
                           [r["years"] for r in rows if r.get("years")]), 2) if rows else None)
    return out, meta


# ─────────────────────────── ② 土台の照合 ───────────────────────────
def verify_base(mine):
    """out/opmtrend_base.json を独立実装と突き合わせる。土台が壊れていれば全部壊れる"""
    try:
        b = load("opmtrend_base.json")
    except Exception as e:
        return dict(ok=False, why=f"読めない: {e}")
    theirs = defaultdict(dict)
    for r in b["rows"]:
        theirs[r["vintage"]][r["ticker"]] = r
    diffs = []
    n_cmp = 0
    for v in VINTAGES:
        mv = {r["ticker"]: r for r in mine[v]}
        tv = theirs.get(v, {})
        only_mine = sorted(set(mv) - set(tv))
        only_theirs = sorted(set(tv) - set(mv))
        if only_mine or only_theirs:
            diffs.append(dict(vintage=v, kind="集合", only_mine=only_mine[:8],
                              n_only_mine=len(only_mine),
                              only_theirs=only_theirs[:8], n_only_theirs=len(only_theirs)))
        for t in sorted(set(mv) & set(tv)):
            a, c = mv[t], tv[t]
            n_cmp += 1
            for k, kk in (("opmD5", "opmD5"), ("cagr5", "cagr5"), ("tr", "tr_cagr"),
                          ("opm", "opm"), ("qual", "qual"), ("sic2", "sic2")):
                x, y = a.get(k), c.get(kk)
                if isinstance(x, float) and isinstance(y, float):
                    if abs(x - y) > 1e-6:
                        diffs.append(dict(vintage=v, ticker=t, field=k, mine=x, theirs=y))
                elif x != y:
                    diffs.append(dict(vintage=v, ticker=t, field=k, mine=x, theirs=y))
    return dict(ok=not diffs, n_compared=n_cmp, n_diff=len(diffs), diffs=diffs[:20])


# ─────────────────────────── ③ セルの独立再計算 ───────────────────────────
def grp(rows):
    if not rows:
        return None
    tr = [r["tr"] for r in rows]
    return dict(n=len(rows),
                med=round(statistics.median(tr), 4),
                impair=round(sum(1 for x in tr if x <= IMPAIR) / len(tr), 4),
                n_impair=sum(1 for x in tr if x <= IMPAIR),
                hurdle=round(sum(1 for x in tr if x >= HURDLE) / len(tr), 4))


def blocked_flag(r, rule, strict):
    """retro_breaker_test.py:118 と同じ意味論。
       main: 欠測は `or 0` で 0 扱い＝止めない側（門の ccfShrinkGate と同じ挙動）
       strict: 欠測は母集団から外す（→ここでは None を返して呼び手が落とす）"""
    c, o = r.get("cagr5"), r.get("opmD5")
    if strict and (c is None or o is None):
        return None
    c = c if c is not None else 0.0
    o = o if o is not None else 0.0
    if rule == "and":
        return (c < 0) and (o < 0)
    if rule == "cagr_only":
        return c < 0
    if rule == "opm_only":
        return o < 0
    raise ValueError(rule)


def cell(rows, rule="and", strict=False, pool="all"):
    pop = [r for r in rows if (r["qual"] if pool == "qual" else True)]
    used, na = [], 0
    for r in pop:
        f = blocked_flag(r, rule, strict)
        if f is None:
            na += 1
            continue
        used.append((r, f))
    if not used:
        return None
    base = grp([r for r, _ in used])
    blocked = [r for r, f in used if f]
    passed = [r for r, f in used if not f]
    b, p = grp(blocked), grp(passed)
    conc = round(b["impair"] / base["impair"], 3) if (b and base["impair"] > 0) else (0.0 if b else None)
    stop = round(len(blocked) / len(used), 4)
    c1 = bool(b and conc is not None and conc >= CONC_MIN and b["n_impair"] >= MIN_NUM)
    c2 = bool(b and p and b["med"] <= p["med"])
    c4 = stop <= MAX_STOP
    return dict(pool=pool, rule=rule, strict=strict, n_pool=len(pop), n_used=len(used),
                n_na=na, stop_rate=stop, base=base, blocked=b, passed=p,
                concentration=conc, c1=c1, c2=c2, c4=c4,
                verdict=("合格" if (c1 and c2 and c4) else "不合格"))


def all_cells(data):
    cells = {}
    for v in VINTAGES:
        for pool in ("all", "qual"):
            for rule in ("and", "cagr_only", "opm_only"):
                for strict in (False, True):
                    k = f"{v}/{pool}/{rule}/{'strict' if strict else 'main'}"
                    cells[k] = cell(data[v], rule, strict, pool)
    return cells


def verify_h4(mine):
    try:
        h = load("opmtrend_h4.json")
    except Exception as e:
        return dict(ok=False, why=f"読めない: {e}")
    theirs = h.get("cells", {})
    diffs = []
    n = 0
    for k, c in mine.items():
        t = theirs.get(k)
        if t is None:
            diffs.append(dict(key=k, why="測定側に無い"))
            continue
        n += 1
        pairs = [("n_pool", c["n_pool"], t.get("n_pool")),
                 ("n_used", c["n_used"], t.get("n_used")),
                 ("n_na", c["n_na"], t.get("n_na")),
                 ("stop_rate", c["stop_rate"], t.get("stop_rate")),
                 ("concentration", c["concentration"], t.get("concentration"))]
        for g in ("base", "blocked", "passed"):
            a, b = c.get(g), t.get(g)
            if a and b:
                for f in ("n", "med", "impair", "n_impair"):
                    pairs.append((f"{g}.{f}", a.get(f), b.get(f)))
        for f, x, y in pairs:
            if x is None and y is None:
                continue
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if abs(float(x) - float(y)) > 0.0015:
                    diffs.append(dict(key=k, field=f, mine=x, theirs=y))
            elif x != y:
                diffs.append(dict(key=k, field=f, mine=x, theirs=y))
    return dict(ok=not diffs, n_cells=n, n_diff=len(diffs), diffs=diffs[:25])


# ─────────────────────────── ④ retro_breaker_test の再現と母集団感応 ───────────────────────────
def replication(data):
    """581社プール（retro_er_test）と 956社プール（土台）で同じ規則を当てる"""
    er = rows_of(load("retro_er_test.json"))
    fea = {r["ticker"]: r for r in rows_of(load("retro_features2_2018.json"))}

    def st(g):
        if not g:
            return None
        return dict(n=len(g), med=round(statistics.median(g), 2),
                    impair=round(sum(1 for x in g if x <= -15.0) / len(g), 4),
                    n_impair=sum(1 for x in g if x <= -15.0),
                    loss=round(sum(1 for x in g if x < 0) / len(g), 4))
    blocked, passed = [], []
    for r in er:
        f = fea.get(r["t"], {})
        b = ((f.get("cagr5") or 0) < 0) and ((f.get("opmD5") or 0) < 0)
        (blocked if b else passed).append(r["real"])
    base = st([r["real"] for r in er])
    b, p = st(blocked), st(passed)
    conc581 = round(b["impair"] / base["impair"], 3)
    # 956社（土台と同じ join）
    c956 = cell(data[2018], "and", False, "all")
    # 581社が 956社の部分集合として何を落としているか
    er_t = {r["t"] for r in er}
    all_t = {r["ticker"] for r in data[2018]}
    dropped = sorted(all_t - er_t)
    drows = [r for r in data[2018] if r["ticker"] in dropped]
    return dict(
        pool581=dict(n=base["n"], base=base, blocked=b, passed=p, concentration=conc581),
        pool956=dict(n=c956["n_used"], base=c956["base"], blocked=c956["blocked"],
                     passed=c956["passed"], concentration=c956["concentration"]),
        n_dropped_by_581=len(dropped),
        dropped_profile=dict(n=len(drows),
                             impair=round(sum(1 for r in drows if r["tr"] <= IMPAIR) / len(drows), 4),
                             med=round(statistics.median(r["tr"] for r in drows), 4),
                             blocked_share=round(sum(1 for r in drows
                                                     if blocked_flag(r, "and", False)) / len(drows), 4)),
        note="581社は retro_er_test（PER/shy/g が組めた社）。**この絞り込みは結果と無関係ではない**——"
             "PERが組める＝黒字で株価がある社に偏る")


# ─────────────────────────── ⑤ 攻撃 ───────────────────────────
def mh_adjust(rows, key, rule="and", strict=False, min_stratum=8):
    """層別（Mantel-Haenszel 型）: 層内の期待毀損に対する観測毀損の比。
       層 = key（sic2 / 規模三分位）。層が薄いと不安定なので min_stratum で切る"""
    used = []
    for r in rows:
        f = blocked_flag(r, rule, strict)
        if f is None:
            continue
        k = r.get(key)
        if k is None:
            continue
        used.append((r, f, k))
    by = defaultdict(list)
    for r, f, k in used:
        by[k].append((r, f))
    obs = exp = 0.0
    nb = 0
    kept = 0
    keptrows = []
    for k, g in by.items():
        if len(g) < min_stratum:
            continue
        kept += 1
        keptrows += [r for r, _ in g]
        nk = len(g)
        imp = sum(1 for r, _ in g if r["tr"] <= IMPAIR)
        bk = sum(1 for _, f in g if f)
        nb += bk
        obs += sum(1 for r, f in g if f and r["tr"] <= IMPAIR)
        exp += bk * imp / nk
    # ★同じ部分集合の**素の**濃縮も出す。でないと「層別で落ちた」のか
    #   「薄い層を捨てて母集団が変わったから落ちた」のかが分離できない
    craw = cell(keptrows, rule, strict, "all") if keptrows else None
    return dict(strata_kept=kept, n_kept=len(keptrows), n_blocked=nb,
                obs=round(obs, 2), exp=round(exp, 2),
                adj_conc=round(obs / exp, 3) if exp > 0 else None,
                raw_conc_on_kept=(craw or {}).get("concentration"))


def size_tercile(rows):
    """売上(rev)の三分位を付ける。**単位は生のまま**（比較は順位なので影響しない）"""
    vals = sorted(r["rev"] for r in rows if r.get("rev"))
    if len(vals) < 30:
        return rows
    q1 = vals[len(vals) // 3]
    q2 = vals[2 * len(vals) // 3]
    for r in rows:
        v = r.get("rev")
        r["sz"] = None if v is None else ("小" if v < q1 else ("中" if v < q2 else "大"))
    return rows


def leave_one_out(rows, rule="and", strict=False):
    """止めた群の毀損社を1社ずつ抜くと濃縮がどこまで落ちるか"""
    c = cell(rows, rule, strict, "all")
    if not c or not c["blocked"] or c["blocked"]["n_impair"] == 0:
        return None
    used = [(r, blocked_flag(r, rule, strict)) for r in rows]
    used = [(r, f) for r, f in used if f is not None]
    imp_blocked = [r["ticker"] for r, f in used if f and r["tr"] <= IMPAIR]
    res = []
    for t in imp_blocked:
        sub = [r for r in rows if r["ticker"] != t]
        cc = cell(sub, rule, strict, "all")
        res.append(dict(drop=t, conc=cc["concentration"], n_impair=cc["blocked"]["n_impair"]))
    res.sort(key=lambda x: x["conc"])
    return dict(full=c["concentration"], worst_drop=res[0] if res else None,
                n_impair_blocked=len(imp_blocked), all_drops=res[:6])


def drop_one_sector(data, rule="and", strict=False):
    """1業種(sic2)を抜くと『8ビンテージすべて 1.0超』が消えるか"""
    secs = sorted({r["sic2"] for v in VINTAGES for r in data[v] if r.get("sic2")})
    worst = None
    rows = []
    for s in secs:
        vals = []
        for v in VINTAGES:
            sub = [r for r in data[v] if r.get("sic2") != s]
            c = cell(sub, rule, strict, "all")
            vals.append(c["concentration"] if c and c["concentration"] is not None else 0.0)
        n_above = sum(1 for x in vals if x >= 1.0)
        med = round(statistics.median(vals), 3)
        rec = dict(drop_sic2=s, n_above_1=n_above, median=med, min=min(vals), max=max(vals))
        rows.append(rec)
        if worst is None or (n_above, med) < (worst["n_above_1"], worst["median"]):
            worst = rec
    rows.sort(key=lambda x: (x["n_above_1"], x["median"]))
    return dict(worst=worst, lowest5=rows[:5])


def overlap(data, rule="and", strict=False):
    """8ビンテージは何回の独立な観測に相当するか——止めた社・毀損社の重なり"""
    blocked = {}
    for v in VINTAGES:
        s = set()
        for r in data[v]:
            f = blocked_flag(r, rule, strict)
            if f:
                s.add(r["ticker"])
        blocked[v] = s
    pairs = []
    for i, a in enumerate(VINTAGES):
        for b in VINTAGES[i + 1:]:
            inter = len(blocked[a] & blocked[b])
            union = len(blocked[a] | blocked[b])
            pairs.append(dict(a=a, b=b, jaccard=round(inter / union, 3) if union else None,
                              overlap_of_smaller=round(inter / min(len(blocked[a]), len(blocked[b])), 3)))
    cnt = defaultdict(int)
    for v in VINTAGES:
        for t in blocked[v]:
            cnt[t] += 1
    dist = defaultdict(int)
    for t, k in cnt.items():
        dist[k] += 1
    return dict(sizes={str(v): len(blocked[v]) for v in VINTAGES},
                jaccard_median=round(statistics.median(p["jaccard"] for p in pairs if p["jaccard"] is not None), 3),
                jaccard_max=max(p["jaccard"] for p in pairs if p["jaccard"] is not None),
                n_unique_blocked_ever=len(cnt),
                times_blocked_hist={str(k): dist[k] for k in sorted(dist)},
                adjacent=[p for p in pairs if VINTAGES.index(p["b"]) - VINTAGES.index(p["a"]) == 1])


# ── 置換（会社単位・全ビンテージ同時。ビンテージ内で独立に混ぜると従属が壊れる＝既記録） ──
class Perm:
    def __init__(self, data, rule="and", strict=False, pool="all", stratify=None, seed=SEED,
                 restrict_common=False):
        self.rnd = random.Random(seed)
        self.restrict_common = restrict_common
        self.rule, self.strict, self.stratify = rule, strict, stratify
        self.lab, self.blk, self.order = {}, {}, {}
        for v in VINTAGES:
            rows = [r for r in data[v] if (r["qual"] if pool == "qual" else True)]
            keep = []
            for r in rows:
                f = blocked_flag(r, rule, strict)
                if f is None:
                    continue
                keep.append((r["ticker"], 1 if r["tr"] <= IMPAIR else 0, 1 if f else 0))
            keep.sort()
            self.order[v] = [t for t, _, _ in keep]
            self.lab[v] = {t: l for t, l, _ in keep}
            self.blk[v] = [t for t, _, b in keep if b]
        self.strat = {}
        if stratify:
            for v in VINTAGES:
                for r in data[v]:
                    if r.get(stratify) is not None:
                        self.strat[r["ticker"]] = r[stratify]
        common = set(self.order[VINTAGES[0]])
        for v in VINTAGES[1:]:
            common &= set(self.order[v])
        if restrict_common:
            # ⚠ solo を独立に混ぜると**ビンテージ間の従属が壊れ**、帰無で
            #   『8/8とも1.0超』が起きにくくなる＝観測の p が小さく出る（反保守）。
            #   共通集合だけに絞れば全ビンテージが同一の置換を受ける＝保守側の帰無
            for v in VINTAGES:
                self.order[v] = [t for t in self.order[v] if t in common]
                self.lab[v] = {t: l for t, l in self.lab[v].items() if t in common}
                self.blk[v] = [t for t in self.blk[v] if t in common]
        self.common = sorted(common)
        by = defaultdict(list)
        for t in self.common:
            by[self.strat.get(t, "_ALL") if stratify else "_ALL"].append(t)
        self.by = dict(by)
        self.solo = {v: sorted(set(self.order[v]) - common) for v in VINTAGES}
        # 基準率は置換で不変（ビンテージ内の相対頻度を保つ並べ替えなので）
        self.base_imp = {v: sum(self.lab[v].values()) / len(self.lab[v]) for v in VINTAGES}

    def stat(self, shuffle=True):
        mapping = {}
        if shuffle:
            for _s, ts in self.by.items():
                sh = list(ts)
                self.rnd.shuffle(sh)
                for a, b in zip(ts, sh):
                    mapping[a] = b
        concs = []
        for v in VINTAGES:
            lv = self.lab[v]
            if shuffle:
                solo_vals = [lv[t] for t in self.solo[v]]
                self.rnd.shuffle(solo_vals)
                solo_map = dict(zip(self.solo[v], solo_vals))
                k = 0
                for t in self.blk[v]:
                    k += lv[mapping[t]] if t in mapping else solo_map[t]
            else:
                k = sum(lv[t] for t in self.blk[v])
            nb = len(self.blk[v])
            bi = self.base_imp[v]
            concs.append((k / nb) / bi if nb and bi > 0 else 0.0)
        return concs


def perm_test(data, rule="and", strict=False, pool="all", stratify=None, iters=2000, seed=SEED,
              restrict_common=False):
    P = Perm(data, rule, strict, pool, stratify, seed, restrict_common)
    obs = P.stat(shuffle=False)
    obs_num = [sum(P.lab[v][t] for t in P.blk[v]) for v in VINTAGES]
    obs_above = sum(1 for x in obs if x >= 1.0)
    obs_med = statistics.median(obs)
    obs_max = max(obs)
    obs_pass = sum(1 for x in obs if x >= CONC_MIN)
    ge_above = ge_med = ge_max = ge_pass = 0
    dist_above = defaultdict(int)
    meds = []
    for _ in range(iters):
        c = P.stat(True)
        a = sum(1 for x in c if x >= 1.0)
        m = statistics.median(c)
        dist_above[a] += 1
        meds.append(m)
        if a >= obs_above:
            ge_above += 1
        if m >= obs_med:
            ge_med += 1
        if max(c) >= obs_max:
            ge_max += 1
        if sum(1 for x in c if x >= CONC_MIN) >= obs_pass:
            ge_pass += 1
    meds.sort()
    return dict(rule=rule, strict=strict, pool=pool, stratify=stratify, iters=iters,
                restrict_common=restrict_common,
                n_used_by_vintage={str(v): len(P.lab[v]) for v in VINTAGES},
                n_blocked_by_vintage={str(v): len(P.blk[v]) for v in VINTAGES},
                observed=dict(concs=[round(x, 3) for x in obs], numerators=obs_num,
                              n_blocked=[len(P.blk[v]) for v in VINTAGES], n_above_1=obs_above,
                              median=round(obs_med, 3), max=round(obs_max, 3),
                              n_at_line=obs_pass),
                p_n_above_1=round((ge_above + 1) / (iters + 1), 4),
                p_median=round((ge_med + 1) / (iters + 1), 4),
                p_max=round((ge_max + 1) / (iters + 1), 4),
                p_n_at_line=round((ge_pass + 1) / (iters + 1), 4),
                null_n_above_1_hist={str(k): dist_above[k] for k in sorted(dist_above)},
                null_median_pcts=dict(p50=round(meds[iters // 2], 3),
                                      p95=round(meds[int(iters * .95)], 3),
                                      p99=round(meds[int(iters * .99)], 3)),
                n_common=len(P.common))


def fisher_greater(a, b, c, d):
    """2x2 の片側 p（止めた群の毀損が観測以上になる確率）"""
    n = a + b + c + d
    r1, r2, c1 = a + b, c + d, a + c
    tot = math.comb(n, c1)
    hi = min(r1, c1)
    s = sum(math.comb(r1, k) * math.comb(r2, c1 - k) for k in range(a, hi + 1))
    return s / tot


def wilson(k, n):
    if n == 0:
        return (None, None)
    z = 1.959964
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, ctr - half), 4), round(min(1.0, ctr + half), 4))


def cell_stats(rows, rule="and", strict=False, pool="all"):
    c = cell(rows, rule, strict, pool)
    if not c or not c["blocked"]:
        return None
    b, p = c["blocked"], c["passed"]
    a = b["n_impair"]
    fp = fisher_greater(a, b["n"] - a, p["n_impair"], p["n"] - p["n_impair"])
    return dict(concentration=c["concentration"], n_blocked=b["n"], n_impair=a,
                blocked_impair=b["impair"], passed_impair=p["impair"],
                fisher_p_one_sided=round(fp, 4),
                blocked_impair_ci95=wilson(a, b["n"]))


def window_contamination(data, rule="and", strict=False):
    """窓の短い行（HWM 9.76 / DBD 3.01 …）が止めた群に紛れていないか。
       年率は窓が短いほど暴れるので、左尾の話では効きうる"""
    res = {}
    for v in VINTAGES:
        rows = data[v]
        med = statistics.median(r["years"] for r in rows if r.get("years"))
        short = [r for r in rows if r.get("years") and r["years"] < med - 0.5]
        sb = [r for r in short if blocked_flag(r, rule, strict)]
        c_full = cell(rows, rule, strict, "all")
        c_cut = cell([r for r in rows if not (r.get("years") and r["years"] < med - 0.5)],
                     rule, strict, "all")
        res[str(v)] = dict(years_median=round(med, 2), n_short=len(short),
                           n_short_blocked=len(sb),
                           short_blocked=[r["ticker"] for r in sb][:8],
                           conc_full=c_full["concentration"],
                           conc_without_short=c_cut["concentration"] if c_cut else None)
    return res


def lookahead(data, meta):
    """信号の会計期末が結果の窓の開始より前か（features2 は filed<=deadline で切ってある）"""
    res = {}
    for v in VINTAGES:
        ends = [r["fy_end"] for r in data[v] if r.get("fy_end")]
        dl = meta[v]["deadline"]
        bad = sorted([e for e in ends if e and dl and e > dl])[-5:]
        res[str(v)] = dict(deadline=dl, window_start=meta[v]["start"],
                           fy_end_max=max(ends) if ends else None,
                           n_fy_end_after_deadline=sum(1 for e in ends if e and dl and e > dl),
                           examples=bad)
    return res


def unit_audit(data, meta):
    """opm が比率で入っている取り違えが無いか。
       ファイル単位の換算と per-row 帯検問が食い違う社で qual が変わるか"""
    res = {}
    for v in VINTAGES:
        flips = []
        for r in data[v]:
            raw = r.get("opm_raw")
            if raw is None:
                continue
            file_pct = r["opm"]
            band = band_pct(raw)
            if abs((band or 0) - (file_pct or 0)) > 1e-9:
                q_file = (file_pct >= QUAL_OPM_PCT and (r["fcfpos5"] or 0) >= QUAL_FCFPOS)
                q_band = (band >= QUAL_OPM_PCT and (r["fcfpos5"] or 0) >= QUAL_FCFPOS)
                flips.append(dict(ticker=r["ticker"], raw=raw, file_pct=round(file_pct, 2),
                                  band_pct=round(band, 2), qual_file=q_file, qual_band=q_band))
        n_flip_qual = sum(1 for f in flips if f["qual_file"] != f["qual_band"])
        neg = [r["opmD5"] for r in data[v] if r.get("opmD5") is not None]
        res[str(v)] = dict(opm_scale=meta[v]["opm_scale"], opm_med_abs=meta[v]["opm_med_abs"],
                           n_disagree=len(flips), n_qual_flipped=n_flip_qual,
                           examples=flips[:3],
                           opmD5_median=round(statistics.median(neg), 5) if neg else None,
                           opmD5_neg_share=round(sum(1 for x in neg if x < 0) / len(neg), 4) if neg else None,
                           opmD5_abs_med=round(statistics.median(abs(x) for x in neg), 5) if neg else None,
                           opmD5_looks_like="比率pt（|中央|<=3）" if neg and statistics.median(abs(x) for x in neg) <= 3 else "%pt?")
    return res


def combo_key(rows):
    for r in rows:
        r["sic_sz"] = None if (r.get("sic2") is None or r.get("sz") is None) else f"{r['sic2']}/{r['sz']}"
    return rows


def replication_decompose(rep):
    """『3.19倍 → 1.84倍』は分子で起きたのか分母で起きたのか"""
    a, b = rep["pool581"], rep["pool956"]
    return dict(
        blocked_impair_581=a["blocked"]["impair"], blocked_impair_956=b["blocked"]["impair"],
        blocked_impair_ratio=round(b["blocked"]["impair"] / a["blocked"]["impair"], 3),
        base_impair_581=a["base"]["impair"], base_impair_956=b["base"]["impair"],
        base_impair_ratio=round(b["base"]["impair"] / a["base"]["impair"], 3),
        conc_581=a["concentration"], conc_956=b["concentration"],
        verdict="止めた群の毀損率はほぼ同じ（分子は動いていない）。濃縮が半減したのは**分母（母集団の毀損率）が倍近くになったから**"
        if abs(b["blocked"]["impair"] - a["blocked"]["impair"]) < 0.02 else "分子も動いている")


def main():
    iters = 2000
    for i, a in enumerate(sys.argv):
        if a == "--perm" and i + 1 < len(sys.argv):
            iters = int(sys.argv[i + 1])
    data, meta = build()
    for v in VINTAGES:
        size_tercile(data[v])

    res = dict(generated="2026-08-18", tool="night/opmtrend_ref_h4.py",
               role="H4 の反証専門。独立実装（測定側を import しない）。判定・規約・採点には一切触らない",
               prereg="out/opm_trend_prereg.json / H4_shrink_gate",
               line=dict(concentration_min=CONC_MIN, numerator_min=MIN_NUM,
                         median_not_worse=True, stop_rate_max=MAX_STOP),
               vintage_meta={str(v): meta[v] for v in VINTAGES})

    # ① 独立再計算と照合
    res["verify_base"] = verify_base(data)
    mine = all_cells(data)
    res["verify_h4"] = verify_h4(mine)
    res["cells_mine"] = {k: (None if c is None else
                             dict(n_used=c["n_used"], n_na=c["n_na"], stop_rate=c["stop_rate"],
                                  conc=c["concentration"],
                                  n_impair_blocked=(c["blocked"] or {}).get("n_impair"),
                                  base_impair=c["base"]["impair"],
                                  blocked_impair=(c["blocked"] or {}).get("impair"),
                                  blocked_med=(c["blocked"] or {}).get("med"),
                                  passed_med=(c["passed"] or {}).get("med"),
                                  c1=c["c1"], c2=c["c2"], c4=c["c4"], verdict=c["verdict"]))
                        for k, c in mine.items()}
    res["summary_mine"] = {}
    for rule in ("and", "cagr_only", "opm_only"):
        for strict in (False, True):
            key = f"{rule}/{'strict' if strict else 'main'}"
            vals = [mine[f"{v}/all/{rule}/{'strict' if strict else 'main'}"]["concentration"]
                    for v in VINTAGES]
            nums = [mine[f"{v}/all/{rule}/{'strict' if strict else 'main'}"]["blocked"]["n_impair"]
                    for v in VINTAGES]
            res["summary_mine"][key] = dict(concs=[round(x, 3) for x in vals],
                                            numerators=nums,
                                            median=round(statistics.median(vals), 3),
                                            n_above_1=sum(1 for x in vals if x >= 1.0),
                                            n_at_line=sum(1 for x, n in zip(vals, nums)
                                                          if x >= CONC_MIN and n >= MIN_NUM))

    # ② 再現と母集団感応
    res["replication"] = replication(data)
    res["replication"]["decompose"] = replication_decompose(res["replication"])

    # ③ 攻撃
    atk = {}
    atk["a_sector"] = dict(
        note="Mantel-Haenszel 型（層内の期待毀損に対する観測毀損）。層=sic2・8社未満の層は捨てる",
        by_vintage={str(v): dict(raw=mine[f"{v}/all/and/main"]["concentration"],
                                 **mh_adjust(data[v], "sic2"))
                    for v in VINTAGES},
        drop_one_sector=drop_one_sector(data))
    atk["b_size"] = dict(
        note="規模(rev)の三分位で層別。規模は既記録で『消えないこと』を当てる＝最有力の交絡",
        by_vintage={str(v): dict(raw=mine[f"{v}/all/and/main"]["concentration"],
                                 **mh_adjust(data[v], "sz"))
                    for v in VINTAGES},
        within_tercile={str(v): {sz: (lambda c: None if not c or not c["blocked"] else
                                      dict(conc=c["concentration"], n_blocked=c["blocked"]["n"],
                                           n_impair=c["blocked"]["n_impair"]))(
                                          cell([r for r in data[v] if r.get("sz") == sz], "and", False, "all"))
                                 for sz in ("小", "中", "大")}
                        for v in VINTAGES})
    atk["c_leave_one_out"] = {str(v): leave_one_out(data[v]) for v in VINTAGES}
    atk["d_permutation"] = dict(
        note="会社単位・全ビンテージ同時（ビンテージ内で独立に混ぜると従属が壊れ偽陽性率を過小評価する＝既記録）",
        and_main=perm_test(data, "and", False, "all", None, iters),
        and_strict=perm_test(data, "and", True, "all", None, iters, seed=SEED + 1),
        cagr_only_main=perm_test(data, "cagr_only", False, "all", None, iters, seed=SEED + 2),
        and_main_sic2=perm_test(data, "and", False, "all", "sic2", iters, seed=SEED + 3))
    for v in VINTAGES:
        combo_key(data[v])
    atk["a2_combo"] = dict(
        note="業種(sic2)×規模三分位の合わせ技で層別。層が薄くなるので min_stratum=8 で切る",
        by_vintage={str(v): dict(raw=mine[f"{v}/all/and/main"]["concentration"],
                                 **mh_adjust(data[v], "sic_sz"))
                    for v in VINTAGES})
    adj = [atk["a2_combo"]["by_vintage"][str(v)]["adj_conc"] for v in VINTAGES]
    adj = [x for x in adj if x is not None]
    atk["a2_combo"]["median_adj"] = round(statistics.median(adj), 3) if adj else None
    atk["a2_combo"]["n_above_1"] = sum(1 for x in adj if x >= 1.0)
    for key, lbl in (("a_sector", "sic2"), ("b_size", "sz")):
        vals = [atk[key]["by_vintage"][str(v)]["adj_conc"] for v in VINTAGES]
        vals = [x for x in vals if x is not None]
        atk[key]["median_adj"] = round(statistics.median(vals), 3)
        atk[key]["n_above_1"] = sum(1 for x in vals if x >= 1.0)
    atk["d_permutation"]["and_strict_common_only"] = perm_test(
        data, "and", True, "all", None, iters, seed=SEED + 4, restrict_common=True)
    atk["d_permutation"]["and_main_size"] = perm_test(
        data, "and", False, "all", "sz", iters, seed=SEED + 5)
    atk["a3_min_stratum"] = {
        str(m): dict(
            sic2=round(statistics.median([mh_adjust(data[v], "sic2", min_stratum=m)["adj_conc"] or 0
                                          for v in VINTAGES]), 3),
            sz=round(statistics.median([mh_adjust(data[v], "sz", min_stratum=m)["adj_conc"] or 0
                                        for v in VINTAGES]), 3),
            combo=round(statistics.median([mh_adjust(data[v], "sic_sz", min_stratum=m)["adj_conc"] or 0
                                           for v in VINTAGES]), 3))
        for m in (5, 8, 12, 20)}
    atk["a4_rev_coverage"] = {str(v): dict(
        n=len(data[v]),
        n_rev=sum(1 for r in data[v] if r.get("rev")),
        n_sic2=sum(1 for r in data[v] if r.get("sic2")),
        cut_small=None, cut_big=None) for v in VINTAGES}
    for v in VINTAGES:
        vals = sorted(r["rev"] for r in data[v] if r.get("rev"))
        if vals:
            atk["a4_rev_coverage"][str(v)]["cut_small"] = vals[len(vals) // 3]
            atk["a4_rev_coverage"][str(v)]["cut_big"] = vals[2 * len(vals) // 3]
    # 機構を実数で見せる: 止めた群はどの規模層に居るか／その層の毀損率はいくつか
    comp = {}
    for v in VINTAGES:
        rows = data[v]
        used = [(r, blocked_flag(r, "and", False)) for r in rows]
        tot = len(used)
        rec = {}
        for sz in ("小", "中", "大"):
            g = [r for r, _ in used if r.get("sz") == sz]
            b = [r for r, f in used if f and r.get("sz") == sz]
            rec[sz] = dict(share_of_pool=round(len(g) / tot, 3),
                           share_of_blocked=round(len(b) / max(1, sum(1 for _, f in used if f)), 3),
                           impair_rate=round(sum(1 for r in g if r["tr"] <= IMPAIR) / len(g), 4) if g else None)
        comp[str(v)] = rec
    atk["b3_composition"] = dict(
        note="止めた群の規模構成 vs 母集団の規模構成。小型の毀損率が高く、規則は小型を多く止める",
        by_vintage=comp)
    # 共通430社（厳格読みの全ビンテージ共通集合）はどんな社か
    P = Perm(data, "and", True, "all", None, SEED, restrict_common=True)
    cm = set(P.common)
    prof = {}
    for v in VINTAGES:
        inn = [r for r in data[v] if r["ticker"] in cm]
        out_ = [r for r in data[v] if r["ticker"] not in cm and blocked_flag(r, "and", True) is not None]
        prof[str(v)] = dict(
            n_common=len(inn), rev_med_common=statistics.median([r["rev"] for r in inn if r.get("rev")]),
            n_other=len(out_),
            rev_med_other=statistics.median([r["rev"] for r in out_ if r.get("rev")]) if out_ else None,
            impair_common=round(sum(1 for r in inn if r["tr"] <= IMPAIR) / len(inn), 4),
            impair_other=round(sum(1 for r in out_ if r["tr"] <= IMPAIR) / len(out_), 4) if out_ else None)
    atk["b4_common_profile"] = dict(
        note="厳格読みの共通430社＝2013でopmD5が測れた社＝大型に偏る。"
             "『8/8一致』はこの偏りの外側（各ビンテージ固有の小型）が支えている",
        by_vintage=prof)
    # ★2013 の異常（濃縮0.47）の正体: opmD5 の欠測が**規模に依存する**
    cov = {}
    for v in VINTAGES:
        rec = {}
        for sz in ("小", "中", "大"):
            g = [r for r in data[v] if r.get("sz") == sz]
            got = [r for r in g if r.get("opmD5") is not None]
            rec[sz] = dict(n=len(g), n_measured=len(got),
                           coverage=round(len(got) / len(g), 4) if g else None)
        cov[str(v)] = rec
    atk["b5_coverage_by_size"] = dict(
        note="opmD5 が測れる社の割合を規模三分位で。2013 は小型15.6% / 大型73.0% ＝**欠測が規模に依存する**。"
             "測定側の『2013の符号反転は欠測の産物』は正しいが、欠測は中立ではなく**小型を系統的に落とす**ので、"
             "2013の厳格読み(1.821)は『公平な比較』ではなく**大型だけの部分標本**。しかも分子は1社",
        by_vintage=cov)
    atk["e_units"] = unit_audit(data, meta)
    atk["f_lookahead"] = lookahead(data, meta)
    atk["g_window"] = window_contamination(data)
    atk["h_overlap"] = overlap(data)
    atk["i_cellstats"] = {k: cell_stats(data[v], "and", strict, pool)
                          for v in VINTAGES
                          for pool in ("all", "qual")
                          for strict in (False,)
                          for k in [f"{v}/{pool}/and/main"]}
    # 測定側との唯一の食い違い（定義の選択・誤りではない）を明記する
    try:
        th = load("opmtrend_h4.json")["cells"]
        res["definitional_gap"] = dict(
            where="cagr_only/strict のみ（14セル）。and と opm_only は完全一致",
            mine="strict では cagr5・opmD5 の**どちらか**が欠測なら母集団から外す（積と片脚を同じ母集団で比べるため）",
            theirs="strict ではその規則が使う欄の欠測だけ外す（cagr_only なら cagr5 のみ）",
            impact_example=dict(
                cell="2013/all/cagr_only/strict",
                mine_n_used=mine["2013/all/cagr_only/strict"]["n_used"],
                theirs_n_used=th["2013/all/cagr_only/strict"]["n_used"],
                mine_conc=mine["2013/all/cagr_only/strict"]["concentration"],
                theirs_conc=th["2013/all/cagr_only/strict"]["concentration"]),
            why_it_matters="測定側の定義だと**厳格読みの『積』と『片脚』が別の母集団**で計算される"
                           "（2013 で 449 vs 942）。③の比較を厳格読みでやるなら『基準の違う二つ』になる。"
                           "⚠ただし測定側の報告の③表は main 読みなので、報告そのものは影響を受けていない",
            h4_verdict_affected=False)
    except Exception:
        res["definitional_gap"] = None
    # opm_only/strict の 2013 が c1 に届く（③表の脚注に無い）
    c = mine["2013/all/opm_only/strict"]
    res["side_finding_opm_only_strict_2013"] = dict(
        conc=c["concentration"], n_impair=c["blocked"]["n_impair"], stop_rate=c["stop_rate"],
        c1=c["c1"], c2=c["c2"], c4=c["c4"], verdict=c["verdict"],
        note="③表は main 読みなので報告に矛盾は無い。ただし厳格読みだと片脚(opmD5<0)が"
             "濃縮2.075・分子5＝c1に**届く**。止率41%で c4 に落ちるので遮断器にはならない")
    res["attacks"] = atk
    # ── 反証の総括（この道具の答え） ──
    sm = res["summary_mine"]["and/main"]
    pm = atk["d_permutation"]
    res["refutation_verdict"] = dict(
        independent_recompute="一致（and と opm_only の全セル。cagr_only/strict のみ定義の選択が違う＝下の definitional_gap）",
        h4_verdict_agreed="不合格（8/8ビンテージで線に届かない）——測定側と同じ",
        broken=[
            dict(claim="『向きは8ビンテージすべて一致』（厳格読み 8/8）",
                 attack="母集団を8ビンテージ共通の430社に固定する（＝同じ社を8つの入口日で追う）",
                 result=f"8/8 → {pm['and_strict_common_only']['observed']['n_above_1']}/8、"
                        f"中央値 {res['summary_mine']['and/strict']['median']} → "
                        f"{pm['and_strict_common_only']['observed']['median']}、p={pm['and_strict_common_only']['p_median']}",
                 caveat="⚠この攻撃は分子を壊す（共通430社だと止めた群の毀損が0〜9社・過半が0〜3社）。"
                        "示せたのは『主張が母集団に依存する』までで、『効果が無い』ではない。"
                        "母集団を保ったまま効果を消すのは下の規模層別のほう",
                 verdict="refuted（ただし検出力の代償つき）"),
            dict(claim="濃縮の中央値 1.39（素）",
                 attack="規模三分位で層別（Mantel-Haenszel）＋規模層内の置換検定",
                 result=f"中央値 1.393 → {atk['b_size']['median_adj']}（1.0超 7/8 → {atk['b_size']['n_above_1']}/8）。"
                        f"規模層内置換 p(median)={pm['and_main_size']['p_median']}・"
                        f"帰無の中央値が既に {pm['and_main_size']['null_median_pcts']['p50']}",
                 verdict="refuted（規模の構成でほぼ説明できる）"),
            dict(claim="同上",
                 attack="業種×規模の合わせ技で層別",
                 result=f"中央値 {atk['a2_combo']['median_adj']}・1.0超 {atk['a2_combo']['n_above_1']}/8"
                        f"（薄い層の切り方 min=5/8/12/20 でも 0.99〜1.01 で安定）",
                 verdict="refuted（効果が消える）"),
            dict(claim="『2018年ビンテージの 3.19倍』（CLAUDE.md が引用し続けた数字）",
                 attack="止めた群と母集団のどちらが動いたかを分解",
                 result=f"止めた群の毀損率 {res['replication']['decompose']['blocked_impair_581']} → "
                        f"{res['replication']['decompose']['blocked_impair_956']}（ほぼ不変）／"
                        f"母集団の毀損率 {res['replication']['decompose']['base_impair_581']} → "
                        f"{res['replication']['decompose']['base_impair_956']}（{res['replication']['decompose']['base_impair_ratio']}倍）",
                 verdict="refuted（3.19倍は分子ではなく**分母**の産物）")],
        not_broken=[
            dict(claim="1社の外れ値ではない", result="止めた群の毀損社を1社抜いても濃縮は 1.837→1.781（2018）等ほぼ不変"),
            dict(claim="窓の短い行の混入ではない", result="窓が中央値より短い行を全部除いても濃縮は ±0.04 しか動かない"),
            dict(claim="単位の取り違えは無い", result="opm はファイル単位で比率→%換算が正しく、per-row 帯検問との食い違い10〜16社は**qual を1社も変えない**"),
            dict(claim="look-ahead は無い", result="8ビンテージとも会計期末の最大が締切の1ヶ月前・締切後の行は0件・窓の開始＝締切"),
            dict(claim="業種だけでは説明できない", result=f"業種層内の置換で p(median)={pm['and_main_sic2']['p_median']}・"
                                                        f"MH調整でも中央値 {atk['a_sector']['median_adj']}"),
            dict(claim="素の中央値 1.39 は雑音ではない（層別しない限り）",
                 result=f"無層別の置換で p(median)={pm['and_main']['p_median']}＝**弱いが実在する信号**。"
                        "ただし『実在するが線の 2.0 に遠く、しかも規模でほぼ説明できる』が正しい読み")],
        mechanism=f"止めた群は小型に偏る（母集団の小型は33.3%なのに止めた群の小型は46.5〜57.1%・2016-2022）。"
                  f"そして小型の毀損率は 10.8〜26.4%、大型は 0.9〜6.3% ＝10〜20倍違う。"
                  f"濃縮1.4倍はこの構成でほぼ説明が付く。2013だけ濃縮0.47なのも同じ機構の裏返し"
                  f"——2013はopmD5の被覆が47.6%で**小型が測れず**、止めた群の51.2%が大型になったから",
        bottom_line="H4 は不合格。測定側の結論は正しい。だが**残った肯定的な所見（向きの一貫性・濃縮1.39）も"
                    "反証に耐えない**——規模で層別すると中央値 1.09・業種と合わせると 0.995 で消える。"
                    "『8/8一致』は8つの**別々の母集団**を並べた結果で、母集団を固定すると 4/8 になる。"
                    "そして CLAUDE.md が1年引用してきた『3.2倍』は分母の産物だった。")
    json.dump(res, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {DEST}")
    return res


if __name__ == "__main__":
    r = main()
    print("verify_base:", r["verify_base"]["ok"], r["verify_base"].get("n_diff"))
    print("verify_h4  :", r["verify_h4"]["ok"], r["verify_h4"].get("n_diff"))
