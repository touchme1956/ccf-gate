#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_ref2013.py — **参照群を2013年ビンテージに固定して、今日の irr=85 を突き合わせる**（2026-08-09新設）

発端（ユーザー指示「irr85で2013からリターンをだした銘柄たちを参考にしてってこと」）:
  これまでの突合せは **2018年ビンテージ（8.1年・21社）**を参照群にしていた。
  2013年ビンテージは **13.1年**＝在庫で最も長い窓で、しかも
  **AI相場の前(2013-2018)と AI相場(2018-2026)の二つの時代を跨ぐ**。
  参照群としてはこちらのほうが「長い複利」の問いに合う。

**この道具が出した最大の結果**:
  2013年に irr=85 と読まれたのは **6社だけ**（LRCX CW RBC WST DLB CMTL）。
  そして **今日の厳格な試験（2026-08-05〜07の全数検算）が、この6社を実績で完全に二分した**——
    ・年15%+を出した4社（LRCX 39.1 / CW 25.8 / RBC 20.5 / WST 19.2）→ **今日も全社 irr=85**
    ・届かなかった2社（DLB +6.0 / CMTL −17.2）→ **今日は2社とも 70 へ降格済み**
  ⚠ 完全な盲検ではない——**CMTL は「歴史で唯一 irr=85 が壊れた社」として台帳に記録済み**だった。
     DLB の降格は 2026-08-07 の未審査7社パック化で機械的に出た（'sole source' が
     **当社の調達先**＝向きが逆）ので、こちらは結末を参照していない。

刻み別 P(13.1年で年15%+)（読解249社・ベース0.217）:
  50 **0.145**(n=186) < 70 **0.451**(n=51) < 85 **0.667**(n=6) ／ **100 は 0.000(n=4) で最下位**
  ——**irr=100 が最下位なのは 2013 / 2015 / 2018 の三ビンテージで一致**（規約の刻みの順序への反証）

使い方: python3 night/irr85_ref2013.py [--json] [--hurdle 0.15]
"""
import glob
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
H = float(sys.argv[sys.argv.index('--hurdle') + 1]) if '--hurdle' in sys.argv else 0.15
MOAT13 = ('out/retro_moat_2013.json', 'out/retro_moat_2013q.json')


def load():
    M = {}
    for f in MOAT13:
        if not os.path.exists(f):
            continue
        for r in json.load(open(f, encoding='utf-8'))['rows']:
            M[r.get('ticker') or r.get('t')] = r
    A = {r['ticker']: (r['tr_cagr'], r['years'])
         for r in json.load(open('out/retro_returns_2013_all.json', encoding='utf-8'))['rows']}
    B = {r['ticker']: (r['tr_cagr'], r['years'])
         for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    led = {}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        led[t] = (x.get('data') or x)
    return M, A, B, SA, led


def pre(t, A, B):
    """重ならない前半（2013→2018）を復元。窓が揃う社だけ（irr85_windows.py と同式）"""
    if t not in A or t not in B:
        return None
    a, ya = A[t]
    b, yb = B[t]
    if abs(ya - 13.09) > 0.2 or abs(yb - 8.09) > 0.2:
        return None
    return ((1 + a) ** ya / (1 + b) ** yb) ** (1 / (ya - yb)) - 1


def main():
    M, A, B, SA, led = load()
    read = {t: r for t, r in M.items() if t in A}
    g85 = sorted([t for t, r in read.items() if r.get('irr') == 85],
                 key=lambda z: -A[z][0])

    print(f'■ 参照群＝**2013年ビンテージの irr=85**（読解{len(read)}社中 **{len(g85)}社**・窓13.1年）')
    print(f"  {'':<6}{'13.1年実現':>11}{'前半13-18':>11}{'後半18-26':>11}  {'機構':<14}{'時制':<6} 今日のirr")
    for t in g85:
        r = read[t]
        p = pre(t, A, B)
        cur = led.get(t, {}).get('irr')
        mk = '（★実績と一致して降格）' if (A[t][0] < H and cur != 85) else ''
        print(f"  {t:<6}{A[t][0]*100:>10.1f}%{(f'{p*100:>10.1f}%' if p is not None else f'{chr(8212):>11}')}"
              f"{B[t][0]*100:>10.1f}%  {str(r.get('mech') or '—'):<14}{str(r.get('tense') or '—'):<6} "
              f"{cur if cur else '台帳外'}{mk}")
    w = [t for t in g85 if A[t][0] >= H]
    print(f"  中央値 {st.median([A[t][0] for t in g85])*100:.1f}% ／ 年{H:.0%}+ {len(w)}/{len(g85)}")
    print('  ★**継続した4社は今日も85・届かなかった2社は今日70**＝今日の厳格な試験が6社を実績で二分した')
    print('    ⚠ CMTL は「歴史で唯一壊れた85」として台帳に記録済み＝盲検ではない。')
    print('       DLB の降格は 2026-08-07 の機械的な読解（向きが逆）で、結末を参照していない')

    print(f'\n■ 2013年ビンテージ 刻み別 P(13.1年で年{H:.0%}+)')
    print(f"  {'irr':<8}{'n':>5}{'15%+':>6}{'率':>8}{'中央値':>9}{'リフト':>8}")
    base = sum(1 for t in read if A[t][0] >= H) / len(read)
    for lab in (100, 85, 70, 50):
        g = [t for t in read if read[t].get('irr') == lab]
        if not g:
            continue
        k = sum(1 for t in g if A[t][0] >= H)
        print(f"  {lab:<8}{len(g):>5}{k:>6}{k/len(g):>8.3f}"
              f"{st.median([A[t][0] for t in g])*100:>8.1f}%{k/len(g)/base:>7.1f}x")
    kk = sum(1 for t in read if A[t][0] >= H)
    print(f"  {'全体':<7}{len(read):>5}{kk:>6}{base:>8.3f}"
          f"{st.median([A[t][0] for t in read])*100:>8.1f}%{1.0:>7.1f}x")
    print('  → 50<70<85 は単調。**だが 100 は最下位**（2013/2015/2018 の三ビンテージで一致）')

    print(f'\n■ 今日の irr=85 を、この参照群の物差し（13.1年の実績）で並べる')
    print(f"  {'':<7}{'13.1年':>9}{'前半':>9}{'後半':>9}{'2013読解':>9}{'Ω':>7}{'堀':>7}  門  長い複利")
    cur = [t for t, x in led.items() if x.get('irr') == 85]
    rows = []
    for t in cur:
        a = A.get(t, (None,))[0]
        b = B.get(t, (None,))[0]
        p = pre(t, A, B)
        rows.append((t, a, p, b))
    rows.sort(key=lambda z: -(z[1] if z[1] is not None else -9))
    out = []
    for t, a, p, b in rows:
        sa = SA.get(t, {})
        stt = '🟢' if sa.get('buy') else ('🔵' if sa.get('quali') else '⛔')
        lg = ('★' if (p is not None and b is not None and p >= H and b >= H)
              else ('—' if p is not None else '追えない'))
        f = lambda v, w=9: (f'{v*100:>{w-1}.1f}%' if v is not None else f"{chr(8212):>{w}}")
        print(f"  {t:<7}{f(a)}{f(p)}{f(b)}{str(read.get(t, {}).get('irr') or '未読'):>9}"
              f"{str(sa.get('s')):>7}{str(sa.get('moat')):>7}  {stt}  {lg}")
        out.append(dict(t=t, r13=a, pre=p, r18=b, read2013=read.get(t, {}).get('irr'),
                        s=sa.get('s'), moat=sa.get('moat'), buy=bool(sa.get('buy'))))
    up = [t for t in cur if read.get(t, {}).get('irr') not in (None, 85)]
    print(f"\n  ・2013年には85でなかったのに今日85: {' '.join(up)}"
          f"（当時70）——いずれも実績は年14〜25%で、**降格ではなく当時の読みが保守的だった側**")
    print(f"  ・2013年に未読: {' '.join(t for t in cur if t not in read)}"
          "（ASML/VRSK/LOAR は米国10-K経路の在庫に実績も無い）")

    if AS_JSON:
        p = 'out/irr85_ref2013.json'
        json.dump({'generated': '2026-08-09', 'hurdle': H,
                   'ref85': [{'t': t, 'r13': A[t][0], 'pre': pre(t, A, B), 'r18': B.get(t, (None,))[0],
                              'mech': read[t].get('mech'), 'tense': read[t].get('tense'),
                              'irr_today': led.get(t, {}).get('irr')} for t in g85],
                   'today': out}, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
