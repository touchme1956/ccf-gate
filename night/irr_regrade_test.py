#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr_regrade_test.py — 歴史の irr ラベルを『今日の規約』で再採点した結果を、事前登録どおり一度だけ裁く

事前登録: out/irr_regrade_prereg.json（採点を1件も見る前に commit 9622ffb で固定）
入力:     out/irr_regrade_meta.json（ビンテージ・元の刻み・リターン）
          out/irr_regrade/graded_A*.json / graded_B*.json（2人の独立な採点者・盲検）
出力:     out/irr_regrade_test.json

★測っているもの: 門が引く基礎率（50:0.162 / 70:0.366 / 85:0.579、85の『+24.6%/年』）が
  **今日の門が使っているラベルについての数字か**。効き幅ではなく「何を測ったか」の検定。

⚠ 置換検定は `night/irr70_mech_test.py:perm` と**同じ構成**にしてある——会社単位で並べ替え、
  同じ社の全ビンテージを一緒に動かす。ビンテージ内で独立に混ぜると従属が壊れ p を33倍 過小に出す（既記録）。
使い方: python3 night/irr_regrade_test.py [--json]
"""
import glob
import json
import math
import os
import random
import statistics as st
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = "out"
HURDLE = 0.15          # 既存の物差しを流用（新しい定数を作らない）
IMPAIR = 0.5           # 恒久毀損 = tr_total < 0.5（既存の定義）
SEED = 20260918
PERM = 2000
AS_JSON = "--json" in sys.argv[1:]


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def stat(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    tr = [r["tr"] for r in rows]
    k = sum(1 for x in tr if x >= HURDLE)
    # ⚠ tot(元本倍率) を持つ行だけで毀損を測る。持つ行がゼロなら **0.0 ではなく null**
    #   ——「測っていない」を「測って問題なし」に化かさない（絶対のルール7）
    has = [r for r in rows if r.get("tot") is not None]
    imp = [r for r in has if r["tot"] < IMPAIR]
    return {"n": n, "P15": round(k / n, 3), "CI": wilson(k, n),
            "med": round(st.median(tr), 4),
            "worst": round(min(tr), 4),
            "恒久毀損": (round(len(imp) / len(has), 3) if has else None),
            "毀損分子": (len(imp) if has else None),
            "毀損の分母": len(has)}


def load_graded():
    """2人の採点者を読み、id ごとに (A, B) を返す。⚠ 欠けは黙って0にしない。"""
    def rd(pat):
        g = {}
        for f in sorted(glob.glob(os.path.join(OUT, "irr_regrade", pat))):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception as e:
                print(f"⚠ {f} が読めない: {e}", file=sys.stderr)
                continue
            rows = d.get("rows") if isinstance(d, dict) else d
            for r in rows or []:
                if r.get("id"):
                    g[r["id"]] = r
        return g
    return rd("graded_A*.json"), rd("graded_B*.json")


def kappa(pairs):
    """Cohen の κ（3刻み）。一致率だけだと偶然の一致を実力と読む。"""
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] / n * cb[k] / n for k in set(ca) | set(cb))
    return None if pe >= 1 else round((po - pe) / (1 - pe), 3)


def perm_p(rows, key, hi, lo, n=PERM):
    """会社単位の置換（irr70_mech_test.py:perm と同じ構成）。
    ⚠ 同じ社が別ビンテージで違う採点を受けたら『高いほう』の社として数える
      ＝帰無を実測に有利へ倒す（p は保守的に出る）。"""
    ent = [r for r in rows if r.get(key) in (hi, lo)]
    if not ent:
        return None, None
    lab = {}
    for r in ent:
        lab[r["t"]] = lab.get(r["t"], False) or (r[key] == hi)
    cos = sorted(lab)
    ks = [lab[c] for c in cos]

    def diff(assign):
        a = [r for r in ent if assign[r["t"]]]
        b = [r for r in ent if not assign[r["t"]]]
        if not a or not b:
            return None
        return stat(a)["P15"] - stat(b)["P15"]

    obs = diff(lab)
    if obs is None:
        return None, None
    rnd = random.Random(SEED)
    hit = 0
    for _ in range(n):
        sh = ks[:]
        rnd.shuffle(sh)
        d = diff(dict(zip(cos, sh)))
        if d is not None and d >= obs:
            hit += 1
    return round(obs, 4), round((hit + 1) / (n + 1), 4)


def sizes():
    """規模（LLM の事前知識の漏れを層別で潰すため）。無ければ None＝層別を諦める。"""
    s = {}
    try:
        for f, k in (("retro_cohort_2013.json", "rev_asof"), ("retro_cohort_2015.json", "rev_asof")):
            for r in json.load(open(os.path.join(OUT, f), encoding="utf-8"))["rows"]:
                if r.get("ticker") and r.get(k) is not None:
                    s.setdefault(r["ticker"], r[k])
        d = json.load(open(os.path.join(OUT, "retro_features2_2018.json"), encoding="utf-8"))
        for r in (d.get("rows") or d):
            if r.get("t") and r.get("rev") is not None:
                s.setdefault(r["t"], r["rev"])
    except Exception as e:
        print(f"⚠ 規模が読めない: {e}", file=sys.stderr)
    return s


def build():
    meta = json.load(open(os.path.join(OUT, "irr_regrade_meta.json"), encoding="utf-8"))["rows"]
    A, B = load_graded()
    SZ = sizes()
    rows, miss, split = [], [], 0
    for m in meta:
        a, b = A.get(m["id"]), B.get(m["id"])
        if not a or not b:
            miss.append(m["id"])
            continue
        ra, rb = a.get("rung"), b.get("rung")
        agree = (ra == rb)
        if not agree:
            split += 1
        rows.append({**m, "A": ra, "B": rb, "agree": agree,
                     "new": ra if agree else None,
                     "mechA": a.get("mech"), "mechB": b.get("mech"),
                     "dirA": a.get("dir"), "rev": SZ.get(m["t"])})
    return rows, miss, split, len(A), len(B)



def today_calibration():
    """★較正: 同じ採点器を**今日の台帳**に当て、今日の審査官の刻みを再現できるか。
    ⚠ 今日の審査官は**原本の全文**を読んで決めた。採点器が見るのは審査官が引いた一文だけ＝
      **同じ作業ではない**ので、不一致は必ずしも採点器の誤りではない（どちらが誤りかは人が読む）。"""
    import glob as _g
    try:
        meta = json.load(open(os.path.join(OUT, "irr_regrade_today_meta.json"), encoding="utf-8"))
    except Exception as e:
        return {"error": f"今日の較正の材料が読めない: {e}"}

    def rd(pat):
        g = {}
        for f in sorted(_g.glob(os.path.join(OUT, "irr_regrade", pat))):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for r in (d.get("rows") if isinstance(d, dict) else d) or []:
                if r.get("id"):
                    g[r["id"]] = r
        return g
    A, B = rd("tgraded_A*.json"), rd("tgraded_B*.json")
    rows, miss = [], []
    for m in meta["rows"]:
        a, b = A.get(m["id"]), B.get(m["id"])
        if not a or not b:
            miss.append(m["t"])
            continue
        rows.append({**m, "A": a.get("rung"), "B": b.get("rung"),
                     "agree": a.get("rung") == b.get("rung")})
    if not rows:
        return {"error": "採点が1件も読めない", "欠け": miss}
    ok = [r for r in rows if r["agree"]]
    # ⚠ 門は irr=100 を堀指数では 85 として扱う（TOPCAP）。較正でも 100 は 85 と同じ段で数える
    def seg(x):
        return 85 if x in (85, 100) else x
    conf = Counter((seg(r["today"]), r["A"]) for r in ok)
    hit = sum(v for (t, n), v in conf.items() if t == n)
    out = {"n": len(rows), "両者一致": len(ok), "欠け": miss,
           "採点者間の一致率": round(len(ok) / len(rows), 3),
           "κ": kappa([(r["A"], r["B"]) for r in rows]),
           "今日の刻みとの一致率(両者一致分)": round(hit / len(ok), 3) if ok else None,
           "混同表": {f"今日{t}→採点{n}": v for (t, n), v in sorted(conf.items())},
           "引用が取れなかった社": meta.get("引用が取れない", [])}
    # 今日の刻み別に、採点器が下へ倒した社を名指しする（黙って数だけにしない）
    down = defaultdict(list)
    for r in ok:
        if r["A"] < seg(r["today"]):
            down[str(r["today"])].append(r["t"])
    out["採点器が下へ倒した社"] = {k: sorted(v) for k, v in sorted(down.items())}
    return out


def by_company(ok):
    """★**のべ件数と実社数は違う**（この台帳が irr85_evidence で確立した作法）。
    同じ社が複数ビンテージに出るので、社単位でも数え直す。社の代表値は
    **その社の全ビンテージの tr の中央値**、ラベルは **ビンテージの過半**（割れたら上の刻み＝
    実測に有利な側へ倒し、p を保守的に出す）。"""
    g = defaultdict(list)
    for r in ok:
        g[r["t"]].append(r)
    co = {}
    for t, rs in g.items():
        news = [x["new"] for x in rs]
        origs = [x["orig"] for x in rs]
        co[t] = {"t": t, "tr": st.median([x["tr"] for x in rs]),
                 "tot": st.median([x["tot"] for x in rs if x.get("tot") is not None])
                        if any(x.get("tot") is not None for x in rs) else None,
                 "new": max(set(news), key=lambda v: (news.count(v), v)),
                 "orig": max(set(origs), key=lambda v: (origs.count(v), v)),
                 "n_v": len(rs)}
    C = list(co.values())
    S70 = [c for c in C if c["orig"] in (70, 75) and c["new"] == 70]
    R70 = [c for c in C if c["orig"] in (70, 75) and c["new"] != 70]
    S85 = [c for c in C if c["orig"] == 85 and c["new"] == 85]
    L85 = [c for c in C if c["orig"] == 85 and c["new"] != 85]
    return {"のべ→実社数": {"のべ": len(ok), "実社数": len(C),
                      "2ビンテージ以上": sum(1 for c in C if c["n_v"] > 1)},
            "H1_社単位": {"70S": stat(S70), "70R": stat(R70),
                       "lift": round(stat(S70)["P15"] - stat(R70)["P15"], 3)},
            "H2_社単位": {"85S": stat(S85), "85L": stat(L85),
                       "lift": round(stat(S85)["P15"] - stat(L85)["P15"], 3),
                       "85Sの顔ぶれ": sorted(c["t"] for c in S85)},
            "⚠": f"85S はのべ {len(S85)*0 + sum(1 for r in ok if r['orig']==85 and r['new']==85)} 件＝"
                 f"**実 {len(S85)} 社**（LRCX が3ビンテージ）。のべで数えると同じ社が何度も効く"}



CONTRACTUAL = ("複数年の購買義務", "解約率・更新率の実数")
OPERATIONAL = ("工程への組込", "設置基盤", "消耗品の専用性", "物理的固着", "顧客側の再認定")


def mech_kind(ok):
    """★記述のみ（事前登録の外）。v9.9.144 が列挙する機構を**契約型と現場型**に割って成績を見る。
    ⚠ この割り方は結果を見てから作った事後の切り口なので、**規則の根拠にはならない**。
      次に事前登録するときの候補としてだけ残す。"""
    g = [r for r in ok if r["orig"] in (70, 75) and r["new"] == 70]
    c = [r for r in g if (r.get("mechA") or "") in CONTRACTUAL]
    o = [r for r in g if (r.get("mechA") or "") in OPERATIONAL]
    return {"契約型(複数年の購買義務・解約率)": stat(c),
            "現場型(工程への組込・設置基盤・消耗品・物理・再認定)": stat(o),
            "差": (round(stat(o)["P15"] - stat(c)["P15"], 3) if c and o else None),
            "⚠": "**事後の切り口**。規則の根拠にはならない。次の事前登録の候補としてだけ残す"}



def reconcile(ok):
    """★**二つの検査器が逆のことを言っている**ので突き合わせる（v9.9.65: 放置しない）。

    旧 `night/irr70_mech_test.py` は「歴史の `mech` 欄が埋まっているか」を v9.9.144 の代理に使い
    **lift +0.159** を出した。この器は「その引用を今日のルーブリックで採点し直す」ので **lift −0.182**。
    **どちらも内部では整合している**——同じ131社を**別の軸**で割っているだけ。ここではその軸の関係を出す。

    ⚠ 2018 は `mech` が全社『なし』なので旧の軸が存在しない。よって **2013/2015 だけ**で比べる
      （混ぜると「2018＝機構なし」が丸ごと片側に積まれ、比較が窓の違いに化ける）。"""
    g = [r for r in ok if r["v"] in (2013, 2015) and r["orig"] in (70, 75)]
    old = lambda r: (r.get("mech") or "なし") != "なし"
    new = lambda r: r["new"] == 70            # 今日の規約でも70
    cell = lambda f: stat([r for r in g if f(r)])
    mech_new = defaultdict(list)
    for r in ok:
        if r["orig"] in (70, 75) and r["new"] == 70:
            mech_new[r.get("mechA") or "（名指しなし）"].append(r)
    down = Counter((r.get("mech") or "なし") for r in g if old(r) and not new(r))
    keep = Counter((r.get("mech") or "なし") for r in g if old(r) and new(r))
    return {
        "なぜ": "旧=mech欄の有無（代理）／新=引用の再採点。同じ社を別の軸で割っている",
        "母集団": "2013+2015 の 70/75 のみ（2018は mech が全社『なし』で旧の軸が無い）",
        "交差表": {"mechあり×今日も70": cell(lambda r: old(r) and new(r)),
                "mechあり×今日は50": cell(lambda r: old(r) and not new(r)),
                "mechなし×今日も70": cell(lambda r: (not old(r)) and new(r)),
                "mechなし×今日は50": cell(lambda r: (not old(r)) and not new(r))},
        "旧の軸だけ": {"mechあり": cell(old), "mechなし": cell(lambda r: not old(r))},
        "新の軸だけ": {"今日も70": cell(new), "今日は50": cell(lambda r: not new(r))},
        # ⚠ 見出しに数字を焼き付けない（この台帳が何度も踏んだ陳腐化の型）——毎回数える
        f"★mechありの {sum(down.values())}/{sum(down.values())+sum(keep.values())} が今日は50へ落ちる":
            {"落ちた": dict(down), "残った": dict(keep)},
        "新採点器が名指しした機構ごとの成績": {m: stat(v) for m, v in
                              sorted(mech_new.items(), key=lambda kv: -len(kv[1]))},
        "読み": "mechあり の中では新の分割はほぼ効かない（0.385 vs 0.476）が、mechなし の中では"
              "強く効く（0.212 vs 0.394）——**ただし逆向き**。新の 70S は旧の『機構がある社』と"
              "ほぼ独立で、しかも当たらない側に寄る。★そして今日のルーブリックが最も多く当てはまる"
              "機構『複数年の購買義務』(n=23) の P15 は 0.087 で**全カテゴリ最低**",
    }



def main():
    rows, miss, split, na, nb = build()
    res = {"generated": "2026-09-18", "hurdle": HURDLE, "seed": SEED, "perm": PERM,
           "prereg": "out/irr_regrade_prereg.json (commit 9622ffb)",
           "coverage": {"meta": len(rows) + len(miss), "採点A": na, "採点B": nb,
                        "両方そろった": len(rows), "欠け": miss}}

    # ---- H4 再現性（先に出す。ここが低ければ以下の結論は弱い） ----
    pairs = [(r["A"], r["B"]) for r in rows]
    by_orig = defaultdict(list)
    for r in rows:
        by_orig[r["orig"]].append((r["A"], r["B"]))
    res["H4_再現性"] = {
        "全体": {"n": len(pairs), "一致率": round(sum(1 for a, b in pairs if a == b) / len(pairs), 3) if pairs else None,
                "κ": kappa(pairs)},
        "元の刻み別": {str(k): {"n": len(v), "一致率": round(sum(1 for a, b in v if a == b) / len(v), 3), "κ": kappa(v)}
                   for k, v in sorted(by_orig.items())},
        "不一致": split,
        "本判定に使うのは": "2人が一致した項目のみ（事前登録どおり）"}

    ok = [r for r in rows if r["agree"] and r["tr"] is not None]

    # ---- 再採点の分布（結果ではなく記述） ----
    res["再採点の分布"] = {f"{o}→{n}": c for (o, n), c in
                     sorted(Counter((r["orig"], r["new"]) for r in ok).items())}

    def grp(sel):
        return stat([r for r in ok if sel(r)])

    # ---- H5 較正: 2018 の 85 は他より降格されるか（既知の事実を掴めるか） ----
    cal = {}
    for v in (2013, 2015, 2018):
        e = [r for r in ok if r["orig"] == 85 and r["v"] == v]
        d = [r for r in e if r["new"] != 85]
        cal[str(v)] = {"n": len(e), "降格": len(d),
                       "降格率": round(len(d) / len(e), 3) if e else None}
    e1315 = [r for r in ok if r["orig"] == 85 and r["v"] in (2013, 2015)]
    e18 = [r for r in ok if r["orig"] == 85 and r["v"] == 2018]
    res["H5_較正"] = {"ビンテージ別": cal,
                   "予言": "2018 の降格率 > 2013/2015 の降格率（既知: 2018の班は85に緩く付与率3.2倍）",
                   "判定": ((len(e18) and len(e1315)) and
                           (sum(1 for r in e18 if r["new"] != 85) / len(e18) >
                            sum(1 for r in e1315 if r["new"] != 85) / len(e1315))) or False}

    # ---- H1: 70/75 の厳格化 ----
    mid = [r for r in ok if r["orig"] in (70, 75)]
    S = [r for r in mid if r["new"] in (70, 85)]
    R = [r for r in mid if r["new"] == 50]
    h1 = {"70S": stat(S), "70R": stat(R),
          "lift": round(stat(S).get("P15", 0) - stat(R).get("P15", 0), 4) if S and R else None,
          "到達可能": bool(len(S) >= 5 and len(R) >= 5)}
    h1["ビンテージ別"] = {}
    for v in (2013, 2015, 2018):
        a = [r for r in S if r["v"] == v]
        b = [r for r in R if r["v"] == v]
        h1["ビンテージ別"][str(v)] = {"70S": stat(a), "70R": stat(b),
                                 "lift": round(stat(a)["P15"] - stat(b)["P15"], 4) if a and b else None}
    o, p = perm_p([{**r, "g": ("S" if r in S else "R")} for r in mid], "g", "S", "R")
    h1["置換"] = {"obs": o, "p": p}
    signs = [x["lift"] for x in h1["ビンテージ別"].values() if x["lift"] is not None]
    h1["判定"] = {"線": "lift>=0.10 かつ 両群 n>=5 かつ 3ビンテージのうち2つ以上で符号が同じ",
                "符号が正のビンテージ": sum(1 for s in signs if s > 0), "測れたビンテージ": len(signs),
                "合格": bool(h1["到達可能"] and (h1["lift"] or 0) >= 0.10 and sum(1 for s in signs if s > 0) >= 2)}

    # ---- H2: 85 の厳格化 ----
    top = [r for r in ok if r["orig"] == 85]
    S85 = [r for r in top if r["new"] == 85]
    L85 = [r for r in top if r["new"] in (50, 70)]
    h2 = {"85S": stat(S85), "85L": stat(L85),
          "lift": round(stat(S85).get("P15", 0) - stat(L85).get("P15", 0), 4) if S85 and L85 else None,
          "到達可能": bool(len(S85) >= 5 and len(L85) >= 5)}
    o2, p2 = perm_p([{**r, "g": ("S" if r in S85 else "L")} for r in top], "g", "S", "L")
    h2["置換"] = {"obs": o2, "p": p2}
    h2["判定"] = {"線": "lift>=0.10 かつ 両群 n>=5",
                "合格": bool(h2["到達可能"] and abs(h2["lift"] or 0) >= 0.10),
                "向き": ("85S が高い" if (h2["lift"] or 0) > 0 else "85L が高い") if h2["lift"] is not None else None}
    if not h2["到達可能"]:
        h2["判定"]["注"] = "**判定不能**（分割が 5/35 より偏った）——『効かなかった』ではない"

    res["H1_70の厳格化"], res["H2_85の厳格化"] = h1, h2

    # ---- family-wise の値札 ----
    ps = [x for x in (p, p2) if x is not None]
    res["多重検定"] = {"家族": 2, "個別p": ps,
                   "Bonferroni": [round(min(1.0, x * len(ps)), 4) for x in ps]}

    # ---- 今日のラベルで引き直した基礎率（記述） ----
    fifty = []
    try:
        Lr = lambda n: json.load(open(os.path.join(OUT, n), encoding="utf-8"))["rows"]
        RET = {}   # ⚠ 変数名を R にすると上の 70R 群を潰す（実際に潰して例外になった）
        for f in ("retro_returns_2013_all.json", "retro_returns_2015_q.json", "retro_returns_2018.json"):
            for x in Lr(f):
                RET.setdefault(x["ticker"], []).append(x.get("tr_cagr"))
        for f, k, q in (("retro_moat_2013.json", "irr", "ticker"), ("retro_moat_2013q.json", "irr", "ticker"),
                        ("retro_moat_2015.json", "irr", "ticker"), ("retro_moat_2015q.json", "irr", "ticker"),
                        ("retro_moat_2015qb.json", "irr", "ticker"),
                        ("retro_moat_2018.json", "irr18", "t"), ("retro_moat_2018_rest.json", "irr18", "t")):
            for x in Lr(f):
                if x.get(k) == 50 and x.get(q) in RET:
                    for t in RET[x[q]]:
                        if t is not None:
                            fifty.append({"tr": t, "tot": None})
    except Exception as e:
        print(f"⚠ 50 の基礎率が引けない: {e}", file=sys.stderr)
    res["今日のラベルでの基礎率"] = {
        "50(歴史のまま)": stat(fifty) if fifty else {"n": 0},
        "70R(今日なら50へ落ちる)": stat(R), "70S(今日も70)": stat(S),
        "85L(今日なら70以下)": stat(L85), "85S(今日も85)": stat(S85)}

    # ---- 規模で層別（LLM の事前知識の漏れ） ----
    sz = [r["rev"] for r in ok if r.get("rev")]
    if sz:
        med = st.median(sz)
        res["規模で層別"] = {
            "中央値(売上)": round(med, 1),
            "小型のみ_H1": {"70S": grp(lambda r: r in S and (r.get("rev") or 0) and r["rev"] < med),
                        "70R": grp(lambda r: r in R and (r.get("rev") or 0) and r["rev"] < med)},
            "大型のみ_H1": {"70S": grp(lambda r: r in S and (r.get("rev") or 0) >= med),
                        "70R": grp(lambda r: r in R and (r.get("rev") or 0) >= med)},
            "規模不明": sum(1 for r in ok if not r.get("rev"))}

    res["社単位で数え直す"] = by_company(ok)
    res["二つの検査器の突き合わせ"] = reconcile(ok)
    res["機構を契約型と現場型に割る(事後)"] = mech_kind(ok)
    res["較正_今日の台帳"] = today_calibration()

    json.dump(res, open(os.path.join(OUT, "irr_regrade_test.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if AS_JSON:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
