#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_derived_judgment.py — 判断項目のうち**規約が機械導出を定めている3欄**(p1/p3/f5)を片付ける（2026-07-29新設）

なぜ要るか:
  night/audit_evidence.py の実測で、根拠の無い判断項目の上位はこの3つに集中していた——
    p1 180社(56.8%) / p3 171社(53.9%) / f5 159社(50.2%)
  ところがこの3欄は**審査官の主観ではなく、規約が入力からの写像を定めている**:

  ・p3 財務頑健 ＝ nde の表。門(index.html)はこう書く:
      const p3v=(nn('p3')!=null)?n('p3'):(()=>{const dv=nn('nde');if(dv==null)return 70;
                                               return dv<0?95:dv<1?85:dv<2.5?70:50;})();
    審査プロトコルも『**ndeを埋めれば空欄可**＝門が同表で機械導出。逸脱評価時のみ値+根拠』と明記。
  ・f5 耐陳腐化 ＝ disrupt の表。同じく門が導出し、プロトコルも『disruptを埋めれば空欄可』。
  ・p1 ROIC安定性 ＝ 5年ROICのσ。門は導出しないが、刻みは σ<3pt→90 / <6pt→80 / σ8pt級→65 /
    二桁→50 と**完全に機械的**で、σは原本(XBRL)から出せる。

  つまりこの3欄に「原本の根拠」を書き足すのは筋が違う。正しい姿は:
    p3/f5 … 導出値と同じなら**空欄にする**（値を消す）。門が nde/disrupt から出す。
             違うなら**逸脱評価**なので、値と根拠を審査官が書く＝作業リストへ。
    p1  … σを計算して刻みに落とし、**系列とσの実額を根拠に刻む**（provenance=machine）。
             台帳の値と食い違うなら書き換えず作業リストへ（審査官の判断のほうが強い）。

  **空欄化は「証拠を消す」のではなく「規約どおりに戻す」**——値が入っていると門は
  それを逸脱評価として尊重してしまい、ndeを直しても p3 が追随しなくなる（陳腐化する）。

p1のROIC系列は採取器と同じ門式で出す:
  投下資本 = 自己資本 + 有利子負債 − のれん − 無形（直近5年）、NOPAT = 営業利益×(1−実効税率)。
  有利子負債タグが無い年・ICが自己資本の2割未満の年は**飛ばす**（絶対のルール7）。3年未満ならσを出さない。

使い方:
  python3 night/fill_derived_judgment.py             判定のみ（書き換えない）
  python3 night/fill_derived_judgment.py --write     空欄化と根拠の刻みを実行
  python3 night/fill_derived_judgment.py --p1        p1だけ（SECを叩くので遅い）
  python3 night/fill_derived_judgment.py --p3f5      p3/f5だけ（SEC不要・速い）
日本株(コード始まり)は p3/f5 のみ対象（p1のROIC系列はEDINET経路のため）。

■ 初回実測（2026-07-29）
  p3/f5: 導出値と一致した **147欄を空欄へ戻した**（Ωは1社も動かない＝門が同じ値を導出するので当然）。
         残る198欄は逸脱評価。方向を測ると **f5は80欄中74欄が規約より辛い**（平均 −11.3pt）、
         p3は103欄中63欄が辛い（平均 −4.3pt）。台帳は規約より保守的に振れている。
         いずれも根拠が無いので、埋めるか空欄へ戻すかは審査官の作業（値を勝手に動かさない）。

  p1: **規約そのものが高ROIC企業で機能していなかった**ことがここで判り、v9.9.50 で直した。
      旧刻みは σ<3pt→90 / <6pt→80 / σ8pt級→65 / 二桁→50 と**絶対の百分点**で切っており、
      これは ROIC が 10-25% の帯を想定した目盛り。ROIC が 50-130% ある会社では σ が必ず二桁になり、
      **不安定さではなく ROIC の絶対水準を測っていた**（V: ROIC 76-138% → σ21.5pt → 刻み50）。
      → **v9.9.50（2026-07-29 ユーザー指示）で変動係数(σ÷平均)へ変更**。刻みは上の p1_of が唯一の実装。
      影の計測 night/shadow_p1_cv.py の実測: ROIC平均40%超の65社のうち絶対σが最低の50を返すのは
      **44社→8社**へ減り構造的な誤判定が解消。一方で **Ωが動くのは91社・平均+0.02pt・投下可の出入りは0社**
      （p1の実効ウェイトは .30×.40×.35≒4.2%）。**規約が正しくなって判断が動かない＝較正の理想形**。
"""
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
OUT = os.path.join(BASE, "out")


def p3_of(nde):
    """門の p3v と同じ表。nde が無ければ導出できない(門は70で裁く)"""
    if nde is None:
        return None
    return 95 if nde < 0 else 85 if nde < 1 else 70 if nde < 2.5 else 50


def f5_of(disrupt):
    return {"threat": 45, "unsettled": 65}.get(disrupt or "settled", 85)


def p1_of(cv):
    """審査プロトコルの刻み（v9.9.50・2026-07-29ユーザー指示で**変動係数**へ変更）:
       変動係数 CV = σ ÷ 平均（%）で <15%→90 / <30%→80 / <50%→65 / 以上→50。

       旧刻みは**絶対の百分点**(σ<3/6/10pt)で、ROIC 10-25%帯を想定した目盛りだった。
       ROICが50-130%ある会社は機械的にσが二桁になり、**不安定さではなくROICの絶対水準**を
       測っていた（実測: ROIC平均40%超の65社のうち44社が最低の50判定→変動係数では8社）。
       **この関数がp1の刻みの唯一の実装**。night/shadow_p1_cv.py もこれを呼ぶ（二重正本を作らない）。"""
    return 90 if cv < 15 else 80 if cv < 30 else 65 if cv < 50 else 50


def roic_series(t):
    """採取器と同じ門式で直近5年ののれん・無形除外ROIC系列を出す。(系列, 説明) or (None, 理由)"""
    import hachimon_fetch as H
    f = H.facts_of(H.cik_of(t))
    S = {k: H.series(f, H.TAGS[k])[0] for k in ("eq", "gw", "intan", "op", "ni", "tax")}
    dl = H.series_sum(f, H.TAGS["debtL"], "LongTermDebt")[0]
    ds = H.series_sum(f, H.TAGS["debtS"], "DebtCurrent")[0]
    out, skip = [], []
    for y in sorted(S["op"])[-5:]:
        if not all(y in S[k] for k in ("ni", "eq")):
            skip.append(f"{y}:純利益/自己資本タグ不在")
            continue
        if not ((y in dl) or (y in ds)):
            skip.append(f"{y}:有利子負債タグ不在")           # ルール7: 0と読まない
            continue
        tax = max(0.0, min(0.5, 1 - S["ni"][y] / max(S["ni"][y] + S["tax"].get(y, 0), 1)))
        ic = S["eq"][y] + dl.get(y, 0) + ds.get(y, 0) - S["gw"].get(y, 0) - S["intan"].get(y, 0)
        if ic <= 0 or ic < 0.20 * max(S["eq"][y], 1):
            skip.append(f"{y}:IC が自己資本の2割未満＝分母縮退")   # ルール7(b)
            continue
        out.append((y, S["op"][y] * (1 - tax) / ic * 100))
    if len(out) < 3:
        return None, f"門式で算出できた年が{len(out)}年しかない（{' / '.join(skip) or 'タグ不足'}）"
    return out, " / ".join(skip)


def main():
    write = "--write" in sys.argv
    only_p1 = "--p1" in sys.argv
    only_p3f5 = "--p3f5" in sys.argv
    do_p1 = not only_p3f5
    do_p3f5 = not only_p1

    files = sorted(f for f in os.listdir(OUT) if f.endswith("_gate_pack.json"))
    n_blank = n_dev = n_p1ok = n_p1bad = n_p1na = 0
    dev, p1bad = [], []

    for fn in files:
        t = fn.split("_gate_pack")[0]
        p = os.path.join(OUT, fn)
        d = json.load(open(p, encoding="utf-8"))
        m = d.setdefault("_meta", {})
        ev = m.setdefault("evidence", {})
        nu = m.setdefault("nulls", {})
        changed = False

        # ---- p3 / f5: 導出値と同じなら空欄へ戻す。違えば逸脱評価＝作業リスト ----
        if do_p3f5:
            for k, got, src, tbl in (
                ("p3", p3_of(d.get("nde") if isinstance(d.get("nde"), (int, float)) else None),
                 f"nde={d.get('nde')}", "純現金→95 / <1→85 / <2.5→70 / 以上→50"),
                ("f5", f5_of(d.get("disrupt")), f"disrupt={d.get('disrupt')!r}",
                 "settled→85 / unsettled→65 / threat→45"),
            ):
                v = d.get(k)
                if not isinstance(v, (int, float)) or got is None:
                    continue
                if abs(v - got) < 0.5:
                    if ev.get(k):                     # 根拠つきで置かれているなら触らない
                        continue
                    d[k] = None
                    nu[k] = (f"【2026-07-29】規約どおり空欄へ戻した。{k} は門が {src} から同表で導出する"
                             f"（{tbl}）。台帳にあった {v:g} は導出値と一致していたので、値を置いておく意味が無い"
                             f"——むしろ値が残っていると門はそれを『逸脱評価』として尊重し、"
                             f"{src.split('=')[0]} を直しても {k} が追随しなくなる（陳腐化する）。"
                             f"審査プロトコル『{src.split('=')[0]}を埋めれば空欄可＝門が機械導出』。")
                    n_blank += 1
                    changed = True
                else:
                    dev.append((t, k, v, got, src))
                    n_dev += 1

        # ---- p1: ROIC 5年σ から刻みを出し、一致すれば根拠を刻む ----
        if do_p1 and not t[0].isdigit() and isinstance(d.get("p1"), (int, float)) and not ev.get("p1"):
            try:
                ser, why = roic_series(t)
            except (Exception, SystemExit):
                ser, why = None, "SEC取得失敗"
            if ser is None:
                n_p1na += 1
                nu["p1_note"] = f"【2026-07-29】p1の根拠を機械で刻めなかった: {why}"
                changed = True
            else:
                vals = [x[1] for x in ser]
                sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
                mean = statistics.mean(vals)
                if mean <= 0:
                    n_p1na += 1
                    continue
                cv = sd / mean * 100
                got = p1_of(cv)
                txt = " / ".join(f"{y} {v:.1f}%" for y, v in ser)
                if abs(d["p1"] - got) < 0.5:
                    ev["p1"] = (f"【2026-07-29 機械算出・変動係数刻み(v9.9.50)】ROIC安定性＝のれん・無形除外ROIC"
                                f"{len(ser)}年系列の**変動係数(σ÷平均)**。"
                                f"系列: {txt} → 平均{mean:.1f}% / σ{sd:.1f}pt / **CV={cv:.1f}%** "
                                f"→ 刻み(CV<15→90 / <30→80 / <50→65 / 以上→50)で **{got}**。"
                                f"投下資本 = 自己資本 + 有利子負債 − のれん − 無形（門式）。"
                                + (f" 除外年: {why}。" if why else "")
                                + "出典: SEC XBRL companyfacts。")
                    m.setdefault("provenance", {})["p1"] = "machine"
                    n_p1ok += 1
                    changed = True
                else:
                    p1bad.append((t, d["p1"], got, sd, txt))
                    n_p1bad += 1

        if changed and write:
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if do_p3f5:
        print(f"■ p3/f5: 導出値と一致 → 空欄へ戻す **{n_blank}欄**")
        print(f"■ p3/f5: 導出値と食い違う（逸脱評価＝値と根拠が要る） **{n_dev}欄**")
        for t, k, v, got, src in sorted(dev)[:40]:
            print(f"    {t:7s} {k}={v:g} だが {src} からの導出は {got}")
        if len(dev) > 40:
            print(f"    …ほか {len(dev)-40}件")
    if do_p1:
        print(f"\n■ p1: σから再現でき根拠を刻んだ **{n_p1ok}社** / 台帳と食い違う {n_p1bad}社 / 算出不能 {n_p1na}社")
        for t, v, got, sd, txt in sorted(p1bad, key=lambda x: -abs(x[1]-x[2]))[:25]:
            print(f"    {t:7s} 台帳 p1={v:g} / σ={sd:.1f}pt から出る刻みは {got}   [{txt}]")
        if len(p1bad) > 25:
            print(f"    …ほか {len(p1bad)-25}社")
    print("\n" + ("→ 書き換え済み。`node night/score_all.js` で誰がどう動いたかを実測すること。"
                  if write else "※--write で実行（p3/f5の空欄化と p1 の根拠刻み）"))
    print("※食い違いは書き換えない——審査官が原本で判断して置いた値のほうが機械より強い（作業リスト）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
