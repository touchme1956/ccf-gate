#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/base_rate_check.py — **今日の投下可を歴史の基礎率へ当てる**（2026-08-08新設）

なぜ要るか（ユーザーの問い「歴史的にいま買える10社は複利を得られる？」）:
  この台帳は歴史検証で「どの型が何%で複利したか」を実測してある（out/retro_moat_durability.json）。
  ところが**今日の投下可をその表へ当てる道具が無かった**ので、毎回手で照らすことになる。
  手で照らすと、都合のいい群（irr=85 ∧ 第三者が認定＝恒久毀損0%）だけを見て
  「歴史が支持している」と言いやすい。**全社をそれぞれの群へ機械的に割り当てて数える。**

  **これは予測ではない。** 歴史の同じ型が実際に何%だったかを言うだけで、
  今日の10社がそうなるとは言っていない。基礎率は当たりの保証ではなく**出発点**。

何を出すか:
  1. 各社を irr の刻みで歴史の群へ割り当て、その群の 中央値／P(年率15%+)／元本割れ／恒久毀損 を並べる
  2. 等ウェイトの組合せとしての期待（**平均**で合成する——等ウェイトの実現は構成銘柄の算術平均であって
     中央値の平均ではない。中央値は「1社を選んだとき」の話）
  3. 歴史の逆風の印を各社に付ける: 高成長(cagr≥15＝lift0.6の逆信号) ／ 倍率(PER÷fair) ／
     維持型プロファイル(roic12+ ∧ opm10+ ∧ conv0.8+) ／ 機構B(設計組込＝歴史で唯一壊れた型)
  4. 同期間の指数との比較を必ず併記する（**群が指数に勝ったかは、群の絶対値とは別の問い**）

使い方: python3 night/base_rate_check.py [--json]
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]

# 歴史検証の同期間の指数（CLAUDE.md 記載の実測）
SPY = {'2013(13.1年)': 0.142, '2018(8.1年)': 0.150}


def buy_list():
    if not os.path.exists('out/score_all.json'):
        subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    a = json.load(open('out/score_all.json', encoding='utf-8'))
    return [r['t'] for r in a if r.get('buy')]


def pack(t):
    for p in glob.glob('out/*_gate_pack.json'):
        if os.path.basename(p).split('_gate_pack')[0] == t:
            d = json.load(open(p, encoding='utf-8'))
            return d.get('data') or d
    return None


def group_of(irr):
    if irr == 85:
        return 'irr=85'
    if irr == 70:
        return 'irr=70'
    if irr == 100:
        return 'irr=100'      # 歴史では最下位（P=0.056/0.091）。durabilityの表には群が無い
    return 'irr=50'


def main():
    G = json.load(open('out/retro_moat_durability.json', encoding='utf-8'))['groups']
    ts = buy_list()
    rows = []
    for t in ts:
        x = pack(t) or {}
        irr = x.get('irr')
        g = x.get('cagr') or 0
        per = x.get('per')
        fair = max(16, min(30, 8 + min(g, 20)))
        conv = (x['fcf'] / x['ni']) if (x.get('fcf') and x.get('ni')) else None
        rows.append(dict(
            t=t, irr=irr, grp=group_of(irr), roic=x.get('roic'), opm=x.get('gm'),
            cagr=g, per=per, fair=fair,
            mult=round(per / fair, 2) if per else None,
            conv=round(conv, 2) if conv else None,
            keep=bool((x.get('roic') or 0) >= 12 and (x.get('gm') or 0) >= 10 and (conv or 0) >= 0.8),
            hot=g >= 15))

    print('■ 今日の投下可を歴史の基礎率へ当てる（out/retro_moat_durability.json・2013+2015の542件・ハードル年15%）')
    print('  ※ 基礎率は「同じ型が過去に何%だったか」であって、この10社の予測ではない\n')
    print(f"  {'':<6}{'irr':>4}{'roic':>7}{'opm':>6}{'cagr':>6}{'倍率':>6}{'conv':>6}  印")
    for r in rows:
        mk = []
        if r['hot']:
            mk.append('高成長=逆信号(lift0.6)')
        if r['mult'] and r['mult'] >= 3:
            mk.append(f"倍率{r['mult']}x=裾")
        if not r['keep']:
            mk.append('維持型プロファイル外')
        print(f"  {r['t']:<6}{str(r['irr']):>4}{str(r['roic']):>7}{str(r['opm']):>6}"
              f"{r['cagr']:>6}{str(r['mult']):>6}{str(r['conv']):>6}  {' / '.join(mk)}")

    print(f"\n  {'群':<10}{'社':>3}{'歴史n':>6}{'中央値':>8}{'平均':>7}{'P(15%+)':>9}{'元本割れ':>8}{'恒久毀損':>8}")
    tot_mean = tot_p = tot_imp = 0.0
    n = len(rows)
    for grp in ('irr=85', 'irr=70', 'irr=50', 'irr=100'):
        k = [r for r in rows if r['grp'] == grp]
        if not k:
            continue
        s = G.get(grp)
        if not s:
            print(f"  {grp:<10}{len(k):>3}     —  （歴史の表に群が無い: {' '.join(r['t'] for r in k)}）")
            continue
        w = len(k) / n
        tot_mean += w * s['mean']
        tot_p += w * s['P15']
        tot_imp += w * s['恒久毀損']
        print(f"  {grp:<10}{len(k):>3}{s['n']:>6}{s['median']*100:>7.1f}%{s['mean']*100:>6.1f}%"
              f"{s['P15']:>9.2f}{s['元本割れ']:>8.2f}{s['恒久毀損']:>8.2f}   {' '.join(r['t'] for r in k)}")

    print(f"\n  等ウェイト10社の合成（**平均**で合成——等ウェイトの実現は構成銘柄の算術平均）:")
    print(f"     年率 **{tot_mean*100:.1f}%** ／ 15%+に届く社数の期待 **{tot_p*n:.1f}/{n}社** "
          f"／ 恒久毀損の期待 **{tot_imp*n:.1f}社**")
    print(f"  同期間の指数（歴史検証の実測）: " + " / ".join(f"{k} {v*100:.1f}%" for k, v in SPY.items()))

    print('\n■ 読み方（数字と同じくらい大事な限界）')
    print('  ・**「複利するか」と「指数に勝つか」は別の問い**。irr=70 の歴史中央値 11.4% は')
    print('    同期間の指数(14〜15%)に**負けている**。勝ち越しの支持があるのは irr=85 の群だけ')
    # ⚠ n を文字列に焼き付けない——2026-08-12 に durability の母集団が 542→754 へ増え、
    #   ここだけ「n は10」と言い続けていた（数字を書き写した箇所は必ず陳腐化する）
    _n85 = (G.get('irr=85') or {}).get('n')
    print(f"  ・irr=85 の n は{_n85}（2018年ビンテージでは21）。**0件は真のゼロではない**")
    print('  ・歴史の窓は 8〜13年。**20〜30年の複利へ外挿したものではない**')
    print('  ・成長の基礎率は別に測ってある——trailing 20-30% の社の前方10年は中央値 7.1%・')
    print('    15%維持は20%（out/retro_growth_persistence.json）。高成長を織り込んだ株価は逆風側')

    if AS_JSON:
        p = 'out/base_rate_buy.json'
        json.dump(dict(generated='2026-08-08', rows=rows,
                       mean=round(tot_mean, 4), p15=round(tot_p, 4), impair=round(tot_imp, 4)),
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
