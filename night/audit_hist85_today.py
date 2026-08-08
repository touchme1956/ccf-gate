#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_hist85_today.py — **歴史でリターンを出した irr=85 の社は、今日の門を通るか**（2026-08-08新設）

なぜ要るか（ユーザーの問い「過去リターンだしたirr85の銘柄たちは門をつうかするの？」）:
  この台帳は「irr=85 が継続組を分ける唯一の変数」を歴史で実測し、それを堀の規約の中心に置いた。
  ならば**当の21社が今日の門で何と言われるか**は、門そのものの較正になる。

  **ただし読み違えやすい。** 今日のΩは**今日の財務**で測った値であって、2018年時点の姿ではない。
  だからこの道具が出すのは「門が2018年に見逃したか」ではなく、
  「**8年走った後の同じ会社を、門は今どう見るか**」である。この二つを混同すると
  「基準の違う二つを割る」型をそのまま踏む。
  2018年時点で機械のふるいを通ったかは、同時に出す `retro_features2_2018.json` の側で見る。

出すもの:
  1. 21社の実現リターン(2018-07→2026-08・配当込み)と最大DD
  2. 今日のΩ・堀・irr・キル・nde・roicg と四関門の判定
  3. 落ちている社の死因の分類（財務キル／買収代金／堀不足／実際に壊れた／データ健全）
  4. 2018年時点で質実証(opm≥10% ∧ 5年FCF全年黒字)を満たしていたか＝当時の機械のふるいの通過

使い方: python3 night/audit_hist85_today.py [--json]
"""
import glob
import json
import os
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
WACC = 8.93  # 台帳の既定（roicg<WACC の−8 の線）


def pack(t):
    for p in glob.glob('out/*_gate_pack.json'):
        if os.path.basename(p).split('_gate_pack')[0] == t:
            d = json.load(open(p, encoding='utf-8'))
            return d.get('data') or d
    return None


def cause(s, x):
    """落ちている社の死因を一つに決める（門の判定順に合わせる）"""
    if s is None:
        return '台帳に無し'
    if s.get('buy'):
        return '—'
    if s.get('quali'):
        return '席外（資格あり）'
    if s.get('moat') is None:
        return 'データ健全（堀が算出不能）'
    if (s.get('kills') or 0) > 0:
        nde = (x or {}).get('nde')
        if isinstance(nde, (int, float)) and nde > 4:
            return '財務キル（nde>4）'
        return 'キル（複利停止ほか）'
    if (s.get('s') or 0) >= 75 and (s.get('moat') or 0) >= 70:
        return 'データ健全（点検/期末後/納品検査）'
    if (s.get('moat') or 0) < 70:
        return '堀不足'
    rg = (x or {}).get('roicg')
    if isinstance(rg, (int, float)) and rg < WACC:
        return "買収代金（roicg<WACC）"
    return 'Ω不足'


def main():
    if not os.path.exists('out/score_all.json'):
        subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    firms = json.load(open('out/retro_irr85_deep.json', encoding='utf-8'))['firms85']
    ret = {r['ticker']: r for r in
           json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    sa = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    F = {r['ticker']: r for r in
         json.load(open('out/retro_features2_2018.json', encoding='utf-8'))['rows']}

    rows = []
    for t in sorted(firms, key=lambda z: -(ret.get(z, {}).get('tr_cagr') or -9)):
        r, s, x, f = ret.get(t, {}), sa.get(t), pack(t), F.get(t)
        rows.append(dict(
            t=t, cagr=r.get('tr_cagr'), mdd=r.get('mdd'),
            s=(s or {}).get('s'), moat=(s or {}).get('moat'), kills=(s or {}).get('kills'),
            irr=(x or {}).get('irr'), nde=(x or {}).get('nde'), roicg=(x or {}).get('roicg'),
            buy=bool((s or {}).get('buy')), quali=bool((s or {}).get('quali')),
            cause=cause(s, x),
            q2018=(bool(f and f['opm'] >= 0.10 and f.get('fcfpos5') == 5) if f else None)))

    print('■ 2018年ビンテージで irr=85 と読まれた21社は、今日の門を通るか')
    print('  ※ **今日のΩは今日の財務**。2018年に門が見逃したかの検証ではない（8年走った後の姿）\n')
    print(f"  {'':<6}{'実現%/年':>9}{'DD':>6} | {'Ω':>6}{'堀':>6}{'irr':>4}{'kill':>5}"
          f"{'nde':>6}{'roicg':>7} {'18年質':>6}  判定／死因")
    for r in rows:
        j = '🟢投下可' if r['buy'] else ('🔵席外' if r['quali'] else '⛔' + r['cause'])
        print(f"  {r['t']:<6}{(r['cagr'] or 0)*100:>8.1f}%{(r['mdd'] or 0)*100:>5.0f}% | "
              f"{str(r['s']):>6}{str(r['moat']):>6}{str(r['irr']):>4}{str(r['kills']):>5}"
              f"{str(r['nde']):>6}{str(r['roicg']):>7} {('◎' if r['q2018'] else '—'):>6}  {j}")

    w = [r['cagr'] for r in rows if r['cagr'] is not None]
    print(f"\n  実現(8.1年・配当込み) 中央値 {statistics.median(w)*100:.1f}%/年 ／ "
          f"年15%+ {sum(1 for v in w if v >= .15)}/21社 ／ 元本割れ {sum(1 for v in w if v < 0)}社")
    print(f"  **今日の門: 投下可 {sum(1 for r in rows if r['buy'])}社 ／ 席外 "
          f"{sum(1 for r in rows if r['quali'] and not r['buy'])}社 ／ 不通過 "
          f"{sum(1 for r in rows if not r['quali'])}社**")
    print(f"  2018年時点で質実証(opm≥10% ∧ 5年FCF全年黒字)を満たしていた: "
          f"{sum(1 for r in rows if r['q2018'])}/21社")

    from collections import Counter
    c = Counter(r['cause'] for r in rows if not r['quali'])
    print('\n  死因の内訳: ' + ' ／ '.join(f'{k} {v}社' for k, v in c.most_common()))

    print('\n■ 読み方')
    print('  ・**irr=85 は「買ってよい」を意味しない。** 堀の関門を通っても、財務キル・買収代金・')
    print('    データ健全が独立に止める。この21社の中にも DD−74%(IPGP)・−77%(ROG) が実在する')
    print('  ・**当時は通っていた**（18/21が質実証◎）。今日落ちているのは8年の間に起きたこと——')
    print('    買収でレバレッジを載せた／買収代金が資本を膨らませた／事業が実際に壊れた')
    print('  ・**門が2018年に何を言ったかはこの道具では判らない**（定性採点を当時の原本でやり直す')
    print('    必要がある）。機械の背骨だけなら retro_cohort.py／backtest_core.py の領分')

    if AS_JSON:
        p = 'out/audit_hist85_today.json'
        json.dump(dict(generated='2026-08-08', rows=rows), open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
