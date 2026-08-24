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
  python3 night/lookthrough.py --pick     資産全体の「つるはし比率」を層で割る
  python3 night/lookthrough.py --holdings "ITA,NASA"  ETFの中身を1銘柄ずつ（層＋門の判定つき）
  python3 night/lookthrough.py --pick --castle "MSFT=8.0,ASML=7.26,..."  城の姿を変えて測る
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
# ★ETFの中身を**門の判定で**見る（2026-08-19新設）。--gate "MISL,GRID"
#   なぜ要るか: 「金のつるはし（掘る人でなく道具を売る側）」を網で取りたい、という問いに
#   この台帳は既に答えを持っている——13年の検証で唯一「効く」と出た変数 irr=85
#   （顧客の側が再認定の費用を負う型）は、まさにつるはしの機構そのもの。
#   ところが**ETFは同じ業界の「機構を持つ社」と「持たない社」を区別しない**。
#   実測: 2018年ビンテージの irr=85 のうち、引用が願望形だった5社は3社が非継続
#   （IPGP −6.6%/年・ROG +1.6%・OLED −0.6%）。**同じ業界の中で結果が割れる。**
#   だから「この ETF を門の目で見ると何を買うことになるのか」を数える。**判定には使わない。**
# ★ETFを「つるはしか」で見る（2026-08-19新設）。--chain "GRID,MISL"
#   ユーザーの明示指示「ETFはirrの評価はいらない。そのETFが今後伸びる産業で金のツルハシかが大事」。
#   つるはしの判定は**層**で行う——供給(誰が勝っても払ってもらえる) / 元請(勝者を取り合う) / 需要側(資産を運用する)。
#   層の割り当ては night/chain_layers.json（**判断**であって測定ではない・外に出してあるので誰でも直せる）。
#   産業の伸びは gate0_all.csv の **実測**（売上5年CAGR・営業利益率・ROIC）を保有比で加重する。
#   ⚠測れた分だけで加重するので、**測れた割合を必ず併記する**（未取得を0と読むと薄く見える・ルール7）。
CHAIN_SPEC = None
for _i, _a in enumerate(sys.argv):
    if _a == "--chain" and _i + 1 < len(sys.argv):
        CHAIN_SPEC = sys.argv[_i + 1]

# ★資産全体の「つるはし比率」を測る（2026-08-19新設）。--pick
#   ユーザーの明示指示「ツルハシを持つことを何よりも優先したい」。
#   ETF1本ずつではなく**資産全体**（城＋網をルックスルー）を層で割る。
#   ⚠**層は判断**（chain_layers.json）。だから結論が読みに依存しない
#   **二重のつるはし**（装置・材料・EDA＋認定済み航空部品）を必ず併記する。
#   ⚠**未取得は0と読まない**（ルール7）——別の列に出し、そのぶん供給%は下限として読む。
#   城の姿を変えて測るには --castle "MSFT=8.00,ASML=7.26,..."（**総資産に対する%**）。
#   目標ウェイトをここへ焼き付けない——Ⅵが Tier で毎日計算しており、
#   写した数字は必ず陳腐化する（版番号・堀の線・四関門の再掲で繰り返し踏んだ型）。
# ★ETFの中身を1銘柄ずつ全部出す（2026-08-19新設）。--holdings "ITA,NASA"
#   層（判断）と門の判定（score_all.json）を各行に添える。**表示だけ・判定には使わない。**
#   ⚠ティッカーが配信されない保有は**捨てず**「未取得」として合計を出す（ルール7）。
HOLD_SPEC = None
for _i, _a in enumerate(sys.argv):
    if _a == "--holdings" and _i + 1 < len(sys.argv):
        HOLD_SPEC = sys.argv[_i + 1]

PICK = "--pick" in sys.argv
CASTLE_SPEC = None
for _i, _a in enumerate(sys.argv):
    if _a == "--castle" and _i + 1 < len(sys.argv):
        CASTLE_SPEC = sys.argv[_i + 1]

GATE_SPEC = None
for _i, _a in enumerate(sys.argv):
    if _a == "--gate" and _i + 1 < len(sys.argv):
        GATE_SPEC = sys.argv[_i + 1]

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
        # ★v9.9.169 から台帳(pf:portfolio)は**網(ETF)も持つ**（ユーザー指示「保有に入れてほしい」）。
        #   網は下の net() が portfolio.json から読んで**中身へ分解する**ので、
        #   ここで数えると **同じ ETF を2回**（丸ごと1回＋構成銘柄へ分解して1回）数える。
        if p.get("sleeve") == "net":
            continue
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
        "top": rows[:40],
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

    tmix, tasof = target_mix()
    if tmix and not NET_SPEC:
        miss = [k for k in tmix if k not in prof.get("etfs", {})]
        if miss:
            print(f"   ⚠ 目標の網に中身が未取得のETF: {', '.join(miss)} — 『未取得』に丸ごと乗る")
        run(f"★目標の網（portfolio.json {tasof}・網 {sum(tmix.values()):.0f}%）",
            {k: total * v / 100.0 for k, v in tmix.items()})

    run("A 現行（XLK/QQQ/SMH/FANG+）", n_map)
    tot_net = sum(n_map.values())
    run("B 網を全部 VT へ", {"VT": tot_net})
    run("C 網の半分を VT へ（SMHとFANG+をVTに）",
        {**{k: v for k, v in n_map.items() if k in ("XLK", "QQQ")},
         "VT": n_map.get("SMH", 0) + n_map.get("FANG+", 0)})
    run("D 網を 40%→30% に減らす（現行の中身のまま）",
        {k: v * 0.75 for k, v in n_map.items()})
    return cases


def gate_view(specs):
    """ETFの中身を score_all.json（門の判定）と突き合わせる。**表示だけ。**"""
    prof = (jload("out/etf_profiles.json") or {}).get("etfs", {})
    rows = jload("out/score_all.json") or []
    G = {r["t"]: r for r in rows}
    for sym in [x.strip().upper() for x in specs.split(",") if x.strip()]:
        e = prof.get(sym)
        if not e:
            print(f"\n■ {sym} — ⚠ 中身が未取得（out/etf_profiles.json に無い）。**測っていない**")
            continue
        h = e.get("h") or []
        cov = sum(w for _, w in h)
        buckets = {"buy": [], "next": [], "block": [], "unrated": []}
        irr = {}
        for t, w in h:
            r = G.get(t)
            if not r:
                buckets["unrated"].append((t, w)); continue
            k = "buy" if r.get("buy") else ("next" if r.get("quali") else "block")
            buckets[k].append((t, w, r))
            v = r.get("irr")
            if v:
                irr[v] = irr.get(v, 0) + w
        inl = sum(w for _, w in h) - sum(w for _, w in buckets["unrated"])
        print(f"\n■ {sym}（{e.get('nm','')}）  中身のうち銘柄が判るのは {cov*100:.1f}%"
              f"（残り {100-cov*100:.1f}% は配信元で symbol=n/a か未取得＝**測れていない**）")
        print(f"   台帳にある社 {inl*100:5.1f}%  ／  台帳に無い社 {sum(w for _,w in buckets['unrated'])*100:5.1f}%")
        for k, lab in (("buy", "🟢門が買う"), ("next", "🔵次点(資格あり)"), ("block", "⛔門が落とした")):
            b2 = sorted(buckets[k], key=lambda x: -x[1])
            if not b2:
                continue
            tot = sum(x[1] for x in b2) * 100
            print(f"   {lab} {tot:5.1f}%  " + " ".join(
                f"{x[0]}{x[1]*100:.1f}" for x in b2[:8]) + (" …" if len(b2) > 8 else ""))
        if irr:
            print("   irr の内訳: " + " / ".join(
                f"{k}→{v*100:.1f}%" for k, v in sorted(irr.items(), reverse=True))
                + "　（85＝顧客側が再認定を要する型＝歴史で唯一効いた刻み）")
    return 0



def chain_view(specs):
    """ETFを『つるはしか』で見る。層＝判断（chain_layers.json）／伸び＝実測（gate0_all.csv）。**表示だけ。**"""
    import csv as _csv
    prof = (jload("out/etf_profiles.json") or {}).get("etfs", {})
    lay = jload("night/chain_layers.json") or {}
    LMAP, LNAME = lay.get("map", {}), lay.get("layers", {})
    U = {}
    try:
        with open(os.path.join(ROOT, "gate0_all.csv"), encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                if r.get("ticker"):
                    U[r["ticker"]] = r
    except Exception as e:
        print(f"⚠ gate0_all.csv が読めない（{e}）＝**伸びは測れていない**")
    if not U:
        print("⚠ 母集団が0件＝照合が成立していない。**0を発見と読まない**")

    def num(r, k):
        try:
            v = float(r.get(k) or "")
            return v if v == v else None
        except Exception:
            return None

    print("\n■ つるはし判定（層＝判断 / 伸び＝実測）  物差し: night/chain_layers.json")
    for sym in [x.strip().upper() for x in specs.split(",") if x.strip()]:
        e = prof.get(sym)
        if not e:
            print(f"\n□ {sym} — ⚠ 中身が未取得。**測っていない**")
            continue
        h = e.get("h") or []
        cov = sum(w for _, w in h)
        agg = {"supply": [], "contract": [], "prime": [], "demand": [], "?": []}
        for t, w in h:
            agg[LMAP.get(t, "?")].append((t, w))
        gw = {}
        for key, col in (("cagr", "sales_cagr5"), ("opm", "opm"), ("roic", "roic_latest")):
            num_, den = 0.0, 0.0
            for t, w in h:
                r = U.get(t)
                v = num(r, col) if r else None
                if v is not None:
                    num_ += v * w
                    den += w
            gw[key] = (num_ / den * 100 if den else None, den)
        print(f"\n□ {sym}（{e.get('nm','')}）")
        print(f"   中身のうち銘柄が判るのは {cov*100:.1f}%")
        for k in ("supply", "contract", "prime", "demand", "?"):
            b = sorted(agg[k], key=lambda x: -x[1])
            if not b:
                continue
            tot = sum(w for _, w in b) * 100
            nm = LNAME.get(k, "層が未分類（＝判定していない）")
            print(f"   {tot:5.1f}%  {nm}")
            print("          " + " ".join(f"{t}{w*100:.1f}" for t, w in b[:9])
                  + (" …" if len(b) > 9 else ""))
        s = sum(w for _, w in agg["supply"]) * 100
        c = sum(w for _, w in agg["contract"]) * 100
        p = sum(w for _, w in agg["prime"]) * 100
        print(f"   → 供給 {s:.1f} : 請負 {c:.1f} : 元請 {p:.1f}" +
              ("　つるはし側が厚い" if s > c + p else "　掘る人側が厚い" if p > s else ""))
        for key, lab in (("cagr", "売上5年CAGR"), ("opm", "営業利益率"), ("roic", "ROIC")):
            v, den = gw[key]
            if v is None:
                print(f"   {lab}: **測れていない**")
            else:
                print(f"   {lab} {v:5.1f}%（保有の {den*100:.0f}% で加重）")
    return 0


def holdings_view(specs):
    """ETFの中身を1銘柄ずつ。層＋門の判定を添える。**表示だけ。**"""
    prof = (jload("out/etf_profiles.json") or {}).get("etfs", {})
    lay = jload("night/chain_layers.json") or {}
    LMAP = lay.get("map", {})
    DEEP = {x.upper() for x in (lay.get("deep") or [])}
    G = {r["t"]: r for r in (jload("out/score_all.json") or [])}
    SH = {"supply": "供給", "contract": "請負", "prime": "元請", "demand": "需要側", "?": "—"}
    for sym in [x.strip().upper() for x in (specs or "").split(",") if x.strip()]:
        e = prof.get(sym)
        if not e:
            print(f"\n□ {sym} — ⚠ 中身が未取得（out/etf_profiles.json に無い）。**測っていない**")
            continue
        h = sorted(e.get("h") or [], key=lambda x: -x[1])
        cov = sum(w for _, w in h)
        print(f"\n□ {sym}（{e.get('nm','')}）　経費率 {e.get('er',0)*100:.2f}%"
              f"　純資産 ${e.get('aum',0)/1e9:.1f}B　設定 {e.get('inc','?')}　銘柄 {e.get('n','?')}")
        print(f"   {'#':>3} {'銘柄':<8}{'比率':>7}  {'層':<5}{'門':<12}印")
        for i, (t, w) in enumerate(h, 1):
            g = G.get(t)
            v = ("🟢投下可" if g and g.get("buy") else
                 "🔵次点" if g and g.get("quali") else
                 f"⛔Ω{g['s']:.0f}" if g else "台帳に無い")
            mk = []
            if t in DEEP:
                mk.append("★二重")
            if t in SEMI:
                mk.append("半導体")
            if g and g.get("irr") == 85:
                mk.append("irr85")
            print(f"   {i:>3} {t:<8}{w*100:6.2f}%  {SH.get(LMAP.get(t,'?'),'—'):<5}{v:<12}{' '.join(mk)}")
        miss = 1 - cov
        print(f"   ── 計 {cov*100:.1f}%" + (f"　⚠**未取得 {miss*100:.1f}%**"
              "（配信元でティッカーが出ない保有・下位保有）＝**0と読まない**" if miss > 0.001 else ""))
        note = e.get("hnote")
        if note:
            print(f"   注: {note}")
    return 0


def target_mix():
    """portfolio.json の**今の**網の目標（保有ではない）。
    ★記録したのに誰も読まないと『見つけたものを誰にも渡していない型』になるので、
      --net を書かなくても各ビューが自動で並べる。**判定には一切使わない。**
    ⚠**正本は `target.ami_weights`**（2026-08-20 ユーザー明示指示 XLK15/SMH10/GRID10/ITA10/NASA5）で、
      門(index.html の ccfNetRows)・night/net_plan.py もここを読む。**同じ量を二箇所で持たない**（v9.9.65）。
      旧 `ami_mix`（2026-08-19 の指示・並走ブランチが記録）は翌日に置き換わったので**読まない**——
      置き換わった目標を道具が読み続けると、画面と道具が違う目標を語る。"""
    t = (jload("portfolio.json") or {}).get("target") or {}
    w = t.get("ami_weights") or {}
    if w:
        return ({k.upper(): float(v) for k, v in w.items()}, "target.ami_weights")
    # 旧様式（並走ブランチが書いた形）にしか無いときだけ拾う。**無ければ空**で、0で埋めない
    old = t.get("ami_mix") or {}
    pct = old.get("pct_of_total") or {}
    return ({k.upper(): float(v) for k, v in pct.items()}, old.get("asof"))


def _spec(txt, total):
    """"XLK=15,SMH=15" → {ticker: 円}。**総資産に対する%**で受ける。"""
    out = {}
    for part in (txt or "").split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k.strip().upper()] = total * float(v) / 100.0
        except ValueError:
            print(f"⚠ 読めない指定を無視した: {part!r}")
    return out


def pick_view(castle_spec=None):
    """資産全体のつるはし比率。**表示だけ・判定には一切使わない。**"""
    lay = jload("night/chain_layers.json") or {}
    LMAP, LNAME = lay.get("map", {}), lay.get("layers", {})
    DEEP = {x.upper() for x in (lay.get("deep") or [])}
    prof = jload("out/etf_profiles.json") or {}
    if not LMAP:
        print("⚠ chain_layers.json の map が空＝**照合が成立していない**。0を発見と読まない")
        return 1
    c, _, cerr = castle()
    n, _ = net()
    if cerr:
        print("⚠", cerr)
    T = sum(c.values()) + sum(n.values())
    if T <= 0:
        print("⚠ 総資産が0＝**測れていない**")
        return 1

    def one(cm, nm, lab):
        look, unk = explode(nm, prof)
        tot = sum(cm.values()) + sum(nm.values())
        agg, deep, semi = {}, 0.0, 0.0
        for src in (cm, look):
            for t, v in src.items():
                t = t.upper()
                agg[LMAP.get(t, "?")] = agg.get(LMAP.get(t, "?"), 0) + v
                if t in DEEP:
                    deep += v
                if t in SEMI:
                    semi += v
        u = sum(unk.values())
        agg["?"] = agg.get("?", 0) + u
        g = lambda k: agg.get(k, 0) / tot * 100
        return dict(lab=lab, supply=g("supply"), deep=deep / tot * 100, contract=g("contract"),
                    prime=g("prime"), demand=g("demand"), unk=g("?"),
                    semi=semi / tot * 100, semi_hi=(semi + u) / tot * 100)

    cases = [one(c, n, f"現行（城{sum(c.values())/T*100:.0f}% / 網{sum(n.values())/T*100:.0f}%）")]
    if castle_spec:
        ct = _spec(castle_spec, T)
        rest = T - sum(ct.values())
        if rest < 0:
            print("⚠ --castle の合計が100%を超えている＝網が負になる。測らない")
            return 1
        nt = sum(n.values()) or 1
        cases.append(one(ct, {k: v * rest / nt for k, v in n.items()}, "指定した城（網は今の中身のまま）"))
        cases.append(one(ct, {"SMH": rest}, "同＋網を全部SMH"))
    variants = []
    if NET_SPEC:                       # --net で渡した案も**同じ物差し**で並べる
        variants.append((NET_SPEC, f"★指定の網 {NET_SPEC}"))
    else:                              # 書かなければ**記録された目標の網**を並べる
        tmix, tasof = target_mix()
        if tmix:
            variants.append((",".join(f"{k}={v:g}" for k, v in tmix.items()),
                             f"★目標の網（{tasof}・網{sum(tmix.values()):.0f}%）"))
    variants += [("SMH=30,XLK=20", "網を SMH30/XLK20"), ("SMH=53", "網を全部SMH")]
    for spec, lab in variants:
        m = _spec(spec, T)
        cases.append(one(c, m, lab + "（城は今のまま）"))

    print("\n■ 資産全体のつるはし比率  物差し: night/chain_layers.json（**層は判断・測定ではない**）")
    print(f"   {'案':<34}{'供給':>7}{'うち二重':>9}{'元請':>7}{'需要側':>8}{'測れず':>8}{'半導体(下〜上)':>17}")
    for r in cases:
        print(f"   {r['lab']:<34}{r['supply']:6.1f}%{r['deep']:8.1f}%{r['prime']:6.1f}%"
              f"{r['demand']:7.1f}%{r['unk']:7.1f}%{r['semi']:8.1f}〜{r['semi_hi']:5.1f}%")
    print("   ⚠『測れず』は未取得＋層が未分類。**0と読まない**ので供給%は下限として読む")
    print("   ⚠『うち二重』＝どちらの読みでも供給に残る層（装置・材料・EDA＋認定済み航空部品）。"
          "層の割り当ては読みで反転するので、順位はこの列で読む")
    return 0


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

    if GATE_SPEC:
        gate_view(GATE_SPEC)

    if CHAIN_SPEC:
        chain_view(CHAIN_SPEC)

    if HOLD_SPEC:
        holdings_view(HOLD_SPEC)

    if PICK or CASTLE_SPEC:
        pick_view(CASTLE_SPEC)

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
