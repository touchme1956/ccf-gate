#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_angleD.py — 角度D: **美点の数（加法スコア）**。

事前登録: out/hist10_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json   （特徴量。再実装しない）
          out/hist10_targets.json  （y10 / y_persist / y_biz の正本）
          night/hist10_diag.py     （**原始関数を import する**。score_masks / count_masks /
                                     ge_mask / perm_engine / build_universes / quantile / mh_diff）
          night/hist10_angleB.py   （B2 の持続ラベル `_ypersist` を import。再実装しない）
出力    : out/hist10_angleD.json

判定・採点・台帳・index.html・パックには一切触らない。読むだけの調査。

────────────────────────────────────────────────────────────
なぜ加法スコアが新しいのか
────────────────────────────────────────────────────────────
これまでの探索は **単変量** と **2本の積** だけ＝関数形が2種類しか試されていない。
個々では lift 0.15 に届かない弱い信号が、**数を数えると効く**（加法）可能性は
一度も検定されていない。積は「全部を同時に満たす」を要求するので群が痩せるが、
和は「いくつ満たすか」なので**弱い信号を足し合わせられる**——別の関数形である。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計上の決定（すべて事前診断 hist10_diag と揃える）
────────────────────────────────────────────────────────────
1) **候補の部分集合は診断と同一**（cov90_14 / all20）。理由は一つ——
   診断が角度Dの偽陽性率を **この部分集合で** 測っているから。別の集合にすると
   「自分の手続きの値札」が分からなくなる（v2 で払った授業料）。
2) **母集団は P_full / P_quality**。P_moat は 2016/2017 に irr の読解が無く n=61-63＝
   分子>=20 に構造的に届かない（診断の到達可能性がそう出している）＝判定不能。
3) **向きを決める年は2つ試す。両方を報告する。**
   - 変種P（診断と同じ・発見年=2018）: 診断の `real_data_pass_count` と**突合せできる**
   - 変種T（依頼文の指定・向きと閾値を **2016** で決めて 2017/2018 に当てる）
   実装は**一つ**（`eval_additive_disc`）で、disc=2018 のとき診断の `eval_additive` と
   **1件も食い違わないこと**を毎回確かめる（v9.9.65: 同じ台帳を見る二つの検査器が
   違うことを言ってはいけない）。
4) 二値化は **中央値**（主）と **上下1/4**（副）。依頼文が「中央値または上下1/4」。
   中央値を主にするのは診断の偽陽性率がそちらで測られているため。
5) スコア = 良い側の数。群は `score>=s`（ge）と `score<=s`（le）の両方。s=1..J。
6) J（何本使うか）は |lift| 上位 3/5/8/10/全。**本数もデータから選ぶ＝自由度**。
7) **cut は各ビンテージのコホート内中央値**（絶対値を持ち越さない）。
   基準の違う二つを割らないため——2016年の中央値を2018年に当てると
   「その年の相対順位」ではなく「暦の水準」を測ってしまう。

────────────────────────────────────────────────────────────
⚠ この角度が構造的に抱えるもの（結果の前に書く）
────────────────────────────────────────────────────────────
・**変数の選び方・本数・閾値・向きの4つすべてがデータから決まる**。診断の実測で
  角度Dの偽陽性率は cov90_14 で 0.1935 / all20 で 0.377 / **和集合 0.482**＝
  **雑音でも約半分の確率で「合格」が1つ出る**。よって
  「lift・分子・符号不変」まで通っただけでは何も言えない。
  残りのゲート（業種・irr層・増分）が本体である。
・complete-case で作るので **all20 は母集団の約26%しか残らず、規模の大きい側へ偏る**
  （診断: 中央値売上 2,090百万$ → 3,776百万$）。lift の一部はこの選択が作りうる。
・2016/2017/2018 は**同じ956ティッカー**（Jaccard=1.00）＝3ビンテージは
  独立な3つの証拠ではない。out-of-sample はこの在庫に一つも無い。
"""

import json
import math
import os
import random
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hist10_diag as D          # noqa: E402  原始関数（再実装しない）
import hist10_angleB as B        # noqa: E402  B2 の持続ラベル

OUT = os.path.join(os.path.dirname(HERE), "out")
DEST = os.path.join(OUT, "hist10_angleD.json")

# ── 事前登録の線。**この道具は一つも作らない**（診断・角度A/B と同じ値を読む） ──
LIFT = D.LIFT                    # 0.15
MIN_NUM = D.MIN_NUM              # 20
INCREMENTAL_MAX_CAUGHT = 0.70    # prereg pass_line.incremental
TRIO = D.TRIO                    # [2016, 2017, 2018]
POPS = ["P_full", "P_quality"]   # P_moat は構造的に判定不能（診断の到達可能性）
SUBSETS = D.SUBSETS              # cov90_14 / all20（診断と同一）
JS = (3, 5, 8, 10)               # + 全本数
SEED = D.SEED
N_PERM = int(os.environ.get("HIST10_NPERM", 2000))
N_POWER = int(os.environ.get("HIST10_NPOWER", 5000))


def r4(x):
    return None if x is None else round(x, 4)


def rate(k, n):
    return (k / n) if n else None


def spearman(xs, ys):
    n = len(xs)
    if n < 8:
        return None

    def rk(v):
        idx = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for t in range(i, j + 1):
                r[idx[t]] = avg
            i = j + 1
        return r

    a, b = rk(xs), rk(ys)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


# ─────────────────── 既存の関門（増分ゲート）。角度A と同一定義 ───────────────────
def g_shrink(r):
    """事業の収縮（v9.9.99・門に実装済み）: 売上5年CAGR<0 ∧ 営業利益率の5年変化<0"""
    return (r.get("f2_cagr5") is not None and r["f2_cagr5"] < 0
            and r.get("f2_opmD5") is not None and r["f2_opmD5"] < 0)


def g_thin(r):
    """財務の薄さ。intcov<3 ＝ 門の nde>4 の歴史側の相当物（v2 と同じ代用）"""
    return r.get("f2_intcov") is not None and r["f2_intcov"] < 3


def g_notq(r):
    return not r.get("P_quality")


def g_blocked(r):
    return g_shrink(r) or g_thin(r) or g_notq(r)


# ─────────────────── 目的変数の取り付け ───────────────────
def load_rows():
    """診断の load() をそのまま使い（再実装しない）、B2 の持続ラベルを足す。"""
    panel, tg, prereg, rows = D.load()
    # B2（角度B・厳密f2・その窓自身の中点で二分）の持続ラベル
    pmap = {}
    for v, rs in B.B2.items():
        for r in rs:
            pmap[(r["ticker"], v)] = (bool(r["_ypersist"]), bool(r["_ypre"]), bool(r["_ypost"]))
    n_attached = 0
    for r in rows:
        k = (r["ticker"], r["vintage"])
        if k in pmap:
            r["y_persist_half"], r["y_pre"], r["y_post"] = pmap[k]
            n_attached += 1
        else:
            r["y_persist_half"] = r["y_pre"] = r["y_post"] = None
    return panel, tg, prereg, rows, n_attached


# ─────────────────── 加法スコアの評価（変種Pと変種Tの単一実装） ───────────────────
def good_mask_bits(rs, col, side, binar):
    """1本の候補の『良い側』の bitmask。binar='median' か 'quartile'。

    quartile は **上位1/4 か 下位1/4 のどちらかだけ**を良い側にし、真ん中の半分は
    『良くない側』に入れる（＝美点として数えない）。中央値版と違い、
    良い側と悪い側が非対称になる。
    """
    n = len(rs)
    full = (1 << n) - 1
    xs = [r[col] for r in rs]
    if binar == "median":
        med = D.quantile(xs, 0.5)
        hi = 0
        for i, r in enumerate(rs):
            if r[col] >= med:
                hi |= (1 << i)
        return hi if side == "hi" else (full & ~hi)
    q25, q75 = D.quantile(xs, 0.25), D.quantile(xs, 0.75)
    g = 0
    for i, r in enumerate(rs):
        if (r[col] >= q75) if side == "hi" else (r[col] <= q25):
            g |= (1 << i)
    return g


def feats_at(rs, cols, lm, binar):
    """発見年で各候補の『良い側』と |lift| を決める。binar='median' は D.score_masks と同一。"""
    n = len(rs)
    full = (1 << n) - 1
    if binar == "median":
        return D.score_masks(rs, cols, lm)
    base = lm.bit_count() / n if n else 0
    feats = []
    for c in cols:
        best = None
        for side in ("hi", "lo"):
            g = good_mask_bits(rs, c, side, binar)
            m = g.bit_count()
            if m == 0 or m == n:
                continue
            lf = (lm & g).bit_count() / m - base
            if best is None or lf > best[1]:
                best = (side, lf, g)
        if best is None:
            continue
        feats.append({"col": c, "good": best[2], "abs_lift": abs(best[1]), "side": best[0]})
    feats.sort(key=lambda x: (-x["abs_lift"], x["col"]))
    return feats, full, base


def eval_additive_disc(U, sname, mm, disc, want_all=False, binar="median"):
    """角度D の評価。**発見年 disc と二値化 binar を引数にした以外は診断の eval_additive と同じ**。

    disc=2018・binar='median' のとき診断の `D.eval_additive` と 1件も食い違わないことを
    検算する（下の `crosscheck_with_diag`）。
    """
    cols = SUBSETS[sname]
    n_pass = 0
    hits = []
    allrec = []
    for pop in POPS:
        rsD = U[(sname, pop, disc)]
        if len(rsD) < 100:
            continue
        lmD, ndD, _ = mm[(sname, pop, disc)]
        feats, fullD, baseD = feats_at(rsD, cols, lmD, binar)
        if not feats:
            continue
        Js = sorted({j for j in tuple(JS) + (len(feats),) if 1 <= j <= len(feats)})
        per_v = {}
        for v in TRIO:
            rs = U[(sname, pop, v)]
            n = len(rs)
            full = (1 << n) - 1
            good = {ft["col"]: good_mask_bits(rs, ft["col"], ft["side"], binar) for ft in feats}
            per_v[v] = {"rs": rs, "n": n, "full": full, "good": good}
        for J in Js:
            sel = [ft["col"] for ft in feats[:J]]
            planes = {v: D.count_masks([per_v[v]["good"][c] for c in sel], J, per_v[v]["full"])
                      for v in TRIO}
            for s in range(1, J + 1):
                for mode in ("ge", "le"):
                    ok = True
                    up = None
                    rec = {}
                    fail = None
                    for v in TRIO:
                        if mode == "ge":
                            g = D.ge_mask(planes[v], s, J, per_v[v]["full"])
                        else:
                            g = per_v[v]["full"] & ~D.ge_mask(planes[v], s + 1, J, per_v[v]["full"])
                        m = g.bit_count()
                        if m < MIN_NUM or m >= per_v[v]["n"]:
                            ok = False
                            fail = fail or ("group_size", v, m)
                            break
                        lmv, ndv, kdv = mm[(sname, pop, v)]
                        k = (lmv & g).bit_count()
                        base = kdv / ndv if ndv else 0
                        lf = k / m - base
                        if up is None:
                            up = lf > 0
                        rec[v] = {"lift": r4(lf), "k": k, "m": m, "base": r4(base),
                                  "p": r4(k / m), "gmask": g}
                        if k < MIN_NUM or abs(lf) < LIFT or ((lf > 0) != up):
                            ok = False
                            fail = fail or (("min_num" if k < MIN_NUM else
                                             ("lift" if abs(lf) < LIFT else "sign")), v, None)
                            break
                    ent = {"pop": pop, "subset": sname, "disc": disc, "J": J, "s": s, "mode": mode,
                           "binar": binar,
                           "sel": sel, "sides": [ft["side"] for ft in feats[:J]],
                           "direction": ("up" if up else "down") if up is not None else None,
                           "per_v": rec, "gate1_ok": ok, "first_fail": fail}
                    if want_all:
                        allrec.append(ent)
                    if ok:
                        n_pass += 1
                        hits.append(ent)
    return n_pass, hits, allrec


def strip_masks(ent):
    """JSON へ出す前に bitmask を落とす（巨大整数を書かない）。"""
    q = {k: v for k, v in ent.items() if k != "per_v"}
    q["per_v"] = {str(v): {kk: vv for kk, vv in d.items() if kk != "gmask"}
                  for v, d in ent["per_v"].items()}
    return q


# ─────────────────── ゲート（角度A の verdict_for と同一の作法） ───────────────────
def group_tickers(U, sname, pop, v, gmask):
    rs = U[(sname, pop, v)]
    return {rs[i]["ticker"] for i in range(len(rs)) if (gmask >> i) & 1}


def mh_g(U, sname, pop, v, gset, ykey="y10"):
    """Mantel-Haenszel 重み付きリスク差。角度A の mh_risk_diff と同じ重み・同じ足切り。"""
    rs = [r for r in U[(sname, pop, v)] if r.get("sic2") and r.get(ykey) is not None]
    if len(rs) < 20:
        return None
    strata = defaultdict(lambda: [0, 0, 0, 0])
    for r in rs:
        d = strata[r["sic2"]]
        w = 1 if r[ykey] else 0
        if r["ticker"] in gset:
            d[0] += 1
            d[1] += w
        else:
            d[2] += 1
            d[3] += w
    num = den = 0.0
    used = drop = 0
    for _s, (n1, k1, n0, k0) in strata.items():
        if n1 < 3 or n0 < 3:
            drop += 1
            continue
        wgt = n1 * n0 / (n1 + n0)
        num += wgt * (k1 / n1 - k0 / n0)
        den += wgt
        used += 1
    if den == 0:
        return None
    return {"mh_risk_diff": r4(num / den), "strata_used": used, "strata_dropped": drop}


def drop_one_sector_g(U, sname, pop, v, gset, ykey="y10"):
    """業種を1つずつ抜いたときの**最悪** lift（角度A と同じ足切り: nb>=40・群>=10）。"""
    rs = [r for r in U[(sname, pop, v)] if r.get(ykey) is not None]
    secs = sorted({r.get("sic2") for r in rs if r.get("sic2")})
    worst = None
    for dr in secs:
        RR = [r for r in rs if r.get("sic2") != dr]
        nb = len(RR)
        if nb < 40:
            continue
        kb = sum(1 for r in RR if r[ykey])
        grp = [r for r in RR if r["ticker"] in gset]
        if len(grp) < 10:
            continue
        kg = sum(1 for r in grp if r[ykey])
        lf = kg / len(grp) - kb / nb
        ent = {"dropped_sector": dr, "n_group": len(grp), "k": kg, "lift": r4(lf)}
        if worst is None or abs(lf) < abs(worst["lift"]):
            worst = ent
    return worst


def irr_control_g(U, sname, pop, v, gset, score_by_ticker, ykey="y10"):
    """irr の影でないか。角度A と同じ二段（層内で差が残るか／irr と直交か）。

    ⚠ 層内は**群の定義を作り直さない**（コホート中央値で作った同じ群を層へ落とす）。
    角度A は層内で刻みを作り直すが、加法スコアで作り直すと『別のスコア』になるので、
    ここは「作った群をその層で見る」を主とし、作り直した版も併記する。
    """
    rs = [r for r in U[(sname, pop, v)] if r.get("irr") is not None and r.get(ykey) is not None]
    out = {"n_with_irr": len(rs)}
    if len(rs) < 20:
        out["status"] = "irr の読解がこのビンテージ・母集団で %d 行しかなく判定不能" % len(rs)
        out["orthogonal_hint"] = None
        out["irr_ge70"] = {"status": "判定不能"}
        return out
    rho = spearman([score_by_ticker[r["ticker"]] for r in rs], [float(r["irr"]) for r in rs])
    out["corr_score_vs_irr"] = r4(rho)
    out["orthogonal_hint"] = (None if rho is None else abs(rho) < 0.15)
    hi = [r for r in rs if r["irr"] >= 70]
    if len(hi) >= 20:
        base = sum(1 for r in hi if r[ykey]) / len(hi)
        g = [r for r in hi if r["ticker"] in gset]
        out["irr_ge70"] = {"n": len(hi), "base": r4(base), "n_group": len(g),
                           "k": sum(1 for r in g if r[ykey]),
                           "p_group": r4(rate(sum(1 for r in g if r[ykey]), len(g))),
                           "lift": (None if not g else
                                    r4(sum(1 for r in g if r[ykey]) / len(g) - base))}
    else:
        out["irr_ge70"] = {"status": "irr>=70 が %d 行で判定不能" % len(hi)}
    return out


def incremental_g(U, sname, pop, v, gset, direction, ykey="y10"):
    """増分（prereg: 既存関門で7割超が説明されるなら不合格）。角度A と同じ当て方。"""
    rs = [r for r in U[(sname, pop, v)] if r.get(ykey) is not None]
    if direction == "up":
        keep = [r for r in rs if not g_blocked(r)]
        grp_all = [r for r in rs if r["ticker"] in gset]
        g = [r for r in keep if r["ticker"] in gset]
        common = {"applied": "上向き＝既存関門を通る社だけに絞って測り直した lift",
                  "n_rows": len(rs), "n_keep": len(keep),
                  "n_group_before": len(grp_all), "n_group_after_gates": len(g),
                  "share_of_group_already_blocked":
                      r4(1 - rate(len(g), len(grp_all))) if grp_all else None}
        if len(keep) < 40:
            return {**common, "status": "既存関門を通る行が %d で判定不能" % len(keep)}
        if len(g) < 10:
            return {**common,
                    "status": "群 %d 社のうち既存関門を通るのは %d 社で、増分を測れない"
                              % (len(grp_all), len(g))}
        base = sum(1 for r in keep if r[ykey]) / len(keep)
        k = sum(1 for r in g if r[ykey])
        return {**common, "k": k, "base": r4(base), "lift": r4(k / len(g) - base)}
    fails = [r for r in rs if r["ticker"] in gset and not r[ykey]]
    caught = sum(1 for r in fails if g_blocked(r))
    return {"applied": "下向き＝群の10%未満だった社のうち既存関門で既に落ちている割合",
            "n_failures_in_group": len(fails), "already_caught": caught,
            "caught_share": r4(rate(caught, len(fails)))}


def full_gates(U, ent, score_by_ticker_v):
    """gate1（lift/分子/符号）を通った配置に、残りのゲートを当てる。"""
    sname, pop = ent["subset"], ent["pop"]
    d = ent["direction"]
    gsets = {v: group_tickers(U, sname, pop, v, ent["per_v"][v]["gmask"]) for v in TRIO}
    mh = {str(v): mh_g(U, sname, pop, v, gsets[v]) for v in TRIO}
    dos = {str(v): drop_one_sector_g(U, sname, pop, v, gsets[v]) for v in TRIO}
    sgn = 1 if d == "up" else -1
    mh_ok = all(m and m["mh_risk_diff"] is not None and abs(m["mh_risk_diff"]) >= LIFT
                and (1 if m["mh_risk_diff"] > 0 else -1) == sgn for m in mh.values())
    dos_ok = all(w and w["lift"] is not None and abs(w["lift"]) >= LIFT
                 and (1 if w["lift"] > 0 else -1) == sgn for w in dos.values())
    res = {"mh": mh, "drop_one_sector": dos, "mh_ok": mh_ok, "drop_one_sector_ok": dos_ok}
    # **判定不能と不合格を分ける**（測れなかったことを『落ちた』と書かない）
    if any(m is None for m in mh.values()) or any(w is None for w in dos.values()):
        res["verdict"] = "判定不能"
        res["gate_failed_at"] = "sector_control(測定不能)"
        res["reason"] = "業種の層が薄く MH または業種1つ抜きが算出できないビンテージがある"
        return res
    if not (mh_ok and dos_ok):
        res["verdict"] = "不合格"
        res["gate_failed_at"] = "sector_control"
        res["reason"] = ("同一 sic2 内（MH重み付きリスク差）" if not mh_ok else "業種を1つ抜く") \
            + " で 0.15 を維持できない"
        return res
    irr = {str(v): irr_control_g(U, sname, pop, v, gsets[v], score_by_ticker_v[v]) for v in (2018,)}
    e = irr["2018"]
    res["irr"] = irr
    lay = e.get("irr_ge70", {}).get("lift")
    if lay is None and not e.get("orthogonal_hint"):
        res["verdict"] = "判定不能"
        res["gate_failed_at"] = "not_irr_shadow"
        res["reason"] = "irr>=70 層が薄く層内検定ができず、かつ irr と直交とも言えない"
        return res
    if not (e.get("orthogonal_hint") is True or (lay is not None and abs(lay) >= LIFT)):
        res["verdict"] = "不合格"
        res["gate_failed_at"] = "not_irr_shadow"
        res["reason"] = "irr>=70 層内で差が消え、かつ irr と直交でもない＝irr の影"
        return res
    inc = {str(v): incremental_g(U, sname, pop, v, gsets[v], d) for v in TRIO}
    res["incremental"] = inc
    if any("status" in inc[str(v)] for v in TRIO):
        res["verdict"] = "判定不能"
        res["gate_failed_at"] = "incremental(測定不能)"
        res["reason"] = ("既存関門を通したあとに残る群が薄く、増分を測れないビンテージがある: "
                         + str({v: inc[str(v)].get("status") for v in TRIO
                                if "status" in inc[str(v)]}))
        return res
    if d == "up":
        ls = [inc[str(v)].get("lift") for v in TRIO]
        inc_ok = all(x is not None and abs(x) >= LIFT and (1 if x > 0 else -1) == sgn for x in ls)
        res["incremental_summary"] = {"lift_within_gate_passers_3v": ls, "line": LIFT}
    else:
        tot = sum(inc[str(v)].get("n_failures_in_group", 0) for v in TRIO)
        cau = sum(inc[str(v)].get("already_caught", 0) for v in TRIO)
        sh = rate(cau, tot)
        inc_ok = (sh is not None and sh <= INCREMENTAL_MAX_CAUGHT)
        res["incremental_summary"] = {"n_failures": tot, "caught": cau, "caught_share": r4(sh),
                                      "line": INCREMENTAL_MAX_CAUGHT}
    res["incremental_ok"] = inc_ok
    if not inc_ok:
        res["verdict"] = "不合格"
        res["gate_failed_at"] = "incremental"
        res["reason"] = "既存の関門で説明され、増分が無い"
        return res
    res["verdict"] = "合格"
    res["reason"] = "prereg の全条件を満たす"
    return res


# ─────────────────── スコアの表（依頼文 (b)(c)） ───────────────────
def build_scores(U, sname, pop, v, feats, binar="median"):
    """そのビンテージのコホート内の刻みで二値化し、良い側の数を数える。"""
    rs = U[(sname, pop, v)]
    n = len(rs)
    sc = [0] * n
    for ft in feats:
        g = good_mask_bits(rs, ft["col"], ft["side"], binar)
        for i in range(n):
            if (g >> i) & 1:
                sc[i] += 1
    return rs, sc


def score_table(rs, sc, ykeys):
    """スコアごとの P(目的)。目的が None の行はその目的の分母から外す（欠測を0と読まない）。"""
    by = defaultdict(lambda: {"n": 0})
    for i, r in enumerate(rs):
        d = by[sc[i]]
        d["n"] += 1
        for yk in ykeys:
            x = r.get(yk)
            e = d.setdefault(yk, {"n_def": 0, "k": 0})
            if x is None:
                continue
            e["n_def"] += 1
            if x:
                e["k"] += 1
    out = {}
    for s in sorted(by):
        d = by[s]
        e = {"n": d["n"]}
        for yk in ykeys:
            q = d.get(yk, {"n_def": 0, "k": 0})
            e[yk] = {"n_def": q["n_def"], "k": q["k"], "p": r4(rate(q["k"], q["n_def"]))}
        out[str(s)] = e
    return out


def monotone_check(tbl, yk, min_n=15):
    """単調か。分母 min_n 未満のスコアは『判定不能』として並びから外す（0と読まない）。"""
    pts = []
    for s in sorted(tbl, key=lambda x: int(x)):
        e = tbl[s][yk]
        if e["n_def"] >= min_n and e["p"] is not None:
            pts.append((int(s), e["p"], e["n_def"]))
    if len(pts) < 3:
        return {"status": "分母 %d 以上のスコアが %d 段しかなく判定不能" % (min_n, len(pts)),
                "points": pts}
    inc = all(pts[i + 1][1] >= pts[i][1] for i in range(len(pts) - 1))
    dec = all(pts[i + 1][1] <= pts[i][1] for i in range(len(pts) - 1))
    rho = spearman([p[0] for p in pts], [p[1] for p in pts])
    # 行レベルの相関（段の数ではなく社の数で見る）
    return {"points": [{"score": a, "p": r4(b), "n_def": c} for a, b, c in pts],
            "monotone_increasing": inc, "monotone_decreasing": dec,
            "spearman_over_steps": r4(rho),
            "span": r4(pts[-1][1] - pts[0][1]),
            "note": "段どうしの相関は段数（数点）でしか取れない。行レベルは下の row_spearman"}


# ─────────────────── 依頼文 (d) 内訳を分ける ───────────────────
def ablation(U, sname, pop, feats, J, s, mode, mm, binar="median"):
    """1本ずつ抜く／同じ本数の無作為部分集合／最良の単変量 と比べる。"""
    sel = [ft["col"] for ft in feats[:J]]
    side = {ft["col"]: ft["side"] for ft in feats}

    def lift_for(cols, ss, mm_):
        """指定の列集合・閾値 ss での lift（3ビンテージ）。"""
        res = {}
        for v in TRIO:
            rs = U[(sname, pop, v)]
            n = len(rs)
            full = (1 << n) - 1
            masks = [good_mask_bits(rs, c, side[c], binar) for c in cols]
            planes = D.count_masks(masks, len(cols), full)
            if mode == "ge":
                g = D.ge_mask(planes, ss, len(cols), full)
            else:
                g = full & ~D.ge_mask(planes, ss + 1, len(cols), full)
            m = g.bit_count()
            lmv, ndv, kdv = mm_[(sname, pop, v)]
            k = (lmv & g).bit_count()
            base = kdv / ndv if ndv else 0
            res[v] = {"n_group": m, "k": k, "base": r4(base),
                      "lift": (r4(k / m - base) if m else None)}
        return res

    base_res = lift_for(sel, s, mm)
    loo = []
    for c in sel:
        rest = [x for x in sel if x != c]
        # 閾値は「同じ s」と「本数に比例して丸めた s」の両方を出す（どちらか一方だと誤読する）
        s_same = min(s, len(rest))
        s_prop = max(1, min(len(rest), int(round(s * len(rest) / float(len(sel))))))
        loo.append({"dropped": c, "s_same": s_same, "s_prop": s_prop,
                    "same_s": {str(v): base_res_v for v, base_res_v in lift_for(rest, s_same, mm).items()},
                    "prop_s": {str(v): x for v, x in lift_for(rest, s_prop, mm).items()}})
    # 同じ本数の無作為部分集合（**数そのものが効いているか**）
    # ⚠ 母集団は「使える列」＝feats に載った列だけ。発見年の中央値で群が空/全部になる列
    #   （二値の列で中央値がその値になる等）は**そもそも群を作れない**ので、そこから引くと
    #   『無作為のほうが弱い』が道具の都合で出てしまう
    cols_all = [ft["col"] for ft in feats]
    rnd = random.Random(SEED + 7)
    rand = []
    seen = set()
    tries = 0
    while len(rand) < 60 and tries < 400:
        tries += 1
        pick = tuple(sorted(rnd.sample(cols_all, min(J, len(cols_all)))))
        if pick in seen:
            continue
        seen.add(pick)
        rr = lift_for(list(pick), s, mm)
        mn = min((abs(rr[v]["lift"]) if rr[v]["lift"] is not None else 0) for v in TRIO)
        sg = {(1 if (rr[v]["lift"] or 0) > 0 else -1) for v in TRIO}
        rand.append({"cols": list(pick), "min_abs_lift_3v": r4(mn),
                     "sign_stable": len(sg) == 1,
                     "per_v": {str(v): rr[v] for v in TRIO}})
    rand.sort(key=lambda x: -(x["min_abs_lift_3v"] or 0))
    sel_min = min(abs(base_res[v]["lift"]) for v in TRIO if base_res[v]["lift"] is not None)
    better = sum(1 for x in rand if (x["min_abs_lift_3v"] or 0) >= sel_min)
    # 最良の単変量（J=1・s=1 と同じ）
    singles = []
    for ft in feats:
        rr = lift_for([ft["col"]], 1, mm)
        mn = min((abs(rr[v]["lift"]) if rr[v]["lift"] is not None else 0) for v in TRIO)
        sg = {(1 if (rr[v]["lift"] or 0) > 0 else -1) for v in TRIO}
        singles.append({"col": ft["col"], "side": ft["side"], "min_abs_lift_3v": r4(mn),
                        "sign_stable": len(sg) == 1,
                        "per_v": {str(v): rr[v] for v in TRIO}})
    singles.sort(key=lambda x: -(x["min_abs_lift_3v"] or 0))
    return {
        "selected": {"cols": sel, "s": s, "mode": mode,
                     "per_v": {str(v): base_res[v] for v in TRIO},
                     "min_abs_lift_3v": r4(sel_min)},
        "leave_one_out": loo,
        "random_same_size": {
            "n_drawn": len(rand), "J": J, "s": s,
            "n_at_least_as_good_as_selected": better,
            "share": r4(rate(better, len(rand))),
            "top5": rand[:5],
            "median_min_abs_lift": r4(sorted(x["min_abs_lift_3v"] or 0 for x in rand)[len(rand) // 2]
                                      if rand else None),
            "read": "選んだ J 本と**同じ本数の無作為な J 本**が同じくらい効くなら、"
                    "効いているのは『数』であって『どの変数か』ではない。"
                    "逆にほとんど無いなら、効いているのは選択（＝過剰適合の疑い）",
        },
        "best_singles_top5": singles[:5],
        "score_vs_best_single": {
            "score_min_abs_lift_3v": r4(sel_min),
            "best_single_min_abs_lift_3v": (singles[0]["min_abs_lift_3v"] if singles else None),
            "gain": (r4(sel_min - (singles[0]["min_abs_lift_3v"] or 0)) if singles else None),
            "read": "加法スコアが最良の単変量を超えないなら、『数を数える』ことに増分は無い",
        },
    }


# ─────────────────── 配置ごとの内訳（段の表・重なり） ───────────────────
def config_detail(U, x, feats):
    """**段そのもの**（score==s）の表と、3ビンテージの群の重なり。

    ・累積（score>=s）だけを見ると下の段が薄まって『どこから効くか』が分からない
    ・3ビンテージは**同じ956ティッカー**なので、群が同じ会社ばかりなら
      『3年で維持した』は**3つの証拠ではない**。実社数と重なりを必ず数える
    """
    s, pop, bn, J, ss, mode = (x["subset"], x["pop"], x["binar"], x["J"], x["s"], x["mode"])
    steps = {}
    gsets = {}
    for v in TRIO:
        rs, sc = build_scores(U, s, pop, v, feats[:J], bn)
        n = len(rs)
        kd = sum(1 for r in rs if r["y10"])
        base = kd / n
        tbl = {}
        for lev in range(0, J + 1):
            idx = [i for i in range(n) if sc[i] == lev]
            if not idx:
                continue
            ent = {"n": len(idx)}
            for yk in ("y10", "y_pre", "y_post", "y_persist_half"):
                dn = [i for i in idx if rs[i].get(yk) is not None]
                ent[yk] = {"n_def": len(dn),
                           "k": sum(1 for i in dn if rs[i][yk]),
                           "p": r4(rate(sum(1 for i in dn if rs[i][yk]), len(dn)))}
            tbl[str(lev)] = ent
        steps[str(v)] = {"n": n, "base_y10": r4(base), "by_step": tbl}
        gsets[v] = {rs[i]["ticker"] for i in range(n)
                    if (sc[i] >= ss if mode == "ge" else sc[i] <= ss)}
    uni = set().union(*gsets.values())
    inter = set.intersection(*gsets.values())
    # 群が何でできているか（業種の構成・規模・R&Dゼロ率）
    comp = {}
    for v in TRIO:
        rs = U[(s, pop, v)]
        g = [r for r in rs if r["ticker"] in gsets[v]]
        cs = Counter(r.get("sic2") for r in g)
        ca = Counter(r.get("sic2") for r in rs)
        top = sorted(cs.items(), key=lambda kv: -kv[1])[:6]
        szg = sorted(r["size_rev"] for r in g if r.get("size_rev") is not None)
        sza = sorted(r["size_rev"] for r in rs if r.get("size_rev") is not None)
        rz_g = sum(1 for r in g if r.get("f2_rnd_r") is not None and r["f2_rnd_r"] <= 0)
        rz_a = sum(1 for r in rs if r.get("f2_rnd_r") is not None and r["f2_rnd_r"] <= 0)
        comp[str(v)] = {
            "top_sic2_in_group": [{"sic2": a, "n_group": b, "n_pop": ca.get(a, 0),
                                   "share_of_group": r4(rate(b, len(g))),
                                   "share_of_pop": r4(rate(ca.get(a, 0), len(rs)))}
                                  for a, b in top],
            "median_size_rev_group": (szg[len(szg) // 2] if szg else None),
            "median_size_rev_pop": (sza[len(sza) // 2] if sza else None),
            "rnd_zero_share_group": r4(rate(rz_g, len(g))),
            "rnd_zero_share_pop": r4(rate(rz_a, len(rs))),
        }
    return {"step_table": steps, "group_composition": comp,
            "group_overlap": {
                "n_group_by_vintage": {str(v): len(gsets[v]) for v in TRIO},
                "n_distinct_companies": len(uni),
                "n_in_all_three": len(inter),
                "share_in_all_three": r4(rate(len(inter), len(uni))),
                "read": "3ビンテージは同じ956ティッカーなので、群がほぼ同じ会社なら"
                        "『3年で維持した』は**独立な3つの証拠ではない**",
                "members_all_three": sorted(inter)[:80],
            }}


# ─────────────────── 合格した配置への攻撃 ───────────────────
def attack_pass(U, x, mm, feats):
    """**合格は攻撃してから書く**（この台帳の作法）。事前登録の外の追加検問。

    ① レジーム分割（前半/後半）——prereg の known_limits が『2018窓はAI相場。
       前期/後期で分けて必ず出す』と要求している
    ② 1社抜き（jackknife）——1社で結論が変わらないか
    ③ 単変量への還元——群が実は1本の言い換えでないか
    ④ もう一方の二値化での対応物——刻みの取り方に依存していないか
    ⑤ 群の中身（銘柄名）——名指しできない群は検算できない
    """
    s, pop, bn, J, ss, mode = (x["subset"], x["pop"], x["binar"], x["J"], x["s"], x["mode"])
    out = {"regime_split": {}, "jackknife": {}, "reduces_to_single": {}, "other_binarize": {},
           "members": {}}
    for v in TRIO:
        rs, sc = build_scores(U, s, pop, v, feats[:J], bn)
        idx = [i for i in range(len(rs)) if (sc[i] >= ss if mode == "ge" else sc[i] <= ss)]
        gset = {rs[i]["ticker"] for i in idx}
        out["members"][str(v)] = sorted(gset)
        # ① レジーム
        ent = {}
        for yk in ("y10", "y_pre", "y_post", "y_persist_half"):
            dn = [r for r in rs if r.get(yk) is not None]
            gg = [r for r in dn if r["ticker"] in gset]
            if not dn or not gg:
                ent[yk] = {"status": "定義された行が無い"}
                continue
            base = sum(1 for r in dn if r[yk]) / len(dn)
            k = sum(1 for r in gg if r[yk])
            ent[yk] = {"n_def": len(dn), "n_group": len(gg), "k": k,
                       "p_group": r4(k / len(gg)), "base": r4(base),
                       "lift": r4(k / len(gg) - base)}
        out["regime_split"][str(v)] = ent
        # ② 1社抜き（群から1社抜いたときの最悪 lift）
        m = len(idx)
        k = sum(1 for i in idx if rs[i]["y10"])
        n = len(rs)
        kd = sum(1 for r in rs if r["y10"])
        worst = None
        for i in idx:
            hit = 1 if rs[i]["y10"] else 0
            lf = (k - hit) / (m - 1) - (kd - hit) / (n - 1)
            if worst is None or abs(lf) < abs(worst[1]):
                worst = (rs[i]["ticker"], lf)
        out["jackknife"][str(v)] = {"worst_dropped": worst[0], "worst_lift": r4(worst[1]),
                                    "still_over_line": bool(abs(worst[1]) >= LIFT)}
        # ③ 単変量への還元（各構成変数の『良い側』だけの群と比べる）
        red = []
        for ft in feats[:J]:
            g1 = good_mask_bits(rs, ft["col"], ft["side"], bn)
            s1 = {rs[i]["ticker"] for i in range(len(rs)) if (g1 >> i) & 1}
            inter = len(gset & s1)
            m1 = len(s1)
            k1 = sum(1 for i in range(len(rs)) if ((g1 >> i) & 1) and rs[i]["y10"])
            red.append({"col": ft["col"], "side": ft["side"], "n_single": m1,
                        "lift_single": r4(k1 / m1 - kd / n) if m1 else None,
                        "jaccard_with_group": r4(inter / max(len(gset | s1), 1))})
        out["reduces_to_single"][str(v)] = red
    # ④ もう一方の二値化
    ob = "median" if bn == "quartile" else "quartile"
    rsD = U[(s, pop, x["disc"])]
    lmD, _n, _k = mm[(s, pop, x["disc"])]
    f2, _f, _b = feats_at(rsD, SUBSETS[s], lmD, ob)
    sel = [ft["col"] for ft in feats[:J]]
    f2sel = [ft for ft in f2 if ft["col"] in sel]
    ent = {"binarize": ob, "same_cols_found": len(f2sel) == len(sel),
           "sides": {ft["col"]: ft["side"] for ft in f2sel}, "per_v": {}}
    if len(f2sel) == len(sel):
        for v in TRIO:
            rs, sc = build_scores(U, s, pop, v, f2sel, ob)
            idx = [i for i in range(len(rs)) if (sc[i] >= ss if mode == "ge" else sc[i] <= ss)]
            n = len(rs)
            kd = sum(1 for r in rs if r["y10"])
            k = sum(1 for i in idx if rs[i]["y10"])
            ent["per_v"][str(v)] = {"n_group": len(idx), "k": k,
                                    "lift": r4(k / len(idx) - kd / n) if idx else None}
    out["other_binarize"] = ent
    return out


# ─────────────────── 単調性（傾き）の置換検定 ───────────────────
def trend_test(U, sname, pop, disc, draw, n_perm=N_PERM, seed=SEED + 21, binar="median"):
    """『スコアが上がるほど P(y10) が上がる』の傾きに、正しい帰無で p 値を付ける。

    ⚠ 向きは disc のラベルから決まる＝**置換のたびに向きも作り直す**。
      向きを固定したまま混ぜると、選択の自由度を帰無に入れ損ねて p が小さく出る。
    統計量 = **3ビンテージの行レベル Spearman の最小値**（符号は観測の向きに揃える）。
      「3ビンテージすべてで維持」という事前登録の形に合わせるため。
    """
    cols = SUBSETS[sname]
    pre = {}
    for v in TRIO:
        rs = U[(sname, pop, v)]
        n = len(rs)
        hi = {}
        for c in cols:
            gh = good_mask_bits(rs, c, "hi", binar)
            gl = good_mask_bits(rs, c, "lo", binar)
            h = [1 if (gh >> i) & 1 else 0 for i in range(n)]
            lo = [1 if (gl >> i) & 1 else 0 for i in range(n)]
            if sum(h) in (0, n) or sum(lo) in (0, n):
                continue
            hi[c] = (h, lo)
        pre[v] = {"rs": rs, "n": n, "hi": hi,
                  "tick": [r["ticker"] for r in rs]}
    usable = sorted(set(pre[TRIO[0]]["hi"]) & set(pre[TRIO[1]]["hi"]) & set(pre[TRIO[2]]["hi"]))

    def stat(labs):
        # 向きを disc で決める
        rsD = pre[disc]
        yD = [1.0 if labs[disc].get(t) else 0.0 for t in rsD["tick"]]
        nD = rsD["n"]
        baseD = sum(yD) / nD
        side = {}
        for c in usable:
            h, lo = rsD["hi"][c]
            lf_hi = sum(yD[i] for i in range(nD) if h[i]) / sum(h) - baseD
            lf_lo = sum(yD[i] for i in range(nD) if lo[i]) / sum(lo) - baseD
            side[c] = "hi" if lf_hi >= lf_lo else "lo"
        rhos = []
        for v in TRIO:
            p = pre[v]
            sc = [0] * p["n"]
            for c in usable:
                h, lo = p["hi"][c]
                arr = h if side[c] == "hi" else lo
                for i in range(p["n"]):
                    if arr[i]:
                        sc[i] += 1
            yy = [1.0 if labs[v].get(t) else 0.0 for t in p["tick"]]
            rho = spearman([float(x) for x in sc], yy)
            rhos.append(0.0 if rho is None else rho)
        return rhos

    oth = [i for i, v in enumerate(TRIO) if v != disc]

    def two_stats(rr):
        sg = 1.0 if sum(rr) >= 0 else -1.0
        return (min(sg * x for x in rr),                     # 3ビンテージ（発見年を含む＝in-sample）
                min(sg * rr[i] for i in oth) if oth else None)  # 発見年を除く＝out-of-vintage

    obs = stat(draw(shuffle=False))
    obs_all, obs_out = two_stats(obs)
    ge_all = ge_out = 0
    d_all, d_out = [], []
    for _ in range(n_perm):
        a, b = two_stats(stat(draw()))
        d_all.append(a)
        if a >= obs_all:
            ge_all += 1
        if b is not None:
            d_out.append(b)
            if b >= obs_out:
                ge_out += 1
    d_all.sort()
    d_out.sort()
    return {"n_usable_cols": len(usable),
            "observed_row_spearman_3v": {str(v): r4(obs[i]) for i, v in enumerate(TRIO)},
            "statistic_min_signed_rho_all3": r4(obs_all),
            "perm_p_one_sided_all3": r4((ge_all + 1) / (n_perm + 1)),
            "perm_null_p95_all3": r4(d_all[int(0.95 * (len(d_all) - 1))]) if d_all else None,
            "perm_null_median_all3": r4(d_all[len(d_all) // 2]) if d_all else None,
            "statistic_min_signed_rho_excl_disc": r4(obs_out) if obs_out is not None else None,
            "perm_p_one_sided_excl_disc": (r4((ge_out + 1) / (n_perm + 1)) if d_out else None),
            "perm_null_p95_excl_disc": r4(d_out[int(0.95 * (len(d_out) - 1))]) if d_out else None,
            "n_perm": n_perm,
            "def": "統計量=行レベル Spearman(スコア, y10) の最小値。"
                   "all3=3ビンテージ（**発見年を含む＝in-sample**）／"
                   "excl_disc=発見年を除く2つ（**out-of-vintage**。ただし同じ956ティッカーなので"
                   "out-of-sample ではない）。帰無は会社単位・sic2層内の置換で、"
                   "**向きの決め直しも帰無に含める**（固定したまま混ぜると選択の自由度が帰無から漏れる）"}


# ─────────────────── 偽陽性率（変種T・置換2000回） ───────────────────
def perm_fpr(U, draw, to_masks, combos, n_perm=N_PERM):
    """会社単位で全ビンテージ同時に y10 を並べ替え（sic2 層内）→ 手続き全体を回す。

    combos = [(tag, disc, binar), ...]。**同じ置換で全部の変種を評価する**ので、
    和集合（＝探索者が実際に払っている家族単位の値札）が正しく出る。
    """
    hits = {(t, s): 0 for (t, _d, _b) in combos for s in SUBSETS}
    dist = {(t, s): [] for (t, _d, _b) in combos for s in SUBSETS}
    uni_by_tag = {t: 0 for (t, _d, _b) in combos}
    uni_all = 0
    uni_median_only = 0
    for _ in range(n_perm):
        mm = to_masks(draw())
        any_all = False
        any_med = False
        for (t, disc, binar) in combos:
            any_tag = False
            for s in SUBSETS:
                n, _h, _a = eval_additive_disc(U, s, mm, disc, binar=binar)
                dist[(t, s)].append(n)
                if n > 0:
                    hits[(t, s)] += 1
                    any_tag = True
            if any_tag:
                uni_by_tag[t] += 1
                any_all = True
                if binar == "median":
                    any_med = True
        if any_all:
            uni_all += 1
        if any_med:
            uni_median_only += 1
    out = {"n_perm": n_perm, "by_variant": {}}
    for (t, _d, _b) in combos:
        ent = {}
        for s in SUBSETS:
            arr = sorted(dist[(t, s)])
            ent[s] = {"false_positive_rate": r4(hits[(t, s)] / n_perm),
                      "expected_false_passes_per_run": r4(sum(dist[(t, s)]) / n_perm),
                      "max_observed": arr[-1] if arr else 0,
                      "p95_passes": arr[int(0.95 * (len(arr) - 1))] if arr else 0}
        ent["union_of_subsets"] = r4(uni_by_tag[t] / n_perm)
        out["by_variant"][t] = ent
    out["union_of_all_variants_searched"] = r4(uni_all / n_perm)
    out["union_of_median_variants_only"] = r4(uni_median_only / n_perm)
    return out


# ─────────────────── 検出力（この角度の群の大きさで） ───────────────────
def power_for(ms, ns, base, delta, direction, n_sims=N_POWER, seed=SEED + 3):
    """観測された群の大きさ ms（3ビンテージ）で、真の lift が delta のときに
    『3ビンテージすべてで |lift|>=0.15 ∧ 分子>=20 ∧ 同符号』を通す確率。"""
    rnd = random.Random(seed)
    p1 = base + delta if direction == "up" else base - delta
    if p1 <= 0 or p1 >= 1:
        return None
    ok = 0
    for _ in range(n_sims):
        good = True
        for m, n in zip(ms, ns):
            p0 = (base * n - p1 * m) / max(n - m, 1)
            if p0 < 0 or p0 > 1:
                good = False
                break
            k = sum(1 for _i in range(m) if rnd.random() < p1)
            k0 = sum(1 for _i in range(n - m) if rnd.random() < p0)
            b = (k + k0) / n
            lf = k / m - b
            if k < MIN_NUM or abs(lf) < LIFT or ((lf > 0) != (direction == "up")):
                good = False
                break
        if good:
            ok += 1
    return r4(ok / n_sims)


# ─────────────────── main ───────────────────
def main():
    panel, tg, prereg, rows, n_persist = load_rows()
    U = D.build_universes(rows)
    draw, to_masks, perm_info = D.perm_engine(rows, U, SEED)
    mm_real = to_masks(draw(shuffle=False))

    out = {
        "generated": "2026-08-12",
        "tool": "night/hist10_angleD.py",
        "prereg": "out/hist10_prereg.json",
        "angle": "D — 美点の数（加法スコア）。関数形が新しい（単変量でも2本の積でもない）",
        "purpose": "個々では lift 0.15 に届かない弱い信号が、数を数えると効くか。"
                   "判定・採点・台帳には一切触れない（読むだけの調査）",
        "sources": {
            "out/hist_wd_panel.json": panel.get("generated"),
            "out/hist10_targets.json": tg.get("generated"),
            "out/hist10_prereg.json": prereg.get("generated"),
            "night/hist10_diag.py": "原始関数を import（score_masks/count_masks/ge_mask/"
                                    "build_universes/perm_engine/quantile）",
            "night/hist10_angleB.py": "B2 の持続ラベル `_ypersist` を import（%d 行に付いた）" % n_persist,
        },
        "pass_line": {"lift": LIFT, "min_numerator": MIN_NUM,
                      "incremental_max_caught": INCREMENTAL_MAX_CAUGHT,
                      "sign_vintages": TRIO,
                      "src": "out/hist10_prereg.json（新しい定数を作っていない）"},
        "design_fixed_before_results": {
            "subsets": {k: v for k, v in SUBSETS.items()},
            "pops": POPS,
            "pop_excluded": "P_moat は 2016/2017 に irr の読解が無く n=61-63＝分子>=20 に"
                            "構造的に届かない（診断の到達可能性）＝判定不能",
            "binarize": "中央値（主・診断の偽陽性率がこちらで測られている）／上下1/4（副）",
            "cut_basis": "**各ビンテージのコホート内中央値**。絶対値を持ち越さない"
                         "（2016年の中央値を2018年に当てると暦の水準を測ってしまう＝基準の違う二つを割る型）",
            "J": list(JS) + ["全本数"],
            "s": "1..J、群は score>=s（ge）と score<=s（le）の両方",
            "discovery_variants": {
                "P": "発見年=2018（**診断と同一**。診断の real_data_pass_count と突合せできる）",
                "T": "発見年=2016（依頼文の指定。向きも閾値も2016で決めて2017/2018へ当てる）",
            },
        },
    }

    # ── 検算①: 変種P が診断の eval_additive と 1件も食い違わないか ──
    cross = {}
    for s in SUBSETS:
        n_mine, hits_mine, _ = eval_additive_disc(U, s, mm_real, 2018)
        n_diag, hits_diag = D.eval_additive(U, s, mm_real)
        key_mine = sorted((h["pop"], h["J"], h["s"], h["mode"], h["direction"]) for h in hits_mine)
        key_diag = sorted((h["pop"], h["J"], h["s"], h["mode"], h["direction"]) for h in hits_diag)
        cross[s] = {"n_pass_mine": n_mine, "n_pass_diag": n_diag,
                    "hits_identical": key_mine == key_diag,
                    "diag_recorded_real_data_pass_count":
                        (json.load(open(os.path.join(OUT, "hist10_diag.json"), encoding="utf-8"))
                         ["false_positive"]["angle_D_additive_score"]["by_subset"][s]
                         ["real_data_pass_count"]),
                    }
    out["crosscheck_with_diag"] = {
        "why": "同じ台帳を見る二つの検査器が違うことを言ってはいけない（v9.9.65）。"
               "変種P は診断の eval_additive と**同じ手続き**なので、通る配置の集合まで一致するはず",
        "by_subset": cross,
        "all_match": all(c["hits_identical"] and c["n_pass_mine"] == c["n_pass_diag"]
                         and c["n_pass_mine"] == c["diag_recorded_real_data_pass_count"]
                         for c in cross.values()),
    }

    # ── 母集団・基準率・被覆 ──
    uni = {}
    for s in SUBSETS:
        for pop in POPS:
            for v in TRIO:
                rs = U[(s, pop, v)]
                allrs = [r for r in D.pop_rows(rows, v, pop) if r.get("y10") is not None]
                k = sum(1 for r in rs if r["y10"])
                uni["%s/%s/%d" % (s, pop, v)] = {
                    "n_complete_case": len(rs), "n_pop": len(allrs),
                    "share": r4(rate(len(rs), len(allrs))),
                    "base_complete_case": r4(rate(k, len(rs))),
                    "base_pop": r4(rate(sum(1 for r in allrs if r["y10"]), len(allrs))),
                }
    out["universes"] = uni

    # ── 到達可能性（両方向）: 加法スコアの群は score の分布で決まるので、実際に作れる群で測る ──
    reach = {}
    for s in SUBSETS:
        for pop in POPS:
            rsD = U[(s, pop, 2018)]
            lmD, ndD, _ = mm_real[(s, pop, 2018)]
            feats, _f, _b = D.score_masks(rsD, SUBSETS[s], lmD)
            for v in TRIO:
                rs, sc = build_scores(U, s, pop, v, feats)
                n = len(rs)
                base = rate(sum(1 for r in rs if r["y10"]), n)
                cnt = Counter(sc)
                # ge/le それぞれで作れる群の大きさ
                sizes_ge = {}
                acc = 0
                for x in sorted(cnt, reverse=True):
                    acc += cnt[x]
                    sizes_ge[x] = acc
                up_ok = any(m >= MIN_NUM / max(base + LIFT, 1e-9) and m < n
                            for m in sizes_ge.values())
                dn_ok = any(m >= MIN_NUM / max(base - LIFT, 1e-9) and m < n
                            for m in sizes_ge.values() if base - LIFT > 0)
                reach["%s/%s/%d" % (s, pop, v)] = {
                    "n": n, "base": r4(base),
                    "min_group_for_up": int(math.ceil(MIN_NUM / (base + LIFT))) if base + LIFT > 0 else None,
                    "min_group_for_down": (int(math.ceil(MIN_NUM / (base - LIFT)))
                                           if base - LIFT > 0 else None),
                    "largest_group_available": max(sizes_ge.values()) if sizes_ge else 0,
                    "up_possible": bool(up_ok), "down_possible": bool(dn_ok),
                    "why_down_is_hard": "下向きは『群の率が base−0.15 以下』なのに"
                                        "**その群の中に事象が20社要る**ので、群は最低 "
                                        "20/(base−0.15) 社ないと効果がどれだけ強くても通らない",
                }
    out["reachability_two_way"] = reach

    # ── 実効要求倍率（MIN_NUM が LIFT より強く縛っていないか） ──
    eff = {}
    for k, c in reach.items():
        if c["base"] is None:
            continue
        need_up = c["min_group_for_up"]
        # 実際に作れる最小の群（>=MIN_NUM）で、分子>=20 を満たすのに要る率
        eff[k] = {"registered_lift": LIFT,
                  "min_group_for_up": need_up,
                  "largest_group_available": c["largest_group_available"],
                  "min_num_binding_up": bool(need_up is not None
                                             and need_up > MIN_NUM)}
    out["effective_requirement"] = {
        "why": "v2 では MIN_NUM が LIFT より強く縛るセルがあり、登録した線より高い線が"
               "こっそり課されていた。加法スコアでも同じことが起きていないかを結果の前に数える",
        "by_cell": eff,
        "note": "加法スコアの群は score の分布で決まるので、単変量のように"
                "『群の大きさを自由に選ぶ』ことができない。**刻みが飛ぶ**のがこの角度の特徴",
    }

    # ── 本体: 変種P と変種T ──
    variants = {}
    all_hits = []
    for tag, disc, binar in (("P_disc2018_median", 2018, "median"),
                             ("T_disc2016_median", 2016, "median"),
                             ("P_disc2018_quartile", 2018, "quartile"),
                             ("T_disc2016_quartile", 2016, "quartile")):
        vres = {"discovery_vintage": disc, "binarize": binar, "by_subset": {}}
        for s in SUBSETS:
            n, hits, allrec = eval_additive_disc(U, s, mm_real, disc, want_all=True, binar=binar)
            for h in hits:
                h["_variant"] = tag
            all_hits.extend(hits)
            # gate1 で落ちた理由の内訳
            why = Counter()
            for a in allrec:
                if not a["gate1_ok"]:
                    why[a["first_fail"][0] if a["first_fail"] else "unknown"] += 1
            vres["by_subset"][s] = {
                "n_configs_tried": len(allrec),
                "n_pass_gate1": n,
                "gate1_failure_reasons": dict(why),
                "hits": [strip_masks(h) for h in hits],
            }
        variants[tag] = vres
    out["gate1_lift_minnum_sign"] = variants

    # ── 通った配置に残りのゲートを当てる ──
    verdicts = []
    for h in all_hits:
        s, pop, bn = h["subset"], h["pop"], h["binar"]
        rsD = U[(s, pop, h["disc"])]
        lmD, _n, _k = mm_real[(s, pop, h["disc"])]
        feats, _f, _b = feats_at(rsD, SUBSETS[s], lmD, bn)
        sbt = {}
        for v in TRIO:
            rs, sc = build_scores(U, s, pop, v, feats[:h["J"]], bn)
            sbt[v] = {rs[i]["ticker"]: sc[i] for i in range(len(rs))}
        g = full_gates(U, h, sbt)
        verdicts.append({**strip_masks(h), **g, "detail": config_detail(U, h, feats)})
    out["verdicts"] = verdicts
    passes = [x for x in verdicts if x.get("verdict") == "合格"]
    out["n_pass_all_gates"] = len(passes)
    out["passes"] = passes
    # 合格した配置は必ず攻撃してから書く
    atk = {}
    for x in passes:
        s, pop, bn = x["subset"], x["pop"], x["binar"]
        rsD = U[(s, pop, x["disc"])]
        lmD, _n, _k = mm_real[(s, pop, x["disc"])]
        feats, _f, _b = feats_at(rsD, SUBSETS[s], lmD, bn)
        key = "%s|%s|%s|%s|J%d|s%d|%s" % (x["_variant"], s, pop, bn, x["J"], x["s"], x["mode"])
        atk[key] = attack_pass(U, x, mm_real, feats)
    out["attacks_on_passes"] = {
        "why": "**合格は攻撃してから書く**。レジーム分割は prereg の known_limits が"
               "『2018窓はAI相場。前期/後期で分けて必ず出す』と要求している",
        "cells": atk,
    }
    out["verdict_breakdown"] = dict(Counter(
        "%s|%s" % (x.get("verdict"), x.get("gate_failed_at") or "-") for x in verdicts))
    # 惜しさ（どのゲートにどれだけ足りなかったか）
    near = []
    for x in verdicts:
        if x.get("verdict") == "合格":
            continue
        ent = {"key": "%s|%s|%s|%s|J%d|s%d|%s" % (x["_variant"], x["subset"], x["pop"],
                                                  x["binar"], x["J"], x["s"], x["mode"]),
               "verdict": x.get("verdict"), "failed_at": x.get("gate_failed_at"),
               "lift_3v": {k: v["lift"] for k, v in x["per_v"].items()}}
        if x.get("gate_failed_at") == "sector_control":
            ent["mh_min_abs"] = r4(min(abs((v or {}).get("mh_risk_diff") or 0)
                                       for v in x["mh"].values()))
            ent["dos_min_abs"] = r4(min(abs((v or {}).get("lift") or 0)
                                        for v in x["drop_one_sector"].values()))
            ent["gap_to_line"] = r4(LIFT - min(ent["mh_min_abs"], ent["dos_min_abs"]))
        near.append(ent)
    near.sort(key=lambda e: (e.get("gap_to_line") if e.get("gap_to_line") is not None else 9))
    out["near_misses"] = near

    # ── 依頼文 (b)(c): スコアごとの P(y10)/P(y_persist)/P(y_biz)・単調性・閾値 ──
    tables = {}
    for s in SUBSETS:
        for pop in POPS:
            for disc in (2016, 2018):
              for bn in ("median", "quartile"):
                rsD = U[(s, pop, disc)]
                lmD, _n, _k = mm_real[(s, pop, disc)]
                feats, _f, _b = feats_at(rsD, SUBSETS[s], lmD, bn)
                key = "%s/%s/disc%d/%s" % (s, pop, disc, bn)
                ent = {"J_all": len(feats), "binarize": bn,
                       "features_in_order": [{"col": ft["col"], "side": ft["side"],
                                              "abs_lift_at_disc": r4(ft["abs_lift"])}
                                             for ft in feats],
                       "by_vintage": {}}
                for v in TRIO:
                    rs, sc = build_scores(U, s, pop, v, feats, bn)
                    tbl = score_table(rs, sc, ["y10", "y_persist_half", "y_biz"])
                    rowsp = spearman([float(x) for x in sc],
                                     [1.0 if rs[i]["y10"] else 0.0 for i in range(len(rs))])
                    ent["by_vintage"][str(v)] = {
                        "n": len(rs),
                        "base_y10": r4(rate(sum(1 for r in rs if r["y10"]), len(rs))),
                        "table": tbl,
                        "row_spearman_score_vs_y10": r4(rowsp),
                        "monotone_y10": monotone_check(tbl, "y10"),
                        "monotone_y_persist": monotone_check(tbl, "y_persist_half"),
                        "monotone_y_biz": monotone_check(tbl, "y_biz"),
                    }
                tables[key] = ent
    out["score_tables"] = tables

    # ── 前提の確認: 単変量は本当に線に届かないのか（加法スコアが超えるべき土台） ──
    singles = {}
    for s in SUBSETS:
        for pop in POPS:
            for bn in ("median", "quartile"):
                rs16 = U[(s, pop, 2016)]
                lm16, _n, _k = mm_real[(s, pop, 2016)]
                feats, _f, _b = feats_at(rs16, SUBSETS[s], lm16, bn)
                tab = []
                for ft in feats:
                    per = {}
                    for v in TRIO:
                        rs = U[(s, pop, v)]
                        n = len(rs)
                        kd = sum(1 for r in rs if r["y10"])
                        g = good_mask_bits(rs, ft["col"], ft["side"], bn)
                        m = g.bit_count()
                        k = sum(1 for i in range(n) if ((g >> i) & 1) and rs[i]["y10"])
                        per[v] = {"n_group": m, "k": k,
                                  "lift": r4(k / m - kd / n) if m else None}
                    lifts = [per[v]["lift"] for v in TRIO]
                    sg = {(1 if (x or 0) > 0 else -1) for x in lifts}
                    tab.append({"col": ft["col"], "side": ft["side"],
                                "min_abs_lift_3v": r4(min(abs(x or 0) for x in lifts)),
                                "sign_stable": len(sg) == 1,
                                "min_k_3v": min(per[v]["k"] for v in TRIO),
                                "per_v": {str(v): per[v] for v in TRIO}})
                tab.sort(key=lambda x: -(x["min_abs_lift_3v"] or 0))
                singles["%s/%s/%s" % (s, pop, bn)] = {
                    "n_candidates": len(tab),
                    "max_min_abs_lift_3v": (tab[0]["min_abs_lift_3v"] if tab else None),
                    "n_reaching_line": sum(1 for x in tab
                                           if (x["min_abs_lift_3v"] or 0) >= LIFT
                                           and x["sign_stable"] and x["min_k_3v"] >= MIN_NUM),
                    "top5": tab[:5],
                }
    out["single_variable_baseline"] = {
        "why": "依頼文の前提『個々では lift 0.15 に届かない弱い信号』が、この母集団・この二値化で"
               "本当に成り立っているかを先に確かめる。**加法スコアはこの土台を超えて初めて意味がある**",
        "cells": singles,
    }

    # ── (c) 何点から効くか（線を跨ぐ最小のスコア） ──
    onset = {}
    for key, ent in tables.items():
        per = {}
        for v in TRIO:
            b = ent["by_vintage"][str(v)]
            base = b["base_y10"]
            first = None
            for sstr in sorted(b["table"], key=lambda x: int(x)):
                e = b["table"][sstr]["y10"]
                if e["n_def"] >= MIN_NUM and e["p"] is not None and e["p"] - base >= LIFT:
                    first = int(sstr)
                    break
            per[str(v)] = {"first_score_over_line": first, "base": base}
        vals = [per[str(v)]["first_score_over_line"] for v in TRIO]
        onset[key] = {"per_vintage": per,
                      "same_score_in_all3": (len(set(vals)) == 1 and vals[0] is not None),
                      "note": "『スコアがちょうど s の段』が base+0.15 を超える最小の s。"
                              "分母 %d 未満の段は判定不能として飛ばす（0と読まない）" % MIN_NUM}
    out["where_does_it_start"] = {
        "why": "依頼文の『何点から効くか』。**段そのもの**（score==s）で見る。"
               "score>=s の累積で見ると下の段が薄まって見えるため",
        "cells": onset,
    }

    # ── (c) 閾値を2016で決めて2017/2018で検証 ──
    thr = {}
    for s in SUBSETS:
      for pop in POPS:
        for bn in ("median", "quartile"):
            rs16 = U[(s, pop, 2016)]
            lm16, _n, _k = mm_real[(s, pop, 2016)]
            feats, _f, _b = feats_at(rs16, SUBSETS[s], lm16, bn)
            Js = sorted({j for j in tuple(JS) + (len(feats),) if 1 <= j <= len(feats)})
            for J in Js:
                for mode in ("ge", "le"):
                    best = None
                    per = {}
                    for ss in range(1, J + 1):
                        rr = {}
                        for v in TRIO:
                            rs, sc = build_scores(U, s, pop, v, feats[:J], bn)
                            grp = [i for i in range(len(rs))
                                   if (sc[i] >= ss if mode == "ge" else sc[i] <= ss)]
                            m = len(grp)
                            if m == 0 or m == len(rs):
                                rr[v] = None
                                continue
                            k = sum(1 for i in grp if rs[i]["y10"])
                            base = rate(sum(1 for r in rs if r["y10"]), len(rs))
                            rr[v] = {"n_group": m, "k": k, "p": r4(rate(k, m)),
                                     "base": r4(base), "lift": r4(k / m - base)}
                        per[ss] = rr
                        c16 = rr.get(2016)
                        if c16 and c16["k"] >= MIN_NUM:
                            if best is None or abs(c16["lift"]) > abs(per[best][2016]["lift"]):
                                best = ss
                    if best is None:
                        continue
                    b16 = per[best][2016]
                    d16 = 1 if b16["lift"] > 0 else -1
                    held = []
                    for v in (2017, 2018):
                        c = per[best].get(v)
                        held.append(bool(c and c["k"] >= MIN_NUM and abs(c["lift"]) >= LIFT
                                         and (1 if c["lift"] > 0 else -1) == d16))
                    thr["%s/%s/%s/J%d/%s" % (s, pop, bn, J, mode)] = {
                        "s_chosen_at_2016": best,
                        "lift_2016": b16["lift"], "k_2016": b16["k"], "m_2016": b16["n_group"],
                        "verify_2017": per[best].get(2017),
                        "verify_2018": per[best].get(2018),
                        "held_2017": held[0], "held_2018": held[1],
                        "held_both": held[0] and held[1],
                    }
    out["threshold_chosen_at_2016"] = {
        "procedure": "2016 で |lift| が最大になる s（分子>=20）を選び、2017/2018 で"
                     "『同符号 ∧ |lift|>=0.15 ∧ 分子>=20』が保たれるかを見る",
        "⚠": "2016/2017/2018 は**同じ956ティッカー**なので、これは out-of-sample ではなく"
             "**out-of-vintage**（同じ会社の別の入口・後半の窓は大きく重なる）",
        "cells": thr,
        "n_cells": len(thr),
        "n_held_both": sum(1 for x in thr.values() if x["held_both"]),
    }

    # ── (d) 内訳: 1本抜き／無作為な同数／最良の単変量 ──
    abl = {}
    targets_for_abl = []
    if all_hits:
        # gate1 を通った配置すべて
        targets_for_abl = all_hits[:]
    else:
        # 一つも通らなかったときは「2016で最も惜しい配置」を当てる（作業リストとして意味がある）
        for s in SUBSETS:
            for pop in POPS:
                rs16 = U[(s, pop, 2016)]
                lm16, _n, _k = mm_real[(s, pop, 2016)]
                feats, _f, _b = feats_at(rs16, SUBSETS[s], lm16, "median")
                key = "%s/%s/median/J%d/ge" % (s, pop, len(feats))
                cand = thr.get(key)
                if cand:
                    targets_for_abl.append({"subset": s, "pop": pop, "J": len(feats),
                                            "s": cand["s_chosen_at_2016"], "mode": "ge",
                                            "disc": 2016, "binar": "median",
                                            "_variant": "near_miss_2016"})
    for h in targets_for_abl:
        s, pop, bn = h["subset"], h["pop"], h.get("binar", "median")
        rsD = U[(s, pop, h["disc"])]
        lmD, _n, _k = mm_real[(s, pop, h["disc"])]
        feats, _f, _b = feats_at(rsD, SUBSETS[s], lmD, bn)
        key = "%s|%s|%s|disc%d|J%d|s%d|%s" % (s, pop, bn, h["disc"], h["J"], h["s"], h["mode"])
        abl[key] = ablation(U, s, pop, feats, h["J"], h["s"], h["mode"], mm_real, bn)
    out["ablation"] = {
        "why": "『どの変数が効いているのか』と『数そのものが効いているのか』を分ける。"
               "加法スコアは変数の選択に自由度があるので、選択が効いているだけなら過剰適合",
        "cells": abl,
    }

    # ── スコアが何の代理か（規模・収益性・irr との相関） ──
    proxy = {}
    for s in SUBSETS:
        for pop in POPS:
            rs18 = U[(s, pop, 2018)]
            lm18, _n, _k = mm_real[(s, pop, 2018)]
            feats, _f, _b = D.score_masks(rs18, SUBSETS[s], lm18)
            rs, sc = build_scores(U, s, pop, 2018, feats)
            ent = {}
            for nm, key in (("size_rev", "size_rev"), ("f2_opm", "f2_opm"),
                            ("f2_cagr5", "f2_cagr5"), ("irr", "irr")):
                pairs = [(sc[i], rs[i].get(key)) for i in range(len(rs)) if rs[i].get(key) is not None]
                if len(pairs) >= 20:
                    ent[nm] = {"n": len(pairs),
                               "spearman": r4(spearman([float(a) for a, _ in pairs],
                                                       [float(b) for _, b in pairs]))}
                else:
                    ent[nm] = {"n": len(pairs), "spearman": None,
                               "status": "行が %d で判定不能" % len(pairs)}
            proxy["%s/%s/2018" % (s, pop)] = ent
    out["what_is_the_score_a_proxy_for"] = {
        "why": "14〜20本の『美点』が全部おなじ一つのもの（規模・収益性・irr）の言い換えなら、"
               "加法スコアは新しい関数形ではなくその一つの変数の粗い測り方にすぎない",
        "cells": proxy,
    }

    # ── 単調性（傾き）の置換検定 ──
    trend = {}
    for s in SUBSETS:
        for pop in POPS:
            for disc in (2016, 2018):
                for bn in ("median", "quartile"):
                    trend["%s/%s/disc%d/%s" % (s, pop, disc, bn)] = \
                        trend_test(U, s, pop, disc, draw, binar=bn)
    out["trend_permutation_test"] = {
        "why": "スコアの表を目で見て『単調そう』と言うのは測定ではない。"
               "**向きの決め直しまで帰無に含めた**置換で傾きに p 値を付ける",
        "cells": trend,
    }

    # ── どの業種が lift を作っているか（sector_control で落ちる配置の内訳） ──
    sect = {}
    for x in verdicts:
        if x.get("gate_failed_at") not in ("sector_control",):
            continue
        key = "%s|%s|%s|%s|J%d|s%d|%s" % (x["_variant"], x["subset"], x["pop"],
                                          x["binar"], x["J"], x["s"], x["mode"])
        sect[key] = {
            "raw_lift_3v": {k: v["lift"] for k, v in x["per_v"].items()},
            "mh_3v": {k: (v or {}).get("mh_risk_diff") for k, v in x["mh"].items()},
            "worst_sector_3v": {k: {"dropped": (v or {}).get("dropped_sector"),
                                    "lift": (v or {}).get("lift")}
                                for k, v in x["drop_one_sector"].items()},
            "shrink_raw_to_mh": {k: r4((x["per_v"][k]["lift"] or 0)
                                       - ((v or {}).get("mh_risk_diff") or 0))
                                 for k, v in x["mh"].items()},
        }
    out["sector_attribution"] = {
        "why": "同一 sic2 内（MH）で lift が縮むなら、その差は**業種間の差**であって"
               "会社の差ではない。どの業種を抜くと消えるかも名指しする",
        "cells": sect,
    }

    # ── 検出力（実際に作れた群の大きさで） ──
    pw = {}
    for s in SUBSETS:
        for pop in POPS:
            rs18 = U[(s, pop, 2018)]
            lm18, _n, _k = mm_real[(s, pop, 2018)]
            feats, _f, _b = D.score_masks(rs18, SUBSETS[s], lm18)
            J = len(feats)
            # 代表として「中央付近の s」＝群がだいたい半分になる閾値
            ms, ns, bases = [], [], []
            for v in TRIO:
                rs, sc = build_scores(U, s, pop, v, feats)
                n = len(rs)
                target = n / 2.0
                bestm, bests = None, None
                for ss in range(1, J + 1):
                    m = sum(1 for x in sc if x >= ss)
                    if bestm is None or abs(m - target) < abs(bestm - target):
                        bestm, bests = m, ss
                ms.append(bestm)
                ns.append(n)
                bases.append(rate(sum(1 for r in rs if r["y10"]), n))
            base = sum(bases) / len(bases)
            ent = {"group_sizes_3v": ms, "n_3v": ns, "base_mean": r4(base),
                   "power_by_delta": {}}
            for dd in (0.10, 0.15, 0.20):
                for dirn in ("up", "down"):
                    ent["power_by_delta"]["%s/%.2f" % (dirn, dd)] = power_for(ms, ns, base, dd, dirn)
            pw["%s/%s" % (s, pop)] = ent
    out["power"] = {
        "model": "実際に作れた群の大きさ（score>=s で半分に近い s）で、真の lift が δ のとき"
                 "『3ビンテージすべてで |lift|>=0.15 ∧ 分子>=20 ∧ 同符号』を通す確率。MC %d 回" % N_POWER,
        "⚠δ=0.15 で約0.5 になるのは構造": "真の効果が登録した線とちょうど等しいとき標本分布は"
                                     "線の上下に半分ずつ割れる。設計の差は δ≠0.15 に出る",
        "cells": pw,
    }

    # ── 偽陽性率（変種T を自前で。変種P は診断の値と突合せ） ──
    combos = [("P_disc2018_median", 2018, "median"), ("T_disc2016_median", 2016, "median"),
              ("P_disc2018_quartile", 2018, "quartile"), ("T_disc2016_quartile", 2016, "quartile")]
    fpr = perm_fpr(U, draw, to_masks, combos, n_perm=N_PERM)
    diagj = json.load(open(os.path.join(OUT, "hist10_diag.json"), encoding="utf-8"))
    fpr_P_diag = diagj["false_positive"]["angle_D_additive_score"]
    out["false_positive_rate"] = {
        "permutation_scheme": "y10 を**会社単位で全ビンテージ同時に**（結果ベクトルを丸ごと）"
                              "sic2 の層内で並べ替える。群の定義（特徴量）は不変＝"
                              "帰無は『候補は結果と無関係』。ビンテージ内で独立に混ぜると従属が壊れ、"
                              "v2 の実測で 33倍の過小評価になった",
        "perm_info": perm_info,
        "measured_here": fpr,
        "variant_P_disc2018_median_from_diag": {
            "by_subset": {k: v["false_positive_rate"] for k, v in fpr_P_diag["by_subset"].items()},
            "union_of_subsets": fpr_P_diag["false_positive_rate_union_of_subsets"],
            "src": "out/hist10_diag.json（結果を見る前に固定した事前診断）",
        },
        "note_on_quartile": "**上下1/4 版は事前診断が値札を付けていない**（診断は中央値版だけを"
                            "測っている）。依頼文が『中央値または上下1/4』と書いているので走らせたが、"
                            "**探索空間を広げた分は事前登録の外**として自前で値札を測ってある",
        "read": "**雑音でも約半分の確率で『gate1 合格』が1つ出る**手続き。"
                "したがって gate1 を通っただけの配置には証拠としての価値がほとんど無い。"
                "残りのゲート（業種・irr層・増分）が本体である",
    }

    # ── 陽性対照（注入検査）: 本物があれば掴めるか ──
    inj = {}
    rnd = random.Random(SEED + 11)
    for s in ("cov90_14",):
        for pop in ("P_full",):
            rs18 = U[(s, pop, 2018)]
            lm18, _n, _k = mm_real[(s, pop, 2018)]
            feats, _f, _b = D.score_masks(rs18, SUBSETS[s], lm18)
            for delta in (0.20, 0.30):
                labs = {}
                for v in TRIO:
                    rs, sc = build_scores(U, s, pop, v, feats)
                    n = len(rs)
                    base = rate(sum(1 for r in rs if r["y10"]), n)
                    J = len(feats)
                    target = n / 2.0
                    bs = min(range(1, J + 1),
                             key=lambda ss: abs(sum(1 for x in sc if x >= ss) - target))
                    m = sum(1 for x in sc if x >= bs)
                    p1 = min(0.99, base + delta)
                    p0 = max(0.01, (base * n - p1 * m) / max(n - m, 1))
                    cur = {}
                    for i, r in enumerate(rs):
                        cur[r["ticker"]] = (rnd.random() < (p1 if sc[i] >= bs else p0))
                    labs[v] = cur
                mm_inj = {}
                for key, rr in U.items():
                    vv = key[2]
                    lmk = 0
                    nd = kd = 0
                    for i, r in enumerate(rr):
                        x = labs[vv].get(r["ticker"])
                        if x is None:
                            continue
                        nd += 1
                        if x:
                            lmk |= (1 << i)
                            kd += 1
                    mm_inj[key] = (lmk, nd, kd)
                nT, hT, _ = eval_additive_disc(U, s, mm_inj, 2016)
                nP, hP, _ = eval_additive_disc(U, s, mm_inj, 2018)
                inj["%s/%s/delta%.2f" % (s, pop, delta)] = {
                    "n_pass_variant_T": nT, "n_pass_variant_P": nP,
                    "detected": nT > 0 or nP > 0,
                    "def": "スコア上位半分だけ真の lift=%.2f を注入して y10 を作り直す" % delta,
                }
    out["positive_control_injection"] = {
        "why": "**強い結論ほど先に道具を疑う**。本物を入れて掴めることを確かめてから"
               "『合格ゼロ』と書く",
        "cells": inj,
        "all_detected": all(x["detected"] for x in inj.values()) if inj else None,
    }

    # ── 検算②: bitmask の評価が素朴な再計算と一致するか ──
    naive = {"checked": 0, "mismatch": 0, "examples": []}
    for h in all_hits[:40] or []:
        s, pop, bn = h["subset"], h["pop"], h["binar"]
        rsD = U[(s, pop, h["disc"])]
        lmD, _n, _k = mm_real[(s, pop, h["disc"])]
        feats, _f, _b = feats_at(rsD, SUBSETS[s], lmD, bn)
        for v in TRIO:
            rs, sc = build_scores(U, s, pop, v, feats[:h["J"]], bn)
            grp = [i for i in range(len(rs))
                   if (sc[i] >= h["s"] if h["mode"] == "ge" else sc[i] <= h["s"])]
            k = sum(1 for i in grp if rs[i]["y10"])
            naive["checked"] += 1
            if len(grp) != h["per_v"][v]["m"] or k != h["per_v"][v]["k"]:
                naive["mismatch"] += 1
                naive["examples"].append({"cell": "%s/%s/%d" % (s, pop, v),
                                          "bitset": [h["per_v"][v]["m"], h["per_v"][v]["k"]],
                                          "naive": [len(grp), k]})
    out["self_check_bitset_vs_naive"] = naive

    # ── 判定 ──
    out["verdict"] = {
        "n_pass_gate1": {t: {s: variants[t]["by_subset"][s]["n_pass_gate1"] for s in SUBSETS}
                         for t in variants},
        "n_pass_all_gates": len(passes),
        "line": "prereg の全条件（lift>=0.15 ∧ 分子>=20 ∧ 3ビンテージ符号不変 ∧ 業種調整 ∧ "
                "irr層 ∧ 増分）",
        "stopping_rule": "合格ゼロならゼロと書く。線を緩めて通さない",
    }

    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ── 画面 ──
    print("角度D（加法スコア）——出力 %s" % DEST)
    print("検算: 変種P vs 診断 = %s" % out["crosscheck_with_diag"]["all_match"])
    for t in variants:
        for s in SUBSETS:
            print("  gate1 %s/%s: %d 件 / 試した配置 %d"
                  % (t, s, variants[t]["by_subset"][s]["n_pass_gate1"],
                     variants[t]["by_subset"][s]["n_configs_tried"]))
    print("全ゲート合格: %d 件" % len(passes))
    print("偽陽性率 変種T: %s（和集合）/ 変種P(診断): %s"
          % (fpr["union_of_median_variants_only"],
             fpr_P_diag["false_positive_rate_union_of_subsets"]))
    print("偽陽性率 実際に探索した4変種の和集合: %s" % fpr["union_of_all_variants_searched"])
    print("注入検査（本物を入れたら掴めるか）: %s" % out["positive_control_injection"]["all_detected"])
    print("bitset vs 素朴: checked=%d mismatch=%d" % (naive["checked"], naive["mismatch"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
