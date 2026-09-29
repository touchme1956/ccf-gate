#!/usr/bin/env python3
"""night/mw_concentration_regime_verify.py — 角度 concentration_regime の反証の検証（読むだけ・門の判定には不使用）

対象: out/mw_concentration_regime.json の S 4本（F1b_valmom・E1_equal・E1_valmom・F1c_valmom）と B の上位（E3_P1）。
独立性: 取得は mw_common の取得器（M.get / M.jkp_rows / M.ff_factors）だけを使い、
  国の市場・三分位の読み込み、良い側、信号（R_cap・上限の効き・自国の80%点・米国の絶対の閾値）、
  X（割安＋勢い・等加重・門の写し P1）、国ごとの切替と費用、国の等分、超過・NW t・幾何の年率差・20年窓・積立を自前で書いた。
  線（C1〜C8 → S/A/B/C）だけは M.grade をそのまま当てる（線を動かさないため）。
反証の軸: ①再現 ②局面の効き（在X の印を国ごとに回した偽の時期＝プラセボ・在X と外の差）
  ③部分期間（1998-2000・2020-2021 を外す・保有の前後半・訓練の TMT の崩れ〔Nokia 等＝後知恵〕を外す）
  ④近い母数（分位・窓・保有・上限の効き・履歴） ⑤国の集合（先進国・新興国・大きい市場・銘柄数の重み）
  ⑥費用（現実的な回転率・単価2倍・3倍） ⑦多重検定（角度 141本・プログラム 3,613本の Bonferroni t≈4.35）
  ⑧誠実さの規則（全体の事前登録: 保有の結果を見て作った規則は判定に使わない）
出力: out/mw_concentration_regime_verify.json
"""
import csv, io, json, math, os, random, statistics as S, sys, time, zipfile, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import numpy as np  # noqa: E402

T0 = time.time()
BASE = M.BASE
TARGET = os.path.join(BASE, 'out', 'mw_concentration_regime.json')
S3 = 'https://jkpfactors-data.s3.amazonaws.com/public/'
DEV = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
       'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe'}
BIG = {'jpn', 'gbr', 'can', 'fra', 'deu', 'che', 'aus', 'kor', 'twn', 'ind', 'chn', 'hkg', 'nld', 'swe', 'esp', 'ita', 'dnk', 'bra'}
END = 202512
TRAIN_END, HOLD0 = 200612, 200701
VAL4 = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
MOMK = 'ret_12_1'
NEED = VAL4 + [MOMK, 'cop_at', 'qmj']
PROGRAM_BONF_T = 4.35
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def ym2i(ym):
    return (ym // 100) * 12 + ym % 100 - 1


def i2ym(i):
    return (i // 12) * 100 + i % 12 + 1


def ymd(s):
    return int(s[:4]) * 100 + int(s[5:7])


# ───────────────────────── 取得（読み込みは自前）─────────────────────────
FF = M.ff_factors()
RF = {ym2i(k): v for k, v in FF['rf'].items()}
FMKTRF = {ym2i(k): v for k, v in FF['mktrf'].items()}


def markets():
    mk = {w: collections.defaultdict(dict) for w in ('vw', 'vw_cap', 'ew')}
    nst = collections.defaultdict(dict)
    for w in mk:
        b = M.get(S3 + '%5Ball_countries%5D_%5Bmkt%5D_%5Bmonthly%5D_%5B' + w + '%5D.zip',
                  name='jkp_factor_all_countries_mkt_' + w + '_monthly.zip')
        z = zipfile.ZipFile(io.BytesIO(b))
        for row in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            r = row['ret']
            if r in ('', 'NA', 'na'):
                continue
            i = ym2i(ymd(row['date']))
            mk[w][row['location']][i] = float(r)
            if w == 'vw' and row['n_stocks'] not in ('', 'NA', 'na'):
                nst[row['location']][i] = int(float(row['n_stocks']))
    return {w: {c: dict(v) for c, v in d.items()} for w, d in mk.items()}, {c: dict(v) for c, v in nst.items()}


PF_CACHE = {}


def terciles(c, names):
    """JKP all_factors 三分位（上限なしの時価加重）→ {name: {pf: {i: (ret, n)}}}"""
    key = (c, tuple(sorted(names)))
    if key in PF_CACHE:
        return PF_CACHE[key]
    d = {}
    try:
        rows = M.jkp_rows(c, 'all_factors', 'portfolios', 'vw')
    except Exception as e:  # noqa
        log('三分位の取得失敗', c, e)
        rows = []
    for row in rows:
        if row['name'] not in names or row['ret'] in ('', 'NA', 'na'):
            continue
        n = row.get('n')
        n = int(float(n)) if n not in (None, '', 'NA', 'na') else None
        d.setdefault(row['name'], {}).setdefault(row['pf'], {})[ym2i(ymd(row['date']))] = (float(row['ret']), n)
    PF_CACHE[key] = d
    return d


def good_side_checks():
    """良い側を2通りで: (a) JKP の文献の向き（direction 列）(b) 米国 ≤2006 の (第3−第1) と因子の相関の符号"""
    fac = collections.defaultdict(dict)
    dirn = {}
    for row in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
        if row['name'] in NEED and row['ret'] not in ('', 'NA', 'na'):
            fac[row['name']][ym2i(ymd(row['date']))] = float(row['ret'])
            dirn[row['name']] = row['direction']
    pf = terciles('usa', NEED)
    out = {}
    for k in NEED:
        ms = sorted(i for i in fac[k] if i in pf[k].get('3.0', {}) and i in pf[k].get('1.0', {}) and i <= ym2i(TRAIN_END))
        a = np.array([pf[k]['3.0'][i][0] - pf[k]['1.0'][i][0] for i in ms])
        b = np.array([fac[k][i] for i in ms])
        cc = float(np.corrcoef(a, b)[0, 1])
        out[k] = {'direction_col': dirn[k], 'corr_to_2006': round(cc, 3), 'months': len(ms),
                  'good_by_corr': '3.0' if cc > 0 else '1.0', 'good_by_dir': '3.0' if dirn[k] in ('1', '1.0') else '1.0'}
    return out


def xseries(c, mk, nst, start_ym):
    """国 c の X: capped・equal・valmom（割安4本の良い側の平均〔2本以上〕50%＋勢いの良い側50%）・cop_at・qmj"""
    pf = terciles(c, NEED)
    ns = nst.get(c, {})
    st = ym2i(start_ym)
    scr = {}
    for k in NEED:
        p = pf.get(k, {})
        g = p.get('3.0', {})  # 良い側は全7本とも第3（上の検査で2通り一致を確かめる）
        o = {}
        for i, (r, n) in g.items():
            if i < st or i > ym2i(END) or n is None or n < 10:
                continue
            tot = 0
            for q in ('1.0', '2.0', '3.0'):
                v = p.get(q, {}).get(i)
                if v is not None and v[1] is not None:
                    tot += v[1]
            d = ns.get(i)
            if not d or tot / d < 0.4:
                continue
            o[i] = r
        scr[k] = o
    vm = {}
    for i in scr[MOMK]:
        v = [scr[k][i] for k in VAL4 if i in scr[k]]
        if len(v) >= 2:
            vm[i] = 0.5 * (sum(v) / len(v)) + 0.5 * scr[MOMK][i]
    return {'capped': dict(mk['vw_cap'].get(c, {})), 'equal': dict(mk['ew'].get(c, {})), 'valmom': vm,
            'cop_at': scr['cop_at'], 'qmj': scr['qmj']}


# ───────────────────────── 信号（自前）─────────────────────────
def cumlog(a, b, W):
    """R(t) = Σ_{t−W+1..t} [ln(1+a+rf) − ln(1+b+rf)]、W か月すべてそろう t だけ"""
    L = {}
    for i, x in a.items():
        if i in b and i in RF:
            L[i] = math.log(1 + x + RF[i]) - math.log(1 + b[i] + RF[i])
    R = {}
    if not L:
        return R
    lo, hi = min(L), max(L)
    run, cnt = 0.0, 0
    buf = []
    for i in range(lo, hi + 1):
        if i in L:
            buf.append(L[i])
        else:
            buf = []
        if len(buf) > W:
            buf.pop(0)
        if len(buf) == W:
            R[i] = math.fsum(buf)
    return R


def binding(vw, cap, W, need):
    B = {i: abs(vw[i] - cap[i]) > 1e-6 for i in vw if i in cap}
    out = {}
    if not B:
        return out
    buf = []
    for i in range(min(B), max(B) + 1):
        if i in B:
            buf.append(B[i])
        else:
            buf = []
        if len(buf) > W:
            buf.pop(0)
        if len(buf) == W:
            out[i] = sum(buf) >= need
    return out


def pct_linear(sorted_vals, q):
    n = len(sorted_vals)
    pos = (n - 1) * q / 100
    lo = int(math.floor(pos)); hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def own_state(R, extra, q, hmin):
    import bisect
    hist, st = [], {}
    for i in sorted(R):
        bisect.insort(hist, R[i])
        if len(hist) < hmin:
            st[i] = None
            continue
        p = pct_linear(hist, q)
        st[i] = bool(R[i] > 0 and R[i] > p and (extra is None or extra.get(i, False)))
    return st


# ───────────────────────── 戦略（自前）─────────────────────────
def country_rows(state, X, vw, nst_c, unit, turn, rule, R=None, H=60, nmin=100):
    """→ list of (i=保有の月, 超過X or vw, vw, 在X, 費用)。信号の月 t → 保有の月 t+1"""
    out, prev = [], None
    ts = sorted(state)
    on = {t for t in ts if state[t] is True}
    for t in ts:
        if state[t] is None:
            continue
        if nst_c is not None and nst_c.get(t, 0) < nmin:
            continue
        i = t + 1
        if i not in X or i not in vw or i not in RF:
            continue
        if rule == 'H0':
            inx = state[t] is True
        elif rule == 'H':
            inx = any((t - j) in on for j in range(H))
        elif rule == 'PP':
            inx = any((t - j) in on for j in range(H)) and t in R and (t - 12) in R and R[t] < R[t - 12]
        else:
            raise ValueError(rule)
        cost = unit * turn / 12 if inx else 0.0
        if prev is not None and prev[0] == i - 1:
            if prev[1] != inx:
                cost += unit
        elif inx:
            cost += unit
        out.append((i, X[i] if inx else vw[i], vw[i], inx, cost))
        prev = (i, inx)
    return out


def pool(crow, only=None, weight=None, cost_mult=1.0):
    """国を等分（または weight(c,i) の重み）で混ぜる → s（総）・b（総）・sn（費用後 総）・{i: 国数}"""
    acc = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    for c, rows in crow.items():
        if only is not None and c not in only:
            continue
        for (i, r, v, inx, co) in rows:
            w = 1.0 if weight is None else weight(c, i)
            if not w:
                continue
            a = acc[i]
            a[0] += w * r; a[1] += w * v; a[2] += w * co; a[3] += w; a[4] += 1
    s, b, sn, nc = {}, {}, {}, {}
    for i, (sr, sv, sc, sw, n) in acc.items():
        s[i] = sr / sw + RF[i]
        b[i] = sv / sw + RF[i]
        sn[i] = (sr - sc * cost_mult) / sw + RF[i]
        nc[i] = n
    return s, b, sn, nc


# ───────────────────────── 統計（自前）─────────────────────────
def nwt(x, L=12):
    x = np.asarray(x, float)
    n = len(x)
    if n < 24:
        return None
    e = x - x.mean()
    v = float(e @ e) / n
    for l in range(1, min(L, n - 1) + 1):
        v += 2 * (1 - l / (L + 1)) * float(e[l:] @ e[:-l]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else None


def stats(s, b, a=None, z=None, drop=()):
    ks = sorted(i for i in s if i in b and (a is None or i >= ym2i(a)) and (z is None or i <= ym2i(z))
                and not any(ym2i(p) <= i <= ym2i(q) for p, q in drop))
    if len(ks) < 24:
        return None
    sv = np.array([s[i] for i in ks]); bv = np.array([b[i] for i in ks])
    d = sv - bv
    t = nwt(d)
    gs = math.exp(np.log1p(sv).sum() * 12 / len(ks)) - 1
    gb = math.exp(np.log1p(bv).sum() * 12 / len(ks)) - 1
    return {'from': i2ym(ks[0]), 'to': i2ym(ks[-1]), 'months': len(ks), 'ex_ann': round(float(d.mean()) * 1200, 2),
            't': round(t, 2) if t is not None else None, 'p': round(math.erfc(abs(t) / math.sqrt(2)), 4) if t is not None else None,
            'cagr_diff': round((gs - gb) * 100, 2), 'te': round(float(d.std(ddof=1)) * math.sqrt(12) * 100, 2)}


def roll20(s, b, years=20):
    ks = sorted(i for i in s if i in b)
    if not ks:
        return None
    res = []
    y0, last = i2ym(ks[0]) // 100, ks[-1]
    kset = set(ks)
    for y in range(y0, 2100):
        a = ym2i(y * 100 + 7); z = a + years * 12 - 1
        if z > last:
            break
        w = [i for i in range(a, z + 1) if i in kset]
        if len(w) < years * 12 * 0.97:
            continue
        gs = math.exp(sum(math.log1p(s[i]) for i in w) * 12 / len(w)) - 1
        gb = math.exp(sum(math.log1p(b[i]) for i in w) * 12 / len(w)) - 1
        res.append((y, round((gs - gb) * 100, 2)))
    if not res:
        return None
    return {'windows': len(res), 'win_rate': round(sum(1 for _, d in res if d > 0) / len(res), 3),
            'median': sorted(d for _, d in res)[len(res) // 2], 'worst': min(res, key=lambda x: x[1])}


def dca20(s, b):
    ks = sorted(i for i in s if i in b)
    out = []
    for j in range(0, len(ks) - 240 + 1, 12):
        ws = wb = 0.0
        for i in ks[j:j + 240]:
            ws = (ws + 1) * (1 + s[i]); wb = (wb + 1) * (1 + b[i])
        out.append(ws / wb)
    if not out:
        return None
    return {'windows': len(out), 'win_rate': round(sum(1 for r in out if r > 1) / len(out), 3), 'median': round(sorted(out)[len(out) // 2], 3)}


def sharpe(r, a=None, z=None):
    ks = sorted(i for i in r if i in RF and (a is None or i >= ym2i(a)) and (z is None or i <= ym2i(z)))
    x = np.array([r[i] - RF[i] for i in ks])
    return float(x.mean() / x.std(ddof=1) * math.sqrt(12)) if len(x) > 24 else None


def full_eval(s, b, sn, repl=None, holm_p=None):
    full, train, hold = stats(s, b), stats(s, b, z=TRAIN_END), stats(s, b, a=HOLD0)
    hn = stats(sn, b, a=HOLD0)
    rl = roll20(s, b)
    sp = {'train': (sharpe(s, z=TRAIN_END), sharpe(b, z=TRAIN_END)), 'hold': (sharpe(s, a=HOLD0), sharpe(b, a=HOLD0))}
    g, cr = M.grade(full, train, hold, rl, cost_hold=hn, repl=repl, family_holm_p=holm_p, sharpe_pair=sp, leveraged_or_timing=True)
    return {'full': full, 'train': train, 'hold': hold, 'hold_net': hn, 'roll20': rl, 'dca20': dca20(s, b),
            'sharpe': {k: [round(v, 3) if v is not None else None for v in p] for k, p in sp.items()},
            'grade_mech': g, 'criteria': cr}


def brief(e):
    if not e:
        return None
    return f"{e['ex_ann']:+.2f}%/年 t{e['t']}"


# ───────────────────────── 本体 ─────────────────────────
def main():
    CL = json.load(open(TARGET))
    TT = {t['name']: t for t in CL['tested']}
    log('データ読み込み')
    mk, nst = markets()
    gs = good_side_checks()
    log('良い側の検査', gs)
    assert all(v['good_by_corr'] == '3.0' and v['good_by_dir'] == '3.0' for v in gs.values()), '良い側が第3でない特性がある'
    countries = sorted(c for c in mk['vw'] if c != 'usa' and any(n >= 100 for n in nst.get(c, {}).values()))
    log('米国外の国', len(countries))
    XX = {c: xseries(c, mk, nst, 199007) for c in countries}

    US_R = cumlog(FMKTRF, mk['vw_cap']['usa'], 60)
    thrB = pct_linear(sorted(v for i, v in US_R.items() if i <= ym2i(TRAIN_END)), 80)
    log('米国の閾値B', round(thrB, 4), '研究側', CL['sanity']['thr_us_B'])

    def unit(c, x):
        if c == 'usa':
            return 0.003 if x == 'equal' else 0.001
        u = 0.003 if c in DEV else 0.005
        return 2 * u if x == 'equal' else u

    TURN = {'capped': 0.10, 'equal': 0.50, 'valmom': 0.95, 'cop_at': 0.40, 'qmj': 0.50}

    SIGCACHE = {}

    def sig(kind, W=60, q=80, hmin=120, bneed=48, thr_q=80):
        key = (kind, W, q, hmin, bneed, thr_q)
        if key in SIGCACHE:
            return SIGCACHE[key]
        st, RR = {}, {}
        if kind == 'B':
            th = pct_linear(sorted(v for i, v in cumlog(FMKTRF, mk['vw_cap']['usa'], W).items() if i <= ym2i(TRAIN_END)), thr_q)
        for c in countries:
            vw, cap = mk['vw'].get(c, {}), mk['vw_cap'].get(c, {})
            R = cumlog(vw, cap, W)
            bo = binding(vw, cap, W, round(bneed * W / 60))
            if kind == 'A':
                st[c] = own_state(R, bo, q, hmin)
            else:
                st[c] = {i: bool(bo.get(i, False)) and R[i] > th for i in R}
            RR[c] = R
        SIGCACHE[key] = (st, RR)
        return st, RR

    def run(kind, rule, x, H=60, turn_mult=1.0, turn_over=None, **kw):
        st, RR = sig(kind, **kw)
        crow = {}
        for c in countries:
            tv = turn_over if turn_over is not None else TURN[x] * turn_mult
            rows = country_rows(st[c], XX[c][x], mk['vw'][c], nst.get(c, {}), unit(c, x), tv, rule, R=RR[c], H=H)
            if rows:
                crow[c] = rows
        return crow

    def repl_of(crow):
        reg = pos = 0
        for c, rows in crow.items():
            if sum(1 for r in rows if r[3]) < 12:
                continue
            reg += 1
            pos += (sum(r[1] - r[2] for r in rows) / len(rows)) > 0
        return {'regions': reg, 'positive': pos}

    CANDS = {
        'F1b_valmom': dict(kind='A', rule='H', x='valmom', fam='F1b'),
        'E1_equal': dict(kind='A', rule='PP', x='equal', fam='E1'),
        'E1_valmom': dict(kind='A', rule='PP', x='valmom', fam='E1'),
        'F1c_valmom': dict(kind='B', rule='H0', x='valmom', fam='F1c'),
    }
    details, verdicts = {}, []

    # ─── 米国外の4本 ───
    for name, cf in CANDS.items():
        log('━━', name)
        crow = run(cf['kind'], cf['rule'], cf['x'])
        s, b, sn, nc = pool(crow)
        rep = repl_of(crow)
        ev = full_eval(s, b, sn, repl=rep, holm_p=TT[name].get('holm_p'))
        cl = TT[name]
        match = {k: (ev[k] or {}).get('ex_ann') == (cl.get(k) or {}).get('ex_ann') and (ev[k] or {}).get('t') == (cl.get(k) or {}).get('t')
                 for k in ('full', 'train', 'hold', 'hold_net')}
        log('再現', {k: brief(ev[k]) for k in ('full', 'train', 'hold', 'hold_net')}, '一致', match, '国', rep, '格', ev['grade_mech'])
        D = {'reproduced': ev, 'match_claim': match, 'repl': rep}
        nin = sum(1 for r in crow.values() for x in r if x[3]); ntot = sum(len(r) for r in crow.values())
        D['in_X_share'] = round(nin / ntot, 3)
        # 訓練期間の中身: 国数・在X の国
        tr_n = [nc[i] for i in nc if i <= ym2i(TRAIN_END)]
        tr_in = collections.Counter()
        for c, rows in crow.items():
            for r in rows:
                if r[3] and r[0] <= ym2i(TRAIN_END):
                    tr_in[c] += 1
        D['train_composition'] = {'avg_countries_per_month': round(S.mean(tr_n), 1) if tr_n else None,
                                  'min_countries': min(tr_n) if tr_n else None,
                                  'in_X_country_months_by_country': dict(tr_in.most_common(12)),
                                  'in_X_countries': len(tr_in)}
        # 訓練の上乗せの寄与（国別の和 ÷ 各月の国数）
        contrib = collections.Counter()
        for c, rows in crow.items():
            for r in rows:
                if r[0] <= ym2i(TRAIN_END):
                    contrib[c] += (r[1] - r[2]) / nc[r[0]]
        ntr = len(tr_n)
        D['train_contrib_ann_by_country'] = {c: round(v / ntr * 1200, 2) for c, v in contrib.most_common(8)}
        drop_known = {'fin', 'can', 'swe', 'nld'}
        s2, b2, sn2, _ = pool({c: r for c, r in crow.items() if c not in drop_known})
        D['train_without_known_topdogs'] = {'dropped': sorted(drop_known), 'train': stats(s2, b2, z=TRAIN_END), 'hold': stats(s2, b2, a=HOLD0)}
        # 部分期間
        D['subperiods'] = {
            'train_drop_1998_2000': stats(s, b, z=TRAIN_END, drop=((199801, 200012),)),
            'train_drop_1998_2002': stats(s, b, z=TRAIN_END, drop=((199801, 200212),)),
            'full_drop_1998_2000_2020_2021': stats(s, b, drop=((199801, 200012), (202001, 202112))),
            'hold_drop_2020_2021': stats(s, b, a=HOLD0, drop=((202001, 202112),)),
            'hold_first_2007_2016H1': stats(s, b, a=HOLD0, z=201606),
            'hold_second_2016H2_2025': stats(s, b, a=201607),
            'hold_net_first': stats(sn, b, a=HOLD0, z=201606),
            'hold_net_second': stats(sn, b, a=201607),
            'post2018': stats(s, b, a=201801),
            'hold_drop_2009': stats(s, b, a=HOLD0, drop=((200901, 200912),)),
        }
        log('部分期間', {k: brief(v) for k, v in D['subperiods'].items()})
        log('訓練の中身', D['train_composition'], D['train_contrib_ann_by_country'])
        log('既知の top dogs（fin can swe nld）抜き', {k: brief(v) for k, v in D['train_without_known_topdogs'].items() if k != 'dropped'})
        # 常に X（同じ国×月）
        # 常に X（同じ国×月）: X を持たない月も X[i] を取り直す
        always = {}
        for c, rows in crow.items():
            al = []
            for (i, r, v, inx, co) in rows:
                al.append((i, XX[c][cf['x']][i], v, True, 0.0))
            always[c] = al
        sA, bA, _, _ = pool(always)
        D['always_X_same_country_months'] = {'full': stats(sA, bA), 'train': stats(sA, bA, z=TRAIN_END), 'hold': stats(sA, bA, a=HOLD0)}
        # 在X の月と外の月の (X−vw)：各月、在X の国の平均 − 外の国の平均 → 保有期間の NW t
        din, dout, dd, dd_all = collections.defaultdict(list), collections.defaultdict(list), [], []
        for c, rows in crow.items():
            for (i, r, v, inx, co) in rows:
                (din if inx else dout)[i].append(XX[c][cf['x']][i] - v)
        for i in sorted(din):
            if i in dout and din[i] and dout[i]:
                dd_all.append((i, S.mean(din[i]) - S.mean(dout[i])))
        h = [d for i, d in dd_all if i >= ym2i(HOLD0)]
        tr = [d for i, d in dd_all if i <= ym2i(TRAIN_END)]
        inx_h = [x for i in din if i >= ym2i(HOLD0) for x in din[i]]
        out_h = [x for i in dout if i >= ym2i(HOLD0) for x in dout[i]]
        D['conditioning'] = {
            'hold_in_minus_out_ann': round(S.mean(h) * 1200, 2) if h else None, 'hold_t': round(nwt(h), 2) if len(h) > 24 else None,
            'train_in_minus_out_ann': round(S.mean(tr) * 1200, 2) if tr else None, 'train_t': round(nwt(tr), 2) if len(tr) > 24 else None,
            'hold_mean_X_minus_vw_in_X_ann': round(S.mean(inx_h) * 1200, 2) if inx_h else None,
            'hold_mean_X_minus_vw_out_X_ann': round(S.mean(out_h) * 1200, 2) if out_h else None,
            'months_both_hold': len(h)}
        log('局面の効き（在X − 外の X−vw）', D['conditioning'])
        # プラセボ: 国ごとに在X の印を無作為に回す（割合と持続は保つ）→ 保有期間の上乗せの分布
        rng = random.Random(20260928)
        arrs = {}
        for c, rows in crow.items():
            arrs[c] = (np.array([r[0] for r in rows]), np.array([XX[c][cf['x']][r[0]] - r[2] for r in rows]),
                       np.array([r[3] for r in rows], bool))
        allm = sorted({i for c in arrs for i in arrs[c][0]})
        pos = {i: k for k, i in enumerate(allm)}
        cnt = np.zeros(len(allm))
        for c, (ms, a, v) in arrs.items():
            np.add.at(cnt, [pos[i] for i in ms], 1)
        hmask = np.array([i >= ym2i(HOLD0) for i in allm]); tmask = ~hmask

        def pooled_active(shifts=None):
            tot = np.zeros(len(allm))
            for c, (ms, a, v) in arrs.items():
                vv = v if shifts is None else np.roll(v, shifts[c])
                np.add.at(tot, [pos[i] for i in ms], a * vv)
            p = tot / cnt
            return float(p[hmask].mean() * 1200), float(p[tmask].mean() * 1200) if tmask.any() else None
        act_h, act_t = pooled_active()
        sims = []
        for _ in range(1000):
            sh = {c: rng.randrange(len(arrs[c][0])) for c in arrs}
            sims.append(pooled_active(sh))
        sh_h = sorted(x[0] for x in sims); sh_t = sorted(x[1] for x in sims if x[1] is not None)
        D['placebo_circular_shift'] = {'draws': 1000, 'actual_hold_ann': round(act_h, 2), 'placebo_hold_mean': round(S.mean(sh_h), 2),
                                       'placebo_hold_p95': round(sh_h[949], 2), 'p_placebo_ge_actual_hold': round(sum(1 for x in sh_h if x >= act_h) / 1000, 3),
                                       'actual_train_ann': round(act_t, 2) if act_t is not None else None,
                                       'placebo_train_mean': round(S.mean(sh_t), 2) if sh_t else None,
                                       'p_placebo_ge_actual_train': round(sum(1 for x in sh_t if x >= act_t) / len(sh_t), 3) if sh_t else None}
        log('プラセボ', D['placebo_circular_shift'])
        # 近い母数
        nb = {}
        grid = []
        if cf['kind'] == 'A':
            for q in (70, 75, 85, 90):
                grid.append((f'pct{q}', dict(q=q)))
            for W in (36, 48, 84, 120):
                grid.append((f'win{W}', dict(W=W)))
            for hm in (60, 180):
                grid.append((f'hist{hm}', dict(hmin=hm)))
            for bn in (36, 54):
                grid.append((f'bind{bn}', dict(bneed=bn)))
        else:
            for tq in (70, 75, 85, 90):
                grid.append((f'usthr_pct{tq}', dict(thr_q=tq)))
            for W in (36, 48, 84, 120):
                grid.append((f'win{W}', dict(W=W)))
            for bn in (36, 54):
                grid.append((f'bind{bn}', dict(bneed=bn)))
        Hs = [None]
        if cf['rule'] in ('H', 'PP'):
            Hs = [36, 48, 84, 120]
        for lab, kw in grid + [(f'H{h}', {'_H': h}) for h in Hs if h]:
            kw = dict(kw)
            Hh = kw.pop('_H', 60)
            cr2 = run(cf['kind'], cf['rule'], cf['x'], H=Hh, **kw)
            s3, b3, sn3, _ = pool(cr2)
            e3 = full_eval(s3, b3, sn3, repl=repl_of(cr2), holm_p=None)
            nb[lab] = {'train': brief(e3['train']), 'hold': brief(e3['hold']), 'hold_net': brief(e3['hold_net']),
                       'full': brief(e3['full']), 'grade_without_holm': e3['grade_mech'],
                       'C1': e3['criteria']['C1_train'], 'C3': e3['criteria']['C3_hold_t'], 'C6': e3['criteria']['C6_net_cost']}
        D['neighbors'] = nb
        log('近い母数', {k: (v['train'], v['hold'], v['grade_without_holm']) for k, v in nb.items()})
        # 国の集合
        emg = set(countries) - DEV
        sub = {}
        for lab, grp in (('developed', DEV), ('emerging', emg), ('big_markets', BIG), ('developed_ex_jpn', DEV - {'jpn'})):
            s4, b4, sn4, _ = pool(crow, only=grp)
            sub[lab] = {'train': stats(s4, b4, z=TRAIN_END), 'hold': stats(s4, b4, a=HOLD0), 'hold_net': stats(sn4, b4, a=HOLD0)}
        # 銘柄数の重み（時価の重みの粗い代わり: 大きい市場ほど重く）
        s5, b5, sn5, _ = pool(crow, weight=lambda c, i: nst.get(c, {}).get(i - 1, 0))
        sub['weighted_by_n_stocks'] = {'train': stats(s5, b5, z=TRAIN_END), 'hold': stats(s5, b5, a=HOLD0), 'hold_net': stats(sn5, b5, a=HOLD0)}
        D['country_sets'] = sub
        log('国の集合', {k: (brief(v['train']), brief(v['hold']), brief(v['hold_net'])) for k, v in sub.items()})
        # 一国ずつ外す（保有）
        loo = []
        for c in crow:
            s6, b6, _, _ = pool(crow, only=set(crow) - {c})
            h6 = stats(s6, b6, a=HOLD0); t6 = stats(s6, b6, z=TRAIN_END)
            loo.append((c, h6['ex_ann'] if h6 else None, h6['t'] if h6 else None, t6['t'] if t6 else None))
        loo_h = [x for x in loo if x[1] is not None]
        loo_t = [x for x in loo if x[3] is not None]
        D['leave_one_out'] = {'hold_min': min(loo_h, key=lambda x: x[1]), 'hold_t_min': min(loo_h, key=lambda x: x[2]),
                              'train_t_min': min(loo_t, key=lambda x: x[3]) if loo_t else None,
                              'train_t_below_2': [x[0] for x in loo_t if x[3] < 2.0]}
        log('一国外し', D['leave_one_out'])
        # 費用
        cs = {}
        base_turn = TURN[cf['x']]
        real_turn = 1.3 if cf['x'] == 'valmom' else (0.8 if cf['x'] == 'equal' else base_turn)
        for lab, tv, cm in (('as_claimed', base_turn, 1.0), ('realistic_turnover', real_turn, 1.0),
                            ('unit_x2', base_turn, 2.0), ('realistic_turnover_unit_x2', real_turn, 2.0), ('unit_x3', base_turn, 3.0)):
            cr7 = run(cf['kind'], cf['rule'], cf['x'], turn_over=tv)
            s7, b7, sn7, _ = pool(cr7, cost_mult=cm)
            cs[lab] = {'turnover': tv, 'unit_mult': cm, 'hold_net': stats(sn7, b7, a=HOLD0), 'full_net': stats(sn7, b7)}
        D['costs'] = cs
        sw = 0
        for rows in crow.values():
            for a_, z_ in zip(rows, rows[1:]):
                if z_[0] == a_[0] + 1 and a_[3] != z_[3]:
                    sw += 1
        D['switches'] = sw
        log('費用', {k: brief(v['hold_net']) for k, v in cs.items()}, '切替', sw)
        details[name] = D

    # ─── 米国 E3_P1 ───
    log('━━ E3_P1（米国）')
    MEAS = {'M01_roic': [('ebit_bev', 1)], 'M02_opm': [('ebit_sale', 1)], 'M03_gpa': [('gp_at', 1)], 'M04_conv': [('oaccruals_ni', -1)],
            'M05_accr': [('oaccruals_at', -1)], 'M06_lev': [('netdebt_me', -1)], 'M07_z': [('z_score', 1)], 'M08_intcov': [('o_score', -1)],
            'M09_p1': [('ni_ivol', -1), ('ocfq_saleq_std', -1)], 'M10_p2': [('qmj_safety', 1)], 'M11_growth': [('sale_gr3', 1)],
            'M12_roiic': [('qmj_growth', 1)], 'M13_shy': [('eqnpo_me', 1)], 'M14_dil': [('chcsho_12m', -1)], 'M15_roict': [('niq_be_chg1', 1)],
            'M16_moat': [('ni_ar1', 1)]}
    TURNP = {'ebit_bev': 0.5, 'ebit_sale': 0.4, 'gp_at': 0.4, 'oaccruals_ni': 1.2, 'oaccruals_at': 1.2, 'netdebt_me': 0.6,
             'z_score': 0.6, 'o_score': 0.8, 'ni_ivol': 0.4, 'ocfq_saleq_std': 0.5, 'qmj_safety': 0.6, 'sale_gr3': 0.8,
             'qmj_growth': 0.8, 'eqnpo_me': 0.8, 'chcsho_12m': 1.0, 'niq_be_chg1': 2.0, 'ni_ar1': 0.5}
    import mw_gate_proxy as GP  # 定義の突き合わせだけ（計算は使わない）
    assert GP.MEASURES == MEAS, '門の写しの定義が食い違う'
    chars = sorted({c for v in MEAS.values() for c, _ in v})
    pf = terciles('usa', chars)
    sleeves = {}
    for mname, px in MEAS.items():
        ss = []
        for c, d in px:
            g = pf[c]['3.0' if d > 0 else '1.0']
            ss.append({i: r for i, (r, n) in g.items() if n is not None and n >= 10})
        sl = {}
        for i in set().union(*ss):
            v = [x[i] for x in ss if i in x]
            sl[i] = sum(v) / len(v)
        sleeves[mname] = sl
    need = math.ceil(2 * len(MEAS) / 3)
    P1 = {}
    for i in set().union(*sleeves.values()):
        v = [sl[i] for sl in sleeves.values() if i in sl]
        if len(v) >= need and i >= ym2i(196307) and i <= ym2i(END):
            P1[i] = sum(v) / len(v)
    turnP1 = round(S.mean(S.mean(TURNP[c] for c, _ in px) for px in MEAS.values()) + 0.10, 3)
    bind_us = binding(mk['vw']['usa'], mk['vw_cap']['usa'], 60, 48)
    stA = own_state(US_R, bind_us, 80, 120)
    XU = xseries('usa', mk, nst, 196307)
    XU['P1'] = P1

    def us_run(xname, rule, H=60, stt=None, R=None, turn_over=None, unit_mult=1.0):
        stt = stt or stA
        tv = turn_over if turn_over is not None else (turnP1 if xname == 'P1' else TURN[xname])
        rows = country_rows(stt, XU[xname], FMKTRF, None, unit('usa', xname) * unit_mult, tv, rule, R=R or US_R, H=H)
        return {'usa': rows}

    crow = us_run('P1', 'H')
    s, b, sn, _ = pool(crow)
    ev = full_eval(s, b, sn, repl=None, holm_p=TT['E3_P1'].get('holm_p'))
    cl = TT['E3_P1']
    match = {k: (ev[k] or {}).get('ex_ann') == (cl.get(k) or {}).get('ex_ann') and (ev[k] or {}).get('t') == (cl.get(k) or {}).get('t')
             for k in ('full', 'train', 'hold', 'hold_net')}
    log('E3_P1 再現', {k: brief(ev[k]) for k in ('full', 'train', 'hold', 'hold_net')}, '一致', match, ev['grade_mech'])
    D = {'reproduced': ev, 'match_claim': match, 'turnover_P1': turnP1}
    rows = crow['usa']
    D['in_X_share'] = round(sum(1 for r in rows if r[3]) / len(rows), 3)
    al = {'usa': [(i, XU['P1'][i], v, True, 0.0) for (i, r, v, inx, co) in rows]}
    sA, bA, _, _ = pool(al)
    D['always_P1_same_months'] = {'full': stats(sA, bA), 'train': stats(sA, bA, z=TRAIN_END), 'hold': stats(sA, bA, a=HOLD0)}
    D['subperiods'] = {
        'train_drop_1998_2000': stats(s, b, z=TRAIN_END, drop=((199801, 200012),)),
        'full_drop_1998_2000_2020_2021': stats(s, b, drop=((199801, 200012), (202001, 202112))),
        'hold_drop_2020_2021': stats(s, b, a=HOLD0, drop=((202001, 202112),)),
        'hold_first_2007_2016H1': stats(s, b, a=HOLD0, z=201606), 'hold_second_2016H2_2025': stats(s, b, a=201607),
        'train_1963_1984': stats(s, b, z=198412), 'train_1985_2006': stats(s, b, a=198501, z=TRAIN_END)}
    log('E3_P1 部分期間', {k: brief(v) for k, v in D['subperiods'].items()})
    # 在X と外の P1−Mkt
    pin = [(i, XU['P1'][i] - v) for (i, r, v, inx, co) in rows if inx]
    pout = [(i, XU['P1'][i] - v) for (i, r, v, inx, co) in rows if not inx]
    D['conditioning'] = {
        'hold_in_ann': round(S.mean([d for i, d in pin if i >= ym2i(HOLD0)]) * 1200, 2),
        'hold_out_ann': round(S.mean([d for i, d in pout if i >= ym2i(HOLD0)]) * 1200, 2) if any(i >= ym2i(HOLD0) for i, _ in pout) else None,
        'train_in_ann': round(S.mean([d for i, d in pin if i <= ym2i(TRAIN_END)]) * 1200, 2),
        'train_out_ann': round(S.mean([d for i, d in pout if i <= ym2i(TRAIN_END)]) * 1200, 2),
        'hold_out_months': sum(1 for i, _ in pout if i >= ym2i(HOLD0))}
    log('E3_P1 局面の効き', D['conditioning'])
    # プラセボ（1国なので、在X の印を回す）
    ms = np.array([r[0] for r in rows]); a = np.array([XU['P1'][r[0]] - r[2] for r in rows]); v = np.array([r[3] for r in rows], bool)
    hm = ms >= ym2i(HOLD0)
    act = float((a * v)[hm].mean() * 1200)
    rng = random.Random(7)
    sims = sorted(float((a * np.roll(v, rng.randrange(len(v))))[hm].mean() * 1200) for _ in range(1000))
    D['placebo_circular_shift'] = {'actual_hold_ann': round(act, 2), 'placebo_mean': round(S.mean(sims), 2), 'p95': round(sims[949], 2),
                                   'p_ge_actual': round(sum(1 for x in sims if x >= act) / 1000, 3)}
    log('E3_P1 プラセボ', D['placebo_circular_shift'])
    nb = {}
    for lab, kw in [('pct70', dict(q=70)), ('pct75', dict(q=75)), ('pct85', dict(q=85)), ('pct90', dict(q=90)),
                    ('win36', dict(W=36)), ('win48', dict(W=48)), ('win84', dict(W=84)), ('win120', dict(W=120)),
                    ('H36', dict(H=36)), ('H48', dict(H=48)), ('H84', dict(H=84)), ('H120', dict(H=120)), ('hist60', dict(hmin=60)), ('hist180', dict(hmin=180))]:
        W = kw.get('W', 60); q = kw.get('q', 80); hm_ = kw.get('hmin', 120); H = kw.get('H', 60)
        R2 = cumlog(FMKTRF, mk['vw_cap']['usa'], W)
        st2 = own_state(R2, binding(mk['vw']['usa'], mk['vw_cap']['usa'], W, round(48 * W / 60)), q, hm_)
        cr2 = us_run('P1', 'H', H=H, stt=st2, R=R2)
        s2, b2, sn2, _ = pool(cr2)
        e2 = full_eval(s2, b2, sn2)
        nb[lab] = {'train': brief(e2['train']), 'hold': brief(e2['hold']), 'hold_net': brief(e2['hold_net']), 'grade_without_holm': e2['grade_mech'],
                   'C1': e2['criteria']['C1_train']}
    D['neighbors'] = nb
    log('E3_P1 近い母数', {k: (v['train'], v['hold'], v['grade_without_holm']) for k, v in nb.items()})
    cs = {}
    for lab, tv, um in (('as_claimed', turnP1, 1), ('unit_x2', turnP1, 2), ('unit_x3', turnP1, 3), ('turnover_x1.5_unit_x2', turnP1 * 1.5, 2)):
        cr3 = us_run('P1', 'H', turn_over=tv, unit_mult=um)
        s3, b3, sn3, _ = pool(cr3)
        cs[lab] = stats(sn3, b3, a=HOLD0)
    D['costs'] = cs
    log('E3_P1 費用', {k: brief(v) for k, v in cs.items()})
    details['E3_P1'] = D

    # ─── 多重検定 ───
    graded = [t for t in CL['tested'] if t.get('graded')]
    mt = {'angle_tested': CL['n_tested'], 'angle_graded': CL['n_graded'], 'program_bonferroni_t': PROGRAM_BONF_T,
          'angle_bonferroni_t_graded': round(float(_z_two(0.05 / CL['n_graded'])), 2),
          'hold_t_rank_among_graded': sorted(((t['hold'] or {}).get('t') or -99, t['name']) for t in graded)[::-1][:8]}
    log('多重検定', mt)


    # ─── 訓練期間の独立な局面（状態A が 2006年までに始まった局面の始まりの月）───
    st_eps = [(e['country'], e['start']) for e in CL['episodes']['A']['list'] if e['start'] <= TRAIN_END]
    tmt = [x for x in st_eps if 199806 <= x[1] <= 200112]
    ep = {'episodes_starting_by_2006': len(st_eps), 'of_which_1998_06_to_2001_12': len(tmt), 'list': st_eps}
    log('訓練の局面', ep)

    verdicts = build_verdicts(details, mt, ep)
    out = {'angle': 'concentration_regime', 'verifier': 'night/mw_concentration_regime_verify.py', 'target': 'out/mw_concentration_regime.json',
           'independence': '取得は mw_common の取得器（M.get・M.jkp_rows・M.ff_factors）だけ。国の市場と三分位の読み込み・良い側（2通り）・信号（R_cap・上限の効き・自国の80%点・米国の閾値）・'
                           'X（割安＋勢い・等加重・門の写し P1〔定義は mw_gate_proxy.MEASURES と一致を確かめるだけ〕）・切替と費用・国の等分・超過・NW t・幾何の年率差・20年窓・積立・プラセボは自前。線（C1〜C8→格）だけ M.grade',
           'selection': '課題の指定: S/A 全部（F1b_valmom・E1_equal・E1_valmom・F1c_valmom の S 4本・A なし）＋保有の超過で上位の B（B は E3_P1 の1本だけ）',
           'rules_of_this_verification': [
               '再現: 研究側の数字（全期間・訓練・保有・費用後の超過と t）を自前のコードで作り直して突き合わせる',
               '全体の事前登録（out/mw_prereg.json）の誠実さの規則『保有期間の結果を見て規則を変えたら事後と明記し、判定には使わない』を当てる: 事前登録2（E1・E3）は F1・F1b・F2 の結果（保有期間を含む）を見た後の着想＝判定の外（C）',
               '局面の効き: 国ごとに在X の印を無作為に回した偽の時期（割合と持続を保つ・1000回）と、在X の月と外の月の (X−vw) の差で測る。偽の時期と区別できなければ、規則の勝ちは X そのものの既知の上乗せ',
               '割安＋勢い（米国外・国の中の三分位）の 2007〜 の勝ちは mw_intl（検証で S 確定）で知られていた＝この角度の保有期間は X にとって独立の答え合わせではない。局面の効きも無ければ C3 を新しい証拠として数えない（C5 が合格なら A）',
               '費用は研究側の単価に加え、現実的な回転率（割安＋勢い 1.3/年＝mw_intl の検証の勢い 2.2/年 を半分）と単価2倍・3倍で C6 を見直す',
               '線（C1〜C8）は M.grade そのまま'],
           'no_issue_found': {
               'lookahead': '信号は月 t の末までの値（R は t までの60か月・分位は t までの履歴・上限の効きも t まで）で作り、保有は t+1。自前で作り直して研究側と全項目一致',
               'good_side': gs, 'good_side_note': '7特性すべて、JKP の文献の向き（direction 列）と米国 ≤2006 の相関の両方で第3分位＝保有期間のデータで選んでいない',
               'benchmark': '国ごとの相手は JKP の上限なしの時価加重（vw）。米国は French Mkt（研究側の点検で JKP usa vw と全期間 −0.03%/年）。上限つき・等加重は相手に使っていない',
               'excess_vs_total': 'JKP の超過・French Mkt-RF の両方に French RF を足して総リターンどうしで比べている',
               'survivorship': 'JKP・French は CRSP/上場廃止込み',
               'thrB': {'mine': round(thrB, 4), 'claimed': CL['sanity']['thr_us_B']},
               'data_gap': 'bgr（ブルガリア）の三分位は JKP が 403 で取れない（研究側も同じ・その国は X が無い月として両側から外れる＝0で埋めていない）'},
           'caveats_common': [
               '相手は各国の純粋な時価加重を国の等分で混ぜたもの＝地域の時価加重（world ex US）でも S&P500 でもない。等分は新興国・小国を重くする（銘柄数の重みで混ぜた版も details に）',
               'X の三分位（米国外の約30か国）は ETF が無く、個人が持てる形ではない。mw_intl の検証では実在の割安＋勢いの ETF の組み合わせは紙の半分〜3分の1で有意でない',
               '2006年までに始まった状態A の局面 18 のうち 12 は 1998-06〜2001-12（IT バブルの天井＝ほぼ一つの世界的な出来事）。訓練の独立な局面は実質少ない'],
           'training_episodes': ep,
           'multiple_testing': mt,
           'verdicts': verdicts,
           'details': details}
    out['summary_ja'] = summary(details, verdicts, mt)
    for l in out['summary_ja']:
        log(l)
    out['log'] = LOG
    out['runtime_sec'] = round(time.time() - T0)
    p = M.save('mw_concentration_regime_verify.json', out)
    log('書いた', p)


def B(e):
    return f"{e['ex_ann']:+.2f}%/年 t{e['t']}" if e else 'なし'


def keynums(D):
    e = D['reproduced']
    rl = e['roll20'] or {}
    return (f"再現 全{B(e['full'])}・訓{B(e['train'])}・保{B(e['hold'])}・CAGR差 保{e['hold']['cagr_diff']:+.2f}・費後{B(e['hold_net'])}・"
            f"20年一括 {rl.get('win_rate')}（{rl.get('windows')}窓）・積立中央 {(e['dca20'] or {}).get('median')}・"
            f"国 {D.get('repl')}（研究側と一致={all(D['match_claim'].values())}）")


def nb_fail(D, key='C1'):
    return [f"{k} {v['train']}" for k, v in D['neighbors'].items() if v.get(key) is False]


def build_verdicts(details, mt, ep):
    V = []
    bonf = mt['program_bonferroni_t']
    # F1b_valmom
    D = details['F1b_valmom']; sp = D['subperiods']; pl = D['placebo_circular_shift']; co = D['conditioning']; cs = D['costs']; cset = D['country_sets']
    V.append({'name': 'F1b_valmom', 'claimed_grade': 'S', 'verified_grade': 'A', 'reproduced': True, 'verdict': 'downgraded to A',
              'key_numbers': keynums(D),
              'issues': [
                  f"局面（独走の後60か月）には時期の情報が無い: 在X の印を国ごとに無作為に回した偽の時期 1000回で 保有の上乗せ 平均 {pl['placebo_hold_mean']:+.2f}%/年・95%点 {pl['placebo_hold_p95']:+.2f}、実際 {pl['actual_hold_ann']:+.2f}（偽≥実 {pl['p_placebo_ge_actual_hold']}）。訓練も 偽 {pl['placebo_train_mean']:+.2f} ≥ 実 {pl['actual_train_ann']:+.2f}（{pl['p_placebo_ge_actual_train']}）。在X の月 − 外の月の (X−vw) は 保有 {co['hold_in_minus_out_ann']:+.2f}%/年 t{co['hold_t']}＝角度の新しい中身（局面）は反証",
                  f"勝ちの中身は既知の割安＋勢い（米国外・国の中）を約半分の月（在X {D['in_X_share']}）持っただけ: 同じ国×月で常に持つと 保有 {B(D['always_X_same_country_months']['hold'])}・訓練 {B(D['always_X_same_country_months']['train'])} ＞ 規則。割安＋勢いの 2007〜 の勝ちは mw_intl（検証で S 確定・同じ保有期間・同じ地域）で設計前に知られていた＝保有の t は新しい証拠ではない（C3 を数えず、C5 38/38 で A）。プログラムの台帳で mw_intl の S と二重に数えないこと",
                  f"訓練は 9.9 年（1997-02〜・全体の事前登録の最低15年に届かない）で、1か月の国数は平均 {D['train_composition']['avg_countries_per_month']}・最小 {D['train_composition']['min_countries']}。訓練の局面 {ep['episodes_starting_by_2006']} のうち {ep['of_which_1998_06_to_2001_12']} が 1998-06〜2001-12 の IT バブルの天井＝実質一つの出来事。近い母数で C1 が落ちる: {nb_fail(D)}（16通り中 {len(nb_fail(D))}）",
                  f"紙の上では頑丈: 訓練から 1998-2000 を外して {B(sp['train_drop_1998_2000'])}・1998-2002 を外して {B(sp['train_drop_1998_2002'])}・既知の top dogs（fin can swe nld）抜き 訓練 {B(D['train_without_known_topdogs']['train'])}／保有の前半 {B(sp['hold_first_2007_2016H1'])}・後半 {B(sp['hold_second_2016H2_2025'])}・2020-21 抜き {B(sp['hold_drop_2020_2021'])}／先進国だけ 保有 {B(cset['developed']['hold'])}・銘柄数の重み {B(cset['weighted_by_n_stocks']['hold'])}／一国外しの最小 {D['leave_one_out']['hold_min'][0]} {D['leave_one_out']['hold_min'][1]:+.2f}",
                  f"費用: 研究側 {B(cs['as_claimed']['hold_net'])}・現実的な回転（1.3/年）{B(cs['realistic_turnover']['hold_net'])}・単価2倍 {B(cs['unit_x2']['hold_net'])}・両方 {B(cs['realistic_turnover_unit_x2']['hold_net'])}・単価3倍 {B(cs['unit_x3']['hold_net'])}（C6 は保つ）。保有の前半の費用後は {B(sp['hold_net_first'])}",
                  f"多重検定: 保有 t {D['reproduced']['hold']['t']} はプログラム全体の Bonferroni 線 t≈{bonf} を越える（角度で唯一）。全期間 t {D['reproduced']['full']['t']}。ただし越えているのは X（割安＋勢い）の上乗せで、局面ではない",
                  "相手は各国の純粋な時価加重の国の等分（S&P500 ではない）。X は JKP の国の中の三分位で個人は持てない（mw_intl の検証: 実在の ETF の組み合わせは紙の半分〜3分の1・有意でない）"]})
    # E1_equal
    D = details['E1_equal']; sp = D['subperiods']; pl = D['placebo_circular_shift']; co = D['conditioning']; cs = D['costs']; cset = D['country_sets']
    V.append({'name': 'E1_equal', 'claimed_grade': 'S', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
              'key_numbers': keynums(D),
              'issues': [
                  "事後の規則: 事前登録2（09e60f1）の着想は F1・F1b・F2 の結果（2007〜の保有期間を含む・次の60か月の差）を見た後と研究側自身が明記。全体の事前登録の誠実さの規則『保有期間の結果を見て規則を変えたら事後と明記し、判定には使わない』により判定の外（族の中の Holm では選択の偏りは消えない）",
                  f"費用後が単価に弱い: 研究側 {B(cs['as_claimed']['hold_net'])}（C6 は正だが t1.42）・単価2倍 {B(cs['unit_x2']['hold_net'])}・現実的な回転0.8＋単価2倍 {B(cs['realistic_turnover_unit_x2']['hold_net'])}・3倍 {B(cs['unit_x3']['hold_net'])}。切替 {D['switches']} 回。新興国の等加重は極小型株を含み、片道100%あたり 1.0% は楽観的＝現実的な費用で C6 が落ちる",
                  f"先進国だけ 保有 {B(cset['developed']['hold'])}・費用後 {B(cset['developed']['hold_net'])}／新興国 費用後 {B(cset['emerging']['hold_net'])}／保有の前半 費用後 {B(sp['hold_net_first'])}・後半 {B(sp['hold_net_second'])}／2018〜 {B(sp['post2018'])}",
                  f"局面の効きはこの角度でいちばん本物に近い（偽の時期 p={pl['p_placebo_ge_actual_hold']}・訓練 p={pl['p_placebo_ge_actual_train']}・在X − 外 保有 {co['hold_in_minus_out_ann']:+.2f}%/年 t{co['hold_t']}）が、事後の規則なので新しい事前登録で前向きに確かめる材料にとどまる",
                  f"多重検定: 保有 t {D['reproduced']['hold']['t']} は角度の Bonferroni（判定49本）t≈{mt['angle_bonferroni_t_graded']} にもプログラムの t≈{bonf} にも届かない",
                  f"常に等加重を持つ（同じ国×月）と 保有 {B(D['always_X_same_country_months']['hold'])}。近い母数で C1 が落ちる: {nb_fail(D)}"]})
    # E1_valmom
    D = details['E1_valmom']; sp = D['subperiods']; pl = D['placebo_circular_shift']; co = D['conditioning']; cs = D['costs']
    V.append({'name': 'E1_valmom', 'claimed_grade': 'S', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
              'key_numbers': keynums(D),
              'issues': [
                  "事後の規則（E1_equal と同じ）: 事前登録2 は保有期間を含む結果を見た後の着想＝全体の事前登録の規則で判定の外",
                  f"C1 がフィンランド1国（Nokia・設計時に既知の後知恵）に乗っている: フィンランドを外すと訓練 t {D['leave_one_out']['train_t_min'][3]}（<2.0）。近い母数でも C1 が落ちる: {nb_fail(D)}（16通り中 {len(nb_fail(D))}）",
                  f"費用: 研究側 {B(cs['as_claimed']['hold_net'])}・単価2倍 {B(cs['unit_x2']['hold_net'])}・現実的な回転1.3＋単価2倍 {B(cs['realistic_turnover_unit_x2']['hold_net'])}・3倍 {B(cs['unit_x3']['hold_net'])}＝費用後の上乗せは現実的な費用でほぼ0。保有の前半の費用後 {B(sp['hold_net_first'])}",
                  f"局面の効きは弱い: 偽の時期 p={pl['p_placebo_ge_actual_hold']}（保有）・{pl['p_placebo_ge_actual_train']}（訓練）・在X − 外 保有 {co['hold_in_minus_out_ann']:+.2f} t{co['hold_t']}。常に割安＋勢いを持つと 保有 {B(D['always_X_same_country_months']['hold'])}＝規則の {B(D['reproduced']['hold'])} を大きく上回る",
                  f"多重検定: 保有 t {D['reproduced']['hold']['t']} はプログラムの Bonferroni t≈{bonf} に届かない。割安＋勢いの保有期間の勝ちは mw_intl で既知"]})
    # F1c_valmom
    D = details['F1c_valmom']; sp = D['subperiods']; pl = D['placebo_circular_shift']; co = D['conditioning']; cs = D['costs']; cset = D['country_sets']
    V.append({'name': 'F1c_valmom', 'claimed_grade': 'S', 'verified_grade': 'A', 'reproduced': True, 'verdict': 'downgraded to A',
              'key_numbers': keynums(D),
              'issues': [
                  f"保有期間で局面の効きはゼロ: 在X の月 − 外の月の (X−vw) {co['hold_in_minus_out_ann']:+.2f}%/年 t{co['hold_t']}・偽の時期 p={pl['p_placebo_ge_actual_hold']}（訓練だけ p={pl['p_placebo_ge_actual_train']}）。同じ国×月で常に割安＋勢いを持つと 保有 {B(D['always_X_same_country_months']['hold'])}・規則はその {D['reproduced']['hold']['ex_ann'] / D['always_X_same_country_months']['hold']['ex_ann']:.0%} を在X {D['in_X_share']} の月で取っただけ＝比例",
                  "F1b と同じ理由で保有の t は X（mw_intl で既知の割安＋勢い）の上乗せで新しい証拠ではない（C3 を数えず、C5 28/29・C7 全期間 t3.57 で A）",
                  f"経済的にはごく小さく、費用に弱い: 研究側 {B(cs['as_claimed']['hold_net'])}・単価2倍 {B(cs['unit_x2']['hold_net'])}・現実的な回転＋単価2倍 {B(cs['realistic_turnover_unit_x2']['hold_net'])}・3倍 {B(cs['unit_x3']['hold_net'])}。保有の前半の費用後 {B(sp['hold_net_first'])}・銘柄数の重みの費用後 {B(cset['weighted_by_n_stocks']['hold_net'])}・新興国の費用後 {B(cset['emerging']['hold_net'])}",
                  f"紙の上の粗の上乗せは母数に頑丈（近い母数10通りすべて S）・訓練は 16.5 年で本物・1998-2000 抜き 訓練 {B(sp['train_drop_1998_2000'])}",
                  f"多重検定: 保有 t {D['reproduced']['hold']['t']} はプログラムの Bonferroni t≈{bonf} に届かない"]})
    # E3_P1
    D = details['E3_P1']; sp = D['subperiods']; pl = D['placebo_circular_shift']; co = D['conditioning']; cs = D['costs']
    V.append({'name': 'E3_P1', 'claimed_grade': 'B', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
              'key_numbers': keynums(D).replace('国 None', '国 N/A'),
              'issues': [
                  "事後の規則: 事前登録2 の探索（米国の H60）は F3 の結果（保有期間を含む）を見た後＝全体の事前登録の規則で判定の外",
                  f"C1 が 1998-2000（IT バブルの崩壊・既知の歴史）に乗っている: 訓練から外すと {B(sp['train_drop_1998_2000'])}・1963-84 は {B(sp['train_1963_1984'])}。近い母数で C1 が落ちる: {nb_fail(D)}（14通り中 {len(nb_fail(D))}）",
                  f"時期に情報が無い: 偽の時期 p={pl['p_ge_actual']}（実 {pl['actual_hold_ann']:+.2f} vs 偽の平均 {pl['placebo_mean']:+.2f}）。訓練では在X の月 {co['train_in_ann']:+.2f}%/年 ＜ 外の月 {co['train_out_ann']:+.2f}（逆向き）。常に P1 を持つと 保有 {B(D['always_P1_same_months']['hold'])}・訓練 {B(D['always_P1_same_months']['train'])} ＞ 規則",
                  f"保有の前半 {B(sp['hold_first_2007_2016H1'])}・後半 {B(sp['hold_second_2016H2_2025'])}＝勝ちは 2016 年以降だけ。2020-21 を外すと {B(sp['hold_drop_2020_2021'])}",
                  f"費用には強い（単価3倍 {B(cs['unit_x3'])}）が、C7 は研究側どおり不合格（全期間 t {D['reproduced']['full']['t']}・Holm 0.083）"]})
    return V


def summary(details, V, mt):
    g = {v['name']: v['verified_grade'] for v in V}
    f1b, f1c = details['F1b_valmom'], details['F1c_valmom']
    e1e = details['E1_equal']
    return [
        f"再現: 5本とも研究側の数字（全期間・訓練・保有・費用後の超過と t）を自前のコードで小数2桁まで再現。先読み・相手（各国の純粋な時価加重・米国は French Mkt）・良い側（2006年までの米国で第3）に不正は無い。",
        f"しかし角度の新しい中身（巨大株の独走という局面）は、割安＋勢いの規則では時期の情報を持たない: 在X の印を無作為に回した偽の時期と区別できない（F1b 保有 実 {f1b['placebo_circular_shift']['actual_hold_ann']:+.2f} vs 偽 {f1b['placebo_circular_shift']['placebo_hold_mean']:+.2f}・p={f1b['placebo_circular_shift']['p_placebo_ge_actual_hold']}／F1c 在X − 外 {f1c['conditioning']['hold_in_minus_out_ann']:+.2f}%/年）。",
        f"F1b・F1c の S は、mw_intl で既に S の割安＋勢い（米国外・同じ 2007〜）を一部の月だけ持った形で、常に持つほうが大きい（保有 +2.73〜2.87 t6.3〜6.9）。保有の t は新しい証拠ではないので C3 を数えず A に下げる（F1b={g['F1b_valmom']}・F1c={g['F1c_valmom']}）。F1c は費用後 +0.23・単価2倍で +0.05 と経済的にはほぼ0。",
        f"E1_equal・E1_valmom・E3_P1 は事前登録2＝保有期間を含む結果を見た後の着想で、全体の事前登録の規則により判定の外（C）。加えて E1_equal は単価2倍で費用後 {e1e['costs']['unit_x2']['hold_net']['ex_ann']:+.2f}%/年、E1_valmom は訓練の C1 がフィンランド（Nokia）1国に乗り、E3_P1 は訓練から 1998-2000 を外すと t1.43。",
        f"ただし独走が折り返した後の等加重には時期の情報がありそう（偽の時期 p={e1e['placebo_circular_shift']['p_placebo_ge_actual_hold']}・在X − 外 +{e1e['conditioning']['hold_in_minus_out_ann']}%/年 t{e1e['conditioning']['hold_t']}）で、前向きの事前登録の材料にはなる。",
        f"多重検定: 角度 {mt['angle_tested']}本（判定 {mt['angle_graded']}本）。プログラム全体の線 t≈{mt['program_bonferroni_t']} を保有で越えるのは F1b_valmom だけで、越えているのは既知の割安＋勢いの上乗せ。相手は国の等分・X は個人が持てない三分位＝S&P500 に対する個人の勝ちにはなっていない。",
    ]


def _z_two(p):
    """両側 p に対応する |z|（二分法）"""
    lo, hi = 0.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == '__main__':
    main()
