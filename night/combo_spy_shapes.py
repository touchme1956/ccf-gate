#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/combo_spy_shapes.py — **combo_spy が探していない「規則の形」を数え上げて、同じ物差しで試す**
（2026-09-19新設・ユーザーの問い「有力な指標を組み合わせてS&P500を超えるリターンをだすものがないか」の続き）

★この器は判定を持たない。門へ線を入れる話ではない（規約の改定は絶対のルール1の領分）。
★事前登録 out/combo_spy_prereg.json は**書き換えていない**。ここで測る形は登録の外なので、
  **合否ではなく「探索空間に穴があったか」の測定**として読むこと。

【combo_spy が探していた空間】
  単変量50本の **AND（連言）だけ**、等ウェイト買い持ち、群は「満たす社の集合」。
  ＝2,446本。best +17.2pt / 家族の帰無95%点 +18.8pt → 通過0本。

【この器が足す形（探していなかったもの）】
  F1 OR / NOT（選言と否定）          F2 NOT込みの3本AND
  F3 合成スコアの上位N社（連言より自然な形）   F4 業種中立（sic2ごとに上位を採る）
  F5 等ウェイトでない重み付け            F6 使っていない在庫の指標を足す
  F7 ★上の全部を一つの家族として裁く（＝私がこの器で探した空間の、本当の値札）

【反則を避ける一点】
  候補を増やせば帰無も上がる。**片方だけ増やすのは反則**なので、
  形ごとに **その形の候補空間そのもの** で帰無を作り直す（combo_spy.family_null をそのまま使う）。
  重み付き(F5)だけは equal-weight の family_null が表現できないので一般化した関数を書き、
  **重みを一様にすると combo_spy.family_null と一致すること**を毎回検算する（二つの実装を割らない）。

使い方: python3 night/combo_spy_shapes.py [--B 300] [--json]
出力  : out/combo_spy_shapes.json
"""
import json, os, sys, random, datetime as dt
from itertools import combinations

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as C                      # ← 土台は再実装しない（v9.9.65）

OUT = os.path.join(BASE, 'out')
SEED = 20260919
MIN_N = C.MIN_N                            # 事前登録の基準4を借りる（新しい定数を作らない）
SEARCH = '2013'

# ── (e) 使っていない在庫 ────────────────────────────────────────
# ⚠ 前方の量（結果側）は**絶対に入れない**。hist_val の mdd / tr_cagr / ret_* / years は
#   hist_val_join.py:54 の JOINED で tr_cagr と同じ束として結合される＝**前方**。predictor にしない。
FUND2 = ['agr1', 'noa_r', 'sbc_r', 'gwimp_r', 'gwimp_n', 'age_pp', 'lease_r',
         'divcut_n', 'restr_n', 'shr_cagr', 'shr_down', 'cetr', 'getr', 'etrgap', 'leasex']
HVAL  = ['pe', 'ps', 'pfcf', 'mcap', 'pe_pct', 'ps_pct', 'pfcf_pct', 'adj_pe_pct', 'pe_z', 'ps_z']
F2X   = ['streak_opm', 'accel']            # features2 にあるのに combo_spy が使っていない2欄
HVAL_BANNED = {'mdd', 'tr_cagr', 'tr_total', 'ret_start', 'ret_end', 'years', 'per_xs'}

def extra_feats(pool, min_cov=300):
    """新しい連続指標。⚠ 被覆が薄い欄は**入れない**（群が小さすぎて帰無が暴れる）。
    返すのは {key: {ticker: value}} と被覆の実測。"""
    P = set(pool); F = {}; cov = {}
    def take(fn, tk, keys, pre):
        try: rows = C.L(fn)
        except Exception as e:
            cov[pre] = f'読めない: {e}'; return
        rows = rows.get('rows', rows)
        if isinstance(rows, dict): rows = [dict(v, **{tk: k}) for k, v in rows.items()]
        for k in keys:
            assert k not in HVAL_BANNED, f'{k} は前方の量'
            m = {r[tk]: r[k] for r in rows
                 if r.get(tk) in P and isinstance(r.get(k), (int, float))}
            cov[f'{pre}:{k}'] = len(m)
            if len(m) >= min_cov: F[f'{pre}:{k}'] = m
    take(f'retro_features2_{SEARCH}.json', 'ticker', F2X, 'f2')
    take(f'retro_fund2_{SEARCH}.json', 'ticker', FUND2, 'fd')
    take(f'hist_val_{SEARCH}.json', 'ticker', HVAL, 'hv')
    return F, cov

def base_feats(pool, D):
    """combo_spy が既に使っている連続指標（合成スコア／重み付けの材料に要る）。"""
    P = set(pool); F = {}
    for k in C.FEAT_KEYS:
        m = {t: D['feat'][t][k] for t in P
             if t in D['feat'] and isinstance(D['feat'][t].get(k), (int, float))}
        if len(m) >= 300: F[k] = m
    return F

# ── 一般化した帰無（重み付きも扱える）───────────────────────────────
def family_null_w(cands, M, order_src, spy_mult, months, B, seed):
    """cands = [(name, {ticker: weight})]。重みが一様なら combo_spy.family_null と一致する。
    ⚠ 一致することを caller が毎回検算する（同じ問いに二つの実装を持たない）。"""
    ts = [t for t in order_src if t in M]
    vals = [M[t] for t in ts]; pos = {t: i for i, t in enumerate(ts)}
    packed = []
    for _, w in cands:
        ii, ww, s = [], [], 0.0
        for t, x in w.items():
            if t in pos and x > 0: ii.append(pos[t]); ww.append(x); s += x
        if ii: packed.append((ii, ww, s))
    base = C.cagr(spy_mult, months)
    rnd = random.Random(seed); mx = []
    for _ in range(B):
        rnd.shuffle(vals)
        best = -9.0
        for ii, ww, s in packed:
            acc = 0.0
            for i, x in zip(ii, ww): acc += vals[i] * x
            e = C.cagr(acc / s, months) - base
            if e > best: best = e
        mx.append(best)
    mx.sort()
    return dict(B=B, p95=round(mx[int(.95*B)], 4), p99=round(mx[int(.99*B)], 4),
                med=round(mx[len(mx)//2], 4), max=round(mx[-1], 4))

def wexcess(w, M, spy_mult, months):
    s = sum(w.values())
    if s <= 0: return None
    return C.cagr(sum(M[t]*x for t, x in w.items())/s, months) - C.cagr(spy_mult, months)

def dedupe(cands):
    """同じ会社集合（重み付きなら同じ重みベクトル）を作る別名は1本に潰す＝家族を水増ししない。"""
    seen, out = set(), []
    for n, w in cands:
        k = frozenset((t, round(x, 6)) for t, x in w.items())
        if k in seen: continue
        seen.add(k); out.append((n, w))
    return out

def as_w(g): return {t: 1.0 for t in g}

# ── 規則の形 ───────────────────────────────────────────────
def form_signed_atoms(at):
    """(a) NOT を足す。⚠ NOT は **have の中**で取る（測っていない社を『満たさない』にしない）。"""
    sg = []
    for n, g, h in at:
        sg.append((n, set(g), set(h)))
        ng = set(h) - set(g)
        if len(ng) >= 5: sg.append((f'¬({n})', ng, set(h)))
    return sg

def form_or_and2(sg):
    """(a) 署名付き原子の 1本 ／ 2本AND ／ 2本OR。"""
    out = [(n, as_w(g)) for n, g, _ in sg if len(g) >= MIN_N]
    for (a, ga, _), (b, gb, _) in combinations(sg, 2):
        i = ga & gb
        if len(i) >= MIN_N: out.append((f'{a} ∧ {b}', as_w(i)))
        u = ga | gb
        if len(u) >= MIN_N: out.append((f'{a} ∨ {b}', as_w(u)))
    return dedupe(out)

def form_and3(sg):
    """(a) 署名付き原子の 3本AND（NOT込み）＝combo_spy の AND3 の上位集合。"""
    out = [(n, as_w(g)) for n, g, _ in sg if len(g) >= MIN_N]
    L = [(n, g) for n, g, _ in sg]
    for (a, ga), (b, gb) in combinations(L, 2):
        i = ga & gb
        if len(i) >= MIN_N: out.append((f'{a} ∧ {b}', as_w(i)))
    for (a, ga), (b, gb), (c, gc) in combinations(L, 3):
        i = ga & gb & gc
        if len(i) >= MIN_N: out.append((f'{a} ∧ {b} ∧ {c}', as_w(i)))
    return dedupe(out)

def ranks(m, pool):
    """指標を順位へ（0=最悪 … 1=最良）。⚠ 欠測の社は返さない＝順位を与えない。"""
    have = [t for t in pool if t in m]
    s = sorted(have, key=lambda t: m[t])
    n = len(s)
    return {t: (i/(n-1) if n > 1 else .5) for i, t in enumerate(s)}

def form_topn(F, pool, ks=(2, 3), Ns=(20, 30, 50, 75, 100), maxk3=None):
    """(b) 合成スコア上位N社。**連言より自然な形**——連言は各軸で閾値を切るが、
    こちらは順位を足して上位を買う（片方が飛び抜けていれば他方の弱さを補える）。
    ⚠ 合成は **全指標がそろう社**だけで作る（欠測を平均で埋めない＝ルール7）。"""
    R = {k: ranks(m, pool) for k, m in F.items()}
    keys = sorted(F)
    out = []
    for k in ks:
        combos = list(combinations(keys, k))
        if k == 3 and maxk3: combos = combos[:maxk3]
        for cb in combos:
            have = set(R[cb[0]])
            for c in cb[1:]: have &= set(R[c])
            if len(have) < max(Ns) + 10: continue
            for signs in _signs(k):
                sc = {t: sum(sg*(R[c][t]-.5) for c, sg in zip(cb, signs)) for t in have}
                order = sorted(have, key=lambda t: -sc[t])
                nm = ' + '.join(('' if s > 0 else '−')+c for c, s in zip(cb, signs))
                for N in Ns:
                    if N <= len(order): out.append((f'上位{N}: {nm}', as_w(order[:N])))
    return dedupe(out)

def _signs(k):
    out = [[]]
    for _ in range(k): out = [o+[s] for o in out for s in (1, -1)]
    return [tuple(o) for o in out if o[0] > 0] + [tuple(o) for o in out if o[0] < 0]

def form_sector_neutral(F, pool, SIC, ks=(1, 2), per=(1, 2, 3), maxk2=None):
    """(c) 業種中立。sic2 ごとに合成スコアの上位 per 社を採って束ねる。
    ⚠ 業種が判らない社は入れない（『測っていない』を『業種なし』にしない）。"""
    R = {k: ranks(m, pool) for k, m in F.items()}
    keys = sorted(F); out = []
    for k in ks:
        combos = list(combinations(keys, k))
        if k == 2 and maxk2: combos = combos[:maxk2]
        for cb in combos:
            have = set(R[cb[0]])
            for c in cb[1:]: have &= set(R[c])
            have = {t for t in have if t in SIC}
            if len(have) < 100: continue
            for signs in _signs(k):
                sc = {t: sum(sg*(R[c][t]-.5) for c, sg in zip(cb, signs)) for t in have}
                bys = {}
                for t in have: bys.setdefault(SIC[t], []).append(t)
                for s in bys: bys[s].sort(key=lambda t: -sc[t])
                nm = ' + '.join(('' if s > 0 else '−')+c for c, s in zip(cb, signs))
                for p in per:
                    g = set()
                    for s, lst in bys.items(): g |= set(lst[:p])
                    if len(g) >= MIN_N: out.append((f'業種内上位{p}: {nm}', as_w(g)))
    return dedupe(out)

def form_weighted(F, pool, SIC):
    """(d) 等ウェイトでない重み。**重みは指標だけで決める**（前方リターンを見ない）。
      w1 順位そのもの／w2 順位の2乗（上位へ強く寄せる）／w3 上位N社の中で順位重み
    ⚠ この形は equal-weight の family_null では表現できないので family_null_w を使う。"""
    R = {k: ranks(m, pool) for k, m in F.items()}
    out = []
    for k, r in R.items():
        for sg, lab in ((1, ''), (-1, '−')):
            w = {t: (sg*(v-.5)+.5) for t, v in r.items()}
            out.append((f'重み∝順位 {lab}{k}', {t: max(x, 1e-9) for t, x in w.items()}))
            out.append((f'重み∝順位² {lab}{k}', {t: max(x, 1e-9)**2 for t, x in w.items()}))
            order = sorted(r, key=lambda t: -sg*r[t])
            for N in (30, 50, 100):
                if N > len(order): continue
                sub = order[:N]
                out.append((f'上位{N}を順位重み {lab}{k}',
                            {t: max(sg*(r[t]-.5)+.5, 1e-9) for t in sub}))
    return dedupe(out)

def main():
    a = sys.argv[1:]
    B = int(a[a.index('--B')+1]) if '--B' in a else 300
    pan = C.panel()
    spy = {int(k): v for k, v in C.L('_spy_monthly.json').items()}
    END = max(spy); SEMI = C.semi_set()
    k0 = int(SEARCH)*12 + 6; months = END - k0
    pool = C.anchor_pool(pan, k0, END)
    D = C.load_anchor(SEARCH)
    at = C.atoms(SEARCH, pool, D, SEMI)
    M = C.mults(pan, pool, k0, END); spym = spy[END]/spy[k0]
    SIC = {r['ticker']: r.get('sic2') for r in C.L('retro_sic.json')['rows']
           if r.get('ticker') in set(pool) and r.get('sic2')}

    res = {'generated': dt.date.today().isoformat(), 'tool': 'night/combo_spy_shapes.py',
           'stance': ('★探索空間の穴の測定。合否ではない。事前登録(out/combo_spy_prereg.json)は'
                      '書き換えていない——ここで測る形は登録の外。門へ線を入れる話でもない（絶対のルール1）'),
           'search_anchor': f'{SEARCH}-07', 'window_years': round(months/12, 2),
           'pool_n': len(pool), 'spy_cagr': round(C.cagr(spym, months), 4),
           'equal_weight_all': round(C.cagr(sum(M.values())/len(M), months), 4), 'B': B}

    # ── 検算1: 一般化した帰無が、一様重みで combo_spy.family_null と一致するか ──
    probe = [(n, g) for n, g in C.build_cands(at, 2)][:400]
    probe = [(n, g) for n, g in probe if len(g) >= MIN_N]
    f_old = C.family_null(probe, M, pool, spym, months, 60, 777)
    f_new = family_null_w([(n, as_w(g)) for n, g in probe], M, pool, spym, months, 60, 777)
    res['selftest_family_null_matches'] = (f_old == f_new)
    res['selftest_detail'] = {'old': f_old, 'new': f_new}
    if not res['selftest_family_null_matches']:
        print('✗ 検算に落ちた: family_null_w が combo_spy.family_null と一致しない'); 

    # ── 検算2: 帰無は pool 全体で混ぜる。群の母体(have)が偏っていないか ──
    ew_pool = C.cagr(sum(M.values())/len(M), months)
    hv = {}
    for n, g, h in at:
        if len(h) < len(pool):
            e = C.cagr(sum(M[t] for t in h)/len(h), months)
            hv.setdefault(n.split('>')[0].split('=')[0], (len(h), round((e-ew_pool)*100, 2)))
    res['have_vs_pool_bias_pt'] = {k: {'have_n': v[0], 'EWの差pt': v[1]} for k, v in sorted(hv.items())}

    # ── 新しい指標の在庫 ──
    EX, cov = extra_feats(pool)
    BF = base_feats(pool, D)
    res['extra_feature_coverage'] = cov
    res['extra_feats_used'] = sorted(EX)
    res['base_feats_used'] = sorted(BF)

    ALLF = dict(BF); ALLF.update(EX)

    # ── (e) 新しい指標を原子にする ──
    at_ex = list(at)
    for k, m in EX.items():
        have = {t for t in pool if t in m}
        vs = [m[t] for t in have]
        hi, lo = C.quart(vs, .75), C.quart(vs, .25)
        g1 = {t for t in have if m[t] >= hi}; g2 = {t for t in have if m[t] <= lo}
        if len(g1) >= 5: at_ex.append((f'{k}↑1/4', g1, have))
        if len(g2) >= 5: at_ex.append((f'{k}↓1/4', g2, have))

    forms = {}
    def run(tag, cands, note):
        cands = [(n, w) for n, w in cands if len(w) >= MIN_N]
        if not cands: forms[tag] = {'skip': '候補が作れない'}; return []
        sc = sorted(((wexcess(w, M, spym, months), n, len(w)) for n, w in cands), reverse=True)
        fam = family_null_w(cands, M, pool, spym, months, B, SEED)
        top = [{'rule': n, 'n': ln, 'excess': round(e, 4)} for e, n, ln in sc[:8]]
        forms[tag] = {'note': note, 'n_candidates': len(cands),
                      'best_excess': round(sc[0][0], 4), 'best_rule': sc[0][1], 'best_n': sc[0][2],
                      'family_p95': fam['p95'], 'family_med': fam['med'], 'family_max': fam['max'],
                      'beats_family': bool(sc[0][0] > fam['p95']),
                      'n_beating_family': sum(1 for e, _, _ in sc if e > fam['p95']),
                      'top8': top}
        return cands

    print('■ 形ごとに探索して、**その形の空間で**帰無を作り直す（片方だけ増やすのは反則）')
    allc = []
    # F0 対照: combo_spy と同じ形（再現）
    allc += run('F0_AND3_baseline', [(n, as_w(g)) for n, g in C.build_cands(at, 3)],
                'combo_spy と同じ形（対照・再現）')
    sg = form_signed_atoms(at)
    res['n_signed_atoms'] = len(sg)
    allc += run('F1_OR_NOT_2way', form_or_and2(sg), '(a) NOT込みの原子で 1本/2本AND/2本OR')
    allc += run('F2_AND3_signed', form_and3(sg), '(a) NOT込みの3本AND（F0の上位集合）')
    allc += run('F3_topN_composite', form_topn(BF, pool), '(b) 合成スコアの上位N社（既存の指標）')
    allc += run('F4_sector_neutral', form_sector_neutral(BF, pool, SIC), '(c) 業種中立（sic2ごとに上位）')
    allc += run('F5_weighted', form_weighted(BF, pool, SIC), '(d) 等ウェイトでない重み付け')
    allc += run('F6_AND3_plus_new', [(n, as_w(g)) for n, g in C.build_cands(at_ex, 3)],
                '(e) 使っていない在庫の指標を足して、combo_spy と同じ形')
    allc += run('F3b_topN_all_feats', form_topn(ALLF, pool, ks=(2,), maxk3=None),
                '(b)+(e) 合成スコア上位N社（新しい指標込み・2本）')

    # F7 ★全部を一つの家族として（私がこの器で探した空間の本当の値札）
    allc = dedupe(allc)
    sc = sorted(((wexcess(w, M, spym, months), n, len(w)) for n, w in allc), reverse=True)
    fam = family_null_w(allc, M, pool, spym, months, B, SEED)
    forms['F7_ALL_TOGETHER'] = {
        'note': '★この器で探した全形を一つの家族として裁く＝本当の値札。片方だけ増やすのは反則',
        'n_candidates': len(allc), 'best_excess': round(sc[0][0], 4), 'best_rule': sc[0][1],
        'best_n': sc[0][2], 'family_p95': fam['p95'], 'family_med': fam['med'],
        'family_max': fam['max'], 'beats_family': bool(sc[0][0] > fam['p95']),
        'n_beating_family': sum(1 for e, _, _ in sc if e > fam['p95']),
        'top15': [{'rule': n, 'n': ln, 'excess': round(e, 4)} for e, n, ln in sc[:15]]}
    res['forms'] = forms

    with open(os.path.join(OUT, 'combo_spy_shapes.json'), 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    if '--json' in a: print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"\n母集団 {res['pool_n']}社／{res['window_years']}年／SPY {res['spy_cagr']*100:+.1f}%"
          f"／等ウェイト全社 {(res['equal_weight_all']-res['spy_cagr'])*100:+.1f}pt")
    print(f"検算1 family_null_w == combo_spy.family_null : {res['selftest_family_null_matches']}")
    print(f"\n{'形':<22}{'候補':>7}{'最良':>9}{'家族95%':>9}{'家族中央':>9}  超えた本数")
    for k, v in forms.items():
        if 'skip' in v: print(f"{k:<22} —（{v['skip']}）"); continue
        print(f"{k:<22}{v['n_candidates']:>7}{v['best_excess']*100:>+8.1f}pt"
              f"{v['family_p95']*100:>+8.1f}{v['family_med']*100:>+8.1f}   {v['n_beating_family']}"
              f"{'  ★' if v['beats_family'] else ''}")
        print(f"      最良: {v['best_rule'][:78]}  (n={v['best_n']})")

if __name__ == '__main__':
    main()
