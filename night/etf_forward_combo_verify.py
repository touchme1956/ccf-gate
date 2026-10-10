#!/usr/bin/env python3
"""night/etf_forward_combo_verify.py — ETFの組み合わせ（etf_forward_combo.py）の独立の再計算（2026-10-10）

別の検証役が事前登録 out/etf_combo_prereg.json（b4ce1ee）の文章だけから書いたもの（本体 night/etf_forward_combo.py と
その結果は読まずに書いた）。repo に置くとき、入力の読み込み（一時ファイル経由→etf_forward_rank.main(write=False) を直接）と
書き出し先だけを直し、最後に本体の結果 out/etf_forward_combo.json と突き合わせる段を足した。主の世界（感度なし）だけを再計算する。

出力: out/etf_forward_combo_verify.json
"""
import itertools, json, math, os, sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as RK   # noqa: E402

OUT = os.path.join(BASE, 'out', 'etf_forward_combo_verify.json')
MAIN_OUT = os.path.join(BASE, 'out', 'etf_forward_combo.json')

res0 = RK.main(write=False)
rows, chains = res0['rows'], res0['chains']
MA1, MA2 = RK.months(*RK.A1), RK.months(*RK.A2)
assert len(MA1) == 313 and MA1[0] == 200009 and MA1[-1] == 202609
assert len(MA2) == 180 and MA2[0] == 201110 and MA2[-1] == 202609

CANDS = ['VT', 'VOO', 'VEA', 'VWO', 'TOPIX', 'QQQM', 'VUG', 'XLK', 'SMH', 'XLV', 'XLP', 'XLU', 'XLE', 'ITA',
         'VTV', 'VBR', 'IJR', 'MOAT', 'PXF', 'DEM', 'GLDM']
N = len(CANDS)
ix = {c: i for i, c in enumerate(CANDS)}

# ---- 候補の決まりの点検: 21本は A1 の毎月の値が全部そろい、外した4本はそろわない ----
for c in CANDS:
    miss = [m for m in MA1 if m not in chains[c]]
    assert not miss, (c, miss[:5])
excluded_missing = {c: sum(1 for m in MA1 if m not in chains[c]) for c in ['EPI', 'VIG', 'VYM', 'RSP']}

# ---- 1本ずつの入力 ----
R = np.array([[chains[c][m] for m in MA1] for c in CANDS], dtype=np.float64)        # 21 x 313 毎月の算術リターン
T1 = R.shape[1]
a2_mask = np.array([m >= MA2[0] for m in MA1])
T2 = int(a2_mask.sum())
assert T2 == 180
adjA1 = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in CANDS])
adjA2 = np.array([rows[c]['A2'] - rows[c]['A2_gross'] for c in CANDS])
GB = np.array([rows[c]['B'] for c in CANDS])
GC = np.array([rows[c]['C'] for c in CANDS])
gB, gC = np.log1p(GB), np.log1p(GC)
L = np.log1p(R)
Lc = L - L.mean(axis=1, keepdims=True)
S = (Lc @ Lc.T) / T1 * 12.0                     # 毎月の対数リターンの母共分散 × 12
s2 = np.diag(S).copy()

for i, c in enumerate(CANDS):                   # 1本ずつ、順位付けの値と同じになるか
    a1g = math.expm1(L[i].sum() * 12 / T1)
    a2g = math.expm1(L[i][a2_mask].sum() * 12 / T2)
    assert abs(a1g - rows[c]['A1_gross']) < 1e-12, (c, a1g, rows[c]['A1_gross'])
    assert abs(a2g - rows[c]['A2_gross']) < 1e-12, (c, a2g, rows[c]['A2_gross'])
    v = R[i].std() * math.sqrt(12)
    assert abs(v - rows[c]['vol_A1']) < 1e-12, (c, v, rows[c]['vol_A1'])


def evaluate(W):
    W = np.asarray(W, dtype=np.float64)
    P = W @ R
    LP = np.log1p(P)
    A1 = np.expm1(LP.sum(axis=1) * 12 / T1) + W @ adjA1
    A2 = np.expm1(LP[:, a2_mask].sum(axis=1) * 12 / T2) + W @ adjA2
    vol = P.std(axis=1) * math.sqrt(12)
    V = np.cumprod(1.0 + P, axis=1)
    peak = np.maximum.accumulate(np.maximum(V, 1.0), axis=1)     # 始まりの1.0も山に数える
    mdd = np.minimum((V / peak - 1.0).min(axis=1), 0.0)
    quad = np.einsum('ij,jk,ik->i', W, S, W)
    bonus = 0.5 * (W @ s2 - quad)
    B = np.expm1(W @ gB + bonus)
    C = np.expm1(W @ gC + bonus)
    M4 = np.stack([A1, A2, B, C], axis=1)
    return dict(A1=A1, A2=A2, B=B, C=C, mean=M4.mean(axis=1), worst=M4.min(axis=1), vol=vol, mdd=mdd, bonus=bonus)


def compositions(total, k):
    if k == 1:
        yield (total,)
        return
    for first in range(1, total - k + 2):
        for rest in compositions(total - first, k - 1):
            yield (first,) + rest


def build_grid(kmax=4):
    combos_w = []
    for k in range(1, kmax + 1):
        comps = list(compositions(10, k))
        for sub in itertools.combinations(range(N), k):
            for cp in comps:
                combos_w.append((sub, cp))
    Wint = np.zeros((len(combos_w), N), dtype=np.int8)
    for r, (sub, cp) in enumerate(combos_w):
        for j, w in zip(sub, cp):
            Wint[r, j] = w
    return Wint


Wint = build_grid(4)
n = Wint.shape[0]
assert n == 552531
keys = ['A1', 'A2', 'B', 'C', 'mean', 'worst', 'vol', 'mdd', 'bonus']
res = {k: np.empty(n) for k in keys}
CH = 40000
for s in range(0, n, CH):
    e = evaluate(Wint[s:s + CH].astype(np.float64) / 10.0)
    for k in keys:
        res[k][s:s + CH] = e[k]

w_now = np.zeros(N); w_now[ix['QQQM']] = 50 / 85; w_now[ix['XLK']] = 15 / 85; w_now[ix['SMH']] = 20 / 85
NOW = {k: float(v[0]) for k, v in evaluate(w_now[None, :]).items()}


def wdesc(r):
    return {CANDS[j]: int(Wint[r, j]) * 10 for j in range(N) if Wint[r, j]}


def pick(mask, primary, secondary, tertiary, sign=(-1, -1, 1)):
    idx = np.nonzero(mask)[0]
    if idx.size == 0:
        return None, []
    order = np.lexsort((sign[2] * res[tertiary][idx], sign[1] * res[secondary][idx], sign[0] * res[primary][idx]))
    return idx[order[0]], idx[order[:5]]


def describe(r):
    return dict(weights=wdesc(r), **{k: float(res[k][r]) for k in keys})


out = {'generated': __import__('datetime').date.today().isoformat(), 'tool': 'night/etf_forward_combo_verify.py',
       'note': '別の検証役が事前登録の文章だけから書いた独立の再計算（主の世界だけ）。本体の結果との突き合わせは compare'}
m_r1 = (res['mean'] >= NOW['mean']) & (res['vol'] <= NOW['vol'])
r1, r1_top = pick(m_r1, 'worst', 'mean', 'vol')
m_r2 = (res['worst'] >= NOW['worst']) & (res['vol'] <= NOW['vol'])
r2, r2_top = pick(m_r2, 'mean', 'worst', 'vol')
f1, f1_top = pick(np.ones(n, bool), 'mean', 'worst', 'vol')
f2, f2_top = pick(np.ones(n, bool), 'worst', 'mean', 'vol')
voo_r = int(np.nonzero((Wint[:, ix['VOO']] == 10))[0][0])
VOO = {k: float(res[k][voo_r]) for k in keys}
m_r3 = ((res['A1'] >= VOO['A1']) & (res['A2'] >= VOO['A2']) & (res['B'] >= VOO['B']) & (res['C'] >= VOO['C'])
        & (res['vol'] <= VOO['vol']))
r3, r3_top = pick(m_r3, 'mean', 'worst', 'vol')
out['counts'] = dict(grid=n, R1_feasible=int(m_r1.sum()), R2_feasible=int(m_r2.sum()), R3_feasible=int(m_r3.sum()))
out['now'] = NOW
for name, r, top in [('R1', r1, r1_top), ('R2', r2, r2_top), ('F1', f1, f1_top), ('F2', f2, f2_top), ('R3', r3, r3_top)]:
    out[name] = describe(r) if r is not None else None
    out[name + '_top5'] = [describe(t) for t in top]
dom = ((res['mean'] >= NOW['mean']) & (res['worst'] >= NOW['worst']) & (res['vol'] <= NOW['vol'])
       & ((res['mean'] > NOW['mean']) | (res['worst'] > NOW['worst']) | (res['vol'] < NOW['vol'])))
out['dominance_count'] = int(dom.sum())

others = [c for c in CANDS if c not in ('QQQM', 'SMH')]
tab = {}
for X in others + ['QQQM', 'SMH']:
    w = np.zeros(N); w[ix['QQQM']] += 50 / 85; w[ix['SMH']] += 20 / 85; w[ix[X]] += 15 / 85
    tab[X] = {k: float(v[0]) for k, v in evaluate(w[None, :]).items()}
base = tab['XLK']
qual = [X for X in others if X != 'XLK' and tab[X]['mean'] >= base['mean'] and tab[X]['worst'] >= base['worst'] and tab[X]['vol'] <= base['vol']]
qual_sorted = sorted(qual, key=lambda X: (-tab[X]['worst'], -tab[X]['mean'], tab[X]['vol']))
out['other15'] = tab
out['other15_qualifying'] = qual_sorted
out['other15_pick'] = qual_sorted[0] if qual_sorted else 'XLK'
wr1 = Wint[r1].astype(float) / 10
out['R1_sanity'] = dict(
    bonus_pp=float(res['bonus'][r1] * 100),
    A1_weighted_avg_members=float(sum(wr1[j] * rows[CANDS[j]]['A1'] for j in range(N))),
    A1_realized_log_bonus_pp=float(100 * (np.log1p(wr1 @ R).sum() * 12 / T1 - sum(wr1[j] * L[j].sum() * 12 / T1 for j in range(N)))))
out['excluded_A1_missing_months'] = excluded_missing

# ---- 本体の結果との突き合わせ（主の世界・小数2桁） ----
cmp, ok = {}, True
if os.path.exists(MAIN_OUT):
    mm = json.load(open(MAIN_OUT))['results']['main']

    def same(d_main, d_ver, label):
        pairs = [('A1(%/年)', 'A1'), ('A2(%/年)', 'A2'), ('B(%/年)', 'B'), ('C(%/年)', 'C'), ('平均(%/年)', 'mean'), ('最悪(%/年)', 'worst')]
        diff = {a: (d_main[a], round(100 * d_ver[b], 2)) for a, b in pairs if abs(d_main[a] - round(100 * d_ver[b], 2)) > 0.005}
        if 'weights' in d_ver and d_main.get('weights') is not None and d_main['weights'] != d_ver['weights']:
            diff['weights'] = (d_main['weights'], d_ver['weights'])
        cmp[label] = '一致' if not diff else diff
        return not diff
    ok &= same(mm['今'], NOW, '今')
    for nm in ('R1', 'R2', 'F1', 'F2', 'R3'):
        ok &= same(mm['picks'][nm], out[nm], nm)
    cmp['other15'] = '一致' if mm['other15']['pick'] == out['other15_pick'] else (mm['other15']['pick'], out['other15_pick'])
    cmp['dominance'] = '一致' if mm['dominating_now'] == out['dominance_count'] else (mm['dominating_now'], out['dominance_count'])
    ok &= cmp['other15'] == '一致' and cmp['dominance'] == '一致'
out['compare'] = dict(all_match=bool(ok), detail=cmp)
json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
print(f'→ {OUT}  本体との突き合わせ: {"全部一致" if ok else "食い違いあり"}')
print(json.dumps(cmp, ensure_ascii=False))
print('F2 の上位2:', [(t['weights'], round(100 * t['worst'], 7)) for t in out['F2_top5'][:2]])
print('R1 の上位2:', [(t['weights'], round(100 * t['worst'], 4)) for t in out['R1_top5'][:2]])
