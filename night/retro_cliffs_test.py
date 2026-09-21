#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_cliffs_test.py — 未検定の崖 ① `乖離>15pt ∧ acq5=yes` と ③ `ROIC≤WACC キル` を歴史で検定する
（2026-09-21新設・ユーザー指示「1.2.3を歴史検証」）

**読むだけ。採点・規約・合否には一切触れない。**
事前登録は `out/retro_cliffs_prereg.json`（**結果を見る前に**固定済み・git で日時が残っている）。
採用基準・代理・限界は retro_roicg_pen.py と同一（同じ器を使う＝基準の違う二つを作らない）。

使い方: python3 night/retro_cliffs_test.py [--json]
出力  : out/retro_cliffs_test.json
"""
import json, os, statistics as st, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAX, WACC, GAPLINE = 0.21, 0.08, 15.0
ACQ_GWG, ACQ_SPEND = 0.4286, 0.311     # acq5『のれんの30%が新しい』の同値 ／ acqS5『大きく買う』帯
RET = {2013: 'retro_returns_2013_all.json', 2015: 'retro_returns_2015_q.json',
       2016: 'retro_returns_2016.json', 2017: 'retro_returns_2017.json',
       2018: 'retro_returns_2018.json', 2019: 'retro_returns_2019.json',
       2020: 'retro_returns_2020.json', 2021: 'retro_returns_2021.json'}


def rows(name):
    d = json.load(open(os.path.join(ROOT, 'out', name), encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def load(y):
    F = {r['ticker']: r for r in rows('retro_features2_%d.json' % y)}
    R = {r['ticker']: r for r in rows(RET[y]) if not r.get('stale') and r.get('tr_cagr') is not None}
    out = []
    for t, f in F.items():
        if t not in R:
            continue
        opm, at, gw = f.get('opm'), f.get('aturn'), f.get('gw_r')
        if opm is None or at is None:
            continue
        nopa = opm * at * (1 - TAX)                       # NOPAT/総資産 ≒ roicg（のれん込み）
        # ⚠ のれんが総資産の95%以上は (1−gw) が0へ縮退して発散（絶対のルール7）
        nox = nopa / (1 - gw) if (gw is not None and gw < 0.95) else None
        out.append({'t': t, 'inc': nopa, 'ex': nox,
                    'gap': (nox - nopa) * 100 if nox is not None else None,
                    'cagr': R[t]['tr_cagr']})
    return out


def stat(g):
    c = [x['cagr'] for x in g]
    if not c:
        return None
    return {'n': len(c), 'med': round(st.median(c) * 100, 1),
            'p15': round(sum(1 for v in c if v >= .15) / len(c), 3),
            'dmg': round(sum(1 for v in c if v <= -.15) / len(c), 3)}


def judge(a, b):
    """採用の線: (a)中央値が低い ∧ (b)恒久毀損が濃い の両方向"""
    return {'stopped': a, 'passed': b,
            'median_lower': a['med'] < b['med'], 'damage_denser': a['dmg'] > b['dmg'],
            'conc': round(a['dmg'] / b['dmg'], 2) if b['dmg'] else None}


def block(name, jp, years, split):
    blk, ok = {}, []
    for y in years:
        try:
            d = load(y)
        except FileNotFoundError:
            continue
        res = split(y, d)
        if res is None:
            continue
        bad, good = res
        a, b = stat(bad), stat(good)
        if not a or not b or a['n'] < 20 or b['n'] < 20:
            blk[y] = {'skipped': '群が薄い（<20社）', 'n_stopped': len(bad), 'n_passed': len(good)}
            continue
        blk[y] = judge(a, b)
        ok.append(blk[y]['median_lower'] and blk[y]['damage_denser'])
    blk['verdict'] = 'PASS' if (ok and all(ok)) else ('FAIL' if ok else 'UNTESTABLE')
    blk['title'] = jp
    return name, blk


def main():
    GW = json.load(open(os.path.join(ROOT, 'out/retro_gwg_vintages.json')))['gwg']
    SP = json.load(open(os.path.join(ROOT, 'out/retro_acqspend.json')))
    PER, DIRTY = SP.get('per_company', {}), SP.get('dirty_tickers', {})

    def acquirers(y, kind):
        """買収した社の集合。**測れていない社（支出0だがのれん増）は両方の群から外す**"""
        dirty = set(DIRTY.get(str(y), []))
        if kind == 'gwg':
            return {t for t, v in (GW.get(str(y)) or {}).items() if v >= ACQ_GWG} - dirty
        return {t for t, v in (PER.get(str(y)) or {}).items() if v >= ACQ_SPEND} - dirty

    out = {'generated': datetime.date.today().isoformat(), 'prereg': 'out/retro_cliffs_prereg.json',
           'lines': {'wacc': WACC, 'gap_pt': GAPLINE, 'acq_gwg': ACQ_GWG, 'acq_spend': ACQ_SPEND},
           'blocks': {}}
    YG = [y for y in (2015, 2016, 2017, 2018, 2019, 2020, 2021) if str(y) in GW and len(GW[str(y)]) > 100]

    def sp_gap(kind):
        def f(y, d):
            A = acquirers(y, kind)
            base = [x for x in d if x['gap'] is not None and x['t'] in A]
            if not base:
                return None
            return ([x for x in base if x['gap'] > GAPLINE], [x for x in base if x['gap'] <= GAPLINE])
        return f

    def sp_gap_q(kind):
        """scale-free の副検定: 買収した社の中で gap 上位1/4 vs 残り（線を当てない）"""
        def f(y, d):
            A = acquirers(y, kind)
            base = sorted([x for x in d if x['gap'] is not None and x['t'] in A], key=lambda x: x['gap'])
            if len(base) < 40:
                return None
            k = len(base) * 3 // 4
            return (base[k:], base[:k])
        return f

    for nm, jp, ys, fn in [
        ('1_gap15_gwg', '① 乖離>15pt ∧ 買収した社（買収の印=のれん増 gwg≥0.43）', YG, sp_gap('gwg')),
        ('1_gap15_spend', '①- 同じ線・買収の印を**支出**に替えた版（spend≥0.311）', YG, sp_gap('spend')),
        ('1_gapQ_gwg', '①- scale-free 副検定: 買収した社の中で gap 上位1/4 vs 残り', YG, sp_gap_q('gwg')),
        ('3_roic_wacc', '③ ROIC≤WACC キル（のれん除外ROIC ≤ 8%）', [2013, 2015, 2018],
         lambda y, d: ([x for x in d if x['ex'] is not None and x['ex'] <= WACC],
                       [x for x in d if x['ex'] is not None and x['ex'] > WACC])),
    ]:
        k, v = block(nm, jp, ys, fn)
        out['blocks'][k] = v


    # ── 事後の切り分け（**事前登録に無い＝探索である**と明記して読む）──────────────
    # gap = nopa × gw_r/(1−gw_r) なので、**gap は「のれんの重み」と「収益性」の積**。
    # つまり同じのれん比率なら**収益性が高い社ほど gap が大きくなる**——門の roicGap も
    # 定義上まったく同じ性質を持つ（roic−roicg = NOPAT×(1/IC除外 − 1/IC込み)）。
    # ⇒ 「gapが大きい＝悪い」を検定すると、**収益性の高さを罰しているだけ**かもしれない。
    # そこで2つに割る: (i)のれんの重みだけ(gw_r) (ii)収益性だけ(nopa)。
    def sp_split(field, hi_is_stopped):
        def f(y, d):
            A = acquirers(y, 'gwg')
            base = [x for x in d if x['gap'] is not None and x['t'] in A]
            base.sort(key=lambda x: x[field] if field != 'gw' else (x['ex'] - x['inc']) / x['ex'] if x['ex'] else 0)
            if len(base) < 40:
                return None
            k = len(base) * 3 // 4
            return (base[k:], base[:k]) if hi_is_stopped else (base[:len(base) // 4], base[len(base) // 4:])
        return f
    for nm, jp, fn in [
        ('post_gwweight', '【事後・探索】買収した社の中で **のれんの重みだけ** 上位1/4 vs 残り', sp_split('gw', True)),
        ('post_profit', '【事後・探索】買収した社の中で **収益性(nopa)だけ** 上位1/4 vs 残り', sp_split('inc', True)),
    ]:
        k, v = block(nm, jp, YG, fn)
        out['blocks'][k] = v

    p = os.path.join(ROOT, 'out/retro_cliffs_test.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return
    for k, blk in out['blocks'].items():
        print('\n%s   判定: **%s**' % (blk['title'], blk['verdict']))
        print('  %-6s%-30s%-30s%8s' % ('年', '止めた側 n/中央値/毀損', '通した側 n/中央値/毀損', '両方向'))
        for y in sorted([x for x in blk if isinstance(x, int)]):
            r = blk[y]
            if 'skipped' in r:
                print('  %-6s%s（止 %d / 通 %d）' % (y, r['skipped'], r['n_stopped'], r['n_passed'])); continue
            a, b = r['stopped'], r['passed']
            both = '✓' if (r['median_lower'] and r['damage_denser']) else '✗'
            print('  %-6s%-30s%-30s%8s' % (y, '{} / {}% / {}'.format(a['n'], a['med'], a['dmg']),
                                           '{} / {}% / {}'.format(b['n'], b['med'], b['dmg']), both))
    print('\n※ 事前登録は out/retro_cliffs_prereg.json（結果を見る前に固定）。')
    print('※ ①の線は門の15ptを**総資産基準の代理へそのまま当てた**もので、門のIC基準とは別スケール。')
    print('   だから scale-free の副検定を併記してある。読むべきは**向き**であって線の再現ではない。')
    print('※ この道具は読むだけ。規約の改定は絶対のルール1の領分（ユーザー明示指示）')


if __name__ == '__main__':
    main()
