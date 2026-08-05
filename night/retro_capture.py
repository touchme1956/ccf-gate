# night/retro_capture.py — 途中乗りの「継続組」を2018年時点の数字で捕捉できるかの徹底検証（2026-08-05新設）
#
# 問い（ユーザー「もっと調べて捕捉できないか徹底的にデータ取って」）:
#   前半5年(2013-18)の実証がある社のうち、後半8年(2018-26)も年率15%+を出した「継続組」を、
#   2018年に観測できた数字（ファンダメンタルズ・PER・直前リターン）でどこまで見分けられたか。
#
# 正直さの担保:
#   - すべて2018年までに公表済みの数字のみ（look-ahead無し）
#   - 単一ビンテージのin-sample探索なので、複合条件は過剰適合しうる——n(該当数)と
#     ベース確率を必ず並記し、支持の薄い組合せ(n<20)は出さない
# 実行: python3 night/retro_capture.py
import json, os, statistics, itertools

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    p = os.path.join(BASE, "out", name)
    return json.load(open(p)) if os.path.exists(p) else None


C = {r["ticker"]: r for r in load("retro_cohort_2013.json")["rows"] if r.get("ticker")}
R13 = {r["ticker"]: r for r in load("retro_returns_2013_all.json")["rows"] if r.get("tr_cagr") is not None}
R18 = {r["ticker"]: r for r in load("retro_returns_2018.json")["rows"] if r.get("tr_cagr") is not None}
F = {r["ticker"]: r for r in (load("retro_features_2018.json") or {"rows": []})["rows"]}
P18 = {r["ticker"]: r["per"] for r in (load("retro_per_2018_all.json") or {"rows": []})["rows"]}
R17 = {r["ticker"]: r for r in (load("retro_returns_2017.json") or {"rows": []})["rows"]
       if r.get("tr_cagr") is not None}

rows = []
for t in R13:
    if t not in R18 or t not in C:
        continue
    y13, y18 = R13[t]["years"], R18[t]["years"]
    if y13 - y18 < 4:
        continue
    rf = ((1 + R13[t]["tr_cagr"]) ** y13 / (1 + R18[t]["tr_cagr"]) ** y18) ** (1 / (y13 - y18)) - 1
    row = {"t": t, "rf": rf, "r18": R18[t]["tr_cagr"],
           "roicA": C[t].get("fwd_roic_med5_a1"), "cagrA": C[t].get("fwd_cagr_5y"),
           "per18": P18.get(t), **{k: v for k, v in F.get(t, {}).items() if k != "ticker"}}
    if t in R17:  # 直前1年(2017-07→2018-07)のモメンタム
        y17 = R17[t]["years"]
        if y17 - y18 > 0.5:
            row["mom1y"] = ((1 + R17[t]["tr_cagr"]) ** y17 /
                            (1 + R18[t]["tr_cagr"]) ** y18) ** (1 / (y17 - y18)) - 1
    rows.append(row)

demo = [r for r in rows if r["rf"] >= 0.15]                       # 価格実証
demoQ = [r for r in demo if (r["roicA"] or -9) >= 0.15]           # 価格×質の実証
print(f"=== 対象: 全{len(rows)} / 価格実証{len(demo)} / 価格×質の実証{len(demoQ)} ===")


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


FEATS = [("roicA", "実証ROIC(14-18中央値)", False), ("cagrA", "実証成長(13-18)", False),
         ("opm18", "営業利益率2018", False), ("opmD", "利益率の5年変化", False),
         ("accel", "成長の加速度", False), ("rnd18", "R&D/売上", False),
         ("conv58", "FCF転換(14-18)", False), ("payout58", "還元性向(14-18)", False),
         ("gwg", "のれん増加率", True), ("nde18", "純負債/EBITDA", True),
         ("roic18", "門式roic2018", False), ("per18", "PER2018(分割補正)", True),
         ("mom1y", "直前1年リターン", False), ("rf", "前半5年リターン", False)]


def scan(univ, label):
    base = sum(1 for r in univ if r["r18"] >= 0.15) / len(univ)
    print(f"\n--- {label}（n={len(univ)}・継続組ベース確率 {base:.2f}） ---")
    print(f"  {'特徴量':24s} 継続med vs 停滞med | 上位1/4のP(継続) | 下位1/4のP(継続)")
    for k, name, lower_better in FEATS:
        vals = [(r, r.get(k)) for r in univ]
        vals = [(r, v) for r, v in vals if v is not None]
        if len(vals) < 40:
            continue
        cont = [v for r, v in vals if r["r18"] >= 0.15]
        stall = [v for r, v in vals if r["r18"] < 0.15]
        sv = sorted(v for _, v in vals)
        q25, q75 = sv[len(sv) // 4], sv[len(sv) * 3 // 4]
        top = [r for r, v in vals if v >= q75]
        bot = [r for r, v in vals if v <= q25]
        pt = sum(1 for r in top if r["r18"] >= 0.15) / len(top) if top else None
        pb = sum(1 for r in bot if r["r18"] >= 0.15) / len(bot) if bot else None
        mark = " ◀" if (max(pt, pb) - base) >= 0.10 else ""
        print(f"  {name:24s} {med(cont):8.3f} vs {med(stall):8.3f} |"
              f"  {pt:.2f} (n={len(top)}) | {pb:.2f} (n={len(bot)}){mark}")
    return base


scan(rows, "全社（参考）")
scan(demo, "価格実証あり（前半15%+）")
base = scan(demoQ, "価格×質の実証（本命の母集団）")

# ---- 本命母集団の継続組の顔ぶれ（シグナルの中身を目で確かめる） ---------------------
cont = sorted([r for r in demoQ if r["r18"] >= 0.15], key=lambda r: -r["r18"])
print(f"\n--- 価格×質の実証の継続組 {len(cont)}社（後半8年の実り順） ---")
def _f(v, scale=100, suf="%", fmt="{:.1f}"):
    return "—" if v is None else fmt.format(v * scale) + suf


for r in cont:
    print(f"  {r['t']:6s} 前半{r['rf']*100:+5.1f}% → 後半{r['r18']*100:+5.1f}%/年"
          f"  R&D/売上={_f(r.get('rnd18'))}"
          f"  roicA={_f(r.get('roicA'), fmt='{:.0f}')}"
          f"  PER18={_f(r.get('per18'), 1, '')}"
          f"  mom1y={_f(r.get('mom1y'), fmt='{:+.0f}')}")

# ---- 2条件の総当たり（過剰適合に注意・支持n>=25のみ・上位のみ表示） -----------------
print("\n--- 価格×質の実証の中で、さらに効く2条件の組（in-sample・n>=25のみ） ---")
conds = []
for k, name, _ in FEATS:
    vals = sorted(r.get(k) for r in demoQ if r.get(k) is not None)
    if len(vals) < 50:
        continue
    m = vals[len(vals) // 2]
    conds.append((f"{name}>中央値", lambda r, k=k, m=m: r.get(k) is not None and r[k] > m))
    conds.append((f"{name}<中央値", lambda r, k=k, m=m: r.get(k) is not None and r[k] < m))
results = []
for (n1, f1), (n2, f2) in itertools.combinations(conds, 2):
    g = [r for r in demoQ if f1(r) and f2(r)]
    if len(g) < 25:
        continue
    p = sum(1 for r in g if r["r18"] >= 0.15) / len(g)
    results.append((p, len(g), f"{n1} ∧ {n2}"))
for p, n, label in sorted(results, reverse=True)[:8]:
    print(f"  P(継続)={p:.2f} (n={n})  {label}")
print(f"  （ベース {base:.2f}・単一ビンテージのin-sample探索＝上位は過剰適合を含みうる）")

# ---- 在庫（再現用・snapではなく分析結果の記録） -------------------------------------
import datetime
art = {"generated": datetime.date.today().isoformat(),
       "note": "2018年観測可能シグナルによる継続組(後半8年15%+)捕捉の徹底検証。"
               "単一ビンテージin-sample——複合条件は過剰適合を含みうる",
       "n_all": len(rows), "n_demo": len(demo), "n_demoQ": len(demoQ),
       "base_demoQ": round(base, 3),
       "continuers_demoQ": [r["t"] for r in cont],
       "combos_top": [{"p": round(p, 3), "n": n, "cond": label}
                      for p, n, label in sorted(results, reverse=True)[:8]]}
json.dump(art, open(os.path.join(BASE, "out", "retro_capture_2018.json"), "w"),
          ensure_ascii=False, indent=1)
print("■ out/retro_capture_2018.json へ記録")
