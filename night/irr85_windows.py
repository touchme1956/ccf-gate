#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_windows.py — **「実績の窓」を5つに広げ、重なりを外して前半だけを復元する**（2026-08-09新設）

発端（ユーザーの問い「実績の窓は他のチャットで一回調べたんだけど追える?」）:
  追えた。**この repo には既に5つの窓が在庫としてある**——2026-08-04〜05 の別セッションが作ったもの:
    out/retro_returns_2013_all.json (13.09年・956社) ／ _2015_q.json (11.10年・506社) ／
    _2016.json (10.09年) ／ _2017.json (9.09年) ／ _2018.json (8.09年)
  irr の読解も 2013/2015/2018 の3ビンテージぶんある（out/retro_moat_*.json）。

⚠ **5つの窓はすべて2026で終わるので重なっている。** 13.09年の窓と8.09年の窓は
  最後の8.09年を共有するので、「5つの窓で安定していた」は独立な5つの証拠ではない。
  → **重ならない前半だけを復元する**:
      (1+r13)^13.09 = (1+r_前半)^5.0 × (1+r18)^8.09
      ⇒ r_前半 = [(1+r13)^13.09 ÷ (1+r18)^8.09]^(1/5) − 1
  これで **2013→2018（AI相場の前）** と **2018→2026（AI相場）** を分離できる。

**この道具が出した最大の結果**（2026-08-09）:
  今日の irr=85 で実績が追える11社のうち **10社は AI相場の前(2013-2018)のほうが良かった**。
  唯一 LRCX だけが後半で伸びた(+11.1pt)。同じ期間に **SPY は 12.9% → 15.0% と後半のほうが良い**ので、
  「この群はAI相場の追い風で嵩上げされていた」という読みは**ほぼ全社で逆**だった。

使い方: python3 night/irr85_windows.py [--json]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
# CLAUDE.md 記載の実測（歴史検証の同期間の指数）
SPY = {'2013': 0.142, '2018': 0.150}
FILES = [('2013(13.1年)', 'out/retro_returns_2013_all.json'),
         ('2015(11.1年)', 'out/retro_returns_2015_q.json'),
         ('2016(10.1年)', 'out/retro_returns_2016.json'),
         ('2017(9.1年)', 'out/retro_returns_2017.json'),
         ('2018(8.1年)', 'out/retro_returns_2018.json')]
MOAT = [('2013', 'out/retro_moat_2013.json'), ('2013', 'out/retro_moat_2013q.json'),
        ('2015', 'out/retro_moat_2015.json'), ('2015', 'out/retro_moat_2015q.json'),
        ('2015', 'out/retro_moat_2015qb.json'), ('2018', 'out/retro_moat_2018.json'),
        ('2018', 'out/retro_moat_2018_rest.json')]


def pre(r_long, y_long, r_short, y_short):
    """重なりを外した前半の年率"""
    return ((1 + r_long) ** y_long / (1 + r_short) ** y_short) ** (1 / (y_long - y_short)) - 1


def main():
    import glob
    today = []
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        x = x.get('data') or x
        if x.get('irr') == 85:
            today.append(t)
    W = []
    for tag, f in FILES:
        if os.path.exists(f):
            W.append((tag, {r['ticker']: (r['tr_cagr'], r['years'])
                            for r in json.load(open(f, encoding='utf-8'))['rows']}))
    M = {}
    for tag, f in MOAT:
        if not os.path.exists(f):
            continue
        for r in json.load(open(f, encoding='utf-8'))['rows']:
            k = r.get('ticker') or r.get('t')
            v = r.get('irr') if 'irr' in r else r.get('irr18')
            if v is not None:
                M.setdefault(k, {})[tag] = v

    print('■ 実績の窓は5つある（すべて配当込み年率・在庫は2026-08-04〜05の別セッションが作成）')
    print(f"  {'':<6}" + ''.join(f'{t:>13}' for t, _ in W) + '   irr=85 と読まれた年')
    for t in today:
        row = ''
        for _, d in W:
            v = d.get(t)
            row += (f'{v[0]*100:>12.1f}%' if v else f"{'—':>13}")
        p85 = sorted({y for y, v in M.get(t, {}).items() if v == 85})
        print(f"  {t:<6}{row}   {' '.join(p85) if p85 else '—'}")

    print('\n■ ★重なりを外す——5つの窓はすべて2026で終わるので独立ではない')
    print('  (1+r13)^13.09 = (1+r_前半)^5.0 × (1+r18)^8.09 で **2013→2018（AI相場の前）**を復元')
    A = dict(W)['2013(13.1年)']
    B = dict(W)['2018(8.1年)']
    print(f"\n  {'':<6}{'2013→2026':>11}{'2018→2026':>11}{'★2013→2018':>13}{'後半−前半':>11}")
    out = []
    for t in today:
        a, b = A.get(t), B.get(t)
        if not a or not b:
            print(f"  {t:<6}{'—':>11}{'—':>11}{'—':>13}{'—':>11}   （米国10-K経路の在庫に無い）")
            continue
        pr = pre(a[0], a[1], b[0], b[1])
        out.append((t, a[0], b[0], pr))
        print(f"  {t:<6}{a[0]*100:>10.1f}%{b[0]*100:>10.1f}%{pr*100:>12.1f}%{(b[0]-pr)*100:>10.1f}pt")
    sp = pre(SPY['2013'], 13.09, SPY['2018'], 8.09)
    print(f"  {'SPY':<6}{SPY['2013']*100:>10.1f}%{SPY['2018']*100:>10.1f}%{sp*100:>12.1f}%"
          f"{(SPY['2018']-sp)*100:>10.1f}pt  ← **指数は後半のほうが良い**")
    worse = [t for t, _, b, p in out if b < p]
    print(f"\n  → **{len(worse)}/{len(out)}社が AI相場の前(2013-2018)のほうが良かった**"
          f"（{' '.join(worse)}）")
    print('    指数が後半+2.1pt なのに、この群はほぼ全社が後半で落ちている＝')
    print('    **「AI相場の追い風で嵩上げされていた」という読みは、この群についてはほぼ全社で逆**')
    if AS_JSON:
        p = 'out/irr85_windows.json'
        json.dump({'generated': '2026-08-09', 'spy_pre': sp,
                   'rows': [{'t': t, 'r2013': a, 'r2018': b, 'pre': pr} for t, a, b, pr in out]},
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
