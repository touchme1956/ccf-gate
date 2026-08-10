# night/hist_val_join.py — 自己相対バリュエーション在庫に「前方リターン」と「プールの印」を綴じる
#                          (2026-08-09新設)
#
# なぜ別の道具にするか:
#   hist_valuation.py は **その時点の倍率を測る**器で、リターンを一切知らない（知るべきでない
#   ——asof より後を見る経路をあの器に作ると look-ahead の穴が一つ増える）。
#   一方で後段の検定 agent が毎回 join を書くと、**同じ join が3つできて基準がずれる**
#   （v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」）。
#   → join は1本にして、在庫の行に畳み込んでおく。
#
# ── この道具が決めていること（＝後段が決め直さなくてよいこと）─────────────────
#  ■ 窓を揃える（事前登録 data.forward_return に明記された規則）
#    2026-08-09 に踏んだ **DBD 型**を必ず除く。DBD は Chapter11 で普通株が消え、
#    Yahoo の系列は **2023-08 の再上場以降しか無い**。その3.01年を「8.09年のコホート」に
#    混ぜると年率62.5%の勝者に見えるが、2018年に買った株主の実現は概ね −100%。
#    → `window_full` = そのビンテージの**最頻の窓**と一致するか。ずれた社は
#      **行は残して印だけ落とす**（黙って消さない・v9.9.52）。
#
#  ■ 質実証プールの印は**そのビンテージで既にある道具の定義をそのまま使う**
#    2013/2015: out/retro_cohort_{Y}.json の `opm>=0.10 ∧ fcf_all_pos ∧ op_all_pos`
#               （retro_build_readlist.py / retro_moat_durability.py と同じ式）
#    2018     : out/retro_features2_{Y}.json の `opm>=0.10 ∧ fcfpos5>=5`
#               （retro_price_tail.py / retro_er_test.py と同じ式。実測でこの式は
#                 CLAUDE.md 記載の **質実証プール274社** をそのまま再現する）
#    ⚠**2018には「営業利益全年黒字」の在庫が無い**。retro_features2 が持つのは
#      opm(アンカー年) / opmD5(両端の差) / streak_opm(改善した年数) で、**どれも
#      「全年黒字」ではない**。推測で印を付けない（絶対のルール7の同族）ので
#      `q_op_all_pos=null` として残し、欠けている条件を header に明記する。
#      参考の実測（同じ条件を持つ 2013/2015 で数えた差）:
#        2013: opm10∧fcf全年黒字 628社 → op_all_pos も課すと 563社（−10.4%）
#        2015: 664社 → 619社（−6.8%）
#      ＝2018のプールは他の2つより **7〜10%ぶん緩い**。基準3（2ビンテージ以上で同符号）を
#      読むときはこの差を承知で読むこと。
#
# ■ 単位を変換しない: tr_cagr は出所（retro_returns）のまま **小数**（0.1046＝年率10.46%）。
#   同じ量を2つの単位で持つと、いつか片方だけ使われる（この台帳が5回踏んだ型の入口）。
#
# 実行（冪等・何度でも上書きしてよい）:
#   python3 night/hist_val_join.py --asof 2018            # out/hist_val_2018.json を綴じ直す
#   python3 night/hist_val_join.py --asof 2018 --report   # 被覆率と hist_months 分布も出す
import argparse
import collections
import json
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hist_val_rev import load_vintage_checked, seen_revs   # 在庫の版の検問（単一実装）

# join が足す欄。**書く前に必ず消す**ので何度回しても同じ結果になる（冪等）
JOINED = ("tr_cagr", "tr_total", "years", "mdd", "ret_start", "ret_end", "ret_stale",
          "ret_group", "window_full", "quality", "q_opm", "q_fcfpos5", "q_op_all_pos",
          "q_src", "in_per_inv", "per_xs", "analysis_set", "join_note")

PCTS = ("pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_pct_ann", "adj_pe_pct_ann")


def load(name):
    p = os.path.join(OUT, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def returns_for(y):
    """そのビンテージの前方リターン在庫。複数あれば**突合せてから**まとめる。

    retro_build_readlist.py と同じ優先順（_all → _q → 素）。重なる社が
    **違う値**を持っていたら黙って片方を採らず conflict として数える
    ——別々の採取で作られた系列を混ぜるのは「基準の違う二つ」の入口だから。
    """
    src, rows, conflict = [], {}, []
    for nm in (f"retro_returns_{y}_all.json", f"retro_returns_{y}_q.json",
               f"retro_returns_{y}.json"):
        j = load(nm)
        if not j:
            continue
        src.append(nm)
        for r in j.get("rows") or []:
            t = r.get("ticker")
            if not t:
                continue
            if t in rows:
                a, b = rows[t].get("tr_cagr"), r.get("tr_cagr")
                if a is not None and b is not None and abs(a - b) > 0.002:
                    conflict.append({"ticker": t, "a": a, "b": b, "file": nm})
                continue
            r = dict(r)
            r["_src"] = nm
            rows[t] = r
    bench = None
    for nm in src:
        b = (load(nm) or {}).get("benchmark")
        if b:
            bench = dict(b, source=nm)
            break
    return rows, src, conflict, bench


# retro_cohort の窓は **会計年度ラベル** [Y-4, Y] で切られており、**filed<=asof では切られていない**。
# 実測（2026-08-09・2015の507社を facts の filed 日で数えた）: 暦2015年に期末が来る年次を持つ 485社の
# うち **428社(88.2%) は asof(2015-07-01) までに一度も提出されていない**
# （AAPL の FY2015 は 2015-10-28 提出＝asofの4ヶ月後。KO の FY2015 は 2016-02 提出）。
# ＝この印は **プールの membership に最大で約1年半の look-ahead** を含む。
# 分位そのもの（hist_valuation.py 側）は filed<=asof で厳密に切られているので**汚染されていない**——
# 汚れるのは「どの社をプールに入れるか」だけ。それでも 2018（retro_features2＝filed厳密）と
# 束ねるときは**ビンテージ間で印の作り方が違う**ことを承知で読むこと。
LOOKAHEAD_COHORT = ("会計年度ラベルで切った窓＝filed<=asof ではない。実測(2015): FY2015を持つ485社中"
                    "428社(88.2%)は asof までに未提出＝プールの membership に最大約1年半の look-ahead。"
                    "分位・zは filed<=asof で厳密に切られているので汚染されていない")


def quality_for(y):
    """質実証プールの印。定義は**そのビンテージで既に使われている式**をそのまま。"""
    coh = load(f"retro_cohort_{y}.json")
    if coh:
        out = {}
        for r in coh.get("rows") or []:
            t = r.get("ticker")
            if not t or t in out:
                continue
            out[t] = {"q_opm": r.get("opm"),
                      "q_fcfpos5": bool(r.get("fcf_all_pos")),
                      "q_op_all_pos": bool(r.get("op_all_pos")),
                      "q_src": f"retro_cohort_{y}.json"}
        return out, f"retro_cohort_{y}.json", ("opm>=0.10 ∧ fcf_all_pos ∧ op_all_pos", True)
    fea = load(f"retro_features2_{y}.json")
    if fea:
        out = {}
        for r in fea.get("rows") or []:
            t = r.get("ticker")
            if not t or t in out:
                continue
            f5 = r.get("fcfpos5")
            out[t] = {"q_opm": r.get("opm"),
                      "q_fcfpos5": (None if f5 is None else f5 >= 5),
                      "q_op_all_pos": None,     # ← 在庫に無い。推測で埋めない
                      "q_src": f"retro_features2_{y}.json"}
        return out, f"retro_features2_{y}.json", ("opm>=0.10 ∧ fcfpos5>=5", False)
    return {}, None, (None, False)


def per_for(y):
    for nm in (f"retro_per_{y}_all.json", f"retro_per_{y}.json"):
        j = load(nm)
        if j:
            return {r["ticker"]: r.get("per") for r in (j.get("rows") or [])
                    if r.get("ticker")}, nm
    return {}, None


def caveats(rows, y):
    """**在庫を使う側が知らないと結論を誤る事実**を、数えたうえで在庫の中に置く。
    （別ファイルの覚書にすると読まれない。行と同じファイルに入れる）"""
    A = [r for r in rows if r.get("analysis_set")]
    out = []

    # (1) z と 分位 で自己履歴の下限が違う（採取器の仕様。値は直さず印だけ）
    n = sum(1 for r in A if r.get("pe_z") is not None and (r.get("pe_hist_months") or 0) < 36)
    m = sum(1 for r in A if r.get("ps_z") is not None and (r.get("ps_hist_months") or 0) < 36)
    if n or m:
        out.append(f"z と 分位で自己履歴の下限が違う: 分位は36ヶ月を要求するが z は8ヶ月で出る。"
                   f"**pe_z が {n}社・ps_z が {m}社、36ヶ月未満の履歴で付いている**。"
                   f"事前登録の z 格子(1.0/1.5/2.0)を当てるときは "
                   f"`{'{'}指標{'}'}_hist_months >= 36` を必ず併せて課すこと（行に入っている）")

    # (2) 倍率を測った月と、リターンが始まる月が1ヶ月ずれる
    pm = collections.Counter(r.get("px_month") for r in A).most_common(1)
    st = collections.Counter(r.get("ret_start") for r in A).most_common(1)
    if pm and st:
        out.append(f"倍率は {pm[0][0]} の月末終値・前方リターンは {st[0][0]} 始まり＝**1ヶ月ずれる**。"
                   f"asof より後を見ないための設計（look-ahead を作らない）だが、その1ヶ月に"
                   f"大きな分配があった社は前後で別の会社になる（実例 KDP: 2018-07 に"
                   f"1株$103.75の特別配当で株価122→24）")

    # (3) 赤字で PER が定義できない社（事前登録『分母の質』）
    neg = sum(1 for r in A if r.get("pe_pct") is None
              and "正でない" in ((r.get("nulls") or {}).get("pe") or ""))
    out.append(f"PERは純利益が正でないと定義できない: 分析対象のうち **{neg}社**がこれで脱落。"
               f"残った社の分位も『黒字だった月だけ』の分布に対する順位＝赤字期の多い社ほど"
               f"母数が薄い（pe_hist_months を見ること）")

    # (4) 2018年ビンテージ固有: 米国税制改革の一時費用が TTM 純利益に乗っている
    if y == 2018:
        out.append("**2018年ビンテージ固有の交絡**: 2017-12 の米国税制改革(TCJA)の一時費用は、"
                   "2018-06 時点の TTM 純利益（多くの12月決算社で2018-03期末）に丸ごと乗る。"
                   "実測 MSFT: TTM純利益 14.2十億$（FY2017は21.2十億$）→ PER 53.3・自己分位0.958。"
                   "KO も TTM純利益1.4十億$で PER 130。**pe_pct が高い社の一部は『高い株価』ではなく"
                   "『一時的に低い利益』を測っている**。ps_pct / pfcf_pct はこの費用を受けない")

    # (4b) 綴じ込む横断面PER(`per_xs`)は**1ヶ月先の株価**で作られている（2026-08-09に実測して判明）
    #   retro_per_asof.fetch_raw_close は Yahoo へ `period1 = asof年7月1日, interval=1mo` で問い合わせ、
    #   返ってきた**最初の月足の close** を「当時の板の値」として採る。Yahoo の月足は月初ラベル・
    #   close は月末値なので、これは **7月末の終値＝asof の1ヶ月後**になる。
    #   実測（px キャッシュと突合・分割倍率で復元してから比較）:
    #     2013 n=694 / 2015 n=136 / 2018 n=699 の**すべてで 7月末終値と 100%（1%以内）一致**、
    #     6月末とは中央値で 2013 +5.8% / 2015 +1.4% / 2018 +2.5% ずれる。
    #   → `per_xs` は横断面の参考値としては使えるが、**本器の pe/ps/pfcf と同じ月ではない**。
    #     両者を割ったり同じ図に重ねたりすると「基準の違う二つ」を作る。
    #     本器の px は asof 以前（6月末）で、事前登録の look-ahead 規則に従っている。
    out.append("綴じ込んだ `per_xs`（retro_per_{Y}）の株価は **asof の1ヶ月後（7月末終値）**＝1ヶ月の"
               "look-ahead を含む（3ビンテージとも7月末終値と100%一致・6月末とは中央値で1.4〜5.8%ずれる）。"
               "本器の pe/ps/pfcf は asof 以前の6月末。**同じ行に並ぶが同じ月ではない**ので割らないこと")

    # (5) 生存バイアス（事前登録の既知リスク・構造的に消せない）
    out.append("自己履歴は**長く生きた社にしか作れない**。母集団は『今日のティッカーで価格が引ける社』"
               "で既に絞られており、この検定は構造的に生存者寄り（事前登録 known_risks どおり）")
    return out


def main():
    ap = argparse.ArgumentParser(description="自己相対バリュエーション在庫に前方リターンを綴じる")
    ap.add_argument("--asof", default="2018", help="ビンテージの年（2013/2015/2018）")
    ap.add_argument("--file", help="在庫のパス（既定 out/hist_val_{年}.json）")
    ap.add_argument("--report", action="store_true", help="被覆率と hist_months 分布を出す")
    a = ap.parse_args()
    y = int(str(a.asof)[:4])
    path = a.file or os.path.join(OUT, f"hist_val_{y}.json")
    # 版の検問（night/hist_val_rev.py）。**版の無い在庫には綴じない**——
    # 綴じてしまうと「リターンが付いた在庫」の顔をして後段の検定へ流れる（2026-08-09に踏んだ事故の入口）
    hv = load_vintage_checked(y, path=path)
    rows = hv["rows"]

    rr, rsrc, rconf, bench = returns_for(y)
    qq, qsrc, (qdef, qfull) = quality_for(y)
    pp, psrc = per_for(y)

    # 窓の最頻値＝そのコホートの「揃った窓」
    yrs = [r["years"] for r in rr.values() if r.get("years") is not None]
    modal = collections.Counter(round(v, 2) for v in yrs).most_common(1)[0][0] if yrs else None

    short = []
    for r in rows:
        for k in JOINED:
            r.pop(k, None)
        t = r["ticker"]
        g = rr.get(t)
        if g:
            r["tr_cagr"] = g.get("tr_cagr")
            r["tr_total"] = g.get("tr_total")
            r["years"] = g.get("years")
            r["mdd"] = g.get("mdd")
            r["ret_start"] = g.get("start")
            r["ret_end"] = g.get("end")
            r["ret_stale"] = g.get("stale")
            r["ret_group"] = g.get("group")
            ok = (modal is not None and g.get("years") is not None
                  and abs(g["years"] - modal) <= 0.02)
            r["window_full"] = bool(ok)
            if not ok:
                short.append({"ticker": t, "years": g.get("years"), "start": g.get("start"),
                              "tr_cagr": g.get("tr_cagr")})
                r["join_note"] = (f"前方リターンの窓が {g.get('years')}年（コホートは {modal}年）"
                                  f"＝{g.get('start')}からしか系列が無い。DBD型（破綻・再上場で"
                                  f"普通株が入れ替わった）の疑い＝事前登録どおり分析対象から外す")
        else:
            r["window_full"] = None
            r["join_note"] = "前方リターンの在庫に無い"

        q = qq.get(t)
        if q:
            r.update(q)
            opm_ok = (q["q_opm"] is not None and q["q_opm"] >= 0.10)
            parts = [opm_ok, q["q_fcfpos5"]] + ([q["q_op_all_pos"]] if qfull else [])
            r["quality"] = None if any(p is None for p in parts) else bool(all(parts))
        else:
            r["quality"] = None
            r["q_src"] = None
        r["in_per_inv"] = t in pp
        r["per_xs"] = pp.get(t)
        r["analysis_set"] = bool(any(r.get(k) is not None for k in PCTS)
                                 and r.get("tr_cagr") is not None
                                 and r.get("window_full"))

    hv["join"] = {
        "tool": "night/hist_val_join.py",
        "joined": "2026-08-09",
        # どの版の在庫へ綴じたか。後から「この数字はどの採取器で出たか」を辿れるようにする
        "src_tool_rev": hv.get("tool_rev"),
        "returns_src": rsrc,
        "returns_conflicts": rconf,
        "benchmark": bench,
        "modal_years": modal,
        "window_short_excluded": short,
        "quality_src": qsrc,
        "quality_def": qdef,
        "quality_full_3conditions": qfull,
        "quality_lookahead": (LOOKAHEAD_COHORT if (qsrc or "").startswith("retro_cohort") else None),
        "quality_missing_condition": (None if qfull else
                                      "営業利益全年黒字（op_all_pos）は2018年の在庫に無い"
                                      "＝q_op_all_pos は null。2013/2015 で同条件を課すと"
                                      "プールは 10.4% / 6.8% 縮む＝2018のプールはその分だけ緩い"),
        "per_inv_src": psrc,
        "units": {"tr_cagr": "小数（0.1046 = 年率10.46%）", "mdd": "小数（-0.402 = -40.2%）",
                  "*_pct": "0-1 の自己履歴分位（1.0 = 自己史上いちばん高い）"},
        "analysis_set_def": "自己相対分位が1つ以上ある ∧ 前方リターンがある ∧ window_full",
        "caveats": caveats(rows, y),
        "counts": {
            "rows": len(rows),
            "with_return": sum(1 for r in rows if r.get("tr_cagr") is not None),
            "window_full": sum(1 for r in rows if r.get("window_full")),
            "analysis_set": sum(1 for r in rows if r.get("analysis_set")),
            "quality_true": sum(1 for r in rows if r.get("quality")),
            "quality_true_in_set": sum(1 for r in rows if r.get("quality") and r["analysis_set"]),
            "in_per_inv": sum(1 for r in rows if r.get("in_per_inv")),
        },
    }
    tmp = path + ".tmp"
    json.dump(hv, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    c = hv["join"]["counts"]
    print(f"■ {path}")
    print(f"  {c['rows']}社 / リターンあり {c['with_return']} / 窓が揃う {c['window_full']} "
          f"/ **分析対象 {c['analysis_set']}** / 質実証 {c['quality_true_in_set']}"
          f" / PER在庫にも居る {c['in_per_inv']}")
    if short:
        print(f"  窓が揃わず外した {len(short)}社: "
              + ", ".join(f"{s['ticker']}({s['years']}年)" for s in short))
    if rconf:
        print(f"  ⚠ リターン在庫どうしの食い違い {len(rconf)}件")
    if a.report:
        report(rows)
    return 0


def report(rows):
    A = [r for r in rows if r.get("analysis_set")]
    Q = [r for r in A if r.get("quality")]
    print("\n【被覆率】分析対象 %d社（うち質実証 %d社）" % (len(A), len(Q)))
    print(f"  {'指標':<14}{'分析対象':>12}{'質実証':>12}")
    for k in PCTS:
        a = sum(1 for r in A if r.get(k) is not None)
        q = sum(1 for r in Q if r.get(k) is not None)
        print(f"  {k:<14}{a:>6} ({100*a/max(len(A),1):>4.1f}%){q:>6} ({100*q/max(len(Q),1):>4.1f}%)")
    a = sum(1 for r in A if r.get("spx_pe_pct") is not None)
    print(f"  {'spx_pe_pct':<14}{a:>6} ({100*a/max(len(A),1):>4.1f}%)  ＝市場の水準（社に依らない）")
    # 分位が出せなかった理由は **2箇所**に散る——値そのものが作れない(nulls['pe'])と、
    # 値はあるが自己履歴が下限36ヶ月に足りない(nulls['pe_pct'])。片方だけ数えると
    # 「理由不明」が山になる（初版がそうなった）
    for m, why in (("pe", "PER"), ("ps", "P/S"), ("pfcf", "P/FCF")):
        neg = [r for r in A if r.get(f"{m}_pct") is None]
        if not neg:
            continue
        c = collections.Counter()
        for r in neg:
            n = r.get("nulls") or {}
            s = n.get(f"{m}_pct") or n.get(m) or "理由の記録なし"
            # 理由に**実額**が入る欄（『ni が正でない（-255,856,000）』）は社ごとに
            # 文字列が違うので、そのまま数えると全部が「1社」になって山が見えない
            if "自己履歴" in s:
                s = "自己履歴が36ヶ月に満たない"
            elif "正でない" in s:
                s = f"{s.split(' ')[0]} が正でない（赤字）＝倍率が定義できない"
            c[s[:44]] += 1
        print(f"  {why}の分位が出ない {len(neg)}社: "
              + " / ".join(f"{k}…{v}社" for k, v in c.most_common(4)))
    print("\n【hist_months の分布】自己履歴が短いほど分位は信用できない")
    for k in ("hist_months", "pe_hist_months", "ps_hist_months", "pfcf_hist_months"):
        # 各指標は **その指標の分位が出た社だけ**で数える（出ていない社の0を混ぜない）
        pk = k.split("_")[0] + "_pct"
        v = sorted(r[k] for r in A if r.get(k) is not None
                   and (k == "hist_months" or r.get(pk) is not None))
        if not v:
            continue
        qs = statistics.quantiles(v, n=10)
        print(f"  {k:<18} n={len(v):<4} min {v[0]:>3} / p10 {qs[0]:>5.0f} / 中央 "
              f"{statistics.median(v):>5.0f} / p90 {qs[-1]:>5.0f} / max {v[-1]:>3}")
    b = collections.Counter()
    for r in A:
        m = r.get("pe_hist_months")
        if m is None or r.get("pe_pct") is None:
            continue
        b["<48ヶ月(4年未満)" if m < 48 else ("48-71" if m < 72 else ("72-95" if m < 96 else "96ヶ月以上"))] += 1
    print("  pe の自己履歴: " + " / ".join(f"{k} {v}社" for k, v in sorted(b.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
