# night/hist_val_gate_test.py — 自己相対バリュエーションを「遮断器」として検定する (2026-08-09新設)
#
# 何をする道具か:
#   在庫 out/hist_val_{2013,2015,2018}.json（night/hist_valuation.py + hist_val_join.py が作る）へ、
#   事前登録 out/hist_valuation_prereg.json の**格子どおりの閾値だけ**を当てて、
#   「その閾値で買付を止めていたら、20-30年の複利にとって得だったか」を実測する。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【この道具が守っている作法】
#
# ■ 事前登録を後から動かさない（この検定の全部）
#   閾値の格子・合否の6基準は **out/hist_valuation_prereg.json が正本**。この道具は起動時に
#   prereg を読んで**格子と基準の文字列が当時のまま残っているか照合**し、変わっていたら走らない。
#   「結果を見てから基準を動かす」を、人の意志ではなく機構で防ぐ。
#
# ■ 遮断器は選別器ではない（物差しの選び方）
#   v9.9.98 でE[r]を門から外したときに確立した読み方をそのまま使う——
#   遮断器を裁くのは「**止めた側の左尾**（恒久毀損率 P(年率<=-15%)）」であって
#   「通した側の平均」ではない。同時に「**止めた群の中央値が通過群より高くないか**」
#   （＝勝者を巻き込んでいないか）を必ず併せて見る。片方だけ良い規則は遮断器として失格。
#
# ■ 中央値だけで語らない
#   等ウェイト買い持ち（終価倍率の**算術平均**を年率へ）も必ず併記する。実測で
#   「中央値7.2% vs 等ウェイト12.4%」と大きく違い、差は右裾にある。中央値は「1社を選んだとき」、
#   等ウェイトは「その群を全部買ったとき」で、**別の問い**に答えている。
#
# ■ 「n=9の0件は真のゼロではない」を自分に当てる
#   恒久毀損率は必ず**分子（実数）**を併記する。事前登録の基準1が「分子>=5社」を要求するのは
#   この台帳が何度も踏んだ「小さい分母の0%・100%」を規則にしないため。
#
# ■ 窓を揃える / 二重実装を作らない
#   窓の判定（window_full）・質実証プールの印（quality）・前方リターンの綴じ込みは
#   すべて hist_val_join.py が済ませてある。ここでは**畳み込まれた印を読むだけ**で、
#   join をやり直さない（同じ join が3つできると基準がずれる・v9.9.65）。
#   基準5の「事業の収縮」も **retro_breaker_test.py と同じ式**（cagr5<0 ∧ opmD5<0）を使う。
#
# ■ 欠測をゼロと読むな（絶対のルール7）
#   指標が null の社は「止めた」でも「通した」でもない＝**判定不能**として別に数える。
#   0（＝低い）と読み替えない。被覆率は必ず出す（事前登録『分母の質』）。
#
# 実行:
#   python3 night/hist_val_gate_test.py                  # 全ビンテージ・全指標・全格子
#   python3 night/hist_val_gate_test.py --pool quality   # プールを絞る
#   python3 night/hist_val_gate_test.py --json out/hist_val_gate_test.json
import argparse
import json
import math
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

VINTAGES = (2018, 2015, 2013)          # 主ビンテージは2018（自己履歴が最も長い）

# ── 事前登録の格子（**ここを直したら prereg も直す。照合で落ちる**）──────────────
GRID_PCT = (0.80, 0.85, 0.90, 0.95)
GRID_Z = (1.0, 1.5, 2.0)
GRID_SPX = (0.80, 0.90, 0.95)

# 事前登録 indicators のうち、在庫に実在する欄へ写したもの。
#  kind: "pct" = 0-1 の自己履歴分位 / "z" = (現値−自己中央値)/自己σ / "mkt" = 市場水準（社に依らない）
#  hist: その指標の自己履歴の長さの欄（z は下限36ヶ月を**別に課す**。下の注記を見よ）
INDICATORS = [
    ("pe_pct",     "pct", "pe_hist_months",   "A 自己相対PER 分位"),
    ("ps_pct",     "pct", "ps_hist_months",   "A 自己相対P/S 分位"),
    ("pfcf_pct",   "pct", "pfcf_hist_months", "A 自己相対P/FCF 分位"),
    ("adj_pe_pct", "pct", "adj_pe_hist_months", "A 市場調整PER 分位"),
    ("pe_z",       "z",   "pe_hist_months",   "A 自己相対PER z"),
    ("ps_z",       "z",   "ps_hist_months",   "A 自己相対P/S z"),
    ("spx_pe_pct", "mkt", None,               "B 市場の水準（S&P500実績PERの1871年以降分位）"),
]

# 事前登録の indicators に**入っていない**版（年次更新だけで組んだ分位）。
# 採取器が感度用に持っているだけなので、**合否には一切使わない**（基準6の多重検定を増やさない）。
SENSITIVITY_ONLY = [
    ("pe_pct_ann",     "pct", "pe_ann_hist_months",     "感度(事前登録外) 年次更新だけのPER分位"),
    ("adj_pe_pct_ann", "pct", "adj_pe_ann_hist_months", "感度(事前登録外) 年次更新だけの市場調整PER分位"),
]

# z は採取器の仕様で**自己履歴8ヶ月から出る**（分位は36ヶ月を要求する）。
# 在庫の caveats がこれを名指ししているので、z の格子を当てるときは 36ヶ月を併せて課す
# ——課さないと「分位では判定不能の社が z では判定される」＝二つの指標が別の母集団を見る。
Z_MIN_MONTHS = 36

PERM = -0.15        # 恒久毀損の線（この台帳の既定）
WIN = 0.15          # 「15%+」の線（目標帯の下限）


# ── 事前登録との照合 ─────────────────────────────────────────────────────────
def check_prereg():
    """**結果を見てから基準を動かす**を機構で防ぐ。prereg の文言と格子が当時のままか照合する。"""
    p = os.path.join(OUT, "hist_valuation_prereg.json")
    j = json.load(open(p, encoding="utf-8"))
    c = j["pass_criteria_ALL_must_hold"]
    blob = json.dumps(j, ensure_ascii=False)
    need = [
        ("格子: 分位 80/85/90/95", "80/85/90/95"),
        ("格子: z 1.0/1.5/2.0", "1.0/1.5/2.0"),
        ("格子: spx_pe_pct 80/90/95", "80/90/95"),
        ("基準1: 2.0倍", "2.0倍"),
        ("基準1: 分子>=5社", "5社"),
        ("基準4: 15%以下", "15%以下"),
    ]
    bad = [nm for nm, s in need if s not in blob]
    if bad:
        raise SystemExit("■ 事前登録が当時と違う。検定を中止する（基準を動かして走らせない）:\n  "
                         + "\n  ".join(bad))
    return {"path": "out/hist_valuation_prereg.json", "registered": j.get("registered"),
            "criteria": c, "grid_verified": True}


# ── 統計 ─────────────────────────────────────────────────────────────────────
def ew_cagr(rows, years):
    """等ウェイト買い持ちの年率。**終価倍率の算術平均**を年率へ（中央値とは別の問いに答える）。"""
    tot = []
    for r in rows:
        t = r.get("tr_total")
        if t is None and r.get("tr_cagr") is not None and r.get("years"):
            t = (1.0 + r["tr_cagr"]) ** r["years"]
        if t is not None and t > 0:
            tot.append(t)
    if not tot or not years:
        return None, 0
    return (statistics.fmean(tot)) ** (1.0 / years) - 1.0, len(tot)


def stats(rows, years):
    """群の姿。**恒久毀損は必ず分子（実数）を持たせる**。"""
    rs = [r["tr_cagr"] for r in rows if r.get("tr_cagr") is not None]
    if not rs:
        return {"n": len(rows), "n_ret": 0}
    nperm = sum(1 for x in rs if x <= PERM)
    nwin = sum(1 for x in rs if x >= WIN)
    ew, n_ew = ew_cagr(rows, years)
    mdd = [r["mdd"] for r in rows if r.get("mdd") is not None]
    return {
        "n": len(rows), "n_ret": len(rs),
        "median": round(statistics.median(rs), 4),
        "mean": round(statistics.fmean(rs), 4),
        "ew_cagr": None if ew is None else round(ew, 4), "n_ew": n_ew,
        "p_perm": round(nperm / len(rs), 4), "n_perm": nperm,
        "p_win": round(nwin / len(rs), 4), "n_win": nwin,
        "mdd_median": round(statistics.median(mdd), 3) if mdd else None,
    }


def worst(rows, k=8):
    xs = sorted((r for r in rows if r.get("tr_cagr") is not None), key=lambda r: r["tr_cagr"])
    return [{"t": r["ticker"], "cagr": round(r["tr_cagr"], 4)} for r in xs[:k]]


# ── プール ───────────────────────────────────────────────────────────────────
def load_vintage(y):
    d = json.load(open(os.path.join(OUT, f"hist_val_{y}.json"), encoding="utf-8"))
    rows = [r for r in d["rows"] if r.get("analysis_set")]
    return d, rows


def pools(rows):
    """quality = 質実証プール（**合否はこちらで判定する**・事前登録 pools.note）。full は参考。"""
    return {"quality": [r for r in rows if r.get("quality")], "full": list(rows)}


# ── 基準5（既存の関門で既に落ちる社を除く）──────────────────────────────────
def shrink_flags(y):
    """『事業の収縮』(v9.9.99の第四の関門)の歴史側の相当物。

    2018: retro_features2 の `cagr5<0 ∧ opmD5<0` ＝ **retro_breaker_test.py と同じ式**（再実装しない）。
    2013/2015: 在庫(retro_cohort)に **opmD5（営業利益率の5年変化）が無い**。推測で埋めないので
      `sales_cagr5<0` だけの **上位集合の代理**として計算し、そう明記する（真の関門より多く除く）。
    """
    p2 = os.path.join(OUT, f"retro_features2_{y}.json")
    if os.path.exists(p2):
        j = json.load(open(p2, encoding="utf-8"))
        f = {r["ticker"]: r for r in j.get("rows") or [] if r.get("ticker")}
        return ({t: ((r.get("cagr5") or 0) < 0 and (r.get("opmD5") or 0) < 0) for t, r in f.items()},
                f"retro_features2_{y}.json: cagr5<0 ∧ opmD5<0（retro_breaker_test と同式・厳密）", True)
    pc = os.path.join(OUT, f"retro_cohort_{y}.json")
    if os.path.exists(pc):
        j = json.load(open(pc, encoding="utf-8"))
        f = {}
        for r in j.get("rows") or []:
            t = r.get("ticker")
            if t and t not in f:
                f[t] = (r.get("sales_cagr5") or 0) < 0
        return (f, f"retro_cohort_{y}.json: sales_cagr5<0 のみ（**opmD5 が在庫に無い**＝"
                   f"真の関門より多く除く上位集合の代理）", False)
    return {}, "在庫なし＝基準5は判定不能", False


# ── 1つの (プール × 指標 × 閾値) を測る ──────────────────────────────────────
def evaluate(pool_rows, key, kind, hist_key, thr, years, drop=None):
    """止めた群 / 通過群 / 判定不能 に分けて姿を出す。

    **欠測をゼロと読まない**: 指標が null の社は止めても通してもいない＝`na` として別に数える
    （実運用では未測定は発火しない側だが、それを『通過群』に混ぜると規則の姿がぼやける。
      両方の読みが出せるよう `pass_incl_na` も併記する）。
    """
    rows = [r for r in pool_rows if not (drop and drop.get(r["ticker"]))]
    stop, pas, na = [], [], []
    for r in rows:
        v = r.get(key)
        ok_hist = True
        if kind == "z" and hist_key:
            ok_hist = (r.get(hist_key) or 0) >= Z_MIN_MONTHS
        if v is None or not ok_hist:
            na.append(r)
        elif v >= thr:
            stop.append(r)
        else:
            pas.append(r)
    n_pool = len(rows)
    return {
        "n_pool": n_pool,
        "n_measurable": len(stop) + len(pas),
        "coverage": round((len(stop) + len(pas)) / n_pool, 4) if n_pool else None,
        "n_stop": len(stop),
        "stop_rate_pool": round(len(stop) / n_pool, 4) if n_pool else None,
        "stop_rate_measurable": (round(len(stop) / (len(stop) + len(pas)), 4)
                                 if (stop or pas) else None),
        "stopped": stats(stop, years),
        "passed": stats(pas, years),
        "passed_incl_na": stats(pas + na, years),
        "na": stats(na, years),
        "base": stats(rows, years),
        "stopped_worst": worst(stop),
        "stopped_perm_tickers": [r["ticker"] for r in stop
                                 if r.get("tr_cagr") is not None and r["tr_cagr"] <= PERM],
    }


def judge(ev):
    """事前登録の基準1・2・4を機械的に当てる（3と5は横断・後段）。"""
    st, pa, ba = ev["stopped"], ev["passed"], ev["base"]
    if not st.get("n_ret") or not pa.get("n_ret"):
        return {"c1": None, "c2": None, "c4": None, "why": "止めた群または通過群が空＝判定不能"}
    # **ベースの恒久毀損が0件のプールでは「2.0倍」が定義できない**（2013がこれ＝自己履歴36ヶ月を
    # 要求すると初期XBRL提出社＝大型株だけが残り、毀損した社が母集団から丸ごと消える）。
    # 不合格と判定不能は別物なので status で書き分ける（0で割った答えを0や False と読まない・ルール7の同族）。
    if ba["p_perm"] <= 0:
        c1, c1_ratio, c1_status = False, None, "判定不能（ベースの恒久毀損が0件＝倍率が定義できない）"
    else:
        c1_ratio = round(st["p_perm"] / ba["p_perm"], 2)
        c1 = (st["p_perm"] >= 2.0 * ba["p_perm"] and st["n_perm"] >= 5)
        c1_status = "合格" if c1 else (
            f"不合格（濃縮 {c1_ratio}倍 / 分子 {st['n_perm']}社）")
    c2 = st["median"] <= pa["median"]
    c4 = (ev["stop_rate_pool"] is not None and ev["stop_rate_pool"] <= 0.15)
    return {"c1": bool(c1), "c1_status": c1_status, "c1_ratio": c1_ratio, "c1_numer": st["n_perm"],
            "c2": bool(c2), "c2_gap": round(st["median"] - pa["median"], 4),
            "c4": bool(c4), "c4_stop_rate": ev["stop_rate_pool"]}


def crosscheck(out):
    """**同じ台帳を見る二つの検査器が違うことを言ってはいけない**(v9.9.65)。

    並走で作られた night/hist_val_full.py の在庫（full プールの参考判定）と、同じ
    (プール×指標×閾値×ビンテージ) のセルを突き合わせる。**プールを揃えて比べること**
    ——別器の rules には full と quality が同居しており、pool を見ずに突合すると
    「別器の quality」と「本器の full」を比べて**存在しない食い違いを279件でっち上げる**
    （初版で実際にそうなった。食い違いを見つけたら、まず突合せ側を疑う）。

    既知の差（判定には影響しない）:
      ・別器の full は `window_full ∧ リターンあり`、本器の full は `analysis_set`
        （＝さらに「自己相対分位が1つ以上ある」を課す）。2018で 952 vs 918。
        分位が1つも無い社はどの規則でも止めも通しもしないので、群の中身は変わらない。
      ・基準4の分母: 本器は**プール全体**、別器は**その指標が定義できた社**。両方を持つ。
    """
    p = os.path.join(OUT, "hist_val_full.json")
    if not os.path.exists(p):
        return {"ran": False, "why": "out/hist_val_full.json が無い"}
    b = json.load(open(p, encoding="utf-8"))
    mine = {(r["pool"], r["indicator"], r["threshold"], r["vintage"]): r for r in out["results"]}
    n = bad = 0
    diffs = []
    for rule in b.get("rules") or []:
        for vy, v in (rule.get("vintages") or {}).items():
            m = mine.get((rule["pool"], rule["key"], rule["thr"], int(vy)))
            if not m:
                continue
            n += 1
            for nm, x, y in (("n_stop", m["ev"]["n_stop"], v.get("stop_n")),
                             ("stop_rate_measurable", m["ev"]["stop_rate_measurable"], v.get("stop_frac")),
                             ("stop_median", m["ev"]["stopped"].get("median"), v.get("stop_median")),
                             ("pass_median", m["ev"]["passed"].get("median"), v.get("pass_median")),
                             ("stop_ew", m["ev"]["stopped"].get("ew_cagr"), v.get("stop_ew")),
                             ("kill_numer", m["judge"].get("c1_numer"), v.get("stop_kill_n")),
                             ("c1", m["judge"].get("c1"), v.get("c1")),
                             ("c2", m["judge"].get("c2"), v.get("c2"))):
                if x is None or y is None:
                    continue
                same = (bool(x) == bool(y)) if isinstance(x, bool) or isinstance(y, bool) \
                    else abs(x - y) <= 0.0011
                if not same:
                    bad += 1
                    diffs.append({"cell": [rule["pool"], rule["key"], rule["thr"], vy],
                                  "field": nm, "mine": x, "other": y})
    return {"ran": True, "other": "out/hist_val_full.json", "cells": n, "mismatches": bad,
            "diffs": diffs[:20],
            "verdicts": {"mine_pass": len(out["passing_rules"]), "other_pass": b.get("n_pass_all")}}


def main():
    ap = argparse.ArgumentParser(description="自己相対バリュエーションを遮断器として事前登録どおり検定する")
    ap.add_argument("--pool", choices=("quality", "full", "both"), default="both")
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val_gate_test.json"))
    ap.add_argument("--sensitivity", action="store_true", help="事前登録外の _ann 版も出す（合否には不使用）")
    a = ap.parse_args()

    pre = check_prereg()
    print("■ 事前登録と照合 OK（格子・基準の文言が当時のまま）:", pre["path"], pre["registered"])

    out = {"generated": "2026-08-09", "tool": "night/hist_val_gate_test.py",
           "prereg": pre, "grid": {"pct": GRID_PCT, "z": GRID_Z, "spx": GRID_SPX},
           "z_min_months": Z_MIN_MONTHS, "perm_line": PERM, "win_line": WIN,
           "vintages": {}, "results": [], "notes": []}

    indi = INDICATORS + (SENSITIVITY_ONLY if a.sensitivity else [])
    want = ("quality", "full") if a.pool == "both" else (a.pool,)

    for y in VINTAGES:
        d, rows = load_vintage(y)
        years = d["join"]["modal_years"]
        bench = d["join"].get("benchmark") or {}
        P = pools(rows)
        drop, drop_src, drop_exact = shrink_flags(y)
        n_drop = {k: sum(1 for r in v if drop.get(r["ticker"])) for k, v in P.items()}
        out["vintages"][str(y)] = {
            "asof": d["asof"], "years": years,
            "bench": {"symbol": bench.get("symbol"), "tr_cagr": bench.get("tr_cagr")},
            "n_analysis_set": len(rows),
            "n_pool": {k: len(v) for k, v in P.items()},
            "spx_pe": rows[0].get("spx_pe") if rows else None,
            "spx_pe_pct": rows[0].get("spx_pe_pct") if rows else None,
            "shrink_src": drop_src, "shrink_exact": drop_exact, "n_shrink_in_pool": n_drop,
            "caveats": d["join"].get("caveats"),
        }
        print(f"\n{'='*100}\n■ {y}年ビンテージ  asof={d['asof']}  窓={years}年  "
              f"SPY {bench.get('tr_cagr')}  分析対象 {len(rows)}社  "
              f"質実証 {len(P['quality'])}社")
        print(f"  市場の水準 spx_pe={rows[0].get('spx_pe')} / 1871年以降分位 "
              f"{rows[0].get('spx_pe_pct')}（**社に依らない定数**）")
        print(f"  基準5で除く『事業の収縮』: {drop_src} → 質実証プール中 {n_drop['quality']}社")

        for pk in want:
            rws = P[pk]
            if not rws:
                continue
            b = stats(rws, years)
            print(f"\n  ── プール={pk}  n={len(rws)}  "
                  f"中央値 {b['median']:+.1%} / 等ウェイト {b['ew_cagr']:+.1%} / "
                  f"恒久毀損 {b['p_perm']:.1%}({b['n_perm']}社) / 15%+ {b['p_win']:.1%}")
            print(f"     {'指標':<16}{'閾値':>6}{'止めた':>8}{'止率':>7}{'被覆':>7}"
                  f"{'止:中央':>9}{'止:等W':>9}{'止:毀損':>12}{'通:中央':>9}{'通:毀損':>10}"
                  f"  {'1':>2}{'2':>2}{'4':>2}")
            for key, kind, hk, label in indi:
                grid = GRID_SPX if kind == "mkt" else (GRID_Z if kind == "z" else GRID_PCT)
                for thr in grid:
                    ev = evaluate(rws, key, kind, hk, thr, years)
                    jd = judge(ev)
                    ev5 = evaluate(rws, key, kind, hk, thr, years, drop=drop)
                    jd5 = judge(ev5)
                    rec = {"vintage": y, "pool": pk, "indicator": key, "kind": kind,
                           "label": label, "threshold": thr,
                           "prereg_indicator": key not in dict((k, 1) for k, *_ in SENSITIVITY_ONLY),
                           "ev": ev, "judge": jd,
                           "ev_excl_shrink": ev5, "judge_excl_shrink": jd5,
                           "shrink_exact": drop_exact}
                    out["results"].append(rec)
                    st, pa = ev["stopped"], ev["passed"]
                    if not st.get("n_ret") or not pa.get("n_ret"):
                        print(f"     {key:<16}{thr:>6}{ev['n_stop']:>8}"
                              f"{'':>7}{'':>7}   —— 判定不能（{jd.get('why','')}）")
                        continue
                    mk = lambda b_: "✓" if b_ else "✗"
                    print(f"     {key:<16}{thr:>6}{ev['n_stop']:>8}"
                          f"{ev['stop_rate_pool']:>7.1%}{ev['coverage']:>7.1%}"
                          f"{st['median']:>+9.1%}{st['ew_cagr']:>+9.1%}"
                          f"{st['p_perm']:>7.1%}({st['n_perm']:>2}){pa['median']:>+9.1%}"
                          f"{pa['p_perm']:>10.1%}  {mk(jd['c1']):>2}{mk(jd['c2']):>2}{mk(jd['c4']):>2}")

    # ── 基準3: 同じ (プール×指標×閾値) が 2ビンテージ以上で 1∧2 を満たすか ────────
    agg = {}
    for r in out["results"]:
        if not r["prereg_indicator"]:
            continue
        k = (r["pool"], r["indicator"], r["threshold"])
        j = r["judge"]
        agg.setdefault(k, {"vint": {}, "n_ok12": 0})
        ok = bool(j.get("c1")) and bool(j.get("c2"))
        agg[k]["vint"][r["vintage"]] = {"c1": j.get("c1"), "c2": j.get("c2"), "c4": j.get("c4"),
                                        "c1_ratio": j.get("c1_ratio"), "c1_numer": j.get("c1_numer"),
                                        "stop_rate": j.get("c4_stop_rate")}
        agg[k]["n_ok12"] += 1 if ok else 0
    passing = []
    for (pk, key, thr), v in sorted(agg.items()):
        c3 = v["n_ok12"] >= 2
        # **`all([])` は True になる**——判定不能しか無い指標(spx_pe_pct)が「基準4に合格」に
        # 化けるので、非nullが1つも無ければ c4_all は None（判定不能）にする。
        c4s = [x.get("c4") for x in v["vint"].values() if x.get("c4") is not None]
        c4_all = all(c4s) if c4s else None
        judgeable = bool(c4s)
        v.update({"pool": pk, "indicator": key, "threshold": thr, "c3": c3, "c4_all": c4_all,
                  "judgeable": judgeable,
                  "all_pass_1234": bool(judgeable and c3 and c4_all)})
        if v["all_pass_1234"]:
            passing.append(v)
    out["aggregate"] = list(agg.values())
    out["passing_rules"] = passing

    print(f"\n{'='*100}\n■ 基準3（1∧2 が2ビンテージ以上で同符号）と基準4（止率<=15%）の横断集計")
    print(f"   {'プール':<9}{'指標':<14}{'閾値':>6}{'1∧2を満たすV数':>16}{'基準3':>7}{'基準4(全V)':>11}")
    for v in sorted(out["aggregate"], key=lambda x: (x["pool"], x["indicator"], x["threshold"])):
        m4 = "判定不能" if v["c4_all"] is None else ("✓" if v["c4_all"] else "✗")
        m3 = "判定不能" if not v["judgeable"] else ("✓" if v["c3"] else "✗")
        print(f"   {v['pool']:<9}{v['indicator']:<14}{v['threshold']:>6}{v['n_ok12']:>16}"
              f"{m3:>7}{m4:>11}")
    print(f"\n■ 事前登録の基準1〜4をすべて満たす『指標×閾値×プール』: **{len(passing)}件**")
    for v in passing:
        print("   ", v["pool"], v["indicator"], v["threshold"], v["vint"])

    # ── どこまで惜しかったか（合否ではなく「外れ方」を残す）──────────────────
    summ = {}
    for pk in want:
        R = [r for r in out["results"] if r["pool"] == pk and r["prereg_indicator"]
             and r["judge"].get("c1") is not None]
        n = len(R)
        if not n:
            continue
        c1 = sum(1 for r in R if r["judge"]["c1"])
        c2 = sum(1 for r in R if r["judge"]["c2"])
        c4 = sum(1 for r in R if r["judge"]["c4"])
        ratios = [(r["judge"]["c1_ratio"], r["judge"]["c1_numer"], r["vintage"],
                   r["indicator"], r["threshold"]) for r in R if r["judge"]["c1_ratio"] is not None]
        ratios.sort(key=lambda x: -(x[0] or 0))
        gaps = [(r["judge"]["c2_gap"], r["vintage"], r["indicator"], r["threshold"]) for r in R]
        summ[pk] = {
            "n_cells": n,
            "c1_pass": c1, "c2_pass": c2, "c4_pass": c4,
            "c2_median_gap": round(statistics.median(g[0] for g in gaps), 4),
            "c2_gap_positive": sum(1 for g in gaps if g[0] > 0),
            "best_c1": [{"ratio": a, "numer": b, "vintage": c, "indicator": d, "threshold": e}
                        for a, b, c, d, e in ratios[:5]],
            "max_numer": max((r["judge"]["c1_numer"] or 0) for r in R),
        }
        print(f"\n■ 外れ方のまとめ（プール={pk}・事前登録の指標のみ・判定できたセル {n}個）")
        print(f"   基準1(左尾2倍かつ分子5社+) 合格 {c1}/{n} ／ 基準2(勝者を巻き込まない) {c2}/{n}"
              f" ／ 基準4(止率<=15%) {c4}/{n}")
        print(f"   基準2の中央値の差（止めた群 − 通過群）の中央値 = {summ[pk]['c2_median_gap']:+.4f}"
              f"（**正なら止めた側のほうが高い＝勝者を巻き込んでいる**）"
              f"／ 正だったセル {summ[pk]['c2_gap_positive']}/{n}")
        print(f"   恒久毀損の分子の最大 = {summ[pk]['max_numer']}社（基準1は5社以上を要求）")
        print(f"   左尾の濃縮が最も強かった5件（倍率, 分子）: "
              + ", ".join(f"{d}{e}@{c} {a}倍({b}社)" for a, b, c, d, e in ratios[:5]))
    out["summary"] = summ

    # 基準5（既存の関門で既に落ちる社を除く）は、1〜4が1件も通っていなければ**当てる先が無い**。
    # それでも「除いても姿が変わらない」ことは記録に値するので差分だけ出す。
    ch = [r for r in out["results"] if r["prereg_indicator"]
          and r["judge"].get("c1") is not None and r["judge_excl_shrink"].get("c1") is not None
          and (r["judge"]["c1"] != r["judge_excl_shrink"]["c1"]
               or r["judge"]["c2"] != r["judge_excl_shrink"]["c2"])]
    out["c5_cells_changed"] = len(ch)
    print(f"\n■ 基準5（『事業の収縮』で既に落ちる社を除く）: 除いても基準1・2の合否が変わるセルは "
          f"**{len(ch)}件**（1〜4が0件合格なので当てる先そのものが無い）")

    cc = crosscheck(out)
    out["crosscheck"] = cc
    if cc["ran"]:
        print(f"\n■ 別器との突合せ（{cc['other']}・プールを揃えて比較）: "
              f"{cc['cells']}セル / 食い違い **{cc['mismatches']}件** "
              f"／ 合格件数 本器 {cc['verdicts']['mine_pass']} vs 別器 {cc['verdicts']['other_pass']}")
        for x in cc["diffs"]:
            print("   ✗", x)

    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n■ 在庫: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
