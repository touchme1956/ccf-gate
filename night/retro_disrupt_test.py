#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_disrupt_test.py — ②『disrupt=unsettled』の機械代理を、**家族の値札つき**で測る（2026-09-21新設）

読むだけ。事前登録は out/retro_cliffs_prereg.json、採取は night/retro_disrupt_ft.py。
物差しは irr_rung_audit.py と同じ **lift = P(年15%+ | 該当) − P(年15%+ | 非該当)**。
家族の値札: **1回のシャッフルを全候補へ当てて最大|lift|を取る**帰無の95%点（候補どうしの相関を壊さない置換）。
向きは結果を見てから選ばない——**有る側・無い側の両方**を家族に入れる。
⚠ ヒット率が5%未満/95%超のフレーズは**構造的に検定不能**として落とさず明記する（dom=50 の96.6%と同じ形）。

使い方: python3 night/retro_disrupt_test.py
出力  : out/retro_disrupt_test.json
"""
import json, os, random, statistics as st, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RET = {2018: 'retro_returns_2018.json', 2013: 'retro_returns_2013_all.json'}
SHUFFLES = 2000
random.seed(20260921)   # 結果の再現性のため固定（探索には使わない）


def rows(n):
    d = json.load(open(os.path.join(BASE, 'out', n), encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def main():
    FT = json.load(open(os.path.join(BASE, 'out/retro_disrupt_ft.json'), encoding='utf-8'))
    keys = list(FT['phrases'].keys())
    out = {'generated': datetime.date.today().isoformat(), 'prereg': 'out/retro_cliffs_prereg.json',
           'metric': 'lift = P(年15%+ | 該当) − P(年15%+ | 非該当)', 'shuffles': SHUFFLES, 'vintages': {}}
    for v, rf in RET.items():
        F = FT['rows'].get(str(v))
        if not F:
            continue
        R = {r['ticker']: r['tr_cagr'] for r in rows(rf)
             if not r.get('stale') and r.get('tr_cagr') is not None}
        pool = [(t, R[t], F[t]) for t in F if t in R and not F[t].get('no10k')]
        n = len(pool)
        if n < 100:
            out['vintages'][str(v)] = {'n': n, 'skipped': '10-Kが窓内にある社が少なすぎる'}
            continue
        win = [1 if c >= .15 else 0 for _, c, _ in pool]
        # 候補 = フレーズ × {有る側, 無い側}（向きを後から選ばない）
        cands = []
        for k in keys:
            # ⚠ 採取失敗(None)は**非該当**として扱う——「取れなかった」を「有った」証拠にしない（絶対のルール7）
            sel = [1 if (r.get(k) == 1) else 0 for _, _, r in pool]
            cands.append((k + ' 有り', sel))
            cands.append((k + ' 無し', [1 - s for s in sel]))

        def lift(sel):
            A = [w for w, s in zip(win, sel) if s]; B = [w for w, s in zip(win, sel) if not s]
            if not A or not B:
                return None
            return sum(A) / len(A) - sum(B) / len(B)
        # 家族の帰無: 勝ち負けだけをシャッフルし、全候補の最大|lift|の分布を作る
        mx = []
        for _ in range(SHUFFLES):
            w = win[:]; random.shuffle(w)
            best = 0.0
            for _, sel in cands:
                A = [x for x, s in zip(w, sel) if s]; B = [x for x, s in zip(w, sel) if not s]
                if not A or not B:
                    continue
                best = max(best, abs(sum(A) / len(A) - sum(B) / len(B)))
            mx.append(best)
        mx.sort()
        fam = mx[int(.95 * len(mx))]
        res = {'n': n, 'base_p15': round(sum(win) / n, 3), 'family_null_p95': round(fam, 3), 'cands': []}
        for nm, sel in cands:
            hr = sum(sel) / n
            L = lift(sel)
            row = {'cand': nm, 'hit_rate': round(hr, 3), 'n_hit': sum(sel),
                   'lift': None if L is None else round(L, 3),
                   'testable': 0.05 <= hr <= 0.95,
                   'beats_family': (L is not None and abs(L) > fam and 0.05 <= hr <= 0.95)}
            res['cands'].append(row)
        res['cands'].sort(key=lambda r: -(abs(r['lift']) if r['lift'] is not None else -1))
        out['vintages'][str(v)] = res

    p = os.path.join(BASE, 'out/retro_disrupt_test.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for v, r in out['vintages'].items():
        if 'skipped' in r:
            print('\n■ %s年: %s' % (v, r['skipped'])); continue
        print('\n■ %s年ビンテージ  n=%d  基礎率 P(15%%+)=%.3f  **家族の帰無95%%点 %.3f**'
              % (v, r['n'], r['base_p15'], r['family_null_p95']))
        print('  %-28s%9s%9s%9s  %s' % ('候補', 'ヒット率', '該当', 'lift', '判定'))
        for c in r['cands']:
            mk = '**家族を超えた**' if c['beats_family'] else ('—' if c['testable'] else '検定不能(ヒット率が端)')
            print('  %-28s%9.3f%9d%9s  %s' % (c['cand'], c['hit_rate'], c['n_hit'],
                                              ('%+.3f' % c['lift']) if c['lift'] is not None else '—', mk))
    print('\n⚠ 2ビンテージしか作れない＝**採用基準（3ビンテージで符号が反転しない）を原理的に満たせない**。')
    print('   最良でも「棄却できない」までで、採用の根拠にはならない（事前登録に明記済み）。')


if __name__ == '__main__':
    main()
