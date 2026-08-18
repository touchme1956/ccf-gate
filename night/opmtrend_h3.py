#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H3（利益率の水準との交互作用）——**高い利益率から下がる**のと低い利益率から下がるのは違うか。

事前登録 out/opm_trend_prereg.json の H3_level_interaction:
    split : opm の中央値で二分し、その中で opmD5<0 の lift を測る
    line  : H1 と同じ線 ＝ lift >= 0.15 かつ **8ビンテージすべてで符号が同じ**
    lift  : P(前方年率>=15% | opmD5>=0) - P(... | opmD5<0)
            ＝ **正なら「利益率が下がっている社のほうが悪い」**（向きをここで固定する）

★この器は判定しか持たない。データの結合・単位・到達可能性・十分位の切り方は
  night/opmtrend_base.py の load_base() と night/opmtrend_h1.py の小道具を**読むだけ**で、
  一行も再実装しない（v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」）。

★値・規約・採点式・刻み・重み・関門・売却規律・配分は1バイトも触らない。
  書くのは out/opmtrend_h3.json だけ。

★合否に使うのは**事前登録どおり中央値二分だけ**。
  十分位・交互作用の差・相対低下・業種/規模の統制は**記述**であって、そこから線を引かない
  （結果を見てから線を引けば curve-fitting になる）。出力にも `preregistered: false` と刻む。

★線の読み方を結果の前に3通り出す（後から都合のよい読みを選ばないため。H1 と同一）:
   (i) 厳格 : 8ビンテージすべてで lift>=0.15
   (ii) プール: 全ビンテージの行を束ねた lift>=0.15
   (iii) 中央値: 8つの lift の中央値>=0.15
  符号の一致は (i)(ii)(iii) と独立に課す。

★0件は測定ではないことがある。プール・群・十分位が0/極小なら名指しで警告し判定から外す。
"""
import json, os, random, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "out")
sys.path.insert(0, HERE)

from opmtrend_base import load_base, VINTAGES, HURDLE, IMPAIR  # noqa: E402
from opmtrend_h1 import share, med, r4, spearman               # noqa: E402  再実装しない

LINE_LIFT = 0.15   # 事前登録 H1_selector / H3_level_interaction の線。ここで動かさない
MIN_ARM = 20       # 群の下限。**H1 が使った数字をそのまま継ぐ**（H3 のために作っていない）
N_PERM = 2000
N_POWER = 2000
SEED = 20260818

LEVELS = ("high", "low")


def hit(r):
    return r["tr_cagr"] >= HURDLE


def imp(r):
    return r["tr_cagr"] <= IMPAIR


def pick(rows_all, y, pool):
    """そのビンテージ・そのプールで **opm と opmD5 が両方ある**行。

    H3 は水準で切ってからトレンドで切るので、**どちらかが欠けた行は最初から使えない**。
    落とした数は必ず記録する（測れなかった行と、測って落ちた行を混ぜない）。
    """
    vr = [r for r in rows_all if r["vintage"] == y]
    sel = [r for r in vr if pool == "all" or (r["qual"] and not r["qual_na"])]
    use = [r for r in sel if r["opmD5"] is not None and r["opm"] is not None]
    return sel, use


def split_level(use):
    """opm の中央値で二分。**ビンテージ×プールの中で**切る。

    ★束ねてから切ってはいけない——ビンテージごとに基礎率が 19.7〜33.1% と違う
      （窓の長さが 4.08〜13.09年で違うため）ので、一括で切ると
      『どのビンテージが多く入ったか』が『高マージンか』に化ける。
    ★プールの中で切るのも必須——質実証プールは opm>=10% で定義されているので、
      そこでの「低マージン」は絶対水準では低くない（10〜17%）。解釈で必ず断る。
    """
    if not use:
        return None, [], []
    m = st.median(r["opm"] for r in use)
    high = [r for r in use if r["opm"] > m]
    low = [r for r in use if r["opm"] <= m]
    return m, high, low


def arms(rows):
    """トレンドで二分。A=非負（opmD5>=0） / B=負（opmD5<0）。"""
    A = [r for r in rows if r["opmD5"] >= 0]
    B = [r for r in rows if r["opmD5"] < 0]
    return A, B


def cw_weights(rows):
    """★社単位の重み。行は『社×ビンテージ』なので、同じ社が最大8回数えられる。

    のべ件数で割ると、**何度も現れる社が分布の両端を太らせる**
    （既記録: irr=85 の『のべ38件＝実28社』と同型）。
    各社の重みの合計を1にすると、社が1票ずつになる。
    ★腕ごとに重みを作る——ある年は下落・ある年は非下落だった社は、
      両方の腕に1票ずつ入れるのが正直（実際に両方の状態を経験している）。
    """
    cnt = {}
    for r in rows:
        cnt[r["ticker"]] = cnt.get(r["ticker"], 0) + 1
    return {t: 1.0 / c for t, c in cnt.items()}


def wshare(rows, pred):
    if not rows:
        return None
    w = cw_weights(rows)
    den = sum(w[r["ticker"]] for r in rows)
    return (sum(w[r["ticker"]] for r in rows if pred(r)) / den) if den else None


def ncomp(rows):
    return len({r["ticker"] for r in rows})


def cell_stats(rows):
    A, B = arms(rows)
    pA, pB = share(A, hit), share(B, hit)
    return {
        "n": len(rows), "n_nonneg": len(A), "n_neg": len(B),
        "share_neg": r4(len(B) / len(rows)) if rows else None,
        "base_hit": r4(share(rows, hit)),
        "p_hit_nonneg": r4(pA), "p_hit_neg": r4(pB),
        "lift": r4(pA - pB) if (pA is not None and pB is not None) else None,
        "med_tr_nonneg": r4(med([r["tr_cagr"] for r in A])),
        "med_tr_neg": r4(med([r["tr_cagr"] for r in B])),
        "p_impair_nonneg": r4(share(A, imp)), "p_impair_neg": r4(share(B, imp)),
        "med_opm_pct": r4(med([r["opm"] for r in rows])),
        # ---- 社単位（疑似反復を外した版）----
        "n_companies": ncomp(rows),
        "n_companies_nonneg": ncomp(A), "n_companies_neg": ncomp(B),
        "cw_p_hit_nonneg": r4(wshare(A, hit)), "cw_p_hit_neg": r4(wshare(B, hit)),
        "cw_lift": (r4(wshare(A, hit) - wshare(B, hit))
                    if (A and B) else None),
        "cw_p_impair_neg": r4(wshare(B, imp)),
    }


# ================= 本体 =================
def build():
    base = load_base()
    rows_all = base["rows"]
    vmeta = base["vintage_meta"]
    reach = base["reachability"]
    warns = []
    checks = {}

    # ---- 自己検算 0: 土台と同じ母集団を見ているか ----
    pm = {}
    for y in VINTAGES:
        for pool in ("all", "qual"):
            sel, use = pick(rows_all, y, pool)
            want = reach[f"{y}/{pool}"]["n"]
            pm[f"{y}/{pool}"] = {"pool_mine": len(sel), "pool_base": want,
                                 "same": len(sel) == want,
                                 "usable_both_cols": len(use),
                                 "dropped_missing": len(sel) - len(use)}
            if len(sel) != want:
                warns.append(f"★{y}/{pool}: 母集団が土台と食い違う"
                             f"（自分 {len(sel)} / 土台 {want}）——照合の失敗を疑うこと")
    checks["pool_matches_base"] = pm
    checks["pool_all_match"] = all(v["same"] for v in pm.values())

    # ---- 自己検算 1: 単位（この台帳は opm を2度取り違えている） ----
    opm_pct = [r["opm"] for r in rows_all if r["opm"] is not None]
    d5 = [r["opmD5"] for r in rows_all if r["opmD5"] is not None]
    u = {"opm_pct_median": r4(med(opm_pct)),
         "opm_pct_p01": r4(sorted(opm_pct)[int(len(opm_pct) * .01)]),
         "opm_pct_p99": r4(sorted(opm_pct)[int(len(opm_pct) * .99)]),
         "opmD5_median_abs": r4(med([abs(x) for x in d5])),
         "opm_looks_percent": 1.0 < med(opm_pct) < 100.0,
         "opmD5_looks_ratio": med([abs(x) for x in d5]) < 1.0}
    checks["unit"] = u
    if not u["opm_looks_percent"]:
        warns.append("★opm(%)の中央値が 1〜100 の外——帯検問が効いていない疑い")
    if not u["opmD5_looks_ratio"]:
        warns.append("★opmD5 の中央値|x|が 1.0 以上——%pt が混ざっている疑い")
    # 上位十分位を汚しうる極端値（名指ししておく）
    ext = [{"vintage": r["vintage"], "ticker": r["ticker"], "opm_pct": r["opm"],
            "rev": r["rev"], "qual": r["qual"]}
           for r in rows_all if r["opm"] is not None and r["opm"] > 100]
    checks["opm_over_100pct_rows"] = {"n": len(ext), "rows": ext,
                                      "note": "上位十分位に入りうる。1社抜きの反証で効きを測る"}

    # ---- 自己検算 2: 中央値の位置と群のバランス ----
    sp = {}
    for y in VINTAGES:
        for pool in ("all", "qual"):
            _, use = pick(rows_all, y, pool)
            m, hi, lo = split_level(use)
            bal = (min(len(hi), len(lo)) / max(len(hi), len(lo))) if (hi and lo) else None
            sp[f"{y}/{pool}"] = {"opm_median_pct": r4(m), "n_high": len(hi), "n_low": len(lo),
                                 "balance": r4(bal)}
            if bal is not None and bal < 0.9:
                warns.append(f"{y}/{pool}: 中央値二分の偏り {bal:.2f}——同値が多い疑い")
            if not use:
                warns.append(f"★{y}/{pool}: 使える行が0——単位・欄名・照合の失敗を疑うこと")
    checks["split_medians"] = sp

    # ---- 自己検算 3: 水準とトレンドは独立ではない（H3 の解釈の土台） ----
    #   opm は opmD5 の**終点**なので、低い水準は「下がった結果」でもある＝機械的に従属する。
    #   交互作用はこの従属の上で測っている、と必ず断る。
    dep = {}
    for pool in ("all", "qual"):
        rows = []
        for y in VINTAGES:
            _, use = pick(rows_all, y, pool)
            rows += use
        dep[pool] = {
            "n": len(rows),
            "spearman_opm_vs_opmD5": r4(spearman([r["opm"] for r in rows],
                                                 [r["opmD5"] for r in rows])),
            "share_neg_high": None, "share_neg_low": None,
        }
        H, L = [], []
        for y in VINTAGES:
            _, use = pick(rows_all, y, pool)
            m, hi, lo = split_level(use)
            H += hi; L += lo
        dep[pool]["share_neg_high"] = r4(share(H, lambda r: r["opmD5"] < 0))
        dep[pool]["share_neg_low"] = r4(share(L, lambda r: r["opmD5"] < 0))
        dep[pool]["note"] = ("ρ>0＝高マージンほど**上がって**いる。素朴な平均回帰の予想と逆。"
                             "opm は opmD5 の終点なので機械的に従属する")
    checks["level_trend_dependency"] = dep

    # ---- H3 本体（事前登録） ----
    per = []
    for y in VINTAGES:
        vm = vmeta[str(y)]
        for pool in ("all", "qual"):
            _, use = pick(rows_all, y, pool)
            m, hi, lo = split_level(use)
            for lv, g in (("high", hi), ("low", lo)):
                rec = {"vintage": y, "pool": pool, "level": lv,
                       "opm_median_pct": r4(m)}
                rec.update(cell_stats(g))
                if not g:
                    rec["usable"], rec["why_not"] = False, "群が0社——照合の失敗を疑うこと"
                    warns.append(f"★{y}/{pool}/{lv}: 群が0社")
                elif rec["n_nonneg"] < MIN_ARM or rec["n_neg"] < MIN_ARM:
                    rec["usable"] = False
                    rec["why_not"] = (f"腕が薄い（非負{rec['n_nonneg']}/負{rec['n_neg']}"
                                      f"・下限{MIN_ARM}）")
                    warns.append(f"{y}/{pool}/{lv}: 腕が薄い"
                                 f"（非負{rec['n_nonneg']}/負{rec['n_neg']}）——判定から外す")
                else:
                    rec["usable"], rec["why_not"] = True, None
                per.append(rec)

    # ---- 線に照らす（3通りの読み・符号の一致） ----
    summary = {}
    for pool in ("all", "qual"):
        for lv in LEVELS:
            cells = [c for c in per if c["pool"] == pool and c["level"] == lv]
            ok = [c for c in cells if c["usable"]]
            lifts = [c["lift"] for c in ok]
            pos = sum(1 for v in lifts if v > 0)
            neg = sum(1 for v in lifts if v < 0)
            same_sign = (len(ok) == len(cells) and len(ok) > 0 and
                         (pos == len(ok) or neg == len(ok)))
            # プール読み
            allrows = []
            for y in VINTAGES:
                _, use = pick(rows_all, y, pool)
                m, hi, lo = split_level(use)
                allrows += (hi if lv == "high" else lo)
            A, B = arms(allrows)
            pooled = (share(A, hit) - share(B, hit)) if (A and B) else None
            cw_pooled = (wshare(A, hit) - wshare(B, hit)) if (A and B) else None
            reads = {
                "i_strict_all_vintages_ge_line": (len(ok) == len(cells) and len(ok) > 0 and
                                                  all(v >= LINE_LIFT for v in lifts)),
                "ii_pooled_ge_line": (pooled is not None and pooled >= LINE_LIFT),
                "iii_median_ge_line": (bool(lifts) and st.median(lifts) >= LINE_LIFT),
            }
            if len(ok) == 0:
                verdict = "判定不能"
            elif same_sign and any(reads.values()):
                verdict = "合格"
            else:
                verdict = "不合格"
            summary[f"{pool}/{lv}"] = {
                "cells": len(cells), "usable_cells": len(ok),
                "lifts_by_vintage": {str(c["vintage"]): c["lift"] for c in cells},
                "lifts": lifts,
                "n_lift_ge_line": sum(1 for v in lifts if v >= LINE_LIFT),
                "sign_pos": pos, "sign_neg": neg,
                "all_same_sign": same_sign,
                "pooled_lift": r4(pooled),
                "pooled_n": len(allrows),
                "pooled_n_companies": ncomp(allrows),
                "cw_pooled_lift": r4(cw_pooled),
                "cw_note": ("cw_ ＝ 社単位（各社の重みの合計を1にした版）。"
                            "行は社×ビンテージなので、のべで読むと何度も現れる社が両端を太らせる"),
                "median_lift": r4(st.median(lifts)) if lifts else None,
                "min_lift": r4(min(lifts)) if lifts else None,
                "max_lift": r4(max(lifts)) if lifts else None,
                "readings": reads,
                "verdict": verdict,
                "why": (None if verdict == "合格" else
                        ("使えるセルが無い" if verdict == "判定不能" else
                         "符号が8ビンテージで揃わない、または lift がどの読み方でも線 %.2f に届かない"
                         % LINE_LIFT)),
            }
    return base, rows_all, vmeta, per, summary, warns, checks


# ================= 交互作用（記述・事前登録の合否には使わない） =================
def interaction(per, rows_all):
    out = {"preregistered": False,
           "what": "lift(high) - lift(low)。**正なら『高マージンから下がるほうが悪い』**",
           "why_not_verdict": ("事前登録の線は『二分した中での lift>=0.15 と符号の一致』であって、"
                               "差そのものに線は登録されていない。ここで線を作れば "
                               "結果を見てから線を引くことになる"),
           "pools": {}}
    for pool in ("all", "qual"):
        rows = []
        for y in VINTAGES:
            h = next(c for c in per if c["pool"] == pool and c["level"] == "high"
                     and c["vintage"] == y)
            l = next(c for c in per if c["pool"] == pool and c["level"] == "low"
                     and c["vintage"] == y)
            d = (None if (h["lift"] is None or l["lift"] is None or
                          not (h["usable"] and l["usable"]))
                 else round(h["lift"] - l["lift"], 4))
            rows.append({"vintage": y, "lift_high": h["lift"], "lift_low": l["lift"],
                         "diff": d, "usable": bool(h["usable"] and l["usable"])})
        ds = [r["diff"] for r in rows if r["diff"] is not None]
        out["pools"][pool] = {
            "by_vintage": rows,
            "n_usable": len(ds),
            "median_diff": r4(st.median(ds)) if ds else None,
            "min_diff": r4(min(ds)) if ds else None, "max_diff": r4(max(ds)) if ds else None,
            "sign_pos": sum(1 for v in ds if v > 0), "sign_neg": sum(1 for v in ds if v < 0),
            "all_same_sign": (bool(ds) and (all(v > 0 for v in ds) or all(v < 0 for v in ds))),
        }
    return out


# ================= 十分位（記述） =================
def deciles(rows_all):
    """★ビンテージ内で opm の十分位に切ってから束ねる（H1 の deciles と同じ作法）。

    束ねてから切ると『どのビンテージが多く入ったか』が中身に化ける。
    D10 ＝ V が居る場所（V の opm は 52〜66%）。
    """
    out = {"preregistered": False,
           "method": "ビンテージ内で opm の十分位に切ってから束ねる（基礎率の差を相殺）",
           "pools": {}}
    for pool in ("all", "qual"):
        buckets = {i: [] for i in range(1, 11)}
        skipped = {}
        for y in VINTAGES:
            _, use = pick(rows_all, y, pool)
            use = sorted(use, key=lambda r: (r["opm"], r["ticker"]))
            n = len(use)
            if n < 30:
                skipped[str(y)] = f"n={n}（<30）——十分位に切れない"
                continue
            for i, r in enumerate(use):
                dec = min(10, int(i * 10 / n) + 1)
                r2 = dict(r); r2["_dec"] = dec
                buckets[dec].append(r2)
        tab = []
        for dcl in range(1, 11):
            g = buckets[dcl]
            s = cell_stats(g)
            tab.append({"decile": dcl,
                        "opm_lo_pct": r4(min(r["opm"] for r in g)) if g else None,
                        "opm_hi_pct": r4(max(r["opm"] for r in g)) if g else None, **s})
        ok = [t for t in tab if t["n"] and t["n_nonneg"] >= MIN_ARM and t["n_neg"] >= MIN_ARM]
        out["pools"][pool] = {
            "table": tab,
            "skipped_vintages": skipped,
            "usable_deciles": [t["decile"] for t in ok],
            "spearman_dec_vs_share_neg": r4(spearman([t["decile"] for t in tab],
                                                     [t["share_neg"] for t in tab])),
            "spearman_dec_vs_lift": r4(spearman([t["decile"] for t in ok],
                                                [t["lift"] for t in ok])) if len(ok) >= 3 else None,
            "spearman_dec_vs_phit_neg": r4(spearman([t["decile"] for t in ok],
                                                    [t["p_hit_neg"] for t in ok]))
                                        if len(ok) >= 3 else None,
            "lift_D10": next((t["lift"] for t in tab if t["decile"] == 10), None),
            "lift_D1": next((t["lift"] for t in tab if t["decile"] == 1), None),
        }
    return out


# ================= V の問い（記述） =================
def v_question(rows_all, per):
    """『高マージンの中で opmD5<0 は何を意味するか』を、V の居る帯で見る。

    ★opm>=40/50% の切り方は**事前登録に無い**（結果を見た後の帯）。合否には使わない。
      V の実測 opm は 52〜66% なので、D10 だけでは V の帯を代表できないため併記する。
    """
    out = {"preregistered": False,
           "V_actual": [{"vintage": r["vintage"], "opm_pct": r["opm"], "opmD5": r["opmD5"],
                         "tr_cagr": r["tr_cagr"], "qual": r["qual"]}
                        for r in rows_all if r["ticker"] == "V"],
           "cuts": {}, "decliners_high_vs_low": {}, "names_in_top_band": {}}

    # (1) 絶対の帯（事後の切り方と明記）
    for pool in ("all", "qual"):
        for name, lo in (("opm_ge_30", 30.0), ("opm_ge_40", 40.0), ("opm_ge_50", 50.0)):
            rows = []
            for y in VINTAGES:
                _, use = pick(rows_all, y, pool)
                rows += [r for r in use if r["opm"] >= lo]
            s = cell_stats(rows)
            s["usable"] = bool(s["n_nonneg"] >= MIN_ARM and s["n_neg"] >= MIN_ARM)
            out["cuts"][f"{pool}/{name}"] = s

    # (2) 「下がっている社」の中で、高マージンと低マージンを比べる
    #     ＝事前登録の split の中の別の対比（新しい変数を作っていない）
    for pool in ("all", "qual"):
        H = []
        L = []
        for y in VINTAGES:
            _, use = pick(rows_all, y, pool)
            m, hi, lo = split_level(use)
            H += [r for r in hi if r["opmD5"] < 0]
            L += [r for r in lo if r["opmD5"] < 0]
        out["decliners_high_vs_low"][pool] = {
            "n_high_decliners": len(H), "n_low_decliners": len(L),
            "p_hit_high": r4(share(H, hit)), "p_hit_low": r4(share(L, hit)),
            "diff_hit": r4(share(H, hit) - share(L, hit)) if (H and L) else None,
            "med_tr_high": r4(med([r["tr_cagr"] for r in H])),
            "med_tr_low": r4(med([r["tr_cagr"] for r in L])),
            "p_impair_high": r4(share(H, imp)), "p_impair_low": r4(share(L, imp)),
        }

    # (3) 名前を出す（人が検算できるように）——★社単位で。のべで並べると
    #     何度も現れる社が両端を埋めて「たくさんの証拠」に見える
    for pool in ("qual", "all"):
        for lo in (40.0, 50.0):
            rows = []
            for y in VINTAGES:
                _, use = pick(rows_all, y, pool)
                rows += [r for r in use if r["opm"] >= lo and r["opmD5"] < 0]
            byt = {}
            for r in rows:
                byt.setdefault(r["ticker"], []).append(r)
            comp = []
            for t, g in byt.items():
                comp.append({"t": t, "times": len(g),
                             "opm_lo": r4(min(x["opm"] for x in g)),
                             "opm_hi": r4(max(x["opm"] for x in g)),
                             "mean_tr": r4(st.mean([x["tr_cagr"] for x in g])),
                             "hits": sum(1 for x in g if hit(x)),
                             "sic2": g[0].get("sic2"), "sicDesc": g[0].get("sicDesc")})
            comp.sort(key=lambda c: -c["mean_tr"])
            sicn = {}
            for c in comp:
                k = f'{c["sic2"]} {c["sicDesc"]}'
                sicn[k] = sicn.get(k, 0) + 1
            out["names_in_top_band"][f"{pool}/opm_ge_{int(lo)}"] = {
                "cut": f"opm>={int(lo)}% ∧ opmD5<0（★事後の帯・記述。合否に使わない）",
                "n_rows": len(rows), "n_companies": len(byt),
                "p_hit_rows": r4(share(rows, hit)),
                "p_hit_companies": r4(st.mean([c["hits"] / c["times"] for c in comp]))
                                   if comp else None,
                "n_companies_with_any_hit": sum(1 for c in comp if c["hits"] > 0),
                "n_companies_impaired": sum(1 for c in comp if c["mean_tr"] <= IMPAIR),
                "worst_company_mean_tr": r4(min(c["mean_tr"] for c in comp)) if comp else None,
                "sector_counts_companies": dict(sorted(sicn.items(), key=lambda kv: -kv[1])),
                "companies": comp,
            }
    return out


# ================= 反証（記述） =================
def adversarial(rows_all, per, summary):
    """(a)業種 (b)規模 (c)1業種抜き (d)極端値1社抜き。

    ★事前登録は『合格した仮説は必ず反証にかける』と書いている。
      不合格でも、**なぜ不合格なのか（信号が無いのか、統制で消えたのか）**を分けるために回す。
    """
    out = {"preregistered": "反証の枠組みは事前登録済み。個々の切り方は記述",
           "sector_relative_split": {}, "size_control": {},
           "leave_one_sector_out": {}, "leave_one_extreme_out": {}}

    # (a) 業種内で「高マージン」を定義し直す（高マージン＝業種のラベルではないか）
    for pool in ("all", "qual"):
        H, L = [], []
        nosic = 0
        for y in VINTAGES:
            _, use = pick(rows_all, y, pool)
            bysic = {}
            for r in use:
                s = r.get("sic2")
                if not s:
                    nosic += 1
                    continue
                bysic.setdefault(s, []).append(r)
            for s, g in bysic.items():
                if len(g) < 6:      # 業種内の中央値が意味を持たない大きさは使わない
                    continue
                m = st.median(x["opm"] for x in g)
                H += [x for x in g if x["opm"] > m]
                L += [x for x in g if x["opm"] <= m]
        def lf(rows):
            A, B = arms(rows)
            return (r4(share(A, hit) - share(B, hit)) if (A and B) else None,
                    len(A), len(B))
        lh, nAh, nBh = lf(H)
        ll, nAl, nBl = lf(L)
        out["sector_relative_split"][pool] = {
            "note": "SIC2 の中で opm の中央値二分（業種の水準差を外す）。業種内 n<6 は除外",
            "n_high": len(H), "n_low": len(L), "rows_without_sic2": nosic,
            "pooled_lift_high": lh, "pooled_lift_low": ll,
            "arms_high": [nAh, nBh], "arms_low": [nAl, nBl],
            "diff": r4(lh - ll) if (lh is not None and ll is not None) else None,
        }

    # (b) 規模の統制（高マージン群を売上の中央値で二分）
    for pool in ("all", "qual"):
        res = {}
        for lv in LEVELS:
            big, small = [], []
            for y in VINTAGES:
                _, use = pick(rows_all, y, pool)
                m, hi, lo = split_level(use)
                g = [r for r in (hi if lv == "high" else lo) if r.get("rev")]
                if len(g) < 10:
                    continue
                rm = st.median(r["rev"] for r in g)
                big += [r for r in g if r["rev"] > rm]
                small += [r for r in g if r["rev"] <= rm]
            def lf(rows):
                A, B = arms(rows)
                return r4(share(A, hit) - share(B, hit)) if (A and B) else None
            res[lv] = {"n_big": len(big), "n_small": len(small),
                       "pooled_lift_big": lf(big), "pooled_lift_small": lf(small)}
        out["size_control"][pool] = res

    # (c) 1業種抜き（プール読みの lift がどれだけ動くか）
    for pool in ("all", "qual"):
        res = {}
        for lv in LEVELS:
            rows = []
            for y in VINTAGES:
                _, use = pick(rows_all, y, pool)
                m, hi, lo = split_level(use)
                rows += (hi if lv == "high" else lo)
            sics = sorted({r.get("sic2") for r in rows if r.get("sic2")})
            vals = []
            for s in sics:
                sub = [r for r in rows if r.get("sic2") != s]
                A, B = arms(sub)
                if A and B:
                    vals.append((s, round(share(A, hit) - share(B, hit), 4)))
            if vals:
                vals.sort(key=lambda t: t[1])
                res[lv] = {"n_sectors": len(vals),
                           "min": vals[0], "max": vals[-1],
                           "median": round(st.median([v for _, v in vals]), 4)}
        out["leave_one_sector_out"][pool] = res

    # (d) 極端値（opm>100%）を全部抜く
    for pool in ("all", "qual"):
        res = {}
        for lv in LEVELS:
            rows = []
            for y in VINTAGES:
                _, use = pick(rows_all, y, pool)
                m, hi, lo = split_level(use)
                rows += (hi if lv == "high" else lo)
            sub = [r for r in rows if not (r["opm"] is not None and r["opm"] > 100)]
            A, B = arms(sub)
            res[lv] = {"n_before": len(rows), "n_after": len(sub),
                       "pooled_lift_after": r4(share(A, hit) - share(B, hit)) if (A and B) else None}
        out["leave_one_extreme_out"][pool] = res
    return out


# ================= 検出力 =================
def power(per, pool, lv, rng):
    """真の lift が◯なら、この手続きは何回に1回 合格を出すか。

    ★『不合格』の意味を定めるために要る。H1 と同じ形（腕の大きさだけ H3 のセルに替える）。
    """
    cells = [c for c in per if c["pool"] == pool and c["level"] == lv and c["usable"]]
    if not cells:
        return None
    res = {}
    for true_lift in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        passes = 0
        for _ in range(N_POWER):
            lifts = []
            for c in cells:
                nA, nB, p = c["n_nonneg"], c["n_neg"], c["base_hit"]
                pB = p - true_lift * nA / (nA + nB)
                pA = pB + true_lift
                pA, pB = min(max(pA, 0.0), 1.0), min(max(pB, 0.0), 1.0)
                hA = sum(1 for _ in range(nA) if rng.random() < pA)
                hB = sum(1 for _ in range(nB) if rng.random() < pB)
                lifts.append(hA / nA - hB / nB)
            same = all(v > 0 for v in lifts) or all(v < 0 for v in lifts)
            reads = all(v >= LINE_LIFT for v in lifts) or st.median(lifts) >= LINE_LIFT
            if same and reads:
                passes += 1
        res[f"{true_lift:.2f}"] = round(passes / N_POWER, 4)
    return res


# ================= 置換（会社単位・全ビンテージ同時） =================
def permutation(rows_all, per, pool, rng):
    """★ビンテージ内で独立に混ぜると従属が壊れ偽陽性率を桁で過小評価する（既記録）。

    会社単位の**一つの**並べ替えを全ビンテージへ同時に当てる。
    高/低の両方と、交互作用の差を同じ帰無で裁く。
    """
    data = {}
    for y in VINTAGES:
        _, use = pick(rows_all, y, pool)
        m, hi, lo = split_level(use)
        d = {}
        for lv, g in (("high", hi), ("low", lo)):
            g = sorted(g, key=lambda r: r["ticker"])
            d[lv] = {"tick": [r["ticker"] for r in g],
                     "neg": [r["opmD5"] < 0 for r in g],
                     "hit": [hit(r) for r in g]}
        data[y] = d
    usable_y = {lv: [c["vintage"] for c in per
                     if c["pool"] == pool and c["level"] == lv and c["usable"]]
                for lv in LEVELS}
    universe = sorted({t for y in VINTAGES for lv in LEVELS for t in data[y][lv]["tick"]})

    def lifts_for(lv, rank):
        out = []
        for y in usable_y[lv]:
            d = data[y][lv]
            n = len(d["tick"])
            idx = sorted(range(n), key=lambda i: rank[d["tick"][i]])
            hits = [d["hit"][i] for i in idx]
            nA = sum(1 for v in d["neg"] if not v)
            nB = n - nA
            hA = sum(1 for v, h in zip(d["neg"], hits) if not v and h)
            hB = sum(1 for v, h in zip(d["neg"], hits) if v and h)
            out.append(hA / nA - hB / nB)
        return out

    passes = {lv: 0 for lv in LEVELS}
    null_med = {lv: [] for lv in LEVELS}
    null_diff = []
    for _ in range(N_PERM):
        order = universe[:]
        rng.shuffle(order)
        rank = {t: i for i, t in enumerate(order)}
        ls = {}
        for lv in LEVELS:
            ls[lv] = lifts_for(lv, rank)
            if ls[lv]:
                null_med[lv].append(st.median(ls[lv]))
                same = all(v > 0 for v in ls[lv]) or all(v < 0 for v in ls[lv])
                if same and (all(v >= LINE_LIFT for v in ls[lv]) or
                             st.median(ls[lv]) >= LINE_LIFT):
                    passes[lv] += 1
        ys = [y for y in usable_y["high"] if y in usable_y["low"]]
        if ys:
            hi = {y: v for y, v in zip(usable_y["high"], ls["high"])}
            lo = {y: v for y, v in zip(usable_y["low"], ls["low"])}
            null_diff.append(st.median([hi[y] - lo[y] for y in ys]))

    res = {"n_perm": N_PERM, "note": "会社単位の一つの並べ替えを全ビンテージ・高低へ同時に当てる"}
    for lv in LEVELS:
        cells = [c for c in per if c["pool"] == pool and c["level"] == lv and c["usable"]]
        if not cells or not null_med[lv]:
            res[lv] = None
            continue
        obs = st.median([c["lift"] for c in cells])
        nm = sorted(null_med[lv])
        res[lv] = {
            "false_positive_rate": round(passes[lv] / N_PERM, 4),
            "null_median_lift_p50": r4(nm[len(nm) // 2]),
            "null_median_lift_p95": r4(nm[int(len(nm) * .95)]),
            "observed_median_lift": r4(obs),
            "p_value_median_lift": round((sum(1 for v in nm if v >= obs) + 1) / (len(nm) + 1), 4),
        }
    if null_diff:
        ys = [y for y in usable_y["high"] if y in usable_y["low"]]
        oh = {c["vintage"]: c["lift"] for c in per
              if c["pool"] == pool and c["level"] == "high" and c["usable"]}
        ol = {c["vintage"]: c["lift"] for c in per
              if c["pool"] == pool and c["level"] == "low" and c["usable"]}
        obsd = st.median([oh[y] - ol[y] for y in ys])
        nd = sorted(null_diff)
        res["interaction_diff"] = {
            "observed_median_diff": r4(obsd),
            "null_p50": r4(nd[len(nd) // 2]),
            "null_p05": r4(nd[int(len(nd) * .05)]), "null_p95": r4(nd[int(len(nd) * .95)]),
            "p_two_sided": round((sum(1 for v in nd if abs(v) >= abs(obsd)) + 1) / (len(nd) + 1), 4),
            "note": "差そのものには事前登録の線が無い。ここは記述であって合否ではない",
        }
    return res


def pseudo_replication(rows_all):
    """★のべ件数と実社数は違う。どれだけ違うかを名指しで出す。

    行は『社×ビンテージ』で、同じ社が最大8回入る。
    のべで割った比率は、何度も現れる社に引っぱられる（既記録の irr=85 と同型）。
    """
    out = {"preregistered": False,
           "what": "同じ社が何回数えられているか。のべ読みと社単位読みの差",
           "pools": {}}
    for pool in ("all", "qual"):
        rows = []
        for y in VINTAGES:
            _, use = pick(rows_all, y, pool)
            rows += use
        cnt = {}
        for r in rows:
            cnt[r["ticker"]] = cnt.get(r["ticker"], 0) + 1
        hist = {}
        for c in cnt.values():
            hist[c] = hist.get(c, 0) + 1
        out["pools"][pool] = {
            "n_rows": len(rows), "n_companies": len(cnt),
            "rows_per_company_mean": r4(len(rows) / len(cnt)) if cnt else None,
            "appearances_histogram": {str(k): hist[k] for k in sorted(hist)},
            "max_appearances": max(cnt.values()) if cnt else None,
        }
    return out


# ================= 出力 =================
def main():
    base, rows_all, vmeta, per, summary, warns, checks = build()
    inter = interaction(per, rows_all)
    dec = deciles(rows_all)
    vq = v_question(rows_all, per)
    pr = pseudo_replication(rows_all)
    adv = adversarial(rows_all, per, summary)
    pw = {f"{p}/{lv}": power(per, p, lv, random.Random(SEED + 1))
          for p in ("all", "qual") for lv in LEVELS}
    pm = {p: permutation(rows_all, per, p, random.Random(SEED + 2)) for p in ("all", "qual")}

    verdict = {
        "line_from_prereg": "lift >= 0.15 かつ 8ビンテージすべてで符号が同じ（H1 と同じ線）",
        "line_value": LINE_LIFT,
        "split_from_prereg": "opm の中央値で二分（ビンテージ×プールの中で切る）",
        "by_cell": {k: v["verdict"] for k, v in summary.items()},
        "overall": ("合格" if any(v["verdict"] == "合格" for v in summary.values())
                    else ("判定不能" if all(v["verdict"] == "判定不能" for v in summary.values())
                          else "不合格")),
        "readings_all_agree": all(
            (v["verdict"] == "合格") == any(v["readings"].values()) or v["verdict"] == "判定不能"
            for v in summary.values()),
        "note": ("交互作用の差・十分位・V の帯・相対低下は**記述**であって合否に使っていない"),
    }

    o = {
        "generated": "2026-08-18",
        "tool": "night/opmtrend_h3.py",
        "role": ("H3（水準との交互作用）。**値も規約も採点式も刻みも重みも関門も売却規律も"
                 "配分も1バイト触っていない**。書くのは out/opmtrend_h3.json だけ"),
        "reads": ["out/opmtrend_base.json（load_base）", "night/opmtrend_h1.py の小道具"],
        "seed": SEED,
        "prereg": "out/opm_trend_prereg.json の H3_level_interaction",
        "direction": "lift = P(hit|opmD5>=0) - P(hit|opmD5<0)。正なら『下がっている社のほうが悪い』",
        "self_checks": checks,
        "h3_per_cell": per,
        "h3_summary": summary,
        "interaction": inter,
        "deciles": dec,
        "v_question": vq,
        "pseudo_replication": pr,
        "adversarial": adv,
        "power": pw,
        "permutation": pm,
        "verdict": verdict,
        "warnings": warns,
        "limits": [
            "8ビンテージは同じ956社で窓が重なる＝真の out-of-sample はゼロ",
            "窓の長さが 4.08〜13.09年と違うので基礎率をビンテージ間で直接比べない",
            "2013 は opmD5 の被覆が48%・欠測が小型に偏る（売上中央が5.91倍）＝別の母集団の疑い",
            "★質実証プールの『低マージン』は絶対水準では低くない（opm>=10% で定義されているため）",
            "opmD5 は会計上の営業利益率の差で、一過性費用（CELH の解約金型）を調整しない",
            "opm の水準と opmD5 は独立ではない（高マージンほど下がりやすい＝平均回帰）。"
            "交互作用はこの従属の上で測っている",
            "★行は社×ビンテージ＝同じ社が最大8回入る。のべ読みは疑似反復を含む。"
            "cw_ 欄（社単位）を必ず併記して読むこと",
            "生存バイアスは既記録のまま（左尾は 2.00〜25.68% の幅）",
            "V 自身は歴史パネルに居るが、V の opmD5 は 8ビンテージ中6つで正＝"
            "今日の gmt=down は歴史側の V とは別の局面",
        ],
    }
    fp = os.path.join(OUT, "opmtrend_h3.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    print("wrote", fp)
    for w in warns:
        print("WARN:", w)
    print("verdict:", json.dumps(verdict, ensure_ascii=False))
    return o


if __name__ == "__main__":
    main()
