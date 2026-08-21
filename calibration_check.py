#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibration_check.py — 門2定性判定の「答え合わせ台帳」(2026-07精査で新設)
背景: 門には判定→結果を突き合わせる較正ループが無く、ルーブリックの甘辛が検証不能だった
(実測: p2は280パック中59.3%が85点以上・根拠の9割がCOVID一本足=甘い方向の偏りが既に存在)。
本器は年次全面再採点(毎年7月)のタイミングで実行し、
  snapshot: out/*_gate_pack.json から較正対象フィールドを年別に out/calibration.json へ保存
  compare : 直前年スナップショットとの突合——(i) erosion/disrupt の遷移行列
            (none→active 等の「見逃し→顕在化」率) (ii) f1帯 vs 実現roiic
            (iii) 定量実績の前年差(roic/gm/cagr) を印字・台帳へ追記
使い方: python calibration_check.py            … snapshot＋(前年があれば)compare
出力:   out/calibration.json  {snapshots:{YYYY:{T:{...}}}, reviews:[{year,vs,summary,...}]}
規律:   判定式・閾値には一切触れない「答え合わせ」専用。ルーブリック刻みの再調整は
        年1回・この結果を見てユーザーが明示指示した時のみ(絶対のルール1)。
"""
import json, glob, os
from datetime import date

CAL = "out/calibration.json"
FIELDS_Q = ["erosion", "disrupt", "moatdecay", "expiry", "geopol",
            "dom", "irr", "rep", "dur", "p1", "p2", "p3", "p4",
            "f1", "f2", "f3", "f4", "f5"]
FIELDS_N = ["roic", "roiic", "gm", "cagr", "nde", "z", "nrr", "sbc"]

def load_cal():
    if os.path.exists(CAL):
        try:
            return json.load(open(CAL, encoding="utf-8"))
        except Exception as e:
            print(f"▲ {CAL} を読めない({e})→ 新規作成")
    return {"snapshots": {}, "reviews": []}

def snapshot(cal, year):
    snap = {}
    for f in sorted(glob.glob("out/*_gate_pack.json")):
        try:
            o = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        t = o.get("nm") or os.path.basename(f).split("_gate_pack")[0]
        row = {}
        for k in FIELDS_Q + FIELDS_N:
            if o.get(k) is not None:
                row[k] = o[k]
        row["auditDate"] = (o.get("_meta") or {}).get("auditDate")
        snap[t] = row
    # v10影スコア(系列の門・V10_SPEC.md)も保存——2027-07に v9予実 vs v10予実 の勝敗を裁く材料
    #
    # ★2026-08-16: **どの版の v10 を封じたかを必ず記録する**。2026年はここが無かったせいで
    #   「snapshots.2026 の v10＝07-27版28社」と「out/v10_shadow.json＝08-04版40社」が
    #   別物だと気づくのに、値を1社ずつ突き合わせるまで判らなかった（重なる28社のうち12社が食い違い
    #   ＝08-04のパック一斉是正で定性の入力が書き換わっていた）。
    #   ⚠ ops.yml は 7月に v10_series.py → calibration_check.py の順で走るので通常は同じ日に揃うが、
    #     **手で片方だけ走らせると静かにずれる**。ずれたことが後から判る形にしておく。
    v10_prov = {"file": "out/v10_shadow.json", "generated": None, "n": 0}
    try:
        vd = json.load(open("out/v10_shadow.json", encoding="utf-8"))
        v10 = vd.get("scores", {})
        v10_prov["generated"] = vd.get("generated")
        v10_prov["n"] = len(v10)
        for t, r in v10.items():
            snap.setdefault(t, {})["v10"] = r.get("v10")
    except Exception as e:
        v10_prov["error"] = str(e)
    cal["snapshots"][year] = snap
    # 出所は snapshots[year] の中に置かない（ティッカーの辞書なので混ざる）。兄弟キーへ。
    cal.setdefault("_snapshot_prov", {})[year] = {
        "recorded": str(date.today()), "v10": v10_prov,
        "packs": len([f for f in glob.glob("out/*_gate_pack.json")]),
    }
    print(f"snapshot {year}: {len(snap)}銘柄を保存"
          f"（v10影 {v10_prov['n']}社・generated {v10_prov['generated']}）")
    return cal

def transition(cal, prev_y, cur_y, key, order):
    """key(erosion/disrupt)の遷移行列を作る。orderは悪化方向の並び"""
    prev, cur = cal["snapshots"][prev_y], cal["snapshots"][cur_y]
    both = sorted(set(prev) & set(cur))
    mat, worsened = {}, []
    for t in both:
        a, b = str(prev[t].get(key, "?")), str(cur[t].get(key, "?"))
        mat[f"{a}→{b}"] = mat.get(f"{a}→{b}", 0) + 1
        if a in order and b in order and order.index(b) > order.index(a):
            worsened.append(f"{t}({a}→{b})")
    return mat, worsened

def compare(cal, prev_y, cur_y):
    prev, cur = cal["snapshots"][prev_y], cal["snapshots"][cur_y]
    both = sorted(set(prev) & set(cur))
    print(f"\n=== 較正 {prev_y}→{cur_y}（共通{len(both)}銘柄） ===")
    rev = {"year": cur_y, "vs": prev_y, "n": len(both)}
    for key, order in [("erosion", ["none", "emerging", "active"]),
                       ("disrupt", ["settled", "unsettled", "threat"])]:
        mat, worsened = transition(cal, prev_y, cur_y, key, order)
        rev[key] = {"matrix": mat, "worsened": worsened}
        print(f"{key} 遷移: " + "  ".join(f"{k}:{v}" for k, v in sorted(mat.items())))
        if worsened:
            print(f"  悪化{len(worsened)}件: {', '.join(worsened[:10])}")
            print(f"  → 前年判定の見逃し率の材料。悪化銘柄の前年evidenceを読み直し、"
                  f"兆候が原本にあったなら門2の読みの甘さ・無かったなら構造的限界")
    # f1(ROIIC帯の予測)vs実現roiic: f1が80+なのにroiicがWACC+8を割った件数など
    miss = []
    for t in both:
        f1p, rr = prev[t].get("f1"), cur[t].get("roiic")
        try:
            f1p = float(f1p); rr = float(str(rr))
        except (TypeError, ValueError):
            continue
        if f1p >= 80 and rr < 12:   # WACC≈9+3の近似帯を割った
            miss.append(f"{t}(f1={f1p:.0f}→実現roiic{rr:.0f}%)")
    rev["f1_miss"] = miss
    if miss:
        print(f"f1楽観の疑い {len(miss)}件: {', '.join(miss[:10])}")
    cal["reviews"].append(rev)
    return cal

if __name__ == "__main__":
    year = str(date.today().year)
    cal = load_cal()
    cal = snapshot(cal, year)
    prevs = sorted(y for y in cal["snapshots"] if y < year)
    if prevs:
        cal = compare(cal, prevs[-1], year)
    else:
        print("前年スナップショットなし→今年は基準線の保存のみ(来年から突合が始まる)")
    os.makedirs("out", exist_ok=True)
    json.dump(cal, open(CAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {CAL} 更新")
