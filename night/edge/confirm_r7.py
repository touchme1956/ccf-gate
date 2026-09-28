#!/usr/bin/env python3
"""night/edge/confirm_r7.py — 「市場に勝てる規則の探索」第7回（確認）: 凍結した6規則を新興国で確かめる（事前登録 out/edge_prereg_r7.json）

  ★凍結した規則（out/edge/spec_*.json・night/edge/fam_*.py）は変えない。各 fam の build(spec, 国, rf, 20) をそのまま呼ぶ。
  ★EDGE_PHASE=holdout はこのプロセスの中でだけ立てる。判定は 2001-01〜。2001年より前は報告だけ。
  相手: その国の JKP mkt（vw）＋米国 rf（fam の run() の再現と同じ作り）。費用: 0.5%/回転（回転は fam の置き値のまま）。
  出力: out/edge/confirm_r7.json
"""
import os, sys, json, math, importlib, datetime
os.environ['EDGE_PHASE'] = 'holdout'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h                     # noqa: E402
from evaluate import pooled, committed  # noqa: E402

assert h.PHASE == 'holdout'
EM = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
TESTS = {'C7_profit_em': 'profit', 'C8_payout_em': 'payout', 'C9_resmom_em': 'resmom',
         'C10_rd_em': 'rd', 'C11_hi52_em': 'hi52', 'C12_old_firms_em': 'old_firms'}
COST_EM, MIN_N, T_MIN, SHARE_MIN, ALPHA = 0.005, 20, 2.0, 0.6, 0.05
OUT = os.path.join(h.BASE, 'out', 'edge', 'confirm_r7.json')


def one_test(key):
    for p in (f'out/edge/spec_{key}.json', f'night/edge/fam_{key}.py'):
        sha, clean = committed(p)
        if not sha or not clean:
            raise SystemExit(f'{key}: {p} がコミットされていない／変更がある')
    spec = json.load(open(os.path.join(h.BASE, 'out', 'edge', f'spec_{key}.json')))['spec']
    mod = importlib.import_module(f'fam_{key}')
    _, rf = h.us_market()
    markets, by = {}, {}
    for c in EM:
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')
        except Exception as e:
            by[c] = {'note': f'JKP の市場が無い（{type(e).__name__}）'}; continue
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        try:
            r, t = mod.build(spec, c, rf, MIN_N)
        except Exception as e:
            by[c] = {'note': f'特徴の系列が無い（{type(e).__name__}: {str(e)[:80]}）'}; continue
        r = {m: v for m, v in r.items() if m in bench}
        if not r:
            by[c] = {'note': '20社以上の月が無い'}; continue
        x = {'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t.get(m, 0.0) for m in r}, 'cost': COST_EM}
        n01 = sum(1 for m in r if m >= h.HOLD_START)
        st = h.stats(r, bench, rf, a=h.HOLD_START, turnover=x['turnover'], cost=COST_EM) if n01 >= 24 else None
        pre = h.stats(r, bench, rf, b=200012, turnover=x['turnover'], cost=COST_EM) if sum(1 for m in r if m <= 200012) >= 24 else None
        by[c] = {'months_since2001': n01, 'holdout': st, 'pre2001_info': pre}
        if n01 > 0:
            markets[c] = x
    rated = {c: v for c, v in by.items() if v.get('holdout')}
    pos = sum(1 for v in rated.values() if v['holdout']['excess'] > 0)
    ex, t = pooled(markets)
    halves = {}
    for lab, a, b in (('2001-2012', 200101, 201212), ('2013-', 201301, 999999)):
        sub = {c: {**x, 'ret': {m: v for m, v in x['ret'].items() if a <= m <= b}} for c, x in markets.items()}
        halves[lab] = dict(zip(('excess', 't'), pooled(sub)))
    p = 0.5 * math.erfc(t / math.sqrt(2)) if t is not None else 1.0
    return {'key': key, 'spec': spec, 'by_country': by, 'countries_rated': len(rated), 'positive': f'{pos}/{len(rated)}',
            'positive_share': round(pos / len(rated), 3) if rated else None, 'pooled_excess': ex, 'pooled_t': t,
            'p_one_sided': p, 'halves': halves}


def main():
    res = {k: one_test(v) for k, v in TESTS.items()}
    order = sorted(res, key=lambda k: res[k]['p_one_sided'])
    K, alive = len(order), True
    for i, k in enumerate(order):
        thr = ALPHA / (K - i)
        alive = alive and res[k]['p_one_sided'] <= thr
        r = res[k]
        r['holm'] = {'thr': round(thr, 5), 'pass': alive}
        c1 = r['pooled_t'] is not None and r['pooled_t'] >= T_MIN and (r['pooled_excess'] or 0) > 0
        c2 = (r['positive_share'] or 0) >= SHARE_MIN
        r['criteria'] = {'ならした超過が正で t≥2': c1, '6割以上の国で正': c2, 'Holm（6本の中）': alive}
        r['verdict'] = '再現した' if (c1 and c2 and alive) else '再現しなかった'
    out = {'title': '第7回の確認（凍結した6規則を新興国へ）', 'prereg': 'out/edge_prereg_r7.json',
           'generated': datetime.date.today().isoformat(), 'cost_per_turnover': COST_EM, 'min_n': MIN_N, 'K_within': K,
           'tests': res}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for k in TESTS:
        r = res[k]
        print(f"{k:18s} {r['verdict']:6s} 正 {r['positive']:>6s}  ならし {r['pooled_excess']}%/年 t{r['pooled_t']}  "
              f"半分 {r['halves']}  Holm {r['holm']}")


if __name__ == '__main__':
    main()
