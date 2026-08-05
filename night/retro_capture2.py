# night/retro_capture2.py — 30%の壁の徹底検証・合流分析器（2026-08-05新設）
#
# 問い（ユーザー「ではこれで30%の壁を越えるため調べ上げて」）:
#   途中乗りの継続組（後半も年率15%+）の事前捕捉率 P≈0.26-0.41 の天井を、
#   5系統の新採取データ（厳密特徴量20系統・値動きの質7系統・堀の言語・業種・複数アンカー）で破れるか。
#
# 事前登録の成功基準（分析前に固定・動かさない）:
#   (1) 精度 P(継続|選別) >= 0.50 かつ 捕捉 >= 継続組の1/3 …2018年アンカー
#   (2) 同じ規則が2017・2016年アンカーでも正のリフト（窓が重なる擬似再現である旨併記）
#   (3) 副次: 選別バスケットの後半リターン中央値 >= 15%/年
#
# look-ahead の正直さ:
#   - 前半リターン rf5 は path（period2=アンカー固定のYahoo系列）＝厳密
#   - features2 は filed<=アンカー7/1 の厳密ガード
#   - fulltext は提出日窓 2016-07〜2018-06 ＝2018年アンカーでのみ使用（2017/2016再現には使わない）
#   - cohort の roicA(fwd_roic_med5_a1=2014-18) は12月決算社のFY2018が2019年2月提出＝数ヶ月の漏れ
#     を含む(旧demoQ定義)。主定義は features2 の厳密版に替え、旧定義は比較参考として併記
# 実行: python3 night/retro_capture2.py [--anchor 2018]
import json, os, sys, statistics, itertools, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANCHOR = 2018
for i, a in enumerate(sys.argv):
    if a == "--anchor" and i + 1 < len(sys.argv):
        ANCHOR = int(sys.argv[i + 1])


def load(name):
    p = os.path.join(BASE, "out", name)
    return json.load(open(p)) if os.path.exists(p) else None


MON = load("retro_monthly_2013_2018.json")
RB = {r["ticker"]: r for r in load(f"retro_returns_{ANCHOR}.json")["rows"]
      if r.get("tr_cagr") is not None}
F2 = {r["ticker"]: r for r in load(f"retro_features2_{ANCHOR}.json")["rows"]}
FT = {r["ticker"]: r for r in (load("retro_fulltext_2018.json") or {"rows": []})["rows"]}
SIC = {r["ticker"]: r for r in load("retro_sic.json")["rows"]}
C = {r["ticker"]: r for r in load("retro_cohort_2013.json")["rows"] if r.get("ticker")}
P18 = {r["ticker"]: r["per"] for r in (load("retro_per_2018_all.json") or {"rows": []})["rows"]}

CUT = datetime.datetime(ANCHOR, 7, 1).timestamp()
CUT12 = datetime.datetime(ANCHOR - 1, 7, 1).timestamp()


def first_half(t):
    """月次在庫をアンカーで切った前半CAGR・直前1年・値動きの質(その場計算)"""
    pts = [(ts, v) for ts, v in (MON.get(t) or []) if ts < CUT]
    if len(pts) < 33:  # 2013-07起点で33ヶ月未満は実証と呼ばない(2016アンカー=36ヶ月が上限)
        return None
    years = (pts[-1][0] - pts[0][0]) / (365.25 * 86400)
    if years < 2.5 or pts[0][1] <= 0:
        return None
    out = {"rf5": (pts[-1][1] / pts[0][1]) ** (1 / years) - 1}
    m12 = [(ts, v) for ts, v in pts if ts >= CUT12]
    if len(m12) >= 11:
        out["mom1y"] = m12[-1][1] / m12[0][1] - 1
    peak, mdd = 0.0, 0.0
    for _, v in pts:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    out["mdd5"] = mdd
    out["prox_hi"] = pts[-1][1] / peak
    rets = [pts[i][1] / pts[i - 1][1] - 1 for i in range(1, len(pts))]
    out["vol_m"] = statistics.pstdev(rets)
    out["upmo_r"] = sum(1 for r in rets if r > 0) / len(rets)
    w12 = [pts[i][1] / pts[i - 12][1] - 1 for i in range(12, len(pts))]
    if w12:
        out["worst12"] = min(w12)
    return out


rows = []
for t, rb in RB.items():
    fh = first_half(t)
    if fh is None or t not in F2:
        continue
    row = {"t": t, "r18": rb["tr_cagr"], **fh,
           **{k: v for k, v in F2[t].items() if k not in ("ticker", "fy", "fy_end")},
           "sic2": SIC.get(t, {}).get("sic2"),
           "roicA_leaky": C.get(t, {}).get("fwd_roic_med5_a1")}
    if ANCHOR == 2018:
        row["per18"] = P18.get(t)
        ftr = FT.get(t, {})
        if not ftr.get("no10k"):
            for k in ("ft_frag", "ft_ltc", "ft_rec", "ft_cust", "ft_comp"):
                if k in ftr:
                    row[k] = ftr[k]
    rows.append(row)

# --- 母集団の定義（主=厳密。旧demoQ(roicA)は漏れ込みの比較参考） ---------------------
demo = [r for r in rows if r["rf5"] >= 0.15]
# 質の実証(厳密): 5年FCF黒字>=4年 ∧ 直近営業利益率>=10% ＝2018-07時点で全て公表済みの数字
demoQ = [r for r in demo if (r.get("fcfpos5") or 0) >= 4 and (r.get("opm") or -9) >= 0.10]
demoQ_old = [r for r in demo if (r.get("roicA_leaky") or -9) >= 0.15]
print(f"=== アンカー{ANCHOR}: 全{len(rows)} / 価格実証{len(demo)} / "
      f"価格×質(厳密){len(demoQ)} / 価格×質(旧roicA・漏れ込み){len(demoQ_old)} ===")


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


NUM_FEATS = [
    ("rf5", "前半リターン"), ("mom1y", "直前1年リターン"), ("mdd5", "前半の最大DD"),
    ("prox_hi", "高値からの近さ"), ("vol_m", "月次ボラ"), ("upmo_r", "陽線月比率"),
    ("worst12", "最悪12ヶ月"),
    ("gm", "粗利率"), ("opm", "営業利益率"), ("opmD5", "営利率5年変化"),
    ("sga_r", "販管費率"), ("capex_r", "capex/売上"), ("aturn", "資産回転"),
    ("accr", "アクルーアル"), ("streak_rev", "増収年数(0-4)"), ("streak_opm", "増益率年数(0-4)"),
    ("fcfpos5", "FCF黒字年数(0-5)"), ("intcov", "利息カバレッジ"), ("cash_r", "現金/資産"),
    ("gw_r", "のれん/資産"), ("netiss_r", "純発行/売上"), ("rnd_r", "R&D/売上"),
    ("conv5", "FCF転換"), ("payout5", "還元性向"), ("cagr5", "売上5年CAGR"),
    ("accel", "成長の加速度"), ("rev", "売上規模"), ("per18", "PER(分割補正)"),
    ("roicA_leaky", "実証ROIC(旧・漏れ込み)"),
]
BIN_FEATS = [("ft_frag", "『highly fragmented』"), ("ft_ltc", "『long-term contracts』"),
             ("ft_rec", "『recurring revenue』"), ("ft_cust", "『customer accounted for』"),
             ("ft_comp", "『intense competition』")]


def scan(univ, label):
    n = len(univ)
    base = sum(1 for r in univ if r["r18"] >= 0.15) / n
    print(f"\n--- {label}（n={n}・継続ベース {base:.2f}・後半中央値 "
          f"{med([r['r18'] for r in univ])*100:.1f}%/年） ---")
    print(f"  {'特徴量':22s} 継続med vs 停滞med | 上位1/4 P | 下位1/4 P")
    hits = []
    for k, name in NUM_FEATS:
        vals = [(r, r.get(k)) for r in univ]
        vals = [(r, v) for r, v in vals if v is not None]
        if len(vals) < max(40, n // 3):
            continue
        cont = [v for r, v in vals if r["r18"] >= 0.15]
        stall = [v for r, v in vals if r["r18"] < 0.15]
        sv = sorted(v for _, v in vals)
        q25, q75 = sv[len(sv) // 4], sv[len(sv) * 3 // 4]
        top = [r for r, v in vals if v >= q75]
        bot = [r for r, v in vals if v <= q25]
        pt = sum(1 for r in top if r["r18"] >= 0.15) / len(top)
        pb = sum(1 for r in bot if r["r18"] >= 0.15) / len(bot)
        mark = " ◀" if max(pt, pb) - base >= 0.10 else ""
        if mark:
            hits.append((k, name, pt, pb, base))
        print(f"  {name:22s} {med(cont):8.3f} vs {med(stall):8.3f} |"
              f" {pt:.2f}(n={len(top)}) | {pb:.2f}(n={len(bot)}){mark}")
    for k, name in BIN_FEATS:
        vals = [(r, r.get(k)) for r in univ if r.get(k) is not None]
        yes = [r for r, v in vals if v]
        no = [r for r, v in vals if not v]
        if len(yes) < 12 or len(no) < 12:
            continue
        py = sum(1 for r in yes if r["r18"] >= 0.15) / len(yes)
        pn = sum(1 for r in no if r["r18"] >= 0.15) / len(no)
        mark = " ◀" if max(py, pn) - base >= 0.10 else ""
        print(f"  {name:22s} {'':21s} | 有 {py:.2f}(n={len(yes)}) | 無 {pn:.2f}(n={len(no)}){mark}")
    return base, hits


scan(rows, "全社（参考）")
base_demo, hits_demo = scan(demo, "価格実証（rf5≥15%）")
base, hits = scan(demoQ, "価格×質の実証（厳密・本命）")

# --- 業種の基礎率（demo内・n>=10） --------------------------------------------------
print("\n--- 業種(SIC2)ごとの継続基礎率（価格実証内・n>=10） ---")
by = {}
for r in demo:
    by.setdefault(r.get("sic2") or "?", []).append(r)
for s, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
    if len(g) < 10:
        continue
    p = sum(1 for r in g if r["r18"] >= 0.15) / len(g)
    desc = next((SIC[r["t"]].get("sicDesc", "") for r in g if r["t"] in SIC), "")
    print(f"  SIC{s} n={len(g):3d} P(継続)={p:.2f}  例:{desc[:28]}")

# --- 複合条件の探索（2条件・3条件）＋事前登録基準の判定 -------------------------------
CONT_N = sum(1 for r in demoQ if r["r18"] >= 0.15)
print(f"\n--- 複合条件（demoQ n={len(demoQ)}・継続組{CONT_N}社・"
      f"合格線: P>=0.50 ∧ 捕捉>={CONT_N}/3={CONT_N/3:.0f}社以上） ---")
conds = []
for k, name in NUM_FEATS:
    vals = sorted(r[k] for r in demoQ if r.get(k) is not None)
    if len(vals) < 50:
        continue
    m = vals[len(vals) // 2]
    conds.append((f"{name}>med", lambda r, k=k, m=m: r.get(k) is not None and r[k] > m))
    conds.append((f"{name}<med", lambda r, k=k, m=m: r.get(k) is not None and r[k] < m))
for k, name in BIN_FEATS:
    if sum(1 for r in demoQ if r.get(k)) >= 15:
        conds.append((f"{name}有", lambda r, k=k: r.get(k) is True))
results = []
for combo in itertools.chain(itertools.combinations(range(len(conds)), 2),
                             itertools.combinations(range(len(conds)), 3)):
    g = [r for r in demoQ if all(conds[i][1](r) for i in combo)]
    if len(g) < 20:
        continue
    cap = sum(1 for r in g if r["r18"] >= 0.15)
    p = cap / len(g)
    results.append((p, cap, len(g), med([r["r18"] for r in g]),
                    " ∧ ".join(conds[i][0] for i in combo),
                    [r["t"] for r in g if r["r18"] >= 0.15]))
results.sort(reverse=True)
passing = [x for x in results if x[0] >= 0.50 and x[1] >= CONT_N / 3]
print(f"  探索した組合せ: {len(results)}（n>=20のみ）・事前登録基準の合格: {len(passing)}")
for p, cap, n, m, label, names in results[:12]:
    flag = " ★合格" if (p >= 0.50 and cap >= CONT_N / 3) else ""
    print(f"  P={p:.2f} 捕捉{cap}/{CONT_N} (n={n}) 後半med{m*100:+.1f}%  {label}{flag}")

art = {"generated": datetime.date.today().isoformat(), "anchor": ANCHOR,
       "n": {"all": len(rows), "demo": len(demo), "demoQ": len(demoQ)},
       "base": {"demo": round(base_demo, 3), "demoQ": round(base, 3)},
       "continuers_demoQ": sorted(r["t"] for r in demoQ if r["r18"] >= 0.15),
       "pre_registered_pass": [{"p": round(p, 3), "capture": c, "n": n, "cond": lbl}
                               for p, c, n, m, lbl, _ in passing],
       "top_combos": [{"p": round(p, 3), "capture": c, "n": n, "med_r18": round(m, 3),
                       "cond": lbl, "captured": names} for p, c, n, m, lbl, names in results[:12]]}
json.dump(art, open(os.path.join(BASE, "out", f"retro_capture2_{ANCHOR}.json"), "w"),
          ensure_ascii=False, indent=1)
json.dump({"anchor": ANCHOR, "rows": rows},
          open(os.path.join(BASE, "out", f"retro_frame_{ANCHOR}.json"), "w"))
print(f"■ out/retro_capture2_{ANCHOR}.json / retro_frame_{ANCHOR}.json へ記録")
