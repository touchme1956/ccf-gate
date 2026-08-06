#!/usr/bin/env python3
# night/retro_irr85_replicate.py — irr=85 の追試（2013/2015ビンテージ）の解析（2026-08-05新設）
#
# 事前登録: out/retro_irr85_replication_prereg.json（**読解前**にコミット済み）
# 入力:
#   out/retro_moat_{asof}.json        盲検読解の結果（irr/quote/tense/mech/moat5）
#   out/retro_returns_2013_all.json   実現リターン（配当込み・2026-08-04生成・この解析では再計算しない）
#   out/retro_returns_2015.json
#   out/retro_cohort_{asof}.json      asof時点の売上（無名社サブセット用）
#   out/_subs_cache/{cik}.json        SIC（業種交絡の検問。readlist作成時に落としたもの）
#   out/retro_monthly_2013_2018.json / retro_monthly_2018_2026.json  レジーム分割
# 使い方: python3 night/retro_irr85_replicate.py --asof 2013 [--asof 2015]
# 出力  : out/retro_irr85_replication_{asof}.json ＋ 標準出力の表
import json, os, sys, statistics, math

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
HURDLE = 0.15
# 半導体・フォトニクス連鎖（実体で除外する側。2018年検証の SEMI と同じ考え方）
SEMI_SIC = {"3674", "3559", "3827", "3679", "3670", "3690", "3559", "3826", "3672", "3944"}
SEMI_T = {"LRCX", "ENTG", "SNPS", "NVMI", "TSEM", "CAMT", "INTC", "VSH", "AUDC", "COHR",
          "SWKS", "MU", "SIMO", "HIMX", "AMAT", "MKSI", "NOVT", "OLED", "IPGP", "AEIS"}


def load(n):
    p = os.path.join(OUT, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def cagr_pairs(pts):
    if not pts or len(pts) < 24:
        return None
    a, b = pts[0], pts[-1]
    if a[1] <= 0:
        return None
    y = (b[0] - a[0]) / (365.25 * 86400)
    return (b[1] / a[1]) ** (1 / y) - 1 if y > 0.5 else None


def rate(rows, key=lambda r: True, h=HURDLE):
    s = [r for r in rows if key(r) and r.get("tr") is not None]
    if not s:
        return {"n": 0, "p": None, "med": None}
    k = sum(1 for r in s if r["tr"] >= h)
    lo, hi = wilson(k, len(s))
    return {"n": len(s), "k": k, "p": round(k / len(s), 3), "ci": [lo, hi],
            "med": round(statistics.median(r["tr"] for r in s), 4),
            "basket": round(statistics.mean(r["tr"] for r in s), 4)}


def main():
    tag = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else "2013"
    asof = int("".join(c for c in tag.split("+")[0] if c.isdigit()))
    tags = [tag] if "+" not in tag else tag.split("+")   # 例: --asof 2013+2013q で広域と質実証プールを合算
    mrows, srcs = [], []
    for tg in tags:
        m = load(f"retro_moat_{tg}.json")
        if not m:
            sys.exit(f"out/retro_moat_{tg}.json が無い（読解が未完）")
        mrows += m["rows"]; srcs.append(tg)
    seen = set(); ded = []
    for r in mrows:
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"]); ded.append(r)
    moat = {"rows": ded}
    print(f"（読解の出所: {'+'.join(srcs)} ／ 重複除去後 {len(ded)}社）")
    rf = None
    for cand in (f"retro_returns_{asof}_all.json", f"retro_returns_{asof}_q.json", f"retro_returns_{asof}.json"):
        if os.path.exists(os.path.join(OUT, cand)):
            rf = cand
            break
    R = load(rf)
    ret = {r["ticker"]: r for r in R["rows"]}
    spy = R["benchmark"]["tr_cagr"]
    years = R["benchmark"]["years"]
    coh = {r["ticker"]: r for r in load(f"retro_cohort_{asof}.json")["rows"] if r.get("ticker")}
    rl = {}
    for tg in tags:
        for r in (load(f"retro_readlist_{tg}.json") or {"rows": []})["rows"]:
            rl.setdefault(r["ticker"], r)

    def sic_of(t):
        c = rl.get(t, {}).get("cik")
        p = os.path.join(OUT, "_subs_cache", f"{c}.json")
        if not c or not os.path.exists(p):
            return None
        try:
            return str(json.load(open(p, encoding="utf-8")).get("sic") or "")[:4] or None
        except Exception:
            return None

    rows = []
    for m in moat["rows"]:
        t = m["ticker"]
        r = ret.get(t)
        s = sic_of(t)
        rows.append({**m, "tr": (r or {}).get("tr_cagr"), "mdd": (r or {}).get("mdd"),
                     "sic": s, "sic2": (s or "  ")[:2],
                     "rev": (coh.get(t) or {}).get("rev_asof"),
                     "semi": (s in SEMI_SIC) or (t in SEMI_T)})

    base = rate(rows)
    out = {"generated": "2026-08-05", "asof": asof, "tag": tag, "sources": srcs, "years": years, "spy": spy,
           "hurdle": HURDLE, "n_read": len(rows), "base": base}

    print(f"\n{'='*74}\nirr=85 の追試 — asof={asof}（{years}年・SPY {spy:.1%}・継続の線 {HURDLE:.0%}）\n{'='*74}")
    print(f"読解 {len(rows)}社 / リターンあり {base['n']}社 / ベース P(継続)={base['p']} 中央値{base['med']:.1%}")

    # --- 刻み別 ---
    grades = {}
    print(f"\n【刻み別】{'':4}   n   P(継続)  95%CI            中央値   等加重年率")
    for g in [100, 85, 70, 50, None]:
        st = rate(rows, lambda r, g=g: r.get("irr") == g)
        grades[str(g)] = st
        if st["n"]:
            print(f"  irr={str(g):4} {st['n']:4}   {st['p']:.3f}  {str(st['ci']):16} {st['med']:+.1%}  {st['basket']:+.1%}")
    out["by_grade"] = grades

    g85 = rate(rows, lambda r: r.get("irr") == 85)
    lift = None if g85["p"] is None or base["p"] is None else round(g85["p"] - base["p"], 3)
    out["irr85"] = {**g85, "lift": lift}

    # --- 事前登録の判定 ---
    ok = (g85["n"] >= 5 and g85["p"] is not None and g85["p"] >= 0.50 and lift is not None and lift >= 0.20)
    power = g85["n"] < 5
    out["verdict"] = {"n85": g85["n"], "p85": g85["p"], "lift": lift,
                      "pass": bool(ok), "underpowered": bool(power)}
    print(f"\n【事前登録の判定】n(irr85)={g85['n']} / P={g85['p']} / lift={lift} → "
          + ("**検出力不足（n<5）**" if power else ("**合格**" if ok else "**不合格**")))

    # --- バスケット ---
    o = rate(rows, lambda r: r.get("irr") != 85)
    out["basket"] = {"irr85": g85.get("basket"), "other": o.get("basket"), "spy": spy}
    print(f"【等加重バスケット年率】irr85 {g85.get('basket')} / その他 {o.get('basket')} / SPY {spy}")

    # --- 言語（完了形 vs 願望形。2018年は 0.81 vs 0.40）---
    lang = {k: rate(rows, lambda r, k=k: r.get("irr") == 85 and r.get("tense") == k)
            for k in ("完了形", "願望形", "なし")}
    out["language_within85"] = lang
    print(f"【irr85内の言語】完了形 n={lang['完了形']['n']} P={lang['完了形']['p']} / "
          f"願望形 n={lang['願望形']['n']} P={lang['願望形']['p']}")
    lang_all = {k: rate(rows, lambda r, k=k: r.get("tense") == k) for k in ("完了形", "願望形", "なし")}
    out["language_all"] = lang_all

    # --- 主観の堀（対照）---
    m5 = {f">={k}": rate(rows, lambda r, k=k: (r.get("moat5") or 0) >= k) for k in (4, 5)}
    out["moat5_control"] = m5
    print(f"【対照 moat5】>=4 n={m5['>=4']['n']} P={m5['>=4']['p']}（lift "
          f"{None if m5['>=4']['p'] is None else round(m5['>=4']['p']-base['p'],3)}）"
          f" / >=5 n={m5['>=5']['n']} P={m5['>=5']['p']}")

    # --- 業種交絡: 同一SIC2内 ---
    s85 = {r["sic2"] for r in rows if r.get("irr") == 85 and r["sic2"].strip()}
    same = rate(rows, lambda r: r.get("irr") == 85 and r["sic2"] in s85)
    peer = rate(rows, lambda r: r.get("irr") != 85 and r["sic2"] in s85)
    out["same_sic2"] = {"irr85": same, "同業の非irr85": peer, "sic2": sorted(s85)}
    print(f"【同一SIC2内】irr85 n={same['n']} P={same['p']} vs 同業の非irr85 n={peer['n']} P={peer['p']}")

    # --- 半導体連鎖の除外 ---
    ns = rate(rows, lambda r: r.get("irr") == 85 and not r["semi"])
    out["ex_semi"] = ns
    print(f"【半導体連鎖を除外】irr85 n={ns['n']} P={ns['p']} 等加重{ns.get('basket')}")

    # --- 閾値非依存 ---
    th = {}
    for h in (0.10, 0.15, 0.20, 0.25):
        a = rate(rows, lambda r: r.get("irr") == 85, h)
        b = rate(rows, lambda r: True, h)
        th[f"{h:.2f}"] = {"irr85": a["p"], "base": b["p"],
                          "lift": None if a["p"] is None or b["p"] is None else round(a["p"] - b["p"], 3)}
    out["thresholds"] = th
    print("【閾値非依存】" + " / ".join(f"{k}: {v['irr85']}vs{v['base']}(lift{v['lift']})" for k, v in th.items()))

    # --- 無名社（LLMの事前知識の検問）---
    small = rate(rows, lambda r: r.get("irr") == 85 and (r.get("rev") or 0) < 1e9)
    smallb = rate(rows, lambda r: (r.get("rev") or 0) < 1e9)
    out["small_only"] = {"irr85": small, "base": smallb}
    print(f"【無名社(売上<10億$)】irr85 n={small['n']} P={small['p']} vs その帯のベース n={smallb['n']} P={smallb['p']}")

    # --- レジーム分割 ---
    mon = load("retro_monthly_2013_2018.json") if asof == 2013 else None
    mon2 = load("retro_monthly_2018_2026.json")
    if mon2:
        def sub(t, M):
            return cagr_pairs(M.get(t)) if M else None
        for r in rows:
            r["r_pre"] = sub(r["ticker"], mon) if mon else None
            r["r_post"] = sub(r["ticker"], mon2)
        reg = {}
        for k, f in (("前期", "r_pre"), ("後期", "r_post")):
            a = [r[f] for r in rows if r.get("irr") == 85 and r.get(f) is not None]
            b = [r[f] for r in rows if r.get(f) is not None]
            if a and b:
                reg[k] = {"n85": len(a), "P85": round(sum(1 for x in a if x >= HURDLE) / len(a), 3),
                          "Pbase": round(sum(1 for x in b if x >= HURDLE) / len(b), 3)}
        out["regime"] = reg
        if reg:
            print("【レジーム】" + " / ".join(f"{k}: irr85 {v['P85']} vs base {v['Pbase']}(n={v['n85']})" for k, v in reg.items()))

    # --- 明細 ---
    out["rows"] = [{k: r.get(k) for k in ("ticker", "irr", "tense", "mech", "moat5", "tr", "mdd",
                                          "sic", "semi", "rev", "quote", "note")} for r in rows]
    print("\n【irr=85 の明細】")
    for r in sorted([x for x in rows if x.get("irr") == 85], key=lambda x: -(x["tr"] or -9)):
        print(f"  {r['ticker']:6} {('%+.1f%%' % (r['tr']*100)) if r['tr'] is not None else '  na  ':>8}/年"
              f"  {r['tense']:3} {r['mech']:12} moat5={r['moat5']}  {str(r['quote'])[:90]}")

    p = os.path.join(OUT, f"retro_irr85_replication_{tag.replace(chr(43),chr(95))}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {p}")


if __name__ == "__main__":
    main()
