#!/usr/bin/env python3
"""night/net_mix_search.py — ETF側の配合（QQQ/XLK/SMH/SPY・10%刻み）を毎月積立で総当たりし、
『どの窓・どの時代でも崩れない』配合を探す（読むだけ・配分は変えない）

物差し（どれも毎月同額の積立・最後の評価額÷投下額）:
  20年の中央・20年の最悪・15年の最悪・15年の中央を『前半に始めた窓（〜2005-12）』と『後半（2006-01〜）』で別々に。
堅さ＝上の5つの順位の平均（小さいほど良い）。一つの物差しの1位ではなく、全部で上位に居るものを選ぶ。
出力: out/net_mix_search.json
"""
import json, os, sys, time, itertools
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_theme as T

def add(k, n):
    y, m = int(k[:4]), int(k[5:]); m += n; y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f'{y:04d}-{m:02d}'

def main():
    A = ('QQQ', 'XLK', 'SMH', 'SPY')
    px = {t: T.fetch(t) for t in A}
    c = sorted(set.intersection(*[set(px[t]) for t in A])); end = max(m for m in c if m < time.strftime('%Y-%m')); c = [m for m in c if m <= end]
    idx = {m: i for i, m in enumerate(c)}
    # 1単位を月 i に入れて月 j に持っていれば px[j]/px[i]。前計算: 各資産の「i..j-1 に毎月1ずつ入れた口数」の累積
    import numpy as np
    P = {t: np.array([px[t][m] for m in c]) for t in A}
    cumU = {t: np.concatenate([[0], np.cumsum(1 / P[t])]) for t in A}
    def windows(Y):
        out = []
        for a in c:
            b = add(a, Y * 12)
            if b > end: break
            out.append((idx[a], idx[b], a))
        return out
    W20, W15 = windows(20), windows(15)
    combos = [w for w in itertools.product(range(11), repeat=4) if sum(w) == 10]
    rows = []
    for w in combos:
        def mult(i, j):
            n = j - i
            return sum((w[k] / 10) * (cumU[t][j] - cumU[t][i]) * P[t][j] for k, t in enumerate(A)) / n
        v20 = sorted(mult(i, j) for i, j, _ in W20)
        v15a = sorted(mult(i, j) for i, j, a in W15 if a <= '2005-12'); v15b = sorted(mult(i, j) for i, j, a in W15 if a >= '2006-01')
        v15 = sorted(v15a + v15b)
        rows.append({'配合': dict(zip(A, [x * 10 for x in w])), '20年中央': round(v20[len(v20) // 2], 3), '20年最悪': round(v20[0], 3),
                     '15年最悪': round(v15[0], 3), '15年中央_前半': round(v15a[len(v15a) // 2], 3), '15年中央_後半': round(v15b[len(v15b) // 2], 3)})
    keys = ['20年中央', '20年最悪', '15年最悪', '15年中央_前半', '15年中央_後半']
    for k in keys:
        for r, x in enumerate(sorted(rows, key=lambda x: -x[k]), 1): x.setdefault('順位', {})[k] = r
    for x in rows: x['堅さ'] = round(sum(x['順位'].values()) / len(keys), 1)
    rows.sort(key=lambda x: x['堅さ'])
    def find(q, xl, sm, sp): return next(x for x in rows if x['配合'] == {'QQQ': q, 'XLK': xl, 'SMH': sm, 'SPY': sp})
    ref = {'今（iFree50/XLK20/SMH10 ≈ QQQ62.5/XLK25/SMH12.5 → 60/30/10）': find(60, 30, 10, 0), 'QQQのみ': find(100, 0, 0, 0),
           'SPYのみ': find(0, 0, 0, 100), 'QQQ60/XLK10/SMH30': find(60, 10, 30, 0), 'QQQ70/SMH30': find(70, 0, 30, 0), 'QQQ80/SMH20': find(80, 0, 20, 0)}
    out = {'窓': f'{c[0]}→{end}', '組み合わせ': len(rows), '20年窓': len(W20), '15年窓': len(W15), '上位15': rows[:15],
           '参考': {k: dict(v, 総合順位=rows.index(v) + 1) for k, v in ref.items()}}
    json.dump(out, open(os.path.join(BASE, 'out', 'net_mix_search.json'), 'w'), ensure_ascii=False, indent=1)
    for i, x in enumerate(rows[:15], 1): print(i, x['配合'], x['堅さ'], {k: x[k] for k in keys})
    print('--- 参考')
    for k, v in out['参考'].items(): print(k, '総合', v['総合順位'], '/', len(rows), {kk: v[kk] for kk in keys}, v['順位'])

if __name__ == '__main__':
    main()
