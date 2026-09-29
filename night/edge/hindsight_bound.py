#!/usr/bin/env python3
"""night/edge/hindsight_bound.py — 事後の上限: 後知恵で選んでも、2001年以降の米国市場に勝った買いだけの組はいくつあるか

  判定ではない（事前登録の外・結果を見た後に選べば必ず勝つ組は見つかる）。『探す余地がどれだけ残っているか』の目安。
  JKP 米国の153特徴 × 良い側の三分位（JKP の direction：因子と 3.0−1.0 の相関の符号で決める）× vw_cap / vw を、
  French 米国市場（上限なし）と 2001-01〜 で比べる。費用は 0.25%×回転（置き値 100%/年＝会計と価格の間）。
  出力: out/edge/hindsight_bound.json
"""
import os, sys, json, math, statistics as S
os.environ['EDGE_PHASE'] = 'holdout'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h                      # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

OUT = os.path.join(h.BASE, 'out', 'edge', 'hindsight_bound.json')
COST, TURN = 0.0025, 1.0


def chars():
    d = json.loads(h.cached('jkp_availability.json', 'https://jkpfactors-data.s3.amazonaws.com/public/availability.json'))
    f = d.get('factors', {})
    names = f.get('usa') or f.get('all_countries') or []
    return sorted(n for n in names if n != 'mkt')      # テーマ名（accruals 等）は三分位のファイルが無く one() が捨てる


def one(c, mk, rf):
    try:
        f = h.jkp('usa', c, 'factor', 'vw_cap')
    except Exception:
        return None
    out = {'char': c}
    for w in ('vw_cap', 'vw'):
        try:
            p = h.jkp('usa', c, 'portfolio', w)
        except Exception:
            continue
        if '1.0' not in p or '3.0' not in p:
            continue
        common = [m for m in f if m in p['1.0'] and m in p['3.0'] and m <= 200012]
        if len(common) < 60:
            continue
        a = [f[m] for m in common]; b = [p['3.0'][m] - p['1.0'][m] for m in common]
        ma, mb = S.mean(a), S.mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        side = '3.0' if cov >= 0 else '1.0'
        r = {m: v + rf[m] for m, v in p[side].items() if m in rf}
        tv = {m: TURN / 12 for m in r}
        st = h.stats(r, mk, rf, a=h.HOLD_START, turnover=tv, cost=COST)
        st7 = h.stats(r, mk, rf, a=200701, turnover=tv, cost=COST)
        if st:
            out[w] = {'side': side, 'excess': st['excess'], 't': st['t'], 'vol': st['vol'], 'bench_vol': st['bench_vol'],
                      'excess_2007': st7['excess'] if st7 else None, 't_2007': st7['t'] if st7 else None}
    return out if len(out) > 1 else None


def main():
    mk, rf = h.us_market()
    cs = chars()
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(lambda c: one(c, mk, rf), cs) if r]
    summ = {}
    for w in ('vw_cap', 'vw'):
        xs = [r[w] for r in rows if w in r]
        summ[w] = {'n': len(xs),
                   'excess_gt0': sum(1 for x in xs if x['excess'] > 0),
                   'excess_ge1_t_ge2': sum(1 for x in xs if x['excess'] >= 1 and (x['t'] or 0) >= 2),
                   'excess_ge1_t_ge2_and_2007on_positive': sum(1 for x in xs if x['excess'] >= 1 and (x['t'] or 0) >= 2 and (x['excess_2007'] or -1) > 0),
                   'best10': sorted(({'char': r['char'], **r[w]} for r in rows if w in r), key=lambda z: -(z['t'] or -9))[:10]}
    out = {'about': '事後の上限（判定ではない）: 後知恵で良い側を選んでも、2001年以降の米国市場に勝った JKP の買いだけの三分位はいくつあるか。'
                    '良い側は選定期間（〜2000-12）の因子と三分位の差の相関で決めた（後知恵を1つ減らすため）。費用 0.25%×回転100%/年',
           'rows': rows, 'summary': summ}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for w, s in summ.items():
        print(w, {k: v for k, v in s.items() if k != 'best10'})
        for b in s['best10']:
            print('   ', b['char'], b['side'], b['excess'], b['t'], '2007〜', b['excess_2007'], b['t_2007'])


if __name__ == '__main__':
    main()
