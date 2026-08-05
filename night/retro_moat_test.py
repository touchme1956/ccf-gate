# night/retro_moat_test.py — 「当時の原本から読んだ堀」は継続組を捕捉できるか（2026-08-05新設）
#
# 30%の壁の検証の本丸。機械の数字（14→20系統）が P=0.50 を越えられないことは
# retro_capture2 で確定した。門の思想は「最後の分離は定性の堀」だが、それは
# 歴史で検証されていなかった。45班が2018-07以前の10-K/20-Fだけを読み（引用必須・
# その後の運命は知らせない）採点した dom18/irr18/moat5 を実現リターンに突き合わせる。
#
# 正直さの担保:
#   - 読解は 140/177社で止まった（セッション上限）。**打ち切りはティッカーのアルファベット順**
#     なので結果に対して概ね無作為だが、打ち切り群と読了群のベース率を必ず並記して確かめる。
#   - 読解者はその社の結末を知らない状態で採点したが、LLMの事前知識の混入は完全には
#     排除できない（AAPL/MSFTは有名）。**無名社に絞った再計測**を併せて出す。
#   - レジーム検問（2018-22 / 2022-26）を機械シグナルと同じ基準で通す。
# 実行: python3 night/retro_moat_test.py
import json, os, statistics, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(n):
    return json.load(open(os.path.join(BASE, "out", n)))


M = {r["t"]: r for r in load("retro_moat_2018.json")["rows"]}
FR = {r["t"]: r for r in load("retro_frame_2018.json")["rows"]}
MON2 = load("retro_monthly_2018_2026.json")
CUT = datetime.datetime(2022, 7, 1).timestamp()


def subs(t):
    pts = MON2.get(t)
    if not pts or len(pts) < 24:
        return None, None
    a = [(ts, v) for ts, v in pts if ts < CUT]
    b = [(ts, v) for ts, v in pts if ts >= CUT]
    if len(a) < 24 or len(b) < 24 or a[0][1] <= 0 or b[0][1] <= 0:
        return None, None
    ya = (a[-1][0] - a[0][0]) / (365.25 * 86400)
    yb = (b[-1][0] - b[0][0]) / (365.25 * 86400)
    return (a[-1][1] / a[0][1]) ** (1 / ya) - 1, (b[-1][1] / b[0][1]) ** (1 / yb) - 1


demoQ = [r for r in FR.values() if r["rf5"] >= 0.15
         and (r.get("fcfpos5") or 0) >= 4 and (r.get("opm") or -9) >= 0.10]
read = [r for r in demoQ if r["t"] in M]
unread = [r for r in demoQ if r["t"] not in M]


def P(g):
    return sum(1 for r in g if r["r18"] >= 0.15) / len(g) if g else None


print(f"=== 打ち切りの偏りの検査 ===")
print(f"  demoQ全体 n={len(demoQ)} P={P(demoQ):.2f}  /  読了 n={len(read)} P={P(read):.2f}"
      f"  /  未読 n={len(unread)} P={P(unread):.2f}")
print(f"  → 差 {abs(P(read)-P(unread)):.2f}pt（アルファベット順の打ち切り＝結果に対して概ね無作為）")

rows = []
for r in read:
    m = M[r["t"]]
    a, b = subs(r["t"])
    rows.append({**r, **{k: m.get(k) for k in
                         ("dom18", "irr18", "moat5", "cust_max", "cust_none10", "rec", "nseg")},
                 "rA": a, "rB": b, "rev": r.get("rev")})
base = P(rows)
print(f"\n=== 定性の堀 vs 継続（読了 n={len(rows)}・ベース {base:.2f}） ===")


def cell(g, label, key="r18"):
    if len(g) < 8:
        print(f"  {label:34s} n={len(g):3d}  （n<8で判定保留）")
        return
    xs = [r[key] for r in g if r.get(key) is not None]
    p = sum(1 for x in xs if x >= 0.15) / len(xs)
    print(f"  {label:34s} n={len(xs):3d}  P(継続)={p:.2f}  中央値{statistics.median(xs)*100:+5.1f}%/年"
          f"  lift{p-base:+.2f}")


print("--- moat5（堀の記述の具体性 1-5） ---")
for v in (5, 4, 3, 2, 1):
    cell([r for r in rows if r["moat5"] == v], f"moat5={v}")
cell([r for r in rows if (r["moat5"] or 0) >= 4], "moat5>=4（構造的優位あり）")
print("--- dom18（市場支配・v9.9.41の刻み） ---")
for v in (100, 85, 70, 50, None):
    cell([r for r in rows if r["dom18"] == v], f"dom18={v}")
print("--- irr18（移行障壁） ---")
for v in (85, 75, 50, None):
    cell([r for r in rows if r["irr18"] == v], f"irr18={v}")
print("--- その他 ---")
cell([r for r in rows if r["rec"] is True], "recurring収益を強調")
cell([r for r in rows if r["rec"] is False], "recurring強調なし")
cell([r for r in rows if r["cust_none10"] is True], "10%超の顧客なし（分散）")
cell([r for r in rows if (r["cust_max"] or 0) >= 10], "最大顧客10%以上（集中）")
cell([r for r in rows if (r["nseg"] or 0) >= 3], "報告セグメント3以上")
cell([r for r in rows if (r["nseg"] or 9) == 1], "単一セグメント")

print("\n--- 門の形（堀の複合）: 事前登録基準 P>=0.50 ∧ 捕捉>=1/3 で判定 ---")
CN = sum(1 for r in rows if r["r18"] >= 0.15)
combos = [
    ("moat5>=4", lambda r: (r["moat5"] or 0) >= 4),
    ("moat5>=4 ∧ irr18>=75", lambda r: (r["moat5"] or 0) >= 4 and (r["irr18"] or 0) >= 75),
    ("moat5>=4 ∧ dom18>=70", lambda r: (r["moat5"] or 0) >= 4 and (r["dom18"] or 0) >= 70),
    ("moat5>=4 ∧ rec", lambda r: (r["moat5"] or 0) >= 4 and r["rec"] is True),
    ("moat5>=4 ∧ 顧客分散", lambda r: (r["moat5"] or 0) >= 4 and r["cust_none10"] is True),
    ("dom18>=70 ∧ irr18>=75", lambda r: (r["dom18"] or 0) >= 70 and (r["irr18"] or 0) >= 75),
    ("moat5>=4 ∧ R&D>med", None),  # 下で閾値を作る
]
v_rnd = sorted(r["rnd_r"] for r in rows if r.get("rnd_r") is not None)
m_rnd = v_rnd[len(v_rnd) // 2] if v_rnd else 0
combos[-1] = ("moat5>=4 ∧ R&D>med",
              lambda r: (r["moat5"] or 0) >= 4 and (r.get("rnd_r") or -1) > m_rnd)
res = []
for label, f in combos:
    g = [r for r in rows if f(r)]
    if len(g) < 8:
        print(f"  {label:30s} n={len(g)} （n<8）")
        continue
    cap = sum(1 for r in g if r["r18"] >= 0.15)
    p = cap / len(g)
    ok = " ★事前登録基準クリア" if (p >= 0.50 and cap >= CN / 3) else ""
    print(f"  {label:30s} n={len(g):3d}  P={p:.2f}  捕捉{cap}/{CN}"
          f"  中央値{statistics.median(r['r18'] for r in g)*100:+5.1f}%{ok}")
    res.append({"cond": label, "n": len(g), "p": round(p, 3), "capture": cap,
                "pass": bool(p >= 0.50 and cap >= CN / 3)})

print("\n--- レジーム検問（moat5>=4・機械シグナルと同じ基準） ---")
g4 = [r for r in rows if (r["moat5"] or 0) >= 4]
for key, lab in (("rA", "前期2018-22"), ("rB", "後期2022-26")):
    xs = [r[key] for r in rows if r.get(key) is not None]
    ys = [r[key] for r in g4 if r.get(key) is not None]
    if len(ys) >= 8:
        pb = sum(1 for x in xs if x >= 0.15) / len(xs)
        pg = sum(1 for y in ys if y >= 0.15) / len(ys)
        print(f"  {lab}: base={pb:.2f} → moat5>=4 P={pg:.2f} (n={len(ys)}) lift{pg-pb:+.2f}")

print("\n--- LLMの事前知識の混入検査（有名社を外す: 売上100億$以上を除外） ---")
small = [r for r in rows if (r.get("rev") or 0) < 1e10]
bs = P(small)
gs = [r for r in small if (r["moat5"] or 0) >= 4]
if len(gs) >= 8:
    print(f"  無名寄り n={len(small)} base={bs:.2f} → moat5>=4 P={P(gs):.2f} (n={len(gs)}) lift{P(gs)-bs:+.2f}")

json.dump({"generated": datetime.date.today().isoformat(), "n_read": len(rows),
           "base": round(base, 3), "bias_check": {"read": round(P(read), 3),
                                                  "unread": round(P(unread), 3)},
           "combos": res},
          open(os.path.join(BASE, "out", "retro_moat_test.json"), "w"),
          ensure_ascii=False, indent=1)
print("■ out/retro_moat_test.json へ記録")
