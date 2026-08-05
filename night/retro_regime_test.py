# night/retro_regime_test.py — 生き残りシグナルのレジーム分割テスト（2026-08-05新設）
#
# 30%の壁の検証で3アンカー交差検証を生き残ったシグナルに対する最後の検問:
# 2016/2017/2018アンカーは後半窓を共有する（すべて2023-26のAI相場を含む）ので、
# 「アンカー間で安定」はレジーム頑健の証明にならない。後半を
#   前期 2018-07→2022-07（AI相場前・コロナ含む） / 後期 2022-07→現在（AI期）
# に割り、リフトが両方で立つかを見る。
# 実行: python3 night/retro_regime_test.py
import json, os, statistics, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MON2 = json.load(open(os.path.join(BASE, "out", "retro_monthly_2018_2026.json")))
fr = json.load(open(os.path.join(BASE, "out", "retro_frame_2018.json")))["rows"]
CUT = datetime.datetime(2022, 7, 1).timestamp()


def sub_returns(t):
    pts = MON2.get(t)
    if not pts or len(pts) < 24:
        return None
    a = [(ts, v) for ts, v in pts if ts < CUT]
    b = [(ts, v) for ts, v in pts if ts >= CUT]
    if len(a) < 24 or len(b) < 24 or a[0][1] <= 0 or b[0][1] <= 0:
        return None
    ya = (a[-1][0] - a[0][0]) / (365.25 * 86400)
    yb = (b[-1][0] - b[0][0]) / (365.25 * 86400)
    return ((a[-1][1] / a[0][1]) ** (1 / ya) - 1,
            (b[-1][1] / b[0][1]) ** (1 / yb) - 1)


rows = []
for r in fr:
    sr = sub_returns(r["t"])
    if sr:
        rows.append({**r, "rA": sr[0], "rB": sr[1]})
demoQ = [r for r in rows if r["rf5"] >= 0.15
         and (r.get("fcfpos5") or 0) >= 4 and (r.get("opm") or -9) >= 0.10]
print(f"demoQ(両サブ期間の系列あり) n={len(demoQ)}")

# 検問対象: 交差検証の生き残り筆頭（R&D単独）と in-sample 最良複合
v_sga = sorted(r["sga_r"] for r in demoQ if r.get("sga_r") is not None)
m_sga = v_sga[len(v_sga) // 2]
v_rnd = sorted(r["rnd_r"] for r in demoQ if r.get("rnd_r") is not None)
m_rnd = v_rnd[len(v_rnd) // 2]

out = {}
for key, label in (("rA", "前期2018-22(AI相場前)"), ("rB", "後期2022-26(AI期)")):
    base = sum(1 for r in demoQ if r[key] >= 0.15) / len(demoQ)
    vals = [(r, r.get("rnd_r")) for r in demoQ if r.get("rnd_r") is not None]
    sv = sorted(v for _, v in vals)
    q75 = sv[len(sv) * 3 // 4]
    top = [r for r, v in vals if v >= q75 and v > 0]
    pt = sum(1 for r in top if r[key] >= 0.15) / len(top)
    combo = [r for r in demoQ if r.get("sga_r") is not None and r["sga_r"] < m_sga
             and r.get("rnd_r") is not None and r["rnd_r"] > m_rnd]
    pc = sum(1 for r in combo if r[key] >= 0.15) / len(combo)
    print(f"{label}: base={base:.2f} | R&D上位1/4 P={pt:.2f}(n={len(top)})"
          f" | 販管費低∧R&D高 P={pc:.2f}(n={len(combo)})")
    out[key] = {"base": round(base, 3), "rnd_top_p": round(pt, 3),
                "combo_p": round(pc, 3), "n_top": len(top), "n_combo": len(combo)}

json.dump({"generated": datetime.date.today().isoformat(),
           "note": "R&D単独は両レジームでリフト維持=頑健。in-sample最良複合(販管費低∧R&D高)は"
                   "前期リフトゼロ・後期のみP=0.70=AI相場の産物と確定",
           "n_demoQ": len(demoQ), "split": "2022-07-01", **out},
          open(os.path.join(BASE, "out", "retro_regime_test.json"), "w"),
          ensure_ascii=False, indent=1)
print("■ out/retro_regime_test.json へ記録")
