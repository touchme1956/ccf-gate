#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事前登録v2の**到達可能性**の事前計算（結果は一切見ない）。

なぜこの器が要るか
------------------
事前登録v1は、結果を見る前から**達成不能な基準**を持っていた——基準1が
「恒久毀損の分子5社以上」を要求するのに、判定プール(質実証)の恒久毀損の実数は
2013年 0社 / 2015年 3社 / 2018年 9社しか無かった。**毀損社を先に知って止める
『神の遮断器』でも通らない**。原因は指標のデータ要件（自己履歴36ヶ月＋XBRL 2009開始）が
母集団を大型survivorへ絞り、**仮説が要求する履歴が、基準が数える事象を消していた**こと。

だから v2 では、事前登録を書く前に必ずこの器を回す:
  (a) プールの大きさ
  (b) **結果事象の実数**（＝分子の天井）
  (c) 指標の被覆と、格子の各閾値での**止率**（＝止める社数の天井）
  (d) (b)(c) から **神の遮断器の上限**を出し、各基準が各ビンテージで到達可能かを判定

**この器は指標と結果を絶対に突き合わせない。**周辺分布だけを出す（下の GUARD を見よ）。
突き合わせ＝検定は事前登録をコミットした後、別の器で一度だけ行う。

使い方:
  python3 night/hist_val_prereg_v2_reach.py            # out/hist_val_prereg_v2_reach.json
  python3 night/hist_val_prereg_v2_reach.py --quiet
"""
import argparse
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

import hist_valuation as HV   # noqa: E402  価格の取得・月キーは採取器のものをそのまま使う（二重実装を作らない）

VINTAGES = (2013, 2015, 2018)

# ---- 事前に固定した格子（丸い数字。データを見て決めていない） -------------------
GRID_DD = (-0.20, -0.30, -0.40, -0.50)      # 自己の5年高値からの下落率
GRID_MOM = (0.00, -0.05)                    # 5年トレーリング年率（従指標）

# ---- 結果指標（すべて周辺分布として数えるだけ） --------------------------------
def is_loss(tr):        return tr < 0            # 元本割れ（主指標）
def is_perm(tr):        return tr <= -0.15       # 恒久毀損（従指標）
# 不採用の候補（下の "rejected" に実数を残す）。指数−5pt未満は**左尾ではなく半々**なので
# 遮断器の物差しにならない——事象が多い指標を選ぶのは curve-fitting に近い
def is_lag5(tr, bench):  return bench is not None and tr < bench - 0.05

STOP_CAP = 0.15         # 基準4（止率の上限）。v1 と同じ＝ゴールポストを動かさない
LIFT = 2.0              # 基準1（止めた群の事象率 ÷ ベース）。v1 と同じ
MIN_NUM = 5             # 基準1（分子の下限）。v1 と同じ

# ---- 検問②③（2026-08-10 の教訓を器にした・2026-09-23 追加・todo prereg_v3_checklist） ----
#   ② **各セルで実効的に要求される倍率**——need = max(MIN_NUM, ceil(LIFT×base×K)) の MIN_NUM が小さい K で拘束すると、
#      登録した LIFT=2.0 倍が静かに高い線へ化ける（実測: dd5≤−0.40 の2013は 2.86倍、−0.50 は 7.85/5.52倍＝到達不能）。
#      事前登録は『到達不能』には旗を立てたが『線が変わっている』には立てなかった。
#   ③ **登録した手続きの検出力**——真の lift が L のとき、止めた K 社の事象数を Binomial(K, min(1, L×base)) と置いて
#      P(事象数 ≥ need) を出す（v2 は事後に測って 0.512 と判った。先に判っていれば標本設計を変えられた）。
#   ⚠ ここも**指標と結果を突き合わせない**——使うのは K（止めた社数）・ベース率・need だけ＝周辺分布。
POWER_LIFTS = (2.0, 3.0)


def binom_sf(k_min, n, p):
    """P(X >= k_min), X~Binomial(n, p)。"""
    import math
    if k_min <= 0:
        return 1.0
    if k_min > n or p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k_min, n + 1))


def check23(K, n_ev, base):
    """② 実効倍率と拘束条件 ／ ③ 真の lift ごとの検出力。"""
    import math
    lift_need = math.ceil(LIFT * (base or 0) * K)
    need = max(MIN_NUM, lift_need)
    exp_base = (base or 0) * K
    eff = round(need / exp_base, 2) if exp_base > 0 else None
    ceil_num = min(n_ev, K)
    power = {}
    for L in POWER_LIFTS:
        pw = binom_sf(need, K, min(1.0, L * (base or 0))) if ceil_num >= need else 0.0
        power[f"真のlift{L:.1f}倍"] = round(pw, 3)
    return {"必要分子": need,
            "拘束": "MIN_NUM" if MIN_NUM > lift_need else "LIFT",
            "実効倍率": eff,
            "登録倍率から化けた": bool(eff is not None and eff > LIFT * 1.2),
            "検出力": power}


DD_WIN = 60             # 5年高値
DD_MIN_OBS = 48         # 60ヶ月中48ヶ月以上の観測を要求
DD3_WIN, DD3_MIN_OBS = 36, 30


def month_sub(mk, n):
    """月キー(YYYY-MM)から n ヶ月前の月キー。"""
    y, m = int(mk[:4]), int(mk[5:7])
    t = y * 12 + (m - 1) - n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def window_months(m0, n):
    return [month_sub(m0, i) for i in range(n - 1, -1, -1)]


def drawdown(adj, m0, win, min_obs):
    """自己の高値からの下落率。

    **adjclose(配当込み)の比**で測る。理由は2つ——
     (1) 前方リターンと同じ系列なので「基準の違う二つを割る」型を踏まない
     (2) 素の close だと高配当銘柄が配当落ちのぶんだけ機械的に『落ちた』側へ寄る
    adjclose は今日までの分割・配当で遡及調整されるが、**調整は乗法なので二点間の比は不変**
    （この台帳が retro_per_asof の是正で確認済み: リターン=比 は無事・水準=PER だけが壊れる）。
    """
    if not adj:
        return None, "px_no_adj"
    ms = window_months(m0, win)
    vals = [(m, adj[m]) for m in ms if m in adj and adj[m] and adj[m] > 0]
    if len(vals) < min_obs:
        return None, f"obs<{min_obs}({len(vals)})"
    if ms[0] not in adj:
        # 窓の先頭が無い＝5年の履歴が本当にあるか怪しい。上場が窓の途中なら除く
        first = vals[0][0]
        if first > month_sub(m0, win - 7):      # 窓の先頭から半年以内に始まっていなければ不可
            return None, f"hist_starts_{first}"
    cur = adj.get(m0)
    if not cur or cur <= 0:
        return None, "no_px_at_asof"
    peak = max(v for _, v in vals)
    if peak <= 0:
        return None, "bad_peak"
    return cur / peak - 1.0, None


def mom(adj, m0, win=60):
    a, b = adj.get(month_sub(m0, win)), adj.get(m0)
    if not a or not b or a <= 0:
        return None
    return (b / a) ** (12.0 / win) - 1.0


def pools_for(rows):
    """P_wide = 質実証 ∧ 前方リターンあり ∧ window_full（**指標のデータ要件を課さない**）
    P_set  = さらに analysis_set（＝自己相対分位がある＝XBRL自己履歴36ヶ月）。v1 の判定プール。
    """
    wide = [r for r in rows
            if r.get("quality") and r.get("tr_cagr") is not None and r.get("window_full")]
    return {"P_wide": wide, "P_set": [r for r in wide if r.get("analysis_set")]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val_prereg_v2_reach.json"))
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--augment", action="store_true",
                    help="価格を取り直さず、既存の出力の K・ベース率から検問②③だけを足して書き戻す")
    a = ap.parse_args()

    if a.augment:
        # 価格キャッシュ(out/_histval_cache)は .gitignore＝容器の中にしか無い。取り直せない容器で全体を回すと
        # 被覆0の出力で既存の記録を潰すので、②③に要る K とベース率だけを既存の出力から読む。
        res = json.load(open(a.json, encoding="utf-8"))
        n = 0
        for y, v in res["vintages"].items():
            for pn, p in v["pools"].items():
                for t_key, c in p["dd5_止率"].items():
                    for k, r in c["セル別到達可能性"].items():
                        r["検問②③"] = check23(c["止めた社数"], p["事象"][k], p["ベース率"][k])
                        n += 1
                        if not a.quiet:
                            q = r["検問②③"]
                            print(f"{y} {pn} dd5<={t_key} {k}: K={c['止めた社数']} 必要{q['必要分子']}"
                                  f"（拘束 {q['拘束']}）実効{q['実効倍率']}倍"
                                  f"{' ★化けた' if q['登録倍率から化けた'] else ''} 検出力 {q['検出力']}")
        res["検問②③_追記"] = "2026-09-23 --augment（価格は取り直していない・K とベース率は元の出力のまま）"
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n-> {a.json}（{n}セルに検問②③を追記）")
        return

    res = {"generated": "2026-08-09",
           "tool": "night/hist_val_prereg_v2_reach.py",
           "GUARD": "この器は指標と結果を突き合わせない。出すのは周辺分布と神の遮断器の上限だけ",
           "grid": {"dd": list(GRID_DD), "mom": list(GRID_MOM)},
           "criteria_params": {"stop_cap": STOP_CAP, "lift": LIFT, "min_numerator": MIN_NUM},
           "vintages": {}}

    for y in VINTAGES:
        p = os.path.join(OUT, f"hist_val_{y}.json")
        d = json.load(open(p, encoding="utf-8"))
        rows = d["rows"]
        P = pools_for(rows)
        v = {"asof": d["asof"], "src_tool_rev": d.get("tool_rev"),
             "benchmark": (d.get("join") or {}).get("benchmark", {}).get("tr_cagr"),
             "pools": {}}

        for pname, pool in P.items():
            N = len(pool)
            tr = [r["tr_cagr"] for r in pool]
            ev = {"元本割れ": sum(1 for x in tr if is_loss(x)),
                  "恒久毀損": sum(1 for x in tr if is_perm(x))}
            base = {k: (n / N if N else None) for k, n in ev.items()}
            bench_tr = (d.get("join") or {}).get("benchmark", {}).get("tr_cagr")
            n_lag = sum(1 for x in tr if is_lag5(x, bench_tr))
            rejected = {"指数−5pt未満": {"実数": n_lag,
                                      "率": round(n_lag / N, 4) if N else None,
                                      "不採用の理由": "左尾ではなく半々に近い＝遮断器の物差しにならない"}}

            # --- 指標の被覆と止率（結果には触れていない） ---
            dd, dd3, mo, why = {}, {}, {}, {}
            for r in pool:
                px = HV.fetch_px(r["ticker"], offline=True) or {}
                adj = px.get("adj") or {}
                m0 = r.get("px_month")
                if not m0:
                    why["no_px_month"] = why.get("no_px_month", 0) + 1
                    continue
                x, w = drawdown(adj, m0, DD_WIN, DD_MIN_OBS)
                if x is None:
                    k = (w or "?").split("(")[0]
                    why[k] = why.get(k, 0) + 1
                else:
                    dd[r["ticker"]] = x
                x3, _ = drawdown(adj, m0, DD3_WIN, DD3_MIN_OBS)
                if x3 is not None:
                    dd3[r["ticker"]] = x3
                m = mom(adj, m0)
                if m is not None:
                    mo[r["ticker"]] = m

            def cells(vals, grid, sense):
                out = {}
                for t in grid:
                    k = sum(1 for x in vals.values() if (x <= t if sense == "le" else x >= t))
                    rate = k / N if N else None
                    out[f"{t:+.2f}"] = {
                        "止めた社数": k, "止率": round(rate, 4) if rate is not None else None,
                        "基準4(止率<=%.0f%%)" % (STOP_CAP * 100): (rate is not None and rate <= STOP_CAP),
                    }
                return out

            dd_cells = cells(dd, GRID_DD, "le")
            mo_cells = cells(mo, GRID_MOM, "le")

            # --- セル別の到達可能性（**本当の拘束条件はここ**） -------------------
            # 閾値 t で止まるのは K社。分子の天井は min(事象数, K)。
            # 基準1は「分子>=MIN_NUM」かつ「止めた群の事象率>=LIFT*ベース」＝
            # 必要分子 = ceil(LIFT * ベース * K)。両方を満たせるかを結果を見ずに判定する。
            import math
            for t_key, c in dd_cells.items():
                K = c["止めた社数"]
                c["セル別到達可能性"] = {}
                for k, n_ev in ev.items():
                    ceil_num = min(n_ev, K)
                    need = max(MIN_NUM, math.ceil(LIFT * (base[k] or 0) * K))
                    c["セル別到達可能性"][k] = {
                        "分子の天井": ceil_num, "必要分子": need,
                        "到達可能": bool(K > 0 and ceil_num >= need),
                    }
                    c["セル別到達可能性"][k]["検問②③"] = check23(K, n_ev, base[k])

            # --- 神の遮断器の上限 ---
            # 止率の上限 STOP_CAP のもとで、事象社だけを狙って止めたときの分子の天井
            cap_n = int(N * STOP_CAP)
            oracle = {}
            for k, n_ev in ev.items():
                ceil_num = min(n_ev, cap_n)
                # 止率の上限内で全部が事象なら事象率=1.0 → lift = 1/base
                reach_num = ceil_num >= MIN_NUM
                reach_lift = (base[k] is not None and base[k] > 0 and (1.0 / base[k]) >= LIFT)
                oracle[k] = {
                    "事象の実数": n_ev, "止率上限での止め枠": cap_n,
                    "分子の天井": ceil_num,
                    "基準1の分子(>=%d)到達可能" % MIN_NUM: reach_num,
                    "基準1のlift(>=%.1f倍)到達可能" % LIFT: reach_lift,
                    "到達可能": bool(reach_num and reach_lift),
                }

            v["pools"][pname] = {
                "N": N,
                "中央値": round(statistics.median(tr), 4) if tr else None,
                "最悪": round(min(tr), 4) if tr else None,
                "事象": ev, "ベース率": {k: round(x, 4) for k, x in base.items()},
                "不採用の候補": rejected,
                "指標の被覆": {"dd5": len(dd), "dd3": len(dd3), "mom5": len(mo),
                             "dd5_被覆率": round(len(dd) / N, 4) if N else None},
                "被覆できない理由": why,
                "dd5_止率": dd_cells, "mom5_止率": mo_cells,
                "神の遮断器": oracle,
            }
        res["vintages"][str(y)] = v

    json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if not a.quiet:
        for y, v in res["vintages"].items():
            print(f"\n=== {y} (asof {v['asof']}, SPY {v['benchmark']:+.1%}) ===")
            for pn, p in v["pools"].items():
                print(f" {pn}: N={p['N']} 中央{p['中央値']:+.2%} 最悪{p['最悪']:+.1%} "
                      f"元本割れ={p['事象']['元本割れ']}({p['ベース率']['元本割れ']:.1%}) "
                      f"恒久毀損={p['事象']['恒久毀損']}({p['ベース率']['恒久毀損']:.2%})")
                print(f"   dd5被覆 {p['指標の被覆']['dd5']}/{p['N']} "
                      f"({p['指標の被覆']['dd5_被覆率']:.0%})  欠測理由 {p['被覆できない理由']}")
                print(f"   不採用候補 指数−5pt未満={p['不採用の候補']['指数−5pt未満']['実数']}"
                      f"({p['不採用の候補']['指数−5pt未満']['率']:.1%})")
                for t, c in p["dd5_止率"].items():
                    ok4 = c[f"基準4(止率<={int(STOP_CAP*100)}%)"]
                    r1 = c["セル別到達可能性"]["元本割れ"]
                    r2 = c["セル別到達可能性"]["恒久毀損"]
                    print(f"   dd5<={t}: 止{c['止めた社数']}({c['止率']:.1%}) 基準4={'✓' if ok4 else '✗'}"
                          f" | 元本割れ 天井{r1['分子の天井']}/必要{r1['必要分子']}"
                          f"={'✓' if r1['到達可能'] else '✗'}"
                          f" | 恒久毀損 天井{r2['分子の天井']}/必要{r2['必要分子']}"
                          f"={'✓' if r2['到達可能'] else '✗'}")
                for k, o in p["神の遮断器"].items():
                    print(f"   神の遮断器[{k}]: 事象{o['事象の実数']} 枠{o['止率上限での止め枠']} "
                          f"→ 分子天井{o['分子の天井']} 到達可能={o['到達可能']}")
    print(f"\n-> {a.json}")


if __name__ == "__main__":
    main()
