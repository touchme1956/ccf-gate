#!/usr/bin/env python3
"""night/portfolio_search.py — 歴史で「成功率が高く、リターンも高い」配合を総当たりで探す（2026-09-25・ユーザー指示）

読むだけ。portfolio.json・門・採点には触れない。
資産（月次・配当込み）: SPY / QQQ / XLK / SMH / IJR（小型株）/ GOLD（2004-11 前は金先物 GC=F・欠けた月は対数で内挿、以後は GLD）/
                       BOND（VFITX＝米国中期国債の投信・分配込み）。
窓: 全員がそろう 2000-08 → 最新（ITバブル崩壊の下げの大半・2008・2022 を含む）。
配合: 10%刻みの全組合せ（7資産・合計100%）＝8,008通り。毎月リバランス。
物差し（あなたの運用＝毎月同額の積立）:
  成功率10  = 転がる15年の積立窓のうち、積立の年率(IRR) >= 10% だった割合
  SPY勝率  = 同じ窓で S&P500 の積立に勝った割合
  中央・最悪 = 15年積立の年率の中央値・最悪値 ／ 20年積立も同様に出す ／ 最大下落（全期間・一括）
並べ方: 成功率10 → 中央値 の順。
★過学習の検問: 窓の起点を前半（2000-08〜2005-12 起点）と後半（2006-01〜 起点）に割り、
  前半だけで1位を選んで後半の成績を見る（逆も）。前半の1位が後半でも上位に残るかを報告する。
出力: out/portfolio_search.json
"""
import itertools, json, math, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_theme as E

ASSETS = ['SPY', 'QQQ', 'XLK', 'SMH', 'IJR', 'GOLD', 'BOND']

def ym_next(k):
    y, m = map(int, k.split('-')); m += 1
    if m > 12: y, m = y + 1, 1
    return f'{y:04d}-{m:02d}'

def months(a, b):
    out, k = [], a
    while k <= b: out.append(k); k = ym_next(k)
    return out

def gold_series():
    gc, gld = E.fetch('GC=F'), E.fetch('GLD')
    ks = months(min(gc), '2004-11')
    s = {}
    for i, k in enumerate(ks):
        if k in gc: s[k] = gc[k]; continue
        j0 = max(j for j in range(i) if ks[j] in gc); j1 = min(j for j in range(i + 1, len(ks)) if ks[j] in gc)
        a, b = math.log(gc[ks[j0]]), math.log(gc[ks[j1]])
        s[k] = math.exp(a + (b - a) * (i - j0) / (j1 - j0))
    f = s['2004-11'] / gld['2004-11']
    for k, v in gld.items():
        if k > '2004-11': s[k] = v * f
    return s

def load():
    C = {t: E.fetch(t) for t in ['SPY', 'QQQ', 'XLK', 'SMH', 'IJR']}
    C['GOLD'] = gold_series(); C['BOND'] = E.fetch('VFITX')
    start = max(min(v) for v in C.values()); end = min(max(v) for v in C.values())
    M = months(start, end)
    miss = {t: [k for k in M if k not in C[t]] for t in C}
    assert not any(miss.values()), miss
    R = {t: [C[t][b] / C[t][a] for a, b in zip(M, M[1:])] for t in C}   # 月次の倍率
    return M, R

import numpy as np

def path(w, R, n):
    """毎月リバランスの指数（長さ n+1）"""
    r = sum(w[t] * np.asarray(R[t]) for t in w if w[t])
    return np.concatenate([[1.0], np.cumprod(r)])

def dca_irr_all(v, L):
    """全ての起点 i0 について、L ヶ月毎月1ずつ積み立てた年率（IRR）と倍率。
    FV = v[i0+L] × Σ 1/v[i0+j]（累積和）、Σ m^(L-j) は等比級数の閉じた式＝二分法を全窓まとめて回す"""
    inv = np.concatenate([[0.0], np.cumsum(1.0 / v)])
    N = len(v) - L
    i0 = np.arange(N)
    fv = v[i0 + L] * (inv[i0 + L] - inv[i0])
    lo, hi = np.full(N, -0.99), np.full(N, 1.0)
    for _ in range(50):
        r = (lo + hi) / 2; m = (1 + r) ** (1 / 12)
        g = np.where(np.abs(m - 1) < 1e-12, L, m * (m ** L - 1) / (m - 1))
        lo = np.where(g < fv, r, lo); hi = np.where(g < fv, hi, r)
    return (lo + hi) / 2, fv / L

def evaluate(w, R, n, M, spy):
    v = path(w, R, n)
    out = {}
    for L, tag in ((180, '15y'), (240, '20y')):
        irr, mult = dca_irr_all(v, L)
        out[tag] = dict(irr=irr.tolist(), mult=mult.tolist())
    dd = float(np.min(v / np.maximum.accumulate(v) - 1))
    out['dd'] = dd; out['cagr'] = float(v[-1] ** (12 / n) - 1)
    return out

def summ(ev, spy_ev, idx=None):
    s = {}
    for tag in ('15y', '20y'):
        irr = ev[tag]['irr']; mult = ev[tag]['mult']; sm = spy_ev[tag]['mult']
        ii = idx if (idx is not None and tag == '15y') else range(len(irr))
        ii = [i for i in ii if i < len(irr)]
        if not ii: continue
        xs = sorted(irr[i] for i in ii)
        s[tag] = dict(n=len(ii), 成功率10=round(sum(irr[i] >= .10 for i in ii) / len(ii), 3),
                      成功率15=round(sum(irr[i] >= .15 for i in ii) / len(ii), 3),
                      SPY勝率=round(sum(mult[i] > sm[i] for i in ii) / len(ii), 3),
                      中央=round(xs[len(xs) // 2] * 100, 2), 最悪=round(xs[0] * 100, 2))
    s['最大下落'] = round(ev['dd'] * 100, 1); s['一括年率'] = round(ev['cagr'] * 100, 2)
    return s

def main():
    M, R = load(); n = len(M) - 1
    spy_ev = evaluate({'SPY': 1.0}, R, n, M, None)
    grid = [c for c in itertools.product(range(11), repeat=len(ASSETS)) if sum(c) == 10]
    res = []
    for c in grid:
        w = {t: c[i] / 10 for i, t in enumerate(ASSETS)}
        ev = evaluate(w, R, n, M, spy_ev)
        res.append((c, ev))
    n15 = len(spy_ev['15y']['irr'])
    split = M.index('2006-01')
    first, second = list(range(0, split)), list(range(split, n15))
    rows = []
    for c, ev in res:
        rows.append(dict(w={t: c[i] * 10 for i, t in enumerate(ASSETS) if c[i]}, all=summ(ev, spy_ev),
                         first=summ(ev, spy_ev, first), second=summ(ev, spy_ev, second)))
    key = lambda s: (s['15y']['成功率10'], s['15y']['中央'])
    rows.sort(key=lambda r: key(r['all']), reverse=True)
    # 過学習の検問: 前半で1位 → 後半の順位、後半で1位 → 前半の順位
    rk2 = sorted(range(len(rows)), key=lambda i: key(rows[i]['second']), reverse=True); pos2 = {i: r for r, i in enumerate(rk2)}
    rk1 = sorted(range(len(rows)), key=lambda i: key(rows[i]['first']), reverse=True); pos1 = {i: r for r, i in enumerate(rk1)}
    oos = dict(前半1位=dict(w=rows[rk1[0]]['w'], 後半での順位=pos2[rk1[0]] + 1, 後半=rows[rk1[0]]['second']),
               後半1位=dict(w=rows[rk2[0]]['w'], 前半での順位=pos1[rk2[0]] + 1, 前半=rows[rk2[0]]['first']),
               母数=len(rows))
    named = {'SPY100': {'SPY': 10}, 'QQQ100': {'QQQ': 10}, '現行ETF側（QQQ62/XLK23/SMH12〜）': {'QQQ': 6, 'XLK': 3, 'SMH': 1},
             '60/40（SPY60/BOND40）': {'SPY': 6, 'BOND': 4}, 'QQQ80/GOLD20': {'QQQ': 8, 'GOLD': 2}}
    nm = {}
    for k, d in named.items():
        c = tuple(d.get(t, 0) for t in ASSETS)
        ev = dict(res)[c] if c in dict(res) else None
        nm[k] = summ(ev, spy_ev)
    # 基準を年率15%へ上げた順位（10%では上位がそろって100%になり差が付かないため）
    by15 = sorted(rows, key=lambda r: (r['all']['15y']['成功率15'], r['all']['15y']['中央']), reverse=True)[:15]
    # リターン（15年積立の中央）と最大下落の釣り合いの前線: どちらかを良くするには他方を悪くするしかない配合
    pf = []
    for r in sorted(rows, key=lambda r: r['all']['最大下落'], reverse=True):
        if not pf or r['all']['15y']['中央'] > pf[-1]['all']['15y']['中央']: pf.append(r)
    out_extra = dict(top_by_success15=by15, pareto_median_vs_dd=pf)
    out = dict(**out_extra, generated=__import__('datetime').date.today().isoformat(), tool='night/portfolio_search.py',
               window=f'{M[0]} → {M[-1]}', assets=ASSETS, n_portfolios=len(rows),
               note='毎月リバランス・毎月同額の積立。成功率10=転がる15年の積立年率>=10%の割合。ドル建て・税と為替は入っていない。生存バイアス: 指数とETFは生き残った商品',
               top30=rows[:30], named=nm, out_of_sample=oos, spy=summ(spy_ev, spy_ev))
    json.dump(out, open(os.path.join(BASE, 'out', 'portfolio_search.json'), 'w'), ensure_ascii=False, indent=1)
    print('窓', out['window'], '配合', len(rows), '15年窓', n15)
    for r in rows[:15]: print(r['w'], r['all'])
    print('--- 名前つき'); [print(k, v) for k, v in nm.items()]
    print('--- 過学習の検問', json.dumps(oos, ensure_ascii=False))

if __name__ == '__main__':
    main()
