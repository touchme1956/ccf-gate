#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_acq_good.py — **「良い買収なら罰さない」を規約にしたら誰がどう動くか**（2026-08-08新設）

なぜ要るか（ユーザーの意向「買収した会社が良ければこの銘柄の門を通そうと思う」）:
  今の罰は `roicGap>15pt ∧ acq5='yes'` で、**乖離の絶対pt**で発火する。
  ところがこの線は**roicの水準が高いほど機械的に開く**（CLAUDE.md 2026-08-03 に記録済み）——
  APHは買収後に roicg が **15.6→17.6〜19.8% と改善している**のに、
  roic が 39.8→52.6 とそれ以上に上がるので乖離が 24.2→35.0pt へ**広がり、罰が部分罰3.68から満額6になる**。
  ＝**買収が稼ぐようになったのに罰が重くなる**。ここが「良い買収は通す」という思想と食い違う。

  そこで「良い」を門の言葉で定義して測る。門は既に `roicg < WACC → −8` を持っているので、
  **良い買収＝roicg ≥ WACC（払った代金を全部分母に入れても資本コストを超える）** が自然な定義。

測る案（いずれも影の計測。正本のパックは必ず元へ戻す）:
  A 現行
  B **roicg ≥ WACC なら roicGap の罰を免除**（＝良い買収は罰さない）
  C **罰を比で測る**: roic ÷ roicg > 2.0 のときだけ発火（絶対ptの水準依存を外す）
  D B と C の両方

使い方: python3 night/shadow_acq_good.py [--write] [--wacc 8.93]
"""
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ARGV = sys.argv[1:]
WRITE = '--write' in ARGV
WACC = float(ARGV[ARGV.index('--wacc') + 1]) if '--wacc' in ARGV else 8.93
OUT, BAK = 'out', '/tmp/_shadow_acq_good_bak'


def packs():
    return sorted(glob.glob(os.path.join(OUT, '*_gate_pack.json')))


def score():
    subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    return {r['t']: r for r in json.load(open(os.path.join(OUT, 'score_all.json'), encoding='utf-8'))}


def snap(sa):
    return {t: (r.get('s'), r.get('moat'), r.get('buy'), r.get('quali')) for t, r in sa.items()}


def apply(rule):
    """rule(roic, roicg) -> True なら罰を免除する（acq5 を 'no' に落とす）"""
    n = []
    for p in packs():
        d = json.load(open(p, encoding='utf-8'))
        x = d.get('data') or d
        ro, rg = x.get('roic'), x.get('roicg')
        if str(x.get('acq5')) != 'yes':
            continue
        if not (isinstance(ro, (int, float)) and isinstance(rg, (int, float))):
            continue
        if ro - rg <= 15:
            continue                      # そもそも罰が出ていない
        if rule(ro, rg):
            x['acq5'] = 'no'
            json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            n.append(os.path.basename(p).split('_gate_pack')[0])
    return n


def diff(base, now, label, freed):
    moved = [(t, base[t], now[t]) for t in base if t in now and base[t][0] != now[t][0]]
    bb = sorted(t for t in base if base[t][2])
    nb = sorted(t for t in now if now[t][2])
    q0 = sum(1 for t in base if base[t][3])
    q1 = sum(1 for t in now if now[t][3])
    print(f'\n  【{label}】罰を免除した {len(freed)}社: {" ".join(sorted(freed)) or "—"}')
    for t, a, b in sorted(moved, key=lambda z: -((z[2][0] or 0) - (z[1][0] or 0)))[:12]:
        print(f'     {t:<7} Ω {a[0]:>5} → {b[0]:>5} ({(b[0] or 0)-(a[0] or 0):+.1f})')
    print(f'     四関門通過(資格) {q0}社 → {q1}社 ／ 投下可 {len(bb)} → {len(nb)}社'
          f' ／ 出 {" ".join(sorted(set(bb)-set(nb))) or "—"} ／ 入 {" ".join(sorted(set(nb)-set(bb))) or "—"}')
    return dict(freed=sorted(freed), quali=[q0, q1], buy_before=bb, buy_after=nb)


def main():
    base = snap(score())
    print(f'■ 「良い買収なら罰さない」の影の計測（WACC={WACC}）')
    print('  現行の罰: 乖離(roic−roicg)>15pt ∧ acq5=yes → v9.9.93の段階減点（15pt→0 / 30pt→6）')

    shutil.rmtree(BAK, ignore_errors=True)
    os.makedirs(BAK)
    for p in packs():
        shutil.copy(p, os.path.join(BAK, os.path.basename(p)))

    cases = [
        ('B roicg≥WACC なら免除（良い買収は罰さない）', lambda ro, rg: rg >= WACC),
        ('C 罰を比で測る（roic÷roicg>2.0 のときだけ発火）', lambda ro, rg: not (rg > 0 and ro / rg > 2.0)),
        ('D B∧C の両方', lambda ro, rg: rg >= WACC or not (rg > 0 and ro / rg > 2.0)),
    ]
    res = {}
    try:
        for label, rule in cases:
            for f in os.listdir(BAK):
                shutil.copy(os.path.join(BAK, f), os.path.join(OUT, f))
            freed = apply(rule)
            res[label[0]] = diff(base, snap(score()), label, freed)
    finally:
        for f in os.listdir(BAK):
            shutil.copy(os.path.join(BAK, f), os.path.join(OUT, f))
        after = snap(score())
        print(f'\n（パックと score_all.json を元へ戻した — 完全一致: '
              f'{all(base[t] == after[t] for t in base)}）')

    print('\n■ 読み方')
    print('  ・**Bは門の中に既にある言葉で「良い」を定義している**——`roicg<WACC → −8` の線と同じ WACC。')
    print('    新しい定数を発明していない（E[r]点の錨と同じ作法）')
    print('  ・**Cは別の病気を治す**——絶対ptの罰は roic の水準が高いほど機械的に開く。')
    print('    ただし線(2.0)は新しい定数で、較正の材料が無い（2026-08-03に同じ理由で見送っている）')
    print('  ・**どちらもΩと買付を動かす＝絶対のルール1の領分。ユーザーの明示指示が要る**')

    if WRITE:
        p = os.path.join(OUT, 'shadow_acq_good.json')
        json.dump(dict(generated='2026-08-08', wacc=WACC, result=res),
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
