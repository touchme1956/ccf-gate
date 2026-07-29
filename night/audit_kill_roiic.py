#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_kill_roiic.py — 複利停止キル（ROIIC³<WACC）が立った社の**データの健全性**を仕分ける（2026-07-29新設）

なぜ要るか:
  v9.9.46 で roiic を機械算出したところ、複利停止キルが23社に新規で立った。
  キルは Ω を60で頭打ちにする強い判定なので、**データが汚れたまま有罪にしない**ことが要る。
  直前に KLAC で実例が出た——OperatingIncomeLoss が2014年で途切れており、EBITDA が減価償却
  だけになって nde=9.66（原本からは約0.2-0.5）。**同じ穴が ROIIC の分子(ΔNOPAT)にも効きうる。**

  原本を23社ぶん読むのは重い。**先に機械で「読む価値のある社」と「データが汚れている社」を分ける。**

仕分けの観点（すべて原本を読まずに判る）:
  A 系列の鮮度   : 営業利益・純利益の最新年が他系列から遅れていないか（絶対のルール7の年検問）
  B 窓の裏付け   : 3年窓と5年窓の両方が取れ、両方ともWACC近傍以下か（片方だけなら弱い）
  C 分母の素性   : ΔIC が IC のどれくらいか。極端に小さいと少しの誤差で符号が変わる
  D 投資期の疑い : 直近3年で capex/売上 が過去比で大きく上がっていないか
                   （新工場・大型買収の建設期＝門0の病名でいう「谷」。TXNの300mm新工場が実例）

出力は**作業リスト**であって有罪判決ではない。最終判断は原本でしか下せない。
ただし**原本を読む前に「読んで意味があるか」を測れ**（--impact）。2026-07-29の実測では、
28社すべてについて roiic を 'na' にしてキルを外しても **Ω75 に届く社は一社も無かった**
（最大は HD の 71.3）。しかも28社は**保有・監視・watchのいずれにも入っていない**。
＝キルは買付判断にも売却判断にも効いていないので、26社ぶんの原本読解は**やっても何も動かない**。
キルが効くのは (a) 外せばΩ75に届く社がいる場合 か (b) 保有銘柄に立った場合（S1の売却規律に直結）だけ。

初回実測（2026-07-29・候補28社）で判ったこと:
  ・**26社は損益系列が最新年まで届いており、データは健全**＝キルは素直に読める
  ・データを疑うべきは2社だけ: TXN（capex/売上 14.0%→25.7%）と WTRG（44.8%→59.2%）
  ・TXNは原本で決着済み——capexは300mm新工場(Sherman/Lehi)で4.5%(2020)→28.9%(2023)へ激増し、
    ICは16,535→30,821百万$(+86%)なのに営業利益は5,894→6,023でほぼ横ばい。
    ROIICは**3年窓−50.9%/5年窓−1.4%/7年窓−2.0%**＝**どの窓でも回収していない**のでキル維持。
    性質は「価値破壊」ではなく「**投資期・未回収**」で、反転は次期以降の実績でしか確認できない。
  ・**規制公益（WTRG/YORW/NEE/NJR）はROIICが構造的にWACC近傍になる**——規制当局が許容ROEを
    資本コスト近辺に設定するため。キルが立つのは誤爆ではなく、「この業態は資本コストを超えて
    複利しない」という正しい読み。20-30年複利を目的とする門の趣旨と整合する。
使い方:
  python3 night/audit_kill_roiic.py            データの健全性で仕分ける
  python3 night/audit_kill_roiic.py --impact   **キルを外したら誰がどう動くかを実測**（原本を読む前にこれ）
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import hachimon_fetch as H       # noqa: E402


def main():
    rows = json.load(open("out/score_all.json", encoding="utf-8"))
    sc = {r["t"]: r for r in rows}
    targets = []
    for t, r in sc.items():
        if re.match(r"^\d", t) or not r.get("kills"):
            continue
        try:
            d = json.load(open(f"out/{t}_gate_pack.json", encoding="utf-8"))
        except Exception:
            continue
        v = d.get("roiic")
        if isinstance(v, (int, float)) and v < 12:      # 複利停止キルの候補帯
            targets.append((t, v, d.get("roiic5"), r["s"]))
    targets.sort(key=lambda x: -x[3])
    print(f"複利停止キルの候補帯（roiic<12%）にいる社: {len(targets)}\n")
    hdr = f"{'':6s} {'Ω':>5s} {'roiic':>6s} {'5年窓':>6s} {'損益最新':>8s} {'系列最新':>8s} {'ΔIC/IC':>7s} {'capex/売上 3年前→直近':>22s}  所見"
    print(hdr)
    work, dirty = [], []
    for t, r3, r5, s in targets:
        try:
            f = H.facts_of(H.cik_of(t))
            S = {k: (H.series_sum(f, H.TAGS[k], "DebtCurrent" if k == "debtS" else "LongTermDebt")[0]
                     if k in ("debtL", "debtS") else H.series(f, H.TAGS[k])[0])
                 for k in ("rev", "op", "ni", "eq", "debtL", "debtS", "capex")}
        except (Exception, SystemExit):
            print(f"{t:6s} 取得失敗")
            continue
        allys = [y for k in ("rev", "op", "ni", "eq") for y in S[k]]
        latest = max(allys) if allys else None
        y_pl = max(S["op"]) if S["op"] else None
        stale = (latest is not None and y_pl is not None and y_pl < latest - 1)
        # ΔIC/IC
        ic = {}
        for y in S["eq"]:
            if (y in S["debtL"]) or (y in S["debtS"]):
                ic[y] = S["eq"][y] + S["debtL"].get(y, 0) + S["debtS"].get(y, 0)
        ys = sorted(ic)
        dic = ""
        if len(ys) >= 4:
            a, b = ic[ys[-4]], ic[ys[-1]]
            dic = f"{(b-a)/max(a,1)*100:+.0f}%"
        # capex/売上
        cx = ""
        cys = sorted(set(S["capex"]) & set(S["rev"]))
        if len(cys) >= 4:
            o = abs(S["capex"][cys[-4]]) / S["rev"][cys[-4]] * 100
            n = abs(S["capex"][cys[-1]]) / S["rev"][cys[-1]] * 100
            cx = f"{o:.1f}% → {n:.1f}%"
            invest = n > o * 1.3 and n > 8
        else:
            invest = False
        note = []
        if stale:
            note.append(f"**損益系列が{latest-y_pl}年遅れ＝要検算**")
        if not isinstance(r5, (int, float)):
            note.append("5年窓なし")
        if invest:
            note.append("**capex急増＝投資期の谷の疑い**")
        line = (f"{t:6s} {s:5.1f} {r3:6.1f} {str(r5):>6s} "
                f"{str(y_pl):>8s} {str(latest):>8s} {dic:>7s} {cx:>22s}  " + " / ".join(note))
        print(line)
        (dirty if (stale or invest) else work).append(t)
    print(f"\n【原本を読む価値が高い（データは健全・キルは素直に読める）】{len(work)}社")
    print("   " + " ".join(sorted(work)))
    print(f"【先にデータを疑うべき（系列の遅れ／投資期の疑い）】{len(dirty)}社")
    print("   " + " ".join(sorted(dirty)))
    print("\n※これは作業リストであって有罪判決ではない。最終判断は原本でしか下せない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
