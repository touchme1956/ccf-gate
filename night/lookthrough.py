#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/lookthrough.py — **資産全体を1銘柄まで分解する**（v9.9.134・2026-08-10）

■ なぜ要るか
  門は城（個別）の中では 1銘柄8%（¼ケリー）を厳密に守る。ところが**網（ETF）を分解する
  検査器が無かった**ので、資産全体で見たときに同じ銘柄が何%になっているかを誰も測っていない。
  実測では **MSFT が資産の26%＝上限の3.3倍**、半導体連鎖が約半分。
  ＝**網は分散ではなく城の増幅器**として働いている。これは門の欠陥ではなく
  「網を誰も分解していなかった」ことの結果——同じ台帳を見る検査器が片方しか無かった型（v9.9.65）。

■ 何を読むか（すべて repo の中。推測しない）
  城 … state.json の pf:portfolio（株数×現値×ドル円）＝**人の決定の正本**
  網 … portfolio.json（証券アプリのスナップショット・人が更新）
  中身 … out/etf_profiles.json の h=[[ticker, weight], ...]（Alpha Vantage 実採取）

■ 絶対のルール7（欠測をゼロと読むな）
  ETFの中身が取れていない銘柄（FANG+ 等）は**0%として薄めない**。
  「未取得」として別に数え、**カバー率を必ず出す**。カバー外がある限り
  「実際の集中はこれ以上」と明記する——**測れていないことを健全と読ませない**。

使い方:
  python3 night/lookthrough.py            人が読む形
  python3 night/lookthrough.py --json     out/lookthrough.json を書く
  python3 night/lookthrough.py --what-if  網の中身・比率を替えたらどうなるかを並べる
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = "--json" in sys.argv
WHATIF = "--what-if" in sys.argv
# ★任意の網の構成を、同じ物差しで測る（2026-08-19新設）
#   例: --net "XLK=15,SMH=15,GRID=15,MISL=5"  ＝**総資産に対する%**で網を組む。
#   ⚠ 案をこの中にハードコードで増やし続けると必ず陳腐化する（v9.9.145 の SEMI 列挙と同じ問題）。
#     候補を検討するたびに引数で渡せる形にしておく。指定すると --what-if も自動で立つ。
NET_SPEC = None
for _i, _a in enumerate(sys.argv):
    if _a == "--net" and _i + 1 < len(sys.argv):
        NET_SPEC = sys.argv[_i + 1]
        WHATIF = True
CAP = 8.0   # 門の1銘柄上限（¼ケリー・v9.9.96）。ここでは**判定に使わず物差しとして表示するだけ**

# 半導体連鎖（v9.9.117 の SEMI と同じ思想＝同じ設備投資サイクルに乗るか）
SEMI = {"NVDA", "AVGO", "AMD", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU", "INTC", "TXN",
        "QCOM", "ADI", "NXPI", "MRVL", "MCHP", "ON", "SWKS", "QRVO", "TER", "ENTG", "MKSI",
        "6857", "6146", "6920", "8035", "3436"}


def jload(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def castle():
    """城（個別）。state.json の pf:portfolio が正本。円換算して {ticker: 円} を返す。"""
    s = jload("state.json") or {}
    raw = (s.get("data") or {}).get("pf:portfolio")
    if not raw:
        return {}, None, "state.json に pf:portfolio が無い（まだ書き出していない）"
    pf = json.loads(raw)
    fx = pf.get("fx") or 0
    out = {}
    for p in pf.get("positions") or []:
        t = (p.get("t") or "").upper()
        sh = p.get("sh") or 0
        px = p.get("npx") or p.get("bpx") or 0
        if sh and px:
            v = sh * px * (1 if p.get("ccy") == "JPY" else fx)
        else:
            v = p.get("v") or 0          # 株数が無い行は保存済みの評価額で
        if t and v:
            out[t] = out.get(t, 0) + v
    return out, pf.get("asof"), None


def net():
    """網（ETF）。portfolio.json のスナップショットが正本。{ticker: 円} を返す。"""
    p = jload("portfolio.json") or {}
    out = {}
    for x in p.get("positions") or []:
        if x.get("sleeve") == "網":
            t = (x.get("ticker") or "").upper()
            v = x.get("value_jpy") or 0
            if t and v:
                out[t] = out.get(t, 0) + v
    return out, p.get("asof")


def explode(net_map, profiles):
    """網を中身へ分解。取れない分は '未取得' として残す（ゼロと読まない＝ルール7）。"""
    look, unknown = {}, {}
    for etf, yen in net_map.items():
        prof = (profiles.get("etfs") or {}).get(etf)
        h = (prof or {}).get("h") or []
        cov = sum(w for _, w in h)
        if not h or cov <= 0:
            unknown[etf] = yen                     # 中身をまったく持っていない
            continue
        for t, w in h:
            look[t.upper()] = look.get(t.upper(), 0) + yen * w
        rest = yen * max(0.0, 1.0 - cov)           # 上位N件しか無い分
        if rest > 1:
            unknown[etf] = unknown.get(etf, 0) + rest
    return look, unknown


def build():
    c, c_asof, c_err = castle()
    n, n_asof = net()
    prof = jload("out/etf_profiles.json") or {}
    look, unknown = explode(n, prof)

    total = sum(c.values()) + sum(n.values())
    merged = {}
    for t, v in c.items():
        merged[t] = merged.get(t, 0) + v
    for t, v in look.items():
        merged[t] = merged.get(t, 0) + v

    rows = sorted(({"t": t, "yen": v, "pct": v / total * 100 if total else 0,
                    "direct": c.get(t, 0), "via_etf": look.get(t, 0)}
                   for t, v in merged.items()), key=lambda r: -r["yen"])
    cov_yen = sum(merged.values())
    unk_yen = sum(unknown.values())
    semi = sum(r["yen"] for r in rows if r["t"] in SEMI)
    return {
        "asof_castle": c_asof, "asof_net": n_asof,
        "etf_asof": prof.get("asof"),
        "total_jpy": round(total),
        "castle_jpy": round(sum(c.values())), "net_jpy": round(sum(n.values())),
        "castle_pct": round(sum(c.values()) / total * 100, 1) if total else 0,
        "net_pct": round(sum(n.values()) / total * 100, 1) if total else 0,
        "coverage_pct": round(cov_yen / total * 100, 1) if total else 0,
        "unknown_jpy": round(unk_yen), "unknown_by_etf": {k: round(v) for k, v in unknown.items()},
        "over_cap": [r for r in rows if r["pct"] > CAP],
        "top": rows[:20],
        "semi_pct": round(semi / total * 100, 1) if total else 0,
        "top5_pct": round(sum(r["pct"] for r in rows[:5]), 1),
        "castle_err": c_err,
        "note": "網の中身が取れない分は**ゼロで薄めず『未取得』として別に数える**（ルール7）。"
                "カバー外がある限り、実際の集中はここに出た数字より高い。"
                "**この道具は判定に一切使わない**——門の四関門・配分・売却規律はどれもこれを読まない。",
    }


def whatif(b):
    """網の中身と比率を替えたら1銘柄の最大%がどうなるか。**提案であって規約ではない**。"""
    prof = jload("out/etf_profiles.json") or {}
    n_map, _ = net()
    c, _, _ = castle()
    total = b["total_jpy"]
    cases = []

    def run(label, net_alloc):
        look, unknown = explode(net_alloc, prof)
        m = dict(c)
        for t, v in look.items():
            m[t] = m.get(t, 0) + v
        rows = sorted(m.items(), key=lambda kv: -kv[1])
        semi = sum(v for t, v in m.items() if t in SEMI)
        cases.append({"case": label,
                      "max_t": rows[0][0] if rows else None,
                      "max_pct": round(rows[0][1] / total * 100, 1) if rows and total else 0,
                      "semi_pct": round(semi / total * 100, 1) if total else 0,
                      "n_over_cap": sum(1 for t, v in m.items() if v / total * 100 > CAP),
                      # ★半導体は**幅**で出す（2026-08-19）。未取得を0として比べると、
                      #   **中身が採れていない案ほど「分散して見える」**——実測 VT は9500銘柄中41件しか
                      #   採れず未取得35%で、半導体13.8%は「薄い」ではなく「測れていない」。
                      #   下限=未取得を全部 非半導体と置く／上限=全部 半導体と置く。
                      #   ＝**未取得の大きさが違う案どうしを、下限だけで比べてはいけない**（ルール7）。
                      "semi_hi": round((semi + sum(unknown.values())) / total * 100, 1) if total else 0,
                      "unknown_pct": round(sum(unknown.values()) / total * 100, 1) if total else 0})

    if NET_SPEC:
        # **総資産に対する%**で受ける（円ではない）。読めない指定は黙って無視せず落とす。
        alloc = {}
        for part in NET_SPEC.split(","):
            k, _, v = part.partition("=")
            k = k.strip().upper()
            if not k or not v.strip():
                raise SystemExit(f"--net の書式は 'XLK=15,SMH=15' （%）。読めない: {part!r}")
            alloc[k] = total * float(v) / 100.0
        miss = [k for k in alloc if k not in prof.get("etfs", {})]
        if miss:
            # ⚠ 中身を持っていないETFを混ぜると**分解できない分が「無い」ことにされる**（ルール7）。
            print(f"   ⚠ 中身が未取得のETF: {', '.join(miss)}"
                  f" — 下の『未取得』に丸ごと乗る。実際の集中はこれ以上")
        run(f"★指定 {NET_SPEC}（網 {sum(alloc.values())/total*100:.0f}%）", alloc)

    run("A 現行（XLK/QQQ/SMH/FANG+）", n_map)
    tot_net = sum(n_map.values())
    run("B 網を全部 VT へ", {"VT": tot_net})
    run("C 網の半分を VT へ（SMHとFANG+をVTに）",
        {**{k: v for k, v in n_map.items() if k in ("XLK", "QQQ")},
         "VT": n_map.get("SMH", 0) + n_map.get("FANG+", 0)})
    run("D 網を 40%→30% に減らす（現行の中身のまま）",
        {k: v * 0.75 for k, v in n_map.items()})
    return cases


def main():
    b = build()
    if AS_JSON:
        json.dump(b, open("out/lookthrough.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(json.dumps(b, ensure_ascii=False, indent=1))
        return 0

    print("■ 資産全体のルックスルー（night/lookthrough.py）— **表示だけ・判定には一切使わない**")
    if b["castle_err"]:
        print("  ⚠", b["castle_err"])
    print(f"  総額 ¥{b['total_jpy']:,}　城 {b['castle_pct']}%（¥{b['castle_jpy']:,}）"
          f" / 網 {b['net_pct']}%（¥{b['net_jpy']:,}）")
    print(f"  日付: 城 {b['asof_castle']}（state.json）／ 網 {b['asof_net']}（portfolio.json）"
          f"／ ETFの中身 {b['etf_asof']}")
    print(f"  分解できた割合 {b['coverage_pct']}%"
          + (f"　⚠未取得 ¥{b['unknown_jpy']:,}（{', '.join(b['unknown_by_etf'])}）"
             "＝**実際の集中はこれ以上**" if b["unknown_jpy"] else ""))
    print()
    print(f"■ 1銘柄の上限 {CAP}%（¼ケリー）を超えている銘柄　{len(b['over_cap'])}件")
    for r in b["over_cap"]:
        d = f"直接 {r['direct']/b['total_jpy']*100:.1f}%" if r["direct"] else "直接なし"
        e = f"網ごし {r['via_etf']/b['total_jpy']*100:.1f}%" if r["via_etf"] else ""
        print(f"   {r['t']:6} {r['pct']:5.2f}%  （上限の{r['pct']/CAP:.1f}倍）  {d}"
              + (f" ＋ {e}" if e else ""))
    print()
    print("■ 上位10銘柄")
    for r in b["top"][:10]:
        print(f"   {r['t']:6} {r['pct']:5.2f}%  ¥{round(r['yen']):>9,}")
    print(f"\n  半導体連鎖 {b['semi_pct']}%　／　上位5銘柄 {b['top5_pct']}%")

    if WHATIF:
        print("\n■ 網の中身・比率を替えたら（**提案であって規約ではない**）")
        print(f"   {'案':38} {'最大の1銘柄':>16} {'半導体(下限〜上限)':>19} {'8%超':>5} {'未取得':>7}")
        for c in whatif(b):
            print(f"   {c['case']:38} {str(c['max_t'])+' '+str(c['max_pct'])+'%':>16}"
                  f" {c['semi_pct']:8.1f}〜{c['semi_hi']:5.1f}% {c['n_over_cap']:4}件 {c['unknown_pct']:6.1f}%")
        print("   ⚠ 半導体は**幅**。上限＝未取得が全部半導体だった場合。"
              "未取得の大きさが違う案は下限だけで比べられない（VTは9500銘柄中41件しか中身が採れていない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
