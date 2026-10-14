#!/usr/bin/env python3
"""night/longrun1990.py — 1990年〜今の長い検証（longrun1990）の測定（読むだけ・採点に不使用）

2026-10-14 ユーザー「短い期間の検証だから足りないのでは？ 1990〜今までの検証結果がいるよね？」。
事前登録 out/longrun1990_prereg.json（4dc44296・測る前）のとおりに測る。系列・向き・線・期間はそこから動かさない。

  A 群のリターン（上場廃止を含む CRSP がもとの Ken French・JKP）: 1990-01〜2025-12 と前半・後半で、
    名指しした群 S が同じ出所の『全部』B より平均で上か下か（主の族 L 11本・探索の族 E 6本・時価加重で判定、
    等ウェイトと大型は同じ規則で別に出す）
  B 株単位（今も上場している会社だけ・Yahoo 月足）: 1990〜2013年の1月に始まる13年の窓24本で、
    年15%以上の複利株の下げの深さ（B1〜B4）。取得は night/longrun1990_fetch.py（先に回す）
出力: out/longrun1990.json
使い方: python3 night/longrun1990.py           … A と B（B の取得が無ければ B は飛ばして理由を書く）
        python3 night/longrun1990.py --only-a   … A だけ
"""
import datetime
import gzip
import hashlib
import json
import math
import os
import statistics as S
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as C  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREREG = os.path.join(BASE, 'out', 'longrun1990_prereg.json')
OUT = os.path.join(BASE, 'out', 'longrun1990.json')
YDIR = os.path.join(BASE, 'out', '_mw_cache', 'lr1990_yh')
START, END = 199001, 202512
PERIODS = {'P0': (199001, 202512), 'H1': (199001, 200612), 'H2': (200701, 202512), 'E13': (201307, 202512)}
WIN = 156                      # 13年
WIN_FIRST, WIN_LAST = 199001, 201301

# ───────────── 系列の台帳（事前登録の tests と同じ）─────────────
# French: (ファイル, S の列, 分け切る群の列)。JKP: (特性, 'high'|'low')
EP4 = ['<= 0', 'Lo 30', 'Med 40', 'Hi 30']
DEC_ME = ['Lo 10', '2-Dec', '3-Dec', '4-Dec', '5-Dec', '6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']
DEC_PR = ['Lo PRIOR', 'PRIOR 2', 'PRIOR 3', 'PRIOR 4', 'PRIOR 5', 'PRIOR 6', 'PRIOR 7', 'PRIOR 8', 'PRIOR 9', 'Hi PRIOR']
TESTS = {
    'L-a1': dict(fam='L', src='JKP', key='ebit_bev', side='high', predict='none',
                 big=('6_Portfolios_ME_OP_2x3', 'BIG HiOP', ['BIG LoOP', 'ME2 OP2', 'BIG HiOP'])),
    'L-a2': dict(fam='L', src='JKP', key='ebit_sale', side='high', predict='none', big=None),
    'L-a3': dict(fam='L', src='JKP', key='qmj', side='high', predict='none', big=None),
    'L-a4': dict(fam='L', src='JKP', key='sale_gr3', side='high', predict='none', big=None),
    'L-a5': dict(fam='L', src='French', file='Portfolios_Formed_on_E-P', col='Lo 30', part=EP4, predict='not_higher',
                 big=('6_Portfolios_ME_EP_2x3', 'BIG LoEP', ['BIG LoEP', 'ME2 EP2', 'BIG HiEP'])),
    'L-a6': dict(fam='L', src='French', file='Portfolios_Formed_on_E-P', col='Hi 30', part=EP4, predict='none',
                 big=('6_Portfolios_ME_EP_2x3', 'BIG HiEP', ['BIG LoEP', 'ME2 EP2', 'BIG HiEP'])),
    'L-c1': dict(fam='L', src='French', file='Portfolios_Formed_on_E-P', col='<= 0', part=EP4, predict='lower', big=None),
    'L-c2': dict(fam='L', src='French', file='Portfolios_Formed_on_ME', col='Lo 10', part=DEC_ME, predict='lower', big=None),
    'L-c3': dict(fam='L', src='JKP', key='o_score', side='high', predict='lower', big=None),
    'L-c4': dict(fam='L', src='JKP', key='ebit_bev', side='low', predict='lower',
                 big=('6_Portfolios_ME_OP_2x3', 'BIG LoOP', ['BIG LoOP', 'ME2 OP2', 'BIG HiOP'])),
    'L-c5': dict(fam='L', src='JKP', key='qmj', side='low', predict='lower', big=None),
    'E1': dict(fam='E', src='French', file='10_Portfolios_Prior_12_2', col='Hi PRIOR', part=DEC_PR, predict='higher',
               big=('6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', ['BIG LoPRIOR', 'ME2 PRIOR2', 'BIG HiPRIOR'])),
    'E2': dict(fam='E', src='French', file='10_Portfolios_Prior_60_13', col='Lo PRIOR', part=DEC_PR, predict='lower',
               big=('6_Portfolios_ME_Prior_60_13', 'BIG LoPRIOR', ['BIG LoPRIOR', 'ME2 PRIOR2', 'BIG HiPRIOR'])),
    'E3': dict(fam='E', src='French', file='10_Portfolios_Prior_60_13', col='Hi PRIOR', part=DEC_PR, predict='none',
               big=('6_Portfolios_ME_Prior_60_13', 'BIG HiPRIOR', ['BIG LoPRIOR', 'ME2 PRIOR2', 'BIG HiPRIOR'])),
    'E4': dict(fam='E', src='JKP', key='prc_highprc_252d', side='low', predict='none', big=None),
    'E5': dict(fam='E', src='JKP', key='eqnpo_me', side='high', predict='higher', big=None),
    'E6': dict(fam='E', src='French', file='Portfolios_Formed_on_D-P', col='<= 0', part=EP4, predict='not_higher', big=None),
}


# ───────────── 小道具 ─────────────
def ym_next(m):
    y, mo = divmod(m, 100)
    return y * 100 + mo + 1 if mo < 12 else (y + 1) * 100 + 1


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m)
        m = ym_next(m)
    return out


def sha_file(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else None


def pick(tables, kind):
    """French の表を名前の言葉で1つだけ選ぶ（月次）。kind: vw|ew|n|s"""
    hits = []
    for t, v in tables.items():
        if v['freq'] != 'monthly':
            continue
        tl = t.lower()
        ok = {'vw': 'value weight' in tl and 'return' in tl,
              'ew': 'equal weight' in tl and 'return' in tl,
              'n': 'number of firms' in tl,
              's': 'average firm size' in tl or 'average market cap' in tl}[kind]
        if ok:
            hits.append(t)
    if len(hits) != 1:
        raise RuntimeError(f'表の選択が一つに決まらない: {kind} → {hits}')
    v = tables[hits[0]]
    return hits[0], v


def french_parts(name):
    """{'vw': {列: {ym: r}}, 'ew': …, 'n': {列: {ym: 数}}, 's': {列: {ym: 平均の時価}}}（r は小数）"""
    tb = C.french_tables(name)
    out = {}
    for kind in ('vw', 'ew', 'n', 's'):
        title, v = pick(tb, kind)
        d = {c: {} for c in v['cols']}
        for m, row in v['data'].items():
            for c, x in zip(v['cols'], row):
                if x is not None:
                    d[c][m] = x / 100 if kind in ('vw', 'ew') else x
        out[kind] = d
        out[kind + '_title'] = title
    return out


def french_universe(fp, part, w):
    """分け切る群を、等ウェイトなら銘柄数・時価加重なら銘柄数×平均の時価で重み付けた『全部』"""
    r = fp[w]
    out, dropped = {}, 0
    ms = set.union(*[set(r[c]) for c in part])
    for m in sorted(ms):
        num = den = 0.0
        ok = True
        for c in part:
            if m not in r[c] or m not in fp['n'][c]:
                ok = False
                break
            wt = fp['n'][c][m] if w == 'ew' else fp['n'][c][m] * fp['s'][c].get(m, float('nan'))
            if not (wt == wt) or wt < 0:
                ok = False
                break
            num += wt * r[c][m]
            den += wt
        if ok and den > 0:
            out[m] = num / den
        else:
            dropped += 1
    return out, dropped


def jkp_terciles(key, w):
    """{'1.0': {ym: r}, '2.0': …, '3.0': …}（超過）と {'1.0': {ym: n}, …}"""
    r, n = {}, {}
    for x in C.jkp_rows('usa', key, 'portfolios', w):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        m = C._ym(x['date'])
        r.setdefault(x['pf'], {})[m] = float(x['ret'])
        try:
            n.setdefault(x['pf'], {})[m] = float(x['n'])
        except (TypeError, ValueError):
            pass
    return r, n


_ALLF = None


def jkp_allfactors():
    global _ALLF
    if _ALLF is None:
        f, dirn = {}, {}
        for x in C.jkp_rows('usa', 'all_factors', 'factor', 'vw_cap'):
            dirn[x['name']] = int(float(x['direction']))
            if x['ret'] not in ('', 'NA', 'na'):
                f.setdefault(x['name'], {})[C._ym(x['date'])] = float(x['ret'])
        _ALLF = (f, dirn)
    return _ALLF


def jkp_side(key, r):
    f, dirn = jkp_allfactors()
    ms = sorted(set(r['3.0']) & set(r['1.0']) & set(f[key]))
    c = C.corr([r['3.0'][m] - r['1.0'][m] for m in ms], [f[key][m] for m in ms])
    high = '3.0' if c * dirn[key] > 0 else '1.0'
    return high, ('1.0' if high == '3.0' else '3.0'), round(c, 4), dirn[key]


def nw(d):
    t = C.nw_t(d, 12)
    return t, C.p_two(t)


def mdd_of(rs):
    v = peak = 1.0
    worst = 0.0
    for r in rs:
        v *= 1 + r
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def stats(rS, rB, a, z, rf=None):
    """期間 [a, z] の d の要約。rf を渡すと（JKP の超過→総リターン）裾の計算に足す"""
    ms = [m for m in months(a, z) if m in rS and m in rB]
    exp = len(months(a, z))
    if len(ms) < 24:
        return {'months': len(ms), 'expected_months': exp, 'note': '月数不足'}
    d = [rS[m] - rB[m] for m in ms]
    t, p = nw(d)
    g = math.fsum(math.log1p(rS[m]) - math.log1p(rB[m]) for m in ms)
    return {'months': len(ms), 'expected_months': exp, 'mean_ann_pct': round(12 * S.mean(d) * 100, 3),
            't': round(t, 3) if t is not None else None, 'p': p,
            'geo_ann_pct': round((math.exp(g * 12 / len(ms)) - 1) * 100, 3)}


def tails(rS, rB, rf=None):
    """P0 の裾（総リターン）と 13年の窓の勝ち・最悪"""
    tot = (lambda r, m: r[m] + rf[m]) if rf is not None else (lambda r, m: r[m])
    ms = [m for m in months(START, END) if m in rS and m in rB and (rf is None or m in rf)]
    msset = set(ms)
    out = {'mdd_S_pct': round(mdd_of([tot(rS, m) for m in ms]) * 100, 1),
           'mdd_B_pct': round(mdd_of([tot(rB, m) for m in ms]) * 100, 1)}
    wins = tot_w = 0
    worst_S = worst_B = None
    for st in months(WIN_FIRST, WIN_LAST):
        m = st
        w = [m]
        for _ in range(WIN - 1):
            m = ym_next(m)
            w.append(m)
        if not all(x in msset for x in w):
            continue
        gS = math.fsum(math.log1p(tot(rS, x)) for x in w)
        gB = math.fsum(math.log1p(tot(rB, x)) for x in w)
        tot_w += 1
        wins += gS > gB
        aS, aB = math.exp(gS / 13) - 1, math.exp(gB / 13) - 1
        worst_S = aS if worst_S is None else min(worst_S, aS)
        worst_B = aB if worst_B is None else min(worst_B, aB)
    out.update({'win13_windows': tot_w, 'win13_share': round(wins / tot_w, 3) if tot_w else None,
                'worst13_S_pct': round(worst_S * 100, 2) if worst_S is not None else None,
                'worst13_B_pct': round(worst_B * 100, 2) if worst_B is not None else None})
    return out


def verdict(predict, st, holm_p):
    """事前登録 verdict_rules_A"""
    P0, H1, H2 = st['P0'], st['H1'], st['H2']
    t0, t1, t2 = P0.get('t'), H1.get('t'), H2.get('t')
    m0, m1, m2 = P0.get('mean_ann_pct'), H1.get('mean_ann_pct'), H2.get('mean_ann_pct')
    if None in (t0, t1, t2, m0, m1, m2, holm_p):
        return '測れない'
    if predict in ('lower', 'higher'):
        s = -1 if predict == 'lower' else 1
        if m0 * s > 0:
            if holm_p < 0.05 and m1 * s > 0 and m2 * s > 0:
                return '成り立つ'
            return '向きは合う（弱い）'
        return '逆' if holm_p < 0.05 else '成り立たない'
    if predict == 'none':
        if abs(t0) < 2:
            return '差が見えない' if abs(t1) < 2 and abs(t2) < 2 else '時代で変わる'
        sgn = '上回る' if m0 > 0 else '下回る'
        return f'差がある（{sgn}）' if holm_p < 0.05 else f'差があるかもしれない（弱い・{sgn}）'
    if predict == 'not_higher':
        if t0 < 2:
            return '上回らない' if t1 < 2 and t2 < 2 else '時代で変わる'
        return '上回った' if holm_p < 0.05 else '上回ったかもしれない（弱い）'
    raise ValueError(predict)


def link(v):
    if v in ('成り立つ', '差が見えない', '上回らない'):
        return '1990年からも同じ'
    if v == '向きは合う（弱い）':
        return '向きは同じだが弱い'
    if v == '時代で変わる':
        return '時代しだい'
    if v == '測れない':
        return '測れない'
    return '1990年からでは違う'


# ───────────── A ─────────────
def part_a():
    ff = C.ff_factors()
    rf, mkt = ff['rf'], ff['mkt']
    fcache = {}

    def fparts(name):
        if name not in fcache:
            fcache[name] = french_parts(name)
        return fcache[name]

    # 守り G1・G2
    me = fparts('Portfolios_Formed_on_ME')
    uni_me, _ = french_universe(me, DEC_ME, 'vw')
    ms = [m for m in months(START, END) if m in uni_me and m in mkt]
    g1 = {'corr': round(C.corr([uni_me[m] for m in ms], [mkt[m] for m in ms]), 5),
          'mean_diff_pct_per_month': round(S.mean(uni_me[m] - mkt[m] for m in ms) * 100, 4), 'months': len(ms)}
    g1['ok'] = g1['corr'] >= 0.995 and abs(g1['mean_diff_pct_per_month']) <= 0.05
    jm = {C._ym(x['date']): float(x['ret']) for x in C.jkp_rows('usa', 'mkt', 'factor', 'vw') if x['ret'] not in ('', 'NA', 'na')}
    ms = [m for m in months(START, END) if m in jm and m in mkt and m in rf]
    g2 = {'corr': round(C.corr([jm[m] + rf[m] for m in ms], [mkt[m] for m in ms]), 5),
          'mean_diff_pct_per_month': round(S.mean(jm[m] + rf[m] - mkt[m] for m in ms) * 100, 4), 'months': len(ms)}
    g2['ok'] = g2['corr'] >= 0.99 and abs(g2['mean_diff_pct_per_month']) <= 0.10

    res = {}
    for tid, T in TESTS.items():
        row = {'family': T['fam'], 'predict': T['predict'], 'series': {}}
        for w in ('vw', 'ew'):
            if T['src'] == 'JKP':
                r, n = jkp_terciles(T['key'], w)
                hi, lo, c, dr = jkp_side(T['key'], r)
                side = hi if T['side'] == 'high' else lo
                rS = r[side]
                if w == 'vw':
                    rB = jm
                    nb_drop = 0
                else:
                    rB, nb_drop = {}, 0
                    for m in sorted(set(r['1.0']) & set(r['2.0']) & set(r['3.0'])):
                        ws = [n.get(k, {}).get(m) for k in ('1.0', '2.0', '3.0')]
                        if None in ws or sum(ws) <= 0:
                            nb_drop += 1
                            continue
                        rB[m] = sum(wk * r[k][m] for wk, k in zip(ws, ('1.0', '2.0', '3.0'))) / sum(ws)
                row['series'][w] = {'source': f'JKP {T["key"]} 第{side[0]}分位（{w}）', 'side_rule': {'high': hi, 'corr': c, 'direction': dr},
                                    'benchmark': 'JKP mkt（vw）' if w == 'vw' else 'JKP 三分位の銘柄数で重み付けた平均（ew）',
                                    'benchmark_dropped_months': nb_drop}
                rfx = rf
            else:
                fp = fparts(T['file'])
                rS = fp[w][T['col']]
                rB, nb_drop = french_universe(fp, T['part'], w)
                row['series'][w] = {'source': f'French {T["file"]} の {T["col"]}（{w}）', 'table': fp[w + '_title'],
                                    'benchmark': f'分け切る群 {T["part"]} の{"銘柄数×平均の時価" if w == "vw" else "銘柄数"}で重み付けた平均',
                                    'benchmark_dropped_months': nb_drop}
                rfx = None
            stt = {k: stats(rS, rB, a, z) for k, (a, z) in PERIODS.items()}
            if T['src'] == 'French':
                last = max(m for m in rS if m in rB)
                stt['latest_French'] = dict(stats(rS, rB, START, last), end=last)
            stt['tail'] = tails(rS, rB, rfx)
            row['series'][w]['stats'] = stt
        if T['big']:
            fp = fparts(T['big'][0])
            out = {}
            for w in ('vw', 'ew'):
                rS = fp[w][T['big'][1]]
                rB, nb_drop = french_universe(fp, T['big'][2], w)
                stt = {k: stats(rS, rB, a, z) for k, (a, z) in PERIODS.items()}
                stt['tail'] = tails(rS, rB, None)
                out[w] = {'source': f'French {T["big"][0]} の {T["big"][1]}（{w}）', 'table': fp[w + '_title'],
                          'benchmark': f'大型の3群 {T["big"][2]}', 'benchmark_dropped_months': nb_drop, 'stats': stt}
            row['big'] = out
        res[tid] = row

    # Holm（族ごと・重み付けごと）→ 判定
    for fam in ('L', 'E'):
        for w in ('vw', 'ew'):
            ps = {tid: res[tid]['series'][w]['stats']['P0'].get('p') for tid in res if res[tid]['family'] == fam}
            hp = C.holm(ps)
            for tid in ps:
                s = res[tid]['series'][w]
                s['holm_p'] = hp.get(tid)
                s['verdict'] = verdict(res[tid]['predict'], s['stats'], hp.get(tid))
                s['link_to_2013'] = link(s['verdict'])
        for w in ('vw', 'ew'):
            ps = {tid: res[tid]['big'][w]['stats']['P0'].get('p') for tid in res if res[tid]['family'] == fam and 'big' in res[tid]}
            hp = C.holm(ps) if ps else {}
            for tid in ps:
                b = res[tid]['big'][w]
                b['holm_p_within_big'] = hp.get(tid)
                b['verdict'] = verdict(res[tid]['predict'], b['stats'], hp.get(tid))
                b['link_to_2013'] = link(b['verdict'])
    for tid in res:
        res[tid]['verdict'] = res[tid]['series']['vw']['verdict']
        res[tid]['link_to_2013'] = res[tid]['series']['vw']['link_to_2013']
    hashes = {fn: sha_file(os.path.join(C.CACHE, fn)) for fn in sorted(os.listdir(C.CACHE))
              if (fn.startswith('fr_') or fn.startswith('jkp_')) and fn.endswith('.zip')}
    return {'guards': {'G1': g1, 'G2': g2}, 'tests': res, 'raw_sha256': hashes}


# ───────────── B ─────────────
def load_yahoo(t):
    p = os.path.join(YDIR, t.replace('^', 'IDX_').replace('/', '_') + '.json.gz')
    if not os.path.exists(p):
        return None, 'no_file'
    try:
        j = json.loads(gzip.open(p).read())
        res = j['chart']['result'][0]
    except Exception:  # noqa
        return None, 'bad_json'
    meta = res.get('meta', {})
    ts = res.get('timestamp') or []
    try:
        adj = res['indicators']['adjclose'][0]['adjclose']
    except Exception:  # noqa
        return None, 'no_adjclose'
    out, dup = {}, 0
    for t0, a in zip(ts, adj):
        if a is None:
            continue
        dt = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc) - datetime.timedelta(hours=0)
        # 月足の時刻は月初（ニューヨークの0時＝UTC 4〜5時）。UTC の日付が前月末に落ちる場合に備え、12時間足して月を決める
        dt = dt + datetime.timedelta(hours=12)
        m = dt.year * 100 + dt.month
        if m in out:
            dup += 1
        out[m] = float(a)
    return {'meta': meta, 'adj': out, 'dup': dup}, 'ok'


def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return rk
    return C.corr(rank(x), rank(y))


def window_months(y):
    st = (y - 1) * 100 + 12
    w = [st]
    for _ in range(WIN):
        w.append(ym_next(w[-1]))
    return w                                   # 157 本（前月末＋156か月）


def part_b():
    st_p = os.path.join(YDIR, '_status.json')
    if not os.path.exists(st_p):
        return {'skipped': '取得が無い（night/longrun1990_fetch.py を先に回す）'}
    status = json.load(open(st_p))
    uni = json.load(open(os.path.join(BASE, 'out', 'longrun1990_universe.json')))
    ticks = [r[1] for r in uni['rows']]
    cnt = {}
    for t in ticks:
        s = status.get(t, 'not_tried').split(':')[0]
        cnt[s] = cnt.get(s, 0) + 1
    bench, bs = load_yahoo('^SP500TR')
    if bench is None:
        return {'skipped': f'^SP500TR が読めない（{bs}）', 'fetch_status': cnt}
    series, load_issue, not_equity, dups = {}, {}, 0, 0
    for t in ticks:
        if status.get(t) != 'ok':
            continue
        d, s = load_yahoo(t)
        if d is None:
            load_issue[s] = load_issue.get(s, 0) + 1
            continue
        if d['meta'].get('instrumentType') != 'EQUITY':
            not_equity += 1
            continue
        dups += d['dup']
        series[t] = d['adj']
    # G3
    ff = C.ff_factors()
    mkt = ff['mkt']
    br = {}
    ba = bench['adj']
    for m in months(START, END):
        pm = (m // 100 - 1) * 100 + 12 if m % 100 == 1 else m - 1
        if m in ba and pm in ba and ba[pm] > 0:
            br[m] = ba[m] / ba[pm] - 1
    ms = [m for m in months(START, END) if m in br and m in mkt]
    g3 = {'corr': round(C.corr([br[m] for m in ms], [mkt[m] for m in ms]), 5), 'months': len(ms)}
    g3['ok'] = g3['corr'] >= 0.98

    wins = []
    for y in range(1990, 2014):
        wm = window_months(y)
        if not all(m in ba and ba[m] > 0 for m in wm):
            wins.append({'start': y, 'note': '^SP500TR の月が欠けている'})
            continue
        bvals = [ba[m] for m in wm]
        b_cagr = (bvals[-1] / bvals[0]) ** (1 / 13) - 1
        b_mdd = mdd_of([bvals[i] / bvals[i - 1] - 1 for i in range(1, len(bvals))])
        rows, spike = [], 0
        for t, a in series.items():
            if not all(m in a and a[m] > 0 for m in wm):
                continue
            v = [a[m] for m in wm]
            rr = [v[i] / v[i - 1] - 1 for i in range(1, len(v))]
            if any((rr[i] <= -0.5 and rr[i + 1] >= 1.0) or (rr[i] >= 1.0 and rr[i + 1] <= -0.5) for i in range(len(rr) - 1)):
                spike += 1
                continue
            rows.append((t, (v[-1] / v[0]) ** (1 / 13) - 1, mdd_of(rr)))
        comp = [r for r in rows if r[1] >= 0.15]
        rest = [r for r in rows if r[1] < 0.15]
        w = {'start': y, 'end': (y + 12) * 100 + 12, 'n': len(rows), 'spike_excluded': spike,
             'n_comp': len(comp), 'share_comp': round(len(comp) / len(rows), 4) if rows else None,
             'n_destroy': sum(1 for r in rows if r[1] <= -0.15),
             'spx_cagr_pct': round(b_cagr * 100, 2), 'spx_mdd_pct': round(b_mdd * 100, 1)}
        if len(comp) >= 30:
            b1 = sum(1 for r in comp if r[2] < b_mdd) / len(comp)
            b2 = sum(1 for r in comp if r[2] <= -0.5) / len(comp)
            mc, mr = S.median(r[2] for r in comp), S.median(r[2] for r in rest) if rest else None
            sp = spearman([r[1] for r in comp], [r[2] for r in comp])
            w.update({'measurable': True,
                      'B1_share_deeper_than_spx': round(b1, 4), 'B1_holds': b1 >= 2 / 3,
                      'B2_share_halved': round(b2, 4), 'B2_holds': b2 >= 1 / 3,
                      'B3_median_mdd_comp_pct': round(mc * 100, 1), 'B3_median_mdd_rest_pct': round(mr * 100, 1) if mr is not None else None,
                      'B3_holds': (mr is not None and mc > mr),
                      'B4_spearman_cagr_mdd': round(sp, 4), 'B4_holds': abs(sp) < 0.2})
        else:
            w['measurable'] = False
        wins.append(w)
    verd = {}
    for k in ('B1', 'B2', 'B3', 'B4'):
        meas = [w for w in wins if w.get('measurable')]
        h = sum(1 for w in meas if w[f'{k}_holds'])
        n = len(meas)
        if n == 0:
            v = '測れない'
        elif h >= n * 5 / 6:
            v = '成り立つ'
        elif h <= n / 6:
            v = '成り立たない'
        else:
            v = '時代で変わる'
        verd[k] = {'holds_windows': h, 'measurable_windows': n, 'verdict': v,
                   'failed_starts': [w['start'] for w in meas if not w[f'{k}_holds']]}
    return {'fetch_status': cnt, 'load_issue': load_issue, 'not_equity': not_equity, 'duplicate_month_bars': dups,
            'n_series_used': len(series), 'guards': {'G3': g3}, 'windows': wins, 'verdicts': verd,
            'bridge_2013': next((w for w in wins if w['start'] == 2013), None)}


def main():
    pre = json.load(open(PREREG))
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/longrun1990.py', 'prereg': 'out/longrun1990_prereg.json',
           'prereg_commit': '4dc44296', 'prereg_title': pre['title']}
    out['A'] = part_a()
    if '--only-a' not in sys.argv:
        out['B'] = part_b()
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    A = out['A']
    print('G1', A['guards']['G1'])
    print('G2', A['guards']['G2'])
    for tid, r in A['tests'].items():
        v = r['series']['vw']
        s0, s1, s2 = v['stats']['P0'], v['stats']['H1'], v['stats']['H2']
        e = r['series']['ew']
        print(f"{tid:5} {r['predict']:10} VW P0 {s0.get('mean_ann_pct'):+7.2f}%(t{s0.get('t'):+5.2f}) "
              f"H1 {s1.get('mean_ann_pct'):+6.2f}(t{s1.get('t'):+5.2f}) H2 {s2.get('mean_ann_pct'):+6.2f}(t{s2.get('t'):+5.2f}) "
              f"holm {v['holm_p']} → {v['verdict']} ／ EW → {e['verdict']}")
    if 'B' in out and 'verdicts' in out['B']:
        print('B', json.dumps(out['B']['verdicts'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
