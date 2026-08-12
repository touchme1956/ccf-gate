# night/retro_subperiod.py — 重ならない部分期間で当て直し、真の out-of-sample で確認する（2026-08-12新設）
#
# ★背景（この器が存在する理由）:
#   night/retro_powered.py が「既存の判定基準 lift>=0.15 は実効 ×1.42〜1.76 を要求するのに、
#   この母集団で検出**可能**な最小は ×1.23」＝**×1.23〜1.70 の帯が13年ぶん見えていなかった**と定量した。
#   そこで検出力に見合う基準で当て直したところ、7アンカー(2016..2022)で13本が符号一致した。
#   **だが7アンカーはすべて2026年終点＝同じ終盤相場を共有している。**
#   置換検定（会社の並びを1回だけ入れ替え全アンカーへ同じ置換を当てる）で
#   **帰無でも符号が7/7そろう確率は 0.996** と出た＝一致は証拠にならない。
#
# ⇒ この器は「時間的に**重ならない**窓」で当て直す:
#     期1 2016-07→2019-06 ／ 期2 2019-07→2022-06 ／ 期3 2022-07→2026-08
#   さらに **真の out-of-sample** として、選択に一切使っていない
#     期0 2013-07→2016-06（他の3期と時間的に一切重ならない）を用意する。
#   指標の選択は期1-3で行い、**期0では指標も符号も凍結したまま当てる**。
#
# ⚠ 判定はしない（規約・値・採点式には触れない）。測定と記録だけ。
# 実行: python3 night/retro_subperiod.py [--json]

import datetime
import json
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
HURDLE = 0.15
NPERM = 1000
# 選択に使う3期（時間的に重ならない）と、確認だけに使う期0
SEL = [(2016, 2019), (2019, 2022), (2022, None)]
OOS = (2013, 2016)

F2 = ["gm", "sga_r", "capex_r", "aturn", "accr", "streak_rev", "streak_opm", "fcfpos5", "intcov",
      "cash_r", "gw_r", "netiss_r", "rnd_r", "conv5", "payout5", "opm", "opmD5", "cagr5", "accel"]
FU = ["agr1", "agr5", "noa_r", "lease_r", "leasex", "sbc_r", "age_pp", "gwimp_n", "gwimp_r",
      "restr_n", "getr", "cetr", "etrgap", "defrev_gap", "shr_cagr", "shr_down", "dso", "dso_d",
      "dio_d", "divcut_n"]
SH = ["mx1", "skew", "kurt", "dsd", "vol", "negrun", "beta", "ivol"]
ALLK = F2 + FU + SH


def ymk(ts):
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)


def panel():
    p = {}
    for f in ("retro_monthly_2013_2018.json", "retro_monthly_2018_2026.json"):
        for t, s in json.load(open(os.path.join(OUT, f))).items():
            m = p.setdefault(t, {})
            for ts, px in s:
                if px and px > 0:
                    k = ymk(ts)
                    if k not in m:
                        m[k] = px
    return p


def cagr(m, k0, k1):
    ks = [k for k in sorted(m) if k0 <= k <= k1]
    if len(ks) < 24:
        return None
    p0, p1 = m[ks[0]], m[ks[-1]]
    y = (ks[-1] - ks[0]) / 12
    return (p1 / p0) ** (1 / y) - 1 if p0 > 0 and y > 0 else None


def indicators(asof):
    def rd(p):
        try:
            return json.load(open(os.path.join(OUT, p)))["rows"]
        except Exception:
            return []
    f2 = {r["ticker"]: r for r in rd(f"retro_features2_{asof}.json")}
    fu = {r["ticker"]: r for r in rd(f"retro_fund2_{asof}.json")}
    sh = {r["t"]: r for r in rd(f"retro_shape_{asof}.json")}
    o = {}
    for t in set(f2) | set(fu) | set(sh):
        d = {k: f2.get(t, {}).get(k) for k in F2}
        d.update({k: fu.get(t, {}).get(k) for k in FU})
        d.update({k: sh.get(t, {}).get(k) for k in SH})
        d["rev"] = f2.get(t, {}).get("rev")
        o[t] = d
    return o


def window(P, a, b, kend):
    k0 = a * 12 + 6
    k1 = kend if b is None else b * 12 + 6
    ind = indicators(a)
    out = {}
    for t, m in P.items():
        c = cagr(m, k0, k1)
        if c is None or t not in ind:
            continue
        out[t] = (ind[t], 1 if c >= HURDLE else 0)
    return out


def half_diff(dat, k, mp=None, keys=None):
    src = keys if keys is not None else list(dat)
    rows = []
    for t in src:
        if t not in dat:
            continue
        v = (dat[mp[t]][0] if mp else dat[t][0]).get(k) if (not mp or mp[t] in dat) else None
        if v is None:
            continue
        rows.append((v, dat[t][1]))
    if len(rows) < 200:
        return None
    med = statistics.median(x[0] for x in rows)
    lo = [w for v, w in rows if v < med]
    hi = [w for v, w in rows if v >= med]
    if len(lo) < 80 or len(hi) < 80:
        return None
    return sum(hi) / len(hi) - sum(lo) / len(lo)


def main():
    as_json = "--json" in sys.argv
    P = panel()
    kend = max(x for m in P.values() for x in m)
    D = [window(P, a, b, kend) for a, b in SEL]
    common = sorted(set(D[0]) & set(D[1]) & set(D[2]))

    # --- 期1-3 で符号が一致し、平均|差|が大きい指標 ---
    obs = {}
    for k in ALLK:
        ds = [half_diff(d, k) for d in D]
        if any(x is None for x in ds):
            continue
        same = all(x > 0 for x in ds) or all(x < 0 for x in ds)
        obs[k] = {"diffs": [round(x, 4) for x in ds], "same_sign": same,
                  "score": abs(sum(ds) / 3) if same else 0.0,
                  "good_side": "高い側" if ds[0] > 0 else "低い側"}
    surv = sorted([(v["score"], k) for k, v in obs.items() if v["score"] > 0], reverse=True)

    # --- 置換検定: 会社の並びを1回入れ替え、3期に同じ置換を当てる ---
    rnd = random.Random(20260812)
    maxs, n_same = [], []
    for _ in range(NPERM):
        perm = common[:]
        rnd.shuffle(perm)
        mp = dict(zip(common, perm))
        best, cnt = 0.0, 0
        for k in obs:
            ds = [half_diff(d, k, mp, common) for d in D]
            if any(x is None for x in ds):
                continue
            if all(x > 0 for x in ds) or all(x < 0 for x in ds):
                cnt += 1
                best = max(best, abs(sum(ds) / 3))
        maxs.append(best)
        n_same.append(cnt)
    maxs.sort()
    obs_max = surv[0][0] if surv else 0.0
    fp = {
        "n_same_sign_observed": len(surv),
        "n_same_sign_null_median": statistics.median(n_same),
        "p_n_same_sign": round(sum(1 for c in n_same if c >= len(surv)) / NPERM, 4),
        "max_score_observed": round(obs_max, 4),
        "max_score_null_p95": round(maxs[int(0.95 * len(maxs)) - 1], 4),
        "p_family": round(sum(1 for m in maxs if m >= obs_max) / NPERM, 4),
        "null_design": "会社の並びを1回だけ入れ替え、3期に同じ置換を当てる（期間相関を壊さない）",
    }

    # --- 真の out-of-sample（期0）で凍結したまま当てる ---
    TOP = [k for _s, k in surv[:6]]
    SIGN = {k: (1 if obs[k]["good_side"] == "高い側" else -1) for k in TOP}
    ret0 = {r["ticker"]: r["tr_cagr"]
            for r in json.load(open(os.path.join(OUT, "retro_returns_2013w.json")))["rows"]}
    ind0 = indicators(2013)
    d0 = {t: (ind0[t], 1 if y >= HURDLE else 0) for t, y in ret0.items() if t in ind0}
    oos_single = {}
    for k in TOP:
        v = [(d[k], w) for d, w in d0.values() if d.get(k) is not None]
        if len(v) < 200:
            oos_single[k] = {"n": len(v), "note": "n不足"}
            continue
        med = statistics.median(x[0] for x in v)
        lo = [w for x, w in v if x < med]
        hi = [w for x, w in v if x >= med]
        diff = (sum(hi) / len(hi) - sum(lo) / len(lo)) * SIGN[k]
        oos_single[k] = {"n": len(v), "diff_signed": round(diff, 4), "held": diff > 0}
    have = [t for t, (d, _w) in d0.items() if all(d.get(k) is not None for k in TOP)]
    oos_comp = {"n": len(have)}
    if len(have) >= 150:
        base = sum(d0[t][1] for t in have) / len(have)
        ranks = {t: {} for t in have}
        for k in TOP:
            vals = sorted((d0[t][0][k], t) for t in have)
            for r, (_v, t) in enumerate(vals):
                p = r / (len(vals) - 1)
                ranks[t][k] = p if SIGN[k] > 0 else 1 - p
        sc = sorted(((sum(ranks[t].values()) / len(TOP), t) for t in have))
        n = len(sc)
        dec = [sum(d0[t][1] for _s, t in sc[n * j // 10:n * (j + 1) // 10]) /
               len(sc[n * j // 10:n * (j + 1) // 10]) for j in range(10)]
        oos_comp.update({"base": round(base, 3), "deciles": [round(x, 3) for x in dec],
                         "top10_ratio": round(dec[-1] / base, 2), "bot10_ratio": round(dec[0] / base, 2)})

    out = {"generated": "2026-08-12",
           "note": "重ならない3期で選び、時間的に一切重ならない期0(2013-07→2016-06)で確認する。判定はしない",
           "windows": {"selection": [f"{a}-07→{(b or 2026)}-0{6 if b else 8}" for a, b in SEL],
                       "oos": "2013-07→2016-06"},
           "same_sign_indicators": [{"k": k, "score": round(s, 4), **obs[k]} for s, k in surv],
           "false_positive": fp, "frozen_top": TOP, "signs": SIGN,
           "oos_single": oos_single, "oos_composite": oos_comp}
    json.dump(out, open(os.path.join(OUT, "retro_subperiod.json"), "w"), ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print("=== 重ならない3期で符号が一致した指標（平均|差|順）===")
    for s, k in surv:
        print(f"  {k:<10}{obs[k]['good_side']:<6}平均|差|={s:.4f}  各期={obs[k]['diffs']}")
    print(f"\n=== 置換検定 ===\n  符号一致の本数: 実測{fp['n_same_sign_observed']} vs 帰無中央値{fp['n_same_sign_null_median']}"
          f" → p={fp['p_n_same_sign']}（＝符号の一致は証拠にならない）")
    print(f"  平均|差|の最大: 実測{fp['max_score_observed']} vs 帰無95%点{fp['max_score_null_p95']}"
          f" → **族全体 p={fp['p_family']}**")
    print(f"\n=== 真の out-of-sample（2013-07→2016-06・凍結して当てる）===")
    for k in TOP:
        v = oos_single[k]
        print(f"  {k:<10}{v}")
    print(f"  合成スコア: {oos_comp}")


if __name__ == "__main__":
    main()
