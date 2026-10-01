#!/usr/bin/env python3
"""night/edge/fam_minvar_ind.py — 系統 minvar_ind: 業種の最小分散（空売りなし・1業種の上限つき）

事前登録 out/edge_prereg.json（第1回の枠組み・第5回の系統）の一系統。読むだけ・門の採点に不使用。
  信号: 月 m に持つ重みは **m−1 月末までの過去 N か月**の業種リターンの標本共分散 S（窓の平均を引く・ddof=1）を
        対角へ δ だけ縮めた Σ=(1−δ)S+δ·diag(S) から、
            min wᵀΣw  s.t.  Σw=1, 0 ≤ w ≤ w_max
        を解いて作る（厳密な active-set 法・numpy だけ）。借入なし。
        作り直しは毎月（reb='M'）か四半期（reb='Q'＝1・4・7・10月の頭＝12・3・6・9月末の情報で作る）。
        作り直さない月は重みを前月のリターンで流したまま持つ（回転0）。
  データ: Ken French の {n}_Industry_Portfolios の 'Average Value Weighted Returns -- Monthly'（業種の中は時価加重・配当込み）。
        窓の全月と m−1 月のリターンがそろう業種だけを使う（49業種は 1963〜69 年に始まる業種と Rubbr の 1943-07〜1944-06 の欠測がある）。
        持っている業種の m 月が欠測（Rubbr の12か月だけ）はリターン0と置き、次の作り直しで窓が欠けるので外れる。
  相手: 米国市場（h.us_market＝French の CRSP 全上場の時価加重・配当込み）。費用: 片道の回転1あたり 0.10%（業種ETF）。
  回転: 前月の重みを当月のリターンで流した後の重みと、新しい重みの差の絶対値の和の半分（片道）。最初の月は1（全額を買う）。
  先読みの検査: lookahead_test()（未来のデータを消しても・乱数に置き換えても過去の重みが1ビットも変わらないこと等）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h                                                  # noqa: E402
import numpy as np                                                   # noqa: E402

FAMILY = {
    'key': 'minvar_ind',
    'name': '業種の最小分散（過去のぶれと連動から、いちばん揺れない業種の組を毎月作る・空売りなし・1業種の上限つき）',
    'implement': ('楽天証券の米国株口座（特定口座）で、米国の業種ETFを最小分散の重みで持つ。粗い業種（12〜17）なら SPDR の '
                  'Select Sector 11本〔XLU・XLP・XLV・XLF・XLE・XLI・XLY・XLB・XLK・XLRE・XLC〕で近似でき、細かい業種（30・49）は '
                  'iShares/SPDR の業種ETF〔IYT・ITA・XHB・KBE・XOP・XME・IHI・XPH など〕を足して近似する（49業種の完全な再現はできない）。'
                  '毎月（または四半期）末に過去 N か月の月次リターンから共分散を計算し、重みを表計算で解いて入れ替える。'
                  '⚠ NISA の成長投資枠でも業種ETFは買えるが、定期的な入れ替えは売るたびに枠を消費し翌年まで戻らないので続けられない'
                  '＝課税口座で行う（売却益に20.315%・事前登録どおり主の判定には入れない）。'
                  '同じ考え方の既製品として iShares MSCI USA Min Vol Factor ETF（USMV・個別株の最小分散・業種の偏りに上限）や '
                  'Invesco S&P 500 Low Volatility（SPLV）が楽天で買え NISA 成長枠にも入るが、これは個別株の最小分散で本規則そのものではない'),
}

COST = 0.001            # 事前登録: 指数・ETF・業種の入れ替え＝片道の回転100%につき 0.10%

_cache = {}


def _load(n):
    if n not in _cache:
        d = h.french(f'{n}_Industry_Portfolios')
        _cache[n] = {i: {m: v / 100 for m, v in s.items() if 99999 < m < 1000000}
                     for i, s in d['Average Value Weighted Returns -- Monthly'].items()}
    return _cache[n]


# ───────────────────────── 最小分散の解（厳密な active-set 法） ─────────────────────────
def _proj_capped_simplex(v, u):
    """{w: Σw=1, 0≤w≤u} への射影（区分線形の方程式を折れ点で厳密に解く）"""
    bps = np.concatenate([v, v - u])
    f = np.clip(v[None, :] - bps[:, None], 0.0, u).sum(axis=1)     # f(τ) は τ について非増加
    order = np.argsort(bps)
    bs, fs = bps[order], f[order]
    k = np.searchsorted(-fs, -1.0)                                   # fs[k-1] ≥ 1 ≥ fs[k]
    if k == 0:
        tau = bs[0]
    elif k >= len(bs):
        tau = bs[-1]
    else:
        t0, t1, f0, f1 = bs[k - 1], bs[k], fs[k - 1], fs[k]
        tau = t0 if f0 == f1 else t0 + (f0 - 1.0) * (t1 - t0) / (f0 - f1)
    return np.clip(v - tau, 0.0, u)


def _pgd(Q, u, iters=20000):
    """予備: 加速射影勾配（active-set が収束しないときだけ使う）"""
    n = len(Q)
    L = float(np.linalg.eigvalsh(Q)[-1]) * 2 + 1e-18
    w = np.full(n, 1.0 / n); y = w.copy(); t = 1.0
    for _ in range(iters):
        w1 = _proj_capped_simplex(y - (2 * Q @ y) / L, u)
        t1 = (1 + (1 + 4 * t * t) ** 0.5) / 2
        y = w1 + ((t - 1) / t1) * (w1 - w)
        if np.max(np.abs(w1 - w)) < 1e-14:
            w = w1; break
        w, t = w1, t1
    return w


def minvar_weights(Q, u, tol=1e-12, maxit=500):
    """min wᵀQw s.t. 1ᵀw=1, 0≤w≤u（Q は正定値）。原始の active-set 法（Nocedal & Wright 16.3）。等加重から始める"""
    n = len(Q)
    if n * u < 1 - 1e-12:
        raise ValueError('上限が低すぎて合計1にできない')
    w = np.full(n, 1.0 / n)
    lo, up = set(), set()                                            # 作業集合（下限0・上限u で縛っている業種）
    if abs(1.0 / n - u) < 1e-15:
        up = set(range(n))
    for _ in range(maxit):
        F = [i for i in range(n) if i not in lo and i not in up]
        g = Q @ w
        if F:
            QF = Q[np.ix_(F, F)]
            K = np.zeros((len(F) + 1, len(F) + 1))
            K[:-1, :-1] = QF; K[:-1, -1] = -1.0; K[-1, :-1] = 1.0
            rhs = np.concatenate([-g[F], [0.0]])
            sol = np.linalg.solve(K, rhs)
            pF, mu = sol[:-1], sol[-1] + 0.0
            # 勾配 g＋Qp の自由な成分は mu に等しい（KKT）
            mu = float(np.mean(g[F] + QF @ pF))
        else:
            pF, mu = np.zeros(0), None
        if len(pF) == 0 or np.max(np.abs(pF)) < tol:
            gl = [(g[i], i) for i in lo]; gu = [(g[i], i) for i in up]
            if mu is None:                                           # 全部が境界（n·u=1 のような端）
                if gl and gu and max(x for x, _ in gu) > min(x for x, _ in gl):
                    return _pgd(Q, u)
                return w
            worst, wi, side = -tol * max(1.0, abs(mu)), None, None
            for x, i in gl:                                          # 下限の乗数 g_i − mu ≥ 0
                if x - mu < worst:
                    worst, wi, side = x - mu, i, 'lo'
            for x, i in gu:                                          # 上限の乗数 mu − g_i ≥ 0
                if mu - x < worst:
                    worst, wi, side = mu - x, i, 'up'
            if wi is None:
                return w
            (lo if side == 'lo' else up).discard(wi)
            continue
        p = np.zeros(n); p[F] = pF
        alpha, block, bside = 1.0, None, None
        for j, i in enumerate(F):
            if pF[j] < -1e-18:
                a = -w[i] / pF[j]
                if a < alpha:
                    alpha, block, bside = a, i, 'lo'
            elif pF[j] > 1e-18:
                a = (u - w[i]) / pF[j]
                if a < alpha:
                    alpha, block, bside = a, i, 'up'
        w = w + alpha * p
        if block is not None:
            w[block] = 0.0 if bside == 'lo' else u
            (lo if bside == 'lo' else up).add(block)
        w = np.clip(w, 0.0, u)
    return _pgd(Q, u)


# ───────────────────────── 信号（m−1 月末までのデータだけ） ─────────────────────────
def window_cov(r, m, N):
    """月 m に持つための窓: m−N 〜 m−1 の N か月。全月そろう業種だけ → (業種の並び, N×k の行列)"""
    last = h.add_months(m, -1)
    ms = h.month_range(h.add_months(last, -(N - 1)), last)
    names = [i for i, s in r.items() if all(x in s for x in ms)]
    if not names:
        return [], None, ms
    X = np.array([[r[i][x] for i in names] for x in ms])
    return names, X, ms


def weights(r, m, spec):
    names, X, ms = window_cov(r, m, spec['N'])
    assert ms[-1] == h.add_months(m, -1) and len(ms) == spec['N']   # 窓の最後は m−1 月
    u = spec['wmax']
    if len(names) < 3 or len(names) * u < 1:
        return None
    S = np.cov(X, rowvar=False, ddof=1)
    d = spec.get('shrink', 0.5)
    Q = (1 - d) * S + d * np.diag(np.diag(S))
    w = minvar_weights(Q, u)
    w = np.clip(w, 0.0, u); w = w / w.sum()
    return {i: float(x) for i, x in zip(names, w) if x > 1e-12}


def _is_reb(m, reb):
    return reb == 'M' or (m % 100) in (1, 4, 7, 10)


def run(spec, _data=None):
    """spec: {'n': 業種の数(49/30/17/12), 'N': 窓の月数, 'wmax': 1業種の上限, 'shrink': 対角への縮小 δ, 'reb': 'M'|'Q'}"""
    r = _data if _data is not None else _load(spec['n'])
    mkt, rf = h.us_market()
    months = sorted(set().union(*[set(s) for s in r.values()]))
    ret, tv = {}, {}
    w_drift = None
    for m in months:
        if w_drift is None or _is_reb(m, spec.get('reb', 'M')):
            w = weights(r, m, spec)
            if w is None:
                if w_drift is None:
                    continue
                w = w_drift
        else:
            w = w_drift
        rp = sum(wi * r[i].get(m, 0.0) for i, wi in w.items())
        if w_drift is None:
            tv[m] = 1.0
        else:
            ks = set(w) | set(w_drift)
            tv[m] = 0.5 * sum(abs(w.get(i, 0.0) - w_drift.get(i, 0.0)) for i in ks)
        ret[m] = rp
        w_drift = {i: wi * (1 + r[i].get(m, 0.0)) / (1 + rp) for i, wi in w.items()} if rp > -1 else None
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, cut=199012, step=23, seed=7):
    """(1) 各検査月 m で、m 以降のデータを全部消した表と、m 以降を乱数に置き換えた表と、元の表から作った重みが
           1ビットも変わらない（重みは m−1 月末までのデータだけで決まる）
       (2) 規則全体を cut（1990-12）で切ったデータで走らせた成績が、全データの成績と cut までの全月で1ビットも一致する
       (3) 解の検算: active-set の解が加速射影勾配の解と目的関数で一致（最適性）"""
    r = _load(spec['n'])
    months = sorted(set().union(*[set(s) for s in r.values()]))
    rng = np.random.default_rng(seed)
    checked = 0
    for m in months[spec['N'] + 1::step]:
        w0 = weights(r, m, spec)
        cutd = {i: {k: v for k, v in s.items() if k < m} for i, s in r.items()}
        noisy = {i: {k: (v if k < m else float(rng.normal(0, 0.2))) for k, v in s.items()} for i, s in r.items()}
        w1, w2 = weights(cutd, m, spec), weights(noisy, m, spec)
        assert w0 == w1 == w2, f'先読み: {m} の重みが未来のデータで変わった'
        checked += 1
    full = run(spec)
    trunc = run(spec, _data={i: {k: v for k, v in s.items() if k <= cut} for i, s in r.items()})
    common = [k for k in full['ret'] if k <= cut]
    bad = [k for k in common if trunc['ret'].get(k) != full['ret'][k] or trunc['turnover'].get(k) != full['turnover'][k]]
    assert not bad, f'先読み: {cut} で切ると過去の成績が変わる {bad[:5]}'
    # 最適性の検算
    worst = 0.0
    for m in months[spec['N'] + 1::97]:
        names, X, _ = window_cov(r, m, spec['N'])
        if len(names) * spec['wmax'] < 1:
            continue
        S = np.cov(X, rowvar=False, ddof=1); d = spec.get('shrink', 0.5)
        Q = (1 - d) * S + d * np.diag(np.diag(S))
        wa, wb = minvar_weights(Q, spec['wmax']), _pgd(Q, spec['wmax'], 60000)
        oa, ob = float(wa @ Q @ wa), float(wb @ Q @ wb)
        worst = max(worst, (oa - ob) / ob)
        assert abs(wa.sum() - 1) < 1e-9 and wa.min() > -1e-12 and wa.max() < spec['wmax'] + 1e-12
    assert worst < 1e-6, f'active-set の解が最適でない（相対差 {worst}）'
    return {'weight_months_checked': checked, 'prefix_months_equal': len(common), 'cut': cut,
            'optimality_worst_rel_gap_vs_pgd': worst}


if __name__ == '__main__':
    sp = {'n': 49, 'N': 60, 'wmax': 0.15, 'shrink': 0.5, 'reb': 'M'}
    x = run(sp)
    print(sp, h.stats(x['ret'], x['bench'], x['rf'], turnover=x['turnover'], cost=x['cost']))
