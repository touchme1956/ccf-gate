#!/usr/bin/env python3
"""night/etf_p15_check.py — etf_p15.py の積立の確率の表を、別の乱数・別の書き方で照らし合わせる（2026-10-10）

表（40,000本・同じ乱数を全格子点で使う・行列の積で資産を出す）と、別の種の400,000本で
内部収益率を1本ずつ解かずに『資産≥目標の資産』で数える直接の計算を、いくつかの (m, σ) で比べる。
あわせて、一括の閉じた式と一括の乱数の道を比べる。読むだけ。出力: out/etf_p15_check.json
"""
import json, math, os, sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_p15 as P   # noqa: E402

POINTS = [(0.07, 0.15), (0.09, 0.211), (0.207, 0.237), (0.261, 0.33), (0.10, 0.25), (0.14, 0.20)]


def direct(m, s, H=20, tau=0.15, npath=400000, seed=7, chunk=50000):
    T = 12 * H
    rng = np.random.default_rng(seed)
    K = sum((1 + tau) ** (n / 12) for n in range(1, T + 1))
    hit = 0
    for c0 in range(0, npath, chunk):
        r = rng.normal(m / 12, s / math.sqrt(12), size=(chunk, T))
        W = np.zeros(chunk)
        for t in range(T):            # 月の初めに1を入れ、その月のリターンで回す
            W = (W + 1.0) * np.exp(r[:, t])
        hit += int((W >= K).sum())
    return hit / npath


def main():
    sig = sorted({s for _, s in POINTS})
    P.S_GRID = np.array(sig)          # 必要な σ の行だけ表を作る（格子の値そのもの＝補間なし）
    tab = P.dca_tables(20, [0.15], log=False)[0.15]
    out = []
    for m, s in POINTS:
        i = sig.index(s); j = int(round((m - P.M0) / P.DM))
        assert abs(P.M_GRID[j] - m) < 1e-9
        t_val = float(tab[i, j]); d_val = direct(m, s)
        lump_cf = float(P.norm_cdf(np.array([(m - math.log1p(0.15)) * math.sqrt(20) / s]))[0])
        rng = np.random.default_rng(11)
        lump_sim = float((rng.normal(m * 20, s * math.sqrt(20), 400000) >= 20 * math.log1p(0.15)).mean())
        out.append(dict(m=m, sigma=s, 表=round(100 * t_val, 2), 直接=round(100 * d_val, 2), 差pt=round(100 * (t_val - d_val), 2),
                        一括_式=round(100 * lump_cf, 2), 一括_乱数=round(100 * lump_sim, 2)))
        print(out[-1], flush=True)
    worst = max(abs(o['差pt']) for o in out)
    doc = dict(tool='night/etf_p15_check.py', points=out, 最大の差pt=worst, 判定='一致（差が乱数の誤差の範囲）' if worst < 1.0 else '食い違い')
    json.dump(doc, open(os.path.join(BASE, 'out', 'etf_p15_check.json'), 'w'), ensure_ascii=False, indent=1)
    print('最大の差', worst, doc['判定'])


if __name__ == '__main__':
    main()
