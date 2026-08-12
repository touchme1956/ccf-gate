#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist_wd_asym.py — 勝者(目的A)と破壊(目的B)を**同じ表に並べる**。

事前登録: out/hist_winner_destroyer_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_win_uni.json（W1・勝者側）/ out/hist_wd_dst_uni.json（D1・破壊側）
出力    : out/hist_wd_asym.json

この道具が答える問い（prereg の novelty #3）:
  **勝者と破壊で、別の変数が効いていないか。**
  ＝「上を狙う」と「下を防ぐ」で採るべき変数が違うのか。

────────────────────────────────────────────────────────────
0) 再実装をしない（v9.9.65）
────────────────────────────────────────────────────────────
lift はこの道具では**一つも計算しない**。W1/D1 が出した値をそのまま読む。
ただし「同じ台帳を見る二つの検査器が違うことを言ってはいけない」ので、
読む前に **両者の構造（n_pop / n_measurable / n_missing / distinct / 四分位点 / 各群の n_group）が
一致するか**を全セルで突き合わせ、1件でも食い違えばそれ自体を欠陥として出す
（両者は同じ解析集合・同じ切り方を使うので、一致は恒等的に成り立たねばならない。
  一致しないなら、どちらかの群の作り方が壊れている）。

────────────────────────────────────────────────────────────
1) 象限の名前を、親の指示の言葉のまま使わない（ここが本題の入口）
────────────────────────────────────────────────────────────
横軸 lift_win = P(勝者|群) − P(勝者|母集団)、縦軸 lift_destroy = P(破壊|群) − P(破壊|母集団)。
依頼文は「右上(両方効く)」と書いているが、**右上は「両方効く」ではない**——
右上 = 勝者も多いが破壊も多い = **極端を作る（ボラティリティ型）**。
依頼文の項目3が言う『勝者にも破壊にも正＝極端を作る変数』と、項目1の『右上(両方効く)』は
同じ象限を指していて、**呼び名だけが食い違っている**。
望ましい意味で「両方効く」のは **右下**（勝者が増え、破壊が減る）。
  右下 純粋な追い風 / 左上 純粋な向かい風 / 右上 極端を作る / 左下 凪（安全だが伸びない）
**この取り違えは実害を生む**——右上を「両方効く」と読むと、ボラティリティを選別力と誤認する。
この台帳が『質の指標と結果が逆を向く』を4回記録してきたのと同じ型なので、名前で先に潰しておく。

────────────────────────────────────────────────────────────
2) 散布の座標に何を使うか
────────────────────────────────────────────────────────────
prereg の必須ゲートは 2016/2017/2018 の符号不変。よって座標は**この3ビンテージの中央値**。
同時に **min|lift| と符号安定** も併記する（既存の W1/D1・D1 の win_vs_destroy_asymmetry と同じ
保守的な尺度。ここを変えると「基準の違う二つ」を自分で作る）。
⚠ **3ビンテージは独立ではない**（同じ956ティッカー・窓が重なる）。
   中央値は「3つの独立な証拠の代表値」ではなく「ほぼ同じ標本を3回見た値の代表」。

────────────────────────────────────────────────────────────
3) 象限の頭数は、閾値ひとつで決めない
────────────────────────────────────────────────────────────
どこかに線を引けば必ず何かが選ばれる。そこで象限の頭数は
**大きさの床を 0.00 / 0.02 / 0.05 / 0.10 と動かした4通りを全部出す**。
結論が床の選び方で変わるなら、それは結論ではない。
なお 0.10 は依頼文が指定した**探索用の床で、prereg の線(0.15)ではない**＝
ここから出るものは全て **事前登録の外**。合否は W1/D1 の verdict が持つ。

────────────────────────────────────────────────────────────
4) 同じ変数の 上位1/4 と 下位1/4 は「2件の発見」ではない
────────────────────────────────────────────────────────────
4つの切り方のうち 中央値超/中央値以下 は完全な補集合、上位1/4/下位1/4 は互いに鏡。
＝1変数につき実質「高い側」「低い側」の2つの見方しかない。
象限の頭数は**四分位の切り方だけ**で数え（鋭いほうの道具）、
変数レベルの要約では「破壊|lift| が最大になる向き」を1本選んで、
**その同じ群で勝者側がどうなっているか**を並べる（＝破壊の予言子は勝者も拾うのか、を直接見る）。
`f2_rev` と `size_rev` は D1 が実測で**同一列**と確定しているので、変数レベルでは1本に畳む。

────────────────────────────────────────────────────────────
5) 破壊側は稀事象——「守る側」は構造的に分子が足りない
────────────────────────────────────────────────────────────
破壊の基準率は 2016-2018 で 5.8〜8.1%、2015 は **9件(1.8%)**。
lift_destroy が**負**（＝破壊を減らす＝守る）のセルは、定義上その群の事象が少ないので
prereg の min_numerator>=5 に**構造的に届きにくい**（D1 が既に記録している）。
よって「下を防ぐ変数が見つからない」を「守る変数が無い」と読んではいけない。
各行に両側の分子を必ず出し、守る向きのセルには到達可能性の印を付ける。
"""
import json, os, sys, math
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")

WIN_SRC = os.path.join(OUT, "hist_wd_win_uni.json")
DST_SRC = os.path.join(OUT, "hist_wd_dst_uni.json")
PREREG = os.path.join(OUT, "hist_winner_destroyer_prereg.json")
DEST = os.path.join(OUT, "hist_wd_asym.json")

GATE_VINTAGES = [2016, 2017, 2018]          # prereg の必須ゲート
ALL_VINTAGES = [2013, 2015, 2016, 2017, 2018]
POPS = ["P_full", "P_quality", "P_moat"]
QUARTILE_CUTS = ["上位1/4", "下位1/4"]
MEDIAN_CUTS = ["中央値超", "中央値以下"]
ALL_CUTS = QUARTILE_CUTS + MEDIAN_CUTS

FLOORS = [0.00, 0.02, 0.05, 0.10]           # 象限の頭数を数える大きさの床（結論を1本の線に載せない）
EXPLORE_FLOOR = 0.10                        # 依頼文の探索用の床。**prereg の 0.15 ではない**
PREREG_LIFT = 0.15
MIN_NUM = 5
COVERAGE_DIVERGE = 0.02                     # lift_vs_pop と lift_vs_measurable の食い違いに印を付ける幅

DUP_ALIAS = {"size_rev": "f2_rev"}          # D1 が実測で同一列と確定（2016-2018）


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def quadrant(lw, ld):
    """象限。**符号だけで決める**（大きさの床は呼び出し側で動かす）。"""
    if lw is None or ld is None:
        return None
    if lw >= 0 and ld < 0:
        return "右下 純粋な追い風（勝者↑ 破壊↓）"
    if lw < 0 and ld >= 0:
        return "左上 純粋な向かい風（勝者↓ 破壊↑）"
    if lw >= 0 and ld >= 0:
        return "右上 極端を作る（勝者↑ 破壊↑・ボラティリティ型）"
    return "左下 凪（勝者↓ 破壊↓・安全だが伸びない）"


def sign_stable(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    return all(x > 0 for x in xs) or all(x < 0 for x in xs)


def main():
    win = jload(WIN_SRC)
    dst = jload(DST_SRC)

    # ── 0) 二つの検査器が同じことを言っているか（読む前に確かめる） ──
    kw, kd = set(win["cells"]), set(dst["cells"])
    mism = []
    for k in sorted(kw & kd):
        a, b = win["cells"][k], dst["cells"][k]
        for f in ("n_pop", "n_measurable", "n_missing", "distinct", "q25", "q50", "q75"):
            if a.get(f) != b.get(f):
                mism.append({"cell": k, "field": f, "win": a.get(f), "dst": b.get(f)})
        for c, av in (a.get("cuts") or {}).items():
            bv = (b.get("cuts") or {}).get(c)
            if bv is not None and av.get("n_group") != bv.get("n_group"):
                mism.append({"cell": k, "field": c + ".n_group",
                             "win": av.get("n_group"), "dst": bv.get("n_group")})
    verification = {
        "why": ("W1 と D1 は同じ解析集合・同じ切り方を使うので、群の作り方が一致するのは恒等的。"
                "一致しないなら、どちらかが壊れている。**lift を再計算せずに読む前提**がこれ。"),
        "cells_win": len(kw), "cells_dst": len(kd),
        "cells_only_in_one": sorted(kw ^ kd),
        "structural_mismatches": len(mism),
        "mismatch_examples": mism[:10],
        "verdict": ("✓ 全セルで一致＝そのまま読んでよい" if not mism
                    else "⚠ 食い違いあり＝先にどちらかを直すこと"),
    }
    if mism:
        # 食い違ったまま並べると、その表自体が「基準の違う二つ」になる。
        print("⚠ W1/D1 の構造が食い違っています。並べる前に直してください。", file=sys.stderr)

    # ── 1) セル行を組む ──
    rows = []
    for var_pop in sorted({k.rsplit("|", 1)[0] for k in kw & kd}):
        var, pop = var_pop.split("|")
        for cut in ALL_CUTS:
            per_v = {}
            for v in ALL_VINTAGES:
                ck = f"{var_pop}|{v}"
                wc, dc = win["cells"].get(ck), dst["cells"].get(ck)
                if not wc or not dc:
                    continue
                wcut = (wc.get("cuts") or {}).get(cut)
                dcut = (dc.get("cuts") or {}).get(cut)
                if not wcut or not dcut:
                    continue
                per_v[v] = {
                    "n_group": wcut["n_group"],
                    "win_num": wcut["numerator"], "win_p": wcut["p_group"],
                    "win_lift": wcut["lift_vs_pop"], "win_lift_meas": wcut.get("lift_vs_measurable"),
                    "win_p_pop": wc["p_pop"],
                    "dst_num": dcut["numerator"], "dst_p": dcut["p_group"],
                    "dst_lift": dcut["lift_vs_pop"], "dst_lift_meas": dcut.get("lift_vs_measurable"),
                    "dst_rr": dcut.get("rr_vs_pop"), "dst_p_pop": dc["p_pop"],
                    "dst_attainable_positive": dcut.get("attainable_positive"),
                    "dst_attainable_protective": dcut.get("attainable_protective"),
                    "win_quintile_spearman": wc.get("quintile_spearman"),
                    "dst_quintile_spearman": dc.get("quintile_spearman"),
                }
            if not per_v:
                continue
            gate_v = [v for v in GATE_VINTAGES if v in per_v]
            wl = [per_v[v]["win_lift"] for v in gate_v]
            dl = [per_v[v]["dst_lift"] for v in gate_v]
            # 低カーディナリティの変数は中央値切りで群が空になる（例: f2_fcfpos5 の中央値=5 →
            # 「中央値超」が0行）。lift は None になる。**空の群は「判定不能」であって
            # 「効果ゼロ」ではない**ので、0 で埋めずにここで落とす。
            empty_groups = [v for v in gate_v if per_v[v]["win_lift"] is None
                            or per_v[v]["dst_lift"] is None]
            gate_ok = (len(gate_v) == len(GATE_VINTAGES) and not empty_groups)
            if empty_groups:
                wl = [x for x in wl if x is not None]
                dl = [x for x in dl if x is not None]

            # 被覆の食い違い（変数が分けたのか、報告している社が違うのか）
            div = []
            for v in gate_v:
                for side, a, b in (("win", per_v[v]["win_lift"], per_v[v]["win_lift_meas"]),
                                   ("dst", per_v[v]["dst_lift"], per_v[v]["dst_lift_meas"])):
                    if b is not None and abs(a - b) > COVERAGE_DIVERGE:
                        div.append(f"{v}/{side} {a:+.4f}→{b:+.4f}")

            lw = median(wl) if gate_ok else None
            ld = median(dl) if gate_ok else None
            row = {
                "variable": var, "population": pop, "cut": cut,
                "side": "高い側" if cut in ("上位1/4", "中央値超") else "低い側",
                "granularity": "四分位" if cut in QUARTILE_CUTS else "中央値",
                "gate_evaluable": gate_ok,
                "gate_unevaluable_reason": (
                    None if gate_ok else
                    ("群が空（低カーディナリティで切り方が潰れた）＝効果ゼロではなく判定不能: "
                     + ",".join(str(v) for v in empty_groups)) if empty_groups else
                    "2016/2017/2018 のどれかにこの変数が無い＝結果を見る前から構造的に判定不能"),
                "gate_vintages_present": gate_v,
                "vintages_present": sorted(per_v),
                "lift_win_med": round(lw, 4) if lw is not None else None,
                "lift_destroy_med": round(ld, 4) if ld is not None else None,
                "lift_win_by_vintage": {str(v): per_v[v]["win_lift"] for v in sorted(per_v)},
                "lift_destroy_by_vintage": {str(v): per_v[v]["dst_lift"] for v in sorted(per_v)},
                "win_sign_stable": sign_stable(wl) if gate_ok else None,
                "destroy_sign_stable": sign_stable(dl) if gate_ok else None,
                "win_min_abs_lift": round(min(abs(x) for x in wl), 4) if gate_ok else None,
                "destroy_min_abs_lift": round(min(abs(x) for x in dl), 4) if gate_ok else None,
                "n_group_by_vintage": {str(v): per_v[v]["n_group"] for v in sorted(per_v)},
                "win_numerator_by_vintage": {str(v): per_v[v]["win_num"] for v in sorted(per_v)},
                "destroy_numerator_by_vintage": {str(v): per_v[v]["dst_num"] for v in sorted(per_v)},
                "destroy_rr_by_vintage": {str(v): per_v[v]["dst_rr"] for v in sorted(per_v)},
                "win_quintile_spearman": {str(v): per_v[v]["win_quintile_spearman"] for v in sorted(per_v)},
                "destroy_quintile_spearman": {str(v): per_v[v]["dst_quintile_spearman"] for v in sorted(per_v)},
                "quadrant": quadrant(lw, ld) if gate_ok else None,
                "coverage_divergence": div or None,
                "destroy_min_numerator_met": (all(per_v[v]["dst_num"] >= MIN_NUM for v in gate_v)
                                              if gate_ok else None),
                "win_min_numerator_met": (all(per_v[v]["win_num"] >= MIN_NUM for v in gate_v)
                                          if gate_ok else None),
            }
            # 守る向き（破壊を減らす）は分子が構造的に足りない側
            if gate_ok and ld is not None and ld < 0 and not row["destroy_min_numerator_met"]:
                row["note_protective"] = ("守る向き（破壊↓）だが分子<5＝prereg の min_numerator に"
                                          "構造的に届かない。『効果が無い』ではなく『この標本では確かめられない』")
            rows.append(row)

    # ── 2) 象限の頭数（床を動かして4通り。四分位の切り方だけで数える） ──
    quad_counts = {}
    q_rows = [r for r in rows if r["gate_evaluable"] and r["granularity"] == "四分位"]
    for fl in FLOORS:
        c = Counter()
        for r in q_rows:
            lw, ld = r["lift_win_med"], r["lift_destroy_med"]
            if max(abs(lw), abs(ld)) < fl:
                c["帯の中（どちらも床未満）"] += 1
            else:
                c[r["quadrant"]] += 1
        quad_counts[f"floor_{fl:.2f}"] = dict(c)

    # ── 3) 片側だけ効く（探索用の床 0.10・事前登録の外） ──
    one_sided_destroy, one_sided_win, both_sides = [], [], []
    for r in q_rows:
        lw, ld = abs(r["lift_win_med"]), abs(r["lift_destroy_med"])
        item = {k: r[k] for k in ("variable", "population", "cut", "lift_win_med", "lift_destroy_med",
                                  "win_sign_stable", "destroy_sign_stable", "quadrant",
                                  "destroy_numerator_by_vintage", "win_numerator_by_vintage",
                                  "destroy_rr_by_vintage", "n_group_by_vintage")}
        item["ratio_destroy_over_win"] = round(ld / lw, 2) if lw > 1e-9 else None
        if ld >= EXPLORE_FLOOR and lw < EXPLORE_FLOOR:
            one_sided_destroy.append(item)
        elif lw >= EXPLORE_FLOOR and ld < EXPLORE_FLOOR:
            one_sided_win.append(item)
        elif lw >= EXPLORE_FLOOR and ld >= EXPLORE_FLOOR:
            both_sides.append(item)
    one_sided_destroy.sort(key=lambda x: -abs(x["lift_destroy_med"]))
    one_sided_win.sort(key=lambda x: -abs(x["lift_win_med"]))

    # ── 4) 極端を作る変数（勝者にも破壊にも正） ──
    extremes = [r for r in q_rows if r["quadrant"] and r["quadrant"].startswith("右上")]
    extremes.sort(key=lambda r: -(r["lift_win_med"] + r["lift_destroy_med"]))
    extremes_top = [{k: r[k] for k in ("variable", "population", "cut", "lift_win_med",
                                       "lift_destroy_med", "win_sign_stable", "destroy_sign_stable",
                                       "win_numerator_by_vintage", "destroy_numerator_by_vintage")}
                    for r in extremes[:25]]
    # 反対側（左下 凪）も対で出す——同じ変数の裏返しが凪なら「極端 vs 凪」の軸が実在する
    calm = [r for r in q_rows if r["quadrant"] and r["quadrant"].startswith("左下")]
    calm.sort(key=lambda r: (r["lift_win_med"] + r["lift_destroy_med"]))
    calm_top = [{k: r[k] for k in ("variable", "population", "cut", "lift_win_med",
                                   "lift_destroy_med", "win_sign_stable", "destroy_sign_stable")}
                for r in calm[:25]]

    # ── 5) 五分位の単調性の非対称（1本の切り方より強い証拠） ──
    # ⚠ ただし**事象の数を必ず添える**。破壊は稀事象なので、P_quality では
    #    五分位のビンが 0,1,1,0,2 件といった数になり、spearman は1社の移動で大きく動く
    #    ＝『単調』に見えても雑音。読める数の目安は prereg の min_numerator=5 を
    #    五分位のビンに当てた **総事象25件**（1ビンあたり平均5件）。新しい定数を作らない。
    MONO_MIN_EVENTS = MIN_NUM * 5
    MONO_RHO = 0.6                     # 「単調に近い」の目安（探索用・事前登録の外）
    mono = []
    for r in q_rows:
        if r["cut"] != "下位1/4":       # 変数につき1行（切り方に依らない量なので重複を避ける）
            continue
        ws = [r["win_quintile_spearman"][str(v)] for v in GATE_VINTAGES
              if r["win_quintile_spearman"].get(str(v)) is not None]
        ds = [r["destroy_quintile_spearman"][str(v)] for v in GATE_VINTAGES
              if r["destroy_quintile_spearman"].get(str(v)) is not None]
        if len(ws) < 3 or len(ds) < 3:
            continue
        dev, wev, dq = {}, {}, {}
        for v in GATE_VINTAGES:
            ck = f"{r['variable']}|{r['population']}|{v}"
            dc, wc = dst["cells"].get(ck), win["cells"].get(ck)
            if dc:
                dev[str(v)] = dc.get("k_pop")
                dq[str(v)] = [q["k"] for q in (dc.get("quintiles") or [])]
            if wc:
                wev[str(v)] = wc.get("k_pop")
        d_ok = all((dev.get(str(v)) or 0) >= MONO_MIN_EVENTS for v in GATE_VINTAGES)
        w_ok = all((wev.get(str(v)) or 0) >= MONO_MIN_EVENTS for v in GATE_VINTAGES)
        mono.append({
            "variable": r["variable"], "population": r["population"],
            "win_spearman": ws, "destroy_spearman": ds,
            "win_med": round(median(ws), 3), "destroy_med": round(median(ds), 3),
            "win_sign_stable": sign_stable(ws), "destroy_sign_stable": sign_stable(ds),
            "gap": round(abs(median(ds)) - abs(median(ws)), 3),
            "destroy_events_by_vintage": dev, "win_events_by_vintage": wev,
            "destroy_quintile_counts": dq,
            "destroy_spearman_supported": d_ok, "win_spearman_supported": w_ok,
            "support_note": (None if d_ok else
                             f"破壊の総事象が {MONO_MIN_EVENTS} 件に届かないビンテージがある＝"
                             "五分位の順位相関は1社の移動で動く。**単調に見えても雑音**"),
        })
    mono.sort(key=lambda x: -x["gap"])
    # 支持のあるものだけを「発見」として出す（支持の無いものは別枠で全部出す・隠さない）
    mono_destroy_only = [m for m in mono
                         if m["destroy_spearman_supported"]
                         and abs(m["destroy_med"]) >= MONO_RHO and abs(m["win_med"]) < MONO_RHO
                         and m["destroy_sign_stable"]]
    mono_win_only = [m for m in mono
                     if m["win_spearman_supported"]
                     and abs(m["win_med"]) >= MONO_RHO and abs(m["destroy_med"]) < MONO_RHO
                     and m["win_sign_stable"]]
    mono_both = [m for m in mono
                 if m["destroy_spearman_supported"]
                 and abs(m["destroy_med"]) >= MONO_RHO and abs(m["win_med"]) >= MONO_RHO
                 and m["destroy_sign_stable"] and m["win_sign_stable"]]
    mono_unsupported = [m for m in mono if not m["destroy_spearman_supported"]
                        and abs(m["destroy_med"]) >= MONO_RHO]

    # ── 5b) 物差しの非対称（この道具の核心・Q4への直接の答え） ──
    # lift = P(群) − P(母集団) は絶対差。到達しうる上限は基準率で決まる:
    #   増やす向き: 1 − p   /   減らす向き: p（群の事象が0でも、そこまでしか下がれない）
    # 勝者の基準率は 21-24%、破壊は 5.8-8.1%。**同じ 0.15 の線が、二つの目的で別の意味を持つ。**
    instrument = {"why": ("prereg は勝者・破壊の両方に同じ線（|lift|>=0.15）を当てている。"
                          "だが lift は絶対差なので、**到達しうる上限が基準率で決まる**——"
                          "増やす向きは 1−p、減らす向きは p。基準率が線より低い目的では"
                          "『減らす向き』が数学的に不可能になる。"
                          "『合格ゼロ』を読む前に、そもそも合格しうるかを目的ごとに数える。"),
                  "by_vintage": {}}
    for v in GATE_VINTAGES:
        a = win["analysis_set_size"][str(v)]
        b = dst["analysis_set_size"][str(v)]
        pw, pd = a["wins"] / a["n"], b["destroys"] / b["n"]
        instrument["by_vintage"][str(v)] = {
            "n": a["n"],
            "win": {
                "events": a["wins"], "base_rate": round(pw, 4),
                "max_lift_increase": round(1 - pw, 4), "max_lift_decrease": round(pw, 4),
                "increase_reachable": (1 - pw) >= PREREG_LIFT,
                "decrease_reachable": pw >= PREREG_LIFT,
                "group_p_needed_to_pass_increase": round(pw + PREREG_LIFT, 4),
            },
            "destroy": {
                "events": b["destroys"], "base_rate": round(pd, 4),
                "max_lift_increase": round(1 - pd, 4), "max_lift_decrease": round(pd, 4),
                "increase_reachable": (1 - pd) >= PREREG_LIFT,
                "decrease_reachable": pd >= PREREG_LIFT,
                "group_p_needed_to_pass_increase": round(pd + PREREG_LIFT, 4),
                "multiple_of_base_needed": round((pd + PREREG_LIFT) / pd, 2),
            },
        }
    instrument["headline"] = (
        "勝者側は**増やす向きも減らす向きも到達可能**（基準率 21-24% > 0.15）。"
        "破壊側は**減らす向きが全ビンテージで数学的に不可能**（基準率 5.8-8.1% < 0.15＝"
        "群の破壊がゼロでも |lift| は基準率までしか下がらない）。"
        "増やす向きも、群の破壊率が基準率の 2.9-3.6倍 に達して初めて線に届く。"
        "＝**同じ 0.15 の線が、『上を狙う』には普通の関門・『下を防ぐ』には通れない関門になっている。**"
        "したがって『破壊側の合格ゼロ』は『下を防ぐ変数が無い』ことの証拠にならない。"
        "稀事象の物差しは比(RR)であって絶対差ではない——D1 の outside_prereg_relative_risk を見よ。")
    instrument["consequence_for_Q4"] = (
        "『上を狙う』と『下を防ぐ』で採るべき変数が違うか、という問いに対し、"
        "**この事前登録の線では対称に答えられない**。片側だけ通れない物差しで両側を測ると、"
        "『下を防ぐ変数は見つからなかった』という結論が、変数の性質ではなく線の引き方から出てしまう。")

    # ── 6) 変数レベル: 破壊|lift|が最大の向きで、勝者側はどうか ──
    var_level = []
    seen = set()
    for pop in POPS:
        by_var = defaultdict(list)
        for r in q_rows:
            if r["population"] != pop:
                continue
            by_var[DUP_ALIAS.get(r["variable"], r["variable"])].append(r)
        for v, rs in by_var.items():
            if (v, pop) in seen:
                continue
            seen.add((v, pop))
            bd = max(rs, key=lambda r: abs(r["lift_destroy_med"]))
            bw = max(rs, key=lambda r: abs(r["lift_win_med"]))
            var_level.append({
                "variable": v, "population": pop,
                "best_destroy_cut": bd["cut"],
                "destroy_lift_there": bd["lift_destroy_med"],
                "win_lift_in_same_group": bd["lift_win_med"],
                "destroy_sign_stable": bd["destroy_sign_stable"],
                "win_sign_stable_there": bd["win_sign_stable"],
                "quadrant_at_best_destroy": bd["quadrant"],
                "best_win_cut": bw["cut"],
                "win_lift_there": bw["lift_win_med"],
                "destroy_lift_in_same_group": bw["lift_destroy_med"],
                "same_direction_serves_both": (bd["cut"] == bw["cut"]
                                               and bd["lift_win_med"] > 0 > bd["lift_destroy_med"]),
            })
    var_level.sort(key=lambda x: -abs(x["destroy_lift_there"]))

    # ── 6b) 対照: irr そのものを同じ表に載せる ──
    # prereg は irr を**候補から除外**しているが「対照としては使う」と明記している。
    # W1/D1 は候補しか見ないので、**irr 自身の勝者率・破壊率は誰も測っていない**。
    # ここで測る意味: この台帳は既に『上を狙うなら85／下を防ぐなら70』と書いている。
    # それが本当に「目的ごとに別の変数（別の刻み）」の実例なら、irr は
    # **85=右上(極端を作る) / 70=右下(追い風)** に分かれて見えるはず。
    panel = jload(os.path.join(OUT, "hist_wd_panel.json"))
    # まず解析集合が W1/D1 と同一であることを検算する（違えば比べてはいけない）
    aset = defaultdict(list)
    for r in panel["rows"]:
        if r.get("has_outcome") and r.get("window_full"):
            aset[r["vintage"]].append(r)
    aset_check = []
    for v in ALL_VINTAGES:
        rs = aset.get(v, [])
        got = {"n": len(rs), "wins": sum(1 for x in rs if x.get("win")),
               "destroys": sum(1 for x in rs if x.get("destroy"))}
        exp = dict(dst["analysis_set_size"][str(v)])
        aset_check.append({"vintage": v, "recomputed": got, "D1": exp,
                           "match": got["n"] == exp["n"] and got["wins"] == exp["wins"]
                                    and got["destroys"] == exp["destroys"]})
    irr_rows = []
    for v in ALL_VINTAGES:
        rs = [x for x in aset.get(v, []) if x.get("irr") is not None]
        if not rs:
            continue
        base_w = sum(1 for x in rs if x["win"]) / len(rs)
        base_d = sum(1 for x in rs if x["destroy"]) / len(rs)
        by = defaultdict(list)
        for x in rs:
            by[x["irr"]].append(x)
        for lv in sorted(by):
            g = by[lv]
            kw_, kd_ = sum(1 for x in g if x["win"]), sum(1 for x in g if x["destroy"])
            pw_, pd_ = kw_ / len(g), kd_ / len(g)
            irr_rows.append({
                "vintage": v, "irr": lv, "n": len(g),
                "win_k": kw_, "win_p": round(pw_, 4), "win_lift": round(pw_ - base_w, 4),
                "destroy_k": kd_, "destroy_p": round(pd_, 4),
                "destroy_lift": round(pd_ - base_d, 4),
                "destroy_rr": round(pd_ / base_d, 3) if base_d > 0 else None,
                "base_win": round(base_w, 4), "base_destroy": round(base_d, 4),
                "quadrant": quadrant(pw_ - base_w, pd_ - base_d),
                "n_readable": len(rs),
            })
    # 長窓の2ビンテージ（2013:13.09年 / 2015:11.10年・刻みが 50/70/85/100 で揃う）を束ねる。
    # 2018 は刻みが 75 で違ううえ窓が 8.09年なので**混ぜない**。
    pooled = {}
    for lv in (50, 70, 85, 100):
        n = k_w = k_d = 0
        exp_d = 0.0
        for v in (2013, 2015):
            rs = [x for x in aset.get(v, []) if x.get("irr") == lv]
            if not rs:
                continue
            allr = [x for x in aset.get(v, []) if x.get("irr") is not None]
            bd = sum(1 for x in allr if x["destroy"]) / len(allr)
            n += len(rs)
            k_w += sum(1 for x in rs if x["win"])
            k_d += sum(1 for x in rs if x["destroy"])
            exp_d += len(rs) * bd            # そのビンテージの基準率での期待件数
        if n:
            # 破壊0件がどれだけ珍しいか（ポアソン近似）。**独立でない標本なので目安**
            p0 = math.exp(-exp_d) if k_d == 0 else None
            pooled[str(lv)] = {
                "n": n, "win_k": k_w, "win_p": round(k_w / n, 4),
                "destroy_k": k_d, "destroy_p": round(k_d / n, 4),
                "destroy_expected_at_base": round(exp_d, 2),
                "p_zero_destroy_poisson": round(p0, 4) if p0 is not None else None,
            }
    irr_contrast = {
        "why": ("prereg は irr を候補から外し『対照としては使う』と定めている。"
                "この台帳の既存の結論『上を狙うなら85／下を防ぐなら70』が"
                "**目的ごとに別の指標が要る**ことの実例なら、irr の刻みは象限で分かれて見えるはず。"),
        "pooled_2013_2015": pooled,
        "pooled_note": ("窓の長い2ビンテージ（13.09年/11.10年）だけを束ねた。刻みが 50/70/85/100 で"
                        "揃うのもこの2つだけ（2018 は 75）。⚠**2013 と 2015 はティッカーが重なる＝"
                        "独立標本ではない**ので、束ねた n も p 値も『独立な証拠の積み上げ』ではない。"
                        "ポアソンの p は『基準率どおりなら破壊が何件出るはずか』の目安であって検定ではない。"),
        "reproduces_existing_record": ("retro_moat_durability の既存の記録"
                                       "（irr=70 恒久毀損 0.02・n=101／irr=85 0.10・n=10）を、"
                                       "**別の解析集合で独立に再現している**"
                                       "（ここでは 70: 0/131・85: 2/19=0.105）。"
                                       "同じ台帳の二つの道具が同じことを言っている＝v9.9.65 の意味で健全。"),
        "analysis_set_recomputed_matches_W1D1": aset_check,
        "caveat": ("⚠ 刻みがビンテージで違う（2013/2015 は 50/70/85/100、2018 は 50/75/85）。"
                   "**通時で1本の系列として繋がない**。2016/2017 に読解は存在しない＝"
                   "prereg の必須ゲート（2016/2017/2018 の符号不変）は irr には当てられない。"
                   "n も小さい（2013 の 85 は6社・2018 は21社）＝方向の傍証であって検定ではない。"),
        "rows": irr_rows,
    }

    # ── 7) ゲートを当てられない変数（不合格ではなく判定不能） ──
    unevaluable = defaultdict(list)
    for r in rows:
        if not r["gate_evaluable"] and r["granularity"] == "四分位":
            unevaluable[r["variable"]] = sorted(set(unevaluable[r["variable"]]) | set(r["vintages_present"]))
    unevaluable_summary = {
        "why": ("prereg の必須ゲートは 2016/2017/2018 の符号不変。co_(2013/2015のみ)・pa_(2018のみ)・"
                "hv_/per(2016/2017に無い) は**結果を見る前から構造的に判定不能**。"
                "『不合格』と書いてはいけない（hist_valuation v1 の教訓のゲート版）。"),
        "variables": {k: v for k, v in sorted(unevaluable.items())},
        "n_variables": len(unevaluable),
    }

    out = {
        "generated": "2026-08-11",
        "tool": "night/hist_wd_asym.py",
        "prereg": "out/hist_winner_destroyer_prereg.json",
        "inputs": {"win": "out/hist_wd_win_uni.json", "destroy": "out/hist_wd_dst_uni.json"},
        "objective": ("勝者(A)と破壊(B)を同じ表に並べ、『上を狙う』と『下を防ぐ』で"
                      "採るべき変数が違うかを見る。**探索的**——合否は W1/D1 の verdict が持つ。"),
        "this_tool_computes_no_lift": ("lift は W1/D1 の値をそのまま読む（二重実装を作らない）。"
                                       "読む前に両者の構造一致を全セルで検算する。"),
        "verification_two_checkers_agree": verification,
        "quadrant_naming": {
            "axes": "横軸 lift_win / 縦軸 lift_destroy（どちらも P(群) − P(母集団)）",
            "右下": "純粋な追い風（勝者↑ 破壊↓）＝望ましい意味で『両方効く』のはここ",
            "左上": "純粋な向かい風（勝者↓ 破壊↑）",
            "右上": "極端を作る（勝者↑ 破壊↑）＝ボラティリティ型。**『両方効く』ではない**",
            "左下": "凪（勝者↓ 破壊↓）＝安全だが伸びない",
            "⚠依頼文との差": ("依頼文は『右上(両方効く)』と書いているが、右上は勝者も破壊も増える象限。"
                          "依頼文の項目3『勝者にも破壊にも正＝極端を作る』と同じ象限を指しており、"
                          "呼び名だけが食い違っている。右上を『両方効く』と読むと"
                          "**ボラティリティを選別力と誤認する**ので、ここでは象限名を実体で書く。"),
        },
        "base_rates": {
            "win": {str(v): win["analysis_set_size"][str(v)] for v in ALL_VINTAGES},
            "destroy": {str(v): dst["analysis_set_size"][str(v)] for v in ALL_VINTAGES},
            "note": ("破壊は稀事象。2015 は 503社中 **9件(1.8%)**＝この年は破壊側の分子が"
                     "どの群でも5に届きにくい。守る向き(破壊↓)はさらに届かない。"),
        },
        "how_to_read": {
            "coordinate": "2016/2017/2018 の lift の中央値。min|lift|と符号安定も併記。",
            "vintages_not_independent": ("2016/2017/2018 は同じ956ティッカーで窓が重なる。"
                                         "中央値は『3つの独立な証拠の代表値』ではない。"),
            "floors": ("象限の頭数は床 0.00/0.02/0.05/0.10 の4通りを全部出す。"
                       "床の選び方で結論が変わるなら、それは結論ではない。"),
            "explore_floor_is_outside_prereg": (f"片側判定の床 {EXPLORE_FLOOR} は依頼文の探索用。"
                                                f"prereg の線は {PREREG_LIFT}。ここから出るものは"
                                                "すべて**事前登録の外**で、合否には数えない。"),
            "mirror_cuts": ("同じ変数の 上位1/4 と 下位1/4 は鏡・中央値超と中央値以下は補集合。"
                            "1変数につき実質2つの見方しかないので、頭数は四分位だけで数える。"),
            "duplicate": "f2_rev と size_rev は D1 の実測で同一列。変数レベルでは1本に畳んだ。",
        },
        "quadrant_counts_by_floor": quad_counts,
        "one_sided_destroy_only": {
            "note": (f"|lift_destroy| >= {EXPLORE_FLOOR} かつ |lift_win| < {EXPLORE_FLOOR}。"
                     "＝破壊だけを分け、勝者を分けない群。**事前登録の外**"),
            "n": len(one_sided_destroy), "rows": one_sided_destroy[:40],
        },
        "one_sided_win_only": {
            "note": (f"|lift_win| >= {EXPLORE_FLOOR} かつ |lift_destroy| < {EXPLORE_FLOOR}。"
                     "＝勝者だけを分け、破壊を分けない群。**事前登録の外**"),
            "n": len(one_sided_win), "rows": one_sided_win[:40],
        },
        "both_sides_over_floor": {
            "note": f"両側とも |lift| >= {EXPLORE_FLOOR}。**事前登録の外**",
            "n": len(both_sides), "rows": both_sides[:40],
        },
        "extremes_makers": {
            "note": ("右上＝勝者にも破壊にも正。**この群を『両方効く』と読んではいけない**——"
                     "上も下も増える＝分散が大きいということ。20-30年の複利では"
                     "1回の恒久毀損が20年効くので、この象限は追い風ではない。"),
            "n": len(extremes), "top": extremes_top,
        },
        "calm_mirror": {
            "note": "左下＝勝者も破壊も減る（凪）。極端を作る変数の裏返しが凪なら、その軸は実在する。",
            "n": len(calm), "top": calm_top,
        },
        "instrument_asymmetry": instrument,
        "monotonicity_asymmetry": {
            "note": ("五分位の順位相関（spearman）を両側で並べる。1本の切り方より強い証拠——"
                     "『破壊側は単調なのに勝者側は平ら』なら、その変数は**下を防ぐためだけの変数**。"
                     "|spearman|>=0.6 を『単調に近い』の目安に使う（**探索用・事前登録の外**）。"),
            "support_rule": (f"破壊の総事象が {MIN_NUM*5} 件（五分位1ビンあたり平均 {MIN_NUM} 件＝"
                             "prereg の min_numerator を五分位に当てた数）に満たないビンテージが"
                             "あれば **spearman を読まない**。P_quality の破壊は総事象 4-10件で、"
                             "ビンが 0,1,1,0,2 のような数になる＝1社の移動で ρ が 0.5 動く。"),
            "destroy_monotone_win_flat": mono_destroy_only,
            "win_monotone_destroy_flat": mono_win_only,
            "monotone_on_both_sides": mono_both,
            "unsupported_looks_monotone_but_is_noise": {
                "note": ("|ρ|>=0.6 だが事象が足りない＝**発見として読んではいけない**もの。"
                         "隠さずに全部出す（次に同じ表を見た人が『単調だ』と拾わないため）。"),
                "n": len(mono_unsupported), "rows": mono_unsupported[:30],
            },
            "all_sorted_by_gap": mono[:40],
        },
        "variable_level_best_destroy_direction": {
            "note": ("変数ごとに『破壊|lift|が最大になる向き』を1本選び、**その同じ群で勝者側が"
                     "どうなっているか**を並べる。破壊の予言子が勝者も拾うのかを直接見る表。"),
            "rows": var_level[:60],
        },
        "irr_contrast_not_a_candidate": irr_contrast,
        "gate_unevaluable": unevaluable_summary,
        "limitations": {
            "exploratory": "この道具の出力に合否は無い。prereg の5条件の判定は W1/D1 が持つ。",
            "vintage_overlap": "2016/2017/2018 は独立標本ではない（同じ956ティッカー・窓が重なる）。",
            "rare_event": "破壊の分子は小さい。守る向きは min_numerator に構造的に届かない。",
            "survivorship": ("母集団はティッカーが解決できた社＝退場社が薄い。"
                             "破壊側は**この偏りの影響を最も強く受ける**（out/retro_delisted_secpx_2013.json の"
                             "挟み込みでは、2013年の恒久毀損は 2.00〜25.68% の幅がありうる）。"),
            "quartile_cannot_see_U": "四分位の切り方はU字を見られない。五分位の単調性で補っている。",
            "not_causal": "どれも同時点の相関。原因ではない。",
            "size_confound_not_cleared_for_all": (
                "破壊側の単変量で最強は size(f2_rev/size_rev)＝五分位で Q1 17-22% → Q5 1.1-1.6%。"
                "したがって他の破壊予言子は『size の言い換え』でありうる。D1 の size_shadow_diagnostic が"
                "size 四分位で層別しており、**f2_opm と f2_intcov は P_full の四分位で層別後も"
                "符号が3ビンテージ安定**（opm 下位1/4: MH 0.040/0.072/0.063、intcov 下位1/4: 0.028/0.044/0.074）"
                "＝size とは別の情報を持つ。**一方 f2_gm・f2_sga_r・f2_cash_r は P_full の四分位で"
                "size 層別が当てられていない＝size の影かどうか未確認**。ここは断定せず、"
                "次に測るべき先として名指しする。"),
            "gm_vs_opm_opposite_signs": (
                "f2_gm(粗利率) は破壊ρ +0.90 / 勝者ρ −0.82、f2_opm(営業利益率) は破壊ρ −0.90 / 勝者ρ −0.87 ＝"
                "**破壊に対して符号が逆**。差は営業費用（sga_r は破壊ρ +0.70）なので"
                "『粗利は高いが営業費用も高い＝営業利益率が低い』帯が破壊に寄っている、と読むのが整合的。"
                "ただしこれは3変数の符号から組み立てた解釈であって、"
                "**その帯を直接切って測ってはいない**（2本の積は W2/D2 の領分）。"),
        },
    }
    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ── 画面出力 ──
    print(f"検算: W1/D1 の構造一致 {verification['verdict']}（{len(kw)}セル・食い違い{len(mism)}件）")
    print(f"\n象限の頭数（四分位・ゲート判定可 {len(q_rows)}セル）")
    for fl, c in quad_counts.items():
        print(" ", fl, dict(sorted(c.items(), key=lambda x: -x[1])))
    print(f"\n片側だけ（床{EXPLORE_FLOOR}・事前登録の外）: 破壊のみ {len(one_sided_destroy)} / "
          f"勝者のみ {len(one_sided_win)} / 両側 {len(both_sides)}")
    for r in one_sided_destroy[:12]:
        print(f"  破壊のみ {r['variable']:16s} {r['population']:9s} {r['cut']:6s} "
              f"D{r['lift_destroy_med']:+.3f} W{r['lift_win_med']:+.3f} "
              f"倍率{r['ratio_destroy_over_win']} 安定D={r['destroy_sign_stable']}")
    for r in one_sided_win[:12]:
        print(f"  勝者のみ {r['variable']:16s} {r['population']:9s} {r['cut']:6s} "
              f"W{r['lift_win_med']:+.3f} D{r['lift_destroy_med']:+.3f} 安定W={r['win_sign_stable']}")
    print(f"\n極端を作る(右上) {len(extremes)}セル / 凪(左下) {len(calm)}セル")
    for r in extremes_top[:8]:
        print(f"  右上 {r['variable']:16s} {r['population']:9s} {r['cut']:6s} "
              f"W{r['lift_win_med']:+.3f} D{r['lift_destroy_med']:+.3f}")
    print("\n物差しの非対称（prereg の 0.15 は目的ごとに別の意味を持つ）")
    for v in GATE_VINTAGES:
        iv = instrument["by_vintage"][str(v)]
        print(f"  {v}: 勝者 base={iv['win']['base_rate']:.3f} "
              f"増↑{iv['win']['increase_reachable']} 減↓{iv['win']['decrease_reachable']} ／ "
              f"破壊 base={iv['destroy']['base_rate']:.3f} "
              f"増↑{iv['destroy']['increase_reachable']}(基準率の"
              f"{iv['destroy']['multiple_of_base_needed']}倍が必要) "
              f"減↓{iv['destroy']['decrease_reachable']}")

    print(f"\n五分位（事象数の支持あり）破壊だけ単調 {len(mono_destroy_only)}件 / "
          f"勝者だけ単調 {len(mono_win_only)}件 / 両側とも単調 {len(mono_both)}件 / "
          f"支持なし(雑音) {len(mono_unsupported)}件")
    for m in mono_destroy_only[:12]:
        print(f"  破壊のみ {m['variable']:14s} {m['population']:8s} 破壊ρ={m['destroy_med']:+.2f} "
              f"勝者ρ={m['win_med']:+.2f} 事象={list(m['destroy_events_by_vintage'].values())}")
    for m in mono_both[:12]:
        print(f"  両側     {m['variable']:14s} {m['population']:8s} 破壊ρ={m['destroy_med']:+.2f} "
              f"勝者ρ={m['win_med']:+.2f} 事象={list(m['destroy_events_by_vintage'].values())}")
    for m in mono_unsupported[:8]:
        print(f"  ⚠雑音   {m['variable']:14s} {m['population']:8s} 破壊ρ={m['destroy_med']:+.2f} "
              f"事象={list(m['destroy_events_by_vintage'].values())}")

    print("\n対照: irr そのもの（候補ではない）")
    bad = [c for c in aset_check if not c["match"]]
    print(f"  解析集合の検算: {'✓ W1/D1 と一致' if not bad else '⚠ 不一致'+str(bad)}")
    for r in irr_rows:
        print(f"  {r['vintage']} irr={r['irr']:3d} n={r['n']:3d} "
              f"勝者{r['win_p']:.3f}(lift{r['win_lift']:+.3f}) "
              f"破壊{r['destroy_p']:.3f}(lift{r['destroy_lift']:+.3f} RR{r['destroy_rr']}) "
              f"{r['quadrant'][:2] if r['quadrant'] else '-'}")
    print(f"\n→ {DEST}")


if __name__ == "__main__":
    main()
