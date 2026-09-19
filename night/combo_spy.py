#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/combo_spy.py — **指標の組合せで、等ウェイト買い持ちが S&P500 を超えるか**
（2026-09-19新設・ユーザーの問い「有力な指標を組み合わせてS&P500を超えるリターンをだすものがないか」）

★この器は判定を持たない。門へ線を入れる話ではない（規約の改定は絶対のルール1の領分）。
  事前登録は out/combo_spy_prereg.json（**測定を1件も見る前にコミット済み**）。

【物差しが今までと違う】
  これまでの検定は lift（P(15%+)の差）で測ってきた。だが問いは「SPYを超えるか」なので
  **超過CAGR = 等ウェイト買い持ちCAGR − SPY CAGR（同じ月）** で測る。
  ⚠ 中央値で測ってはいけない——中央値は『1社を選んだとき』の値で、SPYは portfolio。
    実測: 同じ母集団で 中央値7.9% / 等ウェイト14.1%（SPY 14.2%）。

【較正（登録の前に測った）】
  等ウェイト全社の超過は 2013 −0.0pt / 2016 −0.9 / 2017 −2.1 / 2018 −2.7 / 2019 −1.5 / 2020 +1.8
  ＝**「SPY超え」は自明ではない**。母集団を全部買うと負ける窓のほうが多い。

【家族の値札】
  候補を何千本も並べるので、1本の超過だけ見てはいけない。
  **会社→前方の倍率の対応を1回シャッフルし、探索全体をやり直して最大超過を取る**帰無を作る
  （候補どうしの重なりを壊さない）。その95%点が線。

使い方: python3 night/combo_spy.py [--B 1000] [--max-and 3] [--json]
出力  : out/combo_spy.json
"""
import json, os, sys, random, datetime as dt
from itertools import combinations

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
L = lambda p: json.load(open(os.path.join(OUT, p)))
SEED = 20260919
MIN_N = 20              # 事前登録の基準4（結果を見てから緩めない）

def ymk(ts):
    d = dt.datetime.utcfromtimestamp(ts)
    return d.year * 12 + (d.month - 1)

def panel():
    p = {}
    for f in ("retro_monthly_2013_2018.json", "retro_monthly_2018_2026.json"):
        for t, s in L(f).items():
            m = p.setdefault(t, {})
            for ts, px in s:
                if px and px > 0:
                    k = ymk(ts)
                    if k not in m: m[k] = px      # 同一年月は最初のバー
    return p

def cagr(mult, months): return mult ** (12.0 / months) - 1 if months > 0 and mult > 0 else None

# ── 指標の在庫（アンカーごと。⚠ 無い欄は「無い」——0 と読まない） ──────────────
READ = {  # 読解: irr と moat5
    '2013': [('retro_moat_2013.json', 'irr', 'ticker'), ('retro_moat_2013q.json', 'irr', 'ticker')],
    '2015': [('retro_moat_2015.json', 'irr', 'ticker'), ('retro_moat_2015q.json', 'irr', 'ticker'),
             ('retro_moat_2015qb.json', 'irr', 'ticker')],
    '2018': [('retro_moat_2018.json', 'irr18', 't'), ('retro_moat_2018_rest.json', 'irr18', 't')],
}
PILL_F = {'2013': 'retro_moat_pillars_2013.json', '2015': 'retro_moat_pillars_2015.json'}
FEAT_F = {y: f'retro_features2_{y}.json' for y in ('2013', '2016', '2017', '2018')}
FEAT_KEYS = ['rev', 'gm', 'opm', 'cagr5', 'cash_r', 'gw_r', 'aturn', 'capex_r', 'rnd_r', 'accr',
             'intcov', 'conv5', 'netiss_r', 'payout5', 'sga_r', 'fcfpos5', 'opmD5', 'streak_rev']

def load_anchor(y):
    """そのアンカーで**実際に読める**指標だけを返す。⚠ 読めない欄は入れない（穴は穴のまま）。"""
    d = {'irr': {}, 'moat5': {}, 'pill': {}, 'feat': {}}
    for fn, kk, tk in READ.get(y, []):
        for r in L(fn)['rows']:
            if r.get(kk) is not None: d['irr'][r[tk]] = r[kk]
            if r.get('moat5') is not None: d['moat5'][r[tk]] = r['moat5']
    if y in PILL_F:
        for r in L(PILL_F[y])['rows']:
            d['pill'][r['ticker']] = {k: r.get(k) for k in ('rep', 'dur', 'dom', 'moatW')}
    if y in FEAT_F:
        try:
            for r in L(FEAT_F[y])['rows']: d['feat'][r['ticker']] = r
        except Exception: pass
    return d

def semi_set():
    s = set()
    for r in L('retro_sic.json')['rows']:
        dl = (r.get('sicDesc') or '').lower()
        if 'semiconductor' in dl or 'electronic component' in dl: s.add(r['ticker'])
        elif (r.get('sic') or '') in {'3559','3674','3672','3675','3676','3677','3678','3679','3827'}: s.add(r['ticker'])
    return s

def quart(vals, p):
    s = sorted(vals); i = max(0, min(len(s)-1, int(round(p*(len(s)-1)))))
    return s[i]

def atoms(y, pool, D, SEMI):
    """そのアンカーで作れる**単変量の条件**。(名前, 会社集合) で返す。
    ⚠ 欄が無い社は群にも補集合にも入れない＝『測っていない』を『満たさない』にしない。"""
    out = []
    P = set(pool)
    if D['irr']:
        have = {t for t in P if t in D['irr']}
        for ln in (85, 70, 50):
            out.append((f'irr>={ln}', {t for t in have if D['irr'][t] >= ln}, have))
        out.append(('irr=85', {t for t in have if D['irr'][t] == 85}, have))
    if D['moat5']:
        have = {t for t in P if t in D['moat5']}
        out.append(('moat5>=4', {t for t in have if D['moat5'][t] >= 4}, have))
    for k, lines in (('rep', (80, 60)), ('dur', (100, 85, 75)), ('dom', (70,)), ('moatW', (85, 70))):
        have = {t for t in P if t in D['pill'] and D['pill'][t].get(k) is not None}
        if len(have) < 50: continue
        for ln in lines:
            out.append((f'{k}>={ln}', {t for t in have if D['pill'][t][k] >= ln}, have))
    for k in FEAT_KEYS:
        have = {t for t in P if t in D['feat'] and D['feat'][t].get(k) is not None}
        if len(have) < 50: continue
        vs = [D['feat'][t][k] for t in have]
        hi, lo = quart(vs, .75), quart(vs, .25)
        out.append((f'{k}↑1/4', {t for t in have if D['feat'][t][k] >= hi}, have))
        out.append((f'{k}↓1/4', {t for t in have if D['feat'][t][k] <= lo}, have))
    out.append(('半導体連鎖', {t for t in P if t in SEMI}, P))
    out.append(('非半導体', {t for t in P if t not in SEMI}, P))
    return [(n, g, h) for n, g, h in out if len(g) >= 5]

def build_cands(at, max_and):
    """単変量 ＋ 2本・3本の連言。⚠ 向きは上下とも入れる（結果を見てから向きを選ばない）。"""
    cands = [(n, g) for n, g, h in at]
    if max_and >= 2:
        for (a, ga, _), (b, gb, _) in combinations(at, 2):
            g = ga & gb
            if len(g) >= MIN_N: cands.append((f'{a} ∧ {b}', g))
    if max_and >= 3:
        for (a, ga, _), (b, gb, _), (c, gc, _) in combinations(at, 3):
            g = ga & gb & gc
            if len(g) >= MIN_N: cands.append((f'{a} ∧ {b} ∧ {c}', g))
    seen, uniq = set(), []
    for n, g in cands:
        k = frozenset(g)
        if k in seen: continue      # 同じ会社集合を作る別名は1本に潰す（家族を水増ししない）
        seen.add(k); uniq.append((n, g))
    return uniq

# ── 超過の計算 ────────────────────────────────────────────
def mults(pan, pool, k0, k1):
    return {t: pan[t][k1]/pan[t][k0] for t in pool}

def excess(group, M, spy_mult, months):
    if len(group) < 1: return None
    s = 0.0
    for t in group: s += M[t]
    return cagr(s/len(group), months) - cagr(spy_mult, months)

def anchor_pool(pan, k0, k1):
    return [t for t in pan if k0 in pan[t] and k1 in pan[t]]

def family_null(cands, M, order_src, spy_mult, months, B, seed):
    """★探索**全体**を帰無で回す。1回のシャッフルを全候補へ当てて最大超過を取る。
    ⚠ 候補ごとに独立に引くと、候補どうしの重なりが壊れて帰無が甘くなる。"""
    ts = list(order_src)
    vals = [M[t] for t in ts]
    pos = {t: i for i, t in enumerate(ts)}
    idx = [[pos[t] for t in g if t in pos] for _, g in cands]
    base = cagr(spy_mult, months)
    rnd = random.Random(seed); mx = []
    n = len(vals)
    for _ in range(B):
        rnd.shuffle(vals)
        best = -9.0
        for ii in idx:
            if not ii: continue
            s = 0.0
            for i in ii: s += vals[i]
            e = cagr(s/len(ii), months) - base
            if e > best: best = e
        mx.append(best)
    mx.sort()
    return dict(B=B, p95=round(mx[int(.95*B)], 4), p99=round(mx[int(.99*B)], 4),
                med=round(mx[len(mx)//2], 4), max=round(mx[-1], 4))

def indiv_null(group, M, order_src, spy_mult, months, B, seed):
    """★**1本だけ**の帰無。探索の値札（family_null）と混同しないこと。
    family は『2446本から最大を選ぶ』費用を含む＝効果があっても検出できない。
    こちらは『この群だけを、事前に名指しして』当てた場合の p。
    ⚠ これは事前登録の基準ではない（結果を見た後に足した診断）。
      合否はあくまで基準1〜4で、それは既に0本で確定している。"""
    ts = [t for t in order_src if t in M]
    vals = [M[t] for t in ts]; pos = {t: i for i, t in enumerate(ts)}
    idx = [pos[t] for t in group if t in pos]
    if not idx: return None
    base = cagr(spy_mult, months)
    obs = cagr(sum(vals[i] for i in idx)/len(idx), months) - base
    rnd = random.Random(seed); ge = 0
    for _ in range(B):
        rnd.shuffle(vals)
        e = cagr(sum(vals[i] for i in idx)/len(idx), months) - base
        if e >= obs: ge += 1
    return dict(n=len(idx), excess=round(obs, 4), p=round((ge+1)/(B+1), 4), B=B)

def evaluate(rule_atoms, y, pan, spy, k1, SEMI):
    """規則を**そのアンカーのデータで作り直して**当てる（銘柄リストではなく規則を凍結する）。"""
    k0 = int(y)*12 + 6
    if k0 not in pan.get(next(iter(pan)), {}) and k0 not in spy: return None
    if k0 not in spy or k1 not in spy: return None
    pool = anchor_pool(pan, k0, k1)
    if len(pool) < 50: return None
    D = load_anchor(y)
    at = {n: (g, h) for n, g, h in atoms(y, pool, D, SEMI)}
    grp = None
    for a in rule_atoms:
        if a not in at: return {'skip': f'この窓に「{a}」が無い'}
        g = at[a][0]
        grp = g if grp is None else (grp & g)
    M = mults(pan, pool, k0, k1); months = k1 - k0
    e = excess(grp, M, spy[k1]/spy[k0], months)
    return dict(n=len(grp), excess=round(e, 4), years=round(months/12, 2),
                port=round(cagr(sum(M[t] for t in grp)/len(grp), months), 4),
                spy=round(cagr(spy[k1]/spy[k0], months), 4))

def main():
    a = sys.argv[1:]
    B = int(a[a.index('--B')+1]) if '--B' in a else 1000
    MAXAND = int(a[a.index('--max-and')+1]) if '--max-and' in a else 3
    pan = panel()
    spy = {int(k): v for k, v in L('_spy_monthly.json').items()}
    END = max(spy); SEMI = semi_set()
    SEARCH = '2013'
    k0 = int(SEARCH)*12 + 6; months = END - k0
    pool = anchor_pool(pan, k0, END)
    D = load_anchor(SEARCH)
    at = atoms(SEARCH, pool, D, SEMI)
    cands = build_cands(at, MAXAND)
    M = mults(pan, pool, k0, END); spym = spy[END]/spy[k0]
    scored = []
    for n, g in cands:
        if len(g) < MIN_N: continue
        scored.append(dict(rule=n, n=len(g), excess=round(excess(g, M, spym, months), 4)))
    scored.sort(key=lambda r: -r['excess'])
    # 家族の帰無は **n>=MIN_N を通った候補全部** で回す（探索した空間そのもの）
    fam_c = [(n, g) for n, g in cands if len(g) >= MIN_N]
    fam = family_null(fam_c, M, pool, spym, months, B, SEED)

    out = {
        'generated': dt.date.today().isoformat(),
        'tool': 'night/combo_spy.py',
        'prereg': 'out/combo_spy_prereg.json（測定を1件も見る前にコミット済み）',
        'stance': '測定器。門へ線を入れる話ではない（絶対のルール1）',
        'outcome': '超過CAGR = 等ウェイト買い持ち − SPY（同じ月・配当込み）',
        'search_anchor': f'{SEARCH}-07', 'window_years': round(months/12, 2),
        'pool_n': len(pool), 'min_n': MIN_N, 'max_and': MAXAND,
        'n_atoms': len(at), 'n_candidates_searched': len(fam_c),
        'spy_cagr': round(cagr(spym, months), 4),
        'equal_weight_all': round(cagr(sum(M.values())/len(M), months), 4),
        'family_null': fam,
        'top30': scored[:30],
        'bottom10': scored[-10:],
    }
    # 基準1を通った候補だけ、凍結して他アンカー＋非重複窓へ
    win = [r for r in scored if r['excess'] > fam['p95']]
    out['passed_criterion1'] = len(win)
    frozen = []
    for r in win[:40]:
        parts = [p.strip() for p in r['rule'].split('∧')]
        rec = {'rule': r['rule'], 'search': {'n': r['n'], 'excess': r['excess']}, 'anchors': {}, 'windows': {}}
        for y in ('2015', '2016', '2017', '2018'):
            rec['anchors'][y] = evaluate(parts, y, pan, spy, END, SEMI)
        # 重ならない4窓（2013-07起点・各39ヶ月）
        for i in range(4):
            a0 = k0 + 39*i; a1 = a0 + 39
            if a1 not in spy: continue
            p2 = anchor_pool(pan, a0, a1)
            D2 = load_anchor(SEARCH)   # 規則の定義は探索アンカーの在庫で作る（窓は切るが指標は同じ時点）
            at2 = {n: g for n, g, h in atoms(SEARCH, p2, D2, SEMI)}
            g = None; ok = True
            for pp in parts:
                if pp not in at2: ok = False; break
                g = at2[pp] if g is None else (g & at2[pp])
            if not ok or g is None or len(g) < 5:
                rec['windows'][f'W{i+1}'] = {'skip': '窓で群が作れない'}; continue
            M2 = mults(pan, p2, a0, a1)
            rec['windows'][f'W{i+1}'] = dict(n=len(g), excess=round(excess(g, M2, spy[a1]/spy[a0], 39), 4))
        aok = [v for v in rec['anchors'].values() if v and 'excess' in v]
        rec['crit2_all_anchors_positive'] = bool(aok) and all(v['excess'] > 0 for v in aok)
        rec['crit4_all_n_ge_min'] = bool(aok) and all(v['n'] >= MIN_N for v in aok) and r['n'] >= MIN_N
        wok = [v for v in rec['windows'].values() if 'excess' in v]
        rec['crit3_windows_positive'] = sum(1 for v in wok if v['excess'] > 0)
        rec['crit3_pass'] = rec['crit3_windows_positive'] >= 3
        rec['ALL_PASS'] = rec['crit2_all_anchors_positive'] and rec['crit3_pass'] and rec['crit4_all_n_ge_min']
        frozen.append(rec)
    out['frozen'] = frozen
    out['survivors'] = [r['rule'] for r in frozen if r['ALL_PASS']]

    # ★診断（事前登録の基準ではない）——「探索が見つけられない」と「効果が無い」を分ける
    # 合否は基準1〜4で既に 0本 で確定している。ここは *なぜ* 0本なのかを分けるためだけの測定。
    if '--fixed' in a:
        diag = {'note': ('★事前登録の基準ではない（結果を見た後に足した診断）。合否は基準1〜4で 0本 のまま。'
                         '探索の値札 %+.1fpt は「2446本から最大を選ぶ」費用込みなので、効果があっても検出できない。'
                         'ここは **事前に1本だけ名指しして** 当てた場合の p を出す。' % (fam['p95']*100)),
                'anchors': {}}
        for y in ('2013', '2015', '2018'):
            a0 = int(y)*12 + 6
            if a0 not in spy: continue
            mo = END - a0; pl = anchor_pool(pan, a0, END)
            if len(pl) < 50: continue
            Dy = load_anchor(y); My = mults(pan, pl, a0, END); sm = spy[END]/spy[a0]
            irr = Dy['irr']
            rec = {'years': round(mo/12, 2), 'pool_n': len(pl),
                   'spy_cagr': round(cagr(sm, mo), 4), 'rows': {}}
            def put(lab, g):
                g = set(g) & set(pl)
                if len(g) < 3: rec['rows'][lab] = {'skip': f'n={len(g)} 少なすぎる'}; return
                d = indiv_null(g, My, pl, sm, mo, B, int(y))
                d['semi'] = sum(1 for t in g if t in SEMI); rec['rows'][lab] = d
            for r in sorted({v for v in irr.values() if v}):
                put(f'irr=={r}', [t for t in irr if irr[t] == r])
            put('irr>=85', [t for t in irr if (irr[t] or 0) >= 85])
            put('半導体連鎖', [t for t in pl if t in SEMI])
            put('irr==85 ∧ 非半導体', [t for t in irr if irr[t] == 85 and t not in SEMI])
            put('irr>=85 ∧ 非半導体', [t for t in irr if (irr[t] or 0) >= 85 and t not in SEMI])
            put('irr in(70,75) ∧ 非半導体', [t for t in irr if irr[t] in (70, 75) and t not in SEMI])
            put('irr==50 ∧ 非半導体', [t for t in irr if irr[t] == 50 and t not in SEMI])
            diag['anchors'][y] = rec
        # 探索の最良も個別の帰無で測り直す（家族の値札との差を見せる）
        atmap = {n: g for n, g, h in at}
        best = scored[0]; gb = None
        for pp in [x.strip() for x in best['rule'].split('∧')]:
            gb = atmap[pp] if gb is None else (gb & atmap[pp])
        diag['search_best_individual'] = {'rule': best['rule'],
                                          **(indiv_null(gb, M, pool, spym, months, B, SEED) or {})}
        out['indiv_diag'] = diag

    with open(os.path.join(OUT, 'combo_spy.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    if '--json' in a: print(json.dumps(out, ensure_ascii=False, indent=1)); return
    print(f"■ 探索 {out['search_anchor']}／{out['window_years']}年／母集団 {out['pool_n']}社")
    print(f"   SPY {out['spy_cagr']:+.1%}   等ウェイト全社 {out['equal_weight_all']:+.1%}"
          f"（超過 {(out['equal_weight_all']-out['spy_cagr'])*100:+.1f}pt）")
    print(f"   単変量 {out['n_atoms']}本 → 候補 {out['n_candidates_searched']}本（n>={MIN_N}）")
    print(f"   ★家族の帰無95%点 {fam['p95']*100:+.1f}pt（中央 {fam['med']*100:+.1f} / 最大 {fam['max']*100:+.1f}・B={fam['B']}）")
    print(f"\n--- 探索アンカーの上位（超過の大きい順）---")
    for r in scored[:15]:
        mark = '★家族超え' if r['excess'] > fam['p95'] else ''
        print(f"   {r['excess']*100:+6.1f}pt  n={r['n']:<4} {r['rule'][:70]} {mark}")
    print(f"\n   基準1を通った候補: {out['passed_criterion1']}本（上位40本を凍結して当て直した）")
    print(f"\n--- 凍結して他アンカー／非重複窓 ---")
    for rec in frozen[:15]:
        aa = ' '.join(f"{y}:{(v['excess']*100):+.1f}({v['n']})" if v and 'excess' in v else f"{y}:—"
                      for y, v in rec['anchors'].items())
        ww = ' '.join(f"{k}:{(v['excess']*100):+.1f}" if 'excess' in v else f"{k}:—"
                      for k, v in rec['windows'].items())
        print(f"   {rec['rule'][:58]}")
        print(f"      探索 {rec['search']['excess']*100:+.1f}pt(n={rec['search']['n']}) | {aa} | {ww}"
              f" | 基準2:{'○' if rec['crit2_all_anchors_positive'] else '×'}"
              f" 3:{'○' if rec['crit3_pass'] else '×'}({rec['crit3_windows_positive']}/4)"
              f" 4:{'○' if rec['crit4_all_n_ge_min'] else '×'} → {'★全通過' if rec['ALL_PASS'] else '落選'}")
    if 'indiv_diag' in out:
        dg = out['indiv_diag']
        print(f"\n--- ★診断: 個別の帰無（事前登録の基準ではない）---")
        print(f"    探索の値札 {fam['p95']*100:+.1f}pt は「2446本から最大を選ぶ」費用込み。")
        print(f"    ここは **事前に1本だけ名指しして** 当てた場合。⚠ アンカーは社が重なるので独立ではない。")
        for y, rec in dg['anchors'].items():
            print(f"\n  ■ {y}-07 ／ {rec['years']}年 ／ 母集団{rec['pool_n']}社 ／ SPY {rec['spy_cagr']*100:+.1f}%/年")
            for lab, v in rec['rows'].items():
                if 'skip' in v: print(f"       {lab:<26} —（{v['skip']}）"); continue
                star = '★' if v['p'] < 0.05 else '  '
                print(f"    {star} {lab:<26} {v['excess']*100:+6.1f}pt n={v['n']:<4} 半導体{v['semi']:<3} p={v['p']:.4f}")
        sb = dg.get('search_best_individual', {})
        if 'p' in sb:
            print(f"\n    [探索の最良] {sb['rule']}")
            print(f"       {sb['excess']*100:+.1f}pt n={sb['n']} 個別p={sb['p']:.4f}"
                  f" → だが家族の値札 {fam['p95']*100:+.1f}pt を通らない＝**探索の費用で消える**")
    print(f"\n■ 全基準を通った規則: {len(out['survivors'])}本  {out['survivors'] if out['survivors'] else ''}")
    print(f"→ out/combo_spy.json")

if __name__ == '__main__':
    main()
