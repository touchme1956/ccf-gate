# night/retro_mcap.py — 歴史検証の「穴」を埋める: asof時点の**時価総額**（2026-09-20新設）
#
# なぜ要るか:
#   この台帳が使ってきた規模の物差しは一貫して**売上(rev)**で、
#   `grep -l mcap out/retro_*.json` は **0件**＝時価総額で測った歴史検証は一件も無い。
#   一方 v9.9.146/147 の配分（城の目標ウェイト）は**時価総額Tier**で決まる。
#   ＝配分を決めている当の物差しが、歴史で一度も検定されていない。
#
# 作り方（新しい採取を書かない・v9.9.65）:
#   `retro_per_asof.py` の annual_entries / latest_before / NI_TAGS / SH_TAGS を **import する**。
#   px（asof年7月頭の板の値・分割復元済）は在庫 out/retro_per_{asof}_all.json に残っているので
#   Yahoo は叩かない。
#
# ★★初版の検査は恒等式だった（2026-09-20・自分で踏んで是正）:
#   初版は「mcap は (A) px×sh と (B) per×ni の二経路で出るから、一致を要求すれば検算になる」
#   としたが、**per はその px と sh と ni から作られている**ので
#   B = per×ni = (px·sh/ni)·ni ≡ A ＝ **恒等的に一致する**。705/705 が通り max gap 0.0018 という
#   「強い検証」に見えたが、**構造的に保証されていただけ**で何も検証していなかった。
#   ⇒ 本物の検算は **独立な出所どうし**でしかできない。そこで株数を二つ採る:
#     sh_wa  = WeightedAverageNumberOfDilutedShares（損益計算書の分母・per と同じ基準）
#     sh_eop = dei:EntityCommonStockSharesOutstanding（表紙の実株数・提出日時点）
#   この二つは別の場所から来るので**食い違えば本物の異常**（系列の途切れ・ADR比の混線）。
#   実測（±10%以内で一致）: **2018 621/705(88%) ／ 2013 608/703(86%)**＝独立な二源が概ね一致する。
#   ★食い違いは3種類あって、扱いを分けないと片方向に選別が入る:
#     (i) 壊れている —— CLX eop=1.3e14株 / DIOD 4.6e10 / CTA-PB=100 / CROX=8（dei の単位・桁事故）
#         → 比が [0.2,5] の外なら eop を捨てる
#     (ii) **eop のほうが正しい** —— LUMN 1.70（2017-11 Level3 買収で株数が倍。wa は期中平均なので
#         asof(7月)の株数を41%過小に出す）／BDX 1.19（Bard買収）／OKE 1.37 ／
#         **NKE 1.91・HAE 2.00（FY末→cutoffの間の株式分割。px は板の値＝分割後なのに wa は分割前）**
#         ⇒ `retro_per_asof` の per は**この社で分割基準が割れている**（KLAC事故の型が在庫に生きている）
#     (iii) 自社株買い・複数クラス —— 0.74〜0.87 の帯
#   ⇒ **食い違いで落とさない**（落とすと株式で買収した社が系統的に消える＝選別）。
#   両方の株数で mcap を出し、**検定は二つとも回して結論が基準に依らないことを示す**。
#
# ★もう一つ実測で見つけた欠陥（在庫の側・ここでは直さず名指しする）:
#   `retro_per_asof.annual_entries` は候補タグの**最初に見つかった系列で break** し、
#   `latest_before` は**どれだけ古くても最新の一つ**を返すので、系列が途中で途切れている社では
#   **何年も前の会計年度で per を作る**。実測（2018アンカー）: **fy_end が450日以上古い社が32社**、
#   最古は PCG 2009-12-31（**8.2年**）。**BKNG は per 192.1 が FY2010 の利益から出ている**
#   ——CLAUDE.md が「BKNGは11年前の決算で計算していた」と名指しした当の型が在庫に生きていた。
#   この道具は `per_stale` で名指しし、**per を使う検定からその社を外す**。在庫は書き換えない
#   （過去の結論を黙って動かさないため。是正は todo `retro_per_stale_fy`）。
#
# ⚠ 基準（門の mcap 欄とは別物。混ぜてはいけない）:
#   門の ccfMcapUSD は `px_今日 × (ni ÷ eps)` で eps は期末株数ベース。こちらは asof時点。
#   用途は**コホート内の順位**で、水準を門の数字と直接比べない。
#
# 実行: python3 night/retro_mcap.py --asof 2018
# 出力: out/retro_mcap_{asof}.json
import json, os, sys, datetime, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
import retro_per_asof as RP  # 採取の作法はここから借りる（再実装しない）

ASOF = 2018
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])

PER = os.path.join(BASE, "out", f"retro_per_{ASOF}_all.json")
OUT = os.path.join(BASE, "out", f"retro_mcap_{ASOF}.json")
LAG_MAX = 450          # 会計年度の古さの上限（日）。cutoff=asof-03-01 なので正当な最大は約366日
AGREE = (0.90, 1.10)   # 二つの株数が「一致した」と言える帯
PLAUS = (0.20, 5.00)    # この外は eop が壊れている（単位・桁・ADR比）。eop を捨てる


def lag_days(cutoff, fy):
    return (RP.d2(cutoff) - RP.d2(fy)).days


def shares_eop(facts, cutoff):
    """表紙の実株数（提出日時点）。cutoff以前に**提出された**申告のうち最も新しいもの。
    dei は instant なので end ではなく filed で切る＝as-of の意味が保てる。"""
    best = None
    for taxo in ("dei", "us-gaap"):
        for tag in ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"):
            node = (facts.get(taxo) or {}).get(tag)
            if not node:
                continue
            for unit, ents in node.get("units", {}).items():
                if unit != "shares":
                    continue
                for e in ents:
                    fl, v = e.get("filed"), e.get("val")
                    if not fl or not v or float(v) <= 0:
                        continue
                    if fl > cutoff:
                        continue
                    if best is None or fl > best[0]:
                        best = (fl, float(v), f"{taxo}:{tag}")
            if best:
                return best
    return best


def main():
    if not os.path.exists(PER):
        sys.exit(f"■ 在庫が無い: {PER}（先に retro_per_asof.py --asof {ASOF} --all）")
    per = json.load(open(PER))
    cutoff = per["cutoff_fy_end"]          # per を作ったときと同じ線を使う
    cf = os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")
    if not os.path.exists(cf):
        cf = os.path.join(BASE, "out", "retro_cohort_2013.json")
    t2cik = {r["ticker"]: r["cik"] for r in json.load(open(cf))["rows"] if r.get("ticker")}
    z = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip"))

    rows, miss = [], []
    for i, r in enumerate(per["rows"], 1):
        t, px, fy = r["ticker"], r["px"], r["fy_end"]
        cik = t2cik.get(t)
        if not cik:
            miss.append({"ticker": t, "why": "no_cik"}); continue
        try:
            facts = json.loads(z.read(f"CIK{cik:010d}.json")).get("facts", {})
        except Exception:
            miss.append({"ticker": t, "why": "no_facts"}); continue
        ni = RP.latest_before(RP.annual_entries(facts, RP.NI_TAGS, ("USD",)), cutoff)
        sh = RP.latest_before(RP.annual_entries(facts, RP.SH_TAGS, ("shares",)), cutoff)
        if not ni or not sh or ni[1] <= 0 or sh[1] <= 0:
            miss.append({"ticker": t, "why": "ni_or_sh"}); continue
        if ni[0] != fy:
            # per を作ったときと別の会計年度を掴んでいる＝基準の違う二つ
            miss.append({"ticker": t, "why": f"fy_mismatch {ni[0]} vs {fy}"}); continue
        lag_sh = lag_days(cutoff, sh[0])
        wa_fresh = lag_sh <= LAG_MAX
        eop = shares_eop(facts, cutoff)
        lag_eop = lag_days(cutoff, eop[0]) if eop else None
        eop_fresh = bool(eop) and lag_eop <= LAG_MAX
        ratio = (eop[1] / sh[1]) if (eop and sh[1] > 0) else None
        eop_ok = eop_fresh and ratio is not None and PLAUS[0] <= ratio <= PLAUS[1]
        if not wa_fresh and not eop_ok:
            miss.append({"ticker": t, "why": f"sh_stale wa={sh[0]}({lag_sh}d) eop={eop and eop[0]}"})
            continue
        mcap_wa = round(px * sh[1] / 1e9, 4) if wa_fresh else None
        mcap_eop = round(px * eop[1] / 1e9, 4) if eop_ok else None
        # 主は eop（asof に最も近い株数）。使えないときだけ wa へ倒し、どちらかを必ず記録する
        src = "eop" if mcap_eop is not None else "wa"
        lag_ni = lag_days(cutoff, ni[0])
        rows.append({"ticker": t, "fy_end": fy, "px": px,
                     "sh_wa": sh[1], "sh_eop": eop[1] if eop else None,
                     "eop_filed": eop[0] if eop else None,
                     "wa_fresh": wa_fresh, "eop_fresh": eop_fresh,
                     "ni": ni[1],
                     "mcap_b": mcap_eop if src == "eop" else mcap_wa,
                     "mcap_src": src,
                     "mcap_wa_b": mcap_wa, "mcap_eop_b": mcap_eop,
                     "sh_ratio": round(ratio, 4) if ratio is not None else None,
                     "sh_agree": bool(ratio is not None and AGREE[0] <= ratio <= AGREE[1]),
                     "per": r["per"], "per_stale": lag_ni > LAG_MAX, "fy_lag_d": lag_ni})
        if i % 150 == 0:
            print(f"  {i}/{len(per['rows'])}  算出:{len(rows)}")

    from collections import Counter
    out = {"generated": datetime.date.today().isoformat(), "asof": ASOF,
           "cutoff_fy_end": cutoff,
           "note": ("asof年7月頭の板の値(分割復元済) × as-reported加重平均希薄化後株数。"
                    "px/株数/純利益の採り方は retro_per_asof.py を import して共有。"
                    "⚠門の mcap 欄は今日の株価×期末株数なので水準を直接比べない（順位の用）。"),
           "checks": {"lag_max_d": LAG_MAX, "agree_band": AGREE, "plausible_band": PLAUS,
                      "sh_wa": "WeightedAverageNumberOfDilutedShares（perの分母と同じ）",
                      "sh_eop": "dei:EntityCommonStockSharesOutstanding（表紙・提出日時点）",
                      "route_identity_warning": ("初版の px×sh vs per×ni は恒等式で検算にならなかった。"
                                                 "独立なのは sh_wa と sh_eop の突合せだけ")},
           "n": len(rows), "n_per_stale": sum(1 for x in rows if x["per_stale"]),
           "n_sh_agree": sum(1 for x in rows if x["sh_agree"]),
           "n_src_eop": sum(1 for x in rows if x["mcap_src"] == "eop"),
           "n_both": sum(1 for x in rows if x["mcap_wa_b"] and x["mcap_eop_b"]),
           "rows": rows, "unmeasured": miss}
    if not rows:
        sys.exit("■ 1社も算出できなかったので書き換えない")   # 空書き込みの検問
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"■ 書き出し: {OUT}  算出 {len(rows)} / 不能 {len(miss)}")
    print("  不能の内訳:", Counter(m["why"].split()[0] for m in miss).most_common())
    print(f"  株数の二源が±10%以内で一致: {out['n_sh_agree']}/{len(rows)}  "
          f"（両方使える {out['n_both']} / 主にeopを採用 {out['n_src_eop']}）")
    print(f"  ⚠ per が古い会計年度から作られている社（mcapは健全・perを使う検定から外す）: {out['n_per_stale']}")


if __name__ == "__main__":
    main()
