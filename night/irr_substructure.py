#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr_substructure.py — **irr=70 の中に、継続を分ける下位構造はあるか**（事前登録 Q1）

事前登録: out/irr_precision_prereg.json（結果を見る前に固定・commit 7033858）
  合格の線 = lift>=0.15 ∧ 分子(該当かつ継続)>=5 ∧ 2013系と2015系で符号が反転しない
  **線も候補もここで動かさない。**

【なぜこの問いか】v11 の実験で「irr=70 の中では誰も区別できない」と出た
（判定圏の45/49社が70・変動係数6.6%）。ところが**歴史の読解には irr=70 の中に下位構造が
記録されている**——のべ131件のうち機構の型 mech が57件で命名済み、時制は完了形89/願望形18、moat5 は全件。
**今日の台帳はこれを 85 にしか記録していない**（それも2026-08-12に入れたばかり）。
つまり「70の中を分ける情報」は原理的に取れるのに、台帳が捨てている可能性がある。

【踏まないようにしたこと】
  ・**ティッカー単位で扱う**（同じ社が複数ファイルに出る。行単位で数えると重複で n を水増しする）
  ・**ビンテージを 2013系 / 2015系 に分ける**（符号の反転を見るのが合格の線に入っているため）
  ・**到達可能性・実効的に要求される lift・偽陽性率を、合否の前に出す**
    （v1 hist_val で「基準が構造的に成立しえなかった」、v2 で「MIN_NUM が LIFT を上書きしていた」を
      後から知った失敗の再演を防ぐ）
  ・置換は**ティッカー単位で全ビンテージ同時に**混ぜる（ビンテージ内で独立に混ぜると従属が壊れ、
    偽陽性率を桁で過小評価する。CLAUDE.md の実測: 0.002 vs 0.062＝33倍）

使い方: python3 night/irr_substructure.py [--json]
出力: out/irr_substructure.json
"""
import glob
import json
import os
import random
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

WIN = 0.15          # 既存のハードル。新しい定数を作らない
LIFT_LINE = 0.15    # 事前登録
MIN_NUM = 5         # 事前登録

# 読解ファイル → ビンテージ（2018系はキー名が違うので別扱い。下で正規化する）
READ = {'out/retro_moat_2013.json': '2013', 'out/retro_moat_2013q.json': '2013',
        'out/retro_moat_2015.json': '2015', 'out/retro_moat_2015q.json': '2015',
        'out/retro_moat_2015qb.json': '2015'}
# ビンテージ → 実現リターンの在庫（優先順。先に見つかったものを使う）
RET = {'2013': ['out/retro_returns_2013_all.json', 'out/retro_returns_2013.json'],
       '2015': ['out/retro_returns_2015_q.json', 'out/retro_returns_2015.json']}


def rows_of(path):
    d = json.load(open(path, encoding='utf-8'))
    r = d.get('rows') or d.get('items') or d
    return list(r.values()) if isinstance(r, dict) else r


def returns(vint):
    """{ticker: tr_cagr}。**どのファイルから引いたか**を返す（在庫の出所を必ず記録する）"""
    out, src = {}, []
    for p in RET[vint]:
        if not os.path.exists(p):
            continue
        for x in rows_of(p):
            t = str(x.get('ticker') or '').upper()
            if t and x.get('tr_cagr') is not None and t not in out:
                out[t] = x['tr_cagr']
        src.append(p)
    return out, src


def load():
    """{ (vintage, ticker): {irr, mech, tense, quote, moat5, tr} }。ティッカー単位で畳む。
       同じ社が同じビンテージの複数ファイルに出たら**最初に読んだものを採る**（件数を水増ししない）。"""
    rec, srcs = {}, {}
    for p, v in READ.items():
        if not os.path.exists(p):
            continue
        for x in rows_of(p):
            t = str(x.get('ticker') or '').upper()
            if not t or x.get('irr') is None:
                continue
            k = (v, t)
            if k in rec:
                continue
            rec[k] = {'irr': int(x['irr']), 'mech': x.get('mech'), 'tense': x.get('tense'),
                      'moat5': x.get('moat5'), 'qlen': len(x.get('quote') or ''), 'src': p}
    for v in ('2013', '2015'):
        r, s = returns(v)
        srcs[v] = s
        for (vv, t), d in rec.items():
            if vv == v:
                d['tr'] = r.get(t)
    return rec, srcs


def stat(g):
    tr = [d['tr'] for d in g if d.get('tr') is not None]
    if not tr:
        return {'n': 0, 'n_tr': 0}
    return {'n': len(g), 'n_tr': len(tr),
            'win': sum(1 for v in tr if v >= WIN),
            'p_win': round(sum(1 for v in tr if v >= WIN) / len(tr), 3),
            'median': round(statistics.median(tr) * 100, 2)}


def main():
    rec, srcs = load()
    g70 = {k: d for k, d in rec.items() if d['irr'] == 70}
    out = {'generated': '2026-08-12', 'tool': 'night/irr_substructure.py',
           'prereg': 'out/irr_precision_prereg.json Q1（線は動かしていない）',
           'sources': {'readings': list(READ.keys()), 'returns': srcs},
           'hurdles': {'win': WIN, 'lift_line': LIFT_LINE, 'min_num': MIN_NUM}}

    # ── 照合の検算（既記録の刻み別 P を再現できるか。**0件を発見と読む前に照合を確かめる**）──
    out['照合の検算'] = {}
    for v in ('50', '70', '85', '100'):
        g = [d for d in rec.values() if d['irr'] == int(v)]
        out['照合の検算'][f'irr={v}'] = stat(g)
    out['照合の検算']['既記録との突合'] = ('プール754件で 50:0.162 / 70:0.366 / 85:0.579 / 100:0.056〜0.091。'
                                          '母集団の作り方（ティッカー単位・2013/2015系のみ）が違うので'
                                          '**一致しなくてよい。向きが同じかだけを見る**')

    base = stat(list(g70.values()))
    out['母集団'] = {'irr=70 のティッカー×ビンテージ': len(g70), **base,
                     'ビンテージ別': {v: stat([d for (vv, _), d in g70.items() if vv == v])
                                      for v in ('2013', '2015')}}

    # ── 事前登録の6候補 ─────────────────────────────────────────
    MECH_3RD = {'A工程認定', 'C第三者が用途を認定', 'D認定業者名簿', 'E長期認定期間'}
    qmed = statistics.median([d['qlen'] for d in g70.values()]) if g70 else 0
    CANDS = [
        ('mech!=なし（機構の型が命名できる）', lambda d: d.get('mech') not in (None, 'なし')),
        ('mech∈第三者が認定する型', lambda d: d.get('mech') in MECH_3RD),
        ('mech==B設計組込', lambda d: d.get('mech') == 'B設計組込'),
        ('tense==完了形', lambda d: d.get('tense') == '完了形'),
        ('moat5>=4', lambda d: (d.get('moat5') or 0) >= 4),
        (f'引用長 上位1/2（>{int(qmed)}字）', lambda d: d['qlen'] > qmed),
    ]

    res = []
    for name, f in CANDS:
        hit = [d for d in g70.values() if f(d)]
        no = [d for d in g70.values() if not f(d)]
        a, b = stat(hit), stat(no)
        # **到達可能性を合否の前に出す**——神の分類器でも分子>=5 が成立しうるか
        reach = {'該当社数(リターンあり)': a.get('n_tr', 0),
                 '該当の中の継続社数': a.get('win', 0),
                 '分子>=5 は原理的に可能か': a.get('win', 0) >= MIN_NUM}
        # **実効的に要求される lift**（分子の下限が lift を上書きしていないか）
        eff = None
        if a.get('n_tr'):
            need_p = MIN_NUM / a['n_tr']
            eff = round(max(LIFT_LINE, need_p - (b.get('p_win') or 0)), 4)
        lift = None if not (a.get('n_tr') and b.get('n_tr')) else round(a['p_win'] - b['p_win'], 4)
        per_v = {}
        for v in ('2013', '2015'):
            hv = [d for (vv, _), d in g70.items() if vv == v and f(d)]
            nv = [d for (vv, _), d in g70.items() if vv == v and not f(d)]
            av, bv = stat(hv), stat(nv)
            per_v[v] = {'lift': None if not (av.get('n_tr') and bv.get('n_tr'))
                                 else round(av['p_win'] - bv['p_win'], 4),
                        'n': av.get('n_tr', 0), 'win': av.get('win', 0)}
        signs = [x['lift'] for x in per_v.values() if x['lift'] is not None]
        no_flip = len(signs) >= 2 and (all(s > 0 for s in signs) or all(s <= 0 for s in signs))
        ok = (lift is not None and lift >= LIFT_LINE and a.get('win', 0) >= MIN_NUM and no_flip)
        res.append({'候補': name, '該当': a, '非該当': b, 'lift': lift,
                    '到達可能性': reach, '実効的に要求されるlift': eff,
                    'ビンテージ別': per_v, '符号が反転しない': no_flip, '合否': '✓' if ok else '✗'})
    out['候補'] = res

    # ── 偽陽性率（ティッカー単位・全ビンテージ同時に混ぜる）────────────────
    rnd = random.Random(20260812)
    tick = sorted({t for (_, t) in g70})
    lab = {}
    for (v, t), d in g70.items():
        if d.get('tr') is not None:
            lab.setdefault(t, []).append(d['tr'] >= WIN)
    pool = [t for t in tick if t in lab]
    hits = 0
    for _ in range(2000):
        perm = pool[:]
        rnd.shuffle(perm)
        remap = dict(zip(pool, perm))
        any_ok = False
        for name, f in CANDS:
            A = B_ = Aw = Bw = 0
            for (v, t), d in g70.items():
                if d.get('tr') is None or t not in remap:
                    continue
                w = (rec.get((v, remap[t])) or {}).get('tr')
                if w is None:
                    continue
                w = w >= WIN
                if f(d):
                    A += 1; Aw += w
                else:
                    B_ += 1; Bw += w
            if A and B_ and Aw >= MIN_NUM and (Aw / A - Bw / B_) >= LIFT_LINE:
                any_ok = True
                break
        hits += any_ok
    out['偽陽性率'] = {'置換': 2000, '1本でも合格が出る確率': round(hits / 2000, 4),
                       '注': 'ティッカー単位で全ビンテージ同時に混ぜる。ビンテージ内で独立に混ぜると'
                             '従属が壊れて偽陽性率を桁で過小評価する（CLAUDE.md 実測 0.002 vs 0.062）'}

    passed = [r['候補'] for r in res if r['合否'] == '✓']
    out['判定'] = {'合格': passed, '合格数': len(passed),
                   '結論': ('irr=70 の中に、事前登録の線を通る下位構造がある' if passed
                            else 'irr=70 の中に、事前登録の線を通る下位構造は**無い**')}
    out['この測定で言えないこと'] = [
        'out-of-sample はゼロ（2013系と2015系は同じ956ティッカーの母集団で、窓は2026で終わり重なる）',
        '読解はLLM。人の審査官の再現性ではない',
        'irr=50 は 580件すべて mech/tense が「なし」なので、**70と50の境界はこの下位構造では検定できない**',
        'mech/tense は 85 を探す読解の副産物で、70 に対して系統的に付けられたものではない（欠測が非ランダムでありうる）']
    json.dump(out, open('out/irr_substructure.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 0
    print(f"■ 母集団: irr=70 の ティッカー×ビンテージ {len(g70)}件"
          f"（リターンあり {base.get('n_tr')}件 / 継続 {base.get('win')}社 / P(勝) {base.get('p_win')}）")
    print(f"  ビンテージ別: " + ' ／ '.join(
        f"{v} n={s.get('n_tr')} P={s.get('p_win')}" for v, s in out['母集団']['ビンテージ別'].items()))
    print('\n■ 照合の検算（刻み別・向きが既記録と同じか）')
    for k, v in out['照合の検算'].items():
        if isinstance(v, dict) and v.get('n_tr'):
            print(f"  {k:<8} n={v['n_tr']:>3}  P(勝)={v['p_win']}  中央値{v['median']:>6.1f}%")
    print('\n■ 事前登録の6候補（線: lift>=0.15 ∧ 分子>=5 ∧ 符号反転なし）')
    for r in res:
        a = r['該当']
        print(f"  {r['候補'][:30]:<32} n={a.get('n_tr',0):>3} 継続{a.get('win',0):>2} "
              f"P={a.get('p_win')} lift={r['lift']} 実効要求={r['実効的に要求されるlift']} "
              f"反転なし={r['符号が反転しない']}  {r['合否']}")
    print(f"\n■ 偽陽性率（1本でも合格が出る確率）: {out['偽陽性率']['1本でも合格が出る確率']}")
    print(f"■ 判定: {out['判定']['結論']}（合格 {out['判定']['合格数']}本）")
    print('→ out/irr_substructure.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
