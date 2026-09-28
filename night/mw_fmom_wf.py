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
PRE_FILES = ['mw_fmom_wf_prereg.json', 'mw_fmom_wf_prereg2.json']
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

    def __init__(self, region, raw=None, mkt=None, rf=None, cal_=None, minc=MINC, end=JKP_END, turn=None):
        self.region = region
        self.minc = minc
        self.turn = turn or TURN
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
        self.cal = cal_ or cal(min(allm), min(max(allm), end))
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

    def asset_cost(self, a):
        if a[0] == 'm':
            return MKT_TURN, MKT_COST
        return self.turn[a[1]]

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
            cs, cn, cneg, czero = [0.0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
            for i, m in enumerate(self.cal):
                v = s.get(m)
                ok = v is not None
                neg = zero = 0
                if ok:
                    if how == 'log':
                        # 複利 Π(1+v) を符号つきでそのまま扱う（1+v≤0 の月が地域の初期データにある）
                        if 1 + v == 0:
                            zero, v = 1, 0.0
                        else:
                            neg = 1 if 1 + v < 0 else 0
                            v = math.log(abs(1 + v))
                    elif how == 'sq':
                        v = v * v
                cs[i + 1] = cs[i] + (v if ok else 0.0)
                cn[i + 1] = cn[i] + (1 if ok else 0)
                cneg[i + 1] = cneg[i] + neg
                czero[i + 1] = czero[i] + zero
            self._pre[key] = (cs, cn, cneg, czero)
        return self._pre[key]

    def win(self, a, i, L, how='sum'):
        """暦の添字 i（月末 t）で終わる L か月の和。L か月すべて値が無ければ None（0で埋めない）"""
        if i - L + 1 < 0:
            return None
        cs, cn, cneg, czero = self.pre(a, how)
        if cn[i + 1] - cn[i - L + 1] != L:
            return None
        if how == 'log':
            # 戻り値 > 0 ⇔ Π(1+v) − 1 > 0（積が0か負なら −inf）
            if czero[i + 1] - czero[i - L + 1] > 0 or (cneg[i + 1] - cneg[i - L + 1]) % 2 == 1:
                return float('-inf')
        return cs[i + 1] - cs[i - L + 1]


# ───────────────────────── 選び方（月末 t＝暦の添字 i で、t+1 の重みを返す） ─────────────────────────
def _nxt(D, i):
    return D.cal[i + 1] if i + 1 < len(D.cal) else None


def sel_cs(L, K, pool='good', score='sum', uni=None, buf=None):
    """K='q' は ceil(特性数/4)。buf=2 なら上位 K で買い、順位が 2K より下がるまで持つ（緩衝帯）"""
    def f(D, i, prev=None):
        nxt = _nxt(D, i)
        Kk = math.ceil(len(D.chars) / 4) if K == 'q' else K
        cands = []
        chars_ok = set()
        for k in D.chars:
            if uni is not None and k not in uni:
                continue
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
        if len(chars_ok) < D.minc:
            return None
        cands.sort()
        if not buf:
            top = [(kd, k) for _, k, kd in cands[:Kk]]
        else:
            rank = {(kd, k): r for r, (_, k, kd) in enumerate(cands)}
            keep = sorted((a for a in (prev or {}) if a in rank and rank[a] < buf * Kk), key=lambda a: rank[a])[:Kk]
            for _, k, kd in cands:
                if len(keep) >= Kk:
                    break
                if (kd, k) not in keep:
                    keep.append((kd, k))
            top = keep
        return {a: 1.0 / len(top) for a in top}
    return f


def sel_ts(L, kind='ls', uni=None):
    """kind: ls=良い側の F の複利>0 / side=第3−第1 の符号で側を選ぶ / lo=良い側の総リターンの複利>市場"""
    def f(D, i, prev=None):
        nxt = _nxt(D, i)
        n_ok, pick = 0, []
        lm = D.win(('LM', None), i, L) if kind == 'lo' else None
        if kind == 'lo' and lm is None:
            return None
        for k in D.chars:
            if uni is not None and k not in uni:
                continue
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
        if n_ok < D.minc:
            return None
        if not pick:
            return {('m', None): 1.0}
        return {a: 1.0 / len(pick) for a in pick}
    return f


def sel_ew(uni=None):
    def f(D, i, prev=None):
        nxt = _nxt(D, i)
        pick = [('g', k) for k in D.chars if (uni is None or k in uni) and D.ret(('g', k), nxt) is not None]
        if len(pick) < D.minc:
            return None
        return {a: 1.0 / len(pick) for a in pick}
    return f


def sel_cluster(L, K=None, ts=False):
    def f(D, i, prev=None):
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
        if n < D.minc or len(cl) < 10:
            return None
        if not ts:
            sc = sorted((-S.mean(D.win(('g', k), i, L) for k in ks), c) for c, ks in cl.items())
            chosen = [c for _, c in sc[:K]]
        else:
            chosen = []
            for c, ks in sorted(cl.items()):
                pr = 1.0
                for j in range(i - L + 1, i + 1):
                    m = D.cal[j]
                    v = S.mean(D.ser(('F', k))[m] for k in ks)
                    pr *= 1 + v
                if pr - 1 > 0:
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
            tgt = select(D, i, w)
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
                        sw_cost += 0.5 * dw * D.asset_cost(a)[1]
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
        inner_to = math.fsum(w[a] * D.asset_cost(a)[0] / 100 / 12 for a in w)
        inner_cost = math.fsum(w[a] * D.asset_cost(a)[0] / 100 / 12 * D.asset_cost(a)[1] for a in w)
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


def eval_gen(sim, mktrf, rf, label_end=None):
    """一般の評価（超過どうし）。転がる20年窓・積立・シャープは総リターン（超過＋RF 対 市場の超過＋RF）"""
    ex = sim['ret']
    net = {k: ex[k] - sim['cost'][k] for k in ex}
    tot, tot_net = total(ex, rf), total(net, rf)
    mkt_tot = total(mktrf, rf)
    r = {}
    r['start'], r['end'] = min(ex), max(ex)
    r['full'] = M.excess_stats(ex, mktrf)
    r['train'] = M.excess_stats(ex, mktrf, z=TR)
    r['hold'] = M.excess_stats(ex, mktrf, a=HS)
    r['recent'] = M.excess_stats(ex, mktrf, a=RS)
    r['postpub_2020'] = M.excess_stats(ex, mktrf, a=POSTPUB)
    r['net_full'] = M.excess_stats(net, mktrf)
    r['net_train'] = M.excess_stats(net, mktrf, z=TR)
    r['net_hold'] = M.excess_stats(net, mktrf, a=HS)
    r['turnover_hold'] = ann_turn(sim, HS)
    r['turnover_full'] = ann_turn(sim)
    r['roll20'] = M.rolling(tot, mkt_tot, 20)
    r['roll20_net'] = M.rolling(tot_net, mkt_tot, 20)
    r['dca20'] = M.dca(tot, mkt_tot, 20)
    r['dca20_net'] = M.dca(tot_net, mkt_tot, 20)
    r['sharpe'] = {'train': (M.sharpe(tot, rf, z=TR), M.sharpe(mkt_tot, rf, a=min(ex), z=TR)),
                   'hold': (M.sharpe(tot, rf, a=HS), M.sharpe(mkt_tot, rf, a=HS, z=max(ex)))}
    r['maxdd'] = {'strategy': round(M.maxdd(tot) * 100, 1), 'market_same_span': round(M.maxdd(M.window(mkt_tot, min(ex), max(ex))) * 100, 1)}
    r['held_hold'] = top_held(sim, HS)
    r['held_train_last10y'] = top_held(sim, 199701, TR)
    r['missing_in_hold_count'] = sim['nmiss']
    r['select_fail_after_start'] = sim['nfail']
    return r


def eval_us(sim, jkpmkt):
    r = eval_gen(sim, MKTRF, RF)
    ex = sim['ret']
    r['vs_jkp_mkt_vw_hold'] = M.excess_stats(ex, jkpmkt, a=HS)
    r['vs_jkp_mkt_vw_full'] = M.excess_stats(ex, jkpmkt)
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

# ───────────────────────── 第2次（out/mw_fmom_wf_prereg2.json） ─────────────────────────
LOWTO = frozenset(k for k in CHARS if TURN[k][0] <= 100)


def families2():
    F = collections.OrderedDict()
    F['Q1_us_cost_aware'] = [
        ('Q1a_cs_L12_K10_H1_lowTO', sel_cs(12, 10, uni=LOWTO), 1, '回転の少ない112特性で上位10本・毎月'),
        ('Q1b_cs_L12_K10_H1_lowTO_buf20', sel_cs(12, 10, uni=LOWTO, buf=2), 1, '回転の少ない112特性で上位10本・20位まで持つ緩衝帯'),
        ('Q1c_ts12_lowTO', sel_ts(12, 'ls', uni=LOWTO), 1, '回転の少ない112特性で過去12か月の F がプラスの良い側（無ければ市場）'),
        ('Q1d_ew_lowTO', sel_ew(uni=LOWTO), 1, '回転の少ない112特性の良い側をすべて等分'),
        ('Q1e_cs_L12_K10_H1_buf20', sel_cs(12, 10, buf=2), 1, '全153特性で上位10本・20位まで持つ緩衝帯')]
    return F


def rules_q2():
    return [('ts12', sel_ts(12, 'ls'), 1, '過去12か月の F がプラスの良い側をすべて等分（無ければ市場）'),
            ('cs_L12_Kq', sel_cs(12, 'q'), 1, '過去12か月の超過の和で上位 ceil(特性数/4) 本'),
            ('ew', sel_ew(), 1, '良い側をすべて等分'),
            ('ts_lo12', sel_ts(12, 'lo'), 1, '過去12か月に市場に勝った良い側をすべて等分（無ければ市場）'),
            ('ts1', sel_ts(1, 'ls'), 1, '過去1か月の F がプラスの良い側をすべて等分（無ければ市場）')]


FR_US = [('fr_bm', '25_Portfolios_5x5', 'BIG HiBM', 'BIG LoBM', 30),
         ('fr_op', '25_Portfolios_ME_OP_5x5', 'BIG HiOP', 'BIG LoOP', 30),
         ('fr_inv', '25_Portfolios_ME_INV_5x5', 'BIG LoINV', 'BIG HiINV', 50),
         ('fr_mom', '25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 150),
         ('fr_str', '25_Portfolios_ME_Prior_1_0', 'BIG LoPRIOR', 'BIG HiPRIOR', 800),
         ('fr_ltr', '25_Portfolios_ME_Prior_60_13', 'BIG LoPRIOR', 'BIG HiPRIOR', 60),
         ('fr_ac', '25_Portfolios_ME_AC_5x5', 'BIG LoAC', 'BIG HiAC', 60),
         ('fr_beta', '25_Portfolios_ME_BETA_5x5', 'BIG LoBETA', 'BIG HiBETA', 50),
         ('fr_ni', '25_Portfolios_ME_NI_5x5', 'BIG NegNI', 'BIG HiNI', 50),
         ('fr_var', '25_Portfolios_ME_VAR_5x5', 'BIG LoVAR', 'BIG HiVAR', 120),
         ('fr_resvar', '25_Portfolios_ME_RESVAR_5x5', 'BIG LoVAR', 'BIG HiVAR', 120)]
FR_REG = [('fr_bm', '25_Portfolios_ME_BE-ME', 'BIG HiBM', 'BIG LoBM', 30),
          ('fr_op', '25_Portfolios_ME_OP', 'BIG HiOP', 'BIG LoOP', 30),
          ('fr_inv', '25_Portfolios_ME_INV', 'BIG LoINV', 'BIG HiINV', 50),
          ('fr_mom', '25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 150)]
FR_EM = [('fr_bm', '6_Portfolios_ME_BE-ME', 'BIG HiBM', 'BIG LoBM', 25),
         ('fr_op', '6_Portfolios_ME_OP', 'BIG HiOP', 'BIG LoOP', 25),
         ('fr_inv', '6_Portfolios_ME_INV', 'BIG LoINV', 'BIG HiINV', 40),
         ('fr_mom', '6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 120)]
FR_REGIONS = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Developed_ex_US', 'Emerging']
FR_INDEP = {'Europe': ['Japan', 'Asia_Pacific_ex_Japan', 'Emerging', 'US'],
            'Japan': ['Europe', 'Asia_Pacific_ex_Japan', 'Emerging', 'US'],
            'Asia_Pacific_ex_Japan': ['Europe', 'Japan', 'Emerging', 'US'],
            'Developed_ex_US': ['Emerging', 'US'],
            'Emerging': ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'US']}
for _k, *_ in FR_US:
    GOOD[_k], BAD[_k] = '3.0', '1.0'


def fr_region_factors(region):
    name = 'Emerging_5_Factors' if region == 'Emerging' else f'{region}_3_Factors'
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly':
            cols = v['cols']
            i_m, i_rf = cols.index('Mkt-RF'), cols.index('RF')
            mk, rf = {}, {}
            for d, row in v['data'].items():
                if row[i_m] is not None and row[i_rf] is not None:
                    mk[d] = row[i_m] / 100
                    rf[d] = row[i_rf] / 100
            return mk, rf
    raise KeyError(name)


def french_data(region):
    """French の巨大株（BIG 行）の良い側・悪い側 → Data。総リターンから同じ地域の RF を引いて超過"""
    if region == 'US':
        spec, mk, rf, minc, cost, prefix = FR_US, MKTRF, RF, 8, 0.001, ''
    elif region == 'Emerging':
        spec, minc, cost, prefix = FR_EM, 3, 0.003, 'Emerging_Markets_'
        mk, rf = fr_region_factors(region)
    else:
        spec, minc, cost, prefix = FR_REG, 3, 0.001, f'{region}_'
        mk, rf = fr_region_factors(region)
    raw, turn, info = {}, {}, {}
    for k, f, gc, bc, to in spec:
        cols = M.french_series(prefix + f, 'Value Weight')
        g, b = cols[gc], cols[bc]
        raw[(k, '3.0')] = {m: v - rf[m] for m, v in g.items() if m in rf}
        raw[(k, '1.0')] = {m: v - rf[m] for m, v in b.items() if m in rf}
        turn[k] = (float(to), cost)
        info[k] = {'file': prefix + f, 'good': gc, 'bad': bc, 'from': min(g), 'to': max(g), 'turnover_pct': to, 'cost': cost}
    D = Data('fr_' + region, raw, dict(mk), dict(rf), None, minc=minc, end=202608, turn=turn)
    D.info = info
    return D


def eval_region_gen(sim, D):
    ex = sim['ret']
    if not ex:
        return {'error': '系列が作れない'}
    net = {k: ex[k] - sim['cost'][k] for k in ex}
    return {'start': min(ex), 'end': max(ex),
            'full': M.excess_stats(ex, D.mkt), 'hold': M.excess_stats(ex, D.mkt, a=HS),
            'net_full': M.excess_stats(net, D.mkt), 'net_hold': M.excess_stats(net, D.mkt, a=HS),
            'turnover_full': ann_turn(sim)}


DEV21 = ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe']
PANEL_EXCL = {'all_countries', 'all_regions', 'developed', 'emerging', 'frontier', 'world', 'world_ex_us', 'usa', 'jpn'}


def sign_p(k, n):
    """片側の符号検定 P(X ≥ k | n, 1/2)"""
    if n == 0:
        return None
    return round(sum(math.comb(n, j) for j in range(k, n + 1)) / 2 ** n, 5)


def panel(sims, mkts, cost_mult=1.0):
    """国々の等分パネル → (戦略の総リターン, 市場の総リターン, 費用後の戦略の総リターン)"""
    s, b, sn = {}, {}, {}
    months = sorted(set().union(*[set(x['ret']) for x in sims.values()])) if sims else []
    for m in months:
        cs = [c for c in sims if m in sims[c]['ret'] and m in mkts[c] and m in RF]
        if not cs:
            continue
        s[m] = S.mean(sims[c]['ret'][m] + RF[m] for c in cs)
        b[m] = S.mean(mkts[c][m] + RF[m] for c in cs)
        sn[m] = S.mean(sims[c]['ret'][m] - cost_mult * sims[c]['cost'][m] + RF[m] for c in cs)
    return s, b, sn


def run_q3(rules):
    """JKP 各国パネル（米国・日本を除く）。rules = [(name, sel, H, desc)]"""
    countries = [c for c in AV['portfolios'] if c not in PANEL_EXCL]
    out = collections.OrderedDict()
    datas = {}
    for c in countries:
        try:
            datas[c] = Data(c)
        except Exception as e:  # noqa
            log('country load fail', c, e)
    for name, sel, H, desc in rules:
        sims, mkts, per = {}, {}, {}
        for c, D in datas.items():
            if not D.pf:
                continue
            sim = simulate(D, sel, H)
            nh = sum(1 for m in sim['ret'] if HS <= m <= JKP_END)
            if nh < 120:
                continue
            sims[c], mkts[c] = sim, D.mkt
            net = {k: sim['ret'][k] - sim['cost'][k] for k in sim['ret']}
            net2 = {k: sim['ret'][k] - 2 * sim['cost'][k] for k in sim['ret']}
            h, hn, hn2 = M.excess_stats(sim['ret'], D.mkt, a=HS), M.excess_stats(net, D.mkt, a=HS), M.excess_stats(net2, D.mkt, a=HS)
            fu = M.excess_stats(sim['ret'], D.mkt)
            per[c] = {'start': min(sim['ret']), 'hold_months': nh,
                      'full_ex': fu and fu['ex_ann'], 'hold_ex': h and h['ex_ann'], 'hold_t': h and h['t'],
                      'net_hold_ex': hn and hn['ex_ann'], 'net2x_hold_ex': hn2 and hn2['ex_ann'],
                      'turn_cost_pct': ann_turn(sim, HS)['cost_pct_per_year'], 'dev': c in DEV21}
        res = {'name': f'Q3_panel_{name}', 'family': 'Q3_jkp_country_panel', 'primary': False, 'H': H,
               'description': f'JKP 各国パネル（米国・日本を除く）: {desc}', 'n_countries': len(sims), 'by_country': per}
        def signs(keys, fld):
            v = [per[c][fld] for c in keys if per[c][fld] is not None]
            k = sum(1 for x in v if x > 0)
            return {'n': len(v), 'positive': k, 'share': round(k / len(v), 3) if v else None, 'sign_p_one_sided': sign_p(k, len(v)),
                    'median': round(S.median(v), 2) if v else None}
        allc = list(per)
        dev = [c for c in allc if per[c]['dev']]
        em = [c for c in allc if not per[c]['dev']]
        res['panel_sign'] = {grp: {fld: signs(ks, fld) for fld in ('hold_ex', 'net_hold_ex', 'net2x_hold_ex', 'full_ex')}
                             for grp, ks in (('all', allc), ('developed21', dev), ('others', em))}
        s_tot, b_tot, sn_tot = panel(sims, mkts)
        _, _, sn2_tot = panel(sims, mkts, 2.0)
        s_ex = {m: v - RF[m] for m, v in s_tot.items()}
        b_ex = {m: v - RF[m] for m, v in b_tot.items()}
        sn_ex = {m: v - RF[m] for m, v in sn_tot.items()}
        sn2_ex = {m: v - RF[m] for m, v in sn2_tot.items()}
        res['start'], res['end'] = min(s_ex), max(s_ex)
        res['full'] = M.excess_stats(s_ex, b_ex)
        res['train'] = M.excess_stats(s_ex, b_ex, z=TR)
        res['hold'] = M.excess_stats(s_ex, b_ex, a=HS)
        res['recent'] = M.excess_stats(s_ex, b_ex, a=RS)
        res['postpub_2020'] = M.excess_stats(s_ex, b_ex, a=POSTPUB)
        res['net_full'] = M.excess_stats(sn_ex, b_ex)
        res['net_hold'] = M.excess_stats(sn_ex, b_ex, a=HS)
        res['net2x_hold'] = M.excess_stats(sn2_ex, b_ex, a=HS)
        res['roll20'] = M.rolling(s_tot, b_tot, 20)
        res['roll20_net'] = M.rolling(sn_tot, b_tot, 20)
        res['dca20'] = M.dca(s_tot, b_tot, 20)
        res['countries_per_month'] = {'train_median': S.median([sum(1 for c in sims if m in sims[c]['ret']) for m in s_ex if m <= TR]) if any(m <= TR for m in s_ex) else None,
                                      'hold_median': S.median([sum(1 for c in sims if m in sims[c]['ret']) for m in s_ex if m >= HS])}
        for grp, ks in (('developed21', dev), ('others', em)):
            ss, bb, snn = panel({c: sims[c] for c in ks}, {c: mkts[c] for c in ks})
            se = {m: v - RF[m] for m, v in ss.items()}; be = {m: v - RF[m] for m, v in bb.items()}; sne = {m: v - RF[m] for m, v in snn.items()}
            res[f'split_{grp}'] = {'full': M.excess_stats(se, be), 'train': M.excess_stats(se, be, z=TR), 'hold': M.excess_stats(se, be, a=HS),
                                   'net_hold': M.excess_stats(sne, be, a=HS)} if se else None
        res['repl'] = None
        out[res['name']] = res
        h = res['hold'] or {}
        log(f"{res['name']:28s} n{len(sims)} full {res['full']['ex_ann']} t{res['full']['t']} train {res['train'] and res['train']['ex_ann']} t{res['train'] and res['train']['t']}"
            f" hold {h.get('ex_ann')} t{h.get('t')} net {res['net_hold']['ex_ann']} net2x {res['net2x_hold']['ex_ann']} sign {res['panel_sign']['all']['hold_ex']}")
    return out


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
def run_family_us(FAM, DUS, DR, jkpmkt, res):
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


def run_q2(res):
    """Q2（米国 French 巨大株）と Q2R（French の地域）"""
    FD = {'US': french_data('US')}
    for rg in FR_REGIONS:
        FD[rg] = french_data(rg)
    src = {rg: D.info for rg, D in FD.items()}
    reg_res = collections.defaultdict(dict)   # rule -> region -> 評価
    for rname, sel, H, desc in rules_q2():
        for rg, D in FD.items():
            sim = simulate(D, sel, H)
            r = eval_gen(sim, D.mkt, D.rf)
            r['n_chars'] = len(D.chars)
            reg_res[rname][rg] = r
    # 米国（Q2）
    for rname, sel, H, desc in rules_q2():
        r = dict(reg_res[rname]['US'])
        indep = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']
        byr = {rg: {k: reg_res[rname][rg][k] for k in ('start', 'end', 'full', 'hold', 'net_full', 'net_hold')} for rg in indep}
        npos = sum(1 for rg in indep if reg_res[rname][rg]['full'] and reg_res[rname][rg]['full']['ex_ann'] > 0)
        r['repl'] = {'regions': len(indep), 'positive': npos, 'by_region': byr}
        nm = {'ts12': 'Q2a_ts12_me5', 'cs_L12_Kq': 'Q2b_cs_L12_Kq_me5', 'ew': 'Q2c_ew_me5', 'ts_lo12': 'Q2d_ts_lo12_me5', 'ts1': 'Q2e_ts1_me5'}[rname]
        r.update({'name': nm, 'family': 'Q2_us_french_megacap', 'primary': False, 'H': H, 'description': 'French 米国 最大五分位の11特性: ' + desc})
        res[nm] = r
        h = r['hold'] or {}
        log(f"{nm:28s} full {r['full']['ex_ann']:+.2f} t{r['full']['t']} train {r['train']['ex_ann']} t{r['train']['t']} hold {h.get('ex_ann')} t{h.get('t')} cagr{h.get('cagr_diff')} net_hold {r['net_hold']['ex_ann']} repl {npos}/3 turn {r['turnover_hold']}")
    # 地域（Q2R）
    for rname, sel, H, desc in rules_q2():
        for rg in FR_REGIONS:
            r = dict(reg_res[rname][rg])
            others = FR_INDEP[rg]
            npos = sum(1 for o in others if reg_res[rname][o]['full'] and reg_res[rname][o]['full']['ex_ann'] > 0)
            r['repl'] = {'regions': len(others), 'positive': npos,
                         'by_region': {o: (reg_res[rname][o]['full'] or {}).get('ex_ann') for o in others}}
            nm = f'Q2R_{rg}_{rname}'
            r.update({'name': nm, 'family': 'Q2R_french_regions', 'primary': False, 'H': H,
                      'description': f'French {rg} の BIG 行 {len(FD[rg].chars)}特性: {desc}'})
            res[nm] = r
            h = r['hold'] or {}
            log(f"{nm:34s} full {r['full']['ex_ann']:+.2f} t{r['full']['t']} train {r['train'] and r['train']['ex_ann']} t{r['train'] and r['train']['t']} hold {h.get('ex_ann')} t{h.get('t')} cagr{h.get('cagr_diff')} net_hold {r['net_hold']['ex_ann']} repl {npos}/{len(others)}")
    return src


def run_posthoc_regions(DR):
    out = {}
    FAM = families()
    for name, sel, H, desc in FAM['P_primary']:
        for rg in REGIONS:
            D = DR[rg]
            sim = simulate(D, sel, H)
            r = eval_gen(sim, D.mkt, D.rf)
            g, c = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['net_hold'], repl=None, family_holm_p=None)
            keep = {k: r[k] for k in ('start', 'end', 'full', 'train', 'hold', 'recent', 'net_hold', 'roll20', 'dca20', 'turnover_hold', 'sharpe', 'maxdd')}
            keep['criteria_for_reference_only'] = c
            keep['note'] = '事後（格付けしない）: 第1次で C5 の答え合わせとして既に見た数字を一つの戦略として並べ直しただけ'
            out[f'X_{rg}_{name}'] = keep
            log(f"X_{rg}_{name:22s} train {r['train'] and r['train']['ex_ann']} t{r['train'] and r['train']['t']} hold {r['hold']['ex_ann']} t{r['hold']['t']} net {r['net_hold']['ex_ann']} roll {r['roll20'] and r['roll20']['win_rate']}")
    return out


def finalize(res, fam_of):
    """族ごとの Holm と角度全体の Holm → 格付け"""
    fams = collections.defaultdict(list)
    for n, r in res.items():
        fams[r['family']].append(n)
    allp = {}
    for fam, ns in fams.items():
        ps = {n: (res[n]['hold'] or {}).get('p') for n in ns}
        hm = M.holm(ps)
        for n in ns:
            res[n]['holm_p_family'] = hm.get(n)
        allp.update(ps)
    hall = M.holm(allp)
    for n, r in res.items():
        r['holm_p_all'] = hall.get(n)
        g, c = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['net_hold'], repl=r.get('repl'),
                       family_holm_p=r['holm_p_family'], leveraged_or_timing=False)
        r['grade'], r['criteria'] = g, c
        g2, _ = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['net_hold'], repl=r.get('repl'),
                        family_holm_p=r['holm_p_all'], leveraged_or_timing=False)
        r['grade_if_holm_all'] = g2
        log(f"{n:34s} grade {g} (Holm全体なら {g2}) {c}")
    return {f: ns for f, ns in fams.items()}


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
    res = collections.OrderedDict()
    run_family_us(families(), DUS, DR, jkpmkt, res)          # 第1次
    run_family_us(families2(), DUS, DR, jkpmkt, res)         # 第2次 Q1
    fr_src = run_q2(res)                                     # 第2次 Q2・Q2R
    q3 = run_q3(families()['P_primary'])                     # 第2次 Q3
    res.update(q3)
    posthoc = run_posthoc_regions(DR)                        # 事後
    fams = finalize(res, None)
    san['lowTO_n_chars'] = len(LOWTO)
    out = {'angle': 'fmom_wf', 'prereg': pre, 'global_prereg': 'out/mw_prereg.json', 'sanity': san,
           'benchmark': 'French Mkt-RF（超過どうし）。転がる20年窓・積立は総リターン（戦略超過＋French RF 対 French Mkt）。地域はその地域の市場（JKP mkt vw／French 地域 Mkt）。Q3 は国々の市場の等分',
           'n_tested': len(res), 'families': fams, 'french_sources': fr_src,
           'tested': list(res.values()), 'posthoc_not_graded': posthoc, 'log_tail': LOG[-200:]}
    p = M.save(OUT, out)
    log('saved', p, os.path.getsize(p))


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        ok = selftest()
        sys.exit(0 if ok else 1)
    main()
