#!/usr/bin/env python3
"""night/bestpf_ndx_core.py — NASDAQ100 を主軸に、最も効率よく15%を超える組み合わせ（2026-10-12・ユーザー「NASDAQを主軸に最も効率よく15％を超えるポートフォリオは？」）

読むだけ。門・採点・配分には触れない。事前登録の外（ユーザーの問いへの答え。物差しは bestpf_eval と同じ）。
物差し（bestpf_eval と同じ・関数もそこから読む）:
  5つの世界 A1（2000-09〜の実績）・A2（2011-10〜）・B（100年の平均）・C（JPM 2026）・D（15社の予想の中央）と重み π（R8 の較正）。
  20年の毎月の積立の内部収益率が15%以上になる確率 P15π（毎月の対数リターンを N(m/12, σ²/12)・σ は A1 の窓の共分散）。
  P5π＝5%未満・P0π＝元本割れ・最悪の世界・ぶれ・最大下落（A1 の窓）。株だけ（金を除く）26本。
主軸の決まり（主）: NASDAQ100（QQQM＝iFreeNEXT と同じ指数）が 40%以上 かつ どの本よりも多い（同じは可）。10%刻み・合わせて5本まで。
  感度: NASDAQ100 が50%以上。実行可能＝最悪の世界が S&P500（VOO）以上（bestpf の事前登録と同じ）。
「効率よく」＝同じぶれで15%以上の確率が高い（etf_p15 と同じ定義）。ぶれの上限ごとに確率が最大の組み合わせ（前線）を出し、
  答えの中心は「NASDAQ100 だけと同じぶれで確率が最大」（主軸のぶれの枠の中で最も効率がよい）。同点（0.5pt 以内）は 5%未満の確率 → ぶれ の順。
感度（bestpf_eval と同じ名前）: 世界を1つ外す（loo_*）・半導体の基礎率（K4）・共分散を A2 の窓（K2）・C を GMO / Vanguard・π を等しく・π の別の較正。
出力: out/bestpf_ndx_core.json
"""
import datetime, itertools, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R      # noqa: E402
import etf_forward_combo as CB    # noqa: E402
import etf_p15 as P               # noqa: E402
import bestpf_eval as E           # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_ndx_core.json')
WORLDS = E.WORLDS
KMAX = 5
TIE = 0.005
CORE = 'QQQM'


def grid(n, iq, min0):
    """NASDAQ100（列 iq）が min0×10% 以上かつ最大の組み合わせ（10%刻み・5本まで）→ Wint（10分の1単位）"""
    others = [j for j in range(n) if j != iq]
    rows = []
    for w0 in range(min0, 11):
        rest = 10 - w0
        if rest == 0:
            v = np.zeros(n, dtype=np.uint8); v[iq] = 10; rows.append(v); continue
        for k in range(1, KMAX):
            if k > rest:
                break
            comps = CB.compositions(rest, k)
            comps = comps[(comps <= w0).all(axis=1)]
            if not len(comps):
                continue
            for sub in itertools.combinations(others, k):
                for c in comps:
                    v = np.zeros(n, dtype=np.uint8); v[iq] = w0; v[list(sub)] = c; rows.append(v)
    W = np.array(rows, dtype=np.uint8)
    assert (W.sum(axis=1) == 10).all()
    return W


def main():
    t0 = time.time()
    res, _ = E.rank_result()
    rows, chains = res['rows'], res['chains']
    k1, k2 = R.months(*R.A1), R.months(*R.A2)
    assets = [c for c in rows if c not in E.EXCLUDE and all(m in chains.get(c, {}) for m in k1)]
    n = len(assets)
    iq, vi = assets.index(CORE), assets.index('VOO')
    print('資産', n, assets, flush=True)
    G1 = np.array([[chains[c][m] for m in k1] for c in assets])
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    S1 = np.cov(np.log1p(G1), bias=True) * 12; S2 = np.cov(np.log1p(G2), bias=True) * 12
    s1, s2 = np.diag(S1).copy(), np.diag(S2).copy()
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets])
    gC_gmo = np.array([rows[c]['_c_gmo'] for c in assets]); gC_vg = np.array([rows[c]['_c_vg'] for c in assets])
    Dmap, _, _ = E.load_D(rows, assets)
    gD = np.array([Dmap[c] for c in assets])
    pi_main, pi_sens, _ = E.load_pi()
    chips_share = {}
    for c in assets:
        if c == 'VOO':
            chips_share[c] = CB.CHIPS_MKT
        elif (R.C.get(c) or {}).get('us'):
            chips_share[c] = float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    chips_adj = np.array([((-CB.CHIPS_GAP * chips_share[c] + rest * (1 - chips_share[c])) / 2) if c in chips_share else 0.0 for c in assets])
    tabs = P.dca_tables(E.H, [0.0, 0.05, 0.10, 0.15], log=False)

    def stats(W):
        """W: (N, n) 比 → a1g・a2g・vol・mdd・q1・q2（塊で）"""
        N = W.shape[0]
        out = {k: np.empty(N) for k in ('a1g', 'a2g', 'vol', 'mdd', 'q1', 'q2')}
        for s in range(0, N, 20000):
            w = W[s:s + 20000]
            g, v, d = CB.path_stats(w @ G1, len(k1))
            out['a1g'][s:s + 20000] = g; out['vol'][s:s + 20000] = v; out['mdd'][s:s + 20000] = d
            out['a2g'][s:s + 20000] = np.expm1(np.log1p(w @ G2).sum(axis=-1) * 12 / len(k2))
            out['q1'][s:s + 20000] = ((w @ S1) * w).sum(axis=1); out['q2'][s:s + 20000] = ((w @ S2) * w).sum(axis=1)
        return out

    def world_vals(W, bs, var):
        A1 = bs['a1g'] + W @ adj; A2 = bs['a2g'] + W @ adj
        sv, qv = (s2, bs['q2']) if var == 'K2' else (s1, bs['q1'])
        bonus = 0.5 * (W @ sv - qv)
        b, c, dd = gB, gC, gD
        if var == 'K4':
            b, c, dd = gB + chips_adj, gC + chips_adj, gD + chips_adj
        if var == 'C_GMO':
            c = gC_gmo
        if var == 'C_VG':
            c = gC_vg
        return dict(A1=A1, A2=A2, B=np.expm1(W @ np.log1p(b) + bonus), C=np.expm1(W @ np.log1p(c) + bonus), D=np.expm1(W @ np.log1p(dd) + bonus))

    def pi_of(var):
        if var.startswith('loo_'):
            p = {k: (0.0 if k == var[4:] else v) for k, v in pi_main.items()}
            s = sum(p.values()); return {k: v / s for k, v in p.items()}
        if var.startswith('pi_'):
            return pi_sens.get(var[3:])
        if var == 'equal_pi':
            return {w: 1 / 5 for w in WORLDS}
        return pi_main

    def probs(wv, sig, pi):
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
        out['mean'] = sum(pi[w] * wv[w] for w in live)
        return out

    Wint = grid(n, iq, 4)
    W = Wint.astype(np.float64) / 10.0
    print(f'組み合わせ {len(W):,}（NASDAQ100 ≥40% かつ最大・5本まで）', flush=True)
    bs = stats(W)
    e_voo = np.zeros((1, n)); e_voo[0, vi] = 1.0
    e_ndx = np.zeros((1, n)); e_ndx[0, iq] = 1.0
    bs_voo, bs_ndx = stats(e_voo), stats(e_ndx)
    w_now = np.zeros((1, n)); w_now[0, iq] = 50 / 85; w_now[0, assets.index('SMH')] = 20 / 85; w_now[0, assets.index('ITA')] = 15 / 85
    bs_now = stats(w_now)

    def wd(i):
        return {assets[j]: int(Wint[i, j]) * 10 for j in np.argsort(-Wint[i].astype(int), kind='stable') if Wint[i, j]}

    def evaluate(var):
        pi = pi_of(var)
        if pi is None:
            return None
        sg = np.sqrt(bs['q2'] if var == 'K2' else bs['q1'])
        pr = probs(world_vals(W, bs, var), sg, pi)
        ref = {}
        for nm, b1, w1 in (('VOO', bs_voo, e_voo), ('NDX', bs_ndx, e_ndx), ('今の形', bs_now, w_now)):
            p1 = probs(world_vals(w1, b1, var), np.sqrt(b1['q2'] if var == 'K2' else b1['q1']), pi)
            ref[nm] = {k: float(v[0]) for k, v in p1.items()}
            ref[nm]['vol'] = float(b1['vol'][0]); ref[nm]['mdd'] = float(b1['mdd'][0])
        feas = pr['worst'] >= ref['VOO']['worst'] - 1e-12
        return pi, pr, ref, feas

    def pick(pr, feas, mask):
        ok = feas & mask
        if not ok.any():
            return None
        key = np.where(ok, pr['P15'], -1.0)
        best = float(key.max())
        near = np.where(ok & (pr['P15'] >= best - TIE))[0]
        return int(near[np.lexsort((bs['vol'][near], pr['P5'][near]))[0]])

    def row(i, pr, extra=None):
        d = dict(weights=wd(i), P15=round(100 * float(pr['P15'][i]), 1), P10=round(100 * float(pr['P10'][i]), 1),
                 P5=round(100 * float(pr['P5'][i]), 1), P0=round(100 * float(pr['P0'][i]), 1), mean=round(100 * float(pr['mean'][i]), 2),
                 worst=round(100 * float(pr['worst'][i]), 2), vol=round(100 * float(bs['vol'][i]), 1), mdd=round(100 * float(bs['mdd'][i]), 1),
                 ndx=int(Wint[i, iq]) * 10)
        if extra:
            d.update(extra)
        return d

    pi, pr, ref, feas = evaluate('main')
    caps = [('S&P500 と同じぶれ', ref['VOO']['vol']), ('18%', 0.18), ('20%', 0.20), ('NASDAQ100 だけと同じぶれ', ref['NDX']['vol']),
            ('今の形と同じぶれ', ref['今の形']['vol']), ('24%', 0.24), ('26%', 0.26), ('28%', 0.28), ('上限なし', 9.9)]
    out = dict(constraint='NASDAQ100 ≥40% かつ最大・10%刻み・5本まで・最悪の世界 ≥ S&P500', n=int(len(W)), n_feasible=int(feas.sum()),
               reference={k: {kk: round(100 * v, 2) for kk, v in d.items()} for k, d in ref.items()}, frontier={}, frontier_ndx50={})
    print('参考', {k: (round(100 * d['P15'], 1), round(100 * d['vol'], 1)) for k, d in ref.items()})
    for nm, cap in caps:
        for key, mask in (('frontier', bs['vol'] <= cap + 1e-12), ('frontier_ndx50', (bs['vol'] <= cap + 1e-12) & (Wint[:, iq] >= 5))):
            i = pick(pr, feas, mask)
            if i is not None:
                out[key][nm] = row(i, pr, dict(cap=round(100 * min(cap, 9.9), 1)))
        r_ = out['frontier'].get(nm)
        if r_:
            print(f'  ぶれ≤{nm:<16} {r_["weights"]}  P15 {r_["P15"]} P5 {r_["P5"]} P0 {r_["P0"]} 最悪 {r_["worst"]} ぶれ {r_["vol"]} 下落 {r_["mdd"]}', flush=True)
    # 効率の物差し2つ（参考）: S&P500 から増えた確率 ÷ 増えたぶれ／15%以上 − 5%未満
    gain = (pr['P15'] - ref['VOO']['P15']) / np.maximum(bs['vol'] - ref['VOO']['vol'], 0.01)
    i_g = int(np.argmax(np.where(feas & (bs['vol'] > ref['VOO']['vol'] + 0.01), gain, -9)))
    i_d = int(np.argmax(np.where(feas, pr['P15'] - pr['P5'], -9)))
    out['efficiency_alt'] = {'S&P500 から増えた確率÷増えたぶれ が最大': row(i_g, pr, dict(gain_per_vol=round(float(gain[i_g]), 2))),
                             '15%以上 − 5%未満 が最大': row(i_d, pr)}
    # 頑健さ: 答えの中心（NASDAQ100 だけと同じぶれ）の組み合わせが、感度ごとの同じ枠の中で何位か
    cap_ndx = ref['NDX']['vol']
    i_main = pick(pr, feas, bs['vol'] <= cap_ndx + 1e-12)
    SENS = ['loo_A1', 'loo_A2', 'loo_B', 'loo_C', 'loo_D', 'K4', 'K2', 'C_GMO', 'C_VG', 'equal_pi'] + [f'pi_{k}' for k in pi_sens]
    sens = {}
    for var in SENS:
        ev = evaluate(var)
        if ev is None:
            continue
        pi2, pr2, ref2, feas2 = ev
        mask = feas2 & (bs['vol'] <= cap_ndx + 1e-12)
        key = np.where(mask, pr2['P15'], -1.0)
        o = np.argsort(-key, kind='stable'); rk = np.empty(len(key)); rk[o] = np.arange(len(key))
        nf = max(int(mask.sum()), 1)
        j = pick(pr2, feas2, bs['vol'] <= cap_ndx + 1e-12)
        sens[var] = dict(pick=row(j, pr2) if j is not None else None, main_rank_pct=round(100 * float(rk[i_main]) / nf, 2) if mask[i_main] else None,
                         main_P15=round(100 * float(pr2['P15'][i_main]), 1), ndx_P15=round(100 * ref2['NDX']['P15'], 1), now_P15=round(100 * ref2['今の形']['P15'], 1))
        print(f'  感度 {var:<12} 1位 {sens[var]["pick"]["weights"] if sens[var]["pick"] else None} P15 {sens[var]["pick"]["P15"] if sens[var]["pick"] else None}｜答えの中心 P15 {sens[var]["main_P15"]} 順位 {sens[var]["main_rank_pct"]}%', flush=True)
    top1 = sum(1 for v in sens.values() if v['main_rank_pct'] is not None and v['main_rank_pct'] < 1.0)
    out['answer'] = row(i_main, pr, dict(rule='NASDAQ100 だけと同じぶれ以下で P15π が最大（同点は 5%未満 → ぶれ）'))
    out['robustness'] = dict(n_sens=len(sens), in_top1pct=top1, sens=sens)
    # 上位20（NASDAQ100 だけと同じぶれ以下）
    m = feas & (bs['vol'] <= cap_ndx + 1e-12)
    top = np.argsort(-np.where(m, pr['P15'], -1.0))[:20]
    out['top20_at_ndx_vol'] = [row(int(i), pr) for i in top]
    # 主軸の組み合わせの中で、各本が上位1000に入る割合
    top1000 = np.argsort(-np.where(m, pr['P15'], -1.0))[:1000]
    out['top1000_presence_pct'] = {assets[j]: round(100 * float((Wint[top1000, j] > 0).mean()), 1) for j in np.argsort(-(Wint[top1000] > 0).mean(axis=0))[:12]}
    out.update(generated=datetime.date.today().isoformat(), tool='night/bestpf_ndx_core.py', posthoc=True, pi=pi,
               question='NASDAQを主軸に最も効率よく15％を超えるポートフォリオは？（ユーザーの問い）',
               warn=['確率は仮定（5つの世界・独立な正規・ぶれと相関は 2000-2026 と同じ）の上の数字',
                     'P15π はぶれを点にしやすい（伸びが15%より下の世界では、ぶれが大きいほど15%を超える確率が上がる）＝同じぶれで比べる',
                     '個別株はこの外（ETF 側だけを測る）'])
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('答え', out['answer'])
    print(f'→ {OUT}（{time.time() - t0:.0f}秒）')


if __name__ == '__main__':
    main()
