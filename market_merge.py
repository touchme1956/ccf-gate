#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_merge.py — market_data.json の市場値を審査パックへ機械充填する(2026-07精査で新設)
背景: Ω75+14社中12社のパックが per/px/shy=null で、Ⅵ買付順位は素のrepoデータでは
投下可0・E[r]判定不能12——判断面がブラウザ手入力だけに支えられ、並走突合が不能だった。
市場値(px/per/perF/beta/shy/evebit)は客観データであり、定性項目(dom/irr/…)とは別物
=「定性を勝手に埋めない」(絶対のルール2)に抵触しない。null のフィールドのみ充填し、
手入力済みの値は上書きしない。充填履歴は _meta.market に記録する。
使い方: python market_fetch.py <TICKERS...> で market_data.json を更新してから
        python market_merge.py            … 全パックへnullのみ充填
        python market_merge.py NVDA MSFT  … 指定銘柄のみ
"""
import json, glob, os, sys
from datetime import date

FIELDS = ["px", "per", "perF", "beta", "shy", "evebit", "analysts", "instOwn"]

# --- 常識帯の関門（2026-07-29新設）------------------------------------------------
# なぜ充填側にも要るか: ガードを採取側(market_fetch_free.py)にしか置いていなかったため、
#   **過去に書き込まれた不正値が market_data.json に残り、ここから何度でもパックへ再注入された**。
#   実測(2026-07-29): KLAC per=5.53/shy=12.28、V shy=13.27、TDG shy=13.83、GRND shy=15.49、
#   NVMI mcap=0.0133(＝$13.3M。px$405の会社であり得ない)→evebit=-2.1。いずれもセッション中に
#   パックからは一度排除したのに、market_data.json 側を消していなかったので復活した。
#   「採取器を直せば安全」は誤り——**保管された値も毎回検問する**。
# shy の上限12%: 純還元が時価総額の12%を超えるのは、時価総額の過小算定(複数クラス株・ADRで
#   dei表紙の株数を使った場合)を疑うべき水準。定義上ありえなくはないが、実測ではすべて誤りだった。
# per の帯 8-200: 外れたら株価源の取り違え(現地通貨とADR、分割未調整)を疑う。
#   ただし**株価とEPSが独立2系統で一致するなら誤りではない**ので、その場合は
#   パック側に手入力するか、根拠を _meta に残して個別に入れること(機械充填はしない)。
BANDS = {"per": (8.0, 200.0), "shy": (-5.0, 12.0), "evebit": (0.0, 300.0), "beta": (0.0, 4.0),
         "px": (0.0, 1e7), "perF": (1.0, 500.0)}


def sane(k, v):
    """常識帯に入っているか。外れた値は充填しない(空欄のほうが誤値よりましという門の原則)"""
    lo_hi = BANDS.get(k)
    if lo_hi is None or v is None:
        return True, ""
    try:
        x = float(v)
    except Exception:
        return False, "数値でない"
    lo, hi = lo_hi
    if x < lo or x > hi:
        return False, f"常識帯[{lo},{hi}]外={x}"
    return True, ""
md = {}
if os.path.exists("market_data.json"):
    md = {k.upper(): v for k, v in json.load(open("market_data.json", encoding="utf-8")).items()}
if not md:
    raise SystemExit("market_data.json が空——先に python market_fetch.py を実行")

only = {a.upper() for a in sys.argv[1:]}
n_f = n_p = 0
for f in sorted(glob.glob("out/*_gate_pack.json")):
    t = os.path.basename(f).split("_gate_pack")[0].upper()
    if only and t not in only:
        continue
    if t not in md:
        continue
    try:
        o = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        print(f"▲ {f} 読込不能: {e}")
        continue
    filled, rejected = [], []
    for k in FIELDS:
        v = md[t].get(k)
        if v is None or o.get(k) is not None:
            continue
        ok, why = sane(k, v)
        if not ok:
            rejected.append(f"{k}={v}({why})")
            continue
        o[k] = v
        filled.append(k)
    if rejected:
        print(f"{t:<6} ✗ 充填拒否: {' / '.join(rejected)}  ← market_data.json 側の値が疑わしい。採り直せ")
    if filled:
        m = o.setdefault("_meta", {})
        m["market"] = {"date": str(date.today()), "filled": filled,
                       "src": "market_fetch/market_data.json"}
        # 2026-07-29新設: 充填した欄そのものに「いつ・どこから」を刻む。
        #   市場項目の根拠被覆率は実測6.0%（night/audit_evidence.py）で、
        #   **どの値がいつの採取か台帳から判らなかった**——だから market_data.json に残った
        #   旧不正値が11社へ再注入されても気づけなかった。日付が入っていれば陳腐化も見える。
        ev = m.setdefault("evidence", {})
        pv = m.setdefault("provenance", {})
        for k in filled:
            ev[k] = f"市場データ機械充填 {date.today()}: market_fetch/market_data.json（常識帯{BANDS.get(k,'—')}を通過）"
            pv[k] = "market"
        json.dump(o, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n_p += 1
        n_f += len(filled)
        print(f"{t:<6} 充填: {','.join(filled)}")
print(f"→ {n_p}パックに{n_f}フィールド充填(nullのみ・手入力値は不変)。門で再取込すればⅥのE[r]判定が生きる")
