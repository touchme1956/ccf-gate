#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/rf_test.py — rf_replicate.py の純関数と Path 記憶の単体検算（手で計算した値と一致するか）。python3 night/rf_test.py"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rf_replicate as R  # noqa: E402

ok = 0


def eq(a, b, msg):
    global ok
    assert (abs(a - b) < 1e-9) if isinstance(a, float) or isinstance(b, float) else a == b, f"{msg}: {a} != {b}"
    ok += 1


# 1) trend_score: 重み (1.5,1.5,1.0,0.5,0.5)
eq(R.trend_score([10, 8, 6, 4, 2, 0]), 5.0, "全部改善=5")
eq(R.trend_score([1, 1, 1, 1, 1, 1]), 0.0, "同じ値=0（>0 のみ）")
eq(R.trend_score([None, 8, 6, 4, 2, 0]), 3.5, "P1欠測→R1だけ0")
eq(R.trend_score([1, 1, 5, 4, 4, 4]), 1.0, "R3 だけ改善=1.0")
eq(R.trend_score([None, None, 5, 4, 3, 2]), 2.0, "実績だけの最高点=2.0（事前登録の算術）")
eq(R.trend_score([1, 2, 3, 4, 5, 6]), 0.0, "悪化し続ける（新しいほど小さい）=0")

# 2) forward_extrap（V1）: R1=R2=R3 の符号
eq(R.forward_extrap(5, 3), (9, 7), "延長")
eq(R.forward_extrap(None, 3), (None, None), "欠測")
for d in (2, 0, -2):
    p3, p4 = 10.0, 10.0 - d
    f1, f2 = R.forward_extrap(p3, p4)
    sc = R.trend_score([f1, f2, p3, p4, p4 - 1, p4 - 2])
    eq(sc >= 3.0, d > 0, f"V1: 直近の改善 d={d} でだけ ≥3.0")
    eq(sc >= 4.0, d > 0, f"V1: Path2 の 4.0 も同じ条件 d={d}")

# 3) cap_weights
w = R.cap_weights({"a": 50, "b": 30, "c": 10, "d": 5, "e": 5}, cap=0.4)
eq(round(sum(w.values()), 12), 1.0, "合計1")
eq(w["a"], 0.4, "上限")
eq(round(w["b"] / w["c"], 9), 3.0, "残りは元の比")
w = R.cap_weights({"a": 1, "b": 1, "c": 1}, cap=0.06)
eq(round(w["a"], 9), round(1 / 3, 9), "1/cap 未満なら等分")
w = R.cap_weights({str(i): (100 if i == 0 else 1) for i in range(30)}, cap=0.06)
eq(round(max(w.values()), 9), 0.06, "6%上限")
eq(round(sum(w.values()), 12), 1.0, "合計1（30社）")


# 4) quarters / ltm_map
def o(s):
    return datetime.date.fromisoformat(s).toordinal()


def row(s, e, seq):
    so, eo = o(s), o(e)
    return (so, eo, eo - so, [o(x[0]) for x in seq], [x[1] for x in seq])


rows = [
    row("2020-01-01", "2020-03-31", [("2020-05-01", 100.0)]),
    row("2020-01-01", "2020-06-30", [("2020-08-01", 250.0)]),
    row("2020-01-01", "2020-09-30", [("2020-11-01", 420.0)]),
    row("2020-01-01", "2020-12-31", [("2021-02-20", 600.0), ("2021-03-01", 610.0)]),   # 訂正で 610
    row("2021-01-01", "2021-03-31", [("2021-05-01", 200.0)]),
]
d = R.quarters(rows, o("2021-02-25"))
eq(d[o("2020-03-31")], 100.0, "Q1")
eq(d[o("2020-06-30")], 150.0, "Q2=6M−Q1")
eq(d[o("2020-09-30")], 170.0, "Q3=9M−6M")
eq(d[o("2020-12-31")], 180.0, "Q4=FY−9M（提出日 2021-02-20 の値 600）")
d2 = R.quarters(rows, o("2021-03-05"))
eq(d2[o("2020-12-31")], 190.0, "訂正後（610）は提出日以降だけ見える")
d3 = R.quarters(rows, o("2020-10-01"))
assert o("2020-09-30") not in d3 and o("2020-06-30") in d3, "S 時点で未提出の四半期は無い"
ok += 1
ends, ltm = R.ltm_map(R.quarters(rows, o("2021-06-01")))
eq(ltm[o("2020-12-31")], 100 + 150 + 170 + 190, "LTM=4四半期の和")
eq(ltm[o("2021-03-31")], 150 + 170 + 190 + 200, "LTM(次)")
assert o("2020-09-30") not in ltm, "4四半期そろわない期は LTM 無し"
ok += 1

# 5) Path 記憶（select_variant・V1）
S = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31",
     "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]


def mk(ni_T, d_ni, d_om, margin):
    """LTM 純利益 T=ni_T、直近の変化 d_ni（>0 改善）、営業利益率も d_om"""
    return {"priced": True, "mcap": 2e9, "w": 2e9, "ni_P": [ni_T, ni_T - d_ni, ni_T - 2 * d_ni, ni_T - 3 * d_ni],
            "om_P": [0.1, 0.1 - d_om, 0.1 - 2 * d_om, 0.1 - 3 * d_om], "ni_T": ni_T, "margin": margin, "neg8": False,
            "fut_ni": None, "fut_om": None, "T": 0, "last_o": 10 ** 6}


cands = {s: {} for s in S}
cands[S[0]]["A"] = mk(-5.0, 2.0, 0.01, -0.1)       # Path1（赤字・改善）
cands[S[1]]["A"] = mk(3.0, 2.0, 0.01, 0.05)         # 黒字化・改善 → Path2（前回ウォッチリスト・8期以内）
cands[S[2]]["A"] = mk(6.0, -1.0, 0.01, 0.08)        # 悪化 → 落ちる
cands[S[3]]["A"] = mk(9.0, 2.0, 0.01, 0.09)         # 改善に戻ったが前回ウォッチリストに居ない → Path2 不可
cands[S[0]]["B"] = mk(-5.0, 2.0, 0.01, -0.2)        # Path1 だけの社（1期だけ）
cands[S[1]]["B"] = mk(4.0, 2.0, 0.01, 0.04)
for k in range(2, 10):
    cands[S[k]]["B"] = mk(4.0 + k, 2.0, 0.01, 0.04)  # 改善し続ける＝Path2 が続くが、Path1 から8期を超えると外れる
res = R.select_variant(cands, S, "V1")
wl = [set(x["sel"]) for x in res]
assert "A" in wl[0] and "A" in wl[1], "A: Path1→Path2"
ok += 1
assert "A" not in wl[2], "A: 悪化で外れる"
ok += 1
assert "A" not in wl[3], "A: 前回ウォッチリストに居ないので Path2 で戻れない"
ok += 1
assert "B" in wl[0] and "B" in wl[8], "B: k=8 は Path1(k=0) から8期以内"
ok += 1
assert "B" not in wl[9], "B: k=9 は Path1 から9期＝外れる"
ok += 1
# 上位75の切り出しと並び
big = {"c%d" % i: mk(-1.0, 1.0, 0.01, -1.0 + i / 200.0) for i in range(100)}
res2 = R.select_variant({S[0]: big}, [S[0]], "V1")
eq(len(res2[0]["sel"]), 75, "上位75")
eq(res2[0]["sel"][0], "c99", "純利益率の高い順")

# 6) simulate: 買い持ちのドリフト・途切れた社・下限版（early=True＝月m+1から）
def bars(d):
    return {int(k): [v, v, 1e6] for k, v in d.items()}


pxs = {"A": {"t": "A", "bars": bars({202003: 100, 202004: 110, 202005: 121, 202006: 121}), "splits": [], "last": 202006},
       "B": {"t": "B", "bars": bars({202003: 100, 202004: 100, 202005: 100}), "splits": [], "last": 202005}}
cd = {"2020-03-31": {"A": {"priced": True, "last_o": 10 ** 6}, "B": {"priced": True, "last_o": 10 ** 6}}}
sel1 = [{"S": "2020-03-31", "names": {"A": 1.0, "B": 1.0}}]
r, ct, dg = R.simulate(sel1, cd, pxs, ["2020-03-31"], mode="base", early=True, weighting="ew")
eq(round(r[202004], 12), 0.05, "1か月目 (10%+0%)/2")
wA = 0.5 * 1.1 / 1.05
eq(round(r[202005], 12), round(wA * 0.10, 12), "2か月目はドリフトした重み（A が大きい）")
# 3か月目: B は系列が途切れた → base は外して A だけ（A は 0%）
eq(round(r[202006], 12), 0.0, "base: 途切れた B を外し A(0%) だけ")
r2, _c, _d = R.simulate(sel1, cd, pxs, ["2020-03-31"], mode="lb", early=True, weighting="ew")
wA2 = wA * 1.1 / (1 + wA * 0.10)
eq(round(r2[202006], 12), round((1 - wA2) * -0.30, 12), "lb: 途切れた B は −30%、A は 0%")
# 費用: 初月に cost×回転を引く（最初の保有は回転0）
r3, _c, _d = R.simulate(sel1, cd, pxs, ["2020-03-31"], mode="base", early=True, weighting="ew", fee=0.012)
eq(round(r3[202004], 12), round(0.05 - 0.001, 12), "信託報酬 年1.2%＝月0.1%")
print(f"OK {ok} 件の検算が通った")
