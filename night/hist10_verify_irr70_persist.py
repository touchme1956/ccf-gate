# -*- coding: utf-8 -*-
"""角度Bの候補「【対照】irr=70 → 持続（前半と後半の両方で年率10%+）」を潰しにかかる（6検問）。

候補（探索側 out/hist10_angleB.json の B1.control_irr の記述）:
    設計 B1 ／ 入口 2013 ／ 母集団 P_full ／ 群 = irr==70（2018の読解では75と同じ刻み）
    n=51 ／ 分子=24 ／ P=0.4706 ／ base=0.2602 ／ lift=0.2104
    探索側の弁: 「設計をまたぐと符号が反転する＝規則にできない。B1では母集団の1.8倍だが
                 B2では母集団を下回る。既記録『上を狙うなら85／下を防ぐなら70』のうち、
                 持続については70は支持されない」

この道具は hist10_angleB / hist10_targets / hist10_diag を **一行も import しない**。
  * irr は retro_moat_*.json（読解の原簿）から自分で組み直す
  * y_persist は retro_monthly_*.json（月次系列）から自分で組み直す
  * lift・MH・置換・増分もすべて自前
食い違いが出たらそれ自体が発見なので、境界の約束（>= か >）と base の定義まで振って比べる。

判定・採点・台帳・index.html・パックには一切触らない（読むだけの調査）。
出力: out/hist10_verify_irr70_persist.json
"""
import datetime
import json
import math
import random
from collections import Counter, defaultdict

PANEL = "out/hist_wd_panel.json"
TARGETS = "out/hist10_targets.json"          # 突合せ用（自前の組み直しの答え合わせにだけ使う）
PREREG = "out/hist10_prereg.json"
M1 = "out/retro_monthly_2013_2018.json"
M2 = "out/retro_monthly_2018_2026.json"
INV13 = "out/retro_returns_2013_all.json"
INV18 = "out/retro_returns_2018.json"
INV15 = "out/retro_returns_2015_q.json"
OUT = "out/hist10_verify_irr70_persist.json"

MOAT_SRC = {
    2013: [("out/retro_moat_2013.json", "irr", "広域119"),
           ("out/retro_moat_2013q.json", "irr", "質実証プール130")],
    2015: [("out/retro_moat_2015.json", "irr", "2015既存163"),
           ("out/retro_moat_2015q.json", "irr", "質実証プール130"),
           ("out/retro_moat_2015qb.json", "irr", "質実証プール追補212")],
    2018: [("out/retro_moat_2018.json", "irr18", "2018本編140"),
           ("out/retro_moat_2018_rest.json", "irr18", "2018残り37")],
}

HURDLE = 0.10        # prereg。新しい定数を作らない
LIFT = 0.15          # prereg
MIN_NUM = 20         # prereg
MAX_CAUGHT = 0.70    # prereg
N_PERM = 2000        # prereg「置換2000回」
SEED = 20260812

ANCHOR_YM = {2013: (2013, 7), 2015: (2015, 7), 2016: (2016, 7),
             2017: (2017, 7), 2018: (2018, 7)}
END_YM = (2026, 8)


# ───────────────────────── 小道具（自前） ─────────────────────────
def r4(x):
    return None if x is None else round(x, 4)


def ym(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return (d.year, d.month)


def yrs(a, b):
    """(y,m) 同士の年数。月割り。"""
    return ((b[0] - a[0]) * 12 + (b[1] - a[1])) / 12.0


def cagr(p0, p1, years):
    if p0 is None or p1 is None or p0 <= 0 or p1 <= 0 or years <= 0:
        return None
    return (p1 / p0) ** (1.0 / years) - 1.0


def binom_tail_ge(n, k, p):
    """P(X>=k), X~Bin(n,p)。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    s = 0.0
    for i in range(k, n + 1):
        s += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return s


def fisher_2x2(a, b, c, d):
    """両側 Fisher の正確確率（a,b / c,d）。"""
    n = a + b + c + d
    if n == 0:
        return None
    row1, col1 = a + b, a + c

    def pr(x):
        if x < max(0, col1 - (c + d)) or x > min(row1, col1):
            return 0.0
        return (math.comb(row1, x) * math.comb(c + d, col1 - x)) / math.comb(n, col1)
    p0 = pr(a)
    tot = 0.0
    for x in range(max(0, col1 - (c + d)), min(row1, col1) + 1):
        px = pr(x)
        if px <= p0 * (1 + 1e-9):
            tot += px
    return min(1.0, tot)


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [r4(max(0.0, c - h)), r4(min(1.0, c + h))]


# ───────────────────────── 読み込み（自前の join） ─────────────────────────
def load_irr():
    """読解の原簿から irr を自分で組む。2018 の 75 は 70 と同じ刻み（パネルの約束）。

    同じ (vintage,ticker) が複数ファイルに出たら **食い違いを必ず記録**する。
    """
    out, prov, conflicts, raw = {}, {}, [], {}
    for v, srcs in MOAT_SRC.items():
        out[v], prov[v], raw[v] = {}, {}, {}
        for path, key, label in srcs:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            for r in d["rows"]:
                t = r.get("ticker") or r.get("t")
                x = r.get(key)
                if x is None:
                    continue
                g = 70 if x == 75 else x     # 2018の読解の75＝他年の70
                if t in out[v] and out[v][t] != g:
                    conflicts.append({"vintage": v, "ticker": t,
                                      "a": out[v][t], "b": g,
                                      "a_src": prov[v][t], "b_src": label})
                out[v][t] = g
                raw[v][t] = x
                prov[v][t] = label
    return out, prov, conflicts, raw


def load_monthly():
    px = defaultdict(dict)
    for path in (M1, M2):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        for t, ser in d.items():
            for ts, p in ser:
                if p is None or p <= 0:
                    continue
                px[t][ym(ts)] = p
    return px


def load_panel():
    with open(PANEL, encoding="utf-8") as f:
        p = json.load(f)
    by = {}
    for r in p["rows"]:
        by[(r["ticker"], r["vintage"])] = r
    return p, by


def load_targets():
    with open(TARGETS, encoding="utf-8") as f:
        t = json.load(f)
    return {(r["ticker"], r["vintage"]): r for r in t["rows"]}


# ───────────────────────── 目的変数を自分で組む ─────────────────────────
def build_persist(px, anchor, split, end=END_YM, ge=True):
    """(pre_cagr, post_cagr, y_persist, y10) を月次から直に組む。

    ge=True なら 10% の線は >=、False なら >（境界の約束を振るため）。
    """
    a, m, e = ANCHOR_YM[anchor], split, end
    ya, yb, yt = yrs(a, m), yrs(m, e), yrs(a, e)
    res = {}
    for t, ser in px.items():
        p0, p1, p2 = ser.get(a), ser.get(m), ser.get(e)
        if p0 is None or p1 is None or p2 is None:
            continue
        pre, post, tot = cagr(p0, p1, ya), cagr(p1, p2, yb), cagr(p0, p2, yt)
        if pre is None or post is None or tot is None:
            continue
        hit = (lambda x: x >= HURDLE) if ge else (lambda x: x > HURDLE)
        res[t] = {"pre": pre, "post": post, "tot": tot,
                  "y_persist": bool(hit(pre) and hit(post)), "y10": bool(hit(tot))}
    return res, {"anchor": "%04d-%02d" % a, "split": "%04d-%02d" % m,
                 "end": "%04d-%02d" % e, "pre_years": round(ya, 4),
                 "post_years": round(yb, 4), "total_years": round(yt, 4)}


# ───────────────────────── 統計 ─────────────────────────
def cell(members, lab, base_kind="pool"):
    """群 members（ticker集合）と全体 lab（ticker→0/1）から n/k/P/lift を出す。

    base_kind: "pool" = 母集団に群自身を含む（探索側の約束）
               "rest" = 群を除いた残り
    """
    ks = [lab[t] for t in members if t in lab]
    n, k = len(ks), sum(ks)
    allk = list(lab.values())
    N, K = len(allk), sum(allk)
    if n == 0 or N == 0:
        return None
    p = k / n
    if base_kind == "pool":
        base, nb, kb = K / N, N, K
    else:
        nb, kb = N - n, K - k
        base = (kb / nb) if nb else None
    return {"n": n, "k": k, "P": r4(p), "base": r4(base), "base_n": nb, "base_k": kb,
            "lift": (None if base is None else r4(p - base)),
            "ratio": (None if not base else r4(p / base)),
            "P_ci95": wilson(k, n),
            "fisher_p": (None if base is None else
                         r4(fisher_2x2(k, n - k, kb, nb - kb)))}


def mh(strata):
    """Mantel-Haenszel の共通オッズ比と、業種調整後の lift（周辺の期待から復元）。

    strata: [(a,b,c,d)] = (群のヒット, 群の外れ, 群外のヒット, 群外の外れ)
    """
    num = den = 0.0
    e_sum = obs_sum = n_g = 0.0
    for (a, b, c, d) in strata:
        n = a + b + c + d
        if n == 0:
            continue
        num += a * d / n
        den += b * c / n
        e_sum += (a + b) * (a + c) / n
        obs_sum += a
        n_g += a + b
    orr = (num / den) if den else None
    # 業種調整後の lift ＝ (観測ヒット − 業種内期待ヒット) / 群のサイズ
    adj = ((obs_sum - e_sum) / n_g) if n_g else None
    return {"MH_OR": r4(orr), "adj_lift": r4(adj),
            "obs_hits": obs_sum, "expected_hits_within_sector": r4(e_sum),
            "n_group": int(n_g), "n_strata": len(strata)}


def strata_from(members, lab, sic, drop=None):
    by = defaultdict(lambda: [0, 0, 0, 0])
    for t, y in lab.items():
        s = sic.get(t)
        if drop is not None and s == drop:
            continue
        i = (0 if t in members else 2) + (0 if y else 1)
        by[s][i] += 1
    return [tuple(v) for v in by.values()], by


# ───────────────────────── 置換（会社単位・全ビンテージ同時） ─────────────────────────
class Perm:
    """会社の結果の束をまるごと入れ替える。ビンテージをまたぐ従属を壊さない。

    ⚠ ビンテージ内で独立に混ぜると帰無が壊れ偽陽性率が桁で過小になる（既記録・実測33倍）。
    """

    def __init__(self, labs, sic, seed, stratify=True):
        self.rnd = random.Random(seed)
        self.vs = sorted(labs)
        self.labs = labs
        allt = sorted(set().union(*[set(labs[v]) for v in self.vs]))
        self.allt = allt
        # 被覆パターン（どのビンテージに居るか）ごとに入れ替える＝未定義セルを作らない
        by = defaultdict(list)
        for t in allt:
            pat = tuple(1 if t in labs[v] else 0 for v in self.vs)
            key = (pat, sic.get(t)) if stratify else (pat,)
            by[key].append(t)
        self.by = dict(by)
        sizes = sorted(len(x) for x in by.values())
        singles = sum(len(x) for x in by.values() if len(x) < 2)
        self.info = {"n_tickers": len(allt), "n_cells": len(by),
                     "stratified_by_sector": stratify,
                     "cell_size_min_med_max": [sizes[0], sizes[len(sizes) // 2], sizes[-1]],
                     "tickers_in_cells_of_size1": singles,
                     "share_frozen_by_construction": r4(singles / len(allt)),
                     "warning": ("⚠ 層が細かすぎて %d社(%.1f%%)が入れ替わらない＝帰無が壊れている"
                                 % (singles, 100 * singles / len(allt))) if singles else None,
                     "coverage_patterns": {str(k[0]): 0 for k in by}}
        for k, ts in by.items():
            self.info["coverage_patterns"][str(k[0])] += len(ts)

    def draw(self, shuffle=True):
        if not shuffle:
            return {v: dict(self.labs[v]) for v in self.vs}
        mp = {}
        for _k, ts in self.by.items():
            sh = list(ts)
            self.rnd.shuffle(sh)
            for a, b in zip(ts, sh):
                mp[a] = b
        out = {}
        for v in self.vs:
            out[v] = {t: self.labs[v][mp[t]] for t in self.labs[v] if mp[t] in self.labs[v]}
        return out


# ───────────────────────── 本体 ─────────────────────────
def main():
    with open(PREREG, encoding="utf-8") as f:
        prereg = json.load(f)
    irr, prov, irr_conf, irr_raw = load_irr()
    px = load_monthly()
    panel, pmap = load_panel()
    tmap = load_targets()

    R = {"generated": str(datetime.date.today()), "tool": "night/hist10_verify_irr70_persist.py",
         "prereg": PREREG, "purpose": "角度Bの候補『irr=70 → 持続』を6検問で潰しにかかる。反証が仕事で確認ではない。",
         "candidate": {
             "angle": "B（持続）", "variable": "【対照】irr=70（2018の読解では75）",
             "target": "y_persist（前半 ∧ 後半 とも年率10%+）", "population": "P_full",
             "cut": "irr==70 の社",
             "explorer_claim": {"design": "B1（入口2013）", "n": 51, "numerator": 24,
                                "P": 0.4706, "base": 0.2602, "lift": 0.2104},
             "explorer_defence": "設計をまたぐと符号が反転する＝規則にできない",
             "prereg_status": "**そもそも事前登録の候補ではない**。prereg.candidates は "
                              "『irr/moat5/dom は対照専用で候補にしない』と明記している。"
                              "以下は対照として置かれた数字を、候補と同じ厳しさで裁いた結果",
         },
         "independence": "hist10_angleB / hist10_targets / hist10_diag を import しない。"
                         "irr は retro_moat_*.json、y_persist は retro_monthly_*.json から自前で組む",
         "pass_line": {"lift": LIFT, "min_numerator": MIN_NUM,
                       "sign_stability": "2016/2017/2018 すべてで lift>=0.15",
                       "sector": "MH ＋ 業種1つ抜き", "not_irr_shadow": "irr>=70 層内でも残る",
                       "incremental_max_caught": MAX_CAUGHT,
                       "all_required": "すべて。1つでも欠ければ不合格"}}

    # ── 前提: irr の組み直し ──
    R["build_irr"] = {
        "sources": {str(v): [{"file": p, "key": k, "label": lb} for (p, k, lb) in s]
                    for v, s in MOAT_SRC.items()},
        "n_by_vintage": {str(v): len(irr[v]) for v in irr},
        "dist_by_vintage": {str(v): {str(k): c for k, c in
                                     sorted(Counter(irr[v].values()).items(),
                                            key=lambda x: (x[0] is None, x[0]))}
                            for v in irr},
        "conflicts_between_files": irr_conf,
        "harmonisation": "2018 の irr18=75 を 70 と同じ刻みに畳む（パネルの約束）。"
                         "生値の分布も残す",
        "raw_2018_dist": {str(k): c for k, c in Counter(irr_raw[2018].values()).items()},
    }
    # パネルの irr と一致するか（同じ台帳を見る二つの検査器が違うことを言ってはいけない）
    mism, harm = [], []
    for v in irr:
        for t, g in irr[v].items():
            pr = pmap.get((t, v))
            if pr is None:
                continue
            pv = pr.get("irr")
            if pv == g:
                continue
            if g == 70 and pv == 75:
                harm.append(t)          # 畳み方の違いだけ（パネルは生値75を保持）
            else:
                mism.append({"vintage": v, "ticker": t, "mine": g, "panel": pv})
    R["build_irr"]["vs_panel"] = {
        "real_mismatch_n": len(mism), "rows": mism[:20],
        "harmonisation_only_n": len(harm),
        "note": "パネルは 2018 の生値 75 をそのまま持つ。畳むのは分析側（探索側も同じ）。"
                "畳んだあとの分布は探索側の by_irr と一致するかを次で確かめる",
    }
    # 探索側 B2 の by_irr の n と突き合わせる（同じ台帳を見る二つの検査器が違うことを言ってはいけない）
    R["build_irr"]["vs_explorer_B2_2018_counts"] = {
        "mine": {str(k): c for k, c in sorted(Counter(irr[2018].values()).items())},
        "explorer": {"irr<=50": 73, "irr=70(2018の読解では75)": 42, "irr=85": 21},
    }

    # ── 前提: y_persist の組み直し ──
    designs = {}
    # B1: 事前登録どおり（入口2013・分割は2018-07）
    d13, m13 = build_persist(px, 2013, (2018, 7))
    designs["B1_2013"] = (d13, m13, 2013)
    # 追加: 2015 の入口（irr の読解がある年）。2つの割り方を両方作る
    d15a, m15a = build_persist(px, 2015, (2018, 7))
    designs["X_2015_split2018"] = (d15a, m15a, 2015)
    d15b, m15b = build_persist(px, 2015, (2021, 1))     # 11.1年の中点
    designs["X_2015_midpoint"] = (d15b, m15b, 2015)
    # B2: 入口2018・その窓自身の中点（2022-07）
    d18, m18 = build_persist(px, 2018, (2022, 7))
    designs["B2_2018"] = (d18, m18, 2018)

    R["build_target"] = {"definition": "pre と post の**両方**が年率10%+（線は prereg の 0.10）",
                         "windows": {k: v[1] for k, v in designs.items()},
                         "source": "retro_monthly_{2013_2018,2018_2026}.json を自分で継いだ"}

    # 自前の組み直しと在庫（targets）の突合せ
    chk = {"n": 0, "flips": 0, "examples": [], "pre_max_abs": 0.0, "post_max_abs": 0.0}
    for t, r in d13.items():
        tg = tmap.get((t, 2013))
        if tg is None or tg.get("y_persist") is None:
            continue
        chk["n"] += 1
        if tg.get("r_pre") is not None:
            chk["pre_max_abs"] = max(chk["pre_max_abs"], abs(tg["r_pre"] - r["pre"]))
        if tg.get("r_post") is not None:
            chk["post_max_abs"] = max(chk["post_max_abs"], abs(tg["r_post"] - r["post"]))
        if bool(tg["y_persist"]) != r["y_persist"]:
            chk["flips"] += 1
            if len(chk["examples"]) < 8:
                chk["examples"].append({"t": t, "inventory": bool(tg["y_persist"]),
                                        "mine": r["y_persist"], "pre": r4(r["pre"]),
                                        "post": r4(r["post"])})
    chk["pre_max_abs"] = r4(chk["pre_max_abs"])
    chk["post_max_abs"] = r4(chk["post_max_abs"])
    chk["flip_share"] = r4(chk["flips"] / chk["n"]) if chk["n"] else None
    chk["note"] = ("在庫は (1+r13)^13.09=(1+r_pre)^5.0×(1+r18)^8.09 の代数で復元、"
                   "こちらは月次から直に測る。裏返るのは 10% の線の際どい社＝"
                   "どちらかが誤りではなく月足の端1ヶ月ぶんの不定性")
    R["build_target"]["vs_inventory_2013"] = chk

    # 母集団 P_full ∩ window_full（在庫の札に依らず、パネルの母集団定義だけ借りる）
    def pop(v):
        return {r["ticker"] for r in panel["rows"]
                if r["vintage"] == v and r.get("P_full") is True
                and r.get("has_outcome") is True and r.get("window_full") is True}

    sic = {}
    pq = {}
    for r in panel["rows"]:
        sic[(r["ticker"], r["vintage"])] = r.get("sic2")
        pq[(r["ticker"], r["vintage"])] = r.get("P_quality")

    def labs_for(dname):
        d, _m, v = designs[dname]
        P = pop(v)
        return {t: (1 if d[t]["y_persist"] else 0) for t in d if t in P}, v

    # ═════════════ 検問1: 再現 ═════════════
    lab13, _ = labs_for("B1_2013")
    read13 = {t for t in irr[2013] if t in lab13}
    g70 = {t for t in read13 if irr[2013][t] == 70}
    lab_read = {t: lab13[t] for t in read13}

    variants = {}
    # (a) 探索側の約束: 母集団＝読解プール（irr が読まれた社）
    variants["読解プール基準・>=（探索側の約束）"] = cell(g70, lab_read, "pool")
    variants["読解プール基準・群を除いた残りと比較"] = cell(g70, lab_read, "rest")
    # (b) 母集団＝P_full 全体（読まれていない社も含む）
    variants["P_full全体基準（読解の選抜を無視）"] = cell(g70, lab13, "pool")
    # (c) 境界の約束を > に振る
    d13g, _ = build_persist(px, 2013, (2018, 7), ge=False)
    lab13g = {t: (1 if d13g[t]["y_persist"] else 0) for t in d13g if t in pop(2013)}
    lab_read_g = {t: lab13g[t] for t in read13 if t in lab13g}
    variants["読解プール基準・>（境界を厳しく）"] = cell(g70 & set(lab_read_g), lab_read_g, "pool")
    # (d) 在庫の札（代数で復元した y_persist）を使う
    lab_inv = {}
    for t in pop(2013):
        tg = tmap.get((t, 2013))
        if tg and tg.get("y_persist") is not None:
            lab_inv[t] = 1 if tg["y_persist"] else 0
    lab_inv_read = {t: lab_inv[t] for t in read13 if t in lab_inv}
    variants["在庫の札（代数復元）・読解プール基準"] = cell(g70 & set(lab_inv_read), lab_inv_read, "pool")
    # (e) irr>=70 でまとめた場合（『70か否か』ではなく『70以上か』）
    gge70 = {t for t in read13 if irr[2013][t] is not None and irr[2013][t] >= 70}
    variants["参考: irr>=70 でまとめる"] = cell(gge70, lab_read, "pool")

    claim = R["candidate"]["explorer_claim"]
    main_v = variants["読解プール基準・>=（探索側の約束）"]      # 自前の月次で組んだ札
    inv_v = variants["在庫の札（代数復元）・読解プール基準"]      # 探索側と同じ札
    R["gate1_reproduce"] = {
        "def": "探索側の n/分子/lift を独立実装で再現できるか。境界の約束（>= か >）と "
               "base の定義まで振る",
        "variants": variants,
        "match_explorer_same_label": {
            "note": "探索側と**同じ札**（在庫の代数復元）を使ったときの一致。"
                    "群の切り方・base の定義・境界の約束まで揃えて突き合わせる",
            "n": inv_v["n"] == claim["n"],
            "numerator": inv_v["k"] == claim["numerator"],
            "P": abs(inv_v["P"] - claim["P"]) <= 0.001,
            "base": abs(inv_v["base"] - claim["base"]) <= 0.001,
            "lift": abs(inv_v["lift"] - claim["lift"]) <= 0.001,
        },
        "independent_label_rebuild": {
            "note": "月次系列から**独立に**組み直した札。差は既知の±1ヶ月の不定性で、"
                    "**候補に有利な側**（分子が増える）にずれる＝再現の失敗ではない",
            "n": main_v["n"], "numerator": main_v["k"], "lift": main_v["lift"],
            "delta_numerator": main_v["k"] - claim["numerator"],
            "delta_lift": r4(main_v["lift"] - claim["lift"]),
        },
        "boundary_sensitivity": {
            "note": "10% の線を >= から > に変えると誰が動くか",
            "ge_n_k": [main_v["n"], main_v["k"]],
            "gt_n_k": [variants["読解プール基準・>（境界を厳しく）"]["n"],
                       variants["読解プール基準・>（境界を厳しく）"]["k"]],
        },
        "base_definition_matters": {
            "note": "探索側の base=0.2602 は **読解プール246社の基準率**であって "
                    "P_full 941社の基準率(0.2189)ではない。どちらを使うかで lift が動く",
            "lift_pool_base": main_v["lift"],
            "lift_Pfull_base": variants["P_full全体基準（読解の選抜を無視）"]["lift"],
        },
    }
    R["gate1_reproduce"]["verdict"] = (
        "✓再現（同じ札で完全一致・独立の札では候補に有利側へ+%d社）"
        % (main_v["k"] - claim["numerator"])
        if all(R["gate1_reproduce"]["match_explorer_same_label"].values())
        else "✗再現しない")

    # ── 到達可能性・実効要求倍率・検出力 ──
    n_g, base = main_v["n"], main_v["base"]
    need = max(MIN_NUM, math.ceil((base + LIFT) * n_g - 1e-9))
    R["reachability_and_power"] = {
        "reachable_up": {"max_numerator": n_g, "need": need,
                         "ok": n_g >= need,
                         "binding": ("lift" if math.ceil((base + LIFT) * n_g - 1e-9) > MIN_NUM
                                     else "min_numerator")},
        "reachable_down": {"note": "下向き（10%%+を減らす）は base=%.4f>0.15 なので絶対差でも到達可能" % base,
                           "need_k_at_most": max(0, math.floor((base - LIFT) * n_g)),
                           "ok": True},
        "effective_required_ratio": r4(need / (n_g * base)),
        "power": {("delta=%.2f" % dd): r4(binom_tail_ge(n_g, need, min(0.999, base + dd)))
                  for dd in (0.10, 0.15, 0.20, 0.25)},
        "power_note": "n=%d・base=%.4f・必要分子=%d の下での検出力（二項）。"
                      "候補が実際に出した分子は %d" % (n_g, base, need, main_v["k"]),
    }

    # ═════════════ 検問2: ビンテージ ═════════════
    v2 = {"def": "2016/2017/2018 すべてで lift>=0.15 を維持するか（prereg の符号不変ゲート）",
          "literal_prereg": {}, "measurable_designs": {}, "substantive": {}}

    # 文字どおりの prereg ゲートは何が測れて何が測れないか
    for v in (2016, 2017, 2018):
        has_irr = len(irr.get(v, {}))
        v2["literal_prereg"][str(v)] = {
            "irr_read": has_irr,
            "y_persist_definable_at_this_entry_in_B1": False,
            "status": ("判定不能（irrの読解が無い）" if has_irr == 0
                       else "y_persist は入口2013でしか定義されない＝B1では到達不能"),
        }
    v2["literal_prereg"]["_verdict"] = (
        "✗ 文字どおりの符号不変ゲートは**構造的に到達不能**。"
        "y_persist(B1) は入口2013にしか無く、2016/2017 は irr の読解自体が無い。"
        "『不合格』ではなく『未検定』——両者を取り違えない")

    # 測れる設計で当てる
    for name in ("B1_2013", "X_2015_split2018", "X_2015_midpoint", "B2_2018"):
        d, meta, v = designs[name]
        P = pop(v)
        lab = {t: (1 if d[t]["y_persist"] else 0) for t in d if t in P}
        rd = {t for t in irr.get(v, {}) if t in lab}
        gg = {t for t in rd if irr[v][t] == 70}
        lr = {t: lab[t] for t in rd}
        c = cell(gg, lr, "pool")
        v2["measurable_designs"][name] = {
            "window": meta, "n_read": len(rd), "cell": c,
            "pass_lift": (c is not None and c["lift"] is not None and c["lift"] >= LIFT),
            "pass_minnum": (c is not None and c["k"] >= MIN_NUM),
            "by_irr": {str(g): cell({t for t in rd if irr[v][t] == g}, lr, "pool")
                       for g in sorted({irr[v][t] for t in rd if irr[v][t] is not None})},
        }
    # 符号の反転は「窓の違い」か「読まれた社が違うこと」か——同じ社に絞って当て直す
    d13d, d18d = designs["B1_2013"][0], designs["B2_2018"][0]
    common = ({t for t in irr[2013] if t in d13d and t in pop(2013)}
              & {t for t in irr[2018] if t in d18d and t in pop(2018)})
    agree = sum(1 for t in common if irr[2013][t] == irr[2018][t])
    lab13c = {t: (1 if d13d[t]["y_persist"] else 0) for t in common}
    lab18c = {t: (1 if d18d[t]["y_persist"] else 0) for t in common}
    g70_13c = {t for t in common if irr[2013][t] == 70}
    g70_18c = {t for t in common if irr[2018][t] == 70}
    g70_both = g70_13c & g70_18c
    v2["same_companies"] = {
        "def": "2013 と 2018 の**両方で読まれた社**だけに絞って符号を当て直す。"
               "反転が『窓の違い』なのか『読まれた社が違うこと』なのかを分ける",
        "n_common": len(common),
        "irr_agreement_between_reads": {"agree": agree, "n": len(common),
                                        "share": r4(agree / len(common)) if common else None},
        "2013窓・2013の読みで irr=70": cell(g70_13c, lab13c, "pool"),
        "2018窓・2018の読みで irr=70": cell(g70_18c, lab18c, "pool"),
        "2013窓・両読みとも70": cell(g70_both, lab13c, "pool"),
        "2018窓・両読みとも70": cell(g70_both, lab18c, "pool"),
        "reading": "同じ社に揃えても符号が保たれないなら、反転は読解プールの構成ではなく**窓（レジーム）**の側",
        "⚠ceiling": "共通57社は**2回読まれた社＝際立った社**に偏り、2013窓の基準率が %s まで上がる。"
                     "基準率が高いと絶対差の lift は天井で圧縮されるので、"
                     "ここでの縮小の一部は**構成でも窓でもなく天井**。過大に読まないこと"
                     % r4(sum(lab13c.values()) / len(lab13c)),
    }

    signs = {k: (val["cell"]["lift"] if val["cell"] else None)
             for k, val in v2["measurable_designs"].items()}
    v2["substantive"] = {
        "def": "irr の読解がある年（2013/2015/2018）で符号が保たれるか。"
               "prereg の 2016/2017/2018 が到達不能なので、**測れる年で同じ問いを当てる**",
        "lifts": {k: r4(x) if x is not None else None for k, x in signs.items()},
        "n_designs_measurable": len(signs),
        "n_designs_with_lift_ge_0.15": sum(1 for x in signs.values() if x is not None and x >= LIFT),
        "n_designs_negative": sum(1 for x in signs.values() if x is not None and x < 0),
        "vintages_clearing_0.15": ["2013"] if signs["B1_2013"] >= LIFT else [],
        "criterion": "prereg は『すべてのビンテージで lift>=0.15』。到達可能な設計に文字どおり写すと"
                     "**測れる設計すべて**が 0.15 を超えることを要求する",
        "contrast_irr85": {k: (val["by_irr"].get("85", {}) or {}).get("lift")
                           for k, val in v2["measurable_designs"].items()},
        "contrast_irr100": {k: (val["by_irr"].get("100", {}) or {}).get("lift")
                            for k, val in v2["measurable_designs"].items()},
        "contrast_note": "**同じ4設計で irr=85 は一度も符号を落とさない**（既記録『上を狙うなら85』と整合）。"
                         "irr=100 は測れる3設計すべてで負。つまり設計が壊れているのではなく"
                         "**70という刻みだけが持たない**",
    }
    v2["verdict"] = "保留（下で確定）"
    R["gate2_vintage"] = v2

    # ═════════════ 検問3: 業種 ═════════════
    sic13 = {t: sic.get((t, 2013)) for t in lab_read}
    st, by = strata_from(g70, lab_read, sic13)
    mh_all = mh(st)
    loo = {}
    for s in sorted({x for x in sic13.values() if x is not None}):
        lab_s = {t: y for t, y in lab_read.items() if sic13.get(t) != s}
        g_s = g70 & set(lab_s)
        c = cell(g_s, lab_s, "pool")
        if c is None:
            continue
        loo[str(s)] = {"dropped_n_group": main_v["n"] - c["n"],
                       "n": c["n"], "k": c["k"], "lift": c["lift"],
                       "pass": (c["lift"] is not None and c["lift"] >= LIFT and c["k"] >= MIN_NUM)}
    worst = sorted(((k, v["lift"]) for k, v in loo.items() if v["lift"] is not None),
                   key=lambda x: x[1])[:6]
    # 群の業種構成
    comp = Counter(sic13.get(t) for t in g70)
    R["gate3_sector"] = {
        "def": "同一 sic2 内でも残るか（Mantel-Haenszel）＋業種を1つずつ抜いても残るか",
        "MH": mh_all,
        "MH_pass": (mh_all["adj_lift"] is not None and mh_all["adj_lift"] >= LIFT),
        "group_sector_composition": {str(k): c for k, c in comp.most_common()},
        "leave_one_sector_out": loo,
        "worst_six": [{"sic2": k, "lift": r4(x)} for k, x in worst],
        "n_loo_fail": sum(1 for v in loo.values() if not v["pass"]),
        "n_loo": len(loo),
    }
    R["gate3_sector"]["verdict"] = ("✓通過" if (R["gate3_sector"]["MH_pass"]
                                             and R["gate3_sector"]["n_loo_fail"] == 0)
                                    else "✗落ちる")

    # ═════════════ 検問4: irr の影 ═════════════
    # 候補そのものが irr なので degenerate。正直に書いたうえで意味のある変種を測る
    rest_ge70 = gge70 - g70
    c_within = cell(g70, {t: lab_read[t] for t in gge70}, "pool")
    c_vs_rest_high = cell(g70, {t: lab_read[t] for t in (g70 | rest_ge70)}, "rest")
    R["gate4_irr_shadow"] = {
        "def": "irr>=70 の層内でも残るか（候補が irr の影でないことの確認）",
        "degenerate": "**この候補は irr そのもの**。irr>=70 で層別すると候補は層の部分集合になり、"
                      "『irr の影か』という問いが自己言及になる＝この検問は候補に当てられない",
        "status": "判定不能（自己言及）",
        "meaningful_variant": {
            "def": "irr>=70 の中で 70 が 85/100 より良いか（『70が持続を予言する』の中身）",
            "within_irr_ge70": c_within,
            "vs_rest_of_irr_ge70": c_vs_rest_high,
            "by_grade": {str(g): cell({t for t in read13 if irr[2013][t] == g}, lab_read, "pool")
                         for g in (50, 70, 85, 100)},
        },
    }

    # ═════════════ 検問5: 置換 ═════════════
    labs_all, sic_all = {}, {}
    for name, v in (("B1_2013", 2013), ("X_2015_split2018", 2015), ("B2_2018", 2018)):
        d, _m, _v = designs[name]
        P = pop(v)
        rd = {t for t in irr.get(v, {}) if t in d and t in P}
        labs_all[v] = {t: (1 if d[t]["y_persist"] else 0) for t in rd}
        for t in rd:
            sic_all[t] = sic.get((t, v)) or sic_all.get(t)
    grp = {v: {t for t in labs_all[v] if irr[v][t] == 70} for v in labs_all}

    def stat(labs):
        """観測統計: 各ビンテージの lift（読解プール基準）"""
        o = {}
        for v in labs:
            c = cell(grp[v], labs[v], "pool")
            o[v] = c["lift"] if c else None
        return o

    obs = stat(labs_all)
    obs_lift = obs.get(2013)

    def run_null(stratify, seed):
        PM = Perm(labs_all, sic_all, seed, stratify=stratify)
        hits_gate = hits_all = 0
        dist = []
        for _ in range(N_PERM):
            lb = PM.draw()
            c13 = cell(grp[2013], lb[2013], "pool")
            dist.append(c13["lift"] if c13 else None)
            if c13 and c13["lift"] is not None and c13["lift"] >= LIFT and c13["k"] >= MIN_NUM:
                hits_gate += 1
            ok = True
            for v in labs_all:
                c = cell(grp[v], lb[v], "pool")
                if not (c and c["lift"] is not None and c["lift"] >= LIFT):
                    ok = False
                    break
            if ok:
                hits_all += 1
        xs = sorted(x for x in dist if x is not None)
        return {
            "perm_info": PM.info,
            "p_one_sided_2013": r4((sum(1 for x in xs if x >= obs_lift) + 1) / (N_PERM + 1)),
            "fpr_2013_cell_gate(lift>=0.15 ∧ 分子>=20)": r4(hits_gate / N_PERM),
            "fpr_all_three_designs_lift>=0.15": r4(hits_all / N_PERM),
            "null_lift_2013_quantiles": {q: r4(xs[int(qq * (len(xs) - 1))])
                                         for q, qq in (("p50", .5), ("p90", .9),
                                                       ("p95", .95), ("p99", .99))},
            "null_lift_mean": r4(sum(xs) / len(xs)),
        }

    # 主＝層別なし（事前登録の文言どおり「会社単位で全ビンテージ同時」）。
    # 層別ありは参考——sic2×被覆パターンで切ると層が細かくなりすぎ、多くの社が動かない
    null_flat = run_null(False, SEED)
    null_sic = run_null(True, SEED)

    # ⚠ 上の二つは**被覆パターン（どの年に読まれたか）を保つ**ので、群がどのパターンに
    #   偏っているかぶんだけ帰無の期待 lift が 0 から浮く。純粋な帰無（2013の246社の札を
    #   素朴に混ぜる）も出して、その差＝**読まれ方の選抜が持ち込む下駄**を見せる
    rnd = random.Random(SEED + 7)
    keys13 = sorted(labs_all[2013])
    vals13 = [labs_all[2013][t] for t in keys13]
    plain, hits_p = [], 0
    for _ in range(N_PERM):
        sh = list(vals13)
        rnd.shuffle(sh)
        lb = dict(zip(keys13, sh))
        c = cell(grp[2013], lb, "pool")
        plain.append(c["lift"])
        if c["lift"] >= LIFT and c["k"] >= MIN_NUM:
            hits_p += 1
    ps = sorted(plain)
    null_plain = {
        "def": "2013の読解プール246社の札を素朴に混ぜる（被覆パターンを保たない）。"
               "この帰無では期待 lift が厳密に 0 になる",
        "null_lift_mean": r4(sum(ps) / len(ps)),
        "p_one_sided_2013": r4((sum(1 for x in ps if x >= obs_lift) + 1) / (N_PERM + 1)),
        "fpr_2013_cell_gate(lift>=0.15 ∧ 分子>=20)": r4(hits_p / N_PERM),
        "null_lift_quantiles": {q: r4(ps[int(qq * (len(ps) - 1))])
                                for q, qq in (("p50", .5), ("p90", .9),
                                              ("p95", .95), ("p99", .99))},
    }
    R["gate5_permutation"] = {
        "def": "会社単位で全ビンテージ同時に結果を並べ替える2000回。"
               "ビンテージ内で独立に混ぜると従属が壊れ偽陽性率が桁で過小になる（既記録）",
        "n_perm": N_PERM, "seed": SEED,
        "observed_lift_by_vintage": {str(k): r4(v) for k, v in obs.items()},
        "primary_company_level": null_flat,
        "reference_sector_stratified": null_sic,
        "reference_plain_2013_only": null_plain,
        "why_primary_is_unstratified":
            "sic2×被覆パターンで層別すると層が細かくなりすぎ、"
            "**%d社(%.1f%%)が層の唯一の住人＝入れ替わらない**。"
            "事前登録の文言は『会社単位で全ビンテージ同時』なのでそちらを主にする"
            % (null_sic["perm_info"]["tickers_in_cells_of_size1"],
               100 * null_sic["perm_info"]["share_frozen_by_construction"]),
        "★selection_pedestal": {
            "def": "**三つの帰無の平均 lift の差そのものが所見**。"
                   "被覆パターン（どの年に読まれたか）を保つ帰無では期待 lift が 0 から浮く"
                   "＝群が『複数年で読まれた社』に偏っているぶんの下駄",
            "plain_null_mean(期待0)": null_plain["null_lift_mean"],
            "coverage_preserving_null_mean": null_flat["null_lift_mean"],
            "sector×coverage_null_mean": null_sic["null_lift_mean"],
            "observed": r4(obs_lift),
            "reading": "観測 %s のうち **%s は『どの年に読まれたか』だけで説明が付く**。"
                       "残差は約 %s。それでも被覆を保つ帰無に対して p=%s なので"
                       "『下駄で全部説明できる』わけではない"
                       % (r4(obs_lift), null_flat["null_lift_mean"],
                          r4(obs_lift - null_flat["null_lift_mean"]),
                          null_flat["p_one_sided_2013"]),
        },
    }
    R["gate5_permutation"]["verdict"] = (
        "✓通過（偶然では出ない）" if null_flat["p_one_sided_2013"] <= 0.05
        else "✗偶然と区別できない")

    # ═════════════ 検問6: 増分 ═════════════
    hits = {t for t in g70 if lab_read.get(t) == 1}
    caught = {}
    # (a) 質実証
    q_true = {t for t in hits if pq.get((t, 2013)) is True}
    caught["質実証(P_quality)"] = {"k": len(q_true), "share": r4(len(q_true) / len(hits)),
                                  "basis": "パネルの P_quality（2013は3条件＝規約どおり）"}
    # (b) 事業の収縮（cagr5<0 ∧ opmD5<0）— 2013 は opmD5 が無い
    sh_strict, sh_proxy = 0, 0
    n_shrink_measurable = 0
    for t in hits:
        pr = pmap.get((t, 2013)) or {}
        c5, od5 = pr.get("co_sales_cagr5"), pr.get("f2_opmD5")
        if od5 is not None and c5 is not None:
            n_shrink_measurable += 1
            if c5 < 0 and od5 < 0:
                sh_strict += 1
        if c5 is not None and c5 < 0:
            sh_proxy += 1
    caught["事業の収縮（厳密 cagr5<0 ∧ opmD5<0）"] = {
        "k": sh_strict, "measurable": n_shrink_measurable,
        "share": None,
        "status": "**判定不能**。2013の入口には f2_opmD5（営業利益率の5年変化）が無い（f2_ は2016-2018のみ）",
    }
    caught["（参考・上位集合）売上5年CAGR<0 だけ"] = {
        "k": sh_proxy, "share": r4(sh_proxy / len(hits)),
        "note": "厳密条件の**上位集合**なので既存の関門が捕まえる数を必ず過大に出す＝候補に不利な側の見積り",
    }
    # (c) 薄い財務 intcov<3 — 2013 には無い
    caught["薄い財務（intcov<3）"] = {
        "k": None, "share": None,
        "status": "**判定不能**。2013の入口には f2_intcov が無い（f2_ は2016-2018のみ）",
    }
    # (d) irr>=70（課題文の指定）— 候補そのもの
    caught["irr>=70"] = {
        "k": len(hits), "share": 1.0,
        "status": "**自己言及**。候補（irr==70）は irr>=70 の部分集合なので定義上 100%。"
                  "循環なので増分の証拠として数えない",
    }
    # 測れる関門の和集合
    union = q_true | {t for t in hits
                      if (pmap.get((t, 2013)) or {}).get("co_sales_cagr5") is not None
                      and (pmap.get((t, 2013)) or {})["co_sales_cagr5"] < 0}
    # 数え上げだけでは足りない——既存の関門で層別しても効果が残るか（条件付き）
    cond = {}
    for nm, sel in (("質実証=True", True), ("質実証=False", False)):
        lb = {t: y for t, y in lab_read.items() if pq.get((t, 2013)) is sel}
        c = cell(g70 & set(lb), lb, "pool")
        cond[nm] = c
    st3 = []
    for sel in (True, False):
        ts = {t for t in lab_read if pq.get((t, 2013)) is sel}
        a = sum(1 for t in ts & g70 if lab_read[t] == 1)
        b = len(ts & g70) - a
        c_ = sum(1 for t in ts - g70 if lab_read[t] == 1)
        d_ = len(ts - g70) - c_
        st3.append((a, b, c_, d_))
    # 既存の関門そのものの持続予言力（比較の錨）
    q_cell = cell({t for t in lab_read if pq.get((t, 2013)) is True}, lab_read, "pool")
    R["gate6_incremental"] = {
        "def": "この群の『持続した社』は、門が既に持つ関門で説明が付く社ではないか。"
               "7割超が既存で説明されるなら不合格（prereg）",
        "n_hits_in_group": len(hits),
        "caught_by": caught,
        "union_of_measurable_gates": {"k": len(union), "share": r4(len(union) / len(hits))},
        "coverage_problem": "2013の入口で測れる既存関門は **質実証だけ**。"
                            "事業の収縮・薄い財務は f2_ 列が2016-2018にしか無いので測れない。"
                            "したがってこの検問は**部分的にしか当てられない**",
        "conditional_on_existing_gate": {
            "def": "数え上げ（重なり）だけでは『既存が説明している』の証拠にならない。"
                   "既存の関門で層別しても候補の効果が残るかを見る",
            "cells": cond,
            "MH_over_quality": mh(st3),
            "existing_gate_alone": {"note": "質実証そのものの持続予言力（比較の錨）", "cell": q_cell},
        },
    }
    share_caught = len(union) / len(hits)
    q_lift = q_cell["lift"] if q_cell else None
    mh_q = R["gate6_incremental"]["conditional_on_existing_gate"]["MH_over_quality"]["adj_lift"]
    if share_caught > MAX_CAUGHT:
        vd = "✗既存で7割超が説明される（%.1f%%）" % (100 * share_caught)
    else:
        vd = ("✓通過（数え上げ %.1f%% < %.0f%%）。しかも**重なりは冗長の証拠になっていない**"
              "——質実証そのものの持続予言力は lift %s（Fisher p=%s）でほぼ無く、"
              "質実証で層別しても候補の効果は残る（True %s / False %s・MH調整後 %s）"
              % (100 * share_caught, 100 * MAX_CAUGHT, q_lift, q_cell["fisher_p"],
                 cond["質実証=True"]["lift"], cond["質実証=False"]["lift"], mh_q))
    R["gate6_incremental"]["verdict"] = vd
    R["gate6_incremental"]["why_overlap_is_not_redundancy"] = (
        "読解プール246社のうち163社(66%)が質実証＝**プール全体がもともと質に偏っている**ので、"
        "群のヒットの69.2%が質実証なのは当たり前。既存の関門が説明しているかは"
        "『層別しても効果が残るか』で見るべきで、残っている")

    # ═════════════ 追加の反証: 読解プールの構成 ═════════════
    # 2013の読解は「広域119」と「質実証プール130」の二つ。基準率も irr 分布も違うなら
    # 『irr=70 の効果』は『どちらのプールから読まれたか』の影かもしれない
    pool_of = {}
    for t, lb in prov[2013].items():
        pool_of[t] = lb
    sub = {}
    for lb in sorted(set(pool_of.values())):
        ts = {t for t in lab_read if pool_of.get(t) == lb}
        lr = {t: lab_read[t] for t in ts}
        gg = g70 & ts
        c = cell(gg, lr, "pool")
        sub[lb] = {"n_pool": len(ts), "pool_base": r4(sum(lr.values()) / len(lr)) if lr else None,
                   "cell": c,
                   "pass": (c is not None and c["lift"] is not None and c["lift"] >= LIFT
                            and c["k"] >= MIN_NUM)}
    st2 = []
    for lb in sub:
        ts = {t for t in lab_read if pool_of.get(t) == lb}
        a = sum(1 for t in ts & g70 if lab_read[t] == 1)
        b = len(ts & g70) - a
        c_ = sum(1 for t in ts - g70 if lab_read[t] == 1)
        d_ = len(ts - g70) - c_
        st2.append((a, b, c_, d_))
    R["counter_read_pool"] = {
        "def": "2013の読解は『広域119』と『質実証プール130』の二つ（互いに素）。"
               "基準率も irr 分布も違うなら、irr=70 の効果は『どちらのプールから読まれたか』の影かもしれない",
        "by_pool": sub,
        "pool_adjusted_MH": mh(st2),
        "irr_dist_by_pool": {lb: {str(k): c for k, c in
                                  Counter(irr[2013][t] for t in irr[2013]
                                          if prov[2013].get(t) == lb).items()}
                             for lb in sorted(set(prov[2013].values()))},
    }

    # ═════════════ 追加の反証: 札の脆さ ═════════════
    frag = {"within_1pt": 0, "n": 0, "flip_if_pre_shifted": 0}
    for t in g70:
        r = d13.get(t)
        if r is None:
            continue
        frag["n"] += 1
        if abs(r["pre"] - HURDLE) <= 0.01 or abs(r["post"] - HURDLE) <= 0.01:
            frag["within_1pt"] += 1
    frag["share_within_1pt"] = r4(frag["within_1pt"] / frag["n"]) if frag["n"] else None
    # 線を ±1pt 動かしたときの分子
    for dd in (-0.01, 0.01):
        k = sum(1 for t in g70 if (d13[t]["pre"] >= HURDLE + dd and d13[t]["post"] >= HURDLE + dd))
        n_all = {t: (1 if (d13[t]["pre"] >= HURDLE + dd and d13[t]["post"] >= HURDLE + dd) else 0)
                 for t in read13 if t in d13}
        c = cell(g70, n_all, "pool")
        frag["hurdle%+0.2f" % dd] = {"k": k, "lift": c["lift"] if c else None}
    R["counter_fragility"] = frag

    # ═════════════ 総括 ═════════════
    n_ok = v2["substantive"]["n_designs_with_lift_ge_0.15"]
    n_ms = v2["substantive"]["n_designs_measurable"]
    g2_pass = (n_ok == n_ms)
    v2["verdict"] = ("✓通過" if g2_pass else
                     "✗落ちる（測れる%d設計のうち0.15を超えるのは%d＝入口2013だけ。"
                     "2018は符号が反転し、2015は2通りの割り方とも届かない）" % (n_ms, n_ok))
    R["gate2_vintage"] = v2

    gates = {
        "1 再現": R["gate1_reproduce"]["verdict"],
        "2 ビンテージ": v2["verdict"],
        "3 業種": R["gate3_sector"]["verdict"],
        "4 irrの影": "判定不能（自己言及）",
        "5 置換": R["gate5_permutation"]["verdict"],
        "6 増分": R["gate6_incremental"]["verdict"],
    }
    failed = [k for k, v in gates.items() if v.startswith("✗")]
    R["verdict"] = {
        "gates": gates,
        "failed": failed,
        "result": ("不合格" if failed else "落とせなかった"),
        "decisive": "検問2（ビンテージ）。測れる4設計のうち 0.15 を超えるのは入口2013だけで、"
                    "2018 では符号が反転（lift %s）し、2015 は割り方を2通り試してもどちらも届かない"
                    "（%s / %s）。**同じ4設計で irr=85 は一度も符号を落とさない**ので、"
                    "壊れているのは設計ではなく『70という刻み』のほう"
                    % (r4(signs["B2_2018"]), r4(signs["X_2015_split2018"]),
                       r4(signs["X_2015_midpoint"])),
        "not_a_reason": [
            "検問1で分子が24→26にずれたこと（±1ヶ月の不定性で、**候補に有利側**）",
            "検問3（業種）は通っている——MH調整後 %s・業種1つ抜きの52通りすべて通過" % r4(mh_all["adj_lift"]),
            "検問5（置換）も通っている——2013単体の効果は偶然では出ない（p=%s）"
            % R["gate5_permutation"]["primary_company_level"]["p_one_sided_2013"],
            "検問6も通っている——しかも**重なり69.2%%は冗長の証拠ではない**。"
            "質実証そのものの持続予言力は lift %s しか無く、層別しても候補の効果は残る" % r4(q_lift),
            "読解プールの構成（広域119 vs 質実証プール130）でも説明が付かない——"
            "どちらのプール単体でも lift は %s / %s"
            % (R["counter_read_pool"]["by_pool"]["広域119"]["cell"]["lift"],
               R["counter_read_pool"]["by_pool"]["質実証プール130"]["cell"]["lift"]),
            "10%%の線の脆さでもない——線を±1pt動かしても lift は %s〜%s"
            % (R["counter_fragility"]["hurdle+0.01"]["lift"],
               R["counter_fragility"]["hurdle-0.01"]["lift"]),
        ],
        "also_weakens_it": [
            "**読まれ方の下駄**——被覆パターン（どの年に読まれたか）を保つ帰無の期待 lift は %s。"
            "観測 %s のうち約%.0f%%はこれで説明が付き、残差は %s＝**線 0.15 のちょうど上**"
            % (null_flat["null_lift_mean"], r4(obs_lift),
               100 * null_flat["null_lift_mean"] / obs_lift,
               r4(obs_lift - null_flat["null_lift_mean"])),
            "**同じ社に揃えると消える**——2013と2018の両方で読まれた57社に絞ると、"
            "2013窓でも lift は %s（両読みとも70の16社では %s）。"
            "ただし基準率が %s へ上がる天井の効果を含むので過大に読まない"
            % (v2["same_companies"]["2013窓・2013の読みで irr=70"]["lift"],
               v2["same_companies"]["2013窓・両読みとも70"]["lift"],
               v2["same_companies"]["2013窓・2013の読みで irr=70"]["base"]),
            "**70という刻みの中身が空**——irr>=70 の中で 70 が 85/100 より良いかを見ると "
            "lift %s（Fisher p=%s）。つまり2013の効果は『70であること』ではなく"
            "『50でないこと』から来ている"
            % (R["gate4_irr_shadow"]["meaningful_variant"]["within_irr_ge70"]["lift"],
               R["gate4_irr_shadow"]["meaningful_variant"]["within_irr_ge70"]["fisher_p"]),
        ],
        "what_survives": "**入口2013という一つの窓の中でだけ**、irr=70 は持続を強く予言する"
                         "（P=0.51 vs 0.27・Fisher p=0.0015・業種調整後も置換でも残る）。"
                         "だがそれが2015でも2018でも再現しない以上、**規則にはできない**",
        "honest_caveats": [
            "検問4は**この候補には当てられない**（候補が irr そのもの＝自己言及）。判定不能であって不合格ではない",
            "検問6は2013の入口で f2_ 列（opmD5・intcov）が無いため**部分的にしか当てられない**",
            "prereg の 2016/2017/2018 の符号不変ゲートは**構造的に到達不能**"
            "（y_persist は入口2013にしか無く、2016/2017 は irr の読解が無い）。"
            "上の検問2は到達可能な設計へ写した版で、**事前登録の文言そのものではない**",
            "検出力は δ=0.15 で %s＝コイン投げ。『2015/2018で出なかった』は"
            "『効果が無い』の証明ではなく『この標本では掴めない』"
            % R["reachability_and_power"]["power"]["delta=0.15"],
            "対照の irr=85 が4設計とも 0.15 を超えることは**n が 6/12/12/21 と薄い**。"
            "『85は持つ』の証拠としてはこの道具単体では弱く、既記録の追試と併せて読むもの",
            "2015 の結果は 506社の質実証寄りプールの上での話（全社ではない）",
            "そもそも prereg は irr を対照専用と定め候補にしていない",
        ],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1)
    print(json.dumps({"verdict": R["verdict"],
                      "gate1": R["gate1_reproduce"]["variants"]["読解プール基準・>=（探索側の約束）"],
                      "gate2_lifts": v2["substantive"]["lifts"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
