#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H3（利益率の水準との交互作用）の**反証**。

役割: 測定側 night/opmtrend_h3.py の結論を壊しにいく。迷ったら refuted に倒す。
- **測定側のコードを一行も import しない**。out/opmtrend_base.json の rows[] から自分で組み直す。
- 値・規約・採点式・刻み・重み・関門・売却規律・配分は1バイトも触らない。
- 書くのは out/opmtrend_ref_h3.json だけ。

事前登録（out/opm_trend_prereg.json の H3_level_interaction）:
  split = opm の中央値で二分。line = lift >= 0.15 かつ 8ビンテージすべてで符号が同じ。
  lift = P(hit|opmD5>=0) - P(hit|opmD5<0)。**線は後から動かさない。**

★この器が自分で踏んだ欠陥は my_own_defects に残す（0件は測定ではない、を自分に当てる）。
"""
import json, math, os, random, statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT  = os.path.join(ROOT, 'out')

HURDLE, IMPAIR, LINE = 0.15, -0.15, 0.15
QUAL_OPM_PCT, QUAL_FCFPOS = 10.0, 5
MIN_ARM = 20
SEED = 20260819          # ★測定側(20260818)と別の種

def j(p):
    with open(p, encoding='utf-8') as f: return json.load(f)
def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None
def frac(xs): return (sum(xs)/len(xs)) if xs else None
def r4(x): return None if x is None else round(x, 4)

base = j(os.path.join(OUT, 'opmtrend_base.json'))
ROWS = base['rows']
h3   = j(os.path.join(OUT, 'opmtrend_h3.json'))
VINT = sorted({r['vintage'] for r in ROWS})
warnings, defects = [], []

def pools_of(r):
    o = ['all']
    if r.get('qual'): o.append('qual')
    return o
def hit(r): return 1 if r['tr_cagr'] >= HURDLE else 0

# ================================================== (e) 単位・欄名
opm_raw = [r['opm_raw'] for r in ROWS if r.get('opm_raw') is not None]
d5      = [r['opmD5']   for r in ROWS if r.get('opmD5')   is not None]
mism = []
for r in ROWS:
    raw, pct = r.get('opm_raw'), r.get('opm')
    if raw is None or pct is None: continue
    mine = raw*100.0 if abs(raw) <= 3 else raw
    if abs(mine - pct) > 1e-6:
        mism.append({'vintage': r['vintage'], 'ticker': r['ticker'], 'opm_raw': raw,
                     'base_pct': pct, 'my_row_band_pct': round(mine,4)})
unit_check = {
    'opm_raw_median_abs': r4(med([abs(x) for x in opm_raw])),
    'opm_pct_median': r4(med([r['opm'] for r in ROWS if r.get('opm') is not None])),
    'opmD5_median_abs': r4(med([abs(x) for x in d5])),
    'opmD5_neg_share': r4(frac([1 if x < 0 else 0 for x in d5])),
    'qual_definition_recheck': None,
    'row_band_vs_file_band_mismatch_n': len(mism),
    'row_band_vs_file_band_sample': mism[:6],
    'note': ('base はファイル単位で倍率を決めて全行へ当てる。行単位の帯検問と食い違うのは |raw|>3 の'
             '深い赤字社（-425% 等）だけで、**ファイル単位のほうが正しい**——同じファイルの他の行が'
             '比率なら、その行も比率。行単位で当てると赤字社だけ100倍小さくなる。'
             'opmD5 は生の比率pt のまま（事前登録の閾値が比率）。'),
}
bad = 0
for r in ROWS:
    o, f5 = r.get('opm'), r.get('fcfpos5')
    want = None if (o is None or f5 is None) else (o >= QUAL_OPM_PCT and f5 >= QUAL_FCFPOS)
    if want is not None and want != r.get('qual'): bad += 1
unit_check['qual_definition_recheck'] = {'mismatch_vs_prereg': bad, 'ok': bad == 0}
if bad: warnings.append('qual の定義が事前登録と食い違う')

# ================================================== (f) look-ahead
la = {}
for y in VINT:
    f = j(os.path.join(OUT, f'retro_features2_{y}.json'))
    dl = f['deadline']
    after = [rr['ticker'] for rr in f['rows'] if rr.get('fy_end') and rr['fy_end'] > dl]
    ret = None
    for c in (f'retro_returns_{y}_all.json', f'retro_returns_{y}_q.json', f'retro_returns_{y}.json'):
        p = os.path.join(OUT, c)
        if os.path.exists(p): ret = j(p); break
    starts = sorted({rr.get('start') for rr in ret['rows'] if rr.get('start')})
    late = [rr['ticker'] for rr in ret['rows'] if rr.get('start') and rr['start'] > dl]
    la[str(y)] = {'features_deadline': dl, 'fy_end_after_deadline_n': len(after),
                  'sample': after[:5], 'returns_start_min': starts[0] if starts else None,
                  'returns_start_ge_deadline': all(s >= dl for s in starts),
                  'rows_starting_late_n': len(late), 'rows_starting_late_sample': late[:6],
                  'ok': len(after) == 0 and all(s >= dl for s in starts)}
if not all(v['ok'] for v in la.values()): warnings.append('look-ahead の検問に失敗')

# ================================================== 設計
def cells(pool, key='opm', tie='low'):
    """ビンテージ×プールで key の中央値二分。tie='low' は中央値ちょうどを低側（測定側と同じ）。
    ★事前登録は境界を決めていないので両方測る。"""
    res = {}
    for v in VINT:
        us = [r for r in ROWS if r['vintage'] == v and pool in pools_of(r)
              and r.get('opmD5') is not None and r.get('tr_cagr') is not None and r.get(key) is not None]
        if not us: res[v] = None; continue
        m = st.median([r[key] for r in us])
        if tie == 'low':
            hi = [r for r in us if r[key] >  m]; lo = [r for r in us if r[key] <= m]
        else:
            hi = [r for r in us if r[key] >= m]; lo = [r for r in us if r[key] <  m]
        res[v] = {'median': m, 'high': hi, 'low': lo, 'usable_n': len(us)}
    return res

def lift_of(rs):
    a = [r for r in rs if r['opmD5'] >= 0]; b = [r for r in rs if r['opmD5'] < 0]
    if len(a) < MIN_ARM or len(b) < MIN_ARM: return None, len(a), len(b)
    return frac([hit(r) for r in a]) - frac([hit(r) for r in b]), len(a), len(b)

def cw_lift_of(rs):
    def arm(g):
        d = defaultdict(list)
        for r in g: d[r['ticker']].append(hit(r))
        return frac([frac(v) for v in d.values()]), len(d)
    a, na = arm([r for r in rs if r['opmD5'] >= 0]); b, nb = arm([r for r in rs if r['opmD5'] < 0])
    return (None if (a is None or b is None) else a-b), na, nb

# ================================================== 1) 独立再計算
def summarise(pool, tie):
    C = cells(pool, 'opm', tie); out = {}
    for side in ('high','low'):
        per, arms, pooled = {}, {}, []
        for v in VINT:
            c = C[v]
            if c is None: per[str(v)] = None; continue
            L, na, nb = lift_of(c[side]); per[str(v)] = r4(L); arms[str(v)] = [na, nb]; pooled += c[side]
        pl, _, _ = lift_of(pooled); cw, _, _ = cw_lift_of(pooled)
        vals = [x for x in per.values() if x is not None]
        out[f'{pool}/{side}'] = {
            'lifts_by_vintage': per, 'arms_by_vintage': arms, 'usable_cells': len(vals),
            'n_lift_ge_line': sum(1 for x in vals if x >= LINE),
            'sign_pos': sum(1 for x in vals if x > 0), 'sign_neg': sum(1 for x in vals if x < 0),
            'all_same_sign': (len(set(x > 0 for x in vals)) == 1) if vals else False,
            'pooled_lift': r4(pl), 'pooled_n': len(pooled),
            'pooled_n_companies': len({r['ticker'] for r in pooled}), 'cw_pooled_lift': r4(cw),
            'median_lift': r4(med(vals)), 'min_lift': r4(min(vals)) if vals else None,
            'max_lift': r4(max(vals)) if vals else None,
            'verdict_mine': '合格' if (vals and all(x >= LINE for x in vals)
                                     and len(set(x > 0 for x in vals)) == 1) else '不合格'}
    return out

recompute, recompute_hi = {}, {}
for pool in ('all','qual'):
    recompute.update(summarise(pool, 'low')); recompute_hi.update(summarise(pool, 'high'))

theirs = h3['h3_summary']; mismatch = []
for k, v in recompute.items():
    t = theirs.get(k, {})
    for fld in ('pooled_lift','cw_pooled_lift','median_lift','min_lift','max_lift',
                'pooled_n','pooled_n_companies','sign_pos','sign_neg','usable_cells'):
        mv, tv = v[fld], t.get(fld)
        if mv is None or tv is None:
            if mv != tv: mismatch.append({'cell': k, 'field': fld, 'mine': mv, 'theirs': tv})
        elif isinstance(mv, float) and abs(mv - tv) > 0.0011:
            mismatch.append({'cell': k, 'field': fld, 'mine': mv, 'theirs': tv})
        elif isinstance(mv, int) and mv != tv:
            mismatch.append({'cell': k, 'field': fld, 'mine': mv, 'theirs': tv})
    for vv in VINT:
        mv = v['lifts_by_vintage'][str(vv)]; tv = t.get('lifts_by_vintage', {}).get(str(vv))
        if mv is None or tv is None:
            if mv != tv: mismatch.append({'cell': k, 'field': f'lift{vv}', 'mine': mv, 'theirs': tv})
        elif abs(mv - tv) > 0.0011:
            mismatch.append({'cell': k, 'field': f'lift{vv}', 'mine': mv, 'theirs': tv})

tie_rows = 0
for pool in ('all','qual'):
    for v in VINT:
        us = [r for r in ROWS if r['vintage'] == v and pool in pools_of(r)
              and r.get('opmD5') is not None and r.get('tr_cagr') is not None and r.get('opm') is not None]
        if us:
            m = st.median([r['opm'] for r in us]); tie_rows += sum(1 for r in us if r['opm'] == m)
tie_sens = {'prereg_is_silent_on_boundary': True, 'tie_rows_total': tie_rows, 'cells': {}}
for k in recompute:
    a, b = recompute[k], recompute_hi[k]
    ds = [abs(a['lifts_by_vintage'][str(v)] - b['lifts_by_vintage'][str(v)])
          for v in VINT if a['lifts_by_vintage'][str(v)] is not None and b['lifts_by_vintage'][str(v)] is not None]
    tie_sens['cells'][k] = {'max_abs_shift': r4(max(ds)) if ds else None,
                            'median_lift_tie_low': a['median_lift'], 'median_lift_tie_high': b['median_lift'],
                            'max_lift_tie_low': a['max_lift'], 'max_lift_tie_high': b['max_lift'],
                            'below_line_under_both': a['n_lift_ge_line'] == 0 and b['n_lift_ge_line'] == 0}

inter = {}
for pool in ('all','qual'):
    hi = recompute[f'{pool}/high']['lifts_by_vintage']; lo = recompute[f'{pool}/low']['lifts_by_vintage']
    ds = [round(hi[str(v)]-lo[str(v)], 4) for v in VINT
          if hi[str(v)] is not None and lo[str(v)] is not None]
    inter[pool] = {'diffs': ds, 'median_diff': r4(med(ds)), 'min': min(ds), 'max': max(ds),
                   'sign_pos': sum(1 for x in ds if x > 0), 'sign_neg': sum(1 for x in ds if x < 0)}
    t = h3['interaction']['pools'][pool]
    if abs(inter[pool]['median_diff'] - t['median_diff']) > 0.0011:
        mismatch.append({'cell': f'interaction/{pool}', 'field': 'median_diff',
                         'mine': inter[pool]['median_diff'], 'theirs': t['median_diff']})

# ================================================== 2) 事後の帯
def cut_rows(pool, thr):
    return [r for r in ROWS if pool in pools_of(r) and r.get('opmD5') is not None
            and r.get('tr_cagr') is not None and r.get('opm') is not None and r['opm'] >= thr]
posthoc = {}
for pool in ('all','qual'):
    for thr in (30, 40, 50):
        rs = cut_rows(pool, thr); a = [r for r in rs if r['opmD5'] >= 0]; b = [r for r in rs if r['opmD5'] < 0]
        if len(a) < MIN_ARM or len(b) < MIN_ARM:
            posthoc[f'{pool}/opm_ge_{thr}'] = {'usable': False, 'n': len(rs), 'arms': [len(a), len(b)]}; continue
        cw, _, _ = cw_lift_of(rs)
        posthoc[f'{pool}/opm_ge_{thr}'] = {
            'usable': True, 'n': len(rs), 'n_nonneg': len(a), 'n_neg': len(b),
            'n_companies': len({r['ticker'] for r in rs}), 'n_companies_neg': len({r['ticker'] for r in b}),
            'p_hit_nonneg': r4(frac([hit(r) for r in a])), 'p_hit_neg': r4(frac([hit(r) for r in b])),
            'lift': r4(frac([hit(r) for r in a]) - frac([hit(r) for r in b])), 'cw_lift': r4(cw),
            'med_tr_neg': r4(med([r['tr_cagr'] for r in b])),
            'impair_neg_rows': sum(1 for r in b if r['tr_cagr'] <= IMPAIR),
            'impair_neg_companies': len({r['ticker'] for r in b if r['tr_cagr'] <= IMPAIR})}
for k, v in posthoc.items():
    t = h3['v_question']['cuts'].get(k)
    if not t or not v.get('usable'): continue
    for fld in ('lift','cw_lift','p_hit_neg'):
        if abs(v[fld] - t[fld]) > 0.0011:
            mismatch.append({'cell': k, 'field': fld, 'mine': v[fld], 'theirs': t[fld]})

# ================================================== 置換の道具
HIT_FULL = {(r['vintage'], r['ticker']): hit(r) for r in ROWS if r.get('tr_cagr') is not None}
UNI_FULL = sorted({r['ticker'] for r in ROWS})

def groups_of(pool, key='opm', tie='low'):
    C = cells(pool, key, tie); g = {}
    for v in VINT:
        if not C[v]: continue
        for lv in ('high','low'):
            g[(v, lv)] = [(r['ticker'], r['opmD5'] < 0, hit(r)) for r in sorted(C[v][lv], key=lambda x: x['ticker'])]
    return g

def med_lifts(groups, om=None):
    out = {}
    for lv in ('high','low'):
        ls = []
        for v in VINT:
            g = groups.get((v, lv))
            if not g: continue
            pr = []
            for t, n, h in g:
                hh = h if om is None else om.get((v, t))
                if hh is None: continue
                pr.append((n, hh))
            a = [h for n, h in pr if not n]; b = [h for n, h in pr if n]
            if len(a) < MIN_ARM or len(b) < MIN_ARM: continue
            ls.append(sum(a)/len(a) - sum(b)/len(b))
        out[lv] = ls
    return out

def run_nulls(groups, NP, seed):
    """A=測定側の再現（グループ内で全体順位に並べ替え）／B=会社ブロック（ドナーは全パネル）／C=素朴（グループ内独立）"""
    obs = {lv: med(v) for lv, v in med_lifts(groups).items()}
    res = {'observed': {lv: r4(obs[lv]) for lv in obs}}
    for null in ('A_theirs_reconstructed','B_company_block','C_naive_within_group'):
        rnd = random.Random(seed); nl = {'high': [], 'low': []}; passes = 0; drops = 0; tot = 0
        for _ in range(NP):
            if null == 'A_theirs_reconstructed':
                order = UNI_FULL[:]; rnd.shuffle(order); rank = {t: i for i, t in enumerate(order)}
            elif null == 'B_company_block':
                sh = UNI_FULL[:]; rnd.shuffle(sh); pi = dict(zip(UNI_FULL, sh))
                om = {}
                for (v, t) in HIT_FULL:
                    hh = HIT_FULL.get((v, pi[t]))
                    if hh is not None: om[(v, t)] = hh
            ls = {'high': [], 'low': []}
            for lv in ('high','low'):
                for v in VINT:
                    g = groups.get((v, lv))
                    if not g: continue
                    if null == 'A_theirs_reconstructed':
                        idx = sorted(range(len(g)), key=lambda i: rank[g[i][0]])
                        pr = [(g[i][1], g[idx[i]][2]) for i in range(len(g))]
                    elif null == 'C_naive_within_group':
                        hs = [x[2] for x in g]; rnd.shuffle(hs)
                        pr = [(g[i][1], hs[i]) for i in range(len(g))]
                    else:
                        pr = []
                        for t, n, h in g:
                            tot += 1; hh = om.get((v, t))
                            if hh is None: drops += 1; continue
                            pr.append((n, hh))
                    a = [h for n, h in pr if not n]; b = [h for n, h in pr if n]
                    if len(a) < MIN_ARM or len(b) < MIN_ARM: continue
                    ls[lv].append(sum(a)/len(a) - sum(b)/len(b))
                if ls[lv]: nl[lv].append(med(ls[lv]))
            ok = all(ls[lv] and all(x >= LINE for x in ls[lv]) and len(set(x > 0 for x in ls[lv])) == 1
                     for lv in ('high','low'))
            if ok: passes += 1
        e = {'n_perm': NP, 'false_positive_rate': round(passes/NP, 4)}
        if null == 'B_company_block': e['row_drop_rate'] = round(drops/tot, 4) if tot else None
        for lv in ('high','low'):
            s = sorted(nl[lv]); o = obs[lv]
            c = sum(1 for x in s if x >= o); p = c/len(s)
            e[lv] = {'null_p50': r4(s[len(s)//2]), 'null_p95': r4(s[int(.95*len(s))]),
                     'null_sd': r4(st.pstdev(s)), 'p_one_sided': round(p, 4),
                     'exceed_count': c, 'mc_se': round(math.sqrt(p*(1-p)/len(s)), 4)}
        res[null] = e
    return res

# ================================================== 3) 攻撃
A = {}

# (a) 業種内で opm を二分（水準差を外す）
sec = {}
for pool in ('all','qual'):
    rs = [r for r in ROWS if pool in pools_of(r) and r.get('opmD5') is not None
          and r.get('tr_cagr') is not None and r.get('opm') is not None]
    by = defaultdict(list)
    for r in rs: by[(r['vintage'], r.get('sic2'))].append(r)
    hi, lo = [], []
    for k, g in by.items():
        if k[1] is None or len(g) < 6: continue
        m = st.median([x['opm'] for x in g])
        hi += [x for x in g if x['opm'] > m]; lo += [x for x in g if x['opm'] <= m]
    lh, _, _ = lift_of(hi); ll, _, _ = lift_of(lo)
    sec[pool] = {'n_high': len(hi), 'n_low': len(lo), 'lift_high': r4(lh), 'lift_low': r4(ll),
                 'diff_high_minus_low': r4(lh-ll)}
A['a_sector_internal_split'] = sec

# (a2) 1業種抜き（事後の帯）
los = {}
for pool in ('all','qual'):
    for thr in (40, 50):
        k = f'{pool}/opm_ge_{thr}'; rs = cut_rows(pool, thr)
        outs = []
        for s in sorted({r.get('sic2') for r in rs if r.get('sic2')}):
            L, _, _ = lift_of([r for r in rs if r.get('sic2') != s])
            if L is not None: outs.append({'drop_sic2': s, 'lift': r4(L)})
        outs.sort(key=lambda x: x['lift'])
        los[k] = {'base_lift': posthoc[k].get('lift'), 'n_sectors_usable': len(outs),
                  'min': outs[0] if outs else None, 'max': outs[-1] if outs else None,
                  'median': r4(med([o['lift'] for o in outs])) if outs else None,
                  'n_below_line': sum(1 for o in outs if o['lift'] < LINE)}
A['a2_leave_one_sector_out'] = los

# (b) 規模の三分位
size = {}
for pool in ('all','qual'):
    C = cells(pool)
    for side in ('high','low'):
        bk = {0: [], 1: [], 2: []}
        for v in VINT:
            c = C[v]
            if not c: continue
            g = sorted([r for r in c[side] if r.get('rev') is not None], key=lambda r: r['rev'])
            n = len(g)
            if n < 9: continue
            for i, r in enumerate(g): bk[0 if i < n//3 else (1 if i < 2*n//3 else 2)].append(r)
        res = {}
        for bi, nm in ((0,'small'),(1,'mid'),(2,'big')):
            L, na, nb = lift_of(bk[bi]); res[nm] = {'n': len(bk[bi]), 'lift': r4(L), 'arms': [na, nb]}
        size[f'{pool}/{side}'] = res
A['b_size_tercile'] = size

# (c) 1社抜き（事後の帯）
loo = {}
for pool in ('all','qual'):
    for thr in (40, 50):
        k = f'{pool}/opm_ge_{thr}'; rs = cut_rows(pool, thr)
        comps = sorted({r['ticker'] for r in rs}); outs = []; unusable = 0
        for c in comps:
            L, _, _ = lift_of([r for r in rs if r['ticker'] != c])
            if L is None: unusable += 1
            else: outs.append({'drop': c, 'lift': r4(L)})
        outs.sort(key=lambda x: x['lift'])
        loo[k] = {'base_lift': posthoc[k].get('lift'), 'n_companies': len(comps),
                  'n_unusable_after_drop': unusable,
                  'min': outs[0] if outs else None, 'max': outs[-1] if outs else None,
                  'median': r4(med([o['lift'] for o in outs])) if outs else None,
                  'n_below_line': sum(1 for o in outs if o['lift'] < LINE), 'n_evaluated': len(outs)}
A['c_leave_one_company_out'] = loo

# (d) 置換: 3つの帰無を並べる
A['d_permutation_three_nulls'] = {p: run_nulls(groups_of(p), 2000, SEED) for p in ('all','qual')}
A['d_note'] = ('A=測定側の再現（グループ内で全体順位に並べ替え）／B=会社ブロック（会社の結果ベクトルごと'
               '入れ替え・ドナーは全パネル956社なので腕の大きさが保たれる）／C=素朴（グループ内で独立に混ぜる'
               '＝この台帳が「偽陽性率を桁で過小評価する」と記録している版）。'
               'A と C の null 幅が一致するなら、A は会社ブロックを保っていない。')

# (d2) 事後の帯の置換 + family-wise
cuts = {f'{p}/opm_ge_{t}': cut_rows(p, t) for p in ('all','qual') for t in (30, 40, 50)}
def cut_lift(rs, om=None):
    a1 = a0 = b1 = b0 = 0
    for r in rs:
        h = HIT_FULL[(r['vintage'], r['ticker'])] if om is None else om.get((r['vintage'], r['ticker']))
        if h is None: continue
        if r['opmD5'] < 0: b1 += h; b0 += 1
        else: a1 += h; a0 += 1
    if a0 < MIN_ARM or b0 < MIN_ARM: return None
    return a1/a0 - b1/b0
obs_cut = {k: cut_lift(v) for k, v in cuts.items()}
obs_max = max(x for x in obs_cut.values() if x is not None)
rnd = random.Random(SEED+1); NP2 = 4000
nulls = {k: [] for k in cuts}; maxes = []
for _ in range(NP2):
    sh = UNI_FULL[:]; rnd.shuffle(sh); pi = dict(zip(UNI_FULL, sh))
    om = {}
    for (v, t) in HIT_FULL:
        hh = HIT_FULL.get((v, pi[t]))
        if hh is not None: om[(v, t)] = hh
    mx = None
    for k, rs in cuts.items():
        L = cut_lift(rs, om)
        if L is None: continue
        nulls[k].append(L); mx = L if mx is None else max(mx, L)
    if mx is not None: maxes.append(mx)
sm = sorted(maxes)
A['d2_posthoc_permutation'] = {
    'n_perm': NP2, 'donor_pool': '全パネル956社（★ドナーを帯の中だけから採ると行が57%落ちて p が壊れる。下の my_own_defects）',
    'per_cut': {k: {'observed': r4(obs_cut[k]), 'n_null_draws': len(nulls[k]),
                    'null_p50': r4(sorted(nulls[k])[len(nulls[k])//2]),
                    'null_p95': r4(sorted(nulls[k])[int(.95*len(nulls[k]))]),
                    'p_one_sided': round(sum(1 for x in nulls[k] if x >= obs_cut[k])/len(nulls[k]), 4)}
                for k in cuts if obs_cut[k] is not None and nulls[k]},
    'family_wise': {'observed_max': r4(obs_max), 'null_max_p50': r4(sm[len(sm)//2]),
                    'null_max_p95': r4(sm[int(.95*len(sm))]),
                    'p': round(sum(1 for x in sm if x >= obs_max)/len(sm), 4)},
    'note': '6つの帯は入れ子で強く相関する。family-wise は「6つのうち最大が観測値以上」で測る'}

# (e) 分割を外した素の lift（＝H1相当）。分割は情報を足しているか
un = {}
for pool in ('all','qual'):
    per, pooled = [], []
    for v in VINT:
        us = [r for r in ROWS if r['vintage'] == v and pool in pools_of(r)
              and r.get('opmD5') is not None and r.get('tr_cagr') is not None and r.get('opm') is not None]
        L, _, _ = lift_of(us)
        if L is not None: per.append(round(L, 4))
        pooled += us
    pl, _, _ = lift_of(pooled)
    un[pool] = {'lifts': per, 'median_lift': r4(med(per)), 'pooled_lift': r4(pl), 'n': len(pooled),
                'sign_pos': sum(1 for x in per if x > 0), 'sign_neg': sum(1 for x in per if x < 0),
                'median_lift_high': recompute[f'{pool}/high']['median_lift'],
                'median_lift_low': recompute[f'{pool}/low']['median_lift']}
A['e_unsplit_lift'] = un
A['e_note'] = ('分割後の両側が素の lift より大きいのは Simpson 型——opmD5 の符号は opm の水準と相関し'
               '(ρ=+0.37)、水準は結果とも関係するので、束ねると交絡が効果を打ち消す。'
               '**つまり分割が足しているのは「交互作用」ではなく「層別による交絡の除去」＝H1 の精緻化**。')

# (g) 終点で条件づける問題: 開始時の利益率で切り直す
for r in ROWS:
    r['opm_start'] = (r['opm'] - r['opmD5']*100.0) if (r.get('opm') is not None and r.get('opmD5') is not None) else None
start = {}
for pool in ('all','qual'):
    C = cells(pool, 'opm_start')
    for side in ('high','low'):
        per, pooled = [], []
        for v in VINT:
            c = C[v]
            if not c: continue
            L, _, _ = lift_of(c[side])
            if L is not None: per.append(round(L, 4))
            pooled += c[side]
        pl, _, _ = lift_of(pooled)
        start[f'{pool}/{side}'] = {'lifts': per, 'median_lift': r4(med(per)), 'pooled_lift': r4(pl),
                                   'n': len(pooled), 'sign_pos': sum(1 for x in per if x > 0),
                                   'sign_neg': sum(1 for x in per if x < 0),
                                   'median_lift_when_split_on_END': recompute[f'{pool}/{side}']['median_lift']}
A['g_split_on_starting_margin'] = start
def spearman(xs, ys):
    n = len(xs)
    if n < 10: return None
    def rank(a):
        o = sorted(range(n), key=lambda i: a[i]); rk = [0.0]*n; i = 0
        while i < n:
            k = i
            while k+1 < n and a[o[k+1]] == a[o[i]]: k += 1
            av = (i+k)/2.0 + 1
            for q in range(i, k+1): rk[o[q]] = av
            i = k+1
        return rk
    rx, ry = rank(xs), rank(ys); mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    dx = math.sqrt(sum((rx[i]-mx)**2 for i in range(n))); dy = math.sqrt(sum((ry[i]-my)**2 for i in range(n)))
    return num/(dx*dy) if dx and dy else None
cor = {}
for pool in ('all','qual'):
    rs = [r for r in ROWS if pool in pools_of(r) and r.get('opmD5') is not None and r.get('opm') is not None]
    cor[pool] = {'n': len(rs),
                 'rho_opm_END_vs_opmD5': r4(spearman([r['opm'] for r in rs], [r['opmD5'] for r in rs])),
                 'rho_opm_START_vs_opmD5': r4(spearman([r['opm_start'] for r in rs], [r['opmD5'] for r in rs]))}
A['g_correlations'] = cor
A['g_note'] = ('opm(終点) = opm_start + opmD5 なので、**終点で高低に切ってから opmD5 の符号で割るのは'
               '同じ量で二度切っている**。終点で条件づけると ρ(opm,opmD5) は +0.37 と正に見えるが、'
               '開始時で条件づけると **−0.31/−0.51 と符号が反転**する＝素朴な平均回帰のとおり。'
               '測定側の「高マージンほど margin が上がっている（平均回帰の予想と逆）」は'
               '**終点で条件づけたことの産物**であって、事業の性質ではない。')
A['g_permutation_on_start_split'] = {p: run_nulls(groups_of(p, 'opm_start'), 1000, SEED+5)['B_company_block']
                                     for p in ('all','qual')}

# (h) 「高マージン」の実際の線
A['h_split_thresholds_pct'] = {p: {str(v): r4(cells(p)[v]['median']) for v in VINT if cells(p)[v]}
                               for p in ('all','qual')}
A['h_note'] = ('事前登録は「opm の中央値で二分」なので、all の**高マージンは 7.95〜12.64% 以上**、'
               'qual の**低マージンは 10〜19.3%**＝**all の高マージンと重なる**。'
               '二つのプールの high/low を同じ言葉で読んではいけない。'
               'V(opm 65%) はどちらのプールでも「高」だが、その帯の n は極めて薄い。')

# (j) 2013（opmD5 被覆48%）を落とす
drop13 = {}
for pool in ('all','qual'):
    g = groups_of(pool); g2 = {k: v for k, v in g.items() if k[0] != 2013}
    f8 = med_lifts(g); f7 = med_lifts(g2)
    rn = run_nulls(g2, 1000, SEED+2)['B_company_block']
    for lv in ('high','low'):
        drop13[f'{pool}/{lv}'] = {'median_all8': r4(med(f8[lv])), 'median_drop2013': r4(med(f7[lv])),
                                  'p_block_drop2013': rn[lv]['p_one_sided']}
A['j_drop_2013'] = drop13

# (k) 連続量
cont = {}
for pool in ('all','qual'):
    C = cells(pool)
    for side in ('high','low'):
        rs = [r for v in VINT if C[v] for r in C[v][side]]
        cont[f'{pool}/{side}'] = {'n': len(rs),
                                  'rho_opmD5_vs_tr_cagr': r4(spearman([r['opmD5'] for r in rs],
                                                                      [r['tr_cagr'] for r in rs]))}
A['k_continuous_rho'] = cont

# (l) ゼロ件に rule of three
A['l_zero_counts'] = {k: {'impair_rows_neg': v['impair_neg_rows'], 'n_rows_neg': v['n_neg'],
                          'n_companies_neg': v['n_companies_neg'],
                          'upper95_by_rows': round(3.0/v['n_neg'], 4),
                          'upper95_by_companies': round(3.0/v['n_companies_neg'], 4)}
                      for k, v in posthoc.items() if v.get('usable')}
A['l_note'] = '0件は真のゼロではない。社単位で数えると上限はさらに緩い（qual/opm>=50 は最大37.5%まで許す）'

# (n) 生き残った唯一の主張（all プール）を 20000 回で詰める
prec = {}
for pool in ('all',):
    g = groups_of(pool); obs = {lv: med(v) for lv, v in med_lifts(g).items()}
    rnd = random.Random(SEED+7); NP3 = 20000; nl = {'high': [], 'low': []}
    for _ in range(NP3):
        sh = UNI_FULL[:]; rnd.shuffle(sh); pi = dict(zip(UNI_FULL, sh))
        om = {}
        for (v, t) in HIT_FULL:
            hh = HIT_FULL.get((v, pi[t]))
            if hh is not None: om[(v, t)] = hh
        L = med_lifts(g, om)
        for lv in ('high','low'):
            if L[lv]: nl[lv].append(med(L[lv]))
    for lv in ('high','low'):
        s2 = sorted(nl[lv]); o = obs[lv]; c = sum(1 for x in s2 if x >= o); pv = c/len(s2)
        prec[f'{pool}/{lv}'] = {'observed': r4(o), 'n_perm': len(s2), 'exceed': c,
                                'p_one_sided': round(pv, 5),
                                'mc_se': round(math.sqrt(pv*(1-pv)/len(s2)), 5),
                                'null_p95': r4(s2[int(.95*len(s2))])}
A['n_precision_block_null_20000'] = prec

# (o) 外れ値の帯を落とす（|opm|>100% を全部除く。測定側は上側の7行しか落としていない）
trim = {}
KEEP = [r for r in ROWS if r.get('opm') is not None and abs(r['opm']) <= 100.0]
dropped = len(ROWS) - len(KEEP)
for pool in ('all','qual'):
    for side in ('high','low'):
        per, pooled = [], []
        for v in VINT:
            us = [r for r in KEEP if r['vintage'] == v and pool in pools_of(r)
                  and r.get('opmD5') is not None and r.get('tr_cagr') is not None]
            if not us: continue
            m = st.median([r['opm'] for r in us])
            g = [r for r in us if r['opm'] > m] if side == 'high' else [r for r in us if r['opm'] <= m]
            L, _, _ = lift_of(g)
            if L is not None: per.append(round(L, 4))
            pooled += g
        pl, _, _ = lift_of(pooled)
        trim[f'{pool}/{side}'] = {'median_lift': r4(med(per)), 'pooled_lift': r4(pl), 'n': len(pooled),
                                  'median_lift_untrimmed': recompute[f'{pool}/{side}']['median_lift'],
                                  'n_lift_ge_line': sum(1 for x in per if x >= LINE)}
trim['rows_dropped'] = dropped
A['o_trim_extreme_opm'] = trim

# (p) 層別が効く仕組み（Simpson）を数字で見せる
simp = {}
for pool in ('all','qual'):
    C = cells(pool); rec = {}
    for side in ('high','low'):
        rs = [r for v in VINT if C[v] for r in C[v][side]]
        neg = [r for r in rs if r['opmD5'] < 0]
        rec[side] = {'n': len(rs), 'share_opmD5_neg': r4(frac([1 if r['opmD5'] < 0 else 0 for r in rs])),
                     'base_hit': r4(frac([hit(r) for r in rs]))}
    simp[pool] = rec
A['p_simpson_mechanism'] = simp
A['p_note'] = ('低マージン側のほうが (i)opmD5<0 の割合が高く (ii)基礎的な hit 率も高い。'
               'だから束ねると「下がっている群」に高hitの低マージン社が偏って混ざり、素の lift が薄まる。'
               '層別はその交絡を外しているだけで、**高低で効果が違うことを示してはいない**。')

# (m) 窓の長さと基礎率
A['m_window_and_base'] = {str(v): {'years_median': r4(med([r['years'] for r in ROWS if r['vintage'] == v])),
                                   'base_hit': r4(frac([hit(r) for r in ROWS if r['vintage'] == v]))}
                          for v in VINT}

# ================================================== 判定
vals = {k: [x for x in v['lifts_by_vintage'].values() if x is not None] for k, v in recompute.items()}
verdict = {
    'line_from_prereg': 'lift >= 0.15 かつ 8ビンテージすべてで符号が同じ',
    'independent_recompute_mismatches': len(mismatch), 'mismatch_detail': mismatch[:20],
    'independent_recompute_agrees': len(mismatch) == 0,
    'by_cell_mine': {k: recompute[k]['verdict_mine'] for k in recompute},
    'max_lift_any_cell_any_vintage': r4(max(max(v) for v in vals.values() if v)),
    'overall': '不合格（refuted）——測定側の合否と一致',
    'what_broke': [
        '★事後の帯（qual/opm>=50 の lift 0.1487・opm>=40 の 0.1385）は**単独でも雑音と区別できない**。'
        '会社ブロック置換で p=0.164 / 0.0895、6帯の family-wise p=0.273。'
        'n=62 の帯の帰無は p95=0.222 で、観測値 0.149 はその内側',
        '同じ帯は1社抜きでも壊れる（qual/opm>=50: MA を抜くと 0.1487→0.0842／'
        '24社中4社は抜くと腕が20を割って評価不能）。1業種抜きでも qual/opm>=40 は SIC73 を抜くと 0.1385→0.0749',
        '★測定側の「高マージンほど margin が上がっている（平均回帰の予想と逆）」は'
        '**終点で条件づけたことの産物**。ρ(opm_END,opmD5)=+0.373 に対し ρ(opm_START,opmD5)=−0.306（qual は −0.507）で符号が反転する',
        '★開始時の利益率で切り直すと、唯一生き残っていた all/high の lift が 0.0558 → −0.0009 へ消える（置換 p=0.50）',
        '★測定側の置換の帰無は会社ブロックを保っていない。再現した null A の sd=0.0177・p95=0.0282 は'
        '素朴な「ビンテージ内で独立に混ぜる」null C（sd=0.0174・p95=0.0287）と数値上ほぼ同一で、'
        '真の会社ブロック null B（sd=0.0217・p95=0.0352）より23%狭い。'
        'その結果 all/high の p は 0.0010 → **0.0054** と5倍緩む',
        '「分割が交互作用を示した」わけではない。素の lift（分割なし）は all 0.0277 / qual 0.0131 で、'
        '分割後の両側（0.0558/0.0403）はどちらもそれより**大きい**＝Simpson 型の交絡除去。'
        '低マージン側は opmD5<0 の割合(0.614 vs 0.374)も基礎 hit 率(0.288 vs 0.227)も高い'],
    'what_survived_the_attacks': [
        'all/high の lift 0.0558 は、正しい会社ブロック置換でもゼロと区別できる（p=0.0054・108/20000・MC±0.0005）。'
        'all/low も p=0.031。**ただし線 0.15 の1/3で、測定側の検出力表ではこの帯の検出力は 0.001〜0.029**',
        '|opm|>100% の674行を落としても中央値はほぼ動かない（all/high 0.0558→0.0605）＝外れ値駆動ではない',
        '2013（opmD5 被覆48%）を落としても残る（all/high 中央値 0.0522・p=0.013）',
        '業種内で opm を二分し直しても all は正のまま（high 0.0256 / low 0.0445）。ただし縮む',
        'qual プールは3つの帰無すべてで完全に null（p=0.33〜0.47）＝ここは測定側の結論のとおり',
        '独立再計算・単位・qual の定義・look-ahead はすべて健全（食い違い0件）'],
    'how_far_to_trust': (
        'H3（交互作用）は**壊れている**——差の中央値 −0.0027/−0.0131、8ビンテージで4勝4敗、置換 p=0.92/0.75、'
        '開始時の利益率で切り直すと符号が定まらない。**「高い利益率から下がるほうが悪い」は支持されない。**'
        '残るのは H3 ではなく H1 の話——`all` プールで opmD5<0 は前方 hit を 3〜6pt 下げ、これは雑音ではない。'
        'だが (i)線 0.15 の1/3 (ii)この帯は検出力 0.001〜0.029 で試験の設計外 (iii)qual プールでは消える '
        '(iv)開始時の利益率で切ると消える、の4点により**買付規則にできる強さではない**。')}

defects.append({
    'what': '事後の帯の置換で、ドナーを**帯の中の会社だけ**から採っていた',
    'symptom': 'π(c) がそのビンテージに居ないと行が落ち、**行の57%が消えて** qual/opm>=50 は'
               '2000回中1999回で腕が20を割り「p=0.0000」を n_null=1 から出していた',
    'why_it_matters': 'この台帳が繰り返し戒める「0件は測定ではない」を、それを測る器の中で作った',
    'fix': 'ドナーを全パネル956社にする。行落ちは0.1%になり、qual/opm>=50 の p は 0.0000 → 0.16 へ',
    'lesson': 'p=0.0000 のような強い結論ほど、まず分母（有効な置換回数）を数える'})

out = {
    'generated': '2026-08-18',
    'tool': 'night/opmtrend_ref_h3.py',
    'role': 'H3 の反証専門。測定側のコードを import せず base から独立に組み直した。値・規約は1バイトも触っていない',
    'reads': ['out/opmtrend_base.json', 'out/opmtrend_h3.json', 'out/opm_trend_prereg.json',
              'out/retro_features2_*.json', 'out/retro_returns_*.json'],
    'seed': SEED,
    'unit_check': unit_check, 'lookahead': la,
    'split_tie_convention': {'matched_with': 'low（中央値ちょうどは低側＝測定側と同じ）',
                             'prereg_is_silent': True},
    'independent_recompute': recompute, 'independent_recompute_tie_high': recompute_hi,
    'tie_sensitivity': tie_sens, 'interaction_mine': inter, 'posthoc_cuts_mine': posthoc,
    'attacks': A, 'verdict': verdict, 'warnings': warnings, 'my_own_defects': defects,
    'limits': [
        '母集団は同じ956社・窓はすべて2026-08で終わる＝真の out-of-sample はゼロ',
        '8ビンテージは独立標本ではない（1社あたり最大8行・実912社にのべ6546行）',
        'opmD5 は一過性費用を調整しない会計上の営業利益率の差',
        '2013 は opmD5 の被覆48%・欠測が小型に偏る（別の母集団の疑い）',
        '2019〜2022 のベンチマークは SPY ではない。ただし H3 は15%ハードルだけを使うので今回は噛んでいない',
        '生存バイアスは既記録のまま（左尾は 2.00〜25.68% の幅）',
        '会社ブロック置換のドナーは全パネルから採る＝プール外の結果が混ざる。'
        'lift は同一集合内の差なので基礎率の平行移動は相殺するが、厳密な層内交換可能性ではない'],
}
with open(os.path.join(OUT, 'opmtrend_ref_h3.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print('mismatches vs 測定側:', len(mismatch))
for m in mismatch[:10]: print('  ', m)
print('written out/opmtrend_ref_h3.json')
