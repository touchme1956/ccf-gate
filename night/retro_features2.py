# night/retro_features2.py — asof時点で観測可能だった拡張ファンダメンタルズ特徴量（2026-08-05新設）
#
# 目的: 「途中乗り」検証(retro_returns_2018)の対象956社について、2018-07-01時点で
#   実際に読めた申告値だけから拡張特徴量を採る。retro_features_2018.py の後継。
#
# look-ahead の防ぎ方（旧版との最大の違い）:
#   旧 retro_features_2018.py は年ラベル(≤2018)で切っていたが、12月決算社のFY2018は
#   2019年2月提出＝2018-07-01には読めない。本版は **filed <= asof-07-01** のエントリだけを使い、
#   同一(タグ,年)の重複は「期限内で最も新しいfiled」を採る（期限内の訂正は反映・期限後は不可視）。
#
# 「直近FY」= filed期限内の年次(330-400日)売上エントリのうち end が最新のもの（アンカー）。
# 「5年窓」 = アンカーから遡る5会計年度（ラベル a-4..a）。streak系0-4 / fcfpos5 0-5 と整合。
#
# 欠測の流儀（ルール7「欠測をゼロと読むな」との折り合い・各特徴量で明示）:
#   - BS/IS項目（売上・営利・純利・総資産・現金・利息）: 欠測は欠測。0と読まない。
#   - CF活動項目（capex・配当・自社株買い・株式発行）は三値で読む:
#       (1) 年次値あり → その値
#       (2) 年次値は無いが同年ラベルに触れるエントリ（四半期YTD等）がある → **欠測**
#           ——活動は実在するのに年次が採れない社（実例NVDA: FY2016-18の年次capexが
#           us-gaap側に無く custom拡張タグ。四半期YTDだけ残る）に0を作らせない
#       (3) その年に触れる報告が一つも無い → 活動なし＝0（CF計算書は活動が無い行を載せない）
#   - R&D: タグが期限内に一度も無い社は0（本当にR&Dの無い社は報告しない）。
#     タグはあるのにアンカー年だけ無いのは欠測（もっともらしい0を作らない）。
#   - のれん: Goodwillタグが期限内に一度も無い社は0（IRMD前例）。あるのにアンカー末日に無いのは欠測。
#   - 支払利息: 利息ゼロ・タグ無しは欠測（intcov=∞のもっともらしい代値を作らない）。
#
# インスタント項目（Assets/現金/のれん）は年ラベルでなく **アンカーFYの末日±10日** で照合する
# （年ラベル照合だと10-Q由来のQ末残高が混入する——年次PLとBSの期日を必ず揃える）。
#
# 実行: python3 night/retro_features2.py --asof 2018 → out/retro_features2_2018.json
import argparse
import datetime
import json
import os
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


# ---- タグ候補（参考実装 retro_features_2018.py と同じ流儀・年ごとに先頭一致で解決） ----
REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
       "SalesRevenueServicesNet",
       "RegulatedAndUnregulatedOperatingRevenue"]  # 公益の総売上タグ（AWK等）。
# 意図して入れないもの: RefiningAndMarketingRevenue（MPCの主要行だが関連当事者売上を含まない構成要素）、
# REITの賃料タグ等——構成要素をREVに足すと mode=max でも総額の下振れを作る
GP = ["GrossProfit"]
COGS_TOTAL = ["CostOfRevenue", "CostOfGoodsAndServicesSold"]
COGS_PARTS = ["CostOfGoodsSold", "CostOfServices"]  # 構成要素＝和で使う（代替ではない）
SGA = ["SellingGeneralAndAdministrativeExpense"]  # 分割報告(S&M/G&A別建て)の社は欠測でよい（仕様）
OP = ["OperatingIncomeLoss"]
NI = ["NetIncomeLoss", "ProfitLoss"]
OCF = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets"]
RND = ["ResearchAndDevelopmentExpense",
       "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost",  # ADBE等が使う変種
       "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"]
DIV = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]
BUY = ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"]
ISS = ["ProceedsFromIssuanceOfCommonStock", "ProceedsFromIssuanceOrSaleOfEquity"]
INT = ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"]
ASSETS = ["Assets"]
CASH = ["CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
GW = ["Goodwill"]

FLOW_MIN, FLOW_MAX = 330, 400  # 年次エントリの日数帯


def flow_maps(g, tags, deadline, mode="first"):
    """各タグの {年ラベル: (val, filed, end)}。filed<=deadline の年次(330-400日)USDのみ。
    同一(タグ,年)の重複は期限内で最も新しいfiledを採る。
    mode='first': 年ごとに候補の先頭一致（意味の優先順がある概念用）。
    mode='max'  : 年ごとに候補中の最大値（売上用——filerが'Revenues'を構成要素の行に使う社が実在し
    〔ENS: Revenues 186M vs SalesRevenueNet 2,582M〕、構成要素は総額を超えないので最大が総額）。"""
    maps = []
    for tag in tags:
        node = g.get(tag)
        m = {}
        if node:
            for e in node.get('units', {}).get('USD', []):
                en, st, fl = e.get('end', ''), e.get('start', ''), e.get('filed', '')
                if not en or not st or not fl or fl > deadline:
                    continue
                try:
                    if not (FLOW_MIN <= (d2(en) - d2(st)).days <= FLOW_MAX):
                        continue
                except Exception:
                    continue
                y = int(en[:4])
                if y not in m or fl > m[y][1]:
                    m[y] = (e['val'], fl, en)
        maps.append(m)

    def get(y):
        if mode == "max":
            vals = [m[y][0] for m in maps if y in m]
            return max(vals) if vals else None
        for m in maps:  # 年ごとに候補の先頭一致（タグ改称は年で自然に接がれる）
            if y in m:
                return m[y][0]
        return None
    return get, maps


def flow3(g, tags, deadline):
    """CF活動項目の三値読み。get(y) → (状態, 値):
    ('val', v)=年次値あり ／ ('miss', None)=年次は無いが同年ラベルに触れる報告がある（測れない）
    ／ ('zero', 0)=その年に触れる報告が一つも無い（活動なし）。"""
    get_ann, maps = flow_maps(g, tags, deadline)
    touched = set()
    for tag in tags:
        node = g.get(tag)
        if not node:
            continue
        for e in node.get('units', {}).get('USD', []):
            en, fl = e.get('end', ''), e.get('filed', '')
            if en and fl and fl <= deadline:
                touched.add(int(en[:4]))

    def get(y):
        v = get_ann(y)
        if v is not None:
            return ('val', v)
        if y in touched:
            return ('miss', None)
        return ('zero', 0)
    return get


def tag_seen(g, tags, deadline):
    """期限内に一度でも（期間形式を問わず）USD報告があるか。「一度も無い＝0でよい」判定用。"""
    for tag in tags:
        node = g.get(tag)
        if not node:
            continue
        for e in node.get('units', {}).get('USD', []):
            if e.get('filed', '') and e['filed'] <= deadline:
                return True
    return False


def inst_at(g, tags, deadline, end_date):
    """インスタント項目をアンカーFY末日±10日で照合（年ラベル照合はQ末残高が混入する）。"""
    tgt = d2(end_date)
    for tag in tags:
        node = g.get(tag)
        if not node:
            continue
        best = None
        for e in node.get('units', {}).get('USD', []):
            if e.get('start'):
                continue
            en, fl = e.get('end', ''), e.get('filed', '')
            if not en or not fl or fl > deadline:
                continue
            try:
                if abs((d2(en) - tgt).days) > 10:
                    continue
            except Exception:
                continue
            if best is None or fl > best[1]:
                best = (e['val'], fl)
        if best:
            return best[0]
    return None


def cagr(a, b, n):
    if a is None or b is None or a <= 0 or b <= 0 or n <= 0:
        return None
    return (b / a) ** (1 / n) - 1


def r4(x):
    return None if x is None else round(x, 4)


def build_row(t, g, deadline):
    row = {"ticker": t}
    rev_get, rev_maps = flow_maps(g, REV, deadline, mode="max")
    # アンカー = 期限内の年次売上エントリのうち end が最新のもの
    ends = [v[2] for m in rev_maps for v in m.values()]
    if not ends:
        return row  # 売上が一つも読めない社は特徴量なし（tickerのみ）
    fy_end = max(ends, key=d2)
    a = int(fy_end[:4])
    row["fy"] = a
    row["fy_end"] = fy_end
    W = list(range(a - 4, a + 1))  # 5年窓

    op_get, _ = flow_maps(g, OP, deadline)
    ni_get, _ = flow_maps(g, NI, deadline)
    ocf_get, _ = flow_maps(g, OCF, deadline)
    cap3 = flow3(g, CAPEX, deadline)
    cap = {y: cap3(y) for y in W}  # (状態, 値)

    rev = {y: rev_get(y) for y in range(a - 5, a + 1)}
    op = {y: op_get(y) for y in W}
    ocf = {y: ocf_get(y) for y in W}
    ni = {y: ni_get(y) for y in W}

    ra = rev[a]
    if ra and ra > 0:
        row["rev"] = ra
        # gm: GrossProfit → 総額COGS → 構成要素の和（Goods+Services）の順
        gp_get, _ = flow_maps(g, GP, deadline)
        gp = gp_get(a)
        if gp is not None:
            row["gm"] = r4(gp / ra)
        else:
            ct_get, _ = flow_maps(g, COGS_TOTAL, deadline)
            ct = ct_get(a)
            if ct is not None:
                row["gm"] = r4((ra - ct) / ra)
            else:
                parts = []
                for tag in COGS_PARTS:
                    pg, _ = flow_maps(g, [tag], deadline)
                    v = pg(a)
                    if v is not None:
                        parts.append(v)
                if parts:
                    row["gm"] = r4((ra - sum(parts)) / ra)
        sga_get, _ = flow_maps(g, SGA, deadline)
        sga = sga_get(a)
        if sga is not None:
            row["sga_r"] = r4(sga / ra)
        # capex_r: 三値読み（年次あり／同年に触れる報告だけ＝欠測／一切なし＝0）。CF計算書の実在も要る
        if ocf[a] is not None and cap[a][0] != 'miss':
            row["capex_r"] = r4(cap[a][1] / ra)
        # rnd_r: タグが期限内に一度も無い社は0。あるのにアンカー年に無いのは欠測
        rnd_get, _ = flow_maps(g, RND, deadline)
        rd = rnd_get(a)
        if rd is not None:
            row["rnd_r"] = r4(rd / ra)
        elif not tag_seen(g, RND, deadline):
            row["rnd_r"] = 0.0
        if op[a] is not None:
            row["opm"] = r4(op[a] / ra)
            # intcov: 利息ゼロ・タグ無しは欠測
            int_get, _ = flow_maps(g, INT, deadline)
            ie = int_get(a)
            if ie is not None and ie > 0:
                row["intcov"] = r4(op[a] / ie)

    # 総資産系（アンカーFY末日で照合）
    assets = inst_at(g, ASSETS, deadline, fy_end)
    if assets and assets > 0:
        if ra and ra > 0:
            row["aturn"] = r4(ra / assets)
        if ni[a] is not None and ocf[a] is not None:
            row["accr"] = r4((ni[a] - ocf[a]) / assets)
        cash = inst_at(g, CASH, deadline, fy_end)
        if cash is not None:
            row["cash_r"] = r4(cash / assets)
        gw = inst_at(g, GW, deadline, fy_end)
        if gw is not None:
            row["gw_r"] = r4(gw / assets)
        elif not tag_seen(g, GW, deadline):
            row["gw_r"] = 0.0  # のれんを一度も報告していない社＝のれん無し（IRMD前例）

    # 成長系（年ラベルの差で年数を数える）
    if ra and ra > 0:
        avail = [y for y in W if rev[y] and rev[y] > 0]
        y0 = min(avail) if avail else None
        if y0 is not None and a - y0 >= 3:
            row["cagr5"] = r4(cagr(rev[y0], ra, a - y0))
        c2 = cagr(rev[a - 2], ra, 2)
        c1 = cagr(rev[a - 5], rev[a - 2], 3)
        if c1 is not None and c2 is not None:
            row["accel"] = r4(c2 - c1)
    if all(rev[y] and rev[y] > 0 for y in W):
        row["streak_rev"] = sum(1 for y in W[1:] if rev[y] > rev[y - 1])
    if all(op[y] is not None and rev[y] and rev[y] > 0 for y in W):
        opm = {y: op[y] / rev[y] for y in W}
        row["streak_opm"] = sum(1 for y in W[1:] if opm[y] > opm[y - 1])
        row["opmD5"] = r4(opm[a] - opm[a - 4])

    # CF窓もの（5年すべてのOCFが要る）。capex・配当・買戻し・発行は三値読み——
    # 窓のどこかで 'miss'（活動はあるのに年次が採れない）なら特徴量ごと欠測にする
    buy3 = flow3(g, BUY, deadline)
    buy = {y: buy3(y) for y in W}
    if all(ocf[y] is not None for y in W):
        if all(cap[y][0] != 'miss' for y in W):
            fcf = {y: ocf[y] - cap[y][1] for y in W}
            row["fcfpos5"] = sum(1 for y in W if fcf[y] > 0)
            if all(ni[y] is not None for y in W) and sum(ni.values()) > 0:
                row["conv5"] = r4(sum(fcf.values()) / sum(ni.values()))
        iss3 = flow3(g, ISS, deadline)
        iss = {y: iss3(y) for y in W}
        if ra and ra > 0 and all(iss[y][0] != 'miss' and buy[y][0] != 'miss' for y in W):
            row["netiss_r"] = r4(sum(iss[y][1] - buy[y][1] for y in W) / ra)
        if all(ni[y] is not None for y in W) and sum(ni.values()) > 0:
            div3 = flow3(g, DIV, deadline)
            div = {y: div3(y) for y in W}
            if all(div[y][0] != 'miss' and buy[y][0] != 'miss' for y in W):
                row["payout5"] = r4(sum(div[y][1] + buy[y][1] for y in W) / sum(ni.values()))
    return row


FEATS = ["gm", "sga_r", "capex_r", "aturn", "accr", "streak_rev", "streak_opm", "fcfpos5",
         "intcov", "cash_r", "gw_r", "netiss_r", "rnd_r", "conv5", "payout5",
         "opm", "opmD5", "cagr5", "accel", "rev"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", type=int, default=2018)
    # 母集団のファイル名を明示できるようにした（2026-09-20・既定は従来どおり）。
    # 2015だけ retro_returns_2015.json が164社の抽出で、実際に読解された母集団は
    # retro_returns_2015_q.json の506社（164 ⊂ 506）。既定のまま回すと342社が落ちる。
    ap.add_argument("--returns", default=None,
                    help="母集団に使う out/retro_returns_*.json（省略時 retro_returns_{asof}.json）")
    args = ap.parse_args()
    deadline = f"{args.asof}-07-01"

    rname = args.returns or f"retro_returns_{args.asof}.json"
    rets = json.load(open(os.path.join(BASE, "out", rname)))
    tickers = sorted({r["ticker"] for r in rets["rows"] if r.get("ticker")})
    # CIK表は **asofと同じビンテージのcohort**を優先する（無ければ従来どおり2013へ）。
    # 実測: 2015の母集団506社のうち **101社が cohort_2013 に無い**ので、2013表だけだと
    # その101社は cik無しで黙って落ちる（＝ここで測れるのに測らない形になる・ルール7）。
    # 両cohortにある社のCIKは **食い違い0件**（実測）なので、優先しても基準は割れない。
    cname = f"retro_cohort_{args.asof}.json"
    if not os.path.exists(os.path.join(BASE, "out", cname)):
        cname = "retro_cohort_2013.json"
    cohort = json.load(open(os.path.join(BASE, "out", cname)))
    t2cik = {r["ticker"]: r["cik"] for r in cohort["rows"] if r.get("ticker")}

    z = zipfile.ZipFile(os.path.join(BASE, "companyfacts.zip"))
    have = set(z.namelist())
    rows, miss = [], []
    for i, t in enumerate(tickers, 1):
        if i % 200 == 0:
            print(f"  {i}/{len(tickers)}")
        cik = t2cik.get(t)
        name = f"CIK{cik:010d}.json" if cik is not None else None
        if not name or name not in have:
            miss.append(t)
            rows.append({"ticker": t})
            continue
        try:
            g = json.loads(z.read(name)).get("facts", {}).get("us-gaap", {})
        except Exception:
            miss.append(t)
            rows.append({"ticker": t})
            continue
        rows.append(build_row(t, g, deadline))

    note = (f"filed<={deadline}のエントリのみ使用（年ラベル切りはlook-ahead＝12月決算のFY{args.asof}は"
            f"{args.asof + 1}年提出で不可視）。直近FY=期限内年次売上エントリのend最新（rows.fy/fy_endに記録・"
            "遅延提出社は古いFYがそのまま『当時の直近』になる）。5年窓=fy-4..fy。cagr5は年ラベル差で割る"
            "（窓内最古年が欠けば実n・n>=3のみ）。accel=CAGR(a-2→a,2)−CAGR(a-5→a-2,3)。"
            "欠測規約: BS/IS項目は欠測のまま／CF活動項目(capex・配当・買戻し・発行)は三値"
            "（年次値あり=値／同年ラベルに触れる報告だけ=欠測〔実例NVDA: 年次capexがcustomタグで"
            "四半期YTDのみus-gaap＝0と読むと偽値〕／その年に触れる報告なし=活動なし0。窓ものは窓内に"
            "欠測が1年でもあれば特徴量ごと欠測）／R&D・のれんは期限内に一度も報告が無い社だけ0"
            "（R&DはSoftware変種タグ含む＝ADBEの偽0を是正済み）。インスタント項目は"
            "アンカーFY末日±10日で照合（年ラベルだとQ末残高が混入）。netiss_r=Σ(発行−買戻し)/直近FY売上"
            "（正=純希薄化・株数不使用=分割フリー）。intcovは利息>0のみ。sga_rは合算タグのみ（分割報告社は欠測）。"
            "売上は候補中の年ごと最大値（'Revenues'を構成要素の行に使うfilerが実在＝ENS 186M vs "
            "SalesRevenueNet 2,582M。構成要素は総額を超えない）。gmのCOGSは総額タグ優先・無ければ"
            "Goods+Servicesの和（片方だけ報告の社は過大の可能性＝注意）。")
    out = {"generated": datetime.date.today().isoformat(), "asof": args.asof,
           "deadline": deadline, "universe_file": rname, "cohort_file": cname,
           "note": note, "n": len(rows), "rows": rows}
    path = os.path.join(BASE, "out", f"retro_features2_{args.asof}.json")
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)
    got = {k: sum(1 for r in rows if k in r) for k in FEATS}
    print(f"■ {path}  {len(rows)}社（cik/facts無し {len(miss)}）")
    print("  被覆:", got)
    if miss:
        print("  facts無し:", ",".join(miss[:20]), "..." if len(miss) > 20 else "")


if __name__ == "__main__":
    main()
