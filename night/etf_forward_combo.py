#!/usr/bin/env python3
"""night/etf_forward_combo.py — ETFの組み合わせを4つの世界で選ぶ（2026-10-10・ユーザー「組み合わせるなら？」）

読むだけ。門・採点・配分には触れない。事前登録 out/etf_combo_prereg.json（b4ce1ee・測る前に固定）どおり。
1本ずつの4つの世界の数字と毎月のリターンは night/etf_forward_rank.py と同じ計算（同じデータの器・同じキャッシュ）を使う。

  A1・A2 … 組み合わせを毎月組み直した実績の幾何年率（費用前の器のデータ）＋ Σw_i（A1の正味−A1の費用前）
  B・C   … 各本の正味の複利 G_i から g_p = Σw_i ln(1+G_i) + ½(Σw_i s_i² − w'Sw)、G_p = e^{g_p} − 1
            （S は A1 の窓の毎月の対数リターンの共分散×12＝ぶれと相関は 2000-2026 と同じと置く）
  1〜4本（感度 K3 は5本まで）・10%刻み・入れる本は各10%以上。

出力: out/etf_forward_combo.json
"""
import datetime, itertools, json, math, os, sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R   # noqa: E402

OUT = os.path.join(BASE, 'out', 'etf_forward_combo.json')
PREREG = 'out/etf_combo_prereg.json（b4ce1ee）'
CANDS = ['VT', 'VOO', 'VEA', 'VWO', 'TOPIX', 'QQQM', 'VUG', 'XLK', 'SMH', 'XLV', 'XLP', 'XLU', 'XLE', 'ITA',
         'VTV', 'VBR', 'IJR', 'MOAT', 'PXF', 'DEM', 'GLDM']
NOW = {'QQQM': 50 / 85, 'XLK': 15 / 85, 'SMH': 20 / 85}       # 今の目標の ETF 側（その他15＝XLK）
IFREE_EXTRA = 0.00495 - 0.0015                                # iFreeNEXT（税込0.495%）と QQQM（0.15%）の差
MAIN_K, MAX_K = 4, 5
VARIANTS = ['main', 'S0', 'S2', 'S3_0.3', 'S3_0.7', 'S4_GMO', 'S4_VG', 'S5', 'S6', 'K1', 'K2', 'K3']
POST = ['K4', 'K4_SMHのみ']                                  # 事後の点検（事前登録の外・安定性の数には入れない）
# tech_persist: 過去10年の1位の業種（今は Chips＝半導体・電子部品）は次の10年に市場に中央 −4.0%/年（81窓・勝率26%）。
# 市場の年率は B・C で据え置くので、Chips が市場に −4.0 なら残り（市場の 80.7%）は +4.0×0.193/0.807＝+0.96。
# 次の10年だけ効いてその後は0と置き、20年に薄めて半分。各米国ETFは中身の Chips の比重で（VOO は0になる）。米国外・金は0
CHIPS_GAP, CHIPS_MKT = 0.040, 0.193
SMH_PENALTY = 0.020                                           # 最初に試した版: SMH だけ −2.0%/年（XLK・QQQM の半導体に掛けていなかった）
VAR_JA = {'main': '主（事前登録どおり）', 'S0': 'B・C を業種の時価総額の下限なしで', 'S2': 'A2 を外す', 'S3_0.3': '上乗せの縮み0.3',
          'S3_0.7': '縮み0.7', 'S4_GMO': 'C を GMO に', 'S4_VG': 'C を Vanguard に', 'S5': '期間30年', 'S6': '外国税なし',
          'K1': 'B・C で分散の上乗せを入れない', 'K2': 'B・C の共分散を A2 の窓から', 'K3': '5本まで',
          'K4': '★事後: 半導体の基礎率（B・C で各米国ETFに中身の Chips の比重で 次の10年 −4.0%/年〔残りは +0.96〕を20年に薄めて）',
          'K4_SMHのみ': '★事後（最初に試した版）: SMH だけ B・C で −2.0%/年'}


def compositions(total, k):
    """total（10）を k 個の正の整数に分ける全通り"""
    out = []
    for cuts in itertools.combinations(range(1, total), k - 1):
        b = (0,) + cuts + (total,)
        out.append([b[i + 1] - b[i] for i in range(k)])
    return np.array(out, dtype=np.int64)


def path_stats(Rp, T):
    """Rp: (..., T) 毎月のリターン → 幾何年率・ぶれ（母標準偏差×√12）・最大下落"""
    L = np.log1p(Rp)
    cs = np.cumsum(L, axis=-1)
    geo = np.expm1(cs[..., -1] * 12 / T)
    vol = Rp.std(axis=-1) * math.sqrt(12)
    peak = np.maximum(np.maximum.accumulate(cs, axis=-1), 0.0)
    mdd = np.expm1((cs - peak).min(axis=-1))
    return geo, vol, mdd


def main():
    res = R.main(write=False)
    rows, chains = res['rows'], res['chains']
    k1, k2 = R.months(*R.A1), R.months(*R.A2)
    n = len(CANDS)
    G1 = np.array([[chains[c][m] for m in k1] for c in CANDS])      # 欠けがあれば KeyError で止まる（欠測を0と読まない）
    G2 = np.array([[chains[c][m] for m in k2] for c in CANDS])
    T1, T2 = len(k1), len(k2)

    # 1本ずつの数字（順位付けと同じ）
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in CANDS])
    adj2 = np.array([rows[c]['A2'] - rows[c]['A2_gross'] for c in CANDS])
    assert np.allclose(adj, adj2), 'A1 と A2 の費用・税の差が食い違う'
    tax = np.array([rows[c]['tax_drag'] for c in CANDS])
    GV = {   # 各感度の B・C（正味）
        'main': ('B', 'C'), 'S0': ('_b_raw', '_c_raw'), 'S3_0.3': ('_b03', '_c03'), 'S3_0.7': ('_b07', '_c07'),
        'S4_GMO': ('B', '_c_gmo'), 'S4_VG': ('B', '_c_vg'), 'S5': ('B', '_c_h30'),
    }

    def gbc(var):
        kb, kc = GV.get(var, ('B', 'C'))
        gb = np.array([rows[c][kb] for c in CANDS]); gc = np.array([rows[c][kc] for c in CANDS])
        if var == 'S6':
            gb, gc = gb + tax, gc + tax
        if var == 'K4':
            gb, gc = gb + chips_adj, gc + chips_adj
        if var == 'K4_SMHのみ':
            j = CANDS.index('SMH')
            gb, gc = gb.copy(), gc.copy()
            gb[j] -= SMH_PENALTY; gc[j] -= SMH_PENALTY
        return gb, gc
    chips_share = {}
    for c in CANDS:
        if c == 'VOO':
            chips_share[c] = CHIPS_MKT
        elif R.C[c]['us']:
            chips_share[c] = float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)   # 上位6業種に無ければ0
    rest = CHIPS_GAP * CHIPS_MKT / (1 - CHIPS_MKT)
    chips_adj = np.array([((-CHIPS_GAP * chips_share[c] + rest * (1 - chips_share[c])) / 2) if c in chips_share else 0.0 for c in CANDS])
    L1, L2 = np.log1p(G1), np.log1p(G2)
    S1 = np.cov(L1, bias=True) * 12
    S2 = np.cov(L2, bias=True) * 12
    s1, s2 = np.diag(S1).copy(), np.diag(S2).copy()

    # ── 全組み合わせ ──
    blocks = []
    for k in range(1, MAX_K + 1):
        comps = compositions(10, k)
        subs = np.array(list(itertools.combinations(range(n), k)), dtype=np.int64)
        blocks.append((k, comps, subs))
    N = sum(len(c) * len(s) for _, c, s in blocks)
    Wint = np.zeros((N, n), dtype=np.uint8)
    nk = np.zeros(N, dtype=np.int8)
    a1g = np.empty(N); a2g = np.empty(N); vol1 = np.empty(N); mdd1 = np.empty(N); q1 = np.empty(N); q2 = np.empty(N)
    pos = 0
    for k, comps, subs in blocks:
        cw = comps / 10.0
        Ck = len(comps)
        step = max(1, 40000 // Ck)
        for b0 in range(0, len(subs), step):
            idx = subs[b0:b0 + step]
            B = len(idx)
            Rp1 = np.matmul(cw[None, :, :], G1[idx])                 # (B, Ck, T1)
            g, v, d = path_stats(Rp1, T1)
            Rp2 = np.matmul(cw[None, :, :], G2[idx])
            g2 = np.expm1(np.log1p(Rp2).sum(axis=-1) * 12 / T2)
            S1s = S1[idx[:, :, None], idx[:, None, :]]
            S2s = S2[idx[:, :, None], idx[:, None, :]]
            qq1 = np.einsum('ck,bkl,cl->bc', cw, S1s, cw)
            qq2 = np.einsum('ck,bkl,cl->bc', cw, S2s, cw)
            sl = slice(pos, pos + B * Ck)
            a1g[sl] = g.ravel(); vol1[sl] = v.ravel(); mdd1[sl] = d.ravel(); a2g[sl] = g2.ravel()
            q1[sl] = qq1.ravel(); q2[sl] = qq2.ravel(); nk[sl] = k
            rr = np.arange(pos, pos + B * Ck)
            for j in range(k):
                Wint[rr, np.repeat(idx[:, j], Ck)] = np.tile(comps[:, j], B)
            pos += B * Ck
    assert pos == N
    W = Wint.astype(np.float64) / 10.0
    assert np.allclose(W.sum(axis=1), 1.0)

    def base_of(Wf):
        """任意の重み（組み合わせの外の『今』など）の実績の部分"""
        Rp1 = Wf @ G1; Rp2 = Wf @ G2
        g, v, d = path_stats(Rp1, T1)
        g2 = np.expm1(np.log1p(Rp2).sum(axis=-1) * 12 / T2)
        return dict(a1g=g, a2g=g2, vol=v, mdd=d, q1=np.einsum('mi,ij,mj->m', Wf, S1, Wf), q2=np.einsum('mi,ij,mj->m', Wf, S2, Wf))

    def worlds(Wf, bs, var):
        av = adj + (tax if var == 'S6' else 0.0)
        A1 = bs['a1g'] + Wf @ av
        A2 = bs['a2g'] + Wf @ av
        gb, gc = gbc(var)
        if var == 'K1':
            Bw, Cw = Wf @ gb, Wf @ gc
            bonus = np.zeros(len(A1))
        else:
            sv, qv = (s2, bs['q2']) if var == 'K2' else (s1, bs['q1'])
            bonus = 0.5 * (Wf @ sv - qv)
            Bw = np.expm1(Wf @ np.log1p(gb) + bonus)
            Cw = np.expm1(Wf @ np.log1p(gc) + bonus)
        ws = [A1, A2, Bw, Cw] if var != 'S2' else [A1, Bw, Cw]
        st = np.vstack(ws)
        return dict(A1=A1, A2=A2, B=Bw, C=Cw, mean=st.mean(axis=0), worst=st.min(axis=0), bonus=bonus, names=['A1', 'A2', 'B', 'C'] if var != 'S2' else ['A1', 'B', 'C'])

    grid_bs = dict(a1g=a1g, a2g=a2g, vol=vol1, mdd=mdd1, q1=q1, q2=q2)
    wnow = np.array([[NOW.get(c, 0.0) for c in CANDS]])
    now_bs = base_of(wnow)
    voo_i = CANDS.index('VOO')
    wvoo = np.zeros((1, n)); wvoo[0, voo_i] = 1.0
    voo_bs = base_of(wvoo)

    # 単体で組み合わせの道と同じ値になるか（自己検問）
    for c in CANDS:
        j = CANDS.index(c)
        i1 = np.where((nk == 1) & (Wint[:, j] == 10))[0][0]
        wm = worlds(W[i1:i1 + 1], {k: v[i1:i1 + 1] for k, v in grid_bs.items()}, 'main')
        for wn in ('A1', 'A2', 'B', 'C'):
            assert abs(wm[wn][0] - rows[c][wn]) < 1e-9, (c, wn, wm[wn][0], rows[c][wn])
        assert abs(vol1[i1] - rows[c]['vol_A1']) < 1e-9 and abs(mdd1[i1] - rows[c]['maxdd_A1']) < 1e-9, c

    def wdict(i):
        return {CANDS[j]: int(Wint[i, j]) * 10 for j in np.argsort(-Wint[i].astype(int), kind='stable') if Wint[i, j]}

    def pct(x, d=2):
        return None if x is None else round(float(x) * 100, d)

    def describe(Wf_row, bs_row, wv, i_or_none=None, label=None, weights=None, voo=None):
        names = wv['names']
        vals = {nm: float(wv[nm][0]) for nm in ('A1', 'A2', 'B', 'C')}
        worst_nm = min(names, key=lambda nm: vals[nm])
        out = dict(label=label, weights=weights, **{f'{nm}(%/年)': pct(vals[nm]) for nm in ('A1', 'A2', 'B', 'C')},
                   **{'平均(%/年)': pct(wv['mean'][0]), '最悪(%/年)': pct(wv['worst'][0]), '最悪の世界': worst_nm,
                      'A1_ぶれ(%/年)': pct(bs_row['vol'][0], 1), 'A1_最大下落(%)': pct(bs_row['mdd'][0], 1),
                      'B・Cの分散の上乗せ(%/年)': pct(wv['bonus'][0], 2)})
        if voo is not None:
            out['どの世界でもS&P500以上'] = bool(all(vals[nm] >= float(voo[nm][0]) - 1e-12 for nm in names))
        return out

    def pick(order_keys, feas):
        """order_keys: (主キー, 次, …) の配列（大きいほど良い）。feas の中で辞書順に最良の1つ"""
        ids = np.where(feas)[0]
        if len(ids) == 0:
            return None
        keys = [k[ids] for k in order_keys][::-1]
        return int(ids[np.lexsort([-k for k in keys])[0]])

    def frontier(mean, worst, feas, npts=8):
        ids = np.where(feas)[0]
        o = ids[np.lexsort((-worst[ids], -mean[ids]))]
        fr, best = [], -np.inf
        for i in o:
            if worst[i] > best + 1e-12:
                fr.append(int(i)); best = worst[i]
        if len(fr) <= npts:
            return fr
        ws = np.array([worst[i] for i in fr])
        targets = np.linspace(ws.min(), ws.max(), npts)
        chosen = []
        for t in targets:
            j = int(np.argmin(np.abs(ws - t)))
            if fr[j] not in chosen:
                chosen.append(fr[j])
        return sorted(chosen, key=lambda i: -mean[i])

    def overlap(wa, wb):
        return sum(min(wa.get(k, 0), wb.get(k, 0)) for k in set(wa) | set(wb)) / 100.0

    # その他15%
    others = [c for c in CANDS if c not in ('QQQM', 'SMH')]
    o_rows = []
    for x in others + ['QQQM', 'SMH']:
        w = dict(QQQM=50 / 85, SMH=20 / 85)
        w[x] = w.get(x, 0) + 15 / 85
        o_rows.append((x, np.array([[w.get(c, 0.0) for c in CANDS]])))
    o_W = np.vstack([r[1] for r in o_rows])
    o_bs = base_of(o_W)

    results = {}
    for var in VARIANTS + POST:
        mask = (nk <= (MAX_K if var == 'K3' else MAIN_K))
        wv = worlds(W, grid_bs, var)
        nw = worlds(wnow, now_bs, var)
        vw = worlds(wvoo, voo_bs, var)
        m0, w0, v0 = float(nw['mean'][0]), float(nw['worst'][0]), float(now_bs['vol'][0])
        mean, worst = wv['mean'], wv['worst']
        names = wv['names']
        geq_voo = np.all(np.vstack([wv[nm] >= float(vw[nm][0]) - 1e-12 for nm in names]), axis=0)
        P = {}
        P['R1'] = pick((worst, mean, -vol1), mask & (mean >= m0) & (vol1 <= v0))
        P['R2'] = pick((mean, worst, -vol1), mask & (worst >= w0) & (vol1 <= v0))
        P['F1'] = pick((mean, worst, -vol1), mask)
        P['F2'] = pick((worst, mean, -vol1), mask)
        P['R3'] = pick((mean, worst, -vol1), mask & geq_voo & (vol1 <= float(voo_bs['vol'][0])))
        dom = mask & (mean >= m0) & (worst >= w0) & (vol1 <= v0) & ((mean > m0) | (worst > w0) | (vol1 < v0))
        ent = dict(ja=VAR_JA[var], 今=describe(wnow, now_bs, nw, label='今', weights={k: round(v * 100, 1) for k, v in NOW.items()}, voo=vw),
                   picks={}, dominating_now=int(dom.sum()), n_combos=int(mask.sum()))
        for nm, i in P.items():
            if i is None:
                ent['picks'][nm] = None
                continue
            sub = {k: v[i:i + 1] for k, v in grid_bs.items()}
            ent['picks'][nm] = describe(W[i:i + 1], sub, {k: (v[i:i + 1] if isinstance(v, np.ndarray) else v) for k, v in wv.items()},
                                         label=nm, weights=wdict(i), voo=vw)
        # その他15%
        ow = worlds(o_W, o_bs, var)
        x_now = others.index('XLK')
        om0, ow0, ov0 = float(ow['mean'][x_now]), float(ow['worst'][x_now]), float(o_bs['vol'][x_now])
        o_tab = []
        for ii, (x, _) in enumerate(o_rows):
            d = describe(o_W[ii:ii + 1], {k: v[ii:ii + 1] for k, v in o_bs.items()},
                         {k: (v[ii:ii + 1] if isinstance(v, np.ndarray) else v) for k, v in ow.items()}, label=x, voo=vw)
            d['参考（その他の区分の外）'] = x in ('QQQM', 'SMH')
            d['XLKより平均・最悪とも上・ぶれ以下'] = bool(x not in ('QQQM', 'SMH', 'XLK') and ow['mean'][ii] >= om0 and ow['worst'][ii] >= ow0 and o_bs['vol'][ii] <= ov0)
            o_tab.append(d)
        cand = [d for d in o_tab if d['XLKより平均・最悪とも上・ぶれ以下']]
        o_pick = max(cand, key=lambda d: (d['最悪(%/年)'], d['平均(%/年)'], -d['A1_ぶれ(%/年)']))['label'] if cand else 'XLK'
        ent['other15'] = dict(pick=o_pick, table=sorted(o_tab, key=lambda d: -d['平均(%/年)']))
        if var == 'main':
            fr = frontier(mean, worst, mask & (vol1 <= v0))
            ent['frontier_ぶれが今以下'] = [describe(W[i:i + 1], {k: v[i:i + 1] for k, v in grid_bs.items()},
                                               {k: (v[i:i + 1] if isinstance(v, np.ndarray) else v) for k, v in wv.items()},
                                               label=f'F{j + 1}', weights=wdict(i), voo=vw) for j, i in enumerate(fr)]
            fr_all = frontier(mean, worst, mask)
            ent['frontier_制約なし'] = [describe(W[i:i + 1], {k: v[i:i + 1] for k, v in grid_bs.items()},
                                            {k: (v[i:i + 1] if isinstance(v, np.ndarray) else v) for k, v in wv.items()},
                                            label=f'G{j + 1}', weights=wdict(i), voo=vw) for j, i in enumerate(fr_all)]
            bench = {}
            for c in ('VOO', 'VT', 'QQQM', 'SMH'):
                i1 = int(np.where((nk == 1) & (Wint[:, CANDS.index(c)] == 10))[0][0])
                bench[c] = describe(W[i1:i1 + 1], {k: v[i1:i1 + 1] for k, v in grid_bs.items()},
                                    {k: (v[i1:i1 + 1] if isinstance(v, np.ndarray) else v) for k, v in wv.items()}, label=c, weights={c: 100}, voo=vw)
            ent['benchmarks'] = bench
            ifr = dict(ent['今'])
            for nm in ('A1', 'A2', 'B', 'C', '平均', '最悪'):
                ifr[f'{nm}(%/年)'] = round(ifr[f'{nm}(%/年)'] - 100 * IFREE_EXTRA * NOW['QQQM'], 2)
            ifr['label'] = '今（NASDAQ100 を iFreeNEXT の費用で）'
            ent['今_iFreeNEXT'] = ifr
        results[var] = ent

    # 安定性
    main_r1 = results['main']['picks']['R1']['weights']
    stab = {}
    for var in VARIANTS[1:]:
        p = results[var]['picks']['R1']
        stab[var] = None if p is None else round(overlap(main_r1, p['weights']), 2)
    n_ok = sum(1 for v in stab.values() if v is not None and v >= 0.7)
    o_main = results['main']['other15']['pick']
    o_same = sum(1 for var in VARIANTS[1:] if results[var]['other15']['pick'] == o_main)
    corr = np.corrcoef(G1)
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/etf_forward_combo.py', 'prereg': PREREG,
        'question': 'ETFの組み合わせ（1〜4本・10%刻み）を4つの世界で選ぶ。あわせて今の配分の「その他15%」に入れる本',
        'unit': 'ドル建ての幾何年率（費用と外国税を引いた後）。組み合わせの順位は円でも同じ（毎月、どの本も同じドル円の変化が掛かる）。ぶれ・最大下落は A1（2000-09〜2026-09）・ドル建て',
        'candidates': CANDS, 'n_combos': {'1〜4本': int((nk <= MAIN_K).sum()), '1〜5本': int(N)},
        'now_weights(%)': {k: round(v * 100, 2) for k, v in NOW.items()},
        'stability_R1': dict(overlap_with_main=stab, n_ge_0_7=n_ok, of=len(stab), verdict='堅い' if n_ok >= 6 else '前提しだい'),
        'stability_other15': dict(main_pick=o_main, same_in=o_same, of=len(VARIANTS) - 1),
        'post_hoc': {'K4': '事前登録の外（結果を見た後に足した点検）。out/tech_persist.json の『過去10年の1位の業種の次の10年』中央 −4.0%/年（81窓・勝率26%）を、市場の年率は据え置いて Chips に −4.0・残りに +0.96（=4.0×0.193/0.807）とし、次の10年だけ効いてその後は0と置いて20年に薄めた（半分）。各米国ETFは中身の Chips の比重で: '
                            + ' / '.join(f'{c} {100 * chips_adj[i]:+.2f}' for i, c in enumerate(CANDS) if c in chips_share) + '（%/年・米国外と金は0）。Chips は 2016-07→2026-06 の1位（年33.3%）。B の REC（記録の業種）は SMH で −0.24%/年しか引いていない',
                     'K4_SMHのみ': '最初に試した版（SMH だけ B・C で −2.0%/年）。XLK（Chips 55.5%）・QQQM（37%）の半導体に掛けていなかったので、K4 へ直した。両方を残す'},
        'results': results,
        'assets': {c: {'A1': pct(rows[c]['A1']), 'A2': pct(rows[c]['A2']), 'B': pct(rows[c]['B']), 'C': pct(rows[c]['C']),
                       'ぶれA1': pct(rows[c]['vol_A1'], 1), '対数のぶれA1': pct(math.sqrt(s1[i]), 1)} for i, c in enumerate(CANDS)},
        'corr_A1(毎月)': {c: {d: round(float(corr[i, j]), 2) for j, d in enumerate(CANDS)} for i, c in enumerate(CANDS)},
        '⚠': [
            '4つの世界は仮定で、重みは同じと置いた',
            'B・C の組み合わせの数字は、ぶれと相関が 2000-2026 と同じという仮定の上の計算（分散の上乗せ）。実績ではない',
            'A1・A2 は毎月組み直す前提。実際の買い方（売らずに足りない本へ入金）は近いが同じではない',
            'EPI・VIG・VYM・RSP は毎月の値が A1 にそろわないので入らない',
            '個別株の15% はこの外（個別株もテックと半導体に厚い）',
            'iFreeNEXT（つみたて投資枠の NASDAQ100）は QQQM より年約0.345pt 高い',
            '判定・配分には使わない（材料）。配分を変えるかはユーザーの明示指示の領分',
        ],
    }
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {OUT}  組み合わせ {N:,}（1〜4本 {int((nk <= MAIN_K).sum()):,}）')

    def line(d):
        w = ' '.join(f'{k}{v:g}' for k, v in (d['weights'] or {}).items())
        return (f"{d['label']:<6} {w:<34} 平均{d['平均(%/年)']:6.2f} 最悪{d['最悪(%/年)']:6.2f}({d['最悪の世界']}) "
                f"A1{d['A1(%/年)']:6.2f} A2{d['A2(%/年)']:6.2f} B{d['B(%/年)']:6.2f} C{d['C(%/年)']:6.2f} "
                f"ぶれ{d['A1_ぶれ(%/年)']:5.1f} 下落{d['A1_最大下落(%)']:6.1f} 上乗せ{d['B・Cの分散の上乗せ(%/年)']:5.2f} S&P割れなし{d.get('どの世界でもS&P500以上')}")
    m = results['main']
    print(line(m['今']))
    print(line(m['今_iFreeNEXT'] | {'label': '今iFree'}))
    for c, d in m['benchmarks'].items():
        print(line(d))
    for nm in ('R1', 'R2', 'F1', 'F2', 'R3'):
        if m['picks'][nm]:
            print(line(m['picks'][nm]))
    print('今を上回る組み合わせ（平均・最悪とも以上・ぶれ以下）:', m['dominating_now'])
    print('フロンティア（ぶれが今以下）:')
    for d in m['frontier_ぶれが今以下']:
        print(' ', line(d))
    print('フロンティア（制約なし）:')
    for d in m['frontier_制約なし']:
        print(' ', line(d))
    print('その他15%（主）: 推奨', m['other15']['pick'])
    for d in m['other15']['table']:
        print(f"  {d['label']:<6} 平均{d['平均(%/年)']:6.2f} 最悪{d['最悪(%/年)']:6.2f}({d['最悪の世界']}) A1{d['A1(%/年)']:6.2f} A2{d['A2(%/年)']:6.2f} "
              f"B{d['B(%/年)']:6.2f} C{d['C(%/年)']:6.2f} ぶれ{d['A1_ぶれ(%/年)']:5.1f} 下落{d['A1_最大下落(%)']:6.1f} XLKより上:{d['XLKより平均・最悪とも上・ぶれ以下']}{' 参考' if d['参考（その他の区分の外）'] else ''}")
    print('感度:')
    for var in VARIANTS[1:]:
        e = results[var]
        r1 = e['picks']['R1']
        print(f"  {var:<7} R1 {' '.join(f'{k}{v:g}' for k, v in (r1['weights'] if r1 else {}).items()):<30} 重なり{stab[var]}  "
              f"F1 {' '.join(f'{k}{v:g}' for k, v in e['picks']['F1']['weights'].items()):<24} F2 {' '.join(f'{k}{v:g}' for k, v in e['picks']['F2']['weights'].items()):<28} その他15%: {e['other15']['pick']}  今を上回る数 {e['dominating_now']}")
    print(f"R1 の安定性: {n_ok}/{len(stab)} → {doc['stability_R1']['verdict']}／その他15% の同じ本: {o_same}/{len(VARIANTS) - 1}")
    print('K4 の割り引き（%/年）:', {c: round(100 * chips_adj[i], 2) for i, c in enumerate(CANDS) if c in chips_share})
    for var in POST:
        e = results[var]
        print(f'★{VAR_JA[var]}:')
        print(' ', line(e['今']))
        for nm in ('R1', 'R2', 'F1', 'F2', 'R3'):
            if e['picks'][nm]:
                print(' ', line(e['picks'][nm]))
        print('  その他15%:', e['other15']['pick'], ' 今を上回る数', e['dominating_now'])


if __name__ == '__main__':
    main()
