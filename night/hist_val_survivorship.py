# night/hist_val_survivorship.py — 自己相対バリュエーション検定の「生存バイアス」を壊しにいく
#                                   (2026-08-09新設)
#
# 何をする道具か:
#   事前登録 out/hist_valuation_prereg.json の known_risks 筆頭
#   「**自己履歴は長く生きた社にしか作れない**」を実測で裁く。
#   検定 (night/hist_val_gate_test.py) は「合格ゼロ」を出したが、**ゼロが正しいか**は
#   ゼロを出した母集団が母集団として正しいかに全部かかっている。
#
# ── この道具が答える5つの問い ────────────────────────────────────────────────
#   Q1 漏斗   : CIKの母集団 → 今日のティッカー保有 → 価格が引ける → 窓が揃う →
#               自己履歴36ヶ月 → 質実証、の各段で何社落ちるか
#   Q2 退場   : 落ちた社は**本当に退場した社**か（＝生存バイアスか、ただの欠測か）
#   Q3 左尾   : 各段の恒久毀損率 P(年率<=-15%)。自己履歴フィルタが左尾を切っているか
#               （超幾何分布で検定。落ちた社の分だけ偶然に説明できるかを数字で出す）
#   Q4 検出力 : 判定プールに恒久毀損が**何件あるか**。事前登録の基準1は
#               「止めた群の分子>=5社」を要求するので、プール全体の毀損が5件未満なら
#               **どんな指標・どんな閾値でも基準1は原理的に満たせない**
#   Q5 独立性 : 3ビンテージは独立した標本か（基準3「2ビンテージ以上で同符号」の前提）
#
# ── 検査器を信じる前に検査器を検算する（この道具が最初に踏んだ落とし穴）───────────
#   retro_cohort の `last_year` を「最後に報告した年」＝退場の印として使おうとしたが、
#   実体は **採用した売上タグの系列の末端**（retro_cohort.py:172-174）。
#   ASC606(2018)で `Revenues` → `RevenueFromContractWithCustomer…` へ改称した社は
#   系列がそこで切れるので、**KO=2017 / LMT=2017 / PFE=2023 / DHR=2018 が「退場」に見える**。
#   ＝CLAUDE.md が5回記録している「候補タグの先頭を無条件採用」の型が、退場の測りに化けていた。
#   → 退場は **SEC submissions API の実提出日**で測る（タグに依存しない）。
#     ついでに Form 15(登録抹消) / Form 25(上場廃止) の実在も拾う＝退場の理由まで判る。
#
# ── 守っている作法 ──────────────────────────────────────────────────────────
#   ■ 欠測をゼロと読むな: SECが引けなかったCIKは「生存」でも「退場」でもなく **不明**。
#   ■ 二重実装を作らない: プール・窓・分位・リターンの綴じ込みは hist_val_join.py が
#     済ませた印をそのまま読む。judge の再実装もしない（gate_test の base を突合せに使う）。
#   ■ 0件は真のゼロではない: 毀損0件には95%上端(3/n)を必ず併記する。
#   ■ 推測値を混ぜない: 測れなかったものは「測れなかった」と書く。反実仮想は
#     **上界・下界**として出し、点推定を結論にしない。
#
# 実行:
#   python3 night/hist_val_survivorship.py --fetch     # SEC submissions を採る（キャッシュ済なら不要）
#   python3 night/hist_val_survivorship.py             # 解析だけ（キャッシュを読む）
#   python3 night/hist_val_survivorship.py --json out/hist_val_survivorship.json
import argparse
import collections
import gzip
import json
import math
import os
import statistics as st
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
SUBS = os.path.join(OUT, "_histval_cache", "subs")
SEC_UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com", "Accept-Encoding": "gzip"}

IMP = -0.15          # 恒久毀損の線（この台帳の既存定義。retro_moat_durability と同じ）
VINTAGES = (2013, 2015, 2018)
# 「今も報告している」の線。SEC の提出は遅れるので asof を2025-01-01 に置く
ALIVE_LINE = "2025-01-01"


def load(name):
    p = os.path.join(OUT, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def qual(r):
    """retro_cohort 行に対する質実証プールの定義（hist_val_join.py と同じ式）"""
    return (r.get("opm") or -9) >= 0.10 and bool(r.get("fcf_all_pos")) and bool(r.get("op_all_pos"))


# ── 超幾何: N社中K社が毀損、n社を引いてk件以下になる確率（左尾が切られているかの検定）──
def hyp_le(N, K, n, k):
    def logC(a, b):
        if b < 0 or b > a:
            return float("-inf")
        return math.lgamma(a + 1) - math.lgamma(b + 1) - math.lgamma(a - b + 1)
    tot = logC(N, n)
    s = 0.0
    for i in range(0, k + 1):
        lp = logC(K, i) + logC(N - K, n - i) - tot
        if lp > -700:
            s += math.exp(lp)
    return min(1.0, s)


def rate(rows, key="tr_cagr"):
    v = [r[key] for r in rows if r.get(key) is not None]
    if not v:
        return {"n": 0}
    imp = [x for x in v if x <= IMP]
    d = {"n": len(v), "median": round(st.median(v), 4), "min": round(min(v), 4),
         "n_perm": len(imp), "p_perm": round(len(imp) / len(v), 4)}
    if not imp:                       # 0件は真のゼロではない（規則3: 3/n）
        d["p_perm_ci95_upper"] = round(3.0 / len(v), 4)
    return d


# ── SEC submissions（退場の実測。タグに依存しない）──────────────────────────────
def fetch_subs(ciks, sleep=0.11):
    os.makedirs(SUBS, exist_ok=True)
    got = err = 0
    for i, cik in enumerate(ciks):
        p = os.path.join(SUBS, f"CIK{int(cik):010d}.json.gz")
        if os.path.exists(p):
            continue
        url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=30) as r:
                raw = r.read()
            j = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
            rec = j.get("filings", {}).get("recent", {}) or {}
            forms, dates = rec.get("form") or [], rec.get("filingDate") or []
            slim = {"cik": int(cik), "name": j.get("name", ""),
                    "tickers": j.get("tickers") or [], "exchanges": j.get("exchanges") or [],
                    "last_filing": max(dates) if dates else None,
                    "last_annual": max([d for f, d in zip(forms, dates)
                                        if f in ("10-K", "20-F", "40-F", "10-K/A")] or [None]),
                    "form15": sorted([d for f, d in zip(forms, dates) if f.startswith("15")])[:1],
                    "form25": sorted([d for f, d in zip(forms, dates) if f.startswith("25")])[:1]}
            with gzip.open(p, "wt", encoding="utf-8") as fh:
                json.dump(slim, fh)
            got += 1
        except Exception:
            err += 1
        time.sleep(sleep)
        if (i + 1) % 200 == 0:
            print(f"    …{i+1}/{len(ciks)}  取得{got} 失敗{err}")
    print(f"  SEC submissions: 取得{got} 失敗{err} （キャッシュ {SUBS}）")


def read_subs(cik):
    p = os.path.join(SUBS, f"CIK{int(cik):010d}.json.gz")
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def exit_status(s):
    """実測の退場判定。引けなければ『不明』（ゼロと読まない）"""
    if s is None:
        return "不明"
    lf = s.get("last_filing")
    if not lf:
        return "不明"
    if lf >= ALIVE_LINE:
        return "生存"
    if s.get("form15"):
        return "退場(登録抹消 Form15)"
    if s.get("form25"):
        return "退場(上場廃止 Form25)"
    return "退場(提出停止)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--json", default=os.path.join(OUT, "hist_val_survivorship.json"))
    a = ap.parse_args()

    hv = {y: load(f"hist_val_{y}.json") for y in VINTAGES}
    coh = {y: load(f"retro_cohort_{y}.json") for y in (2013, 2015)}
    rep = {"generated": "2026-08-09", "tool": "night/hist_val_survivorship.py",
           "instrument_check": {}, "funnel": {}, "exits": {}, "left_tail": {},
           "power": {}, "independence": {}, "counterfactual": {}}

    # ── 0. 検査器の検算: retro_cohort.last_year は退場の印になるか ──────────────
    c13 = coh[2013]["rows"]
    false_dead = [r for r in c13 if r.get("ticker") in
                  ("KO", "LMT", "PFE", "DHR", "HON", "SNPS", "ADI") and (r.get("last_year") or 0) < 2024]
    rep["instrument_check"] = {
        "claim": "retro_cohort の last_year は『最後に報告した年』ではなく『採用した売上タグ系列の末端』",
        "evidence": [{"ticker": r["ticker"], "name": r["name"], "last_year": r["last_year"]}
                     for r in false_dead],
        "verdict": "last_year を退場の指標に使ってはいけない（ASC606のタグ改称で切れる）。"
                   "退場は SEC submissions の実提出日で測る",
        "impact_on_ledger": "CLAUDE.md が案Cで記録する『生存率(2025年まで報告) score7 64.6% vs score0 31.6%』も"
                            "同じ last_year 由来＝タグ改称の汚染を含む可能性がある（別途要検算）",
    }

    # ── 1. 漏斗 ───────────────────────────────────────────────────────────────
    for y in VINTAGES:
        rows = hv[y]["rows"]
        f = {}
        if y in coh:
            cr = coh[y]["rows"]
            f["A_CIK母集団"] = len(cr)
            f["B_今日のティッカー保有"] = sum(1 for r in cr if r.get("ticker"))
            f["A_CIK母集団_質実証"] = sum(1 for r in cr if qual(r))
            f["B_ティッカー保有_質実証"] = sum(1 for r in cr if qual(r) and r.get("ticker"))
        else:
            f["A_CIK母集団"] = None
            f["note"] = "2018ビンテージにCIK母集団の在庫が無い（下の independence を見よ）"
        f["C_価格が引けた"] = sum(1 for r in rows if r.get("tr_cagr") is not None)
        f["D_窓が揃う(window_full)"] = sum(1 for r in rows if r.get("window_full"))
        f["E_自己履歴36ヶ月(analysis_set)"] = sum(1 for r in rows if r.get("analysis_set"))
        f["F_判定プール(analysis∧quality)"] = sum(1 for r in rows
                                                if r.get("analysis_set") and r.get("quality"))
        rep["funnel"][y] = f

    # ── 2. 退場の実測（SEC submissions）──────────────────────────────────────
    #    対象は2013の質実証CIK母集団＝**判定プールの本来の母集団**（標本ではなく全数）
    q13 = [r for r in c13 if qual(r)]
    if a.fetch:
        print(f"  SEC submissions を採る: {len(q13)} 社（2013 質実証CIK母集団の全数）")
        fetch_subs([r["cik"] for r in q13])
    have = sum(1 for r in q13 if read_subs(r["cik"]))
    if have:
        an13 = {r["ticker"] for r in hv[2013]["rows"] if r.get("analysis_set")}
        buckets = {"ティッカー無し": [], "ティッカー有り": [], "判定プール入り": []}
        for r in q13:
            s = exit_status(read_subs(r["cik"]))
            if not r.get("ticker"):
                buckets["ティッカー無し"].append(s)
            else:
                buckets["ティッカー有り"].append(s)
                if r["ticker"] in an13:
                    buckets["判定プール入り"].append(s)
        ex = {}
        for k, v in buckets.items():
            c = collections.Counter(v)
            known = sum(n for kk, n in c.items() if kk != "不明")
            gone = sum(n for kk, n in c.items() if kk.startswith("退場"))
            ex[k] = {"n": len(v), "内訳": dict(c),
                     "退場率(不明を除く)": round(gone / known, 4) if known else None}
        rep["exits"] = {"母集団": "2013 質実証プールのCIK全数（標本ではない）",
                        "生存線": ALIVE_LINE, "coverage": f"{have}/{len(q13)}", "buckets": ex}

    # ── 3. 左尾: 自己履歴フィルタは中立か ────────────────────────────────────
    for y in VINTAGES:
        rows = hv[y]["rows"]
        d = {}
        for nm, filt in (("窓が揃う全社", lambda r: r.get("window_full")),
                         ("窓が揃う∧質実証", lambda r: r.get("window_full") and r.get("quality"))):
            base = [r for r in rows if filt(r) and r.get("tr_cagr") is not None]
            sel = [r for r in base if r.get("analysis_set")]
            drop = [r for r in base if not r.get("analysis_set")]
            K = sum(1 for r in base if r["tr_cagr"] <= IMP)
            k = sum(1 for r in sel if r["tr_cagr"] <= IMP)
            d[nm] = {"母集団": rate(base), "自己履歴36ヶ月を通った": rate(sel),
                     "落ちた": rate(drop),
                     "期待毀損数": round(len(sel) * K / len(base), 2) if base else None,
                     "観測毀損数": k,
                     "P(観測<=期待|中立)": round(hyp_le(len(base), K, len(sel), k), 6) if base else None}
        rep["left_tail"][y] = d

    # ── 4. 検出力: 基準1は原理的に満たせるか ─────────────────────────────────
    gt = load("hist_val_gate_test.json")
    base_perm = {}
    if gt:
        for c in gt["results"]:
            base_perm.setdefault((c["vintage"], c["pool"]), c["ev"]["base"]["n_perm"])
    pw = {}
    for (v, pool), np_ in sorted(base_perm.items()):
        pw[f"{v}/{pool}"] = {
            "プール全体の恒久毀損数": np_,
            "基準1の要求(止めた群の分子)": 5,
            "原理的に到達可能か": np_ >= 5,
            "理由": ("プール全体の毀損が5件未満＝どの指標・どの閾値でも分子は5に届かない"
                     if np_ < 5 else "到達可能（毀損が止めた群へ十分集中すれば）")}
    ok_v = sorted({int(k.split("/")[0]) for k, v in pw.items()
                   if k.endswith("/quality") and v["原理的に到達可能か"]})
    rep["power"] = {
        "判定プール": "prereg『合否は quality プールで判定する』",
        "cells": pw,
        "基準1が到達可能なビンテージ(quality)": ok_v,
        "基準3の要求": "1と2が2ビンテージ以上で同符号",
        "結論": ("基準1が到達可能なビンテージが1つ以下＝**基準3は信号の有無に関わらず永久に満たせない**。"
                 "この事前登録は構造的に不合格しか出せない検定だった"
                 if len(ok_v) < 2 else "基準3は到達可能"),
    }

    # ── 5. 独立性: 3ビンテージは別の標本か ───────────────────────────────────
    U = {y: {r["ticker"] for r in hv[y]["rows"]} for y in VINTAGES}
    Q = {y: {r["ticker"] for r in hv[y]["rows"] if r.get("analysis_set") and r.get("quality")}
         for y in VINTAGES}
    ind = {}
    for x in VINTAGES:
        for z in VINTAGES:
            if x < z:
                ind[f"母集団 {x}∩{z}"] = {"共通": len(U[x] & U[z]), "n": [len(U[x]), len(U[z])],
                                        "jaccard": round(len(U[x] & U[z]) / len(U[x] | U[z]), 3)}
                ind[f"判定プール {x}∩{z}"] = {"共通": len(Q[x] & Q[z]), "n": [len(Q[x]), len(Q[z])],
                                           "jaccard": round(len(Q[x] & Q[z]) / len(Q[x] | Q[z]), 3)}
    ind["2018母集団のうち2013に無い社"] = len(U[2018] - U[2013])
    rep["independence"] = ind

    # ── 6. 反実仮想は**上界・下界**で（点推定を結論にしない）────────────────────
    if rep.get("exits"):
        b = rep["exits"]["buckets"]
        nt, ht = b["ティッカー無し"], b["ティッカー有り"]
        f13 = rep["funnel"][2013]
        pool_n = f13["F_判定プール(analysis∧quality)"]
        univ = f13["A_CIK母集団_質実証"]
        # 参照率は「**測れた**質実証プール全体」(358社)の毀損率を使う。
        # 判定プール(117社)の率は 0/117 なので、そのまま外挿すると 0 になり
        # 『生存バイアスが無ければ毀損も無い』という循環した答えになる。
        obs = rep["left_tail"][2013]["窓が揃う∧質実証"]["母集団"]
        rep["counterfactual"] = {
            "問い": "退場社を測れていたら、判定プールの恒久毀損は基準1の分子5に届いたか",
            "2013質実証: CIK母集団": univ, "判定プールに残った": pool_n,
            "取りこぼし": univ - pool_n,
            "退場率(ティッカー無し)": nt["退場率(不明を除く)"],
            "退場率(ティッカー有り)": ht["退場率(不明を除く)"],
            "下界(最も保守的)": {
                "仮定": "取りこぼした社の毀損率＝観測プールと同じ（＝生存バイアスをゼロと仮定）",
                "毀損の期待数": round((obs.get("p_perm") or 0) * univ, 1)},
            "上界": {"仮定": "退場した社は全員が恒久毀損（現金化された買収も毀損と数える最悪の仮定）",
                     "注記": "退場≠毀損（プレミアム付き買収は勝ちで終わる）。点推定として使わないこと"},
            "測れなかったもの": "退場社の実現リターン（今日のティッカーが無いので Yahoo で引けない）",
        }

    # ── 7. 公平のための逆検定 ─────────────────────────────────────────────────
    #    生存バイアスが「信号を隠している」なら、**左尾が残っているプール**では信号が出るはず。
    #    2018/full は毀損69件（SUNE -80% / TOPS -77% 等が near-zero のOTC系列として生き残っている）
    #    ＝この台帳の retro 系で最も左尾が保たれた場所。ここで向きが出なければ、
    #    ゼロという結論は生存バイアスの産物ではない。
    #    さらに **2013が構造的に落とした帯（小型）だけ**を切り出して同じことを見る
    #    ——2013の脱落は XBRL段階導入による純粋な規模フィルタ（時価総額中央値 17.9 vs 1.6十億$）なので、
    #    「落ちた帯に信号が住んでいたのでは」が最後の逃げ道になる。
    r18 = [r for r in hv[2018]["rows"]
           if r.get("analysis_set") and r.get("tr_cagr") is not None and r.get("mcap")]
    strata = {"全体": r18,
              "大型 >=5.87十億$（2013判定プールのp10）": [r for r in r18 if r["mcap"] >= 5.87e9],
              "中型 1.62-5.87十億$": [r for r in r18 if 1.62e9 <= r["mcap"] < 5.87e9],
              "小型 <1.62十億$（2013が落とした帯）": [r for r in r18 if r["mcap"] < 1.62e9]}
    rev = {}
    for nm, pool in strata.items():
        cells = {}
        for ind in ("pe_pct", "ps_pct", "adj_pe_pct", "pfcf_pct"):
            for thr in (0.90, 0.95):
                m = [r for r in pool if r.get(ind) is not None]
                s = [r for r in m if r[ind] >= thr]
                p = [r for r in m if r[ind] < thr]
                if len(m) < 30 or not s or not p:
                    continue
                K = sum(1 for r in m if r["tr_cagr"] <= IMP)
                ks = sum(1 for r in s if r["tr_cagr"] <= IMP)
                cells[f"{ind}>={thr}"] = {
                    "n": len(m), "止めた": len(s), "毀損(母集団)": K, "毀損(止めた群)": ks,
                    "濃縮比": round((ks / len(s)) / (K / len(m)), 2) if K else None,
                    "止めた群の中央値": round(st.median([r["tr_cagr"] for r in s]), 4),
                    "通した群の中央値": round(st.median([r["tr_cagr"] for r in p]), 4)}
        rev[nm] = {"n": len(pool), "cells": cells}
    rep["reverse_test_2018_by_size"] = {
        "問い": "生存バイアスが信号を隠しているなら、左尾が残るプール／落とされた帯で信号が出るはず",
        "strata": rev}

    # 向きの不一致（ビンテージ間）
    if gt:
        dirs = {}
        for c in gt["results"]:
            if c["pool"] != "full" or c["indicator"] not in ("pe_pct", "pe_z", "adj_pe_pct"):
                continue
            dirs.setdefault(c["vintage"], []).append(c["judge"].get("c1_ratio"))
        rep["direction_conflict"] = {
            v: {"濃縮比の範囲(full/PER系)": [min(x for x in r if x is not None),
                                        max(x for x in r if x is not None)],
                "母集団の毀損数": base_perm.get((v, "full"))}
            for v, r in sorted(dirs.items()) if any(x is not None for x in r)}
        rep["direction_conflict"]["読み"] = (
            "2015は濃縮比2.2-4.1（仮説を支持する向き）だが母集団の毀損が6件しかなく、"
            "『6件中4件が30%の枠に入る』は超幾何でp≒0.07＝偶然と区別できない"
            "（事前登録の『分子>=5社』はまさにこれを弾くための規則）。"
            "毀損69件で検出力のある2018は0.32-0.97＝逆向き。"
            "**向きが一致しないのは、生存バイアスで薄くなった標本の宿命**")

    json.dump(rep, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:200])
    print(f"→ {a.json}")


if __name__ == "__main__":
    main()
