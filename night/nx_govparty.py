#!/usr/bin/env python3
"""night/nx_govparty.py — nx 角度 govparty（政府への依存度の高い業種 × 大統領の党）の**測る道具**（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…探し続けて」。
ただし線を下げて勝ちを作らない。事前登録 out/nx_govparty_prereg.json（測る前に固定・この道具はそれを書き換えない）と
全体の線 out/nx_prereg.json（C1〜C8・格付け S/A/B/C）をそのまま当てる。統計と格付けは night/nx_common.py。

何を測るか（Belo-Gala-Li 2013 の買いだけ版）
  BEA の産業連関表から作った『業種の生産のうち政府が直接・間接に買う割合』（night/nx_govparty_data.py →
  out/_nx_cache/nx_govparty_io.json・最初に sha256 を事前登録の値と照合し、違えば止まる）で French 49 業種を三分位に分け、
    主の族（格付け・Holm は4本の中で）:
      G1 D → 高依存の三分位を VW／R → 低依存の三分位を VW
      G2 D → 高依存を VW／R → 市場
      G3 D → 市場／R → 低依存を VW
      G4 悪い側だけ避ける: D → 49業種から低依存を除いた残りを VW／R → 高依存を除いた残りを VW
    探索の族14本（E1〜E14・格付けはするが『探索』）、対照・並べ替え検定・1956年以前・市場の党別・1業種抜き・米国外5か国・ETF。
  信号は t 月末に分かる値（党の暦・公表済みの表・French の t 月の行の社数×平均時価）だけで t+1 月を持つ。信号にリターンは使わない。

使い方: python3 night/nx_govparty.py            → out/nx_govparty.json
"""
import sys, os, json, math, hashlib, itertools, time, datetime, statistics as S, zipfile, io as _io, csv
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402

PRE = os.path.join(N.BASE, 'out', 'nx_govparty_prereg.json')
IO = os.path.join(N.CACHE, 'nx_govparty_io.json')
DATA_TOOL = os.path.join(N.BASE, 'night', 'nx_govparty_data.py')
OUTNAME = 'nx_govparty.json'
COST, COST_SENS = 0.001, 0.003
PP_SSRN, PP_JFE = 201101, 201401
T_LAST = 202607                      # French の最後の月 2026-08 を持つ信号の月
EXCL_RANK = ['Util', 'Banks', 'Insur', 'RlEst', 'Fin', 'Other']
TECH, DEFN = ['Chips', 'Softw', 'Hardw'], ['Guns', 'Aero', 'Ships']
INTL = ['gbr', 'can', 'aus', 'deu', 'jpn']
GICS_NORANK = {'40', '55', '60'}
ETF = {'XLE': '10', 'XLB': '15', 'XLI': '20', 'XLY': '25', 'XLP': '30', 'XLV': '35', 'XLF': '40', 'XLK': '45', 'XLC': '50', 'XLU': '55', 'XLRE': '60'}
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:6.1f}s]', *a, flush=True)


def nxt(ym):
    y, m = divmod(ym, 100)
    return (y + 1) * 100 + 1 if m == 12 else ym + 1


def prv(ym):
    y, m = divmod(ym, 100)
    return (y - 1) * 100 + 12 if m == 1 else ym - 1


def mrange(a, z):
    out, x = [], a
    while x <= z:
        out.append(x); x = nxt(x)
    return out


def K3(n):
    return int(math.floor(n / 3 + 0.5))


def K5(n):
    return int(math.floor(n / 5 + 0.5))


def sha_obj(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def ymd(s):
    return int(s[:4]) * 100 + int(s[5:7])


# ───────────────────────── 読み込みと照合 ─────────────────────────
def load_io(pre):
    exp_tool = pre['tools']['data_tool_sha256'][:64]
    exp_t = pre['tools']['io_tables_sha256'][:64]
    exp_c = pre['tools']['calendar_sha256'][:64]
    got_tool = hashlib.sha256(open(DATA_TOOL, 'rb').read()).hexdigest()
    io = json.load(open(IO))
    got_t, got_c = sha_obj(io['tables']), sha_obj(io['calendar'])
    chk = {'data_tool_sha256': [got_tool, got_tool == exp_tool], 'io_tables_sha256': [got_t, got_t == exp_t],
           'calendar_sha256': [got_c, got_c == exp_c]}
    if not all(v[1] for v in chk.values()):
        raise SystemExit(f'事前登録の指紋と一致しない（依存度・暦を作り直した疑い）→ 止まる: {chk}')
    return io, chk


class Panel:
    pass


def french_panel():
    T = N.french_tables('49_Industry_Portfolios')
    vw, ew = T['Average Value Weighted Returns -- Monthly'], T['Average Equal Weighted Returns -- Monthly']
    nf, sz = T['Number of Firms in Portfolios'], T['Average Firm Size']
    cols = [c.strip() for c in vw['cols']]
    months = sorted(vw['data'])
    assert months == mrange(months[0], months[-1])

    def arr(tab, scale):
        A = np.full((len(months), len(cols)), np.nan)
        for i, mm in enumerate(months):
            for j, v in enumerate(tab['data'][mm]):
                if v is not None:
                    A[i, j] = v * scale
        return A
    P = Panel()
    P.months, P.names = months, cols
    P.idx = {m: i for i, m in enumerate(months)}
    P.nidx = {c: j for j, c in enumerate(cols)}
    P.n = len(cols)
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
        g = str(int(float(x['gics'])))
        out.setdefault(g, {})[N._ym(x['date'])] = float(x['ret'])
    return out


# ───────────────────────── 暦と表 ─────────────────────────
class World:
    def __init__(self, io, P, mkt, rf):
        self.io, self.P, self.mkt, self.rf = io, P, mkt, rf
        self.cal = io['calendar']['party_by_signal_month']
        self.sen = io['calendar']['party_by_signal_month']['senate_at_signal_month_end']
        self.pres = [(ymd(d), p) for _, p, d in io['calendar']['presidents']]
        self.sched_all = io['schedule']
        self.tables = io['tables']
        self.fr = io['industries']
        assert self.fr == P.names, 'French の業種の並びが io と違う'

    def party(self, cal, t):
        p = self.cal[cal][str(t)]
        if cal == 'main':   # 先読みの検査: 就任月 ≤ t−1 の最後の大統領の党
            assert p == [q for s, q in self.pres if s <= prv(t)][-1]
        elif cal == 'bgl':
            assert p == [q for s, q in self.pres if s <= t][-1]
        return p

    def sched(self, variant='all', first_table=None):
        s = [x for x in self.sched_all if self.tables[x['table']]['fr49'].get(variant) is not None]
        if first_table:
            s = [x for x in s if int(x['table']) >= int(first_table)]
        return s

    def table_at(self, t, sched):
        ok = [s for s in sched if s['signal'] <= t]
        if not ok:
            return None
        assert ok[-1]['signal'] <= t   # 先読みの検査
        return ok[-1]['table']

    def expo(self, t, variant, sched, fixed_table=None):
        tab = fixed_table or self.table_at(t, sched)
        if tab is None:
            return None, None
        return self.tables[tab]['fr49'][variant], tab

    def gics_expo(self, t, sched):
        tab = self.table_at(t, sched)
        return self.tables[tab]['gics11']['all'], tab


def avail(P, ti):
    return np.isfinite(P.R[ti]) & np.isfinite(P.CAP[ti]) & (np.nan_to_num(P.CAP[ti]) > 0)


def vw_w(P, ti, sel):
    w = np.zeros(P.n)
    c = P.CAP[ti, sel]
    assert np.all(np.isfinite(c)) and np.all(c > 0)
    w[sel] = c / c.sum()
    return w


def ew_w(n, sel):
    w = np.zeros(n)
    w[sel] = 1.0 / len(sel)
    return w


def rank_sets(W, t, variant='all', sched=None, excl=EXCL_RANK, kfun=K3, fixed_table=None):
    P = W.P
    ti = P.idx[t]
    e, tab = W.expo(t, variant, sched, fixed_table)
    if e is None:
        return None
    av = avail(P, ti)
    U = [j for j, nm in enumerate(P.names) if av[j] and nm not in excl and e.get(nm) is not None]
    K = kfun(len(U))
    assert K >= 1
    H = sorted(U, key=lambda j: (-e[P.names[j]], j))[:K]
    Lo = sorted(U, key=lambda j: (e[P.names[j]], j))[:K]
    assert len(H) == K and len(Lo) == K and not (set(H) & set(Lo)), 'H と L が重なる'
    return {'H': H, 'L': Lo, 'K': K, 'N': len(U), 'table': tab, 'av': av, 'ti': ti}


# ───────────────────────── 規則の実行 ─────────────────────────
def run(W, decide, t_list):
    """decide(t) → (kind, w, party, info)。kind='mkt' なら French Mkt を持つ（回転は49業種の VW で近似）。
    返り: dict（rets・tos・W（形成の重み）・kind・party・info・missing）"""
    P = W.P
    for a, b in zip(t_list, t_list[1:]):
        assert b == nxt(a)
    out = {'rets': {}, 'tos': {}, 'W': {}, 'kind': {}, 'party': {}, 'table': {}, 'missing_hold': 0}
    prev = None
    for t in t_list:
        ti = P.idx[t]
        h = P.months[ti + 1]
        kind, w, party, info = decide(t)
        if kind == 'mkt':
            av = avail(P, ti)
            w = vw_w(P, ti, np.flatnonzero(av))
        assert abs(w.sum() - 1) < 1e-9 and np.all(w >= -1e-15)
        rh = P.R[ti + 1]
        fin = np.isfinite(rh)
        if kind != 'mkt':
            out['missing_hold'] += int(((w > 0) & ~fin).sum())
        rh0 = np.where(fin, rh, 0.0)
        r_ind = float(w @ rh0)
        r = W.mkt[h] if kind == 'mkt' else r_ind
        to = 1.0 if prev is None else 0.5 * float(np.abs(w - prev).sum())
        assert -1e-12 <= to <= 1 + 1e-9
        g = w * (1 + rh0)
        prev = g / g.sum()
        out['rets'][h], out['tos'][h], out['W'][h] = r, to, w
        out['kind'][h], out['party'][h], out['table'][h] = kind, party, (info or {}).get('table')
    return out


def net_of(r, to, c):
    return {k: r[k] - to[k] * c for k in r}


# ───────────────────────── 規則の定義 ─────────────────────────
def make_rule(W, kind, cal='main', variant='all', sched=None, excl=EXCL_RANK, kfun=K3, weighting='vw',
              gate=None, fixed_table=None, reverse=False):
    """kind: 'G1' 切替 H/L・'G2' D→H/R→Mkt・'G3' D→Mkt/R→L・'G4' 悪い側を避ける・
    'H' 常に H・'L' 常に L・'avoidL' 常に L を避ける・'avoidH' 常に H を避ける。
    gate(t, h) が False の月は Mkt（E13・E14）。reverse=True で党を逆に（D→L・R→H）"""
    P = W.P
    sched = sched if sched is not None else W.sched(variant)

    def wts(ti, sel):
        return vw_w(P, ti, sel) if weighting == 'vw' else ew_w(P.n, sel)

    def decide(t):
        party = W.party(cal, t)
        h = nxt(t)
        rs = rank_sets(W, t, variant, sched, excl, kfun, fixed_table)
        info = {'table': rs['table'], 'K': rs['K'], 'N': rs['N']}
        if gate is not None and not gate(t, h, party):
            return 'mkt', None, party, info
        ti = rs['ti']
        allv = [j for j in range(P.n) if rs['av'][j]]
        k = kind
        p = party
        if reverse:
            p = 'R' if party == 'D' else 'D'
        if k == 'G1':
            sel = rs['H'] if p == 'D' else rs['L']
        elif k == 'G2':
            if p != 'D':
                return 'mkt', None, party, info
            sel = rs['H']
        elif k == 'G3':
            if p != 'R':
                return 'mkt', None, party, info
            sel = rs['L']
        elif k == 'G4':
            avoid = set(rs['L'] if p == 'D' else rs['H'])
            sel = [j for j in allv if j not in avoid]
        elif k == 'H':
            sel = rs['H']
        elif k == 'L':
            sel = rs['L']
        elif k == 'avoidL':
            sel = [j for j in allv if j not in set(rs['L'])]
        elif k == 'avoidH':
            sel = [j for j in allv if j not in set(rs['H'])]
        else:
            raise ValueError(k)
        if k in ('G1', 'G2', 'G3', 'H', 'L'):
            assert len(sel) == rs['K']
        w = wts(ti, sel)
        return 'ind', w, party, info
    return decide


# ───────────────────────── 評価 ─────────────────────────
def term_year(h):
    return ((h // 100 - 1953) % 4) + 1


def geo_ex(rs, bs):
    n = len(rs)
    if n == 0:
        return None
    gs = math.exp(math.fsum(math.log1p(x) for x in rs) * 12 / n) - 1
    gb = math.exp(math.fsum(math.log1p(x) for x in bs) * 12 / n) - 1
    cum = math.exp(math.fsum(math.log1p(x) for x in rs) - math.fsum(math.log1p(x) for x in bs)) - 1
    return {'cagr_rule': round(gs * 100, 2), 'cagr_mkt': round(gb * 100, 2), 'geo_ex_ann': round((gs - gb) * 100, 2), 'cum_rel': round(cum * 100, 2),
            '_raw_diff': gs - gb}


def party_blocks(party_by_hold):
    ks = sorted(party_by_hold)
    runs = []
    for h in ks:
        p = party_by_hold[h]
        if runs and runs[-1][0] == p and nxt(runs[-1][1][-1]) == h:
            runs[-1][1].append(h)
        else:
            runs.append((p, [h]))
    return runs


def c5_units(res, bench):
    runs = party_blocks(res['party'])
    tab, n_units, n_pos = [], 0, 0
    for p, ms in runs:
        cm = [h for h in ms if res['kind'][h] != 'mkt']
        g = geo_ex([res['rets'][h] for h in cm], [bench[h] for h in cm]) if cm else None
        ga = geo_ex([res['rets'][h] for h in ms], [bench[h] for h in ms])
        unit = len(cm) >= 24
        pos = bool(unit and g and g['_raw_diff'] > 0)
        if unit:
            n_units += 1; n_pos += int(pos)
        tab.append({'party': p, 'from': ms[0], 'to': ms[-1], 'months_all': len(ms), 'months_counted': len(cm),
                    'counted_geo_excess': g, 'all_months_geo_excess': ga, 'is_unit': unit, 'positive': pos if unit else None})
    return {'regions': n_units, 'positive': n_pos}, tab


def stats_block(W, gross, to, res, bench, rf, post_pub=(PP_SSRN, PP_JFE)):
    es = N.excess_stats
    net, net_s = net_of(gross, to, COST), net_of(gross, to, COST_SENS)
    ks = sorted(gross)
    st = {'full': es(gross, bench), 'train': es(gross, bench, z=N.TRAIN_END), 'hold': es(gross, bench, a=N.HOLD_START),
          'recent_2013_07': es(gross, bench, a=N.RECENT_START),
          'post_ssrn_2011_01': es(gross, bench, a=post_pub[0]), 'post_jfe_2014_01': es(gross, bench, a=post_pub[1]),
          '1956_1989': es(gross, bench, a=195601, z=198912), '1990_2006': es(gross, bench, a=199001, z=200612)}
    by_party = {}
    for p in ('D', 'R'):
        hs = [h for h in ks if res['party'][h] == p]
        by_party[p] = {'months': len(hs), 'excess': es({h: gross[h] for h in hs}, bench),
                       'geo': geo_ex([gross[h] for h in hs], [bench[h] for h in hs]) if hs else None,
                       'hold_period_excess': es({h: gross[h] for h in hs if h >= N.HOLD_START}, bench)}
    by_term = {}
    for y in (1, 2, 3, 4):
        hs = [h for h in ks if term_year(h) == y]
        by_term[str(y)] = {'months': len(hs), 'excess': es({h: gross[h] for h in hs}, bench),
                           'geo': geo_ex([gross[h] for h in hs], [bench[h] for h in hs]) if hs else None}
    tov = [to[k] for k in ks]
    cst = {'cost_per_oneway': COST, 'cost_sensitivity': COST_SENS,
           'oneway_turnover_per_year': round(float(np.mean(tov[1:])) * 12, 3) if len(tov) > 1 else None,
           'first_month_turnover_1_included_in_net': True,
           'net_main': {'full': es(net, bench), 'train': es(net, bench, z=N.TRAIN_END), 'hold': es(net, bench, a=N.HOLD_START)},
           'net_sensitivity': {'full': es(net_s, bench), 'train': es(net_s, bench, z=N.TRAIN_END), 'hold': es(net_s, bench, a=N.HOLD_START)}}
    bw = {k: bench[k] for k in ks if k in bench}
    tr_b = {k: bench[k] for k in ks if k <= N.TRAIN_END}
    ho_b = {k: bench[k] for k in ks if k >= N.HOLD_START}
    shp = {'train': [N.sharpe(net, rf, z=N.TRAIN_END), N.sharpe(tr_b, rf)],
           'hold': [N.sharpe(net, rf, a=N.HOLD_START), N.sharpe(ho_b, rf)],
           'train_gross': N.sharpe(gross, rf, z=N.TRAIN_END), 'hold_gross': N.sharpe(gross, rf, a=N.HOLD_START),
           'full': [N.sharpe(net, rf), N.sharpe(bw, rf)],
           'note': '[規則（費用 0.10% 後）, Mkt（同じ月）]。C8 は費用後のシャープ（事前登録 series_used_per_criterion.C8_sharpe）'}
    out = {'span': [ks[0], ks[-1]], 'months': len(ks), 'stats_gross': st, 'by_party': by_party, 'by_term_year': by_term, 'cost': cst,
           'roll20_net': N.rolling(net, bench), 'roll20_gross': N.rolling(gross, bench),
           'dca20_net_ratio': N.dca(net, bench, 20), 'dca20_gross_ratio': N.dca(gross, bench, 20),
           'maxdd': {'rule_gross': round(N.maxdd(gross) * 100, 1), 'rule_net': round(N.maxdd(net) * 100, 1), 'bench_same_span': round(N.maxdd(bw) * 100, 1)},
           'sharpe': shp}
    return out, net


def table_usage(res):
    u = {}
    for h in sorted(res['table']):
        tb = res['table'][h]
        if tb not in u:
            u[tb] = [h, h, 0]
        u[tb][1] = h; u[tb][2] += 1
    return {k: {'hold_from': v[0], 'hold_to': v[1], 'months': v[2]} for k, v in u.items()}


def composition(W, res):
    P = W.P
    out = {}
    for p in ('D', 'R'):
        hs = [h for h in sorted(res['W']) if res['party'][h] == p]
        if not hs:
            continue
        A = np.mean([res['W'][h] for h in hs], axis=0)
        mk = sum(1 for h in hs if res['kind'][h] == 'mkt')
        top = sorted(range(P.n), key=lambda j: -A[j])[:12]
        out[p] = {'months': len(hs), 'months_holding_mkt': mk,
                  'avg_weight_top12': {P.names[j]: round(float(A[j]), 4) for j in top if A[j] > 0},
                  'tech_Chips_Softw_Hardw': round(float(sum(A[P.nidx[x]] for x in TECH)), 4),
                  'defense_Guns_Aero_Ships': round(float(sum(A[P.nidx[x]] for x in DEFN)), 4),
                  'note': 'Mkt を持つ月は49業種の VW（回転の近似の重み）を入れた平均'}
        hh = [h for h in hs if h >= N.HOLD_START]
        if hh:
            A2 = np.mean([res['W'][h] for h in hh], axis=0)
            out[p]['hold_period'] = {'months': len(hh), 'tech': round(float(sum(A2[P.nidx[x]] for x in TECH)), 4),
                                     'defense': round(float(sum(A2[P.nidx[x]] for x in DEFN)), 4),
                                     'avg_weight_top8': {P.names[j]: round(float(A2[j]), 4) for j in sorted(range(P.n), key=lambda j: -A2[j])[:8] if A2[j] > 0}}
    return out


def contributions(W, res, a=None, z=None):
    P = W.P
    c = np.zeros(P.n)
    for h in sorted(res['W']):
        if (a and h < a) or (z and h > z) or res['kind'][h] == 'mkt':
            continue
        rh = np.nan_to_num(P.R[P.idx[h]], nan=0.0)
        c += res['W'][h] * (rh - W.mkt[h])
    return c


# ───────────────────────── 主 ─────────────────────────
def main():
    pre = json.load(open(PRE))
    io, fp = load_io(pre)
    log('指紋は事前登録と一致', {k: v[1] for k, v in fp.items()})
    P = french_panel()
    ff = N.ff_factors()
    mkt, rf, mktrf = ff['mkt'], ff['rf'], ff['mktrf']
    W = World(io, P, mkt, rf)
    res_out = {'angle': 'nx_govparty', 'generated': datetime.date.today().isoformat(),
               'prereg': 'out/nx_govparty_prereg.json', 'global_prereg': 'out/nx_prereg.json', 'script': 'night/nx_govparty.py',
               'fingerprints': fp}

    # ── 健全性の検査（規則の成績ではない）: 49業種の VW（社数×平均時価）と Mkt
    tl_all = mrange(192607, T_LAST)
    proxy = {}
    for t in tl_all:
        ti = P.idx[t]
        av = avail(P, ti)
        w = vw_w(P, ti, np.flatnonzero(av))
        proxy[P.months[ti + 1]] = float(w @ np.nan_to_num(P.R[ti + 1], nan=0.0))
    sanity = {'fr49_vw_vs_mkt_1926_08': N.excess_stats(proxy, mkt), 'fr49_vw_vs_mkt_1956_02': N.excess_stats(proxy, mkt, a=195602),
              'note': 'French 49業種の VW（t 月の社数×平均時価の重み・t+1 月のリターン）を Mkt と並べた（G4 と『市場を持つ』月の回転の近似の確かさ・規則の成績ではない）'}
    log('49業種 VW 対 Mkt', sanity['fr49_vw_vs_mkt_1956_02'])

    t_main = mrange(195601, T_LAST)
    t_1970 = mrange(197001, T_LAST)
    rules = {}

    def add(name, family, spec, decide, t_list, cal='main'):
        r = run(W, decide, t_list)
        rules[name] = {'family': family, 'spec': spec, 'res': r, 'cal': cal}
        log(f'{name}: {min(r["rets"])}〜{max(r["rets"])} ({len(r["rets"])}か月) missing_hold={r["missing_hold"]}')

    # 主の族
    add('G1_switch_hi_lo', 'primary', 'D → 高依存の三分位（all）を VW／R → 低依存の三分位を VW（主の暦・43業種の順位・K=floor(N/3+0.5)）', make_rule(W, 'G1'), t_main)
    add('G2_dem_hi_else_mkt', 'primary', 'D → 高依存の三分位を VW／R → Mkt', make_rule(W, 'G2'), t_main)
    add('G3_rep_lo_else_mkt', 'primary', 'D → Mkt／R → 低依存の三分位を VW', make_rule(W, 'G3'), t_main)
    add('G4_avoid_side', 'primary', 'D → 49業種（データのある全業種）から低依存の三分位を除いて VW／R → 高依存の三分位を除いて VW', make_rule(W, 'G4'), t_main)
    # 探索の族
    add('E1_G1_quintile', 'exploratory', 'G1 を五分位で（K=floor(N/5+0.5)）', make_rule(W, 'G1', kfun=K5), t_main)
    add('E2_G4_quintile', 'exploratory', 'G4 を五分位で（避けるのは上位・下位の K=floor(N/5+0.5)）', make_rule(W, 'G4', kfun=K5), t_main)
    add('E3_G1_direct', 'exploratory', 'G1 の依存度を direct_all（一段目だけ）に', make_rule(W, 'G1', variant='direct_all'), t_main)
    add('E4_G1_federal', 'exploratory', 'G1 の依存度を federal（連邦だけ）に', make_rule(W, 'G1', variant='federal'), t_main)
    add('E5_G1_defense', 'exploratory', 'G1 の依存度を defense（連邦国防だけ）に（1963年表から・持つのは 1970-02〜）', make_rule(W, 'G1', variant='defense'), t_1970)
    add('E6_G1_nondefense', 'exploratory', 'G1 の依存度を nondefense（連邦非国防＋州と地方）に（1970-02〜）', make_rule(W, 'G1', variant='nondefense'), t_1970)
    add('E7_G1_ex_defense_inds', 'exploratory', 'G1 の順位から Guns・Aero・Ships を除く', make_rule(W, 'G1', excl=EXCL_RANK + DEFN), t_main)
    add('E8_G1_bgl_timing', 'exploratory', 'G1 の党の暦を bgl（就任月＋1 から持つ）に', make_rule(W, 'G1', cal='bgl'), t_main, cal='bgl')
    add('E9_G1_election_timing', 'exploratory', 'G1 の党の暦を election（党が替わった選挙の結果の翌月末）に', make_rule(W, 'G1', cal='election'), t_main, cal='election')
    add('E10_G1_ew', 'exploratory', 'G1 の三分位の中を業種の等分で', make_rule(W, 'G1', weighting='ew'), t_main)
    add('E11_G1_all49', 'exploratory', 'G1 の順位に49業種すべてを入れる', make_rule(W, 'G1', excl=[]), t_main)
    add('E12_G1_detailed_only', 'exploratory', '1947・1958年表を使わず 1963年表から（1970-02〜）', make_rule(W, 'G1', sched=W.sched('all', first_table='1963')), t_1970)

    def gate_unified(t, h, party):
        return W.sen[str(t)] == party
    add('E13_G1_unified_senate', 'exploratory', 't 月末の上院の多数党が（main の）大統領の党と同じ月だけ G1、違う月は Mkt', make_rule(W, 'G1', gate=gate_unified), t_main)

    def gate_term23(t, h, party):
        return term_year(h) in (2, 3)
    add('E14_G1_term_years_2_3', 'exploratory', '持つ月の暦年が任期の2・3年目（(年−1953) mod 4 が 1 か 2）の月だけ G1、ほかは Mkt', make_rule(W, 'G1', gate=gate_term23), t_main)
    # 報告のみ（対照）
    add('CTRL_static_H', 'report_only', '常に高依存の三分位を VW（党を使わない）', make_rule(W, 'H'), t_main)
    add('CTRL_static_L', 'report_only', '常に低依存の三分位を VW', make_rule(W, 'L'), t_main)
    add('CTRL_static_avoidL', 'report_only', '常に低依存を避ける（49業種から L を除いて VW）', make_rule(W, 'avoidL'), t_main)
    add('CTRL_static_avoidH', 'report_only', '常に高依存を避ける（49業種から H を除いて VW）', make_rule(W, 'avoidH'), t_main)
    add('CTRL_reverse_G1', 'report_only', '党を逆に（D → L・R → H）', make_rule(W, 'G1', reverse=True), t_main)
    t_pre = mrange(192607, 195512)
    add('HIST_pre1956_G1', 'report_only', '1926-08〜1956-01 を 1947年表（公表前＝先読みあり）で G1（格付けしない）', make_rule(W, 'G1', fixed_table='1947'), t_pre)
    add('HIST_pre1956_G4', 'report_only', '1926-08〜1956-01 を 1947年表（公表前＝先読みあり）で G4（格付けしない）', make_rule(W, 'G4', fixed_table='1947'), t_pre)

    # ── 先読み・構造の検査
    for nm in ('G1_switch_hi_lo', 'G4_avoid_side'):
        r = rules[nm]['res']
        unit, tab = c5_units(r, mkt)
        got = [x['months_counted'] for x in tab if x['is_unit']]
        assert unit['regions'] == 10 and got == [61, 96, 96, 48, 144, 96, 96, 96, 48, 48], (nm, unit, got)
    for nm, need in (('G2_dem_hi_else_mkt', 5), ('G3_rep_lo_else_mkt', 5)):
        unit, _ = c5_units(rules[nm]['res'], mkt)
        assert unit['regions'] == need, (nm, unit)
    log('C5 の単位の数と月数は登録どおり')

    # ── 評価
    entries = {}
    for nm, rr in rules.items():
        r = rr['res']
        e, net = stats_block(W, r['rets'], r['tos'], r, mkt, rf)
        unit, blocks = c5_units(r, mkt)
        e.update({'name': nm, 'family': rr['family'], 'spec': rr['spec'], 'calendar': rr['cal'],
                  'C5_units': unit, 'party_blocks': blocks, 'table_usage': table_usage(r),
                  'missing_hold_count': r['missing_hold'],
                  'months_holding_mkt': sum(1 for h in r['kind'] if r['kind'][h] == 'mkt')})
        entries[nm] = e
        rr['net'] = net

    # ── Holm と格付け
    fam_p = {f: N.holm({n: e['stats_gross']['hold']['p'] for n, e in entries.items() if e['family'] == f}) for f in ('primary', 'exploratory')}
    for nm, e in entries.items():
        if e['family'] not in fam_p:
            e['grade'] = None
            e['criteria'] = None
            e['note_grade'] = '報告のみ（格付けしない）'
            continue
        st = e['stats_gross']
        sp = {'train': tuple(e['sharpe']['train']), 'hold': tuple(e['sharpe']['hold'])}
        hp = fam_p[e['family']].get(nm)
        g, c = N.grade(st['full'], st['train'], st['hold'], e['roll20_net'], e['cost']['net_main']['hold'], e['C5_units'], hp, sp, True)
        e['grade'], e['criteria'], e['holm_p_in_family'] = g, c, hp
        e['grading_inputs'] = {'C1_C2_C3_C7': 'stats_gross（費用前・対 French Mkt）', 'C4': 'roll20_net（費用 0.10% 後・転がる20年窓）',
                               'C5': 'C5_units（政権の塊・規則自身の暦・Mkt を持たない月≥24）', 'C6': 'cost.net_main.hold',
                               'C7': f'full t≥3.0 または Holm（{e["family"]} の族の中・保有期間の両側 p）<0.05', 'C8': 'sharpe.train / sharpe.hold（費用後の規則 対 Mkt）'}
        if e['family'] == 'exploratory':
            e['note_grade'] = '探索（格付けはするが探索と明記・主の勝ちには数えない）'
        log(f'{nm}: {g} {c}')

    # ── 構成（D の月・R の月の平均の重み）
    comp = {nm: composition(W, rules[nm]['res']) for nm in ('G1_switch_hi_lo', 'G2_dem_hi_else_mkt', 'G3_rep_lo_else_mkt', 'G4_avoid_side',
                                                          'E1_G1_quintile', 'E7_G1_ex_defense_inds', 'E11_G1_all49')}

    # ── 並べ替え検定（政権の塊の単位）
    perm = {}
    for base_nm, kinds in (('G1_switch_hi_lo', ('H', 'L')), ('G4_avoid_side', ('avoidL', 'avoidH'))):
        rD = rules[f'CTRL_static_{kinds[0]}']['res']['rets']   # D のときに持つもの
        rR = rules[f'CTRL_static_{kinds[1]}']['res']['rets']   # R のときに持つもの
        real = rules[base_nm]['res']
        for h in real['rets']:   # 本物と一致することの検査
            assert abs(real['rets'][h] - (rD[h] if real['party'][h] == 'D' else rR[h])) < 1e-12
        runs = party_blocks(real['party'])
        for span_nm, a in (('full', None), ('hold', N.HOLD_START)):
            rr_ = [(p, [h for h in ms if (a is None or h >= a)]) for p, ms in runs]
            rr_ = [(p, ms) for p, ms in rr_ if ms]
            nD = sum(1 for p, _ in rr_ if p == 'D')
            vals = []
            real_lab = tuple(i for i, (p, _) in enumerate(rr_) if p == 'D')
            real_v = None
            for combo in itertools.combinations(range(len(rr_)), nD):
                sD = set(combo)
                rs_, bs_ = [], []
                for i, (_, ms) in enumerate(rr_):
                    for h in ms:
                        rs_.append(rD[h] if i in sD else rR[h]); bs_.append(mkt[h])
                g = geo_ex(rs_, bs_)['_raw_diff'] * 100
                vals.append(g)
                if combo == real_lab:
                    real_v = g
            ge = sum(1 for v in vals if v >= real_v - 1e-12)
            perm[f'{base_nm}_{span_nm}'] = {'blocks': len(rr_), 'D_blocks': nD, 'n_labelings': len(vals), 'real_geo_ex_ann': round(real_v, 3),
                                            'rank_from_top': ge, 'p_one_sided': round(ge / len(vals), 4),
                                            'median_of_labelings': round(sorted(vals)[len(vals) // 2], 3), 'min': round(min(vals), 3), 'max': round(max(vals), 3),
                                            'note': '費用前・対 Mkt の幾何の年率差。本物の並びも数に入る（p = 本物以上の割合）'}
    log('並べ替え検定', {k: (v['real_geo_ex_ann'], v['p_one_sided']) for k, v in perm.items()})

    # ── 市場そのものの党別（規則ではない）
    mbp = {}
    for span_nm, a, z in (('1926_08_2026_08', 192608, 202608), ('1956_02_2026_08', 195602, 202608), ('hold_2007_01', 200701, 202608)):
        d = {'D': [], 'R': []}
        for h in mrange(a, z):
            if h in mktrf:
                d[W.party('main', prv(h))].append(mktrf[h])
        mD, mR = S.mean(d['D']), S.mean(d['R'])
        se = math.sqrt(S.variance(d['D']) / len(d['D']) + S.variance(d['R']) / len(d['R']))
        mbp[span_nm] = {'D_months': len(d['D']), 'R_months': len(d['R']), 'D_mktrf_ann': round(mD * 1200, 2), 'R_mktrf_ann': round(mR * 1200, 2),
                        'diff_ann': round((mD - mR) * 1200, 2), 'welch_t': round((mD - mR) / se, 2)}
    log('市場の党別', mbp)

    # ── 1業種抜き（保有期間の寄与が最大の1業種）
    drop = {}
    for nm in ('G1_switch_hi_lo', 'G4_avoid_side'):
        r = rules[nm]['res']
        c = contributions(W, r, a=N.HOLD_START)
        order = sorted(range(P.n), key=lambda j: -c[j])
        top = order[0]
        top_nm = P.names[top]
        # (a) 持ち物から外して残りで割り直す（顔ぶれの選び方は同じ）
        rets_a, tos_a = {}, {}
        prev = None
        for h in sorted(r['W']):
            ti = P.idx[h]
            w = r['W'][h].copy()
            w[top] = 0.0
            if w.sum() <= 0:
                w = r['W'][h].copy()
            w = w / w.sum()
            rh0 = np.nan_to_num(P.R[ti], nan=0.0)
            rets_a[h] = float(w @ rh0)
            tos_a[h] = 1.0 if prev is None else 0.5 * float(np.abs(w - prev).sum())
            g = w * (1 + rh0); prev = g / g.sum()
        # (b) 順位と持ち物の世界から外して作り直す
        kind = 'G1' if nm.startswith('G1') else 'G4'
        rb = run(W, make_rule(W, kind, excl=EXCL_RANK + [top_nm]) if kind == 'G1' else _g4_without(W, top_nm), t_main)
        drop[nm] = {'top_contributor_hold': top_nm, 'hold_contrib_arith_sum_pct': {P.names[j]: round(float(c[j]) * 100, 2) for j in order[:6]},
                    'hold_contrib_bottom3_pct': {P.names[j]: round(float(c[j]) * 100, 2) for j in order[-3:]},
                    'a_drop_from_holdings': {'hold': N.excess_stats(rets_a, mkt, a=N.HOLD_START), 'full': N.excess_stats(rets_a, mkt),
                                             'hold_net010': N.excess_stats(net_of(rets_a, tos_a, COST), mkt, a=N.HOLD_START)},
                    'b_drop_from_universe': {'hold': N.excess_stats(rb['rets'], mkt, a=N.HOLD_START), 'full': N.excess_stats(rb['rets'], mkt),
                                             'hold_net010': N.excess_stats(net_of(rb['rets'], rb['tos'], COST), mkt, a=N.HOLD_START)},
                    'note': '報告のみ。寄与 = Σ_保有期間 w_i×(r_i − Mkt)（算術）。(a) 持ち物から外して残りの重みで割り直す（選び方は同じ）／(b) 順位・持ち物の世界から外して作り直す'}
    log('1業種抜き', {k: (v['top_contributor_hold'], v['a_drop_from_holdings']['hold']) for k, v in drop.items()})

    # ── 米国外5か国（報告のみ）
    intl = intl_report(W, io)
    # ── ETF（報告のみ）
    etf = etf_report(W, io)

    res_out.update({'sanity': sanity, 'holm': fam_p, 'permutation': perm, 'market_by_party': mbp, 'drop_top1': drop,
                    'composition': comp, 'R_intl': intl, 'R_etf_us': etf})
    res_out['post_hoc'] = post_hoc(W, rules, entries)
    res_out['deviations_from_prereg'] = DEVIATIONS + [intl_zero_deviation(intl, etf)]
    res_out['fixes'] = fixes_entries(intl, etf)
    res_out['headline'] = headline(entries, perm, drop)
    res_out['summary_ja'] = summary_ja(entries, res_out)
    tested = []
    for nm, e in entries.items():
        tested.append(e)
    res_out['tested'] = tested
    res_out['tested_count'] = {'primary': sum(1 for e in tested if e['family'] == 'primary'),
                               'exploratory': sum(1 for e in tested if e['family'] == 'exploratory'),
                               'report_only_rules': sum(1 for e in tested if e['family'] == 'report_only'),
                               'report_only_other': 'permutation 462×2＋10×2・market_by_party・drop_top1 2本×2型・R_intl 5か国×2型・R_etf_us 2型×2'}
    res_out['grade_summary'] = {e['name']: e['grade'] for e in tested if e['grade']}
    p = N.save(OUTNAME, res_out)
    log('書いた', p)
    return res_out


# ───────────────────────── 事後（結果を見た後の追加・格付けに使わない） ─────────────────────────
def nw_ols(y, X, lag=12):
    y = np.asarray(y); X = np.column_stack([np.ones(len(y)), np.asarray(X)])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        Gm = Xe[L:].T @ Xe[:-L]
        Sm += w * (Gm + Gm.T)
    V = XtXi @ Sm @ XtXi
    return b, np.sqrt(np.diag(V))


def ff_monthly(name, cols):
    for t, v in N.french_tables(name).items():
        if v['freq'] == 'monthly':
            ix = [v['cols'].index(c) for c in cols]
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for c, i in zip(cols, ix)}
    raise KeyError(name)


def post_hoc(W, rules, entries):
    """事後（結果を見た後）。格付けには使わない。勝ちの中身の診断"""
    P, mkt, rf = W.P, W.mkt, W.rf
    es = N.excess_stats
    out = {'_label': '★事後（結果を見た後に足した診断）。格付け・合否には一切使っていない'}
    # (1) 党で切り替えることの上乗せ = G1 − ½(常に H + 常に L)、G4 − ½(常に L を避ける + 常に H を避ける)
    zero = {h: 0.0 for h in mkt}
    sw = {}
    for nm, a, b in (('G1_switch_hi_lo', 'CTRL_static_H', 'CTRL_static_L'), ('G4_avoid_side', 'CTRL_static_avoidL', 'CTRL_static_avoidH')):
        g, ra, rb = rules[nm]['res']['rets'], rules[a]['res']['rets'], rules[b]['res']['rets']
        x = {h: g[h] - 0.5 * (ra[h] + rb[h]) for h in g}
        sw[nm] = {k: es(x, zero, a=aa, z=zz) for k, (aa, zz) in {'full': (None, None), 'train': (None, N.TRAIN_END), 'hold': (N.HOLD_START, None),
                                                               'post_ssrn_2011_01': (PP_SSRN, None)}.items()}
        stat = {h: 0.5 * (ra[h] + rb[h]) for h in g}
        sw[nm]['static_half_half_vs_mkt'] = {k: es(stat, mkt, a=aa, z=zz) for k, (aa, zz) in {'full': (None, None), 'train': (None, N.TRAIN_END), 'hold': (N.HOLD_START, None)}.items()}
    sw['_note'] = '規則 − 党を使わない静的な半々（常に H と常に L の毎月の半々）。これが党で切り替えることの上乗せ（静的な傾きを除いた分）。ex_ann は差の算術×12、t は NW'
    out['switch_premium'] = sw
    # (2) 因子で説明できるか（FF5＋勢い）: (規則 − Mkt) を Mkt−RF・SMB・HML・RMW・CMA・Mom に回帰（1963-07〜）
    f5 = ff_monthly('F-F_Research_Data_5_Factors_2x3', ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA'])
    mom = ff_monthly('F-F_Momentum_Factor', ['Mom'])['Mom']
    fac = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA']
    reg = {}
    for nm in ('G1_switch_hi_lo', 'G4_avoid_side', 'E1_G1_quintile', 'E3_G1_direct', 'E8_G1_bgl_timing', 'E9_G1_election_timing', 'CTRL_static_H', 'CTRL_static_L'):
        g = rules[nm]['res']['rets']
        reg[nm] = {}
        for span, a, z in (('1963_07_all', 196307, None), ('train_1963_07_2006_12', 196307, N.TRAIN_END), ('hold', N.HOLD_START, None)):
            ks = [h for h in sorted(g) if h >= a and (z is None or h <= z) and all(h in f5[c] for c in fac) and h in mom]
            y = [g[h] - mkt[h] for h in ks]
            X = [[f5[c][h] for c in fac] + [mom[h]] for h in ks]
            b, se = nw_ols(y, X)
            reg[nm][span] = {'months': len(ks), 'alpha_ann_pct': round(b[0] * 1200, 2), 'alpha_t': round(b[0] / se[0], 2),
                             'loadings': {c: [round(float(b[i + 1]), 3), round(float(b[i + 1] / se[i + 1]), 2)] for i, c in enumerate(fac + ['Mom'])}}
    reg['_note'] = '(規則 − Mkt) の月次を FF5（Mkt−RF・SMB・HML・RMW・CMA）＋ Mom に回帰（NW ラグ12）。alpha は年率%、loadings は [係数, t]'
    out['factor_regression'] = reg
    # (3) 党ごとの CAPM（規則 − RF を Mkt − RF に）
    capm = {}
    for nm in ('G1_switch_hi_lo', 'E9_G1_election_timing'):
        r = rules[nm]['res']
        capm[nm] = {}
        for p in ('D', 'R'):
            for span, a, z in (('train', None, N.TRAIN_END), ('hold', N.HOLD_START, None)):
                ks = [h for h in sorted(r['rets']) if r['party'][h] == p and (a is None or h >= a) and (z is None or h <= z)]
                if len(ks) < 24:
                    continue
                y = [r['rets'][h] - rf[h] for h in ks]
                X = [[mkt[h] - rf[h]] for h in ks]
                b, se = nw_ols(y, X)
                capm[nm][f'{p}_{span}'] = {'months': len(ks), 'alpha_ann_pct': round(b[0] * 1200, 2), 'alpha_t': round(b[0] / se[0], 2),
                                           'beta': round(float(b[1]), 3), 'mkt_excess_ann_pct': round(S.mean(X[i][0] for i in range(len(ks))) * 1200, 2)}
    capm['_note'] = '党の月ごとに (規則 − RF) を (Mkt − RF) に回帰。R の月は市場の超過が小さい（大統領の謎）ので、β<1 の持ち物は β だけでも差が出る'
    out['capm_by_party'] = capm
    # (4) 保有期間の暦年ごとの超過（幾何）と、保有期間の寄与の上位
    yr = {}
    for nm in ('G1_switch_hi_lo', 'E3_G1_direct', 'E8_G1_bgl_timing', 'E9_G1_election_timing', 'G4_avoid_side'):
        r = rules[nm]['res']
        yr[nm] = {}
        for y in range(2007, 2027):
            ks = [h for h in r['rets'] if h // 100 == y]
            if ks:
                g = geo_ex([r['rets'][h] for h in ks], [mkt[h] for h in ks])
                yr[nm][str(y)] = {'party_months': ''.join(sorted(set(r['party'][h] for h in ks))), 'rel_pct': g['cum_rel']}
        c = contributions(W, r, a=N.HOLD_START)
        order = sorted(range(P.n), key=lambda j: -c[j])
        yr[nm]['_hold_contrib_top3_pct'] = {P.names[j]: round(float(c[j]) * 100, 2) for j in order[:3]}
        yr[nm]['_hold_contrib_bottom3_pct'] = {P.names[j]: round(float(c[j]) * 100, 2) for j in order[-3:]}
    yr['_note'] = 'rel_pct = その暦年の (1+規則)/(1+Mkt) − 1（%）。寄与 = Σ w×(r − Mkt)（算術・%）'
    out['hold_by_year'] = yr
    # (5) A になった探索（E3・E8・E9）と主の G1 から Chips を外した版（持ち物から外して残りで割り直す）
    dc = {}
    j0 = P.nidx['Chips']
    for nm in ('G1_switch_hi_lo', 'E1_G1_quintile', 'E3_G1_direct', 'E8_G1_bgl_timing', 'E9_G1_election_timing'):
        r = rules[nm]['res']
        rr = {}
        for h in sorted(r['W']):
            w = r['W'][h].copy()
            w[j0] = 0.0
            w = w / w.sum()
            rr[h] = float(w @ np.nan_to_num(P.R[P.idx[h]], nan=0.0))
        dc[nm] = {'full': es(rr, mkt), 'train': es(rr, mkt, z=N.TRAIN_END), 'hold': es(rr, mkt, a=N.HOLD_START),
                  'chips_avg_weight_D_months': round(float(np.mean([r['W'][h][j0] for h in r['W'] if r['party'][h] == 'D'])), 4)}
    dc['_note'] = 'Chips（French の定義は探知・航法・誘導システムと通信機器を含む）を持ち物から外し、残りの重みで割り直した（選び方は同じ）。費用前・対 Mkt'
    out['drop_chips'] = dc
    # (6) 多重性の目安: 主4＋探索14 の18本のうち全期間 t≥3.0 を通ったのは何本か（同じ考えの変形どうしで強く相関）
    fam = [e for e in entries.values() if e['family'] in ('primary', 'exploratory')]
    out['multiplicity'] = {'graded_rules': len(fam), 'full_t_ge_3': [e['name'] for e in fam if (e['stats_gross']['full']['t'] or 0) >= 3.0],
                           'hold_t_ge_1.65': [e['name'] for e in fam if (e['stats_gross']['hold']['t'] or 0) >= 1.65],
                           'note': '探索の14本は G1 の変形（暦・依存度の定義・分位）で互いに強く相関する。全期間 t≥3.0 は Harvey-Liu-Zhu の線だが、同じ族の中で最良の変形を拾うことの割り引きはしていない'}
    return out


def headline(entries, perm, drop):
    g = {e['name']: e for e in entries.values()}
    prim = {n: g[n]['grade'] for n in ('G1_switch_hi_lo', 'G2_dem_hi_else_mkt', 'G3_rep_lo_else_mkt', 'G4_avoid_side')}
    expl = {n: e['grade'] for n, e in g.items() if e['family'] == 'exploratory'}
    return {'primary_grades': prim, 'exploratory_grades': expl,
            'primary_S_or_A': [n for n, v in prim.items() if v in ('S', 'A')],
            'exploratory_S_or_A': [n for n, v in expl.items() if v in ('S', 'A')],
            'permutation_p_one_sided': {k: v['p_one_sided'] for k, v in perm.items()},
            'drop_top1_hold_cagr_diff': {k: [v['top_contributor_hold'], v['a_drop_from_holdings']['hold']['cagr_diff']] for k, v in drop.items()}}


def summary_ja(entries, R):
    g = {e['name']: e for e in entries.values()}
    f = lambda x: 'なし' if x is None else f"{x['cagr_diff']:+.2f}%/年（t {x['t']}）"
    L = []
    for n in ('G1_switch_hi_lo', 'G2_dem_hi_else_mkt', 'G3_rep_lo_else_mkt', 'G4_avoid_side'):
        e = g[n]; st = e['stats_gross']
        L.append(f"{n} {e['grade']}: 訓練 {f(st['train'])}・保有 {f(st['hold'])}・全期間 {f(st['full'])}・費用後の保有 {f(e['cost']['net_main']['hold'])}・"
                 f"20年窓 {e['roll20_net']['win_rate']}・政権の塊 {e['C5_units']['positive']}/{e['C5_units']['regions']}")
    ex = [n for n, e in g.items() if e['family'] == 'exploratory' and e['grade'] in ('S', 'A')]
    for n in ex:
        e = g[n]; st = e['stats_gross']
        L.append(f"探索 {n} {e['grade']}: 全期間 t {st['full']['t']}（C7 は全期間 t≥3.0 で通過）・訓練 {f(st['train'])}・保有 {f(st['hold'])}（C3 不合格）")
    ph = R['post_hoc']
    sp = ph['switch_premium']['G1_switch_hi_lo']
    L.append(f"事後: G1 の『党で切り替える上乗せ』（静的な半々を引いた分）は訓練 {f(sp['train'])}・保有 {f(sp['hold'])}・SSRN 後 {f(sp['post_ssrn_2011_01'])}")
    L.append(f"事後: 保有期間の勝ちは Chips（高依存の三分位に入る）が担い、Chips を外すと G1 の保有は {f(ph['drop_chips']['G1_switch_hi_lo']['hold'])}・E9 {f(ph['drop_chips']['E9_G1_election_timing']['hold'])}・E3 {f(ph['drop_chips']['E3_G1_direct']['hold'])}")
    fr = ph['factor_regression']['G1_switch_hi_lo']
    L.append(f"事後: G1 の FF5＋勢いのアルファ 訓練 {fr['train_1963_07_2006_12']['alpha_ann_pct']}%（t {fr['train_1963_07_2006_12']['alpha_t']}）・保有 {fr['hold']['alpha_ann_pct']}%（t {fr['hold']['alpha_t']}）")
    pm = R['permutation']
    L.append(f"並べ替え検定（政権の塊に D を付ける全462通り）: G1 p={pm['G1_switch_hi_lo_full']['p_one_sided']}・G4 p={pm['G4_avoid_side_full']['p_one_sided']}／保有期間10通り G1 p={pm['G1_switch_hi_lo_hold']['p_one_sided']}")
    ic = R['R_intl']['_count_geo_positive']
    icd = R['R_intl']['_count_geo_positive_missing_dropped']
    zf = R['R_intl']['_zero_filled_months']
    tmax = max(abs(R['R_intl'][c][typ]['excess_vs_country_mkt_excess_to_excess']['t']) for c in INTL for typ in ('G1_type', 'G4_type'))
    zf_txt = '・'.join(f"{c} {zf[c]['G4_type']}" for c in INTL if zf[c]['G4_type']) or 'なし'
    L.append(f"米国外5か国（報告のみ）: G1 型 {ic['G1_type']['positive']}/{ic['G1_type']['units']}・G4 型 {ic['G4_type']['positive']}/{ic['G4_type']['units']} で幾何の超過が正（|t| の最大 {tmax}）。"
             f"持っているセクターのリターンが欠けた月を 0 とした回数 G1 型 {sum(zf[c]['G1_type'] for c in INTL)}・G4 型 {sum(zf[c]['G4_type'] for c in INTL)}（{zf_txt}）、"
             f"欠けを外して残りで割り直しても G1 型 {icd['G1_type']['positive']}/{icd['G1_type']['units']}・G4 型 {icd['G4_type']['positive']}/{icd['G4_type']['units']}")
    return L


# 検査役の指摘で直したもの（前の値は直す前の実行 out/nx_govparty.json 2026-09-28 20:29 から写した）
FIX_BEFORE_R_INTL = {
    'cagr_diff': {'gbr': [0.5, 0.66], 'can': [2.95, 1.91], 'aus': [0.42, 0.44], 'deu': [0.48, 0.91], 'jpn': [0.08, 0.29]},
    'ex_ann_G4': {'can': 1.34, 'deu': 0.68},
    'geo_positive': {'G1_type': '5/5', 'G4_type': '5/5'},
    'zero_filled_months_reported': '記録なし（deviations_from_prereg に R_intl の 0 埋めは書かれていなかった）',
}


def intl_zero_deviation(intl, etf):
    zf = intl['_zero_filled_months']
    icd = intl['_count_geo_positive_missing_dropped']
    parts = []
    for c in INTL:
        for typ in ('G1_type', 'G4_type'):
            e = intl[c][typ]
            if e['zero_filled_months']['count']:
                a = e['excess_vs_country_mkt_excess_to_excess']; b = e['alt_missing_dropped_reweighted']['excess_vs_country_mkt_excess_to_excess']
                secs = sorted({s for v in e['zero_filled_months']['months'].values() for s in v})
                parts.append(f"{c} {typ[:2]} 型 {e['zero_filled_months']['count']}回（セクター{'・'.join(secs)}）: 幾何の差 {a['cagr_diff']:+.2f}→{b['cagr_diff']:+.2f}・算術 {a['ex_ann']:+.2f}→{b['ex_ann']:+.2f}")
    etf_z = sum(v['zero_filled_months']['count'] for k, v in etf.items() if not k.startswith('_'))
    return ('R_intl（報告のみ）で、持っているセクターの t+1 月のリターンが JKP の国別 GICS ファイルで欠けた月を 0 とした'
            '（families.common.missing_hold『持っている業種の t+1 月が欠けたら 0』を R_intl にも当てた読み。JKP の超過なので 0 ＝その分を現金〔RF〕で持ったのと同じ）。'
            '検査役の指摘までこの 0 埋めを記録していなかった。0 で埋めた月の数（国ごと）: '
            + '／'.join(f"{c} G1 {zf[c]['G1_type']}・G4 {zf[c]['G4_type']}" for c in INTL) + '。'
            + ('；'.join(parts) + '。' if parts else '')
            + f"欠けを外して残りを等分し直した版（各国の alt_missing_dropped_reweighted）でも幾何の超過が正の国は G1 型 {icd['G1_type']['positive']}/{icd['G1_type']['units']}・"
              f"G4 型 {icd['G4_type']['positive']}/{icd['G4_type']['units']}。R_etf_us（同じ eq_run）で 0 で埋めた月は {etf_z} 回。報告のみなので格付けへの影響なし")


def fixes_entries(intl, etf):
    after_cd = {c: [intl[c][typ]['alt_missing_dropped_reweighted']['excess_vs_country_mkt_excess_to_excess']['cagr_diff'] for typ in ('G1_type', 'G4_type')] for c in INTL}
    head_cd = {c: [intl[c][typ]['excess_vs_country_mkt_excess_to_excess']['cagr_diff'] for typ in ('G1_type', 'G4_type')] for c in INTL}
    icd = intl['_count_geo_positive_missing_dropped']
    return [{
        'id': 'F1',
        'reported': '報告のみの米国外（R_intl）で、持っているセクターの翌月のリターンが欠けた月を 0% として数えている（欠測を0と読む）。deviations_from_prereg には HIST_pre1956_G4 の1回しか書かれておらず、R_intl の分は記録されていない',
        'verdict': ('記録漏れは誤り（確かめた）。eq_run は h 月にリターンの無い持ち物を 0 で数えており、自分で数え直すと 0 で埋めた月は CAN G4 型 1回・DEU G4 型 4回（どれもセクター50）・G1 型 0回で、検査役の数と一致した。'
                    'それが deviations_from_prereg に書かれていなかった。0 埋めそのものは事前登録 families.common.missing_hold（report_only も families の下）を当てた読みで、'
                    'HIST_pre1956_G4 と同じ扱い＝規則は変えない。ただし CLAUDE.md ルール7（欠測を0と読むな）に照らして、欠けを外して割り直した版を併記した'),
        'fix': ('eq_run に missing（zero＝登録の読み・既定／drop＝h 月に欠けたセクターを外して残りを等分）と 0 で埋めた月の一覧（gaps）を足した。'
                'R_intl の各国・各型に zero_filled_months と alt_missing_dropped_reweighted、全体に _zero_filled_months と _count_geo_positive_missing_dropped を出した。'
                'R_etf_us の4本にも zero_filled_months を出した。deviations_from_prereg に R_intl の 0 埋めの行を足し、summary_ja の米国外の行に回数と割り直し版の正の数を足した（|t| の最大も計算値に）'),
        'before': FIX_BEFORE_R_INTL,
        'after': {'headline_cagr_diff_G1_G4_unchanged_by_design': head_cd,
                  'alt_missing_dropped_reweighted_cagr_diff_G1_G4': after_cd,
                  'alt_ex_ann_G4': {c: intl[c]['G4_type']['alt_missing_dropped_reweighted']['excess_vs_country_mkt_excess_to_excess']['ex_ann'] for c in ('can', 'deu')},
                  'geo_positive_missing_dropped': {k: f"{v['positive']}/{v['units']}" for k, v in icd.items()},
                  'zero_filled_months': intl['_zero_filled_months'],
                  'grades_changed': 'なし（報告のみ）'},
    }]


DEVIATIONS = [
    'C8 は事前登録（series_used_per_criterion.C8_sharpe）どおり費用後（0.10%）の規則のシャープ 対 同じ月の Mkt のシャープで判定した（兄弟の角度 nx_leadlag は費用前を使っているが、ここは登録の文面に従った）。格付けへの影響なし（登録どおり）',
    'DROP_TOP1 の「寄与」は登録に式が無いので、保有期間の Σ_月 w_i×(r_i − Mkt)（算術）と定義し、(a) 持ち物から外して残りの重みで割り直す版（選び方は同じ）と (b) 順位と持ち物の世界から外して作り直す版の2つを出した。報告のみ・格付けへの影響なし',
    '「各月の信号に使う表の年と党の暦を記録」は、各規則の table_usage（表 → 持った月の範囲）と party_blocks（党の塊）に要約して残した（月ごとの一覧はファイルが大きくなるので出さない）。先読みの検査（表の signal ≤ t・main は就任月 ≤ t−1・bgl は就任月 ≤ t）は全ての月で assert した',
    '年あたりの片道回転（cost.oneway_turnover_per_year）は最初の月（回転1）を除いた平均×12 で表示した。費用後の系列（net）には登録どおり最初の月の回転1も引いてある',
    'R_intl（報告のみ）: 登録どおり JKP の超過どうしで国の市場（vw）と比べた。幾何の差は超過どうしだと総リターンの差と少しずれるので、両方に米国 RF（French）を足した版も併記した。登録に費用の指定が無いので 0.10% 後も併記。首班の党は登録の暦（就任月 ≤ t−1 の最後の首班）',
    'R_etf_us（報告のみ）: XLRE・XLC は信号の月 t にリターンがある月から入れた（XLC は 2018-07 にリターンが出る → 2018-08 から持つ＝登録どおり。XLRE は 2015-11 → 2015-12 から G4 型の持ち物へ）。JKP 米国 GICS 版の転がる20年窓・積立は超過のリターンのまま計算した（報告のみ）',
    'HIST_pre1956_G4（報告のみ）で、持っている業種の t+1 月が欠けた月が1回あり、登録どおり 0 とした',
    '市場の党別（MKT_BY_PARTY・報告のみ）は main の暦（持つ月の党＝前月末の信号の党）で Mkt−RF を分け、Welch の t を付けた（登録に検定の指定なし）',
    'composition（報告のみ）の平均の重みは、Mkt を持つ月には49業種の VW（回転の近似に使う重み）を入れて平均した',
    'Holm の p は兄弟の角度と同じく excess_stats が返す保有期間の両側 p（小数4桁に丸めた値）から計算した',
]


def _g4_without(W, drop_nm):
    """G4 を、順位にも持ち物にもその業種を入れずに作り直す（1業種抜き (b)）"""
    P = W.P
    sched = W.sched('all')
    j0 = P.nidx[drop_nm]

    def decide(t):
        party = W.party('main', t)
        rs = rank_sets(W, t, 'all', sched, EXCL_RANK + [drop_nm], K3)
        allv = [j for j in range(P.n) if rs['av'][j] and j != j0]
        avoid = set(rs['L'] if party == 'D' else rs['H'])
        sel = [j for j in allv if j not in avoid]
        return 'ind', vw_w(P, rs['ti'], sel), party, {'table': rs['table']}
    return decide


# ───────────────────────── 米国外（報告のみ） ─────────────────────────
def eq_run(t_list, pick, R, sectors, missing='zero'):
    """R: {sec: {ym: r}}。pick(t) → (sel セクターの一覧, party)。等分。回転は等分の重みの流し。
    missing='zero': 持っているセクターの h 月のリターンが欠けたら 0（事前登録 families.common.missing_hold を当てた読み。
                    JKP の超過なので 0 ＝その分を現金〔RF〕で持ったのと同じ）。
    missing='drop': h 月にリターンの無いセクターを持ち物から外し、残りを等分し直す（欠測を 0 と読まない版・報告のみ・検査役の指摘で追加）。
    返り: rets, tos, par, gaps（{h: h 月に欠けていた持ち物のセクター}＝'zero' なら 0 で埋めた月）"""
    rets, tos, par, gaps = {}, {}, {}, {}
    prev = None
    for t in t_list:
        h = nxt(t)
        sel, party = pick(t)
        if sel is None:
            continue
        rh = {s: R[s].get(h) for s in sectors}
        miss = [s for s in sel if rh[s] is None]
        if miss:
            gaps[h] = miss
        held = [s for s in sel if rh[s] is not None] if missing == 'drop' else list(sel)
        if not held:
            continue
        w = {s: 1.0 / len(held) for s in held}
        r = sum(w[s] * (rh[s] if rh[s] is not None else 0.0) for s in held)
        wv = np.array([w.get(s, 0.0) for s in sectors])
        to = 1.0 if prev is None else 0.5 * float(np.abs(wv - prev).sum())
        g = wv * (1 + np.array([rh[s] if rh[s] is not None else 0.0 for s in sectors]))
        prev = g / g.sum()
        rets[h], tos[h], par[h] = r, to, party
    return rets, tos, par, gaps


def intl_report(W, io):
    heads = io['calendar']['intl_heads_report_only']
    sched = W.sched('all')
    out = {}
    count = {'G1_type': {'units': 0, 'positive': 0}, 'G4_type': {'units': 0, 'positive': 0}}
    count_drop = {'G1_type': {'units': 0, 'positive': 0}, 'G4_type': {'units': 0, 'positive': 0}}
    zero_months = {c: {} for c in INTL}
    for c in INTL:
        R = jkp_gics(c)
        mk = N.jkp_mkt(c, 'vw')
        sectors = sorted(R)
        hs = [(ymd(d), p) for d, p, _ in heads[c]]

        def party_at(t):
            ok = [p for s, p in hs if s <= prv(t)]
            return ok[-1] if ok else None
        ms = sorted(set().union(*[set(v) for v in R.values()]))
        t_list = [t for t in mrange(ms[0], 202511)]
        res_c = {}
        for typ in ('G1_type', 'G4_type'):
            def pick(t, typ=typ):
                party = party_at(t)
                if party is None:
                    return None, None
                e, tab = W.gics_expo(t, sched)
                avs = [s for s in sectors if R[s].get(t) is not None]
                U = [s for s in avs if s not in GICS_NORANK and e.get(s) is not None]
                K = K3(len(U))
                H = sorted(U, key=lambda s: (-e[s], s))[:K]
                Lo = sorted(U, key=lambda s: (e[s], s))[:K]
                assert not set(H) & set(Lo)
                if typ == 'G1_type':
                    return (H if party == 'L' else Lo), party
                avoid = set(Lo if party == 'L' else H)
                return [s for s in avs if s not in avoid], party
            rets, tos, par, gaps = eq_run(t_list, pick, R, sectors)
            rf_ = W.rf
            tot = {h: v + rf_[h] for h, v in rets.items() if h in rf_}
            mk_tot = {h: v + rf_[h] for h, v in mk.items() if h in rf_}
            ex = N.excess_stats(rets, mk)
            ex_tot = N.excess_stats(tot, mk_tot)
            net = N.excess_stats(net_of(rets, tos, COST), mk)
            by_p = {p: N.excess_stats({h: v for h, v in rets.items() if par[h] == p}, mk) for p in ('L', 'R')}
            pos = bool(ex and ex['cagr_diff'] > 0)
            count[typ]['units'] += 1; count[typ]['positive'] += int(pos)
            # 欠測を 0 と読まない版（h 月にリターンの無いセクターを外して残りを等分し直す・報告のみ）
            rets_d, tos_d, par_d, gaps_d = eq_run(t_list, pick, R, sectors, missing='drop')
            assert gaps_d == gaps
            ex_d = N.excess_stats(rets_d, mk)
            tot_d = {h: v + rf_[h] for h, v in rets_d.items() if h in rf_}
            pos_d = bool(ex_d and ex_d['cagr_diff'] > 0)
            count_drop[typ]['units'] += 1; count_drop[typ]['positive'] += int(pos_d)
            zero_months[c][typ] = {'count': len(gaps), 'months': {str(h): v for h, v in sorted(gaps.items())}}
            res_c[typ] = {'excess_vs_country_mkt_excess_to_excess': ex, 'excess_total_return_basis_plus_us_rf': ex_tot,
                          'net010': net, 'by_head_side': by_p, 'geo_positive': pos,
                          'turnover_per_year': round(float(np.mean(list(tos.values())[1:])) * 12, 3),
                          'zero_filled_months': zero_months[c][typ],
                          'alt_missing_dropped_reweighted': {
                              'excess_vs_country_mkt_excess_to_excess': ex_d,
                              'excess_total_return_basis_plus_us_rf': N.excess_stats(tot_d, mk_tot),
                              'net010': N.excess_stats(net_of(rets_d, tos_d, COST), mk),
                              'geo_positive': pos_d,
                              'turnover_per_year': round(float(np.mean(list(tos_d.values())[1:])) * 12, 3),
                              'note': 'h 月にリターンの無いセクターを持ち物から外し、残りを等分し直した版（欠測を 0 と読まない・報告のみ）。'
                                      '欠けた月が0回なら上の値と同じ'}}
        out[c] = res_c
        log(f'intl {c}', {k: ((v['excess_vs_country_mkt_excess_to_excess'] or {}).get('cagr_diff'),
                              (v['alt_missing_dropped_reweighted']['excess_vs_country_mkt_excess_to_excess'] or {}).get('cagr_diff'),
                              v['zero_filled_months']['count']) for k, v in res_c.items()})
    out['_count_geo_positive'] = count
    out['_count_geo_positive_missing_dropped'] = count_drop
    out['_zero_filled_months'] = {c: {typ: v['count'] for typ, v in d.items()} for c, d in zero_months.items()}
    out['_note'] = ('報告のみ。首班が左（英労働・加自由・豪労働・独 SPD・日 民主党）→ 米国のその月の表の GICS 依存度の上位 K（40・55・60 を除く8セクターで順位・'
                    'K=floor(N/3+0.5)）を等分／右 → 下位 K を等分。G4 型は避ける K を除いた残り全セクターを等分。首班の就任月＋2 から持つ。'
                    'JKP の超過どうしで国の市場（vw）と比べた（excess_to_excess）。幾何の差は超過どうしだと総リターンの差と少しずれるので、両方に米国 RF を足した版も併記。'
                    '持っているセクターの h 月のリターンが JKP で欠けた月は 0（families.common.missing_hold を当てた読み・超過なので現金で持ったのと同じ）で、'
                    'その月の数は zero_filled_months／_zero_filled_months。欠けを外して残りを等分し直した版を alt_missing_dropped_reweighted に併記')
    return out


def etf_report(W, io):
    sched = W.sched('all')
    out = {}
    R = {}
    for tk, g in ETF.items():
        d = N.yahoo(tk)
        R[g] = {k: v for k, v in d.items() if k <= 202608}
    spy = {k: v for k, v in N.yahoo('SPY').items() if k <= 202608}
    sectors = sorted(R)
    rank_ok = {'10', '15', '20', '25', '30', '35', '45', '50'}

    def mk_pick(Rs, typ):
        secs = sorted(Rs)

        def pick(t):
            party = W.party('main', t)
            e, tab = W.gics_expo(t, sched)
            avs = [s for s in secs if Rs[s].get(t) is not None]
            U = [s for s in avs if s in rank_ok and e.get(s) is not None]
            K = K3(len(U))
            H = sorted(U, key=lambda s: (-e[s], s))[:K]
            Lo = sorted(U, key=lambda s: (e[s], s))[:K]
            assert not set(H) & set(Lo)
            if typ == 'G1_type':
                return (H if party == 'D' else Lo), party
            avoid = set(Lo if party == 'D' else H)
            return [s for s in avs if s not in avoid], party
        return pick

    for src, Rs, bench, t_list in (('select_sector_spdr_vs_SPY', R, spy, mrange(199901, 202607)),):
        for typ in ('G1_type', 'G4_type'):
            rets, tos, par, gaps = eq_run(t_list, mk_pick(Rs, typ), Rs, sorted(Rs))
            out[f'{src}_{typ}'] = etf_stats(rets, tos, par, bench, W.rf)
            out[f'{src}_{typ}']['zero_filled_months'] = {'count': len(gaps), 'months': {str(h): v for h, v in sorted(gaps.items())}}
    ju = jkp_gics('usa')
    jm = N.jkp_mkt('usa', 'vw')
    t_list = mrange(min(set().union(*[set(v) for v in ju.values()])), 202511)
    for typ in ('G1_type', 'G4_type'):
        rets, tos, par, gaps = eq_run(t_list, mk_pick(ju, typ), ju, sorted(ju))
        out[f'jkp_us_gics_vs_jkp_us_mkt_{typ}'] = etf_stats(rets, tos, par, jm, W.rf, excess_basis=True)
        out[f'jkp_us_gics_vs_jkp_us_mkt_{typ}']['zero_filled_months'] = {'count': len(gaps), 'months': {str(h): v for h, v in sorted(gaps.items())}}
    out['_note'] = ('報告のみ。Select Sector SPDR（配当込み・Yahoo）で D → GICS 依存度の上位 K（XLB・XLE・XLI・XLK・XLP・XLV・XLY、XLC はリターンの出た月から順位へ。'
                    'XLF・XLU・XLRE は順位に入れない・K=floor(N/3+0.5)）を等分／R → 下位 K を等分。G4 型は避ける K を除いた残り（XLRE・XLC は出てから）を等分。相手 SPY。'
                    '同じ2本を JKP 米国 GICS（超過・対 JKP 米国市場 vw）でも')
    log('ETF', {k: (v.get('excess') or {}).get('cagr_diff') for k, v in out.items() if not k.startswith('_')})
    return out


def etf_stats(rets, tos, par, bench, rf, excess_basis=False):
    es = N.excess_stats
    net = net_of(rets, tos, COST)
    o = {'span': [min(rets), max(rets)], 'excess': es(rets, bench), 'train_part_to_2006': es(rets, bench, z=N.TRAIN_END),
         'hold_2007': es(rets, bench, a=N.HOLD_START), 'net010': es(net, bench), 'net010_hold': es(net, bench, a=N.HOLD_START),
         'net030': es(net_of(rets, tos, COST_SENS), bench),
         'by_party': {p: es({h: v for h, v in rets.items() if par[h] == p}, bench) for p in ('D', 'R')},
         'turnover_per_year': round(float(np.mean(list(tos.values())[1:])) * 12, 3),
         'maxdd': {'rule': round(N.maxdd(rets) * 100, 1), 'bench_same_span': round(N.maxdd({k: bench[k] for k in rets if k in bench}) * 100, 1)},
         'roll20_net': N.rolling(net, bench), 'dca20_net_ratio': N.dca(net, bench, 20)}
    if excess_basis:
        tot = {h: v + rf[h] for h, v in rets.items() if h in rf}
        btot = {h: v + rf[h] for h, v in bench.items() if h in rf}
        o['excess_total_return_basis_plus_us_rf'] = es(tot, btot)
        o['sharpe'] = {'rule_net': N.sharpe({h: v + rf[h] for h, v in net.items() if h in rf}, rf), 'bench': N.sharpe({k: btot[k] for k in rets if k in btot}, rf)}
    else:
        o['sharpe'] = {'rule_net': N.sharpe(net, rf), 'bench': N.sharpe({k: bench[k] for k in rets if k in bench}, rf)}
    return o


if __name__ == '__main__':
    main()
