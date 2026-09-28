#!/usr/bin/env python3
"""night/nx_regime_ind.py — nx 角度 regime_ind（マクロの局面で『どの業種を持つか』を替える）の**測る道具**
（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…探し続けて」。
ただし線を下げて勝ちを作らない。事前登録 out/nx_regime_ind_prereg.json（測る前に固定・この道具はそれを書き換えない）と
全体の線 out/nx_prereg.json（C1〜C8・格付け S/A/B/C）をそのまま当てる。統計と格付けは night/nx_common.py。

何を測るか
  月末 t に分かるマクロの信号（out/_nx_cache/nx_regime_ind_signals_0fc5506e8837.json の 'frozen'・最初に sha256 を
  事前登録の値と照合し、違えば止まる）で局面を決め、局面の月の翌月 t+1 は業種の組（French 49 の VW 総リターンを
  French の t 月の行の 社数×平均時価 で時価加重）を、それ以外の月は French Mkt（Mkt-RF＋RF）を持つ。常に株100%。
    主の族（格付け・Holm は4本の中で）:
      P1 インフレの急上昇（前年比≥5% かつ 6か月前より高い）→ 実物（GICS 10・15 に当たる10業種）
      P2 直近12か月に逆イールド（10年−3か月<0）→ 守り（GICS 30・35・55 に当たる10業種）
      P3 実時点の Sahm ≥ 0.5 → 守り
      P4 SPF の翌四半期の景気後退の確率が拡大窓の80%点以上 → 守り
    探索の族20本（E1〜E20・格付けはするが『探索』。Holm は20本の中で）。
    対照（無条件・局面の条件つきの差・現金版・偽の時期・偽の業種・後知恵・時代の分割）・局面の塊ごとの符号と二項検定・
    米国外7か国（C5・P1 と P2）・実在の器（SPDR・Fidelity Select・JKP の米国 GICS）はすべて報告。

C4 は丸める前の差で勝ちを数える（兄弟の nx_osap_intang.rolling_x・nx_leadlag.rolling_exact と同じ。nx_common.rolling は
窓ごとの差を小数2桁の%に丸めてから数えるので、0〜0.005%/年の勝ちが負けに化ける）。丸めた数え方も併記する。

使い方: python3 night/nx_regime_ind.py            → out/nx_regime_ind.json
"""
import sys, os, json, math, hashlib, time, zipfile, io as _io, csv
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_regime_ind_data as D  # noqa: E402  （局面の塊の数え方 episodes()・月の計算を事前登録の形の要約と同じ実装で）

PRE = os.path.join(N.BASE, 'out', 'nx_regime_ind_prereg.json')
SIGFILE = os.path.join(N.CACHE, 'nx_regime_ind_signals_0fc5506e8837.json')
OUTNAME = 'nx_regime_ind.json'
COST, COST_SENS = 0.001, 0.003
SEED = 20260928
NPLACEBO = 200
T0 = time.time()
TR, HS = N.TRAIN_END, N.HOLD_START
C5_COUNTRIES = ['jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che']


def log(*a):
    print(f'[{time.time() - T0:6.1f}s]', *a, flush=True)


add, mrange = D.add, D.mrange


def fmt(m):
    return f'{m // 100}-{m % 100:02d}'


# ───────────────────────── 読み込みと照合 ─────────────────────────
def load_signals(pre):
    exp = pre['tools']['signals_sha256'][:64]
    o = json.load(open(SIGFILE))
    got = hashlib.sha256(json.dumps(o['frozen'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if got != exp or o.get('frozen_sha256') != exp:
        raise SystemExit(f'事前登録の信号の指紋と一致しない → 止まる: 期待 {exp} / 写しの frozen {got} / 写しの記録 {o.get("frozen_sha256")}')
    return o, got


class Panel:
    pass


def french_panel():
    T = N.french_tables('49_Industry_Portfolios')
    vw = T['Average Value Weighted Returns -- Monthly']
    nf, sz = T['Number of Firms in Portfolios'], T['Average Firm Size']
    cols = [c.strip() for c in vw['cols']]
    months = sorted(vw['data'])
    assert months == mrange(months[0], months[-1])

    def arr(tab, scale):
        A = np.full((len(months), len(cols)), np.nan)
        for i, mm in enumerate(months):
            for j, v in enumerate(tab['data'].get(mm, [])):
                if v is not None:
                    A[i, j] = v * scale
        return A
    P = Panel()
    P.months, P.names = months, cols
    P.idx = {m: i for i, m in enumerate(months)}
    P.nidx = {c: j for j, c in enumerate(cols)}
    P.R = arr(vw, 0.01)
    P.CAP = arr(nf, 1.0) * arr(sz, 1.0)
    return P


def jkp_gics(country):
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{country}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = N.get(url, name=f'jkp_industry_{country}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(_io.BytesIO(b))
    out = {}
    for x in csv.DictReader(_io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        out.setdefault(str(int(float(x['gics']))), {})[N._ym(x['date'])] = float(x['ret'])
    return out


# ───────────────────────── 規則の実行（持つ月 h ごと） ─────────────────────────
def run_rule(hold_months, state_fn, members_fn, ret_fn, bench, half=False, cash=None, record=False):
    """state_fn(h) → None（市場）か 組の名前。members_fn(組, h) → {構成: 形成の重み}（和1）。ret_fn(構成, h) → リターン or None。
    回転（片道）: 市場↔組 の切り替え 1.0（半分の版 0.5）、組を持ち続ける月は ½Σ|新しい重み − 前月の重みを当月のリターンで流した重み|、
    市場を持ち続ける月は 0。期間の前は市場を持っていたとみなす（最初の月が局面なら切り替え 1.0 を数える）。
    cash が渡されたら局面の月は組の代わりに cash[h]（RF）を持つ（CTRL_regime_cash）。"""
    rets, tos, states, held = {}, {}, {}, {}
    prev = ('MKT',)
    for h in hold_months:
        st = state_fn(h)
        if st is None:
            r = bench[h]
            to = 0.0 if prev[0] == 'MKT' else (0.5 if prev[0] == 'HALF' else 1.0)
            new = ('MKT',)
            assert r == bench[h]
        elif cash is not None:
            r = cash[h]
            to = 0.0 if prev[0] == 'CASH' else 1.0
            new = ('CASH',)
        else:
            w = members_fn(st, h)
            assert w and abs(sum(w.values()) - 1) < 1e-9 and min(w.values()) > 0
            rr = {k: ret_fn(k, h) for k in w}
            fin = {k: v for k, v in rr.items() if v is not None}
            assert fin, f'組 {st} の {h} にリターンが一つも無い'
            s = math.fsum(w[k] for k in fin)
            w2 = {k: w[k] / s for k in fin}
            rs = math.fsum(w2[k] * fin[k] for k in fin)
            g = {k: w2[k] * (1 + fin[k]) for k in fin}
            gs = math.fsum(g.values())
            drift = {k: v / gs for k, v in g.items()}
            if not half:
                r = rs
                if prev[0] == 'SET':
                    pd = prev[1]
                    to = 0.5 * math.fsum(abs(w2.get(k, 0.0) - pd.get(k, 0.0)) for k in set(w2) | set(pd))
                else:
                    to = 1.0
                new = ('SET', drift)
            else:
                r = 0.5 * rs + 0.5 * bench[h]
                if prev[0] == 'HALF':
                    pd, sd = prev[1], prev[2]
                    to = 0.5 * (math.fsum(abs(0.5 * w2.get(k, 0.0) - sd * pd.get(k, 0.0)) for k in set(w2) | set(pd)) + abs(0.5 - (1 - sd)))
                else:
                    to = 0.5
                sd_new = 0.5 * (1 + rs) / (0.5 * (1 + rs) + 0.5 * (1 + bench[h]))
                new = ('HALF', drift, sd_new)
            if record:
                held[h] = w2
        assert -1e-12 <= to <= 1 + 1e-9, (h, to)
        rets[h], tos[h], states[h] = r, to, st
        prev = new
    return {'rets': rets, 'tos': tos, 'states': states, 'held': held}


def french_members(P, SETS, wt):
    def f(st, h):
        ti = P.idx[add(h, -1)]    # French の t 月の行（t−1 月末の時価）
        sel = [P.nidx[x] for x in SETS[st]]
        cap = P.CAP[ti, sel]
        ok = [j for j, c in zip(sel, cap) if np.isfinite(c) and c > 0]
        assert ok, (st, h)
        if wt == 'vw':
            c = np.array([P.CAP[ti, j] for j in ok])
            return {P.names[j]: float(x) for j, x in zip(ok, c / c.sum())}
        return {P.names[j]: 1.0 / len(ok) for j in ok}
    return f


def french_ret(P):
    def f(k, h):
        v = P.R[P.idx[h], P.nidx[k]]
        return float(v) if np.isfinite(v) else None
    return f


def net_of(r, to, c):
    return {k: r[k] - to[k] * c for k in r}


# ───────────────────────── 評価 ─────────────────────────
def _roll_raw(s, b, years=20, start_month=7):
    ks = sorted(set(s) & set(b))
    out = []
    if not ks:
        return out
    y0, last = ks[0] // 100, ks[-1]
    for y in range(y0, 2100):
        a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, gs - gb))
    return out


def rolling_x(s, b, years=20, start_month=7):
    """nx_common.rolling と同じ窓・同じ戻り値。ただし wins / win_rate は丸める前の差 > 0 で数える（兄弟の rolling_x と同じ）"""
    ro = N.rolling(s, b, years, start_month)
    if not ro:
        return ro
    d = _roll_raw(s, b, years, start_month)
    rounded = sorted(round(c * 100, 2) for _, c in d)
    if len(d) != ro['windows'] or rounded[len(rounded) // 2] != ro['median'] or sum(1 for c in rounded if c > 0) != ro['wins']:
        raise SystemExit('rolling_x: 窓の切り方が nx_common.rolling と一致しない')
    we = sum(1 for _, c in d if c > 0)
    ro['wins_nx_common_rounded'] = ro['wins']
    ro['win_rate_nx_common_rounded'] = ro['win_rate']
    ro['wins_changed_by_rounding'] = [[y, c * 100] for y, c in d if c > 0 and round(c * 100, 2) <= 0]
    ro['windows_exactly_zero'] = sum(1 for _, c in d if c == 0)
    ro['wins'] = we
    ro['win_rate'] = round(we / len(d), 3)
    return ro


def dca_x(s, b, years=20, step=12):
    """nx_common.dca と同じ窓・同じ戻り値。ただし win_rate は丸める前の倍率 > 1 で数える"""
    ro = N.dca(s, b, years, step)
    if not ro:
        return ro
    ks = sorted(set(s) & set(b))
    n = years * 12
    raw = []
    for i in range(0, len(ks) - n + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        raw.append((ks[i], ws / wb))
    if len(raw) != ro['windows'] or round(sum(1 for _, r in raw if round(r, 3) > 1) / len(raw), 3) != ro['win_rate']:
        raise SystemExit('dca_x: 窓の切り方が nx_common.dca と一致しない')
    ro['win_rate_nx_common_rounded'] = ro['win_rate']
    ro['win_rate'] = round(sum(1 for _, r in raw if r > 1) / len(raw), 3)
    return ro


def exact_t(g, b, a=None, z=None):
    ks = sorted(k for k in set(g) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    return N.nw_t([g[k] - b[k] for k in ks]) if len(ks) >= 24 else None


def exact_signs(g, b, a=None, z=None):
    ks = sorted(k for k in set(g) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = math.fsum(g[k] - b[k] for k in ks) / len(ks) * 12
    return ex, N.cagr([g[k] for k in ks]) - N.cagr([b[k] for k in ks])


def evaluate(gross, to, bench, rf, post_pubs=None, extra_spans=None):
    es = N.excess_stats
    net, net_s = net_of(gross, to, COST), net_of(gross, to, COST_SENS)
    ks = sorted(gross)
    st = {'full': es(gross, bench), 'train': es(gross, bench, z=TR), 'hold': es(gross, bench, a=HS),
          'recent_2013_07': es(gross, bench, a=N.RECENT_START)}
    for lab, a in (post_pubs or {}).items():
        st[f'post_publication_{lab}'] = es(gross, bench, a=a)
    for lab, (a, z) in (extra_spans or {}).items():
        st[lab] = es(gross, bench, a=a, z=z)
    tov = [to[k] for k in ks]
    cst = {'cost_per_oneway': COST, 'cost_sensitivity': COST_SENS,
           'oneway_turnover_per_year': round(float(np.mean(tov)) * 12, 3),
           'oneway_turnover_per_year_train': round(float(np.mean([to[k] for k in ks if k <= TR])) * 12, 3) if ks[0] <= TR else None,
           'oneway_turnover_per_year_hold': round(float(np.mean([to[k] for k in ks if k >= HS])) * 12, 3),
           'initial_state_assumed': '期間の前は市場を持っていた（最初の月が局面なら切り替え1.0を数える）',
           'net_main': {'full': es(net, bench), 'train': es(net, bench, z=TR), 'hold': es(net, bench, a=HS)},
           'net_sensitivity': {'full': es(net_s, bench), 'train': es(net_s, bench, z=TR), 'hold': es(net_s, bench, a=HS)}}
    bw = {k: bench[k] for k in ks}
    out = {'span': [ks[0], ks[-1]], 'months': len(ks), 'stats_gross': st, 'cost': cst,
           'roll20_net': rolling_x(net, bw), 'roll20_gross': rolling_x(gross, bw),
           'dca20_net_ratio': dca_x(net, bw, 20), 'dca20_gross_ratio': dca_x(gross, bw, 20),
           'maxdd': {'rule_gross': round(N.maxdd(gross) * 100, 1), 'rule_net': round(N.maxdd(net) * 100, 1),
                     'bench_same_span': round(N.maxdd(bw) * 100, 1)},
           'sharpe': {'train': [N.sharpe(gross, rf, z=TR), N.sharpe(bw, rf, z=TR)],
                      'hold': [N.sharpe(gross, rf, a=HS), N.sharpe(bw, rf, a=HS)],
                      'full': [N.sharpe(gross, rf), N.sharpe(bw, rf)],
                      'train_net010': N.sharpe(net, rf, z=TR), 'hold_net010': N.sharpe(net, rf, a=HS),
                      'note': '[規則, Mkt（同じ月）]。費用前（事前登録 series_used_per_criterion.C8_sharpe）。C8 は訓練・保有の両方で規則 > Mkt'}}
    return out, net


def regime_counts(states, a=None, z=None):
    ks = [k for k in sorted(states) if (a is None or k >= a) and (z is None or k <= z)]
    c = {}
    for k in ks:
        s = states[k] or 'MKT'
        c[s] = c.get(s, 0) + 1
    return {'months': len(ks), 'by_state': c}


def binom_upper(k, n):
    return math.fsum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else None


def per_episode(gross, bench, flag_hold, a, z):
    """局面の塊（D.episodes と同じ数え方）ごとに、塊の最初〜最後の月の 規則÷市場 の累積の超過と符号。訓練・保有・全期間"""
    out = {}
    parts = [('full', a, z)]
    if a <= TR:
        parts.append(('train', a, min(z, TR)))
    if z >= HS:
        parts.append(('hold', max(a, HS), z))
    for part, pa, pz in parts:
        e = D.episodes(flag_hold, pa, pz)
        rows = []
        for s, t, n in e['episodes']:
            ms = mrange(s, t)
            cum = math.exp(math.fsum(math.log1p(gross[m]) for m in ms) - math.fsum(math.log1p(bench[m]) for m in ms)) - 1
            rows.append({'from': fmt(s), 'to': fmt(t), 'regime_months': n, 'span_months': len(ms),
                         'cum_excess_pct': round(cum * 100, 3), 'sign': 1 if cum > 0 else (-1 if cum < 0 else 0)})
        k = sum(1 for r in rows if r['sign'] > 0)
        out[part] = {'episodes_n': len(rows), 'positive': k, 'binom_p_one_sided': (round(binom_upper(k, len(rows)), 4) if rows else None),
                     'regime_months': e['on'], 'unknown_months': e['unknown'], 'episodes': rows}
    out['note'] = ('塊＝局面の月の連なりで、局面でない月が6か月未満しか挟まらなければ同じ塊（事前登録の形の要約と同じ D.episodes）。'
                   '訓練と保有をまたぐ塊は両方に（その期間の中の部分で）数える。累積の超過は塊の最初〜最後の月の ∏(1+規則)/∏(1+市場)−1（費用前）。'
                   '二項検定は 正の塊の数 ≥ k の片側 p（p=0.5）。格付けには使わない')
    return out


def nw_ols(y, X, lag=12):
    y = np.asarray(y, float); X = np.column_stack([np.ones(len(y)), np.asarray(X, float)])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:-L]
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi
    return b, np.sqrt(np.diag(V))


# ───────────────────────── 本体 ─────────────────────────
def main():
    pre = json.load(open(PRE))
    sig, sha = load_signals(pre)
    fz = sig['frozen']
    SETS = fz['sets']
    log('信号の指紋 一致', sha[:16])
    P = french_panel()
    ff = N.ff_factors()
    mkt, rf = ff['mkt'], ff['rf']
    Z = P.months[-1]
    assert Z == 202608 and max(mkt) >= Z and max(rf) >= Z, (Z, max(mkt))
    log('French 49', P.months[0], Z)

    us = {k: {int(t): v for t, v in d.items()} for k, d in fz['us_signals'].items()}
    hold_flag = {k: {add(t, 1): v for t, v in d.items()} for k, d in us.items()}
    hind = {k: {int(m): v for m, v in d.items()} for k, d in fz['hindsight'].items()}
    spans = {k: (v['hold_from'], v['hold_to']) for k, v in fz['spans'].items()}

    # 規則の定義（事前登録 families.P_primary / X_exploratory）
    def R_(family, signal, sets, span_of, wt='vw', half=False, post=None):
        return {'family': family, 'signal': signal, 'sets': sets, 'span_of': span_of, 'wt': wt, 'half': half, 'post': post or {}}
    PP = {'P1': {'Neville2021_JPM': 202201, 'FamaSchwert1977': 197801}, 'P2': {'EstrellaMishkin1998': 199901},
          'P3': {'Sahm2019': 201906}, 'P4': {'Philly_release_dates': 199007}}
    RULES = {
        'P1_INF_REAL': R_('primary', 'INF5_r6', 'REAL', 'P1_INF_REAL', post=PP['P1']),
        'P2_YC_DEF': R_('primary', 'YC12', 'DEF', 'P2_YC_DEF', post=PP['P2']),
        'P3_SAHM_DEF': R_('primary', 'SAHM', 'DEF', 'P3_SAHM_DEF', post=PP['P3']),
        'P4_SPF_DEF': R_('primary', 'SPF80', 'DEF', 'P4_SPF_DEF', post=PP['P4']),
        'E1_INF_REAL_early': R_('exploratory', 'INF5_r6', 'REAL', 'E1_INF_REAL_early', post=PP['P1']),
        'E2_YC_DEF_early': R_('exploratory', 'YC12_splice', 'DEF', 'E2_YC_DEF_early', post=PP['P2']),
        'E3_INF_REAL_ew': R_('exploratory', 'INF5_r6', 'REAL', 'P1_INF_REAL', wt='ew', post=PP['P1']),
        'E4_YC_DEF_ew': R_('exploratory', 'YC12', 'DEF', 'P2_YC_DEF', wt='ew', post=PP['P2']),
        'E5_SAHM_DEF_ew': R_('exploratory', 'SAHM', 'DEF', 'P3_SAHM_DEF', wt='ew', post=PP['P3']),
        'E6_SPF_DEF_ew': R_('exploratory', 'SPF80', 'DEF', 'P4_SPF_DEF', wt='ew', post=PP['P4']),
        'E7_INF4': R_('exploratory', 'INF4_r6', 'REAL', 'E7_INF4', post=PP['P1']),
        'E8_INF5_lvl': R_('exploratory', 'INF5_lvl', 'REAL', 'E8_INF5_lvl', post=PP['P1']),
        'E9_INF5_r3': R_('exploratory', 'INF5_r3', 'REAL', 'E9_INF5_r3', post=PP['P1']),
        'E10_INF5_r12': R_('exploratory', 'INF5_r12', 'REAL', 'E10_INF5_r12', post=PP['P1']),
        'E11_INF_REAL_NARROW': R_('exploratory', 'INF5_r6', 'REAL_NARROW', 'P1_INF_REAL', post=PP['P1']),
        'E12_INF_REAL_UTIL': R_('exploratory', 'INF5_r6', 'REAL_UTIL', 'P1_INF_REAL', post=PP['P1']),
        'E13_YC1': R_('exploratory', 'YC1', 'DEF', 'E13_YC1', post=PP['P2']),
        'E14_YC24': R_('exploratory', 'YC24', 'DEF', 'E14_YC24', post=PP['P2']),
        'E15_YC12_10y1y': R_('exploratory', 'YC12_10y1y', 'DEF', 'E15_YC12_10y1y', post=PP['P2']),
        'E16_YC_DEF_EKNZBH': R_('exploratory', 'YC12', 'DEF_EKNZBH', 'P2_YC_DEF', post=PP['P2']),
        'E17_SAHM_12m': R_('exploratory', 'SAHM_12m', 'DEF', 'E17_SAHM_12m', post=PP['P3']),
        'E18_INF_REAL_half': R_('exploratory', 'INF5_r6', 'REAL', 'P1_INF_REAL', half=True, post=PP['P1']),
        'E19_YC_DEF_half': R_('exploratory', 'YC12', 'DEF', 'P2_YC_DEF', half=True, post=PP['P2']),
        'E20_COMBO': R_('exploratory', 'COMBO', None, 'E20_COMBO'),
    }
    assert sum(1 for r in RULES.values() if r['family'] == 'primary') == pre['test_count']['primary']
    assert sum(1 for r in RULES.values() if r['family'] == 'exploratory') == pre['test_count']['exploratory']
    fret = french_ret(P)
    mem = {'vw': french_members(P, SETS, 'vw'), 'ew': french_members(P, SETS, 'ew')}

    def state_fn_of(spec):
        fl = hold_flag[spec['signal']]
        if spec['signal'] == 'COMBO':
            return lambda h: {'REAL': 'REAL', 'DEF': 'DEF', 'MKT': None}[fl[h]]
        return lambda h: spec['sets'] if fl[h] == 1 else None

    def flag01(spec):
        fl = hold_flag[spec['signal']]
        if spec['signal'] == 'COMBO':
            return {h: int(v != 'MKT') for h, v in fl.items()}
        return dict(fl)

    res = {'angle': 'nx_regime_ind', 'generated': time.strftime('%Y-%m-%d'),
           'prereg': 'out/nx_regime_ind_prereg.json', 'global_prereg': 'out/nx_prereg.json',
           'signals_file': os.path.relpath(SIGFILE, N.BASE), 'signals_sha256': sha,
           'benchmark': 'French Mkt（Mkt-RF＋RF・上限なしの時価加重・CRSP 全上場）。規則は French 業種の VW 総リターンと Mkt なので総リターンどうし',
           'sanity': {}, 'deviations_from_prereg': []}

    # ── 形の検査: 事前登録の regime_shape_before_results と同じか（リターンを見る前の約束の再確認）
    shape_chk = []
    reg = pre['regime_shape_before_results']['us']
    for name, spec in RULES.items():
        keys = []
        if spec['signal'] == 'COMBO':
            keys = [('E20_COMBO:REAL', 'REAL'), ('E20_COMBO:DEF', 'DEF')]
        elif name in reg:
            keys = [(name, None)]
        for key, st_ in keys:
            a, z = spans[spec['span_of']]
            fl = hold_flag[spec['signal']]
            f2 = {h: (None if v is None else int(v == st_)) for h, v in fl.items()} if st_ else fl
            for part, (pa, pz) in (('train', (a, TR)), ('hold', (HS, z))):
                e = D.episodes(f2, pa, pz)
                r0 = reg[key][part]
                ok = (e['on'] == r0['regime_months'] and e['months'] == r0['months'] and e['episodes_n'] == r0['episodes'] and e['unknown'] == 0)
                shape_chk.append({'rule': key, 'part': part, 'ok': ok, 'regime_months': e['on'], 'episodes': e['episodes_n']})
                assert ok, (key, part, e, r0)
    res['sanity']['regime_shape_matches_prereg'] = {'checked': len(shape_chk), 'all_ok': all(x['ok'] for x in shape_chk)}
    log('形の検査', len(shape_chk), '件 一致')

    # ── 規則を回す
    entries, runs = {}, {}
    for name, spec in RULES.items():
        a, z = spans[spec['span_of']]
        hm = mrange(a, z)
        fl = hold_flag[spec['signal']]
        assert all(fl.get(h) is not None for h in hm), f'{name}: 期間の中に信号が不明の月がある'
        rr = run_rule(hm, state_fn_of(spec), mem[spec['wt']], fret, mkt, half=spec['half'], record=True)
        # 検査: 局面でない月は市場そのもの・局面の月は組の業種だけ
        for h in hm:
            if rr['states'][h] is None:
                assert rr['rets'][h] == mkt[h]
            else:
                allowed = set(SETS[rr['states'][h]])
                assert set(rr['held'][h]) <= allowed, (name, h)
                assert abs(sum(rr['held'][h].values()) - 1) < 1e-9
        e, net = evaluate(rr['rets'], rr['tos'], mkt, rf, post_pubs=spec['post'],
                          extra_spans={'train_to_1979_12': (None, 197912), 'train_1980_2006': (198001, TR)})
        f01 = flag01(spec)
        e['family'] = spec['family']
        e['spec'] = {'signal': spec['signal'], 'set': spec['sets'] if spec['sets'] else 'INF→REAL／（YC12 か SAHM）→DEF／他は市場',
                     'set_members': SETS[spec['sets']] if spec['sets'] else {'REAL': SETS['REAL'], 'DEF': SETS['DEF']},
                     'weighting': spec['wt'], 'half': spec['half'], 'hold_from': a, 'hold_to': z}
        e['regime_months'] = {'full': regime_counts(rr['states']), 'train': regime_counts(rr['states'], z=TR),
                              'hold': regime_counts(rr['states'], a=HS)}
        e['episodes_shape'] = {part: {'episodes': D.episodes(f01, pa, pz)['episodes_n'], 'regime_months': D.episodes(f01, pa, pz)['on']}
                               for part, pa, pz in (('train', a, TR), ('hold', HS, z))}
        e['exact_t'] = {'full': exact_t(rr['rets'], mkt), 'train': exact_t(rr['rets'], mkt, z=TR), 'hold': exact_t(rr['rets'], mkt, a=HS)}
        e['exact_hold_p_two'] = N.p_two(e['exact_t']['hold'])
        missing = sum(1 for h in hm if rr['states'][h] is not None and len(rr['held'][h]) < len(mem[spec['wt']](rr['states'][h], h)))
        e['missing_hold_months'] = missing
        entries[name] = e
        runs[name] = {'gross': rr['rets'], 'net': net, 'to': rr['tos'], 'states': rr['states'], 'flag01': f01, 'span': (a, z), 'held': rr['held']}
        s = e['stats_gross']
        log(f"{name:22s} full {s['full']['ex_ann']:+.2f} t{s['full']['t']} | train {s['train']['ex_ann']:+.2f} t{s['train']['t']} | hold {s['hold']['ex_ann']:+.2f} t{s['hold']['t']} cagr{s['hold']['cagr_diff']:+.2f}")

    # ── C5（米国外7か国・P1 と P2）
    log('C5: 米国外7か国')
    c5 = {'unit': pre['criteria']['C5_independent_unit'], 'countries': {}}
    repl_of = {}
    c5sig = fz['c5_signals']
    ca, cz = fz['c5_span']
    gsets = {'P1_INF_REAL': ('INF5_r6', SETS['GICS_REAL']), 'P2_YC_DEF': ('YC12', SETS['GICS_DEF'])}
    for c in C5_COUNTRIES:
        g = jkp_gics(c)
        mk = N.jkp_mkt(c, 'vw')
        cc = {'sectors_present': {k: [min(v), max(v), len(v)] for k, v in sorted(g.items())}, 'market_vw': [min(mk), max(mk), len(mk)]}
        for rule, (sg, secs) in gsets.items():
            fl = {add(int(t), 1): v for t, v in c5sig[c][sg].items()}
            hm = [h for h in mrange(ca, cz) if h in mk]
            rets, used, flag_on, unknown = {}, 0, 0, 0
            for h in hm:
                f = fl.get(h)
                if f is None:
                    unknown += 1
                if f == 1:
                    flag_on += 1
                    av = [s for s in secs if s in g and h in g[s]]
                    if av:
                        rets[h] = math.fsum(g[s][h] for s in av) / len(av)
                        used += 1
                        continue
                rets[h] = mk[h]
            ex = N.excess_stats(rets, mk)
            sx = exact_signs(rets, mk)
            testable = used >= 6
            pos = bool(testable and sx and sx[1] > 0)
            cc[rule] = {'hold_months': [hm[0], hm[-1], len(hm)], 'flag_on_months': flag_on, 'months_holding_set': used,
                        'unknown_signal_months': unknown, 'excess_vs_mkt_vw': ex,
                        'exact_geo_diff_pct': sx[1] * 100 if sx else None, 'testable(>=6)': testable, 'positive': pos if testable else None,
                        'episodes': D.episodes({h: (1 if fl.get(h) == 1 else 0) for h in hm}, hm[0], hm[-1])['episodes'],
                        'per_episode': per_episode(rets, mk, {h: (1 if fl.get(h) == 1 else 0) for h in hm}, hm[0], hm[-1])['full']}
        c5['countries'][c] = cc
        log(f'  {c}: ' + ' '.join(f"{r} 局面{cc[r]['months_holding_set']} 差{cc[r]['exact_geo_diff_pct'] if cc[r]['exact_geo_diff_pct'] is None else round(cc[r]['exact_geo_diff_pct'], 3)}" for r in gsets))
    for rule in gsets:
        tst = [c for c in C5_COUNTRIES if c5['countries'][c][rule]['testable(>=6)']]
        pos = [c for c in tst if c5['countries'][c][rule]['positive']]
        passed = (len(pos) / len(tst) >= 2 / 3) if len(tst) >= 3 else None
        c5[f'summary_{rule}'] = {'testable': tst, 'positive': pos, 'pass': passed,
                                 'rule': '検定できる国（局面の月≥6）が3以上 かつ 正の国がその2/3以上。3未満なら N/A'}
        repl_of[rule] = {'regions': len(tst), 'positive': len(pos)} if len(tst) >= 3 else None
    c5['note_japan'] = pre['criteria']['C5_independent_unit']['caveat']
    res['c5'] = c5

    # ── Holm と格付け
    fam_p = {f: N.holm({n: e['exact_hold_p_two'] for n, e in entries.items() if e['family'] == f}) for f in ('primary', 'exploratory')}
    fam_p_r = {f: N.holm({n: e['stats_gross']['hold']['p'] for n, e in entries.items() if e['family'] == f}) for f in ('primary', 'exploratory')}
    for name, e in entries.items():
        st = e['stats_gross']
        repl = repl_of.get(name) if e['family'] == 'primary' else None
        sp = {'train': tuple(e['sharpe']['train']), 'hold': tuple(e['sharpe']['hold'])}
        g, c = N.grade(st['full'], st['train'], st['hold'], e['roll20_net'], e['cost']['net_main']['hold'], repl,
                       fam_p[e['family']].get(name), sp, True)
        if e['family'] == 'primary' and name not in repl_of:
            c['C5_repl'] = None
        e['criteria'] = c
        e['grade'] = g
        e['grade_label'] = g if e['family'] == 'primary' else f'{g}（探索）'
        e['holm_p_in_family'] = fam_p[e['family']].get(name)
        e['holm_p_in_family_from_rounded_p'] = fam_p_r[e['family']].get(name)
        e['c5_repl_used'] = repl if e['family'] == 'primary' else 'N/A（探索は C5 を測らない）'
        if e['family'] == 'primary' and name in ('P3_SAHM_DEF', 'P4_SPF_DEF'):
            e['c5_repl_used'] = 'N/A（事前登録: 実時点の失業率・SPF が各国に無い）'
        ep = e['episodes_shape']
        few = ep['train']['episodes'] < 5 or ep['hold']['episodes'] < 2
        e['few_episodes_flag'] = few
        if few:
            e['few_episodes_note'] = f"局面が少なく偶然と区別しにくい（訓練の塊 {ep['train']['episodes']}・保有の塊 {ep['hold']['episodes']}）"
    # 丸めの境界の検査（格付けは nx_common.grade の丸めた t・符号・Holm は丸める前の p・C4 は丸める前の差）
    rb = []
    for name, e in entries.items():
        st, xt = e['stats_gross'], e['exact_t']
        for crit, part, thr in (('C1_train', 'train', 2.0), ('C3_hold_t', 'hold', 1.65), ('C7_multi(full t)', 'full', 3.0)):
            if st[part] and xt[part] is not None and ((st[part]['t'] or 0) >= thr) != (xt[part] >= thr):
                rb.append({'rule': name, 'criterion': crit, 'rounded_t': st[part]['t'], 'exact_t': xt[part]})
        a_, b_ = e['holm_p_in_family'], e['holm_p_in_family_from_rounded_p']
        if a_ is not None and b_ is not None and (a_ < 0.05) != (b_ < 0.05):
            rb.append({'rule': name, 'criterion': 'C7_multi(Holm)', 'holm_exact_p': a_, 'holm_rounded_p': b_})
        g_, n_ = runs[name]['gross'], runs[name]['net']
        for crit, ser, part, pa, pz in (('C1_train(sign)', g_, 'train', None, TR), ('C2_hold_sign', g_, 'hold', HS, None), ('C6_net_cost', n_, 'hold', HS, None)):
            sx = exact_signs(ser, mkt, pa, pz)
            stp = st[part] if crit != 'C6_net_cost' else e['cost']['net_main']['hold']
            if sx is None or stp is None:
                continue
            if crit.startswith('C1'):
                r_ok, x_ok = stp['ex_ann'] > 0, sx[0] > 0
            else:
                r_ok, x_ok = stp['ex_ann'] > 0 and stp['cagr_diff'] > 0, sx[0] > 0 and sx[1] > 0
            if r_ok != x_ok:
                rb.append({'rule': name, 'criterion': crit, 'rounded': [stp['ex_ann'], stp['cagr_diff']], 'exact_pct': [sx[0] * 100, sx[1] * 100]})
        r20 = e['roll20_net']
        if r20 and (r20['win_rate'] >= 0.8) != (r20['win_rate_nx_common_rounded'] >= 0.8):
            rb.append({'rule': name, 'criterion': 'C4_roll20', 'win_rate_exact': r20['win_rate'], 'win_rate_nx_common_rounded': r20['win_rate_nx_common_rounded']})
    res['sanity']['rounding_boundary_check'] = {'crossings': rb,
                                                'note': '空なら丸めは格付けに影響しない。格付けは Holm を丸める前の p で、C4 の勝ちは丸める前の差で数え（rolling_x）、t と符号は excess_stats の丸めた値（nx_common.grade のまま）で当てた'}

    # ── 局面の塊ごとの符号（主の4本と E1・E2・E20）
    log('塊ごとの符号')
    epi = {}
    for name in ('P1_INF_REAL', 'P2_YC_DEF', 'P3_SAHM_DEF', 'P4_SPF_DEF', 'E1_INF_REAL_early', 'E2_YC_DEF_early'):
        a, z = runs[name]['span']
        epi[name] = per_episode(runs[name]['gross'], mkt, runs[name]['flag01'], a, z)
    a, z = runs['E20_COMBO']['span']
    fl = hold_flag['COMBO']
    for st_ in ('REAL', 'DEF'):
        epi[f'E20_COMBO:{st_}'] = per_episode(runs['E20_COMBO']['gross'], mkt, {h: int(fl[h] == st_) for h in mrange(a, z)}, a, z)
    res['per_episode'] = epi

    # ── 対照（報告のみ）
    log('対照')
    ctrl = {}
    # 無条件に持つ
    for setname, span_of in (('REAL', 'P1_INF_REAL'), ('DEF', 'P2_YC_DEF')):
        for lab, (a, z) in (('span_of_primary', spans[span_of]), ('from_1926_08', (192608, Z))):
            hm = mrange(a, z)
            rr = run_rule(hm, lambda h, s=setname: s, mem['vw'], fret, mkt)
            ev, _ = evaluate(rr['rets'], rr['tos'], mkt, rf)
            ctrl[f'CTRL_static_{setname}_vw:{lab}'] = {'spec': f'{setname} をいつも時価加重で持つ（{fmt(a)}〜{fmt(z)}）', **{k: ev[k] for k in ('stats_gross', 'cost', 'sharpe', 'maxdd', 'roll20_net', 'dca20_net_ratio')}}
    # 局面の条件つきの差（組−市場 を 旗 に回帰）と 現金版
    for name in ('P1_INF_REAL', 'P2_YC_DEF', 'P3_SAHM_DEF', 'P4_SPF_DEF'):
        spec = RULES[name]
        a, z = runs[name]['span']
        hm = mrange(a, z)
        rr_all = run_rule(hm, lambda h, s=spec['sets']: s, mem['vw'], fret, mkt)
        setr = rr_all['rets']
        f01 = runs[name]['flag01']
        cs = {}
        for part, pa, pz in (('full', a, z), ('train', a, TR), ('hold', HS, z)):
            ks = [h for h in hm if pa <= h <= pz]
            y = [setr[h] - mkt[h] for h in ks]
            x = [f01[h] for h in ks]
            b, se = nw_ols(y, x)
            on = [yy for yy, xx in zip(y, x) if xx == 1]
            off = [yy for yy, xx in zip(y, x) if xx == 0]
            cs[part] = {'slope_ann_pct': round(b[1] * 1200, 3), 't_nw12': round(b[1] / se[1], 3),
                        'intercept_ann_pct(off_months)': round(b[0] * 1200, 3),
                        'mean_spread_on_ann_pct': round(float(np.mean(on)) * 1200, 3) if on else None, 'n_on': len(on),
                        'mean_spread_off_ann_pct': round(float(np.mean(off)) * 1200, 3) if off else None, 'n_off': len(off)}
        ctrl[f'COND_SPREAD:{name}'] = {'spec': f'月ごとの（{spec["sets"]} の VW − Mkt）を局面の旗（0/1）に回帰（NW t・ラグ12）', **cs}
        rc = run_rule(hm, state_fn_of(spec), mem['vw'], fret, mkt, cash=rf)
        ev, _ = evaluate(rc['rets'], rc['tos'], mkt, rf)
        ctrl[f'CTRL_regime_cash:{name}'] = {'spec': '局面の月に株を降りて RF（業種の選び方ではなく市場の時期選びの寄与）',
                                            **{k: ev[k] for k in ('stats_gross', 'cost', 'sharpe', 'maxdd', 'roll20_net', 'dca20_net_ratio')}}
        runs[name]['setr_all'] = setr
    # 後知恵
    for key, setname, lab in (('NEVILLE_expost', 'REAL', 'HINDSIGHT_NEVILLE_REAL'), ('NBER_USREC', 'DEF', 'HINDSIGHT_NBER_DEF')):
        hm = mrange(192608, Z)
        f = hind[key]
        rr = run_rule(hm, lambda h, f=f, s=setname: s if f.get(h) == 1 else None, mem['vw'], fret, mkt)
        ev, _ = evaluate(rr['rets'], rr['tos'], mkt, rf)
        ctrl[lab] = {'spec': f'{key} の月そのもの（後知恵＝先読み）に {setname} を持つ。格付けしない',
                     **{k: ev[k] for k in ('stats_gross', 'cost', 'sharpe', 'maxdd')},
                     'per_episode': per_episode(rr['rets'], mkt, {h: f.get(h, 0) for h in hm}, 192608, Z)}
    # 時代の分割（主の4本の訓練）
    ctrl['ERA_SPLIT'] = {n: {'to_1979_12': entries[n]['stats_gross']['train_to_1979_12'], '1980_2006': entries[n]['stats_gross']['train_1980_2006']}
                         for n in ('P1_INF_REAL', 'P2_YC_DEF', 'P3_SAHM_DEF', 'P4_SPF_DEF')}

    # ── 偽の規則（時期・業種）
    log('偽の規則')
    others = [nm for nm in P.names if nm != 'Other']

    def placebo_timing(name):
        a, z = runs[name]['span']
        hm = mrange(a, z)
        L = len(hm)
        f = np.array([runs[name]['flag01'][h] for h in hm])
        sr = np.array([runs[name]['setr_all'][h] for h in hm])
        mk = np.array([mkt[h] for h in hm])
        rng = np.random.default_rng(SEED)
        offs = rng.integers(24, L - 24 + 1, size=NPLACEBO)
        ex_full, cd_full, ex_hold = [], [], []
        hi = np.array([h >= HS for h in hm])
        for k in offs:
            fk = np.roll(f, int(k))
            r = np.where(fk == 1, sr, mk)
            ex_full.append(float(np.mean(r - mk) * 1200))
            cd_full.append((math.exp(np.sum(np.log1p(r)) * 12 / L) - math.exp(np.sum(np.log1p(mk)) * 12 / L)) * 100)
            ex_hold.append(float(np.mean((r - mk)[hi]) * 1200))
        return offs, ex_full, cd_full, ex_hold

    def placebo_industry(name):
        a, z = runs[name]['span']
        hm = mrange(a, z)
        f01 = runs[name]['flag01']
        eps = D.episodes(f01, a, z)['episodes']
        rng = np.random.default_rng(SEED)
        mk = np.array([mkt[h] for h in hm])
        hidx = {h: i for i, h in enumerate(hm)}
        hi = np.array([h >= HS for h in hm])
        ex_full, cd_full, ex_hold = [], [], []
        for _ in range(NPLACEBO):
            r = mk.copy()
            for s, t, _n in eps:
                on = [h for h in mrange(s, t) if f01[h] == 1]
                h0 = on[0]
                ti0, hi0 = P.idx[add(h0, -1)], P.idx[h0]
                cand = [P.nidx[x] for x in others if np.isfinite(P.CAP[ti0, P.nidx[x]]) and P.CAP[ti0, P.nidx[x]] > 0 and np.isfinite(P.R[hi0, P.nidx[x]])]
                pick = rng.choice(cand, size=10, replace=False)
                for h in on:
                    ti, hh = P.idx[add(h, -1)], P.idx[h]
                    ok = [j for j in pick if np.isfinite(P.CAP[ti, j]) and P.CAP[ti, j] > 0 and np.isfinite(P.R[hh, j])]
                    c = P.CAP[ti, ok]
                    r[hidx[h]] = float((c / c.sum()) @ P.R[hh, ok])
            L = len(hm)
            ex_full.append(float(np.mean(r - mk) * 1200))
            cd_full.append((math.exp(np.sum(np.log1p(r)) * 12 / L) - math.exp(np.sum(np.log1p(mk)) * 12 / L)) * 100)
            ex_hold.append(float(np.mean((r - mk)[hi]) * 1200))
        return ex_full, cd_full, ex_hold

    def pct_stats(real, arr):
        arr = np.asarray(arr)
        return {'real': round(real, 3), 'placebo_mean': round(float(arr.mean()), 3), 'placebo_p05': round(float(np.percentile(arr, 5)), 3),
                'placebo_p50': round(float(np.percentile(arr, 50)), 3), 'placebo_p95': round(float(np.percentile(arr, 95)), 3),
                'share_placebo_ge_real': round(float(np.mean(arr >= real)), 3)}
    plac = {}
    for name in ('P1_INF_REAL', 'P2_YC_DEF', 'P3_SAHM_DEF', 'P4_SPF_DEF'):
        g = runs[name]['gross']
        a, z = runs[name]['span']
        hm = mrange(a, z)
        real_ex = float(np.mean([g[h] - mkt[h] for h in hm]) * 1200)
        real_cd = (N.cagr([g[h] for h in hm]) - N.cagr([mkt[h] for h in hm])) * 100
        real_exh = float(np.mean([g[h] - mkt[h] for h in hm if h >= HS]) * 1200)
        o1, t1, t2, t3 = placebo_timing(name)
        o1b, t1b, _, _ = placebo_timing(name)
        assert list(o1) == list(o1b) and t1 == t1b, '偽の時期: 同じ種で再現しない'
        i1, i2, i3 = placebo_industry(name)
        i1b, _, _ = placebo_industry(name)
        assert i1 == i1b, '偽の業種: 同じ種で再現しない'
        plac[name] = {'timing': {'spec': f'持つ月の旗を期間の中で丸ごと巡回ずらし（24〜{len(hm) - 24}か月・{NPLACEBO}回・種 {SEED}）',
                                 'full_ex_ann_pct': pct_stats(real_ex, t1), 'full_cagr_diff_pct': pct_stats(real_cd, t2),
                                 'hold_ex_ann_pct(report)': pct_stats(real_exh, t3), 'reproducible_same_seed': True},
                      'industry': {'spec': f'同じ局面の月に Other 以外のその月にある業種から乱数で10業種（塊ごとに1回選ぶ）を時価加重（{NPLACEBO}回・種 {SEED}）',
                                   'full_ex_ann_pct': pct_stats(real_ex, i1), 'full_cagr_diff_pct': pct_stats(real_cd, i2),
                                   'hold_ex_ann_pct(report)': pct_stats(real_exh, i3), 'reproducible_same_seed': True}}
        log(f"  {name}: 時期 本物 {real_ex:+.2f} 偽の≥本物 {plac[name]['timing']['full_ex_ann_pct']['share_placebo_ge_real']} | 業種 偽の≥本物 {plac[name]['industry']['full_ex_ann_pct']['share_placebo_ge_real']}")
    ctrl['PLACEBO'] = plac
    res['controls_report_only'] = ctrl

    # ── 実在の器（報告のみ）
    log('実在の器')
    real = {}
    yh = {tk: {k: v for k, v in N.yahoo(tk).items() if k <= 202608} for tk in ('SPY', 'VFINX', 'XLE', 'XLB', 'XLP', 'XLV', 'XLU', 'FSENX', 'FSDPX', 'FDFAX', 'FSPHX', 'FSUTX')}
    usg = jkp_gics('usa')
    usm = N.jkp_mkt('usa', 'vw')
    vehicles = {
        'R1_spdr': {'REAL': ['XLE', 'XLB'], 'DEF': ['XLP', 'XLV', 'XLU'], 'bench': 'SPY', 'span': (199902, 202608), 'src': yh},
        'R2_fidelity_select': {'REAL': ['FSENX', 'FSDPX'], 'DEF': ['FDFAX', 'FSPHX', 'FSUTX'], 'bench': 'VFINX', 'span': (198611, 202608), 'src': yh},
        'R3_jkp_us_gics': {'REAL': SETS['GICS_REAL'], 'DEF': SETS['GICS_DEF'], 'bench': None, 'span': (199908, 202512), 'src': usg},
    }
    for vname, v in vehicles.items():
        src = v['src']
        bench = src[v['bench']] if v['bench'] else usm
        rfx = rf if v['bench'] else {k: 0.0 for k in usm}   # JKP は超過なので シャープは RF=0 で

        def memf(st, h, v=v, src=src):
            av = [x for x in v[st] if h in src[x]]
            return {x: 1.0 / len(av) for x in av} if av else None

        def retf(k, h, src=src):
            return src[k].get(h)
        real[vname] = {'members': {'REAL': v['REAL'], 'DEF': v['DEF']}, 'bench': v['bench'] or 'JKP usa mkt vw（超過）',
                       'span': [v['span'][0], v['span'][1]], 'cost': 0.10}
        for name in ('P1_INF_REAL', 'P2_YC_DEF', 'P3_SAHM_DEF', 'P4_SPF_DEF'):
            spec = RULES[name]
            hm = [h for h in mrange(*v['span']) if h in bench]
            assert all(hold_flag[spec['signal']].get(h) is not None for h in hm)
            for h in hm:
                if hold_flag[spec['signal']][h] == 1:
                    assert memf(spec['sets'], h), (vname, name, h)
            rr = run_rule(hm, state_fn_of(spec), memf, retf, bench)
            ev, _ = evaluate(rr['rets'], rr['tos'], bench, rfx)
            real[vname][name] = {k: ev[k] for k in ('span', 'stats_gross', 'cost', 'sharpe', 'maxdd')}
            real[vname][name]['regime_months'] = regime_counts(rr['states'])
            log(f"  {vname} {name}: full {ev['stats_gross']['full']['ex_ann']:+.2f} t{ev['stats_gross']['full']['t']} hold {ev['stats_gross']['hold']['ex_ann'] if ev['stats_gross']['hold'] else None}")
    res['real_instrument_check'] = real

    # ── 出力
    tested = []
    for name, e in entries.items():
        tested.append({'rule': name, **e})
    res['tested'] = tested
    res['summary'] = [{'rule': n, 'family': e['family'], 'grade': e['grade_label'],
                       'train_ex_ann': e['stats_gross']['train']['ex_ann'], 'train_t': e['stats_gross']['train']['t'],
                       'hold_ex_ann': e['stats_gross']['hold']['ex_ann'], 'hold_t': e['stats_gross']['hold']['t'],
                       'hold_cagr_diff': e['stats_gross']['hold']['cagr_diff'],
                       'hold_net010_cagr_diff': e['cost']['net_main']['hold']['cagr_diff'],
                       'full_ex_ann': e['stats_gross']['full']['ex_ann'], 'full_t': e['stats_gross']['full']['t'],
                       'roll20_net_win_rate': e['roll20_net']['win_rate'] if e['roll20_net'] else None,
                       'sharpe_train': e['sharpe']['train'], 'sharpe_hold': e['sharpe']['hold'],
                       'holm_p': e['holm_p_in_family'], 'failed': [c for c, v in e['criteria'].items() if v is False],
                       'few_episodes': e['few_episodes_flag']} for n, e in entries.items()]
    res['grade_counts'] = {f: {g: sum(1 for e in entries.values() if e['family'] == f and e['grade'] == g) for g in 'SABC'} for f in ('primary', 'exploratory')}
    return res, entries, runs, P, mkt, rf, SETS, hold_flag, spans


def post_hoc(res, entries, runs, P, mkt, rf, SETS):
    """結果を見た後の診断（事後・格付けに使わない）。勝った側（保有期間の幾何差が正）の中身を分ける"""
    ph = {'label': '事後（結果を見た後に足した診断・格付けに使わない）', 'items': {}}
    es = N.excess_stats
    winners = [n for n, e in entries.items() if e['stats_gross']['hold'] and e['stats_gross']['hold']['cagr_diff'] > 0]
    ph['rules_with_positive_hold'] = winners
    for name in winners:
        g, f01, (a, z) = runs[name]['gross'], runs[name]['flag01'], runs[name]['span']
        eps = D.episodes(f01, a, z)['episodes']
        loo = []
        for s, t, n in eps:
            g2 = {h: (mkt[h] if s <= h <= t else v) for h, v in g.items()}
            fu, tr, ho = es(g2, mkt), es(g2, mkt, z=TR), es(g2, mkt, a=HS)
            loo.append({'dropped_episode': f'{fmt(s)}〜{fmt(t)}', 'regime_months': n,
                        'full': [fu['ex_ann'], fu['t'], fu['cagr_diff']],
                        'train': [tr['ex_ann'], tr['t'], tr['cagr_diff']] if tr else None,
                        'hold': [ho['ex_ann'], ho['t'], ho['cagr_diff']] if ho else None})
        # 塊を一つずつ抜く（その塊の局面の月を市場に置き換える）。[算術の超過%/年, NW t, 幾何の差%/年]
        # 業種ごとの寄与: 局面の月の Σ w_j (R_j − Mkt)。年率（その期間の全月で割る）
        contrib = {}
        held = runs[name]['held']
        for part, pa, pz in (('full', a, z), ('train', a, TR), ('hold', HS, z)):
            ks = [h for h in mrange(pa, pz)]
            c = {}
            for h in ks:
                if runs[name]['states'][h] is None:
                    continue
                for k, w in held[h].items():
                    r = P.R[P.idx[h], P.nidx[k]]
                    if entries[name]['spec']['half']:
                        w = 0.5 * w
                    c[k] = c.get(k, 0.0) + w * (float(r) - mkt[h])
            contrib[part] = {k: round(v / len(ks) * 1200, 3) for k, v in sorted(c.items(), key=lambda x: -x[1])}
        top = max(eps, key=lambda e: math.fsum(math.log1p(g[h]) - math.log1p(mkt[h]) for h in mrange(e[0], e[1])))
        ph['items'][name] = {'leave_one_episode_out': loo,
                             'industry_contribution_ann_pct(Σ w(R−Mkt)/全月×1200)': contrib,
                             'largest_episode': f'{fmt(top[0])}〜{fmt(top[1])}'}
    # P1 の保有期間の局面（2021-08〜2022-10）の月ごとの中身（どの業種が勝ちを作ったか）
    name = 'P1_INF_REAL'
    rows = []
    for h in mrange(202108, 202210):
        if runs[name]['states'][h] is None:
            continue
        w = runs[name]['held'][h]
        top3 = sorted(w.items(), key=lambda x: -x[1])[:3]
        rows.append({'month': fmt(h), 'rule': round(runs[name]['gross'][h] * 100, 2), 'mkt': round(mkt[h] * 100, 2),
                     'top3_weights': {k: round(v, 3) for k, v in top3},
                     'Oil_ret': round(float(P.R[P.idx[h], P.nidx['Oil']]) * 100, 2)})
    ph['P1_hold_episode_2021_08_2022_10_monthly'] = rows
    # 規則の保有期間の超過のうち、何割が一つの塊から来たか（主の P1 と探索の勝ち側）
    share = {}
    for n in winners:
        g, f01, (a, z) = runs[n]['gross'], runs[n]['flag01'], runs[n]['span']
        tot = math.fsum(math.log1p(g[h]) - math.log1p(mkt[h]) for h in mrange(HS, z))
        eps = D.episodes(f01, HS, z)['episodes']
        share[n] = {f'{fmt(s)}〜{fmt(t)}': round(math.fsum(math.log1p(g[h]) - math.log1p(mkt[h]) for h in mrange(s, t)) / tot, 3) if tot else None
                    for s, t, _ in eps}
    ph['hold_log_excess_share_by_episode'] = {'note': '保有期間の Σlog(1+規則) − Σlog(1+市場) に占める各塊の割合（1を超える＝他の塊が負）', **share}
    return ph


DEVIATIONS = [
    {'item': '回転の起点', 'prereg': '切り替え1回を片道100%',
     'implemented': '期間の前は市場を持っていたとみなし、最初の持つ月が局面ならその月に切り替え1.0を数えた（事前登録は起点を書いていない）',
     'affects_grade': False},
    {'item': '半分だけ傾ける版（E18・E19）の回転', 'prereg': '切り替えは片道50%',
     'implemented': '局面に入る・出る月は 0.5。局面が続く月は、組50%・市場50%へ毎月戻す分（½Σ|0.5w − 流れた重み| と 組/市場の比の戻し）も数えた（事前登録に書いていない細部を最も近い形で）',
     'affects_grade': False},
    {'item': 'C4 の勝ちの数え方', 'prereg': 'nx_common.rolling（転がる窓と積立に中央で直した版があればそれを使う）',
     'implemented': '課題文どおり丸める前の差で勝ちを数える rolling_x（兄弟の角度と同じ）。nx_common の丸めた数え方も併記（wins_nx_common_rounded）。積立の倍率も丸める前（dca_x）。今回は丸めで判定が変わる窓は0（sanity.rounding_boundary_check）',
     'affects_grade': False},
    {'item': 'Holm の p', 'prereg': '両側 p＝nx_common.p_two(NW t)',
     'implemented': '丸める前の NW t から p を作った（excess_stats の p は4桁に丸めてある）。丸めた p の Holm も holm_p_in_family_from_rounded_p に併記',
     'affects_grade': False},
    {'item': 'PLACEBO_timing のずらし方', 'prereg': '持つ月の旗を期間の中で丸ごとずらす（24か月以上・期間の長さ−24か月以下の乱数・塊の形を保つ）',
     'implemented': '期間の中で巡回ずらし（np.roll）。期間の端をまたぐ塊は両端に割れる（それ以外の塊の形は保たれる）。種 20260928 で各規則ごとに新しい乱数列',
     'affects_grade': False},
    {'item': '対照の期間', 'prereg': 'CTRL_static・HINDSIGHT の期間は書いていない',
     'implemented': 'CTRL_static は主の規則の期間（REAL 1947-02〜・DEF 1954-04〜）と 1926-08〜 の両方。HINDSIGHT は 1926-08〜（時価の重みに前月の行が要る最初の月）',
     'affects_grade': False},
    {'item': '実在の器 R3 のシャープ', 'prereg': '—',
     'implemented': 'JKP のリターンは超過なので RF=0 でシャープを計算（相手も超過）', 'affects_grade': False},
    {'item': 'C5 のセクターの有無', 'prereg': '組のセクターが欠けた月はあるセクターだけで等分',
     'implemented': '持つ月 h にリターンのあるセクターで等分（事前登録の文どおり）。一つも無い月・信号が不明の月は市場（超過0）', 'affects_grade': False},
]


if __name__ == '__main__':
    res, entries, runs, P, mkt, rf, SETS, hold_flag, spans = main()
    res['post_hoc'] = post_hoc(res, entries, runs, P, mkt, rf, SETS)
    res['deviations_from_prereg'] = DEVIATIONS
    p1 = entries['P1_INF_REAL']['episodes_shape']
    res['few_episodes_boundary'] = {'P1_INF_REAL': f"保有の塊 {p1['hold']['episodes']}（事前登録の注記の境＝2未満で注記。境ちょうど）。保有の局面は 2008-08〜10（3か月）と 2021-08〜2022-10（15か月）だけ"}
    p = N.save(OUTNAME, res)
    log('書いた', p)
    for r in res['summary']:
        print(r)
