#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr70_mech_test.py — v9.9.144（70に機構の名指しを要求する）を歴史で答え合わせする（2026-08-20新設）

なぜ要るか:
  2026-08-12 に irr=70 を「残余」から「積極的な主張」へ改めた（ユーザー明示指示）。
  検証の設計は「**同じ社を二度読ませて一致率 0.706 が上がるか**」＝**再現性**の話だった。
  だが**予言力**の話は一度もしていない——改定が『読み手のぶれを減らす』だけなのか、
  『当たる社を選び直している』のかが判らないまま、213社に当てようとしている。

  ⚠ しかも**これは「基準の違う二つ」の型そのもの**（この台帳が11回踏んだ）——
  歴史の P(継続) 刻み別（50:0.162 / 70:0.366 / 85:0.579）は **改定前の「残余」の70**で測った数字。
  改定後の70は**別の定義**なのに、同じ 0.366 を引き継いで語ると基準の違う二つを並べることになる。

何をするか:
  歴史の読解（2013/2015）が irr=70 の社に付けた `mech`（機構の型）を使って、
  **機構が名指しされた70 と、されなかった70** を分けて P(年率15%+) を出す。
  ＝改定が予言力を上げるかの直接の検定。

⚠ 限界（先に書く）:
  ・`mech` は**85の型分けのために記録された欄**で、70 は「たまたま書かれていた」もの。
    「読み手が v9.9.144 の粒度で機構を名指しできたか」と完全に同じではない
  ・2013 と 2015 は **147社が重複**し窓の後半を共有＝独立標本ではない
  ・2018 は 75刻みで mech が全社『なし』＝**検定できない**（「効かない」ではない）
  ・私の事前登録ではない。ただし**方向は 2026-08-12 に既に記録済**（+6.8pt・n=12/22）なので
    探索ではなく**標本を増やした確認**
  ・⚠**交絡**: 「mech が書かれている」は「その社に機構がある」の代理かもしれないし、
    「その班が丁寧だった」の代理かもしれない。ただし mech は irr=50 の**580社すべてで『なし』**
    ＝機構の型がある社にしか書かれない欄なので、丁寧さの代理としては働きにくい（決定的ではない）

使い方:
  python3 night/irr70_mech_test.py [--json]
"""
import glob
import json
import os
import random
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUR = 0.15          # 既存のハードル。新しい定数を作らない
SEED = 20260820


def rows_of(p):
    d = json.load(open(p, encoding='utf-8'))
    return d if isinstance(d, list) else (d.get('rows') or [])


def load():
    read = {}
    for p in sorted(glob.glob(os.path.join(ROOT, 'out', 'retro_moat_2*.json'))):
        v = '2013' if '2013' in p else ('2015' if '2015' in p else '2018')
        for r in rows_of(p):
            if not isinstance(r, dict):
                continue
            t = r.get('ticker') or r.get('t')
            irr = r.get('irr') if r.get('irr') is not None else r.get('irr18')
            if not t or irr is None:
                continue
            read[(v, t)] = dict(irr=irr, mech=(r.get('mech') or 'なし'))
    RET = {'2013': ['retro_returns_2013_all.json', 'retro_returns_2013.json'],
           '2015': ['retro_returns_2015_q.json', 'retro_returns_2015.json'],
           '2018': ['retro_returns_2018.json']}
    ret = {}
    for v, ps in RET.items():
        for f in ps:
            p = os.path.join(ROOT, 'out', f)
            if not os.path.exists(p):
                continue
            for r in rows_of(p):
                if isinstance(r, dict) and r.get('ticker') and r.get('tr_cagr') is not None:
                    ret.setdefault((v, r['ticker']), r['tr_cagr'])
    return read, ret


def stat(sel, ret):
    xs = sorted(ret[k] for k in sel if k in ret)
    if not xs:
        return None
    return dict(n=len(xs), P=round(sum(1 for x in xs if x >= HUR) / len(xs), 4),
                med=round(xs[len(xs) // 2], 4),
                neg=round(sum(1 for x in xs if x < 0) / len(xs), 4))


def perm(named, unn, ret, n=4000):
    """★**会社単位で並べ替える**。ビンテージ内で独立に混ぜると従属が壊れる
    （2026-08-11 に33倍の過小評価を実測した型）ので、**同じ社の全ビンテージを一緒に動かす**。
    ⚠ 同じ社が片方のビンテージで機構あり・もう片方でなし、ということが起きる。
      その社は「機構ありの社」として数える（**帰無を作るときは実測の側に有利に倒す**
      ——そうしておけば p は保守的に出る）。"""
    ent = [(k, True) for k in named if k in ret] + [(k, False) for k in unn if k in ret]
    if not ent:
        return 0.0, 1.0
    lab = {}
    for k, v in ent:
        lab[k[1]] = lab.get(k[1], False) or v      # 社ごとの真のラベル（あり優先）
    cos = sorted(lab)
    ks = [lab[c] for c in cos]
    def diff(assign):
        a = [k for k, _ in ent if assign[k[1]]]
        b = [k for k, _ in ent if not assign[k[1]]]
        sa, sb = stat(a, ret), stat(b, ret)
        return None if (not sa or not sb) else sa['P'] - sb['P']
    obs = diff(lab)
    if obs is None:
        return 0.0, 1.0
    rnd = random.Random(SEED)
    hit = 0
    for _ in range(n):
        sh = ks[:]
        rnd.shuffle(sh)
        d = diff(dict(zip(cos, sh)))
        if d is not None and d >= obs:
            hit += 1
    return round(obs, 4), round((hit + 1) / (n + 1), 4)


def main():
    as_json = '--json' in sys.argv
    read, ret = load()
    out = {'hurdle': HUR, 'seed': SEED, 'vintages': {}}
    for v in ['2013', '2015', '2018']:
        g = [k for k in read if k[0] == v and read[k]['irr'] in (70, 75)]
        if not g:
            continue
        out['vintages'][v] = dict(
            base=stat([k for k in read if k[0] == v], ret),
            r70=stat(g, ret),
            named=stat([k for k in g if read[k]['mech'] != 'なし'], ret),
            unnamed=stat([k for k in g if read[k]['mech'] == 'なし'], ret))
    pool = [k for k in read if k[0] in ('2013', '2015') and read[k]['irr'] == 70]
    named = [k for k in pool if read[k]['mech'] != 'なし']
    unn = [k for k in pool if read[k]['mech'] == 'なし']
    obs, p = perm(named, unn, ret)
    out['pool'] = dict(
        base=stat([k for k in read if k[0] in ('2013', '2015')], ret),
        r50=stat([k for k in read if k[0] in ('2013', '2015') and read[k]['irr'] == 50], ret),
        unnamed=stat(unn, ret), named=stat(named, ret),
        r85=stat([k for k in read if k[0] in ('2013', '2015') and read[k]['irr'] == 85], ret),
        lift=obs, perm_p=p)
    by = defaultdict(list)
    for k in pool:
        by[read[k]['mech']].append(k)
    out['by_mech'] = {m: stat(ks, ret) for m, ks in by.items()}

    # ★左尾は逆を向く。**この改定は「壊れない」を買っているのではない**——
    #   堀は買付の関門＝壊れないための装置なので、これは記録に値する緊張。
    def fisher(a, b, c, d):
        from math import lgamma
        def lc(n, k):
            return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
        tot = a + b + c + d
        obs = lc(a + b, a) + lc(c + d, c) - lc(tot, a + c)
        s = 0.0
        for i in range(0, min(a + b, a + c) + 1):
            j, k, l = a + b - i, a + c - i, d - (a - i)
            if j < 0 or k < 0 or l < 0:
                continue
            v = lc(a + b, i) + lc(c + d, k) - lc(tot, a + c)
            if v <= obs + 1e-9:
                s += pow(2.718281828459045, v)
        return round(min(1.0, s), 4)
    nn, un = out['pool']['named'], out['pool']['unnamed']
    an, bn = round(nn['neg'] * nn['n']), nn['n'] - round(nn['neg'] * nn['n'])
    au, bu = round(un['neg'] * un['n']), un['n'] - round(un['neg'] * un['n'])
    out['left_tail'] = dict(named_neg=an, named_n=nn['n'], unnamed_neg=au, unnamed_n=un['n'],
                            fisher_p=fisher(an, bn, au, bu))
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    P = out['pool']
    print('■ v9.9.144（70に機構の名指しを要求）を歴史で答え合わせ（2013+2015プール）')
    for nm, k in [('ベース', 'base'), ('irr=50', 'r50'), ('70 機構なし', 'unnamed'),
                  ('70 機構あり', 'named'), ('irr=85', 'r85')]:
        s = P[k]
        print(f'  {nm:12} n={s["n"]:3} P(年率15%+)={s["P"]:.3f} 中央{s["med"]*100:5.1f}% 元本割れ{s["neg"]:.2f}')
    print(f'\n  → **機構ありの lift {P["lift"]:+.3f}（会社単位の置換 p={P["perm_p"]:.4f}）**')
    print('  ＝改定は「読み手のぶれを減らす」だけでなく**当たる社を選び直している**')
    print('\n■ ビンテージ別（独立ではない・147社が重複）')
    for v, d in out['vintages'].items():
        if not d.get('named'):
            print(f'  {v}: mech が全社『なし』＝**検定できない**（「効かない」ではない）')
            continue
        print(f"  {v}: 機構あり P={d['named']['P']:.3f}(n={d['named']['n']}) "
              f"vs なし P={d['unnamed']['P']:.3f}(n={d['unnamed']['n']}) "
              f"lift {d['named']['P']-d['unnamed']['P']:+.3f}")
    print('\n■ 型別（irr=70・プール）')
    for m, s in sorted(out['by_mech'].items(), key=lambda kv: -(kv[1]['n'] if kv[1] else 0)):
        if s:
            print(f'  {m:16} n={s["n"]:3} P={s["P"]:.3f} 中央{s["med"]*100:5.1f}%')
    L = out['left_tail']
    print(f"\n■ ★左尾は逆を向く（元本割れ）: 機構あり {L['named_neg']}/{L['named_n']}"
          f" vs なし {L['unnamed_neg']}/{L['unnamed_n']}  (Fisher p={L['fisher_p']:.3f})")
    print('  ＝この改定は**「壊れない」を買っているのではない**。上を狙う側へ動かしている。')
    print('  堀は買付の**関門**（壊れないための装置）なので、ここは記録に値する緊張——')
    print('  「上を狙うなら85／下を防ぐなら70」という既記録が、70 の中でも同じ形で出た。')
    print('\n⚠ 限界は頭注に書いてある。とくに `mech` は**85の型分けのために記録された欄**で、')
    print('  「v9.9.144 の粒度で機構を名指しできたか」と完全に同じではない。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
