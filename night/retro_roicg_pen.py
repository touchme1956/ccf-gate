#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_roicg_pen.py — **門の `roicg<WACC → −8`（のれん込みROICが資本コスト割れ）を歴史で検定する**
（2026-09-21新設・ユーザーの問い「買収はマイナスのケースが多いの？ 検討もせずにマイナスにするのもおかしい」）

■ 何を測るか（**読むだけ。採点・規約・合否には一切触れない**）
  門は `if(roicg && roicg<wacc && roicg>0){ amberPen+=8 }` で **−8 の減点**を置いている
  （キルではない）。⚠**この罰に `acq5` の条件は無い**——買収の罰ではなく「のれんを分母に入れた
  資本利益率が資本コストを割る」ことへの罰で、買収した社に効くのは**のれんが分母を膨らませるから**。

■ 二段で測る（**一段目だけ見て結論しない**のがこの道具の要）
  ① 粗い代理: NOPAT/総資産 < 8%  ＝「のれん込みの資本利益率が資本コスト割れ」全般
  ② **門の罰が狙う群を直接作る**: のれん除外 ≥8% **かつ** のれん込み <8%
     ＝「**事業は稼いでいるが、払った代金は稼いでいない**」。対照は同じ『事業が稼ぐ』群の中で代金も稼ぐ社。
  **①が合格でも②が落ちるなら、罰は当たっている的が違う**（実測でそうなった）。

■ 事前登録（2026-09-21・結果を見る前に固定）
  物差し: retro_features2_{年} の `opm × aturn × (1−0.21)` ＝ NOPAT/総資産（**roicg の代理**）
          のれん除外は `÷(1−gw_r)`。⚠ roicg の真の分母は(自己資本+有利子負債)で総資産より小さいので、
          **この代理は roicg を過小に見る＝罰の対象を広めに取る（保守側）**。
  線:     **8%**＝門の WACC の典型値。**探索しない**（刻みを振ったら家族の値札を付け直すこと）。
  採用の線（v9.9.98/99 の遮断器の作法をそのまま借用）:
          **(a)止めた群の中央値が低い ∧ (b)止めた群の恒久毀損が濃い** の**両方向**。
          かつ **2013/2015/2018 の3ビンテージで符号が反転しない**（「少しずつ鈍化」を退けた線と同じ）。
  指標:   実現年率(配当込み tr_cagr)の中央値 ／ P(年15%+) ／ 恒久毀損 P(年率≤−15%)

■ 限界（先に書く）
  代理であること／窓はすべて2026年終点／2013と2015はコホートが重複＝真のOOSはゼロ／
  ②の群は n=73/56/112 と薄い／生存バイアスは既記録のまま。

使い方: python3 night/retro_roicg_pen.py [--json]
出力  : out/retro_roicg_pen.json
"""
import json, os, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAX, LINE = 0.21, 0.08
SETS = {2013: ('retro_features2_2013.json', 'retro_returns_2013_all.json'),
        2015: ('retro_features2_2015.json', 'retro_returns_2015_q.json'),
        2018: ('retro_features2_2018.json', 'retro_returns_2018.json')}


def rows(name):
    d = json.load(open(os.path.join(ROOT, 'out', name), encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def load(y):
    F = {r['ticker']: r for r in rows(SETS[y][0])}
    R = {r['ticker']: r for r in rows(SETS[y][1])}
    out = []
    for t, f in F.items():
        r = R.get(t)
        opm, at, gw = f.get('opm'), f.get('aturn'), f.get('gw_r')
        if not r or r.get('tr_cagr') is None or r.get('stale'):
            continue
        if opm is None or at is None:
            continue
        nopa = opm * at * (1 - TAX)                     # NOPAT/総資産 ≒ roicg
        # ⚠ のれんが総資産の95%以上の社は除外——(1−gw) が0へ縮退して除外ROICが発散する
        #   （絶対のルール7「分母の縮退」と同じ型。0と欠測を区別するのと同じ作法）
        nox = nopa / (1 - gw) if (gw is not None and gw < 0.95) else None
        out.append({'t': t, 'g': nopa, 'x': nox, 'gw': gw, 'cagr': r['tr_cagr']})
    return out


def stat(g):
    c = [x['cagr'] for x in g]
    if not c:
        return None
    return {'n': len(g), 'med': round(st.median(c) * 100, 1),
            'p15': round(sum(1 for v in c if v >= .15) / len(c), 3),
            'dmg': round(sum(1 for v in c if v <= -.15) / len(c), 3)}


def main():
    out = {'generated': __import__('datetime').date.today().isoformat(),
           'line': LINE, 'tax': TAX, 'note': __doc__.strip().splitlines()[1], 'blocks': {}}
    for label, pick in (('broad', 'broad'), ('targeted', 'targeted')):
        blk, ok = {}, []
        for y in SETS:
            d = load(y)
            if pick == 'broad':
                bad = [x for x in d if x['g'] < LINE]
                good = [x for x in d if x['g'] >= LINE]
            else:
                base = [x for x in d if x['x'] is not None and x['x'] >= LINE]
                bad = [x for x in base if x['g'] < LINE]
                good = [x for x in base if x['g'] >= LINE]
            a, b = stat(bad), stat(good)
            if not a or not b:
                continue
            med_ok, dmg_ok = a['med'] < b['med'], a['dmg'] > b['dmg']
            blk[y] = {'stopped': a, 'passed': b, 'median_lower': med_ok, 'damage_denser': dmg_ok,
                      'conc': round(a['dmg'] / b['dmg'], 2) if b['dmg'] else None}
            ok.append(med_ok and dmg_ok)
        blk['verdict'] = 'PASS' if (ok and all(ok)) else 'FAIL'
        out['blocks'][label] = blk
    p = os.path.join(ROOT, 'out', 'retro_roicg_pen.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return
    for label, jp in (('broad', '① 粗い代理: のれん込み<8% 全般'),
                      ('targeted', '② ★門の罰が狙う群: 除外≥8% かつ 込み<8%（事業は稼ぐが代金は稼がない）')):
        blk = out['blocks'][label]
        print(f'\n{jp}   判定: **{blk["verdict"]}**')
        print(f"  {'年':<6}{'止めた側 n/中央値/毀損':<30}{'通した側 n/中央値/毀損':<30}{'両方向':>8}")
        for y in SETS:
            if y not in blk: continue
            r = blk[y]; a, b = r['stopped'], r['passed']
            both = '✓' if (r['median_lower'] and r['damage_denser']) else '✗'
            ca = '{} / {}% / {}'.format(a['n'], a['med'], a['dmg'])
            cb = '{} / {}% / {}'.format(b['n'], b['med'], b['dmg'])
            print('  {:<6}{:<30}{:<30}{:>8}'.format(y, ca, cb, both))
    print('\n⇒ ①が合格・②が不合格なら、**罰は「低ROA全般」を当てており、'
          '「事業は稼ぐが代金は稼がない」を当てていない**')
    print('※ この道具は読むだけ。規約の改定は絶対のルール1の領分（ユーザー明示指示）')


if __name__ == '__main__':
    main()
