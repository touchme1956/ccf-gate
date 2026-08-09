# night/hist_val_full.py — 自己相対バリュエーション遮断器を **full プール**で判定し、
#                          あわせて **指標そのものの健全性**を検査する（2026-08-09新設）
#
# 事前登録: out/hist_valuation_prereg.json（合否6基準・閾値の格子・プール定義の正本）
#   ※ 事前登録は「合否は quality プールで判定する。full は参考」と書いている。
#     この器が出す verdict は **full プールについての参考判定**であり、正本の合否ではない。
#     それでも6基準はそのまま当てる——基準を緩めた別物の判定を作ると、
#     「同じ台帳を見る二つの検査器が違うことを言う」(v9.9.65) の入口になるから。
#
# ── この器が答える4つの問い ─────────────────────────────────────────────
#  Q1 判定  : 事前登録の格子（分位 .80/.85/.90/.95 ／ z 1.0/1.5/2.0 ／ spx 80/90/95）を
#             full プールで一度だけ回し、6基準を全部満たす「指標×閾値」があるか
#  Q2 被覆  : 各指標が母集団の何%で定義できるか（被覆が半分を切る指標は事前登録により不合格）
#  Q3 健全性: (a) 分位の分布は一様か（一様でない＝自己履歴の作り方が偏っている）
#             (b) hist_months が短い社を除くと結論が変わるか
#             (c) pe_pct と ps_pct はどのくらい一致するか（別の指標か、同じものの言い換えか）
#  Q4 反証  : **横断面の絶対PER（out/retro_per_*.json の per）と自己相対分位の相関**。
#             強く相関するなら、これは既に「効かない」と分かっている横断面PERの言い換えにすぎない
#             ＝この検定の最重要の反証経路。手を抜かない。
#
# ── 測り方の掟（このリポジトリの作法をそのまま使う）───────────────────────
#  ■ 窓を揃える: `window_full` が False の行は使わない（DBD 型＝再上場後3.01年を8.09年の
#    コホートに混ぜる事故。除外は hist_val_join.py が既に印を付けている）
#  ■ 遮断器は選別器ではない: 裁く物差しは **止めた側の左尾（恒久毀損率 P(年率<=-15%)）**。
#    同時に「止めた群の中央値が通過群より高くないか」＝勝者を巻き込んでいないかも必ず見る
#  ■ 中央値だけで語らない: **等ウェイト買い持ち**（終価倍率の平均を年率へ）も併記する
#    （2026-08-09の実測で中央値7.2% vs 等ウェイト12.4%＝差は右裾）
#  ■ 基準の違う二つを割らない: per_xs（retro_per_{Y}）の株価は **asof の1ヶ月後（7月末）**、
#    本器の pe/ps/pfcf は **asof 以前（6月末）**。相関(Q4)は順位相関だけを取り、
#    比・差は一切作らない（hist_val_2013.json の caveat がこの罠を明記している）
#  ■ 二重実装を作らない: プール・窓・リターンの綴じ込みは hist_val_join.py が決めたものを
#    そのまま読む。この器は join をやり直さない
#
# 実行:
#   python3 night/hist_val_full.py                 # 3ビンテージ全部・out/hist_val_full.json へ
#   python3 night/hist_val_full.py --asof 2018     # 1ビンテージだけ
#   python3 night/hist_val_full.py --quiet         # 標準出力を抑えてJSONだけ書く
import argparse
import json
import math
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

VINTAGES = (2013, 2015, 2018)

# ── 事前登録の格子（**ここを結果を見てから動かしたら検定は死ぬ**）─────────────
PCT_GRID = (0.80, 0.85, 0.90, 0.95)
Z_GRID = (1.0, 1.5, 2.0)
SPX_GRID = (0.80, 0.90, 0.95)

# 事前登録 indicators.A_self_relative に列挙されたものだけを **合否に使う**。
# *_ann（年次のみで組んだ変種）は器が副産物として持つが格子外＝健全性の参考にのみ使う。
PCT_INDICATORS = ("pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct")
PCT_EXTRA = ("pe_pct_ann", "adj_pe_pct_ann")
Z_INDICATORS = ("pe_z", "ps_z")

# z は履歴8ヶ月でも出てしまう（分位は36ヶ月を要求する）。
# 在庫の caveat が「z格子を当てるときは hist_months>=36 を必ず併せて課せ」と明記しているので従う。
Z_HIST_KEY = {"pe_z": "pe_hist_months", "ps_z": "ps_hist_months"}

MDD_KILL = -0.15   # 恒久毀損の線: 年率 <= -15%
WIN = 0.15         # 「15%+」の線
PASS_TAIL_RATIO = 2.0
PASS_TAIL_MIN_N = 5
PASS_STOP_FRAC = 0.15


# ───────────────────────── 小さな統計（外部依存なし）─────────────────────────
def med(xs):
    return round(statistics.median(xs), 4) if xs else None


def ew_cagr(rows, years):
    """等ウェイト買い持ち。終価倍率の**算術平均**を年率へ（＝等ウェイトの実現はこれ）。"""
    tot = [r["tr_total"] for r in rows if r.get("tr_total") is not None]
    if not tot or not years or years <= 0:
        return None
    m = sum(tot) / len(tot)
    if m <= 0:
        return None
    return round(m ** (1.0 / years) - 1.0, 4)


def rank(xs):
    """順位（同順位は平均順位）。Spearman 用。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rk[order[k]] = avg
        i = j + 1
    return rk


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    if sa == 0 or sb == 0:
        return None
    return round(sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa * sb), 4)


def spearman(a, b):
    if len(a) < 3:
        return None
    return pearson(rank(a), rank(b))


def wilson(k, n):
    """二項の95%信頼区間（Wilson）。『n=9の0件は真のゼロではない』を毎回言えるように。"""
    if not n:
        return None
    z = 1.959964
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


# ───────────────────────── 在庫の読み込み ─────────────────────────
def load_vintage(y):
    p = os.path.join(OUT, f"hist_val_{y}.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def usable(rows):
    """窓が揃っていて前方リターンがある行だけ。**ここが全ての母集団の土台**。"""
    return [r for r in rows
            if r.get("window_full") and r.get("tr_cagr") is not None
            and r.get("tr_total") is not None]


# ───────────────────────── 判定（1つの規則を裁く）─────────────────────────
def judge(pool, key, thr, years, hist_key=None, hist_min=36):
    """key >= thr を『止める』とする遮断器を1つ裁く。

    pool は既に窓が揃っている。指標が定義できない社は**この規則の母集団から外す**
    ——欠測を『止めない』に倒すと被覆の低い指標ほど有利に見えるから（ルール7の同族）。
    """
    elig = []
    for r in pool:
        v = r.get(key)
        if v is None:
            continue
        if hist_key is not None:
            hm = r.get(hist_key)
            if hm is None or hm < hist_min:
                continue
        elig.append(r)
    n = len(elig)
    if n == 0:
        return None
    stop = [r for r in elig if r[key] >= thr]
    pas = [r for r in elig if r[key] < thr]
    ns, np_ = len(stop), len(pas)

    def blk(g):
        if not g:
            return {"n": 0}
        kill = [r for r in g if r["tr_cagr"] <= MDD_KILL]
        win = [r for r in g if r["tr_cagr"] >= WIN]
        return {
            "n": len(g),
            "median": med([r["tr_cagr"] for r in g]),
            "ew": ew_cagr(g, years),
            "kill_n": len(kill),
            "kill_rate": round(len(kill) / len(g), 4),
            "kill_ci95": wilson(len(kill), len(g)),
            "win15_n": len(win),
            "win15_rate": round(len(win) / len(g), 4),
        }

    base_kill = sum(1 for r in elig if r["tr_cagr"] <= MDD_KILL) / n
    s, p = blk(stop), blk(pas)
    ratio = (s["kill_rate"] / base_kill) if (ns and base_kill > 0) else None
    c1 = bool(ns and ratio is not None and ratio >= PASS_TAIL_RATIO
              and s["kill_n"] >= PASS_TAIL_MIN_N)
    c2 = bool(ns and np_ and s["median"] is not None and p["median"] is not None
              and s["median"] <= p["median"])
    c4 = bool(ns and (ns / n) <= PASS_STOP_FRAC)
    return {
        "key": key, "thr": thr, "n_eligible": n,
        "stop_frac": round(ns / n, 4),
        "base_kill_rate": round(base_kill, 4),
        "base_median": med([r["tr_cagr"] for r in elig]),
        "base_ew": ew_cagr(elig, years),
        "stop": s, "pass": p,
        "kill_ratio": round(ratio, 3) if ratio is not None else None,
        "c1_left_tail": c1, "c2_no_winner_capture": c2, "c4_narrow": c4,
        "stop_tickers": sorted(r["ticker"] for r in stop)[:60],
    }


# ───────────────────────── 健全性の検査 ─────────────────────────
def uniformity(pool, key):
    """分位の分布は一様か。自己履歴の作り方が偏っていれば十分位が崩れる。

    自己分位は定義上『その社の過去の月に対する順位』なので、**倍率拡大期には
    全員が上に寄る**（事前登録 known_risks の regime）。それを数で見る。
    一様性の検定は χ²（十分位・自由度9・5%点16.92 / 1%点21.67）。
    """
    xs = [r[key] for r in pool if r.get(key) is not None]
    n = len(xs)
    if n < 30:
        return {"n": n, "note": "n<30 で分布は判定しない"}
    dec = [0] * 10
    for v in xs:
        i = min(9, max(0, int(v * 10)))
        dec[i] += 1
    exp = n / 10.0
    chi2 = sum((c - exp) ** 2 / exp for c in dec)
    return {
        "n": n,
        "deciles": dec,
        "top_decile_frac": round(dec[9] / n, 4),
        "top2_decile_frac": round((dec[8] + dec[9]) / n, 4),
        "bottom_decile_frac": round(dec[0] / n, 4),
        "median": round(statistics.median(xs), 4),
        "chi2_vs_uniform_df9": round(chi2, 1),
        "uniform_at_1pct": bool(chi2 < 21.67),
    }


def agreement(pool, k1, k2, thr):
    """2つの指標が『止める』集合としてどれだけ一致するか（Jaccard と κ）。

    別の情報を測っているのか、同じものの言い換えなのかを、順位相関と
    **実際の遮断集合**の両方で見る（相関が中位でも遮断集合は一致しうる）。
    """
    both = [r for r in pool if r.get(k1) is not None and r.get(k2) is not None]
    n = len(both)
    if n < 30:
        return {"n": n, "note": "n<30"}
    a = set(r["ticker"] for r in both if r[k1] >= thr)
    b = set(r["ticker"] for r in both if r[k2] >= thr)
    inter, uni = len(a & b), len(a | b)
    # Cohen's κ
    po = (inter + (n - uni)) / n
    pa, pb = len(a) / n, len(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    kappa = (po - pe) / (1 - pe) if pe < 1 else None
    return {
        "n": n, "thr": thr,
        "n_%s" % k1: len(a), "n_%s" % k2: len(b),
        "both": inter, "either": uni,
        "jaccard": round(inter / uni, 4) if uni else None,
        "kappa": round(kappa, 4) if kappa is not None else None,
        "spearman": spearman([r[k1] for r in both], [r[k2] for r in both]),
    }


def vs_cross_section(pool, key):
    """**最重要の反証**: 自己相対分位は横断面PERの言い換えか。

    per_xs は retro_per_{Y} の絶対PER（分割補正済み・当時の板）。
    ⚠ 株価の基準日が1ヶ月ずれる（per_xs=7月末 / 本器=6月末）ので **順位相関だけ**を取る。
      比や差は作らない（「基準の違う二つを割る」型をここで踏まない）。
    """
    both = [r for r in pool
            if r.get(key) is not None and r.get("per_xs") not in (None, 0)]
    n = len(both)
    if n < 30:
        return {"n": n, "note": "n<30"}
    sp = spearman([r[key] for r in both], [r["per_xs"] for r in both])
    # 遮断集合の重なりも見る: 自己分位>=.90 と 横断面PERの上位10%
    xs_sorted = sorted(r["per_xs"] for r in both)
    cut = xs_sorted[int(len(xs_sorted) * 0.90)]
    a = set(r["ticker"] for r in both if r[key] >= 0.90)
    b = set(r["ticker"] for r in both if r["per_xs"] >= cut)
    uni = len(a | b)
    return {
        "n": n, "spearman_selfpct_vs_absPER": sp,
        "xs_top10pct_cut_per": round(cut, 2),
        "overlap_jaccard_at_p90": round(len(a & b) / uni, 4) if uni else None,
        "n_self_p90": len(a), "n_xs_top10": len(b), "both": len(a & b),
    }


# ───────────────────────── ビンテージ1本を回す ─────────────────────────
def run_vintage(y, verbose=True):
    d = load_vintage(y)
    if not d:
        return None
    rows = d["rows"]
    j = d["join"]
    years = j.get("modal_years")
    pool = usable(rows)
    n_pool = len(pool)
    qpool = [r for r in pool if r.get("quality")]

    res = {
        "asof": d["asof"], "modal_years": years,
        "benchmark_spy_cagr": j["benchmark"]["tr_cagr"],
        "n_rows": len(rows), "n_full_pool": n_pool, "n_quality_in_pool": len(qpool),
        "base": {
            "median": med([r["tr_cagr"] for r in pool]),
            "ew": ew_cagr(pool, years),
            "kill_rate": round(sum(1 for r in pool if r["tr_cagr"] <= MDD_KILL) / n_pool, 4),
            "kill_n": sum(1 for r in pool if r["tr_cagr"] <= MDD_KILL),
            "win15_rate": round(sum(1 for r in pool if r["tr_cagr"] >= WIN) / n_pool, 4),
        },
        "coverage": {}, "grid": [], "health": {},
    }

    # ── Q2 被覆 ──
    for k in PCT_INDICATORS + PCT_EXTRA + Z_INDICATORS + ("per_xs",):
        c = sum(1 for r in pool if r.get(k) is not None)
        e = {"n": c, "frac": round(c / n_pool, 4) if n_pool else None,
             "below_half": bool(n_pool and c / n_pool < 0.5)}
        if k in Z_INDICATORS:
            hk = Z_HIST_KEY[k]
            c36 = sum(1 for r in pool
                      if r.get(k) is not None and (r.get(hk) or 0) >= 36)
            e["n_hist36"] = c36
            e["frac_hist36"] = round(c36 / n_pool, 4) if n_pool else None
            e["below_half"] = bool(n_pool and c36 / n_pool < 0.5)
        res["coverage"][k] = e
    # spx は定数（下の health で扱う）
    spx = sorted({r.get("spx_pe_pct") for r in pool if r.get("spx_pe_pct") is not None})
    res["coverage"]["spx_pe_pct"] = {
        "n": sum(1 for r in pool if r.get("spx_pe_pct") is not None),
        "distinct_values": spx,
        "constant_within_vintage": len(spx) <= 1,
        "testable_by_cross_section": False,
        "why": ("spx_pe_pct は買値時点の市場水準＝**1ビンテージに1つの定数**。"
                "横断面では全員を止めるか誰も止めないかしかなく、この設計では検定できない。"
                "検定するには asof を多数用意した『コホートの時系列』が要る"),
    }

    # ── 検出力の事前確認: そのサブプールの恒久毀損の実数が5社未満なら、
    #    閾値をどこに置いても基準1（分子>=5社）は**原理的に**満たせない ──
    power = {}
    for k in PCT_INDICATORS + PCT_EXTRA + Z_INDICATORS:
        hk = Z_HIST_KEY.get(k)
        sub = [r for r in pool if r.get(k) is not None
               and (hk is None or (r.get(hk) or 0) >= 36)]
        kn = sum(1 for r in sub if r["tr_cagr"] <= MDD_KILL)
        power[k] = {"n_eligible": len(sub), "kill_n_in_subpool": kn,
                    "c1_attainable": bool(kn >= PASS_TAIL_MIN_N),
                    "base_kill_rate": round(kn / len(sub), 4) if sub else None}
    res["power_c1"] = power

    # ── Q1 格子（full プール／参考で quality プールも同じ格子で回す）──
    for pool_name, P in (("full", pool), ("quality", qpool)):
        for k in PCT_INDICATORS + PCT_EXTRA:
            for t in PCT_GRID:
                r = judge(P, k, t, years)
                if r:
                    r["pool"] = pool_name
                    r["in_prereg_grid"] = k in PCT_INDICATORS
                    res["grid"].append(r)
        for k in Z_INDICATORS:
            for t in Z_GRID:
                r = judge(P, k, t, years, hist_key=Z_HIST_KEY[k], hist_min=36)
                if r:
                    r["pool"] = pool_name
                    r["in_prereg_grid"] = True
                    res["grid"].append(r)

    # ── Q3 健全性 ──
    h = res["health"]
    h["uniformity"] = {k: uniformity(pool, k) for k in PCT_INDICATORS + PCT_EXTRA}
    h["uniformity_quality_pool"] = {k: uniformity(qpool, k) for k in PCT_INDICATORS}

    # (b) hist_months を厳しくすると結論が変わるか
    sens = {}
    for hmin in (36, 60, 84):
        sub = [r for r in pool if (r.get("hist_months") or 0) >= hmin]
        if len(sub) < 30:
            sens[str(hmin)] = {"n": len(sub), "note": "n<30"}
            continue
        e = {"n": len(sub)}
        for k in PCT_INDICATORS:
            r = judge(sub, k, 0.90, years)
            if r:
                e[k] = {"n_elig": r["n_eligible"], "stop_n": r["stop"]["n"],
                        "stop_median": r["stop"].get("median"),
                        "pass_median": r["pass"].get("median"),
                        "stop_ew": r["stop"].get("ew"), "pass_ew": r["pass"].get("ew"),
                        "kill_ratio": r["kill_ratio"], "kill_n": r["stop"].get("kill_n"),
                        "c1": r["c1_left_tail"], "c2": r["c2_no_winner_capture"]}
        sens[str(hmin)] = e
    h["hist_months_sensitivity_at_p90"] = sens

    # (c) pe_pct と ps_pct の一致
    h["pe_vs_ps"] = {str(t): agreement(pool, "pe_pct", "ps_pct", t) for t in PCT_GRID}
    h["pe_vs_adjpe"] = {str(t): agreement(pool, "pe_pct", "adj_pe_pct", t) for t in PCT_GRID}
    h["pe_vs_pfcf"] = {str(t): agreement(pool, "pe_pct", "pfcf_pct", t) for t in PCT_GRID}

    # (d) 等ウェイトは右裾1社で決まっていないか
    #     「中央値だけで語らない」の裏返し——**等ウェイトだけで語ってもいけない**。
    #     等ウェイトは終価倍率の算術平均なので、n が数十〜数百でも1社で符号が変わる。
    tail = {}
    for k in PCT_INDICATORS:
        e = {}
        for t in PCT_GRID:
            sub = [r for r in pool if r.get(k) is not None]
            if len(sub) < 50:
                continue
            g = {"stop": [r for r in sub if r[k] >= t], "pass": [r for r in sub if r[k] < t]}
            b = {}
            for nm, grp in g.items():
                if len(grp) < 3:
                    continue
                s = sorted(grp, key=lambda r: -r["tr_total"])
                b[nm] = {
                    "n": len(s), "ew": ew_cagr(s, years),
                    "ew_drop_top1": ew_cagr(s[1:], years),
                    "top1": s[0]["ticker"], "top1_total": round(s[0]["tr_total"], 1),
                    "median": med([r["tr_cagr"] for r in s]),
                }
            if b:
                e[str(t)] = b
        if e:
            tail[k] = e
    h["ew_tail_sensitivity"] = tail

    # ── Q4 横断面PERとの相関（最重要の反証）──
    h["vs_cross_section"] = {k: vs_cross_section(pool, k)
                             for k in PCT_INDICATORS}
    # 横断面PER自身を同じ格子で遮断器にしたらどうか（比較の錨）
    xsp = [r for r in pool if r.get("per_xs") not in (None, 0)]
    if len(xsp) >= 50:
        vals = sorted(r["per_xs"] for r in xsp)
        xs_rules = []
        for q in (0.80, 0.85, 0.90, 0.95):
            cut = vals[min(len(vals) - 1, int(len(vals) * q))]
            for r in xsp:
                r["_xs_flag"] = r["per_xs"]
            rr = judge(xsp, "_xs_flag", cut, years)
            if rr:
                rr["quantile"] = q
                rr["key"] = "per_xs(横断面絶対PER・%d分位=%.1f)" % (int(q * 100), cut)
                rr.pop("stop_tickers", None)
                xs_rules.append(rr)
        h["cross_section_per_as_breaker"] = xs_rules
        for r in xsp:
            r.pop("_xs_flag", None)

    if verbose:
        print(f"\n===== asof {d['asof']}  窓{years}年  SPY {j['benchmark']['tr_cagr']:.1%} "
              f"／ full {n_pool}社（質実証 {len(qpool)}社）"
              f"／ ベース 中央値{res['base']['median']:.1%} 等ウェイト{res['base']['ew']:.1%} "
              f"恒久毀損{res['base']['kill_rate']:.1%}({res['base']['kill_n']}社)")
    return res


# ───────────────────────── 合否の集計（基準3・5込み）─────────────────────────
def collect(all_res):
    """指標×閾値×プール ごとに、ビンテージを跨いで基準1〜5を数える。"""
    idx = {}
    for y, r in all_res.items():
        if not r:
            continue
        for g in r["grid"]:
            k = (g["pool"], g["key"], g["thr"])
            idx.setdefault(k, {})[y] = g
    out = []
    for (pool, key, thr), byy in sorted(idx.items()):
        ok12 = [y for y, g in byy.items() if g["c1_left_tail"] and g["c2_no_winner_capture"]]
        ok4 = [y for y, g in byy.items() if g["c4_narrow"]]
        # 基準5(incremental)の代理: full で立った規則が **質実証プールでも** 1と2を保つか。
        # 歴史側には Ω・堀が無いので、四関門の相当物として『既に質で落ちない社だけ』を使う。
        rec = {
            "pool": pool, "key": key, "thr": thr,
            "in_prereg_grid": byy[list(byy)[0]]["in_prereg_grid"],
            "vintages": {str(y): {
                "n_elig": g["n_eligible"], "stop_n": g["stop"]["n"],
                "stop_frac": g["stop_frac"],
                "stop_median": g["stop"].get("median"), "pass_median": g["pass"].get("median"),
                "stop_ew": g["stop"].get("ew"), "pass_ew": g["pass"].get("ew"),
                "base_kill": g["base_kill_rate"],
                "stop_kill_rate": g["stop"].get("kill_rate"), "stop_kill_n": g["stop"].get("kill_n"),
                "kill_ratio": g["kill_ratio"],
                "stop_win15": g["stop"].get("win15_rate"), "pass_win15": g["pass"].get("win15_rate"),
                "c1": g["c1_left_tail"], "c2": g["c2_no_winner_capture"], "c4": g["c4_narrow"],
            } for y, g in sorted(byy.items())},
            "c12_vintages": sorted(ok12), "c3_robust": len(ok12) >= 2,
            "c4_vintages": sorted(ok4),
        }
        out.append(rec)
    # 基準5 を綴じる: 同じ 指標×閾値 の quality 版が1と2を2ビンテージ以上で保つか
    qmap = {(r["key"], r["thr"]): r for r in out if r["pool"] == "quality"}
    for r in out:
        q = qmap.get((r["key"], r["thr"]))
        r["c5_incremental_proxy"] = bool(q and q["c3_robust"])
        r["c5_note"] = ("歴史側にΩ・堀は無い。四関門の相当物として『質実証プールでも1と2が"
                        "2ビンテージ以上で保つか』を代理に使った")
        r["PASS_ALL"] = bool(
            r["in_prereg_grid"] and r["c3_robust"]
            and len(r["c4_vintages"]) >= 2
            and r["c5_incremental_proxy"]
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    vs = (a.asof,) if a.asof else VINTAGES
    res = {}
    for y in vs:
        res[y] = run_vintage(y, verbose=not a.quiet)
    summary = collect(res)
    doc = {
        "generated": "2026-08-09",
        "tool": "night/hist_val_full.py",
        "prereg": "out/hist_valuation_prereg.json",
        "lens": "full プールでの判定 ＋ 指標の健全性・被覆・反証（横断面PERとの相関）",
        "note_verdict_scope": ("事前登録は『合否は quality プールで判定する。full は参考』。"
                               "この器の PASS_ALL は full プールについての参考判定であり、正本の合否ではない"),
        "grid": {"pct": list(PCT_GRID), "z": list(Z_GRID), "spx": list(SPX_GRID)},
        "vintages": {str(k): v for k, v in res.items()},
        "rules": summary,
        "n_pass_all": sum(1 for r in summary if r["PASS_ALL"]),
        "reconcile_with_hist_val_gate_test": {
            "why": ("同じ台帳を見る二つの検査器が違うことを言ってはいけない(v9.9.65)ので、"
                    "違いを黙って残さず記録する"),
            "agree": "**両器とも合格規則ゼロ**（本器 full/quality 60本・兄弟器 66本）。結論は一致",
            "difference": ("止め率(stop_frac)の分母が違う。本器は『その指標が定義できる社』を分母にする"
                           "（欠測を通す側に入れると、被覆の低い指標ほど『狭い遮断器』に見えてしまうため）。"
                           "hist_val_gate_test.py はプール全体を分母にする（実運用の遮断器は測れない社を"
                           "止めないので、基準4『止めるのは15%以下』の実運用の読みとしてはこちらが正しい）。"
                           "実測 2018 quality pe_pct>=0.80: 止めた社数は **両器とも116社で完全一致**、"
                           "分母が 319（定義できる社）か 332（プール全体）かの差で 36.4% と 34.9%"),
            "verdict_impact": "無し（どちらの分母でも合格規則はゼロ）",
        },
        "not_tested": [{
            "indicator": "spx_pe_pct（B_market_level）",
            "reason": ("ビンテージ内で定数（2013=0.7563 / 2015=0.9114 / 2018=0.9019）。"
                       "横断面の分割ができないので、この設計では合否を出せない＝**判定不能**。"
                       "しかも3本とも格子(80/90/95)の下限80をまたぐ側に偏っており、"
                       "『市場が安いとき』の観測が一つも無い。黙って落とさず、ここに記録する"),
        }],
    }
    p = os.path.join(OUT, "hist_val_full.json")
    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        print(f"\n書いた: {p}  （規則 {len(summary)} 本・全基準合格 {doc['n_pass_all']} 本）")
    return doc


if __name__ == "__main__":
    main()
