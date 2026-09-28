#!/usr/bin/env python3
"""night/mw_fmom_wf.py — 角度 fmom_wf: 特性の勢い（ファクター・モメンタム）で買いだけの『良い側の三分位』を
その時点までのデータだけで選び直す（walk-forward）。純粋な時価加重の市場と比べる（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」。
事前登録 out/mw_fmom_wf_prereg.json（族 P・E1〜E5・規則・費用・C5 の単位）を**測る前に**コミットしてから回す。
線は out/mw_prereg.json（C1〜C8）を night/mw_common.grade でそのまま当てる。線は結果を見て動かさない。

  python3 night/mw_fmom_wf.py             → out/mw_fmom_wf.json
  python3 night/mw_fmom_wf.py --selftest  → 合成データで『月末 t の選択が t までのデータだけで決まる』ことを検算するだけ

約束（mw_common と同じ）: 月次リターンは小数・キーは yyyymm。欠測は0と読まない（ルール7）。
JKP の三分位は超過（米国T-bill を引いた値）＝French の Mkt-RF と超過どうしで比べる。
"""
import sys, os, json, math, subprocess, statistics as S, random, csv, io, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
OUT = 'mw_fmom_wf.json'
PRE_FILES = ['mw_fmom_wf_prereg.json']
NMIN = 10            # 三分位の銘柄数がこれ未満の月は欠測（事前登録）
MINC = 30            # 候補が30本未満の月は戦略を作らない（事前登録）
JKP_END = 202512
POSTPUB = 202001
REGIONS = ['world_ex_us', 'developed', 'emerging', 'jpn']
MKT_TURN, MKT_COST = 5.0, 0.001   # 市場へ逃げる月（事前登録）
TR, HS, RS = M.TRAIN_END, M.HOLD_START, M.RECENT_START
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


# ───────────────────────── 暦 ─────────────────────────
def cal(a, z):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= z:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ───────────────────────── データ ─────────────────────────
AV = json.load(open(os.path.join(BASE, 'out', '_mw_cache', 'jkp_availability.json')))
CHARS = [k for k in AV['portfolios']['usa'] if k != 'all_factors']
_FUS = json.load(open(os.path.join(BASE, 'out', 'mw_factor_us_prereg.json')))['families']['a_jkp_tercile_vw']['list']
TURN = {x['key']: (float(x['turnover_pct']), float(x['cost_per_100pct'])) for x in _FUS}
CLUSTER = {}
for row in csv.DictReader(io.StringIO(M.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Cluster%20Labels.csv',
                                            name='jkp_cluster_labels.csv').decode())):
    CLUSTER[row['characteristic']] = row['cluster']
DIRECTION = {}
for k in CHARS:
    d = {x['direction'] for x in M.jkp_rows('usa', k, 'factor', 'vw')}
    assert len(d) == 1, (k, d)
    DIRECTION[k] = int(float(d.pop()))
GOOD = {k: ('3.0' if DIRECTION[k] > 0 else '1.0') for k in CHARS}
BAD = {k: ('1.0' if DIRECTION[k] > 0 else '3.0') for k in CHARS}

FF = M.ff_factors()
MKTRF, RF, MKT = FF['mktrf'], FF['rf'], FF['mkt']


class Data:
    """地域のデータ。asset = ('g', k) 良い側 / ('b', k) 悪い側 / ('t1', k)・('t3', k) 第1・第3 / ('m', None) 市場"""

    def __init__(self, region, raw=None, mkt=None, rf=None, cal_=None):
        self.region = region
        self.pf = {}          # (k, '1.0'|'3.0') -> {ym: ex}
        if raw is None:
            for k in CHARS:
                if k not in AV['portfolios'].get(region, []):
                    continue
                for x in M.jkp_rows(region, k, 'portfolios', 'vw'):
                    if x['ret'] in ('', 'NA', 'na') or x['pf'] not in ('1.0', '3.0'):
                        continue
                    n = x.get('n')
                    if n not in (None, '', 'NA', 'na') and float(n) < NMIN:
                        continue
                    self.pf.setdefault((k, x['pf']), {})[M._ym(x['date'])] = float(x['ret'])
            self.mkt = dict(MKTRF) if region == 'usa' else M.jkp_mkt(region, 'vw')
            self.rf = dict(RF)
        else:
            self.pf, self.mkt, self.rf = raw, mkt, rf
        self.chars = sorted({k for k, _ in self.pf})
        allm = [m for s in self.pf.values() for m in s]
        self.cal = cal_ or cal(min(allm), min(max(allm), JKP_END))
        self.idx = {m: i for i, m in enumerate(self.cal)}
        self._pre = {}
        self._ser = {}

    def ser(self, a):
        if a not in self._ser:
            self._ser[a] = self._ser_build(a)
        return self._ser[a]

    def _ser_build(self, a):
        kind, k = a
        if kind == 'm':
            return self.mkt
        if kind == 'g':
            return self.pf.get((k, GOOD[k]), {})
        if kind == 'b':
            return self.pf.get((k, BAD[k]), {})
        if kind == 't1':
            return self.pf.get((k, '1.0'), {})
        if kind == 't3':
            return self.pf.get((k, '3.0'), {})
        if kind == 'F':      # 良い側−悪い側（両方ある月だけ）
            g, b = self.ser(('g', k)), self.ser(('b', k))
            return {m: g[m] - b[m] for m in g if m in b}
        if kind == 'G':      # 第3−第1（向きを使わない）
            g, b = self.ser(('t3', k)), self.ser(('t1', k))
            return {m: g[m] - b[m] for m in g if m in b}
        if kind == 'D':      # 良い側−市場（情報比の材料）
            g = self.ser(('g', k))
            return {m: g[m] - self.mkt[m] for m in g if m in self.mkt}
        if kind == 'LT':     # log(1+総リターン)（良い側）
            g = self.ser(('g', k))
            return {m: math.log1p(g[m] + self.rf[m]) for m in g if m in self.rf}
        if kind == 'LM':     # log(1+市場の総リターン)
            return {m: math.log1p(self.mkt[m] + self.rf[m]) for m in self.mkt if m in self.rf}
        raise KeyError(a)

    def ret(self, a, m):
        if a[0] == 'm':
            return self.mkt.get(m)
        return self.ser(a).get(m)

    def pre(self, a, how='sum'):
        """累積和の前計算（暦の添字）。how: sum=値の和 / log=log1p の和 / sq=二乗の和"""
        key = (a, how)
        if key not in self._pre:
            s = self.ser(a)
            n = len(self.cal)
            cs, cn = [0.0] * (n + 1), [0] * (n + 1)
            for i, m in enumerate(self.cal):
                v = s.get(m)
                ok = v is not None
                if ok:
                    if how == 'log':
                        assert v > -1, (a, m, v)
                        v = math.log1p(v)
                    elif how == 'sq':
                        v = v * v
                cs[i + 1] = cs[i] + (v if ok else 0.0)
                cn[i + 1] = cn[i] + (1 if ok else 0)
            self._pre[key] = (cs, cn)
        return self._pre[key]

    def win(self, a, i, L, how='sum'):
        """暦の添字 i（月末 t）で終わる L か月の和。L か月すべて値が無ければ None（0で埋めない）"""
        if i - L + 1 < 0:
            return None
        cs, cn = self.pre(a, how)
        if cn[i + 1] - cn[i - L + 1] != L:
            return None
        return cs[i + 1] - cs[i - L + 1]


# ───────────────────────── 選び方（月末 t＝暦の添字 i で、t+1 の重みを返す） ─────────────────────────
def _nxt(D, i):
    return D.cal[i + 1] if i + 1 < len(D.cal) else None


def sel_cs(L, K, pool='good', score='sum'):
    def f(D, i):
        nxt = _nxt(D, i)
        cands = []
        chars_ok = set()
        for k in D.chars:
            kinds = ['g'] if pool == 'good' else ['t1', 't3']
            for kd in kinds:
                a = (kd, k)
                if D.ret(a, nxt) is None:
                    continue
                if score == 'sum':
                    sc = D.win(a, i, L)
                    if sc is None:
                        continue
                else:   # 情報比（良い側−市場）
                    d = ('D', k)
                    s1, s2 = D.win(d, i, L), D.win(d, i, L, 'sq')
                    if s1 is None or s2 is None:
                        continue
                    mu = s1 / L
                    var = (s2 - L * mu * mu) / (L - 1)
                    if var <= 0:
                        continue
                    sc = mu / math.sqrt(var)
                cands.append((-sc, k, kd))
                chars_ok.add(k)
        if len(chars_ok) < MINC:
            return None
        cands.sort()
        top = cands[:K]
        return {(kd, k): 1.0 / len(top) for _, k, kd in top}
    return f


def sel_ts(L, kind='ls'):
    """kind: ls=良い側の F の複利>0 / side=第3−第1 の符号で側を選ぶ / lo=良い側の総リターンの複利>市場"""
    def f(D, i):
        nxt = _nxt(D, i)
        n_ok, pick = 0, []
        lm = D.win(('LM', None), i, L) if kind == 'lo' else None
        if kind == 'lo' and lm is None:
            return None
        for k in D.chars:
            if kind == 'ls':
                if D.ret(('g', k), nxt) is None:
                    continue
                s = D.win(('F', k), i, L, 'log')
                if s is None:
                    continue
                n_ok += 1
                if s > 0:
                    pick.append(('g', k))
            elif kind == 'side':
                s = D.win(('G', k), i, L, 'log')
                if s is None:
                    continue
                a = ('t3', k) if s > 0 else ('t1', k)
                if D.ret(a, nxt) is None:
                    continue
                n_ok += 1
                pick.append(a)
            elif kind == 'lo':
                if D.ret(('g', k), nxt) is None:
                    continue
                s = D.win(('LT', k), i, L)
                if s is None:
                    continue
                n_ok += 1
                if s > lm:
                    pick.append(('g', k))
        if n_ok < MINC:
            return None
        if not pick:
            return {('m', None): 1.0}
        return {a: 1.0 / len(pick) for a in pick}
    return f


def sel_ew():
    def f(D, i):
        nxt = _nxt(D, i)
        pick = [('g', k) for k in D.chars if D.ret(('g', k), nxt) is not None]
        if len(pick) < MINC:
            return None
        return {a: 1.0 / len(pick) for a in pick}
    return f


def sel_cluster(L, K=None, ts=False):
    def f(D, i):
        nxt = _nxt(D, i)
        by = collections.defaultdict(list)
        n = 0
        for k in D.chars:
            if D.ret(('g', k), nxt) is None:
                continue
            if ts:
                if D.win(('F', k), i, L) is None:
                    continue
            else:
                if D.win(('g', k), i, L) is None:
                    continue
            by[CLUSTER.get(k, '?')].append(k)
            n += 1
        cl = {c: ks for c, ks in by.items() if len(ks) >= 2}
        if n < MINC or len(cl) < 10:
            return None
        if not ts:
            sc = sorted((-S.mean(D.win(('g', k), i, L) for k in ks), c) for c, ks in cl.items())
            chosen = [c for _, c in sc[:K]]
        else:
            chosen = []
            for c, ks in sorted(cl.items()):
                lg = 0.0
                for j in range(i - L + 1, i + 1):
                    m = D.cal[j]
                    v = S.mean(D.ser(('F', k))[m] for k in ks)
                    lg += math.log1p(v)
                if lg > 0:
                    chosen.append(c)
            if not chosen:
                return {('m', None): 1.0}
        w = {}
        for c in chosen:
            for k in cl[c]:
                w[('g', k)] = 1.0 / len(chosen) / len(cl[c])
        return w
    return f


# ───────────────────────── 走らせる ─────────────────────────
def asset_cost(a):
    if a[0] == 'm':
        return MKT_TURN, MKT_COST
    return TURN[a[1]] if a[0] == 'g' or a[0] in ('t1', 't3', 'b') else (50.0, 0.003)


def simulate(D, select, H):
    """戻り値: ret（超過・費用前）, cost（月の費用・小数）, turnover（月の片道・組み直し分と中身分）, held（月→資産）"""
    w = None
    started = False
    ret, cost, to_sw, to_in, held = {}, {}, {}, {}, {}
    nmiss = 0
    nfail = 0
    for i in range(len(D.cal) - 1):
        t, nxt = D.cal[i], D.cal[i + 1]
        if nxt not in D.mkt or nxt not in D.rf:
            continue
        reb = (H == 1) or (t % 100 == 12)
        if not started and not reb:
            continue
        sw_to, sw_cost = 0.0, 0.0
        if reb:
            tgt = select(D, i)
            if tgt is None:
                if not started:
                    continue
                nfail += 1          # 始まった後に候補が足りない月＝前の重みを漂わせたまま持つ
            else:
                if started:
                    keys = set(tgt) | set(w)
                    for a in keys:
                        dw = abs(tgt.get(a, 0.0) - w.get(a, 0.0))
                        sw_to += 0.5 * dw
                        sw_cost += 0.5 * dw * asset_cost(a)[1]
                w = dict(tgt)
                started = True
        rr = {}
        for a, x in w.items():
            v = D.ret(a, nxt)
            if v is not None:
                rr[a] = v
        if len(rr) < len(w):
            nmiss += len(w) - len(rr)
            tot_w = sum(w[a] for a in rr)
            if tot_w <= 0:
                w = {('m', None): 1.0}
                rr = {('m', None): D.mkt[nxt]}
            else:
                w = {a: w[a] / tot_w for a in rr}
        ex = math.fsum(w[a] * rr[a] for a in rr)
        inner_to = math.fsum(w[a] * asset_cost(a)[0] / 100 / 12 for a in w)
        inner_cost = math.fsum(w[a] * asset_cost(a)[0] / 100 / 12 * asset_cost(a)[1] for a in w)
        ret[nxt] = ex
        cost[nxt] = sw_cost + inner_cost
        to_sw[nxt] = sw_to
        to_in[nxt] = inner_to
        held[nxt] = tuple(sorted(w))
        rf = D.rf[nxt]
        tot = ex + rf
        w = {a: w[a] * (1 + rr[a] + rf) / (1 + tot) for a in w}
    return {'ret': ret, 'cost': cost, 'to_sw': to_sw, 'to_in': to_in, 'held': held, 'nmiss': nmiss, 'nfail': nfail}


# ───────────────────────── 評価 ─────────────────────────
def total(ex, rf):
    return {k: v + rf[k] for k, v in ex.items() if k in rf}


def ann_turn(sim, a=None, z=None):
    ks = [k for k in sim['ret'] if (a is None or k >= a) and (z is None or k <= z)]
    if not ks:
        return None
    return {'switch_pct': round(S.mean(sim['to_sw'][k] for k in ks) * 12 * 100, 1),
            'within_pct': round(S.mean(sim['to_in'][k] for k in ks) * 12 * 100, 1),
            'cost_pct_per_year': round(S.mean(sim['cost'][k] for k in ks) * 12 * 100, 3)}


def top_held(sim, a, z=None, n=12):
    c = collections.Counter()
    ks = [k for k in sim['held'] if k >= a and (z is None or k <= z)]
    for k in ks:
        for x in sim['held'][k]:
            c['/'.join(str(y) for y in x)] += 1
    return {'months': len(ks), 'mean_n_held': round(S.mean(len(sim['held'][k]) for k in ks), 1) if ks else None,
            'top': [(nm, round(v / len(ks), 3)) for nm, v in c.most_common(n)] if ks else []}


def eval_us(sim, jkpmkt):
    ex = sim['ret']
    net = {k: ex[k] - sim['cost'][k] for k in ex}
    tot, tot_net = total(ex, RF), total(net, RF)
    r = {}
    r['start'], r['end'] = min(ex), max(ex)
    r['full'] = M.excess_stats(ex, MKTRF)
    r['train'] = M.excess_stats(ex, MKTRF, z=TR)
    r['hold'] = M.excess_stats(ex, MKTRF, a=HS)
    r['recent'] = M.excess_stats(ex, MKTRF, a=RS)
    r['postpub_2020'] = M.excess_stats(ex, MKTRF, a=POSTPUB)
    r['net_full'] = M.excess_stats(net, MKTRF)
    r['net_train'] = M.excess_stats(net, MKTRF, z=TR)
    r['net_hold'] = M.excess_stats(net, MKTRF, a=HS)
    r['turnover_hold'] = ann_turn(sim, HS)
    r['turnover_full'] = ann_turn(sim)
    r['roll20'] = M.rolling(tot, MKT, 20)
    r['roll20_net'] = M.rolling(tot_net, MKT, 20)
    r['dca20'] = M.dca(tot, MKT, 20)
    r['dca20_net'] = M.dca(tot_net, MKT, 20)
    r['sharpe'] = {'train': (M.sharpe(tot, RF, z=TR), M.sharpe(MKT, RF, a=min(ex), z=TR)),
                   'hold': (M.sharpe(tot, RF, a=HS), M.sharpe(MKT, RF, a=HS, z=JKP_END))}
    r['maxdd'] = {'strategy': round(M.maxdd(tot) * 100, 1), 'market_same_span': round(M.maxdd(M.window(MKT, min(ex), max(ex))) * 100, 1)}
    r['vs_jkp_mkt_vw_hold'] = M.excess_stats(ex, jkpmkt, a=HS)
    r['vs_jkp_mkt_vw_full'] = M.excess_stats(ex, jkpmkt)
    r['held_hold'] = top_held(sim, HS)
    r['held_train_last10y'] = top_held(sim, 199701, TR)
    r['missing_in_hold_count'] = sim['nmiss']
    r['select_fail_after_start'] = sim['nfail']
    return r


def eval_region(sim, D):
    ex = sim['ret']
    net = {k: ex[k] - sim['cost'][k] for k in ex}
    if not ex:
        return {'error': '系列が作れない（候補が30本に届かない）'}
    return {'start': min(ex), 'end': max(ex),
            'full': M.excess_stats(ex, D.mkt), 'hold': M.excess_stats(ex, D.mkt, a=HS),
            'net_full': M.excess_stats(net, D.mkt), 'net_hold': M.excess_stats(net, D.mkt, a=HS),
            'turnover_full': ann_turn(sim)}


# ───────────────────────── 族（事前登録どおり） ─────────────────────────
def families():
    F = collections.OrderedDict()
    F['P_primary'] = [('P1_cs_L12_K10_H1', sel_cs(12, 10), 1, '良い側を過去12か月の超過の和で上位10本・毎月'),
                      ('P2_ts12', sel_ts(12, 'ls'), 1, '過去12か月の F がプラスの良い側をすべて等分（無ければ市場）・毎月'),
                      ('P3_ew_all', sel_ew(), 1, '良い側をすべて等分・毎月')]
    g = []
    for L in (12, 60):
        for K in (5, 10, 20):
            for H in (1, 12):
                if (L, K, H) == (12, 10, 1):
                    continue
                g.append((f'E1_cs_L{L}_K{K}_H{H}', sel_cs(L, K), H, f'良い側を過去{L}か月の超過の和で上位{K}本・{"毎月" if H == 1 else "毎年12月"}'))
    F['E1_grid'] = g
    F['E2_no_direction'] = [('E2_cs_both_L12_K10_H1', sel_cs(12, 10, 'both'), 1, '第1と第3の両方を候補に過去12か月で上位10本・毎月'),
                            ('E2_cs_both_L12_K20_H1', sel_cs(12, 20, 'both'), 1, '同じく上位20本'),
                            ('E2_ts_side12', sel_ts(12, 'side'), 1, '過去12か月の(第3−第1)の符号で側を選び全特性を等分・毎月')]
    F['E3_short_formation'] = [('E3_cs_L1_K10_H1', sel_cs(1, 10), 1, '良い側を過去1か月の超過で上位10本・毎月'),
                               ('E3_ts1', sel_ts(1, 'ls'), 1, '過去1か月の F がプラスの良い側をすべて等分（無ければ市場）')]
    F['E4_cluster'] = [('E4_cluster_cs_L12_K3_H1', sel_cluster(12, 3), 1, '13群を過去12か月で上位3群・群ごとに1/3・群の中は等分'),
                       ('E4_cluster_ts12', sel_cluster(12, ts=True), 1, '群の F の過去12か月の複利がプラスの群をすべて（無ければ市場）')]
    F['E5_long_only_signal'] = [('E5_ts_lo12', sel_ts(12, 'lo'), 1, '過去12か月に市場に勝った良い側をすべて等分（無ければ市場）'),
                                ('E5_cs_ir_L12_K10_H1', sel_cs(12, 10, score='ir'), 1, '過去12か月の情報比で上位10本・毎月'),
                                ('E5_cs_ir_L60_K10_H12', sel_cs(60, 10, score='ir'), 12, '過去60か月の情報比で上位10本・毎年12月')]
    return F


PRIMARY_FAMILIES = {'P_primary'}


# ───────────────────────── 検算 ─────────────────────────
def selftest():
    rnd = random.Random(7)
    months = cal(200001, 200512)
    raw = {}
    for j in range(80):
        k = CHARS[j]
        for side in ('1.0', '3.0'):
            raw[(k, side)] = {m: rnd.gauss(0.005, 0.05) for m in months}
    mkt = {m: rnd.gauss(0.005, 0.04) for m in months}
    rf = {m: 0.002 for m in months}
    D = Data('test', raw, mkt, rf, months)
    sel = sel_cs(3, 5)
    sim = simulate(D, sel, 1)
    # 手計算: 月末 t の上位5本（t−2..t の和）の t+1 の平均
    bad = 0
    for i in range(5, len(months) - 1):
        t, nxt = months[i], months[i + 1]
        sc = sorted((-(sum(raw[(k, GOOD[k])][months[j]] for j in range(i - 2, i + 1))), k) for k in D.chars)
        top = [k for _, k in sc[:5]]
        exp = S.mean(raw[(k, GOOD[k])][nxt] for k in top)
        if abs(sim['ret'][nxt] - exp) > 1e-12:
            bad += 1
    # 先の月を書き換えても t の選択が変わらないこと
    i = 30
    w1 = sel(D, i)
    raw2 = {a: {m: (v if m <= months[i] else rnd.gauss(0, 0.08)) for m, v in s.items()} for a, s in raw.items()}
    D2 = Data('test', raw2, mkt, rf, months)
    w2 = sel_cs(3, 5)(D2, i)
    # 時系列版: 先の月の書き換えで選択が変わらないこと
    t1 = sel_ts(3, 'ls')(D, i); t2 = sel_ts(3, 'ls')(D2, i)
    c1 = sel_cluster(3, 3)(D, i); c2 = sel_cluster(3, 3)(D2, i)
    ok = bad == 0 and w1 == w2 and t1 == t2 and c1 == c2
    print('selftest', 'OK' if ok else 'NG', 'mismatch months', bad, 'cs same', w1 == w2, 'ts same', t1 == t2, 'cluster same', c1 == c2)
    return ok


def sanity(DUS, jkpmkt):
    s = {}
    s['french_mkt_cagr_full'] = round(M.cagr(MKT) * 100, 2)
    s['french_mkt_cagr_2007'] = round(M.cagr(M.window(MKT, HS)) * 100, 2)
    s['jkp_mkt_vw_minus_french_full_pct'] = M.excess_stats(jkpmkt, MKTRF)['ex_ann']
    s['jkp_mkt_vw_minus_french_2007_pct'] = M.excess_stats(jkpmkt, MKTRF, a=HS)['ex_ann']
    gs = {}
    for k in CHARS:
        g, _ = M.jkp_good_side('usa', k, 'vw', upto=TR)
        gs[k] = g
    s['good_side_train_equals_direction'] = sum(1 for k in CHARS if gs[k] == GOOD[k])
    s['n_chars'] = len(CHARS)
    # P3 の手計算（2010-06）
    i = DUS.idx[201005]
    w = sel_ew()(DUS, i)
    hand = S.mean(DUS.pf[(k, GOOD[k])][201006] for k in CHARS if 201006 in DUS.pf.get((k, GOOD[k]), {}))
    s['p3_hand_check_201006'] = {'engine': round(sum(w[a] * DUS.ret(a, 201006) for a in w), 8), 'hand': round(hand, 8)}
    return s


# ───────────────────────── 本体 ─────────────────────────
def main():
    if not selftest():
        raise SystemExit('selftest NG')
    pre = [{'file': f'out/{p}', 'commit': sha_of(f'out/{p}')} for p in PRE_FILES]
    log('prereg', pre)
    DUS = Data('usa')
    jkpmkt = M.jkp_mkt('usa', 'vw')
    san = sanity(DUS, jkpmkt)
    log('sanity', san)
    DR = {r: Data(r) for r in REGIONS}
    FAM = families()
    res = collections.OrderedDict()
    for fam, lst in FAM.items():
        for name, sel, H, desc in lst:
            sim = simulate(DUS, sel, H)
            r = eval_us(sim, jkpmkt)
            reg = {}
            for rg in REGIONS:
                reg[rg] = eval_region(simulate(DR[rg], sel, H), DR[rg])
            npos = sum(1 for v in reg.values() if v.get('full') and v['full']['ex_ann'] > 0)
            r['repl'] = {'regions': len(REGIONS), 'positive': npos, 'by_region': reg,
                         'hold_positive': sum(1 for v in reg.values() if v.get('hold') and v['hold']['ex_ann'] > 0),
                         'net_full_positive': sum(1 for v in reg.values() if v.get('net_full') and v['net_full']['ex_ann'] > 0)}
            r.update({'name': name, 'family': fam, 'primary': fam in PRIMARY_FAMILIES, 'H': H, 'description': desc})
            res[name] = r
            h = r['hold'] or {}
            log(f"{name:28s} full {r['full']['ex_ann']:+.2f} t{r['full']['t']}  train {r['train']['ex_ann'] if r['train'] else None} t{r['train']['t'] if r['train'] else None}"
                f"  hold {h.get('ex_ann')} t{h.get('t')} cagr{h.get('cagr_diff')}  net_hold {r['net_hold']['ex_ann']}  repl {npos}/4  turn {r['turnover_hold']}")
    # Holm（族ごと・角度全体）
    allp = {}
    for fam, lst in FAM.items():
        ps = {n: (res[n]['hold'] or {}).get('p') for n, _, _, _ in lst}
        hm = M.holm(ps)
        for n in ps:
            res[n]['holm_p_family'] = hm.get(n)
        allp.update(ps)
    hall = M.holm(allp)
    for n in res:
        res[n]['holm_p_all24'] = hall.get(n)
    # 判定
    for n, r in res.items():
        g, c = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['net_hold'], repl=r['repl'],
                       family_holm_p=r['holm_p_family'], leveraged_or_timing=False)
        r['grade'], r['criteria'] = g, c
        g2, _ = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['net_hold'], repl=r['repl'],
                        family_holm_p=r['holm_p_all24'], leveraged_or_timing=False)
        r['grade_if_holm_all24'] = g2
        log(f"{n:28s} grade {g} {c}")
    out = {'angle': 'fmom_wf', 'prereg': pre, 'global_prereg': 'out/mw_prereg.json', 'sanity': san,
           'benchmark': 'French Mkt-RF（超過どうし）。転がる20年窓・積立は総リターン（戦略超過＋French RF 対 French Mkt）',
           'n_tested': len(res), 'families': {f: [x[0] for x in l] for f, l in FAM.items()},
           'tested': list(res.values()), 'log_tail': LOG[-80:]}
    p = M.save(OUT, out)
    log('saved', p, os.path.getsize(p))


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        ok = selftest()
        sys.exit(0 if ok else 1)
    main()
