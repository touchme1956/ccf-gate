#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_moat_double_count.py — **堀の柱どうしが同じ事実を二度数えていないか数える**（2026-08-13新設）

■ なぜ要るか（todo: moat_dom_irr_double_count）
  v9.9.141 で「最上段(100)を85として採点する」を入れたが、**なぜ最上段が劣るのか**の
  有力な説明である**二重計上**は手つかずのまま残った。
  規約の文そのものに重なりがある——
    dom=100 の刻みは「独占≥90%、**または実質唯一供給**」
    irr=100 の刻みは「**唯一供給**」
  ＝**同じ一つの事実（唯一供給）が、重み .25 と .25 の二つの欄を同時に満たす**。
  さらに dur=100 は「**規制**/プロセス知/物理」で、規制フランチャイズ由来の唯一供給は
  irr=100 と dur=100 を同時に満たしうる（.25 + .12）。
  v9.9.45 で TAM柱を廃した理由「**同じ信号を二度数えない**」に正面から反する。

■ ⚠ この道具は判定を一つも持たない
  Ω・採点式・刻み・重み・関門・売却規律・配分には一切触れない。**列挙するだけ**。
  「同じ事実か」の最終判定は**原本を読む審査官の側**にある（機械のキーワード一致は
  irr=70 で偽陽性だらけだったという実測が既にある——同じ轍を踏まない）。
  出すのは (a)規約の定義そのものが重なる社 (b)引用が literally 共有されている社
  (c)機構語が両方の欄に現れる社 の**作業リスト**である。

■ 数え方（結果を見る前に固定した規則）
  1. **引用の共有**——evidence の中の引用（『』"" “” で囲まれた span）を正規化し、
     二つの欄で **40字以上**共通する span があれば「引用共有」。
     ⚠ 部分文字列ではなく**共通部分文字列の最長**で測る（片方が長い引用でもう一方がその一部、を拾う）
  2. **機構語の共有**——唯一供給を主張する語群 SOLE と、規制を主張する語群 REG を定義し、
     どちらの欄にも同じ語群が現れるか。⚠ これは**弱い証拠**（同じ語でも別の事実を指しうる）
  3. **規約の定義の重なり**——irr=100 は規約上 dom=100 の条件を**定義上満たす**ので、
     evidence が無くても構造的に重なる。**dom が空欄でも「重なりうる」として数える**
     （空欄は他4本の平均を与えるので、唯一供給の事実が dom 側にも効いている可能性が残る）

■ 使い方
  python3 night/audit_moat_double_count.py            要約 + 作業リスト
  python3 night/audit_moat_double_count.py --all      全社の内訳
  python3 night/audit_moat_double_count.py --json     out/moat_double_count.json を書く
  python3 night/audit_moat_double_count.py --t ASML   1社の中身
"""
import json, os, re, sys, glob, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# 正は index.html の ccfMoat（v9.9.36の5本重み）
W = {"dom": .25, "irr": .25, "rep": .20, "dur": .12, "moatW": .18}
# 正は index.html の ccfMoat（v9.9.141: 最上段は一つ下として採点）
TOPCAP = {"irr": 85, "dur": 85}

# 「唯一供給・排他」を主張する語（規約 dom=100「または実質唯一供給」／irr=100「唯一供給」の引き金）
SOLE = [
    r"only manufacturer", r"sole (?:provider|supplier|source|manufacturer)",
    r"single source", r"exclusive franchise", r"exclusive right", r"exclusive territor",
    r"free from (?:direct )?competition", r"no competition", r"not (?:currently )?subject to competition",
    r"唯一供給", r"実質唯一", r"独占",
]
# 「規制」を主張する語（規約 dur=100「規制/プロセス知/物理」の引き金）
REG = [
    r"regulated", r"regulator", r"franchise", r"tariff", r"public utilit",
    r"commission", r"rate case", r"規制", r"フランチャイズ", r"料金",
]
GROUPS = {"SOLE": SOLE, "REG": REG}
# 「法で守られた排他的な事業権」——コンセッション・フランチャイズ・専属区域。
# ⚠ SOLE より狭い（技術的な唯一供給を含まない）。これが**どの柱に置かれているか**を数えるため
EXCL = re.compile(r"exclusive franchise|exclusive right|exclusive territor|exclusive concession|"
                  r"franchised territory|free from .{0,25}competition|no competition for|"
                  r"not .{0,20}subject to competition|独占コンセッション|排他的|独占的", re.I)

QUOTE = re.compile(r"『([^』]{20,})』|“([^”]{20,})”|\"([^\"]{20,})\"|「([^」]{20,})」")
MIN_SHARE = 40          # 共通部分文字列の最短（字）


def norm(s):
    """引用を突き合わせるための正規化——全角/半角・空白・強調記号を落とす。
    ⚠ irr85_mech_diff.py と同じ作法（** を空白でなく**空文字**へ落とす。
      空白へ落とすと『certification**.』が『certification .』になり本文と一致しなくなる）。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("**", "").replace("*", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def quotes(s):
    out = []
    for m in QUOTE.finditer(s or ""):
        q = next(g for g in m.groups() if g)
        q = norm(q)
        if len(q) >= MIN_SHARE:
            out.append(q)
    return out


def lcs_len(a, b):
    """最長共通部分文字列の長さ（DPは O(n*m) だが引用は短いので十分）"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def shared_quote(ea, eb):
    """二つの evidence の引用のあいだで MIN_SHARE 以上共通する最長 span を返す（無ければ None）"""
    qa, qb = quotes(ea), quotes(eb)
    best, bl = None, 0
    for x in qa:
        for y in qb:
            n = lcs_len(x, y)
            if n >= MIN_SHARE and n > bl:
                bl = n
                # 実際の共通部分を復元（最長一致の位置を探す）
                for i in range(len(x) - n + 1):
                    if x[i:i + n] in y:
                        best = x[i:i + n]
                        break
    return (best, bl) if best else (None, 0)


def hits(s, pats):
    t = norm(s)
    return sorted({p for p in pats if re.search(p, t)})


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return None if x <= 0 else x


def moat_idx(d, drop=None):
    """index.html の ccfMoat と同値（TOPCAP + cap96 + cultAdj）。drop で1本を空欄にできる。"""
    import math
    legs = []
    for k in W:
        if drop and k in drop:
            continue
        v = num(d.get(k))
        if v is None:
            continue
        if k in TOPCAP and v == 100:
            v = TOPCAP[k]
        legs.append((k, v))
    if len(legs) < 4:
        return None
    sw = sum(W[k] for k, _ in legs)
    gls = num(d.get("gls"))
    cult = -2 if (gls is not None and gls <= 3.3
                  and (d.get("disrupt") or "settled") != "threat"
                  and (d.get("erosion") or "none") != "active") else 0
    g = math.exp(sum(W[k] / sw * math.log(max(min(96, v), 1)) for k, v in legs))
    return max(0.0, min(96.0, g + cult))


def pillar_corr(packs):
    """★引用の共有とは**独立**の証拠——柱どうしの順位相関。
    規約が別のものを測っているはずの柱が強く相関するのは、重なりの疑いになる。
    ⚠ 相関は「同じ事実を数えている」の証明ではない（良い会社は全部の柱が高い）。
      ただし **moatW が他と +0.13〜0.18 しか相関しない**のが内部対照で、
      高い相関が単なる『良い会社の後光』では説明できないことを示す。"""
    import itertools, math
    def rank(v):
        s2 = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v); i = 0
        while i < len(s2):
            j = i
            while j + 1 < len(s2) and v[s2[j + 1]] == v[s2[i]]:
                j += 1
            for k in range(i, j + 1):
                r[s2[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    def rho(a, b):
        ra, rb = rank(a), rank(b); n = len(a)
        ma, mb = sum(ra) / n, sum(rb) / n
        num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        da = math.sqrt(sum((x - ma) ** 2 for x in ra))
        db = math.sqrt(sum((y - mb) ** 2 for y in rb))
        return num / (da * db) if da and db else 0.0
    vals = [{k: num(p.get(k)) for k in W} for p in packs]
    out = []
    for a, b in itertools.combinations(W, 2):
        xy = [(x[a], x[b]) for x in vals if x[a] is not None and x[b] is not None]
        if len(xy) < 30:
            continue
        out.append({"a": a, "b": b, "n": len(xy),
                    "rho": round(rho([x for x, _ in xy], [y for _, y in xy]), 3)})
    return sorted(out, key=lambda r: -r["rho"])


def load():
    rows = []
    for f in sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json"))):
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rows.append(p)
    return rows


PAIRS = [("dom", "irr"), ("irr", "dur"), ("dom", "dur"),
         ("dom", "rep"), ("irr", "rep"), ("rep", "dur")]


def analyse(p):
    m = p.get("_meta") or {}
    ev = m.get("evidence") or {}
    nu = m.get("nulls") or {}
    t = (p.get("nm") or "?").split(" ")[0]

    def text(k):
        # 空欄の理由にも根拠文が書かれることがある（domの再監査記録が典型）
        return str(ev.get(k) or "") + "\n" + str(nu.get(k) or "")

    val = {k: num(p.get(k)) for k in W}
    out = {"t": t, "nm": p.get("nm"), "val": val, "pairs": [], "flags": []}

    # (3) 規約の定義そのものの重なり——irr=100 は定義上 dom=100 の条件を満たす
    if val["irr"] == 100:
        out["flags"].append({
            "kind": "規約の定義の重なり",
            "why": "irr=100(唯一供給) は dom=100 の刻み『独占≥90%、**または実質唯一供給**』を"
                   "定義上そのまま満たす。dom が何であれ、同じ一つの事実が二つの欄の資格を作る",
            "weight": W["dom"] + W["irr"],
        })
    if val["dom"] == 100:
        out["flags"].append({
            "kind": "規約の定義の重なり(dom側)",
            "why": "dom=100 は『または実質唯一供給』でも取れるので、irr=100 と同じ事実で立ちうる",
            "weight": W["dom"] + W["irr"],
        })

    for a, b in PAIRS:
        ta, tb = text(a), text(b)
        if not ta.strip() or not tb.strip():
            continue
        q, ql = shared_quote(ta, tb)
        grp = {}
        for g, pats in GROUPS.items():
            ha, hb = hits(ta, pats), hits(tb, pats)
            both = sorted(set(ha) & set(hb))
            if both:
                grp[g] = both
        if q or grp:
            out["pairs"].append({
                "a": a, "b": b, "va": val[a], "vb": val[b],
                "weight": round(W[a] + W[b], 4),
                "shared_quote": q, "shared_quote_len": ql,
                "shared_groups": grp,
            })
    # 影の計測: 重なっている対の**軽いほう**を空欄へ落としたら堀はどうなるか（判定はしない）
    idx0 = moat_idx(p)
    out["moat"] = idx0
    worst = None
    for pr in out["pairs"]:
        if not pr["shared_quote"]:
            continue                     # 引用共有だけを影の計測の対象にする（機構語は弱い証拠）
        drop = pr["a"] if W[pr["a"]] <= W[pr["b"]] else pr["b"]
        i2 = moat_idx(p, drop={drop})
        if i2 is None:
            continue
        if worst is None or i2 < worst[1]:
            worst = (drop, i2)
    if worst:
        out["shadow_drop"] = {"drop": worst[0], "moat_after": round(worst[1], 2),
                              "delta": round(worst[1] - (idx0 or 0), 2)}
    return out


def main():
    show_all = "--all" in sys.argv
    as_json = "--json" in sys.argv
    only = None
    if "--t" in sys.argv:
        only = {x.strip().upper() for x in sys.argv[sys.argv.index("--t") + 1].split(",")}

    sc = {}
    p = os.path.join(OUT, "score_all.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        sc = {r["t"]: r for r in (d if isinstance(d, list) else d.get("rows", []))}

    res = []
    for pack in load():
        r = analyse(pack)
        if only and r["t"].upper() not in only:
            continue
        r["omega"] = (sc.get(r["t"]) or {}).get("s")
        r["buy"] = (sc.get(r["t"]) or {}).get("buy")
        res.append(r)

    hit = [r for r in res if r["pairs"] or r["flags"]]
    qshare = [r for r in res if any(x["shared_quote"] for x in r["pairs"])]
    defn = [r for r in res if r["flags"]]

    print("■ 堀の柱どうしの二重計上の目録（night/audit_moat_double_count.py）")
    print(f"  パック {len(res)}社 ／ 何らかの重なり {len(hit)}社")
    print(f"  ★引用が literally 共有されている社 {len(qshare)}社（最も強い証拠）")
    print(f"  ★規約の定義そのものが重なる社 {len(defn)}社（irr=100 または dom=100）")
    print()

    if qshare:
        print("── ★引用の共有（同じ一文が二つの欄の根拠になっている）──")
        for r in sorted(qshare, key=lambda x: -(x.get("omega") or 0)):
            for pr in r["pairs"]:
                if not pr["shared_quote"]:
                    continue
                mark = "🟢" if r.get("buy") else "  "
                print(f"  {mark}{r['t']:<7} Ω{(r.get('omega') or 0):>5.1f}  "
                      f"{pr['a']}={pr['va'] and int(pr['va'])} × {pr['b']}={pr['vb'] and int(pr['vb'])}"
                      f"  重み計 {pr['weight']:.2f}  共通 {pr['shared_quote_len']}字")
                print(f"        『{pr['shared_quote'][:150]}』")
            if r.get("shadow_drop"):
                s = r["shadow_drop"]
                print(f"        影の計測: {s['drop']} を空欄にすると 堀 {r['moat']:.1f}→{s['moat_after']}"
                      f"（{s['delta']:+.1f}）")
        print()

    if defn:
        print("── ★規約の定義の重なり（irr=100 / dom=100 は同じ『唯一供給』で立ちうる）──")
        for r in sorted(defn, key=lambda x: -(x.get("omega") or 0)):
            mark = "🟢" if r.get("buy") else "  "
            v = r["val"]
            print(f"  {mark}{r['t']:<7} Ω{(r.get('omega') or 0):>5.1f}  "
                  f"irr={v['irr'] and int(v['irr'])} dom={v['dom'] and int(v['dom'])} "
                  f"dur={v['dur'] and int(v['dur'])} rep={v['rep'] and int(v['rep'])} "
                  f"moatW={v['moatW'] and int(v['moatW'])}  堀 {r['moat'] and round(r['moat'],1)}")
        print()

    # ★2026-08-13 追加: 二重計上より大きい問題が出たので数える——
    #   **同じ型の事実（法で守られた排他的な事業権）が、社によって別の柱に置かれている**。
    #   規約はこの事実がどの柱に属すかを言っていないので、読み手ごとに置き場所が変わる。
    place = {}
    for pack in load():
        t = (pack.get("nm") or "?").split(" ")[0]
        if only and t.upper() not in only:
            continue
        ev = ((pack.get("_meta") or {}).get("evidence") or {})
        hit = [k for k in W if EXCL.search(str(ev.get(k) or ""))]
        if hit:
            place[t] = {"where": hit, "vals": {k: num(pack.get(k)) for k in W},
                        "omega": (sc.get(t) or {}).get("s"), "buy": bool((sc.get(t) or {}).get("buy"))}
    if place:
        cnt = {}
        for v in place.values():
            cnt["+".join(sorted(v["where"]))] = cnt.get("+".join(sorted(v["where"])), 0) + 1
        print(f"── ★『法で守られた排他的な事業権』を根拠に持つ社 {len(place)}社 — その事実が置かれた柱 ──")
        print("  ⚠ 規約はこの事実がどの柱に属すかを言っていない。**置き場所が読み手ごとに変わる**")
        for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
            print(f"     {k:<18} {v}社")
        both = [t for t, v in place.items() if len(v["where"]) >= 2]
        print(f"  ★**同じ社の中で二つ以上の柱に置かれている**（＝literal な二重計上）: "
              f"{len(both)}社  {' '.join(sorted(both)) or '—'}")
        print()

    corr = pillar_corr(load())
    print("── ★柱どうしの順位相関（引用の共有とは独立の証拠）──")
    print("  ⚠相関は二重計上の証明ではない。だが**moatW だけが他と弱くしか相関しない**のが内部対照で、")
    print("    高い相関が単なる『良い会社の後光』では説明できないことを示す")
    for c_ in corr:
        print(f"     {c_['a']:>6} × {c_['b']:<6} n={c_['n']:>3}  rho={c_['rho']:+.3f}  "
              + "#" * max(0, int(c_["rho"] * 40)))
    print()

    grponly = [r for r in res if r["pairs"] and not any(x["shared_quote"] for x in r["pairs"])]
    print(f"── 機構語だけが両方の欄に出る社 {len(grponly)}社 ──")
    print("  ⚠**弱い証拠**。同じ語でも別の事実を指しうるので、これだけで二重計上と断じない")
    if show_all:
        for r in sorted(grponly, key=lambda x: -(x.get("omega") or 0))[:60]:
            gs = sorted({g for pr in r["pairs"] for g in pr["shared_groups"]})
            ps = " ".join(f"{pr['a']}×{pr['b']}" for pr in r["pairs"])
            print(f"     {r['t']:<7} Ω{(r.get('omega') or 0):>5.1f}  {ps}  [{','.join(gs)}]")

    if as_json:
        out = {"tool": "audit_moat_double_count", "rev": "r3",
               "n_packs": len(res), "n_quote_shared": len(qshare), "n_definition": len(defn),
               "n_group_only": len(grponly), "exclusive_placement": place, "pillar_corr": corr, "rows": hit}
        with open(os.path.join(OUT, "moat_double_count.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("\n→ out/moat_double_count.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
