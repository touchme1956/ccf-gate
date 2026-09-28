#!/usr/bin/env python3
"""night/mw_concentration_regime.py — 『市場に勝てる歴史検証』の角度 concentration_regime（読むだけ・門の判定には不使用）

問い: ある市場で最大級の会社が他を大きく引き離した後（純粋な時価加重 − 上限つき時価加重 の過去60か月の累積が
      その国自身の歴史で上位20%）、同じ市場の中の検証済みの上乗せ（上限つき加重・等加重・割安＋勢い・cop_at・qmj）を
      持つと、同じ市場の純粋な時価加重に勝ったか。米国の2007年以降の負けは『戻る局面』か。
事前登録: out/mw_concentration_regime_prereg.json（線は out/mw_prereg.json・判定は mw_common.grade）
出力: out/mw_concentration_regime.json

使い方: python3 night/mw_concentration_regime.py [--check]
  --check はデータと信号の有無・件数だけを数える（戦略と市場を比べる数字は出さない）
"""
import csv, io, json, math, os, statistics as S, subprocess, sys, zipfile, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import numpy as np  # noqa: E402

BASE = M.BASE
ANGLE = 'concentration_regime'
PREREG = 'mw_concentration_regime_prereg.json'
S3 = 'https://jkpfactors-data.s3.amazonaws.com/public/'
DEVELOPED = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
             'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe'}
JKP_END = 202512
NMIN_STOCKS = 100
WIN, HIST_MIN, PCT, BIND_MIN = 60, 120, 80, 48
COV_R, N_GOOD, START_INTL, START_US_ACC = 0.4, 10, 199007, 196307
VALUE4 = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
MOM = 'ret_12_1'
CHARS = VALUE4 + [MOM, 'cop_at', 'qmj']
XS = ['capped', 'equal', 'valmom', 'cop_at', 'qmj']
TURN = {'capped': 0.10, 'equal': 0.50, 'valmom': 0.95, 'cop_at': 0.40, 'qmj': 0.50}
DESC_X = {'capped': '上限つき時価加重の市場（JKP vw_cap）', 'equal': '等加重の市場（JKP ew）',
          'valmom': '割安4本の良い側の平均50%＋勢い(ret_12_1)の良い側50%', 'cop_at': 'cop_at の良い側の三分位',
          'qmj': 'qmj の良い側の三分位', 'P1': '門の写し P1_GATE_ALL（16の物差しの良い側を等分）'}
DESC_SIG = {'A': '状態A: R_cap（vw−vw_cap の過去60か月の累積）がその国の履歴の80%点超', 'B': '状態B: R_cap が米国1926〜2006の80%点超（絶対の閾値）',
            'C': '状態C: R_ew（vw−ew の過去60か月の累積）がその国の履歴の80%点超', 'D': '状態D: 米国の最上位 NYSE 十分位の時価の割合が履歴の80%点超'}
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def sha_of(path):
    try:
        return subprocess.run(['git', 'log', '--format=%H', '-n1', '--', path], cwd=BASE,
                              capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def sha_first(path):
    try:
        return subprocess.run(['git', 'log', '--diff-filter=A', '--format=%H', '--', path], cwd=BASE,
                              capture_output=True, text=True).stdout.strip().split('\n')[-1] or None
    except Exception:  # noqa
        return None


# ───────────────────────── 月の算術 ─────────────────────────
def addm(ym, k):
    y, m = divmod(ym, 100)
    t = y * 12 + (m - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def midx(ym):
    return (ym // 100) * 12 + ym % 100 - 1


# ───────────────────────── データ ─────────────────────────
FF = M.ff_factors()
RF, FR_MKTRF = FF['rf'], FF['mktrf']


def load_markets():
    mk = {w: collections.defaultdict(dict) for w in ('vw', 'vw_cap', 'ew')}
    nst = collections.defaultdict(dict)
    for w in mk:
        b = M.get(S3 + '%5Ball_countries%5D_%5Bmkt%5D_%5Bmonthly%5D_%5B' + w + '%5D.zip', name='jkp_factor_all_countries_mkt_' + w + '_monthly.zip')
        z = zipfile.ZipFile(io.BytesIO(b))
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            if x['ret'] in ('', 'NA', 'na'):
                continue
            ym = M._ym(x['date'])
            mk[w][x['location']][ym] = float(x['ret'])
            if w == 'vw' and x['n_stocks'] not in ('', 'NA', 'na'):
                nst[x['location']][ym] = int(float(x['n_stocks']))
    return {w: dict(v) for w, v in mk.items()}, dict(nst)


def load_af(c):
    """JKP all_factors 三分位（vw）→ {特性: {pf: {ym: (ret, n)}}}（必要な7特性だけ）。取れなければ {}（0で埋めない）"""
    try:
        rows = M.jkp_rows(c, 'all_factors', 'portfolios', 'vw')
    except Exception as e:  # noqa
        log('  all_factors 取得失敗', c, e)
        return {}
    d = {}
    for x in rows:
        if x['name'] not in CHARS or x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x.get('n') not in (None, '', 'NA', 'na') else None
        d.setdefault(x['name'], {}).setdefault(x['pf'], {})[M._ym(x['date'])] = (float(x['ret']), n)
    return d


GOOD = {}


def good_sides():
    for k in CHARS:
        side, _ = M.jkp_good_side('usa', k, 'vw', upto=200612)
        GOOD[k] = side
    return GOOD


def screened(af, k, nst_c, start):
    side = GOOD.get(k)
    pf = af.get(k)
    if not pf or side not in pf:
        return {}
    out = {}
    for m, (r, n) in pf[side].items():
        if m < start or m > JKP_END or n is None or n < N_GOOD:
            continue
        tot = sum(pf[q][m][1] for q in pf if m in pf[q] and pf[q][m][1] is not None)
        d = nst_c.get(m)
        if not d or tot / d < COV_R:
            continue
        out[m] = r
    return out


def build_X(c, mk, nst, start):
    """国 c の X 5本（JKP の超過）"""
    X = {'capped': dict(mk['vw_cap'].get(c, {})), 'equal': dict(mk['ew'].get(c, {}))}
    af = load_af(c)
    sc = {k: screened(af, k, nst.get(c, {}), start) for k in CHARS}
    vc = {}
    for m in set().union(*[set(sc[k]) for k in VALUE4]):
        v = [sc[k][m] for k in VALUE4 if m in sc[k]]
        if len(v) >= 2:
            vc[m] = S.mean(v)
    X['valmom'] = {m: 0.5 * vc[m] + 0.5 * sc[MOM][m] for m in vc if m in sc[MOM]}
    X['cop_at'] = sc['cop_at']
    X['qmj'] = sc['qmj']
    return X


# ───────────────────────── 信号 ─────────────────────────
def roll_R(a_ex, b_ex, win=WIN):
    """R(t) = Σ_{t−59..t} [ln(1+a+rf) − ln(1+b+rf)]（60か月すべてそろうときだけ）"""
    L = {m: math.log1p(a_ex[m] + RF[m]) - math.log1p(b_ex[m] + RF[m]) for m in a_ex if m in b_ex and m in RF}
    R = {}
    for t in sorted(L):
        ms = [addm(t, -i) for i in range(win)]
        if all(x in L for x in ms):
            R[t] = math.fsum(L[x] for x in ms)
    return R


def bind_ok(vw, cap, win=WIN):
    """過去60か月のうち上限が効いた月（|vw−vw_cap|>1e-6）が48以上か"""
    B = {m: abs(vw[m] - cap[m]) > 1e-6 for m in vw if m in cap}
    out = {}
    for t in sorted(B):
        ms = [addm(t, -i) for i in range(win)]
        if all(x in B for x in ms):
            out[t] = sum(B[x] for x in ms) >= BIND_MIN
    return out


def own_pct_state(R, extra=None, hist_min=HIST_MIN, q=PCT):
    """状態(t) = extra(t) ∧ R(t)>0 ∧ R(t) > t までの全履歴（t を含む）の q%点。履歴が hist_min 未満は None（未定義）"""
    hist, st, pv = [], {}, {}
    for t in sorted(R):
        hist.append(R[t])
        if len(hist) < hist_min:
            st[t] = None
            continue
        p = float(np.percentile(hist, q))
        ok = R[t] > 0 and R[t] > p and (extra is None or bool(extra.get(t, False)))
        st[t], pv[t] = ok, p
    return st, pv


def abs_state(R, thr, extra):
    return {t: bool(extra.get(t, False)) and R[t] > thr for t in R}


# ───────────────────────── 戦略 ─────────────────────────
def unit_cost(c, x):
    if c == 'usa':
        u = 0.001
        return 0.003 if x == 'equal' else u
    u = 0.003 if c in DEVELOPED else 0.005
    return 2 * u if x == 'equal' else u


def run_country(state, Xs, vw, nst_ok, unit, turn, rule='H0'):
    """→ {m: (戦略の超過, 市場の超過, 上乗せ, 費用, X を持ったか)}。state は信号の月 t → bool/None。m = t+1"""
    rows, prev_hold, prev_m = {}, None, None
    for t in sorted(state):
        if state[t] is None:
            continue
        if nst_ok is not None and not nst_ok(t):
            continue
        m = addm(t, 1)
        if m not in Xs or m not in vw or m not in RF:
            continue
        if rule == 'H0':
            inx = bool(state[t])
        else:
            inx = any(state.get(addm(t, -i)) is True for i in range(WIN))
        r = Xs[m] if inx else vw[m]
        cost = unit * turn / 12 if inx else 0.0
        hold = 'X' if inx else 'M'
        if prev_m is not None and prev_m == addm(m, -1):
            if hold != prev_hold:
                cost += unit
        elif hold == 'X':
            cost += unit
        rows[m] = (r, vw[m], r - vw[m], cost, inx)
        prev_hold, prev_m = hold, m
    return rows


def pool(crow, exclude=(), only=None, cost_mult=1.0):
    """国の行を等分に混ぜる → (s 総, b 総, s 費用後 総, 月ごとの国数)"""
    by = collections.defaultdict(list)
    for c, rows in crow.items():
        if c in exclude or (only is not None and c not in only):
            continue
        for m, v in rows.items():
            by[m].append(v)
    s, b, sn, nc = {}, {}, {}, {}
    for m in sorted(by):
        v = by[m]
        be = math.fsum(x[1] for x in v) / len(v)
        ac = math.fsum(x[2] for x in v) / len(v)
        co = math.fsum(x[3] for x in v) / len(v) * cost_mult
        b[m] = be + RF[m]
        s[m] = be + ac + RF[m]
        sn[m] = be + ac - co + RF[m]
        nc[m] = len(v)
    return s, b, sn, nc


def repl_counts(crow, min_in=12):
    reg = pos = 0
    per = {}
    for c, rows in crow.items():
        nin = sum(1 for v in rows.values() if v[4])
        if nin < min_in:
            continue
        mean_act = math.fsum(v[2] for v in rows.values()) / len(rows)
        ins = [v[2] for v in rows.values() if v[4]]
        reg += 1
        pos += mean_act > 0
        per[c] = {'in_months': nin, 'months': len(rows), 'mean_active_ann': round(mean_act * 1200, 2),
                  'in_state_mean_ann': round(S.mean(ins) * 1200, 2)}
    return {'regions': reg, 'positive': pos}, per


def compact(st):
    if not st:
        return None
    return {k: st[k] for k in ('from', 'to', 'years', 'ex_ann', 't', 'p', 'cagr_diff', 'te', 'ir', 'beta')}


def evaluate(s, b, sn, extra=None):
    full = M.excess_stats(s, b)
    train = M.excess_stats(s, b, z=M.TRAIN_END)
    hold = M.excess_stats(s, b, a=M.HOLD_START)
    recent = M.excess_stats(s, b, a=M.RECENT_START)
    post18 = M.excess_stats(s, b, a=201801)
    hold_net = M.excess_stats(sn, b, a=M.HOLD_START)
    full_net = M.excess_stats(sn, b)
    sp = {'train': (M.sharpe(s, RF, z=M.TRAIN_END), M.sharpe(b, RF, z=M.TRAIN_END)),
          'hold': (M.sharpe(s, RF, a=M.HOLD_START), M.sharpe(b, RF, a=M.HOLD_START))}
    out = {'full': full, 'train': train, 'hold': hold, 'recent': recent, 'post2018': compact(post18),
           'hold_net': hold_net, 'full_net': compact(full_net), 'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20),
           'sharpe_pair': sp}
    if extra:
        out.update(extra)
    return out


def activity(crow):
    n = sum(len(r) for r in crow.values())
    nin = sum(1 for r in crow.values() for v in r.values() if v[4])
    sw = 0
    for r in crow.values():
        ks = sorted(r)
        for a, z in zip(ks, ks[1:]):
            if z == addm(a, 1) and r[a][4] != r[z][4]:
                sw += 1
    return {'country_months': n, 'in_X_share': round(nin / n, 3) if n else None, 'switches': sw,
            'countries': len([c for c, r in crow.items() if r])}


# ───────────────────────── F2（報告）: 次の h か月の (X−vw) を状態に回帰・Driscoll-Kraay ─────────────────────────
def dk_reg(rows, L):
    """rows = [(t, D, y)]。y = a + b·D。Driscoll-Kraay（Bartlett・ラグ L）"""
    if len(rows) < 50 or len(set(r[1] for r in rows)) < 2:
        return None
    t_ = np.array([midx(r[0]) for r in rows])
    D = np.array([1.0 if r[1] else 0.0 for r in rows])
    y = np.array([r[2] for r in rows])
    X = np.column_stack([np.ones(len(y)), D])
    XtX = X.T @ X
    beta = np.linalg.solve(XtX, X.T @ y)
    e = y - X @ beta
    t0 = t_.min()
    T = t_.max() - t0 + 1
    H = np.zeros((T, 2))
    np.add.at(H, t_ - t0, X * e[:, None])
    Sm = H.T @ H
    for l in range(1, min(L, T - 1) + 1):
        w = 1 - l / (L + 1)
        G = H[l:].T @ H[:-l]
        Sm += w * (G + G.T)
    iX = np.linalg.inv(XtX)
    V = iX @ Sm @ iX
    se = np.sqrt(np.maximum(np.diag(V), 0))
    tb = beta[1] / se[1] if se[1] > 0 else None
    return {'n_obs': int(len(y)), 'n_in_state': int(D.sum()), 'months': int(len(set(t_.tolist()))),
            'mean_out': round(float(beta[0]) * 100, 2), 'mean_in': round(float(beta[0] + beta[1]) * 100, 2),
            'diff': round(float(beta[1]) * 100, 2), 't_dk': round(float(tb), 2) if tb is not None else None,
            'mean_all': round(float(y.mean()) * 100, 2)}


def forward_rows(state, Xs, vw, nst_ok, h):
    out = []
    for t in sorted(state):
        if state[t] is None or (nst_ok is not None and not nst_ok(t)):
            continue
        ms = [addm(t, i) for i in range(1, h + 1)]
        if not all(m in Xs and m in vw for m in ms):
            continue
        y = math.fsum(Xs[m] - vw[m] for m in ms) / h * 12
        out.append((t, bool(state[t]), y))
    return out


def episodes(state, R, nst_ok, gap=12):
    ts = [t for t in sorted(state) if state[t] is True and (nst_ok is None or nst_ok(t))]
    eps = []
    for t in ts:
        if eps and midx(t) - midx(eps[-1]['end']) - 1 < gap:
            e = eps[-1]
            e['end'] = t
            e['months'] += 1
            e['maxR'] = max(e['maxR'], R.get(t, float('-inf')))
        else:
            eps.append({'start': t, 'end': t, 'months': 1, 'maxR': R.get(t, float('-inf'))})
    for e in eps:
        e['maxR'] = round(e['maxR'], 3)
    return eps


# 巨大株の名前（JKP からは分からない。よく知られた例を『推定・後知恵』として注記するだけ・判定に不使用）
KNOWN = {('fin', 1997, 2003): 'Nokia（推定・後知恵）', ('can', 1998, 2003): 'Nortel（推定・後知恵）',
         ('swe', 1998, 2003): 'Ericsson（推定・後知恵）', ('dnk', 2020, 2025): 'Novo Nordisk（推定・後知恵）',
         ('nld', 1998, 2003): 'Philips・ING 等（推定・後知恵）', ('twn', 2019, 2025): 'TSMC（推定・後知恵）',
         ('kor', 2016, 2025): 'Samsung Electronics・SK hynix（推定・後知恵）', ('che', 2000, 2025): 'Nestlé・Roche・Novartis（推定・後知恵）',
         ('usa', 1995, 2001): 'IT バブル（Microsoft・Cisco・GE 等・推定）', ('usa', 2019, 2025): '巨大テック（Apple・Microsoft・NVIDIA 等・推定）',
         ('jpn', 1986, 1991): 'NTT・銀行株（推定・後知恵）'}


def known_note(c, e):
    for (cc, a, z), nm in KNOWN.items():
        if cc == c and not (e['end'] // 100 < a or e['start'] // 100 > z):
            return nm
    return None


# ───────────────────────── 本体 ─────────────────────────
def main(check=False):
    log('データ読み込み')
    mk, nst = load_markets()
    good_sides()
    log('良い側（米国〜2006）', GOOD)
    countries = sorted(c for c in mk['vw'] if c != 'usa' and any(n >= NMIN_STOCKS for n in nst.get(c, {}).values()))
    log('米国外の国（銘柄数100以上の月がある）', len(countries))

    # 米国の信号 A と閾値 B
    us_vw, us_cap, us_ew = mk['vw']['usa'], mk['vw_cap']['usa'], mk['ew']['usa']
    R_us = roll_R(FR_MKTRF, us_cap)
    bind_us = bind_ok(us_vw, us_cap)
    thr_us = float(np.percentile([R_us[t] for t in R_us if t <= M.TRAIN_END], PCT))
    log('米国 R_cap の初月', min(R_us), '閾値B（米国〜2006の80%点）', round(thr_us, 4), '月数', sum(1 for t in R_us if t <= M.TRAIN_END))

    # 国ごとの信号
    SIG = {'A': {}, 'B': {}, 'C': {}}
    RR = {'A': {}, 'C': {}}
    for c in countries:
        vw, cap, ew = mk['vw'].get(c, {}), mk['vw_cap'].get(c, {}), mk['ew'].get(c, {})
        Rc = roll_R(vw, cap)
        bo = bind_ok(vw, cap)
        SIG['A'][c], _ = own_pct_state(Rc, extra=bo)
        SIG['B'][c] = abs_state(Rc, thr_us, bo)
        Re = roll_R(vw, ew)
        SIG['C'][c], _ = own_pct_state(Re)
        RR['A'][c], RR['C'][c] = Rc, Re
    nst_ok = {c: (lambda t, c=c: nst.get(c, {}).get(t, 0) >= NMIN_STOCKS) for c in countries}

    log('X を作る（all_factors 三分位）')
    XX = {c: build_X(c, mk, nst, START_INTL) for c in countries}

    if check:
        for sg in SIG:
            defined = sum(1 for c in countries for t, v in SIG[sg][c].items() if v is not None and nst_ok[c](t))
            on = sum(1 for c in countries for t, v in SIG[sg][c].items() if v is True and nst_ok[c](t))
            first = min((t for c in countries for t, v in SIG[sg][c].items() if v is not None and nst_ok[c](t)), default=None)
            log(f'信号{sg}: 定義された国×月 {defined}・状態の国×月 {on}・最初の月 {first}')
        for x in XS:
            log(f'X {x}: 国数 {sum(1 for c in countries if XX[c][x])}・国×月 {sum(len(XX[c][x]) for c in countries)}')
        return

    tested = []
    CROW = {}

    def fam_eval(fam, sg, rule, graded=True, label=None):
        res = {}
        for x in XS:
            crow = {}
            for c in countries:
                rows = run_country(SIG[sg][c], XX[c][x], mk['vw'][c], nst_ok[c], unit_cost(c, x), TURN[x], rule)
                if rows:
                    crow[c] = rows
            CROW[(fam, x)] = crow
            s, b, sn, nc = pool(crow)
            repl, per = repl_counts(crow)
            ev = evaluate(s, b, sn, {'repl': repl, 'per_country': per, 'activity': activity(crow),
                                     'avg_countries_per_month': round(S.mean(nc.values()), 1) if nc else None})
            res[x] = ev
        ph = M.holm({x: res[x]['hold']['p'] if res[x]['hold'] else None for x in XS})
        for x in XS:
            ev = res[x]
            g, cr = M.grade(ev['full'], ev['train'], ev['hold'], ev['roll20'], cost_hold=ev['hold_net'], repl=ev['repl'],
                            family_holm_p=ph.get(x), sharpe_pair=ev['sharpe_pair'], leveraged_or_timing=True)
            ent = {'name': f'{fam}_{x}', 'family': fam, 'graded': graded, 'label': label or ('主' if fam == 'F1' else '副'),
                   'signal': sg, 'rule': rule, 'X': x,
                   'description': f'{DESC_SIG[sg]}のとき X＝{DESC_X[x]}、それ以外はその国の純粋な時価加重（vw）。米国外の国を等分（{rule}）',
                   'holm_p': ph.get(x), 'grade': g, 'criteria': cr}
            ent.update(ev)
            tested.append(ent)
            h = ev['hold'] or {}
            log(f'{fam}_{x}: 全期間 {(ev["full"] or {}).get("ex_ann")}%/年 t{(ev["full"] or {}).get("t")}・訓練 {(ev["train"] or {}).get("ex_ann")} t{(ev["train"] or {}).get("t")}'
                f'・保有 {h.get("ex_ann")} t{h.get("t")}・費用後 {(ev["hold_net"] or {}).get("ex_ann")}・国 {ev["repl"]}・{g}')
        return res

    log('── F1（主）状態A・H0')
    fam_eval('F1', 'A', 'H0')
    log('── F1b 状態A・H60')
    fam_eval('F1b', 'A', 'H60')
    log('── F1c 状態B（米国の閾値）・H0')
    fam_eval('F1c', 'B', 'H0')
    log('── F1d 状態C（vw−ew）・H0')
    fam_eval('F1d', 'C', 'H0')

    # F0（文脈・判定しない）: 同じ国×月の集合で X を持ち続けた場合
    ctx = {}
    for x in XS:
        crow = {}
        for c in countries:
            st = {t: (True if v is not None else None) for t, v in SIG['A'][c].items()}
            rows = run_country(st, XX[c][x], mk['vw'][c], nst_ok[c], unit_cost(c, x), TURN[x], 'H0')
            if rows:
                crow[c] = rows
        s, b, sn, nc = pool(crow)
        ev = {'full': compact(M.excess_stats(s, b)), 'train': compact(M.excess_stats(s, b, z=M.TRAIN_END)),
              'hold': compact(M.excess_stats(s, b, a=M.HOLD_START)), 'hold_net': compact(M.excess_stats(sn, b, a=M.HOLD_START))}
        ctx[x] = ev
        tested.append({'name': f'F0_always_{x}', 'family': 'F0_context', 'graded': False, 'label': '文脈（既知の上乗せ）',
                       'description': f'状態Aが定義される国×月で、常に X＝{DESC_X[x]} を持つ（局面の条件なし）', **ev})
        log(f'F0 常に{x}: 全期間 {(ev["full"] or {}).get("ex_ann")} t{(ev["full"] or {}).get("t")}・保有 {(ev["hold"] or {}).get("ex_ann")} t{(ev["hold"] or {}).get("t")}')

    # 一国ずつ外す・新しい答え合わせ・先進国/新興国
    loo, fresh, split, cost2 = {}, {}, {}, {}
    first_on = {}
    for c in countries:
        ts = [t for t, v in SIG['A'][c].items() if v is True and nst_ok[c](t)]
        if ts:
            first_on[c] = min(ts)
    late = {c for c, t in first_on.items() if t >= M.HOLD_START}
    for (fam, x), crow in CROW.items():
        rows = []
        for c in crow:
            s, b, sn, _ = pool(crow, exclude=(c,))
            f, h = M.excess_stats(s, b), M.excess_stats(s, b, a=M.HOLD_START)
            rows.append((c, f['ex_ann'] if f else None, h['ex_ann'] if h else None, h['t'] if h else None))
        hv = [r for r in rows if r[2] is not None]
        loo[f'{fam}_{x}'] = {'hold_min': min(hv, key=lambda r: r[2]) if hv else None, 'hold_max': max(hv, key=lambda r: r[2]) if hv else None,
                             'full_min': min((r for r in rows if r[1] is not None), key=lambda r: r[1], default=None),
                             'full_max': max((r for r in rows if r[1] is not None), key=lambda r: r[1], default=None),
                             'hold_sign_changes_when_dropping': [r[0] for r in hv if (r[2] > 0) != ((tested_by(tested, f'{fam}_{x}')['hold'] or {}).get('ex_ann', 0) > 0)]}
        if fam == 'F1':
            s, b, sn, nc = pool(crow, only=late)
            fresh[f'late_runup_{x}'] = {'countries': sorted(late & set(crow)), 'hold': compact(M.excess_stats(s, b, a=M.HOLD_START)),
                                        'full': compact(M.excess_stats(s, b))}
            tested.append({'name': f'FR_late_{x}', 'family': 'fresh', 'graded': False, 'label': '新しい答え合わせ（報告）',
                           'description': f'最初の独走（状態A）が2007年以降に始まった国だけ・X＝{DESC_X[x]}', **fresh[f'late_runup_{x}']})
            for nm, grp in (('developed', DEVELOPED), ('emerging', set(countries) - DEVELOPED)):
                s, b, sn, nc = pool(crow, only=grp)
                split[f'{nm}_{x}'] = {'full': compact(M.excess_stats(s, b)), 'train': compact(M.excess_stats(s, b, z=M.TRAIN_END)),
                                      'hold': compact(M.excess_stats(s, b, a=M.HOLD_START))}
                tested.append({'name': f'SPLIT_{nm}_{x}', 'family': 'split', 'graded': False, 'label': '報告',
                               'description': f'F1 を{nm}の国だけで・X＝{DESC_X[x]}', **split[f'{nm}_{x}']})
            s, b, sn, nc = pool(crow, cost_mult=2.0)
            cost2[x] = compact(M.excess_stats(sn, b, a=M.HOLD_START))

    # F2（報告）
    log('── F2（報告）次の60か月の (X−vw) を状態に回帰')
    f2 = {}
    for sg in ('A', 'B', 'C'):
        for x in XS:
            for h, L in ((60, 60), (36, 36), (12, 12)):
                allrows, per = [], {}
                for c in countries:
                    rr = forward_rows(SIG[sg][c], XX[c][x], mk['vw'][c], nst_ok[c], h)
                    allrows += rr
                    ins = [r[2] for r in rr if r[1]]
                    outs = [r[2] for r in rr if not r[1]]
                    if len(ins) >= 12 and len(outs) >= 12:
                        per[c] = round((S.mean(ins) - S.mean(outs)) * 100, 2)
                reg = dk_reg(allrows, L)
                key = f'F2_{sg}_{x}_h{h}'
                f2[key] = {'reg': reg, 'countries_with_both': len(per), 'countries_in_gt_out': sum(1 for v in per.values() if v > 0),
                           'per_country_diff': per if h == 60 else None}
                tested.append({'name': key, 'family': 'F2_report', 'graded': False, 'label': '報告（条件つきの差）',
                               'description': f'{DESC_SIG[sg]}の月とそれ以外で、次の{h}か月の (X−vw) の平均（年率%）を比べる・X＝{DESC_X[x]}・DK ラグ{L}',
                               **f2[key]})
                if h == 60:
                    log(f'{key}: {reg}・国 {f2[key]["countries_in_gt_out"]}/{f2[key]["countries_with_both"]}')
    # 当月の上乗せ（t+1 の X−vw）: 状態の月 vs それ以外（国をまたいで月ごとに平均→差の系列）
    contemp = {}
    for sg in ('A', 'B', 'C'):
        for x in XS:
            ins_m, outs_m = collections.defaultdict(list), collections.defaultdict(list)
            for c in countries:
                for t, v in SIG[sg][c].items():
                    if v is None or not nst_ok[c](t):
                        continue
                    m = addm(t, 1)
                    if m in XX[c][x] and m in mk['vw'][c]:
                        (ins_m if v else outs_m)[m].append(XX[c][x][m] - mk['vw'][c][m])
            d = [S.mean(ins_m[m]) - S.mean(outs_m[m]) for m in sorted(ins_m) if m in outs_m]
            di = [S.mean(ins_m[m]) for m in sorted(ins_m)]
            tt = M.nw_t(d) if len(d) >= 24 else None
            ti = M.nw_t(di) if len(di) >= 24 else None
            contemp[f'{sg}_{x}'] = {'months_both': len(d), 'diff_ann': round(S.mean(d) * 1200, 2) if d else None, 't': round(tt, 2) if tt else None,
                                    'in_state_ann': round(S.mean(di) * 1200, 2) if di else None, 't_in': round(ti, 2) if ti else None}
            tested.append({'name': f'CT_{sg}_{x}', 'family': 'F2_report', 'graded': False, 'label': '報告（当月の差）',
                           'description': f'{DESC_SIG[sg]}の国の翌月の (X−vw) の月平均 − 状態に無い国の同じ月の平均・X＝{DESC_X[x]}', **contemp[f'{sg}_{x}']})

    # 独立な局面
    eps_all = {}
    for sg in ('A', 'B', 'C'):
        lst = []
        for c in countries:
            for e in episodes(SIG[sg][c], RR['A' if sg in 'AB' else 'C'][c], nst_ok[c]):
                e = dict(e, country=c, note=known_note(c, e))
                lst.append(e)
        lst.sort(key=lambda e: (e['start'], e['country']))
        eps_all[sg] = {'n': len(lst), 'n_countries': len({e['country'] for e in lst}),
                       'n_start_2007_on': sum(1 for e in lst if e['start'] >= M.HOLD_START),
                       'n_start_by_2006': sum(1 for e in lst if e['start'] <= M.TRAIN_END), 'list': lst}
        log(f'局面 {sg}: {eps_all[sg]["n"]}（{eps_all[sg]["n_countries"]}か国・〜2006始まり {eps_all[sg]["n_start_by_2006"]}・2007〜 {eps_all[sg]["n_start_2007_on"]}）')

    # ───── 米国（F3）─────
    log('── F3 米国（French Mkt が相手）')
    import mw_gate_proxy as GP
    p1, p1info = GP.composite(GP.load('usa'), GP.MEASURES, 'good')
    p1 = {m: v for m, v in p1.items() if m >= START_US_ACC}
    turn_p1 = GP.turnover(GP.MEASURES, 'good')
    XU = build_X('usa', mk, nst, START_US_ACC)
    XU['P1'] = p1
    TURN_US = dict(TURN, P1=turn_p1)
    stA_us, pvA_us = own_pct_state(R_us, extra=bind_us)
    # 状態D: 最上位 NYSE 十分位の時価の割合
    ft = M.french_tables('Portfolios_Formed_on_ME')
    nf, sz = ft['Number of Firms in Portfolios'], ft['Average Firm Size']
    dec = ['Lo 10', '2-Dec', '3-Dec', '4-Dec', '5-Dec', '6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']
    ci = [nf['cols'].index(k) for k in dec]
    share = {}
    for d, row in nf['data'].items():
        r2 = sz['data'].get(d)
        if r2 is None:
            continue
        v = [(row[i], r2[i]) for i in ci]
        if any(a is None or b_ is None or a < 0 or b_ < 0 for a, b_ in v):
            continue
        tot = sum(a * b_ for a, b_ in v)
        if tot > 0:
            share[d] = v[-1][0] * v[-1][1] / tot
    stD_us, pvD_us = own_pct_state(share)
    us_sig = {'A': stA_us, 'D': stD_us}
    us_res = {}
    for fam, sg in (('F3', 'A'), ('F3b', 'D')):
        res = {}
        for x in XS + ['P1']:
            rows = run_country(us_sig[sg], XU[x], FR_MKTRF, None, unit_cost('usa', x), TURN_US[x], 'H0')
            s, b, sn, _ = pool({'usa': rows})
            if fam == 'F3' and x in XS:
                repl = next(t for t in tested if t['name'] == f'F1_{x}')['repl']
            else:
                repl = None
            res[x] = evaluate(s, b, sn, {'repl': repl, 'activity': activity({'usa': rows})})
            CROW[(fam, x)] = {'usa': rows}
        ph = M.holm({x: res[x]['hold']['p'] if res[x]['hold'] else None for x in res})
        for x, ev in res.items():
            g, cr = M.grade(ev['full'], ev['train'], ev['hold'], ev['roll20'], cost_hold=ev['hold_net'], repl=ev['repl'],
                            family_holm_p=ph.get(x), sharpe_pair=ev['sharpe_pair'], leveraged_or_timing=True)
            ent = {'name': f'{fam}_{x}', 'family': fam, 'graded': True, 'label': '主（米国）' if fam == 'F3' else '副（米国・水準）',
                   'signal': sg, 'rule': 'H0', 'X': x,
                   'description': f'米国: {DESC_SIG[sg]}のとき X＝{DESC_X[x]}、それ以外は French Mkt',
                   'holm_p': ph.get(x), 'grade': g, 'criteria': cr}
            ent.update(ev)
            tested.append(ent)
            h = ev['hold'] or {}
            log(f'{fam}_{x}: 全期間 {(ev["full"] or {}).get("ex_ann")} t{(ev["full"] or {}).get("t")}・訓練 {(ev["train"] or {}).get("ex_ann")} t{(ev["train"] or {}).get("t")}'
                f'・保有 {h.get("ex_ann")} t{h.get("t")}・20年窓 {(ev["roll20"] or {}).get("win_rate")}・{g}')
        us_res[fam] = res
    # 米国の文脈（常に X）
    for x in XS + ['P1']:
        st = {t: (True if v is not None else None) for t, v in stA_us.items()}
        rows = run_country(st, XU[x], FR_MKTRF, None, unit_cost('usa', x), TURN_US[x], 'H0')
        s, b, sn, _ = pool({'usa': rows})
        ev = {'full': compact(M.excess_stats(s, b)), 'train': compact(M.excess_stats(s, b, z=M.TRAIN_END)),
              'hold': compact(M.excess_stats(s, b, a=M.HOLD_START))}
        tested.append({'name': f'F0us_always_{x}', 'family': 'F0_context', 'graded': False, 'label': '文脈（既知）',
                       'description': f'米国: 状態Aが定義される月に常に X＝{DESC_X[x]}（相手 French Mkt）', **ev})
    # 米国の業者の点検（信号・相手とも JKP usa vw）
    R_v = roll_R(us_vw, us_cap)
    stV, _ = own_pct_state(R_v, extra=bind_us)
    common = [t for t in stA_us if t in stV and stA_us[t] is not None and stV[t] is not None]
    agree = sum(1 for t in common if stA_us[t] == stV[t]) / len(common) if common else None
    vendor = {'state_agreement': round(agree, 3) if agree else None, 'months': len(common), 'by_X': {}}
    for x in XS + ['P1']:
        rows = run_country(stV, XU[x], us_vw, None, unit_cost('usa', x), TURN_US[x], 'H0')
        s, b, sn, _ = pool({'usa': rows})
        vendor['by_X'][x] = {'full': compact(M.excess_stats(s, b)), 'train': compact(M.excess_stats(s, b, z=M.TRAIN_END)),
                             'hold': compact(M.excess_stats(s, b, a=M.HOLD_START))}
        tested.append({'name': f'VENDOR_{x}', 'family': 'vendor_check', 'graded': False, 'label': '業者の点検（報告）',
                       'description': f'米国: 信号も相手も JKP usa vw にそろえた版・X＝{DESC_X[x]}', **vendor['by_X'][x]})
    us_eps = {'A': [dict(e, note=known_note('usa', e)) for e in episodes(stA_us, R_us, None)],
              'D': [dict(e, note=known_note('usa', e)) for e in episodes(stD_us, share, None)]}

    # 米国の今（判定に使わない）
    lastA = max(t for t in stA_us)
    lastD = max(t for t in stD_us)
    now = {'A_at': lastA, 'A_R': round(R_us[lastA], 4), 'A_p80': round(pvA_us[lastA], 4), 'A_state': stA_us[lastA],
           'D_at': lastD, 'D_share': round(share[lastD], 4), 'D_p80': round(pvD_us[lastD], 4), 'D_state': stD_us[lastD]}
    try:
        spy, rsp = M.yahoo('SPY'), M.yahoo('RSP')
        Rp = roll_R({m: v - RF.get(m, 0) for m, v in spy.items() if m in RF}, {m: v - RF.get(m, 0) for m, v in rsp.items() if m in RF})
        stP, pvP = own_pct_state(Rp)
        lp = max(Rp)
        now.update({'RSP_proxy_at': lp, 'RSP_proxy_R': round(Rp[lp], 4), 'RSP_proxy_p80': round(pvP[lp], 4) if lp in pvP else None,
                    'RSP_proxy_state': stP.get(lp), 'RSP_proxy_hist_months': len(Rp),
                    'note': 'RSP・SPY は Yahoo（配当込み・生き残り）・French RF は 2026-08 まで。SPY−RSP の過去60か月の累積の対数差'})
    except Exception as e:  # noqa
        now['RSP_proxy_error'] = str(e)
    log('米国の今', now)

    # 健全性
    sanity = {'french_mkt_cagr_full': round(M.cagr(FF['mkt']) * 100, 2), 'french_mkt_cagr_2007_on': round(M.cagr(M.window(FF['mkt'], M.HOLD_START)) * 100, 2),
              'jkp_usa_vw_vs_french': compact(M.excess_stats({m: v + RF[m] for m, v in us_vw.items() if m in RF}, FF['mkt'])),
              'thr_us_B': round(thr_us, 4), 'R_us_first': min(R_us), 'stateA_us_first_defined': min(t for t, v in stA_us.items() if v is not None),
              'good_sides_us_to_2006': GOOD, 'p1_info': {k: p1info[k] for k in ('need', 'months', 'from', 'to')},
              'no_lookahead': '信号は月 t の末までの値（R は t までの60か月・分位は t までの履歴）で作り、保有は t+1（run_country の m = addm(t,1)）',
              'excess_vs_total': 'JKP の超過と French Mkt-RF に French RF を足して総リターンどうしで比べる'}
    log('健全性', sanity)

    graded = [t for t in tested if t.get('graded')]
    cnt = collections.Counter(t['grade'] for t in graded)
    out = {'angle': ANGLE, 'prereg': PREREG, 'prereg_commit': sha_first(f'out/{PREREG}'), 'global_prereg': 'mw_prereg.json',
           'global_prereg_commit': sha_first('out/mw_prereg.json'),
           'n_tested': len(tested), 'n_graded': len(graded), 'grade_counts': dict(cnt),
           'tested': tested, 'loo': loo, 'fresh_late_runup_countries': sorted(late), 'first_state_A': first_on,
           'cost_x2_hold_F1': cost2, 'F2_contemporaneous': contemp, 'episodes': eps_all, 'us_episodes': us_eps, 'us_now': now,
           'vendor_check': vendor, 'sanity': sanity, 'log': LOG}
    p = M.save('mw_concentration_regime.json', out)
    log('書いた', p, os.path.getsize(p))


def tested_by(tested, name):
    return next(t for t in tested if t['name'] == name)


if __name__ == '__main__':
    main(check='--check' in sys.argv)
