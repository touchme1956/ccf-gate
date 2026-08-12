# night/retro_surprise.py — リターンを生むのは「予言できた事業」か「驚き」か（2026-08-12新設）
#
# ★この器が答える問い:
#   night/retro_business_vs_price.py が
#     ・入口の質 → **前方の事業** は ρ 0.63〜0.71 でよく当たる
#     ・入口の質 → **株価リターン** は ρ 0.08 でほぼ当たらない
#   と出した。そこから出る仮説は一つ——**予言できる分は既に値段に入っている**。
#   仮説が正しければ、次が同時に成り立つはずである:
#     (a) **実現した**事業（＝入口では知りようがない）は、リターンをよく当てる
#     (b) 実現した事業を「入口から予言できた分」と「驚き（残差）」に割ると、
#         **リターンを当てているのは驚きのほうだけ**
#   (b) が成り立てば、「指標を増やせば当てられる」という道は**構造的に閉じている**と言える
#   ——驚きは定義上、入口の情報では作れないから。
#
# ⚠ この器は判定を一つも持たない。規約・値・採点式・刻み・重み・関門・売却規律には触れない。
#   予測器ではない（実現値を説明変数に使うので、当然ながら投資には使えない）。**上限の測定**である。
#
# 測り方（新しい定数を発明していない）:
#   ・全部**順位**で行う（水準の外れ値に結論を預けない）。順位で回帰し、順位で残差を取る
#   ・予言できた分 = 入口の質（roic_med5）の順位から前方事業の順位を線形回帰した予測値
#     驚き = 前方事業の順位 − その予測値
#   ・入口の質は **roic_med5**（門0の through-cycle ROIC 相当）を基準に置く。
#     `--entry` で opm / score / roic_latest にも差し替えられる（結論が錨に依らないことを見るため）
#   ・多重検定の心配は無い（比べるのは3本だけ）。代わりに **ブートストラップで信頼区間**を出す
#
# 入力（すべて在庫・追加取得ゼロ）:
#   out/retro_cohort_{2013,2015}.json   … 入口の質 と 前方の事業（retro_cohort.py が gate0 の
#                                          関数定義を exec で取り込み窓だけ前方へずらしたもの）
#   out/retro_returns_{2013_all,2015_q,...}.json … 実現リターン（Yahoo adjclose＝配当込み）
#
# 出力: out/retro_surprise.json
# 実行: python3 night/retro_surprise.py [--json] [--entry roic_med5]

import json
import math
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
MIN_N = 150
NBOOT = 2000

BIZ = {"fwd_roic": ("fwd_roic_med5_a1", "前方ROIC(+6..+10年の中央値)"),
       "fwd_growth": ("fwd_cagr_10y", "前方売上CAGR(10年)"),
       "fwd_opm": ("fwd_opm_10y", "前方営業利益率(10年)")}


def rows(path, key="rows"):
    p = os.path.join(OUT, path)
    if not os.path.exists(p):
        return []
    d = json.load(open(p))
    return d[key] if isinstance(d, dict) and key in d else (d if isinstance(d, list) else [])


def ranks(xs):
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


def pearson(xs, ys):
    n = len(xs)
    if n < MIN_N:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def rho(a, b):
    """Spearman = 順位に対する Pearson"""
    return pearson(ranks(a), ranks(b))


def boot_ci(a, b, seed):
    """順位相関のブートストラップ95%区間。⚠順位は毎回引き直す（部分集合の順位で測るのが正しい）"""
    if len(a) < MIN_N:
        return None
    rnd = random.Random(seed)
    n = len(a)
    vals = []
    for _ in range(NBOOT):
        idx = [rnd.randrange(n) for _ in range(n)]
        r = pearson(ranks([a[i] for i in idx]), ranks([b[i] for i in idx]))
        if r is not None:
            vals.append(r)
    if len(vals) < NBOOT * 0.9:
        return None
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]


def split(entry, fwd):
    """前方事業の順位を、入口の質の順位から線形回帰して
    『予言できた分(fit)』と『驚き(residual)』へ割る。
    ⚠ 順位のまま回帰するので、当てはめは単調変換に頑健。R2 = ρ² がそのまま予言できた割合になる"""
    xr, yr = ranks(entry), ranks(fwd)
    n = len(xr)
    mx, my = sum(xr) / n, sum(yr) / n
    sxx = sum((x - mx) ** 2 for x in xr)
    sxy = sum((xr[i] - mx) * (yr[i] - my) for i in range(n))
    b = sxy / sxx if sxx > 0 else 0.0
    fit = [my + b * (x - mx) for x in xr]
    res = [yr[i] - fit[i] for i in range(n)]
    return fit, res, (b * b * sxx / sum((y - my) ** 2 for y in yr)) if n > 1 else None


def prices(asof):
    px = {}
    for name in (f"retro_returns_{asof}_all.json", f"retro_returns_{asof}_q.json",
                 f"retro_returns_{asof}.json"):
        for r in rows(name):
            if r.get("ticker") and r.get("tr_cagr") is not None and r["ticker"] not in px:
                px[r["ticker"]] = r["tr_cagr"]
    return px


def analyse(asof, entry_key):
    co = {r["ticker"]: r for r in rows(f"retro_cohort_{asof}.json") if r.get("ticker")}
    px = prices(asof)
    out = {"asof": asof, "entry": entry_key, "targets": {}}
    for name, (col, lab) in BIZ.items():
        tk = [t for t in co
              if co[t].get(entry_key) is not None and co[t].get(col) is not None and t in px]
        if len(tk) < MIN_N:
            out["targets"][name] = {"n": len(tk), "note": "n不足"}
            continue
        e = [co[t][entry_key] for t in tk]
        f = [co[t][col] for t in tk]
        r = [px[t] for t in tk]
        fit, res, r2 = split(e, f)
        out["targets"][name] = {
            "label": lab, "n": len(tk),
            "rho_entry_to_biz": round(rho(e, f), 3),
            "r2_predictable": round(r2, 3) if r2 is not None else None,
            "rho_entry_to_return": round(rho(e, r), 3),
            "rho_realized_biz_to_return": round(rho(f, r), 3),
            "rho_predicted_part_to_return": round(rho(fit, r), 3),
            "rho_surprise_to_return": round(rho(res, r), 3),
            "ci_realized_biz": boot_ci(f, r, 2026 + asof),
            "ci_surprise": boot_ci(res, r, 8120 + asof),
            "ci_entry": boot_ci(e, r, 5280 + asof),
        }
    return out


MOAT = {2013: ["retro_moat_2013.json", "retro_moat_2013q.json"],
        2015: ["retro_moat_2015.json", "retro_moat_2015q.json", "retro_moat_2015qb.json"]}


def moat_vs_surprise(asof, entry_key):
    """★この検証で唯一13年生き延びた指標＝原本読解の irr（移行障壁の型）は、
    『驚き』を当てているのか。当てているなら、なぜ irr=85 だけが報われたのかの機構になる。
    ⚠ irr=85 は母集団の1〜3%しか出ない稀なラベルなので n は極小。**順序として**も測る"""
    m = {}
    for f in MOAT.get(asof, []):
        for r in rows(f):
            t, v = r.get("ticker"), r.get("irr")
            if t and v is not None and t not in m:
                m[t] = v
    if not m:
        return None
    co = {r["ticker"]: r for r in rows(f"retro_cohort_{asof}.json") if r.get("ticker")}
    px = prices(asof)
    out = {"n_read": len(m), "by_target": {}, "by_grade": {}}
    for name, (col, lab) in BIZ.items():
        tk = [t for t in m
              if t in co and co[t].get(entry_key) is not None and co[t].get(col) is not None and t in px]
        if len(tk) < 60:
            out["by_target"][name] = {"n": len(tk), "note": "n不足（60未満）"}
            continue
        e = [co[t][entry_key] for t in tk]
        f2 = [co[t][col] for t in tk]
        r2 = [px[t] for t in tk]
        _fit, res, _ = split(e, f2)
        irr = [m[t] for t in tk]
        rec = {
            "label": lab, "n": len(tk),
            "rho_irr_to_surprise": round(rho(irr, res), 3),
            "rho_irr_to_realized_biz": round(rho(irr, f2), 3),
            "rho_irr_to_return": round(rho(irr, r2), 3),
            "ci_irr_to_surprise": boot_ci(irr, res, 1985 + asof),
        }
        # ⚠規模の言い換えでないことを確かめる——この検証で株価に対して唯一残った指標は
        #   売上規模だった（retro_business_vs_price）。規模を order で除いた偏順位相関を出す
        sz = [co[t].get("rev_asof") for t in tk]
        if all(v is not None for v in sz):
            a1 = rho(irr, res)
            a2 = rho(irr, sz)
            a3 = rho(sz, res)
            den = math.sqrt((1 - a2 * a2) * (1 - a3 * a3))
            rec["rho_irr_to_size"] = round(a2, 3)
            rec["rho_size_to_surprise"] = round(a3, 3)
            rec["partial_irr_surprise_given_size"] = round((a1 - a2 * a3) / den, 3) if den > 0 else None
        out["by_target"][name] = rec
    # 刻みごとの実数（順位相関は稀なラベルを薄める。刻みで直接見せる）
    tk = [t for t in m if t in px]
    if tk:
        grades = {}
        for t in tk:
            grades.setdefault(m[t], []).append(px[t])
        base = sorted(px[t] for t in tk)
        out["by_grade"] = {
            "base_median": round(base[len(base) // 2], 4), "base_n": len(base),
            "grades": {str(g): {"n": len(v), "median": round(sorted(v)[len(v) // 2], 4),
                                "p15plus": round(sum(1 for x in v if x >= 0.15) / len(v), 3)}
                       for g, v in sorted(grades.items())}}
    return out


def main():
    as_json = "--json" in sys.argv
    entry = "roic_med5"
    if "--entry" in sys.argv:
        entry = sys.argv[sys.argv.index("--entry") + 1]

    out = {"generated": "2026-08-12",
           "question": "リターンを生むのは『入口から予言できた事業』か『驚き』か（上限の測定・判定はしない）",
           "entry_signal": entry,
           "method": "すべて順位。前方事業の順位を入口の質の順位で回帰し、予言できた分と驚きへ割る",
           "anchors": [analyse(a, entry) for a in (2013, 2015)]}
    # 錨を替えても結論が動かないことを同じ実行で見せる
    out["entry_robustness"] = {
        k: {a["asof"]: {n: v.get("rho_surprise_to_return") for n, v in a["targets"].items()}
            for a in [analyse(2013, k), analyse(2015, k)]}
        for k in ("roic_latest", "opm", "score")}

    out["moat_vs_surprise"] = {str(a): moat_vs_surprise(a, entry) for a in (2013, 2015)}

    json.dump(out, open(os.path.join(OUT, "retro_surprise.json"), "w"),
              ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for a in out["anchors"]:
        print(f"\n=== asof={a['asof']}（入口の質＝{a['entry']}）===")
        for n, v in a["targets"].items():
            if "note" in v:
                print(f"  {n}: {v['note']} (n={v['n']})")
                continue
            print(f"  【{v['label']}】n={v['n']}")
            print(f"    入口 → 事業            ρ={v['rho_entry_to_biz']:+.3f}"
                  f"（予言できた割合 R²={v['r2_predictable']}）")
            print(f"    入口 → ★リターン        ρ={v['rho_entry_to_return']:+.3f}  CI{v['ci_entry']}")
            print(f"    **実現した事業** → ★リターン ρ={v['rho_realized_biz_to_return']:+.3f}  CI{v['ci_realized_biz']}")
            print(f"      うち 予言できた分 → ★  ρ={v['rho_predicted_part_to_return']:+.3f}")
            print(f"      うち **驚き** → ★       ρ={v['rho_surprise_to_return']:+.3f}  CI{v['ci_surprise']}")
    print("\n=== 入口の錨を替えても驚きの側が効くか（驚き→リターンのρ）===")
    for k, d in out["entry_robustness"].items():
        print(f"  {k:<12}" + "  ".join(f"{a}:{v}" for a, v in d.items()))
    print("\n=== ★原本読解の irr（移行障壁の型）は『驚き』を当てているか ===")
    for a, d in out["moat_vs_surprise"].items():
        if not d:
            continue
        print(f"  asof={a}（読解{d['n_read']}社）")
        for n, v in d["by_target"].items():
            if "note" in v:
                print(f"    {n}: {v['note']} (n={v['n']})")
                continue
            print(f"    {v['label']:<24}n={v['n']}  irr→驚き ρ={v['rho_irr_to_surprise']:+.3f}"
                  f" CI{v['ci_irr_to_surprise']}   irr→実現事業 {v['rho_irr_to_realized_biz']:+.3f}"
                  f"   irr→★リターン {v['rho_irr_to_return']:+.3f}"
                  + (f"   規模を除いた偏ρ={v['partial_irr_surprise_given_size']:+.3f}"
                     f"（irr↔規模 {v['rho_irr_to_size']:+.3f}）" if v.get("partial_irr_surprise_given_size") is not None else ""))
        g = d.get("by_grade") or {}
        if g:
            print(f"    刻み別リターン（ベース中央値 {g['base_median']:+.3f} / n={g['base_n']}）:")
            for k, v in g["grades"].items():
                print(f"      irr={k:<4}n={v['n']:<4}中央値 {v['median']:+.4f}  15%+ {v['p15plus']}")


if __name__ == "__main__":
    main()
