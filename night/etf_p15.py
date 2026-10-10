#!/usr/bin/env python3
"""night/etf_p15.py — 年率15%を効率よく上回る確率が高い組み合わせ（2026-10-10・ユーザー「年率15%を効率よく上回る確率が高い組み合わせは？」）

読むだけ。門・採点・配分には触れない。事前登録 out/etf_p15_prereg.json（3456f35・測る前に固定）どおり。
組み合わせ（21本・1〜4本・10%刻み）と4つの世界の年率は night/etf_forward_combo.py の build() をそのまま使う。

  確率 … 各世界 w の伸び m_w=ln(1+G_w)・ぶれ σ=√(w'Sw)（A1 の窓の毎月の対数リターンの共分散×12）で、毎月の対数リターンを
          N(m/12, σ²/12) と置き、毎月同じ額を240か月積み立てた資産 W が、年率15%で回した場合の資産 K15 以上になる割合
          （＝内部収益率≥15%）。40,000本の道（20,000本＋符号の反転）で m×σ の格子の表を作り、双一次補間。4つの世界の単純平均
  効率 … 同じぶれ（A1 の年率の標準偏差）の上限の中で確率が最大の組み合わせを比べる

出力: out/etf_p15.json
"""
import datetime, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_combo as CB   # noqa: E402

OUT = os.path.join(BASE, 'out', 'etf_p15.json')
PREREG = 'out/etf_p15_prereg.json（3456f35）'
SEED, NPATH = 20261010, 20000
M0, M1, DM = -0.10, 0.45, 0.001
S0, S1_, DS = 0.05, 0.45, 0.001
M_GRID = np.round(np.arange(M0, M1 + DM / 2, DM), 3)
S_GRID = np.round(np.arange(S0, S1_ + DS / 2, DS), 3)
TAUS_MAIN = [0.0, 0.05, 0.10, 0.12, 0.15, 0.18]
CAPS = [0.12, 0.15, 0.18, 0.21, 'now', 0.27, 0.30, None]
SENS = ['S2', 'K4', 'S4_GMO', 'S4_VG', 'K1', 'K2', 'H15', 'H30', 'LUMP', 'T12', 'T18']
SENS_JA = {'main': '主（20年の積立・目標15%）', 'S2': 'A2 を外す', 'K4': '半導体の基礎率で割り引く', 'S4_GMO': 'C を GMO に', 'S4_VG': 'C を Vanguard に',
           'K1': 'B・C で分散の上乗せなし', 'K2': '共分散を A2 の窓から', 'H15': '15年の積立', 'H30': '30年の積立', 'LUMP': '一括で20年',
           'T12': '目標12%', 'T18': '目標18%'}


def dca_tables(H, taus, log=True):
    """{τ: 表(σ×m) の P(内部収益率≥τ)}。同じ乱数を全格子点で使う"""
    T = 12 * H
    rng = np.random.default_rng(SEED)
    Z = rng.standard_normal((NPATH, T)).astype(np.float32)
    Z = np.vstack([Z, -Z])
    RC = np.flip(np.cumsum(np.flip(Z, axis=1), axis=1), axis=1) / np.float32(math.sqrt(12))   # RC[:, t] = Σ_{u≥t} Z_u /√12
    n_t = np.arange(T, 0, -1, dtype=np.float64)                                                 # 月 t に入れたお金が回る月数
    A = np.exp(np.outer(n_t / 12.0, M_GRID)).astype(np.float32)                                # (T, m)
    K = {tau: float(np.sum((1 + tau) ** (np.arange(1, T + 1) / 12.0))) for tau in taus}
    tabs = {tau: np.empty((len(S_GRID), len(M_GRID))) for tau in taus}
    t0 = time.time()
    for i, s in enumerate(S_GRID):
        E = np.exp(np.float32(s) * RC)
        Wt = E @ A                                                                              # (道, m) 240か月後の資産
        for tau in taus:
            tabs[tau][i] = (Wt >= np.float32(K[tau])).mean(axis=0)
        if log and i % 100 == 0:
            print(f'  {H}年の表 σ={s:.3f}（{i + 1}/{len(S_GRID)}・{time.time() - t0:.0f}秒）', flush=True)
    return tabs


def interp(tab, m, s):
    if np.any(m < M0) or np.any(m > M1) or np.any(s < S0) or np.any(s > S1_):
        raise SystemExit(f'格子の外: m {m.min():.3f}〜{m.max():.3f} / σ {s.min():.3f}〜{s.max():.3f}')
    fi = (s - S0) / DS; fj = (m - M0) / DM
    i0 = np.clip(np.floor(fi).astype(np.int64), 0, len(S_GRID) - 2); j0 = np.clip(np.floor(fj).astype(np.int64), 0, len(M_GRID) - 2)
    di = np.clip(fi - i0, 0, 1); dj = np.clip(fj - j0, 0, 1)
    return (tab[i0, j0] * (1 - di) * (1 - dj) + tab[i0 + 1, j0] * di * (1 - dj)
            + tab[i0, j0 + 1] * (1 - di) * dj + tab[i0 + 1, j0 + 1] * di * dj)


def norm_cdf(x):
    """標準正規の累積分布（scipy が無いので math.erf を要素ごとに）"""
    x = np.asarray(x, dtype=np.float64)
    return 0.5 * (1.0 + np.array([math.erf(v / math.sqrt(2)) for v in x.ravel()]).reshape(x.shape))


def hist_success(Wf, G1, adj, T1, months_list=(240, 180), tau=0.15):
    """2000-09〜2026-09 の実績で、転がる窓の積立の内部収益率≥τ の割合（窓の長さごと）"""
    out = {Tw: np.empty(len(Wf)) for Tw in months_list}
    K = {Tw: float(np.sum((1 + tau) ** (np.arange(1, Tw + 1) / 12.0))) for Tw in months_list}
    CH = 20000
    for s in range(0, len(Wf), CH):
        Wc = Wf[s:s + CH]
        r = Wc @ G1 + (Wc @ adj)[:, None] / 12.0
        Lc = np.cumsum(np.log1p(r), axis=1)                          # Lc[:, t] = 月0〜t の累積
        prev = np.hstack([np.zeros((len(Wc), 1)), Lc[:, :-1]])        # 月 t の初めまでの累積
        Pp = np.cumsum(np.exp(-prev), axis=1)                         # Σ_{u≤t} exp(−prev_u)
        Pp0 = np.hstack([np.zeros((len(Wc), 1)), Pp])                 # Pp0[:, t] = Σ_{u<t}
        for Tw in months_list:
            nwin = T1 - Tw + 1
            a = np.arange(nwin); b = a + Tw - 1
            Wend = np.exp(Lc[:, b]) * (Pp0[:, b + 1] - Pp0[:, a])
            out[Tw][s:s + CH] = (Wend >= K[Tw]).mean(axis=1)
    return out


def main():
    t_all = time.time()
    ctx = CB.build(max_k=CB.MAIN_K)
    CANDS = CB.CANDS
    rows, W, Wint, nk, vol1, mdd1 = ctx['rows'], ctx['W'], ctx['Wint'], ctx['nk'], ctx['vol1'], ctx['mdd1']
    grid_bs, base_of, worlds = ctx['grid_bs'], ctx['base_of'], ctx['worlds']
    G1, adj, T1 = ctx['G1'], ctx['adj'], ctx['T1']
    n = len(CANDS)
    print(f'組み合わせ {len(W):,}（{time.time() - t_all:.0f}秒）', flush=True)

    # ── 確率の表 ──
    tabs = {20: dca_tables(20, TAUS_MAIN)}
    tabs[15] = dca_tables(15, [0.05, 0.15])
    tabs[30] = dca_tables(30, [0.05, 0.15])

    # 名前のある組み合わせ（格子の外も含む）
    def wvec(d):
        return np.array([[d.get(c, 0.0) for c in CANDS]])
    named = {
        '今': {'QQQM': 50 / 85, 'XLK': 15 / 85, 'SMH': 20 / 85},
        'S&P500（VOO）': {'VOO': 1.0}, 'NASDAQ100（QQQM）': {'QQQM': 1.0}, '半導体（SMH）': {'SMH': 1.0},
        '前回の主 SMH50/TOPIX20/XLE20/VTV10': {'SMH': .5, 'TOPIX': .2, 'XLE': .2, 'VTV': .1},
        'S&P500並みのぶれ SMH30/XLV30/ITA20/金20': {'SMH': .3, 'XLV': .3, 'ITA': .2, 'GLDM': .2},
        '今のまま その他15%=ITA': {'QQQM': 50 / 85, 'ITA': 15 / 85, 'SMH': 20 / 85},
    }
    nW = np.vstack([wvec(d) for d in named.values()])
    n_bs = base_of(nW)

    def probs(Wf, bs, var):
        """各組み合わせの {P_hi, P5, P10, P0, 世界ごと, σ}。var は SENS か 'main'"""
        cvar = {'S2': 'main', 'H15': 'main', 'H30': 'main', 'LUMP': 'main', 'T12': 'main', 'T18': 'main'}.get(var, var)
        wv = worlds(Wf, bs, cvar)
        sig = np.sqrt(bs['q2'] if var == 'K2' else bs['q1'])
        names = ['A1', 'B', 'C'] if var == 'S2' else ['A1', 'A2', 'B', 'C']
        H = {'H15': 15, 'H30': 30}.get(var, 20)
        tau = {'T12': 0.12, 'T18': 0.18}.get(var, 0.15)
        per = {}
        p_hi, p5, p10, p0 = [], [], [], []
        for nm in names:
            m = np.log1p(wv[nm])
            if var == 'LUMP':
                ph = norm_cdf((m - math.log1p(tau)) * math.sqrt(H) / sig)
                pl = norm_cdf((math.log1p(0.05) - m) * math.sqrt(H) / sig)
                p_hi.append(ph); p5.append(pl)
            else:
                ph = interp(tabs[H][tau], m, sig)
                pl = 1.0 - interp(tabs[H][0.05], m, sig)
                p_hi.append(ph); p5.append(pl)
                if H == 20 and var not in ('T12', 'T18'):
                    p10.append(interp(tabs[20][0.10], m, sig)); p0.append(1.0 - interp(tabs[20][0.0], m, sig))
            per[nm] = ph
        out = dict(P=np.mean(p_hi, axis=0), P5=np.mean(p5, axis=0), per=per, sig=sig, wv=wv, names=names)
        if p10:
            out['P10'] = np.mean(p10, axis=0); out['P0'] = np.mean(p0, axis=0)
        return out

    def pick(P, P5, feas):
        ids = np.where(feas)[0]
        if len(ids) == 0:
            return None
        return int(ids[np.lexsort((vol1[ids], P5[ids], -P[ids]))[0]])

    def wdict(i):
        return {CANDS[j]: int(Wint[i, j]) * 10 for j in np.argsort(-Wint[i].astype(int), kind='stable') if Wint[i, j]}

    def pct(x, d=1):
        return None if x is None else round(float(x) * 100, d)

    def desc_i(pr, i, label, weights, vol, mdd, hist=None):
        d = dict(label=label, weights=weights, **{'確率(%)': pct(pr['P'][i]), '5%未満の確率(%)': pct(pr['P5'][i])})
        if 'P10' in pr:
            d['10%以上の確率(%)'] = pct(pr['P10'][i]); d['元本割れの確率(%)'] = pct(pr['P0'][i])
        d['世界ごとの確率(%)'] = {nm: pct(pr['per'][nm][i]) for nm in pr['names']}
        d['世界ごとの年率(%)'] = {nm: pct(pr['wv'][nm][i], 2) for nm in ('A1', 'A2', 'B', 'C')}
        d['ぶれ(%/年)'] = pct(vol); d['最大下落(%)'] = pct(mdd); d['対数のぶれσ(%)'] = pct(pr['sig'][i])
        if hist is not None:
            d['過去の転がる20年で15%以上(%)'] = pct(hist[240]); d['過去の転がる15年で15%以上(%)'] = pct(hist[180])
        return d

    # ── 過去の成功率（主・参考） ──
    mask4 = nk <= CB.MAIN_K
    t0 = time.time()
    hs = hist_success(W, G1, adj, T1)
    hs_named = hist_success(nW, G1, adj, T1)
    print(f'過去の転がる窓（{time.time() - t0:.0f}秒）', flush=True)

    v_now = float(n_bs['vol'][0])
    v_voo = float(n_bs['vol'][1])
    results = {}
    for var in ['main'] + SENS:
        pr = probs(W, grid_bs, var)
        pn = probs(nW, n_bs, var)
        P, P5 = pr['P'], pr['P5']
        E = {
            'E1': pick(P, P5, mask4 & (vol1 <= v_now)),
            'E0': pick(P, P5, mask4),
            'E2': pick(P, P5, mask4 & (vol1 <= v_voo)),
        }
        ids = np.where(mask4)[0]
        net = P - P5
        E['E3'] = int(ids[np.lexsort((vol1[ids], -P[ids], -net[ids]))[0]])
        ent = dict(ja=SENS_JA[var], picks={}, named={})
        for nm, i in E.items():
            ent['picks'][nm] = None if i is None else desc_i(pr, i, nm, wdict(i), vol1[i], mdd1[i],
                                                               {240: hs[240][i], 180: hs[180][i]} if var == 'main' else None)
        for j, (nm, d) in enumerate(named.items()):
            ent['named'][nm] = desc_i(pn, j, nm, {k: round(v * 100, 1) for k, v in d.items()}, n_bs['vol'][j], n_bs['mdd'][j],
                                      {240: hs_named[240][j], 180: hs_named[180][j]} if var == 'main' else None)
        ent['今を確率で上回りぶれが同じ以下の数'] = int((mask4 & (P > pn['P'][0]) & (vol1 <= v_now)).sum())
        if var == 'main':
            fr = []
            for cap in CAPS:
                c = v_now if cap == 'now' else cap
                feas = mask4 if c is None else (mask4 & (vol1 <= c))
                i = pick(P, P5, feas)
                d = desc_i(pr, i, f"ぶれ≤{'今' if cap == 'now' else ('なし' if cap is None else f'{100 * cap:g}%')}", wdict(i), vol1[i], mdd1[i], {240: hs[240][i], 180: hs[180][i]})
                d['上限(%)'] = None if c is None else round(100 * c, 1)
                fr.append(d)
            ent['frontier'] = fr
            ih = int(ids[np.lexsort((vol1[ids], -hs[180][ids], -hs[240][ids]))[0]])
            ent['H_best'] = desc_i(pr, ih, 'H_best', wdict(ih), vol1[ih], mdd1[ih], {240: hs[240][ih], 180: hs[180][ih]})
            ent['過去の転がる20年で100%の組み合わせの数'] = int((mask4 & (hs[240] >= 1.0)).sum())
            ent['P15の分布'] = {q: pct(np.quantile(P[mask4], q / 100)) for q in (0, 10, 50, 90, 100)}
        results[var] = ent
        print(f'{var} 済（{time.time() - t_all:.0f}秒）', flush=True)

    def overlap(wa, wb):
        return sum(min(wa.get(k, 0), wb.get(k, 0)) for k in set(wa) | set(wb)) / 100.0
    main_e1 = results['main']['picks']['E1']['weights']
    stab = {v: round(overlap(main_e1, results[v]['picks']['E1']['weights']), 2) for v in SENS}
    n_ok = sum(1 for v in stab.values() if v >= 0.7)

    # 自己検問: 一括の表を使わない閉じた式と、積立の表の向き（m が大きいほど・m<目標では σ が大きいほど確率が上がる）
    chk = {}
    t20 = tabs[20][0.15]
    chk['m方向に単調'] = bool(np.all(np.diff(t20, axis=1) >= -0.002))
    j_lo = int(np.argmin(np.abs(M_GRID - 0.07)))
    chk['m=7%ではσが大きいほど確率が上がる'] = bool(np.all(np.diff(t20[:, j_lo]) >= -0.002))
    j_hi = int(np.argmin(np.abs(M_GRID - 0.25)))
    chk['m=25%ではσが大きいほど確率が下がる'] = bool(np.all(np.diff(t20[:, j_hi]) <= 0.002))
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/etf_p15.py', 'prereg': PREREG,
        'question': '年率15%を効率よく上回る確率が高い組み合わせ（毎月の積立で20年後の内部収益率≥15% の確率・4つの世界の平均・同じぶれで比べる）',
        'model': f'各世界の伸び m=ln(1+年率)・σ=√(w\'Sw)・毎月の対数リターン N(m/12, σ²/12)・{2 * NPATH:,}本の道（種 {SEED}）・m {M0}〜{M1} / σ {S0}〜{S1_} の 0.001 刻みの表を双一次補間',
        'now_vol(%)': pct(v_now), 'voo_vol(%)': pct(v_voo),
        'stability_E1': dict(overlap_with_main=stab, n_ge_0_7=n_ok, of=len(SENS), verdict='堅い' if n_ok >= 6 else '前提しだい'),
        'self_checks': chk,
        'results': results,
        '⚠': [
            '4つの世界は仮定で重みは同じ。確率はこの仮定の上の数字',
            '毎月のリターンを独立な正規分布と置いた（実際は暴落が固まって来る）。ぶれと相関は 2000-2026 と同じと置いた',
            '過去の転がる窓の成功率は一つの歴史（2000-2026・テックの時代）で、窓は大きく重なる。未来の確率ではない',
            '個別株の15% はこの外。判定・配分には使わない（材料）',
        ],
    }
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {OUT}（{time.time() - t_all:.0f}秒）')

    def line(d):
        w = ' '.join(f'{k}{v:g}' for k, v in (d['weights'] or {}).items())
        pw = ' '.join(f"{k}{v:5.1f}" for k, v in d['世界ごとの確率(%)'].items())
        h = f" 過去20年{d.get('過去の転がる20年で15%以上(%)')}・15年{d.get('過去の転がる15年で15%以上(%)')}" if '過去の転がる20年で15%以上(%)' in d else ''
        return (f"{d['label'][:22]:<22} {w:<30} 確率{d['確率(%)']:5.1f} 5%未満{d['5%未満の確率(%)']:5.1f} [{pw}] ぶれ{d['ぶれ(%/年)']:5.1f} 下落{d['最大下落(%)']:6.1f}{h}")
    m = results['main']
    print('■ 名前のある組み合わせ（主）')
    for d in m['named'].values():
        print(' ', line(d))
    print('■ 選んだ組み合わせ（主）')
    for d in m['picks'].values():
        print(' ', line(d))
    print('  H_best', line(m['H_best']))
    print('■ ぶれの上限ごと（主）')
    for d in m['frontier']:
        print(' ', line(d))
    print('  P15 の分布（全組み合わせ）:', m['P15の分布'], ' 過去の転がる20年で100%:', m['過去の転がる20年で100%の組み合わせの数'], ' 今を上回る数:', m['今を確率で上回りぶれが同じ以下の数'])
    print('■ 感度')
    for v in SENS:
        e = results[v]
        e1 = e['picks']['E1']; e0 = e['picks']['E0']; nw = e['named']['今']
        print(f"  {v:<7} 今 確率{nw['確率(%)']:5.1f} | E1 {' '.join(f'{k}{x:g}' for k, x in e1['weights'].items()):<28} 確率{e1['確率(%)']:5.1f} 重なり{stab[v]} | E0 {' '.join(f'{k}{x:g}' for k, x in e0['weights'].items()):<22} 確率{e0['確率(%)']:5.1f}")
    print(f"E1 の安定性: {n_ok}/{len(SENS)} → {doc['stability_E1']['verdict']}　自己検問: {chk}")


if __name__ == '__main__':
    main()
