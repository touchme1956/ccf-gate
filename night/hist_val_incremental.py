# night/hist_val_incremental.py — 自己相対バリュエーションの「既存の門に対する増分」を測る (2026-08-09新設)
#
# 何をする道具か:
#   night/hist_val_gate_test.py が事前登録の基準1〜4を**プール全体**で当てたのに対し、
#   こちらは事前登録の **基準5（増分）** を担当する——
#   「**既存の四関門（Ω75+ / 堀70+ / データ健全 / 事業の収縮）で既に落ちる社を除いても**
#     1〜4 が保たれるか」。遮断器を1本増やす価値は、既存の関門が取り逃した左尾を
#   どれだけ拾えるかで決まる。既に門が止めている社を止めても、増分はゼロ。
#
#   同時に **irr=85 との交互作用**を測る。この台帳で唯一「効く」と実証された変数が irr で、
#   2026-08-07 の E[r] の検定は「**irrを固定すると E[r] の効果は消えるが、E[r]を固定しても
#   irr=85 の効果は残る**」と出た。自己相対分位にも同じ検定を当てる——
#   **irrを固定して効果が消えるなら、それは irr の影であって独立な信号ではない。**
#
# ─────────────────────────────────────────────────────────────────────────────
# 【この道具が守っている作法】
#
# ■ 二重実装を作らない（v9.9.65）
#   プールの作り方・窓の判定・統計・基準1/2/4の判定・事前登録の照合・『事業の収縮』の式は
#   すべて night/hist_val_gate_test.py の関数を**そのまま読んで使う**。同じことを測る関数が
#   二つできると、同じ台帳を見て違うことを言い始める。ここで新しく足すのは
#   「**残差プールの作り方**」と「**層別**」だけ。
#
# ■ 代理は代理と書く（憶測で埋めない）
#   歴史ビンテージに Ω も 台帳の点検も無い。**定性採点を後知恵でやらない**のが retro 系の
#   設計方針なので、四関門のうち機械で代理できるのは2つだけ:
#     ・堀70+   → **読解済み irr**（out/retro_moat_*.json・結末を伏せて読まれたもの）が
#                  2013/2015は70以上・2018は75以上。**5本柱のうち1本だけの代理**であり、
#                  irr は 2026-08-06 の実測で P(継続) 50:0.162 / 70:0.366 / 85:0.579 と
#                  単調に効く唯一の柱なので、5本の中では最も強い代理になる。
#     ・事業の収縮 → gate_test.shrink_flags（retro_breaker_test と同式）
#     ・Ω75+    → **代理できない**。最も近いのは事前登録の質実証プールそのもの
#                  （prereg が『門が遮断器を当てる場所の相当物』と定義している）。
#                  Ω は定性採点を含むので、機械値で作った代理を Ω と呼ばない。
#     ・データ健全 → **代理できない**（歴史側に台帳もパックも無い）。
#   代理できない2つは「代理できない」と出力に書く。埋めた顔をしない。
#
# ■ 0 と 判定不能 を混ぜない（絶対のルール7の同族）
#   残差プールでベースの恒久毀損が **0件** なら、基準1の『2.0倍』は**割り算が定義できない**。
#   これは「不合格」ではなく「**判定不能**」。同時に **0件は真のゼロではない**ので
#   95%上端（規則3: 3/n）を必ず併記する。
#
# ■ 中央値だけで語らない / 分子を必ず出す
#   等ウェイト買い持ち（終価倍率の算術平均→年率）を併記し、恒久毀損は率と実数の両方を出す。
#
# 実行:
#   python3 night/hist_val_incremental.py
#   python3 night/hist_val_incremental.py --json out/hist_val_incremental.json
import argparse
import importlib.util
import json
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# ── 既存器をそのまま読む（再実装しない）──────────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "hist_val_gate_test", os.path.join(BASE, "night", "hist_val_gate_test.py"))
GT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GT)

VINTAGES = GT.VINTAGES
INDICATORS = GT.INDICATORS
GRID_PCT, GRID_Z, GRID_SPX = GT.GRID_PCT, GT.GRID_Z, GT.GRID_SPX
PERM, WIN = GT.PERM, GT.WIN

# 2018年ビンテージの読解は刻みが 50/75/85（当時の規約）、2013/2015 は 50/70/85/100。
# 「堀70+」に対応する線はそれぞれ 75 / 70。**刻みの無い数字を発明しない**。
IRR_GATE_LINE = {2018: 75, 2015: 70, 2013: 70}


def moat_irr(y):
    """結末を伏せて読まれた irr を読む。**同一社が複数ファイルに出たら先に読まれた方を採る**
    （2015 は 2015 / 2015q / 2015qb の3本があり、重複は同じ社の同じ原本を別班が読んだもの。
      追試の実測で両ビンテージ147社の一致率は90.5%・85 は一度も揺れていない）。"""
    src = {2018: [("retro_moat_2018.json", "t", "irr18"),
                  ("retro_moat_2018_rest.json", "t", "irr18")],
           2015: [("retro_moat_2015.json", "ticker", "irr"),
                  ("retro_moat_2015q.json", "ticker", "irr"),
                  ("retro_moat_2015qb.json", "ticker", "irr")],
           2013: [("retro_moat_2013.json", "ticker", "irr"),
                  ("retro_moat_2013q.json", "ticker", "irr")]}[y]
    m, files = {}, []
    for f, tk, ik in src:
        p = os.path.join(OUT, f)
        if not os.path.exists(p):
            continue
        files.append(f)
        for r in json.load(open(p, encoding="utf-8")).get("rows") or []:
            t, v = r.get(tk), r.get(ik)
            if t and v is not None:
                m.setdefault(t, v)
    return m, files


# ── 残差プール（基準5の本体）─────────────────────────────────────────────────
# **結果を見る前に4つに固定した**。あとから「よく見える残差」を探さない。
RESIDUALS = [
    ("R0_quality",            "質実証プールそのまま（＝gate_test が基準1〜4を当てた場所）"),
    ("R1_no_shrink",          "R0 ∧ 事業の収縮なし（第四の関門）"),
    ("R2_moat",               "R0 ∧ 堀の代理（読解済み irr が線以上）"),
    ("R3_moat_and_no_shrink", "R0 ∧ 堀の代理 ∧ 収縮なし ＝ **機械で代理できる限りの四関門通過**"),
]


def residual(rows, name, shrink, irr, line):
    def ok(r):
        t = r["ticker"]
        if name in ("R1_no_shrink", "R3_moat_and_no_shrink") and shrink.get(t):
            return False
        if name in ("R2_moat", "R3_moat_and_no_shrink"):
            v = irr.get(t)
            if v is None or v < line:
                return False
        return True
    return [r for r in rows if ok(r)]


def upper95_zero(n):
    """0件の95%上端（規則3: 3/n）。**0件は真のゼロではない**を数字で言うため。"""
    return round(3.0 / n, 4) if n else None


def judge5(ev):
    """基準1/2/4 を残差プールで当てる。**ベースの毀損0件は『判定不能』**（不合格と書かない）。"""
    st, pa, ba = ev["stopped"], ev["passed"], ev["base"]
    if not st.get("n_ret") or not pa.get("n_ret"):
        return {"c1": None, "c1_status": "判定不能（止めた群または通過群が空）",
                "c2": None, "c4": None}
    if ba["p_perm"] <= 0:
        c1, ratio = None, None
        status = (f"判定不能（残差プールの恒久毀損が **0件/{ba['n_ret']}社** ＝ 倍率が定義できない。"
                  f"95%上端 {upper95_zero(ba['n_ret'])}）")
    else:
        ratio = round(st["p_perm"] / ba["p_perm"], 2)
        c1 = bool(st["p_perm"] >= 2.0 * ba["p_perm"] and st["n_perm"] >= 5)
        status = "合格" if c1 else f"不合格（濃縮 {ratio}倍 / 分子 {st['n_perm']}社）"
    c2 = bool(st["median"] <= pa["median"])
    c4 = bool(ev["stop_rate_pool"] is not None and ev["stop_rate_pool"] <= 0.15)
    return {"c1": c1, "c1_status": status, "c1_ratio": ratio, "c1_numer": st["n_perm"],
            "c2": c2, "c2_gap": round(st["median"] - pa["median"], 4),
            "c4": c4, "c4_stop_rate": ev["stop_rate_pool"]}


# ── 交互作用 ─────────────────────────────────────────────────────────────────
# **irr85+ には irr=100 も入る**（v>=85）。台帳の追試では 100 は最下位（P継続 0.056/0.091）なので、
# 100 を混ぜるのは irr85 の効果を**小さく見せる側＝保守的**。85ちょうどだけの版も別に出す。
IRR_STRATA = [("irr85+", lambda v: v is not None and v >= 85),
              ("irr85_exact", lambda v: v == 85),
              ("irr70_75", lambda v: v is not None and 70 <= v < 85),
              ("irr50", lambda v: v is not None and v < 70)]


def interact(pool_rows, irr, key, kind, hist_key, thr, years):
    """(a) irr を固定して自己相対の効果を見る / (b) 自己相対を固定して irr=85 の効果を見る。

    どちらも同じ群分けから作るので、**同じ台帳から二つの読みが出る**（別々に組まない）。
    指標は中央値・等ウェイト・P(15%+)・恒久毀損の4つを毎回そろえる。
    """
    def cls(r):
        v = r.get(key)
        if kind == "z" and hist_key and (r.get(hist_key) or 0) < GT.Z_MIN_MONTHS:
            return None
        if v is None:
            return None
        return "stop" if v >= thr else "pass"

    rows = [r for r in pool_rows if irr.get(r["ticker"]) is not None and cls(r)]
    out = {"n_joint": len(rows), "by_irr": {}, "by_val": {}}

    # (a) irr 層の中で、自己相対の線は何かを分けるか
    for nm, f in IRR_STRATA:
        sub = [r for r in rows if f(irr[r["ticker"]])]
        if not sub:
            continue
        s = [r for r in sub if cls(r) == "stop"]
        p = [r for r in sub if cls(r) == "pass"]
        out["by_irr"][nm] = {
            "n": len(sub), "stopped": GT.stats(s, years), "passed": GT.stats(p, years),
            "d_median": (None if not (s and p) else
                         round(GT.stats(s, years)["median"] - GT.stats(p, years)["median"], 4)),
            "d_win": (None if not (s and p) else
                      round(GT.stats(s, years)["p_win"] - GT.stats(p, years)["p_win"], 4)),
        }
    # (b) 自己相対の層の中で、irr=85 は何かを分けるか
    for nm in ("stop", "pass"):
        sub = [r for r in rows if cls(r) == nm]
        if not sub:
            continue
        hi = [r for r in sub if irr[r["ticker"]] >= 85]
        lo = [r for r in sub if irr[r["ticker"]] < 85]
        out["by_val"][nm] = {
            "n": len(sub), "irr85": GT.stats(hi, years), "other": GT.stats(lo, years),
            "d_median": (None if not (hi and lo) else
                         round(GT.stats(hi, years)["median"] - GT.stats(lo, years)["median"], 4)),
            "d_win": (None if not (hi and lo) else
                      round(GT.stats(hi, years)["p_win"] - GT.stats(lo, years)["p_win"], 4)),
        }
    return out


def perm_overlap(q, shrink, irr, line):
    """**この検定の核心**——自己相対の線が捕まえた恒久毀損は、既存の関門が既に捕まえていたか。

    増分は「止めた社数」ではなく「**既存の関門をすり抜けた左尾のうち何社を拾えたか**」で決まる。
    質実証プールの恒久毀損を1社ずつ並べ、(a)既存の関門のどれが止めるか (b)自己相対の各指標が
    格子の閾値で止めるか、を突き合わせる。

    **irr未読解**は『関門を通る』と読まない——実際の門も、堀が5本そろわない社は堀が算出不能で
    通さない（キーエンス型）。ただし『読まれていないだけ』と『読んで低かった』は証拠の強さが違うので
    hard / soft に分けて数える（soft を関門扱いしない最も保守的な読みも同時に出す）。
    """
    out = []
    for r in q:
        c = r.get("tr_cagr")
        if c is None or c > PERM:
            continue
        t = r["ticker"]
        v = irr.get(t)
        hard, soft = [], []
        if shrink.get(t):
            hard.append("事業の収縮")
        if v is None:
            soft.append("irr未読解（読まれていない＝堀が算出不能）")
        elif v < line:
            hard.append(f"irr={v} < {line}")
        # 自己相対の線は、この社を格子のどこかで止められるか
        caught = []
        for key, kind, hist_key, _ in INDICATORS:
            if kind == "mkt":
                continue
            grid = GRID_PCT if kind == "pct" else GRID_Z
            val = r.get(key)
            if val is None:
                continue
            if kind == "z" and hist_key and (r.get(hist_key) or 0) < GT.Z_MIN_MONTHS:
                continue
            hits = [g for g in grid if val >= g]
            if hits:
                caught.append(f"{key}>={min(hits)}")
        out.append({"ticker": t, "cagr": round(c, 4),
                    "gate_hard": hard, "gate_soft": soft,
                    "already_stopped_hard": bool(hard),
                    "already_stopped_any": bool(hard or soft),
                    "val_catch": caught, "val_would_catch": bool(caught),
                    "pe_pct": r.get("pe_pct"), "ps_pct": r.get("ps_pct"),
                    "adj_pe_pct": r.get("adj_pe_pct")})
    return out


def spearman(xs, ys):
    """順位相関（事前登録外の**記述統計**・合否には使わない）。閾値に依らず向きと強さを1数字で出す。"""
    n = len(xs)
    if n < 8:
        return None
    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        rk = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math_sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math_sqrt(sum((b - my) ** 2 for b in ry))
    return None if dx == 0 or dy == 0 else round(num / (dx * dy), 4)


def math_sqrt(x):
    return x ** 0.5


def rho_by_irr(pool_rows, irr, key, kind, hist_key):
    """指標 vs 前方リターンの順位相関を、全体と irr 層それぞれで出す。

    **遮断器としては負の相関（高いほど悪い）を期待する**。層の中で相関が消えるなら
    それは irr の影であって独立な信号ではない（2026-08-07 の E[r] の検定と同じ形）。
    """
    def val(r):
        if kind == "z" and hist_key and (r.get(hist_key) or 0) < GT.Z_MIN_MONTHS:
            return None
        return r.get(key)
    def rho(rows):
        xy = [(val(r), r.get("tr_cagr")) for r in rows]
        xy = [(a, b) for a, b in xy if a is not None and b is not None]
        return {"n": len(xy), "rho": spearman([a for a, _ in xy], [b for _, b in xy])}
    res = {"all": rho(pool_rows),
           "joint_all": rho([r for r in pool_rows if irr.get(r["ticker"]) is not None])}
    for nm, f in IRR_STRATA:
        res[nm] = rho([r for r in pool_rows
                       if irr.get(r["ticker"]) is not None and f(irr[r["ticker"]])])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    prereg = GT.check_prereg()          # **基準を後から動かしていないことを機構で確かめる**
    res = {"generated": "2026-08-09", "tool": "night/hist_val_incremental.py",
           "lens": "基準5（既存の門に対する増分）＋ irr=85 との交互作用",
           "prereg": prereg, "residual_defs": dict(RESIDUALS),
           "proxy_note": {
               "堀70+": "読解済み irr（2018は>=75 / 2013・2015は>=70）。**5本柱のうち1本だけの代理**",
               "事業の収縮": "gate_test.shrink_flags（retro_breaker_test と同式）",
               "Ω75+": "**代理しない**。歴史側に定性採点が無い（後知恵汚染を避ける retro の設計方針）。"
                       "最も近いのは事前登録の質実証プールそのもの",
               "データ健全": "**代理できない**（歴史側に台帳・パックが無い）",
           },
           "vintages": {}, "cells": [], "interactions": [], "perm_overlap": {},
           "rho": {}, "summary": {}}

    all_cells = []
    inter_all = []
    for y in VINTAGES:
        d, rows = GT.load_vintage(y)
        years = d["join"]["modal_years"]
        P = GT.pools(rows)
        q = P["quality"]
        shrink, shrink_src, shrink_exact = GT.shrink_flags(y)
        irr, irr_files = moat_irr(y)
        line = IRR_GATE_LINE[y]

        subs = {nm: residual(q, nm, shrink, irr, line) for nm, _ in RESIDUALS}
        vinfo = {"asof": d["asof"], "years": years,
                 "bench": d["join"]["benchmark"]["tr_cagr"],
                 "irr_src": irr_files, "irr_line": line,
                 "n_irr_read": len(irr),
                 "n_irr_in_quality": sum(1 for r in q if r["ticker"] in irr),
                 "irr_dist_in_quality": {},
                 "shrink_src": shrink_src, "shrink_exact": shrink_exact,
                 "n": {nm: len(v) for nm, v in subs.items()},
                 "base_perm": {}, }
        for nm, v in subs.items():
            s = GT.stats(v, years)
            vinfo["base_perm"][nm] = {"n_ret": s.get("n_ret"), "n_perm": s.get("n_perm"),
                                      "p_perm": s.get("p_perm"),
                                      "median": s.get("median"), "ew_cagr": s.get("ew_cagr"),
                                      "p_win": s.get("p_win"), "n_win": s.get("n_win"),
                                      "upper95_if_zero": (upper95_zero(s.get("n_ret") or 0)
                                                          if s.get("n_perm") == 0 else None)}
        dist = {}
        for r in q:
            v = irr.get(r["ticker"])
            dist[str(v)] = dist.get(str(v), 0) + 1
        vinfo["irr_dist_in_quality"] = dist
        res["vintages"][str(y)] = vinfo

        po = perm_overlap(q, shrink, irr, line)
        # **最も保守的な読み**: 収縮の代理が厳密でないビンテージ(2013/2015)ではそれを関門と数えず、
        # irr未読解も通ると仮定する＝既存の関門の力を最小に見積もる。増分がここでも出ないなら、
        # 「代理が甘いから増分が消えた」という反論が閉じる。
        for p in po:
            hard = [h for h in p["gate_hard"] if shrink_exact or h != "事業の収縮"]
            p["gate_hard_exact_only"] = hard
            p["survives_ultra_conservative"] = not hard
        res["perm_overlap"][str(y)] = po
        res["rho"][str(y)] = {key: rho_by_irr(q, irr, key, kind, hk)
                              for key, kind, hk, _ in INDICATORS if kind != "mkt"}

        for key, kind, hist_key, label in INDICATORS:
            grid = GRID_PCT if kind == "pct" else (GRID_Z if kind == "z" else GRID_SPX)
            for thr in grid:
                for nm, _ in RESIDUALS:
                    ev = GT.evaluate(subs[nm], key, kind, hist_key, thr, years)
                    all_cells.append({"vintage": y, "residual": nm, "indicator": key,
                                      "kind": kind, "label": label, "threshold": thr,
                                      "ev": ev, "judge": judge5(ev)})
                # 交互作用は分位/zの指標だけ（spx_pe_pct は社に依らないので層別しても割れない）
                if kind != "mkt":
                    inter_all.append({"vintage": y, "indicator": key, "threshold": thr,
                                      "pool": "R0_quality",
                                      "res": interact(q, irr, key, kind, hist_key, thr, years)})

    res["cells"] = all_cells
    res["interactions"] = inter_all

    # ── 横断（基準3）と総括 ──────────────────────────────────────────────────
    agg = {}
    for c in all_cells:
        k = (c["residual"], c["indicator"], c["threshold"])
        agg.setdefault(k, {})[c["vintage"]] = c["judge"]
    rules = []
    for (rn, ind, thr), vs in agg.items():
        ok12 = [y for y, j in vs.items() if j.get("c1") is True and j.get("c2") is True]
        und = [y for y, j in vs.items() if j.get("c1") is None]
        rules.append({"residual": rn, "indicator": ind, "threshold": thr,
                      "vint": {str(y): {"c1": j.get("c1"), "c1_status": j.get("c1_status"),
                                        "c2": j.get("c2"), "c4": j.get("c4"),
                                        "stop_rate": j.get("c4_stop_rate")}
                               for y, j in vs.items()},
                      "n_ok12": len(ok12), "n_undecidable": len(und),
                      "c3": len(ok12) >= 2,
                      "c4_all": all(j.get("c4") for j in vs.values()),
                      "all_pass_1234": len(ok12) >= 2 and all(j.get("c4") for j in vs.values())})
    res["rules"] = rules
    passing = [r for r in rules if r["all_pass_1234"]]
    res["passing_rules"] = passing

    # 増分の総括: 「既存の関門をすり抜けた恒久毀損」を自己相対の線は何社拾えたか
    po_all = [p for v in res["perm_overlap"].values() for p in v]
    survive_hard = [p for p in po_all if not p["already_stopped_hard"]]
    survive_any = [p for p in po_all if not p["already_stopped_any"]]
    res["increment"] = {
        "n_perm_in_quality": len(po_all),
        "n_survive_existing_gates_strict": len(survive_any),
        "n_survive_existing_gates_conservative": len(survive_hard),
        "conservative_note": "『irr未読解』を関門扱いしない最も保守的な読み（未読解は通ると仮定）",
        "n_caught_by_valuation_among_survivors_strict": sum(1 for p in survive_any if p["val_would_catch"]),
        "n_caught_by_valuation_among_survivors_conservative":
            sum(1 for p in survive_hard if p["val_would_catch"]),
        "survivors_conservative": [{"t": p["ticker"], "cagr": p["cagr"],
                                    "pe_pct": p["pe_pct"], "ps_pct": p["ps_pct"],
                                    "adj_pe_pct": p["adj_pe_pct"],
                                    "val_catch": p["val_catch"]} for p in survive_hard],
    }
    ultra = [p for p in po_all if p.get("survives_ultra_conservative")]
    res["increment"]["ultra_conservative"] = {
        "def": "収縮の代理が厳密なビンテージ(2018)でだけ収縮を関門と数え、irr未読解も通ると仮定する"
               "＝既存の関門の力を最小に見積もる読み",
        "n_survive": len(ultra),
        "n_caught_by_valuation": sum(1 for p in ultra if p["val_would_catch"]),
        "rows": [{"t": p["ticker"], "cagr": p["cagr"], "val_catch": p["val_catch"],
                  "pe_pct": p["pe_pct"], "ps_pct": p["ps_pct"], "adj_pe_pct": p["adj_pe_pct"]}
                 for p in ultra],
        "prereg_c1_needs": "基準1は分子>=5社を要求する",
    }

    # 交互作用の総括（事前登録の分位指標×格子だけを平均する。z は下限36ヶ月つき）
    def agg_inter(pick):
        acc = {}
        for it in inter_all:
            if it["indicator"] not in ("pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct"):
                continue
            for k, v in it["res"][pick].items():
                if v.get("d_median") is None:
                    continue
                a = acc.setdefault((it["vintage"], k), {"dm": [], "dw": [], "n": 0})
                a["dm"].append(v["d_median"])
                a["dw"].append(v["d_win"])
                a["n"] = v["n"]
        return {f"{y}/{k}": {"cells": len(a["dm"]), "n": a["n"],
                             "d_median_mean": round(statistics.fmean(a["dm"]), 4),
                             "d_win_mean": round(statistics.fmean(a["dw"]), 4)}
                for (y, k), a in sorted(acc.items())}
    res["interaction_summary"] = {
        "a_valuation_within_irr": agg_inter("by_irr"),
        "b_irr85_within_valuation": agg_inter("by_val"),
        "read": "a は『irrを固定したとき自己相対が分けるか（止−通）』。"
                "遮断器なら負であってほしい。b は『自己相対を固定したとき irr=85 が分けるか（85−他）』",
    }

    r3 = [r for r in rules if r["residual"] == "R3_moat_and_no_shrink"]
    res["summary"] = {
        "n_cells": len(all_cells), "n_rules": len(rules),
        "n_passing_rules": len(passing),
        "R3_rules": len(r3),
        "R3_all_undecidable_c1": all(r["n_undecidable"] == len(r["vint"]) for r in r3),
        "verdict_note": ("残差プール（機械で代理できる限りの四関門通過）で恒久毀損が0件なら、"
                         "基準1は『不合格』ではなく『判定不能』——**止めるべき左尾が残っていない**"),
    }

    if not a.quiet:
        print(f"■ 事前登録: {prereg['path']} ({prereg['registered']}) 照合OK")
        for y in VINTAGES:
            v = res["vintages"][str(y)]
            print(f"\n── {y} (asof {v['asof']} / {v['years']}年 / SPY {v['bench']:.1%}) "
                  f"irr読解 {v['n_irr_read']}社・うち質実証プール内 {v['n_irr_in_quality']}社 "
                  f"(irr>={v['irr_line']} を堀の代理)")
            print("   irr分布(質実証内):", v["irr_dist_in_quality"])
            for nm, _ in RESIDUALS:
                b = v["base_perm"][nm]
                u = f" [0件の95%上端 {b['upper95_if_zero']}]" if b["upper95_if_zero"] else ""
                print(f"   {nm:24s} n={v['n'][nm]:4d} 中央値 {b['median']} "
                      f"等ウェイト {b['ew_cagr']} 15%+ {b['p_win']}({b['n_win']}) "
                      f"恒久毀損 {b['p_perm']}({b['n_perm']}社){u}")
        inc = res["increment"]
        print(f"\n■ 増分: 質実証プールの恒久毀損 {inc['n_perm_in_quality']}社 → "
              f"既存の関門をすり抜けるのは {inc['n_survive_existing_gates_strict']}社"
              f"（未読解を通す最も保守的な読みでも {inc['n_survive_existing_gates_conservative']}社）"
              f" → そのうち自己相対の線が拾えるのは "
              f"{inc['n_caught_by_valuation_among_survivors_conservative']}社")
        u = inc["ultra_conservative"]
        print(f"   最も保守的な読み（{u['def']}）: すり抜け {u['n_survive']}社 → "
              f"自己相対が拾えるのは {u['n_caught_by_valuation']}社（基準1は分子>=5社を要求）")
        for s in u["rows"]:
            print(f"     {s['t']:6s} cagr={s['cagr']} 自己相対で止まる? "
                  f"{s['val_catch'] or '**止まらない**'}")
        for s in inc["survivors_conservative"]:
            print(f"   すり抜け: {s['t']:6s} cagr={s['cagr']} pe_pct={s['pe_pct']} "
                  f"ps_pct={s['ps_pct']} adj={s['adj_pe_pct']} 自己相対で止まる? "
                  f"{s['val_catch'] or '**止まらない（全部 安い側）**'}")
        print("\n■ 交互作用 (a) irr を固定したとき 自己相対 が分けるか（止−通・格子平均）")
        for k, v in res["interaction_summary"]["a_valuation_within_irr"].items():
            print(f"   {k:16s} n={v['n']:3d} Δ中央値 {v['d_median_mean']:+.4f} Δ15%+ {v['d_win_mean']:+.4f}")
        print("■ 交互作用 (b) 自己相対 を固定したとき irr=85 が分けるか（85−他・格子平均）")
        for k, v in res["interaction_summary"]["b_irr85_within_valuation"].items():
            print(f"   {k:16s} n={v['n']:3d} Δ中央値 {v['d_median_mean']:+.4f} Δ15%+ {v['d_win_mean']:+.4f}")
        print("\n■ 順位相関 rho(指標, 前方リターン)  ※遮断器なら負を期待。層で消えるなら irr の影")
        for y in VINTAGES:
            for key in ("pe_pct", "ps_pct", "adj_pe_pct"):
                rr = res["rho"][str(y)][key]
                cells = "  ".join(f"{nm}:{(rr[nm]['rho'] if rr[nm]['rho'] is not None else '—')}"
                                  f"(n={rr[nm]['n']})" for nm in
                                  ("all", "joint_all", "irr85+", "irr70_75", "irr50"))
                print(f"   {y} {key:11s} {cells}")

        print(f"\n■ 基準1〜4を全部満たす (残差×指標×閾値): {len(passing)} 件")
        for p in passing:
            print("   ", p["residual"], p["indicator"], p["threshold"])

    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n書き出し: {a.json}")
    return res


if __name__ == "__main__":
    main()
