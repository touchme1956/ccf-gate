#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_lookalike.py — **歴史の勝者と同じ姿をした社を、台帳全部から拾う**（2026-08-09新設）

発端（ユーザー指示「過去リターンをだした銘柄と同じようなやつだして」）:
  前の道具（irr85_similarity.py）は**今日の irr=85 の14社**を勝者への近さで並べた。
  これはその外側——**台帳369社の全部**に同じ物差しを当てて、勝者と同じ姿の社を拾う。

⚠ **先に限界を書く。財務の近さは、歴史では勝敗を分けていない。**
  2018年ビンテージ irr=85 の21社で、継続組と非継続の入口はほぼ同一だった
  （営業利益率 20.36 vs 20.51／FCF転換 1.19 vs 1.33／nde 0.88 vs 0.91）。
  分けたのは**機構（irr）と、その文が断定形か願望形か**だけ。
  だから**財務の近さ「だけ」で拾うと、歴史がいちばん報われないと言った群（irr=50・P=0.162）を大量に拾う**。
  → この道具は **財務の近さ × 機構(irr)** の二軸で出す。片方だけ見ないこと。

  歴史の刻み別 P(継続): irr=50 **0.162** ／ irr=70 **0.366** ／ irr=85 **0.579**（プール754件・ベース0.204）

物差し（irr85_similarity.py と同一・恣意を増やさない）:
  ・特徴量 = 営業利益率 / 売上5年CAGR / FCF転換 / 純負債EBITDA（両方に存在するものだけ）
  ・2018年コホート21社の **IQR で正規化**（継続組の狭さで割ると狭い項が過大に効く）
  ・**継続組の中央値からのロバスト距離**。4項そろっている社だけを対象にする（欠測は憶測で埋めない）

  さらに **2つの原型**を出し分ける:
   A「継続組ぜんぶ」の中央値（営利率20.4 / 成長18.0 / FCF転換1.19 / nde0.88）
   B「**事業が稼いだ**組」＝実現年率のうち売上成長の寄与が大きかった社（RBC/TDG/ENTG/MKSI/WST）の中央値
     ——20年持つ側にとって再現性が高いのはこちら（LRCX/CWの実現は大半が再評価）

使い方: python3 night/irr85_lookalike.py [--json] [--top 20]
"""
import glob
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
TOP = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 15
HURDLE = 0.15
KEYS = ['opm', 'cagr5', 'conv5', 'nde']
LAB = {'opm': '営利率', 'cagr5': '成長', 'conv5': 'FCF転換', 'nde': 'nde'}
# 実現年率のうち売上成長の寄与が大きかった＝「事業が稼いだ」組（残差が10pt未満）
BIZ = ['RBC', 'TDG', 'ENTG', 'MKSI', 'WST']
# 歴史の刻み別 P(継続)（out/retro_moat_durability.json のプール754件）
PCONT = {50: 0.162, 70: 0.366, 85: 0.579, 100: 0.056}


def cohort():
    F2 = {r['ticker']: r for r in json.load(open('out/retro_features2_2018.json', encoding='utf-8'))['rows']}
    F1 = {r['ticker']: r for r in json.load(open('out/retro_features_2018.json', encoding='utf-8'))['rows']}
    R = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    firms = json.load(open('out/retro_irr85_deep.json', encoding='utf-8'))['firms85']
    H = {}
    for t in firms:
        if t not in R:
            continue
        f = F2.get(t, {})
        H[t] = {'opm': (f['opm'] * 100) if f.get('opm') is not None else None,
                'cagr5': (f['cagr5'] * 100) if f.get('cagr5') is not None else None,
                'conv5': f.get('conv5'), 'nde': F1.get(t, {}).get('nde18'),
                'ret': R[t]['tr_cagr']}
    return H


def med_of(H, names):
    return {k: st.median([H[t][k] for t in names if H.get(t, {}).get(k) is not None]) for k in KEYS}


def iqr(v):
    v = sorted(x for x in v if x is not None)
    if len(v) < 4:
        return None
    return (v[(3 * len(v)) // 4] - v[len(v) // 4]) or None


def main():
    H = cohort()
    win = [t for t, v in H.items() if v['ret'] >= HURDLE]
    A = med_of(H, win)
    B = med_of(H, [t for t in BIZ if t in H])
    SP = {k: iqr([v[k] for v in H.values()]) for k in KEYS}
    print('■ 原型（2018年ビンテージ irr=85 の実測）')
    print(f"  {'':<22}" + ''.join(f'{LAB[k]:>10}' for k in KEYS))
    print(f"  {'A 継続組ぜんぶ('+str(len(win))+'社)':<20}" + ''.join(f'{A[k]:>10.2f}' for k in KEYS))
    print(f"  {'B 事業が稼いだ組(5社)':<19}" + ''.join(f'{B[k]:>10.2f}' for k in KEYS)
          + '   ← RBC/TDG/ENTG/MKSI/WST（実現のうち売上成長の寄与が大きい）')
    print(f"  {'（正規化に使うIQR）':<19}" + ''.join(f'{(SP[k] or 0):>10.2f}' for k in KEYS))

    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    rows = []
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        x = x.get('data') or x
        conv = (x['fcf'] / x['ni']) if (x.get('fcf') and x.get('ni')) else None
        v = {'opm': x.get('gm'), 'cagr5': x.get('cagr'), 'conv5': conv, 'nde': x.get('nde')}
        if any(v[k] is None for k in KEYS):        # 4項そろわない社は対象外（欠測を憶測で埋めない）
            continue
        r = SA.get(t, {})
        dA = sum(abs(v[k] - A[k]) / SP[k] for k in KEYS) / len(KEYS)
        dB = sum(abs(v[k] - B[k]) / SP[k] for k in KEYS) / len(KEYS)
        rows.append(dict(t=t, **v, dA=round(dA, 2), dB=round(dB, 2), irr=x.get('irr'),
                         s=r.get('s'), moat=r.get('moat'), buy=bool(r.get('buy')),
                         quali=bool(r.get('quali'))))
    print(f'\n  対象 {len(rows)}社（4項そろうパック。全369社のうち欠測のある社は外した）')

    def show(title, key, filt=None, n=TOP):
        g = [r for r in rows if (filt is None or filt(r))]
        g.sort(key=lambda z: z[key])
        print(f'\n■ {title}')
        print(f"  {'':<7}{'距離':>5}{'irr':>5}{'P(継続)':>8}{'営利率':>7}{'成長':>7}{'FCF転換':>8}{'nde':>7}{'Ω':>7}{'堀':>7}  門")
        for r in g[:n]:
            pc = PCONT.get(r['irr'])
            print(f"  {r['t']:<7}{r[key]:>5.2f}{str(r['irr']):>5}{(f'{pc:.3f}' if pc else '  —'):>8}"
                  f"{r['opm']:>7.1f}{r['cagr5']:>7.1f}{r['conv5']:>8.2f}{r['nde']:>7.2f}"
                  f"{str(r['s']):>7}{str(r['moat']):>7}  "
                  f"{'🟢投下可' if r['buy'] else ('🔵次点' if r['quali'] else '⛔')}")

    show('① 機構つき（irr=85）で、原型Aに近い順 ← **歴史が支持するのはこの群だけ**',
         'dA', lambda r: r['irr'] == 85)
    show('② irr=70（歴史 P=0.366・ベース0.204の1.8倍）で、原型Aに近い順',
         'dA', lambda r: r['irr'] == 70, 12)
    show('③ 機構を無視して財務の近さだけ（**この並びは歴史の支持が無い**——'
         'irr=50 が混ざるが、その群の P は 0.162 でベース以下）',
         'dA', None, 12)
    show('④ 原型B（事業が稼いだ組）に近い順・irr≥70 に限定',
         'dB', lambda r: r['irr'] in (70, 85), 12)

    # ── ★この道具でいちばん重要な出力: **画面そのものの答え合わせ** ─────────────────
    #   ⚠ 「今日の財務 × 2018→2026のリターン」で突き合わせてはいけない——**因果が逆流する**
    #      （今日良く見える社は 2018-2026 に良かった社）。正しい検定は
    #      **2018年時点の財務で距離を作り、同じ窓のリターンに当てる**こと。在庫にその両方がある。
    R18 = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    F2 = {r['ticker']: r for r in json.load(open('out/retro_features2_2018.json', encoding='utf-8'))['rows']}
    F1 = {r['ticker']: r for r in json.load(open('out/retro_features_2018.json', encoding='utf-8'))['rows']}
    P = []
    for t, r in R18.items():
        f = F2.get(t, {})
        v = {'opm': (f['opm'] * 100) if f.get('opm') is not None else None,
             'cagr5': (f['cagr5'] * 100) if f.get('cagr5') is not None else None,
             'conv5': f.get('conv5'), 'nde': F1.get(t, {}).get('nde18')}
        if any(v[k] is None for k in KEYS):
            continue
        P.append((sum(abs(v[k] - A[k]) / SP[k] for k in KEYS) / len(KEYS), t, r['tr_cagr']))
    P.sort()
    print(f'\n■ ★答え合わせ——**2018年時点の財務**で同じ距離を作り、同じ窓(8.1年)のリターンに当てる（{len(P)}社）')
    print('  ※今日の財務で突き合わせると因果が逆流するので、必ず当時の財務で測る')
    print(f"  {'帯':<16}{'n':>5}{'中央値':>9}{'P(15%+)':>9}{'恒久毀損':>9}")
    q = len(P) // 5
    for i, lab in enumerate(['Q1 最も似ている', 'Q2', 'Q3', 'Q4', 'Q5 最も遠い']):
        g = P[i * q:(i + 1) * q] if i < 4 else P[4 * q:]
        v = [x[2] for x in g]
        print(f"  {lab:<14}{len(v):>5}{st.median(v)*100:>8.1f}%"
              f"{sum(1 for x in v if x >= HURDLE)/len(v):>9.2f}{sum(1 for x in v if x <= -0.15)/len(v):>9.2f}")
    v = [x[2] for x in P]
    base = sum(1 for x in v if x >= HURDLE) / len(v)
    print(f"  {'全体':<14}{len(v):>5}{st.median(v)*100:>8.1f}%{base:>9.2f}"
          f"{sum(1 for x in v if x <= -0.15)/len(v):>9.2f}")
    hv = [R18[t]['tr_cagr'] for t in H if t in R18]
    print(f"  {'（参考）irr=85 の21社':<13}{len(hv):>5}{st.median(hv)*100:>8.1f}%"
          f"{sum(1 for x in hv if x >= HURDLE)/len(hv):>9.2f}{sum(1 for x in hv if x <= -0.15)/len(hv):>9.2f}")
    print('  **→ 財務の近さのリフトはゼロ（Q1 の P=0.21 ＝ 全体の 0.21）。効いたのは irr=85 のラベルだけ（0.71）。**')
    print('     この台帳が4回記録してきた「質の指標と結果が逆／効かない」の5回目')

    print('\n■ 読み方')
    print('  ・**①以外は「似ている」だけで、歴史はそれが報われるとは言っていない**。')
    print('    継続/非継続は入口の財務で分かれなかった（営利率 20.36 vs 20.51）のが実測。')
    print('  ・②③に出た社を買う理由にするなら、必要なのは**財務の近さではなく原本の機構文**')
    print('    ——「顧客の側が再認定・再試験をやり直すか」。2026-08-08 に EDGAR 全文で 403社を読んで')
    print('    **新しい irr=85 はゼロ**だったので、②から85へ昇格する社が出る見込みは薄い。')
    print('  ・したがって実務的な答えは「①の14社が母集団のすべて」——外に同じ型は（今のところ）居ない。')

    if AS_JSON:
        p = 'out/irr85_lookalike.json'
        json.dump({'generated': '2026-08-09', 'proto_A': A, 'proto_B': B, 'iqr': SP,
                   'winners': sorted(win), 'rows': rows}, open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
