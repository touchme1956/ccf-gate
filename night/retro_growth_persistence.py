# night/retro_growth_persistence.py — 歴史検証・案D「成長持続の基礎率」(2026-08-04新設)
#
# 何を測るか:
#   門X(E[r])は g = min(実績cagr3y, gcap, 20%) を「保有年数ぶんそのまま置く」。
#   初回スナップ(2026-08-03)でΩ75+の30社中8社が上限20%に張り付いており、
#   さらに「終端成長の置き方だけで総合が9.4〜13.6%と4pt振れるのに較正材料が無い」と
#   CLAUDE.mdに記録されている。この較正材料を歴史から作るのが本スクリプト。
#
# 方法（偏りの入り口を最小にする＝案Dが最も正確である理由そのもの）:
#   - 定性採点なし（後知恵が入る余地がない）
#   - 母集団は companyfacts.zip の全ファイラー（自分で選ばない＝選択バイアスなし）
#   - 入力は売上系列のみ・USD報告のみ（fill_sht の教訓: ペソ・レアル建てを混ぜると
#     現地インフレを成長と読む）
#   - ビンテージ年Vの時点の trailing 3y CAGR で層別し、その後の実現成長を追う
#
# survivorship の扱い（黙って切らない・no silent caps）:
#   前方窓の途中で系列が終わる社（被買収・上場廃止・報告停止）は除外せず
#   「dropout」として層別ごとに数えて出力する。dropout を無視した中央値は
#   生存者に偏るので、両方（生存者中央値・dropout率）を必ず並記する。
#   さらに **ticker で母集団を絞らない**（初版の穴・2026-08-04当日に是正）——
#   SECのticker表は「今日の」登録社なので、2012年以降に買収・上場廃止された社は
#   表に無く、ticker必須にすると退場社が母集団から最初から消える＝dropout率が
#   過小に出る。識別はCIKで行い、tickerは参考情報として残す。
#   （注: ticker無しには債券発行子会社等の重複ファイラーも混じる。has_ticker別の
#   集計を併記し、二つの断面が大きく食い違えば掘る）
#
# 実装の由来（二重実装を作らない・v9.9.65の教訓）:
#   collect() と系列の接ぎ方(SEAM_TOL=0.02)は gate0_v8_5.py (L119-214) の正典実装から
#   持ってきた。gate0側を変えたらここも同期すること。pick_series は固定窓・全年必須の
#   設計なので、ここでは同じ接ぎ規則を「窓なし・年ラベル辞書」に写した merge_years() を使う
#   （年数を要素数で数えない＝ルール7の「年ラベルの差で数える」を維持）。
#
# 実行: python3 night/retro_growth_persistence.py            # 全ビンテージ
# 出力: out/retro_growth_persistence.json ＋ 標準出力にサマリ
import json, os, sys, time, zipfile, datetime, collections, statistics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP_PATH = os.path.join(BASE, "companyfacts.zip")
OUT_PATH = os.path.join(BASE, "out", "retro_growth_persistence.json")

EMAIL = "fortis5280@gmail.com"
SEAM_TOL = 0.02  # gate0_v8_5.py L69 と同値

# 売上タグ: gate0_v8_5.py TAGS["revenue"] と同一（候補＝代替。構成要素ではない）
REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
            "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "Revenue",
            "RevenueFromContractsWithCustomers"]

# ビンテージ: XBRLの実質的な始まり(FY2009・大手はFY2008が比較年として載る)から、
# trailing 3y が組める最初の年は 2012。前方10年窓が閉じるのは 2012-2015 ビンテージのみ。
VINTAGES = list(range(2012, 2023))
HORIZONS = [3, 5, 8, 10, 13]

# 層別（trailing 3y CAGR）。20%は門Xの g 上限＝一番知りたい線
BUCKETS = [("ge30", 0.30, None), ("20to30", 0.20, 0.30), ("15to20", 0.15, 0.20),
           ("10to15", 0.10, 0.15), ("5to10", 0.05, 0.10), ("0to5", 0.0, 0.05),
           ("neg", None, 0.0)]

# 規模の床: 門の対象はほぼ大型なので、全社と併せて売上5億$以上の層も出す
SIZE_FLOOR = 500e6


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def collect_revenue(facts):
    """gate0_v8_5.collect() の revenue 専用版（同一ロジック・USDのみ）。
    年次(330-400日)のフローだけを拾い、同年重複は filed の新しい方を採る。"""
    out = []
    for taxo in ("us-gaap", "ifrs-full"):
        ns = facts.get(taxo)
        if not ns:
            continue
        for tag in REV_TAGS:
            node = ns.get(tag)
            if not node:
                continue
            for unit, ents in node.get("units", {}).items():
                if unit != "USD":  # USD報告のみ（インフレ混入の防止）
                    continue
                d = {}
                for e in ents:
                    en = e.get("end")
                    st = e.get("start")
                    fl = e.get("filed", "")
                    if not en or not st:
                        continue
                    try:
                        if not (330 <= (d2(en) - d2(st)).days <= 400):
                            continue
                    except Exception:
                        continue
                    y = int(en[:4])
                    if y not in d or fl > d[y][1]:
                        d[y] = (float(e["val"]), fl)
                if d:
                    out.append((tag, {y: v for y, (v, _) in d.items()}))
    return out


def merge_years(cands):
    """候補（代替タグ）を年ラベル辞書へ接ぐ。主系列＝被覆年数が最大の候補。
    他候補は「重なる年が SEAM_TOL 以内で一致するときだけ」欠けた年を埋める
    （gate0 pick_series L197-211 と同じ接ぎ規則の窓なし版）。"""
    if not cands:
        return None
    cands = sorted(cands, key=lambda c: -len(c[1]))
    merged = dict(cands[0][1])
    for tag, d in cands[1:]:
        overlap = [y for y in merged if y in d]
        if not all(merged[y] == 0 or abs(d[y] - merged[y]) / abs(merged[y]) <= SEAM_TOL
                   for y in overlap):
            continue
        for y, v in d.items():
            if y not in merged:
                merged[y] = v
    return merged


def cagr(v0, v1, years):
    if v0 is None or v1 is None or v0 <= 0 or v1 <= 0 or years <= 0:
        return None
    return (v1 / v0) ** (1.0 / years) - 1.0


def bucket_of(g):
    for name, lo, hi in BUCKETS:
        if (lo is None or g >= lo) and (hi is None or g < hi):
            return name
    return None


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    i = (len(xs) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (i - lo), 4)


def main():
    if not os.path.exists(ZIP_PATH):
        sys.exit("companyfacts.zip が無い。run_gate0_local.py と同じ場所（リポジトリ直下）に置くこと")
    z = zipfile.ZipFile(ZIP_PATH)
    names = [n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json")]
    print(f"■ companyfacts: {len(names)} ファイル")

    # ticker の有無で「上場ファイラー」に絞る（gate0と同じ）。tickers表はSECから
    import urllib.request
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json",
                                 headers={"User-Agent": f"CCF-Omega-Screener {EMAIL}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tk = json.loads(r.read())
    cik2tk = {}
    for row in tk.values():
        cik2tk.setdefault(int(row["cik_str"]), row["ticker"])

    rows = []           # (ticker, series{year:rev})
    skipped = collections.Counter()
    t0 = time.time()
    for i, name in enumerate(names, 1):
        if i % 3000 == 0:
            el = time.time() - t0
            print(f"    {i}/{len(names)}  採用:{len(rows)}  残り約{el/i*(len(names)-i)/60:.0f}分")
        cik = int(name[3:13])
        tkr = cik2tk.get(cik)  # 無くても除外しない（退場社はtickerが今日の表に無い）
        try:
            facts = json.loads(z.read(name)).get("facts", {})
        except Exception:
            skipped["parse_error"] += 1
            continue
        if not facts:
            skipped["no_facts"] += 1
            continue
        ser = merge_years(collect_revenue(facts))
        if not ser or len(ser) < 4:
            skipped["series_lt4y"] += 1
            continue
        rows.append((tkr, ser))
    print(f"■ 系列構築: 採用 {len(rows)} 社 / 除外 {dict(skipped)}")

    # ---- ビンテージ×層別の集計 -------------------------------------------------
    # obs 1件 = (ビンテージ年, 会社)。trailing = rev[V]/rev[V-3] の3年CAGR。
    # forward H年 = rev[V+H]/rev[V] のCAGR（V+H の年ラベルが無ければ欠測）。
    # dropout = 系列の最終年が V+H より手前（… ただし「まだ未来」の窓と区別する:
    # 最終年が データ末端(2025/2026) に達している社は dropout ではなく censored）。
    data_end = max(max(s) for _, s in rows)  # 実測のデータ末端年
    result = {"generated": datetime.date.today().isoformat(),
              "universe": len(rows), "data_end_year": data_end,
              "seam_tol": SEAM_TOL, "size_floor_usd": SIZE_FLOOR,
              "skipped": dict(skipped), "vintages": {}, "pooled": {}}

    pooled_fwd = collections.defaultdict(lambda: collections.defaultdict(list))
    pooled_path = collections.defaultdict(lambda: collections.defaultdict(list))
    pooled_drop = collections.defaultdict(lambda: collections.Counter())
    pooled_fwd_big = collections.defaultdict(lambda: collections.defaultdict(list))
    # ticker有無の断面（重複ファイラー混入の検知用。大きく食い違えば掘る）
    sanity_tk = collections.defaultdict(lambda: collections.defaultdict(list))

    for V in VINTAGES:
        vres = {"n": 0, "buckets": {}}
        for tkr, ser in rows:
            if V not in ser or (V - 3) not in ser:
                continue
            g3 = cagr(ser[V - 3], ser[V], 3)
            if g3 is None:
                continue
            b = bucket_of(g3)
            if b is None:
                continue
            vres["n"] += 1
            big = ser[V] >= SIZE_FLOOR
            bb = vres["buckets"].setdefault(b, {"n": 0, "n_big": 0})
            bb["n"] += 1
            bb["n_big"] += 1 if big else 0
            last = max(ser)
            for H in HORIZONS:
                if V + H > data_end:
                    continue  # 窓がまだ閉じていない（censored・数えない）
                key = (b, H)
                if (V + H) in ser:
                    f = cagr(ser[V], ser[V + H], H)
                    if f is not None:
                        pooled_fwd[b][H].append(f)
                        if big:
                            pooled_fwd_big[b][H].append(f)
                        if H == 10:
                            sanity_tk[b][bool(tkr)].append(f)
                else:
                    # V+H の年が無い＝途中退場か端点欠測。系列末端で判定
                    if last < V + H:
                        pooled_drop[b][H] += 1
                    # last >= V+H なのに年が抜けている＝タグの穴。欠測として数えない
            # 成長経路（k年目の単年成長率）: 終端成長の較正に使う
            for k in range(1, 14):
                if (V + k) in ser and (V + k - 1) in ser:
                    yk = cagr(ser[V + k - 1], ser[V + k], 1)
                    if yk is not None:
                        pooled_path[b][k].append(yk)
        result["vintages"][V] = vres

    # ---- プール集計の整形 -------------------------------------------------------
    for b, _, _ in BUCKETS:
        entry = {"forward": {}, "forward_big": {}, "dropout": {}, "growth_path": {}}
        for H in HORIZONS:
            xs = pooled_fwd[b][H]
            drop = pooled_drop[b][H]
            n_total = len(xs) + drop
            entry["forward"][H] = {
                "n": len(xs), "dropout_n": drop,
                "dropout_rate": round(drop / n_total, 3) if n_total else None,
                "median": med(xs), "p25": q(xs, 0.25), "p75": q(xs, 0.75),
                "p_ge15": round(sum(1 for x in xs if x >= 0.15) / len(xs), 3) if xs else None,
                "p_ge10": round(sum(1 for x in xs if x >= 0.10) / len(xs), 3) if xs else None,
                "p_neg": round(sum(1 for x in xs if x < 0) / len(xs), 3) if xs else None,
            }
            xb = pooled_fwd_big[b][H]
            entry["forward_big"][H] = {"n": len(xb), "median": med(xb),
                                       "p25": q(xb, 0.25), "p75": q(xb, 0.75),
                                       "p_ge15": round(sum(1 for x in xb if x >= 0.15) / len(xb), 3) if xb else None}
        for k in range(1, 14):
            xs = pooled_path[b][k]
            if xs:
                entry["growth_path"][k] = {"n": len(xs), "median": med(xs)}
        entry["sanity_ticker_split_10y"] = {
            "with_ticker": {"n": len(sanity_tk[b][True]), "median": med(sanity_tk[b][True])},
            "no_ticker": {"n": len(sanity_tk[b][False]), "median": med(sanity_tk[b][False])}}
        result["pooled"][b] = entry

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    json.dump(result, open(OUT_PATH, "w"), ensure_ascii=False, indent=1)
    print(f"\n■ 書き出し: {OUT_PATH}")

    # ---- サマリ（読む用） -------------------------------------------------------
    print("\n=== 成長持続の基礎率（全ビンテージ・プール） ===")
    print("trailing3yCAGR層 | H=5y中央値(n, dropout率) | H=10y中央値(n, dropout率) | 10y後もP(≥15%)")
    for b, _, _ in BUCKETS:
        e = result["pooled"][b]
        f5, f10 = e["forward"].get(5, {}), e["forward"].get(10, {})
        print(f"  {b:8s} | {f5.get('median')} (n={f5.get('n')}, drop={f5.get('dropout_rate')})"
              f" | {f10.get('median')} (n={f10.get('n')}, drop={f10.get('dropout_rate')})"
              f" | {f10.get('p_ge15')}")
    print("\n=== 成長経路（≥20%組の k年目 単年成長率の中央値）＝終端成長の較正材料 ===")
    for b in ("ge30", "20to30"):
        path = result["pooled"][b]["growth_path"]
        line = "  " + b + ": " + "  ".join(f"+{k}y:{path[k]['median']*100:.1f}%" for k in sorted(path))
        print(line)


if __name__ == "__main__":
    main()
