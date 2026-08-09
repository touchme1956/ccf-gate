#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_alloc_buckets.py — **配分を「枠(バケツ)」で切ったらどうなるか**を実測する（2026-08-09新設）

発端（ユーザーの提案）: 「irr85以上の枠を30% / 私の門を40% / ETFを30% はどうだろう？」
  今日の配分は **網(ETF)40% / 城60%・城の中は等ウェイト**（v9.9.96）。提案は城を二つの枠に割り、
  網を10pt削る形。**配分は門の外（DCA側）の決断**なので、ここでは測るだけで何も変更しない。

何を測るか（配分案は「総合リターン」だけで採点しない——v9.9.68 で自分が踏んだ循環を避ける）:
  1. **1銘柄あたりの重み** ——枠%を枠の中の社数で割った値。ここが本題。
     枠%が固定で社数が変動すると、**1銘柄の重みが勝手に動き ¼ケリー上限8%を破りうる**
  2. **上限違反** —— 8%（¼ケリー）を超える社が出るか
  3. **歴史の基礎率** —— out/retro_moat_durability.json の群平均で合成（等ウェイトの実現は
     構成銘柄の**算術平均**。中央値は「1社を選んだとき」の話なので合成に使わない）
  4. **半導体連鎖の集中** —— 城の30%上限(v9.9.117)は「席数の30%」で定義されている。
     枠で切ると席の意味が変わるので、**ウェイトで測り直す**
  5. **枠の頑健性** —— 枠の中の社数が1社増減したとき、1銘柄の重みがどれだけ跳ねるか

使い方: python3 night/shadow_alloc_buckets.py [--json]
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]

CAP = 8.0          # 1銘柄の上限（¼ケリー相当・v9.9.70 から不変）
AMI = 9.0          # 網(ETF)の想定年率。CLAUDE.md が一貫して使っている値
SEMI = {'ASML', 'LRCX', 'KLAC', 'AMAT', 'ONTO', 'ACMR', 'NVMI', 'MKSI', 'ENTG', 'TER', 'COHR', 'AEIS',
        'NVDA', 'TSM', 'AVGO', 'MU', 'INTC', 'ADI', 'TXN', 'NXPI', 'MPWR', 'SWKS', 'STM', 'MRVL',
        'QCOM', 'ARM', 'SNPS', 'CDNS',
        '6857', '6146', '6920', '8035', '6981', '6963', '4062', '4186', '7729'}


def load():
    if not os.path.exists('out/score_all.json'):
        subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    rows = json.load(open('out/score_all.json', encoding='utf-8'))
    buy = [r for r in rows if r.get('buy')]
    G = json.load(open('out/retro_moat_durability.json', encoding='utf-8'))['groups']
    return buy, G


def grp(r):
    irr = r.get('irr')
    return 'irr=85' if irr in (85, 100) else ('irr=70' if irr == 70 else 'irr=50')


def scheme_fixw(name, weights, buy, G, note='', semi_cap=0.30):
    """1銘柄の重みを固定する形（枠%ではなく per-name %を決め、残りは全部 網へ）。
       枠%固定と違い**社数が変わっても1銘柄の重みは動かない**——動くのは網の比率だけ。
       semi_cap: 城の中の半導体連鎖の上限（v9.9.117 と同じ 30%）。超えたら比例で削って網へ返す。"""
    rows = [{'t': r['t'], 'w': weights(r), 'irr': r.get('irr'), 's': r['s'], 'grp': grp(r),
             'semi': r['t'].upper() in SEMI} for r in buy]
    trim = []
    for _ in range(40):                                    # 上限を満たすまで比例で削る（単調なので収束する）
        city = sum(x['w'] for x in rows)
        semi = sum(x['w'] for x in rows if x['semi'])
        if not city or semi <= city * semi_cap + 1e-9:
            break
        # 半導体だけを比例で削る（削った分は網へ戻る＝城の比率が下がる）
        k = (semi_cap * (city - semi)) / ((1 - semi_cap) * semi)
        for x in rows:
            if x['semi']:
                x['w'] *= k
        trim.append(round(k, 3))
    city = sum(x['w'] for x in rows)
    semi = sum(x['w'] for x in rows if x['semi'])
    er = sum(x['w'] / 100 * G[x['grp']]['mean'] * 100 for x in rows) + max(0.0, 100 - city) / 100 * AMI
    out = {'name': name, 'note': note, 'buckets': [], 'rows': [], 'viol': [],
           'city': round(city, 1), 'ami': round(max(0.0, 100 - city), 1),
           'semi': round(semi, 1), 'semi_of_city': round(semi / city * 100, 1) if city else 0,
           'total': round(er, 2), 'trim': trim}
    for lab, pred in [('irr=85 の社', lambda x: x['irr'] in (85, 100)), ('その他', lambda x: x['irr'] not in (85, 100))]:
        mem = [x for x in rows if pred(x)]
        if not mem:
            continue
        w = sum(x['w'] for x in mem)
        out['buckets'].append({'b': lab, 'pct': round(w, 1), 'n': len(mem),
                               'w': round(w / len(mem), 2),
                               'rate': round(sum(G[x['grp']]['mean'] * 100 for x in mem) / len(mem), 2),
                               'names': [f"{x['t']}{x['w']:.1f}" for x in mem]})
    for x in rows:
        out['rows'].append({'t': x['t'], 'w': round(x['w'], 2), 'irr': x['irr'], 's': x['s'], 'grp': x['grp']})
        if x['w'] > CAP + 1e-9:
            out['viol'].append(f"{x['t']} {x['w']:.1f}%>{CAP}")
    return out


def scheme(name, buckets, buy, G, note=''):
    """buckets = [(枠名, 枠%, 判定関数)] ／ 残りは網へ"""
    out = {'name': name, 'note': note, 'rows': [], 'buckets': [], 'viol': [], 'semi': 0.0}
    used = 0.0
    er = 0.0
    for bn, bpct, pred in buckets:
        mem = [r for r in buy if pred(r)]
        n = len(mem)
        w = (bpct / n) if n else 0.0
        used += bpct if n else 0.0
        # 歴史の群平均で枠の期待を作る
        rate = 0.0
        for r in mem:
            rate += G[grp(r)]['mean'] * 100 / n if n else 0
        er += (bpct / 100) * rate
        out['buckets'].append({'b': bn, 'pct': bpct, 'n': n, 'w': round(w, 2),
                               'rate': round(rate, 2),
                               'names': [r['t'] for r in mem]})
        for r in mem:
            out['rows'].append({'t': r['t'], 'b': bn, 'w': round(w, 2), 'irr': r.get('irr'),
                                's': r['s'], 'grp': grp(r)})
            if w > CAP + 1e-9:
                out['viol'].append(f"{r['t']} {w:.1f}%>{CAP}")
            if r['t'].upper() in SEMI:
                out['semi'] += w
    ami = max(0.0, 100 - used)
    er += (ami / 100) * AMI
    out['ami'] = round(ami, 1)
    out['city'] = round(used, 1)
    out['total'] = round(er, 2)
    out['semi'] = round(out['semi'], 1)
    return out


def show(s):
    print(f"\n── {s['name']}")
    if s['note']:
        print(f"   {s['note']}")
    for b in s['buckets']:
        mark = '  ⚠上限超' if b['w'] > CAP + 1e-9 else ''
        print(f"   {b['b']:<22} 枠{b['pct']:>5.1f}%  {b['n']:>2}社  1銘柄 {b['w']:>5.2f}%{mark}"
              f"   群平均{b['rate']:>6.2f}%   {' '.join(b['names'])}")
    print(f"   {'網(ETF)':<22} 枠{s['ami']:>5.1f}%              （年{AMI}%と仮定）")
    soc = s.get('semi_of_city')
    if soc is None:
        soc = (s['semi'] / s['city'] * 100) if s['city'] else 0
    print(f"   → 城 {s['city']:.0f}% ／ **総合 {s['total']:.2f}%/年** ／ 半導体連鎖 {s['semi']:.1f}%"
          f"（城の {soc:.1f}%{'  ⚠上限30%超' if soc > 30.05 else ''}）"
          + (f" ／ ⚠1銘柄上限違反 {len(s['viol'])}件: {' '.join(s['viol'])}" if s['viol'] else ' ／ 1銘柄上限違反なし')
          + (f" ／ 半導体を{s['trim']}倍に削って網へ返した" if s.get('trim') else ''))


def main():
    buy, G = load()
    is85 = lambda r: r.get('irr') in (85, 100)
    not85 = lambda r: not is85(r)
    n85 = sum(1 for r in buy if is85(r))
    nOther = len(buy) - n85
    print('■ 配分を「枠」で切ったらどうなるか（**測るだけ。配分は門の外＝DCA側の決断で、門の採点は1点も動かない**）')
    print(f'  今日の投下可 {len(buy)}社 ＝ irr≥85 {n85}社 ／ その他 {nOther}社')
    print(f'  歴史の群平均（out/retro_moat_durability.json・2013+2015の542件）: '
          f"irr=85 {G['irr=85']['mean']*100:.2f}% ／ irr=70 {G['irr=70']['mean']*100:.2f}% ／ 網 {AMI}%")

    S = []
    S.append(scheme('A 現行（網40 / 城60・城の中は等ウェイト）',
                    [('城（投下可 全社）', 60.0, lambda r: True)], buy, G,
                    'v9.9.96。1銘柄 60÷10=6.0%'))
    S.append(scheme('B 提案（irr≥85 の枠30 / 門の残り40 / ETF30）',
                    [('irr≥85 の枠', 30.0, is85), ('門の残り', 40.0, not85)], buy, G,
                    'ユーザー提案'))
    S.append(scheme('C 提案の枠を入れ替え（irr≥85 40 / 門の残り30 / ETF30）',
                    [('irr≥85 の枠', 40.0, is85), ('門の残り', 30.0, not85)], buy, G,
                    '歴史の順序どおりに厚くした場合'))
    S.append(scheme('D 網だけ30へ（枠を作らず等ウェイトのまま）',
                    [('城（投下可 全社）', 70.0, lambda r: True)], buy, G,
                    '1銘柄 70÷10=7.0%（上限8%の内側）'))
    S.append(scheme('E 1銘柄8%固定・残りを網へ（＝上限に張り付ける）',
                    [('城（投下可 全社）', CAP * len(buy), lambda r: True)], buy, G,
                    '社数が変わると城の比率が動く形'))
    S.append(scheme_fixw('F 傾けるが**枠%でなく1銘柄の重み**を固定（irr=85→8% / その他→6%）',
                         lambda r: CAP if is85(r) else 6.0, buy, G,
                         '社数が変わっても1銘柄の重みは動かない＝上限を構造的に破れない。動くのは網の比率だけ',
                         semi_cap=1.0))
    S.append(scheme_fixw('G F と同じ傾け方＋**半導体連鎖 城の30%上限(v9.9.117)を強制**',
                         lambda r: CAP if is85(r) else 6.0, buy, G,
                         '超えた分は比例で削って網へ返す'))
    for s in S:
        show(s)

    print('\n■ 枠の頑健性——**枠%を固定すると、1銘柄の重みが社数で勝手に動く**')
    print(f"   {'irr≥85 の社数':<14}{'B案の1銘柄':>12}{'C案の1銘柄':>12}   上限8%")
    for n in range(1, 9):
        b, c = 30.0 / n, 40.0 / n
        print(f"   {n:>2}社{'（今日）' if n == n85 else '      '}{b:>12.1f}%{c:>12.1f}%   "
              + ('⚠ B/C とも超過' if b > CAP and c > CAP else ('⚠ C が超過' if c > CAP else '—')))
    print(f"   {'門の残りの社数':<13}{'B案の1銘柄':>12}{'C案の1銘柄':>12}")
    for n in range(1, 9):
        b, c = 40.0 / n, 30.0 / n
        print(f"   {n:>2}社{'（今日）' if n == nOther else '      '}{b:>12.1f}%{c:>12.1f}%   "
              + ('⚠ B/C とも超過' if b > CAP and c > CAP else ('⚠ B が超過' if b > CAP else '—')))

    if AS_JSON:
        p = 'out/shadow_alloc_buckets.json'
        json.dump({'generated': '2026-08-09', 'cap': CAP, 'ami_rate': AMI,
                   'buy': [{'t': r['t'], 'irr': r.get('irr'), 's': r['s']} for r in buy],
                   'schemes': S}, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
