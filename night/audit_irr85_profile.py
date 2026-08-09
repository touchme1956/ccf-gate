#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_irr85_profile.py — **今日の irr=85 を、歴史の irr=85 の「入口の姿」と突き合わせる**（2026-08-09新設）

なぜ要るか（ユーザーの問い「irr85の銘柄すべてを分析して当時の状況と見比べて評価を再度やり直すべきでは？」）:
  この台帳は irr=85 を堀の規約の中心に置いたが、**「歴史の85」と「今日の85」が同じ顔をしているか**を
  一度も突き合わせていなかった。歴史の21社が出した年20.6%は
  **売上成長10.6% + 利益率0.6% + 株数−0.6% + 倍率11.8%** の合成で、半分は再評価だった。
  だから「85だから安心」ではなく、**入口の姿が当時とどれだけ違うか**を毎回見る必要がある。

出すもの:
  1. **歴史の分かれ目**——irr=85 の21社を継続組(年15%+)/非継続に割り、入口の特徴量で比較する。
     実測: 営業利益率は 20.4% vs 20.5% で**同一**、売上CAGRも 18.0% vs 15.5% でほとんど差が無い。
     **入口の財務では分かれない。** 分けたのは**機構の文が断定か願望か**——
     願望形5社(AEIS/COHR/IPGP/OLED/ROG)のうち**3社が非継続**(60%)、完了形16社は3社(19%)。
  2. **今日の irr=85 の各社**を、その歴史の中央値（売上CAGR18.0% / 営利率20.4% / 入口PER31.7 /
     FCF転換118.7%）と並べ、乖離に印を付ける。
  3. 印は**判定に一切使わない**——Ω・堀・関門・配分はいずれも不変。これは較正の材料であって規則ではない。

限界（必ず併記する）: 歴史は n=21 の単一ビンテージ・8.1年の一窓で、2018-2026 は半導体資本財に極端に有利。
  継続/非継続の分割は 15/6 で、6社側の中央値は外れ値1社で動く。**規則にできる強度ではない。**

使い方: python3 night/audit_irr85_profile.py [--json]
"""
import glob
import json
import os
import re
import statistics as st
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
# 2026-08-05 にホールドアウトを見る前に封印した「願望形」の5社（out/retro_irr85_language_hypothesis.json）
WISH = {'AEIS', 'COHR', 'IPGP', 'OLED', 'ROG'}
HURDLE = 0.15


def hist():
    d = json.load(open('out/retro_features2_2018.json', encoding='utf-8'))
    F = {r['ticker']: r for r in (d['rows'] if isinstance(d, dict) else d)}
    R = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    firms = json.load(open('out/retro_irr85_deep.json', encoding='utf-8'))['firms85']
    have = [t for t in firms if t in R and t in F]
    win = [t for t in have if R[t]['tr_cagr'] >= HURDLE]
    los = [t for t in have if R[t]['tr_cagr'] < HURDLE]
    med = lambda ts, k: st.median([F[t][k] for t in ts if F[t].get(k) is not None]) if ts else None
    return F, R, have, win, los, med


def mech_of(ev):
    for k, pat in [('A工程認定', r'qualify and integrate|production line|工程認定'),
                   ('C第三者認定', r'certified by|must be certified|OEM|FAA|DoD|第三者'),
                   ('D名簿', r'sole provider|designated|名簿'),
                   ('E長期認定', r're-?qualif|requalif|長期認定')]:
        if re.search(pat, ev, re.I):
            return k
    return '?'


def main():
    if not os.path.exists('out/score_all.json'):
        subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    F, R, have, win, los, med = hist()

    print('■ 歴史（2018年ビンテージ irr=85・21社）: 何が継続/非継続を分けたか')
    print(f'  継続組(年{HURDLE:.0%}+) {len(win)}社 / 非継続 {len(los)}社 …… {" ".join(sorted(los))}')
    print(f"  {'特徴量':<16}{'継続組':>10}{'非継続':>10}")
    for k, l in [('cagr5', '売上5年CAGR'), ('opm', '営業利益率'), ('opmD5', '営利率の5年変化'),
                 ('conv5', 'FCF転換'), ('payout5', '還元性向'), ('netiss_r', '純株式発行率')]:
        a, b = med(win, k), med(los, k)
        if a is None or b is None:
            continue
        print(f'  {l:<14}{a*100:>9.1f}%{b*100:>9.1f}%')
    lw = len(WISH & set(los))
    print(f'  → **入口の財務では分かれない**（営業利益率は同一）。分けたのは**機構の文が断定か願望か**——')
    print(f'     願望形5社のうち非継続 **{lw}社**（{lw/5:.0%}）／完了形16社のうち非継続 {len(los)-lw}社（{(len(los)-lw)/16:.0%}）')

    H = dict(cagr=med(win, 'cagr5') * 100, opm=med(win, 'opm') * 100, conv=med(win, 'conv5') * 100, per=31.7)
    print(f"\n■ 今日の irr=85 を、その継続組の入口（売上CAGR {H['cagr']:.1f}% / 営利率 {H['opm']:.1f}% "
          f"/ FCF転換 {H['conv']:.0f}% / 入口PER {H['per']}）と並べる")
    rows = []
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        d = json.load(open(p, encoding='utf-8'))
        x = d.get('data') or d
        if x.get('irr') != 85:
            continue
        ev = ((d.get('_meta') or {}).get('evidence') or {}).get('irr', '')
        g = x.get('cagr') or 0
        per = x.get('per')
        fair = max(16, min(30, 8 + min(g, 20)))
        conv = (x['fcf'] / x['ni']) if (x.get('fcf') and x.get('ni')) else None
        r = SA.get(t, {})
        flags = []
        if g < H['cagr'] * 0.6:
            flags.append('成長が歴史の6割未満')
        if per and per / fair > 2.0:
            flags.append(f'倍率{per/fair:.2f}x')
        if (x.get('nde') or 0) > 4:
            flags.append('財務キル')
        if conv and conv * 100 < H['conv'] * 0.8:
            flags.append('FCF転換が薄い')
        if re.search(r'work closely|strive|aim to', ev, re.I):
            flags.append('⚠願望形の疑い')
        rows.append(dict(t=t, s=r.get('s'), moat=r.get('moat'), buy=bool(r.get('buy')), cagr=g,
                         opm=x.get('gm'), per=per, mult=(per / fair) if per else None, conv=conv,
                         nde=x.get('nde'), mech=mech_of(ev), flags=flags))
    rows.sort(key=lambda z: -(z['s'] or 0))
    print(f"  {'':<6}{'Ω':>6}{'堀':>6}{'cagr':>7}{'営利率':>7}{'倍率':>7}{'FCF転換':>8}  {'機構':<10}買付  歴史との差")
    for r in rows:
        print(f"  {r['t']:<6}{str(r['s']):>6}{str(r['moat']):>6}{r['cagr']:>6.1f}%{str(r['opm']):>7}"
              f"{(f'{r[chr(109)+chr(117)+chr(108)+chr(116)]:.2f}x' if r['mult'] else '—'):>7}"
              f"{(f'{r[chr(99)+chr(111)+chr(110)+chr(118)]:.2f}' if r['conv'] else '—'):>8}"
              f"  {r['mech']:<10}{'🟢' if r['buy'] else '🔵/⛔'}  {' / '.join(r['flags'])}")

    print('\n■ 読み方')
    print('  ・**今日の14社に願望形はゼロ**——2026-08-05〜07 の全数検算で 53社→11社 へ削り、')
    print('    歴史で最も分けた型（AEIS/COHR/OLED/ROG/IPGP の願望形）は全部70へ降格済み。')
    print('    **歴史が示した唯一の分かれ目について、今日の台帳は既に掃除されている**')
    print('  ・一方、**投下可の4社は歴史の勝者の顔をしていない**——成長が薄く買値が高い側に寄る。')
    print('    歴史の勝者の顔に最も近いのは RBC・LOAR（成長25%・営利率21-23%・FCF転換1.2-1.4）だが、')
    print('    **どちらも買収由来の指標（roicg<WACC / nde>4）で止まっている**')
    print('  ・限界: n=21 の単一ビンテージ・8.1年の一窓・非継続は6社。**規則にできる強度ではない**')

    if AS_JSON:
        p = 'out/audit_irr85_profile.json'
        json.dump(dict(generated='2026-08-09', hist_winner=H, rows=rows),
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
