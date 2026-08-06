#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_cliffs.py — **崖3件を外したら誰がどう動くか**の影の計測（2026-08-06新設）

対象（2026-08-06のユーザー明示指示「3つともやって」で当てることになった3件）:
  A. geopol の 85 の崖   `geopolPen = evalScore>=85 ? basePen*1.15 : basePen`
     → コメントは「崖(ハードキャップ)でなく連続ペナルティで序列情報を保存」と宣言しているのに
       次の行で崖を作っていた。実測 KLAC(geopol=2) は f1 を 90→95 に上げると Ω が 81.4→81.0 と**下がる**
  B. roicGap の 6点の崖  `roicGap>15 ∧ acq5='yes' → amberPen+=6`
     → 全362社のうち **181社(50%)** で「roicを上げるとΩが下がる」を作っていた
  C. 配分の錨            `合成点=(Ω−70)×E[r]点÷50`
     → Ω 76.4〜82.8（比1.08倍）を (Ω−70) 6.4〜12.8（比2.00倍）へ＝**相対差を12.5倍に増幅**。
       本文Ⅰの「ティア内の小数差に意味はなく、選別は間（価格）が行う」と矛盾していた

作法（この repo の型）:
  index.html を退避 → 1案ずつ差し替え → score_all を回す → **必ず元へ戻す**。
  正本の採点は一切変えない。当てるかどうかは別の作業。

使い方:
  python3 night/shadow_cliffs.py            A/B/C を単独と全部入りで測る
  python3 night/shadow_cliffs.py --only B   1案だけ
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
BAK = HTML + '.shadow_bak'
SCORE = os.path.join(ROOT, 'out', 'score_all.json')
SCORE_BAK = SCORE + '.shadow_bak'

# ── 差し替え定義 ────────────────────────────────────────────────────────────
A_OLD = "    geopolPen = evalScore>=85 ? basePen*1.15 : basePen;"
A_NEW = ("    geopolPen = basePen*(1+0.15*Math.max(0,Math.min(1,(evalScore-80)/10)));")

B_OLD = ("    else {amberPen+=6;ambers.push(`のれん込みROIC乖離${roicGap.toFixed(0)}pt"
         "——買収規律に疑義 −6`);}")
B_NEW = ("    else {const _gp=ramp(roicGap,[[15,0],[30,6]]);amberPen+=_gp;"
         "ambers.push(`のれん込みROIC乖離${roicGap.toFixed(0)}pt——買収規律に疑義 −${_gp.toFixed(1)}`);}")

C_OLD = "  return Math.max(0,((c&&c.s)||0)-70)*erP(c&&c.xEr)/50;"
C_NEW = "  return Math.max(0,((c&&c.s)||0))*erP(c&&c.xEr)/50;"

CASES = {
    'A': ('geopolの85の崖を連続へ', [(A_OLD, A_NEW)]),
    'B': ('roicGapの6点の崖を段階減点へ', [(B_OLD, B_NEW)]),
    'C': ('配分の錨を70→0へ', [(C_OLD, C_NEW)]),
    'ABC': ('3件すべて', [(A_OLD, A_NEW), (B_OLD, B_NEW), (C_OLD, C_NEW)]),
}


def run_score():
    subprocess.run(['node', 'night/score_all.js'], cwd=ROOT,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    with open(SCORE, encoding='utf-8') as f:
        return {r['t']: r for r in json.load(f)}


def erP(x):
    x = 2 if x is None else x
    return max(0, min(100, 50 + (x - 12) * 5))


def portfolio(rows, anchor):
    """投下可10社の目標ウェイトと総合リターン（城60%・網9%）"""
    buy = [r for r in rows.values() if r.get('buy')]
    sc = [(r['t'], max(0.0, (r['s'] or 0) - anchor) * erP(r.get('xEr')) / 50, r.get('xEr') or 0)
          for r in buy]
    tot = sum(s for _, s, _ in sc)
    if not tot:
        return None
    w = [(t, min(8.0, 60 * s / tot), e) for t, s, e in sc]
    castle = sum(x[1] for x in w)
    wer = sum(x[1] * x[2] for x in w) / castle if castle else 0
    total = castle / 100 * wer + (100 - castle) / 100 * 9.0
    return dict(castle=castle, wer=wer, total=total,
                lo=min(x[1] for x in w), hi=max(x[1] for x in w),
                names=[x[0] for x in sorted(w, key=lambda y: -y[1])])


def report(base, alt, label, anchor_base=70, anchor_alt=70):
    moved = []
    for t, b in base.items():
        a = alt.get(t)
        if not a:
            continue
        if abs((a['s'] or 0) - (b['s'] or 0)) >= 0.05:
            moved.append((t, b['s'], a['s'], a['s'] - b['s']))
    moved.sort(key=lambda x: -abs(x[3]))
    bb = set(t for t, r in base.items() if r.get('buy'))
    ab = set(t for t, r in alt.items() if r.get('buy'))
    q75b = sum(1 for r in base.values() if (r['s'] or 0) >= 75)
    q75a = sum(1 for r in alt.values() if (r['s'] or 0) >= 75)

    print(f'\n━━ {label} ━━')
    print(f'  Ωが動く社数 {len(moved)}   最大 {moved[0][3]:+.1f}pt ({moved[0][0]})' if moved
          else '  Ωが動く社数 0')
    for t, b, a, d in moved[:8]:
        print(f'      {t:<7} {b:5.1f} → {a:5.1f}  ({d:+.1f})')
    if len(moved) > 8:
        print(f'      …他{len(moved)-8}社')
    print(f'  Ω75+ {q75b} → {q75a}社')
    print(f'  投下可 {len(bb)} → {len(ab)}社', end='')
    if bb != ab:
        print(f'   出 {" ".join(sorted(bb-ab)) or "—"} ／ 入 {" ".join(sorted(ab-bb)) or "—"}')
    else:
        print('   顔ぶれ不変')
    pb, pa = portfolio(base, anchor_base), portfolio(alt, anchor_alt)
    if pb and pa:
        print(f'  城 {pb["castle"]:.1f}% → {pa["castle"]:.1f}%   '
              f'加重E[r] {pb["wer"]:.2f}% → {pa["wer"]:.2f}%   '
              f'総合 {pb["total"]:.2f}% → {pa["total"]:.2f}%  ({pa["total"]-pb["total"]:+.2f}pt)')
        print(f'  1銘柄の幅 {pb["lo"]:.1f}〜{pb["hi"]:.1f}% → {pa["lo"]:.1f}〜{pa["hi"]:.1f}%')
    return moved


def main():
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]

    src = open(HTML, encoding='utf-8').read()
    for name, (_, subs) in CASES.items():
        for old, _ in subs:
            if src.count(old) != 1:
                print(f'✗ 差し替え対象が一意でない（{name}）: {src.count(old)}件')
                return 1

    shutil.copy2(HTML, BAK)
    if os.path.exists(SCORE):
        shutil.copy2(SCORE, SCORE_BAK)
    try:
        print('■ 崖3件の影の計測（正本は最後に必ず戻す）')
        base = run_score()
        pb = portfolio(base, 70)
        print(f'\n基準: 投下可 {len([r for r in base.values() if r.get("buy")])}社 ／ '
              f'城 {pb["castle"]:.1f}% ／ 加重E[r] {pb["wer"]:.2f}% ／ 総合 {pb["total"]:.2f}%')

        for name, (label, subs) in CASES.items():
            if only and name != only:
                continue
            out = src
            for old, new in subs:
                out = out.replace(old, new, 1)
            open(HTML, 'w', encoding='utf-8').write(out)
            alt = run_score()
            anchor = 0 if 'C' in name else 70
            report(base, alt, f'案{name}: {label}', 70, anchor)
    finally:
        shutil.copy2(BAK, HTML)
        os.remove(BAK)
        if os.path.exists(SCORE_BAK):
            shutil.copy2(SCORE_BAK, SCORE)
            os.remove(SCORE_BAK)
        subprocess.run(['node', 'night/score_all.js'], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('\n✓ 正本 index.html と out/score_all.json を復元した')
    return 0


if __name__ == '__main__':
    sys.exit(main())
