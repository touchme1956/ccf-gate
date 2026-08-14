#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/omega_retro_judg.py — 案A: 判断項目 p1/p2/p4 を歴史側で**機械導出**する（2026-08-14新設）

■ なぜ「読解」ではなく「機械」なのか（案Aの規模が変わった実測）
  Ω̂ が潰れる 46.4pt の内訳を1欄ずつ測ると:

      p1 −16.7 ／ p2 −14.0 ／ p4 −11.6 ／ f1 −9.6 ／ f3 −6.2 ／ f2 −4.1 ／ f4 −2.7
      p3 −0.5（nde から門が自動導出）／ f5 +0.1（disrupt から自動導出）

  **効いている上位3つ（p1/p2/p4 ＝ 合計 −42.3pt ＝潰れの91%）は全部機械で出せる。**
  ＝案Aは「500社×9欄の読解」ではなく、**ほぼ採取の仕事**だった。

■ 刻みは門の正本（ccfAskText）から取る。ここで発明しない
  p1 ROIC安定性 = 5年ROICの**変動係数(σ÷平均)**: <15→90 / <30→80 / <50→65 / 以上→50
     ⇒ **既存の正本 fill_derived_judgment.p1_of をそのまま呼ぶ**（二重正本を作らない）
  p2 不況耐性 = 直近2回の景気後退時の営利DD: 浅い(−20%以内)→95 / 中(−40%)→75 / 深い(−60%超)→50
     （不況実績なしは70上限）
  p4 会計健全 = accr<0→90 / 0〜5%→80 / 5〜10%→65 / >10%→45
     ⚠ 門の刻みは「accr<0 **かつ監査意見無限定**→90」。監査意見は歴史側に無いので
       **無限定と仮定して90を許す**——この一点だけ門より甘い。報告に明記する。

■ ⚠ f1 は歴史側で埋まらない（読解の問題ではなく採取の穴）
  f1 は ROIIC と WACC が要る。実測の被覆は **roiic 11%(2013) / 53%(2015)**、
  かつ WACC は beta を要し歴史側に無い。**埋められないものを埋めたことにしない**（ルール7）。
  f1 は空欄のまま＝Ω̂_A にも −9.6pt 分の潰れが残る。**これは限界として報告する。**

■ p2 の「直近2回の景気後退」をどう決めるか（恣意を入れない）
  暦で決め打ちしない——**その社自身の営業利益系列の中で、前年より落ちた年**を後退年とし、
  各後退の**ピークからの落ち込み率**を測る。窓に落ち込みが2回以上あれば直近2回の**深いほう**、
  1回なら それ、0回なら **不況実績なし＝70上限**（門の刻みそのもの）。
  2013ビンテージの窓は 2008-2013 でリーマンを含む＝この定義で自然に拾える。

使い方: python3 night/omega_retro_judg.py
出力: out/omega_retro_judg_{2013,2015}.json
"""
import json
import os
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
OUT = os.path.join(BASE, "out")

# ★p1 の刻みの唯一の実装をそのまま呼ぶ（night/shadow_p1_cv.py と同じ作法）
from night.fill_derived_judgment import p1_of  # noqa: E402


def p2_of(op_series):
    """門の刻み: 浅い(−20%以内)→95 / 中(−40%)→75 / 深い(−60%超)→50 / 不況実績なし→70上限。
    後退＝前年より営業利益が落ちた年。落ち込み率はその局面のピークから測る。"""
    if not op_series:
        return None, "営業利益系列が無い"
    ys = sorted(op_series)
    v = [op_series[y] for y in ys]
    if len(v) < 3:
        return None, f"営業利益系列が{len(v)}年で足りない"
    dds, peak = [], v[0]
    for i in range(1, len(v)):
        if v[i] >= peak:
            peak = v[i]
        elif peak > 0:
            dds.append((v[i] - peak) / peak)      # 負の値
    if not dds:
        return 70, f"窓({ys[0]}-{ys[-1]})に営業利益の落ち込みが一度も無い＝不況実績なし→70上限"
    worst = min(dds[-2:]) if len(dds) >= 2 else dds[-1]
    g = 95 if worst >= -0.20 else 75 if worst >= -0.40 else 50
    return g, (f"窓({ys[0]}-{ys[-1]})の営業利益の落ち込み {len(dds)}回・"
               f"直近2回の深いほう {worst:.1%} → {g}")


def p4_of(accr):
    """門の刻み: accr<0→90 / 0〜5%→80 / 5〜10%→65 / >10%→45。
    ⚠ 門は 90 に「監査意見無限定」も要求するが歴史側に無い＝**無限定と仮定**（門より甘い一点）。"""
    if accr is None:
        return None, "accr が無い"
    g = 90 if accr < 0 else 80 if accr <= 5 else 65 if accr <= 10 else 45
    return g, f"accr {accr:.1f}% → {g}（90は監査意見無限定を仮定＝歴史側に監査意見が無い）"


def cv_of(tc):
    """{年:[roic,roicg]} から roic 系列の変動係数(%)。門式 roic の側だけを使う。"""
    if not tc:
        return None, "ROIC系列が無い"
    ser = [v[0] for _, v in sorted(tc.items()) if v and v[0] is not None]
    if len(ser) < 3:
        return None, f"ROIC系列が{len(ser)}年で足りない（3年未満）"
    m = st.mean(ser)
    if m <= 0:
        return None, f"ROICの平均が {m:.1f}% ＝変動係数が定義できない"
    return st.pstdev(ser) / m * 100, f"ROIC {len(ser)}年 平均{m:.1f}% σ{st.pstdev(ser):.1f}pt"


def main():
    for yr in (2013, 2015):
        p = os.path.join(OUT, f"omega_retro_machine_{yr}.json")
        if not os.path.exists(p):
            sys.exit(f"{p} が無い（先に python3 night/omega_retro_collect.py）")
        M = json.load(open(p, encoding="utf-8"))["items"]
        out, cnt = {}, {"p1": 0, "p2": 0, "p4": 0}
        for t, m in M.items():
            cv, why1 = cv_of(m.get("tc"))
            p1 = p1_of(cv) if cv is not None else None
            p2, why2 = p2_of(m.get("op"))
            p4, why4 = p4_of(m.get("accr"))
            for k, val in (("p1", p1), ("p2", p2), ("p4", p4)):
                if val is not None:
                    cnt[k] += 1
            out[t] = dict(p1=p1, p2=p2, p4=p4,
                          why=dict(p1=(f"変動係数 {cv:.1f}%（{why1}）" if cv is not None else why1),
                                   p2=why2, p4=why4))
        q = os.path.join(OUT, f"omega_retro_judg_{yr}.json")
        json.dump({"generated": __import__("time").strftime("%Y-%m-%d"), "vintage": yr,
                   "note": "案A: p1/p2/p4 を門の刻みで機械導出。p1 は fill_derived_judgment.p1_of の正本を呼ぶ。"
                           "f1 は roiic の被覆(11%/53%)と WACC 不在で**埋められない**＝空欄のまま。",
                   "n": len(out), "filled": cnt, "items": out},
                  open(q, "w"), ensure_ascii=False, indent=1)
        n = len(out)
        print(f"■ {yr}: {n}社  p1 {cnt['p1']}({cnt['p1']/n:.0%}) / p2 {cnt['p2']}({cnt['p2']/n:.0%})"
              f" / p4 {cnt['p4']}({cnt['p4']/n:.0%})  → {os.path.relpath(q, BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
