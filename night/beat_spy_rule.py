#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/beat_spy_rule.py — **「S&P500に負けている社を落とす」という規則は働くか**
（2026-08-18新設・ユーザーの問い「VISA IDXX CWなどはS&P500のリターンにかなわないよね？
ならばそこを落とす基準もいるのでは？」）

【この器が答える一つの問い】
  **直近の窓でSPYに負けた社は、次の窓でもSPYに負けるのか。**
  負けるなら「落とす基準」は作れる。負けないなら、その基準は過去のノイズで未来を切ることになる。

【なぜ測るのか——この台帳は既に近い問いを潰している】
  ・`retro_persistence`: 重ならない4窓の勝敗分布は**独立抽選と一致**（比0.99〜1.05）／ICC 0.054／
    決定的に **他の3窓の実現リターンそのもので選んでも当てられない（×0.84〜1.12）**
  ・`retro_midway`: 一方で**負け側だけは信号がある**——前半マイナスの社は後半0.4%/年・49%がマイナス
  ⇒ 「マイナス」と「SPY未満」は**別の線**。前者に信号があっても後者にあるとは限らない。だから測る。

【設計（結果を見る前に決めた線）】
  ・窓: 2013-07 起点の**重ならない4窓**（各39ヶ月）。すべて月次パネルから作る＝追加取得は SPY だけ
  ・判定: 連続する窓 W_n → W_{n+1} で
      lift = P(次もSPY超 | 今回SPY超) − P(次もSPY超 | 今回SPY未満)
  ・**採用の線は既存のものを流用する**（新しい定数を作らない）:
      lift ≥ 0.15 ∧ **3つの遷移すべてで符号が同じ**
  ・母集団は2つ出す: 全社 ／ **質実証**（門が実際に買う帯の相当物＝この台帳の既存の定義）
  ・おまけ: 規則を実際に回したときの**ポートフォリオの終価**（落とした群と持ち続けた群）

【限界（先に書く）】
  ・パネルは**今日ティッカーが引ける社**＝生存バイアス（既記録・左尾は 2.00〜25.68% の幅）
  ・4窓とも同じ13年の中にあり、独立標本ではない／窓の長さ(39ヶ月)は3つの遷移を作るための機械的な分割
  ・SPY は配当込み(adjclose)。個別も同じ adjclose なので基準は揃っている

使い方: python3 night/beat_spy_rule.py [--json]
出力  : out/beat_spy_rule.json
"""
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))
# ★窓の作り方は retro_persistence の実装をそのまま使う（書き写さない・v9.9.65）
from retro_persistence import panel, cagr, ymk        # noqa: E402

WIN_M = 39          # 39ヶ月×4 = 13年。3つの遷移が作れる最小の分割
LIFT = 0.15         # 既存の採用線（新しい定数を作らない）
HD = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}


def spy_monthly():
    """SPY の月次 adjclose（1回だけ取って out/_spy_monthly.json へ）"""
    p = os.path.join(OUT, "_spy_monthly.json")
    if os.path.exists(p):
        return {int(k): v for k, v in json.load(open(p)).items()}
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/SPY"
           "?range=20y&interval=1mo&events=div%2Csplit")
    j = json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=HD), timeout=60).read())
    r = j["chart"]["result"][0]
    adj = ((r.get("indicators", {}).get("adjclose") or [{}])[0]).get("adjclose") or []
    m = {}
    for ts, v in zip(r["timestamp"], adj):
        if v:
            m[ymk(ts)] = float(v)
    json.dump({str(k): v for k, v in m.items()}, open(p, "w"))
    return m


def main():
    P = panel()
    S = spy_monthly()
    k0 = min(min(v) for v in P.values() if v)
    wins = [(k0 + i * WIN_M, k0 + (i + 1) * WIN_M) for i in range(4)]
    out = {"generated": "2026-08-18", "win_months": WIN_M, "lift_line": LIFT,
           "note": "「SPY未満の社を落とす」規則が働くかの検定。値も規約も一切変えない（読むだけ）。"}

    # 各窓の SPY 年率と、各社の年率
    sp, per = [], []
    for a, b in wins:
        if a not in S or b not in S:
            sp.append(None); per.append({}); continue
        yrs = (b - a) / 12.0
        sp.append((S[b] / S[a]) ** (1 / yrs) - 1)
        per.append({t: c for t in P for c in [cagr(P[t], a, b)] if c is not None})
    print("■ 窓ごとの SPY（配当込み・年率）")
    for i, ((a, b), s) in enumerate(zip(wins, sp), 1):
        f = lambda k: f"{k//12}-{k%12+1:02d}"
        print(f"   W{i} {f(a)}→{f(b)}  SPY {'—' if s is None else f'{s*100:+5.1f}%'}"
              f"   測れた社 {len(per[i-1])}")
    out["windows"] = [{"w": i + 1, "spy": sp[i], "n": len(per[i])} for i in range(4)]

    # 質実証プール（この台帳の既存の定義＝営利率10%+ ∧ 5年FCF全年黒字 ∧ 5年営利黒字）
    qual = set()
    try:
        f2 = json.load(open(os.path.join(OUT, "retro_features2_2018.json")))
        # 質実証＝この台帳の既存の定義（営業利益率10%+ ∧ 5年FCF全年黒字）。
        # ⚠**この欄は「率」で入っている**（実データで確認: opm=0.1881／fcfpos5=5＝黒字だった年数）。
        #   %と取り違えると `>=10` が一件も当たらず**プールが静かに0社になる**——
        #   fill_sht.py が gate0_all.csv の成長率で踏んだのと同じ罠。だから帯で確かめてから使う。
        for r in (f2.get("rows") or []):
            o = r.get("opm")
            if o is None:
                continue
            o = o * 100 if abs(o) <= 3 else o        # 率で来たら%へ（帯検問）
            if o >= 10 and (r.get("fcfpos5") or 0) >= 5:
                qual.add(r.get("ticker"))
    except Exception:
        pass
    # ★プールが空なら**黙って飛ばさない**——「0社」は測定ではなく照合の失敗のことがある
    #   （門0のBOM事故・hist_val_market の探索下限と同族）
    if not qual:
        print("  ⚠質実証プールが0社になった＝欄名か単位の照合に失敗している。全社だけで測る")
    pools = [("全社", None)] + ([("質実証", qual)] if qual else [])

    print("\n■ 判定: 直近の窓でSPYに負けた社は、次の窓でもSPYに負けるか")
    res = {}
    for plab, pool in pools:
        rows = []
        print(f"\n  【{plab}】")
        for i in range(3):
            if sp[i] is None or sp[i + 1] is None:
                continue
            both = [t for t in per[i] if t in per[i + 1] and (pool is None or t in pool)]
            won = [t for t in both if per[i][t] > sp[i]]
            lost = [t for t in both if per[i][t] <= sp[i]]
            nx = lambda g: (sum(1 for t in g if per[i + 1][t] > sp[i + 1]) / len(g)) if g else None
            pw, pl = nx(won), nx(lost)
            med = lambda g: (sorted(per[i + 1][t] for t in g)[len(g) // 2]) if g else None
            lift = None if (pw is None or pl is None) else pw - pl
            rows.append(dict(trans=f"W{i+1}→W{i+2}", n=len(both), n_won=len(won), n_lost=len(lost),
                             p_next_won=pw, p_next_lost=pl, lift=lift,
                             med_won=med(won), med_lost=med(lost)))
            print(f"    W{i+1}→W{i+2}  勝った{len(won):3}社→次も勝つ {pw*100:4.1f}%"
                  f" ／ 負けた{len(lost):3}社→次は勝つ {pl*100:4.1f}%"
                  f"   **lift {lift:+.3f}**"
                  f"   次の窓の中央値 勝{med(won)*100:+5.1f}% / 負{med(lost)*100:+5.1f}%")
        ls = [r["lift"] for r in rows if r["lift"] is not None]
        ok = bool(ls) and min(ls) >= LIFT
        same = bool(ls) and (all(x > 0 for x in ls) or all(x < 0 for x in ls))
        print(f"    → lift {[f'{x:+.3f}' for x in ls]}　"
              f"線{LIFT}以上が全遷移: {'✓' if ok else '✗'}／符号が揃う: {'✓' if same else '✗'}"
              f"　**判定: {'合格' if (ok and same) else '不合格'}**")
        res[plab] = dict(rows=rows, all_above_line=ok, same_sign=same,
                         verdict="合格" if (ok and same) else "不合格")
    out["test"] = res

    # おまけ: 規則を実際に回したら終価はどうなるか（等ウェイト・窓ごとに入替）
    print("\n■ おまけ: 規則を実際に回したときの終価（W1の実績で選び、W2以降を等ウェイトで持つ）")
    for plab, pool in pools:
        base = [t for t in per[0] if t in per[1] and t in per[2] and t in per[3]
                and (pool is None or t in pool)]
        if not base:
            continue
        keep = [t for t in base if per[0][t] > sp[0]]
        drop = [t for t in base if per[0][t] <= sp[0]]
        def tv(g):
            if not g:
                return None
            tot = 0.0
            for t in g:
                v = 1.0
                for i in (1, 2, 3):
                    v *= (1 + per[i][t]) ** (WIN_M / 12.0)
                tot += v
            return tot / len(g)
        yrs = 3 * WIN_M / 12.0
        a, b = tv(keep), tv(drop)
        spv = 1.0
        for i in (1, 2, 3):
            spv *= (1 + sp[i]) ** (WIN_M / 12.0)
        print(f"  【{plab}】W1でSPY超だった{len(keep)}社 → 年率 {(a**(1/yrs)-1)*100:+5.1f}%"
              f" ／ W1でSPY未満だった{len(drop)}社 → 年率 {(b**(1/yrs)-1)*100:+5.1f}%"
              f" ／ SPY {(spv**(1/yrs)-1)*100:+5.1f}%")
        out.setdefault("carry", {})[plab] = dict(
            n_keep=len(keep), n_drop=len(drop),
            cagr_keep=a ** (1 / yrs) - 1, cagr_drop=b ** (1 / yrs) - 1,
            cagr_spy=spv ** (1 / yrs) - 1)

    json.dump(out, open(os.path.join(OUT, "beat_spy_rule.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n→ out/beat_spy_rule.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
