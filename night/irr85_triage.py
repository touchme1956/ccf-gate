#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_triage.py — **見つかった irr=85 の候補を「読む価値があるか」で仕分ける**（2026-08-08新設）

なぜ要るか:
  irr=85 は歴史でリターンと生死を分けた唯一の変数だが、**堀が強いだけでは買えない**。
  2026-08-07 の実測がそれを示している——台帳の irr=85 は12社あるのに投下可は3社で、
  残り9社は**堀ではなくΩで落ちている**（財務キル nde 4.34〜8.05 と複利停止キル）。
  だから新しく見つけた85候補も、**門2審査に回す前に「Ωが75に届きうるか」を測る**。
  これは kill_impact.py・audit_moat_gap.py と同じ作法＝**読む先を絞る道具**であって、
  読むこと自体が目的ではない。

何を出すか（候補1社ごと）:
  ・門0の7点スコアと病名（gate0_all.csv）＝機械のふるいをどこで落ちているか
  ・その社が既にパック化されているか
  ・**上限の見立て**: 門0のfailsから、Ω75に届く見込みを3段階で出す
      有望   … 門0 6-7点（ROIC・利益率・成長・FCF転換のいずれも大きくは欠けない）
      要検討 … 門0 4-5点、またはROIC単独fail
      低い   … 門0 0-3点（ROICが構造的に低い／営業赤字／FCFマイナス）
  ・母集団に無い社は「門0の穴」として別立てで出す（RBC・HOYAの前例）

使い方:
  python3 night/irr85_triage.py                     out/irr85_hunt_result.json を読む
  python3 night/irr85_triage.py --in <path>
"""
import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ARGV = sys.argv[1:]
SRC = 'out/irr85_hunt_result.json'
if '--in' in ARGV:
    SRC = ARGV[ARGV.index('--in') + 1]


def load_gate0():
    g = {}
    p = 'gate0_all.csv'
    if not os.path.exists(p):
        return g
    for r in csv.DictReader(open(p, encoding='utf-8-sig')):
        t = (r.get('ticker') or '').strip().upper()
        if t:
            g[t] = r
    return g


def outlook(row):
    """門0のスコアと病名から Ω75 への見込みを3段階で出す"""
    if row is None:
        return '母集団に無し', '門0の母集団に一行も無い＝落選ですらなく判定の土俵に上がっていない（RBC・HOYAの前例）'
    try:
        sc = int(row.get('score') or 0)
    except ValueError:
        sc = 0
    f = row.get('fails') or ''
    hard = any(k in f for k in ('営業赤字', 'FCFマイナス', '売上CAGR'))
    if sc >= 6:
        return '有望', f'門0 {sc}/7（fails: {f or "なし"}）'
    if sc >= 4 and not hard:
        return '要検討', f'門0 {sc}/7（fails: {f}）'
    if sc >= 4:
        return '要検討', f'門0 {sc}/7 だが構造的なfailを含む（fails: {f}）'
    return '低い', f'門0 {sc}/7（fails: {f}）＝ROICか利益の水準が構造的に足りない'


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f'{SRC} が無い。先に探索のワークフローを回すこと')
    d = json.load(open(SRC, encoding='utf-8'))
    surv = d.get('survived') or []
    refu = d.get('refuted') or []
    rows = d.get('rows') or []
    g0 = load_gate0()
    packed = {os.path.basename(p).replace('_gate_pack.json', '').upper()
              for p in glob.glob('out/*_gate_pack.json')}

    print('■ 全銘柄の irr=85 探索——反証を生き残った候補の仕分け')
    print(f'  読了 {d.get("read", len(rows))}社 ／ 85+と読まれた {d.get("proposed85", 0)}社 '
          f'／ **反証を生き残った {len(surv)}社**')
    print('  ※ irr=85 は母集団の1〜3%しか出ない稀なラベル（歴史実測）。空振りが基本\n')

    if not surv:
        print('  生き残りなし。')
    order = {'有望': 0, '要検討': 1, '母集団に無し': 2, '低い': 3}
    tri = []
    for s in surv:
        t = (s.get('ticker') or '').upper()
        ol, why = outlook(g0.get(t))
        tri.append(dict(s, t=t, outlook=ol, why=why, packed=t in packed))
    tri.sort(key=lambda z: (order.get(z['outlook'], 9), z['t']))

    for ol in ('有望', '要検討', '母集団に無し', '低い'):
        grp = [x for x in tri if x['outlook'] == ol]
        if not grp:
            continue
        print(f'\n── {ol}（{len(grp)}社）──')
        for x in grp:
            mark = '✓既存' if x['packed'] else '  新規'
            print(f'  {mark} {x["t"]:<7} irr={x.get("irr")}  機構={x.get("mech","")}')
            print(f'         {x["why"]}')
            q = (x.get('quote') or '').strip().replace('\n', ' ')
            if q:
                print(f'         「{q[:210]}」')

    if refu:
        print(f'\n── 反証で落ちた {len(refu)}社（誤りの型ごと）──')
        from collections import Counter
        c = Counter(r.get('failureMode') or '不明' for r in refu)
        for k, v in c.most_common():
            names = ' '.join(r['ticker'] for r in refu if (r.get('failureMode') or '不明') == k)
            print(f'  {k}: {v}社  {names[:120]}')

    print('\n■ 次の一手')
    print('  「有望」と「母集団に無し」だけを門2審査に回す。')
    print('  **堀が強いだけでは買えない**——2026-08-07の実測では台帳の irr=85 は12社あるのに投下可は3社で、')
    print('  残り9社は堀(73.6〜87.8で全社が関門70超)ではなく**Ωで落ちている**（財務キル nde 4.34〜8.05・複利停止キル）。')

    out = 'out/irr85_hunt_triage.json'
    json.dump(dict(generated='2026-08-08', survived=tri, refuted=refu),
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n→ {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
