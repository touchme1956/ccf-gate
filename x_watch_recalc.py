#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
x_watch_recalc.py — X監視表(gate1_x_watch.json)の開通ラインを門X4条件の同時成立で再計算する。
背景(2026-07精査): 旧監視表は条件①(E[r]≥12)だけを解いており、記載の開通PERで約定しても
④ストレス(成長−25%∧終着PER−30%でE[r]≥7)が不成立=門X自身の判定を通らない不整合があった
(例: ASML 旧開通PER33.8ではストレス4.79<7)。本器は①と④を同時に満たす最大PERを解く。
併せて階段指値の上段「fair線」(終着PER線=倍率の重力ゼロ・約定時E[r]=earned)を出力する:
  下段1/2=X開通ライン(E[r]=12ちょうど) / 上段1/2=fair線(E[r]=earned=12〜18%)。
  X開通ライン一本の指値は約定期待値を12%に錨付けする——階段化でエントリー期待値を12〜15%帯へ。
  倍率拡大は相変わらず計上しない(掟六)ため教義と両立。
式(正本Ⅵ・chomiraiと同一):
  fairPER = clamp(8+g, 16, 30)   mult(p) = ((min(p,fair)/p)^0.1 − 1)×100
  ① E[r]=shy+g+mult(p) ≥ 12 → p ≤ fair / (1+(12−earned)/100)^10   (earned=shy+g)
  ④ erS(p)=shy+0.75g+((min(p,fair)×0.7/p)^0.1−1)×100 ≥ 7
     p≤fairでは erS=shy+0.75g−3.5(定数)。これが7未満なら④は価格で解けない=値段では開かない。
     p>fairでは p ≤ 0.7×fair / (1+(7−shy−0.75g)/100)^10
  ② earned ≥ 10(価格非依存) ③ 倍率寄与: per1=min(p,fair)よりmult≤0=常に成立
使い方: python x_watch_recalc.py   (gate1_x_watch.json を読み、同ファイルへ書き戻す)
注意: eps一定仮定(四半期保守で新epsのper_now/px_nowを更新してから再実行する)。
"""
import json, math
from datetime import date

P = "gate1_x_watch.json"
d = json.load(open(P, encoding="utf-8"))

# --- Ω75+(kanshi_list)のうち監視表に未収載で、packに市場値(per/px)が揃った銘柄を自動追加 ---
#     g導出はⅥ買付順位と同式: roicQ>=15かつ堀無傷かつcagr>0→min(cagr,20) / それ以外はbR×min(roicg,60)をcagrで頭打ち
try:
    kn = json.load(open("kanshi_list.json", encoding="utf-8"))
    have = {l["ticker"] for l in d["lines"]}
    cand = []
    for grp in ("toka", "omega_watch", "oshime"):
        cand += kn.get("groups", {}).get(grp, [])
    for t in cand:
        if t in have: continue
        fp = f"out/{t}_gate_pack.json"
        if not __import__("os").path.exists(fp): continue
        o = json.load(open(fp, encoding="utf-8"))
        per, px = o.get("per"), o.get("px")
        if not per or not px:
            print(f"…{t}: per/px未充填のため追加不可(market_fetch→market_mergeで充填してから再実行)"); continue
        shy = o.get("shy") or 0.0
        cagr = float(o.get("cagr") or 0)
        roicg = float(o.get("roicg") or o.get("roic") or 0)
        roicq = float(o.get("roicEx") or 0) if (o.get("roicEx") and float(o.get("roicEx")) > roicg) else roicg
        moat = (o.get("erosion") != "active") and (o.get("disrupt") != "threat") and (o.get("moatdecay") != "yes")
        if roicq >= 15 and moat and cagr > 0:
            g = min(cagr, 20.0)
        else:
            bR = max(0.0, min(1.0, 1 - (shy / 100.0) * float(per)))
            g = bR * min(roicg, 60.0)
            g = min(g, cagr) if cagr > 0 else min(g, 8.0)
            g = min(g, 20.0)
        d["lines"].append({"ticker": t, "omega": None, "otier": "kanshi",
                           "earned": round(shy + g, 1), "g": round(g, 1),
                           "per_now": float(per), "px_now": float(px), "status": "自動追加"})
        print(f"＋{t}: kanshi Ω75+群から自動追加(g={g:.1f} earned={shy+g:.1f})")
except Exception as e:
    print(f"▲ 自動追加スキップ: {e}")

out = []
for l in d["lines"]:
    earned, g, per, px = l["earned"], l["g"], l["per_now"], l["px_now"]
    shy = round(earned - g, 2)
    fair = max(16.0, min(30.0, 8.0 + g))
    nl = dict(l)
    nl["shy"] = shy
    nl["fairPER"] = round(fair, 1)
    stress_floor = shy + 0.75 * g - 3.5   # p≤fair帯のストレス値(定数)
    if earned < 12:
        nl.update(x_open_per=None, x_open_px=None, drop_pct=None,
                  fair_per=None, fair_px=None,
                  status="値段では開かない(還元+実証成長<12)")
    elif stress_floor < 7:
        nl.update(x_open_per=None, x_open_px=None, drop_pct=None,
                  fair_per=None, fair_px=None,
                  status="値段では開かない(ストレス④が価格で解けない=成長×還元が薄い)")
    else:
        p1 = fair / (1 + (12 - earned) / 100) ** 10
        p4 = 0.7 * fair / (1 + (7 - shy - 0.75 * g) / 100) ** 10
        popen = min(p1, p4)
        nl["x_open_per"] = round(popen, 1)
        nl["x_open_px"] = round(px * popen / per, 2)
        nl["drop_pct"] = round((popen / per - 1) * 100, 1)
        # 階段上段: fair線(倍率の重力ゼロ・約定時E[r]=earned)。現PERがfair以下なら既にfair圏。
        # ④拘束銘柄では開通線がfair線を下回りうる——上段も開通線にクリップ(どの段の約定も4条件成立圏内)
        fair_eff = min(fair, popen)
        if fair_eff < per:
            nl["fair_per"] = round(fair_eff, 1)
            nl["fair_px"] = round(px * fair_eff / per, 2)
        else:
            nl["fair_per"] = round(per, 1)
            nl["fair_px"] = px
        nl["status"] = "既に開通圏——再採点で確認" if popen >= per else "監視"
    out.append(nl)

d["lines"] = out
d["generated"] = str(date.today())
d["method"] = ("門X裁きⅠの4条件を同時に満たす最大PERから逆算(2026-07修正: 旧版は①E[r]≥12のみを解いており"
               "④ストレス〔成長−25%∧終着PER−30%≥7〕不成立の開通線を出していた)。掟六v2成長連動: "
               "終着PER=min(現PER,clamp(8+g,16,30))。階段指値=下段1/2をx_open(E[r]=12)・上段1/2を"
               "fair線(倍率の重力ゼロ・E[r]=earned)に置く——約定期待値を12%固定から12〜15%帯へ。"
               "eps一定仮定で株価換算。earned<12またはストレス下限(shy+0.75g−3.5)<7は値段では開かない")
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for l in out:
    print(f"{l['ticker']:<6} Ω{l.get('omega','')} earned{l['earned']}% "
          f"開通PER{l.get('x_open_per')} fair線PER{l.get('fair_per')} {l['status']}")
