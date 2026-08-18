# night/opmtrend_h6.py — H6（重ならない窓）: 利益率トレンドの検証を「終点が全部2026」から外す
#
# 事前登録: out/opm_trend_prereg.json の H6
#   「すべての窓が2026で終わる問題を外しても残るか。
#     月次パネルから重ならない窓（各39ヶ月×4）を作り、H1 を当て直す」
#
# ★この器がやること / やらないこと
#   やる  : 月次パネルから重ならない4窓を作り、**各窓の手前で測れる** opmD5 で H1 の線を当て直す
#   やらない: 値・規約・採点式・刻み・重み・関門・売却規律・配分にはいっさい触れない（読むだけ）
#            線を後から動かさない（lift>=0.15 ∧ すべての窓で符号が同じ）
#            結合・単位・到達可能性は opmtrend_base.json を読む（再実装しない・v9.9.65）
#            窓と cagr は night/retro_persistence.py の panel()/cagr() を import（再実装しない）
#
# ★H1 との違いは「窓」だけ。判定の手続き（プール・lift の向き・群の下限20・読み方i/ii/iii）は
#   opmtrend_h1.py と同一にしてある。**そうしないと「窓を変えたら結果が変わった」が
#   「手続きを変えたら結果が変わった」と区別できない。**
#
# ★look-ahead の封じ方（この器の肝）
#   retro_features2_{Y}.json は deadline = Y-07-01（filed<=その日）＝**Y-07-01 時点で読めた数字**。
#   窓の開始日より **後** の deadline を持つビンテージは絶対に使わない。
#   使うのは「窓の開始日以前で最も新しいビンテージ」だけ。違反したら測らずに止まる（exit 1）。
#
# ⚠ 窓の作り方は night/beat_spy_rule.py（2026-08-18・同じ4窓・同じSPY）と**同一**。
#   起動時に out/beat_spy_rule.json と突き合わせ、SPYと社数が食い違ったら止まる
#   ——同じ台帳を見る二つの器が違うことを言ってはいけない（v9.9.65）。
#
# 実行: python3 night/opmtrend_h6.py [--json]
# 出力: out/opmtrend_h6.json

import json
import os
import random
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

from retro_persistence import panel, cagr            # noqa: E402  窓と年率は再実装しない
from opmtrend_base import load_base                  # noqa: E402  結合・単位・プールは再実装しない

WIN_M = 39            # 39ヶ月×4 = 13年（beat_spy_rule.py と同一。新しい定数を作らない）
N_WIN = 4
LINE_LIFT = 0.15      # 事前登録 H1 の線（動かさない）
HURDLE = 0.15         # 事前登録: 前方年率 >= 0.15
MIN_GROUP = 20        # opmtrend_h1.py と同一の「群が薄い」下限
N_PERM = 2000
SEED = 20260818


def r4(x):
    return None if x is None else round(x, 4)


def lab(k):
    return f"{k // 12}-{k % 12 + 1:02d}"


def share(rows, f):
    return sum(1 for r in rows if f(r)) / len(rows) if rows else None


def die(msg):
    print("■ 測定を中止する: " + msg)
    sys.exit(1)


def spy_monthly():
    """SPY の月次 adjclose。**取りに行かない**——beat_spy_rule.py が置いた在庫を読むだけ。
    無ければ測らずに止まる（黙って別のベンチマークへ倒すと『基準の違う二つ』を自分で作る）。"""
    p = os.path.join(OUT, "_spy_monthly.json")
    if not os.path.exists(p):
        die("out/_spy_monthly.json が無い（先に python3 night/beat_spy_rule.py を回すこと）")
    return {int(k): v for k, v in json.load(open(p)).items()}


def build():
    random.seed(SEED)
    B = load_base()
    P = panel()
    S = spy_monthly()

    # ---------- 窓（beat_spy_rule.py と同一の作り方） ----------
    k0 = min(min(v) for v in P.values() if v)
    wins = [(k0 + i * WIN_M, k0 + (i + 1) * WIN_M) for i in range(N_WIN)]
    for a, b in wins:
        if a not in S or b not in S:
            die(f"SPY が窓の端 {lab(a)}/{lab(b)} を持っていない")

    # ---------- ★兄弟器との突合せ（同じ窓・同じSPYを二度実装していないことの証明） ----------
    xchk = {"file": "out/beat_spy_rule.json", "ok": None, "detail": []}
    bp = os.path.join(OUT, "beat_spy_rule.json")
    if os.path.exists(bp):
        bw = json.load(open(bp)).get("windows") or []
        ok = len(bw) == N_WIN
        for i, (a, b) in enumerate(wins):
            spy_i = (S[b] / S[a]) ** (12.0 / (b - a)) - 1
            n_i = sum(1 for t in P if cagr(P[t], a, b) is not None)
            got = bw[i] if i < len(bw) else {}
            m1 = got.get("spy") is not None and abs(got["spy"] - spy_i) < 1e-9
            m2 = got.get("n") == n_i
            ok = ok and m1 and m2
            xchk["detail"].append({"w": i + 1, "spy_here": r4(spy_i), "spy_there": r4(got.get("spy")),
                                   "n_here": n_i, "n_there": got.get("n"), "match": bool(m1 and m2)})
        xchk["ok"] = bool(ok)
        if not ok:
            die("beat_spy_rule.json と窓/SPY/社数が食い違う（同じ台帳を見る二つの器が違うことを言っている）")
    else:
        xchk["ok"] = None
        xchk["note"] = "beat_spy_rule.json が無いので突合せできない"

    # ---------- ★信号の時点（look-ahead の封じ込み） ----------
    # features2 の deadline は Y-07-01。窓の開始「以前」で最も新しいものだけを使う。
    vintages = sorted({r["vintage"] for r in B["rows"]})
    dl = {}
    for y in vintages:
        f = os.path.join(OUT, f"retro_features2_{y}.json")
        d = json.load(open(f)).get("deadline") if os.path.exists(f) else None
        if d != f"{y}-07-01":
            die(f"ビンテージ {y} の deadline が想定と違う（{d}）——時点の仮定が崩れている")
        dl[y] = y * 12 + 6          # Y-07 の月キー

    mapping = []
    for i, (a, b) in enumerate(wins):
        cand = [y for y in vintages if dl[y] <= a]
        if not cand:
            die(f"W{i+1}（{lab(a)} 開始）の手前に使えるビンテージが無い")
        v = max(cand)
        gap = a - dl[v]
        if dl[v] > a:
            die(f"look-ahead: W{i+1} は {lab(a)} に始まるのに信号が {lab(dl[v])} 時点")
        mapping.append({"w": i + 1, "window": f"{lab(a)}→{lab(b)}", "k0": a, "k1": b,
                        "years": round((b - a) / 12.0, 2),
                        "vintage": v, "signal_asof": f"{v}-07-01",
                        "gap_months": gap,
                        "spy": r4((S[b] / S[a]) ** (12.0 / (b - a)) - 1),
                        "unused_later_vintages": [y for y in vintages if dl[y] > a and y < v + 12]})

    # ---------- 行を組む ----------
    brow = {(r["vintage"], r["ticker"]): r for r in B["rows"]}
    warns = []
    per_window = []
    W = {}                     # (w, pool) -> rows
    for mp in mapping:
        a, b, v = mp["k0"], mp["k1"], mp["vintage"]
        yrs = (b - a) / 12.0
        spy = (S[b] / S[a]) ** (1 / yrs) - 1
        rows, short = [], 0
        for t, m in P.items():
            c = cagr(m, a, b)
            if c is None:
                continue
            ks = [k for k in m if a <= k <= b]
            full = (min(ks) == a and max(ks) == b)
            if not full:
                short += 1
            r = brow.get((v, t))
            rows.append({"ticker": t, "tr": c, "full_span": full,
                         "opmD5": (r or {}).get("opmD5"),
                         "opm": (r or {}).get("opm"),
                         "qual": bool((r or {}).get("qual")) and not (r or {}).get("qual_na"),
                         "in_vintage": r is not None,
                         "rev": (r or {}).get("rev"), "sic2": (r or {}).get("sic2")})
        mp["n_panel"] = len(rows)
        mp["n_short_span"] = short
        mp["n_in_vintage"] = sum(1 for r in rows if r["in_vintage"])
        mp["n_opmD5"] = sum(1 for r in rows if r["opmD5"] is not None)
        mp["coverage_opmD5"] = r4(mp["n_opmD5"] / len(rows)) if rows else None
        mp["base_hit"] = r4(share(rows, lambda r: r["tr"] >= HURDLE))
        mp["base_beat"] = r4(share(rows, lambda r: r["tr"] > spy))
        mp["median_tr"] = r4(st.median([r["tr"] for r in rows])) if rows else None
        for pool in ("all", "qual"):
            W[(mp["w"], pool)] = [r for r in rows
                                  if (pool == "all" or r["qual"]) and r["opmD5"] is not None]
        per_window.append(mp)
        if mp["coverage_opmD5"] is not None and mp["coverage_opmD5"] < 0.6:
            warns.append(f"W{mp['w']}（信号=ビンテージ{v}）の opmD5 被覆が "
                         f"{mp['coverage_opmD5']*100:.0f}%——他の窓と同じ母集団ではない")

    # ---------- セル（H1 と同一の手続き） ----------
    def cell(w, pool, strict_span=False):
        a = next(m for m in mapping if m["w"] == w)
        spy = (S[a["k1"]] / S[a["k0"]]) ** (12.0 / (a["k1"] - a["k0"])) - 1
        rows = W[(w, pool)]
        if strict_span:
            rows = [r for r in rows if r["full_span"]]
        A = [r for r in rows if r["opmD5"] >= 0]
        Bg = [r for r in rows if r["opmD5"] < 0]
        hit = lambda r: r["tr"] >= HURDLE          # noqa: E731
        beat = lambda r: r["tr"] > spy             # noqa: E731
        rec = {"w": w, "pool": pool, "window": a["window"], "vintage": a["vintage"],
               "n": len(rows), "n_pos": len(A), "n_neg": len(Bg),
               "spy": r4(spy), "usable": False,
               "base_hit": r4(share(rows, hit)), "base_beat": r4(share(rows, beat)),
               "p_hit_pos": r4(share(A, hit)), "p_hit_neg": r4(share(Bg, hit)),
               "p_beat_pos": r4(share(A, beat)), "p_beat_neg": r4(share(Bg, beat)),
               "median_tr_pos": r4(st.median([r["tr"] for r in A])) if A else None,
               "median_tr_neg": r4(st.median([r["tr"] for r in Bg])) if Bg else None}
        rec["lift_hit"] = (r4(share(A, hit) - share(Bg, hit)) if (A and Bg) else None)
        rec["lift_beat"] = (r4(share(A, beat) - share(Bg, beat)) if (A and Bg) else None)
        if len(A) < MIN_GROUP or len(Bg) < MIN_GROUP:
            rec["why_not"] = f"群が薄い（非負{len(A)} / 負{len(Bg)}・下限{MIN_GROUP}）"
        else:
            rec["usable"] = True
        return rec

    cells = [cell(w, p) for w in range(1, N_WIN + 1) for p in ("all", "qual")]
    for c in cells:
        if c["n_pos"] == 0 or c["n_neg"] == 0:
            warns.append(f"W{c['w']}/{c['pool']}: 片群が0社——照合の失敗を疑うこと（0件は測定ではない）")

    # ---------- 線に照らす ----------
    def summarize(key, pool, cs):
        ok = [c for c in cs if c["usable"] and c[key] is not None]
        lifts = [c[key] for c in ok]
        pos = sum(1 for v in lifts if v > 0)
        neg = sum(1 for v in lifts if v < 0)
        same = (len(ok) == len(cs)) and (pos == len(ok) or neg == len(ok))
        # プール読み: 4窓の行を束ねる（会社が複数窓に出るので独立ではない・注記する）
        allrows = []
        for w in range(1, N_WIN + 1):
            allrows += [dict(r, _w=w) for r in W[(w, pool)]]
        spyd = {m["w"]: (S[m["k1"]] / S[m["k0"]]) ** (12.0 / (m["k1"] - m["k0"])) - 1
                for m in mapping}
        f = ((lambda r: r["tr"] >= HURDLE) if key == "lift_hit"
             else (lambda r: r["tr"] > spyd[r["_w"]]))
        A = [r for r in allrows if r["opmD5"] >= 0]
        Bg = [r for r in allrows if r["opmD5"] < 0]
        pooled = (share(A, f) - share(Bg, f)) if (A and Bg) else None
        wmean = (sum(c[key] * c["n"] for c in ok) / sum(c["n"] for c in ok)) if ok else None
        reads = {"i_strict_all_windows_ge_line": (len(ok) == len(cs) and
                                                  all(v >= LINE_LIFT for v in lifts)),
                 "ii_pooled_ge_line": (pooled is not None and pooled >= LINE_LIFT),
                 "iii_median_ge_line": (bool(lifts) and st.median(lifts) >= LINE_LIFT)}
        if len(ok) == 0:
            verdict = "判定不能"
        elif same and any(reads.values()):
            verdict = "合格"
        else:
            verdict = "不合格"
        return {"windows": len(cs), "usable_windows": len(ok), "lifts": lifts,
                "n_lift_ge_line": sum(1 for v in lifts if v >= LINE_LIFT),
                "sign_pos": pos, "sign_neg": neg,
                "all_same_sign": same,
                "pooled_lift": r4(pooled), "median_lift": r4(st.median(lifts)) if lifts else None,
                "mean_lift_weighted": r4(wmean),
                "min_lift": r4(min(lifts)) if lifts else None,
                "max_lift": r4(max(lifts)) if lifts else None,
                "readings": reads, "verdict": verdict,
                "why": (f"符号が4窓で揃わない、または lift がどの読み方でも線 {LINE_LIFT:.2f} に届かない"
                        if verdict == "不合格" else None)}

    summary = {}
    for pool in ("all", "qual"):
        cs = [c for c in cells if c["pool"] == pool]
        summary[pool] = {"hurdle15": summarize("lift_hit", pool, cs),
                         "beat_spy": summarize("lift_beat", pool, cs)}

    # ---------- 頑健性: 窓を丸ごと持っている社だけ ----------
    strict_cells = [cell(w, p, strict_span=True) for w in range(1, N_WIN + 1)
                    for p in ("all", "qual")]
    strict = {}
    for pool in ("all", "qual"):
        cs = [c for c in strict_cells if c["pool"] == pool]
        ok = [c for c in cs if c["usable"] and c["lift_hit"] is not None]
        lf = [c["lift_hit"] for c in ok]
        lb = [c["lift_beat"] for c in ok if c["lift_beat"] is not None]
        strict[pool] = {"lifts_hit": lf, "median_hit": r4(st.median(lf)) if lf else None,
                        "lifts_beat": lb, "median_beat": r4(st.median(lb)) if lb else None,
                        "all_same_sign_hit": bool(lf) and (all(v > 0 for v in lf) or
                                                           all(v < 0 for v in lf)),
                        "n_dropped": sum(c0["n"] - c1["n"] for c0, c1
                                         in zip([c for c in cells if c["pool"] == pool], cs))}

    # ---------- 置換検定（会社単位の一つの並べ替えを4窓へ同時に当てる） ----------
    perm = {}
    for pool in ("all", "qual"):
        cs = [c for c in cells if c["pool"] == pool and c["usable"]]
        if not cs:
            perm[pool] = {"note": "使えるセルが無い"}
            continue
        tick = sorted({r["ticker"] for w in range(1, N_WIN + 1) for r in W[(w, pool)]})
        sig = {}
        for w in range(1, N_WIN + 1):
            for r in W[(w, pool)]:
                sig.setdefault(r["ticker"], []).append(r["opmD5"])
        # 会社の代表符号（複数窓に出る社は各窓の値を持つ——並べ替えは「会社→会社」で行う）
        obs = st.median([c["lift_hit"] for c in cs])
        spyd = {m["w"]: (S[m["k1"]] / S[m["k0"]]) ** (12.0 / (m["k1"] - m["k0"])) - 1
                for m in mapping}
        nulls, passes = [], 0
        for _ in range(N_PERM):
            sh = tick[:]
            random.shuffle(sh)
            mapt = dict(zip(tick, sh))          # 会社→会社（全窓へ同じ写像を当てる）
            lf = []
            for w in range(1, N_WIN + 1):
                rows = W[(w, pool)]
                d5 = {r["ticker"]: r["opmD5"] for r in rows}
                A, Bg = [], []
                for r in rows:
                    v = d5.get(mapt[r["ticker"]])
                    if v is None:
                        continue
                    (A if v >= 0 else Bg).append(r)
                if len(A) < MIN_GROUP or len(Bg) < MIN_GROUP:
                    lf = []
                    break
                lf.append(share(A, lambda r: r["tr"] >= HURDLE) -
                          share(Bg, lambda r: r["tr"] >= HURDLE))
            if not lf:
                continue
            nulls.append(st.median(lf))
            same = all(v > 0 for v in lf) or all(v < 0 for v in lf)
            if same and st.median(lf) >= LINE_LIFT:
                passes += 1
        nulls.sort()
        ge = sum(1 for v in nulls if v >= obs)
        perm[pool] = {"n_perm": len(nulls), "observed_median_lift": r4(obs),
                      "null_median_p50": r4(nulls[len(nulls) // 2]) if nulls else None,
                      "null_median_p95": r4(nulls[int(len(nulls) * 0.95)]) if nulls else None,
                      "p_value_median_lift": round((ge + 1) / (len(nulls) + 1), 4) if nulls else None,
                      "false_positive_rate_of_procedure": round(passes / len(nulls), 4) if nulls else None,
                      "note": "会社→会社の一つの写像を4窓へ同時に当てる（窓間の従属を壊さない）"}

    # ---------- 検出力（この手続きは真の効果をどれだけ掴めるか） ----------
    power = {}
    for pool in ("all", "qual"):
        cs = [c for c in cells if c["pool"] == pool and c["usable"]]
        if len(cs) < N_WIN:
            power[pool] = {"note": f"使える窓が{len(cs)}/{N_WIN}——検出力を測れない"}
            continue
        g = {}
        for d in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
            hit = 0
            for _ in range(N_PERM):
                lf = []
                for c in cs:
                    n1, n0, p = c["n_pos"], c["n_neg"], c["base_hit"]
                    n = n1 + n0
                    p1 = min(0.999, max(0.001, p + d * n0 / n))
                    p0 = min(0.999, max(0.001, p - d * n1 / n))
                    x1 = sum(1 for _ in range(n1) if random.random() < p1)
                    x0 = sum(1 for _ in range(n0) if random.random() < p0)
                    lf.append(x1 / n1 - x0 / n0)
                same = all(v > 0 for v in lf) or all(v < 0 for v in lf)
                if same and st.median(lf) >= LINE_LIFT:
                    hit += 1
            g[f"{d:.2f}"] = round(hit / N_PERM, 4)
        power[pool] = g


    # ---------- 探索（★事前登録に無い。合否・線の根拠にしない。記述のみ） ----------
    # W1 の信号だけビンテージ2013で、opmD5 の被覆が約48%・欠測が小型に偏る（base の警告）。
    # 「W1 が唯一はっきり正なのは、母集団が大型に寄っているからでは」を潰すため、
    # **他の3窓を W1 と同じ社の部分集合に揃えて**当て直す。
    cov13 = {t for (v, t), r in brow.items() if v == 2013 and r.get("opmD5") is not None}
    expl = {"caveat": "事前登録に無い事後の切り方。合否・線の根拠にしない。記述のみ",
            "question": "W1 が唯一はっきり正なのは母集団（ビンテージ2013の被覆＝大型寄り）のせいか",
            "rows": []}
    for w in range(1, N_WIN + 1):
        for pool in ("all", "qual"):
            for sub, nm in ((None, "全部"), (cov13, "2013被覆の社だけ")):
                rows = [r for r in W[(w, pool)] if sub is None or r["ticker"] in sub]
                A = [r for r in rows if r["opmD5"] >= 0]
                Bg = [r for r in rows if r["opmD5"] < 0]
                hit = lambda r: r["tr"] >= HURDLE          # noqa: E731
                expl["rows"].append({
                    "w": w, "pool": pool, "subset": nm, "n": len(rows),
                    "n_pos": len(A), "n_neg": len(Bg),
                    "lift_hit": (r4(share(A, hit) - share(Bg, hit))
                                 if (len(A) >= MIN_GROUP and len(Bg) >= MIN_GROUP) else None)})
    expl["reading"] = ("W2〜W4 を W1 と同じ社へ揃えると lift はむしろ負へ動く＝"
                       "W1 の正の lift は『大型なら効く』では説明が付かない（窓の側の特異）")

    # ---------- 線にいちばん近かったセル（自分に不利な数字も出す） ----------
    near = []
    for c in cells:
        for k, nm in (("lift_hit", "15%+"), ("lift_beat", "SPY超")):
            if c["usable"] and c[k] is not None:
                near.append({"w": c["w"], "pool": c["pool"], "outcome": nm,
                             "lift": c[k], "gap_to_line": r4(LINE_LIFT - c[k])})
    near.sort(key=lambda x: -x["lift"])
    closest = {"top3": near[:3],
               "note": ("★最大でも線に届かない。しかも仮に届いても手続きは"
                        "『すべての窓で符号が同じ』を同時に要求するので、1セルでは合格にならない")}

    # ---------- H1（終点が全部2026）との対比 ----------
    vs = {"note": "窓を重ならないものに替えても lift の大きさは同じ帯に留まるか"}
    hp = os.path.join(OUT, "opmtrend_h1.json")
    if os.path.exists(hp):
        h1 = json.load(open(hp))
        vs["rows"] = []
        for pool in ("all", "qual"):
            a = h1["h1_summary"][pool]
            b = summary[pool]["hurdle15"]
            vs["rows"].append({"pool": pool, "outcome": "15%+",
                               "h1_median": a["median_lift"], "h1_min": a["min_lift"],
                               "h1_max": a["max_lift"], "h1_verdict": a["verdict"],
                               "h6_median": b["median_lift"], "h6_min": b["min_lift"],
                               "h6_max": b["max_lift"], "h6_verdict": b["verdict"]})
            ab = a["beat"]
            bb = summary[pool]["beat_spy"]
            vs["rows"].append({"pool": pool, "outcome": "ベンチ超",
                               "h1_median": ab["median_lift"], "h1_spy_only_median": ab["spy_only_median"],
                               "h6_median": bb["median_lift"], "h6_verdict": bb["verdict"],
                               "note": "H1 のベンチは SPY と EW の混成／H6 は4窓とも実SPY"})
    else:
        vs["rows"] = None

    out = {
        "generated": "2026-08-18", "tool": "night/opmtrend_h6.py",
        "prereg": "out/opm_trend_prereg.json",
        "hypothesis": "H6（重ならない窓）: すべての窓が2026-08で終わる問題を外しても H1 は残るか",
        "reads": ["out/opmtrend_base.json", "out/retro_monthly_*.json", "out/_spy_monthly.json",
                  "out/retro_features2_*.json（deadline の確認のみ）", "out/beat_spy_rule.json（突合せ）"],
        "writes_nothing_else": "値・規約・採点式・刻み・重み・関門・売却規律・配分には1バイトも触っていない",
        "seed": SEED,
        "line_from_prereg": ("H1 の線をそのまま当てる: lift >= 0.15 かつ **すべての窓で符号が同じ**"
                             "（事前登録の『8ビンテージすべて』の『すべて』を4窓へ機械的に当てただけ。"
                             "線 0.15 も lift の向きも群の下限20も H1 と同一）"),
        "lift_direction": "lift = P(前方年率>=15% | opmD5>=0) − P(... | opmD5<0)（事前登録 H1 と同一）",
        "window_def": {"months": WIN_M, "n": N_WIN,
                       "how": "night/beat_spy_rule.py と同一（k0=パネル最古月から39ヶ月ずつ・端点は共有）",
                       "windows": [f"{lab(a)}→{lab(b)}" for a, b in wins]},
        "cross_check_vs_beat_spy_rule": xchk,
        "signal_timing": mapping,
        "per_window": per_window,
        "cells": cells,
        "summary": summary,
        "strict_full_span": strict,
        "permutation": perm,
        "power": power,
        "closest_to_line": closest,
        "vs_h1_same_procedure_different_windows": vs,
        "exploratory_not_preregistered": expl,
        "warnings": warns,
        "limits": [
            "4窓は同じ956社のパネル＝会社が最大4回出る。窓どうしは期間としては重ならないが**標本としては独立ではない**",
            "★W1 の信号はビンテージ2013で opmD5 の被覆が約48%・しかも欠測が小型に偏る（base の警告）＝他の3窓と同じ母集団ではない",
            "信号と窓の開始のあいだに 0/3/6/9ヶ月の隙間がある（使える中で最も新しいビンテージを使った結果）",
            "各窓は3.25年＝13年の窓より短く、年率の分散が大きい。ベース率も窓ごとに大きく違う",
            "パネルは今日ティッカーが引ける社＝生存バイアス（既記録）",
            "SPY は配当込み(adjclose)・個別も同じ adjclose なので基準は揃っている",
            "この器は上限や機構を測るものではない。H1 の線に照らして合否を出すだけ",
        ],
    }
    return out


def main():
    o = build()
    if "--json" in sys.argv:
        print(json.dumps(o, ensure_ascii=False, indent=1))
    else:
        print("■ H6（重ならない窓）——終点が全部2026という問題を外して H1 を当て直す\n")
        x = o["cross_check_vs_beat_spy_rule"]
        print(f"兄弟器との突合せ（out/beat_spy_rule.json）: "
              f"{'✓一致' if x['ok'] else ('—' if x['ok'] is None else '✗')}")
        print("\n■ 信号の時点（look-ahead の封じ込み）")
        print("  窓                     年数  信号=ビンテージ  信号のasof     隙間  SPY年率  母集団  opmD5被覆")
        for m in o["signal_timing"]:
            w = next(p for p in o["per_window"] if p["w"] == m["w"])
            print(f"  W{m['w']} {m['window']:<18}{m['years']:>5}   {m['vintage']}"
                  f"        {m['signal_asof']}   {m['gap_months']:>2}ヶ月"
                  f"  {m['spy']*100:+6.2f}%  {w['n_panel']:>4}社"
                  f"   {w['coverage_opmD5']*100:>5.1f}%")
        print("\n■ 窓ごとの基礎率")
        print("  窓   15%+の割合  SPY超の割合  中央年率  端まで無い社")
        for w in o["per_window"]:
            print(f"  W{w['w']}  {w['base_hit']*100:>7.1f}%   {w['base_beat']*100:>7.1f}%"
                  f"   {w['median_tr']*100:>+7.2f}%   {w['n_short_span']:>4}社")
        for key, nm in (("lift_hit", "① 前方年率 >= 15%"), ("lift_beat", "② SPY超")):
            print(f"\n■ {nm}：lift = P(・|opmD5>=0) − P(・|opmD5<0)")
            print("  プール  窓  n(非負/負)   P(非負)  P(負)   lift    使えるか")
            for c in o["cells"]:
                p1 = c["p_hit_pos"] if key == "lift_hit" else c["p_beat_pos"]
                p0 = c["p_hit_neg"] if key == "lift_hit" else c["p_beat_neg"]
                lv = c[key]
                print(f"  {c['pool']:<6} W{c['w']}  {c['n_pos']:>4}/{c['n_neg']:<4}"
                      f"  {'—' if p1 is None else f'{p1*100:6.1f}%'}"
                      f" {'—' if p0 is None else f'{p0*100:6.1f}%'}"
                      f"  {'—' if lv is None else f'{lv:+.4f}'}"
                      f"   {'✓' if c['usable'] else c.get('why_not','')}")
            for pool in ("all", "qual"):
                s = o["summary"][pool]["hurdle15" if key == "lift_hit" else "beat_spy"]
                print(f"  → {pool}: 中央 {s['median_lift']} / プール {s['pooled_lift']}"
                      f" / 加重平均 {s['mean_lift_weighted']}"
                      f" / 符号 +{s['sign_pos']} −{s['sign_neg']}"
                      f" / 符号一致 {s['all_same_sign']} / 線以上 {s['n_lift_ge_line']}窓"
                      f"  ⇒ **{s['verdict']}**")
        print("\n■ 頑健性（窓の端まで在る社だけ）")
        for pool in ("all", "qual"):
            s = o["strict_full_span"][pool]
            print(f"  {pool}: 15%+ の lift {s['lifts_hit']} 中央 {s['median_hit']}"
                  f" ／ SPY超 中央 {s['median_beat']} ／ 落ちた行 {s['n_dropped']}")
        print("\n■ 置換検定 / 検出力")
        for pool in ("all", "qual"):
            p = o["permutation"][pool]
            print(f"  {pool}: 観測の中央lift {p.get('observed_median_lift')}"
                  f" ／ 帰無 p50 {p.get('null_median_p50')} p95 {p.get('null_median_p95')}"
                  f" ／ p={p.get('p_value_median_lift')}"
                  f" ／ 手続きの偽陽性率 {p.get('false_positive_rate_of_procedure')}")
            print(f"       検出力 {o['power'][pool]}")
        print("\n■ 線にいちばん近かったセル（自分に不利な数字も出す）")
        for t in o["closest_to_line"]["top3"]:
            print(f"  W{t['w']}/{t['pool']}/{t['outcome']}  lift {t['lift']:+.4f}"
                  f"  線まであと {t['gap_to_line']:+.4f}")
        if o["vs_h1_same_procedure_different_windows"].get("rows"):
            print("\n■ H1（終点が全部2026）との対比——手続きは同一・窓だけ違う")
            for r in o["vs_h1_same_procedure_different_windows"]["rows"]:
                print(f"  {r['pool']:<5}{r['outcome']:<7} H1 中央 {r['h1_median']:+.4f}"
                      f" ／ H6 中央 {r['h6_median']:+.4f}")
        print("\n■ 探索（事前登録に無い・合否に使わない）: W1 の母集団の効き")
        for r in o["exploratory_not_preregistered"]["rows"]:
            if r["subset"] == "2013被覆の社だけ":
                v = r["lift_hit"]
                print(f"  W{r['w']}/{r['pool']:<5} 2013被覆の社だけ n={r['n']:>4}"
                      f" lift {'—' if v is None else format(v, '+.4f')}")
        if o["warnings"]:
            print("\n■ 警告")
            for w in o["warnings"]:
                print("  ⚠ " + w)
    with open(os.path.join(OUT, "opmtrend_h6.json"), "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    print("\n→ out/opmtrend_h6.json")


if __name__ == "__main__":
    main()
