#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""買付日(bd)を取得単価から**想定**する（2026-08-18新設・ユーザー指示「かいつけ日は想定日でいい」）

出力: state.json の `bd` / `bdEst` / `bdWin`。**表示専用の系にしか効かない**——
Ω・採点式・四関門・堀の関門・売却規律・配分はどれもこの欄を読まない。

■ なぜ「想定」と明示するのか
  取引履歴が無いので、判るのは「**終値がその水準だった日**」まで。しかも平均取得価額は
  複数回買付の平均でありうるので、**一致する日が実際の買付日とは限らない**
  （実測: MSFT は 2株@¥59,091 ＋ 1株@¥72,333 の合算で、2×59,091+72,333=190,515 とぴったり合う
   ＝単一の買付日は存在しない）。だから `bdEst:true` を必ず立て、
  **S&P500 との比較は「想定」と札を付けたまま出す**。

■ 二つの制約で挟む（ここが肝）
  A) 終値 ≈ bpx（平均取得価額・現地通貨）
  B) 終値 × ドル円 ≈ bjpy ÷ 株数（実際に出した円）
  **A と B が同じ日で交わるなら、独立な二系列が一致したということ**——偶然そうなる確率は低い。
  実測で MSFT は36日→**3日**、RMD は18日→**2日**まで狭まった。片方しか無ければ窓は広いままで、
  そのぶん答えは想定に依存する（`--report` が窓の両端で答えがどう動くかを出す）。

■ ユーザーの申告で窓を切る（`bdAfter` / `bdBefore`）
  ★2026-08-18 に **MSFT の想定日を 2024-04-26 と置いて外した**——ユーザーの
  「マイクロソフトは2026だよ？」で判明。実測で **S&P500 との差が −39.7pt → +4.1pt ＝33pt の誤り**。
  終値とドル円が2024年にも同じ水準を通っていたので、**平均が偶然その日に一致していた**。
  ⇒ 人が知っている範囲は `bdAfter`/`bdBefore` に書いて窓を切る。**推測より申告が強い。**

■ 複数回買付は内訳で解く（`bdLots`）
  平均取得価額は複数回買付の平均でありうるので、**単一の日が存在しないことがある**。
  実測 MSFT は 2株@¥59,091 ＋ 1株@¥72,333 ＝ ¥190,515 の2ロット（合計がぴったり合う）。
  `bdLots` があれば **各ロットを別々に指数へ当てて**から、同じ結果を出す「等価な単一日」を逆算する
  （台帳は1銘柄1行なので）。3つの制約——ロットごとの円/株・USDの平均取得価額・円の合計——を
  同時に満たす組だけを採るので、**過剰決定＝解が出れば強い**。

■ 想定日は**窓の中央値**にする（最も偏りが少ない・決定的）
  ⚠ 直感に反するが「最新の一致日」を採ってはいけない——保有期間が最短になる＝
  **S&P500 の複利期間も最短になる＝自分に一番有利な仮定**を選ぶことになる。
  実測 RMD: 最新なら S&P500 +1.1%（差 +10.4pt）／最古なら +77.0%（差 −65.5pt）＝**76pt の開き**。

使い方:
  python3 night/estimate_bd.py            測るだけ（窓と感度を出す）
  python3 night/estimate_bd.py --write    state.json へ書く
"""
import datetime
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST = os.path.join(ROOT, "state.json")
TOL = 0.005          # ±0.5%
_spec = importlib.util.spec_from_file_location("fr", os.path.join(ROOT, "night", "fetch_returns.py"))
fr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fr)   # 価格の採り方を再実装しない


def solve_lots(ser, fxs, bench, lots, bpx, bjpy, ds):
    """複数回買付を内訳から解き、(窓, 説明, 想定日, 置き換えの誤差pt) を返す。

    各ロットを**別々に**指数へ当ててから、同じ指数の結果を出す単一日を逆算する
    （台帳は1銘柄1行なので）。制約は3つ同時＝過剰決定なので、解が出れば強い。
    """
    tot_sh = sum(l["sh"] for l in lots)
    fx1 = fr.last(fxs)[1][0]; b1 = fr.last(bench)[1][1]
    ok = []
    for l in lots:                       # ロットごとに「円/株が一致する日」を先に絞る
        cand = []
        for d in ds:
            f = fr.on_or_before(fxs, d)
            per = l["jpy"] / l["sh"]
            if not f or abs(ser[d][0] * f[0] - per) / per >= 0.01:
                continue
            # ★そのロットだけ現地通貨の平均取得価額が判っていれば、それも制約に足す
            if l.get("usd") and abs(ser[d][0] / l["usd"] - 1) >= 0.01:
                continue
            cand.append(d)
        l["_d"] = cand
        if not l["_d"]:
            return [], "内訳のどれかが窓に無い", None, None
    def walk(i, chosen):
        if i == len(lots):
            usd = sum(l["sh"] * ser[d][0] for l, d in zip(lots, chosen)) / tot_sh
            yen = sum(l["sh"] * ser[d][0] * fr.on_or_before(fxs, d)[0] for l, d in zip(lots, chosen))
            if bpx and abs(usd / bpx - 1) > 0.01: return
            if bjpy and abs(yen / bjpy - 1) > 0.01: return
            if len(set(chosen)) < len(chosen) and len({id(l) for l in lots}) > 1:
                pass   # 同じ日に複数ロットは有りうる（同日に別口座で買う）ので弾かない
            sp = sum(l["sh"] * ser[d][0] * fr.on_or_before(fxs, d)[0]
                     * (b1 / fr.on_or_before(bench, d)[1]) * (fx1 / fr.on_or_before(fxs, d)[0])
                     for l, d in zip(lots, chosen))
            ok.append((sp / yen, list(chosen)))
            return
        for d in lots[i]["_d"]:
            walk(i + 1, chosen + [d])
    walk(0, [])
    if not ok:
        return [], "内訳の組が3つの制約を同時に満たさない", None, None
    # 各組の「等価な単一日」＝同じ指数の伸びを出す日
    eq = []
    for mult, _ in ok:
        best = min(ds, key=lambda d: abs((b1 / fr.on_or_before(bench, d)[1])
                                         * (fx1 / fr.on_or_before(fxs, d)[0]) - mult))
        eq.append((mult, best))
    # ⚠ 窓は重複を除いて出す（表示のため）が、**中央値は「組」の中央値**で採る。
    #   重複を除いてから中央を取ると、同じ等価日に落ちる組の重みが消えて答えがずれる
    #   （実測: 本当の3ロット計算の中央 +14.5pt に対し、重複除去だと +12.9pt ＝1.6pt の差）。
    eq.sort()
    hint = eq[len(eq) // 2][1]
    # ★置き換えの誤差を測って一緒に返す。等価日は「一番近い営業日」なので厳密には一致せず、
    #   台帳が1銘柄1行である以上この残差は消せない。**消せないものは黙らせずに出す**
    eqerr = max(abs((b1 / fr.on_or_before(bench, d)[1])
                    * (fx1 / fr.on_or_before(fxs, d)[0]) - m) for m, d in eq)
    return sorted({d for _, d in eq}), \
        f"内訳{len(lots)}ロットを別々に指数へ当てた等価日（{len(ok)}通りの組）", hint, eqerr


def candidates(ser, fxs, sh, bpx, bjpy):
    """(窓, 使った制約) を返す。A∩B が空でないときだけ二制約と名乗る"""
    ds = sorted(ser)
    jpsh = (bjpy / sh) if (bjpy and sh) else None
    A = [d for d in ds if bpx and abs(ser[d][0] - bpx) / bpx < TOL] if bpx else []
    B = []
    if jpsh:
        for d in ds:
            f = fr.on_or_before(fxs, d)
            if f and abs(ser[d][0] * f[0] - jpsh) / jpsh < TOL:
                B.append(d)
    both = sorted(set(A) & set(B))
    if both:
        return both, "A∩B（終値とドル円の両方が一致）", None, None
    if A:
        return A, "A（終値のみ）", None, None
    if B:
        return B, "B（円の取得額のみ）", None, None
    return [], "該当なし", None, None


def main():
    write = "--write" in sys.argv
    st = json.load(open(ST, encoding="utf-8"))
    pf = json.loads(st["data"]["pf:portfolio"])
    t1 = int(time.time()); t0 = t1 - 86400 * 1200
    fxs = fr.yahoo("JPY=X", t0, t1)
    bench = fr.yahoo("^SP500TR", t0, t1)
    if not fxs or not bench:
        print("✗ ドル円か指数が取れない——**書かずに終わる**"); return 1
    fx1 = fr.last(fxs)[1][0]; b1 = fr.last(bench)[1][1]

    print("■ 買付日の想定（night/estimate_bd.py）")
    print(f"  {'銘柄':<6}{'想定日':<12}{'窓':<26}{'制約':<26}{'S&P500との差':>26}")
    n = 0
    for p in pf["positions"]:
        t = p["t"]; sh = float(p.get("sh") or 0)
        bpx = float(p.get("bpx") or 0); bjpy = float(p.get("bjpy") or 0)
        if not sh or (not bpx and not bjpy):
            print(f"  {t:<6}—— 取得単価も取得額も無いので想定できない"); continue
        ser = fr.yahoo(t if not t[:1].isdigit() else f"{t}.T", t0, t1)
        if not ser:
            print(f"  {t:<6}—— 価格が取れない"); continue
        # ★人の申告で窓を切る（推測より申告が強い）
        lo, hi = p.get("bdAfter"), p.get("bdBefore")
        if lo or hi:
            ser = {d: v for d, v in ser.items() if (not lo or d >= lo) and (not hi or d <= hi)}
            if not ser:
                print(f"  {t:<6}—— 申告の範囲に価格が無い"); continue
        lots = p.get("bdLots")
        if lots:
            win, how, hint, eqerr = solve_lots(ser, fxs, bench, [dict(l) for l in lots],
                                        bpx, bjpy, sorted(ser))
        else:
            win, how, hint, eqerr = candidates(ser, fxs, sh, bpx, bjpy)
        if not win:
            print(f"  {t:<6}—— 終値がその水準だった日が見つからない（{how}）"); continue
        cost = bjpy if bjpy else sh * bpx * fr.on_or_before(fxs, win[len(win) // 2])[0]
        val = sh * fr.last(ser)[1][0] * fx1
        # ⚠ **窓の両端だけを見てはいけない**——S&P500 との差は日付に対して単調ではないので、
        #   両端が最小・最大とは限らない（実測で中央値の答えが「両端の幅」の外に出た）。
        #   候補**全部**を計算して、幅は min/max、想定日は**答えが中央値になる日**にする。
        scored = []
        for d in win:
            b0 = fr.on_or_before(bench, d); f0 = fr.on_or_before(fxs, d)
            if not b0 or not f0:
                continue
            sp = cost * (b1 / b0[1]) * (fx1 / f0[0])
            scored.append(((val / cost - 1) - (sp / cost - 1), d))
        if not scored:
            print(f"  {t:<6}—— 指数か為替が窓に無い"); continue
        scored.sort()
        # 内訳がある行は**組の中央値**（hint）を使う。無ければ候補日の中で答えが中央になる日
        pick = hint or scored[len(scored) // 2][1]
        lo, hi = scored[0][0], scored[-1][0]
        # ★出す中央値は「採った日 pick の答え」。hint を採ったのに scored の中央を
        #   表示すると、直したはずの重みのずれが画面にだけ残る（v9.9.65 の同型）
        mid = next((v for v, d in scored if d == pick), scored[len(scored) // 2][0])
        span = f"{win[0]}〜{win[-1]}({len(win)}日)"
        err = f"±{eqerr*100:.1f}" if eqerr and eqerr * 100 >= 0.05 else ""
        rng = f"{mid*100:+.1f}{err}pt（幅 {lo*100:+.1f}〜{hi*100:+.1f}）"
        print(f"  {t:<6}{pick:<12}{span:<26}{how:<26}{rng:>26}")
        if write:
            p["bd"] = pick; p["bdEst"] = True
            # 候補日を**全部**持たせる——幅を出すのは fetch_returns 側の仕事だが、
            # 「どの日が候補か」の正本はここ一つ（v9.9.65: 二重に持たない）。両端だけだと
            # 答えが日付に単調でないぶんを取りこぼす（実測で IRMD の幅が -24.5〜-11.2 → -29.8〜-8.3）
            p["bdWin"] = {"first": win[0], "last": win[-1], "n": len(win), "how": how,
                          "days": win}
            if p.get("bdAfter") or p.get("bdBefore"):
                p["bdWin"]["bound"] = f"{p.get('bdAfter') or ''}〜{p.get('bdBefore') or ''}（申告）"
            n += 1
    if write:
        st["data"]["pf:portfolio"] = json.dumps(pf, ensure_ascii=False, separators=(",", ":"))
        st["savedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        open(ST, "w", encoding="utf-8").write(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
        print(f"\n→ state.json に {n}件の想定日を書いた（bdEst:true・取引履歴が判ったら上書きすること）")
    else:
        print("\n（--write で state.json へ書く）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
