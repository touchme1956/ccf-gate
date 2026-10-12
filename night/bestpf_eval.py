#!/usr/bin/env python3
"""night/bestpf_eval.py — 過去・現在・未来から、株式だけで「最も上がりやすい」ポートフォリオを選ぶ（2026-10-12）

読むだけ。門・採点・配分（portfolio.json）には触れない。事前登録 out/bestpf_prereg.json（7c4b672・測る前に固定）の final_selection どおり。

  資産     … 株の ETF だけ（GLDM は外す）。etf_forward_combo の20本＋ R7（night/bestpf_ext.py）が測れた本。
             A1（2000-09〜2026-09）の毎月の値がそろう本だけ（そろわない本は名指しして外す）。
  世界     … A1・A2・B・C（night/etf_forward_rank.py と同じ）＋ D（R3: 2026年の長期予想の中央値・out/bestpf_cma_2026.json）。
             重み π は R8（out/bestpf_calibration.json）の主。
  確率     … etf_p15 と同じ: 各世界の伸び m=ln(1+年率)・σ=√(w'Sw)（A1 の窓）・毎月 N(m/12, σ²/12) の20年の積立の内部収益率の表。
  選び方   … ★2026-10-12 ユーザー明示指示「15％以上を、狙う。」で事前登録を改めた（amendment_2026_10_12・本番の前）:
             P15π（内部収益率≥15% の確率の π 加重）が最大。0.5pt 以内は P5π（5%未満の確率）が低いほう→ぶれが小さいほう。
             旧の主（P10π が最大・0.5pt 以内は P15π）も並べて出す。
             制約: ETF 側 2〜5本・10%刻み・1本 60%以下・最悪の世界 ≥ S&P500（VOO）の最悪の世界。
  頑健さ   … 感度（世界を1つずつ外す・K4・K2・π の別の作り方・C を GMO/Vanguard に・π を等しく）で、主の1位が
             半分以上の感度で上位1%に残らなければ、全感度の平均順位が最良の案を採る。

出力: out/bestpf_eval.json
"""
import datetime, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R      # noqa: E402
import etf_forward_combo as CB    # noqa: E402
import etf_p15 as P               # noqa: E402
import mw_common as M             # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_eval.json')
PREREG = 'out/bestpf_prereg.json（7c4b672）'
WORLDS = ['A1', 'A2', 'B', 'C', 'D']
H = 20
CAP = 6            # 1本 60%以下（10%刻みの単位）
KMIN, KMAX = 2, 5
TIE = 0.005        # P10π の 0.5pt 以内は同点
NOW_ETF = {'QQQM': 50 / 85, 'ITA': 15 / 85, 'SMH': 20 / 85}     # 今の目標の ETF 側（その他15%＝ITA・2026-10-10〜）
EXCLUDE = {'GLDM'}                                              # 株だけ
DRY = '--dry' in sys.argv                                       # 試運転（R3・R8 の出力が無ければ D=C・π=等しく。書き出さない）
if '--kmax' in sys.argv:
    KMAX = int(sys.argv[sys.argv.index('--kmax') + 1])


# ───────────────────────── 入力 ─────────────────────────
def rank_result():
    """R7 の拡張があればそれを、無ければ etf_forward_rank の main(write=False)"""
    if '--base' in sys.argv:
        return R.main(write=False), 'night/etf_forward_rank.py の main(write=False)（--base）'
    try:
        import bestpf_ext as X   # noqa: E402
        if hasattr(X, 'rank_result'):
            return X.rank_result(), 'night/bestpf_ext.py の rank_result()'
    except ImportError:
        pass
    return R.main(write=False), 'night/etf_forward_rank.py の main(write=False)（拡張なし）'


def load_D(rows, assets):
    """R3 の D の世界（各資産の正味＝費用と外国税を引いた後・小数）。取れない資産は None → C で代える（事前登録）"""
    p = os.path.join(BASE, 'out', 'bestpf_cma_2026.json')
    if DRY and not os.path.exists(p):
        return {c: rows[c]['C'] for c in assets}, {c: '試運転: C で代用' for c in assets}, {}
    j = json.load(open(p))
    d = j.get('D_net_by_asset') or {}
    out, src = {}, {}
    for c in assets:
        v = d.get(c)
        if v is None:
            out[c] = rows[c]['C']; src[c] = 'C で代用（D が無い）'
        else:
            out[c] = float(v); src[c] = 'D'
    return out, src, j


def load_pi():
    p = os.path.join(BASE, 'out', 'bestpf_calibration.json')
    if DRY and not os.path.exists(p):
        return {w: 1 / 5 for w in WORLDS}, {}, {}
    j = json.load(open(p))
    main = j.get('pi_main')
    sens = j.get('pi_sens') or {}
    if not main:
        main = {w: 1 / 5 for w in WORLDS}
    return {w: float(main.get(w, 0.0)) for w in WORLDS}, {k: {w: float(v.get(w, 0.0)) for w in WORLDS} for k, v in sens.items() if v}, j


# ───────────────────────── 組み合わせ ─────────────────────────
def compositions_capped(k):
    c = CB.compositions(10, k)
    return c[(c <= CAP).all(axis=1)]


def build_grid(G1, G2, S1, S2, n):
    import itertools
    T1, T2 = G1.shape[1], G2.shape[1]
    blocks = []
    for k in range(KMIN, KMAX + 1):
        comps = compositions_capped(k)
        subs = np.array(list(itertools.combinations(range(n), k)), dtype=np.int64)
        blocks.append((k, comps, subs))
    N = sum(len(c) * len(s) for _, c, s in blocks)
    Wint = np.zeros((N, n), dtype=np.uint8)
    nk = np.zeros(N, dtype=np.int8)
    a1g = np.empty(N); a2g = np.empty(N); vol1 = np.empty(N); mdd1 = np.empty(N); q1 = np.empty(N); q2 = np.empty(N)
    pos = 0
    t0 = time.time()
    for k, comps, subs in blocks:
        cw = comps / 10.0
        Ck = len(comps)
        step = max(1, 30000 // Ck)
        for b0 in range(0, len(subs), step):
            idx = subs[b0:b0 + step]
            B = len(idx)
            Rp1 = np.matmul(cw[None, :, :], G1[idx])
            g, v, d = CB.path_stats(Rp1, T1)
            Rp2 = np.matmul(cw[None, :, :], G2[idx])
            g2 = np.expm1(np.log1p(Rp2).sum(axis=-1) * 12 / T2)
            S1s = S1[idx[:, :, None], idx[:, None, :]]
            S2s = S2[idx[:, :, None], idx[:, None, :]]
            sl = slice(pos, pos + B * Ck)
            a1g[sl] = g.ravel(); vol1[sl] = v.ravel(); mdd1[sl] = d.ravel(); a2g[sl] = g2.ravel()
            q1[sl] = np.einsum('ck,bkl,cl->bc', cw, S1s, cw).ravel(); q2[sl] = np.einsum('ck,bkl,cl->bc', cw, S2s, cw).ravel()
            nk[sl] = k
            rr = np.arange(pos, pos + B * Ck)
            for jj in range(k):
                Wint[rr, np.repeat(idx[:, jj], Ck)] = np.tile(comps[:, jj], B)
            pos += B * Ck
        print(f'  {k}本 済 {pos:,}/{N:,}（{time.time() - t0:.0f}秒）', flush=True)
    assert pos == N
    assert (Wint.sum(axis=1) == 10).all()
    return dict(Wint=Wint, nk=nk, a1g=a1g, a2g=a2g, vol=vol1, mdd=mdd1, q1=q1, q2=q2, N=N)


def wdot(Wint, x, chunk=1_000_000):
    """Wint（10分の1単位の整数）× x を、大きな float の行列を作らずに"""
    out = np.empty(Wint.shape[0])
    xf = np.asarray(x, dtype=np.float64)
    for s in range(0, Wint.shape[0], chunk):
        out[s:s + chunk] = Wint[s:s + chunk].astype(np.float64) @ xf / 10.0
    return out


def main():
    t_all = time.time()
    res, rsrc = rank_result()
    rows, chains = res['rows'], res['chains']
    k1, k2 = R.months(*R.A1), R.months(*R.A2)
    order = [c for c in rows]                     # R.C の並び（拡張は後ろ）
    dropped = {}
    assets = []
    for c in order:
        if c in EXCLUDE:
            dropped[c] = '株でない（金）'; continue
        miss = [m for m in k1 if m not in chains.get(c, {})]
        if miss:
            dropped[c] = f'A1 の毎月の値がそろわない（欠け {len(miss)} か月・最初 {miss[0]}）'; continue
        assets.append(c)
    n = len(assets)
    print('資産', n, assets, '\n外した', dropped, flush=True)

    G1 = np.array([[chains[c][m] for m in k1] for c in assets])
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    L1, L2 = np.log1p(G1), np.log1p(G2)
    S1 = np.cov(L1, bias=True) * 12; S2 = np.cov(L2, bias=True) * 12
    s1, s2 = np.diag(S1).copy(), np.diag(S2).copy()
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    gB = np.array([rows[c]['B'] for c in assets])
    gC = np.array([rows[c]['C'] for c in assets])
    gC_gmo = np.array([rows[c]['_c_gmo'] for c in assets])
    gC_vg = np.array([rows[c]['_c_vg'] for c in assets])
    Dmap, Dsrc, Dj = load_D(rows, assets)
    gD = np.array([Dmap[c] for c in assets])
    _dl = ((Dj.get('sensitivity_D_net_by_asset') or {}).get('S_no5y_fidi_arith') or {}) if Dj else {}
    gD_low = np.array([float(_dl[c]) if _dl.get(c) is not None else Dmap[c] for c in assets])   # 事後の参考: R3 の下側の読み方
    pi_main, pi_sens, Pj = load_pi()
    print('π 主', pi_main, '\nπ 感度', pi_sens, flush=True)

    # K4（半導体の基礎率）: etf_forward_combo と同じ作り
    chips_share = {}
    for c in assets:
        if c == 'VOO':
            chips_share[c] = CB.CHIPS_MKT
        elif (R.C.get(c) or {}).get('us'):
            chips_share[c] = float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    chips_adj = np.array([((-CB.CHIPS_GAP * chips_share[c] + rest * (1 - chips_share[c])) / 2) if c in chips_share else 0.0 for c in assets])

    print('組み合わせを作る', flush=True)
    g = build_grid(G1, G2, S1, S2, n)
    Wint, N = g['Wint'], g['N']

    # 名前のある組み合わせ
    named = {'今（NASDAQ100 50・その他15=ITA・SMH 20 の ETF 側）': NOW_ETF, 'S&P500（VOO）': {'VOO': 1.0}, '全世界株（VT）': {'VT': 1.0},
             'NASDAQ100（QQQM）': {'QQQM': 1.0}, '前回の確率最大 SMH60/ITA40': {'SMH': .6, 'ITA': .4}}
    panel_names = set()
    panel_p = os.path.join(BASE, 'out', 'bestpf_panel.json')
    if os.path.exists(panel_p):
        for p in json.load(open(panel_p)).get('candidates', []):
            w = {k: v for k, v in p['weights'].items() if v}
            bad = [k for k in w if k not in assets]
            if bad:
                print('設計の案で測れない本', p['name'], bad); continue
            tot = sum(w.values())
            named[p['name']] = {k: v / tot for k, v in w.items()}
            if not p.get('posthoc'):
                panel_names.add(p['name'])
    NW = np.array([[named[nm].get(c, 0.0) for c in assets] for nm in named])
    Rn1, Rn2 = NW @ G1, NW @ G2
    ng, nv, nd = CB.path_stats(Rn1, len(k1))
    n_bs = dict(a1g=ng, a2g=np.expm1(np.log1p(Rn2).sum(axis=-1) * 12 / len(k2)), vol=nv, mdd=nd,
                q1=np.einsum('mi,ij,mj->m', NW, S1, NW), q2=np.einsum('mi,ij,mj->m', NW, S2, NW))

    # ── 世界の年率（var ごと）──
    def world_vals(dot, bs, var):
        """dot(x) = 重み×x。bs は a1g/a2g/q1/q2 を持つ。戻り値 {世界: 年率}"""
        A1 = bs['a1g'] + dot(adj); A2 = bs['a2g'] + dot(adj)
        sv, qv = (s2, bs['q2']) if var == 'K2' else (s1, bs['q1'])
        bonus = 0.5 * (dot(sv) - qv)
        b, c, dd = gB, gC, gD
        if var == 'K4':
            b, c, dd = gB + chips_adj, gC + chips_adj, gD + chips_adj
        if var == 'post_K4_full':
            b, c, dd = gB + 2 * chips_adj, gC + 2 * chips_adj, gD + 2 * chips_adj
        if var == 'post_D_low':
            dd = gD_low
        if var == 'C_GMO':
            c = gC_gmo
        if var == 'C_VG':
            c = gC_vg
        Bw = np.expm1(dot(np.log1p(b)) + bonus)
        Cw = np.expm1(dot(np.log1p(c)) + bonus)
        Dw = np.expm1(dot(np.log1p(dd)) + bonus)
        return dict(A1=A1, A2=A2, B=Bw, C=Cw, D=Dw)

    def pi_of(var):
        if var.startswith('loo_'):
            w = var[4:]
            p = {k: (0.0 if k == w else v) for k, v in pi_main.items()}
            s = sum(p.values()); return {k: v / s for k, v in p.items()}
        if var.startswith('pi_'):
            return pi_sens.get(var[3:]) or None
        if var == 'equal_pi':
            return {w: 1 / 5 for w in WORLDS}
        return pi_main

    print('確率の表', flush=True)
    tabs = P.dca_tables(H, [0.0, 0.05, 0.10, 0.15], log=False)

    def probs(wv, sig, pi):
        """π 加重の確率（P10・P15・P5〔5%未満〕・P0〔元本割れ〕）と最悪の世界"""
        out = {k: np.zeros_like(sig) for k in ('P10', 'P15', 'P5', 'P0')}
        for w in WORLDS:
            if pi.get(w, 0) <= 0:
                continue
            m = np.log1p(np.clip(wv[w], -0.095, 0.56))
            out['P10'] += pi[w] * P.interp(tabs[0.10], m, sig)
            out['P15'] += pi[w] * P.interp(tabs[0.15], m, sig)
            out['P5'] += pi[w] * (1 - P.interp(tabs[0.05], m, sig))
            out['P0'] += pi[w] * (1 - P.interp(tabs[0.0], m, sig))
        live = [w for w in WORLDS if pi.get(w, 0) > 0]
        out['worst'] = np.min(np.vstack([wv[w] for w in live]), axis=0)
        out['mean_pi'] = sum(pi[w] * wv[w] for w in live)
        return out

    gdot = lambda x: wdot(Wint, x)          # noqa: E731
    ndot = lambda x: NW @ x                 # noqa: E731
    vi = assets.index('VOO')
    e_voo = np.zeros(n); e_voo[vi] = 1.0
    voo_bs = dict(a1g=np.array([CB.path_stats(G1[vi][None, :], len(k1))[0][0]]), a2g=np.array([np.expm1(np.log1p(G2[vi]).sum() * 12 / len(k2))]),
                  q1=np.array([S1[vi, vi]]), q2=np.array([S2[vi, vi]]))
    vdot = lambda x: np.array([float(e_voo @ x)])   # noqa: E731

    SENS = ['loo_A1', 'loo_A2', 'loo_B', 'loo_C', 'loo_D', 'K4', 'K2', 'C_GMO', 'C_VG', 'equal_pi'] + [f'pi_{k}' for k in pi_sens]
    POST = ['post_K4_full', 'post_D_low']      # 事後の参考（頑健さの規則には数えない）: 半導体の基礎率を薄めずに全部／R3 の D の下側
    results = {}
    rank_sum = np.zeros(N); rank_cnt = 0
    main_pick = None
    for var in ['main'] + SENS + POST:
        pi = pi_of(var)
        if pi is None:
            continue
        t0 = time.time()
        sigq = g['q2'] if var == 'K2' else g['q1']
        wv = world_vals(gdot, g, var)
        pr = probs(wv, np.sqrt(sigq), pi)
        vv = world_vals(vdot, voo_bs, var)
        pv = probs(vv, np.sqrt(voo_bs['q2'] if var == 'K2' else voo_bs['q1']), pi)
        feas = pr['worst'] >= float(pv['worst'][0]) - 1e-12
        key = np.where(feas, pr['P15'], -1.0)
        best = float(key.max())
        near = np.where(feas & (pr['P15'] >= best - TIE))[0]
        i_best = int(near[np.lexsort((g['vol'][near], pr['P5'][near]))[0]])
        k10 = np.where(feas, pr['P10'], -1.0)
        near10 = np.where(feas & (pr['P10'] >= float(k10.max()) - TIE))[0]
        i_p10 = int(near10[np.argmax(pr['P15'][near10])])
        i_nocap = None
        # 順位（大きいほど良い・実行可能でないものは最下位）
        rk = np.empty(N); o = np.argsort(-key, kind='stable'); rk[o] = np.arange(N)
        ent = dict(pi=pi, n_feasible=int(feas.sum()), voo_worst=float(pv['worst'][0]), pick=int(i_best),
                   pick_P10=float(pr['P10'][i_best]), pick_P15=float(pr['P15'][i_best]), pick_P10_old_rule=int(i_p10))
        if var == 'main':
            main_pick = i_best
            main_p10 = i_p10
            main_pr, main_wv, main_feas = pr, wv, feas
        elif var in POST:
            nf = max(int(feas.sum()), 1)
            ent['main_pick_rank_pct'] = float(100 * rk[main_pick] / nf)
            ent['main_pick_in_top1pct'] = bool(rk[main_pick] < 0.01 * nf)
            ent['post_hoc'] = True
            ent['pick_weights'] = {assets[j]: int(Wint[i_best, j]) * 10 for j in range(n) if Wint[i_best, j]}
        else:
            nf = max(int(feas.sum()), 1)
            ent['main_pick_rank_pct'] = float(100 * rk[main_pick] / nf)
            ent['main_pick_in_top1pct'] = bool(rk[main_pick] < 0.01 * nf)
            rank_sum += rk; rank_cnt += 1
        results[var] = ent
        print(f'{var:<10} 実行可能 {feas.sum():,}  1位 P15π {100 * pr["P15"][i_best]:.1f}%（{time.time() - t0:.0f}秒）', flush=True)

    n_top = sum(1 for v in results if v != 'main' and not results[v].get('post_hoc') and results[v].get('main_pick_in_top1pct'))
    n_sens = sum(1 for v in results if v != 'main' and not results[v].get('post_hoc'))
    for v in results:
        if v != 'main' and 'pick_weights' not in results[v]:
            i = results[v]['pick']
            results[v]['pick_weights'] = {assets[j]: int(Wint[i, j]) * 10 for j in range(n) if Wint[i, j]}
    robust_ok = n_top >= n_sens / 2
    avg_rank = np.where(main_feas, rank_sum / max(rank_cnt, 1), np.inf)
    i_robust = int(np.argmin(avg_rank))
    final_i = main_pick if robust_ok else i_robust

    def wdict_i(i):
        return {assets[j]: int(Wint[i, j]) * 10 for j in np.argsort(-Wint[i].astype(int), kind='stable') if Wint[i, j]}

    # ── 説明（選んだ案・名前のある案）──
    sim = simulate_tables()

    def describe(weights_vec, bs1, label, pi=pi_main):
        """weights_vec: (n,) の比。bs1: a1g,a2g,vol,mdd,q1,q2 の1行"""
        d1 = lambda x: np.array([float(weights_vec @ x)])   # noqa: E731
        wv = world_vals(d1, {k: np.array([v]) for k, v in bs1.items()}, 'main')
        sig = math.sqrt(bs1['q1'])
        pr = probs(wv, np.array([sig]), pi)
        per = {w: dict(年率=round(100 * float(wv[w][0]), 2),
                       P10=round(100 * float(P.interp(tabs[0.10], np.log1p(wv[w]), np.array([sig]))[0]), 1),
                       P15=round(100 * float(P.interp(tabs[0.15], np.log1p(wv[w]), np.array([sig]))[0]), 1)) for w in WORLDS}
        q = irr_quantiles(sim, {w: math.log1p(float(wv[w][0])) for w in WORLDS}, sig, pi)
        beat = beat_voo(weights_vec, wv, pi)
        hs = P.hist_success(weights_vec[None, :], G1, adj, len(k1), tau=0.15)
        hs10 = P.hist_success(weights_vec[None, :], G1, adj, len(k1), tau=0.10)
        return {'label': label, 'weights': {assets[j]: round(100 * float(weights_vec[j]), 1) for j in np.argsort(-weights_vec) if weights_vec[j] > 1e-9},
                'P10π': round(100 * float(pr['P10'][0]), 1), 'P15π': round(100 * float(pr['P15'][0]), 1),
                'P5π（5%未満）': round(100 * float(pr['P5'][0]), 1), 'P0π（元本割れ）': round(100 * float(pr['P0'][0]), 1),
                'π加重の年率': round(100 * float(pr['mean_pi'][0]), 2), '最悪の世界': round(100 * float(pr['worst'][0]), 2),
                '世界ごと': per, '積立20年の内部収益率': q, 'S&P500に勝つ確率': beat,
                'ぶれ': round(100 * bs1['vol'], 1), '最大下落': round(100 * bs1['mdd'], 1),
                '過去の転がる20年で15%以上': round(100 * float(hs[240][0]), 1), '過去の転がる15年で15%以上': round(100 * float(hs[180][0]), 1),
                '過去の転がる20年で10%以上': round(100 * float(hs10[240][0]), 1), '過去の転がる15年で10%以上': round(100 * float(hs10[180][0]), 1)}

    def beat_voo(wvec, wv, pi):
        """同じ世界で、毎月の対数リターンを2変量正規（共分散は A1）と置き、20年の積立の終わりの資産が VOO より多い確率"""
        rng = np.random.default_rng(20261012)
        T = 12 * H
        e = np.zeros(n); e[vi] = 1.0
        a, b = wvec, e
        Sab = np.array([[a @ S1 @ a, a @ S1 @ b], [a @ S1 @ b, b @ S1 @ b]])
        Lc = np.linalg.cholesky(Sab / 12 + 1e-12 * np.eye(2))
        Z = rng.standard_normal((20000, T, 2)) @ Lc.T
        out = {}
        tot = 0.0
        for w in WORLDS:
            mp = math.log1p(float(wv[w][0])) / 12
            vworld = {'A1': rows['VOO']['A1'], 'A2': rows['VOO']['A2'], 'B': rows['VOO']['B'], 'C': rows['VOO']['C'], 'D': Dmap['VOO']}[w]
            mv = math.log1p(vworld) / 12
            lp = np.cumsum((mp + Z[:, :, 0])[:, ::-1], axis=1)[:, ::-1]
            lv = np.cumsum((mv + Z[:, :, 1])[:, ::-1], axis=1)[:, ::-1]
            wp = np.exp(lp).sum(axis=1); wvv = np.exp(lv).sum(axis=1)
            pw = float((wp > wvv).mean())
            out[w] = round(100 * pw, 1)
            tot += pi.get(w, 0) * pw
        out['π加重'] = round(100 * tot, 1)
        return out

    final_vec = Wint[final_i].astype(np.float64) / 10.0
    rowbs = lambda i: dict(a1g=float(g['a1g'][i]), a2g=float(g['a2g'][i]), vol=float(g['vol'][i]), mdd=float(g['mdd'][i]), q1=float(g['q1'][i]), q2=float(g['q2'][i]))   # noqa: E731
    picks = {'最終（事前登録の規則）': describe(final_vec, rowbs(final_i), '最終'),
             '主の1位': describe(Wint[main_pick].astype(np.float64) / 10, rowbs(main_pick), '主の1位'),
             '平均順位の1位（頑健）': describe(Wint[i_robust].astype(np.float64) / 10, rowbs(i_robust), '平均順位の1位'),
             '旧の主（P10π が最大）': describe(Wint[main_p10].astype(np.float64) / 10, rowbs(main_p10), '旧の主 P10π')}
    # 参考: 1本の上限なし（単体を含む）で P15π が最大の単体（選択には使わない）
    single = {}
    for j, c in enumerate(assets):
        e = np.zeros(n); e[j] = 1.0
        bs1 = dict(a1g=float(CB.path_stats(G1[j][None, :], len(k1))[0][0]), a2g=float(np.expm1(np.log1p(G2[j]).sum() * 12 / len(k2))),
                   vol=float(rows[c]['vol_A1']), mdd=float(rows[c]['maxdd_A1']), q1=float(S1[j, j]), q2=float(S2[j, j]))
        single[c] = describe(e, bs1, f'単体 {c}')
    best_single = max(single, key=lambda c: single[c]['P15π'])
    named_out = {}
    for j, nm in enumerate(named):
        named_out[nm] = describe(NW[j], dict(a1g=float(n_bs['a1g'][j]), a2g=float(n_bs['a2g'][j]), vol=float(n_bs['vol'][j]), mdd=float(n_bs['mdd'][j]),
                                             q1=float(n_bs['q1'][j]), q2=float(n_bs['q2'][j])), nm)
    # 設計役の案（事前登録の候補）も同じ規則に入れる: 実行可能（最悪の世界 ≥ VOO・1本 60%以下・8本まで）で、
    # P15π が全体の最大から 0.5pt 以内なら、5%未満の確率 → ぶれ の順で比べる
    voo_worst = results['main']['voo_worst']
    pool = [('grid', final_i, picks['最終（事前登録の規則）'])]
    for nm in panel_names:
        d = named_out[nm]
        ok = d['最悪の世界'] / 100 >= voo_worst - 1e-12 and max(d['weights'].values()) <= 60.0 + 1e-9 and len(d['weights']) <= 8
        if ok:
            pool.append(('panel', nm, d))
    best15 = max(x[2]['P15π'] for x in pool)
    near = [x for x in pool if x[2]['P15π'] >= best15 - 100 * TIE - 1e-9]
    near.sort(key=lambda x: (x[2]['P5π（5%未満）'], x[2]['ぶれ']))
    final_with_panel = dict(source=near[0][0], name=('グリッド' if near[0][0] == 'grid' else near[0][1]), weights=near[0][2]['weights'],
                            P15π=near[0][2]['P15π'], P5=near[0][2]['P5π（5%未満）'],
                            note='P15π は丸め（0.1pt）で比べる。設計役の案は5%刻み・8本まで')
    print('設計役の案を入れた最終:', final_with_panel)
    # 上位20（主）
    keyM = np.where(main_feas, main_pr['P15'], -1.0)
    top = np.argsort(-keyM)[:20]
    top20 = [dict(weights=wdict_i(int(i)), P10π=round(100 * float(main_pr['P10'][i]), 2), P15π=round(100 * float(main_pr['P15'][i]), 2),
                  π加重の年率=round(100 * float(main_pr['mean_pi'][i]), 2), 最悪の世界=round(100 * float(main_pr['worst'][i]), 2),
                  ぶれ=round(100 * float(g['vol'][i]), 1), 最大下落=round(100 * float(g['mdd'][i]), 1), 平均順位=round(float(avg_rank[i]), 0)) for i in top]
    # 本ごとの出現（上位1000）
    top1000 = np.argsort(-keyM)[:1000]
    freq = {assets[j]: round(float((Wint[top1000, j] > 0).mean()) * 100, 1) for j in range(n)}
    avgw = {assets[j]: round(float(Wint[top1000, j].mean()) * 10, 1) for j in range(n)}
    corr = np.corrcoef(G1)
    doc = dict(
        generated=datetime.date.today().isoformat(), tool='night/bestpf_eval.py', prereg=PREREG, rank_source=rsrc,
        assets=assets, dropped=dropped, n_combos=int(N),
        D_source=Dsrc, D_json_note=Dj.get('note') or Dj.get('summary_ja'), pi_main=pi_main, pi_sens=pi_sens,
        per_asset={c: dict(A1=round(100 * rows[c]['A1'], 2), A2=round(100 * rows[c]['A2'], 2), B=round(100 * rows[c]['B'], 2), C=round(100 * rows[c]['C'], 2),
                           D=round(100 * Dmap[c], 2), K4_adj=round(100 * float(chips_adj[i]), 2), vol_A1=round(100 * math.sqrt(S1[i, i]), 1))
                   for i, c in enumerate(assets)},
        robustness=dict(n_sens=n_sens, main_pick_in_top1pct=n_top, rule='半分以上の感度で上位1%（P15π の順位）に残れば主の1位、残らなければ平均順位の1位', main_kept=bool(robust_ok)),
        sens=results, picks=picks, named=named_out, top20_main=top20, final_with_panel=final_with_panel,
        panel_candidates=sorted(panel_names),
        single_assets={c: {k: single[c][k] for k in ('P15π', 'P10π', 'π加重の年率', '最悪の世界', 'ぶれ', '最大下落')} for c in single},
        best_single_uncapped=dict(asset=best_single, **{k: single[best_single][k] for k in ('P15π', 'P10π', 'π加重の年率', '最悪の世界', 'ぶれ', '最大下落')}),
        objective='P15π（ユーザー明示指示「15％以上を、狙う。」・事前登録の amendment_2026_10_12）',
        top1000_presence_pct=dict(sorted(freq.items(), key=lambda kv: -kv[1])), top1000_avg_weight_pct=dict(sorted(avgw.items(), key=lambda kv: -kv[1])),
        corr_A1={c: {d: round(float(corr[i, j]), 2) for j, d in enumerate(assets)} for i, c in enumerate(assets)},
        warn=['世界の数字は仮定。確率は「毎月のリターンが独立な正規分布・ぶれと相関は 2000-2026 と同じ」の上の数字',
              '過去の転がる窓は一つの歴史（2000-2026）で窓は大きく重なる',
              '個別株15%はこの外（ETF 側だけを測る）。判定・配分には使わない（材料）'],
    )
    if not DRY:
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {OUT if not DRY else "（試運転・書き出さない）"}（{time.time() - t_all:.0f}秒）')
    for k, d in list(picks.items()) + list(named_out.items()):
        print(f"{k[:28]:<28} {d['weights']}  P10π {d['P10π']} P15π {d['P15π']} 年率π {d['π加重の年率']} 最悪 {d['最悪の世界']} ぶれ {d['ぶれ']} 下落 {d['最大下落']} 勝つ確率 {d['S&P500に勝つ確率']['π加重']} IRR {d['積立20年の内部収益率']}")


# ───────────────────────── 積立の内部収益率の分布 ─────────────────────────
def simulate_tables():
    """標準正規の道（20,000本＋反転）を1回だけ作り、m・σ を与えると20年の積立の資産を返せるようにする"""
    T = 12 * H
    rng = np.random.default_rng(P.SEED)
    Z = rng.standard_normal((P.NPATH, T)).astype(np.float32)
    Z = np.vstack([Z, -Z])
    RC = np.flip(np.cumsum(np.flip(Z, axis=1), axis=1), axis=1) / np.float32(math.sqrt(12))
    n_t = np.arange(T, 0, -1, dtype=np.float64)
    r_grid = np.linspace(-0.30, 0.60, 9001)
    K = np.array([np.sum((1 + r) ** (np.arange(1, T + 1) / 12.0)) for r in r_grid])
    return dict(RC=RC, n_t=n_t, r_grid=r_grid, K=K)


def irr_quantiles(sim, m_by_world, sig, pi):
    """π で混ぜた20年の積立の内部収益率の分位（10・25・50・75・90%）"""
    vals, wts = [], []
    for w, m in m_by_world.items():
        p = pi.get(w, 0)
        if p <= 0:
            continue
        A = np.exp(sim['n_t'] / 12.0 * m)
        Wt = (np.exp(np.float32(sig) * sim['RC']) * A[None, :].astype(np.float32)).sum(axis=1)
        irr = np.interp(Wt, sim['K'], sim['r_grid'])
        vals.append(irr); wts.append(np.full(len(irr), p / len(irr)))
    v = np.concatenate(vals); wt = np.concatenate(wts)
    o = np.argsort(v); v, wt = v[o], np.cumsum(wt[o]); wt /= wt[-1]
    return {f'{q}%点': round(100 * float(v[np.searchsorted(wt, q / 100)]), 1) for q in (10, 25, 50, 75, 90)}


if __name__ == '__main__':
    main()
