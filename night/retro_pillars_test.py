# night/retro_pillars_test.py — rep/dur/dom/moatW を歴史で答え合わせする（2026-08-12新設）
#
# ★この器が存在する理由:
#   門の絶対MOAT指数は dom .25 / irr .25 / rep .20 / moatW .18 / dur .12 の加重幾何平均だが、
#   `night/retro_moat_pillars.py` の実測で **歴史側で検定できたのは irr だけ**と判った——
#   **rep / dur / moatW は3ビンテージのどの読解在庫にも欄が存在しない**（キーの和集合に0本）。
#   そこで2013ビンテージ249社の原本を読み直し、門の刻みで4本を採点した在庫を作った。
#   この器はその在庫を、**事前登録（out/retro_moat_pillars_prereg.json・結果を見る前にコミット）
#   のとおりに**裁く。
#
# ⚠ 判定を一つも持たない。規約・値・採点式・刻み・重み・関門・売却規律には触れない。
#
# 入力:
#   out/retro_moat_pillars_2013.json … 読解の在庫（rows: ticker, rep, dur, dom, moatW と各引用）
#   out/retro_returns_2013_all.json  … 実現リターン（tr_cagr・mdd）
#   out/retro_moat_2013{,q}.json     … 既存の irr / moat5（**読解班には見せていない**。突合せはここで初めて行う）
#   out/_retro_docs/2013_{T}.txt     … 原本のキャッシュ（引用の verbatim 照合に使う。無ければ照合を skip）
#
# 出力: out/retro_moat_pillars_test.json
# 実行: python3 night/retro_pillars_test.py [--json]

import json
import math
import os
import random
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
DOC = os.path.join(OUT, "_retro_docs")
NPERM = 2000
HURDLE = 0.15
MIN_N = 150          # 事前登録: 被覆がこれ未満なら「検出力不足で判定不能」
MODE_SHARE_CAP = 0.85  # 事前登録: 最頻値の占有がこれ以上なら「測れない」
PILLARS = ["rep", "dur", "dom", "moatW"]
LEVELS = {"rep": [35, 60, 80, 100], "dur": [55, 75, 85, 100],
          "dom": [50, 70, 85, 100], "moatW": [50, 70, 85, 100]}
# 門の絶対MOAT指数の重み（index.html の ccfMoat と同じ）
W = {"dom": .25, "irr": .25, "rep": .20, "moatW": .18, "dur": .12}
CAP96 = 96           # ccfMoat は各本と指数を96で頭打ちにする


def rows(path, key="rows"):
    p = os.path.join(OUT, path)
    if not os.path.exists(p):
        return []
    d = json.load(open(p))
    return d[key] if isinstance(d, dict) and key in d else (d if isinstance(d, list) else [])


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def rho(a, b, floor=30):
    if len(a) < floor:
        return None
    xs, ys = ranks(a), ranks(b)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def perm_p(a, b, seed, floor=30):
    """会社の並びを1回だけ入れ替える置換（順位相関の帰無）"""
    obs = rho(a, b, floor)
    if obs is None:
        return None
    rnd = random.Random(seed)
    y = list(b)
    hit = 0
    for _ in range(NPERM):
        rnd.shuffle(y)
        r = rho(a, y, floor)
        if r is not None and abs(r) >= abs(obs):
            hit += 1
    return round(hit / NPERM, 4)


def partial(a, b, c):
    ab, ac, bc = rho(a, b), rho(a, c), rho(b, c)
    if ab is None or ac is None or bc is None:
        return None
    d = math.sqrt((1 - ac * ac) * (1 - bc * bc))
    return round((ab - ac * bc) / d, 3) if d > 0 else None


def partial2(a, b, cs):
    """複数の統制変数（cs: list of list）で順位残差を取ってから相関する"""
    if not cs:
        return rho(a, b)
    ya, yb = ranks(a), ranks(b)
    for c in cs:
        rc = ranks(c)
        ya = residual(ya, rc)
        yb = residual(yb, rc)
    n = len(ya)
    ma, mb = sum(ya) / n, sum(yb) / n
    num = sum((ya[i] - ma) * (yb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ya))
    db = math.sqrt(sum((y - mb) ** 2 for y in yb))
    return round(num / (da * db), 3) if da > 0 and db > 0 else None


def residual(y, x):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    b = (sum((x[i] - mx) * (y[i] - my) for i in range(n)) / sxx) if sxx > 0 else 0.0
    return [y[i] - (my + b * (x[i] - mx)) for i in range(n)]


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def verbatim(t, quote):
    """引用が原本のキャッシュに一字一句あるか。キャッシュが無ければ None（skip）"""
    if not quote:
        return None
    p = os.path.join(DOC, f"2013_{t}.txt")
    if not os.path.exists(p):
        return None
    body = norm(open(p, encoding="utf-8", errors="ignore").read())
    q = norm(quote)
    if len(q) < 25:
        return None
    if q in body:
        return True
    # 途中で切られた引用に備え、先頭120字だけでも照合する
    return q[:120] in body


def grade_table(pairs, base):
    g = {}
    for v, y in pairs:
        g.setdefault(v, []).append(y)
    out = {}
    for k, s in sorted(g.items()):
        s2 = sorted(s)
        out[str(k)] = {"n": len(s), "median": round(s2[len(s2) // 2], 4),
                       "p15": round(sum(1 for x in s if x >= HURDLE) / len(s), 3),
                       "loss": round(sum(1 for x in s if x < 0) / len(s), 3),
                       "impair": round(sum(1 for x in s if x <= -HURDLE) / len(s), 3)}
    out["_base"] = base
    return out


def monotone(tab, key="median"):
    """刻みの昇順で key が単調か（同値は許す）"""
    ks = sorted(int(k) for k in tab if k != "_base")
    v = [tab[str(k)][key] for k in ks]
    up = all(v[i] <= v[i + 1] for i in range(len(v) - 1))
    dn = all(v[i] >= v[i + 1] for i in range(len(v) - 1))
    return "単調増" if up and not dn else ("単調減" if dn and not up else "単調でない")


def moat_index(d, irr):
    """index.html の ccfMoat と同じ加重幾何平均（空欄は残りへ再正規化・各本と指数を96で頭打ち）"""
    vals, ws = [], []
    for k in ("dom", "irr", "rep", "moatW", "dur"):
        v = irr if k == "irr" else d.get(k)
        if v is None:
            continue
        vals.append(min(v, CAP96))
        ws.append(W[k])
    if len(vals) < 3 or sum(ws) <= 0:
        return None
    s = sum(ws)
    lg = sum(w / s * math.log(max(v, 1e-9)) for v, w in zip(vals, ws))
    return min(math.exp(lg), CAP96)


def main():
    as_json = "--json" in sys.argv
    src = rows("retro_moat_pillars_2013.json")
    if not src:
        print("out/retro_moat_pillars_2013.json が無い（読解の納品待ち）")
        sys.exit(1)
    px, mdd = {}, {}
    for r in rows("retro_returns_2013_all.json"):
        if r.get("ticker") and r.get("tr_cagr") is not None:
            px[r["ticker"]] = r["tr_cagr"]
            if r.get("mdd") is not None:
                mdd[r["ticker"]] = r["mdd"]
    prev = {}
    for f in ("retro_moat_2013.json", "retro_moat_2013q.json"):
        for r in rows(f):
            if r.get("ticker"):
                prev.setdefault(r["ticker"], r)

    D = {r["ticker"]: r for r in src if r.get("ticker")}
    tk = [t for t in D if t in px]
    base = {"n": len(tk),
            "median": round(sorted(px[t] for t in tk)[len(tk) // 2], 4),
            "p15": round(sum(1 for t in tk if px[t] >= HURDLE) / len(tk), 3),
            "loss": round(sum(1 for t in tk if px[t] < 0) / len(tk), 3),
            "impair": round(sum(1 for t in tk if px[t] <= -HURDLE) / len(tk), 3)}

    out = {"generated": "2026-08-12", "asof": 2013, "window_years": 13.09,
           "prereg": "out/retro_moat_pillars_prereg.json（読解の結果を見る前にコミット）",
           "note": "判定はしない。規約・値・採点式・刻み・重み・関門には触れない",
           "base": base, "coverage": {}, "quote_audit": {}, "primary": {}, "secondary": {}}

    # ── 被覆と引用の verbatim 照合 ──
    for k in PILLARS:
        have = [t for t in tk if isinstance(D[t].get(k), (int, float))]
        vv = [D[t][k] for t in have]
        mode = max((vv.count(v) for v in set(vv)), default=0) / max(1, len(vv))
        ok = sum(1 for t in have if verbatim(t, D[t].get(k + "_quote")) is True)
        chk = sum(1 for t in have if verbatim(t, D[t].get(k + "_quote")) is not None)
        out["coverage"][k] = {"n": len(have), "share": round(len(have) / len(tk), 3),
                              "mode_share": round(mode, 3),
                              "underpowered_n": len(have) < MIN_N,
                              "unmeasurable_variation": mode >= MODE_SHARE_CAP}
        out["quote_audit"][k] = {"checked": chk, "verbatim": ok,
                                 "rate": round(ok / chk, 3) if chk else None,
                                 "note": "キャッシュが無い社は照合を skip（None）"}

    # ── 主判定 ──
    fam = []
    for k in ("rep", "dur"):
        have = [t for t in tk if isinstance(D[t].get(k), (int, float))]
        a, b = [D[t][k] for t in have], [px[t] for t in have]
        r = rho(a, b)
        tab = grade_table(list(zip(a, b)), base)
        rec = {"n": len(have), "rho": round(r, 3) if r is not None else None,
               "perm_p": perm_p(a, b, 20130712 + len(k)),
               "monotone_median": monotone(tab), "monotone_p15": monotone(tab, "p15"),
               "grades": tab,
               "verdict_note": ("被覆不足（n<%d）で判定不能" % MIN_N) if len(have) < MIN_N else None}
        out["primary"][k] = rec
        if r is not None:
            fam.append((abs(r), k, have, a, b))
    # 族全体（2本のうち最大|ρ|を同じ置換で裁く）
    if fam:
        fam.sort(reverse=True)
        obs = fam[0][0]
        common = [t for t in tk if all(isinstance(D[t].get(k), (int, float)) for k in ("rep", "dur"))]
        if len(common) >= 30:
            rnd = random.Random(20130712)
            y = [px[t] for t in common]
            hit = 0
            for _ in range(NPERM):
                rnd.shuffle(y)
                best = 0.0
                for k in ("rep", "dur"):
                    rr = rho([D[t][k] for t in common], y)
                    if rr is not None:
                        best = max(best, abs(rr))
                if best >= obs:
                    hit += 1
            out["primary"]["_family"] = {"n_common": len(common), "max_abs_rho": round(obs, 3),
                                         "argmax": fam[0][1], "family_p": round(hit / NPERM, 4)}

    # ── S1 moat5 は rep/dur の代理か ──
    have = [t for t in tk if isinstance(prev.get(t, {}).get("moat5"), (int, float))
            and isinstance(D[t].get("rep"), (int, float)) and isinstance(D[t].get("dur"), (int, float))]
    if len(have) >= 30:
        m = [prev[t]["moat5"] for t in have]
        y = [px[t] for t in have]
        raw = rho(m, y)
        pr = partial2(m, y, [[D[t]["rep"] for t in have], [D[t]["dur"] for t in have]])
        out["secondary"]["S1_proxy"] = {
            "n": len(have), "moat5_raw_rho": round(raw, 3) if raw is not None else None,
            "moat5_given_rep_dur": pr,
            "line": "生ρの半分以下に落ちれば『代理』を支持",
            "supports_proxy": (pr is not None and raw is not None and abs(pr) <= abs(raw) / 2),
            "rho_moat5_rep": round(rho(m, [D[t]["rep"] for t in have]), 3),
            "rho_moat5_dur": round(rho(m, [D[t]["dur"] for t in have]), 3)}

    # ── S2 門が判断する帯（irr>=70）で効くか ──
    band = [t for t in tk if isinstance(prev.get(t, {}).get("irr"), (int, float)) and prev[t]["irr"] >= 70]
    s2 = {"band_n": len(band)}
    for k in PILLARS:
        h = [t for t in band if isinstance(D[t].get(k), (int, float))]
        if len(h) >= 30:
            a, b = [D[t][k] for t in h], [px[t] for t in h]
            s2[k] = {"n": len(h), "rho": round(rho(a, b), 3), "perm_p": perm_p(a, b, 700 + len(k))}
        else:
            s2[k] = {"n": len(h), "note": "n不足（30未満）"}
    out["secondary"]["S2_band"] = s2

    # ── S3 dom と moatW ──
    s3 = {}
    for k in ("dom", "moatW"):
        h = [t for t in tk if isinstance(D[t].get(k), (int, float))]
        if not h:
            s3[k] = {"n": 0, "note": "在庫に無い"}
            continue
        a, b = [D[t][k] for t in h], [px[t] for t in h]
        cov = out["coverage"][k]
        s3[k] = {"n": len(h), "rho": round(rho(a, b), 3) if rho(a, b) is not None else None,
                 "perm_p": perm_p(a, b, 300 + len(k)),
                 "mode_share": cov["mode_share"],
                 "verdict": "測れない（変動が乏しい）" if cov["unmeasurable_variation"] else "測れる",
                 "grades": grade_table(list(zip(a, b)), base)}
    out["secondary"]["S3_dom_moatW"] = s3

    # ── S4 谷の深さか複利か ──
    s4 = {}
    for k in PILLARS:
        h = [t for t in tk if isinstance(D[t].get(k), (int, float)) and t in mdd]
        if len(h) < 30:
            s4[k] = {"n": len(h), "note": "n不足"}
            continue
        a = [D[t][k] for t in h]
        y = [px[t] for t in h]
        m = [mdd[t] for t in h]
        s4[k] = {"n": len(h), "rho_ret": round(rho(a, y), 3), "rho_mdd": round(rho(a, m), 3),
                 "rho_ret_given_mdd": partial(a, y, m)}
    s4["_note"] = "mdd は同じ窓の事後変数なので統制は因果を測らない。向きだけを読む"
    out["secondary"]["S4_drawdown"] = s4

    # ── S5 絶対MOAT指数そのもの ──
    idx = {}
    for t in tk:
        v = moat_index(D[t], prev.get(t, {}).get("irr"))
        if v is not None:
            idx[t] = v
    if len(idx) >= 30:
        h = sorted(idx)
        a, b = [idx[t] for t in h], [px[t] for t in h]
        hi = [t for t in h if idx[t] >= 70]
        lo = [t for t in h if idx[t] < 70]
        f = lambda s: {"n": len(s), "median": round(sorted(px[t] for t in s)[len(s) // 2], 4),
                       "p15": round(sum(1 for t in s if px[t] >= HURDLE) / len(s), 3),
                       "impair": round(sum(1 for t in s if px[t] <= -HURDLE) / len(s), 3)} if s else None
        out["secondary"]["S5_composite"] = {
            "n": len(idx), "rho": round(rho(a, b), 3), "perm_p": perm_p(a, b, 555),
            "gate70_pass": f(hi), "gate70_fail": f(lo),
            "lift_p15": (round(f(hi)["p15"] - base["p15"], 3) if hi else None),
            "note": "門の関門70+ を歴史で答え合わせする初めての機会。5本のうち3本以上が非nullの社のみ"}

    json.dump(out, open(os.path.join(OUT, "retro_moat_pillars_test.json"), "w"),
              ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    b = out["base"]
    print(f"=== 2013→2026（13.09年）n={b['n']}  ベース 中央値{b['median']:+.4f} / P(15%+) {b['p15']}"
          f" / 元本割れ {b['loss']} / 恒久毀損 {b['impair']} ===")
    print("\n【被覆と引用の照合】")
    for k in PILLARS:
        c, q = out["coverage"][k], out["quote_audit"][k]
        flag = ("  ⚠被覆不足" if c["underpowered_n"] else "") + ("  ⚠変動が乏しく測れない" if c["unmeasurable_variation"] else "")
        print(f"  {k:<7}非null {c['n']:>3}社({c['share']:.0%})  最頻値の占有 {c['mode_share']}"
              f"  引用の逐語一致 {q['verbatim']}/{q['checked']}{flag}")
    print("\n【主判定（事前登録）】")
    for k in ("rep", "dur"):
        r = out["primary"].get(k, {})
        if not r:
            continue
        print(f"  {k:<7}n={r['n']:<4}ρ={r['rho']}  置換p={r['perm_p']}  中央値の刻み {r['monotone_median']}"
              + (f"  ⚠{r['verdict_note']}" if r.get("verdict_note") else ""))
        for kk, v in r["grades"].items():
            if kk == "_base":
                continue
            print(f"      {kk:<5}n={v['n']:<4}中央値 {v['median']:+.4f}  15%+ {v['p15']}  毀損 {v['impair']}")
    if "_family" in out["primary"]:
        f = out["primary"]["_family"]
        print(f"  族全体: 最大|ρ|={f['max_abs_rho']}({f['argmax']})  **族p={f['family_p']}**  n共通={f['n_common']}")
    print("\n【副次】")
    s1 = out["secondary"].get("S1_proxy")
    if s1:
        print(f"  S1 moat5 は rep/dur の代理か: 生ρ={s1['moat5_raw_rho']} → rep/dur統制後 {s1['moat5_given_rep_dur']}"
              f"  → 代理を支持: {s1['supports_proxy']}  (ρ(moat5,rep)={s1['rho_moat5_rep']} / dur={s1['rho_moat5_dur']})")
    s2 = out["secondary"].get("S2_band")
    if s2:
        print(f"  S2 門が判断する帯（irr>=70・n={s2['band_n']}）:")
        for k in PILLARS:
            v = s2.get(k, {})
            print(f"      {k:<7}" + (f"n={v['n']:<4}ρ={v['rho']}  p={v['perm_p']}" if "rho" in v else f"n={v['n']}  {v.get('note')}"))
    s3 = out["secondary"].get("S3_dom_moatW")
    if s3:
        for k, v in s3.items():
            if "rho" in v:
                print(f"  S3 {k:<7}n={v['n']:<4}ρ={v['rho']}  p={v['perm_p']}  最頻値占有 {v['mode_share']} → {v['verdict']}")
    s4 = out["secondary"].get("S4_drawdown")
    if s4:
        print("  S4 谷の深さか複利か:")
        for k in PILLARS:
            v = s4.get(k, {})
            if "rho_ret" in v:
                print(f"      {k:<7}→リターン {v['rho_ret']:+.3f}  →谷の深さ {v['rho_mdd']:+.3f}"
                      f"  谷を統制すると {v['rho_ret_given_mdd']}")
    s5 = out["secondary"].get("S5_composite")
    if s5:
        print(f"  S5 絶対MOAT指数 n={s5['n']}  ρ={s5['rho']}  p={s5['perm_p']}")
        print(f"      関門70+ 通過 {s5['gate70_pass']}")
        print(f"      関門70+ 不通過 {s5['gate70_fail']}   lift(P15+)={s5['lift_p15']}")


if __name__ == "__main__":
    main()
