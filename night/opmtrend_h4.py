#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/opmtrend_h4.py — H4『事業の収縮』を8ビンテージへ広げて再現するか裁く（2026-08-18新設）

事前登録: out/opm_trend_prereg.json の H4_shrink_gate
  q:    門の関門 cagr<0 ∧ gmt=down の相当物 = **cagr5<0 ∧ opmD5<0** は歴史で成立するか
  note: retro_breaker_test が2018年ビンテージで既に測っている（止めた49社・恒久毀損14.3%＝
        ベース4.5%の3.2倍）。**ここでは8ビンテージへ広げて再現するかを見る**
  line: H2 と同じ ＝「濃縮≥2.0倍 ∧ 分子≥5社 ∧ 止めた群の中央値が通過群より低い ∧ 止率≤15%」
        （hist_val v2 の6基準を流用・新しい物差しを作らない）

★この器は**線を一つも発明しない**。閾値は規則の中に無い（cagr5<0 ∧ opmD5<0 は自由変数ゼロ）。
★土台は out/opmtrend_base.json を読む。結合も窓も**再実装しない**（v9.9.65）。

────────────────────────────────────────────────────────────────────────
■ 走らせる前に固定した判定規則（結果を見てから緩めない）
────────────────────────────────────────────────────────────────────────
[セル別]（ビンテージ × プール）
  判定不能 : 土台の reachability が reachable=false（神の遮断器でも分子5に届かない）
  合格     : c1 ∧ c2 ∧ c4
             c1 = 濃縮(止めた群の恒久毀損率 ÷ プールのベース率) ≥ 2.0 **かつ** 分子(止めた群の毀損社数) ≥ 5
             c2 = 止めた群の中央値 ≤ 通過群の中央値（勝者を巻き込んでいない）
             c4 = 止率 ≤ 15%（遮断器であって間引きではない）
  不合格   : それ以外
  ※c3(ビンテージ間の頑健性)は下の[全体]で当てる。
  ※c5(増分)は **H4 では定義上判定不能**——この規則そのものが既存の第四の関門なので、
    「既に落ちる社を除く」と止めた群がそのまま消える。代わりに事前登録に無い**適応**として
    「片方だけ（cagr5<0のみ / opmD5<0のみ）と較べて積が増分を持つか」を測り、そう明記する。
  ※c6(恣意でない)は **構造上成立**——規則に自由変数が無く、格子も方向も選ぶ余地が無い。

[全体]（★これを H4 の合否とする）
  プール別: 合格 = **判定可能な全ビンテージ**でセル別の線が成立
    → 事前登録がこの文書内で cross-vintage に置いている唯一の線は H1 の
      「**8ビンテージすべてで符号が同じ**」。それを H4 に当てた最も厳しい読み。
      「過半数で合格」のような緩い読みは**結果を見てから作らない**。
  H4 の合否: **all / qual のどちらか一方でもプール別合格なら合格。両方とも不成立なら不合格。**
  （参考として「何/何ビンテージで成立したか」も必ず出す＝どれだけ惜しかったかを隠さない）

────────────────────────────────────────────────────────────────────────
■ 欠測の扱い（★結論を左右するので二通り出す）
  (a) 主判定 = `(cagr5 or 0) < 0 and (opmD5 or 0) < 0`
      ＝ retro_breaker_test.py:118 と hist_val_gate_test.shrink_flags と**同じ式**。
      門の ccfShrinkGate も gmt の空欄では発火しない（SELECT既定 'flat'）ので、
      **実挙動に一致するのはこちら**。欠測は「止めない側」へ入る。
  (b) 感度 = 欠測を na として**両群から外す**（ルール7「欠測をゼロと読むな」の読み）。
      2013 は opmD5 の被覆が48%しか無いので、この二つは同じ数字にならない。両方出す。

実行: python3 night/opmtrend_h4.py [--json]
在庫: out/opmtrend_h4.json
"""
import json
import os
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

# 土台を再実装しない（v9.9.65）。opmtrend_base は retro_persistence の panel/cagr を import 済み。
from opmtrend_base import load_base, HURDLE, IMPAIR, MIN_NUM, MAX_STOP  # noqa: E402

CONC_MIN = 2.0   # 事前登録 H2/H4 の濃縮の線（hist_val v2 基準1の流用）
WRITE = "--json" in sys.argv[1:]


def load(fn):
    with open(os.path.join(OUT, fn), encoding="utf-8") as f:
        return json.load(f)


# ── 規則（自由変数ゼロ） ────────────────────────────────────────────────
def leg_cagr(r, strict=False):
    v = r.get("cagr5")
    if v is None:
        return None if strict else False
    return v < 0


def leg_opm(r, strict=False):
    v = r.get("opmD5")
    if v is None:
        return None if strict else False
    return v < 0


RULES = {
    "and": ("事業の収縮 = cagr5<0 ∧ opmD5<0（門の第四の関門の相当物）",
            lambda r, s: None if (leg_cagr(r, s) is None or leg_opm(r, s) is None)
            else (leg_cagr(r, s) and leg_opm(r, s))),
    "cagr_only": ("売上縮小のみ cagr5<0", lambda r, s: leg_cagr(r, s)),
    "opm_only": ("営業利益率低下のみ opmD5<0", lambda r, s: leg_opm(r, s)),
}


def grp(rows):
    """止めた/通した群の姿。tr_cagr は**小数**（base の単位）で持つ。"""
    if not rows:
        return None
    v = [r["tr_cagr"] for r in rows]
    n_imp = sum(1 for x in v if x <= IMPAIR)
    return dict(n=len(rows),
                med=round(st.median(v), 4),
                impair=round(n_imp / len(rows), 4), n_impair=n_imp,
                loss=round(sum(1 for x in v if x < 0) / len(rows), 4),
                hurdle=round(sum(1 for x in v if x >= HURDLE) / len(rows), 4),
                worst=round(min(v), 4))


def measure(pool, rule_key, strict=False):
    """一つの (プール × 規則) を測る。判定はしない。"""
    _, fn = RULES[rule_key]
    stop, pas, na = [], [], []
    for r in pool:
        hit = fn(r, strict)
        (na if hit is None else (stop if hit else pas)).append(r)
    b = grp(stop)
    p = grp(pas)
    base = grp(stop + pas)          # ★ベースは判定に使った母集団（na を除く）
    if base is None:
        return None
    conc = (round(b["impair"] / base["impair"], 3)
            if (b and base["impair"] > 0) else None)
    return dict(rule=rule_key, strict=strict,
                n_pool=len(pool), n_used=len(stop) + len(pas), n_na=len(na),
                stop_rate=round(len(stop) / (len(stop) + len(pas)), 4) if (stop or pas) else None,
                base=base, blocked=b, passed=p,
                concentration=conc,
                impair_lift=round(b["impair"] - base["impair"], 4) if b else None)


def judge(m, reachable, why_not):
    """★セル別の合否。線は上の docstring で走らせる前に固定済み。"""
    if not reachable:
        return dict(verdict="判定不能", why=why_not, c1=None, c2=None, c4=None)
    if not m or not m["blocked"]:
        return dict(verdict="判定不能", why="止めた社が0＝この母集団でこの規則は作動しない",
                    c1=None, c2=None, c4=None)
    b, p = m["blocked"], m["passed"]
    c1 = bool(m["concentration"] is not None and m["concentration"] >= CONC_MIN
              and b["n_impair"] >= MIN_NUM)
    c2 = bool(p is not None and b["med"] <= p["med"])
    c4 = bool(m["stop_rate"] is not None and m["stop_rate"] <= MAX_STOP)
    ok = c1 and c2 and c4
    fail = []
    if not c1:
        fail.append(f"c1: 濃縮{m['concentration']}倍(線{CONC_MIN}) 分子{b['n_impair']}社(線{MIN_NUM})")
    if not c2:
        fail.append(f"c2: 止めた中央値{b['med']:+.4f} > 通過{p['med']:+.4f}＝勝者を巻き込む")
    if not c4:
        fail.append(f"c4: 止率{m['stop_rate']:.1%}(線{MAX_STOP:.0%})＝遮断器でなく間引き")
    # ★不合格の「型」を分ける。効果量で落ちたのか検出力で落ちたのかで、
    #   この不合格が何を測れたのかがまったく違う（v1が三度踏んだ到達可能性の話の続き）。
    kind = None
    if not ok:
        if b["n_impair"] < MIN_NUM:
            kind = "検出力（止めた群の毀損が分子5に届かない＝規則の性能を測れていない）"
        elif not c1:
            kind = "効果量（分子は足りているのに濃縮が線に届かない＝規則の性能を測れている）"
        elif not c4:
            kind = "止率（遮断器ではなく間引き）"
        elif not c2:
            kind = "勝者の巻き込み"
    return dict(verdict="合格" if ok else "不合格", c1=c1, c2=c2, c4=c4,
                fail_kind=kind, why="; ".join(fail) if fail else None)


# ── ① 再現（2018年・retro_breaker_test と同じ母集団・同じ式） ─────────────
def replicate(rows18):
    """★母集団は out/retro_er_test.json の581社。base の 2018/all(956) ではない。
    retro_breaker_test は er_test を母集団に取るので、956で測ると別の数字になる
    （その差自体も測って出す＝『基準の違う二つ』を自分で作らない）。"""
    er = load("retro_er_test.json")["rows"]
    keep = {r["t"] for r in er}
    sub = [r for r in rows18 if r["ticker"] in keep]

    # retro_breaker_test.stat() と同じ定義（real=%・IMPAIR=-15.0）を小数で再現
    m = measure(sub, "and", strict=False)
    got = dict(n_pool=len(sub),
               base_n=m["base"]["n"], base_med_pct=round(m["base"]["med"] * 100, 1),
               base_impair=m["base"]["impair"],
               blocked_n=m["blocked"]["n"], blocked_med_pct=round(m["blocked"]["med"] * 100, 1),
               blocked_impair=m["blocked"]["impair"], blocked_loss=m["blocked"]["loss"],
               passed_n=m["passed"]["n"], passed_med_pct=round(m["passed"]["med"] * 100, 1),
               passed_impair=m["passed"]["impair"],
               concentration=m["concentration"])

    ref = None
    p = os.path.join(OUT, "retro_breaker_test.json")
    if os.path.exists(p):
        d = load("retro_breaker_test.json")
        for r in d["rules"]:
            if r["rule"].startswith("売上縮小"):
                ref = dict(base_n=d["base"]["n"], base_med_pct=d["base"]["med"],
                           base_impair=d["base"]["impair"],
                           blocked_n=r["blocked"]["n"], blocked_med_pct=r["blocked"]["med"],
                           blocked_impair=r["blocked"]["impair"], blocked_loss=r["blocked"]["loss"],
                           passed_n=r["passed"]["n"], passed_med_pct=r["passed"]["med"],
                           passed_impair=r["passed"]["impair"])
    # ★突合せは**相手の精度に揃えてから**行う。retro_breaker_test は率を round(...,3)、
    #   中央値を round(...,1) で保存しているので、こちらの4桁のまま比べると
    #   0.1429 vs 0.143 が「不一致」に化ける（初回の実行で実際にそう出た＝実装の欠陥であって
    #   データの食い違いではない）。丸めの桁は相手の保存値から機械で決める。
    def _dec(x):
        s0 = repr(float(x))
        return len(s0.split(".")[1]) if "." in s0 else 0

    diffs, ok = {}, None
    if ref:
        ok = True
        for k, v in ref.items():
            g = got.get(k)
            same = (round(g, _dec(v)) == v) if isinstance(v, float) else (g == v)
            diffs[k] = dict(ref=v, got=g, same=same)
            if not same:
                ok = False
    return dict(pool_src="out/retro_er_test.json（581社）", n_pool=len(sub),
                got=got, ref=ref, fields=diffs, reproduced=ok,
                note=("retro_breaker_test.py:118 の式 `(cagr5 or 0)<0 ∧ (opmD5 or 0)<0` を"
                      "そのまま当て、%と小数の単位差だけ揃えて比べた"))


def main():
    B = load_base()
    rows = B["rows"]
    reach = B["reachability"]
    meta = B["vintage_meta"]
    vintages = sorted({r["vintage"] for r in rows})

    print("■ H4『事業の収縮』(cagr5<0 ∧ opmD5<0) を8ビンテージで再現するか")
    print(f"  線（事前登録・H2と同じ）: 濃縮≥{CONC_MIN}倍 ∧ 分子≥{MIN_NUM}社 ∧ "
          f"止めた中央値≤通過中央値 ∧ 止率≤{MAX_STOP:.0%}")
    print(f"  恒久毀損 = 前方年率 ≤ {IMPAIR:+.0%} ／ 当たり = ≥ {HURDLE:+.0%}\n")

    # ── ① 再現 ──
    rows18 = [r for r in rows if r["vintage"] == 2018]
    rep = replicate(rows18)
    print("── ① 2018年の再現（母集団 = retro_er_test.json の581社） ──")
    if rep["ref"]:
        for k, v in rep["fields"].items():
            print(f"  {'✓' if v['same'] else '✗'} {k:<18} 既存 {str(v['ref']):>8}   今回 {str(v['got']):>8}")
        print(f"  → 再現: {'**できた**' if rep['reproduced'] else '**できていない——自分の実装を疑う**'}"
              f"（濃縮 {rep['got']['concentration']}倍）")
    else:
        print("  ⚠ out/retro_breaker_test.json が無い＝突合せ不能")

    # 同じ2018年でも母集団を956にすると数字が変わることを見せる
    m18all = measure([r for r in rows18], "and", False)
    print(f"  ⚠ 同じ式でも母集団を base の 2018/all(956社) にすると "
          f"止めた {m18all['blocked']['n']}社（止率{m18all['stop_rate']:.1%}）"
          f"・恒久毀損 {m18all['blocked']['impair']:.1%}（ベース{m18all['base']['impair']:.1%}"
          f"・濃縮{m18all['concentration']}倍）")
    print("     ＝ retro_breaker_test の581社は PER/shy/g が組めた社への絞り込みで、"
          "赤字社などが落ちている。**同じ数字を名乗らない**")

    # ── ② 8ビンテージ × 2プール × 3規則 ──
    cells = {}
    for y in vintages:
        vr = [r for r in rows if r["vintage"] == y]
        for pool_key, sel in (("all", lambda r: True), ("qual", lambda r: r.get("qual") is True)):
            pool = [r for r in vr if sel(r)]
            rk = reach.get(f"{y}/{pool_key}", {})
            for rule in RULES:
                for strict in (False, True):
                    m = measure(pool, rule, strict)
                    if m is None:
                        continue
                    j = judge(m, rk.get("reachable", False), rk.get("why_not"))
                    cells[f"{y}/{pool_key}/{rule}/{'strict' if strict else 'main'}"] = dict(
                        vintage=y, pool=pool_key,
                        na_reading="strict(欠測を両群から外す)" if strict else "main(欠測は止めない側)",
                        reachable=rk.get("reachable"), reach_why=rk.get("why_not"),
                        years=meta[str(y)]["years_median"], **m, judge=j)

    def C(y, p, rule="and", na="main"):
        return cells[f"{y}/{p}/{rule}/{na}"]

    for pool_key, label in (("all", "全社"), ("qual", "質実証（opm≥10% ∧ 5年FCF全年黒字）")):
        print(f"\n── ② 事業の収縮 — プール『{label}』（主判定・欠測は止めない側） ──")
        print("  年   窓   n   止めた(止率)  止/通の中央値      毀損 止/ベース  分子 濃縮  判定")
        for y in vintages:
            c = C(y, pool_key)
            b, ba, p = c["blocked"], c["base"], c["passed"]
            if not b:
                print(f"  {y}  {c['years']:>5}  {c['n_used']:>4}  作動せず")
                continue
            print(f"  {y}  {c['years']:>5}  {c['n_used']:>4}  "
                  f"{b['n']:>3}({c['stop_rate']:>5.1%})  "
                  f"{b['med']:>+7.1%}/{p['med']:>+6.1%}  "
                  f"{b['impair']:>5.1%}/{ba['impair']:>5.1%}  "
                  f"{b['n_impair']:>3}  {str(c['concentration']):>5}  "
                  f"{c['judge']['verdict']}"
                  + (f"  [{c['judge']['why']}]" if c["judge"]["why"] else ""))

    # ── ③ 片方だけ vs 積（c5 の代わりの増分検査） ──
    print("\n── ③ 積にして初めて効くのか（片方だけと較べる・主判定プール=全社） ──")
    print("  年    規則              止めた(止率)   毀損   濃縮   中央値(止/通)")
    for y in vintages:
        for rule, nm in (("cagr_only", "売上縮小のみ"), ("opm_only", "利益率低下のみ"), ("and", "★積(事業の収縮)")):
            c = C(y, "all", rule)
            b, p = c["blocked"], c["passed"]
            if not b:
                continue
            print(f"  {y}  {nm:<16} {b['n']:>3}({c['stop_rate']:>5.1%})  "
                  f"{b['impair']:>5.1%}  {str(c['concentration']):>5}  "
                  f"{b['med']:>+7.1%}/{p['med']:>+6.1%}")

    # ── ③b 欠測の扱いの感度（2013 は opmD5 の被覆が48%＝ここが効く） ──
    print("\n── ③b 欠測の扱いの感度（主判定=止めない側 vs 厳格=両群から外す・全社プール） ──")
    print("  年   被覆        主: 止めた(止率) 濃縮      厳格: 止めた(止率) 濃縮")
    sens = {}
    for y in vintages:
        a, b_ = C(y, "all", "and", "main"), C(y, "all", "and", "strict")
        cov = 1 - b_["n_na"] / b_["n_pool"]
        sens[y] = dict(coverage=round(cov, 4),
                       main=dict(n=a["blocked"]["n"], stop=a["stop_rate"], conc=a["concentration"]),
                       strict=dict(n=b_["blocked"]["n"], stop=b_["stop_rate"], conc=b_["concentration"],
                                   n_na=b_["n_na"], verdict=b_["judge"]["verdict"]))
        print(f"  {y}  {cov:>5.1%}      {a['blocked']['n']:>4}({a['stop_rate']:>5.1%}) {str(a['concentration']):>6}"
              f"        {b_['blocked']['n']:>4}({b_['stop_rate']:>5.1%}) {str(b_['concentration']):>6}"
              f"  [{b_['judge']['verdict']}]")

    # ★欠測社が誰かを実測する——2013 の符号反転が「規則の反証」なのか
    #   「欠測の扱いの産物」なのかは、欠測社の姿を測らないと言えない
    na_who = {}
    for y in vintages:
        vr = [r for r in rows if r["vintage"] == y]
        has = [r for r in vr if r.get("opmD5") is not None]
        nav = [r for r in vr if r.get("opmD5") is None]
        if not nav or not has:
            continue
        def _d(g):
            rev = [r["rev"] for r in g if r.get("rev")]
            return dict(n=len(g), rev_med=round(st.median(rev)) if rev else None,
                        impair=round(sum(1 for r in g if r["tr_cagr"] <= IMPAIR) / len(g), 4),
                        med=round(st.median([r["tr_cagr"] for r in g]), 4))
        na_who[y] = dict(has=_d(has), na=_d(nav))
    y0 = 2013
    if y0 in na_who:
        h, n_ = na_who[y0]["has"], na_who[y0]["na"]
        print(f"\n  ★{y0} の符号反転(濃縮0.47)の正体を実測: opmD5あり {h['n']}社(売上中央 {h['rev_med']/1e6:,.0f}M・"
              f"毀損{h['impair']:.1%}) vs **欠測 {n_['n']}社(売上中央 {n_['rev_med']/1e6:,.0f}M・毀損{n_['impair']:.1%})**")
        print(f"    ＝主判定では欠測の小型が丸ごと通過群へ入りベース率を押し上げる。"
              f"厳格読みだと {C(y0,'all','and','strict')['concentration']}倍で他年と同じ向きへ戻る")

    # ── ③c まとめ（何が信号を運んでいるか） ──
    summ = {}
    for rule in ("and", "cagr_only", "opm_only"):
        cs = [C(y, "all", rule)["concentration"] for y in vintages]
        cs = [c for c in cs if c is not None]
        summ[rule] = dict(vals=cs, median=round(st.median(cs), 3),
                          lo=min(cs), hi=max(cs),
                          n_above_1=sum(1 for c in cs if c > 1.0),
                          n_above_line=sum(1 for c in cs if c >= CONC_MIN))
    and_c = {y: C(y, "all", "and")["concentration"] for y in vintages}
    rank2018 = sorted(and_c.values(), reverse=True).index(and_c[2018]) + 1
    print("\n── ③c 何が信号を運んでいるか（全社プール・8ビンテージの濃縮） ──")
    for rule, nm in (("cagr_only", "売上縮小のみ"), ("opm_only", "利益率低下のみ"), ("and", "★積(事業の収縮)")):
        v = summ[rule]
        print(f"  {nm:<16} 中央 {v['median']:>5.2f}倍  範囲 {v['lo']:>5.2f}〜{v['hi']:>5.2f}  "
              f"1.0超 {v['n_above_1']}/8  **線(2.0)到達 {v['n_above_line']}/8**")
    print(f"  ★積の濃縮で 2018 は 8ビンテージ中 **{rank2018}位**"
          f"（規則が見つかった当のビンテージが最良なら、それは過剰適合の署名）")

    # ── ④ 合否 ──
    verdicts = {}
    for pool_key in ("all", "qual"):
        det = []
        for y in vintages:
            c = C(y, pool_key)
            det.append(dict(vintage=y, verdict=c["judge"]["verdict"],
                            c1=c["judge"]["c1"], c2=c["judge"]["c2"], c4=c["judge"]["c4"],
                            concentration=c["concentration"],
                            n_impair_blocked=(c["blocked"] or {}).get("n_impair"),
                            stop_rate=c["stop_rate"], why=c["judge"]["why"]))
        judged = [d for d in det if d["verdict"] != "判定不能"]
        passed = [d for d in judged if d["verdict"] == "合格"]
        ok = bool(judged) and len(passed) == len(judged)
        kinds = {}
        for d0 in judged:
            c = C(d0["vintage"], pool_key)["judge"]
            k = (c.get("fail_kind") or "合格")
            kinds[k] = kinds.get(k, 0) + 1
        verdicts[pool_key] = dict(fail_kinds=kinds,
            verdict=("合格" if ok else ("判定不能" if not judged else "不合格")),
            n_judged=len(judged), n_pass=len(passed),
            n_undecidable=len(det) - len(judged), detail=det)

    overall = "合格" if any(v["verdict"] == "合格" for v in verdicts.values()) else (
        "判定不能" if all(v["verdict"] == "判定不能" for v in verdicts.values()) else "不合格")

    print("\n── ④ 合否（線は走らせる前に固定・結果を見て緩めていない） ──")
    for pool_key, label in (("all", "全社"), ("qual", "質実証")):
        v = verdicts[pool_key]
        print(f"  プール『{label}』: **{v['verdict']}**"
              f"（判定可能 {v['n_judged']}ビンテージ中 {v['n_pass']}で線が成立"
              f"・判定不能 {v['n_undecidable']}）")
        for k, n in sorted(v["fail_kinds"].items(), key=lambda x: -x[1]):
            print(f"      不合格の型: {k} … {n}ビンテージ")
    print(f"\n  ★H4 の合否: **{overall}**")

    # ── ⑤ 自己検算——measure() を使わず素で組み直して一致するか ──
    sc = []
    for y in vintages:
        for pool_key, sel in (("all", lambda r: True), ("qual", lambda r: r.get("qual") is True)):
            P = [r for r in rows if r["vintage"] == y and sel(r)]
            bk = [r for r in P if (r.get("cagr5") or 0) < 0 and (r.get("opmD5") or 0) < 0]
            ps = [r for r in P if not ((r.get("cagr5") or 0) < 0 and (r.get("opmD5") or 0) < 0)]
            c = C(y, pool_key)
            ok = (len(bk) == c["blocked"]["n"] and len(ps) == c["passed"]["n"]
                  and sum(1 for r in bk if r["tr_cagr"] <= IMPAIR) == c["blocked"]["n_impair"]
                  and round(st.median([r["tr_cagr"] for r in bk]), 4) == c["blocked"]["med"])
            sc.append(dict(cell=f"{y}/{pool_key}", ok=ok))
    n_bad = sum(1 for x in sc if not x["ok"])
    print(f"\n  自己検算: 16セルを measure() を使わず素で組み直して突合せ → 食い違い {n_bad}件")

    o = dict(generated="2026-08-18", tool="night/opmtrend_h4.py",
             prereg="out/opm_trend_prereg.json / H4_shrink_gate",
             base="out/opmtrend_base.json",
             rule="cagr5<0 ∧ opmD5<0（自由変数ゼロ＝c6は構造上成立）",
             line=dict(concentration_min=CONC_MIN, numerator_min=MIN_NUM,
                       median_not_worse=True, stop_rate_max=MAX_STOP,
                       aggregation="判定可能な全ビンテージで成立＝プール別合格。"
                                   "all/qual のどちらか一方でも成立すれば H4 合格",
                       fixed_before_running=True),
             c5_note="c5(増分)は H4 では定義上判定不能（この規則そのものが既存の第四の関門）。"
                     "代替として片方だけとの比較を③に置いた（事前登録に無い適応と明記）",
             replication=rep,
             na_sensitivity=sens, na_composition=na_who,
             selfcheck=dict(cells=sc, mismatches=n_bad),
             concentration_summary=summ,
             rank_of_2018_in_and=rank2018,
             replication_pool_warning=dict(
                 msg="retro_breaker_test の母集団は er_test の581社。base の 2018/all は956社",
                 all956=dict(blocked=m18all["blocked"]["n"], stop_rate=m18all["stop_rate"],
                             impair=m18all["blocked"]["impair"],
                             base_impair=m18all["base"]["impair"],
                             concentration=m18all["concentration"])),
             verdict=dict(overall=overall, by_pool=verdicts),
             cells=cells,
             base_warnings=B.get("warnings"),
             lesson_reachability=(
                 "★土台の reachability（神の遮断器でも分子5に届くか）は**必要条件であって十分条件ではない**。"
                 "質実証プールは8ビンテージ中6つが reachable=true だったのに、実際の規則が止めた群の"
                 "毀損は 0〜3社で一度も分子5に届かなかった＝**この不合格は規則の性能を測れていない**。"
                 "一方 全社プールは 2016〜2022 の7ビンテージで分子11〜37社あり、"
                 "**濃縮が線に届かないという効果量の不合格＝規則の性能を測れている**。"
                 "次に事前登録を書くときは『神の遮断器』だけでなく"
                 "『**その規則が現に止める群**で分子が足りるか』も結果の前に数えること"),
             limits=[
                 "8ビンテージは同じ956社で窓が重なる＝真の out-of-sample はゼロ",
                 "窓の長さが 4.08〜13.09年と違う。ベース率をビンテージ間で直接比べない",
                 "2013 は opmD5 の被覆が48%・欠測が小型に偏る（土台の警告）。"
                 "主判定(欠測は止めない側)だと通過群が別の母集団を含む",
                 "2019〜2022 のベンチマークは SPY ではない（EW）。ただし H4 は"
                 "ベンチマークを一度も使わない（絶対の年率で裁く）ので合否には効かない",
                 "生存バイアスは既記録のまま（左尾は 4.20〜19.16% の幅・2026-09-23 退場日の是正後／是正前は 2.00〜25.68%）",
             ])
    if WRITE:
        p = os.path.join(OUT, "opmtrend_h4.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
