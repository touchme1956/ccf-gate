#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_price_tail.py — **「歴史的に高すぎる株価はリターンを生まない」は本当か**（2026-08-07新設）

なぜ要るか（ユーザーの問い「高すぎる株価は押し目待ちにしたほうがいいのでは？」）:
  v9.9.98 で門から E[r] を外したとき、CLAUDE.md が
  「1999年型（法外な倍率）への保険は倍率の重力(mult)が担う」と書いていた**その保険も一緒に外れた**。
  実際、今日の投下可には **HWM PER 77.3（fairPERの4.44倍）/ CW 56.5（3.53倍）** が入っている——
  どちらも**今日 価格の関門を外したから入った社**。指摘は具体的で、測る価値がある。

これまでの検定との違い（同じ失敗を繰り返さないために）:
  ・retro_er_test は E[r] を**五分位で**見た＝選別器の物差し
  ・retro_breaker_test の PER>40 は **24%を止める粗すぎる線**で「ただの間引き」と出た
  → この道具は **極端の裾だけ**を切り出し、**止めた側**を
     中央値／恒久毀損率 P(年率≤−15%)／15%+の割合 の3つで裁く。
     さらに **その社自身の fairPER（=clamp(8+g,16,30)・門X本体と同式）の何倍か**という
     成長で正規化した尺度でも測る——生PERは成長率の違いを吸収できないため。

  そして**3つのビンテージで頑健性を見る**（2018 / 2013 / 2015）。
  2018-2026 は高倍率成長に極端に有利な期間なので、単独では結論にできない。

使い方: python3 night/retro_price_tail.py [--write]
"""
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
WRITE = "--write" in sys.argv[1:]
IMPAIR = -15.0


def rows_of(p):
    p = os.path.join(OUT, p) if not p.startswith("/") else p
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding="utf-8"))
    for k in ("rows", "items"):
        if isinstance(d, dict) and isinstance(d.get(k), list):
            return d[k]
    return d if isinstance(d, list) else []


def st(g):
    if not g:
        return None
    return dict(n=len(g), med=round(statistics.median(x["real"] for x in g), 1),
                impair=round(sum(1 for x in g if x["real"] <= IMPAIR) / len(g), 3),
                win15=round(sum(1 for x in g if x["real"] >= 15) / len(g), 3))


def cut(pool, base, key, ths, label):
    out = []
    print(f"  ── {label} で止めたら ──")
    for th in ths:
        blk = [r for r in pool if key(r) > th]
        pas = [r for r in pool if key(r) <= th]
        if len(blk) < 8:
            print(f"     >{th:<5} 止めた {len(blk):>3}社  ——標本が薄すぎる（結論にしない）")
            continue
        b, p = st(blk), st(pas)
        verdict = ("◎中央値も低い＝両方向とも正しい" if b["med"] < p["med"] - 0.5 and b["impair"] > base["impair"] + 0.01
                   else ("△恒久毀損だけ高い＝裾の保険にはなるが勝者も掴む" if b["impair"] > base["impair"] + 0.01
                         else "×効かない"))
        print(f"     >{th:<5} 止めた {b['n']:>3}社（{b['n']/base['n']:.0%}） "
              f"中央値 {b['med']:>5.1f}%（通過 {p['med']:>5.1f}%） "
              f"恒久毀損 {b['impair']:>5.1%}（差 {b['impair']-base['impair']:+.1%}・実数{round(b['impair']*b['n'])}社） "
              f"15%+ {b['win15']:.0%}（通過 {p['win15']:.0%}）  {verdict}")
        out.append(dict(th=th, blocked=b, passed=p, verdict=verdict))
    return out


def main():
    res = {}
    # ── 2018年ビンテージ（fairPER倍率まで測れる唯一の在庫）────────────────────
    rows = rows_of("retro_er_test.json")
    fea = {r["ticker"]: r for r in rows_of("retro_features2_2018.json")}
    for r in rows:
        fair = max(16.0, min(30.0, 8.0 + r["g"]))
        r["ratio"] = r["per"] / fair
    qp = [r for r in rows
          if (fea.get(r["t"], {}).get("opm") or 0) >= 0.10
          and (fea.get(r["t"], {}).get("fcfpos5") or 0) >= 5]

    print("■ 「高すぎる株価はリターンを生まない」を極端の裾で検定する")
    print("  遮断器と同じ物差し——**止めた側**を 中央値／恒久毀損／15%+の3つで見る\n")
    for nm, pool in (("2018年 全母集団", rows), ("2018年 質実証プール＝門が当てる場所", qp)):
        b = st(pool)
        print(f"● {nm}（n={b['n']}）ベース 中央値{b['med']}% / 恒久毀損{b['impair']:.1%} / 15%+{b['win15']:.0%}")
        res[nm + "/PER"] = cut(pool, b, lambda r: r["per"], (40, 50, 60, 70, 80, 90, 100, 110, 120), "生PER")
        res[nm + "/ratio"] = cut(pool, b, lambda r: r["ratio"], (2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0),
                                 "現PER÷fairPER（成長で正規化）")
        print()

    # ── 2013 / 2015 ビンテージ（頑健性）──────────────────────────────────
    for yr, pf, rf in (("2013", "retro_per_2013_all.json", "retro_returns_2013_all.json"),
                       ("2015", "retro_per_2015.json", "retro_returns_2015.json")):
        per = {(r.get("ticker") or r.get("t")): r for r in rows_of(pf)}
        ret = {(r.get("ticker") or r.get("t")): r for r in rows_of(rf)}
        g = []
        for t, p in per.items():
            rr, pv = ret.get(t), p.get("per")
            if not rr or pv is None or rr.get("tr_cagr") is None or not (2 <= pv <= 200):
                continue
            g.append(dict(t=t, per=pv, real=rr["tr_cagr"] * 100))
        if len(g) < 50:
            print(f"● {yr}年ビンテージ: 突合 {len(g)}社——薄いので割愛\n")
            continue
        b = st(g)
        print(f"● {yr}年ビンテージ（n={b['n']}）ベース 中央値{b['med']}% / 恒久毀損{b['impair']:.1%} / 15%+{b['win15']:.0%}")
        res[yr] = cut(g, b, lambda r: r["per"], (40, 50, 60, 70, 80, 90, 100, 120), "生PER")
        print()

    print("■ 読み方（2026-08-07の実測）")
    print("  ・**全母集団では高倍率は悪い**（3倍超の中央値 6.2% vs 通過 7.4%・恒久毀損 6.5% vs 4.5%）")
    print("    ＝『歴史的に高すぎる株価はリターンを生まない』は**市場全体では正しい**")
    print("  ・**だが質・堀を通った社の中では逆転する**（3倍超の中央値 10.1% vs 7.1%・15%+ 27% vs 18%）。")
    print("    2013年(PER>50 で 9.1% vs 8.3%)・2015年(PER>40 で 9.5% vs 7.5%)でも高い側が同等以上")
    print("  ・**一貫して悪いのは恒久毀損だけ**（4つの切り方すべてで上昇）。ただし質実証プールでの")
    print("    分子は1社＝**裾の保険としては本物だが、規約にするには薄い**")
    print("  ・門の記録の非対称も効く——『3割高づかみの20年コスト年−1.3% vs 買い逃し年−19%』。")
    print("    押し目待ちは**買い逃すリスク**を負う側の選択で、質の中では歴史がそれを支持しない")
    print("\n■ 極端の裾まで伸ばした結果（2026-08-09・ユーザーの問い「これ以上だとダメな水準はあったのか」）")
    print("  ・**『ここから上は一貫してダメ』と言える線は見つからなかった。**")
    print("  ・唯一それらしく見えるのは **2018年 全母集団 PER>90**（中央値 3.2% vs 通過 7.5%・")
    print("    恒久毀損 12.5%＝ベースの2.8倍）と **fair比>5.5**（恒久毀損 18.8%＝4.2倍）。")
    print("    だが**どちらも分子は3社**で、**2013年では再現しない**（>90 で恒久毀損 4.5%、")
    print("    **>100 と >120 は 0%**・中央値はむしろ通過群より高い 9.1/9.2%）。2015年も >60 以上は全て0%。")
    print("  ・**質実証プール（門が当てる場所）では最後まで逆転したまま**——>80 で中央値 10.1%、")
    print("    >100 で 11.3%、>120 で 12.1%（いずれも通過群 7.2%）。上がるのは恒久毀損だけで**分子は常に1社**")
    print("    （MLCO −16.7%）。同じ帯の生存側は WST 8.0x→+15.7% / SNPS 6.1x→+20.5% / ISRG 5.5x→+10.1% /")
    print("    IDXX 4.8x→+11.4% / ECL 4.9x→+10.2% ＝**門が狙う型がそのまま高倍率帯に居る**")
    print("  ・**標本の天井に注意**——PERは採取時の帯検問(2-200)で切ってあるので")
    print("    （retro_per_asof.py:150・分割/単位の桁事故対策）、**PER 200超はそもそも母集団に居ない**。")
    print("    実測の最大は 193（ALB→+4.5%）。**『PER 300はどうか』にこの在庫は答えられない**")

    if WRITE:
        p = os.path.join(OUT, "retro_price_tail.json")
        json.dump({"generated": "2026-08-07", "impair_line": IMPAIR, "results": res,
                   "note": "全母集団では高倍率は悪いが、質実証プール内では中央値が逆転。"
                           "一貫して悪いのは恒久毀損だけで分子は1社＝規約にするには薄い"},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {p} を保存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
