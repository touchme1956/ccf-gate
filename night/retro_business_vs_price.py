# night/retro_business_vs_price.py — 「事業の未来」と「株価の未来」を同じ指標で当て比べる（2026-08-12新設）
#
# ★この器が存在する理由（否定的結果の建設的な裏返し）:
#   night/retro_persistence.py が「『年率15%+』は会社の性質ではなく、ほぼ抽選」と出した
#   （4つの重ならない窓の当選分布が独立抽選と一致・ICC 0.054・
#     他3窓の**実現リターンそのもの**で選んでも4窓目を当てられない ×0.84〜1.12）。
#   だが同じ器が対照として「**事業の質は持続する**」（前方ROICの順位相関 +0.635）も出した。
#   ⇒ 残る問いは一つ: **株価は当てられないのに事業は当てられるなら、どの指標が事業を当てるのか。**
#   これは「門は何を測るべきか」に直結する（門は株価を合否に使わない・v9.9.98）。
#
# ⚠ この器は判定を一つも持たない。規約・値・採点式・刻み・重み・関門・売却規律には触れない。
#   出すのは順位相関だけで、閾値も刻みも作らない。
#
# 測り方（新しい定数を発明していない）:
#   ・順位相関 Spearman ρ を使う（中央値二分は情報を捨てるので、**連続量のまま**当てる。
#     この台帳がこれまで使ってきた lift は「上半分−下半分」＝ρ の粗い代理）
#   ・前方の事業 = retro_cohort_{asof}.json の fwd_roic_med5_a1 / fwd_cagr_10y / fwd_opm_10y
#     （retro_cohort.py が gate0 の関数定義を exec で取り込み、窓だけ前方へずらして作ったもの＝
#       評価規則は1行も変えていないので look-ahead が構造で防がれている）
#   ・前方の株価 = retro_returns_{asof}_all.json の tr_cagr（Yahoo adjclose＝配当込み）
#   ・指標は asof 時点で観測できるものだけ（features2 は filed<=asof-07-01 で切ってある）
#
# 多重検定: 指標本数ぶんの当たりが出るのは当然なので、**族全体の最大|ρ|**を置換で裁く
#   （会社の並びを1回入れ替える＝指標どうしの相関を壊さない・retro_powered.py と同じ作法）
#
# 出力: out/retro_business_vs_price.json
# 実行: python3 night/retro_business_vs_price.py [--json]

import datetime
import json
import math
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
NPERM = 2000
MIN_N = 150

# 事業の未来（cohort が前方窓で実測した会社の姿）と 株価の未来
BIZ = {
    "fwd_roic": ("fwd_roic_med5_a1", "前方ROIC(+6..+10年の中央値)"),
    "fwd_growth": ("fwd_cagr_10y", "前方売上CAGR(10年)"),
    "fwd_opm": ("fwd_opm_10y", "前方営業利益率(10年)"),
}

# asof 時点で観測できる指標（cohort内 / features2 / fund2）
COHORT_IND = ["roic_latest", "roic_med5", "roic_worst5", "opm", "sales_cagr5", "fcf_conv_5y",
              "score", "rev_asof"]
F2_IND = ["gm", "sga_r", "capex_r", "aturn", "accr", "streak_rev", "streak_opm", "fcfpos5",
          "intcov", "cash_r", "gw_r", "netiss_r", "rnd_r", "conv5", "payout5", "opm",
          "opmD5", "cagr5", "accel", "rev"]
FU_IND = ["agr1", "noa_r", "sbc_r", "age_pp", "gwimp_n", "gwimp_r", "restr_n", "getr",
          "cetr", "etrgap", "defrev_gap", "shr_cagr", "shr_down", "dso", "dso_d", "dio_d",
          "divcut_n"]


def rows(path, key="rows"):
    p = os.path.join(OUT, path)
    if not os.path.exists(p):
        return []
    d = json.load(open(p))
    return d[key] if isinstance(d, dict) and key in d else (d if isinstance(d, list) else [])


def ranks(xs):
    """同順位は平均順位（tie 補正なしだと離散欄で ρ が歪む）"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(pairs):
    if len(pairs) < MIN_N:
        return None
    xs = ranks([p[0] for p in pairs])
    ys = ranks([p[1] for p in pairs])
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def build(asof):
    """{ticker: {指標名: 値}} と {ticker: {目的名: 値}} を作る。
    ⚠ 同名の欄（opm）が cohort と features2 の両方にあるので接頭辞で必ず分ける
    （基準の違う二つを同じ名前で並べない）。"""
    co = {r["ticker"]: r for r in rows(f"retro_cohort_{asof}.json") if r.get("ticker")}
    f2 = {r["ticker"]: r for r in rows(f"retro_features2_{asof}.json")}
    fu = {r["ticker"]: r for r in rows(f"retro_fund2_{asof}.json")}
    # ⚠ リターンの在庫は同じ年に複数ある（_all=全数 / _q=質実証プール / 無印=抽出）。
    #   **全部を union する**——片方だけ読むと n が痩せて「効かない」が検出力不足に化ける
    #   （実測 asof=2015: 無印だけなら164社、_q を足すと506社）。
    #   同じ ticker が複数に居たら先に読んだほうを採る（窓の長さが揃っているものを先に置く）
    px, px_src = {}, []
    for name in (f"retro_returns_{asof}_all.json", f"retro_returns_{asof}_q.json",
                 f"retro_returns_{asof}.json"):
        got = 0
        for r in rows(name):
            if r.get("ticker") and r.get("tr_cagr") is not None and r["ticker"] not in px:
                px[r["ticker"]] = r["tr_cagr"]
                got += 1
        if got:
            px_src.append({"file": name, "added": got})

    ind, tgt = {}, {}
    # ⚠ sorted() が要る——set の反復順は PYTHONHASHSEED で毎回変わるので、
    #   置換検定の組み合わせ方が実行ごとに変わり **同じ入力で p が動く**（実測 0.155 vs 0.174）。
    #   ρ は順序に依らないので無害だが、**同じものを二度測ったら同じ答えが出る**を壊す
    for t in sorted(set(co) | set(f2) | set(fu)):
        d = {}
        for k in COHORT_IND:
            v = co.get(t, {}).get(k)
            if v is not None:
                d[f"co.{k}"] = v
        for k in F2_IND:
            v = f2.get(t, {}).get(k)
            if v is not None:
                d[f"f2.{k}"] = v
        for k in FU_IND:
            v = fu.get(t, {}).get(k)
            if v is not None:
                d[f"fu.{k}"] = v
        if not d:
            continue
        ind[t] = d
        g = {}
        for name, (col, _lab) in BIZ.items():
            v = co.get(t, {}).get(col)
            if v is not None:
                g[name] = v
        if t in px:
            g["price"] = px[t]
        tgt[t] = g
    return ind, tgt, px_src


def measure(ind, tgt, keys, targets):
    res = {}
    for k in keys:
        row = {}
        for g in targets:
            pairs = [(ind[t][k], tgt[t][g]) for t in ind
                     if k in ind[t] and g in tgt.get(t, {})]
            r = spearman(pairs)
            row[g] = {"rho": round(r, 3), "n": len(pairs)} if r is not None else {"rho": None, "n": len(pairs)}
        res[k] = row
    return res


def family_perm(ind, tgt, keys, g, obs_max, seed):
    """会社の並びを1回だけ入れ替える＝指標どうしの相関構造を壊さない置換。
    帰無で『どれか1本が |ρ|=obs_max 以上を出す』確率を数える。"""
    have = [t for t in ind if g in tgt.get(t, {})]
    if len(have) < MIN_N:
        return None
    rnd = random.Random(seed)
    ys_all = [tgt[t][g] for t in have]
    hit = 0
    for _ in range(NPERM):
        perm = ys_all[:]
        rnd.shuffle(perm)
        shuffled = dict(zip(have, perm))
        best = 0.0
        for k in keys:
            pairs = [(ind[t][k], shuffled[t]) for t in have if k in ind[t]]
            r = spearman(pairs)
            if r is not None:
                best = max(best, abs(r))
        if best >= obs_max:
            hit += 1
    return round(hit / NPERM, 4)


def ymk(ts):
    import datetime
    d = datetime.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)


def halves():
    """★株価を当てた指標が『いつ』当てたかを分ける。
    2013-07→2026-08 は一つの窓なので、そのまま読むと『13年当て続けた』のか
    『前半だけ』『後半だけ』なのかが区別できない。重ならない前半・後半へ割る。
    月次パネル（在庫・追加取得ゼロ）から作るので新しい取得はしない。"""
    P = {}
    for f in ("retro_monthly_2013_2018.json", "retro_monthly_2018_2026.json"):
        p = os.path.join(OUT, f)
        if not os.path.exists(p):
            return None
        for t, s in json.load(open(p)).items():
            m = P.setdefault(t, {})
            for ts, px in s:
                if px and px > 0:
                    k = ymk(ts)
                    if k not in m:
                        m[k] = px
    if not P:
        return None
    kend = max(x for m in P.values() for x in m)

    def cg(m, k0, k1):
        ks = [k for k in sorted(m) if k0 <= k <= k1]
        if len(ks) < 24:
            return None
        p0, p1 = m[ks[0]], m[ks[-1]]
        y = (ks[-1] - ks[0]) / 12
        return (p1 / p0) ** (1 / y) - 1 if p0 > 0 and y > 0 else None

    segs = {"first_2013_2019": (2013 * 12 + 6, 2019 * 12 + 5),
            "second_2019_2026": (2019 * 12 + 6, kend),
            "whole_2013_2026": (2013 * 12 + 6, kend)}
    co = {r["ticker"]: r for r in rows("retro_cohort_2013.json") if r.get("ticker")}
    out = {}
    for k in COHORT_IND:
        row = {}
        for s, (a, b) in segs.items():
            pr = []
            for t, m in P.items():
                v = co.get(t, {}).get(k)
                c = cg(m, a, b)
                if v is not None and c is not None:
                    pr.append((v, c))
            r = spearman(pr)
            row[s] = {"rho": round(r, 3) if r is not None else None, "n": len(pr)}
        out[k] = row
    return out


def main():
    as_json = "--json" in sys.argv
    # ⚠ 生成日は**実行時**に採る（2026-09-20是正）。初版は "2026-08-12" を焼き付けており、
    #   回し直すと「2026-08-12に測った」と名乗り続けた（`check_frozen_dates` の錨は左辺の
    #   変数名だけなので**辞書リテラルの固定日は鳴らない**＝todo frozen_date_dict_literal の族）。
    #   ⚠ 2026-09-20 の再実行は **2015アンカーの指標が8本→43本へ増えた後**のもの＝
    #   初版（features2_2015 / fund2_2015 が在庫に無く co.* だけだった8本）とは別の測定。
    out = {"generated": datetime.date.today().isoformat(),
           "prior_run": {"generated": "2026-08-12",
                         "what": "2015は features2_2015 / fund2_2015 が在庫に無く co.* の8指標だけ"
                                 "（族p 0.175 はその8本に対する値）"},
           "note": "同じ指標で『事業の未来』と『株価の未来』を当て比べる。判定はしない",
           "method": "Spearman順位相関（tie平均）。多重検定は会社の並びを1回入れ替える置換で族全体を裁く",
           "anchors": {}}

    for asof in (2013, 2015):
        ind, tgt, px_src = build(asof)
        if not ind:
            continue
        keys = sorted({k for d in ind.values() for k in d})
        keys = [k for k in keys if sum(1 for t in ind if k in ind[t]) >= MIN_N]
        targets = [g for g in ("fwd_roic", "fwd_growth", "fwd_opm", "price")
                   if sum(1 for t in tgt if g in tgt[t]) >= MIN_N]
        if not targets:
            continue
        res = measure(ind, tgt, keys, targets)

        summ = {}
        for g in targets:
            vals = [(abs(res[k][g]["rho"]), k) for k in keys if res[k][g]["rho"] is not None]
            vals.sort(reverse=True)
            summ[g] = {
                "n_indicators": len(vals),
                "max_abs_rho": round(vals[0][0], 3) if vals else None,
                "argmax": vals[0][1] if vals else None,
                "n_ge_020": sum(1 for v, _k in vals if v >= 0.20),
                "n_ge_030": sum(1 for v, _k in vals if v >= 0.30),
                "top5": [{"k": k, "rho": res[k][g]["rho"], "n": res[k][g]["n"]} for _v, k in vals[:5]],
            }
            if vals:
                summ[g]["p_family"] = family_perm(ind, tgt, keys, g, vals[0][0], 20260812 + asof)

        out["anchors"][str(asof)] = {
            "n_companies": len(ind), "n_indicators": len(keys),
            "price_sources": px_src,
            "targets": {g: sum(1 for t in tgt if g in tgt[t]) for g in targets},
            "summary": summ, "rho": res,
        }

    # --- 対照の要約（この器の結論そのもの）---
    con = []
    for a, d in out["anchors"].items():
        s = d["summary"]
        biz = [s[g]["max_abs_rho"] for g in ("fwd_roic", "fwd_growth", "fwd_opm") if g in s]
        con.append({
            "asof": a,
            "biz_max_abs_rho": max(biz) if biz else None,
            "price_max_abs_rho": s.get("price", {}).get("max_abs_rho"),
            "biz_n_ge_020": max((s[g]["n_ge_020"] for g in ("fwd_roic", "fwd_growth", "fwd_opm") if g in s), default=None),
            "price_n_ge_020": s.get("price", {}).get("n_ge_020"),
            "p_family_price": s.get("price", {}).get("p_family"),
        })
    out["contrast"] = con
    h = halves()
    if h:
        out["price_by_half"] = {
            "note": "★2013-07→2026-08 を重ならない前半・後半へ割り、株価に対するρがいつ出たかを見る",
            "caveat": "月次パネルは生存者のみ。小型の退場社が入っていないので、規模の効果は**過小に出る**側",
            "rho": h}

    json.dump(out, open(os.path.join(OUT, "retro_business_vs_price.json"), "w"),
              ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for a, d in out["anchors"].items():
        print(f"\n=== asof={a}  {d['n_companies']}社 × {d['n_indicators']}指標 ===")
        for g, s in d["summary"].items():
            lab = {"fwd_roic": "前方ROIC", "fwd_growth": "前方売上CAGR",
                   "fwd_opm": "前方営利率", "price": "★株価(実現年率)"}[g]
            print(f"  {lab:<16} 最大|ρ|={s['max_abs_rho']} ({s['argmax']})  "
                  f"|ρ|≥0.20 {s['n_ge_020']}本 / ≥0.30 {s['n_ge_030']}本  族p={s.get('p_family')}")
            for x in s["top5"]:
                print(f"      {x['k']:<16}ρ={x['rho']:+.3f} (n={x['n']})")
    if out.get("price_by_half"):
        print("\n=== ★株価に対するρを、重ならない前半・後半へ割る（asof=2013の指標）===")
        print(f"  {'指標':<14}{'前半 13-19':<18}{'後半 19-26':<18}{'全体 13-26':<18}")
        for k, v in out["price_by_half"]["rho"].items():
            def f(s):
                x = v[s]["rho"]
                return f"{x:+.3f} (n={v[s]['n']})" if x is not None else "na"
            print(f"  {k:<14}{f('first_2013_2019'):<18}{f('second_2019_2026'):<18}{f('whole_2013_2026'):<18}")
        print("  ⚠ パネルは生存者のみ＝小型の退場社が居ない。規模の効果は過小に出る側")
    print("\n=== 対照 ===")
    for c in out["contrast"]:
        print(f"  asof={c['asof']}: 事業 最大|ρ|={c['biz_max_abs_rho']} / |ρ|≥0.20 {c['biz_n_ge_020']}本"
              f"  ★株価 最大|ρ|={c['price_max_abs_rho']} / |ρ|≥0.20 {c['price_n_ge_020']}本"
              f"（族p={c['p_family_price']}）")


if __name__ == "__main__":
    main()
