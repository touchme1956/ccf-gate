#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_roicg_incremental.py — 「のれん込みROIC(roicg)には、除外ROIC(roic)が持っていない情報が残っているか」
（2026-09-21新設・ユーザーの問い「acqS5 の帯 / ROIC≤WACC キルを門に入れたら？」への測定）

**読むだけ。採点・規約・合否には一切触れない。**

■ なぜこれを測るのか
  v9.9.182/183 で roicg を使う罰を2本とも撤去した結果、**門から「買った資産が稼いでいるか」を
  見る規則がゼロ**になった。埋めるとしたら候補は `roicg ≤ WACC` を**キル**に置くことだが、
  歴史は二つの顔を見せている（retro_roicg_pen.py・2026-09-21）:
    ① 粗い群（のれん込み<8% 全般）           → **PASS**（3ビンテージとも毀損が濃い）
    ② 狙った群（除外≥8% かつ 込み<8%）       → **FAIL**（3つ中2つで符号反転）
  ⇒ **①が通るのは、その大半が「除外ROICも低い社」＝既に ROIC≤WACC キルが捕まえている社だから**
  という仮説が立つ。そうなら roicg を足しても**新しく捕まるのは②＝落ちた群だけ**になる。

■ 測り方（retro_cliffs_test.py と同じ代理・同じ線・同じ母集団）
  nopa = opm × aturn × (1−0.21) ≒ roicg（のれん込み）／ nox = nopa/(1−gw_r) ≒ roic（除外）
  線は 8%（門のWACCの典型値・探索しない）。gw_r≥0.95 は分母縮退で除外（絶対のルール7）。

使い方: python3 night/retro_roicg_incremental.py
出力  : out/retro_roicg_incremental.json
"""
import json, os, statistics as st, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAX, LINE = 0.21, 0.08
SETS = {2013: ('retro_features2_2013.json', 'retro_returns_2013_all.json'),
        2015: ('retro_features2_2015.json', 'retro_returns_2015_q.json'),
        2018: ('retro_features2_2018.json', 'retro_returns_2018.json')}


def rows(n):
    d = json.load(open(os.path.join(ROOT, 'out', n), encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def load(y):
    F = {r['ticker']: r for r in rows(SETS[y][0])}
    R = {r['ticker']: r['tr_cagr'] for r in rows(SETS[y][1])
         if not r.get('stale') and r.get('tr_cagr') is not None}
    out = []
    for t, f in F.items():
        if t not in R:
            continue
        opm, at, gw = f.get('opm'), f.get('aturn'), f.get('gw_r')
        if opm is None or at is None or gw is None or gw >= 0.95:
            continue
        nopa = opm * at * (1 - TAX)
        out.append({'t': t, 'inc': nopa, 'ex': nopa / (1 - gw), 'cagr': R[t]})
    return out


def stat(g):
    c = [x['cagr'] for x in g]
    if not c:
        return None
    return {'n': len(c), 'med': round(st.median(c) * 100, 1),
            'dmg': round(sum(1 for v in c if v <= -.15) / len(c), 3)}


def main():
    out = {'generated': datetime.date.today().isoformat(), 'line': LINE, 'vintages': {}}
    print('■ のれん込み(roicg)≤8% の群は、どれだけ「除外(roic)≤8%」と重なっているか\n')
    print('%-6s %10s %12s %14s %10s' % ('年', '込み≤8%', 'うち除外も≤8%', '重なり', '新しく捕まる'))
    for y in SETS:
        d = load(y)
        inc_bad = [x for x in d if x['inc'] <= LINE]
        both = [x for x in inc_bad if x['ex'] <= LINE]
        only = [x for x in inc_bad if x['ex'] > LINE]     # ＝②の群（除外は稼ぐが込みで割る）
        ex_bad = [x for x in d if x['ex'] <= LINE]
        ex_ok = [x for x in d if x['ex'] > LINE]
        ov = len(both) / len(inc_bad) if inc_bad else 0
        print('%-6d %10d %12d %13.0f%% %10d' % (y, len(inc_bad), len(both), 100 * ov, len(only)))
        # 「新しく捕まる群」は、既存キルを通った社の中でどう振る舞ったか
        a, b = stat(only), stat([x for x in ex_ok if x['inc'] > LINE])
        out['vintages'][str(y)] = {
            'n': len(d), 'inc_bad': len(inc_bad), 'both': len(both), 'only_inc': len(only),
            'overlap': round(ov, 3), 'ex_bad': len(ex_bad),
            'increment_stopped': a, 'increment_passed': b,
            'median_lower': (a and b and a['med'] < b['med']),
            'damage_denser': (a and b and a['dmg'] > b['dmg'])}
    print('\n■ その「新しく捕まる群」（＝既存のROIC≤WACCキルを通った社のうち、のれん込みだけ割る社）は')
    print('  本当に悪かったか。対照は同じ『除外>8%』の中で込みも>8% の社\n')
    print('  %-6s%-28s%-28s%8s' % ('年', '新しく止める側 n/中央値/毀損', '通す側 n/中央値/毀損', '両方向'))
    ok = []
    for y in SETS:
        r = out['vintages'][str(y)]
        a, b = r['increment_stopped'], r['increment_passed']
        if not a or not b:
            continue
        both_ok = r['median_lower'] and r['damage_denser']
        ok.append(both_ok)
        print('  %-6d%-28s%-28s%8s' % (
            y, '{} / {}% / {}'.format(a['n'], a['med'], a['dmg']),
            '{} / {}% / {}'.format(b['n'], b['med'], b['dmg']), '✓' if both_ok else '✗'))
    out['verdict'] = 'PASS' if (ok and all(ok)) else 'FAIL'
    print('\n  判定: **%s**' % out['verdict'])
    p = os.path.join(ROOT, 'out/retro_roicg_incremental.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n→', p)
    print('※ この道具は読むだけ。規約の改定は絶対のルール1の領分（ユーザー明示指示）')


if __name__ == '__main__':
    main()
