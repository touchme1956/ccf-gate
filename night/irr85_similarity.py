#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_similarity.py — **今日の irr=85 を「歴史の継続組の入口の姿」への近さで並べ替える**（2026-08-09新設）

発端（ユーザー指示「過去のirr85でリターンをだした銘柄に類似している順番に入れ替えて」）:
  門の買付順は **席の選定規則（irr=85優先→Ω順）** で決まる。それとは別に、
  「2018年ビンテージの irr=85 のうち**実際に年15%+を出した継続組**が、当時どんな姿だったか」
  への近さで並べたらどうなるかを測る。

⚠ **最初に限界を書く。これは予測の並びではない。**
  この台帳の歴史検証は「**継続/非継続は入口の財務では分かれなかった**」と実測している
  （継続組の営業利益率 20.4% vs 非継続 20.5%＝同一、売上5年CAGR 18.0% vs 15.5%）。
  分けたのは**機構の文が断定形か願望形か**だけだった。したがってこの並びは
  **「勝った社に似ているか」という記述**であって「勝つ確率が高い順」ではない。
  唯一 n=21 の中で方向が出ているのは**レバレッジ**（nde≤1 が 9/12継続 vs nde>1 が 2/4）だが、
  これも1社差の世界で、**nde>4 は TDG ただ1社**しか標本に無い。

測り方（恣意を減らすための3つの約束）:
  1. 特徴量は **2018年コホートと今日のパックの両方に存在するもの**だけ——
     営業利益率 / 売上5年CAGR / FCF転換 / 純負債EBITDA / 規模(売上)。後から足さない
  2. 距離は**当時のコホート21社のばらつき(IQR)で正規化**する。継続組のばらつきで割ると
     「継続組が狭い項」が過大に効く
  3. **中央値からの距離**（ロバスト）。平均と標準偏差は外れ値1社で動く

出すもの:
  (a) 継続組の入口プロファイル（中央値とIQR）
  (b) 今日の各社の距離と、**最も似ている歴史の1社＋その社の実現年率**
  (c) 門の席順との差（どこがどう入れ替わるか）

使い方: python3 night/irr85_similarity.py [--json]
"""
import glob
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
HURDLE = 0.15

# (表示名, 2018側のキー, 今日のパック側の作り方)
FEATS = [('営業利益率', 'opm', lambda x: x.get('gm')),
         ('売上5年CAGR', 'cagr5', lambda x: x.get('cagr')),
         ('FCF転換', 'conv5', lambda x: (x['fcf'] / x['ni']) if (x.get('fcf') and x.get('ni')) else None),
         ('純負債/EBITDA', 'nde', lambda x: x.get('nde')),
         ('規模(売上・十億$)', 'rev', lambda x: None)]      # 規模は今日側を別途 XBRL から入れないと不可 → 使わない


def hist():
    F2 = {r['ticker']: r for r in json.load(open('out/retro_features2_2018.json', encoding='utf-8'))['rows']}
    F1 = {r['ticker']: r for r in json.load(open('out/retro_features_2018.json', encoding='utf-8'))['rows']}
    R = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    firms = json.load(open('out/retro_irr85_deep.json', encoding='utf-8'))['firms85']
    rows = {}
    for t in firms:
        if t not in R:
            continue
        f = F2.get(t, {})
        v = {'opm': (f.get('opm') or 0) * 100 if f.get('opm') is not None else None,
             'cagr5': (f.get('cagr5') or 0) * 100 if f.get('cagr5') is not None else None,
             'conv5': f.get('conv5'),
             'nde': F1.get(t, {}).get('nde18')}
        v['ret'] = R[t]['tr_cagr']
        rows[t] = v
    return rows


def iqr(vals):
    v = sorted(x for x in vals if x is not None)
    if len(v) < 4:
        return None
    q1 = v[len(v) // 4]
    q3 = v[(3 * len(v)) // 4]
    return (q3 - q1) or None


def main():
    H = hist()
    win = {t: v for t, v in H.items() if v['ret'] >= HURDLE}
    los = {t: v for t, v in H.items() if v['ret'] < HURDLE}
    keys = ['opm', 'cagr5', 'conv5', 'nde']
    labels = {'opm': '営業利益率', 'cagr5': '売上5年CAGR', 'conv5': 'FCF転換', 'nde': '純負債/EBITDA'}
    med = {k: st.median([v[k] for v in win.values() if v[k] is not None]) for k in keys}
    spread = {k: iqr([v[k] for v in H.values()]) for k in keys}

    print(f'■ 2018年ビンテージ irr=85（{len(H)}社）: 継続組 {len(win)}社 / 非継続 {len(los)}社（ハードル年{HURDLE:.0%}）')
    print(f"  {'特徴量':<14}{'継続組の中央値':>14}{'非継続の中央値':>14}{'コホート全体のIQR':>18}")
    for k in keys:
        a = st.median([v[k] for v in win.values() if v[k] is not None])
        b = st.median([v[k] for v in los.values() if v[k] is not None])
        print(f'  {labels[k]:<12}{a:>14.2f}{b:>14.2f}{(spread[k] or 0):>18.2f}')
    print('  ⚠ **営業利益率も成長もほとんど差が無い**——この台帳の歴史検証の結論どおり、')
    print('     入口の財務は継続/非継続を分けていない。差が出ているのは主にレバレッジだけ')

    # 今日の irr=85
    today = []
    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        x = x.get('data') or x
        if x.get('irr') != 85:
            continue
        conv = (x['fcf'] / x['ni']) if (x.get('fcf') and x.get('ni')) else None
        v = {'opm': x.get('gm'), 'cagr5': x.get('cagr'), 'conv5': conv, 'nde': x.get('nde')}
        r = SA.get(t, {})
        d = {}
        for k in keys:
            if v[k] is None or spread[k] is None:
                continue
            d[k] = abs(v[k] - med[k]) / spread[k]
        dist = (sum(d.values()) / len(d)) if d else None
        # 最も似ている歴史の1社（同じ正規化での距離）
        best, bd = None, 1e9
        for ht, hv in H.items():
            dd, n = 0, 0
            for k in keys:
                if v[k] is None or hv[k] is None or not spread[k]:
                    continue
                dd += abs(v[k] - hv[k]) / spread[k]
                n += 1
            if n >= 3 and dd / n < bd:
                bd, best = dd / n, ht
        today.append(dict(t=t, **v, dist=dist, nfeat=len(d), near=best, neard=bd,
                          nearret=H[best]['ret'] if best else None,
                          s=r.get('s'), moat=r.get('moat'), buy=bool(r.get('buy'))))

    today.sort(key=lambda z: (z['dist'] is None, z['dist']))
    print(f"\n■ 今日の irr=85 を「継続組の入口」への近さで並べた（距離が小さいほど似ている）")
    print(f"  {'':<6}{'距離':>6}{'営利率':>7}{'成長':>7}{'FCF転換':>8}{'nde':>7}   {'最も似た歴史の1社':<18}{'その社の実現':>10}   門の判定")
    for r in today:
        near = f"{r['near']}（{r['neard']:.2f}）" if r['near'] else '—'
        nr = f"{r['nearret']*100:+.1f}%" if r['nearret'] is not None else '—'
        print(f"  {r['t']:<6}{(r['dist'] if r['dist'] is not None else 9.99):>6.2f}"
              f"{(r['opm'] if r['opm'] is not None else 0):>7.1f}{(r['cagr5'] if r['cagr5'] is not None else 0):>7.1f}"
              f"{(r['conv5'] if r['conv5'] is not None else 0):>8.2f}{(r['nde'] if r['nde'] is not None else 0):>7.2f}"
              f"   {near:<18}{nr:>10}   {'🟢投下可' if r['buy'] else f'⛔(Ω{r[chr(115)]})'}")

    # ── ★ここが本題: 似ている社を探す前に、**本人の実績があるかを見る**─────────────────
    #   今日の irr=85 の14社のうち **9社は2018年コホートそのもの**で、実現年率が判っている。
    #   距離で似た社を当てるより、**本人が何を出したか**のほうが桁違いに強い証拠。
    R18 = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    R15 = {}
    for f in ('out/retro_returns_2015.json', 'out/retro_returns_2015_q.json'):
        if os.path.exists(f):
            for r in json.load(open(f, encoding='utf-8'))['rows']:
                R15.setdefault(r['ticker'], r)
    print('\n■ ★本人の実績（似ている社を探す前に、本人が過去に何を出したかを見る）')
    print(f"  今日の irr=85 {len(today)}社のうち **{sum(1 for r in today if r['t'] in R18)}社は2018年コホートそのもの**")
    tier = []
    for r in today:
        t = r['t']
        if t in R18:
            r['self'] = R18[t]['tr_cagr']; r['selfsrc'] = '2018→2026(8.1年)'
        elif t in R15:
            r['self'] = R15[t]['tr_cagr']; r['selfsrc'] = '2015→2026(11.1年)'
        else:
            r['self'] = None; r['selfsrc'] = None
        tier.append(r)
    A = sorted([r for r in tier if r['self'] is not None and r['self'] >= HURDLE], key=lambda z: -z['self'])
    B = sorted([r for r in tier if r['self'] is not None and r['self'] < HURDLE], key=lambda z: -z['self'])
    C = sorted([r for r in tier if r['self'] is None], key=lambda z: z['dist'] if z['dist'] is not None else 9)
    for lab, g in (('Ⅰ 本人が年15%+を出した（継続組）', A), ('Ⅱ 本人が届かなかった', B),
                   ('Ⅲ 実績が無い（似ている社で代用）', C)):
        print(f'\n  ── {lab}')
        for r in g:
            selfs = f"{r['self']*100:+6.1f}% {r['selfsrc']}" if r['self'] is not None else \
                    f"→ {r['near']} の {r['nearret']*100:+.1f}% に近い（距離{r['neard']:.2f}）"
            print(f"    {r['t']:<6} {selfs:<30} 今日Ω{str(r['s']):>5} 堀{str(r['moat']):>6}  {'🟢投下可' if r['buy'] else '⛔'}")

    if AS_JSON:
        p = 'out/irr85_similarity.json'
        json.dump({'generated': '2026-08-09', 'hurdle': HURDLE,
                   'winner_median': med, 'cohort_iqr': spread,
                   'winners': sorted(win), 'losers': sorted(los), 'today': today},
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
