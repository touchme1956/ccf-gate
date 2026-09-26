#!/usr/bin/env python3
"""night/smh_crash_dca.py — 「半導体ETFは暴落時だけ積み立てる」を歴史で測る（読むだけ・配分は変えない）

毎月同額を入れる。ふだんは QQQ（=iFreeNEXT と同じ NASDAQ100）へ。SMH がその月までの最高値から D% 以上
下がっている月だけ、その月の全額（または10%分）を SMH へ。判定はその月までの値だけ（先読みなし）。
比べる相手: QQQのみ／毎月 QQQ90+SMH10（今の形）。線 D は 30/40/50% を先に決めて全部出す。
出力: out/smh_crash_dca.json
"""
import json, os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_theme as T

def add(k, n):
    y, m = int(k[:4]), int(k[5:]); m += n; y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f'{y:04d}-{m:02d}'

def run(px, ms, rule):
    """rule(m, dd) → {ticker: 割合}。最終評価額 ÷ 投下額と、SMH に入った月数を返す"""
    units = {'QQQ': 0.0, 'SMH': 0.0}; n = 0; hits = 0
    for m in ms[:-1]:
        w = rule(m); n += 1; hits += w.get('SMH', 0) > 0
        for t, a in w.items(): units[t] += a / px[t][m]
    e = ms[-1]
    return sum(units[t] * px[t][e] for t in units) / n, hits

def main():
    px = {t: T.fetch(t) for t in ('QQQ', 'SMH')}
    common = sorted(set(px['QQQ']) & set(px['SMH']))
    end = max(m for m in common if m < time.strftime('%Y-%m'))
    common = [m for m in common if m <= end]
    peak, dd = 0, {}
    for m in common:
        peak = max(peak, px['SMH'][m]); dd[m] = 1 - px['SMH'][m] / peak
    rules = {'QQQのみ': lambda m: {'QQQ': 1},
             '毎月 QQQ90/SMH10（今の形）': lambda m: {'QQQ': .9, 'SMH': .1}}
    for D in (.3, .4, .5):
        rules[f'暴落{int(D*100)}%以上の月だけ全額SMH'] = (lambda D: lambda m: {'SMH': 1} if dd[m] >= D else {'QQQ': 1})(D)
        rules[f'暴落{int(D*100)}%以上の月だけ20%をSMH'] = (lambda D: lambda m: {'QQQ': .8, 'SMH': .2} if dd[m] >= D else {'QQQ': 1})(D)
    out = {'窓': f'{common[0]}→{end}', '暴落の月の数': {f'{int(D*100)}%': sum(dd[m] >= D for m in common) for D in (.3, .4, .5)}, '結果': {}}
    for Y in (20, 15, 10):
        res = {k: [] for k in rules}
        for i, a in enumerate(common):
            b = add(a, Y * 12)
            if b > end: break
            ms = [m for m in common if a <= m <= b]
            for k, r in rules.items():
                v, h = run(px, ms, r); res[k].append(v)
        base = res['QQQのみ']
        out['結果'][f'転がる{Y}年'] = {k: {'窓': len(v), '倍率の中央': round(sorted(v)[len(v) // 2], 3), '最悪': round(min(v), 3),
                                       'QQQのみに勝った割合': round(sum(x > y for x, y in zip(v, base)) / len(v), 2)} for k, v in res.items()}
    v, h = zip(*[run(px, common, r) for r in rules.values()])
    out['全期間'] = {k: {'倍率': round(x, 3), 'SMHを買った月': y} for k, x, y in zip(rules, v, h)}
    json.dump(out, open(os.path.join(BASE, 'out', 'smh_crash_dca.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()
