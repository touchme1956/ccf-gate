# night/hist_val_market.py — (a)市場調整版バリュエーションと (b)市場水準そのものの遮断器 (2026-08-09新設)
#
# 事前登録 out/hist_valuation_prereg.json のうち、**この道具が担当する2つ**を測る:
#
#   (a) adj_pe_pct（自社PER ÷ S&P500実績PER の自己履歴分位）で同じ格子を回し、
#       素の pe_pct と**どう違うか**を出す。
#       ── なぜ要るか: 2009-2018 は倍率拡大期なので、素の自己分位は**構造的に全員高く出る**。
#          その交絡が結果を作っていないかを確かめるのが市場調整版の役目。事前登録の
#          indicators に『この交絡を外すために必須』と明記されている。
#
#   (b) spx_pe_pct（買値時点のS&P500実績PERの1871年以降の分位）＝**市場全体の遮断器**。
#       ── ここが構造的に難しい: spx_pe_pct は **社に依らない定数**なので、1ビンテージの中では
#          全社を止めるか全社を通すかのどちらかにしかならない。**銘柄横断の検定にならず、
#          時点横断の検定になる**。手元のビンテージは3つ＝ n=3 で検出力が無い。
#          → 補強として **1871年以降の任意の月を起点とする前方10/15/20年の配当込みリターン**
#            （out/sp500_tr_monthly.json）で同じ閾値を裁く。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【守っている作法】
#
# ■ 二重実装を作らない
#   セルの測り方（止めた群/通過群/判定不能の分け方・恒久毀損・等ウェイト・基準1/2/4の当て方）は
#   **night/hist_val_gate_test.py から import する**。分位の定義（中位順位法）は
#   **night/hist_valuation.py の pctile を import する**。ここで書き直さない
#   ——同じ台帳を見る二つの検査器が違うことを言い始める入口だから(v9.9.65)。
#
# ■ 事前登録を後から動かさない
#   起動時に hist_val_gate_test.check_prereg() を呼ぶ（格子と基準の文言の照合）。
#   格子は GRID_PCT / GRID_SPX をそのまま使い、**自分では定義しない**。
#
# ■ 事前登録に無い指標は「合否に使わない」と明示して分ける
#   CAPE型（実質10年平均利益で平滑した市場PER）は **診断であって検定ではない**。
#   『市場水準という概念が悪いのか、実績PERという物差しが悪いのか』を切り分けるために出すが、
#   合否には一切数えない（SENSITIVITY_ONLY と同じ扱い）。
#
# ■ 指数の左尾に -15%/年 の線を当てない（当たらないことを数字で示す）
#   恒久毀損 P(年率<=-15%) は**個別銘柄の線**。指数の10年年率はどの起点でもそこまで落ちない。
#   基準1は指数水準では**当てる先が無い**と書き、代わりに P(10年年率<0%) 等を
#   **記述統計として**併記する（基準を作り替えたのではない・作り替えられないことの報告）。
#
# ■ 重なる窓を数えすぎない
#   月次の前方10年窓は 119ヶ月ぶん重なる。全月を独立標本のように語ると n が10倍以上に水増しされる。
#   **重ならない部分標本（120ヶ月ごと・位相を12通りずらして全部出す）**を必ず併記する。
#
# 実行:
#   python3 night/hist_val_market.py                      # 全部
#   python3 night/hist_val_market.py --json out/hist_val_market.json
import argparse
import importlib.util
import json
import math
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, "night", path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


GT = _load("hist_val_gate_test", "hist_val_gate_test.py")   # セルの測り方・基準の当て方
HV = _load("hist_valuation", "hist_valuation.py")           # pctile（分位の定義）

VINTAGES = GT.VINTAGES
GRID_PCT = GT.GRID_PCT
GRID_SPX = GT.GRID_SPX
PERM = GT.PERM
WIN = GT.WIN

# 市場水準の検定で使う前方の窓（年）。10年が主・15/20年は感度
HORIZONS = (10, 15, 20)
# 分位を出すのに要求する自己履歴の最低（月）。1871-01 起点なので 1891年以降が対象になる
MKT_MIN_HIST = 240


# ═══════════════════════════════════════════════════════════════════════════
# (a) 市場調整版 vs 素
# ═══════════════════════════════════════════════════════════════════════════
def denom_diag(px_month, start="2009-01"):
    """**市場調整の分母が、その窓の中でどこに居たか**。

    adj_pe = 自社PER ÷ S&P500 PER なので、分母がその窓で高い位置に居る asof ほど
    adj_pe の自己分位は一律に押し下げられる。**銘柄の割高さではなく分母の位置**で
    止める社数が変わるので、ビンテージ間で市場調整版の強さが揃わない理由がここに出る。
    XBRL は2009年始まりなので自己履歴の窓もそこから（既定 start=2009-01）。
    """
    if not px_month:
        return None
    p = os.path.join(OUT, "sp500_pe_monthly.json")
    spx = {k: float(v) for k, v in json.load(open(p, encoding="utf-8"))["series"].items() if v}
    ks = [k for k in sorted(spx) if start <= k <= px_month]
    if not ks:
        return None
    v = [spx[k] for k in ks]
    now = spx[px_month]
    return {"window": [ks[0], ks[-1]], "months": len(ks),
            "spx_pe_now": round(now, 2),
            "spx_pe_median_in_window": round(statistics.median(v), 2),
            "spx_pe_max_in_window": round(max(v), 2),
            "pct_of_own_window": round(sum(1 for x in v if x < now) / len(v), 4),
            "months_pe_over_30": sum(1 for x in v if x > 30),
            "note": ("窓内で分母が高い位置に居るほど adj_pe の自己分位は一律に下がる。"
                     "2009年の利益消滅で S&P500 実績PERが70〜124まで跳ねた月が窓に残っており、"
                     "その残り方（窓に占める割合）がビンテージごとに違う")}


def part_a(pool_want=("quality", "full")):
    res = {"why": "2009-2018は倍率拡大期。素の自己分位が構造的に高く出る交絡を外す",
           "vintages": {}, "cells": [], "flips": [], "diagnostics": []}
    for y in VINTAGES:
        d, rows = GT.load_vintage(y)
        years = d["join"]["modal_years"]
        P = GT.pools(rows)
        drop, drop_src, drop_exact = GT.shrink_flags(y)
        vin = {"asof": d["asof"], "years": years,
               "spx_pe": rows[0].get("spx_pe") if rows else None,
               "spx_pe_pct": rows[0].get("spx_pe_pct") if rows else None,
               "denominator": denom_diag(rows[0].get("px_month") if rows else None),
               "pools": {}}
        for pk in pool_want:
            rws = P[pk]
            if not rws:
                continue
            # ── A1 交絡の実測: 素の分位はどれだけ上へ寄っているか ────────────────
            raw = [r["pe_pct"] for r in rws if r.get("pe_pct") is not None]
            adj = [r["adj_pe_pct"] for r in rws if r.get("adj_pe_pct") is not None]
            both = [(r["pe_pct"], r["adj_pe_pct"]) for r in rws
                    if r.get("pe_pct") is not None and r.get("adj_pe_pct") is not None]
            diag = {
                "n_pool": len(rws),
                "cov_raw": round(len(raw) / len(rws), 4),
                "cov_adj": round(len(adj) / len(rws), 4),
                "raw_median": round(statistics.median(raw), 4) if raw else None,
                "adj_median": round(statistics.median(adj), 4) if adj else None,
                "raw_mean": round(statistics.fmean(raw), 4) if raw else None,
                "adj_mean": round(statistics.fmean(adj), 4) if adj else None,
                "raw_ge80": round(sum(1 for x in raw if x >= 0.80) / len(raw), 4) if raw else None,
                "adj_ge80": round(sum(1 for x in adj if x >= 0.80) / len(adj), 4) if adj else None,
                "raw_ge90": round(sum(1 for x in raw if x >= 0.90) / len(raw), 4) if raw else None,
                "adj_ge90": round(sum(1 for x in adj if x >= 0.90) / len(adj), 4) if adj else None,
                "n_both": len(both),
                "spearman": spearman([a for a, _ in both], [b for _, b in both]) if both else None,
                "mean_shift": (round(statistics.fmean([a - b for a, b in both]), 4)
                               if both else None),
            }
            vin["pools"][pk] = diag
            res["diagnostics"].append({"vintage": y, "pool": pk, **diag})

            # ── A2 同じ格子を両方に当てる（測り方は gate_test をそのまま使う）──────
            for key, label in (("pe_pct", "素の自己相対PER分位"),
                               ("adj_pe_pct", "市場調整PER分位")):
                for thr in GRID_PCT:
                    ev = GT.evaluate(rws, key, "pct", None, thr, years)
                    jd = GT.judge(ev)
                    ev5 = GT.evaluate(rws, key, "pct", None, thr, years, drop=drop)
                    jd5 = GT.judge(ev5)
                    res["cells"].append({
                        "vintage": y, "pool": pk, "indicator": key, "label": label,
                        "threshold": thr,
                        "n_stop": ev["n_stop"], "stop_rate_pool": ev["stop_rate_pool"],
                        "coverage": ev["coverage"],
                        "stop_median": ev["stopped"].get("median"),
                        "stop_ew": ev["stopped"].get("ew_cagr"),
                        "stop_pperm": ev["stopped"].get("p_perm"),
                        "stop_nperm": ev["stopped"].get("n_perm"),
                        "pass_median": ev["passed"].get("median"),
                        "pass_ew": ev["passed"].get("ew_cagr"),
                        "pass_pperm": ev["passed"].get("p_perm"),
                        "base_median": ev["base"].get("median"),
                        "base_pperm": ev["base"].get("p_perm"),
                        "base_nperm": ev["base"].get("n_perm"),
                        "c1": jd.get("c1"), "c1_ratio": jd.get("c1_ratio"),
                        "c1_numer": jd.get("c1_numer"), "c1_status": jd.get("c1_status"),
                        "c2": jd.get("c2"), "c2_gap": jd.get("c2_gap"),
                        "c4": jd.get("c4"),
                        "c1_excl_shrink": jd5.get("c1"), "c2_excl_shrink": jd5.get("c2"),
                        "shrink_exact": drop_exact,
                    })

            # ── A3 対にして見る: 素だけが止める社 / 調整版だけが止める社 ────────────
            for thr in GRID_PCT:
                onlyraw, onlyadj, bothstop, neither = [], [], [], []
                for r in rws:
                    a, b = r.get("pe_pct"), r.get("adj_pe_pct")
                    if a is None or b is None:
                        continue
                    sa, sb = a >= thr, b >= thr
                    (bothstop if (sa and sb) else onlyraw if sa else
                     onlyadj if sb else neither).append(r)
                res["flips"].append({
                    "vintage": y, "pool": pk, "threshold": thr,
                    "n_both_stop": len(bothstop), "n_only_raw": len(onlyraw),
                    "n_only_adj": len(onlyadj), "n_neither": len(neither),
                    "both_stop": GT.stats(bothstop, years),
                    "only_raw": GT.stats(onlyraw, years),
                    "only_adj": GT.stats(onlyadj, years),
                    "neither": GT.stats(neither, years),
                })
        res["vintages"][str(y)] = vin
    return res


def spearman(a, b):
    """順位相関。**この2つの分位が同じ順序を言っているか**を見るだけの道具。"""
    n = len(a)
    if n < 3:
        return None
    def rank(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk
    ra, rb = rank(a), rank(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 4) if den else None


# ═══════════════════════════════════════════════════════════════════════════
# (b) 市場水準そのものの遮断器
# ═══════════════════════════════════════════════════════════════════════════
def part_b_vintages():
    """手元の3ビンテージへ当てる。**銘柄横断ではなく時点横断の検定になる**ことを数字で示す。"""
    out = {"n_vintages": len(VINTAGES), "rows": [], "grid": list(GRID_SPX), "verdict_cells": []}
    for y in VINTAGES:
        d, rows = GT.load_vintage(y)
        years = d["join"]["modal_years"]
        P = GT.pools(rows)
        bench = d["join"].get("benchmark") or {}
        spx_pct = rows[0].get("spx_pe_pct") if rows else None
        rec = {"vintage": y, "asof": d["asof"], "years": years,
               "spx_pe": rows[0].get("spx_pe") if rows else None,
               "spx_pe_pct": spx_pct,
               "spy_cagr": bench.get("tr_cagr"),
               "pool_stats": {k: GT.stats(v, years) for k, v in P.items()},
               "stopped_by": {str(t): (spx_pct is not None and spx_pct >= t) for t in GRID_SPX}}
        out["rows"].append(rec)
    # 閾値ごとに「止めたビンテージ / 通したビンテージ」を並べる（n=3）
    for t in GRID_SPX:
        st = [r for r in out["rows"] if r["stopped_by"][str(t)]]
        pa = [r for r in out["rows"] if not r["stopped_by"][str(t)]]
        def agg(rs, key):
            xs = [r[key] for r in rs if r.get(key) is not None]
            return round(statistics.median(xs), 4) if xs else None
        out["verdict_cells"].append({
            "threshold": t,
            "n_stop": len(st), "n_pass": len(pa),
            "stopped_vintages": [r["vintage"] for r in st],
            "passed_vintages": [r["vintage"] for r in pa],
            "stop_spy_median": agg(st, "spy_cagr"), "pass_spy_median": agg(pa, "spy_cagr"),
            "stop_qual_median": (round(statistics.median(
                [r["pool_stats"]["quality"]["median"] for r in st]), 4) if st else None),
            "pass_qual_median": (round(statistics.median(
                [r["pool_stats"]["quality"]["median"] for r in pa]), 4) if pa else None),
            "judgeable": bool(st and pa),
            "note": ("1ビンテージの中では spx_pe_pct は**社に依らない定数**なので全社を止めるか"
                     "全社を通すかしかない＝銘柄横断のセル検定は定義できない（gate_test で"
                     "『判定不能』と出るのはこのため）。ここは時点の標本 n=3 の比較"),
        })
    return out


def load_market():
    p = os.path.join(OUT, "sp500_tr_monthly.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def mk_add(mk, n):
    y, m = int(mk[:4]), int(mk[5:])
    t = (y * 12 + m - 1) + n
    return f"{t // 12}-{t % 12 + 1:02d}"


def build_market_panel(mkt, spx, use_cape=False):
    """月ごとに (市場PERの as-of 分位, 前方H年の配当込み年率) の表を作る。

    ■ look-ahead を構造で防ぐ: 分位は **その月より前**の値だけで測る（在庫 hist_valuation.py が
      spx_pe_pct を出すときとまったく同じ規則＝pctile を import している）。
    ■ 実質も出す（CPIで割る）。名目だけだと1970年代の高インフレ期が『高リターン』に見える。
    """
    price, cpi, tr = mkt["price"], mkt.get("cpi") or {}, mkt["tr"]
    ser = dict(spx)
    if use_cape:
        ser = build_cape(price, spx, cpi)
    ks = sorted(k for k in ser if k in tr)
    rows = []
    for i, k in enumerate(ks):
        hist = [ser[x] for x in ks[:i]]
        if len(hist) < MKT_MIN_HIST:
            continue
        pct = HV.pctile(hist, ser[k])
        rec = {"month": k, "val": round(ser[k], 4), "pct": None if pct is None else round(pct, 4),
               "hist_months": len(hist)}
        for H in HORIZONS:
            e = mk_add(k, H * 12)
            if e in tr and tr[k] > 0:
                rec[f"fwd{H}"] = round((tr[e] / tr[k]) ** (1.0 / H) - 1.0, 4)
                if k in cpi and e in cpi and cpi[k] > 0:
                    real = (tr[e] / tr[k]) * (cpi[k] / cpi[e])
                    rec[f"fwd{H}_real"] = round(real ** (1.0 / H) - 1.0, 4)
        rows.append(rec)
    return rows


def build_cape(price, spx, cpi):
    """**事前登録外の診断**: 実質10年平均利益で平滑した市場PER（Shiller CAPE 相当）。

    利益は E = 価格 ÷ 実績PER で復元できる（同じ出所なので基準は揃う）。
    CPI で実質化して10年平均を取り、実質価格を割る。合否には一切使わない。
    """
    e = {k: price[k] / spx[k] for k in spx if k in price and spx[k] > 0}
    ks = sorted(k for k in e if k in cpi and cpi[k] > 0)
    base = cpi[ks[-1]]
    re_ = {k: e[k] * base / cpi[k] for k in ks}          # 実質利益
    rp = {k: price[k] * base / cpi[k] for k in ks}       # 実質価格
    out = {}
    for i, k in enumerate(ks):
        if i < 120:
            continue
        w = [re_[x] for x in ks[i - 119:i + 1]]
        m = statistics.fmean(w)
        if m > 0:
            out[k] = rp[k] / m
    return out


def mkt_stats(rows, key):
    """群の姿。**DCAの視点**なので『各月に等額で買ったときの終価倍率の平均』も出す
    ——中央値は『1回だけ買ったとき』の話で、毎月買う運用とは別の問いに答えている。"""
    xs = [r[key] for r in rows if r.get(key) is not None]
    if not xs:
        return {"n": 0}
    H = int(key.replace("fwd", "").replace("_real", ""))
    mult = [(1 + x) ** H for x in xs]
    ew = statistics.fmean(mult) ** (1.0 / H) - 1.0
    q = sorted(xs)
    def qt(p):
        i = min(len(q) - 1, max(0, int(round(p * (len(q) - 1)))))
        return round(q[i], 4)
    return {
        "n": len(xs),
        "median": round(statistics.median(xs), 4),
        "mean": round(statistics.fmean(xs), 4),
        "ew_dca": round(ew, 4),
        "p10": qt(0.10), "p25": qt(0.25), "p75": qt(0.75), "p90": qt(0.90),
        "min": round(min(xs), 4), "max": round(max(xs), 4),
        "p_neg": round(sum(1 for x in xs if x < 0) / len(xs), 4),
        "n_neg": sum(1 for x in xs if x < 0),
        "p_lt5": round(sum(1 for x in xs if x < 0.05) / len(xs), 4),
        "n_lt5": sum(1 for x in xs if x < 0.05),
        "p_perm15": round(sum(1 for x in xs if x <= PERM) / len(xs), 4),
        "n_perm15": sum(1 for x in xs if x <= PERM),
        "p_win15": round(sum(1 for x in xs if x >= WIN) / len(xs), 4),
    }


def part_b_market(mkt, spx, since=None, use_cape=False, label=""):
    rows = build_market_panel(mkt, spx, use_cape=use_cape)
    if since:
        rows = [r for r in rows if r["month"] >= since]
    out = {"label": label, "since": since, "indicator": "cape_pct(事前登録外・診断)" if use_cape
           else "spx_pe_pct(事前登録)", "prereg_indicator": not use_cape,
           "n_months": len(rows), "first": rows[0]["month"] if rows else None,
           "last": rows[-1]["month"] if rows else None, "cells": [], "nonoverlap": []}
    for H in HORIZONS:
        key = f"fwd{H}"
        avail = [r for r in rows if r.get(key) is not None]
        if not avail:
            continue
        base = mkt_stats(avail, key)
        base_real = mkt_stats(avail, f"{key}_real")
        for t in GRID_SPX:
            st = [r for r in avail if r["pct"] is not None and r["pct"] >= t]
            pa = [r for r in avail if r["pct"] is not None and r["pct"] < t]
            s, p = mkt_stats(st, key), mkt_stats(pa, key)
            cell = {
                "horizon": H, "threshold": t,
                "n_avail": len(avail), "n_stop": len(st), "n_pass": len(pa),
                "stop_rate": round(len(st) / len(avail), 4) if avail else None,
                "base": base, "base_real": base_real,
                "stopped": s, "passed": p,
                "stopped_real": mkt_stats(st, f"{key}_real"),
                "passed_real": mkt_stats(pa, f"{key}_real"),
                # 事前登録の基準のうち、**指数水準でも意味を保つのは基準2だけ**
                "c2": (None if not (s.get("n") and p.get("n"))
                       else s["median"] <= p["median"]),
                "c2_gap": (None if not (s.get("n") and p.get("n"))
                           else round(s["median"] - p["median"], 4)),
                "c1_applicable": False,
                "c1_note": ("恒久毀損 P(年率<=-15%) は個別銘柄の線。指数の"
                            f"{H}年年率は全{len(avail)}起点中 {base['n_perm15']}件しか該当せず、"
                            "基準1は指数水準では**当てる先が無い**（基準を作り替えたのではない）"),
                "c4_stop_rate": round(len(st) / len(avail), 4) if avail else None,
                "worst_stopped": sorted(
                    ({"m": r["month"], "pct": r["pct"], "fwd": r[key]} for r in st),
                    key=lambda x: x["fwd"])[:5],
                "best_stopped": sorted(
                    ({"m": r["month"], "pct": r["pct"], "fwd": r[key]} for r in st),
                    key=lambda x: -x["fwd"])[:5],
            }
            out["cells"].append(cell)
        # ── 重ならない部分標本（位相を12通りずらして全部出す）────────────────
        for t in GRID_SPX:
            phases = []
            for ph in range(12):
                sub = avail[ph::H * 12]
                st = [r for r in sub if r["pct"] is not None and r["pct"] >= t]
                pa = [r for r in sub if r["pct"] is not None and r["pct"] < t]
                if not st or not pa:
                    phases.append({"phase": ph, "n_sub": len(sub), "n_stop": len(st),
                                   "judgeable": False})
                    continue
                s, p = mkt_stats(st, key), mkt_stats(pa, key)
                phases.append({"phase": ph, "n_sub": len(sub), "n_stop": len(st),
                               "judgeable": True,
                               "stop_median": s["median"], "pass_median": p["median"],
                               "c2": s["median"] <= p["median"]})
            ok = [x for x in phases if x["judgeable"]]
            out["nonoverlap"].append({
                "horizon": H, "threshold": t,
                "n_indep_windows": round(len(avail) / (H * 12), 1),
                "phases_judgeable": len(ok), "phases_c2_true": sum(1 for x in ok if x["c2"]),
                "median_n_stop": (round(statistics.median([x["n_stop"] for x in ok]), 1)
                                  if ok else None),
                "phases": phases,
            })
    out["panel_sample"] = rows[::60]
    return out


def bottom_diagnostic(mkt, spx):
    """**実績PERは市場の底で跳ね上がる**（利益が先に消えるから）。

    「その時点で市場全体が高すぎるなら買わない」を実績PERの分位で実装すると、
    **不況の底＝最良の買値**で発火しないか。事実で確かめる。
    同じ月の CAPE型（実質10年平均利益で平滑）を並べて、**概念が悪いのか物差しが悪いのか**を切り分ける。
    """
    rows = build_market_panel(mkt, spx)
    cape = {r["month"]: r for r in build_market_panel(mkt, spx, use_cape=True)}
    have = [r for r in rows if r.get("fwd10") is not None and r["pct"] is not None]
    if not have:
        return {}
    q = sorted(r["fwd10"] for r in have)
    def qt(xs, p):
        s = sorted(xs)
        return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]
    top10 = qt(q, 0.90)
    hi = [r for r in have if r["pct"] >= 0.95]
    hi_f = sorted(r["fwd10"] for r in hi)

    def row(r):
        c = cape.get(r["month"]) or {}
        # 止めた群の中でこの起点がどれくらい良かったか（**止めた群の内側の順位**で見る）。
        # 前方10年がまだ無い月（直近10年）は順位も出さない——**空欄を0と読まない**（ルール7）
        f = r.get("fwd10")
        rank = (sum(1 for x in hi_f if x < f) / len(hi_f)) if (hi_f and f is not None) else None
        return {"m": r["month"], "pe": r["val"], "pe_pct": r["pct"],
                "cape": c.get("val"), "cape_pct": c.get("pct"),
                "fwd10": r.get("fwd10"),
                "rank_in_stopped": None if rank is None else round(rank, 3)}

    crisis = [row(r) for r in rows if "2008-06" <= r["month"] <= "2010-06"]
    return {
        "n": len(have),
        "top_decile_fwd10_line": round(top10, 4),
        "n_pct95": len(hi),
        "n_pct95_and_top_decile": sum(1 for r in hi if r["fwd10"] >= top10),
        "stopped_fwd10_quartiles": {"p25": round(qt(hi_f, .25), 4),
                                    "median": round(qt(hi_f, .50), 4),
                                    "p75": round(qt(hi_f, .75), 4),
                                    "max": round(hi_f[-1], 4)} if hi_f else None,
        # ── 金融危機の窓を1ヶ月ずつ並べる（遮断器がいつ閉じ、その起点が何を返したか）──
        "crisis_2008_2010": crisis,
        "n_crisis_stopped_at_090": sum(1 for x in crisis
                                       if x["pe_pct"] is not None and x["pe_pct"] >= 0.90),
        "worst_10y_starts": [row(r) for r in sorted(have, key=lambda x: x["fwd10"])[:10]],
        "best_10y_starts": [row(r) for r in sorted(have, key=lambda x: -x["fwd10"])[:10]],
        "landmarks": [row(rows[i]) for i, r in enumerate(rows)
                      if r["month"] in ("1929-08", "1932-06", "1949-06", "1966-01",
                                        "1982-07", "1999-03", "2000-03", "2009-03",
                                        "2013-06", "2015-06", "2018-06", "2026-03")],
        "note": ("実績GAAP PER は分子(価格)が落ちるより先に分母(利益)が消えるので、"
                 "**不況の底で分位が最大になる**。市場水準の遮断器をこの物差しで作ると"
                 "『最良の買値で買付を止める』側に働く。CAPE型を並べると同じ月で分位が"
                 "大きく違い、**概念ではなく物差しの問題**であることが見える"),
    }


def decile_profile(mkt, spx, since="1926-01", use_cape=False, H=10):
    """**閾値を1本選ぶ前に、形を見る**。買値時点の分位を10等分して前方リターンの中央値を並べる。

    遮断器の合否は閾値の話だが、そもそも『分位が上がるほど前方が下がる』という単調な形が
    無ければ、どの閾値を選んでも意味が無い。格子を回す前に見るべき絵（記述統計・合否に不使用）。
    """
    rows = [r for r in build_market_panel(mkt, spx, use_cape=use_cape)
            if r["month"] >= since and r.get(f"fwd{H}") is not None and r["pct"] is not None]
    out = []
    for i in range(10):
        lo, hi = i / 10.0, (i + 1) / 10.0
        g = [r for r in rows if (lo <= r["pct"] < hi) or (i == 9 and r["pct"] >= 1.0)]
        if not g:
            out.append({"decile": i + 1, "n": 0})
            continue
        s = mkt_stats(g, f"fwd{H}")
        out.append({"decile": i + 1, "range": [lo, hi], "n": s["n"], "median": s["median"],
                    "ew_dca": s["ew_dca"], "p10": s["p10"], "p90": s["p90"],
                    "p_neg": s["p_neg"], "min": s["min"]})
    return {"since": since, "horizon": H, "n": len(rows),
            "indicator": "cape_pct(事前登録外)" if use_cape else "spx_pe_pct(事前登録)",
            "deciles": out}


# ── (b-4) 毎月積立にこの遮断器を掛けたら終価はどうなるか ──────────────────────
def dca_sim(mkt, spx, since="1926-01", use_cape=False, cash_rate=0.0):
    """**この台帳の運用はDCA（毎月定額）**なので、遮断器の値打ちは終価で出るのが本筋。

    規則: 止めた月は買わずに現金へ積む → 遮断器が開いた月に**溜めた現金を全部投じる**。
    最後まで開かなければ現金のまま残る（＝終価に現金として算入する）。
    現金の利回りは既定 0%（短期金利の系列を持っていないため）。**0%は遮断器に不利**なので、
    『いくらの現金利回りがあれば引き分けになるか』を二分法で解いて併記する
    ——持っていないデータを推測で置かず、**必要条件のほうを答えにする**。
    """
    rows = build_market_panel(mkt, spx, use_cape=use_cape)
    tr = mkt["tr"]
    rows = [r for r in rows if r["month"] >= since and r["month"] in tr and r["pct"] is not None]
    if len(rows) < 240:
        return {"ran": False, "why": f"起点が {len(rows)}ヶ月しかない"}
    last = rows[-1]["month"]
    end_tr = tr[last]

    def run(thr, cr):
        """閾値 thr で止め、現金利回り cr で待つ。thr>1 なら一度も止まらない＝常時投資。"""
        units = cash = 0.0
        n_stop = 0
        mrate = (1 + cr) ** (1 / 12.0) - 1
        for r in rows:
            cash *= (1 + mrate)
            cash += 1.0                       # 今月の入金
            if r["pct"] >= thr:               # 遮断器が閉じている＝買わない
                n_stop += 1
                continue
            units += cash / tr[r["month"]]    # 溜めた現金をまとめて投じる
            cash = 0.0
        return {"terminal": units * end_tr + cash, "n_stop": n_stop,
                "stop_rate": round(n_stop / len(rows), 4), "cash_left": round(cash, 2)}

    base = run(2.0, cash_rate)                 # 閾値2.0＝絶対に止まらない＝常時投資
    out = {"ran": True, "since": since, "last": last, "n_months": len(rows),
           "indicator": "cape_pct(事前登録外)" if use_cape else "spx_pe_pct(事前登録)",
           "cash_rate": cash_rate,
           "always_invested_terminal": round(base["terminal"], 1), "cells": []}
    for thr in GRID_SPX:
        g = run(thr, cash_rate)
        ratio = g["terminal"] / base["terminal"]
        # 引き分けに要る現金利回り。**単調（現金利回りが高いほど待つのが得）**なので二分法でよい。
        #
        # ⚠ 答えは3通りに割れる。**どれなのかを必ず `breakeven_case` に書く**（2026-08-09是正）。
        #   初版は二分法の下限を cash_rate(=0) に置いたまま、遮断器が0%で既に勝っている場合も
        #   そのまま `be=0.0` を返していた。**その 0.0 は「計算した分岐点」ではなく探索の下限そのもの**
        #   ——真の分岐点は0%以下（負の現金利回りでも勝つ）かもしれず、下限で頭打ちになっただけ。
        #   しかも当時は be が非Noneのとき note を None にしていたので、出力だけ見ると
        #   「計算結果の0%」と「既定値の残り」が見分けられなかった。
        #   **もっともらしい0は空欄より有害**（この台帳がルール7で繰り返し戒めてきた型）。
        #   実測では全6セル（spx_pe_pct/cape_pct × 3閾値）がこの『下限で既に勝ち』の側だった。
        be = be_case = be_note = None
        if g["terminal"] >= base["terminal"]:
            # 下限の現金利回りで既に常時投資以上＝この向きに分岐点は存在しない。
            # 「0%が要る」ではなく「要らない」なので、数値は置かず None にして理由を書く。
            be_case = "no_gap_at_floor"
            be_note = (f"現金 {cash_rate:.2%}（＝探索の下限）でも既に常時投資を上回る"
                       f"（常時投資比 {ratio:.4f}）＝この向きに分岐点は無い")
        elif run(thr, 0.20)["terminal"] >= base["terminal"]:
            lo, hi_ = cash_rate, 0.20
            for _ in range(50):
                mid = (lo + hi_) / 2
                if run(thr, mid)["terminal"] < base["terminal"]:
                    lo = mid
                else:
                    hi_ = mid
            be, be_case = round(hi_, 4), "solved"
            be_note = f"現金が年 {be:.2%} 以上あれば引き分け"
        else:
            # 上限20%でも届かなければ「そんな金利は無い」と書く（推測で埋めない）。
            be_case, be_note = "unreachable", "現金が年20%でも常時投資に届かない"
        out["cells"].append({
            "threshold": thr, "n_stop": g["n_stop"], "stop_rate": g["stop_rate"],
            "terminal": round(g["terminal"], 1),
            "vs_always": round(ratio, 4),
            "cost_pct": round((ratio - 1) * 100, 2),
            "breakeven_cash_rate": be,          # None のときは case が理由を持つ
            "breakeven_case": be_case,          # solved / no_gap_at_floor / unreachable
            "breakeven_note": be_note,          # **常に文字列**（null にしない）
            "cash_left_uninvested": g["cash_left"],
        })
    return out


def dca_rolling(mkt, spx, years=30, use_cape=False, cash_rate=0.0):
    """**1本の道の終価は n=1**。1926年以降を30年の積立窓で転がして**分布**にする。

    ⚠ 100年の一括シミュレーションは終価が**最初期の入金に支配される**
      （1926年の1は今日 約5万倍・2016年の1は約2倍）。つまり実質「1926-1950年の検定」に
      なってしまう。30年窓なら『これから20-30年積む人』の問いに形が近い。
    """
    rows = [r for r in build_market_panel(mkt, spx, use_cape=use_cape)
            if r["pct"] is not None and r["month"] in mkt["tr"]]
    tr = mkt["tr"]
    n = years * 12
    res = {"years": years, "cash_rate": cash_rate,
           "indicator": "cape_pct(事前登録外)" if use_cape else "spx_pe_pct(事前登録)",
           "cells": []}

    def term(win, thr, cr):
        units = cash = 0.0
        mrate = (1 + cr) ** (1 / 12.0) - 1
        for r in win:
            cash = cash * (1 + mrate) + 1.0
            if r["pct"] >= thr:
                continue
            units += cash / tr[r["month"]]
            cash = 0.0
        return units * tr[win[-1]["month"]] + cash

    wins = [rows[i:i + n] for i in range(0, len(rows) - n + 1)]
    for thr in GRID_SPX:
        ratios, stops = [], []
        for w in wins:
            b = term(w, 2.0, cash_rate)
            if b <= 0:
                continue
            ratios.append(term(w, thr, cash_rate) / b)
            stops.append(sum(1 for r in w if r["pct"] >= thr) / len(w))
        if not ratios:
            continue
        q = sorted(ratios)
        def qt(p):
            return round(q[min(len(q) - 1, max(0, int(round(p * (len(q) - 1)))))], 4)
        res["cells"].append({
            "threshold": thr, "n_windows": len(ratios),
            "n_indep_windows": round(len(ratios) / n, 1),
            "median_ratio": round(statistics.median(ratios), 4),
            "mean_ratio": round(statistics.fmean(ratios), 4),
            "p10": qt(.10), "p25": qt(.25), "p75": qt(.75), "p90": qt(.90),
            "min": qt(0.0), "max": qt(1.0),
            "p_better": round(sum(1 for x in ratios if x > 1) / len(ratios), 4),
            "mean_stop_rate": round(statistics.fmean(stops), 4),
            "first_window_start": wins[0][0]["month"], "last_window_end": wins[-1][-1]["month"],
        })
    return res


# ═══════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="市場調整版と市場水準の遮断器を事前登録どおり検定する")
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val_market.json"))
    ap.add_argument("--pool", choices=("quality", "full", "both"), default="both")
    a = ap.parse_args()

    pre = GT.check_prereg()
    print("■ 事前登録と照合 OK（格子・基準の文言が当時のまま）:", pre["path"], pre["registered"])
    print(f"  格子: 分位 {GRID_PCT} / 市場水準 {GRID_SPX}")

    want = ("quality", "full") if a.pool == "both" else (a.pool,)
    out = {"generated": "2026-08-09", "tool": "night/hist_val_market.py", "prereg": pre,
           "grid": {"pct": list(GRID_PCT), "spx": list(GRID_SPX)},
           "horizons": list(HORIZONS), "mkt_min_hist_months": MKT_MIN_HIST}

    # ── (a) ───────────────────────────────────────────────────────────────
    print(f"\n{'='*104}\n■ (a) 市場調整版 adj_pe_pct と 素の pe_pct")
    A = part_a(want)
    out["part_a"] = A
    print(f"\n  【A0】市場調整の**分母**がその窓のどこに居たか（止める社数が銘柄でなく分母で動く）")
    print(f"     {'V':>5}{'窓':>20}{'月数':>6}{'分母(asof)':>11}{'窓の中央':>10}{'窓の最大':>10}"
          f"{'窓内分位':>10}{'PER>30の月':>11}")
    for y in VINTAGES:
        dn = (A["vintages"][str(y)] or {}).get("denominator")
        if not dn:
            continue
        print(f"     {y:>5}{dn['window'][0]+'〜'+dn['window'][1]:>20}{dn['months']:>6}"
              f"{dn['spx_pe_now']:>11.2f}{dn['spx_pe_median_in_window']:>10.2f}"
              f"{dn['spx_pe_max_in_window']:>10.2f}{dn['pct_of_own_window']:>10.1%}"
              f"{dn['months_pe_over_30']:>11}")

    print(f"\n  【A1】交絡の実測——素の自己分位はどれだけ上へ寄っているか")
    print(f"     {'V':>5}{'プール':<9}{'n':>5}{'素:中央':>9}{'調:中央':>9}{'素>=.80':>9}"
          f"{'調>=.80':>9}{'素>=.90':>9}{'調>=.90':>9}{'順位相関':>10}{'平均差':>8}")
    for g in A["diagnostics"]:
        print(f"     {g['vintage']:>5}{g['pool']:<9}{g['n_pool']:>5}"
              f"{g['raw_median']:>9.3f}{g['adj_median']:>9.3f}"
              f"{g['raw_ge80']:>9.1%}{g['adj_ge80']:>9.1%}"
              f"{g['raw_ge90']:>9.1%}{g['adj_ge90']:>9.1%}"
              f"{(g['spearman'] if g['spearman'] is not None else float('nan')):>10.3f}"
              f"{g['mean_shift']:>+8.3f}")

    for pk in want:
        print(f"\n  【A2】同じ格子を両方に当てる（プール={pk}）")
        print(f"     {'V':>5}{'指標':<12}{'閾値':>6}{'止めた':>7}{'止率':>7}"
              f"{'止:中央':>9}{'止:等W':>9}{'止:毀損':>11}{'通:中央':>9}{'通:毀損':>9}"
              f"  {'1':>2}{'2':>2}{'4':>2}")
        for c in A["cells"]:
            if c["pool"] != pk:
                continue
            if c["stop_median"] is None or c["pass_median"] is None:
                print(f"     {c['vintage']:>5}{c['indicator']:<12}{c['threshold']:>6}"
                      f"{c['n_stop']:>7}   —— 判定不能")
                continue
            mk = lambda b: "✓" if b else "✗"
            print(f"     {c['vintage']:>5}{c['indicator']:<12}{c['threshold']:>6}"
                  f"{c['n_stop']:>7}{c['stop_rate_pool']:>7.1%}"
                  f"{c['stop_median']:>+9.1%}{c['stop_ew']:>+9.1%}"
                  f"{c['stop_pperm']:>6.1%}({c['stop_nperm']:>2}){c['pass_median']:>+9.1%}"
                  f"{c['pass_pperm']:>9.1%}  {mk(c['c1']):>2}{mk(c['c2']):>2}{mk(c['c4']):>2}")

    print(f"\n  【A3】対にして見る——素だけが止める社 / 調整版だけが止める社（中央値・等ウェイト）")
    print(f"     {'V':>5}{'プール':<9}{'閾値':>6}{'両方':>6}{'素だけ':>7}{'調だけ':>7}"
          f"{'両方:中央':>11}{'素だけ:中央':>13}{'調だけ:中央':>13}{'どちらも通:中央':>17}")
    for f in A["flips"]:
        def m(s):
            return f"{s['median']:+.1%}" if s.get("n_ret") else "—"
        print(f"     {f['vintage']:>5}{f['pool']:<9}{f['threshold']:>6}"
              f"{f['n_both_stop']:>6}{f['n_only_raw']:>7}{f['n_only_adj']:>7}"
              f"{m(f['both_stop']):>11}{m(f['only_raw']):>13}{m(f['only_adj']):>13}"
              f"{m(f['neither']):>17}")

    # ── (b) ───────────────────────────────────────────────────────────────
    print(f"\n{'='*104}\n■ (b-1) 市場水準の遮断器を手元の3ビンテージへ当てる（**時点の標本 n=3**）")
    B1 = part_b_vintages()
    out["part_b_vintages"] = B1
    print(f"     {'V':>5}{'asof':>12}{'窓':>6}{'S&P500 PER':>12}{'1871以降分位':>13}"
          f"{'SPY年率':>9}{'質実証:中央':>12}{'>=.80':>7}{'>=.90':>7}{'>=.95':>7}")
    for r in B1["rows"]:
        q = r["pool_stats"]["quality"]
        print(f"     {r['vintage']:>5}{r['asof']:>12}{r['years']:>6.1f}{r['spx_pe']:>12.2f}"
              f"{r['spx_pe_pct']:>13.4f}{r['spy_cagr']:>9.1%}{q['median']:>+12.1%}"
              f"{('止' if r['stopped_by']['0.8'] else '通'):>7}"
              f"{('止' if r['stopped_by']['0.9'] else '通'):>7}"
              f"{('止' if r['stopped_by']['0.95'] else '通'):>7}")
    for c in B1["verdict_cells"]:
        print(f"     閾値 {c['threshold']}: 止めたビンテージ {c['stopped_vintages']} "
              f"(SPY中央 {c['stop_spy_median']}) / 通した {c['passed_vintages']} "
              f"(SPY中央 {c['pass_spy_median']}) → 判定可能={c['judgeable']}")

    mkt = load_market()
    spx = {k: float(v) for k, v in
           json.load(open(os.path.join(OUT, "sp500_pe_monthly.json"), encoding="utf-8"))["series"].items()}
    if not mkt:
        print("\n⚠ out/sp500_tr_monthly.json が無い → (b-2) 補強は走らない。"
              "先に `python3 night/fetch_sp500_tr.py` を回すこと")
        out["part_b_market"] = {"ran": False}
    else:
        out["market_src"] = {"file": "out/sp500_tr_monthly.json",
                             "generated": mkt.get("generated"),
                             "basis": mkt.get("basis"),
                             "verify_pe": mkt.get("verify_pe"),
                             "crosscheck_yahoo": mkt.get("crosscheck_yahoo")}
        print(f"\n{'='*104}\n■ (b-2) 補強: 1871年以降の任意の月を起点とする前方リターンで同じ閾値を裁く")
        cc = mkt.get("crosscheck_yahoo") or {}
        print(f"  TR系列の検算: 本器 {cc.get('mine_cagr')} vs Yahoo ^SP500TR "
              f"{cc.get('yahoo_sp500tr_cagr')}（{cc.get('years')}年・差 {cc.get('diff_pt')}pt）")
        runs = []
        runs.append(part_b_market(mkt, spx, since=None, label="全期間(1891-)"))
        runs.append(part_b_market(mkt, spx, since="1926-01", label="1926年以降"))
        runs.append(part_b_market(mkt, spx, since="1926-01", use_cape=True,
                                  label="1926年以降・CAPE型(事前登録外の診断)"))
        out["part_b_market"] = runs
        for R in runs:
            print(f"\n  ── {R['label']}  指標={R['indicator']}  "
                  f"起点 {R['first']}〜{R['last']}  {R['n_months']}ヶ月")
            print(f"     {'H':>3}{'閾値':>6}{'起点数':>7}{'止めた':>7}{'止率':>7}"
                  f"{'止:中央':>9}{'止:DCA':>9}{'止:P(<0)':>10}{'通:中央':>9}{'通:DCA':>9}"
                  f"{'通:P(<0)':>10}{'基準2':>7}{'-15%該当':>10}")
            for c in R["cells"]:
                s, p = c["stopped"], c["passed"]
                if not s.get("n") or not p.get("n"):
                    print(f"     {c['horizon']:>3}{c['threshold']:>6}{c['n_avail']:>7}"
                          f"{c['n_stop']:>7}   —— 判定不能（片側が空）")
                    continue
                print(f"     {c['horizon']:>3}{c['threshold']:>6}{c['n_avail']:>7}"
                      f"{c['n_stop']:>7}{c['stop_rate']:>7.1%}"
                      f"{s['median']:>+9.1%}{s['ew_dca']:>+9.1%}{s['p_neg']:>10.1%}"
                      f"{p['median']:>+9.1%}{p['ew_dca']:>+9.1%}{p['p_neg']:>10.1%}"
                      f"{('✓' if c['c2'] else '✗'):>7}{c['base']['n_perm15']:>10}")
            print(f"     重ならない部分標本（位相12通り）:")
            for x in R["nonoverlap"]:
                print(f"       H={x['horizon']} 閾値{x['threshold']}: "
                      f"独立な窓 約{x['n_indep_windows']}本 / 判定できた位相 "
                      f"{x['phases_judgeable']}/12 / そのうち基準2を満たす "
                      f"{x['phases_c2_true']} / 止めた起点の中央 {x['median_n_stop']}")

        print(f"\n{'='*104}\n■ (b-3) 実績PERは市場の底で跳ね上がる——遮断器が最良の買値で発火しないか")
        bd = bottom_diagnostic(mkt, spx)
        out["bottom_diagnostic"] = bd
        q = bd["stopped_fwd10_quartiles"]
        print(f"  分位>=0.95 で止めた起点 {bd['n_pct95']}ヶ月の前方10年: "
              f"p25 {q['p25']:+.1%} / 中央 {q['median']:+.1%} / p75 {q['p75']:+.1%} / "
              f"最良 {q['max']:+.1%}")
        print(f"\n  【金融危機の窓】遮断器(0.90)が閉じた月 = {bd['n_crisis_stopped_at_090']}ヶ月")
        print(f"     {'月':>9}{'実績PER':>10}{'PER分位':>9}{'CAPE':>8}{'CAPE分位':>10}"
              f"{'前方10年':>10}{'止めた群での順位':>18}")
        for x in bd["crisis_2008_2010"]:
            f10 = f"{x['fwd10']:+.1%}" if x["fwd10"] is not None else "—"
            rk = f"{x['rank_in_stopped']:.0%}" if x["rank_in_stopped"] is not None else "—"
            cp = f"{x['cape']:.2f}" if x["cape"] else "—"
            cpp = f"{x['cape_pct']:.4f}" if x["cape_pct"] is not None else "—"
            print(f"     {x['m']:>9}{x['pe']:>10.2f}{x['pe_pct']:>9.4f}{cp:>8}{cpp:>10}"
                  f"{f10:>10}{rk:>18}")
        print(f"\n  【節目の月】実績PER分位 と CAPE分位 が同じ月で何を言うか")
        print(f"     {'月':>9}{'実績PER':>10}{'PER分位':>9}{'CAPE':>8}{'CAPE分位':>10}{'前方10年':>10}")
        for x in bd["landmarks"]:
            f10 = f"{x['fwd10']:+.1%}" if x["fwd10"] is not None else "—"
            cp = f"{x['cape']:.2f}" if x["cape"] else "—"
            cpp = f"{x['cape_pct']:.4f}" if x["cape_pct"] is not None else "—"
            print(f"     {x['m']:>9}{x['pe']:>10.2f}{x['pe_pct']:>9.4f}{cp:>8}{cpp:>10}{f10:>10}")
        print(f"  最悪の10年の起点: " + ", ".join(
            f"{x['m']}({x['fwd10']:+.1%}/PER分位{x['pe_pct']:.2f}/CAPE分位"
            f"{(x['cape_pct'] if x['cape_pct'] is not None else float('nan')):.2f})"
            for x in bd["worst_10y_starts"][:5]))
        print(f"  最良の10年の起点: " + ", ".join(
            f"{x['m']}({x['fwd10']:+.1%}/PER分位{x['pe_pct']:.2f}/CAPE分位"
            f"{(x['cape_pct'] if x['cape_pct'] is not None else float('nan')):.2f})"
            for x in bd["best_10y_starts"][:5]))

        print(f"\n{'='*104}\n■ (b-3.5) 閾値を選ぶ前に形を見る——買値時点の分位10等分と前方10年")
        out["deciles"] = []
        for cape in (False, True):
            dp = decile_profile(mkt, spx, since="1926-01", use_cape=cape)
            out["deciles"].append(dp)
            print(f"\n  ── 指標={dp['indicator']}  1926年以降 {dp['n']}ヶ月")
            print(f"     {'分位':>8}{'n':>6}{'中央':>9}{'DCA':>9}{'p10':>9}{'p90':>9}"
                  f"{'P(<0)':>8}{'最悪':>9}")
            for x in dp["deciles"]:
                if not x.get("n"):
                    print(f"     {x['decile']:>8}{0:>6}   ——")
                    continue
                print(f"     {x['range'][0]:.1f}-{x['range'][1]:.1f}{x['n']:>6}"
                      f"{x['median']:>+9.1%}{x['ew_dca']:>+9.1%}{x['p10']:>+9.1%}"
                      f"{x['p90']:>+9.1%}{x['p_neg']:>8.1%}{x['min']:>+9.1%}")

        print(f"\n{'='*104}\n■ (b-4) 毎月積立にこの遮断器を掛けたら終価はどうなるか"
              f"（止めた月は現金へ積み、開いた月にまとめて投じる）")
        out["dca"] = []
        for cape in (False, True):
            s = dca_sim(mkt, spx, since="1926-01", use_cape=cape)
            out["dca"].append(s)
            if not s.get("ran"):
                continue
            print(f"\n  ── 指標={s['indicator']}  {s['since']}〜{s['last']}  "
                  f"{s['n_months']}ヶ月・現金利回り {s['cash_rate']:.0%}")
            print(f"     常時投資の終価 = {s['always_invested_terminal']:,.0f}（毎月1を投じた場合）")
            print(f"     {'閾値':>6}{'止めた月':>9}{'止率':>7}{'終価':>14}{'常時投資比':>11}"
                  f"{'差':>9}{'引き分けに要る現金利回り':>26}")
            for c in s["cells"]:
                # 数値が無いときは **どちらの意味の無しか**を短く出す（0.00% と書かない）
                be = (f"{c['breakeven_cash_rate']:.2%}" if c["breakeven_cash_rate"] is not None
                      else ("要らない(下限で既に勝ち)"
                            if c["breakeven_case"] == "no_gap_at_floor"
                            else "年20%でも届かない"))
                print(f"     {c['threshold']:>6}{c['n_stop']:>9}{c['stop_rate']:>7.1%}"
                      f"{c['terminal']:>14,.0f}{c['vs_always']:>11.3f}"
                      f"{c['cost_pct']:>+8.1f}%{be:>26}")
        print(f"\n  ⚠ 上の終価は**一本の道 n=1**で、しかも最初期の入金に支配される"
              f"（1926年の1は約5万倍・2016年の1は約2倍）。30年の積立窓で転がして分布にする:")
        out["dca_rolling"] = []
        for cape in (False, True):
            rr = dca_rolling(mkt, spx, years=30, use_cape=cape)
            out["dca_rolling"].append(rr)
            print(f"\n  ── 指標={rr['indicator']}  30年の積立窓")
            print(f"     {'閾値':>6}{'窓数':>7}{'独立窓':>8}{'平均止率':>9}{'比:中央':>9}"
                  f"{'比:平均':>9}{'p10':>8}{'p90':>8}{'最悪':>8}{'最良':>8}{'勝率':>8}")
            for c in rr["cells"]:
                print(f"     {c['threshold']:>6}{c['n_windows']:>7}{c['n_indep_windows']:>8.1f}"
                      f"{c['mean_stop_rate']:>9.1%}{c['median_ratio']:>9.3f}"
                      f"{c['mean_ratio']:>9.3f}{c['p10']:>8.3f}{c['p90']:>8.3f}"
                      f"{c['min']:>8.3f}{c['max']:>8.3f}{c['p_better']:>8.1%}")

    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n■ 在庫: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
