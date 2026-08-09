# night/_histval_crosscheck.py — hist_valuation.py の自己検算（使い捨てではなく再実行可能）
#
# out/retro_per_{Y}*.json（別実装・別経路・2026-08-04）と突き合わせる。
# 両者は **意図的に基準が違う**ので「一致するか」ではなく「差が説明できるか」を見る:
#   retro : asof の**板の株価** ÷ (as-reported 純利益 ÷ 加重平均希薄化後株数)   FY末 ≤ asof年3月 で切る
#   本器  : 前月の**今日基準の株価** × 発行済株数(今日基準) ÷ as-reported 純利益   filed ≤ asof で切る
# 差の成分は3つ: (1)価格の月 (2)株数の種類 (3)決算の切り方。(1)は割り算で消せる。
#
# いちばん効く検問は **株価そのもの**: retro_px / 本器_px は
#   「asof 以降の累積分割倍率」に**ぴったり**一致しなければならない（整数比になる）。
#   ここがずれたら、どちらかが分割を取り違えている＝この台帳が5回踏んだ型。
#
# **ビンテージ共通**（2026-08-09に2015で使うため一般化。年を1箇所も直書きしない＝
#   ビンテージごとに検算器を書き分けると、同じ台帳を見る検査器が違うことを言い始める）:
#   asof は HV ファイルの中の "asof" から読む。retro側の相手は out/retro_per_{Y}_all.json →
#   無ければ out/retro_per_{Y}.json。第2引数で明示指定もできる。
#   使い方: python3 night/_histval_crosscheck.py out/hist_val_2015.json
import json
import math
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "out", "hist_val_2018.json")

_hvj = json.load(open(HV))
ASOF = _hvj.get("asof") or "2018-07-01"          # 例 "2015-07-01"
Y = int(ASOF[:4])
PREV_M = f"{Y}-{int(ASOF[5:7])-1:02d}" if int(ASOF[5:7]) > 1 else f"{Y-1}-12"
if len(sys.argv) > 2:
    RP = sys.argv[2]
else:
    RP = next((p for p in (os.path.join(BASE, "out", f"retro_per_{Y}_all.json"),
                           os.path.join(BASE, "out", f"retro_per_{Y}.json"))
               if os.path.exists(p)), None)
    if RP is None:
        print(f"⚠ out/retro_per_{Y}*.json が無い → 検問1・2（別実装との突合せ）は飛ばす")

def _lg(x):
    return math.log(x) if x and x > 0 else 0.0


hv = {r["ticker"]: r for r in _hvj["rows"]}
rp = {r["ticker"]: r for r in json.load(open(RP))["rows"]} if RP else {}
both = sorted(set(hv) & set(rp))
print(f"asof={ASOF}  本器 {len(hv)}社 / retro {len(rp)}社"
      f"({os.path.basename(RP) if RP else '—'}) / 共通 {len(both)}社")

# ── 検問1: 株価が分割の翻訳ぶんだけ違うか（いちばん効く検問）────────────────────
#   retro_px（asofの**板の値**） = 本器px（今日基準・asofの前月） × S(asof) × (1ヶ月の値動き)
#   S は**キャッシュした分割イベントから厳密に計算**する（「きりの良い比」を当てにいくと
#   逆分割〔比<1〕を見落とす。初版はここで ASPS の 1:8 逆分割を「事故」と誤検出した）。
#   残差＝1ヶ月の値動きなので、±40%を超えたらどちらかの株価が壊れている。
import gzip as _gz
CACHE = os.path.join(BASE, "out", "_histval_cache", "px")


def _split_factor_after(tk, day):
    p = os.path.join(CACHE, f"{tk}.json.gz")
    if not os.path.exists(p):
        return None
    with _gz.open(p, "rt", encoding="utf-8") as f:
        j = json.load(f)
    fac = 1.0
    for s in j.get("splits", []):
        if s["date"] > day:
            fac *= s["ratio"]
    return fac


resid, bad_split, nofac = [], [], 0
for t in both:
    a, b = hv[t].get("px"), rp[t].get("px")
    if not a or not b:
        continue
    S = _split_factor_after(t, ASOF)
    if S is None:
        nofac += 1
        continue
    x = b / (a * S)                       # ＝1ヶ月の値動き（1.0前後のはず）
    resid.append((t, x, S))
    if not (0.60 <= x <= 1.40):
        bad_split.append((t, round(x, 4), S))
rs = sorted(x for _, x, _ in resid)
print(f"\n【検問1】retro_px ÷ (本器px × 分割倍率) ＝ {PREV_M}→{ASOF[:7]} の値動き   n={len(rs)}")
if rs:
    print(f"   中央値 {statistics.median(rs):.4f}  p05 {rs[len(rs)//20]:.3f}  p95 {rs[19*len(rs)//20]:.3f}"
          )
print(f"   ±40%を外れる＝株価が壊れている疑い: {len(bad_split)}社")
for t, x, S in sorted(bad_split, key=lambda z: -abs(_lg(z[1])))[:20]:
    print(f"   {t:6s} 残差{x:8.4f}  分割倍率{S:g}  本器px={hv[t].get('px')} retro_px={rp[t].get('px')}")

# ── 検問2: 倍率の水準（価格の月ぶんを補正してから比べる）──────────────────────
rows = []
for t in both:
    h, r_ = hv[t], rp[t]
    if h.get("pe_ann") is None or not r_.get("per") or not h.get("px") or not r_.get("px"):
        continue
    fx = r_["px"] / h["px"]                     # ＝分割倍率×1ヶ月の値動き
    rows.append((t, h["pe_ann"], r_["per"], h["pe_ann"] / r_["per"]))
rat = [x[3] for x in rows]
rat.sort()
if rat:
    def q(p):
        return rat[min(int(p * len(rat)), len(rat) - 1)]
    print(f"\n【検問2】pe_ann / retro_per   n={len(rat)}")
    print(f"   中央値 {statistics.median(rat):.3f}   p10 {q(.10):.3f}  p25 {q(.25):.3f}  "
          f"p75 {q(.75):.3f}  p90 {q(.90):.3f}")
    print(f"   ±15%以内: {100.0*sum(1 for x in rat if 0.85<=x<=1.15)/len(rat):.1f}%   "
          f"±30%以内: {100.0*sum(1 for x in rat if 0.70<=x<=1.30)/len(rat):.1f}%")
    out = sorted(rows, key=lambda x: -abs(_lg(x[3])))[:15]
    print("   乖離の大きい社:")
    for t, a, b, r in out:
        print(f"     {t:6s} 本器pe_ann={a:9.2f}  retro_per={b:8.2f}  比{r:6.2f}  "
              f"retro_fy={rp[t]['fy_end']}  本器fy={hv[t]['diag'].get('ni_ttm_end')}")

    # ── 乖離の原因を2つに切り分ける ────────────────────────────────────────
    # (a) retro が **古い会計年度** を掴んでいる（CLAUDE.md が BKNG で記録した
    #     「取れた値＝最新の値」型。retro の annual_entries は最初に当たったタグで break する）
    # (b) 会計年度は同じでも **申告日と asof の間に分割があった**（retro は asof 以降の分割しか
    #     株価に戻さないので、申告EPSが分割前・株価が分割後という基準の違う二つを割る）
    RECENT = (str(Y - 1), str(Y))          # asof直前の2会計年度
    same = [(t, a, b, r) for t, a, b, r in rows if rp[t]["fy_end"][:4] in RECENT]
    old = [(t, a, b, r) for t, a, b, r in rows if rp[t]["fy_end"][:4] < RECENT[0]]
    print(f"\n   (a) retro が {RECENT[0]}/{RECENT[1][2:]}年度を使った社 {len(same)} / {int(RECENT[0])-1}年以前の古い年度 {len(old)}")
    if old:
        yrs = {}
        for t, *_ in old:
            yrs[rp[t]["fy_end"][:4]] = yrs.get(rp[t]["fy_end"][:4], 0) + 1
        print(f"       古い年度の内訳: {dict(sorted(yrs.items()))}")
    if same:
        rs2 = sorted(x[3] for x in same)
        print(f"   同じ年度どうしの比: 中央値 {statistics.median(rs2):.3f}  "
              f"±15%以内 {100.0*sum(1 for x in rs2 if .85<=x<=1.15)/len(rs2):.1f}%  "
              f"±30%以内 {100.0*sum(1 for x in rs2 if .70<=x<=1.30)/len(rs2):.1f}%")
        wide = [(t, a, b, r) for t, a, b, r in same if not (0.70 <= r <= 1.30)]
        print(f"   (b) 同じ年度なのに±30%を外れる {len(wide)}社 — 申告日〜asofの分割の有無:")
        for t, a, b, r in sorted(wide, key=lambda z: -abs(_lg(z[3])))[:12]:
            p = os.path.join(CACHE, f"{t}.json.gz")
            sp = []
            if os.path.exists(p):
                with _gz.open(p, "rt", encoding="utf-8") as f:
                    sp = [s for s in json.load(f).get("splits", [])
                          if f"{Y-1}-01-01" <= s["date"] <= ASOF]
            print(f"     {t:6s} 比{r:5.2f}  期間内の分割 {sp if sp else 'なし'}")

# ── 検問3: TTM と 直近FY の差（2017年の税制改革の汚染を測る）──────────────────
pair = [(t, hv[t]["pe"], hv[t]["pe_ann"]) for t in hv
        if hv[t].get("pe") and hv[t].get("pe_ann")]
if pair:
    rr = sorted(a / b for _, a, b in pair)
    print(f"\n【検問3】pe(TTM) / pe_ann(直近FY)  n={len(rr)}  "
          f"中央値 {statistics.median(rr):.3f}  p10 {rr[len(rr)//10]:.3f}  p90 {rr[9*len(rr)//10]:.3f}")

# ── 検問3b: EPSタグ版 と 時価総額÷純利益版 の一致と被覆 ──────────────────────
#   親からの宿題「EPSタグを素直に使うか NI÷株数で作るかを実測で比べて決めよ」への答え。
ea = [(t, x["extras"]["pe_eps"], x["pe"]) for t, x in hv.items()
      if (x.get("extras") or {}).get("pe_eps") and x.get("pe")]
only_mcap = sum(1 for x in hv.values() if x.get("pe") and not (x.get("extras") or {}).get("pe_eps"))
only_eps = sum(1 for x in hv.values() if not x.get("pe") and (x.get("extras") or {}).get("pe_eps"))
if ea:
    rr = sorted(a / b for _, a, b in ea)
    print(f"\n【検問3b】pe_eps(EPSタグ) / pe(時価総額÷純利益)  n={len(rr)}  "
          f"中央値 {statistics.median(rr):.4f}  p10 {rr[len(rr)//10]:.3f}  p90 {rr[9*len(rr)//10]:.3f}")
    print(f"   ±5%以内 {100.0*sum(1 for x in rr if .95<=x<=1.05)/len(rr):.1f}%   "
          f"時価総額版だけ算出できた社 {only_mcap}  /  EPS版だけ {only_eps}")

# ── 検問4: 被覆と分位の分布 ──────────────────────────────────────────────────
allr = list(hv.values())
print(f"\n【検問4】被覆 n={len(allr)}")
for k in ("pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct", "pe_pct_ann", "spx_pe_pct"):
    v = [x[k] for x in allr if x.get(k) is not None]
    print(f"   {k:12s} {len(v):4d}社 ({100.0*len(v)/len(allr):5.1f}%)"
          + (f"  中央値{statistics.median(v):.3f}  ≥0.90が{100.0*sum(1 for z in v if z>=0.9)/len(v):5.1f}%"
             if v else ""))

# ── 検問5: 全滅した社の理由（生存バイアスの実数）────────────────────────────
dead = {}
for x in allr:
    w = (x.get("nulls") or {}).get("all")
    if w:
        dead[w[:40]] = dead.get(w[:40], 0) + 1
print(f"\n【検問5】1指標も出せなかった社 {sum(dead.values())} / {len(allr)}")
for w, n in sorted(dead.items(), key=lambda z: -z[1]):
    print(f"   {n:4d}  {w}")
print("   ※ ここが小さいのは本器が生存バイアスを免れているからではない——**入力の母集団**が"
      "\n     『今日のティッカーで価格が引ける社』で既に絞られているから。自己履歴は長く生きた社"
      "\n     にしか作れないので、この検定は構造的に生存者寄り（事前登録の既知リスクどおり）。"
      "\n     『asof以前の月足が無い』は破産・改称で系列が今日側にしか無い社（DBD型）＝"
      "\n     数字を作らず null で落とすのが正しい。")

# ── 検問6: 指標どうしの相関（同じことを測っていないか）──────────────────────
import itertools
keys = ("pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct")
print("\n【検問6】指標どうしの順位相関（1.0に近ければ同じものを測っている）")
for a, b in itertools.combinations(keys, 2):
    xs = [(x[a], x[b]) for x in allr if x.get(a) is not None and x.get(b) is not None]
    if len(xs) < 30:
        continue
    ra = {v: i for i, v in enumerate(sorted(set(z[0] for z in xs)))}
    rb = {v: i for i, v in enumerate(sorted(set(z[1] for z in xs)))}
    n = len(xs)
    ma = statistics.mean(ra[z[0]] for z in xs)
    mb = statistics.mean(rb[z[1]] for z in xs)
    cov = sum((ra[z[0]] - ma) * (rb[z[1]] - mb) for z in xs)
    va = sum((ra[z[0]] - ma) ** 2 for z in xs) ** .5
    vb = sum((rb[z[1]] - mb) ** 2 for z in xs) ** .5
    print(f"   {a:11s} × {b:11s} n={n:4d}  ρ={cov/(va*vb):.3f}")



