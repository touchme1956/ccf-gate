#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fill_divy.py — E[r]予実台帳のための配当利回りの分離採取（2026-08-04新設・提案1）

なぜ要るか:
  予実台帳(audit_er_realized.py)は価格リターンで実現を測るが、E[r] の shy(純還元)は
  配当＋自社株買い。自社株買いは価格に出るが**配当は価格に出ない**ので、実現価格リターンは
  E[r] より配当利回りの分だけ構造的に低く出る。この補正項を観測時に分離保存しておかないと、
  突合が始まってから「E[r]は過大だった」と**自分で作った偏りを発見と誤認する**。
  snap() は out/divy.json があれば divY を観測に同梱する——このファイルを作るのが本器。

方式（株数を経由しない）:
  divY = 直近年次の1株配当(DPS) ÷ 現在株価。
  DPSタグ(CommonStockDividendsPerShareDeclared/CashPaid)を使うのは、mcap=px×株数の経路が
  分割・ADR比でスケールを壊した実績(KLAC 10:1)があるため——同じ穴を掘らない。
  無配の判定: DPSタグも配当支払CFタグ(PaymentsOfDividends系)も一度も無い会社だけ 0 とする
  （上限の不等式の作法）。支払CFはあるのにDPSが無い会社は null＋理由（欠測をゼロと読まない）。
  日本株は SEC 経路外＝null＋理由（黙って対象外にしない）。

使い方: python3 night/fill_divy.py        Ω75+（score_all.jsonのs>=75）を採取
        python3 night/fill_divy.py --all  全パック（重い）
出力: out/divy.json = {"asof":..., "divY":{T:pct|null}, "why":{T:理由}}
"""
import json, os, sys, time, urllib.request

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL = "fortis5280@gmail.com"
HDRS  = {"User-Agent": f"ccf-gate-divy {EMAIL}"}

DPS_TAGS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"]
# 原本で検算した年間DPS（機械値より優先）。上の分割検問は「大きすぎ」しか捕まえないので、
# 年間の行に四半期額が入っている「小さすぎ」はここで名指しで直す（2026-09-23・V: 年間行 0.59 は四半期額）
DPS_OVERRIDE = {
    "V": (2.36, "FY2025 10-K v-20250930.htm 株主資本等変動計算書『at a quarterly amount of $0.59 per class A common stock』×4"),
}
PAY_TAGS = ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)
    return b.decode("utf-8", "ignore")


def latest_annual_dps(facts):
    """DPSタグの最新FY値（USD/株・10-Kのみ）。無ければ None"""
    from datetime import date as _d
    best = None
    for tag in DPS_TAGS:
        node = facts.get("facts", {}).get("us-gaap", {}).get(tag)
        if not node:
            continue
        for unit, rows in (node.get("units") or {}).items():
            for r in rows:
                if r.get("form") != "10-K":
                    continue
                if r.get("fp") != "FY" or r.get("val") is None:
                    continue
                # 期間長の検問: 10-K内のDPSにはfp=FYでも四半期期間(Q4宣言分)の行が混ざる。
                # 実測: V 0.59(四半期) を年間と読み divY を1/4に誤るところだった。年間=300日以上のみ採る
                try:
                    s = r.get("start"); e = r.get("end")
                    y0, m0, d0 = map(int, s.split("-")); y1, m1, d1 = map(int, e.split("-"))
                    span = (_d(y1, m1, d1) - _d(y0, m0, d0)).days
                except Exception:
                    continue
                if span < 300:
                    continue
                if best is None or (r.get("end") or "") > best[0]:
                    best = (r.get("end"), tag, float(r["val"]))
    return None if best is None else {"end": best[0], "tag": best[1], "dps": best[2]}


def pack_shy(base, t):
    try:
        d = json.load(open(os.path.join(base, "out", f"{t}_gate_pack.json"), encoding="utf-8"))
        v = d.get("shy")
        return None if v in (None, "", "na") else float(v)
    except Exception:
        return None


def has_any(facts, tags):
    g = facts.get("facts", {}).get("us-gaap", {})
    return any(t in g and (g[t].get("units") or {}) for t in tags)


def main():
    allmode = "--all" in sys.argv
    rows = json.load(open(os.path.join(BASE, "out", "score_all.json"), encoding="utf-8"))
    names = [r["t"] for r in rows if allmode or r.get("s", 0) >= 75]

    px = {}
    try:
        d = json.load(open(os.path.join(BASE, "out", "dashboard.json"), encoding="utf-8"))
        for t, q in (d.get("quotes") or {}).items():
            if q.get("px"):
                px[t.upper()] = (float(q["px"]), q.get("ccy") or "USD")
    except Exception:
        pass
    try:
        md = json.load(open(os.path.join(BASE, "market_data.json"), encoding="utf-8"))
        for t, v in md.items():
            if isinstance(v, dict) and v.get("px") and t.upper() not in px:
                px[t.upper()] = (float(v["px"]), "USD")
    except Exception:
        pass

    cm = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in cm.values()}

    divY, why = {}, {}
    for t in names:
        T = t.upper()
        if T[:1].isdigit():
            divY[T] = None; why[T] = "日本株=SEC経路外。EDINETの配当は未採取（欠測をゼロと読まない）"
            continue
        c = cik.get(T)
        if not c:
            divY[T] = None; why[T] = "CIK不明（ADR名義違い等）"
            continue
        p = px.get(T)
        try:
            facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c}.json"))
        except Exception as e:
            divY[T] = None; why[T] = f"companyfacts取得失敗: {str(e)[:80]}"
            continue
        # IFRS/ADR提出体(20-F/40-F)は対象外＝null。初版はus-gaapタグ不在を「無配」と読み、
        # RACE/RELX/SAP（いずれも実際は配当あり）に 0 を置いた——タグ体系が違うだけの不在を
        # ゼロと読む、まさにルール7の事故。DPSの通貨(EUR等)とADR比の検算も要るので機械では置かない
        if "ifrs-full" in facts.get("facts", {}):
            divY[T] = None; why[T] = "IFRS/ADR提出体(20-F系)＝DPSの通貨・ADR比の検算が要るため機械では置かない（us-gaapタグ不在は無配の証拠にならない）"
            continue
        dps = latest_annual_dps(facts)
        if dps is None:
            if not has_any(facts, DPS_TAGS) and not has_any(facts, PAY_TAGS):
                divY[T] = 0.0; why[T] = "DPS・配当支払CFタグとも一度も報告なし＝無配と確定（上限の不等式）"
            else:
                divY[T] = None; why[T] = "配当支払CFはあるがDPSタグが取れない＝算出不能（株数経由はKLAC型の分割事故を再生産するため使わない）"
            continue
        # 鮮度検問: DPS期末が500日超前なら増配・減配で陳腐化している可能性＝置かない
        try:
            from datetime import date as _d
            y1, m1, d1 = map(int, dps["end"].split("-"))
            if (_d.today() - _d(y1, m1, d1)).days > 500:
                divY[T] = None; why[T] = f"DPSが古い（FY末{dps['end']}＝500日超前。最新10-Kに年間DPS行が無い）"
                continue
        except Exception:
            pass
        if not p:
            divY[T] = None; why[T] = f"株価未取得（DPS {dps['dps']} {dps['end']} は取れている）"
            continue
        if p[1] == "JPY":
            divY[T] = None; why[T] = "株価がJPY・DPSがUSDで通貨不一致（ADR比の確認が要る）"
            continue
        if T in DPS_OVERRIDE:
            o = DPS_OVERRIDE[T]
            divY[T] = round(o[0] / p[0] * 100, 3)
            why[T] = f"DPS {o[0]}（原本で検算: {o[1]}）÷ px {p[0]}——機械の年間DPS {dps['dps']} は四半期額のため不採用"
            continue
        v = round(dps["dps"] / p[0] * 100, 3)
        # 分割検問: DPSは前期10-K＝分割前スケールのことがある（KLAC 10:1で実測 3.69% vs pack shy 1.29%）。
        # shy=(配当+買戻し−発行)/時価総額 は配当を含む上位集合なので divY が shy+2pt を超えたらスケール疑い＝null
        sh = pack_shy(BASE, T)
        if sh is None:
            # shyとの突合が無い正値は置かない。実測: Vは年間期間なのに val=0.59(四半期額相当)の行が
            # companyfactsに残っており（クラス別次元タグの剥落＝CLAUDE.md既記録の欄）、突合なしでは捕まえられない
            divY[T] = None; why[T] = f"pack shyが無く突合不能（DPS {dps['dps']} FY末{dps['end']} は取れているが単独では確定しない——V型の次元剥落を弾けない）"
        elif v > sh + 2.0:
            divY[T] = None; why[T] = f"スケール疑い: DPS由来 {v}% > pack shy {sh}%+2pt——分割またぎ(KLAC型)の可能性。原本で検算するまで置かない"
        else:
            divY[T] = v
            why[T] = f"DPS {dps['dps']}（{dps['tag']}・FY末{dps['end']}）÷ px {p[0]}／shy {sh}%と整合"

    out = {"asof": __import__("datetime").date.today().isoformat(), "divY": divY, "why": why,
           "note": "予実突合の補正項: 実現価格リターン + divY ≈ トータルリターン。snapが観測へ同梱する"}
    op = os.path.join(BASE, "out", "divy.json")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_ok = sum(1 for v in divY.values() if v is not None)
    print(f"divY: {len(divY)}社中 {n_ok}社を確定（null {len(divY)-n_ok}社＝理由つき）→ {os.path.relpath(op, BASE)}")
    for t in sorted(divY):
        v = divY[t]
        print(f"  {t:6} {'—' if v is None else f'{v:5.2f}%'}  {why[t][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
