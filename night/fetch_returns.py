#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保有のトータルリターンと S&P500 との突合せ（2026-08-17新設・ユーザー要望）

出力: out/returns.json —— **表示専用。Ω・四関門・売却規律・配分のどれにも触れない。**

■ 何を出すか（3つとも「円建て」に揃える）
  ① 銘柄ごと: 取得額 / 評価額 / 価格リターン / トータルリターン / 為替の寄与
  ② ポートフォリオ合計: 同上
  ③ S&P500: **同じ円を同じ日に S&P500 へ入れていたら**いくらになっていたか

■ 円建てに揃える理由（これが一番大事）
  資産は100%が外貨建てで、生活の通貨は円。**ドル建てのリターンと円建ての資産を並べたら
  「基準の違う二つを割る」型そのもの**（この台帳が12回踏んだ型）。
  だから S&P500 も `^SP500TR × USDJPY` で円へ直してから比べる。
  そのうえで **為替の寄与を分けて出す**——これを混ぜると、円安で儲かったのを
  「銘柄選択が上手かった」と読み違える。

■ 配当の扱い（ここも揃える）
  **価格リターン**  = 終値ベース。証券口座の含み損益と一致する
  **トータルリターン** = adjclose ベース＝配当再投資込み。**S&P500TR と同じ基準**
  片方だけ出すと必ず誤読する（audit_er_realized が記録した
  「価格リターンには配当が入らない。揃えずに結論すると自分で作った偏りを発見と誤認する」）。

■ 取得額（絶対のルール7 —— 欠測を勝手に埋めない）
  円建ての投資家にとっての一次データは **実際に出した円**なので、優先順はこう:
    ① `bjpy`（取得額・円）  … 証券アプリの「取得価額」。**為替を仮定せずに済む唯一の値**
    ② `bpx`（買付単価・現地通貨）… 証券口座の「平均取得価額」。現地通貨のリターンは厳密になる
    ③ 無ければ `bd`（買付日）の終値で推定し src="est" と明示する
    ④ どれも無ければ **測れない**（skip）——推測の数字は出さない
  ⚠ est は「その日の終値」であって「実際に約定した値」ではない。手数料もスプレッドも入らない。

■ ★`bd` が買付日でないことがある（2026-08-18・実測で判った）
  `bd` は**台帳に行を作った日**が入っていることがある。実測: 4社とも `bd=2026-08-05` なのに、
  証券口座の平均取得価額はその日の終値と **3.8〜16.4% 食い違う**（MSFT 407.73 vs 487.46 等）
  ＝**実際の買付はもっと前**。これを放置すると二つ壊れる——
    (a) 円換算に**買付日でない日のドル円**を使う（＝「基準の違う二つを割る」型）
    (b) S&P500 との比較が「**同じ日**に入れていたら」でなくなる＝比較の意味が消える
  よって `bpx` が `bd` の終値と 3% 超ずれたら `bd_suspect` を立て、
  **その行は S&P500 との比較から外す**（円建ての取得額も「概算」と明示する）。
  ⚠ 買付日をこの道具が推定して埋めることはしない。代わりに**その水準だった期間**を候補として出す。
    ★2026-08-18 ユーザー指示「かいつけ日は想定日でいい」を受けて、`night/estimate_bd.py` が
    **別の道具として**想定日を書く（`bdEst:true` + `bdWin`）。この道具はその札を読んで
    **「想定」と明示したまま**比較を出し、**窓の両端で答えがどう動くか**を必ず併記する
    ——実測で RBC は −0.3〜−15.9pt と 15pt 動く＝**想定が答えを支配する行がある**。

■ 年率換算はしない（180日未満）
  audit_er_realized / kessan_check_jp と同じ判断。数日の値動きを年率にすると桁が暴れ、
  **数字がある分だけ空欄より有害**。180日を超えたら年率も出す。

■ データ源は Yahoo 一本
  retro_fetch_returns.py が確立した作法をそのまま使う——FMPとYahooは配当調整の作法が違い
  （実測 MSFT 0.789 vs 0.814）、混ぜると事故になる。鍵不要。
  日本株は `.T` を付ける（fetch_dashboard.py と同じ）。

実行: python3 night/fetch_returns.py [--json]
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "returns.json")
# ⚠ 推移は**別ファイル**に置く。20年で5000点まで伸びるので、盤が毎回読む
#   returns.json に混ぜると表を出すだけの画面が推移のぶんまで払うことになる。
OUT_SERIES = os.path.join(BASE, "out", "returns_series.json")
MAX_POINTS = 600          # これを超えたら間引く（両端は必ず残す）
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
BENCH = "^SP500TR"      # S&P500 トータルリターン指数（配当再投資込み）
FX = "JPY=X"            # USDJPY
ANNUALIZE_MIN_DAYS = 180


def yahoo(sym, t0, t1):
    """日次の close / adjclose を {YYYY-MM-DD: (close, adj)} で返す。取れなければ None。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(sym)}?period1={t0}&period2={t1}&interval=1d")
    try:
        r = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=30).read())
        res = r["chart"]["result"][0]
        ts = res["timestamp"]
        cl = res["indicators"]["quote"][0]["close"]
        aj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or cl
        out = {}
        for i, t in enumerate(ts):
            c, a = cl[i], aj[i]
            if c is None:
                continue
            d = datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
            out[d] = (float(c), float(a if a is not None else c))
        return out or None
    except Exception:
        return None


def on_or_before(series, day):
    """その日、無ければ直前の営業日。無ければ None。"""
    ks = [k for k in series if k <= day]
    return series[max(ks)] if ks else None


def day_on_or_before(series, day):
    """その日、無ければ直前の営業日の**日付**。無ければ None。
    ⚠ `on_or_before` は値しか返さない——**どの日の値を掴んだか**が要る場面があるので分けてある
    （実測: ドル円の系列に 08-17 が無く 08-16→08-18 と飛ぶ。掴んだ日を知らないと
     『08-18のドル円 × 08-17の株価』を黙って掛けてしまう）。"""
    ks = [k for k in series if k <= day]
    return max(ks) if ks else None


def last(series):
    k = max(series)
    return k, series[k]


def level_window(ser, px, tol=0.005):
    """終値がその水準（±tol）だった期間を返す。**買付日の推定ではない**。

    平均取得価額は複数回買付の平均でありうるので、終値が一致する日を買付日と決めるのは推測。
    ここが返すのは「人が取引履歴のどこを見ればよいか」の**候補の窓**であって、
    どこにも書き戻さないし計算にも一切使わない（絶対のルール7）。
    """
    if not px:
        return None
    hits = [d for d in sorted(ser) if abs(ser[d][0] - px) / px < tol]
    if not hits:
        return None
    return {"first": hits[0], "last": hits[-1], "n": len(hits), "tol_pct": tol * 100}


def build_series(rows, sers, bench, fx, compared, compared_tr, benchmark):
    """日次の推移（円建て）。**表示専用**——判定にも合計にも使わない。

    作り方は終点の式とまったく同じで、日付だけ動かす:
      値   = Σ 株数 × 終値(d) × ドル円(d)
      配当込 = Σ 取得額(円) × (adjclose(d)/adjclose(買付日)) × (ドル円(d)/ドル円(買付日))
      指数  = Σ 取得額(円) × (^SP500TR(d)/^SP500TR(買付日)) × (ドル円(d)/ドル円(買付日))
    ★だから **終点は既存の合計と一致しなければならない**。一致しなければ
      「同じ台帳を見る二つの検査器が違うことを言っている」(v9.9.65) ので、
      ずれを `endpoint_gap` として必ず書き出す（黙って直さない）。
    ⚠ 買付日が判らない行（cmp_out）は**入れない**——比較の集合と揃えるため。
    """
    use = [r for r in rows if not r.get("skip") and not r.get("cmp_out")
           and r.get("bd") and r.get("cost_jpy") and sers.get(r["t"])]
    if not use or not bench or not fx:
        return None
    start = min(r["bd"] for r in use)
    end = max((r.get("asof") or "") for r in use)
    spine = [d for d in sorted(bench) if start <= d <= end]
    if len(spine) < 2:
        return None

    days, inv_a, val_a, tr_a, bmk_a = [], [], [], [], []
    for d in spine:
        inv = val = tr = bmk = 0.0
        b = on_or_before(bench, d); f = on_or_before(fx, d)
        if not (b and f):
            continue
        for r in use:
            if r["bd"] > d:
                continue                      # まだ入金していない＝この日は分母に入らない
            c = on_or_before(sers[r["t"]], d)
            b0 = on_or_before(bench, r["bd"])
            if not (c and b0):
                continue
            jp = r["ccy"] == "JPY"
            k = 1.0 if jp else f[0]
            k0 = 1.0 if jp else float(r.get("fx0") or 0)
            if not k0:
                continue
            fxr = k / k0
            inv += r["cost_jpy"]
            v = r["sh"] * c[0] * k
            val += v
            # 配当の寄与だけを価格に掛ける（終点の式と同じ・v9.9.156）
            c0 = on_or_before(sers[r["t"]], r["bd"])
            df = ((c[1] / c0[1]) / (c[0] / c0[0])) if (c0 and c0[0] and c0[1] and c[0]) else 1.0
            tr += v * df
            bmk += r["cost_jpy"] * (b[1] / b0[1]) * fxr
        if inv <= 0:
            continue
        days.append(d); inv_a.append(round(inv))
        val_a.append(round(val)); tr_a.append(round(tr)); bmk_a.append(round(bmk))
    if len(days) < 2:
        return None

    # ★終点の検算——ここが合わなければ推移か合計のどちらかが壊れている
    gap = None
    if compared and compared.get("cost_jpy"):
        # ★3本とも突き合わせる。1本だけ合わせても「たまたま合った」を排除できない
        gap = {"val": round(val_a[-1] - compared["val_jpy"]),
               "cost": round(inv_a[-1] - compared["cost_jpy"]),
               "tr": (round(tr_a[-1] - compared_tr["val_jpy"]) if compared_tr else None),
               "bmk": (round(bmk_a[-1] - benchmark["val_jpy"]) if benchmark else None)}
        tol = max(50, compared["val_jpy"] * 0.001)
        gap["ok"] = all(abs(gap[k]) <= tol for k in ("val", "cost", "tr", "bmk")
                        if gap.get(k) is not None)

    # 間引き（両端は必ず残す）。線を描くためだけなので等間隔でよい
    thin = None
    if len(days) > MAX_POINTS:
        step = (len(days) + MAX_POINTS - 1) // MAX_POINTS
        idx = list(range(0, len(days), step))
        if idx[-1] != len(days) - 1:
            idx.append(len(days) - 1)
        thin = {"step": step, "before": len(days), "after": len(idx)}
        days = [days[i] for i in idx]; inv_a = [inv_a[i] for i in idx]
        val_a = [val_a[i] for i in idx]; tr_a = [tr_a[i] for i in idx]
        bmk_a = [bmk_a[i] for i in idx]

    return {"days": days, "inv": inv_a, "val": val_a, "tr": tr_a, "bmk": bmk_a,
            "n": len(use), "tickers": sorted(r["t"] for r in use),
            "endpoint_gap": gap, "downsampled": thin}


def main():
    st_path = os.path.join(BASE, "state.json")
    if not os.path.exists(st_path):
        print("✗ state.json が無い——保有が読めないので何も書かない"); return 1
    st = json.load(open(st_path, encoding="utf-8"))
    try:
        pf = json.loads((st.get("data") or {}).get("pf:portfolio") or "{}")
        positions = [p for p in (pf.get("positions") or []) if (p.get("sh") or 0) > 0]
    except Exception as e:
        print(f"✗ pf:portfolio が読めない: {e}"); return 1
    if not positions:
        print("✗ 株数のある保有が1件も無い——**書かずに終わる**"
              "（空で上書きすると『保有ゼロ』という嘘になる）"); return 1

    days = [p.get("bd") for p in positions if p.get("bd")]
    start = min(days) if days else None
    if not start:
        print("✗ 買付日(bd)が1件も無い——リターンの起点が決まらないので書かない"); return 1
    # ⚠ 窓は **3年** 遡る。`bd` が買付日でないことがあるので（下の bd_suspect）、
    #   bd の10日前から採ると「終値がその水準だった期間」に届かず候補窓が出せない（実測）。
    #   リクエスト数は変わらない（1銘柄1回）ので、広く採って損は無い。
    t0 = int(datetime.datetime.strptime(start, "%Y-%m-%d").timestamp()) - 86400 * 1100
    t1 = int(time.time())

    fx = yahoo(FX, t0, t1)
    bench = yahoo(BENCH, t0, t1)
    blind = []
    if not fx:
        blind.append(f"{FX}（ドル円）が取れない")
    if not bench:
        blind.append(f"{BENCH}（S&P500トータルリターン指数）が取れない")

    rows, notes = [], []
    sers = {}                 # 推移を組むために銘柄ごとの系列を持ち回す
    tot_cost = tot_val = tot_cost_tr = tot_val_tr = 0.0
    bench_cost = bench_val = 0.0
    cmp_cost = cmp_val = cmp_val_tr = 0.0
    bench_ends = [0.0, 0.0]   # 想定日の窓の両端で指数がどうなるか

    for p in positions:
        t = p["t"]
        jp = (p.get("ccy") == "JPY") or t[:1].isdigit()
        sym = f"{t}.T" if jp else t
        sh = float(p.get("sh") or 0)
        bd = p.get("bd")
        ser = yahoo(sym, t0, t1)
        r = {"t": t, "nm": p.get("nm") or t, "ccy": "JPY" if jp else "USD",
             "sh": sh, "bd": bd}
        sers[t] = ser
        if not ser:
            r["skip"] = "Yahooで価格が取れない"
            rows.append(r); notes.append(f"{t}: 価格が取れない"); continue

        lastd, (cl_now, aj_now) = last(ser)
        r["asof"] = lastd
        # ── 取得額（① bjpy ② bpx ③ bd の終値）────────────────────────
        bpx = float(p.get("bpx") or 0)
        bjpy = float(p.get("bjpy") or 0)          # 取得額（円）＝実際に出した円
        at_bd = on_or_before(ser, bd) if bd else None
        if bpx > 0:
            r["cost_px"], r["src"] = bpx, "actual"
        elif at_bd:
            r["cost_px"], r["src"] = at_bd[0], "est"
            # ⚠ 取得額(円)が実記録なら、推定した単価は**現地通貨のリターンにしか効かない**
            #   （円建ては bjpy、配当込みは adjclose の比なので単価が約分される）。
            #   ひとまとめに「推定」と書くと、実記録の円まで推定に見える
            notes.append(
                f"{t}: 買付単価（現地通貨）が未記録——{bd}の終値で推定"
                + ("。取得額(円)は実記録なので円建てと配当込みには効かない"
                   if bjpy > 0 else "。取得額もこの単価から出している"))
        elif bjpy > 0:
            r["cost_px"], r["src"] = None, "jpy_only"   # 円だけ判っている（現地通貨のリターンは出せない）
        else:
            r["skip"] = "買付単価も買付日も取得額(円)も無い＝取得額が測れない"
            rows.append(r); continue

        # ★ bd が買付日か検算する。実記録の単価が bd の終値と食い違えば bd は買付日でない
        if r["src"] == "actual" and at_bd and at_bd[0]:
            gap = r["cost_px"] / at_bd[0] - 1
            r["bd_gap"] = gap
            if abs(gap) > 0.03:
                r["bd_suspect"] = True
                r["bd_window"] = level_window(ser, r["cost_px"])
                w = r["bd_window"]
                notes.append(
                    f"{t}: **bd({bd}) は買付日ではない**——実記録の単価 {r['cost_px']:,.2f} は"
                    f"その日の終値 {at_bd[0]:,.2f} と {gap*100:+.1f}% 違う"
                    + (f"（終値がこの水準だったのは {w['first']}〜{w['last']}）" if w else "")
                    + "。S&P500 との比較から外し、円換算は概算として出す")

        # ── 配当の寄与だけを取り出す（v9.9.156で是正）──────────────────────
        #   ★**いくらで買ったかに依らない**——窓だけで決まる比にする:
        #       配当の寄与 = (adj(今)/adj(買付日)) ÷ (終値(今)/終値(買付日))
        #   旧実装は adj0 = 取得単価 × (adj/終値) と置いて `adj(今)/adj0` を配当込みとしていたが、
        #   これは「**想定日の株価で買った場合**の配当込み」であって、実際に払った金額の
        #   リターンではない。実コストと想定日の株価が違う行（取得額が実記録＋買付日が想定）で
        #   両者が割れる＝同じ行の中で「基準の違う二つ」を並べていた。
        #   実測(MSFT): 価格 +26.38%（実コスト ¥62,495/株）vs 旧・配当込 +21.20%（想定日 ¥65,305/株）
        #   ＝5.18pt の差は**配当ではなく入口の値段の違い**。配当の寄与は実は +0.26pt しかない。
        #   決定打は **RBC（無配当なのに配当込 −0.72% < 価格 −0.33%）**＝定義上ありえない値が出ていた。
        if at_bd and at_bd[0] and at_bd[1] and cl_now:
            div_f = (aj_now / at_bd[1]) / (cl_now / at_bd[0])
        else:
            div_f = None                                   # 起点の日が無い＝配当込みは出せない
        r["div_f"] = div_f
        r["_adj0"] = at_bd[1] if at_bd else None
        fx0 = on_or_before(fx, bd)[0] if (fx and bd and on_or_before(fx, bd)) else None
        # ⚠ 出口のドル円は **last(fx) ではなく「その銘柄の株価の日」** に合わせる。
        #   実測(2026-08-18): ドル円の系列に 08-17 が無く 08-16→08-18 と飛ぶので、
        #   `last(fx)` は **08-18 のドル円 × 08-17 の株価** を掛けていた＝「基準の違う二つ」。
        #   差(pt)には効かない（保有側と指数側の両方に同じ係数が掛かる）が、
        #   両方の絶対%が +0.168pt ずれる。**掛ける二つは同じ日から採る。**
        _f1 = on_or_before(fx, lastd) if fx else None
        fx1 = _f1[0] if _f1 else (last(fx)[1][0] if fx else None)
        r["fx0"], r["fx1"] = fx0, fx1
        r["fx0_day"] = day_on_or_before(fx, bd) if (fx and bd) else None
        r["fx1_day"] = day_on_or_before(fx, lastd) if fx else None

        k = 1.0 if jp else (fx1 or 0)
        k0 = 1.0 if jp else (fx0 or 0)
        if not k:
            r["skip"] = "ドル円が取れないので円建てにできない"
            rows.append(r); continue

        # ── 取得額（円）: bjpy が最優先＝**実際に出した円**。為替を仮定しない ──
        if bjpy > 0:
            r["cost_jpy"], r["cost_src"] = bjpy, "actual_jpy"
            if not jp and r["cost_px"] and sh:
                r["fx_implied"] = bjpy / (sh * r["cost_px"])   # 逆算した買付時のドル円
        elif k0:
            r["cost_jpy"], r["cost_src"] = sh * r["cost_px"] * k0, "px_x_fx"
        else:
            r["skip"] = "買付日のドル円が取れない＝円建ての取得額が出せない"
            rows.append(r); continue

        r["val_jpy"] = sh * cl_now * k
        r["px_now"] = cl_now
        r["pl_jpy"] = r["val_jpy"] - r["cost_jpy"]
        r["ret_px_jpy"] = r["val_jpy"] / r["cost_jpy"] - 1                # 円建て・価格のみ
        # ── 現地通貨（bpx が実記録なら**厳密**＝証券口座の損益率と一致する）──
        r["ret_px_local"] = (cl_now / r["cost_px"] - 1) if r["cost_px"] else None
        # ── 配当込み: 起点の日が要る。無ければ **出さない**（価格リターンで代用すると
        #    配当のぶんだけ静かに過小に出て、S&P500TR と基準が割れる）──
        if div_f:
            # 価格リターンに**配当の寄与だけ**を掛ける。分母は実際に払った円のまま
            r["ret_tr_local"] = ((cl_now / r["cost_px"]) * div_f - 1) if r["cost_px"] else None
            r["cost_tr_jpy"] = r["cost_jpy"]                              # 同じ円を投じた前提
            r["val_tr_jpy"] = r["val_jpy"] * div_f
            r["ret_tr_jpy"] = r["val_tr_jpy"] / r["cost_tr_jpy"] - 1
        else:
            r["ret_tr_local"] = r["ret_tr_jpy"] = None
            r["cost_tr_jpy"] = r["val_tr_jpy"] = None
            notes.append(f"{t}: 買付日が無いので**配当込み**が出せない（価格ベースだけ）")
        r["fx_ret"] = ((k / k0 - 1) if k0 else None) if not jp else 0.0   # 為替の寄与
        r["days"] = (datetime.date.fromisoformat(lastd) - datetime.date.fromisoformat(bd)).days if bd else None
        # ── 内部矛盾: state.json の `v`（円）と突き合わせる ──────────────
        #   `v` は posValue() の**フォールバック**（sh も px も無いときだけ使う）なので、
        #   sh>0 のこの行では採点にも表示にも使われていない。だが**人が手で入れた数字**なので、
        #   取得額とも評価額とも合わないなら「どちらかが古い／誤り」の合図になる。
        #   ⚠ どちらが正しいかは機械には判らない——**名指しするだけで、勝手に採らない**（ルール7）。
        v = float(p.get("v") or 0)
        if v > 0:
            near_cost = abs(v / r["cost_jpy"] - 1) < 0.02 if r["cost_jpy"] else False
            near_val = abs(v / r["val_jpy"] - 1) < 0.02 if r["val_jpy"] else False
            if not (near_cost or near_val):
                r["v_conflict"] = {"v": round(v), "cost": round(r["cost_jpy"]),
                                   "val": round(r["val_jpy"])}
                notes.append(f"{t}: state.json の v ¥{v:,.0f} が取得額 ¥{r['cost_jpy']:,.0f} とも"
                             f"評価額 ¥{r['val_jpy']:,.0f} とも合わない（どちらが正かは機械には判らない）")
        rows.append(r)

        tot_cost += r["cost_jpy"]; tot_val += r["val_jpy"]
        if r.get("cost_tr_jpy"):
            tot_cost_tr += r["cost_tr_jpy"]; tot_val_tr += r["val_tr_jpy"]

        r["bd_est"] = bool(p.get("bdEst"))
        r["bd_win"] = p.get("bdWin")
        r["_k"], r["_k0"] = k, k0

    # ── ★ 同じ `bd` を持つ行への伝播 ────────────────────────────────────
    #   実測で4社とも `bd=2026-08-05` が同じだった＝**取引ごとの買付日ではなく、
    #   台帳に行をまとめて作った日**。うち3社は実記録の単価と食い違うことが証明できたので、
    #   **その日付そのものが買付日ではない**——同じ日付を持つ残りの行も同じ穴に落ちている。
    #   ⚠ これは「1行の証拠を全社へ広げる」のではなく「その**日付**が記入日だと判った」話。
    #     だから伝播は *同じ bd 文字列を持つ行* に限る（2行以上で共有されているときだけ）。
    bad_bd = {r["bd"] for r in rows if r.get("bd_suspect") and r.get("bd")}
    for b in sorted(bad_bd):
        share = [r for r in rows if r.get("bd") == b]
        if len(share) < 2:
            continue
        for r in share:
            if not r.get("bd_suspect") and not r.get("skip"):
                r["bd_suspect"] = True
                r["bd_suspect_by"] = "batch"
                if r.get("cost_px") and r.get("src") == "actual":
                    r["bd_window"] = r.get("bd_window") or None
                notes.append(f"{r['t']}: 同じ日付 {b} の別の行で「買付日ではない」ことが実証された"
                             "＝この行の bd も台帳の記入日。S&P500 との比較から外す")

    # ── 同じ円を同じ日に S&P500 へ入れていたら ──────────────────────────
    #   ★「**同じ日**に」が成立する行だけを比べる。bd が買付日でない行を混ぜると、
    #     数ヶ月持った銘柄と12日ぶんの指数を比べることになる＝**精度でなく種類の誤り**。
    #     だから比較の合計(`compared`)は指数(`benchmark`)と**必ず同じ集合**で作る。
    for r in rows:
        if r.get("skip"):
            continue
        k, k0 = r.pop("_k", None), r.pop("_k0", None)
        if r.get("bd_suspect") and not r.get("bd_est"):
            r["cmp_out"] = "買付日が判らない（bd が台帳の記入日）＝同じ日で比べられない"
        elif not (bench and r.get("bd") and k0):
            r["cmp_out"] = "買付日か指数か為替が取れない＝同じ日で比べられない"
        else:
            b0 = on_or_before(bench, r["bd"])
            if not b0:
                r["cmp_out"] = "指数にその日が無い"
            else:
                b1 = last(bench)[1][1]
                # 指数はUSD建て。円で買う＝入金時のドル円で換算し、出口のドル円で戻す
                bench_cost += r["cost_jpy"]
                bench_val += r["cost_jpy"] * (b1 / b0[1]) * (k / k0)
                cmp_cost += r["cost_jpy"]
                cmp_val += r["val_jpy"]
                # ★指数は配当込み(^SP500TR)なので、**同じ基準**の保有側も持つ。
                #   価格ベースの保有を配当込みの指数と引き算すると、配当のぶんだけ
                #   保有が構造的に低く出る（「基準の違う二つを割る」型）
                cmp_val_tr += (r.get("val_tr_jpy") or r["val_jpy"])
                # ★想定日なら、窓の両端でも同じ計算をして**答えがどれだけ動くか**を出す。
                #   1点だけ出すと「測った数字」に見えてしまう——動く幅こそがこの行の情報。
                w = r.get("bd_win")
                if w:
                    ends = []
                    # ⚠ **両端だけを見てはいけない**——差は日付に単調でないので、両端が min/max とは
                    #   限らない（実測 IRMD: 両端 -24.5〜-11.2 に対し全候補では -29.8〜-8.3）。
                    #   候補日の正本は estimate_bd が書く `bdWin.days`。無ければ両端で代用する。
                    for d in (w.get("days") or [w.get("first"), w.get("last")]):
                        bx = on_or_before(bench, d) if d else None
                        fxx = on_or_before(fx, d) if (fx and d) else None
                        if bx and fxx and fxx[0]:
                            spv = r["cost_jpy"] * (b1 / bx[1]) * (k / fxx[0])
                            ends.append(r["ret_px_jpy"] - (spv / r["cost_jpy"] - 1))
                    if len(ends) >= 2:
                        r["cmp_range"] = [min(ends), max(ends)]
                        # 合計側の幅も**全候補の中の最良/最悪**で積む（両端ではなく）
                        sp_all = []
                        for d in (w.get("days") or [w["first"], w["last"]]):
                            bx = on_or_before(bench, d); fxx = on_or_before(fx, d) if fx else None
                            if bx and fxx and fxx[0]:
                                sp_all.append(r["cost_jpy"] * (b1 / bx[1]) * (k / fxx[0]))
                        bench_ends[0] += min(sp_all); bench_ends[1] += max(sp_all)
                    else:
                        bench_ends[0] += r["cost_jpy"] * (b1 / b0[1]) * (k / k0)
                        bench_ends[1] += r["cost_jpy"] * (b1 / b0[1]) * (k / k0)
                else:
                    bench_ends[0] += r["cost_jpy"] * (b1 / b0[1]) * (k / k0)
                    bench_ends[1] += r["cost_jpy"] * (b1 / b0[1]) * (k / k0)

    def pack(cost, val, cost_tr=None, val_tr=None):
        if not cost or cost <= 0:
            return None
        o = {"cost_jpy": round(cost), "val_jpy": round(val),
             "pl_jpy": round(val - cost), "ret": val / cost - 1}
        if cost_tr and cost_tr > 0:
            o["ret_tr"] = val_tr / cost_tr - 1
            o["pl_tr_jpy"] = round(val_tr - cost_tr)
        return o

    meas = [r for r in rows if not r.get("skip")]
    span = max([r["days"] for r in meas if r.get("days") is not None
                and not r.get("bd_suspect")], default=None)
    if span is None:      # 信用できる bd が一つも無いときは、あるものから取って印を付ける
        span = max([r["days"] for r in meas if r.get("days") is not None], default=None)
    out = {
        "generated": datetime.date.today().isoformat(),
        "tool": "night/fetch_returns.py",
        "base_ccy": "JPY",
        "source": "Yahoo Finance（close / adjclose）・^SP500TR・JPY=X。鍵不要",
        "note": ("表示専用。Ω・四関門・売却規律・配分のどれにも触れない。"
                 "**すべて円建てに揃えてある**——ドル建てのリターンと円建ての資産を並べると"
                 "「基準の違う二つを割る」型になるため。為替の寄与は別に出している。"),
        "basis": {
            "price": "終値ベース＝証券口座の含み損益と一致する（配当は入らない）",
            "total": "adjclose ベース＝配当再投資込み。**S&P500TR と同じ基準**",
            "benchmark": ("^SP500TR（配当再投資込み）を、各買付日のドル円で円へ直して比較。"
                          "**買付日が判る行だけ**で作り、`compared`（同じ集合の保有側）と必ず対で読む"),
            "cost": ("① bjpy=取得額(円・実際に出した円) ② bpx=平均取得価額(現地通貨) "
                     "③ bd の終値で推定。行ごとに `cost_src` / `src` に書いてある"),
        },
        "compared": pack(cmp_cost, cmp_val),
        "compared_tr": pack(cmp_cost, cmp_val_tr),   # 指数と同じ配当込みの基準

        # 想定日の窓の両端で指数がどうなるか＝**この比較がどれだけ想定に依存しているか**
        "benchmark_range": ([min(bench_ends) / cmp_cost - 1, max(bench_ends) / cmp_cost - 1]
                            if cmp_cost > 0 and bench_ends[0] and bench_ends[1] else None),
        "bench_asof": last(bench)[0] if bench else None,
        "annualized": None,
        "span_days": span,
        "positions": rows,
        "portfolio": pack(tot_cost, tot_val, tot_cost_tr, tot_val_tr),
        "benchmark": pack(bench_cost, bench_val),
        "notes": notes,
        "blind": blind,
    }
    if span is not None and span >= ANNUALIZE_MIN_DAYS:
        out["annualized"] = True
        if any(r.get("bd_est") for r in rows):
            # ⚠ 年数そのものが想定なので、年率は想定の上に想定を重ねた数字になる
            out["annualize_why"] = ("⚠ 保有期間が**想定日から数えた日数**なので、年率も想定の上の数字。"
                                    "取引履歴の日付が入るまでは累積の%のほうを見ること")
    else:
        out["annualized"] = False
        out["annualize_why"] = (f"保有期間が {span} 日＝{ANNUALIZE_MIN_DAYS}日未満なので**年率換算しない**。"
                                "数日の値動きを年率にすると桁が暴れ、数字がある分だけ空欄より有害"
                                "（audit_er_realized / kessan_check_jp と同じ判断）")

    if not meas:
        print("✗ 1社も測れなかった——**書かずに終わる**（空の結果は『損益ゼロ』ではない）")
        for b in blind + notes:
            print("   ", b)
        return 1

    # ── 日次の推移（別ファイル・表示専用）────────────────────────────────
    ser_out = build_series(rows, sers, bench, fx, out.get("compared"),
                             out.get("compared_tr"), out.get("benchmark"))
    for r in rows:
        r.pop("_adj0", None)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if ser_out:
        ser_out["generated"] = out["generated"]
        ser_out["tool"] = "night/fetch_returns.py"
        ser_out["base_ccy"] = "JPY"
        ser_out["note"] = ("日次の推移。**表示専用**——Ω・四関門・売却規律・配分のどれにも触れない。"
                           "終点の式と同じ計算を日付だけ動かして作ってあるので、"
                           "終点は out/returns.json の `compared` と一致する（endpoint_gap で検算）。"
                           "買付日が判らない行は入っていない＝比較の集合と揃えてある。")
        json.dump(ser_out, open(OUT_SERIES, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        g = ser_out.get("endpoint_gap") or {}
        if g and not g.get("ok"):
            notes.append("推移の終点が合計と合わない（"
                         + " / ".join(f"{k} {g[k]:+,}円" for k in ("val", "cost", "tr", "bmk")
                                      if g.get(k) is not None)
                         + "）——推移か合計のどちらかが壊れている")
    else:
        # ⚠ 空で上書きしない。「推移が作れなかった」と「推移がゼロ」は別物（ルール7）
        notes.append("推移が作れなかった（買付日が判る行が2日ぶん揃わない）——"
                     "out/returns_series.json は更新していない")

    if "--json" not in sys.argv:
        pc = out["portfolio"]; bc = out["benchmark"]; cc = out["compared"]
        pct = lambda v: f"{v*100:>+7.2f}%" if v is not None else f"{'——':>8}"
        exit_days = sorted({r.get("asof") for r in rows if r.get("asof")})
        exit_fx = sorted({r.get("fx1_day") for r in rows if r.get("fx1_day")})
        print(f"■ トータルリターン（円建て・{out['generated']} 生成）")
        print(f"  出口（全銘柄で共通）: 株価 {'/'.join(exit_days) or '—'}"
              f"　指数 ^SP500TR {out.get('bench_asof') or '—'}　ドル円 {'/'.join(exit_fx) or '—'}")
        print(f"  {'銘柄':<7}{'入口(想定)':<12}{'株数':>4} {'取得':>10} {'評価':>10} {'損益':>10} "
              f"{'価格%':>8} {'配当込%':>8} {'うち為替':>8}  取得額の出所")
        for r in rows:
            if r.get("skip"):
                print(f"  {r['t']:<7}{'':<12}{'':>4} —— {r['skip']}"); continue
            src = {"actual_jpy": "実記録(円)", "px_x_fx": ""}.get(r.get("cost_src"), "")
            if not src:
                src = {"actual": "実記録(単価)", "est": f"推定({r['bd']}の終値)",
                       "jpy_only": "円のみ"}.get(r.get("src"), "?")
            if r.get("bd_est"):
                w = r.get("bd_win") or {}
                src += f" ⚠想定日({w.get('n','?')}日窓)"
            elif r.get("bd_suspect"):
                src += " ⚠買付日不明"
            print(f"  {r['t']:<7}{(r.get('bd') or '—'):<12}{r['sh']:>4.0f} {r['cost_jpy']:>10,.0f} {r['val_jpy']:>10,.0f} "
                  f"{r['pl_jpy']:>+10,.0f} {pct(r.get('ret_px_jpy'))} {pct(r.get('ret_tr_jpy'))} "
                  f"{pct(r.get('fx_ret'))}  {src}")
        if pc:
            print(f"\n  {'合計':<7}{'':<12}{'':>4} {pc['cost_jpy']:>10,.0f} {pc['val_jpy']:>10,.0f} "
                  f"{pc['pl_jpy']:>+10,.0f} {pct(pc['ret'])} {pct(pc.get('ret_tr'))}"
                  f"   ← 保有ぜんぶ（S&P500と比べられない行も含む）")
        # ── S&P500 との比較は**同じ集合どうし**でしか出さない ──────────────
        out_of = [r for r in rows if r.get("cmp_out")]
        if bc and cc:
            print(f"\n  ── 同じ日・同じ円で比べられる分だけ（{len(rows)-len(out_of)-sum(1 for r in rows if r.get('skip'))}社）──")
            print(f"  {'保有':<7}{'':<12}{'':>4} {cc['cost_jpy']:>10,.0f} {cc['val_jpy']:>10,.0f} "
                  f"{cc['pl_jpy']:>+10,.0f} {pct(cc['ret'])}")
            ct = out.get("compared_tr")
            if ct:
                print(f"  {'保有(配当込)':<7}{'':<8}{'':>4} {ct['cost_jpy']:>10,.0f} {ct['val_jpy']:>10,.0f} "
                      f"{ct['pl_jpy']:>+10,.0f} {pct(ct['ret'])}  ← 指数と同じ基準")
            print(f"  {'S&P500':<7}{'':<12}{'':>4} {bc['cost_jpy']:>10,.0f} {bc['val_jpy']:>10,.0f} "
                  f"{bc['pl_jpy']:>+10,.0f} {pct(bc['ret'])}  ← 同じ円を同じ日に入れていたら")
            # ★差は**同じ基準どうし**（配当込 vs ^SP500TR）を主に出す。
            #   価格ベースの保有を配当込みの指数と引くと、配当のぶんだけ保有が低く出る
            if ct:
                print(f"\n  差（円建て・**配当込どうし**）: {(ct['ret']-bc['ret'])*100:+.2f}pt"
                      f"　／　参考: 価格ベースの保有と引くと {(cc['ret']-bc['ret'])*100:+.2f}pt"
                      "（指数だけ配当が入る＝保有が構造的に低く出る）")
            else:
                print(f"\n  差（円建て）: {(cc['ret']-bc['ret'])*100:+.2f}pt")
            print(f"  ⚠ S&P500 の {bc['ret']*100:+.2f}% は**1本の窓の指数リターンではない**——"
                  f"銘柄ごとに別々の入口から走らせた{len([r for r in rows if not r.get('skip') and not r.get('cmp_out')])}本の"
                  "加重合成（投じた円で重みづけ）")
            br = out.get("benchmark_range")
            nEst = sum(1 for r in rows if r.get("bd_est"))
            if br and nEst:
                # 幅も**同じ基準**（配当込みの保有）から引く。点推定と土俵を揃える
                _b = (ct or cc)["ret"]
                lo = (_b - max(br)) * 100
                hi = (_b - min(br)) * 100
                print(f"  ⚠ うち **{nEst}社は買付日が想定**。候補日のどこを取るかで差は "
                      f"**{lo:+.2f}〜{hi:+.2f}pt** に開く")
                print("     ＝この一つの数字は「測った」ではなく「置いた前提の上の数字」。"
                      "取引履歴の日付を入れれば確定する")
            for r in rows:
                if r.get("cmp_range") and abs(r["cmp_range"][1] - r["cmp_range"][0]) > 0.05:
                    print(f"       {r['t']:<6} 単独では {r['cmp_range'][0]*100:+.1f}〜"
                          f"{r['cmp_range'][1]*100:+.1f}pt ＝想定が答えを支配している")
        else:
            print("\n  ✗ **S&P500 との比較が1社も作れない**——「同じ円を同じ日に」の"
                  "『同じ日』が判らないため。買付日(bd)を入れれば出る")
        if out_of:
            print(f"\n  ⚠ 比較から外した {len(out_of)}社:")
            for r in out_of:
                w = r.get("bd_window")
                hint = (f"（終値がその水準だったのは {w['first']}〜{w['last']}"
                        f"・{w['n']}日）" if w else "")
                print(f"      {r['t']:<6} {r['cmp_out']}{hint}")
        if not out["annualized"]:
            print(f"\n  ⚠ {out['annualize_why']}")
        conf = [r for r in rows if r.get("v_conflict")]
        if conf:
            print(f"\n  ⚠ state.json の v と食い違う行 {len(conf)}件"
                  "（v は sh>0 のとき採点にも表示にも使われないが、手入力の数字なので合図として出す）")
        for n in notes:
            print(f"  ⚠ {n}")
        for b in blind:
            print(f"  ✗ 読めなかった入力: {b}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
