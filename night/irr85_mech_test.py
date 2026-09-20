#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_mech_test.py — **irr=85 の中を「歴史的に複利中央値が高い型」で絞れるかを検定する**（2026-08-09新設）

発端（ユーザー指示「irr85は歴史的にみて今後も複利中央値が高いと見込めるものだけ
特別にポートフォリオにいれたい」）。門は irr=85 に**二つの特別扱い**を与えている——
  (1) **別枠85**（v9.9.119/122）＝Ω75+ を免除して買付の土俵に上げる
  (2) **席の優先**（v9.9.100・ccfAllocTop）＝上位10席で irr=85 を先に置く
その特別扱いを「歴史的に高い型」だけに限れるか、を測る。

**先に検定の設計を書く（結果を見てから軸を選ばないため）。** 絞る軸の候補は2つしかない:
  軸A **機構の型**（A工程認定/B設計組込/C第三者が用途を認定/D認定業者名簿/E長期認定期間）
  軸B **その社自身の実現実績**（今日の14社のうち11社は歴史のコホート本人で年率が判っている）
軸を規則にしてよい条件も先に置く: **(i) 型ごとの n が結論に耐える (ii) 同じ文を別の読み手が
同じ型に分類する（ラベルが再現する）**。この2条件を満たさない軸で買付を止めるのは、
この台帳が繰り返し退けてきた curve-fitting になる。

【この道具が出す3つの表】
  1. 機構の型ごとの実績（2013/2015ビンテージの読解が mech ラベルを持つ のべ19件）
  2. **ラベルの再現性**——同じ社を2つのビンテージで読んだとき mech は一致したか
  3. 今日の irr=85 14社 × 全ての窓の実現年率（軸B）

使い方: python3 night/irr85_mech_test.py [--json] [--hurdle 0.15]
出力: out/irr85_mech_test.json
"""
import glob
import datetime, json
import os
import statistics as st
import sys

# ⚠ generated は**実行時**に採る。2026-09-19まで '2026-08-09' を焼き付けており、
#   回転盤(ops_status)の錨が out/irr85_history.json の generated なので、
#   **毎月回っているのに永久に「止まっている」と表示されていた**（同日 irr85_er.py でも同型を直した）。
TODAY = datetime.date.today().isoformat()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
H = float(sys.argv[sys.argv.index('--hurdle') + 1]) if '--hurdle' in sys.argv else 0.15

# 読解ファイル → (ビンテージ名, リターン在庫)
READS = [('out/retro_moat_2013.json', '2013', 'out/retro_returns_2013_all.json'),
         ('out/retro_moat_2013q.json', '2013', 'out/retro_returns_2013_all.json'),
         ('out/retro_moat_2015.json', '2015', 'out/retro_returns_2015_q.json'),
         ('out/retro_moat_2015q.json', '2015', 'out/retro_returns_2015_q.json'),
         ('out/retro_moat_2015qb.json', '2015', 'out/retro_returns_2015_q.json')]
WINDOWS = [('13.1年(2013→)', 'out/retro_returns_2013_all.json'),
           ('11.1年(2015→)', 'out/retro_returns_2015_q.json'),
           ('8.1年(2018→)', 'out/retro_returns_2018.json')]


def load_returns(path):
    d = json.load(open(path, encoding='utf-8'))
    return {r['ticker']: r['tr_cagr'] for r in d['rows']}


def stats(v):
    return dict(n=len(v), med=st.median(v), p15=sum(1 for x in v if x >= H) / len(v),
                loss=sum(1 for x in v if x < 0) / len(v),
                ruin=sum(1 for x in v if x <= -0.15) / len(v), worst=min(v))


def main():
    RET = {p: load_returns(p) for _, p in WINDOWS}
    rows, by_t = [], {}
    for f, v, rp in READS:
        if not os.path.exists(f):
            continue
        for r in json.load(open(f, encoding='utf-8'))['rows']:
            if r.get('irr') != 85:
                continue
            t = r.get('ticker') or r.get('t')
            tr = RET.get(rp, {}).get(t)
            if tr is None:
                continue
            rec = dict(v=v, t=t, mech=r.get('mech') or '不明', tense=r.get('tense'), tr=tr,
                       quote=(r.get('quote') or '')[:160])
            rows.append(rec)
            by_t.setdefault(t, []).append(rec)

    print(f'■ 表1  機構の型ごとの実績（2013/2015ビンテージの読解・**のべ{len(rows)}件**・ハードル年{H:.0%}）')
    print(f"  {'機構':<18}{'n':>4}{'中央値':>9}{'年15%+':>8}{'元本割れ':>9}{'恒久毀損':>9}{'最悪':>9}  銘柄")
    order = ['A工程認定', 'E長期認定期間', 'C第三者が用途を認定', 'D認定業者名簿', 'B設計組込']
    tab = {}
    for m in order:
        g = [r for r in rows if r['mech'] == m]
        if not g:
            continue
        s = stats([r['tr'] for r in g])
        tab[m] = s
        who = ' '.join(sorted({r['t'] for r in g}))
        print(f"  {m:<17}{s['n']:>4}{s['med']*100:>8.1f}%{s['p15']:>8.2f}{s['loss']:>9.2f}"
              f"{s['ruin']:>9.2f}{s['worst']*100:>8.1f}%  {who}")
    s = stats([r['tr'] for r in rows])
    print(f"  {'合計':<17}{s['n']:>4}{s['med']*100:>8.1f}%{s['p15']:>8.2f}{s['loss']:>9.2f}"
          f"{s['ruin']:>9.2f}{s['worst']*100:>8.1f}%")
    print('  ⚠ **どの型も n=2〜8**。同じ社が2ビンテージで重複して数えられている（独立標本ではない）')

    print('\n■ 表2  ラベルの再現性——同じ社を2つのビンテージで読んだとき mech は一致したか')
    multi = {t: v for t, v in by_t.items() if len({r['v'] for r in v}) >= 2}
    agree = 0
    for t, v in sorted(multi.items()):
        ms = {r['v']: r['mech'] for r in v}
        ok = len(set(ms.values())) == 1
        agree += ok
        print(f"  {t:<6} {'○一致' if ok else '**×不一致**'}  " +
              ' / '.join(f'{k}:{x}' for k, x in sorted(ms.items())))
    print(f'  → 2ビンテージで読まれた {len(multi)}社のうち mech 一致は {agree}社'
          f'（**irr の刻み 85 自体は一度も揺れていない**——追試の147社一致率90.5%）')
    cw = [r for r in by_t.get('CW', []) if r['mech']]
    if len({r['mech'] for r in cw}) > 1:
        print('  ★CW は **まったく同じ引用**で2013読解=D認定業者名簿 / 2015読解=C第三者が用途を認定 に割れた:')
        for r in cw:
            print(f"     {r['v']} [{r['mech']}] 「{r['quote'][:96]}…」")

    print(f'\n■ 表3  今日の irr=85 を「その社自身の実績」で並べる（軸B）')
    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    today = {}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        x = x.get('data') or x
        if x.get('irr') == 85:
            today[t] = x
    hist = {}
    for t in today:
        hist[t] = [RET[p].get(t) for _, p in WINDOWS]
    ordr = sorted(today, key=lambda t: -(st.median([x for x in hist[t] if x is not None])
                                         if any(x is not None for x in hist[t]) else -9))
    print(f"  {'':<7}{'13.1年':>9}{'11.1年':>9}{'8.1年':>9}{'中央値':>9}"
          f"{'長い複利':>9}{'Ω':>7}{'堀':>6}  門   歴史の読解")
    out = []
    for t in ordr:
        h = hist[t]
        med = st.median([x for x in h if x is not None]) if any(x is not None for x in h) else None
        sa = SA.get(t, {})
        stt = '🟢' if sa.get('buy') else ('🔵' if sa.get('quali') else '⛔')
        # 「長い複利」＝重ならない前半(2013→2018)と後半(2018→2026)を両方 15%+
        pre = None
        if h[0] is not None and h[2] is not None:
            pre = ((1 + h[0]) ** 13.09 / (1 + h[2]) ** 8.09) ** (1 / 5.0) - 1
        lg = ('★' if (pre is not None and pre >= H and h[2] >= H)
              else ('—' if pre is not None else '追えない'))
        rd = ' '.join(sorted({f"{r['v']}:{r['mech']}" for r in by_t.get(t, [])})) or '歴史の読解なし'
        f = lambda x: (f'{x*100:>8.1f}%' if x is not None else f"{chr(8212):>9}")
        print(f"  {t:<7}{f(h[0])}{f(h[1])}{f(h[2])}{f(med)}{lg:>9}"
              f"{str(sa.get('s')):>7}{str(sa.get('moat')):>6}  {stt}   {rd}")
        out.append(dict(t=t, r13=h[0], r15=h[1], r18=h[2], med=med, pre=pre,
                        s=sa.get('s'), moat=sa.get('moat'), buy=bool(sa.get('buy')),
                        quali=bool(sa.get('quali')), reads=rd))
    kn = [o for o in out if o['med'] is not None]
    print(f"  → 実績が追えるのは {len(kn)}/{len(out)}社。うち中央値が年{H:.0%}+ は"
          f" {sum(1 for o in kn if o['med'] >= H)}社")
    print('  ⚠ ASML/VRSK/LOAR は米国10-K経路の在庫に無い（ASML=20-F提出体・LOAR=2024年IPO・'
          'VRSK=コホートscreenが自己資本マイナスで落とした＝ルール7の10例目）')

    # ── 門が読む正本を必ず書く（v9.9.124）─────────────────────────────────────
    #   別枠85と席の優先は**特権**なので、「その社自身の実現複利が歴史のハードルを割っている」と
    #   **判っている**社からは取り上げる。**実績が追えない社は中立**（＝取り上げない）——
    #   在庫の境界（米国10-K・2013年コホート）は我々の道具の限界であって会社の性質ではないから。
    items = {}
    for o in out:
        if o['med'] is None:
            continue
        items[o['t']] = dict(med=round(o['med'], 4),
                             w={'13.1': o['r13'], '11.1': o['r15'], '8.1': o['r18']},
                             verdict='below' if o['med'] < H else 'above')
    gp = 'out/irr85_history.json'
    json.dump({'generated': TODAY, 'hurdle': H,
               'note': 'その社自身の実現複利（配当込み・重なる3窓の中央値）。verdict=below は '
                       'irr=85 の特権（別枠85・席の優先）を取り上げる。**載っていない社は中立**'
                       '——在庫は米国10-K・2013年コホートに限られ、載らない理由は会社ではなく道具の側にある',
               'items': items}, open(gp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"\n→ {gp}（実績あり{len(items)}社・うち verdict=below は "
          f"{sum(1 for v in items.values() if v['verdict']=='below')}社）")

    if AS_JSON:
        p = 'out/irr85_mech_test.json'
        json.dump({'generated': TODAY, 'hurdle': H, 'mech_table': tab,
                   'mech_rows': rows, 'label_stability': {t: {r['v']: r['mech'] for r in v}
                                                          for t, v in multi.items()},
                   'today': out}, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
