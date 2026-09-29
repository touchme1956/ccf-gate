#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/rf_replicate.py — Bloomberg Reformers Index（＝Smart-i Pro 米国リブート75 の対象指数）の再現・段2〜4

事前登録: out/reformers_prereg.json（コミット a595eee2・規則・変種・対照・窓・合否の線はそちら。ここは実装）
入力: out/_rf_facts.json.gz（night/rf_facts.py）・out/_rf_prices.json.gz（night/rf_prices.py）

段A  各選定日 S で、資格を満たす社ごとに『S までに分かっていた情報だけ』の LTM 純利益・営業利益率・純利益率を作る
段B  変種ごとに Path1/Path2/ウォッチリストの記憶を持ち回し、純利益率の上位75を選ぶ（6%上限つきの時価加重）
段C  月次の買い持ちで成績を出す（採用は月m+2から3か月。価格なし社・途切れた社の扱いは事前登録どおり）
段D  円換算・超過・半分・提供元の窓・1社抜き・下限版・費用・較正の検査

使い方:
  python3 night/rf_replicate.py --stage select --dates 2016-06-30     # 数日だけ選定を確かめる（成績は出さない）
  python3 night/rf_replicate.py                                        # 全段 → out/reformers.json
純関数（trend_score・quarters・ltm_map・cap_weights）は night/rf_test.py が単体検算する。
"""
import argparse
import bisect
import datetime
import gzip
import json
import math
import os
import sys
import time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
sys.path.insert(0, os.path.join(BASE, "night"))

W = (1.5, 1.5, 1.0, 0.5, 0.5)
MCAP_MIN = 5e8
ADV_MIN = 5e6
COVER_MCAP = 1e9            # V1b: 予想の寄稿者3人以上の代理
TOPN = 75
CAP = 0.06
FRESH_DAYS = 200            # T が S より何日以上前なら『もう提出していない』
FEE = 0.005                 # 年（仮置き・事前登録）
TRADE_COST = 0.001          # 片側
COUNT_FROM = 201211         # 数える最初の月（選定日 2012-09-30 以降の構成）
LB_HIT = -0.30
FIRST_S = "2010-09-30"
LAST_S = "2026-06-30"       # この構成は 2026-08 に1か月だけ効く


def o(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10])).toordinal()


def ym_add(k, n):
    y, m = divmod(k // 100 * 12 + k % 100 - 1 + n, 12)
    return y * 100 + m + 1


def sel_dates(first=FIRST_S, last=LAST_S):
    out = []
    for y in range(int(first[:4]), int(last[:4]) + 1):
        for m in (3, 6, 9, 12):
            d = datetime.date(y + (m == 12 and 0), m, 1)
            nxt = datetime.date(y + (m == 12), (m % 12) + 1, 1)
            e = (nxt - datetime.timedelta(days=1)).isoformat()
            if first <= e <= last:
                out.append(e)
    return out


# ───────────────────────── 純関数（単体検算の対象） ─────────────────────────
def trend_score(P):
    """P=[P1..P6]（P1=T+2 … P6=T-3・欠測は None）。R_t=P_t−P_(t+1)>0 なら 重み W_t。欠測の絡む R は 0 点"""
    s = 0.0
    for t in range(5):
        a, b = P[t], P[t + 1]
        if a is not None and b is not None and a - b > 0:
            s += W[t]
    return s


def forward_extrap(P3, P4):
    """V1: 予想＝直近の四半期の変化がもう2四半期続く → (P1, P2)。どちらかが欠測なら (None, None)"""
    if P3 is None or P4 is None:
        return None, None
    d = P3 - P4
    return P3 + 2 * d, P3 + d


def cap_weights(base, cap=CAP):
    """base={名前: 正の値} → 上限 cap を反復して適用した重み（超過分は残りへ比例）。名前が 1/cap 未満なら等分"""
    names = list(base)
    n = len(names)
    if n == 0:
        return {}
    if n * cap <= 1.0:
        return {k: 1.0 / n for k in names}
    w = {k: base[k] / sum(base.values()) for k in names}
    fixed = {}
    for _ in range(200):
        over = [k for k in w if k not in fixed and w[k] > cap + 1e-12]
        if not over:
            break
        for k in over:
            fixed[k] = cap
        rest = [k for k in names if k not in fixed]
        rem = 1.0 - cap * len(fixed)
        tot = sum(base[k] for k in rest)
        w = {k: (fixed[k] if k in fixed else rem * base[k] / tot) for k in names}
    return w


def quarters(rows, S_o):
    """rows=[(start_o, end_o, dur, filed_os[], vals[])]・S_o までに提出された値だけで 四半期（3か月）の値 {end_o: 値}。
    直接の3か月の事実を優先、無ければ 同じ開始日の累計の差（間隔 75〜110日）"""
    groups = defaultdict(list)
    for s, e, dur, fo, vv in rows:
        i = bisect.bisect_right(fo, S_o) - 1
        if i >= 0:
            groups[s].append((e, vv[i], dur))
    disc = {}
    for lst in groups.values():
        for e, v, d in lst:
            if d <= 100:
                disc[e] = v
    for lst in groups.values():
        lst.sort()
        for j in range(1, len(lst)):
            e, v, d = lst[j]
            if d <= 100 or e in disc:
                continue
            pe, pv, _pd = lst[j - 1]
            if 75 <= e - pe <= 110:
                disc[e] = v - pv
    return disc


def ltm_map(disc):
    """{end_o: LTM}（連続する4四半期の和・間隔 75〜110日）と 昇順の end 一覧"""
    ends = sorted(disc)
    out = {}
    for i in range(3, len(ends)):
        if all(75 <= ends[k + 1] - ends[k] <= 110 for k in range(i - 3, i)):
            out[ends[i]] = sum(disc[ends[k]] for k in range(i - 3, i + 1))
    return ends, out


def chain_ends(ends, i, n):
    """ends[i] から n 個さかのぼった連続の end（途切れたらそこから先は None）"""
    out = [ends[i]]
    for k in range(1, n):
        j = i - k
        if j < 0 or not (75 <= ends[j + 1] - ends[j] <= 110):
            out += [None] * (n - k)
            break
        out.append(ends[j])
    return out


# ───────────────────────── データ ─────────────────────────
class Firm:
    __slots__ = ("cik", "name", "rows", "sh", "bs", "wa", "pf", "last_o", "fut")

    def __init__(self, cik, f):
        self.cik = cik
        self.name = f.get("name")
        self.rows = {}
        for k in ("ni", "oi", "rev"):
            rr = []
            for s, e, seq in f[k]:
                so, eo = o(s), o(e)
                rr.append((so, eo, eo - so, [o(x[0]) for x in seq], [x[1] for x in seq]))
            self.rows[k] = rr
        for k in ("sh", "bs", "wa", "pf"):
            lst = f.get(k) or []
            setattr(self, k, ([o(x[0]) for x in lst], [x[2] for x in lst], [o(x[1]) for x in lst]))
        self.last_o = o(f["last_filed"])
        self.fut = None


def pit_val(tri, S_o):
    fo, vals, ends = tri
    i = bisect.bisect_right(fo, S_o) - 1
    return (vals[i], ends[i]) if i >= 0 else (None, None)


def load_all():
    t0 = time.time()
    F = json.load(gzip.open(os.path.join(OUT, "_rf_facts.json.gz"), "rt"))["firms"]
    firms = {c: Firm(c, f) for c, f in F.items()}
    P = json.load(gzip.open(os.path.join(OUT, "_rf_prices.json.gz"), "rt"))
    px = {}
    for c, v in P["firms"].items():
        bars = {int(k): x for k, x in v["bars"].items()}
        sp = [(o(d), r) for d, r in v["splits"]]
        px[c] = {"t": v["t"], "bars": bars, "splits": sp, "last": max(bars) if bars else 0}
    bench = {n: {int(k): x for k, x in d.items()} for n, d in P["bench"].items()}
    print(f"   読込 {len(firms)}社・価格 {len(px)}社 {time.time() - t0:.0f}s", flush=True)
    return firms, px, bench, P


def split_after(px, S_o):
    f = 1.0
    for d, r in px["splits"]:
        if d > S_o:
            f *= r
    return f


def shares_at(firm, S_o, price, pf_val):
    """株数（表紙→貸借対照表→基本加重平均・浮動株時価との比で桁の誤りを避ける）。戻り (株数, 出所) か (None, 理由)"""
    cands = []
    for k in ("sh", "bs", "wa"):
        v, e = pit_val(getattr(firm, k), S_o)
        if v and v > 0 and e is not None and S_o - e <= 500:
            cands.append((k, v))
    if not cands:
        return None, "株数なし"
    if pf_val and price:
        for k, v in cands:
            r = v * price / pf_val
            if 0.25 <= r <= 12:
                return v, k
        return None, "株数が浮動株時価と合わない"
    return cands[0][1], cands[0][0]


def adv_at(px, Sym):
    vals = []
    for m in (Sym, ym_add(Sym, -1), ym_add(Sym, -2)):
        b = px["bars"].get(m)
        if b and b[2] is not None and b[2] > 0:
            vals.append(b[2] / 21.0 * b[1])
    return sum(vals) / len(vals) if len(vals) >= 2 else None


def fut_ltm(firm):
    """V2 の後知恵: 全提出を使った LTM の辞書（ni/oi/rev）と end 一覧"""
    if firm.fut is None:
        FUT = o("2099-12-31")
        d = {}
        for k in ("ni", "oi", "rev"):
            disc = quarters(firm.rows[k], FUT)
            ends, ltm = ltm_map(disc)
            d[k] = (ends, ltm)
        firm.fut = d
    return firm.fut


def stage_a(firms, px, bench, tick_ciks, dates, verbose=True):
    """各選定日 → {cik: 記録}（資格を満たす社だけ）と 診断"""
    out, diag = {}, {}
    for S in dates:
        t0 = time.time()
        S_o = o(S)
        Sym = int(S[:4]) * 100 + int(S[5:7])
        cand = {}
        dg = defaultdict(int)
        for cik, fm in firms.items():
            p = px.get(cik)
            pf_val, _pe = pit_val(fm.pf, S_o)
            if p is not None:
                b = p["bars"].get(Sym)
                if not b:
                    dg["価格なし(その月)"] += 1
                    continue
                price = b[1] * split_after(p, S_o)
                sh, why = shares_at(fm, S_o, price, pf_val)
                if sh is None:
                    dg[why] += 1
                    continue
                mcap = sh * price
                if mcap < MCAP_MIN:
                    continue
                adv = adv_at(p, Sym)
                if adv is None or adv < ADV_MIN:
                    dg["売買代金不足/欠測"] += 1
                    continue
                base_w, priced = mcap, True
            else:
                if int(cik) in tick_ciks:
                    continue                       # 今日の記号があるのに価格が取れない社（非株式・取得失敗）は入れない
                if pf_val is None or pf_val < MCAP_MIN:
                    continue
                base_w, mcap, priced = pf_val, pf_val, False
            # LTM（S までに分かっていた値）
            disc_ni = quarters(fm.rows["ni"], S_o)
            if not disc_ni:
                continue
            ends, ltm_ni = ltm_map(disc_ni)
            eT = ends[-1]
            if S_o - eT > FRESH_DAYS or eT > S_o:
                dg["Tが古い(提出停止)"] += 1
                continue
            iT = len(ends) - 1
            ce = chain_ends(ends, iT, 4)
            ni_P = [ltm_ni.get(e) if e is not None else None for e in ce]
            ends_oi, ltm_oi = ltm_map(quarters(fm.rows["oi"], S_o))
            ends_rv, ltm_rv = ltm_map(quarters(fm.rows["rev"], S_o))
            om_P = []
            for e in ce:
                a, r = (ltm_oi.get(e), ltm_rv.get(e)) if e is not None else (None, None)
                om_P.append(a / r if (a is not None and r is not None and r > 0) else None)
            ni_T = ni_P[0]
            rvT = ltm_rv.get(eT)
            margin = ni_T / rvT if (ni_T is not None and rvT is not None and rvT > 0) else None
            # 過去8評価期間の赤字（C1）: 直近8個の LTM 純利益のどこかが負
            neg8 = False
            for j in range(0, 8):
                ii = iT - j
                if ii < 3:
                    break
                v = ltm_ni.get(ends[ii])
                if v is not None and v < 0:
                    neg8 = True
                    break
            # V2 の後知恵: T の次の2四半期の LTM（純利益・営業利益率）
            fut_ni = fut_om = None
            fu = fut_ltm(fm)
            fe_ni, fl_ni = fu["ni"]
            if eT in fl_ni or eT in fe_ni:
                try:
                    j = fe_ni.index(eT)
                except ValueError:
                    j = None
                if j is not None and j + 2 < len(fe_ni) and 75 <= fe_ni[j + 1] - fe_ni[j] <= 110 and 75 <= fe_ni[j + 2] - fe_ni[j + 1] <= 110:
                    e1, e2 = fe_ni[j + 1], fe_ni[j + 2]
                    n1, n2 = fl_ni.get(e1), fl_ni.get(e2)
                    if n1 is not None and n2 is not None:
                        fut_ni = (n2, n1)            # (P1, P2)
                    fl_oi, fl_rv = fu["oi"][1], fu["rev"][1]
                    def om_at(e):
                        a, r = fl_oi.get(e), fl_rv.get(e)
                        return a / r if (a is not None and r is not None and r > 0) else None
                    m1, m2 = om_at(e1), om_at(e2)
                    if m1 is not None and m2 is not None:
                        fut_om = (m2, m1)
            cand[cik] = {"priced": priced, "mcap": mcap, "w": base_w, "ni_P": ni_P, "om_P": om_P, "ni_T": ni_T,
                         "margin": margin, "neg8": neg8, "fut_ni": fut_ni, "fut_om": fut_om, "T": eT,
                         "last_o": fm.last_o}
            dg["資格あり"] += 1
            dg["資格あり・価格つき" if priced else "資格あり・価格なし"] += 1
        out[S] = cand
        diag[S] = dict(dg)
        if verbose:
            print(f"   段A {S}: 資格 {dg['資格あり']}（価格つき {dg['資格あり・価格つき']}／価格なし {dg['資格あり・価格なし']}） {time.time() - t0:.1f}s", flush=True)
    return out, diag


# ───────────────────────── 段B: 選定 ─────────────────────────
def scores(c, variant):
    """(純利益スコア, 営業利益率スコア)"""
    ni3, ni4 = c["ni_P"][0], c["ni_P"][1]
    om3, om4 = c["om_P"][0], c["om_P"][1]
    if variant in ("V1", "V1b"):
        if variant == "V1b" and c["mcap"] < COVER_MCAP:
            f_ni = f_om = (None, None)
        else:
            f_ni = forward_extrap(ni3, ni4)
            f_om = forward_extrap(om3, om4)
    elif variant == "V2":
        f_ni = c["fut_ni"] or (None, None)
        f_om = c["fut_om"] or (None, None)
    else:
        raise ValueError(variant)
    Pn = [f_ni[0], f_ni[1]] + list(c["ni_P"])
    Po = [f_om[0], f_om[1]] + list(c["om_P"])
    return trend_score(Pn), trend_score(Po)


def select_variant(cands, dates, variant, topn=TOPN):
    """→ [{'S':…, 'names':{cik: 基礎の重み}, 'wl':n, 'p1':n, 'p2':n}]（時価加重・6%上限は重みの段で）"""
    mem, prev_wl, res = {}, set(), []
    for k, S in enumerate(dates):
        cand = cands[S]
        wl, p1s, p2s = set(), set(), set()
        if variant == "C1":
            for cik, c in cand.items():
                if c["margin"] is None or c["ni_T"] is None:
                    continue
                if c["ni_T"] < 0 or c["neg8"]:
                    wl.add(cik)
        elif variant in ("C0", "C0EW"):
            wl = set(cand)
        else:
            for cik, c in cand.items():
                if c["ni_T"] is None or c["margin"] is None:
                    continue
                nis, oms = scores(c, variant)
                is_p1 = nis >= 3.0 and oms >= 3.0 and c["ni_T"] < 0
                last = mem.get(cik)
                is_p2 = (last is not None and k - last <= 8 and cik in prev_wl and nis >= 4.0 and oms >= 4.0)
                if is_p1:
                    p1s.add(cik)
                if is_p2 and not is_p1:
                    p2s.add(cik)
                if is_p1 or is_p2:
                    wl.add(cik)
            for cik in p1s:
                mem[cik] = k
            prev_wl = wl
        if variant in ("C0", "C0EW"):
            ranked = sorted(wl)
        else:
            ranked = sorted(wl, key=lambda x: -cand[x]["margin"])[:topn]
        res.append({"S": S, "names": {cik: cand[cik]["w"] for cik in ranked}, "wl": len(wl), "p1": len(p1s), "p2": len(p2s),
                    "sel": ranked})
    return res


# ───────────────────────── 段C: 月次の買い持ち ─────────────────────────
def ym_of_ord(x):
    d = datetime.date.fromordinal(x)
    return d.year * 100 + d.month


def simulate(sel, cands, px, dates, c0ret=None, mode="base", early=False, weighting="cap", exclude=None,
             fee=0.0, cost=0.0, count_from=0, priced_only=False, capped=True):
    """月次の買い持ち。→ (月次リターン {ym: r}, 寄与 {cik: 累計}, 診断)。mode: base｜lb（事前登録の delisting_and_unpriced_treatment）
    採用: 選定日 S が月 m の末なら 月 m+2 の月初から3か月（early なら m+1 から）。開始時の重み＝S の重み×（S→開始の価格変化）"""
    rets, contrib, turn_log = {}, defaultdict(float), []
    prev_w = {}
    unp_w, unp_n = [], []
    for item in sel:
        S = item["S"]
        Sym = int(S[:4]) * 100 + int(S[5:7])
        cand = cands[S]
        names = {c: w for c, w in item["names"].items() if not (exclude and c in exclude)}
        if priced_only:
            names = {c: w for c, w in names.items() if cand[c]["priced"]}
        if not names:
            continue
        if weighting == "ew":
            w0 = {c: 1.0 / len(names) for c in names}
        elif capped:
            w0 = cap_weights(names)
        else:
            tot0 = sum(names.values())
            w0 = {c: w / tot0 for c, w in names.items()}
        start = ym_add(Sym, 1 if early else 2)
        months = [ym_add(start, i) for i in range(3)]
        wt, kind, st = {}, {}, {}
        for c, w in w0.items():
            if cand[c]["priced"]:
                if early:
                    g = 1.0
                else:
                    b0, b1 = px[c]["bars"].get(Sym), px[c]["bars"].get(ym_add(Sym, 1))
                    g = (b1[0] / b0[0]) if (b0 and b1) else None
                if g is None:
                    continue                       # 開始までに価格が消えた社は入れない（まだ持っていない）
                kind[c] = "p"
            else:
                g = 1.0 if (early or c0ret is None) else 1.0 + c0ret.get(ym_add(Sym, 1), 0.0)
                kind[c] = "u"
            wt[c] = w * g
            st[c] = "act"
        if not wt:
            continue
        tot = sum(wt.values())
        wt = {c: w / tot for c, w in wt.items()}
        unp_w.append(sum(w for c, w in wt.items() if kind[c] == "u"))
        unp_n.append(sum(1 for c in wt if kind[c] == "u"))
        if prev_w:
            keys = set(prev_w) | set(wt)
            tv = sum(abs(wt.get(c, 0.0) - prev_w.get(c, 0.0)) for c in keys)
        else:
            tv = 0.0
        turn_log.append(tv / 2)
        first = True
        for mm in months:
            if mm > 202608:
                break
            r, live = {}, {}
            for c, w in wt.items():
                if st[c] == "out":
                    continue
                if st[c] == "cash":
                    live[c] = w
                    r[c] = 0.0
                    continue
                if kind[c] == "p":
                    bars = px[c]["bars"]
                    b0, b1 = bars.get(ym_add(mm, -1)), bars.get(mm)
                    if b0 and b1:
                        r[c] = b1[0] / b0[0] - 1.0
                    elif px[c]["last"] < mm:                    # 系列が途切れた
                        if mode == "lb":
                            r[c] = LB_HIT
                            st[c] = "cash"
                        else:
                            st[c] = "out"
                            continue
                    else:
                        r[c] = 0.0                              # 月の穴（まれ）は据え置き
                else:
                    hit = None
                    if mode == "lb":
                        lym = ym_of_ord(cand[c]["last_o"])
                        if Sym <= lym < months[-1]:
                            hit = max(ym_add(lym, 1), start)
                    if hit is not None and mm == hit:
                        r[c] = LB_HIT
                        st[c] = "cash"
                    elif hit is not None and mm > hit:
                        st[c] = "cash"
                        r[c] = 0.0
                    else:
                        x = c0ret.get(mm) if c0ret is not None else None
                        if x is None:
                            st[c] = "out"
                            continue
                        r[c] = x
                live[c] = w
            sw = sum(live.values())
            if sw <= 0:
                continue
            rp = sum(live[c] * r[c] for c in live) / sw
            if mm >= count_from:
                for c in live:
                    contrib[c] += live[c] / sw * r[c]
            new = {c: (live[c] / sw) * (1 + r[c]) / (1 + rp) for c in live}
            s2 = sum(new.values())
            wt = {c: w / s2 for c, w in new.items()}
            net = rp
            if fee:
                net -= fee / 12.0
            if cost and first:
                net -= cost * tv
            first = False
            rets[mm] = net
        prev_w = dict(wt)
    diag = {"turnover_oneway_avg": (sum(turn_log[1:]) / (len(turn_log) - 1)) if len(turn_log) > 1 else None,
            "unpriced_weight_avg": (sum(unp_w) / len(unp_w)) if unp_w else None,
            "unpriced_n_avg": (sum(unp_n) / len(unp_n)) if unp_n else None}
    return rets, dict(contrib), diag


# ───────────────────────── 段D: 成績・格付け ─────────────────────────
def to_jpy(usd, fx):
    out = {}
    for m, r in usd.items():
        f0, f1 = fx.get(ym_add(m, -1)), fx.get(m)
        if f0 and f1:
            out[m] = (1 + r) * (f1 / f0) - 1
    return out


def bench_ret(series):
    out = {}
    for m, v in series.items():
        p = series.get(ym_add(m, -1))
        if p:
            out[m] = v / p - 1
    return out


def clip(d, a=COUNT_FROM, z=202608):
    return {m: v for m, v in d.items() if a <= m <= z}


def blocks(s, b, months):
    """窓ごとの excess_stats。months=数える月の昇順リスト"""
    import nx_common as N
    mid = months[len(months) // 2]
    E = lambda a=None, z=None: N.excess_stats(s, b, a, z)
    return {
        "full": E(), "first_half": E(None, ym_add(mid, -1)), "second_half": E(mid, None),
        "provider_2016-07_2026-07": E(201607, 202607),
        "pre_provider_2012-11_2016-06": E(None, 201606),
        "2016-07_2019-12": E(201607, 201912), "2020-01_2022-12": E(202001, 202212), "2023-01_2026-08": E(202301, None),
        "split_month": mid,
    }


def yr1_stats(s, a=202106, z=202605):
    """1年騰落率（各月末）の 最大・最小・平均（%）— 目論見書の表と同じ切り方"""
    out = []
    for m in sorted(s):
        if a <= m <= z:
            prod = 1.0
            ok = True
            for i in range(12):
                v = s.get(ym_add(m, -i))
                if v is None:
                    ok = False
                    break
                prod *= 1 + v
            if ok:
                out.append((prod - 1) * 100)
    if not out:
        return None
    return {"n": len(out), "max": round(max(out), 1), "min": round(min(out), 1), "mean": round(sum(out) / len(out), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["select", "all"])
    ap.add_argument("--dates", default=None)
    a = ap.parse_args()
    import gate_add_facts as G
    import nx_common as N
    t0 = time.time()
    firms, px, bench, P = load_all()
    tick, _ = G.ticker_table()
    tick = set(tick)
    dates = a.dates.split(",") if a.dates else sel_dates()
    cands, diag = stage_a(firms, px, bench, tick, dates)
    variants = ["V1", "V1b", "V2", "C1", "C0"]
    sels = {v: select_variant(cands, dates, v) for v in variants}
    sels["V1_top50"] = select_variant(cands, dates, "V1", 50)
    sels["V1_top100"] = select_variant(cands, dates, "V1", 100)
    names = {c: f.name for c, f in firms.items()}
    if a.stage == "select":
        for v in ("V1", "V2"):
            for it in sels[v][-3:]:
                print(v, it["S"], "wl", it["wl"], "p1", it["p1"], "p2", it["p2"], "sel", len(it["sel"]),
                      [names[c][:14] for c in it["sel"][:8]])
        return
    fx_r = bench_ret(bench["JPY=X"])
    fxb = bench["JPY=X"]
    spx_u = clip(bench_ret(bench["^SP500TR"]))
    qqq_u, iwm_u = clip(bench_ret(bench["QQQ"])), clip(bench_ret(bench["IWM"]))
    months = sorted(m for m in spx_u if m in fx_r)
    J = lambda u: clip(to_jpy(u, fxb))
    spx, qqq, iwm = J(spx_u), J(qqq_u), J(iwm_u)
    # C0
    c0_u, _c, c0d = simulate(sels["C0"], cands, px, dates, mode="base", priced_only=True, capped=False, count_from=COUNT_FROM)
    c0all = {m: v for m, v in c0_u.items()}
    c0ew_u, _c, _d = simulate(sels["C0"], cands, px, dates, mode="base", priced_only=True, weighting="ew", count_from=COUNT_FROM)
    c0 = J(c0all)
    c0ew = J(c0ew_u)
    out = {"generated": datetime.date.today().isoformat(), "prereg": "out/reformers_prereg.json（コミット a595eee2）",
           "counted_months": [months[0], months[-1], len(months)], "diag_by_S": diag}
    res = {}
    # 各ポートフォリオ
    cfgs = {
        "V1": dict(sel="V1"), "V1b": dict(sel="V1b"), "V2": dict(sel="V2"), "C1": dict(sel="C1"),
        "V1_ew": dict(sel="V1", weighting="ew"), "V1_early": dict(sel="V1", early=True),
        "V1_top50": dict(sel="V1_top50"), "V1_top100": dict(sel="V1_top100"),
    }
    series_u = {}
    for nm, cfg in cfgs.items():
        s_u, contrib, dd = simulate(sels[cfg["sel"]], cands, px, dates, c0ret=c0all, mode="base", early=cfg.get("early", False),
                                    weighting=cfg.get("weighting", "cap"), count_from=COUNT_FROM)
        series_u[nm] = (s_u, contrib, dd)
    # 下限版・価格つきだけ・費用
    extra = {}
    for nm in ("V1", "V1b", "V2", "C1"):
        extra[nm + "_lb"] = simulate(sels[nm], cands, px, dates, c0ret=c0all, mode="lb", count_from=COUNT_FROM)[0]
        extra[nm + "_priced_only"] = simulate(sels[nm], cands, px, dates, c0ret=c0all, mode="base", priced_only=True, count_from=COUNT_FROM)[0]
        extra[nm + "_net"] = simulate(sels[nm], cands, px, dates, c0ret=c0all, mode="base", fee=FEE, cost=TRADE_COST, count_from=COUNT_FROM)[0]
    # 1社抜き（V1 の寄与最大）
    top_c = sorted(series_u["V1"][1].items(), key=lambda kv: -kv[1])[:5]
    drop = {}
    for c, _v in top_c[:3]:
        drop[c] = simulate(sels["V1"], cands, px, dates, c0ret=c0all, mode="base", exclude={c}, count_from=COUNT_FROM)[0]
    out["top_contributors_V1"] = [{"cik": c, "name": names[c], "cum_contribution_pct": round(v * 100, 1)} for c, v in top_c]
    opp = {"C0": c0, "SPX": spx, "QQQ": qqq, "IWM": iwm}
    pack = {}
    for nm, (s_u, contrib, dd) in series_u.items():
        s = J(s_u)
        pack[nm] = {"n_months": len(s), "diag": dd,
                    "vs": {o_: blocks(s, b, months) for o_, b in opp.items()},
                    "usd_vs_SPX": blocks(clip(s_u), spx_u, months),
                    "yr1_2021-06_2026-05": yr1_stats(s),
                    "cagr_jpy": round(N.cagr(s) * 100, 2), "maxdd_jpy": round(N.maxdd(s) * 100, 1),
                    "rolling5y_vs_SPX": N.rolling(s, spx, years=5, start_month=1),
                    "rolling5y_vs_C0": N.rolling(s, c0, years=5, start_month=1)}
    for nm, s_u in extra.items():
        s = J(s_u)
        pack[nm] = {"vs": {o_: N.excess_stats(s, b) for o_, b in (("C0", c0), ("SPX", spx))}}
    for c, s_u in drop.items():
        s = J(s_u)
        pack["V1_drop_" + names[c][:12].replace(" ", "_")] = {"cik": c, "vs": {o_: N.excess_stats(s, b) for o_, b in (("C0", c0), ("SPX", spx))}}
    pack["C0"] = {"cagr_jpy": round(N.cagr(c0) * 100, 2), "yr1_2021-06_2026-05": yr1_stats(c0), "diag": c0d,
                  "vs_SPX": blocks(c0, spx, months)}
    pack["C0EW"] = {"cagr_jpy": round(N.cagr(c0ew) * 100, 2), "vs_SPX": blocks(c0ew, spx, months), "vs_C0": blocks(c0ew, c0, months)}
    pack["SPX"] = {"cagr_jpy": round(N.cagr(spx) * 100, 2), "yr1_2021-06_2026-05": yr1_stats(spx),
                   "cagr_usd": round(N.cagr(spx_u) * 100, 2)}
    pack["QQQ"] = {"cagr_jpy": round(N.cagr(qqq) * 100, 2), "yr1_2021-06_2026-05": yr1_stats(qqq)}
    pack["IWM"] = {"cagr_jpy": round(N.cagr(iwm) * 100, 2), "yr1_2021-06_2026-05": yr1_stats(iwm)}
    out["portfolios"] = pack
    # 格付け（V1・短標本）
    fam = {}
    for o_ in ("C0", "SPX"):
        fam[o_] = pack["V1"]["vs"][o_]["full"]
    pone = {o_: N.p_one(x["t"]) if x else None for o_, x in fam.items()}
    holm = N.holm(pone)
    grades = {}
    for o_, b in (("C0", c0), ("SPX", spx)):
        v = pack["V1"]["vs"][o_]
        dt = None
        for c, s_u in drop.items():
            dt = N.excess_stats(J(s_u), b) if dt is None else dt
        # 最大寄与の1社を抜いた版
        top1 = top_c[0][0]
        dt = N.excess_stats(J(drop[top1]), b)
        g, crit = N.grade_short(v["full"], v["first_half"], v["second_half"], dt,
                                N.excess_stats(J(extra["V1_net"]), b), N.excess_stats(J(extra["V1_lb"]), b), holm.get(o_))
        grades[o_] = {"grade": g, "criteria": crit, "holm_adj_p_one": holm.get(o_)}
    out["grades_V1"] = grades
    # 名指しの組入
    named = {"MU": "723125", "HOOD": "1783879", "DUOL": "1562088", "UBER": "1543151", "PLTR": "1321655"}
    mem = {}
    for v in ("V1", "V2"):
        for nm, cik in named.items():
            mem[f"{v}:{nm}"] = [it["S"] for it in sels[v] if cik in it["sel"]]
    out["named_members"] = mem
    out["selection_log"] = {v: [{"S": it["S"], "wl": it["wl"], "p1": it["p1"], "p2": it["p2"], "n": len(it["sel"]),
                                 "unpriced_n": sum(1 for c in it["sel"] if not cands[it["S"]][c]["priced"]),
                                 "top": [names[c][:22] for c in it["sel"][:5]]} for it in sels[v]] for v in ("V1", "V2", "C1")}
    p = os.path.join(OUT, "reformers.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    print(f"■ → {p} {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
