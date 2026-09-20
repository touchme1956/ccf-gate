#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/combo_spy_within.py — **層の中で帰無を作り直す**（2026-09-19新設）

★問い: 「半導体 ∧ X」が家族の帰無を超えたのは、X が良い半導体を選んだからか、
  それとも **半導体の群を小さくしただけ**か。
  母集団941社でシャッフルする帰無は「半導体が市場を大きく超えた」という既知の事実を
  そのまま超過へ算入してしまう＝**層の効果と、層の中の選別を分離できていない**。
  ⇒ **半導体の中だけでシャッフルする**帰無を作る（CLAUDE.md の
    「irr を固定すると E[r] の効果は消える」「半導体層の内側では刻みが何も分けていない」と同じ作法）。

★判定を持たない。事前登録は書き換えていない。門にも触らない（絶対のルール1）。
使い方: python3 night/combo_spy_within.py [--B 2000] [--json]
出力  : out/combo_spy_within.json
"""
import json, os, sys, random, datetime as dt
from itertools import combinations

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as C
from combo_spy_shapes import form_signed_atoms

OUT = os.path.join(BASE, 'out')
SEED = 20260919
SEARCH = '2013'

def within_family_null(cands, M, universe, spy_mult, months, B, seed):
    """★シャッフルを **universe（層）の中だけ**で行う。層の外の社は一切触らない。"""
    ts = [t for t in universe if t in M]
    vals = [M[t] for t in ts]; pos = {t: i for i, t in enumerate(ts)}
    idx = [[pos[t] for t in g if t in pos] for _, g in cands]
    base = C.cagr(spy_mult, months)
    rnd = random.Random(seed); mx = []
    for _ in range(B):
        rnd.shuffle(vals)
        best = -9.0
        for ii in idx:
            if not ii: continue
            e = C.cagr(sum(vals[i] for i in ii)/len(ii), months) - base
            if e > best: best = e
        mx.append(best)
    mx.sort()
    return dict(B=B, p95=round(mx[int(.95*B)], 4), p99=round(mx[int(.99*B)], 4),
                med=round(mx[len(mx)//2], 4), max=round(mx[-1], 4))

def within_indiv(group, M, universe, spy_mult, months, B, seed):
    """★「層から同じ大きさを無作為に引く」帰無。＝フィルタは無作為抽出より良いか。"""
    ts = [t for t in universe if t in M]
    vals = [M[t] for t in ts]
    k = len([t for t in group if t in M])
    base = C.cagr(spy_mult, months)
    obs = C.cagr(sum(M[t] for t in group if t in M)/k, months) - base
    rnd = random.Random(seed); ge = 0; draws = []
    for _ in range(B):
        s = rnd.sample(vals, k)
        e = C.cagr(sum(s)/k, months) - base
        draws.append(e)
        if e >= obs: ge += 1
    draws.sort()
    return dict(n=k, excess=round(obs, 4), p_within=round((ge+1)/(B+1), 4),
                null_med=round(draws[len(draws)//2], 4), null_p95=round(draws[int(.95*B)], 4), B=B)

def main():
    a = sys.argv[1:]
    B = int(a[a.index('--B')+1]) if '--B' in a else 2000
    pan = C.panel(); spy = {int(k): v for k, v in C.L('_spy_monthly.json').items()}
    END = max(spy); SEMI = C.semi_set()
    k0 = int(SEARCH)*12+6; months = END-k0
    pool = C.anchor_pool(pan, k0, END)
    M = C.mults(pan, pool, k0, END); spym = spy[END]/spy[k0]
    at = C.atoms(SEARCH, pool, C.load_anchor(SEARCH), SEMI)
    sg = form_signed_atoms(at)
    amap = {n: g for n, g, _ in sg}
    semi = {t for t in pool if t in SEMI}
    base = C.cagr(spym, months)

    res = {'generated': dt.date.today().isoformat(), 'tool': 'night/combo_spy_within.py',
           'stance': '★層の効果と、層の中の選別を分ける測定。判定ではない（絶対のルール1）',
           'B': B, 'universe': '半導体連鎖', 'universe_n': len(semi),
           'universe_excess': round(C.cagr(sum(M[t] for t in semi)/len(semi), months)-base, 4)}

    # ① 基準1を通った8本 ＋ 対照を、層の中の帰無で測り直す
    WIN = [
        'rnd_r↑1/4 ∧ ¬(accr↓1/4) ∧ 半導体連鎖', '¬(gm↓1/4) ∧ ¬(accr↓1/4) ∧ 半導体連鎖',
        '¬(cash_r↑1/4) ∧ rnd_r↑1/4 ∧ 半導体連鎖', '¬(cash_r↑1/4) ∧ ¬(sga_r↑1/4) ∧ 半導体連鎖',
        '¬(rev↓1/4) ∧ ¬(cash_r↑1/4) ∧ 半導体連鎖', '¬(cash_r↑1/4) ∧ ¬(gw_r↓1/4) ∧ 半導体連鎖',
        '¬(opm↓1/4) ∧ rnd_r↑1/4 ∧ 半導体連鎖', '¬(cash_r↑1/4) ∧ ¬(aturn↓1/4) ∧ 半導体連鎖']
    rows = []
    for nm in WIN:
        parts = [p.strip() for p in nm.split('∧')]
        g = None
        for p in parts:
            if p not in amap: g = None; break
            g = set(amap[p]) if g is None else g & amap[p]
        if not g: rows.append({'rule': nm, 'skip': '群が作れない'}); continue
        d = within_indiv(g, M, semi, spym, months, B, SEED)
        d['rule'] = nm
        tot = sum(M[t] for t in g); top = sorted(((M[t]/tot, t) for t in g), reverse=True)
        d['top1'] = top[0][1]; d['top1_share'] = round(top[0][0], 4)
        g2 = g - {'NVDA'}
        d['excess_wo_NVDA'] = round(C.cagr(sum(M[t] for t in g2)/len(g2), months)-base, 4) if g2 else None
        rows.append(d)
    res['winners_within_semi'] = rows

    # ② 家族: 「半導体 ∧ 署名付き原子 1〜2本」を全部作り、**層の中の帰無**で裁く
    semi_c = [('半導体連鎖', semi)]
    L = [(n, g) for n, g, _ in sg if n != '半導体連鎖' and n != '非半導体']
    for n, g in L:
        i = semi & g
        if len(i) >= C.MIN_N: semi_c.append((f'{n} ∧ 半導体連鎖', i))
    for (n1, g1), (n2, g2) in combinations(L, 2):
        i = semi & g1 & g2
        if len(i) >= C.MIN_N: semi_c.append((f'{n1} ∧ {n2} ∧ 半導体連鎖', i))
    seen, uq = set(), []
    for n, g in semi_c:
        k = frozenset(g)
        if k in seen: continue
        seen.add(k); uq.append((n, g))
    sc = sorted(((C.excess(g, M, spym, months), n, len(g)) for n, g in uq), reverse=True)
    fam_w = within_family_null(uq, M, semi, spym, months, min(B, 1000), SEED)
    fam_p = C.family_null(uq, M, pool, spym, months, min(B, 1000), SEED)
    res['semi_family'] = {
        'n_candidates': len(uq),
        'best_excess': round(sc[0][0], 4), 'best_rule': sc[0][1], 'best_n': sc[0][2],
        'family_p95_within_semi': fam_w['p95'], 'family_med_within_semi': fam_w['med'],
        'family_p95_whole_pool': fam_p['p95'],
        'n_beating_within': sum(1 for e, _, _ in sc if e > fam_w['p95']),
        'n_beating_pool': sum(1 for e, _, _ in sc if e > fam_p['p95']),
        'top8': [{'rule': n, 'n': ln, 'excess': round(e, 4)} for e, n, ln in sc[:8]]}

    # ③ 対照: 半導体を**含まない**規則で同じことができるか（層の外に信号はあるか）
    nonsemi = {t for t in pool if t not in SEMI}
    ns_c = [('非半導体', nonsemi)]
    for n, g in L:
        i = nonsemi & g
        if len(i) >= C.MIN_N: ns_c.append((f'{n} ∧ 非半導体', i))
    for (n1, g1), (n2, g2) in combinations(L, 2):
        i = nonsemi & g1 & g2
        if len(i) >= C.MIN_N: ns_c.append((f'{n1} ∧ {n2} ∧ 非半導体', i))
    seen, uq2 = set(), []
    for n, g in ns_c:
        k = frozenset(g)
        if k in seen: continue
        seen.add(k); uq2.append((n, g))
    sc2 = sorted(((C.excess(g, M, spym, months), n, len(g)) for n, g in uq2), reverse=True)
    fw2 = within_family_null(uq2, M, nonsemi, spym, months, min(B, 1000), SEED)
    res['nonsemi_family'] = {
        'n_candidates': len(uq2), 'universe_n': len(nonsemi),
        'universe_excess': round(C.cagr(sum(M[t] for t in nonsemi)/len(nonsemi), months)-base, 4),
        'best_excess': round(sc2[0][0], 4), 'best_rule': sc2[0][1], 'best_n': sc2[0][2],
        'family_p95_within': fw2['p95'], 'family_med_within': fw2['med'],
        'n_beating_within': sum(1 for e, _, _ in sc2 if e > fw2['p95']),
        'top8': [{'rule': n, 'n': ln, 'excess': round(e, 4)} for e, n, ln in sc2[:8]]}

    with open(os.path.join(OUT, 'combo_spy_within.json'), 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    if '--json' in a: print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"■ 層 = 半導体連鎖 {res['universe_n']}社／層そのものの超過 {res['universe_excess']*100:+.1f}pt")
    print(f"\n--- 基準1を通った8本を **半導体の中で無作為抽出** と比べる（B={B}）---")
    print(f"{'規則':<44}{'n':>4}{'超過':>9}{'層内帰無の中央':>15}{'p(層内)':>9}  NVDA抜き")
    for r in rows:
        if 'skip' in r: continue
        print(f"{r['rule'][:44]:<44}{r['n']:>4}{r['excess']*100:>+8.1f}{r['null_med']*100:>+14.1f}"
              f"{r['p_within']:>9.3f}  {r['excess_wo_NVDA']*100:+.1f}pt ({r['top1']}{r['top1_share']*100:.0f}%)")
    f = res['semi_family']
    print(f"\n--- 家族: 「半導体 ∧ …」{f['n_candidates']}本 ---")
    print(f"   最良 {f['best_excess']*100:+.1f}pt ({f['best_rule'][:50]}, n={f['best_n']})")
    print(f"   母集団941でシャッフルした帰無95%点 {f['family_p95_whole_pool']*100:+.1f}pt → 超えた {f['n_beating_pool']}本")
    print(f"   ★半導体の中でシャッフルした帰無95%点 {f['family_p95_within_semi']*100:+.1f}pt"
          f"（中央 {f['family_med_within_semi']*100:+.1f}）→ 超えた {f['n_beating_within']}本")
    g = res['nonsemi_family']
    print(f"\n--- 対照: 「非半導体 ∧ …」{g['n_candidates']}本（層そのもの {g['universe_excess']*100:+.1f}pt）---")
    print(f"   最良 {g['best_excess']*100:+.1f}pt ({g['best_rule'][:50]}, n={g['best_n']})")
    print(f"   ★層の中の帰無95%点 {g['family_p95_within']*100:+.1f}pt → 超えた {g['n_beating_within']}本")

if __name__ == '__main__':
    main()
