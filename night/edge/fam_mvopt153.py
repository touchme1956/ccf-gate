#!/usr/bin/env python3
"""night/edge/fam_mvopt153.py — 系統 mvopt153（第10回 ④）: 最適な混ぜ方——153特徴の良い側の三分位を、〜2000 の「超過÷追従のぶれ」が最大の重みで混ぜて固定する

事前登録 out/edge_prereg_r10.json の families.mvopt153（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  ・素材: JKP 米国の三分位ポートフォリオ（買いだけ）。特徴の一覧と良い側は fam_charmom153.py の chars()・sides() をそのまま使う
    （＝hindsight_bound.py と同じ決め方: 〜2000-12 の米国で JKP 因子(vw_cap) と '3.0'−'1.0'（重み w）の共分散の符号）。
  ・総リターン = JKP の三分位 'ret'（米ドルの超過）+ French RF。米国は三分位が50社以上の月だけ（r6/r8/charmom153 にそろえた）。
  ・推定の窓: 「SEL_END（2000-12）まで一か月も欠けずにそろう特徴が100本以上になる、いちばん早い月」M0 から SEL_END まで。
    その窓で欠けの無い特徴だけ（完全ケース）を使い、窓の外の特徴・欠けのある特徴は重み0。
    （対ごとの欠測で共分散を組むと正定値でなくなることがあるので、完全ケースにした）
  ・目的: 米国市場（French）に対する月次超過 e_i = r_i − 市場 の平均 μ と共分散 Σ から、
        IR(w) = w'μ̃ / √(w'Σw)  を最大化（w ≥ 0・Σw = 1・w_i ≤ w_max）。μ̃ = (1−λ)μ + λ·mean(μ)（全体の平均へ λ だけ寄せる）。
    解き方: numpy だけの射影勾配上昇（上限つき単体への射影は二分法）。出発点は等分と「μ̃ の上位 1/w_max 本の等分」の2つ、
    決まった回数・決まった刻みで回す＝同じデータなら必ず同じ答え（乱数なし）。IR の高いほうを採る。
  ・★重みは凍結の時に一度だけ推定して spec['weights'] に書く。run() は spec の重みを読むだけで、決して推定し直さない。
    だから EDGE_SEL_END=199012 で切っても 200012 で切っても同じ重み＝先読みの検査で 1990 年までの成績が一致する。
  ・持ち方: 毎月その重みへ戻す。月 m に三分位が最低社数以上の特徴だけで重みを合計1へ直す（凍結した重みのうちそろう分が50%未満の月は持たない）。
    米国は spec['start']（＝M0）から。
  ・回転: 組の中の置き値 100%/年（月 1/12）＋戻しの回転（前月末に漂った重みと今月の目標の差の絶対値の和の半分）。費用 0.25%/回転。
  ・他の市場: JKP 先進国22か国（spec_profit.json の replicate と同じ）。その国に在る特徴（三分位20社以上）だけで重みを合計1へ直す。
    国の相手は JKP の国の mkt（vw）＋米国 RF。
  ⚠ 選定期間の成績は、同じデータで重みを当てはめた結果＝最適化の性質上、上に偏る（楽観的）。

使い方: python3 night/edge/fam_mvopt153.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_mvopt153.py --save   → 選んで凍結（out/edge/spec_mvopt153.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import fam_charmom153 as cm                     # chars()・legs()・sides() を共有（同じ素材・同じ良い側）
import math, statistics as S
import numpy as np
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'mvopt153',
    'name': '最適な混ぜ方（JKP 米国153特徴の良い側の三分位を、〜2000 の米国市場に対する超過÷追従のぶれが最大の重みで混ぜ、以後固定）',
    'implement': ('JKP が公開する米国の153の特徴ごとの「良い側の3分の1」を、2000年までの成績で決めた固定の重み（1本あたり上限 w_max）で混ぜ、'
                  '毎月その重みへ戻す。個人がそのまま再現するのは難しい——一本ごとに数百社の組を数十本混ぜることになるので、'
                  '実際には重みの大きい特徴の上位銘柄を時価の大きい順に絞る近似か、因子ETF（楽天で買える QUAL・VLUE・MTUM・USMV など）'
                  'を固定比で持つ粗い近似になる（ETF は十数本しか無く、この最適化とは別物）。楽天証券の米国株・海外ETF（成長投資枠＝NISA 可）'),
}

COST = 0.0025
TURN_ANN = 1.0                    # 組の中の回転の置き値（会計と価格の信号の間・charmom153 と同じ）
MIN_N = 50
MIN_N_REPL = 20
MIN_AVAIL = 0.5                   # 凍結した重みのうち、その月にそろう分がこれ未満なら持たない
MIN_FULL = 100                    # 推定の窓: 完全にそろう特徴がこの本数以上になる最初の月から
LAMS, WMAXS, WS = (0.0, 0.5, 0.9), (0.1, 0.25), ('vw_cap', 'vw')
REPL = list(cm.REPL)
ITERS = 4000


# ───────────────────────── 系列 ─────────────────────────
def series(region, sides, w, rf, min_n):
    """→ {特徴: {m: 総リターン}}（三分位が min_n 社以上の月だけ）"""
    out = {}
    for c, s in sides.items():
        p = cm.legs(region, c, w)
        if s not in p:
            continue
        r, n = p[s]
        ok = {m: r[m] + rf[m] for m in r if m in rf and n.get(m, 0) >= min_n}
        if ok:
            out[c] = ok
    return out


# ───────────────────────── 推定（凍結の時だけ） ─────────────────────────
def window(ser):
    """M0 = SEL_END まで一か月も欠けずにそろう特徴が MIN_FULL 本以上になる最初の月 → (M0, 特徴の一覧)"""
    starts = {}
    for c, v in ser.items():
        m = h.SEL_END
        if m not in v:
            continue
        while h.add_months(m, -1) in v:
            m = h.add_months(m, -1)
        starts[c] = m                                        # SEL_END から遡って途切れない最初の月
    ss = sorted(starts.values())
    if len(ss) < MIN_FULL:
        return None, []
    M0 = ss[MIN_FULL - 1]
    return M0, sorted(c for c, m in starts.items() if m <= M0)


def proj(x, u):
    """上限つき単体 {0 ≤ w ≤ u, Σw = 1} への射影（二分法・決まった回数）"""
    lo, hi = x.min() - 1.0, x.max()
    for _ in range(200):
        tau = (lo + hi) / 2
        if np.clip(x - tau, 0, u).sum() > 1:
            lo = tau
        else:
            hi = tau
    w = np.clip(x - (lo + hi) / 2, 0, u)
    return w / w.sum()


def ir(w, mu, cov):
    v = float(w @ cov @ w)
    return float(w @ mu) / math.sqrt(v) if v > 0 else -1e9


def optimize(mu, cov, u):
    """IR を射影勾配上昇で最大化。刻みは後退（半分ずつ）で決める。出発点は等分と μ の上位 ⌈1/u⌉ 本の等分"""
    N = len(mu)
    k = min(N, math.ceil(1 / u))
    top = np.zeros(N); top[np.argsort(-mu, kind='stable')[:k]] = 1.0 / k
    best = None
    for w0 in (proj(np.full(N, 1.0 / N), u), proj(top, u)):
        w, f, step = w0, ir(w0, mu, cov), 1.0
        for _ in range(ITERS):
            v = float(w @ cov @ w); a = float(w @ mu)
            g = mu / math.sqrt(v) - a * (cov @ w) / v ** 1.5
            while step > 1e-12:
                wn = proj(w + step * g, u)
                fn = ir(wn, mu, cov)
                if fn > f + 1e-15:
                    break
                step /= 2
            if step <= 1e-12:
                break
            if fn - f < 1e-13:
                w, f = wn, fn
                break
            w, f, step = wn, fn, step * 2
        if best is None or f > best[1]:
            best = (w, f)
    return best


def estimate(sides, w, lam, u):
    """選定期間（M0〜SEL_END）の米国で重みを推定 → {'weights': {特徴: 重み}, 'start': M0, ...}"""
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    ser = series('usa', sides, w, rf, MIN_N)
    M0, cs = window(ser)
    ms = h.month_range(M0, h.SEL_END)
    E = np.array([[ser[c][m] - mk[m] for m in ms] for c in cs])      # 特徴 × 月 の超過
    mu = E.mean(axis=1)
    mu_s = (1 - lam) * mu + lam * mu.mean()
    cov = np.cov(E)
    wv, f = optimize(mu_s, cov, u)
    wts = {c: round(float(x), 6) for c, x in zip(cs, wv) if x > 1e-6}
    tot = sum(wts.values())
    wts = {c: round(x / tot, 6) for c, x in wts.items()}
    return {'weights': wts, 'start': M0, 'n_chars_est': len(cs), 'months_est': len(ms),
            'ir_monthly_fitted': round(f, 4), 'ir_annual_fitted': round(f * math.sqrt(12), 3)}


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n, start=None):
    """spec の固定の重みで持つ（推定しない）→ (総リターン {m}, 片道の回転 {m})
    月 m に使うのは月 m の行の n（m−1 月末に組んだ時点の数）と凍結した重みだけ"""
    W = spec['weights']
    ser = series(region, {c: spec['sides'][c] for c in W}, spec['w'], rf, min_n)
    if not ser:
        return {}, {}
    months = sorted(set().union(*[set(v) for v in ser.values()]))
    ret, tv, prev = {}, {}, None
    for m in months:
        if (start and m < start) or m not in rf:
            prev = None
            continue
        av = [c for c in W if c in ser and m in ser[c]]
        s = sum(W[c] for c in av)
        if s < MIN_AVAIL:
            prev = None
            continue
        tw = {c: W[c] / s for c in av}
        reb = 0.0 if prev is None else 0.5 * sum(abs(tw.get(c, 0.0) - prev.get(c, 0.0)) for c in set(tw) | set(prev))
        rs = {c: ser[c][m] for c in av}
        ret[m] = sum(tw[c] * rs[c] for c in av)
        tv[m] = TURN_ANN / 12 + reb
        g = {c: tw[c] * (1 + rs[c]) for c in av}
        tot = sum(g.values())
        prev = {c: x / tot for c, x in g.items()} if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N), spec.get('start'))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    jobs = [(c, ch) for c in spec.get('replicate', []) for ch in spec['weights']]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda x: cm.legs(x[0], x[1], spec['w']), jobs))
    for c in spec.get('replicate', []):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')
        except Exception:
            continue
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t = build(spec, c, rf, spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        if len(r) >= 24 and bench:
            out['markets'][c] = {'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def variants():
    """成績を見る前に決めた変種（12本）: λ × w_max × 重み"""
    return [(f'lam{lam}_wmax{u}|{w}', lam, u, w) for w in WS for lam in LAMS for u in WMAXS]


def select(SD):
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    rows = []
    for name, lam, u, w in variants():
        est = estimate(SD[w], w, lam, u)
        sp = {'w': w, 'lam': lam, 'w_max': u, 'weights': est['weights'], 'start': est['start'],
              'sides': {c: SD[w][c] for c in est['weights']}}
        r, tv = build(sp, 'usa', rf, MIN_N, sp['start'])
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in (('〜1975', None, 197512), ('1976-2000', 197601, h.SEL_END), ('1986-2000', 198601, h.SEL_END)):
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        bt, al = cm.beta(r, mk, rf, b=h.SEL_END)
        top = sorted(est['weights'].items(), key=lambda x: -x[1])[:8]
        rows.append({'name': name, 'spec': sp, 'est': est, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None,
                     'n_held': len(est['weights']), 'top_weights': top})
        print(f"{name:22} {st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al:+} 回転{rows[-1]['turnover_yr']} "
              f"本数{len(est['weights'])} IR(当てはめ・年){est['ir_annual_fitted']} 部分{sub}")
        print('      上位の重み', top)
    return rows


def main(save=False):
    SD = cm.sides(cm.chars())
    for w in WS:
        print(w, '特徴', len(SD[w]), '側3.0', sum(1 for s in SD[w].values() if s == '3.0'))
    rows = select(SD)
    elig = [r for r in rows if r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max(rows, key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。t が最大の変種を選んだ（線に届かないことを承知で）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'min_avail': MIN_AVAIL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "sides = 〜2000-12 の米国で JKP 因子(vw_cap) と '3.0'−'1.0' の共分散の符号（hindsight_bound・charmom153 と同じ）。凍結時に固定",
                 'weights_note': '重みは凍結の時に M0〜2000-12 の米国で一度だけ推定した定数。run() は推定し直さない'})
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    tbl = [{'name': x['name'], 'from': x['stats']['from'], 'excess': x['stats']['excess'], 't': x['stats']['t'],
            't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'bench_vol': x['stats']['bench_vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm': x['alpha_capm'], 'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr'],
            'n_held': x['n_held'], 'ir_annual_fitted': x['est']['ir_annual_fitted'], 'top_weights': x['top_weights']} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    sub, est = best['sub'], best['est']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    others = sorted(rows, key=lambda x: -x['stats']['t'])[:4]
    rationale = (
        f'【規則】{best["name"]}: JKP 米国の特徴の良い側の三分位（{"上限つきの時価加重 vw_cap" if spec["w"] == "vw_cap" else "上限なしの時価加重 vw"}）を、'
        f'{est["start"]}〜2000-12（{est["months_est"]}か月・完全にそろう {est["n_chars_est"]} 本）の米国市場に対する月次超過の'
        f'「平均（全体の平均へ λ={spec["lam"]} 寄せた）÷ 追従のぶれ」が最大になる重み（買いだけ・合計1・1本 {spec["w_max"]} まで）で混ぜ、'
        f'以後その重み（{len(spec["weights"])} 本）に固定して毎月戻す。'
        '【なぜ】2001年より前に筋があった: 平均・分散の最適化（Markowitz 1952）・情報比の最大化（Grinold & Kahn 1995 の能動運用の枠組み）、'
        '推定誤差への縮小（James-Stein・Jorion 1986 のベイズ・スタイン縮小）。多くの特徴は相関が低く、混ぜると追従のぶれが下がる。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年。回転 {best["turnover_yr"]}/年。当てはめの IR（年・費用前）{est["ir_annual_fitted"]}。'
        f'部分期間: ' + ' / '.join(f'{lab} {v["excess"]:+}%/年（t {v["t"]}）' for lab, v in sub.items() if v) + '。'
        '★⚠ 選定期間の成績は、同じデータで重みを当てはめた結果＝最適化の性質上、上に偏る（楽観的）。t は「この期間に最も良かった混ぜ方」の t であって、'
        '将来の期待の推定ではない（推定誤差の最大化・Michaud 1989）。検定期間（2001〜）でだけ意味のある数字が出る。'
        f'【選び方】{how}。t の上位4: ' + ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in others) + '。'
        f'【他の市場（選定期間・参考・多くは1990年前後から）】先進国22か国のうち選定期間で測れた {len(mkt_sel)} か国で超過が正は {pos}（重みは米国で決めたもの）。'
        '⚠ 153本という特徴の一覧そのものは2023年の JKP の選択＝2001年以降に知られた特徴も含む（事後の知識が一覧に入っている）。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'],
             'estimation': est,
             'lookahead_test': ('night/edge/prefix_check.py（EDGE_SEL_END=199012 と 200012 で別プロセスに run() を回し、1990-12 までの規則・相手・'
                                '他の市場の成績が完全一致）。重み・側・開始月は spec の定数で、run() はデータから平均・共分散・分位を推定しない'
                                '（推定は --save の時に 2000-12 までのデータで一度だけ）。月 m に持つかは月 m の行の n（JKP が m−1 月末に組んだ時点の数）だけで決める'),
             'variants_table': tbl, 'markets': list(REPL), 'markets_selection_period': mkt_sel, 'selection_note': how,
             'benchmark': 'French 米国市場（Mkt-RF＋RF）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転1あたり 0.25%。回転は組の中の置き値 100%/年＋固定の重みへ戻す回転（漂った重みと目標の差の絶対値の和の半分）',
             'in_sample_warning': '選定期間の成績は同じデータで最適化した当てはめ＝上に偏る。検定期間の成績だけが判定に意味を持つ',
             'decisions_not_in_prereg': [
                 f'推定の窓: SEL_END まで欠けずにそろう特徴が {MIN_FULL} 本以上になる最初の月 M0（={est["start"]}）から 2000-12。完全ケースだけ（対ごとの欠測は共分散が正定値でなくなるので使わない）。窓でそろわない特徴は重み0',
                 '米国の三分位は50社以上の月だけ（r6/r8/charmom153 の米国の決まりにそろえた）',
                 'μ・Σ は費用前の月次の算術超過（総リターン − French 市場）。Σ は標本共分散（縮小なし・事前登録は平均の縮小だけを書いていた）',
                 '解き方: numpy の射影勾配上昇（後退の刻み・上限つき単体への二分法の射影）。出発点は等分と μ̃ の上位 ⌈1/w_max⌉ 本の等分の2つで IR の高いほう（scipy は入っていない）',
                 '重みは 1e-6 未満を0にして合計1へ直し、小数6桁で spec に固定',
                 f'持ち方: その月に三分位が最低社数以上の特徴だけで合計1へ直す。凍結した重みのうちそろう分が {MIN_AVAIL} 未満の月は持たない（他の国も同じ）',
                 '米国は M0 から持つ（M0 より前は推定の窓の外なので成績に入れない）',
                 '良い側は米国で凍結した側を他の国にもそのまま使う（国ごとに推定しない）',
                 '良い側・重みは凍結時に spec に固定（run() で推定すると先読みの検査で切り口ごとに変わるため）']}
    doc = h.save_spec('mvopt153', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
