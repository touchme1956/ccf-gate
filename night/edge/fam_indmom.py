#!/usr/bin/env python3
"""night/edge/fam_indmom.py — 系統 indmom: 業種の勢いの入れ替え（Moskowitz & Grinblatt 1999）

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。
  信号: 月末 m−1 までの過去 J か月（skip=1 なら直近1か月を飛ばす）の業種リターンの複利。上位 k 業種を
        等加重（ew）または時価加重（vw）で翌月 m の1か月だけ持つ。毎月入れ替え。
  データ: Ken French の {N}_Industry_Portfolios の 'Average Value Weighted Returns -- Monthly'（業種の中は時価加重・配当込み）。
        時価加重の重みは 'Number of Firms in Portfolios' × 'Average Firm Size' の **m−1 月の行**に m−1 月のリターンを掛けたもの
        （French の Average Firm Size の m 月の行は m−1 月末の時価＝実測で確認済み。ここではさらに1行古い行から作るので
        m 月の行を一切読まない＝どちらの約束でも先読みにならない）。
  相手: 米国市場（h.us_market＝French の CRSP 全上場の時価加重・配当込み）。費用: 片道の回転1あたり 0.10%（業種ETF）。
  回転: 前月の重みを当月のリターンで流した後の重みと、新しい重みの差の絶対値の和の半分（片道）。最初の月は 1（全額を買う）。
  欠測: 窓の全月と m−1 月のリターンがそろう業種だけを順位に入れる。持っている業種の m 月が欠測（業種の社数が0になった月・
        49業種の Rubbr 1943-07 の1回だけ）はリターン 0 と置く（その月にその業種が消えることを前もって知らないため）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h                                                  # noqa: E402
import math

FAMILY = {
    'key': 'indmom',
    'name': '業種の勢いの入れ替え（過去の勝ち業種を翌月持つ）',
    'implement': ('米国の業種ETF（SPDR の Select Sector 11本〔XLK・XLV・XLF・XLE・XLI・XLY・XLP・XLU・XLB・XLRE・XLC〕、'
                  '細かい業種なら SPDR/iShares の業種ETF〔XSD・XBI・XHB・KRE・XME・XOP・IYT・ITA など〕）を楽天証券の米国株口座で、'
                  '毎月末に過去の成績を並べて上位の業種ETFへ入れ替える。⚠ NISA の成長投資枠でも買えるが、毎月の入れ替えは'
                  '年240万円の枠を買うたびに消費し、売った枠は翌年まで戻らないので NISA では続けられない＝課税口座（特定口座）で行う'
                  '（利益の20.315%が売るたびに課税される＝事前登録どおり主の判定には入れない）'),
}

COST = 0.001            # 事前登録: 指数・ETF・業種の入れ替え＝片道の回転100%につき 0.10%

_cache = {}


def _load(n):
    if n not in _cache:
        d = h.french(f'{n}_Industry_Portfolios')
        r = {i: {m: v / 100 for m, v in s.items() if m > 99999} for i, s in d['Average Value Weighted Returns -- Monthly'].items()}
        nf = d.get('Number of Firms in Portfolios', {})
        sz = d.get('Average Firm Size', {})
        cap = {}
        for i in r:
            a, b = nf.get(i, {}), sz.get(i, {})
            cap[i] = {m: a[m] * b[m] for m in a if m in b and m > 99999 and a[m] > 0 and b[m] > 0}
        _cache[n] = (r, cap)
    return _cache[n]


def signal(r, m, J, skip):
    """月 m に持つ業種を選ぶための得点（m−1 月末までのデータだけ）。{業種: 過去Jか月の複利}"""
    last = h.add_months(m, -1 - skip)                    # 窓の最後の月
    first = h.add_months(last, -(J - 1))
    prev = h.add_months(m, -1)
    out = {}
    for i, s in r.items():
        if prev not in s:
            continue
        g, ok, mm = 1.0, True, first
        while mm <= last:
            x = s.get(mm)
            if x is None:
                ok = False
                break
            g *= 1 + x
            mm = h.add_months(mm, 1)
        if ok:
            out[i] = g - 1
    return out


def weights(r, cap, m, spec):
    sc = signal(r, m, spec['J'], spec.get('skip', 0))
    if len(sc) < max(spec['k'] + 1, 3):
        return None
    top = [i for i, _ in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[:spec['k']]]
    if spec.get('weight', 'ew') == 'vw':
        prev = h.add_months(m, -1)
        # m−1 の行の時価（＝m−2 月末）× (1＋m−1 月のリターン) ≒ m−1 月末の時価。m 月の行は読まない
        cw = {i: cap[i].get(prev, 0.0) * (1 + r[i][prev]) for i in top}
        tot = sum(cw.values())
        if tot <= 0:
            return {i: 1 / len(top) for i in top}
        return {i: v / tot for i, v in cw.items()}
    return {i: 1 / len(top) for i in top}


def run(spec):
    """spec: {'n': 業種の数, 'J': 窓の月数, 'skip': 0|1, 'k': 持つ業種の数, 'weight': 'ew'|'vw'}"""
    r, cap = _load(spec['n'])
    mkt, rf = h.us_market()
    months = sorted(set().union(*[set(s) for s in r.values()]))
    ret, tv = {}, {}
    w_prev_drift = None
    for m in months:
        w = weights(r, cap, m, spec)
        if w is None:
            continue
        rp = sum(wi * r[i].get(m, 0.0) for i, wi in w.items())
        if w_prev_drift is None:
            tv[m] = 1.0
        else:
            ks = set(w) | set(w_prev_drift)
            tv[m] = 0.5 * sum(abs(w.get(i, 0.0) - w_prev_drift.get(i, 0.0)) for i in ks)
        ret[m] = rp
        w_prev_drift = {i: wi * (1 + r[i].get(m, 0.0)) / (1 + rp) for i, wi in w.items()} if rp > -1 else None
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}


if __name__ == '__main__':
    sp = {'n': 10, 'J': 6, 'skip': 0, 'k': 3, 'weight': 'ew'}
    x = run(sp)
    print(sp, h.stats(x['ret'], x['bench'], x['rf'], turnover=x['turnover'], cost=x['cost']))
