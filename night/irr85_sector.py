#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_sector.py — **irr=85 は業種効果か**を、業種を揃えて測る（2026-09-18新設）

■ なぜ要るか
  ユーザーの問い「irr85 はたまたまではないのか？ 航空と半導体に偏っていることから
  **業界が良かったからよく見えた**のでは」。偏りの観察は正しい——今日の台帳の irr=85 は
  15社中11社(73%)が半導体か航空防衛、歴史の28社でも21社(75%)。
  ところが **『85が居る業種そのものが良かったのか』は一度も測っていなかった**。
  既記録にあるのは 2018年ビンテージの同一SIC2内比較（0.70 vs 0.18）だけで、
  **全ビンテージで業種のベースラインを引いた残差**も、**層内の置換検定**も無かった。

■ 何を測るか（3つとも「業種が良かっただけか」への直接の答え）
  ① 業種そのものの効き … 『85と同じ業種の“他の社”』 vs 『85が一人もいない業種』
     ——業界が良かっただけなら、同業他社も同じだけ上がっているはず
  ② 業種の中での上乗せ … 各社から同SIC2の中央値を引いた残差を刻み別に見る
  ③ 層内の置換 … 業種を固定したまま irr のラベルだけ混ぜる（2000回）

■ 判定は一つも持たない。値も規約も採点式も関門も売却規律も配分も触らない。
  これは**記述**であって、門の刻みの根拠を作り直す器ではない。

■ 読み方の注意
  ⚠ 社単位へ畳んでから数える。のべ件数だと同じ社が複数ビンテージで何度も効く
    （実測: irr=85 はのべ38件だが実28社。CMTL と LRCX＝分布の両端が二重に入る）
  ⚠ 半導体の集合は irr85_evidence.SEMI を import（二重に持たない）。
    **航空防衛の集合はこの器が新しく置く判断**なので、--list で1社ずつ出して
    誰でも引き直せるようにする（v9.9.143「分類を1社ずつSICつきで出す」の作法）
  ⚠ 層は3社以上の業種だけ。層が作れない＝**「効かない」ではなく「測れない」**

使い方:
  python3 night/irr85_sector.py           人が読む形
  python3 night/irr85_sector.py --json    out/irr85_sector.json を書く
  python3 night/irr85_sector.py --list    半導体/航空防衛の割り当てを1社ずつ
"""
import json
import os
import random
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv
LIST = '--list' in sys.argv
SEED = 20260918

# ★航空防衛の集合＝**この器が置く判断**であって測定ではない。--list で引き直せる。
#   線は「FAA/DoD/NRC 等の第三者認証が製品そのものに掛かる製造業」。
#   ⚠ 機体の運航者（航空会社）や総合防衛の元請は入れていない——機構が別だから。
AERO = set('BWXT CW HEI TDG RBC HXL KRMN LOAR SPR TGI MOG-A ATRO DCO VSEC WWD'.split())

# SIC 2桁の区分名（SIC の Major Group。公式の区分であって、この器の判断ではない）
SIC2NAME = {
    '28': '化学・医薬', '30': 'ゴム・プラスチック', '33': '一次金属',
    '34': '金属製品', '35': '産業機械・コンピュータ', '36': '電子・電気機器',
    '37': '輸送機器（航空を含む）', '38': '計測・分析機器', '48': '通信',
    '67': '持株・投資', '73': 'ビジネスサービス',
}


def _ev():
    """irr85_evidence.py の読み込み部をそのまま使う（v9.9.65: 二重に持たない）"""
    src = open('night/irr85_evidence.py').read()
    ns = {'__name__': 'notmain', '__file__': os.path.abspath('night/irr85_evidence.py')}
    exec(compile(src, 'irr85_evidence.py', 'exec'), ns)
    return ns


def rung_group(r):
    if r == 85:
        return 85
    if r == 100:
        return 100
    if r in (70, 75):       # 2018年の班だけ中間が 75
        return 70
    return 50


def p15(xs):
    return (sum(1 for x in xs if x >= 0.15) / len(xs)) if xs else None


def build():
    ns = _ev()
    rows = ns['load_reads']()[0]
    semi = set(ns['SEMI'])
    sicj = ns['jload']('retro_sic.json') or {}
    sic = {r.get('ticker') or r.get('t'): r for r in (sicj.get('rows') or [])}

    # ★0件の検問（門0のBOM事故・hist_val_market の探索下限と同族）
    #   「照合が成立していない0」を「該当なし」と読ませない
    if not rows:
        raise SystemExit('読解が1件も読めない——測っていないのであって、85が無いのではない')
    if not sic:
        raise SystemExit('retro_sic.json が読めない——業種を揃える検定は成立しない')

    by = {}
    for r in rows:
        if r.get('rung') is None or r.get('cagr') is None:
            continue
        by.setdefault(r['t'], []).append(r)
    if not by:
        raise SystemExit('刻みと実現リターンの両方がそろう行が0件'
                         '——リターンのキーは tr_cagr（cagr ではない）。照合を確かめること')

    comp = []
    for t, rs in by.items():
        # ⚠ キーは sicDesc / sic2（sic_desc ではない）。外すと業種名が静かに空欄になる
        sr = sic.get(t) or {}
        s2v = sr.get('sic2') or (str(sr.get('sic') or '')[:2] or None)
        comp.append({
            't': t,
            'g': rung_group(max(x['rung'] for x in rs)),
            'tr': st.median([x['cagr'] for x in rs]),
            's2': s2v or None,
            'nm': sr.get('sicDesc') or '',
            'semi': t in semi,
            'aero': t in AERO,
        })

    out = {'generated': __import__('datetime').date.today().isoformat(),
           'tool': 'night/irr85_sector.py',
           'role': 'irr=85 が業種効果かを測る記述。**判定は一つも持たない**',
           'n_companies': len(comp),
           'n_with_sic': sum(1 for c in comp if c['s2'])}

    # --- 0) 除外を積み上げたときの刻み別
    def cut(label, sel):
        d = {'label': label}
        for g in (50, 70, 85, 100):
            v = [c['tr'] for c in comp if c['g'] == g and sel(c)]
            d[str(g)] = {'n': len(v), 'p15': p15(v),
                         'median': st.median(v) if v else None}
        a = [c['tr'] for c in comp if c['g'] == 85 and sel(c)]
        b = [c['tr'] for c in comp if c['g'] == 70 and sel(c)]
        d['85_minus_70'] = (p15(a) - p15(b)) if a and b else None
        return d
    out['刻み別'] = [
        cut('全部', lambda c: True),
        cut('半導体を外す', lambda c: not c['semi']),
        cut('航空防衛を外す', lambda c: not c['aero']),
        cut('半導体も航空防衛も外す', lambda c: not c['semi'] and not c['aero']),
    ]
    out['85の内訳'] = {
        'semi': sorted(c['t'] for c in comp if c['g'] == 85 and c['semi']),
        'aero': sorted(c['t'] for c in comp if c['g'] == 85 and c['aero']),
        'other': [{'t': c['t'], 'tr': c['tr']} for c in
                  sorted((c for c in comp if c['g'] == 85 and not c['semi'] and not c['aero']),
                         key=lambda x: -x['tr'])],
    }

    # --- 1) 業種そのものの効き / 業種の中での上乗せ
    bys2 = {}
    for c in comp:
        if c['s2']:
            bys2.setdefault(c['s2'], []).append(c)
    usable = {k: v for k, v in bys2.items() if len(v) >= 3}
    has85 = set(k for k, v in usable.items() if any(c['g'] == 85 for c in v))
    A = [c['tr'] for k, v in usable.items() if k in has85 for c in v if c['g'] != 85]
    B = [c['tr'] for k, v in usable.items() if k not in has85 for c in v]
    C = [c['tr'] for k, v in usable.items() if k in has85 for c in v if c['g'] == 85]
    out['業種の効き'] = {
        'note': '業界が良かっただけなら、85と同業の“他の社”も 85不在の業種より上がっているはず',
        'n_usable_sic': len(usable),
        '同業他社': {'n': len(A), 'median': st.median(A) if A else None, 'p15': p15(A)},
        '85不在の業種': {'n': len(B), 'median': st.median(B) if B else None, 'p15': p15(B)},
        '85そのもの': {'n': len(C), 'median': st.median(C) if C else None, 'p15': p15(C)},
        '業種そのものの効き_pt': ((st.median(A) - st.median(B)) * 100) if A and B else None,
        '業種の中での85の上乗せ_pt': ((st.median(C) - st.median(A)) * 100) if A and C else None,
    }

    # --- 2) 業種の中央値を引いた残差
    for c in comp:
        c['ex'] = None
        if c['s2'] in usable:
            c['ex'] = c['tr'] - st.median([x['tr'] for x in usable[c['s2']]])
    res = {}
    for g in (50, 70, 85, 100):
        v = [c['ex'] for c in comp if c['g'] == g and c['ex'] is not None]
        res[str(g)] = {'n': len(v),
                       'median_pt': (st.median(v) * 100) if v else None,
                       'frac_positive': (sum(1 for x in v if x > 0) / len(v)) if v else None}
    out['業種調整の残差'] = res

    # --- 3) 業種別の内訳
    det = []
    # ⚠ has85 は set なので、同点の並びは PYTHONHASHSEED で変わる（数字は同じでも出力が揺れる）。
    #   決定的でない出力は「同じ入力で同じ答えが出る」という検算そのものを壊すので、
    #   最後に sic2 を入れて並びを完全に決める（hist_val_regime で踏んだのと同型）
    for k in sorted(has85, key=lambda k: (-sum(1 for c in usable[k] if c['g'] == 85), k)):
        v = usable[k]
        a = [c['tr'] for c in v if c['g'] == 85]
        b = [c['tr'] for c in v if c['g'] != 85]
        det.append({'sic2': k,
                    'name': SIC2NAME.get(k) or next((c['nm'] for c in v if c['nm']), ''),
                    'n85': len(a), 'median85': st.median(a),
                    'nother': len(b), 'median_other': st.median(b) if b else None,
                    'diff_pt': ((st.median(a) - st.median(b)) * 100) if b else None})
    out['業種別'] = det

    # --- 4) 層内の置換（業種を固定して irr のラベルだけ混ぜる）
    def perm(sel, label):
        strata, real = [], []
        for v in usable.values():
            vv = [c for c in v if sel(c)]
            if len(vv) >= 3 and any(c['g'] == 85 for c in vv) and any(c['g'] != 85 for c in vv):
                strata.append(vv)
                real.append(set(i for i, c in enumerate(vv) if c['g'] == 85))
        n85 = sum(len(x) for x in real)
        if n85 < 3:
            return {'label': label, 'n85': n85,
                    'verdict': '⚠測れない（層の中の85が3社未満）＝「効かない」ではない'}

        def stat(asg):
            tot = k = 0
            for v, idx in zip(strata, asg):
                for i, c in enumerate(v):
                    if i in idx:
                        tot += (1 if c['tr'] >= 0.15 else 0)
                        k += 1
            return tot / k if k else 0
        obs = stat(real)
        rnd = random.Random(SEED)
        null, cnt = [], 0
        for _ in range(2000):
            asg = [set(rnd.sample(range(len(v)), len(idx))) for v, idx in zip(strata, real)]
            s = stat(asg)
            null.append(s)
            cnt += (s >= obs)
        null.sort()
        return {'label': label, 'n_strata': len(strata), 'n85': n85, 'observed': obs,
                'null_median': null[1000], 'null_p05': null[100], 'null_p95': null[1900],
                'p': (cnt + 1) / 2001}
    out['層内の置換'] = [perm(lambda c: True, '全部'),
                         perm(lambda c: not c['semi'], '半導体を外す'),
                         perm(lambda c: not c['semi'] and not c['aero'], '半導体も航空防衛も外す')]

    out['限界'] = [
        '3ビンテージ(2013/2015/2018)は同じ956ティッカーの母集団で、窓はすべて2026年で終わる＝out-of-sample はゼロ',
        '社単位へ畳んでも、同じ社が複数ビンテージにいると窓の長さが混ざる',
        'SIC2桁は粗い。半導体の社が複数のSIC2に散る（3674/3559/3827/3089…）ので、層の切り方で数字は動く',
        '航空防衛の集合はこの器が置いた判断（--list で引き直せる）',
        '読解はLLM（人手の再現検定は irr で90.5%まで）／生存バイアスは既記録のまま',
    ]
    return comp, out


def main():
    comp, out = build()
    if LIST:
        print('■ 半導体 / 航空防衛 の割り当て（**判断**であって測定ではない）')
        for c in sorted((c for c in comp if c['g'] == 85), key=lambda x: -x['tr']):
            k = '半導体' if c['semi'] else ('航空防衛' if c['aero'] else '——')
            print('   %-6s %-8s SIC %-4s %-34s 実現 %+6.1f%%'
                  % (c['t'], k, c['s2'] or '—', (c['nm'] or '')[:34], c['tr'] * 100))
        return
    if AS_JSON:
        json.dump(out, open('out/irr85_sector.json', 'w'), ensure_ascii=False, indent=1)
        print('→ out/irr85_sector.json  （社 %d / SICあり %d）'
              % (out['n_companies'], out['n_with_sic']))
        return

    print('■ irr=85 は業種効果か  社単位 n=%d（SIC2が取れた %d社）'
          % (out['n_companies'], out['n_with_sic']))
    print()
    print('① 刻み別 P(実現年率15pct以上)')
    for d in out['刻み別']:
        cells = '  '.join('%d: %s(n=%d)' % (g, ('%.2f' % d[str(g)]['p15']) if d[str(g)]['p15'] is not None else '—',
                                            d[str(g)]['n']) for g in (50, 70, 85, 100))
        dd = d['85_minus_70']
        print('   %-24s %s   85-70 = %s' % (d['label'], cells, ('%+.2f' % dd) if dd is not None else '—'))
    o = out['85の内訳']
    print('   ◆85のうち 半導体%d / 航空防衛%d / どちらでもない%d'
          % (len(o['semi']), len(o['aero']), len(o['other'])))
    print('   ◆どちらでもない: ' + ', '.join('%s %+.0f%%' % (x['t'], x['tr'] * 100) for x in o['other']))
    print()
    e = out['業種の効き']
    print('② ★業種そのものの効き vs 業種の中での上乗せ（使える業種 %d＝3社以上）' % e['n_usable_sic'])
    for k in ('同業他社', '85不在の業種', '85そのもの'):
        v = e[k]
        print('   %-14s n=%-4d 中央値 %+6.2f%%  P15 %.2f' % (k, v['n'], v['median'] * 100, v['p15']))
    print('   ⇒ 業種そのものの効き        %+.2fpt' % e['業種そのものの効き_pt'])
    print('   ⇒ 業種の中での85の上乗せ    %+.2fpt' % e['業種の中での85の上乗せ_pt'])
    print()
    print('③ 業種の中央値を引いた残差')
    for g in (50, 70, 85, 100):
        r = out['業種調整の残差'][str(g)]
        if r['median_pt'] is None:
            continue
        print('   %-3d n=%-3d 残差の中央値 %+6.2fpt  残差>0 %.2f' % (g, r['n'], r['median_pt'], r['frac_positive']))
    print()
    print('④ 業種別の内訳')
    for d in out['業種別']:
        print('   SIC%-3s %-30s 85が%d社 %+6.1f%% | 他%3d社 %+6.1f%%  差 %+6.1fpt'
              % (d['sic2'], (d['name'] or '')[:30], d['n85'], d['median85'] * 100,
                 d['nother'], (d['median_other'] or 0) * 100, d['diff_pt'] or 0))
    print()
    print('⑤ ★層内の置換（業種は固定・irrのラベルだけ混ぜる・2000回）')
    for d in out['層内の置換']:
        if 'observed' not in d:
            print('   %-24s %s' % (d['label'], d['verdict']))
            continue
        print('   %-24s 層%d／85が%d社  実測 %.3f  帰無中央 %.3f(90pct帯 %.3f〜%.3f)  p=%.4f'
              % (d['label'], d['n_strata'], d['n85'], d['observed'],
                 d['null_median'], d['null_p05'], d['null_p95'], d['p']))
    print()
    for l in out['限界']:
        print('   ⚠ ' + l)


if __name__ == '__main__':
    main()
