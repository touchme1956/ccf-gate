#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**自己相対バリュエーション**を、退場社込みの母集団で検定し直す（2013年・2026-08-10新設）

  ※ night/hist_val2_delisted.py は**別の器**（並走セッションが dd5 を同じ母集団へ当てるもの）。
    こちらは v1 の自己相対指標（pe_pct/ps_pct/pfcf_pct/adj_pe_pct/pe_z/ps_z）が対象。
    母集団と price-only の作法は同じなので、結論は互いの独立な傍証になる。

なぜこの器が要るか
------------------
v1 も night/hist_val2_outcome.py も、母集団が **「2013年に上場していて、今日もティッカーが
引ける社」** だった。左尾を作る種類（買収・破産・登録抹消）はそこから丸ごと消えている。
実測（retro_delisted.py + retro_delisted_secpx.py）——質実証プールの真の母集団は **563社**で、
ティッカー経由で見えていたのは 374社だけ。**189社が最初から居ない。**

  ⇒ 「自己相対は効かない」が、**左尾が切れた母集団の上でしか確かめられていない**。
     この器は退場社を SEC原本から戻した母集団で数え直し、戻せなかった分は**幅**で明示する。

基準の混在を踏まない（この台帳が7回踏んでいる型）
------------------------------------------------
退場社の価格は **合併対価（SEC原本）÷ 10-K Item5 の高安表** ＝ **price-only（配当なし）**。
hist_val の tr_cagr は **adjclose＝配当込み**。**割ってはいけない。**
→ **全社を price-only に揃える**（survivor も Yahoo close で採り直した px_cagr）。
   指標だけを hist_val から借りる。

指標は退場社に**原理的に**当てられない（だから bounds で裁く）
--------------------------------------------------------------
自己相対の分位は asof までの**月次**価格の自己履歴（36ヶ月以上）を要る。退場社はまさに
Yahoo が履歴ごと消している社で、月足が取れない（実測 404 / 記号が MUTUALFUND として再利用）。
並走セッションが dd5 について**live で再確認**している——8社を叩いて取れたのは1社の1ヶ月だけ。
10-K Item5 の四半期高安で代用する道はあるが、**survivor=月次終値 / 退場=四半期の高安**という
**基準の違う二つ**を作る（しかも四半期高安のほうが幅が広く、仮説に有利な向きへ偏る）。
だから代用しない。**判らないものは判らないと書き、両極端で挟む。**

生の PER で代用する道も測った上で捨てた（記録）
----------------------------------------------
「自己相対は無理でも生の PER なら退場社にも作れるのでは」——作れるが、**proxy として弱い**。
実測（両方が取れる社での順位相関 ρ(生PER, pe_pct)）: 2013 **+0.437** / 2015 +0.473 / 2018 +0.703。
生PER 上位1/4 のうち実際に pe_pct>=0.9 なのは 2013 で **35%** しかない。
この検定のビンテージは 2013＝**最も proxy が弱い年**なので、90社ぶんの SEC 採取をして
弱い代理を差し込むより、**挟み込みの幅を正直に出すほうが強い**と判断した。
（この数字は `--proxy` で毎回測り直せる。次に来た人が同じ検算をやり直さないため。）

打ち切りの扱い（欠測をゼロと読むな・絶対のルール7）
--------------------------------------------------
価格を復元できなかった 130社は「損していない」ではなく **判らない**。
下限（一社も元本割れしない）・中間（**非M&Aの打ち切りだけ**元本割れ）・上限（全部元本割れ）の
**3つの読み**で全部の数字を出す。点推定は出さない。

窓の扱い（正直に）
------------------
survivor は全社 13.09年で揃うが、**退場社は退場日で窓が終わる**（実測 0.8〜13.0年）。
  ・**主結果指標の『元本割れ』は符号の検定**（CAGR<0 ⟺ 終値<始値）なので**窓の長さに依らない**。
    退場社を混ぜても意味が壊れない——これがこの検定で元本割れを主指標にする実務上の理由。
  ・**中央値CAGRと等ウェイト買い持ちは窓に依存する**ので混合プールでは主張に使わず、
    窓が揃った survivor だけの部分集合で別に出す。

実行:
  python3 night/hist_val2_selfrel_delisted.py
  python3 night/hist_val2_selfrel_delisted.py --proxy     # 生PERがproxyになるかの再検算だけ
"""
import argparse
import json
import math
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

from hist_val_rev import load_vintage_checked, seen_revs                     # noqa: E402  版の検問
from hist_val2_outcome import (GRID_PCT, GRID_Z, INDICATORS, Z_MIN_MONTHS,   # noqa: E402
                               LIFT, MIN_NUM, STOP_CAP, check_prereg)

VINTAGE = 2013
# M&A 退場は「相手が現金で買った」＝価格が存在する型。非M&A（破産・登録抹消・上場基準抵触・
# 提出停止）は**そもそも合併対価が無い**＝左尾を作る型。中間の読みはここを使う。
NON_MA = {"bankruptcy", "deregistered", "listing_deficiency", "stopped_filing", None}


def spearman(xs, ys):
    def rk(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[s[k]] = avg
            i = j + 1
        return r
    a, b = rk(xs), rk(ys)
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(len(xs)))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return round(num / den, 4) if den else None


def proxy_quality():
    """**生PERは自己相対分位の代理になるか**を、両方が取れる社で毎回測り直す。

    代理で代用する誘惑は必ず来る（退場社には自己履歴が無いから）。だから
    「代用しない」という判断の根拠を、文章ではなく数字として器に残す。
    """
    o = {}
    for y in (2013, 2015, 2018):
        d = json.load(open(os.path.join(OUT, f"hist_val_{y}.json"), encoding="utf-8"))
        R = [r for r in d["rows"] if r.get("quality") and r.get("tr_cagr") is not None
             and r.get("window_full") and r.get("pe_pct") is not None and r.get("pe") is not None]
        if len(R) < 20:
            continue
        xs = [r["pe"] for r in R]
        thr = statistics.quantiles(xs, n=4)[2]
        top = [r for r in R if r["pe"] >= thr]
        o[y] = {"n": len(R), "rho_rawpe_vs_pe_pct": spearman(xs, [r["pe_pct"] for r in R]),
                "top_quartile_rawpe_precision_for_pe_pct_ge_090":
                    round(sum(1 for r in top if r["pe_pct"] >= 0.9) / len(top), 4),
                "median_rawpe_when_pe_pct_ge_090":
                    round(statistics.median([r["pe"] for r in R if r["pe_pct"] >= 0.9]), 2),
                "median_rawpe_otherwise":
                    round(statistics.median([r["pe"] for r in R if r["pe_pct"] < 0.9]), 2)}
    return o


def readings(measured_loss, n_measured, censored):
    """打ち切りの3つの読み。**点推定を出さない**（ルール7）。"""
    n_cens = len(censored)
    n_nonma = sum(1 for r in censored if r.get("exit_kind") in NON_MA)
    N = n_measured + n_cens
    return {
        "下限(打ち切りは元本割れしない)": {"n_loss": measured_loss, "N": N,
                                "rate": round(measured_loss / N, 4)},
        "中間(非M&Aの打ち切りだけ元本割れ)": {"n_loss": measured_loss + n_nonma, "N": N,
                                   "rate": round((measured_loss + n_nonma) / N, 4),
                                   "n_nonma": n_nonma},
        "上限(打ち切りは全部元本割れ)": {"n_loss": measured_loss + n_cens, "N": N,
                              "rate": round((measured_loss + n_cens) / N, 4)},
    }


def required_extremeness(n_stop, n_loss_stop, base_rate, N):
    """**この器でいちばん効く数字。**

    「未測定社を止められたら結論は変わるのでは」に、極端さを数で答える。
    追加で m 社を止め、そのうち f 社が元本割れなら、基準1は
        (L + f) / (n + m) >= 2*base
    最も有利なのは f = m（止めた未測定社が**全部**元本割れ）。そのとき必要な m は
        m >= (2*base*n - L) / (1 - 2*base)          … 2*base < 1 のとき
    これを、**指標が実際に測れた社での的中率**と並べて読む。
    100%の的中を仮定して初めて届くなら、それは仮説ではなく願望である。
    """
    need = LIFT * base_rate
    hit = (n_loss_stop / n_stop) if n_stop else None
    if need >= 1.0:
        return {"impossible": True,
                "why": f"必要な止めた群の元本割れ率 {need:.1%} が100%を超える＝どんな指標でも不可能",
                "measured_hit_rate": None if hit is None else round(hit, 4)}
    m = (need * n_stop - n_loss_stop) / (1.0 - need)
    m = max(0.0, m)
    cap = int(N * STOP_CAP)
    return {"impossible": False,
            "need_stop_loss_rate": round(need, 4),
            "measured_hit_rate": None if hit is None else round(hit, 4),
            "extra_stops_all_of_which_must_be_losses": math.ceil(m),
            "room_under_stop_cap": max(0, cap - n_stop),
            "fits_under_stop_cap": bool(n_stop + math.ceil(m) <= cap),
            "also_needs_numerator_ge_5": bool(n_loss_stop + math.ceil(m) >= MIN_NUM)}


def main():
    ap = argparse.ArgumentParser(description="自己相対を退場社込みの母集団で検定し直す（2013・price-only）")
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val2_selfrel_delisted.json"))
    ap.add_argument("--proxy", action="store_true", help="生PERがproxyになるかの再検算だけ出す")
    a = ap.parse_args()

    pq = proxy_quality()
    if a.proxy:
        print("■ 生PERは自己相対分位の代理になるか（両方取れる社で実測）")
        for y, v in pq.items():
            print(f"   {y}: n={v['n']}  ρ={v['rho_rawpe_vs_pe_pct']:+.3f}  "
                  f"生PER上位1/4の適合率 {v['top_quartile_rawpe_precision_for_pe_pct_ge_090']:.0%}"
                  f"  （pe_pct>=0.9 の生PER中央 {v['median_rawpe_when_pe_pct_ge_090']} vs "
                  f"それ以外 {v['median_rawpe_otherwise']}）")
        print("\n   ⇒ 2013 は ρ=+0.44・適合率35%＝**最も弱い年**。代用しない。")
        return 0

    pre = check_prereg()
    print("■ 事前登録と照合 OK（格子・指標=v1 ／ 基準・主結果指標=v2）")

    dl = json.load(open(os.path.join(OUT, f"retro_delisted_secpx_{VINTAGE}.json"), encoding="utf-8"))
    # **在庫の版の検問を通す**（json.load で直に読むと、2026-08-09に踏んだ
    #  「2013だけr2・2015/2018がr1のまま検定7本が回っていた」型を自分で再発させる）
    hv = load_vintage_checked(VINTAGE)
    ind = {str(r["cik"]): r for r in hv["rows"] if r.get("cik")}

    Q = [r for r in dl["rows"] if r.get("quality") and r.get("kind") != "対象外"]
    for r in Q:
        r["_ind"] = ind.get(str(r["cik"]))
    meas = [r for r in Q if r.get("px_cagr") is not None]
    cens = [r for r in Q if r.get("px_cagr") is None]
    surv = [r for r in meas if r["status"] == "survivor"]
    rest = [r for r in meas if r["status"] != "survivor"]
    n_loss_meas = sum(1 for r in meas if r["px_cagr"] < 0)
    base_readings = readings(n_loss_meas, len(meas), cens)
    n_seen = sum(1 for r in Q if r.get("_ind") and r["_ind"].get("window_full")
                 and r["_ind"].get("tr_cagr") is not None)

    print(f"\n■ 母集団（2013年・質実証・**CIKで同定＝ティッカー生存に依らない**）")
    print(f"   全体 {len(Q)}社 ＝ survivor {len(surv)} ＋ 退場を原本で復元 {len(rest)} ＋ 打ち切り {len(cens)}")
    print(f"   （比較）v1/v2 が見ていた母集団 P_wide = **{n_seen}社**＝ティッカーが引けた survivor だけ")
    print(f"   基準: {dl['basis']}")
    print(f"\n■ ベース元本割れ率の3つの読み（点推定は出さない・ルール7）")
    for k, v in base_readings.items():
        print(f"   {k:<32} {v['n_loss']:>4}/{v['N']} = **{v['rate']:.1%}**")

    cov = {}
    for key, kind, hk, _ in INDICATORS:
        if kind == "mkt":
            continue
        n = 0
        for r in Q:
            i = r.get("_ind")
            if not i:
                continue
            v = i.get(key)
            if v is None or (kind == "z" and (i.get(hk) or 0) < Z_MIN_MONTHS):
                continue
            n += 1
        cov[key] = {"n": n, "rate": round(n / len(Q), 4)}
    print(f"\n■ 指標の被覆（退場社込みの母集団 {len(Q)}社に対して）")
    for k, v in cov.items():
        print(f"   {k:<12} {v['n']:>4}/{len(Q)} = **{v['rate']:.1%}**")
    print("   ※退場社に指標は**一度も当たっていない**（月次価格が無い）。だから下の bounds で裁く。")

    sv = [r["px_cagr"] for r in surv]
    aligned = {"n": len(sv), "years": 13.09, "median": round(statistics.median(sv), 4),
               "ew_cagr": round(statistics.fmean([(1 + x) ** 13.09 for x in sv]) ** (1 / 13.09) - 1, 4),
               "p_loss": round(sum(1 for x in sv if x < 0) / len(sv), 4)}
    print(f"\n■ 窓が揃った部分集合（survivor {len(sv)}社・13.09年・price-only）: "
          f"中央値 {aligned['median']:+.1%} / 等ウェイト {aligned['ew_cagr']:+.1%} / "
          f"元本割れ {aligned['p_loss']:.1%}")

    out = {"generated": "2026-08-10", "tool": "night/hist_val2_selfrel_delisted.py",
           "vintage": VINTAGE, "prereg": pre, "basis": dl["basis"],
           "sibling_tool": "night/hist_val2_delisted.py は同じ母集団に dd5 を当てる別器（並走）",
           "universe": {"n_quality": len(Q), "n_survivor": len(surv), "n_restored": len(rest),
                        "n_censored": len(cens), "n_seen_by_v1_v2": n_seen},
           "base_readings": base_readings, "indicator_coverage": cov,
           "raw_pe_proxy_quality": pq,
           "window_aligned_survivors_only": aligned,
           "window_note": ("survivor は13.09年で揃うが退場社は0.8〜13.0年。**元本割れは符号の検定なので"
                           "窓に依らない**が、中央値CAGRと等ウェイトは窓に依存するので混合プールでは"
                           "主張に使わない"),
           "cells": []}

    print(f"\n■ 各セル（止めた群は**測れた社の中**からしか作れない）")
    print(f"   {'指標':<12}{'閾値':>6}{'止':>5}{'止率':>7}{'止:元本割れ':>14}"
          f"{'濃縮(下限)':>11}{'濃縮(中間)':>11}{'濃縮(上限)':>11}"
          f"{'必要な追加(全部が損)':>20}{'2':>3}{'4':>3}")
    for key, kind, hk, label in INDICATORS:
        if kind == "mkt":
            continue
        for thr in (GRID_Z if kind == "z" else GRID_PCT):
            stop, pas = [], []
            for r in Q:
                i = r.get("_ind")
                v = i.get(key) if i else None
                if kind == "z" and i and (i.get(hk) or 0) < Z_MIN_MONTHS:
                    v = None
                (stop if (v is not None and v >= thr) else pas).append(r)
            srs = [r["px_cagr"] for r in stop if r.get("px_cagr") is not None]
            prs = [r["px_cagr"] for r in pas if r.get("px_cagr") is not None]
            if not srs or not prs:
                continue
            nl = sum(1 for x in srs if x < 0)
            rate = nl / len(srs)
            stop_rate = len(stop) / len(Q)
            rec = {"indicator": key, "threshold": thr, "n_stop": len(stop),
                   "stop_rate_pool": round(stop_rate, 4), "n_stop_measured": len(srs),
                   "n_loss_stop": nl, "stop_loss_rate": round(rate, 4),
                   "stop_median": round(statistics.median(srs), 4),
                   "pass_median": round(statistics.median(prs), 4),
                   "c2": bool(statistics.median(srs) <= statistics.median(prs)),
                   "c4": bool(stop_rate <= STOP_CAP), "by_reading": {}}
            lifts, extras = [], []
            for rk, rv in base_readings.items():
                rq = required_extremeness(len(stop), nl, rv["rate"], rv["N"])
                rec["by_reading"][rk] = {
                    "base": rv["rate"], "lift": round(rate / rv["rate"], 3),
                    "c1": bool(rate >= LIFT * rv["rate"] and nl >= MIN_NUM),
                    "required_extremeness": rq}
                lifts.append(rate / rv["rate"])
                extras.append("不可能" if rq["impossible"]
                              else str(rq["extra_stops_all_of_which_must_be_losses"]))
            out["cells"].append(rec)
            mk = lambda x: "✓" if x else "✗"
            print(f"   {key:<12}{thr:>6}{len(stop):>5}{stop_rate:>7.1%}{rate:>10.1%}({nl:>2})"
                  f"{lifts[0]:>11.2f}{lifts[1]:>11.2f}{lifts[2]:>11.2f}"
                  f"{'/'.join(extras):>20}{mk(rec['c2']):>3}{mk(rec['c4']):>3}")

    n_pass = sum(1 for c in out["cells"]
                 if any(v["c1"] for v in c["by_reading"].values()) and c["c2"] and c["c4"])
    hits = [c["stop_loss_rate"] for c in out["cells"]]
    out["verdict"] = {
        "n_cells": len(out["cells"]),
        "n_pass_c1_and_c2_and_c4_any_reading": n_pass,
        "measured_hit_rate_median": round(statistics.median(hits), 4),
        "note": ("『必要な追加』は、指標が未測定の446社の中から**全部が元本割れの社ばかりを**"
                 "選び取れたと仮定したときに、基準1へ届くのに要る社数。"
                 "測れた社での的中率と並べて読むこと——的中率100%を仮定して初めて届くなら、"
                 "それは仮説ではなく願望である。")}
    print(f"\n■ 判定（退場社込み・{len(out['cells'])}セル）")
    print(f"   基準1∧2∧4 を（3つの読みのどれかで）満たすセル: **{n_pass}件**")
    print(f"   測れた社での的中率（止めた群の元本割れ率）の中央 = "
          f"**{out['verdict']['measured_hit_rate_median']:.1%}** ／ "
          f"『必要な追加』はその全部が**元本割れ100%**であることを要求する")

    out["src_tool_rev"] = seen_revs()
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n■ 在庫: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
