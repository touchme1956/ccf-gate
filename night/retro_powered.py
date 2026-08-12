# night/retro_powered.py — 検出力に合わせた基準で全指標を当て直す（2026-08-12新設）
#
# ★なぜ作るか（この台帳の全歴史に関わる）:
#   これまでの検定はすべて **lift >= 0.15** を採用の線にしてきた。ところがベース率は 0.20〜0.35 なので、
#   その線は実効的に **×1.42〜×1.76 の濃縮**を要求する。一方この母集団(n≈470/群)で
#   統計的に検出**可能**な最小の効果は **×1.23**（片側二項・α=0.05・検出力0.80）。
#   実測した検出力は ×1.3 → **0.000** ／ ×1.5 → 0.017 ／ ×1.7 → 0.435。
#   ⇒ **×1.23〜×1.70 の帯は、13年ぶんの検証で構造的に見えていなかった。**
#   P(15%+) を 21%→27% にする信号は実務的に大きいのに、全部素通りしている。ここを当て直す。
#
# 手続き（過剰適合を構造で防ぐ）:
#   ・7アンカー（2016..2022）で同じ47指標を当てる。2019-2022 は 2026-08-12 に新設した未見のアンカー
#   ・各指標は中央値で二分し、**上半分−下半分の P(15%+) の差**を効果量とする
#   ・採用の線は **7アンカーすべてで符号が一致** ∧ **プールした効果が片側二項で有意**
#     （lift の絶対値ではなく、検出力に見合った線にする）
#   ・十分位も出して**単調性**を見る（1つの十分位だけ跳ねるのは雑音の疑い）
#
# ⚠ 7アンカーは**独立ではない**: 母集団は同じ956社で、前方の窓が大きく重なる。
#   だから置換検定の帰無は「アンカーごとに結果を混ぜる」ではなく、
#   **会社の並びを1回だけ入れ替えて全アンカーへ同じ置換を当てる**。
#   こうしないとアンカー間の相関を壊してしまい、帰無が甘くなって自分の試験を過大評価する。
#
# 実行: python3 night/retro_powered.py [--json]

import json
import math
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
ANCHORS = (2016, 2017, 2018, 2019, 2020, 2021, 2022)
HURDLE = 0.15
NPERM = 2000
MIN_NUM = 10          # 群の中の 15%+ の実数の下限（分子）

FEAT2 = ["gm", "sga_r", "capex_r", "aturn", "accr", "streak_rev", "streak_opm", "fcfpos5",
         "intcov", "cash_r", "gw_r", "netiss_r", "rnd_r", "conv5", "payout5",
         "opm", "opmD5", "cagr5", "accel"]
FUND = ["agr1", "agr5", "noa_r", "lease_r", "leasex", "sbc_r", "age_pp", "gwimp_n", "gwimp_r",
        "restr_n", "getr", "cetr", "etrgap", "defrev_gap", "shr_cagr", "shr_down",
        "dso", "dso_d", "dio_d", "divcut_n"]
SHAPE = ["mx1", "skew", "kurt", "dsd", "vol", "negrun", "beta", "ivol"]
ALL = FEAT2 + FUND + SHAPE
FAM = {**{k: "財務比率" for k in FEAT2}, **{k: "会計(新)" for k in FUND},
       **{k: "分布の形(新)" for k in SHAPE}}


def load(anchor):
    def j(p):
        return json.load(open(os.path.join(OUT, p)))
    rets = {r["ticker"]: r["tr_cagr"] for r in j(f"retro_returns_{anchor}.json")["rows"]
            if r.get("tr_cagr") is not None}
    f2 = {r["ticker"]: r for r in j(f"retro_features2_{anchor}.json")["rows"]}
    fu = {r["ticker"]: r for r in j(f"retro_fund2_{anchor}.json")["rows"]}
    sh = {r["t"]: r for r in j(f"retro_shape_{anchor}.json")["rows"]}
    rows = []
    for t, y in rets.items():
        rec = {"t": t, "win": 1 if y >= HURDLE else 0}
        for k in FEAT2:
            rec[k] = f2.get(t, {}).get(k)
        for k in FUND:
            rec[k] = fu.get(t, {}).get(k)
        for k in SHAPE:
            rec[k] = sh.get(t, {}).get(k)
        rows.append(rec)
    return rows


def split_effect(rows, key, wins):
    """中央値で二分し (上半分の率 − 下半分の率) を返す。wins は行と同じ順の 0/1 配列。"""
    idx = [i for i, r in enumerate(rows) if r.get(key) is not None]
    if len(idx) < 60:
        return None
    med = statistics.median(rows[i][key] for i in idx)
    lo = [i for i in idx if rows[i][key] < med]
    hi = [i for i in idx if rows[i][key] >= med]
    if len(lo) < 30 or len(hi) < 30:
        return None
    a = sum(wins[i] for i in lo) / len(lo)
    b = sum(wins[i] for i in hi) / len(hi)
    return {"lo_n": len(lo), "hi_n": len(hi), "lo_p": a, "hi_p": b,
            "lo_num": sum(wins[i] for i in lo), "hi_num": sum(wins[i] for i in hi),
            "diff": b - a, "cut": med}


def deciles(rows, key, wins):
    idx = [i for i, r in enumerate(rows) if r.get(key) is not None]
    if len(idx) < 200:
        return None
    idx.sort(key=lambda i: rows[i][key])
    n = len(idx)
    out = []
    for d in range(10):
        s, e = n * d // 10, n * (d + 1) // 10
        g = idx[s:e]
        if not g:
            return None
        out.append(round(sum(wins[i] for i in g) / len(g), 3))
    return out


def z_two_prop(p1, n1, p2, n2):
    """二群の比率差の片側z（プール分散）。"""
    if n1 < 2 or n2 < 2:
        return 0.0
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return 0.0 if se == 0 else (p1 - p2) / se


def main():
    as_json = "--json" in sys.argv
    data = {a: load(a) for a in ANCHORS}
    # 会社の並びをアンカー間で揃える（置換で同じ入れ替えを当てるため）
    common = set(data[ANCHORS[0]][i]["t"] for i in range(len(data[ANCHORS[0]])))
    for a in ANCHORS[1:]:
        common &= {r["t"] for r in data[a]}
    common = sorted(common)
    pos = {t: i for i, t in enumerate(common)}
    aligned = {}
    for a in ANCHORS:
        arr = [None] * len(common)
        for r in data[a]:
            if r["t"] in pos:
                arr[pos[r["t"]]] = r
        aligned[a] = arr
    wins = {a: [r["win"] for r in aligned[a]] for a in ANCHORS}
    bases = {a: sum(wins[a]) / len(wins[a]) for a in ANCHORS}

    res = {}
    for k in ALL:
        per, ok = {}, True
        for a in ANCHORS:
            e = split_effect(aligned[a], k, wins[a])
            per[a] = e
            if e is None:
                ok = False
        if not ok:
            res[k] = {"family": FAM[k], "skip": "測れたアンカーが足りない"}
            continue
        diffs = [per[a]["diff"] for a in ANCHORS]
        sgn = all(d > 0 for d in diffs) or all(d < 0 for d in diffs)
        # プールした効果（全アンカーの群を足し合わせる＝重み付きの差）
        hi_num = sum(per[a]["hi_num"] for a in ANCHORS)
        hi_n = sum(per[a]["hi_n"] for a in ANCHORS)
        lo_num = sum(per[a]["lo_num"] for a in ANCHORS)
        lo_n = sum(per[a]["lo_n"] for a in ANCHORS)
        z = z_two_prop(hi_num / hi_n, hi_n, lo_num / lo_n, lo_n)
        good_side = "高い側" if (hi_num / hi_n) > (lo_num / lo_n) else "低い側"
        gp = max(hi_num / hi_n, lo_num / lo_n)
        bp = min(hi_num / hi_n, lo_num / lo_n)
        res[k] = {
            "family": FAM[k], "diffs": [round(d, 3) for d in diffs],
            "sign_consistent": sgn, "good_side": good_side,
            "pooled_good_p": round(gp, 4), "pooled_bad_p": round(bp, 4),
            "pooled_ratio": round(gp / bp, 3) if bp > 0 else None,
            "pooled_lift": round(gp - bp, 4), "z": round(abs(z), 2),
            "num_good": hi_num if good_side == "高い側" else lo_num,
            "deciles": {a: deciles(aligned[a], k, wins[a]) for a in ANCHORS},
        }

    # ---- 置換検定: 会社の並びを1回入れ替え、全アンカーへ同じ置換を当てる ----
    rnd = random.Random(20260812)
    order = list(range(len(common)))
    obs_best = max((v["z"] for v in res.values() if "z" in v), default=0)
    hit_z, hit_sign = 0, 0
    for _ in range(NPERM):
        rnd.shuffle(order)
        best_z, any_sign = 0.0, False
        for k in ALL:
            v = res.get(k)
            if "z" not in v:
                continue
            diffs, hn, hnum, ln, lnum = [], 0, 0, 0, 0
            for a in ANCHORS:
                rows = aligned[a]
                w = wins[a]
                idx = [i for i in range(len(rows)) if rows[order[i]].get(k) is not None]
                if len(idx) < 60:
                    diffs = None
                    break
                med = statistics.median(rows[order[i]][k] for i in idx)
                lo = [i for i in idx if rows[order[i]][k] < med]
                hi = [i for i in idx if rows[order[i]][k] >= med]
                if len(lo) < 30 or len(hi) < 30:
                    diffs = None
                    break
                a1 = sum(w[i] for i in lo)
                b1 = sum(w[i] for i in hi)
                diffs.append(b1 / len(hi) - a1 / len(lo))
                hn += len(hi); hnum += b1; ln += len(lo); lnum += a1
            if not diffs:
                continue
            if all(d > 0 for d in diffs) or all(d < 0 for d in diffs):
                any_sign = True
            zz = abs(z_two_prop(hnum / hn, hn, lnum / ln, ln))
            best_z = max(best_z, zz)
        if best_z >= obs_best:
            hit_z += 1
        if any_sign:
            hit_sign += 1
    fp = {"any_indicator_reaches_observed_max_z": round(hit_z / NPERM, 4),
          "any_indicator_sign_consistent_7of7": round(hit_sign / NPERM, 4),
          "observed_max_z": round(obs_best, 2),
          "null_design": "会社の並びを1回だけ入れ替え、全アンカーへ同じ置換を当てる"
                         "（アンカー間の相関を壊さない帰無）"}

    out = {"generated": "2026-08-12", "anchors": list(ANCHORS), "n_common": len(common),
           "bases": {a: round(bases[a], 3) for a in ANCHORS},
           "note": "検出力に合わせた基準で当て直す。採用の線は『7アンカーすべてで符号が一致』∧"
                   "『プールした効果が片側zで有意』∧『分子>=10』。⚠7アンカーは独立ではない",
           "false_positive": fp, "indicators": res}
    json.dump(out, open(os.path.join(OUT, "retro_powered.json"), "w"), ensure_ascii=False, indent=1)

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1)[:15000])
        return
    print(f"共通母集団 {len(common)}社 × {len(ANCHORS)}アンカー")
    print("ベース率:", {a: round(bases[a], 3) for a in ANCHORS})
    print(f"\n偽陽性率（帰無で符号が7/7そろう確率）: {fp['any_indicator_sign_consistent_7of7']}")
    print(f"偽陽性率（帰無で観測の最大z {fp['observed_max_z']} に届く確率）: {fp['any_indicator_reaches_observed_max_z']}")
    hits = [(v["z"], k, v) for k, v in res.items()
            if v.get("sign_consistent") and v.get("num_good", 0) >= MIN_NUM]
    hits.sort(reverse=True)
    print(f"\n=== 7アンカーすべてで符号が一致した指標: {len(hits)} / {len([1 for v in res.values() if 'z' in v])}本 ===")
    print(f"{'指標':<12}{'族':<14}{'良い側':<8}{'良P':>7}{'悪P':>7}{'比':>7}{'z':>7}  各アンカーの差")
    for z, k, v in hits:
        print(f"{k:<12}{v['family']:<14}{v['good_side']:<8}{v['pooled_good_p']:>7.3f}{v['pooled_bad_p']:>7.3f}"
              f"{v['pooled_ratio']:>7.2f}{v['z']:>7.2f}  {v['diffs']}")


if __name__ == "__main__":
    main()
