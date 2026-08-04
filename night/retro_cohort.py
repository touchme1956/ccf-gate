# night/retro_cohort.py — 歴史検証・案C「asofビンテージのコホート検証」(2026-08-04新設)
#
# 何を測るか:
#   門の機械の背骨（gate0の7点スクリーン＝売上CAGR/営業利益率/ROIC水準・最低値/FCF転換/
#   営業黒字/FCF黒字）を **asof年時点のデータだけ** で全上場に当て、
#   通過群と非通過群の「その後」——前方の売上成長・ROIC持続・退場率——を実測する。
#   これが出ると「門の機械部分に判別力があるか」が推測でなく数字で言える。
#
# look-ahead の防ぎ方（構造で保証する）:
#   gate0_v8_5.py の関数定義部（collect / pick_series / derive_opinc / evaluate）を
#   **execでそのまま取り込み**、per-company ループの `yrs = ys[-YEARS:]`（最新5年）だけを
#   `yrs = [asof-4 .. asof]`（ビンテージ窓・全年必須）へ差し替える。
#   評価関数そのものは1行も変えないので、「2012年の門0」と「今日の門0」は同じ規則で動く。
#   （二重実装を作らない＝v9.9.65の教訓。gate0側が変わればここも自動で追随する）
#
# 前方アウトカム（すべて companyfacts 内で完結＝ファンダメンタルズ）:
#   - fwd_cagr_5y / 10y / 13y : asof→asof+H の売上CAGR（USD・年ラベルで数える）
#   - fwd_roic_med5_H         : asof+1..asof+5 / asof+6..asof+10 窓の ROIC(gate0式) 中央値
#   - fwd_opm_10y             : asof+10 年の営業利益率
#   - last_year / dropout     : 系列の末端（被買収・上場廃止・報告停止は除外せず数える）
#   価格リターンは別スクリプト（retro_fetch_returns.py）で後結合する——
#   audit_er_realized の教訓どおり配当込みで取れる経路を検証してから使う。
#
# 制約（正直に書く）:
#   - USD報告のみ（インフレ混入防止・fill_shtの教訓）。日本株・現地通貨ADRは対象外
#   - ROICは gate0式（NOPAT=営業利益×0.79・IC=自己資本+有利子負債）＝門式(7-b)とは
#     控除項が違う。同じ式を両群に当てるので**比較としての妥当性**は保たれるが、
#     Ωのroic欄そのものの検証ではない（そこは審査プロトコルの領分）
#   - XBRLの実質的始まりがFY2008-2009なので、asofは2012が最古（trailing 5年が組める線）
#
# 実行: python3 night/retro_cohort.py            # asof=2012
#       python3 night/retro_cohort.py --asof 2014
# 出力: out/retro_cohort_{asof}.json ＋ 標準出力にサマリ
import json, os, re, sys, time, zipfile, datetime, collections, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)  # gate0スライスの SAVE_DIR="." がリポジトリ直下を指すように
sys.path.insert(0, os.path.join(BASE, "night"))
from retro_growth_persistence import collect_revenue, merge_years, cagr  # 同じ接ぎ規則を共有

ASOF = 2012
for i, a in enumerate(sys.argv):
    if a == "--asof" and i + 1 < len(sys.argv):
        ASOF = int(sys.argv[i + 1])

OUT_PATH = os.path.join(BASE, "out", f"retro_cohort_{ASOF}.json")

# ---- gate0_v8_5.py の定義部をそのまま取り込む --------------------------------------
# EMAIL〜（定数・collect・pick_series・sti_series・derive_opinc・evaluate）を実行する。
# PART A（漏斗の全社ループ）の手前で切る。zipは存在するので再DLは走らない。
src = open(os.path.join(BASE, "gate0_v8_5.py"), encoding="utf-8").read()
start = src.index("EMAIL =")
end = src.index("# ============================ PART A")
G = {}
exec(compile(src[start:end], "gate0_v8_5.py[defs]", "exec"), G)
collect, pick_series, sti_series, derive_opinc, evaluate = \
    G["collect"], G["pick_series"], G["sti_series"], G["derive_opinc"], G["evaluate"]
CIK2TK, YEARS = G["CIK2TK"], G["YEARS"]
d2 = G["d2"]

ZIP_PATH = os.path.join(BASE, "companyfacts.zip")
HORIZONS = [5, 10, 13]


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def roic_med_window(facts, unit, yrs, fye_all):
    """指定窓の ROIC(gate0式: op*0.79/(eq+lt+st)) 中央値。窓の全年が要る。"""
    fye = {y: fye_all[y] for y in yrs if y in fye_all}
    if len(fye) < len(yrs):
        return None
    STOCK = {"equity", "debt_lt", "debt_st"}

    def grab(key, zero=False):
        v, _, _ = pick_series(collect(facts, key), yrs, unit_lock=unit, fye=fye,
                              stock=(key in STOCK))
        if v is None and zero:
            return [0.0] * len(yrs)
        return v

    eq, op = grab("equity"), grab("opinc")
    lt, st = grab("debt_lt", zero=True), grab("debt_st", zero=True)
    if eq is None or op is None:
        return None
    vals = []
    for k in range(len(yrs)):
        ic = eq[k] + lt[k] + st[k]
        if ic <= 0:
            return None
        vals.append(op[k] * 0.79 / ic)
    return round(statistics.median(vals), 4)


def main():
    z = zipfile.ZipFile(ZIP_PATH)
    names = [n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json")]
    yrs = list(range(ASOF - YEARS + 1, ASOF + 1))  # asof-4 .. asof（全年必須）
    print(f"■ asof={ASOF} 窓={yrs[0]}-{yrs[-1]}  {len(names)} ファイル")
    ROWS, QUAR = [], collections.Counter()
    t0 = time.time()
    for i, name in enumerate(names, 1):
        if i % 3000 == 0:
            el = time.time() - t0
            print(f"    {i}/{len(names)}  判定:{len(ROWS)}  残り約{el/i*(len(names)-i)/60:.0f}分")
        cik = int(name[3:13])
        # tickerで母集団を絞らない（今日のticker表に無い＝退場社を最初から消してしまう
        # survivorshipの穴。retro_growth_persistence.py と同じ是正・2026-08-04）
        tkr = CIK2TK.get(cik)
        try:
            j = json.loads(z.read(name))
            facts = j.get("facts", {})
        except Exception:
            continue
        if not facts:
            continue
        rev_c = collect(facts, "revenue")
        if not rev_c:
            QUAR["no_revenue_tag"] += 1
            continue
        # USDのみ・ビンテージ窓の全年が要る（gate0の「最新5年」をasof窓へ差し替えた一点だけが変更）
        rev_c_usd = [(t, u, d) for (t, u, d) in rev_c if u == "USD"]
        if not rev_c_usd:
            QUAR["non_usd"] += 1
            continue
        v, u0, lin = pick_series(rev_c_usd, yrs, unit_lock="USD")
        if v is None:
            QUAR["window_incomplete"] += 1
            continue
        rev = v
        unit = "USD"
        fye_all = {}
        for (_, uu, d) in rev_c_usd:
            for y, t in d.items():
                en = t[0]
                if y not in fye_all or en > fye_all[y]:
                    fye_all[y] = en
        fye = {y: fye_all[y] for y in yrs}
        STOCK = {"equity", "debt_lt", "debt_st", "cash", "gw"}

        def grab(key, zero=False):
            vv, _, _ = pick_series(collect(facts, key), yrs, unit_lock=unit, fye=fye,
                                   stock=(key in STOCK))
            if vv is None and zero:
                return [0.0] * YEARS
            return vv

        ni, ocf, eq = grab("ni"), grab("ocf"), grab("equity")
        cap = grab("capex", zero=True)
        lt = grab("debt_lt", zero=True)
        st = grab("debt_st", zero=True)
        op, op_src = grab("opinc"), "reported"
        if op is None:
            op = derive_opinc(facts, yrs, unit, fye)
            op_src = "derived"
        miss = [k for k, vv in [("ni", ni), ("ocf", ocf), ("equity", eq), ("opinc", op)] if vv is None]
        if miss:
            QUAR["欠損:" + miss[0]] += 1
            continue
        m, err = evaluate(rev, op, ni, ocf, cap, eq, lt, st)
        if err:
            QUAR[err] += 1
            continue
        if m["warn_anomaly"] and op_src == "derived":
            QUAR["derived_suspect"] += 1
            continue
        # through-cycle med5（v9.9.72の形。gate0式ROICの窓内中央値）
        roics = [op[k] * 0.79 / (eq[k] + lt[k] + st[k]) for k in range(YEARS)]
        m["roic_med5"] = round(statistics.median(roics), 4)

        # ---- 前方アウトカム（asofより後のデータはここでだけ使う） ----------------
        ser = merge_years(collect_revenue(facts)) or {}
        last = max(ser) if ser else None
        fwd = {}
        for H in HORIZONS:
            if ser.get(ASOF) and ser.get(ASOF + H):
                fwd[f"fwd_cagr_{H}y"] = round(cagr(ser[ASOF], ser[ASOF + H], H), 4)
            else:
                fwd[f"fwd_cagr_{H}y"] = None
        fwd["fwd_roic_med5_a1"] = roic_med_window(facts, unit, list(range(ASOF + 1, ASOF + 6)), fye_all)
        fwd["fwd_roic_med5_a2"] = roic_med_window(facts, unit, list(range(ASOF + 6, ASOF + 11)), fye_all)
        # 前方の営業利益率（asof+10年）
        op10, _, _ = pick_series(collect(facts, "opinc"), [ASOF + 10], unit_lock=unit,
                                 fye={ASOF + 10: fye_all.get(ASOF + 10, "")}) \
            if (ASOF + 10) in fye_all else (None, None, None)
        fwd["fwd_opm_10y"] = round(op10[0] / ser[ASOF + 10], 4) \
            if (op10 and ser.get(ASOF + 10)) else None
        m.update({"ticker": tkr, "cik": cik, "has_ticker": bool(tkr),
                  "name": j.get("entityName", "")[:40],
                  "rev_asof": rev[-1], "op_src": op_src, "last_year": last, **fwd})
        ROWS.append(m)
    print(f"    処理完了: {len(ROWS)} 社  ({(time.time()-t0)/60:.0f}分)  隔離: "
          + ", ".join(f"{k}:{v}" for k, v in QUAR.most_common(6)))

    result = {"generated": datetime.date.today().isoformat(), "asof": ASOF,
              "window": [yrs[0], yrs[-1]], "n": len(ROWS), "quarantine": dict(QUAR),
              "note": "gate0式スクリーンをasof窓に当てた機械の背骨の検証。ROICはgate0式(のれん・無形を控除しない)",
              "rows": ROWS}
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    json.dump(result, open(OUT_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"■ 書き出し: {OUT_PATH}")

    # ---- サマリ: スコア層別の前方アウトカム ------------------------------------
    # 生存の線は「データ末端−1年」まで報告があるか（asof+13がデータ末端を超えると
    # 全社が退場に見える——初版がこのバグを踏んだ。FY2026の10-Kはまだ存在しない）
    data_end = max((r["last_year"] or 0) for r in ROWS)
    alive_line = min(ASOF + 13, data_end - 1)
    print(f"\n=== asof={ASOF} スコア層別の前方実測（中央値・生存線={alive_line}年） ===")
    print("score | n | fwd売上CAGR10y | fwd ROIC med5(+6..+10) | 生存率 | 大型(売上5億$+)のみ fwd10y")
    for s in range(7, -1, -1):
        g = [r for r in ROWS if r["score"] == s]
        if not g:
            continue
        alive = [r for r in g if r["last_year"] and r["last_year"] >= alive_line]
        big = [r for r in g if r["rev_asof"] >= 500e6]
        print(f"  {s} | {len(g)} | {med([r['fwd_cagr_10y'] for r in g])}"
              f" | {med([r['fwd_roic_med5_a2'] for r in g])}"
              f" | {round(len(alive)/len(g), 3)}"
              f" | {med([r['fwd_cagr_10y'] for r in big])} (n={len(big)})")


if __name__ == "__main__":
    main()
