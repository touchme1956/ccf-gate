# night/retro_capture2_xval.py — 2018年合格規則の複数アンカー交差検証（2026-08-05新設）
#
# 事前登録基準(2): 2018年アンカーで合格した規則そのものを2017・2016アンカーへ当て、
# 両方で正のリフト（P > そのアンカーのベース）を出すかを見る。閾値(中央値)は
# 各アンカーのdemoQ内で取り直す（分位定義＝事前登録どおり）。
# 注意: 後半窓が重なる（2016/2017アンカーの後半は2018のを包含）ので独立再現ではない
# ——「同一データの別スライスでの整合性テスト」。それでも過剰適合の大半はここで落ちる。
# さらに単独特徴量の向きの安定性（3アンカーで同符号か）も出す。
# 実行: python3 night/retro_capture2_xval.py
import json, os, re, statistics, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    return json.load(open(os.path.join(BASE, "out", name)))


FRAMES = {}
for a in (2018, 2017, 2016):
    fr = load(f"retro_frame_{a}.json")["rows"]
    demo = [r for r in fr if r["rf5"] >= 0.15]
    FRAMES[a] = [r for r in demo if (r.get("fcfpos5") or 0) >= 4 and (r.get("opm") or -9) >= 0.10]

NAME2KEY = {
    "前半リターン": "rf5", "直前1年リターン": "mom1y", "前半の最大DD": "mdd5",
    "高値からの近さ": "prox_hi", "月次ボラ": "vol_m", "陽線月比率": "upmo_r",
    "最悪12ヶ月": "worst12", "粗利率": "gm", "営業利益率": "opm", "営利率5年変化": "opmD5",
    "販管費率": "sga_r", "capex/売上": "capex_r", "資産回転": "aturn", "アクルーアル": "accr",
    "増収年数(0-4)": "streak_rev", "増益率年数(0-4)": "streak_opm", "FCF黒字年数(0-5)": "fcfpos5",
    "利息カバレッジ": "intcov", "現金/資産": "cash_r", "のれん/資産": "gw_r",
    "純発行/売上": "netiss_r", "R&D/売上": "rnd_r", "FCF転換": "conv5", "還元性向": "payout5",
    "売上5年CAGR": "cagr5", "成長の加速度": "accel", "売上規模": "rev",
    "PER(分割補正)": "per18", "実証ROIC(旧・漏れ込み)": "roicA_leaky",
}
FT_NAMES = {"『highly fragmented』": "ft_frag", "『long-term contracts』": "ft_ltc",
            "『recurring revenue』": "ft_rec", "『customer accounted for』": "ft_cust",
            "『intense competition』": "ft_comp"}


def make_pred(term, univ):
    """'名前>med' / '名前<med' / '『…』有' → 述語。中央値はunivで取り直す。ft系は2018のみ。"""
    if term.endswith("有"):
        k = FT_NAMES.get(term[:-1])
        if k is None or not any(k in r for r in univ):
            return None
        return lambda r, k=k: r.get(k) is True
    m = re.match(r"^(.*)(>|<)med$", term)
    if not m:
        return None
    k = NAME2KEY.get(m.group(1))
    if k is None:
        return None
    vals = sorted(r[k] for r in univ if r.get(k) is not None)
    if len(vals) < 50:
        return None
    mid = vals[len(vals) // 2]
    if m.group(2) == ">":
        return lambda r, k=k, mid=mid: r.get(k) is not None and r[k] > mid
    return lambda r, k=k, mid=mid: r.get(k) is not None and r[k] < mid


def evaluate(cond_label, univ):
    preds = []
    for term in cond_label.split(" ∧ "):
        p = make_pred(term, univ)
        if p is None:
            return None
        preds.append(p)
    g = [r for r in univ if all(p(r) for p in preds)]
    if len(g) < 8:
        return {"n": len(g), "p": None}
    cap = sum(1 for r in g if r["r18"] >= 0.15)
    return {"n": len(g), "p": cap / len(g), "cap": cap,
            "med": statistics.median(r["r18"] for r in g)}


art18 = load("retro_capture2_2018.json")
rules = art18["pre_registered_pass"]
print(f"=== 2018年合格 {len(rules)} 規則の交差検証（閾値は各アンカーで取り直し） ===")
bases = {a: sum(1 for r in FRAMES[a] if r["r18"] >= 0.15) / len(FRAMES[a]) for a in FRAMES}
print("  ベース: " + "  ".join(f"{a}={bases[a]:.2f}" for a in (2018, 2017, 2016)))
survivors = []
for ru in rules:
    line = f"  [{ru['p']:.2f} n={ru['n']}] {ru['cond']}"
    ok = True
    evs = {}
    for a in (2017, 2016):
        ev = evaluate(ru["cond"], FRAMES[a])
        evs[a] = ev
        if ev is None:
            line += f" | {a}:ft系で評価不能"
            ok = False
            break
        if ev["p"] is None:
            line += f" | {a}:n={ev['n']}<8"
            ok = False
        else:
            line += f" | {a}: P={ev['p']:.2f}(n={ev['n']})"
            if ev["p"] <= bases[a]:
                ok = False
    print(line + ("  ◎両アンカーで正リフト" if ok else ""))
    if ok:
        survivors.append({**ru, "xval": {str(a): evs[a] for a in evs}})

print(f"\n=== 生存 {len(survivors)}/{len(rules)} ===")

# --- 単独特徴量の向きの安定性（上位1/4のリフトが3アンカーで同符号か） -----------------
print("\n--- 単独特徴量の3アンカー安定性（demoQ・上位1/4リフト） ---")
print(f"  {'特徴量':16s} 2018    2017    2016   安定?")
for name, k in NAME2KEY.items():
    lifts = []
    for a in (2018, 2017, 2016):
        univ = FRAMES[a]
        vals = [(r, r.get(k)) for r in univ]
        vals = [(r, v) for r, v in vals if v is not None]
        if len(vals) < 60:
            lifts.append(None)
            continue
        sv = sorted(v for _, v in vals)
        q75 = sv[len(sv) * 3 // 4]
        top = [r for r, v in vals if v >= q75]
        base = sum(1 for r, _ in vals if r["r18"] >= 0.15) / len(vals)
        lifts.append(sum(1 for r in top if r["r18"] >= 0.15) / len(top) - base)
    if any(x is None for x in lifts):
        continue
    stable = all(x > 0.03 for x in lifts) or all(x < -0.03 for x in lifts)
    print(f"  {name:16s} " + " ".join(f"{x:+.2f}  " for x in lifts) + ("  ◎" if stable else ""))

json.dump({"generated": datetime.date.today().isoformat(),
           "bases": {str(a): round(b, 3) for a, b in bases.items()},
           "rules_tested": len(rules), "survivors": survivors},
          open(os.path.join(BASE, "out", "retro_capture2_xval.json"), "w"),
          ensure_ascii=False, indent=1)
print("■ out/retro_capture2_xval.json へ記録")
