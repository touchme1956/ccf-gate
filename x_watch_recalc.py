#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
x_watch_recalc.py — X監視表(gate1_x_watch.json)の開通ラインを門X遮断器(E[r]≥0・v9.9.78)で再計算する。
背景(2026-07精査): 旧監視表は条件①(E[r]≥12)だけを解いており、記載の開通PERで約定しても
④ストレス(成長−25%∧終着PER−30%でE[r]≥7)が不成立=門X自身の判定を通らない不整合があった
(例: ASML 旧開通PER33.8ではストレス4.79<7)。本器は①と④を同時に満たす最大PERを解く。
併せて階段指値の上段「fair線」(終着PER線=倍率の重力ゼロ・約定時E[r]=earned)を出力する:
  先段1/2=X開通ライン(浅い・先に約定・E[r]=12) / 深段1/2=fair線(深い・後に約定・E[r]=earned)。
  X開通ライン一本の指値は約定期待値を12%に錨付けする——階段化でエントリー期待値を12〜15%帯へ。
  倍率拡大は相変わらず計上しない(掟六)ため教義と両立。
式(正本Ⅵ・chomiraiと同一):
  fairPER = clamp(8+g, 16, 30)   mult(p) = ((min(p,fair)/p)^0.1 − 1)×100
  ① E[r]=shy+g+mult(p) ≥ 12 → p ≤ fair / (1+(12−earned)/100)^10   (earned=shy+g)
  ④ erS(p)=shy+hc·g+((min(p,fair)×0.7/p)^0.1−1)×100 ≥ 7  (hc=grower0.85/通常0.75・2026-07成長連動)
     p≤fairでは erS=shy+hc·g−3.5(定数)。これが7未満なら④は価格で解けない=値段では開かない。
     p>fairでは p ≤ 0.7×fair / (1+(7−shy−hc·g)/100)^10
  ② earned ≥ 10(価格非依存) ③ 倍率寄与: per1=min(p,fair)よりmult≤0=常に成立
使い方: python x_watch_recalc.py   (gate1_x_watch.json を読み、同ファイルへ書き戻す)
注意: eps一定仮定(四半期保守で新epsのper_now/px_nowを更新してから再実行する)。
"""
import json, math, os
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
        import re as _re
        if _re.match(r"^\d{4,5}$", str(t)) and float(o.get("roic") or 0) > 40 and not float(o.get("roicEx") or 0) > 0:
            print(f"▲{t}: 日本株roic>40%かつroicEx無し=検死未了のため追加不可(門式現金控除ROICで再審査)"); continue
        if o.get("shy") is None:
            print(f"…{t}: shy(純還元)未測定のため追加不可——0と断定するとE[r]を過小評価し開通線が実際より遠くなる"); continue
        shy = float(o.get("shy"))
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
    # grower(実証成長≥15×ROIC≥20×堀無傷×質72+)は④ヘアカット15%(ユーザー支持の成長連動・正本Ⅵと同期)
    hc = 0.75
    try:
        fp2 = f"out/{l['ticker']}_gate_pack.json"
        if os.path.exists(fp2):
            pk = json.load(open(fp2, encoding="utf-8"))
            qok = (l.get("omega") or 0) >= 72 or (l.get("omega") is None and l.get("otier") == "kanshi")
            import re as _re2
            if _re2.match(r"^\d{4,5}$", str(l.get("ticker"))) and float(pk.get("roic") or 0) > 40 and not float(pk.get("roicEx") or 0) > 0:
                qok = False  # JP検死未了はgrower不適格(掟一=怪しい実測は使わない)
            if qok and float(pk.get("cagr") or 0) >= 15 and float(pk.get("roic") or 0) >= 20 \
               and (pk.get("erosion") or "none") == "none" and (pk.get("disrupt") or "settled") != "threat":
                hc = 0.85
                nl["grower"] = True
    except Exception:
        pass
# 2026-07(ユーザー指示): shyを価格連動で解く——同じ還元ドル額なら安値ほど利回りが上がる(shy(p)=shy0×p0/p)。
    # 旧実装はshyを現値固定で解いており、高還元の成熟優良で「値段では開かない」が過剰に絶対的だった。
    # 倍率拡大は相変わらず不計上(掟六)。v9.9.78(2026-08-04 ユーザー明示指示「遮断器のみ実装しよう」):
    # 合否線は遮断器 E[r]≥0 のみ——開通線も同じ式で解く(合否と別の式で解くと v9.9.65 の
    # 「同じ台帳を見る二つの検査器が違うことを言う」になる)。旧①≥12∧④ストレス≥7は廃止。
    # 2026-07-28: shy未測定を0と断定しない。旧実装は pack.shy=null を 0.0 に化けさせており、
    #   ASML(配当利回りだけで0.52%＋自社株買い)まで「還元ゼロ」として開通線を遠くに描いていた。
    #   MPTIの「値段では開かない(還元ほぼゼロ)」もこの既定値の産物の疑いがある。
    shy_unknown = False
    try:
        if os.path.exists(fp2):
            if json.load(open(fp2, encoding="utf-8")).get("shy") is None and abs(shy) < 1e-9:
                shy_unknown = True
    except Exception:
        pass
    if shy_unknown:
        nl.update(x_open_per=None, x_open_px=None, drop_pct=None, fair_per=None, fair_px=None,
                  status="判定不能(還元shy未測定——market_fetch→market_mergeで充填してから再実行)")
        out.append(nl)
        continue

    def cond(pp):
        sy = shy * (per / pp)  # shy0×(p0/p)——PER比=価格比(eps一定仮定)
        m1 = ((min(pp, fair) / pp) ** 0.1 - 1) * 100
        return sy + g + m1 >= 0  # v9.9.78: 遮断器E[r]≥0（index.html ccfXJudge と同式）
    if cond(per):
        popen = per
        nl.update(x_open_per=round(per, 1), x_open_px=px, drop_pct=0.0, status="既に開通圏——再採点で確認")
    elif not cond(per * 0.02):
        popen = None
        nl.update(x_open_per=None, x_open_px=None, drop_pct=None, fair_per=None, fair_px=None,
                  status="値段では開かない(還元ほぼゼロ×エンジン不足——価格が利回りを生まない)")
    else:
        lo, hi = per * 0.02, per
        for _ in range(80):
            mid = (lo + hi) / 2
            if cond(mid): lo = mid
            else: hi = mid
        popen = lo
        nl["x_open_per"] = round(popen, 1)
        nl["x_open_px"] = round(px * popen / per, 2)
        nl["drop_pct"] = round((popen / per - 1) * 100, 1)
        nl["status"] = "監視" if nl["drop_pct"] >= -70 else f"監視(開通{nl['drop_pct']}%＝事実上遠い・還元が細い)"
    if popen is not None:
        # 階段深段: fair線。④拘束で開通線がfairを下回る場合は開通線にクリップ(全段が4条件成立圏内)
        fair_eff = min(fair, popen)
        if fair_eff < per:
            nl["fair_per"] = round(fair_eff, 1)
            nl["fair_px"] = round(px * fair_eff / per, 2)
        else:
            nl["fair_per"] = round(per, 1)
            nl["fair_px"] = px
    out.append(nl)

d["lines"] = out
d["generated"] = str(date.today())
d["method"] = ("門X遮断器(E[r]≥0・v9.9.78)が成立する最大PERから逆算(旧4条件は2026-08-04に廃止——歴史検証で"
               "④ストレス〔成長−25%∧終着PER−30%≥7〕不成立の開通線を出していた)。掟六v2成長連動: "
               "終着PER=min(現PER,clamp(8+g,16,30))。階段指値=先段1/2をx_open(浅い・先に約定)・深段1/2を"
               "fair線(深い)に置く。shyは価格連動(shy(p)=shy0×p0/p・2026-07)＝同じ還元ドル額を安い時価で割り直す。grower(実証成長×資本効率×堀無傷×質72+)は④ヘアカット15%——約定期待値を12%固定から12〜15%帯へ。"
               "eps一定仮定で株価換算。earned<12またはストレス下限(shy+0.75g−3.5)<7は値段では開かない")
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for l in out:
    print(f"{l['ticker']:<6} Ω{l.get('omega','')} earned{l['earned']}% "
          f"開通PER{l.get('x_open_per')} fair線PER{l.get('fair_per')} {l['status']}")
