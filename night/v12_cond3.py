#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/v12_cond3.py — V12_SPEC 条件3「物差しの交換」を**層0（土俵）**で測り直す（2026-08-13）

■ なぜ測り直すか
  v11 の在庫（out/v11_backtest.json の C2_financial）は母集団を **層0∧層1** に取っており、
  そこには**恒久毀損が一件も無い**（両群とも n_destroy=0）ので濃縮が定義できず **判定不能**だった。
  V12_SPEC はこれを見越して条件3の母集団を **層0** と指定してある（事前登録・commit 9fe80eb）。

■ ⚠ この器は判定を作らない
  v11_backtest.py のデータ読み込み・層0の定義・統計をそのまま import する（二重実装を作らない）。
  変えるのは**母集団を層0にする**ことだけ。

使い方: python3 night/v12_cond3.py [--json]
"""
import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "night"))
import v11_backtest as B          # noqa: E402  層0の定義も統計もここが正本

OUT = os.path.join(BASE, "out")


def conc(stopped, passed, key="p_destroy"):
    """濃縮＝止めた群の率 ÷ 通した群の率。**分母か分子が0なら None（判定不能）**を返す。
    ⚠ 0/0 も x/0 も『効いた』と読まない——測れなかったことを測れたことにしない。"""
    a, b = stopped.get(key), passed.get(key)
    if not a or not b:
        return None
    return round(a / b, 2)


def main():
    rows = B.load()
    nde = {}
    for y in (2016, 2017, 2018):
        p = os.path.join(OUT, f"retro_features_{y}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        for r in (d.get("rows") if isinstance(d, dict) else d) or []:
            v = r.get("nde18") if r.get("nde18") is not None else r.get("nde")
            if v is not None:
                nde.setdefault(r.get("ticker"), v)

    out = {"tool": "v12_cond3", "spec": "V12_SPEC 条件3（事前登録 commit 9fe80eb）",
           "population": "層0（土俵）——v11 は層0∧層1 で測って判定不能だった", "vintages": {}}

    for y in (2016, 2017, 2018):
        g = [x for x in rows if x["vintage"] == y and B.L0(x)]
        both = [x for x in g if x["ticker"] in nde and x.get("f2_intcov") is not None]
        rec = {"n_層0": len(g), "n_両方採れる": len(both), "欠測で落ちた": len(g) - len(both)}
        if both:
            for label, pred in (("nde>4", lambda x: nde[x["ticker"]] is not None and nde[x["ticker"]] > B.NDE_KILL),
                                ("intcov<3", lambda x: x["f2_intcov"] < B.INTCOV_LINE)):
                st = [x for x in both if pred(x)]
                ps = [x for x in both if not pred(x)]
                s_, p_ = B.stats(st), B.stats(ps)
                rec[label] = {"止めた": s_, "通した": p_,
                              "濃縮(止/通)": conc(s_, p_),
                              "止めた側の中央値は低いか": (s_.get("median") is not None
                                                and p_.get("median") is not None
                                                and s_["median"] < p_["median"])}
        out["vintages"][str(y)] = rec

    # プール（重複あり＝独立標本ではないことを明記して併記）
    g = [x for x in rows if B.L0(x)]
    both = [x for x in g if x["ticker"] in nde and x.get("f2_intcov") is not None]
    pooled = {"n_層0": len(g), "n_両方採れる": len(both),
              "note": "⚠3ビンテージは同じ956ティッカーで重複＝独立標本ではない"}
    for label, pred in (("nde>4", lambda x: nde[x["ticker"]] is not None and nde[x["ticker"]] > B.NDE_KILL),
                        ("intcov<3", lambda x: x["f2_intcov"] < B.INTCOV_LINE)):
        st = [x for x in both if pred(x)]
        ps = [x for x in both if not pred(x)]
        s_, p_ = B.stats(st), B.stats(ps)
        pooled[label] = {"止めた": s_, "通した": p_, "濃縮(止/通)": conc(s_, p_),
                         "止めた側の中央値は低いか": (s_.get("median") is not None
                                          and p_.get("median") is not None
                                          and s_["median"] < p_["median"])}
    out["pooled"] = pooled

    # 判定（事前登録どおり）
    a = pooled.get("intcov<3", {}).get("濃縮(止/通)")
    b = pooled.get("nde>4", {}).get("濃縮(止/通)")
    if a is None or b is None:
        out["verdict"] = "判定不能——どちらかの濃縮が定義できない（V12_SPEC 条件3の但し書きどおり合格にも不合格にもしない）"
    else:
        out["verdict"] = ("合格（intcov のほうが濃縮が大きい）" if a > b
                          else "不合格（nde のほうが濃縮が大きいか同じ）")

    print("■ V12_SPEC 条件3 — 物差しの交換（母集団＝層0）")
    for y, rec in out["vintages"].items():
        print(f"\n  {y}: 層0 {rec['n_層0']}社 / 両方採れる {rec['n_両方採れる']}社")
        for label in ("nde>4", "intcov<3"):
            if label not in rec:
                continue
            s_, p_ = rec[label]["止めた"], rec[label]["通した"]
            print(f"     {label:<10} 止めた n={s_['n']:<3} 毀損{s_['p_destroy']:.3f}({s_['n_destroy']})"
                  f" 中央{s_['median']}  ／ 通した n={p_['n']:<3} 毀損{p_['p_destroy']:.3f}({p_['n_destroy']})"
                  f" 中央{p_['median']}  濃縮={rec[label]['濃縮(止/通)']}")
    print(f"\n  ── プール（⚠重複あり）──")
    for label in ("nde>4", "intcov<3"):
        if label not in pooled:
            continue
        s_, p_ = pooled[label]["止めた"], pooled[label]["通した"]
        print(f"     {label:<10} 止めた n={s_['n']:<3} 毀損{s_['p_destroy']:.3f}({s_['n_destroy']})"
              f" 中央{s_['median']}  ／ 通した n={p_['n']:<3} 毀損{p_['p_destroy']:.3f}({p_['n_destroy']})"
              f" 中央{p_['median']}  濃縮={pooled[label]['濃縮(止/通)']}")
    print(f"\n  ⇒ **{out['verdict']}**")

    if "--json" in sys.argv:
        json.dump(out, open(os.path.join(OUT, "v12_cond3.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n→ out/v12_cond3.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
