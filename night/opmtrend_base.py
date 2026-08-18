# night/opmtrend_base.py — 利益率トレンド検証の**土台**（2026-08-18新設）
#
# ★この器は**合否を一切判定しない**。後続の測定（H1〜H6）が全部これを読むことで、
#   「同じ台帳を見る二つの検査器が違うことを言う」(v9.9.65) を構造で防ぐ。
#
# 事前登録: out/opm_trend_prereg.json（測定を1件も見る前にコミット済み）。
#   基準・線・限界はそこに固定してある。**この器は線を一つも持たない。**
#
# やること:
#   ① 8ビンテージの features2（信号）と returns（結果）を ticker で結合し、SIC2 を添える
#   ② **単位の検算**——この台帳は「opm が比率(0.0979)なのに >=10 と比べて全社を落とす」罠を2度踏んでいる
#      （fill_sht.py の gate0_all.csv・beat_spy_rule.py の opm）。3度目を踏まないため、
#      生の中央値・%換算後の中央値・opmD5<0 の割合を**ビンテージ別に印字**する
#   ③ **到達可能性を結果の前に数える**——v1/v3/v11 が三度踏んだ「基準が稀少事象の実数で到達不能」を
#      四度目にしない。各ビンテージ×各プールで「神の遮断器（毀損社を先に知って止める）でも
#      分子5社に届くか」を数え、届かないセルは reachable=false と記録する
#   ④ 各ビンテージのベンチマークと窓の年数
#
# ⚠ この器が**判断したこと**（すべて出力JSONに記録する）:
#   (a) returns の出所は `_all` → `_q` → 素 の優先順（hist_val_join.py:74 と同一）。
#       **retro_returns_2013.json は pass70+ctrl70=140行の抽出**で、_all が956行。
#       素を読むと「139社の標本と946社の母集団を比べる」既記録の罠をそのまま踏む
#   (b) **2019〜2022 のベンチマークは SPY ではない**——パネル自身の等ウェイト指数(EW)。
#       在庫にSPYの月次が無いため。**SPYと呼ばない**（呼べば「基準の違う二つ」を自分で作る）
#   (c) opm の単位は**ファイル単位で判定**して全行へ当てる（中央|opm|≈0.12＝比率）。
#       per-row の帯検問（|x|<=3 なら x*100）は**極端な行で file単位と食い違う**ので、
#       食い違う行を名指しで記録する（黙って片方を採らない）
#   (d) **opmD5 は生の比率pt のまま持つ**——事前登録の H2 の閾値が
#       「opmD5 < -0.02 / -0.05 / -0.10（**絶対の比率pt**）」と比率で書いてあるため。
#       読みやすさ用に opmD5_pp（×100）を別欄で添える。**二つを混ぜて割らない**
#
# 実行: python3 night/opmtrend_base.py [--json]
# 在庫: out/opmtrend_base.json

import json
import os
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

# 窓と結合は既存の実装をそのまま使う（二重実装を作らない・v9.9.65）。
# retro_persistence は main() が __name__ ガードの中なので import に副作用は無い。
from retro_persistence import panel, cagr, ymk  # noqa: E402

VINTAGES = [2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022]

# 事前登録どおり（新しい定数を一つも作らない）
HURDLE = 0.15        # 前方年率 >= 15% ＝ 当たり
IMPAIR = -0.15       # 前方年率 <= -15% ＝ 恒久毀損
QUAL_OPM_PCT = 10.0  # 質実証: 営業利益率 >= 10%（%で比べる。帯検問を通してから）
QUAL_FCFPOS = 5      # 質実証: 5年FCF全年黒字
MIN_NUM = 5          # H2/H4 が要求する分子の下限
MAX_STOP = 0.15      # H2/H4 が要求する止率の上限


def load(fn):
    with open(os.path.join(OUT, fn), encoding="utf-8") as f:
        return json.load(f)


def returns_src(y):
    """hist_val_join.py:74 と同一の優先順。どれを読んだかを返す。"""
    for nm in (f"retro_returns_{y}_all.json", f"retro_returns_{y}_q.json",
               f"retro_returns_{y}.json"):
        if os.path.exists(os.path.join(OUT, nm)):
            return nm
    return None


def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def unit_scale(vals):
    """★ファイル単位で単位を決める。per-row の帯検問は極端な行で誤る。

    返り値 (scale, why)。scale=100 なら比率→%、1 なら既に%。
    判定は中央値の絶対値——営業利益率の分布の中心が 0.03〜0.60 なら比率、
    3〜60 なら%。どちらでもなければ None を返して**推測しない**。
    """
    v = sorted(abs(x) for x in vals if x is not None)
    if not v:
        return None, "値が一つも無い"
    m = st.median(v)
    if m <= 3:
        return 100.0, f"中央|x|={m:.4f} <= 3 ＝比率（×100 で%へ）"
    if m <= 300:
        return 1.0, f"中央|x|={m:.4f} > 3 ＝既に%"
    return None, f"中央|x|={m:.4f} ＝どちらとも判定不能"


def band_row(x):
    """事前登録／指示が求める per-row の帯検問（|x|<=3 なら ×100）。
    ★file単位と食い違う行を見つけるためだけに使う。採点には使わない。"""
    if x is None:
        return None
    return x * 100.0 if abs(x) <= 3 else x


def load_base():
    """★後続の測定（H1〜H6）はこれを呼ぶ。土台を再実装しない（v9.9.65）。

    返り値は out/opmtrend_base.json そのもの。無ければ作る。
    """
    fp = os.path.join(OUT, "opmtrend_base.json")
    if not os.path.exists(fp):
        o = build()
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=1)
        return o
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def build():
    sic = {r["ticker"]: r for r in load("retro_sic.json")["rows"]}

    rows = []
    unit_check = {}
    vintage_meta = {}
    reach = {}
    warns = []

    for y in VINTAGES:
        fsrc = f"retro_features2_{y}.json"
        rsrc = returns_src(y)
        fd = load(fsrc)
        rd = load(rsrc)

        frows = fd["rows"]
        rmap = {r["ticker"]: r for r in rd["rows"]}

        # ---- ② 単位の検算（結合の前に。単位を誤ると全部が静かに壊れる） ----
        opm_raw = [r.get("opm") for r in frows]
        d5_raw = [r.get("opmD5") for r in frows]
        scale, why = unit_scale(opm_raw)
        if scale is None:
            warns.append(f"{y}: opm の単位を判定できない（{why}）——このビンテージは測らない")
            continue
        if scale != 100.0:
            warns.append(f"{y}: opm が比率ではない（{why}）＝既存在庫と基準が違う。要確認")

        d5_scale, d5_why = unit_scale(d5_raw)

        # per-row 帯検問と file単位が食い違う行（|x|>3 の行で必ず食い違う）
        dis = [{"ticker": r["ticker"], "opm_raw": r["opm"],
                "file_pct": round(r["opm"] * scale, 3),
                "band_pct": round(band_row(r["opm"]), 3)}
               for r in frows
               if r.get("opm") is not None
               and abs(round(r["opm"] * scale, 6) - round(band_row(r["opm"]), 6)) > 1e-6]

        d5n = [x for x in d5_raw if x is not None]
        neg_share = (sum(1 for x in d5n if x < 0) / len(d5n)) if d5n else None

        unit_check[str(y)] = {
            "features_src": fsrc,
            "opm_raw_median": round(med(opm_raw), 6) if med(opm_raw) is not None else None,
            "opm_scale": scale, "opm_scale_why": why,
            "opm_pct_median": round(med(opm_raw) * scale, 4) if med(opm_raw) is not None else None,
            "opm_n": sum(1 for x in opm_raw if x is not None),
            "opm_missing": sum(1 for x in opm_raw if x is None),
            "opmD5_raw_median": round(med(d5_raw), 6) if med(d5_raw) is not None else None,
            "opmD5_scale_detected": d5_scale, "opmD5_scale_why": d5_why,
            "opmD5_kept_as": "生の比率pt（事前登録 H2 の閾値 -0.02/-0.05/-0.10 が比率のため）",
            "opmD5_n": len(d5n),
            "opmD5_missing": sum(1 for x in d5_raw if x is None),
            "opmD5_neg_share": round(neg_share, 4) if neg_share is not None else None,
            "opmD5_neg_share_ok": (0.40 <= neg_share <= 0.60) if neg_share is not None else None,
            "band_test_disagree_n": len(dis),
            "band_test_disagree": dis,
        }
        if neg_share is not None and not (0.40 <= neg_share <= 0.60):
            warns.append(f"{y}: opmD5<0 の割合が {neg_share:.1%} ＝50%から大きく外れる。"
                         f"単位・欄名・照合の失敗を疑うこと")

        # ---- ① 結合 ----
        n_join = 0
        for r in frows:
            t = r["ticker"]
            rr = rmap.get(t)
            if rr is None or rr.get("tr_cagr") is None:
                continue
            opm = r.get("opm")
            opm_pct = opm * scale if opm is not None else None
            fcf = r.get("fcfpos5")
            qual_na = (opm_pct is None or fcf is None)   # 測れなかった＝「落ちた」ではない
            qual = (not qual_na and opm_pct >= QUAL_OPM_PCT and fcf >= QUAL_FCFPOS)
            s = sic.get(t, {})
            rows.append({
                "vintage": y, "ticker": t,
                "opmD5": r.get("opmD5"),
                "opmD5_pp": (round(r["opmD5"] * 100.0, 4)
                             if r.get("opmD5") is not None else None),
                "opm": (round(opm_pct, 4) if opm_pct is not None else None),
                "opm_raw": opm,
                "fcfpos5": fcf,
                "streak_opm": r.get("streak_opm"),
                "cagr5": r.get("cagr5"),
                "accel": r.get("accel"),
                "gm": r.get("gm"),
                "rev": r.get("rev"),
                "tr_cagr": rr.get("tr_cagr"),
                "years": rr.get("years"),
                "mdd": rr.get("mdd"),
                "sic2": s.get("sic2"), "sicDesc": s.get("sicDesc"),
                "qual": qual, "qual_na": qual_na,
            })
            n_join += 1

        yrs = [rr["years"] for rr in rd["rows"] if rr.get("years") is not None]
        ymed = st.median(yrs) if yrs else None
        b = rd.get("benchmark", {}) or {}
        bsym = b.get("symbol")
        is_spy = isinstance(bsym, str) and bsym.strip().upper() == "SPY"
        vintage_meta[str(y)] = {
            "features_src": fsrc, "returns_src": rsrc,
            "features_n": len(frows), "returns_n": len(rd["rows"]),
            "joined_n": n_join,
            "deadline": fd.get("deadline"), "asof_date": rd.get("asof_date"),
            "now_date": rd.get("now_date"),
            "benchmark_symbol": bsym,
            "benchmark_is_spy": is_spy,
            "benchmark_tr_cagr": b.get("tr_cagr"),
            "benchmark_years": b.get("years"),
            "years_median": ymed,
            "years_short_n": sum(1 for v in yrs if ymed and v < ymed * 0.9),
            "years_short": [(rr["ticker"], rr["years"]) for rr in rd["rows"]
                            if ymed and rr.get("years") is not None
                            and rr["years"] < ymed * 0.9],
        }
        if not is_spy:
            warns.append(f"{y}: ベンチマークは SPY ではない（{bsym}）。"
                         f"**SPYと呼ばないこと**——呼べば『基準の違う二つ』を自分で作る")
        if rsrc != f"retro_returns_{y}_all.json" and os.path.exists(
                os.path.join(OUT, f"retro_returns_{y}_all.json")):
            warns.append(f"{y}: returns の出所が _all ではない（{rsrc}）")

    # ---- ③ 到達可能性（**結果を見る前に**数える） ----
    for y in VINTAGES:
        vr = [r for r in rows if r["vintage"] == y]
        for pool, sel in (("all", lambda r: True),
                          ("qual", lambda r: r["qual"] and not r["qual_na"])):
            p_ = [r for r in vr if sel(r)]
            n = len(p_)
            imp = [r for r in p_ if r["tr_cagr"] <= IMPAIR]
            hit = [r for r in p_ if r["tr_cagr"] >= HURDLE]
            # ★到達可能性は「全毀損社を止める」ではない——遮断器は毀損社の**部分集合**を
            #   止めてもよい。初版はそこを固定していて、**毀損が最も多い 2021/all(144社)を
            #   『止率15.1%>15%』で判定不能にする**という正反対の誤りを出した（検算で発見）。
            #   拘束するのは (a)分子 >= MIN_NUM (b)MIN_NUM社が止率の上限に収まるか だけ。
            #   濃縮の上限は 1/毀損率（止めた全員が毀損のとき）。
            base = (len(imp) / n) if n else None
            fits = (n > 0 and MIN_NUM / n <= MAX_STOP)
            maxconc = (1.0 / base) if base else None
            ok = (len(imp) >= MIN_NUM and fits
                  and maxconc is not None and maxconc >= 2.0)
            why = None
            if not ok:
                if len(imp) < MIN_NUM:
                    why = "毀損の実数 %d < 分子の下限 %d" % (len(imp), MIN_NUM)
                elif not fits:
                    why = "分子%d社が止率の上限%.0f%%に収まらない（n=%d）" % (MIN_NUM, MAX_STOP * 100, n)
                else:
                    why = "濃縮の上限 %.1f倍 < 2.0倍（毀損率が高すぎる）" % (maxconc or 0)
            reach[f"{y}/{pool}"] = {
                "vintage": y, "pool": pool, "n": n,
                "n_impair": len(imp),
                "base_impair": round(base, 4) if base is not None else None,
                "n_hurdle": len(hit),
                "base_hurdle": round(len(hit) / n, 4) if n else None,
                "max_concentration": round(maxconc, 2) if maxconc else None,
                "stop_rate_if_all_impaired": round(base, 4) if base is not None else None,
                "min_stop_rate_for_num5": round(MIN_NUM / n, 4) if n else None,
                "reachable": ok,
                "why_not": why,
                "pool_excluded_na": sum(1 for r in vr if r["qual_na"]),
                "pool_excluded_fail": sum(1 for r in vr if not r["qual"] and not r["qual_na"]),
            }

    # ---- ③b opmD5 の被覆と欠測の偏り ----
    # ★2013 は窓に FY2008 が要り XBRL 被覆が薄い（既記録: 「大型早期適用社への偏り」）。
    #   欠測が無作為でないなら、そのビンテージの opmD5 は**別の母集団**を測っている。
    cover = {}
    for y in VINTAGES:
        vr = [r for r in rows if r["vintage"] == y]
        have = [r for r in vr if r["opmD5"] is not None]
        miss = [r for r in vr if r["opmD5"] is None]
        rv_h = [r["rev"] for r in have if r.get("rev")]
        rv_m = [r["rev"] for r in miss if r.get("rev")]
        tr_h = [r["tr_cagr"] for r in have]
        tr_m = [r["tr_cagr"] for r in miss]
        cover[str(y)] = {
            "n": len(vr), "with_opmD5": len(have), "missing": len(miss),
            "coverage": round(len(have) / len(vr), 4) if vr else None,
            "rev_med_with": round(st.median(rv_h) / 1e6, 1) if rv_h else None,
            "rev_med_missing": round(st.median(rv_m) / 1e6, 1) if rv_m else None,
            "rev_ratio": (round(st.median(rv_h) / st.median(rv_m), 2)
                          if rv_h and rv_m and st.median(rv_m) else None),
            "tr_med_with": round(st.median(tr_h), 4) if tr_h else None,
            "tr_med_missing": round(st.median(tr_m), 4) if tr_m else None,
        }
        if vr and len(have) / len(vr) < 0.70:
            warns.append(f"{y}: opmD5 の被覆が {len(have)}/{len(vr)}"
                         f"（{len(have)/len(vr):.0%}）——欠測が半分近い。"
                         f"このビンテージの opmD5 は**別の母集団**を測っている疑い。"
                         f"H1 の『8ビンテージすべてで符号が同じ』を当てるときに必ず注記すること")

    # ---- ④ 月次パネルの被覆（H6 が重ならない窓を作れるか） ----
    try:
        pn = panel()
        tk = set(r["ticker"] for r in rows)
        cov = {"panel_tickers": len(pn),
               "joined_tickers": len(tk),
               "with_panel": len(tk & set(pn)),
               "without_panel": sorted(tk - set(pn))[:20],
               "without_panel_n": len(tk - set(pn)),
               "note": "H6（重ならない窓）が使える母集団。panel()/cagr() は "
                       "night/retro_persistence.py の実装をそのまま import している"}
    except Exception as e:                                   # noqa: BLE001
        cov = {"error": repr(e)}
        warns.append("月次パネルを読めなかった: %r" % (e,))

    return {
        "generated": "2026-08-18",
        "tool": "night/opmtrend_base.py",
        "prereg": "out/opm_trend_prereg.json",
        "role": "土台。**合否を一切判定しない**。線も閾値も持たない。",
        "constants_from_prereg": {
            "HURDLE": HURDLE, "IMPAIR": IMPAIR,
            "QUAL_OPM_PCT": QUAL_OPM_PCT, "QUAL_FCFPOS": QUAL_FCFPOS,
            "MIN_NUM": MIN_NUM, "MAX_STOP": MAX_STOP,
        },
        "decisions": {
            "returns_priority": "_all -> _q -> 素（hist_val_join.py:74 と同一）",
            "opm_unit": "ファイル単位で判定し全行へ当てる。per-row 帯検問との食い違いは名指しで記録",
            "opmD5_unit": "生の比率pt のまま（事前登録の閾値が比率のため）。%pt は opmD5_pp に別欄",
            "benchmark": "2019〜2022 は SPY ではなくパネル自身の等ウェイト指数(EW)",
        },
        "unit_check": unit_check,
        "vintage_meta": vintage_meta,
        "reachability": reach,
        "opmD5_coverage": cover,
        "panel_coverage": cov,
        "warnings": warns,
        "n_rows": len(rows),
        "rows": rows,
    }


def main():
    o = build()

    print("=" * 78)
    print("opmtrend_base — 利益率トレンド検証の土台（合否は一切判定しない）")
    print("=" * 78)

    print("\n[1] 単位の検算（この台帳は opm の単位で2度事故を起こしている）")
    print(f"  {'年':>5} {'opm生中央':>10} {'倍率':>5} {'opm%中央':>9} "
          f"{'opmD5生中央':>11} {'opmD5<0':>8} {'判定':>6} {'帯検問と不一致':>12}")
    for y in VINTAGES:
        u = o["unit_check"].get(str(y))
        if not u:
            print(f"  {y:>5}  ——測定できず")
            continue
        ok = "OK" if u["opmD5_neg_share_ok"] else "⚠外れ"
        print(f"  {y:>5} {u['opm_raw_median']:>10.5f} {u['opm_scale']:>5.0f} "
              f"{u['opm_pct_median']:>8.2f}% {u['opmD5_raw_median']:>11.5f} "
              f"{u['opmD5_neg_share']:>7.1%} {ok:>6} {u['band_test_disagree_n']:>12}")
    print("  ★読み方の注意: **×100 は符号を変えない**ので、opmD5<0 の割合は"
          "『倍率の誤り』を検出しない。")
    print("    これが検出するのは**欄名の取り違え・照合の失敗**（別の列を掴む/結合が空になる）。")
    print("    倍率の誤りを検出するのは中央値のほう（|opm| の中央が 0.12 ＝比率と確定）。")
    dis_all = {}
    for y in VINTAGES:
        for d in o["unit_check"].get(str(y), {}).get("band_test_disagree", []):
            dis_all.setdefault(d["ticker"], []).append((y, d["opm_raw"], d["file_pct"], d["band_pct"]))
    print(f"  ★file単位と per-row 帯検問が食い違う銘柄: {len(dis_all)}社"
          f"（|opm|>3 の行。file単位を採用し、食い違いは在庫に名指しで記録した）")
    for t, v in sorted(dis_all.items())[:6]:
        y0, raw, fp, bp = v[0]
        print(f"    {t:<6} 生 {raw:>12.4f} → file {fp:>10.1f}% / 帯検問 {bp:>8.2f}%  "
              f"（{len(v)}ビンテージ）")

    print("\n[2] ビンテージ別の n と窓")
    print(f"  {'年':>5} {'features':>9} {'returns':>8} {'結合':>6} {'opmD5あり':>9} "
          f"{'ベンチ':>26} {'年率':>7} {'窓年':>6} {'短い行':>6}")
    for y in VINTAGES:
        m = o["vintage_meta"].get(str(y))
        if not m:
            continue
        u = o["unit_check"][str(y)]
        vr = [r for r in o["rows"] if r["vintage"] == y]
        d5 = sum(1 for r in vr if r["opmD5"] is not None)
        bs = (m["benchmark_symbol"] or "")[:24]
        mark = " " if m["benchmark_is_spy"] else "!"
        print(f"  {y:>5} {m['features_n']:>9} {m['returns_n']:>8} {m['joined_n']:>6} "
              f"{d5:>9} {mark}{bs:>25} {m['benchmark_tr_cagr']:>7.4f} "
              f"{m['years_median']:>6.2f} {m['years_short_n']:>6}")
    print("  ! ＝ベンチマークが SPY ではない（パネル自身の等ウェイト指数）")
    print("  結果の出所（_all -> _q -> 素 の優先順）:")
    for y in VINTAGES:
        m = o["vintage_meta"].get(str(y))
        if m:
            alt = os.path.join(OUT, f"retro_returns_{y}.json")
            n_plain = (len(json.load(open(alt, encoding="utf-8"))["rows"])
                       if os.path.exists(alt) else None)
            note = ("  ★素は %d行の抽出＝素を読むと『標本と母集団を比べる』既記録の罠"
                    % n_plain) if (n_plain and n_plain < m["returns_n"]) else ""
            print(f"    {y}: {m['returns_src']}（{m['returns_n']}行）{note}")

    print("\n[3] 到達可能性（★結果を見る前に数える。届かないセルは合否から外す）")
    print("  ＝『毀損社を先に知っている神の遮断器なら基準を満たせるか』。")
    print("    遮断器は毀損社の**部分集合**を止めてよいので、拘束するのは")
    print("    (a)毀損の実数 >= 5社  (b)5社が止率上限15%に収まる  (c)濃縮の上限 >= 2.0倍 の3つ。")
    print(f"  {'年':>5} {'プール':>5} {'n':>5} {'毀損':>5} {'毀損率':>7} "
          f"{'15%+':>5} {'基礎率':>7} {'濃縮上限':>8} {'到達':>5}  理由")
    for y in VINTAGES:
        for pool in ("all", "qual"):
            r = o["reachability"].get(f"{y}/{pool}")
            if not r:
                continue
            ok = "✓" if r["reachable"] else "✗"
            print(f"  {y:>5} {pool:>5} {r['n']:>5} {r['n_impair']:>5} "
                  f"{(r['base_impair'] or 0):>6.1%} {r['n_hurdle']:>5} "
                  f"{(r['base_hurdle'] or 0):>6.1%} "
                  f"{(r['max_concentration'] or 0):>7.1f}x {ok:>5}  "
                  f"{r['why_not'] or ''}")
    nr = [k for k, v in o["reachability"].items() if not v["reachable"]]
    print(f"  ★判定不能セル: {len(nr)}/{len(o['reachability'])} — "
          f"{', '.join(nr) if nr else 'なし'}")
    print(f"  {'年':>5} {'質実証n':>7} {'測れず除外':>10} {'測って落選':>10}   "
          f"（★『測れなかった』を『質を満たさない』と読まない＝ルール7）")
    for y in VINTAGES:
        r = o["reachability"].get(f"{y}/qual")
        if r:
            print(f"  {y:>5} {r['n']:>7} {r['pool_excluded_na']:>10} "
                  f"{r['pool_excluded_fail']:>10}")

    print("\n[3b] opmD5 の被覆と欠測の偏り")
    print("  ★欠測が無作為でないなら、そのビンテージの opmD5 は**別の母集団**を測っている")
    print(f"  {'年':>5} {'n':>5} {'opmD5あり':>9} {'被覆':>6} "
          f"{'売上中央(あり)':>14} {'売上中央(欠測)':>14} {'倍':>6} "
          f"{'前方年率(あり)':>13} {'(欠測)':>8}")
    for y in VINTAGES:
        c = o["opmD5_coverage"].get(str(y))
        if not c:
            continue
        print(f"  {y:>5} {c['n']:>5} {c['with_opmD5']:>9} {c['coverage']:>5.0%} "
              f"{(c['rev_med_with'] or 0):>13,.0f}M {(c['rev_med_missing'] or 0):>13,.0f}M "
              f"{(c['rev_ratio'] or 0):>5.2f}x {(c['tr_med_with'] or 0):>12.1%} "
              f"{(c['tr_med_missing'] or 0):>7.1%}")

    print("\n[4] 月次パネルの被覆（H6用）")
    c = o["panel_coverage"]
    if "error" in c:
        print("  ⚠", c["error"])
    else:
        print(f"  パネル {c['panel_tickers']}社 / 結合した銘柄 {c['joined_tickers']}社 / "
              f"両方ある {c['with_panel']}社 / パネルに無い {c['without_panel_n']}社")

    if o["warnings"]:
        print("\n[5] ⚠ 警告（黙って飛ばさない）")
        seen = set()
        for w in o["warnings"]:
            if w not in seen:
                print("  -", w)
                seen.add(w)

    p = os.path.join(OUT, "opmtrend_base.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    print(f"\n書いた: {p}  （{o['n_rows']} 行）")

    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in o.items() if k != "rows"},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
