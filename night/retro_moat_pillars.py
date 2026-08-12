# night/retro_moat_pillars.py — 堀の5本のうち、歴史側で検定されたのはどれか（2026-08-12新設）
#
# ★この器が存在する理由:
#   門の絶対MOAT指数は dom .25 / irr .25 / rep .20 / moatW .18 / dur .12 の加重幾何平均だが、
#   **歴史側で検定されてきたのは irr ただ一本**（と、副次的に moat5＝読み手の主観の堀）。
#   `night/retro_surprise.py` が「読み手の判断は rung より広く『驚き』を当てている」と出したので、
#   **残りの柱が実際に効くのか**を、在庫の読解データだけで測れるところまで測る。
#
# 測れるもの / 測れないもの（正直に）:
#   ・**irr**   … 3ビンテージすべてにある（2013/2015 は 50/70/85/100、**2018 は 50/75/85**＝刻みが違う）
#   ・**moat5** … 3ビンテージすべてにある（読み手の主観 1-5・門の欄ではない）
#   ・**dom**   … **2018ビンテージにだけ** `dom18` として在る＝歴史側で初めての検定
#   ・**moatW** … 直接は無い。2018の `nseg`(セグメント数) を**粗い代理**として使う
#   ・**dep**   … 2018の `cust_max`(最大顧客%) を代理に使う（帯へ丸める）
#   ・**rep / dur** … **どのビンテージにも記録が無い＝構造的に検定できない**（宿題）
#   ⚠ 代理は代理であって欄そのものではない。nseg が多い＝moatW が高い、とは限らない
#
# ⚠ この器は判定を一つも持たない。規約・値・採点式・刻み・重み・関門・売却規律には触れない。
#
# 多重検定: 各欄について**会社の並びを入れ替える置換**（2000回）で p を出す。
#   欄は6本なので family-wise は Bonferroni 相当で p<0.0083 を目安に読む（線は引かない）
#
# 出力: out/retro_moat_pillars.json
# 実行: python3 night/retro_moat_pillars.py [--json]

import json
import math
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
NPERM = 2000
MIN_N = 80

VINTAGES = {
    2013: {"moat": ["retro_moat_2013.json", "retro_moat_2013q.json"],
           "ret": ["retro_returns_2013_all.json"], "irr": "irr", "tk": "ticker", "years": 13.1},
    2015: {"moat": ["retro_moat_2015.json", "retro_moat_2015q.json", "retro_moat_2015qb.json"],
           "ret": ["retro_returns_2015_q.json", "retro_returns_2015.json"], "irr": "irr",
           "tk": "ticker", "years": 11.1},
    2018: {"moat": ["retro_moat_2018.json", "retro_moat_2018_rest.json"],
           "ret": ["retro_returns_2018.json"], "irr": "irr18", "tk": "t", "years": 8.1},
}
HURDLE = 0.15


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


def rho(a, b):
    if len(a) < MIN_N:
        return None
    xs, ys = ranks(a), ranks(b)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else None


def perm_p(a, b, seed):
    obs = rho(a, b)
    if obs is None:
        return None
    rnd = random.Random(seed)
    y = list(b)
    hit = 0
    for _ in range(NPERM):
        rnd.shuffle(y)
        r = rho(a, y)
        if r is not None and abs(r) >= abs(obs):
            hit += 1
    return round(hit / NPERM, 4)


def partial(a, b, c):
    ab, ac, bc = rho(a, b), rho(a, c), rho(b, c)
    if ab is None or ac is None or bc is None:
        return None
    d = math.sqrt((1 - ac * ac) * (1 - bc * bc))
    return round((ab - ac * bc) / d, 3) if d > 0 else None


def load(v):
    cfg = VINTAGES[v]
    m = {}
    for f in cfg["moat"]:
        for r in rows(f):
            t = r.get(cfg["tk"]) or r.get("ticker") or r.get("t")
            if t and t not in m:
                m[t] = dict(r)
    px = {}
    for f in cfg["ret"]:
        for r in rows(f):
            if r.get("ticker") and r.get("tr_cagr") is not None and r["ticker"] not in px:
                px[r["ticker"]] = r["tr_cagr"]
    tk = [t for t in m if t in px]
    # 代理欄を作る（帯へ丸める・元の値は壊さない）
    for t in tk:
        c = m[t].get("cust_max")
        m[t]["_dep"] = None if c is None else (0 if c < 10 else (1 if c < 20 else 2))
        rc = m[t].get("rec")
        m[t]["_rec"] = None if rc is None else (1 if rc else 0)
    return m, px, tk, cfg


def analyse(v):
    m, px, tk, cfg = load(v)
    if len(tk) < MIN_N:
        return None
    base = sorted(px[t] for t in tk)
    out = {"vintage": v, "years": cfg["years"], "n_read": len(m), "n_matched": len(tk),
           "base_median": round(base[len(base) // 2], 4),
           "base_p15": round(sum(1 for x in base if x >= HURDLE) / len(base), 3),
           "pillars": {}}
    FIELDS = [(cfg["irr"], "irr", "移行障壁の型"),
              ("moat5", "moat5", "読み手の主観の堀1-5（門の欄ではない）"),
              ("dom18", "dom", "支配シェア（2018のみ在庫あり）"),
              ("nseg", "moatW(代理)", "セグメント数＝堀の広さの粗い代理"),
              ("_dep", "dep(代理)", "最大顧客の帯 0:<10% 1:10-20% 2:20%+"),
              ("_rec", "読み手の推奨", "読み手が推したか（採点欄ではない）")]
    for key, lab, note in FIELDS:
        vv = [(m[t][key], px[t]) for t in tk if isinstance(m[t].get(key), (int, float))]
        if not vv:
            out["pillars"][lab] = {"note": note, "n": 0, "status": "この年の在庫に無い"}
            continue
        g = {}
        for a, b in vv:
            g.setdefault(a, []).append(b)
        grades = {str(k): {"n": len(s), "median": round(sorted(s)[len(s) // 2], 4),
                           "p15": round(sum(1 for x in s if x >= HURDLE) / len(s), 3)}
                  for k, s in sorted(g.items())}
        a_, b_ = [x[0] for x in vv], [x[1] for x in vv]
        r = rho(a_, b_)
        # ★変動が無ければ「効かない」ではなく「測れない」——最頻値の占有率を必ず出す
        top = max(len(s) for s in g.values()) / len(vv)
        out["pillars"][lab] = {
            "note": note, "n": len(vv), "n_levels": len(g),
            "mode_share": round(top, 3),
            "rho": round(r, 3) if r is not None else None,
            "perm_p": perm_p(a_, b_, 20260812 + v + len(lab)),
            "underpowered": top >= 0.85,
            "grades": grades}
    # 互いを除いた偏相関（在る欄だけ）
    keys = [k for k in (cfg["irr"], "moat5", "dom18") ]
    sub = [t for t in tk if all(isinstance(m[t].get(k), (int, float)) for k in keys)]
    if len(sub) >= MIN_N:
        Y = [px[t] for t in sub]
        col = {k: [m[t][k] for t in sub] for k in keys}
        I, M = col[cfg["irr"]], col["moat5"]
        out["partial"] = {
            "n": len(sub),
            "irr": {"rho": round(rho(I, Y), 3), "given_moat5": partial(I, Y, M)},
            "moat5": {"rho": round(rho(M, Y), 3), "given_irr": partial(M, Y, I)},
        }
        if "dom18" in col:
            D = col["dom18"]
            out["partial"]["dom"] = {"rho": round(rho(D, Y), 3), "given_moat5": partial(D, Y, M)}
    return out


def main():
    as_json = "--json" in sys.argv
    res = [a for a in (analyse(v) for v in sorted(VINTAGES)) if a]
    out = {"generated": "2026-08-12",
           "question": "堀の5本のうち歴史側で検定できるのはどれか。効いたのはどれか",
           "note": "判定はしない。rep と dur はどの読解在庫にも無く構造的に検定できない（宿題）",
           "hurdle": HURDLE, "vintages": res}
    # 3ビンテージの横並び（結論はここで読む）
    tab = {}
    for a in res:
        for lab, p in a["pillars"].items():
            tab.setdefault(lab, {})[str(a["vintage"])] = {
                "rho": p.get("rho"), "p": p.get("perm_p"), "n": p.get("n"),
                "underpowered": p.get("underpowered")}
    out["across_vintages"] = tab
    json.dump(out, open(os.path.join(OUT, "retro_moat_pillars.json"), "w"),
              ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for a in res:
        print(f"\n=== {a['vintage']}→2026（{a['years']}年）読解{a['n_read']} 突合{a['n_matched']}"
              f"  ベース中央値 {a['base_median']:+.4f} / P(15%+) {a['base_p15']} ===")
        for lab, p in a["pillars"].items():
            if p.get("status"):
                print(f"  {lab:<14}{p['status']}")
                continue
            flag = "  ⚠変動が乏しく測れない" if p["underpowered"] else ""
            print(f"  {lab:<14}n={p['n']:<4}ρ={('%+.3f' % p['rho']) if p['rho'] is not None else 'na':<8}"
                  f"p={p['perm_p']}  最頻値の占有 {p['mode_share']}{flag}")
            print("      " + "  ".join(f"{k}:n{v['n']}/中{v['median']:+.3f}/15%+{v['p15']}"
                                       for k, v in p["grades"].items()))
        if a.get("partial"):
            q = a["partial"]
            s = f"  偏相関 n={q['n']}  irr {q['irr']['rho']:+.3f}(moat5除く {q['irr']['given_moat5']:+.3f})" \
                f" | moat5 {q['moat5']['rho']:+.3f}(irr除く {q['moat5']['given_irr']:+.3f})"
            if "dom" in q:
                s += f" | dom {q['dom']['rho']:+.3f}(moat5除く {q['dom']['given_moat5']:+.3f})"
            print(s)
    print("\n=== 3ビンテージ横並び（ρ / 置換p）===")
    for lab, d in out["across_vintages"].items():
        print(f"  {lab:<14}" + "  ".join(
            f"{v}:{('%+.3f' % x['rho']) if x['rho'] is not None else 'na'}(p{x['p']}{'⚠' if x.get('underpowered') else ''})"
            for v, x in sorted(d.items())))


if __name__ == "__main__":
    main()
