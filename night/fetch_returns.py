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

■ 取得単価（絶対のルール7 —— 欠測を勝手に埋めない）
  `bpx`（買付単価）があれば src="actual"。無ければ **買付日の終値**で src="est" と明示する。
  `bd` も無ければ **測れない**（null）——推測の数字は出さない。
  ⚠ est は「その日の終値」であって「実際に約定した値」ではない。手数料もスプレッドも入らない。

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


def last(series):
    k = max(series)
    return k, series[k]


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
    t0 = int(datetime.datetime.strptime(start, "%Y-%m-%d").timestamp()) - 86400 * 10
    t1 = int(time.time())

    fx = yahoo(FX, t0, t1)
    bench = yahoo(BENCH, t0, t1)
    blind = []
    if not fx:
        blind.append(f"{FX}（ドル円）が取れない")
    if not bench:
        blind.append(f"{BENCH}（S&P500トータルリターン指数）が取れない")

    rows, notes = [], []
    tot_cost = tot_val = tot_cost_tr = tot_val_tr = 0.0
    bench_cost = bench_val = 0.0

    for p in positions:
        t = p["t"]
        jp = (p.get("ccy") == "JPY") or t[:1].isdigit()
        sym = f"{t}.T" if jp else t
        sh = float(p.get("sh") or 0)
        bd = p.get("bd")
        ser = yahoo(sym, t0, t1)
        r = {"t": t, "nm": p.get("nm") or t, "ccy": "JPY" if jp else "USD",
             "sh": sh, "bd": bd}
        if not ser:
            r["skip"] = "Yahooで価格が取れない"
            rows.append(r); notes.append(f"{t}: 価格が取れない"); continue

        lastd, (cl_now, aj_now) = last(ser)
        r["asof"] = lastd
        # ── 取得単価 ────────────────────────────────────────────────
        bpx = float(p.get("bpx") or 0)
        at_bd = on_or_before(ser, bd) if bd else None
        if bpx > 0:
            r["cost_px"], r["src"] = bpx, "actual"
        elif at_bd:
            r["cost_px"], r["src"] = at_bd[0], "est"
            notes.append(f"{t}: 買付単価が未記録——{bd}の終値で推定")
        else:
            r["skip"] = "買付単価も買付日も無い＝取得額が測れない"
            rows.append(r); continue
        # 配当込みの起点は adjclose 側で取る（指数と基準を揃えるため）
        aj_bd = at_bd[1] if at_bd else r["cost_px"]
        cl_bd = at_bd[0] if at_bd else r["cost_px"]
        # 実記録の bpx がある場合、adjclose 起点は bpx を同じ比率でずらす
        adj0 = r["cost_px"] * (aj_bd / cl_bd) if cl_bd else r["cost_px"]

        fx0 = on_or_before(fx, bd)[0] if (fx and bd and on_or_before(fx, bd)) else None
        fx1 = last(fx)[1][0] if fx else None
        r["fx0"], r["fx1"] = fx0, fx1

        k = 1.0 if jp else (fx1 or 0)
        k0 = 1.0 if jp else (fx0 or 0)
        if not k or not k0:
            r["skip"] = "ドル円が取れないので円建てにできない"
            rows.append(r); continue

        r["cost_jpy"] = sh * r["cost_px"] * k0
        r["val_jpy"] = sh * cl_now * k
        r["cost_tr_jpy"] = sh * adj0 * k0
        r["val_tr_jpy"] = sh * aj_now * k
        r["px_now"] = cl_now
        # ── リターン ──────────────────────────────────────────────
        r["ret_px_local"] = cl_now / r["cost_px"] - 1                    # 現地通貨・価格のみ
        r["ret_tr_local"] = aj_now / adj0 - 1                            # 現地通貨・配当込み
        r["ret_px_jpy"] = r["val_jpy"] / r["cost_jpy"] - 1                # 円建て・価格のみ
        r["ret_tr_jpy"] = r["val_tr_jpy"] / r["cost_tr_jpy"] - 1          # 円建て・配当込み
        r["fx_ret"] = (k / k0 - 1) if not jp else 0.0                     # 為替の寄与
        r["pl_jpy"] = r["val_jpy"] - r["cost_jpy"]
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
        tot_cost_tr += r["cost_tr_jpy"]; tot_val_tr += r["val_tr_jpy"]

        # ── 同じ円を同じ日に S&P500 へ入れていたら ──────────────────
        if bench and bd:
            b0 = on_or_before(bench, bd)
            if b0:
                b1 = last(bench)[1][1]
                # 指数はUSD建て。円で買う＝入金時のドル円で換算し、出口のドル円で戻す
                bench_cost += r["cost_jpy"]
                bench_val += r["cost_jpy"] * (b1 / b0[1]) * (k / k0)

    def pack(cost, val, cost_tr=None, val_tr=None):
        if cost <= 0:
            return None
        o = {"cost_jpy": round(cost), "val_jpy": round(val),
             "pl_jpy": round(val - cost), "ret": val / cost - 1}
        if cost_tr and cost_tr > 0:
            o["ret_tr"] = val_tr / cost_tr - 1
            o["pl_tr_jpy"] = round(val_tr - cost_tr)
        return o

    meas = [r for r in rows if not r.get("skip")]
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
            "benchmark": "^SP500TR（配当再投資込み）を、各買付日のドル円で円へ直して比較",
        },
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

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if "--json" not in sys.argv:
        pc = out["portfolio"]; bc = out["benchmark"]
        print(f"■ トータルリターン（円建て・{out['generated']}）  起点 {start}"
              + (f"・{span}日" if span is not None else ""))
        print(f"  {'銘柄':<7}{'株数':>4} {'取得':>10} {'評価':>10} {'損益':>10} "
              f"{'価格%':>8} {'配当込%':>8} {'うち為替':>8}  取得単価")
        for r in rows:
            if r.get("skip"):
                print(f"  {r['t']:<7}{'':>4} —— {r['skip']}"); continue
            print(f"  {r['t']:<7}{r['sh']:>4.0f} {r['cost_jpy']:>10,.0f} {r['val_jpy']:>10,.0f} "
                  f"{r['pl_jpy']:>+10,.0f} {r['ret_px_jpy']*100:>+7.2f}% {r['ret_tr_jpy']*100:>+7.2f}% "
                  f"{r['fx_ret']*100:>+7.2f}%  "
                  f"{'実記録' if r['src']=='actual' else '推定(' + str(r['bd']) + 'の終値)'}")
        if pc:
            print(f"\n  {'合計':<7}{'':>4} {pc['cost_jpy']:>10,.0f} {pc['val_jpy']:>10,.0f} "
                  f"{pc['pl_jpy']:>+10,.0f} {pc['ret']*100:>+7.2f}% "
                  f"{pc.get('ret_tr',0)*100:>+7.2f}%")
        if bc:
            print(f"  {'S&P500':<7}{'':>4} {bc['cost_jpy']:>10,.0f} {bc['val_jpy']:>10,.0f} "
                  f"{bc['pl_jpy']:>+10,.0f} {bc['ret']*100:>+7.2f}%  ← 同じ円を同じ日に入れていたら")
            if pc:
                print(f"\n  差（配当込み・円建て）: {(pc.get('ret_tr', pc['ret'])-bc['ret'])*100:+.2f}pt")
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
