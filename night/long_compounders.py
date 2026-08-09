#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/long_compounders.py — **「長い複利」を、二つの別々の時代を両方通ったかで定義して測る**（2026-08-09新設）

発端（ユーザーの問い「過去に長い複利を達成した銘柄と同じようなやつはどれ？」）。

【なぜ新しい定義が要るか】
  これまでの検証は「2018→2026 の8.1年で年15%+」を継続の定義にしていた。
  だが **8年は「長い複利」ではない**——一つの相場を通っただけかもしれない。
  在庫の5つの窓はすべて2026で終わるので重なっており、そのままでは独立な証拠にならない。
  → `night/irr85_windows.py` と同じ操作で**重ならない前半を復元**し、
     **2013→2018（5.0年）と 2018→2026（8.09年）という二つの時代**に分ける。
     **「長い複利」＝その両方を年15%+で通り抜けたこと**（13.1年・二つの相場）。

【この定義が効いている証拠（2026-08-09の実測・941社）】
  ・該当は **80社＝8.5%** だけ。前半だけ262社／後半だけ118社＝**片方だけなら3倍以上いる**
  ・**SPYは入らない**（前半12.9% / 後半15.0%）——指数は前半で15%に届かない
  ・**irr の刻みがこれを予言する**: irr=85 **0.64**（7/11） / 70 0.25 / 50 0.18 /
    **未審査(台帳外) 0.05** ／ 全体 0.09。**irr=85 のリフトは 7.1倍**
  ・門の審査を通っていること自体が大きなふるい——台帳内 0.26 vs 台帳外 0.05

使い方: python3 night/long_compounders.py [--json] [--hurdle 0.15]
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
H = float(sys.argv[sys.argv.index('--hurdle') + 1]) if '--hurdle' in sys.argv else 0.15
SPY = (0.129, 0.150, 0.142)     # 前半 / 後半 / 通算（CLAUDE.md 記載の実測から復元）


def main():
    A = {r['ticker']: (r['tr_cagr'], r['years'])
         for r in json.load(open('out/retro_returns_2013_all.json', encoding='utf-8'))['rows']}
    B = {r['ticker']: (r['tr_cagr'], r['years'])
         for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    P = {}
    for t, (r13, y13) in A.items():
        if t not in B:
            continue
        r18, y18 = B[t]
        if abs(y13 - 13.09) > 0.2 or abs(y18 - 8.09) > 0.2:
            continue                      # 窓が揃う社だけ（DBD型の短い系列を混ぜない）
        P[t] = (((1 + r13) ** y13 / (1 + r18) ** y18) ** (1 / (y13 - y18)) - 1, r18, r13)
    L = {t: v for t, v in P.items() if v[0] >= H and v[1] >= H}

    led, SA = {}, {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        led[t] = (x.get('data') or x).get('irr')

    print(f'■ 「長い複利」＝2013→2018（5.0年）と 2018→2026（8.09年）の**二つの時代を両方とも年{H:.0%}+**')
    print(f'  対象 {len(P)}社 → 該当 **{len(L)}社（{len(L)/len(P):.1%}）**')
    a = sum(1 for v in P.values() if v[0] >= H > v[1])
    b = sum(1 for v in P.values() if v[1] >= H > v[0])
    print(f'  片方だけ: 前半だけ {a}社 ／ 後半だけ {b}社 ＝ **片方なら{(a+b)/len(L):.1f}倍いる**')
    print(f'  参考 SPY: 前半{SPY[0]:.1%} / 後半{SPY[1]:.1%} → **指数は前半で届かず、この群に入らない**')

    print(f'\n■ irr の刻みは「長い複利」を予言したか')
    print(f"  {'irr':<8}{'n':>5}{'該当':>6}{'率':>8}{'リフト':>8}")
    base = len(L) / len(P)
    for lab, sel in [('85', lambda t: led.get(t) == 85), ('70', lambda t: led.get(t) == 70),
                     ('50', lambda t: led.get(t) == 50), ('未審査', lambda t: t not in led)]:
        g = [t for t in P if sel(t)]
        if not g:
            continue
        k = sum(1 for t in g if t in L)
        print(f"  {lab:<8}{len(g):>5}{k:>6}{k/len(g):>8.2f}{k/len(g)/base:>7.1f}x")
    print(f"  {'全体':<7}{len(P):>5}{len(L):>6}{base:>8.2f}{1.0:>7.1f}x")

    print('\n■ 今日の投下可10社は「長い複利」組か')
    buy = [r['t'] for r in SA.values() if r.get('buy')]
    buy.sort(key=lambda t: -(P[t][2] if t in P else -9))
    for t in buy:
        if t not in P:
            print(f"  {t:<6} 実績が追えない（米国10-K経路の在庫に無い）")
            continue
        pr, po, al = P[t]
        mk = '★長い複利' if t in L else ('前半だけ（後半で減速）' if pr >= H else
                                       ('後半だけ' if po >= H else '—'))
        print(f"  {t:<6} 前半{pr*100:>6.1f}% ／ 後半{po*100:>6.1f}% ／ 通算{al*100:>6.1f}%   {mk}")

    inter = sorted(set(L) & set(led), key=lambda t: -L[t][2])
    print(f'\n■ 「長い複利」{len(L)}社のうち**今日の台帳にも居る** {len(inter)}社（通算の高い順）')
    print(f"  {'':<7}{'前半':>8}{'後半':>8}{'通算':>8}{'irr':>5}{'Ω':>7}{'堀':>7}  門")
    for t in inter:
        r = SA.get(t, {})
        pr, po, al = L[t]
        stt = '🟢投下可' if r.get('buy') else ('🔵次点' if r.get('quali') else '⛔')
        print(f"  {t:<7}{pr*100:>7.1f}%{po*100:>7.1f}%{al*100:>7.1f}%{str(led[t]):>5}"
              f"{str(r.get('s')):>7}{str(r.get('moat')):>7}  {stt}")

    if AS_JSON:
        p = 'out/long_compounders.json'
        json.dump({'generated': '2026-08-09', 'hurdle': H, 'n_universe': len(P),
                   'long': {t: {'pre': v[0], 'post': v[1], 'all': v[2]} for t, v in L.items()},
                   'in_ledger': inter}, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
