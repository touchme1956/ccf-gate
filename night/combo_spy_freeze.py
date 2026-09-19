#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/combo_spy_freeze.py — **NOT を足して家族の帰無を超えた規則を、事前登録の基準2〜4へ当てる**
（2026-09-19新設）

★事前登録(out/combo_spy_prereg.json)は書き換えていない。基準はそこに書いてあるものをそのまま使う:
   1. 探索アンカーで 超過 > 家族の帰無95%点   ← combo_spy_shapes.py が測った
   2. 凍結したまま、評価できる**全**アンカーで 超過 > 0
   3. 重ならない4窓のうち **3窓以上**で 超過 > 0
   4. 全アンカーで n >= 20
⚠ 基準は結果を見てから緩めない。⚠ 門にも触らない（絶対のルール1）。

使い方: python3 night/combo_spy_freeze.py [--B 300] [--json]
出力  : out/combo_spy_freeze.json
"""
import json, os, sys, datetime as dt
from itertools import combinations

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as C
from combo_spy_shapes import form_signed_atoms, form_and3, as_w, family_null_w, wexcess

OUT = os.path.join(BASE, 'out')
SEED = 20260919
MIN_N = C.MIN_N
SEARCH = '2013'

def signed_map(y, pool, SEMI):
    """そのアンカーの在庫で署名付き原子を作り直す（銘柄リストではなく**規則**を凍結する）。"""
    D = C.load_anchor(y)
    at = C.atoms(y, pool, D, SEMI)
    return {n: g for n, g, _ in form_signed_atoms(at)}

def apply_rule(parts, amap):
    g = None
    for p in parts:
        if p not in amap: return None, f'この窓に「{p}」が無い'
        g = set(amap[p]) if g is None else (g & amap[p])
    return g, None

def main():
    a = sys.argv[1:]
    B = int(a[a.index('--B')+1]) if '--B' in a else 300
    pan = C.panel(); spy = {int(k): v for k, v in C.L('_spy_monthly.json').items()}
    END = max(spy); SEMI = C.semi_set()
    k0 = int(SEARCH)*12+6; months = END-k0
    pool = C.anchor_pool(pan, k0, END)
    M = C.mults(pan, pool, k0, END); spym = spy[END]/spy[k0]
    amap0 = signed_map(SEARCH, pool, SEMI)

    at = C.atoms(SEARCH, pool, C.load_anchor(SEARCH), SEMI)
    sg = form_signed_atoms(at)
    cands = [(n, w) for n, w in form_and3(sg) if len(w) >= MIN_N]
    fam = family_null_w(cands, M, pool, spym, months, B, SEED)
    sc = sorted(((wexcess(w, M, spym, months), n, len(w)) for n, w in cands), reverse=True)
    win = [(e, n, ln) for e, n, ln in sc if e > fam['p95']]

    res = {'generated': dt.date.today().isoformat(), 'tool': 'night/combo_spy_freeze.py',
           'stance': '★事前登録の基準1〜4をそのまま当てる。基準は緩めない。門にも触らない（絶対のルール1）',
           'form': 'F2 = NOT込みの署名付き原子・3本まで AND',
           'B': B, 'n_candidates': len(cands), 'family_p95': fam['p95'],
           'family_med': fam['med'], 'family_max': fam['max'],
           'n_passed_criterion1': len(win)}

    rows = []
    for e, name, ln in win:
        parts = [p.strip() for p in name.split('∧')]
        rec = {'rule': name, 'search': {'n': ln, 'excess': round(e, 4)}, 'anchors': {}, 'windows': {}}
        for y in ('2015', '2016', '2017', '2018'):
            a0 = int(y)*12+6
            if a0 not in spy: rec['anchors'][y] = {'skip': 'SPYに月が無い'}; continue
            pl = C.anchor_pool(pan, a0, END)
            if len(pl) < 50: rec['anchors'][y] = {'skip': '母集団が薄い'}; continue
            am = signed_map(y, pl, SEMI)
            g, err = apply_rule(parts, am)
            if err: rec['anchors'][y] = {'skip': err}; continue
            if not g: rec['anchors'][y] = {'skip': '群が空'}; continue
            My = C.mults(pan, pl, a0, END); mo = END-a0
            rec['anchors'][y] = dict(n=len(g), excess=round(C.excess(g, My, spy[END]/spy[a0], mo), 4),
                                     years=round(mo/12, 2))
        for i in range(4):
            b0 = k0+39*i; b1 = b0+39
            if b1 not in spy: rec['windows'][f'W{i+1}'] = {'skip': 'SPYに月が無い'}; continue
            p2 = C.anchor_pool(pan, b0, b1)
            am2 = signed_map(SEARCH, p2, SEMI)   # 規則は探索アンカーの在庫で作る（窓だけ切る）
            g, err = apply_rule(parts, am2)
            if err or not g or len(g) < 5:
                rec['windows'][f'W{i+1}'] = {'skip': err or f'群 n={len(g) if g else 0}'}; continue
            M2 = C.mults(pan, p2, b0, b1)
            rec['windows'][f'W{i+1}'] = dict(n=len(g),
                                             excess=round(C.excess(g, M2, spy[b1]/spy[b0], 39), 4))
        aok = [v for v in rec['anchors'].values() if 'excess' in v]
        wok = [v for v in rec['windows'].values() if 'excess' in v]
        rec['crit2'] = bool(aok) and all(v['excess'] > 0 for v in aok)
        rec['crit3_n_positive'] = sum(1 for v in wok if v['excess'] > 0)
        rec['crit3'] = rec['crit3_n_positive'] >= 3
        rec['crit4'] = bool(aok) and all(v['n'] >= MIN_N for v in aok) and ln >= MIN_N
        rec['ALL_PASS'] = rec['crit2'] and rec['crit3'] and rec['crit4']
        # 中身: 半導体の割合／終価の集中／年次リバランス
        g0, _ = apply_rule(parts, amap0)
        tot = sum(M[t] for t in g0); top = sorted(((M[t]/tot, t) for t in g0), reverse=True)
        rb = C.rebal_excess(g0, pan, k0, END, spym)
        rec['semi_share'] = round(sum(1 for t in g0 if t in SEMI)/len(g0), 3)
        rec['top1'] = top[0][1]; rec['top1_share'] = round(top[0][0], 4)
        rec['top3_share'] = round(sum(x for x, _ in top[:3]), 4)
        rec['rebal_excess'] = round(rb, 4) if rb is not None else None
        rows.append(rec)
    res['frozen'] = rows
    res['survivors'] = [r['rule'] for r in rows if r['ALL_PASS']]

    with open(os.path.join(OUT, 'combo_spy_freeze.json'), 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    if '--json' in a: print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"■ F2（NOT込み3本AND）候補 {res['n_candidates']}本／家族95%点 {fam['p95']*100:+.1f}pt")
    print(f"   基準1を通った: {len(win)}本 → 凍結して基準2〜4へ\n")
    for r in rows:
        aa = ' '.join(f"{y}:{v['excess']*100:+.1f}({v['n']})" if 'excess' in v else f"{y}:—"
                      for y, v in r['anchors'].items())
        ww = ' '.join(f"{k}:{v['excess']*100:+.1f}" if 'excess' in v else f"{k}:—"
                      for k, v in r['windows'].items())
        print(f"  {r['rule'][:72]}")
        print(f"    探索 {r['search']['excess']*100:+.1f}pt(n={r['search']['n']}) "
              f"半導体{r['semi_share']*100:.0f}% 終価の最大1社 {r['top1']}{r['top1_share']*100:.0f}%"
              f" 年次リバ {('%+.1f' % (r['rebal_excess']*100)) if r['rebal_excess'] is not None else '—'}pt")
        print(f"    {aa}")
        print(f"    {ww}")
        print(f"    基準2:{'○' if r['crit2'] else '×'} 3:{'○' if r['crit3'] else '×'}"
              f"({r['crit3_n_positive']}/4) 4:{'○' if r['crit4'] else '×'}"
              f" → {'★全通過' if r['ALL_PASS'] else '落選'}\n")
    print(f"★全通過: {len(res['survivors'])}本")

if __name__ == '__main__':
    main()
